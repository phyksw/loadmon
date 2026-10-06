# -*- coding: utf-8 -*-
r"""설명 원장·결과 파일 — 시간 코어 B(W §7.4 · §7.5 · 부록 A `ledger.py`, 계약 §3.14 `timecore/1.1`).

- `TimeResult`: 한 번의 분석 결과(정규화·봉투·업무·귀속·정수 분 표·월 MM·확인 큐). `files()` 가 계약 §3.14 의 파일 9종
  (env_slots.jsonl · day_ledger.jsonl · interval_ledger.jsonl · tasks.json · attrib.jsonl · team_tables.json ·
  mm_month.json · confirm_queue.json · run_meta.json)을 정규 바이트(`lm27.util.fsx.canon_bytes`, JSONL 은 한 줄 한 행 +
  LF)로 만든다 — 같은 입력·as_of·설정이면 같은 바이트(T-02).
- 모든 시간량은 정수 초(`*_s`) 또는 정수 분(`*_min`·`min`)이다. 시각은 로컬 초(lsec — 2020-01-01 00:00 로컬 기준,
  계약 §3.14), 구간 원장의 `a`·`b` 는 로컬 분(lsec // 60).
- 원장은 **키와 숫자만** 담는다(W-G8 · T-07): unit_id·버킷·문서군 키·메시지 키·회의 키·근거 코드·한국어 고정 항목명.
  제목·문서 이름·본문 원문은 없다. 화면은 로컬에서만 키를 정제된 이름으로 풀어 보인다(R §3.6).
- `day_ledger(result, day)` · `interval_ledger(result, day)` · `task_ledger(result, task_id)` 는 사람이 읽는 한 줄
  설명(W §7.4 형식 — 키·숫자만)이다.

표준 라이브러리만 쓴다. 이 모듈은 파일을 쓰지 않는다(쓰기는 `lm27.time.write_time_files` → `fsx.atomic_write`).
"""
from __future__ import annotations

import bisect
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from lm27.time.calendar import EPOCH, SLOT, TAGS, d_of, day0
from lm27.time.intervals import IvIx, lr_minutes
from lm27.util.fsx import canon_bytes

__all__ = [
    "CORE_VERSION",
    "FILES",
    "TimeResult",
    "day_ledger",
    "day_ledger_rows",
    "input_digest",
    "interval_ledger",
    "interval_ledger_rows",
    "parallel_of",
    "pre_request",
    "task_ledger",
    "task_rows",
]

CORE_VERSION = "timecore/1.1"
FILES = ("env_slots.jsonl", "day_ledger.jsonl", "interval_ledger.jsonl", "tasks.json", "attrib.jsonl",
         "team_tables.json", "mm_month.json", "confirm_queue.json", "run_meta.json")
MIN = 60
SLOT_MIN = SLOT // MIN
LEVEL_KEYS = ("L1", "L2", "L3", "L4", "L5", "L6", "L7")
DEDUCT = ("사적차감", "개인일정차감", "사용자제외")
EXCLUDE = ("창밖_무자격_제외", "창밖_골격밖_제외", "잠금단절_다리없음", "사적단절_다리없음", "점심차감", "수신상한_제외")
ENV_PREFIX = "봉투_"
PRIO = ("C11", "C11u", "C2", "C1", "C3", "C4", "C1b", "C4L", "C6", "C7", "C8", "C8d", "C9", "C10", "C10r", "C12", "C5")
CONF = ("high", "mid", "low")
CONF_OF = {"C11": "high", "C11u": "high", "C2": "high", "C1": "high", "C3": "high", "C4": "mid", "C1b": "mid",
           "C4L": "mid", "C5": "mid", "C6": "mid", "C7": "mid", "C8": "low", "C8d": "low", "C9": "low", "C10": "low",
           "C10r": "low", "C12": "low"}
OBSERVED = frozenset({"L1", "L2회의", "L3PC"})


def _round_min(sec: int) -> int:
    return (int(sec) + 30) // MIN


