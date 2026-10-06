# -*- coding: utf-8 -*-
r"""입출력 한도 보정 프로브(B §7.14) — 실측 한도 × ``bridge.calibSafety`` 를 패킹 예산으로.

    entry = run_calibration(rt, model_class="fast", force=False)   # 전송 4~6회(약 3~6분), 실패해도 기본값으로 진행
    calib = current(profile_doc, profile_id, model, edge_major, cfg, clock)   # 유효 기간 안의 최신(없으면 None)

입력 한도는 **전송 없이 주입만으로** 잰다(L1 ``inject``·``clear_editor`` — CDP 전송만 지원). 넘친 주입은 편집기가 받아들인
글자 수(``got``)가 곧 한도라 그 값을 확인 주입으로 검증하고, 아니면 2분 탐색(250자 간격·최대 10회). 서버 쪽 잘림은
채움 글 끝 줄의 확인 코드를 돌려받아 확인한다(다르면 한도 × 0.9, 최대 2회). 출력 한도는 항목 60·100·140개를 청해
잘림 지점을 직접 관찰한다(잘린 길이가 곧 한도, 다 성공하면 마지막 성공 길이 = 하한 추정).

저장: ``bridge_profile.calibration`` 항목 ``{profile_id, model, edge_major, date, input_limit, output_limit, pack_in, pack_out,
server_trunc, sends}`` — 키는 ``(profile_id, model, edge_major)``(계정·테넌트를 식별하는 정보는 쓰지 않는다. 프로필을 새로
만들면 자동으로 다시 보정). 채움 글·확인 코드에는 업무 내용·개인정보가 없다(그래도 프롬프트 게이트를 통과시킨다).
"""
from __future__ import annotations

import secrets
import sys
import types
from datetime import date, timedelta

from lm27.bridge import budget as BG
from lm27.bridge import jsonx
from lm27.bridge.clock import Deadline, today
from lm27.bridge.transport import SendRequest

INPUT_LO = 2000                   # 입력 한도 탐색 범위(B §7.14)
INPUT_HI = 40000
SEARCH_STEP = 250
SEARCH_ITERS = 10
SERVER_TRUNC_SHRINK = 0.9
SERVER_TRUNC_TRIES = 2
OUTPUT_KS = (60, 100, 140)        # 항목당 약 90자
KEEP_ENTRIES = 20
CODE_ALPHA = "ABCDEFGHJKMNPQSTVWXYZ"
CODE_LEN = 6
FILLER_UNIT = "검증용문장가나다라마바사아자차카타파하abcdefghijklmnopqrstuvwxyz"   # 공백 없음 — 정규화 길이 = 글자 수
CALIB_STAGE = "calibrate"

INPUT_CHECK_PROMPT = ("[LM27 요청 {rid} · 입력 한도 확인 · 항목 1개]\n"
                      "아래 채움 글의 맨 마지막 줄에 있는 확인 코드를 그대로 돌려주세요. 채움 글의 내용은 의미가 없습니다.\n"
                      "- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다.\n"
                      '- 형식(<…> 자리에 실제 값): {{"rid": <요청번호>, "n": 1, "items": [ {{"id": 1, "code": <확인 코드>}} ]}}\n'
                      "- 코드 블록이 끝나면 맨 마지막 줄에 [[END {rid}]] 만 씁니다.\n"
                      "[채움 글]\n")
INPUT_CODE_TEMPLATE = "\n확인 코드 {code}"
OUTPUT_CHECK_PROMPT = ("[LM27 요청 {rid} · 답 한도 확인 · 항목 {k}개]\n"
                       "1부터 {k} 까지 번호마다 하나씩, t 에는 그 번호를 한글로 읽은 말과 80자 안팎의 아무 문장을 씁니다.\n"
                       "- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다. 코드 블록 밖에는 설명을 쓰지 않습니다.\n"
                       "- 문자열 값은 큰따옴표로 감싸고 값 안에서 줄을 바꾸지 않습니다.\n"
                       '- 형식(<…> 자리에 실제 값): {{"rid": <요청번호>, "n": <항목 수>, "items": [ {{"id": <번호>, '
                       '"t": <번호를 한글로 읽은 말과 문장>}} ]}}\n'
                       "- 코드 블록이 끝나면 맨 마지막 줄에 [[END {rid}]] 만 씁니다.")


