# -*- coding: utf-8 -*-
r"""WP-22 단위업무 라벨 시험 — H §4.6~§4.8 · §10 · §1.4(role_id) · 계약 §4.4.

- unit_inputs: 시간 코어 단위업무(tasks.json 행 모양) + 특징 + 귀속 행 → 역할별 증거(boundary·msg·doc·meet·app·manual),
  앱 범주 분·회의 분·PC 밖 분·투입(정수 분 표 우선)·흔적 종류·제목 요지. 입력을 바꾸지 않는다(H-I5).
- unit_rule_label: 수동 라벨(user) · 결정 토큰(경계 토큰이 엇갈리면 쓰지 않음) · 설정 섭동.
- field_func·decide_wtype: 팀 규칙 then.field·then.wtype · 본인 기본 분야 · 앱 힌트(카탈로그 app_id 대조).
- decide_stance·ax_link·role_id.
"""
import copy
import unittest

from lm27.hier.unitlabel import (RuleLabel, ax_link, decide_stance, decide_wtype, field_func, role_id, unit_inputs,
                                 unit_rule_label)
from tests.fixtures.wp22 import hierkit as K


def scenario():
    F = K.F
    feats = [
        F("m1", "mail", "[과제:P-0007] 공차 해석 요청", key="mk1", conv="tc1", direction="in", act="request", t=1000,
          subject="[과제:P-0007] 공차 해석 요청", dom_labels=["고객사:C01"]),
        F("m2", "mail", "진행 공유 부탁드립니다", key="mk2", conv="tc1", direction="out", act="request", t=2000,
          subject="진행 공유"),
        F("mi", "mail", "중간 보고", key="mki", conv="tc1", direction="out", act="report", t=3000, subject="중간 보고"),
        F("m3", "mail", "RE: 공차 해석 결과 송부", key="mk3", conv="tc1", direction="out", act="report", t=5000,
          subject="RE: 공차 해석 결과 송부", names=(("dB", "결과.pptx"),), fams=["dB"]),
        F("f1", "file", "공차해석_v3", fams=["dA"], names=(("dA", "공차해석_v3.xlsx"),), t=1500, exts=[".xlsx"]),
        F("f2", "file", "공차해석_v4", fams=["dA"], names=(("dA", "공차해석_v4.xlsx"),), t=2500, exts=[".xlsx"]),
        F("w1", "win", "공차 모델 - Fluent", app="ansys_fluent", app_cat="해석", t=1200, t_end=1800),
        F("c1", "cal", "공차 검토 회의", t=4000, t_end=4600, subject="공차 검토 회의", flags=["organizer_me"]),
        F("u1", "manual", "확인", refs=["mk1"], t=900),
        F("zz", "mail", "무관한 메일", key="mkz", conv="tc9", direction="in", t=1000),
    ]
    task = {"unit_id": "u_1", "kind": "S1", "conv": "tc1", "peer": K.fake_who(1),
            "docs": {"dA": {"n": 2, "ops": {"save": 1, "export": 0, "attach": 1}},
                     "dB": {"n": 1, "ops": {"save": 0, "export": 0, "attach": 0}}},
            "cycles": [{"s": 1000, "sb": "S1", "e": 5000, "eb": "E1", "s_ref": "m1", "e_ref": "m3",
                        "interim": [[3000, "E1p"]], "unstarted": False}],
            "first_key": "mk1", "follow_of": None, "effort_s": 7200, "label": "공차 해석"}
    attrib = [{"slot": 1200, "target": "u_1", "sec": 300, "level": "L3PC", "obs": "", "app": "ansys_fluent", "fam": ""},
              {"slot": 1500, "target": "u_1", "sec": 300, "level": "L3PC", "obs": "", "app": "excel", "fam": "dA"},
              {"slot": 4200, "target": "u_1", "sec": 300, "level": "L2회의", "obs": "", "app": "", "fam": ""},
              {"slot": 6000, "target": "u_1", "sec": 300, "level": "L5공백", "obs": "", "app": "", "fam": ""},
              {"slot": 6000, "target": "B_COMM", "sec": 300, "level": "L7버킷", "obs": "", "app": "", "fam": ""}]
    tables = {"envelope_daily": {"cols": ["date", "regular", "extended", "night", "holiday"], "rows": []},
              "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"], "rows": [["2026-09-01", "u_1", "regular", 25]]}}
    return feats, task, attrib, tables


