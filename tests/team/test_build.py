# -*- coding: utf-8 -*-
"""WP-34 팀 묶음 빌더 — 허용 목록 빌드가 공용 검증기(TAB §2.3.2)·정제 G4 를 통과하고, 시간 수치는 정수 분 표 그대로
(개인 = 팀, TAB R-3 · A01 의 개인 쪽), W §4.11 대응표, 워크플로우·agentic·동료·품질 = 보고서 모델 값(RPT-12 · RP15),
결정성(U02), 기간 일부·분석 기간 밖, 측정 품질 선택 필드(커버리지 원장·PC 표)·정제 감사 합계·미상 프로그램 제안, 감사 gate_team."""
import json
import os
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from lm27 import privacy as P
from lm27.team import build as B
from lm27.team import queue as Q
from lm27.team import schema as S
from lm27.util import events, fsx
from tests.fixtures.wp34 import world as W

PERIOD = {"from": W.D0, "to": W.D1}
NOW = datetime(2026, 10, 1, 1, 0, 0, tzinfo=UTC)


class BuildCase(unittest.TestCase):
    world_kw: dict = {}

    def setUp(self):
        self._mode = events.mode()
        events.configure("off")
        self.w = W.World(**self.world_kw)
        self.cfg = W.cfg()

    def tearDown(self):
        self.w.cleanup()
        events.configure(self._mode)

    def build(self, model=None, period=None, cfg=None, env=None, overrides=None, registry=None):
        c = cfg or self.cfg
        p = period or PERIOD
        env = env or self.w.env(c, period=p)
        reg = registry if registry is not None else W.registry()
        return B.build_team_bundle(model or W.model(), p, reg, B.pepper_of(reg), overrides or {}, c, env=env, now=NOW)

    def unit(self, obj, n):
        return next((u for u in obj["units"] if u["unit_id"] == W.U[n]), None)


