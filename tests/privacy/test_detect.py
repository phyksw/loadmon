# -*- coding: utf-8 -*-
"""WP-10 ``sanitize()`` 시험 — 회귀 말뭉치 양성·미끼·폐기(P-T1 일부), 멱등(I4)·결정성(I6), P-T21(절단)·T22(전각),
카나리아(WP-05 런타임 조립 값)가 정제 뒤 남지 않음, LM27 보강(extra_stopwords·사전 캐시·safe_truncate).

번호·주소 같은 값은 소스에 리터럴로 두지 않는다 — 말뭉치 파일·canary 하네스에서 읽거나 런타임에 조립한다.
"""
import contextlib
import dataclasses
import io
import re
import unittest

from lm27.privacy import detect, rules, selftest
from lm27.privacy.detect import MAX_SCAN, SanitizeContext, safe_truncate, sanitize, subkey
from tests.fixtures.canary import canaries, canary_ctx

CORPUS = selftest.load_corpus()
BY_ID = {r["id"]: r for r in CORPUS}
PERSON_TAG = re.compile(r"\[사람#[0-9a-f]{6}\]")
AT = chr(64)
CTX_A = {"internal_domains": ["corp.example"],
         "customers": [{"id": "C01", "names": ["고객사A", "CustA"], "domains": ["custa.example"]}],
         "projects": [{"id": "P0001", "codenames": ["과제A", "PROJ-A"]}],
         "persons": {"김철수": "a1b2c3d4e5f60718"}, "self_names": ["홍길동"]}


def _ctx(d):
    return SanitizeContext(**d) if d else SanitizeContext()


def _canary(cat):
    return next(c for c in canaries() if c.cat == cat)


class CorpusTest(unittest.TestCase):
    def test_positive_60(self):
        """P §18.2 양성 60 + 2026.10.1 회귀 양성 P61~P75(대시·서식 문자·띄운 구분자·경로 2단계 — W1 통합 창)."""
        rows = [r for r in CORPUS if r["type"] == "pos"]
        self.assertEqual(len(rows), 75)
        for r in rows:
            with self.subTest(rid=r["id"]):
                ctx = _ctx(r.get("ctx"))
                res = sanitize(r["text"], ctx=ctx)
                got = PERSON_TAG.sub("[사람#*]", res.text) if "#*" in r["expect"] else res.text
                self.assertEqual(got, r["expect"])
                self.assertEqual(res.hits, r["hits"])
                self.assertFalse(res.drop)
                again = sanitize(res.text, ctx=ctx)                       # I4 멱등
                self.assertEqual(again.text, res.text)
                self.assertEqual(again.hits, {})

    def test_negative_50(self):
        rows = [r for r in CORPUS if r["type"] == "neg"]
        self.assertEqual(len(rows), 54)                                      # + N51~N54(2026.10.1)
        for r in rows:
            with self.subTest(rid=r["id"]):
                res = sanitize(r["text"])
                self.assertEqual(res.text, re.sub(r"\s{2,}", " ", r["text"]).strip())
                self.assertEqual(res.hits, {})

    def test_drop_6(self):
        for r in (x for x in CORPUS if x["type"] == "drop"):
            with self.subTest(rid=r["id"]):
                res = sanitize(r["text"])
                self.assertTrue(res.drop)
                self.assertEqual((res.text, res.hits, res.drop_reason), ("", {"cred": 1}, "cred"))

    def test_dictionary_tag_uses_person_dict(self):
        res = sanitize(BY_ID["P44"]["text"], ctx=_ctx(CTX_A))
        self.assertTrue(res.text.startswith("[사람#a1b2c3]"))


