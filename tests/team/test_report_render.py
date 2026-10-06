# -*- coding: utf-8 -*-
"""WP-37 자기완결 팀 보고서(R §9.4 · TAB §3.9) — 데이터 섬 이스케이프(TAB-S06 · G-R6) · 공유판 제거 키 0회(RPT-44)
· 외부 참조 0(G-R5) · 고정 껍데기(G-R4) · 결정성(G-R1) · 드릴다운 섬 상한(R §7.8.2) · 인라인 금지 글자열(빌드 실패).
"""
import copy
import json
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from lm27.config import load_config
from lm27.paths import Paths
from lm27.team import report as R
from tests.fixtures.wp37 import teamdata as T

TREE = Path(__file__).resolve().parents[2]
EVIL = "</script><!--<script>"                               # TAB-S06 악성 라벨(합성)


class Scan(HTMLParser):
    """시작 태그·섬 글자를 모은다(스크립트 안 글자는 CDATA — 태그로 세지 않는다)."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tags, self.islands, self._cur = [], {}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag == "script" and a.get("type") == "application/json":
            self._cur = a.get("id")
            self.islands[self._cur] = ""

    def handle_endtag(self, tag):
        if tag == "script":
            self._cur = None

    def handle_data(self, data):
        if self._cur:
            self.islands[self._cur] += data


def scan(html):
    p = Scan()
    p.feed(html)
    p.close()
    return p


def island_of(td, details):
    td = copy.deepcopy(td)
    td["interpretation"] = R.interpret(td, load_config())
    isl = dict(td)
    isl["details"] = copy.deepcopy(details)
    return isl


class RenderCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.td, cls.det = T.team8()
        cls.island = island_of(cls.td, cls.det)
        cls.full = R.render_team_report(cls.island, share=False, cfg=cls.cfg)
        cls.share = R.render_team_report(cls.island, share=True, cfg=cls.cfg)


class TestShell(RenderCase):
    def test_fixed_shell_and_islands(self):
        """고정 껍데기: 제목 고정·data-kind=team·변형 표시·섬 2개(lm27-data·lm27-detail)·인라인 스크립트 3개(G-R4)."""
        for html, variant in ((self.full, "full"), (self.share, "share")):
            p = scan(html)
            self.assertIn("<title>LM27 팀 보고서</title>", html)
            body = [a for t, a in p.tags if t == "body"][0]
            self.assertEqual(body, {"data-kind": "team", "data-variant": variant})
            scripts = [a for t, a in p.tags if t == "script"]
            self.assertEqual([a.get("id") for a in scripts], ["lm27-data", "lm27-detail", None, None, None])
            self.assertEqual(sorted(p.islands), ["lm27-data", "lm27-detail"])
            ids = {a.get("id") for _t, a in p.tags if a.get("id")}
            self.assertTrue({"team-root", "team-head", "team-nav", "app"} <= ids)
            self.assertEqual(html.count("<style>"), 1)

    def test_no_external_reference(self):
        """G-R5: http(s)·// 자원 참조·웹 글꼴·@import 0."""
        for html in (self.full, self.share):
            self.assertIsNone(re.search(r"(?i)(?:src|href)\s*=\s*['\"](?:https?:)?//", html))
            self.assertIsNone(re.search(r"(?i)url\(\s*['\"]?(?:https?:)?//", html))
            self.assertNotIn("@import", html)
            self.assertNotIn("@font-face", html)
            hosts = set(re.findall(r"https?://([\w.-]+)", html))
            self.assertTrue(hosts <= {"www.w3.org"}, hosts)              # SVG 이름공간 글자뿐

    def test_comment_line_and_determinism(self):
        """G-R1: 같은 입력·설정이면 같은 바이트. 머리 주석은 형식 검사를 통과한 세대·시각만."""
        self.assertEqual(R.render_team_report(self.island, cfg=self.cfg), self.full)
        self.assertIn("<!-- LM27 team report · gen 12 · built 2026-10-05T10:21:44+09:00 -->", self.full)
        bad = dict(self.island)
        bad["built_at"] = "2026-10-05 --> <script>x"
        bad["gen"] = "12"
        html = R.render_team_report(bad, cfg=self.cfg)
        self.assertIn("<!-- LM27 team report -->", html)

    def test_sprite_inlined_from_icons(self):
        """R §8.2.9: 자기완결 HTML 은 icons.svg 의 symbol 을 그대로 인라인(주석·외부 참조 없이)."""
        icons = re.sub(r"<!--.*?-->", "", (TREE / "web" / "common" / "icons.svg").read_text("utf-8"), flags=re.S)
        syms = re.findall(r"<symbol\b[^>]*>.*?</symbol>", icons, re.S)
        self.assertGreaterEqual(len(syms), 20)
        for s in syms:
            self.assertIn(s, self.full)
        self.assertEqual(self.full.count("<symbol "), len(syms))

    def test_inline_assets_are_the_web_files(self):
        """인라인 스크립트·스타일 = web\\common\\{lm27ui.js, lm27charts.js, lm27.css} · web\\team\\team.js 그대로."""
        for rel in ("common/lm27ui.js", "common/lm27charts.js", "team/team.js", "common/lm27.css"):
            self.assertIn((TREE / "web" / Path(rel)).read_text("utf-8"), self.full)


