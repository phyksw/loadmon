# -*- coding: utf-8 -*-
r"""test_p0_names.py — WP0: LM24 와 이름 분리 · 팀 호환 불변 · bat 일괄 개명 · 인코딩 · 새 설정 키.

LM27 hook_check L-28(OLD_PORTS)의 '옛 이름 0건 검사' 발상만 가져왔다(코드 이식 없음).
실 Outlook·Edge·작업 스케줄러는 건드리지 않는다 — 파일·문자열·순수 함수만 본다.
(9)는 run_tests.py --ps 가 남긴 PowerShell 결과(Test-LmName)를 단언만 한다 — 없으면 건너뛴다.
"""
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest

import _boot

ROOT = _boot.ROOT
import lmname  # noqa: E402

# ── 고정값 — 실재하지 않는 예시 경로와 그 h6(core\lmname.py·collect\LmName.ps1 공통 규칙) ──
FIXED_PATH = r"C:\LM28test\Sample Folder"
FIXED_H6 = "d0feee"
# 팀 서버 기본 IP 는 값 대신 해시로만 확인한다(사내 IP 를 시험에 쓰지 않는다)
DEFAULT_HOST_SHA256 = "89663266b0b251e8471fecefd353753b333d45c6ffe3001861467ab7558e5d9b"

# (1) 운영 코드에 남으면 안 되는 옛 이름(LM24·LM22 판의 작업·뮤텍스·프로필·포트·임시 파일)
BANNED = [
    ("LoadMonitor24-Sampler", re.compile(re.escape("LoadMonitor24-Sampler"))),
    ("LoadMonitor24-ActivitySampler", re.compile(re.escape("LoadMonitor24-ActivitySampler"))),
    ("copilot_profile", re.compile(re.escape("copilot_profile"))),
    ("9333", re.compile(r"(?<!\d)9333(?!\d)")),
    ("9148", re.compile(r"(?<!\d)9148(?!\d)")),
    ("LM22-Prepare", re.compile(re.escape("LM22-Prepare"))),
    ("lm_from.txt", re.compile(re.escape("lm_from.txt"))),
]
SCAN_SKIP_DIRS = {".git", "python", "data", "report", "teamdata", "__pycache__", ".ruff_cache",
                  ".wf", ".claude", "tests", "samples", "lm20_ref"}
# 허용: lmname 의 옛 값 판별 상수(OLD_*) 정의 줄 · 역사 주석(필요할 때만 (상대경로, 줄 조각)으로 추가)
OLD_CONST_FILE = os.path.join("core", "lmname.py")
HISTORY_ALLOW = []

# (8) 배포 템플릿 noticeSenders 에 허용되는 일반어(조직 고유 계정명은 받은 사람이 자기 config.json 에)
GENERIC_NOTICE = {
    "no-reply", "noreply", "do-not-reply", "donotreply", "알림", "notification", "notice", "뉴스레터",
    "newsletter", "웹진", "webzine", "공지", "설문", "survey", "시스템", "system", "sharepoint", "yammer",
    "viva", "helpdesk", "보안공지", "(광고)", "광고", "promotion", "프로모션", "마케팅", "수신거부",
    "unsubscribe", "mailer-daemon", "postmaster",
}

BAT_NAMES = ["LoadMonitor28-UI.bat", "LoadMonitor28.bat", "LoadMonitor28-팀취합.bat", "LoadMonitor28-팀서버.bat",
             "LoadMonitor28-팀업로드.bat", "LoadMonitor28-팀서버주소.bat", "LoadMonitor28-수집진단.bat",
             "LoadMonitor28-가동시간비교.bat", "LoadMonitor28-이동준비.bat", "LoadMonitor28-팀로드율재계산.bat"]


def _ops_files(exts=(".py", ".ps1", ".bat")):
    for cur, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP_DIRS]
        for fn in files:
            if os.path.splitext(fn)[1].lower() in exts:
                p = os.path.join(cur, fn)
                yield p, os.path.relpath(p, ROOT)


