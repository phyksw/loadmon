# -*- coding: utf-8 -*-
"""화면 API — 사용자 비교 지적(B7·B10~B16) 수리 확인. 모래상자·합성 자료(자리표시자 이름·과제)만, 실 Edge·네트워크 없음.

- B7  머리 띠: /api/analysis/runs 의 current 에 라벨 출처 수·분석 시각 · /api/report 의 run.built_at(모델 파일 밖 값)
- B10 분류 상태: 제안(투입·처음~마지막·이름표) · 학습 규칙 조건/결과(로컬 해석) · 미적용 수정 · 팀 과제 자동 연결 알림
- B11 [내 과제로 받기] 폼: keywords·words 둘 다, 영역(domain)
- B12 코드네임 [고객사 이름] → privacy.customers(C9xx) + 검토 표시 · B13 니즈 되돌리기(drop=false)
- B14 Copilot 상태: 마지막 탐침·보정 한도 · [분석용 Edge 창 앞으로] 결과 문구(실 Edge 대신 UiDeps.bridge_front)
- B15 직접 붙여넣기: 항목 수·단계/상태 이름 · 반입 결과 요청 번호·건수 · B16 대시보드 달 = 기준 시각의 달, 초과 = 기준 설정
"""
import json
import unittest
from datetime import UTC, date, datetime, timedelta
from unittest import mock

from lm27.hier.proposals import codename_hash
from lm27.util import fsx
from tests.fixtures.wp35.harness import RUN_ID, Running, Sandbox, sample_model, seed_analysis

M1, M9 = "m" + "1" * 24, "m" + "9" * 24


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        seed_analysis(self.sb)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)
        self.p = self.sb.paths

    def status(self, **kw):
        st = fsx.read_json(self.p.run_status_file(RUN_ID), None)
        st.update(kw)
        self.sb.write_json(self.p.run_status_file(RUN_ID), st)

    def model(self, m):
        self.sb.write_json(self.p.analysis_report_file(RUN_ID, "report_model.json"), m)


