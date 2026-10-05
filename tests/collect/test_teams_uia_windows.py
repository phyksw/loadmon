# -*- coding: utf-8 -*-
"""WP-16 teams.uia — 창 열거·가시 판정·권한 상승·상한·워치독·예산·채팅 목록 열 제외(CT §7.2 · §7.3 · CT-1 · CT-2).

-RawFile JSON 스냅숏(tests\\fixtures\\wp16\\uia.py)으로 창 상태를 흉내 낸다 — 실제 창·UIA 는 읽지 않는다.
"""
from __future__ import annotations

import unittest

from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp16 import uia

MAIN = "채팅 | 과제A 설계 | Microsoft Teams"


def _msgs(author: str, n: int, *, start_min: int = 0, day: str = "2026년 9월 30일") -> list[dict]:
    return [uia.msg(f"{author}, {day} 오전 10:{start_min + i:02d}, 과제A 검토 항목 {i} 확인 부탁드립니다", y=200 + 45 * i)
            for i in range(n)]


class _Base(CloneTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not uia.powershell_exe():
            raise unittest.SkipTest("powershell 없음")

    def run_snap(self, name: str, snap: dict, **kw) -> uia.Result:
        path = uia.write_json(self.clone.temp / f"{name}.json", snap)
        res = uia.run(self.clone, path, **kw)
        self.assertIsNotNone(res.status, res.stderr.decode("utf-8", "replace")[-2000:])
        self.assertEqual(res.status["rc"], res.rc)
        self.assertEqual(sorted(set(res.reasons) - set(rcmap.REASONS)), [])
        self.assertIn("_cursor", res.lines[-1], "막혀도 마지막 줄은 _cursor")
        return res


class TestWindowEnumeration(_Base):
    def test_ct1_popout_windows_only(self):
        """CT-1: 주 창은 최소화, 팝아웃 채팅 창 2개만 보임 → 모든 최상위 창 열거로 두 방 모두 수집, rc 0."""
        snap = uia.snapshot(
            uia.window(MAIN, _msgs("동료B", 3), iconic=True),
            uia.window("김철수 | Microsoft Teams", [
                uia.el("김철수"), uia.sep("오늘"),
                uia.msg("김철수, 오전 8:10, 과제B 시험계획 검토 부탁드립니다", x=230, w=740),
                uia.mine("오전 8:12, 넵 확인했습니다", win_w=800, win_x=200, w=300),
            ], rect=(200, 100, 800, 700)),
            uia.window("과제C 양산 | Microsoft Teams", [
                uia.button("참가자 4명"), uia.sep("어제"),
                uia.msg("동료C, 오후 4:40, 과제C 양산검토 결과 공유드립니다", x=1030, w=740),
            ], rect=(1000, 100, 800, 700)),
        )
        r = self.run_snap("ct1", snap)
        self.assertEqual(r.rc, 0)
        c = r.counts
        self.assertEqual((c["windows"], c["visible"], c["read"]), (3, 2, 2))
        rooms = {x["chat_id"] for x in r.records}
        self.assertEqual(rooms, {"uia:김철수", "uia:과제c 양산"})
        self.assertEqual(uia.by_body(r, "과제A 검토"), [], "최소화 창은 읽지 않는다(가시일 때만)")
        mine = uia.by_body(r, "넵 확인했습니다")[0]
        self.assertIs(mine["is_me"], True)
        self.assertEqual(mine["ts_utc"], "2026-09-30T23:12:00Z")
        grp = uia.by_body(r, "양산검토")[0]
        self.assertEqual((grp["chat_type"], grp["n_participants"], grp["chat_title"]), ("group", 4, "과제C 양산"))
        self.assertEqual(grp["ts_utc"], "2026-09-30T07:40:00Z")       # '어제' 구분선 → 2026-09-30 16:40 KST

    def test_ct2_minimized_and_hidden_is_blocked_not_zero(self):
        """CT-2: 창이 모두 최소화·숨김 → R-UIAEMPTY, rc 3(막힌 사유 — 0건을 '성공'으로 숨기지 않음)."""
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), iconic=True),
                            uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), visible=False))
        r = self.run_snap("ct2", snap)
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.reasons, ["R-UIAEMPTY"])
        self.assertEqual(r.records, [])
        self.assertEqual(rcmap.cell_status(r.rc, r.reasons, {"n": 0}), "blocked")

    def test_tray_only_process_is_uiaempty(self):
        r = self.run_snap("tray", uia.snapshot(procs=1))
        self.assertEqual((r.rc, r.reasons), (3, ["R-UIAEMPTY"]))

    def test_no_teams_process_is_rc1(self):
        r = self.run_snap("noproc", uia.snapshot(procs=0))
        self.assertEqual((r.rc, r.reasons, r.records), (1, [], []))

    def test_offscreen_and_cloaked_are_not_visible(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), on_screen=False),
                            uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), cloaked=True))
        r = self.run_snap("offscreen", snap)
        self.assertEqual((r.rc, r.reasons, r.counts["visible"]), (3, ["R-UIAEMPTY"], 0))

    def test_visible_but_empty_uia_tree(self):
        r = self.run_snap("empty", uia.snapshot(uia.window(MAIN, [])))
        self.assertEqual((r.rc, r.reasons, r.counts["empty"]), (3, ["R-UIAEMPTY"], 1))

    def test_visible_only_off_reads_minimized(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), iconic=True))
        r = self.run_snap("visoff", snap, cfg={"teams.uia.visibleOnly": False})
        self.assertEqual(r.rc, 0)
        self.assertEqual(len(r.records), 2)

    def test_rendered_zero_message_lines_is_rc4(self):
        snap = uia.snapshot(uia.window(MAIN, [uia.el("과제A 설계"), uia.button("참가자 5명"), uia.el("메시지 입력")]))
        r = self.run_snap("nolines", snap)
        self.assertEqual((r.rc, r.records, r.counts["time_lines"]), (4, [], 0))