def _ast_assign(path, name):
    src = _boot.read_text(path)
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path} 에 {name} 없음")


def _cfg(name):
    with open(os.path.join(ROOT, "config", name), encoding="utf-8-sig") as f:
        return json.load(f)


class OldNamesGone(unittest.TestCase):
    """(1) 옛 이름 0건"""

    def test_no_old_names_in_ops_code(self):
        hits = []
        n = 0
        for p, rel in _ops_files():
            n += 1
            for i, ln in enumerate(_boot.read_text(p).splitlines(), 1):
                for label, rx in BANNED:
                    if not rx.search(ln):
                        continue
                    if rel == OLD_CONST_FILE and ln.lstrip().startswith(("OLD_CDP_PORT =", "OLD_PROFILE =")):
                        continue
                    if any(rel == r and frag in ln for r, frag in HISTORY_ALLOW):
                        continue
                    hits.append(f"{rel}:{i}: {label}")
        self.assertGreater(n, 50, "운영 파일을 거의 못 찾았다 — 경로 규칙 확인")
        self.assertEqual(hits, [], "옛 이름이 남아 있다:\n" + "\n".join(hits))

    def test_ops_python_compiles(self):
        """이름을 바꾼 파일이 구문 오류 없이 읽힌다(ruff 가 없는 PC 에서도 — 인프로세스 compile)"""
        bad = []
        for p, rel in _ops_files((".py",)):
            try:
                compile(_boot.read_text(p), p, "exec")
            except SyntaxError as e:
                bad.append(f"{rel}:{e.lineno}: {e.msg}")
        self.assertEqual(bad, [])

    def test_no_lm24_bats_left(self):
        left = [f for f in os.listdir(ROOT) if f.lower().endswith(".bat") and f.startswith("LoadMonitor24")]
        self.assertEqual(left, [])

    def test_temp_names_have_lm28_prefix(self):
        want = {
            "LoadMonitor28.bat": ["lm28_from.txt", "lm28_to.txt"],
            "LoadMonitor28-이동준비.bat": ["LM28-Prepare-Move.ps1"],
            os.path.join("collect", "Get-PcOnHints.py"): ["lm28_hist_copy"],
            os.path.join("tools", "Make-Package.ps1"): ["LM28pkg_", "'LoadMonitor28'", "LoadMonitor28_v1_"],
            os.path.join("ui", "app.py"): ["LM28-Prepare-Move.ps1"],
            "ruff.toml": ["LoadMonitor28-ruff_cache"],
        }
        for rel, frags in want.items():
            txt = _boot.read_text(os.path.join(ROOT, rel))
            for fr in frags:
                self.assertIn(fr, txt, f"{rel} 에 {fr} 없음")