class BandTest(_Base):
    def test_b7_runs_current_label_sources_and_report_built_at(self):
        self.status(started="2026-10-05T01:15:00Z", ended="2026-10-05T01:20:30Z")
        m = sample_model()
        m["flags"]["label_sources"] = {"task_label": {"ai": 0, "manual": 0, "rule": 9, "user": 0},
                                       "workflow_label": {"ai": 0, "manual": 0, "rule": 3}}
        self.model(m)
        st, b, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(st, 200, b)
        cur = b["current"]
        self.assertEqual(cur["label_sources"], m["flags"]["label_sources"])   # current.json 에는 없다 — 모델에서
        self.assertEqual(cur["built_at"], "2026-10-05T10:20:30+09:00")         # 이력 표 '분석 시각' 과 같은 값
        st, r, _ = self.srv.req("GET", "/api/report?variant=full")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["run"]["built_at"], "2026-10-05T10:20:30+09:00")
        raw = fsx.read_bytes(self.p.analysis_report_file(RUN_ID, "report_model.json"))
        self.assertNotIn(b"built_at", raw)                                     # 모델 파일은 그대로(G-R1)

    def test_report_chosen_only_in_response(self):
        """통합(W2 C01 handoff): run.chosen 은 모델 파일이 아니라 응답에만 — current.json 이 그 실행일 때만(지어내지 않는다)."""
        m = sample_model()
        m["run"].pop("chosen", None)
        self.model(m)
        cur = fsx.read_json(self.p.analysis_current(), None)
        self.sb.write_json(self.p.analysis_current(), {**cur, "chosen": "explicit"})
        st, r, _ = self.srv.req("GET", "/api/report?variant=full")
        self.assertEqual((st, r["run"].get("chosen")), (200, "explicit"), r.get("run"))
        raw = fsx.read_bytes(self.p.analysis_report_file(RUN_ID, "report_model.json"))
        self.assertNotIn(b"chosen", raw)                                       # 모델 파일은 그대로(G-R1)
        self.sb.write_json(self.p.analysis_current(), {**cur, "run_id": "20261001-000000-0000"})   # 다른 실행이 현재 결과
        st, r, _ = self.srv.req("GET", "/api/report?variant=full&run=" + RUN_ID)
        self.assertEqual(st, 200, r)
        self.assertNotIn("chosen", r["run"])

    def test_forget_models_also_forgets_drill_cache(self):
        """통합(W2 C18 handoff): 화면 모델 캐시 비우기·분석/보고서 작업 끝이 [근거] 드릴다운 캐시도 바로 놓는다."""
        from lm27.report import drill
        from lm27.ui import api_report
        calls = []
        with mock.patch.object(drill, "forget", lambda: calls.append(1)):
            api_report.forget_models(self.app)
            self.assertEqual(len(calls), 1)
            for kind, n in (("report_export", 1), ("report_build", 2), ("analyze", 3), ("quick_reanalyze", 4)):
                self.app._job_done(type("J", (), {"kind": kind, "state": "done"})())
                self.assertEqual(len(calls), n, kind)

    def test_b16_home_month_is_as_of_month_and_overtime_basis(self):
        m = sample_model()
        m["run"]["as_of"] = "2026-08-31T18:00"
        m["months"] = [{"m": "2026-08", "env_min": 9000, "denom_min": 9600, "avail_min": 9600, "overtime_window_min": 600,
                        "overtime_daily8h_min": 120, "unattr_min": 300, "quality": {"grade": "reliable"}},
                       {"m": "2026-09", "env_min": 9600, "denom_min": 9600, "avail_min": 9600, "overtime_window_min": 60,
                        "overtime_daily8h_min": 0, "unattr_min": 480, "quality": {"grade": "caution"}}]
        m["denominator"] = {"basis": "workdays", "std_day_min": 480, "overtime_basis": "daily8h"}
        self.model(m)
        st, b, _ = self.srv.req("GET", "/api/home")
        self.assertEqual(st, 200, b)
        a = b["analysis"]
        self.assertEqual(a["month"], "2026-08")                                 # 근무가 있는 마지막 달(09)이 아니라 기준 달
        self.assertEqual((a["kpi"]["ot_h"], a["kpi"]["ot_basis"]), ("2.0", "daily8h"))
        self.assertEqual(a["kpi"]["quality"], "reliable")
        m["run"]["as_of"] = "2026-11-02T09:00"                                   # 기준 달이 기간 밖 — 근무가 있는 마지막 달
        del m["denominator"]
        self.model(m)
        st, b, _ = self.srv.req("GET", "/api/home")
        self.assertEqual((b["analysis"]["month"], b["analysis"]["kpi"]["ot_h"], b["analysis"]["kpi"]["ot_basis"]),
                         ("2026-09", "1.0", "window"))


