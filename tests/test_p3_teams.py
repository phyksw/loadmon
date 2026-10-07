# -*- coding: utf-8 -*-
r"""tests\test_p3_teams.py — WP3: 팀즈 웹 목록·스크롤 검증·증분(F-06·F-07·F-30·C-21·W1-05) · 창 읽기(C-18·C-19·C-20 — PS 결과) ·
Graph·Copilot 병합(W1-17·W1-13).

실제 Edge·Teams·네트워크를 쓰지 않는다 — tests\fakes\fake_teams.py(FakeTeams: Get-TeamsWeb 의 JS 머리 표식에 각본 응답 +
가짜 시계)와 주입한 왕복·Graph 함수로 돈다. 파일은 tempfile 폴더에만 쓴다(모듈 OUT_DIR 를 임시로 돌린다).
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
from datetime import date, datetime, timedelta
from unittest import mock

import _boot  # noqa: F401  — 경로 등록
import privacy  # noqa: E402
import teams_parse as tp  # noqa: E402

sys.path.insert(0, os.path.join(_boot.TESTS, "fakes"))
import fake_teams as ft  # noqa: E402

COL = os.path.join(_boot.ROOT, "collect")


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, os.path.join(COL, fn))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tw = _load("teams_web_t", "Get-TeamsWeb.py")
tw.log = lambda msg: None                      # 수집기 진행 줄은 시험 출력에 싣지 않는다(main 시험은 LMSTATUS 만 본다)
tgc = _load("teams_copilot_t", "Get-TeamsViaCopilot.py")
tgh = _load("teams_graph_t", "Get-TeamsChats.py")

TODAY = date(2026, 10, 7)                      # 수요일
D = date.fromisoformat


def _status_of(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    assert lines and lines[-1].startswith("LMSTATUS "), lines[-3:]
    return json.loads(lines[-1][len("LMSTATUS "):])


def _csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@contextlib.contextmanager
def _fake_time(br):
    with mock.patch.object(tw, "_mono", br.mono), mock.patch.object(tw, "_sleep", br.sleep):
        yield


def _collect(br, tmp, d0, d1, state=None, today=TODAY, **kw):
    run = tw.Run(d0, d1, today, deadline=kw.pop("deadline", None), **kw)
    store = tw.Store(os.path.join(tmp, "teams_web.csv"))
    st = state if state is not None else {}
    with _fake_time(br):
        rooms, end, how = tw.collect(br, run, st, store)
    return rooms, end, run, store, st


def _verdicts(rooms):
    return {r["name"]: r["verdict"] for r in rooms}


# ── 순수 함수 ─────────────────────────────────────────────────────────────────
class TeamsParse(unittest.TestCase):
    def test_key_of_date_and_pii(self):
        a = tp.key_of("2026-10-05", "09:10", "홍길동", "개발 협의", "자료 확인 부탁드립니다")
        b = tp.key_of("2026-10-06", "09:10", "홍길동", "개발 협의", "자료 확인 부탁드립니다")
        self.assertNotEqual(a, b)                                   # 같은 글이 다른 날 → 2행(C-21)
        raw = "견적 회신은 010-1234-5678 로 주시고 메일 someone@example.com 로 보내 주세요"
        clean = privacy.sanitize(raw, "summary")[0]
        self.assertNotEqual(raw, clean)                             # 개인정보가 실제로 가려지는 글
        k1 = tp.key_of("2026-10-05", "09:10", "홍길동", "개발 협의", raw)
        k2 = tp.key_of("2026-10-05", "09:10", "홍길동", "개발 협의", clean)
        self.assertEqual(k1, k2)                                    # 원문/정제 어느 쪽이든 같은 키(G1 뒤에도)
        self.assertEqual(tp.msg_hash("2026-10-05", "09:10", "홍길동", raw),
                         tp.msg_hash("2026-10-05", "09:10", "홍길동", clean))
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:   # 저장도 날짜가 다르면 2행
            st = tw.Store(os.path.join(tmp, "teams_web.csv"))
            row = {"from": "홍길동", "chat": "개발 협의", "kind": "msg", "summary": "자료 확인 부탁드립니다"}
            added, _ = st.add([dict(row, time="2026-10-05 09:10"), dict(row, time="2026-10-06 09:10"),
                               dict(row, time="2026-10-06 09:10", summary="자료 확인 부탁드립니다 ")])
            self.assertEqual(added, 2)

    def test_room_verdict_precedence(self):
        v = tp.room_verdict
        self.assertEqual(v({"gone", "overlap"}), "roomgone")
        self.assertEqual(v({"overlap", "budget"}), "incremental_ok")
        self.assertEqual(v({"reached_d0"}), "complete")
        self.assertEqual(v({"top_confirmed"}), "complete")
        self.assertEqual(v({"no_scroller"}), "cut_no_scroller")
        self.assertEqual(v({"budget"}), "cut_budget")
        self.assertEqual(v({"max_scroll"}), "cut_budget")
        self.assertEqual(v(set()), "cut_budget")

    def test_day_ranges(self):
        d0, d1 = D("2026-09-01"), D("2026-09-30")
        ok = {"verdict": "complete", "read_to": d0}
        rooms = [dict(ok, last=D("2026-09-28")), dict(ok, last=D("2026-09-20")), {"last": D("2026-09-15"),
                                                                               "verdict": "cut_budget", "read_to": None}]
        rg = tp.day_ranges(rooms, True, d0, d1)
        self.assertEqual(rg, [{"axis": "teams", "from": "2026-09-01", "to": "2026-09-15", "st": "partial"},
                              {"axis": "teams", "from": "2026-09-16", "to": "2026-09-30", "st": "ok"}])
        # 목록 끝을 못 봤어도 마지막 방이 d 보다 오래됐으면 ①은 성립 · 안 연 방(verdict None)은 ② 실패
        rooms2 = [dict(ok, last=D("2026-09-28")), {"last": D("2026-09-10"), "verdict": None, "read_to": None}]
        rg2 = tp.day_ranges(rooms2, False, d0, d1)
        self.assertEqual([(r["from"], r["st"]) for r in rg2], [("2026-09-01", "partial"), ("2026-09-11", "ok")])
        # 증분은 read_to(지난 확인 구간의 시작) 이후만 ok · 오늘(cap)은 partial · roomgone 은 ok 아님
        rooms3 = [{"last": D("2026-09-29"), "verdict": "incremental_ok", "read_to": D("2026-09-05")},
                  {"last": D("2026-09-03"), "verdict": "roomgone", "read_to": None}]
        rg3 = tp.day_ranges(rooms3, True, d0, d1, cap=D("2026-09-30"))
        self.assertEqual([(r["from"], r["to"], r["st"]) for r in rg3],
                         [("2026-09-01", "2026-09-04", "partial"), ("2026-09-05", "2026-09-29", "ok"),
                          ("2026-09-30", "2026-09-30", "partial")])

    def test_merge_keep_outside_and_union(self):
        old = [["2026-02-10 09:00", "A", "옛 2월"], ["2026-03-05 09:00", "B", "옛 3월"], ["2026-04-02 10:00", "C", "옛 4월"]]
        new = [["2026-03-07 11:00", "D", "새 3월"], ["2026-03-07 11:00", "D", "새 3월"]]
        got = tp.merge_keep_outside(old, new, "2026-03-01", "2026-03-31")
        self.assertEqual([r[2] for r in got], ["옛 2월", "새 3월", "옛 4월"])    # 기간 밖 옛 행 보존 · 기간 안은 교체
        u = tp.merge_union(old, new, lambda r: (r[0], r[1]))
        self.assertEqual([r[2] for r in u], ["옛 2월", "옛 3월", "새 3월", "옛 4월"])


# ── 팀즈 웹 수집(collect — 가짜 화면·가짜 시계) ──────────────────────────────────
class TeamsWebCollect(unittest.TestCase):
    d0, d1 = D("2026-09-01"), TODAY

    def test_list_120_rooms(self):
        rooms = []
        for i in range(120):
            day = TODAY - timedelta(days=1 + i // 10)
            rooms.append(ft.room(f"동료{i:03d}", [ft.msg(datetime(2026, 8, 20, 9, 0), f"동료{i:03d}", f"지난 달 안내 {i}"),
                                                ft.msg(datetime(day.year, day.month, day.day, 9, i % 60), f"동료{i:03d}",
                                                       f"주간 보고 {i}번 공유")], key=f"19:k{i}@thread.v2"))
        br = ft.FakeTeams(TODAY, rooms)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            got, end, run, store, st = _collect(br, tmp, self.d0, self.d1)
            self.assertEqual((len(got), end, run.c["rooms_listed"], run.c["list_end"]), (120, True, 120, True))
            self.assertEqual((run.c["opened"], run.c["complete"], run.c["rows_new"]), (120, 120, 120))
            self.assertEqual(len(_csv_rows(os.path.join(tmp, "teams_web.csv"))), 120)
            rg = tp.day_ranges(got, end, self.d0, self.d1, cap=TODAY)
            self.assertEqual({r["st"] for r in rg if r["to"] < TODAY.isoformat()}, {"ok"})
        capped = ft.FakeTeams(TODAY, rooms)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            got, end, run, _s, _st = _collect(capped, tmp, self.d0, self.d1, max_chats=40)
            self.assertEqual((len(got), end), (40, False))           # 상한 — 끝을 못 봤다

    def test_stuck_room_is_roomgone_and_no_rows(self):
        def mk(name, **fl):
            return ft.room(name, [ft.msg(datetime(2026, 8, 25, 9, 0), name + "씨", f"{name} 지난 안내"),
                                  ft.msg(datetime(2026, 10, 5, 10, 0), name + "씨", f"{name} 방의 업무 메시지")],
                           key="19:" + name, **fl)
        for flags in ({}, {"no_sel": True}):
            br = ft.FakeTeams(TODAY, [mk("가방"), mk("나방", stuck=True), mk("다방")], **flags)
            with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
                got, end, run, store, st = _collect(br, tmp, self.d0, self.d1)
                self.assertEqual(_verdicts(got), {"가방": "complete", "나방": "roomgone", "다방": "complete"}, flags)
                rows = _csv_rows(os.path.join(tmp, "teams_web.csv"))
                self.assertEqual(sorted(r["chat"] for r in rows), ["가방", "다방"])     # 앞 방 메시지를 나방으로 적지 않는다
                self.assertEqual(run.c["roomgone"], 1)
                self.assertNotIn("newest_read", st[tp.room_id("19:나방")])
                self.assertEqual(st[tp.room_id("19:나방")]["status"], "roomgone")

    def test_top_lazy_load_and_top_confirmed(self):
        lazy = ft.daily("지연방", self.d0 - timedelta(days=5), TODAY - timedelta(days=1), key="19:lazy", lazy=8)
        whole = ft.daily("짧은방", D("2026-09-10"), TODAY - timedelta(days=2), key="19:short")
        br = ft.FakeTeams(TODAY, [lazy, whole])
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            got, end, run, store, st = _collect(br, tmp, self.d0, self.d1)
            self.assertEqual(_verdicts(got), {"지연방": "complete", "짧은방": "complete"})
            self.assertGreaterEqual(run.c.get("top_loaded", 0), 1)  # 맨 위에서 기다리니 지난 메시지가 붙었다
            days = {r["time"][:10] for r in _csv_rows(os.path.join(tmp, "teams_web.csv")) if r["chat"] == "지연방"}
            self.assertIn("2026-09-01", days)                        # 늦게 붙은 기간 첫 날까지 읽었다
            self.assertNotIn("2026-08-31", days)                     # 기간 밖은 저장하지 않는다
            self.assertEqual(st[tp.room_id("19:short")]["oldest"], "0001-01-01")    # 맨 위 확인 = 방 처음까지
            self.assertEqual(st[tp.room_id("19:lazy")]["oldest"], self.d0.isoformat())

    def test_no_scroller_is_cut_and_refind(self):
        n = ft.daily("막힌방", D("2026-09-10"), TODAY - timedelta(days=1), key="19:ns", no_scroller=True)
        dp = ft.daily("찾은방", D("2026-08-25"), TODAY - timedelta(days=2), key="19:deep", deep=True)
        bk = ft.daily("오류방", D("2026-09-12"), TODAY - timedelta(days=3), key="19:broken", broken=True)
        br = ft.FakeTeams(TODAY, [n, dp, bk])
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            got, end, run, store, st = _collect(br, tmp, self.d0, self.d1)
            # 스크립트 오류(빈 응답)도 '맨 위'가 아니다 — 읽음으로 적지 않는다
            self.assertEqual(_verdicts(got), {"막힌방": "cut_no_scroller", "찾은방": "complete", "오류방": "cut_no_scroller"})
            self.assertGreaterEqual(run.c.get("scroll_refound", 0), 1)
            self.assertNotIn("newest_read", st[tp.room_id("19:ns")])  # '처음까지 읽음'이 아니다 — 커서 전진 없음
            rg = tp.day_ranges(got, end, self.d0, self.d1, cap=TODAY)
            self.assertEqual({r["st"] for r in rg if r["from"] <= (TODAY - timedelta(days=1)).isoformat()}, {"partial"})

    def test_unchanged_skip_rule(self):
        run = tw.Run(self.d0, self.d1, TODAY)
        last = D("2026-10-03")
        room = {"last": last, "preview": "p1"}
        st = {"newest_read": "h", "oldest": self.d0.isoformat(), "list_day": last.isoformat(), "list_prev": "p1",
              "read_day": "2026-10-05"}
        self.assertTrue(tw._unchanged(room, st, run))                # 마지막 활동 다음 날 이후에 확인 · 미리보기 같음
        self.assertFalse(tw._unchanged(room, dict(st, read_day=last.isoformat()), run))   # 같은 날 확인 — 그 뒤 메시지가 있을 수 있다
        self.assertFalse(tw._unchanged(dict(room, preview="p2"), st, run))
        self.assertFalse(tw._unchanged(room, dict(st, oldest="2026-09-15"), run))         # 확인 구간이 기간 시작을 못 덮음
        self.assertFalse(tw._unchanged(dict(room, last=TODAY), dict(st, list_day=TODAY.isoformat()), run))

    def test_author_inherit_and_mine(self):
        t = datetime(2026, 9, 30, 9, 0)
        msgs = [ft.msg(datetime(2026, 8, 20, 9, 0), "옛사람", "지난 달 이야기입니다"),
                ft.msg(t, "갑돌", "첫 번째 요청 드립니다"), ft.msg(t + timedelta(minutes=2), "갑돌", "이어서 두 번째 요청"),
                ft.msg(t + timedelta(minutes=5), "나", "확인했습니다 진행할게요", mine=True),
                ft.msg(t + timedelta(minutes=6), "을순", "을순의 의견입니다"),
                ft.msg(t + timedelta(minutes=7), "을순", "을순 덧붙임 메시지")]
        br = ft.FakeTeams(TODAY, [ft.room("묶음방", msgs, key="19:grp")])
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            _collect(br, tmp, self.d0, self.d1)
            rows = sorted(_csv_rows(os.path.join(tmp, "teams_web.csv")), key=lambda r: r["time"])
            self.assertEqual([(r["from"], r["kind"]) for r in rows],
                             [("갑돌", "msg"), ("갑돌", "msg"), ("나", "sent"), ("을순", "msg"), ("을순", "msg")])


# ── 팀즈 웹 main(LMSTATUS·커서 파일) ───────────────────────────────────────────
class TeamsWebMain(unittest.TestCase):
    def _main(self, br, tmp, d0, d1, cfg=None, extra=()):
        @contextlib.contextmanager
        def lock(cfg=None, timeout=600):
            yield "x"
        br.ca = types.SimpleNamespace(edge_lock=lock, EdgeBusy=RuntimeError)
        br.cfg = {}
        out = io.StringIO()
        with mock.patch.object(tw, "Browser", lambda: br), mock.patch.object(tw, "OUT_DIR", tmp), \
                mock.patch.object(tw, "_load_cfg", lambda: dict(cfg or {})), _fake_time(br), \
                mock.patch.object(sys, "argv", ["Get-TeamsWeb.py", "--from", d0.isoformat(), "--to", d1.isoformat(), *extra]), \
                mock.patch.dict(os.environ, {"LM_NO_BROWSER": ""}), contextlib.redirect_stdout(out):
            rc = tw.main()
        return rc, _status_of(out.getvalue())

    def test_no_scroller_rc3_websel(self):
        today = date.today()
        rooms = [ft.daily(f"막힌방{i}", today - timedelta(days=25), today - timedelta(days=1 + i), key=f"19:n{i}",
                          no_scroller=True) for i in range(2)]
        br = ft.FakeTeams(today, rooms)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            rc, st = self._main(br, tmp, today - timedelta(days=60), today)
            self.assertEqual((rc, st["rc"], st["src"]), (3, 3, "teams_web"))
            self.assertTrue(st["reason"].startswith("R-WEBSEL"), st["reason"])
            self.assertEqual(st["counts"]["cut_no_scroller"], 2)
            for k in ("rooms_listed", "list_end", "opened", "complete", "incremental_ok", "cut_budget", "cut_no_scroller",
                      "roomgone", "rows_new", "teams_present"):
                self.assertIn(k, st["counts"])
            self.assertTrue({r["st"] for r in st["ranges"]} <= {"partial"})
            with open(os.path.join(tmp, tw.STATE_NAME), encoding="utf-8") as f:
                cur = json.load(f)
            self.assertTrue(all(v["status"] == "cut_no_scroller" and "newest_read" not in v for v in cur["rooms"].values()))

    def test_budget_cut_keeps_earlier_rooms(self):
        today = date.today()
        rooms = [ft.daily(f"예산방{i}", today - timedelta(days=45), today - timedelta(days=1 + i), key=f"19:b{i}")
                 for i in range(6)]
        br = ft.FakeTeams(today, rooms)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            rc, st = self._main(br, tmp, today - timedelta(days=40), today, extra=("--budget", "6"))
            c = st["counts"]
            self.assertIn("R-TIMEOUT", st["reason"])
            self.assertGreaterEqual(c["complete"], 1)
            self.assertGreaterEqual(c["not_opened"], 1)
            chats = {r["chat"] for r in _csv_rows(os.path.join(tmp, "teams_web.csv"))}
            self.assertIn("예산방0", chats)                           # 앞 방은 방마다 저장됐다
            with open(os.path.join(tmp, tw.STATE_NAME), encoding="utf-8") as f:
                cur = json.load(f)["rooms"]
            self.assertEqual(cur[tp.room_id("19:b0")]["status"], "complete")
            # 다음 실행은 잘린 방(cut)을 먼저 연다
            first = [r for r in rooms if cur.get(tp.room_id(r["key"]), {}).get("status") in tw.CUT_STATES]
            if first:
                br2 = ft.FakeTeams(today, rooms)
                opened = []
                real = br2._open

                def spy(js):
                    r = real(js)
                    if r == "ok":
                        opened.append(br2.rooms[br2.target]["name"])
                    return r
                br2._open = spy
                self._main(br2, tmp, today - timedelta(days=40), today)
                self.assertEqual(opened[0], first[0]["name"])

    def test_second_run_incremental_then_epoch_reset(self):
        today = date.today()
        rooms = [ft.daily(f"증분방{i}", today - timedelta(days=33), today - timedelta(days=1 + i), key=f"19:i{i}")
                 for i in range(5)]
        br = ft.FakeTeams(today, rooms)
        d0 = today - timedelta(days=30)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            rc1, st1 = self._main(br, tmp, d0, today)
            c1 = st1["counts"]
            self.assertEqual((rc1, c1["opened"], c1["complete"]), (0, 5, 5))
            yday = (today - timedelta(days=1)).isoformat()
            self.assertEqual({r["st"] for r in st1["ranges"] if r["to"] <= yday}, {"ok"})
            self.assertEqual([r["st"] for r in st1["ranges"] if r["to"] == today.isoformat()], ["partial"])
            n_scroll1 = br.calls["scroll_up"]
            # 새 메시지 하나(오늘) — 그 방만 열고 지난 newest_read 와 겹치면 멈춘다
            rooms[0]["msgs"].append(ft.msg(datetime(today.year, today.month, today.day, 8, 1), "증분방0님", "오늘 새로 온 요청"))
            rc2, st2 = self._main(br, tmp, d0, today)
            c2 = st2["counts"]
            self.assertEqual((rc2, c2["opened"], c2["incremental_ok"], c2["unchanged_skip"], c2["rows_new"]), (0, 1, 5, 4, 1))
            self.assertLess(c2["opened"], c1["opened"])               # 열기 수 감소
            self.assertEqual(br.calls["scroll_up"], n_scroll1)          # 되감기 없음 — 첫 화면에서 겹침
            self.assertEqual({r["st"] for r in st2["ranges"] if r["to"] <= yday}, {"ok"})
            # cursorEpoch 가 바뀌면 커서를 버리고 처음부터
            rc3, st3 = self._main(br, tmp, d0, today, cfg={"collect": {"cursorEpoch": 2}})
            c3 = st3["counts"]
            self.assertEqual((c3.get("cursor_reset"), c3["opened"], c3["incremental_ok"], c3["complete"]), (1, 5, 0, 5))
            self.assertEqual(rc3, 4)                                   # 이미 다 있는 행 — 새 행 0
            with open(os.path.join(tmp, tw.STATE_NAME), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["ver"], tw.COLLECTOR_VER + "|2")

    def test_login_keeps_tab(self):
        br = ft.FakeTeams(date.today(), [], login=True)
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            rc, st = self._main(br, tmp, date.today() - timedelta(days=10), date.today())
        self.assertEqual((rc, st["reason"], br.closed), (2, "R-LOGIN", "kept"))

    def test_teams_url_and_hosts(self):
        self.assertEqual(tw.TEAMS_URL, "https://teams.microsoft.com/")
        self.assertIn("teams.cloud.microsoft", tw.HOSTS)
        self.assertNotIn("teams.live.com", tw.HOSTS)


# ── Copilot 팀즈 ──────────────────────────────────────────────────────────────
class TeamsCopilot(unittest.TestCase):
    def test_collect_ranges_merge_keep_outside(self):
        calls = []

        def one(s0, s1, alt=False):
            calls.append((s0, s1))
            if s0.startswith("2026-03"):
                return [["2026-03-07 11:00", "동료", "개발", "msg", "미응답", "새 3월 메시지"]], "table"
            return [], "empty"
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            p = os.path.join(tmp, "teams_copilot.csv")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(tgc.HDR + "\n")
                f.write("2026-02-10 09:00,A,방,msg,미응답,옛 2월\n2026-03-05 09:00,B,방,msg,미응답,옛 3월\n"
                        "2026-04-02 10:00,C,방,msg,미응답,옛 4월\n")
            with contextlib.redirect_stdout(io.StringIO()):
                n, unable, fatal, chunks = tgc.collect_ranges([("2026-03-01", "2026-03-10"), ("2026-04-01", "2026-04-05")],
                                                              one_slice=one, dst=p)
            self.assertEqual((n, unable, fatal), (1, False, False))
            self.assertEqual([c[2] for c in chunks], ["table", "empty"])
            with open(p, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))[1:]
            self.assertEqual([r[5] for r in rows], ["옛 2월", "새 3월 메시지", "옛 4월"])   # 표 받은 조각만 교체 · 'empty' 조각은 둔다
            self.assertEqual(tgc.chunk_ranges(chunks), [
                {"axis": "teams", "from": "2026-03-01", "to": "2026-03-10", "st": "partial"},
                {"axis": "teams", "from": "2026-04-01", "to": "2026-04-05", "st": "unverified"}])

    def test_main_inproc_and_unable_two_days_ttl(self):
        with open(os.path.join(COL, "Get-TeamsViaCopilot.py"), encoding="utf-8") as f:
            self.assertNotIn("subprocess", f.read())                  # 조각마다 자식 프로세스를 띄우지 않는다
        sends = []

        def send(prompt):
            sends.append(prompt)
            return {"ok": True, "phase": "replied", "reply": "현재 연결된 Microsoft Teams 데이터 조회 도구가 없어 조회할 수 없습니다."}
        today = date.today()
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            def run_main():
                out = io.StringIO()
                with mock.patch.object(tgc, "_send", send), mock.patch.object(tgc, "OUT_DIR", tmp), \
                        mock.patch.object(sys, "argv", ["Get-TeamsViaCopilot.py", "--ranges", "2026-03-02:2026-03-08"]), \
                        contextlib.redirect_stdout(out):
                    rc = tgc.main()
                return rc, _status_of(out.getvalue())
            rc, st = run_main()
            self.assertEqual((rc, st["reason"], st["src"], len(sends)), (3, "R-UNABLE", "teams_copilot", 2))
            flag = os.path.join(tmp, tgc.UNAVAILABLE_NAME)
            mvc = tgc._mvc()
            self.assertEqual(mvc.unable_load(flag)["until"], "")        # 1회 — 다음 실행을 막지 않는다
            rc, st = run_main()
            self.assertEqual(len(sends), 4)                             # 같은 날 두 번째도 묻는다(같은 날은 1회로 센다)
            with open(flag, "w", encoding="utf-8") as f:                # 다른 날 관측 하나를 더한다
                json.dump({"hits": [(today - timedelta(days=3)).isoformat()], "until": ""}, f)
            rc, st = run_main()
            self.assertTrue(mvc.unable_load(flag)["until"] >= (today + timedelta(days=13)).isoformat())
            n = len(sends)
            rc, st = run_main()
            self.assertEqual((rc, st["reason"], len(sends)), (3, "R-UNABLE", n))   # TTL 안 — 왕복 생략
            with open(flag, "w", encoding="utf-8") as f:                # LM24 판(영구 플래그)은 1회 관측 — 막지 않는다
                json.dump({"when": "2026-08-21 10:00", "note": "x"}, f)
            run_main()
            self.assertEqual(len(sends), n + 2)


# ── Graph ─────────────────────────────────────────────────────────────────────
class TeamsGraph(unittest.TestCase):
    def test_complete_run_ok_ranges_and_keep_outside(self):
        def get_json(url, token, timeout=30):
            if url.endswith("/me"):
                return {"id": "me1", "displayName": "나"}
            if "/me/chats" in url:
                return {"value": [{"id": "19:c1@thread.v2", "topic": "개발 협의",
                                   "lastMessagePreview": {"createdDateTime": "2026-09-20T03:00:00Z"}}]}
            return {"value": [{"createdDateTime": "2026-09-20T03:00:00Z", "body": {"content": "<p>검토 요청드립니다</p>"},
                               "from": {"user": {"id": "u2", "displayName": "동료"}}},
                              {"createdDateTime": "2026-09-15T03:00:00Z", "body": {"content": "확인했습니다"},
                               "from": {"user": {"id": "me1", "displayName": "나"}}},
                              {"createdDateTime": "2026-08-20T03:00:00Z", "body": {"content": "기간 전"},
                               "from": {"user": {"id": "u2", "displayName": "동료"}}}]}
        with tempfile.TemporaryDirectory(prefix="lm28_t_") as tmp:
            p = os.path.join(tmp, "teams_chats.csv")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(tgh.HDR + "\n2026-01-05 09:00,A,옛 1월,미응답,방,msg\n2026-09-03 09:00,B,옛 9월,미응답,방,msg\n")
            out = io.StringIO()
            with mock.patch.object(tgh, "acquire_token", lambda interactive=True: ("tok", None)), \
                    mock.patch.object(tgh, "get_json", get_json), mock.patch.object(tgh, "OUT_DIR", tmp), \
                    mock.patch.object(tgh, "graph_cfg", lambda: ("cid", "organizations", ["Chat.Read"])), \
                    mock.patch.object(sys, "argv", ["Get-TeamsChats.py", "--from", "2026-09-01", "--to", "2026-09-30",
                                                    "--non-interactive"]), contextlib.redirect_stdout(out):
                rc = tgh.main()
            st = _status_of(out.getvalue())
            self.assertEqual((rc, st["rc"], st["src"], st["counts"]["complete"]), (0, 0, "teams_graph", True))
            self.assertEqual(st["ranges"], [{"axis": "teams", "from": "2026-09-01", "to": "2026-09-30", "st": "ok"}])
            with open(p, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))[1:]
            sums = [r[2] for r in rows]
            self.assertIn("옛 1월", sums)                               # 기간 밖 옛 행 보존(W1-17)
            self.assertNotIn("옛 9월", sums)                            # 완주 — 기간 안은 이번 결과로 교체
            self.assertIn("검토 요청드립니다", sums)
        self.assertEqual({r["st"] for r in tgh.graph_ranges("2026-09-01", "2026-09-30", False)}, {"partial"})


# ── 창 읽기(PowerShell — run_tests --ps) ───────────────────────────────────────
class TeamsWindowPs(unittest.TestCase):
    def test_window_inject_undated_inproc(self):
        r = _boot.ps_result("TeamsWindow")
        if r is None:
            self.skipTest("--ps 로 돌지 않음")
        self.assertNotIn("error", r, r.get("error") if isinstance(r, dict) else r)
        self.assertEqual((r["r1_targets"], r["r1_excluded"], r["r1_personal"], r["r1_iconic"]), (2, 2, 1, 1))
        self.assertEqual((r["r1_rc"], r["r1_rows_new"], r["r1_undated"]), (0, 3, 1))
        self.assertEqual((r["r1_retry_reads"], r["r1_retry_gain"]), (2, 1))      # 요소 20개 미만 → 1번 다시 읽기
        self.assertTrue(r["r1_present"])
        self.assertEqual(r["r1_ranges"], "teams:2026-10-05~2026-10-06:partial")
        self.assertEqual((r["csv_rows"], r["csv_has_undated"], r["csv_has_free"]), (3, False, False))
        self.assertEqual((r["undated_rows"], r["undated_has"], r["undated_rows_again"]), (1, True, 1))
        st = json.loads(r["status"][len("LMSTATUS "):])
        self.assertEqual((st["src"], st["rc"], st["counts"]["targets"]), ("teams_window", 0, 2))
        self.assertEqual((r["r1b_rc"], r["r1b_rows_new"]), (4, 0))
        self.assertEqual((r["r2_rc"], r["r2_reason"], r["r2_cause"]), (3, "R-UIAEMPTY", "iconic"))
        self.assertEqual((r["r3_rc"], r["r3_reason"], r["r3_cause"]), (1, "R-NOTEAMS", "no_process"))
        self.assertEqual((r["inproc_rows"], r["spawned"], r["spawn_calls"]), (3, 0, 0))
        self.assertEqual(r["win32_error"], "")
        self.assertGreater(r["win32_count"], 0)                      # Add-Type 없이 user32 최상위 창 열거
        ds = json.loads(r["direct_status"][len("LMSTATUS "):])         # 직접 실행 가드 — 본체가 돌고 종료 코드 = rc
        self.assertEqual((r["direct_rc"], ds["rc"], ds["reason"], ds["src"]), (1, 1, "R-ARGS", "teams_window"))


if __name__ == "__main__":
    unittest.main()
