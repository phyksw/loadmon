# -*- coding: utf-8 -*-
r"""WP-22 라벨 적용 시험 — H §6.5(우선순위·구체화·NONE·NEW·H02·분야/기능/유형 축) · §5.4(이름 우선순위·제목 캐시) ·
§11.1(level·src·conf) · H-I2(영역 유도) · H-I4(role_id) · X-252(NEW → 제안 큐, 폴백 제목 = 규칙 이름)."""
import unittest

from lm27.hier.apply import UnitLabel, apply_labels, level_of, merge_project, role_slot
from lm27.hier.groups import Group, TitleCache
from lm27.hier.proposals import ProposalQueue
from lm27.hier.unitlabel import FieldFunc, RuleLabel, role_id
from tests.fixtures.wp22 import hierkit as K

AT = "2026-10-05T10:00:00+09:00"


def team():
    t = dict(K.GOLDEN_TEAM)
    t["projects"] = list(K.GOLDEN_TEAM["projects"]) + [
        {"id": "P-0030", "name": "예산 관리", "domain": "COM", "copilot_desc": "팀 예산"},
        {"id": "P-0040", "name": "옛 과제", "domain": "DEV", "status": "retired"}]
    return t


def ans(project, conf="h", **kw):
    a = {"project": project, "field": "THERM", "func": "DESIGN", "wtype": "DEV", "title": "광학 모듈 공차 해석",
         "new": "", "dom": "", "conf": conf}
    a.update(kw)
    return {"ans": a, "by": kw.pop("by", "ai")}


