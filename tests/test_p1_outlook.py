# -*- coding: utf-8 -*-
r"""test_p1_outlook.py — WP1: Outlook COM·Windows Search 색인 수집 보강(판 무관, 검증된 0건만).

PowerShell 쪽은 tests\ps\Test-OutlookCommon.ps1(run_tests.py --ps 가 1회 띄움)이 남긴 값을 단언만 한다 — 이 파일은
PowerShell 을 띄우지 않는다. 결과가 없으면(--ps 없이 돌면) 그 시험은 건너뛴다.
'COM 이 쓴 완료 표(coverage)가 색인의 mail_source_index.json 이 생긴 뒤에도 남는다'는 순수 Python 으로 파일 규칙을 본다:
수집기 원문에서 출처별 파일 이름 규칙을 읽어 두 출처의 파일이 겹치지 않고, COM 의 표 읽기(Load-Coverage)가 다른 출처의
상태 파일을 보지 않는지(LM24 132-139 규칙 삭제) 확인한다.
"""
import json
import os
import re
import tempfile
import unittest

import _boot

ROOT = _boot.ROOT
COL = os.path.join(ROOT, "collect")


def _src(name):
    return _boot.read_text(os.path.join(COL, name))


def _code(text):
    """주석('#' 뒤)을 뗀 본문 — 주석에 적은 금지어(taskkill·Start-Job 등)를 코드로 오인하지 않게"""
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def lmstatus(line):
    """'LMSTATUS {...}' 한 줄 → dict(파싱 못 하면 실패)"""
    assert isinstance(line, str) and line.startswith("LMSTATUS "), line
    return json.loads(line[len("LMSTATUS "):])


def rng(st, axis):
    return [(x["from"], x["to"], x["st"]) for x in st["ranges"] if x["axis"] == axis]


class _Ps(unittest.TestCase):
    def setUp(self):
        r = _boot.ps_result("OutlookCommon")
        if r is None:
            self.skipTest("PowerShell 결과 없음 — tests\\run_tests.py --ps 로 실행")
        self.assertNotIn("error", r, r)
        self.r = r


class FindClassic(_Ps):
    """REQ-17·F-11·C-01: Find-ClassicOutlook 한 벌 — C2R 자기 경로는 MSI 가 아니다"""

    def test_c2r_only(self):
        c = self.r["c2r_only"]
        self.assertEqual((c["found"], c["c2r"], c["msi"], c["n"]), (True, True, False, 1))
        self.assertEqual(c["ver"], "16.0.19999.1")

    def test_c2r_own_installroot_not_msi(self):
        c = self.r["c2r_installroot"]
        self.assertEqual((c["found"], c["c2r"], c["msi"], c["n"]), (True, True, False, 1))

    def test_msi_and_com_and_none(self):
        m = self.r["msi_only"]
        self.assertEqual((m["found"], m["c2r"], m["msi"]), (True, False, True))
        self.assertTrue(m["path"].lower().endswith("office15\\outlook.exe"))
        c = self.r["com_only"]
        self.assertTrue(c["found"] and c["comReg"] and c["msi"])
        self.assertTrue(c["path"].endswith("OUTLOOK.EXE") and "/automation" not in c["path"], c["path"])
        n = self.r["none"]
        self.assertEqual((n["found"], n["comReg"], n["c2r"], n["msi"]), (False, False, False, False))