class UnitInputsTest(unittest.TestCase):
    def test_roles_and_minutes(self):
        feats, task, attrib, tables = scenario()
        before = copy.deepcopy((task, attrib, tables))
        units = unit_inputs([task], feats, attrib, None, cfg=K.cfg(), team_tables=tables)
        self.assertEqual(before, (task, attrib, tables))                       # 입력 불변(H-I5)
        u = units["u_1"]
        roles = {}
        for f, w, r in u.ev:
            roles.setdefault(r, []).append((f.id, w))
        self.assertEqual(sorted(x for x, _w in roles["boundary"]), ["m1", "m3", "mi"])
        self.assertEqual(roles["msg"], [("m2", 1.0)])
        self.assertEqual(sorted(roles["doc"]), [("fam:dA", 1.5), ("fam:dB", 1.0)])   # 강도 3(첨부) 1.5 · 강도 2 1.0
        self.assertEqual(roles["meet"], [("c1", 1.0)])
        self.assertEqual(sorted(x for x, _w in roles["app"]), ["app:u_1:ansys_fluent", "app:u_1:excel"])
        self.assertEqual(roles["manual"], [("u1", 1.0)])
        self.assertNotIn("zz", {f.id for f, _w, _r in u.ev})
        self.assertEqual(dict(u.app_min), {"사무": 5, "해석": 5})
        self.assertEqual((u.meet_min, u.offpc_min, u.effort_min), (5, 5, 25))   # 투입 = 정수 분 표
        self.assertEqual(dict(u.kinds), {"메일수신": 1, "메일발신": 3, "회의": 1, "문서": 2, "앱": 2, "수동": 1})
        self.assertEqual(u.subjects[:2], ("[과제:P-0007] 공차 해석 요청", "RE: 공차 해석 결과 송부"))
        self.assertEqual(u.fam_names["dA"], "공차해석_v4.xlsx")                 # 가장 최근 이름
        self.assertTrue(u.peers_ext)
        self.assertEqual((u.organizer_meetings, u.sent_requests), (1, 1))
        self.assertEqual(decide_stance(u), "LEAD")
        app = next(f for f, _w, r in u.ev if r == "app" and f.app == "ansys_fluent")
        self.assertIn("공차", app.toks)                                        # 그 앱 L3 슬롯과 겹치는 창 특징의 합집합

    def test_effort_fallbacks_and_basis(self):
        feats, task, attrib, _t = scenario()
        u = unit_inputs([task], feats, attrib, None, cfg=K.cfg())["u_1"]
        self.assertEqual(u.effort_min, 20)                                     # 정수 분 표 없으면 귀속 초
        u = unit_inputs([task], feats, [], None, cfg=K.cfg())["u_1"]
        self.assertEqual(u.effort_min, 120)                                    # 귀속도 없으면 effort_s
        u = unit_inputs([task], feats, attrib, None, cfg=K.cfg(), slot_basis={1200: "C4L", 6000: "C1"})["u_1"]
        self.assertEqual(u.offpc_min, 5)                                       # 근거로 PC 밖 판정(다리)

    def test_unit_task_object(self):
        from types import SimpleNamespace as NS
        feats, task, attrib, _t = scenario()
        cyc = NS(s=1000, sb="S1", e=5000, eb="E1", s_ref="m1", e_ref="m3", interim=[(3000, "E1p")], unstarted=False)
        t = NS(id="u_1", kind="S1", conv="tc1", convs=set(), peer="", docs={"dA": 3, "dB": 2}, cycles=[cyc],
               first_key="mk1", follow_of=None, label="", adds=[(2000, "m2", "mk2")], meet_refs=[], app="")
        u = unit_inputs([t], feats, attrib, None, cfg=K.cfg())["u_1"]
        self.assertEqual(dict(u.fams), {"dA": 3, "dB": 2})
        self.assertIn("m2", {f.id for f, _w, r in u.ev if r == "msg"})


