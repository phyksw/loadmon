# -*- coding: utf-8 -*-
"""WP-26 Get-TeamsWeb.py(teams.web) 시험 — 실물 정제·저장 지점(WP-11)과 합성 화면 응답(LM_TEAMSWEB_FAKE)만.

CT-5(가상 목록 60방) · CT-6(날짜 포함 키 — 매일 같은 시각 정형 메시지가 뭉개지지 않음) · CT-7(재렌더 gone → 그 방만
R-ROOMGONE) · CT-12(로그인 → rc 2 + R-LOGIN) · CT-16(예산 → partial + R-BUDGET, 체크포인트로 이어 읽기) · R-LISTVIRT ·
R-CAP(--max-chats) · R-WEBSEL · X-140(--no-channels · --no-activity · --force) · X-023(체크포인트 = raw_cursor 의
teams.web.rooms{chat_key}) · C7(unknown 격리 · 작성자 상속 · is_me null) · T-07(store·감사 카나리아 0)."""
import json
import re
import unittest
from datetime import UTC, date, datetime, timedelta

from lm27.bridge.clock import VirtualClock
from lm27.privacy import context as C
from lm27.privacy.sanitize import sanitize
from tests.fixtures.canary import canaries, canary_ctx, find_canaries
from tests.fixtures.synth import inject, month
from tests.fixtures.wp26 import webkit as K

R_ = "R-"
D = date(2026, 9, 21)
RANGE = ["--from", "2026-09-01", "--to", "2026-09-30"]


def _path_gap() -> bool:
    return "abc" in sanitize(r"C:\Users\abc\Documents\a.xlsx / b").text


def room_msgs(n_days: int = 3, *, start: date = D, mid_prefix: str = "") -> list:
    """방 하나의 화면 한 장: 날마다 구분선 + 김철수·홍길동 메시지(분 단위)."""
    items = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        items += [K.tw_sep(d), K.tw_msg(K.KIM, f"과제A 도면 검토 부탁드립니다 {i}", h=9, m=10, d=d,
                                         mid=f"{mid_prefix}{1757000000000 + i * 10}" if mid_prefix else ""),
                  K.tw_msg(K.ME, f"넵 확인했습니다 {i}", h=9, m=20, d=d,
                           mid=f"{mid_prefix}{1757000000001 + i * 10}" if mid_prefix else "")]
    return items


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def run_tw(self, fake, *extra, **kw):
        return K.run_tw(self.sb, [*RANGE, *extra], fake=fake, **kw)

    def rows(self):
        return self.sb.rows("teams", "teams.web")


