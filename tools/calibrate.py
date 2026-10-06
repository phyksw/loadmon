# -*- coding: utf-8 -*-
r"""시간 파라미터 격자 보정 — ``python\python.exe -B tools\calibrate.py --keys <k,…> [--grid <json>]``(W §8.3 · 계약 §7.3).

정답 세트 = 사용자가 남긴 **시각 있는 수동 기록**(manual 행): `work`(a·b·참조) · 확인 응답 `instr`·`report`
(경계 시각) · `must_link`(같은 업무) · `exclude`(업무 아님). 정답 행은 분석 입력에서 빼고(보정이 정답을 베끼지 않게)
나머지로 시간 코어를 돌린 뒤 정답과 견준다.

목적 함수(낮을수록 좋음) `J = w1·봉투 오차 + w2·경계 오차(분)/60 + w3·(1 − 귀속 일치율)`, 기본 w = (1.0, 0.5, 1.0).
- 봉투 오차 = 정답 근무가 있는 날마다 |정답 구간(첫 시작~마지막 끝) 안 봉투 분 − 정답 분| / 정답 분의 평균
  (+ `exclude` 구간마다 봉투에 남은 비율). 정답이 일부 구간만 있으면 그 구간에서만 잰다.
- 경계 오차 = `instr`·`report` 응답마다 업무 시작·끝과 응답 시각의 차(분) 평균(업무 찾기는 W §4.8 규칙).
- 귀속 일치율 = 참조가 있는 `work` 구간에서 그 문서군 업무에 귀속된 초의 비율 + `must_link` 충족 여부의 평균.

격자: ★(미보정) 키만, 한 번에 1~3개 키, 키당 2~5단계. 다른 키는 기본값(실행 설정) 고정.
가드: ① 보존(Σ귀속 = 봉투 — 시간 코어가 매 실행 확인)과 단조성 탐침(PC 가동 기록을 빼면 봉투가 늘지 않아야)을
통과한 값만 후보 ② 기본값 대비 J 개선이 5% 미만이면 바꾸지 않는다 ③ 정답 날짜 < 10 이면 '자료 부족'만 보고
④ **자동 적용 금지** — 보고서(`calibration_report.json` 형, 스키마 `lm27.calibration/1`)만 내고 설정 파일은 건드리지
않는다. 사용자가 승인해야 개인 덮어쓰기에 쓴다(화면 몫).

명령줄: ``--keys k1,k2 [--grid '{"k1":[…]}'] --from YYYY-MM-DD --to YYYY-MM-DD [--as-of ISO] [--out 파일]`` —
보고서는 `--out`(사용자가 고른 경로, `fsx.atomic_write`) 또는 표준 출력. 종료 코드 0 보고 · 1 인자·내부 오류 ·
2 자료 부족(보고는 냄). 번들 적재(`lm27.normalize.load`)·키링(`lm27.privacy.keys`)이 아직 없으면 rc 1 + 한국어 한 줄.
원문은 다루지 않는다(정제 후 행·키·숫자만).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import argparse
import importlib.util
import itertools
import json
from collections import Counter
from datetime import date, datetime

from lm27.time.calendar import SLOT, d_of
from lm27.time.tokens import tok_sim
from lm27.util.fsx import atomic_write, canon_bytes

SCHEMA = "lm27.calibration/1"
WEIGHTS = (1.0, 0.5, 1.0)
MIN_TRUTH_DAYS = 10
MIN_GAIN = 0.05
TRUTH_KINDS = ("work", "instr", "report", "must_link", "exclude")
MAX_KEYS, MIN_STEPS, MAX_STEPS = 3, 2, 5
EXAMPLE_GRID = {"episode.dormantWd": [3, 5, 7, 10], "time.envelope.preWindowMin.mail": [10, 20, 30],
                "episode.s2PrePadMin": [15, 30, 60]}           # W §8.3 예시 격자
USAGE = ("사용: calibrate.py --keys <k,…> --from YYYY-MM-DD --to YYYY-MM-DD [--grid <json>] [--as-of ISO] "
         "[--out 파일]")


class CalibrationError(ValueError):
    """보정 인자 오류(미등록·보정 대상 아닌 키, 격자 크기)."""


# ───────────────────────────── 정답 세트 ─────────────────────────────
def is_truth(row) -> bool:
    """정답 행인가: 시각 있는 수동 기록(work a·b, instr·report a, exclude a·b) 또는 must_link."""
    if not isinstance(row, dict) or row.get("kind") != "manual":
        return False
    mk = row.get("man_kind") or "work"
    if mk not in TRUTH_KINDS:
        return False
    if mk == "must_link":
        return True
    return row.get("ts_precision") in ("exact", "minute")


def split_truth(records):
    """(분석 입력, 정답 행) — 정답 행은 입력에서 뺀다."""
    inputs, truth = [], []
    for r in records:
        (truth if is_truth(r) else inputs).append(r)
    return inputs, truth


def truth_mans(records, truth, profile, cfg, as_of) -> list:
    """정답 행을 시간 코어 `Man` 으로(문서군 키가 입력 전체의 이름 색인과 같게 — 같은 정규화)."""
    from lm27.time.evidence import normalize
    ids = {str(r.get("id") or "") for r in truth}
    ev, _ = normalize(list(records) + list(truth), profile, cfg, as_of, None)
    return [m for m in ev.manual if m.id in ids]


# ───────────────────────────── 평가 ─────────────────────────────
def _find_task(res, m, ml: int):
    """확인 응답이 가리키는 업무(W §4.8 — 문서군 ∈ 업무 문서 · 첫 근거 키 · 토큰 유사 ≥ 0.5, 첫 진행이 가장 가까운 것)."""
    cands = [t for t in res.tasks if t.kind != "APP" and
             ((m.ref and m.ref in t.docs) or (m.key and m.key == t.first_key) or
              (m.tokens and tok_sim(set(m.tokens), set(t.tokens), ml) >= 0.5))]
    if not cands or m.a is None:
        return None
    return min(cands, key=lambda t: (abs((t.p_times[0] if t.p_times else res.as_of) - m.a), t.id))


def evaluate(res, truth: list, cfg, weights=WEIGHTS) -> dict:
    """정답 대비 J·구성 항목. 슬롯은 로컬 초 // 300. 시간량은 정수 분."""
    ml = int(cfg["episode.tokens.minSubLen"])
    slots = res.env.slots
    by_day: dict[date, list] = {}
    for m in truth:
        if m.kind == "work" and m.a is not None and m.b is not None and m.b > m.a:
            by_day.setdefault(d_of(m.a), []).append((m.a, m.b))
    errs = []
    for _d, ivs in sorted(by_day.items()):
        lo, hi = min(a for a, _ in ivs), max(b for _, b in ivs)
        truth_min = sum(b - a for a, b in ivs) // 60
        env_in = sum(1 for s in range(lo // SLOT, (hi - 1) // SLOT + 1) if s in slots) * (SLOT // 60)
        if truth_min > 0:
            errs.append(abs(env_in - truth_min) / truth_min)
    for m in truth:
        if m.kind == "exclude" and m.a is not None and m.b is not None and m.b > m.a:
            n = (m.b - 1) // SLOT - m.a // SLOT + 1
            errs.append(sum(1 for s in range(m.a // SLOT, (m.b - 1) // SLOT + 1) if s in slots) / n)
    bounds = []
    for m in truth:
        if m.kind not in ("instr", "report"):
            continue
        tk = _find_task(res, m, ml)
        if tk is None:
            continue
        t = tk.cycles[0].s if m.kind == "instr" else (tk.cycles[-1].e if tk.cycles[-1].e is not None else res.as_of)
        bounds.append(abs(t - m.a) / 60)
    agree = []
    for m in truth:
        if m.kind == "work" and m.ref and m.a is not None and m.b is not None and m.b > m.a:
            ids = {t.id for t in res.tasks if m.ref in t.docs}
            tot = hit = 0
            for s in range(m.a // SLOT, (m.b - 1) // SLOT + 1):
                dist = res.assign.get(s)
                if not dist:
                    continue
                tot += sum(dist.values())
                hit += sum(v for k, v in dist.items() if k in ids)
            if tot:
                agree.append(hit / tot)
        elif m.kind == "must_link" and m.ref:
            agree.append(1.0 if any(t.first_key == m.key and m.ref in t.docs for t in res.tasks) else 0.0)
    w1, w2, w3 = weights
    E = sum(errs) / len(errs) if errs else None
    B = sum(bounds) / len(bounds) if bounds else None
    A = sum(agree) / len(agree) if agree else None
    J = (w1 * E if E is not None else 0.0) + (w2 * B / 60 if B is not None else 0.0) + \
        (w3 * (1 - A) if A is not None else 0.0)
    grades = Counter(t.grade for t in res.tasks)
    return {"J": round(J, 6), "E": None if E is None else round(E, 6), "B": None if B is None else round(B, 3),
            "A": None if A is None else round(A, 6), "env_min": len(slots) * (SLOT // 60),
            "grades": dict(sorted(grades.items())), "n_days": len(by_day), "n_bound": len(bounds),
            "n_attr": len(agree)}


# ───────────────────────────── 격자 ─────────────────────────────
def check_keys(keys, cfg) -> list[str]:
    keys = [k for k in (str(x).strip() for x in keys) if k]
    if not 1 <= len(keys) <= MAX_KEYS:
        raise CalibrationError(f"한 번에 1~{MAX_KEYS}개 키만 보정합니다({len(keys)}개)")
    for k in keys:
        if k not in cfg:
            raise CalibrationError(f"등록되지 않은 설정 키: {k}")
        if not cfg.meta(k).uncalibrated:
            raise CalibrationError(f"미보정(★) 키가 아닙니다: {k}")
    return keys


def default_grid(keys, cfg) -> dict:
    """격자 기본값: W §8.3 예시가 있으면 그것, 아니면 현재 값 × (0.5, 1, 1.5, 2)를 범위 안으로(정수 키는 반올림)."""
    out = {}
    for k in keys:
        if k in EXAMPLE_GRID:
            out[k] = list(EXAMPLE_GRID[k])
            continue
        meta = cfg.meta(k)
        v = cfg[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CalibrationError(f"수치 키만 기본 격자를 만들 수 있습니다 — --grid 로 값을 주세요: {k}")
        rng = meta.range or {}
        vals = []
        for f in (0.5, 1.0, 1.5, 2.0):
            x = v * f
            if isinstance(v, int):
                x = int(round(x))
            if "min" in rng:
                x = max(rng["min"], x)
            if "max" in rng:
                x = min(rng["max"], x)
            if x not in vals:
                vals.append(x)
        out[k] = vals
    return out


def check_grid(grid: dict, keys, cfg) -> dict:
    out = {}
    for k in keys:
        vals = list(grid.get(k) or [])
        if not MIN_STEPS <= len(vals) <= MAX_STEPS:
            raise CalibrationError(f"키당 {MIN_STEPS}~{MAX_STEPS}단계여야 합니다: {k}({len(vals)}단계)")
        for v in vals:
            from lm27.config import check_value
            why = check_value(k, v)
            if why:
                raise CalibrationError(f"격자 값이 레지스트리 범위·형에 맞지 않습니다: {k}={v!r} — {why}")
        out[k] = vals
    return out


def _run(records, profile, calendar, as_of, cfg, unit_key):
    from lm27.time import analyze_time
    return analyze_time(unit_key, records, profile, calendar, as_of, cfg=cfg)


def _mono_ok(records, profile, calendar, as_of, cfg, unit_key, env_min: int) -> bool:
    """단조성 탐침: PC 가동(L0/L1 — pc.events) 기록을 빼면 봉투가 늘지 않아야 한다(W §3.12 ②)."""
    no_on = [r for r in records if not (r.get("kind") == "pc_session" and
                                        (r.get("src") == "pc.events" or r.get("layer") in ("L0", "L1")))]
    if len(no_on) == len(records):
        return True
    res = _run(no_on, profile, calendar, as_of, cfg, unit_key)
    return len(res.env.slots) * (SLOT // 60) <= env_min


def calibrate(records, truth, keys, grid, cfg, *, profile, calendar, as_of, unit_key, weights=WEIGHTS) -> dict:
    """W §8.3 격자 보정. records = 분석 입력(정답 행 제외), truth = 정답 `Man` 목록(`truth_mans`).
    반환 = 보고서 dict(`lm27.calibration/1`) — **설정을 바꾸지 않는다**(`applied` 는 늘 false)."""
    from lm27.time.attribute import ConservationError
    keys = check_keys(keys, cfg)
    grid = check_grid(grid or default_grid(keys, cfg), keys, cfg)
    base = cfg.derive({})
    res0 = _run(records, profile, calendar, as_of, base, unit_key)
    b = evaluate(res0, truth, base, weights)
    report = {"schema": SCHEMA, "keys": keys, "grid": {k: list(v) for k, v in grid.items()},
              "weights": list(weights), "samples": {"days": b["n_days"], "boundaries": b["n_bound"],
                                                    "attrib": b["n_attr"]},
              "baseline": {"values": {k: _json(cfg[k]) for k in keys}, **b}, "candidates": [],
              "sensitivity": {}, "recommended": {}, "gain": 0.0, "status": "ok", "applied": False}
    if b["n_days"] < MIN_TRUTH_DAYS:
        report["status"] = "insufficient"
        report["note"] = f"정답 날짜 {b['n_days']}일 — {MIN_TRUTH_DAYS}일 이상이어야 보정합니다(자료 부족)"
        return report
    best = None
    for combo in itertools.product(*(grid[k] for k in keys)):
        vals = dict(zip(keys, combo, strict=True))
        cand = cfg.derive(vals)
        row = {"values": {k: _json(v) for k, v in vals.items()}, "ok": True, "why": ""}
        try:
            res = _run(records, profile, calendar, as_of, cand, unit_key)
        except ConservationError:
            row.update(ok=False, why="보존 위반")
            report["candidates"].append(row)
            continue
        ev = evaluate(res, truth, cand, weights)
        row.update(ev)
        row["env_delta_min"] = ev["env_min"] - b["env_min"]
        if not _mono_ok(records, profile, calendar, as_of, cand, unit_key, ev["env_min"]):
            row.update(ok=False, why="단조성 위반(PC 가동 기록 제거 시 봉투 증가)")
        report["candidates"].append(row)
        if row["ok"] and (best is None or (row["J"], json.dumps(row["values"], sort_keys=True)) <
                          (best["J"], json.dumps(best["values"], sort_keys=True))):
            best = row
    for k in keys:                                  # 키별 민감도: 격자 순서대로 그 값의 최선 J(다른 키는 최선 조합)
        marg: dict = {}
        for row in report["candidates"]:
            if not row["ok"]:
                continue
            v = json.dumps(row["values"][k])
            if v not in marg or row["J"] < marg[v]:
                marg[v] = row["J"]
        report["sensitivity"][k] = [{"value": _json(x), "J": marg[json.dumps(_json(x))]} for x in grid[k]
                                    if json.dumps(_json(x)) in marg]
    if best is not None and b["J"] > 0:
        gain = (b["J"] - best["J"]) / b["J"]
        report["gain"] = round(gain, 6)
        if gain >= MIN_GAIN and best["values"] != report["baseline"]["values"]:
            report["recommended"] = best["values"]
        else:
            report["status"] = "no_gain"
            report["note"] = f"기본값 대비 개선 {gain * 100:.1f}% — {MIN_GAIN * 100:.0f}% 미만이라 바꾸지 않습니다"
    elif best is None:
        report["status"] = "no_candidate"
        report["note"] = "가드를 통과한 후보가 없습니다"
    else:
        report["status"] = "no_gain"
    return report


def _json(v):
    if isinstance(v, tuple):
        return list(v)
    return v


# ───────────────────────────── 명령줄 ─────────────────────────────
def _parse(argv):
    p = argparse.ArgumentParser(prog="calibrate.py", add_help=True, description="시간 파라미터 격자 보정(보고서만)")
    p.add_argument("--keys", required=True)
    p.add_argument("--grid", default=None)
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--as-of", dest="as_of", default=None)
    p.add_argument("--out", default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    try:
        a = _parse(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as e:
        return 0 if e.code == 0 else 1
    try:
        d0, d1 = date.fromisoformat(a.from_), date.fromisoformat(a.to)
        grid = json.loads(a.grid) if a.grid else None
        if grid is not None and not isinstance(grid, dict):
            raise ValueError("--grid 는 JSON 객체여야 합니다")
    except ValueError as e:
        sys.stderr.write(f"인자 오류: {e}\n{USAGE}\n")
        return 1
    for mod in ("lm27.normalize.load", "lm27.privacy.keys"):
        if importlib.util.find_spec(mod) is None:
            sys.stderr.write(f"보정에 필요한 모듈이 아직 없습니다({mod}) — 번들 적재·키링이 준비된 뒤 다시 실행하세요\n")
            return 1
    from lm27.config import load_config
    from lm27.normalize.load import load_evidence
    from lm27.paths import Paths
    from lm27.privacy.keys import load_keyring
    from lm27.time.calendar import load_calendar
    paths = Paths()
    cfg = load_config(paths)
    as_of = a.as_of or datetime.combine(d1, datetime.max.time()).replace(microsecond=0).isoformat()
    profile = {"d0": d0.isoformat(), "d1": d1.isoformat()}
    records = load_evidence(paths, cfg, d0.isoformat(), d1.isoformat())
    inputs, truth_rows = split_truth(records)
    kr = load_keyring(str(paths.data()), None)
    cal = load_calendar(paths)
    truth = truth_mans(inputs, truth_rows, profile, cfg, as_of)
    try:
        rep = calibrate(inputs, truth, a.keys.split(","), grid, cfg, profile=profile, calendar=cal, as_of=as_of,
                        unit_key=kr)
    except CalibrationError as e:
        sys.stderr.write(f"보정 인자 오류: {e}\n")
        return 1
    data = canon_bytes(rep)
    if a.out:
        atomic_write(a.out, data)
        sys.stderr.write(f"보정 보고서를 썼습니다(자동 적용 안 함): 상태 {rep['status']}\n")
    else:
        sys.stdout.write(data.decode("utf-8") + "\n")
    return 2 if rep["status"] == "insufficient" else 0


if __name__ == "__main__":
    for _st in (sys.stdout, sys.stderr):
        _rc = getattr(_st, "reconfigure", None)
        if _rc is not None:
            _rc(encoding="utf-8", errors="replace")
    sys.exit(main())