class ProfileVerdict(_Ps):
    """F-02·F-12·C-02·C-03: 띄우면 모달이 확실할 때만 건너뛴다"""

    def test_trace(self):
        t = self.r["trace"]
        self.assertTrue(t["useNew"] and t["anyNew"] and t["appx"] and t["anyApp"])
        self.assertFalse(t["none"])
        self.assertEqual(t["autoMig"], 1)

    def test_profiles(self):
        p = self.r["profiles"]
        self.assertEqual((p["p0"], p["p2"], p["p2u"]), (0, 2, 2))
        self.assertEqual(p["locs2"], ["16.0"])
        self.assertEqual((p["ab"], p["abu"]), (1, 0), "주소록만 든 프로필은 긍정 증거가 있을 때만 0")
        self.assertEqual(p["ex"], 1)
        self.assertTrue(p["cvMismatch"])
        self.assertEqual(p["cvLocs"], ["15.0"])

    def test_verdicts(self):
        v = self.r["verdict"]
        self.assertEqual(v["newol"], "R-NEWOL")            # 프로필 0 + UseNewOutlook + 미실행
        self.assertEqual(v["newol_appx"], "R-NEWOL")
        self.assertEqual(v["noprof"], "R-NOPROF")          # 새 Outlook 흔적 없음
        self.assertEqual(v["noclassic"], "R-NOCLASSIC")
        self.assertEqual(v["classic2"], "")                # 클래식 + UseNewOutlook + 프로필 2 → COM 시도
        self.assertEqual(v["pol"], "R-NEWOLPOL")           # 전환 정책 + 미실행
        self.assertEqual(v["pol_run"], "")                 # 떠 있으면 붙어 본다
        self.assertEqual(v["run0"], "")
        self.assertEqual(v["abonly"], "R-NOPROF")
        self.assertEqual(v["exch"], "")


class Canary(_Ps):
    """C-06·F-28: 'g' → yyyy-MM-dd HH:mm → ISO, 전부 실패면 fail(R-FILTER)"""

    def test_select(self):
        c = self.r["canary"]
        self.assertEqual(c["formats"], ["g", "plain", "iso"])
        self.assertEqual((c["plain_fmt"], c["plain"]), ("plain", "ok"))
        self.assertEqual((c["fail"], c["fail_fmt"]), ("fail", ""))
        self.assertEqual((c["none"], c["none_fmt"]), ("none", "g"))
        self.assertEqual(c["g"], "g")
        self.assertEqual(c["plain_literal"], "2026-03-05 14:07")
        self.assertEqual(c["iso_literal"], "2026-03-05T14:07:00")

    def test_collector_maps_fail_to_r_filter(self):
        s = _src("Get-OutlookData.ps1")
        i = s.index("$sel = Select-DaslFormat -Probe $probe")
        body = s[i:i + 1500]
        self.assertIn("if ($canary -eq 'fail')", body)
        self.assertIn("Stop-Collect 'R-FILTER'", body)
        self.assertIn("$script:monthMismatch++", s)                 # Restrict 결과 재검사
        self.assertIn("if ($t -lt $mo.start -or $t -ge $upper)", s)


class MonthDone(_Ps):
    """W1-02·C-08·F-09: 0행 달은 카나리아·지평선·OST 신선도를 모두 만족할 때만 zero_ok 완료"""

    def test_states(self):
        m = self.r["month"]
        self.assertEqual(m["zero_ok"], {"done": True, "st": "zero_ok"})
        self.assertEqual(m["before_horizon"], {"done": False, "st": "out_of_horizon"})
        self.assertEqual(m["horizon_inside"], {"done": False, "st": "ok"})
        self.assertEqual(m["no_canary"], {"done": False, "st": "unverified"})
        self.assertEqual(m["mismatch"], {"done": False, "st": "partial"})
        self.assertEqual(m["stale"], {"done": False, "st": "zero_ok"})
        self.assertEqual(m["online"], {"done": True, "st": "zero_ok"})
        self.assertEqual(m["stopped"], {"done": False, "st": "partial"})
        self.assertEqual(m["rows_no_canary"], {"done": True, "st": "ok"})

    def test_ranges(self):
        mr = self.r["month_ranges"]
        t = lambda xs: [(x["from"], x["to"], x["st"]) for x in xs]  # noqa: E731
        self.assertEqual(t(mr["horizon_inside"]), [("2026-03-01", "2026-03-14", "out_of_horizon"),
                                                   ("2026-03-15", "2026-03-31", "ok")])
        self.assertEqual(t(mr["stale"]), [("2026-10-01", "2026-10-02", "zero_ok"),
                                          ("2026-10-03", "2026-10-07", "out_of_horizon")])
        self.assertEqual(t(mr["before_horizon"]), [("2026-03-01", "2026-03-31", "out_of_horizon")])
        self.assertEqual(t(mr["days"]), [("2026-03-01", "2026-03-03", "ok"), ("2026-03-05", "2026-03-05", "ok")])
        self.assertEqual({x["axis"] for x in mr["before_horizon"]}, {"mail_out"})

    def test_coverage_version(self):
        c = self.r["coverage"]
        self.assertTrue(c["ok"])
        self.assertFalse(c["ver_mismatch"], "판(cursorEpoch) 불일치면 폐기")
        self.assertFalse(c["lm24"], "LM24 v2 표(판 없음)는 폐기 — 잘못 기록된 '완료'를 다시 읽는다")
        self.assertFalse(c["writer"])
        self.assertFalse(c["none"])