def _local_iso(t: int, off_min: int) -> str:
    dt = datetime(EPOCH.year, EPOCH.month, EPOCH.day) + timedelta(seconds=int(t))
    sign = "+" if off_min >= 0 else "-"
    h, m = divmod(abs(int(off_min)), 60)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f"{sign}{h:02d}:{m:02d}"


def _hhmm(t: int) -> str:
    m = (t - day0(d_of(t))) // MIN
    return f"{m // 60:02d}:{m % 60:02d}"


def _hm_text(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}:{m:02d}"


def input_digest(records: Iterable) -> str:
    """입력 다이제스트 — 행마다 정규 JSON sha256 을 정렬해 다시 sha256(입력 순서와 무관, T-02)."""
    hs = []
    for r in records:
        b = json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        hs.append(hashlib.sha256(b).hexdigest())
    hs.sort()
    return hashlib.sha256("\n".join(hs).encode("ascii")).hexdigest()


def _grade(level: str, target: str) -> str:
    if str(target).startswith("B_"):
        return "X"
    return "O" if level in OBSERVED else "I"


@dataclass
class TimeResult:
    """시간 코어 결과(W 부록 A `TimeResult` — X-217 구현 정의). 파일 열은 계약 §3.14 `timecore/1.1`."""
    ev: object
    days: dict
    env: object
    tasks: list
    attribution: object
    tables: object
    months: dict
    queue: list
    cfg_used: dict
    cfg_hash: str
    calendar_version: str
    as_of: int
    tz_offset_min: int
    input_digest: str
    warnings: list = field(default_factory=list)
    parallel: dict = field(default_factory=dict)
    labels: dict | None = None
    core_version: str = CORE_VERSION

    # --- 편의 ---
    @property
    def assign(self) -> dict[int, dict[str, int]]:
        return self.attribution.assign

    @property
    def level(self) -> dict[int, str]:
        return self.attribution.level

    def effort(self) -> Counter:
        """대상(unit_id·버킷)별 귀속 초."""
        return self.attribution.effort()

    def task(self, unit_id: str):
        return next((t for t in self.tasks if t.id == unit_id), None)

    def env_minutes(self) -> int:
        return len(self.env.slots) * SLOT_MIN

    def bucket_sec(self) -> dict[str, int]:
        return {k: v for k, v in sorted(self.effort().items()) if k.startswith("B_")}

    # --- 파일 ---
    def env_slots_rows(self) -> list[dict]:
        env = self.env
        return [{"date": d_of(s * SLOT).isoformat(), "slot": s, "tag": env.tags[s], "basis": env.basis[s],
                 "conf": CONF_OF.get(env.basis[s], "low"), "on_leave": s in env.on_leave,
                 "pcs": list(env.pcs.get(s, ()))} for s in sorted(env.slots)]

    def run_meta(self) -> dict:
        return {"core_version": self.core_version, "calendar_version": self.calendar_version,
                "cfg_used": self.cfg_used, "cfg_hash": self.cfg_hash,
                "as_of": _local_iso(self.as_of, self.tz_offset_min), "input_digest": self.input_digest,
                "audit": dict(sorted((str(k), int(v)) for k, v in self.ev.audit.items())),
                "warnings": [str(w) for w in self.warnings]}

    def mm_rows(self) -> list[dict]:
        return [self.months[k] for k in sorted(self.months)]

    def files(self) -> dict[str, bytes]:
        """계약 §3.14 파일 9종의 정규 바이트."""
        def jl(rows):
            return b"".join(canon_bytes(r) + b"\n" for r in rows)
        return {
            "env_slots.jsonl": jl(self.env_slots_rows()),
            "day_ledger.jsonl": jl(day_ledger_rows(self)),
            "interval_ledger.jsonl": jl(interval_ledger_rows(self)),
            "tasks.json": canon_bytes(task_rows(self)),
            "attrib.jsonl": jl(self.attribution.rows()),
            "team_tables.json": canon_bytes(self.tables.as_json()),
            "mm_month.json": canon_bytes(self.mm_rows()),
            "confirm_queue.json": canon_bytes([q.to_row() for q in self.queue]),
            "run_meta.json": canon_bytes(self.run_meta()),
        }


