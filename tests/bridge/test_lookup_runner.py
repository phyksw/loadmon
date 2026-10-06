# -*- coding: utf-8 -*-
"""WP-25 조회 단계 × L3 실행기(실제 단계 lookup_mail·lookup_teams·lookup_calendar, 스텁 전송·가상 시계 — 실 Edge 0):
B-T39(7일 가득 참 → 3·4일로 쪼개 다시, 첫 결과 커밋 안 함) · B-T40(구간 밖 행 버림, dropped.out_of_window) ·
B-T41(같은 날 unavailable 2회 → 다른 날 1회 → suspect 유지 → unavailable 14일, 수송 실패는 능력 판단 무관) ·
B-T49(업무 탭 없음 + 무라이선스 문구 → basic·web, 세 조회 같은 날 R-NOLIC, 같은 호출의 lookup_teams 전송 0 skipped,
분석 단계는 엄격 규칙으로 진행, BR-NOLIC) · B-T54(행 t 에 시각 → 날짜만, dropped.time_dropped)."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from lm27.bridge.env import CopilotEnv
from lm27.bridge.stages import REGISTRY
from lm27.util import events

from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp24.rig import Rig, act_rows, window_rows

DAY = 86400.0
MAIL, TEAMS = REGISTRY["lookup_mail"], REGISTRY["lookup_teams"]


def setUpModule():
    events.configure(mode="off")


def _full_rows(key, n=40):
    d0 = key.split(":")[1]
    return [{"t": d0, "d": "in", "s": f"업무 메일 {i}"} for i in range(n)]


class Split(unittest.TestCase):
    def test_T39_full_window_splits_3_4_and_parent_not_committed_as_answer(self):
        full_key = "lookup_mail:2026-09-01:2026-09-07"
        r = Rig(stages=[MAIL], rows=lambda key: _full_rows(key, 40) if key == full_key else
                [{"t": key.split(":")[1], "d": "out", "s": "회신"}])
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-07")]))
        res = r.run()["lookup_mail"]
        store = r.store("lookup_mail")
        self.assertEqual([c["key"] for c in store], [full_key, "lookup_mail:2026-09-01:2026-09-03",
                                                     "lookup_mail:2026-09-04:2026-09-07"])
        self.assertEqual((store[0]["by"], store[0]["why"]), ("rule", "split"))      # 첫 결과(가득 참)는 답으로 커밋 안 함
        self.assertNotIn("rows", store[0]["ans"])
        items = r.ai_out("lookup_mail")["items"]
        self.assertEqual(items["lookup_mail:2026-09-04:2026-09-07"]["ans"]["rows"][0]["t"], "2026-09-04")
        self.assertEqual((res["state"], res["items_ai"]), ("done", 2))
        self.assertEqual(check_stage_common(res), [])
        self.assertEqual(r.sends(), 3)

    def test_capped_when_one_day_still_full(self):
        r = Rig(stages=[MAIL], rows=lambda key: _full_rows(key, 40))
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-02", "2026-09-02")]))
        res = r.run()["lookup_mail"]
        c = r.store("lookup_mail")[0]
        self.assertTrue(c["ans"]["capped"])
        self.assertEqual(res["caps_hit"], {"lookup_rows": 1})


class Rows(unittest.TestCase):
    def test_T40_T54_rows_filtered_and_dates_only(self):
        phone = "-".join(("0" + "1" + "0", "5" * 4, "6" * 4))
        rows = [{"t": "2026-09-02 14:30", "d": "out", "s": "회의 자료 송부"},
                {"t": "2026-08-31", "d": "in", "s": "구간 밖"},
                {"t": "2026-09-03", "d": "in", "who": "partner.example", "rcv": "to", "s": "견적 회신 " + phone,
                 "th": "견적"}]
        r = Rig(stages=[MAIL], rows=lambda key: rows)
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-07")]))
        res = r.run()["lookup_mail"]
        got = r.ai_out("lookup_mail")["items"]["lookup_mail:2026-09-01:2026-09-07"]["ans"]["rows"]
        self.assertEqual([x["t"] for x in got], ["2026-09-02", "2026-09-03"])
        self.assertTrue(got[1]["who"].startswith("@"))                # 입수 정제 ③ 은 조회 행의 글도 거른다(B §9.1)
        self.assertEqual(got[1]["s"], "견적 회신 [전화]")
        self.assertFalse(any(phone.encode() in b for _p, b in r.tree_bytes()), "카나리아가 임시 트리 파일에 남음")
        self.assertEqual((res["dropped"]["time_dropped"], res["dropped"]["out_of_window"]), (1, 1))
        self.assertEqual(res["state"], "done")
        for p in r.transport.sent_texts:
            self.assertNotIn("시각은 쓰지 않습니다", p.split("[답 형식]")[1])     # 규칙은 머리말에(답 형식은 공통 골격)
            self.assertIn("날짜만 씁니다. 시각은 쓰지 않습니다.", p)


class Capability(unittest.TestCase):
    def test_T41_two_strike_across_days_transport_neutral(self):
        r = Rig(stages=[TEAMS], script={"lookup_teams": ["unavailable"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_teams", window_rows("lookup_teams", [("2026-09-01", "2026-09-02")]))
        res = r.run()["lookup_teams"]
        self.assertEqual((res["stop_kind"], res["reason"]), ("refused", "R-NOCONN"))
        self.assertEqual(r.rt.caps.state("lookup_teams"), "suspect")
        first = r.responder.count["lookup_teams"]
        self.assertEqual(first, 2)                                   # 거절·조회 불가 → 화법 바꿔 1회 더(B §8.1 rephrase)
        self.assertIn("기간의 업무 메시지를 검색해서, 찾은 것만", r.transport.sent_texts[-1])
        r.new_runtime()                                              # 같은 날 두 번째 호출 — 보내지 않는다
        res = r.run()["lookup_teams"]
        self.assertEqual((res["state"], res["reason"]), ("skipped", "capability_unavailable"))
        self.assertEqual(r.responder.count["lookup_teams"], first)
        self.assertEqual(r.rt.caps.confirmed_days("lookup_teams"), 1)
        r.clock.advance(DAY)                                         # 다른 날 1회
        r.responder.script = {"lookup_teams": ["phase:dead_session", "phase:dead_session", "unavailable"]}
        r.responder.count.clear()
        r.new_runtime()
        res = r.run()["lookup_teams"]
        self.assertEqual(res["stop_kind"], "fatal")                  # 수송 실패 2회 — 능력 판단 무관
        self.assertEqual(r.rt.caps.state("lookup_teams"), "suspect")
        r.new_runtime()
        res = r.run()["lookup_teams"]
        self.assertEqual(r.rt.caps.state("lookup_teams"), "unavailable")
        until = r.rt.caps.caps["lookup_teams"]["until"]
        self.assertEqual(until, (date.fromisoformat(r.rt.caps.today) + timedelta(days=14)).isoformat())
        self.assertEqual(r.rt.caps.state("lookup_mail"), "unknown")  # R-NOCONN 은 단계별

    def test_T49_nolic_account_level_and_strict_analysis(self):
        env = CopilotEnv(tier="unknown", work_toggle="absent", work_mode="unknown", web_grounding="unknown",
                         web_exposed=True)
        act = REGISTRY["speech_act"]
        r = Rig(stages=[MAIL, TEAMS, act], env=env, script={"lookup_mail": ["nolic", "nolic"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-07")]))
        r.write_ai_in("lookup_teams", window_rows("lookup_teams", [("2026-09-01", "2026-09-07")]))
        r.write_ai_in("speech_act", act_rows(3))
        res = r.run()
        self.assertEqual((res["lookup_mail"]["stop_kind"], res["lookup_mail"]["reason"]), ("refused", "R-NOLIC"))
        self.assertEqual((res["lookup_teams"]["state"], res["lookup_teams"]["reason"]),
                         ("skipped", "capability_unavailable"))
        self.assertEqual(r.responder.count["lookup_teams"], 0)
        self.assertEqual((r.rt.env.tier, r.rt.env.work_mode, r.rt.env.web_exposed), ("basic", "web", True))
        caps = r.rt.caps
        self.assertEqual({caps.state(s) for s in ("lookup_mail", "lookup_teams", "lookup_calendar")}, {"suspect"})
        self.assertEqual({tuple(caps.reasons(s)) for s in ("lookup_mail", "lookup_teams", "lookup_calendar")},
                         {("R-NOLIC",)})
        self.assertEqual(res["speech_act"]["state"], "done")
        self.assertTrue(res["speech_act"]["gate"]["web"]["exposed"])
        self.assertIn("BR-NOLIC", r.notified())


if __name__ == "__main__":
    unittest.main()
