# -*- coding: utf-8 -*-
"""WP-11 키 시험 — 키링·하위 키 동치(P-T28 · E01~E04), 문서군 정규화(C16 · P §18.2 D01~D08 · W §4.1), 문서 연결(P-T27),
폴더·경로·저장소 키, peer_key(P-T32), 키링 적재·생성·손상·병합·충돌(P §9.5 · P-T7 · P-T8 일부), 에이전트 하위 키(P §9.4)."""
import base64
import hashlib
import hmac
import json
import os
import re
import unittest
from unittest import mock

from lm27.privacy import keys as K
from lm27.privacy.detect import SanitizeContext, sanitize, subkey
from lm27.util import fsx
from tests.fixtures.wp11 import helpers as H


class _Audit:
    def __init__(self):
        self.c = {}

    def add(self, counter, key, n=1):
        self.c[f"{counter}.{key}"] = self.c.get(f"{counter}.{key}", 0) + n


class PurposeTest(unittest.TestCase):
    def test_purposes_contract_42(self):
        self.assertEqual(K.PURPOSES, ("person", "msg", "thread", "chat", "cal", "doc", "path", "dir", "repo", "commit",
                                      "unit", "host", "peer"))
        self.assertEqual(K.AGENT_PURPOSES, ("person", "msg", "thread", "chat", "doc", "path", "dir"))
        self.assertEqual(K.KEYS_VERSION, "lm27-keys/1")

    def test_keyed_is_hmac_of_subkey(self):
        kr = H.keyring()
        want = hmac.new(subkey(H.MASTER, "msg"), b"x", hashlib.sha256).hexdigest()[:24]
        self.assertEqual(K.keyed(kr, "msg", "x", 24), want)
        with self.assertRaises(ValueError):
            K.keyed(kr, "nope", "x")

    def test_secret_not_in_repr(self):
        kr, ak = H.keyring(), H.agent_keys()
        for obj in (kr, ak):
            r = repr(obj)
            self.assertNotIn(base64.b64encode(H.MASTER).decode()[:8], r)
            self.assertNotIn(repr(H.MASTER), r)


class EquivalenceTest(unittest.TestCase):
    """P-T28: 키링과 하위 키가 같은 값(말뭉치 E01~E04)."""

    def setUp(self):
        self.kr, self.ak = H.keyring(), H.agent_keys()

    def test_E01_who_key(self):
        a, b = K.who_key(self.kr, "smtp:user01@corp.example"), K.who_key(self.ak, "smtp:user01@corp.example")
        self.assertEqual(a, b)
        self.assertRegex(a, r"^w[0-9a-f]{16}$")

    def test_E02_doc_key(self):
        got = {K.doc_key(x, n) for n in ("보고서_v3.pptx", "보고서_최종.docx") for x in (self.kr, self.ak)}
        self.assertEqual(len(got), 1)
        self.assertRegex(next(iter(got)), r"^d[0-9a-f]{16}$")

    def test_E03_person_tag(self):
        a = sanitize("김철수 책임님께 보고드립니다", ctx=SanitizeContext(key=H.MASTER)).text
        b = sanitize("김철수 책임님께 보고드립니다", ctx=SanitizeContext(person_subkey=subkey(H.MASTER, "person"))).text
        self.assertEqual(a, b)
        self.assertIn("[사람#", a)

    def test_E04_agent_missing_purpose(self):
        with self.assertRaises(K.NoKeyError):
            K.keyed(self.ak, "repo", "x")
        with self.assertRaises(K.NoKeyError):
            K.cal_key(self.ak, "x")

    def test_nokeys_mode(self):
        nk = K.NoKeys()
        self.assertEqual(nk.kid, K.NO_KID)
        for p in K.PURPOSES:
            with self.assertRaises(K.NoKeyError):
                K.keyed(nk, p, "x")

    def test_key_formats(self):
        kr = self.kr
        self.assertRegex(K.msg_key(kr, "mid:x"), r"^m[0-9a-f]{24}$")
        self.assertRegex(K.cal_key(kr, "gid:x"), r"^e[0-9a-f]{24}$")
        self.assertRegex(K.thread_key(kr, "conv:x"), r"^t[0-9a-f]{16}$")
        self.assertRegex(K.chat_key(kr, "x"), r"^h[0-9a-f]{16}$")
        self.assertRegex(K.commit_key(kr, "ABCDEF0"), r"^g[0-9a-f]{16}$")
        self.assertEqual(K.commit_key(kr, "ABCDEF0"), K.commit_key(kr, "abcdef0"))
        self.assertRegex(K.path_key(kr, r"C:\a\b.txt"), r"^f[0-9a-f]{16}$")
        self.assertRegex(K.dir_key(kr, "문서"), r"^s[0-9a-f]{16}$")
        self.assertRegex(K.repo_key(kr, r"C:\src\firmware"), r"^r[0-9a-f]{16}$")

    def test_person_ident(self):
        self.assertEqual(K.person_ident("Kim@Corp.Example", "김철수"), "smtp:kim@corp.example")
        self.assertEqual(K.person_ident(None, "김철수 책임"), "name:김철수")
        self.assertEqual(K.person_ident("not-an-address", ""), None)
        self.assertIsNone(K.person_ident(None, None))


