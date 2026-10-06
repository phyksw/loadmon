# -*- coding: utf-8 -*-
"""teams.uia — 회사 PC(계정 있음) 위험 재현·회귀(M365 공식 문서 대조 ``.wf\\m365_research.json`` 의 팀즈 묶음).

  · M1  Teams 기본 = '기기 시작 시 백그라운드 실행, 닫아도 백그라운드에서 계속 실행'(보이는 창 없음). R-UIAEMPTY 는 사람이
        풀 수 있는 상태(사람·확정 ✘) — 다른 날 여러 번이어도 '불가(확정)'이 아니다. 하위 원인을 숫자로 남긴다
        (no_window · hidden · iconic · cloaked · offscreen · empty_tree · excluded → counts.empty_cause).
  · L10 보이는 창의 첫 판독이 0·소수 요소면(접근성 트리 지연) 한 번 더 읽는다(counts.retry_reads) — 전경 1회(--no-agent) 수집이
        늘 R-UIAEMPTY 로 끝나지 않게.
  · M10 같은 ms-teams 의 개인 계정 제품 창(제목 끝 'Microsoft Teams (free)'·'(무료)')은 읽지 않는다(제목만 본다).
        사용자가 지정하는 제외 패턴(teams.uia.excludeTitleRegex)은 설정 레지스트리 등재 뒤(handoff).
  · L8(팀즈 쪽) 다른 세션 사용자의 Teams 프로세스는 세지 않는다.
-RawFile JSON 스냅숏만(실제 창·UIA 0). 이름은 자리표시자."""
from __future__ import annotations

import unittest

from lm27.bundle import pcreg
from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp16 import uia

MAIN = "채팅 | 과제A 설계 | Microsoft Teams"


def _msgs(author: str, n: int, *, day: str = "2026년 9월 30일") -> list[dict]:
    return [uia.msg(f"{author}, {day} 오전 10:{i:02d}, 검토 항목 {i} 확인 부탁드립니다", y=200 + 45 * i) for i in range(n)]


class VerdictTest(unittest.TestCase):
    """M1 — 확정 판정에서 빠진다(계획 건너뜀·셀 blocked 는 그대로)."""

    def test_m1_background_teams_never_confirmed(self):
        hist = [{"date": d, "status": "fail", "reasons": ["R-UIAEMPTY"], "probe_sig": "s1"}
                for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04")]
        self.assertEqual(pcreg.verdict(hist, None, today="2026-10-04"), "불가(잠정)")
        self.assertFalse(rcmap.confirmable("R-UIAEMPTY"))
        self.assertEqual(rcmap.cell_status(3, ["R-UIAEMPTY"]), "blocked")              # 0건을 '성공'으로 숨기지 않음
        o = rcmap.stage_outcome(3, ["R-UIAEMPTY"], {})
        self.assertEqual((o["state"], o["reason"]), ("skipped", "R-UIAEMPTY"))          # 단계는 그대로 skipped

    def test_m1_elevated_still_confirmable(self):
        self.assertTrue(rcmap.confirmable("R-UIAELEV"))                                 # 관리자 권한 창은 구조(바뀌지 않음)


class _Base(CloneTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not uia.powershell_exe():
            raise unittest.SkipTest("powershell 없음")

    def run_snap(self, name: str, snap: dict, **kw) -> uia.Result:
        res = uia.run(self.clone, uia.write_json(self.clone.temp / f"{name}.json", snap), **kw)
        self.assertIsNotNone(res.status, res.stderr.decode("utf-8", "replace")[-2000:])
        self.assertEqual(sorted(set(res.reasons) - set(rcmap.REASONS)), [])
        return res


class EmptyCauseTest(_Base):
    """M1 — 하위 원인(사용자가 할 일을 고를 수 있게)."""

    def test_no_window_background_default(self):
        r = self.run_snap("bg", uia.snapshot(procs=3))
        self.assertEqual((r.rc, r.reasons), (3, ["R-UIAEMPTY"]))
        self.assertEqual((r.counts["no_window"], r.counts["empty_cause"]), (1, "no_window"))

    def test_hidden_and_minimized_causes(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), iconic=True),
                            uia.window("Microsoft Teams", [], visible=False))
        r = self.run_snap("causes", snap)
        self.assertEqual((r.rc, r.reasons), (3, ["R-UIAEMPTY"]))
        c = r.counts
        self.assertEqual((c["iconic"], c["hidden"], c["cloaked"], c["offscreen"]), (1, 1, 0, 0))
        self.assertEqual(c["empty_cause"], "iconic")                                    # 최소화를 풀면 읽힌다(가장 쉬운 조치)

    def test_cloaked_and_offscreen(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2), cloaked=True),
                            uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), on_screen=False))
        r = self.run_snap("cloak", snap)
        self.assertEqual((r.counts["cloaked"], r.counts["offscreen"], r.counts["empty_cause"]), (1, 1, "cloaked"))

    def test_visible_but_empty_tree_cause(self):
        r = self.run_snap("emptytree", uia.snapshot(uia.window(MAIN, [])))
        self.assertEqual((r.rc, r.reasons, r.counts["empty_cause"]), (3, ["R-UIAEMPTY"], "empty_tree"))

    def test_other_session_processes_not_counted(self):
        snap = uia.snapshot(procs=0)
        snap["procs_other_session"] = 2
        r = self.run_snap("othersess", snap)
        self.assertEqual((r.rc, r.reasons, r.counts["procs_other_session"]), (1, [], 2))


