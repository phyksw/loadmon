# -*- coding: utf-8 -*-
"""WP-24 전체 흐름(가짜 CDP·가상 시계 — 실 Edge 0) — B-T46(LM_NO_BROWSER → edge_not_found → 수동 전환, BR-MANUAL-SWITCH) ·
B-T47(closeOnExit: 우리가 띄운 Edge 는 Browser.close, 원래 떠 있던 Edge 는 그대로) · B-T48/G-B10(모든 종료 경로에서 결과
봉투, rc 표 일치) · B-T15 의 L3 몫(로그인 안 함 → strike 1 → 확인 재전송 실패 → 단계 중지 fatal, 남은 단계 skipped)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lm27.bridge import runner
from lm27.bridge.gate import GateBase, clock_iso_of
from lm27.bridge.messages import Notices
from lm27.bridge.transport_stub import StubTransport, build_reply, item_ids
from lm27.privacy.detect import SanitizeContext
from lm27.util import events

from tests.bridge.fake_cdp import FakePage, FakeReply
from tests.bridge.fake_http import World
from tests.bridge.stub_responder import StubResponder
from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp24.rig import ENV_SAFE, REG, RUN, Rig, act_rows, settings
from tests.fixtures.wp24.stages import ActStage, LabelStage

PC = "pc_0123456789abcdef"


def setUpModule():
    events.configure(mode="off")


def _act_reply(prompt, rid):
    ids = item_ids(prompt)
    return build_reply("ok", rid, ids, {i: {"act": "info", "conf": "m"} for i in ids})[1]


class FullBase(unittest.TestCase):
    def world(self, page=None, environ=None, overrides=None):
        w = World(page_factory=lambda url: FakePage(w.clock, **{"url": url, **(page or {})}), overrides=overrides)
        self.addCleanup(w.cleanup)
        if environ:
            w.environ.update(environ)
        return w

    def open(self, w, notices, run_id=RUN, **kw):
        _cfg, raw = settings(w.tmp)
        gb = GateBase(SanitizeContext(), None, None, paths=w.paths, policy="strict", clock_iso=clock_iso_of(w.clock),
                      environ=dict(ENV_SAFE), machine_guid="")
        return runner.open_runtime(w.paths, run_id, mode=kw.pop("mode", "auto"), clock=w.clock, environ=w.environ,
                                   session_factory=lambda: w.session("bridge", run_id, notices=notices),
                                   emit=None, notices=notices, registry=REG, gate_base=gb, pc_id=PC, raw_cfg=raw,
                                   heartbeat=False, **kw)

    def write(self, w, stage, rows):
        p = Path(w.paths.ai_in(stage))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))


class Flows(FullBase):
    def test_T46_no_browser_switches_to_manual(self):
        w = self.world(environ={"LM_NO_BROWSER": "1"})
        notices = Notices()
        self.write(w, "t_act", act_rows(3))
        rt = self.open(w, notices)
        self.assertEqual(rt.transport.kind, "manual")
        self.assertTrue(rt.env.web_exposed)
        res = runner.run_stages(rt, [ActStage()])["t_act"]
        runner.close_runtime(rt)
        self.assertEqual(w.net.launches, [])                               # Edge 기동 0
        self.assertEqual((res["stop_kind"], res["rc"], res["transport"]), ("manual_wait", 2, "manual"))
        self.assertIn("BR-EDGE", notices.shown)
        self.assertIn("BR-MANUAL-SWITCH", notices.shown)
        self.assertEqual(len(list(Path(w.paths.copilot_manual()).glob("*.prompt.txt"))), 1)

    def test_T47_close_on_exit_launched_vs_existing(self):
        w = self.world()
        notices = Notices()
        self.write(w, "t_act", act_rows(4))
        rt = self.open(w, notices)
        page = w.net.our_pages()[0]
        page.replies.extend([FakeReply(text=_act_reply, cps=2000)] * 3)
        res = runner.run_stages(rt, [ActStage()])["t_act"]
        runner.close_runtime(rt)
        self.assertEqual((res["state"], res["transport"], res["items_ai"]), ("done", "cdp", 4))
        browser = next(b for b in w.net.browsers.values() if not b.foreign)
        self.assertEqual(browser.closed_by_cdp, 1)                         # 우리가 띄운 Edge → Browser.close
        w2 = self.world()
        b2 = w2.net.add_ours(9343, w2.profile_dir)
        self.write(w2, "t_act", act_rows(2))
        rt2 = self.open(w2, Notices())
        w2.net.our_pages()[-1].replies.extend([FakeReply(text=_act_reply, cps=2000)] * 3)
        runner.run_stages(rt2, [ActStage()])
        runner.close_runtime(rt2)
        self.assertEqual(w2.net.launches, [])
        self.assertEqual(b2.closed_by_cdp, 0)                              # 원래 떠 있던 Edge 는 그대로
        self.assertTrue(b2.alive)

    def test_T15_login_never_held_not_failed(self):
        """처음부터 로그인 화면이고 사람이 로그인하지 않음 — 세션이 로그인 대기를 다 하고 보류를 남겼다: 단계는 실패(2-strike
        치명·rc 1)가 아니라 skipped(login_pending)·rc 0(O-18 ⑤ · V18)."""
        w = self.world(page={"login_until_s": 10 ** 9})
        notices = Notices()
        self.write(w, "t_act", act_rows(3))
        self.write(w, "t_label", [{"key": "grp:1", "fields": {"kinds": "메일 1", "subjects": ["회의 준비"]}}])
        rt = self.open(w, notices)
        res = runner.run_stages(rt, [ActStage(), LabelStage()])
        runner.close_runtime(rt)
        for st in ("t_act", "t_label"):
            self.assertEqual((res[st]["state"], res[st]["stop_kind"], res[st]["reason"], res[st]["rc"]),
                             ("skipped", None, "login_pending", 0), st)
        self.assertIn("BR-LOGIN-HELD", notices.shown)
        self.assertNotIn("BR-LOGIN-TIMEOUT", notices.shown)
        self.assertEqual(runner.worst_rc(res), 0)

    def test_T15_login_lost_midrun_two_strikes_and_rest_skipped(self):
        """B-T15 의 L3 몫 — 실행 중 로그인이 풀렸고 질의 마감 안에서 로그인 대기가 잘렸다(보류 아님): strike 1 → 확인 재전송
        실패 → 단계 중지 fatal(login_required), 남은 단계 skipped(fatal)."""
        w = self.world(overrides={"bridge.loginWaitMin": 30})          # 30분 > 질의 마감(roundtripMaxSec 900초)
        notices = Notices()
        self.write(w, "t_act", act_rows(3))
        self.write(w, "t_label", [{"key": "grp:1", "fields": {"kinds": "메일 1", "subjects": ["회의 준비"]}}])
        rt = self.open(w, notices)
        for p in w.net.our_pages():
            p.login_until_s = 10 ** 9                                   # 세션이 준비된 뒤 로그인이 풀림
        res = runner.run_stages(rt, [ActStage(), LabelStage()])
        runner.close_runtime(rt)
        a, b = res["t_act"], res["t_label"]
        self.assertEqual((a["stop_kind"], a["reason"], a["resumable"], a["state"], a["rc"]),
                         ("fatal", "login_required", True, "failed", 1))
        self.assertEqual(a["statuses"], {"transport_fatal": 2})
        self.assertEqual((b["state"], b["stop_kind"], b["rc"]), ("skipped", "fatal", 0))
        self.assertIn("BR-LOGIN", notices.shown)
        self.assertIn("BR-LOGIN-TIMEOUT", notices.shown)
        self.assertEqual(runner.worst_rc(res), 1)


class _Boom(ActStage):
    def item_line(self, it, n):
        raise RuntimeError("단계 버그 흉내")


class Envelopes(unittest.TestCase):
    """B-T48 / G-B10: 정상·예외·중지·건너뜀·사용자 중단 — 결과 봉투가 늘 있고 rc 가 표와 같다."""

    def check(self, r, stage, state, rc):
        res = r.result(stage)
        self.assertEqual(check_stage_common(res), [])
        self.assertEqual((res["state"], res["rc"]), (state, rc))
        return res

    def test_all_exit_paths(self):
        r = Rig(stages=[ActStage()])
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_act", act_rows(2))
        r.run()
        self.check(r, "t_act", "done", 0)
        r2 = Rig(stages=[_Boom()])
        self.addCleanup(r2.cleanup)
        r2.write_ai_in("t_act", act_rows(2))
        r2.run()
        res = self.check(r2, "t_act", "failed", 1)
        self.assertEqual((res["stop_kind"], res["reason"], res["error_type"]), ("fatal", "exception", "RuntimeError"))
        r3 = Rig(stages=[ActStage()], overrides={"bridge.mode": "off"})
        self.addCleanup(r3.cleanup)
        r3.write_ai_in("t_act", act_rows(2))
        r3.run()
        self.check(r3, "t_act", "skipped", 0)
        st = StubResponder([ActStage()], script={"t_act": ["ok", "partial:0.5"]})

        class _Interrupt(StubTransport):
            def roundtrip(self, req):
                if self.sends >= 1:
                    raise KeyboardInterrupt
                return super().roundtrip(req)
        r4 = Rig(stages=[ActStage()], transport=_Interrupt(st), responder=st)
        self.addCleanup(r4.cleanup)
        r4.write_ai_in("t_act", act_rows(50))
        with self.assertRaises(KeyboardInterrupt):
            r4.run()
        res = self.check(r4, "t_act", "partial", 2)
        self.assertEqual((res["stop_kind"], res["items_ai"]), ("cancelled", 40))


class Probe(FullBase):
    def test_probe_ready_world(self):
        from lm27.bridge.cli import do_probe
        w = self.world()
        notices = Notices()

        def probe_reply(prompt, rid):
            ids = item_ids(prompt)
            words = {1: "사과", 2: "바다"}
            return build_reply("ok", rid, ids, {i: {"w": words.get(i, "")} for i in ids})[1]
        _cfg, raw = settings(w.tmp)
        gb = GateBase(SanitizeContext(), None, None, paths=w.paths, clock_iso=clock_iso_of(w.clock),
                      environ=dict(ENV_SAFE), machine_guid="")
        orig = w.net.page_factory

        def pf(url):                                                       # 연결 확인 질의의 가짜 답
            page = orig(url)
            page.replies.append(FakeReply(text=probe_reply, cps=2000))
            return page
        w.net.page_factory = pf
        env = {"paths": w.paths, "environ": w.environ, "emit": None,
               "rt_kw": {"clock": w.clock, "session_factory": lambda: w.session("bridge", RUN, notices=notices),
                         "registry": REG, "gate_base": gb, "pc_id": PC, "raw_cfg": raw, "notices": notices}}
        out = do_probe(env, roundtrip=True)
        by = {c["id"]: c for c in out["checks"]}
        for cid in ("edge", "launch", "tab", "identity", "login", "roundtrip", "stub_env", "lock", "port"):
            self.assertTrue(by[cid]["ok"], (cid, by[cid]))
        self.assertEqual(out["recommend"], "auto")
        self.assertEqual(by["calib"]["code"], "calib_none")
        self.assertEqual(out["rc"], 2)                                     # 보정값 없음 = 경고(제한적)
        last = json.loads(Path(w.paths.bridge_dir(), "probe_last.json").read_text("utf-8"))
        self.assertEqual(last["recommend"], "auto")
        self.assertIn("last_probe", json.loads(Path(w.paths.bridge_dir(), "bridge_profile.json")
                                               .read_text("utf-8"))["health"])

    def test_probe_no_browser_recommends_manual(self):
        from lm27.bridge.cli import do_probe
        w = self.world(environ={"LM_NO_BROWSER": "1"})
        _cfg, raw = settings(w.tmp)
        gb = GateBase(SanitizeContext(), None, None, paths=w.paths, clock_iso=clock_iso_of(w.clock),
                      environ=dict(ENV_SAFE), machine_guid="")
        env = {"paths": w.paths, "environ": w.environ, "emit": None,
               "rt_kw": {"clock": w.clock, "session_factory": lambda: w.session("bridge", RUN), "registry": REG,
                         "gate_base": gb, "pc_id": PC, "raw_cfg": raw}}
        out = do_probe(env, roundtrip=True)
        by = {c["id"]: c for c in out["checks"]}
        self.assertFalse(by["stub_env"]["ok"])
        self.assertEqual(out["recommend"], "manual")
        self.assertEqual(out["rc"], 2)


class OpenFailureCleanup(FullBase):
    """W1b 회귀: open_runtime 이 세션을 연 뒤 자동 보정(3~6분) 중 예외(Ctrl+C·CdpError)가 나도 우리가 띄운 디버그 포트
    Edge·CDP·session.lock.json 이 남지 않는다(다음 실행이 그 Edge 를 '재사용'해 closeOnExit 가 영영 적용되지 않던 결함)."""

    def _world(self, exc):
        class Page(FakePage):
            def cdp_call(self, method, params):
                if method == "Input.insertText":
                    raise exc
                return super().cdp_call(method, params)
        w = World(page_factory=lambda url: Page(w.clock, url=url))
        self.addCleanup(w.cleanup)
        return w

    def _ours(self, w):
        return [b for b in w.net.browsers.values() if not b.foreign]

    def test_ctrl_c_during_calibration_closes_edge_and_lock(self):
        w = self._world(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.open(w, Notices(), calibrate_model="fast")
        (b,) = self._ours(w)
        self.assertEqual((b.alive, b.closed_by_cdp), (False, 1))                       # 우리가 띄운 Edge → Browser.close
        self.assertFalse(Path(w.paths.edge_lock()).exists())                           # 잠금 해제

    def test_cdp_error_in_inject_is_a_phase_not_an_exception(self):
        from lm27.bridge.cdp import CdpError
        w = self._world(CdpError("Target closed"))
        rt = self.open(w, Notices(), calibrate_model="fast")                         # 보정은 실패로 끝나고 실행은 이어진다
        try:
            from lm27.bridge.clock import Deadline
            r = rt.transport.inject("가나다", Deadline.after(w.clock, 30))
            self.assertIn(r.phase, ("cdp_error", "tab_lost"))
        finally:
            runner.close_runtime(rt)
        (b,) = self._ours(w)
        self.assertEqual((b.alive, b.closed_by_cdp), (False, 1))
        self.assertFalse(Path(w.paths.edge_lock()).exists())

    def test_owned_vs_injected_transport_on_failure(self):
        """전송을 연 뒤 조립 단계(레지스트리)에서 실패 — 여기서 만든 CDP 세션은 닫고, 주입받은 전송은 호출자 몫으로 둔다."""
        from unittest import mock
        w = self.world()
        with mock.patch.object(runner, "_registry", side_effect=RuntimeError("조립 실패 흉내")),                 self.assertRaises(RuntimeError):
            runner.open_runtime(w.paths, RUN, mode="auto", clock=w.clock, environ=w.environ,
                                session_factory=lambda: w.session("bridge", RUN, notices=Notices()), emit=None,
                                notices=Notices(), registry=None, gate_base=None, pc_id=PC, raw_cfg=settings(w.tmp)[1],
                                heartbeat=False)
        (b,) = self._ours(w)
        self.assertEqual((b.alive, b.closed_by_cdp), (False, 1))
        self.assertFalse(Path(w.paths.edge_lock()).exists())
        closed = []

        class T(StubTransport):
            def close(self):
                closed.append(1)
        with mock.patch.object(runner, "_registry", side_effect=RuntimeError("조립 실패 흉내")),                 self.assertRaises(RuntimeError):
            runner.open_runtime(w.paths, RUN, mode="auto", clock=w.clock, environ=w.environ,
                                transport=T(lambda prompt, rid, stage: ("ok", "")), emit=None, notices=Notices(),
                                registry=None, gate_base=None, pc_id=PC, raw_cfg=settings(w.tmp)[1], heartbeat=False)
        self.assertEqual(closed, [])                                                   # 주입받은 전송은 닫지 않는다


if __name__ == "__main__":
    unittest.main()