class DocFamTest(unittest.TestCase):
    """계약 v1.2 C16 — P §18.2 D01~D08 기대값 그대로 + W §4.1 확장자·꼬리 반복(WP-19 시험과 같은 사례)."""

    D = [("D01", "과제A_열해석_v3.wbpj", "과제a_열해석"), ("D02", "보고서_최종.pptx", "보고서"),
         ("D03", "보고서 - 복사본.pptx", "보고서"), ("D04", "보고서 (1).pptx", "보고서"),
         ("D05", "주간보고_20261005.xlsx", "주간보고_20261005"), ("D06", "v2.docx", "v2"),
         ("D07", "C:\\Users\\hong\\Documents\\2026 사업계획 v2 최종.pptx", "2026_사업계획"),
         ("D08", "photocopy.pdf", "photocopy")]

    def test_D01_to_D08(self):
        for did, name, want in self.D:
            with self.subTest(did):
                self.assertEqual(K.doc_fam(name), want)

    def test_w41_extensions_and_tails(self):
        self.assertEqual(K.doc_fam("검토보고서_과제A_열해석_v2.pptx"), "검토보고서_과제a_열해석")
        self.assertEqual(K.doc_fam("하우징_과제D.prt.12"), "하우징_과제d")
        self.assertEqual(K.doc_fam("결과.cas.gz"), "결과")
        self.assertEqual(K.doc_fam("도면_최종_v3.dwg"), "도면")
        self.assertEqual(K.doc_fam("보고서 rev2.pptx"), "보고서")
        self.assertEqual(K.doc_fam("보고서_수정본.hwp"), "보고서")

    def test_tail_words_need_separator(self):
        for name, want in (("자료수정.xlsx", "자료수정"), ("motor2.prt", "motor2"), ("dev2.c", "dev2"),
                           ("finalreport.docx", "finalreport"), ("보고서최종.pptx", "보고서최종")):
            self.assertEqual(K.doc_fam(name), want, name)

    def test_empty_and_odd(self):
        self.assertEqual(K.doc_fam(""), "")
        self.assertEqual(K.doc_fam(None), "")
        self.assertEqual(K.doc_fam("최종.pptx"), "최종")               # 다 지우면 원래 이름
        self.assertEqual(K.doc_fam("https://tenant.sharepoint.example/sites/a/견적.xlsx"), "견적")
        self.assertLessEqual(len(K.doc_fam("가" * 5000 + ".txt")), K.NAME_MAX)
        self.assertEqual(K.doc_fam("ＡＢＣ　보고서．ｐｐｔｘ"), "abc_보고서")          # NFKC 전각

    def test_T27_doc_link_same_key(self):
        """P-T27: 같은 문서를 창 제목 문서명·파일(전체 경로)·메일 첨부·팀즈 파일로 관측 → doc_key 같음."""
        kr = H.keyring()
        names = ["과제A_열해석_v3.wbpj", r"C:\Users\hongtest\Documents\과제A_열해석_최종.wbpj", "과제A_열해석 (1).wbpj",
                 "과제A_열해석.wbpj"]
        self.assertEqual(len({K.doc_key(kr, n) for n in names}), 1)
        self.assertNotEqual(K.doc_key(kr, "주간보고_20261005.xlsx"), K.doc_key(kr, "주간보고_20261012.xlsx"))


