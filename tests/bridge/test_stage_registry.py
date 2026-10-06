# -*- coding: utf-8 -*-
"""WP-25 단계 등록부 — G-B4(REGISTRY 11종 완결성 — prompt_ver·item_schema·format_line <요청번호>·폴백(조회 제외)·스텁 고정 답,
머리말에 메일 주소·IPv4·코드네임 사전 단어 0) · G-B8(보낼 필드·프롬프트에 시간 정보 0) · L-30(stages import 무부작용 —
세션 없이 fallback) · R §4.10.3 · RPT-29(보고서 폴백 한 벌 = 단계 fallback 과 바이트 동일) · WP-10 요청(템플릿 상수 이름·
scan 0) · 실행기 resolve_specs 순서."""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from lm27.bridge import runner
from lm27.bridge import settings as S
from lm27.bridge.stages import REGISTRY, STAGE_IDS, build_registry, get
from lm27.bridge.stages import base as B
from lm27.privacy import scan

from tests.fixtures.wp25 import kit as K

ROOT = Path(__file__).resolve().parents[2]
STAGES_DIR = ROOT / "lm27" / "bridge" / "stages"
WP25_MODULES = ("__init__", "lookup", "speech_act", "task_label", "taxonomy_bootstrap", "taxonomy_consolidate",
                "workflow_label", "review_text", "agentic_match", "subagent_review")
L30_PROBE = r'''
import os, sys
sys.path.insert(0, ROOT)
BAD = {"subprocess.Popen", "os.system", "os.startfile", "socket.connect", "socket.bind", "os.mkdir", "os.rename",
       "os.remove", "os.rmdir", "shutil.rmtree", "shutil.move", "winreg.SetValue"}
W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
def hook(ev, args):
    if ev == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and isinstance(flags, int)
                                                                          and flags & W):
            raise RuntimeError("부작용: 파일 쓰기")
    elif ev in BAD or ev.startswith("winreg.Set") or ev.startswith("winreg.Create"):
        raise RuntimeError("부작용: " + ev)
sys.addaudithook(hook)
import importlib
for m in MODS:
    importlib.import_module(m)
from types import SimpleNamespace
pkg = importlib.import_module("lm27.bridge.stages")
reg = pkg.REGISTRY
item = {"key": "k", "fields": {"steps": [["S1", "REQ_IN", 3]], "facts": [["F1", "완료", "공차 해석", "P-0012", "해석"]],
        "type": "DOC_XLS", "kinds": "문서 1"}, "rule": {"act": "request"}}
ns = SimpleNamespace(registry=None, catalog=[], agents=[], cfg=None, stage="x")
for sid, spec in reg.items():
    spec.fallback(dict(item), ns, why="no_ai_out")
print("ok", len(reg))
'''


def _ctx(spec, registry=None):
    return K.ctx_for(spec, registry if registry is not None else K.DICT_REG)


class Registry(unittest.TestCase):
    def test_eleven_stages_in_call_order(self):
        self.assertIsInstance(REGISTRY, dict)
        self.assertEqual(list(REGISTRY), list(STAGE_IDS))
        self.assertEqual(len(REGISTRY), 11)
        self.assertEqual(set(REGISTRY), set(S.STAGE_IDS))           # 설정 bridge.stages 표와 같은 11종(계약 §2.12)
        for sid, spec in REGISTRY.items():
            self.assertIsInstance(spec, B.StageSpec)
            self.assertEqual(spec.id, sid)
        self.assertLess(STAGE_IDS.index("taxonomy_bootstrap"), STAGE_IDS.index("task_label"))
        self.assertLess(STAGE_IDS.index("workflow_label"), STAGE_IDS.index("agentic_match"))
        self.assertIs(get("task_label"), REGISTRY["task_label"])

    def test_build_registry_fresh_instances(self):
        a, b = build_registry(), build_registry()
        self.assertEqual(list(a), list(b))
        self.assertIsNot(a["task_label"], b["task_label"])

    def test_runner_resolves_registry(self):
        specs = runner.resolve_specs(None)
        self.assertEqual([s.id for s in specs], list(STAGE_IDS))
        self.assertEqual([s.id for s in runner.resolve_specs(["review_text", "lookup_mail"])],
                         ["review_text", "lookup_mail"])
        with self.assertRaises(LookupError):
            runner.resolve_specs(["nope"])

    def test_prompt_versions(self):
        self.assertEqual(REGISTRY["task_label"].prompt_ver, "task_label/1.1")         # H §6 내용 정본(X-250)
        self.assertEqual(REGISTRY["subagent_review"].prompt_ver, "subagent_review/1.1")   # R B-1(T 플래그)
        self.assertEqual(REGISTRY["taxonomy_bootstrap"].prompt_ver, "taxonomy_bootstrap/1.0")
        self.assertEqual(REGISTRY["taxonomy_consolidate"].prompt_ver, "taxonomy_consolidate/1.0")
        self.assertEqual(REGISTRY["review_text"].kind, "single")
        self.assertEqual({s.kind for s in REGISTRY.values() if s.id.startswith("lookup_")}, {"lookup"})


