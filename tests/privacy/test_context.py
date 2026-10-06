# -*- coding: utf-8 -*-
"""WP-11 문맥 시험 — 본인 이름 집합 단일원(X-306 · CT §4.4 원천·변형), 설정 검증(P §8.3 · §17.3 — bad_regex·allow_too_broad·
별칭), 정제 문맥 조립·사본(계약 §3.9 — 키 없음·해시), 프로그램/에이전트 동치(P-T7·T28), 키 없음 문맥(P-T29·T36), 로컬
사전 갱신(P §9.6), import 방향(X-304 — AST)."""
import ast
import json
import sys
import unittest
from unittest import mock

from lm27.privacy import context as C
from lm27.privacy import keys as K
from lm27.privacy import records as R
from lm27.privacy.detect import sanitize
from lm27.util import fsx
from tests.fixtures.wp11 import helpers as H


class _Audit:
    def __init__(self):
        self.c = {}

    def add(self, counter, key, n=1):
        self.c[f"{counter}.{key}"] = self.c.get(f"{counter}.{key}", 0) + n


def _local(people: dict) -> C.LocalOnly:
    return C.LocalOnly(person_dir={"format": C.PERSONDIR_FORMAT, "people": people})


class SelfNamesTest(unittest.TestCase):
    """X-306 · CT §4.4: 설정(person_dir self 이름·collect.ownerAddress) + OS 표시명 + 고정값, 변형 모두."""

    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_sources_and_variants(self):
        local = _local({"w" + "1" * 16: {"self": True, "names": ["홍 길동 님"]},
                        "w" + "2" * 16: {"self": False, "names": ["김철수"]}})
        cfg = self.sb.cfg(**{"collect.ownerAddress": "Hong.GD@corp.example"})
        got = set(C.self_name_set(local, cfg, ["HongTest", "홍길동씨"]))
        for want in ("홍 길동 님", "홍 길동", "홍길동님", "홍길동", "Hong.GD", "hong.gd", "HongTest", "hongtest",
                     "홍길동씨", "나", "본인", "you", "me"):
            self.assertIn(want, got)
        self.assertNotIn("김철수", got)
        self.assertEqual(sorted(got), C.self_name_set(local, cfg, ["HongTest", "홍길동씨"]))     # 결정적 정렬
        replay = set(C.self_name_set(local, cfg, ["HongTest"], replay=True))                # 원문이 타 PC → 설정만
        self.assertNotIn("HongTest", replay)
        self.assertIn("홍길동", replay)

    def test_os_display_names_fallback(self):
        with mock.patch.dict(C.os.environ, {"USERNAME": "hongtest"}), \
                mock.patch.object(C, "_logonui_display_name", return_value="홍길동"), \
                mock.patch.object(C, "_directory_display_name", side_effect=AssertionError("AD 조회 금지")):
            self.assertEqual(C.os_display_names(), ["hongtest", "홍길동"])
        with mock.patch.dict(C.os.environ, {"USERNAME": "hongtest"}), \
                mock.patch.object(C, "_logonui_display_name", return_value=""), \
                mock.patch.object(C, "_directory_display_name", return_value="홍길동 (과제A)") as d:
            self.assertEqual(C.os_display_names(), ["hongtest", "홍길동 (과제A)"])        # 설정·LogonUI 모두 없음
            self.assertEqual(C.os_display_names(have_settings=True), ["hongtest"])          # 설정이 있으면 AD 안 감
            self.assertEqual(d.call_count, 1)
        with mock.patch.object(C, "os_display_names", return_value=["osname"]) as f:
            C.self_name_set(_local({"w" + "1" * 16: {"self": True, "names": ["홍길동"]}}), self.sb.cfg())
            f.assert_called_once_with(have_settings=True)

    def test_text_self_names(self):
        self.assertEqual(C.text_self_names(["나", "본인", "Me", "홍", "홍길동", "hongtest"]), ["hongtest", "홍길동"])


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_allow_patterns(self):
        au = _Audit()
        ok = C.validate_allow_patterns([r"PRJ-\d{3}", "(", "", "x" * 201, r"a*", r"\d+", r".*@.*", r"사번\d{6}"], au)
        self.assertEqual(ok, [r"PRJ-\d{3}", r"사번\d{6}"])
        self.assertEqual(au.c, {"cfg.bad_regex": 4, "cfg.allow_too_broad": 2})

    def test_dictionary_validation(self):
        reg = {"customers": [{"id": "C01", "names": ["고객사A", "A", "회의", "고객사A"], "domains": ["@CustA.Example", "x"]},
                             {"id": "bad id!", "names": ["무시"]},
                             {"id": "C02", "names": ["고객사a"]}],
               "projects": [{"id": "P-0001", "codenames": ["과제A", "과제A2"]}], "internal_domains": ["Corp.Example"]}
        au = _Audit()
        local = _local({"w" + "a" * 16: {"names": ["김철수", "김", "남궁"]}, "w" + "b" * 16: {"self": True, "names": ["홍길동"]},
                        "bad": {"names": ["박영수"]}})
        ctx = C.build_context(self.sb.cfg(**{"privacy.allowPatterns": [r"PRJ-\d{3}"]}), reg, local, H.keyring(),
                              os_names=["hongtest"], audit=au)
        self.assertEqual(ctx.customers, [{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}])
        self.assertEqual(ctx.projects, [{"id": "P-0001", "codenames": ["과제A", "과제A2"]}])
        self.assertEqual(ctx.internal_domains, ["corp.example"])
        self.assertEqual(ctx.persons, {"김철수": "a" * 16})
        self.assertIn("홍길동", ctx.self_names)
        self.assertEqual(ctx.allow_patterns, [r"PRJ-\d{3}"])
        self.assertEqual(au.c, {"cfg.short_alias": 1, "cfg.generic_alias": 1, "cfg.bad_id": 1, "cfg.dup_alias": 1})
        self.assertEqual(sanitize("고객사A 과제A2 김철수 홍길동", ctx=ctx).text, "[고객사:C01] [과제:P-0001] [사람#"
                         + sanitize("김철수", ctx=ctx).text[4:10] + "] [나]")


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"privacy.path.excludeKeywords": ["개인", "가족"], "time.window.std": "08:30-17:30"})
        self.local = _local({"w" + "a" * 16: {"names": ["김철수"]}})

    def obj(self):
        return C.context_cache_obj(self.sb.paths, self.cfg, kr=H.keyring(), registry=H.REGISTRY,
                                   calendar={"years": [{"holidays": [{"date": "2026-10-09"}]}], "weekdays": [0, 1, 2, 3, 4]},
                                   local=self.local, os_names=H.OS_NAMES)

    def test_roundtrip_no_keys(self):
        obj = self.obj()
        self.assertEqual(obj["schema"], C.CTXCACHE_SCHEMA)
        h = C.write_context_cache(self.sb.paths.agent_dir(), obj)
        raw = self.sb.paths.context_cache().read_bytes()
        self.assertNotIn(b"secret", raw)
        for secret in (H.MASTER.hex(), __import__("base64").b64encode(H.MASTER).decode()):
            self.assertNotIn(secret.encode(), raw)
        back = C.read_context_cache(self.sb.paths.agent_dir())
        self.assertEqual((back["hash"], C.cache_hash(back)), (h, h))
        self.assertEqual(back["work_window"], {"std": "08:30-17:30", "weekdays": [0, 1, 2, 3, 4],
                                               "holidays": ["2026-10-09"], "tz_offset_min": 540})
        self.assertEqual(back["path_exclude"], ["개인", "가족"])
        tampered = dict(back, path_exclude=[])
        fsx.atomic_write(self.sb.paths.context_cache(), fsx.canon_bytes(tampered))
        self.assertIsNone(C.read_context_cache(self.sb.paths.agent_dir()))
        bad = self.obj()
        bad["sanitize"]["key"] = "x"
        with self.assertRaises(ValueError):
            C.write_context_cache(self.sb.paths.agent_dir(), bad)

    def test_T7_T28_program_agent_equivalence(self):
        """같은 설정 → 프로그램 폴더(키링) 문맥과 에이전트(하위 키 + 문맥 사본) 문맥이 같은 저장 행을 만든다."""
        K.write_agent_subkeys(H.keyring(), self.sb.paths.agent_dir(), None)
        C.write_context_cache(self.sb.paths.agent_dir(), self.obj())
        prog = H.Sandbox.rc(self.sb, "pc.sampler", cfg=self.cfg, local=self.local)
        agent = C.make_record_context(None, "pc.sampler", H.PC1, agent_dir=self.sb.paths.agent_dir())
        self.assertEqual((agent.mode, agent.stage, agent.keyring.kid), ("agent", "agent", H.keyring().kid))
        raw = H.raw_sampler(fg_title="김철수 책임 검토 요청_v2.docx - Word", fg_doc_name="검토 요청_v2.docx",
                            fg_doc_path=r"C:\Users\x\Documents\과제A\검토 요청_v2.docx")
        a = R.sanitize_record("pc_session", dict(raw), prog).row.to_dict()
        b = R.sanitize_record("pc_session", dict(raw), agent).row.to_dict()
        self.assertEqual(a, b)
        self.assertIn("[사람#", a["title_masked"])
        t1 = R.sanitize_record("teams", H.raw_teams(), H.Sandbox.rc(self.sb, "teams.uia", cfg=self.cfg, local=self.local))
        t2 = R.sanitize_record("teams", H.raw_teams(), C.make_record_context(None, "teams.uia", H.PC1,
                                                                               agent_dir=self.sb.paths.agent_dir()))
        self.assertEqual(t1.row.to_dict(), t2.row.to_dict())

    def test_agent_without_keys_or_cache(self):
        rc = C.make_record_context(None, "pc.sampler", H.PC1, agent_dir=self.sb.paths.agent_dir())
        self.assertIsInstance(rc.keyring, K.NoKeys)
        self.assertTrue(rc.no_key)
        self.assertEqual(rc.audit.counts()["err"], {"cfg.ctxcache_missing": 1})
        out = R.sanitize_record("teams", H.raw_teams(), C.make_record_context(None, "teams.uia", H.PC1,
                                                                               agent_dir=self.sb.paths.agent_dir()))
        self.assertEqual(out.reason, "no_key")

    def test_refresh_context_cache_program(self):
        h = C.refresh_context_cache(self.sb.paths, self.cfg, kr=H.keyring(), os_names=H.OS_NAMES)
        self.assertEqual(C.read_context_cache(self.sb.paths.agent_dir())["hash"], h)


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_person_dir_after_flush_program(self):
        rc = self.sb.rc("mail.com", now="2026-10-05")
        R.sanitize_record("mail", H.raw_mail(), rc)
        pd = self.sb.paths.local_only_file("person_dir.json")
        self.assertFalse(pd.exists())                                   # 감사 기록 성공 뒤에만
        self.assertTrue(rc.audit.flush())
        people = json.loads(pd.read_text(encoding="utf-8"))["people"]
        kim = people[K.who_key(H.keyring(), "smtp:" + H.KIM)]
        self.assertEqual((kim["names"], kim["smtp"], kim["internal"]), (["김철수"], [H.KIM], True))
        self.assertFalse(self.sb.paths.local_only_file("corresp_domains.json").exists())   # 왕래 도메인은 보낸 메일에서
        R.sanitize_record("mail", H.raw_mail(box="sent", folder_role="sent", sender_addr=H.ME, sender_name="홍길동",
                                             to=[{"addr": H.CUST, "name": "영업"}], internet_message_id="<s1@corp.example>"),
                          rc)
        self.assertTrue(rc.audit.flush())
        cd = json.loads(self.sb.paths.local_only_file("corresp_domains.json").read_text(encoding="utf-8"))
        self.assertEqual(cd, {"custa.example": "2026-09-15"})

    def test_merge_person_dir(self):
        cur = {"people": {"w" + "a" * 16: {"names": ["김철수"], "smtp": [], "first": "2026-09-01", "last": "2026-09-02"},
                          "junk": {}}}
        new = C.merge_person_dir(cur, {"w" + "a" * 16: {"names": ["김 책임"], "smtp": [H.KIM], "first": "2026-08-30",
                                                        "last": "2026-09-01", "internal": True}})
        p = new["people"]["w" + "a" * 16]
        self.assertEqual((p["names"], p["first"], p["last"], p["internal"]), (["김 책임", "김철수"], "2026-08-30",
                                                                             "2026-09-02", True))
        self.assertNotIn("junk", new["people"])
        self.assertEqual(new["format"], C.PERSONDIR_FORMAT)

    def test_agent_delta(self):
        K.write_agent_subkeys(H.keyring(), self.sb.paths.agent_dir(), None)
        rc = C.make_record_context(None, "teams.uia", H.PC1, agent_dir=self.sb.paths.agent_dir())
        R.sanitize_record("teams", H.raw_teams(author_addr=H.KIM), rc)
        rc.audit.flush()
        self.assertTrue(self.sb.paths.person_dir_delta().is_file())
        self.assertFalse(self.sb.paths.local_only_file("person_dir.json").exists())


