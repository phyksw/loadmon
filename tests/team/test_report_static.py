# -*- coding: utf-8 -*-
"""WP-37 정적 파일 — 팀 대시보드·관리 셸(web\\team\\index.html · admin.html)과 화면 스크립트(web\\team\\team.js).

· 셸은 데이터 없는 껍데기: 인라인 스크립트·스타일 0(TAB §3.12 CSP script-src 'self' · style-src 'self'), 공용 렌더러 3개 +
  team.js 를 고정 사전 경로(/static/…)로만 부른다(X-279 — team.css 없음). 아이콘은 icons.svg 의 symbol 사본(같은지 대조).
· team.js: 금지 API 0(G-R4) · 16진 색 0(G-R7) · 외부 참조 0(G-R5) · '</script'·'</style'·'<!--' 0(G-R6) · 고전 스크립트(L-27)
  · 공유판 제거 키 이름 글자 0(TAB §3.9).
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from lm27.team import report as R
from lm27.team import server

TREE = Path(__file__).resolve().parents[2]
WEB = TREE / "web"
BANNED = (r"\binnerHTML\b", r"\bouterHTML\b", r"\binsertAdjacentHTML\b", r"\bdocument\.write", r"(?<![\w.])eval\s*\(",
          r"\bnew\s+Function\b", r"\bset(?:Timeout|Interval)\s*\(\s*['\"`]", r"\bDOMParser\b", r"\.toFixed\s*\(")


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.inline = [], []
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag in ("script", "style"):
            self._in = tag

    def handle_endtag(self, tag):
        self._in = None

    def handle_data(self, data):
        if self._in and data.strip():
            self.inline.append(self._in)


def parse(path: Path) -> Tags:
    p = Tags()
    p.feed(path.read_text("utf-8"))
    return p


def symbols(text: str) -> list[str]:
    return re.findall(r"<symbol\b[^>]*>.*?</symbol>", re.sub(r"<!--.*?-->", "", text, flags=re.S), re.S)


class TestShells(unittest.TestCase):
    def test_csp_safe_shells(self):
        for name, kind in (("index.html", "team"), ("admin.html", "team-admin")):
            with self.subTest(name=name):
                p = parse(WEB / "team" / name)
                self.assertEqual(p.inline, [], "인라인 스크립트·스타일 금지(CSP)")
                srcs = [a.get("src") for t, a in p.tags if t == "script"]
                self.assertEqual(srcs, ["/static/lm27ui.js", "/static/lm27charts.js", "/static/team.js"])
                css = [a.get("href") for t, a in p.tags if t == "link" and a.get("rel") == "stylesheet"]
                self.assertEqual(css, ["/static/lm27.css"])
                body = [a for t, a in p.tags if t == "body"][0]
                self.assertEqual(body.get("data-kind"), kind)
                ids = {a.get("id") for _t, a in p.tags if a.get("id")}
                self.assertTrue({"team-root", "team-head", "team-nav", "app"} <= ids)
                self.assertFalse(any(k.startswith("on") for _t, a in p.tags for k in a), "인라인 이벤트 속성 금지")
                self.assertFalse(any("style" in a for _t, a in p.tags), "style 속성 금지(CSP)")
                html = (WEB / "team" / name).read_text("utf-8")
                self.assertIn('<html lang="ko">', html)
                self.assertIn('<meta name="color-scheme" content="light">', html)
                self.assertIsNone(re.search(r"(?i)(?:src|href)\s*=\s*['\"](?:https?:)?//", html))

    def test_sprite_copy_matches_icons(self):
        """아이콘 스프라이트 사본 = web\\common\\icons.svg 의 symbol(바이트 같음 — 원본을 바꾸면 이 시험이 알린다)."""
        want = symbols((WEB / "common" / "icons.svg").read_text("utf-8"))
        self.assertGreaterEqual(len(want), 20)
        for name in ("index.html", "admin.html"):
            self.assertEqual(symbols((WEB / "team" / name).read_text("utf-8")), want, name)

    def test_server_static_dictionary_serves_these_files(self):
        """팀 서버 고정 사전(TAB §3.12 · 계약 §2.16)이 이 파일들을 가리키고, team.css 는 없다(X-279)."""
        self.assertEqual(server.STATIC["/"][0], "team/index.html")
        self.assertEqual(server.STATIC["/admin"][0], "team/admin.html")
        self.assertEqual(server.STATIC["/static/team.js"][0], "team/team.js")
        self.assertNotIn("/static/team.css", server.STATIC)
        for rel, _ctype in server.STATIC.values():
            self.assertTrue((WEB / Path(rel)).is_file(), rel)
        self.assertIn("sandbox allow-scripts", server.CSP_REPORT)
        self.assertNotIn("unsafe-inline", server.CSP_DASH)


class TestFixtureSync(unittest.TestCase):
    def test_node_fixture_matches_generator(self):
        """node 시험 자료(tests\\fixtures\\wp37\\team8.json) = 생성기 출력(바꿨으면 T.write_fixture() 로 다시 쓴다)."""
        from tests.fixtures.wp37 import teamdata as T
        self.assertEqual(T.FIXTURE.read_bytes(), T.fixture_bytes())


class TestTeamJs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (WEB / "team" / "team.js").read_text("utf-8")

    def test_no_banned_api(self):
        for pat in BANNED:
            self.assertIsNone(re.search(pat, self.text), pat)

    def test_no_hex_color_no_external(self):
        self.assertIsNone(re.search(r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])", self.text))
        self.assertIsNone(re.search(r"(?i)https?://(?!www\.w3\.org/)[\w.-]+", self.text))
        self.assertIsNone(re.search(r"(?i)</(?:script|style)|<!--", self.text))

    def test_classic_script(self):
        """L-27: ES module 문 0(import·export) — node --check 는 CommonJS 로 읽는다."""
        self.assertIsNone(re.search(r"(?m)^\s*(?:import\s+[\w{*]|export\s+(?:default|function|var|const|let|class|\{))", self.text))

    def test_share_keys_not_literal(self):
        """TAB §3.9: 공유판에 인라인되는 화면 JS 가 제거 키 이름을 글자로 갖지 않는다(조각으로 조립)."""
        for k in R.SHARE_DROP_KEYS:
            self.assertNotIn(k, self.text)


if __name__ == "__main__":
    unittest.main()
