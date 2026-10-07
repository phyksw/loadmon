# -*- coding: utf-8 -*-
r"""tests\test_p2_owa.py — WP2: Outlook 웹 검증 수집(F-03·F-04·F-05) · 시각 복원(UD-08) · 병합(W1-04) · 반입 파일(C-17) ·
Copilot 메일 축소(C-16·C-34·W1-13).

실제 Edge·Outlook·네트워크를 쓰지 않는다 — tests\fakes\fake_browser.py(FakeBrowser: Get-OutlookWeb 의 JS 상수 머리 표식에
각본 응답)와 주입한 왕복 함수로 돈다. 운영 data\ 에 쓰지 않는다(파일은 tempfile 폴더만, 모듈 OUT_DIR 도 임시로 돌린다).
"""
import contextlib
import csv
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import _boot  # noqa: F401  — 경로 등록
import owa_parse as op  # noqa: E402

sys.path.insert(0, os.path.join(_boot.TESTS, "fakes"))
import fake_browser as fb  # noqa: E402

COL = os.path.join(_boot.ROOT, "collect")


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, os.path.join(COL, fn))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


owa = _load("owa_web_t", "Get-OutlookWeb.py")
owa._sleep = lambda s: None                    # 수집 루프 대기 없음
owa.log = lambda msg: None                     # 수집기 진행 줄은 시험 출력에 싣지 않는다(main 시험은 LMSTATUS 만 본다)
mvc = _load("mail_copilot_t", "Get-MailViaCopilot.py")
imc = _load("import_mailcal_t", "Import-MailCal.py")

TODAY = date(2026, 10, 7)                      # 수요일
D = date.fromisoformat


def _st_days(day_st, a, b, want):
    """a~b 의 날이 모두 want 상태인가 → 어긋난 날 목록"""
    bad, d = [], a
    while d <= b:
        if day_st.get(d) != want:
            bad.append((d.isoformat(), day_st.get(d)))
        d += timedelta(days=1)
    return bad