class Protected(_Ps):
    """C-05: 위험의 긍정 증거가 있을 때만 보호 멤버를 읽지 않는다"""

    def test_protected(self):
        p = self.r["prot"]
        self.assertFalse(p["always_warn"])
        self.assertFalse(p["prompt"])
        self.assertFalse(p["deny"])
        self.assertTrue(p["approve"])
        self.assertTrue(p["no_info"], "정보 없음 → LM24 처럼 읽는다")
        self.assertTrue(p["av_empty"])
        self.assertFalse(p["av_off"])
        self.assertFalse(p["av_old"])
        self.assertTrue(p["av_ok"])
        self.assertEqual(p["why_off"], "av-off")

    def test_rcv_unknown_not_to(self):
        s = _src("Get-OutlookData.ps1")
        self.assertNotIn("catch { $rcv = 'to' }", s, "수신자 열람 실패를 'to' 로 올리던 오판이 남아 있다")
        self.assertIn("$rcv = 'unknown'; $script:protErr++", s)
        self.assertIn("'R-NOADDR'", s)
        self.assertIn("Get-ProtectedState", s)


class Folders(_Ps):
    """C-07·W1-03: 기본 저장소 메일 폴더 재귀 · 제외 목록 · 상한"""

    def test_skip_ids(self):
        ids = set(self.r["folders"]["skip_ids"])
        for n in (3, 4, 16, 19, 20, 21, 22, 23, 25):
            self.assertIn(n, ids)
        self.assertNotIn(6, ids)
        self.assertNotIn(5, ids)

    def test_walk(self):
        f = self.r["folders"]
        self.assertEqual(f["list"], ["Inbox:inbox:inbox", "Sent Items:sent:sent", "Archive:inbox:subfolder",
                                     "Projects:inbox:subfolder", "old sent:sent:subfolder", "deep:inbox:subfolder"])
        self.assertEqual((f["excluded"], f["empty"], f["capped"]), (7, 1, False))
        self.assertEqual((f["cap_n"], f["cap_capped"]), (2, True))
        for nm in ("Conflicts", "Local Failures", "Server Failures"):
            self.assertNotIn(nm, f["list2"])
        self.assertIn("Sync Issues", f["list2"])
        self.assertEqual(f["key_len"], [12])


class IndexStore(_Ps):
    """F-29·C-10: 주소 일치 행이 있을 때만 주 저장소로 거른다"""

    def test_scope(self):
        s = self.r["store"]
        self.assertEqual((s["name_mode"], s["name_other"]), ("unknown", 0))
        self.assertEqual(s["addr_mode"], "addr")
        self.assertEqual(s["addr_stores"], ["me@corp.example"])
        self.assertFalse(s["addr_own"])
        self.assertTrue(s["addr_shared"])
        self.assertFalse(s["addr_nostore"])


