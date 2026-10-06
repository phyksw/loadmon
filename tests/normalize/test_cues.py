# -*- coding: utf-8 -*-
"""WP-18 cues — 화행 단서 추출(정제기 훅 · 계약 §3.1 act_cues · O-12 · CT §6 · X-305).

닫힌 어휘·순서 · 요청 어미(낱말 부분 일치 금지 — CT-10) · 송부·완료·수락·질문·기한·취소·공지 · 참고/양해 '바랍니다' 구분 ·
인용(지난 대화) 무시 · 제목 꼬리표 · 정제 토큰 무시 · 병적 입력 · 에이전트 사본 import 범위(표준 라이브러리만) ·
정제기(sanitize_record) 훅 연결."""
import ast
import sys
import unittest
from pathlib import Path

from lm27.normalize import cues as C
from lm27.normalize.cues import ACT_CUES, extract

ROOT = Path(__file__).resolve().parents[2]


class VocabularyTest(unittest.TestCase):
    def test_closed_vocab_order_no_dups(self):
        texts = ["", "넵", "검토 부탁드립니다?", "[공지] 회의 취소 안내 — 9/30까지 회신 요망. 결과 공유드립니다. 완료했습니다",
                 "x" * 50, "?" * 10, "please find attached. could you review by eod? noted. cancelled. fyi"]
        for t in texts:
            got = extract(t)
            self.assertTrue(set(got) <= set(ACT_CUES), got)
            self.assertEqual(got, [c for c in ACT_CUES if c in got], "ACT_CUES 순서")
            self.assertEqual(len(got), len(set(got)))
        self.assertEqual(ACT_CUES, ("req", "rep", "done", "ack", "ask", "sched", "cancel", "fyi"))

    def test_non_text_and_empty(self):
        for v in (None, "", 123, b"bytes", ["검토 부탁드립니다"]):
            self.assertEqual(extract(v), [])

    def test_all_codes_reachable(self):
        got = set(extract("[공지] 회의 취소 안내 — 9/30까지 회신 요망. 결과 공유드립니다. 작업 완료했습니다. "
                          "확인했습니다. 어디인가요?"))
        self.assertEqual(got, set(ACT_CUES))


class RequestTest(unittest.TestCase):
    """CT §6 · CT-10 — 요청 어미는 단서, 낱말 부분 일치는 단서가 아니다."""

    REQ = ["도면 검토 부탁드립니다", "내일 회의 자료 보내 주세요", "검토해 주시기 바랍니다", "확인 부탁드려요",
           "회신 바랍니다", "자료 요청드립니다", "회신 요망", "확인하세요", "검토 가능할까요?", "보내 주실 수 있을까요?",
           "도면 검토 요청", "검토 의뢰", "확인 부탁", "이거 해줘요", "please review the draft", "Can you check?",
           "참석 바랍니다", "[요청] 주간보고 작성", "[과제:P-0001] 설계 검토 부탁드립니다. 금요일까지 회신 바랍니다"]
    NOT_REQ = ["확인", "공유", "일정", "가능", "필요", "확인 필요", "일정 공유", "가능 여부 확인", "공유 폴더",
               "확인했습니다", "공유드립니다", "참고 바랍니다", "양해 바랍니다", "Please find attached the report.",
               "요청사항 정리", "회의 일정 확인했습니다", "필요한 자료 송부드립니다", "참고하시기 바랍니다",
               "양해 부탁드립니다", "너그러운 이해 바랍니다", "공유했나요?", "부탁하신 자료입니다"]

    def test_request_endings(self):
        for t in self.REQ:
            self.assertIn("req", extract(t), t)

    def test_no_partial_word_request(self):
        for t in self.NOT_REQ:
            self.assertNotIn("req", extract(t), t)

    def test_hope_phrase_distinguished(self):
        self.assertEqual(extract("참고 바랍니다"), ["fyi"])
        self.assertEqual(extract("양해 바랍니다"), [])
        self.assertIn("req", extract("참석 바랍니다"))
        self.assertIn("req", extract("제출하기 바랍니다"))
        self.assertEqual(extract("참고하시기 바랍니다"), ["fyi"])
        self.assertEqual(extract("회신요망"), ["req"])


