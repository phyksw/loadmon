# -*- coding: utf-8 -*-
"""
Get-TeamsChats.py — Microsoft Graph로 '내 팀즈 채팅'을 직접 수집 (device code flow, 표준 라이브러리만).

팀즈로 내려오는 업무 오더가 통째로 누락되는 문제를 Copilot 수동 추출이 아니라 API로 해결한다.

사용:
  python collect\\Get-TeamsChats.py --from 2026-05-19 --to 2026-08-17
  python collect\\Get-TeamsChats.py --login-only          # 토큰만 먼저 받아두기
  python collect\\Get-TeamsChats.py --status              # 설정·토큰 상태 확인

설정(config\\config.json):
  "graph": {
    "clientId": "<Entra 앱 등록 후 애플리케이션(클라이언트) ID>",
    "tenantId": "organizations",           // 또는 회사 테넌트 GUID
    "scopes": ["Chat.Read", "User.Read", "offline_access"]
  }
앱 등록은 1회만: Entra 포털 > 앱 등록 > 새 등록 > 지원 계정 유형 '내 조직 디렉터리만' >
  플랫폼 추가 > 모바일 및 데스크톱 > '공용 클라이언트 흐름 허용' 사용 > 클라이언트 ID 복사.
(테넌트가 사용자 앱 등록을 막아둔 경우 관리자에게 위 앱 1개 생성만 요청하면 된다 —
 위임 권한 Chat.Read 는 본인 채팅만 읽는다.)

출력: data\\m365\\teams_chats.csv  (time,from,summary,replied_time,chat,kind)
      — 기존 teams_orders*.csv 와 같은 스키마라 분석기가 그대로 인제스트한다.
      time 은 이 PC 의 로컬 시각(Graph 의 createdDateTime 은 UTC '…Z' — 그대로 적으면 9시간 밀려
      낮 발신이 새벽 '야간 산출물'이 됐다). since/until 도 로컬 자정을 UTC 로 바꿔 비교한다.
      채팅방·메시지는 since 에 닿을 때까지 페이지를 넘기고(서버 필터 $filter=lastModifiedDateTime gt since),
      안전 상한에 걸리면 '미수집' 경고를 낸다. 총 시간 예산(기본 240초) 안에서만 돈다.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

LOCAL_TZ = None     # None = 이 PC 의 시스템 시간대(astimezone() 기본, DST 반영). 테스트에서 고정 tz 로 바꿀 수 있다

if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽의 stdout 이
    # 교체·GC 되면서 버퍼가 닫혀 이후 출력이 전부 죽는다(run.py 와 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, "config", "config.json")
TOKEN_PATH = os.path.join(ROOT, "data", "graph_token.json")
OUT_DIR = os.path.join(ROOT, "data", "m365")
GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = ["Chat.Read", "User.Read", "offline_access"]


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def graph_cfg():
    g = (load_cfg().get("graph") or {})
    return (g.get("clientId", "").strip(), g.get("tenantId", "organizations").strip() or "organizations",
            g.get("scopes") or DEFAULT_SCOPES)


def post_form(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read().decode("utf-8"))
        except Exception:
            return None, {"error": f"http_{e.code}"}


def get_json(url, token, timeout=30):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def save_token(tok):
    tok["_expires_at"] = time.time() + float(tok.get("expires_in", 3600)) - 120
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tok, f)
    os.replace(tmp, TOKEN_PATH)
    try:                      # 토큰 파일은 본인만 (다른 사용자 읽기 차단)
        import subprocess
        subprocess.run(["icacls", TOKEN_PATH, "/inheritance:r", "/grant:r",
                        f"{os.environ.get('USERNAME', '')}:F"],
                       capture_output=True, timeout=15, creationflags=0x08000000)
    except Exception:
        pass


def load_token():
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def acquire_token(interactive=True):
    """저장된 토큰 → 만료면 refresh → 없으면 device code flow"""
    client_id, tenant, scopes = graph_cfg()
    if not client_id:
        return None, ("config.json 의 graph.clientId 가 비어 있습니다 — 파일 상단 주석의 앱 등록 절차를 "
                      "1회 수행한 뒤 클라이언트 ID를 넣으세요.")
    tok = load_token()
    if tok.get("access_token") and tok.get("_expires_at", 0) > time.time():
        return tok["access_token"], None
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    if tok.get("refresh_token"):
        new, err = post_form(base + "/token", {
            "client_id": client_id, "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"], "scope": " ".join(scopes)})
        if new and new.get("access_token"):
            save_token(new)
            return new["access_token"], None
    if not interactive:
        return None, ("Graph 토큰 없음/만료 — 콘솔에서 "
                      "'python collect\\Get-TeamsChats.py --login-only' 을 1회 실행해 로그인하세요 "
                      "(분석 중에는 로그인 입력을 기다리지 않고 건너뜁니다)")
    dc, err = post_form(base + "/devicecode",
                        {"client_id": client_id, "scope": " ".join(scopes)})
    if not dc:
        return None, f"device code 요청 실패: {err}"
    print("\n" + "=" * 64)
    print(dc.get("message") or
          f"{dc.get('verification_uri')} 에서 코드 {dc.get('user_code')} 를 입력하세요")
    print("=" * 64 + "\n(브라우저에서 회사 계정으로 승인하면 자동으로 진행됩니다)\n")
    deadline = time.time() + int(dc.get("expires_in", 900))
    interval = int(dc.get("interval", 5))
    while time.time() < deadline:
        time.sleep(interval)
        got, err = post_form(base + "/token", {
            "client_id": client_id, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dc["device_code"]})
        if got and got.get("access_token"):
            save_token(got)
            print("[graph] 로그인 완료 — 토큰 저장됨 (이후 자동 갱신)")
            return got["access_token"], None
        code = (err or {}).get("error", "")
        if code == "authorization_pending":
            continue
        if code == "slow_down":
            interval += 5
            continue
        return None, f"로그인 실패: {code} — {(err or {}).get('error_description', '')[:200]}"
    return None, "로그인 시간 초과"


def strip_html(s):
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", s).strip()


ORDER_HINTS = ("요청", "검토", "부탁", "송부", "확인", "회신", "공유", "전달", "리뷰",
               "please", "review", "asap", "필요", "일정", "언제", "가능")

_FRAC = re.compile(r"\.(\d+)")


def parse_graph_time(raw):
    """Graph 의 createdDateTime('2026-06-01T01:00:00.1234567Z', UTC) → 이 PC 로컬 시각(aware).
    소수 자릿수를 6자리로 맞춘 뒤 fromisoformat — 시간대 표기가 없으면 UTC 로 본다. 못 읽으면 None."""
    s = (raw or "").strip()
    if not s:
        return None
    s = _FRAC.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), s, count=1)
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(LOCAL_TZ)


def local_day(d):
    """'YYYY-MM-DD' → 그 날 00:00 로컬(aware)"""
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ) if LOCAL_TZ else \
        datetime.strptime(d, "%Y-%m-%d").astimezone()


def collect(d0, d1, max_chats=500, max_msgs=None, interactive=True, time_budget=240.0):
    """d0~d1(로컬 날짜) 의 내 채팅을 모아 CSV 로. max_msgs 는 방당 안전 상한(None = 기간 길이 비례, 최소 1000)"""
    token, err = acquire_token(interactive)
    if not token:
        print(f"[graph] {err}")
        return None
    t_start = time.time()
    me = get_json(f"{GRAPH}/me", token)
    my_id = me.get("id", "")
    print(f"[graph] 로그인: {me.get('displayName','')} <{me.get('mail') or me.get('userPrincipalName','')}>")
    since = local_day(d0)
    until = local_day(d1) + timedelta(days=1)
    since_z = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    days = max(1, (until - since).days)
    if not max_msgs:
        max_msgs = max(1000, 50 * days)
    rows = []
    warns = []
    # 채팅방: 마지막 메시지 시각 내림차순으로 받아 since 이전 방이 나오면 멈춘다 — 60개 상한이 아니라 기간이 기준.
    # ($orderby 를 거절하는 테넌트/버전이면 정렬 없이 전부 훑고 lastMessagePreview 로만 거른다)
    ordered = True
    url = (f"{GRAPH}/me/chats?$top=50&$expand=members,lastMessagePreview"
           "&$orderby=lastMessagePreview/createdDateTime%20desc")
    chats, pages = [], 0
    max_pages = max_chats // 50 + 2
    stop = False
    while url and not stop and pages < max_pages:
        pages += 1
        try:
            page = get_json(url, token)
        except urllib.error.HTTPError as e:
            if e.code == 400 and ordered:
                ordered = False
                url = f"{GRAPH}/me/chats?$top=50&$expand=members"
                pages -= 1
                continue
            print(f"[graph] /me/chats 실패 {e.code} — 권한(Chat.Read) 동의 여부 확인")
            return None
        for ch in page.get("value", []):
            last = parse_graph_time(((ch.get("lastMessagePreview") or {}).get("createdDateTime")) or "")
            if last is not None and last < since:
                if ordered:
                    stop = True          # 정렬돼 있으니 이후 방은 전부 기간 밖
                    break
                continue                 # 정렬 없음: 이 방만 건너뜀
            chats.append(ch)
            if len(chats) >= max_chats:
                warns.append(f"채팅방 {max_chats}개 상한 도달 — 더 오래된 방은 미수집(--max-chats 로 상향)")
                stop = True
                break
        url = page.get("@odata.nextLink")
    if url and not stop:
        warns.append(f"채팅방 목록 {pages}페이지 상한 — 이후 방 미수집")
    print(f"[graph] 채팅방 {len(chats)}개 조회 ({d0}~{d1} 안에 메시지가 있을 수 있는 방)")
    filtered = True
    n_budget_left = 0
    for i, ch in enumerate(chats):
        if time.time() - t_start > time_budget:
            n_budget_left = len(chats) - i
            warns.append(f"시간 예산 {int(time_budget)}초 도달 — 채팅방 {n_budget_left}개 미수집(다음 실행 때 재시도)")
            break
        cid = ch.get("id")
        topic = ch.get("topic") or ", ".join(
            (m.get("displayName") or "") for m in (ch.get("members") or [])[:3])[:40]
        base = f"{GRAPH}/chats/{urllib.parse.quote(cid)}/messages?$top=50"
        murl = base + ("&$filter=lastModifiedDateTime%20gt%20" + since_z if filtered else "")
        got, pages = 0, 0
        reached = False                  # since 이전 메시지를 만났거나 페이지가 끝났다 = 기간을 다 덮음
        while murl:
            pages += 1
            try:
                mp = get_json(murl, token)
            except urllib.error.HTTPError as e:
                if e.code == 400 and filtered and pages == 1:
                    filtered = False     # 이 테넌트는 $filter 미지원 — 필터 없이 페이지로만
                    murl = base
                    pages -= 1
                    continue
                if e.code in (403, 404):
                    reached = True
                    break
                raise
            stop = False
            for m in mp.get("value", []):
                t = parse_graph_time(m.get("createdDateTime"))
                if t is None:
                    continue
                if t < since:
                    stop = True
                    break
                if t >= until:
                    continue
                body = strip_html((m.get("body") or {}).get("content", ""))
                if not body or len(body) < 2:
                    continue
                frm = (((m.get("from") or {}).get("user") or {}).get("displayName") or "")
                is_me = (((m.get("from") or {}).get("user") or {}).get("id") or "") == my_id
                kind = "sent" if is_me else ("order" if any(k in body for k in ORDER_HINTS) else "msg")
                rows.append({"time": t.strftime("%Y-%m-%d %H:%M"), "from": frm or ("나" if is_me else ""),
                             "summary": body[:220], "chat": topic, "kind": kind})
                got += 1
            nxt = mp.get("@odata.nextLink")
            if stop or not nxt:
                reached = True
                murl = None
            elif got >= max_msgs:
                murl = None
            else:
                murl = nxt
        if not reached:
            warns.append(f"방 '{topic[:20]}': {got}건 상한 도달(이전 메시지 미수집 — 기간을 나눠 다시 수집)")
    rows.sort(key=lambda r: r["time"])
    # 오더 → 내 응답 리드타임 (같은 채팅방에서 내 다음 발신)
    for i, r in enumerate(rows):
        r["replied_time"] = "미응답"
        if r["kind"] != "order":
            continue
        for nxt in rows[i + 1:]:
            if nxt["chat"] == r["chat"] and nxt["kind"] == "sent":
                r["replied_time"] = nxt["time"]
                break
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "teams_chats.csv")

    def esc(s):
        s = re.sub(r"[\r\n]+", " ", str(s or ""))
        return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s

    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        f.write("time,from,summary,replied_time,chat,kind\n")
        for r in rows:
            f.write(",".join(esc(r[k]) for k in
                             ("time", "from", "summary", "replied_time", "chat", "kind")) + "\n")
    n_order = sum(1 for r in rows if r["kind"] == "order")
    n_sent = sum(1 for r in rows if r["kind"] == "sent")
    print(f"[graph] 메시지 {len(rows)}건 (업무 오더 후보 {n_order}건 · 내 발신 {n_sent}건, 로컬 시각) → {out}")
    for w in warns:
        print(f"[graph] 경고: {w}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default="")
    ap.add_argument("--to", dest="d1", default="")
    ap.add_argument("--login-only", action="store_true")
    ap.add_argument("--status", action="store_true")
    # 분석기(run.py)가 부를 때 쓴다 — 로그인 입력을 기다리며 수집 전체를 멈추지 않게
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--max-chats", type=int, default=500, help="채팅방 안전 상한(기본 500, 도달 시 경고)")
    ap.add_argument("--max-msgs", type=int, default=0, help="방당 메시지 안전 상한(기본 0 = 기간 비례, 최소 1000)")
    ap.add_argument("--time-budget", type=float, default=240.0,
                    help="총 수집 시간 예산(초, 기본 240 — run.py 단계 제한 300초 안)")
    a = ap.parse_args()
    client_id, tenant, scopes = graph_cfg()
    if a.status:
        tok = load_token()
        exp = tok.get("_expires_at", 0)
        print(json.dumps({
            "clientId_설정됨": bool(client_id), "tenant": tenant, "scopes": scopes,
            "토큰": ("유효" if exp > time.time() else ("만료(갱신 가능)" if tok.get("refresh_token") else "없음")),
            "출력파일": os.path.join(OUT_DIR, "teams_chats.csv"),
        }, ensure_ascii=False, indent=1))
        return 0
    if a.login_only:
        tok, err = acquire_token()
        print("[graph] " + ("로그인 OK" if tok else err))
        return 0 if tok else 1
    d0 = a.d0 or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1 = a.d1 or datetime.now().strftime("%Y-%m-%d")
    return 0 if collect(d0, d1, max_chats=max(1, a.max_chats), max_msgs=(a.max_msgs or None),
                        interactive=not a.non_interactive, time_budget=max(30.0, a.time_budget)) else 1


if __name__ == "__main__":
    sys.exit(main())
