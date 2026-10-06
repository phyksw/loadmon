# -*- coding: utf-8 -*-
r"""팀 보고서(R §7 · §9.1.2 · §9.4 · TAB §3.9 · §4.6 · 계약 §2.15 · §3.22) — 해석 문장 · 자기완결 HTML · 드릴다운 섬.

    rows = interpret(td, cfg)                          # [{code, text_ko, refs}] — 결정적 템플릿 TI-01~TI-08(최대 6문장)
    html = render_team_report(island, share=False)     # island = team_data + "details"(R §7.8.2) → 자기완결 HTML 문자열
    det  = build_details(details, cfg)                 # 드릴다운 섬 — teamReport.maxDetailMb 를 넘으면 units 를 뺀다
    decorate(td, cfg, details)                         # 표시 메타(영역 이름·색·순서, 단계 이름·종류, 어휘 이름, view) — 제자리
    files = team_tables(td, share=False)               # 팀 표 CSV(R §9.3.3 · 요청 T-5) — {파일 이름: 바이트}, 쓰기는 호출자

원칙
  · 팀 서버에는 코파일럿이 없다. 문장은 모두 결정적 템플릿이고, 단계 라벨·니즈 이름은 팀원 묶음에 실려 온 값이다.
  · 측정 불충분 인원은 합계 문장(TI-01)에는 넣고("측정 불충분 n명 포함") 비율 문장(TI-02~TI-07)에서는 뺀다(TAB §4.5).
  · 숫자 글자는 화면(web\common\lm27ui.js fmtNum·fmtRatio)과 같은 정수 half-up 으로만 만든다(R §3.1 — 은행가 반올림 금지).
  · HTML 은 고정 껍데기 + 데이터 섬뿐이다. 값은 섬(정규 JSON 의 < > & U+2028 U+2029 를 \uXXXX 로)으로만 들어간다
    (R §8.6.3 · G-R4 · G-R6 · TAB-S06). 인라인하는 JS·CSS 에 '</script'·'</style'·'<!--' 가 있으면 만들지 않는다(빌드 실패).
  · 공유판은 사람별 로드율·가용일·꼬리표 분(초과 시간) 열을 섬에서 뺀다(SHARE_DROP_KEYS). 팀 합계 꼬리표 분은
    ``tag_totals`` 로 남는다(R §7.1 '공유판에도 팀 합계는 남는다'). 화면 JS 도 그 키 이름을 글자 그대로 쓰지 않는다
    (TAB §3.9 관문: 제거 키가 공유판 HTML 전체에 0회).
  · 원값(정수 분·float MM)은 바꾸지 않는다 — 반올림은 표시 때만(계약 §3.22).

설정(계약 §5.2 '화면·보고서', 읽는 곳 = 이 모듈): ``teamReport.shiftPp`` · ``teamReport.concentrationShare`` ·
``teamReport.officeShareNote`` · ``teamReport.unattributedNote`` · ``teamReport.axLinkNote``(해석 문턱) ·
``teamReport.smallProjectMm`` · ``teamReport.ganttExpandRows``(화면 view) · ``teamReport.maxDetailMb``(드릴다운 섬 상한).
"""
from __future__ import annotations

import copy
import csv
import io
import math
import re
import statistics

from lm27.hier import vocab as hvocab
from lm27.util import fsx
from lm27.vocab import steps as vsteps

TITLE = "LM27 팀 보고서"
ISLAND_DATA = "lm27-data"
ISLAND_DETAIL = "lm27-detail"
MB = 1024 * 1024
MAX_SENTENCES = 6
TI_CODES = ("TI-01", "TI-02", "TI-03", "TI-04", "TI-05", "TI-06", "TI-07", "TI-08")
TAGS = ("regular", "extended", "night", "holiday")
DOMAIN_CODES = ("DEV", "MP", "EXT", "COM", "AX", "UNC")
OFFICE = "OFFICE"                               # 업무 유형 '사무'(H §1.6) — TI-04
LEAD_MIN_UNITS = 5                              # TI-07: 완료 단위업무 5개 이상인 영역
SHARE_DROP_KEYS = ("load_pct", "avail_days", "by_tag")   # 공유판이 people[].months[] 에서 빼는 키
INLINE_CSS = "common/lm27.css"
INLINE_JS = ("common/lm27ui.js", "common/lm27charts.js", "team/team.js")
ICONS = "common/icons.svg"
CFG_KEYS = ("teamReport.shiftPp", "teamReport.concentrationShare", "teamReport.officeShareNote",
            "teamReport.unattributedNote", "teamReport.axLinkNote", "teamReport.smallProjectMm",
            "teamReport.ganttExpandRows", "teamReport.maxDetailMb")
_COLOR_RX = re.compile(r"^#[0-9a-f]{6}$")
_ISO_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[+-]\d{2}:\d{2}|Z)$")
_INLINE_BAD = re.compile(r"(?i)</(?:script|style)|<!--")
_SYMBOL_RX = re.compile(r"<symbol\b[^>]*>.*?</symbol>", re.S)
_COMMENT_RX = re.compile(r"<!--.*?-->", re.S)
_SYMBOL_BAD = re.compile(r"(?i)<script|<foreignobject|\son[a-z]+\s*=|href\s*=|:\s*//|url\s*\(")
_MONTH_RX = re.compile(r"^(\d{4})-(\d{2})$")


