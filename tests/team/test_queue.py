# -*- coding: utf-8 -*-
"""WP-34 팀 대기열 — 정규 바이트 1벌 + meta(``lm27.outbox/1``), 같은 바이트 재빌드(rc 4 · 승인 유지), U09 대체(superseded ·
보내는 중 lease 는 건드리지 않음), U11 크기 막힘(승인·보내기 불가), 상태 기계(mark·approve·끝난 항목), 미리보기 = 파일 바이트
(sha 재대조·가림 표·변조 감지), meta 재구성, sent·dropped 보관 개수, 재시도 일정(±10% 결정적 흔들기·소진), 보낼 차례 규칙.
네트워크 없음(대상 고르기는 주입한 hello 로)."""
import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from lm27.team import build as B
from lm27.team import client as C
from lm27.team import queue as Q
from lm27.util import events, fsx
from tests.fixtures.wp34 import world as W

PERIOD = {"from": W.D0, "to": W.D1}
PER = f"{W.D0}_{W.D1}"
NOW = datetime(2026, 10, 1, 1, 0, 0, tzinfo=UTC)


def refused(base, timeout, *, proxy=False, target="primary"):
    """주입 hello — 모든 주소가 연결 거부(네트워크를 쓰지 않는다)."""
    return C.Hello("refused", 0, None, "R-TEAM-REFUSED", C.TEXT_KO["refused"], {}, target)


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class QCase(unittest.TestCase):
    def setUp(self):
        self._mode = events.mode()
        events.configure("off")
        self.w = W.World()
        self.p = self.w.paths
        self.cfg = W.cfg()

    def tearDown(self):
        self.w.cleanup()
        events.configure(self._mode)

    def make(self, cfg=None, *, now=NOW, period=PERIOD, model=None):
        c = cfg or self.cfg
        return B.build_and_queue(model or W.model(), period, c, paths=self.p, now=now, env=self.w.env(c, period=period))

    def files(self, folder):
        try:
            return sorted(os.listdir(self.p.outbox(folder)))
        except FileNotFoundError:
            return []


class TestPending(QCase):
    def test_one_body_and_meta(self):
        it = self.make()
        self.assertEqual((it.rc, it.folder, it.state), (0, "pending", "pending"))
        m = Q.BODY_RX.fullmatch(it.name)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), PER)
        raw = fsx.read_bytes(it.path)
        self.assertEqual((it.sha256, it.meta["bytes"], m.group(2)), (fsx.sha256_hex(raw), len(raw), it.sha256[:12]))
        self.assertEqual(self.files("pending"), [it.name, it.name + Q.META_SUFFIX])
        meta = fsx.read_json(it.meta_path, None)
        self.assertEqual(meta, it.meta)
        self.assertEqual((meta["schema"], meta["approved"], meta["attempts"], meta["person_key"], meta["period_key"]),
                         (Q.META_SCHEMA, False, 0, W.PERSON_KEY, PER))
        self.assertEqual(meta["history"], [{"at": _ts(NOW), "event": "built"}])
        self.assertEqual(meta["check"], {"peer_unresolved": 1, "team_text_rejected": meta["check"]["team_text_rejected"],
                                         "violations": 0})
        self.assertEqual(meta["blockers"], [])
        self.assertNotIn(self.w.root.encode("utf-8"), fsx.canon_bytes(meta))        # meta 에 경로 없음
        self.assertEqual([x.name for x in Q.list_items(paths=self.p)], [it.name])
        self.assertEqual(Q.find_item(self.p, it.name[:-5]).sha256, it.sha256)
        self.assertEqual(Q.find_pending(self.p, it.sha256).name, it.name)
        self.assertIn("미리보기", it.message)

    def test_same_bytes_rc4_keeps_approval(self):
        it = self.make()
        self.assertEqual(Q.approve(it, now=NOW).rc, 0)
        again = self.make(now=NOW)
        self.assertEqual((again.rc, again.name, again.meta["approved"]), (4, it.name, True))
        self.assertEqual(len(self.files("pending")), 2)

    def test_meta_rebuilt_when_missing(self):
        it = self.make()
        Q.approve(it, now=NOW)
        os.remove(it.meta_path)
        got = Q.find_item(self.p, it.name)
        self.assertEqual((got.state, got.sha256, got.meta["approved"]), ("pending", it.sha256, False))
        self.assertEqual(got.meta["history"][-1]["event"], "meta_rebuilt")


