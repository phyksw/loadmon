# -*- coding: utf-8 -*-
"""WP-34 팀 묶음 정제 관문 — U03 PII 카나리아(T-07 팀 페이로드: 바이트 0건 · 자유 문자열 거절 수 = 삽입 수 · 서버 재검사 0건),
T-21(키·로컬 사전·pepper·호스트 표시 0), 허용 목록 빌드(모델의 로컬 전용 필드는 읽지도 싣지도 않음), 로컬 사전(사람 표시명·
PC 별칭) 부분 일치, L-22(통째 전달·호스트 표시 필드 읽기 0)·L-21(기본 주소 상수 한 곳) 정적 확인."""
import ast
import base64
import itertools
import unittest
from datetime import UTC, datetime

from lm27 import privacy as P
from lm27.team import build as B
from lm27.team import schema as S
from lm27.util import events, fsx
from tests.fixtures import canary as K
from tests.fixtures.wp34 import world as W

PERIOD = {"from": W.D0, "to": W.D1}
NOW = datetime(2026, 10, 1, 1, 0, 0, tzinfo=UTC)
BUILD_PY = W.TREE / "lm27" / "team" / "build.py"


class _Case(unittest.TestCase):
    def setUp(self):
        self._mode = events.mode()
        events.configure("off")

    def tearDown(self):
        events.configure(self._mode)


def _canaries():
    """U03 형식 카나리아(약한 것 제외): 형식만으로 잡히는 PII · 게이트 환경(호스트명·계정·GUID) · 가명 키 모양."""
    cs = K.canaries(groups=("pii", "env", "key"), weak=False)
    by = {c.cat: c for c in cs}
    texts = [c.sentence if c.sentence else f"검토 메모 {c.value}" for c in cs]
    return cs, by, texts


class TestCanaries(_Case):
    def setUp(self):
        super().setUp()
        self.cs, self.by, self.texts = _canaries()
        pd = W.deep(W.PERSON_DIR)
        pd["people"][W.KIM]["names"].append(self.by["peer_name"].value)          # U03 동료 표시명
        self.w = W.World(person_dir=pd)
        self.env_vars = {"COMPUTERNAME": self.by["hostname"].value, "USERNAME": self.by["winuser"].value,
                         "USERDOMAIN": "WORKGRP34"}

    def tearDown(self):
        self.w.cleanup()
        super().tearDown()

    def env(self, c):
        return self.w.env(c, environ=self.env_vars, machine_guid=self.by["machine_guid"].value)

    def test_every_canary_is_rejected_as_free_text(self):
        """자유 문자열 검사(team_text — P check_team_label·forbidden_codes + 로컬 사전)가 카나리아 문장을 모두 거절한다."""
        env = self.env(W.cfg())
        tc = B.TextCtx(env.gctx, env.local_words)
        passed = [c.cid for c, t in zip(self.cs, self.texts, strict=True) if tc.text(t, 40, "units[].title") is not None]
        self.assertEqual(passed, [])
        self.assertEqual(tc.rejected, len(self.cs))

    def test_u03_bundle_bytes_zero_and_rejected_count(self):
        m = W.model()
        it = itertools.cycle(self.texts)
        n_free = 0
        for u in m["units"]:
            u["title"] = next(it)
            n_free += u["unit_id"] != W.U[7]                                   # 미착수는 묶음에 없다
        for wf in m["workflows"]["roles"].values():
            for s in wf["steps"]:
                s["label"] = next(it)
                n_free += 1
        m["proposals"][0]["label"] = next(it)
        n_free += 1
        for nd in m["agentic"]["needs"]:
            nd["label"] = nd["name"] = next(it)
            n_free += not nd["dropped"]
        for sa in m["team"]["subagents"]:
            for ch in sa["chain"]:
                ch["proposal"] = next(it)
                n_free += ch["step_no"] in (3, 4)                               # 없는 단계(9)는 싣지 않는다
        # 빌더가 읽지 않아야 하는 로컬 전용 필드(허용 목록 밖)에도 심는다
        for r in m["refs"]["people"].values():
            r["name"] = next(it)
        for d in m["refs"]["docs"].values():
            d["name"] = next(it)
        for q in m["queue"]:
            q["why_ko"] = next(it)
        for u in m["units"]:
            u["why"] = [next(it)]
            u["cycles"][0]["s_key"] = self.by["who_key"].value
        c = W.cfg(**{"team.selfLabel": self.by["phone"].value})
        n_free += 1
        env = self.env(c)
        obj, audit = B.build_team_bundle(m, PERIOD, W.registry(), W.PEPPER, {}, c, env=env, now=NOW)
        raw = fsx.canon_bytes(obj)
        self.assertEqual(K.find_canaries(raw, self.cs), [])
        self.assertEqual(audit["team_text_rejected"], n_free)
        self.assertEqual(obj["quality"]["team_text_rejected"], n_free)
        self.assertEqual(S.privacy_payload_check(c)(obj), [])                 # 서버 재검사(서버 모드 게이트)
        self.assertEqual(P.check_team_payload(obj, env.gctx, S.TEAM_SPEC_V1), [])
        self.assertTrue(all(u["title_mode"] == "generic" for u in obj["units"]))
        self.assertEqual(obj["person"]["self_label"], "")
        errs = S.validate_team_bundle(obj, registry=W.registry(), side="client")
        self.assertEqual([e for e in errs if e.blocking], [])


