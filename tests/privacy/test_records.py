# -*- coding: utf-8 -*-
"""WP-11 레코드 시험 — 열 허용 목록(SCHEMAS ⊇ synth.STORED_COLUMNS · schemas_v1.json 스냅숏), 봉인(L-11 ③ · P-T6),
kind 8종 정제·열 검증(I12 · P-T30·T31), 폐기 사유(cred·ad·private_folder·folder_excluded·bad_raw·no_key), 공사·광고(P-T13),
키 없음 모드(P-T29·T36), 레코드 id(P §10.1 · C6), 재정제(P-T23), 소급 가림(C11), 수집기 원시 모양(C7)."""
import copy
import dataclasses
import gzip
import pickle
import unittest
from types import MappingProxyType

from lm27.privacy import context as C
from lm27.privacy import keys as K
from lm27.privacy import records as R
from lm27.privacy import selftest
from lm27.privacy.rules import RULES_VERSION
from lm27.store import SegmentWriter
from lm27.util import fsx
from tests.fixtures import synth
from tests.fixtures.canary import canaries, canary_ctx, find_canaries
from tests.fixtures.wp11 import helpers as H


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def rec(self, kind, raw=None, src=None, rc=None, **over):
        src0, fn = H.RAW[kind]
        rc = rc or self.sb.rc(src or src0)
        return R.sanitize_record(kind, raw if raw is not None else fn(**over), rc), rc

    def stored(self, kind, raw=None, src=None, rc=None, **over):
        out, _rc = self.rec(kind, raw, src, rc, **over)
        self.assertEqual((out.status, out.reason), ("stored", None))
        return out.row.to_dict()


