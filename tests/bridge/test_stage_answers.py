# -*- coding: utf-8 -*-
"""WP-25 단계 답 검증·정규화·폴백 — task_label(H §6.5 · HG30: 목록 밖 코드·NEW 이름/영역·제목 금액·시간형 키 → 무효,
예약 과제 허용, 따옴표·[과제:] 정리, 폴백) · workflow_label(B §8.4: S 부분열·낯선 S 무효·빠진 S 채움·시간 문장 지움·유형
붙임) · review_text(B §8.5: refs·번호표·시간 문장·peers_map) · agentic_match(B §8.6: 같은 a 첫 것·카탈로그 이름 중복 니즈 버림)
· subagent_review(B §8.7: 낯선 S sub 버림·부적합이면 subs 비움·플래그 폴백) · taxonomy_consolidate(H §8.3: 자기 자신·범위 밖
무효, same_as_key) · taxonomy_bootstrap(H §8.2 행 규칙 · 항목형 L2 에서는 커밋 차단) · speech_act(B §8.2)."""
from __future__ import annotations

import unittest

from lm27.bridge import exchange as X
from lm27.bridge.stages import REGISTRY
from lm27.bridge.stages import base as B
from lm27.bridge.transport import SendResult

from tests.fixtures.wp25 import kit as K


def classify(spec, batch, items, ctx, rid="R7F3QK"):
    """조립(묶음 기억) → 봉투 분류(L2 한 벌)."""
    import json
    asm = K.assemble(spec, batch, ctx, rid)
    body = "```json\n" + json.dumps({"rid": rid, "n": len(items), "items": items}, ensure_ascii=False) + \
           f"\n```\n[[END {rid}]]"
    return X.classify(spec, SendResult(phase="replied", body=body), asm, ctx)


TL_FIELDS = {"kinds": "메일발신 3·문서 1", "subjects": ["[과제:P-0007] 공차 해석 결과 공유"], "files": ["공차해석.xlsx"],
             "apps": ["해석 프로그램"], "domains": ["사내"], "cands": [["P-0007", 0.62]], "hint": "OPT/ANALYSIS/DEV",
             "regv": ""}