# ───────────────────────────── 설정 ─────────────────────────────
def _cfg(cfg):
    """설정 — 없으면 이 프로그램 폴더의 설정(load_config). ``cfg[key]`` 로 읽는 사전도 받는다(시험)."""
    if cfg is not None:
        return cfg
    from lm27.config import load_config
    return load_config()


def report_view(cfg) -> dict:
    """화면 view 설정(간트 펼침·작은 과제 접기) — 대시보드·자기완결 보고서 JS 가 ``td["view"]`` 로 읽는다."""
    cfg = _cfg(cfg)
    return {"small_project_mm": float(cfg["teamReport.smallProjectMm"]),
            "gantt_expand_rows": int(cfg["teamReport.ganttExpandRows"])}


# ───────────────────────────── 표시 숫자(R §3.1 — lm27ui.js 와 글자 단위로 같음) ─────────────────────────────
def _js_round(x: float) -> int:
    """JS ``Math.round`` 와 같은 정수(동률은 +∞ 쪽) — 부동소수 덧셈 오차 없이."""
    f = math.floor(x)
    return int(f) + 1 if x - f >= 0.5 else int(f)


def fmt_ratio(num: int, den: int, digits: int) -> str | None:
    """정수 num/den 을 digits 자리 half-up(lm27ui.fmtRatio · R §3.1 fmt_ratio). den ≤ 0 이면 None."""
    if den <= 0:
        return None
    s = 10 ** digits
    q = (num * s * 2 + den) // (2 * den)
    return f"{q // s}.{q % s:0{digits}d}" if digits else str(q)


def fmt_num(v, digits: int) -> str | None:
    """JSON 소수 값(MM·비율) 표시 — 1e-6 단위 정수로 바꾼 뒤 정수 half-up(lm27ui.fmtNum 과 같은 글자)."""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    s = fmt_ratio(_js_round(abs(v) * 1_000_000), 1_000_000, digits)
    return "−" + s if v < 0 and any(c in "123456789" for c in s) else s


def pct_int_text(num: int, den: int) -> str | None:
    """정수 분자·분모 비율 → % 숫자 글자(정수, 1% 미만이면 1자리 — lm27ui.pctText 규칙). den ≤ 0 이면 None."""
    if den <= 0:
        return None
    if num == 0:
        return "0"
    return fmt_ratio(num * 100, den, 1 if num * 100 < den else 0)


def pct_share_text(share: float) -> str | None:
    """0~1 소수 비중 → % 숫자 글자(정수, 0 초과 1% 미만이면 1자리)."""
    if share is None or not math.isfinite(share):
        return None
    p = share * 100
    if p == 0:
        return "0"
    return fmt_num(p, 1 if 0 < abs(p) < 1 else 0)


def days_text(biz_min, std_day_min: int) -> str | None:
    """영업 분(정수 또는 중앙값의 .5) → 영업일 1자리(fmt_days)."""
    if biz_min is None or std_day_min <= 0:
        return None
    return fmt_ratio(_js_round(biz_min * 2), std_day_min * 2, 1)


# ───────────────────────────── 한국어 조사 ─────────────────────────────
_LATIN_CONS = frozenset("LMNR")                    # 영문 끝 글자 읽기가 받침으로 끝나는 것(엘·엠·엔·알)
_DIGIT_CONS = frozenset("013678")                  # 영·일·삼·육·칠·팔


def josa(word: str, with_final: str, without_final: str) -> str:
    """낱말 끝소리에 맞는 조사(이/가 · 은/는 …). 판단할 수 없으면 '이(가)' 꼴."""
    w = str(word or "").rstrip(" )]")
    if not w:
        return f"{with_final}({without_final})"
    c = w[-1]
    if "가" <= c <= "힣":
        return with_final if (ord(c) - 0xAC00) % 28 else without_final
    if c.isdigit():
        return with_final if c in _DIGIT_CONS else without_final
    if c.isascii() and c.isalpha():
        return with_final if c.upper() in _LATIN_CONS else without_final
    return f"{with_final}({without_final})"


# ───────────────────────────── 이름 ─────────────────────────────
def _dom_rank(code) -> int:
    return DOMAIN_CODES.index(code) if code in DOMAIN_CODES else len(DOMAIN_CODES)


def _domain_name(td: dict, code: str) -> str:
    for d in td.get("domains") or ():
        if isinstance(d, dict) and d.get("code") == code and isinstance(d.get("name"), str) and d["name"]:
            return d["name"]
    return hvocab.domain_name(code)                      # 모르는 코드는 DOMAIN_META 의 미분류 이름(단일원 — G-H11)


_VOCAB_KIND = {"field": "fields", "func": "functions", "wtype": "activity_types"}


