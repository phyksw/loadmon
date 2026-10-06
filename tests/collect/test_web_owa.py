# -*- coding: utf-8 -*-
"""WP-26 Get-OutlookWeb.py(mail.owa · cal.owa) 시험 — 실물 정제·저장 지점(WP-11 lm27.privacy.sanitize · lm27.store)과
합성 화면 응답(LM_OWA_FAKE)만 쓴다. 쓰기는 %TEMP% 샌드박스(Paths(root, lad=…))에만.

D-14 · X-132(빈칸만 · 보낸 편지함은 열어 minute · 받은 메일은 date) · CM-11(date-only → ts_precision date) · X-315(빈칸 파일) ·
계약 §3.10 커서(assigned_todo_ids · done_ranges, flush 성공 뒤에만) · §8.1 rc(0·1·2·3·4, 예산 = rc 0 + partial + R-BUDGET) ·
v1.2 C1 상태 줄 · T-07(store·감사 카나리아 0) · CM-16(UTC 클라우드PC → utc_suspect · R-TZ) · R-WEBSEL · R-LOGIN · R-CA."""
import json
import re
import unittest
from datetime import date

from lm27.bridge.clock import VirtualClock
from lm27.collect.rcmap import confirmable
from lm27.privacy import context as C
from lm27.privacy.sanitize import sanitize
from tests.fixtures.canary import canaries, canary_ctx, find_canaries
from tests.fixtures.synth import inject, month
from tests.fixtures.wp26 import webkit as K

W = K.OWA
R_ = "R-"                                    # 사유 코드는 런타임에 조립(L-13 — 시험의 표본 문자열)
TODO = "mail.owa:2026-09-01:2026-09-15"


def _path_gap() -> bool:
    """WP-10 rules.RX['path'] 가 뒤에 ' / '·줄바꿈이 오는 경로를 통째로 놓치는가(WP-11 보고 CR #1) — 고쳐지면 False."""
    return "abc" in sanitize(r"C:\Users\abc\Documents\a.xlsx / b").text


def mail_fake(**extra) -> dict:
    inbox = [K.owa_item(K.KIM, "과제A 견적 요청", "2026-09-03", preview="검토 부탁드립니다", key="i1"),
             K.owa_item(K.PEER, "주간 회의록 공유", "2026-09-15", key="i2"),
             K.owa_item(K.KIM, "기간 밖 메일", "2026-09-20", key="i3")]
    sent = [K.owa_item("받는 사람 김철수", "RE: 과제A 견적 요청", "2026-09-04", key="s1",
                       head=["2026년 9월 4일 (금) 오후 2:30"]),
            K.owa_item("받는 사람 동료B", "자료 송부", "2026-09-05", key="s2"),          # 열어도 머리가 없음 → date
            K.owa_item(K.KIM, "같은 항목(받은 편지함에서 먼저 읽음)", "2026-09-03", key="i1")]
    out = {"login": False, "mail": {"2026-09": {"inbox": inbox, "sent": sent},
                                    "2026-08": {"inbox": [K.owa_item(K.KIM, "8월 메일", "2026-08-20", key="a1")]}}}
    out.update(extra)
    return out


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def blanks(self, items=None, name="blanks.json"):
        return str(self.sb.write_json(name, items if items is not None else [
            {"todo_id": TODO, "date_range": ["2026-09-01", "2026-09-15"], "kind_axis": "mail_in"}]))

    def mail(self, *extra, fake=None, **kw):
        return K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks(), *extra],
                         fake=mail_fake() if fake is None else fake, **kw)