class HierStateTest(_Base):
    def write_local(self, name, obj):
        self.sb.write_json(self.p.hier_local_file(name), obj)

    def seed_hier(self):
        now = datetime.now(UTC)
        recent, old = (now - timedelta(days=2)).isoformat(timespec="seconds"), (now - timedelta(days=40)).isoformat(timespec="seconds")

        def item(pid, label, status, **kw):
            it = {"proposal_id": pid, "kind": "project", "label": label, "domain_guess": "DEV", "status": status,
                  "local_project": None, "mapped_to": None, "merged_into": None, "sources": [], "groups": [], "n_units": 0,
                  "effort_min": 0, "first_at": None, "last_at": None, "match_words": [], "evidence_keys": [],
                  "customers": [], "history": [{"at": old, "event": "created", "by": "task_label"}]}
            it.update(kw)
            return it
        self.write_local("proposals.json", {"schema": "lm27.proposals/1", "next_seq": 5, "items": [
            item("pr_1", "방열 모듈", "pending", n_units=3, effort_min=720, first_at="2026-09-14", last_at="2026-10-02",
                 sources=[{"from": "task_label", "group": "grp:aaaaaaaaaaaa", "conf": "m", "at": old}]),
            item("pr_2", "광센서 선행", "mapped", mapped_to="P-0021",
                 history=[{"at": old, "event": "created", "by": "bootstrap"},
                          {"at": recent, "event": "mapped", "by": "registry", "project": "P-0021"}]),
            item("pr_3", "옛 연결", "mapped", mapped_to="P-0022",
                 history=[{"at": old, "event": "mapped", "by": "registry", "project": "P-0022"}]),
            item("pr_4", "다른 제안", "pending", history=[{"at": old, "event": "created", "by": "user"}])]})

    def test_b10_proposals_rules_unapplied_notices(self):
        self.seed_hier()
        self.write_local("rules_learned.json", {"schema": "lm27.rules_learned/1", "learned_from": ["c_1"], "rules": [
            {"id": "LT-0a1b2c3d", "kind": "token", "if": {"token": "방열"}, "then": {"project": "P-0007"}, "status": "active",
             "hits": 4, "agree": 3, "disagree": 1},
            {"id": "LK-conv-h5555555", "kind": "key", "if": {"conv": "h" + "5" * 16}, "then": {"project": "P-0007"},
             "status": "candidate"},
            {"id": "LK-fam-d6666666", "kind": "key", "if": {"fam": "d" + "6" * 16}, "then": {"project": "P-0007"},
             "status": "retired", "reason": "정밀도 2/6"},
            {"id": "LK-app-wtype-12345678", "kind": "app", "if": {"app": "excel"}, "then": {"wtype": "OFFICE"},
             "status": "active"},
            {"id": "LT-0a1b2c3d~1", "kind": "token", "if": {"token": "방열"}, "then": {"project": "P-0012"},
             "status": "superseded"}]})
        tgt = {"group": "", "fam_keys": [], "conv_keys": [], "dir_keys": []}
        lines = [{"at": "2026-09-30T10:00:00+09:00", "id": "c_1", "target": dict(tgt, anchor=M1, unit_keys=[M1]),
                  "set": {"project": "P-0007"}, "scope": "similar"},
                 {"at": "2026-09-29T10:00:00+09:00", "id": "c_2", "target": dict(tgt, anchor=M9, unit_keys=[M9],
                                                                                fam_keys=["d" + "8" * 16]),
                  "set": {"title": "새 제목", "project": "P-0007"}, "scope": "this"},
                 {"at": "2026-10-05T12:00:00+09:00", "id": "c_3", "target": dict(tgt, anchor=M9, unit_keys=[M9]),
                  "set": {"project": "NONE"}, "scope": "this"}]                  # 분석 뒤에 쓴 기록 — 아직 적용 전(대기)
        fsx.atomic_write(self.p.hier_local_file("corrections.jsonl"),
                         b"".join(fsx.canon_bytes(x) + b"\n" for x in lines))
        self.status(started="2026-10-05T01:15:00Z")
        self.sb.write_json(self.p.analysis_hier_file(RUN_ID, "hier_meta.json"), {"warnings": ["unapplied_corrections:1"]})
        st, b, _ = self.srv.req("GET", "/api/hier/state")
        self.assertEqual(st, 200, b)
        props = {p["proposal_id"]: p for p in b["proposals"]}
        p1 = props["pr_1"]
        self.assertEqual((p1["units"], p1["effort_min"], p1["first"], p1["last"]), (3, 720, "2026-09-14", "2026-10-02"))
        self.assertEqual((p1["src"], p1["src_ko"], p1["state_ko"]), ("task_label", "AI", "검토 대기"))
        self.assertEqual((props["pr_2"]["state_ko"], props["pr_2"]["src_ko"]), ("팀 과제로 연결됨", "부트스트랩"))
        self.assertEqual(props["pr_4"]["src_ko"], "내가 만듦")
        self.assertNotIn("{", json.dumps([p["src_ko"] for p in b["proposals"]], ensure_ascii=False))   # 객체 아님
        self.assertEqual([n["text_ko"] for n in b["notices"]], ["제안 '광센서 선행' → 팀 과제 P-0021 로 연결됨"])  # 40일 전 연결은 뺀다
        rules = {r["rule_id"]: r for r in b["rules"]}
        r = rules["LT-0a1b2c3d"]
        self.assertEqual((r["kind_ko"], r["cond"], r["result"], r["state_ko"], r["hits"]), ("낱말", "'방열' 낱말", "P-0007", "켜짐", 4))
        self.assertEqual(rules["LK-conv-h5555555"]["cond"], "'전원부 검증' 업무의 대화")          # 대화 키 → 그 대화가 근거인 업무
        self.assertEqual(rules["LK-conv-h5555555"]["kind_ko"], "대화방")
        self.assertEqual((rules["LK-fam-d6666666"]["cond"], rules["LK-fam-d6666666"]["state_ko"]),
                         ("이번 결과에 없는 문서", "은퇴(맞힌 비율이 낮음)"))
        self.assertTrue(rules["LK-app-wtype-12345678"]["result"].startswith("유형 "))
        self.assertEqual(rules["LT-0a1b2c3d~1"]["state"], "superseded")
        self.assertNotIn("h" + "5" * 16, json.dumps(b["rules"]))               # 로컬 키 자체는 보이지 않는다
        self.assertEqual(b["unapplied"], [{"id": "c_2", "date": "2026-09-29", "set": {"title": "새 제목", "project": "P-0007"},
                                           "set_ko": "과제 → P-0007 · 제목 → '새 제목'", "n_keys": 2}])
        self.assertEqual(b["corrections"], 3)
        self.sb.write_json(self.p.analysis_hier_file(RUN_ID, "hier_meta.json"), {"warnings": []})
        st, b, _ = self.srv.req("GET", "/api/hier/state")
        self.assertEqual(b["unapplied"], [])                                   # 분석이 모두 적용했다고 남겼으면 빈 목록

    def test_b11_accept_words_or_keywords_and_domain(self):
        self.seed_hier()
        st, b, _ = self.srv.req("POST", "/api/hier/proposal", {"proposal_id": "pr_1", "action": "accept", "domain": "MP",
                                                                 "words": ["방열", " 열해석 ", ""]})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["project"], "L-0001")
        st, b, _ = self.srv.req("POST", "/api/hier/proposal", {"proposal_id": "pr_4", "action": "accept",
                                                                 "keywords": ["센서"]})
        self.assertEqual((st, b.get("project")), (200, "L-0002"), b)
        loc = fsx.read_json(self.p.hier_local_file("registry_local.json"), None)
        ps = {p["id"]: p for p in loc["projects"]}
        self.assertEqual((ps["L-0001"]["keywords"], ps["L-0001"]["domain"]), (["방열", "열해석"], "MP"))
        self.assertEqual((ps["L-0002"]["keywords"], ps["L-0002"]["domain"]), (["센서"], "DEV"))
        st, b, _ = self.srv.req("POST", "/api/hier/proposal", {"proposal_id": "pr_1", "action": "accept", "words": "방열"})
        self.assertEqual(st, 400)

    def test_b10_rule_copy_team_text(self):
        self.write_local("rules_learned.json", {"schema": "lm27.rules_learned/1", "learned_from": [], "rules": [
            {"id": "LT-0a1b2c3d", "kind": "token", "if": {"token": "방열"}, "then": {"project": "P-0007"},
             "status": "active", "hits": 4}]})
        st, b, _ = self.srv.req("POST", "/api/hier/rule", {"rule_id": "LT-0a1b2c3d", "action": "copy_team"})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["text_ko"], "팀 규칙 제안: 낱말 '방열' 낱말 → P-0007(적중 4건 · 학습 규칙 LT-0a1b2c3d)")

    def test_b12_codename_customer(self):
        st, b, _ = self.srv.req("POST", "/api/hier/codename", {"cand": "고객사엑스", "action": "customer"})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["customer"], "C901")
        self.assertIn("C901", b["text_ko"])
        cfg = fsx.read_json(self.p.config_json(), None)
        self.assertEqual(cfg["privacy.customers"], [{"id": "C901", "names": ["고객사엑스"], "domains": []}])
        self.assertEqual(list(self.app.cfg()["privacy.customers"][0]["names"]), ["고객사엑스"])   # 설정을 다시 읽었다
        loc = fsx.read_json(self.p.hier_local_file("registry_local.json"), None)
        self.assertIn(codename_hash("고객사엑스"), loc["codename_review"]["ignored"])         # 후보 목록에서 빠진다
        st, b, _ = self.srv.req("POST", "/api/hier/codename", {"cand": "고객사엑스", "action": "customer"})
        self.assertEqual((st, b["customer"]), (200, "C901"))
        self.assertIn("이미", b["text_ko"])
        st, b, _ = self.srv.req("POST", "/api/hier/codename", {"cand": "다른고객", "action": "customer"})
        self.assertEqual(b["customer"], "C902")


