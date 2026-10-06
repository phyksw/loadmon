# -*- coding: utf-8 -*-
"""WP-14 pc.files 수집기 시험 — collect\\Get-FileActivity.ps1 을 %TEMP% 복제 트리의 합성 폴더에서 시험 주입
(-RecentDir -MruTextDir -NoToolMru -TestNow, 계약 §11.3)으로만 돌린다(실제 Recent·레지스트리·사용자 폴더를 읽지 않는다).

CP §5.1 · 계약 §2.17(자기 제외 X-316) · X-142 · §5.2(pc.* 키를 _in.cfg 로) · §5.3(OOXML 예산) · §8.1 rc · T-10(상한 → partial +
cap_hit) · L-09(디스크 쓰기 0) · P-T31(금지 원시 필드 없음).
"""
import os
import time
import unittest
import zipfile
from datetime import UTC, datetime

from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import FORBIDDEN_RAW, run_ps, snapshot
from tests.fixtures.wp14.shell_files import write_lnk

SCRIPT = "Get-FileActivity.ps1"
RAW_KEYS = {"path", "op", "size", "ooxml_totaltime", "ooxml_revision", "ooxml_last_modified_by", "target_mtime",
            "pdf_sibling", "folder_role", "root_id", "ts_utc", "ts_local_offset", "ts_precision", "observed_at",
            "confidence", "flags"}
