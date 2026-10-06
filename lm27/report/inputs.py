# -*- coding: utf-8 -*-
r"""보고서 입력 단일 로더(R §2.5 · 부록 A `load_inputs`, 계약 §3.14 · §3.15 · §3.17 · §3.23 · L-08 · G-R10).

`load_inputs(run_id) -> ReportInputs` — 한 분석 실행(`data\derived\analysis\<run_id>\`)의 결과 파일과 로컬 자료를 **열고 ·
다 읽고 · 닫아** 한 객체로 모은다. 파일 없음·형식 깨짐은 조용히 삼키지 않고 `missing[]`·`warnings[]` 로 남긴다.

| 논리 이름 | 원천(모두 `lm27.paths` 경유) | 없을 때 |
|---|---|---|
| `time.env_slots`·`tasks`·`team_tables`·`mm_month`·`run_meta` | 시간 코어 결과(`timecore/1.1`) | 보고서 거부(`refused` — rc 1) |
| `time.day_ledger`·`interval_ledger`·`attrib`·`queue` | 〃 | 만들되 경고(`missing` — rc 2) |
| `labels`(+ groups·queue·hier_meta·proposals_snapshot) | 분류 결과(`hier/1`) | 모두 미분류 + 경고(`missing`) |
| `ai.<stage>` 4종 | `data\derived\ai_out\<stage>.json` | 단계 폴백(R §4.10.3) — 정상 상태 |
| `registry` | 유효 레지스트리(`lm27.hier.registry.load_effective`, persist=False — 쓰지 않음) | 내장 레지스트리 + 경고 |
| `person_dir` | `data\local_only\person_dir.json` | 동료 표시명 = `동료 #k` |
| `evidence` | 번들 단일 로더(`lm27.normalize.load.load_evidence`) + 시간 코어 정규화(`lm27.time.evidence.normalize`) | 드릴다운 증거 줄 비움·동료 관계 미확인 |
| `overrides` | `data\team\overrides.json`(니즈 '팀에 올리지 않기') | 빈 값 |
| `bundle_state`·`outbox` | 커버리지 원장·todo·대기열 meta | 빈 값(모델에는 쓰지 않는다 — RP14) |

분석 폴더 안 하위 경로는 계약 L-08 대로 `lm27.paths` 메서드로만 만든다: `Paths.analysis_time_file(run_id, name)`(WP-20 과
같은 이름) · `Paths.analysis_hier_file(run_id, name)`(또는 WP-22 의 `analysis_hier(run_id)` 폴더) ·
`Paths.analysis_report_file(run_id, name)` · `Paths.out_personal_file(from_, to, run_id, rel)` — 아직 `paths.py` 에 없으면
`PathsMethodMissing`(RuntimeError, 한국어 한 줄 — CR). 모델은 분석 결과 파일만으로 결정적으로 다시 만든다(RP14): 번들 현황·
대기열은 화면용으로만 싣고 다이제스트·모델에 넣지 않는다.

표준 라이브러리만 쓴다. 이 모듈은 파일을 쓰지 않는다(증거 적재의 정제 감사도 끈다 — 분석 파이프라인의 적재가 감사 원본).
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from lm27.util import fsx

__all__ = [
    "AI_STAGES",
    "HIER_FILES",
    "MISSING",
    "PARTIAL_TIME",
    "REQUIRED_TIME",
    "TIME_FILES",
    "BundleState",
    "EvidenceIndex",
    "PathsMethodMissing",
    "ReportInputs",
    "TimeFiles",
    "analysis_time",
    "hier_file",
    "load_evidence_index",
    "load_inputs",
    "out_personal_file",
    "report_file",
    "sha16",
    "time_file",
]

TIME_FILES = {"env_slots": "env_slots.jsonl", "day_ledger": "day_ledger.jsonl",
              "interval_ledger": "interval_ledger.jsonl", "tasks": "tasks.json", "attrib": "attrib.jsonl",
              "team_tables": "team_tables.json", "mm_month": "mm_month.json", "queue": "confirm_queue.json",
              "run_meta": "run_meta.json"}
REQUIRED_TIME = ("env_slots", "tasks", "team_tables", "mm_month", "run_meta")     # 없으면 보고서 거부(R §2.5)
PARTIAL_TIME = ("day_ledger", "interval_ledger", "attrib", "queue")                # 없으면 만들되 경고(rc 2)
HIER_FILES = ("labels.json", "groups.json", "queue.json", "hier_meta.json", "proposals_snapshot.json")
TAGS_FILE = "evidence_tags.jsonl"                 # 분류 증거 꼬리표(레코드 id → 과제) — 회의 레코드 몫만 읽는다
AI_STAGES = ("workflow_label", "agentic_match", "subagent_review", "review_text")
MISSING = "missing"
_WANT = {"tasks": list, "team_tables": dict, "mm_month": list, "queue": list, "run_meta": dict}
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OFF_RX = re.compile(r"([+-]\d{2}:\d{2}|Z)$")
TITLE_MAX = 120


class PathsMethodMissing(RuntimeError):
    """분석 폴더 하위 경로 메서드가 아직 `lm27.paths` 에 없다(계약 L-08 — CR 대상)."""


def sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


# ───────────────────────────── 경로(계약 L-08 — paths.py 메서드로만) ─────────────────────────────
def _method(paths, name: str):
    fn = getattr(paths, name, None)
    if fn is None:
        raise PathsMethodMissing(f"Paths.{name} 이 아직 없습니다 — lm27.paths 에 그 메서드가 생겨야 이 일을 합니다(계약 L-08 CR)")
    return fn


def time_file(paths, run_id: str, name: str):
    r"""``data\derived\analysis\<run_id>\time\<name>`` — `Paths.analysis_time_file`(WP-20 과 같은 이름)."""
    return _method(paths, "analysis_time_file")(run_id, name)


def _sub_file(paths, run_id: str, name: str, file_meth: str, dir_meth: str):
    fn = getattr(paths, file_meth, None)
    if fn is not None:
        return fn(run_id, name)
    d = getattr(paths, dir_meth, None)
    if d is None:
        raise PathsMethodMissing(f"Paths.{file_meth}(run_id, name) 이 아직 없습니다 — lm27.paths 에 그 메서드가 생겨야 이 일을 "
                                 "합니다(계약 L-08 CR)")
    return os.path.join(os.fspath(d(run_id)), name)


def hier_file(paths, run_id: str, name: str):
    r"""``…\<run_id>\hier\<name>`` — `Paths.analysis_hier_file`, 없으면 WP-22 의 `Paths.analysis_hier(run_id)` 폴더."""
    return _sub_file(paths, run_id, name, "analysis_hier_file", "analysis_hier")


def report_file(paths, run_id: str, name: str):
    r"""``…\<run_id>\report\<name>`` — `Paths.analysis_report_file`(또는 `analysis_report(run_id)` 폴더)."""
    return _sub_file(paths, run_id, name, "analysis_report_file", "analysis_report")


def out_personal_file(paths, from_, to, run_id: str, rel: str):
    r"""``out\personal\<from>_<to>_<run8>\<rel>`` — `Paths.out_personal_file`(rel = 'report_full.html'·'csv_full/units.csv')."""
    return _method(paths, "out_personal_file")(from_, to, run_id, rel)


# ───────────────────────────── 형 ─────────────────────────────
@dataclass
class TimeFiles:
    """시간 코어 결과(계약 §3.14) — 읽은 값. 없거나 깨진 파일은 None."""
    env_slots: list | None = None
    day_ledger: list | None = None
    interval_ledger: list | None = None
    tasks: list | None = None
    attrib: list | None = None
    team_tables: dict | None = None
    mm_month: list | None = None
    queue: list | None = None
    run_meta: dict | None = None


@dataclass
class BundleState:
    """화면용 번들 현황(홈·수집 — 모델에는 쓰지 않는다)."""
    coverage: list | None = None
    todo: object = None


@dataclass
class EvidenceIndex:
    """정규화 증거의 보고서 보기 — 동료 관계 확인(msgs·meets) · 문서군 이름 · 드릴다운 증거 줄(정제 열만).

    `msgs`·`meets`·`docs` = 시간 코어 `Msg`·`Meet`·`DocE`(또는 같은 속성의 dict), `lines` = 레코드 id → 표시 열
    {kind, t(로컬 'YYYY-MM-DD HH:MM'), dir, prec, who(who_key), title(정제문)}. 원문은 애초에 없다(P)."""
    msgs: list = field(default_factory=list)
    meets: list = field(default_factory=list)
    docs: list = field(default_factory=list)
    fam_names: dict = field(default_factory=dict)
    lines: dict = field(default_factory=dict)
    leaves: dict = field(default_factory=dict)
    absences: list = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """관계 확인에 쓸 수 있는가 — 메시지·회의가 하나도 없으면 번들이 없거나 빈 것(미확인으로 둔다)."""
        return bool(self.msgs or self.meets)

    def digest(self) -> str:
        def g(o, k, d=None):
            v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
            return d if v is None else v
        summ = {"msgs": sorted([str(g(m, "id", "")), str(g(m, "conv", "")), str(g(m, "peer", "")),
                                sorted(str(x) for x in (g(m, "flags", ()) or ()))] for m in self.msgs),
                "meets": sorted([str(g(m, "id", "")), sorted(str(x) for x in (g(m, "attendees", ()) or ())),
                                 int(g(m, "n_att", 0) or 0)] for m in self.meets),
                "docs": sorted([str(g(d, "id", "")), str(g(d, "fam", "")), str(g(d, "raw", ""))] for d in self.docs),
                "fam_names": dict(sorted(self.fam_names.items())), "lines": dict(sorted(self.lines.items())),
                "leaves": dict(sorted(self.leaves.items())), "absences": sorted(self.absences)}
        return sha16(fsx.canon_bytes(summ))


@dataclass
class ReportInputs:
    """R 부록 A `ReportInputs` — 한 분석 실행의 보고서 입력(읽은 값)."""
    run_id: str
    time: TimeFiles = field(default_factory=TimeFiles)
    labels: dict | None = None
    hier: dict = field(default_factory=dict)            # groups · queue · meta · proposals
    ai: dict = field(default_factory=dict)              # 단계 → ai_out 객체(없으면 None)
    registry: object = None                             # 유효 레지스트리(EffectiveRegistry) 또는 dict
    registry_status: dict | None = None
    person_dir: dict | None = None
    evidence: EvidenceIndex | None = None
    bundle_state: BundleState = field(default_factory=BundleState)
    outbox: list = field(default_factory=list)
    overrides: dict | None = None
    calendar: object = None
    period: tuple | None = None                         # ('YYYY-MM-DD', 'YYYY-MM-DD')
    as_of: str | None = None                            # run_meta.as_of(근무 시간대 ISO + 오프셋)
    run: dict = field(default_factory=dict)             # {run_id, from, to, as_of, chosen, period_source}
    leaves: dict = field(default_factory=dict)
    absences: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    refused: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    digests: dict = field(default_factory=dict)

    @property
    def from_(self) -> str | None:
        return self.period[0] if self.period else None

    @property
    def to(self) -> str | None:
        return self.period[1] if self.period else None

    def warn(self, code: str, text_ko: str, **kw) -> None:
        if any(w.get("code") == code for w in self.warnings):
            return
        w = {"code": code, "text_ko": text_ko}
        w.update({k: v for k, v in kw.items() if v is not None})
        self.warnings.append(w)


# ───────────────────────────── 읽기 ─────────────────────────────
def _raw(path) -> tuple[bytes | None, str | None]:
    """(바이트, 오류 유형). 파일 없음 = (None, None) — 첫 실행의 정상 상태와 같게 다룬다."""
    try:
        return fsx.read_bytes(path), None
    except FileNotFoundError:
        return None, None
    except OSError as e:
        return None, type(e).__name__


def _parse(raw: bytes, jsonl: bool, want):
    if jsonl:
        rows = []
        for ln in raw.decode("utf-8-sig").splitlines():
            if ln.strip():
                rows.append(fsx.loads_strict(ln))
        if not all(isinstance(r, Mapping) for r in rows):
            raise ValueError("JSONL 행이 객체가 아닙니다")
        return rows
    obj = fsx.loads_strict(raw)
    if want is not None and not isinstance(obj, want):
        raise ValueError(f"형이 다릅니다(기대 {want.__name__})")
    return obj


def _load(inp: ReportInputs, logical: str, path, *, jsonl: bool = False, want=None):
    """한 파일 읽기 — 다이제스트를 남기고, 없음·깨짐은 None(+ 깨짐은 경고)."""
    raw, err = _raw(path)
    if raw is None:
        inp.digests[logical] = MISSING
        if err:
            inp.warn("input_unreadable:" + logical, f"입력 파일을 읽지 못했습니다({err}): {logical}")
        return None
    inp.digests[logical] = sha16(raw)
    try:
        return _parse(raw, jsonl, want)
    except ValueError as e:
        inp.digests[logical] = "broken:" + sha16(raw)
        inp.warn("input_broken:" + logical, f"입력 파일 형식이 깨졌습니다({type(e).__name__}): {logical}")
        return None


def _load_time(inp: ReportInputs, paths) -> None:
    for name, fname in TIME_FILES.items():
        val = _load(inp, "time." + name, time_file(paths, inp.run_id, fname), jsonl=fname.endswith(".jsonl"),
                    want=_WANT.get(name))
        setattr(inp.time, name, val)
        if val is None:
            if name in REQUIRED_TIME:
                inp.refused.append("time." + name)
            elif name in PARTIAL_TIME:
                inp.missing.append("time." + name)
    if inp.refused:
        inp.warn("time_missing", "시간 결과가 없습니다 — 분석을 다시 실행하면 만들어집니다",
                 files=sorted(inp.refused))


def _load_hier(inp: ReportInputs, paths) -> None:
    parts = []
    got = {}
    for fname in HIER_FILES:
        raw, _err = _raw(hier_file(paths, inp.run_id, fname))
        parts.append(fname.encode("ascii") + b"\0" + (raw if raw is not None else b"\0missing"))
        if raw is None:
            continue
        try:
            got[fname] = fsx.loads_strict(raw)
        except ValueError as e:
            inp.warn("input_broken:labels", f"분류 결과 파일 형식이 깨졌습니다({type(e).__name__}): {fname}")
    inp.digests["labels"] = sha16(b"\n".join(parts)) if got else MISSING
    labels = got.get("labels.json")
    if isinstance(labels, Mapping) and isinstance(labels.get("labels"), Mapping):
        labels = labels["labels"]
    if isinstance(labels, Mapping) and labels:
        inp.labels = {str(k): v for k, v in labels.items() if isinstance(v, Mapping)}
    else:
        inp.missing.append("labels")
        inp.warn("labels_missing", "분류 결과가 없어 모두 미분류로 보입니다")
    q = got.get("queue.json")
    meta = got.get("hier_meta.json")
    props = got.get("proposals_snapshot.json")
    inp.hier = {"groups": got.get("groups.json") if isinstance(got.get("groups.json"), Mapping) else None,
                "queue": [x for x in q if isinstance(x, Mapping)] if isinstance(q, list) else [],
                "meta": meta if isinstance(meta, Mapping) else {},
                "proposals": [x for x in (props.get("items") or []) if isinstance(x, Mapping)]
                if isinstance(props, Mapping) else []}


def _load_ai(inp: ReportInputs, paths) -> None:
    for st in AI_STAGES:
        obj = _load(inp, "ai." + st, paths.ai_out(st), want=dict)
        inp.ai[st] = obj if isinstance(obj, Mapping) else None


def _load_registry(inp: ReportInputs, paths, cfg, registry) -> None:
    """유효 레지스트리(팀 ⊕ 개인 로컬 — H §3.4). 서버에 묻지 않고(fetch=None) 쓰지 않는다(persist=False)."""
    if registry is not None:
        inp.registry = registry
        inp.registry_status = {"source": "given", "version": _attr(registry, "version", 0), "fetched_at": None}
    else:
        from lm27.hier.registry import load_effective
        try:
            reg, st = load_effective(paths, cfg, persist=False)
        except (OSError, ValueError, KeyError) as e:
            inp.warn("registry_unreadable", f"레지스트리를 읽지 못해 내장 어휘로 보입니다({type(e).__name__})")
            inp.digests["registry"] = MISSING
            return
        inp.registry = reg
        inp.registry_status = {"source": st.source, "version": int(st.version), "fetched_at": st.fetched_at,
                               "label_ko": st.label_ko()}
        if st.source == "builtin":
            inp.warn("registry_missing", "팀 레지스트리가 없어 과제 이름 대신 ID 를, 에이전트 목록 없이 보입니다")
    reg = inp.registry
    payload = {"hash": str(_attr(reg, "hier_hash", "") or ""), "version": _attr(reg, "version", 0),
               "source": (inp.registry_status or {}).get("source")}
    if isinstance(reg, Mapping):
        payload["obj"] = reg
    inp.digests["registry"] = sha16(fsx.canon_bytes(payload))


def _attr(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def _load_calendar(inp: ReportInputs, paths, cal) -> None:
    if cal is None:
        from lm27.time.calendar import load_calendar
        cal = load_calendar(paths, inp.registry)
    inp.calendar = cal
    inp.digests["calendar"] = sha16(fsx.canon_bytes({"version": str(getattr(cal, "version", "") or ""),
                                                     "source": str(getattr(cal, "source", "") or "")}))


def _period(inp: ReportInputs, paths) -> None:
    """분석 기간: current.json(같은 실행일 때) → run_status(메서드가 있으면) → 날짜 원장 날짜 → 봉투 날짜."""
    cur = fsx.read_json(paths.analysis_current(), None, want=dict)
    run = {"run_id": inp.run_id, "from": None, "to": None, "as_of": None, "chosen": None, "period_source": None}
    src = None
    if isinstance(cur, Mapping) and cur.get("run_id") == inp.run_id:
        src = cur
        run["chosen"] = cur.get("chosen") if cur.get("chosen") in ("auto", "explicit") else None
    rs_fn = getattr(paths, "run_status_file", None)
    if rs_fn is not None:
        rs = fsx.read_json(rs_fn(inp.run_id), None, want=dict)
        if isinstance(rs, Mapping) and (src is None or not src.get("from")):
            src = {**rs, **(src or {})}
    for k in ("period_source", "period_months"):
        if isinstance(src, Mapping) and src.get(k) is not None:
            run[k] = src.get(k)
    a = b = None
    if isinstance(src, Mapping) and _DATE_RX.match(str(src.get("from") or "")) and _DATE_RX.match(str(src.get("to") or "")):
        a, b = str(src["from"]), str(src["to"])
    if a is None and inp.time.day_ledger:
        ds = sorted(str(r.get("date")) for r in inp.time.day_ledger if _DATE_RX.match(str(r.get("date") or "")))
        if ds:
            a, b = ds[0], ds[-1]
    if a is None and inp.time.team_tables:
        rows = (inp.time.team_tables.get("envelope_daily") or {}).get("rows") or []
        ds = sorted(str(r[0]) for r in rows if r and _DATE_RX.match(str(r[0])))
        if ds:
            a, b = ds[0], ds[-1]
    if a is not None and b is not None and a > b:
        a, b = b, a
    inp.period = (a, b) if a is not None else None
    run["from"], run["to"] = a, b
    meta = inp.time.run_meta or {}
    inp.as_of = str(meta.get("as_of")) if meta.get("as_of") else None
    run["as_of"] = inp.as_of[:16] if inp.as_of else None
    inp.run = run
    inp.digests["run"] = sha16(fsx.canon_bytes({k: run.get(k) for k in sorted(run)}))


def analysis_time(paths, run_id: str, off_min: int) -> str | None:
    """그 실행의 분석 시각(근무 시간대 ISO 8601 + 오프셋) — run_status 의 끝 시각(없으면 시작), 둘 다 없으면 current.json
    의 built_at(같은 실행일 때). 머리 띠 '분석 MM-DD HH:MM' 과 분석 이력 표의 '분석 시각' 이 같은 값을 쓴다. 모델 파일에는
    넣지 않는다(G-R1 — 같은 입력 = 같은 모델 바이트). 화면 응답·자기완결 HTML 섬에만 덧붙인다. 모르면 None."""
    fn = getattr(paths, "run_status_file", None)
    st = fsx.read_json(fn(run_id), None, want=dict) if fn is not None and _RUN_RX.match(str(run_id)) else None
    for k in ("ended", "started"):
        v = st.get(k) if isinstance(st, Mapping) else None
        if isinstance(v, str) and v:
            if not v.endswith("Z"):
                return v
            from lm27.util.tz import to_local
            try:
                return to_local(v, int(off_min)).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                continue
    cur = fsx.read_json(paths.analysis_current(), None, want=dict)
    if isinstance(cur, Mapping) and cur.get("run_id") == run_id and isinstance(cur.get("built_at"), str):
        return cur["built_at"]
    return None


def tz_offset_of(inp: ReportInputs, cfg=None) -> int:
    """근무 시간대 오프셋(분) — run_meta.as_of 의 꼬리(+09:00), 없으면 설정 `time.tzOffsetMin`."""
    if inp.as_of:
        m = _OFF_RX.search(inp.as_of)
        if m:
            from lm27.util.tz import parse_offset
            try:
                return int(parse_offset(m.group(1)))
            except ValueError:
                pass
    return int(cfg["time.tzOffsetMin"]) if cfg is not None else 540


def _local_text(lsec: int) -> str:
    from lm27.report.analysis.activity import lmin_iso
    return str(lmin_iso(int(lsec) // 60)).replace("T", " ")


def _g(o, k, d=None):
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def _title(row: Mapping, kind: str) -> str:
    col = {"mail": "subject_masked", "cal": "subject_masked", "teams": "chat_title_masked",
           "pc_file": "name_masked", "manual": "text_masked"}.get(kind, "")
    v = row.get(col) if col else None
    s = " ".join(str(v).split()) if isinstance(v, str) else ""
    return s[:TITLE_MAX]


def evidence_from(ev, rows) -> EvidenceIndex:
    """시간 코어 `Evidence` + 적재 행 → 보고서 증거 보기. 증거 줄은 정제 열만(제목·시각·방향·상대 키)."""
    by_id = {str(r.get("id")): r for r in rows or () if isinstance(r, Mapping) and r.get("id")}
    lines: dict[str, dict] = {}
    for m in _g(ev, "msgs", ()) or ():
        rid = str(_g(m, "id", ""))
        row = by_id.get(rid, {})
        lines[rid] = {"kind": str(_g(m, "ch", "") or row.get("kind") or "mail"), "t": _local_text(_g(m, "t", 0)),
                      "dir": str(_g(m, "dir", "")), "prec": str(_g(m, "prec", "")), "who": str(_g(m, "peer", "")),
                      "title": _title(row, str(row.get("kind") or "mail")), "key": str(_g(m, "key", ""))}
    for mt in _g(ev, "meets", ()) or ():
        rid = str(_g(mt, "id", ""))
        row = by_id.get(rid, {})
        lines[rid] = {"kind": "meeting", "t": _local_text(_g(mt, "a", 0)), "dir": "", "prec": "",
                      "who": "", "title": _title(row, "cal"), "key": str(_g(mt, "key", "")),
                      "n_att": int(_g(mt, "n_att", 0) or 0)}
    for d in _g(ev, "docs", ()) or ():
        rid = str(_g(d, "id", ""))
        lines.setdefault(rid, {"kind": "file", "t": _local_text(_g(d, "t", 0)), "dir": "", "prec": "",
                               "who": "", "title": " ".join(str(_g(d, "raw", "") or "").split())[:TITLE_MAX],
                               "op": str(_g(d, "kind", "")), "fam": str(_g(d, "fam", ""))})
    leaves = {}
    for k, v in (_g(ev, "leaves", {}) or {}).items():
        leaves[k.isoformat() if isinstance(k, date) else str(k)[:10]] = str(v)
    absences = sorted({_g(m, "d").isoformat() for m in (_g(ev, "manual", ()) or ())
                       if _g(m, "kind") == "absence" and isinstance(_g(m, "d"), date)})
    return EvidenceIndex(msgs=list(_g(ev, "msgs", ()) or ()), meets=list(_g(ev, "meets", ()) or ()),
                         docs=list(_g(ev, "docs", ()) or ()), fam_names=dict(_g(ev, "fam_names", {}) or {}),
                         lines=lines, leaves=leaves, absences=absences)


def load_evidence_index(paths, cfg, d0, d1, as_of) -> EvidenceIndex:
    """번들 단일 로더 → 시간 코어 정규화(분석과 같은 함수 — conv·peer·문서군 키가 tasks.json 과 맞는다)."""
    from lm27.normalize.load import load_evidence
    from lm27.time.evidence import normalize
    a = date.fromisoformat(d0)
    b = date.fromisoformat(d1)
    rows = load_evidence(paths, cfg, a - timedelta(days=1), b + timedelta(days=1), audit=False)
    ev, _audit = normalize(rows, {"d0": a, "d1": b}, cfg, as_of, None)
    return evidence_from(ev, rows)


def _load_evidence(inp: ReportInputs, paths, cfg, evidence) -> None:
    if isinstance(evidence, EvidenceIndex):
        idx = evidence
    elif evidence is False or not inp.period or not inp.as_of:
        inp.digests["evidence"] = MISSING
        return
    else:
        try:
            idx = load_evidence_index(paths, cfg, inp.period[0], inp.period[1], inp.as_of)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
            inp.digests["evidence"] = MISSING
            inp.warn("evidence_unreadable", f"근거 기록을 읽지 못해 근거 줄 없이 보입니다({type(e).__name__})")
            return
    inp.digests["evidence"] = idx.digest()
    inp.leaves, inp.absences = dict(idx.leaves), list(idx.absences)
    if idx.usable or idx.lines or idx.fam_names:
        inp.evidence = idx
    else:
        inp.warn("evidence_empty", "이 PC 의 번들에서 근거 기록을 찾지 못했습니다 — 동료 관계는 시간 결과를 그대로 씁니다")


def _load_meet_tags(inp: ReportInputs, paths) -> None:
    """회의 레코드의 분류 꼬리표(``hier\\evidence_tags.jsonl`` 의 ``{id, proj}`` — 규칙이 그 회의 제목·시리즈를 과제 키워드와
    맞춘 결과) → ``inp.hier['meet_tags']`` {회의 레코드 id: 과제}. 업무 트리 과제 행의 '관련 미귀속 회의 …(MM 미포함)' 주석
    재료(R §6.3.1). 증거(회의 목록)가 없거나 파일이 없으면 빈 값. 과제 꼬리표가 없는 줄은 풀지 않고 넘긴다(큰 파일)."""
    ev = inp.evidence
    meets = {str(_g(m, "id", "") or "") for m in (ev.meets if ev is not None else ())} - {""}
    tags: dict[str, str] = {}
    if meets:
        raw, _err = _raw(hier_file(paths, inp.run_id, TAGS_FILE))
        for ln in (raw or b"").splitlines():
            if b'"proj":null' in ln or b'"proj"' not in ln:
                continue
            try:
                r = fsx.loads_strict(ln)
            except ValueError:
                continue
            if isinstance(r, Mapping) and str(r.get("id") or "") in meets and isinstance(r.get("proj"), str) and r["proj"]:
                tags[str(r["id"])] = r["proj"]
    inp.hier = {**(inp.hier or {}), "meet_tags": dict(sorted(tags.items()))}
    inp.digests["meet_tags"] = sha16(fsx.canon_bytes(inp.hier["meet_tags"])) if tags else MISSING


def _load_local(inp: ReportInputs, paths) -> None:
    pd = _load(inp, "person_dir", paths.local_only_file("person_dir.json"), want=dict)
    inp.person_dir = pd if isinstance(pd, Mapping) and isinstance(pd.get("people"), Mapping) else None
    ov = _load(inp, "overrides", paths.team_overrides(), want=dict)
    inp.overrides = ov if isinstance(ov, Mapping) else None


def _load_bundle_state(inp: ReportInputs, paths) -> None:
    """화면용(모델·다이제스트 밖) — 커버리지 원장·todo·대기열 meta."""
    raw, _e = _raw(paths.coverage_ledger())
    if raw is not None:
        try:
            inp.bundle_state.coverage = _parse(raw, True, None)
        except ValueError:
            inp.bundle_state.coverage = None
    inp.bundle_state.todo = fsx.read_json(paths.todo(), None, want=None)
    fn = getattr(paths, "outbox_file", None)
    if fn is None:
        return
    from lm27.paths import OUTBOX_STATES
    for st in OUTBOX_STATES:
        try:
            names = sorted(os.listdir(paths.outbox(st)))
        except OSError:
            continue
        for nm in names:
            if nm.endswith(".meta.json"):
                m = fsx.read_json(fn(st, nm), None, want=dict)
                if isinstance(m, Mapping):
                    inp.outbox.append({"state": st, "name": nm[: -len(".meta.json")], **m})


def load_inputs(run_id: str, *, paths=None, cfg=None, registry=None, cal=None, evidence=True,
                bundle_state: bool = True) -> ReportInputs:
    """R 부록 A `load_inputs(run_id) -> ReportInputs`. 키워드는 시험·파이프라인 주입점:
    paths·cfg(없으면 `Paths()`·`load_config`) · registry(유효 레지스트리 — 없으면 `load_effective`) · cal(달력 — 없으면
    `load_calendar(paths, 레지스트리)`) · evidence(True = 번들에서 적재 · False = 읽지 않음 · `EvidenceIndex` = 그것).
    필수 시간 결과가 없으면 `refused` 에 남긴다(호출자가 rc 1 — 보고서를 만들지 않는다)."""
    if not isinstance(run_id, str) or not _RUN_RX.match(run_id):
        raise ValueError("run_id 형식이 아닙니다(YYYYMMDD-HHMMSS-xxxx)")
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths)
    inp = ReportInputs(run_id=run_id)
    _load_time(inp, paths)
    _load_hier(inp, paths)
    _load_ai(inp, paths)
    _load_local(inp, paths)
    _load_registry(inp, paths, cfg, registry)
    _load_calendar(inp, paths, cal)
    _period(inp, paths)
    if not inp.refused:
        _load_evidence(inp, paths, cfg, evidence)
        _load_meet_tags(inp, paths)
    else:
        inp.digests["evidence"] = MISSING
    if bundle_state:
        _load_bundle_state(inp, paths)
    return inp