class ManualUnitTitleTest(unittest.TestCase):
    """W2 검토 C08 — 토큰 해시 키('manual:t:<해시>')의 MANUAL 업무도 그 수동 기록을 증거로 갖고, 사용자가 적은 글이 제목 재료다
    (시간 코어 표지 'MANUAL:t:…' 대신). 어느 기록인지 하나로 정해지지 않으면 붙이지 않는다."""
    DAY = 86400 * 2000

    def task(self):
        return {"unit_id": "u_man", "kind": "MANUAL", "label": "MANUAL:t:1e9f7be2940441f0",
                "first_key": "manual:t:1e9f7be2940441f0",
                "cycles": [{"s": self.DAY, "sb": "S2M", "e": self.DAY + 86400, "eb": "E3M", "s_ref": "수동",
                            "e_ref": "수동"}]}

    def test_manual_text_is_title(self):
        from lm27.hier import groups as G
        man = K.F("mr1", "manual", "사내 안전 교육 이수", t=self.DAY, subject="사내 안전 교육 이수")
        other = K.F("mr2", "manual", "다른 날 기록", t=self.DAY + 3 * 86400, subject="다른 날 기록")
        u = unit_inputs([self.task()], [man, other], None, None, cfg=K.cfg())["u_man"]
        self.assertEqual([(f.id, r) for f, _w, r in u.ev], [("mr1", "manual")])
        self.assertEqual(u.subjects, ("사내 안전 교육 이수",))
        g = G.Group("grp:000000000001", "a", "u_man", ("u_man",), 60)
        self.assertEqual(G.rule_title(G.title_material(g, {"u_man": u}), {"reg": None, "cfg": K.cfg()}),
                         ("사내 안전 교육 이수", "subject"))

    def test_ambiguous_record_not_linked(self):
        a = K.F("mr1", "manual", "기록 가", t=self.DAY, subject="기록 가")
        b = K.F("mr2", "manual", "기록 나", t=self.DAY, subject="기록 나")
        u = unit_inputs([self.task()], [a, b], None, None, cfg=K.cfg())["u_man"]
        self.assertEqual((u.ev, u.subjects), ((), ()))

    def test_other_units_keep_spec_subjects(self):
        """MANUAL 이 아닌 업무는 H §5.3 그대로 — 확인 응답 같은 수동 기록 글을 제목 재료로 쓰지 않는다."""
        feats, task, attrib, _t = scenario()
        task = dict(task, cycles=[dict(task["cycles"][0], s_ref=None, e_ref=None)], conv="")
        fs = [f for f in feats if f.kind == "file"] + [K.F("u1", "manual", "확인 응답 글", refs=["mk1"], t=900,
                                                          subject="확인 응답 글")]
        u = unit_inputs([task], fs, attrib, None, cfg=K.cfg())["u_1"]
        self.assertIn("u1", {f.id for f, _w, r in u.ev if r == "manual"})
        self.assertEqual(u.subjects, ())


class RuleLabelTest(unittest.TestCase):
    def test_token_and_manual(self):
        reg = K.golden_reg()
        feats, task, attrib, tables = scenario()
        u = unit_inputs([task], feats, attrib, None, cfg=K.cfg(), team_tables=tables)["u_1"]
        rl = unit_rule_label(u, reg, K.cfg())
        self.assertEqual((rl.project, rl.source, rl.conf, rl.domain), ("P-0007", "token", "h", "DEV"))
        self.assertTrue(any("token" in w for w in rl.why))
        man = K.F("x", "manual", "기록", manual={"project_id": "P-0012"})
        u2 = K.U("u_2", "MANUAL", [(man, 1.0, "manual")])
        rl2 = unit_rule_label(u2, reg, K.cfg())
        self.assertEqual((rl2.project, rl2.source, rl2.domain), ("P-0012", "user", "EXT"))

    def test_conflicting_boundary_tokens(self):
        reg = K.golden_reg()
        a = K.F("a", "mail", "[과제:P-0007] 요청")
        b = K.F("b", "mail", "[과제:P-0011] 보고")
        rl = unit_rule_label(K.U("u", "S1", [(a, 2.0, "boundary"), (b, 2.0, "boundary")]), reg, K.cfg())
        self.assertNotEqual(rl.source, "token")
        c = K.F("c", "mail", "[과제:P-0999] 요청")
        rl = unit_rule_label(K.U("u", "S1", [(c, 2.0, "boundary")]), reg, K.cfg())
        self.assertEqual(rl.source, "none")                                    # 모르는 과제 토큰은 결정 토큰이 아니다

    def test_cfg_perturbation(self):
        reg = K.golden_reg()
        g = K.golden()["HG11"]["unit"]
        ev = [(K.F(e["feat"]["id"], e["feat"]["kind"], e["feat"]["text"]), e["w"], e["role"]) for e in g["ev"]]
        u = K.U("u_b", "SELF", ev)
        self.assertEqual(unit_rule_label(u, reg, K.cfg()).source, "rule")
        self.assertEqual(unit_rule_label(u, reg, K.cfg({"hier.unit.confirm": 0.95})).source, "rule_probable")
        self.assertEqual(unit_rule_label(u, reg, K.cfg({"hier.unit.minMass": 40.0})).source, "none")