class MailTest(_Base):

    def test_blanks_only_inbox_date_sent_opened_minute(self):
        rc, st, err = self.mail()
        self.assertEqual(rc, 0, err)
        self.assertEqual((st["schema"], st["src"], st["rc"]), ("lm27.collector_status/1", "mail.owa", 0))
        rows = {r["subject_masked"]: r for r in self.sb.rows("mail", "mail.owa")}
        self.assertEqual(set(rows), {"[과제:P-0001] 견적 요청", "주간 회의록 공유", "RE: [과제:P-0001] 견적 요청", "자료 송부"})
        inbox = rows["[과제:P-0001] 견적 요청"]
        self.assertEqual((inbox["ts_precision"], inbox["confidence"], inbox["ts_utc"], inbox["box"], inbox["direction"]),
                         ("date", 0.4, "2026-09-03T03:00:00Z", "inbox", "in"))          # CM-11 · 받은 메일은 날짜만
        self.assertEqual(inbox["rcv"], "unknown")                                       # 받는 사람을 모름(C7)
        sent = rows["RE: [과제:P-0001] 견적 요청"]
        self.assertEqual((sent["ts_precision"], sent["confidence"], sent["ts_utc"], sent["direction"], sent["n_to"]),
                         ("minute", 0.8, "2026-09-04T05:30:00Z", "out", 1))             # X-132 · 열어서 분 단위
        self.assertEqual(rows["자료 송부"]["ts_precision"], "date")
        self.assertEqual({r["src"] for r in rows.values()}, {"mail.owa"})
        c = st["counts"]
        self.assertEqual((c["sent_opened"], c["sent_open_fail"], c["out_of_range"], c["dup"]), (1, 1, 1, 1))
        self.assertEqual(st["n"], 4)
        cur = self.sb.cursor("mail.owa")
        self.assertEqual(cur, {"assigned_todo_ids": [TODO], "done_ranges": [["2026-09-01", "2026-09-15"]]})
        self.assertNotIn("8월", json.dumps(cur, ensure_ascii=False))

    def test_second_run_skips_done_and_force_rereads(self):
        self.assertEqual(self.mail()[0], 0)
        n1 = len(self.sb.rows("mail", "mail.owa"))
        rc, st, _ = self.mail()
        self.assertEqual((rc, st["counts"]["days_todo"]), (4, 0))                        # 이미 읽은 구간 — 새로 읽을 것 없음
        self.assertEqual(len(self.sb.rows("mail", "mail.owa")), n1)
        rc, st, _ = self.mail("--force")
        self.assertEqual(rc, 0)
        rows = self.sb.rows("mail", "mail.owa")
        self.assertEqual(len(rows), 2 * n1)
        self.assertEqual(len({r["id"] for r in rows}), n1)                              # 다시 읽어도 같은 id(적재 때 흡수)

    def test_partial_overlap_reads_only_new_days(self):
        self.mail()
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks([
            {"todo_id": "mail.owa:2026-09-10:2026-09-20", "date_range": ["2026-09-10", "2026-09-20"],
             "kind_axis": "mail_out"}], name="b2.json")], fake=mail_fake())
        self.assertEqual(rc, 0)
        self.assertEqual(st["counts"]["days_todo"], 5)                                  # 9/16~9/20 만
        self.assertEqual(self.sb.cursor("mail.owa")["done_ranges"], [["2026-09-01", "2026-09-20"]])
        self.assertEqual(self.sb.cursor("mail.owa")["assigned_todo_ids"],
                         ["mail.owa:2026-09-01:2026-09-15", "mail.owa:2026-09-10:2026-09-20"])

    def test_no_blanks_rc1_without_opening_browser(self):
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail"], fake=mail_fake(login=True))
        self.assertEqual((rc, st["reasons"]), (1, []))                                  # 전체 재수집 폐기 — 화면을 열지 않는다
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--from", "2026-09-01", "--to", "2026-09-05"],
                              fake=mail_fake())
        self.assertEqual(rc, 0)
        self.assertEqual(st["counts"]["days_requested"], 5)

    def test_login_rc2_and_conditional_access(self):
        rc, st, _ = self.mail(fake=mail_fake(login=True))
        self.assertEqual((rc, st["reasons"], st["n"]), (2, [R_ + "LOGIN"], 0))
        self.assertFalse(any(confirmable(r) for r in st["reasons"]))                   # 로그인 전 '불가' 확정 근거 0
        self.assertFalse(self.sb.paths.store_root().exists())
        self.assertEqual(self.sb.cursor("mail.owa"), {})
        rc, st, _ = self.mail(fake=mail_fake(login="ca"))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "CA"]))

    def test_bad_inputs_rc3_with_reason(self):
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", str(self.sb.dir / "none.json")],
                              fake=mail_fake())
        self.assertEqual((rc, st["reasons"], st["counts"]["blanks_error"]), (3, [R_ + "TRANSPORT"], "missing"))
        bad = self.sb.dir / "bad_fake.json"
        bad.write_bytes(b"{not json")
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks()],
                              environ={"LM_OWA_FAKE": str(bad)})
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "TRANSPORT"]))
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--from", "2026-13-01"], fake=mail_fake())
        self.assertEqual((rc, st["counts"]["error"]), (3, "BadArguments"))
        # 다른 축(cal)의 빈칸·형식이 틀린 항목은 뺀다
        p = self.blanks([{"todo_id": "x", "date_range": ["2026-09-01", "2026-09-02"], "kind_axis": "cal"},
                         {"todo_id": "y", "date_range": ["2026-09-09"]}], name="b3.json")
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", p], fake=mail_fake())
        self.assertEqual((rc, st["counts"]["blanks"]), (1, 0))

    def test_websel_when_no_selector_matches(self):
        fake = {"login": False, "mail": {"2026-09": {"inbox": {"how": "", "items": []},
                                                     "sent": {"how": "", "items": []}}}}
        rc, st, _ = self.mail(fake=fake)
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "WEBSEL"]))

    def test_budget_partial_then_resume(self):
        b = self.blanks([{"todo_id": "mail.owa:2026-07-01:2026-09-15", "date_range": ["2026-07-01", "2026-09-15"],
                          "kind_axis": "mail_in"}], name="b4.json")
        fake = mail_fake()
        fake["mail"]["2026-07"] = {"inbox": [K.owa_item(K.KIM, "7월 메일", "2026-07-07", key="j1")]}
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", b, "--budget-sec", "28"], fake=fake,
                              cost=10.0, clock=VirtualClock())
        self.assertEqual(rc, 0)
        self.assertTrue(st["partial"] and st["budget_hit"])
        self.assertIn(R_ + "BUDGET", st["reasons"])
        done1 = self.sb.cursor("mail.owa")["done_ranges"]
        self.assertEqual(done1, [["2026-07-01", "2026-07-31"]])                         # 끝난 조각만 커서에
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", b], fake=fake)
        self.assertEqual((rc, st["partial"]), (0, False))
        self.assertEqual(self.sb.cursor("mail.owa")["done_ranges"], [["2026-07-01", "2026-09-15"]])
        subjects = {r["subject_masked"] for r in self.sb.rows("mail", "mail.owa")}
        self.assertIn("7월 메일", subjects)
        self.assertIn("8월 메일", subjects)

    def test_store_failure_rc3_cursor_unchanged(self):
        api = self.sb.api()
        real = api["SegmentWriter"]

        class Broken:
            def __init__(self, *a, **kw):
                self.w = real(*a, **kw)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self.w.__exit__(*exc)

            def append(self, row):
                self.w.append(row)

            def flush(self):
                raise OSError("disk")

        api["SegmentWriter"] = Broken
        rc, st, _ = self.mail(api=api)
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "TRANSPORT"]))
        self.assertTrue(st["counts"]["store_error"].startswith("store:"))
        self.assertEqual(self.sb.cursor("mail.owa"), {})

    def test_tz_mismatch_utc_suspect(self):
        self.sb.cfg = self.sb.cfg.derive({"time.tzOffsetMin": 0})
        rc, st, _ = self.mail()
        self.assertEqual(rc, 0)
        self.assertIn(R_ + "TZ", st["reasons"])
        rows = self.sb.rows("mail", "mail.owa")
        self.assertTrue(all((r.get("flags") or {}).get("utc_suspect") for r in rows if r["ts_precision"] == "minute"))
        self.assertFalse(any((r.get("flags") or {}).get("utc_suspect") for r in rows if r["ts_precision"] == "date"))

    def test_synth_month_inject_format(self):
        plan = month.plan_month(2026, 9)
        fake = inject.owa_fake(plan)
        b = self.blanks([{"todo_id": "mail.owa:2026-09-01:2026-09-30", "date_range": ["2026-09-01", "2026-09-30"],
                          "kind_axis": "mail_out"}], name="b5.json")
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", b], fake=fake, now=plan.as_of)
        self.assertEqual(rc, 0)
        rows = self.sb.rows("mail", "mail.owa")
        self.assertEqual(len(rows), len(plan.mails))
        sent = [r for r in rows if r["box"] == "sent"]
        self.assertEqual(len(sent), sum(1 for ev in plan.mails if ev.box == "sent"))
        self.assertTrue(all(r["direction"] == "out" and r["sender_key"] == "self" for r in sent))
        self.assertTrue(all(re.fullmatch(r"m[0-9a-f]{24}", r["msg_key"]) for r in rows))


