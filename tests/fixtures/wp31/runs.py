# -*- coding: utf-8 -*-
r"""WP-31 합성 분석 실행 — 시간 코어 결과(계약 §3.14 `timecore/1.1`) · 분류 결과(§3.15 `hier/1`) · 사람 사전 · 증거 보기를
임시 트리에 쓴다(실제 메일·팀즈·PC 기록 없음, 자리표시자만).

    from tests.fixtures.wp31 import runs as R
    t = R.TmpRoot()                         # %TEMP% 아래 임시 ROOT + 시험용 Paths(R.TPaths — 분석 하위 경로 메서드 CR 흉내)
    run = R.rich_run()                      # WP-30 합성 세계(tests.fixtures.wp30.world) + 실제 모양 키(w·d + 16hex)
    run.write(t.paths)                      # data\derived\analysis\<run_id>\{time,hier}\ + current.json + person_dir.json
    inp = run.inputs(t.paths)               # load_inputs(…, registry=REGISTRY, evidence=run.evidence())

- 정수 분 표는 시간 코어와 같은 방식으로 만든다: (날짜, 꼬리표) 칸마다 봉투 분 = 5 × 슬롯 수, 칸 안 대상별 초를
  `lm27.time.intervals.lr_minutes`(최대잉여)로 나눠 Σ = 봉투 분. 단위업무 몫은 `alloc_daily`, 버킷 몫은 `mm_month.buckets_min`.
- `TPaths` 는 계약 L-08 CR 로 요청한 `Paths` 메서드(`analysis_time_file`·`analysis_hier_file`·`analysis_report_file`·
  `out_personal_file`)를 시험 안에서만 흉내 낸다. 화면 자원·달력은 저장소 원본을 읽기만 한다.
"""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from lm27.paths import Paths
from lm27.time.calendar import SLOT, TAGS, d_of
from lm27.util.fsx import atomic_write, canon_bytes
from tests.fixtures.wp30 import world as W

REPO = Path(__file__).resolve().parents[3]
RUN_ID = "20261005-101500-3fa2"
RUN_ID2 = "20261006-090000-0b1c"


def key(prefix: str, name: str, n: int = 16) -> str:
    """합성 키(실제 모양 — `w`·`d` + 16hex). 같은 이름 → 같은 키."""
    return prefix + hashlib.sha256(("lm27t|" + name).encode("utf-8")).hexdigest()[:n]


class TPaths(Paths):
    """시험용 Paths — 분석 하위 경로 메서드(CR)와 저장소 원본 자원(읽기만)."""

    def analysis_time_file(self, run_id, name):
        return self.analysis(run_id) / "time" / name

    def analysis_hier_file(self, run_id, name):
        return self.analysis(run_id) / "hier" / name

    def analysis_report_file(self, run_id, name):
        return self.analysis(run_id) / "report" / name

    def out_personal_file(self, from_, to, run_id, rel):
        return self.out_personal(from_, to, run_id).joinpath(*str(rel).split("/"))

    def outbox_file(self, state, name):
        return self.outbox(state) / name

    def web_file(self, rel):
        return REPO.joinpath("web", *str(rel).replace("\\", "/").split("/"))

    def calendar_json(self):
        return REPO / "config" / "calendar.json"


class TmpRoot:
    r"""%TEMP% 아래 임시 ROOT(`data\`·`out\` 만 생긴다). 시험 끝에 `cleanup()`."""

    def __init__(self, prefix="lm27t_wp31_"):
        self.root = tempfile.mkdtemp(prefix=prefix)
        os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
        self.paths = TPaths(self.root, lad=os.path.join(self.root, "lad"))

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