class NeedTest(_Base):
    def test_b13_drop_and_undo(self):
        st, b, _ = self.srv.req("POST", "/api/agentic/need/drop", {"need_id": "n_1a2b3c"})
        self.assertEqual((st, b["dropped"], b["changed"]), (200, True, True), b)
        self.assertEqual(fsx.read_json(self.p.team_overrides(), None)["needs"], {"n_1a2b3c": "drop"})
        st, b, _ = self.srv.req("POST", "/api/agentic/need/drop", {"need_id": "n_1a2b3c", "drop": False})
        self.assertEqual((st, b["dropped"], b["changed"]), (200, False, True), b)
        self.assertEqual(fsx.read_json(self.p.team_overrides(), None)["needs"], {})
        st, b, _ = self.srv.req("POST", "/api/agentic/need/drop", {"need_id": "n_1a2b3c", "drop": False})
        self.assertEqual((st, b["changed"]), (200, False))
        st, b, _ = self.srv.req("POST", "/api/agentic/need/drop", {"need_id": "n_1a2b3c", "drop": "아니오"})
        self.assertEqual(st, 400)


class CopilotTest(_Base):
    def test_b14_status_last_probe_and_limits(self):
        pid = "0e7d1c2b-3a49-4f58-9e6d-7c8b9a0f1e2d"
        today = date.today()
        fsx.atomic_write(self.p.bridge_profile_id(), (pid + "\n").encode("utf-8"))
        self.sb.write_json(self.p.bridge_probe_last(), {"ok": False, "recommend": "none", "env": {"tier": "premium",
                                                                                                    "web_exposed": False},
                                                         "checks": [{"id": "edge", "ok": True, "code": ""},
                                                                    {"id": "login", "ok": False, "code": "login_required"}]})
        fast = str(self.app.cfg()["bridge.modelFast"])
        self.sb.write_json(self.p.bridge_profile(), {"health": {"last_probe": "2026-10-05T00:12:00Z"}, "calibration": [
            {"profile_id": pid, "model": fast, "edge_major": 129, "date": (today - timedelta(days=400)).isoformat(),
             "input_limit": 5000, "output_limit": 4000},
            {"profile_id": pid, "model": fast, "edge_major": 129, "date": today.isoformat(), "input_limit": 8200,
             "output_limit": 6100, "pack_in": 6970, "pack_out": 5185},
            {"profile_id": "other", "model": fast, "edge_major": 129, "date": today.isoformat(), "input_limit": 99999,
             "output_limit": 99999}]})
        st, b, _ = self.srv.req("GET", "/api/bridge/status")
        self.assertEqual(st, 200, b)
        self.assertIn("copilot_role", b)
        self.assertEqual(b["last_probe"]["text_ko"], "10-05 09:12 · 아직 연결하지 못했습니다(로그인 필요 — [분석용 Edge 창 앞으로]에서 한 번 로그인)")
        self.assertEqual((b["limits"]["in"], b["limits"]["out"], b["limits"]["date"], b["limits"]["stale"]),
                         (8200, 6100, today.isoformat(), False))

    def test_b14_front_result_texts(self):
        self.app.deps.front_result = {"state": "launched", "port": 9343}
        st, b, _ = self.srv.req("POST", "/api/bridge/front", {})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["state"], "launched")
        self.assertIn("새로 열었습니다", b["text_ko"])
        self.app.deps.front_result = {"state": "front", "port": 9343, "restored": True}
        st, b, _ = self.srv.req("POST", "/api/bridge/front", {})
        self.assertEqual((st, b["restored"]), (200, True))
        self.assertIn("앞으로 가져왔습니다", b["text_ko"])
        self.assertFalse(b["login_pending_cleared"])
        self.assertNotIn("다시 기다립니다", b["text_ko"])
        # 로그인 보류(V18)를 지웠으면 그 사실을 알린다 — 다음 수집·분석은 다시 로그인을 기다린다(통합 — A handoff)
        self.app.deps.front_result = {"state": "launched", "port": 9343, "login_pending_cleared": True}
        st, b, _ = self.srv.req("POST", "/api/bridge/front", {})
        self.assertEqual((st, b["login_pending_cleared"]), (200, True))
        self.assertTrue(b["text_ko"].endswith("다음 수집·분석에서 로그인을 다시 기다립니다"), b["text_ko"])
        for state, code in (("lock_busy", 409), ("policy_blocked", 409), ("edge_not_found", 409), ("launch_failed", 500)):
            self.app.deps.front_result = {"state": state}
            st, b, _ = self.srv.req("POST", "/api/bridge/front", {})
            self.assertEqual((st, b["code"]), (code, state))
        self.assertEqual(self.app.deps.front_calls, 7)


