# -*- coding: utf-8 -*-
r"""WP-22 규칙 분류 시험 — H §4.3~§4.5 · §2.3.5 · §11.4 · G-H7 · T-14(설정 섭동).

- KwIndex = kw_hit 와 같은 뜻(무작위 대조) · SubIndex = 부분 문자열 대조.
- 과제 점수 R1~R13(공유 고객 나눔·하위 도메인·폴더·감시 루트·앱·팀 규칙·학습 규칙·기간 밖·퇴역·모르는 토큰·요약 증인 가중).
- 영역 점수(긴 키워드 덮기·우선순위·공공 계급·'ai' 정규식·팀 규칙 then.domain).
- 증거 꼬리표(문턱·2위 차·문서군 합집합·msg_key 충돌·공용 문서) · G-H7(rules.py·learn.py 가 AI 답·제안 큐를 읽지 않음).
"""
import ast
import random
import unittest
from pathlib import Path

from lm27.hier import match as M
from lm27.hier.rules import (NEG, HierTags, KwIndex, RuleCtx, SubIndex, best_two, family_feats, score_domains,
                             score_projects, tag_evidence, tag_rows)
from tests.fixtures.wp22 import hierkit as K

ROOT = Path(__file__).resolve().parents[2]
SYL = ["광", "학", "브", "라", "켓", "해", "석", "열", "공", "차", "수", "율", "a", "b", "x", "lidar", "proj", "ai",
       "mail", "모듈", "설계", "-", " "]


def rnd_word(r: random.Random, n=None) -> str:
    return "".join(r.choice(SYL) for _ in range(n or r.randint(1, 4))).strip(" -") or "광학"


class KwIndexTest(unittest.TestCase):
    def test_same_as_kw_hit(self):
        r = random.Random(22)
        for mode in ("name", "head"):
            for _ in range(300):
                kws = sorted({rnd_word(r) for _ in range(r.randint(1, 12))})
                ix = KwIndex([(k, k) for k in kws], mode)
                toks = M.match_tokens(" ".join(rnd_word(r) for _ in range(r.randint(1, 8))))
                want = sorted(k for k in kws if M.kw_hit(k, toks, mode))
                got = sorted(v for _k, v in ix.hits(toks))
                self.assertEqual(got, want, (mode, kws, sorted(toks)))

    def test_fuzzy_and_parts(self):
        ix = KwIndex([("lidar-x", 1), ("proja", 2), ("정렬", 3), ("해석", 4)], "head")
        self.assertEqual([v for _k, v in ix.hits({"lidar", "x"})], [1])
        self.assertEqual([v for _k, v in ix.hits({"projaa"})], [2])               # 앞부분 일치(4자+)
        self.assertEqual([v for _k, v in ix.hits({"열해석"})], [4])                # head: 짧은 접두 뒤 꼬리
        self.assertEqual([v for _k, v in KwIndex([("정렬", 3)], "name").hits({"재정렬"})], [])
        self.assertEqual(len(ix), 4)

    def test_sub_index(self):
        r = random.Random(5)
        keys = sorted({rnd_word(r, 3).replace(" ", "") for _ in range(40)})
        si = SubIndex([(k, k) for k in keys], 3)
        for _ in range(200):
            s = "".join(rnd_word(r) for _ in range(4)).replace(" ", "")
            want = sorted(k for k in keys if len(k) >= 3 and k in s)
            self.assertEqual(sorted(v for _k, v in si.hits(s)), want)


def team(**kw) -> dict:
    t = {k: (list(v) if isinstance(v, list) else v) for k, v in K.GOLDEN_TEAM.items()}
    t["projects"] = [dict(p) for p in K.GOLDEN_TEAM["projects"]]
    t.update(kw)
    return t


class ScoreProjectsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = K.cfg()

    def test_rules_r5_to_r8(self):
        t = team(partners=[{"id": "V01", "names": [], "domains": []}])
        t["projects"][0]["partners"] = ["V01"]
        t["projects"][0]["apps"] = ["zemax_opticstudio"]
        reg = K.golden_reg(team=t)
        f = K.F("m", "mail", "[협력사:V01] 협의", mail_doms=["x.custa.example"])
        sc = score_projects(f, reg, self.cfg)
        self.assertEqual(sc["P-0007"], 1.0 + 1.5)                            # 협력사 1.0 + 메일 도메인(하위) 1.5
        f = K.F("w", "win", "", app="zemax_opticstudio")
        self.assertEqual(score_projects(f, reg, self.cfg), {"P-0007": 1.0})
        f = K.F("f", "file", "x", dir_keys=[K.fake_folder("과제A_설계"), K.fake_folder("과제A 설계")])
        self.assertEqual(score_projects(f, reg, self.cfg), {"P-0007": 3.0})  # 폴더는 과제마다 한 번

    def test_root_and_local(self):
        local = {"schema": "lm27.registry_local/1", "roots": {"R03": "P-0008"}}
        reg = K.golden_reg(local=local)
        f = K.F("f", "file", "x", root_id="R03")
        self.assertEqual(score_projects(f, reg, self.cfg), {"P-0008": 3.0})

    def test_team_and_learned_rules(self):
        t = team(rules=[{"id": "TR001", "if": {"token": "광정렬"}, "then": {"project": "P-0007"}, "w": 2.0, "status": "active"},
                        {"id": "TR002", "if": {"ext": ".zmx"}, "then": {"project": "P-0012"}, "status": "active"},
                        {"id": "TR003", "if": {"sender_label": "고객사:C01"}, "then": {"project": "P-0008"}, "w": 1.0,
                         "status": "off"}])
        learned = [{"id": "LT-1", "kind": "token", "if": {"token": "지그"}, "then": {"project": "P-0011"}, "w": 2.5,
                    "status": "active"},
                   {"id": "LT-2", "kind": "token", "if": {"token": "공차"}, "then": {"project": "P-0011"}, "w": 2.5,
                    "status": "candidate"},
                   {"id": "LK-fam-d1", "kind": "key", "if": {"fam": "d1"}, "then": {"project": "P-0012"}, "w": 5.0,
                    "status": "active"}]
        reg = K.golden_reg(team=t, learned=learned)
        f = K.F("m", "mail", "광정렬 지그 공차.zmx", exts=[".zmx"], fams=["d1"], dom_labels=["고객사:C01"])
        sc = score_projects(f, reg, self.cfg)
        self.assertEqual(sc["P-0011"], 2.5)                                   # 학습 토큰(active 만)
        self.assertEqual(sc["P-0012"], 2.0 + 5.0)                             # 팀 규칙 기본 가중 + 학습 키
        self.assertEqual(sc["P-0007"], 2.0 + 0.75)                            # 팀 규칙 + 공유 고객(1.5/2)
        self.assertEqual(sc["P-0008"], 0.75)                                  # off 규칙은 없다

    def test_period_retired_unknown_summary(self):
        t = team()
        t["projects"][1]["period"] = {"from": "2026-01", "to": "2026-03"}
        t["projects"].append({"id": "P-0020", "name": "과제Z", "domain": "DEV", "status": "retired",
                              "codenames": ["PROJ-Z"]})
        reg = K.golden_reg(team=t)
        c = RuleCtx(reg, self.cfg)
        from lm27.hier.features import lsec_of
        f = K.F("m", "mail", "[과제:P-0008] [과제:P-0020] [과제:P-0999] 수율개선", t=lsec_of("2026-09-01T00:00:00Z", 540))
        sc = score_projects(f, reg, ctx=c)
        self.assertEqual(sc, {"P-0008": (6.0 + 2.0) * 0.5})                    # 기간 밖 ×0.5, 퇴역·모르는 토큰 0
        self.assertEqual(c.unknown_token_feats, {"m"})
        f2 = K.F("s", "summary", "PROJ-Z 공유", weight_mult=0.5)
        self.assertEqual(score_projects(f2, reg, ctx=c), {})                   # 퇴역(병합 없음) 코드네임은 후보 밖
        f3 = K.F("s2", "summary", "[과제:P-0007] 브라켓", weight_mult=0.5)
        self.assertEqual(score_projects(f3, reg, ctx=c), {"P-0007": (6.0 + 2.0) * 0.5})

    def test_never_only_scored(self):
        t = team()
        t["projects"][1]["never"] = ["과제B 후속", "2세대"]
        reg = K.golden_reg(team=t)
        sc = score_projects(K.F("m", "mail", "2세대 일정"), reg, self.cfg)
        self.assertEqual(sc, {})                                              # 점수 없는 과제에는 never 를 붙이지 않는다
        sc = score_projects(K.F("m", "mail", "과제B 후속 일정"), reg, self.cfg)
        self.assertEqual(sc, {"P-0008": NEG})                                 # 이름 별칭 4.0 → never 로 −∞
        reg = K.golden_reg()
        why = {}
        sc = score_projects(K.F("m", "mail", "[과제:P-0008] 과제B 후속"), reg, self.cfg, why=why)
        self.assertEqual(sc, {"P-0008": NEG})
        self.assertIn("never −∞", why["P-0008"])
        self.assertEqual(best_two(sc), ((None, 0.0), (None, 0.0)))

    def test_cfg_perturbation(self):
        reg = K.golden_reg()
        f = K.F("m", "mail", "[과제:P-0007] 일정")
        self.assertEqual(score_projects(f, reg, K.cfg({"hier.rule.w.token": 3.0})), {"P-0007": 3.0})
        rows = tag_rows([f], reg, K.cfg({"hier.rule.evidenceMin": 7.0}))
        self.assertIsNone(rows[0]["proj"])