def _vocab_name(td: dict, axis: str, code) -> str:
    """분야·기능·업무 유형 코드 → 이름: 팀 데이터 vocab_names(레지스트리) → 내장 어휘 → 코드. 빈 코드는 '미지정'."""
    if not code:
        return "미지정"
    vn = (td.get("vocab_names") or {}).get(axis) or {}
    if isinstance(vn, dict) and isinstance(vn.get(code), str) and vn[code]:
        return vn[code]
    it = hvocab.builtin_item(_VOCAB_KIND[axis], code)
    return it.name if it is not None else str(code)


def _step_meta(code):
    st = vsteps.STEP_TYPES.get(code) if isinstance(code, str) else None
    return (st.name, st.kind) if st is not None else (None, None)


# ───────────────────────────── 해석 문장(R §7.4.4) ─────────────────────────────
def _weak(td: dict) -> set:
    """비교에서 빼는 사람(측정 불충분) — quality.excluded_from_comparison ∪ people[].quality == unreliable."""
    out = set()
    q = td.get("quality") or {}
    for i in q.get("excluded_from_comparison") or ():
        if isinstance(i, int) and not isinstance(i, bool):
            out.add(i)
    for p in td.get("people") or ():
        if isinstance(p, dict) and p.get("quality") == "unreliable" and isinstance(p.get("i"), int):
            out.add(p["i"])
    return out


def _team_total_mm(td: dict) -> float:
    tot = 0.0
    for p in td.get("people") or ():
        for e in (p or {}).get("months") or ():
            v = (e or {}).get("mm")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tot += v
    return tot


def _month_prev(m: str) -> str | None:
    mt = _MONTH_RX.match(m or "")
    if not mt:
        return None
    y, mo = int(mt.group(1)), int(mt.group(2))
    return f"{y - 1:04d}-12" if mo == 1 else f"{y:04d}-{mo - 1:02d}"


def _ti01(td, weak, total):
    doms = [d for d in td.get("domains") or () if isinstance(d, dict) and isinstance(d.get("total_mm"), (int, float))]
    if not doms or total <= 0:
        return None
    best = min(doms, key=lambda d: (-d["total_mm"], _dom_rank(d.get("code")), str(d.get("code"))))
    if best["total_mm"] <= 0:
        return None
    name = _domain_name(td, best.get("code"))
    text = (f"기간 동안 {name}{josa(name, '이', '가')} 팀 투입의 {pct_share_text(best['total_mm'] / total)}%"
            f"({fmt_num(best['total_mm'], 2)} MM)로 가장 큽니다")
    if weak:
        text += f"(측정 불충분 {len(weak)}명 포함)"
    return {"code": "TI-01", "text_ko": text + ".", "refs": {"domain": best.get("code")}}


def _complete(td, weak, m) -> bool:
    """그 달이 '완전한 달'인가 — 비교 대상 사람 중 그 달 자료가 있는 사람이 모두 부분월이 아님(1명 이상)."""
    seen = False
    for p in td.get("people") or ():
        if not isinstance(p, dict) or p.get("i") in weak:
            continue
        for e in p.get("months") or ():
            if isinstance(e, dict) and e.get("m") == m:
                seen = True
                if e.get("partial"):
                    return False
    return seen


def _dom_month_shares(td, weak, m) -> dict | None:
    """영역 비중(그 달, 귀속분 기준, 측정 불충분 제외) — {code: share}. 분모 0 이면 None."""
    num = {}
    for d in td.get("domains") or ():
        if not isinstance(d, dict):
            continue
        cell = (d.get("by_month") or {}).get(m) or {}
        num[d.get("code")] = sum(v for i, v in cell.get("by_person") or () if i not in weak)
    den = sum(num.values())
    if den <= 0:
        return None
    return {k: v / den for k, v in num.items()}


def _ti02(td, weak, shift_pp):
    months = [m for m in td.get("months") or () if isinstance(m, str)]
    full = [m for m in months if _complete(td, weak, m)]
    if not full:
        return None
    m1 = full[-1]
    m0 = _month_prev(m1)
    if m0 not in months:
        return None
    s0, s1 = _dom_month_shares(td, weak, m0), _dom_month_shares(td, weak, m1)
    if s0 is None or s1 is None:
        return None
    codes = sorted(set(s0) | set(s1), key=lambda c: (_dom_rank(c), str(c)))
    deltas = [((s1.get(c, 0.0) - s0.get(c, 0.0)) * 100, c) for c in codes]
    best = min(deltas, key=lambda dc: (-abs(dc[0]), _dom_rank(dc[1]), str(dc[1])))
    if abs(best[0]) < shift_pp or best[0] == 0:
        return None
    code = best[1]
    p0, p1 = fmt_num(s0.get(code, 0.0) * 100, 0), fmt_num(s1.get(code, 0.0) * 100, 0)
    name = _domain_name(td, code)
    verb = "늘었" if best[0] > 0 else "줄었"
    d = abs(int(p1) - int(p0))
    return {"code": "TI-02", "text_ko": f"{name} 비중이 전월보다 {d}%p {verb}습니다({m0} {p0}% → {m1} {p1}%).",
            "refs": {"domain": code, "from": m0, "to": m1}}


