# -*- coding: utf-8 -*-
r"""조회 능력 기록(B §7.13) — 메일·팀즈·일정 조회 단계가 '될 수 있는가'를 서로 다른 날 2회 확정·TTL·해제로 기록한다.

상태 기계(``bridge_profile.capabilities.<조회 단계>``: ``{state, checks[{date, result, reason?}], until}``):

| 현재 | 관찰 | 다음 |
|---|---|---|
| unknown·ok·suspect | ok(행 0건 포함) | ok, checks 초기화(그 날 ok 한 줄) |
| unknown·ok | refusal(unavailable) · 수송 정상 | suspect(그 날짜 기록) |
| suspect | 다른 날짜의 unavailable 이 쌓여 날짜 수 ≥ ``collect.confirmBlockedCount`` | unavailable, until = 오늘 + ``collect.confirmTtlDays`` |
| suspect | 같은 날 다시 호출 | 보내지 않는다(``skipped(capability_unavailable)``) — suspect 유지 |
| unavailable | until 지남 | unknown(재확인 표식) |
| 아무 상태 | 수송 실패(transport_fatal·timeout) | **변화 없음** — 수송 실패는 능력 판단 근거가 아니다 |

  · **R-NOLIC 은 계정 단위** — 어느 조회든 무라이선스 문구면 그 날짜의 관찰을 세 조회 능력에 함께 기록한다.
    R-NOCONN(조회 도구 없음)은 단계별로만. 업무 모드가 아니어서 생략한 조회(mode_web)는 관찰이 아니다.
  · ``any_ok_within(days)``·``any_reason_within(code, days)`` 를 갖춰 ``env.detect_env``·``recompute`` 에 그대로 넘긴다
    (WP-23 계약 — 계정 등급 판별).
  · 호출 끝에 ``data\ai\runs\<run_id>\capabilities.json``(상태·날짜·사유 코드만)을 쓰고, PC 능력 기록(계약 §3.8
    ``pc.json.capabilities``)은 ``lm27.bundle.pcreg.record_probe`` 로만 남긴다(키 ``mail.copilot``·``teams.copilot``·
    ``cal.copilot`` + ``copilot_connector``(하위 mail·teams·calendar)). 판정 어휘 대응: ok→가능 · suspect→불가(잠정) ·
    unavailable→불가(확정) · unknown→미확인.
"""
from __future__ import annotations

from datetime import date, timedelta

from lm27.bridge.clock import today

LOOKUP_STAGES = ("lookup_mail", "lookup_teams", "lookup_calendar")
SRC_OF = {"lookup_mail": "mail.copilot", "lookup_teams": "teams.copilot", "lookup_calendar": "cal.copilot"}
SUB_OF = {"lookup_mail": "mail", "lookup_teams": "teams", "lookup_calendar": "calendar"}
LABEL_KO = {"lookup_mail": "메일", "lookup_teams": "Teams 채팅", "lookup_calendar": "일정"}     # BR-LOOKUP-* 자리 값(받침 → 을)
STATES = ("unknown", "ok", "suspect", "unavailable")
VERDICT_OF = {"ok": "가능", "suspect": "불가(잠정)", "unavailable": "불가(확정)", "unknown": "미확인"}
NOLIC = "R-NOLIC"
NOCONN = "R-NOCONN"
CHECKS_MAX = 10
PC_LOCK_WAIT_S = 5.0


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


class ChatAccess:
    """Copilot 채팅 접근(M5) — ``bridge_profile.chat_access`` = ``{state, checks[{date, result}], until}``. 관리자가 Copilot Chat
    을 막으면 같은 주소에 입력창 없는 안내 화면이 나온다(문서: 'shown an in-product message explaining that access is disabled
    by organizational policy'). Copilot 주소·로드 끝인데 입력창이 없는(input_not_found) 날이 서로 다른
    ``collect.confirmBlockedCount`` 날 쌓이면 ``unavailable``(``collect.confirmTtlDays`` 동안 분석은 세션을 열지 않고 AI 단계
    skipped(chat_unavailable)), 입력창을 한 번이라도 보면 ok 로 되돌린다. 조회 능력(``Capabilities``)과 따로 둔다 — 계정 등급
    판별에 섞이지 않게. 연결 진단(probe)은 이 상태와 무관하게 늘 다시 본다."""

    KEY = "chat_access"

    def __init__(self, profile, cfg, clock):
        self.profile = profile
        self.cfg = cfg
        self.clock = clock

    def _load(self) -> dict:
        d = (self.profile.load().get(self.KEY) if self.profile is not None else None) or {}
        st = d.get("state") if d.get("state") in ("ok", "suspect", "unavailable") else "unknown"
        checks = [x for x in d.get("checks") or [] if isinstance(x, dict) and _d(x.get("date"))]
        return {"state": st, "checks": checks[-CHECKS_MAX:], "until": d.get("until")}

    def _save(self, c: dict) -> None:
        if self.profile is None:
            return

        def put(d):
            d[self.KEY] = c
        self.profile.update(put)

    def state(self) -> str:
        c = self._load()
        if c["state"] == "unavailable":
            until = _d(c.get("until"))
            if until is not None and _d(today(self.clock)) > until:
                return "unknown"                                    # TTL 지남 — 다시 확인
        return c["state"]

    def observe_ok(self) -> None:
        c = self._load()
        if c["state"] == "ok" and not c["checks"]:
            return
        self._save({"state": "ok", "checks": [], "until": None})

    def observe_blocked(self) -> bool:
        """입력창 없는 Copilot 화면 관찰(그 날 한 번). 반환: 이번 관찰로 unavailable 이 되었는가."""
        c = self._load()
        d = today(self.clock)
        checks = c["checks"] + ([] if any(x.get("date") == d for x in c["checks"]) else [{"date": d, "result": "no_input"}])
        days = {x.get("date") for x in checks}
        if len(days) >= int(self.cfg.confirm_count):
            until = (_d(d) + timedelta(days=int(self.cfg.confirm_ttl_days))).isoformat()
            self._save({"state": "unavailable", "checks": checks[-CHECKS_MAX:], "until": until})
            return c["state"] != "unavailable"
        self._save({"state": "suspect", "checks": checks[-CHECKS_MAX:], "until": None})
        return False


