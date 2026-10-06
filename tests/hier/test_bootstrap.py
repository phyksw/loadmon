# -*- coding: utf-8 -*-
r"""WP-22 초기 부트스트랩 시험 — H §8(코드네임 후보 · 코파일럿 열림 · 1회차 조건 · 결과 처리 · 2회차 쌍) · §3.5 ·
T-H05(검토 전 코파일럿 안 열림) · T-H18(AI 단독 통합 쌍은 질문, 자동 병합 0). 부트스트랩은 과제를 만들지 않는다(H-I6)."""
import hashlib
import unittest
from datetime import date

from lm27.hier import bootstrap as B
from lm27.hier import merge as MG
from lm27.hier.apply import UnitLabel
from lm27.hier.groups import Group
from lm27.hier.names import ukey
from lm27.hier.proposals import ProposalQueue
from lm27.time.calendar import day0
from lm27.hier import proposals as PQ
from tests.fixtures.wp22 import hierkit as K

AT = "2026-10-05T10:00:00+09:00"


def t_of(d: date) -> int:
    return day0(d) + 10 * 3600


class CandidatesTest(unittest.TestCase):
    def test_candidates(self):
        reg = K.empty_reg()
        feats, fg = [], {}
        days = [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22)]
        for i, d in enumerate(days):
            m = K.F(f"m{i}", "mail", f"[QX-12] 회의 일정 {i}", t=t_of(d), subject=f"[QX-12] 회의 일정 {i}")
            f = K.F(f"f{i}", "file", f"QX-12_설계_{i}.xlsx", t=t_of(d), names=((f"d{i}", f"QX-12_설계_{i}.xlsx"),))
            n = K.F(f"n{i}", "mail", "PROJ-A 검토", t=t_of(d))
            o = K.F(f"o{i}", "mail", "버너스 검토", t=t_of(days[0]))                # 한 주에만 — 주 수 미달
            feats += [m, f, n, o]
            for x in (m, f, n, o):
                fg[x.id] = f"g{i}"
        cands = B.codename_candidates(feats, [], reg, K.cfg(), feat_groups=fg)
        toks = [c.token for c in cands]
        self.assertEqual(toks[0], "QX-12")
        top = cands[0]
        self.assertEqual((top.n_groups, top.n_weeks), (4, 4))
        self.assertEqual(top.score, 2.0 + 1.0 + 1.0 + 0.5 * 2 + 0.5)              # 코드 모양·파일 접두 50%·꺾쇠·log2(4)·4주
        self.assertNotIn("회의", toks)                                             # 업무 일반어·상용구
        self.assertNotIn("버너스", toks)
        self.assertEqual(len(top.examples), 3)
        reg2 = K.golden_reg()
        self.assertNotIn("PROJ-A", [c.token for c in B.codename_candidates(feats, [], reg2, K.cfg(), feat_groups=fg)])
        h = hashlib.sha1(ukey("QX-12").encode("utf-8")).hexdigest()[:8]
        reg3 = K.golden_reg(team={"schema": "lm27.registry/1", "version": 0},
                            local={"schema": "lm27.registry_local/1",
                                   "codename_review": {"done_at": "2026-10-05T10:00:00+09:00", "ignored": [h],
                                                       "skipped": False}})
        self.assertNotIn("QX-12", [c.token for c in B.codename_candidates(feats, [], reg3, K.cfg(), feat_groups=fg)])
        few = B.codename_candidates(feats, [], reg, K.cfg({"hier.bootstrap.codenameMinGroups": 5}), feat_groups=fg)
        self.assertEqual(few, [])

    def test_hyphen_code_and_exts(self):
        """대문자 하이픈 코드(PROJ-X — T-H06 예시)는 통째 후보, 그 조각(proj)·파일 확장자(xlsx)는 후보가 아니다."""
        feats = []
        for i, d in enumerate([date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15)]):
            feats.append(K.F(f"m{i}", "mail", f"PROJ-X 결과 송부 보고서_{i}.xlsx", t=t_of(d),
                             subject=f"PROJ-X 결과 송부 {i}", exts=frozenset({".xlsx"})))
        toks = [c.token for c in B.codename_candidates(feats, [], K.empty_reg(), K.cfg())]
        self.assertIn("PROJ-X", toks)
        self.assertNotIn("PROJ", toks)
        self.assertNotIn("xlsx", toks)
        self.assertTrue(B.is_code_like("PROJ-X") and B.is_code_like("AB_12") and not B.is_code_like("Proj-x"))


