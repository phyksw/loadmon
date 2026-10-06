# -*- coding: utf-8 -*-
"""WP-32 AI 단계 — 브리지 호출 지점(B §2.3: speech_act · task_label · 워크플로우 3단계 · review_text)과 순서, 문(--no-ai ·
Copilot 역할 · bridge.mode · bridge.stages), fail-soft(일부·실패 → partial, 규칙 라벨로 끝까지 — rc 2, current 교체),
T-H16(--no-ai 면 저장된 AI 답을 쓰지 않음), 기본 브리지 호출(process_bridge — 가짜 자식 프로세스, 이벤트 다시 내기)."""
import io
import json
import unittest

from lm27.pipeline import analyze as A
from lm27.util import events, fsx
from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp32 import world as W

OPEN = {"hier.copilot.requireCodenameReview": False}      # 빈 레지스트리에서도 코파일럿 분류 단계를 연다(시험)


class _Base(unittest.TestCase):
    def setUp(self):
        events.configure(mode="off")
        self.addCleanup(events.configure, mode="text")
        self.w = W.World()
        self.addCleanup(self.w.remove)
        self.w.put(W.rows())
        self.w.keyring()

    def by(self) -> dict:
        return {s["id"]: s for s in self.w.status()["stages"]}


class CallOrderTest(_Base):
    def test_points_and_order(self):
        fb = W.FakeBridge()
        rc = self.w.analyze(self.w.cfg(OPEN), ai=True, bridge=fb)
        self.assertEqual(rc, 0)
        calls = fb.calls
        stages = [c[0] for c in calls]
        self.assertEqual([s for s in stages if s != "normalize"], ["ai:task_label", "ai:workflow", "ai:review_text"])
        if "normalize" in stages:
            self.assertEqual(stages[0], "normalize", "화행 회색 지대는 정규화 직후(호출 지점 2)")
            self.assertEqual(calls[0][1], ("speech_act",))
        names = {c[0]: c[1] for c in calls}
        self.assertEqual(names["ai:task_label"], ("task_label",))
        self.assertEqual(names["ai:workflow"], ("workflow_label", "agentic_match", "subagent_review"))
        self.assertEqual(names["ai:review_text"], ("review_text",))
        self.assertTrue(all(c[2] == self.w.last for c in calls), "브리지 run_id = 분석 run_id")
        by = self.by()
        for sid in ("ai:task_label", "ai:workflow", "ai:review_text"):
            self.assertEqual(by[sid]["state"], "done", sid)
            self.assertEqual(check_stage_common(by[sid]), [])
        self.assertGreater(by["classify"]["counts"]["task_label_items"], 0)
        for st in ("task_label", "workflow_label", "agentic_match", "subagent_review", "review_text"):
            self.assertTrue(self.w.paths.ai_in(st).is_file(), f"ai_in {st}")
        self.assertEqual(by["mining"]["counts"]["written"], 1)
        self.assertTrue(self.w.status()["current"])

    def test_no_items_skips_bridge(self):
        """검토 선행을 켰는데 빈 레지스트리·코드네임 검토 전 = 코파일럿 분류 안 열림(T-H05) → task_label 물을 항목 0 →
        그 단계만 건너뜀."""
        fb = W.FakeBridge()
        self.assertEqual(self.w.analyze(self.w.cfg({"hier.copilot.requireCodenameReview": True}), ai=True, bridge=fb), 0)
        self.assertNotIn("ai:task_label", fb.stages())
        self.assertEqual((self.by()["ai:task_label"]["state"], self.by()["ai:task_label"]["reason"]),
                         ("skipped", "no_items"))
        self.assertIn("ai:workflow", fb.stages())

    def test_default_asks_task_label_without_registry(self):
        """계약 v1.3 §0.8 V12: 기본값이면 팀 레지스트리가 없어도 코드네임 검토를 기다리지 않고 task_label 을 묻는다(LM24 와 같음)."""
        fb = W.FakeBridge()
        self.w.analyze(ai=True, bridge=fb)
        self.assertIn("ai:task_label", fb.stages())
        self.assertNotEqual(self.by()["ai:task_label"].get("reason"), "no_items")


