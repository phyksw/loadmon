# -*- coding: utf-8 -*-
r"""WP-22 초기 부트스트랩 시험 — H §8(코드네임 후보 · 코파일럿 열림 · 1회차 조건 · 결과 처리 · 2회차 쌍) · §3.5 ·
T-H05(검토 전 코파일럿 안 열림) · T-H18(AI 단독 통합 쌍은 질문, 자동 병합 0). 부트스트랩은 과제를 만들지 않는다(H-I6)."""
import hashlib
import unittest
from datetime import date, timedelta

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


# ───────────────────────── W2 검토 C06 · C15 · 개발 PC 실측 N2 — 이름이 될 수 없는 낱말 ─────────────────────────
WEEKS6 = [date(2026, 8, 3) + timedelta(days=7 * i) for i in range(6)]
DEV_FILES = ("get_signals.py", "load_signals.py", "judge_load.py", "refine_judge.py", "signals_2026.json", "refine_v2.py")


def name_world(spec, kind="file", effort=120, **fkw):
    """spec = [(군집 이름, [(주 번호, 정제문)])] → (feats, units, groups, labels). 군집 하나 = 단위업무 하나."""
    feats, units, groups, labels = [], {}, [], {}
    for gi, (gname, rows) in enumerate(spec):
        ev = []
        for j, (wk, text) in enumerate(rows):
            kw = dict(fkw, t=t_of(WEEKS6[wk]) + j * 60)
            if kind == "file":
                kw.setdefault("names", ((K.fake_doc(text), text),))
            elif kind in ("mail", "teams"):
                kw.setdefault("subject", text)
            f = K.F(f"{gname}_{j}", kind, text, **kw)
            feats.append(f)
            ev.append((f, 1.0, "boundary"))
        uid = f"u_{gname}"
        units[uid] = K.U(uid, "SELF", ev, effort_min=effort)
        g = Group(f"grp:{gi:012x}", "a", uid, (uid,), effort)
        groups.append(g)
        labels[uid] = UnitLabel(unit_id=uid, group=g.key, field="ETC", func="ETC")
    return feats, units, groups, labels


def auto(spec, kind="file", fkw=None, effort=120, **kw):
    feats, units, groups, labels = name_world(spec, kind, effort, **(fkw or {}))
    q = PQ.ProposalQueue()
    st = B.rule_auto_projects(labels, groups, units, feats, K.empty_reg(), K.cfg(), q, ai={}, at=AT, **kw)
    names = {uid[2:]: (q.get(lb.proposal_id)["label"] if lb.proposal_id else None) for uid, lb in labels.items()}
    cands = [c.token for c in B.codename_candidates(feats, [], K.empty_reg(), K.cfg())]
    return st, names, cands, q, labels


def dev_auto(folder):
    """개발 PC 모양 군집 6개(파일 하나씩 · 6주) — 창 제목('<파일> - <폴더> - Visual Studio Code')·저장 파일·커밋."""
    feats, units, groups, labels = [], {}, [], {}
    for gi, fn in enumerate(DEV_FILES):
        ev = []
        title = f"{fn} - {folder} - Visual Studio Code" if folder else f"{fn} - Visual Studio Code"
        for j in range(6):
            t = t_of(WEEKS6[j]) + j * 60
            w = K.F(f"d{gi}_w{j}", "win", title, t=t, app="vscode", app_cat="SW", names=((K.fake_doc(fn), fn),),
                    fams=(K.fake_doc(fn),))
            f = K.F(f"d{gi}_f{j}", "file", fn, t=t + 30, exts={"." + fn.rsplit(".", 1)[1]},
                    names=((K.fake_doc(fn), fn),), fams=(K.fake_doc(fn),))
            g = K.F(f"d{gi}_g{j}", "git", ("W2 검토 반영", "v2 수정", "코드 정리")[j % 3], t=t + 60)
            feats += [w, f, g]
            ev += [(w, 1.0, "app"), (f, 1.5, "doc"), (g, 1.0, "doc")]
        uid = f"u_d{gi}"
        units[uid] = K.U(uid, "SELF", ev, effort_min=300)
        grp = Group(f"grp:{gi:012x}", "a", uid, (uid,), 300)
        groups.append(grp)
        labels[uid] = UnitLabel(unit_id=uid, group=grp.key, field="SW", func="ETC")
    q = PQ.ProposalQueue()
    st = B.rule_auto_projects(labels, groups, units, feats, K.empty_reg(), K.cfg(), q, ai={}, at=AT)
    cands = B.codename_candidates(feats, [], K.empty_reg(), K.cfg())
    return st, {lb.proposal_id and q.get(lb.proposal_id)["label"] for lb in labels.values()}, cands


