# -*- coding: utf-8 -*-
r"""라벨 적용 — 규칙 판정 + 코파일럿 답 + 사용자 수정 + 제목 캐시 → `UnitLabel`(H §6.5 · §5.4 · §11.1, 계약 §3.15).

- 우선순위(큰 쪽이 이긴다): user 100 · token 85 · rule 80 · domain_rule 75 · ai_h 70 · rule_probable 60 · ai_m 55 · ai_l 30 ·
  none·폴백 0~10. 예외 '구체화' — 규칙이 예약 과제(domain_rule)이고 AI 가 **같은 영역의 등록 과제**를 h·m 로 고르면 AI 가 이긴다.
- 충돌 질문 H02: AI h 가 규칙 확정 과제와 다르면(규칙 유지) · AI h 가 규칙 유력(≥ 0.4) 1위와 다른 과제로 이기면. AI m 은 규칙
  유력을 이기지 못한다. NONE 은 규칙 과제(예약·유력)가 있으면 그대로, 없으면 UNC. NEW 는 제안 큐(`ProposalQueue.on_new_name`)로 —
  라벨 과제 자리 = proposal_id, 영역 = domain_guess(`ai_out.proposals` 폐지 — X-252).
- 분야·기능·유형: 규칙 확신 h → 규칙, m → AI h 가 이김, l → AI h·m 이 이김. AI l 은 규칙을 이기지 못한다.
- 이름(H §5.4): 사용자 입력 > 캐시(사용자) > 캐시(AI h·m) > 이번 AI 답(h·m) > 규칙 이름(doc·subject) > AI 답(l) > 규칙 이름(app·generic).
  title_src 저장값 = user · ai · rule_doc · rule_subject · rule_app · rule_generic(계약 §3.15). 폴백 제목 = 규칙 이름(X-252).
- 영역은 과제에서 **유도**한다(H-I2): 등록·개인·예약 과제는 유효 레지스트리, 제안은 domain_guess, 과제 없음은 UNC.
  role_id 는 R-8 식(과제 자리 = P-ID · 제안 ID(개인 과제는 그 제안 ID) · 'UNC').
- 코파일럿 답은 이름·분류만 바꾸고 시간 값을 바꾸지 않는다. 답은 현재 레지스트리로 다시 검증한다(퇴역 과제는 옛 라벨 + 표식).

표준 라이브러리만 쓴다. 파일을 쓰지 않는다(제목 캐시·제안 큐 객체를 갱신만 — 저장은 호출자).
"""
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as _dc_field

from lm27.hier import vocab as _vocab
from lm27.hier.copilot_io import PROMPT_VER, codes_for, validate_answer
from lm27.hier.features import default_cfg, get
from lm27.hier.groups import clip_title
from lm27.hier.unitlabel import ax_link, decide_stance, role_id

__all__ = ["LEVELS", "RANK", "SRC_VALUES", "UnitLabel", "apply_labels", "level_of", "merge_project", "role_slot"]

RANK = {"user": 100, "token": 85, "rule": 80, "domain_rule": 75, "ai_h": 70, "rule_probable": 60, "ai_m": 55,
        "ai_l": 30, "fallback": 10, "none": 0}
SRC_VALUES = ("user", "token", "rule", "domain_rule", "rule_probable", "ai_h", "ai_m", "ai_l", "fallback", "none")
LEVELS = ("confirmed", "high", "medium", "low", "unclassified")
_TITLE_TOKENS = re.compile(r"\[과제:[^\]]*\]")
_AXES = (("field", "fields", "field_conf", "field_src"), ("func", "functions", "func_conf", "func_src"))