class OtherCuesTest(unittest.TestCase):
    def check(self, text, want: set, absent: set = frozenset()):
        got = set(extract(text))
        self.assertTrue(want <= got, f"{text!r}: {got}")
        self.assertFalse(absent & got, f"{text!r}: {got}")

    def test_report_and_done(self):
        self.check("회의록 공유드립니다", {"rep"}, {"req"})
        self.check("검토 결과 공유드립니다. 확인 부탁드립니다.", {"rep", "req"})
        self.check("시험 결과 보고드립니다", {"rep"})
        self.check("자료 올려 두었습니다", {"rep"})
        self.check("첨부와 같이 송부합니다", {"rep"})
        self.check("작업 완료했습니다", {"done"})
        self.check("반영했습니다", {"done"})
        self.check("[완료] 도면 수정", {"done"})
        for t in ("완료 예정입니다", "미완료 항목 정리", "완료되면 알려주세요", "완료 여부 확인", "완료했나요?"):
            self.assertNotIn("done", extract(t), t)
        self.assertEqual(extract("공유했나요?"), ["ask"], "질문형 '했나요' 는 송부 보고가 아니다")
        self.assertEqual(extract("완료됐나요"), ["ask"])

    def test_ack(self):
        for t in ("넵", "네 알겠습니다!", "확인했습니다", "잘 받았습니다", "진행하겠습니다", "OK", "noted"):
            self.assertIn("ack", extract(t), t)
        for t in ("확인 부탁드립니다", "ok 확인 부탁드립니다 내일까지", "is it ok?"):
            self.assertNotIn("ack", extract(t), t)

    def test_ask(self):
        self.check("회의실이 어디인가요", {"ask"})
        self.check("내일 회의 몇 시에 하나요?", {"ask"}, {"req", "sched"})
        self.check("검토하셨나요", {"ask"})
        self.check("문의드립니다", {"ask"})
        self.assertNotIn("ask", extract("내일 만나요."))

    def test_sched_is_deadline_not_any_time(self):
        self.check("9/30까지 제출 바랍니다", {"sched", "req"})
        self.check("오늘 중으로 보내주세요", {"sched", "req"})
        self.check("15:00까지 회신 요망", {"sched", "req"})
        self.check("언제까지 드리면 될까요?", {"sched", "ask"})
        self.check("일정 조율 부탁드립니다", {"sched", "req"})
        self.check("[긴급] 서버 점검", {"sched"})
        for t in ("오늘 회의록 공유드립니다", "어제 회의 자료", "내일 회의는 10시입니다"):
            self.assertNotIn("sched", extract(t), t)

    def test_cancel_and_fyi(self):
        self.check("회의 취소되었습니다", {"cancel"})
        self.check("취소됨: 주간 회의", {"cancel"})
        self.check("[취소] 주간회의", {"cancel"})
        self.check("교육 일정 연기합니다", {"cancel"})
        self.check("[공지] 보안 교육 안내", {"fyi"})
        self.check("참고로 알려드립니다", {"fyi"})
        self.check("FYI - newsletter", {"fyi"})
        self.assertNotIn("cancel", extract("미취소 건"))


class TextHandlingTest(unittest.TestCase):
    def test_quoted_history_ignored(self):
        self.assertEqual(extract("확인했습니다\n> 검토 부탁드립니다"), ["ack"])
        self.assertEqual(extract("확인했습니다\n\n-----Original Message-----\nFrom: 김철수\n검토 부탁드립니다"), ["ack"])
        self.assertEqual(extract("넵\n________________\n보낸 사람: 김철수\n자료 보내 주세요"), ["ack"])
        self.assertEqual(extract("2026년 9월 1일 (화) 오후 3:00, 김철수 작성:\n검토 부탁드립니다"), [])

    def test_masked_tokens_are_not_cues(self):
        self.assertEqual(extract("[과제:P-0001] [사람#0a1b2c] [전화] [고객사:C01]"), [])
        self.assertEqual(extract("[과제:P-0001] 도면 검토 부탁드립니다"), ["req"])

    def test_raw_and_masked_give_same_cues(self):
        pairs = [("김철수 책임님 도면 검토 부탁드립니다", "[사람#0a1b2c] 책임님 도면 검토 부탁드립니다"),
                 ("과제A 결과 공유드립니다", "[과제:P-0001] 결과 공유드립니다"),
                 ("고객사A 미팅 취소되었습니다", "[고객사:C01] 미팅 취소되었습니다")]
        for raw, masked in pairs:
            self.assertEqual(extract(raw), extract(masked), raw)

    def test_pathological_input_is_bounded(self):
        big = ("검토 부탁드립니다 " * 50) + ("가" * 400_000) + "?" * 1000
        from tests.fixtures.tree import best_of                 # 부하에 민감 — 여러 번 재서 최솟값(W1 통합 창 R8)
        got = extract(big)
        self.assertLess(best_of(lambda: extract(big), under=2.0), 2.0)
        self.assertIn("req", got)
        self.assertNotIn("ask", got, "MAX_SCAN 뒤의 글은 보지 않는다")
        evil = ("[" * 3000) + ("까지" * 3000) + ("주 " * 3000)
        self.assertLess(best_of(lambda: extract(evil), under=2.0), 2.0)