class NameQualityTest(unittest.TestCase):
    def test_c06_version_tail_loses_to_code(self):
        """'v2' 같은 판 꼬리는 과제가 아니고, 군집마다 그 군집의 구체적인 코드가 이름이 된다(C06)."""
        docs = ("회로도", "배선도", "부품표", "시험표", "설계서", "검토표")
        spec = [(f"g{i}", [(w, f"{docs[i]}_{'QX-12' if i < 3 else 'QY-34'}_v2.xlsx") for w in range(i % 2, 6, 2)])
                for i in range(6)]
        st, names, cands, _q, _l = auto(spec, fkw={"exts": frozenset({".xlsx"})})
        self.assertEqual(names, {"g0": "QX-12", "g1": "QX-12", "g2": "QX-12", "g3": "QY-34", "g4": "QY-34",
                                 "g5": "QY-34"})
        self.assertEqual(st.get("assigned"), 6)
        self.assertNotIn("v2", [c.lower() for c in cands])

    def test_c06_token_and_category_tail(self):
        """정제 토큰 속 과제 ID·판 꼬리(v3)·앱 범주 꼬리(' - CAD')는 후보가 아니다 — 남는 것이 없으면 '과제 없음'."""
        spec = [(f"g{i}", [(w, "회로도_[과제:P-0001]_v3.xlsx") for w in range(6)]) for i in range(3)]
        _st, _names, cands, _q, _l = auto(spec)
        self.assertFalse({"P-0001", "v3", "p0001"} & set(cands), cands)
        spec = [(f"c{i}", [(w, f"{1000 + i}_v2.dwg - CAD") for w in range(6)]) for i in range(3)]
        _st, names, cands, _q, _l = auto(spec, "win", fkw={"app": "unknown:cadtool.exe"})
        self.assertNotIn("cad", [c.lower() for c in cands])
        self.assertEqual(set(names.values()), {None})

    def test_c15_sanitizer_tokens_never_names(self):
        """사람 가명 조각('a1b'·'c3')·고객사·협력사·이메일·과제 토큰 ID 는 후보·제안이 되지 않는다(C15)."""
        for subj in ("RE: [사람#a1b2c3] 주간 업무 공유", "[고객사:C01] 견적 문의 회신", "[이메일@고객사:C01] 회신 드림",
                     "[협력사:V02] 납기 협의", "[과제:P-0001] 일정 공지"):
            spec = [(f"p{i}", [(w, f"{subj} {i}") for w in range(4)]) for i in range(3)]
            st, names, cands, _q, _l = auto(spec, "mail")
            self.assertFalse({"a1b", "c3", "C01", "V02", "P-0001", "a1b2c3"} & set(cands), (subj, cands))
            self.assertEqual((st.get("assigned"), set(names.values())), (None, {None}), subj)
        spec = [(f"p{i}", [(w, f"[사람#a1b2c3] PROJ-X 시험 결과 {i}") for w in range(4)]) for i in range(3)]
        _st, names, _c, _q, _l = auto(spec, "mail")
        self.assertEqual(set(names.values()), {"PROJ-X"})                 # 진짜 코드는 그대로 선다

    def test_small_clusters_join_established_name(self):
        """제안 최소 투입(hier.proposals.minEffortMin 60분)은 이름 전체로 본다 — 30분 군집 셋(합 90분)도 같은 제안으로 간다.
        이름 전체가 모자라면(합 45분) 세우지 않는다."""
        spec = [(f"p{i}", [(w, f"PROJ-X 시험 결과 {i}") for w in range(4)]) for i in range(3)]
        st, names, _c, q, _l = auto(spec, "mail", effort=30)
        self.assertEqual((st.get("assigned"), set(names.values()), len(q.live())), (3, {"PROJ-X"}, 1))
        st, names, _c, q, _l = auto(spec, "mail", effort=15)
        self.assertEqual((st.get("assigned"), set(names.values()), q.live()), (None, {None}, []))
        self.assertEqual(st.get("skip_too_small"), 3)

    def test_label_check_reaches_proposal_queue(self):
        spec = [(f"p{i}", [(w, f"PROJ-X 시험 결과 {i}") for w in range(4)]) for i in range(3)]
        st, names, _c, q, _l = auto(spec, "mail", label_check=lambda s: False)
        self.assertEqual(st.get("assigned"), 3)
        self.assertIn("proposal_label_rejected", q.warnings)              # 팀 라벨 검사를 거친다
        self.assertNotIn("PROJ-X", set(names.values()))

    def test_n2_junk_words(self):
        for t in ("v2", "ver3", "rev1", "r2", "w2", "q3", "h1", "2026", "202609", "20260930", "1차", "2nd",
                  "signals_2026", "report2025", "utf8", "x64", "sha256", "py", "json", "xlsx", "ab", "[사람#a1b2c3]"):
            self.assertTrue(B._junk(t, ukey(t)), t)
        for t in ("QX-12", "PROJ-X", "loadmon27", "방열모듈", "lm27", "P-12"):
            self.assertFalse(B._junk(t, ukey(t)), t)
        common = B._match.common_words()
        for w in ("get", "load", "judge", "refine", "signals", "utils", "main", "test", "config", "fix", "merge"):
            self.assertIn(w, common)

    def test_n2_title_parts(self):
        f = K.F("w", "win", "● get_signals.py - loadmon27 [SSH: host] - Visual Studio Code", app="vscode",
                app_cat="SW", names=(("d1", "get_signals.py"),))
        parts = B.name_parts(f)
        self.assertIn(("loadmon27", "folder", False), parts)
        self.assertIn(("get", "code", True), parts)
        self.assertFalse({t.lower() for t, _r, _p in parts} & {"visual", "studio", "code", "host", "ssh"})
        # VS Code 의 홀로 남은 마디는 약한 폴더(folder1) — 작업 폴더가 없는 창의 탭 이름일 수도 있어 글 조각으로도 낸다(N2 남은 것)
        self.assertEqual(B.name_parts(K.F("w", "win", "loadmon27 - Visual Studio Code", app="vscode", app_cat="SW")),
                         (("loadmon27", "folder1", False), ("loadmon27", "text", False)))
        tab = B.name_parts(K.F("w", "win", "Welcome - loadmon27 - Visual Studio Code", app="vscode", app_cat="SW"))
        self.assertEqual([p for p in tab if p[1] == "folder"], [("loadmon27", "folder", False)])
        office = B.name_parts(K.F("w", "win", "견적서.xlsx - Excel", app="excel", app_cat="사무"))
        self.assertEqual({r for _t, r, _p in office}, {"doc"})              # 개발 도구가 아니면 폴더 마디로 보지 않는다

    def test_n2_dev_pc_work_folder_is_the_name(self):
        """개발 PC(계정 없음): 파일 이름 조각(get·judge·refine·load·signals_2026)·확장자·판 꼬리·커밋의 W2 대신 작업 폴더."""
        st, names, cands = dev_auto("loadmon27")
        self.assertEqual((names, st.get("assigned")), ({"loadmon27"}, 6))
        self.assertEqual((cands[0].token, cands[0].folder), ("loadmon27", True))
        bad = {"get", "judge", "refine", "load", "signals", "signals_2026", "py", "json", "v2", "w2", "2026"}
        self.assertFalse(bad & {c.token.lower() for c in cands}, [c.token for c in cands])

    def test_n2_dev_pc_without_folder_stays_unclassified(self):
        """의미 있는 이름이 없으면 쓰레기 이름 대신 '과제 없음'(UNC) 그대로."""
        st, names, cands = dev_auto(None)
        self.assertEqual((names, st.get("assigned"), st.get("no_name")), ({None}, None, 6))
        self.assertEqual(cands, [])

    def test_n2_editor_tabs_and_terminals_not_folders(self):
        """N2 남은 것(재현 확인 still_broken 1): 작업 폴더가 없는 VS Code 창('<탭> - Visual Studio Code')의 편집기 고유 탭과
        터미널 창 제목은 작업 폴더 후보가 아니다. 작업 폴더는 개발 편집기(창 분류 ide) 창 제목의 자리로 정한다."""
        for title in ("Untitled-1 - Visual Studio Code", "● Untitled-2 - Visual Studio Code", "Welcome - Visual Studio Code",
                      "Settings - Visual Studio Code", "Extension: Python - Visual Studio Code",
                      "Keyboard Shortcuts - Visual Studio Code", "Release Notes: 1.95 - Visual Studio Code",
                      "제목 없음-1 - Visual Studio Code", "Get Started - Visual Studio Code"):
            self.assertEqual(B.name_parts(K.F("w", "win", title, app="vscode", app_cat="SW")), (), title)
        for title in ("Windows PowerShell", "관리자: Windows PowerShell", "MINGW64:/d/ /loadmon27"):
            parts = B.name_parts(K.F("w", "win", title, app="terminal", app_cat="SW"))      # 터미널 = SW 범주·창 분류 other
            self.assertFalse([p for p in parts if p[1].startswith("folder")], (title, parts))
        prof = B.name_parts(K.F("w", "win", "main.py - loadmon27 - Data Lab - Visual Studio Code", app="vscode",
                                app_cat="SW"))
        self.assertEqual([p for p in prof if p[1] == "folder"], [("loadmon27", "folder", False)])
        self.assertFalse({"data", "lab", "Data Lab"} & {t for t, _r, _p in prof})       # 폴더 뒤 마디 = 프로필 이름
        jb = B.name_parts(K.F("w", "win", "signal_lab – get_signals.py", app="jetbrains_ide", app_cat="SW"))
        self.assertIn(("signal_lab", "folder", False), jb)                                # '<프로젝트> – <파일>'
        vs = B.name_parts(K.F("w", "win", "SensorFw - Microsoft Visual Studio", app="visual_studio", app_cat="SW"))
        self.assertEqual(vs, (("SensorFw", "folder", False),))                            # 솔루션 이름 하나 — 탭이 아니다

    def test_n2_lone_segment_needs_folder_evidence(self):
        """VS Code 의 홀로 남은 마디는 같은 이름이 다른 창 제목('<파일> - <폴더> - 앱')에서 작업 폴더로 나왔을 때만 폴더다.
        아니면 글 조각으로만 센다(폴더 점수 없음) — 'Untitled-1' 같은 탭 이름은 어느 쪽으로도 후보가 아니다."""
        def cands(titles):
            feats, fg = [], {}
            for w in range(4):
                for j, title in enumerate(titles):
                    f = K.F(f"w{w}_{j}", "win", title, t=t_of(WEEKS6[w]) + j * 60, app="vscode", app_cat="SW")
                    feats.append(f)
                    fg[f.id] = f"g{w}"
            return {c.token: c.folder for c in B.codename_candidates(feats, [], K.empty_reg(), K.cfg(), feat_groups=fg)}
        self.assertEqual(cands(["loadmon27 - Visual Studio Code"]), {"loadmon27": False})
        self.assertEqual(cands(["loadmon27 - Visual Studio Code", "main.py - loadmon27 - Visual Studio Code"]),
                         {"loadmon27": True})
        self.assertEqual(cands(["Untitled-1 - Visual Studio Code", "Untitled-1 - loadmon27 - Visual Studio Code"]),
                         {"loadmon27": True})

    def test_n2_generic_forms(self):
        """범용 낱말(단일원 common_words.txt — 한국어·영어)과 그 꼴바뀜: 서술어 어미 · 일반어 + 번호 · 일반어 + 조사·높임 꼬리."""
        common = B._match.common_words()

        def generic(t):
            return B._junk(t, ukey(t)) or B._generic(t, ukey(t), common)
        for t in ("공유드립니다", "확인했습니다", "가능하실까요", "가능하세요", "부탁드려요", "검토하고", "수고하셨습니다",
                  "Untitled-1", "system32", "Book1", "문서1", "프레젠테이션1", "mingw64", "자료를", "팀장님", "공유건", "검토용",
                  "회의중", "참고", "상황", "채널", "이거", "가능", "여부", "FYI", "thanks", "regards", "attached", "question",
                  "following", "windows", "welcome", "extension"):
            self.assertTrue(generic(t), t)
        for t in ("방열모듈", "QX-12", "PROJ-X", "loadmon27", "lm27", "signal_lab", "센서사양", "납기표", "견적서", "회로도",
                  "품질지표", "교육자료", "P-12"):
            self.assertFalse(generic(t), t)

    def test_n2_greeting_phrases_never_names(self):
        """N2 남은 것(재현 확인 still_broken 2): 메일·팀즈 제목의 인사·요청·응답 상투어(한국어 서술어·범용 명사, 영어 기능어)는
        규칙 제안 과제 이름이 아니다 — 의미 있는 이름이 없으면 '과제 없음', 있으면 그 이름."""
        for subj in ("자료 공유드립니다", "넵 확인했습니다", "내일 회의 가능하실까요?", "이거 가능하세요?", "참고 부탁드립니다",
                     "견적 문의드립니다", "채널 공지", "진행 상황 공유", "확인 부탁드려요", "회의 참석 가능 여부", "잘 받았습니다",
                     "수고하셨습니다", "자료를 공유합니다", "팀장님 보고 건", "Please find attached", "Thanks for the update",
                     "FYI regarding the call", "Quick question", "Following up on this", "Can you check", "Kind regards"):
            for kind in ("mail", "teams"):
                spec = [(f"p{i}", [(w, subj) for w in range(4)]) for i in range(3)]
                st, names, cands, _q, _l = auto(spec, kind)
                self.assertEqual((cands, set(names.values()), st.get("assigned")), ([], {None}, None), (kind, subj))
        spec = [(f"p{i}", [(w, "방열모듈 시험 결과 공유드립니다") for w in range(4)]) for i in range(3)]
        _st, names, cands, _q, _l = auto(spec, "mail")
        self.assertEqual((set(names.values()), cands), ({"방열모듈"}, ["방열모듈"]))   # 전에는 '공유드립니다'(사전순 동률)

    def test_display_form_and_hash_seed(self):
        """표기는 가장 많이 나온 꼴(동률 사전순)이고, 해시 씨앗이 달라도 결과가 같다(C06 별도 관찰 — 결정성)."""
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path
        spec = [(f"p{i}", [(w, f"{'PROJ-X' if w else 'proj-x'} 시험 {i}") for w in range(4)]) for i in range(3)]
        _st, names, cands, _q, _l = auto(spec, "mail")
        self.assertEqual((set(names.values()), cands[:1]), ({"PROJ-X"}, ["PROJ-X"]))
        code = ("import json,sys;sys.path.insert(0,sys.argv[1]);from tests.hier.test_bootstrap import dev_auto;"
                "st,names,c=dev_auto('loadmon27');"
                "print(json.dumps([st,sorted(map(str,names)),[(x.token,x.score,x.n_groups) for x in c]],"
                "ensure_ascii=False))")
        outs = []
        root = str(Path(__file__).resolve().parents[2])
        for seed in ("0", "1"):                                           # 동봉 파이썬(._pth)은 작업 폴더를 sys.path 에 넣지 않는다
            cp = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code, root],
                                cwd=root, env=dict(os.environ, PYTHONHASHSEED=seed),
                                capture_output=True, timeout=120,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-800:])
            outs.append(json.loads(cp.stdout.decode("utf-8")))
        self.assertEqual(outs[0], outs[1])

    def test_domain_from_cluster_evidence(self):
        """영역은 DEV 고정이 아니라 그 이름이 붙은 군집 증거의 영역 키워드 다수결(H §8.1 — 없으면 DEV)."""
        mp = B.domain_vote([K.F("a", "mail", "양산 라인 수율 점검")], K.empty_reg())
        self.assertNotEqual(mp, "DEV")
        spec = [(f"p{i}", [(w, f"QX-12 양산 라인 수율 점검 {i}") for w in range(4)]) for i in range(3)]
        _st, names, _c, _q, labels = auto(spec, "mail")
        self.assertEqual(set(names.values()), {"QX-12"})
        self.assertEqual({lb.domain for lb in labels.values()}, {mp})