@dataclass
class UnitLabel:
    """단위업무 라벨(H §11.1 · 계약 §3.15). why 는 로컬 전용 설명 조각."""
    unit_id: str
    group: str = ""
    project: str | None = None
    proposal_id: str | None = None
    domain: str = "UNC"
    field: str = "ETC"
    func: str = "ETC"
    wtype: str = "OFFICE"
    stance: str = "DO"
    ax_link: bool = False
    role_id: str = ""
    title: str = ""
    title_src: str = "rule_generic"
    src: dict = _dc_field(default_factory=dict)
    conf: dict = _dc_field(default_factory=dict)
    level: str = "unclassified"
    cands: list = _dc_field(default_factory=list)
    why: list = _dc_field(default_factory=list)
    flags: list = _dc_field(default_factory=list)

    def to_obj(self) -> dict:
        """labels.json 값(unit_id 는 키라 뺀다)."""
        return {"group": self.group, "project": self.project, "proposal_id": self.proposal_id, "domain": self.domain,
                "field": self.field, "func": self.func, "wtype": self.wtype, "stance": self.stance,
                "ax_link": self.ax_link, "role_id": self.role_id, "title": self.title, "title_src": self.title_src,
                "src": dict(sorted(self.src.items())), "conf": dict(sorted(self.conf.items())), "level": self.level,
                "cands": [[p, s] for p, s in self.cands], "why": list(self.why), "flags": sorted(set(self.flags))}


def merge_project(rule, ai: Mapping | None, reg=None) -> tuple[str | None, str, str | None]:
    """과제 축 합치기(H §6.5) → (과제 | 'NEW' | None, 출처, 'H02' | None). rule = RuleLabel 또는 사전."""
    rp = get(rule, "project", None)
    rsrc = get(rule, "source", "none") or "none"
    r_rank = RANK.get(rsrc, 0)
    if ai is None:
        return (rp, rsrc, None) if rp else (None, "none", None)
    conf = ai.get("conf")
    asrc = "ai_" + str(conf)
    a_rank = RANK.get(asrc, 0)
    ap = ai.get("project")
    if ap == "NONE":                                               # 규칙에 예약·유력 과제가 있으면 그대로
        return (rp, rsrc, None) if rp else (None, "none", None)
    if reg is not None and ap not in (None, "NEW"):
        ap = reg.resolve(ap)
    if rp and rsrc == "domain_rule" and conf in ("h", "m") and reg is not None and ap not in (None, "NEW") \
            and ap not in _vocab.RESERVED and reg.domain_of(ap) == get(rule, "domain", "") \
            and ap in reg.active_ids():                            # 구체화 — 같은 영역의 등록 과제
        return ap, asrc, None
    if rp and r_rank >= a_rank:
        q = "H02" if (ap and ap != "NEW" and ap != rp and conf == "h") else None
        return rp, rsrc, q
    if ap == "NEW":
        return "NEW", asrc, None
    q = None
    cands = list(get(rule, "cands", ()) or ())
    top = cands[0] if cands else None
    if top and ap != top[0] and top[1] >= 0.4 and conf == "h":
        q = "H02"
    return ap, asrc, q


def level_of(src: str, conf: str, project: str | None, proposal: str | None, rule_top: str | None) -> str:
    """과제 축 출처 → 신뢰 등급(H §11.1 표)."""
    if src == "user":
        return "confirmed"
    if proposal:
        return "low"
    if project is None:
        return "unclassified"
    if src == "token" or (src == "rule" and conf == "h") or (src == "ai_h" and rule_top == project):
        return "high"
    if src in ("rule", "domain_rule", "ai_h", "ai_m"):
        return "medium"
    return "low"


def role_slot(project: str | None, proposal: str | None, reg) -> str:
    """role_id 의 과제 자리: P-ID(예약 포함) · 제안 ID · 개인 과제는 그 제안 ID · 없으면 'UNC'(H §12.3)."""
    if proposal:
        return proposal
    if not project:
        return "UNC"
    if project.startswith("L-"):
        pv = reg.projects.get(project) if reg is not None else None
        return (pv.proposal_id if pv is not None and pv.proposal_id else project)
    return project


