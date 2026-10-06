# -*- coding: utf-8 -*-
"""WP-31 가림판 모델(R §9.2.4 · §3.6 · §11 · G-R8 · RPT-31 · T-07).

가림판은 전체판에서 지우는 방식이 아니라 **허용 목록으로 새로 만든다**. 직렬화 바이트에 사람 사전 이름(한글 2자 이상·ASCII 4자
이상)·who_key·로컬 키 모양·카나리아가 0건이어야 하고, 하나라도 있으면 가림판을 만들지 않는다(rc 1 · 필드 경로만).
"""
from __future__ import annotations

import copy
import json
import os
import unittest

from lm27.report import export as EX
from lm27.report import model as M
from lm27.report.resolve import KEY_RX
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


def build(run, t, cfg=None):
    run.write(t.paths)
    c = cfg or W.cfg()
    inp = run.inputs(t.paths, c)
    return M.build_model(inp, c, fallback=no_fallback), inp


def canary_run():
    """사람 사전 이름 20개 + 카나리아(이름·파일 이름·본문 형식·키 모양)를 로컬 전용 자리(사람 사전 이름·문서 이름·근거 제목·
    동료 키)에만 심은 실행. 단위업무 제목·과제 이름에는 넣지 않는다(정제된 라벨이라 원값이 없는 자리)."""
    cs = canaries()
    by = {c.cid: c for c in cs}
    run = R.rich_run()
    names = []
    for s in range(1, 40):
        v = next(c.value for c in canaries(seed=s) if c.cid == "c52.person")
        if v not in names:
            names.append(v)
        if len(names) == 20:
            break
    people = run.person_dir["people"]
    uids = sorted(run.w.tasks)
    for i, nm in enumerate(names):
        who = R.key("w", f"extra{i}")
        people[who] = {"names": [nm], "smtp": [f"user{i + 10:02d}@corp.example"], "internal": True, "self": False}
        run.w.tasks[uids[i % len(uids)]]["peers"].append({"who_key": who, "rel": "requester"})
    people[R.PEER2]["names"] = [by["c62.person_dict"].value]
    people[R.ME]["names"] = [by["c63.self_name"].value]
    f2, f3 = R.fam_of("f2"), R.fam_of("f3")
    run.fam_names[f2] = by["c55.file_phone"].value
    run.fam_names[f3] = by["c59.file_rrn"].value
    for ln in run.ev["lines"].values():
        if ln["kind"] == "mail":
            ln["title"] = "회신 " + by["c01.phone"].value
    key_c = next(c for c in cs if c.group == "key" and c.value.startswith("w"))
    run.w.tasks["u_a2"]["peers"].append({"who_key": key_c.value, "rel": "requester"})
    sel = [by["c52.person"], by["c62.person_dict"], by["c63.self_name"], by["c55.file_phone"], by["c59.file_rrn"],
           by["c01.phone"], key_c]
    return run, names, sel


class RedactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)          # setUpClass 가 중간에 실패해도 임시 ROOT 를 지운다(W2 검토 L12)
        cls.srun = R.rich_run(title_over={"u_a3": "김철수 요청 전원부 해석"})
        cls.m, cls.inp = build(cls.srun, cls.t)
        cls.red = M.redact_model(cls.m, cls.inp.registry, person_dir=cls.inp.person_dir)

    def test_allow_list(self):
        red = self.red
        self.assertEqual(red["variant"], "redacted")
        self.assertEqual(red["refs"]["people"], {str(k): {"name": f"동료 #{k}"} for k in (1, 2, 3)})
        self.assertTrue(all(set(v) == {"name"} for v in red["refs"]["docs"].values()))
        for u in red["units"]:
            for k in ("docs", "queue", "label_src", "label_conf", "why"):
                self.assertNotIn(k, u)
            for c in u["cycles"]:
                self.assertNotIn("s_key", c)
            self.assertFalse(any(str(f).startswith("회의연결") for f in u["flags"]))
        for q in red["queue"]:
            self.assertNotIn("evidence_keys", q)
            self.assertNotIn("why_ko", q)
            self.assertNotIn("note", q["proposal"])
        self.assertTrue(all(p["name"] == f"동료 #{p['ref']}" for p in red["peers"]["internal"]))
        for n in red["ontology"]["nodes"]:
            if n["type"] == "D" and n.get("ref"):
                self.assertEqual(n["label"], f"문서 #{n['ref']}")
            if n["type"] == "C" and n.get("ref"):
                self.assertEqual(n["label"], f"동료 #{n['ref']}")
        for rv in red["reviews"]["months"]:
            for p in rv["peers_top"]:
                self.assertEqual(p["name"], f"동료 #{p['ref']}")
            if rv.get("ai"):
                self.assertNotIn("peers_map", rv["ai"])
        self.assertNotIn("proposals", red)
        self.assertEqual(M.check_model(red), [])                      # 숫자·등식은 그대로

    def test_g_r8(self):
        self.assertEqual(M.redaction_violations(self.red, self.inp.person_dir), [])
        full_bad = M.redaction_violations(self.m, self.inp.person_dir)
        self.assertTrue(any(p.startswith("refs.people") for p in full_bad))     # 전체판에는 이름·키가 있다(시험이 유효)
        self.assertFalse(KEY_RX.search(M.model_bytes(self.red).decode("utf-8")))

    def test_unsafe_title_becomes_generic(self):
        u3 = next(u for u in self.red["units"] if u["unit_id"] == "u_a3")
        self.assertRegex(u3["title"], r"^.+·.+ 단위업무 #\d+$")
        self.assertEqual(u3["title_mode"], "generic")
        u1 = next(u for u in self.red["units"] if u["unit_id"] == "u_a1")
        self.assertEqual(u1["title"], "전원부 해석 1")
        gen = M.redact_model(self.m, self.inp.registry, person_dir=self.inp.person_dir, title_mode="generic")
        self.assertTrue(all(u["title_mode"] == "generic" for u in gen["units"]))

    def test_mask_name(self):
        reg = copy.deepcopy(R.REGISTRY)
        reg["projects"][0]["mask_name"] = True
        run = R.rich_run()
        run.registry = reg
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        m, inp = build(run, t)
        p = next(x for x in m["projects"] if x["key"] == "P-0007")
        self.assertEqual(p["label"], "과제A")                          # 전체판(로컬)은 이름
        red = M.redact_model(m, inp.registry, person_dir=inp.person_dir)
        rp = next(x for x in red["projects"] if x["key"] == "P-0007")
        self.assertEqual(rp["label"], "P-0007")
        pn = next(n for n in red["ontology"]["nodes"] if n["type"] == "P")
        self.assertEqual(pn["label"], "P-0007")

    def test_review_ai_peer_tokens(self):
        """코파일럿 리뷰 문장의 `동료k`(질의 안 번호)는 가림판에서 `동료 #k`(모델 번호표)로 — 이름도 키도 없이."""
        run = R.rich_run()
        run.ai = {"review_text": {"schema": 1, "stage": "review_text", "items": {
            "review:month:2026-09": {"ans": {"summary": "동료1 과 전원부를 검토했습니다.",
                                             "highlights": [{"text": "동료1 의뢰 건 완료", "refs": ["F1"]}],
                                             "relations": [], "next": ["동료1 회신 확인"]},
                                     "by": "ai", "peers_map": {"동료1": R.KIM}}}}}
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        m, inp = build(run, t)
        sep = next(r for r in m["reviews"]["months"] if r["key"] == "2026-09")
        ref = int(next(k for k, v in m["refs"]["people"].items() if v["key"] == R.KIM))
        self.assertEqual(sep["ai"]["peers_map"], {"동료1": ref})
        red = M.redact_model(m, inp.registry, person_dir=inp.person_dir)
        rs = next(r for r in red["reviews"]["months"] if r["key"] == "2026-09")
        self.assertEqual(rs["ai"]["summary"], f"동료 #{ref} 과 전원부를 검토했습니다.")
        self.assertEqual(rs["ai"]["next"], [f"동료 #{ref} 회신 확인"])
        self.assertEqual(M.redaction_violations(red, inp.person_dir), [])


TOKEN_TITLE = "[사람#a1b2c3] 요청 견적 검토"
ACME_TITLE = "Acme 단가 협상안"