class FolderHashAndPorts(unittest.TestCase):
    """(2) 설치 폴더 해시 h6 · 포트 — LM28 에는 예약 작업·뮤텍스(샘플러)가 없다"""

    def test_fixed_path_h6(self):
        self.assertEqual(lmname.h6(FIXED_PATH), FIXED_H6)
        for v in (FIXED_PATH + "\\", FIXED_PATH.lower(), FIXED_PATH.upper(), "C:/LM28test/Sample Folder/"):
            self.assertEqual(lmname.h6(v), FIXED_H6, v)
        self.assertEqual(lmname.names(FIXED_PATH), {"H6": FIXED_H6})
        self.assertNotEqual(lmname.h6(r"C:\LM28test\Other Folder"), FIXED_H6)

    def test_no_task_or_mutex_names(self):
        for k in ("TASK_RE", "TASK_SAMPLER", "TASK_TEAMS", "MUTEX_ACTIVITY", "MUTEX_TEAMS"):
            self.assertFalse(hasattr(lmname, k), k)
        ps_names = _boot.read_text(os.path.join(ROOT, "collect", "LmName.ps1"))
        for k in ("TaskSampler", "TaskTeams", "MutexActivity", "MutexTeams", "TaskRegex"):
            self.assertNotIn(k, ps_names, k)

    def test_ui_ports_and_cdp(self):
        self.assertEqual(lmname.UI_PORTS, range(9248, 9268))
        self.assertEqual(lmname.CDP_PORT, 9533)
        self.assertNotEqual(lmname.CDP_PORT, lmname.OLD_CDP_PORT)
        self.assertNotIn(lmname.OLD_PROFILE, lmname.EDGE_PROFILE_NAME)
        self.assertEqual(lmname.EDGE_PROFILE, os.path.join(ROOT, "data", "lm28_edge"))
        app = _boot.read_text(os.path.join(ROOT, "ui", "app.py"))
        self.assertIn("for p in lmname.UI_PORTS", app)
        self.assertIn("<title>LoadMonitor28</title>", app)
        self.assertIn("<h1>LoadMonitor28<small", app)

    def test_edge_kill_scoped_to_this_root(self):
        app = _boot.read_text(os.path.join(ROOT, "ui", "app.py"))
        i = app.index("def kill_copilot_edge")
        body = app[i:app.index("\ndef ", i + 10)]
        self.assertIn("lmname.edge_profile(ROOT)", body)
        self.assertIn(".Contains(", body)
        pm = _boot.read_text(os.path.join(ROOT, "tools", "Prepare-Move.ps1"))
        self.assertIn("Join-Path $Root 'data\\lm28_edge'", pm)
        mp = _boot.read_text(os.path.join(ROOT, "tools", "Make-MovePack.py"))
        self.assertIn("lmname.edge_profile(ROOT)", mp)
        sc = _boot.read_text(os.path.join(ROOT, "자가점검.py"))
        self.assertIn('os.path.join(ROOT, d, "lm28_edge")', sc)


