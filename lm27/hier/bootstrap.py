# -*- coding: utf-8 -*-
r"""레지스트리가 빈 초기 — 코드네임 후보 검토 · 코파일럿 단계 열림 판정 · taxonomy 부트스트랩 결과 처리(H §8 · §3.5).

- `codename_candidates(feats, groups, reg, cfg)` — 코파일럿을 열기 전에 **내 PC 에서만** 코드네임 후보를 보여 준다(H §8.1).
  재료는 정제문(메일·회의 제목, 첨부·파일 이름, 창 제목, 그룹 대화방 이름)뿐이다. 상용구·어휘·영역 키워드·범용 줄기·업무
  일반어(`common_words.txt`)·프로그램 이름·이미 등록된 이름·무시한 후보(`codename_review.ignored` = ukey sha1 앞 8자)를 빼고,
  군집 ≥ `hier.bootstrap.codenameMinGroups` · 주 ≥ `codenameMinWeeks` 인 낱말을 점수(코드 모양 2.0 · 파일 이름 접두 1.0 ·
  꺾쇠 1.0 · 0.5×log2(군집 수) · 4주 이상 0.5) 순으로 `codenameTopN` 개.
- `copilot_allowed(reg, cfg)` — `hier.copilot.requireCodenameReview` 이면 레지스트리에 비예약 과제가 하나도 없고 검토를 마치거나
  건너뛰지 않은 동안 코파일럿 분류를 열지 않는다(H §3.5 · T-H05 — 분석은 막지 않고 안내 한 줄).
- `needs_bootstrap(reg, labels, last_run, cfg)` — 1회차 자동 조건(H §8.2): 비예약 active 과제 0 · 명명 군집 ≥ `minGroups` ·
  검토 완료/건너뜀, 또는 최근 30일 투입 중 미분류·예약·제안 비중 ≥ `unclassifiedShare` 이고 지난 부트스트랩 뒤 ≥ `cooldownDays`.
- `apply_bootstrap(rows, ...)` — 1회차 답 처리(H §8.4): 행 수가 `hier.bootstrap.maxModels` 를 넘으면 넘는 행은 버리고
  `caps_hit`(§8.2) · code 있음 → 보고에만 · code='' project → 제안 · common → 제안(영역 COM·EXT 밖이면 COM) · nonwork →
  표식만(시간·라벨 불변). `consolidate_pairs` — 2회차 답 h·m 쌍만 AI 통합 근거(+1.0)로(제안 큐 `consolidate` 가 S2 점수로 본다).
  부트스트랩은 과제를 만들지 않는다 — 제안 큐로만 간다(H-I6). 코드네임 검토의 버튼 기록은 `proposals.from_codename`·
  `mark_codename_review`(개인 로컬 레지스트리 쓰기는 그 모듈 하나).

표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from lm27.hier import match as _match
from lm27.hier import vocab as _vocab
from lm27.hier.features import default_cfg, get
from lm27.hier.learn import excluded_tokens
from lm27.hier.names import ukey
from lm27.hier.proposals import codename_hash
from lm27.time.calendar import d_of

__all__ = [
    "CODE_RX", "Cand", "apply_bootstrap", "codename_candidates", "consolidate_pairs", "copilot_allowed",
    "is_code_like", "needs_bootstrap", "review_state",
]

CODE_RX = re.compile(r"[A-Za-z]{1,8}[-_]?\d{1,4}[A-Za-z]?|[A-Z][A-Z0-9]{1,7}[-_][A-Z0-9]{1,4}|[A-Z][A-Z0-9]{2,}")
_CODE_FULL = re.compile(r"(?:[A-Za-z]{1,8}[-_]?\d{1,4}[A-Za-z]?|[A-Z][A-Z0-9]{1,7}[-_][A-Z0-9]{1,4}|[A-Z][A-Z0-9]{2,})")
WINDOW_DAYS = 30


@dataclass(frozen=True)
class Cand:
    token: str                       # 표기(첫 관측 표기)
    score: float
    n_groups: int
    n_weeks: int
    examples: tuple[str, ...] = ()   # 정제문 예시(로컬 화면 전용)
    hash8: str = ""                  # sha1(ukey)[:8] — [무시] 기록용


def is_code_like(t: str) -> bool:
    return bool(_CODE_FULL.fullmatch(str(t or "")))


def _hash8(t: str) -> str:
    return codename_hash(t)


def _app_names() -> frozenset[str]:
    from lm27 import catalog                        # 지연 import — 프로그램 카탈로그 표시 이름(APP_NAMES)
    out = set()
    for p in catalog.entries():
        out.add(ukey(p.name))
        out.update(ukey(w) for w in re.split(r"[\s/·]+", p.name) if len(w) >= 2)
    return frozenset(x for x in out if x)


def codename_candidates(feats: Iterable, groups: Iterable, reg, cfg=None, *,
                        feat_groups: Mapping[str, str] | None = None) -> list[Cand]:
    """코드네임 후보(H §8.1). feat_groups = 특징 id → 군집 키(없으면 특징의 단위업무를 모른다 — 특징 id 를 군집으로 센다)."""
    cfg = default_cfg(cfg)
    top_n = int(cfg["hier.bootstrap.codenameTopN"])
    min_g = int(cfg["hier.bootstrap.codenameMinGroups"])
    min_w = int(cfg["hier.bootstrap.codenameMinWeeks"])
    review = reg.codename_review or {}
    ignored = {str(x) for x in (review.get("ignored") or ())}
    excl = set(excluded_tokens(reg, cfg))
    for kind in ("fields",):
        for it in reg.vocab.get(kind, {}).values():
            excl.update(str(x).lower() for x in it.keywords)
    common = _match.common_words()
    apps = _app_names()
    fg = feat_groups or {}
    stats: dict[str, dict] = {}
    feats = list(feats)
    exts = {e.lstrip(".").lower() for f in feats for e in f.exts if e}           # 파일 확장자 조각은 과제 이름이 아니다
    for f in feats:
        if f.kind not in ("mail", "cal", "teams", "file", "win", "summary"):
            continue
        raw = unicodedata.normalize("NFKC", f.text or "")
        if not raw:
            continue
        toks = set(CODE_RX.findall(raw)) | _match.match_tokens(raw)
        low = raw.lower()
        week = ""
        if f.t:
            y, w, _ = d_of(f.t).isocalendar()
            week = f"{y}-{w:02d}"
        names = [nm for _fk, nm in f.names] if f.names else ([raw] if f.kind == "file" else [])
        for t in toks:
            k = ukey(t)
            if len(k) < 2:
                continue
            s = stats.setdefault(k, {"tok": t, "groups": set(), "weeks": set(), "n": 0, "prefix": 0, "br": False,
                                     "ex": []})
            s["groups"].add(fg.get(f.id, f.id))
            if week:
                s["weeks"].add(week)
            s["n"] += 1
            if any(ukey(nm).startswith(k) for nm in names):
                s["prefix"] += 1
            if "[" + t.lower() + "]" in low:
                s["br"] = True
            subj = f.subject or raw
            if len(s["ex"]) < 3 and subj not in s["ex"]:
                s["ex"].append(subj[:80])
    out = []
    for k, s in stats.items():
        t = s["tok"]
        if t.lower() in excl or k in excl or t.lower() in common or k in common or k in apps or k in exts:
            continue
        if k in reg.alias_ix or _hash8(t) in ignored:
            continue
        ng, nw = len(s["groups"]), len(s["weeks"])
        if ng < min_g or nw < min_w:
            continue
        sc = 2.0 * is_code_like(t) + 1.0 * (s["prefix"] / max(s["n"], 1) >= 0.5) + 1.0 * s["br"] \
            + 0.5 * math.log2(ng) + 0.5 * (nw >= 4)
        out.append(Cand(t, round(sc, 3), ng, nw, tuple(s["ex"]), _hash8(t)))
    out = _drop_covered(out, stats)
    return sorted(out, key=lambda c: (-c.score, c.token))[:top_n]


RULE_AUTO_MAX = 8                 # 규칙 제안 과제 상한(LM24 규칙 대체 — 자주 나온 규칙 과제 8개)
RULE_AUTO_MIN_GROUPS = 2          # 그 이름이 든 미분류 군집이 이만큼은 돼야 과제로 세운다(LM24 — 근거 2개 이상)


def rule_auto_projects(labels: Mapping, groups: Iterable, units: Mapping, feats: Iterable, reg, cfg, props, *,
                       ai: Mapping | None = None, at: str = "") -> dict:
    """AI 답이 없고 과제를 못 정한(UNC) 군집에 '자주 나온 이름'(코드네임 후보 점수 — H §8.1)으로 **규칙 제안 과제**를 붙인다
    (계약 v1.3 §0.8 V15 — LM24 의 규칙 대체 '지정 과제 + 자주 나온 규칙 과제'와 같은 자리). 팀·개인 과제가 하나도 없을 때만
    (`hier.ruleAutoProjects`, 기본 켜짐). 제안은 사람이 받기 전까지 과제가 아니다(H-I6) — MM 은 제안 과제로 계상(H §7.1).
    AI 답이 있는 군집(NONE 포함)·사람이 고친 단위업무는 건드리지 않는다. labels 를 제자리에서 고치고 통계를 돌려준다."""
    from collections import Counter

    from lm27.hier.apply import level_of, role_slot
    from lm27.hier.unitlabel import role_id
    cfg = default_cfg(cfg)
    st: Counter = Counter()
    if not bool(cfg["hier.ruleAutoProjects"]) or _non_reserved(reg):
        return {}
    ai = ai or {}
    gl = list(groups)
    todo = []
    for g in gl:
        rep = labels.get(g.rep)
        hit = ai.get(g.key)
        if rep is None or rep.project or rep.proposal_id or (isinstance(hit, Mapping) and hit.get("by") in ("ai", "manual")):
            continue
        if any(getattr(labels.get(m), "src", {}).get("project") == "user" for m in g.members):
            continue
        todo.append(g)
    if not todo:
        return {}
    feat_groups = {}
    toks_of: dict[str, set] = {}
    for g in gl:
        ks = toks_of.setdefault(g.key, set())
        for m in g.members:
            u = units.get(m)
            for f, _w, _r in (get(u, "ev", ()) or ()) if u is not None else ():
                feat_groups[f.id] = g.key
                raw = unicodedata.normalize("NFKC", f.text or "")
                if raw:
                    ks.update(ukey(t) for t in set(CODE_RX.findall(raw)) | _match.match_tokens(raw))
    cands = codename_candidates(feats, gl, reg, cfg, feat_groups=feat_groups)
    st["todo"], st["names"] = len(todo), len(cands)
    rank = {ukey(c.token): (i, c.token) for i, c in enumerate(cands)}
    # LM24 의 규칙 대체처럼 '자주 나온 이름 상위 8개, 각각 근거 군집 2개 이상'만 과제로 세운다 — 이름마다 과제를 세우면 잘게 흩어진다
    cover: dict[str, list] = defaultdict(list)
    for g in todo:
        for k in toks_of.get(g.key, ()):
            if k in rank:
                cover[k].append(g.key)
    chosen: list[str] = []
    for k in sorted(cover, key=lambda x: (-len(cover[x]), rank[x][0])):
        if len(chosen) >= RULE_AUTO_MAX or len(cover[k]) < RULE_AUTO_MIN_GROUPS:
            break
        chosen.append(k)
    pick_rank = {k: i for i, k in enumerate(chosen)}
    for g in todo:
        hits = sorted((pick_rank[k], rank[k][1]) for k in toks_of.get(g.key, ()) if k in pick_rank)
        if not hits:
            st["no_name"] += 1
            continue
        rep = labels[g.rep]
        dom = rep.domain if rep.domain in _vocab.DOMAINS else "DEV"
        asg = props.on_new_name(hits[0][1], dom, g.key, "bootstrap", reg, cfg=cfg, effort_min=int(g.effort_min),
                                conf="l", at=at)
        pid = getattr(asg, "proposal", None)
        if not pid:
            st["skip_" + (str(getattr(asg, "src", "") or "none"))] += 1
            continue
        for m in g.members:
            lb = labels.get(m)
            if lb is None or lb.src.get("project") == "user":
                continue
            lb.project, lb.proposal_id = None, pid
            lb.domain = props.dom_of(pid)
            for fl in ("proposal", "rule_auto"):
                if fl not in lb.flags:
                    lb.flags.append(fl)
            lb.src["project"], lb.conf["project"] = "rule", "l"
            lb.level = level_of("rule", "l", None, pid, None)
            lb.role_id = role_id(role_slot(None, pid, reg), lb.field, lb.func)
        st["assigned"] += 1
    return dict(sorted(st.items()))


def _drop_covered(cands: list[Cand], stats: Mapping[str, Mapping]) -> list[Cand]:
    """코드 모양 후보(예 PROJ-X)의 조각(proj)이 같은 군집에서만 나오면 조각은 뺀다 — 같은 이름을 두 번 묻지 않는다."""
    code = [(ukey(c.token), stats[ukey(c.token)]["groups"]) for c in cands if is_code_like(c.token)]
    keep = []
    for c in cands:
        k = ukey(c.token)
        if any(k != ck and k in ck and stats[k]["groups"] <= cg for ck, cg in code):
            continue
        keep.append(c)
    return keep


def _non_reserved(reg) -> list[str]:
    return [pid for pid, p in reg.projects.items() if p.origin != "reserved"]


def review_state(reg) -> str:
    """초기 코드네임 검토 상태: not_needed(비예약 과제 있음) · done · skipped · pending."""
    if _non_reserved(reg):
        return "not_needed"
    r = reg.codename_review or {}
    if r.get("skipped"):
        return "skipped"
    if r.get("done_at"):
        return "done"
    return "pending"


def copilot_allowed(reg, cfg=None) -> tuple[bool, str]:
    """코파일럿 분류 단계를 열어도 되는가(H §3.5·§8.1). (가능, 안내 문구 — 막히면 한 줄)."""
    cfg = default_cfg(cfg)
    if not bool(cfg["hier.copilot.requireCodenameReview"]):
        return True, ""
    st = review_state(reg)
    if st == "pending":
        return False, "과제 이름 후보를 확인하면 코파일럿 분류를 켭니다"
    if st == "skipped":
        return True, "레지스트리 없이 코파일럿을 쓰면 제목 속 과제 이름이 그대로 갈 수 있습니다"
    return True, ""


def needs_bootstrap(reg, labels: Mapping, last_run: str | date | None, cfg=None, *, groups: Iterable = (),
                    user_request: bool = False, as_of: date | None = None) -> bool:
    """taxonomy_bootstrap 1회차를 돌릴까(H §8.2). last_run = 지난 부트스트랩 날짜(없으면 None)."""
    cfg = default_cfg(cfg)
    if user_request:
        return True
    min_groups = int(cfg["hier.bootstrap.minGroups"])
    share_min = float(cfg["hier.bootstrap.unclassifiedShare"])
    cooldown = int(cfg["hier.bootstrap.cooldownDays"])
    gl = list(groups)
    if not reg.active_ids() and len(gl) >= min_groups and review_state(reg) in ("done", "skipped"):
        return True
    today = as_of
    if today is None:
        return False
    if last_run:
        lr = last_run if isinstance(last_run, date) else date.fromisoformat(str(last_run)[:10])
        if (today - lr).days < cooldown:
            return False
    lo = today - timedelta(days=WINDOW_DAYS)
    tot = weak = 0
    for g in gl:
        t = int(get(g, "last_t", 0) or 0)
        if not t or d_of(t) < lo:
            continue
        lab = labels.get(g.rep)
        eff = int(g.effort_min)
        tot += eff
        proj = get(lab, "project", None)
        if proj is None or str(proj).startswith("P-99"):          # 미분류·제안 과제(과제 자리 없음)·예약 과제
            weak += eff
    return bool(tot) and weak / tot >= share_min


def apply_bootstrap(rows: Iterable[Mapping], samples: list[Mapping], proposals, reg, cfg=None, *,
                    efforts: Mapping[str, int] | None = None, at: str = "", label_check=None) -> dict:
    """1회차 답 처리(H §8.4). rows = 답 행 {name, code, dom, kind, match, obs}, samples = 보낸 표본(번호 = 위치 + 1).
    행 수가 `hier.bootstrap.maxModels` 를 넘으면 넘는 행은 버린다(§8.2 — `caps_hit`).
    반환 {report: [(행 id, 코드, 표본 번호)], proposals: [(행 id, Assign)], nonwork: [군집 키], caps_hit: 버린 행 수}."""
    cfg = default_cfg(cfg)
    cap = int(cfg["hier.bootstrap.maxModels"])
    rows = list(rows)
    out = {"report": [], "proposals": [], "nonwork": [], "caps_hit": max(0, len(rows) - cap)}
    seen = set()
    for i, r in enumerate(rows[:cap], start=1):
        obs = [int(x) for x in (r.get("obs") or ()) if isinstance(x, int) and 1 <= x <= len(samples)]
        keys = [str(samples[x - 1].get("key")) for x in obs]
        code = str(r.get("code") or "")
        kind = r.get("kind")
        if code:
            out["report"].append((i, code, obs))
            continue
        if kind == "nonwork":
            out["nonwork"].extend(keys)
            continue
        name = str(r.get("name") or "")
        k = ukey(name)
        if kind not in ("project", "common") or len(k) < 2 or k in seen:
            continue
        seen.add(k)
        dom = str(r.get("dom") or "")
        if kind == "common" and dom not in ("COM", "EXT"):
            dom = "COM"
        if dom not in _vocab.DOMAINS:
            continue
        eff = sum(int((efforts or {}).get(key, 0)) for key in keys)
        first = keys[0] if keys else ""
        asg = proposals.on_new_name(name, dom, first, "bootstrap", reg, cfg=cfg, effort_min=eff, conf="m", at=at,
                                    label_check=label_check)
        p = proposals.get(asg.proposal) if asg.proposal else None
        if p is not None:
            for key in keys[1:]:
                if key not in p["groups"]:
                    p["groups"] = sorted(set(p["groups"]) | {key})
            mw = [str(w)[:20] for w in (r.get("match") or ())][:5]
            p["match_words"] = sorted(set(p.get("match_words") or ()) | set(mw))
        out["proposals"].append((i, asg))
    out["nonwork"] = sorted(set(out["nonwork"]))
    return out


def consolidate_pairs(answers: Iterable[Mapping], items: list[Mapping]) -> frozenset:
    """2회차 답 → AI 통합 제안 쌍(ukey frozenset) — conf h·m 인 (id, same_as) 만(H §8.3). 자기 자신·범위 밖은 버린다."""
    pairs = set()
    for a in answers:
        try:
            i = int(a.get("id"))
            j = int(a.get("same_as"))
        except (TypeError, ValueError):
            continue
        if a.get("conf") not in ("h", "m") or j == 0 or i == j or not (1 <= i <= len(items)) or \
                not (1 <= j <= len(items)):
            continue
        na = str((items[i - 1].get("rule") or {}).get("name") or (items[i - 1].get("fields") or {}).get("name") or "")
        nb = str((items[j - 1].get("rule") or {}).get("name") or (items[j - 1].get("fields") or {}).get("name") or "")
        if ukey(na) and ukey(nb) and ukey(na) != ukey(nb):
            pairs.add(frozenset((ukey(na), ukey(nb))))
    return frozenset(pairs)


def domain_vote(feats: Iterable, reg) -> str:
    """후보가 나온 증거의 영역 키워드 다수결(없으면 DEV) — [과제 이름] 으로 표시할 때의 기본 영역(H §8.1)."""
    from lm27.hier.rules import rule_ctx, score_domains
    c = rule_ctx(reg)
    votes: dict[str, float] = defaultdict(float)
    for f in feats:
        for d, v in score_domains(f, reg, ctx=c).items():
            votes[d] += v
    if not votes:
        return "DEV"
    return min(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