class Capabilities:
    """``bridge_profile.json`` 의 조회 능력. ``profile`` = ``session.BridgeProfile``(None 이면 메모리에만)."""

    def __init__(self, profile, cfg, clock):
        self.profile = profile
        self.cfg = cfg
        self.clock = clock
        raw = (profile.load().get("capabilities") if profile is not None else None) or {}
        self.caps: dict = {}
        for sid in LOOKUP_STAGES:
            c = raw.get(sid) if isinstance(raw.get(sid), dict) else {}
            st = c.get("state") if c.get("state") in STATES else "unknown"
            checks = [x for x in c.get("checks") or [] if isinstance(x, dict) and _d(x.get("date"))]
            self.caps[sid] = {"state": st, "checks": checks[-CHECKS_MAX:], "until": c.get("until"),
                              "recheck": bool(c.get("recheck"))}
        self.observed: dict = {}          # 이번 호출의 관찰 {단계: (result, reason)} — PC 기록 재료
        self.events: list = []            # 띄울 문구 [(코드, 단계)]

    @property
    def today(self) -> str:
        return today(self.clock)

    # ── 조회 ──────────────────────────────────────────────────────────
    def state(self, stage: str) -> str:
        c = self.caps.get(stage)
        if c is None:
            return "unknown"
        if c["state"] == "unavailable":
            until = _d(c.get("until"))
            if until is not None and _d(self.today) > until:
                c.update(state="unknown", until=None, recheck=True)
                self._save()
        return c["state"]

    def checked_today(self, stage: str) -> bool:
        c = self.caps.get(stage) or {}
        return any(x.get("result") == "unavailable" and str(x.get("date"))[:10] == self.today
                   for x in c.get("checks") or [])

    def recheck_pending(self, stage: str) -> bool:
        """unavailable TTL 이 지나 unknown 으로 돌아온 뒤 첫 확인(1일 구간 1회 — 단계가 좁힌다)."""
        return self.state(stage) == "unknown" and bool((self.caps.get(stage) or {}).get("recheck"))

    def reasons(self, stage: str) -> list:
        c = self.caps.get(stage) or {}
        return sorted({x.get("reason") for x in c.get("checks") or [] if x.get("result") == "unavailable"
                       and isinstance(x.get("reason"), str)})

    @staticmethod
    def _unavailable_days(checks) -> set:
        """마지막 ok 이후의 unavailable 관찰 날짜 집합(서로 다른 날 확정 — 같은 날 여러 번은 1)."""
        last_ok = max((i for i, x in enumerate(checks) if x.get("result") == "ok"), default=-1)
        return {str(x.get("date"))[:10] for x in checks[last_ok + 1:] if x.get("result") == "unavailable"}

    def confirmed_days(self, stage: str) -> int:
        c = self.caps.get(stage) or {}
        return len(self._unavailable_days(c.get("checks") or []))

    # env.detect_env·recompute 가 부르는 두 메서드(WP-23)
    def _recent(self, d, days: int) -> bool:
        x = _d(d)
        return x is not None and x >= _d(self.today) - timedelta(days=int(days))

    def any_ok_within(self, days: int) -> bool:
        return any(x.get("result") == "ok" and self._recent(x.get("date"), days)
                   for c in self.caps.values() for x in c.get("checks") or [])

    def any_reason_within(self, code: str, days: int) -> bool:
        return any(x.get("reason") == code and self._recent(x.get("date"), days)
                   for c in self.caps.values() for x in c.get("checks") or [])

    # ── 관찰 ──────────────────────────────────────────────────────────
    def observe_ok(self, stage: str) -> None:
        if stage not in self.caps:
            return
        self.caps[stage] = {"state": "ok", "checks": [{"date": self.today, "result": "ok"}], "until": None,
                            "recheck": False}
        self.observed[stage] = ("ok", "")
        self._save()

    def observe_unavailable(self, stage: str, reason: str = NOCONN) -> list:
        """refusal(unavailable) 관찰. R-NOLIC 이면 세 조회 능력에 함께. 반환: 새로 확정된 단계 목록."""
        reason = reason if reason in (NOLIC, NOCONN) else NOCONN
        targets = LOOKUP_STAGES if reason == NOLIC else (stage,)
        confirmed = []
        for sid in targets:
            c = self.caps.get(sid)
            if c is None:
                continue
            new = {"date": self.today, "result": "unavailable", "reason": reason}
            checks = (list(c["checks"]) + [new])[-CHECKS_MAX:]
            days = self._unavailable_days(checks)
            if len(days) >= int(self.cfg.confirm_count):
                until = (_d(self.today) + timedelta(days=int(self.cfg.confirm_ttl_days))).isoformat()
                self.caps[sid] = {"state": "unavailable", "checks": checks, "until": until, "recheck": False}
                confirmed.append(sid)
                self.events.append(("BR-LOOKUP-UNAVAILABLE", sid))
            else:
                self.caps[sid] = {"state": "suspect", "checks": checks, "until": None, "recheck": False}
                self.events.append(("BR-LOOKUP-SUSPECT", sid))
            self.observed[sid] = ("unavailable", reason)
        if reason == NOLIC:
            self.events.append(("BR-NOLIC", stage))
        self._save()
        return confirmed

    def reset(self, stage: str) -> None:
        """화면의 '다시 확인' — 사용자 본인의 선택으로 unknown 으로 돌린다."""
        if stage in self.caps:
            self.caps[stage] = {"state": "unknown", "checks": [], "until": None, "recheck": False}
            self._save()

    def _save(self) -> None:
        if self.profile is None:
            return
        snap = {sid: {"state": c["state"], "checks": list(c["checks"]), "until": c.get("until"),
                      **({"recheck": True} if c.get("recheck") else {})} for sid, c in self.caps.items()}

        def put(d):
            d["capabilities"] = snap
        self.profile.update(put)

    # ── 내보내기 ───────────────────────────────────────────────────────
    def export(self) -> dict:
        r"""``capabilities.json`` 형(B §7.13 — 두 형제 명세 형식 함께): 출처 키 ``mail.copilot`` 등."""
        out = {}
        for sid in LOOKUP_STAGES:
            st = self.state(sid)
            c = self.caps[sid]
            out[SRC_OF[sid]] = {"state": st, "ok": True if st == "ok" else (False if st == "unavailable" else None),
                                "reasons": self.reasons(sid), "confirmed_days": self.confirmed_days(sid),
                                "verdict": VERDICT_OF[st], "until": c.get("until"),
                                "checks": [{k: v for k, v in x.items() if k in ("date", "result", "reason")}
                                           for x in c["checks"]]}
        return out

    def record_pc(self, paths, pc_id: str | None, cfg_raw=None) -> int:
        """이번 호출의 관찰을 PC 능력 기록에(``pcreg.record_probe`` 만 — 계약 §3.8). 번들 잠금을 못 잡거나 pc.json 이
        없으면 건너뛴다. 반환: 기록한 키 수."""
        if not pc_id or not self.observed:
            return 0
        from lm27.bundle import pcreg
        from lm27.bundle.lock import BundleBusy, BundleLock
        pcdir = paths.pc_dir(pc_id)
        n = 0
        try:
            with BundleLock(paths, "fg-write", PC_LOCK_WAIT_S):
                if pcreg.load_pc(pcdir) is None:
                    return 0
                d = self.today
                for sid, (result, reason) in sorted(self.observed.items()):
                    ok = result == "ok"
                    pcreg.record_probe(pcdir, SRC_OF[sid], ok, {"state": self.state(sid)},
                                       [] if ok else [reason], "ok" if ok else "fail", date=d, cfg=cfg_raw, today=d)
                    n += 1
                sub = {SUB_OF[s]: VERDICT_OF[self.state(s)] for s in LOOKUP_STAGES}
                oks = [s for s, (r, _x) in self.observed.items() if r == "ok"]
                reasons = sorted({x for _s, (r, x) in self.observed.items() if r != "ok" and x})
                pcreg.record_probe(pcdir, "copilot_connector", bool(oks), sub, [] if oks else reasons,
                                   "ok" if oks else "fail", date=d, cfg=cfg_raw, today=d)
                n += 1
        except BundleBusy:
            return n
        return n