class TestElevationCapWatchdog(_Base):
    def test_elevated_only_window(self):
        r = self.run_snap("elev", uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), elevated=True)))
        self.assertEqual((r.rc, r.reasons, r.counts["elevated"]), (3, ["R-UIAELEV"], 1))
        self.assertEqual(rcmap.cell_status(r.rc, r.reasons, {"n": 0}), "blocked")

    def test_elevated_plus_normal_window(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), elevated=True),
                            uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), rect=(200, 100, 800, 700)))
        r = self.run_snap("elev2", snap)
        self.assertEqual(r.rc, 0)
        self.assertIn("R-UIAELEV", r.reasons)
        self.assertEqual({x["author_name"] for x in r.records}, {"김철수"})

    def test_element_cap_is_partial(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 40) + _msgs("김철수", 80, start_min=0, day="2026년 9월 29일")
                                       + [uia.el(f"빈 요소 {i}") for i in range(30)]))
        r = self.run_snap("cap", snap, cfg={"teams.uia.maxElements": 100})
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.reasons, ["R-CAP"])
        self.assertEqual((r.counts["capped"], r.counts["elements"]), (1, 100))
        self.assertEqual(rcmap.translate_cell(r.rc, r.reasons, {"n": len(r.records), "cap_hit": True})["status"],
                         "partial")

    def test_window_watchdog_skips_slow_window(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), read_ms=2500),
                            uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), rect=(200, 100, 800, 700)))
        r = self.run_snap("wd", snap, cfg={"teams.uia.windowWatchdogSec": 1})
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.reasons, ["R-CAP"])
        self.assertEqual(r.counts["timeout"], 1)
        self.assertEqual({x["author_name"] for x in r.records}, {"김철수"})

    def test_only_window_hangs(self):
        r = self.run_snap("hang", uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), hang=True)))
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.reasons, ["R-CAP", "R-TRANSPORT"])
        self.assertEqual(rcmap.cell_status(r.rc, r.reasons, {"n": 0}), "transport_fail")

    def test_read_error_is_transport(self):
        r = self.run_snap("err", uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), error="ElementNotAvailableException")))
        self.assertEqual((r.rc, r.reasons, r.counts["errors"]), (3, ["R-TRANSPORT"], 1))

    def test_budget_stops_and_keeps_what_was_read(self):
        """예산(teams.uia.budgetSec) 소진 — 읽은 창은 내고 rc 0 + R-BUDGET(partial), 남은 창은 읽지 않는다."""
        snap = uia.snapshot(
            uia.window(MAIN, _msgs("동료B", 2)),
            uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), read_ms=20000, rect=(200, 100, 800, 700)),
            uia.window("동료D | Microsoft Teams", _msgs("동료D", 2), rect=(300, 100, 800, 700)))
        r = self.run_snap("budget", snap, cfg={"teams.uia.budgetSec": 5}, timeout=120)
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.reasons, ["R-BUDGET"])
        self.assertEqual(r.counts["budget_hit"], 1)
        self.assertEqual({x["author_name"] for x in r.records}, {"동료B"})
        cell = rcmap.translate_cell(r.rc, r.reasons, {"n": 2, "budget_hit": True})
        self.assertEqual(cell["status"], "partial")

    def test_out_of_range_cfg_falls_back_to_default(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 3)))
        r = self.run_snap("cfgbad", snap, cfg={"teams.uia.maxElements": 2, "teams.uia.budgetSec": "x"})
        self.assertEqual((r.rc, r.reasons, len(r.records)), (0, [], 3))