def _status_of(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    assert lines and lines[-1].startswith("LMSTATUS "), lines[-3:]
    return json.loads(lines[-1][len("LMSTATUS "):])


class ParseListDate(unittest.TestCase):
    def test_relative_and_absolute(self):
        p = op.parse_list_date
        self.assertEqual(p("오후 3:12", TODAY), (TODAY, (15, 12)))                 # 오늘 = 시각만
        self.assertEqual(p("화 10:05", TODAY), (D("2026-10-06"), (10, 5)))         # 이번 주 = 요일+시각
        self.assertEqual(p("화 오후 3:12", TODAY), (D("2026-10-06"), (15, 12)))
        self.assertEqual(p("Tue 3:12 PM", TODAY), (D("2026-10-06"), (15, 12)))
        self.assertEqual(p("수 9:00", TODAY), (D("2026-09-30"), (9, 0)))           # 오늘과 같은 요일 = 7일 전
        self.assertEqual(p("어제", TODAY), (D("2026-10-06"), None))
        self.assertEqual(p("2026-03-05", TODAY), (D("2026-03-05"), None))         # 연월일
        self.assertEqual(p("2026년 3월 5일 (목) 오후 3:12", TODAY), (D("2026-03-05"), (15, 12)))
        self.assertEqual(p("Mar 5", TODAY), (D("2026-03-05"), None))
        self.assertEqual(p("12/30", TODAY), (D("2025-12-30"), None))              # 연도 없으면 오늘 이전이 되는 해
        self.assertIsNone(p("월간 보고", TODAY))                                   # 제목 글은 날짜가 아니다
        self.assertIsNone(p("3/5 보고", TODAY))

    def test_list_when_joins_date_and_time_fragments(self):
        self.assertEqual(op.list_when(["Hong", "Thu 3/5/2026", "3:12 PM"], TODAY), (D("2026-03-05"), (15, 12)))
        self.assertEqual(op.list_when(op.frags_of("홍길동, 3/5 보고, 오후 3:12"), TODAY), (TODAY, (15, 12)))

    def test_parse_mail_item_relative_and_quote_guard(self):
        it = {"label": "동료, 주간 보고, 화 오후 3:12", "texts": ["동료", "주간 보고", "화 오후 3:12"]}
        info = {}
        r = owa.parse_mail_item(it, None, None, "inbox", TODAY, info)
        self.assertEqual(r[1], "2026-10-06 15:12")
        self.assertEqual(info["date"], D("2026-10-06"))
        # 미리보기 속 인용문 머리글의 날짜는 쓰지 않는다(LM24 규칙 유지)
        it2 = {"label": "동료, 회의 결과, 2026-03-05",
               "texts": ["동료", "회의 결과", "2026년 6월 12일 (금) 오전 10:00, 홍길동 님이 작성:"]}
        r2 = owa.parse_mail_item(it2, D("2026-03-01"), D("2026-03-31"), "inbox", TODAY, {})
        self.assertEqual(r2[1][:10], "2026-03-05")

    def test_iso_local_and_week_header(self):
        loc = datetime(2026, 3, 5, 6, 12, tzinfo=timezone(timedelta(0))).astimezone()
        self.assertEqual(op.iso_local("2026-03-05T06:12:00Z"), (loc.date(), (loc.hour, loc.minute)))
        self.assertEqual(op.iso_local("2026-03-05T15:12"), (D("2026-03-05"), (15, 12)))
        w = op.week_header_range
        self.assertEqual(w("2026년 9월 14일–20일"), (D("2026-09-14"), D("2026-09-20")))
        self.assertEqual(w("2026년 9월 28일 – 10월 4일"), (D("2026-09-28"), D("2026-10-04")))
        self.assertEqual(w("2026년 12월 28일–2027년 1월 3일"), (D("2026-12-28"), D("2027-01-03")))
        self.assertEqual(w("September 14–20, 2026"), (D("2026-09-14"), D("2026-09-20")))
        self.assertEqual(w("Dec 28 – Jan 3, 2027"), (D("2026-12-28"), D("2027-01-03")))
        self.assertIsNone(w("2026년 9월"))
        self.assertIsNone(w("오전 9:00 – 오전 10:00"))                             # 일정 시각은 주 범위가 아니다
        self.assertIsNone(w("정기 회의, 2026년 9월 14일 ~ 2026년 9월 18일"))         # 제목이 든 일정 막대


class SliceVerdict(unittest.TestCase):
    s, e = D("2026-03-01"), D("2026-03-31")

    def test_five_cases(self):
        v = op.slice_verdict
        ok = [D("2026-03-30"), D("2026-03-12"), D("2026-03-01")]
        self.assertEqual(v(ok, self.s, self.e, False, False, True), ("ok", None))
        self.assertEqual(v(ok, self.s, self.e, False, False, False), ("list_verified", D("2026-03-01")))
        lst = [TODAY - timedelta(days=i) for i in range(0, 250, 3)]                  # 최신부터 끊김 없이(목록 모드)
        self.assertEqual(v(lst, D("2026-01-01"), D("2026-09-30"), False, True), ("list_verified", lst[-1]))
        self.assertEqual(v(lst, D("2026-01-01"), D("2026-09-30"), False, True, True), ("ok", None))   # 목록 전체가 보임
        self.assertEqual(v(lst[::-1], self.s, self.e, False, False, False)[0], "filter_ineffective")
        self.assertEqual(v([TODAY, TODAY], self.s, self.e), ("filter_ineffective", None))   # 검색이 안 걸린 화면
        self.assertEqual(v([], self.s, self.e, True), ("empty_verified", None))
        self.assertEqual(v([], self.s, self.e, False), ("unverified", None))
        self.assertEqual(v([None, None], self.s, self.e), ("unverified", None))
        mixed = [D("2026-05-01"), D("2026-02-01")] * 30                              # 날짜 순서가 아닌 목록
        self.assertEqual(v(mixed, D("2026-01-01"), D("2026-09-30"), False, True)[0], "unverified")

    def test_ranges(self):
        r = op.verdict_ranges
        self.assertEqual(r("list_verified", D("2026-02-10"), D("2026-01-01"), D("2026-09-30")),
                         [(D("2026-01-01"), D("2026-02-10"), "partial"), (D("2026-02-11"), D("2026-09-30"), "ok")])
        self.assertEqual(r("list_verified", D("2025-12-31"), D("2026-01-01"), D("2026-09-30")),
                         [(D("2026-01-01"), D("2026-09-30"), "ok")])
        self.assertEqual(r("empty_verified", None, self.s, self.e), [(self.s, self.e, "zero_ok")])
        self.assertEqual(r("filter_ineffective", None, self.s, self.e), [(self.s, self.e, "unverified")])
        ds = {D("2026-10-06"): "unverified", TODAY: "unverified"}
        op.apply_ranges(ds, [(D("2026-10-06"), TODAY, "ok")], TODAY)                   # 오늘은 ok 대신 partial
        self.assertEqual(ds, {D("2026-10-06"): "ok", TODAY: "partial"})


class OwaMail(unittest.TestCase):
    d0, d1 = D("2026-01-01"), D("2026-09-30")

    def _run(self, br, **kw):
        run = owa.Run(self.d0, self.d1, today=TODAY, recover_max=kw.pop("recover_max", 0))
        rows, st, diag, day_st = owa.collect_mail(br, self.d0, self.d1, run=run)
        return run, rows, day_st

    def test_f03_search_ignored_list_verified(self):
        box = fb.make_mailbox(D("2025-12-01"), TODAY)
        br = fb.FakeBrowser(TODAY, mail=box, ignore_search=True)
        run, rows, day_st = self._run(br)
        self.assertEqual(br.calls["search"], 2)                       # 첫 조각에서 폴더마다 한 번 — 그 뒤 조각은 폴백이 덮었다
        self.assertEqual(run.c["fallback_scroll"], 2)                 # 폴백은 폴더당 1회
        self.assertEqual(run.c["filter_ineffective"], 2)
        for ax in ("mail_in", "mail_out"):
            self.assertEqual(_st_days(day_st[ax], self.d0, self.d1, "ok"), [], ax)
            rg = op.ranges_of(day_st[ax], ax)
            self.assertEqual(rg, [{"axis": ax, "from": "2026-01-01", "to": "2026-09-30", "st": "ok"}])
        # Copilot 이 물을 날(ok·zero_ok 아닌 날)이 없다 = run 경로에서 Copilot 호출 0
        gaps = [d for ax in day_st for d, s in day_st[ax].items() if s not in ("ok", "zero_ok")]
        self.assertEqual(gaps, [])
        self.assertEqual(len(rows), 2 * ((self.d1 - self.d0).days + 1))
        self.assertEqual(len({(r[0], r[1][:10]) for r in rows}), len(rows))   # 중복 없음

    def test_f03_cannot_reach_january_partial_only(self):
        box = fb.make_mailbox(D("2025-12-01"), TODAY)
        cut = [m["when"].date() for m in box["inbox"]].index(D("2026-03-10")) + 1
        br = fb.FakeBrowser(TODAY, mail=box, ignore_search=True, reach=cut)
        run, rows, day_st = self._run(br)
        for ax in ("mail_in", "mail_out"):
            self.assertEqual(op.ranges_of(day_st[ax], ax),
                             [{"axis": ax, "from": "2026-01-01", "to": "2026-03-10", "st": "partial"},
                              {"axis": ax, "from": "2026-03-11", "to": "2026-09-30", "st": "ok"}])

    def test_small_folder_fits_is_complete(self):
        box = fb.make_mailbox(D("2026-09-01"), TODAY)
        box["sent"] = box["sent"][:5]                                 # 보낸 편지함 5통 — 목록 전체가 한 화면
        br = fb.FakeBrowser(TODAY, mail=box, ignore_search=True)
        _run, _rows, day_st = self._run(br)
        self.assertEqual(_st_days(day_st["mail_out"], self.d0, self.d1, "ok"), [])   # 끝까지 보였으니 기간 전체 읽음(0건)
        self.assertEqual(day_st["mail_in"][D("2026-08-31")], "partial")              # 'end' 만으로는 더 오래된 메일이 없다고 보지 않는다

    def test_search_works_month_slices_ok(self):
        box = fb.make_mailbox(D("2026-01-01"), D("2026-03-31"))
        br = fb.FakeBrowser(TODAY, mail=box)
        d0, d1 = D("2026-01-01"), D("2026-03-31")
        run = owa.Run(d0, d1, today=TODAY, recover_max=0)
        rows, _st, _diag, day_st = owa.collect_mail(br, d0, d1, run=run)
        self.assertEqual(run.c["slices_ok"], 6)
        self.assertEqual(run.c["fallback_scroll"], 0)
        self.assertEqual(_st_days(day_st["mail_in"], d0, d1, "ok"), [])
        self.assertEqual(len(rows), 2 * 90)

    def test_no_scroller_is_partial_not_ok(self):
        box = fb.make_mailbox(D("2026-03-01"), D("2026-03-31"), per_day=3)
        br = fb.FakeBrowser(TODAY, mail=box, no_scroller=True)
        d0, d1 = D("2026-03-01"), D("2026-03-31")
        run = owa.Run(d0, d1, today=TODAY, recover_max=0)
        _rows, _st, _diag, day_st = owa.collect_mail(br, d0, d1, run=run)
        sts = set(day_st["mail_in"].values())
        self.assertIn("partial", sts)                                 # 끝을 모르는 화면은 '읽음'으로 적지 않는다
        self.assertEqual(day_st["mail_in"][d1], "ok")                 # 맨 아래 날짜 뒤(최신 쪽)만 ok

    def test_focused_pivot_fallback_not_ok(self):
        box = fb.make_mailbox(D("2025-12-01"), TODAY)
        br = fb.FakeBrowser(TODAY, mail=box, ignore_search=True, pivot=True)
        run, _rows, day_st = self._run(br)
        self.assertNotIn("ok", set(day_st["mail_in"].values()))      # '중요' 탭만 보이는 목록은 읽음 아님
        self.assertEqual(_st_days(day_st["mail_out"], self.d0, self.d1, "ok"), [])
        self.assertEqual(run.sd.get("focused_pivot"), 1)

    def test_time_recovery_from_item_attrs_and_reading_pane(self):
        sent = [fb.msg("a", datetime(2026, 3, 5, 15, 12), "나", "회신", dts=["2026-03-05 (목) 오후 3:12"]),
                fb.msg("b", datetime(2026, 3, 10, 9, 41), "나", "회신", dts=["2026-03-10T09:41:00"]),
                fb.msg("c", datetime(2026, 3, 20, 17, 3), "나", "회신", open=["2026-03-20 (금) 오후 5:03"])]
        d0, d1 = D("2026-03-01"), D("2026-03-31")
        # ① 항목의 다른 title·datetime 속성만(읽기 창 0건) → 3건 중 2건 복원
        br = fb.FakeBrowser(TODAY, mail={"inbox": [], "sent": sent})
        run = owa.Run(d0, d1, today=TODAY, recover_max=0)
        rows, _st, diag, _ds = owa.collect_mail(br, d0, d1, run=run)
        self.assertEqual(run.c["recovered"], 2)
        self.assertEqual(diag["date_only"], 1)
        got = {r[1] for r in rows}
        self.assertIn("2026-03-05 15:12", got)
        self.assertIn("2026-03-10 09:41", got)
        self.assertIn("2026-03-20 12:00", got)                        # 날짜만 = 12:00 + time_precision=date
        self.assertEqual(br.calls["open"], 0)
        # ② 읽기 창(보낸 편지함만, 상한 안) → 나머지 1건도
        br2 = fb.FakeBrowser(TODAY, mail={"inbox": [], "sent": sent})
        run2 = owa.Run(d0, d1, today=TODAY, recover_max=5)
        rows2, _st, diag2, _ds = owa.collect_mail(br2, d0, d1, run=run2)
        self.assertEqual(run2.c["recovered"], 3)
        self.assertEqual(run2.c["opened"], 1)
        self.assertEqual(diag2["date_only"], 0)
        self.assertIn("2026-03-20 17:03", {r[1] for r in rows2})

    def test_inbox_items_are_not_opened(self):
        inbox = [fb.msg("x", datetime(2026, 3, 5, 9, 0), "동료", "안내", open=["2026-03-05 (목) 오전 9:00"])]
        br = fb.FakeBrowser(TODAY, mail={"inbox": inbox, "sent": []})
        d0, d1 = D("2026-03-01"), D("2026-03-31")
        run = owa.Run(d0, d1, today=TODAY, recover_max=10)
        owa.collect_mail(br, d0, d1, run=run)
        self.assertEqual(br.calls["open"], 0)                         # 받은 메일은 열지 않는다(읽음 표시)


class OwaCal(unittest.TestCase):
    def test_f05_url_ignored_sequential_prev_week(self):
        d0, d1 = D("2026-08-03"), TODAY
        evs = fb.make_events(D("2026-07-27"), D("2026-10-09"))
        br = fb.FakeBrowser(TODAY, events=evs, ignore_url=True, stuck_clicks={3}, bad_header={D("2026-09-07")})
        run = owa.Run(d0, d1, today=TODAY)
        rows, _st, diag, day_st = owa.collect_cal(br, d0, d1, run=run)
        n_weeks = 10
        self.assertEqual(br.calls["goto"], 1)                         # URL 이동은 시작 주 한 번
        self.assertLessEqual(run.c["cal_clicks"], n_weeks + 3)
        self.assertEqual(run.c["weeks_unverified"], 1)
        self.assertEqual(run.c["weeks_ok"], n_weeks - 1)
        bad = [r for r in rows if "2026-09-07" <= r[0][:10] <= "2026-09-13"]
        self.assertEqual(bad, [])                                     # 머리 불일치 주의 행 0
        self.assertEqual(_st_days(day_st, D("2026-09-07"), D("2026-09-13"), "unverified"), [])
        self.assertEqual(_st_days(day_st, D("2026-08-03"), D("2026-09-06"), "ok"), [])
        self.assertEqual(day_st[TODAY], "partial")
        ok_days = {r[0][:10] for r in rows}
        self.assertIn("2026-08-03", ok_days)
        self.assertIn("2026-10-06", ok_days)

    def test_header_unreadable_is_unverified(self):
        evs = fb.make_events(D("2026-09-28"), D("2026-10-09"))
        br = fb.FakeBrowser(TODAY, events=evs)
        br._header = lambda ws: "캘린더"                              # 머리를 못 읽는 화면
        d0, d1 = D("2026-09-28"), TODAY
        run = owa.Run(d0, d1, today=TODAY)
        rows, st, _diag, day_st = owa.collect_cal(br, d0, d1, run=run)
        self.assertEqual(st, "unverified")
        self.assertEqual(rows, [])
        self.assertEqual(set(day_st.values()), {"unverified"})


class MergeSave(unittest.TestCase):
    def test_merge_keeps_unverified_months(self):
        old = [["inbox", "2026-02-10 09:00", "A", "옛 2월", "옛 2월", "to", "minute"],
               ["inbox", "2026-03-05 09:00", "B", "옛 3월", "옛 3월", "to", "minute"],
               ["sent", "2026-03-06 12:00", "나", "보고", "보고", "", "date"]]
        new = [["inbox", "2026-03-07 10:00", "C", "새 3월", "새 3월", "to", "minute"],
               ["sent", "2026-03-06 15:20", "나", "보고", "보고", "", "minute"]]
        out = op.merge_slices(old, new, {"mail_in": [("2026-03-01", "2026-03-31")]}, "mail")
        subj = [r[3] for r in out]
        self.assertIn("옛 2월", subj)                                 # 미검증 달의 옛 행 보존
        self.assertNotIn("옛 3월", subj)                              # 검증한 달(받은 편지함)은 이번 행으로
        self.assertIn("새 3월", subj)
        sent = [r for r in out if r[0] == "sent"]
        self.assertEqual([r[1] for r in sent], ["2026-03-06 15:20"])  # 날짜만 행은 분 단위 행으로 바뀐다

    def test_save_writes_merge_not_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            p = os.path.join(tmp, "mail_owa.csv")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(owa.MAIL_HDR + "\n")
                f.write("inbox,2026-02-10 09:00,A,옛 2월,옛 2월,to,minute\n")
                f.write("inbox,2026-03-05 09:00,B,옛 3월,옛 3월,to,minute\n")
            owa._save("mail", [["inbox", "2026-03-07 10:00", "C", "새 3월", "새 3월", "to", "minute"]], True, p,
                      {"mail_in": [("2026-03-01", "2026-03-31")], "mail_out": []})
            with open(p, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))[1:]
            self.assertEqual(sorted(r[3] for r in rows), ["새 3월", "옛 2월"])


