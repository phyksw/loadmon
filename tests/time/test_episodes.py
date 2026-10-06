# -*- coding: utf-8 -*-
"""WP-20 단위업무 형성(W §4 · 계약 §4.2 unit_id · §6.4 등급·경계 근거 · X-204 · X-207).

등급 조합표 · unit_id(HMAC 하위 키) · 키만 담은 표지 · 대화 상태기계(1:1 상시방·다대다·조율형·재의뢰·NEXT_REQ) ·
반복 문서와 follow_of · 범용 이름 · 회의 연결(주최자 키 없음 → 참석자로 판정) · 확인 응답(증거 키 — 업무 ID 가 바뀌어도 유지)
· 커버리지 보류 · 미착수 · 선행 착수 · 기계 시간 · 결정성.
"""
from __future__ import annotations

import hashlib
import hmac
import unittest

from lm27.time.episodes import EG, SG, TaskList, build_tasks, completion, grade_of, make_unit_key, team_bounds
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

# W §4.10.2 조합표(시작 7 × 종료 10)
TABLE = {
    "S1": "A A B B B C C D D O", "S1o": "A A B B B C C D D O", "S1d": "B B C B B C C D D O",
    "S2a": "B B B B B C C D D O", "S2M": "B B B B B C C D D O", "S2m": "C C C C C D C E E O",
    "S2p": "C C C C C D C E E O",
}
ENDS = ("E1", "E1i", "E1d", "E2h", "E3M", "E2l", "E3c", "NEXT_REQ", "E3i", "OPEN")


def by_label(res, names):
    return {H.ref_label(names, t.label): t for t in res.tasks}


class GradeTest(unittest.TestCase):
    def test_combination_table(self):
        for sb, row in TABLE.items():
            for eb, g in zip(ENDS, row.split(), strict=True):
                with self.subTest(sb=sb, eb=eb):
                    self.assertEqual(grade_of(sb, eb), g)
        self.assertEqual(grade_of("S1", None), "O")
        self.assertEqual(set(SG), set(TABLE))
        self.assertEqual(set(EG) | {"OPEN"}, set(ENDS))


class TeamBoundsTest(unittest.TestCase):
    """W §4.11 시간 코어 → 팀 묶음 경계 대응(TAB §2.3 · X-207)."""

    def test_mapping_table(self):
        self.assertEqual(team_bounds("S1", "E1", "A"), {"start_kind": "S1i", "start_precision": "minute",
                                                         "end_kind": "E1o", "end_precision": "minute",
                                                         "grade": "A", "status": "closed"})
        self.assertEqual(team_bounds("S1d", "E1d", "C")["start_precision"], "date")
        self.assertEqual(team_bounds("S2p", "E3i", "E")["end_kind"], "E3i")                # X-207 E3i
        self.assertEqual(team_bounds("S2p", "NEXT_REQ", "E")["status"], "estimated")
        self.assertEqual(team_bounds("S2M", "E3M", "M")["start_kind"], "M")
        self.assertEqual(team_bounds("S2M", "E3M", "M")["grade"], "M")                      # X-207 M
        o = team_bounds("S1o", "OPEN", "O")
        self.assertEqual((o["end_kind"], o["grade"], o["status"]), (None, "A", "open"))      # 잠정 = 시작 등급
        self.assertIsNone(team_bounds("S1", "OPEN", "Z"))                                   # 미착수는 올리지 않음
        for sb in SG:
            for eb in EG:
                b = team_bounds(sb, eb, grade_of(sb, eb))
                self.assertIn(b["start_kind"], ("S1i", "S1o", "S2", "M"))
                self.assertIn(b["end_kind"], ("E1o", "E1i", "E2", "E3c", "E3i", "M"))
                self.assertIn(b["start_precision"], ("exact", "minute", "date", "none"))


class UnitKeyTest(unittest.TestCase):
    def test_bytes_key_is_hmac_of_start_key(self):
        fn = make_unit_key(H.TEST_KEY)
        want = "u_" + hmac.new(H.TEST_KEY, b"m0123", hashlib.sha256).hexdigest()[:10]
        self.assertEqual(fn("m0123", "S1"), want)
        self.assertEqual(fn("m0123", "S1"), fn("m0123", "ACK"))        # 종류는 재료가 아니다(W §4.11)
        self.assertNotEqual(fn("m0123", "S1"), fn("m0124", "S1"))
        self.assertRegex(fn("x", "SELF"), r"^u_[0-9a-f]{10}$")

    def test_rejects_public_or_missing_key(self):
        with self.assertRaises(TypeError):
            make_unit_key("p_0123456789ab")                          # 번들 소유자 ID 는 비밀 키가 아니다
        with self.assertRaises(ValueError):
            make_unit_key(None)
        with self.assertRaises(ValueError):
            make_unit_key(b"short")

    def test_callable_key(self):
        fn = make_unit_key(lambda s, k: "abcdef0123")
        self.assertEqual(fn("x", "S1"), "u_abcdef0123")

    def test_keyring_object_uses_privacy_keyed(self):
        """키링 객체는 lm27.privacy.keys.keyed(kr, 'unit', 시작 근거 키, 10) 로 만든다(계약 §4.2 — 지연 import)."""
        from unittest import mock
        calls = []

        def fake_keyed(kr, purpose, value, n=16):
            calls.append((kr, purpose, value, n))
            return "0123456789abcdef"[:n]
        kr = object()
        with mock.patch("lm27.privacy.keys.keyed", fake_keyed, create=True):
            fn = make_unit_key(kr)
            self.assertEqual(fn("m0123", "S1"), "u_0123456789")
        self.assertEqual(calls, [(kr, "unit", "m0123", 10)])


class StateMachineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.cache = {}

    def run_sc(self, name):
        if name not in self.cache:
            self.cache[name] = H.run(X.SC[name](), self.cfg, ref_ids=False)
        return self.cache[name]

    def test_labels_and_keys_only(self):
        """표지·first_key 에 문서 이름·대화 이름 원문이 없다(키만) — 원장 PII 0(W-G8)."""
        for name, fn in X.SC.items():
            w = fn()
            res, names = H.run(w, self.cfg, ref_ids=False)
            words = {X.fam(d["doc"]) for d in w.docs} | {m["conv"] for m in w.msgs} | \
                {X.fam(s["doc"]) for s in w.samples if s["doc"]}
            words = {x for x in words if len(x) >= 3}
            for t in res.tasks:
                with self.subTest(name=name, label=t.label):
                    self.assertRegex(t.id, r"^u_[0-9a-f]{10}$")
                    for x in words:
                        self.assertNotIn(x, t.label)
                        self.assertNotIn(x, t.first_key)

    def test_unit_id_from_start_key(self):
        res, names = self.run_sc("W01")
        fn = make_unit_key(H.TEST_KEY)
        for t in res.tasks:
            self.assertEqual(t.id, fn(t.first_key, t.kind))
        s1 = by_label(res, names)["S1:chat_kim#1"]
        self.assertEqual(s1.first_key, X.msg_key("k1"))              # S1 = 그 의뢰 메시지 msg_key
        self.assertTrue(by_label(res, names)["SELF:주간회의록_과제b@10-13"].first_key.endswith("|2026-10-13"))

    def test_one_to_one_room_two_topics(self):
        res, names = self.run_sc("W17")
        t = by_label(res, names)
        self.assertEqual({t["S1:chat_p31#1"].grade, t["S1:chat_p31#2"].grade}, {"A"})
        self.assertTrue(any(f.startswith("수락 ") for f in t["S1:chat_p31#1"].flags))

    def test_many_to_many_close(self):
        res, names = self.run_sc("W18")
        t = by_label(res, names)
        self.assertEqual(t["S1:M1#1"].cycles[-1].e, t["S1:M2#1"].cycles[-1].e)
        self.assertIn("다대다 종료", t["S1:M2#1"].flags)

    def test_coordinator_task(self):
        res, names = self.run_sc("W19")
        t = by_label(res, names)["COORD:M21#1"]
        self.assertEqual((t.kind, t.cycles[0].sb, t.grade), ("COORD", "S1o", "A"))
        self.assertIn("보완보고(끝 연장)", t.flags)
        self.assertEqual(round(res.effort()[t.id] / 3600, 2), 2.67)
        self.assertIn("reporter", set().union(*t.rels.values()))

    def test_recurring_doc_follow_of_chain(self):
        res, names = self.run_sc("W20")
        selfs = sorted((t for t in res.tasks if t.kind == "SELF"), key=lambda t: t.cycles[0].s)
        self.assertEqual(len(selfs), 8)
        self.assertIsNone(selfs[0].follow_of)
        for a, b in zip(selfs, selfs[1:], strict=False):
            self.assertEqual(b.follow_of, a.id)                     # 같은 문서군의 앞 인스턴스로만 잇는다

    def test_generic_name_without_folder(self):
        """폴더를 모르는 범용 이름(B_GENERIC)은 자체 업무를 만들지 않고, 첨부로 이어진 업무 창으로만 나뉜다(W21)."""
        res, names = self.run_sc("W21")
        self.assertFalse([t for t in res.tasks if t.kind == "SELF"])
        t = by_label(res, names)
        self.assertEqual({t["S1:M1#1"].grade, t["S1:M2#1"].grade}, {"A"})
        self.assertIn("B_GENERIC", t["S1:M1#1"].docs)

    def test_rework_and_next_request_cycles(self):
        res, names = self.run_sc("W13")
        self.assertEqual(len(by_label(res, names)["S1:M13#1"].cycles), 2)
        res, names = self.run_sc("W16")
        t = by_label(res, names)["S1:M16#1"]
        self.assertEqual([c.eb for c in t.cycles], ["NEXT_REQ", "E3i"])
        self.assertEqual(t.grade, "D")

    def test_meeting_link_by_attendees(self):
        """주최자 키는 저장하지 않으므로(X-204 — organizer 는 'self'·'') 의뢰자 동석은 참석자로 판정한다."""
        res, names = self.run_sc("W08")
        t = by_label(res, names)["S1:M8#1"]
        self.assertTrue(all(mt.organizer in ("self", "") for mt in res.env.counted_meetings))
        self.assertEqual(t.cycles[-1].eb, "E3c")
        self.assertEqual(t.grade, "C")
        mt = next(m for m, _ in t.meet_refs)
        self.assertEqual(t.cycles[-1].e, mt.b)
        res, names = self.run_sc("W05")
        t = by_label(res, names)["SELF:원가분석_과제b@10-13"]
        self.assertEqual(t.cycles[0].sb, "S2m")

    def test_manual_answers_survive_task_identity_change(self):
        a, na = self.run_sc("W47A")
        b, nb = self.run_sc("W47B")
        ta = by_label(a, na)["SELF:점검표_과제h@09-14"]
        tb = by_label(b, nb)["S1:M47#1"]
        self.assertNotEqual(ta.id, tb.id)                          # 업무 종류·ID 는 바뀐다
        self.assertEqual(ta.cycles[-1].eb, "E3M")
        self.assertEqual(tb.cycles[-1].eb, "E3M")                  # 응답은 증거 키로 따라간다
        self.assertEqual(ta.cycles[-1].e, tb.cycles[-1].e)

    def test_coverage_hold_and_unstarted(self):
        res, names = self.run_sc("W55")
        t = by_label(res, names)["S1:M7#1"]
        self.assertEqual((t.cycles[-1].eb, t.grade), ("OPEN", "O"))
        self.assertTrue(any(q.code == "Q03" and q.target == t.id for q in res.queue))
        res, names = self.run_sc("W10")
        t = by_label(res, names)["S1:chat_z#1"]
        self.assertEqual((t.grade, t.status), ("Z", "not_started"))
        self.assertEqual(res.effort().get(t.id, 0), 0)
        self.assertTrue(any(q.code == "Q02" and q.target == t.id for q in res.queue))

    def test_must_link(self):
        a, na = self.run_sc("W67A")
        b, nb = self.run_sc("W67B")
        self.assertEqual(by_label(a, na)["S1:M67#1"].grade, "Z")
        self.assertGreater(b.effort()[by_label(b, nb)["S1:M67#1"].id], 7 * 3600)

    def test_pre_start_and_machine_time(self):
        res, names = self.run_sc("W15")
        t = by_label(res, names)["S1:M15#1"]
        self.assertIn("선행착수(공식 의뢰 전 작업)", t.flags)
        self.assertEqual(t.pre_request_s, 3 * 3600)
        res, names = self.run_sc("W42")
        t = by_label(res, names)["SELF:열해석_모델@10-19"]
        self.assertEqual(t.machine_s, int(11.5 * 3600))
        self.assertEqual(t.machine_iv[0][1] - t.machine_iv[0][0], int(11.5 * 3600))

    def test_completion_score(self):
        """W02: 목 15:00 저장 + 15:05 PDF 내보내기 + 3근무일 조용 = 0.7 → E2h(15:05)."""
        w = X.SC["W02"]()
        ev, days, env, c = X.run_env(w, self.cfg)
        tasks, _q = build_tasks(ev, env, days, c, X.calendar(), unit_key=H.TEST_KEY)
        self.assertIsInstance(tasks, TaskList)
        t = next(t for t in tasks if t.kind == "S1")
        self.assertEqual(t.cycles[-1].eb, "E2h")
        nxt = ev.as_of + 1
        t.cycles[-1].e = None
        e2 = completion(t, t.cycles[-1], nxt, tasks.ctx)
        self.assertIsNotNone(e2)
        self.assertEqual(e2[1:], ("E2h", 0.7))

    def test_deterministic_ids_across_shuffles(self):
        for name in ("W01", "W18", "W20", "W45", "W61"):
            a, _ = H.run(X.SC[name](), self.cfg, ref_ids=False)
            for seed in (1, 2):
                b, _ = H.run(X.SC[name](), self.cfg, ref_ids=False, shuffle=seed)
                self.assertEqual([(t.id, t.label, t.grade) for t in a.tasks],
                                 [(t.id, t.label, t.grade) for t in b.tasks], (name, seed))


if __name__ == "__main__":
    unittest.main()