class CanaryTest(unittest.TestCase):
    """WP-05 카나리아(P01~P60 형식, 런타임 조립 값)가 정제문에 남지 않는다."""

    def test_pii_group_masked(self):
        ctx = SanitizeContext(internal_domains=["corp.example"],
                              customers=[{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}])
        for c in canaries(groups=["pii"]):
            with self.subTest(cid=c.cid):
                res = sanitize(c.sentence, ctx=ctx)
                self.assertFalse(res.drop)
                self.assertNotIn(c.value, res.text)
                if c.token and c.token != "[사람#]":
                    self.assertIn(c.token, res.text)
                self.assertEqual(sanitize(res.text, ctx=ctx).text, res.text)

    def test_ctx_group_masked_with_dictionary(self):
        d = canary_ctx()
        d.pop("canaries")
        ctx = SanitizeContext(**d)
        for c in canaries(groups=["ctx"]):
            with self.subTest(cid=c.cid):
                res = sanitize(c.sentence, ctx=ctx)
                self.assertNotIn(c.value, res.text)
                if c.token != "[사람#]":
                    self.assertIn(c.token, res.text)


class SpecScenarioTest(unittest.TestCase):
    def test_truncate_never_splits_token_T21(self):
        """P-T21: 300자 넘는 팀즈 본문 끝에 토큰이 걸려도 출력 ≤300자, 반쪽 토큰 없음."""
        phone = _canary("phone").value
        for pad in range(285, 300):
            text = "가" * pad + " " + phone + " 끝"
            out = sanitize(text, "body_masked", max_len=300).text
            with self.subTest(pad=pad):
                self.assertLessEqual(len(out), 300)
                self.assertNotIn(phone, out)
                tail = out[out.rfind("["):] if "[" in out else ""
                self.assertTrue(not tail or "]" in tail, "닫히지 않은 토큰")

    def test_fullwidth_phone_T22(self):
        """P-T22: 전각 숫자·하이픈 전화번호 → [전화](NFKC)."""
        v = _canary("phone").value
        fw = "".join(chr(0xFF10 + int(ch)) if ch.isdigit() else chr(0xFF0D) for ch in v)
        self.assertNotEqual(fw, v)
        res = sanitize(fw)
        self.assertEqual(res.text, "[전화]")
        self.assertEqual(res.hits, {"phone": 1})

    def test_deterministic_I6(self):
        for c in canaries(groups=["pii"])[:20]:
            a, b = sanitize(c.sentence, ctx=_ctx(CTX_A)), sanitize(c.sentence, ctx=_ctx(CTX_A))
            self.assertEqual((a.text, a.hits), (b.text, b.hits))

    def test_person_subkey_equivalence_E03(self):
        """에이전트(하위 키만)와 키링(주 키)이 같은 [사람#…] 태그를 만든다(P §6 구현 주의)."""
        k = bytes(range(32))
        text = BY_ID["P42"]["text"]
        a = sanitize(text, ctx=SanitizeContext(key=k)).text
        b = sanitize(text, ctx=SanitizeContext(person_subkey=subkey(k, "person"))).text
        c = sanitize(text, ctx=SanitizeContext()).text                       # 0 바이트 키 — 다른 태그
        self.assertEqual(a, b)
        self.assertIn("[사람#", a)
        self.assertNotEqual(a, c)

    def test_keyed_hex_matches_subkey(self):
        import hashlib
        import hmac
        k = b"\x02" * 32
        want = hmac.new(subkey(k, "person"), b"name:x", hashlib.sha256).hexdigest()
        self.assertEqual(detect.keyed_hex(k, "person", "name:x"), want)
        self.assertNotEqual(subkey(k, "person"), subkey(k, "doc"))