class TestShapeAndTime(BuildCase):
    def test_valid_against_shared_validator_and_g4(self):
        obj, audit = self.build()
        errs = S.validate_team_bundle(obj, registry=W.registry(), side="client", calendar=W.cal())
        self.assertEqual([(e.path, e.code) for e in errs], [])
        self.assertEqual(set(obj), set(S.TEAM_SPEC_V1))
        env = self.w.env(self.cfg)
        self.assertEqual(P.check_team_payload(obj, env.gctx, S.TEAM_SPEC_V1), [])
        self.assertEqual(S.bytes_guard_hits(fsx.canon_bytes(obj)), [])
        self.assertEqual((obj["schema"], obj["schema_version"]), ("lm27.team_bundle", "1.0"))
        self.assertEqual(obj["built_at"], "2026-10-01T10:00:00+09:00")
        self.assertEqual(obj["period"], {"from": W.D0, "to": W.D1, "analyzed_until": "2026-09-30T18:00:00+09:00",
                                         "months": ["2026-08", "2026-09"]})
        g = obj["generator"]
        self.assertEqual((g["app"], g["rules_ver"], g["rules_hash"]), ("LM27", P.RULES_VERSION, P.RULES_HASH))
        self.assertEqual((g["core_version"], g["registry_version"], g["catalog_version"]), ("timecore/1.1", 3, "ag-1"))
        self.assertEqual(audit["peer_unresolved"], 1)

    def test_time_numbers_are_the_integer_tables(self):
        """개인 = 팀: 봉투·귀속 행은 모델(시간 코어 team_tables) 그대로, 월 MM 은 같은 식 — 모델 MM 과 정확히 같다."""
        m = W.model()
        obj, _a = self.build(m)
        self.assertEqual(obj["envelope_daily"]["rows"], m["tables"]["envelope_daily"]["rows"])
        self.assertEqual(obj["alloc_daily"]["rows"], m["tables"]["alloc_daily"]["rows"])
        for bm, mm in zip(obj["summary"]["months"], m["months"], strict=True):
            self.assertEqual(bm["month"], mm["m"])
            self.assertEqual(bm["mm"], mm["mm"])                              # 같은 정수 ÷ 같은 분모 — 소수점까지
            self.assertEqual((bm["envelope_min"], bm["attributed_min"], bm["by_tag"]),
                             (mm["env_min"], mm["attributed_min"], mm["by_tag"]))
            self.assertEqual((bm["workdays"], bm["covered_workdays"], bm["absence_days"]),
                             (mm["workdays"], mm["covered_workdays"], mm["absence_days"]))
            self.assertEqual(bm["avail_days"], bm["covered_workdays"] - bm["absence_days"])   # TAB 식(모델 0.25 일 아님)
            self.assertAlmostEqual(bm["load_pct"], bm["envelope_min"] / (480 * bm["avail_days"]) * 100, places=9)
        env = sum(sum(r[1:]) for r in obj["envelope_daily"]["rows"])
        al = sum(r[3] for r in obj["alloc_daily"]["rows"])
        self.assertEqual(obj["integrity"], {"envelope_min": env, "alloc_min": al, "unattributed_min": env - al,
                                            "rows_env": len(obj["envelope_daily"]["rows"]),
                                            "rows_alloc": len(obj["alloc_daily"]["rows"]), "units": 6})

    def test_w411_unit_mapping(self):
        obj, _a = self.build()
        u1, u3, u4, u6 = self.unit(obj, 1), self.unit(obj, 3), self.unit(obj, 4), self.unit(obj, 6)
        self.assertIsNone(self.unit(obj, 7))                                  # 미착수(Z)·투입 0 은 올리지 않는다
        self.assertEqual(u1["start"], {"kind": "S1i", "at": "2026-08-03T09:00:00+09:00", "precision": "minute"})
        self.assertEqual(u1["end"], {"kind": "E1o", "at": "2026-08-14T17:00:00+09:00", "precision": "minute"})
        self.assertEqual((u1["grade"], u1["status"], u1["lead_time_h"]), ("A", "closed", 272.0))
        self.assertEqual((u3["grade"], u3["status"], u3["end"]["kind"], u3["end"]["precision"]),
                         ("D", "estimated", "E3i", "none"))
        self.assertEqual((u4["grade"], u4["status"], u4["lead_time_h"]), ("C", "open", None))     # O → SG[S2p]
        self.assertEqual(u4["end"], {"kind": None, "at": None, "precision": "none"})
        self.assertEqual(u4["start"]["kind"], "S2")
        self.assertEqual((u6["grade"], u6["start"]["kind"], u6["end"]["kind"]), ("M", "M", "M"))
        rows = obj["alloc_daily"]["rows"]
        for u in obj["units"]:
            self.assertEqual(u["effort_min"], sum(r[3] for r in rows if r[1] == u["unit_id"]))
            days = sorted({date.fromisoformat(r[0]) for r in rows if r[1] == u["unit_id"]})
            leads = [s for s in u["spans"] if s[2] == "lead"]
            self.assertEqual(len(leads), 1)
            self.assertLessEqual(leads[0][0], days[0].isoformat())
            self.assertGreaterEqual(leads[0][1], days[-1].isoformat())
            self.assertEqual([(s[0], s[1]) for s in u["spans"] if s[2] == "active"],
                             [(a.isoformat(), b.isoformat()) for a, b in S.active_spans(days, 2)])
        self.assertEqual([s for s in u1["spans"] if s[2] == "active"],
                         [["2026-08-03", "2026-08-06", "active"], ["2026-08-10", "2026-08-14", "active"]])

    def test_apps_catalog_only_unknown_as_minutes(self):
        """TAB R-9: 카탈로그 앱 ID 만(24자 이하), 미상·사내 도구 이름은 분 합계로만."""
        obj, _a = self.build()
        u1, u2, u3 = self.unit(obj, 1), self.unit(obj, 2), self.unit(obj, 3)
        self.assertEqual((u1["apps"], u1["apps_unknown_min"]), (["excel"], 60))
        self.assertEqual((u2["apps"], u2["apps_unknown_min"]), (["excel"], 100))
        self.assertEqual((u3["apps"], u3["apps_unknown_min"]), (["kicad"], 50))
        raw = fsx.canon_bytes(obj)
        for name in (b"solverx", b"inhouse_tool", b"ansys_electronics_desktop"):
            self.assertNotIn(name, raw)
        self.assertEqual(obj["catalog_proposals"], [])

    def test_catalog_proposals_opt_in(self):
        c = W.cfg(**{"team.shareUnknownApps": True})
        obj, _a = self.build(cfg=c, env=self.w.env(c))
        u1_days = {r[0] for r in obj["alloc_daily"]["rows"] if r[1] == W.U[1]}
        self.assertEqual(obj["catalog_proposals"], [{"exe": "solverx.exe", "company": "", "product": "",
                                                     "n_days": len(u1_days), "minutes": 60}])
        self.assertEqual([e for e in S.validate_team_bundle(obj, registry=W.registry(), side="client") if e.blocking], [])

    def test_member_id_and_self_label(self):
        c = W.cfg(**{"team.memberId": "M003", "team.selfLabel": "팀원A"})
        obj, _a = self.build(cfg=c, env=self.w.env(c))
        self.assertEqual((obj["person"]["member_id"], obj["person"]["self_label"]), ("M003", "팀원A"))
        c = W.cfg(**{"team.memberId": "X17", "team.selfLabel": "WP34-TESTPC 자리"})
        env = self.w.env(c)
        obj, audit = self.build(cfg=c, env=env)
        self.assertEqual((obj["person"]["member_id"], obj["person"]["self_label"]), (None, ""))
        self.assertEqual(len(audit["warnings"]), 2)
        self.assertNotIn(b"WP34-TESTPC", fsx.canon_bytes(obj))

    def test_generic_title_mode(self):
        c = W.cfg(**{"team.unitTitleMode": "generic"})
        obj, _a = self.build(cfg=c, env=self.w.env(c))
        self.assertTrue(all(u["title_mode"] == "generic" and "단위업무 #" in u["title"] for u in obj["units"]))
        self.assertRegex(self.unit(obj, 1)["title"], r"^\S+·\S+ 단위업무 #\d+$")
        self.assertNotIn("전원부", json.dumps(obj, ensure_ascii=False))

    def test_size_blockers(self):
        c = W.cfg(**{"team.maxBundleMb": 1})
        self.assertEqual(B.size_blockers(b"x" * 1024, c), [])
        self.assertEqual(len(B.size_blockers(b"x" * (1024 * 1024 + 1), c)), 1)


