# -*- coding: utf-8 -*-
r"""코파일럿 분류 단계의 상류·하류 — ai_in 항목 만들기 · ai_out 읽기 · 재질의 표식 · 프롬프트 문맥 줄
(H §6 · §8.2 · §8.3, 계약 §2.10 · §3.17 · X-250~X-252).

**브리지와는 `ai_in`·`ai_out` 파일로만 만난다 — 브리지 모듈을 import 하지 않는다**(H §12.2 · B §2.5).

- `build_task_label_items(...)` — `task_label/1.1` ai_in 항목(H §6.1·§6.2). 보내는 군집: 사용자 라벨 없음 ∧ ((a) 과제 미확정
  (none·rule_probable·그 영역에 active 과제가 있는 예약 과제) ∨ (b) 이름이 약함(app·generic, 캐시에 사용자·AI h·m 이름 없음 —
  `hier.copilot.askTitleWeak`) ∨ (c) 분야·기능 둘 다 l 이고 군집 투입 ≥ `hier.copilot.vocabAskMinEffortH`). 큰 일부터,
  한 실행 `hier.copilot.maxGroupsPerRun` 개. 필드: kinds · subjects · files · apps(범주 이름 — exe 이름은 보내지 않는다) ·
  domains(계급만 — 도메인 원문은 보내지 않는다) · cands · hint(분야/기능/유형) · regv.
- 증거 정제문 안의 레지스트리 이름·별칭·코드네임은 ai_in 에 쓰기 전에 `[과제:ID]` 로 한 번 더 바꾼다(`mask_registry_names` —
  G-H2: 프롬프트에 코드네임·별칭·mask_name 이름 0회. 전송 직전 브리지 게이트가 같은 일을 다시 한다).
- 재질의 `regv`(H §6.6): 레지스트리 과제 목록이 바뀌었고 이전 답이 NONE·NEW·예약·비active 면 과제 목록 해시, `conf=l` 이고 증거가
  `hier.copilot.reaskGrowth` 배 이상 늘었으면 'g'+건수. 값은 제목 캐시(`ask`)에 붙박여 다음 실행에도 같은 내용 키가 된다.
- `prompt_context(reg, stage)` — 프롬프트의 레지스트리·어휘 목록 줄(단계 내용 소유 H — 과제 이름·별칭·코드네임은 싣지 않고
  `코드 · 영역 · copilot_desc` 만, 개인 `L_` 어휘 코드는 싣지 않음, 축약은 이 묶음 후보 + 예약 5줄). 브리지 단계가 쓰거나
  같은 바이트를 내야 한다(골든 HG29 · 관문 G-H9).
- `validate_answer` — 답 검증(H §6.5, 골든 HG30). 적용 전에 현재 레지스트리로 한 번 더 본다.

표준 라이브러리만 쓴다. 쓰기는 `fsx.atomic_write`(ai_in) 하나.
"""
import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping

from lm27.hier import vocab as _vocab
from lm27.hier.features import default_cfg, get
from lm27.hier.groups import app_cat_name, clip_title, display_stem
from lm27.hier.names import ukey
from lm27.hier.unitlabel import KIND_LABELS
from lm27.time.tokens import is_generic_key
from lm27.util import fsx

__all__ = [
    "BOOT_SEND_FIELDS", "CONTENT_KEY_FIELDS", "HIER_VERSION", "PROMPT_VER", "SEND_FIELDS", "STAGE", "TEXT_FIELDS",
    "WEB_DROP_FIELDS", "ask_state", "build_bootstrap_samples", "build_consolidate_items", "build_task_label_items",
    "codes_for", "domain_classes", "fit_lines", "mask_registry_names", "prompt_context", "read_ai_out", "regv_for",
    "set_hash", "validate_answer", "write_ai_in",
]