class GateTest(unittest.TestCase):
    def test_copilot_allowed(self):
        """T-H05 — 검토 선행을 켰으면(hier.copilot.requireCodenameReview) 빈 레지스트리·검토 전에는 코파일럿 분류 단계가
        열리지 않는다(안내 1줄, 분석은 계속). 기본값은 꺼짐 — LM24 처럼 바로 연다(계약 v1.3 §0.8 V12)."""
        on = K.cfg({"hier.copilot.requireCodenameReview": True})
        self.assertEqual(B.copilot_allowed(K.empty_reg(), on), (False, "과제 이름 후보를 확인하면 코파일럿 분류를 켭니다"))
        self.assertEqual(B.copilot_allowed(K.empty_reg(), K.cfg()), (True, ""))            # 기본: 검토 없이 바로
        skipped = K.golden_reg(team={"schema": "lm27.registry/1", "version": 0},
                               local={"schema": "lm27.registry_local/1", "codename_review": {"skipped": True}})
        ok, msg = B.copilot_allowed(skipped, on)
        self.assertTrue(ok)
        self.assertIn("그대로 갈 수 있습니다", msg)
        self.assertEqual(B.review_state(K.golden_reg()), "not_needed")
        self.assertEqual(B.copilot_allowed(K.golden_reg(), on), (True, ""))

    def test_needs_bootstrap(self):
        done = K.golden_reg(team={"schema": "lm27.registry/1", "version": 0},
                            local={"schema": "lm27.registry_local/1", "codename_review": {"done_at": "2026-10-01"}})
        gs = [Group(f"grp:{i:012d}", "a", f"u{i}", (f"u{i}",), 60, t_of(date(2026, 9, 25)), t_of(date(2026, 9, 26)))
              for i in range(20)]
        self.assertTrue(B.needs_bootstrap(done, {}, None, K.cfg(), groups=gs))
        self.assertFalse(B.needs_bootstrap(done, {}, None, K.cfg(), groups=gs[:19]))
        self.assertTrue(B.needs_bootstrap(done, {}, None, K.cfg(), groups=[], user_request=True))
        reg = K.golden_reg()
        labels = {f"u{i}": UnitLabel(unit_id=f"u{i}", project=None if i < 12 else "P-0007") for i in range(20)}
        today = date(2026, 9, 30)
        self.assertTrue(B.needs_bootstrap(reg, labels, None, K.cfg(), groups=gs, as_of=today))           # 미분류 60%
        self.assertFalse(B.needs_bootstrap(reg, labels, "2026-09-20", K.cfg(), groups=gs, as_of=today))  # 쿨다운
        self.assertFalse(B.needs_bootstrap(reg, labels, None, K.cfg({"hier.bootstrap.unclassifiedShare": 0.7}),
                                           groups=gs, as_of=today))