def _ai_title(s) -> str:
    t = unicodedata.normalize("NFKC", str(s or ""))
    t = _TITLE_TOKENS.sub(" ", t)
    return " ".join(t.split()).strip(" .\"'")


def _rule_title_src(src: str) -> str:
    return src if src.startswith("rule_") else "rule_" + (src or "generic")


@dataclass
class _GroupAI:
    ans: Mapping | None = None
    assign: object = None
    invalid: str = ""


def apply_labels(rule: Mapping, ff: Mapping, wt: Mapping, ai: Mapping | None, corrections: Mapping | None,
                 title_cache, proposals, reg, cfg=None, *, groups: Iterable, units: Mapping,
                 titles: Mapping[str, tuple[str, str]], at: str = "", label_check=None,
                 pub_classes: Iterable[str] = ()) -> tuple[dict[str, UnitLabel], list[dict], dict]:
    """라벨 적용(H §6.5). rule = {unit_id: RuleLabel}, ff = {unit_id: FieldFunc}, wt = {unit_id: (유형, 확신, 근거)},
    ai = read_ai_out 결과 {군집 키: {ans, by, …}}, corrections = apply_corrections 결과 {unit_id: {필드: 값}},
    titles = {군집 키: (규칙 이름, doc|subject|app|generic)}. 반환 (라벨, H02 충돌 목록, 통계)."""
    cfg = default_cfg(cfg)
    title_max = int(cfg["hier.name.titleMax"])
    codes = codes_for(reg)
    known = {pid for pid, p in reg.projects.items() if p.origin != "reserved"}
    vcodes = {"fields": set(reg.vocab_codes("fields")), "functions": set(reg.vocab_codes("functions")),
              "activity_types": set(reg.vocab_codes("activity_types"))}
    corr = corrections or {}
    out: dict[str, UnitLabel] = {}
    conflicts: list[dict] = []
    stats: Counter = Counter()
    for g in sorted(groups, key=lambda x: x.key):
        ga = _GroupAI()
        hit = (ai or {}).get(g.key)
        if hit is not None and hit.get("by") in ("ai", "manual") and isinstance(hit.get("ans"), Mapping):
            ans = dict(hit["ans"])
            vcodes_p = dict(codes)
            vcodes_p["projects"] = list(codes["projects"]) + sorted(known - set(codes["projects"]))
            why = validate_answer(ans, vcodes_p)
            if why:
                ga.invalid = why
                stats["ai_invalid"] += 1
            else:
                ga.ans = ans
                stats["ai_items"] += 1
                if ans.get("project") == "NEW" and proposals is not None:
                    ev_keys = sorted({k for m in g.members for k in _evidence_keys(units.get(m))})
                    custs = sorted({c for m in g.members for c in _custs(units.get(m))})
                    ga.assign = proposals.on_new_name(ans.get("new"), ans.get("dom"), g.key, "task_label", reg, cfg=cfg,
                                                      effort_min=int(g.effort_min), conf=str(ans.get("conf") or ""),
                                                      at=at, evidence_keys=ev_keys, customers=custs,
                                                      label_check=label_check)
        rtitle, rsrc_t = titles.get(g.key, ("", "generic"))
        ce = title_cache.get(g.key) if title_cache is not None else None
        g_title, g_tsrc, g_tconf = _pick_title(g, rtitle, rsrc_t, ce, ga.ans, title_max)
        if ga.ans is not None and g_tsrc == "ai" and title_cache is not None and \
                not (ce and (ce.get("src") == "user" or (ce.get("src") == "ai" and ce.get("conf") in ("h", "m")))):
            title_cache.put(g.key, title=g_title, src="ai", conf=g_tconf, at=at, prompt_ver=PROMPT_VER, anchor=g.anchor)
        for uid in g.members:
            rl = rule.get(uid)
            if rl is None:
                continue
            lab = _one(uid, g, rl, ff.get(uid), wt.get(uid), ga, corr.get(uid) or {}, reg, cfg, units.get(uid),
                       proposals, g_title, g_tsrc, g_tconf, known, vcodes, title_max, conflicts, title_cache, at)
            out[uid] = lab
    return dict(sorted(out.items())), conflicts, dict(sorted(stats.items()))


