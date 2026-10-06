# -*- coding: utf-8 -*-
"""WP-33 빈칸 계획기(lm27.collect.todo) — 미관측 날 → 다음 출처·PC 배정 · '불가(확정)' 반영·사슬 넘김 · 자동 해제(released) ·
백필 빈칸 파일(X-315) — CM-4 · CM-9 · CT-2(원장 측) · D-6 · D-7 · 계약 §3.12 · §6.4."""
from __future__ import annotations

import json
import unittest

from lm27.collect import todo
from lm27.util import fsx
from tests.fixtures.wp33.helpers import NOW, Sandbox, hist, ident

PC1, CLOUD = ident("PC1"), ident("CLOUD", kind="cloud")


def cell(day, axis, src, pc, status, reasons=()):
    return {"account": "self", "date": day, "kind_axis": axis, "src": src, "pc_id": pc.pc_id, "status": status,
            "n": 0, "n_minute": 0, "n_date": 0, "n_unknown": 0, "horizon_oldest": None, "horizon_newest": None,
            "reasons": list(reasons), "budget_hit": False, "cap_hit": False, "probe_sig": None, "run_id": "",
            "observed_at": ""}


def days(a, b):
    from datetime import date, timedelta
    d, e = date.fromisoformat(a), date.fromisoformat(b)
    while d <= e:
        yield d.isoformat()
        d += timedelta(days=1)


def pcs(*, cloud=True, cloud_caps=None, pc1_caps=None):
    out = [{"pc_id": PC1.pc_id, "kind": "desktop", "label_auto": "PC1", "first_seen": "2026-09-01T00:00:00Z",
            "capabilities": pc1_caps or {}}]
    if cloud:
        out.append({"pc_id": CLOUD.pc_id, "kind": "cloud", "label_auto": "클라우드PC",
                    "first_seen": "2026-09-02T00:00:00Z", "capabilities": cloud_caps or {}})
    return out


def full_ok(axis_src, a="2026-09-26", b="2026-10-05"):
    """그 축들이 모든 날 ok 인 셀(빈칸 없음)."""
    return [cell(d, ax, src, PC1, "ok") for d in days(a, b) for ax, src in axis_src]


OK_ALL = [("mail_in", "mail.index"), ("mail_out", "mail.index"), ("cal", "cal.index"), ("teams", "teams.uia")]
CONFIRMED = hist(("2026-10-01", "fail", ["R-EDGEPOL"], "s1"), ("2026-10-03", "fail", ["R-EDGEPOL"], "s1"))


class TodoCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(scripts=False)
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10})

    def plan(self, cells, pcs_, prev=(), cfg=None):
        return todo.plan_todo(self.sb.paths, cfg or self.cfg, now=NOW, cells=cells, pcs=pcs_, prev=list(prev))

    def test_no_blanks_no_todos(self):
        self.assertEqual(self.plan(full_ok(OK_ALL), pcs()), [])
        obj = json.loads(fsx.read_bytes(self.sb.paths.todo()))
        self.assertEqual((obj["schema"], obj["todos"]), ("lm27.todo/1", []))

    def test_horizon_days_go_to_owa_on_cloud(self):
        """CM-4·CM-9 — 지평선 밖(보관 사서함 꺼짐 포함)인 메일 날은 백필 PC 의 OWA 로 배정된다(빈칸만)."""
        cells = [c for c in full_ok(OK_ALL) if not (c["kind_axis"].startswith("mail") and c["date"] < "2026-10-01")]
        cells += [cell(d, ax, "mail.com", PC1, "out_of_horizon", ["R-HORIZON"])
                  for d in days("2026-09-26", "2026-09-30") for ax in ("mail_in", "mail_out")]
        ts = self.plan(cells, pcs())
        self.assertEqual(len(ts), 1)
        t = ts[0]
        self.assertEqual((t.todo_id, t.want_src, t.want_pc, t.state, t.kind_axis),
                         ("mail.owa:2026-09-26:2026-09-30", "mail.owa", CLOUD.pc_id, "assigned", "mail_in"))
        self.assertEqual(t.date_range, ["2026-09-26", "2026-09-30"])
        self.assertEqual(t.reasons, ["R-HORIZON"])

    def test_ranges_split_by_month_and_gap(self):
        cells = [c for c in full_ok(OK_ALL) if c["kind_axis"] != "teams"]
        cells += [cell(d, "teams", "teams.uia", PC1, "blocked", ["R-UIAEMPTY"]) for d in
                  ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-04")]
        cells += [cell(d, "teams", "teams.uia", PC1, "ok") for d in ("2026-09-26", "2026-09-27", "2026-09-28",
                                                                     "2026-10-03", "2026-10-05")]
        ids = [t.todo_id for t in self.plan(cells, pcs())]        # CT-2 원장 측: 숨김 창 날 → 팀즈 웹 백필
        self.assertEqual(ids, ["teams.web:2026-09-29:2026-09-30", "teams.web:2026-10-01:2026-10-02",
                               "teams.web:2026-10-04:2026-10-04"])

    def test_missing_axis_is_not_attempted_and_open_without_cloud(self):
        cells = [c for c in full_ok(OK_ALL) if c["kind_axis"] != "cal"]
        ts = self.plan(cells, pcs(cloud=False))                   # 로컬 달 경계에서 구간을 나눈다
        self.assertEqual([(t.want_src, t.want_pc, t.state) for t in ts], [("cal.owa", "cloud", "open")] * 2)
        self.assertEqual([t.date_range for t in ts], [["2026-09-26", "2026-09-30"], ["2026-10-01", "2026-10-05"]])
        self.assertEqual(ts[0].attempts, [])

    def test_pc_axis_never_assigned(self):
        cells = full_ok(OK_ALL) + [cell(d, "pc", "pc.events", PC1, "blocked", ["R-NOEVT"]) for d in days(
            "2026-09-26", "2026-10-05")]
        self.assertEqual(self.plan(cells, pcs()), [])

    def test_confirmed_blocked_owa_falls_to_copilot_then_blocked_confirmed(self):
        cells = [c for c in full_ok(OK_ALL) if c["kind_axis"] != "mail_out"]
        cells += [cell(d, "mail_out", "mail.com", PC1, "blocked", ["R-NEWOL"]) for d in days("2026-10-01", "2026-10-05")]
        cells += [cell(d, "mail_out", "mail.com", PC1, "ok") for d in days("2026-09-26", "2026-09-30")]
        ts = self.plan(cells, pcs(cloud_caps={"mail.owa": CONFIRMED}))
        self.assertEqual([(t.want_src, t.state, t.kind_axis) for t in ts], [("mail.copilot", "assigned", "mail_out")])
        both = {"mail.owa": CONFIRMED, "mail.copilot": hist(("2026-10-01", "fail", ["R-NOLIC"], "s2"),
                                                            ("2026-10-02", "fail", ["R-NOLIC"], "s2"))}
        ts = self.plan(cells, pcs(cloud_caps=both))
        self.assertEqual([(t.want_src, t.state) for t in ts], [("mail.owa", "blocked_confirmed")])
        self.assertEqual(ts[0].reasons, ["R-EDGEPOL", "R-NEWOL", "R-NOLIC"])
        self.assertEqual(ts[0].attempts[-1], {"pc_id": CLOUD.pc_id, "date": "2026-10-03", "result": "R-EDGEPOL"})
        # 다음 생성에서 확정이 풀리면(TTL·탐침 변화·ok) 한 번 released 로 알린다
        prev = [t.to_dict() for t in ts]
        freed = {"mail.owa": hist(("2026-10-01", "fail", ["R-EDGEPOL"], "s1"), ("2026-10-04", "ok", [], "s9")),
                 "mail.copilot": both["mail.copilot"]}
        ts2 = self.plan(cells, pcs(cloud_caps=freed), prev=prev)
        self.assertEqual([(t.todo_id, t.state) for t in ts2], [("mail.owa:2026-10-01:2026-10-05", "released")])
        ts3 = self.plan(cells, pcs(cloud_caps=freed), prev=[t.to_dict() for t in ts2])
        self.assertEqual(ts3[0].state, "assigned")

    def test_still_empty_after_owa_goes_to_copilot(self):
        """C §6.1 '그래도 비면 코파일럿 증인' — OWA 가 이미 시도한 날만 다음 출처로, 둘 다 시도했으면 OWA 로 다시."""
        cells = [c for c in full_ok(OK_ALL) if not c["kind_axis"].startswith("mail")]
        cells += [cell(d, ax, "mail.com", PC1, "blocked", ["R-NEWOL"])
                  for d in days("2026-09-26", "2026-10-05") for ax in ("mail_in", "mail_out")]
        cells += [cell(d, ax, "mail.owa", CLOUD, "transport_fail", ["R-TRANSPORT"])
                  for d in days("2026-10-01", "2026-10-05") for ax in ("mail_in", "mail_out")]
        cells += [cell(d, ax, "mail.copilot", CLOUD, "zero_ok")                  # 증인 zero_ok — 덮지 못한다
                  for d in ("2026-10-04", "2026-10-05") for ax in ("mail_in", "mail_out")]
        ts = self.plan(cells, pcs())
        self.assertEqual([(t.todo_id, t.state) for t in ts],
                         [("mail.owa:2026-09-26:2026-09-30", "assigned"),       # OWA 미시도
                          ("mail.copilot:2026-10-01:2026-10-03", "assigned"),   # OWA 가 읽었는데도 빔
                          ("mail.owa:2026-10-04:2026-10-05", "assigned")])      # 둘 다 시도 → 첫 출처로 다시

    def test_edge_policy_confirmed_blocks_web_backfill(self):
        cells = [c for c in full_ok(OK_ALL) if c["kind_axis"] != "teams"]
        cells += [cell(d, "teams", "teams.uia", PC1, "transport_fail", ["R-TRANSPORT"]) for d in days(
            "2026-09-26", "2026-10-05")]
        ts = self.plan(cells, pcs(cloud_caps={"edge_cdp_policy": CONFIRMED}))
        self.assertEqual({t.want_src for t in ts}, {"teams.copilot"})

    def test_calendar_copilot_off_by_default(self):
        cells = [c for c in full_ok(OK_ALL) if c["kind_axis"] != "cal"]
        cells += [cell(d, "cal", "cal.index", PC1, "blocked", ["R-NOIDX"]) for d in days("2026-09-26", "2026-10-05")]
        ts = self.plan(cells, pcs(cloud_caps={"cal.owa": CONFIRMED}))
        self.assertEqual({(t.want_src, t.state) for t in ts}, {("cal.owa", "blocked_confirmed")})
        cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "bridge.stages": {"lookup_calendar": True}})
        ts = self.plan(cells, pcs(cloud_caps={"cal.owa": CONFIRMED}), cfg=cfg)
        self.assertEqual({(t.want_src, t.state) for t in ts}, {("cal.copilot", "assigned")})

    def test_blanks_file(self):
        cells = [c for c in full_ok(OK_ALL) if not c["kind_axis"].startswith("mail")]
        cells += [cell(d, "mail_in", "mail.com", PC1, "out_of_horizon", ["R-HORIZON"]) for d in days(
            "2026-09-26", "2026-10-05")]
        cells += [cell(d, "mail_out", "mail.com", PC1, "ok") for d in days("2026-09-26", "2026-10-05")]
        ts = self.plan(cells, pcs())
        run = "20261005-120000-0abc"
        p = todo.write_blanks(self.sb.paths, run, "mail.owa", ts, pc_id=CLOUD.pc_id)
        self.assertEqual(str(p), str(self.sb.paths.blanks_file(run, "mail.owa")))
        rows = json.loads(fsx.read_bytes(p))
        self.assertEqual(rows, [{"todo_id": "mail.owa:2026-09-26:2026-09-30", "date_range": ["2026-09-26", "2026-09-30"],
                                 "kind_axis": "mail_in"},
                                {"todo_id": "mail.owa:2026-10-01:2026-10-05", "date_range": ["2026-10-01", "2026-10-05"],
                                 "kind_axis": "mail_in"}])
        self.assertIsNone(todo.write_blanks(self.sb.paths, run, "mail.owa", ts, pc_id=PC1.pc_id))   # 남의 작업
        self.assertIsNone(todo.write_blanks(self.sb.paths, run, "teams.web", ts, pc_id=CLOUD.pc_id))
        self.assertEqual(todo.load_todo(self.sb.paths)[0]["todo_id"], "mail.owa:2026-09-26:2026-09-30")

    def test_deterministic(self):
        cells = [cell(d, "teams", "teams.uia", PC1, "blocked", ["R-UIAEMPTY"]) for d in days("2026-09-26", "2026-10-05")]
        self.plan(cells, pcs())
        a = fsx.read_bytes(self.sb.paths.todo())
        self.plan(list(reversed(cells)), list(reversed(pcs())))
        self.assertEqual(a, fsx.read_bytes(self.sb.paths.todo()))


if __name__ == "__main__":
    unittest.main()