class SchemaTest(unittest.TestCase):
    def test_superset_of_synth_stored_columns(self):
        """계획 v1.1: SCHEMAS[kind] 열 ⊇ tests.fixtures.synth.STORED_COLUMNS[kind](다르면 WP-05 CR)."""
        for kind, cols in synth.STORED_COLUMNS.items():
            with self.subTest(kind):
                self.assertLessEqual(set(cols), set(R.SCHEMAS[kind].columns))
                self.assertLessEqual(set(synth.FLAG_KEYS[kind]), set(R.SCHEMAS[kind].flag_keys))

    def test_kinds_and_paths(self):
        self.assertEqual(R.KINDS, ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual"))
        self.assertEqual(sum(len(v) for v in R.SRCS_BY_KIND.values()), 21)
        for kind in R.KINDS:
            self.assertLessEqual(set(R.SCHEMAS[kind].text_fields), set(R.SCHEMAS[kind].columns))
            self.assertLessEqual(set(R.SCHEMAS[kind].required), set(R.SCHEMAS[kind].columns))
            self.assertLessEqual(set(R.SCHEMAS[kind].columns), set(R.VALIDATORS))

    def test_schemas_v1_snapshot(self):
        """schemas_v1.json = canon_bytes(schema_snapshot(SCHEMAS)) — 열을 바꾸면 스냅숏도 함께(selftest '스키마')."""
        p = H.REAL_ROOT / "lm27" / "privacy" / "schemas_v1.json"
        self.assertEqual(p.read_bytes(), fsx.canon_bytes(selftest.schema_snapshot(R.SCHEMAS)) + b"\n")


class FacadeTest(unittest.TestCase):
    def test_L10_collector_facade(self):
        """L-10: 수집기는 ``lm27.privacy.sanitize`` 한 모듈만 import — 필요한 이름이 모두 그 모듈에 있다."""
        from lm27.privacy import sanitize as facade
        self.assertIs(facade.sanitize_record, R.sanitize_record)
        self.assertIs(facade.SanitizedRow, R.SanitizedRow)
        self.assertIs(facade.RecordOutcome, R.RecordOutcome)
        self.assertIs(facade.make_record_context, C.make_record_context)
        for name in ("sanitize", "scan"):
            self.assertTrue(callable(getattr(facade, name)))
        self.assertFalse(hasattr(facade, "_SEAL"))
        import lm27.privacy as P                                  # 이름 하나가 모듈·함수 둘 — import 순서와 무관하게 같다
        import lm27.privacy.sanitize as M
        self.assertIs(P.sanitize, M)
        self.assertEqual(P.sanitize("연락처 010-1234-5678").text, "연락처 [전화]")
        self.assertEqual(facade("연락처 010-1234-5678", "subject").hits, {"phone": 1})


class SealTest(_Base):
    def test_cannot_forge(self):
        with self.assertRaises(TypeError):
            R.SanitizedRow("mail", {}, None)
        with self.assertRaises(TypeError):
            R.SanitizedRow("mail", {}, object())

    def test_frozen_and_uncopyable(self):
        row = self.rec("mail")[0].row
        self.assertIsInstance(row.data, MappingProxyType)
        self.assertIsInstance(row.data["attach_keys"], tuple)
        with self.assertRaises(TypeError):
            row.data["subject_masked"] = "x"
        with self.assertRaises(TypeError):
            row.kind = "cal"
        with self.assertRaises(TypeError):
            del row.data
        for fn in (copy.copy, copy.deepcopy, pickle.dumps, lambda r: r.__replace__(kind="cal")):
            with self.assertRaises(TypeError):
                fn(row)
        with self.assertRaises(TypeError):
            dataclasses.replace(row, kind="cal")
        d = row.to_dict()
        d["subject_masked"] = "변경"
        self.assertNotEqual(row.data["subject_masked"], "변경")
        self.assertNotIn("subject", repr(row))
        with self.assertRaises(TypeError):
            R.check_row(d)

    def test_as_pair(self):
        out, _ = self.rec("mail")
        rec, audit = out.as_pair()
        self.assertEqual(rec["id"], out.row.data["id"])
        self.assertEqual(audit, {"status": "stored", "reason": None, "hits": {}})
        drop, _ = self.rec("mail", folder_role="deleted")
        self.assertEqual(drop.as_pair()[0], None)


class KindsTest(_Base):
    def test_all_kinds_store_and_validate(self):
        for kind in R.KINDS:
            with self.subTest(kind):
                d = self.stored(kind)
                self.assertEqual(R.validate_columns(kind, d), [])
                self.assertEqual((d["act"], d["rules_ver"], d["kid"]), ("", RULES_VERSION, H.keyring().kid))
                self.assertRegex(d["id"], r"^[0-9a-f]{16}$")

    def test_synth_all_paths_store(self):
        plan = synth.plan_month(2026, 9)
        for kind, srcs in synth.SRCS_BY_KIND.items():
            for src in srcs:
                raws = synth.raw_records(kind, plan, src=src)[:40]
                rc = self.sb.rc(src)
                with self.subTest(src=src):
                    res = [R.sanitize_record(kind, r, rc) for r in raws]
                    self.assertTrue(raws)
                    self.assertEqual([o.reason for o in res if o.status == "error"], [])
                    for o in res:
                        if o.status == "stored":
                            self.assertEqual(R.validate_columns(kind, o.row.data), [])

    def test_mail_columns(self):
        d = self.stored("mail", subject="RE: 고객사A 견적 010-1234-5678 회신 요청")
        self.assertEqual(d["subject_masked"], "RE: [고객사:C01] 견적 [전화] 회신 요청")
        self.assertEqual(d["san"], {"customer": 1, "phone": 1})
        self.assertEqual((d["direction"], d["rcv"], d["box"], d["sender_label"]), ("in", "to", "inbox", "사내"))
        self.assertEqual(d["sender_key"], K.who_key(H.keyring(), "smtp:" + H.KIM))
        self.assertEqual(d["counterpart_keys"], [K.who_key(H.keyring(), "smtp:" + H.KIM)])
        self.assertEqual((d["is_reply"], d["refw_depth"], d["n_to"], d["n_cc"]), (True, 1, 1, 0))
        self.assertEqual(d["attach_keys"], [K.doc_key(H.keyring(), "견적_v2.xlsx")])
        self.assertEqual(d["attach_exts"], [".xlsx"])
        self.assertEqual(d["msg_key"], K.msg_key(H.keyring(), "mid:m1.s0@corp.example"))
        self.assertEqual(d["thread_key"], K.thread_key(H.keyring(), "conv:CONV0001"))
        self.assertEqual(d["flags"], {"has_file": True})
        self.assertNotIn("sender_addr", d)

    def test_sent_mail(self):
        d = self.stored("mail", box="sent", folder_role="sent", sender_addr=H.ME, sender_name="홍길동",
                        to=[{"addr": H.CUST, "name": "영업"}])
        self.assertEqual((d["direction"], d["sender_key"], d["rcv"]), ("out", "self", "na"))
        self.assertNotIn("ad_band", d)

    def test_rcv_unknown_without_parties_C7(self):
        raw = H.raw_mail()
        for k in ("to", "cc", "sender_addr", "sender_name"):
            raw.pop(k)
        d = self.stored("mail", raw=raw)
        self.assertEqual(d["rcv"], "unknown")
        self.assertNotIn("n_to", d)
        self.assertNotIn("sender_key", d)
        self.assertEqual(d["sender_label"], "미상")
        rc = self.sb.rc("mail.com", my_addrs=())
        d2 = self.stored("mail", rc=rc)
        self.assertEqual(d2["rcv"], "unknown")                       # 내 주소 미확정(R-NOADDR)

    def test_cal_columns(self):
        d = self.stored("cal")
        self.assertEqual((d["ts_end"], d["busy"], d["location_class"]), ("2026-09-15T02:02:00Z", "busy", "room"))
        self.assertEqual(d["flags"], {"meeting_status": 1, "recurring": True, "response": 3})
        self.assertEqual(d["thread_key"], K.thread_key(H.keyring(), "series:GID0001"))
        self.assertRegex(d["msg_key"], r"^e[0-9a-f]{24}$")
        self.assertEqual(d["subject_masked"], "[과제:P-0001] 주간 회의")
        org = self.stored("cal", flags={"organizer_me": True}, organizer={"addr": H.ME, "name": "홍길동"})
        self.assertTrue(org["flags"]["organizer_me"])
        on = self.stored("cal", location="Microsoft Teams 모임", online=False)
        self.assertEqual(on["location_class"], "online")

    def test_teams_C7_shapes(self):
        d = self.stored("teams", is_me=None, chat_type="unknown", chat_title="과제A 설계")
        self.assertEqual((d["direction"], d["chat_type"], d["n_participants"]), ("unknown", "group", 2))
        self.assertTrue(d["flags"]["n_part_est"])
        one = self.stored("teams", chat_type="1:1", chat_title="김철수")
        self.assertNotIn("chat_title_masked", one)                      # 1:1 방 이름 = 상대 이름 → 저장 안 함
        me = self.stored("teams", is_me=True, author_name="홍길동")
        self.assertEqual((me["direction"], me["author_key"]), ("sent", "self"))
        g = self.stored("teams")
        self.assertEqual(g["counterpart_keys"], [K.who_key(H.keyring(), "name:김철수")])
        self.assertEqual(g["chat_title_masked"], "[과제:P-0001] 설계")
        self.assertIn("priv_score_base", g)

    def test_teams_msg_key_includes_date(self):
        a = self.stored("teams", ts_utc="2026-09-15T01:02:00Z")
        b = self.stored("teams", ts_utc="2026-09-16T01:02:00Z")
        self.assertNotEqual(a["msg_key"], b["msg_key"])
        c = self.stored("teams", message_id="19:abc")
        self.assertEqual(c["msg_key"], K.msg_key(H.keyring(), "tid:19:abc"))

    def test_sampler(self):
        d = self.stored("pc_session", fg_doc_path=r"C:\Users\hongtest\Documents\과제A\견적_v2.xlsx")
        self.assertEqual((d["layer"], d["app_class"], d["site_class"], d["priv_class"]), ("L3", "office", "app", "work"))
        self.assertEqual(d["ts_end"], "2026-09-15T01:03:00Z")
        self.assertEqual(d["title_masked"], "견적_v2.xlsx - Excel")
        self.assertEqual(d["doc_key"], K.doc_key(H.keyring(), "견적_v2.xlsx"))
        self.assertEqual(len(d["dir_keys"]), 2)                         # C15 — 상위 폴더 1~2단
        p = self.stored("pc_session", fg_exe="kakaotalk.exe", app_class="messenger_private", fg_title="김철수",
                        fg_doc_name=None)
        self.assertEqual((p["priv_class"], p["title_masked"], p["priv_why"]), ("private", "", ["app"]))
        self.assertNotIn("doc_key", p)
        idle = self.stored("pc_session", app_class="idle", fg_exe="", fg_title="", fg_doc_name=None, layer=None)
        self.assertEqual(idle["layer"], "L2")

    def test_events_textless(self):
        d = self.stored("pc_session", raw=H.raw_event(), src="pc.events")
        self.assertEqual((d["event_class"], d["layer"]), ("boot", "L0"))
        self.assertFalse(any(c.endswith("_masked") for c in d))

    def test_file(self):
        d = self.stored("pc_file")
        self.assertEqual((d["name_masked"], d["ext"], d["folder_role"], d["op"]), ("견적_v2.xlsx", ".xlsx", "documents",
                                                                                  "modify"))
        self.assertEqual(d["size_bucket"], "100KB-1MB")
        self.assertEqual(len(d["dir_keys"]), 3)
        self.assertEqual(d["flags"], {"edit": True})
        self.assertNotIn("path", d)
        other = self.stored("pc_file", ooxml_last_modified_by="김철수", op="open", pdf_sibling=True,
                            flags={"autosave": True, "final_name": True})
        self.assertEqual(other["flags"], {"author_other": True, "autosave": True, "final_name": True, "pdf_export": True,
                                          "view_only": True})

    def test_git_and_compute_and_manual(self):
        g = self.stored("pc_git")
        self.assertEqual((g["doc_key"], g["n_commits"]), (K.repo_key(H.keyring(), "firmware"), 1))
        self.assertEqual(g["exts"], [".c", ".h"])
        c = self.stored("pc_compute")
        self.assertEqual((c["app_id"], c["cpu_core"], c["flags"]), ("fluent", 3.5, {"solver": True}))
        m = self.stored("manual")
        self.assertEqual((m["ts_utc"], m["ts_end"], m["ts_precision"]), ("2026-09-15T05:00:00Z", "2026-09-15T06:30:00Z",
                                                                         "minute"))
        self.assertEqual((m["work_category"], m["man_kind"], m["text_masked"]), ("현장 점검", "work", "[과제:P-0001] 장비 점검"))
        day = self.stored("manual", start=None, end=None)
        self.assertEqual((day["ts_utc"], day["ts_precision"]), ("2026-09-14T15:00:00Z", "date"))

    def test_copilot_witness(self):
        raw = {"copilot_text": "과제A 회의 일정 조율", "ts_utc": "2026-09-14T15:00:00Z", "ts_local_offset": "+09:00",
               "ts_precision": "minute", "observed_at": H.OBS, "confidence": 0.9}
        for kind, src in (("mail", "mail.copilot"), ("cal", "cal.copilot"), ("teams", "teams.copilot")):
            with self.subTest(src):
                d = self.stored(kind, raw=dict(raw), src=src)
                self.assertEqual((d["ts_precision"], d["confidence"]), ("date", 0.4))
                self.assertEqual(d["text_masked"], "[과제:P-0001] 회의 일정 조율")
                self.assertRegex(d["msg_key"], r"^[me][0-9a-f]{24}$")


class DropTest(_Base):
    def test_bad_raw(self):
        for kind, over in (("pc_session", {"user": "x"}), ("mail", {"act": "request"}), ("mail", {"ts_utc": "어제"}),
                           ("mail", {"box": "outbox"}), ("teams", {"chat_id": ""}), ("pc_compute", {"host": "x"}),
                           ("mail", {"username": "x"}), ("manual", {"category": "홍길동 010-1111-2222"}),
                           ("pc_git", {"commit_sha": "zz"}), ("mail", {"ts_local_offset": "KST"})):
            with self.subTest(kind=kind, over=sorted(over)):
                out, _ = self.rec(kind, **over)
                self.assertEqual((out.status, out.reason), ("dropped", "bad_raw"))

    def test_T31_events_forbidden_raw(self):
        for extra in ({"user": "x"}, {"message": "x"}, {"computer": "x"}):
            out, _ = self.rec("pc_session", raw=H.raw_event(**extra), src="pc.events")
            self.assertEqual(out.reason, "bad_raw")

    def test_T30_column_violation(self):
        au_rc = self.sb.rc("pc.sampler")
        out, _ = self.rec("pc_session", rc=au_rc, session_state="홍길동 PC")
        self.assertEqual((out.status, out.reason, out.row), ("error", "ColumnViolation", None))
        out2, _ = self.rec("pc_session", rc=au_rc, app_id="excel 365")
        self.assertEqual(out2.reason, "ColumnViolation")
        c = au_rc.audit.counts()
        self.assertEqual(c["err"], {"column:app_id": 1, "column:session_state": 1})
        self.assertNotIn("홍길동", repr(c))

    def test_cred_deleted_private_folder(self):
        self.assertEqual(self.rec("mail", subject="VPN 비밀번호: Abc!2345 공유")[0].reason, "cred")
        self.assertEqual(self.rec("mail", folder_role="deleted")[0].reason, "folder_excluded")
        self.assertEqual(self.rec("pc_file", path=r"C:\Users\x\Documents\개인\가계부.xlsx")[0].reason, "private_folder")
        self.assertEqual(self.rec("pc_git", repo_root=r"D:\personal\dotfiles")[0].reason, "private_folder")

    def test_path_excluded_rules(self):
        kw = ("개인", "private", "temp")
        self.assertTrue(R.path_excluded(r"C:\a\Private\b.txt", kw))
        self.assertFalse(R.path_excluded(r"C:\a\privatekey_docs\b.txt", kw))   # ASCII 단어 경계
        self.assertTrue(R.path_excluded(r"C:\a\개인정보\b.txt", kw))            # 한글 부분 일치(P §10.4)
        self.assertFalse(R.path_excluded(r"C:\a\b\개인정보 교육.pptx", kw))       # 파일 이름은 보지 않는다
        self.assertTrue(R.path_excluded(r"C:\Temp\b.txt", kw))
        self.assertFalse(R.path_excluded(r"C:\Temp2\b.txt", kw))                # 경로 전용 토큰은 완전 일치
        self.assertFalse(R.path_excluded(r"C:\a\b.txt", ()))

    def test_ad_drop_and_partial_T13(self):
        """P-T13: 같은 광고 — COM(헤더 있음) drop, 색인(헤더 없음) 점수 낮아지고 ad_partial."""
        hdr = "List-Unsubscribe: <mailto:u@promo.example>\nPrecedence: bulk\n"
        base = {"sender_addr": "hello@promo.example", "sender_name": "소식", "subject": "9월 소식 전해드립니다",
                "internet_message_id": "<ad1@promo.example>", "to": [{"addr": H.ME, "name": "홍길동"}]}
        com, rc = self.rec("mail", headers_text=hdr, **base)
        self.assertEqual((com.status, com.reason), ("dropped", "ad"))
        raw = H.raw_mail(**base)
        raw.pop("body_text")
        idx, rc2 = self.rec("mail", raw=raw, src="mail.index")
        self.assertEqual(idx.status, "stored")
        d = idx.row.to_dict()
        self.assertEqual((d["ad_band"], d["ad_partial"], d["flags"].get("ad")), ("suspect", True, True))
        self.assertLess(d["ad_score"], 5)
        self.assertEqual(rc.audit.counts()["ad"], {"drop": 1})
        self.assertEqual(rc2.audit.counts()["ad"], {"partial": 1, "suspect": 1})
        loud = H.raw_mail(**dict(base, sender_addr="news@promo.example", subject="웨비나 초대합니다"))
        loud.pop("body_text")
        out, rc3 = self.rec("mail", raw=loud, src="mail.index")         # 헤더 없이도 drop 점수면 drop + partial 집계
        self.assertEqual(out.reason, "ad")
        self.assertEqual(rc3.audit.counts()["ad"], {"drop": 1, "partial": 1})

    def test_ad_prefix_and_user_block(self):
        self.assertEqual(self.rec("mail", subject="(광고) 할인 안내", sender_addr="x@promo.example")[0].reason, "ad")
        cust = self.stored("mail", sender_addr=H.CUST, sender_name="영업", subject="견적서 송부")
        self.assertEqual(cust["ad_band"], "keep")                        # 등록 고객사 도메인 = 업무 관계

    def test_teams_notice_not_scored(self):
        notice = "noreply@email." + R.TEAMS_NOTICE_DOMAINS[0]             # L-26: 시험 주소는 런타임 조립
        d = self.stored("mail", sender_addr=notice, sender_name="Microsoft Teams",
                        subject="Microsoft Teams 에서 놓친 활동", internet_message_id="<n1@ms.example>")
        self.assertTrue(d["flags"]["teams_notice"])
        self.assertNotIn("ad_band", d)


class PrivacyTest(_Base):
    def test_private_mail_texts_emptied(self):
        d = self.stored("mail", sensitivity=2, subject="가족 병원 예약 내일 연차", attach_names=["진료.pdf"],
                        categories=["개인"])
        self.assertEqual((d["priv_class"], d["subject_masked"], d["attach_names_masked"], d["categories_masked"]),
                         ("private", "", [], []))
        self.assertEqual((d["act_cues"], d["abs_hint"]), ([], "leave"))                 # R-P8 부재 힌트는 유지
        self.assertTrue(d["flags"]["private"])
        self.assertEqual(d["flags"]["sensitivity"], 2)
        self.assertEqual(d["priv_why"], ["explicit"])

    def test_social_and_offhours(self):
        d = self.stored("teams", body_text="저녁 회식 장소 투표해 주세요", ts_utc="2026-09-15T12:30:00Z")
        self.assertEqual(d["priv_class"], "social")
        self.assertIn("offhours", d["priv_why"])
        self.assertEqual(d["body_masked"], "")

    def test_room_prior_within_batch_T9_part(self):
        """P-T9(정제기 몫): 1:1 방 10건 이상·사적 70% 이상이면 같은 방 다음 행에 room_private 가점, priv_score_base 는
        방 성향을 뺀 점수로 남는다(적재기 소급 재계산 재료)."""
        rc = self.sb.rc("teams.uia")
        room = {"chat_type": "1:1", "chat_id": "uia:1:1 김철수", "n_participants": 2, "chat_title": None}
        for i in range(10):
            out, _ = self.rec("teams", rc=rc, body_text="오늘 저녁 가족 모임 병원 들렀다 갈게", message_id=f"r{i}", **room)
            self.assertEqual(out.row.data["priv_class"], "private")
        d = self.stored("teams", rc=rc, body_text="네", message_id="r10", **room)
        self.assertIn("room_private", d["priv_why"])
        self.assertEqual(d["priv_score"], d["priv_score_base"] + 2)
        other = self.stored("teams", rc=rc, body_text="네", message_id="r11", **dict(room, chat_id="uia:1:1 박영수"))
        self.assertNotIn("room_private", other["priv_why"])

    def test_user_private_chat(self):
        rc = self.sb.rc("teams.uia")
        ck = K.chat_key(H.keyring(), "uia:과제a 채널")
        rc.private_chats.add(ck)
        d = self.stored("teams", rc=rc)
        self.assertEqual((d["priv_class"], d["body_masked"]), ("private", ""))


class NoKeyTest(_Base):
    """P-T29 · T36: 키 없음 모드 — teams 는 no_key 폐기, 샘플러·파일은 키 열 null + flags.no_key, [사람#…] 0건."""

    def rc_nokey(self, src):
        return self.sb.rc(src, kr=K.NoKeys())

    def test_teams_dropped(self):
        out, rc = self.rec("teams", rc=self.rc_nokey("teams.uia"))
        self.assertEqual((out.status, out.reason), ("dropped", "no_key"))
        self.assertEqual(rc.audit.counts()["dropped"], {"no_key": 1})

    def test_sampler_and_file_kept(self):
        d = self.stored("pc_session", rc=self.rc_nokey("pc.sampler"),
                        fg_title="김철수 책임 검토 요청.docx - Word", fg_doc_name=None, app_class="office")
        self.assertNotIn("doc_key", d)
        self.assertTrue(d["flags"]["no_key"])
        self.assertNotIn("[사람#", d["title_masked"])
        self.assertIn("[사람]", d["title_masked"])
        self.assertEqual(d["kid"], K.NO_KID)
        f = self.stored("pc_file", rc=self.rc_nokey("pc.files"), path=r"C:\a\b\김철수 책임 메모.txt")
        self.assertTrue(f["flags"]["no_key"])
        for col in ("doc_key", "path_key"):
            self.assertNotIn(col, f)
        self.assertEqual(f["dir_keys"] if "dir_keys" in f else [], [])

    def test_events_need_no_key(self):
        d = self.stored("pc_session", raw=H.raw_event(), src="pc.events", rc=self.rc_nokey("pc.events"))
        self.assertNotIn("flags", d) if not d.get("flags") else self.assertNotIn("no_key", d["flags"])

    def test_T36_zero_key_tags_downgraded(self):
        rc = self.sb.rc("pc.sampler", kr=K.AgentKeys(kid=K.kid_of(H.MASTER), subkeys={}))
        self.assertTrue(rc.no_key)
        d = self.stored("pc_session", rc=rc, fg_title="김철수 책임 보고서.docx - Word", fg_doc_name=None)
        self.assertNotIn("[사람#", d["title_masked"])


class SurrogateTest(_Base):
    """W1b 회귀: 짝 없는 서로게이트(페이지 JS 의 UTF-16 자르기가 이모지를 자름 — CDP JSON 이 외톨이를 넘김) 한 글자 때문에
    행 전체가 정제 error(UnicodeEncodeError)로 사라지지 않는다 — 입력 정규화 첫 단계에서 U+FFFD 로 바꾸고, 짝이 맞는 둘은
    한 글자로 합친다."""

    def test_lone_surrogates_replaced_row_kept(self):
        d = self.stored("teams", chat_title="과제A 설계 \ud83c", body_text="도면 공유 \ud83d", file_names=["도면\udc00.dwg"],
                        participants=[{"name": "김철수\ud83d"}, {"name": "홍길동"}])
        self.assertIn("�", d["chat_title_masked"])
        self.assertIn("�", d["body_masked"])
        for v in d.values():
            self.assertFalse(isinstance(v, str) and R._SURR_RX.search(v), v)
        m = self.stored("mail", subject="견적 \udc81 검토", sender_name="김철수\ud800")
        self.assertIn("�", m["subject_masked"])

    def test_paired_surrogate_code_points_merge(self):
        self.assertEqual(R._fix_surr("a😀b"), "a\U0001f600b")
        self.assertEqual(R._fix_surr({"k\ud83c": ["x\udfff", ("y",)], "n": 1}), {"k�": ["x�", ("y",)], "n": 1})
        self.assertFalse(R._has_surr({"a": ["b", {"c": "d"}], "e": 2}))

    def test_raw_input_not_mutated(self):
        raw = H.raw_teams(body_text="회신 \ud83d")
        self.stored("teams", raw=raw)
        self.assertEqual(raw["body_text"], "회신 \ud83d")                 # 수집기 원시(메모리)는 그대로 — 사본만 고친다


class IdTest(_Base):
    def test_deterministic_and_text_sensitive(self):
        a = self.stored("mail")
        b = self.stored("mail")
        self.assertEqual(a["id"], b["id"])
        c = self.stored("mail", subject="견적 재검토 요청")
        self.assertNotEqual(a["id"], c["id"])

    def test_C6_events_and_compute(self):
        """C6: 같은 초에 시작한 L0 부팅·L1 로그온 구간, 같은 시각 라이선스 기능 둘 — id 가 갈린다."""
        boot = self.stored("pc_session", raw=H.raw_event(), src="pc.events")
        logon = self.stored("pc_session", raw=H.raw_event(event_class="logon", layer="L1"), src="pc.events")
        self.assertNotEqual(boot["id"], logon["id"])
        lic = {"app_id": "ansys", "fg_exe": None, "cpu_core": None, "flags": {"license": True, "end_uncertain": True}}
        a = self.stored("pc_compute", **lic)
        b = self.stored("pc_compute", **dict(lic, app_id="unknown:lic_x"))
        self.assertNotEqual(a["id"], b["id"])
        again = self.stored("pc_session", raw=H.raw_event(ts_end="2026-09-15T10:00:00Z"), src="pc.events")
        self.assertEqual(again["id"], boot["id"])                       # 진행 중 구간의 새 판 = 같은 id(X-032)

    def test_record_id_formula(self):
        d = self.stored("pc_git")
        self.assertEqual(R.record_id(d), d["id"])
        import hashlib
        th = hashlib.sha1(d["msg_masked"].encode()).hexdigest()
        want = hashlib.sha1("|".join((d["src"], d["pc_id"], d["ts_utc"], d["commit_key"], th)).encode()).hexdigest()[:16]
        self.assertEqual(d["id"], want)


class ResanitizeRedactTest(_Base):
    def test_T23_lower_version_masked_in_copy(self):
        d = self.stored("mail")
        old = dict(d, rules_ver="2025.1.0", subject_masked="연락처 010-1234-5678 확인")
        new, hits = R.resanitize_row("mail", old, None)
        self.assertEqual(new["subject_masked"], "연락처 [전화] 확인")
        self.assertEqual((hits, new["rules_ver"], new["id"]), ({"phone": 1}, RULES_VERSION, d["id"]))   # 현행 규칙 판(W1 통합 창 2026.10.1)
        self.assertEqual(old["subject_masked"], "연락처 010-1234-5678 확인")       # 원본 불변
        same, h2 = R.resanitize_row("mail", d, None)
        self.assertIs(same, d)
        self.assertEqual(h2, {})
        cred, h3 = R.resanitize_row("mail", dict(d, rules_ver="1.0.0", subject_masked="pw=hunter22 공유"), None)
        self.assertEqual((cred["subject_masked"], h3), ("", {"cred": 1}))

    def test_C11_redact(self):
        self.assertEqual(R.redact_fields("teams"), ("body_masked", "file_names_masked", "chat_title_masked",
                                                    "text_masked", "act_cues"))
        self.assertEqual(R.redact_fields("pc_compute"), ("act_cues",))
        d = self.stored("teams", file_names=["설계.dwg"])
        r = R.redact_row("teams", d)
        self.assertEqual((r["body_masked"], r["file_names_masked"], r["chat_title_masked"]), ("", [], ""))
        self.assertEqual((r["id"], r["msg_key"], r["ts_utc"], r["file_keys"]), (d["id"], d["msg_key"], d["ts_utc"],
                                                                                d["file_keys"]))
        self.assertNotEqual(d["body_masked"], "")


class CanaryStoreTest(_Base):
    """T-07(정제 경계): 원시 텍스트 필드에 카나리아 문장을 하나씩 심어도 저장 행에 원값 0건(pii 묶음 — 약한 것 제외)."""

    def test_pii_canaries_not_in_rows(self):
        cs = [c for c in canaries(groups=["pii"], weak=False) if c.sentence]
        rc_mail, rc_teams = self.sb.rc("mail.com"), self.sb.rc("teams.uia")
        blobs = []
        for i, c in enumerate(cs):
            for kind, rc, over in (("mail", rc_mail, {"subject": c.sentence, "internet_message_id": f"<c{i}@x.example>"}),
                                   ("teams", rc_teams, {"body_text": c.sentence, "message_id": f"c{i}"})):
                out = R.sanitize_record(kind, H.RAW[kind][1](**over), rc)
                if out.row is not None:
                    blobs.append(fsx.canon_bytes(out.row.to_dict()))
        self.assertGreater(len(blobs), len(cs))
        self.assertEqual(find_canaries(b"\n".join(blobs), cs), [])

    def test_T07_all_paths_store_and_audit(self):
        """합성 한 달치 21개 경로(카나리아 전부 심음 · canary_ctx 사전) → SegmentWriter 저장 + 감사 → store·감사 바이트에
        pii·ctx 카나리아 원값 0(약한 것 제외)."""
        cs = canaries()
        cx = canary_ctx(cs)
        reg = {"internal_domains": ["corp.example"], "customers": cx["customers"], "projects": cx["projects"]}
        local = {"person_dir": {"format": C.PERSONDIR_FORMAT,
                                "people": {"w" + v: {"names": [n]} for n, v in cx["persons"].items()}}}
        plan = synth.plan_month(2026, 9)
        n_stored = 0
        for kind, srcs in synth.SRCS_BY_KIND.items():
            for src in srcs:
                rc = C.make_record_context(self.sb.root, src, H.PC1, paths=self.sb.paths, cfg=self.sb.cfg(),
                                           keyring=H.keyring(), registry=reg, local=local,
                                           os_names=["hongtest", *cx["self_names"]], my_addrs=(H.ME,))
                with SegmentWriter(self.sb.paths, H.PC1, kind, src) as w:
                    for r in synth.raw_records(kind, plan, src=src, canaries=cs):
                        o = R.sanitize_record(kind, r, rc)
                        if o.row is not None:
                            w.append(o.row)
                            n_stored += 1
                self.assertTrue(rc.audit.flush())
        self.assertGreater(n_stored, 1000)
        parts = []
        for f in sorted(self.sb.paths.store_root().rglob("*")):
            if f.is_file() and not f.name.endswith(".lock"):
                parts.append(gzip.decompress(f.read_bytes()) if f.suffix == ".gz" else f.read_bytes())
        found = set(find_canaries(b"\n".join(parts), cs, groups=["pii", "ctx"]))
        known = set()   # W1 통합 창: 정제 규칙 2026.10.1 이 경로 카나리아까지 가린다 — 예외 없이 전부 검사
        self.assertEqual(sorted(found - known), [])

    def test_manual_note_entity_joined_after_masking(self):
        d = self.stored("manual", note=r"자료 C:\Users\hongtest\Documents\견적.xlsx", entity="고객사A 담당")
        self.assertEqual(d["text_masked"], "자료 [경로]\\견적.xlsx / [고객사:C01] 담당")
        self.assertEqual(self.stored("manual", note="", entity="고객사A")["text_masked"], "[고객사:C01]")
        self.assertEqual(self.stored("manual", note="가" * 199, entity="고객사A")["text_masked"], "가" * 199)


if __name__ == "__main__":
    unittest.main()