class ResultTest(unittest.TestCase):
    def test_apply_bootstrap(self):
        reg = K.golden_reg()
        samples = [{"key": f"grp:{i:012d}"} for i in range(4)]
        rows = [{"name": "", "code": "P-0007", "dom": "DEV", "kind": "project", "obs": [1]},
                {"name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project", "match": ["방열", "열해석"], "obs": [2, 3]},
                {"name": "팀 운영 사무", "code": "", "dom": "DEV", "kind": "common", "obs": [4]},
                {"name": "", "code": "", "dom": "COM", "kind": "nonwork", "obs": [4, 9]},
                {"name": "방열모듈", "code": "", "dom": "DEV", "kind": "project", "obs": [2]}]
        q = ProposalQueue()
        out = B.apply_bootstrap(rows, samples, q, reg, K.cfg(),
                                efforts={"grp:000000000001": 400, "grp:000000000002": 300, "grp:000000000003": 90},
                                at="2026-10-05T10:00:00+09:00")
        self.assertEqual(out["report"], [(1, "P-0007", [1])])                     # 코드 있음 → 보고에만
        self.assertEqual(out["nonwork"], ["grp:000000000003"])
        p1 = q.get("pr_1")
        self.assertEqual((p1["label"], p1["domain_guess"], p1["groups"]), ("방열 모듈", "DEV",
                                                                          ["grp:000000000001", "grp:000000000002"]))
        self.assertEqual(p1["match_words"], ["방열", "열해석"])
        self.assertEqual(q.get("pr_2")["domain_guess"], "COM")                    # common → COM·EXT 밖이면 COM
        self.assertEqual(len(q.items), 2)                                         # ukey 중복 행은 버린다
        self.assertEqual(out["caps_hit"], 0)
        self.assertEqual(reg.active_ids(), K.golden_reg().active_ids())          # 과제를 만들지 않는다
        many = [{"name": f"과제 후보 {chr(0xAC00 + i * 3)}{chr(0xAC01 + i)}", "code": "", "dom": "DEV",
                 "kind": "project", "obs": [1]} for i in range(20)]
        q2 = ProposalQueue()
        out2 = B.apply_bootstrap(many, samples, q2, reg, K.cfg({"hier.bootstrap.maxModels": 15}),
                                 efforts={"grp:000000000000": 600})
        self.assertEqual((out2["caps_hit"], len(out2["proposals"])), (5, 15))   # §8.2 — 넘는 행은 버리고 caps_hit

    def test_two_rounds_flow(self):
        """T-H18 — 1회차 스텁 답 → 제안, 2회차 스텁 답(AI 통합 쌍) → H04 질문, 자동 병합 0."""
        from lm27.hier.queue import hier_queue
        reg = K.golden_reg()
        samples = [{"key": f"grp:{i:012d}"} for i in range(4)]
        round1 = [{"name": "AX 도입", "code": "", "dom": "AX", "kind": "project", "obs": [1, 2]},
                  {"name": "Agentic 활용", "code": "", "dom": "AX", "kind": "project", "obs": [3]},
                  {"name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project", "obs": [4]}]
        q = ProposalQueue()
        B.apply_bootstrap(round1, samples, q, reg, K.cfg(),
                          efforts={"grp:000000000000": 300, "grp:000000000001": 200, "grp:000000000002": 300,
                                   "grp:000000000003": 300}, at="2026-10-05T10:00:00+09:00")
        self.assertEqual([p["label"] for p in q.live()], ["AX 도입", "Agentic 활용", "방열 모듈"])
        from lm27.hier.copilot_io import build_consolidate_items
        items = build_consolidate_items(round1, q.items, reg)
        round2 = [{"id": 2, "same_as": 1, "conf": "h"}, {"id": 3, "same_as": 0, "conf": "h"}]
        pairs = B.consolidate_pairs(round2, items)
        merged, asks = q.consolidate(pairs, reg, K.cfg(), at="2026-10-06T10:00:00+09:00")
        self.assertEqual(merged, [])                                              # AI 단독 — 자동 병합 0
        self.assertEqual([(a["a"], a["b"]) for a in asks], [("pr_2", "pr_1")])
        qs = hier_queue({}, [], q.items, [], list(q.asks), K.cfg(), as_of=date(2026, 10, 6))
        self.assertEqual([x["code"] for x in qs], ["H04"])
        self.assertEqual(len(q.live()), 3)

    def test_consolidate_pairs(self):
        """T-H18 — 2회차 AI 쌍은 근거 +1.0 일 뿐: AI 단독이면 질문 구간(자동 병합 0)."""
        items = [{"rule": {"name": "AX 도입"}}, {"rule": {"name": "Agentic 활용"}}, {"rule": {"name": "방열 모듈"}}]
        answers = [{"id": 1, "same_as": 2, "conf": "h"}, {"id": 2, "same_as": 2, "conf": "h"},
                   {"id": 3, "same_as": 1, "conf": "l"}, {"id": 1, "same_as": 9, "conf": "m"}, {"id": "x"}]
        pairs = B.consolidate_pairs(answers, items)
        self.assertEqual(pairs, frozenset({frozenset((ukey("AX 도입"), ukey("Agentic 활용")))}))
        s, why = MG.pair_score("AX 도입", "Agentic 활용", MG.MergeCtx(ai_pairs=pairs))
        self.assertEqual(MG.zone(s, K.cfg()), "ask")
        self.assertIn("AI", why)

    def test_domain_vote(self):
        reg = K.golden_reg()
        self.assertEqual(B.domain_vote([K.F("a", "mail", "양산 라인 수율")], reg), "MP")
        self.assertEqual(B.domain_vote([], reg), "DEV")
        self.assertTrue(B.is_code_like("QX-12") and not B.is_code_like("회의"))


