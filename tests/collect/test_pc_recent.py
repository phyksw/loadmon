# -*- coding: utf-8 -*-
"""WP-14 pc.recent 수집기 시험 — collect\\Get-RecentFiles.ps1 을 합성 Recent 폴더(-RecentDir)와 reg 재생(-MruRegFile — 정책 값)으로만
돌린다(실제 Recent·레지스트리를 읽지 않는다).

CP §5.4 · §12.1(R-RECENTPOLICY · R-MRUEMPTY) · op(open·modify) · 커서·rc 4 · 자기 제외(X-316) · P-T31.
"""
import os
import unittest
from datetime import UTC, datetime

from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import FORBIDDEN_RAW, run_ps, snapshot
from tests.fixtures.wp14.shell_files import write_lnk

SCRIPT = "Get-RecentFiles.ps1"
RAW_KEYS = {"path", "op", "size", "target_mtime", "pdf_sibling", "folder_role", "root_id", "ts_utc", "ts_local_offset",
            "ts_precision", "observed_at", "confidence", "flags"}
NOW = "2026-09-30 12:00"
POLICY = "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def policy_reg(path, **vals):
    lines = ["Windows Registry Editor Version 5.00", "", f"[{POLICY}]"]
    lines += [f'"{k}"=dword:{v:08x}' for k, v in vals.items()]
    path.write_bytes(b"\xff\xfe" + ("\r\n".join(lines) + "\r\n").encode("utf-16-le"))
    return path


