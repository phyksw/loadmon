# -*- coding: utf-8 -*-
"""WP-25 단계 프롬프트 — H §6.3 task_label 실물(WP-22 골든 조각 + copilot_io.prompt_context, '이름 또는' 한 곳만 다름) ·
H §8.2 부트스트랩 실물 · 11종 모두 정제 게이트 ②(scan 0 · 카나리아 0) 통과(웹 노출 여부 둘 다, S5 잔여 0) · T-H17(웹 노출이면
task_label domains 값 '-') · 중첩 목록 글의 엄격 규칙(review_text·subagent_review — S1·S2·S3) · X-255(agentic 머리말에 이름·desc
미전송, 퇴역 제외) · G-H9(과제 150개 레지스트리에서 모든 묶음 ≤ 입력 예산 — 축약 머리말)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lm27.bridge.stages import REGISTRY
from lm27.hier.copilot_io import prompt_context
from lm27.util import events

from tests.fixtures.wp24.rig import Rig
from tests.fixtures.wp25 import kit as K

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "wp22" / "golden.json"
SEEN = "[앞서 쓴 이름] 광학 모듈 공차 해석 / 시험 지그 설계"


def setUpModule():
    events.configure(mode="off")


def golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["prompt"]


def task_items():
    rows = [
        {"kinds": "메일수신 2·메일발신 3·팀즈 3·문서 2", "subjects": ["[과제:P-0007] 공차 해석 결과 공유", "RE: 공차 해석 조건 확인"],
         "files": ["공차해석_v3.xlsx", "브라켓_조립도.pdf"], "apps": ["해석 프로그램", "엑셀"], "domains": ["[고객사:C01]", "사내"],
         "cands": [["P-0007", 0.62], ["P-0012", 0.21]], "hint": "OPT/ANALYSIS/DEV", "regv": ""},
        {"kinds": "문서 4·앱 1", "subjects": [], "files": ["열해석_모델.cas", "열해석_결과정리.xlsx"], "apps": ["해석 프로그램"],
         "domains": [], "cands": [], "hint": "THERM/ANALYSIS/DEV", "regv": ""},
        {"kinds": "메일수신 1·메일발신 1·문서 1", "subjects": ["8월 [금액] 정산 품의 요청"], "files": ["정산내역.xlsx"],
         "apps": ["엑셀"], "domains": ["사내"], "cands": [["P-9904", 0.55]], "hint": "ETC/ADMIN/OFFICE", "regv": ""},
    ]
    return [K.wi(f"grp:{i:012x}", f) for i, f in enumerate(rows)]


def sample_batches() -> dict:
    wi = K.wi
    return {
        "lookup_mail": [wi("lookup_mail:2026-09-01:2026-09-07", {"d0": "2026-09-01", "d1": "2026-09-07"})],
        "lookup_teams": [wi("lookup_teams:2026-09-01:2026-09-07", {"d0": "2026-09-01", "d1": "2026-09-07"})],
        "lookup_calendar": [wi("lookup_calendar:2026-09-01:2026-09-02", {"d0": "2026-09-01", "d1": "2026-09-02"})],
        "speech_act": [wi("msg:1", {"ch": "teams", "dir": "in", "chat": "1:1", "prev": "-",
                                    "text": "[과제:P-0012] 도면 검토 부탁드립니다. 금요일까지요"})],
        "taxonomy_bootstrap": [wi("grp:1", {"dom": "DEV", "title": "공차해석", "files": ["공차해석_v3.xlsx"],
                                            "subject": "[과제:P-0007] 공차 해석 결과 공유", "peer": "[고객사:C01]"}),
                               wi("grp:2", {"dom": "-", "title": "해석 프로그램 작업", "files": [], "subject": "",
                                            "peer": ""})],
        "taxonomy_consolidate": [wi("cs:1", {"name": "방열 모듈", "dom": "DEV", "match": ["방열", "열해석"]}),
                                 wi("cs:2", {"name": "방열모듈 개발", "dom": "DEV", "match": ["방열"]})],
        "task_label": task_items(),
        "workflow_label": [wi("ws:r_1a2b3c", {"project": "P-0012", "field": "OPT", "func": "ANALYSIS",
                                              "steps": [["S1", "REQ_IN", 12], ["S2", "APP_CAE", 30]],
                                              "trans": [["S1", "S2", 10]], "tasks": ["광학 모듈 공차 해석"]})],
        "agentic_match": [wi("ag:DOC_XLS", {"type": "DOC_XLS", "label": "결과 정리", "freq": "주 3회 이상",
                                            "io": "디지털 입력·정형 출력", "apps": "표 계산", "ws": ["P-0012 해석·분석"]})],
        "subagent_review": [wi("sa:r_1a2b3c", {"project": "P-0012", "role": "해석 담당",
                                               "steps": [["S1", "[고객사:C01] 의뢰 접수", "REQ_IN", "D1 R1 B0 L1 S1 T1"],
                                                         ["S2", "해석 수행", "APP_CAE", "D1 R1 B1 L0 S1 T0"]]})],
        "review_text": [wi("review:month:2026-09", {
            "kind": "month", "period": "2026-09-01~2026-09-30",
            "facts": [["F1", "완료", "[고객사:C01] 견적 대응", "P-0012", "해석·분석"],
                      ["F2", "진행", "[고객사:C01] [금액] 정산 건", "P-0012", "행정·사무"],
                      ["F3", "진행", "시험 지그 설계", "P-0007", "설계"]],
            "peers": [["동료1", 3]], "edges": [["E1", "P-0012", "산출함", "[협력사:V01] 표 계산 문서"]]})],
    }


class TaskLabelParity(unittest.TestCase):
    """H §6.3 실물 = 골든 첫 줄 + 머리말 13줄 + prompt_context + 앞서 쓴 이름 + 열 + 항목 줄 + 답 형식(형식 줄 한 곳만 다름)."""

    def test_same_as_reference_except_flagged_phrase(self):
        g = golden()["task_label"]
        reg = K.reg()
        spec = REGISTRY["task_label"]
        items = task_items()
        got = K.assemble(spec, items, K.ctx_for(spec, reg), context_block=SEEN).text

        def line(n, f):
            c = ", ".join(f"{p} {s:.2f}" for p, s in f["cands"]) or "-"
            return (f"{n} | {f['kinds']} | {' / '.join(f['subjects']) or '-'} | {', '.join(f['files']) or '-'} | "
                    f"{', '.join(f['apps']) or '-'} | {', '.join(f['domains']) or '-'} | {c} | {f['hint']}")
        parts = [g["first"].replace("{rid}", "R7F3QK").replace("{n}", "3")] + list(g["lead"])
        parts += prompt_context(reg, "task_label") + [SEEN, g["cols"]]
        parts += [line(i + 1, it.fields) for i, it in enumerate(items)]
        parts.append(g["foot"].replace("{rid}", "R7F3QK").replace("{n}", "3"))
        want = "\n".join(parts).replace('<새 과제 이름 또는 "">', '<새 과제명 또는 "">')
        self.assertEqual(got, want)


class BootstrapParity(unittest.TestCase):
    def test_header_and_lines_match_reference(self):
        g = golden()["bootstrap"]
        reg = K.reg()
        spec = REGISTRY["taxonomy_bootstrap"]
        batch = sample_batches()["taxonomy_bootstrap"]
        got = K.assemble(spec, batch, K.ctx_for(spec, reg)).text.split("\n[답 형식]")[0]
        lead = [x.replace("파일 이름 조각·코드 모듈 이름", "파일명 조각·코드 모듈명").replace("도구 이름 하나로", "도구명 하나로")
                .replace("이름 하나로 씁니다", "한 가지 표기로 씁니다") for x in g["lead"]]
        want = "\n".join([g["first"].replace("{rid}", "R7F3QK").replace("{n}", "2")] + lead
                         + prompt_context(reg, "taxonomy_bootstrap") + [g["cols"],
                         "1 | DEV | 공차해석 | 공차해석_v3.xlsx | [과제:P-0007] 공차 해석 결과 공유 | [고객사:C01]",
                         "2 | - | 해석 프로그램 작업 | - | - | -"])
        self.assertEqual(got, want)
        fmt = g["foot"].split("- 형식(<…> 자리에 실제 값): ")[1].split("\n")[0]
        self.assertEqual(spec.format_line(), fmt)


class PromptGate(unittest.TestCase):
    """11종 × 웹 노출 여부 — ① 항목 게이트(+ 엄격 규칙) 뒤 조립한 프롬프트가 ② 게이트(scan 0 · S5 잔여 0)를 통과한다."""

    def test_all_stages_pass_prompt_gate(self):
        reg = K.reg()
        batches = sample_batches()
        base = K.gate_base()
        for sid, spec in REGISTRY.items():
            for web in (False, True):
                with self.subTest(stage=sid, web=web):
                    sg = base.for_stage(sid, web_exposed=web)
                    kept, dropped = sg.items(spec, batches[sid])
                    if not kept:
                        continue
                    text = K.assemble(spec, kept, K.ctx_for(spec, reg, web=web)).text
                    ok, counts = sg.prompt(text)
                    self.assertTrue(ok, counts)
                    if web:
                        for frag in ("[고객사:", "[협력사:", "[사람#"):
                            self.assertNotIn(frag, text)

    def test_T_H17_domains_dash_when_web_exposed(self):
        spec = REGISTRY["task_label"]
        r = Rig(stages=[spec], env=K.exposed_env(), registry=K.reg())
        self.addCleanup(r.cleanup)
        r.write_ai_in("task_label", [{"key": it.key, "fields": it.fields, "rule": {}} for it in task_items()[:1]])
        res = r.run()["task_label"]
        self.assertEqual(res["gate"]["web"]["field_drop"], {"domains": 1})
        line = next(x for x in r.transport.sent_texts[0].splitlines() if x.startswith("1 | "))
        self.assertEqual(line.split(" | ")[5], "-")
        self.assertNotIn("[고객사", r.transport.sent_texts[0])


class NestedTextWebRules(unittest.TestCase):
    def test_review_text_facts_and_edges(self):
        spec = REGISTRY["review_text"]
        batch = sample_batches()["review_text"]
        web = K.assemble(spec, batch, K.ctx_for(spec, K.reg(), web=True)).text
        self.assertIn("F1 | 완료 | [고객사] 견적 대응 | P-0012", web)            # S1
        self.assertIn("F2 | 진행 | - | P-0012", web)                             # S3 금액 + 고객사 → 글 비움
        self.assertIn("E1 P-0012 —산출함→ [협력사] 표 계산 문서", web)
        self.assertNotIn("[고객사:", web)
        plain = K.assemble(spec, batch, K.ctx_for(spec, K.reg(), web=False)).text
        self.assertIn("F1 | 완료 | [고객사:C01] 견적 대응", plain)
        self.assertIn("[함께 한 동료] 동료1 — 함께 한 단위업무 3건", plain)
        self.assertTrue(plain.startswith("[LM27 요청 R7F3QK · 월간 리뷰 문장 · 2026-09-01~2026-09-30]"))
        self.assertIn("\n[항목] 번호 | 기간\n1 | 2026-09-01~2026-09-30\n", plain)

    def test_subagent_labels(self):
        spec = REGISTRY["subagent_review"]
        batch = sample_batches()["subagent_review"]
        self.assertIn("S1 [고객사] 의뢰 접수(REQ_IN)", K.assemble(spec, batch, K.ctx_for(spec, web=True)).text)
        self.assertIn("S1 [고객사:C01] 의뢰 접수(REQ_IN)", K.assemble(spec, batch, K.ctx_for(spec, web=False)).text)
        self.assertIn("T=그 단계에서 쓰는 도구", K.assemble(spec, batch, K.ctx_for(spec)).text)   # B-1 T 플래그 줄


class Agentic(unittest.TestCase):
    def test_X255_code_desc_io_types_only(self):
        spec = REGISTRY["agentic_match"]
        text = K.assemble(spec, sample_batches()["agentic_match"], K.ctx_for(spec, K.reg())).text
        self.assertIn("AG01 · 문서 초안 작성 · 표·메모 → 문서 초안 · DOC_DOC, DOC_PPT", text)
        self.assertIn("AG02 · 표 계산 결과 정리 · 표 → 요약 표 · DOC_XLS", text)
        for leaked in ("문서 초안 도우미", "표 정리 도우미", "팀 화면 설명", "AG09"):
            self.assertNotIn(leaked, text)
        ctx = K.ctx_for(spec, K.reg())
        self.assertEqual(ctx.codes("catalog"), frozenset({"AG01", "AG02"}))       # 퇴역 코드는 답에서도 무효

    def test_empty_catalog(self):
        spec = REGISTRY["agentic_match"]
        text = K.assemble(spec, sample_batches()["agentic_match"], K.ctx_for(spec, K.DICT_REG)).text
        self.assertIn("[에이전트 목록] 코드 · 설명 · 입력 → 출력 · 적용 단계 유형\n(없음)", text)


class Compact(unittest.TestCase):
    def test_compact_header_bound_and_batch_codes(self):
        reg = K.reg(K.big_team(150))
        spec = REGISTRY["task_label"]
        ctx = K.ctx_for(spec, reg)
        spec.title_line("RZZZZZ", 1, [], ctx)
        bound = len(spec.header(ctx, compact=True))
        batch = [K.wi(f"grp:{i}", {"kinds": "문서 1", "subjects": [], "files": [], "apps": [], "domains": [],
                                   "cands": [[f"P-{i * 7 % 150 + 1:04d}", 0.5], ["P-0003", 0.2]], "hint": "ETC/ETC/OFFICE",
                                   "regv": ""}) for i in range(40)]
        spec.title_line("RZZZZZ", 40, batch, ctx)
        h = spec.header(ctx, compact=True)
        self.assertLessEqual(len(h), bound)
        self.assertIn("(목록은 이번 항목의 후보만 보입니다. 맞는 것이 없으면 NONE 또는 P-99 코드)", h)
        self.assertIn("P-0003 · ", h)
        self.assertIn("P-9905 · AX · ", h)
        listed = [x for x in h.splitlines() if x.startswith("P-0")]
        self.assertLessEqual(len(listed), 20)
        self.assertGreater(len(spec.header(ctx, compact=False)), len(h))

    def test_G_H9_all_batches_within_input_budget(self):
        spec = REGISTRY["task_label"]
        reg = K.reg(K.big_team(150))
        rows = [{"key": f"grp:{i:04d}", "fields": {
            "kinds": "메일수신 2·메일발신 3·팀즈 3·문서 2", "subjects": [f"공차 해석 결과 공유 {i}", "RE: 공차 해석 조건 확인 요청"],
            "files": ["공차해석_v3.xlsx", "브라켓_조립도.pdf"], "apps": ["해석 프로그램", "엑셀"], "domains": ["사내"],
            "cands": [[f"P-{i % 150 + 1:04d}", 0.62], [f"P-{(i * 3) % 150 + 1:04d}", 0.21]], "hint": "OPT/ANALYSIS/DEV",
            "regv": ""}} for i in range(60)]
        r = Rig(stages=[spec], registry=reg)
        self.addCleanup(r.cleanup)
        r.write_ai_in("task_label", rows)
        res = r.run()["task_label"]
        self.assertEqual(res["state"], "done")
        self.assertEqual(res["items_ai"], 60)
        self.assertTrue(r.transport.sent_texts)
        for t in r.transport.sent_texts:
            self.assertLessEqual(len(t), r.cfg.input_max_chars)
        self.assertTrue(any("(목록은 이번 항목의 후보만 보입니다." in t for t in r.transport.sent_texts))


if __name__ == "__main__":
    unittest.main()