class CalTest(_Base):

    def cal_fake(self) -> dict:
        ev = K.owa_event
        cal = {"2026-09-01": [ev("과제A 주간 회의", date(2026, 9, 1), (9, 0), (10, 0), "3층 회의실")],
               "2026-09-10": [{"label": "출장, 2026년 9월 10일 ~ 2026년 9월 15일, 종일, 부재 중", "texts": ["출장"]}],
               "2026-09-14": [{"label": "출장, 2026년 9월 10일 ~ 2026년 9월 15일, 종일, 부재 중", "texts": ["출장"]}],
               "2026-09-30": [ev("과제A 점검", date(2026, 9, 30), (14, 0), (15, 0), "Microsoft Teams 모임")],
               "2026-10-01": [ev("오늘 회의", date(2026, 10, 1), (10, 0), (11, 0), "2층 회의실")]}
        return {"login": False, "cal": cal}

    def test_period_weeks_dedupe_and_done_weeks(self):
        rc, st, err = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-10-01"],
                                fake=self.cal_fake())
        self.assertEqual(rc, 0, err)
        rows = {r["subject_masked"]: r for r in self.sb.rows("cal", "cal.owa")}
        self.assertEqual(set(rows), {"[과제:P-0001] 주간 회의", "출장", "[과제:P-0001] 점검", "오늘 회의"})
        trip = rows["출장"]
        self.assertEqual((trip["ts_precision"], trip["confidence"], trip["busy"]), ("date", 0.4, "oof"))
        self.assertEqual((trip["ts_utc"], trip["ts_end"]), ("2026-09-09T15:00:00Z", "2026-09-15T14:59:00Z"))
        self.assertEqual(rows["[과제:P-0001] 점검"]["location_class"], "online")
        self.assertEqual(rows["[과제:P-0001] 주간 회의"]["location_class"], "room")
        self.assertEqual(st["counts"]["dup"], 1)                                        # 두 주에 걸친 막대는 한 번만
        self.assertEqual(self.sb.cursor("cal.owa")["done_ranges"], [["2026-09-01", "2026-09-27"]])   # 이번 주는 열린 채로
        rc, st, _ = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-10-01"],
                              fake=self.cal_fake())
        self.assertEqual((rc, st["counts"]["days_todo"], st["counts"]["weeks"]), (0, 4, 1))     # 이번 주만 다시

    def test_synth_month_cal_inject_format(self):
        plan = month.plan_month(2026, 9)
        rc, st, _ = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-09-30"],
                              fake=inject.owa_fake(plan), now=plan.as_of)
        self.assertEqual(rc, 0)
        rows = self.sb.rows("cal", "cal.owa")
        self.assertEqual(len(rows), len(plan.meets))                                   # 반복 회차도 주 보기에서 하나씩
        self.assertEqual({r["ts_precision"] for r in rows}, {"minute"})
        self.assertTrue(all(re.fullmatch(r"e[0-9a-f]{24}", r["msg_key"]) for r in rows))
        self.assertEqual(sorted(r["ts_utc"] for r in rows), sorted(ev.start.strftime("%Y-%m-%dT%H:%M:%SZ")
                                                                   for ev in plan.meets))

    def test_no_grid_websel(self):
        rc, st, _ = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-09-10"],
                              fake={"login": False, "cal": {}, "cal_grid": False})
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "WEBSEL"]))
        rc, st, _ = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-09-10"],
                              fake={"login": False, "cal": {}})
        self.assertEqual((rc, st["reasons"]), (1, []))                                  # 주 보기는 있는데 일정 0 = 대상 없음


