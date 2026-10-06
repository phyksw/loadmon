# -*- coding: utf-8 -*-
"""WP-27 취합 — 월 단일 출처·개인=팀·측정 품질·달력·연결·손상·병합 사슬·2026 근무일 관문(TAB §4 · A02~A06 · A08~A10 · A12,
TAB-I1~I7, 계약 T-13). 합성 묶음만, 저장소는 임시 폴더.
"""
import json
import os
import unittest
from pathlib import Path

from lm27.team import aggregate as A
from lm27.util import fsx
from tests.fixtures.wp27 import bundles as B

PK1, PK2, PK3 = B.person_key(1), B.person_key(2), B.person_key(3)
VERIFIED = Path(B.TREE) / "tests" / "fixtures" / "wp02" / "calendar_verified_counts.json"


def _sm(b, m):
    return next(x for x in b["summary"]["months"] if x["month"] == m)


class AggCase(unittest.TestCase):
    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self.st = B.new_store(self.dir)

    def tearDown(self):
        self._td.__exit__(None, None, None)

    def put(self, obj):
        r = B.put_bundle(self.st, obj)
        self.assertTrue(r.ok, (r.code, r.detail))
        return r

    def agg(self, gen=1):
        res = A.aggregate(self.st, gen)
        self.assertTrue(res.ok, res.warnings)
        return res

    def person(self, td, pk):
        return next(p for p in td["people"] if p["person_key"] == pk)


class TestOverlapAndPersonEqTeam(AggCase):
    def test_a02_overlap_one_source_later_build(self):
        """A02: 7–9월(10/1 빌드)·9–11월(10/5 까지·10/5 빌드) — 9월은 한 번만(동률 20 → 나중 빌드)."""
        a = B.make_bundle(PK1, "2026-07-01", "2026-09-30", built_at="2026-10-01T09:00:00+09:00", seed=1)
        b = B.make_bundle(PK1, "2026-09-01", "2026-11-30", until="2026-10-05", built_at="2026-10-05T09:00:00+09:00",
                          seed=2)
        self.put(a)
        self.put(b)
        res = self.agg()
        p = self.person(res.td, PK1)
        months = {e["m"]: e for e in p["months"]}
        self.assertEqual(sorted(months), ["2026-07", "2026-08", "2026-09", "2026-10"])   # 11월 = 자료 없음(0 아님)
        sha_b = B.sha(B.canon(b))[:12]
        self.assertEqual(months["2026-09"]["src12"], sha_b)
        naive = _sm(a, "2026-09")["mm"] + _sm(b, "2026-09")["mm"]
        self.assertAlmostEqual(months["2026-09"]["mm"], _sm(b, "2026-09")["mm"], delta=1e-12)
        self.assertGreater(naive, months["2026-09"]["mm"] * 1.5)                          # 이중 계상 없음
        self.assertEqual(months["2026-10"]["partial"], {"covered_workdays": 2, "workdays": 20})   # A08 부분월
        self.assertAlmostEqual(months["2026-10"]["mm"], months["2026-10"]["env_min"] / (480 * 20), delta=1e-15)
        mv = {m["person_key"]: m for m in self.st.members_view(res.td)["members"]}
        used = {x["sha12"]: x["used_months"] for x in mv[PK1]["periods"]}
        self.assertEqual(used[sha_b], ["2026-09", "2026-10"])

    def test_person_eq_team_and_invariants(self):
        """T-05·A01 축소판: 사람·달 MM = 묶음 요약 MM(|Δ|≤1e-9), 영역 합 + 미귀속 = 사람 MM, 경고 0(I1~I7)."""
        a = B.make_bundle(PK1, "2026-07-01", "2026-08-31", built_at="2026-09-01T09:00:00+09:00")
        b = B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", project="P-0002",
                          domain="MP", field="MECH", func="TEST")
        self.put(a)
        self.put(b)
        res = self.agg()
        td = res.td
        self.assertFalse([w for w in res.warnings if w.startswith("I")], res.warnings)
        for pk, bd in ((PK1, a), (PK2, b)):
            for e in self.person(td, pk)["months"]:
                self.assertLessEqual(abs(e["mm"] - _sm(bd, e["m"])["mm"]), 1e-9)
                self.assertEqual(e["env_min"], _sm(bd, e["m"])["envelope_min"])
                self.assertEqual(e["by_tag"], _sm(bd, e["m"])["by_tag"])
                self.assertNotIn("mm_bundle", e)
        for m in td["months"]:
            team = sum(e["mm"] for p in td["people"] for e in p["months"] if e["m"] == m)
            tree = sum(d["by_month"].get(m, {}).get("mm", 0) for d in td["domains"]) + td["unattributed"]["by_month"][m]
            self.assertLessEqual(abs(team - tree), 1e-9)
        dom = {d["code"]: d for d in td["domains"]}
        self.assertGreater(dom["MP"]["total_mm"], 0)
        self.assertEqual(td["schema"], "lm27.teamdata/1")
        self.assertEqual(td["workdays"], {"2026-07": 22, "2026-08": 20})
        files = sorted(os.listdir(self.st.gen_dir(1)))
        # W1 통합 창: 팀 보고서 렌더러(WP-37 lm27.team.report)가 생겨 보고서 두 벌도 같은 세대에 쓴다
        self.assertEqual(files, ["details.json", "result.json", "team_data.json", "team_report.html",
                                 "team_report_share.html"])
        self.assertEqual(json.loads(fsx.read_bytes(self.st.gen_dir(1) / "result.json"))["members"], 2)

    def test_raw_values_not_rounded(self):
        """반올림은 표시 때만 — team_data 의 MM·로드는 정수 분에서 한 번 나눈 원값."""
        a = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", absence_days=1.0)
        self.put(a)
        e = self.person(self.agg().td, PK1)["months"][0]
        self.assertEqual(e["mm"], e["env_min"] / (480 * 22))
        self.assertEqual(e["avail_days"], 21.0)
        self.assertEqual(e["load_pct"], e["env_min"] / (480 * 21.0) * 100)

    def test_people_index_order(self):
        small = B.make_bundle(PK1, "2026-07-01", "2026-07-10", built_at="2026-08-01T09:00:00+09:00")
        big = B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00")
        self.put(small)
        self.put(big)
        td = self.agg().td
        self.assertEqual([p["person_key"] for p in td["people"]], [PK2, PK1])
        self.assertEqual([p["i"] for p in td["people"]], [0, 1])