class TestChatListColumn(_Base):
    """채팅 목록 열 제외(LM24 계승 + LM22 회귀 가드) · 안전 밸브 · -KeepChatList."""

    @staticmethod
    def _main() -> dict:
        previews = [uia.preview(f"동료{c} 오후 {i + 1}:0{i} 미리보기 내용 {i}", y=100 + 70 * i) for i, c in enumerate("BCDE")]
        body = [uia.button("참가자 5명"), uia.sep("오늘"),
                uia.msg("김철수, 오전 8:30, 과제A 설계 검토 부탁드립니다", y=200),
                uia.msg("동료B, 오전 8:40, 과제A 일정 공유드립니다", y=260),
                uia.mine("오전 8:45, 넵 확인했습니다", y=320)]
        return uia.window(MAIN, previews + body)

    def test_list_column_excluded(self):
        r = self.run_snap("listcol", uia.snapshot(self._main()))
        self.assertEqual(r.rc, 0)
        self.assertEqual(sorted(x["body_text"] for x in r.records),
                         sorted(["과제A 설계 검토 부탁드립니다", "과제A 일정 공유드립니다", "넵 확인했습니다"]))
        self.assertEqual(r.counts["list_skipped"], 4)
        self.assertEqual(r.counts["list_restored"], 0)

    def test_keep_chat_list_reads_previews(self):
        r = self.run_snap("listkeep", uia.snapshot(self._main()), args=("-KeepChatList",))
        self.assertEqual(len(r.records), 7)
        self.assertEqual(r.counts["list_skipped"], 0)

    def test_safety_valve_restores_misjudged_column(self):
        """LM22 회귀: 메시지 항목이 왼쪽 좁은 열에 몰려 목록으로 오인되면, 남은 줄 시각 0 → 되돌려 다시 읽는다."""
        narrow = [uia.el(f"김철수, 2026년 9월 30일 오후 3:{i:02d}, 과제A 회로 검토 {i} 부탁드립니다", "ListItem",
                         (100, 200 + 50 * i, 500, 40)) for i in range(5)]
        wide = [uia.el("메시지 입력", "ListItem", (100, 820, 900, 40))]
        r = self.run_snap("valve", uia.snapshot(uia.window(MAIN, narrow + wide)))
        self.assertEqual(r.rc, 0)
        self.assertEqual(len(r.records), 5)
        self.assertEqual(r.counts["list_restored"], 5)

    def test_wide_window_message_column_not_misjudged(self):
        """LM22 사고 재현 모양: 창 1920 에서 메시지 열 x 452~1052 → 오른쪽 끝이 45% 를 넘으므로 목록 아님."""
        msgs = [uia.el(f"김철수, 2026년 9월 30일 오후 4:{i:02d}, 과제A 시험 {i} 결과 공유드립니다", "ListItem",
                       (452, 200 + 50 * i, 600, 40)) for i in range(6)]
        wide = [uia.el("메시지 입력", "ListItem", (452, 900, 1400, 40))]
        r = self.run_snap("lm22", uia.snapshot(uia.window(MAIN, msgs + wide, rect=(0, 0, 1920, 1040))))
        self.assertEqual(len(r.records), 6)
        self.assertEqual((r.counts["list_skipped"], r.counts["list_restored"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
