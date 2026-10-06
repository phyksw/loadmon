# -*- coding: utf-8 -*-
"""WP-31 가림판 모델(R §9.2.4 · §3.6 · §11 · G-R8 · RPT-31 · T-07).

가림판은 전체판에서 지우는 방식이 아니라 **허용 목록으로 새로 만든다**. 직렬화 바이트에 사람 사전 이름(한글 2자 이상·ASCII 4자
이상)·who_key·로컬 키 모양·카나리아가 0건이어야 하고, 하나라도 있으면 가림판을 만들지 않는다(rc 1 · 필드 경로만).
"""
from __future__ import annotations

import copy
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
        cls.srun = R.rich_run(title_over={"u_a3": "김철수 요청 전원부 해석"})
        cls.m, cls.inp = build(cls.srun, cls.t)
        cls.red = M.redact_model(cls.m, cls.inp.registry, person_dir=cls.inp.person_dir)

    @classmethod
    def tearDownClass(cls):
        cls.t.cleanup()

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