class RetryTest(_Base):
    """L10 — 첫 판독 0 → 한 번 더."""

    def test_first_read_empty_then_full(self):
        w = uia.window(MAIN, [])
        w["elements_seq"] = [[], _msgs("동료B", 3)]
        r = self.run_snap("retry", uia.snapshot(w))
        self.assertEqual(r.rc, 0, r.stderr.decode("utf-8", "replace")[-800:])
        self.assertEqual(len(r.records), 3)
        self.assertEqual((r.counts["retry_reads"], r.counts["retry_gain"]), (1, 1))
        self.assertEqual(r.reasons, [])

    def test_retry_still_empty_is_uiaempty(self):
        w = uia.window(MAIN, [])
        w["elements_seq"] = [[], []]
        r = self.run_snap("retry0", uia.snapshot(w))
        self.assertEqual((r.rc, r.reasons, r.counts["retry_reads"], r.counts["retry_gain"]), (3, ["R-UIAEMPTY"], 1, 0))

    def test_partial_tree_replaced_by_fuller_read(self):
        w = uia.window(MAIN, [])
        w["elements_seq"] = [_msgs("동료B", 1), _msgs("동료B", 4)]
        r = self.run_snap("retrypart", uia.snapshot(w))
        self.assertEqual((r.rc, len(r.records), r.counts["retry_gain"]), (0, 4, 1))


class PersonalWindowTest(_Base):
    """M10 — 개인 계정 제품 창은 읽지 않는다(창 제목만 보고 판단, 내용은 읽지 않음)."""

    def test_teams_free_window_not_read(self):
        snap = uia.snapshot(uia.window(MAIN, _msgs("동료B", 2)),
                            uia.window("채팅 | 가족방 | Microsoft Teams (free)", _msgs("가족", 2), rect=(200, 100, 800, 700)))
        r = self.run_snap("free", snap)
        self.assertEqual(r.rc, 0)
        self.assertEqual({x["author_name"] for x in r.records}, {"동료B"})
        self.assertEqual((r.counts["personal_title"], r.counts["windows"]), (1, 1))

    def test_only_personal_window_is_uiaempty_excluded(self):
        r = self.run_snap("freeonly", uia.snapshot(uia.window("채팅 | Microsoft Teams (무료)", _msgs("가족", 2))))
        self.assertEqual((r.rc, r.reasons, r.records, r.counts["empty_cause"]), (3, ["R-UIAEMPTY"], [], "excluded"))

    def test_window_distribution_counts(self):
        a = uia.window(MAIN, _msgs("동료B", 2))
        b = uia.window("김철수 | Microsoft Teams", _msgs("김철수", 2), rect=(200, 100, 800, 700))
        a["pid"], b["pid"] = 101, 202
        r = self.run_snap("pids", uia.snapshot(a, b))
        self.assertEqual((r.counts["pids"], r.counts["secondary"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