class Status(_Ps):
    """P3: LMSTATUS 한 줄 JSON"""

    def test_line(self):
        st = lmstatus(self.r["status_line"])
        self.assertEqual((st["v"], st["src"], st["rc"]), (1, "com", 3))
        self.assertEqual(st["reason"], "R-FILTER,R-NOADDR")
        self.assertEqual(st["counts"]["profile_locs"], ["16.0"])
        self.assertEqual(rng(st, "mail_in"), [("2026-03-01", "2026-03-31", "blocked")])
        e = lmstatus(self.r["status_line_empty"])
        self.assertEqual((e["rc"], e["reason"], e["counts"], e["ranges"]), (1, "", {}, []))


class ComSelfTest(_Ps):
    """Get-OutlookData 자가검증 끝단 — -OutDir·-Tag 출처 파일 · 완료 표 판 · 마지막 줄 LMSTATUS"""

    def test_first_run(self):
        c = self.r["com"]
        self.assertEqual(c["rc1"], 0, c["last1"])
        st = lmstatus(c["last1"])
        self.assertEqual((st["src"], st["rc"]), ("com", 0))
        self.assertEqual(st["counts"]["months_read"], {"mail": 3, "calendar": 3})
        for k in ("elevated", "profile_locs", "ol", "new_ol", "filter_fmt", "filter_mismatch", "folders"):
            self.assertIn(k, st["counts"])
        for ax in ("mail_in", "mail_out", "cal"):
            got = rng(st, ax)
            self.assertEqual(len(got), 3, (ax, got))
            self.assertTrue(all(x[2] == "ok" for x in got), got)
        self.assertEqual(c["files"], ["cal_com.csv", "coverage_com.json", "mail_com.csv", "mail_source_com.json"])
        self.assertTrue(c["data_untouched"])
        for k in ("source", "mail", "calendar", "me", "uncovered_months", "coverage_complete", "selftest", "ver", "rc", "filter_fmt"):
            self.assertIn(k, c["src_keys"])
        self.assertEqual(c["src_source"], "com")

    def test_coverage_survives_index_and_version_discards(self):
        c = self.r["com"]
        self.assertTrue(c["cov_kept"])
        s2 = lmstatus(c["last2"])
        self.assertEqual(s2["counts"]["months_read"]["mail"], 0, "색인 상태 파일이 생겨도 COM 표는 그대로 쓰인다")
        self.assertEqual(len(rng(s2, "mail_in")), 3)
        s3 = lmstatus(c["last3"])
        self.assertEqual(s3["counts"]["months_read"]["mail"], 3, "판이 다르면 표를 버리고 다시 읽는다")
        self.assertEqual(c["rc3"], 0)


