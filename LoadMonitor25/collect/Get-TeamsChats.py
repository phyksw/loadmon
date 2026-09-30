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
      마지막 수정일 필터로 후보를 좁히고 생성일로 요청 기간을 검사하며 모든 nextLink를 따른다.
      본문 문맥·원본 ID를 페이지마다 누적한다. 권한 오류·시간·건수 상한은 상태 파일에 부분 수집으로
      기록한다. complete도 승인된 /me/chats 범위의 완주이며 채널 대화는 포함하지 않는다.
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
sys.path.insert(0, os.path.join(ROOT, "core"))
from collection_state import merge_csv, write_status  # noqa: E402

FIELDS = ["time", "from", "summary", "replied_time", "chat", "kind", "context_excerpt",
          "context_truncated", "source_id", "source_kind", "source_url", "conversation_id", "time_precision"]
SCOPE = "Graph /me/chats의 권한 있는 채팅 메시지·요청 생성일 범위; Teams 채널은 포함하지 않음"
CFG_PATH = os.path.join(ROOT, "config", "config.json")
TOKEN_PATH = os.path.join(ROOT, "data", "graph_token.json")
OUT_DIR = os.path.join(ROOT, "data", "m365")
GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = ["Chat.Read", "User.Read", "offline_access"]


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as f:
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
    """페이지마다 원자적으로 누적 저장. 페이지 실패·403·상한은 완주가 아니다."""
    started = time.monotonic()
    deadline = started + max(0.0, time_budget)
    out = os.path.join(OUT_DIR, "teams_chats.csv")
    rows, reasons, completed = [], [], []
    chats, seen_chats, chat_urls = [], set(), set()
    cfg = load_cfg()
    context_chars = max(200, min(20000, int((cfg.get("collection") or {}).get("contextChars") or 4000)))
    since, until = local_day(d0), local_day(d1) + timedelta(days=1)
    # gt 필터의 자정 경계를 포함한 뒤 실제 요청 기간은 createdDateTime으로 검사한다.
    since_z = (since - timedelta(seconds=1)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    max_msgs = max(1, int(max_msgs or max(1000, 50 * max(1, (until - since).days))))
    max_chats = max(1, int(max_chats))

    def status(state="partial", more=()):
        return write_status(ROOT, "teams_graph", d0, d1, status=state, rows=len(rows), scope=SCOPE,
                            reasons=reasons + list(more), completed_units=len(completed),
                            total_units=len(chats), completed_chat_ids=completed)

    status(more=["interrupted"])
    try:
        token, err = acquire_token(interactive)
    except Exception as ex:
        status("failed", ["authentication_error:" + type(ex).__name__])
        return None
    if not token:
        print(f"[graph] {err}")
        status("blocked", ["login_or_configuration_required"])
        return None
    try:
        me = get_json(f"{GRAPH}/me", token)
    except Exception as ex:
        status("blocked" if isinstance(ex, urllib.error.HTTPError) and ex.code in (401, 403) else "failed",
               ["identity_request_failed:" + str(getattr(ex, "code", type(ex).__name__))])
        return None
    my_id = me.get("id", "") if isinstance(me, dict) else ""
    if not my_id:
        status("failed", ["identity_missing"])
        return None
    url = f"{GRAPH}/me/chats?$top=50&$expand=members"
    while url:
        if time.monotonic() >= deadline:
            reasons.append("time_budget")
            break
        if url in chat_urls:
            reasons.append("chat_page_repeated")
            break
        chat_urls.add(url)
        try:
            page = get_json(url, token, timeout=max(1, min(30, deadline - time.monotonic())))
        except Exception as ex:
            reasons.append("chat_list_failed:" + str(getattr(ex, "code", type(ex).__name__)))
            break
        if not isinstance(page, dict) or not isinstance(page.get("value"), list):
            reasons.append("chat_list_invalid")
            break
        capped = False
        for ch in page["value"]:
            if not isinstance(ch, dict):
                reasons.append("chat_invalid")
                continue
            cid = str(ch.get("id") or "")
            if not cid:
                reasons.append("chat_id_missing")
                continue
            if cid in seen_chats:
                continue
            if len(chats) >= max_chats:
                capped = True
                break
            seen_chats.add(cid)
            chats.append(ch)
        url = page.get("@odata.nextLink")
        if capped or (url and len(chats) >= max_chats):
            reasons.append("chat_limit")
            break
    for ch in chats:
        if time.monotonic() >= deadline:
            reasons.append("time_budget")
            break
        cid = str(ch["id"])
        topic = ch.get("topic") or ", ".join((m.get("displayName") or "") for m in (ch.get("members") or [])[:3])[:120]
        base = f"{GRAPH}/chats/{urllib.parse.quote(cid, safe='')}/messages?$top=50"
        murl = base + "&$filter=lastModifiedDateTime%20gt%20" + since_z
        filtered_url = murl
        visited, scanned, seen_messages = set(), 0, set()
        while murl:
            if time.monotonic() >= deadline:
                reasons.append("time_budget")
                break
            if murl in visited:
                reasons.append("message_page_repeated")
                break
            visited.add(murl)
            try:
                page = get_json(murl, token, timeout=max(1, min(30, deadline - time.monotonic())))
            except Exception as ex:
                if isinstance(ex, urllib.error.HTTPError) and ex.code == 400 and murl == filtered_url:
                    murl = base  # 필터를 지원하지 않으면 원래 권한 범위에서 페이지를 계속 읽는다.
                    continue
                reasons.append("messages_failed:" + str(getattr(ex, "code", type(ex).__name__)))
                break
            if not isinstance(page, dict) or not isinstance(page.get("value"), list):
                reasons.append("messages_invalid")
                break
            batch, capped = [], False
            for m in page["value"]:
                if not isinstance(m, dict):
                    reasons.append("message_invalid")
                    continue
                mid = str(m.get("id") or "")
                if mid and mid in seen_messages:
                    continue
                if scanned >= max_msgs:
                    capped = True
                    break
                scanned += 1
                if mid:
                    seen_messages.add(mid)
                t = parse_graph_time(m.get("createdDateTime"))
                if t is None:
                    reasons.append("message_time_unreadable")
                    continue
                # Graph의 기본 정렬은 createdDateTime 순서라는 보장이 없다. 오래된 한 건으로 멈추지 않는다.
                if not (since <= t < until):
                    continue
                body = strip_html((m.get("body") or {}).get("content", ""))
                if not body:
                    continue
                user = (m.get("from") or {}).get("user") or {}
                is_me = user.get("id") == my_id
                kind = "sent" if is_me else ("order" if any(k in body for k in ORDER_HINTS) else "msg")
                batch.append({"time": t.strftime("%Y-%m-%d %H:%M"), "from": user.get("displayName") or ("나" if is_me else ""),
                              "chat": topic, "kind": kind, "summary": body[:200], "replied_time": "",
                              "context_excerpt": body[:context_chars], "context_truncated": str(len(body) > context_chars).lower(),
                              "source_id": "graph:" + cid + "/" + mid if mid else "", "source_kind": "teams_graph",
                              "source_url": str(m.get("webUrl") or ""), "conversation_id": cid, "time_precision": "minute"})
            rows.extend(batch)
            if batch:
                merge_csv(out, batch, FIELDS, kind="teams")
            status(more=["interrupted"])
            murl = page.get("@odata.nextLink")
            if capped or (murl and scanned >= max_msgs):
                reasons.append("message_limit")
                break
            if not murl:
                completed.append(cid)
    reasons[:] = list(dict.fromkeys(reasons))
    if reasons:
        state = "partial" if chats or rows else "failed"
    else:
        state = "complete"
    # 정상 0건과 조회 실패 0건을 구분한다. 기존 수집 행은 어느 경우도 지우지 않는다.
    if state == "complete" or rows:
        merge_csv(out, [], FIELDS, kind="teams")
    status(state)
    print(f"[graph] {len(rows)}건 · {state} · " + ", ".join(reasons))
    return out if state == "complete" or rows else None


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