class ListTest(_Base):

    def test_ct5_virtual_list_60_rooms(self):
        rooms = [K.tw_room(i, K.tid(100 + i, "group"), f"과제A 방 {i}") for i in range(60)]
        pages = [{"how": "[role=treeitem]", "items": rooms[a:b]} for a, b in ((0, 30), (20, 50), (40, 60))]
        msgs = {i: [{"how": "x", "items": [K.tw_sep(D), K.tw_msg(K.KIM, f"방 {i} 메시지", d=D)]}] for i in range(60)}
        fake = K.tw_fake(rooms, msgs)
        fake["chats"] = pages
        rc, st, err = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0, err)
        self.assertEqual((st["counts"]["chats_listed"], st["counts"]["rooms_done"]), (60, 60))   # 상한 40 재현 안 됨
        self.assertNotIn(R_ + "LISTVIRT", st["reasons"])
        self.assertEqual(len(self.rows()), 60)
        self.assertEqual(len(self.sb.cursor("teams.web")["rooms"]), 60)

    def test_listvirt_when_list_does_not_end(self):
        rooms = [K.tw_room(i, K.tid(200 + i), f"방 {i}") for i in range(4)]
        fake = K.tw_fake(rooms, {i: [{"items": [K.tw_sep(D), K.tw_msg(K.KIM, "x", d=D)]}] for i in range(4)},
                         chats_end=False)
        fake["chats"] = [{"how": "[role=treeitem]", "items": rooms[:2]}, {"how": "[role=treeitem]", "items": rooms[2:]}]
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0)
        self.assertTrue(st["partial"])
        self.assertIn(R_ + "LISTVIRT", st["reasons"])
        self.assertEqual(st["counts"]["rooms_done"], 4)

    def test_websel_when_chat_list_not_recognized(self):
        fake = {"login": False, "chats": {"how": "", "n": 0, "items": []}, "msgs": {}}
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "WEBSEL"]))
        fake2 = {"login": False, "chats": {"how": "[role=treeitem]", "n": 0, "items": []}, "msgs": {}}
        rc, st, _ = self.run_tw(fake2, "--no-channels", "--no-activity")
        self.assertEqual((rc, st["reasons"]), (1, []))                                  # 목록은 알아봤는데 대화 0

    def test_max_chats_cap_and_channels_activity(self):
        rooms = [K.tw_room(i, K.tid(300 + i, "group"), f"방 {i}") for i in range(4)]
        msgs = {i: [{"items": [K.tw_sep(D), K.tw_msg(K.KIM, f"m{i}", d=D)]}] for i in range(4)}
        chan_tid, act_tid = K.tid(399, "channel"), K.tid(398, "channel")
        msgs["ch0"] = [{"items": [K.tw_sep(D), K.tw_msg(K.PEER, "채널 공지입니다", d=D)]}]
        msgs["a0"] = [{"items": [K.tw_sep(D), K.tw_msg(K.KIM, "@홍길동 확인 부탁드립니다", d=D, mid="1757100000000")]}]
        fake = K.tw_fake(rooms, msgs,
                         channels={"how": "[role=treeitem]", "items": [{"idx": "ch0", "tid": chan_tid, "label": "양산 채널"}]},
                         activity={"how": "[role=listitem]",
                                   "items": [{"idx": "a0", "tid": act_tid, "mid": "1757100000000", "mention": True},
                                             {"idx": 1, "tid": rooms[1]["tid"], "mid": "", "mention": False}]})
        rc, st, _ = self.run_tw(fake)
        self.assertEqual(rc, 0)
        self.assertEqual((st["counts"]["rooms_listed"], st["counts"]["activity_rooms"]), (6, 1))
        rows = {r["body_masked"]: r for r in self.rows()}
        self.assertEqual(rows["채널 공지입니다"]["chat_type"], "channel")
        self.assertTrue(rows["@[나] 확인 부탁드립니다"]["flags"]["mentions_me"])
        sb2 = K.Sandbox()
        self.addCleanup(sb2.cleanup)
        rc, st, _ = K.run_tw(sb2, [*RANGE, "--no-channels", "--no-activity", "--max-chats", "2"], fake=fake)
        self.assertEqual(rc, 0)
        self.assertTrue(st["cap_hit"] and st["partial"])
        self.assertIn(R_ + "CAP", st["reasons"])
        self.assertEqual((st["counts"]["rooms_listed"], st["counts"]["rooms_capped"]), (4, 2))
        self.assertEqual({r["body_masked"] for r in sb2.rows("teams", "teams.web")}, {"m0", "m1"})
        self.assertNotIn("channels_listed", st["counts"])
        self.assertNotIn("activity_listed", st["counts"])


