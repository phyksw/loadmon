# -*- coding: utf-8 -*-
"""WP-18 act — 화행 판정(CT §6 · CT-10) · 수동 태깅(CT-18 · X-091) · 코파일럿 답(B §8.2 · X-090) · 회색 지대 항목.

CT-10: 지시 어미 수신 → request, '확인'·'공유' 포함 발신 → report, 낱말 부분 일치로 지시를 만들지 않음, 경로 무관 같은 판정.
CT-18: tag_feedback.json 의 화행이 자동 판정을 덮는다(원문 없음 — 키·열거·시각만)."""
import json
import unittest

from lm27.normalize import act as A
from lm27.normalize.act import ACTS, classify_act
from tests.fixtures.wp18 import rows as R

T = "2026-09-01T01:00:00Z"


def recv_teams(body, **kw):
    return R.teams(T, body=body, author=R.KIM, **kw)


def sent_teams(body, **kw):
    return R.teams(T, body=body, author="self", **kw)


def recv_mail(subject, **kw):
    return R.mail(T, subject=subject, **kw)


def sent_mail(subject, **kw):
    return R.mail(T, subject=subject, box="sent", **kw)


class Ct10Test(unittest.TestCase):
    """CT-10 — 지시 어미 수신 → request, 확인·공유 포함 발신 → report, 부분 일치 오더 과대 없음, 경로 무관 동일."""

    def test_request_ending_received_is_request(self):
        for row in (recv_teams("[과제:P-0001] 도면 검토 부탁드립니다. 금요일까지 회신 바랍니다"),
                    recv_mail("[과제:P-0001] 도면 검토 부탁드립니다")):
            act, conf = classify_act(row)
            self.assertEqual(act, "request", row["kind"])
            self.assertGreaterEqual(conf, 0.6)

    def test_confirm_share_sent_is_report(self):
        for text in ("검토 결과 공유드립니다. 확인 부탁드립니다.", "확인했습니다. 공유드립니다",
                     "RE: 시험 결과 송부드립니다 [사람]님 확인 부탁드립니다"):
            for row in (sent_teams(text), sent_mail(text)):
                self.assertEqual(classify_act(row)[0], "report", (text, row["kind"]))

    def test_partial_words_do_not_make_request(self):
        for text in ("확인 필요", "일정 공유", "가능 여부 확인", "필요한 자료 송부드립니다", "공유 폴더 정리",
                     "회의 일정 확인했습니다"):
            for row in (recv_teams(text), recv_mail(text)):
                self.assertNotEqual(classify_act(row)[0], "request", (text, row["kind"]))

    def test_same_rule_on_every_path(self):
        text = "[과제:P-0001] 도면 검토 부탁드립니다"
        acts = {classify_act(recv_teams(text, src=s))[0] for s in ("teams.uia", "teams.web")}
        acts |= {classify_act(recv_mail(text, src=s))[0] for s in ("mail.com", "mail.index", "mail.owa", "mail.import")}
        self.assertEqual(acts, {"request"})

    def test_stored_cues_from_body_are_used(self):
        row = recv_mail("RE: 주간 자료", cues=("req", "sched"))      # 제목엔 단서 없음 — 본문 단서(수집 때 원문)
        self.assertEqual(classify_act(row), ("request", 0.65))


