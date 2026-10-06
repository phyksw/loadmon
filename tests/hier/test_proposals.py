# -*- coding: utf-8 -*-
r"""WP-22 새 과제 제안 큐 시험 — H §7 · §3.3 · T-H03 · T-H04 · T-H19 · X-240(domain_guess) · X-252(ai_out.proposals 폐지).
제안은 레지스트리·규칙에 자동으로 들어가지 않는다(H-I6) — 사람 결정(받기·대응)으로만."""
import json
import unittest

from lm27.hier import proposals as PQ
from lm27.hier.registry import load_effective
from tests.fixtures.wp22 import hierkit as K

AT = "2026-10-05T10:00:00+09:00"


def q_new(q, reg, label, group="grp:000000000001", eff=600, **kw):
    return q.on_new_name(label, kw.pop("dom", "DEV"), group, kw.pop("src", "task_label"), reg, cfg=K.cfg(),
                         effort_min=eff, at=AT, **kw)


class OnNewNameTest(unittest.TestCase):
    def test_branches(self):
        reg = K.golden_reg()
        q = PQ.ProposalQueue()
        a = q_new(q, reg, "과제A 모듈")
        self.assertEqual((a.project, a.src), ("P-0007", "ai_alias"))           # 등록 과제 별칭
        a = q_new(q, reg, "작은 일", eff=30)
        self.assertEqual((a.project, a.src), ("P-9901", "too_small"))          # 60분 미만 → 예약 과제
        a = q_new(q, reg, "방열 모듈")
        self.assertEqual(a.proposal, "pr_1")
        self.assertEqual(q.get("pr_1")["domain_guess"], "DEV")
        self.assertEqual(q.get("pr_1")["status"], "pending")
        b = q_new(q, reg, "방열모듈", group="grp:000000000002")                 # T-H19 같은 제안(ukey 동일 → 자동)
        self.assertEqual(b.proposal, "pr_1")
        self.assertEqual(q.get("pr_1")["groups"], ["grp:000000000001", "grp:000000000002"])
        c = q_new(q, reg, "방열 모듈 2세대", group="grp:000000000003")          # 숫자 토큰 상이 → 새 제안
        self.assertEqual(c.proposal, "pr_2")
        q.reject("pr_2", at=AT)
        d = q_new(q, reg, "방열 모듈 2세대", dom="MP")
        self.assertEqual((d.project, d.src), ("P-9902", "rejected_name"))      # 거절한 이름은 다시 제안하지 않는다
        self.assertEqual(q_new(q, reg, "x").src, "invalid")
        self.assertEqual(q_new(q, reg, "새 일", dom="UNC").src, "invalid")

    def test_ask_zone_and_label_check(self):
        reg = K.golden_reg()
        q = PQ.ProposalQueue()
        q_new(q, reg, "공차해석 자동화")
        a = q_new(q, reg, "공차해석 자동화 도구 개발", group="grp:000000000009")
        self.assertIsNotNone(a.proposal)
        q2 = PQ.ProposalQueue()
        q_new(q2, reg, "레이저 모듈", label_check=lambda s: False)
        self.assertEqual(q2.items[0]["label"], "개발 프로젝트 새 과제 #1")      # 팀 라벨 검사 실패 → 대체 이름
        self.assertIn("proposal_label_rejected", q2.warnings)
        q3 = PQ.ProposalQueue()
        q_new(q3, reg, "열해석 모델")
        r = q_new(q3, reg, "열해석 모형", group="grp:00000000000a")
        if r.ask is not None:
            self.assertEqual(q3.asks[-1]["b"], "pr_1")


