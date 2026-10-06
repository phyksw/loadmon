# -*- coding: utf-8 -*-
"""WP-25 Get-MailViaCopilot.py(mail.copilot — 어댑터 한 벌) 시험 — 실물 정제·저장 지점(WP-11)·실물 브리지 L2·L3(WP-24) +
스텁 전송·가상 시계(실 Edge·Copilot 0). 쓰기는 %TEMP% 샌드박스(``Paths(root, lad=…)``)에만.

B §8.1 어댑터(빈칸 → ai_in → run_stages → ai_out 행 → 증인 행 → SegmentWriter) · 계약 §3.2 증인 행(ts_precision summary ·
confidence 0.3 · 그 날짜 00:00 근무 시간대 · src mail.copilot · 메시지 행과 병합 제외) · §3.10 커서 witnessed_days(flush
성공 뒤에만) · B-T54(시각 붙은 행 → 날짜만, 셀 n_minute 0) · B-T39(쪼갠 구간) · 셀·rc 표(B §8.1 · X-257: 무라이선스 blocked
R-NOLIC rc 3 · 로그인 rc 2 · 상한 partial R-CAP · 이미 증인 rc 4 · 대상 없음 rc 1) · v1.2 C1 상태 줄 · T-07(샌드박스 카나리아 0)."""
from __future__ import annotations

import importlib.util
import unittest

from lm27.util import events

from tests.fixtures.wp25 import kit as K

A = K.adapter()
R_ = "R-"                                         # 사유 코드는 런타임에 조립(L-13 — 시험의 표본 문자열)


def setUpModule():
    events.configure(mode="off")


def mail_rows(key):
    d0 = key.split(":")[1]
    return [{"t": d0, "d": "in", "who": "partner.example", "rcv": "to", "s": "견적 회신", "th": "견적 요청"},
            {"t": d0 + " 14:30", "d": "out", "s": "회의 자료 송부"},
            {"t": "2026-08-31", "d": "in", "s": "구간 밖"}]


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def run_mail(self, argv=None, **kw):
        argv = argv if argv is not None else ["--run-id", K.RUN, "--blanks-file", self.sb.blanks()]
        return K.run_adapter(self.sb, "mail.copilot", argv, **kw)


