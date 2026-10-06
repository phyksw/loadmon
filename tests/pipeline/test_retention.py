# -*- coding: utf-8 -*-
"""WP-32 보관 정리 — report.analysisKeep: 새것 N 개 + current.json 이 가리키는 실행 + 보호 목록만 남긴다(R §5.3.4)."""
import json
import unittest

from lm27.pipeline import retention as RT
from lm27.util import fsx
from tests.fixtures.wp32.world import World


def mk_runs(w: World, n: int, *, day: int = 1) -> list[str]:
    ids = [f"202609{day:02d}-{9 + i // 60:02d}{i % 60:02d}00-{i:04x}" for i in range(n)]
    for rid in ids:
        fsx.atomic_write(w.paths.run_status_file(rid), json.dumps({"run_id": rid}).encode("utf-8"))
    return ids


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.addCleanup(self.w.remove)

    def test_keep_newest(self):
        ids = mk_runs(self.w, 13)
        self.assertEqual(RT.list_runs(self.w.paths), ids)
        gone = RT.prune_analysis(self.w.paths, 10)
        self.assertEqual(gone, ids[:3])
        self.assertEqual(RT.list_runs(self.w.paths), ids[3:])
        self.assertEqual(RT.prune_analysis(self.w.paths, 10), [], "두 번째 정리는 할 일 없음")

    def test_current_and_protect_kept(self):
        ids = mk_runs(self.w, 6)
        fsx.atomic_write(self.w.paths.analysis_current(), json.dumps({"run_id": ids[0]}).encode("utf-8"))
        gone = RT.prune_analysis(self.w.paths, 2, protect=[ids[1]])
        self.assertEqual(gone, ids[2:4])
        self.assertEqual(RT.list_runs(self.w.paths), [ids[0], ids[1], ids[4], ids[5]])

    def test_ignores_foreign_names_and_min_keep(self):
        ids = mk_runs(self.w, 3)
        root = self.w.paths.analysis_current().parent
        (root / "notes").mkdir()
        (root / "20260901-090000-zzzz").mkdir()                      # run_id 모양 아님(16진 아님)
        fsx.atomic_write(root / "20260901-080000-00aa", b"file, not a folder")
        gone = RT.prune_analysis(self.w.paths, 0)                    # 하한 1
        self.assertEqual(gone, ids[:2])
        self.assertTrue((root / "notes").is_dir())
        self.assertTrue((root / "20260901-090000-zzzz").is_dir())
        self.assertTrue((root / "20260901-080000-00aa").is_file())
        self.assertEqual(RT.prune_analysis(self.w.paths, "x"), [])   # 형 오류 = 하한 1

    def test_no_analysis_dir(self):
        self.assertEqual(RT.list_runs(self.w.paths), [])
        self.assertEqual(RT.prune_analysis(self.w.paths, 10), [])

    def test_keep_of(self):
        self.assertEqual(RT.keep_of(self.w.cfg()), 10, "레지스트리 기본값")
        self.assertEqual(RT.keep_of(self.w.cfg({"report.analysisKeep": 3})), 3)
        self.assertEqual(RT.keep_of({"report.analysisKeep": 0}), 1)


if __name__ == "__main__":
    unittest.main()