class TeamCompatUnchanged(unittest.TestCase):
    """(3) 팀 서버 호환 불변 — 기본 주소는 해시로만"""

    def test_default_host_and_port(self):
        import teamaddr
        self.assertEqual(hashlib.sha256(teamaddr.DEFAULT_HOST.encode("utf-8")).hexdigest(), DEFAULT_HOST_SHA256)
        self.assertEqual(teamaddr.DEFAULT_PORT, 9310)
        self.assertEqual(teamaddr.FILE_NAME, "team_server.json")
        self.assertEqual(teamaddr.LEGACY_KEY, "teamServerUrl")

    def test_env_names_lm28(self):
        ta = _boot.read_text(os.path.join(ROOT, "core", "teamaddr.py"))
        bat = _boot.read_text(os.path.join(ROOT, "LoadMonitor28-팀서버주소.bat"))
        for v in lmname.TEAM_ADDR_ENV:
            self.assertIn(v, ta)
            self.assertIn(f'set /p "{v}=', bat)
        self.assertNotIn("LM24_TA_", bat)
        self.assertNotIn('"LM24_TA_HOST"', ta)
        self.assertIn("core\\teamaddr.py --set-env", bat)

    def test_set_env_reads_lm28_names_only(self):
        """bat → teamaddr --set-env 경로를 프로세스 없이(main 직접 호출) — LM28_TA_* 만 읽는다"""
        import teamaddr
        keys = ("LM24_TA_HOST", "LM24_TA_PORT") + tuple(lmname.TEAM_ADDR_ENV)
        saved = {k: os.environ.get(k) for k in keys}
        try:
            with tempfile.TemporaryDirectory(prefix="lm28_t0_") as d:
                os.makedirs(os.path.join(d, "config"))
                for k in keys:
                    os.environ.pop(k, None)
                os.environ["LM24_TA_HOST"] = "10.7.7.7"            # 옛 판 bat 의 잔여값 — 읽으면 안 된다
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = teamaddr.main(["--root", d, "--set-env", "--json"])
                self.assertEqual(rc, 0)
                self.assertFalse(os.path.exists(os.path.join(d, "config", teamaddr.FILE_NAME)), "LM24_TA_* 를 읽었다")
                os.environ[lmname.TEAM_ADDR_ENV[0]] = "http://10.9.9.9:9411"
                with contextlib.redirect_stdout(out):
                    rc = teamaddr.main(["--root", d, "--set-env", "--json"])
                a = teamaddr.load(d)
                self.assertEqual((rc, a.host, a.port), (0, "10.9.9.9", 9411))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class BatRenameTogether(unittest.TestCase):
    """(4) bat 10개 일괄 개명 — NEED·FILES.txt·update_files·Make-Package·EDIT_BAT 이 한 번에"""

    def test_need_bats_exist(self):
        need = _ast_assign(os.path.join(ROOT, "자가점검.py"), "NEED")
        bats = [x for x in need if x.lower().endswith(".bat")]
        self.assertEqual(sorted(bats), sorted(BAT_NAMES))
        for b in bats:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, b)), b)
        for f in ("core/lmname.py", "collect/LmName.ps1", "tools/lm_fixenc.py"):
            self.assertIn(f, need)

    def test_files_txt_head_matches(self):
        with open(os.path.join(ROOT, "FILES.txt"), encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        head = _ast_assign(os.path.join(ROOT, "tools", "update_files.py"), "HEAD")
        self.assertEqual(lines[0], head[0])
        mp = _boot.read_text(os.path.join(ROOT, "tools", "Make-Package.ps1"))
        m = re.search(r"-match '\^\((LoadMonitor\d+ 필수)\|", mp)
        self.assertIsNotNone(m, "Make-Package 머리말 정규식을 못 찾음")
        self.assertTrue(lines[0].startswith(m.group(1)), (lines[0], m.group(1)))
        self.assertTrue(lines[0].startswith("LoadMonitor28 필수"))
        body = "\n".join(lines)
        for b in BAT_NAMES:
            self.assertIn(b, body, f"FILES.txt 에 {b} 없음")

    def test_edit_bat_exists(self):
        import teamaddr
        self.assertEqual(teamaddr.EDIT_BAT, "LoadMonitor28-팀서버주소.bat")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, teamaddr.EDIT_BAT)))
        ct = _boot.read_text(os.path.join(ROOT, "tools", "check_teamaddr.py"))
        self.assertIn("TA.EDIT_BAT", ct)
        self.assertIn('"%LM28_TA_HOST%"', ct)

    def test_bat_titles(self):
        for b in BAT_NAMES:
            txt = _boot.read_text(os.path.join(ROOT, b))
            self.assertNotIn("LoadMonitor24", txt, b)
            m = re.search(r"(?im)^title (.+)$", txt)
            self.assertIsNotNone(m, b)
            self.assertTrue(m.group(1).startswith("LoadMonitor28"), (b, m.group(1)))


class SelfExclusion(unittest.TestCase):
    """(5) 자기 산출물 제외 정규식 — loadmonitor* 와 loadmon<숫자>* 둘 다"""

    def _rx(self, rel):
        txt = _boot.read_text(os.path.join(ROOT, rel))
        i = txt.index("function Test-SelfPath")
        body = txt[i:txt.index("\n}", i)]
        self.assertIn("TrimEnd('\\') + '\\'", txt[max(0, i - 400):i], f"{rel}: ROOT 접두 끝 구분자")
        m = re.search(r"\$pl -match '([^']+)'", body)
        self.assertIsNotNone(m, rel)
        return m.group(1)

    def test_patterns(self):
        pats = {rel: self._rx(rel) for rel in (os.path.join("collect", "Get-FileActivity.ps1"),
                                               os.path.join("collect", "Get-RecentFiles.ps1"))}
        self.assertEqual(len(set(pats.values())), 1, pats)
        rx = re.compile(next(iter(pats.values())), re.IGNORECASE)
        for p in (r"D:\x\loadmon28\report\a.html", r"C:\LoadMonitor24\data\b.csv",
                  r"E:\tools\LoadMonitor28_v1\python\x.py", r"D:\dev\loadmon27\teamdata\a.json"):
            self.assertIsNotNone(rx.search(p.lower()), p)
        for p in (r"D:\work\loadcase\a.xlsx", r"D:\x\loadmon28\core\extract.py", r"D:\loadmon\data\a.csv"):
            self.assertIsNone(rx.search(p.lower()), p)