class HappyPath(_Base):
    def test_witness_rows_cells_cursor(self):
        rc, st, _n, resp = self.run_mail(rows=mail_rows)
        self.assertEqual(rc, 0, st)
        self.assertEqual((st["schema"], st["src"], st["stage"], st["rc"], st["n"]),
                         ("lm27.collector_status/1", "mail.copilot", "lookup_mail", 0, 2))
        for k in ("reasons", "partial", "cap_hit", "budget_hit", "counts"):
            self.assertIn(k, st)                                             # v1.2 C1 필수 필드
        self.assertEqual((st["partial"], st["cap_hit"], st["budget_hit"], st["reasons"]), (False, False, False, []))
        self.assertEqual(st["counts"]["dropped.time_dropped"], 1)            # B-T54
        self.assertEqual(st["counts"]["dropped.out_of_window"], 1)           # B-T40
        self.assertEqual(resp.count["lookup_mail"], 1)
        rows = self.sb.rows("mail", "mail.copilot")
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual((r["src"], r["kind"], r["ts_precision"], r["confidence"], r["ts_utc"], r["ts_local_offset"]),
                             ("mail.copilot", "mail", "summary", 0.3, "2026-08-31T15:00:00Z", "+09:00"))
            self.assertRegex(r["msg_key"], r"^m[0-9a-f]{24}$")               # 'cp' 재료 HMAC(계약 §4.2)
            self.assertNotIn("subject_masked", r)
        self.assertEqual(sorted(r["text_masked"] for r in rows), ["견적 회신 / 견적 요청", "회의 자료 송부"])
        cells = {(c["date"], c["axis"]): c for c in st["cells"]}
        self.assertEqual(len(cells), 14)
        self.assertEqual(cells[("2026-09-01", "mail_in")], {"date": "2026-09-01", "axis": "mail_in", "status": "ok",
                                                            "n": 1, "n_date": 1, "n_minute": 0})
        self.assertEqual(cells[("2026-09-01", "mail_out")]["status"], "ok")
        self.assertEqual(cells[("2026-09-02", "mail_in")], {"date": "2026-09-02", "axis": "mail_in", "status": "zero_ok",
                                                            "n": 0, "n_date": 0, "n_minute": 0})
        self.assertEqual({c["n_minute"] for c in cells.values()}, {0})
        self.assertEqual(self.sb.cursor("mail.copilot"),
                         {"witnessed_days": [f"2026-09-0{d}" for d in range(1, 8)]})
        self.assertTrue(st["cursor_saved"])

    def test_zero_rows_zero_ok_rc1(self):
        rc, st, _n, _r = self.run_mail(rows=lambda key: [])
        self.assertEqual((rc, st["n"], {c["status"] for c in st["cells"]}), (1, 0, {"zero_ok"}))
        self.assertEqual(len(self.sb.cursor("mail.copilot")["witnessed_days"]), 7)

    def test_already_witnessed_rc4_and_force(self):
        self.run_mail(rows=mail_rows)
        rc, st, _n, resp = self.run_mail(["--run-id", K.RUN2, "--blanks-file", self.sb.blanks()], rows=mail_rows)
        self.assertEqual((rc, st["counts"]["already_witnessed"], resp.count["lookup_mail"]), (4, 7, 0))
        rc, st, _n, resp = self.run_mail(["--run-id", K.RUN2, "--blanks-file", self.sb.blanks(), "--force"],
                                         rows=mail_rows)
        self.assertEqual((rc, resp.count["lookup_mail"], st["bridge"]["state"]), (0, 0, "done"))   # 저장소에서 재개
        self.assertEqual(len(self.sb.rows("mail", "mail.copilot")), 4)        # 같은 id 행 덧붙임(로더가 흡수)
        self.assertEqual(len({r["id"] for r in self.sb.rows("mail", "mail.copilot")}), 2)

    def test_split_window_children(self):
        full = "lookup_mail:2026-09-01:2026-09-07"

        def rows(key):
            if key == full:
                return [{"t": "2026-09-01", "d": "in", "s": f"메일 {i}"} for i in range(40)]
            return [{"t": key.split(":")[1], "d": "out", "s": "회신"}]
        rc, st, _n, resp = self.run_mail(rows=rows)
        self.assertEqual((rc, st["n"], resp.count["lookup_mail"]), (0, 2, 3))
        self.assertEqual(st["counts"]["answered_windows"], 2)
        days = {r["ts_utc"] for r in self.sb.rows("mail", "mail.copilot")}
        self.assertEqual(days, {"2026-08-31T15:00:00Z", "2026-09-03T15:00:00Z"})

    def test_capped_partial(self):
        b = self.sb.blanks("2026-09-02", "2026-09-02", axes=("mail_in",))
        rc, st, _n, _r = self.run_mail(["--run-id", K.RUN, "--blanks-file", b],
                                       rows=lambda key: [{"t": "2026-09-02", "d": "in", "s": f"메일 {i}"} for i in range(40)])
        self.assertEqual((rc, st["cap_hit"], st["partial"], st["reasons"]), (0, True, True, [R_ + "CAP"]))
        self.assertEqual(st["cells"], [{"date": "2026-09-02", "axis": "mail_in", "status": "partial", "n": 40,
                                        "n_date": 40, "n_minute": 0, "reasons": [R_ + "CAP"]}])

    def test_canary_not_on_disk(self):
        phone = "-".join(("0" + "1" + "0", "8" * 4, "2" * 4))
        rows = [{"t": "2026-09-03", "d": "in", "s": "연락처 " + phone + " 회신 요청"}]
        rc, st, _n, _r = self.run_mail(rows=lambda key: rows)
        self.assertEqual(rc, 0)
        self.assertFalse(phone.encode() in self.sb.tree_bytes(), "카나리아가 샌드박스 파일에 남음")
        self.assertIn("[전화]", self.sb.rows("mail", "mail.copilot")[0]["text_masked"])