class Completeness(unittest.TestCase):
    """G-B4 · G-B8 — 단계 11종 모두(시험 레지스트리 두 모양: 시험용 dict · 유효 레지스트리)."""

    def test_G_B4_dict_registry(self):
        words = ["PROJ-A"] + K.forbidden_words()
        for sid, spec in REGISTRY.items():
            probs = B.check_stage(spec, _ctx(spec), codename_words=words)
            self.assertEqual(probs, [], sid if not any("코드네임" in p for p in probs) else f"{sid}: 코드네임 사전 단어")

    def test_G_B4_effective_registry(self):
        reg = K.reg()
        words = [w for p in reg.projects.values() for w in (*p.codenames, *p.aliases)] + K.forbidden_words()
        for sid, spec in REGISTRY.items():
            probs = B.check_stage(spec, _ctx(spec, reg), codename_words=words)
            self.assertEqual(probs, [], sid if not any("코드네임" in p for p in probs) else f"{sid}: 코드네임 사전 단어")

    def test_fallback_except_lookup(self):
        for sid, spec in REGISTRY.items():
            fb = spec.fallback(K.wi("k", {}), _ctx(spec), "ai_failed")
            if spec.kind == "lookup":
                self.assertIsNone(fb, sid)                          # 조회는 규칙으로 대신할 수 없다(B §8.1)
            else:
                self.assertIsInstance(fb, dict, sid)
            self.assertIsInstance(spec.stub_answer(), dict, sid)
            self.assertIn("<요청번호>", spec.format_line(), sid)

    def test_G_B8_send_fields_and_prompts(self):
        for sid, spec in REGISTRY.items():
            for f in spec.send_fields:
                self.assertIsNone(B.SEND_TIME_KEY_RX.search(f), (sid, f))
            for t in (spec.header(_ctx(spec), False), spec.header(_ctx(spec), True), spec.format_line(),
                      spec.unknown_rule(), spec.columns()):
                self.assertIsNone(B.TIME_TEXT_RX.search(t), sid)