def _evidence_keys(u) -> set[str]:
    if u is None:
        return set()
    return set((get(u, "fams", {}) or {}).keys()) | set(get(u, "convs", ()) or ()) | \
        ({get(u, "peer", "")} - {""})


def _custs(u) -> set[str]:
    out = set()
    if u is None:
        return out
    for f, _w, _r in get(u, "ev", ()) or ():
        out |= set(f.ent.get("고객사", ()))
        out |= {lb.split(":", 1)[1] for lb in f.dom_labels if lb.startswith("고객사:")}
    return out


def _pick_title(g, rtitle: str, rsrc: str, ce: Mapping | None, ans: Mapping | None,
                title_max: int) -> tuple[str, str, str]:
    """군집 이름(H §5.4 우선순위). 반환 (이름, title_src, 확신)."""
    if ce and ce.get("src") == "user" and ce.get("title"):
        return str(ce["title"]), "user", "h"
    if ce and ce.get("src") == "ai" and ce.get("conf") in ("h", "m") and ce.get("title"):
        return str(ce["title"]), "ai", str(ce["conf"])
    at = _ai_title(ans.get("title")) if ans else ""
    aconf = str(ans.get("conf") or "l") if ans else ""
    if at and len(at) >= 2 and aconf in ("h", "m"):
        return clip_title(at, max(title_max, 30)), "ai", aconf
    if rtitle and rsrc in ("doc", "subject"):
        return rtitle, _rule_title_src(rsrc), "m"
    if at and len(at) >= 2:
        return clip_title(at, max(title_max, 30)), "ai", "l"
    return rtitle, _rule_title_src(rsrc), "l"


