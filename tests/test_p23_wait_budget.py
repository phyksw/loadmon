# -*- coding: utf-8 -*-
r"""tests\test_p23_wait_budget.py — 한 실행의 Copilot 쉬는 시간 합계(copilotAuto.runWaitMaxSec, 기본 5분 — LM28 사용자 요청
'10분은 길다 — 3~5분으로, 분석이 길면 업무에도 지장').

· 기록(<프로필>.wait.json): 실행 표식 없음 → 무한·기록 안 함 · 쌓기 · 다른 실행이면 새로 · 0 → 남은 0 · 글자·음수 → 300 ·
  깨진 파일 → 0.
· judge.copilot_send: 사다리 1·2·2분(합계 300초) 뒤 hard · 뒤 단계 프로세스는 남은 몫만 · 다 쓰면 쉬지 않고 hard(한 줄) ·
  사용량 제한은 남은 60초면 60초, 10초면 쉬지 않고 hard(실행 멈춤) · 지난 실행 기록은 5분 중 남은 시간(합계 안)만 · 0 이면 바로 hard.
· agentic(니즈 후보 발굴)·flow 의 쉬기(judge.wait_room·note_waited) · run.py 재시도 대기(합계 안 · 바닥 15초) · 두 설정 파일의 키.
실제 Copilot·Edge·대기는 쓰지 않는다 — _transport·_cooldown·time.sleep 은 가짜. 임시 폴더만 쓴다.
"""
import contextlib
import io
import json
import os
import tempfile
import time
import types
import unittest
from unittest import mock

import _boot  # noqa: F401  — 경로 등록
import agentic  # noqa: E402
import copilot_auto as ca  # noqa: E402
import details  # noqa: E402
import flow  # noqa: E402
import judge  # noqa: E402
import run as R  # noqa: E402
import test_p13_flow as p13  # noqa: E402
import test_p22_throttle as p22  # noqa: E402

THROTTLED, COPILOT_ERR, OK_REPLY = p22.THROTTLED, p22.COPILOT_ERR, p22.OK_REPLY
BUDGET_LINE = "이번 실행에서 Copilot 을 기다리며 쉬는 시간(모두 5분 — copilotAuto.runWaitMaxSec)을 다 썼습니다"
INF = float("inf")