class MessageTest(_Base):

    def test_ct6_same_time_daily_messages_keep_dates(self):
        items = []
        for i in range(3):
            items += [K.tw_sep(D + timedelta(days=i)), K.tw_msg(K.KIM, "넵 확인했습니다", h=9, m=0)]
        fake = K.tw_fake([K.tw_room(0, K.tid(1, "group"), "과제A 설계")],
                         {0: [{"items": items}, {"items": items[:2]}]})            # 두 회차가 겹쳐도 한 번만
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["msg_key"] for r in rows}), 3)
        self.assertEqual(sorted(r["ts_utc"] for r in rows),
                         ["2026-09-21T00:00:00Z", "2026-09-22T00:00:00Z", "2026-09-23T00:00:00Z"])

    def test_direction_inheritance_types_titles(self):
        one = [K.tw_sep(D), K.tw_msg(K.KIM, "회의 자료 보내 주세요", h=9), K.tw_msg(K.ME, "보내 드렸습니다", h=10),
               {"t": "msg", "ts": "오전 10:05", "iso": [], "titles": [], "body": "첨부 확인 바랍니다",
                "texts": ["첨부 확인 바랍니다"]},
               K.tw_msg("나", "구조로 본 내 말풍선", h=11, me=True)]
        grp = [{"t": "msg", "ts": "오전 9:00", "iso": [], "titles": [], "body": "회의실 예약 공지", "texts": ["회의실 예약 공지"]},
               K.tw_sep(D), K.tw_msg(K.PEER, "과제A 회의록 공유", h=9)]
        fake = K.tw_fake([K.tw_room(0, K.tid(5, "one"), K.KIM), K.tw_room(1, K.tid(6, "group"), "과제A 설계")],
                         {0: [{"items": one}], 1: [{"items": grp, "chat": "과제A 설계"}]})
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0)
        rows = {r["body_masked"]: r for r in self.rows()}
        a = rows["회의 자료 보내 주세요"]
        self.assertEqual((a["direction"], a["chat_type"], a["n_participants"], a["confidence"]), ("received", "1:1", 2, 0.8))
        self.assertNotIn("chat_title_masked", a)                                        # 1:1 방 이름(= 상대 이름) 미전달
        b = rows["보내 드렸습니다"]
        self.assertEqual((b["direction"], b["author_key"]), ("sent", "self"))
        self.assertTrue(b["counterpart_keys"])                                          # 1:1 상대가 참여자로
        c = rows["첨부 확인 바랍니다"]
        self.assertEqual((c["direction"], c["confidence"], c["flags"].get("author_inherited")), ("sent", 0.3, True))
        self.assertEqual(rows["구조로 본 내 말풍선"]["direction"], "sent")
        u = rows["회의실 예약 공지"]
        self.assertEqual((u["direction"], u["ts_precision"]), ("unknown", "unknown"))   # 수신 단정 금지 · 날짜 미상 격리
        self.assertEqual(u["ts_utc"], "2026-09-30T15:00:00Z")                           # 수집일 00:00 로컬(C7)
        g = rows["[과제:P-0001] 회의록 공유"]
        self.assertEqual((g["chat_type"], g["chat_title_masked"]), ("group", "[과제:P-0001] 설계"))

    def test_unknown_once_and_out_of_range(self):
        items = [{"t": "msg", "author": K.KIM, "ts": "오전 9:00", "iso": [], "titles": [], "body": "날짜 미상 메시지",
                  "texts": [K.KIM]},
                 K.tw_sep(date(2026, 8, 31)), K.tw_msg(K.KIM, "기간 밖", h=9),
                 K.tw_sep(D), K.tw_msg(K.KIM, "기간 안", h=9)]
        fake = K.tw_fake([K.tw_room(0, K.tid(7), "방")], {0: [{"items": items}]})
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0)
        self.assertEqual({r["body_masked"] for r in self.rows()}, {"날짜 미상 메시지", "기간 안"})
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual((rc, st["n"]), (4, 0))
        self.assertEqual(len(self.rows()), 2)                                           # 날짜 미상 행을 다시 쓰지 않는다
        self.assertEqual(st["counts"]["unknown_skipped"], 1)