class TaskLabel(unittest.TestCase):
    def setUp(self):
        self.spec = REGISTRY["task_label"]
        self.ctx = K.ctx_for(self.spec, K.reg())
        self.batch = [K.wi(f"grp:{i}", TL_FIELDS) for i in range(1, 9)]

    def ans(self, **kw):
        a = {"project": "P-0007", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "광학 모듈 공차 해석",
             "new": "", "dom": "", "conf": "h"}
        a.update(kw)
        return a

    def test_HG30_like_cases(self):
        items = [{"id": 1, **self.ans()},
                 {"id": 2, **self.ans(project="P-0999")},                                  # 목록 밖
                 {"id": 3, **self.ans(project="NEW", new="")},                             # NEW 이름 없음
                 {"id": 4, **self.ans(project="NEW", new="방열 모듈", dom="")},             # NEW 영역 없음
                 {"id": 5, **self.ans(title="정산 1,200만원 품의")},                        # 제목 금액
                 {"id": 6, **self.ans(hours=3)},                                           # 시간형 키
                 {"id": 7, **self.ans(project="P-9904", field="ETC", func="ADMIN", wtype="OFFICE")},   # 예약 과제
                 {"id": 8, **self.ans(project="NEW", new="'방열 모듈'", dom="DEV", title='"[과제:P-0007] 방열 해석."')}]
        status, info = classify(self.spec, self.batch, items, self.ctx)
        self.assertEqual(status, "partial")
        self.assertEqual(info["invalid"], {2: "unknown_code:project", 3: "missing:new", 4: "missing:dom",
                                           5: "bad_pattern:title", 6: "forbidden_field"})
        self.assertEqual(info["answers"][1], self.ans())
        self.assertEqual(info["answers"][7]["project"], "P-9904")
        a8 = info["answers"][8]
        self.assertEqual((a8["title"], a8["new"], a8["dom"]), ("방열 해석", "방열 모듈", "DEV"))
        self.assertEqual(set(info["answers"][1]), {"project", "field", "func", "wtype", "title", "new", "dom", "conf"})

    def test_fallback_rule_label(self):
        it = K.wi("grp:1", TL_FIELDS, rule={"project": "P-0007", "score": 0.62, "source": "rule_probable",
                                            "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "공차해석"})
        self.assertEqual(self.spec.fallback(it, self.ctx, "ai_failed"),
                         {"project": "P-0007", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "공차해석",
                          "new": "", "dom": "", "conf": "l"})
        none = K.wi("grp:2", TL_FIELDS, rule={"project": None, "source": "none"})
        fb = self.spec.fallback(none, self.ctx, "ai_failed")
        self.assertEqual((fb["project"], fb["field"], fb["func"], fb["wtype"], fb["title"]),
                         ("NONE", "OPT", "ANALYSIS", "DEV", "미분류 업무"))      # 규칙안(hint)에서 분야·기능·유형

    def test_codes_include_reserved(self):
        self.assertIn("P-9901", self.ctx.codes("projects"))
        self.assertIn("P-0007", self.ctx.codes("projects"))
        d = K.ctx_for(self.spec, K.DICT_REG)
        self.assertTrue({"P-9905", "P-0003"} <= d.codes("projects"))

    def test_shrink(self):
        big = dict(TL_FIELDS, subjects=["가" * 60, "나" * 60, "다" * 60], files=["f" * 40] * 5, domains=["사내"] * 3)
        nf = self.spec.shrink(K.wi("grp:x", big), 260)
        self.assertEqual((len(nf["subjects"]), len(nf["files"])), (1, 2))
        self.assertIsNone(self.spec.shrink(K.wi("grp:x", big), 40))


class Workflow(unittest.TestCase):
    def setUp(self):
        self.spec = REGISTRY["workflow_label"]
        self.ctx = K.ctx_for(self.spec, K.reg())
        self.f = {"project": "P-0012", "field": "OPT", "func": "ANALYSIS",
                  "steps": [["S1", "REQ_IN", 12], ["S2", "APP_CAE", 30], ["S3", "DOC_XLS", 8]],
                  "trans": [["S1", "S2", 10]], "tasks": ["공차 해석"]}

    def test_subsequence_fill_and_scrub(self):
        batch = [K.wi("ws:a", self.f), K.wi("ws:b", self.f), K.wi("ws:c", self.f)]
        items = [{"id": 1, "role": "해석 담당", "summary": "의뢰를 받아 해석합니다. 주 3시간 정도 듭니다.",
                  "steps": [{"s": "S1", "label": "의뢰 접수", "desc": "요청 확인"}, {"s": "S3", "label": "결과 정리"}]},
                 {"id": 2, "role": "x", "summary": "y", "steps": [{"s": "S3", "label": "a"}, {"s": "S1", "label": "b"}]},
                 {"id": 3, "role": "x", "summary": "y", "steps": [{"s": "S9", "label": "a"}]}]
        status, info = classify(self.spec, batch, items, self.ctx)
        self.assertEqual(info["invalid"], {2: "bad_pattern:steps", 3: "bad_pattern:steps"})
        a = info["answers"][1]
        self.assertEqual(a["summary"], "의뢰를 받아 해석합니다.")
        self.assertEqual([(s["s"], s["type"], s["label"]) for s in a["steps"]],
                         [("S1", "REQ_IN", "의뢰 접수"), ("S2", "APP_CAE", "해석 프로그램"), ("S3", "DOC_XLS", "결과 정리")])
        self.assertEqual((a["filled_steps"], a["time_scrubbed"]), (1, 1))

    def test_key_material_ignores_counts(self):
        a = B.content_key(self.spec, self.f)
        f2 = dict(self.f, steps=[["S1", "REQ_IN", 99], ["S2", "APP_CAE", 1], ["S3", "DOC_XLS", 2]])
        self.assertEqual(a, B.content_key(self.spec, f2))
        f3 = dict(self.f, steps=[["S1", "REQ_IN", 1], ["S2", "MEET", 1], ["S3", "DOC_XLS", 1]])
        self.assertNotEqual(a, B.content_key(self.spec, f3))

    def test_est_out_and_fallback(self):
        it = K.wi("ws:a", self.f)
        self.assertEqual(self.spec.est_out(it), 200 + 110 * 3)
        fb = self.spec.fallback(it, self.ctx, "ai_failed")
        self.assertEqual(fb["role"], "판단 유보")
        self.assertEqual(fb["summary"], "해석·분석 업무가 의뢰 수신에서 시작해 표 계산로 이어집니다.")
        self.assertEqual([s["desc"] for s in fb["steps"]], ["", "", ""])


class Review(unittest.TestCase):
    def setUp(self):
        self.spec = REGISTRY["review_text"]
        self.f = {"kind": "week", "period": "2026-09-28~2026-10-04",
                  "facts": [["F1", "완료", "공차 해석", "P-0012", "해석·분석"], ["F2", "진행", "지그 설계", "P-0007", "설계"]],
                  "peers": [["동료1", 3]]}
        self.it = K.wi("review:week:2026-W40", self.f, rule={"peers_map": {"동료1": "w" + "1" * 16}})
        self.ctx = K.ctx_for(self.spec, K.reg())

    def test_refs_tags_and_scrub(self):
        items = [{"id": 1, "summary": "공차 해석을 마쳤습니다. 이번 주 12시간을 썼습니다. 동료1·동료7 과 함께 했습니다.",
                  "highlights": [{"text": "공차 해석 완료", "refs": ["F1"]}, {"text": "없는 일", "refs": ["F9"]}],
                  "relations": [{"text": "x", "refs": ["E1"]}], "next": ["지그 설계 마무리"]}]
        status, info = classify(self.spec, [self.it], items, self.ctx)
        self.assertEqual(status, "ok")
        a = info["answers"][1]
        self.assertEqual(a["summary"], "공차 해석을 마쳤습니다. 동료1·동료 과 함께 했습니다.")
        self.assertEqual(a["highlights"], [{"text": "공차 해석 완료", "refs": ["F1"]}])
        self.assertEqual(a["relations"], [])
        self.assertEqual(a["peers_map"], {"동료1": "w" + "1" * 16})
        self.assertEqual((a["bad_refs"], a["time_scrubbed"], a["peer_tag_fixed"]), (2, 1, 1))

    def test_invalid_when_nothing_left(self):
        items = [{"id": 1, "summary": "주 40시간 근무.", "highlights": [{"text": "a", "refs": ["F8"]}]}]
        status, info = classify(self.spec, [self.it], items, self.ctx)
        self.assertEqual(info["invalid"], {1: "bad_pattern:highlights"})

    def test_fallback_template(self):
        fb = self.spec.fallback(self.it, self.ctx, "no_ai_out")
        self.assertEqual(fb["summary"], "이번 주에는 1건을 마쳤고 1건을 진행했습니다. 주요 과제는 P-0007, P-0012입니다.")
        self.assertEqual(fb["highlights"], [{"text": "공차 해석", "refs": ["F1"]}])
        self.assertEqual(fb["next"], ["지그 설계"])
        self.assertEqual(self.spec.est_out(self.it), 1200)
        self.assertEqual(self.spec.est_out(K.wi("review:month:2026-09", dict(self.f, kind="month"))), 1800)


class Agentic(unittest.TestCase):
    def setUp(self):
        self.spec = REGISTRY["agentic_match"]
        self.ctx = K.ctx_for(self.spec, K.reg())
        self.it = K.wi("ag:DOC_XLS", {"type": "DOC_XLS", "label": "결과 정리", "freq": "주 1~2회", "io": "-", "apps": "-",
                                      "ws": []})

    def test_dup_agents_and_catalog_name_need(self):
        items = [{"id": 1, "m": [{"a": "AG02", "fit": "상", "why": "표 정리"}, {"a": "AG02", "fit": "하"}],
                  "need": {"name": "표 정리 도우미", "logic": "x", "in": "a", "out": "b"}},
                 {"id": 2, "m": [{"a": "AG09", "fit": "상"}], "need": None},
                 {"id": 3, "m": [], "need": {"name": "회의록 요약기", "logic": "녹취를 받아 요약"}}]
        batch = [self.it, K.wi("ag:2", self.it.fields), K.wi("ag:3", self.it.fields)]
        status, info = classify(self.spec, batch, items, self.ctx)
        self.assertEqual(info["invalid"], {2: "unknown_code:m.a"})                  # 퇴역 에이전트
        a1 = info["answers"][1]
        self.assertEqual((a1["m"], a1["need"], a1["dup_agents"], a1["need_dup_catalog"]),
                         ([{"a": "AG02", "fit": "상", "why": "표 정리"}], None, 1, 1))
        self.assertEqual(info["answers"][3]["need"], {"name": "회의록 요약기", "logic": "녹취를 받아 요약", "in": "", "out": ""})

    def test_fallback_by_step_type(self):
        self.assertEqual(self.spec.fallback(self.it, self.ctx, "ai_failed"),
                         {"m": [{"a": "AG02", "fit": "중", "why": "단계 유형 일치(규칙)"}], "need": None})
        other = K.wi("ag:MEET", dict(self.it.fields, type="MEET"))
        self.assertEqual(self.spec.fallback(other, self.ctx, "ai_failed"), {"m": [], "need": None})


class Subagent(unittest.TestCase):
    def setUp(self):
        self.spec = REGISTRY["subagent_review"]
        self.f = {"project": "P-0012", "role": "해석 담당",
                  "steps": [["S1", "의뢰 접수", "REQ_IN", "D1 R1 B0 L1 S1 T1"], ["S2", "해석 수행", "APP_CAE", "D1 R1 B1 L0 S1 T0"],
                            ["S3", "결과 정리", "DOC_XLS", "D1 R1 B1 L1 S1 T1"], ["S4", "회의", "MEET", "D0 R0 B0 L1 S0 T0"]]}
        self.it = K.wi("sa:r_1", self.f)
        self.ctx = K.ctx_for(self.spec)

    def test_normalize(self):
        items = [{"id": 1, "verdict": "적합", "orch": "흐름 조율", "risk": "검토",
                  "subs": [{"steps": ["S1", "S2"], "role": "의뢰 정리"}, {"steps": ["S9"], "role": "x"}]},
                 {"id": 2, "verdict": "부적합", "orch": "x", "subs": [{"steps": ["S1"], "role": "y"}]}]
        status, info = classify(self.spec, [self.it, K.wi("sa:r_2", self.f)], items, self.ctx)
        a1, a2 = info["answers"][1], info["answers"][2]
        self.assertEqual((len(a1["subs"]), a1["bad_subs"]), (1, 1))
        self.assertEqual((a2["subs"], a2["orch"], a2["cleared_subs"]), ([], "", 1))

    def test_rule_fallback(self):
        fb = self.spec.fallback(self.it, self.ctx, "no_ai_out")
        self.assertEqual(fb["verdict"], "적합")                                    # 후보 3/4 ≥ 0.5
        self.assertEqual([s["steps"] for s in fb["subs"]], [["S1", "S2", "S3"]])
        self.assertEqual((fb["subs"][0]["io"], fb["subs"][0]["check"], fb["orch"], fb["risk"]),
                         ("REQ_IN → DOC_XLS", "결과 검토", "해석 담당 흐름 조율", "규칙 판정 — 사람 검토 필요"))
        none = K.wi("sa:r_3", dict(self.f, steps=[["S1", "회의", "MEET", "D0 R0 B0 L1 S0 T0"]]))
        self.assertEqual(self.spec.fallback(none, self.ctx, "x")["verdict"], "부적합")


class Consolidate(unittest.TestCase):
    def test_same_as_key_and_self_invalid(self):
        spec = REGISTRY["taxonomy_consolidate"]
        ctx = K.ctx_for(spec)
        batch = [K.wi("cs:a", {"name": "방열 모듈", "dom": "DEV", "match": ["방열"]}),
                 K.wi("cs:b", {"name": "방열모듈 개발", "dom": "DEV", "match": ["방열"]}),
                 K.wi("cs:c", {"name": "수율 개선", "dom": "MP", "match": []})]
        items = [{"id": 1, "same_as": 2, "conf": "h"}, {"id": 2, "same_as": 2, "conf": "m"},
                 {"id": 3, "same_as": 9, "conf": "l"}]
        status, info = classify(spec, batch, items, ctx)
        self.assertEqual(info["invalid"], {2: "bad_pattern:same_as", 3: "bad_pattern:same_as"})
        self.assertEqual(info["answers"][1], {"same_as": 2, "conf": "h", "same_as_key": "cs:b"})
        self.assertEqual(spec.fallback(batch[0], ctx, "x"), {"same_as": 0, "conf": "l"})


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self.spec = REGISTRY["taxonomy_bootstrap"]
        self.ctx = K.ctx_for(self.spec, K.reg())
        self.batch = [K.wi(f"grp:{i}", {"dom": "DEV", "title": f"해석 {i}", "files": [], "subject": "", "peer": ""})
                      for i in range(1, 4)]

    def test_row_rules(self):
        self.spec.title_line("R7F3QK", 3, self.batch, self.ctx)
        good, codes = self.spec.normalize_row({"name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project",
                                               "match": ["방열", "가" * 30], "obs": [1, "2", 2, "x"]}, None, self.ctx)
        self.assertEqual((good["match"][1], good["obs"], codes), ("가" * 20, [1, 2], ()))
        self.assertEqual(self.spec.normalize_row({"name": "x", "code": "", "dom": "DEV", "kind": "project"}, None,
                                                 self.ctx), (None, ("bad_name",)))
        self.assertEqual(self.spec.normalize_row({"name": "[사람] 지원", "code": "", "dom": "COM", "kind": "common"},
                                                 None, self.ctx)[0], None)
        whole = self.spec.normalize({"rows": [dict(good, obs=[1, 7]), dict(good), {"name": "", "code": "P-0007",
                                                                                   "dom": "DEV", "kind": "project"}],
                                     "n": 3, "more": False}, None, self.ctx)
        self.assertEqual([r.get("name") or r.get("code") for r in whole["rows"]], ["방열 모듈", "P-0007"])
        self.assertEqual(whole["rows"][0]["obs"], [1])                              # 표본 3줄 밖 번호는 버림

    def test_item_mode_guard_blocks_misassigned_rows(self):
        """L2 가 단건형 행 봉투를 모르는 동안(항목형 검증) 행 → 표본 잘못 맞춤 커밋을 막는다(완료 보고 CR)."""
        items = [{"id": 1, "name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project", "match": [], "obs": [1]}]
        status, info = classify(self.spec, self.batch, items, self.ctx)
        self.assertEqual((status, info["answers"]), ("format", {}))
        self.assertEqual(self.spec.validate({"rows": []}, None, self.ctx), "")
        self.assertEqual(self.spec.fallback(self.batch[0], self.ctx, "ai_failed"), {"rows": [], "n": 0, "more": False})
        self.assertTrue(self.spec.row_envelope)


class SpeechAct(unittest.TestCase):
    def test_answers_and_fallback(self):
        spec = REGISTRY["speech_act"]
        ctx = K.ctx_for(spec)
        f = {"ch": "teams", "dir": "in", "chat": "1:1", "prev": "-", "text": "검토 부탁드립니다"}
        batch = [K.wi("msg:1", f, rule={"act": "request"}), K.wi("msg:2", f)]
        status, info = classify(spec, batch, [{"id": 1, "act": "request", "conf": "h"}, {"id": 2, "act": "order",
                                                                                         "conf": "h"}], ctx)
        self.assertEqual(info["invalid"], {2: "bad_enum:act"})
        self.assertEqual(spec.fallback(batch[0], ctx, "x"), {"act": "request", "conf": "l"})
        self.assertEqual(spec.fallback(batch[1], ctx, "x"), {"act": "info", "conf": "l"})
        self.assertIsNone(spec.shrink(K.wi("msg:3", dict(f, text="가" * 200)), 20))
        self.assertEqual(len(spec.shrink(K.wi("msg:3", dict(f, text="가" * 200)), 200)["text"]), 60)


if __name__ == "__main__":
    unittest.main()
