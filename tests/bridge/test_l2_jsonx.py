# -*- coding: utf-8 -*-
"""WP-24 L2 답 해석(B §6.4) — 정규화 · 봉투 추출 · 잘린 JSON 복구(문자열 안 '}' 오판 없음, B-T28) · 수동 반입 봉투."""
from __future__ import annotations

import unittest

from lm27.bridge import jsonx

RID = "R7F3QK"
GOOD = ('```json\n{"rid":"R7F3QK","n":3,"items":[{"id":1,"act":"request","conf":"h"},'
        '{"id":2,"act":"report","conf":"m"},{"id":3,"act":"info","conf":"l"}]}\n```\n[[END R7F3QK]]')


class Normalize(unittest.TestCase):
    def test_fence_quotes_pledge(self):
        t, cut = jsonx.normalize('```json\n{“rid”: "R7F3QK"}\n```\n[[END R7F3QK]] <<END R22222>>')
        self.assertFalse(cut)
        self.assertNotIn("```", t)
        self.assertNotIn("[[END", t)
        self.assertNotIn("<<END", t)
        self.assertIn('{"rid": "R7F3QK"}', t)

    def test_stop_mark_only_in_tail(self):
        body = '{"rid":"R7F3QK","n":2,"items":[{"id":1}' + "\n\nOK, I've stopped generating the response."
        t, cut = jsonx.normalize(body)
        self.assertTrue(cut)
        self.assertNotIn("stopped", t)
        far = "stopped generating 이라는 말이 본문 앞에 인용됨 " + "가" * (jsonx.STOP_TAIL + 50)
        t2, cut2 = jsonx.normalize(far)
        self.assertFalse(cut2)
        self.assertEqual(t2, far)


class Extract(unittest.TestCase):
    def test_strict_and_pledge(self):
        x = jsonx.extract(GOOD, RID)
        self.assertEqual((x.kind, x.how, x.pledge, x.cut), ("env", "strict", True, False))
        self.assertEqual(len(x.obj["items"]), 3)

    def test_smart_quotes_ok(self):
        x = jsonx.extract(GOOD.replace('"act":"info"', '“act”:“info”'), RID)
        self.assertEqual((x.kind, x.how), ("env", "strict"))

    def test_truncated_brace_inside_string(self):
        """B-T28: 문자열 안 '}' 가 든 잘린 답 — 항목 1 만 정확히 살린다(괄호 개수 근사 폐기)."""
        body = ('{"rid":"R7F3QK","n":3,"items":[{"id":1,"act":"request","conf":"h"},'
                '{"id":2,"act":"report","note":"설계안} 검토 후 B')
        x = jsonx.extract(body, RID)
        self.assertEqual((x.kind, x.how), ("env", "salvaged"))
        self.assertEqual([i["id"] for i in x.obj["items"]], [1])

    def test_truncated_no_complete_element_keeps_rid(self):
        x = jsonx.extract('{"rid":"R7F3QK","n":3,"items":[{"id":1,"act":"req', RID)
        self.assertEqual((x.kind, x.how), ("env", "salvaged"))
        self.assertEqual((x.obj["rid"], x.obj["n"], x.obj["items"]), ("R7F3QK", 3, []))

    def test_cut_marker(self):
        body = ('{"rid":"R7F3QK","n":3,"items":[{"id":1,"act":"request"},{"id":2,"act":"rep'
                "\n\nOK, I've stopped generating the response.")
        x = jsonx.extract(body, RID)
        self.assertTrue(x.cut)
        self.assertEqual(x.how, "salvaged")

    def test_stale_and_echo(self):
        self.assertEqual(jsonx.extract(GOOD.replace("R7F3QK", "R2K9MP"), RID).kind, "stale")
        echo = '{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack>} ]}'
        self.assertEqual(jsonx.extract(echo, RID).kind, "echo")
        self.assertEqual(jsonx.extract('{"rid": "샘플", "items": []}', RID).kind, "echo")

    def test_none(self):
        self.assertEqual(jsonx.extract("요청하신 내용을 검토했습니다.", RID).kind, "none")

    def test_last_envelope_wins(self):
        body = '{"rid":"R7F3QK","n":1,"items":[{"id":1,"v":"a"}]}\n{"rid":"R7F3QK","n":1,"items":[{"id":1,"v":"b"}]}'
        self.assertEqual(jsonx.extract(body, RID).obj["items"][0]["v"], "b")

    def test_close_truncated_strict_when_closed(self):
        o, how, end = jsonx.close_truncated('{"rid":"R7F3QK","items":[{"id":1}]} 꼬리', 0)
        self.assertEqual((how, o["items"]), ("strict", [{"id": 1}]))


class AllEnvelopes(unittest.TestCase):
    def test_many_answers_any_order_dedupe(self):
        a = '```json\n{"rid":"R2AAAA","n":1,"items":[{"id":1,"w":"x"}]}\n```\n[[END R2AAAA]]'
        b = '```json\n{"rid":"R3BBBB","n":2,"items":[{"id":1,"w":"y"},{"id":2,"w":"z"}]}\n```'
        c = '{"rid":"R4CCCC","n":2,"items":[{"id":1,"w":"q"},{"id":2,"w":"잘'
        found = jsonx.all_envelopes(b + "\n잡담\n" + a + "\n" + c + "\n" + a)
        self.assertEqual(sorted(e.rid for e in found), ["R2AAAA", "R3BBBB", "R4CCCC"])
        by = {e.rid: e for e in found}
        self.assertEqual(by["R4CCCC"].how, "salvaged")
        self.assertEqual(jsonx.extract(by["R4CCCC"].segment, "R4CCCC").how, "salvaged")
        self.assertEqual(jsonx.extract(by["R3BBBB"].segment, "R3BBBB").kind, "env")

    def test_no_envelope(self):
        self.assertEqual(jsonx.all_envelopes("그냥 글입니다"), [])


if __name__ == "__main__":
    unittest.main()
