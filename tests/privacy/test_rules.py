# -*- coding: utf-8 -*-
"""WP-10 정제 규칙 시험 — rules.py(P §5)·규칙 해시·잠금(P §16 · L-24), P-T2(규칙 한 글자 변경 → 해시 변화).

말뭉치 값(번호·주소)은 시험 소스에 리터럴로 두지 않고 회귀 말뭉치 파일에서 읽는다(합성 자료 — 계획 §2.9).
"""
import json
import re
import unittest
from unittest import mock

from lm27.privacy import classify, rules, selftest
from lm27.util import fsx

CORPUS = {r["id"]: r for r in selftest.load_corpus()}


def _digits(s):
    return re.sub(r"\D", "", s)


def _first_num(text, rx=r"\d[\d\-]{8,}\d"):
    return re.search(rx, text).group(0)


class VersionHashTest(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(rules.RULES_VERSION, r"^\d{4}\.\d{1,2}\.\d{1,3}$")
        self.assertEqual(rules.RULES_VERSION, "2026.10.0")

    def test_hash_is_16hex_and_stable(self):
        h1, h2 = rules.rules_hash(), rules.rules_hash()
        self.assertRegex(h1, r"^[0-9a-f]{16}$")
        self.assertEqual(h1, h2)
        self.assertEqual(rules.RULES_HASH, h1)                 # 모듈 속성(지연 계산 후 고정)

    def test_unknown_attribute_raises(self):
        with self.assertRaises(AttributeError):
            rules.NO_SUCH_RULE  # noqa: B018

    def test_lock_matches_code_L24(self):
        """L-24: RULES_HASH = rules.lock.json(정규 JSON + LF)."""
        lock = selftest.read_lock()
        self.assertIsNotNone(lock)
        self.assertEqual(lock, {"rules_ver": rules.RULES_VERSION, "rules_hash": rules.rules_hash()})
        raw = fsx.read_bytes(selftest._resource(*selftest.LOCK_REL))
        self.assertEqual(raw, fsx.canon_bytes(json.loads(raw)) + b"\n")
        self.assertTrue(selftest.lock_matches())

    def test_one_char_change_changes_hash_T2(self):
        """P-T2: RX["mobile"] 한 글자 수정 → 해시가 바뀐다(selftest '규칙 고정' 실패의 근거)."""
        base = rules.rules_hash()
        p = rules.RX["mobile"]
        changed = re.compile(p.pattern.replace("{3,4}", "{3,5}", 1), p.flags)
        self.assertNotEqual(changed.pattern, p.pattern)
        with mock.patch.dict(rules.RX, {"mobile": changed}):
            self.assertNotEqual(rules.rules_hash(), base)
        self.assertEqual(rules.rules_hash(), base)

    def test_hash_covers_classify_and_tables(self):
        base = rules.rules_hash()
        cases = [
            (classify, "AD_DROP", 6),
            (classify, "PRIV_THRESHOLD", 3),
            (classify, "PRIVATE_EXES", classify.PRIVATE_EXES | {"x.exe"}),
            (classify, "ABS_HINT", classify.ABS_HINT[:-1]),
            (classify, "P_WEAK", re.compile(classify.P_WEAK.pattern + "?")),
            (rules, "NAME_STOP", rules.NAME_STOP | {"새말"}),
            (rules, "HIGH", rules.HIGH - {"phone"}),
            (rules, "CTX", dict(rules.CTX, ip="(?:ip)")),
            (rules, "PROTECT", rules.PROTECT[:-1]),
            (rules, "RULES_VERSION", "2026.10.1"),
        ]
        for mod, name, val in cases:
            with self.subTest(name=name), mock.patch.object(mod, name, val):
                self.assertNotEqual(rules.rules_hash(), base)
        self.assertEqual(rules.rules_hash(), base)


class CredentialTest(unittest.TestCase):
    def test_drop_corpus_X01_X06(self):
        for i in range(1, 7):
            rid = f"X{i:02d}"
            with self.subTest(rid=rid):
                self.assertTrue(rules.credential_hit(CORPUS[rid]["text"]))

    def test_notice_words_not_credentials(self):
        for rid in ("N10", "N11"):
            with self.subTest(rid=rid):
                self.assertFalse(rules.credential_hit(CORPUS[rid]["text"]))
        self.assertFalse(rules.credential_hit("비밀번호는 정책에 따라 변경"))       # 값 자리가 한글·불용어
        self.assertFalse(rules.credential_hit("password: expired"))

    def test_value_shape(self):
        self.assertTrue(rules.credential_hit("pw: Abcdefgh"))                   # 대소문자 혼합
        self.assertFalse(rules.credential_hit("pw: abcdefgh"))                  # 소문자만 — 값처럼 보이지 않음


class ChecksumTest(unittest.TestCase):
    def test_luhn(self):
        card = _digits(_first_num(CORPUS["P06"]["text"]))
        self.assertTrue(rules.luhn_ok(card))
        bad = card[:-1] + str((int(card[-1]) + 1) % 10)
        self.assertFalse(rules.luhn_ok(bad))

    def test_rrn_checksum_and_date(self):
        p05 = _digits(_first_num(CORPUS["P05"]["text"], r"\d{13}"))
        self.assertTrue(rules.rrn_date_ok(p05))
        self.assertTrue(rules.rrn_checksum_ok(p05))
        lot = _digits(_first_num(CORPUS["N14"]["text"], r"\d{13}"))          # 체크섬이 맞지 않게 만든 LOT 번호
        self.assertFalse(rules.rrn_checksum_ok(lot))
        self.assertFalse(rules.rrn_date_ok("9013011"))                         # 13월
        self.assertFalse(rules.rrn_date_ok("9002301"))                         # 2월 30일
        self.assertFalse(rules.rrn_date_ok("9001019"))                         # 성별 자리 9
        self.assertTrue(rules.rrn_date_ok("0002293"))                          # 2000-02-29(윤년)

    def test_brn(self):
        p18 = _digits(_first_num(CORPUS["P18"]["text"], r"\d{3}-\d{2}-\d{5}"))
        self.assertTrue(rules.brn_ok(p18))
        self.assertFalse(rules.brn_ok(p18[:-1] + str((int(p18[-1]) + 1) % 10)))


class NameRuleTest(unittest.TestCase):
    def test_plausible_korean_name(self):
        self.assertTrue(rules.plausible_korean_name("홍길동"))
        self.assertTrue(rules.plausible_korean_name("남궁민수"))
        self.assertFalse(rules.plausible_korean_name("이번주"))                # NAME_STOP
        self.assertFalse(rules.plausible_korean_name("김개발팀"))              # 조직 접미
        self.assertFalse(rules.plausible_korean_name("김철"))                  # 2자
        self.assertFalse(rules.plausible_korean_name("개발자"))                # 3자 — 첫 글자가 흔한 성 아님

    def test_honorific_mention_label_shapes(self):
        self.assertIsNotNone(rules.HONORIFIC.search("김철수 책임님께"))
        self.assertIsNotNone(rules.MENTION.search("@홍길동 확인"))
        self.assertIsNotNone(rules.LABELED_NAME.search("예금주: 홍길동"))


class TokenGrammarTest(unittest.TestCase):
    TOKENS = ("[주민번호]", "[외국인등록번호]", "[생년월일]", "[카드]", "[전화]", "[사업자번호]", "[법인번호]", "[여권]",
              "[운전면허]", "[계좌]", "[IP]", "[URL]", "[경로]", "[금액]", "[비율]", "[회사]", "[나]", "[사람]",
              "[사람#a1b2c3]", "[고객사:C01]", "[과제:P-0001]", "[과제:P0001]", "[협력사:V01]", "[이메일@사내]",
              "[이메일@개인메일]", "[이메일@외부]", "[이메일@고객사:C01]", "[이메일@협력사:V01]", "[이메일@custa.example]")

    def test_contract_tokens_match(self):
        """계약 §4.6 토큰 전부가 '기존 토큰'(멱등 보호)으로 인식된다."""
        for t in self.TOKENS:
            with self.subTest(t=t):
                self.assertIsNotNone(rules.TOKEN_RX.fullmatch(t))

    def test_non_tokens(self):
        for t in ("[과제X]", "[사람#zzzzzz]", "[고객사:]", "[메모]", "[과제:" + "A" * 17 + "]"):
            with self.subTest(t=t):
                self.assertIsNone(rules.TOKEN_RX.fullmatch(t))


class ConstantsTest(unittest.TestCase):
    def test_high_categories(self):
        self.assertEqual(rules.HIGH, {"rrn", "frn", "birth", "card", "passport", "license", "account", "phone", "email",
                                      "cred", "brn", "corp"})

    def test_personal_mail_domains(self):
        self.assertEqual(len(rules.PERSONAL_MAIL_DOMAINS), 13)
        self.assertEqual(len(set(rules.PERSONAL_MAIL_DOMAINS)), 13)

    def test_detector_table_keys(self):
        want = {"birth", "rrn_front", "rrn", "rrn_masked", "card16", "card15", "card_masked", "mobile", "landline", "rep",
                "intl", "brn", "brn_bare", "corp", "passport", "license", "license_region", "account_hy", "account_bare",
                "ipv4", "ipv6", "url", "email", "path", "money_cur", "money_kor", "money_suffix", "money_kw_adj",
                "money_bare", "rate", "company"}
        self.assertEqual(set(rules.RX), want)
        self.assertEqual([k for k, _ in rules.PROTECT], ["date", "date8", "time", "version", "std"])

    def test_bounded_digit_groups_in_money(self):
        """반복 상한(P §6 구현 주의): 숫자·쉼표 묶음은 {0,24} 상한."""
        for k in ("money_cur", "money_kor", "money_kw_adj"):
            with self.subTest(k=k):
                self.assertIn(r"\d[\d,]{0,24}", rules.RX[k].pattern)
                self.assertNotRegex(rules.RX[k].pattern, r"\[\\d,\][*+]")


if __name__ == "__main__":
    unittest.main()
