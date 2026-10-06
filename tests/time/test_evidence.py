# -*- coding: utf-8 -*-
"""WP-19 증거 정규화(lm27.time.evidence.normalize) — 저장 행 → 시간 코어 형(W §2 · 계약 X-200~X-206 · X-212).

입력은 합성 저장 행(계약 §3.1~§3.3 열 + load_evidence 파생 열)뿐이다.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from datetime import date, datetime

from tests.fixtures import canary as CN
from tests.time import scenarios as X

from lm27.time.calendar import EPOCH, d_of
from lm27.time.evidence import ENG_CATEGORIES, Evidence, lsec_of, normalize
from lm27.time.tokens import B_GENERIC

DAY0 = "2026-10-14"
AS_OF = X.as_of_utc("2026-10-30 18:00")


def lt(hhmm: str, day: str = DAY0) -> int:
    """근무 시간대 로컬 'HH:MM' → 로컬 초."""
    return lsec_of(f"{day} {hhmm}", 540)


def row(kind: str, src: str, hhmm: str, prec: str = "exact", day: str = DAY0, pc: str = "PC1", **kw) -> dict:
    r = X._base(kind, src, pc, f"{day} {hhmm}", prec)
    seed = repr((kind, src, hhmm, day, pc, sorted(kw.items())))
    r["id"] = kw.pop("id", None) or hashlib.sha1(seed.encode()).hexdigest()[:16]     # 결정적 합성 id
    r.update(kw)
    return r


def sampler(a: str, b: str, *, app_class="office", doc=None, state="active", idle=None, priv="work", pc="PC1",
            app_id=None, day=DAY0, **kw) -> dict:
    return row("pc_session", "pc.sampler", a, "exact", day, pc, ts_end=X.utc(f"{day} {b}"), app_class=app_class,
               fg_exe=kw.pop("fg_exe", "winword.exe"), app_id=app_id or app_class, session_state=state,
               idle_sec=idle, priv_class=priv, layer="L3",
               doc_key=X.doc_key(doc) if doc else None, title_masked=(f"{doc} - 앱" if doc else None), **kw)


def events(a: str, b: str, *, pc="PC1", day=DAY0, day_end=None, **kw) -> dict:
    return row("pc_session", "pc.events", a, "minute", day, pc, ts_end=X.utc(f"{day_end or day} {b}"),
               session_state="active", idle_sec=None, layer="L1", event_class=kw.pop("event_class", "logon"), **kw)


def mail(hhmm: str, direction: str, act: str, conv: str, *, prec="exact", key=None, tokens=(), atts=(), peer="P1",
         day=DAY0, rcv=None, flags=None, **kw) -> dict:
    r = row("mail", "mail.com", hhmm, prec, day, act=act, direction=direction, thread_key=X.thread_key(conv),
            msg_key=X.msg_key(key or f"{conv}|{hhmm}|{direction}"), subject_tokens=list(tokens),
            counterpart_keys=[X.who(peer)], sender_key=X.who(peer) if direction == "in" else "self",
            rcv=rcv or ("to" if direction == "in" else "na"), attach_keys=[X.doc_key(a) for a in atts],
            attach_names_masked=list(atts), n_participants=2, **kw)
    if flags:
        r["flags"] = dict(flags)
    return r


def docrow(hhmm: str, name: str, op="modify", *, pc="PC1", dirs=(), flags=None, day=DAY0) -> dict:
    r = row("pc_file", "pc.files", hhmm, "exact", day, pc, doc_key=X.doc_key(name), name_masked=name,
            ext=X._ext(name), op=op, dir_keys=[X.dir_key(d) for d in dirs])
    if flags:
        r["flags"] = dict(flags)
    return r


def norm(rows, profile=None, cfg=None, as_of=AS_OF, tags=None) -> Evidence:
    ev, audit = normalize(rows, profile if profile is not None else {"d0": DAY0, "d1": DAY0}, cfg or X.base_cfg(),
                          as_of, tags)
    assert ev.audit is audit
    return ev


class TimeConversionTest(unittest.TestCase):
    def test_utc_to_work_tz_lsec(self):
        ev = norm([mail("09:30", "out", "info", "A")])
        m = ev.msgs[0]
        self.assertEqual(m.t, lt("09:30"))
        self.assertEqual(d_of(m.t), date(2026, 10, 14))
        self.assertEqual(lt("00:00", "2020-01-01"), 0)                     # 기준점 2020-01-01 00:00 로컬(X-174)

    def test_ts_local_offset_not_used(self):
        r = mail("09:30", "out", "info", "A")
        r["ts_local_offset"] = "+00:00"                                    # UTC 클라우드PC — 변환은 tzOffsetMin 하나
        self.assertEqual(norm([r]).msgs[0].t, lt("09:30"))

    def test_tz_offset_setting(self):
        c = X.base_cfg().derive({"time.tzOffsetMin": 0})
        self.assertEqual(norm([mail("09:30", "out", "info", "A")], cfg=c).msgs[0].t, lt("00:30"))

    def test_as_of_forms(self):
        want = lt("18:00", "2026-10-30")
        self.assertEqual(lsec_of(AS_OF, 540), want)
        self.assertEqual(lsec_of(datetime(2026, 10, 30, 18, 0), 540), want)          # 시간대 없음 = 근무 벽시계
        self.assertEqual(lsec_of("2026-10-30T09:00:00Z", 540), want)
        self.assertEqual(lsec_of("2026-10-30 18:00", 540), want)
        self.assertEqual(lsec_of(want, 540), want)
        self.assertEqual(lsec_of(date(2026, 10, 30), 540), lt("00:00", "2026-10-31") - 1)
        with self.assertRaises(TypeError):
            lsec_of(True, 540)
        self.assertEqual(norm([], as_of=AS_OF).as_of, want)

    def test_bad_time_and_pre_epoch(self):
        r1 = mail("09:30", "out", "info", "A")
        r1["ts_utc"] = "2026-13-40T99:00:00Z"
        r2 = mail("09:30", "out", "info", "B")
        r2["ts_utc"] = "2019-12-31T00:00:00Z"
        ev = norm([r1, r2])
        self.assertEqual(ev.msgs, [])
        self.assertEqual(ev.audit["시각_형식오류"], 1)
        self.assertEqual(ev.audit["기준점_이전"], 1)


class PrecisionPrivacyTest(unittest.TestCase):
    def test_unknown_quarantined(self):
        rows = [mail("09:30", "out", "info", "A", prec="unknown"), sampler("09:00", "10:00") | {"ts_precision": "unknown"}]
        ev = norm(rows)
        self.assertEqual((ev.msgs, ev.samples), ([], []))
        self.assertEqual(ev.audit["격리_시각불명"], 2)

    def test_private_social_ad_messages_dropped_samples_kept(self):
        rows = [mail("09:30", "out", "info", "A", priv_class="private"),
                mail("09:31", "out", "info", "B", priv_class="social"),
                mail("09:32", "in", "info", "C", flags={"ad": True}),
                mail("09:33", "out", "social", "D"),
                sampler("10:00", "10:30", app_class="browser", priv="private")]
        ev = norm(rows)
        self.assertEqual(ev.msgs, [])
        self.assertEqual(ev.audit["사적·광고_시간근거제외"], 4)
        self.assertEqual([s.priv for s in ev.samples], ["private"])         # 창 표본은 부정 증거로 남는다

    def test_future_dropped(self):
        ev = norm([mail("09:30", "out", "info", "A", day="2026-10-31"),
                   mail("09:30", "out", "info", "B", day="2026-10-31", prec="date")])
        self.assertEqual([m.prec for m in ev.msgs], ["date"])
        self.assertEqual(ev.audit["미래시각_폐기"], 1)

    def test_dedupe_precision_and_date_absorption(self):
        rows = [mail("12:00", "out", "info", "M50", prec="date", key="K50"),
                mail("15:00", "out", "info", "M50", prec="exact", key="K50"),
                mail("12:00", "out", "info", "M51", prec="date", key="K51"),     # 다른 키 · 같은 날·방향·대화 없음
                mail("12:00", "out", "info", "M50", prec="date", key="K52")]     # 같은 대화의 정밀 사본 있음 → 흡수
        ev = norm(rows)
        self.assertEqual(sorted((m.key, m.prec) for m in ev.msgs),
                         sorted([(X.msg_key("K50"), "exact"), (X.msg_key("K51"), "date")]))
        self.assertEqual(ev.audit["중복_병합"], 1)
        self.assertEqual(ev.audit["date-only_흡수"], 1)

    def test_utc_suspect_and_offset_correction(self):
        rows = [mail(t, "out", "info", f"U{i}", day="2026-10-22", flags={"utc_suspect": True})
                for i, t in enumerate(("01:10", "02:05", "03:30", "05:40", "06:15", "07:20"))]
        ev = norm(rows)
        self.assertTrue(ev.utc_suspect)
        self.assertTrue(ev.warnings)
        c = X.base_cfg().derive({"time.envelope.mailTimeOffsetH": 9})
        ev2 = norm(rows, cfg=c)
        self.assertFalse(ev2.utc_suspect)
        self.assertEqual(ev2.msgs[0].t, lt("10:10", "2026-10-22"))
        self.assertIn("utc", ev2.msgs[0].flags)
        ev3 = norm([mail("01:10", "out", "info", "N")], cfg=c)            # utc 표식 없는 경로는 보정하지 않음
        self.assertEqual(ev3.msgs[0].t, lt("01:10"))


class SessionTest(unittest.TestCase):
    def test_state_mapping_x202(self):
        rows = [sampler("09:00", "09:10", idle=12), sampler("09:10", "09:20", idle=301),
                sampler("09:20", "09:30", state="remote", idle=5), sampler("09:30", "09:40", state="locked"),
                sampler("09:40", "09:50", state="disconnected"), sampler("09:50", "10:00", idle=None)]
        ev = norm(rows)
        self.assertEqual([s.state for s in ev.samples], ["active", "idle", "active", "locked", "disconnected", "active"])
        c = X.base_cfg().derive({"time.envelope.idleActiveSec": 600})
        self.assertEqual(norm(rows[1:2], cfg=c).samples[0].state, "active")

    def test_app_class_mapping_x201(self):
        cat_of = sys.modules["lm27.catalog"].cat_of
        rows = [sampler("09:00", "09:10", app_class="pdf"), sampler("09:10", "09:20", app_class="mail_work"),
                sampler("09:20", "09:30", app_class="messenger_private"), sampler("09:30", "09:40", app_class="meeting"),
                sampler("09:40", "09:50", app_class="system", fg_exe="explorer.exe"),
                sampler("09:50", "10:00", app_class="idle"), sampler("10:00", "10:10", app_class="game"),
                sampler("10:10", "10:20", app_class="other", app_id="ansys"),
                sampler("10:20", "10:30", app_class="remote")]
        got = [s.cls for s in norm(rows).samples]
        eng = "eng" if cat_of("ansys") in ENG_CATEGORIES else "other"
        self.assertEqual(got, ["office", "mail", "chat", "meet", "explorer", "system", "other", eng, "remote"])

    def test_reversed_sample_dropped(self):
        ev = norm([sampler("10:00", "09:00")])
        self.assertEqual(ev.samples, [])
        self.assertEqual(ev.audit["샘플_역순"], 1)

    def test_stuck_pc_day_dropped(self):
        rows = [sampler(f"{h:02d}:00", f"{h:02d}:59", app_class="other", idle=0) for h in range(24)]
        rows.append(sampler("09:00", "09:30", pc="PC2", idle=0))
        ev = norm(rows)
        self.assertEqual({s.pc for s in ev.samples}, {X.pc_id("PC2")})
        self.assertEqual(ev.audit["고착_PC날_폐기"], 1)
        r = sampler("09:00", "09:10", flags={"stuck": True})
        self.assertEqual(norm([r]).samples, [])

    def test_events_pcspan_and_end_uncertain(self):
        rows = [events("08:50", "18:05"),
                events("08:50", "09:00", pc="PC2", day_end="2026-10-15", flags={"end_uncertain": True}),
                docrow("13:30", "설계서.docx", pc="PC2"),
                events("08:00", "09:00", pc="PC3", flags={"end_uncertain": True}),
                events("12:00", "13:00", event_class="sleep")]
        ev = norm(rows)
        spans = {(p.pc, p.a, p.b) for p in ev.pcon}
        self.assertIn((X.pc_id("PC1"), lt("08:50"), lt("18:05")), spans)
        self.assertIn((X.pc_id("PC2"), lt("08:50"), lt("13:30")), spans)    # 확실한 끝 = 마지막 관측(저장)
        self.assertNotIn(X.pc_id("PC3"), {p.pc for p in ev.pcon})            # 관측 없음 → 가동으로 안 셈
        self.assertEqual(ev.audit["가동_끝불확실_제외"], 1)
        self.assertEqual([(s.state, s.a) for s in ev.samples], [("sleep", lt("12:00"))])

    def test_off_and_sleep_derived_from_on_spans_C14(self):
        """계약 v1.2 §0.7 C14(W1 통합 창): 수집기는 켜짐(L0) 구간만 낸다 — 같은 PC 의 L0 켜짐 구간 사이 빈 곳을 증거층이
        '켜져 있지 않음'(Samp sleep, 부정 증거)으로 파생한다(다음 구간을 wake 로 열면 절전, boot 면 꺼짐). 앞 구간 끝이
        불확실하거나 상시 켜짐이면 만들지 않고, 호환 sleep 행과 겹쳐도 한 번만."""
        def l0(a, b, **kw):
            r = events(a, b, **kw)
            r["layer"] = "L0"
            return r
        rows = [l0("08:00", "12:00", event_class="boot"),
                l0("13:00", "15:00", event_class="wake"),                       # 12:00~13:00 절전
                l0("16:00", "18:00", event_class="boot"),                       # 15:00~16:00 꺼짐
                l0("09:00", "10:00", pc="PC2", event_class="boot", flags={"end_uncertain": True}),
                l0("11:00", "12:00", pc="PC2", event_class="boot"),             # 앞 끝 불확실 → 파생 없음
                l0("09:00", "10:00", pc="PC3", event_class="boot"),
                l0("10:00", "10:30", pc="PC3", event_class="sleep"),            # 호환 sleep 행(같은 빈 곳)
                l0("10:30", "11:00", pc="PC3", event_class="wake"),
                events("09:00", "10:00", pc="PC4", event_class="logon"),          # L1 은 파생 대상 아님
                events("11:00", "12:00", pc="PC4", event_class="logon")]
        ev = norm(rows)
        got = sorted((s.pc, s.a, s.b) for s in ev.samples if s.state == "sleep")
        self.assertEqual(got, sorted([(X.pc_id("PC1"), lt("12:00"), lt("13:00")), (X.pc_id("PC1"), lt("15:00"), lt("16:00")),
                                      (X.pc_id("PC3"), lt("10:00"), lt("10:30"))]))
        self.assertEqual(ev.audit["꺼짐절전_파생"], 2)
        self.assertEqual(len([p for p in ev.pcon if p.pc == X.pc_id("PC1")]), 3)   # 켜짐 구간은 그대로


class MessageTest(unittest.TestCase):
    def test_mail_fields(self):
        r = mail("10:00", "in", "request", "M1", tokens=["[과제:P-0001]", "견적", "검토"], atts=["견적서_v2.xlsx"],
                 peer="P7", flags={"cc": True, "bulk": True})
        m = norm([r]).msgs[0]
        self.assertEqual((m.dir, m.act, m.ch, m.conv, m.peer), ("in", "request", "mail", X.thread_key("M1"),
                                                               X.who("P7")))
        self.assertFalse(m.direct)                                             # cc 표식 → 직접 수신 아님
        self.assertEqual(m.tokens, frozenset({"[과제:p-0001]", "견적"}))
        self.assertEqual(m.atts, (X.doc_key("견적서_v2.xlsx"),))
        self.assertEqual(m.flags, frozenset({"cc", "bulk"}))
        self.assertTrue(norm([mail("10:00", "in", "request", "M1")]).msgs[0].direct)

    def test_teams_fields_x203(self):
        base = {"chat_key": X.chat_key("room"), "chat_type": "channel", "thread_key": X.thread_key("root"),
                "author_key": X.who("P3"), "counterpart_keys": [X.who("P3"), X.who("P4")],
                "msg_key": X.msg_key("T1"), "act": "report", "file_keys": [X.doc_key("보고서.pptx")],
                "file_names_masked": ["보고서.pptx"], "subject_tokens": ["주간"], "n_participants": 6}
        m = norm([row("teams", "teams.uia", "10:00", "minute", direction="received", **base)]).msgs[0]
        self.assertEqual((m.dir, m.ch, m.peer, m.n_part), ("in", "teams", X.who("P3"), 6))
        self.assertEqual(m.conv, X.chat_key("room") + ":" + X.thread_key("root"))
        self.assertFalse(m.direct)
        self.assertEqual(m.atts, (B_GENERIC,))                                 # 범용 이름 + 폴더 모름
        m2 = norm([row("teams", "teams.uia", "10:00", "minute", direction="unknown",
                       **(base | {"chat_type": "1:1", "flags": {"mentions_me": True}}))])
        self.assertEqual((m2.msgs[0].dir, m2.msgs[0].direct), ("in", True))
        self.assertEqual(m2.audit["방향미상"], 1)

    def test_act_fallback_and_notice(self):
        r = mail("10:00", "in", "", "M1", act_cues=["ask"])
        self.assertEqual(norm([r]).msgs[0].act, "question")
        r = mail("10:00", "in", "info", "M1", flags={"teams_notice": True}, rcv="cc")
        m = norm([r]).msgs[0]
        self.assertEqual((m.act, "notice" in m.flags), ("notice", True))

    def test_hier_tags_proj(self):
        r = mail("10:00", "in", "request", "M1", key="K1")
        tags = {"msg": {X.msg_key("K1"): "P-0007"}, "fam": {}, "shared_fams": {"x"}}
        ev = norm([r], tags=tags)
        self.assertEqual(ev.msgs[0].proj, "P-0007")
        self.assertIn("x", ev.shared_docs)
        self.assertIsNone(norm([r]).msgs[0].proj)                             # tags=None 허용


class MeetTest(unittest.TestCase):
    def cal(self, **fl):
        r = row("cal", "cal.com", "10:00", "minute", ts_end=X.utc(f"{DAY0} 11:00"), msg_key=X.cal_key("mt"),
                thread_key=X.thread_key("series"), counterpart_keys=[X.who("P2"), X.who("P1")], n_participants=3,
                busy=fl.pop("busy", "busy"), subject_tokens=["설계", "리뷰"], abs_hint="none", location_class="room")
        r["flags"] = fl
        return r

    def test_status_mapping_x204(self):
        cases = [({"response": 3}, "accepted"), ({"response": 1}, "organizer"), ({"organizer_me": True}, "organizer"),
                 ({"response": 2}, "tentative"), ({"response": 5}, "tentative"), ({"response": 4}, "declined"),
                 ({"response": 3, "meeting_status": 5}, "cancelled"), ({"response": 0}, "accepted"),
                 ({"busy": "free"}, "none"), ({"busy": "tentative"}, "tentative")]
        for fl, want in cases:
            with self.subTest(fl=fl):
                self.assertEqual(norm([self.cal(**fl)]).meets[0].status, want)

    def test_fields(self):
        mt = norm([self.cal(response=3, online_meeting=True)]).meets[0]
        self.assertEqual((mt.a, mt.b), (lt("10:00"), lt("11:00")))
        self.assertEqual(mt.attendees, tuple(sorted([X.who("P2"), X.who("P1")])))
        self.assertEqual((mt.n_att, mt.online, mt.personal, mt.organizer), (3, True, False, ""))
        self.assertEqual((mt.key, mt.series), (X.cal_key("mt"), X.thread_key("series")))
        self.assertEqual(mt.tokens, frozenset({"설계", "리뷰"}))

    def test_personal_has_no_tokens(self):                               # P-T12 '제목 저장 안 됨'
        mt = norm([self.cal(response=3, sensitivity=2)]).meets[0]
        self.assertTrue(mt.personal)
        self.assertEqual(mt.tokens, frozenset())

    def test_future_clipped(self):
        ev = norm([self.cal(response=3)], as_of=X.as_of_utc(f"{DAY0} 10:30"))
        self.assertEqual(ev.meets[0].b, lt("10:35"))                      # as_of + futureSlackMin
        self.assertEqual(norm([self.cal(response=3)], as_of=X.as_of_utc(f"{DAY0} 09:00")).meets, [])


class DocTest(unittest.TestCase):
    def test_kinds_x200(self):
        rows = [docrow("10:00", "a.docx", "modify"), docrow("10:01", "b.docx", "create"),
                docrow("10:02", "c.docx", "open"), docrow("10:03", "d.pdf", "modify", flags={"pdf_export": True}),
                docrow("10:04", "e.docx", "save", flags={"view_only": True}),
                docrow("10:05", "f.docx", "modify", flags={"autosave": True, "author_other": True})]
        ev = norm(rows)
        self.assertEqual([e.kind for e in ev.docs], ["save", "create", "open", "export", "open", "save"])
        self.assertEqual((ev.docs[-1].autosave, ev.docs[-1].other), (True, True))

    def test_result_derived_from_compute_end(self):
        comp = row("pc_compute", "pc.compute", "16:30", "minute", ts_end=X.utc("2026-10-15 04:00"), app_id="fluent",
                   doc_key=X.doc_key("열해석_모델.cas"), flags={"solver": True})
        rows = [comp, docrow("16:25", "열해석_모델.cas"), docrow("04:00", "열해석_모델.cas", day="2026-10-15"),
                docrow("09:00", "열해석_모델.cas", day="2026-10-15")]
        ev = norm(rows, profile={"d0": DAY0, "d1": "2026-10-15"})
        self.assertEqual([e.kind for e in ev.docs], ["save", "result", "save"])
        self.assertEqual([(c.a, c.b) for c in ev.comps], [(lt("16:30"), lt("04:00", "2026-10-15"))])

    def test_license_rows_not_compute(self):
        r = row("pc_compute", "pc.compute", "10:00", "minute", ts_end=X.utc(f"{DAY0} 11:00"), app_id="x",
                flags={"license": True})
        ev = norm([r])
        self.assertEqual(ev.comps, [])
        self.assertEqual(ev.audit["라이선스행_제외"], 1)

    def test_burst(self):
        rows = [docrow("10:00", f"사진{i:02d}_현장.jpg", dirs=("현장",)) for i in range(8)]
        ev = norm(rows)
        self.assertEqual(sum(e.burst for e in ev.docs), 7)
        self.assertEqual(ev.audit["파일뭉치_대표1건"], 7)
        c = X.base_cfg().derive({"pc.files.burstN": 9})
        self.assertEqual(sum(e.burst for e in norm(rows, cfg=c).docs), 0)

    def test_generic_names_split_by_folder(self):
        rows = [docrow("10:00", "보고서.pptx", dirs=("과제A", "팀")), docrow("11:00", "보고서.pptx", dirs=("과제B", "팀")),
                docrow("12:00", "견적검토.xlsx", dirs=("과제A",)),
                sampler("09:00", "09:30", doc="견적검토.xlsx"), sampler("09:30", "10:00", doc="보고서.pptx")]
        ev = norm(rows)
        fams = {e.raw: set() for e in ev.docs}
        for e in ev.docs:
            fams[e.raw].add(e.fam)
        dk = X.doc_key("보고서.pptx")
        self.assertEqual(fams["보고서.pptx"], {dk + "@" + X.dir_key("과제A") + "+" + X.dir_key("팀"),
                                            dk + "@" + X.dir_key("과제B") + "+" + X.dir_key("팀")})
        self.assertEqual(fams["견적검토.xlsx"], {X.doc_key("견적검토.xlsx")})
        sfam = {s.a: s.fam for s in ev.samples}
        self.assertEqual(sfam[lt("09:00")], X.doc_key("견적검토.xlsx"))
        self.assertEqual(sfam[lt("09:30")], B_GENERIC)                      # 폴더가 둘 → 가를 수 없음
        self.assertEqual(ev.docs[0].folder, X.dir_key("과제A") + "+" + X.dir_key("팀"))
        self.assertTrue(set(ev.generic_fams) >= {B_GENERIC})
        self.assertEqual(ev.fam_names[X.doc_key("견적검토.xlsx")], "견적검토")
        self.assertEqual(ev.fam_tokens[X.doc_key("견적검토.xlsx")], frozenset({"견적검토"}))
        one = norm([docrow("10:00", "보고서.pptx", dirs=("과제A",)), sampler("09:30", "10:00", doc="보고서.pptx")])
        self.assertEqual(one.samples[0].fam, one.docs[0].fam)               # 폴더가 하나뿐이면 같은 키

    def test_doc_proj_from_tags(self):
        r = docrow("10:00", "하네스시험_A.xlsx")
        ev = norm([r], tags={"fam": {X.doc_key("하네스시험_A.xlsx"): {"proj": "P-0001"}}})
        self.assertEqual(ev.docs[0].proj, "P-0001")


class OtherKindsTest(unittest.TestCase):
    def test_commit_repo_key_as_fam(self):
        r = row("pc_git", "pc.git", "10:00", doc_key=X.repo_key("repoA"), commit_key="g" + "1" * 16,
                msg_masked="센서 보정", subject_tokens=["센서", "보정"], n_commits=1)
        c = norm([r]).commits[0]
        self.assertEqual((c.fam, c.tokens), (X.repo_key("repoA"), frozenset({"센서", "보정"})))

    def test_manual_rows(self):
        rows = [row("manual", "manual", "08:50", "minute", man_kind="instr", ts_end=None,
                    ref_keys=[X.msg_key("Q1"), X.doc_key("점검표_과제H.xlsx")], subject_tokens=["점검표"]),
                row("manual", "manual", "00:00", "date", man_kind="work", hours=2.5, ts_end=None, ref_keys=[],
                    id="aaaaaaaaaaaaaaaa"),
                row("manual", "manual", "13:00", "minute", man_kind="work", hours=1.0, ts_end=None, ref_keys=[]),
                row("manual", "manual", "10:00", "minute", man_kind="attended", ref_keys=[X.cal_key("mt1")]),
                row("manual", "manual", "18:00", "minute", man_kind="retract", retract_of="aaaaaaaaaaaaaaaa"),
                docrow("09:00", "점검표_과제H.xlsx")]
        ev = norm(rows)
        kinds = sorted(m.kind for m in ev.manual)
        self.assertEqual(kinds, ["attended", "instr", "work"])                # 철회 1건 · retract 행 자체 제외
        self.assertEqual(ev.audit["수동_철회"], 1)
        instr = next(m for m in ev.manual if m.kind == "instr")
        self.assertEqual((instr.key, instr.ref, instr.a), (X.msg_key("Q1"), X.doc_key("점검표_과제H.xlsx"), lt("08:50")))
        self.assertIn("과제h", instr.tokens)
        work = next(m for m in ev.manual if m.kind == "work")
        self.assertEqual((work.a, work.b), (lt("13:00"), lt("14:00")))           # 시작 + hours
        att = next(m for m in ev.manual if m.kind == "attended")
        self.assertEqual(att.ref, X.cal_key("mt1"))

    def test_unknown_kind_skipped(self):
        r = row("privacy_audit", "agent", "10:00")
        self.assertEqual(norm([r]).audit["알수없는_kind"], 1)


class ProfileTest(unittest.TestCase):
    def test_leaves_and_coverage_forms(self):
        prof = {"d0": DAY0, "d1": "2026-10-16", "leaves": {"2026-10-15": "am", "2026-10-16": "bogus"},
                "coverage": {("2026-10-15", "mail_out"): "blocked", "2026-10-16|teams": "ok"}}
        ev = norm([], profile=prof)
        self.assertEqual(ev.leaves, {date(2026, 10, 15): "am"})
        self.assertTrue(ev.warnings)
        self.assertEqual(ev.coverage, {(date(2026, 10, 15), "mail_out"): "blocked",
                                       (date(2026, 10, 16), "teams"): "ok"})
        rows = [{"date": "2026-10-15", "kind_axis": "mail_out", "status": "blocked"},
                {"date": "2026-10-15", "kind_axis": "mail_out", "status": "ok"},
                {"date": "2026-10-15", "kind_axis": "bogus", "status": "ok"}]
        ev2 = norm([], profile={"d0": DAY0, "d1": DAY0, "coverage": rows})
        self.assertEqual(ev2.coverage, {(date(2026, 10, 15), "mail_out"): "ok"})   # 같은 칸 = 최선 값
        self.assertEqual(ev2.audit["커버리지_형식오류"], 1)

    def test_period_default_from_evidence(self):
        ev = norm([mail("10:00", "out", "info", "A", day="2026-10-12"), mail("10:00", "out", "info", "B")],
                  profile={})
        self.assertEqual((ev.d0, ev.d1), (date(2026, 10, 12), date(2026, 10, 14)))
        ev = norm([], profile={}, as_of=X.as_of_utc("2026-10-20 12:00"))
        self.assertEqual((ev.d0, ev.d1), (date(2026, 10, 20), date(2026, 10, 20)))
        self.assertEqual(EPOCH, date(2020, 1, 1))

    def test_profile_and_tags_none(self):
        ev, audit = normalize([mail("10:00", "out", "info", "A")], None, X.base_cfg(), AS_OF, None)
        self.assertEqual((ev.d0, ev.d1, ev.leaves, ev.coverage, ev.shared_docs),
                         (date(2026, 10, 14), date(2026, 10, 14), {}, {}, frozenset()))
        self.assertEqual(sum(audit.values()), 0)

    def test_idf_common_tokens(self):
        rows = [mail(f"{9 + i // 6:02d}:{(i % 6) * 10:02d}", "in", "info", f"C{i}", tokens=["과제A", f"주제{i}"])
                for i in range(25)]
        ev = norm(rows)
        self.assertEqual(ev.common_tokens, frozenset({"과제a"}))
        self.assertEqual(ev.common, ev.common_tokens)
        self.assertEqual(norm(rows[:10]).common_tokens, frozenset())          # 노드 < idfMinN → 없음


class NoRawTextTest(unittest.TestCase):
    """원문·열 밖 텍스트가 Evidence 로 새지 않는다(시간 코어는 정제 키·토큰만 — W §2.1 · G8 의 입력 쪽)."""

    def test_canary_columns_not_carried(self):
        cs = CN.text_canaries(CN.canaries(0, groups=("pii",), weak=False))
        needles = [c.value for c in cs][:5]
        self.assertTrue(needles)
        r = mail("10:00", "in", "request", "M1", tokens=["견적"], sender_label=needles[0],
                 categories_masked=[needles[1]], text_masked=needles[2], subject_masked=needles[3])
        cal = row("cal", "cal.com", "11:00", "minute", ts_end=X.utc(f"{DAY0} 12:00"), msg_key=X.cal_key("c"),
                  subject_masked=needles[4], subject_tokens=["주간"], flags={"response": 3, "sensitivity": 2})
        ev = norm([r, cal, sampler("09:00", "10:00")])
        blob = repr(ev)
        for nd in needles[:5]:
            self.assertNotIn(nd, blob)


if __name__ == "__main__":
    unittest.main()
