# -*- coding: utf-8 -*-
r"""설정 화면 API(R §5.6 · §2.3.6 · 계약 §5) — 단일 설정 레지스트리로 검증한 뒤 개인 덮어쓰기 ``config\config.json`` 에 쓴다.

    GET  /api/settings                     설정 줄(레지스트리 메타 G-1: group·label_ko·help_ko·type·default·range·choices·
                                           uncalibrated·secret·scope·restart) + 실효 값 + config_warnings
    PUT  /api/settings      {key: value}   미등록 키·형 불일치는 저장하지 않고 사유(400 — detail[{key, error}])
    POST /api/settings/reset {key}         그 키를 덮어쓰기에서 지움(기본값으로)
    GET  /api/calibration · POST /api/calibration/apply {key, value}   보정 보고·승인(W §8.3 — 자동 적용 금지)

- 검증은 ``lm27.config.check_value``(레지스트리 단일원) 하나다 — 화면은 형·범위를 따로 두지 않는다.
- ``secret`` 키는 값을 내보내지 않는다(``set`` 여부만). 팀 서버 주소는 팀 화면(``api_team``)이 같은 ``save_settings`` 로 쓴다.
- 쓰기는 ``fsx.atomic_write``(정규 JSON) 뒤 서버 설정을 다시 읽는다(``UiApp.reload_cfg``).
"""
from __future__ import annotations

import threading

from lm27.ui.server import ApiError

__all__ = ["ROUTES", "group_of", "reset_settings", "save_settings"]

# 설정 묶음(R §5.6.1) — 키 접두 → 묶음 이름(앞에서부터 처음 맞는 것)
GROUPS = (("time.window.", "work"), ("time.tzOffsetMin", "work"), ("mm.", "mm"), ("time.", "time_adv"),
          ("episode.", "time_adv"), ("collect.", "collect"), ("probe.", "collect"), ("agent.", "collect"),
          ("bundle.", "collect"), ("move.", "collect"), ("mail.", "collect"), ("teams.", "collect"),
          ("pc.", "collect"), ("ledger.", "collect"), ("privacy.", "privacy"), ("bridge.", "copilot"),
          ("teamServer.", "team_server"), ("team.", "team"), ("teamReport.", "report"), ("report.", "report"),
          ("ui.", "ui"), ("hier.", "hier"))
_LOCK = threading.Lock()


def group_of(key: str) -> str:
    for pre, g in GROUPS:
        if key.startswith(pre) or key == pre:
            return g
    return "other"


def _plain(v):
    if isinstance(v, tuple):
        return [_plain(x) for x in v]
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return v


def _read_overrides(app) -> dict:
    from lm27.util import fsx
    obj = fsx.read_json(app.paths.config_json(), None, want=dict)
    return dict(obj) if isinstance(obj, dict) else {}


def _write_overrides(app, obj: dict) -> None:
    from lm27.util import fsx
    fsx.atomic_write(app.paths.config_json(), fsx.canon_bytes(obj))
    app.reload_cfg()


def save_settings(app, values: dict) -> dict:
    """검증(``check_value``) → config.json 덮어쓰기 병합 → 다시 읽기. 하나라도 틀리면 아무것도 쓰지 않고 400."""
    from lm27.config import UnknownKeyError, check_value
    reg = app.paths.settings_registry()
    errs = []
    for k, v in values.items():
        try:
            why = check_value(k, v, path=reg)
        except UnknownKeyError:
            why = "등록되지 않은 설정 키입니다"
        if why:
            errs.append({"key": k, "error": why})
    if errs:
        raise ApiError(400, "invalid", "설정 값을 저장하지 않았습니다 — 아래 이유를 확인해 주세요", errs)
    cfg = app.cfg()
    restart = sorted(k for k in values if getattr(cfg.meta(k), "restart", "none") not in ("none", "", None))
    with _LOCK:
        cur = _read_overrides(app)
        cur.update(values)
        _write_overrides(app, cur)
    return {"ok": True, "saved": sorted(values), "restart": restart}