class CheckpointTest(_Base):

    def test_x023_checkpoint_incremental_and_force(self):
        room = K.tw_room(0, K.tid(11, "group"), "과제A 설계")
        rng = ["--from", "2026-09-01", "--to", "2026-10-01", "--no-channels", "--no-activity"]
        today = [{"t": "sep", "text": "오늘"}, K.tw_msg(K.KIM, "아침 메시지", h=8, m=0)]
        fake = K.tw_fake([room], {0: [{"items": room_msgs(3) + today}]})
        rc, st, _ = K.run_tw(self.sb, rng, fake=fake)                                    # 10/1 09:00 KST
        self.assertEqual((rc, st["n"]), (0, 7))
        cur = self.sb.cursor("teams.web")
        (ck, cp), = cur["rooms"].items()
        self.assertRegex(ck, r"^h[0-9a-f]{16}$")                                        # 원 대화 ID 가 아니라 chat_key
        self.assertNotIn(room["tid"], json.dumps(cur))
        self.assertEqual((cp["oldest_done"], cp["newest_done"]), ("2026-09-01", "2026-10-01"))
        self.assertRegex(cp["last_msg_key"], r"^m[0-9a-f]{24}$")
        # 그날 오후에 새 메시지 하나 → 그것만 새로(표지까지의 오늘 메시지는 다시 쓰지 않는다)
        later = K.NOW + timedelta(hours=5)
        fake2 = K.tw_fake([room], {0: [{"items": room_msgs(3) + today + [K.tw_msg(K.ME, "오후 회신", h=13, m=0)]}]})
        rc, st, _ = K.run_tw(self.sb, rng, fake=fake2, now=later)
        self.assertEqual((rc, st["n"], st["counts"]["reread"], st["counts"]["done_region"]), (0, 1, 1, 6))
        self.assertEqual(len(self.rows()), 8)
        rc, st, _ = K.run_tw(self.sb, rng, fake=fake2, now=later)
        self.assertEqual((rc, st["n"]), (4, 0))
        rc, st, _ = K.run_tw(self.sb, [*rng, "--force"], fake=fake2, now=later)
        self.assertEqual((rc, st["n"]), (0, 8))                                         # --force = 체크포인트 무시
        self.assertEqual(len({r["id"] for r in self.rows()}), 8)                         # 다시 써도 id 는 같다

    def _paged_room(self):
        """한 방의 화면 세 장(읽는 순서 = 최신 먼저): 9/25~27 · 9/20~24 · 9/10~19(날마다 메시지 하나)."""
        def page(a, b):
            items = []
            for k in range((b - a).days + 1):
                d = a + timedelta(days=k)
                items += [K.tw_sep(d), K.tw_msg(K.KIM, f"{d.isoformat()} 진행 공유", h=10, d=d, iso=True,
                                                mid=str(1758000000000 + d.toordinal()))]
            return {"items": items}
        pages = [page(date(2026, 9, 25), date(2026, 9, 27)), page(date(2026, 9, 20), date(2026, 9, 24)),
                 page(date(2026, 9, 10), date(2026, 9, 19))]
        return K.tw_fake([K.tw_room(0, K.tid(70, "group"), "과제A 설계")], {0: pages})

    def test_checkpoint_skips_done_region_then_reads_older(self):
        fake = self._paged_room()
        rc, st, _ = K.run_tw(self.sb, ["--from", "2026-09-20", "--to", "2026-09-30", "--no-channels", "--no-activity"],
                             fake=fake)
        self.assertEqual((rc, st["n"]), (0, 8))                                         # 9/20~27
        (cp,) = self.sb.cursor("teams.web")["rooms"].values()
        self.assertEqual((cp["oldest_done"], cp["newest_done"]), ("2026-09-20", "2026-09-30"))
        rc, st, _ = K.run_tw(self.sb, ["--from", "2026-09-01", "--to", "2026-09-30", "--no-channels", "--no-activity"],
                             fake=fake)
        self.assertEqual((rc, st["n"], st["counts"]["done_region"], st["counts"]["skip_scrolls"]), (0, 10, 8, 2))
        (cp,) = self.sb.cursor("teams.web")["rooms"].values()
        self.assertEqual((cp["oldest_done"], cp["newest_done"]), ("2026-09-01", "2026-09-30"))
        self.assertEqual(len(self.rows()), 18)
        self.assertEqual(len({r["msg_key"] for r in self.rows()}), 18)

    def test_max_scroll_cut_keeps_contiguous_checkpoint(self):
        self.sb.cfg = self.sb.cfg.derive({"teams.web.maxScroll": 1})
        rc, st, _ = self.run_tw(self._paged_room(), "--no-channels", "--no-activity")
        self.assertEqual((rc, st["n"], st["counts"]["rooms_cut_maxscroll"]), (0, 8, 1))
        (cp,) = self.sb.cursor("teams.web")["rooms"].values()
        self.assertEqual((cp["oldest_done"], cp["newest_done"]), ("2026-09-21", "2026-09-30"))   # 끊긴 날(9/20)은 빼고
        rc, st, _ = self.run_tw(self._paged_room(), "--no-channels", "--no-activity")
        self.assertEqual(st["counts"]["skip_scrolls"], 1)                               # 읽은 구간은 세지 않고 건너
        self.assertEqual(st["n"], 11)                                                   # 9/10~9/19 + 경계 하루 9/20(같은 id)
        (cp,) = self.sb.cursor("teams.web")["rooms"].values()
        self.assertEqual(cp["oldest_done"], "2026-09-11")                               # 또 끊김 — 처음에 닿지 않아 보수적으로

    def test_ct16_budget_partial_then_resume(self):
        rooms = [K.tw_room(i, K.tid(20 + i, "group"), f"방 {i}") for i in range(5)]
        fake = K.tw_fake(rooms, {i: [{"items": [K.tw_sep(D), K.tw_msg(K.KIM, f"m{i}", d=D)]}] for i in range(5)})
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity", "--budget-sec", "55", cost=10.0,
                                clock=VirtualClock())
        self.assertEqual(rc, 0)
        self.assertTrue(st["partial"] and st["budget_hit"])
        self.assertIn(R_ + "BUDGET", st["reasons"])
        self.assertEqual((st["counts"]["rooms_done"], st["counts"]["rooms_deferred"]), (2, 3))
        self.assertEqual(len(self.sb.cursor("teams.web")["rooms"]), 2)
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity", cost=10.0, clock=VirtualClock())
        self.assertEqual((rc, st["n"], st["partial"]), (0, 3, False))                   # 남은 3방만 새로
        self.assertEqual(sorted(r["body_masked"] for r in self.rows()), ["m0", "m1", "m2", "m3", "m4"])

    def test_ct7_gone_room_only(self):
        rooms = [K.tw_room(i, K.tid(30 + i), f"방 {i}") for i in range(3)]
        rooms[1]["gone"] = True
        fake = K.tw_fake(rooms, {i: [{"items": [K.tw_sep(D), K.tw_msg(K.KIM, f"m{i}", d=D)]}] for i in range(3)})
        rc, st, _ = self.run_tw(fake, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0)
        self.assertTrue(st["partial"])
        self.assertIn(R_ + "ROOMGONE", st["reasons"])
        self.assertEqual(st["counts"]["rooms_gone"], 1)
        self.assertEqual(sorted(r["body_masked"] for r in self.rows()), ["m0", "m2"])
        self.assertEqual(len(self.sb.cursor("teams.web")["rooms"]), 2)                  # 못 찾은 방은 다음 실행이 다시

    def test_ct12_login_rc2(self):
        rc, st, _ = self.run_tw({"login": True})
        self.assertEqual((rc, st["reasons"], st["partial"]), (2, [R_ + "LOGIN"], False))
        self.assertFalse(self.sb.paths.store_root().exists())
        rc, st, _ = self.run_tw({"login": "ca"})
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "CA"]))

    def test_synth_month_inject_format(self):
        plan = month.plan_month(2026, 9)
        rc, st, _ = K.run_tw(self.sb, [*RANGE], fake=inject.teamsweb_fake(plan), now=plan.as_of)
        self.assertEqual(rc, 0)
        rows = self.rows()
        self.assertEqual(len(rows), len(plan.chats))
        self.assertEqual({r["ts_precision"] for r in rows}, {"exact"})
        self.assertEqual(len({r["msg_key"] for r in rows}), len(rows))
        self.assertEqual(len(self.sb.cursor("teams.web")["rooms"]), len(plan.rooms))
        self.assertEqual(st["counts"]["chats_listed"], len(plan.rooms))
        self.assertTrue(all(re.fullmatch(r"h[0-9a-f]{16}", r["chat_key"]) for r in rows))

    def test_status_line_c1_shape(self):
        rc, st, err = self.run_tw(K.tw_fake([K.tw_room(0, K.tid(40), "방")],
                                            {0: [{"items": [K.tw_sep(D), K.tw_msg(K.KIM, "x", d=D)]}]}))
        self.assertEqual(rc, 0)
        for k, t in (("schema", str), ("src", str), ("rc", int), ("reasons", list), ("partial", bool), ("cap_hit", bool),
                     ("budget_hit", bool), ("n", int), ("counts", dict)):
            self.assertIsInstance(st[k], t, k)
        self.assertEqual(st["schema"], "lm27.collector_status/1")
        self.assertNotIn("_result", err)
        last = [x for x in err.splitlines() if x.strip()][-1]
        self.assertTrue(last.startswith('{"_status":'))


