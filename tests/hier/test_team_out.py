# -*- coding: utf-8 -*-
r"""WP-22 팀 묶음 라벨 조각 시험 — H §12.4 · §7.6 · T-H11(어휘 코드·role_id 재계산·개인 L_ 코드 maps_to) ·
T-H12(개인 과제 L-… → proposal_id) · T-H13(제안 [빼기] → UNC 역할, 시간 불변) · G-H12(형식) · 계약 §3.18 · X-230."""
import re
import unittest

from lm27.hier.apply import UnitLabel
from lm27.hier.proposals import ProposalQueue
from lm27.hier.team_out import generic_title, team_parts
from lm27.hier.unitlabel import role_id
from tests.fixtures.wp22 import hierkit as K

LOCAL = {"schema": "lm27.registry_local/1",
         "projects": [{"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "proposal_id": "pr_1",
                       "copilot_desc": "광센서 선행"}],
         "vocab_add": {"fields": [{"code": "L_PHOTO", "name": "포토닉스", "maps_to": "OPT"},
                                  {"code": "L_MISC", "name": "개인기타"}]},
         "person": {"default_field": "L_PHOTO", "default_func": ""}}


def lab(uid, project=None, proposal=None, field="OPT", func="ANALYSIS", wtype="DEV", title="공차 해석"):
    return UnitLabel(unit_id=uid, project=project, proposal_id=proposal, field=field, func=func, wtype=wtype,
                     title=title, ax_link=False)