class TestModelEquality(BuildCase):
    """RPT-12 · RP15: 묶음 workflows·agentic·peers·quality = 보고서 모델 값(같은 기간이면 그대로)."""

    def test_rpt12_workflows(self):
        m = W.model()
        obj, _a = self.build(m)
        wfs = m["workflows"]["roles"]
        self.assertEqual(sorted(w["role_id"] for w in obj["workflows"]), sorted([W.RA, W.RB, W.RC, W.RD]))
        for w in obj["workflows"]:
            mw = wfs[w["role_id"]]
            self.assertEqual([s["no"] for s in w["steps"]], [s["no"] for s in mw["steps"]])
            for s, ms in zip(w["steps"], mw["steps"], strict=True):
                self.assertEqual((s["type"], s["n"], s["median_min"], s["agent_grade"], s["subagent"]),
                                 (ms["code"], ms["n"], ms["median_min"], ms["agent_grade"], ms["subagent"]))
                self.assertEqual(s["why"], [x for x in ms["why"] if x in S.WHY])
                self.assertEqual((s["wait_in_median_min"], s["work_share"]), (ms["wait_in_median_min"], ms["work_share"]))
                self.assertEqual(s["sample"], mw["sample"])
            want = sorted({(e[0], e[1]): e for e in mw["edges"] + mw["edges_rest"]}.values(),
                          key=lambda e: (-e[2], e[0], e[1]))
            self.assertEqual(w["edges"], [list(e) for e in want])
        ra = next(w for w in obj["workflows"] if w["role_id"] == W.RA)
        self.assertEqual([s["label"] for s in ra["steps"]], ["의뢰 수신", "전원 해석 수행", "결과 표 정리", "보고 발신"])
        self.assertEqual([s["bottleneck"] for s in ra["steps"]], ["", "work", "wait", ""])
        self.assertEqual(ra["units"], sorted([W.U[1], W.U[2], W.U[4]]))

    def test_rpt12_agentic(self):
        m = W.model()
        obj, _a = self.build(m)
        ag = obj["agentic"]
        inb = {u["unit_id"] for u in obj["units"]}
        want = sorted(({"agent_id": x["agent_id"], "role_id": x["role_id"], "step_type": x["step_type"],
                        "grade": x["grade"], "units": sorted(set(x["units"]) & inb)}
                       for x in m["team"]["agentic_matches"] if x["agent_id"].startswith("AG")),
                      key=lambda x: (x["agent_id"], x["role_id"], x["step_type"]))
        self.assertEqual(ag["matches"], want)
        self.assertNotIn(W.U[7], json.dumps(ag))
        self.assertEqual([(n["need_id"], n["label"], n["grade"], n["freq_per_month"], n["src"]) for n in ag["needs"]],
                         sorted([(n["need_id"], n["label"], n["grade"], n["freq_per_month"],
                                  "ai" if n["by"] == "ai" else "rule") for n in m["agentic"]["needs"] if not n["dropped"]]))
        subs = {s["role_id"]: s for s in ag["subagents"]}
        self.assertEqual({k: v["fit"] for k, v in subs.items()}, {W.RA: "조건부", W.RB: "부적합"})
        self.assertEqual(subs[W.RA]["chain"], [{"step_no": 3, "proposal": "결과 표 정리 단계 보조"},
                                               {"step_no": 4, "proposal": "보고 발신 단계 보조"}])
        self.assertEqual(ag["catalog_version"], "ag-1")

    def test_rpt12_peers_and_quality(self):
        m = W.model()
        obj, audit = self.build(m)
        book = {}
        env = self.w.env(self.cfg)
        for ref, _who, addr in (("1", W.KIM, "user01@" + W.INTERNAL), ("2", W.PEER2, "user02@" + W.INTERNAL)):
            k, scope = P.peer_key(W.PEPPER, addr, [W.INTERNAL], env.keyring)
            row = next(p for p in m["peers"]["internal"] if p["ref"] == int(ref))
            book[k] = (scope, row["units"], row["shared_effort_min"])
        got = {p["peer_key"]: (p["scope"], p["units"], p["shared_effort_min"]) for p in obj["peers"]}
        self.assertEqual(got, book)
        self.assertEqual(obj["peers_external"], m["peers"]["external"])
        self.assertEqual(obj["quality"]["grade"], m["quality"]["grade"])
        self.assertEqual(obj["quality"]["reasons"], m["quality"]["reasons"] + ["peer_unresolved:1"])
        self.assertEqual(obj["quality"]["confirm_queue"], {"open": 1, "resolved": 1})
        self.assertEqual(obj["quality"]["team_text_rejected"], audit["team_text_rejected"])
        self.assertEqual(obj["person"]["self_peer_key"], P.peer_key(W.PEPPER, "me@" + W.INTERNAL, [W.INTERNAL],
                                                                    env.keyring)[0])


