# -*- coding: utf-8 -*-
"""WP-24 보정 프로브(B §7.14) — B-T42: 가짜 입력 한도 9,000·출력 5,560 → pack_in 7,650 · pack_out 4,726, 저장 키
(profile_id, model, edge_major). 입력 한도는 주입만(전송 없음)으로, 서버 쪽 잘림은 확인 코드로, 출력 한도는 잘림 지점으로.
유효 기간·주입을 지원하지 않는 전송 수단(스텁)은 보정하지 않음."""
from __future__ import annotations

import json
import re
import unittest

from lm27.bridge import calibrate as CAL
from lm27.bridge.gate import GateBase, clock_iso_of
from lm27.bridge.messages import Notices
from lm27.bridge.runner import make_runtime
from lm27.bridge.transport import CdpTransport
from lm27.bridge.transport_stub import StubTransport
from lm27.privacy.detect import SanitizeContext
from lm27.util import events

from tests.bridge.fake_cdp import FakePage, FakeReply
from tests.bridge.fake_http import World
from tests.fixtures.wp24.rig import ENV_SAFE

RUN = "20261005-101500-3fa2"
OUT_LIMIT = 5560
_CODE_RX = re.compile(r"확인 코드 ([A-Z]{6})\s*$")
_K_RX = re.compile(r"항목 (\d+)개")


def setUpModule():
    events.configure(mode="off")


def _code_reply(prompt, rid):
    m = _CODE_RX.search(prompt)
    env = {"rid": rid, "n": 1, "items": [{"id": 1, "code": m.group(1) if m else ""}]}
    return "```json\n" + json.dumps(env) + "\n```\n[[END " + rid + "]]"


def _out_reply(prompt, rid):
    k = int(_K_RX.search(prompt).group(1))
    items = [{"id": i, "t": f"{i}번 항목 문장 가나다라마바사아자차카타파하 검증용 문장입니다 abcdefghijklmnopqrstuvwxyz 0123456"}
             for i in range(1, k + 1)]
    body = "```json\n" + json.dumps({"rid": rid, "n": k, "items": items}, ensure_ascii=False,
                                    separators=(",", ":")) + "\n```\n[[END " + rid + "]]"
    return body if len(body) <= OUT_LIMIT else body[:OUT_LIMIT]


class T42(unittest.TestCase):
    def rig(self):
        w = World(page_factory=lambda url: FakePage(w.clock, url=url, input_limit=9000))
        self.addCleanup(w.cleanup)
        s = w.session()
        self.assertEqual(s.start(), "ready")
        self.addCleanup(s.close)
        page = w.net.our_pages()[0]
        page.replies.extend([FakeReply(text=_code_reply, cps=2000), FakeReply(text=_out_reply, cps=2000),
                             FakeReply(text=_out_reply, cps=2000), FakeReply(text=_out_reply, cps=2000)])
        notices = Notices()
        gb = GateBase(SanitizeContext(), None, None, paths=w.paths, policy="strict", clock_iso=clock_iso_of(w.clock),
                      environ=dict(ENV_SAFE), machine_guid="")
        rt = make_runtime(w.paths, RUN, cfg=w.cfg, clock=w.clock, transport=CdpTransport(s), gate_base=gb,
                          profile=s.profile, notices=notices)
        rt.edge_major = s.edge.major
        return w, s, page, rt, notices

    def test_T42_limits_and_key(self):
        w, s, page, rt, notices = self.rig()
        entry = CAL.run_calibration(rt, model_class="fast")
        self.assertIsNotNone(entry)
        self.assertEqual((entry["input_limit"], entry["output_limit"]), (9000, OUT_LIMIT))
        self.assertEqual((entry["pack_in"], entry["pack_out"]), (7650, 4726))
        self.assertFalse(entry["server_trunc"])
        self.assertEqual((entry["profile_id"], entry["model"], entry["edge_major"]),
                         (rt.profile_id, w.cfg.model_fast, s.edge.major))
        self.assertEqual(entry["sends"], len(page.sent_texts))
        self.assertTrue(2 <= entry["sends"] <= 6)        # 확인 코드 1 + 출력 2(60 성공·100 잘림)
        stored = s.profile.load()["calibration"][-1]
        self.assertEqual(stored, entry)
        self.assertIn("BR-CALIB", notices.shown)
        self.assertTrue(all(len(t) <= 9000 for t in page.sent_texts))
        # 유효 기간 안이면 다시 하지 않고, 지나면 없다고 본다
        self.assertIsNone(CAL.run_calibration(rt, model_class="fast"))
        cur = CAL.current(s.profile.load(), rt.profile_id, w.cfg.model_fast, rt.edge_major, w.cfg, w.clock)
        self.assertEqual(cur, entry)
        w.clock.advance(86400 * (w.cfg.calibrate_ttl_days + 1))
        self.assertIsNone(CAL.current(s.profile.load(), rt.profile_id, w.cfg.model_fast, rt.edge_major, w.cfg,
                                      w.clock))
        self.assertIsNone(CAL.current(s.profile.load(), "other-profile", w.cfg.model_fast, rt.edge_major, w.cfg,
                                      w.clock.__class__()))

    def test_server_truncation_lowers_limit(self):
        w, s, page, rt, notices = self.rig()
        page.replies.clear()
        page.replies.extend([FakeReply(text=lambda p, rid: _code_reply("x", rid), cps=2000),
                             FakeReply(text=_code_reply, cps=2000)] + [FakeReply(text=_out_reply, cps=2000)] * 3)
        entry = CAL.run_calibration(rt, model_class="fast", force=True)
        self.assertTrue(entry["server_trunc"])
        self.assertEqual(entry["input_limit"], int(9000 * CAL.SERVER_TRUNC_SHRINK))

    def test_unsupported_transport(self):
        w = World()
        self.addCleanup(w.cleanup)
        rt = make_runtime(w.paths, RUN, cfg=w.cfg, clock=w.clock, transport=StubTransport(lambda p, r, s: ("stub", "")))
        self.assertIsNone(CAL.run_calibration(rt))


if __name__ == "__main__":
    unittest.main()
