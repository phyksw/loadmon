# -*- coding: utf-8 -*-
"""WP-00 lm27.util.fsx — 원자 쓰기·결정적 gzip·정규 JSON·엄격 읽기·긴 경로(계약 §9.3, TAB §0.3) 시험."""
import contextlib
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from lm27.util import fsx


class FsxCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp00_fsx_")
        self.addCleanup(self._rm)

    def _rm(self):
        shutil.rmtree("\\\\?\\" + os.path.abspath(self.tmp) if os.name == "nt" else self.tmp, True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)


class CanonTest(unittest.TestCase):
    def test_same_object_same_bytes(self):
        a = {"b": [1, 2.5, "한글"], "a": {"z": None, "y": True}}
        b = {"a": {"y": True, "z": None}, "b": [1, 2.5, "한글"]}
        self.assertEqual(fsx.canon_bytes(a), fsx.canon_bytes(b))
        self.assertEqual(fsx.canon_bytes(a), '{"a":{"y":true,"z":null},"b":[1,2.5,"한글"]}'.encode())

    def test_nan_rejected(self):
        for v in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(v=v):
                self.assertRaises(ValueError, fsx.canon_bytes, {"x": v})

    def test_sha256_and_utcnow(self):
        self.assertEqual(fsx.sha256_hex(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(fsx.sha256_hex("abc"), fsx.sha256_hex(b"abc"))
        self.assertRegex(fsx.utcnow_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class GzipTest(unittest.TestCase):
    def test_deterministic_and_headerless(self):
        raw = "\n".join(json.dumps({"i": i, "t": "가나다"}, ensure_ascii=False) for i in range(500)).encode()
        a, b = fsx.gzip_bytes(raw), fsx.gzip_bytes(raw)
        self.assertEqual(a, b)
        self.assertEqual(a[:2], b"\x1f\x8b")
        self.assertEqual(a[3] & 0x08, 0)                 # FNAME 플래그 없음(filename='')
        self.assertEqual(a[4:8], b"\x00\x00\x00\x00")    # MTIME = 0
        self.assertEqual(gzip.decompress(a), raw)

    def test_str_input(self):
        self.assertEqual(gzip.decompress(fsx.gzip_bytes("한")), "한".encode())


class ReadJsonTest(FsxCase):
    def write(self, name, raw: bytes):
        path = self.p(name)
        fsx.atomic_write(path, raw)              # 시험 자료(임시 폴더) — 바이트 그대로
        return path

    def read(self, path, *a, **k):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            v = fsx.read_json(path, *a, **k)
        return v, err.getvalue()

    def test_bom_accepted(self):
        path = self.write("bom.json", b"\xef\xbb\xbf" + '{"a":"한"}'.encode())
        v, err = self.read(path)
        self.assertEqual(v, {"a": "한"})
        self.assertEqual(err, "")

    def test_dup_key_rejected(self):
        path = self.write("dup.json", b'{"a":1,"a":2}')
        v, err = self.read(path, {"d": 1})
        self.assertEqual(v, {"d": 1})
        self.assertIn("dup.json", err)
        self.assertEqual(err.count("\n"), 1)

    def test_nested_dup_key_rejected(self):
        path = self.write("dup2.json", b'{"a":{"b":1,"b":1}}')
        self.assertIsNone(self.read(path)[0])

    def test_nan_infinity_rejected(self):
        for i, body in enumerate((b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}')):
            with self.subTest(body=body):
                v, err = self.read(self.write(f"nan{i}.json", body), "기본")
                self.assertEqual(v, "기본")
                self.assertTrue(err.startswith("[경고]"))

    def test_broken_and_wrong_type(self):
        v, err = self.read(self.write("broken.json", b'{"a":'), None)
        self.assertIsNone(v)
        self.assertIn("broken.json", err)
        v, err = self.read(self.write("list.json", b"[1,2]"))
        self.assertIsNone(v)
        self.assertIn("list", err)
        v, err = self.read(self.write("list2.json", b"[1,2]"), want=list)
        self.assertEqual(v, [1, 2])
        v, _err = self.read(self.write("num.json", b"3"), want=None)
        self.assertEqual(v, 3)
        v, _err = self.read(self.write("bad_utf8.json", b'{"a":"\xff"}'), {})
        self.assertEqual(v, {})

    def test_missing_returns_default_quietly(self):
        v, err = self.read(self.p("없음.json"), {"x": 1})
        self.assertEqual(v, {"x": 1})
        self.assertEqual(err, "")

    def test_loads_strict(self):
        self.assertEqual(fsx.loads_strict("\ufeff[1]"), [1])
        self.assertRaises(ValueError, fsx.loads_strict, b'{"a":1,"a":1}')
        self.assertRaises(TypeError, fsx.loads_strict, 3)

    def test_deep_nesting_is_format_error_not_crash(self):
        """'[' 10\ub9cc \uac1c \u2014 RecursionError \uac00 \uc544\ub2c8\ub77c \ud615\uc2dd \uc624\ub958(\uae30\ubcf8\uac12 + \uacbd\uace0 1\uc904). \ubc16\uc5d0\uc11c \uc628 JSON \ud558\ub098\uac00 \ud638\ucd9c\uc790\ub97c \uc8fd\uc774\uc9c0 \uc54a\ub294\ub2e4."""
        deep = b"[" * 100000 + b"]" * 100000
        self.assertRaises(ValueError, fsx.loads_strict, deep)
        self.assertRaises(ValueError, fsx.loads_strict, '{"a": ' + "[" * 100000 + "]" * 100000 + "}")
        v, err = self.read(self.write("deep.json", deep), {"default": True}, want=None)
        self.assertEqual(v, {"default": True})
        self.assertIn("deep.json", err)
        self.assertEqual(err.count("\n"), 1)


class AtomicWriteTest(FsxCase):
    def test_write_creates_parents_no_part_left(self):
        path = self.p("a", "b", "c.json")
        fsx.atomic_write(path, fsx.canon_bytes({"k": "값"}))
        self.assertEqual(fsx.read_json(path), {"k": "값"})
        fsx.atomic_write(path, b"{}")
        self.assertEqual(fsx.read_bytes(path), b"{}")
        self.assertEqual(sorted(os.listdir(self.p("a", "b"))), ["c.json"])

    def test_str_is_utf8_and_type_checked(self):
        path = self.p("s.txt")
        fsx.atomic_write(path, "한글")
        self.assertEqual(fsx.read_bytes(path), "한글".encode())
        self.assertRaises(TypeError, fsx.atomic_write, path, {"x": 1})

    def test_part_name_pattern(self):
        seen = []
        real = os.replace

        def spy(src, dst):
            seen.append(src)
            return real(src, dst)

        path = self.p("x.json")
        with mock.patch.object(fsx.os, "replace", spy):
            fsx.atomic_write(path, b"1")
        name = os.path.basename(seen[0])
        self.assertRegex(name, rf"^x\.json\.{os.getpid()}\.{threading.get_ident()}\.[0-9a-f]{{4}}\.part$")

    def test_permission_retry_schedule(self):
        path = self.p("r.json")
        sleeps, calls = [], {"n": 0}
        real = os.replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)

        with mock.patch.object(fsx.os, "replace", flaky), mock.patch.object(fsx, "_sleep", sleeps.append):
            fsx.atomic_write(path, b"ok")
        self.assertEqual(sleeps, [0.1, 0.2, 0.4])
        self.assertEqual(fsx.read_bytes(path), b"ok")

    def test_permission_gives_up_and_cleans_part(self):
        path = self.p("g.json")
        sleeps = []

        def always(src, dst):
            raise PermissionError(5, "Access is denied")

        with mock.patch.object(fsx.os, "replace", always), mock.patch.object(fsx, "_sleep", sleeps.append):
            self.assertRaises(PermissionError, fsx.atomic_write, path, b"x")
        self.assertEqual(sleeps, [0.1, 0.2, 0.4, 0.8, 1.6])
        self.assertEqual(os.listdir(self.tmp), [])        # 반쪽 파일·조각 없음

    def test_retry_while_other_process_holds_target(self):
        """다른 프로세스가 대상을 열어 둔 동안 os.replace 가 실패하고, 닫히면 재시도로 성공한다(TAB §0.2 실측)."""
        path = self.p("held.json")
        fsx.atomic_write(path, b"old")
        code = ("import sys,time;f=open(sys.argv[1],'rb');print('open',flush=True);time.sleep(0.6);f.close()")
        holder = subprocess.Popen([sys.executable, "-B", "-c", code, path], stdout=subprocess.PIPE,
                                  creationflags=0x08000000)
        try:
            self.assertEqual(holder.stdout.readline().strip(), b"open")
            sleeps = []
            real_sleep = fsx._sleep

            def rec(w):
                sleeps.append(w)
                real_sleep(w)

            with mock.patch.object(fsx, "_sleep", rec):
                fsx.atomic_write(path, b"new")
        finally:
            holder.wait(timeout=30)
            holder.stdout.close()
        self.assertEqual(fsx.read_bytes(path), b"new")
        self.assertTrue(sleeps, "대상을 쥔 동안 재시도가 있어야 한다")


class AppendTest(FsxCase):
    def test_append_lines(self):
        path = self.p("log", "x.jsonl")
        fsx.append_line(path, '{"a":1}')
        fsx.append_line(path, '{"b":"한"}\n')
        self.assertEqual(fsx.read_bytes(path), '{"a":1}\n{"b":"한"}\n'.encode())

    def test_embedded_newline_rejected(self):
        path = self.p("y.jsonl")
        self.assertRaises(ValueError, fsx.append_line, path, "a\nb")
        self.assertRaises(ValueError, fsx.append_line, path, "a\rb")
        self.assertRaises(TypeError, fsx.append_line, path, b"x")
        self.assertFalse(os.path.exists(path))

    def test_fsync_and_readers_not_blocked(self):
        path = self.p("f.jsonl")
        fsx.append_line(path, '{"a":1}', fsync=True)
        with open(path, "rb") as reader:                 # 읽는 쪽이 열어 둔 채로도 덧붙이기가 된다(공유 모드)
            fsx.append_line(path, '{"b":2}', fsync=True)
            self.assertEqual(reader.read(), b'{"a":1}\n{"b":2}\n')

    def _check_jsonl(self, path, writers, n):
        lines = [x for x in fsx.read_bytes(path).split(b"\n") if x]
        seen = set()
        for x in lines:
            obj = json.loads(x)                           # 깨진(섞인) 줄이 있으면 여기서 실패
            seen.add((obj["w"], obj["i"]))
        self.assertEqual(len(lines), writers * n, "잃어버린·겹친 줄")
        self.assertEqual(seen, {(f"w{k}", i) for k in range(writers) for i in range(n)})

    def test_concurrent_threads_lose_nothing(self):
        path = self.p("t.jsonl")
        n = 1500

        def run(k):
            for i in range(n):
                fsx.append_line(path, json.dumps({"w": f"w{k}", "i": i}))
        ts = [threading.Thread(target=run, args=(k,)) for k in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self._check_jsonl(path, 4, n)

    def test_concurrent_processes_lose_nothing(self):
        """4프로세스 × 1,000줄(긴 한글 줄 포함) — CRT 'a' 모드(끝으로 이동 후 쓰기)는 줄을 잃고 섞었다(실측 8,000→6,300)."""
        path = self.p("p.jsonl")
        root = os.path.dirname(os.path.dirname(os.path.dirname(fsx.__file__)))
        code = ("import json,sys\nsys.path.insert(0, sys.argv[1])\nfrom lm27.util import fsx\n"
                "k, pad = sys.argv[3], int(sys.argv[4])\n"
                "for i in range(1000):\n"
                "    fsx.append_line(sys.argv[2], json.dumps({'w': k, 'i': i, 'p': '가' * (pad if i % 3 == 0 else 3)},"
                " ensure_ascii=False))\n")
        procs = [subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-I", "-c", code, root, path, f"w{k}", "1500"],
                                  creationflags=0x08000000) for k in range(4)]
        for pr in procs:
            self.assertEqual(pr.wait(timeout=120), 0)
        self._check_jsonl(path, 4, 1000)


class LongPathTest(FsxCase):
    def test_longp_rules(self):
        short = "C:\\a\\b.txt"
        self.assertEqual(fsx.longp(short), short)
        long_ = "C:\\" + "\\".join(["d" * 50] * 5) + "\\f.txt"
        self.assertGreaterEqual(len(long_), 240)
        self.assertEqual(fsx.longp(long_), "\\\\?\\" + long_)
        unc = "\\\\server\\share\\" + "\\".join(["d" * 50] * 5)
        self.assertEqual(fsx.longp(unc), "\\\\?\\UNC\\server\\share\\" + "\\".join(["d" * 50] * 5))
        pre = "\\\\?\\C:\\x"
        self.assertEqual(fsx.longp(pre), pre)
        self.assertTrue(os.path.isabs(fsx.longp("rel.txt")))

    def test_write_read_append_beyond_260(self):
        deep = self.p(*(["긴폴더" + "x" * 40] * 6))
        path = os.path.join(deep, "파일.json")
        self.assertGreater(len(os.path.abspath(path)), 260)
        fsx.atomic_write(path, fsx.canon_bytes({"a": 1}))
        self.assertEqual(fsx.read_json(path), {"a": 1})
        fsx.append_line(os.path.join(deep, "로그.jsonl"), "{}")
        self.assertEqual(fsx.read_bytes(os.path.join(deep, "로그.jsonl")), b"{}\n")
        self.assertEqual(fsx.ensure_dir(deep), os.path.abspath(deep))
        self.assertTrue(os.path.isdir(fsx.longp(deep)))


class SourceRuleTest(unittest.TestCase):
    def test_utc_strings_only_from_aware_now(self):
        src = fsx.read_bytes(fsx.__file__).decode("utf-8")
        self.assertNotIn("utcnow()", src)
        self.assertNotIn("zoneinfo", src)
        self.assertIsNone(re.search(r"datetime\.now\(\)", src))


if __name__ == "__main__":
    unittest.main()
