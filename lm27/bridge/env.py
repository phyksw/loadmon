# -*- coding: utf-8 -*-
r"""Copilot 환경 판별(B §4.11) — 계정 등급·업무 탭·업무 모드·웹 근거·웹 노출(``CopilotEnv``)과 ``bridge_profile.env`` 기록.

  · 판별은 **읽기만** 한다. 업무 모드 전환 버튼만 ``bridge.preferWorkMode`` 에 따라 세션이 1회 누르고(§4.8),
    웹 근거 토글은 계정 설정이므로 누르지 않으며 그 토글이 든 설정 메뉴도 열지 않는다.
  · 계정 등급은 화면 표기가 아니라 '실제로 조회가 됐는가'(조회 능력 기록)로 정한다(B Q21).
  · ``web_exposed = not (work_mode == "work" and web_grounding == "off")`` — 둘 다 확인되기 전에는 웹 노출로 본다(B15).

    env = detect_env(sess)                     # 호출 시작 때 1회(세션 ensure_ready·업무 모드 맞추기 직후)
    env = recompute(env, caps, cfg, clock)     # 같은 호출 안에서 조회 결과(R-NOLIC·성공)가 기록되면 화면을 다시 읽지 않고 재계산
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from lm27.bridge import js
from lm27.bridge.clock import iso_now, today

TIERS = ("premium", "basic", "unknown")
WORK_MODES = ("work", "web", "unknown")
GROUNDING = ("on", "off", "unknown")
EVIDENCE = ("toggle_present", "toggle_absent", "switch_failed", "lookup_ok", "nolic_reply", "wg_on", "wg_off",
            "wg_missing")
NOLIC = "R-NOLIC"
LOOKUP_STAGES = ("lookup_mail", "lookup_teams", "lookup_calendar")


@dataclass
class CopilotEnv:
    tier: str = "unknown"            # premium | basic | unknown
    work_toggle: str = "unknown"     # present | absent | unknown
    work_mode: str = "unknown"       # work | web | unknown
    web_grounding: str = "unknown"   # on | off | unknown
    web_exposed: bool = True         # not (work_mode == "work" and web_grounding == "off")
    evidence: list = field(default_factory=list)   # 코드만(EVIDENCE)
    checked_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> dict:
        """결과 봉투·probe 출력용 다섯 값(B §7.11·§12.2)."""
        return {"tier": self.tier, "work_toggle": self.work_toggle, "work_mode": self.work_mode,
                "web_grounding": self.web_grounding, "web_exposed": self.web_exposed}

    @classmethod
    def from_dict(cls, d) -> CopilotEnv:
        d = d if isinstance(d, dict) else {}
        out = cls(tier=d.get("tier") if d.get("tier") in TIERS else "unknown",
                  work_toggle=d.get("work_toggle") if d.get("work_toggle") in ("present", "absent", "unknown")
                  else "unknown",
                  work_mode=d.get("work_mode") if d.get("work_mode") in WORK_MODES else "unknown",
                  web_grounding=d.get("web_grounding") if d.get("web_grounding") in GROUNDING else "unknown",
                  evidence=[e for e in d.get("evidence") or [] if e in EVIDENCE],
                  checked_at=str(d.get("checked_at") or ""))
        out.web_exposed = exposed(out.work_mode, out.web_grounding)
        return out


def exposed(work_mode: str, web_grounding: str) -> bool:
    return not (work_mode == "work" and web_grounding == "off")


def derive_env(dom: dict, *, cap_ok_recent: bool, nolic_recent: bool, identity_strong: bool,
               prefer_work_mode: bool, checked_at: str = "") -> CopilotEnv:
    """순수 판별(B §4.11 의사코드). ``dom`` = JS ``env`` 반환 ``{toggle:{found, work, web}, wg:{found, checked}}``
    (업무 모드 맞추기를 마친 뒤의 값)."""
    ev: list[str] = []
    t = (dom or {}).get("toggle") or {}
    if t.get("found"):
        work_toggle = "present"
        ev.append("toggle_present")
        work_mode = "work" if t.get("work") else ("web" if t.get("web") else "unknown")
        if work_mode == "web" and prefer_work_mode:
            ev.append("switch_failed")
    else:
        work_toggle = "absent" if identity_strong else "unknown"      # 신원이 약하면 화면이 바뀐 것일 수 있다
        if work_toggle == "absent":
            ev.append("toggle_absent")
        work_mode = "unknown"
    if cap_ok_recent:
        tier = "premium"
        ev.append("lookup_ok")
    elif nolic_recent:
        tier = "basic"
        ev.append("nolic_reply")
    else:
        tier = "unknown"
    if tier == "basic" and work_toggle != "present":
        work_mode = "web"                                             # 업무 탭 없는 무라이선스 = 웹 근거 전용
    wg = (dom or {}).get("wg") or {}
    if wg.get("found") and wg.get("checked") is True:
        web_grounding = "on"
        ev.append("wg_on")
    elif wg.get("found") and wg.get("checked") is False:
        web_grounding = "off"
        ev.append("wg_off")
    else:
        web_grounding = "unknown"
        ev.append("wg_missing")
    return CopilotEnv(tier, work_toggle, work_mode, web_grounding, exposed(work_mode, web_grounding), ev, checked_at)


class ProfileCaps:
    """``bridge_profile.json`` 의 ``capabilities``(B §4.10·§7.13)를 읽는 기본 능력 조회기.
    ``capabilities.<조회 단계>.checks[{date, result, reason?}]`` — result ``ok`` 는 성공, ``reason == R-NOLIC``
    (또는 ``reasons`` 에 포함)은 무라이선스 관찰. 조회 능력 기록기(capability.py)가 같은 메서드를 갖추면 대신 넘긴다."""

    def __init__(self, caps: dict | None, today_iso: str):
        self.caps = caps if isinstance(caps, dict) else {}
        self.today = today_iso

    def _checks(self):
        for sid in LOOKUP_STAGES:
            c = self.caps.get(sid)
            if isinstance(c, dict):
                for ch in c.get("checks") or []:
                    if isinstance(ch, dict):
                        yield ch

    def _recent(self, d, days: int) -> bool:
        try:
            return date.fromisoformat(str(d)[:10]) >= date.fromisoformat(self.today) - timedelta(days=int(days))
        except ValueError:
            return False

    def any_ok_within(self, days: int) -> bool:
        return any(ch.get("result") == "ok" and self._recent(ch.get("date"), days) for ch in self._checks())

    def any_reason_within(self, code: str, days: int) -> bool:
        def has(ch):
            rs = ch.get("reasons") if isinstance(ch.get("reasons"), list) else []
            return ch.get("reason") == code or code in rs
        return any(has(ch) and self._recent(ch.get("date"), days) for ch in self._checks())


def _caps_flags(caps, cfg) -> tuple[bool, bool]:
    if caps is None:
        return False, False
    days = cfg.confirm_ttl_days
    return bool(caps.any_ok_within(days)), bool(caps.any_reason_within(NOLIC, days))


def detect_env(sess, caps=None, *, record: bool = True) -> CopilotEnv:
    """세션 화면에서 판별(JS ``env`` 1회 — 페이지 글을 읽지 않는다). ``caps`` 가 없으면 ``bridge_profile.capabilities``.
    판별 결과는 ``sess.env`` 와 ``bridge_profile.env`` 에 남긴다(계정·테넌트 식별 정보 없음)."""
    cfg = sess.cfg
    try:
        dom = sess.eval(js.env(cfg.dom.work_labels, cfg.dom.web_labels, cfg.dom.web_grounding_labels)) or {}
    except Exception:  # noqa: BLE001 — 판별 실패는 '모름'(웹 노출 가정)으로 진행한다(B15)
        dom = {}
    if caps is None:
        caps = ProfileCaps(sess.profile.load().get("capabilities"), today(sess.clock))
    ok, nolic = _caps_flags(caps, cfg)
    env = derive_env(dom, cap_ok_recent=ok, nolic_recent=nolic, identity_strong=sess.info.identity == "strong",
                     prefer_work_mode=cfg.prefer_work_mode, checked_at=iso_now(sess.clock))
    sess.env = env
    if record:
        record_env(sess.profile, env)
    return env


def recompute(env: CopilotEnv, caps, cfg, clock) -> CopilotEnv:
    """같은 호출 안에서 조회 단계가 R-NOLIC·성공을 기록한 뒤 다시 계산(화면은 다시 읽지 않는다, B §4.11-6)."""
    ok, nolic = _caps_flags(caps, cfg)
    dom = {"toggle": {"found": env.work_toggle == "present", "work": env.work_mode == "work",
                      "web": env.work_mode == "web"},
           "wg": {"found": env.web_grounding != "unknown",
                  "checked": True if env.web_grounding == "on" else (False if env.web_grounding == "off" else None)}}
    # 토글 없음(absent)은 신원이 강했다는 뜻이고, unknown 은 약했다는 뜻 — 같은 결론이 나오게 넘긴다
    out = derive_env(dom, cap_ok_recent=ok, nolic_recent=nolic, identity_strong=env.work_toggle == "absent",
                     prefer_work_mode=False, checked_at=iso_now(clock))
    if "switch_failed" in env.evidence and "switch_failed" not in out.evidence:
        out.evidence.insert(1, "switch_failed")
    return out


def manual_env(clock) -> CopilotEnv:
    """수동 경로: 화면을 읽지 못하므로 모두 unknown, web_exposed=true(B §4.11-5)."""
    return CopilotEnv(checked_at=iso_now(clock))


def record_env(profile, env: CopilotEnv) -> None:
    """``bridge_profile.json`` 의 ``env`` 갱신."""
    def put(d):
        d["env"] = env.to_dict()
    profile.update(put)
