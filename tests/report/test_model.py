# -*- coding: utf-8 -*-
"""WP-31 보고서 모델(R §9.2 · 계약 §3.16 · G-R2 · RPT-10 · RPT-13 · RPT-18 · X-281 · T-05).

모델 등식: 날·달 `obs + est + unattr = env` · `attributed + unattr = env` · `Σ buckets = unattr` · 달 env = Σ 날짜 = 봉투 표 ·
단위업무 `effort = Σ alloc` · `obs + est = effort` — 실제 분석에서도 상시 검사(실패하면 ModelCheckError, 이전 보고서 유지).
키는 정수 참조(`refs`)로만 싣는다(R §9.2.2).
"""
from __future__ import annotations

import copy
import unittest
from collections import Counter

from lm27.report import fmt as F
from lm27.report import model as M
from lm27.time.calendar import TAGS
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


def build(run, cfg=None, t=None, **kw):
    """합성 실행 → 입력(파일 경유) → 모델."""
    own = t is None
    t = t or R.TmpRoot()
    try:
        run.write(t.paths)
        c = cfg or W.cfg()
        inp = run.inputs(t.paths, c, **kw)
        return M.build_model(inp, c, fallback=no_fallback), inp
    finally:
        if own:
            t.cleanup()


class ModelEquationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srun = R.rich_run()
        cls.m, cls.inp = build(cls.srun)

    def test_shape(self):
        m = self.m
        self.assertEqual((m["schema"], m["schema_version"], m["variant"]), ("lm27.report", "1.0", "full"))
        self.assertEqual(m["generator"]["report_version"], "report/1")
        for k in ("generator", "run", "flags", "denominator", "domains", "months", "days", "projects", "roles", "units",
                  "tree", "workflows", "reviews", "peers", "ontology", "agentic", "subagent", "queue", "quality",
                  "tables", "team", "refs", "proposals"):
            self.assertIn(k, m)
        self.assertEqual(m["run"]["tz_offset_min"], 540)
        self.assertEqual(m["run"]["period_source"], "explicit")          # RPT-04: 기간 출처를 머리 띠로
        self.assertEqual((m["run"]["from"], m["run"]["to"], m["run"]["as_of"]), ("2026-08-01", "2026-10-04",
                                                                                "2026-10-04T18:00"))
        self.assertEqual(m["denominator"]["text_ko"], "1MM = 8시간 × 그 달 근무일(주말·공휴일·회사 휴무 제외)")
        self.assertNotIn("built_at", m)                              # meta 에만(G-R1)
        self.assertEqual(M.check_model(m), [])

    def test_month_equations_against_tables(self):
        """RPT-10: 달 env = 봉투 표 그 달 합(팀 재합산과 같은 원천) · 등식 · fmt_mm 문자열(T-05)."""
        env = Counter()
        alloc = Counter()
        for row in self.srun.tables["envelope_daily"]["rows"]:
            env[row[0][:7]] += sum(row[1:])
        for row in self.srun.tables["alloc_daily"]["rows"]:
            alloc[row[0][:7]] += row[3]
        self.assertEqual([x["m"] for x in self.m["months"]], ["2026-08", "2026-09", "2026-10"])
        for x in self.m["months"]:
            self.assertEqual(x["env_min"], env[x["m"]])
            self.assertEqual(x["attributed_min"], alloc[x["m"]])
            self.assertEqual(x["attributed_min"] + x["unattr_min"], x["env_min"])
            self.assertEqual(x["obs_min"] + x["est_min"], x["attributed_min"])
            self.assertEqual(sum(x["buckets"].values()), x["unattr_min"])
            wd = self.srun.w.cal.month_workdays(int(x["m"][:4]), int(x["m"][5:]))
            self.assertEqual(x["denom_min"], 480 * wd)
            team_mm = F.fmt_mm(env[x["m"]], 480 * wd)              # 팀이 정수 분 표로 다시 계산한 표시
            self.assertEqual(F.fmt_mm(x["env_min"], x["denom_min"]), team_mm)
            if x["mm"] is not None:
                self.assertLessEqual(abs(x["mm"] - env[x["m"]] / (480 * wd)), 1e-9)
        self.assertTrue(self.m["flags"]["buckets_exact"])
        sep = next(x for x in self.m["months"] if x["m"] == "2026-09")
        self.assertEqual(sep["buckets"]["B_GENERIC"], 60)
        self.assertEqual(sep["buckets"]["B_MEET"], 30)

    def test_days_and_buckets_daily(self):
        bd = Counter()
        for d, _b, _t, v in self.m["tables"]["buckets_daily"]["rows"]:
            bd[d] += v
        for x in self.m["days"]:
            self.assertEqual(x["obs_min"] + x["est_min"] + x["unattr_min"], x["env_min"])
            self.assertEqual(bd.get(x["d"], 0), x["unattr_min"])
        self.assertEqual(self.m["days"][0]["d"], "2026-08-01")
        self.assertEqual(self.m["days"][-1]["d"], "2026-10-04")
        self.assertTrue(next(x for x in self.m["days"] if x["d"] == "2026-09-05")["hol"])    # 토요일
        self.assertEqual(next(x for x in self.m["days"] if x["d"] == "2026-09-02")["flags"], ["Q08"])

    def test_months_partial_and_load(self):
        oct_ = next(x for x in self.m["months"] if x["m"] == "2026-10")
        self.assertEqual(oct_["partial"]["from"], "2026-10-01")
        self.assertEqual(oct_["partial"]["to"], "2026-10-04")
        sep = next(x for x in self.m["months"] if x["m"] == "2026-09")
        self.assertIsNone(sep["partial"])
        self.assertEqual(sep["avail_min"], 480 * sep["covered_workdays"])
        self.assertEqual(sep["load_pct"], F.ratio(sep["env_min"] * 100, sep["avail_min"], 2))
        self.assertEqual(sep["overtime_window_min"], sep["env_min"] - sep["by_tag"]["regular"])
        self.assertEqual(sep["units"]["finished"], 4)               # u_a1·u_a2·u_a3·u_b1(u_a4 는 10-02 끝)
        self.assertIn(sep["quality"]["grade"], ("reliable", "caution", "unreliable"))

    def test_units(self):
        alloc = Counter()
        for row in self.srun.tables["alloc_daily"]["rows"]:
            alloc[row[1]] += row[3]
        refs = self.m["refs"]
        for u in self.m["units"]:
            self.assertEqual(u["effort_min"], alloc[u["unit_id"]])
            self.assertEqual(u["obs_min"] + u["est_min"], u["effort_min"])
            self.assertEqual(sum(u["by_month"].values()), u["effort_min"])
            self.assertEqual(sum(u["by_tag"].values()), u["effort_min"])
            dens = sum(v["obs"] + v["est"] for v in u["density"].values())
            self.assertEqual(dens, u["effort_min"])
            self.assertEqual([s[2] for s in u["spans"]].count("lead"), 1)
            for r in u["peers"]:
                self.assertIn(str(r), refs["people"])
            for r in u["docs"]:
                self.assertIn(str(r), refs["docs"])
        u1 = next(u for u in self.m["units"] if u["unit_id"] == "u_a1")
        self.assertEqual(u1["start"], {"kind": "S1i", "at": "2026-09-01T09:30", "precision": "exact"})
        self.assertEqual(u1["end"]["kind"], "E1o")
        self.assertEqual(u1["steps"][0], "REQ_IN")
        self.assertEqual(u1["title"], "전원부 해석 1")
        self.assertEqual(u1["queue"], [])
        self.assertEqual(sorted(u1["peers"]), [1, 2, 3])
        self.assertEqual(u1["apps"][0][0], "cae_x")
        a0 = self.m["units"][0]
        self.assertEqual(a0["unit_id"], "u_a0")                        # 첫 차수 시작 순(R §9.2.2)
        self.assertIn("9f2c01ab3e4d", a0["queue"])

    def test_refs_are_ints_not_keys(self):
        m = self.m
        people = m["refs"]["people"]
        self.assertEqual(sorted(people), ["1", "2", "3"])
        self.assertEqual(people["1"]["key"], R.KIM)
        for p in m["peers"]["internal"]:
            self.assertEqual(p["k"], p["ref"])
            self.assertNotIn("key", p)
        self.assertEqual(m["peers"]["external"]["customer"], 1)
        for n in m["ontology"]["nodes"]:
            self.assertNotIn("key", n)
            if n["type"] in ("C", "D") and not n["id"].startswith(("etc:", "c:ext:")):
                self.assertRegex(n["id"], r"^[cd]:\d+$")
        for rv in m["reviews"]["months"]:
            for p in rv["peers_top"]:
                self.assertIsInstance(p["ref"], int)
            for e in (rv.get("edge_refs") or {}).values():
                self.assertNotRegex(e["from"] + e["to"], r"[wd][0-9a-f]{16}")
        # 키 문자열은 refs·cycles 근거 키·queue 근거 키(전체판 로컬 전용) 밖에 없다
        rest = {k: v for k, v in m.items() if k not in ("refs", "units", "queue")}
        self.assertNotRegex(M.model_bytes(rest).decode("utf-8"), r"(?<![0-9a-z])[wd][0-9a-f]{16}")

    def test_tree_unattributed(self):
        """RPT-13: 근무 중 미분류(버킷 5종) 행이 늘 있고, 버킷 분은 과제 분에 더해지지 않는다."""
        tr = self.m["tree"]
        self.assertEqual(tr["order"][-1], "UNATTR")
        self.assertEqual(tr["nodes"]["UNATTR"]["children"], list(M.BUCKETS))
        tot_unattr = sum(x["unattr_min"] for x in self.m["months"])
        self.assertEqual(tr["nodes"]["UNATTR"]["min_total"], tot_unattr)
        self.assertEqual(sum(tr["nodes"][b]["min_total"] for b in M.BUCKETS), tot_unattr)
        p = tr["nodes"]["P-0007"]
        self.assertEqual(p["min_total"], sum(u["effort_min"] for u in self.m["units"] if u["project_key"] == "P-0007"))
        self.assertIn("UNC", tr["nodes"])
        self.assertEqual(tr["nodes"]["DEV"]["children"], ["P-0007"])
        rid = next(u["role_id"] for u in self.m["units"] if u["unit_id"] == "u_a1")
        self.assertEqual(tr["nodes"][rid]["parent"], "P-0007")
        self.assertIn(tr["nodes"][rid]["bottleneck"], ("wait:3|work:2", "work:2|wait:3", "wait:3", "work:2", "thin", ""))

    def test_projects_roles_queue(self):
        p = next(x for x in self.m["projects"] if x["key"] == "P-0007")
        self.assertEqual(p["label"], "과제A")
        self.assertEqual(p["domain"], "DEV")
        self.assertTrue(all(r["label"] == f"{r['field_name']} · {r['function_name']}" for r in self.m["roles"]))
        q = self.m["queue"]
        self.assertEqual([x["code"] for x in q], ["Q01", "Q09", "H05"])     # 영향 분 순
        self.assertEqual({x["kind"] for x in q}, {"time", "hier"})
        self.assertEqual(q[0]["week"], "2026-W36")
        self.assertEqual(q[0]["proposal"]["note"], "근거 1건")
        self.assertEqual(q[0]["why_ko"], "[과제:P-0007] 전원부 검증 요청")       # 근거 키 → 정제 제목(전체판만)

    def test_team_parts(self):
        """RP15: 팀 묶음 빌더가 고를 재료(정수 분 표·agentic 펼침·서브에이전트 체인)가 모델에 있다."""
        m = self.m
        self.assertEqual(m["tables"]["alloc_daily"]["rows"], self.srun.tables["alloc_daily"]["rows"])
        self.assertEqual(m["tables"]["envelope_daily"]["rows"], self.srun.tables["envelope_daily"]["rows"])
        self.assertEqual({s["role_id"] for s in m["team"]["subagents"]}, set(m["workflows"]["roles"]))
        self.assertTrue(all(set(x) == {"agent_id", "role_id", "step_type", "grade", "units"}
                            for x in m["team"]["agentic_matches"]))


class ModelCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, _ = build(R.rich_run())

    def test_detects_violations(self):
        m = copy.deepcopy(self.m)
        m["months"][1]["env_min"] += 5
        m["units"][0]["effort_min"] += 1
        m["days"][3]["obs_min"] = -1
        m["months"][0]["buckets"]["B_COMM"] += 2
        probs = M.check_model(m)
        self.assertTrue(any(p.startswith("months[2026-09].env_min") for p in probs))
        self.assertTrue(any("effort_min" in p and "Σalloc" in p for p in probs))
        self.assertTrue(any("정수 분" in p for p in probs))
        self.assertTrue(any("Σbuckets" in p for p in probs))

    def test_alloc_over_envelope(self):
        m = copy.deepcopy(self.m)
        row = m["tables"]["alloc_daily"]["rows"][0]
        row[3] += 10_000
        self.assertTrue(any("Σalloc" in p and "> envelope" in p for p in M.check_model(m)))

    def test_build_refuses_inconsistent_tables(self):
        """G-R2: 실분석에서도 등식 실패 = 보고서를 만들지 않는다(ModelCheckError)."""
        run = R.rich_run()
        run.tables["alloc_daily"]["rows"].append(["2026-09-01", "u_zzzzzzzzzz", "regular", 5])
        with self.assertRaises(M.ModelCheckError) as cm:
            build(run)
        self.assertTrue(any("u_zzzzzzzzzz" in p for p in cm.exception.problems))

    def test_fit_size(self):
        """X-281: 모델 상한을 넘으면 runs 요약 → 다른 과제 그래프 → 대기·점 목록 순으로 줄이고 등식은 그대로."""
        m = copy.deepcopy(self.m)
        out, trimmed = M.fit_size(m, 10)
        self.assertEqual(trimmed[0], "단위업무 구간(runs) 요약")
        self.assertIn("단위업무 대기·점 목록", trimmed)
        uw = out["workflows"]["units"]["u_a1"]
        self.assertTrue(uw["runs_summarized"])
        self.assertEqual({r["type"] for r in uw["runs"]}, {"APP_CAE", "COMM", "DOC_XLS", "DOC_DOC", "MEET"})
        self.assertEqual(M.check_model(out), [])
        same, none = M.fit_size(copy.deepcopy(self.m), 1 << 40)
        self.assertEqual(none, [])
        self.assertEqual(M.model_bytes(same), M.model_bytes(self.m))