# ── 1) 기록 — <프로필>.wait.json ─────────────────────────────────────────────────────
class Ledger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t23l_")
        self.cfg = p22._cfg(self._tmp.name)
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        os.environ.pop("LM_RUN_ID", None)
        st.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def path(self):
        return ca._side_path(self.cfg, ca.WAIT_FILE)

    def test_no_run_id(self):
        self.assertEqual(ca.run_wait_left(self.cfg), INF)                       # 단계를 따로 돌림 — 실행 합계 상한 없음
        self.assertFalse(ca.add_run_wait(60, self.cfg))
        self.assertFalse(os.path.exists(self.path()))
        self.assertEqual(ca.run_waited(self.cfg), 0.0)

    def test_accumulate_and_other_run(self):
        os.environ["LM_RUN_ID"] = "run-A"
        self.assertEqual(ca.run_wait_left(self.cfg), 300.0)
        self.assertTrue(ca.add_run_wait(60, self.cfg))
        self.assertTrue(ca.add_run_wait(120.0, self.cfg))
        for bad in (0, -5, "글자", None):
            self.assertFalse(ca.add_run_wait(bad, self.cfg), bad)
        self.assertEqual((ca.run_waited(self.cfg), ca.run_wait_left(self.cfg)), (180.0, 120.0))
        ca.add_run_wait(500, self.cfg)
        self.assertEqual(ca.run_wait_left(self.cfg), 0.0)                       # 음수로 내려가지 않는다
        os.environ["LM_RUN_ID"] = "run-B"                                       # 다음 실행 — 지난 실행의 합계는 쓰지 않는다
        self.assertEqual((ca.run_waited(self.cfg), ca.run_wait_left(self.cfg)), (0.0, 300.0))
        ca.add_run_wait(30, self.cfg)
        with open(self.path(), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["run"], "run-B")
        self.assertEqual(ca.run_waited(self.cfg), 30.0)

    def test_setting_values(self):
        os.environ["LM_RUN_ID"] = "run-A"
        for v, want in ((0, 0.0), ("0", 0.0), (90, 90.0), ("abc", 300.0), (-5, 300.0), (None, 300.0), ("", 300.0),
                        ("inf", 300.0)):
            self.assertEqual(ca.run_wait_max(dict(self.cfg, runWaitMaxSec=v)), want, v)
        self.assertEqual(ca.run_wait_left(dict(self.cfg, runWaitMaxSec=0)), 0.0)
        self.assertEqual(ca.run_wait_left(dict(self.cfg, runWaitMaxSec="abc")), 300.0)
        self.assertEqual(ca.DEFAULTS["runWaitMaxSec"], 300)
        self.assertIn("runWaitMaxSec", ca.KEEP_FALSY)
        p = os.path.join(self._tmp.name, "config.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"copilotAuto": {"runWaitMaxSec": 0}}, f)
        self.assertEqual(ca.load_cfg(p)["runWaitMaxSec"], 0)                    # 0 = 쉬지 않음 — 기본값으로 바뀌지 않는다

    def test_corrupt_file(self):
        os.environ["LM_RUN_ID"] = "run-A"
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write("{깨짐")
        self.assertEqual((ca.run_waited(self.cfg), ca.run_wait_left(self.cfg)), (0.0, 300.0))
        self.assertTrue(ca.add_run_wait(60, self.cfg))                          # 깨진 기록은 0 부터
        self.assertEqual(ca.run_waited(self.cfg), 60.0)
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump(["목록"], f)
        self.assertEqual(ca.run_waited(self.cfg), 0.0)
        self.assertTrue(ca.add_run_wait(10, self.cfg))
        self.assertEqual(ca.run_waited(self.cfg), 10.0)


# ── 2) judge.copilot_send — 한 실행의 쉬는 시간 합계 ─────────────────────────────────────────
class JudgeBudget(p22._Send):
    def setUp(self):
        super().setUp()
        os.environ["LM_RUN_ID"] = "run-A"

    def write_record(self, age, run="run-Z"):
        now = time.time()
        with open(ca._side_path(self.cfg, ca.THROTTLE_FILE), "w", encoding="utf-8") as f:
            json.dump({"t": now - age, "n": 2, "hard": True, "hard_t": now - age, "run": run, "kind": "throttle"}, f)

    def test_constants(self):
        self.assertEqual((judge.COOLDOWN_SEC, judge.COOLDOWN_CAP_SEC, judge.HARD_RECENT_SEC), ((60, 120, 120), 300, 300))
        self.assertLessEqual(max(judge.COOLDOWN_SEC + (judge.THROTTLE_WAIT_SEC,)), 120)    # 한 번 쉬기는 2분 이하
        self.assertEqual([judge._fmt_wait(s) for s in (60, 120.0, 90, 30, 239.97, 45.4)],
                         ["1분(60초)", "2분(120초)", "90초", "30초", "4분(240초)", "45초"])

    def test_ladder_uses_whole_budget_then_hard(self):
        self.replies = [dict(COPILOT_ERR)]
        res = self.send()
        self.assertEqual(self.cool, [60.0, 120.0, 120.0])
        self.assertEqual(len(self.sent), 4)
        self.assertTrue(res.get("hard"))
        self.assertEqual((ca.run_waited(), ca.run_wait_left()), (300.0, 0.0))
        out = self.out.getvalue()
        self.assertIn("1분(60초) 쉬고 새로 고친 뒤 같은 묶음을 다시 보냅니다 (1/3)", out)
        self.assertIn("2분(120초) 쉬고 새로 고친 뒤 같은 묶음을 다시 보냅니다 (3/3)", out)
        self.assertIn("Copilot 이 3번 쉬고 다시 보내도 막혔습니다", out)     # 사다리 끝 — 합계 줄이 아니다
        self.assertNotIn(BUDGET_LINE, out)

    def test_next_process_gets_only_the_rest(self):
        self.replies = [dict(COPILOT_ERR), dict(OK_REPLY)]                     # 판정 프로세스 — 1분 쉬고 성공
        self.assertTrue(self.send()["ok"])
        self.assertEqual(self.cool, [60.0])
        ca.add_run_wait(150)                                                    # 그 사이 다른 단계가 2분 30초 쉼 → 남은 90초
        self.new_process()                                                      # 뒤 단계 프로세스(같은 LM_RUN_ID)
        self.cool.clear()
        self.replies = [dict(COPILOT_ERR)]
        res = self.send("refine1")
        self.assertEqual(self.cool, [60.0, 30.0])                               # 남은 몫만 — 세 번째는 쉬지 않고 hard
        self.assertTrue(res.get("hard"))
        self.assertEqual(ca.run_waited(), 300.0)
        out = self.out.getvalue()
        self.assertIn("30초 쉬고 새로 고친 뒤 같은 묶음을 다시 보냅니다 (2/3)", out)
        self.assertEqual(out.count(BUDGET_LINE), 1)
        self.assertNotIn("모델로 보냅니다", out)                                # 보내지 않을 거면 대체 모델 안내도 없다

    def test_spent_budget_goes_hard_without_rest(self):
        ca.add_run_wait(300)
        self.replies = [dict(COPILOT_ERR)]
        res = self.send()
        self.assertEqual((self.cool, len(self.sent)), ([], 1))
        self.assertTrue(res.get("hard"))
        self.assertTrue(details.explain_failure(res)[2])                        # 호출자가 남은 묶음을 접는다
        self.assertEqual(judge._abort_kind_of(res), "throttle")
        self.assertTrue(self.send("chunk2").get("hard"))                        # 같은 프로세스의 다음 묶음 — 줄을 또 찍지 않는다
        out = self.out.getvalue()
        self.assertEqual(out.count(BUDGET_LINE), 1)
        self.assertIn("이 단계의 남은 묶음은 보내지 않고 여기까지의 결과를 지킵니다(1~2시간 뒤 [재분석만])", out)
        self.assertNotIn("쉬고 다시 보내도 막혔습니다", out)
        self.assertNotIn("여전히 막혀 있습니다", out)
        self.assertFalse(ca.run_stopped())                                      # 일시 오류의 hard — 실행 표식은 없다

    def test_throttle_rests_only_what_is_left(self):
        ca.add_run_wait(240)
        self.replies = [dict(THROTTLED), dict(OK_REPLY)]
        res = self.send()
        self.assertTrue(res["ok"])
        self.assertEqual(self.cool, [60.0])
        self.assertIn("1분(60초) 쉬고 새로 고친 뒤 같은 묶음을 한 번만 다시 보냅니다", self.out.getvalue())
        self.assertEqual(ca.run_wait_left(), 0.0)

    def test_throttle_with_little_left_stops_run(self):
        ca.add_run_wait(290)
        self.replies = [dict(THROTTLED)]
        res = self.send()
        self.assertEqual((self.cool, len(self.sent)), ([], 1))
        self.assertTrue(res.get("hard"))
        self.assertTrue(ca.run_stopped())                                       # 사용량 제한 — 이번 실행의 AI 단계를 멈춘다
        out = self.out.getvalue()
        self.assertEqual(out.count(BUDGET_LINE), 1)
        self.assertNotIn("계속 막고 있습니다", out)                              # 사실과 다른 둘째 줄 없음
        self.new_process()
        r = self.send("refine1")                                                # 뒤 단계 — 보내지도 쉬지도 않는다
        self.assertEqual((r.get("run_stop"), len(self.sent), self.cool), (True, 1, []))

    def test_rerun_rests_rest_of_five_minutes(self):
        self.write_record(60)                                                   # 지난 실행이 1분 전에 멈췄다
        self.replies = [dict(OK_REPLY)]
        self.assertTrue(self.send()["ok"])
        self.assertEqual(len(self.cool), 1)
        self.assertAlmostEqual(self.cool[0], 240.0, delta=3.0)                  # 5분 중 남은 4분만
        self.assertAlmostEqual(ca.run_waited(), 240.0, delta=3.0)               # 새 실행의 합계에 든다
        self.assertIn("4분(240초) 쉬고 한 번 보내 봅니다", self.out.getvalue())

    def test_rerun_rest_is_bounded_by_budget(self):
        self.write_record(60)
        ca.add_run_wait(200)
        self.replies = [dict(OK_REPLY)]
        self.assertTrue(self.send()["ok"])
        self.assertEqual(self.cool, [100.0])                                    # 남은 합계 100초 안
        self.assertIn("100초 쉬고 한 번 보내 봅니다", self.out.getvalue())

    def test_rerun_with_spent_budget_sends_once_then_hard(self):
        self.write_record(60)
        ca.add_run_wait(300)
        self.replies = [dict(COPILOT_ERR)]
        res = self.send()
        self.assertEqual((self.cool, len(self.sent)), ([], 1))
        self.assertTrue(res.get("hard"))
        self.assertIn("이번 실행에서 쉴 수 있는 시간을 다 써 쉬지 않고 한 번만 보내 봅니다(그래도 막히면 이 단계도 멈춥니다)",
                      self.out.getvalue())

    def test_old_record_ignored(self):
        self.write_record(400)                                                  # 5분이 지난 기록 — 쉬지 않는다
        self.replies = [dict(OK_REPLY)]
        self.assertTrue(self.send()["ok"])
        self.assertEqual(self.cool, [])

    def test_zero_transient_goes_hard_at_once(self):
        self.cfg["runWaitMaxSec"] = 0
        self.replies = [dict(COPILOT_ERR)]
        res = self.send()
        self.assertEqual((self.cool, len(self.sent), bool(res.get("hard"))), ([], 1, True))
        self.assertIn("이번 실행은 Copilot 을 기다리며 쉬지 않게 설정돼 있습니다(copilotAuto.runWaitMaxSec 0)",
                      self.out.getvalue())

    def test_zero_throttle_stops_run_at_once(self):
        self.cfg["runWaitMaxSec"] = 0
        self.replies = [dict(THROTTLED)]
        res = self.send()
        self.assertEqual((self.cool, len(self.sent), bool(res.get("hard"))), ([], 1, True))
        self.assertTrue(ca.run_stopped())

    def test_without_run_id_only_process_cap(self):
        os.environ.pop("LM_RUN_ID")
        self.cfg["runWaitMaxSec"] = 0                                           # 실행 표식이 없으면 실행 합계는 보지 않는다
        self.replies = [dict(COPILOT_ERR)]
        self.assertTrue(self.send().get("hard"))
        self.assertEqual(self.cool, [60.0, 120.0, 120.0])                       # 프로세스 합계 5분 안
        self.assertFalse(os.path.exists(ca._side_path(self.cfg, ca.WAIT_FILE)))

    def test_helpers_for_other_modules(self):
        ca.add_run_wait(250)
        self.assertEqual(judge.wait_room(90), 50.0)
        judge.note_waited(50.0)
        self.assertEqual((judge._COOLED[0], ca.run_waited(), judge.wait_room(90)), (50.0, 300.0, 0.0))
        for mod in (agentic, flow):
            self.assertEqual(mod._run_room(judge, 90.0), 0.0, mod.__name__)    # 다 썼다 — 쉬지 않고 바로 한 번 더
            stub = types.SimpleNamespace()                                      # 시험 가짜·옛 판 judge — 바라는 그대로
            self.assertEqual(mod._run_room(stub, 90.0), 90.0, mod.__name__)
            mod._note_wait(stub, 90.0)                                          # 없으면 아무것도 하지 않는다
        os.environ["LM_RUN_ID"] = "run-B"
        self.assertEqual((agentic._run_room(judge, 90.0), flow._run_room(judge, 0.4)), (90.0, 0.0))


# ── 3) agentic(니즈 후보 발굴)·flow — 일시 오류 뒤 쉬기도 실행 합계 안 ───────────────────────────────
AG_ROWS = [p13._mm_row("프로젝트A", "설계 검토", 2.0), p13._mm_row("프로젝트A", "회로 시뮬레이션", 1.5),
           p13._mm_row("프로젝트B", "시험 보고", 1.0, kind="사무")]


def _ag_sigs():
    out = []
    for i, r in enumerate(AG_ROWS):
        out += p13._sigs(r["Level 2"], r["Level 3"], day0=3 + i * 4)
    return out


class StageRest(p13._Env):
    def setUp(self):
        super().setUp()
        self.pcfg = p22._cfg(self.tmp)
        pt = mock.patch.object(ca, "load_cfg", lambda *a, **k: dict(self.pcfg))   # 합계 기록은 임시 폴더에
        pt.start()
        self._patches.append(pt)
        pa = mock.patch.object(agentic, "ROOT", self.tmp)
        pa.start()
        self._patches.append(pa)
        os.environ["LM_RUN_ID"] = "run-A"

    def test_agentic_rest_bounded(self):
        self.data(AG_ROWS, _ag_sigs())
        ca.add_run_wait(250)
        seq = [{"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류"}]
        self.reply = lambda p, n: seq.pop(0) if seq else p13._ok(
            {"new": [{"name": "보고서 초안 자동 작성", "logic": "시험 결과 → 보고서 초안", "reason": "매주 반복", "work": ["#3"]}]})
        rc, js, out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual([n for n, _p in self.calls], [f"{self.TAG}-ag1", f"{self.TAG}-ag1-c"])
        self.assertEqual(self.sleeps, [50.0])                                   # 90초 대신 남은 50초
        self.assertEqual(ca.run_waited(), 300.0)
        self.assertIn("50초 쉬고 새 채팅에서 같은 묶음을 한 번 더 보냅니다", out)

    def test_flow_spent_budget_resends_without_rest(self):
        p13.FlowRuns._data(self)
        ca.add_run_wait(300)
        seq = [{"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류"}]
        self.reply = lambda p, n: seq.pop(0) if seq else p13.FlowRuns._flows(p)
        rc, js, out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 0, js)
        self.assertEqual([n for n, _p in self.calls], [f"{self.TAG}-wf1", f"{self.TAG}-wf1-c"])   # 한 번 더 보내기는 그대로
        self.assertEqual(self.sleeps, [])
        self.assertIn("쉬지 않고 새 채팅에서 같은 묶음을 한 번 더 보냅니다(이번 실행에서 쉴 수 있는 시간을 다 썼습니다)", out)


