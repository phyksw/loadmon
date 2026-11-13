# -*- coding: utf-8 -*-
r"""
team_summary.py — 익명 팀 집계(spec D16). 조직장 팀 서버(teamserver.py)가 teamdata\team\ 의 기여분으로 만든다.

규칙
  · 하루에 한 번만 다시 계산한다(teamdata\summary.json 의 computed_on). 기여분이 지워지면(거두기·보관기한) 그날은 숫자를
    보이지 않고 다음 날 다시 계산한다 — 바뀐 숫자를 비교해 누가 무엇을 냈는지 짐작하지 못하게.
  · 보이는 조건: 기여분 수 ≥ 기준(max(5, team.minGroupSize)) 이고, 개인 리포트를 함께 보내지 않은 기여분
    (personal_also=false)이 0 이거나 기준 이상.
  · 후보 이름은 서로 다른 기여분 max(3, team.minCellSize) 개 이상이 낸 것만 보인다. 나머지는 '기타 후보' 로 묶고, 그런
    후보를 낸 사람(서로 다른 기여분)이 같은 기준 이상일 때만 그 사람 수(구간)를 표 아래 한 줄로 보인다 — 후보 수가 아니다.
  · 기간(달)은 같은 기준 이상의 기여분이 낸 달만 쓴다 — 한 사람만 낸 달이 기간의 끝을 정하지 않게.
  · 수는 구간으로만(3–4, 5–9, 10+). 이름·메일·근거·월보다 자세한 날짜는 없다.
  · 기준 미달: "참여 인원이 기준(5명)보다 적어 표시하지 않습니다. 상위 조직과 함께 운영해 주세요" — 숫자 없음.

API
  band(n) -> "3–4"|"5–9"|"10+"|None
  norm_name(s) -> 같은 후보를 묶는 열쇠
  load_contributions(team_dir) -> [{"month","personal_also","needs":[{"name","task_type"}]}]
  compute(team_dir, cfg, *, today=None) -> 집계 dict(아래)
  cached(teamdata_dir, cfg, *, today=None) -> 하루 한 번 계산한 집계(필요하면 계산해 summary.json 에 남긴다)
  invalidate(teamdata_dir, *, today=None) -> 오늘은 숫자를 보이지 않게 표시(기여분을 지웠을 때)
  render_html(summary) -> 조직장 페이지에 넣을 HTML 조각(이스케이프 끝난 것)
집계 dict = {"product","computed_on","shown":bool,"message","threshold","participants": 구간|None,
             "months":{"from","to"}|None,"candidates":[{"name","task_type","band"}],
             "other":{"band": 접힌 후보를 낸 사람 수의 구간}|None}
표준 라이브러리 + core\afcfg.py 만.
"""
import collections
import html
import json
import os
import re
import sys
import threading
import time
import unicodedata
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
_CORE = os.path.join(ROOT, "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import afcfg  # noqa: E402
import lmname  # noqa: E402

SUMMARY_FILE = "summary.json"
TEAM_DIR = "team"
FOLD_LABEL = "기타 후보"
WITHHELD_MSG = "자료가 바뀌어 오늘은 표시하지 않습니다 — 내일 다시 계산해 보여 줍니다(하루 한 번)."
_ID_RX = re.compile(r"^[0-9a-f]{32}\.json$")
_MONTH_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_KEY_DROP = re.compile(r"[\s\-_·.,/()\[\]{}'\"`~!?:;]+")


def threshold(cfg):
    """보이는 데 필요한 기여분 수 — max(5, team.minGroupSize)."""
    return max(afcfg.TEAM_MIN["minGroupSize"], int(afcfg.get(cfg, "team.minGroupSize")))


def cell_min(cfg):
    """후보 이름이 보이는 데 필요한 서로 다른 기여분 수 — max(3, team.minCellSize)."""
    return max(afcfg.TEAM_MIN["minCellSize"], int(afcfg.get(cfg, "team.minCellSize")))


def below_message(cfg):
    return f"참여 인원이 기준({threshold(cfg)}명)보다 적어 표시하지 않습니다. 상위 조직과 함께 운영해 주세요"


def band(n):
    """수 → 구간 글자. 3 미만은 None(보이지 않는다)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n >= 10:
        return "10+"
    if n >= 5:
        return "5–9"
    if n >= 3:
        return "3–4"
    return None


def norm_name(s):
    """후보 이름 묶음 열쇠 — NFKC · 소문자 · 공백·문장부호 제거."""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    return _KEY_DROP.sub("", t)


def _today(today):
    if today is None:
        return date.today()
    if isinstance(today, date):
        return today
    return date.fromisoformat(str(today)[:10])


def load_contributions(team_dir):
    """teamdata\\team\\<contribution_id>.json → 기여분 목록(이름이 틀린 파일·깨진 파일은 건너뛴다)."""
    out = []
    try:
        names = sorted(os.listdir(team_dir))
    except OSError:
        return out
    for n in names:
        if not _ID_RX.match(n):
            continue
        try:
            with open(os.path.join(team_dir, n), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        needs = []
        for x in d.get("needs") or []:
            if isinstance(x, dict) and str(x.get("name") or "").strip():
                needs.append({"name": str(x["name"]).strip(), "task_type": str(x.get("task_type") or "").strip()})
        m = str(d.get("month") or "")
        out.append({"month": m if _MONTH_RX.match(m) else "", "personal_also": d.get("personal_also") is True,
                    "needs": needs})
    return out


def compute(team_dir, cfg, *, today=None):
    """기여분 → 익명 집계(D16). 기준 미달이면 shown=False 와 안내 문장만(숫자 없음)."""
    t = threshold(cfg)
    c = cell_min(cfg)
    contribs = load_contributions(team_dir)
    base = {"product": lmname.PRODUCT, "computed_on": _today(today).isoformat(), "threshold": t,
            "shown": False, "message": below_message(cfg), "participants": None, "months": None,
            "candidates": [], "other": None}
    n = len(contribs)
    n_anon = sum(1 for x in contribs if not x["personal_also"])
    if n < t or not (n_anon == 0 or n_anon >= t):
        return base
    groups = collections.OrderedDict()
    for i, x in enumerate(contribs):
        seen = set()
        for nd in x["needs"]:
            k = norm_name(nd["name"])
            if not k or k in seen:
                continue                       # 한 기여분은 한 후보를 한 번만 센다
            seen.add(k)
            g = groups.setdefault(k, {"names": collections.Counter(), "types": collections.Counter(), "who": set()})
            g["names"][nd["name"]] += 1
            if nd["task_type"]:
                g["types"][nd["task_type"]] += 1
            g["who"].add(i)
    shown, folded_who = [], set()
    for _k, g in groups.items():
        cnt = len(g["who"])
        if cnt >= c:
            name = sorted(g["names"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            tt = sorted(g["types"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if g["types"] else ""
            shown.append({"name": name, "task_type": tt, "band": band(cnt), "_n": cnt})
        else:
            folded_who |= g["who"]             # 접힌 후보를 낸 서로 다른 기여분(사람) — 후보 이름 수가 아니다
    shown.sort(key=lambda r: (-r["_n"], r["name"]))
    for r in shown:
        r.pop("_n")
    # 기간 — 기준(c) 이상의 기여분이 낸 달만(한 사람만 낸 달이 기간의 끝을 정하면 그 사람이 드러난다)
    per_month = collections.Counter(x["month"] for x in contribs if x["month"])
    months = sorted(m for m, k in per_month.items() if k >= c)
    other = {"band": band(len(folded_who))} if len(folded_who) >= c else None
    base.update(shown=True, message="", participants=band(n),
                months=({"from": months[0], "to": months[-1]} if months else None),
                candidates=shown, other=other)
    return base


def _path(teamdata_dir):
    return os.path.join(teamdata_dir, SUMMARY_FILE)


def _write(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def cached(teamdata_dir, cfg, *, today=None):
    """오늘 계산한 집계가 있으면 그것, 없으면 지금 계산해 남긴다(하루 한 번). 오늘 기여분이 지워졌으면 숫자 없는 안내."""
    day = _today(today).isoformat()
    p = _path(teamdata_dir)
    d = _read(p)
    if d and d.get("computed_on") == day and d.get("product") == lmname.PRODUCT:
        if d.get("withheld"):
            return {"product": lmname.PRODUCT, "computed_on": day, "threshold": threshold(cfg), "shown": False,
                    "message": WITHHELD_MSG, "participants": None, "months": None, "candidates": [], "other": None}
        return d
    s = compute(os.path.join(teamdata_dir, TEAM_DIR), cfg, today=today)
    try:
        _write(p, s)
    except OSError:
        pass
    return s


def invalidate(teamdata_dir, *, today=None):
    """기여분을 지웠다 — 오늘은 숫자를 보이지 않는다(다음 날 다시 계산)."""
    try:
        _write(_path(teamdata_dir), {"product": lmname.PRODUCT, "computed_on": _today(today).isoformat(),
                                     "withheld": True, "at": time.strftime("%Y-%m-%d")})
    except OSError:
        pass


def _e(v):
    return html.escape(str("" if v is None else v), quote=True)


def render_html(s):
    """집계 → HTML 조각(조직장 페이지용). 값은 모두 이스케이프한다(기여분은 팀원이 보낸 남의 입력)."""
    if not s or not s.get("shown"):
        return f"<p class='note'>{_e((s or {}).get('message') or '')}</p>"
    rows = []
    for r in s.get("candidates") or []:
        rows.append(f"<tr><td>{_e(r.get('name'))}</td><td>{_e(r.get('task_type'))}</td><td>{_e(r.get('band'))}</td></tr>")
    oth = s.get("other") if isinstance(s.get("other"), dict) else None
    # 기타 후보 — 표의 '낸 사람 수' 칸에 넣지 않고 따로 한 줄(무엇을 세었는지 적는다: 그런 후보를 낸 사람 수)
    fold = (f"<p class='note'>{_e(FOLD_LABEL)}: 여러 사람이 함께 내지 않은 후보는 이름 없이 묶었습니다 — 그런 후보를 낸 사람 "
            f"{_e(oth.get('band'))}명</p>") if oth and oth.get("band") else ""
    mo = s.get("months") or {}
    per = f"{mo.get('from')} ~ {mo.get('to')}" if mo else ""
    head = (f"<p>참여 {_e(s.get('participants'))}명" + (f" · 기간 {_e(per)}" if per else "")
            + f" · 계산한 날 {_e(s.get('computed_on'))}</p>")
    if not rows:
        return head + "<p class='note'>여러 사람이 함께 낸 후보가 아직 없습니다.</p>" + fold
    return (head + "<table><tr><th>Agentic AI 전환 후보</th><th>업무 유형</th><th>낸 사람 수</th></tr>"
            + "".join(rows) + "</table>" + fold
            + "<p class='note'>수는 구간으로만 보입니다. 이름·근거·날짜는 없습니다.</p>")