def _ti03(td, conc):
    cells = [c for c in (td.get("role_matrix") or {}).get("cells") or ()
             if isinstance(c, list) and len(c) >= 4 and isinstance(c[3], (int, float)) and not isinstance(c[3], bool)
             and (c[0] or c[1])]
    if not cells:
        return None
    best = min(cells, key=lambda c: (-c[3], str(c[0]), str(c[1])))
    if best[3] < conc or best[3] <= 0:
        return None
    f, fn = _vocab_name(td, "field", best[0]), _vocab_name(td, "func", best[1])
    return {"code": "TI-03", "text_ko": f"{f}·{fn} 역할에 귀속 투입의 {pct_share_text(best[3])}%가 몰려 있습니다.",
            "refs": {"field": best[0], "function": best[1]}}


def _ti04(td, weak, office):
    at = td.get("activity_types") or {}
    order = [t for t in at.get("types") or () if isinstance(t, str)]
    tot = {}
    for row in at.get("by_person") or ():
        if not (isinstance(row, list) and len(row) == 2 and isinstance(row[1], dict)) or row[0] in weak:
            continue
        for t, v in row[1].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tot[t] = tot.get(t, 0.0) + v
    den = sum(tot.values())
    if den <= 0:
        return None
    if tot.get(OFFICE, 0.0) / den >= office:
        code = OFFICE
    else:
        cand = [t for t in tot if t and tot[t] > 0]
        if not cand:
            return None
        rank = {t: k for k, t in enumerate(order)}
        code = min(cand, key=lambda t: (-tot[t], rank.get(t, len(rank)), t))
    name = _vocab_name(td, "wtype", code)
    return {"code": "TI-04", "text_ko": f"업무 유형으로는 {name}{josa(name, '이', '가')} {pct_share_text(tot[code] / den)}%입니다.",
            "refs": {"activity_type": code}}


def _ti05(td, weak, unatt):
    env = un = 0
    for p in td.get("people") or ():
        if not isinstance(p, dict) or p.get("i") in weak:
            continue
        for e in p.get("months") or ():
            if isinstance(e, dict) and isinstance(e.get("env_min"), int) and isinstance(e.get("unattributed_min"), int):
                env += e["env_min"]
                un += e["unattributed_min"]
    if env <= 0 or un * 1.0 / env < unatt or un <= 0:
        return None
    return {"code": "TI-05", "text_ko": f"근무시간의 {pct_int_text(un, env)}%가 단위업무에 묶이지 않았습니다(근무 중 미분류)"
            " — 측정 품질 절을 확인하세요.", "refs": {}}


def _ti06(td, weak, axn):
    tot = ax = 0
    seen_flag = False
    for row in td.get("gantt") or ():
        if not isinstance(row, dict) or row.get("person") in weak:
            continue
        for u in row.get("units") or ():
            if not isinstance(u, dict) or not isinstance(u.get("effort_min"), int):
                continue
            tot += u["effort_min"]
            if "ax_link" in u:
                seen_flag = True
                if u["ax_link"] is True:
                    ax += u["effort_min"]
    if not seen_flag or tot <= 0 or ax <= 0 or ax * 1.0 / tot < axn:
        return None
    return {"code": "TI-06", "text_ko": f"AX 연계 표시가 붙은 업무가 투입의 {pct_int_text(ax, tot)}%입니다(개발·양산 영역에 계상).",
            "refs": {}}


def _ti07(td, weak):
    by = {}
    for p in (td.get("units_stats") or {}).get("lead_points") or ():
        if not isinstance(p, dict) or p.get("i") in weak or not isinstance(p.get("biz_lead_min"), (int, float)):
            continue
        by.setdefault(p.get("domain"), []).append(p["biz_lead_min"])
    big = {d: v for d, v in by.items() if len(v) >= LEAD_MIN_UNITS}
    if len(big) < 2:
        return None
    med = {d: statistics.median(sorted(v)) for d, v in big.items()}
    code = min(med, key=lambda d: (-med[d], _dom_rank(d), str(d)))
    name = _domain_name(td, code)
    std = td.get("std_day_min") if isinstance(td.get("std_day_min"), int) and td.get("std_day_min") > 0 else 480
    return {"code": "TI-07", "text_ko": f"{name} 단위업무의 중앙 리드타임이 {days_text(med[code], std)}영업일로 가장 깁니다.",
            "refs": {"domain": code}}


def _ti08(weak):
    if not weak:
        return None
    return {"code": "TI-08", "text_ko": f"{len(weak)}명은 측정이 불충분해 비교 집계에서 뺐습니다(합계에는 포함, 빗금).",
            "refs": {"people": sorted(weak)}}


def interpret(td: dict, cfg=None) -> list[dict]:
    """해석 문장 — R §7.4.4 순서대로 조건에 맞는 것만, 최대 6문장. ``[{code, text_ko, refs}]``(결정적)."""
    if not isinstance(td, dict):
        return []
    cfg = _cfg(cfg)
    shift = float(cfg["teamReport.shiftPp"])
    conc = float(cfg["teamReport.concentrationShare"])
    office = float(cfg["teamReport.officeShareNote"])
    unatt = float(cfg["teamReport.unattributedNote"])
    axn = float(cfg["teamReport.axLinkNote"])
    total = _team_total_mm(td)
    if total <= 0:
        return []
    weak = _weak(td)
    rules = (lambda: _ti01(td, weak, total), lambda: _ti02(td, weak, shift), lambda: _ti03(td, conc),
             lambda: _ti04(td, weak, office), lambda: _ti05(td, weak, unatt), lambda: _ti06(td, weak, axn),
             lambda: _ti07(td, weak), lambda: _ti08(weak))
    out = []
    for rule in rules:
        r = rule()
        if r is not None:
            out.append(r)
        if len(out) >= MAX_SENTENCES:
            break
    return out