class TestSupersede(QCase):
    def test_u09_same_period_other_bytes_dropped(self):
        a = self.make(W.cfg(**{"team.selfLabel": "팀원A"}))
        Q.approve(a, now=NOW)
        sep = self.make(W.cfg(**{"team.selfLabel": "팀원A"}), period={"from": "2026-09-01", "to": "2026-09-30"})
        b = self.make(W.cfg(**{"team.selfLabel": "팀원B"}), now=NOW + timedelta(minutes=5))
        self.assertEqual(b.rc, 0)
        self.assertNotEqual(a.sha256, b.sha256)
        self.assertIn("대체됨", b.message)
        old = Q.find_item(self.p, a.name)
        self.assertEqual((old.folder, old.state, old.meta["history"][-1]["why"]), ("dropped", "dropped", "superseded"))
        self.assertEqual(Q.find_item(self.p, sep.name).state, "pending")             # 다른 기간은 그대로
        self.assertEqual(sorted(x.name for x in Q.list_items(paths=self.p) if x.folder == "pending"),
                         sorted([b.name, sep.name]))

    def test_sending_item_not_superseded(self):
        a = self.make(W.cfg(**{"team.selfLabel": "팀원A"}))
        until = datetime.now(UTC) + timedelta(minutes=5)
        fsx.atomic_write(self.p.outbox_file("pending", a.name + Q.LEASE_SUFFIX),
                         fsx.canon_bytes({"pid": os.getpid(), "until": _ts(until)}))
        b = self.make(W.cfg(**{"team.selfLabel": "팀원B"}))
        self.assertEqual(b.rc, 0)
        self.assertEqual(Q.find_item(self.p, a.name).state, "pending")


class TestBlockers(QCase):
    def test_u11_size_blocks_approve_and_send(self):
        c = W.cfg(**{"team.maxBundleMb": 1})
        with mock.patch.object(B, "MB", 1000):                                     # 상한 1000 바이트로 모사
            it = self.make(c)
        self.assertEqual(it.rc, 2)
        self.assertIn("보낼 수 없습니다", it.message)
        self.assertEqual(len(it.meta["blockers"]), 1)
        self.assertEqual(it.folder, "pending")
        self.assertEqual(Q.approve(it, now=NOW).rc, 2)
        out = Q.send_item(it, c, now=NOW, hello_fn=refused)
        self.assertEqual(out.rc, 2)
        self.assertEqual(Q.find_item(self.p, it.name).meta["attempts"], 0)
        pv = Q.preview(it)
        self.assertEqual((pv["rc"], pv["can_send"]), (0, False))
        res = Q.send_due(c, paths=self.p, now=NOW, hello_fn=refused)
        self.assertEqual((res.rc, res.sent, res.retry), (4, 0, 0))


