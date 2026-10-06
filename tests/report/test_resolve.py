# -*- coding: utf-8 -*-
"""WP-31 로컬 표시 해석과 보고서 변형(R §3.6 · 부록 A `Resolver`).

full = 사람 사전 이름·정제 문서 이름·정제 제목, redacted = 번호표(`동료 #k`·`문서 #k`)·계급 토큰만, 메시지 제목 없음.
가림판 단위업무 제목은 사람 이름·로컬 키·사람 토큰이 없을 때만 그대로, 아니면 일반 제목(`team.unitTitleMode=generic` 이면 늘).
"""
from __future__ import annotations

import unittest

from lm27.report.resolve import KEY_RX, Resolver, external_class, person_names
from tests.fixtures.wp31 import runs as R


def ev():
    return R.rich_run().evidence()


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.pd = R.PERSON_DIR
        self.reg = dict(R.REGISTRY, projects=[{"id": "P-0007", "name": "과제A", "mask_name": False},
                                              {"id": "P-0012", "name": "과제B", "mask_name": True}])
        self.people = {R.KIM: 1, R.PEER2: 2, R.PEER3: 3}
        self.docs = {R.fam_of("f2"): 4}
        self.full = Resolver("full", self.pd, self.reg, ev(), people_ref=self.people, doc_ref=self.docs,
                             proposals=[{"proposal_id": "pr_1", "label": "과제A 후속"}])
        self.red = Resolver("redacted", self.pd, self.reg, None, people_ref=self.people, doc_ref=self.docs,
                            proposals=[{"proposal_id": "pr_1", "label": "과제A 후속"}])

    def test_variant_check(self):
        with self.assertRaises(ValueError):
            Resolver("public")

    def test_person(self):
        self.assertEqual(self.full.person(R.KIM), "김철수")
        self.assertEqual(self.red.person(R.KIM), "동료 #1")
        self.assertEqual(self.full.person(R.ME), "홍길동")             # 본인
        self.assertEqual(self.red.person(R.ME), "나")
        self.assertEqual(Resolver("full", None).person(R.KIM), "동료")  # 사람 사전 없음
        self.assertEqual(Resolver("full", None, people_ref={R.KIM: 7}).person(R.KIM), "동료 #7")

    def test_external(self):
        self.assertEqual(external_class(R.CUST, self.pd, self.reg), ("customer", "C01"))
        self.assertEqual(self.full.who(R.CUST), "[고객사:C01] 고객 담당")
        self.assertEqual(self.red.who(R.CUST), "[고객사:C01]")
        self.assertEqual(self.red.who("w" + "9" * 16), "상대")

    def test_doc_msg_meeting(self):
        f2 = R.fam_of("f2")
        self.assertEqual(self.full.doc(f2), "전원부_검증결과.xlsx")
        self.assertEqual(self.red.doc(f2), "문서 #4")
        self.assertIsNone(Resolver("team").doc(f2))
        k = R.key("m", "msg00", 24)
        self.assertEqual(self.full.msg(k), "[과제:P-0007] 전원부 검증 요청")
        self.assertIsNone(self.red.msg(k))
        self.assertEqual(self.full.meeting("mt1"), "전원부 검토 회의")
        self.assertEqual(self.red.meeting("mt1", "2026-09-04"), "회의 09-04")

    def test_project(self):
        self.assertEqual(self.full.project("P-0007"), "과제A")
        self.assertEqual(self.full.project("P-0012"), "과제B")
        self.assertEqual(self.red.project("P-0012"), "P-0012")       # mask_name → 과제 ID
        self.assertEqual(self.red.project("P-0007"), "과제A")
        self.assertEqual(self.full.project("pr_1"), "과제A 후속")
        self.assertEqual(self.red.project("pr_1"), "pr_1")
        self.assertEqual(self.full.project("UNC"), "과제 없음")

    def test_app(self):
        self.assertEqual(self.full.app("unknown:tool9.exe"), "미상 프로그램(tool9.exe)")
        self.assertEqual(self.red.app("unknown:tool9.exe"), "미상 프로그램")
        self.assertEqual(self.full.app("excel"), "Excel")

    def test_unit_title(self):
        self.assertEqual(self.red.unit_title("전원부 검증", "회로·해석 단위업무 #1"), "전원부 검증")
        self.assertEqual(self.red.unit_title("김철수 요청 건", "회로·해석 단위업무 #1"), "회로·해석 단위업무 #1")
        self.assertEqual(self.red.unit_title("[사람#a1b2c3] 회신", "g"), "g")
        self.assertEqual(self.red.unit_title("자료 " + R.fam_of("x"), "g"), "g")
        self.assertEqual(self.full.unit_title("김철수 요청 건", "g"), "김철수 요청 건")
        gen = Resolver("redacted", self.pd, title_mode="generic")
        self.assertEqual(gen.unit_title("전원부 검증", "g"), "g")

    def test_person_names_and_key_rx(self):
        names = person_names(self.pd)
        self.assertIn("김철수", names)
        self.assertIn("홍길동", names)
        self.assertNotIn("나", person_names({"people": {"x": {"names": ["나", "AB"]}}}))
        self.assertTrue(KEY_RX.search("x " + R.KIM + " y"))
        self.assertTrue(KEY_RX.search(R.key("m", "a", 24)))
        self.assertFalse(KEY_RX.search("u_0123456789"))             # 단위업무 ID 는 팀 반출 허용 값
        self.assertFalse(KEY_RX.search("r_5c0d11"))
        self.assertFalse(KEY_RX.search("9f2c01ab3e4d"))             # qid


if __name__ == "__main__":
    unittest.main()