class PersistTest(unittest.TestCase):
    def test_save_load_bak_and_accept(self):
        reg = K.golden_reg()
        with K.TmpTree() as t:
            q = PQ.ProposalQueue.for_paths(t.paths)
            q_new(q, reg, "방열 모듈")
            self.assertTrue(q.save())
            q = PQ.ProposalQueue.for_paths(t.paths)
            self.assertEqual(q.next_seq, 2)
            lid = q.accept_local("pr_1", ["방열", "열해석", "x"], paths=t.paths, at=AT)
            self.assertEqual(lid, "L-0001")
            q.save()
            loc = json.loads(t.paths.hier_local_file("registry_local.json").read_text(encoding="utf-8"))
            p = loc["projects"][0]
            self.assertEqual((p["id"], p["name"], p["domain"], p["proposal_id"]), ("L-0001", "방열 모듈", "DEV", "pr_1"))
            self.assertEqual(p["keywords"], ["방열", "열해석"])                  # 사용자가 고른 낱말만(2자 이상)
            t.paths.hier_local_file("proposals.json").write_bytes(b"not json")
            q2 = PQ.ProposalQueue.for_paths(t.paths)
            self.assertIn("proposals_broken", q2.warnings)
            self.assertEqual(q2.get("pr_1")["status"], "pending")               # .bak = 직전 판
            q3 = PQ.ProposalQueue.load(t.paths.hier_local_file("nope.json"), None, min_seq=7)
            self.assertEqual((q3.items, q3.next_seq, q3.warnings), ([], 7, []))
            with self.assertRaises(ValueError):
                q.accept_local("pr_9", paths=t.paths)

    def test_registry_sync(self):
        """T-H03 · T-H04 — 팀 adopted·별칭 일치 → mapped(사용자 조작 없음)."""
        reg = K.golden_reg()
        q = PQ.ProposalQueue()
        q_new(q, reg, "광센서 선행")
        q_new(q, reg, "방열 모듈", group="grp:000000000005")
        team = dict(K.GOLDEN_TEAM)
        team["projects"] = list(K.GOLDEN_TEAM["projects"]) + [
            {"id": "P-0021", "name": "광센서 개발", "domain": "DEV", "aliases": ["광센서 선행"]},
            {"id": "P-0022", "name": "냉각 모듈", "domain": "DEV",
             "adopted": [{"person_key": "p_7fa3c2d19e01", "proposal_id": "pr_2"}]}]
        reg2 = K.golden_reg(team=team)
        got = q.sync_registry(reg2, "p_7fa3c2d19e01", at=AT)
        self.assertEqual(sorted(got), [("pr_1", "P-0021"), ("pr_2", "P-0022")])
        self.assertEqual(q.get("pr_1")["status"], "mapped")
        self.assertEqual(q.get("pr_2")["mapped_to"], "P-0022")
        a = q_new(q, reg2, "방열 모듈", group="grp:000000000005")                # 저장된 NEW 답이 다음 실행에 다시 와도
        self.assertEqual((a.project, a.src, a.proposal), ("P-0022", "mapped", None))   # 라벨 = 팀 과제, 새 제안 없음
        self.assertEqual(len(q.items), 2)

    def test_local_project_maps_to(self):
        with K.TmpTree() as t:
            reg = K.golden_reg()
            q = PQ.ProposalQueue.for_paths(t.paths)
            q_new(q, reg, "방열 모듈")
            q.accept_local("pr_1", paths=t.paths, at=AT)
            team = dict(K.GOLDEN_TEAM)
            team["projects"] = list(K.GOLDEN_TEAM["projects"]) + [
                {"id": "P-0030", "name": "방열 모듈", "domain": "DEV"}]
            t.write_json(t.paths.registry_cache(), team)
            reg2, st = load_effective(t.paths, K.cfg(), None, folder_key=K.fake_folder, doc_key=K.fake_doc)
            self.assertEqual(reg2.projects["L-0001"].maps_to, "P-0030")          # 개인 과제 이름 = 팀 과제 이름 → 대응
            got = q.sync_registry(reg2, None, at=AT)
            self.assertEqual(got, [("pr_1", "P-0030")])


class CodenameReviewTest(unittest.TestCase):
    """H §8.1 코드네임 검토 버튼 — [과제 이름] → 개인 과제(codenames, 설명 비움) · [무시] · [이대로 진행] · [건너뛰기]."""

    def test_from_codename_and_marks(self):
        reg = K.empty_reg()
        with K.TmpTree() as t:
            q = PQ.ProposalQueue.for_paths(t.paths)
            lid = q.from_codename("PROJ-X", "MP", reg, paths=t.paths, at=AT)
            self.assertEqual(lid, "L-0001")
            self.assertEqual(q.from_codename("proj-x", "MP", reg, paths=t.paths, at=AT), "L-0001")   # 같은 이름 다시 — 그대로
            it = q.get("pr_1")
            self.assertEqual((it["status"], it["local_project"], it["domain_guess"]), ("accepted_local", "L-0001", "MP"))
            loc = json.loads(t.paths.hier_local_file("registry_local.json").read_text(encoding="utf-8"))
            p = loc["projects"][0]
            self.assertEqual((p["codenames"], p["copilot_desc"], p["created_from"]), (["PROJ-X"], "", "codename_review"))
            cr = PQ.mark_codename_review(paths=t.paths, ignore=["QX-12", "회의"])
            self.assertEqual(cr["ignored"], sorted({PQ.codename_hash("QX-12"), PQ.codename_hash("회의")}))
            cr = PQ.mark_codename_review(paths=t.paths, done_at=AT, ignore=["QX-12"])
            self.assertEqual((len(cr["ignored"]), cr["done_at"]), (2, AT))
            self.assertTrue(t.paths.hier_local_file("registry_local.json.bak").exists())
            reg2, _st = load_effective(t.paths, K.cfg(), None, folder_key=K.fake_folder, doc_key=K.fake_doc)
            self.assertEqual(reg2.codename_review["done_at"], AT)
            self.assertEqual(reg2.resolve(reg2.alias_ix["projx"]), "L-0001")
            self.assertEqual(q.from_codename("PROJ-X", "DEV", reg2, paths=t.paths, at=AT), "L-0001")   # 등록된 이름
            PQ.mark_codename_review(paths=t.paths, skipped=True)
            t.paths.hier_local_file("registry_local.json").write_bytes(b"{broken")
            with self.assertRaises(ValueError):                                 # 깨진 파일은 덮지 않는다
                PQ.mark_codename_review(paths=t.paths, skipped=False)
            self.assertEqual(t.paths.hier_local_file("registry_local.json").read_bytes(), b"{broken")
        with self.assertRaises(ValueError):
            PQ.update_local(lambda o: o.update(schema="x"), local_path=None)