class AgentCopyImportTest(unittest.TestCase):
    """X-305 · 계약 §1.3 — 정제기 훅은 에이전트 bin 사본 안에서 돈다: 표준 라이브러리(와 lm27.util)만 import."""

    def test_imports_stdlib_only(self):
        src = (ROOT / "lm27" / "normalize" / "cues.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                self.assertEqual(n.level, 0, "상대 import 금지(사본에는 normalize\\{__init__, cues} 만 있다)")
                names.append(n.module or "")
        for name in names:
            top = name.split(".")[0]
            ok = top == "__future__" or top in sys.stdlib_module_names or name == "lm27.util" or \
                name.startswith("lm27.util.")
            self.assertTrue(ok, f"사본 밖 import: {name}")

    def test_module_has_no_file_writes(self):
        src = (ROOT / "lm27" / "normalize" / "cues.py").read_text(encoding="utf-8")
        for bad in ("open(", "write(", "print(", "logging"):
            self.assertNotIn(bad, src)
        self.assertTrue(callable(C.extract))


class SanitizerHookTest(unittest.TestCase):
    """정제기(lm27.privacy.records.sanitize_record)가 이 훅으로 act_cues 를 채운다 — 원문은 메모리에서만."""

    def setUp(self):
        from tests.fixtures.wp18.rows import Sandbox
        self.sb = Sandbox()
        self.addCleanup(self.sb.remove)

    def _rc(self, src):
        from lm27.privacy import Keyring, make_record_context
        from lm27.privacy.keys import kid_of
        master = bytes(range(7, 39))
        kr = Keyring(primary_kid=kid_of(master), primary_secret=master, all={kid_of(master): master})
        return make_record_context(self.sb.root, src, "pc_0a1b2c3d4e5f6a7b", paths=self.sb.paths, cfg=self.sb.cfg(),
                                   keyring=kr, registry={}, local={}, os_names=["hongtest"],
                                   my_addrs=("hong@corp.example",))

    def test_teams_body_cues_stored(self):
        from lm27.privacy import sanitize_record
        raw = {"ts_utc": "2026-09-15T01:02:00Z", "ts_local_offset": "+09:00", "ts_precision": "minute",
               "observed_at": "2026-09-15T02:00:00Z", "confidence": 1.0, "message_id": None,
               "chat_id": "uia:과제a 채널", "chat_type": "1:1", "n_participants": 2, "reply_to_id": None,
               "author_addr": None, "author_name": "김철수", "is_me": False, "participants": [{"name": "김철수"}],
               "mentions_me": False, "file_names": [], "body_text": "도면 검토 부탁드립니다. 금요일까지 회신 바랍니다",
               "chat_title": None, "flags": {}}
        out = sanitize_record("teams", raw, self._rc("teams.uia"))
        self.assertEqual(out.status, "stored", out.reason)
        self.assertEqual(list(out.row.data["act_cues"]), ["req", "sched"])

    def test_mail_quoted_request_not_a_cue(self):
        from lm27.privacy import sanitize_record
        raw = {"ts_utc": "2026-09-15T01:02:00Z", "ts_local_offset": "+09:00", "ts_precision": "minute",
               "observed_at": "2026-09-15T02:00:00Z", "confidence": 1.0, "internet_message_id": "<r1@corp.example>",
               "conversation_id": "CONV1", "conversation_topic": "도면 검토", "box": "sent", "folder_role": "sent",
               "sender_addr": "hong@corp.example", "sender_name": "홍길동",
               "to": [{"addr": "kim@corp.example", "name": "김철수"}], "cc": [], "subject": "RE: 도면 검토",
               "attach_names": [], "has_attach": False, "in_reply_to": True,
               "body_text": "확인했습니다.\n\n-----Original Message-----\nFrom: 김철수\n도면 검토 부탁드립니다"}
        out = sanitize_record("mail", raw, self._rc("mail.com"))
        self.assertEqual(out.status, "stored", out.reason)
        self.assertEqual(list(out.row.data["act_cues"]), ["ack"])


if __name__ == "__main__":
    unittest.main()
