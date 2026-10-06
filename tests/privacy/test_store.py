# -*- coding: utf-8 -*-
"""WP-11 저장 지점 시험 — 봉인 행만(P-T6 · L-11 ③), 쓰기 UTC 날짜 일자 파일·플러시당 gzip 멤버 1개, 완전한 멤버까지만 읽는
커서(TAB-B25), 깨진 멤버·지워진 파일 공백(gap), 감사 평문 흐름, 수집 커서 잠금(X-301 — 스레드·프로세스), 보존·제거(O-16),
쓰기 open 위치(L-07)·봉인 토큰 참조(L-11) AST 검사."""
import ast
import gzip
import os
import subprocess
import sys
import threading
import time
import unittest
from datetime import date

from lm27.privacy import audit as A
from lm27.privacy import records as R
from lm27.store import (
    LockTimeout,
    SegmentWriter,
    file_lock,
    iter_store,
    load_raw_cursor,
    member_bytes,
    prune_store,
    purge_store,
    read_store_since,
    save_raw_cursor,
    store_files,
    write_rows_file,
)
from lm27.util import fsx
from tests.fixtures.wp11 import helpers as H

D1 = "2026-10-05T23:59:59Z"
D2 = "2026-10-06T00:00:01Z"


def _members(data: bytes) -> list:
    """gzip 바이트 → 멤버별 평문 목록."""
    import zlib
    out, pos = [], 0
    while pos < len(data):
        d = zlib.decompressobj(wbits=31)
        out.append(d.decompress(data[pos:]))
        pos = len(data) - len(d.unused_data)
    return out


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.paths = self.sb.paths
        self.rc = self.sb.rc("pc.sampler")

    def rows(self, n: int, start: int = 0, pc_id: str = H.PC1) -> list:
        rc = self.rc if pc_id == H.PC1 else self.sb.rc("pc.sampler", pc_id=pc_id)
        out = []
        for i in range(start, start + n):
            o = R.sanitize_record("pc_session", H.raw_sampler(ts_utc=f"2026-10-05T01:{i % 60:02d}:00Z",
                                                              fg_title=f"보고서_{i}.docx - Word", fg_doc_name=None), rc)
            out.append(o.row)
        return out

    def write(self, rows, clock=D1, pc_id=H.PC1):
        w = SegmentWriter(self.paths, pc_id, "pc_session", "pc.sampler", clock=lambda: clock)
        for r in rows:
            w.append(r)
        w.close()
        return w