def filler(n: int) -> str:
    unit = FILLER_UNIT
    return (unit * (n // len(unit) + 1))[:max(0, int(n))]


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def current(profile_doc: dict, profile_id: str, model: str, edge_major: int, cfg, clock) -> dict | None:
    """유효 기간(``bridge.calibrateTtlDays``) 안의 같은 키 최신 보정값."""
    best = None
    t = _d(today(clock))
    for e in (profile_doc or {}).get("calibration") or []:
        if not isinstance(e, dict):
            continue
        if str(e.get("profile_id") or "") != str(profile_id or "") or str(e.get("model") or "") != str(model or ""):
            continue
        if int(e.get("edge_major") or 0) != int(edge_major or 0):
            continue
        d = _d(e.get("date"))
        if d is None or t is None or (t - d).days > int(cfg.calibrate_ttl_days):
            continue
        if best is None or str(e.get("date")) >= str(best.get("date")):
            best = e
    return best


def _ask(rt, text: str, rid: str, model: str):
    """보정 전송 1회(L1 직접 — 단계 아님). 프롬프트 게이트를 통과해야 보낸다."""
    if rt.gate_sg is not None:
        ok, _counts = rt.gate_sg.prompt(text)
        if not ok:
            return None
    cfg, clock = rt.cfg, rt.clock
    reply, first = cfg.rung_timeouts(0)
    req = SendRequest(rid, text, True, model, reply, first, clock.mono() + cfg.roundtrip_max_sec, CALIB_STAGE, False)
    rt.sends += 1
    return rt.transport.roundtrip(req)


def measure_input(rt, model: str) -> tuple[int, bool]:
    """입력 한도(글자) — 주입만(전송 없음) + 서버 쪽 잘림 확인 1~3회 전송. 실패면 (0, False)."""
    t, cfg, clock = rt.transport, rt.cfg, rt.clock
    dl = Deadline.after(clock, cfg.roundtrip_max_sec)
    r = t.inject(filler(INPUT_LO), dl)
    t.clear_editor()
    if r.phase != "ok":
        return 0, False
    lo, hi = INPUT_LO, INPUT_HI
    r = t.inject(filler(hi), dl)
    t.clear_editor()
    if r.phase == "ok":
        lo = hi
    else:
        cand = int(r.got) if r.phase == "input_overflow" else 0
        if INPUT_LO <= cand < hi:
            v = t.inject(filler(cand), dl)
            t.clear_editor()
            if v.phase == "ok":
                lo, hi = cand, cand
        iters = 0
        while hi - lo > SEARCH_STEP and iters < SEARCH_ITERS:
            mid = (lo + hi) // 2
            ok = t.inject(filler(mid), dl).phase == "ok"
            t.clear_editor()
            lo, hi = (mid, hi) if ok else (lo, mid)
            iters += 1
    server_trunc = False
    for _try in range(SERVER_TRUNC_TRIES + 1):
        rid = _new_rid(rt)
        code = "".join(secrets.choice(CODE_ALPHA) for _ in range(CODE_LEN))
        head = INPUT_CHECK_PROMPT.format(rid=rid)
        tail = INPUT_CODE_TEMPLATE.format(code=code)
        text = head + filler(max(0, lo - len(head) - len(tail))) + tail
        res = _ask(rt, text, rid, model)
        if res is None:
            break
        x = jsonx.extract(res.body or "", rid)
        items = (x.obj or {}).get("items") if x.kind == "env" else None
        got = str((items[0] or {}).get("code", "")).strip() if isinstance(items, list) and items and \
            isinstance(items[0], dict) else ""
        if got == code:
            break
        if res.phase not in ("replied", "stub", "no_reply"):
            break
        server_trunc = True
        lo = int(lo * SERVER_TRUNC_SHRINK)
    return lo, server_trunc


def measure_output(rt, model: str) -> int:
    """출력 한도(글자) — 잘린 길이가 곧 한도, 다 성공하면 마지막 성공 길이."""
    best = 0
    for k in OUTPUT_KS:
        rid = _new_rid(rt)
        res = _ask(rt, OUTPUT_CHECK_PROMPT.format(rid=rid, k=k), rid, model)
        if res is None:
            break
        body = res.body or ""
        x = jsonx.extract(body, rid)
        if x.kind != "env":
            break
        if x.how == "salvaged" or x.cut or res.phase == "no_reply":
            return len(body.rstrip())
        best = max(best, len(body.rstrip()))
    return best


class _Cal:
    def __init__(self, rt, gate_sg):
        self.transport, self.cfg, self.clock = rt.transport, rt.cfg, rt.clock
        self.used_rids = rt.used_rids
        self.gate_sg = gate_sg
        self.sends = 0


def _new_rid(cal) -> str:
    from lm27.bridge.exchange import new_rid
    return new_rid(cal.used_rids, cal.gate_sg.rid_ok if cal.gate_sg is not None else None)


def run_calibration(rt, *, model_class: str = "fast", force: bool = False) -> dict | None:
    """보정 1회 → 저장한 항목(또는 None — 전송 수단이 주입을 지원하지 않거나 실패). 유효한 값이 있으면 ``force`` 일 때만."""
    t = rt.transport
    if t is None or not callable(getattr(t, "inject", None)) or not callable(getattr(t, "clear_editor", None)):
        return None
    cfg, clock = rt.cfg, rt.clock
    model = cfg.model_for(model_class)
    if rt.profile is None:
        return None
    if not force and current(rt.profile.load(), rt.profile_id, model, rt.edge_major, cfg, clock):
        return None
    gate_sg = rt.gate_base.for_stage(CALIB_STAGE, web_exposed=True) if rt.gate_base is not None else None
    cal = _Cal(rt, gate_sg)
    in_limit, server_trunc = measure_input(cal, model)
    if in_limit <= 0:
        return None
    out_limit = measure_output(cal, model)
    if out_limit <= 0:
        return None
    (ilo, ihi), (olo, ohi) = BG.pack_bounds()
    entry = {"profile_id": rt.profile_id, "model": model, "edge_major": int(rt.edge_major or 0),
             "date": today(clock), "input_limit": int(in_limit), "output_limit": int(out_limit),
             "pack_in": BG.clamp(in_limit * cfg.calib_safety, ilo, ihi),
             "pack_out": BG.clamp(out_limit * cfg.calib_safety, olo, ohi),
             "server_trunc": bool(server_trunc), "sends": cal.sends}

    def put(d):
        lst = [e for e in d.get("calibration") or [] if isinstance(e, dict)]
        lst.append(entry)
        d["calibration"] = lst[-KEEP_ENTRIES:]
    rt.profile.update(put)
    rt.notify("BR-CALIB", **{"in": entry["input_limit"], "out": entry["output_limit"]})
    return entry


def stale_date(clock, cfg) -> str:
    """유효 기간 경계 날짜(진단 표시용)."""
    t = _d(today(clock))
    return (t - timedelta(days=int(cfg.calibrate_ttl_days))).isoformat() if t else ""


def calibrate(*, force: bool = False, model: str = "fast", paths=None, **kw) -> dict | None:
    """공개 API ``lm27.bridge.calibrate(…)``(계약 §2.12) — 호출 1회를 열어 보정하고 닫는다. 저장한 보정값 또는 None."""
    from lm27.bridge import runner
    rt = runner.open_runtime(paths, None, mode="auto", **kw)
    try:
        return run_calibration(rt, model_class=model, force=force)
    finally:
        runner.close_runtime(rt)


class _CallableModule(types.ModuleType):
    """모듈 자체를 ``calibrate(force=…, model=…, paths=…)`` 처럼 부를 수 있는 모듈 형(패키지 공개 이름과 같은 객체)."""

    def __call__(self, *args, **kwargs):
        return calibrate(*args, **kwargs)


sys.modules[__name__].__class__ = _CallableModule