class ScoreDomainsTest(unittest.TestCase):
    def test_cover_priority_public(self):
        reg = K.golden_reg()
        self.assertEqual(score_domains(K.F("x", "mail", "보안교육 교육"), reg), {"COM": 2.0})
        self.assertEqual(score_domains(K.F("x", "mail", "산학 실험실 정산"), reg), {"EXT": 2.0})
        self.assertEqual(score_domains(K.F("x", "mail", "회의", dom_labels=["기관"]), reg), {"EXT": 1.5})
        self.assertEqual(score_domains(K.F("x", "mail", "email 정리"), reg), {})      # 'ai' ⊄ email
        self.assertEqual(score_domains(K.F("x", "mail", "AI 활용 방안"), reg), {"AX": 1.5})
        self.assertEqual(score_domains(K.F("x", "mail", "자동화", weight_mult=0.5), reg), {"AX": 0.75})

    def test_team_then_domain(self):
        reg = K.golden_reg(team=team(rules=[{"id": "TR9", "if": {"token": "워크숍"}, "then": {"domain": "COM"},
                                              "w": 1.0, "status": "active"}]))
        self.assertEqual(score_domains(K.F("x", "mail", "워크숍 준비"), reg), {"EXT": 2.0, "COM": 1.0})

    def test_registry_domain_meta(self):
        reg = K.golden_reg(team=team(domain_meta={"EXT": {"keywords_add": ["기술자문"], "keywords_remove": ["교육"]}}))
        self.assertEqual(score_domains(K.F("x", "mail", "기술자문"), reg), {"EXT": 2.0})
        self.assertEqual(score_domains(K.F("x", "mail", "교육"), reg), {})


class TagTest(unittest.TestCase):
    def test_thresholds_and_tags(self):
        reg = K.golden_reg()
        fs = [K.F("a", "mail", "[과제:P-0007] 공차", key="mk1"),
              K.F("b", "mail", "브라켓 양산라인", key="mk2"),                     # 2.0 대 2.0 — 2위 차 0
              K.F("c", "teams", "PROJ-A", key="mk3"),
              K.F("c2", "teams", "[과제:P-0008]", key="mk3"),                      # 같은 msg_key 에 엇갈린 꼬리표
              K.F("f1", "file", "광학모듈", fams=["dA"]),
              K.F("w1", "win", "브라켓 설계 - CAD", fams=["dA"])]
        t = tag_evidence(fs, reg, K.cfg())
        self.assertIsInstance(t, HierTags)
        self.assertEqual(t.msg, {"mk1": "P-0007"})
        self.assertEqual(t.fam, {"dA": "P-0007"})                                  # 키워드 2개(파일 + 창 합집합)
        self.assertEqual(t.to_obj()["shared_fams"], [])
        self.assertEqual(set(family_feats(fs)), {"dA"})

    def test_shared_docs(self):
        t = team()
        t["projects"][0]["shared_docs"] = ["팀공용_마스터"]
        reg = K.golden_reg(team=t)
        tags = tag_evidence([], reg, K.cfg())
        self.assertEqual(tags.shared_fams, frozenset({K.fake_doc("팀공용_마스터")}))

    def test_attachment_family(self):
        reg = K.golden_reg()
        m = K.F("m", "mail", "회신", key="k", names=(("dX", "광학모듈 브라켓.xlsx"),), fams=["dX"])
        rows = {r["id"]: r for r in tag_rows([m], reg, K.cfg())}
        self.assertEqual(rows["fam:dX"]["proj"], "P-0007")
        self.assertEqual(rows["m"]["proj"], None)                                 # 메일 제목은 문서군에 넣지 않는다


class NoFeedbackTest(unittest.TestCase):
    """G-H7(H-I6) — rules.py·learn.py 는 ai_out·제안 큐를 import·경로 문자열로 읽지 않는다."""

    def test_static(self):
        for name in ("rules.py", "learn.py"):
            src = (ROOT / "lm27" / "hier" / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            doc_nodes = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef) and n.body and \
                        isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                    doc_nodes.add(id(n.body[0].value))
            for n in ast.walk(tree):
                if isinstance(n, ast.Import | ast.ImportFrom):
                    mods = [a.name for a in n.names] + [getattr(n, "module", "") or ""]
                    for m in mods:
                        self.assertNotRegex(m, r"proposals|copilot_io|ai_out|lm27\.bridge", (name, m))
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes:
                    self.assertNotRegex(n.value, r"ai_out|proposals", (name, n.value))


if __name__ == "__main__":
    unittest.main()