class TestStateMachine(QCase):
    def test_approve_mark_final(self):
        it = self.make()
        self.assertEqual(Q.approve(it, now=NOW).rc, 0)
        self.assertEqual(Q.approve(it, now=NOW).rc, 4)
        d = Q.mark(it, "dropped", "사용자가 치움", now=NOW)
        self.assertEqual((d.rc, d.folder, d.state), (0, "dropped", "dropped"))
        self.assertEqual(self.files("pending"), [])
        self.assertEqual(self.files("dropped"), [it.name, it.name + Q.META_SUFFIX])
        self.assertEqual(Q.approve(d, now=NOW).rc, 4)
        self.assertEqual(Q.mark(d, "dropped", "또", now=NOW).rc, 4)
        self.assertEqual(Q.mark(d, "pending", "되살리기", now=NOW).rc, 4)              # 끝난 항목은 바꾸지 않는다
        with self.assertRaises(ValueError):
            Q.mark(d, "bogus", "x")

    def test_failed_back_to_pending_resets_attempts(self):
        it = self.make()
        f = Q.mark(it, "failed", "x", now=NOW, extra={"attempts": 7})
        self.assertEqual((f.folder, f.meta["attempts"], f.meta["last_error"]), ("failed", 7, "x"))
        p = Q.mark(f, "pending", "다시 시도", now=NOW)
        self.assertEqual((p.folder, p.meta["attempts"], p.meta["next_at"]), ("pending", 0, None))
        self.assertEqual([h["event"] for h in p.meta["history"]], ["built", "failed", "pending"])

    def test_missing_item(self):
        it = self.make()
        os.remove(it.path)
        os.remove(it.meta_path)
        self.assertEqual(Q.mark(it, "dropped", "x").rc, 4)
        self.assertEqual(Q.approve(it).rc, 4)
        self.assertEqual(Q.preview(it)["rc"], 4)
        self.assertEqual(Q.send_item(it, self.cfg, hello_fn=refused).rc, 4)

    def test_history_capped(self):
        it = self.make()
        for i in range(Q.HISTORY_MAX + 5):
            it = Q.mark(it, "retry_wait" if i % 2 else "pending", f"n{i}", now=NOW)
        self.assertEqual(len(it.meta["history"]), Q.HISTORY_MAX)


class TestPreview(QCase):
    def test_same_bytes_summary_and_masks(self):
        it = self.make()
        raw = fsx.read_bytes(it.path)
        obj = json.loads(raw)
        pv0 = Q.preview(it)
        self.assertTrue(pv0["can_send"])
        self.assertEqual((pv0["mask_gaps"], pv0["stale_mask"]), ([], False))
        B.set_mask(self.p, W.U[1], "title")
        pv = Q.preview(it)
        self.assertEqual((pv["rc"], pv["sha_ok"], pv["sha256"], pv["bytes"]), (0, True, it.sha256, len(raw)))
        self.assertEqual(pv["json"].encode("utf-8"), raw)                           # 미리보기 = 실전송 바이트
        self.assertFalse(pv["can_send"], "가림을 바꾼 뒤의 옛 바이트는 보내지 않는다(C16)")
        self.assertEqual((pv["mask_gaps"], pv["stale_mask"], pv["message"]), ([f"unit:{W.U[1]}:title"], True, Q.STALE_MASK))
        self.assertEqual({u["unit_id"]: u["mask_applied"] for u in pv["units"]}[W.U[1]], False)
        self.assertEqual(pv["guard"], [])
        self.assertEqual([m["mm"] for m in pv["summary"]["months"]], [m["mm"] for m in obj["summary"]["months"]])
        self.assertEqual(sum(pv["summary"]["domains"].values()), obj["integrity"]["alloc_min"])
        self.assertEqual(pv["summary"]["units"], len(obj["units"]))
        masks = {u["unit_id"]: u["mask"] for u in pv["units"]}
        self.assertEqual(masks[W.U[1]], "title")
        self.assertEqual({v for k, v in masks.items() if k != W.U[1]}, {""})
        self.assertIn("가릴 수 없습니다", pv["mask_note"])
        self.assertNotIn(self.w.root, json.dumps({k: v for k, v in pv.items() if k != "json"}, ensure_ascii=False))

    def test_tamper_detected(self):
        it = self.make()
        raw = fsx.read_bytes(it.path)
        fsx.atomic_write(it.path, raw.replace(b'"self_label":""', b'"self_label":"x"'))
        pv = Q.preview(it)
        self.assertEqual((pv["rc"], pv["sha_ok"], pv["can_send"]), (1, False, False))
        out = Q.send_item(it, self.cfg, now=NOW, hello_fn=refused)                  # 보내지 않고 failed
        self.assertEqual((out.rc, out.state, out.folder), (1, "failed", "failed"))


