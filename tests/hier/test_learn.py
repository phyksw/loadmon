# -*- coding: utf-8 -*-
r"""WP-22 사용자 수정·규칙 학습 시험 — H §11.3~§11.5 · T-H08(수정이 증거 키로 따라감) · T-H09(같은 스레드 → 다음 실행
꼬리표) · T-H10(정밀도 미달 → retired) · HG36~HG38. 학습 재료는 사람 수정뿐이다(H-I6)."""
import json
import unittest

from lm27.hier import learn as LR
from lm27.hier.rules import tag_rows, tags_from_rows
from tests.fixtures.wp22 import hierkit as K


def corr(cid, at, *, group="", anchor="", unit_keys=(), fam_keys=(), conv_keys=(), dir_keys=(), scope="similar", **st):
    return {"at": at, "id": cid, "scope": scope, "set": st,
            "target": {"group": group, "anchor": anchor, "unit_keys": list(unit_keys), "fam_keys": list(fam_keys),
                       "conv_keys": list(conv_keys), "dir_keys": list(dir_keys)}}


def units():
    return {"u_a": K.U("u_a", "S1", [], first_key="mk1", bkeys=frozenset({"mk1", "mk2"}), fams={"dA": 3},
                       convs=frozenset({"t1"})),
            "u_b": K.U("u_b", "SELF", [], first_key="dB|2026-09-01", fams={"dB": 2, "dC": 2}, convs=frozenset({"t2"})),
            "u_c": K.U("u_c", "S1", [], first_key="mk9", bkeys=frozenset({"mk9"}), fams={"dC": 2},
                       convs=frozenset({"t3"}))}


class ApplyCorrectionsTest(unittest.TestCase):
    def test_matching(self):
        us = units()
        cs = [corr("c1", "2026-10-01T10:00:00+09:00", anchor="mk1", project="P-0007", title="공차 해석"),
              corr("c2", "2026-10-02T10:00:00+09:00", unit_keys=["mk2"], project="P-0008"),            # 늦은 것이 이긴다
              corr("c3", "2026-10-01T11:00:00+09:00", fam_keys=["dB", "dC"], conv_keys=["t2"], wtype="FIELD"),
              corr("c4", "2026-10-01T12:00:00+09:00", group="grp:cccc", field="OPT"),
              corr("c5", "2026-10-01T13:00:00+09:00", anchor="gone", project="P-0012"),
              corr("c6", "2026-10-01T14:00:00+09:00", anchor="mk9", project="UNC")]
        got, unapplied = LR.apply_corrections(us, cs, group_of={"u_c": "grp:cccc"})
        self.assertEqual(got["u_a"]["project"], "P-0008")
        self.assertEqual(got["u_a"]["title"], "공차 해석")
        self.assertEqual(got["u_b"]["wtype"], "FIELD")
        self.assertEqual(got["u_c"]["field"], "OPT")
        self.assertIsNone(got["u_c"]["project"])                              # '과제 없음'(사용자 확정)
        self.assertEqual(unapplied, ["c5"])
        bad = corr("c7", "2026-10-03T00:00:00+09:00", anchor="mk1", project=7, field=["OPT"], title="되는 제목")
        got2, _ = LR.apply_corrections(us, cs + [bad], group_of={"u_c": "grp:cccc"})
        self.assertEqual(got2["u_a"]["project"], "P-0008")                    # 형이 틀린 값은 그 필드만 무시
        self.assertEqual((got2["u_a"]["field"] if "field" in got2["u_a"] else None, got2["u_a"]["title"]),
                         (None, "되는 제목"))

    def test_follows_evidence_keys(self):
        """T-H08 — 자체 업무가 나중에 의뢰 메일을 얻어 unit_id 가 바뀌어도 증거 키(문서군·대화)로 따라간다."""
        c = corr("c1", "2026-10-01T10:00:00+09:00", fam_keys=["dA"], conv_keys=["t1"], project="P-0007")
        new_units = {"u_new": K.U("u_new", "S1", [], first_key="mk-late", fams={"dA": 3}, convs=frozenset({"t1"}))}
        got, unapplied = LR.apply_corrections(new_units, [c])
        self.assertEqual(got["u_new"]["project"], "P-0007")
        self.assertEqual(unapplied, [])

    def test_load(self):
        with K.TmpTree() as t:
            p = t.paths.hier_local_file("corrections.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps(corr("c2", "2026-10-02T00:00:00+09:00", anchor="a", project="P-0007"), ensure_ascii=False),
                     "{broken", json.dumps(corr("c1", "2026-10-01T00:00:00+09:00", anchor="a", project="P-0008"),
                                           ensure_ascii=False), "[]"]
            p.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
            cs = LR.load_corrections(t.paths)
            self.assertEqual([c["id"] for c in cs], ["c1", "c2"])
            self.assertEqual(LR.load_corrections(path=t.paths.hier_local_file("none.jsonl")), [])


