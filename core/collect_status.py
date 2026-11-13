# -*- coding: utf-8 -*-
r"""core\collect_status.py — 수집기 결과 해석(AgentFinder32 — Outlook 앱·Outlook 웹·Copilot 메일·일정 수집기).

수집기는 마지막 줄에 'AF32STATUS {v,src,rc,reason,counts,ranges[{axis,from,to,st}]}' 를 낸다.
  rc 0 정상 · 1 대상 없음 · 2 로그인 필요 · 3 불가·불완전·시작 확인에 걸림(R-CONSENT: 내 자료가 아님 · 지우는 중 — reason 필수) ·
     4 설정 거부(R-NODOMAIN 사내 도메인 없음 · R-NORESTRICTED 제한 고객 목록 없음)
  counts 는 숫자·짧은 글만(메일·일정 글·주소·이름 없음) — excluded{private,admin,…}·g1{kept,excluded} 같은 작은 건수 묶음 포함.
parse(tail, rc, src, how) 는 그 줄을 읽고, 없으면(강제 종료·시작 실패) 종료 코드를 해석한다 —
  Outlook 웹의 1 은 3 R-LEGACY, 시간 초과는 3 R-TIMEOUT, 파이썬 예외는 3 R-CRASH.
'불가' 사유는 실측 전까지 '의심'으로 적는다(describe·note 의 문구).
"""
import json

OK_RC = (0, 1)                        # 실패가 아닌 결과(정상·대상 없음)
WEB_SRCS = ("owa",)
SETUP_REASONS = ("R-CONSENT", "R-NODOMAIN", "R-NORESTRICTED")   # 사람이 풀어야 하는 시작 거부(시작 확인·사내 도메인·제한 고객 목록)
RC_TEXT = {0: "정상", 1: "대상 없음", 2: "로그인 필요", 3: "불가·불완전 의심(실측 전)",
           4: "설정 거부(사내 도메인·제한 고객 목록)"}
_LEGACY = {0: (0, ""), 2: (2, "R-LOGIN"), 3: (3, "R-LEGACY"), 4: (4, "R-SETUP")}
# STATUS_DLL_INIT_FAILED — 프로그램(PowerShell)이 켜지는 순간 Windows 가 초기화에 실패했다(보안 프로그램의 끼어들기·Windows
# 자원 부족 의심). 부호 있는/없는 두 꼴로 온다. core\proc.run_step 이 두 번 다시 띄워 보고도 같으면 이 사유로 남긴다.
START_FAIL_RC = (0xC0000142, 0xC0000142 - (1 << 32))


def _ranges(v):
    """ranges 정규화 — PowerShell 이 한 원소 배열을 dict 로 풀어 낸 경우도 받는다. 형식이 틀린 원소는 버린다."""
    if isinstance(v, dict):
        v = [v]
    out = []
    for x in v if isinstance(v, list) else []:
        if not isinstance(x, dict):
            continue
        a, b, ax, st = str(x.get("from") or "")[:10], str(x.get("to") or "")[:10], x.get("axis"), x.get("st")
        if len(a) == 10 and len(b) == 10 and ax and st:
            out.append({"axis": str(ax), "from": min(a, b), "to": max(a, b), "st": str(st)})
    return out


def _legacy(rc, src, lines):
    """AF32STATUS 가 없을 때 — 종료 코드만으로 (rc, 사유)."""
    if any("Traceback (most recent call last)" in ln for ln in lines):
        return 3, "R-CRASH"
    if any("can't open file" in ln for ln in lines):
        return 3, "R-SPAWN"         # 수집기 파일이 없다(파이썬 종료 코드 2) — '로그인 필요' 로 오진하지 않는다
    if rc == 1:
        return (3, "R-LEGACY") if src in WEB_SRCS else (1, "")
    if rc in _LEGACY:
        return _LEGACY[rc]
    if rc == -2:
        return 3, "R-SPAWN"
    if rc in START_FAIL_RC:
        return 3, "R-STARTFAIL"     # Windows 가 프로그램을 시작하지 못함(0xc0000142) — 수집기 탓이 아니다
    return 3, "R-EXIT"


