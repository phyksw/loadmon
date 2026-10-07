# -*- coding: utf-8 -*-
"""
Get-TeamsViaCopilot.py — 팀즈 채팅을 M365 Copilot 무개입 왕복으로 추출한다.

Graph API가 회사 정책(사용자 동의 제한·device code 차단)으로 막혀도 동작한다 —
M365 Copilot은 테넌트(내 팀즈 채팅) 데이터에 접근할 수 있고, tools\\copilot_auto.py 가
전용 Edge 프로필로 자동 왕복한다(최초 1회 로그인만 필요).

  python collect\\Get-TeamsViaCopilot.py --from 2026-05-19 --to 2026-08-17
  python collect\\Get-TeamsViaCopilot.py --ranges 2026-03-02:2026-03-08,2026-04-01      (run.py 가 팀즈 미관측일만)

출력: data\\m365\\teams_copilot.csv  (time,from,chat,kind,replied_time,summary)
      kind: order(업무요청) / sent(내 발신) / msg(일반수신)

LM28(W1-13·W1-17·W2-12):
  · --ranges 'A:B,C~D,E'(또는 '@파일') — 다른 출처가 못 본 날만 묻는다(Get-MailViaCopilot.parse_ranges 와 같은 규칙). 없으면 --from~--to.
  · 왕복은 copilot_auto.send_inproc(같은 프로세스 — 조각마다 파이썬을 띄우지 않는다). G3 관문에 막힌 조각은 보내지 않은 것으로 둔다.
  · 저장은 teams_parse.merge_keep_outside — 표를 받은 조각 기간의 옛 행만 이번 행으로 바꾸고 그 밖의 옛 행은 둔다
    (LM24 는 이번 기간 행만 'w' 로 써서 짧은 기간으로 다시 돌리면 다른 기간 자료가 사라졌다).
  · '조회 불가'는 서로 다른 날 2회일 때만 14일 동안 생략한다(TTL — 메일 Copilot 과 같은 규칙. LM24 의 'if True' 는 한 번의
    거절로 영구 생략했다). 로그인 같은 '사람이 풀 실패'는 불가로 기록하지 않는다. 드라이버 무응답만 연속 4번이면 멈춘다.
  · 마지막 줄: LMSTATUS {v,src:'teams_copilot',rc,reason,counts,ranges} — rc 0 표를 받음(또는 '없음' 답) · 2 로그인 ·
    3 불가(R-UNABLE·R-NOREPLY·R-GATE·Edge 사유). ranges(axis teams)의 st 는 표를 받은 조각 partial(증인 — '읽음'이 아니다)
    · 그 밖 unverified.
"""
import csv
import importlib.util
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

if __name__ == "__main__":      # import 시(파서 재사용·테스트) stdout을 건드리지 않는다
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import teams_parse  # noqa: E402  — LM28 병합(merge_keep_outside)
OUT_DIR = os.path.join(ROOT, "data", "m365")
HDR = "time,from,chat,kind,replied_time,summary"
ERR_MAX = 4                     # 드라이버가 답을 못 받은 조각이 연속 이만큼이면 멈춘다(판정용 세션 보호 — 메일 Copilot 과 같다)
FATAL_PHASES = ("login_required", "edge_not_found", "launch_failed", "input_not_found")
LAST_FATAL = {}                 # 마지막 '사람이 풀 실패'의 phase·reason(LMSTATUS 사유)
_MVC = {}