class OwaMain(unittest.TestCase):
    """main 끝단 — 잠금 안 사용·자기 탭만 닫기·출처별 파일·LMSTATUS 마지막 줄."""

    def _main(self, argv, env=None):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["Get-OutlookWeb.py"] + argv), \
                mock.patch.dict(os.environ, env or {}, clear=False), contextlib.redirect_stdout(out):
            rc = owa.main()
        return rc, out.getvalue()

    def test_main_fake_browser_tagged_files(self):
        today = date.today()
        box = fb.make_mailbox(today - timedelta(days=60), today)
        br = fb.FakeBrowser(today, mail=box, events=fb.make_events(today - timedelta(days=20), today))
        locks = []

        @contextlib.contextmanager
        def lock(cfg=None, timeout=600):
            locks.append(1)
            yield "x"
        br.ca = types.SimpleNamespace(edge_lock=lock, EdgeBusy=RuntimeError)
        br.cfg = {}
        d0, d1 = today - timedelta(days=40), today - timedelta(days=1)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp, mock.patch.object(owa, "Browser", lambda: br):
            env = dict.fromkeys(("LM_OWA_FAKE", "LM_NO_BROWSER"), "")
            rc, text = self._main(["--from", d0.isoformat(), "--to", d1.isoformat(), "--out-dir", tmp, "--tag", "owa"], env)
            st = _status_of(text)
            self.assertEqual((rc, st["rc"], st["src"]), (0, 0, "owa"))
            self.assertEqual(locks, [1])                              # 전용 Edge 는 잠금 안에서
            self.assertEqual(br.closed, "closed")                     # 이 수집기가 연 탭만 닫는다(로그인 대기 아님)
            for fn in ("mail_owa.csv", "cal_owa.csv", "mail_source_owa.json"):
                self.assertTrue(os.path.isfile(os.path.join(tmp, fn)), fn)
            with open(os.path.join(tmp, "mail_source_owa.json"), encoding="utf-8") as f:
                src = json.load(f)
            for k in ("source", "mail_rows", "date_only", "me", "ver"):
                self.assertIn(k, src)
            axes = {r["axis"] for r in st["ranges"]}
            self.assertEqual(axes, {"mail_in", "mail_out", "cal"})
            mi = [r for r in st["ranges"] if r["axis"] == "mail_in"]
            self.assertEqual(mi, [{"axis": "mail_in", "from": d0.isoformat(), "to": d1.isoformat(), "st": "ok"}])
            for k in ("slices_ok", "list_verified", "filter_ineffective", "fallback_scroll", "weeks_ok", "weeks_unverified",
                      "cal_clicks", "date_only", "recovered", "rows", "selector_diag"):
                self.assertIn(k, st["counts"])

    def test_main_edge_busy_and_login(self):
        @contextlib.contextmanager
        def busy(cfg=None, timeout=600):
            raise RuntimeError("busy")
            yield
        stub = types.SimpleNamespace(ca=types.SimpleNamespace(edge_lock=busy, EdgeBusy=RuntimeError), cfg={})
        env = dict.fromkeys(("LM_OWA_FAKE", "LM_NO_BROWSER"), "")
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp, mock.patch.object(owa, "Browser", lambda: stub):
            rc, text = self._main(["--from", "2026-03-01", "--to", "2026-03-31", "--out-dir", tmp, "--tag", "owa"], env)
        self.assertEqual((rc, _status_of(text)["reason"]), (3, "R-EDGEBUSY"))
        br = fb.FakeBrowser(TODAY, mail={}, login=True)

        @contextlib.contextmanager
        def lock(cfg=None, timeout=600):
            yield "x"
        br.ca = types.SimpleNamespace(edge_lock=lock, EdgeBusy=RuntimeError)
        br.cfg = {}
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp, mock.patch.object(owa, "Browser", lambda: br):
            rc, text = self._main(["--from", "2026-03-01", "--to", "2026-03-31", "--out-dir", tmp, "--tag", "owa"], env)
        self.assertEqual((rc, _status_of(text)["reason"]), (2, "R-LOGIN"))
        self.assertEqual(br.closed, "kept")                           # 로그인 대기 — 탭을 닫지 않는다

    def test_main_no_browser_and_legacy_fake(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            rc, text = self._main(["--from", "2026-03-01", "--to", "2026-03-31", "--out-dir", tmp, "--tag", "owa"],
                                  {"LM_OWA_FAKE": "", "LM_NO_BROWSER": "1"})
            self.assertEqual((rc, _status_of(text)["rc"]), (3, 3))
            fake = {"mail": {"2026-03": {"inbox": [{"key": "k1", "label": "동료, 안내, 2026-03-05 오전 9:10",
                                                     "texts": ["동료", "안내"]}], "sent": []}}}
            fk = os.path.join(tmp, "fake.json")
            with open(fk, "w", encoding="utf-8") as f:
                json.dump(fake, f, ensure_ascii=False)
            rc, text = self._main(["--from", "2026-03-01", "--to", "2026-03-31", "--only", "mail", "--out-dir", tmp,
                                   "--tag", "owa"], {"LM_OWA_FAKE": fk, "LM_NO_BROWSER": ""})
            self.assertEqual(rc, 0)
            with open(os.path.join(tmp, "mail_owa.csv"), encoding="utf-8-sig") as f:
                self.assertIn("2026-03-05 09:10", f.read())


class ImportMailCal(unittest.TestCase):
    def test_eml_and_ics_weekly_count(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            src, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
            os.makedirs(os.path.join(src, "보낸 편지함"))
            with open(os.path.join(src, "a.eml"), "w", encoding="utf-8", newline="") as f:
                f.write("From: Dong Ryo <colleague@example.com>\r\nTo: me@example.com\r\nSubject: =?utf-8?b?7ZqM7J2Y?=\r\n"
                        "Date: Thu, 05 Mar 2026 09:10:00 +0900\r\n\r\nbody\r\n")
            with open(os.path.join(src, "보낸 편지함", "b.eml"), "w", encoding="utf-8", newline="") as f:
                f.write("From: me@example.com\r\nTo: colleague@example.com\r\nSubject: RE: report\r\n"
                        "Date: Fri, 06 Mar 2026 15:20:00 +0900\r\n\r\nbody\r\n")
            with open(os.path.join(src, "c.ics"), "w", encoding="utf-8", newline="") as f:
                f.write("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u1\r\nDTSTART:20260302T100000\r\nDTEND:20260302T110000\r\n"
                        "RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:주간 회의\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
            with open(os.path.join(src, "d.msg"), "wb") as f:
                f.write(b"\xd0\xcf\x11\xe0")
            out_buf = io.StringIO()
            with mock.patch.object(sys, "argv", ["Import-MailCal.py", "--in", src, "--out-dir", out, "--from",
                                                 "2026-01-01", "--to", "2026-06-30"]), contextlib.redirect_stdout(out_buf):
                rc = imc.main()
            st = _status_of(out_buf.getvalue())
            self.assertEqual((rc, st["counts"]["mail_rows"], st["counts"]["cal_rows"], st["counts"]["msg"]), (0, 2, 3, 1))
            with open(os.path.join(out, "mail_import.csv"), encoding="utf-8-sig") as f:
                mail = list(csv.reader(f))[1:]
            boxes = sorted(r[0] for r in mail)
            self.assertEqual(boxes, ["inbox", "sent"])                # 보낸 편지함 폴더 = sent
            with open(os.path.join(out, "cal_import.csv"), encoding="utf-8-sig") as f:
                cal = list(csv.reader(f))[1:]
            self.assertEqual([r[0] for r in cal], ["2026-03-02 10:00", "2026-03-09 10:00", "2026-03-16 10:00"])
            self.assertTrue(os.path.isfile(os.path.join(src, "d.msg")))   # 원본은 그대로

    def test_rrule_exdate_and_byday(self):
        st = datetime(2026, 3, 2, 9, 0)
        got = imc.expand(st, st + timedelta(hours=1), "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4", {"20260304"})
        self.assertEqual([a.strftime("%m-%d") for a, _ in got], ["03-02", "03-09", "03-11"])   # 뺀 회차도 COUNT 에 센다


class CopilotMail(unittest.TestCase):
    def test_unable_ttl_two_distinct_days(self):
        d1, d2 = D("2026-10-01"), D("2026-10-03")
        st, conf = mvc.unable_note({"hits": [], "until": ""}, d1)
        self.assertFalse(conf)
        self.assertFalse(mvc.unable_active(st, d1))                   # 1회 → 생략 기록 없음
        st, conf = mvc.unable_note(st, d1)                            # 같은 날 두 번은 1회
        self.assertFalse(conf or mvc.unable_active(st, d1))
        st, conf = mvc.unable_note(st, d2)                            # 서로 다른 날 2회 → 기록
        self.assertTrue(conf and mvc.unable_active(st, d2))
        self.assertTrue(mvc.unable_active(st, d2 + timedelta(days=14)))
        self.assertFalse(mvc.unable_active(st, d2 + timedelta(days=15)))   # 15일 뒤 만료
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            p = os.path.join(tmp, "mail_copilot_unavailable.json")
            mvc.unable_save(p, st)
            self.assertEqual(mvc.unable_load(p)["until"], st["until"])
            with open(p, "w", encoding="utf-8") as f:                 # LM24 판(영구 플래그) = 1회 관측
                json.dump({"when": "2026-10-01 10:00", "note": "x"}, f)
            old = mvc.unable_load(p)
            self.assertEqual(old, {"hits": ["2026-10-01"], "until": ""})
            self.assertFalse(mvc.unable_active(old, d2))

    def test_ranges_chunks_and_merge(self):
        self.assertEqual(mvc.parse_ranges("2026-03-01:2026-03-10,2026-03-08~2026-03-20 2026-04-02"),
                         [("2026-03-01", "2026-03-20"), ("2026-04-02", "2026-04-02")])
        calls = []

        def one(kind, s0, s1, alt=False):
            calls.append((s0, s1))
            if s0 == "2026-03-01":
                return [], "empty"
            if s0 == "2026-03-08":
                return [], "other"
            return [["inbox", "2026-03-16 12:00", "동료", "새 행", "새 행", "to", "date"]], "table"
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            p = os.path.join(tmp, "mail_copilot.csv")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(mvc.MAIL_HDR + "\n")
                f.write("inbox,2026-02-10 12:00,A,옛 2월,옛 2월,to,date\n")
                f.write("inbox,2026-03-17 12:00,B,옛 3월,옛 3월,to,date\n")
            with contextlib.redirect_stdout(io.StringIO()):
                n, unable, fatal, chunks = mvc.collect_kind("mail", "", "", True, one_slice=one,
                                                            ranges=[("2026-03-01", "2026-03-20")], dst=p)
            self.assertEqual(calls, [("2026-03-01", "2026-03-07"), ("2026-03-08", "2026-03-14"),
                                     ("2026-03-15", "2026-03-20")])   # 7일 조각 · empty·other 로 멈추지 않는다
            self.assertEqual((n, unable, fatal), (1, False, False))
            self.assertEqual([c[2] for c in chunks], ["empty", "other", "table"])
            with open(p, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))[1:]
            self.assertEqual(sorted(r[3] for r in rows), ["새 행", "옛 2월"])   # 표를 받은 조각만 교체
            self.assertEqual({r[6] for r in rows}, {"date"})                     # 정밀도 표식 유지
            rg = mvc.chunk_ranges("mail", chunks)
            self.assertEqual({r["st"] for r in rg if r["from"] == "2026-03-15"}, {"partial"})

    def test_main_inproc_send_and_first_unable_not_recorded(self):
        sends = []

        def send(prompt):
            sends.append(prompt)
            return {"ok": True, "phase": "replied", "reply": "죄송하지만 메일을 조회할 수 없습니다."}
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp, \
                mock.patch.object(mvc, "_send", send), mock.patch.object(mvc, "OUT_DIR", tmp), \
                mock.patch.object(sys, "argv", ["Get-MailViaCopilot.py", "--ranges", "2026-03-02:2026-03-08", "--only",
                                                "mail", "--out-dir", tmp, "--tag", "copilot"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = mvc.main()
            st = _status_of(out.getvalue())
            self.assertEqual((rc, st["reason"]), (3, "R-UNABLE"))
            self.assertEqual(len(sends), 2)                           # 기본 화법 + 검색형 화법 1회 — 자식 프로세스 없음
            flag = mvc.unable_load(os.path.join(tmp, "mail_copilot_unavailable.json"))
            self.assertEqual(len(flag["hits"]), 1)
            self.assertEqual(flag["until"], "")                       # 1회 — 생략 기록 없음

    def test_blocked_is_not_failure(self):
        def one(kind, s0, s1, alt=False):
            return [], "blocked"
        with contextlib.redirect_stdout(io.StringIO()):
            n, unable, fatal, chunks = mvc.collect_kind("mail", "2026-03-01", "2026-03-28", True, one_slice=one,
                                                        dst=os.devnull)
        self.assertEqual((n, unable, fatal, len(chunks)), (0, False, False, 4))


if __name__ == "__main__":
    unittest.main()