class FailSoftTest(_Base):
    def test_partial_bridge(self):
        summ = {"workflow_label": {"state": "partial", "items_total": 5, "items_ok": 3, "items_pending": 2,
                                   "items_failed": 0, "stop_kind": "manual_wait", "reason": None}}
        fb = W.FakeBridge(rc={"ai:workflow": 2}, summary=summ)
        rc = self.w.analyze(ai=True, bridge=fb)
        self.assertEqual(rc, 2)
        st = self.w.status()
        self.assertEqual((st["state"], st["current"]), ("partial", True), "규칙 라벨로 끝까지 — 보고서는 바뀐다")
        wf = self.by()["ai:workflow"]
        self.assertEqual((wf["state"], wf["stop_kind"], wf["resumable"]), ("partial", "manual_wait", True))
        self.assertEqual((wf["items_ok"], wf["items_pending"]), (3, 2))
        self.assertEqual(wf["bridge_rc"], 2)
        self.assertEqual(check_stage_common(wf), [])
        self.assertGreaterEqual(st["ai_pending"], 2)
        self.assertEqual(self.by()["report"]["state"], "done")

    def test_bridge_crash_is_soft(self):
        fb = W.FakeBridge(raise_on={"ai:review_text"})
        rc = self.w.analyze(ai=True, bridge=fb)
        self.assertEqual(rc, 2)
        rt = self.by()["ai:review_text"]
        self.assertEqual((rt["state"], rt["reason"], rt["stop_kind"]), ("partial", "bridge_failed", "fatal"))
        self.assertEqual(rt["error_type"], "OSError")
        self.assertEqual(self.by()["report"]["state"], "done")
        self.assertTrue(self.w.status()["current"])

    def test_failed_rc1_bridge(self):
        fb = W.FakeBridge(rc={"ai:workflow": 1})
        self.assertEqual(self.w.analyze(ai=True, bridge=fb), 2)
        wf = self.by()["ai:workflow"]
        self.assertEqual((wf["state"], wf["reason"]), ("partial", "bridge_failed"))

    def test_speech_act_crash_is_soft(self):
        """정규화 안의 AI 보조 단계(speech_act)가 죽어도 규칙 화행으로 끝까지 — 정규화 partial, 보고서까지."""
        fb = W.FakeBridge(raise_on={"normalize"})
        rc = self.w.analyze(ai=True, bridge=fb)
        nz = self.by()["normalize"]
        if nz["counts"].get("speech_act_items", 0) == 0:
            self.skipTest("합성 자료에 화행 회색 지대가 없음")
        self.assertEqual(rc, 2)
        self.assertEqual((nz["state"], nz["reason"], nz["speech_act"]), ("partial", "bridge_failed", "partial"))
        self.assertEqual(check_stage_common(nz), [])
        self.assertEqual(self.by()["classify"]["state"], "done")
        self.assertEqual(self.by()["report"]["state"], "done")
        self.assertTrue(self.w.status()["current"])


class _TC:
    """팀 클라이언트 대역(네트워크 없음) — refresh_registry·adopt_offline 호출만 기록."""

    def __init__(self, rc=4, boom=False):
        self.rc, self.boom, self.calls = rc, boom, []

    def refresh_registry(self, paths, cfg):
        self.calls.append("refresh")
        if self.boom:
            raise RuntimeError("가짜 실패")

        class R:
            pass
        r = R()
        r.rc = self.rc
        return r

    def adopt_offline(self, paths, cfg):
        self.calls.append("adopt")
        return True


class RegistryTest(_Base):
    def test_refresh_before_analysis(self):
        tc = _TC(rc=4)
        self.assertEqual(self.w.analyze(team_client=tc), 0)
        self.assertEqual(tc.calls, ["refresh"])
        self.assertEqual(self.w.status()["registry"]["refresh_rc"], 4)

    def test_rerun_skips_refresh(self):
        """빠른 재분석은 원본이 받은 캐시로(네트워크 대기 없음 — R §6.9 '수 초')."""
        from lm27.pipeline import stages as S
        tc = _TC(rc=0)
        self.assertEqual(self.w.analyze(team_client=tc), 0)
        self.assertEqual(self.w.analyze(team_client=tc, rerun=self.w.last, stages=list(S.QUICK_RERUN)), 0)
        self.assertEqual(tc.calls, ["refresh"])
        self.assertIsNone(self.w.status()["registry"]["refresh_rc"])

    def test_refresh_failure_is_soft(self):
        tc = _TC(boom=True)
        self.assertEqual(self.w.analyze(team_client=tc), 0)
        codes = [w["code"] for w in self.w.status()["warnings"]]
        self.assertIn("registry_refresh", codes)

    def test_adopt_offline_handed_to_client(self):
        """오프라인 사본을 골랐으면(RegistryStatus.adopt_offline) 캐시로 옮기는 일은 팀 클라이언트에 맡긴다(W1a CR)."""
        import dataclasses
        from unittest import mock

        import lm27.hier.registry as HR
        real = HR.load_effective

        def fake(*a, **k):
            reg, st = real(*a, **k)
            return reg, dataclasses.replace(st, adopt_offline=True)
        tc = _TC()
        with mock.patch.object(HR, "load_effective", fake):
            self.assertEqual(self.w.analyze(team_client=tc), 0)
        self.assertEqual(tc.calls, ["refresh", "adopt"])


