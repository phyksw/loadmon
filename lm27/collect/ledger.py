# -*- coding: utf-8 -*-
r"""커버리지 원장 재생성(파생) — ``data\derived\coverage_ledger.jsonl`` · ``teams_coverage.jsonl``(계약 §3.11 · §6.4 ·
§8.1 · X-014 · X-131 · X-311, C §5 · CM §8 · CT §11 · B §8.1 · D-6).

원장은 파생물이다(지워도 다음 [수집]이 다시 만든다 — X-014). 입력 세 가지:
  1. 번들 세그먼트의 레코드(``lm27.bundle.loader.iter_records`` — 단일 로더) → 셀 건수 ``n``·``n_minute``·``n_date``·``n_unknown``.
  2. 수집 단계 결과(``data\derived\collect\<run_id>\stage_result_<stage>.json``)의 경로별 관측 ``srcs{경로 ID: 관측}`` —
     이번 실행이 어느 날짜 구간을 읽으려 했고(``ranges``) 수집기 rc·사유·지평선·상한·예산이 무엇이었나(``observation``).
  3. pc.json 능력 기록(``probe_sig`` — 셀이 어느 탐침 판단 아래 만들어졌나).

셀 = ``(account, date, kind_axis, src, pc_id)``(``account`` = 단일 사용자 상수 ``self``, ``kind_axis`` = mail_in·mail_out·cal·
teams·pc). 그 날 상태는 그 날을 덮은 관측마다 ``lm27.collect.rcmap.translate_cell`` 로 번역한 것 중 **최선 값**(같은 출처가
한 번이라도 읽어 0건을 확인했으면 zero_ok 는 남는다). 레코드가 있는 날은 관측이 막힘이라도 ok(자료가 있다). 아무 관측도
덮지 않은 날은 ``not_attempted`` — **미관측 4종(not_attempted·blocked·transport_fail·out_of_horizon)은 0h 가 아니다(T-09)**.
상한·예산에 걸린 관측은 ``partial`` + ``cap_hit``/``budget_hit``(T-10). COM 커서의 달 상태(``months`` — done·partial·
out_of_horizon)가 있으면 그 달은 그것을 따른다.

교차검증(X-311): 같은 PC·날·축에서 색인 건수 ÷ COM 건수 > ``ledger.mismatchRatio``(또는 COM 이 읽었는데 0건이고 색인은
있음)면 COM 셀에 경고 사유 ``R-COMGAP``(COM 누락 의심 — 하위 폴더·프로필 오접속).

일자 합성(``composite``) = 그 (날짜, 축)의 출처 중 최선 값(C §5.3). **예외**: ``*.copilot`` 출처의 ``zero_ok`` 는 다른 출처의
미관측을 '활동 없음'으로 바꾸지 못한다(X-131 · B Q23⑤) — 다른 출처가 아예 없으면 그 날은 미관측이다. 시간 코어의
``coverage``(W §2.4)는 ``day_axis_status`` 를 쓴다.

원문 0: 셀은 키·날짜·건수·상태·사유 코드뿐이다. 쓰기는 ``fsx.atomic_write`` 한 번(정렬된 정규 JSON 줄 — 결정적).
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from lm27.collect import rcmap
from lm27.collect import stage_result as sr
from lm27.util import fsx

__all__ = [
    "ACCOUNT", "AXES", "COPILOT_SRCS", "STATUS_ORDER", "axes_of", "composite", "day_axis_status", "ledger_window",
    "list_runs", "load_cells", "load_observations", "observation", "rebuild_coverage", "status_rank",
]

ACCOUNT = "self"
AXES = ("mail_in", "mail_out", "cal", "teams", "pc")
EVIDENCE_KINDS = ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute")
# 최선 순서(왼쪽이 좋다) — 시간 코어 lm27.time.evidence.COVERAGE_STATUS 와 같은 순서
STATUS_ORDER = ("ok", "zero_ok", "partial", "out_of_horizon", "blocked", "transport_fail", "not_attempted")
_RANK = {s: i for i, s in enumerate(STATUS_ORDER)}
COPILOT_SRCS = frozenset({"mail.copilot", "cal.copilot", "teams.copilot"})
COMGAP_PAIRS = {"mail.com": "mail.index", "cal.com": "cal.index"}      # COM 셀 ← 색인 셀
MONTH_STATES = ("done", "partial", "out_of_horizon")
MAX_SPAN_DAYS = 1825                                                  # collect.lookbackDays 의 최댓값과 같은 상한
_ANY_RUN = "20000101-000000-0000"                                     # 실행 폴더들의 부모를 Paths 로 얻는 자리표
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RX = re.compile(r"^\d{4}-\d{2}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_SRC_RX = re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)$")


def status_rank(status: str) -> int:
    """최선 순서의 자리(작을수록 좋다). 모르는 상태는 맨 뒤."""
    return _RANK.get(status, len(STATUS_ORDER))


def axes_of(src: str) -> tuple:
    """경로 ID → 그 출처가 만드는 축(메일은 수신·발신 둘)."""
    head = src.split(".", 1)[0]
    if head == "mail":
        return ("mail_in", "mail_out")
    if head in ("cal", "teams", "pc"):
        return (head,)
    return ()


def _axis_of_row(kind: str, row: dict) -> str | None:
    if kind == "mail":
        out = row.get("box") == "sent" or row.get("direction") == "out"
        return "mail_out" if out else "mail_in"
    if kind in ("cal", "teams"):
        return kind
    if kind.startswith("pc_"):
        return "pc"
    return None


# ── 관측(단계 결과의 경로별 추가 필드) ──────────────────────────────────────
def _d(v):
    return v if isinstance(v, str) and _DATE_RX.match(v) else None


def observation(rc, reasons=(), *, n=0, ranges=(), cap_hit=False, budget_hit=False, stop_kind=None,
                horizon_oldest=None, horizon_newest=None, months=None, probe_sig=None, skipped="") -> dict:
    """수집 단계 결과 ``srcs[경로 ID]`` 의 관측 하나(이 모듈이 형의 단일원 — run 이 만들고 원장이 읽는다).
    ``rc`` = 수집기 원 rc(파이프 실패·감시 종료를 반영한 값, 돌지 않음 = None), ``ranges`` = 이번에 읽으려 한 로컬 날짜 구간
    ``[[d0, d1], …]``(양 끝 포함), ``months`` = COM 커서의 달 상태 ``{"YYYY-MM": done|partial|out_of_horizon}``."""
    rgs = []
    for r in ranges or ():
        if isinstance(r, (list, tuple)) and len(r) == 2 and _d(r[0]) and _d(r[1]) and r[0] <= r[1]:
            rgs.append([r[0], r[1]])
    mo = {k: v for k, v in sorted((months or {}).items()) if isinstance(k, str) and _MONTH_RX.match(k)
          and v in MONTH_STATES} if isinstance(months, dict) else {}
    return {"rc": rc if isinstance(rc, int) and not isinstance(rc, bool) else None,
            "reasons": sorted(r for r in rcmap.norm_reasons(reasons) if rcmap.is_reason(r)),
            "n": n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0,
            "ranges": sorted(rgs), "cap_hit": bool(cap_hit), "budget_hit": bool(budget_hit),
            "stop_kind": stop_kind if stop_kind in sr.STOP_KINDS else None,
            "horizon_oldest": _d(horizon_oldest), "horizon_newest": _d(horizon_newest), "months": mo,
            "probe_sig": probe_sig if isinstance(probe_sig, str) and len(probe_sig) <= 64 else None,
            "skipped": skipped if isinstance(skipped, str) and len(skipped) <= 64 else ""}


def _runs_root(paths) -> str:
    """수집 실행 폴더들의 부모(``data\\derived\\collect``) — ``Paths.collect_runs()``(W2 통합). 그 메서드가 없는 시험용
    경로 객체만 ``collect_stage_results`` 의 부모(경로 조립 없이)."""
    fn = getattr(paths, "collect_runs", None)
    if callable(fn):
        return os.fspath(fn())
    return os.path.dirname(os.fspath(paths.collect_stage_results(_ANY_RUN)))


def list_runs(paths) -> list:
    """수집 실행 run_id 목록(오래된 순)."""
    try:
        names = os.listdir(fsx.longp(_runs_root(paths)))
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(n for n in names if _RUN_RX.match(n))


def load_observations(paths) -> list:
    """모든 수집 실행의 경로별 관측 ``[{run_id, pc_id, src, updated, …관측}]``(run_id·src 순)."""
    out = []
    for rid in list_runs(paths):
        for stage, res in sorted(sr.read_stage_results(paths, rid).items()):
            pc = res.get("pc_id")
            srcs = res.get("srcs")
            if not isinstance(pc, str) or not _PC_RX.match(pc) or not isinstance(srcs, dict):
                continue
            for src, o in sorted(srcs.items()):
                if not isinstance(src, str) or not _SRC_RX.match(src) or not isinstance(o, dict):
                    continue
                ob = observation(o.get("rc"), o.get("reasons"), n=o.get("n", 0), ranges=o.get("ranges"),
                                 cap_hit=o.get("cap_hit"), budget_hit=o.get("budget_hit"),
                                 stop_kind=o.get("stop_kind"), horizon_oldest=o.get("horizon_oldest"),
                                 horizon_newest=o.get("horizon_newest"), months=o.get("months"),
                                 probe_sig=o.get("probe_sig"), skipped=o.get("skipped", ""))
                ob.update(run_id=rid, pc_id=pc, src=src, stage=stage,
                          updated=res.get("updated") if isinstance(res.get("updated"), str) else "")
                out.append(ob)
    return out


# ── 창 ──────────────────────────────────────────────────────────────────────
def _today(cfg, now=None) -> date:
    u = now if isinstance(now, datetime) else datetime.now(UTC)
    if u.tzinfo is None:
        u = u.replace(tzinfo=UTC)
    return (u.astimezone(UTC) + timedelta(minutes=int(cfg["time.tzOffsetMin"]))).date()


def default_since(cfg, today: date) -> date:
    """수집 기본 시작일(단일원 — 원장 창·전경 수집 창이 같이 쓴다): 오늘 − ``collect.lookbackDays`` + 1 과
    (``collect.sinceYearStart`` 가 켜져 있으면 — 기본) 올해 1월 1일 중 이른 날. 사용자 지시: 기본 기간 '1월 1일 ~ 오늘'."""
    d0 = today - timedelta(days=int(cfg["collect.lookbackDays"]) - 1)
    try:
        year_start = bool(cfg["collect.sinceYearStart"])
    except KeyError:
        year_start = True
    if year_start:
        d0 = min(d0, date(today.year, 1, 1))
    return d0


def ledger_window(cfg, now=None, obs=()) -> tuple:
    """원장 날짜 창 ``(d0, d1)``(로컬 날짜 — 근무 시간대 ``time.tzOffsetMin``): ``default_since`` ~ 오늘,
    관측 구간이 더 이르면 거기까지(``MAX_SPAN_DAYS`` 안)."""
    d1 = _today(cfg, now)
    d0 = default_since(cfg, d1)
    floor = d1 - timedelta(days=MAX_SPAN_DAYS - 1)
    for o in obs or ():
        for a, _b in o.get("ranges") or ():
            da = date.fromisoformat(a)
            if da < d0:
                d0 = max(da, floor)
    return d0, d1


def _days(d0: date, d1: date):
    d = d0
    while d <= d1:
        yield d.isoformat()
        d += timedelta(days=1)


# ── 레코드 건수 ─────────────────────────────────────────────────────────────
def _local_day(ts: str, off: int) -> str | None:
    if not isinstance(ts, str) or not _UTC_RX.match(ts):
        return None
    t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=off)
    return t.date().isoformat()


def _count_records(paths, cfg, d0: date, d1: date, off: int, iter_records=None):
    """(pc, src, axis, date) → [n, n_minute, n_date, n_unknown] · 팀즈 (pc, src, chat, date) → [n, n_unknown]."""
    if iter_records is None:
        from lm27.bundle.loader import iter_records          # 단일 로더(L-08)
    cnt = defaultdict(lambda: [0, 0, 0, 0])
    chats = defaultdict(lambda: [0, 0])
    for kind in EVIDENCE_KINDS:
        for row in iter_records(paths, kind, d0, d1, cfg=cfg, overlay=False, off_min=off):
            day = _local_day(row.get("ts_utc"), off)
            ax = _axis_of_row(kind, row)
            pc, src = row.get("_pc"), row.get("src")
            if day is None or ax is None or not isinstance(pc, str) or not isinstance(src, str):
                continue
            c = cnt[(pc, src, ax, day)]
            c[0] += 1
            p = row.get("ts_precision")
            if p in ("exact", "minute"):
                c[1] += 1
            elif p in ("date", "summary"):
                c[2] += 1
            elif p == "unknown":
                c[3] += 1
            if kind == "teams" and isinstance(row.get("chat_key"), str):
                t = chats[(pc, src, row["chat_key"], day)]
                t[0] += 1
                if p == "unknown":
                    t[1] += 1
    return cnt, chats


# ── 셀 판정 ─────────────────────────────────────────────────────────────────
def _covers(o: dict, day: str) -> bool:
    return any(a <= day <= b for a, b in o.get("ranges") or ())


def _obs_day(o: dict, day: str, n: int) -> dict:
    """관측 하나가 그 날에 대해 말하는 셀 상태 ``{status, reasons, cap_hit, budget_hit}``."""
    ms = (o.get("months") or {}).get(day[:7])
    warn = [r for r in o.get("reasons") or () if rcmap.reason_class(r) == rcmap.WARNING]
    if ms == "done":
        return rcmap.translate_cell(0 if n else 4, warn, {"n": n})
    if ms == "partial":
        rs = list(o.get("reasons") or ())
        rs.append("R-BUDGET" if o.get("budget_hit") else "R-CAP")
        return {"status": "partial", "reasons": sorted(set(rs)), "cap_hit": not o.get("budget_hit"),
                "budget_hit": bool(o.get("budget_hit"))}
    if ms == "out_of_horizon" and not n:
        return {"status": "out_of_horizon", "reasons": sorted(set(warn) | {"R-HORIZON"}), "cap_hit": False,
                "budget_hit": False}
    return rcmap.translate_cell(o.get("rc"), o.get("reasons"), {
        "n": n, "date": day, "horizon_oldest": o.get("horizon_oldest"), "horizon_newest": o.get("horizon_newest"),
        "cap_hit": o.get("cap_hit"), "budget_hit": o.get("budget_hit"), "stop_kind": o.get("stop_kind")})


def _cell(pc, src, axis, day, counts, obs_list, sigs) -> dict:
    n, nm, nd, nu = counts.get((pc, src, axis, day), (0, 0, 0, 0))
    best, src_o = None, None
    for o in obs_list:
        if not _covers(o, day):
            continue
        c = _obs_day(o, day, n)
        if best is None or status_rank(c["status"]) < status_rank(best["status"]) or \
                (status_rank(c["status"]) == status_rank(best["status"]) and o["run_id"] >= src_o["run_id"]):
            best, src_o = c, o
    if best is None:
        best = {"status": "ok" if n else "not_attempted", "reasons": [], "cap_hit": False, "budget_hit": False}
    elif n and best["status"] in rcmap.UNOBSERVED:
        best = {"status": "ok", "reasons": [r for r in best["reasons"] if rcmap.reason_class(r) == rcmap.WARNING],
                "cap_hit": False, "budget_hit": False}
    o = src_o or {}
    return {"account": ACCOUNT, "date": day, "kind_axis": axis, "src": src, "pc_id": pc, "status": best["status"],
            "n": n, "n_minute": nm, "n_date": nd, "n_unknown": nu, "horizon_oldest": o.get("horizon_oldest"),
            "horizon_newest": o.get("horizon_newest"), "reasons": sorted(set(best["reasons"])),
            "budget_hit": bool(best["budget_hit"]), "cap_hit": bool(best["cap_hit"]),
            "probe_sig": o.get("probe_sig") or sigs.get((pc, src)), "run_id": o.get("run_id") or "",
            "observed_at": o.get("updated") or ""}


def _comgap(cells: list, ratio: float) -> int:
    """색인 ÷ COM > ratio(또는 COM 0건·색인 있음)인 COM 셀에 R-COMGAP(X-311). 붙인 셀 수."""
    idx = {(c["pc_id"], c["src"], c["kind_axis"], c["date"]): c for c in cells}
    hit = 0
    for c in cells:
        partner = COMGAP_PAIRS.get(c["src"])
        if partner is None:
            continue
        ic = idx.get((c["pc_id"], partner, c["kind_axis"], c["date"]))
        if ic is None or not ic["n"]:
            continue
        if (c["n"] and ic["n"] / c["n"] > ratio) or (not c["n"] and c["status"] == "zero_ok"):
            if "R-COMGAP" not in c["reasons"]:
                c["reasons"] = sorted(set(c["reasons"]) | {"R-COMGAP"})
                hit += 1
    return hit


def _sigs(paths) -> dict:
    """(pc_id, 능력 키) → 가장 최근 probe_sig(pc.json 이력)."""
    from lm27.bundle import pcreg
    out = {}
    for pc in pcreg.load_all_pcs(paths):
        for k, ent in (pc.get("capabilities") or {}).items():
            hist = ent.get("history") if isinstance(ent, dict) else None
            if isinstance(hist, list) and hist and isinstance(hist[-1], dict):
                s = hist[-1].get("probe_sig")
                if isinstance(s, str) and s:
                    out[(pc["pc_id"], k)] = s
    return out


def _jsonl(rows) -> bytes:
    return b"".join(fsx.canon_bytes(r) + b"\n" for r in rows)


def rebuild_coverage(paths, *, cfg=None, now=None, iter_records=None, obs=None) -> int:
    """계약 함수: 커버리지 원장·팀즈 하위 원장을 다시 만든다(파생, 원자 교체). 반환 = 공통 원장 셀 수.
    ``cfg`` 없으면 ``lm27.config.load_config(paths)``, ``now`` = 지금(UTC aware — 창 계산), ``iter_records``·``obs`` = 시험 주입."""
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths)
    off = int(cfg["time.tzOffsetMin"])
    obs = load_observations(paths) if obs is None else list(obs)
    d0, d1 = ledger_window(cfg, now, obs)
    counts, chats = _count_records(paths, cfg, d0, d1, off, iter_records)
    by_pair = defaultdict(list)
    for o in obs:
        by_pair[(o["pc_id"], o["src"])].append(o)
    pairs = set(by_pair) | {(pc, src) for pc, src, _ax, _d in counts}
    sigs = _sigs(paths)
    cells = []
    for pc, src in sorted(pairs):
        olist = sorted(by_pair.get((pc, src), ()), key=lambda o: o["run_id"])
        for axis in axes_of(src):
            for day in _days(d0, d1):
                cells.append(_cell(pc, src, axis, day, counts, olist, sigs))
    _comgap(cells, float(cfg["ledger.mismatchRatio"]))
    cells.sort(key=lambda c: (c["date"], c["kind_axis"], c["src"], c["pc_id"]))
    teams = [{"account": ACCOUNT, "date": day, "chat_key": chat, "src": src, "pc_id": pc, "status": "ok", "n": v[0],
              "n_unknown": v[1]} for (pc, src, chat, day), v in sorted(chats.items(), key=lambda kv: (kv[0][3],
                                                                                                     kv[0][2], kv[0][1],
                                                                                                     kv[0][0]))]
    fsx.atomic_write(paths.coverage_ledger(), _jsonl(cells))
    fsx.atomic_write(paths.teams_coverage(), _jsonl(teams))
    return len(cells)


# ── 읽기·합성 ───────────────────────────────────────────────────────────────
def load_cells(paths) -> list:
    """공통 원장 셀 목록(없거나 깨진 줄은 건너뛴다)."""
    try:
        raw = fsx.read_bytes(paths.coverage_ledger())
    except FileNotFoundError:
        return []
    out = []
    for ln in raw.splitlines():
        if not ln.strip():
            continue
        try:
            obj = fsx.loads_strict(ln)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("status") in _RANK and obj.get("kind_axis") in AXES:
            out.append(obj)
    return out


def composite(cells) -> dict:
    """일자 합성 ``{(date, axis): {status, reasons, srcs{src: status}}}`` — 출처 중 최선 값(C §5.3).
    ``*.copilot`` 의 zero_ok 는 다른 출처의 미관측을 덮지 못하고, 다른 출처가 없으면 그 날은 미관측이다(X-131)."""
    groups = defaultdict(list)
    for c in cells or ():
        groups[(c["date"], c["kind_axis"])].append(c)
    out = {}
    for key, grp in sorted(groups.items()):
        non = [c for c in grp if c["src"] not in COPILOT_SRCS]
        st = min((c["status"] for c in non), key=status_rank) if non else "not_attempted"
        for c in grp:
            if c["src"] in COPILOT_SRCS and c["status"] != "zero_ok" and status_rank(c["status"]) < status_rank(st):
                st = c["status"]
        srcs = {}
        for c in sorted(grp, key=lambda c: (c["src"], c["pc_id"])):
            cur = srcs.get(c["src"])
            if cur is None or status_rank(c["status"]) < status_rank(cur):
                srcs[c["src"]] = c["status"]
        rs = sorted({r for c in grp for r in c.get("reasons") or ()})
        out[key] = {"status": st, "reasons": rs, "srcs": srcs}
    return out


def day_axis_status(paths, cells=None) -> dict:
    """시간 코어 입력 ``coverage[(date, axis)] = 상태``(W §2.4) — 합성(코파일럿 예외 포함) 결과."""
    comp = composite(load_cells(paths) if cells is None else cells)
    return {k: v["status"] for k, v in comp.items()}