HIER_VERSION = "hier/1"
STAGE = "task_label"
PROMPT_VER = "task_label/1.1"
SEND_FIELDS = ("kinds", "subjects", "files", "apps", "domains", "cands", "hint", "regv")
CONTENT_KEY_FIELDS = ("kinds", "subjects", "files", "apps", "domains", "regv")   # cands·hint 는 빼서 규칙만 바뀌면 다시 묻지 않는다
TEXT_FIELDS = ("subjects", "files", "apps", "domains")
WEB_DROP_FIELDS = ("domains",)
BOOT_STAGE = "taxonomy_bootstrap"
BOOT_SEND_FIELDS = ("dom", "title", "files", "subject", "peer")
CONS_STAGE = "taxonomy_consolidate"
NO_DESC = "(설명 없음)"
COMPACT_NOTE = "(목록은 이번 항목의 후보만 보입니다. 맞는 것이 없으면 NONE 또는 P-99 코드)"
OUTSIDE = "외부"
_TIME_KEY = re.compile(r"(?i)^(start|end|begin|finish|time|date|datetime|hours?|minutes?|mins?|mm|man_?month|duration"
                       r"|effort|lead_?time)$")
_MONEY = re.compile(r"\d[\d,]*\s?(원|만원|억|달러|USD|KRW)")
_HANGUL = re.compile(r"[가-힣]")


# ───────────────────────── 문맥 줄(H §6.3 · §8.2) ─────────────────────────
def _vocab_line(reg, kind: str, head: str) -> str:
    items = [it for it in reg.vocab.get(kind, {}).values() if it.status == "active" and it.origin != "local"]
    return f"[{head}] " + " · ".join(f"{it.code} {it.name}" for it in items)


def prompt_context(reg, stage: str = STAGE, *, compact: bool = False, cand_codes: Iterable[str] = ()) -> list[str]:
    """프롬프트의 레지스트리·어휘 목록 줄. task_label = [업무영역]·[과제 목록]·예약 5줄·[분야]·[기능]·[업무유형],
    taxonomy_bootstrap = [업무영역]·[이미 있는 과제]. 과제는 `코드 · 영역 · copilot_desc` 만(B14). 설명에 과제 이름·별칭·
    코드네임이 섞여 있어도 `[과제:ID]` 로 가린다(G-H2 — 레지스트리 검증의 desc_has_codename 다음 둘째 방어선)."""
    lines = [_vocab.domain_prompt_line()]
    ids = reg.active_ids()
    if stage == STAGE:
        lines.append("[과제 목록] 코드 · 업무영역 · 설명")
        if compact:
            cc = set(cand_codes)
            ids = [i for i in ids if i in cc]
        for pid in ids:
            lines.append(f"{pid} · {reg.projects[pid].domain} · {_desc(reg, pid)}")
        for rid, dom in _vocab.RESERVED.items():
            lines.append(f"{rid} · {dom} · {_vocab.reserved_desc(rid)}")
        if compact:
            lines.append(COMPACT_NOTE)
        lines.append(_vocab_line(reg, "fields", "분야"))
        lines.append(_vocab_line(reg, "functions", "기능"))
        lines.append(_vocab_line(reg, "activity_types", "업무유형"))
        return lines
    if stage == BOOT_STAGE:
        lines.append("[이미 있는 과제] 코드 · 업무영역 · 설명")
        for pid in ids:
            lines.append(f"{pid} · {reg.projects[pid].domain} · {_desc(reg, pid)}")
        if not ids:
            lines.append("(없음)")
        return lines
    return lines


def _desc(reg, pid: str) -> str:
    d = str(reg.projects[pid].copilot_desc or "").strip()
    return mask_registry_names(d, reg) if d else NO_DESC


def codes_for(reg) -> dict[str, list[str]]:
    """답 검증 코드 집합(H §6.5 F(codes=…)): projects = active ∪ 예약 5, projects_nonreserved = active, vocab.* = active."""
    act = reg.active_ids()
    return {"projects": act + list(_vocab.RESERVED), "projects_nonreserved": act,
            "vocab.field": reg.vocab_codes("fields"), "vocab.func": reg.vocab_codes("functions"),
            "vocab.wtype": reg.vocab_codes("activity_types")}


def set_hash(ids: Iterable[str]) -> str:
    """과제 목록 해시 sha1('|'.join(정렬 ID))[:8](H §6.6)."""
    return hashlib.sha1("|".join(sorted(ids)).encode("utf-8")).hexdigest()[:8]


