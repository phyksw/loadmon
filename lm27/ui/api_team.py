# -*- coding: utf-8 -*-
r"""팀 화면 API(R §5.5 · TAB §2.5 · §2.7~§2.9 · §3.2~§3.4 · §5.1 · §7.1) — 팀 서버 주소·대기열·미리보기·이 PC 팀 서버.

    GET  /api/team/status · /api/team/outbox · /api/team/preview/<item>
    POST /api/team/ping {host, port}         hello 판정 문구(TAB §2.9 — ok·other_lm·lm24·other_app·timeout·refused·dns)
    PUT  /api/team/settings {...}            검증 후 저장(R §5.5.1 — 포트 1~65535, 사설 IPv4·루프백만(allowPublicHost=false))
    POST /api/team/settings/reset-address    기본 주소로 **정확히** 되돌림(``lm27.team.client.DEFAULT_TEAM_URL`` — L-21 단일원)
    POST /api/team/token {token}             ``data\keys\secrets.json``(응답·화면에 값 없음 — RPT-43 ④)
    POST /api/team/build {from, to} · /api/team/registry/fetch → {job_id}
    POST /api/team/approve/<item> · /send/<item> · /drop/<item> · /export/<item> · /api/team/mask
    GET  /api/teamserver/local · POST /api/teamserver/start · /stop · /diagnose

- 대기열 동작은 TAB 명세 CLI 와 같은 함수(``lm27.team.queue``·``build``·``offline``·``client``)를 부른다.
- [보내기] = 승인(``queue.approve`` — 막힌 묶음·가림을 바꾼 뒤 다시 만들지 않은 묶음은 409) + 전송 작업 ``team send <item>``
  (lane net — 계약 O-14 ① 결정, cli 가 ``queue.send_item(item, cfg)`` 를 부른다, W2 통합).
- 첫 전송은 미리보기에서(TAB §2.8 · C17): 승인 전 묶음의 [보내기]·[승인만]은 미리보기가 그 바이트를 보여 준 기록
  (``queue.mark_previewed`` — 미리보기 GET 이 남긴다)이 있어야 한다. 없으면 409 ``preview_first``.
- 가림(TAB §2.5 · C16): ``POST /api/team/mask {unit_id, mode, item?}`` 는 가림을 저장하고(``build.set_mask`` — 덜 가려진 대기
  묶음의 승인을 푼다) 그 기간 묶음을 다시 만드는 작업 ``team build`` 를 띄운다(``job_id`` — 새 sha 가 옛 것을 대체).
  작업을 띄우지 못하면 ``job_id`` 없이 그 이유를 돌려준다(화면은 '다시 만들었다'고 말하지 않는다).
- 이 PC 팀 서버는 분리 프로세스(``team-server``)로 띄운다 — 화면이 꺼져도 서버는 산다. 끄기는 '내 서버'(pid·instance 대조)일 때만
  그 서버의 ``/api/shutdown``(루프백)으로 한다. 남의 프로세스는 끄지 않는다(TAB §3.4).
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from lm27.ui.server import HOST, ApiError

__all__ = ["ROUTES", "registry_view", "validate_address"]

_ITEM_RX = re.compile(r"^[A-Za-z0-9_\-]{1,120}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNIT_RX = re.compile(r"^u_[0-9a-f]{10}$")
_PERIOD_KEY_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$")
_REG_TTL_S = 30.0
ALT_MAX = 5
TS_START_WAIT_S = 3.0
_reg_lock = threading.Lock()
SETTINGS_KEYS = {"server_host": "team.serverHost", "server_port": "team.serverPort",
                 "server_alternates": "team.serverAlternates", "self_label": "team.selfLabel",
                 "member_id": "team.memberId", "unit_title_mode": "team.unitTitleMode",
                 "share_unknown_apps": "team.shareUnknownApps", "auto_send": "team.autoSend"}
STATE_KO = {"pending": "승인 대기", "sending": "보내는 중", "retry_wait": "다시 시도 대기", "sent": "보냄", "failed": "실패",
            "auth_needed": "인증 필요", "wrong_server": "다른 서버", "dropped": "치움", "exported": "내보냄",
            "delivered": "전달 확인", "superseded": "대체됨"}
SOURCE_KO = {"server": "팀 서버", "cache": "받아 둔 사본", "offline": "공유폴더 사본", "builtin": "레지스트리 없음"}


# ───────────────────────────── 레지스트리(분류 명세 적재기) ─────────────────────────────
def registry_view(app):
    """유효 레지스트리(``lm27.hier.registry.load_effective`` — 서버에 묻지 않고 캐시·사본·내장만, 30초 캐시) → (reg, status).
    팀 레지스트리 파일은 이 적재기로만 읽는다(L-22)."""
    with _reg_lock:
        ent = app.scratch.get("_registry")
        if ent and time.monotonic() - ent[0] < _REG_TTL_S:
            return ent[1], ent[2]
    try:
        from lm27.hier.registry import load_effective
        reg, st = load_effective(app.paths, app.cfg(), fetch=None, persist=False)
    except Exception:                                   # 레지스트리를 읽지 못함 — 화면은 '레지스트리 없음'
        reg, st = None, None
    with _reg_lock:
        app.scratch["_registry"] = (time.monotonic(), reg, st)
    return reg, st


def _registry_brief(app) -> dict:
    reg, st = registry_view(app)
    if st is None:
        return {"version": None, "source": "builtin", "source_ko": SOURCE_KO["builtin"]}
    out = {"version": getattr(st, "version", None), "fetched_at": getattr(st, "fetched_at", None),
           "source": getattr(st, "source", None), "source_ko": SOURCE_KO.get(getattr(st, "source", ""), ""),
           "stale": bool(getattr(st, "stale", False)), "text_ko": st.label_ko() if hasattr(st, "label_ko") else ""}
    if reg is not None:
        out["projects_n"] = sum(1 for p in reg.projects.values() if p.origin == "team")
        out["agents_n"] = len(reg.agents)
        cal = reg.calendar if isinstance(reg.calendar, dict) else {}
        out["calendar_version"] = cal.get("version")
    return out


# ───────────────────────────── 주소 검증(R §5.5.1 · TAB §7.1) ─────────────────────────────
def validate_address(host, port, allow_public: bool) -> list:
    """오류 목록[{field, error}](빈 목록 = 통과). IP 는 ip_address 통과 + allowPublicHost=false 면 사설 IPv4·루프백만."""
    from lm27.team.client import host_allowed
    errs = []
    h = str(host or "").strip()
    try:
        ipaddress.ip_address(h.strip("[]"))
        ok_ip = True
    except ValueError:
        ok_ip = False
    if not h:
        errs.append({"field": "server_host", "error": "팀 서버 IP 를 넣어 주세요"})
    elif not ok_ip and not allow_public:
        errs.append({"field": "server_host", "error": "IP 주소만 쓸 수 있습니다(호스트 이름 불가)"})
    elif not host_allowed(h, allow_public):
        errs.append({"field": "server_host", "error": "사설 IPv4(10·172.16~31·192.168)·루프백 주소만 쓸 수 있습니다"})
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        errs.append({"field": "server_port", "error": "포트는 1~65535 정수입니다"})
    return errs


def _settings_view(app) -> dict:
    from lm27.team.client import token_state
    cfg = app.cfg()
    return {"server_host": cfg["team.serverHost"], "server_port": cfg["team.serverPort"],
            "server_alternates": list(cfg["team.serverAlternates"] or ()), "self_label": cfg["team.selfLabel"],
            "member_id": cfg["team.memberId"] or None, "unit_title_mode": cfg["team.unitTitleMode"],
            "share_unknown_apps": bool(cfg["team.shareUnknownApps"]), "auto_send": bool(cfg["team.autoSend"]),
            "allow_public_host": bool(cfg["team.allowPublicHost"]), "token_set": token_state(app.paths) == "설정됨"}


def _outbox(app) -> list:
    from lm27.team import queue
    from lm27.ui.api_home import all_pcs
    rows = []
    try:
        items = queue.list_items(paths=app.paths)
    except Exception:                                   # 대기열 폴더가 없음 — 빈 목록
        items = []
    labels = {p.get("label_auto"): p.get("label_user") or p.get("label_auto") for p in all_pcs(app)}
    for it in items:
        m = it.meta or {}
        name = it.name[:-5] if it.name.endswith(".json") else it.name
        rows.append({"item": name, "period_key": it.period_key, "built_on_label": labels.get(m.get("built_on"),
                                                                                              m.get("built_on")),
                     "built_at": m.get("built_at"), "bytes": m.get("bytes"), "sha12": it.sha256[:12], "state": it.state,
                     "state_ko": STATE_KO.get(it.state, it.state), "approved": bool(m.get("approved")),
                     "next_at": m.get("next_at"), "last_error": m.get("last_error"),
                     "blockers": list(m.get("blockers") or ())})
    rows.sort(key=lambda r: (str(r.get("built_at") or ""), r["item"]), reverse=True)
    return rows


def _item(app, name: str):
    from lm27.team import queue
    if not _ITEM_RX.match(name or ""):
        raise ApiError(404, "no_item", "대기열에 그 항목이 없습니다")
    it = queue.find_item(app.paths, name + ".json") or queue.find_item(app.paths, name)
    if it is None:
        raise ApiError(404, "no_item", "대기열에 그 항목이 없습니다")
    return it


def _res(r) -> dict:
    rc = getattr(r, "rc", None) if not isinstance(r, dict) else r.get("rc")
    msg = getattr(r, "message", "") if not isinstance(r, dict) else r.get("message", "")
    return {"ok": rc in (0, 4, None), "rc": rc, "text_ko": msg}


# ───────────────────────────── 처리기 ─────────────────────────────
def get_status(app, req):
    return {"settings": _settings_view(app), "members": [], "registry": _registry_brief(app), "outbox": _outbox(app)}


def get_outbox(app, req):
    return {"items": _outbox(app)}


def post_ping(app, req):
    from lm27.team.client import base_of
    b = req.body
    host, port = b.get("host"), b.get("port")
    if isinstance(port, float) and port.is_integer():
        port = int(port)
    errs = validate_address(host, port, bool(app.cfg()["team.allowPublicHost"]))
    if errs:
        raise ApiError(400, "invalid", "주소를 확인해 주세요", errs)
    h = app.deps.team_hello(base_of(str(host).strip(), port), float(app.cfg()["team.connectTimeoutSec"]))
    info = getattr(h, "info", {}) or {}
    return {"ok": getattr(h, "result", "") == "ok", "result": getattr(h, "result", ""), "ms": getattr(h, "ms", 0),
            "text_ko": getattr(h, "text_ko", ""), "reason": getattr(h, "reason", None),
            "server": {k: info.get(k) for k in ("name", "version", "registry_version", "pepper_id") if k in info}}


def put_settings(app, req):
    from lm27.team.client import split_hostport
    from lm27.ui.api_settings import save_settings
    b = req.body
    unknown = [k for k in b if k not in SETTINGS_KEYS]
    if unknown:
        raise ApiError(400, "unknown_field", "모르는 항목입니다", unknown)
    cfg = app.cfg()
    allow = bool(cfg["team.allowPublicHost"])
    host = b.get("server_host", cfg["team.serverHost"])
    port = b.get("server_port", cfg["team.serverPort"])
    errs = validate_address(host, port, allow) if ("server_host" in b or "server_port" in b) else []
    alts = b.get("server_alternates")
    if alts is not None:
        if not isinstance(alts, list) or len(alts) > ALT_MAX:
            errs.append({"field": "server_alternates", "error": f"대체 주소는 최대 {ALT_MAX}개입니다"})
        else:
            for i, a in enumerate(alts, 1):
                h2, p2 = split_hostport(a)
                for e in validate_address(h2, p2, allow):
                    errs.append({"field": "server_alternates", "error": f"{i}번째 대체 주소: {e['error']}"})
    lab = b.get("self_label")
    if lab is not None:
        if not isinstance(lab, str) or len(lab.strip()) > 20:
            errs.append({"field": "self_label", "error": "표시 라벨은 20자 이하입니다"})
        else:
            why = _label_problem(app, lab.strip())
            if why:
                errs.append({"field": "self_label", "error": why})
    if errs:
        raise ApiError(400, "invalid", "팀 설정을 저장하지 않았습니다 — 아래 이유를 확인해 주세요", errs)
    vals = {}
    for f, key in SETTINGS_KEYS.items():
        if f not in b:
            continue
        v = b[f]
        if f == "server_host":
            v = str(v).strip()
        elif f == "self_label":
            v = v.strip()
        elif f == "member_id" and v is None:
            v = ""
        vals[key] = v
    if not vals:
        raise ApiError(400, "empty", "바꿀 항목이 없습니다")
    out = save_settings(app, vals)
    out["settings"] = _settings_view(app)
    return out


def _label_problem(app, label: str) -> str | None:
    """표시 라벨 검사(``check_team_label`` — 실패 사유 표시, 값은 싣지 않는다)."""
    if not label:
        return None
    try:
        from lm27.privacy import GateContext, SanitizeContext, check_team_label
        bad = check_team_label(label, GateContext(sctx=SanitizeContext(), canaries=()), 20)
    except Exception:                                   # 정제 문맥을 만들지 못함 — 저장은 막지 않고 묶음 빌드 때 다시 검사
        return None
    return "개인정보로 보이는 글자가 있어 쓸 수 없습니다 — 다른 라벨을 넣어 주세요" if bad else None


def post_reset_address(app, req):
    from lm27.team.client import DEFAULT_HOST, DEFAULT_PORT
    from lm27.ui.api_settings import reset_settings, save_settings
    reset_settings(app, ["team.serverHost", "team.serverPort"])
    cfg = app.cfg()
    if cfg["team.serverHost"] != DEFAULT_HOST or cfg["team.serverPort"] != DEFAULT_PORT:   # 레지스트리 기본값이 달라도 정확히
        save_settings(app, {"team.serverHost": DEFAULT_HOST, "team.serverPort": DEFAULT_PORT})
    return {"ok": True, "server_host": app.cfg()["team.serverHost"], "server_port": app.cfg()["team.serverPort"]}


def post_token(app, req):
    from lm27.team.client import set_upload_token, token_state
    tok = req.body.get("token")
    if tok is not None and (not isinstance(tok, str) or len(tok) > 256 or any(ord(c) < 32 for c in tok)):
        raise ApiError(400, "bad_token", "토큰 형식이 아닙니다")
    set_upload_token(app.paths, tok)
    return {"ok": True, "token_set": token_state(app.paths) == "설정됨"}


def post_build(app, req):
    f, t = req.body.get("from"), req.body.get("to")
    if not (isinstance(f, str) and _DATE_RX.match(f) and isinstance(t, str) and _DATE_RX.match(t)) or t < f:
        raise ApiError(400, "bad_range", "묶음 기간을 확인해 주세요")
    return app.start_job("team_build", ["team", "build", "--from", f, "--to", t])


def get_preview(app, req):
    from lm27.report.fmt import fmt_num
    from lm27.team import queue
    it = _item(app, req.groups[0])
    p = queue.preview(it)
    if p.get("rc") == 4:
        raise ApiError(404, "no_item", "대기열에 그 항목이 없습니다")
    if p.get("sha_ok") and p.get("sha256"):              # 사람이 이 바이트를 봤다(첫 [보내기]의 조건 — C17)
        try:
            queue.mark_previewed(it, p["sha256"])
        except Exception:                                # 잠금 대기 초과 등 — 미리보기는 보이고 [보내기]가 다시 묻는다
            pass
    s = p.get("summary") or {}
    guard = p.get("guard") or []
    return {"item": req.groups[0], "state": p.get("state"), "state_ko": STATE_KO.get(p.get("state"), p.get("state")),
            "summary": {"months": [{"m": m.get("month"), "mm_text": fmt_num(m.get("mm"), 2) if m.get("mm") is not None
                                    else None, "envelope_min": m.get("envelope_min")} for m in s.get("months") or ()],
                        "domains": s.get("domains") or {}, "units_n": s.get("units", 0), "peers_n": s.get("peers", 0),
                        "needs_n": s.get("needs", 0)},
            "units": p.get("units") or [], "needs": p.get("needs") or [], "matches": p.get("matches") or [],
            "subagents": p.get("subagents") or [],
            "forbidden": {"n": len(guard), "paths": [str(x)[:60] for x in guard]}, "sha12": p.get("sha12"),
            "bytes": p.get("bytes"), "sha_ok": p.get("sha_ok"), "blockers": p.get("blockers") or [],
            "warnings": p.get("warnings") or [], "can_send": bool(p.get("can_send")), "mask_note": p.get("mask_note"),
            "mask_gaps": p.get("mask_gaps") or [], "stale_mask": bool(p.get("stale_mask")),
            "approved": p.get("approved"), "message": p.get("message"), "json_text": p.get("json") or ""}


def _require_preview(it) -> None:
    """승인 전 묶음은 미리보기가 그 바이트를 보여 준 뒤에만 승인·전송한다(TAB §2.8 '미리보기에서 [보내기] = approved' — C17).
    명시 명령 CLI ``team send <item>`` 은 이 조건 밖이다(계약 O-14 ①)."""
    from lm27.team import queue
    if not queue.previewed(it):
        raise ApiError(409, "preview_first", "처음 보내는 묶음은 미리보기에서 내용을 확인한 뒤 [보내기]를 누르세요")


def post_approve(app, req):
    from lm27.team import queue
    it = _item(app, req.groups[0])
    _require_preview(it)
    r = queue.approve(it)
    if getattr(r, "rc", 0) == 2:
        raise ApiError(409, "blocked", getattr(r, "message", "") or "막힌 묶음은 승인할 수 없습니다")
    return _res(r)


def post_send(app, req):
    from lm27.team import queue
    it = _item(app, req.groups[0])
    _require_preview(it)
    r = queue.approve(it)
    if getattr(r, "rc", 0) == 2:
        raise ApiError(409, "blocked", getattr(r, "message", "") or "막힌 묶음은 보낼 수 없습니다")
    return app.start_job("team_send", ["team", "send", str(getattr(it, "name", "") or req.groups[0])])


def post_drop(app, req):
    from lm27.team import queue
    return _res(queue.mark(_item(app, req.groups[0]), "dropped", "사용자가 치웠습니다"))


def post_export(app, req):
    from lm27.team import offline
    it = _item(app, req.groups[0])
    d = req.body.get("dir") or offline.default_export_dir(app.cfg())
    if not isinstance(d, str) or not d.strip():
        raise ApiError(400, "no_dir", "내보낼 폴더를 넣어 주세요(설정 › 팀의 공유폴더)")
    if not os.path.isdir(d):
        raise ApiError(400, "no_dir", "그 폴더가 없습니다")
    try:
        out = offline.export_to_dir(it, d)
    except offline.UserError as e:
        raise ApiError(409, "export_refused", str(e)) from None
    except OSError:
        raise ApiError(409, "export_failed", "그 폴더에 쓰지 못했습니다") from None
    return {"ok": True, "file": os.path.basename(os.fspath(out)) if out else None,
            "text_ko": "파일로 내보냈습니다 — 팀 서버 PC 에서 반입하면 들어갑니다"}


def rebuild_after_mask(app, r: dict, item=None) -> dict:
    """가림·니즈 빼기를 바꾼 뒤(``set_mask``·``drop_need`` 결과 ``r``) 그 기간 묶음을 다시 만드는 작업을 띄운다(TAB §2.5 —
    다시 빌드 → 새 sha → 같은 기간 이전 미전송 묶음은 대체됨). 기간 = 미리보기 중이던 ``item`` 의 기간, 없으면 승인을 푼
    대기 묶음의 첫 기간. 반환 {job_id?, text_ko} — 작업을 띄우지 못하면 job_id 없이 그 이유(C16: 화면은 '다시 만들었다'고
    거짓으로 알리지 않는다)."""
    stale = list(r.get("stale") or ())
    pk = None
    if isinstance(item, str) and _ITEM_RX.match(item):
        try:
            pk = _item(app, item).period_key
        except ApiError:
            pk = None
    if not pk:
        pk = next(iter(r.get("periods") or ()), None)
    m = _PERIOD_KEY_RX.match(pk or "")
    held = f" 가리기 전에 만든 대기 묶음 {len(stale)}개는 보내지 않습니다." if stale else ""
    if not m:
        return {"text_ko": (r.get("message") or "가림을 바꿨습니다") + " — 바뀐 가림은 [팀 묶음 만들기]로 다시 만들 때 들어갑니다"}
    try:
        job = app.start_job("team_build", ["team", "build", "--from", m.group(1), "--to", m.group(2)])
    except ApiError as e:
        return {"text_ko": "가림을 저장했습니다." + held + " 묶음은 아직 다시 만들지 못했습니다: " + e.error}
    return {"job_id": job.get("job_id"), "text_ko": "가림을 바꿔 " + m.group(1) + " ~ " + m.group(2) +
            " 묶음을 다시 만듭니다 — 끝나면 미리보기를 다시 엽니다(이전 묶음은 대체됩니다)"}


def post_mask(app, req):
    from lm27.team.build import set_mask
    uid, mode, item = req.body.get("unit_id"), req.body.get("mode"), req.body.get("item")
    if not isinstance(uid, str) or not _UNIT_RX.match(uid) or mode not in ("title", "detail", "none"):
        raise ApiError(400, "bad_mask", "단위업무와 가림 방식을 고르세요")
    if item is not None and (not isinstance(item, str) or not _ITEM_RX.match(item)):
        raise ApiError(400, "bad_item", "대기열 항목 이름이 아닙니다")
    r = set_mask(app.paths, uid, mode)
    if r.get("rc") == 1:
        raise ApiError(400, "bad_mask", r.get("message") or "형식이 아닙니다")
    out = {"ok": True, "changed": r.get("rc") == 0, "stale_n": len(r.get("stale") or ()), "text_ko": r.get("message")}
    if r.get("rc") == 0:
        out.update(rebuild_after_mask(app, r, item))
    return out


def post_registry_fetch(app, req):
    return app.start_job("registry_fetch", ["team", "registry-fetch"])


# ───────────────────────────── 이 PC 팀 서버(R §5.5.3) ─────────────────────────────
def _store(app):
    from lm27.team.store import TeamStore
    cfg = app.cfg()
    d = cfg["teamServer.storeDir"] or os.fspath(app.paths.teamserver_default())
    return TeamStore(d, cfg)


def _ts_hello(port: int) -> dict | None:
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(urllib.request.Request(f"http://{HOST}:{int(port)}/api/hello"), timeout=1.5) as r:
            obj = json.loads(r.read(65536).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _mine(app) -> dict | None:
    """이 PC 에서 도는 '내 서버'(저장소 server.json 의 pid 가 살아 있고 instance_id 가 hello 와 같음 — TAB §3.3)."""
    from lm27.util.proc import pid_alive
    info = _store(app).server_info()
    if not isinstance(info, dict) or not isinstance(info.get("port"), int) or not isinstance(info.get("pid"), int):
        return None
    if not pid_alive(info["pid"]):
        return None
    h = _ts_hello(info["port"])
    if h is None or h.get("instance_id") != info.get("instance_id"):
        return None
    return {"port": info["port"], "bind_host": info.get("bind_host"), "started_at": info.get("started_at"),
            "name": h.get("name")}


def get_ts_local(app, req):
    from lm27.team.server import local_ipv4s
    cfg = app.cfg()
    mine = _mine(app)
    ips = sorted(local_ipv4s())
    out = {"running": mine is not None, "mine": mine is not None, "interfaces": ips,
           "bind_host": cfg["teamServer.bindHost"], "bind_port": cfg["teamServer.bindPort"],
           "store_dir": cfg["teamServer.storeDir"], "display_name": cfg["teamServer.displayName"]}
    if mine:
        out["urls"] = [f"http://{ip}:{mine['port']}" for ip in ips] or [f"http://{HOST}:{mine['port']}"]
        out["port"] = mine["port"]
    return out


def post_ts_start(app, req):
    b = req.body
    host = str(b.get("bind_host") or app.cfg()["teamServer.bindHost"]).strip()
    port = b.get("bind_port", app.cfg()["teamServer.bindPort"])
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise ApiError(400, "bad_host", "받는 주소는 IP 로 고르세요") from None
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise ApiError(400, "bad_port", "포트는 1024~65535 정수입니다")
    if _mine(app) is not None:
        return {"ok": True, "text_ko": "이미 이 PC 에서 팀 서버가 돌고 있습니다", "already": True}
    from lm27.ui.api_settings import save_settings
    vals = {"teamServer.bindHost": host, "teamServer.bindPort": port}          # 카드에서 고친 값은 설정으로 남긴다(R §5.5.3)
    sd, nm = b.get("store_dir"), b.get("display_name")
    if isinstance(sd, str):
        vals["teamServer.storeDir"] = sd.strip()
    if isinstance(nm, str):
        vals["teamServer.displayName"] = nm.strip()
    save_settings(app, vals)
    argv = app.jobs.base_argv() + ["team-server", "--host", host, "--port", str(port)]
    if isinstance(sd, str) and sd.strip():
        argv += ["--store", sd.strip()]
    ch = app.deps.spawn_detached(argv)
    t0 = time.monotonic()
    while time.monotonic() - t0 < TS_START_WAIT_S:
        if ch.poll() is not None:
            break
        time.sleep(0.1)
    rc = ch.poll()
    if rc is None:
        app.detached.append(ch)
        return {"ok": True, "text_ko": f"팀 서버를 시작했습니다(포트 {port})"}
    try:
        ch.close()
    except OSError:
        pass
    from lm27.util import fsx
    diag = fsx.read_json(_store(app).run_file("port_diag.json"), None, want=dict) or {}
    msg = str(diag.get("message") or "팀 서버를 시작하지 못했습니다 — 포트·저장소를 확인해 다시 누르면 이어서 합니다")
    raise ApiError(409, "start_failed", msg, [diag.get("kind")] if diag.get("kind") else [],
                   extra={"suggest": diag.get("suggest")})


def post_ts_stop(app, req):
    mine = _mine(app)
    if mine is None:
        raise ApiError(409, "not_mine", "이 PC 에서 띄운 팀 서버가 없습니다 — 남의 프로그램은 끄지 않습니다")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    rq = urllib.request.Request(f"http://{HOST}:{mine['port']}/api/shutdown", data=b"{}", method="POST",
                                headers={"Content-Type": "application/json"})
    try:
        with op.open(rq, timeout=5) as r:
            r.read(4096)
    except (urllib.error.URLError, OSError):
        raise ApiError(409, "stop_failed", "팀 서버가 응답하지 않습니다 — 잠시 뒤 다시 눌러 주세요") from None
    return {"ok": True}


def post_ts_diagnose(app, req):
    kind = req.body.get("kind") or "firewall"
    cfg = app.cfg()
    if kind == "port":
        port = req.body.get("port", cfg["teamServer.bindPort"])
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ApiError(400, "bad_port", "포트는 1~65535 정수입니다")
        d = app.deps.diagnose_port(port, 0, cfg)
        return {"ok": True, "kind": getattr(d, "kind", ""), "text_ko": getattr(d, "message", ""),
                "suggest": getattr(d, "suggest", 0)}
    if kind != "firewall":
        raise ApiError(400, "bad_kind", "진단 종류는 firewall·port 입니다")
    d = app.deps.firewall_diag(os.fspath(app.paths.python_exe()))
    return {"ok": True, "kind": "firewall", "text_ko": d.get("message_ko", ""), "suspect": d.get("suspect"),
            "level": d.get("level")}


ROUTES = (("GET", r"/api/team/status", get_status),
          ("GET", r"/api/team/outbox", get_outbox),
          ("POST", r"/api/team/ping", post_ping),
          ("PUT", r"/api/team/settings", put_settings),
          ("POST", r"/api/team/settings/reset-address", post_reset_address),
          ("POST", r"/api/team/token", post_token),
          ("POST", r"/api/team/build", post_build),
          ("GET", r"/api/team/preview/([^/]+)", get_preview),
          ("POST", r"/api/team/approve/([^/]+)", post_approve),
          ("POST", r"/api/team/send/([^/]+)", post_send),
          ("POST", r"/api/team/drop/([^/]+)", post_drop),
          ("POST", r"/api/team/export/([^/]+)", post_export),
          ("POST", r"/api/team/mask", post_mask),
          ("POST", r"/api/team/registry/fetch", post_registry_fetch),
          ("GET", r"/api/teamserver/local", get_ts_local),
          ("POST", r"/api/teamserver/start", post_ts_start),
          ("POST", r"/api/teamserver/stop", post_ts_stop),
          ("POST", r"/api/teamserver/diagnose", post_ts_diagnose))