class WriterTest(_Base):
    def test_T6_only_sealed_rows(self):
        w = SegmentWriter(self.paths, H.PC1, "pc_session", "pc.sampler")
        row = self.rows(1)[0]
        for bad in (row.to_dict(), {"kind": "pc_session"}, R.SanitizedRow.__new__(R.SanitizedRow), None):
            with self.assertRaises(TypeError):
                w.append(bad)
        ev = SegmentWriter(self.paths, H.PC1, "pc_session", "pc.events")
        with self.assertRaises(ValueError):
            ev.append(row)                                         # 다른 src
        other = SegmentWriter(self.paths, H.PC2, "pc_session", "pc.sampler")
        with self.assertRaises(ValueError):
            other.append(row)                                      # 다른 pc_id
        for args in (("mail", "pc.sampler"), ("nope", "pc.sampler")):
            with self.assertRaises(ValueError):
                SegmentWriter(self.paths, H.PC1, *args)
        with self.assertRaises(ValueError):
            SegmentWriter(self.paths, "PC1", "pc_session", "pc.sampler")
        with self.assertRaises(TypeError):
            write_rows_file(self.sb.dir / "x.jsonl", [row.to_dict()])
        self.assertFalse((self.sb.dir / "x.jsonl").exists())

    def test_member_per_flush_on_write_date(self):
        rows = self.rows(5)
        w = SegmentWriter(self.paths, H.PC1, "pc_session", "pc.sampler", clock=lambda: D1)
        self.assertEqual(w.flush(), 0)
        for r in rows[:2]:
            w.append(r)
        self.assertEqual((w.pending, w.flush()), (2, 2))
        for r in rows[2:]:
            w.append(r)
        w.close()
        with self.assertRaises(ValueError):
            w.append(rows[0])
        p = self.paths.store_file(H.PC1, "pc_session", "pc.sampler", "2026-10-05")
        self.assertEqual(w.last_path, p)
        data = p.read_bytes()
        self.assertEqual(data[4:8], b"\x00\x00\x00\x00")         # mtime 0
        self.assertEqual(data[3] & 0x08, 0)                        # 파일 이름 없음
        ms = _members(data)
        self.assertEqual([m.count(b"\n") for m in ms], [2, 3])
        self.assertEqual(gzip.decompress(data), b"".join(fsx.canon_bytes(r.to_dict()) + b"\n" for r in rows))
        self.write(self.rows(1, 9), clock=D2)                      # 이벤트 시각이 아니라 쓰기 날짜(UTC)
        self.assertEqual([d for _r, _p, d in store_files(self.paths, H.PC1, "pc_session", "pc.sampler")],
                         ["20261005", "20261006"])
        self.assertEqual(member_bytes(rows), member_bytes(rows))  # 결정적

    def test_exception_discards_batch(self):
        with self.assertRaises(RuntimeError), SegmentWriter(self.paths, H.PC1, "pc_session", "pc.sampler") as w:
            w.append(self.rows(1)[0])
            raise RuntimeError("x")
        self.assertEqual(store_files(self.paths, H.PC1, "pc_session", "pc.sampler"), [])

    def test_write_rows_file(self):
        rows = self.rows(3)
        gz, plain = self.sb.dir / "out" / "a.jsonl.gz", self.sb.dir / "out" / "a.jsonl"
        sha = write_rows_file(gz, rows)
        import hashlib
        self.assertEqual(sha, hashlib.sha256(gz.read_bytes()).hexdigest())
        self.assertEqual(gzip.decompress(gz.read_bytes()).count(b"\n"), 3)
        write_rows_file(plain, rows)
        self.assertEqual(plain.read_bytes(), b"".join(fsx.canon_bytes(r.to_dict()) + b"\n" for r in rows))
        self.assertEqual([p.name for p in (self.sb.dir / "out").iterdir() if p.name.endswith(".part")], [])