class ConsolidateTest(unittest.TestCase):
    """H §8.3·§8.4 — 2회차 AI 통합 쌍은 S2 점수의 근거(+1.0)일 뿐: AI 단독이면 H04 질문, 사람이 볼 근거가 있으면 자동."""

    def test_pairs(self):
        reg = K.golden_reg()
        q = PQ.ProposalQueue()
        q_new(q, reg, "AX 도입")
        q_new(q, reg, "Agentic 활용", group="grp:000000000002", dom="DEV")
        q_new(q, reg, "공차해석 자동화", group="grp:000000000003", evidence_keys=["d1", "d2"])
        q_new(q, reg, "공차 분석 도구", group="grp:000000000004", evidence_keys=["d2", "d3"])      # 공유 근거 1/3 — 질문 구간
        self.assertEqual(len(q.live()), 4)
        q.asks.clear()
        from lm27.hier.names import ukey
        pairs = {frozenset((ukey("AX 도입"), ukey("Agentic 활용"))),
                 frozenset((ukey("공차해석 자동화"), ukey("공차 분석 도구"))),
                 frozenset((ukey("AX 도입"), ukey("없는 이름")))}
        merged, asks = q.consolidate(pairs, reg, K.cfg(), at=AT)
        self.assertEqual(merged, [("pr_4", "pr_3")])                            # 사람이 볼 근거 + AI → 자동(S2)
        self.assertEqual([(a["a"], a["b"], a["scope"]) for a in asks], [("pr_2", "pr_1", "S2")])
        self.assertIn("AI 단독 근거", asks[0]["why"])
        self.assertEqual(q.get("pr_4")["status"], "merged")
        self.assertEqual(q.consolidate([], reg), ([], []))
        a = q_new(q, reg, "공차 분석 도구", group="grp:000000000009")             # 합친 이름이 다시 와도 대표 제안으로
        self.assertEqual((a.proposal, a.project), ("pr_3", None))
        self.assertEqual(len(q.items), 4)


class PayloadTest(unittest.TestCase):
    def test_team_payload_refresh_merge(self):
        reg = K.golden_reg()
        q = PQ.ProposalQueue()
        q_new(q, reg, "방열 모듈")
        q_new(q, reg, "레이저 모듈", group="grp:000000000002")
        labels = {"u_1": {"proposal_id": "pr_1"}, "u_2": {"proposal_id": None}}
        self.assertEqual(q.team_payload(labels), [{"proposal_id": "pr_1", "kind": "project", "label": "방열 모듈",
                                                   "domain_guess": "DEV"}])
        from lm27.hier.groups import Group
        q.refresh(labels, [Group("grp:000000000001", "a", "u_1", ("u_1",), 10)], efforts={"u_1": 300},
                  days={"u_1": ("2026-09-01", "2026-09-03")})
        it = q.get("pr_1")
        self.assertEqual((it["n_units"], it["effort_min"], it["first_at"], it["last_at"]),
                         (1, 300, "2026-09-01", "2026-09-03"))
        q.merge("pr_2", "pr_1", at=AT)
        self.assertEqual(q.resolve("pr_2"), "pr_1")
        self.assertIn("grp:000000000002", q.get("pr_1")["groups"])
        q.rename("pr_1", "방열 모듈 개발", at=AT)
        self.assertEqual(q.get("pr_1")["ukey"], "방열모듈개발")
        q.reject("pr_1", at=AT)
        q.unreject("pr_1", at=AT)
        self.assertEqual(q.get("pr_1")["status"], "pending")
        self.assertEqual([e["event"] for e in q.get("pr_1")["history"]], ["created", "renamed", "rejected", "unrejected"])

    def test_normalize(self):
        self.assertEqual(PQ.normalize_label('  "[과제:P-0007] 방열​  모듈"  '), "방열 모듈")
        self.assertEqual(PQ.proposal_num("pr_12"), 12)
        self.assertEqual(PQ.proposal_num("x"), -1)


if __name__ == "__main__":
    unittest.main()