def parse(tail, rc, src="", how="ok"):
    """출력 꼬리(줄 목록 또는 글) + 종료 코드 → 상태 dict:
    {v, src, rc, reason, reasons[], counts{}, ranges[], has_status, exit, how, lines[사람용 줄], human(마지막 사람용 줄), ok}"""
    if isinstance(tail, str):
        tail = tail.splitlines()
    lines = [str(x).rstrip() for x in (tail or []) if str(x).strip()]
    o = None
    for ln in reversed(lines):
        s = ln.strip()
        if s.startswith("AF32STATUS "):
            try:
                o = json.loads(s[len("AF32STATUS "):])
            except ValueError:
                o = None
            break
    human = [ln.strip() for ln in lines if not ln.strip().startswith("AF32STATUS ")]
    st = {"v": 1, "src": src, "rc": 0, "reason": "", "counts": {}, "ranges": [], "has_status": False,
          "exit": rc, "how": how, "lines": human, "human": human[-1] if human else ""}
    if isinstance(o, dict):
        try:
            st["rc"] = int(o.get("rc", rc))
        except (TypeError, ValueError):
            st["rc"] = 3
        st.update(src=str(o.get("src") or src), reason=str(o.get("reason") or ""),
                  counts=o.get("counts") if isinstance(o.get("counts"), dict) else {},
                  ranges=_ranges(o.get("ranges")), has_status=True)
    else:
        st["rc"], st["reason"] = _legacy(rc if isinstance(rc, int) else -2, src, lines)
    if how in ("timeout", "stopped"):
        # 시간 초과로 끊었다 — 수집기가 남긴 상태보다 이것이 사실이다(그 범위는 '읽음'이 아니다)
        st["rc"] = 3
        st["reason"] = ",".join(["R-TIMEOUT"] + [r for r in st["reason"].split(",") if r and r != "R-TIMEOUT"])
        st["ranges"] = [dict(x, st="partial") if x["st"] in ("ok", "zero_ok") else x for x in st["ranges"]]
    elif how == "error":
        st["rc"], st["reason"] = 3, "R-SPAWN"
    st["reasons"] = [r.strip() for r in st["reason"].split(",") if r.strip()]
    st["ok"] = st["rc"] in OK_RC
    st["setup"] = bool(set(st["reasons"]) & set(SETUP_REASONS))
    return st


def describe(st):
    """'rc 3 불가·불완전 의심(실측 전) · R-NEWOL' 꼴 한 줄."""
    rc = st.get("rc")
    s = f"rc {rc} {RC_TEXT.get(rc, '')}".rstrip()
    if st.get("reason"):
        s += " · " + st["reason"]
    return s


def note(st, n_lines=2):
    """last_run.json note — 사람용 마지막 줄(들) + rc·사유. 성공은 요약 1줄, 실패는 마지막 2줄."""
    human = st.get("lines") or []
    if st.get("ok"):
        base = (human[-1] if human else "")[:200]
    else:
        base = " / ".join(human[-n_lines:])[:220]
    if st.get("rc") or st.get("reason"):
        base = (base + " — " if base else "") + describe(st)
    return base[:300]


KEEP_NESTED = {"dom_census": 4096, "selector_diag": 1024, "g1": 1024}   # 화면 구조 진단·G1 건수 — 직렬화 크기 상한(글자 없음)


def compact(counts, max_keys=40):
    """last_run.json 에 싣는 counts — 짧은 스칼라만(원격 진단용 숫자·짧은 사유). 원문·긴 목록은 싣지 않는다.
    예외: 화면 구조 진단(dom_census·selector_diag)과 G1 건수(g1)는 상한 안이면 모양 그대로 싣고, 숫자만 든 작은 묶음(excluded·
    rows·months_read 처럼 12키 이하)도 싣는다. 상한을 넘으면 싣지 않는다."""
    out = {}
    if not isinstance(counts, dict):
        return out
    for k, v in counts.items():
        if len(out) >= max_keys:
            break
        if k in KEEP_NESTED:
            continue
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[str(k)[:40]] = v
        elif isinstance(v, str) and len(v) <= 60:
            out[str(k)[:40]] = v
        elif (isinstance(v, dict) and 0 < len(v) <= 12
              and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v.values())):
            out[str(k)[:40]] = {str(a)[:30]: b for a, b in v.items()}
    for k, cap in KEEP_NESTED.items():
        v = counts.get(k)
        if isinstance(v, (dict, list, str)) and v:
            try:
                if len(json.dumps(v, ensure_ascii=False, default=str)) <= cap:
                    out[k] = v
            except (TypeError, ValueError):
                pass
    return out


def census_line(st):
    """수집기가 찍은 화면 구조 줄 — 마지막 '[…] 구조:' 줄과(있으면) 마지막 '[…] 구조+:' 줄을 줄바꿈으로 잇는다. 없으면 ''."""
    lines = st.get("lines") or []
    out = [next((ln for ln in reversed(lines) if mark in ln), "")[:400] for mark in ("구조:", "구조+:")]
    return "\n".join(x for x in out if x)