class RecentTest(CloneTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        b = cls.clone.temp / "wp14_recent"
        cls.base = b
        docs = b / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        edited = docs / "회의록_과제A.docx"
        viewed = docs / "사양서_과제B.pdf"
        edited.write_bytes(b"x" * 10)
        viewed.write_bytes(b"x" * 20)
        os.utime(edited, (datetime(2026, 9, 10, 1, 0, tzinfo=UTC).timestamp(),) * 2)
        os.utime(viewed, (datetime(2026, 8, 1, 1, 0, tzinfo=UTC).timestamp(),) * 2)
        prog = b / "prog"
        (prog / "data").mkdir(parents=True, exist_ok=True)
        (prog / "data" / "bundle.json").write_bytes(b"{}")
        (prog / "out").mkdir(parents=True, exist_ok=True)
        selfdoc = prog / "out" / "보고서.docx"
        selfdoc.write_bytes(b"x")
        rec = b / "Recent"
        cls.recent = rec
        write_lnk(rec / "회의록_과제A.docx.lnk", str(edited), mtime=datetime(2026, 9, 10, 1, 1, tzinfo=UTC))
        write_lnk(rec / "사양서_과제B.pdf.lnk", str(viewed), mtime=datetime(2026, 9, 11, 2, 0, tzinfo=UTC))
        write_lnk(rec / "지운파일.xlsx.lnk", str(docs / "지운파일.xlsx"), mtime=datetime(2026, 9, 12, 2, 0, tzinfo=UTC))
        write_lnk(rec / "docs.lnk", str(docs), mtime=datetime(2026, 9, 12, 3, 0, tzinfo=UTC))            # 폴더
        write_lnk(rec / "보고서.docx.lnk", str(selfdoc), mtime=datetime(2026, 9, 12, 4, 0, tzinfo=UTC))  # 자기 출력
        write_lnk(rec / "옛날.docx.lnk", str(edited), mtime=datetime(2026, 5, 1, 1, 0, tzinfo=UTC))      # 기간 밖
        (rec / "깨진.lnk").write_bytes(b"garbage")
        os.utime(rec / "깨진.lnk", (datetime(2026, 9, 12, 5, 0, tzinfo=UTC).timestamp(),) * 2)
        cls.empty = b / "EmptyRecent"
        cls.empty.mkdir(parents=True, exist_ok=True)
        cls.reg_none = policy_reg(b / "none.reg")
        cls.reg_block = policy_reg(b / "block.reg", NoRecentDocsHistory=1)
        cls.reg_clear = policy_reg(b / "clear.reg", ClearRecentDocsOnExit=1)

    def run_recent(self, recent=None, *, reg=None, cfg=None, cursor=None, since="2026-09-01", until="2026-09-30"):
        args = ["-RecentDir", str(recent or self.recent), "-MruRegFile", str(reg or self.reg_none), "-TestNow", NOW,
                "-Since", since, "-Until", until]
        r = run_ps(self.clone, SCRIPT, args, cfg=cfg if cfg is not None else {}, cursor=cursor)
        self.assertIsNotNone(r.status, r.err())
        self.assertEqual(r.controls[-1].keys(), {"_cursor"})
        for rec in r.records:
            self.assertTrue(set(rec) <= RAW_KEYS, set(rec) - RAW_KEYS)
            self.assertFalse(set(rec) & FORBIDDEN_RAW)
            self.assertEqual(rec["confidence"], 0.8)
        return r

    def test_lnk_targets_and_op(self):
        r = self.run_recent()
        self.assertEqual(r.rc, 0, r.status)
        by = {os.path.basename(x["path"]): x for x in r.records}
        self.assertEqual(sorted(by), sorted(["회의록_과제A.docx", "사양서_과제B.pdf", "지운파일.xlsx"]))
        self.assertEqual(by["회의록_과제A.docx"]["op"], "modify")
        self.assertEqual(by["회의록_과제A.docx"]["size"], 10)
        self.assertEqual(by["회의록_과제A.docx"]["ts_utc"], iso(datetime(2026, 9, 10, 1, 1, tzinfo=UTC)))
        self.assertEqual(by["사양서_과제B.pdf"]["op"], "open")
        self.assertEqual(by["사양서_과제B.pdf"]["target_mtime"], iso(datetime(2026, 8, 1, 1, 0, tzinfo=UTC)))
        self.assertEqual(by["지운파일.xlsx"]["op"], "open")
        self.assertIsNone(by["지운파일.xlsx"]["size"])
        self.assertEqual(r.status["excluded"]["self"], 1)
        self.assertEqual(r.status["lnk"]["found"], 7)
        self.assertEqual(r.status["lnk"]["no_target"], 1)
        self.assertEqual(r.cursor["last_ts_utc"], iso(datetime(2026, 9, 12, 2, 0, tzinfo=UTC)))

    def test_cursor_rc4(self):
        r1 = self.run_recent()
        r2 = self.run_recent(cursor=r1.cursor)
        self.assertEqual((r2.rc, r2.records), (4, []))

    def test_window_earlier_than_read_from_reemits_gap(self):
        """W2 검토 C03(V6): 창이 커서의 read_from 보다 이르면 그 앞쪽을 다시 낸다(이미 낸 뒤쪽은 id 로 흡수)."""
        r1 = self.run_recent(since="2026-09-11")
        self.assertEqual(sorted(os.path.basename(x["path"]) for x in r1.records), ["사양서_과제B.pdf", "지운파일.xlsx"])
        r2 = self.run_recent(cursor=r1.cursor, since="2026-09-01")
        self.assertIn("회의록_과제A.docx", [os.path.basename(x["path"]) for x in r2.records])
        self.assertTrue(r2.status["from_gap"])
        self.assertEqual(r2.cursor["read_from"], iso(datetime(2026, 9, 1).astimezone(UTC)))   # 로컬 9월 1일 0시
        r3 = self.run_recent(cursor=r2.cursor, since="2026-09-01")
        self.assertEqual((r3.rc, r3.records), (4, []))

    def test_extension_filter_from_cfg(self):
        r = self.run_recent(cfg={"pc.watchExtensions": [".pdf"]})
        self.assertEqual([os.path.basename(x["path"]) for x in r.records], ["사양서_과제B.pdf"])

    def test_folder_name_exclusion(self):
        r = self.run_recent(cfg={"pc.excludeFolderNames": ["docs"]})
        self.assertEqual(r.records, [])
        self.assertEqual(r.status["excluded"]["folder_name"], 3)

    def test_policy_blocks_rc3(self):
        r = self.run_recent(reg=self.reg_block)
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.status["reasons"], ["R-RECENTPOLICY"])
        self.assertTrue(r.status["policy"]["no_history"])

    def test_clear_on_exit_only_blocks_when_empty(self):
        self.assertEqual(self.run_recent(reg=self.reg_clear).rc, 0)
        r = self.run_recent(self.empty, reg=self.reg_clear)
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.status["reasons"], ["R-RECENTPOLICY"])

    def test_empty_recent_rc1_mruempty(self):
        r = self.run_recent(self.empty)
        self.assertEqual(r.rc, 1)
        self.assertEqual(r.status["reasons"], ["R-MRUEMPTY"])
        self.assertEqual(r.cursor["last_ts_utc"], None)

    def test_final_name_flag(self):
        rec = self.base / "RecentFinal"
        f = self.base / "docs" / "검토결과_final.xlsx"
        f.write_bytes(b"x")
        write_lnk(rec / "검토결과_final.xlsx.lnk", str(f), mtime=datetime(2026, 9, 20, 1, 0, tzinfo=UTC))
        r = self.run_recent(rec, cfg={"episode.finalWords": ["최종", "final"]})
        self.assertEqual([x["flags"] for x in r.records], [{"final_name": True}])

    def test_no_disk_writes(self):
        before = snapshot(self.base)
        before_lad = snapshot(self.clone.lad)
        self.run_recent()
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(snapshot(self.clone.lad), before_lad)


if __name__ == "__main__":
    unittest.main()