class CanaryTest(_Base):

    def test_t07_store_and_audit(self):
        cs = [c for c in canaries(groups=["pii", "ctx"], weak=False) if c.sentence]
        cx = canary_ctx(cs)
        reg = {"internal_domains": ["corp.example"], "customers": cx["customers"], "projects": cx["projects"]}
        local = {"person_dir": {"format": C.PERSONDIR_FORMAT,
                                "people": {"w" + v: {"names": [n]} for n, v in cx["persons"].items()}}}
        api = self.sb.api(registry=reg, os_names=["홍길동", *cx["self_names"]], local=local)
        inbox, sent, cal = [], [], {}
        for i, c in enumerate(cs):
            d = date(2026, 9, 1 + i % 28)
            inbox.append(K.owa_item(K.KIM, c.sentence, d.isoformat(), preview=c.sentence, key=f"c{i}"))
            sent.append(K.owa_item("받는 사람 김철수", "회신 " + c.sentence, d.isoformat(), key=f"s{i}",
                                   head=[f"{K.kdate(d)} 오후 2:{i % 60:02d}"]))
            cal.setdefault(d.isoformat(), []).append(K.owa_event(c.sentence, d, (9, 0), (10, 0), c.sentence))
        fake = {"login": False, "mail": {"2026-09": {"inbox": inbox, "sent": sent}}, "cal": cal}
        b = self.blanks([{"todo_id": "t", "date_range": ["2026-09-01", "2026-09-30"], "kind_axis": "mail_in"}],
                        name="bc.json")
        rc, st, err = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", b], fake=fake, api=api)
        self.assertEqual(rc, 0, err)
        rc2, _st2, err2 = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-09-30"],
                                    fake=fake, api=api)
        self.assertEqual(rc2, 0)
        self.assertGreater(len(self.sb.rows("mail", "mail.owa")), len(cs))
        known = {c.cid for c in cs if c.cat in ("path_win", "path_unc")} if _path_gap() else set()
        found = set(find_canaries(self.sb.store_bytes(), cs))
        self.assertEqual(sorted(found - known), [])
        audit = json.dumps(self.sb.audit_lines(), ensure_ascii=False).encode("utf-8")
        self.assertTrue(self.sb.audit_lines())
        self.assertEqual(find_canaries(audit, cs), [])
        self.assertEqual(find_canaries((err + err2).encode("utf-8"), cs), [])            # 상태 줄·안내 줄에도 0


if __name__ == "__main__":
    unittest.main()