class ReaderTest(_Base):
    def test_cursor_chain_in_write_order(self):
        self.write(self.rows(2), D1)
        self.write(self.rows(3, 2), D1)
        recs, cur, gap = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", None)
        self.assertEqual((len(recs), gap), (5, None))
        f = self.paths.store_file(H.PC1, "pc_session", "pc.sampler", "2026-10-05")
        self.assertEqual(cur["file"], f"{H.PC1}/evidence/pc_session/pc.sampler/202610/20261005.jsonl.gz")
        self.assertEqual(cur["offset"], f.stat().st_size)
        self.assertEqual(cur["last_ts"], "2026-10-05T01:04:00Z")
        again, cur2, _ = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", cur)
        self.assertEqual((again, cur2), ([], cur))
        self.write(self.rows(1, 7), D2)
        new, cur3, _ = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", cur)
        self.assertEqual([r["ts_utc"] for r in new], ["2026-10-05T01:07:00Z"])
        self.assertTrue(cur3["file"].endswith("202610/20261006.jsonl.gz"))
        self.assertEqual(read_store_since(self.paths, H.PC2, "pc_session", "pc.sampler", None), ([], None, None))

    def test_TAB_B25_truncated_tail(self):
        """완전한 gzip 멤버까지만 — 쓰는 중(잘린) 멤버는 읽지 않고 오프셋을 그 앞에 둔다. 다 쓰이면 다음 읽기가 받는다."""
        self.write(self.rows(2), D1)
        self.write(self.rows(2, 2), D1)
        f = self.paths.store_file(H.PC1, "pc_session", "pc.sampler", "2026-10-05")
        full = f.stat().st_size
        third = member_bytes(self.rows(3, 4))
        with open(f, "ab") as fh:                                  # 시험 전용: 플러시 도중 상태를 흉내
            fh.write(third[: len(third) // 2])
        recs, cur, gap = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", None)
        self.assertEqual((len(recs), cur["offset"], gap), (4, full, None))
        with open(f, "ab") as fh:
            fh.write(third[len(third) // 2:])
        more, cur2, gap2 = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", cur)
        self.assertEqual((len(more), cur2["offset"], gap2), (3, f.stat().st_size, None))
        self.assertEqual(len(list(iter_store(self.paths, H.PC1, "pc_session", "pc.sampler"))), 7)

    def test_corrupt_member_skipped_with_gap(self):
        self.write(self.rows(2), D1)
        f = self.paths.store_file(H.PC1, "pc_session", "pc.sampler", "2026-10-05")
        bad = bytearray(member_bytes(self.rows(1, 5)))
        bad[20:30] = b"\xff" * 10                                  # 압축 본문 훼손
        with open(f, "ab") as fh:
            fh.write(bytes(bad))
        self.write(self.rows(2, 8), D1)
        recs, cur, gap = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", None)
        self.assertEqual(len(recs), 4)
        self.assertEqual(gap["reason"], "store_corrupt")
        self.assertEqual(cur["offset"], f.stat().st_size)

    def test_pruned_cursor_file_gap(self):
        self.write(self.rows(1), D2)
        cur = {"file": f"{H.PC1}/evidence/pc_session/pc.sampler/202610/20261001.jsonl.gz", "offset": 99,
               "last_ts": "2026-10-01T05:00:00Z"}
        recs, new, gap = read_store_since(self.paths, H.PC1, "pc_session", "pc.sampler", cur)
        self.assertEqual(len(recs), 1)
        self.assertEqual(gap, {"from_t": "2026-10-01T05:00:00Z", "to_t": "2026-10-06T00:00:00Z", "reason": "store_pruned"})
        self.assertTrue(new["file"].endswith("20261006.jsonl.gz"))

    def test_audit_stream_complete_lines_only(self):
        for _ in range(2):
            A.AuditSink.open(None, H.PC1, "agent", "pc.sampler", agent_dir=self.paths.agent_dir(),
                             clock=lambda: D1).flush()
        recs, cur, gap = read_store_since(self.paths, H.PC1, "privacy_audit", "agent", None)
        self.assertEqual((len(recs), cur["file"], gap), (2, "privacy_audit/202610/20261005.jsonl", None))
        f = self.paths.privacy_audit_file("2026-10-05")
        with open(f, "ab") as fh:
            fh.write(b'{"ev":"collect_batch"')                    # 쓰는 중인 줄
        recs2, cur2, _ = read_store_since(self.paths, H.PC1, "privacy_audit", "agent", cur)
        self.assertEqual((recs2, cur2["offset"]), ([], cur["offset"]))
        with open(f, "ab") as fh:
            fh.write(b'}\n')
        recs3, _cur3, _ = read_store_since(self.paths, H.PC1, "privacy_audit", "agent", cur2)
        self.assertEqual(recs3, [{"ev": "collect_batch"}])

    def test_iter_store_range(self):
        self.write(self.rows(1), D1)
        self.write(self.rows(2, 1), D2)
        self.assertEqual(len(list(iter_store(self.paths, H.PC1, "pc_session", "pc.sampler", "2026-10-06"))), 2)
        self.assertEqual(len(list(iter_store(self.paths, H.PC1, "pc_session", "pc.sampler", None, date(2026, 10, 5)))), 1)


class RetentionTest(_Base):
    def test_prune_store(self):
        for day in ("2026-08-01T00:00:00Z", "2026-09-04T00:00:00Z", "2026-09-05T00:00:00Z", "2026-10-05T00:00:00Z"):
            self.write(self.rows(1), day)
        n = prune_store(self.paths, H.PC1, 30, today=date(2026, 10, 5))
        self.assertEqual(n, 2)                                     # 30일 전(09-05)보다 이른 파일만
        self.assertEqual([d for _r, _p, d in store_files(self.paths, H.PC1, "pc_session", "pc.sampler")],
                         ["20260905", "20261005"])
        base = self.paths.store_file(H.PC1, "pc_session", "pc.sampler", "2026-10-05").parent.parent
        self.assertEqual(sorted(p.name for p in base.iterdir()), ["202609", "202610"])   # 빈 달 폴더(202608) 정리
        with self.assertRaises(ValueError):
            prune_store(self.paths, H.PC1, 0)

    def test_purge_store_O16(self):
        self.write(self.rows(2), D1)
        self.write(self.rows(1, pc_id=H.PC2), D1, pc_id=H.PC2)
        save_raw_cursor(self.paths, H.PC1, "pc.sampler", {"n": 1})
        A.AuditSink.open(None, H.PC1, "agent", "pc.sampler", agent_dir=self.paths.agent_dir(), clock=lambda: D1).flush()
        holder_in, release = threading.Event(), threading.Event()

        def hold():
            with file_lock(self.paths.raw_cursor_lock(H.PC1)):
                holder_in.set()
                release.wait(5)
        t = threading.Thread(target=hold)
        t.start()
        holder_in.wait(5)
        try:
            with self.assertRaises(LockTimeout):
                purge_store(self.paths, H.PC1, timeout_s=0.2)
            self.assertTrue(self.paths.raw_cursor(H.PC1).is_file())           # 아무것도 지우지 않았다
        finally:
            release.set()
            t.join(5)
        self.assertEqual(purge_store(self.paths, H.PC1), 2)                   # 일자 파일 1 + 커서 1
        self.assertFalse(self.paths.store_dir(H.PC1).exists())
        self.assertTrue(self.paths.store_dir(H.PC2).is_dir())
        self.assertEqual(purge_store(self.paths), 1)
        self.assertTrue(self.paths.privacy_audit_file("2026-10-05").is_file())  # 감사는 audit.purge_audit 몫
        self.assertEqual(purge_store(self.paths), 0)


_SAVE_LOOP = """
import sys
sys.path.insert(0, {root!r})
from lm27.paths import Paths
from lm27.store.cursor import save_raw_cursor
p = Paths({sroot!r}, lad={lad!r})
for i in range({n}):
    save_raw_cursor(p, {pc!r}, {src!r}, {{"n": i, "src": {src!r}}})
"""
_HOLD = """
import sys, time
sys.path.insert(0, {root!r})
from lm27.store.cursor import file_lock
with file_lock({lock!r}):
    print("locked", flush=True)
    time.sleep({sec})
"""


class CursorTest(_Base):
    def _py(self, code: str, **kw):
        env = dict(os.environ, LOCALAPPDATA=str(self.sb.lad), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-c", code], env=env, cwd=str(self.sb.dir),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

    def test_only_that_src(self):
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {})
        save_raw_cursor(self.paths, H.PC1, "mail.com", {"box": {"inbox": {"last_ts_utc": "2026-10-05T00:00:00Z"}}})
        save_raw_cursor(self.paths, H.PC1, "pc.sampler", 5)
        save_raw_cursor(self.paths, H.PC1, "mail.com", {"v": 2})
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"mail.com": {"v": 2}, "pc.sampler": 5})
        for bad in ("mail", "../x", "MAIL.com", ""):
            with self.assertRaises(ValueError):
                save_raw_cursor(self.paths, H.PC1, bad, 1)
        with self.assertRaises(ValueError):
            save_raw_cursor(self.paths, H.PC1, "mail.com", "x" * (5 * 1024 * 1024))
        with self.assertRaises(ValueError):
            save_raw_cursor(self.paths, H.PC1, "mail.com", float("nan"))
        self.assertEqual(load_raw_cursor(self.paths, H.PC1)["mail.com"], {"v": 2})

    def test_X301_threads(self):
        def loop(src):
            for i in range(40):
                save_raw_cursor(self.paths, H.PC1, src, {"n": i})
        ts = [threading.Thread(target=loop, args=(s,)) for s in ("mail.com", "pc.sampler", "teams.uia")]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        self.assertEqual(load_raw_cursor(self.paths, H.PC1),
                         {"mail.com": {"n": 39}, "pc.sampler": {"n": 39}, "teams.uia": {"n": 39}})

    def test_X301_processes(self):
        """에이전트 수확(pc.*)과 전경 수집(mail.*)이 다른 프로세스에서 동시에 저장해도 서로의 커서를 잃지 않는다."""
        procs = [self._py(_SAVE_LOOP.format(root=str(H.REAL_ROOT), sroot=str(self.sb.root), lad=str(self.sb.lad), n=25,
                                            pc=H.PC1, src=s)) for s in ("pc.sampler", "mail.com")]
        for p in procs:
            _out, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err.decode("utf-8", "replace")[-400:])
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"mail.com": {"n": 24, "src": "mail.com"},
                                                               "pc.sampler": {"n": 24, "src": "pc.sampler"}})

    def test_lock_timeout_cross_process(self):
        lock = self.paths.raw_cursor_lock(H.PC1)
        fsx.ensure_dir(lock.parent)
        p = self._py(_HOLD.format(root=str(H.REAL_ROOT), lock=str(lock), sec=3))
        try:
            self.assertEqual(p.stdout.readline().strip(), b"locked")
            t0 = time.monotonic()
            with self.assertRaises(LockTimeout):
                save_raw_cursor(self.paths, H.PC1, "mail.com", 1, timeout_s=0.3)
            self.assertLess(time.monotonic() - t0, 2.5)
        finally:
            p.communicate(timeout=30)
        save_raw_cursor(self.paths, H.PC1, "mail.com", 1, timeout_s=5)
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"mail.com": 1})