def _one(uid, g, rl, ffr, wtr, ga: _GroupAI, user: Mapping, reg, cfg, u, proposals, g_title, g_tsrc, g_tconf,
         known, vcodes, title_max, conflicts, title_cache, at) -> UnitLabel:
    lab = UnitLabel(unit_id=uid, group=g.key, cands=[(p, s) for p, s in (get(rl, "cands", ()) or ())],
                    why=list(get(rl, "why", ()) or ()))
    ans = ga.ans
    proposal = None
    # ── 과제 ──
    if "project" in user and (user["project"] is None or isinstance(user["project"], str)):
        p = user["project"]
        project = reg.resolve(p) if p else None
        psrc, pconf = "user", "h"
        if isinstance(p, str) and p.startswith("pr_"):
            project, proposal = None, (proposals.resolve(p) if proposals is not None else p)
    elif get(rl, "source", "") == "user":
        project, psrc, pconf = get(rl, "project", None), "user", "h"
    else:
        p, psrc, q = merge_project(rl, ans, reg)
        pconf = get(rl, "conf", "l") if psrc == get(rl, "source", "") else str((ans or {}).get("conf") or "l")
        project = p
        if p == "NEW":
            asg = ga.assign
            project = getattr(asg, "project", None) if asg is not None else None
            proposal = getattr(asg, "proposal", None) if asg is not None else None
            if asg is not None and getattr(asg, "src", "") in ("rejected_name", "too_small"):
                lab.flags.append(asg.src)
            if project is None and proposal is None:
                project, psrc = (get(rl, "project", None), get(rl, "source", "none")) if get(rl, "project", None) \
                    else (None, "none")
        if q == "H02":
            lab.flags.append("ai_conflict")
            conflicts.append({"group": g.key, "unit_id": uid, "rule": get(rl, "project", None),
                              "ai": (ans or {}).get("project"), "conf": (ans or {}).get("conf"),
                              "rule_score": get(rl, "score", 0.0), "effort_min": int(get(u, "effort_min", 0) or 0)})
    if project and (project not in known and project not in _vocab.RESERVED):
        lab.flags.append("retired_project")
    elif project and project in reg.projects and reg.projects[project].status != "active" and \
            not reg.projects[project].merged_into:
        lab.flags.append("retired_project")
    if proposal:
        lab.flags.append("proposal")
    lab.project, lab.proposal_id = project, proposal
    if proposal:
        lab.domain = proposals.dom_of(proposal) if proposals is not None else "UNC"
    else:
        lab.domain = reg.domain_of(project) if project else "UNC"
    if project and project.startswith("L-") and not proposal:
        pv = reg.projects.get(project)
        lab.proposal_id = pv.proposal_id if pv is not None and pv.proposal_id else None
    lab.src["project"], lab.conf["project"] = psrc, ("h" if psrc == "user" else pconf)
    cands = list(get(rl, "cands", ()) or ())
    rule_top = cands[0][0] if cands else None
    lab.level = level_of(psrc, lab.conf["project"], project, proposal, rule_top)
    # ── 분야·기능·유형 ──
    for axis, kind, ck, sk in _AXES:
        rv = get(ffr, axis, "ETC") or "ETC"
        rc = get(ffr, ck, "l") or "l"
        rs = get(ffr, sk, "rule") or "rule"
        v, s, c = _axis(user.get(axis), rv, rc, rs, ans.get(axis) if ans else None,
                        str(ans.get("conf") or "") if ans else "", vcodes[kind])
        setattr(lab, axis, v)
        lab.src[axis], lab.conf[axis] = s, c
    wv, wc = (wtr[0], wtr[1]) if wtr else ("OFFICE", "l")
    v, s, c = _axis(user.get("wtype"), wv, wc, "rule", ans.get("wtype") if ans else None,
                    str(ans.get("conf") or "") if ans else "", vcodes["activity_types"])
    lab.wtype, lab.src["wtype"], lab.conf["wtype"] = v, s, c
    # ── 이름 ──
    if isinstance(user.get("title"), str) and _ai_title(user["title"]):
        lab.title, lab.title_src = clip_title(_ai_title(user["title"]), max(title_max, 25)), "user"
        lab.src["title"], lab.conf["title"] = "user", "h"
        if title_cache is not None:
            title_cache.put(g.key, title=lab.title, src="user", conf="h", at=at, anchor=g.anchor)
    else:
        lab.title, lab.title_src = g_title, g_tsrc
        lab.src["title"] = "user" if g_tsrc == "user" else ("ai_" + g_tconf if g_tsrc == "ai" else "rule")
        lab.conf["title"] = g_tconf if g_tsrc != "user" else "h"
    # ── 참여 방식·AX 연계·역할 ──
    lab.stance = decide_stance(u) if u is not None else "DO"
    lab.ax_link = ax_link(u, lab.domain, reg, project, cfg) if u is not None else False
    lab.role_id = role_id(role_slot(project, lab.proposal_id if not project or not str(project).startswith("P-")
                                    else None, reg), lab.field, lab.func)
    return lab


def _axis(user_v, rv: str, rc: str, rs: str, av, aconf: str, valid: set) -> tuple[str, str, str]:
    """분야·기능·유형 한 축(H §6.5): user > 규칙 h > (규칙 m 이면 AI h) > (규칙 l 이면 AI h·m) > 규칙."""
    if isinstance(user_v, str) and user_v in valid:
        return user_v, "user", "h"
    rsrc = "fallback" if rs == "fallback" else "rule"
    if isinstance(av, str) and av in valid and aconf in ("h", "m"):
        if rc == "l" or (rc == "m" and aconf == "h"):
            return av, "ai_" + aconf, aconf
    return rv, rsrc, rc