class TestDeterminism(BuildCase):
    def test_u02_same_bytes_and_order_independent(self):
        """U02: 같은 입력(built_at 고정) → 같은 바이트. 모델 목록 순서를 섞어도 같다."""
        a, _ = self.build()
        b, _ = self.build()
        self.assertEqual(fsx.canon_bytes(a), fsx.canon_bytes(b))
        m = W.model()
        for k in ("units", "projects", "proposals", "roles", "queue", "days"):
            m[k] = list(reversed(m[k]))
        m["tables"]["envelope_daily"]["rows"].reverse()
        m["tables"]["alloc_daily"]["rows"].reverse()
        m["agentic"]["needs"].reverse()
        m["team"]["agentic_matches"].reverse()
        m["team"]["subagents"].reverse()
        c, _ = self.build(m)
        self.assertEqual(fsx.canon_bytes(a), fsx.canon_bytes(c))


class TestPeriods(BuildCase):
    def test_sub_period_one_month(self):
        m = W.model()
        p = {"from": "2026-09-01", "to": "2026-09-30"}
        obj, _a = self.build(m, period=p)
        self.assertEqual(obj["period"]["months"], ["2026-09"])
        sep = next(x for x in m["months"] if x["m"] == "2026-09")
        s = obj["summary"]["months"][0]
        self.assertEqual((s["covered_workdays"], s["absence_days"], s["envelope_min"], s["mm"]),
                         (sep["covered_workdays"], sep["absence_days"], sep["env_min"], sep["mm"]))
        self.assertEqual(sorted(u["unit_id"] for u in obj["units"]), sorted(W.U[n] for n in (2, 3, 4, 5, 6)))
        self.assertTrue(all(r[0] >= "2026-09-01" for r in obj["alloc_daily"]["rows"]))
        kim = P.peer_key(W.PEPPER, "user01@" + W.INTERNAL, [W.INTERNAL], None)[0]
        row = next(x for x in obj["peers"] if x["peer_key"] == kim)
        sep_eff = {u["unit_id"]: u["effort_min"] for u in obj["units"]}
        self.assertEqual((row["units"], row["shared_effort_min"]), (2, sep_eff[W.U[2]] + sep_eff[W.U[5]]))
        self.assertEqual(list(S.validate_team_bundle(obj, registry=W.registry(), side="client",
                                                          calendar=W.cal())), [])

    def test_partial_month_recounted_from_days(self):
        p = {"from": "2026-08-10", "to": "2026-09-30"}
        obj, _a = self.build(period=p)
        aug = obj["summary"]["months"][0]
        self.assertEqual(aug["covered_workdays"], len(W.workdays("2026-08-10", "2026-08-31")))
        self.assertEqual((aug["absence_days"], aug["avail_days"]), (0.0, float(aug["covered_workdays"])))
        self.assertEqual(aug["workdays"], W.cal().month_workdays(2026, 8))      # 분모는 그 달 전체 근무일 그대로
        self.assertEqual(list(S.validate_team_bundle(obj, registry=W.registry(), side="client",
                                                          calendar=W.cal())), [])

    def test_refused_outside_analysis_no_file(self):
        it = B.build_and_queue(W.model(), {"from": "2026-07-01", "to": "2026-09-30"}, self.cfg, paths=self.w.paths,
                               now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 2)
        self.assertIn("분석", it.message)
        self.assertEqual(Q.list_items(paths=self.w.paths), [])
        m = W.model()
        m["run"]["as_of"] = "2026-09-10T18:00"
        it = B.build_and_queue(m, {"from": "2026-09-15", "to": "2026-09-30"}, self.cfg, paths=self.w.paths,
                               now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 2)
        self.assertIn("아직 분석되지 않았습니다", it.message)

    def test_refused_non_full_model(self):
        m = W.model()
        m["variant"] = "redacted"
        it = B.build_and_queue(m, PERIOD, self.cfg, paths=self.w.paths, now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 2)
        it = B.build_and_queue({"schema": "x"}, PERIOD, self.cfg, paths=self.w.paths, now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 2)
        it = B.build_and_queue(W.model(), {"from": "2026-09-30", "to": "2026-09-01"}, self.cfg, paths=self.w.paths,
                               now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 2)

    def test_analyzed_until_capped_at_period_end(self):
        obj, _a = self.build(period={"from": "2026-08-01", "to": "2026-08-31"})
        self.assertEqual(obj["period"]["analyzed_until"], "2026-08-31T23:59:59+09:00")