class DevPcEndToEndTest(unittest.TestCase):
    """개발 PC 모양 합성 행(`tests.fixtures.wp22.devpc`) → 실물 시간 코어 → classify_all(레지스트리 없음): 규칙 제안 과제가
    파일 이름 조각이 아니라 작업 폴더이거나, 그것도 없으면 '과제 없음'(N2)."""

    def run_dev(self, folder, tab=None, every=1):
        """tab = 날마다(every 일에 한 번) 09:00 표본 한 줄(10분)의 창 제목을 이것으로(문서 키 없음) — 재현 확인 N2 절차."""
        from datetime import UTC, datetime

        from lm27.hier import classify_all, prepare
        from lm27.time import analyze_time
        from tests.fixtures.wp22 import devpc as D
        K.install_fakes()
        cfg, reg = K.cfg(), K.empty_reg()
        rows = D.rows(folder)
        if tab:
            days = sorted({r["ts_utc"][:10] for r in rows})
            for r in rows:
                if (r.get("src") == "pc.sampler" and r["ts_utc"][11:16] == "00:00"          # 09:00 KST
                        and days.index(r["ts_utc"][:10]) % every == 0):
                    r["title_masked"], r["doc_key"] = tab, None
        feats, tags, _trows = prepare(rows, reg, cfg)
        tr = analyze_time(K.fake_unit_id, rows, {}, K.CALENDAR, datetime(2026, 9, 30, 23, 0, tzinfo=UTC), cfg=cfg,
                          tags=tags)
        res = classify_all({"cfg": cfg, "reg": reg, "feats": feats, "tasks": list(tr.tasks), "attrib": tr.attribution,
                            "team_tables": tr.tables, "slot_basis": tr.env.basis,
                            "now": datetime(2026, 10, 1, 0, 0, tzinfo=UTC)})
        labels = {p["proposal_id"]: p["label"] for p in res.proposals["items"]}
        eff: dict = {}
        for uid, lb in res.labels.items():
            k = labels.get(lb.proposal_id, "UNC")
            eff[k] = eff.get(k, 0) + int(res.units[uid].effort_min)
        return res, eff, D

    def test_folder_named_project(self):
        _res, eff, D = self.run_dev("loadmon27")
        self.assertEqual(set(eff) - {"UNC"}, {"loadmon27"})
        self.assertGreater(eff["loadmon27"], 10 * eff.get("UNC", 0))        # 코딩 시간이 작업 폴더 과제로
        self.assertFalse({t.lower() for t in eff} & D.JUNK)

    def test_no_folder_no_junk_project(self):
        res, eff, _D = self.run_dev(None)
        self.assertEqual(set(eff), {"UNC"})                                 # 쓰레기 이름 대신 '과제 없음'
        self.assertEqual(res.proposals["items"], [])

    def test_no_folder_editor_tab_is_not_a_project(self):
        """N2 남은 것 재현(날마다 · 닷새에 한 번 10분): 작업 폴더가 없는 VS Code 창의 편집기 고유 탭 이름이 코딩 시간 전체의
        과제가 되지 않는다(수정 전: 'Untitled-1' 14,370분 · 'Welcome' · 'Extension: Python')."""
        for tab, every in (("Untitled-1 - Visual Studio Code", 1), ("Untitled-1 - Visual Studio Code", 5),
                           ("Welcome - Visual Studio Code", 1), ("Extension: Python - Visual Studio Code", 1)):
            res, eff, _D = self.run_dev(None, tab, every)
            self.assertEqual((set(eff), res.proposals["items"]), ({"UNC"}, []), (tab, every))

    def test_folder_with_editor_tab_still_named(self):
        _res, eff, D = self.run_dev("loadmon27", "Untitled-1 - loadmon27 - Visual Studio Code", 1)
        self.assertEqual(set(eff) - {"UNC"}, {"loadmon27"})
        self.assertGreater(eff["loadmon27"], 10 * eff.get("UNC", 0))
        self.assertFalse({t.lower() for t in eff} & (D.JUNK | {"untitled-1", "untitled"}))
