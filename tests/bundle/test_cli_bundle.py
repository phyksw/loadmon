# -*- coding: utf-8 -*-
"""WP-12 CLI 연결 — %TEMP% 복제 트리에서 `lm27 bundle …` 이 이 WP 의 계약 함수와 rc(계약 §8.3)로 이어지는지.
(이동 준비·소급 가림은 이 PC 식별을 읽으므로 여기서 돌리지 않는다 — test_move·test_merge 가 함수 단위로 본다.)"""
import json
import unittest

from tests.fixtures.tree import CloneTestCase

PC_A = "pc_" + "a" * 16
PC_B = "pc_" + "b" * 16


class BundleCliTest(CloneTestCase):
    def cli(self, *args):
        cp = self.clone.run_cli(*args, timeout=120)
        return cp.returncode, cp.stdout.decode("utf-8", "replace"), cp.stderr.decode("utf-8", "replace")

    def test_status_verify_alias_merge(self):
        rc, out, err = self.cli("bundle", "status")
        self.assertEqual(rc, 4, err)
        self.assertIsNone(json.loads(out)["bundle"])
        rc, _out, err = self.cli("bundle", "verify")
        self.assertEqual(rc, 4, err)
        rc, _out, err = self.cli("bundle", "alias", PC_B, PC_A)
        self.assertEqual(rc, 0, err)
        rc, _out, err = self.cli("bundle", "alias", PC_B, PC_A)
        self.assertEqual(rc, 4, err)
        aliases = json.loads(self.clone.path("data", "pc_aliases.json").read_text(encoding="utf-8"))
        self.assertEqual([(d["pc_id"], d["logical"], d["rule"]) for d in aliases["decisions"]],
                         [(PC_B, PC_A, "manual")])
        rc, _out, err = self.cli("bundle", "unalias", PC_B)
        self.assertEqual(rc, 0, err)
        rc, _out, err = self.cli("bundle", "unalias", PC_B)
        self.assertEqual(rc, 4, err)
        other = self.clone.sandbox / "other_copy"
        other.mkdir(parents=True)
        rc, _out, err = self.cli("bundle", "merge", str(other))
        self.assertEqual(rc, 2, err)
        rc, out, err = self.cli("bundle", "status")
        self.assertEqual(rc, 4, err)


if __name__ == "__main__":
    unittest.main()
