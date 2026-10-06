# -*- coding: utf-8 -*-
r"""팀 묶음 라벨 조각 — `projects[]` · `proposals[]` · `roles[]` · `units[]` 라벨 필드 · `person.field`(H §12.4 · §7.6,
계약 §3.18 · X-230 · X-239 · X-240 · TAB §2.3 · §2.5).

- 어휘 값은 **코드**다(X-230): `roles[].field`·`function` = 분야·기능 코드, `units[].activity_type` = 업무 유형 코드 7종.
  개인 `L_` 어휘 코드는 `maps_to`(없으면 ETC)로 바꾸고 role_id 도 바꾼 코드로 다시 계산한다(H-I4 — R-8 식).
- 과제 자리: 팀 과제·예약 과제(`P-…`)는 `project_id`, 제안 과제와 개인 과제(`L-…` — 팀에 의미 없음)는 그 `proposal_id`.
  미리보기에서 제안을 [빼기] 하면 그 역할은 `project_id=null, proposal_id=null`(= UNC)로 실린다(시간은 그대로).
- `projects[].domain`·`proposals[].domain_guess` 는 5종(`UNC` 는 파생 전용 — 계약 §3.18).
- 제목: 군집 이름 → `text_check(s, 40, 'units[].title')`(TAB §2.4 `team_text` — 호출자가 문맥을 묶어 넘긴다), 실패·`generic`
  모드·[제목 가림]·[세부 가림]이면 `<분야 이름>·<기능 이름> 단위업무 #n`(n = 그 역할 안 시작 시각 순번)과 `title_mode="generic"`.
- `stance`·`level`·`src`·`why`·`cands` 는 싣지 않는다(v1).

이 조각은 빌더(`lm27.team.build`)가 허용 목록으로 하나씩 옮긴다 — 분석 객체를 통째로 넘기지 않는다(L-22). 표준 라이브러리만.
"""
from collections import defaultdict
from collections.abc import Callable, Mapping

from lm27.hier import vocab as _vocab
from lm27.hier.features import default_cfg, get
from lm27.hier.proposals import fallback_label, proposal_num
from lm27.hier.unitlabel import role_id

__all__ = ["TITLE_MODES", "generic_title", "team_parts"]

TITLE_MODES = ("label", "generic")
TITLE_MAX = 40


def _vname(reg, kind: str, code: str) -> str:
    it = reg.vocab.get(kind, {}).get(code)
    return it.name if it is not None else code


def generic_title(reg, field_code: str, func_code: str, n: int) -> str:
    """generic 라벨 '<분야 이름>·<기능 이름> 단위업무 #n'(TAB §2.5)."""
    return f"{_vname(reg, 'fields', field_code)}·{_vname(reg, 'functions', func_code)} 단위업무 #{n}"


def team_parts(labels: Mapping, reg, proposals=None, overrides: Mapping | None = None, *, cfg=None,
               starts: Mapping[str, int] | None = None, text_check: Callable[[str, int, str], str | None] | None = None,
               title_mode: str | None = None) -> dict:
    """라벨 → 팀 묶음 조각 {projects, proposals, roles, units{unit_id: {role_id, title, title_mode, activity_type,
    ax_link}}, person{field}}. labels = {unit_id: UnitLabel 또는 사전}. 결정적(ID 순)."""
    cfg = default_cfg(cfg)
    mode = title_mode if title_mode in TITLE_MODES else str(cfg["team.unitTitleMode"])
    ov = overrides or {}
    unit_ov = dict(ov.get("units") or {})
    prop_drop = {k for k, v in dict(ov.get("proposals") or {}).items() if v == "drop"}
    st = starts or {}
    projects: dict[str, str] = {}
    roles: dict[str, dict] = {}
    unit_rows: dict[str, dict] = {}
    by_role: dict[str, list[str]] = defaultdict(list)
    used_props: set[str] = set()
    for uid in sorted(labels):
        lb = labels[uid]
        project = get(lb, "project", None)
        proposal = get(lb, "proposal_id", None)
        fcode = reg.team_code("fields", get(lb, "field", "ETC") or "ETC")
        ccode = reg.team_code("functions", get(lb, "func", "ETC") or "ETC")
        wcode = reg.team_code("activity_types", get(lb, "wtype", "OFFICE") or "OFFICE")
        pid = None
        prid = None
        if project and str(project).startswith("P-"):
            pid = str(project)
            dom = reg.domain_of(pid)
            if dom in _vocab.DOMAINS:
                projects[pid] = dom
        elif proposal:
            prid = str(proposal)
        if prid in prop_drop:
            prid = None
        if prid:
            used_props.add(prid)
        rid = role_id(pid or prid or "UNC", fcode, ccode)
        roles.setdefault(rid, {"role_id": rid, "project_id": pid, "proposal_id": prid, "field": fcode,
                               "function": ccode})
        by_role[rid].append(uid)
        unit_rows[uid] = {"role_id": rid, "title": get(lb, "title", "") or "", "title_mode": "label",
                          "activity_type": wcode, "ax_link": bool(get(lb, "ax_link", False)),
                          "_f": fcode, "_c": ccode}
    for uids in by_role.values():
        order = sorted(uids, key=lambda u: (int(st.get(u, 0) or 0), u))
        for n, uid in enumerate(order, start=1):
            row = unit_rows[uid]
            title = row["title"]
            ok = None
            if mode == "label" and unit_ov.get(uid) not in ("title", "detail") and title:
                ok = text_check(title, TITLE_MAX, "units[].title") if text_check is not None else title[:TITLE_MAX]
            if ok:
                row["title"], row["title_mode"] = ok, "label"
            else:
                row["title"], row["title_mode"] = generic_title(reg, row["_f"], row["_c"], n), "generic"
    units = {}
    for uid in sorted(unit_rows):
        r = dict(unit_rows[uid])
        r.pop("_f")
        r.pop("_c")
        units[uid] = r
    props = []
    if proposals is not None:
        for p in proposals.team_payload({u: labels[u] for u in labels}):
            if p["proposal_id"] not in used_props:
                continue
            lab = p["label"]
            ok = text_check(lab, TITLE_MAX, "proposals[].label") if text_check is not None else lab[:TITLE_MAX]
            if not ok:
                ok = fallback_label(p["domain_guess"], proposal_num(p["proposal_id"]))
            props.append({"proposal_id": p["proposal_id"], "kind": "project", "label": ok,
                          "domain_guess": p["domain_guess"]})
    person = reg.person or {}
    pf = str(person.get("default_field") or "")
    return {"projects": [{"project_id": k, "domain": projects[k]} for k in sorted(projects)],
            "proposals": props,
            "roles": [roles[k] for k in sorted(roles)],
            "units": units,
            "person": {"field": reg.team_code("fields", pf) if pf else ""}}
