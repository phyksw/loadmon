# -*- coding: utf-8 -*-
"""WP-31 내보내기(R §9.1 · §9.3 · §9.4 · 계약 §9.2 · G-R1 · G-R4~G-R6 · RPT-30 · RPT-32 · RPT-33 · RPT-34).

- 폴더 `out\\personal\\<from>_<to>_<run8>\\`: report_full.html · report_redacted.html · report_model(_redacted).json ·
  csv_full\\·csv_redacted\\ 15종 · manifest.json(lm27.export/1).
- CSV: UTF-8 BOM + CRLF, 한글 열 이름, 수식 주입 방어(`= + - @ 탭 CR` 앞에 `'`).
- HTML: 데이터 섬에 `<`·`>`·`&`·U+2028·U+2029 원문자 0, 외부 참조 0, 같은 입력이면 `built` 주석 한 줄만 다르다.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import unittest
from datetime import UTC, datetime

from lm27.report import export as EX
from lm27.report import model as M
from lm27.util import fsx
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


NOW = datetime(2026, 10, 5, 1, 21, 44, tzinfo=UTC)
NOW2 = datetime(2026, 10, 6, 2, 0, 0, tzinfo=UTC)
EVIL_TITLE = "</script><img src=x onerror=alert(1)>"
EVIL_NAME = "<svg onload=alert(1)>"


def island_of(html: str, ident: str) -> str:
    m = re.search(r'<script type="application/json" id="' + ident + r'">(.*?)</script>', html, re.S)
    assert m, ident
    return m.group(1)


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.cfg = W.cfg()
        cls.srun = R.rich_run(title_over={"u_a1": EVIL_TITLE, "u_a2": "=1+1", "u_a3": "-합계", "u_a4": "@SUM(A1)"})
        cls.srun.person_dir["people"][R.PEER3]["names"] = [EVIL_NAME]
        cls.srun.registry["projects"][0]["name"] = "과제A 둘째 줄"
        cls.srun.write(cls.t.paths)
        cls.inp = cls.srun.inputs(cls.t.paths, cls.cfg)
        cls.res = EX.export(R.RUN_ID, None, None, None, paths=cls.t.paths, cfg=cls.cfg, inputs=cls.inp, now=NOW,
                            fallback=no_fallback)
        cls.out = os.fspath(cls.t.paths.out_personal("2026-08-01", "2026-10-04", R.RUN_ID))

    @classmethod
    def tearDownClass(cls):
        cls.t.cleanup()

    def read(self, rel) -> bytes:
        with open(os.path.join(self.out, *rel.split("/")), "rb") as fh:
            return fh.read()

    def test_files_and_manifest(self):
        res = self.res
        self.assertEqual(res.rc, 0, res.failed)
        self.assertEqual(res.out_dir, "out/personal/2026-08-01_2026-10-04_" + R.RUN_ID[-8:])
        paths = sorted(f["path"] for f in res.files)
        expect = sorted(["report_full.html", "report_redacted.html", "report_model.json", "report_model_redacted.json"]
                        + [f"csv_full/{n}" for n in EX.CSV_NAMES] + [f"csv_redacted/{n}" for n in EX.CSV_NAMES])
        self.assertEqual(paths, expect)
        self.assertEqual(len(EX.CSV_NAMES), 15)
        man = json.loads(self.read("manifest.json"))
        self.assertEqual(man["schema"], "lm27.export/1")
        self.assertEqual(man["built_at"], "2026-10-05T10:21:44+09:00")
        for f in man["files"]:
            data = self.read(f["path"])
            self.assertEqual(f["bytes"], len(data))
            self.assertEqual(f["sha256"], fsx.sha256_hex(data))
        self.assertEqual(json.loads(self.read("report_model.json"))["variant"], "full")
        self.assertEqual(json.loads(self.read("report_model_redacted.json"))["variant"], "redacted")

    def test_csv_format_and_injection(self):
        """RPT-32: BOM·CRLF, 수식 주입 방어."""
        raw = self.read("csv_full/units.csv")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
        self.assertEqual(rows[0][:3], ["단위업무 ID", "제목", "제목 출처"])
        titles = {r[0]: r[1] for r in rows[1:]}
        self.assertEqual(titles["u_a2"], "'=1+1")
        self.assertEqual(titles["u_a3"], "'-합계")
        self.assertEqual(titles["u_a4"], "'@SUM(A1)")
        self.assertEqual(titles["u_a1"], EVIL_TITLE)
        mon = list(csv.reader(io.StringIO(self.read("csv_full/monthly.csv").decode("utf-8-sig"), newline="")))
        self.assertEqual(mon[0][0], "월")
        sep = next(r for r in mon if r[0] == "2026-09")
        model = json.loads(self.read("report_model.json"))
        m9 = next(x for x in model["months"] if x["m"] == "2026-09")
        self.assertEqual(sep[3], str(m9["env_min"]))
        self.assertEqual(sep[12], M.F.fmt_mm(m9["env_min"], m9["denom_min"]))   # MM 은 fmt 표시 함수 글자
        for name in EX.CSV_NAMES:
            data = self.read("csv_redacted/" + name)
            self.assertTrue(data.startswith(b"\xef\xbb\xbf"), name)
            self.assertGreaterEqual(len(list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))), 1)
        nobom = EX.csv_bytes(["a"], [["=x"], [-3], [1.5], [None], [True]], bom=False)
        self.assertEqual(nobom, b"a\r\n'=x\r\n-3\r\n1.5\r\n\"\"\r\nY\r\n")      # 빈 칸 하나뿐인 줄은 csv 규칙대로 ""

    def test_island_escape(self):
        """RPT-30 · G-R6: 악성 문자열은 섬에서 `\\u003c` 등으로만 나오고 JSON 뜻은 그대로."""
        for name in ("report_full.html", "report_redacted.html"):
            html = self.read(name).decode("utf-8")
            for ident in ("lm27-data", "lm27-drill"):
                isl = island_of(html, ident)
                self.assertFalse(re.search(r"[<>&  ]", isl), (name, ident))
                json.loads(isl)
            self.assertEqual(len(re.findall(r"^<script", html, re.M)), 5)
            self.assertEqual(len(re.findall(r"(?i)</script", html)), 5)            # 자원 안에는 '</script' 0(G-R6)
        data = json.loads(island_of(self.read("report_full.html").decode("utf-8"), "lm27-data"))
        self.assertEqual(next(u["title"] for u in data["units"] if u["unit_id"] == "u_a1"), EVIL_TITLE)
        self.assertIn(EVIL_NAME, [p["name"] for p in data["refs"]["people"].values()])
        self.assertEqual(EX.island({"a": "< &>"}), '{"a":"\\u003c\\u2028\\u0026\\u003e"}')

    def test_no_external_refs_and_forbidden(self):
        """RPT-34 · RPT-33: 외부 자원 참조 0, '대체 가능'·'절감'·'AX 가능 MM' 0."""
        ext = re.compile(r"(?i)(?:src|href)\s*=\s*['\"](?:https?:)?//|url\(\s*['\"]?(?:https?:)?//|@import")
        for f in self.res.files:
            text = self.read(f["path"]).decode("utf-8-sig")
            if f["format"] == "html":
                self.assertFalse(ext.search(text), f["path"])
                self.assertIn('<svg hidden aria-hidden="true" focusable="false"><defs>', text)
                self.assertIn('<symbol id="i-ok"', text)
            for p in EX.FORBIDDEN:
                self.assertNotIn(p, text, f["path"])
        self.assertFalse([w for w in self.res.warnings if w["code"] == "forbidden_phrase"])

    def test_html_shell(self):
        html = self.read("report_full.html").decode("utf-8")
        self.assertTrue(html.startswith("<!doctype html>\n<html lang=\"ko\">"))
        self.assertIn('<body data-variant="full" data-kind="personal">', html)
        self.assertIn(f"<!-- LM27 report/1 · run {R.RUN_ID} · built 2026-10-05T10:21:44+09:00 -->", html)
        self.assertIn("전체판(로컬 전용)", html)
        self.assertIn("내 PC 밖으로 보내지 마세요", html)
        red = self.read("report_redacted.html").decode("utf-8")
        self.assertIn('data-variant="redacted"', red)
        self.assertNotIn('<p class="alert alert-warn" role="note">', red)
        drill = json.loads(island_of(red, "lm27-drill"))
        for u in drill["units"].values():
            self.assertNotIn("evidence", u)                              # 가림판: 증거 줄 없음(R §6.10.3)
        full_drill = json.loads(island_of(html, "lm27-drill"))
        self.assertTrue(full_drill["units"]["u_a1"]["evidence"])
        self.assertIn("2026-09-02", full_drill["days"])

    def test_g_r1_only_built_line_differs(self):
        """G-R1: 같은 입력의 두 내보내기는 HTML 의 built 주석 한 줄만 다르다(모델·CSV 는 같은 바이트)."""
        t2 = R.TmpRoot()
        self.addCleanup(t2.cleanup)
        self.srun.write(t2.paths)
        inp2 = self.srun.inputs(t2.paths, self.cfg)
        out2 = os.path.join(t2.root, "exp2")
        res2 = EX.export(R.RUN_ID, None, None, out2, paths=t2.paths, cfg=self.cfg, inputs=inp2, now=NOW2,
                         fallback=no_fallback)
        self.assertEqual(res2.rc, 0)
        for f in res2.files:
            with open(os.path.join(out2, *f["path"].split("/")), "rb") as fh:
                b2 = fh.read()
            b1 = self.read(f["path"])
            if f["format"] != "html":
                self.assertEqual(b1, b2, f["path"])
                continue
            l1, l2 = b1.decode("utf-8").split("\n"), b2.decode("utf-8").split("\n")
            diff = [i for i, (x, y) in enumerate(zip(l1, l2, strict=True)) if x != y]
            self.assertEqual(len(diff), 1, f["path"])
            self.assertTrue(l1[diff[0]].startswith("<!-- LM27 report/1 · run "))

    def test_assets_guard(self):
        """G-R6: 인라인 자원에 '</script' 가 있으면 만들지 않는다."""
        class BadPaths(R.TPaths):
            def web_file(self, rel):
                return R.REPO.joinpath("web", *rel.split("/")) if not rel.endswith("lm27ui.js") else \
                    os.path.join(self.root, "bad.js")
        bp = BadPaths(self.t.root, lad=os.path.join(self.t.root, "lad"))
        fsx.atomic_write(os.path.join(self.t.root, "bad.js"), b"var s = '</scr' + 'ipt>';\nvar t = '</script>';\n")
        with self.assertRaises(EX.ExportError):
            EX.load_assets(bp)
        with self.assertRaises(EX.ExportError):
            EX.render_html("{}", "{}", variant="full", run_id="../x", built_at="2026-10-05T10:21:44+09:00",
                           assets={"css": "", "icons": "", "charts": "", "ui": "", "report": ""})
        with self.assertRaises(EX.ExportError):
            EX.render_html("{\"a\":\"<\"}", "{}", variant="full", run_id=R.RUN_ID,
                           built_at="2026-10-05T10:21:44+09:00",
                           assets={"css": "", "icons": "", "charts": "", "ui": "", "report": ""})

    def test_choose_formats_variants(self):
        t2 = R.TmpRoot()
        self.addCleanup(t2.cleanup)
        self.srun.write(t2.paths)
        out2 = os.path.join(t2.root, "only")
        res = EX.export(R.RUN_ID, ["json"], ["redacted"], out2, paths=t2.paths, cfg=self.cfg,
                        inputs=self.srun.inputs(t2.paths, self.cfg), fallback=no_fallback, now=NOW)
        self.assertEqual([f["path"] for f in res.files], ["report_model_redacted.json"])
        with self.assertRaises(ValueError):
            EX.export(R.RUN_ID, ["pdf"], None, out2, paths=t2.paths, cfg=self.cfg)
        cfg2 = self.cfg.derive({"report.export.formats": ["csv"], "report.export.variants": ["full"],
                                "report.csv.bom": False})
        res = EX.export(R.RUN_ID, None, None, os.path.join(t2.root, "d"), paths=t2.paths, cfg=cfg2,
                        inputs=self.srun.inputs(t2.paths, cfg2), fallback=no_fallback, now=NOW)
        self.assertEqual({f["format"] for f in res.files}, {"csv"})
        with open(os.path.join(t2.root, "d", "csv_full", "daily.csv"), "rb") as fh:
            self.assertFalse(fh.read().startswith(b"\xef\xbb\xbf"))        # report.csv.bom = false

    def test_paths_methods_missing_rc1(self):
        """분석·내보내기 하위 경로 메서드가 아직 `lm27.paths` 에 없으면(CR) rc 1 + 한국어 한 줄(예외로 죽지 않는다)."""
        from lm27.paths import Paths

        class Old(Paths):                   # W2 통합: 실제 Paths 에는 메서드가 생겼다 — 옛 판을 흉내 낸다
            analysis_time_file = None
            analysis_report_file = None
            analysis_report = None
            out_personal_file = None
        p = Old(self.t.root, lad=os.path.join(self.t.root, "lad"))
        res = EX.export(R.RUN_ID, ["json"], ["full"], None, paths=p, cfg=self.cfg)
        self.assertEqual(res.rc, 1)
        self.assertIn("Paths.", res.failed[0]["reason"])

    def test_builds_model_when_missing(self):
        """모델이 없으면 먼저 만든다(R §2.4.3 — 판이 다르거나 없으면 다시 만들기)."""
        t2 = R.TmpRoot()
        self.addCleanup(t2.cleanup)
        self.srun.write(t2.paths)
        self.assertFalse(os.path.exists(t2.paths.analysis_report_file(R.RUN_ID, "report_model.json")))
        res = EX.export(R.RUN_ID, ["json"], ["full"], os.path.join(t2.root, "x"), paths=t2.paths, cfg=self.cfg,
                        inputs=self.srun.inputs(t2.paths, self.cfg), fallback=no_fallback, now=NOW)
        self.assertEqual(res.rc, 0)
        self.assertTrue(os.path.exists(t2.paths.analysis_report_file(R.RUN_ID, "report_model.json")))
        os.remove(t2.paths.analysis_time_file(R.RUN_ID, "tasks.json"))
        os.remove(t2.paths.analysis_report_file(R.RUN_ID, "report_model.json"))
        res = EX.export(R.RUN_ID, ["json"], ["full"], os.path.join(t2.root, "y"), paths=t2.paths, cfg=self.cfg,
                        fallback=no_fallback, now=NOW)
        self.assertEqual(res.rc, 1)
        self.assertIn("시간 결과", res.failed[0]["reason"])


if __name__ == "__main__":
    unittest.main()