class StaticTest(unittest.TestCase):
    """L-07: 쓰기 모드 open 은 store\\writer.py 만(이 WP 의 두 패키지 안) · L-11 ③: ``_SEAL`` 참조는 records.py·writer.py,
    ``SanitizedRow(...)`` 생성은 records.py 만(lm27 전체)."""

    def _files(self, *parts):
        base = H.REAL_ROOT.joinpath("lm27", *parts)
        return sorted(base.rglob("*.py"))

    def test_L07_write_open(self):
        hits = []
        for f in self._files("privacy") + self._files("store"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "open":
                    mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
                    m = mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) else "r"
                    if set(m) & set("wax+"):
                        hits.append(f.relative_to(H.REAL_ROOT).as_posix())
        self.assertEqual(sorted(set(hits)), ["lm27/store/writer.py"])

    def test_L11_seal(self):
        seal, ctor = set(), set()
        for f in self._files():
            tree = ast.parse(f.read_text(encoding="utf-8"))
            rel = f.relative_to(H.REAL_ROOT).as_posix()
            for n in ast.walk(tree):
                if (isinstance(n, ast.Name) and n.id == "_SEAL") or (isinstance(n, ast.Attribute) and n.attr == "_SEAL"):
                    seal.add(rel)
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "SanitizedRow":
                    ctor.add(rel)
        self.assertLessEqual(seal, {"lm27/privacy/records.py", "lm27/store/writer.py"})
        self.assertEqual(ctor, {"lm27/privacy/records.py"})


if __name__ == "__main__":
    unittest.main()