def _mvc():
    """메일 Copilot 수집기 모듈 — '조회 불가' 기억(unable_*)·--ranges 해석을 같은 규칙으로 쓴다(WP2)."""
    if "m" not in _MVC:
        spec = importlib.util.spec_from_file_location("_mvc", os.path.join(_HERE, "Get-MailViaCopilot.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MVC["m"] = m
    return _MVC["m"]


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
    """한 조각 왕복의 마감(초) — copilot_auto 재시도 사다리 예산에 맞춘다(judge.roundtrip_timeout 과 동일 규칙)"""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            sec = float(((json.load(f).get("copilotAuto") or {}).get("replyTimeoutSec")) or 240)
    except (OSError, ValueError, TypeError):
        sec = 240.0
    return max(900.0, sec * 3 + 180)


_CA = {}


def _ca():
    """copilot_auto 모듈(같은 프로세스) — 처음 쓸 때 한 번 불러온다(시험이 _send 를 바꾸면 불리지 않는다)."""
    if "m" not in _CA:
        tools = os.path.join(ROOT, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import copilot_auto
        _CA["m"] = copilot_auto
    return _CA["m"]


def _send(prompt):
    """한 조각 왕복 — copilot_auto.send_inproc(LM28 W2-12: 조각마다 copilot_auto.py 를 자식 프로세스로 띄우지 않는다).
    결과 dict 는 --send 의 JSON 과 같다."""
    return _ca().send_inproc(prompt, fresh=True, deadline=time.time() + _timeout(), stage="teams_copilot")


def _one_slice(s0, s1, alt=False):
    """한 조각(<=30일) 왕복 → (행 목록, 상태) — 상태: table|unable|empty|other|blocked(G3 — 보내지 않음)|
    error(드라이버가 답을 못 받음)|fatal(로그인 등 사람이 풀 실패 — LAST_FATAL 에 phase·reason)"""
    prompt = build_prompt(s0, s1, alt)
    # 예외가 터지면 조각 루프 전체가 죽어 앞서 모은 행이 전량 소실된다 — 반드시 이 조각만 실패로 처리한다.
    try:
        res = _send(prompt)
    except Exception as e:  # noqa: BLE001 — 드라이버 예외는 이 조각만 건너뛴다
        print(f"[teams-copilot]   {s0}~{s1}: 드라이버 오류({type(e).__name__})")
        return [], "error"
    if not isinstance(res, dict):
        print(f"[teams-copilot]   {s0}~{s1}: 드라이버 응답 해석 실패")
        return [], "error"
    if res.get("status") == "blocked" or res.get("phase") == "blocked":
        print(f"[teams-copilot]   {s0}~{s1}: 개인정보 관문(G3) — 보내지 않음")
        return [], "blocked"
    if not res.get("ok"):
        print(f"[teams-copilot]   {s0}~{s1}: 실패 — {res.get('error', '')}")
        if str(res.get("phase") or "") in FATAL_PHASES:     # 조각을 나눠 다시 물어도 똑같다 — 한 번에 접는다
            print(f"[teams-copilot]   {res.get('hint', '')}")
            LAST_FATAL.update(phase=str(res.get("phase") or ""), reason=str(res.get("reason") or ""))
            return [], "fatal"
        return [], "error"
    if res.get("retry"):
        print(f"[teams-copilot]   {s0}~{s1}: {res['retry']}")
    reply = res.get("reply", "")
    try:                                    # 원문 응답 보존 — '왜 1건뿐인가'를 진단할 수 있게
        rd = os.path.join(OUT_DIR, "replies")
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


def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def _read_rows(path):
    """기존 CSV 의 행(머리 제외, 6열 미만은 버림) — 없거나 못 읽으면 []."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            rd = csv.reader(f)
            next(rd, None)
            return [list(r[:6]) for r in rd if r and len(r) >= 6]
    except OSError:
        return []


def _save_span(rows, s0, s1, dst=None):
    """표를 받은 조각(s0~s1)을 바로 저장 — 부모(run.py) 타임아웃·강제 종료가 와도 이미 회수한 조각은 잃지 않는다.
    LM28(W1-17): 그 조각 기간의 옛 행만 이번 행으로 바꾸고 그 밖 기간의 옛 행은 그대로 둔다(teams_parse.merge_keep_outside).
    임시 파일에 쓴 뒤 바꿔 넣는다."""
    dst = dst or os.path.join(OUT_DIR, "teams_copilot.csv")
    merged = teams_parse.merge_keep_outside(_read_rows(dst), [list(r[:6]) for r in rows], s0, s1)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(HDR + "\n")
        for r in merged:
            f.write(",".join([_esc(c) for c in r[:6]]) + "\n")
    os.replace(tmp, dst)
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


UNAVAILABLE_NAME = "teams_copilot_unavailable.json"   # OUT_DIR 아래 — {hits, until}(LM24 판 {when, note} 는 1회 관측으로 읽는다)


def emit_status(rc, reasons=(), counts=None, ranges=None, src="teams_copilot"):
    """수집기 마지막 줄(LM28 P3) — 'LMSTATUS ' + JSON 한 줄."""
    rs = ",".join(dict.fromkeys(r for r in reasons if r))
    print("LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": int(rc), "reason": rs, "counts": counts or {},
                                    "ranges": ranges or []}, ensure_ascii=False))
    sys.stdout.flush()


def _unable_save(path, st):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"hits": st.get("hits") or [], "until": st.get("until") or "",
                       "note": "Copilot 이 팀즈 조회 불가로 답한 날들(커넥터 부재 유형) — 서로 다른 날 2회면 until 까지 생략"
                               "(재시도: --retry-copilot 또는 이 파일 삭제)"}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def slices_of(d0, d1, days=30):
    return sub_slices(d0, d1, days)


def chunk_ranges(chunks):
    """조각 결과 → LMSTATUS ranges(axis teams) — 표를 받은 조각은 partial(Copilot 은 증인이지 '읽음'이 아니다), 그 밖은 unverified."""
    return [{"axis": "teams", "from": a, "to": b, "st": "partial" if st == "table" else "unverified"} for a, b, st in chunks]


def collect_ranges(spans, one_slice=None, dst=None):
    """구간들을 30일 조각으로 왕복 → (받은 행 수, unable 여부, fatal 여부, 조각 결과 [(from, to, 상태)]).
    표를 받은 조각마다 merge_keep_outside 로 바로 저장(그 조각 기간의 옛 행만 바뀐다). 'empty'·'other' 는 실패로 세지 않고,
    드라이버 무응답(error)만 연속 ERR_MAX 번이면 멈춘다. one_slice 는 시험용 주입점(기본 _one_slice)."""
    q = one_slice or _one_slice
    # 90일 통짜 요청은 응답이 잘리거나 '응답할 수 없습니다'가 잦다(실측 — 팀즈 데이터 누락의
    # 주원인). 30일 조각으로 나눠 왕복하고 합친다. 각 왕복은 재시도 사다리의 보호를 받는다.
    slices = [c for a, b in spans for c in slices_of(a, b, 30)]
    print(f"[teams-copilot] {len(spans)}구간 → {len(slices)}조각 왕복 (30일 단위) — 조각당 수십 초")
    rows, seen, chunks = [], set(), []

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
    errs = 0                # 드라이버가 답을 못 받은 조각이 연속 몇 번인지(empty·other 는 세지 않는다 — 진짜 빈 달도 있다)
    unable = fatal = False
    for i, (s0, s1) in enumerate(slices):
        print(f"[teams-copilot] {i + 1}/{len(slices)} 조각 {s0}~{s1}")
        got, st = q(s0, s1, alt_mode)
        if st == "fatal":
            # 로그인이 안 된 PC — 조각을 더 물어도 똑같다. 한 조각에서 접는다('조회 불가'로 기억하지는 않는다).
            print(f"[teams-copilot] Copilot 을 쓸 수 없어 남은 {len(slices) - i}조각을 생략합니다 "
                  "(로그인 뒤 다시 실행하면 이어서 모읍니다)")
            fatal = True
            break
        if st == "unable" and not alt_mode:
            # 실측(스크린샷): 회사 Copilot이 "조회 불가" 한마디로 거절 — 일괄 내보내기 화법이
            # 원인일 수 있어 검색형 화법으로 같은 조각을 한 번 더 시도한다.
            print("[teams-copilot]   '조회 불가' 응답 — 검색형 화법으로 전환해 재시도")
            alt_mode = True
            got, st = q(s0, s1, alt_mode)
        if st == "unable":
            # 커넥터 부재는 이번 실행에서 재질의로 해결되지 않는다 — 남은 조각을 접는다. 다음 실행을 막는 기억은
            # 서로 다른 날 2회일 때만(main — LM24 의 'if True' 는 한 번의 거절로 영구 생략했다)
            print("[teams-copilot] '조회 불가' — 이번 실행의 남은 조각을 생략합니다 (헛왕복 방지).")
            print("               대안: 상시 샘플러(collect\\Start-TeamsSampler.ps1) 또는 config.graph(Graph API)")
            chunks.append((s0, s1, st))
            unable = True
            break
        if st == "error":
            errs += 1
            chunks.append((s0, s1, st))
            if errs >= ERR_MAX:
                print(f"[teams-copilot] {ERR_MAX}조각 연속 답을 받지 못해 중단합니다 — 판정용 Copilot 세션을 아끼기 위해서입니다.")
                break
            continue
        errs = 0
        n0 = len(rows)
        take(got)
        table = st == "table"
        if st in ("table", "other"):
            # 30일 조각이 몇 건만 돌아오거나(검색 누락) 표가 크면(응답 잘림) — 실측 '기간 3개월에
            # 1건'의 원인 — 10일 하위 조각으로 다시 물어 회수율을 끌어올린다.
            span = (datetime.strptime(s1, "%Y-%m-%d") - datetime.strptime(s0, "%Y-%m-%d")).days + 1
            if need_subdivide(len(got), span):
                why = "회수 부족" if len(got) < 5 else "잘림 의심"
                print(f"[teams-copilot]   {len(got)}건 ({why}) → 10일 조각 재질의")
                for t0s, t1s in sub_slices(s0, s1):
                    g2, st2 = q(t0s, t1s, alt_mode)
                    add = take(g2)
                    table = table or st2 == "table"
                    print(f"[teams-copilot]     {t0s}~{t1s}: +{add}건")
        chunks.append((s0, s1, "table" if table else st))
        if table and len(rows) > n0:
            _save_span(rows[n0:], s0, s1, dst)  # 증분 저장 — 그 조각 기간의 옛 행만 바뀐다(부모 타임아웃이 와도 회수분 보존)
        print(f"[teams-copilot]   {'메시지 없음(재질의 생략)' if st == 'empty' else st} · 누적 {len(rows)}건")
    return len(rows), unable, fatal, chunks


def main():
    d0 = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1 = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    mvc = _mvc()
    ranges = mvc.parse_ranges(arg("--ranges")) if "--ranges" in sys.argv else None
    if ranges is not None and not ranges:
        print("[teams-copilot] --ranges 에 물을 날이 없습니다 — 왕복 생략")
        emit_status(0, [], {"chunks": 0})
        return 0
    flag_p = os.path.join(OUT_DIR, UNAVAILABLE_NAME)
    today = date.today()
    # 이 계정의 Copilot 이 팀즈 조회 자체를 못 한다고 서로 다른 날 2번 확인됐으면(테넌트에 Teams 커넥터 부재 — 실측)
    # 14일 동안 헛왕복하지 않는다. 회사가 커넥터를 켜준 뒤 바로 다시 시도하려면 --retry-copilot 또는 기억 파일 삭제.
    ust = mvc.unable_load(flag_p)
    if "--retry-copilot" in sys.argv:
        ust = {"hits": [], "until": ""}
        mvc.unable_clear(flag_p)
    if mvc.unable_active(ust, today):
        print(f"[teams-copilot] 이 계정의 Copilot 은 팀즈 조회 불가로 확인됨(서로 다른 날 2회 — {ust['until']} 까지 왕복 생략)")
        print("               팀즈는 상시 샘플러(collect\\Start-TeamsSampler.ps1)로 따로 모으세요.")
        print(f"               (커넥터가 생겨 재시도하려면: --retry-copilot 또는 {flag_p} 삭제)")
        emit_status(3, ["R-UNABLE"], {"unable_until": ust["until"]})
        return 3
    LAST_FATAL.clear()
    spans = ranges or [(d0, d1)]
    n, unable, fatal, chunks = collect_ranges(spans, dst=os.path.join(OUT_DIR, "teams_copilot.csv"))
    tally = {"chunks": 0, "table": 0, "empty": 0, "other": 0, "error": 0, "blocked": 0, "unable": 0}
    for _a, _b, st in chunks:
        tally["chunks"] += 1
        tally[st] = tally.get(st, 0) + 1
    counts = dict(tally, rows=n)
    out_ranges = chunk_ranges(chunks)
    if fatal:
        ph = LAST_FATAL.get("phase") or ""
        why = LAST_FATAL.get("reason") or ("R-LOGIN" if ph == "login_required" else "R-EDGELAUNCH")
        rc = 2 if ph == "login_required" else 3
        emit_status(rc, [why], counts, out_ranges)
        return rc
    if n == 0:
        if unable:
            ust, confirmed = mvc.unable_note(ust, today)
            _unable_save(flag_p, ust)
            print("               (" + (f"서로 다른 날 2회 확인 — {ust['until']} 까지 Copilot 팀즈 왕복을 생략합니다)"
                                       if confirmed else "1회 기록 — 다른 날 한 번 더 같은 답이면 14일 동안 생략합니다)"))
            emit_status(3, ["R-UNABLE"], counts, out_ranges)
            return 3
        print("[teams-copilot] 전 조각에서 표를 얻지 못함 — Copilot이 팀즈 검색을 지원하지 않는")
        print("               계정이거나 기간에 채팅이 없을 수 있음 (창 읽기 폴백이 이어집니다)")
        print("               실제 응답 원문은 data\\m365\\replies\\ 에서 확인할 수 있습니다")
        if not (tally["empty"] or tally["other"]):
            why = "R-GATE" if tally["blocked"] and not tally["error"] else "R-NOREPLY"
            emit_status(3, [why], counts, out_ranges)
            return 3
        emit_status(0, [], counts, out_ranges)
        return 0
    if ust.get("hits") or ust.get("until"):     # 재시도가 성공했으면 '불가' 기억을 해제
        mvc.unable_clear(flag_p)
        print("[teams-copilot] 팀즈 조회가 다시 가능해짐 — '불가' 기억 해제")
    print(f"[teams-copilot] {n}건 받음 — 표를 받은 조각 기간만 교체해 저장(그 밖 기간의 옛 행은 그대로)")
    emit_status(0, [], counts, out_ranges)
    return 0


if __name__ == "__main__":
    sys.exit(main())