# ── 4) run.py — 재시도 대기도 실행 합계 안(바닥 15초) ─────────────────────────────────────────
class RetryWait(unittest.TestCase):
    def stage(self, script, left):
        cmds, sleeps, added = [], [], []

        def cap(cmd, env):
            cmds.append(cmd)
            R.LAST_JSON.clear()
            return (1, "Copilot 일시 오류") if len(cmds) == 1 else (0, "")
        out = io.StringIO()
        with mock.patch.object(R, "_run_capture", cap), mock.patch.object(R.time, "sleep", sleeps.append), \
                mock.patch.object(R, "_RUN_STOPPED", lambda: False), \
                mock.patch.object(R, "_RUN_WAIT_LEFT", lambda: left), \
                mock.patch.object(R, "_ADD_RUN_WAIT", added.append), contextlib.redirect_stdout(out):
            rc, _note = R.run_ai_stage(script, "2026-01-01", "2026-01-31")
        self.assertEqual((rc, len(cmds)), (0, 2))
        return sleeps, added, out.getvalue()

    def test_bounded_with_floor(self):
        sleeps, added, out = self.stage("agentic.py", 50.0)
        self.assertEqual((sleeps, added), ([50], [50]))
        self.assertIn("50초 뒤 1회 재시도합니다 (이번 실행의 Copilot 쉬는 시간 합계 안", out)
        sleeps, added, _out = self.stage("flow.py", 0.0)
        self.assertEqual((sleeps, added), ([15], [15]))                         # 바닥 15초
        sleeps, added, out = self.stage("flow.py", INF)                         # 실행 표식 없음 — 예전 그대로
        self.assertEqual((sleeps, added), ([120], [120]))
        self.assertNotIn("합계 안", out)
        sleeps, added, _out = self.stage("refine.py", 0.0)
        self.assertEqual((sleeps, added), ([15], []))                           # 15초 대기는 줄이지도 적지도 않는다

    def test_unreadable_total_keeps_wait(self):
        def boom():
            raise OSError("못 읽음")
        with mock.patch.object(R, "_RUN_WAIT_LEFT", boom):
            self.assertEqual(R.retry_wait_sec(120), 120)
        self.assertEqual(R.retry_wait_sec(15), 15)


# ── 5) 설정 — 두 설정 파일에 키와 설명 ─────────────────────────────────────────────────
class ConfigKeys(unittest.TestCase):
    def test_both_files(self):
        for fn in ("config.default.json", "config.json"):
            with open(os.path.join(_boot.ROOT, "config", fn), encoding="utf-8-sig") as f:
                o = json.load(f)
            self.assertEqual(o["copilotAuto"]["runWaitMaxSec"], 300, fn)
            desc = o["_copilotAuto_옵션_설명"]
            self.assertIn("0 이면 쉬지 않는다", desc["runWaitMaxSec"], fn)
            self.assertIn("1·2·2분", desc["throttleWaitSec"], fn)
            self.assertNotIn("2·5·10", desc["throttleWaitSec"], fn)


if __name__ == "__main__":
    unittest.main()