class TestBundleSide(BuildCase):
    """측정 품질 선택 필드(커버리지 원장·PC 표) · 정제 감사 기간 합계 · 만든 PC 라벨 · 감사 gate_team."""

    def test_quality_coverage_and_pcs(self):
        W.put_pc(self.w.paths)
        sep = W.workdays("2026-09-01", "2026-09-30")
        cells = []
        for i, d in enumerate(sep):
            cells.append(W.cell(d, "mail_out", "mail.com", "ok"))
            cells.append(W.cell(d, "pc", "pc.sampler", "ok", n=5, n_minute=5))
            if i < 10:
                cells.append(W.cell(d, "teams", "teams.uia", "ok", n=2, n_minute=1, n_date=1))
            if i < 5:
                cells.append(W.cell(d, "pc", "pc.events", "ok", n=1, n_minute=1))
        W.put_ledger(self.w.paths, cells)
        obj, _a = self.build()
        q = obj["quality"]
        cov = {c["axis"]: c for c in q["coverage"]}
        self.assertEqual(cov["mail_out"]["days"], {"ok": 20, "not_attempted": 20})
        self.assertEqual(cov["teams"]["days"], {"ok": 10, "not_attempted": 30})
        self.assertEqual(cov["pc"]["srcs"], ["pc.events", "pc.sampler"])
        self.assertEqual((cov["mail_out"]["exact_ratio"], cov["teams"]["exact_ratio"]), (1.0, 0.5))
        self.assertNotIn("cal", cov)                                          # 원장에 없는 축은 싣지 않는다
        self.assertEqual(q["pcs"], [{"ord": 1, "label_auto": "PC1", "kind": "desktop", "agent_impl": "py",
                                     "observed_days": 20, "event_days": 5,
                                     "probe": {"mail.com": "가능", "teams.uia": "불가(확정)"}}])
        self.assertEqual(list(S.validate_team_bundle(obj, registry=W.registry(), side="client")), [])
        env = self.w.env(self.cfg)
        self.assertEqual(env.built_on, "PC1")

    def test_no_ledger_omits_optional_quality(self):
        obj, _a = self.build()
        self.assertNotIn("coverage", obj["quality"])
        self.assertNotIn("pcs", obj["quality"])

    def test_privacy_counts_period_sum(self):
        W.put_audit(self.w.paths, [("2026-08-10T01:00:00Z", {"phone": 2, "person": 5}, {"ad": 3}),
                                   ("2026-09-02T01:00:00Z", {"person": 1, "money": 4}, {"ad": 1, "bad_raw": 2}),
                                   ("2026-07-15T01:00:00Z", {"phone": 9}, {}),
                                   ("2026-09-03T01:00:00Z", {"Bad Key": 3, "rate2": 1}, {})])
        obj, _a = self.build()
        self.assertEqual(obj["privacy_counts"], {"ad": 4, "bad_raw": 2, "money": 4, "person": 6, "phone": 2})

    def test_gate_team_audit_event(self):
        it = B.build_and_queue(W.model(), PERIOD, self.cfg, paths=self.w.paths, now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 0)
        root = Path(self.w.paths.privacy_audit_file("2026-01-01")).parent.parent
        evs = []
        for f in sorted(root.rglob("*.jsonl")):
            evs += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        gt = [e for e in evs if e.get("ev") == "gate_team"]
        self.assertEqual(len(gt), 1)
        self.assertEqual(gt[0]["out_sha256"], it.meta["sha256"])
        self.assertEqual((gt[0]["stage"], gt[0]["path_id"], gt[0]["pc_id"]), ("team", "team", W.PC_ID))
        self.assertEqual(gt[0]["dropped"], {"team_text": it.meta["check"]["team_text_rejected"]})
        self.assertEqual(gt[0]["err"].get("gate_team.peer_unresolved"), 1)
        raw = json.dumps(gt[0], ensure_ascii=False)
        self.assertNotIn("김철수", raw)
        self.assertNotIn(W.PEPPER, raw)