def regv_for(prev_ans: Mapping | None, reg_now, reg_at_answer_hash: str) -> str:
    """재질의 표식(H §6.6): 과제 목록이 그대로면 '', 바뀌었고 이전 답이 NONE·NEW·예약·비active 면 새 목록 해시."""
    if prev_ans is None:
        return ""
    now = set_hash(reg_now.active_ids())
    if now == reg_at_answer_hash:
        return ""
    p = prev_ans.get("project")
    p_status = reg_now.projects[p].status if p in reg_now.projects else ""
    if p in ("NONE", "NEW") or p in _vocab.RESERVED or p_status != "active" or p not in reg_now.active_ids():
        return now
    return ""


# ───────────────────────── 이름 가리기 ─────────────────────────
class _Masker:
    def __init__(self, reg):
        pairs = []
        for pid in sorted(reg.projects):
            p = reg.projects[pid]
            if p.origin == "reserved":
                continue
            rep = reg.resolve(pid)
            for n in (p.name, *p.aliases, *p.codenames):
                n = unicodedata.normalize("NFKC", str(n or "")).strip()
                k = ukey(n)
                if len(k) >= (2 if _HANGUL.search(k) else 3):
                    pairs.append((n, rep))
        pairs.sort(key=lambda x: (-len(x[0]), x[0]))
        self.rx = None
        self.map: dict[str, str] = {}
        if pairs:
            for n, rep in pairs:
                self.map.setdefault(n.casefold(), rep)
            alts = "|".join(re.escape(n) for n, _r in pairs)
            self.rx = re.compile(r"(?<![0-9A-Za-z가-힣])(?:" + alts + r")(?![0-9A-Za-z])", re.I)

    def __call__(self, s: str) -> str:
        if not s or self.rx is None:
            return s
        t = unicodedata.normalize("NFKC", s)
        return self.rx.sub(lambda m: "[과제:" + self.map.get(m.group(0).casefold(), "") + "]", t)


_MASKERS: list = []


def mask_registry_names(text: str, reg) -> str:
    """정제문 안의 레지스트리 과제 이름·별칭·코드네임 → `[과제:<대표 ID>]`(긴 이름 먼저, 앞뒤 경계)."""
    for r, m in _MASKERS:
        if r is reg:
            return m(text)
    m = _Masker(reg)
    _MASKERS[:] = [(reg, m)]
    return m(text)


# ───────────────────────── 상대 계급(H §6.2 domains) ─────────────────────────
def domain_classes(labels: Iterable[str], public: Iterable[str] = ()) -> list[str]:
    """상대 계급 → 프롬프트 값: 사내 · [고객사:ID] · [협력사:ID] · 기관 · 외부(그 밖·개인메일). 원 도메인은 보내지 않는다."""
    pub = set(public) | {"기관", "학교", "공공", "협회"}
    out = []
    for lb in labels:
        if lb == "사내":
            out.append("사내")
        elif lb.startswith("고객사:"):
            out.append("[" + lb + "]")
        elif lb.startswith("협력사:"):
            out.append("[" + lb + "]")
        elif lb in pub:
            out.append("기관")
        elif lb and lb != "미상":
            out.append(OUTSIDE)
    return out


def _top(counter: Counter, n: int) -> list[str]:
    return [k for k, _v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n].rstrip()


# ───────────────────────── 재질의 상태(제목 캐시 ask) ─────────────────────────
def ask_state(cache_entry: Mapping | None, prev: Mapping | None, reg, n_ev: int, growth: float) -> dict:
    """군집의 재질의 상태 {regv, reg_set, n_ev}. 한 번 정한 regv 는 다음 계기까지 붙박인다(내용 키 안정 — 답이 오가며 흔들리지 않게)."""
    st = dict((cache_entry or {}).get("ask") or {})
    now = set_hash(reg.active_ids())
    regv = str(st.get("regv") or "")
    reg_at = str(st.get("reg_set") or (prev or {}).get("reg_set") or now)
    n_at = int(st.get("n_ev") or n_ev)
    if prev is not None and prev.get("by") in ("ai", "manual") and isinstance(prev.get("ans"), Mapping):
        ans = prev["ans"]
        new = regv_for(ans, reg, reg_at)
        if new:
            regv, reg_at, n_at = new, now, n_ev
        elif ans.get("conf") == "l" and n_at > 0 and n_ev >= growth * n_at:
            regv, n_at = f"g{n_ev}", n_ev
    return {"regv": regv, "reg_set": reg_at, "n_ev": n_at}