class ModelVariantsTest(unittest.TestCase):
    def test_coarse_without_obs(self):
        """RPT-18: attrib 에 obs 열이 없으면 거친 단계 + mining_coarse 경고(화면·품질 사유)."""
        run = R.rich_run()
        orig = run.w.attrib_rows

        def rows():
            out = orig()
            for r in out:
                r.pop("obs", None)
            return out
        run.w.attrib_rows = rows
        m, _ = build(run)
        self.assertTrue(m["flags"]["mining_coarse"])
        self.assertIn("mining_coarse", {w["code"] for w in m["flags"]["warnings"]})
        self.assertIn("mining_coarse", m["quality"]["reasons"])
        self.assertEqual(M.check_model(m), [])

    def test_mm_month_mismatch_warns(self):
        run = R.rich_run()
        run.mm = R.mm_rows(run.w, run.tables, run.buckets, mm_buckets_ok=False)
        m, _ = build(run)
        self.assertIn("mm_month_mismatch", {w["code"] for w in m["flags"]["warnings"]})
        for x in m["months"]:
            self.assertEqual(sum(x["buckets"].values()), x["unattr_min"])

    def test_ai_labels_and_overrides(self):
        run = R.rich_run()
        m0, _ = build(run)
        rid = next(u["role_id"] for u in m0["units"] if u["unit_id"] == "u_a1")
        codes = [s["code"] for s in m0["workflows"]["roles"][rid]["steps"]]
        ans = {"role": "회로 해석 담당", "summary": "의뢰를 받아 해석합니다.",
               "steps": [{"s": f"S{i + 1}", "type": c, "label": f"라벨{i + 1}", "desc": ""} for i, c in enumerate(codes)]}
        run.ai = {"workflow_label": {"schema": 1, "stage": "workflow_label", "stage_ver": "workflow_label/1.0",
                                     "items": {"ws:" + rid: {"ans": ans, "by": "ai"}}}}
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        need = (m0["agentic"]["needs"] or [{"need_id": "n_000000"}])[0]["need_id"]
        from lm27.util.fsx import atomic_write, canon_bytes
        atomic_write(t.paths.team_overrides(), canon_bytes({"needs": {need: "drop"}}))
        m, _ = build(run, t=t)
        steps = m["workflows"]["roles"][rid]["steps"]
        self.assertEqual([s["label_by"] for s in steps], ["ai"] * len(steps))
        self.assertEqual(steps[0]["label"], "라벨1")
        self.assertEqual(m["workflows"]["roles"][rid]["ai_role"], "회로 해석 담당")
        self.assertEqual(m["flags"]["copilot"], "partial")
        self.assertEqual(m["generator"]["stage_versions"]["workflow_label"], "workflow_label/1.0")
        self.assertGreater(m["flags"]["label_sources"]["workflow_label"]["ai"], 0)
        for n in m["agentic"]["needs"]:
            self.assertEqual(n["dropped"], n["need_id"] == need)

    def test_no_units(self):
        """단위업무 0개: 빈 절 + 경고(R §11), 등식은 그대로(봉투 = 미귀속)."""
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        w.bucket("B_GENERIC", "2026-09-02", "09:00", "11:00")
        run = R.SynthRun(w)
        m, _ = build(run)
        self.assertEqual(m["units"], [])
        self.assertIn("units_empty", {x["code"] for x in m["flags"]["warnings"]})
        sep = m["months"][0]
        self.assertEqual(sep["env_min"], 120)
        self.assertEqual(sep["unattr_min"], 120)
        self.assertEqual(sep["buckets"]["B_GENERIC"], 120)
        self.assertEqual(M.check_model(m), [])
        self.assertEqual(set(TAGS), set(sep["by_tag"]))


if __name__ == "__main__":
    unittest.main()