class TestMaskChange(QCase):
    """C16 회귀: 미리보기 [제목 가림]·[세부 가림]·니즈 빼기 뒤, 가리기 전에 만든(승인된) 묶음은 자동 전송·[보내기]·승인 모두
    되지 않는다(예전: 승인된 옛 바이트가 가리지 않은 제목 그대로 자동 전송). 다시 만들면 새 바이트가 옛 것을 대체한다."""

    def test_mask_unapproves_and_blocks_send_until_rebuilt(self):
        it = self.make()
        self.assertEqual(Q.approve(it, now=NOW).rc, 0)
        obj = json.loads(fsx.read_bytes(it.path))
        u0 = obj["units"][0]
        self.assertEqual(u0["title_mode"], "label")
        r = B.set_mask(self.p, u0["unit_id"], "title")
        self.assertEqual((r["rc"], r["stale"], r["periods"]), (0, [it.name], [PER]))
        self.assertIn("보내지 않습니다", r["message"])
        cur = Q.find_item(self.p, it.name)
        self.assertEqual((cur.state, cur.meta["approved"], cur.meta["history"][-1]["event"]),
                         ("pending", False, "mask_changed"))
        self.assertEqual(Q.mask_gaps(cur), [f"unit:{u0['unit_id']}:title"])
        self.assertEqual((Q.approve(cur, now=NOW).rc, Q.approve(cur, now=NOW).message), (2, Q.STALE_MASK))
        calls = []

        def spy(*a, **k):
            calls.append(a)
            return refused(*a, **k)
        for c in (self.cfg, W.cfg(**{"team.autoSend": True})):            # 자동 전송 설정이어도 보내지 않는다
            res = Q.send_due(c, paths=self.p, now=NOW, trigger="startup", hello_fn=spy)
            self.assertEqual(res.sent, 0)
        res = Q.send_due(W.cfg(**{"team.autoSend": True}), paths=self.p, now=NOW, hello_fn=spy)
        self.assertEqual((res.rc, res.sent), (2, 0))
        self.assertIn("다시 만들어야", res.message)
        self.assertEqual(calls, [], "가림이 안 들어간 바이트로는 팀 서버에 묻지도 않는다")
        out = Q.send_item(cur, self.cfg, now=NOW, hello_fn=spy)            # 명시 전송(cli team send <item>)도 막는다
        self.assertEqual((out.rc, out.state, out.message), (2, "pending", Q.STALE_MASK))
        self.assertEqual(calls, [])
        new = self.make(now=NOW + timedelta(minutes=1))                      # 다시 만들기 → 새 바이트, 옛 것은 대체됨
        self.assertNotEqual(new.sha256, it.sha256)
        self.assertEqual(Q.mask_gaps(new), [])
        self.assertEqual(Q.find_item(self.p, it.name).state, "dropped")
        nu = {u["unit_id"]: u for u in json.loads(fsx.read_bytes(new.path))["units"]}
        self.assertEqual(nu[u0["unit_id"]]["title_mode"], "generic")
        self.assertNotIn(u0["title"], fsx.read_bytes(new.path).decode("utf-8"))
        self.assertEqual(Q.approve(new, now=NOW).rc, 0)

    def test_detail_mask_and_drop_need_and_unmask(self):
        it = self.make()
        Q.approve(it, now=NOW)
        obj = json.loads(fsx.read_bytes(it.path))
        nid = obj["agentic"]["needs"][0]["need_id"]
        r = B.drop_need(self.p, nid)
        self.assertEqual((r["rc"], r["stale"]), (0, [it.name]))
        self.assertIn(f"need:{nid}", Q.mask_gaps(Q.find_item(self.p, it.name)))
        it2 = self.make(now=NOW + timedelta(minutes=1))
        self.assertEqual(Q.mask_gaps(it2), [])
        u = next(x for x in json.loads(fsx.read_bytes(it2.path))["units"] if x["peers"] or x["apps"])
        B.set_mask(self.p, u["unit_id"], "detail")
        gaps = Q.mask_gaps(Q.find_item(self.p, it2.name))
        self.assertIn(f"unit:{u['unit_id']}:detail", gaps)                  # 동료·앱·근거 수가 남은 옛 바이트
        self.assertEqual(f"unit:{u['unit_id']}:title" in gaps, u["title_mode"] != "generic")
        it3 = self.make(now=NOW + timedelta(minutes=2))
        self.assertEqual(Q.mask_gaps(it3), [])
        Q.approve(it3, now=NOW)
        r = B.set_mask(self.p, u["unit_id"], "none")                         # 되돌리기 = 더 가려진 바이트 — 틈이 아니다
        self.assertEqual((r["rc"], r["stale"]), (0, []))
        self.assertTrue(Q.find_item(self.p, it3.name).meta["approved"])
        self.assertEqual(B.set_mask(self.p, u["unit_id"], "none", invalidate=False)["rc"], 4)