# ───────────────────────── task_label ai_in(H §6.1·§6.2) ─────────────────────────
def _need_ask(rl, title_src: str, ff, effort_min: int, cache: Mapping | None, reg, c) -> str:
    src = get(rl, "source", "none")
    if src in ("none", "rule_probable"):
        return "a"
    if src == "domain_rule":
        dom = get(rl, "domain", "")
        if any(reg.projects[p].domain == dom for p in reg.active_ids()):
            return "a"
    if c["ask_title_weak"] and title_src in ("app", "generic", "rule_app", "rule_generic"):
        ce = cache or {}
        if not (ce.get("src") == "user" or (ce.get("src") == "ai" and ce.get("conf") in ("h", "m"))):
            return "b"
    if ff is not None and get(ff, "field_conf", "l") == "l" and get(ff, "func_conf", "l") == "l" and \
            effort_min >= c["vocab_min"]:
        return "c"
    return ""


def build_task_label_items(groups: Iterable, labels: Mapping, ff: Mapping, wt: Mapping, store_index: Mapping | None,
                           reg, cfg=None, *, units: Mapping, titles: Mapping[str, tuple[str, str]],
                           cache=None, user_units: Iterable[str] = (), rules_ver: str = "",
                           pub_classes: Iterable[str] = ()) -> tuple[list[dict], dict]:
    """task_label ai_in 항목(정렬 = 군집 투입 내림차순). 반환 (항목 목록, 통계 {selected, skipped_cap, reasons}).
    labels = {unit_id: RuleLabel}(규칙 판정), ff = {unit_id: FieldFunc}, wt = {unit_id: (유형, 확신, 근거)},
    store_index = 이전 ai_out 항목 {군집 키: {ans, by, …}}, titles = {군집 키: (규칙 이름, 출처)}, cache = TitleCache."""
    cfg = default_cfg(cfg)
    c = {"ask_title_weak": bool(cfg["hier.copilot.askTitleWeak"]),
         "vocab_min": int(round(float(cfg["hier.copilot.vocabAskMinEffortH"]) * 60)),
         "max_groups": int(cfg["hier.copilot.maxGroupsPerRun"]), "growth": float(cfg["hier.copilot.reaskGrowth"]),
         "title_max": int(cfg["hier.name.titleMax"])}
    users = set(user_units)
    gs = sorted(groups, key=lambda g: (-int(g.effort_min), g.key))
    items: list[dict] = []
    stats = Counter()
    for g in gs:
        if any(m in users for m in g.members):
            stats["user_label"] += 1
            continue
        rl = labels.get(g.rep)
        title, tsrc = titles.get(g.key, ("", "generic"))
        ce = cache.get(g.key) if cache is not None else None
        why = _need_ask(rl, tsrc, ff.get(g.rep), int(g.effort_min), ce, reg, c)
        if not why:
            stats["rule_final"] += 1
            continue
        if len(items) >= c["max_groups"]:
            stats["skipped_cap"] += 1
            continue
        stats["why_" + why] += 1
        items.append(_item(g, rl, ff.get(g.rep), wt.get(g.rep), units, title, tsrc, store_index, cache, reg, c,
                           rules_ver, pub_classes))
    stats["selected"] = len(items)
    return items, dict(sorted(stats.items()))


def _member_feats(g, units: Mapping):
    for m in g.members:
        u = units.get(m)
        if u is None:
            continue
        for f, _w, r in get(u, "ev", ()) or ():
            yield m, f, r