class ImportDirectionTest(unittest.TestCase):
    """X-304: ``lm27.privacy`` 는 ``lm27.team`` 을 import 하지 않는다. ``lm27.hier``·``lm27.config``·``lm27.store``·
    ``lm27.normalize`` 는 함수 안 지연 import 로만(에이전트 사본에는 없는 패키지)."""

    LAZY_ONLY = ("lm27.hier", "lm27.config", "lm27.store", "lm27.normalize")

    def test_ast(self):
        top, lazy = {}, {}
        for f in sorted((H.REAL_ROOT / "lm27" / "privacy").glob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mod_level = set()
            for n in tree.body:
                for x in ast.walk(n) if isinstance(n, (ast.Import, ast.ImportFrom, ast.If, ast.Try)) else ():
                    mod_level.add(id(x))
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    names = [n.module]
                for nm in names:
                    (top if id(n) in mod_level else lazy).setdefault(nm, set()).add(f.name)
        bad_team = {m: v for m, v in {**top, **lazy}.items() if m == "lm27.team" or m.startswith("lm27.team.")}
        self.assertEqual(bad_team, {})
        bad_top = {m: v for m, v in top.items() if m.startswith(self.LAZY_ONLY)}
        self.assertEqual(bad_top, {})
        self.assertEqual(lazy.get("lm27.hier.registry"), {"context.py"})
        foreign = {m for m in top if m.split(".")[0] not in sys.stdlib_module_names
                   and m not in ("lm27.paths", "lm27.util") and not m.startswith("lm27.util.")}
        self.assertEqual(foreign, set())                                  # 모듈 수준 = 표준 라이브러리 + paths·util 만


if __name__ == "__main__":
    unittest.main()
