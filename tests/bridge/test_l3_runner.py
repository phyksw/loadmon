# -*- coding: utf-8 -*-
"""WP-24 L3 배치 실행기(B §7) — B-T26~T28 · T33~T38 · 접기(멱등·B8) · 결과 봉투 항등식 · 재개 규칙 (a)(b)(c) ·
조회형 구간 쪼개기·상한 · 건너뛰기 사유 · 묶음 순서."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lm27.bridge import journal as J
from lm27.bridge.transport_stub import StubTransport
from lm27.util import events

from tests.bridge.stub_responder import Crash, StubResponder
from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp24.rig import REG, RUN2, Rig, act_rows, flow_rows, label_rows, window_rows
from tests.fixtures.wp24.stages import ActStage, FlowStage, LabelStage, LookupStage


def setUpModule():
    events.configure(mode="off")


class _Clocked(StubTransport):
    def __init__(self, responder, clock, step):
        super().__init__(responder)
        self.clock, self.step = clock, step

    def roundtrip(self, req):
        self.clock.advance(self.step)
        return super().roundtrip(req)


class _One(ActStage):
    max_items = 1


class _NoFallback(ActStage):
    def fallback(self, it, ctx, why):
        return None


class _NoShrink(ActStage):
    gate_max_chars = 3000

    def shrink(self, it, max_chars):
        return None


def _identity(t, res):
    t.assertEqual(check_stage_common(res), [])
    t.assertEqual(res["items_total"], res["items_ai"] + res["items_manual"] + res["items_rule"] + res["items_pending"])
    t.assertEqual(res["items_ok"], res["items_ai"] + res["items_manual"])
    t.assertLessEqual(res["items_failed"] + res["items_gated"] + res["items_oversize"], res["items_rule"])
    t.assertEqual(res["rc"], {"done": 0, "skipped": 0, "partial": 2, "failed": 1}[res["state"]])


class Base(unittest.TestCase):
    def rig(self, stages, ai_in, **kw):
        r = Rig(stages=stages, **kw)
        self.addCleanup(r.cleanup)
        for s in stages:
            r.write_ai_in(s.id, ai_in if not isinstance(ai_in, dict) else ai_in[s.id])
        return r


class Scenarios(Base):
    def test_T26_only_missing_reasked(self):
        r = self.rig([ActStage()], act_rows(40), script={"t_act": ["partial:0.925", "ok"]})
        res = r.run()["t_act"]
        self.assertEqual((res["items_ai"], r.transport.sends), (40, 2))
        self.assertEqual(r.transport.sent_texts[1].count(" | mail | ") + r.transport.sent_texts[1].count(" | teams | "),
                         3)
        asks = {c["key"]: c["asks"] for c in r.store("t_act")}
        self.assertEqual(sorted(k for k, v in asks.items() if v == 2), ["msg:00037", "msg:00038", "msg:00039"])
        self.assertEqual(sum(1 for v in asks.values() if v == 1), 37)
        _identity(self, res)

    def test_T27_three_invalid_then_one_retry_next_run(self):
        def ans(spec, key):
            return {"act": "지시", "conf": "h"} if key == "msg:00001" else None
        r = self.rig([ActStage()], act_rows(3), answer_fn=ans)
        res = r.run()["t_act"]
        c = [x for x in r.store("t_act") if x["key"] == "msg:00001"]
        self.assertEqual((c[-1]["by"], c[-1]["why"], c[-1]["final"], c[-1]["retry_runs"]), ("rule", "ai_failed", False, 0))
        self.assertEqual((res["items_failed"], res["state"]), (1, "partial"))
        before = r.transport.sends
        r.new_runtime(run_id=RUN2)
        res2 = r.run()["t_act"]
        c = [x for x in r.store("t_act") if x["key"] == "msg:00001"]
        self.assertEqual((c[-1]["final"], c[-1]["retry_runs"]), (True, 1))
        self.assertEqual(res2["asks"], 3)                         # 그 항목만 한 실행 더(그 안에서 최대 3번 묻기)
        self.assertEqual(res2["counts"]["resume_skipped"], 2)
        after2 = r.transport.sends
        self.assertGreater(after2, before)
        r.new_runtime(run_id="20261007-090000-0c3d")
        r.run()
        self.assertEqual(r.transport.sends, after2)               # final=true 뒤로는 묻지 않는다
        _identity(self, res2)

    def test_T28_truncated_brace_in_string(self):
        def ans(spec, key):
            return {"project": "P-0012", "field": "OPT", "func": "ANALYSIS", "title": "설계안} 검토 {중", "conf": "h"}
        r = self.rig([LabelStage()], label_rows(6), answer_fn=ans, script={"t_label": ["truncate:0.55", "ok"]})
        res = r.run()["t_label"]
        resp = [j for j in r.journal("t_label") if j["t"] == "resp"]
        self.assertEqual((resp[0]["status"], resp[0]["how"]), ("truncated", "salvaged"))
        first = resp[0]["ok"]
        self.assertTrue(0 < first < 6)
        self.assertTrue(all(c["ans"]["title"] == "설계안} 검토 {중" for c in r.store("t_label")))
        self.assertEqual((res["items_ai"], res["state"]), (6, "done"))
        self.assertTrue(r.transport.requests[1].fresh)          # truncated(output) 다음은 새 채팅

    def test_T33_oversize(self):
        rows = label_rows(4)
        rows[1]["fields"]["subjects"] = ["가나다라 " * 120]
        rows[1]["fields"]["files"] = ["공차해석 결과표 " * 60 + ".xlsx", "보고서 " * 80 + ".pptx"]
        rows[1]["fields"]["apps"] = ["해석 프로그램 " * 50]
        r = self.rig([LabelStage()], rows, overrides={"bridge.inputMaxChars": 2000})
        res = r.run()["t_label"]
        self.assertEqual((res["items_oversize"], res["caps_hit"].get("oversize"), res["items_ai"]), (1, 1, 3))
        ov = [c for c in r.store("t_label") if c.get("why") == "oversize"]
        self.assertEqual((ov[0]["key"], ov[0]["final"]), ("grp:00001", True))
        self.assertTrue(all(len(t) <= 2000 for t in r.transport.sent_texts))
        _identity(self, res)

    def test_many_oversize_no_recursion(self):
        rows = act_rows(1500, text="가나다라마바사 " * 300)
        r = self.rig([_NoShrink()], rows, overrides={"bridge.inputMaxChars": 2000})
        res = r.run()["t_act"]
        self.assertEqual((res["items_oversize"], r.transport.sends, res["state"]), (1500, 0, "done"))

    def test_policy_blocked_midrun_switches_to_manual(self):
        """B §10.1: 호출 중 policy_blocked → 그 질의부터 수동 경로(BR-MANUAL-SWITCH). 남은 항목은 웹 노출 엄격 규칙으로 다시
        거르고(금액+고객사 → gated:web_combo), 결과 봉투 gate 요약은 전환 전후를 합쳐 항목당 한 번만 센다."""
        rows = act_rows(4)
        rows[3]["fields"]["text"] = "[고객사:C0012] 견적 금액 [금액] 회신 요청"
        r = self.rig([_One()], rows, script={"t_act": ["ok", "phase:policy_blocked"]})
        res = r.run()["t_act"]
        _identity(self, res)
        self.assertEqual((res["transport"], res["stop_kind"], res["items_ai"]), ("manual", "manual_wait", 1))
        self.assertIn("BR-MANUAL-SWITCH", r.notified())
        self.assertEqual(r.transport.sends, 2)
        self.assertEqual(res["gate"]["items_in"], 4)
        self.assertTrue(res["gate"]["web"]["exposed"])
        self.assertEqual(res["gate"]["web"]["combo_drop"], 1)
        gated = [c for c in r.store("t_act") if c.get("why") == "gated:web_combo"]
        self.assertEqual([c["key"] for c in gated], ["msg:00003"])
        mf = json.loads(Path(r.paths.copilot_manual(), "manifest.json").read_text("utf-8"))
        self.assertEqual(sorted(i["key"] for b in mf["batches"] for i in b["items"]), ["msg:00001", "msg:00002"])
        self.assertTrue(all(i["ck"] for b in mf["batches"] for i in b["items"]))

    def test_T34_circuit_soft_then_abort(self):
        r = self.rig([ActStage()], act_rows(40), script={"t_act": ["format"]},
                     overrides={"bridge.maxAsksPerItem": 6, "bridge.splitMaxDepth": 6, "bridge.splitMinItems": 1})
        res = r.run()["t_act"]
        self.assertIn("BR-CIRCUIT-SOFT", r.notified())
        self.assertIn("BR-CIRCUIT", r.notified())
        self.assertEqual((res["stop_kind"], res["resumable"], res["statuses"]["format"]), ("circuit", True, 6))
        self.assertEqual(res["items_pending"], 40)
        req = [j for j in r.journal("t_act") if j["t"] == "req" and j["rung"] == 0]
        self.assertEqual(max(q["depth"] for q in req), 3)              # soft 뒤로는 반분하지 않는다(깊이 6까지 허용인데도)
        _identity(self, res)

    def test_T35_crash_after_seventh_commit_resumes(self):
        r = self.rig([ActStage()], act_rows(20))
        orig = J.Store.commit
        n = {"c": 0}

        def boom(self_, rec):
            out = orig(self_, rec)
            n["c"] += 1
            if n["c"] == 7:
                raise Crash("kill")
            return out
        J.Store.commit = boom
        try:
            with self.assertRaises(Crash):
                r.run()
        finally:
            J.Store.commit = orig
        self.assertEqual(len(r.store("t_act")), 7)
        sends_before = r.transport.sends
        r.new_runtime(run_id=RUN2)
        res = r.run()["t_act"]
        self.assertEqual(res["counts"]["resume_skipped"], 7)
        self.assertEqual(r.transport.sends - sends_before, 1)       # 진행 중이던 질의 1건 분량만
        self.assertEqual(r.transport.sent_texts[-1].count("번 항목"), 13)
        self.assertEqual((res["items_ai"], res["state"]), (20, "done"))

    def test_T36_stage_budget(self):
        st = StubResponder([ActStage()])
        r = Rig(stages=[ActStage()], responder=st, overrides={"bridge.stageBudgetMin": 10, "bridge.stageFloorMin": 0})
        self.addCleanup(r.cleanup)
        r.new_runtime(transport=_Clocked(st, r.clock, 240))
        r.write_ai_in("t_act", act_rows(200))
        res = r.run()["t_act"]
        self.assertIn(res["asks"], (2, 3))
        self.assertEqual((res["stop_kind"], res["resumable"], res["state"]), ("budget", True, "partial"))
        self.assertEqual(res["items_pending"], 200 - res["items_ai"])
        self.assertIn("BR-BUDGET", r.notified())
        out = r.ai_out("t_act")
        self.assertEqual(sum(1 for v in out["items"].values() if v["by"] == "rule_pending"), res["items_pending"])
        _identity(self, res)

    def test_T37_chat_turns(self):
        r = self.rig([_One()], act_rows(14), overrides={"bridge.chatTurns": 12})
        r.run()
        fresh = [q.fresh for q in r.transport.requests]
        self.assertEqual(len(fresh), 14)
        self.assertEqual([i for i, f in enumerate(fresh, 1) if f], [1, 13])

    def test_T38_truncated_twice_shrinks_answer_budget(self):
        r = self.rig([ActStage()], act_rows(30), script={"t_act": ["truncate:0.6", "truncate:0.6", "ok"]})
        res = r.run()["t_act"]
        self.assertEqual(res["pack"]["out"], int(r.cfg.answer_max_chars * 0.8))
        ra = r.profile.load()["runtime_adjust"]["t_act"]
        self.assertEqual(ra["pack_out_factor"], 0.8)
        r.new_runtime(run_id=RUN2)
        r.write_ai_in("t_act", act_rows(5, start=100))
        res2 = r.run()["t_act"]
        self.assertEqual(res2["pack"]["out"], int(r.cfg.answer_max_chars * 0.8))     # 다음 실행 시작값

    def test_runtime_adjust_recovers_after_five_ok(self):
        r = self.rig([_One()], act_rows(6))
        r.profile.update(lambda d: d.setdefault("runtime_adjust", {}).update(
            {"t_act": {"pack_out_factor": 0.8, "at": "2026-09-01T00:00:00+09:00"}}))
        r.run()
        self.assertEqual(r.profile.load()["runtime_adjust"]["t_act"]["pack_out_factor"], 0.9)


class Resume(Base):
    def test_registry_change_reasks_gone_codes_only(self):
        seen = set()

        def ans(spec, key):
            proj = "P-0007" if key.endswith(("0", "2")) and key not in seen else "NONE"
            seen.add(key)
            return {"project": proj, "field": "OPT", "func": "ANALYSIS", "title": "공차 해석", "conf": "h"}
        r = self.rig([LabelStage()], label_rows(4), answer_fn=ans)
        r.run()
        sends = r.transport.sends
        r.registry = {"version": 13, "codes": dict(REG["codes"], projects=["P-0012", "P-0003"])}
        r.new_runtime(run_id=RUN2)
        res = r.run()["t_label"]
        self.assertEqual(r.transport.sends - sends, 1)
        self.assertEqual(res["counts"]["resume_skipped"], 2)
        txt = r.transport.sent_texts[-1]
        self.assertIn("공유 0", txt)
        self.assertIn("공유 2", txt)
        self.assertNotIn("공유 1 ", txt)
        self.assertEqual({c["reg"] for c in r.store("t_label")}, {"r12", "r13"})

    def test_same_registry_reuses_everything(self):
        r = self.rig([LabelStage()], label_rows(4))
        r.run()
        sends = r.transport.sends
        r.registry = {"version": 13, "codes": REG["codes"]}               # 판만 바뀌고 코드는 그대로 → 다시 묻지 않음
        r.new_runtime(run_id=RUN2)
        res = r.run()["t_label"]
        self.assertEqual((r.transport.sends, res["state"]), (sends, "done"))


class FoldAndResult(Base):
    def test_fold_idempotent_and_result_path(self):
        r = self.rig([ActStage()], act_rows(5))
        r.run()
        a = r.ai_out("t_act")
        r.new_runtime(run_id=RUN2)
        r.run()
        b = r.ai_out("t_act")
        self.assertEqual(a["items"], b["items"])
        self.assertTrue(b["result"].endswith("t_act.result.json"))
        self.assertTrue(b["result"].startswith("data/ai/runs/"))
        self.assertEqual(b["stats"], {"total": 5, "ai": 5, "manual": 0, "rule": 0, "pending": 0})

    def test_B8_empty_answer_keeps_previous(self):
        spec = _NoFallback()
        r = self.rig([spec], act_rows(2))
        r.run()
        prev = r.ai_out("t_act")["items"]["msg:00000"]["ans"]
        rows = act_rows(2)
        rows[0]["fields"]["text"] = "내용이 바뀐 항목"
        r.write_ai_in("t_act", rows)
        r2 = Rig(stages=[spec], tmp=r.tmp, overrides={"bridge.mode": "off"})
        res = r2.run()["t_act"]
        out = r2.ai_out("t_act")["items"]
        self.assertEqual((res["state"], res["reason"]), ("skipped", "disabled"))
        self.assertEqual(out["msg:00000"]["ans"], prev)                    # 빈 답으로 덮지 않음(B8)

    def test_mode_off_folds_rule_pending(self):
        r = self.rig([ActStage()], act_rows(3), overrides={"bridge.mode": "off"})
        res = r.run()["t_act"]
        self.assertEqual((res["state"], res["rc"], r.transport.sends, res["items_pending"]), ("skipped", 0, 0, 3))
        self.assertEqual({v["by"] for v in r.ai_out("t_act")["items"].values()}, {"rule_pending"})
        _identity(self, res)

    def test_no_input_skipped_without_overwriting(self):
        r = self.rig([ActStage()], act_rows(2))
        r.run()
        Path(r.paths.ai_in("t_act")).unlink()
        r.new_runtime(run_id=RUN2)
        res = r.run()["t_act"]
        self.assertEqual((res["state"], res["reason"]), ("skipped", "no_input"))
        self.assertEqual(len(r.ai_out("t_act")["items"]), 2)

    def test_bad_input_rows_counted(self):
        r = self.rig([ActStage()], act_rows(2) + [{"key": ""}, {"key": "msg:00000"},
                                                  {"key": "x", "fields": {"text": "a", "zzz": 1}}])
        res = r.run()["t_act"]
        self.assertEqual((res["dropped"]["bad_input"], res["dropped"]["dup_input"],
                          res["dropped"]["extra_input_fields"]), (1, 1, 1))

    def test_group_strict_orders_by_group(self):
        rows = flow_rows(6)
        r = self.rig([FlowStage()], rows)
        r.run()
        first = r.transport.sent_texts[0]
        self.assertTrue(all(json.dumps(x, ensure_ascii=False) for x in rows))
        self.assertEqual(r.store("t_flow")[0]["key"], "ws:W0000")
        self.assertGreater(len(first), 0)
        groups = [row["group"] for row in rows]
        order = [c["key"] for c in r.store("t_flow")]
        self.assertEqual(order, sorted(order, key=lambda k: (groups.index(rows[int(k[4:])]["group"]))))

    def test_seen_names_and_overlap_in_second_batch(self):
        r = self.rig([LabelStage()], label_rows(40), overrides={"bridge.inputMaxChars": 3000})
        r.run()
        self.assertGreater(r.transport.sends, 1)
        self.assertIn("[앞서 쓴 이름] 공통 업무", r.transport.sent_texts[1])
        self.assertIn("[참고 — 이미 처리한 항목, 답하지 마세요]", r.transport.sent_texts[1])
        self.assertTrue(all(len(t) <= 3000 for t in r.transport.sent_texts))


class Lookup(Base):
    def test_split_full_window_then_commit_children(self):
        spec = LookupStage()
        rows = window_rows("lookup_mail", [("2026-09-01", "2026-09-07")])
        more = {"lookup_mail:2026-09-01:2026-09-07": True}
        r = self.rig([spec], rows, rows=lambda key: [{"t": key.split(":")[1], "d": "in", "s": "업무 메일"}],
                     more=lambda key: more.get(key, False))
        res = r.run()["lookup_mail"]
        keys = [c["key"] for c in r.store("lookup_mail")]
        self.assertEqual(keys, ["lookup_mail:2026-09-01:2026-09-07", "lookup_mail:2026-09-01:2026-09-03",
                                "lookup_mail:2026-09-04:2026-09-07"])
        parent = r.store("lookup_mail")[0]
        self.assertEqual((parent["why"], parent["ans"]["split"][0]), ("split", "lookup_mail:2026-09-01:2026-09-03"))
        self.assertEqual((res["items_total"], res["items_ai"], res["state"]), (2, 2, "done"))
        self.assertEqual(r.ai_out("lookup_mail")["items"]["lookup_mail:2026-09-04:2026-09-07"]["ans"]["rows"][0]["t"],
                         "2026-09-04")
        self.assertEqual(r.rt.caps.state("lookup_mail"), "ok")
        _identity(self, res)

    def test_capped_when_cannot_split(self):
        rows = window_rows("lookup_mail", [("2026-09-02", "2026-09-02")])
        r = self.rig([LookupStage()], rows, rows=lambda key: [{"t": "2026-09-02", "d": "out"}], more=True)
        res = r.run()["lookup_mail"]
        c = r.store("lookup_mail")[0]
        self.assertTrue(c["ans"]["capped"])
        self.assertEqual(res["caps_hit"], {"lookup_rows": 1})

    def test_split_children_folded_when_stage_skipped(self):
        spec = LookupStage()
        rows = window_rows("lookup_mail", [("2026-09-01", "2026-09-04")])
        r = self.rig([spec], rows, rows=lambda key: [{"t": key.split(":")[1], "d": "in"}],
                     more=lambda k: k == "lookup_mail:2026-09-01:2026-09-04")
        r.run()
        r2 = Rig(stages=[spec], tmp=r.tmp, overrides={"bridge.mode": "off"})
        res = r2.run()["lookup_mail"]
        items = r2.ai_out("lookup_mail")["items"]
        self.assertEqual(sorted(items), ["lookup_mail:2026-09-01:2026-09-02", "lookup_mail:2026-09-01:2026-09-04",
                                         "lookup_mail:2026-09-03:2026-09-04"])
        self.assertEqual((res["state"], res["items_total"], res["items_ai"]), ("skipped", 2, 2))

    def test_resume_split_children(self):
        spec = LookupStage()
        rows = window_rows("lookup_mail", [("2026-09-01", "2026-09-04")])
        st = StubResponder([spec], script={"lookup_mail": ["ok", "crash"]},
                           more=lambda k: k == "lookup_mail:2026-09-01:2026-09-04", rows=lambda key: [])
        r = Rig(stages=[spec], responder=st)
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", rows)
        with self.assertRaises(Crash):
            r.run()
        st.script = {}
        r.new_runtime(run_id=RUN2)
        res = r.run()["lookup_mail"]
        self.assertEqual((res["items_total"], res["items_ai"]), (2, 2))


if __name__ == "__main__":
    unittest.main()
