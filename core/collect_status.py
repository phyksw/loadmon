# -*- coding: utf-8 -*-
r"""core\collect_status.py — 수집기 결과 해석(LM28 P3·C-32·C-33·W1-12·F-34).

수집기는 마지막 줄에 'LMSTATUS {v,src,rc,reason,counts,ranges[{axis,from,to,st}]}' 를 낸다(WP1~WP4).
  rc 0 정상 · 1 대상 없음 · 2 로그인 필요 · 3 불가·불완전(reason 필수) · 4 새 행 0
parse(tail, rc, src, how) 는 그 줄을 읽고, 없으면(LM24 판 수집기·강제 종료) 종료 코드를 해석한다 —
  OWA·팀즈 웹의 옛 1(시간 초과와 0건이 같았다)은 3 R-LEGACY, 시간 초과는 3 R-TIMEOUT, 파이썬 예외는 3 R-CRASH.
'불가' 사유는 실측 전까지 '의심'으로 적는다(P13 — describe·note 의 문구).
"""
import json

OK_RC = (0, 1, 4)                     # 실패가 아닌 결과(정상·대상 없음·새 행 0)
SOFT_REASONS = ("R-RECURINC",)        # rc 3 이지만 저장은 했다(색인 — 반복 회의 미전개) — 단계는 실패로 칠하지 않는다
WEB_SRCS = ("owa", "web", "teams_web")
RC_TEXT = {0: "정상", 1: "대상 없음", 2: "로그인 필요", 3: "불가·불완전 의심(실측 전)", 4: "새 행 0"}
_LEGACY = {0: (0, ""), 2: (2, "R-LOGIN"), 3: (3, "R-LEGACY"), 4: (4, "")}


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
    """LMSTATUS 가 없을 때 — 종료 코드만으로 (rc, 사유)."""
    if any("Traceback (most recent call last)" in ln for ln in lines):
        return 3, "R-CRASH"
    if rc == 1:
        return (3, "R-LEGACY") if src in WEB_SRCS else (1, "")
    if rc in _LEGACY:
        return _LEGACY[rc]
    if rc == -2:
        return 3, "R-SPAWN"
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
        if s.startswith("LMSTATUS "):
            try:
                o = json.loads(s[len("LMSTATUS "):])
            except ValueError:
                o = None
            break
    human = [ln.strip() for ln in lines if not ln.strip().startswith("LMSTATUS ")]
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
    st["ok"] = st["rc"] in OK_RC or (st["rc"] == 3 and bool(st["reasons"]) and st["reasons"][0] in SOFT_REASONS)
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


def compact(counts, max_keys=40):
    """last_run.json 에 싣는 counts — 짧은 스칼라만(원격 진단용 숫자·짧은 사유). 원문·긴 목록은 싣지 않는다."""
    out = {}
    if not isinstance(counts, dict):
        return out
    for k, v in counts.items():
        if len(out) >= max_keys:
            break
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[str(k)[:40]] = v
        elif isinstance(v, str) and len(v) <= 60:
            out[str(k)[:40]] = v
    return out