class ManualTest(_Base):
    def test_b15_batches_and_import_results(self):
        self.sb.write_json(self.p.copilot_manual() / "manifest.json", {"schema": 1, "batches": [
            {"seq": 2, "stage": "task_label", "rid": "R2AAAA", "file": "", "items": [{"n": 1, "key": "k1", "ck": "a"}],
             "in_chars": 100, "created": "2026-10-05T00:00:00Z", "state": "answered"},
            {"seq": 3, "stage": "task_label", "rid": "R2ABCD", "file": "003_task_label_R2ABCD.prompt.txt",
             "items": [{"n": 1, "key": "k1", "ck": "a"}, {"n": 2, "key": "k2", "ck": "b"}], "in_chars": 8150,
             "created": "2026-10-05T00:00:00Z", "state": "open"}]})
        st, b, _ = self.srv.req("GET", "/api/bridge/manual")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["open"], 1)
        row = b["batches"][0]
        self.assertEqual((row["seq"], row["items"], row["items_n"], row["state_ko"]), (3, 2, 2, "답 기다림"))
        self.assertNotEqual(row["stage_ko"], "task_label")                     # 단계 등록부의 한국어 제목
        rep = {"results": [{"rid": "R2ABCD", "stage": "task_label", "status": "partial", "ok": 10, "retry": 2, "was": "open"}],
               "rejected": [], "error": None, "open": 1, "committed": 10, "retry": 2, "rc": 2}
        with mock.patch("lm27.bridge.runner.open_runtime", lambda *a, **k: object()), \
                mock.patch("lm27.bridge.runner.close_runtime", lambda rt: None), \
                mock.patch("lm27.bridge.runner.manual_import", lambda text, rt, specs: dict(rep)):
            st, b, _ = self.srv.req("POST", "/api/bridge/manual/import", {"text": "```json\n{}\n```"})
            self.assertEqual(st, 200, b)
            x = b["results"][0]
            self.assertEqual((x["rid"], x["status_ko"], x["counts_ko"]), ("R2ABCD", "일부 반영", "반영 10 · 다시 물음 2"))
            self.assertEqual(b["text_ko"], "답 1묶음을 반입했습니다(반영 10 · 다시 물음 2) — 남은 묶음 1개")
            rep.update(results=[], error="BR-MANUAL-NOENV", rc=1)
            st, b, _ = self.srv.req("POST", "/api/bridge/manual/import", {"text": "아무 글"})
            self.assertEqual(st, 200, b)
            self.assertFalse(b["ok"])
            self.assertIn("찾지 못했습니다", b["text_ko"])


if __name__ == "__main__":
    unittest.main()