# ───────────────────────────── 표시 메타·공유판 ─────────────────────────────
def _decorate_details(details) -> None:
    if not isinstance(details, dict):
        return
    for v in details.values():
        steps = ((v or {}).get("workflow") or {}).get("steps") if isinstance(v, dict) else None
        for s in steps or ():
            if not isinstance(s, dict):
                continue
            name, kind = _step_meta(s.get("type"))
            if name is not None:
                s.setdefault("name", name)
                s.setdefault("kind", kind)


def decorate(td: dict, cfg=None, details: dict | None = None) -> dict:
    """표시 메타를 채운다(제자리, 여러 번 불러도 같다) — 원값은 건드리지 않는다.

    · ``domains[].name``·``color``·``order``(H §1.2 DOMAIN_META — 화면 JS 는 16진 색을 갖지 않는다, R §8.1.3)
    · ``vocab_names.step``(단계 유형 코드 → 한글명)·``step_kind``(→ M 점 | A 구간) · 비어 있는 ``vocab_names.field``·``func``·``wtype`` 은 내장 어휘 이름으로
    · ``view``(cfg 가 있을 때 — 작은 과제 접기·간트 펼침) · ``details`` 의 단계에 ``name``·``kind``(M|A)."""
    if not isinstance(td, dict):
        return td
    for d in td.get("domains") or ():
        if not isinstance(d, dict) or d.get("code") not in DOMAIN_CODES:
            continue
        d.setdefault("name", hvocab.domain_name(d["code"]))
        col = str(hvocab.domain_color(d["code"])).lower()
        if _COLOR_RX.match(col):
            d.setdefault("color", col)
        d.setdefault("order", hvocab.domain_order(d["code"]))
    vn = td.get("vocab_names")
    if not isinstance(vn, dict):
        vn = td["vocab_names"] = {}
    used = {"field": set(), "func": set(), "wtype": set()}
    for r in td.get("roles") or ():
        if isinstance(r, dict):
            used["field"].add(r.get("field"))
            used["func"].add(r.get("function"))
    for c in (td.get("role_matrix") or {}).get("cells") or ():
        if isinstance(c, list) and len(c) >= 2:
            used["field"].add(c[0])
            used["func"].add(c[1])
    for t in (td.get("activity_types") or {}).get("types") or ():
        used["wtype"].add(t)
    for axis, codes in used.items():
        cur = vn.get(axis)
        if not isinstance(cur, dict):
            cur = vn[axis] = {}
        for code in sorted(c for c in codes if isinstance(c, str) and c):
            if code not in cur:
                it = hvocab.builtin_item(_VOCAB_KIND[axis], code)
                if it is not None:
                    cur[code] = it.name
    step = vn.get("step") if isinstance(vn.get("step"), dict) else {}
    kind = vn.get("step_kind") if isinstance(vn.get("step_kind"), dict) else {}
    for code, st in vsteps.STEP_TYPES.items():
        step.setdefault(code, st.name)
        kind.setdefault(code, st.kind)
    vn["step"] = step
    vn["step_kind"] = kind
    if cfg is not None:
        td["view"] = report_view(cfg)
    _decorate_details(details)
    return td


def tag_totals(td: dict) -> dict:
    """팀 합계 꼬리표 분 ``{"by_month": {m: {tag: 분}}, "total": {tag: 분}}`` — 사람별 by_tag 의 정수 합(측정 불충분 포함).
    사람별 꼬리표가 이미 빠진 자료(공유판)면 있던 ``tag_totals`` 를 그대로 돌려준다."""
    have = any(isinstance(e, dict) and isinstance(e.get("by_tag"), dict)
               for p in td.get("people") or () if isinstance(p, dict) for e in p.get("months") or ())
    if not have and isinstance(td.get("tag_totals"), dict):
        return td["tag_totals"]
    by_month = {m: dict.fromkeys(TAGS, 0) for m in td.get("months") or () if isinstance(m, str)}
    for p in td.get("people") or ():
        for e in (p or {}).get("months") or ():
            if not isinstance(e, dict) or not isinstance(e.get("by_tag"), dict):
                continue
            row = by_month.setdefault(e.get("m"), dict.fromkeys(TAGS, 0))
            for t in TAGS:
                v = e["by_tag"].get(t)
                if isinstance(v, int) and not isinstance(v, bool):
                    row[t] += v
    total = dict.fromkeys(TAGS, 0)
    for row in by_month.values():
        for t in TAGS:
            total[t] += row[t]
    return {"by_month": dict(sorted(by_month.items())), "total": total}