class IndexFake(_Ps):
    """Get-OutlookIndex 가짜 색인 끝단 — 막힘 사유 · 주 저장소 · 반복 마스터 · 상한 · zero_ok 없음"""

    def test_main(self):
        i = self.r["index"]
        st = lmstatus(i["last1"])
        self.assertEqual(i["rc1"], 3)
        self.assertEqual(st["reason"].split(",")[0], "R-RECURINC")
        cn = st["counts"]
        self.assertEqual((cn["store_scope"], cn["other_store"], cn["literal_edge"], cn["recurring_masters"]), ("addr", 1, 1, 1))
        self.assertEqual(rng(st, "mail_in"), [("2026-09-02", "2026-09-02", "ok")])
        self.assertEqual(rng(st, "mail_out"), [("2026-09-03", "2026-09-03", "ok")])
        self.assertEqual(rng(st, "cal"), [("2026-09-01", "2026-09-30", "partial")], "반복 마스터 1건 → 기간 전체 partial")
        self.assertEqual(i["mail_lines"], 3)
        self.assertEqual((i["src_store"], i["src_source"]), ("addr", "index"))
        self.assertTrue(i["lm24_files_absent"])

    def test_display_name_store(self):
        i = self.r["index"]
        st = lmstatus(i["last2"])
        self.assertEqual(i["rc2"], 0, i["last2"])
        self.assertEqual((st["counts"]["store_scope"], st["counts"]["other_store"]), ("unknown", 0))
        self.assertEqual(rng(st, "mail_in"), [("2026-09-02", "2026-09-02", "ok")])
        self.assertEqual(rng(st, "cal"), [("2026-09-04", "2026-09-04", "ok")])

    def test_blocked_reasons(self):
        i = self.r["index"]
        for k, code in (("3", "R-NOIDX"), ("4", "R-IDXPOLICY"), ("5", "R-IDXEMPTY")):
            st = lmstatus(i["last" + k])
            self.assertEqual(i["rc" + k], 3, (k, i["last" + k]))
            self.assertEqual(st["reason"].split(",")[0], code)
        e = lmstatus(i["last5"])
        self.assertTrue(e["ranges"] and all(x["st"] == "unverified" for x in e["ranges"]), e["ranges"])

    def test_cap_partial(self):
        i = self.r["index"]
        st = lmstatus(i["last6"])
        self.assertIn("R-CAP", st["reason"].split(","))
        self.assertTrue(st["counts"]["mail_capped"])
        self.assertEqual(st["counts"]["cap_oldest"], "2026-09-02")
        self.assertEqual(rng(st, "mail_in"), [("2026-09-02", "2026-09-02", "partial")])
        self.assertEqual(rng(st, "mail_out"), [("2026-09-02", "2026-09-02", "partial"), ("2026-09-03", "2026-09-03", "ok")])

    def test_no_zero_ok_from_index(self):
        i = self.r["index"]
        for k in ("1", "2", "3", "4", "5", "6"):
            st = lmstatus(i["last" + k])
            self.assertFalse([x for x in st["ranges"] if x["st"] == "zero_ok"], k)

    def test_tmp_removed(self):
        self.assertTrue(self.r["tmp_removed"])


