# -*- coding: utf-8 -*-
r"""시간 코어(W 부록 A · 계약 §2.9) — 근무 봉투 · 단위업무 · 귀속 · MM · 확인 큐 · 설명 원장.

`analyze_time(person_key, records, profile, calendar_path, as_of, overrides=None, tags=None) -> TimeResult`

정규화(`evidence.normalize`) → 날짜 정보(`calendar.build_days` — 달력에 없는 해는 거부) → 봉투(`envelope`) →
단위업무(`episodes.build_tasks`) → 귀속(`attribute` — 날마다 Σ귀속 초 = 300 × 봉투 슬롯, 어기면 중단) → 정수 분 표·
월 MM(`mm`) → 확인 큐(`queue`) → 결과(`ledger.TimeResult` — 계약 §3.14 `timecore/1.1` 파일 9종).

- `person_key` = unit_id 키(W §4.11): 목적 'unit' 하위 키 bytes(`subkey(주 키, "unit")`), 키링 객체, 또는 호출 가능
  `fn(시작 근거 키, 종류) -> unit_id`. 번들 소유자 ID(`p_…`) 같은 공개 문자열은 받지 않는다(TypeError).
- `calendar_path` = calendar.json 경로 또는 이미 만든 `Calendar`(`load_calendar(paths, registry)` 결과 — 팀 레지스트리
  달력 우선, CR-15).
- `overrides` = 설정 덮어쓰기 dict 또는 `Cfg`. 키워드 `cfg=` 로 실행 설정을 넘기면 그 위에 덮어쓰기를 얹는다. 읽힌
  키는 별도 사본(`Cfg.derive`)에 기록되어 `run_meta.cfg_used` 가 시간 코어 키만 담는다.
- `tags` = HierTags `{msg: {msg_key: proj}, fam: {fam_key: proj}, shared_fams}`(계약 §3.15) 또는 None.
- 키워드 `labels` = 롤업 라벨 `{unit_id: {domain, project, role, wtype, ax_link}}`(분류 뒤, 없으면 'UNC').
- `as_of` = 분석 기준 시각(시계 주입 — 계약 §9.1): 로컬 초 int · aware/naive datetime · date · ISO 문자열.

`write_time_files(paths, run_id, result)` 는 결과 파일을 `fsx.atomic_write` 로 쓴다(경로는 `Paths.analysis_time_file`
— 계약 L-08: `paths.py` 메서드로만, CR).

이 `__init__` 은 하위 모듈을 최상위에서 import 하지 않는다(여러 작업 패키지가 나눠 가진 패키지 — 계약 §2 머리 ·
CR-09). `lm27.time.calendar` 만 쓰는 쪽이 시간 코어 전체를 싣지 않게 한다.
"""
from __future__ import annotations

__all__ = ["CORE_VERSION", "TimeResult", "analyze_time", "write_time_files"]

CORE_VERSION = "timecore/1.1"


def __getattr__(name: str):
    if name == "TimeResult":
        from lm27.time.ledger import TimeResult      # 지연 import(CR-09)
        return TimeResult
    raise AttributeError(f"module 'lm27.time' has no attribute {name!r}")


def _as_cfg(overrides, cfg):
    """실행 설정 → 시간 코어 전용 사본(읽힘 기록이 비어 있는 Cfg)."""
    from lm27.config import load_config
    base = cfg
    if overrides is not None and hasattr(overrides, "derive") and hasattr(overrides, "used"):
        if base is not None:
            raise TypeError("cfg= 와 Cfg 형 overrides 를 함께 줄 수 없다 — 덮어쓰기는 dict 로")
        base, overrides = overrides, None
    if base is None:
        base = load_config()
    return base.derive(dict(overrides or {}))


def _as_calendar(calendar_path):
    from lm27.time.calendar import Calendar
    if hasattr(calendar_path, "wd_between") and hasattr(calendar_path, "is_holiday"):
        return calendar_path
    return Calendar(calendar_path)