class TestIslands(RenderCase):
    def test_island_escape_and_roundtrip(self):
        """섬 글자에 < > & U+2028 U+2029 원문자 0, JSON 으로 되읽으면 표시 메타를 채운 team_data · details."""
        for html in (self.full, self.share):
            p = scan(html)
            for text in p.islands.values():
                for ch in ("<", ">", "&", "\u2028", "\u2029"):
                    self.assertNotIn(ch, text)
            td = json.loads(p.islands["lm27-data"])
            self.assertEqual(td["schema"], "lm27.teamdata/1")
            self.assertEqual(td["view"], {"small_project_mm": 0.3, "gantt_expand_rows": 150})
            self.assertEqual({d["code"]: d["name"] for d in td["domains"]}["EXT"], "외부 업무지원")
            self.assertEqual([r["code"] for r in td["interpretation"]], ["TI-01", "TI-02", "TI-04", "TI-07", "TI-08"])
            det = json.loads(p.islands["lm27-detail"])
            self.assertEqual(sorted(det), sorted(self.det))
            self.assertIn("name", det[sorted(det)[0]]["workflow"]["steps"][0])

    def test_tab_s06_malicious_labels(self):
        """TAB-S06: 라벨·제목·니즈 이름·팀 이름에 '</script><!--<script>' — 섬은 \\u003c 로, 스크립트 요소는 늘지 않는다."""
        td = copy.deepcopy(self.td)
        det = copy.deepcopy(self.det)
        td["team_label"] = EVIL
        td["people"][0]["label"] = EVIL
        td["gantt"][0]["units"][0]["title"] = EVIL
        td["agentic"]["needs"][0]["label"] = EVIL
        td["projects"][0]["label"] = EVIL + "&amp;\u2028\u2029"
        first = sorted(det)[0]
        det[first]["person"]["label"] = EVIL
        det[first]["workflow"]["steps"][0]["label"] = EVIL
        for share in (False, True):
            html = R.render_team_report(island_of(td, det), share=share, cfg=self.cfg)
            self.assertNotIn(EVIL, html)
            self.assertNotIn("<!--<script", html)
            p = scan(html)
            self.assertEqual(sum(1 for t, _a in p.tags if t == "script"), 5)
            self.assertEqual(html.count("</script>"), 5)
            back = json.loads(p.islands["lm27-data"])
            self.assertEqual(back["team_label"], EVIL)                    # 값은 그대로(글자로만 그린다)
            self.assertEqual(back["people"][0]["label"], EVIL)
            self.assertEqual(json.loads(p.islands["lm27-detail"])[first]["person"]["label"], EVIL)
            self.assertIn("\\u003c/script\\u003e\\u003c!--\\u003cscript\\u003e", html)

    def test_island_text_function(self):
        s = R.island_text({"a": "<b>&\u2028\u2029", "k": [1, 2]})
        self.assertEqual(s, '{"a":"\\u003cb\\u003e\\u0026\\u2028\\u2029","k":[1,2]}')
        self.assertEqual(json.loads(s), {"a": "<b>&\u2028\u2029", "k": [1, 2]})


class TestShareVariant(RenderCase):
    def test_removed_keys_zero_in_share_html(self):
        """RPT-44 · TAB §3.9 관문: 공유판에서 뺀 사람별 열(로드율·가용일·꼬리표 분) 키가 HTML 전체에 0회.
        꼬리표 키 이름은 인라인한 공용 렌더러(lm27charts.js) 코드에만 있다 — 섬에는 0회."""
        lib = sum((TREE / "web" / "common" / n).read_text("utf-8").count("by_tag") for n in ("lm27charts.js", "lm27ui.js"))
        team_js = (TREE / "web" / "team" / "team.js").read_text("utf-8")
        for k in R.SHARE_DROP_KEYS:
            self.assertEqual(team_js.count(k), 0, k)                         # 화면 JS 도 키 이름을 글자로 갖지 않는다
            self.assertGreater(self.full.count(k), 0, k)
        self.assertEqual(self.share.count("load_pct"), 0)
        self.assertEqual(self.share.count("avail_days"), 0)
        self.assertEqual(self.share.count("by_tag"), lib)
        p = scan(self.share)
        for text in p.islands.values():
            for k in R.SHARE_DROP_KEYS:
                self.assertNotIn('"' + k + '"', text)

    def test_team_totals_survive(self):
        """공유판에도 팀 합계 꼬리표 분(초과 근무 KPI)은 남는다 — tag_totals = 사람별 꼬리표의 정수 합."""
        td = json.loads(scan(self.share).islands["lm27-data"])
        tt = td["tag_totals"]
        want = dict.fromkeys(R.TAGS, 0)
        for p in self.td["people"]:
            for e in p["months"]:
                for t in R.TAGS:
                    want[t] += e["by_tag"][t]
        self.assertEqual(tt["total"], want)
        self.assertEqual(td["variant"], "share")
        for p in td["people"]:
            for e in p["months"]:
                self.assertIn("mm", e)
                self.assertIn("env_min", e)
        full = json.loads(scan(self.full).islands["lm27-data"])
        self.assertEqual(full["tag_totals"], tt)

    def test_strip_is_a_copy(self):
        before = copy.deepcopy(self.td)
        out = R.strip_for_share(self.td)
        self.assertEqual(self.td, before)
        self.assertNotIn("load_pct", out["people"][0]["months"][0])
        self.assertEqual(R.tag_totals(out), out["tag_totals"])            # 이미 빠진 자료는 있던 합계를 쓴다