class FileRules(unittest.TestCase):
    """P5: 출처마다 자기 파일 — COM 의 완료 표는 색인 상태 파일(mail_source_index.json)이 생겨도 남는다(순수 Python)"""

    NAME_RX = re.compile(r"\(\s*'(mail|coverage|mail_source)'\s*\+\s*\$sfx\s*\+\s*'(\.csv|\.json)'\s*\)|'(cal)'\s*\+\s*\$sfx\s*\+\s*'(\.csv)'")

    def _names(self, src, tag):
        out = set()
        for m in self.NAME_RX.finditer(src):
            base = m.group(1) or m.group(3)
            ext = m.group(2) or m.group(4)
            out.add(f"{base}_{tag}{ext}")
        return out

    def test_disjoint_names_and_coverage_kept(self):
        com = self._names(_src("Get-OutlookData.ps1"), "com")
        idx = self._names(_src("Get-OutlookIndex.ps1"), "index")
        self.assertEqual(com, {"mail_com.csv", "cal_com.csv", "coverage_com.json", "mail_source_com.json"})
        self.assertEqual(idx, {"mail_index.csv", "cal_index.csv", "mail_source_index.json"})
        self.assertFalse(com & idx)
        with tempfile.TemporaryDirectory(prefix="lm28_t1_") as d:
            srcdir = os.path.join(d, "data", "outlook", "src")
            os.makedirs(srcdir)
            for n in com:
                with open(os.path.join(srcdir, n), "w", encoding="utf-8") as f:
                    f.write("{}" if n.endswith(".json") else "h\n")
            for n in idx:                                   # 색인이 자기 파일을 쓴다(덮어쓰기)
                with open(os.path.join(srcdir, n), "w", encoding="utf-8") as f:
                    f.write('{"source":"index"}' if n.endswith(".json") else "h\n")
            self.assertTrue(os.path.isfile(os.path.join(srcdir, "coverage_com.json")))
            self.assertTrue(os.path.isfile(os.path.join(srcdir, "mail_source_com.json")))

    def test_load_coverage_ignores_other_sources(self):
        s = _src("Get-OutlookData.ps1")
        i = s.index("function Load-Coverage")
        body = s[i:s.index("function Save-Coverage", i)]
        self.assertNotIn("$srcP", body, "완료 표를 읽을 때 mail_source 를 보지 않는다(LM24 132-139 삭제)")
        self.assertNotIn("-ne 'com'", body)
        self.assertIn("Test-CoverageUsable", body)
        self.assertIn("$covVer = '{0}|{1}' -f $COLLECTOR_VER", s)
        self.assertIn("'collect' 'cursorEpoch' 1", s)
        ix = _src("Get-OutlookIndex.ps1")
        self.assertNotIn("coverage", ix.lower().replace("coverage_complete", ""), "색인은 COM 완료 표를 건드리지 않는다")

    def test_zero_rows_month_needs_zero_ok(self):
        s = _src("Get-OutlookData.ps1")
        self.assertNotIn("[int]$script:cov[$kind][$k].rows -gt 0) { $script:cov[$kind].Remove($k) }", s,
                         "'rows 0 이면 완료 보존' 예외가 남아 있다")
        self.assertIn("$zok =", s)

    def test_status_is_last_line_and_exit_codes(self):
        s = _src("Get-OutlookData.ps1")
        tail = s.rstrip().splitlines()[-2:]
        self.assertTrue(tail[0].startswith("Write-LmStatus"), tail)
        self.assertEqual(tail[1].strip(), "exit $stRc")
        self.assertNotRegex(s, r"(?m)^\s*exit 0\s*$", "건너뜀을 exit 0 으로 가리던 LM24 경로가 남아 있다")
        ix = _src("Get-OutlookIndex.ps1")
        self.assertNotRegex(ix, r"(?m)^\s*exit 1\s*$")
        self.assertIn("'R-IDXEMPTY'", ix)
        self.assertIn("return , $rows", ix)
        self.assertIn("$cmd.CommandTimeout = $QUERY_TIMEOUT_SEC", ix)
        self.assertIn("$QUERY_TIMEOUT_SEC = 60", ix)

    def test_single_find_classic(self):
        hits = [fn for fn in os.listdir(COL) if fn.lower().endswith(".ps1")
                and "function Find-ClassicOutlook" in _src(fn)]
        self.assertEqual(hits, ["OutlookCommon.ps1"])
        for fn in ("Get-OutlookData.ps1", "Get-OutlookIndex.ps1", "Diagnose-Collectors.ps1"):
            self.assertIn("'OutlookCommon.ps1'", _src(fn), fn)

    def test_process_discipline(self):
        s = _src("Get-OutlookData.ps1")
        self.assertNotRegex(_code(s), r"(?i)\btaskkill\b")
        self.assertIn("Start-OcLaunchWatchdog", s)
        self.assertIn("$nEx -eq 0 -and $nIn -eq 0", s)                      # Explorers·Inspectors 0 일 때만 Quit
        self.assertIn("Stop-OutlookWeStarted -Since $launchT", s)
        i = s.index("try { $ns.Logon(")
        self.assertGreater(i, s.index("$wd = Start-OcLaunchWatchdog"), "Logon 은 우리가 띄웠을 때만")
        self.assertEqual(s.count("$ns.Logon("), 1)
        oc = _src("OutlookCommon.ps1")
        self.assertNotRegex(_code(oc), r"(?i)\bAdd-Type\b|\btaskkill\b|Start-Job|Start-Process")
        self.assertIn("(^|\\s)[-/]embedding", oc)
        dg = _src("Diagnose-Collectors.ps1")
        self.assertNotIn("Start-Job", _code(dg), "진단의 COM 붙기 시험은 런스페이스(프로세스 없음)")
        self.assertIn("Invoke-OcTimed", dg)


if __name__ == "__main__":
    unittest.main()
