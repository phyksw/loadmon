# -*- coding: utf-8 -*-
r"""W2 검토 L12 회귀 — setUpClass 가 %TEMP% 임시 ROOT(lm27t_wp31_*·lm27t_wp32_*)를 만든 뒤 실패하면 tearDownClass 가 불리지
않아 폴더가 남던 것. 임시 ROOT 를 만드는 setUpClass 는 만들자마자 ``addClassCleanup`` 으로 지우기를 건다(실패해도 불린다).

- 동작: 일부러 실패하는 setUpClass 를 돌려 임시 ROOT 가 지워지는지 본다.
- 규칙(정적): tests\report·tests\pipeline 에서 임시 ROOT 를 만드는 setUpClass 는 모두 addClassCleanup 을 쓴다.
"""
from __future__ import annotations

import ast
import io
import os
import unittest
from pathlib import Path

from tests.fixtures.wp31 import runs as R

HERE = Path(__file__).resolve().parent
AREAS = (HERE, HERE.parent / "pipeline")
MAKERS = ("TmpRoot(", "W.World()", "World()", "W.World(prefix")      # wp31 임시 ROOT · wp32 세계(둘 다 mkdtemp)


class ClassCleanupTest(unittest.TestCase):
    def test_failed_setupclass_removes_root(self):
        made = []

        class FailingSetup(unittest.TestCase):       # 안에서 정의 — 발견 대상이 아니다
            @classmethod
            def setUpClass(cls):
                cls.t = R.TmpRoot(prefix="lm27t_l12_")
                made.append(cls.t.root)
                cls.addClassCleanup(cls.t.cleanup)
                raise RuntimeError("일부러 실패")

            def test_never_runs(self):
                raise AssertionError("setUpClass 가 실패해 돌지 않는다")
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FailingSetup)
        res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertEqual(len(res.errors), 1)                       # setUpClass 실패가 보고된다
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))                  # 그래도 임시 ROOT 는 지워졌다

    def test_rule_setupclass_uses_class_cleanup(self):
        bad = []
        for area in AREAS:
            for p in sorted(area.glob("test*.py")):
                src = p.read_text(encoding="utf-8")
                for node in ast.walk(ast.parse(src)):
                    if isinstance(node, ast.FunctionDef) and node.name == "setUpClass":
                        seg = ast.get_source_segment(src, node) or ""
                        if any(m in seg for m in MAKERS) and "addClassCleanup" not in seg:
                            bad.append(f"{p.parent.name}/{p.name}:{node.lineno}")
        self.assertEqual(bad, [], "임시 ROOT 를 만드는 setUpClass 는 addClassCleanup 으로 지우기를 건다")


if __name__ == "__main__":
    unittest.main()