class ContextOptionTest(unittest.TestCase):
    def test_extra_stopwords_honorific_only(self):
        """privacy.names.extraStopwords — 호칭형 후보에서만 NAME_STOP 과 합집합으로 뺀다(계약 §5.2·X-114)."""
        text = "홍길동 책임님 자료"
        self.assertIn("[사람#", sanitize(text).text)
        ctx = SanitizeContext(extra_stopwords=["홍길동"])
        self.assertEqual(sanitize(text, ctx=ctx).text, text)
        self.assertIn("[사람#", sanitize("@홍길동 확인", ctx=ctx).text)          # 멘션은 그대로 잡는다

    def test_allow_pattern_protects(self):
        c = _canary("phone_rep")
        ctx = SanitizeContext(allow_patterns=[re.escape(c.value)])
        res = sanitize(c.sentence, ctx=ctx)
        self.assertIn(c.value, res.text)
        self.assertEqual(res.hits, {})
        self.assertNotIn(c.value, sanitize(c.sentence).text)

    def test_extra_ctx_word(self):
        acct = _canary("account").value
        text = "적립 " + acct
        self.assertEqual(sanitize(text).text, text)                                 # 문맥 없음 → 계좌로 안 봄
        ctx = SanitizeContext(extra_ctx={"account_strong": ["적립"]})
        self.assertEqual(sanitize(text, ctx=ctx).text, "적립 [계좌]")

    def test_email_labels(self):
        cases = [("qa" + AT + "mail.corp.example", "사내"),
                 ("me" + AT + rules.PERSONAL_MAIL_DOMAINS[0], "개인메일"),
                 ("kim" + AT + "custa.example", "고객사:C01"),
                 ("sup" + AT + "vend.example", "협력사:V01"),
                 ("x" + AT + "Other.Example", "other.example")]
        ctx = SanitizeContext(internal_domains=["corp.example"],
                              customers=[{"id": "C01", "names": [], "domains": ["custa.example"]}],
                              partners=[{"id": "V01", "names": [], "domains": ["vend.example"]}])
        for addr, label in cases:
            with self.subTest(label=label):
                out = sanitize("회신 " + addr, ctx=ctx).text
                self.assertEqual(out, f"회신 [이메일@{label}]")
                self.assertNotIn(addr.split(AT)[0] + AT, out)

    def test_dictionary_order_and_boundaries(self):
        ctx = _ctx(CTX_A)
        self.assertEqual(sanitize("XPROJ-A 결과", ctx=ctx).text, "XPROJ-A 결과")       # ASCII 이름은 양쪽 경계
        self.assertEqual(sanitize("과제A의 일정", ctx=ctx).text, "[과제:P0001]의 일정")   # 한글 이름은 뒤 열림(조사)
        self.assertEqual(sanitize("custa 회의", ctx=ctx).text, "[고객사:C01] 회의")      # 대소문자 무시
        ctx2 = SanitizeContext(customers=[{"id": "C01", "names": ["고객사A"], "domains": []},
                                          {"id": "C02", "names": ["고객사A2"], "domains": []}])
        self.assertEqual(sanitize("고객사A2 방문", ctx=ctx2).text, "[고객사:C02] 방문")   # 긴 이름 우선(다른 id)

    def test_grouped_dictionary_regex_equals_per_name_form(self):
        """사전 정규식을 묶음 경계로 바꿔도(성능) 이름마다 경계를 붙인 P §6 원형과 일치 결과가 같다."""
        names = ["PROJ-A", "proj", "PROJ-AB", "A&B Co", "고객사A", "고객사A2", "가나", "가나다라", "X팀", "XY", "B.V", "홍길동"]

        def original(ns):
            ns = sorted({n for n in ns if n}, key=lambda n: (-len(n), n))
            parts = [(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])")
                     if re.fullmatch(r"[A-Za-z0-9 .&\-]+", n) else (r"(?<![가-힣A-Za-z0-9])" + re.escape(n)) for n in ns]
            return re.compile("|".join(parts), re.I)
        texts = ["PROJ-AB 와 PROJ-A, proj 그리고 xproj", "고객사A2와 고객사A의 가나다라마 가나 회의", "X팀XY XY팀 xy",
                 "A&B Co 방문 a&b co.", "B.V 와 B.VX", "홍길동님 김홍길동", "proj-a2 PROJ-ABC 고객사A22"]
        old, new = original(names), detect._dict_rx(names)
        for t in texts:
            with self.subTest(t=t):
                self.assertEqual([m.span() for m in new.finditer(t)], [m.span() for m in old.finditer(t)])

    def test_mask_switches(self):
        rate = BY_ID["P46"]["text"]
        self.assertEqual(sanitize(rate, ctx=SanitizeContext(mask_rates=False)).text, rate)
        comp = BY_ID["P47"]["text"]
        self.assertNotIn("[회사]", sanitize(comp, ctx=SanitizeContext(mask_company_suffix=False)).text)


class InputShapeTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual((sanitize("").text, sanitize("").hits), ("", {}))
        self.assertEqual(sanitize(None).text, "")

    def test_control_and_zero_width(self):
        """제어 문자·사설 영역은 공백, 서식 문자(Cf — 폭 0 공백 등)는 삭제(2026.10.1 — 값 가운데 끼운 서식 문자가 탐지를
        끊지 않게)."""
        res = sanitize("도면" + chr(7) + "검토" + chr(0x200B) + "요청" + chr(0xE123))
        self.assertEqual(res.text, "도면 검토요청")
        self.assertEqual(sanitize("검토" + chr(0x00AD) + chr(0x2060) + chr(0xFEFF) + "요청").text, "검토요청")

    def test_dash_and_format_chars_do_not_hide_pii_2026_10_1(self):
        """W1 통합 창 결함 회귀(P §4 단계 0): 대시류·서식 문자·띄운 구분자로 쓴 전화·주민·카드·사업자·이메일."""
        d = "".join
        cases = [(d(("010", chr(0x2011), "1234", chr(0x2011), "5678")), "phone"),
                 (d(("010 ", chr(0x2013), " 1234 ", chr(0x2013), " 5678")), "phone"),
                 (d(("02 - 123 - 4567",)), "phone"),
                 (d(("010", chr(0x2060), "1234", chr(0x2060), "5678")), "phone"),
                 (d(("010", chr(0x00AD), "1234", chr(0x00AD), "5678")), "phone"),
                 (d(("주민 900101", chr(0x2212), "1234567")), "rrn"),
                 (d(("카드 4111", chr(0x2010), "1111", chr(0x2010), "1111", chr(0x2010), "1111")), "card"),
                 (d(("사업자 123", chr(0x2011), "45", chr(0x2011), "67890")), "brn"),
                 (d(("hong", chr(0x00AD), "@corp.example.com")), "email"),
                 (d(("hong@", chr(0x2060), "corp.example.com")), "email"),
                 (d(("hong", chr(0x200B), "@corp.example.com")), "email")]
        for text, cat in cases:
            with self.subTest(cat=cat, n=len(text)):
                res = sanitize(text)
                self.assertEqual(res.hits.get(cat), 1, res.hits)
                self.assertNotRegex(res.text, r"\d{4}")
                self.assertNotIn("hong", res.text)

    def test_newline_kept(self):
        self.assertEqual(sanitize("첫 줄\n둘째 줄").text, "첫 줄\n둘째 줄")

    def test_max_scan(self):
        v = _canary("phone").value
        res = sanitize("가" * (MAX_SCAN + 500) + " " + v)
        self.assertLessEqual(len(res.text), MAX_SCAN)
        self.assertNotIn(v, res.text)

    def test_field_name_is_label_only(self):
        c = _canary("account")
        self.assertEqual(sanitize(c.sentence, "a").text, sanitize(c.sentence, "copilot_answer").text)

    def test_result_shape(self):
        res = sanitize(BY_ID["P10"]["text"])
        self.assertEqual(res.rules_ver, rules.RULES_VERSION)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            res.text = "x"

    def test_no_output_side_effects(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for r in CORPUS:
                if "text" in r:
                    sanitize(r["text"])
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))


class SafeTruncateTest(unittest.TestCase):
    def test_short_kept(self):
        self.assertEqual(safe_truncate("abc", 3), "abc")

    def test_cut_with_ellipsis(self):
        self.assertEqual(safe_truncate("abcdefgh", 5), "abcd…")

    def test_never_half_token(self):
        s = "가나다 [고객사:C01] 끝"
        for n in range(5, len(s)):
            out = safe_truncate(s, n)
            with self.subTest(n=n):
                self.assertLessEqual(len(out), n)
                self.assertFalse("[" in out and "]" not in out[out.rfind("["):])

    def test_norm_person(self):
        self.assertEqual(detect.norm_person("김철수 책임"), "김철수")
        self.assertEqual(detect.norm_person("Kim (QA) Chul-Su"), "kimchulsu")


if __name__ == "__main__":
    unittest.main()