class Encoding(unittest.TestCase):
    """(6) .ps1 = UTF-8 BOM + CRLF · .bat = CP949 + CRLF (인프로세스)"""

    def test_all_scripts(self):
        import lm_fixenc
        items = lm_fixenc.scan(ROOT)
        self.assertGreaterEqual(len([1 for _p, k in items if k == "bat"]), len(BAT_NAMES))
        self.assertGreater(len([1 for _p, k in items if k == "ps1"]), 15)
        bad = lm_fixenc.check_files(items)
        self.assertEqual({os.path.relpath(p, ROOT): v for p, v in bad.items()}, {})

    def test_fixenc_roundtrip(self):
        import lm_fixenc
        src = "@echo off\nrem 한글 줄\necho 끝\n".encode()
        b = lm_fixenc.to_bat_bytes(src)
        self.assertEqual(lm_fixenc.check_bat(b), [])
        self.assertEqual(b.decode("cp949"), "@echo off\r\nrem 한글 줄\r\necho 끝\r\n")
        self.assertEqual(lm_fixenc.to_bat_bytes(b), b, "멱등이 아니다")
        with self.assertRaises(ValueError):
            lm_fixenc.to_bat_bytes("echo a\u2014b\n".encode("utf-8"))
        p = lm_fixenc.to_ps1_bytes("# 주석\nWrite-Host '가'\r\n".encode())
        self.assertEqual(lm_fixenc.check_ps1(p), [])
        self.assertEqual(lm_fixenc.to_ps1_bytes(p), p)
        self.assertTrue(lm_fixenc.check_ps1(b"# x\n"))       # BOM 없음·LF 단독은 문제로 잡힌다
        with tempfile.TemporaryDirectory(prefix="lm28_t0_") as d:
            fp = os.path.join(d, "a.bat")
            with open(fp, "wb") as f:
                f.write(src)
            self.assertTrue(lm_fixenc.fix_file(fp, "bat"))
            self.assertFalse(lm_fixenc.fix_file(fp, "bat"))
            with open(fp, "rb") as f:
                self.assertEqual(lm_fixenc.check_bat(f.read()), [])


class EdgeConfigOverride(unittest.TestCase):
    """(7) copilot_auto 실효 설정 — 옛 포트·옛 프로필을 LM28 값으로 덮는다 · 배포 설정의 포트·팀즈 웹 상한"""

    def test_old_values_overridden(self):
        import copilot_auto
        self.assertEqual(copilot_auto.DEFAULTS["port"], lmname.CDP_PORT)
        self.assertEqual(copilot_auto.DEFAULTS["profileDir"], lmname.edge_profile(copilot_auto.ROOT))
        with tempfile.TemporaryDirectory(prefix="lm28_t0_") as d:
            cp = os.path.join(d, "config.json")
            with open(cp, "w", encoding="utf-8") as f:
                json.dump({"copilotAuto": {"port": lmname.OLD_CDP_PORT,
                                           "profileDir": "D:\\old\\data\\" + lmname.OLD_PROFILE,
                                           "model": "X"}}, f)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                cfg = copilot_auto.load_cfg(cp)
            self.assertEqual(cfg["port"], 9533)
            self.assertTrue(cfg["profileDir"].lower().endswith("\\data\\lm28_edge"), cfg["profileDir"])
            self.assertEqual(cfg["model"], "X")
            self.assertIn("경고", err.getvalue())
            with open(cp, "w", encoding="utf-8") as f:
                json.dump({"copilotAuto": {"port": 9555, "profileDir": "D:\\mine\\edge"}}, f)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                cfg = copilot_auto.load_cfg(cp)
            self.assertEqual((cfg["port"], cfg["profileDir"]), (9555, "D:\\mine\\edge"))   # 사용자 값은 그대로
            self.assertEqual(err.getvalue(), "")
        self.assertTrue(lmname.is_old_edge(port=lmname.OLD_CDP_PORT))
        self.assertTrue(lmname.is_old_edge(profile_dir="X:\\" + lmname.OLD_PROFILE.upper()))
        self.assertFalse(lmname.is_old_edge(port=9533, profile_dir=lmname.EDGE_PROFILE))

    def test_config_port_and_teams_web(self):
        for name in ("config.default.json", "config.json"):
            if not os.path.isfile(os.path.join(ROOT, "config", name)):
                continue
            c = _cfg(name)
            self.assertEqual(c["copilotAuto"]["port"], 9533, name)
            self.assertEqual(c.get("teamsWebMaxChats"), 200, name)