def strip_for_share(td: dict) -> dict:
    """공유판 섬 — people[].months[] 에서 SHARE_DROP_KEYS(로드율·가용일·꼬리표 분)를 뺀 사본. 팀 합계는 tag_totals 로."""
    out = copy.deepcopy(td)
    out["tag_totals"] = tag_totals(td)
    for p in out.get("people") or ():
        for e in (p or {}).get("months") or ():
            if isinstance(e, dict):
                for k in SHARE_DROP_KEYS:
                    e.pop(k, None)
    out["variant"] = "share"
    return out


def build_details(details, cfg=None, *, max_bytes: int | None = None) -> dict:
    """자기완결 보고서의 드릴다운 섬(R §7.8.2) — 키 ``"<i>|<role_id>"``. 정규 JSON 크기가 상한
    (``teamReport.maxDetailMb``)을 넘으면 항목마다 ``units`` 를 빼고 ``units_omitted: true`` 를 단다(workflow 는 남긴다)."""
    out = copy.deepcopy(details) if isinstance(details, dict) else {}
    _decorate_details(out)
    cap = max_bytes if max_bytes is not None else int(_cfg(cfg)["teamReport.maxDetailMb"]) * MB
    if len(fsx.canon_bytes(out)) > cap:
        for v in out.values():
            if isinstance(v, dict) and "units" in v:
                v.pop("units", None)
                v["units_omitted"] = True
    return out


# ───────────────────────────── 팀 표 CSV(R §9.3.3 · 요청 T-5) ─────────────────────────────
_FORMULA_HEAD = ("=", "+", "-", "@", "\t", "\r")
QUALITY_KO = {"reliable": "신뢰", "caution": "주의", "unreliable": "측정 불충분", "": "미확인"}
STATUS_KO = {"closed": "완료", "estimated": "추정 완료", "open": "진행 중"}
FLAG_KO = {"calendar_mismatch": "달력 다름", "cfg_mismatch": "산식 설정 다름", "pepper_mismatch": "pepper 다름",
           "retired": "퇴직"}
COV_AXES = (("mail_in", "메일 받음"), ("mail_out", "메일 보냄"), ("cal", "일정"), ("teams", "팀즈"), ("pc", "PC"))
SHARE_DROP_COLS = ("정규", "연장", "야간", "휴일", "가용일", "로드율")       # 공유판 person_monthly 에서 빠지는 열(*)