# ───────────────────────────── 정수 분 표(시간 코어와 같은 방식) ─────────────────────────────
def lr_tables(w: W.World) -> tuple[dict, dict]:
    """(team_tables.json, {(날짜, 버킷, 꼬리표): 분})."""
    from lm27.time.intervals import lr_minutes
    cells: dict[tuple[str, str], Counter] = defaultdict(Counter)
    env: dict[tuple[str, str], int] = defaultdict(int)
    for s in sorted(w.slots):
        d = d_of(s * SLOT).isoformat()
        tag = w.tag(s)
        env[(d, tag)] += SLOT // 60
        for k, v in w.slots[s].items():
            if v["sec"] > 0:
                cells[(d, tag)][k] += v["sec"]
    alloc, buckets = {}, {}
    for (d, tag), em in sorted(env.items()):
        for k, v in lr_minutes(dict(cells[(d, tag)]), em).items():
            if v <= 0:
                continue
            if k.startswith("B_"):
                buckets[(d, k, tag)] = v
            else:
                alloc[(d, k, tag)] = v
    days = sorted({d for d, _t in env})
    order = {t: i for i, t in enumerate(TAGS)}
    tables = {"envelope_daily": {"cols": ["date", *TAGS], "rows": [[d] + [env.get((d, t), 0) for t in TAGS]
                                                                    for d in days]},
              "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"],
                              "rows": [[d, u, t, v] for (d, u, t), v in sorted(alloc.items(), key=lambda x: (
                                  x[0][0], x[0][1], order[x[0][2]]))]}}
    return tables, buckets


def mm_rows(w: W.World, tables: dict, buckets: dict, *, mm_buckets_ok: bool = True) -> list[dict]:
    """mm_month.json 행(W §6 — 분모 = 근무일, 가용 = 덮은 근무일 − 휴가)."""
    cal = w.cal
    d0, d1 = date.fromisoformat(w.d0), date.fromisoformat(w.d1)
    env_m: dict[str, Counter] = defaultdict(Counter)
    for row in tables["envelope_daily"]["rows"]:
        for t, v in zip(TAGS, row[1:], strict=True):
            env_m[row[0][:7]][t] += v
    att_m: Counter = Counter()
    for row in tables["alloc_daily"]["rows"]:
        att_m[row[0][:7]] += row[3]
    bk_m: dict[str, Counter] = defaultdict(Counter)
    for (d, b, _t), v in buckets.items():
        bk_m[d[:7]][b] += v
    out = []
    m = date(d0.year, d0.month, 1)
    while m <= d1:
        mk = f"{m.year:04d}-{m.month:02d}"
        wd = cal.month_workdays(m.year, m.month)
        cov = 0
        d = m
        while d.month == m.month:
            if d0 <= d <= d1 and not cal.is_holiday(d):
                cov += 1
            d += timedelta(days=1)
        absence = sum({"full": 1.0, "am": 0.5, "pm": 0.5}.get(v, 0.0) for k, v in w.leaves.items() if k[:7] == mk)
        em = sum(env_m[mk].values())
        bmin = {b: int(bk_m[mk].get(b, 0)) for b in ("B_GENERIC", "B_COMM", "B_MEET", "B_OFFPC", "B_UNKNOWN")}
        if not mm_buckets_ok and em:
            bmin["B_UNKNOWN"] += 7
        avail = cov - absence
        out.append({"month": mk, "workdays": wd, "covered_workdays": cov, "absence_days": absence, "avail_days": avail,
                    "env_min": em, "by_tag_min": {t: env_m[mk].get(t, 0) for t in TAGS}, "attributed_min": att_m[mk],
                    "unattributed_min": em - att_m[mk], "buckets_min": bmin,
                    "overtime_window_min": em - env_m[mk].get("regular", 0), "overtime_daily8h_min": 0,
                    "holiday_night_min": 0, "on_leave_min": 0, "machine_min": 0, "mm": em / (480 * wd),
                    "load_pct": em / (480 * avail) * 100.0 if avail > 0 else None, "units_mm": {}, "rollup": {},
                    "denominator": "workdays", "denom_days": wd, "std_day_min": 480, "overtime_basis": "window",
                    "overtime_min": em - env_m[mk].get("regular", 0)})
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