def reset_settings(app, keys) -> dict:
    from lm27.config import UnknownKeyError
    cfg = app.cfg()
    for k in keys:
        try:
            cfg.meta(k)
        except UnknownKeyError:
            raise ApiError(400, "unknown_key", "등록되지 않은 설정 키입니다", [k]) from None
    with _LOCK:
        cur = _read_overrides(app)
        removed = [k for k in keys if k in cur]
        for k in removed:
            cur.pop(k, None)
        if removed:
            _write_overrides(app, cur)
    return {"ok": True, "reset": sorted(keys)}


def get_settings(app, req):
    cfg = app.cfg()
    snap = cfg.snapshot()                                        # 읽힘으로 세지 않는 실효 값(계약 §2.1)
    over = set(cfg.overridden())
    items = []
    for k in sorted(cfg.keys()):
        m = cfg.meta(k)
        it = {"key": k, "label_ko": m.label_ko, "help_ko": m.help_ko, "type": m.type, "default": _plain(m.default),
              "range": _plain(m.range), "choices": _plain(m.choices), "uncalibrated": bool(m.uncalibrated),
              "secret": bool(m.secret), "scope": m.scope, "restart": m.restart, "group": group_of(k),
              "overridden": k in over}
        if m.secret:
            it["value"], it["set"] = None, bool(snap.get(k))
        else:
            it["value"] = _plain(snap.get(k))
        items.append(it)
    return {"items": items, "config_warnings": cfg.config_warnings}


def put_settings(app, req):
    vals = dict(req.body)
    if not vals:
        raise ApiError(400, "empty", "바꿀 설정이 없습니다")
    return save_settings(app, vals)


def post_reset(app, req):
    k = req.body.get("key")
    keys = [k] if isinstance(k, str) else req.body.get("keys")
    if not isinstance(keys, list) or not keys or any(not isinstance(x, str) for x in keys):
        raise ApiError(400, "no_key", "되돌릴 설정을 고르세요")
    return reset_settings(app, keys)


# ── 보정(W §8.3) ──
def _calibration_report(app) -> dict | None:
    fn = getattr(app.paths, "calibration_report", None)         # 보정 보고서 위치(Paths — CR). 없으면 '아직 없음'
    if not callable(fn):
        return None
    from lm27.util import fsx
    obj = fsx.read_json(fn(), None, want=dict)
    return obj if isinstance(obj, dict) and obj.get("schema") == "lm27.calibration/1" else None


def get_calibration(app, req):
    rep = _calibration_report(app)
    if rep is None:
        return {"rows": [], "applied": {}, "note": "보정 보고서가 아직 없습니다 — tools\\calibrate.py 로 만들 수 있습니다"}
    rows = [r for r in rep.get("rows") or rep.get("candidates") or () if isinstance(r, dict)]
    return {"rows": rows[:200], "applied": {}, "built_at": rep.get("built_at")}


def post_calibration_apply(app, req):
    k = req.body.get("key")
    if not isinstance(k, str):
        raise ApiError(400, "no_key", "적용할 키를 고르세요")
    if "value" in req.body:
        v = req.body["value"]
    else:
        rep = _calibration_report(app) or {}
        row = next((r for r in rep.get("rows") or rep.get("candidates") or () if isinstance(r, dict)
                    and r.get("key") == k), None)
        if row is None or "candidate" not in row:
            raise ApiError(404, "no_candidate", "그 키의 보정 후보가 없습니다")
        v = row["candidate"]
    return save_settings(app, {k: v})


ROUTES = (("GET", r"/api/settings", get_settings),
          ("PUT", r"/api/settings", put_settings),
          ("POST", r"/api/settings/reset", post_reset),
          ("GET", r"/api/calibration", get_calibration),
          ("POST", r"/api/calibration/apply", post_calibration_apply))