class ActRulesTest(unittest.TestCase):
    def test_ack_and_question(self):
        self.assertEqual(classify_act(recv_teams("넵")), ("ack", 0.75))
        self.assertEqual(classify_act(sent_teams("확인했습니다, 오늘 안에 보겠습니다"))[0], "ack")
        self.assertEqual(classify_act(recv_teams("회의실이 어디인가요?", chat_type="group")), ("question", 0.5))

    def test_one_to_one_question_is_gray_request(self):
        act, conf = classify_act(recv_teams("자료 위치가 어디인가요?", chat_type="1:1"))
        self.assertEqual(act, "question")
        row = recv_teams("이번 주 시간 되시나요?", chat_type="1:1")
        act, conf = classify_act(row)
        self.assertIn(act, ("question", "request"))
        self.assertTrue(A.is_gray(act, conf))

    def test_deadline_question_is_request(self):
        act, conf = classify_act(recv_teams("내일까지 가능할까요?", chat_type="group"))
        self.assertEqual((act, conf), ("request", 0.55))

    def test_received_report_and_done(self):
        self.assertEqual(classify_act(recv_teams("회의록 공유드립니다")), ("report", 0.55))
        self.assertEqual(classify_act(recv_teams("반영했습니다. 결과 공유드립니다")), ("report", 0.6))
        act, conf = classify_act(recv_teams("결과 첨부드리니 확인 부탁드립니다"))
        self.assertEqual((act, conf), ("request", 0.5))
        self.assertTrue(A.is_gray(act, conf), "받은 보고 + 요청 어미 = 회색 지대(코파일럿에 묻는다)")
        self.assertEqual(classify_act(recv_teams("금요일까지 회신"))[0], "request")

    def test_sent_request_and_report_with_attachment(self):
        self.assertEqual(classify_act(sent_teams("내일까지 검토 부탁드립니다")), ("request", 0.65))
        row = sent_mail("시험 결과 송부드립니다", attach_keys=[R.doc("결과")])
        self.assertEqual(classify_act(row), ("report", 0.65))

    def test_notice(self):
        notice = recv_mail("Microsoft Teams 놓친 활동", flags={"teams_notice": True})
        self.assertEqual(classify_act(notice), ("notice", 0.95))
        news = recv_mail("월간 소식 안내", flags={"list_unsub": True})
        self.assertEqual(classify_act(news), ("notice", 0.85))
        dl = recv_mail("주간 회의록", rcv="bulk", flags={"bulk": True})
        self.assertEqual(classify_act(dl)[0], "notice")
        dl_req = recv_mail("각자 주간보고 작성 부탁드립니다", rcv="bulk", flags={"bulk": True})
        self.assertEqual(classify_act(dl_req), ("request", 0.5))
        chan = recv_teams("[공지] 보안 점검 안내", chat_type="channel")
        self.assertEqual(classify_act(chan)[0], "notice")

    def test_social(self):
        self.assertEqual(classify_act(recv_teams("감사합니다~ 수고하셨습니다 ^^")), ("social", 0.7))
        self.assertEqual(classify_act(recv_teams("감사합니다. 도면 검토 부탁드립니다"))[0], "request")
        self.assertEqual(classify_act(recv_teams("주말 잘 보내세요", priv_class="social")), ("social", 0.9))

    def test_meeting_response_is_info(self):
        row = sent_mail("수락: 주간 회의", flags={"meeting_response": True})
        self.assertEqual(classify_act(row), ("info", 0.7))

    def test_pm_weight_and_cc(self):
        row = recv_mail("도면 검토 부탁드립니다", sender=R.LEE)
        self.assertEqual(classify_act(row)[1], 0.6)
        ctx = A.ActContext(pm_keys=frozenset({R.LEE}))
        self.assertEqual(classify_act(row, ctx)[1], 0.65)
        self.assertEqual(classify_act(recv_mail("도면 검토 부탁드립니다", rcv="cc", flags={"cc": True}))[1], 0.5)
        mention = recv_teams("@[사람] 자료 부탁드립니다", chat_type="group", flags={"mentions_me": True})
        self.assertEqual(classify_act(mention), ("request", 0.65))

    def test_context_from_cfg(self):
        sb = R.Sandbox()
        self.addCleanup(sb.remove)
        ctx = A.act_context(sb.cfg(**{"teams.pmWhoKeys": [R.LEE]}))
        self.assertEqual(ctx.pm_keys, frozenset({R.LEE}))
        self.assertEqual(A.act_context({"teams.pmWhoKeys": [R.LEE, "실명"]}).pm_keys, frozenset({R.LEE}))
        self.assertEqual(A.act_context(None), A.ActContext())

    def test_private_row_and_other_kinds(self):
        row = recv_teams("", priv_class="private")
        self.assertEqual(classify_act(row), ("info", 0.3))
        for r in (R.session(T), R.git(T), R.manual(T), R.cal(T, R.plus(T, hours=1))):
            self.assertEqual(classify_act(r), ("", 0.0))

    def test_result_always_in_vocab_and_stable(self):
        texts = ["", "넵", "?", "검토 부탁드립니다", "결과 공유", "완료", "취소", "참고", "감사합니다", "x" * 400]
        for t in texts:
            for row in (recv_teams(t), sent_teams(t), recv_mail(t), sent_mail(t)):
                act, conf = classify_act(row)
                self.assertIn(act, ACTS)
                self.assertTrue(0.0 <= conf <= 1.0)
                self.assertEqual((act, conf), classify_act(json.loads(json.dumps(row))))