def _item(g, rl, ffr, wtr, units, title, tsrc, store_index, cache, reg, c, rules_ver, pub_classes) -> dict:
    kinds: Counter = Counter()
    labels: Counter = Counter()
    cat_min: Counter = Counter()
    app_min: Counter = Counter()
    fam_min: Counter = Counter()
    fam_name: dict[str, str] = {}
    n_ev = 0
    for m in g.members:
        u = units.get(m)
        if u is None:
            continue
        for k, v in (get(u, "kinds", {}) or {}).items():
            kinds[k] += int(v)
        for cat, v in (get(u, "app_min", {}) or {}).items():
            cat_min[cat] += int(v)
        for a, v in (get(u, "app_ids", {}) or {}).items():
            app_min[a] += int(v)
        for fk, nm in (get(u, "fam_names", {}) or {}).items():
            fam_min[fk] += int((get(u, "fam_min", {}) or {}).get(fk, 0))
            if fk not in fam_name or nm > fam_name[fk]:
                fam_name[fk] = nm
    app_cat: dict[str, str] = {}
    for _m, f, _r in _member_feats(g, units):
        n_ev += 1
        for lb in domain_classes(sorted(f.dom_labels), pub_classes):
            labels[lb] += 1
        if f.app:
            app_cat.setdefault(f.app, f.app_cat)
    kind_s = "·".join(f"{k} {kinds[k]}" for k in KIND_LABELS if kinds.get(k))
    rep = units.get(g.rep)
    subjects, seen = [], set()
    for s in get(rep, "subjects", ()) or ():
        s2 = _clip(mask_registry_names(s, reg), 60)
        if s2 and ukey(s2) not in seen:
            seen.add(ukey(s2))
            subjects.append(s2)
    names = sorted(fam_name, key=lambda fk: (is_generic_key(fk), -fam_min[fk], fam_name[fk]))
    files, fseen = [], set()
    for fk in names:
        nm = _clip(mask_registry_names(fam_name[fk], reg), 40)
        if nm and nm not in fseen:
            fseen.add(nm)
            files.append(nm)
        if len(files) >= 5:
            break
    name_min: Counter = Counter()
    for a, v in app_min.items():
        cat = app_cat.get(a, "")
        if not cat and not a.startswith("unknown:"):            # 카탈로그에 있으나 범주 없는 앱(탐색기·유틸) — 단서 아님
            continue
        name_min[app_cat_name(cat, a)] += int(v)
    for cat, v in cat_min.items():                               # 창 특징이 없는 범주(귀속 분만) — 범주 이름
        if any(app_cat.get(a) == cat for a in app_min):
            continue
        name_min[app_cat_name(cat)] += int(v)
    apps = _top(name_min, 3)
    cands = [[p, s] for p, s in (get(rl, "cands", ()) or ())]
    if get(rl, "source", "") == "domain_rule":
        rp = get(rl, "project", None)
        cands = [[rp, get(rl, "score", 0.0)]] + [x for x in cands if x[0] != rp]
    cands = cands[:3]
    fcode = reg.team_code("fields", get(ffr, "field", "ETC") or "ETC")
    ccode = reg.team_code("functions", get(ffr, "func", "ETC") or "ETC")
    wcode = reg.team_code("activity_types", (wtr[0] if wtr else "OFFICE") or "OFFICE")
    prev = (store_index or {}).get(g.key)
    st = ask_state(cache.get(g.key) if cache is not None else None, prev, reg, n_ev, c["growth"])
    if cache is not None:
        cache.put(g.key, ask=st)
    fields = {"kinds": _clip(kind_s, 60), "subjects": subjects[:3], "files": files[:5], "apps": apps[:3],
              "domains": _top(labels, 3), "cands": cands, "hint": f"{fcode}/{ccode}/{wcode}", "regv": st["regv"]}
    tsrc_s = tsrc if tsrc.startswith("rule_") or tsrc in ("user", "ai") else "rule_" + tsrc
    rule = {"project": get(rl, "project", None), "score": get(rl, "score", 0.0), "source": get(rl, "source", "none"),
            "field": fcode, "func": ccode, "wtype": wcode, "title": clip_title(title, c["title_max"]),
            "title_src": tsrc_s, "reg_set": set_hash(reg.active_ids())}
    return {"key": g.key, "group": cands[0][0] if cands else "", "fields": fields, "rule": rule,
            "src_ver": HIER_VERSION, "meta": {"priv_class": "work", "ad_band": "keep", "rules_ver": rules_ver}}