def interval_rows(w: W.World) -> list[dict]:
    """interval_ledger.jsonl — 슬롯마다 한 행(로컬 분 a·b, 대상 분 = 5분을 초 비례 최대잉여)."""
    from lm27.time.intervals import lr_minutes
    out = []
    for s in sorted(w.slots):
        sec = {k: v["sec"] for k, v in w.slots[s].items() if v["sec"] > 0}
        mins = lr_minutes(sec, SLOT // 60)
        lv = next((v["level"] for k, v in sorted(w.slots[s].items()) if k.startswith("u_")), "L7버킷")
        tg = []
        for k, v in sorted(mins.items(), key=lambda kv: (-kv[1], kv[0])):
            g = "X" if k.startswith("B_") else ("O" if lv in W.OBSERVED else "I")
            tg.append([k, v, g])
        out.append({"date": d_of(s * SLOT).isoformat(), "a": s * SLOT // 60, "b": (s + 1) * SLOT // 60,
                    "tag": w.tag(s), "basis": w.basis.get(s, "C1"), "targets": tg, "note": lv})
    return out


# ───────────────────────────── 합성 실행 ─────────────────────────────
class SynthRun:
    """합성 세계 하나 = 분석 실행 하나의 결과 파일."""

    def __init__(self, w: W.World, *, run_id: str = RUN_ID, person_dir=None, registry=None, evidence=None,
                 fam_names=None, proposals=(), hier_queue=(), time_queue=None, ai=None):
        self.w = w
        self.run_id = run_id
        self.person_dir = person_dir
        self.registry = registry
        self.ev = evidence or {}
        self.fam_names = fam_names or {}
        self.proposals = list(proposals)
        self.hier_queue = list(hier_queue)
        self.time_queue = time_queue
        self.ai = ai or {}
        self.tables, self.buckets = lr_tables(w)
        self.mm = mm_rows(w, self.tables, self.buckets)

    # ── 시간 코어 결과 ──
    def day_ledger(self) -> list[dict]:
        env: dict[str, dict] = {}
        for row in self.tables["envelope_daily"]["rows"]:
            env[row[0]] = dict(zip(TAGS, row[1:], strict=True))
        out = []
        for r in self.w.day_ledger():
            bt = env.get(r["date"], dict.fromkeys(TAGS, 0))
            tot = sum(bt.values())
            r = dict(r, total_min=tot, by_tag_min=bt, components=[["C1", tot]] if tot else [],
                     conf_min={"high": tot, "mid": 0, "low": 0})
            if r["date"] == "2026-09-02":
                r["deductions"] = [["사적차감", 15, 1]]
                r["flags"] = ["Q08"]
            out.append(r)
        return out

    def time_queue_rows(self) -> list[dict]:
        if self.time_queue is not None:
            return list(self.time_queue)
        out = [{"qid": "aa11bb22cc33", "code": "Q09", "target": "2026-09-23", "impact_min": 480, "evidence_keys": [],
                "proposal": {"title": "근거 없는 근무일", "options": ["부재", "근무"], "date": "2026-09-23"},
                "status": "open"}]
        if self.w.tasks:
            out.insert(0, {"qid": "9f2c01ab3e4d", "code": "Q01", "target": sorted(self.w.tasks)[0], "impact_min": 540,
                           "evidence_keys": [key("m", "msg00", 24)],
                           "proposal": {"title": "의뢰·보고 시각 확인", "options": ["지시받은 때", "보고한 때"],
                                        "answer_kinds": ["instr", "report"], "date": "2026-09-03", "note": "근거 1건"},
                           "status": "open"})
        return out

    def time_files(self) -> dict[str, bytes]:
        def jl(rows):
            return b"".join(canon_bytes(r) + b"\n" for r in rows)
        f = self.w.files()
        meta = dict(f["run_meta"], cfg_used={"time.window.std": "09:00-18:00", "mm.denominator": "workdays"})
        return {"env_slots.jsonl": jl(f["env_slots"]), "day_ledger.jsonl": jl(self.day_ledger()),
                "interval_ledger.jsonl": jl(interval_rows(self.w)), "tasks.json": canon_bytes(f["tasks"]),
                "attrib.jsonl": jl(f["attrib"]), "team_tables.json": canon_bytes(self.tables),
                "mm_month.json": canon_bytes(self.mm), "confirm_queue.json": canon_bytes(self.time_queue_rows()),
                "run_meta.json": canon_bytes(meta)}

    def hier_files(self) -> dict[str, bytes]:
        lab = self.w.files()["labels"]
        n = len(lab)
        unc = sum(1 for v in lab.values() if v.get("project") is None and not v.get("proposal_id"))
        return {"labels.json": canon_bytes(lab), "groups.json": canon_bytes({}),
                "queue.json": canon_bytes(self.hier_queue), "hier_meta.json": canon_bytes(
                    {"ai_share": 0.5, "unclassified_share": (unc / n) if n else 0.0, "counts": {"units": n}}),
                "proposals_snapshot.json": canon_bytes({"schema": "lm27.proposals/1", "next_seq": 2,
                                                        "items": self.proposals})}

    def write(self, paths, *, skip=(), current: bool = True) -> None:
        for name, data in self.time_files().items():
            if name not in skip:
                atomic_write(paths.analysis_time_file(self.run_id, name), data)
        for name, data in self.hier_files().items():
            if name not in skip:
                atomic_write(paths.analysis_hier_file(self.run_id, name), data)
        if current:
            atomic_write(paths.analysis_current(), canon_bytes(
                {"run_id": self.run_id, "from": self.w.d0, "to": self.w.d1, "as_of": self.w.as_of,
                 "built_at": "2026-10-05T10:15:00+09:00", "report_version": "report/1", "chosen": "auto",
                 "chosen_at": "2026-10-05T10:15:00+09:00", "period_source": "explicit"}))
        if self.person_dir is not None and "person_dir.json" not in skip:
            atomic_write(paths.local_only_file("person_dir.json"), canon_bytes(self.person_dir))
        for st, obj in self.ai.items():
            atomic_write(paths.ai_out(st), canon_bytes(obj))

    # ── 증거 보기(번들 대신) ──
    def evidence(self):
        from lm27.report.inputs import EvidenceIndex
        e = copy.deepcopy(self.ev)
        return EvidenceIndex(msgs=e.get("msgs", []), meets=e.get("meets", []), docs=e.get("docs", []),
                             fam_names=dict(self.fam_names), lines=e.get("lines", {}), leaves=dict(self.w.leaves))

    def inputs(self, paths, cfg=None, **kw):
        from lm27.report.inputs import load_inputs
        args = {"paths": paths, "cfg": cfg if cfg is not None else W.cfg(), "registry": self.registry,
                "cal": self.w.cal, "evidence": self.evidence()}
        args.update(kw)
        return load_inputs(self.run_id, **args)


# ───────────────────────────── 합성 세계(실제 모양 키) ─────────────────────────────
KIM = key("w", "kim")
PEER2 = key("w", "peer2")
PEER3 = key("w", "peer3")
CUST = key("w", "cust")
ME = key("w", "me")
WHO = {"w1": KIM, "w2": PEER2, "w3": PEER3, "w9": CUST, "wme": ME}
PERSON_DIR = {"format": "lm27-persondir/1", "people": {
    KIM: {"names": ["김철수"], "smtp": ["user01@corp.example"], "internal": True, "self": False},
    PEER2: {"names": ["동료 둘"], "smtp": ["user02@corp.example"], "internal": True, "self": False},
    PEER3: {"names": ["동료 셋"], "smtp": ["user03@corp.example"], "internal": True, "self": False},
    CUST: {"names": ["고객 담당"], "smtp": ["buyer@customer-a.example"], "internal": False, "self": False},
    ME: {"names": ["홍길동"], "smtp": ["me@corp.example"], "internal": True, "self": True}}}
REGISTRY = {"catalog_version": "ag-1",
            "agents": [{"id": "AG01", "name": "표 정리 도우미", "step_types": ["DOC_XLS"], "inputs": ["회의록"],
                        "outputs": ["음성"], "keywords": []},
                       {"id": "AG03", "name": "전원 검토 도우미", "step_types": [], "inputs": [], "outputs": [],
                        "keywords": ["전원부"]}],
            "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["customer-a.example"]}], "partners": [],
            "projects": [{"id": "P-0007", "name": "과제A", "domain": "DEV", "mask_name": False}]}


def fam_of(name: str) -> str:
    return key("d", "fam:" + name)


def remap(w: W.World) -> dict[str, str]:
    """WP-30 세계의 짧은 키(f1·w1 …)를 실제 모양 키로 바꾼다. 반환 = 문서군 대응표."""
    fams: dict[str, str] = {}

    def fk(f):
        if not f:
            return f
        if f not in fams:
            fams[f] = fam_of(f)
        return fams[f]
    for s in w.slots.values():
        for v in s.values():
            v["fam"] = fk(v["fam"])
    for t in w.tasks.values():
        t["docs"] = {fk(f): v for f, v in t["docs"].items()}
        t["peers"] = [{"who_key": WHO.get(p["who_key"], p["who_key"]), "rel": p["rel"]} for p in t["peers"]]
    return fams


def rich_run(*, run_id: str = RUN_ID, title_over: dict | None = None) -> SynthRun:
    """골든 역할(R §4.2.3) + 앞선 완료 업무 · 다른 역할 인계 · 동료·회의 · 버킷 · 커버리지 결손 — WP-30 `rich_world` 를 실제
    모양 키로. 증거 보기: 대화 2개(c1·c2) · 회의 mt1 · 경계 근거 메시지(m_<uid>_s/e) · 문서 사건."""
    w = W.rich_world()
    fams = remap(w)
    for uid, t in (title_over or {}).items():
        w.labels[uid]["title"] = t
    names = {fams[f]: n for f, n in W.FAM_NAMES.items() if f in fams}
    names[fams["f2"]] = "전원부_검증결과.xlsx"
    names[fams["f3"]] = "회로 사양.docx"
    msgs, lines, docs = [], {}, []
    for i, (conv, peer, dr) in enumerate((("c1", PEER2, "in"), ("c1", PEER2, "out"), ("c2", KIM, "in"), ("c2", KIM, "out"))):
        mid = f"msg{i:02d}"
        msgs.append({"id": mid, "conv": conv, "peer": peer, "flags": [], "dir": dr, "t": W.lsec("2026-09-02", "10:00") + i * 60})
        lines[mid] = {"kind": "mail", "t": f"2026-09-02 10:0{i}", "dir": dr, "prec": "minute", "who": peer,
                      "title": "[과제:P-0007] 전원부 검증 요청", "key": key("m", mid, 24)}
    for uid, t in w.tasks.items():
        for c in t["cycles"]:
            for ref, side in ((c.get("s_ref"), "s"), (c.get("e_ref"), "e")):
                if ref and ref not in lines:
                    lines[ref] = {"kind": "mail", "t": "2026-09-01 09:30", "dir": "in" if side == "s" else "out",
                                  "prec": "exact", "who": KIM, "title": f"{uid} 경계 메일", "key": key("m", ref, 24)}
    lines["mt1"] = {"kind": "meeting", "t": "2026-09-04 10:00", "dir": "", "prec": "", "who": "", "title": "전원부 검토 회의",
                    "key": key("e", "mt1", 24), "n_att": 8}
    for i, f in enumerate(sorted(fams.values())):
        did = f"doc{i:02d}"
        docs.append({"id": did, "fam": f, "t": W.lsec("2026-09-03", "15:00"), "kind": "save", "raw": names.get(f, "자료.bin")})
        lines[did] = {"kind": "file", "t": "2026-09-03 15:00", "dir": "", "prec": "", "who": "",
                      "title": names.get(f, "자료.bin"), "op": "save", "fam": f}
    ev = {"msgs": msgs, "meets": [{"id": "mt1", "attendees": [PEER3, KIM], "n_att": 8}], "docs": docs, "lines": lines}
    props = [{"proposal_id": "pr_1", "kind": "project", "label": "과제A 후속", "domain_guess": "DEV", "status": "pending",
              "evidence_keys": [key("m", "pr1", 24)]}]
    hq = [{"qid": "dd44ee55ff66", "code": "H05", "target": "grp:0123456789ab", "impact_min": 120,
           "evidence_keys": [key("m", "h5", 24)], "proposal": {"title": "업무 유형", "ask": "업무 유형을 골라 주세요",
                                                              "options": ["개발", "사무"], "area": "분류", "date": "2026-09-10"},
           "status": "open"}]
    return SynthRun(w, run_id=run_id, person_dir=copy.deepcopy(PERSON_DIR), registry=copy.deepcopy(REGISTRY),
                    evidence=ev, fam_names=names, proposals=props, hier_queue=hq)


def golden_run() -> SynthRun:
    """R §4.2.3 골든 역할(단위업무 4개)만 — 마이닝 골든이 모델에 그대로 실리는지."""
    w = W.golden_role_a()
    remap(w)
    return SynthRun(w, person_dir=None, registry=None)


SAMPLE_DIR = Path(__file__).resolve().parent
SAMPLE_FILES = ("sample_model.json", "sample_model_redacted.json", "sample_drill.json")


def sample_objects() -> dict[str, dict]:
    """이음매 견본(계획 §4 — `report_model.json` 소비 WP-34·35·36 의 고정 모델 파일): 합성 실행 하나의 전체판·가림판 모델과
    전체판 드릴다운 섬. 폴백은 '답 없음'(브리지 단계 판과 무관하게 결정적)."""
    from lm27.report import model as M
    from lm27.report.drill import drill_island
    from lm27.report.resolve import Resolver
    t = TmpRoot()
    try:
        run = rich_run()
        run.write(t.paths)
        cfg = W.cfg()
        inp = run.inputs(t.paths, cfg)
        m = M.build_model(inp, cfg, fallback=lambda *_a: None)
        red = M.redact_model(m, inp.registry, person_dir=inp.person_dir)
        refs = m["refs"]
        res = Resolver("full", inp.person_dir, inp.registry, inp.evidence,
                       people_ref={v["key"]: int(k) for k, v in refs["people"].items()},
                       doc_ref={v["key"]: int(k) for k, v in refs["docs"].items()})
        return {"sample_model.json": m, "sample_model_redacted.json": red,
                "sample_drill.json": drill_island(inp, m, "full", cfg, res=res)}
    finally:
        t.cleanup()


def shape(obj, path: str = "") -> set[str]:
    """구조 지문 — 키 경로 집합. 목록은 '[]', 키가 snake_case 이름이 아닌 사전(ID·날짜·코드 → 값)은 '{}' 로 접는다."""
    import re
    out = {path}
    if isinstance(obj, dict):
        if obj and all(isinstance(k, str) and re.match(r"^[a-z][a-z0-9_]*$", k) for k in obj):
            for k, v in obj.items():
                out |= shape(v, f"{path}.{k}")
        else:
            for v in obj.values():
                out |= shape(v, path + "{}")
    elif isinstance(obj, list):
        for v in obj:
            out |= shape(v, path + "[]")
    return out


def write_samples(dest=None) -> list[str]:
    """견본 파일을 다시 쓴다(개발자가 모델 모양을 바꿨을 때만 손으로 — 시험은 쓰지 않고 비교만 한다)."""
    d = Path(dest) if dest else SAMPLE_DIR
    out = []
    for name, obj in sample_objects().items():
        atomic_write(d / name, canon_bytes(obj) + b"\n")
        out.append(str(d / name))
    return out


def big_run(n_units: int = 300) -> SynthRun:
    """성능(RPT-46): 3개월(7~9월) 근무일에 단위업무 n_units 개 — 하루 7칸(1시간)마다 업무 하나(구간 2개 · 칸이 겹치지 않아 보존
    법칙이 성립) + 날마다 미귀속 1시간. 역할 6개 · 동료 40명 · 문서 30개."""
    d0, d1 = date(2026, 7, 1), date(2026, 9, 30)
    w = W.World(d0.isoformat(), d1.isoformat(), d1.isoformat() + "T18:00")
    days = []
    d = d0
    while d <= d1:
        if not w.cal.is_holiday(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    fields = (("ELEC", "ANALYSIS"), ("ELEC", "DESIGN"), ("MECH", "DESIGN"), ("SW", "DEV"), ("ETC", "DOC"), ("ETC", "MEET"))
    types = ("APP_CAE", "DOC_XLS", "DOC_DOC", "APP_EDA", "MEET", "COMM", "APP_IDE")
    hours = (9, 10, 11, 13, 14, 15, 16)
    for i in range(n_units):
        fd, fn = fields[i % len(fields)]
        di = (i // len(hours)) % len(days)
        hh = hours[i % len(hours)]
        a, b = days[di], days[min(len(days) - 1, di + 2)]
        uid = f"u_{i:010x}"
        w.unit(uid, project="P-0007" if i % 3 else "P-0012", field=fd, func=fn, start=(a, "09:00"), end=(b, "17:00"),
               title=f"합성 업무 {i}", peers=[(key("w", f"p{i % 40}"), "requester")], docs=[key("d", f"f{i % 30}")])
        w.run(uid, types[i % len(types)], a, f"{hh:02d}:00", f"{hh:02d}:30", app="excel", fam=key("d", f"f{i % 30}"))
        w.run(uid, types[(i + 1) % len(types)], a, f"{hh:02d}:30", f"{hh + 1:02d}:00", app="cae_x")
    for ds in days:
        w.bucket("B_GENERIC", ds, "17:00", "18:00")
    return SynthRun(w, person_dir=None, registry=None)