class TestDetailsCap(unittest.TestCase):
    def test_build_details_cap_drops_units(self):
        """R §7.8.2: 드릴다운 섬이 상한을 넘으면 units 를 빼고 workflow 는 남긴다(units_omitted)."""
        _td, det = T.team8()
        small = R.build_details(det, None, max_bytes=10_000)
        for v in small.values():
            self.assertNotIn("units", v)
            self.assertTrue(v["units_omitted"])
            self.assertIn("steps", v["workflow"])
        big = R.build_details(det, None, max_bytes=50 * 1024 * 1024)
        for k, v in big.items():
            self.assertEqual(v["units"], det[k]["units"])
            self.assertNotIn("units_omitted", v)
        self.assertNotIn("name", det[sorted(det)[0]]["workflow"]["steps"][0])   # 입력은 바꾸지 않는다

    def test_render_reads_max_detail_mb(self):
        td, det = T.team8()
        pad = {f"{i}|r_{i:06x}": {"person": {"i": 0, "label": "팀원A"}, "role": {"role_id": f"r_{i:06x}"},
                                   "workflow": {"steps": [], "edges": []},
                                   "units": [{"unit_id": "u_0000000000", "title": "가" * 1000}] * 2}
               for i in range(700)}
        det.update(pad)
        isl = island_of(td, det)
        html = R.render_team_report(isl, cfg=load_config(overrides={"teamReport.maxDetailMb": 1}))
        d = json.loads(scan(html).islands["lm27-detail"])
        self.assertTrue(all(v.get("units_omitted") for v in d.values()))
        html2 = R.render_team_report(isl, cfg=load_config(overrides={"teamReport.maxDetailMb": 64}))
        self.assertFalse(any(v.get("units_omitted") for v in json.loads(scan(html2).islands["lm27-detail"]).values()))


class TestInlineGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm27t_wp37_"))
        shutil.copytree(TREE / "web", self.tmp / "web")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _render(self):
        td, det = T.team8()
        return R.render_team_report(island_of(td, det), cfg=load_config(), paths=Paths(self.tmp))

    def test_ok_with_copy(self):
        self.assertIn("<title>LM27 팀 보고서</title>", self._render())

    def test_close_script_in_js_fails_build(self):
        """G-R6: 인라인할 JS·CSS 에 '</script'·'</style'·'<!--' 가 있으면 만들지 않는다(빌드 실패)."""
        for rel, bad in (("team/team.js", "var x = '<" + "/script>';"), ("common/lm27.css", "/* <" + "/style> */"),
                         ("common/lm27ui.js", "// <" + "!-- x")):
            with self.subTest(rel=rel):
                p = self.tmp / "web" / Path(rel)
                orig = p.read_bytes()
                p.write_bytes(orig + b"\n" + bad.encode("utf-8") + b"\n")
                try:
                    with self.assertRaises(ValueError):
                        self._render()
                finally:
                    p.write_bytes(orig)

    def test_bad_sprite_fails_build(self):
        p = self.tmp / "web" / "common" / "icons.svg"
        orig = p.read_text("utf-8")
        p.write_text(orig.replace('<symbol id="i-ok" viewBox="0 0 20 20">',
                                  '<symbol id="i-ok" viewBox="0 0 20 20" onload="x()">'), "utf-8")
        with self.assertRaises(ValueError):
            self._render()


class TestInputs(unittest.TestCase):
    def test_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            R.render_team_report([], cfg=load_config())

    def test_island_input_not_mutated(self):
        td, det = T.team8()
        isl = island_of(td, det)
        snap = copy.deepcopy(isl)
        R.render_team_report(isl, share=True, cfg=load_config())
        self.assertEqual(isl, snap)

    def test_missing_interpretation_is_computed(self):
        td, det = T.team8()
        isl = dict(td)
        isl.pop("interpretation")
        isl["details"] = det
        html = R.render_team_report(isl, cfg=load_config())
        got = json.loads(scan(html).islands["lm27-data"])["interpretation"]
        self.assertEqual([r["code"] for r in got], ["TI-01", "TI-02", "TI-04", "TI-07", "TI-08"])


if __name__ == "__main__":
    unittest.main()