class SideEffects(unittest.TestCase):
    def test_L30_import_and_fallback_without_session(self):
        mods = ["lm27.bridge.stages"] + [f"lm27.bridge.stages.{m}" for m in WP25_MODULES if m != "__init__"]
        code = L30_PROBE.replace("ROOT", repr(str(ROOT)), 1).replace("MODS", repr(mods))
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code], capture_output=True, text=True,
                           encoding="utf-8", timeout=180)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok 11"), r.stderr[-600:])

    def test_package_init_has_no_top_level_submodule_import(self):
        tree = ast.parse((STAGES_DIR / "__init__.py").read_text(encoding="utf-8"))
        for n in tree.body:
            if isinstance(n, ast.ImportFrom):
                self.assertFalse((n.module or "").startswith("lm27"), n.module)
            if isinstance(n, ast.Import):
                self.assertFalse(any(a.name.startswith("lm27") for a in n.names))

    def test_stage_modules_do_not_import_privacy(self):
        """정제 관문을 import 하는 브리지 파일은 gate.py 하나(B §9) — 단계 모듈은 gate 를 함수 안에서만 빌린다."""
        for m in WP25_MODULES:
            tree = ast.parse((STAGES_DIR / f"{m}.py").read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    names = [n.module]
                self.assertFalse(any(x.startswith("lm27.privacy") for x in names), m)


class Templates(unittest.TestCase):
    """WP-10 요청: 프롬프트 상수는 최상위 대문자 이름에 TEMPLATE·PROMPT — 정제 selftest '템플릿' 절이 scan 0 을 본다."""

    def test_selftest_template_section_passes(self):
        from lm27.privacy import selftest
        sec = selftest._sec_template()
        self.assertEqual(sec.state, "pass", sec.failed[:5])
        self.assertGreater(sec.total, 100)

    def test_each_module_has_templates(self):
        import importlib
        for m in WP25_MODULES[1:]:
            mod = importlib.import_module(f"lm27.bridge.stages.{m}")
            names = [a for a in vars(mod) if a.isupper() and selftest_name(a)]
            self.assertTrue(names, m)
            for a in names:
                for txt in _strings(getattr(mod, a)):
                    self.assertEqual(scan(txt), [], f"{m}.{a}")


def selftest_name(attr: str) -> bool:
    from lm27.privacy.selftest import TEMPLATE_NAME
    return bool(TEMPLATE_NAME.search(attr))


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _strings(x)


class ReportFallback(unittest.TestCase):
    """R §4.10.3 · RPT-29 — 보고서는 ``REGISTRY[stage].fallback(item, ctx, why="no_ai_out")`` 한 벌(ai_in 행 dict ·
    SimpleNamespace 문맥)을 부르고, 결과 문장은 단계 fallback 과 바이트가 같다."""

    ITEMS = {
        "workflow_label": {"key": "ws:r_1a2b3c", "fields": {"project": "P-0012", "field": "OPT", "func": "ANALYSIS",
                                                            "steps": [["S1", "REQ_IN", 4], ["S2", "APP_CAE", 9]],
                                                            "trans": [["S1", "S2", 3]], "tasks": ["공차 해석"]},
                           "rule": {"func_name": "해석·분석", "step_names": {"S1": "의뢰 수신", "S2": "해석 프로그램"}}},
        "agentic_match": {"key": "ag:DOC_XLS", "fields": {"type": "DOC_XLS", "label": "결과 정리", "freq": "주 1~2회",
                                                          "io": "디지털 입력·정형 출력", "apps": "표 계산", "ws": []},
                          "rule": {"catalog": ["AG01", "AG02"]}},
        "subagent_review": {"key": "sa:r_1a2b3c", "fields": {"project": "P-0012", "role": "해석 담당",
                                                             "steps": [["S1", "의뢰 접수", "REQ_IN", "D1 R1 B1 L1 S1 T1"],
                                                                       ["S2", "해석 수행", "APP_CAE", "D1 R1 B0 L0 S0 T0"]]}},
        "review_text": {"key": "review:week:2026-W40", "fields": {
            "kind": "week", "period": "2026-09-28~2026-10-04",
            "facts": [["F1", "완료", "공차 해석", "P-0012", "해석·분석"], ["F2", "진행", "지그 설계", "P-0012", "설계"]],
            "peers": [["동료1", 2]]}, "rule": {"peers_map": {"동료1": "w" + "0" * 16}}},
    }

    def test_bridge_fallback_bytes_equal(self):
        from lm27.report.analysis.ai_items import bridge_fallback
        catalog = [{"id": "AG02", "name": "표 정리 도우미", "step_types": ["DOC_XLS"]}]
        ns = SimpleNamespace(registry=None, agents=catalog, catalog=catalog, cfg=None, stage="")
        for sid, item in self.ITEMS.items():
            got = bridge_fallback(sid, item, ns)
            want = REGISTRY[sid].fallback(dict(item), ns, why="no_ai_out")
            self.assertEqual(got, want, sid)
            self.assertTrue(got, sid)
        wf = REGISTRY["workflow_label"].fallback(self.ITEMS["workflow_label"], ns, "no_ai_out")
        self.assertEqual(wf["summary"], "해석·분석 업무가 의뢰 수신에서 시작해 해석 프로그램로 이어집니다.")
        ag = REGISTRY["agentic_match"].fallback(self.ITEMS["agentic_match"], ns, "no_ai_out")
        self.assertEqual(ag, {"m": [{"a": "AG02", "fit": "중", "why": "단계 유형 일치(규칙)"}], "need": None})
        rv = REGISTRY["review_text"].fallback(self.ITEMS["review_text"], ns, "no_ai_out")
        self.assertEqual(rv["summary"], "이번 주에는 1건을 마쳤고 1건을 진행했습니다. 주요 과제는 P-0012입니다.")
        self.assertEqual(rv["peers_map"], {"동료1": "w" + "0" * 16})


if __name__ == "__main__":
    unittest.main()
