# -*- coding: utf-8 -*-
r"""WP-30 합성 세계 작성기 — 시간 코어 결과 파일(계약 §3.14 `timecore/1.1`)과 분류 라벨(§3.15 `hier/1`) 모양의 시험 입력.

실제 메일·팀즈·PC 기록은 쓰지 않는다. 사람은 키(`w…`)로만, 이름은 자리표시자(홍길동·김철수)·과제A~C·고객사A 만 쓴다.

    w = World("2026-09-01", "2026-10-04", "2026-10-04T18:00")
    w.unit("u_a1", project="P-0007", field="ELEC", func="ANALYSIS", start=("2026-09-01", "09:30"),
           end=("2026-09-04", "16:00"))
    w.run("u_a1", "APP_CAE", "2026-09-01", "10:00", "12:00", app="cae_x", fam="f1")
    ctx = w.context(cfg)          # lm27.report.analysis.activity.make_context

- `run` 은 5분 슬롯마다 attrib 행(초 = 300 × 몫)을 만든다. 꼬리표는 달력(`config\calendar.json`)과 기본 근무창(09:00~18:00,
  점심 12:00~13:00, 야간 22:00~06:00)으로 정한다. 정수 분 표(team_tables)는 attrib 초를 (날짜, 꼬리표, 대상) 칸마다 분으로
  더한 값(합성 자료는 슬롯이 꽉 차므로 정확히 나뉜다), 봉투는 그 칸의 모든 대상(버킷 포함) 합이다.
- `bucket(...)` 은 미귀속(버킷) 슬롯, `cover(...)` 는 일자 × 축 커버리지 상태, `leave(...)` 는 휴가.
- 같은 입력이면 같은 행(정렬 고정) — 결정성 시험은 행 순서를 섞어 넣는다.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta

from lm27.time.calendar import SLOT, Calendar, day0, d_of

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REG_ZONES = ((9 * 60, 12 * 60), (13 * 60, 18 * 60))
NIGHT = (22 * 60, 6 * 60)
OBSERVED = ("L1", "L2회의", "L3PC")


def calendar() -> Calendar:
    return Calendar(os.path.join(ROOT, "config", "calendar.json"))


def cfg(**over):
    """시험 설정 — 저장소 레지스트리 기본값(개인 config.json 은 읽지 않는다) + 덮어쓰기."""
    import tempfile

    from lm27.config import load_config
    none = os.path.join(tempfile.gettempdir(), "lm27t_wp30_none_config.json")
    c = load_config(registry_path=os.path.join(ROOT, "config", "settings_registry.json"), config_path=none)
    return c.derive(over) if over else c


def lsec(ds: str, hm: str) -> int:
    h, m = (int(x) for x in hm.split(":"))
    return day0(date.fromisoformat(ds)) + h * 3600 + m * 60


def lmin(ds: str, hm: str) -> int:
    return lsec(ds, hm) // 60


def role_id(project, field, func) -> str:
    from lm27.hier.unitlabel import role_id as rid
    return rid(project, field, func)


class World:
    def __init__(self, d0: str, d1: str, as_of: str, *, cal: Calendar | None = None):
        self.d0, self.d1, self.as_of = d0, d1, as_of
        self.cal = cal or calendar()
        self.tasks: dict[str, dict] = {}
        self.labels: dict[str, dict] = {}
        self.slots: dict[int, dict[str, dict]] = defaultdict(dict)    # slot → target → {sec, level, obs, app, fam}
        self.basis: dict[int, str] = {}
        self.coverage: dict[str, dict[str, str]] = defaultdict(dict)
        self.leaves: dict[str, str] = {}

    # ── 단위업무 ──
    def unit(self, uid: str, *, project: str | None = "P-0007", proposal: str | None = None, field="ELEC",
             func="ANALYSIS", domain="DEV", wtype="DEV", title=None, start=None, end=None, sb="S1", eb="E1",
             status=None, grade="A", kind="S1", parallel=1.0, peers=(), docs=(), cycles=None, flags=(), conv="",
             level="high", title_src="ai", label=True, levels_s=None):
        """단위업무 하나. start·end = ('YYYY-MM-DD', 'HH:MM'). cycles = [(s, sb, e, eb)…] 를 주면 그것을 쓴다.
        peers = [(who_key, rel)…], docs = [fam…] 또는 {fam: {'n', 'ops'}}."""
        cyc = []
        if cycles:
            for c in cycles:
                s, csb, e, ceb = c[:4]
                cyc.append({"s": lsec(*s) if s else None, "sb": csb, "e": lsec(*e) if e else None, "eb": ceb,
                            "s_ref": c[4] if len(c) > 4 else f"m_{uid}_s", "e_ref": c[5] if len(c) > 5 else None,
                            "interim": [], "unstarted": False})
        else:
            cyc.append({"s": lsec(*start) if start else None, "sb": sb, "e": lsec(*end) if end else None,
                        "eb": eb if end else None, "s_ref": f"m_{uid}_s", "e_ref": f"m_{uid}_e" if end else None,
                        "interim": [], "unstarted": status == "not_started"})
        st = status or ("closed" if cyc[-1]["e"] is not None else "open")
        dd = docs if isinstance(docs, dict) else {f: {"n": 1, "ops": {"save": 1, "export": 0, "attach": 0}}
                                                  for f in docs}
        self.tasks[uid] = {
            "unit_id": uid, "kind": kind, "label": f"{kind}:{conv or uid}#1", "conv": conv, "peer": "",
            "peers": [{"who_key": w, "rel": r} for w, r in sorted(peers)], "docs": dd, "cycles": cyc,
            "grade": grade, "status": st, "lead_s": None, "biz_lead_s": None, "effort_s": 0,
            "levels_s": levels_s or {"L1": 0, "L2": 0, "L3": 1, "L4": 0, "L5": 0, "L6": 0, "L7": 0},
            "parallel": parallel, "machine_s": 0, "pre_request_s": 0, "flags": list(flags), "proj": project,
            "first_key": f"m_{uid}_s", "follow_of": None}
        if label:
            slot = project if project else None
            self.labels[uid] = {"group": "", "project": project, "proposal_id": proposal, "domain": domain,
                                "field": field, "func": func, "wtype": wtype, "stance": "DO", "ax_link": False,
                                "role_id": role_id(slot or proposal, field, func), "title": title or f"업무 {uid}",
                                "title_src": title_src, "src": {}, "conf": {}, "level": level, "cands": [], "why": [],
                                "flags": []}
        return self

    # ── 귀속 슬롯 ──
    def run(self, uid: str, obs: str, ds: str, a: str, b: str, *, level="L3PC", app="", fam="", share=1.0,
            basis="C1", tail_sec=None):
        """[a, b) 를 5분 슬롯으로 덮는 귀속 행. tail_sec 를 주면 마지막 슬롯 초를 그 값으로(짧은 Run 흉내)."""
        s0, s1 = lsec(ds, a) // SLOT, (lsec(ds, b) + SLOT - 1) // SLOT
        for s in range(s0, s1):
            sec = int(SLOT * share)
            if tail_sec is not None and s == s1 - 1:
                sec = int(tail_sec)
            self.slots[s][uid] = {"sec": sec, "level": level, "obs": obs, "app": app, "fam": fam}
            rest = SLOT - sum(v["sec"] for v in self.slots[s].values())
            if rest > 0 and "B_UNKNOWN" not in self.slots[s]:
                self.slots[s]["B_UNKNOWN"] = {"sec": rest, "level": "L7버킷", "obs": "", "app": "", "fam": ""}
            elif "B_UNKNOWN" in self.slots[s]:
                v = self.slots[s]["B_UNKNOWN"]
                v["sec"] = max(0, SLOT - sum(x["sec"] for k, x in self.slots[s].items() if k != "B_UNKNOWN"))
                if v["sec"] == 0:
                    del self.slots[s]["B_UNKNOWN"]
            self.basis.setdefault(s, basis)
        return self

    def bucket(self, bk: str, ds: str, a: str, b: str, *, basis="C1"):
        s0, s1 = lsec(ds, a) // SLOT, (lsec(ds, b) + SLOT - 1) // SLOT
        for s in range(s0, s1):
            self.slots[s][bk] = {"sec": SLOT, "level": "L7버킷", "obs": "", "app": "", "fam": ""}
            self.basis.setdefault(s, basis)
        return self

    def cover(self, ds: str, **axes):
        self.coverage[ds].update(axes)
        return self

    def leave(self, ds: str, kind: str = "full"):
        self.leaves[ds] = kind
        return self

    # ── 꼬리표 ──
    def tag(self, slot: int) -> str:
        t = slot * SLOT
        d = d_of(t)
        m = (t - day0(d)) // 60
        if d.year in self.cal.years and self.cal.is_holiday(d):
            return "holiday"
        if m >= NIGHT[0] or m < NIGHT[1]:
            return "night"
        if any(a <= m < b for a, b in REG_ZONES):
            return "regular"
        return "extended"

    # ── 결과 파일 모양 ──
    def attrib_rows(self) -> list[dict]:
        out = []
        for s in sorted(self.slots):
            lv = next((v["level"] for k, v in sorted(self.slots[s].items()) if k.startswith("u_")), "L7버킷")
            for k in sorted(self.slots[s]):
                v = self.slots[s][k]
                if v["sec"] <= 0:
                    continue
                out.append({"slot": s, "target": k, "sec": v["sec"], "level": lv if not k.startswith("B_") else lv,
                            "obs": v["obs"], "app": v["app"], "fam": v["fam"]})
        return out

    def env_slots(self) -> list[dict]:
        conf = {"C1": "high", "C1b": "mid", "C2": "high", "C3": "high", "C8": "low", "C10": "low", "C11": "high"}
        return [{"date": d_of(s * SLOT).isoformat(), "slot": s, "tag": self.tag(s), "basis": self.basis.get(s, "C1"),
                 "conf": conf.get(self.basis.get(s, "C1"), "mid"), "on_leave": False, "pcs": ["pc_x"]}
                for s in sorted(self.slots)]

    def tables(self) -> dict:
        env: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        alloc: dict[tuple[str, str, str], int] = defaultdict(int)
        for s in sorted(self.slots):
            d = d_of(s * SLOT).isoformat()
            tag = self.tag(s)
            env[d][tag] += SLOT // 60
            for k, v in self.slots[s].items():
                if k.startswith("u_") and v["sec"] > 0:
                    alloc[(d, k, tag)] += v["sec"]
        tags = ("regular", "extended", "night", "holiday")
        rows = [[d] + [env[d][t] for t in tags] for d in sorted(env)]
        order = {t: i for i, t in enumerate(tags)}
        arows = [[d, u, t, v // 60] for (d, u, t), v in sorted(alloc.items(), key=lambda x: (x[0][0], x[0][1],
                                                                                              order[x[0][2]]))
                 if v // 60 > 0]
        return {"envelope_daily": {"cols": ["date", *tags], "rows": rows},
                "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"], "rows": arows}}

    def day_ledger(self) -> list[dict]:
        out = []
        d = date.fromisoformat(self.d0)
        end = date.fromisoformat(self.d1)
        while d <= end:
            ds = d.isoformat()
            out.append({"date": ds, "total_min": 0, "components": [], "deductions": [], "excluded": [],
                        "by_tag_min": {}, "conf_min": {"high": 0, "mid": 0, "low": 0},
                        "coverage": dict(sorted(self.coverage.get(ds, {}).items())), "flags": []})
            d += timedelta(days=1)
        return out

    def run_meta(self) -> dict:
        return {"core_version": "timecore/1.1", "calendar_version": self.cal.version, "cfg_used": {}, "cfg_hash": "",
                "as_of": self.as_of + ":00+09:00", "input_digest": "", "audit": {}, "warnings": []}

    def files(self) -> dict:
        return {"tasks": [self.tasks[k] for k in sorted(self.tasks)], "attrib": self.attrib_rows(),
                "tables": self.tables(), "env_slots": self.env_slots(), "day_ledger": self.day_ledger(),
                "run_meta": self.run_meta(), "labels": dict(sorted(self.labels.items()))}

    def context(self, c=None, **kw):
        from lm27.report.analysis.activity import make_context
        f = self.files()
        args = {"tasks": f["tasks"], "attrib": f["attrib"], "tables": f["tables"], "cal": self.cal,
                "cfg": c if c is not None else cfg(), "labels": f["labels"], "env_slots": f["env_slots"],
                "day_ledger": f["day_ledger"], "run_meta": f["run_meta"], "period": (self.d0, self.d1),
                "leaves": dict(self.leaves)}
        args.update(kw)
        return make_context(**args)


def as_of_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ───────────────────────────── R §4.2.3 골든 — 과제A · 회로 · 해석/분석(홍길동), 단위업무 4개 ─────────────────────────────
def golden_role_a(w: World | None = None) -> World:
    """시제품 `mine_role_A`(R §4.2.3) 흔적. COMM 5분·DOC_PPT 8분은 짧아서 버려진다(RPT-15)."""
    w = w or World("2026-09-01", "2026-10-04", "2026-10-04T18:00")
    pk, fd, fn = "P-0007", "ELEC", "ANALYSIS"
    w.unit("u_a1", project=pk, field=fd, func=fn, start=("2026-09-01", "09:30"), end=("2026-09-04", "16:00"),
           title="전원부 해석 1")
    w.run("u_a1", "APP_CAE", "2026-09-01", "10:00", "12:00", app="cae_x", fam="f1")
    w.run("u_a1", "APP_CAE", "2026-09-02", "09:00", "11:00", app="cae_x", fam="f1")
    w.run("u_a1", "COMM", "2026-09-02", "11:00", "11:05", app="mail_x")
    w.run("u_a1", "DOC_XLS", "2026-09-03", "14:00", "16:00", app="excel", fam="f2")
    w.run("u_a1", "MEET", "2026-09-04", "10:00", "11:00", level="L2회의")
    w.unit("u_a2", project=pk, field=fd, func=fn, start=("2026-09-07", "10:00"), end=("2026-09-16", "11:00"),
           title="전원부 해석 2")
    w.run("u_a2", "APP_CAE", "2026-09-07", "13:00", "17:00", app="cae_x", fam="f3")
    w.run("u_a2", "DOC_XLS", "2026-09-08", "09:00", "10:00", app="excel", fam="f2")
    w.run("u_a2", "APP_CAE", "2026-09-10", "13:00", "15:00", app="cae_x", fam="f3")
    w.run("u_a2", "DOC_XLS", "2026-09-15", "13:00", "15:00", app="excel", fam="f3x")
    w.unit("u_a3", project=pk, field=fd, func=fn, start=("2026-09-14", "09:10"), end=("2026-09-18", "17:30"),
           title="전원부 해석 3")
    w.run("u_a3", "APP_CAE", "2026-09-14", "10:00", "12:00", app="cae_x", fam="f4")
    w.run("u_a3", "APP_CAE", "2026-09-15", "09:00", "10:00", app="cae_x", fam="f4")
    w.run("u_a3", "DOC_XLS", "2026-09-16", "15:00", "16:30", app="excel", fam="f5")
    w.run("u_a3", "DOC_PPT", "2026-09-17", "09:00", "09:10", app="ppt_x", fam="f6", tail_sec=180)
    w.run("u_a3", "MEET", "2026-09-18", "14:00", "15:00", level="L2회의")
    w.unit("u_a4", project=pk, field=fd, func=fn, start=("2026-09-21", "11:00"), end=("2026-10-02", "10:00"),
           title="전원부 해석 4", parallel=2.4)
    w.run("u_a4", "APP_CAE", "2026-09-22", "09:00", "12:00", app="cae_x", fam="f7")
    w.run("u_a4", "DOC_XLS", "2026-09-30", "13:00", "14:30", app="excel", fam="f8")
    return w


# ───────────────────────────── 설정 섭동·결정성 시험용 넓은 세계 ─────────────────────────────
PERSON_DIR = {"format": "lm27-persondir/1", "people": {
    "w1": {"names": ["김철수"], "smtp": ["user01@corp.example"], "internal": True, "self": False},
    "w2": {"names": ["동료 둘"], "smtp": ["user02@corp.example"], "internal": True, "self": False},
    "w3": {"names": ["동료 셋"], "smtp": ["user03@corp.example"], "internal": True, "self": False},
    "w9": {"names": ["고객 담당"], "smtp": ["buyer@customer-a.example"], "internal": False, "self": False},
    "wme": {"names": ["홍길동"], "smtp": ["me@corp.example"], "internal": True, "self": True}}}
REGISTRY = {"catalog_version": "ag-1",
            "agents": [{"id": "AG01", "name": "표 정리 도우미", "step_types": ["DOC_XLS"], "inputs": ["회의록"],
                        "outputs": ["음성"], "keywords": []},
                       {"id": "AG03", "name": "전원 검토 도우미", "step_types": [], "inputs": [], "outputs": [],
                        "keywords": ["전원부"]}],
            "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["customer-a.example"]}], "partners": []}
EVIDENCE = {"msgs": [{"conv": "c1", "peer": "w2", "flags": [], "dir": d} for d in ("in", "out")]
            + [{"conv": "c2", "peer": "w1", "flags": [], "dir": "in"}],
            "meets": [{"id": "mt1", "attendees": ["w3", "w1"], "n_att": 8}]}
FAM_NAMES = {f"fz{i}": f"자료{i}.abc" for i in range(1, 5)}


def rich_world() -> World:
    """골든 역할 + 앞선 완료 업무(u_a0) · 다른 역할 인계(u_b1) · 동료·회의 · 낮은 신뢰 슬롯 · 버킷 · 커버리지 결손 ·
    확장자 미상 문서(fz*) — `report.*` 키마다 섭동하면 결과가 바뀌도록 짠 세계(G-R9 · T-14)."""
    w = World("2026-08-01", "2026-10-04", "2026-10-04T18:00")
    golden_role_a(w)
    pk, fd, fn = "P-0007", "ELEC", "ANALYSIS"
    w.unit("u_a0", project=pk, field=fd, func=fn, start=("2026-08-13", "10:00"), end=("2026-08-14", "11:00"),
           title="전원부 해석 0")
    w.run("u_a0", "APP_CAE", "2026-08-13", "10:00", "12:00", app="cae_x", fam="f0")
    w.run("u_a0", "DOC_XLS", "2026-08-14", "09:00", "10:00", app="excel", fam="f0x", basis="C8")
    w.unit("u_b1", project=pk, field=fd, func="DESIGN", start=("2026-09-17", "09:00"), end=("2026-09-22", "17:00"),
           docs=["f3"], title="전원부 설계 1")
    w.run("u_b1", "APP_EDA", "2026-09-17", "10:00", "12:00", app="eda_x", fam="f3")
    w.run("u_b1", "COMM", "2026-09-18", "13:00", "13:30", level="L4앵커", basis="C8")
    for i, (uid, day) in enumerate((("u_a1", "2026-09-03"), ("u_a2", "2026-09-09"), ("u_a3", "2026-09-17"),
                                    ("u_a4", "2026-09-29")), 1):
        w.run(uid, "DOC_DOC", day, "16:00", "16:30", app="word_x", fam=f"fz{i}")
    w.run("u_a4", "DOC_DOC", "2026-09-28", "09:00", "12:00", app="word_x", fam="fz9")     # 투입 300 → 480(SCOPE 경계)
    w.tasks["u_a1"].update(conv="c1", flags=["회의연결 mt1"],
                           peers=[{"who_key": "w1", "rel": "requester"}, {"who_key": "w2", "rel": "thread"},
                                  {"who_key": "w3", "rel": "meeting"}, {"who_key": "wme", "rel": "thread"}])
    w.tasks["u_a2"].update(conv="c2", peers=[{"who_key": "w1", "rel": "thread"}, {"who_key": "w9", "rel": "requester"}])
    w.bucket("B_GENERIC", "2026-09-08", "14:00", "15:00")
    w.bucket("B_MEET", "2026-09-10", "16:00", "16:30", basis="C2")
    d = date(2026, 9, 1)
    while d <= date(2026, 9, 30):
        if not w.cal.is_holiday(d):
            ok = d.day % 3 != 0
            w.cover(d.isoformat(), mail_in="ok", mail_out="ok" if ok else "blocked", cal="ok",
                    teams="ok" if d.day % 4 else "partial")
        d += timedelta(days=1)
    return w


def rich_context(c=None, **kw):
    w = rich_world()
    args = {"person_dir": PERSON_DIR, "registry": REGISTRY, "evidence": EVIDENCE, "fam_names": FAM_NAMES}
    args.update(kw)
    return w.context(c, **args)