# ───────────────────────────── 날짜 원장 ─────────────────────────────
def day_ledger_rows(res: TimeResult) -> list[dict]:
    """day_ledger.jsonl — 분석 기간 날짜마다 {date, total_min, components, deductions, excluded, by_tag_min, conf_min,
    coverage, flags}. 구성요소·차감·제외는 봉투 원장(`Envelope.ledger` 정수 초)을 분으로(반올림)."""
    env, ev = res.env, res.ev
    by_tag: dict[date, Counter] = defaultdict(Counter)
    conf: dict[date, Counter] = defaultdict(Counter)
    for s in env.slots:
        d = d_of(s * SLOT)
        by_tag[d][env.tags[s]] += SLOT_MIN
        conf[d][CONF_OF.get(env.basis[s], "low")] += SLOT_MIN
    cov: dict[date, dict[str, str]] = defaultdict(dict)
    for (d, ax), st in ev.coverage.items():
        cov[d][ax] = st
    dates = {d for d, i in res.days.items() if i.get("in_range")}      # 분석 기간 안 날짜만(앞뒤 여유일은 문맥)
    out = []
    for d in sorted(dates):
        led = env.ledger.get(d, Counter())
        n = env.ledger_n.get(d, Counter())
        comps = [[k, _round_min(led.get(ENV_PREFIX + k, 0))] for k in PRIO if led.get(ENV_PREFIX + k, 0)]
        ded = [[k, _round_min(led[k]), int(n.get(k, 0))] for k in DEDUCT if led.get(k, 0)]
        exc = [[k, _round_min(led[k]), int(n.get(k, 0))] for k in EXCLUDE if led.get(k, 0)]
        out.append({"date": d.isoformat(), "total_min": sum(by_tag[d].values()), "components": comps,
                    "deductions": ded, "excluded": exc, "by_tag_min": {t: by_tag[d].get(t, 0) for t in TAGS},
                    "conf_min": {c: conf[d].get(c, 0) for c in CONF}, "coverage": dict(sorted(cov[d].items())),
                    "flags": [str(f) for f in env.flags.get(d, ())]})
    return out


def interval_ledger_rows(res: TimeResult) -> list[dict]:
    """interval_ledger.jsonl — 같은 근거·꼬리표·귀속 분포·단계가 이어지는 슬롯 구간을 한 행으로:
    {date, a, b(로컬 분), tag, basis, targets[[대상, 분, 등급 O|I|X]], note(귀속 단계)}. 분은 구간 안 대상별 초를
    최대잉여법으로 나눈 정수(Σ = 구간 분)."""
    env, att = res.env, res.attribution
    out = []
    cur = None
    for s in sorted(env.slots):
        dist = att.assign[s]
        key = (d_of(s * SLOT), env.tags[s], env.basis[s], att.level[s], tuple(sorted(dist.items())))
        if cur is not None and cur["key"] == key and cur["b"] == s:
            cur["b"] = s + 1
            continue
        if cur is not None:
            out.append(cur)
        cur = {"key": key, "a": s, "b": s + 1}
    if cur is not None:
        out.append(cur)
    rows = []
    for r in out:
        d, tag, basis, lv, dist = r["key"]
        n = r["b"] - r["a"]
        sec = {k: v * n for k, v in dist}
        mins = lr_minutes(sec, n * SLOT_MIN)
        targets = [[k, int(mins.get(k, 0)), _grade(lv, k)] for k, _v in sorted(dist, key=lambda x: (-x[1], x[0]))]
        rows.append({"date": d.isoformat(), "a": r["a"] * SLOT // MIN, "b": r["b"] * SLOT // MIN, "tag": tag,
                     "basis": basis, "targets": targets, "note": lv})
    return rows


# ───────────────────────────── 업무 원장 ─────────────────────────────
def _biz(reg_ix: IvIx, a: int, b: int) -> int:
    return reg_ix.length(a, b) if b > a else 0


