# -*- coding: utf-8 -*-
"""정적 관문(이 WP 몫) — RPT-40 문구 규칙 · G-R10 단일 로더(AST) · L-20 배타 바인드 · 정적 고정 사전(R §2.3.4) ·
127.0.0.1 고정 · 원문 쓰기 0(open·print 없음). 저장소 파일을 읽기만 한다."""
import ast
import re
import unittest
from pathlib import Path

from lm27.ui import server as S

REPO = Path(__file__).resolve().parents[2]
UI = sorted((REPO / "lm27" / "ui").glob("*.py"))
WEB = sorted(p for p in (REPO / "web").rglob("*") if p.suffix in (".js", ".html", ".css", ".svg") and p.is_file())
BANNED = ("개발자" + "에게", "재" + "설치")                       # 금지 문구(런타임 조립 — R §5.0.4 · RPT-40)
DATA_RX = re.compile(r"^(?:data|out)[\\/]+\w", re.I)
DATA_M = {"data", "derived", "analysis", "analysis_time", "analysis_hier", "out_dir", "out_personal", "pcs", "pc_dir",
          "keys", "local_only", "hier_local", "team_dir", "outbox", "ai_run", "import_dir", "logs", "store_root",
          "store_dir", "collect_stage_results"}


def _trees():
    for p in UI:
        yield p, ast.parse(p.read_text(encoding="utf-8"), filename=str(p))


class StaticTest(unittest.TestCase):
    def test_rpt40_no_banned_phrases(self):
        for p in UI + WEB:
            t = p.read_text(encoding="utf-8")
            for w in BANNED:
                self.assertNotIn(w, t, f"{p.relative_to(REPO)}: 금지 문구")
        for p, tree in _trees():
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and "[!]" in n.value:
                    self.fail(f"{p.name}:{n.lineno} 성공 경로에 '[!]'")

    def test_gr10_no_data_path_assembly(self):
        for p, tree in _trees():
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and DATA_RX.match(n.value):
                    self.fail(f"{p.name}:{n.lineno} 데이터 경로 문자열 상수")
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                    left = n.left
                    while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
                        left = left.left
                    if isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute) and left.func.attr in DATA_M:
                        self.fail(f"{p.name}:{n.lineno} paths.{left.func.attr}() 뒤에 경로를 붙임")
                if isinstance(n, ast.Call):
                    f = n.func
                    name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
                    if name == "join" and n.args and isinstance(n.args[0], ast.Call) and \
                            isinstance(n.args[0].func, ast.Attribute) and n.args[0].func.attr in DATA_M:
                        self.fail(f"{p.name}:{n.lineno} os.path.join(paths.{n.args[0].func.attr}(), …)")

    def test_no_open_print_or_raw_writes(self):
        for p, tree in _trees():
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("open", "print"):
                    self.fail(f"{p.name}:{n.lineno} {n.func.id}( — 쓰기는 fsx·로그는 요청 줄만")
                if isinstance(n, ast.Attribute) and n.attr in ("write_text", "write_bytes", "FileHandler"):
                    self.fail(f"{p.name}:{n.lineno} {n.attr}")

    def test_l20_exclusive_bind_and_loopback(self):
        self.assertIs(S.UiHTTPServer.allow_reuse_address, False)
        self.assertEqual(S.HOST, "127.0.0.1")
        src = (REPO / "lm27" / "ui" / "server.py").read_text(encoding="utf-8")
        self.assertIn("SO_EXCLUSIVEADDRUSE", src)
        self.assertNotIn("SO_REUSEADDR", src)
        for p in UI:
            self.assertNotIn('"0.0.0.0"', p.read_text(encoding="utf-8").replace("teamServer", ""), p.name)

    def test_static_dictionary(self):
        self.assertEqual(S.STATIC, {
            "/": ("app/index.html", "text/html; charset=utf-8"),
            "/static/app.js": ("app/app.js", "text/javascript; charset=utf-8"),
            "/static/report.js": ("app/report.js", "text/javascript; charset=utf-8"),
            "/static/lm27charts.js": ("common/lm27charts.js", "text/javascript; charset=utf-8"),
            "/static/lm27ui.js": ("common/lm27ui.js", "text/javascript; charset=utf-8"),
            "/static/lm27.css": ("common/lm27.css", "text/css; charset=utf-8"),
            "/static/icons.svg": ("common/icons.svg", "image/svg+xml")})
        for rel, _ct in S.STATIC.values():
            self.assertTrue((REPO / "web" / rel).is_file(), rel)
        idx = (REPO / "web" / "app" / "index.html").read_bytes()
        self.assertIsNotNone(S._TOKEN_META_RX.search(idx), "index.html 의 토큰 meta 자리")

    def test_routes_cover_screen_calls(self):
        """화면(app.js·report.js)이 부르는 /api/* 경로가 모두 경로표에 있다(WP-36 ↔ WP-35 이음매)."""
        routes = S.build_routes()
        js = (REPO / "web" / "app" / "app.js").read_text(encoding="utf-8")
        calls = set(re.findall(r'api\.(get|post|put)\("(/api/[a-z0-9/\-]+)', js))
        calls |= set(re.findall(r'"(get|post|put)",\s*"(/api/[a-z0-9/\-]+)', js))      # send(scr, 카드, "post", "/api/…")
        self.assertGreater(len(calls), 50)
        samples = {"/api/jobs/": "j20261006000000abcd", "/api/analysis/run/": "20261005-101500-3fa2",
                   "/api/report/unit/": "u_a1a1a1a1a1", "/api/report/day/": "2026-09-03",
                   "/api/team/preview/": "x", "/api/team/approve/": "x", "/api/team/send/": "x",
                   "/api/team/drop/": "x", "/api/team/export/": "x"}
        for m, path in sorted(calls):
            full = path + samples.get(path, "") if path.endswith("/") else path
            if path == "/api/jobs/":
                full = path + samples[path] + "/cancel" if m == "post" else path + samples[path]
            ok = any(mm == m.upper() and rx.fullmatch(full) for mm, rx, _fn in routes)
            self.assertTrue(ok, f"{m.upper()} {full} 경로가 없음")


if __name__ == "__main__":
    unittest.main()