class TestNoLocalSecrets(_Case):
    def setUp(self):
        super().setUp()
        self.w = W.World()

    def tearDown(self):
        self.w.cleanup()
        super().tearDown()

    def test_t21_keys_names_pepper_env_absent(self):
        """T-21: 팀 묶음 바이트에 키링 비밀·pepper·사람 사전 이름·주소·who_key·pc_id·게이트 환경 값 0."""
        c = W.cfg()
        env = self.w.env(c)
        obj, _a = B.build_team_bundle(W.model(), PERIOD, W.registry(), W.PEPPER, {}, c, env=env, now=NOW)
        raw = fsx.canon_bytes(obj)
        kr = P.load_keyring(self.w.paths.data(), None, create=False)
        needles = [W.PEPPER, W.PC_ID, W.MACHINE_GUID, *W.GATE_ENV.values()]
        needles += [base64.b64encode(s).decode("ascii")[:16] for s in kr.all.values()]
        for who, rec in W.PERSON_DIR["people"].items():
            needles += [who, *rec["names"], *rec["smtp"]]
        needles += [r["key"] for r in W.model()["refs"]["people"].values()]
        needles += [d["key"] for d in W.model()["refs"]["docs"].values()]
        for x in needles:
            self.assertNotIn(x.encode("utf-8"), raw, x[:4])
        self.assertNotIn(b"host_display", raw)
        self.assertEqual(S.bytes_guard_hits(raw), [])
        self.assertEqual(obj["person"]["pepper_id"], W.PEPPER_ID)             # pepper 대신 id 만

    def test_local_dict_pc_alias_and_people(self):
        """TAB §2.4 로컬 사전: 사람 사전 표시명·PC 별칭(사람이 붙인 이름)이 들어간 제목은 generic 으로."""
        W.put_pc(self.w.paths, label_user="내작업용노트북")
        m = W.model()
        m["units"][0]["title"] = "내작업용노트북 정리"
        m["units"][1]["title"] = "동료 둘 요청 검토"
        c = W.cfg()
        env = self.w.env(c)
        self.assertIn("내작업용노트북", env.local_words)
        obj, audit = B.build_team_bundle(m, PERIOD, W.registry(), W.PEPPER, {}, c, env=env, now=NOW)
        titles = {u["unit_id"]: (u["title"], u["title_mode"]) for u in obj["units"]}
        self.assertEqual(titles[m["units"][0]["unit_id"]][1], "generic")
        self.assertEqual(titles[m["units"][1]["unit_id"]][1], "generic")
        self.assertNotIn("내작업용노트북".encode(), fsx.canon_bytes(obj))
        self.assertGreaterEqual(audit["fields"].get("units[].title", 0), 2)

    def test_short_dict_words_ignored(self):
        """사전 항목은 한글 2자·ASCII 4자 이상만 — 짧은 항목으로 오탐하지 않는다."""
        tc = B.TextCtx(P.make_gate_context(None, None, None, stage="team", audit=None, environ={}), ["김", "abc", "WP34"])
        self.assertFalse(tc.local_dict_hit("김밥 주문 abc"))
        self.assertTrue(tc.local_dict_hit("wp34 서버"))


class TestStatic(unittest.TestCase):
    def test_l22_no_wholesale_copy_and_no_host_display(self):
        tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))
        bad = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict) and any(k is None for k in n.keys):
                bad.append(("dict-unpack", n.lineno))
            if isinstance(n, ast.Call):
                if any(k.arg is None for k in n.keywords):
                    bad.append(("kwargs-unpack", n.lineno))
                fn = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                if fn == "dict" and len(n.args) == 1 and not isinstance(n.args[0], (ast.Dict, ast.List, ast.Tuple)):
                    bad.append(("dict(obj)", n.lineno))
                if fn == "deepcopy":
                    bad.append(("deepcopy", n.lineno))
            if isinstance(n, ast.Constant) and n.value == "host_display":
                bad.append(("host_display", n.lineno))
            if isinstance(n, (ast.Attribute, ast.Name)) and (getattr(n, "attr", None) == "host_display"
                                                              or getattr(n, "id", None) == "host_display"):
                bad.append(("host_display", n.lineno))
        self.assertEqual(bad, [])

    def test_l21_default_url_defined_once(self):
        """CR-13: DEFAULT_TEAM_URL 상수는 lm27\\team\\client.py 한 곳에만."""
        hits = []
        for f in sorted((W.TREE / "lm27").rglob("*.py")):
            t = f.read_text(encoding="utf-8")
            if "DEFAULT_TEAM_URL =" in t:
                hits.append(f.relative_to(W.TREE).as_posix())
        self.assertEqual(hits, ["lm27/team/client.py"])


if __name__ == "__main__":
    unittest.main()