class ManualTagTest(R.SandboxCase):
    """CT-18 · X-091 — 수동 태깅 파일(키·열거·시각만)."""

    def test_round_trip_and_file_shape(self):
        k1, k2 = R.mk("a"), R.mk("b")
        got = A.save_tag(self.paths, k1, "request", now="2026-09-02T01:00:00Z")
        self.assertEqual(got, {"act": "request", "by": "user", "at": "2026-09-02T01:00:00Z"})
        A.save_tag(self.paths, k2, "report", now="2026-09-02T01:05:00Z")
        self.assertEqual(A.load_tags(self.paths), {k1: "request", k2: "report"})
        raw = self.paths.local_only_file(A.TAG_FILE).read_bytes()
        obj = json.loads(raw)
        self.assertEqual(set(obj), {k1, k2})
        for v in obj.values():
            self.assertEqual(set(v), {"act", "by", "at"})
        self.assertNotIn(b"\r", raw)
        A.save_tag(self.paths, k1, None)
        self.assertEqual(A.load_tags(self.paths), {k2: "report"})

    def test_bad_inputs_rejected(self):
        for mk_, act in (("m123", "request"), (R.ek("x"), "request"), ("", "ack"), (R.mk("a"), "order"),
                         (R.mk("a"), "지시")):
            with self.assertRaises(ValueError):
                A.save_tag(self.paths, mk_, act)
        self.assertFalse(self.paths.local_only_file(A.TAG_FILE).exists())

    def test_malformed_entries_ignored(self):
        from lm27.util import fsx
        k = R.mk("ok")
        fsx.atomic_write(self.paths.local_only_file(A.TAG_FILE), fsx.canon_bytes({
            k: {"act": "ack", "by": "user", "at": "2026-09-02T01:00:00Z"},
            "nonkey": {"act": "ack"}, R.mk("bad"): {"act": "지시"}, R.mk("bad2"): "request"}))
        self.assertEqual(A.load_tags(self.paths), {k: "ack"})
        empty = R.Sandbox()
        self.addCleanup(empty.remove)
        self.assertEqual(A.load_tags(empty.paths), {})


class AiActsTest(R.SandboxCase):
    """B §8.2 — by=ai·manual 이고 conf h·m 인 답만 덮어쓸 자격이 있다."""

    def write_ai_out(self, items):
        from lm27.util import fsx
        fsx.atomic_write(self.paths.ai_out(A.AI_STAGE), fsx.canon_bytes({
            "schema": 1, "stage": "speech_act", "stage_ver": "speech_act/1.0", "run_id": "20261005-101500-3fa2",
            "items": items}))

    def test_only_confident_ai_answers(self):
        k = [R.mk(i) for i in range(6)]
        self.write_ai_out({
            "msg:" + k[0]: {"ans": {"act": "request", "conf": "h"}, "by": "ai"},
            "msg:" + k[1]: {"ans": {"act": "ack", "conf": "m"}, "by": "manual"},
            "msg:" + k[2]: {"ans": {"act": "report", "conf": "l"}, "by": "ai"},
            "msg:" + k[3]: {"ans": {"act": "info", "conf": "h"}, "by": "rule"},
            "msg:" + k[4]: {"ans": {"act": "지시", "conf": "h"}, "by": "ai"},
            k[5]: {"ans": {"act": "question", "conf": "h"}, "by": "ai"},
            "msg:zz": {"ans": {"act": "ack", "conf": "h"}, "by": "ai"}})
        self.assertEqual(A.load_ai_acts(self.paths), {k[0]: ("request", 0.9), k[1]: ("ack", 0.75),
                                                       k[5]: ("question", 0.9)})

    def test_missing_or_broken_file(self):
        self.assertEqual(A.load_ai_acts(self.paths), {})


class SpeechActItemsTest(R.SandboxCase):
    def rows(self):
        gray = recv_teams("이번 주 시간 되시나요?", chat_type="1:1", room="G")
        sure = recv_teams("도면 검토 부탁드립니다", chat_type="1:1", room="G")
        sure["ts_utc"] = R.plus(T, minutes=-5)
        grp = recv_teams("다들 시간 되시나요?", chat_type="group", room="X")
        cp = R.teams(T, src="teams.copilot", body="이번 주 시간 되시나요?", prec="summary", room="G2")
        priv = recv_teams("이번 주 시간 되시나요?", chat_type="1:1", room="P", priv_class="private")
        tagged = dict(recv_teams("오늘 시간 되시나요?", chat_type="1:1", room="M"), act="question", act_conf=0.45,
                      act_source="manual")
        return [gray, sure, grp, cp, priv, tagged]

    def test_gray_zone_only(self):
        items = A.speech_act_items(self.rows())
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertTrue(it["key"].startswith("msg:m"))
        self.assertEqual(set(it), {"key", "group", "fields", "rule", "src_ver", "meta"})
        self.assertEqual(set(it["fields"]), {"ch", "dir", "chat", "prev", "text"})
        self.assertEqual(it["fields"]["dir"], "in")
        self.assertEqual(it["fields"]["chat"], "1:1")
        self.assertEqual(it["fields"]["prev"], "request", "같은 대화의 직전 화행")
        self.assertLessEqual(len(it["fields"]["text"]), 120)
        self.assertTrue(A.is_gray(it["rule"]["act"], it["rule"]["score"]))
        self.assertEqual(it["meta"]["priv_class"], "work")

    def test_write_ai_in(self):
        n = A.write_speech_act_in(self.paths, self.rows())
        self.assertEqual(n, 1)
        lines = self.paths.ai_in(A.AI_STAGE).read_bytes().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["key"], A.speech_act_items(self.rows())[0]["key"])
        self.assertEqual(A.write_speech_act_in(self.paths, []), 0)
        self.assertEqual(self.paths.ai_in(A.AI_STAGE).read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