class ReviewTitleLeakTest(unittest.TestCase):
    """W2 검토 C13: 리뷰 AI 문장(규칙 폴백·AI 답)이 전체판 사실 제목을 베껴 가림판에 원래 제목·`[사람#hex]` 가 남던 것.
    폴백은 실제 브리지 단계 정의(`lm27.bridge.stages` — 주입하지 않음)가 돈다."""

    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)
        cls.srun = R.rich_run(title_over={"u_a1": TOKEN_TITLE, "u_a2": ACME_TITLE})
        cls.srun.write(cls.t.paths)
        cls.cfg = W.cfg()
        cls.inp = cls.srun.inputs(cls.t.paths, cls.cfg)
        cls.m = M.build_model(cls.inp, cls.cfg, fallback=None)
        cls.originals = sorted({u["title"] for u in cls.m["units"]})

    def _ai_texts(self, red):
        out = []
        for kind in ("weeks", "months"):
            for r in red["reviews"][kind]:
                ai = r.get("ai") or {}
                out += [ai.get("summary") or ""] + [h["text"] for h in ai.get("highlights") or ()]
                out += [h["text"] for h in ai.get("relations") or ()] + list(ai.get("next") or ())
        return out

    def test_full_model_has_rule_texts_with_titles(self):
        """시험이 유효한지: 전체판 리뷰 폴백 문장에 원래 제목이 있다."""
        txt = json.dumps(self.m["reviews"], ensure_ascii=False)
        self.assertIn(TOKEN_TITLE, txt)
        self.assertIn(ACME_TITLE, txt)
        self.assertTrue(any((r.get("ai") or {}).get("by") == "rule" for r in self.m["reviews"]["months"]))

    def test_label_mode(self):
        red = M.redact_model(self.m, self.inp.registry, person_dir=self.inp.person_dir, title_mode="label")
        blob = json.dumps(red, ensure_ascii=False)
        self.assertNotIn("[사람#", blob)
        u1 = next(u for u in red["units"] if u["unit_id"] == "u_a1")
        self.assertEqual(u1["title_mode"], "generic")
        self.assertFalse(any(TOKEN_TITLE in s for s in self._ai_texts(red)))
        titles = {u["title"] for u in red["units"]}
        for r in red["reviews"]["months"]:
            ai = r.get("ai") or {}
            if ai.get("by") == "rule":
                for h in ai["highlights"]:
                    self.assertIn(h["text"], titles)                   # 사실의 가림 제목으로 다시 만든다
                for n in ai["next"]:
                    self.assertIn(n, titles)
        self.assertEqual(M.redaction_violations(red, self.inp.person_dir), [])

    def test_generic_mode_no_original_titles(self):
        red = M.redact_model(self.m, self.inp.registry, person_dir=self.inp.person_dir, title_mode="generic")
        blob = json.dumps(red, ensure_ascii=False)
        for t in self.originals:
            self.assertNotIn(t, blob, t)
        self.assertNotIn("[사람#", blob)

    def test_ai_answer_titles_replaced(self):
        """AI 답(by=ai)이 사실 제목을 그대로 인용해도 가림 제목으로 바뀐다."""
        run = R.rich_run(title_over={"u_a2": ACME_TITLE})
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        run.ai = {"review_text": {"schema": 1, "stage": "review_text", "items": {
            "review:month:2026-09": {"ans": {"summary": f"{ACME_TITLE} 를 마쳤습니다. [사람#a1b2c3] 의뢰도 있었습니다.",
                                             "highlights": [{"text": f"{ACME_TITLE} 완료", "refs": ["F1"]}],
                                             "relations": [{"text": f"{ACME_TITLE} → 다음", "refs": []}],
                                             "next": [f"{ACME_TITLE} 후속"]},
                                     "by": "ai", "peers_map": {}}}}}
        run.write(t.paths)
        cfg = W.cfg()
        inp = run.inputs(t.paths, cfg)
        m = M.build_model(inp, cfg, fallback=no_fallback)
        sep = next(r for r in m["reviews"]["months"] if r["key"] == "2026-09")
        self.assertIn(ACME_TITLE, sep["ai"]["summary"])                 # 전체판은 그대로(시험 유효)
        red = M.redact_model(m, inp.registry, person_dir=inp.person_dir, title_mode="generic")
        rs = next(r for r in red["reviews"]["months"] if r["key"] == "2026-09")
        gen = next(u["title"] for u in red["units"] if u["unit_id"] == "u_a2")
        self.assertEqual(rs["ai"]["summary"], f"{gen} 를 마쳤습니다. 동료 의뢰도 있었습니다.")
        self.assertEqual(rs["ai"]["highlights"][0]["text"], f"{gen} 완료")
        self.assertEqual(rs["ai"]["next"], [f"{gen} 후속"])
        self.assertNotIn(ACME_TITLE, json.dumps(red, ensure_ascii=False))

    def test_export_generic_and_label_clean(self):
        """실제 내보내기(JSON·HTML 가림판): 두 모드 모두 rc 0, 원래 제목·사람 가명 토큰 0건."""
        for mode in ("label", "generic"):
            cfg = self.cfg.derive({"team.unitTitleMode": mode})
            out = os.path.join(self.t.root, "exp_" + mode)
            res = EX.export(R.RUN_ID, ["json", "html"], ["redacted"], out, paths=self.t.paths, cfg=cfg,
                            inputs=self.inp, model=self.m)
            self.assertEqual(res.rc, 0, (mode, res.failed))
            for f in res.files:
                with open(os.path.join(out, *f["path"].split("/")), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("[사람#a1b2c3]", text, (mode, f["path"]))
                if mode == "generic":
                    for t in self.originals:
                        self.assertNotIn(t, text, (mode, f["path"], t))

    def test_backstop_blocks_leftover(self):
        """안전망: 가림판 검사가 `[사람#hex]` 와 일반 제목으로 가린 원래 제목을 찾는다(남으면 가림판을 만들지 않는다)."""
        red = M.redact_model(self.m, self.inp.registry, person_dir=self.inp.person_dir, title_mode="generic")
        self.assertEqual(M.redaction_violations(red, self.inp.person_dir, extra=EX.hidden_titles(self.m, red)), [])
        self.assertIn(ACME_TITLE, EX.hidden_titles(self.m, red))
        bad = copy.deepcopy(red)
        bad["reviews"]["months"][0]["ai"] = {"summary": "[사람#a1b2c3] 건", "highlights": [], "relations": [],
                                             "next": [f"{ACME_TITLE} 후속"], "by": "ai"}
        hits = M.redaction_violations(bad, self.inp.person_dir, extra=EX.hidden_titles(self.m, red))
        self.assertIn("reviews.months[0].ai.summary", hits)
        self.assertIn("reviews.months[0].ai.next[0]", hits)


class QueueTargetTest(unittest.TestCase):
    """W2 검토 C14: H04(이름 병합) 질문 대상 = 공백을 지운 단위업무 제목 쌍 — 가림판에 남고 이름 검사를 피했다."""

    def test_h04_target_dropped_and_shapes_whitelisted(self):
        run = R.rich_run()
        run.hier_queue = list(run.hier_queue) + [
            {"qid": "ab12ab12ab12", "code": "H04", "target": "acme단가협상안검토|acme단가협상안정리", "impact_min": 300,
             "evidence_keys": [], "proposal": {"title": "이름병합애매", "ask": "같은 것인가요?", "options": ["같다", "다르다"],
                                               "area": "분류"}, "status": "open"},
            {"qid": "cd34cd34cd34", "code": "H04", "target": "동료둘요청단가협상안검토|동료둘요청단가협상안정리",
             "impact_min": 200, "evidence_keys": [], "proposal": {"title": "이름병합애매"}, "status": "open"},
            {"qid": "ef56ef56ef56", "code": "H03", "target": "pr_1", "impact_min": 100, "evidence_keys": [],
             "proposal": {"title": "새과제확인"}, "status": "open"},
            {"qid": "0a0a0a0a0a0a", "code": "H01", "target": "임의 제목 글", "impact_min": 90, "evidence_keys": [],
             "proposal": {"title": "과제미정"}, "status": "open"}]
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        m, inp = build(run, t)
        red = M.redact_model(m, inp.registry, person_dir=inp.person_dir, title_mode="generic")
        by = {q["qid"]: q["target"] for q in red["queue"]}
        self.assertIsNone(by["ab12ab12ab12"])
        self.assertIsNone(by["cd34cd34cd34"])
        self.assertIsNone(by["0a0a0a0a0a0a"])                          # 모양 허용 목록 밖
        self.assertEqual(by["ef56ef56ef56"], "pr_1")
        self.assertEqual(by["dd44ee55ff66"], "grp:0123456789ab")
        self.assertEqual(by["aa11bb22cc33"], "2026-09-23")
        self.assertTrue(any(v and v.startswith("u_") for v in by.values()))
        blob = json.dumps(red, ensure_ascii=False)
        self.assertNotIn("acme단가", blob)
        self.assertNotIn("동료둘", blob)
        self.assertEqual(M.redaction_violations(red, inp.person_dir), [])

    def test_violations_catch_space_stripped_names(self):
        """이름 검사: 여러 낱말 이름은 공백을 지운 형(·소문자형)도 찾는다 — 한 낱말 이름의 대소문자는 그대로."""
        pd = {"people": {"w1": {"names": ["동료 둘"]}, "w2": {"names": ["Acme Kim"]}, "w3": {"names": ["Support"]}}}
        self.assertEqual(M.redaction_violations({"a": "동료둘요청"}, pd), ["a"])
        self.assertEqual(M.redaction_violations({"a": "acmekim단가"}, pd), ["a"])
        self.assertEqual(M.redaction_violations({"a": "x [사람#a1b2c3] y"}, pd), ["a"])
        self.assertEqual(M.redaction_violations({"a": "SUPPORT", "b": "동료 #2"}, pd), [])


class CanaryTest(unittest.TestCase):
    """RPT-31 · T-07: 이름 20개·카나리아를 심은 자료 → 가림판 모델·HTML·CSV 에 이름·카나리아·키 0건."""

    def test_redacted_outputs_clean(self):
        run, names, sel = canary_run()
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        cfg = W.cfg()
        m, inp = build(run, t, cfg)
        full_txt = M.model_bytes(m).decode("utf-8")
        for nm in names:
            self.assertIn(nm, full_txt)                                # 전체판에 있어야 시험이 유효
        out = os.path.join(t.root, "exp")
        res = EX.export(R.RUN_ID, ["html", "csv", "json"], ["full", "redacted"], out, paths=t.paths, cfg=cfg,
                        inputs=inp, model=m, extra_needles=[c.value for c in sel])
        self.assertEqual(res.rc, 0, res.failed)
        red_files = [f for f in res.files if f["variant"] == "redacted"]
        self.assertEqual(len(red_files), 17)                           # html + json + csv 15
        full_hit = False
        for f in res.files:
            with open(os.path.join(out, *f["path"].split("/")), "rb") as fh:
                data = fh.read()
            if f["variant"] == "full":
                full_hit = full_hit or bool(find_canaries(data, sel))
                continue
            self.assertEqual(find_canaries(data, sel), [], f["path"])
            text = data.decode("utf-8-sig")
            for nm in names:
                self.assertNotIn(nm, text, f["path"])
            self.assertFalse(KEY_RX.search(text), f["path"])
        self.assertTrue(full_hit)

    def test_redacted_blocked_when_name_leaks(self):
        """R §11: 가림판 검사 실패 → 가림판 만들지 않음(rc 1, 필드 경로만), 전체판은 만듦."""
        run = R.rich_run()
        run.registry = copy.deepcopy(R.REGISTRY)
        run.registry["projects"][0]["name"] = "김철수 과제"            # 사람 사전 이름이 과제 이름에(가림 대상 아님)
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        cfg = W.cfg()
        m, inp = build(run, t, cfg)
        out = os.path.join(t.root, "exp")
        res = EX.export(R.RUN_ID, ["json", "csv"], ["full", "redacted"], out, paths=t.paths, cfg=cfg, inputs=inp, model=m)
        self.assertEqual(res.rc, 1)
        self.assertTrue(all(f["variant"] == "full" for f in res.files))
        self.assertTrue(os.path.isfile(os.path.join(out, "report_model.json")))
        self.assertFalse(os.path.exists(os.path.join(out, "report_model_redacted.json")))
        reason = res.failed[0]["reason"]
        self.assertIn("projects[", reason)
        self.assertNotIn("김철수", reason)                               # 값은 보이지 않는다


if __name__ == "__main__":
    unittest.main()