class GateTest(_Base):
    def run_gate(self, cfg_over=None, **kw):
        fb = W.FakeBridge()
        rc = self.w.analyze(self.w.cfg(cfg_over), ai=True, bridge=fb, **kw)
        return rc, fb

    def test_no_copilot_role(self):
        rc, fb = self.run_gate(copilot_role=False)
        self.assertEqual(rc, 0)
        self.assertEqual(fb.calls, [])
        by = self.by()
        for sid in ("ai:task_label", "ai:workflow", "ai:review_text"):
            self.assertEqual((by[sid]["state"], by[sid]["reason"]), ("skipped", "no_copilot_role"))
        self.assertEqual(by["normalize"]["speech_act"], "no_copilot_role")

    def test_bridge_mode_off(self):
        rc, fb = self.run_gate({"bridge.mode": "off"})
        self.assertEqual(rc, 0)
        self.assertEqual(fb.calls, [])
        self.assertEqual(self.by()["ai:workflow"]["reason"], "bridge_off")

    def test_stage_switches(self):
        sw = {"speech_act": False, "task_label": True, "workflow_label": False, "agentic_match": True,
              "subagent_review": False, "review_text": False}
        rc, fb = self.run_gate({"bridge.stages": sw})
        self.assertEqual(rc, 0)
        self.assertEqual({c[0]: c[1] for c in fb.calls}.get("ai:workflow"), ("agentic_match",))
        self.assertNotIn("ai:review_text", fb.stages())
        self.assertNotIn("normalize", fb.stages())
        self.assertEqual(self.by()["ai:review_text"]["reason"], "stage_off")


class NoAiLabelsTest(_Base):
    def _store_answers(self) -> None:
        groups = json.loads(self.w.hier_bytes("groups.json"))
        ans = {"project": "NONE", "field": "ETC", "func": "ETC", "wtype": "OFFICE", "title": "코파일럿 이름", "new": "",
               "dom": "", "conf": "h"}
        ai_out = {"schema": 1, "stage": "task_label", "stage_ver": "task_label/1.1", "run_id": self.w.last,
                  "items": {g: {"ans": dict(ans), "by": "ai", "rid": "R22222", "asks": 1, "at": W.AS_OF}
                            for g in groups},
                  "stats": {"total": len(groups), "ai": len(groups), "manual": 0, "rule": 0, "pending": 0}}
        fsx.atomic_write(self.w.paths.ai_out("task_label"), fsx.canon_bytes(ai_out))

    def test_no_ai_run_keeps_stored_answers(self):
        """계약 v1.3 §0.8 V14: --no-ai·빠른 재분석은 AI 를 부르지 않을 뿐 — 저장된 AI 분류 답은 그대로 쓴다(LM24 처럼)."""
        self.assertEqual(self.w.analyze(), 0)
        self._store_answers()
        self.assertEqual(self.w.analyze(ai=False), 0)
        labels = json.loads(self.w.hier_bytes("labels.json"))
        self.assertTrue(labels)
        self.assertTrue(all(lb.get("title") == "코파일럿 이름" for lb in labels.values()))

    def test_t_h16_bridge_off_ignores_stored_answers(self):
        """T-H16: 브리지를 끈 설정(bridge.mode=off)이면 저장된 AI 분류 답이 있어도 쓰지 않는다(규칙 라벨로 완주)."""
        self.assertEqual(self.w.analyze(), 0)
        self._store_answers()
        self.assertEqual(self.w.analyze(self.w.cfg({"bridge.mode": "off"}), ai=False), 0)
        labels = json.loads(self.w.hier_bytes("labels.json"))
        for lb in labels.values():
            self.assertNotEqual(lb.get("title"), "코파일럿 이름")
            self.assertFalse(any(str(v).startswith("ai") for v in (lb.get("src") or {}).values()))


class _Child:
    """Popen 호환 가짜 자식(이미 끝남) — stdout 은 브리지 cli 의 jsonl 이벤트 줄."""

    def __init__(self, lines, code):
        self.stdout = io.BytesIO(("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n").encode("utf-8"))
        self.stderr = None
        self.pid = 424242
        self.code = code
        self.closed = False

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def close(self):
        self.closed = True


