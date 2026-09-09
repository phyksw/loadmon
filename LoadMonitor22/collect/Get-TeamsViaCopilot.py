# -*- coding: utf-8 -*-
"""
Get-TeamsViaCopilot.py — 팀즈 채팅을 M365 Copilot 무개입 왕복으로 추출한다.

Graph API가 회사 정책(사용자 동의 제한·device code 차단)으로 막혀도 동작한다 —
M365 Copilot은 테넌트(내 팀즈 채팅) 데이터에 접근할 수 있고, tools\\copilot_auto.py 가
전용 Edge 프로필로 자동 왕복한다(최초 1회 로그인만 필요).

  python collect\\Get-TeamsViaCopilot.py --from 2026-05-19 --to 2026-08-17

출력: data\\m365\\teams_copilot.csv  (time,from,chat,kind,replied_time,summary)
      kind: order(업무요청) / sent(내 발신) / msg(일반수신)
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

if __name__ == "__main__":      # import 시(파서 재사용·테스트) stdout을 건드리지 않는다
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WIN = 0x08000000


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def build_prompt(d0, d1, alt=False):
    # alt=검색형 화법: '조회해서 전부 출력'(일괄 내보내기)을 회사 Copilot이 "조회 불가" 한마디로
    # 거절하는 경우가 실측됨 — 같은 내용을 '검색해서 찾은 것만 정리' 화법으로 다시 묻는다.
    head = (f"내 Microsoft Teams 채팅에서 {d0}~{d1} 기간에 주고받은 메시지를 검색해줘. "
            "찾은 메시지를 아래 CSV 형식 표로만 정리해줘(찾은 만큼만). 헤더 포함, 다른 설명 없이, "
            "코드 블록(```)으로:\n") if alt else (
            f"{d0}부터 {d1}까지 내 Microsoft Teams 채팅 메시지를 조회해서 아래 CSV 형식으로만 "
            "출력해줘. 헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n")
    return (head +
            "time,from,chat,kind,replied_time,summary\n"
            "- time / replied_time : YYYY-MM-DD HH:MM (응답 안 했으면 replied_time 은 미응답)\n"
            "- chat : 대화방 이름 또는 상대 이름\n"
            "- kind : 내가 보낸 메시지면 sent, 나에게 온 업무 요청(요청·검토·부탁·송부·확인·회신)이면 order, "
            "그 외 수신이면 msg\n"
            "- summary : 메시지 요지 한 줄 (마지막 칸이라 쉼표가 있어도 됨)\n"
            '- 칸 안에 쉼표가 들어가면 그 칸을 따옴표("...")로 감싸\n'
            "- 단체 공지·봇 알림은 제외\n"
            "- 기간 안의 모든 대화 상대·대화방을 빠짐없이 뒤져서 최대 150행까지 출력\n"
            "- 조회 결과가 정말 없으면 '없음' 한 단어만 출력\n"
            "★ 실제로 검색된 메시지만 출력하라 — 예시·가상·추정으로 행을 만들지 마라. "
            "검색이 안 되거나 확실하지 않은 행은 빼라. 행 수를 채우는 것보다 진짜만 적는 것이 중요하다.\n")


# 표가 없을 때 응답의 의미 구분 (실측 스크린샷: 회사 Copilot이 "조회 불가" 한마디로 거절)
#   unable = 기능/권한상 검색 자체가 안 됨 → 재질의 무의미, 2조각 연속이면 전체 중단
#   empty  = 검색은 됐는데 그 기간에 메시지가 없음 → 다음 조각으로
UNABLE_MARKS = ("조회 불가", "조회가 불가", "조회할 수 없", "검색할 수 없", "검색이 불가",
                "액세스할 수 없", "접근할 수 없", "권한이 없", "지원되지 않", "지원하지 않",
                "제공되지 않", "cannot search", "can't search", "unable to", "no access",
                "don't have access",
                # 실측(2026-08-21 스크린샷): "현재 연결된 Microsoft Teams 데이터 조회 도구가
                # 없어…" — 테넌트에 Teams 커넥터 자체가 없는 유형. 재시도 무의미(구조적 불가).
                "조회 도구가 없", "데이터 조회 도구", "연결된 도구가 없", "도구가 없어",
                "no connected tool", "not connected to teams")
EMPTY_MARKS = ("없음", "찾을 수 없", "검색 결과가 없", "메시지가 없", "no messages",
               "couldn't find", "could not find")


def _reply_status(reply):
    """표 행이 0건일 때 응답 분류 → 'unable' | 'empty' | 'other'"""
    low = (reply or "").strip().lower()
    if any(m in low for m in UNABLE_MARKS):
        return "unable"
    if any(m in low for m in EMPTY_MARKS):
        return "empty"
    return "other"


def parse_rows(reply):
    """CSV/마크다운 표 관용 파싱 — summary가 마지막 칸이라 쉼표 포함 안전"""
    rows = []
    for ln in reply.splitlines():
        raw = ln.strip().strip("`").strip()
        if not raw or re.match(r"^time\s*[,|]", raw, re.I) or re.match(r"^\|?[-\s|]+$", raw):
            continue
        if raw.startswith("|"):
            cells = [c.strip() for c in raw.strip("|").split("|")]
        else:
            try:                                    # 따옴표로 감싼 칸의 쉼표를 올바로 처리
                parts = [c.strip() for c in next(csv.reader([raw]))]
            except (csv.Error, StopIteration):
                parts = [c.strip() for c in raw.split(",")]
            if len(parts) > 6:
                # 따옴표 없는 쉼표(대화방 이름·참여자 목록)로 열이 밀리면 kind/replied_time
                # 이 뒤바뀐다(검증 확정) — kind 어휘(order/sent/msg)를 앵커로 재조립한다.
                kidx = next((k for k in range(3, len(parts) - 1)
                             if parts[k] in ("order", "sent", "msg")), None)
                if kidx is not None and kidx + 1 < len(parts):
                    parts = [parts[0], parts[1], ",".join(parts[2:kidx]), parts[kidx],
                             parts[kidx + 1], ",".join(parts[kidx + 2:])]
                else:
                    parts = parts[:5] + [",".join(parts[5:])]
            cells = parts
        if len(cells) >= 6 and re.match(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", cells[0]):
            rows.append(cells[:6])
    return rows


def _norm_time(s):
    """'2026-06-03 9:05' / '2026-06-03T14:00:00Z' / '2026/06/03 오후 2:10' / '2026.06.03' → 'YYYY-MM-DD HH:MM'.
    날짜만 있으면 12:00(정오) — 00:00 으로 두면 분석기가 '새벽 발신' 야간 산출물로 세고(실측), 버리면 그날 흔적이 사라진다.
    시각이 이상하면 빈 문자열(호출측이 행을 버린다)."""
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\.?"
                 r"(?:[ T]+(?:(오전|오후|AM|PM|am|pm)\s*)?(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s*(AM|PM|am|pm)?\s*Z?)?\s*$",
                 (s or "").strip())
    if not m:
        return ""
    y, mo, d, k1, hh, mm, k2 = m.groups()
    try:
        day = datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""
    if hh is None:
        return day + " 12:00"
    h = int(hh)
    ap = (k1 or k2 or "").upper()
    if ap in ("PM", "오후") and h < 12:
        h += 12
    if ap in ("AM", "오전") and h == 12:
        h = 0
    if h > 23 or int(mm) > 59:
        return ""
    return f"{day} {h:02d}:{mm}"


def self_names(cfg=None):
    """본인 판정 이름 집합(소문자·공백 제거 변형 포함): config.teamsSelfNames + owner + 윈도우 계정 + 나/You/본인.
    Copilot 이 '내가 보낸' 행을 kind=msg 로 적고 from 에 내 이름을 넣는 경우를 로컬에서 바로잡는다(프롬프트엔 넣지 않는다)."""
    if cfg is None:
        try:
            with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    names = list(cfg.get("teamsSelfNames") or []) + [cfg.get("owner") or "", os.environ.get("USERNAME", ""),
                                                      "나", "본인", "you", "me"]
    out = set()
    for x in names:
        v = str(x or "").strip().lower()
        if v:
            out.add(v)
            out.add(re.sub(r"\s+", "", v))
    return out


def _is_self(frm, names):
    f = (frm or "").strip().lower()
    if not f:
        return False
    f2 = re.sub(r"\s*(님|씨)$", "", f)
    return any(c in names for c in (f, re.sub(r"\s+", "", f), f2, re.sub(r"\s+", "", f2)))


def normalize_rows(rows, names=None):
    """parse_rows 결과 정리: time/replied_time 을 'YYYY-MM-DD HH:MM' 으로(못 읽는 time 은 행 제외),
    kind 어휘 밖이면 msg, 본인 이름이 from 이면 sent. → (행 목록, {'bad_time': n, 'date_only': n, 'self_sent': n})"""
    names = self_names() if names is None else names
    out, st = [], {"bad_time": 0, "date_only": 0, "self_sent": 0}
    for r in rows:
        r = list(r[:6]) + [""] * (6 - len(r))
        t = _norm_time(r[0])
        if not t:
            st["bad_time"] += 1
            continue
        if not re.search(r"[ T]\d", (r[0] or "").strip()):
            st["date_only"] += 1
        r[0] = t
        kind = (r[3] or "").strip().lower()
        if kind not in ("order", "sent", "msg"):
            kind = "msg"
        if kind != "order" and _is_self(r[1], names):
            if kind != "sent":
                st["self_sent"] += 1
            kind = "sent"
        r[3] = kind
        rt = (r[4] or "").strip()
        r[4] = _norm_time(rt) or ("미응답" if (not rt or rt in ("미응답", "-", "없음", "none", "None")) else rt)
        out.append(r)
    return out, st


def _timeout():
    """자식(copilot_auto)의 재시도 사다리 예산에 맞춘 타임아웃 (judge.roundtrip_timeout 과 동일 규칙)"""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            sec = float(((json.load(f).get("copilotAuto") or {}).get("replyTimeoutSec")) or 240)
    except (OSError, ValueError, TypeError):
        sec = 240.0
    return max(900.0, sec * 3 + 180)


def _one_slice(s0, s1, alt=False):
    """한 조각(<=30일) 왕복 → (행 목록, 상태) — 상태: table|unable|empty|other"""
    prompt = build_prompt(s0, s1, alt)
    tf = os.path.join(ROOT, "data", "teams_prompt.txt")
    os.makedirs(os.path.dirname(tf), exist_ok=True)
    with open(tf, "w", encoding="utf-8") as f:
        f.write(prompt)
    # 타임아웃이 예외로 터지면 조각 루프 전체가 죽어 앞서 모은 행이 전량 소실된다 —
    # 반드시 이 조각만 실패로 처리한다. 타임아웃 값도 자식의 재시도 예산(최소 900s)에 맞춘다.
    try:
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"),
                              "--send", tf], capture_output=True, timeout=_timeout(), cwd=ROOT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
    except subprocess.TimeoutExpired:
        print(f"[teams-copilot]   {s0}~{s1}: 왕복 시간 초과 — 이 조각 건너뜀")
        return [], "other"
    except OSError as e:
        print(f"[teams-copilot]   {s0}~{s1}: 드라이버 실행 실패({type(e).__name__})")
        return [], "other"
    txt = (out.stdout or b"").decode("utf-8", "replace").strip()
    try:
        res = json.loads(txt.splitlines()[-1])
    except Exception:
        print(f"[teams-copilot]   {s0}~{s1}: 드라이버 응답 해석 실패")
        return [], "other"
    if not res.get("ok"):
        print(f"[teams-copilot]   {s0}~{s1}: 실패 — {res.get('error', '')}")
        return [], "other"
    if res.get("retry"):
        print(f"[teams-copilot]   {s0}~{s1}: {res['retry']}")
    reply = res.get("reply", "")
    try:                                    # 원문 응답 보존 — '왜 1건뿐인가'를 진단할 수 있게
        rd = os.path.join(ROOT, "data", "m365", "replies")
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, f"teams_{s0}_{s1}.txt"), "w", encoding="utf-8") as f:
            f.write(reply)
    except OSError:
        pass
    rows, st = normalize_rows(parse_rows(reply))
    if st["bad_time"] or st["date_only"] or st["self_sent"]:
        print(f"[teams-copilot]   {s0}~{s1}: 시각 정리 — 형식 오류 제외 {st['bad_time']}행, "
              f"날짜만(12:00 배정) {st['date_only']}행, 본인 이름 → sent {st['self_sent']}행")
    # 환각 방어: 요청 구간 밖 날짜의 행은 LLM이 지어냈거나 잘못 검색한 것 — 버리고 알린다.
    # (형식 검사만으로는 '그럴듯한 가짜 행'을 못 거른다 — 진위 감사에서 확인된 위험)
    good = [r for r in rows if s0 <= r[0][:10] <= s1]
    if len(good) < len(rows):
        print(f"[teams-copilot]   {s0}~{s1}: 기간 밖 날짜 {len(rows) - len(good)}행 제외 (환각/오검색 의심)")
    return good, ("table" if good else _reply_status(reply))


def _save_rows(rows):
    """지금까지 모은 행을 즉시 CSV 로 — 부모(run.py) 타임아웃·강제 종료가 와도
    이미 회수한 조각은 잃지 않는다(검증 확정: 끝에서 한 번만 쓰면 전량 소실)."""
    dst = os.path.join(ROOT, "data", "m365", "teams_copilot.csv")
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    def esc(s):
        s = re.sub(r"[\r\n]+", " ", str(s or ""))
        return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s

    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        f.write("time,from,chat,kind,replied_time,summary\n")
        for r in rows:
            f.write(",".join([esc(c) for c in r[:6]]) + "\n")
    return dst


def sub_slices(s0, s1, days=10):
    """조각을 10일 하위 조각으로 재분할 (재질의용)"""
    a = datetime.strptime(s0, "%Y-%m-%d")
    b = datetime.strptime(s1, "%Y-%m-%d")
    outs = []
    cur = a
    while cur <= b:
        end = min(cur + timedelta(days=days - 1), b)
        outs.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        cur = end + timedelta(days=1)
    return outs


def need_subdivide(n_rows, span_days):
    """회수가 빈약하거나(누락 의심) 표가 컸으면(잘림 의심) 짧은 조각으로 다시 묻는다"""
    return span_days > 12 and (n_rows < 5 or n_rows >= 35)


UNAVAILABLE_FLAG = os.path.join(ROOT, "data", "m365", "teams_copilot_unavailable.json")


def main():
    d0 = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1 = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    # 이 계정의 Copilot 이 팀즈 조회 자체를 못 한다고 전에 확인됐으면(테넌트에 Teams
    # 커넥터 부재 — 실측) 분석 때마다 수십 분 헛왕복하지 않는다. 회사가 커넥터를 켜준 뒤
    # 다시 시도하려면 --retry-copilot 을 붙이거나 플래그 파일을 지우면 된다.
    if os.path.exists(UNAVAILABLE_FLAG) and "--retry-copilot" not in sys.argv:
        try:
            info = json.load(open(UNAVAILABLE_FLAG, encoding="utf-8-sig"))
        except (OSError, ValueError):
            info = {}
        print(f"[teams-copilot] 이 계정의 Copilot 은 팀즈 조회 불가로 확인됨({info.get('when', '?')}) — 왕복 생략")
        print("               팀즈는 상시 샘플러(collect\\Start-TeamsSampler.ps1)로 따로 모으세요.")
        print("               (커넥터가 생겨 재시도하려면: --retry-copilot 또는 "
              "data\\m365\\teams_copilot_unavailable.json 삭제)")
        return 1
    # 90일 통짜 요청은 응답이 잘리거나 '응답할 수 없습니다'가 잦다(실측 — 팀즈 데이터 누락의
    # 주원인). 30일 조각으로 나눠 왕복하고 합친다. 각 왕복은 재시도 사다리의 보호를 받는다.
    t0 = datetime.strptime(d0, "%Y-%m-%d")
    t1 = datetime.strptime(d1, "%Y-%m-%d")
    slices = []
    cur = t0
    while cur <= t1:
        end = min(cur + timedelta(days=29), t1)
        slices.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        cur = end + timedelta(days=1)
    print(f"[teams-copilot] {d0}~{d1} → {len(slices)}조각 왕복 (30일 단위) — 조각당 수십 초")
    rows, seen = [], set()

    def take(batch):
        n = 0
        for r in batch:
            # 중복 키에서 summary 는 뺀다 — 요지는 왕복마다 LLM이 새로 쓰므로 같은 메시지가
            # 재질의에서 다른 요약으로 돌아오면 중복 유입된다.
            # 다만 대화방(chat)은 넣는다 — (시각,발신자)만으로 좁히면 같은 분에 다른 방으로
            # 보낸 별개 메시지가 통째로 사라진다(실측: 4건 중 2건 소실).
            k = (r[0], r[1], r[2])
            if k not in seen:                # 조각 경계·재질의 중복 제거
                seen.add(k)
                rows.append(r)
                n += 1
        return n

    alt_mode = False        # '조회 불가' 후 검색형 화법으로 전환됐는지
    fails = 0               # 표를 못 얻은 조각 수(유형 무관) — 연속이 아니라 '누적'으로 센다.
    #                         연속 카운터는 unable↔other 가 섞이면 계속 초기화돼 끝까지
    #                         물어보게 되고, 그 사이 판정용 Copilot 세션이 소진된다(실측).
    for i, (s0, s1) in enumerate(slices):
        print(f"[teams-copilot] {i + 1}/{len(slices)} 조각 {s0}~{s1}")
        got, st = _one_slice(s0, s1, alt_mode)
        if st == "unable" and not alt_mode:
            # 실측(스크린샷): 회사 Copilot이 "조회 불가" 한마디로 거절 — 일괄 내보내기 화법이
            # 원인일 수 있어 검색형 화법으로 같은 조각을 한 번 더 시도한다.
            print("[teams-copilot]   '조회 불가' 응답 — 검색형 화법으로 전환해 재시도")
            alt_mode = True
            got, st = _one_slice(s0, s1, alt_mode)
        if st == "unable":
            # 커넥터 부재는 재질의로 해결되지 않는다 — 한 번 확인되면 즉시 접는다
            fails += 1
            if True:
                print("[teams-copilot] 2조각 연속 '조회 불가' — 이 계정의 Copilot은 팀즈 채팅 검색을")
                print("               지원하지 않는 것으로 보고 남은 조각을 생략합니다 (헛왕복 방지).")
                print("               대안: 상시 샘플러(collect\\Start-TeamsSampler.ps1) 또는 config.graph(Graph API)")
                try:                        # 다음 분석부터는 왕복 자체를 생략 (능력 기억)
                    os.makedirs(os.path.dirname(UNAVAILABLE_FLAG), exist_ok=True)
                    with open(UNAVAILABLE_FLAG, "w", encoding="utf-8") as f:
                        json.dump({"when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                   "note": "Copilot 응답이 팀즈 조회 불가 유형(커넥터 부재) — "
                                           "재시도는 --retry-copilot 또는 이 파일 삭제"},
                                  f, ensure_ascii=False, indent=1)
                    print("               (기록됨 — 다음 분석부터 Copilot 팀즈 왕복을 자동 생략합니다)")
                except OSError:
                    pass
                break
            continue
        if st in ("other", "empty") and not got:
            fails += 1
            if fails >= 3:
                print("[teams-copilot] 3조각에서 표를 얻지 못해 중단합니다 — 판정용 Copilot "
                      "세션을 아끼기 위해서입니다.")
                print("               팀즈는 상시 샘플러(collect\\Start-TeamsSampler.ps1)로 모으세요.")
                break
        take(got)
        if st == "empty":
            print("[teams-copilot]   이 조각은 메시지 없음 (재질의 생략)")
            print(f"[teams-copilot]   누적 {len(rows)}건")
            continue
        # 30일 조각이 몇 건만 돌아오거나(검색 누락) 표가 크면(응답 잘림) — 실측 '기간 3개월에
        # 1건'의 원인 — 10일 하위 조각으로 다시 물어 회수율을 끌어올린다.
        span = (datetime.strptime(s1, "%Y-%m-%d") - datetime.strptime(s0, "%Y-%m-%d")).days + 1
        if need_subdivide(len(got), span):
            why = "회수 부족" if len(got) < 5 else "잘림 의심"
            print(f"[teams-copilot]   {len(got)}건 ({why}) → 10일 조각 재질의")
            for t0s, t1s in sub_slices(s0, s1):
                add = take(_one_slice(t0s, t1s, alt_mode)[0])
                print(f"[teams-copilot]     {t0s}~{t1s}: +{add}건")
        if rows:
            _save_rows(rows)               # 증분 저장 — 부모 타임아웃이 와도 회수분 보존
        print(f"[teams-copilot]   누적 {len(rows)}건" + (" (증분 저장됨)" if rows else ""))
    if not rows:
        print("[teams-copilot] 전 조각에서 표를 얻지 못함 — Copilot이 팀즈 검색을 지원하지 않는")
        print("               계정이거나 기간에 채팅이 없을 수 있음 (창 읽기 폴백이 이어집니다)")
        print("               실제 응답 원문은 data\\m365\\replies\\ 에서 확인할 수 있습니다")
        return 1
    _save_rows(rows)
    if os.path.exists(UNAVAILABLE_FLAG):    # 재시도가 성공했으면 '불가' 기록을 해제
        try:
            os.remove(UNAVAILABLE_FLAG)
            print("[teams-copilot] 팀즈 조회가 다시 가능해짐 — '불가' 기록 해제")
        except OSError:
            pass
    kinds = {}
    for r in rows:
        kinds[r[3]] = kinds.get(r[3], 0) + 1
    print(f"[teams-copilot] {len(rows)}건 저장 ({', '.join(f'{k} {v}' for k, v in kinds.items())}))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
