# -*- coding: utf-8 -*-
"""WP-37 ↔ WP-27 실물 연결 — 취합기(aggregate)가 이 모듈로 해석 문장·자기완결 보고서를 만들고, 팀 서버가 셸·보고서·
드릴다운을 낸다. RPT-45(같은 역할 두 사람 — A 의 막대 = A 의 워크플로우, 자기완결 보고서의 details 섬도 같음).

합성 묶음은 WP-27 생성기(tests\\fixtures\\wp27 — 읽기만)로 만든다. 서버는 127.0.0.1 시험 포트에만 묶는다.
"""
import json
import re
import unittest
from html.parser import HTMLParser

from lm27.team import aggregate as A
from lm27.team import schema, server
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import running_server

PK1, PK2 = B.person_key(71), B.person_key(72)
RID = schema.role_id_of("P-0007", "ELEC", "DESIGN")


class Islands(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.islands, self._cur = {}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("type") == "application/json":
            self._cur = a.get("id")
            self.islands[self._cur] = ""

    def handle_endtag(self, tag):
        self._cur = None

    def handle_data(self, data):
        if self._cur:
            self.islands[self._cur] += data


def islands(html: str) -> dict:
    p = Islands()
    p.feed(html)
    return {k: json.loads(v) for k, v in p.islands.items()}


def two_people():
    """같은 역할(P-0007 · 회로 · 설계)을 하는 두 사람 — 워크플로우 단계 라벨·n 이 다르다."""
    a = B.make_bundle(PK1, "2026-08-01", "2026-09-30", built_at="2026-10-01T09:00:00+09:00", dense=True,
                      self_label="팀원A")
    b = B.make_bundle(PK2, "2026-08-01", "2026-09-30", built_at="2026-10-01T09:00:00+09:00", dense=True, seed=3,
                      self_label="팀원B")
    step = b["workflows"][0]["steps"][0]
    step["label"], step["n"] = "도면 확인", 1
    return a, b


class TestAggregateMakesReports(unittest.TestCase):
    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self.st = B.new_store(self.dir)

    def tearDown(self):
        self._td.__exit__(None, None, None)

    def test_reports_interpretation_and_details(self):
        a, b = two_people()
        for o in (a, b):
            r = B.put_bundle(self.st, o)
            self.assertTrue(r.ok, (r.code, r.detail))
        res = A.aggregate(self.st, 1)
        self.assertTrue(res.ok)
        self.assertFalse([w for w in res.warnings if "lm27.team.report" in w], res.warnings)   # 모듈이 있다
        codes = [x["code"] for x in res.td["interpretation"]]
        self.assertEqual(codes[0], "TI-01")
        self.assertTrue(set(codes) <= {"TI-01", "TI-02", "TI-03", "TI-04", "TI-05", "TI-06", "TI-07", "TI-08"})
        gd = self.st.gen_dir(1)
        full = (gd / "team_report.html").read_text("utf-8")
        share = (gd / "team_report_share.html").read_text("utf-8")
        self.assertIn("<title>LM27 팀 보고서</title>", full)
        self.assertGreater(full.count("load_pct"), 0)
        self.assertEqual(share.count("load_pct"), 0)
        self.assertEqual(share.count("avail_days"), 0)
        isl = islands(full)
        idx = {p["person_key"]: p["i"] for p in isl["lm27-data"]["people"]}
        det = isl["lm27-detail"]
        da, db = det[f"{idx[PK1]}|{RID}"], det[f"{idx[PK2]}|{RID}"]
        self.assertEqual((da["person"]["label"], da["workflow"]["steps"][0]["label"], da["workflow"]["steps"][0]["n"]),
                         ("팀원A", "요청 접수", 3))
        self.assertEqual((db["person"]["label"], db["workflow"]["steps"][0]["label"], db["workflow"]["steps"][0]["n"]),
                         ("팀원B", "도면 확인", 1))
        self.assertEqual(da["workflow"]["steps"][0]["name"], "의뢰 수신")       # 섬에는 단계 한글명이 채워진다
        dom = {d["code"]: d for d in isl["lm27-data"]["domains"]}
        self.assertEqual(dom["DEV"]["name"], "개발 프로젝트")
        self.assertRegex(dom["DEV"]["color"], r"^#[0-9a-f]{6}$")
        self.assertEqual(islands(share)["lm27-detail"].keys(), det.keys())   # 공유판도 같은 details


class TestServerServes(unittest.TestCase):
    def test_shell_static_report_and_detail(self):
        a, b = two_people()
        with B.temp_dir() as d, running_server(d) as ts:
            for o in (a, b):
                code, obj, _h = ts.post_bundle(o)
                self.assertEqual(code, 200, obj)
            for path, needle in (("/", "LM27 팀 대시보드"), ("/admin", "LM27 팀 서버 관리"), ("/static/team.js", "LM27Team")):
                code, body, hdr = ts.call("GET", path)
                self.assertEqual(code, 200, path)
                self.assertIn(needle, body.decode("utf-8"))
                self.assertEqual(hdr["Content-Security-Policy"], server.CSP_DASH)
            code, body, hdr = ts.call("GET", "/report")
            self.assertEqual(code, 200)
            self.assertEqual(hdr["Content-Security-Policy"], server.CSP_REPORT)
            self.assertIn("<title>LM27 팀 보고서</title>", body.decode("utf-8"))
            code, body, _hdr = ts.call("GET", "/report/share")
            self.assertEqual(code, 200)
            self.assertNotIn("load_pct", body.decode("utf-8"))
            for pk, want in ((PK1, "요청 접수"), (PK2, "도면 확인")):          # RPT-45 — 대시보드 드릴다운 API
                code, det, _hdr = ts.call("GET", f"/api/team/detail?person={pk}&role={RID}")
                self.assertEqual(code, 200)
                self.assertEqual(det["workflow"]["steps"][0]["label"], want)
            code, td, _hdr = ts.call("GET", "/api/team")
            self.assertEqual(code, 200)
            self.assertTrue(td["interpretation"])
            self.assertFalse([w for w in td["warnings"] if re.search(r"lm27\.team\.report", w)])


if __name__ == "__main__":
    unittest.main()
