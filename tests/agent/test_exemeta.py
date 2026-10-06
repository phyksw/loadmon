# -*- coding: utf-8 -*-
"""WP-13 미지 프로그램 메타 시험 — ``lm27.agent.exemeta``(계약 §3.9 · CP §6.3 · X-024 · REQ-05 · T-07).

합성 판 정보·서명자(있음/없음)로 ``observe_exe`` 가 ``guess_cat``·``guess_kind``·``source`` 를 채우고, 저장 문자열은 정제 통과값
(사전 가명화·카나리아 0)이며, ``exe_meta.json`` 은 원자 쓰기·처음 본 시각 유지. 실기계 판독기는 동봉 파이썬(우리 파일)에만 쓴다.
"""
import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from lm27.agent import exemeta as E
from lm27.privacy import context as C
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp13 import helpers as H

NOW = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)


class Reader:
    def __init__(self, vi=None, signer=""):
        self.vi, self.sg = vi or {}, signer

    def version_info(self, path):
        return dict(self.vi)

    def signer(self, path):
        return self.sg


class ObserveTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        obj = C.context_cache_obj(self.sb.paths, self.sb.cfg(), kr=H.keyring(), registry=H.REGISTRY, calendar={},
                                  local=C.LocalOnly(), os_names=H.OS_NAMES)
        self.sctx = C.contexts_from_cache(obj, H.keyring())[0]

    def test_signer_wins(self):
        m = E.observe_exe(r"C:\Tools\solverx.exe", reader=Reader({"company": "Example Ltd", "product": "Solver X",
                                                                  "desc": "x", "ver": "2024.1"}, "ANSYS, Inc."),
                          sctx=self.sctx, now=NOW)
        self.assertEqual((m.exe, m.guess_cat, m.guess_kind, m.source, m.ver), ("solverx.exe", "해석", "상용", "signer", "2024.1"))
        self.assertEqual(m.first_seen, "2026-10-05T02:00:00Z")
        self.assertEqual(m.signer, "[회사]")                               # 회사 접미 가림(정제 통과값)

    def test_company_only_and_none(self):
        m = E.observe_exe("C:\\x\\cad.exe", reader=Reader({"company": "Dassault Systemes", "product": "Viewer"}), sctx=self.sctx)
        self.assertEqual((m.guess_cat, m.source, m.signer), ("CAD", "company", ""))
        m = E.observe_exe("C:\\x\\tool.exe", reader=Reader(), sctx=self.sctx)
        self.assertEqual((m.guess_cat, m.guess_kind, m.source, m.company, m.product, m.ver), ("", "", "none", "", "", ""))

    def test_inhouse_names_are_pseudonymized(self):
        m = E.observe_exe("C:\\x\\a.exe", reader=Reader({"company": "고객사A", "product": "과제A 해석 도구",
                                                         "desc": "과제A 전용", "ver": "1.0 beta"}), sctx=self.sctx)
        self.assertNotIn("과제A", m.product + m.desc)
        self.assertNotIn("고객사A", m.company)
        self.assertEqual(m.ver, "")                                       # 숫자·점이 아니면 비운다

    def test_canaries_never_stored(self):
        cs = [c for c in canaries(groups=("pii",), weak=False) if c.slot in ("text", "name", "title")][:8]
        sb = self.sb
        for i, c in enumerate(cs):
            m = E.observe_exe(f"C:\\x\\t{i}.exe", reader=Reader({"product": c.sentence, "desc": c.sentence,
                                                                "company": c.sentence}, c.sentence), sctx=self.sctx)
            E.save_exe_meta(sb.paths, "pc_0a1b2c3d4e5f6a7b", m)
        data = sb.paths.exe_meta("pc_0a1b2c3d4e5f6a7b").read_bytes()
        self.assertEqual(find_canaries(data, cs), [])


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.pc = "pc_0a1b2c3d4e5f6a7b"

    def test_schema_first_seen_and_atomic(self):
        p = self.sb.paths
        m1 = E.ExeMeta(exe="a.exe", product="A", first_seen="2026-10-01T00:00:00Z", source="none")
        self.assertTrue(E.save_exe_meta(p, self.pc, m1))
        self.assertFalse(E.save_exe_meta(p, self.pc, m1))                  # 같으면 다시 쓰지 않는다
        m2 = E.ExeMeta(exe="a.exe", product="A2", first_seen="2026-10-05T00:00:00Z", source="none")
        self.assertTrue(E.save_exe_meta(p, self.pc, m2))
        obj = json.loads(p.exe_meta(self.pc).read_text(encoding="utf-8"))
        self.assertEqual(obj["schema"], "lm27.exemeta/1")
        self.assertEqual(obj["a.exe"]["first_seen"], "2026-10-01T00:00:00Z")
        self.assertEqual(obj["a.exe"]["product"], "A2")
        self.assertEqual(E.load_exe_meta(p, self.pc)["a.exe"]["product"], "A2")
        self.assertEqual([x.name for x in p.exe_meta(self.pc).parent.iterdir() if x.name.endswith(".part")], [])
        with self.assertRaises(TypeError):
            E.save_exe_meta(p, self.pc, {"exe": "b.exe"})

    def test_bad_entries_dropped(self):
        p = self.sb.paths
        f = p.exe_meta(self.pc)
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"schema": "lm27.exemeta/1", "x.exe": {"product": "a\nb"}, "y.exe": {"product": "ok"},
                                 "notexe": {"product": "z"}}), encoding="utf-8")
        self.assertEqual(set(E.load_exe_meta(p, self.pc)), {"x.exe", "y.exe"})
        E.save_exe_meta(p, self.pc, E.ExeMeta(exe="z.exe"))
        self.assertEqual(set(E.load_exe_meta(p, self.pc)), {"y.exe", "z.exe"})


class RealReaderTest(unittest.TestCase):
    def test_bundled_python(self):
        """실기계 판독기 — 동봉 파이썬 실행 파일(우리 배포 파일)의 공개 판 정보·서명자."""
        exe = Path(sys.executable)
        r = E.WinVersion()
        vi = r.version_info(str(exe))
        self.assertEqual(vi.get("company"), "Python Software Foundation")
        self.assertRegex(vi.get("ver", ""), r"^3\.11")
        self.assertIn(r.signer(str(exe)), ("Python Software Foundation", ""))
        self.assertEqual(r.version_info(str(exe.parent / "없는파일.exe")), {})
        self.assertEqual(r.signer(str(exe.parent / "없는파일.exe")), "")


if __name__ == "__main__":
    unittest.main()