def write_ai_in(paths, stage: str, items: Iterable[Mapping]) -> int:
    """`data\\derived\\ai_in\\<stage>.jsonl` 원자 쓰기(한 줄 = 항목, 정규 JSON). 쓴 항목 수."""
    lines = [fsx.canon_bytes(dict(it)).decode("utf-8") for it in items]
    data = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    fsx.atomic_write(paths.ai_in(stage), data)
    return len(lines)


def read_ai_out(path) -> dict[str, dict]:
    """`ai_out\\<stage>.json` → {key: {ans, by, rid, asks, at, reg_set?}}. 없거나 깨졌으면 {}(경고는 fsx.read_json)."""
    obj = fsx.read_json(path, default=None)
    if not isinstance(obj, Mapping):
        return {}
    items = obj.get("items")
    if not isinstance(items, Mapping):
        return {}
    out = {}
    for k in sorted(items):
        v = items[k]
        if isinstance(v, Mapping) and isinstance(v.get("ans"), Mapping):
            d = {"ans": dict(v["ans"]), "by": str(v.get("by") or ""), "rid": v.get("rid"), "asks": v.get("asks"),
                 "at": v.get("at")}
            if v.get("reg_set"):
                d["reg_set"] = str(v["reg_set"])
            out[str(k)] = d
    return out


# ───────────────────────── 답 검증(H §6.5) ─────────────────────────
def validate_answer(a: Mapping, codes: Mapping[str, Iterable[str]], ids: Iterable[int] | None = None) -> str:
    """task_label 답 항목 하나 → 사유('' = 통과). 시간형 키 · 목록 밖 코드 · 제목 길이 · 금액 패턴 · NEW 의 new/dom."""
    if ids is not None:
        try:
            i = int(str(a.get("id")).strip())
        except (TypeError, ValueError):
            return "extra"
        if i not in set(ids):
            return "extra"
    for k in a:
        if _TIME_KEY.match(str(k)):
            return "forbidden_field"
    projects = set(codes.get("projects", ())) | {"NONE", "NEW"}
    if not isinstance(a.get("project"), str) or a.get("project") not in projects:
        return "unknown_code:project"
    for f, ck in (("field", "vocab.field"), ("func", "vocab.func"), ("wtype", "vocab.wtype")):
        if not isinstance(a.get(f), str) or a.get(f) not in set(codes.get(ck, ())):
            return f"unknown_code:{f}"
    if not isinstance(a.get("title", ""), str) or not isinstance(a.get("new", "") or "", str):
        return "bad_type:title"
    t = str(a.get("title", "") or "")
    if len(t) < 2:
        return "too_short:title"
    if len(t) > 80:
        return "too_long:title"
    if _MONEY.search(t) or _MONEY.search(str(a.get("new", "") or "")):
        return "bad_pattern:title"
    if not isinstance(a.get("conf"), str) or a.get("conf") not in ("h", "m", "l"):
        return "bad_enum:conf"
    if a.get("dom") is not None and (not isinstance(a.get("dom"), str) or a.get("dom") not in ("", *_vocab.DOMAINS)):
        return "bad_enum:dom"
    if a["project"] == "NEW":
        if len(str(a.get("new", "") or "")) < 2:
            return "missing:new"
        if a.get("dom") not in _vocab.DOMAINS:
            return "missing:dom"
    return ""