class ConfigTemplate(unittest.TestCase):
    """(8) 배포 템플릿 — noticeSenders 일반어만 · 사용자 결정 전 기본값은 LM24 동작 · 새 키 일괄"""

    def test_template(self):
        c = _cfg("config.default.json")
        ns = c.get("noticeSenders") or []
        self.assertTrue(ns)
        self.assertEqual([x for x in ns if x.lower() not in GENERIC_NOTICE], [])
        mm = c["mm"]
        self.assertEqual(mm["shareBasis"], "weight")
        self.assertIsInstance(mm["eveningCredit"], bool)
        # eveningMode·offhoursSkeletonPadMin(±30분 꼬리)는 사용자 지시(2026-10-07 — 퇴근 경계~산출물 시각 전체 인정)로
        # 키 없이 eveningCredit + pcFloorWindow 로 대체됐다 — 다시 생기면 안 된다
        self.assertNotIn("eveningMode", mm)
        self.assertNotIn("offhoursSkeletonPadMin", mm)
        self.assertEqual(mm["pcFloorWindow"], [8, 19])
        self.assertEqual(mm["nightWindow"], [22, 6])
        self.assertEqual(mm["privateRunMin"], 30)
        self.assertEqual(c["collect"], {"cursorEpoch": 1, "mailAllPaths": False})
        self.assertEqual(c["outlook"], {"subfolders": True, "attachWaitSec": 120, "ostStaleH": 72})
        self.assertEqual(c["owaTimeRecoverMax"], 150)
        self.assertEqual((c["teamsWebMaxScroll"], c["teamsWindowRawDump"]), (60, False))
        self.assertEqual(c["pcHints"], {"includeSynced": False})
        self.assertEqual(c["privacy"], {"customers": [], "partners": [], "allowPatterns": [], "maskCodenames": False})
        self.assertEqual(c["episodeTop"], 50)
        ca = c["copilotAuto"]
        self.assertEqual((ca["inProcess"], ca["requireWorkAccount"], ca["keepEdgeOpen"]), (True, True, False))
        self.assertEqual(c["agentic"], {"domainHint": ""})

    def test_dev_copy_only_four_keys(self):
        p = os.path.join(ROOT, "config", "config.json")
        if not os.path.isfile(p):
            self.skipTest("개발 사본 config.json 없음")
        c = _cfg("config.json")
        for k in ("collect", "outlook", "privacy", "pcHints", "agentic", "episodeTop"):
            self.assertNotIn(k, c, f"개발 사본에는 새 키를 넣지 않는다(cfg.get 기본값으로 읽는다): {k}")


class PsLmName(unittest.TestCase):
    """(9) --ps: Get-LmH6 가 같은 고정 리터럴을 낸다"""

    def test_ps_same_h6(self):
        r = _boot.ps_result("LmName")
        if r is None:
            self.skipTest("PowerShell 결과 없음 — tests\\run_tests.py --ps 로 실행")
        self.assertNotIn("error", r, r)
        for k in ("h6_plain", "h6_slash", "h6_case", "h6_fwd"):
            self.assertEqual(r[k], FIXED_H6, k)
        self.assertEqual(r["norm"], lmname.norm_root(FIXED_PATH))
        self.assertEqual(r["names_h6"], lmname.names(FIXED_PATH)["H6"])
        self.assertEqual(r["root_h6"], lmname.H6, "설치 폴더(한글 경로) 해시가 Python 과 다르다")


if __name__ == "__main__":
    unittest.main()