class MergeProjectTest(unittest.TestCase):
    def test_extra_rules(self):
        reg = K.golden_reg(team=team())
        dom = {"project": "P-9904", "source": "domain_rule", "conf": "m", "cands": [], "domain": "COM"}
        self.assertEqual(merge_project(dom, {"project": "P-0030", "conf": "m"}, reg), ("P-0030", "ai_m", None))
        self.assertEqual(merge_project(dom, {"project": "P-0007", "conf": "h"}, reg), ("P-9904", "domain_rule", "H02"))
        self.assertEqual(merge_project(dom, {"project": "NONE", "conf": "h"}, reg), ("P-9904", "domain_rule", None))
        none = {"project": None, "source": "none", "conf": "l", "cands": []}
        self.assertEqual(merge_project(none, {"project": "NONE", "conf": "h"}, reg), (None, "none", None))
        self.assertEqual(merge_project(none, {"project": "NEW", "conf": "m"}, reg), ("NEW", "ai_m", None))
        self.assertEqual(merge_project(none, {"project": "P-0013", "conf": "h"}, reg), ("P-0007", "ai_h", None))
        self.assertEqual(merge_project(none, None, reg), (None, "none", None))

    def test_level_and_slot(self):
        self.assertEqual(level_of("user", "h", None, None, None), "confirmed")
        self.assertEqual(level_of("ai_h", "h", "P-0007", None, "P-0007"), "high")
        self.assertEqual(level_of("ai_h", "h", "P-0007", None, None), "medium")
        self.assertEqual(level_of("rule", "m", "P-0007", None, None), "medium")
        self.assertEqual(level_of("ai_m", "m", None, "pr_1", None), "low")
        self.assertEqual(level_of("none", "l", None, None, None), "unclassified")
        reg = K.golden_reg(local={"schema": "lm27.registry_local/1",
                                  "projects": [{"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "proposal_id": "pr_2"}]})
        self.assertEqual(role_slot("L-0001", None, reg), "pr_2")
        self.assertEqual(role_slot(None, None, reg), "UNC")
        self.assertEqual(role_slot("P-9904", None, reg), "P-9904")


def setup():
    reg = K.golden_reg(team=team())
    units, rule, ff, wt, groups, titles = {}, {}, {}, {}, [], {}

    def add(uid, gkey, rl, ffr, wtr=("DEV", "h", ""), effort=600, title=("공차해석", "doc"), extra=()):
        units[uid] = K.U(uid, "S1", [(K.F(uid + "m", "mail", "공차 검토"), 2.0, "boundary")], effort_min=effort,
                         first_key="fk" + uid)
        rule[uid], ff[uid], wt[uid] = rl, ffr, wtr
        members = (uid,) + tuple(extra)
        groups.append(Group(gkey, "fk" + uid, uid, members, effort * len(members)))
        titles[gkey] = title

    ffh = FieldFunc("OPT", "h", "ANALYSIS", "l")
    ffm = FieldFunc("OPT", "m", "ANALYSIS", "m")
    add("u1", "grp:000000000001", RuleLabel("P-0007", 1.0, "token", "h", (("P-0007", 0.36),), "DEV"), ffh, extra=("u2",))
    units["u2"] = K.U("u2", "SELF", [], effort_min=100, first_key="fku2")
    rule["u2"], ff["u2"], wt["u2"] = RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm, ("OFFICE", "l", "")
    add("u3", "grp:000000000003", RuleLabel("P-9904", 1.0, "domain_rule", "m", (), "COM"), ffm, ("DEV", "m", ""))
    add("u4", "grp:000000000004", RuleLabel("P-0008", 0.55, "rule_probable", "l", (("P-0008", 0.55), ("P-0007", 0.2)),
                                            "MP"), ffm)
    add("u5", "grp:000000000005", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm)
    add("u6", "grp:000000000006", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm)
    add("u7", "grp:000000000007", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm)
    add("u8", "grp:000000000008", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm)
    add("u9", "grp:000000000009", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm, title=("기타·기타 단위업무", "generic"))
    add("ua", "grp:00000000000a", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm)
    add("ub", "grp:00000000000b", RuleLabel(None, 0.0, "none", "l", (), "UNC"), ffm)
    ai = {"grp:000000000001": ans("P-0008", "h"),
          "grp:000000000003": ans("P-0030", "h", wtype="OFFICE"),
          "grp:000000000004": ans("P-0007", "m"),
          "grp:000000000005": ans("NEW", "m", new="방열 모듈", dom="DEV"),
          "grp:000000000006": ans("NONE", "h"),
          "grp:000000000008": ans("NONE", "l", title="다른 이름"),
          "grp:000000000009": ans("NONE", "l", title="AI 이름"),
          "grp:00000000000a": ans("P-0999", "h"),
          "grp:00000000000b": ans("P-0040", "h")}
    ai["grp:000000000007"] = {"ans": ai["grp:000000000006"]["ans"], "by": "rule_pending"}
    corrections = {"u7": {"project": "P-0012", "title": "사용자 제목", "field": "SYS", "_ids": ["c1"]}}
    return reg, units, rule, ff, wt, groups, titles, ai, corrections


class ApplyLabelsTest(unittest.TestCase):
    def test_apply(self):
        reg, units, rule, ff, wt, groups, titles, ai, corr = setup()
        cache = TitleCache()
        props = ProposalQueue()
        labels, conflicts, stats = apply_labels(rule, ff, wt, ai, corr, cache, props, reg, K.cfg(), groups=groups,
                                                units=units, titles=titles, at=AT)
        self.assertTrue(all(isinstance(v, UnitLabel) for v in labels.values()))
        u1, u2 = labels["u1"], labels["u2"]
        self.assertEqual((u1.project, u1.src["project"], u1.level), ("P-0007", "token", "high"))
        self.assertIn("ai_conflict", u1.flags)                                  # H02 — AI h 가 토큰 과제와 다름
        self.assertEqual(conflicts[0]["group"], "grp:000000000001")
        self.assertEqual((u2.project, u2.src["project"], u2.level), ("P-0008", "ai_h", "medium"))
        self.assertEqual((u1.field, u1.src["field"]), ("OPT", "rule"))           # 규칙 h 는 지킨다
        self.assertEqual((u2.field, u2.src["field"]), ("THERM", "ai_h"))        # 규칙 m < AI h
        self.assertEqual((u1.func, u1.src["func"]), ("DESIGN", "ai_h"))          # 규칙 l < AI h
        self.assertEqual((u1.title, u1.title_src), ("광학 모듈 공차 해석", "ai"))
        self.assertEqual(cache.get("grp:000000000001")["src"], "ai")
        u3 = labels["u3"]
        self.assertEqual((u3.project, u3.domain, u3.wtype), ("P-0030", "COM", "OFFICE"))   # 구체화
        u4 = labels["u4"]
        self.assertEqual((u4.project, u4.src["project"], u4.level), ("P-0008", "rule_probable", "low"))
        u5 = labels["u5"]
        self.assertEqual((u5.project, u5.proposal_id, u5.domain, u5.level), (None, "pr_1", "DEV", "low"))
        self.assertIn("proposal", u5.flags)
        self.assertEqual(u5.role_id, role_id("pr_1", u5.field, u5.func))
        self.assertEqual(props.get("pr_1")["label"], "방열 모듈")
        u6 = labels["u6"]
        self.assertEqual((u6.project, u6.domain, u6.level), (None, "UNC", "unclassified"))
        u7 = labels["u7"]
        self.assertEqual((u7.project, u7.src["project"], u7.level, u7.domain), ("P-0012", "user", "confirmed", "EXT"))
        self.assertEqual((u7.title, u7.title_src, u7.field, u7.src["field"]), ("사용자 제목", "user", "SYS", "user"))
        self.assertEqual(cache.get("grp:000000000007")["src"], "user")
        self.assertEqual((labels["u8"].title, labels["u8"].title_src), ("공차해석", "rule_doc"))   # AI l < 규칙 doc
        self.assertEqual((labels["u9"].title, labels["u9"].title_src), ("AI 이름", "ai"))          # AI l > 규칙 generic
        self.assertEqual(labels["ua"].project, None)                              # 목록 밖 코드 → 답 무효
        self.assertEqual(stats["ai_invalid"], 1)
        self.assertIn("retired_project", labels["ub"].flags)                      # 퇴역(병합 없음) → 옛 라벨 + 표식
        for lb in labels.values():
            slot = role_slot(lb.project, lb.proposal_id if not lb.project else None, reg)
            self.assertEqual(lb.role_id, role_id(slot, lb.field, lb.func))       # H-I4
            self.assertEqual(lb.domain, reg.domain_of(lb.project) if lb.project else (
                props.dom_of(lb.proposal_id) if lb.proposal_id else "UNC"))     # H-I2

    def test_cache_and_no_ai(self):
        reg, units, rule, ff, wt, groups, titles, ai, corr = setup()
        cache = TitleCache()
        cache.put("grp:000000000004", title="캐시 사용자 이름", src="user", conf="h")
        cache.put("grp:000000000003", title="캐시 AI 이름", src="ai", conf="m")
        labels, conflicts, stats = apply_labels(rule, ff, wt, {}, {}, cache, None, reg, K.cfg(), groups=groups,
                                                units=units, titles=titles, at=AT)
        self.assertEqual((labels["u4"].title, labels["u4"].title_src), ("캐시 사용자 이름", "user"))
        self.assertEqual((labels["u3"].title, labels["u3"].title_src), ("캐시 AI 이름", "ai"))
        self.assertEqual((labels["u1"].project, labels["u3"].project), ("P-0007", "P-9904"))   # 코파일럿 없으면 규칙 라벨
        self.assertEqual(conflicts, [])
        self.assertEqual(stats, {})
        d = labels["u1"].to_obj()
        self.assertEqual(set(d), {"group", "project", "proposal_id", "domain", "field", "func", "wtype", "stance",
                                  "ax_link", "role_id", "title", "title_src", "src", "conf", "level", "cands", "why",
                                  "flags"})


if __name__ == "__main__":
    unittest.main()