class FolderPathRepoTest(unittest.TestCase):
    def test_dir_key_matches_registry_rule(self):
        """WP-21 요청: 폴더 키 = 's' + keyed(dir, 'seg:' + seg_norm(seg)) — 레지스트리 폴더 규칙과 같은 정규화."""
        kr = H.keyring()
        self.assertEqual(K.dir_key(kr, "과제 A.설계"), "s" + K.keyed(kr, "dir", "seg:과제_a_설계", 16))
        self.assertEqual(K.seg_norm("  ＡＢ-c_d.e  "), "ab_c_d_e")
        try:
            from lm27.hier import registry as R
        except ModuleNotFoundError:                           # 분류 패키지가 없는 복제(시험 범위 밖)
            return
        for seg in ("과제 A.설계", "Docs-2026", "  x__y  "):
            self.assertEqual(K.seg_norm(seg), R.seg_norm(seg))
            self.assertEqual(R.keyers_from(kr)[0](seg), K.dir_key(kr, seg))

    def test_dir_segments(self):
        self.assertEqual(K.dir_segments(r"C:\Users\hongtest\Documents\과제A\a.xlsx"), ["과제A", "Documents", "hongtest"])
        self.assertEqual(K.dir_segments(r"C:\a.xlsx"), [])
        self.assertEqual(K.dir_segments("https://h.example/sites/x/%EA%B0%80/a.xlsx", 2), ["가", "x"])
        kr = H.keyring()
        self.assertEqual(len(K.dir_keys_of(kr, r"C:\Users\u\Documents\과제A\a.xlsx", 3)), 3)

    def test_path_norm_userprofile(self):
        self.assertEqual(K.path_norm(r"C:\Users\Hong\Documents\A.xlsx"), r"%userprofile%\documents\a.xlsx")
        self.assertEqual(K.path_norm("c:/users/kim/documents/a.xlsx"), r"%userprofile%\documents\a.xlsx")
        kr = H.keyring()
        self.assertEqual(K.path_key(kr, r"C:\Users\Hong\Documents\A.xlsx"), K.path_key(kr, r"C:\Users\kim\documents\a.XLSX"))
        self.assertNotEqual(K.path_key(kr, r"D:\work\A.xlsx"), K.path_key(kr, r"D:\other\A.xlsx"))
        self.assertEqual(K.path_norm("https://h.example/a/b.xlsx?web=1#x"), "https://h.example/a/b.xlsx")

    def test_repo_key_by_name(self):
        kr = H.keyring()
        self.assertEqual(K.repo_key(kr, r"C:\Users\a\src\Firmware"), K.repo_key(kr, "D:/work/firmware/"))
        self.assertNotEqual(K.repo_key(kr, r"C:\src\firmware"), K.repo_key(kr, r"C:\src\viewer"))


class PeerKeyTest(unittest.TestCase):
    """P-T32."""

    def test_external_none(self):
        self.assertEqual(K.peer_key("ab" * 32, "x@vendor.example", ["corp.example"], H.keyring()), (None, ""))
        self.assertEqual(K.peer_key("ab" * 32, "", ["corp.example"], H.keyring()), (None, ""))

    def test_team_same_on_two_pcs(self):
        a = K.peer_key("ab" * 32, "User01@Corp.Example", ["corp.example"], H.keyring(H.MASTER))
        b = K.peer_key("ab" * 32, "user01@corp.example", ["corp.example"], H.keyring(H.MASTER2))
        self.assertEqual(a, b)
        self.assertEqual(a[1], "team")
        self.assertRegex(a[0], r"^c_[0-9a-f]{12}$")
        self.assertEqual(K.peer_key("ab" * 32, "u@mail.corp.example", ["corp.example"], H.keyring())[1], "team")

    def test_personal_without_pepper(self):
        a = K.peer_key(None, "user01@corp.example", ["corp.example"], H.keyring())
        self.assertEqual(a[1], "personal")
        self.assertRegex(a[0], r"^c_[0-9a-f]{12}$")
        self.assertEqual(K.peer_key("zz", "user01@corp.example", ["corp.example"], H.keyring())[1], "personal")


class KeyringFileTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.data = self.sb.paths.data()
        self.kp = self.sb.paths.keyring()

    def test_missing_without_create(self):
        with self.assertRaises(K.NoKeyringError):
            K.load_keyring(self.data, None)

    def test_create_and_reload(self):
        au = _Audit()
        kr = K.load_keyring(self.data, au, create=True, origin=H.PC1, now="2026-10-05T00:00:00Z")
        self.assertEqual(au.c, {"key.created": 1})
        obj = json.loads(self.kp.read_bytes())
        self.assertEqual(obj["format"], "lm27-keyring/1")
        self.assertEqual(obj["primary"], kr.kid)
        self.assertEqual(obj["keys"][0]["origin"], H.PC1)
        self.assertEqual(K.kid_of(base64.b64decode(obj["keys"][0]["secret_b64"])), kr.kid)
        self.assertRegex(kr.kid, r"^k[0-9a-f]{8}$")
        au2 = _Audit()
        kr2 = K.load_keyring(self.data, au2)
        self.assertEqual((kr2.kid, kr2.primary_secret), (kr.kid, kr.primary_secret))
        self.assertEqual(au2.c, {})

    def test_corrupt_renamed_aside(self):
        fsx.atomic_write(self.kp, b"{broken")
        au = _Audit()
        kr = K.load_keyring(self.data, au, create=True, now="2026-10-05T01:02:03Z")
        self.assertEqual(au.c, {"key.corrupt": 1, "key.created": 1})
        names = sorted(p.name for p in self.kp.parent.iterdir())
        self.assertIn("privacy_keyring.json.corrupt-2026-10-05T010203Z", names)
        self.assertEqual(json.loads(self.kp.read_bytes())["primary"], kr.kid)

    def test_merge_conflict_earliest_primary(self):
        """P-T8 일부: 서로 다른 압축 해제본의 키링 합집합 → 주 키 = 더 이른 키, key.conflict, 나머지 retired."""
        a = K.load_keyring(self.data, None, create=True, now="2026-10-02T00:00:00Z")
        other = H.Sandbox()
        self.addCleanup(other.cleanup)
        b = K.load_keyring(other.paths.data(), None, create=True, now="2026-10-01T00:00:00Z")
        au = _Audit()
        m = K.load_keyring(self.data, au, merge_from=[other.paths.keyring()])
        self.assertEqual(au.c, {"key.conflict": 1})
        self.assertEqual(m.kid, b.kid)
        self.assertEqual(set(m.all), {a.kid, b.kid})
        obj = json.loads(self.kp.read_bytes())
        states = {k["kid"]: k["state"] for k in obj["keys"]}
        self.assertEqual(states, {b.kid: "active", a.kid: "retired"})
        au2 = _Audit()
        self.assertEqual(K.load_keyring(self.data, au2, merge_from=[other.paths.keyring()]).kid, b.kid)
        self.assertEqual(au2.c, {})                                     # 이미 합친 키 — 충돌 다시 세지 않음

    def test_readonly_bundle_memory_keyring(self):
        au = _Audit()
        with mock.patch.object(K.fsx, "atomic_write", side_effect=PermissionError(13, "ro")):
            kr = K.load_keyring(self.data, au, create=True)
        self.assertEqual(au.c, {"key.created": 1, "key.bundle_readonly": 1})
        self.assertFalse(self.kp.exists())
        self.assertRegex(kr.kid, r"^k[0-9a-f]{8}$")


class AgentSubkeysTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.agent = self.sb.paths.agent_dir()

    def test_roundtrip_and_equivalence_T7(self):
        """P-T7: 폴더 키링에서 하위 키 → 같은 kid·같은 who_key·msg_key."""
        kr = H.keyring()
        kid = K.write_agent_subkeys(kr, self.agent, None, now="2026-10-05T00:00:00Z")
        self.assertEqual(kid, kr.kid)
        obj = json.loads(self.sb.paths.agent_subkeys().read_bytes())
        self.assertEqual(obj["format"], "lm27-subkeys/1")
        self.assertEqual(sorted(obj["purposes"]), sorted(K.AGENT_PURPOSES))
        self.assertNotIn(base64.b64encode(H.MASTER).decode(), json.dumps(obj))       # 주 키 없음
        ak = K.load_agent_keys(self.agent, None)
        self.assertEqual(ak.kid, kr.kid)
        self.assertEqual(K.who_key(ak, "smtp:" + H.KIM), K.who_key(kr, "smtp:" + H.KIM))
        self.assertEqual(K.msg_key(ak, "mid:x"), K.msg_key(kr, "mid:x"))
        self.assertEqual(K.dir_key(ak, "문서"), K.dir_key(kr, "문서"))

    def test_rotation_counted(self):
        K.write_agent_subkeys(H.keyring(H.MASTER), self.agent, None)
        before = self.sb.paths.agent_subkeys().read_bytes()
        au = _Audit()
        K.write_agent_subkeys(H.keyring(H.MASTER), self.agent, au)
        self.assertEqual(au.c, {})
        self.assertEqual(self.sb.paths.agent_subkeys().read_bytes(), before)        # 같은 키면 다시 쓰지 않음
        K.write_agent_subkeys(H.keyring(H.MASTER2), self.agent, au)
        self.assertEqual(au.c, {"key.agent_rotated": 1})
        self.assertEqual(K.load_agent_keys(self.agent, None).kid, K.kid_of(H.MASTER2))

    def test_missing_or_corrupt(self):
        self.assertIsNone(K.load_agent_keys(self.agent, None))
        fsx.atomic_write(self.sb.paths.agent_subkeys(), b'{"format": "lm27-subkeys/1"}')
        au = _Audit()
        self.assertIsNone(K.load_agent_keys(self.agent, au))
        self.assertEqual(au.c, {"key.corrupt": 1})
        with self.assertRaises(TypeError):
            K.write_agent_subkeys(H.agent_keys(), self.agent, None)

    def test_no_secrets_in_errors(self):
        fsx.atomic_write(self.sb.paths.keyring(), b'{"format":"lm27-keyring/1","keys":[{"kid":"k00000000","secret_b64":"!!"}]}')
        with self.assertRaises(K.NoKeyringError) as cm:
            K.load_keyring(self.sb.paths.data(), None)
        self.assertNotRegex(str(cm.exception), re.escape("!!"))
        self.assertFalse(os.path.exists(self.sb.paths.keyring()))     # 깨진 파일은 옆으로 옮겨졌다


if __name__ == "__main__":
    unittest.main()