def task_rows(res: TimeResult) -> list[dict]:
    """tasks.json — 단위업무마다 계약 §3.14 열(시각은 로컬 초, 시간량은 정수 초)."""
    ev, att = res.ev, res.attribution
    eff = att.effort()
    eff_lv = att.effort_levels()
    reg_ix = IvIx(getattr(res.env, "reg", ()) or ())
    ctx = getattr(res.tasks, "ctx", None)
    # 문서군 조작 수(save·export·attach) — 업무에 귀속된 사건만
    ops: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    if ctx is not None and ctx.attribution is not None:
        from lm27.time.attribute import resolve
        for e in ev.docs:
            if e.other or not e.fam or e.kind not in ("save", "create", "export"):
                continue
            r = resolve(e.fam, e.t, ctx)
            if isinstance(r, dict):
                for tid in r:
                    ops[tid][e.fam]["export" if e.kind == "export" else "save"] += 1
        for m in ev.msgs:
            tid = ctx.msg_task.get(m.id)
            if tid and m.dir == "out":
                for f in m.atts:
                    ops[tid][f]["attach"] += 1
    out = []
    for tk in res.tasks:
        c0, cl = tk.cycles[0], tk.cycles[-1]
        lead = biz = None
        if cl.e is not None and not c0.unstarted:
            lead = sum(c.e - c.s for c in tk.cycles if c.e is not None)
            biz = sum(_biz(reg_ix, c.s, c.e) for c in tk.cycles if c.e is not None)
        docs = {}
        for f in sorted(set(tk.docs) | set(ops.get(tk.id, {}))):
            o = ops.get(tk.id, {}).get(f, Counter())
            docs[f] = {"n": int(sum(o.values())), "ops": {k: int(o.get(k, 0)) for k in ("save", "export", "attach")}}
        lv = eff_lv.get(tk.id, Counter())
        peers = [{"who_key": w, "rel": r} for w in sorted(tk.rels) if isinstance(w, str) and w.startswith("w")
                 for r in ("requester", "reporter", "thread", "meeting") if r in tk.rels[w]]
        out.append({
            "unit_id": tk.id, "kind": tk.kind, "label": tk.label, "conv": tk.conv, "peer": tk.peer, "peers": peers,
            "docs": docs,
            "cycles": [{"s": c.s, "sb": c.sb, "e": c.e, "eb": c.eb, "s_ref": c.s_ref, "e_ref": c.e_ref,
                        "interim": [[t, code] for t, code in c.interim], "unstarted": bool(c.unstarted)}
                       for c in tk.cycles],
            "grade": tk.grade, "status": tk.status, "lead_s": lead, "biz_lead_s": biz,
            "effort_s": int(eff.get(tk.id, 0)), "levels_s": {k: int(lv.get(k, 0)) for k in LEVEL_KEYS},
            "parallel": round(float(res.parallel.get(tk.id, 0.0)), 4), "machine_s": int(tk.machine_s),
            "pre_request_s": int(tk.pre_request_s), "flags": [str(f) for f in tk.flags], "proj": tk.proj,
            "first_key": tk.first_key, "follow_of": tk.follow_of,
        })
    return out


# ───────────────────────────── 사람이 읽는 한 줄(W §7.4 — 키·숫자만) ─────────────────────────────
def _as_date(day) -> date:
    return day if isinstance(day, date) else date.fromisoformat(str(day)[:10])


def day_ledger(res: TimeResult, day) -> str:
    """날짜 원장 한 줄: 'YYYY-MM-DD H:MM = 근거 H:MM + … | 차감·제외 −H:MM … | 꼬리표 H:MM …'."""
    d = _as_date(day)
    row = next((r for r in day_ledger_rows(res) if r["date"] == d.isoformat()), None)
    if row is None:
        return f"{d.isoformat()} 0:00 = - | - | -"
    parts = " + ".join(f"{k} {_hm_text(v)}" for k, v in row["components"]) or "-"
    ded = " ".join(f"{k} −{_hm_text(v)}" for k, v, _n in row["deductions"] + row["excluded"]) or "-"
    tg = " · ".join(f"{k} {_hm_text(v)}" for k, v in row["by_tag_min"].items() if v) or "-"
    return f"{row['date']} {_hm_text(row['total_min'])} = {parts} | {ded} | {tg}"