class TestPreviewMark(QCase):
    """C17 회귀 바탕: 미리보기 확인 기록 — 그 바이트(sha)를 보여 준 적이 있어야 '미리보기를 거쳤다'."""

    def test_mark_previewed(self):
        it = self.make()
        self.assertFalse(Q.previewed(it))
        self.assertEqual(Q.mark_previewed(it, "0" * 64, now=NOW).meta.get("previewed_sha"), None)   # 다른 바이트
        cur = Q.mark_previewed(it, it.sha256, now=NOW)
        self.assertEqual((cur.meta["previewed_sha"], cur.meta["previewed_at"]), (it.sha256, _ts(NOW)))
        self.assertTrue(Q.previewed(Q.find_item(self.p, it.name)))
        self.assertEqual(Q.find_item(self.p, it.name).meta["approved"], False)       # 기록만 — 승인하지 않는다
        other = Q.find_item(self.p, it.name)
        other.meta = dict(other.meta, previewed_sha="1" * 64)
        self.assertFalse(Q.previewed(other))


class TestPrune(QCase):
    def test_sent_and_dropped_keep_newest(self):
        names = []
        for i in range(4):
            raw = fsx.canon_bytes({"n": i})
            sha = fsx.sha256_hex(raw)
            meta = Q.new_meta(sha, len(raw), PER, W.PERSON_KEY, "", "", [], now=NOW)
            it = Q.write_pending(self.p, PER, raw, meta)
            Q.mark(it, "sent" if i < 3 else "dropped", "ok", now=NOW + timedelta(hours=i))
            names.append(it.name)
        self.assertEqual(Q.prune_sent(self.p, 1), 2)
        self.assertEqual(self.files("sent"), [names[2], names[2] + Q.META_SUFFIX])
        self.assertEqual(self.files("dropped"), [names[3], names[3] + Q.META_SUFFIX])