class TestQualityCalendar(AggCase):
    def test_a04_unreliable_in_total_out_of_comparison(self):
        good = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00")
        bad = B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", grade="unreliable",
                            field="MECH")
        self.put(good)
        self.put(bad)
        td = self.agg().td
        i_bad = self.person(td, PK2)["i"]
        self.assertEqual(td["quality"]["excluded_from_comparison"], [i_bad])
        dev = next(d for d in td["domains"] if d["code"] == "DEV")
        self.assertIn(i_bad, [i for i, _v in dev["by_month"]["2026-07"]["by_person"]])      # 합계 포함
        cells = {(c[0], c[1]): c for c in td["role_matrix"]["cells"]}
        self.assertIsNone(cells[("MECH", "DESIGN")][3] or None)                               # 분포 비율 제외(0)
        self.assertEqual(cells[("ELEC", "DESIGN")][3], 1.0)
        self.assertNotIn(i_bad, [x["i"] for x in td["units_stats"]["lead_points"]])
        mx = {m["i"]: m for m in td["quality"]["matrix"]}
        self.assertEqual(mx[i_bad]["grade"], "unreliable")
        self.assertEqual(mx[0]["axes"]["mail_out"], 1.0)

    def test_unknown_grade_not_unreliable(self):
        b = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", grade="")
        self.put(b)
        td = self.agg().td
        self.assertEqual(td["quality"]["excluded_from_comparison"], [])

    def test_a05_calendar_mismatch(self):
        """A05: 7월을 23일로 계산한 옛 판 → 서버 달력(22) + calendar_mismatch + 개인값 병기."""
        b = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                          workdays_override={"2026-07": 23}, calendar_version="kr-old")
        self.put(b)
        p = self.person(self.agg().td, PK1)
        e = p["months"][0]
        self.assertIn("calendar_mismatch", p["flags"])
        self.assertEqual(e["workdays"], 22)
        self.assertEqual(e["mm"], e["env_min"] / (480 * 22))
        self.assertEqual(e["mm_bundle"], e["env_min"] / (480 * 23))

    def test_a12_2026_workdays_gate(self):
        """A12 · T-13: 서버 달력(config\\calendar.json) 2026 월별 근무일 = 검증표, 07=22·08=20·09=20·10=20."""
        cal = self.st.calendar()
        want = json.loads(VERIFIED.read_text(encoding="utf-8"))["counts"]
        for m in range(1, 13):
            self.assertEqual(cal.month_workdays(2026, m), want[f"2026-{m:02d}"], m)
        self.assertEqual([cal.month_workdays(2026, m) for m in (7, 8, 9, 10)], [22, 20, 20, 20])

    def test_cfg_mismatch_majority(self):
        for k, pk in enumerate((PK1, PK2, PK3)):
            b = B.make_bundle(pk, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00")
            if k == 2:
                b["generator"]["rules_ver"] = "2026.9.0"
            self.put(b)
        td = self.agg().td
        flags = {p["person_key"]: p["flags"] for p in td["people"]}
        self.assertIn("cfg_mismatch", flags[PK3])
        self.assertNotIn("cfg_mismatch", flags[PK1])


class TestLinksDamageMerge(AggCase):
    def test_a06_links(self):
        """A06: self_peer_key 같은 두 키(같은 pepper_id) / 같은 member_id → 한 사람."""
        spk = B.peer_key(9)
        a = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                          self_peer_key=spk, pepper_id=self.st.pepper_id)
        b = B.make_bundle(PK2, "2026-08-01", "2026-08-31", built_at="2026-09-01T09:00:00+09:00",
                          self_peer_key=spk, pepper_id=self.st.pepper_id)
        c = B.make_bundle(PK3, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                          self_peer_key=B.peer_key(8), pepper_id="0badbeef")
        for o in (a, b, c):
            self.put(o)
        td = self.agg().td
        self.assertEqual(len(td["people"]), 2)
        rep = next(p for p in td["people"] if p["person_key"] in (PK1, PK2))   # 대표 = 먼저 받은 키(같은 초면 사전순)
        other = PK2 if rep["person_key"] == PK1 else PK1
        self.assertEqual(rep["linked"], [other])
        self.assertEqual([e["m"] for e in rep["months"]], ["2026-07", "2026-08"])
        self.assertIn("pepper_mismatch", self.person(td, PK3)["flags"])
        mv = {m["person_key"]: m for m in self.st.members_view(td)["members"]}
        self.assertEqual(mv[other]["linked"], [rep["person_key"]])

    def test_a06_member_id_link(self):
        self.put(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", member_id="M003"))
        self.put(B.make_bundle(PK2, "2026-08-01", "2026-08-31", built_at="2026-09-01T09:00:00+09:00", member_id="M003"))
        self.assertEqual(len(self.agg().td["people"]), 1)

    def test_a09_tampered_bundle_excluded(self):
        self.put(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00"))
        self.put(B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00"))
        ent = self.st.read_current(PK2)["2026-07-01_2026-07-31"]
        p = self.st.bundles_dir(PK2) / ent["file"]
        raw = bytearray(fsx.read_bytes(p))
        raw[10] ^= 1
        fsx.atomic_write(p, bytes(raw))
        res = self.agg()
        self.assertEqual([x["person_key"] for x in res.td["people"]], [PK1])
        self.assertTrue(any("sha 불일치" in w and PK2 in w for w in res.warnings))

    def test_i1_i6_detected_on_stored_data(self):
        """I1·I6: 저장 뒤 손대진 묶음(검증을 우회)도 취합은 계속하고 warnings 에 남긴다."""
        o = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00")
        d, _u, t, _m = o["alloc_daily"]["rows"][0]
        env = next(r for r in o["envelope_daily"]["rows"] if r[0] == d)
        o["alloc_daily"]["rows"][0][3] = env[1 + B.TAGS.index(t)] + 1
        o["units"][0]["effort_min"] += 1
        raw = B.canon(o)
        sha = B.sha(raw)
        fn = f"2026-07-01_2026-07-31__{sha[:12]}.json"
        fsx.atomic_write(self.st.bundles_dir(PK1) / fn, raw)
        fsx.atomic_write(self.st.current_json(PK1), fsx.canon_bytes({"2026-07-01_2026-07-31": {
            "sha256": sha, "file": fn, "received_at": "2026-08-02T09:00:00+09:00", "built_at": o["built_at"],
            "client": "", "via": "http"}}))
        res = self.agg()
        self.assertTrue(any(w.startswith("I1") for w in res.warnings), res.warnings)
        self.assertTrue(any(w.startswith("I6") for w in res.warnings), res.warnings)
        self.assertEqual(len(res.td["people"]), 1)

    def test_role_id_collision_counted_separately(self):
        """R-8: 서로 다른 (과제·분야·기능)이 같은 role_id(24비트 충돌) → 경고 후 두 역할로 따로 센다."""
        for pk, field in ((PK1, "ELEC"), (PK2, "MECH")):
            o = B.make_bundle(pk, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", field=field)
            forged = "r_abcdef"
            o["roles"][0]["role_id"] = forged
            for u in o["units"]:
                u["role_id"] = forged
            for w in o["workflows"]:
                w["role_id"] = forged
            for x in o["agentic"]["matches"] + o["agentic"]["subagents"]:
                x["role_id"] = forged
            raw = B.canon(o)
            sha = B.sha(raw)
            fn = f"2026-07-01_2026-07-31__{sha[:12]}.json"
            fsx.atomic_write(self.st.bundles_dir(pk) / fn, raw)                     # 검증 우회(충돌 모사)
            fsx.atomic_write(self.st.current_json(pk), fsx.canon_bytes({"2026-07-01_2026-07-31": {
                "sha256": sha, "file": fn, "received_at": "2026-08-02T09:00:00+09:00", "built_at": o["built_at"],
                "client": "", "via": "http"}}))
        res = self.agg()
        self.assertTrue(any(w.startswith("role_id_collision") for w in res.warnings), res.warnings)
        rows = [r for r in res.td["roles"] if r["role_id"] == "r_abcdef"]
        self.assertEqual(sorted(r["field"] for r in rows), ["ELEC", "MECH"])
        self.assertEqual(len({r["key"] for r in rows}), 2)

    def test_broken_member_isolated(self):
        self.put(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00"))
        fsx.atomic_write(self.st.member(PK2) / "current.json", b"{bad")
        fsx.ensure_dir(self.st.bundles_dir(PK2))
        res = self.agg()
        self.assertEqual(len(res.td["people"]), 1)

    def test_a10_project_merge_chain_and_cycle(self):
        """A10: P-0002.merged_into=P-0001 → P-0001 행으로. P-0003↔P-0004 순환 → 묶음 수 많은 쪽(동률 사전순)."""
        reg = B.registry(1, projects=[
            {"id": "P-0001", "name": "과제A", "domain": "DEV", "merged_into": None},
            {"id": "P-0002", "name": "과제B", "domain": "MP", "merged_into": "P-0001"},
            {"id": "P-0003", "name": "과제C", "domain": "EXT", "merged_into": "P-0004"},
            {"id": "P-0004", "name": "과제D", "domain": "COM", "merged_into": "P-0003"}])
        fsx.atomic_write(self.st.registry_json(), fsx.canon_bytes(reg))      # 손편집 가정(PUT 은 순환을 막는다)
        self.put(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                               project="P-0002", domain="MP"))
        self.put(B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                               project="P-0004", domain="COM"))
        self.put(B.make_bundle(PK3, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                               project="P-0004", domain="COM", seed=3))
        td = self.agg().td
        projs = {p["key"]: p for p in td["projects"]}
        self.assertIn("P-0001", projs)
        self.assertNotIn("P-0002", projs)
        self.assertEqual(projs["P-0001"]["merged"], ["P-0002"])
        self.assertEqual(projs["P-0001"]["domain"], "DEV")                    # 영역은 서버 레지스트리 값
        self.assertEqual(projs["P-0001"]["label"], "과제A")
        self.assertIn("P-0004", projs)                                         # 순환: 묶음 수 많은 P-0004
        self.assertEqual(A.resolve_project(reg, "P-0003", {}), "P-0003")       # 동률 → 사전순
        self.assertEqual(A.resolve_project(reg, "P-0099"), "P-0099")

    def test_proposal_and_unc(self):
        self.put(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                               project=None, proposal="pr_1", domain="AX"))
        td = self.agg().td
        pr = [p for p in td["projects"] if p["proposal"]]
        self.assertEqual(len(pr), 1)
        self.assertEqual((pr[0]["domain"], pr[0]["proposal_id"], pr[0]["label"]), ("AX", "pr_1", "과제A 후속"))
        self.assertTrue(next(r for r in td["roles"])["proposal"])


class TestAgentic(AggCase):
    def test_matches_needs_subagents(self):
        self.st.put_registry(B.registry(1))
        a = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00")
        b = B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00")
        self.put(a)
        self.put(b)
        res = A.aggregate(self.st, 1, ukey=lambda s: " ".join(s.split()).casefold())
        ag = res.td["agentic"]
        m = ag["matches"][0]
        self.assertEqual((m["agent_id"], m["name"], m["people"], m["units"]), ("AG003", "문서 초안 작성", 2, 2))
        u0a = a["units"][0]
        u0b = b["units"][0]
        want = (u0a["effort_min"] + u0b["effort_min"]) / (480 * 22)                # 서버가 alloc 에서 다시 합침
        self.assertLessEqual(abs(m["related_mm"] - want), 1e-9)
        n = ag["needs"][0]
        self.assertEqual((n["people"], n["freq_per_month"], n["src"]), (2, 4.0, {"ai": 0, "rule": 2}))
        s = ag["subagents"][0]
        self.assertEqual((s["field"], s["fit"]["조건부"], s["chains"][0]["step_types"]), ("ELEC", 2, ["DOC_XLS"]))
