# -*- coding: utf-8 -*-
r"""WP9 — 화면 기간 칩(분기·반기)·팀 호환(lm_ver·판 표시)·간트 드릴 id·팀 서버 주소 이름·표기 정리·자가점검 목록.

화면 서버(ui\app.py)는 띄우지 않는다 — quarter_range 는 소스에서 함수만 꺼내 같은 프로세스에서 부른다."""
import ast
import os
import re
import unittest

import _boot  # noqa: F401

ROOT = _boot.ROOT


def _read(rel, enc="utf-8-sig"):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return f.read().decode(enc)


def _code_strings(rel):
    """문서 문자열·주석을 뺀 문자열 상수 — 화면·보고서에 실제로 나갈 수 있는 글자."""
    tree = ast.parse(_read(rel))
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            docs.add(id(n.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _quarter_range():
    """ui\app.py 에서 PERIOD_SPANS 와 quarter_range 만 꺼내 실행한다(모듈 import 부작용 없음)."""
    src = _read(os.path.join("ui", "app.py"))
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PERIOD_SPANS" for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "quarter_range")]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "app_period", "exec"), ns)
    return ns["quarter_range"]


class PeriodChips(unittest.TestCase):
    def test_page_has_quarter_and_half_chips(self):
        src = _read(os.path.join("ui", "app.py"))
        for key, label in (("q1", "1분기"), ("q2", "2분기"), ("q3", "3분기"), ("q4", "4분기"),
                           ("h1", "상반기"), ("h2", "하반기")):
            self.assertIn(f'data-d="{key}">{label}<', src, key)

    def test_quarter_range_bounds(self):
        qr = _quarter_range()
        self.assertEqual(qr("2026-10-07", "q4"), ("2026-10-01", "2026-10-07"))   # 끝이 미래면 오늘로
        self.assertEqual(qr("2026-10-07", "h1"), ("2026-01-01", "2026-06-30"))
        self.assertEqual(qr("2026-10-07", "q1"), ("2026-01-01", "2026-03-31"))
        self.assertEqual(qr("2026-10-07", "ytd"), ("2026-01-01", "2026-10-07"))
        self.assertIsNone(qr("2026-03-15", "q2"))                                 # 아직 시작 안 한 기간
        self.assertIsNone(qr("2026-10-07", "zz"))

    def test_bat_menu_has_quarters(self):
        bat = _read("LoadMonitor28.bat", "cp949")
        for k in ("q1", "q2", "q3", "q4", "h1", "h2"):
            self.assertIn(f"DAYS={k}", bat)


class TeamCompat(unittest.TestCase):
    def test_member_carries_lm_ver(self):
        import teamup
        self.assertEqual(teamup.LM_VER, "LM28")
        self.assertIn('"lm_ver": LM_VER', _read("teamup.py"))

    def test_recalc_labels_lm28(self):
        import team_recalc
        meta = {"measure": {}, "coverage": {}}
        self.assertEqual(team_recalc.version_of(meta, {"lm_ver": "LM28", "tag": "t1"}, tag="t1"), "lm28")
        self.assertEqual(team_recalc.version_of(meta, {"lm_ver": "LM28", "tag": "t0"}, tag="t1"), "v3")  # 옛 기간 파일
        self.assertEqual(team_recalc.version_of(meta, {}), "v3")

    def test_gantt_anchor_stable(self):
        import team_report
        a = team_report.wf_anchor("홍길동", "과제A 설계")
        self.assertRegex(a, r"^wf-홍길동-[0-9a-f]{8}$")
        self.assertEqual(a, team_report.wf_anchor("홍길동", "과제A  설계"))       # 띄어쓰기 변형은 같은 id
        self.assertNotEqual(a, team_report.wf_anchor("김철수", "과제A 설계"))

    def test_team_server_address_names(self):
        import teamaddr
        self.assertEqual(teamaddr.EDIT_BAT, "LoadMonitor28-팀서버주소.bat")
        self.assertEqual((teamaddr.DEFAULT_PORT,), (9310,))                       # 팀 호환 — 기본 포트 불변
        bat = _read("LoadMonitor28-팀서버주소.bat", "cp949")
        self.assertIn("LM28_TA_HOST", bat)
        self.assertIn("LM28_TA_PORT", bat)
        self.assertNotIn("%LM28_TA_HOST%", bat)                                   # 입력값을 % 확장으로 끼우지 않는다


class Wording(unittest.TestCase):
    def test_no_replaceable_mm_in_ui_or_reports(self):
        for rel in (os.path.join("ui", "app.py"), "report_out.py", "team_report.py", "freeze.py"):
            hit = [s[:60] for s in _code_strings(rel) if "대체 가능 MM" in s]
            self.assertEqual(hit, [], rel)

    def test_hierarchy_wording(self):
        self.assertIn("업무 영역", _read("freeze.py"))


class SelfCheckList(unittest.TestCase):
    def test_need_files_exist_and_listed(self):
        src = _read("자가점검.py")
        node = next(n for n in ast.parse(src).body
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "NEED")
        need = ast.literal_eval(node.value)
        missing = [p for p in need if not os.path.exists(os.path.join(ROOT, p.replace("/", os.sep)))]
        self.assertEqual(missing, [])
        listed = [m.group(1) for m in (re.match(r"^(\S.*?)\s{2,}[\d,]+ B\s+[0-9a-f]{8}\s*$", ln)
                                       for ln in _read("FILES.txt").splitlines()) if m]
        self.assertEqual(sorted(set(need) - set(listed) - {"FILES.txt"}), [])   # FILES.txt 는 자기 줄에 크기·crc 가 없다


if __name__ == "__main__":
    unittest.main()