class FieldWtypeTest(unittest.TestCase):
    def test_rules_and_person_default(self):
        t = dict(K.GOLDEN_TEAM)
        t["rules"] = [{"id": "TR003", "if": {"ext": ".zmx"}, "then": {"field": "OPT"}, "w": 2.0, "status": "active"},
                      {"id": "TR004", "if": {"token": "현장점검"}, "then": {"wtype": "FIELD"}, "status": "active"}]
        local = {"schema": "lm27.registry_local/1", "person": {"default_field": "ELEC", "default_func": ""}}
        reg = K.golden_reg(team=t, local=local)
        f = K.F("f", "file", "렌즈.zmx", exts=[".zmx"])
        u = K.U("u", "SELF", [(f, 1.5, "doc")], effort_min=60)
        rl = RuleLabel(None, 0.0, "none", "l", (), "UNC")
        ff = field_func(u, reg, rl, K.cfg())
        self.assertEqual(ff.field, "OPT")                                      # 팀 규칙 2.0 + 키워드 '렌즈' 1.0 > 본인 1.0
        self.assertEqual(ff.scores["field"]["ELEC"], 1.0)
        g = K.F("g", "mail", "현장점검 일정")
        u2 = K.U("u2", "S1", [(g, 2.0, "boundary")], effort_min=60)
        self.assertEqual(decide_wtype(u2, ff, rl, reg, K.cfg())[:2], ("FIELD", "m"))

    def test_app_hint_and_fallback(self):
        reg = K.golden_reg()
        rl = RuleLabel(None, 0.0, "none", "l", (), "UNC")
        w = K.F("w", "win", "", app="creo_parametric", app_cat="CAD")
        u = K.U("u", "APP", [(w, 1.0, "app")], app_min={"CAD": 100}, effort_min=100)
        ff = field_func(u, reg, rl, K.cfg())
        self.assertEqual((ff.field, ff.func), ("MECH", "DESIGN"))
        self.assertEqual(ff.scores["field"]["MECH"], 4.0)                       # 앱 힌트 2.0 + 범주 CAD 2.0
        empty = K.U("e", "SELF", [])
        ff = field_func(empty, reg, rl, K.cfg())
        self.assertEqual((ff.field, ff.field_src, ff.func, ff.func_src), ("ETC", "fallback", "ETC", "fallback"))
        wt = decide_wtype(empty, ff, rl, reg, K.cfg())
        self.assertEqual(wt[:2], ("OFFICE", "m"))
        with self.assertRaises(ValueError):
            decide_wtype(empty, ff, rl, None, K.cfg())

    def test_offpc_only_field(self):
        reg = K.golden_reg()
        rl = RuleLabel(None, 0.0, "none", "l", (), "UNC")
        u = K.U("u", "SELF", [], offpc_min=60, effort_min=100)
        ff = field_func(u, reg, rl, K.cfg())
        self.assertEqual(decide_wtype(u, ff, rl, reg, K.cfg())[:2], ("FIELD", "l"))


class StanceAxRoleTest(unittest.TestCase):
    def test_stance(self):
        a = K.F("a", "mail", "도면 검토 요청드립니다")
        self.assertEqual(decide_stance(K.U("u", "S1", [(a, 2.0, "boundary")], effort_min=20)), "REVIEW")
        self.assertEqual(decide_stance(K.U("u", "S1", [(a, 2.0, "boundary")], effort_min=40)), "DO")
        self.assertEqual(decide_stance(K.U("u", "COORD", [])), "COORD")

    def test_ax_link(self):
        t = dict(K.GOLDEN_TEAM)
        t["projects"] = [dict(p) for p in K.GOLDEN_TEAM["projects"]]
        t["projects"][2]["domain"] = "COM"
        t["projects"][2]["ax_link"] = True
        reg = K.golden_reg(team=t)
        u = K.U("u", "S1", [(K.F("a", "mail", "회의록 정리"), 2.0, "boundary")])
        self.assertTrue(ax_link(u, "COM", reg, "P-0011"))                      # 과제 단위 지정
        self.assertFalse(ax_link(u, "DEV", reg, "P-0007"))
        u2 = K.U("u", "S1", [(K.F("a", "mail", "자동화 프롬프트 정리"), 2.0, "boundary")])
        self.assertTrue(ax_link(u2, "DEV", reg, None))                         # 약한 낱말 2개
        self.assertFalse(ax_link(u2, "DEV", reg, None, K.cfg({"hier.ax.minHits": 3})))

    def test_role_id(self):
        self.assertEqual(role_id(None, "ETC", "ETC"), role_id("UNC", "ETC", "ETC"))
        self.assertRegex(role_id("pr_3", "THERM", "ANALYSIS"), r"^r_[0-9a-f]{6}$")


if __name__ == "__main__":
    unittest.main()