if __name__ == "__main__":
    unittest.main()


class RuleAutoProjectsTest(unittest.TestCase):
    """계약 v1.3 §0.8 V15: 팀·개인 과제가 없고 AI 답도 없는 미분류 군집 — 자주 나온 이름으로 규칙 제안 과제(LM24 규칙 대체)."""

    def world(self):
        from datetime import date as _date

        from lm27.hier.apply import UnitLabel
        from lm27.hier.groups import Group
        from lm27.time.calendar import day0
        weeks = [_date(2026, 9, 1), _date(2026, 9, 8), _date(2026, 9, 15), _date(2026, 9, 22)]
        feats, units, groups, labels = [], {}, [], {}
        for i, d in enumerate(weeks):
            t = day0(d) + 10 * 3600
            fs = [K.F(f"m{i}", "mail", f"PROJ-X 시험 결과 {i}", t=t, subject=f"PROJ-X 시험 결과 {i}"),
                  K.F(f"f{i}", "file", f"PROJ-X_결과_{i}.xlsx", t=t,
                      names=((K.fake_doc(f"PROJ-X_결과_{i}"), f"PROJ-X_결과_{i}.xlsx"),))]
            feats += fs
            uid = f"u{i}"
            units[uid] = K.U(uid, "S1", [(f, 1.0, "boundary") for f in fs], effort_min=300)
            g = Group(f"grp:00000000000{i}", "a", uid, (uid,), 300)
            groups.append(g)
            labels[uid] = UnitLabel(unit_id=uid, group=g.key, field="OPT", func="ANALYSIS")
        lone = K.F("z0", "mail", "기타 공지 메일", t=day0(weeks[0]) + 3600, subject="기타 공지 메일")
        feats.append(lone)
        units["uz"] = K.U("uz", "S1", [(lone, 1.0, "boundary")], effort_min=300)
        groups.append(Group("grp:00000000000z", "a", "uz", ("uz",), 300))
        labels["uz"] = UnitLabel(unit_id="uz", group="grp:00000000000z")
        return feats, units, groups, labels

    def test_recurring_name_becomes_rule_proposal(self):
        feats, units, groups, labels = self.world()
        q = PQ.ProposalQueue()
        st = B.rule_auto_projects(labels, groups, units, feats, K.empty_reg(), K.cfg(), q, ai={}, at=AT)
        self.assertEqual((st.get("assigned"), st.get("todo")), (4, 5))
        pids = {labels[f"u{i}"].proposal_id for i in range(4)}
        self.assertEqual(len(pids), 1)                                     # 같은 이름 → 제안 하나로
        pid = pids.pop()
        self.assertEqual(q.get(pid)["label"], "PROJ-X")
        lb = labels["u0"]
        self.assertTrue({"proposal", "rule_auto"} <= set(lb.flags))
        self.assertEqual((lb.project, lb.src["project"], lb.conf["project"], lb.level), (None, "rule", "l", "low"))
        self.assertIsNone(labels["uz"].proposal_id)                        # 반복되는 이름이 없으면 미분류 그대로

    def test_off_ai_answer_or_registry_projects_leave_alone(self):
        feats, units, groups, labels = self.world()
        off = K.cfg({"hier.ruleAutoProjects": False})
        self.assertEqual(B.rule_auto_projects(labels, groups, units, feats, K.empty_reg(), off, PQ.ProposalQueue()), {})
        ai = {groups[0].key: {"by": "ai", "ans": {"project": "NONE"}}}   # AI 가 과제 없음이라고 답한 군집은 그대로
        st = B.rule_auto_projects(labels, groups, units, feats, K.empty_reg(), K.cfg(), PQ.ProposalQueue(), ai=ai)
        self.assertEqual(st.get("todo"), 4)
        self.assertIsNone(labels["u0"].proposal_id)
        feats, units, groups, labels = self.world()
        self.assertEqual(B.rule_auto_projects(labels, groups, units, feats, K.golden_reg(), K.cfg(),
                                              PQ.ProposalQueue()), {})          # 팀·개인 과제가 있으면 쓰지 않는다