# ───────────────────────── taxonomy_bootstrap · consolidate(H §8.2·§8.3) ─────────────────────────
def build_bootstrap_samples(groups: Iterable, labels: Mapping, reg, cfg=None, *, units: Mapping,
                            titles: Mapping[str, tuple[str, str]], pub_classes: Iterable[str] = ()) -> list[dict]:
    """부트스트랩 표본(H §8.2): 투입 내림차순, 같은 규칙 이름(ukey) 3개까지, 최대 `hier.bootstrap.maxLines` 줄.
    항목 `{key, group, fields{dom, title, files, subject, peer}, rule}` — 입력 예산 맞추기는 `fit_lines`."""
    cfg = default_cfg(cfg)
    max_lines = int(cfg["hier.bootstrap.maxLines"])
    per_name: Counter = Counter()
    out = []
    for g in sorted(groups, key=lambda x: (-int(x.effort_min), x.key)):
        title, _src = titles.get(g.key, ("", ""))
        k = ukey(title)
        if per_name[k] >= 3:
            continue
        per_name[k] += 1
        rl = labels.get(g.rep)
        dom = get(rl, "domain", "UNC")
        rep = units.get(g.rep)
        fam_name = dict(get(rep, "fam_names", {}) or {})
        fam_min = dict(get(rep, "fam_min", {}) or {})
        names = sorted(fam_name, key=lambda fk: (is_generic_key(fk), -int(fam_min.get(fk, 0)), fam_name[fk]))
        files = [_clip(mask_registry_names(fam_name[fk], reg), 40) for fk in names[:2]]
        subs = list(get(rep, "subjects", ()) or ())
        subject = _clip(mask_registry_names(subs[0], reg), 50) if subs else ""
        lbs: Counter = Counter()
        for _m, f, _r in _member_feats(g, units):
            for lb in domain_classes(sorted(f.dom_labels), pub_classes):
                lbs[lb] += 1
        out.append({"key": g.key, "group": "", "fields": {
            "dom": dom if dom in _vocab.DOMAINS else "-", "title": mask_registry_names(title, reg),
            "files": files, "subject": subject, "peer": ", ".join(_top(lbs, 2))},
            "rule": {"title": title, "domain": dom}, "src_ver": HIER_VERSION,
            "meta": {"priv_class": "work", "ad_band": "keep", "rules_ver": ""}})
        if len(out) >= max_lines:
            break
    return out


def fit_lines(line_lens: Iterable[int], fixed_chars: int, budget: int) -> int:
    """고정부 + 줄(줄바꿈 1자 포함)이 입력 예산 안에 드는 앞쪽 줄 수 — 뒤에서부터 뺀다(H §8.2)."""
    lens = list(line_lens)
    k = len(lens)
    total = fixed_chars + sum(n + 1 for n in lens)
    while k > 0 and total > budget:
        k -= 1
        total -= lens[k] + 1
    return k


def build_consolidate_items(rows: Iterable[Mapping], proposals: Iterable[Mapping], reg=None) -> list[dict]:
    """통합 확인 항목(H §8.3): 1회차 code=''·kind ∈ {project, common} 행(≤ 15) + pending 제안(≤ 15).
    필드 {name, dom, match(≤3)}. 키는 이름 ukey 의 해시."""
    out, seen = [], set()

    def add(name: str, dom: str, match: Iterable[str], origin: str) -> None:
        k = ukey(name)
        if not k or k in seen:
            return
        seen.add(k)
        def msk(t: str) -> str:
            return mask_registry_names(t, reg) if reg is not None else t
        out.append({"key": "cs:" + hashlib.sha1(k.encode("utf-8")).hexdigest()[:12], "group": "",
                    "fields": {"name": msk(name), "dom": dom if dom in _vocab.DOMAINS else "-",
                               "match": [msk(str(m))[:20] for m in list(match)[:3]]},
                    "rule": {"name": name, "origin": origin}, "src_ver": HIER_VERSION,
                    "meta": {"priv_class": "work", "ad_band": "keep", "rules_ver": ""}})
    n = 0
    for r in rows:
        if n >= 15:
            break
        if str(r.get("code") or "") == "" and r.get("kind") in ("project", "common") and r.get("name"):
            add(str(r["name"]), str(r.get("dom") or ""), r.get("match") or (), "bootstrap")
            n += 1
    m = 0
    for p in sorted(proposals, key=lambda x: str(x.get("proposal_id") or "")):
        if m >= 15:
            break
        if p.get("status") == "pending":
            add(str(p.get("label") or ""), str(p.get("domain_guess") or ""), p.get("match_words") or (), "proposal")
            m += 1
    return out


def display_name(name: str) -> str:
    """파일 이름 → 표시 줄기(확장자·판 꼬리 제거)."""
    return display_stem(name)