class NotMerged(_Base):
    """계약 §3.2 · X-046 — 증인 행은 메시지 행과 병합하지 않는다(읽기 시 병합 실물 ``lm27.normalize.merge`` 로 확인).
    같은 구간을 --force 로 다시 써서 덧붙은 같은 증인(같은 id — 결정적 행 id)은 단일 로더 규칙(T-11)으로 하나가 된다."""

    @unittest.skipUnless(importlib.util.find_spec("lm27.normalize.merge"), "읽기 시 병합 모듈 전")
    def test_witness_rows_stay_apart_from_messages(self):
        from lm27.normalize.merge import merge_messages
        self.run_mail(rows=mail_rows)
        self.run_mail(["--run-id", K.RUN2, "--blanks-file", self.sb.blanks(), "--force"], rows=mail_rows)
        wit = self.sb.rows("mail", "mail.copilot")
        self.assertEqual(len(wit), 4)
        msg = dict(wit[0], src="mail.com", id="0123456789abcdef", ts_precision="exact", confidence=1.0,
                   ts_utc="2026-09-01T01:00:00Z")                         # 같은 날·같은 키의 실제 메시지 행
        stats: dict = {}
        out = merge_messages([*wit, msg], off_min=540, stats=stats)
        self.assertEqual(sorted(r["src"] for r in out), ["mail.com", "mail.copilot", "mail.copilot"])
        self.assertEqual((stats["rows_in"], stats["exact_merged"], stats["copilot_dups"]), (3, 0, 0))
        kept = next(r for r in out if r["src"] == "mail.com")
        self.assertEqual((kept["ts_precision"], kept["confidence"]), ("exact", 1.0))
        for r in out:
            if r["src"] == "mail.copilot":
                self.assertEqual((r["ts_precision"], r["confidence"]), ("summary", 0.3))


class Assignment(_Base):
    def test_no_blanks_no_range_rc1(self):
        rc, st, _n, resp = self.run_mail(["--run-id", K.RUN], rows=mail_rows)
        self.assertEqual((rc, st["counts"]["assigned_days"], resp.count["lookup_mail"]), (1, 0, 0))
        self.assertFalse(self.sb.paths.ai_in("lookup_mail").exists())

    def test_range_and_default_blanks_path(self):
        rc, st, _n, _r = self.run_mail(["--from", "2026-09-10", "--to", "2026-09-11"], rows=mail_rows)
        self.assertEqual((rc, st["counts"]["assigned_days"]), (0, 2))
        self.assertRegex(st["run_id"], r"^\d{8}-\d{6}-[0-9a-f]{4}$")
        p = self.sb.paths.blanks_file(K.RUN, "mail.copilot")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'[{"todo_id": "x", "date_range": ["2026-09-20", "2026-09-20"], "kind_axis": "mail_out"}]')
        rc, st, _n, _r = self.run_mail(["--run-id", K.RUN], rows=mail_rows)
        self.assertEqual((st["counts"]["assigned_days"], [c["axis"] for c in st["cells"]]), (1, ["mail_out"]))

    def test_today_and_future_not_asked(self):
        b = self.sb.blanks("2026-09-29", "2026-10-03", axes=("mail_in",))
        rc, st, _n, _r = self.run_mail(["--run-id", K.RUN, "--blanks-file", b], rows=lambda key: [])
        self.assertEqual((st["counts"]["not_past"], st["counts"]["windows"]), (3, 1))
        self.assertEqual([c["date"] for c in st["cells"]], ["2026-09-29", "2026-09-30"])

    def test_missing_explicit_blanks_rc3(self):
        rc, st, _n, _r = self.run_mail(["--run-id", K.RUN, "--blanks-file", str(self.sb.dir / "none.json")])
        self.assertEqual((rc, st["reasons"], st["error"]), (3, [R_ + "TRANSPORT"], "BlanksMissing"))

    def test_disabled_stage(self):
        self.sb.cfg = self.sb.cfg.derive({"bridge.stages": {"lookup_mail": False}})
        rc, st, _n, resp = self.run_mail(rows=mail_rows)
        self.assertEqual((rc, st["skipped"], resp.count["lookup_mail"]), (1, "disabled", 0))