class TeamPartsTest(unittest.TestCase):
    def setUp(self):
        self.reg = K.golden_reg(local=LOCAL)
        self.q = ProposalQueue()
        self.q.items.append({"proposal_id": "pr_1", "kind": "project", "label": "광센서 선행", "ukey": "광센서선행",
                             "domain_guess": "DEV", "status": "accepted_local", "groups": [], "sources": [],
                             "history": []})
        self.q.items.append({"proposal_id": "pr_2", "kind": "project", "label": "방열 모듈", "ukey": "방열모듈",
                             "domain_guess": "MP", "status": "pending", "groups": [], "sources": [], "history": []})
        self.labels = {"u_1": lab("u_1", "P-0007"), "u_2": lab("u_2", "L-0001", "pr_1", field="L_PHOTO"),
                       "u_3": lab("u_3", None, "pr_2", field="L_MISC", wtype="OFFICE"),
                       "u_4": lab("u_4", None, None, field="ETC", func="ETC", title=""),
                       "u_5": lab("u_5", "P-9904", None, func="ADMIN", title="정산"),
                       "u_6": lab("u_6", "P-0007", title="공차 해석 2")}

    def test_parts(self):
        tp = team_parts(self.labels, self.reg, self.q, None, cfg=K.cfg(), starts={"u_1": 10, "u_6": 5})
        self.assertEqual(tp["projects"], [{"project_id": "P-0007", "domain": "DEV"},
                                          {"project_id": "P-9904", "domain": "COM"}])
        self.assertEqual([p["proposal_id"] for p in tp["proposals"]], ["pr_1", "pr_2"])
        self.assertEqual(tp["proposals"][1]["domain_guess"], "MP")
        u2 = tp["units"]["u_2"]
        r2 = next(r for r in tp["roles"] if r["role_id"] == u2["role_id"])
        self.assertEqual((r2["project_id"], r2["proposal_id"], r2["field"]), (None, "pr_1", "OPT"))   # T-H11·T-H12
        self.assertEqual(u2["role_id"], role_id("pr_1", "OPT", "ANALYSIS"))
        r3 = next(r for r in tp["roles"] if r["role_id"] == tp["units"]["u_3"]["role_id"])
        self.assertEqual(r3["field"], "ETC")                                       # maps_to 없는 개인 코드 → ETC
        r4 = next(r for r in tp["roles"] if r["role_id"] == tp["units"]["u_4"]["role_id"])
        self.assertEqual((r4["project_id"], r4["proposal_id"]), (None, None))
        self.assertEqual(tp["units"]["u_4"]["title_mode"], "generic")              # 빈 제목 → generic
        self.assertEqual(tp["units"]["u_4"]["title"], "기타·기타 단위업무 #1")
        self.assertEqual(tp["person"], {"field": "OPT"})
        for r in tp["roles"]:
            self.assertRegex(r["role_id"], r"^r_[0-9a-f]{6}$")
            self.assertIn(r["field"], self.reg.vocab["fields"])
            self.assertIn(r["function"], self.reg.vocab["functions"])
            self.assertFalse(str(r["field"]).startswith("L_"))
            self.assertTrue(r["project_id"] is None or re.fullmatch(r"P-\d{4}", r["project_id"]))
        for u in tp["units"].values():
            self.assertIn(u["activity_type"], ("DEV", "OFFICE", "FIELD", "PM", "PL", "SUPPORT", "EDU"))
            self.assertLessEqual(len(u["title"]), 40)
        self.assertNotIn("L-0001", repr(tp))                                       # 개인 과제 ID 는 팀에 의미 없음

    def test_generic_mode_overrides_drop(self):
        """T-H13 — 제안 [빼기] → 그 역할 UNC(project_id·proposal_id null), 단위업무는 그대로."""
        ov = {"units": {"u_1": "title", "u_6": "detail"}, "proposals": {"pr_2": "drop"}}
        tp = team_parts(self.labels, self.reg, self.q, ov, cfg=K.cfg(), starts={"u_1": 10, "u_6": 5})
        self.assertEqual(tp["units"]["u_6"]["title"], generic_title(self.reg, "OPT", "ANALYSIS", 1))
        self.assertEqual(tp["units"]["u_1"]["title"], generic_title(self.reg, "OPT", "ANALYSIS", 2))   # 역할 안 시작 순
        r3 = next(r for r in tp["roles"] if r["role_id"] == tp["units"]["u_3"]["role_id"])
        self.assertEqual((r3["project_id"], r3["proposal_id"]), (None, None))
        self.assertEqual([p["proposal_id"] for p in tp["proposals"]], ["pr_1"])
        self.assertEqual(set(tp["units"]), set(self.labels))                       # 단위업무는 빠지지 않는다
        tp = team_parts(self.labels, self.reg, self.q, None, cfg=K.cfg(), title_mode="generic")
        self.assertTrue(all(u["title_mode"] == "generic" for u in tp["units"].values()))
        tp = team_parts(self.labels, self.reg, self.q, None, cfg=K.cfg(),
                        text_check=lambda s, n, f: None if "2" in s else s)
        self.assertEqual(tp["units"]["u_6"]["title_mode"], "generic")              # 팀 라벨 검사 실패 → generic
        self.assertEqual(tp["units"]["u_1"]["title"], "공차 해석")
        tp = team_parts(self.labels, self.reg, self.q, None, cfg=K.cfg(), text_check=lambda s, n, f: None)
        self.assertEqual(tp["proposals"][0]["label"], "개발 프로젝트 새 과제 #1")

    def test_bundle_valid(self):
        """G-H12 — 이 조각을 실은 팀 묶음이 `validate_team_bundle`(WP-27) 을 막힘 없이 통과, role_id 식이 같다."""
        from lm27.team import schema as TS
        from tests.fixtures.wp27 import bundles as WB
        obj = WB.make_bundle(WB.person_key(1), "2026-09-01", "2026-09-30", built_at="2026-10-01T09:00:00+09:00",
                             n_units=6, dense=True)
        uids = [u["unit_id"] for u in obj["units"]]
        self.assertEqual(len(uids), 6)
        labs = dict(zip(uids, [self.labels[k] for k in sorted(self.labels)], strict=True))
        tp = team_parts(labs, self.reg, self.q, None, cfg=K.cfg())
        obj["projects"], obj["proposals"], obj["roles"] = tp["projects"], tp["proposals"], tp["roles"]
        for u in obj["units"]:
            u.update(tp["units"][u["unit_id"]])
        obj["person"]["field"] = tp["person"].get("field", obj["person"]["field"])
        rid = obj["units"][0]["role_id"]
        for w in obj["workflows"]:
            w["role_id"], w["units"] = rid, [obj["units"][0]["unit_id"]]
        for m in obj["agentic"]["matches"]:
            m["role_id"] = rid
        for sa in obj["agentic"]["subagents"]:
            sa["role_id"] = rid
        reg_obj = WB.registry(projects=[{"id": p["id"], "name": p["name"], "domain": p["domain"], "aliases": [],
                                         "keywords": [], "codenames": [], "status": "active", "merged_into": None}
                                        for p in K.GOLDEN_TEAM["projects"] if p.get("status", "active") == "active"])
        errs = TS.validate_team_bundle(obj, reg_obj, side="client")
        self.assertEqual(TS.blocking(errs), [])
        for r in tp["roles"]:
            self.assertEqual(r["role_id"], TS.role_id_of(r["project_id"] or r["proposal_id"], r["field"], r["function"]))


if __name__ == "__main__":
    unittest.main()