def _clip_period(env, days) -> int:
    """분석 기간 밖 날짜의 봉투 슬롯을 결과에서 뺀다(봉투는 자정 연속성을 위해 앞뒤 하루까지 계산하지만, 결과·정수 분
    표·월 MM 은 기간 안 날짜만 — 팀 묶음 envelope_daily 는 '기간 안' 행만 받는다, TAB §2.3.2). 반환 = 뺀 슬롯 수."""
    from lm27.time.calendar import SLOT, d_of
    out = [s for s in env.slots if not (days.get(d_of(s * SLOT)) or {}).get("in_range")]
    for s in out:
        env.slots.discard(s)
        env.basis.pop(s, None)
        env.tags.pop(s, None)
        env.pcs.pop(s, None)
        env.on_leave.discard(s)
    if out:
        keep = set(env.slots)
        env.manual_slots = {k: [s for s in v if s in keep] for k, v in env.manual_slots.items()}
    return len(out)


def analyze_time(person_key, records, profile, calendar_path, as_of, overrides=None, tags=None, *,
                 cfg=None, labels=None):
    """시간 코어 한 번(W 부록 A). 반환 `TimeResult`. 보존 위반은 `attribute.ConservationError`(분석 중단),
    달력에 없는 해는 `calendar.UnknownYearError`(분석 거부) — 둘 다 결과를 만들지 않는다(fail-closed)."""
    from lm27.time.attribute import attribute_full
    from lm27.time.calendar import build_days
    from lm27.time.envelope import build_envelope
    from lm27.time.episodes import build_tasks
    from lm27.time.evidence import normalize
    from lm27.time.ledger import TimeResult, input_digest, parallel_of, pre_request
    from lm27.time.mm import month_mm, rollup, team_tables
    from lm27.time.queue import make_queue, prioritize

    c = _as_cfg(overrides, cfg)
    cal = _as_calendar(calendar_path)
    recs = list(records)
    digest = input_digest(recs)
    ev, _audit = normalize(recs, profile, c, as_of, tags)
    days = build_days(ev, c, cal)
    env = build_envelope(ev, c, days)
    clipped = _clip_period(env, days)
    tasks, q_tasks = build_tasks(ev, env, days, c, cal, unit_key=person_key)
    att = attribute_full(ev, env, tasks, days, c)
    pre_request(att, tasks)
    par = parallel_of(att, env.slots)
    tables = team_tables(env.slots, att.assign, days, c, tags=env.tags)
    months = month_mm(env, att.assign, days, c, cal, ev.as_of, tables=tables, tasks=tasks, ev=ev)
    for m in months.values():
        m["rollup"] = rollup(m, labels)
    effort = att.effort()
    q = list(q_tasks) + make_queue(ev, c, env, tasks, days, effort, att.assign, att, cal=cal, parallel=par)
    shown = prioritize(q, c)
    warnings = list(ev.warnings) + [str(w.get("text_ko", "")) for w in getattr(c, "config_warnings", ())]
    warnings += list(getattr(cal, "warnings", ()) or ())
    if clipped:
        warnings.append(f"분석 기간 밖 봉투 슬롯 {clipped}개는 결과에서 뺐다(앞뒤 날짜 — 기간 밖 근거)")
    used = c.used()
    return TimeResult(ev=ev, days=days, env=env, tasks=tasks, attribution=att, tables=tables, months=months,
                      queue=shown, cfg_used=used, cfg_hash=c.hash(used.keys()),
                      calendar_version=str(getattr(cal, "version", "")), as_of=ev.as_of,
                      tz_offset_min=int(ev.tz_offset_min), input_digest=digest, warnings=warnings, parallel=par,
                      labels=labels)


def write_time_files(paths, run_id: str, result) -> list[str]:
    """결과 파일 9종을 원자 쓰기(`fsx.atomic_write`). 경로는 `paths.analysis_time_file(run_id, name)` 하나로만
    만든다(계약 L-08 — W1 통합 창에서 `lm27.paths` 에 생김). 반환 = 쓴 파일 경로 목록(이름순)."""
    from lm27.util.fsx import atomic_write
    out = []
    for name, data in sorted(result.files().items()):
        p = paths.analysis_time_file(run_id, name)
        atomic_write(p, data)
        out.append(str(p))
    return out