class TestRetry(QCase):
    def test_u05_schedule_jitter_and_exhaustion(self):
        it = self.make()
        sha = it.sha256
        for a in range(1, 8):
            j = Q._jitter(sha, a)
            self.assertLessEqual(abs(j), Q.JITTER)
            self.assertEqual(j, Q._jitter(sha, a))
        self.assertNotEqual(Q._jitter(sha, 1), Q._jitter(sha, 2))
        c = W.cfg(**{"team.retryMaxAttempts": 2})
        r1 = Q.send_item(it, c, now=NOW, hello_fn=refused)
        self.assertEqual((r1.rc, r1.state, r1.meta["attempts"]), (2, "retry_wait", 1))
        nxt = datetime.strptime(r1.meta["next_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        self.assertEqual(nxt, NOW + timedelta(seconds=round(60 * (1 + Q._jitter(sha, 1)))))
        self.assertTrue(54 <= (nxt - NOW).total_seconds() <= 66)
        self.assertTrue(r1.meta["approved"])                                        # send_item = 승인 + 전송
        self.assertIn("닿지 않습니다", r1.meta["last_error"])
        r2 = Q.send_item(r1, c, now=NOW, hello_fn=refused)
        nxt = datetime.strptime(r2.meta["next_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        self.assertEqual(r2.meta["attempts"], 2)
        self.assertTrue(270 <= (nxt - NOW).total_seconds() <= 330)
        r3 = Q.send_item(r2, c, now=NOW, hello_fn=refused)
        self.assertEqual((r3.rc, r3.state, r3.folder), (1, "failed", "failed"))
        self.assertIn("retry_exhausted", r3.meta["last_error"])
        self.assertEqual(self.files(Q.FOLDER_OF["retry_wait"]), [])
        self.assertEqual([f for f in self.files("failed") if f.endswith(Q.LEASE_SUFFIX)], [])

    def test_timer_waits_for_next_at_collect_does_not_count(self):
        it = self.make()
        Q.approve(it, now=NOW)
        r = Q.send_due(self.cfg, paths=self.p, now=NOW, trigger="timer", hello_fn=refused)
        self.assertEqual((r.rc, r.retry), (2, 1))
        r = Q.send_due(self.cfg, paths=self.p, now=NOW + timedelta(seconds=10), trigger="timer", hello_fn=refused)
        self.assertEqual((r.rc, r.skipped, r.retry), (4, 1, 0))                      # next_at 전 — 묻지도 않는다
        r = Q.send_due(self.cfg, paths=self.p, now=NOW + timedelta(seconds=10), trigger="collect", hello_fn=refused)
        self.assertEqual((r.rc, r.waiting), (2, 1))
        self.assertEqual(Q.find_item(self.p, it.name).meta["attempts"], 1)          # [수집]·기동은 횟수를 올리지 않는다
        r = Q.send_due(self.cfg, paths=self.p, now=NOW + timedelta(seconds=10), trigger="startup", hello_fn=refused)
        self.assertEqual(Q.find_item(self.p, it.name).meta["attempts"], 1)
        r = Q.send_due(self.cfg, paths=self.p, now=NOW + timedelta(minutes=2), trigger="timer", hello_fn=refused)
        self.assertEqual(Q.find_item(self.p, it.name).meta["attempts"], 2)


class TestDue(QCase):
    def test_rules(self):
        it = self.make()
        fp = {"targets": Q._targets_fp(self.cfg), "token": ""}
        self.assertFalse(Q._due(it, self.cfg, NOW, "manual", fp, False))             # 승인 전
        self.assertTrue(Q._due(it, self.cfg, NOW, "timer", fp, True))                # autoSend
        it.meta["approved"] = True
        self.assertTrue(Q._due(it, self.cfg, NOW, "timer", fp, False))
        it.meta.update(state="retry_wait", next_at=_ts(NOW + timedelta(minutes=1)))
        self.assertFalse(Q._due(it, self.cfg, NOW, "timer", fp, False))
        self.assertFalse(Q._due(it, self.cfg, NOW, "build", fp, False))
        for trig in ("manual", "collect", "startup"):
            self.assertTrue(Q._due(it, self.cfg, NOW, trig, fp, False))
        it.meta.update(state="auth_needed", fp={"targets": fp["targets"], "token": ""})
        self.assertFalse(Q._due(it, self.cfg, NOW, "timer", fp, False))             # 토큰 그대로
        self.assertTrue(Q._due(it, self.cfg, NOW, "timer", {"targets": fp["targets"], "token": "abcd1234"}, False))
        self.assertTrue(Q._due(it, self.cfg, NOW, "manual", fp, False))
        it.meta.update(state="wrong_server", fp={"targets": fp["targets"], "token": ""})
        self.assertFalse(Q._due(it, self.cfg, NOW, "startup", fp, False))           # 주소 그대로
        self.assertTrue(Q._due(it, self.cfg, NOW, "startup", {"targets": "00000000", "token": ""}, False))
        it.meta["blockers"] = ["x"]
        self.assertFalse(Q._due(it, self.cfg, NOW, "manual", fp, True))
        it.meta.update(blockers=[], state="exported")
        self.assertFalse(Q._due(it, self.cfg, NOW, "manual", fp, True))

    def test_send_due_waits_for_approval(self):
        """첫 전송 승인(team.autoSend=false): 승인 전에는 보내지 않고 rc 2 + 안내."""
        self.make()
        calls = []

        def spy(*a, **k):
            calls.append(a)
            return refused(*a, **k)
        r = Q.send_due(self.cfg, paths=self.p, now=NOW, hello_fn=spy)
        self.assertEqual((r.rc, r.sent), (2, 0))
        self.assertIn("승인을 기다리는", r.message)
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            Q.send_due(self.cfg, paths=self.p, trigger="bogus")

    def test_nothing_to_send(self):
        r = Q.send_due(self.cfg, paths=self.p, now=NOW, hello_fn=refused)
        self.assertEqual((r.rc, r.message), (4, "보낼 묶음이 없습니다"))


if __name__ == "__main__":
    unittest.main()