def _txt(v) -> str:
    """글자 칸 — 수식 주입 방어(= + - @ 탭 CR 로 시작하면 앞에 ')."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA_HEAD) else s


def _num(v, digits: int) -> str:
    s = fmt_num(v, digits)
    return "" if s is None else s


def _csv_bytes(cols, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(cols)
    for r in rows:
        w.writerow(r)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _labels(td: dict) -> dict:
    return {p.get("i"): (p.get("label") or f"담당자 {int(p.get('i', 0)) + 1}")
            for p in td.get("people") or () if isinstance(p, dict) and isinstance(p.get("i"), int)}


def _project_label(td: dict, key) -> str:
    for p in td.get("projects") or ():
        if isinstance(p, dict) and (p.get("key") == key or (key and p.get("project_id") == key)):
            return p.get("label") or p.get("project_id") or str(key)
    return "과제 없음" if key in (None, "", "UNC") else str(key)


def team_tables(td: dict, share: bool = False) -> dict[str, bytes]:
    """팀 표 CSV(R §9.3.3) — ``{파일 이름: 바이트}``(UTF-8 BOM + CRLF, 수식 주입 방어, 숫자는 §3.1 표시 함수 글자).
    ``share=True`` 면 person_monthly 에서 사람별 정규·연장·야간·휴일·가용일·로드율 열을 뺀다(공유판 — ``team_tables\\share\\``).
    쓰기는 호출자(취합기)가 한다 — 이 모듈은 디스크에 쓰지 않는다."""
    td = decorate(copy.deepcopy(td), None)
    lab = _labels(td)
    out = {}
    cols = ["사람 라벨", "월", "MM", "근무(분)", "정규", "연장", "야간", "휴일", "가용일", "로드율", "측정 품질", "부분월"]
    if share:
        cols = [c for c in cols if c not in SHARE_DROP_COLS]
    rows = []
    for p in td.get("people") or ():
        for e in (p or {}).get("months") or ():
            if not isinstance(e, dict):
                continue
            bt = e.get("by_tag") if isinstance(e.get("by_tag"), dict) else {}
            pt = e.get("partial") if isinstance(e.get("partial"), dict) else None
            full = {"사람 라벨": _txt(lab.get(p.get("i"))), "월": e.get("m"), "MM": _num(e.get("mm"), 2),
                    "근무(분)": e.get("env_min"), "정규": bt.get("regular"), "연장": bt.get("extended"),
                    "야간": bt.get("night"), "휴일": bt.get("holiday"), "가용일": _num(e.get("avail_days"), 1),
                    "로드율": _num(e.get("load_pct"), 0), "측정 품질": QUALITY_KO.get(p.get("quality") or "", "미확인"),
                    "부분월": f"{pt.get('covered_workdays')}/{pt.get('workdays')}" if pt else ""}
            rows.append([full[c] for c in cols])
    out["person_monthly.csv"] = _csv_bytes(cols, rows)
    weak = _weak(td)
    rows = []
    for d in td.get("domains") or ():
        for m, cell in sorted((d.get("by_month") or {}).items()):
            w = sum(v for i, v in cell.get("by_person") or () if i in weak)
            rows.append([_txt(_domain_name(td, d.get("code"))), m, _num(cell.get("mm"), 2), _num(w, 2)])
    for m, v in sorted(((td.get("unattributed") or {}).get("by_month") or {}).items()):
        rows.append(["미귀속(근무 중 미분류)", m, _num(v, 2), ""])
    out["domain_monthly.csv"] = _csv_bytes(["영역", "월", "MM", "측정 불충분 몫 MM"], rows)
    rows = []
    for p in td.get("projects") or ():
        for i, v in p.get("by_person") or ():
            rows.append([_txt(_project_label(td, p.get("key"))), _txt(_domain_name(td, p.get("domain"))),
                         _txt(lab.get(i)), _num(v, 2)])
    out["project_people.csv"] = _csv_bytes(["과제", "영역", "사람 라벨", "MM"], rows)
    std = td.get("std_day_min") if isinstance(td.get("std_day_min"), int) and td.get("std_day_min") > 0 else 480
    rows = []
    for r in td.get("roles") or ():
        key = r.get("proposal_key") if r.get("proposal") else (r.get("project_id") or "UNC")
        rows.append([r.get("role_id"), _txt(_project_label(td, key)), _txt(_vocab_name(td, "field", r.get("field"))),
                     _txt(_vocab_name(td, "func", r.get("function"))), _num(r.get("total_mm"), 2), r.get("units"),
                     days_text(r.get("lead_biz_median_min"), std) or "", _num(r.get("effort_median_min"), 0)])
    out["roles.csv"] = _csv_bytes(["역할 ID", "과제", "분야", "기능", "MM", "단위업무 수", "중앙 리드(영업일)", "중앙 투입(분)"],
                                  rows)
    at = td.get("activity_types") or {}
    rows = []
    for dom, types in sorted((at.get("by_domain") or {}).items(), key=lambda kv: (_dom_rank(kv[0]), kv[0])):
        for t, v in sorted(types.items()):
            rows.append([_txt(_vocab_name(td, "wtype", t)), _txt(_domain_name(td, dom)), _num(v, 2)])
    out["activity_types.csv"] = _csv_bytes(["업무 유형", "영역", "MM"], rows)
    rows = []
    for g in td.get("gantt") or ():
        for u in g.get("units") or ():
            rows.append([_txt(lab.get(g.get("person"))), g.get("role_id"), u.get("unit_id"), _txt(u.get("title")),
                         (u.get("start") or {}).get("kind") or "", (u.get("end") or {}).get("kind") or "",
                         u.get("grade") or "", STATUS_KO.get(u.get("status"), u.get("status") or ""),
                         _num(u.get("lead_time_h"), 1), u.get("effort_min"), _num(u.get("parallel"), 1)])
    out["units.csv"] = _csv_bytes(["사람 라벨", "역할 ID", "단위업무 ID", "제목", "시작 종류", "종료 종류", "등급", "상태",
                                   "리드(h)", "투입(분)", "병행도"], rows)
    ag = td.get("agentic") or {}
    rows = []
    for x in ag.get("matches") or ():
        for dom, c in sorted((x.get("by_domain") or {}).items(), key=lambda kv: (_dom_rank(kv[0]), kv[0])):
            rows.append([x.get("agent_id"), _txt(x.get("name")), _txt(_domain_name(td, dom)), c.get("people"),
                         c.get("units"), _num(c.get("related_mm"), 2), c.get("best") or ""])
        rows.append([x.get("agent_id"), _txt(x.get("name")), "전체", x.get("people"), x.get("units"),
                     _num(x.get("related_mm"), 2), "중복 포함" if x.get("overlap") else ""])
    out["agentic.csv"] = _csv_bytes(["에이전트 ID", "이름", "영역", "사람 수", "단위업무 수", "관련 투입 MM", "최고 등급·비고"],
                                    rows)
    rows = []
    step_names = (td.get("vocab_names") or {}).get("step") or {}
    for x in ag.get("needs") or ():
        g, s = x.get("grades") or {}, x.get("src") or {}
        rows.append([_txt(step_names.get(x.get("step_type")) or x.get("step_type")), _txt(x.get("label")), x.get("people"),
                     _num(x.get("freq_per_month"), 1), _num(x.get("related_mm"), 2), g.get("상", 0), g.get("중", 0),
                     g.get("하", 0), s.get("ai", 0), s.get("rule", 0)])
    out["needs.csv"] = _csv_bytes(["단계 유형", "이름", "사람 수", "월 빈도 합", "관련 투입 MM", "상", "중", "하", "AI", "규칙"],
                                  rows)
    rows = []
    for r in (td.get("quality") or {}).get("matrix") or ():
        axes = r.get("axes") or {}
        rows.append([_txt(lab.get(r.get("i"))), QUALITY_KO.get(r.get("grade") or "", "미확인")]
                    + [_num(axes[a] * 100, 0) if isinstance(axes.get(a), (int, float)) else "" for a, _n in COV_AXES]
                    + [r.get("pcs"), " · ".join(FLAG_KO.get(f, f) for f in r.get("flags") or ()),
                       " · ".join(str(c) for c in r.get("reasons") or ())])
    out["quality.csv"] = _csv_bytes(["사람 라벨", "등급"] + [n + "(%)" for _a, n in COV_AXES] + ["PC 수", "표식", "사유 코드"],
                                    rows)
    return out


# ───────────────────────────── 자기완결 HTML(R §9.4) ─────────────────────────────
def island_text(obj) -> str:
    """데이터 섬 글자 — 정규 JSON 의 < > & U+2028 U+2029 를 \\uXXXX 로(LM24 저장형 XSS 실측 방어 계승, G-R6)."""
    s = fsx.canon_bytes(obj).decode("utf-8")
    return (s.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _inline(paths, rel: str) -> str:
    """인라인할 정적 파일 글자. '</script'·'</style'·'<!--' 가 있으면 ValueError(G-R6 — 빌드 실패)."""
    text = fsx.read_bytes(paths.web_file(rel)).decode("utf-8")
    if _INLINE_BAD.search(text):
        raise ValueError(f"인라인 금지 글자열이 있습니다: web/{rel}(G-R6)")
    return text


def _sprite(paths) -> str:
    """icons.svg 의 <symbol> 들(R §8.2.9 — 자기완결 HTML 은 스프라이트를 인라인한다). 스크립트·외부 참조가 있으면 ValueError."""
    text = _COMMENT_RX.sub("", fsx.read_bytes(paths.web_file(ICONS)).decode("utf-8"))
    syms = _SYMBOL_RX.findall(text)
    for s in syms:
        if not s.startswith('<symbol id="i-') or _SYMBOL_BAD.search(s):
            raise ValueError("아이콘 스프라이트에 허용되지 않는 내용이 있습니다(G-R5·G-R6)")
    return '<svg hidden aria-hidden="true" focusable="false"><defs>' + "".join(syms) + "</defs></svg>"


def _comment(td: dict) -> str:
    """머리 주석 한 줄(세대·취합 시각) — 값은 형식 검사를 통과한 것만(정수·ISO 시각)."""
    gen, built = td.get("gen"), td.get("built_at")
    parts = ["<!-- LM27 team report"]
    if isinstance(gen, int) and not isinstance(gen, bool) and gen >= 0:
        parts.append(" · gen " + str(gen))
    if isinstance(built, str) and _ISO_RX.match(built):
        parts.append(" · built " + built)
    parts.append(" -->")
    return "".join(parts)


def render_team_report(island: dict, share: bool = False, *, cfg=None, paths=None) -> str:
    """자기완결 팀 보고서 HTML(R §9.4 · TAB §3.9). ``island`` = team_data(+ ``details``). ``share=True`` = 공유판.

    섬 ``lm27-data`` = 표시 메타를 채운 team_data(공유판은 SHARE_DROP_KEYS 를 뺀 사본 + tag_totals),
    ``lm27-detail`` = build_details(details). 같은 입력·설정·정적 파일이면 같은 바이트(G-R1)."""
    if not isinstance(island, dict):
        raise TypeError("island 는 team_data 사전이어야 합니다")
    cfg = _cfg(cfg)
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    td = copy.deepcopy({k: v for k, v in island.items() if k != "details"})
    details = copy.deepcopy(island.get("details")) if isinstance(island.get("details"), dict) else {}
    decorate(td, cfg, details)
    if not isinstance(td.get("interpretation"), list):
        td["interpretation"] = interpret(td, cfg)
    td["tag_totals"] = tag_totals(td)
    td["variant"] = "full"
    if share:
        td = strip_for_share(td)
    det = build_details(details, cfg)
    css = _inline(paths, INLINE_CSS)
    scripts = [_inline(paths, rel) for rel in INLINE_JS]
    variant = "share" if share else "full"
    out = [
        "<!doctype html>\n",
        '<html lang="ko">\n<head>\n',
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n',
        '<meta name="color-scheme" content="light">\n',
        "<title>", TITLE, "</title>\n",
        "<style>\n", css, "\n</style>\n",
        "</head>\n",
        '<body data-kind="team" data-variant="', variant, '">\n',
        _comment(td), "\n",
        _sprite(paths), "\n",
        '<div id="team-root">\n',
        '<header class="app-head" id="team-head"><h1>', TITLE, "</h1></header>\n",
        '<div id="team-nav"></div>\n',
        '<main id="app" tabindex="-1"><p class="empty">팀 보고서를 여는 중입니다.</p></main>\n',
        "</div>\n",
        "<noscript><p>이 보고서는 브라우저 스크립트로 그립니다 — 스크립트를 켠 브라우저에서 여세요.</p></noscript>\n",
        '<script type="application/json" id="', ISLAND_DATA, '">', island_text(td), "</script>\n",
        '<script type="application/json" id="', ISLAND_DETAIL, '">', island_text(det), "</script>\n",
    ]
    for js in scripts:
        out += ["<script>\n", js, "\n</script>\n"]
    out.append("</body>\n</html>\n")
    return "".join(out)