class ProcessBridgeTest(unittest.TestCase):
    def setUp(self):
        self.w = W.World()
        self.addCleanup(self.w.remove)

    def test_argv_parse_forward(self):
        rid = "20260914-090000-0a0b"
        res = {"run_id": rid, "rc": 2, "stages": {
            "workflow_label": {"state": "done", "rc": 0, "items_total": 4, "items_ok": 4, "items_pending": 0,
                               "items_failed": 0, "stop_kind": None, "reason": None},
            "agentic_match": {"state": "partial", "rc": 2, "items_total": 3, "items_ok": 1, "items_pending": 2,
                              "items_failed": 0, "stop_kind": "budget", "reason": None}}}
        lines = [{"seq": 1, "ts": "2026-09-14T00:00:01Z", "ev": "stage_start", "stage": "workflow_label"},
                 {"seq": 2, "ts": "2026-09-14T00:00:02Z", "ev": "progress", "stage": "workflow_label", "done": 3},
                 {"seq": 3, "ts": "2026-09-14T00:00:03Z", "ev": "progress", "stage": "workflow_label", "done": 4},
                 {"seq": 4, "ts": "2026-09-14T00:00:04Z", "ev": "notice", "stage": "agentic_match", "code": "BR-BUDGET",
                  "text_ko": "예산 안내"},
                 {"seq": 5, "ts": "2026-09-14T00:00:05Z", "ev": "progress", "stage": "agentic_match", "done": 1},
                 {"seq": 6, "ts": "2026-09-14T00:00:06Z", "ev": "result", "cmd": "run", "result": res},
                 {"seq": 7, "ts": "2026-09-14T00:00:07Z", "ev": "run_end", "rc": 2}]
        seen = {}
        child = _Child(lines, 2)

        def spawn(argv):
            seen["argv"] = list(argv)
            return child
        got = []
        br = A.process_bridge(self.w.paths, self.w.cfg(), rid, "ai:workflow", ["workflow_label", "agentic_match"],
                              spawn=spawn, emit=lambda ev, **f: got.append((ev, f)))
        argv = seen["argv"]
        self.assertEqual(argv[1:4], ["-X", "utf8", "-B"])
        self.assertTrue(argv[4].endswith("lm27_cli.py"))
        self.assertEqual(argv[5:], ["bridge", "run", "--run-id", rid, "--stages", "workflow_label,agentic_match",
                                    "--events", "jsonl"])
        self.assertTrue(child.closed)
        self.assertEqual((br.rc, br.killed, sorted(br.stages)), (2, False, ["agentic_match", "workflow_label"]))
        prog = [f for ev, f in got if ev == "progress" and "sub" in f]
        self.assertEqual([p["done"] for p in prog], [3, 4, 5], "자식 단계별 최댓값 증가분의 단조 누계")
        self.assertTrue(all(p["stage"] == "ai:workflow" for p in prog))
        notes = [f for ev, f in got if ev == "notice"]
        self.assertEqual(notes, [{"stage": "ai:workflow", "sub": "agentic_match", "code": "BR-BUDGET",
                                  "text_ko": "예산 안내"}])
        self.assertFalse(any(ev in ("stage_start", "result", "run_end") for ev, _f in got))
        out = A._bridge_out(br)
        self.assertEqual((out.state, out.stop_kind, out.items_total, out.items_ok, out.items_pending),
                         ("partial", "budget", 7, 5, 2))
        self.assertEqual(out.extra["bridge"]["agentic_match"]["state"], "partial")

    def test_as_bridge_run_shapes(self):
        self.assertEqual(A._as_bridge_run(0).rc, 0)
        self.assertIsNone(A._as_bridge_run("x").rc)
        b = A._as_bridge_run({"rc": 1, "stages": {"a": {}}, "killed": True})
        self.assertEqual((b.rc, b.killed, list(b.stages)), (1, True, ["a"]))
        killed = A._bridge_out(A.BridgeRun(rc=3, stop_kind="stall", reason="R-" + "TRANSPORT", killed=True))
        self.assertEqual((killed.state, killed.stop_kind, killed.reason), ("partial", "stall", "R-" + "TRANSPORT"))
        odd = A._bridge_out(A.BridgeRun(rc=2, stages={"x": {"reason": "원문 같은 긴 사유 문장"}}))
        self.assertEqual(odd.reason, "bridge_partial", "형식 밖 사유는 싣지 않는다")


if __name__ == "__main__":
    unittest.main()
