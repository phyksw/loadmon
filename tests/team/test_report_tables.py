# -*- coding: utf-8 -*-
"""WP-37 팀 표 CSV(R §9.3.3 · 요청 T-5) — UTF-8 BOM + CRLF · 한글 열 이름 · 수식 주입 방어 · 숫자는 §3.1 표시 함수 글자 ·
공유판은 사람별 정규·연장·야간·휴일·가용일·로드율 열 없음. 쓰기는 취합기 몫(이 모듈은 바이트만 돌려준다).
"""
import copy
import csv
import io
import unittest

from lm27.team import report as R
from tests.fixtures.wp37 import teamdata as T

FILES = ["activity_types.csv", "agentic.csv", "domain_monthly.csv", "needs.csv", "person_monthly.csv",
         "project_people.csv", "quality.csv", "roles.csv", "units.csv"]


def rows_of(b: bytes) -> list[list[str]]:
    assert b.startswith(b"\xef\xbb\xbf")
    text = b[3:].decode("utf-8")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    return list(csv.reader(io.StringIO(text, newline="")))


class TestTeamTables(unittest.TestCase):
    def setUp(self):
        self.td, _det = T.team8()

    def test_files_encoding_and_heads(self):
        out = R.team_tables(self.td)
        self.assertEqual(sorted(out), FILES)
        for name in FILES:
            self.assertTrue(name.isascii())
            rows_of(out[name])
        pm = rows_of(out["person_monthly.csv"])
        self.assertEqual(pm[0], ["사람 라벨", "월", "MM", "근무(분)", "정규", "연장", "야간", "휴일", "가용일", "로드율",
                                 "측정 품질", "부분월"])
        self.assertEqual(len(pm) - 1, sum(len(p["months"]) for p in self.td["people"]))
        first = self.td["people"][0]["months"][0]
        self.assertEqual(pm[1][:4], ["팀원A", "2026-07", R.fmt_num(first["mm"], 2), str(first["env_min"])])
        self.assertEqual(pm[1][9], R.fmt_num(first["load_pct"], 0))
        dm = rows_of(out["domain_monthly.csv"])
        self.assertEqual(dm[0], ["영역", "월", "MM", "측정 불충분 몫 MM"])
        mp = [r for r in dm if r[0] == "양산 프로젝트"]                   # 측정 불충분 사람(팀원H)은 양산만 — 몫 > 0
        self.assertTrue(mp and all(float(r[3]) > 0 for r in mp))
        units = rows_of(out["units.csv"])
        self.assertEqual(len(units) - 1, sum(len(g["units"]) for g in self.td["gantt"]))
        roles = rows_of(out["roles.csv"])
        self.assertEqual(roles[0][-2:], ["중앙 리드(영업일)", "중앙 투입(분)"])

    def test_share_drops_person_columns(self):
        full = R.team_tables(self.td)
        share = R.team_tables(self.td, share=True)
        head = rows_of(share["person_monthly.csv"])[0]
        self.assertEqual(head, ["사람 라벨", "월", "MM", "근무(분)", "측정 품질", "부분월"])
        for k in FILES:
            if k != "person_monthly.csv":
                self.assertEqual(share[k], full[k], k)

    def test_formula_injection_defense(self):
        td = copy.deepcopy(self.td)
        td["people"][0]["label"] = "=HYPERLINK(1)"
        td["gantt"][0]["units"][0]["title"] = "@SUM(1)"
        td["agentic"]["needs"][0]["label"] = "-2+3"
        out = R.team_tables(td)
        self.assertEqual(rows_of(out["person_monthly.csv"])[1][0], "'=HYPERLINK(1)")
        self.assertIn("'@SUM(1)", [r[3] for r in rows_of(out["units.csv"])])
        self.assertIn("'-2+3", [r[1] for r in rows_of(out["needs.csv"])])

    def test_deterministic_and_pure(self):
        snap = copy.deepcopy(self.td)
        self.assertEqual(R.team_tables(self.td), R.team_tables(copy.deepcopy(self.td)))
        self.assertEqual(self.td, snap)


if __name__ == "__main__":
    unittest.main()