class LearnRulesTest(unittest.TestCase):
    def test_incremental_and_supersede(self):
        us = units()
        feats = {"u_a": [K.F("m", "mail", "광정렬 지그 요청"), K.F("f", "file", "광정렬_지그.xlsx")]}
        df = {"광정렬": 1, "지그": 1}
        c1 = corr("c1", "2026-10-01T10:00:00+09:00", anchor="mk1", conv_keys=["t0123456789abcdef"],
                  fam_keys=["dA", "dG@s1+s2"], dir_keys=["s0011223344556677"], project="P-0007")
        rules, done = LR.learn_rules([c1], feats, df, 100, [], units=us, cfg=K.cfg(), today="2026-10-01")
        ids = [r["id"] for r in rules]
        self.assertIn("LK-conv-t0123456", ids)
        self.assertIn("LK-fam-dA", ids)
        self.assertNotIn("LK-fam-dG@s1+s", ids)                               # 범용 문서군 키는 배우지 않는다
        self.assertIn("LK-dir-s0011223", ids)
        self.assertEqual(done, ["c1"])
        toks = {r["if"].get("token"): r["status"] for r in rules if r["kind"] == "token"}
        self.assertEqual(toks, {"광정렬": "candidate", "지그": "candidate"})
        rules2, done2 = LR.learn_rules([c1], feats, df, 100, {"rules": rules, "learned_from": done}, units=us,
                                       cfg=K.cfg(), today="2026-10-02")
        self.assertEqual(rules2, rules)                                       # 이미 배운 기록은 다시 배우지 않는다
        c2 = corr("c2", "2026-10-03T10:00:00+09:00", anchor="mk1", conv_keys=["t0123456789abcdef"], project="P-0008")
        rules3, _ = LR.learn_rules([c1, c2], feats, df, 100, {"rules": rules, "learned_from": done}, units=us,
                                   cfg=K.cfg(), today="2026-10-03")
        conv = [r for r in rules3 if (r["if"] or {}).get("conv") == "t0123456789abcdef"]
        self.assertEqual(sorted((r["status"], r["then"]["project"]) for r in conv),
                         [("active", "P-0008"), ("superseded", "P-0007")])
        deferred, d = LR.learn_rules([corr("c9", "2026-10-04T00:00:00+09:00", anchor="none", project="P-0007")],
                                     feats, df, 100, [], units=us, cfg=K.cfg())
        self.assertEqual((deferred, d), ([], []))                             # 대상이 없으면 다음 실행으로 미룬다

    def test_app_rule(self):
        us = {"u_x": K.U("u_x", "APP", [], first_key="app:ansys_fluent|2026-09-01", app_ids={"ansys_fluent": 80, "excel": 20})}
        c = corr("c1", "2026-10-01T00:00:00+09:00", anchor="app:ansys_fluent|2026-09-01", field="THERM")
        r1, _ = LR.learn_rules([c], {}, {}, 1, [], units=us, cfg=K.cfg(), today="2026-10-01")
        self.assertEqual([(r["id"][:13], r["status"], r["then"]) for r in r1], [("LK-app-field-", "candidate",
                                                                                 {"field": "THERM"})])
        c2 = corr("c2", "2026-10-02T00:00:00+09:00", anchor="app:ansys_fluent|2026-09-01", field="THERM")
        r2, _ = LR.learn_rules([c, c2], {}, {}, 1, [], units=us, cfg=K.cfg(), today="2026-10-02")
        self.assertEqual(r2[0]["status"], "active")

    def test_next_run_tag(self):
        """T-H09 — 같은 스레드에 수정 1회 → 다음 실행(학습 규칙을 실은 레지스트리)에서 새 메시지 꼬리표 P-0007."""
        us = units()
        c = corr("c1", "2026-10-01T10:00:00+09:00", anchor="mk1", conv_keys=["t1"], project="P-0007")
        rules, _ = LR.learn_rules([c], {}, {}, 1, [], units=us, cfg=K.cfg())
        reg = K.golden_reg(learned=rules)
        fs = [K.F("new", "mail", "RE: 일정", conv="t1", key="mk-new")]
        rows = tag_rows(fs, reg, K.cfg())
        self.assertEqual(rows[0]["proj"], "P-0007")
        self.assertEqual(rows[0]["score"], 5.0)
        self.assertEqual(tags_from_rows(rows, fs, reg).msg, {"mk-new": "P-0007"})   # 시간 코어 연결 제약으로 간다
        rows0 = tag_rows(fs, K.golden_reg(), K.cfg())
        self.assertIsNone(rows0[0]["proj"])                                    # 학습 전에는 꼬리표 없음

    def test_save_load(self):
        with K.TmpTree() as t:
            self.assertEqual(LR.load_learned(t.paths)["rules"], [])
            rules = [{"id": "LT-1", "kind": "token", "if": {"token": "a"}, "then": {"project": "P-0007"}, "w": 2.5,
                      "status": "active", "support": 2, "from": ["c1"]}]
            self.assertTrue(LR.save_learned(t.paths, rules, ["c1"]))
            self.assertFalse(LR.save_learned(t.paths, rules, ["c1"]))
            got = LR.load_learned(t.paths)
            self.assertEqual((got["rules"][0]["id"], got["learned_from"]), ("LT-1", ["c1"]))
            self.assertTrue(LR.save_learned(t.paths, rules, ["c1", "c2"]))
            self.assertTrue(t.paths.hier_local_file("rules_learned.json.bak").exists())


class PrecisionTest(unittest.TestCase):
    def test_retire(self):
        """T-H10 — 학습 토큰 규칙이 5번 중 3번 틀림 → retired + 사유."""
        rule = {"id": "LT-x", "kind": "token", "if": {"token": "지그"}, "then": {"project": "P-0007"}, "status": "active"}
        labels = {}
        for i in range(5):
            labels[f"u{i}"] = {"group": f"g{i}", "project": "P-0007" if i < 2 else "P-0008",
                               "src": {"project": "user" if i % 2 else "token"}}
        out = LR.track_precision([rule], labels, {"LT-x": [f"u{i}" for i in range(5)]}, cfg=K.cfg(), today="2026-10-05")
        self.assertEqual((out[0]["status"], out[0]["hits"], out[0]["agree"], out[0]["disagree"]), ("retired", 5, 2, 3))
        self.assertEqual(out[0]["reason"], "정밀도 2/5")
        out = LR.track_precision([rule], labels, {"LT-x": ["u0", "u1"]}, cfg=K.cfg())
        self.assertEqual(out[0]["status"], "active")
        self.assertEqual(LR.retire_check(0, 0), ("active", None))


if __name__ == "__main__":
    unittest.main()
