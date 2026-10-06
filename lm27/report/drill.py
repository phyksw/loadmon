# -*- coding: utf-8 -*-
r"""근거 드릴다운 조각(R §6.10 · 부록 A `day_drill`·`unit_drill`, 계약 §3.14 · §3.16) — 로컬 앱 API 와 자기완결 HTML 공용.

    월 → 날짜(날짜 원장 + 24시간 띠 CH-P16 + 구간 원장 표) → 구간 → 단위업무(업무 원장) → 증거 줄

- `day_view(inp, model, d, variant)`(R §6.10.2): `{d, hol, s_eff, leave, ledger{total_min, components, deductions,
  excluded, by_tag, conf_min, coverage, flags}, intervals[{a, b, tag, basis, targets[[대상, 분, O|I|X]], note, kind}], labels}`.
  `kind` = `env`(봉투 구간 — 시간 코어 구간 원장 행), 대상이 비면 `excluded`(WP-28 CH-P16 표지). 사적 차감·창 밖 제외 같은
  빼거나 버린 시간은 날짜 원장의 `deductions`·`excluded` 줄로 보인다(구간 원장에는 시각이 없다 — CR).
- `unit_view(inp, model, unit_id, variant)`(R §6.10.3): 경계 근거(차수·코드·시각·추정 여부) · 투입 내역(L1~L7·O/I) · 구간(runs)
  · 증거 줄(**전체판만** — 정제 열만 로컬 해석: 제목·시각·방향·상대 — `report.drill.maxEvidencePerUnit` 상한, 넘으면 '그 밖 n건')
  · 규칙 설명 문장(W §4.10.3 경계 코드 조합). 가림판은 증거 줄 없이 경계 코드·시각·투입 내역만.
- `drill_island(inp, model, variant, cfg)`: 자기완결 HTML 의 `lm27-drill` 섬 `{units, days, trimmed}`.
- `day_drill(run_id, d, variant)` · `unit_drill(run_id, unit_id, variant)`: 로컬 앱 API 진입(실행 하나의 입력·모델을 읽어 둔다 —
  같은 실행·같은 파일이면 다시 읽지 않는다).

원문은 애초에 없다(P). 표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from datetime import date

__all__ = ["DRILL_IDLE_S", "DrillSource", "day_drill", "day_view", "drill_island", "explain_text", "forget",
           "unit_drill", "unit_view"]

DRILL_IDLE_S = 600.0          # 드릴다운 캐시를 놓는 유휴 시간(초) — 코드 상수(C18)

EST_START = frozenset({"S2p", "S2m"})
EST_END = frozenset({"E2l", "E3c", "E3i", "NEXT_REQ"})
START_NAME = {"S1": "디지털 의뢰", "S1d": "날짜만 의뢰", "S1o": "내 지시", "S2a": "수락 발신", "S2M": "확인한 지시",
              "S2m": "의뢰자 회의 — 추정", "S2p": "첫 진행 − 30분 — 추정"}
END_NAME = {"E1": "보고 발신", "E1d": "날짜만 보고", "E1i": "받은 보고", "E2h": "완료 후보(강)", "E2l": "완료 후보(약)",
            "E3c": "검토 회의 — 추정", "E3i": "휴면 추정", "E3M": "확인한 보고", "NEXT_REQ": "다음 요청 직전 — 추정",
            "OPEN": "진행 중"}
S_PHRASE = {"S1": "의뢰 메시지로 시작해", "S1d": "날짜만 있는 의뢰로 시작해", "S1o": "내가 보낸 지시로 시작해",
            "S2a": "수락 회신으로 시작해", "S2M": "확인 질문에서 답한 지시 시각으로 시작해",
            "S2m": "의뢰자 회의를 시작으로 추정해", "S2p": "첫 작업 흔적의 30분 전을 시작으로 추정해"}
E_PHRASE = {"E1": "보고를 보낸 시각을 끝으로 봤습니다", "E1d": "날짜만 있는 보고를 끝으로 봤습니다",
            "E1i": "받은 보고를 끝으로 봤습니다", "E2h": "결과 파일 뒤 조용한 기간이 이어져 그 시각을 끝으로 봤습니다",
            "E2l": "약한 완료 근거를 끝으로 추정했습니다", "E3c": "검토 회의를 끝으로 추정했습니다",
            "E3i": "작업이 멈춘 뒤 마지막 진행을 끝으로 추정했습니다", "E3M": "확인 질문에서 답한 보고 시각을 끝으로 봤습니다",
            "NEXT_REQ": "다음 요청 직전을 끝으로 추정했습니다", "OPEN": "아직 진행 중입니다"}
KIND_OF_CH = {"mail": "mail", "teams": "teams"}
DAY_MIN = 1440


def _g(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def _sp(s) -> str | None:
    """모델 시각 'YYYY-MM-DDTHH:MM' → 드릴다운 표기 'YYYY-MM-DD HH:MM'(R §6.10.3)."""
    return None if s is None else str(s).replace("T", " ")


def _hhmm(lmin: int, d: date) -> str:
    from lm27.time.calendar import day0
    m = int(lmin) - day0(d) // 60
    m = max(0, min(DAY_MIN, m))
    return f"{m // 60:02d}:{m % 60:02d}"


def _window(inp, cfg) -> list[str] | None:
    used = (_g(inp.time.run_meta, "cfg_used", {}) or {}) if inp is not None else {}
    w = used.get("time.window.std") if isinstance(used, Mapping) else None
    if not w and cfg is not None:
        w = cfg["time.window.std"]
    parts = str(w or "").replace(" ", "").split("-")
    return parts if len(parts) == 2 else None


def _model_unit(model, uid: str):
    for u in model.get("units") or ():
        if u.get("unit_id") == uid:
            return u
    return None


def _titles(model) -> dict[str, str]:
    return {u["unit_id"]: u.get("title") or u["unit_id"] for u in model.get("units") or ()}


# ───────────────────────────── 날짜 ─────────────────────────────
def day_view(inp, model: Mapping, d: str, variant: str = "full", *, cfg=None, titles=None) -> dict | None:
    """R §6.10.2 날짜 원장 + 구간 원장. 그 날짜가 분석 기간에 없으면 None."""
    day = next((x for x in model.get("days") or () if x.get("d") == d), None)
    if day is None:
        return None
    dd = date.fromisoformat(d)
    led = next((r for r in (inp.time.day_ledger or ()) if r.get("date") == d), None) if inp is not None else None
    ledger = {"total_min": int(_g(led, "total_min", day["env_min"]) or 0),
              "components": [list(x) for x in (_g(led, "components", ()) or ())],
              "deductions": [list(x) for x in (_g(led, "deductions", ()) or ())],
              "excluded": [list(x) for x in (_g(led, "excluded", ()) or ())],
              "by_tag": dict(day.get("by_tag") or {}), "conf_min": dict(day.get("conf_min") or {}),
              "coverage": dict(_g(led, "coverage", {}) or {}), "flags": list(day.get("flags") or ())}
    ivs = []
    names = titles if titles is not None else _titles(model)
    labels = {}
    for r in (inp.time.interval_ledger or ()) if inp is not None else ():
        if r.get("date") != d:
            continue
        tg = [[str(t[0]), int(t[1]), str(t[2])] for t in (r.get("targets") or ()) if isinstance(t, list) and len(t) >= 3]
        ivs.append({"a": _hhmm(r.get("a", 0), dd), "b": _hhmm(r.get("b", 0), dd), "tag": r.get("tag"),
                    "basis": r.get("basis"), "targets": tg, "note": str(r.get("note") or ""),
                    "kind": "env" if tg else "excluded"})
        for t in tg:
            if t[0].startswith("u_") and t[0] in names:
                labels[t[0]] = names[t[0]]
    ivs.sort(key=lambda x: (x["a"], x["b"]))
    return {"d": d, "hol": bool(day.get("hol")), "s_eff": _window(inp, cfg), "leave": day.get("leave", 0),
            "ledger": ledger, "intervals": ivs, "labels": dict(sorted(labels.items())), "variant": variant}


# ───────────────────────────── 단위업무 ─────────────────────────────
def explain_text(sb: str | None, eb: str | None, grade: str) -> str:
    """경계 코드 조합의 규칙 설명(W §4.10.3)."""
    s = S_PHRASE.get(str(sb or ""), "첫 근거로 시작해")
    e = E_PHRASE.get(str(eb or "OPEN"), "마지막 근거를 끝으로 봤습니다")
    tail = " 추정 경계는 확인 질문으로 바로잡을 수 있습니다." if (sb in EST_START or eb in EST_END) else ""
    return f"{s} {e}(등급 {grade}).{tail}"


def _task(inp, uid: str):
    for t in (inp.time.tasks or ()) if inp is not None else ():
        if t.get("unit_id") == uid:
            return t
    return None


def _evidence_lines(inp, task, cycles, res, cap: int, fams=()) -> tuple[list[dict], dict[str, str], int]:
    """증거 줄(전체판): 경계 근거 → 대화 메시지 → 회의 → 문서 사건(시간 코어 문서 연결 ∪ 귀속 구간의 문서군). 반환 (줄,
    레코드 id → e번호, 더 있는 수)."""
    lines = _g(inp.evidence, "lines", {}) or {}
    order: list[tuple[str, str]] = []
    seen = set()

    def add(rid, role):
        if rid and rid in lines and rid not in seen:
            seen.add(rid)
            order.append((rid, role))
    for i, c in enumerate(cycles):
        add(str(c.get("s_ref") or ""), f"시작 근거({c.get('sb')} {START_NAME.get(str(c.get('sb')), '')}) · {i + 1}차")
        add(str(c.get("e_ref") or ""), f"종료 근거({c.get('eb')} {END_NAME.get(str(c.get('eb')), '')}) · {i + 1}차")
    conv = str(_g(task, "conv", "") or "")
    msgs = [m for m in (_g(inp.evidence, "msgs", ()) or ()) if conv and str(_g(m, "conv", "")) == conv]
    for m in sorted(msgs, key=lambda m: (int(_g(m, "t", 0) or 0), str(_g(m, "id", "")))):
        add(str(_g(m, "id", "")), "같은 대화")
    for f in _g(task, "flags", ()) or ():
        if str(f).startswith("회의연결 "):
            add(str(f).split(" ", 1)[1], "연결된 회의")
    fams = set((_g(task, "docs", {}) or {}).keys()) | set(fams)
    docs = [x for x in (_g(inp.evidence, "docs", ()) or ()) if str(_g(x, "fam", "")) in fams]
    for x in sorted(docs, key=lambda x: (int(_g(x, "t", 0) or 0), str(_g(x, "id", "")))):
        add(str(_g(x, "id", "")), "다룬 문서")
    out, ids = [], {}
    for i, (rid, role) in enumerate(order[:cap]):
        ln = lines[rid]
        eid = f"e{i + 1}"
        ids[rid] = eid
        row = {"id": eid, "kind": ln.get("kind"), "t": ln.get("t"), "role": role}
        if ln.get("kind") == "file":
            row.update({"op": ln.get("op"), "doc": res.doc(ln.get("fam")) if ln.get("fam") else ln.get("title")})
        else:
            row.update({"dir": ln.get("dir"), "prec": ln.get("prec"), "who": res.who(str(ln.get("who") or "")),
                        "title": ln.get("title")})
        out.append(row)
    return out, ids, max(0, len(order) - cap)


def unit_view(inp, model: Mapping, unit_id: str, variant: str = "full", *, cap: int = 200, res=None) -> dict | None:
    """R §6.10.3 업무 원장. 가림판은 증거 줄·근거 키 없이."""
    u = _model_unit(model, unit_id)
    if u is None:
        return None
    task = _task(inp, unit_id)
    raw_cycles = list(_g(task, "cycles", ()) or ())
    ev_ids: dict[str, str] = {}
    evidence: list[dict] = []
    more = 0
    if variant == "full" and inp is not None and inp.evidence is not None and res is not None:
        rdocs = (model.get("refs") or {}).get("docs") or {}
        fams = [str((rdocs.get(str(r)) or {}).get("key") or "") for r in u.get("docs") or ()]
        evidence, ev_ids, more = _evidence_lines(inp, task, raw_cycles, res, cap, [f for f in fams if f])
    cycles = []
    for i, c in enumerate(u.get("cycles") or ()):
        rc = raw_cycles[i] if i < len(raw_cycles) else {}
        st = {"code": c.get("sb"), "t": _sp(c.get("s")), "estimated": c.get("sb") in EST_START}
        eb = c.get("eb") if c.get("e") else "OPEN"
        en = {"code": eb, "t": _sp(c.get("e")), "estimated": eb in EST_END}
        if variant == "full":
            st["evidence"] = ev_ids.get(str(_g(rc, "s_ref", "") or ""))
            en["evidence"] = ev_ids.get(str(_g(rc, "e_ref", "") or ""))
        cycles.append({"no": i, "start": st, "end": en, "unstarted": bool(c.get("unstarted"))})
    uw = ((model.get("workflows") or {}).get("units") or {}).get(unit_id) or {}
    runs = []
    for r in uw.get("runs") or ():
        x = {k: r[k] for k in ("type", "class", "min", "obs_min", "n") if k in r}
        x["a"], x["b"] = _sp(r.get("a")), _sp(r.get("b"))
        x["apps"] = [list(a) for a in (r.get("apps") or ())]
        if variant == "full":
            x["docs"] = [list(dd) for dd in (r.get("docs") or ())]
        runs.append(x)
    first = (u.get("cycles") or [{}])[0]
    last = (u.get("cycles") or [{}])[-1]
    out = {"unit_id": unit_id, "title": u.get("title"), "title_by": u.get("title_by"), "grade": u.get("grade"),
           "status": u.get("status"), "cycles": cycles,
           "levels_min": {k: int((u.get("levels_min") or {}).get(k, 0)) for k in ("L1", "L2", "L3", "L4", "L5", "L6", "L7")},
           "obs_min": u.get("obs_min"), "est_min": u.get("est_min"), "effort_min": u.get("effort_min"), "runs": runs,
           "waits": [{**dict(w), "a": _sp(w.get("a")), "b": _sp(w.get("b"))} for w in uw.get("waits") or ()],
           "explained_ratio": uw.get("explained_ratio"),
           "explain": explain_text(first.get("sb"), last.get("eb") if last.get("e") else "OPEN", str(u.get("grade") or "")),
           "variant": variant}
    if variant == "full":
        out["evidence"] = evidence
        out["evidence_more"] = more
    return out


def drill_island(inp, model: Mapping, variant: str, cfg=None, *, res=None) -> dict:
    """자기완결 HTML 의 `lm27-drill` 섬(R §9.4): {units{unit_id: unit_view}, days{날짜: day_view}, trimmed[]}.
    날짜는 구간 원장이 있는 날만(빈 날은 화면이 모델 days 로 그린다)."""
    cap = int(cfg["report.drill.maxEvidencePerUnit"]) if cfg is not None else 200
    titles = _titles(model)
    days = {}
    iv_days = sorted({str(r.get("date")) for r in (inp.time.interval_ledger or ())}) if inp is not None else []
    for d in iv_days:
        v = day_view(inp, model, d, variant, cfg=cfg, titles=titles)
        if v is not None:
            days[d] = v
    units = {}
    for u in model.get("units") or ():
        v = unit_view(inp, model, u["unit_id"], variant, cap=cap, res=res)
        if v is not None:
            units[u["unit_id"]] = v
    return {"units": units, "days": days, "trimmed": []}


# ───────────────────────────── 로컬 앱 API 진입 ─────────────────────────────
class DrillSource:
    """실행 하나의 드릴다운 재료(입력 + 모델 두 변형). 같은 실행·같은 파일 서명이면 다시 읽지 않는다.

    캐시 수명(W2 검토 C18 — '작업 완료 후 메모리를 계속 잡지 않도록'): 한 번에 실행 하나만 두고, ``idle_s``(기본
    ``DRILL_IDLE_S``) 동안 아무도 쓰지 않으면 데몬 타이머가 놓는다. ``forget()`` 은 바로 놓는다(화면의 모델 캐시 비우기·
    분석/보고서 작업 끝에 부른다). 적재는 한 번에 하나(``_load_lock``) — 같은 실행을 동시에 두 번 읽지 않는다."""
    _cache: dict = {}                     # (root, run_id) → (서명, DrillSource, 마지막 사용 monotonic 초)
    _lock = threading.Lock()
    _load_lock = threading.Lock()
    _timer: threading.Timer | None = None
    idle_s: float = DRILL_IDLE_S

    def __init__(self, inp, model: dict, cfg, res_full, redacted: dict | None = None):
        self.inp = inp
        self.model = model
        self.cfg = cfg
        self.res = res_full
        self._red = redacted

    @classmethod
    def forget(cls) -> None:
        """캐시를 바로 비운다(붙잡던 보고서 입력을 놓는다)."""
        with cls._lock:
            cls._cache.clear()
            if cls._timer is not None:
                cls._timer.cancel()
                cls._timer = None

    @classmethod
    def cached(cls) -> int:
        """지금 붙잡은 실행 수(시험·진단용)."""
        with cls._lock:
            return len(cls._cache)

    @classmethod
    def _arm(cls, delay: float) -> None:
        """만료 타이머(잠금 안에서 부른다). 이미 있으면 그대로 — 만료 때 남은 시간으로 다시 건다."""
        if cls._timer is None:
            t = threading.Timer(max(0.05, float(delay)), cls._expire)
            t.daemon = True
            t.name = "lm27-drill-expire"
            cls._timer = t
            t.start()

    @classmethod
    def _expire(cls) -> None:
        with cls._lock:
            cls._timer = None
            now = time.monotonic()
            for k in [k for k, v in cls._cache.items() if now - v[2] >= cls.idle_s]:
                del cls._cache[k]
            if cls._cache:
                cls._arm(min(cls.idle_s - (now - v[2]) for v in cls._cache.values()))

    @classmethod
    def _hit(cls, key, sig):
        """잠금 안에서: 서명이 같으면 그 재료(사용 시각 갱신), 아니면 None."""
        hit = cls._cache.get(key)
        if hit is None or sig is None or hit[0] != sig:
            return None
        if time.monotonic() - hit[2] >= cls.idle_s:        # 타이머보다 먼저 온 호출 — 만료로 본다
            del cls._cache[key]
            return None
        cls._cache[key] = (hit[0], hit[1], time.monotonic())
        return hit[1]

    @classmethod
    def load(cls, run_id: str, *, paths=None, cfg=None, evidence=True) -> DrillSource:
        from lm27.report import load_model
        from lm27.report.inputs import load_inputs, report_file
        from lm27.report.resolve import Resolver
        if paths is None:
            from lm27.paths import Paths
            paths = Paths()
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        mp = report_file(paths, run_id, "report_model.json")
        try:
            st = os.stat(mp)
            sig = (str(paths.root), run_id, st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        key = (str(paths.root), run_id)
        with cls._lock:
            src = cls._hit(key, sig)
        if src is not None:
            return src
        with cls._load_lock:                                # 동시에 온 첫 [근거] 두 번이 입력을 두 번 읽지 않게
            with cls._lock:
                src = cls._hit(key, sig)
            if src is not None:
                return src
            model = load_model(run_id, paths=paths)
            inp = load_inputs(run_id, paths=paths, cfg=cfg, evidence=evidence, bundle_state=False)
            refs = model.get("refs") or {}
            people = {v["key"]: int(k) for k, v in (refs.get("people") or {}).items() if v.get("key")}
            docs = {v["key"]: int(k) for k, v in (refs.get("docs") or {}).items() if v.get("key")}
            res = Resolver("full", inp.person_dir, inp.registry, inp.evidence, people_ref=people, doc_ref=docs,
                           proposals=(inp.hier or {}).get("proposals"))
            src = cls(inp, model, cfg, res)
            if sig is not None:
                with cls._lock:
                    cls._cache.clear()                      # 한 번에 실행 하나
                    cls._cache[key] = (sig, src, time.monotonic())
                    cls._arm(cls.idle_s)
        return src

    def variant_model(self, variant: str) -> dict:
        if variant == "full":
            return self.model
        if self._red is None:
            from lm27.report.model import redact_model
            self._red = redact_model(self.model, self.inp.registry, person_dir=self.inp.person_dir,
                                     title_mode=str(self.cfg["team.unitTitleMode"]))
        return self._red

    def day(self, d: str, variant: str = "full") -> dict | None:
        return day_view(self.inp, self.variant_model(variant), d, variant, cfg=self.cfg)

    def unit(self, unit_id: str, variant: str = "full") -> dict | None:
        cap = int(self.cfg["report.drill.maxEvidencePerUnit"])
        return unit_view(self.inp, self.variant_model(variant), unit_id, variant, cap=cap, res=self.res)


def forget() -> None:
    """드릴다운 캐시를 바로 비운다 — 화면의 모델 캐시 비우기(`lm27.ui.api_report.forget_models`)·분석/보고서 작업 끝에 부른다."""
    DrillSource.forget()


def _variant(v: str) -> str:
    if v not in ("full", "redacted"):
        raise ValueError("드릴다운 변형은 full · redacted 중 하나입니다")
    return v


def day_drill(run_id: str, d, variant: str = "full", *, paths=None, cfg=None) -> dict | None:
    """R 부록 A `day_drill(run_id, d, variant)` — `GET /api/report/day/<d>?run=<id>`."""
    ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
    return DrillSource.load(run_id, paths=paths, cfg=cfg).day(ds, _variant(variant))


def unit_drill(run_id: str, unit_id: str, variant: str = "full", *, paths=None, cfg=None) -> dict | None:
    """R 부록 A `unit_drill(run_id, unit_id, variant)` — `GET /api/report/unit/<unit_id>?run=<id>`."""
    return DrillSource.load(run_id, paths=paths, cfg=cfg).unit(str(unit_id), _variant(variant))