class TestRealReportModel(BuildCase):
    """WP-31 실물 보고서 모델(합성 3개월 실행 big_run) → 묶음이 공용 검증을 통과하고 월 MM 이 시간 코어 값과 같다."""

    def test_wp31_model_roundtrip(self):
        from lm27.report import model as M
        from tests.fixtures.wp30 import world as W30
        from tests.fixtures.wp31 import runs as R
        t = R.TmpRoot()
        try:
            run = R.big_run(24)
            run.write(t.paths)
            c30 = W30.cfg()
            m = M.build_model(run.inputs(t.paths, c30), c30, fallback=lambda *_a: None)
        finally:
            t.cleanup()
        p = {"from": m["run"]["from"], "to": m["run"]["to"]}
        obj, _a = self.build(m, period=p)
        errs = S.validate_team_bundle(obj, registry=W.registry(), side="client", calendar=W.cal())
        self.assertEqual([(e.path, e.code) for e in errs if e.blocking], [])
        for bm, mm in zip(obj["summary"]["months"], m["months"], strict=True):
            self.assertEqual((bm["mm"], bm["envelope_min"], bm["attributed_min"]), (mm["mm"], mm["env_min"],
                                                                                    mm["attributed_min"]))
        self.assertEqual(sum(u["effort_min"] for u in obj["units"]), obj["integrity"]["alloc_min"])


class TestFailClosed(BuildCase):
    def test_payload_violation_blocks_build_no_file(self):
        """마지막 검사 2단(P check_team_payload)에 걸리면 빌드 실패 rc 1 — 파일을 쓰지 않고 경로·코드만 알린다."""
        from lm27.privacy import Violation
        with mock.patch("lm27.privacy.check_team_payload", return_value=[Violation("units[0].title", "label:not_clean")]):
            it = B.build_and_queue(W.model(), PERIOD, self.cfg, paths=self.w.paths, now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 1)
        self.assertEqual(it.problems, ["units[0].title: label:not_clean"])
        self.assertEqual(Q.list_items(paths=self.w.paths), [])

    def test_bytes_guard_blocks(self):
        with mock.patch.object(S, "bytes_guard_hits", return_value=["email"]):
            with self.assertRaises(B.BuildFailed) as cm:
                self.build()
        self.assertEqual(cm.exception.problems, ["(bytes): email"])

    def test_outbox_paths_method_missing(self):
        """Paths.outbox_file(계약 C19) 가 아직 없으면 rc 1 + 한국어 한 줄(경로를 다른 곳에서 조립하지 않는다 — L-08)."""
        from lm27.paths import Paths

        class Bare(Paths):
            def calendar_json(self):
                return W.TREE / "config" / "calendar.json"
        bare = Bare(self.w.root, lad=os.path.join(self.w.root, "lad"))
        it = B.build_and_queue(W.model(), PERIOD, self.cfg, paths=bare, now=NOW, env=self.w.env(self.cfg))
        self.assertEqual(it.rc, 1)
        self.assertIn("outbox_file", it.message)


if __name__ == "__main__":
    unittest.main()