class CanaryTest(_Base):

    def test_t07_store_and_audit(self):
        cs = [c for c in canaries(groups=["pii", "ctx"], weak=False) if c.sentence]
        cx = canary_ctx(cs)
        reg = {"internal_domains": ["corp.example"], "customers": cx["customers"], "projects": cx["projects"]}
        local = {"person_dir": {"format": C.PERSONDIR_FORMAT,
                                "people": {"w" + v: {"names": [n]} for n, v in cx["persons"].items()}}}
        api = self.sb.api(registry=reg, os_names=["홍길동", *cx["self_names"]], local=local)
        items = [K.tw_sep(D)]
        for i, c in enumerate(cs):
            items.append(K.tw_msg(K.KIM, c.sentence, h=9 + i % 8, m=i % 60, files=(f"자료{i}.xlsx",)))
        fake = K.tw_fake([K.tw_room(0, K.tid(50, "group"), cs[0].sentence)], {0: [{"items": items, "chat": "과제A"}]})
        rc, st, err = self.run_tw(fake, "--no-channels", "--no-activity", api=api)
        self.assertEqual(rc, 0, err)
        self.assertGreaterEqual(len(self.rows()), len(cs) - 2)
        known = {c.cid for c in cs if c.cat in ("path_win", "path_unc")} if _path_gap() else set()
        self.assertEqual(sorted(set(find_canaries(self.sb.store_bytes(), cs)) - known), [])
        self.assertTrue(self.sb.audit_lines())
        self.assertEqual(find_canaries(json.dumps(self.sb.audit_lines(), ensure_ascii=False).encode("utf-8"), cs), [])
        self.assertEqual(find_canaries(err.encode("utf-8"), cs), [])
        self.assertEqual(find_canaries(json.dumps(self.sb.cursor("teams.web")).encode("utf-8"), cs), [])


class TimeTest(unittest.TestCase):

    def test_now_today_from_offset(self):
        sb = K.Sandbox()
        self.addCleanup(sb.cleanup)
        fake = K.tw_fake([K.tw_room(0, K.tid(60), "방")],
                         {0: [{"items": [{"t": "sep", "text": "오늘"}, K.tw_msg(K.KIM, "오늘 메시지", h=8, m=30)]}]})
        rc, _st, _ = K.run_tw(sb, ["--from", "2026-09-25", "--to", "2026-10-01"], fake=fake,
                              now=datetime(2026, 10, 1, 1, 0, tzinfo=UTC))
        self.assertEqual(rc, 0)
        (row,) = sb.rows("teams", "teams.web")
        self.assertEqual((row["ts_utc"], row["ts_local_offset"]), ("2026-09-30T23:30:00Z", "+09:00"))


if __name__ == "__main__":
    unittest.main()