class Failures(_Base):
    def test_nolic_blocked_rc3(self):
        rc, st, notices, _r = self.run_mail(script={"lookup_mail": ["nolic"]}, rows=mail_rows)
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "NOLIC"]))
        self.assertEqual({(c["status"], tuple(c["reasons"])) for c in st["cells"]}, {("blocked", (R_ + "NOLIC",))})
        self.assertIsNone(self.sb.cursor("mail.copilot"))
        self.assertIn("BR-NOLIC", notices.shown)
        self.assertEqual(self.sb.rows("mail", "mail.copilot"), [])

    def test_login_rc2(self):
        rc, st, _n, _r = self.run_mail(script={"lookup_mail": ["phase:login_required"]}, rows=mail_rows)
        self.assertEqual((rc, st["reasons"], st["bridge"]["stop_kind"]), (2, [R_ + "LOGIN"], "fatal"))

    def test_bridge_exception_transport_fail(self):
        def boom(*_a, **_k):
            raise RuntimeError("세션 기동 실패")
        rc, st, _n, _r = self.run_mail(bridge=boom, rows=mail_rows)
        self.assertEqual((rc, st["reasons"], st["bridge"]), (3, [R_ + "TRANSPORT"], {"error": "RuntimeError"}))
        self.assertEqual({c["status"] for c in st["cells"]}, {"transport_fail"})

    def test_writer_failure_keeps_cursor(self):
        rc, st, _n, _r = self.run_mail(rows=mail_rows, api=self.sb.api(fail_flush=True))
        self.assertEqual((rc, st["reasons"], st["error"]), (3, [R_ + "TRANSPORT"], "OSError"))
        self.assertIsNone(self.sb.cursor("mail.copilot"))

    def test_pending_cell_table(self):
        pc = A._pending_cell
        self.assertEqual(pc(None, [], []), ("transport_fail", [R_ + "TRANSPORT"]))
        self.assertEqual(pc({"state": "skipped", "reason": "capability_unavailable"}, [], [R_ + "NOLIC"]),
                         ("blocked", [R_ + "NOLIC"]))
        self.assertEqual(pc({"state": "skipped", "reason": "mode_web", "env": {"tier": "basic"}}, [], []),
                         ("blocked", [R_ + "NOLIC"]))
        self.assertEqual(pc({"state": "skipped", "reason": "mode_web", "env": {"tier": "premium"}}, [], []),
                         ("not_attempted", []))
        self.assertEqual(pc({"state": "skipped", "reason": "disabled"}, [], []), ("not_attempted", []))
        self.assertEqual(pc({"state": "partial", "stop_kind": "budget"}, [], []), ("transport_fail", [R_ + "BUDGET"]))
        self.assertEqual(pc({"state": "partial", "stop_kind": "circuit"}, [], []), ("transport_fail", [R_ + "TRANSPORT"]))
        self.assertEqual(pc({"state": "partial", "stop_kind": "manual_wait"}, ["BR-POLICY"], []),
                         ("blocked", [R_ + "EDGEPOL"]))
        self.assertEqual(pc({"state": "failed", "stop_kind": "fatal", "reason": "policy_blocked"}, [], []),
                         ("blocked", [R_ + "EDGEPOL"]))
        self.assertEqual(pc({"state": "failed", "stop_kind": "fatal", "reason": "dead_session"}, [], []),
                         ("transport_fail", [R_ + "TRANSPORT"]))
        self.assertEqual(pc({"state": "partial", "stop_kind": "refused", "reason": R_ + "NOCONN"}, [], []),
                         ("blocked", [R_ + "NOCONN"]))

    def test_recheck_pending_first_window_one_day(self):
        class Caps:
            def recheck_pending(self, stage):
                return True

            def reasons(self, stage):
                return []
        rc, st, _n, resp = self.run_mail(rows=lambda key: [], caps_factory=lambda paths, settings: Caps())
        self.assertEqual((rc, st["counts"]["recheck"], st["counts"]["windows"]), (1, 1, 2))
        self.assertIn("구간 2026-09-01~2026-09-01]", resp.prompts[0].splitlines()[0])


class Arguments(_Base):
    def test_bad_arguments_status_line(self):
        import io
        import json
        err = io.StringIO()
        self.assertEqual(A.run("mail.copilot", ["--pc", "bad"], paths=self.sb.paths, cfg=self.sb.cfg, err=err), 3)
        st = json.loads(err.getvalue().splitlines()[-1])["_status"]
        self.assertEqual((st["src"], st["rc"], st["error"], st["reasons"]), ("mail.copilot", 3, "BadPcId", [R_ + "TRANSPORT"]))
        err = io.StringIO()
        self.assertEqual(A.run("mail.copilot", ["--pc", K.PC, "--run-id", "x"], paths=self.sb.paths, cfg=self.sb.cfg,
                               err=err), 3)
        self.assertEqual(json.loads(err.getvalue().splitlines()[-1])["_status"]["error"], "BadRunId")


if __name__ == "__main__":
    unittest.main()