def interval_ledger(res: TimeResult, day) -> list[str]:
    """구간 원장 줄들: 'HH:MM~HH:MM 꼬리표 근거 대상×분 … [등급] 단계'."""
    d = _as_date(day).isoformat()
    out = []
    for r in interval_ledger_rows(res):
        if r["date"] != d:
            continue
        a, b = r["a"] * MIN, r["b"] * MIN
        tg = "+".join(f"{k}×{m}" for k, m, _g in r["targets"])
        g = "/".join(sorted({x[2] for x in r["targets"]}))
        out.append(f"{_hhmm(a)}~{_hhmm(b) if b % 86400 else '24:00'} {r['tag']} {r['basis']} {tg} [{g}] {r['note']}")
    return out


def task_ledger(res: TimeResult, task_id: str) -> str:
    """업무 원장 한 줄: '표지 등급 시작근거 MM-DD HH:MM → 종료근거 … | 리드 H:MM(영업 H:MM) | 투입 H:MM = L3 … | 표식'."""
    row = next((r for r in task_rows(res) if r["unit_id"] == task_id), None)
    if row is None:
        return f"{task_id} -"
    c0, cl = row["cycles"][0], row["cycles"][-1]

    def at(t):
        if t is None:
            return "-"
        d = d_of(t)
        return f"{d.month:02d}-{d.day:02d} {_hhmm(t)}"
    lead = "-" if row["lead_s"] is None else f"{_hm_text(row['lead_s'] // MIN)}(영업 {_hm_text(row['biz_lead_s'] // MIN)})"
    lv = " + ".join(f"{k} {_hm_text(v // MIN)}" for k, v in row["levels_s"].items() if v) or "-"
    fl = " · ".join(row["flags"]) or "-"
    return (f"{row['label']} {row['grade']} {c0['sb']} {at(c0['s'])} → {cl['eb'] or 'OPEN'} {at(cl['e'])} | "
            f"리드 {lead} | 투입 {_hm_text(row['effort_s'] // MIN)} = {lv} | {fl}")


# ───────────────────────────── 병행도 ─────────────────────────────
def parallel_of(att, slots: Iterable[int]) -> dict[str, float]:
    """업무별 병행도(W §5.5) = 그 업무가 귀속받은 슬롯에서 창이 열린 업무 수의 평균(슬롯 시작 시각 기준)."""
    ev_pts: list[tuple[int, int]] = []
    for ix in att.win.values():
        for a, b in ix.iv:
            ev_pts.append((a, 1))
            ev_pts.append((b, -1))
    ev_pts.sort()
    times = [t for t, _ in ev_pts]
    pref = []
    acc = 0
    for _t, dv in ev_pts:
        acc += dv
        pref.append(acc)

    def open_at(t: int) -> int:
        i = bisect.bisect_right(times, t) - 1
        return pref[i] if i >= 0 else 0
    cnt: dict[int, int] = {s: open_at(s * SLOT) for s in slots}
    tot: Counter = Counter()
    n: Counter = Counter()
    for s, dist in att.assign.items():
        for tid in dist:
            if tid.startswith("B_") or tid not in att.win:
                continue
            tot[tid] += cnt.get(s, 0)
            n[tid] += 1
    return {tid: tot[tid] / n[tid] for tid in sorted(n)}


def pre_request(att, tasks) -> None:
    """선행 착수 귀속 초(W §4.9.1 `pre_request_s`) — 공식 시작 전 슬롯에 귀속된 초."""
    by: dict[str, int] = {t.id: t.cycles[0].s for t in tasks if t.pre_from is not None and t.cycles}
    acc: Counter = Counter()
    for s, dist in att.assign.items():
        for tid, v in dist.items():
            st = by.get(tid)
            if st is not None and s * SLOT < st:
                acc[tid] += v
    for t in tasks:
        t.pre_request_s = int(acc.get(t.id, 0)) if t.pre_from is not None else 0