EXTS = [".docx", ".xlsx", ".pptx", ".pdf", ".prt", ".cas.gz", ".py", ".hwp"]
NOW = "2026-09-20 12:00"
T0 = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)          # 2026-09-10 10:00 KST


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def put(path, data: bytes = b"x", mtime: datetime | None = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if mtime is not None:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    return path


def put_ooxml(path, *, by="홍길동", rev=7, total=42, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("docProps/core.xml", f"<cp:coreProperties><cp:lastModifiedBy>{by}</cp:lastModifiedBy>"
                                        f"<cp:revision>{rev}</cp:revision></cp:coreProperties>")
        z.writestr("docProps/app.xml", f"<Properties><TotalTime>{total}</TotalTime></Properties>")
    if mtime is not None:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    return path


class FilesTest(CloneTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        b = cls.clone.temp / "wp14_files"
        cls.base = b
        w = b / "work"
        cls.work = w
        put_ooxml(str(w / "과제A" / "설계검토_v2.docx"), mtime=T0)
        put(str(w / "과제A" / "설계검토_v2.pdf"), mtime=datetime(2026, 9, 10, 1, 3, tzinfo=UTC))
        put(str(w / "과제A" / "해석결과.xlsx"), mtime=datetime(2026, 9, 10, 2, 0, tzinfo=UTC))
        put(str(w / "과제A" / "bracket.prt.12"), mtime=datetime(2026, 9, 11, 2, 0, tzinfo=UTC))
        put(str(w / "과제A" / "case1.cas.gz"), mtime=datetime(2026, 9, 11, 3, 0, tzinfo=UTC))
        put(str(w / "과제A" / "~$설계검토_v2.docx"), mtime=T0)
        put(str(w / "과제A" / "사진.jpg"), mtime=T0)
        put(str(w / "과제A" / "옛문서.docx"), mtime=datetime(2025, 1, 2, tzinfo=UTC))
        put(str(w / "build" / "CMakeCache.txt"), mtime=T0)                 # 빌드 표식 → build\ 제외
        put(str(w / "build" / "out.docx"), mtime=T0)
        put(str(w / "Release" / "결과표.xlsx"), mtime=T0)                   # 표식 없는 release\ 는 업무 폴더로 유지
        put(str(w / "node_modules" / "pkg" / "readme.docx"), mtime=T0)      # 이름만으로 확정되는 패키지 폴더
        put(str(w / "제외폴더" / "skip.docx"), mtime=T0)                    # pc.excludeFolderNames
        prog = b / "prog"                                                  # 프로그램 폴더(data\bundle.json) — 자기 제외
        cls.prog = prog
        put(str(prog / "data" / "bundle.json"), b"{}", mtime=T0)
        put(str(prog / "out" / "personal" / "report.docx"), mtime=T0)
        agent = cls.clone.lad / "LoadMonitor27" / "agent"                  # %LOCALAPPDATA%\LoadMonitor27 — 자기 제외
        cls.agent = agent
        put(str(agent / "notes.docx"), mtime=T0)
        # 자동 발견 재료: Recent .lnk 두 개가 가리키는 폴더(auto) · 사적 낱말 폴더(개인) · 텍스트 MRU 폴더(mru)
        auto = b / "auto_dir"
        cls.auto = auto
        put(str(auto / "a1.docx"), mtime=datetime(2026, 9, 12, 1, 0, tzinfo=UTC))
        put(str(auto / "a2.pptx"), mtime=datetime(2026, 9, 12, 1, 5, tzinfo=UTC))
        priv = b / "개인" / "가계부"
        put(str(priv / "p1.xlsx"), mtime=datetime(2026, 9, 12, 1, 0, tzinfo=UTC))
        put(str(priv / "p2.xlsx"), mtime=datetime(2026, 9, 12, 1, 0, tzinfo=UTC))
        rec = b / "recent"
        cls.recent = rec
        rec.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate([auto / "a1.docx", auto / "a2.pptx", priv / "p1.xlsx", priv / "p2.xlsx"]):
            write_lnk(rec / f"{f.name}.lnk", str(f), mtime=datetime(2026, 9, 12, 2, i, tzinfo=UTC))
        mru = b / "mru_dir"
        cls.mru = mru
        put(str(mru / "m1.py"), mtime=datetime(2026, 9, 13, 1, 0, tzinfo=UTC))
        put(str(mru / "m2.py"), mtime=datetime(2026, 9, 13, 1, 1, tzinfo=UTC))
        mtxt = b / "mrutext"
        cls.mrutext = mtxt
        mtxt.mkdir(parents=True, exist_ok=True)
        (mtxt / "tool.xml").write_text(f'<recent><f path="{mru / "m1.py"}"/><f path="{mru / "m2.py"}"/></recent>',
                                       encoding="utf-8")

    def cfg(self, **kw):
        c = {"pc.watchFolders": [str(self.work), str(self.prog), str(self.agent)], "pc.watchExtensions": EXTS,
             "pc.autoDiscoverFolders": False, "pc.excludeFolderNames": ["제외폴더"], "pc.excludePackageDirs": True,
             "pc.files.burstN": 8, "pc.files.budgetSec": 180}
        c.update(kw)
        return c

    def run_files(self, cfg=None, *, cursor=None, extra=(), since="2026-09-01", until="2026-09-20"):
        args = ["-TestNow", NOW, "-Since", since, "-Until", until, "-RecentDir", str(self.recent), "-NoToolMru", *extra]
        r = run_ps(self.clone, SCRIPT, args, cfg=cfg if cfg is not None else self.cfg(), cursor=cursor)
        self.assertIsNotNone(r.status, r.err())
        self.assertEqual(r.controls[-1].keys(), {"_cursor"})
        for rec in r.records:
            self.assertTrue(set(rec) <= RAW_KEYS, set(rec) - RAW_KEYS)
            self.assertFalse(set(rec) & FORBIDDEN_RAW)
            self.assertIn(rec["op"], ("create", "modify"))
            self.assertIn(rec["folder_role"], ("desktop", "documents", "downloads", "onedrive", "sharepoint", "root",
                                               "other"))
            self.assertEqual(rec["ts_precision"], "minute")
            self.assertEqual(rec["confidence"], 1.0)
            self.assertEqual(rec["ts_utc"], rec["target_mtime"])
        return r

    def names(self, r):
        return sorted(os.path.basename(x["path"]) for x in r.records)

    def test_scan_filters_and_fields(self):
        r = self.run_files()
        self.assertEqual(r.rc, 0, r.status)
        self.assertEqual(self.names(r), sorted(["설계검토_v2.docx", "설계검토_v2.pdf", "해석결과.xlsx", "bracket.prt.12",
                                                "case1.cas.gz", "결과표.xlsx"]))
        by = {os.path.basename(x["path"]): x for x in r.records}
        d = by["설계검토_v2.docx"]
        self.assertEqual((d["ooxml_totaltime"], d["ooxml_revision"], d["ooxml_last_modified_by"]), (42, 7, "홍길동"))
        self.assertTrue(d["pdf_sibling"])
        self.assertEqual(d["ts_utc"], iso(T0))
        self.assertEqual(d["root_id"], "R01")
        self.assertEqual(d["folder_role"], "root")
        self.assertEqual(d["op"], "modify")                                   # 만든 시각(지금) ≠ 수정 시각
        self.assertIsNone(by["해석결과.xlsx"]["ooxml_revision"])               # zip 이 아니면 비움(조용히)
        self.assertFalse(by["해석결과.xlsx"]["pdf_sibling"])
        st = r.status
        self.assertEqual(st["excluded"]["self"], 2)                            # 프로그램 폴더 · 에이전트 폴더
        self.assertGreaterEqual(st["excluded"]["package"], 2)                  # build(표식) · node_modules
        self.assertEqual(st["excluded"]["folder_name"], 1)
        self.assertEqual(st["roots"], {"watch": 3, "auto": 0, "missing": 0})
        self.assertEqual(r.cursor["last_ts_utc"], iso(datetime(2026, 9, 11, 3, 0, tzinfo=UTC)))
        ts = [x["ts_utc"] for x in r.records]
        self.assertEqual(ts, sorted(ts))

    def test_create_op_for_new_file(self):
        p = self.base / "fresh" / "새문서.docx"
        put(str(p))
        os.utime(p, None)
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M")
        args = ["-TestNow", now_local, "-RecentDir", str(self.recent), "-NoToolMru"]
        r = run_ps(self.clone, SCRIPT, args, cfg=self.cfg(**{"pc.watchFolders": [str(p.parent)]}))
        self.assertEqual([x["op"] for x in r.records], ["create"])

    def test_cursor_incremental_rc4_then_new(self):
        r1 = self.run_files()
        r2 = self.run_files(cursor=r1.cursor)
        self.assertEqual((r2.rc, r2.records), (4, []))
        self.assertEqual(r2.cursor, r1.cursor)
        p = self.work / "과제A" / "추가.docx"
        put(str(p), mtime=datetime(2026, 9, 15, 1, 0, tzinfo=UTC))
        try:
            r3 = self.run_files(cursor=r1.cursor)
            self.assertEqual(self.names(r3), ["추가.docx"])
            self.assertEqual(r3.rc, 0)
        finally:
            os.remove(p)

    def test_auto_discovery_recent_and_private_candidates(self):
        cfg = self.cfg(**{"pc.watchFolders": [], "pc.autoDiscoverFolders": True,
                          "privacy.path.excludeKeywords": ["개인", "가족", "private"]})
        r = self.run_files(cfg)
        self.assertEqual(self.names(r), ["a1.docx", "a2.pptx"])
        for x in r.records:
            self.assertIsNone(x["root_id"])
        self.assertEqual(r.status["roots"]["auto"], 1)
        self.assertGreaterEqual(r.status["excluded"]["private_candidates"], 2)
        self.assertEqual(r.status["auto_sources"].get("lnk"), 2)

    def test_auto_discovery_mru_text_dir(self):
        cfg = self.cfg(**{"pc.watchFolders": [], "pc.autoDiscoverFolders": True})
        args = ["-TestNow", NOW, "-Since", "2026-09-01", "-Until", "2026-09-20", "-RecentDir", str(self.base / "no_recent"),
                "-MruTextDir", str(self.mrutext)]
        r = run_ps(self.clone, SCRIPT, args, cfg=cfg)
        self.assertEqual(self.names(r), ["m1.py", "m2.py"], r.status)
        self.assertEqual(r.status["auto_sources"].get("test"), 2)

    def test_auto_off_and_no_roots_rc1(self):
        cfg = self.cfg(**{"pc.watchFolders": [str(self.base / "없는폴더"), "C:\\<자리표시자>"]})
        r = self.run_files(cfg)
        self.assertEqual(r.rc, 1)
        self.assertEqual(r.status["roots"]["missing"], 2)
        self.assertEqual(r.records, [])

    def test_burst_cap_partial(self):
        burst = self.base / "burst"
        for i in range(10):
            put(str(burst / f"result_{i:02d}.cas.gz"), mtime=datetime(2026, 9, 14, 1, 0, i, tzinfo=UTC))
        r = self.run_files(self.cfg(**{"pc.watchFolders": [str(burst)], "pc.files.burstN": 1}))
        self.assertEqual(len(r.records), 6)                                     # burstN×5+1
        self.assertTrue(r.status["partial"])
        self.assertTrue(r.status["cap_hit"])
        self.assertIn("R-CAP", r.status["reasons"])
        self.assertEqual(r.status["burst_capped"], 4)
        self.assertEqual(r.rc, 0)

    def test_final_name_flag_from_final_words(self):
        """flags.final_name — 원 이름(확장자 제외)에 episode.finalWords 낱말(연결자가 _in.cfg 로 넘김)이 있으면(계약 §5.2 · X-145)."""
        d = self.base / "final"
        put(str(d / "결과보고_최종.docx"), mtime=datetime(2026, 9, 16, 1, 0, tzinfo=UTC))
        put(str(d / "설계서_V1.0.pptx"), mtime=datetime(2026, 9, 16, 1, 1, tzinfo=UTC))
        put(str(d / "초안.docx"), mtime=datetime(2026, 9, 16, 1, 2, tzinfo=UTC))
        cfg = self.cfg(**{"pc.watchFolders": [str(d)], "episode.finalWords": ["최종", "final", "v1.0"]})
        r = self.run_files(cfg)
        flags = {os.path.basename(x["path"]): x["flags"] for x in r.records}
        self.assertEqual(flags, {"결과보고_최종.docx": {"final_name": True}, "설계서_V1.0.pptx": {"final_name": True},
                                 "초안.docx": {}})
        r2 = self.run_files(self.cfg(**{"pc.watchFolders": [str(d)]}))          # 낱말이 없으면 판정하지 않는다(정제기 몫)
        self.assertTrue(all(x["flags"] == {} for x in r2.records))

    def test_poll_mode_saves_between_scans(self):
        """-Poll(CP §5.2 열린 문서 저장 폴링): Recent 상위 N 대상의 현재 mtime 이 지난 폴링 뒤면 op=save. 스캔 커서는 그대로 둔다."""
        d = self.base / "poll"
        rec = self.base / "poll_recent"
        a, b = d / "보고서.docx", d / "계산.xlsx"
        put(str(a), mtime=datetime(2026, 9, 18, 1, 0, tzinfo=UTC))
        put(str(b), mtime=datetime(2026, 9, 18, 2, 0, tzinfo=UTC))
        write_lnk(rec / "a.lnk", str(a), mtime=datetime(2026, 9, 18, 1, 1, tzinfo=UTC))
        write_lnk(rec / "b.lnk", str(b), mtime=datetime(2026, 9, 18, 2, 1, tzinfo=UTC))
        write_lnk(rec / "dir.lnk", str(d), mtime=datetime(2026, 9, 18, 2, 2, tzinfo=UTC))
        write_lnk(rec / "gone.lnk", str(d / "없음.docx"), mtime=datetime(2026, 9, 18, 2, 3, tzinfo=UTC))
        scan_cur = {"last_ts_utc": iso(datetime(2026, 9, 18, 1, 30, tzinfo=UTC))}
        cfg = self.cfg(**{"pc.watchFolders": [str(d)], "agent.filePoll.topN": 40})
        args = ["-Poll", "-TestNow", NOW, "-RecentDir", str(rec), "-NoToolMru"]
        r1 = run_ps(self.clone, SCRIPT, args, cfg=cfg, cursor=scan_cur)
        self.assertEqual(r1.rc, 0, r1.err())
        self.assertEqual([(os.path.basename(x["path"]), x["op"], x["root_id"]) for x in r1.records],
                         [("계산.xlsx", "save", "R01")])                                 # 스캔 커서 뒤 저장만
        self.assertEqual(r1.cursor, {"last_ts_utc": scan_cur["last_ts_utc"],
                                     "poll_ts_utc": iso(datetime(2026, 9, 18, 2, 0, tzinfo=UTC))})
        self.assertEqual((r1.status["mode"], r1.status["polled"]), ("poll", 2))
        put(str(a), mtime=datetime(2026, 9, 18, 3, 0, tzinfo=UTC))                     # 실행 사이 중간 저장
        r2 = run_ps(self.clone, SCRIPT, args, cfg=cfg, cursor=r1.cursor)
        self.assertEqual([(os.path.basename(x["path"]), x["ts_utc"]) for x in r2.records],
                         [("보고서.docx", iso(datetime(2026, 9, 18, 3, 0, tzinfo=UTC)))])
        self.assertEqual(r2.cursor["last_ts_utc"], scan_cur["last_ts_utc"])
        r3 = run_ps(self.clone, SCRIPT, args, cfg=cfg, cursor=r2.cursor)
        self.assertEqual((r3.rc, r3.records), (4, []))
        r4 = run_ps(self.clone, SCRIPT, args, cfg=self.cfg(**{"pc.watchFolders": [str(d)], "agent.filePoll.topN": 1}),
                    cursor=scan_cur)
        self.assertEqual(r4.status["polled"], 0)                                          # 가장 최근 바로가기 1개 = 없는 파일
        scan = self.run_files(self.cfg(**{"pc.watchFolders": [str(d)]}), cursor=r2.cursor)
        self.assertEqual(scan.cursor["poll_ts_utc"], r2.cursor["poll_ts_utc"])          # 스캔이 폴링 진전을 지우지 않는다
        self.assertEqual(scan.status["mode"], "scan")

    def test_package_dirs_off(self):
        r = self.run_files(self.cfg(**{"pc.excludePackageDirs": False}))
        self.assertIn("out.docx", self.names(r))
        self.assertIn("readme.docx", self.names(r))

    def test_overlapping_roots_scanned_once(self):
        cfg = self.cfg(**{"pc.watchFolders": [str(self.work), str(self.work / "과제A")]})
        r = self.run_files(cfg)
        paths = [x["path"] for x in r.records]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual({x["root_id"] for x in r.records}, {"R01"})

    def test_no_disk_writes(self):
        before_base = snapshot(self.base)
        before_lad = snapshot(self.clone.lad)
        before_tree = snapshot(self.clone.root / "collect")
        time.sleep(0.05)
        self.run_files()
        self.assertEqual(snapshot(self.base), before_base)
        self.assertEqual(snapshot(self.clone.lad), before_lad)
        self.assertEqual(snapshot(self.clone.root / "collect"), before_tree)

    def test_without_in_uses_defaults(self):
        """_in 이 없으면(단독 실행) 감시 폴더 없음 · 자동 발견 켬 · 최소 확장자 목록. 사적 낱말이 없으니 사적 폴더 후보도 잡히고,
        그 행의 폐기·건수는 정제기 몫이다(P §10.4) — 수집기는 원시 경로를 stdout 으로만 낸다."""
        args = ["-TestNow", NOW, "-RecentDir", str(self.recent), "-NoToolMru"]
        r = run_ps(self.clone, SCRIPT, args)
        self.assertEqual(r.status["in"], "none")
        self.assertEqual(r.status["roots"], {"watch": 0, "auto": 2, "missing": 0})
        self.assertEqual(self.names(r), ["a1.docx", "a2.pptx", "p1.xlsx", "p2.xlsx"])
        self.assertEqual(r.rc, 0)


if __name__ == "__main__":
    unittest.main()
