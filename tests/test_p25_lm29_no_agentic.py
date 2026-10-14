# -*- coding: utf-8 -*-
r"""tests\test_p25_lm29_no_agentic.py — LM29 = LM28 에서 'Agentic AI 후보'(agentic.py — 등록 과제 매칭·신규 후보·오할당 검증)를 뺀 판.

다시 들어오지 않게 막는 시험(파일·소스·모듈 값만 본다 — 새 프로세스를 띄우지 않는다):
  · agentic.py · config\agentic_tasks.json 없음 · 자가점검 NEED · FILES.txt · lint 관문 8(check_l1) 목록에도 없음
  · run.py 에 Agentic 단계·몫 선예약·실측 재계산 없음(AI2_STAGES = flow.py 뿐)
  · 대시보드: Agentic 탭(data-t="agentic" · tab-agentic) · /api/agentic · TOOL_JOBS['agentic'] 없음 · 팀 화면 Agentic 카드 없음
  · 팀 서버는 LM28 묶음(agentic_<기간>.json 포함)을 계속 받는다(NAME_OK) — /agentic 보고서는 없음
  · 업로드·공유폴더 묶음에 agentic_<기간>.json 을 넣지 않음 · 얼린 분석리포트 데이터 섬의 "agentic" 키는 계약으로 남김
  · 설정 파일에 agentic 블록·agenticMaxWork 없음 · 공통업무 이름은 '표준화·자동화 후보'
"""
import ast
import json
import os
import re
import unittest

import _boot

ROOT = _boot.ROOT


def _src(rel):
    return _boot.read_text(os.path.join(ROOT, rel.replace("/", os.sep)))


def _assigned(rel, name):
    """모듈 최상위 `name = <리터럴>` 의 값 — 임포트하지 않고 ast 로만 읽는다(부작용 없음)."""
    for node in ast.parse(_src(rel)).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets):
            return node.value
    raise AssertionError(f"{rel}: {name} 없음")


def _regex(rel, name):
    """`name = re.compile(r"..." r"...")` 의 패턴 문자열."""
    v = _assigned(rel, name)
    if not (isinstance(v, ast.Call) and v.args and isinstance(v.args[0], ast.Constant)):
        raise AssertionError(f"{rel}: {name} 가 re.compile(리터럴) 이 아님")
    return re.compile(v.args[0].value)


class Files(unittest.TestCase):
    def test_module_and_task_plan_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "agentic.py")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "config", "agentic_tasks.json")))   # 팀의 과제 계획 — 타팀에 보내지 않는다

    def test_lists(self):
        need = ast.literal_eval(_assigned("자가점검.py", "NEED"))
        self.assertEqual([p for p in need if "agentic" in p.lower()], [])
        self.assertNotIn("agentic", _src("FILES.txt").lower())
        self.assertNotIn("agentic.py", _src("tools/check_l1.py"))          # 없는 파일을 열면 lint 관문 8 이 죽는다


class RunPipeline(unittest.TestCase):
    def test_no_agentic_stage(self):
        import run as R
        self.assertEqual(R.AI2_STAGES, ("flow.py",))
        for n in ("agentic_recalc_inproc", "agentic_deadline", "ai_reserves"):
            self.assertFalse(hasattr(R, n), n)
        self.assertEqual(set(R._AI_RES), {"flow"})
        src = _src("run.py")
        for s in ("agentic.py", "Agentic 매칭", "agenticReserveMin", "import agentic"):
            self.assertNotIn(s, src, s)                                      # 가짜 '성공' 기록도 남기지 않는다


class Dashboard(unittest.TestCase):
    def test_tab_and_api_gone(self):
        import app
        src = _src("ui/app.py")
        for s in ("/api/agentic", "tab-agentic", 'data-t="agentic"', "rv-agentic", "loadAgentic", "agCover",
                  "/team/agentic", "team_agentic", "agentic_recalc", "_agentic_stale", "import agentic"):
            self.assertNotIn(s, src, s)
        self.assertEqual(set(app.TOOL_JOBS), {"flow"})
        self.assertNotIn("/team/agentic", app.TEAM_FILES)
        self.assertIn("공통업무 — 표준화·자동화 후보", app.PAGE)
        self.assertNotIn("Agentic", app.PAGE)

    def test_team_page_cards_gone(self):
        import app
        for s in ("k_ag", 'id="heat"', "newlist", "D.agentic", "D.tasks", "Agentic"):
            self.assertNotIn(s, app.TEAM_PAGE, s)
        self.assertIn('id="commtbl"', app.TEAM_PAGE)                        # 공통업무 카드는 남는다

    def test_exclude_endpoint_kept(self):
        import app
        self.assertTrue(callable(app.exclude_work))
        self.assertIn('"/api/exclude"', _src("ui/app.py"))


class TeamServer(unittest.TestCase):
    def test_still_accepts_lm28_bundle(self):
        ok = _regex("teamserver.py", "NAME_OK")
        for n in ("agentic_20260101-20261015.json", "workflow_20260101-20261015.json", "mm_meta_20260101-20261015.json"):
            self.assertTrue(ok.fullmatch(n), n)                              # 빠지면 LM28 업로드가 400 으로 통째로 거절된다
        rf = ast.literal_eval(_assigned("teamserver.py", "REPORT_FILES"))
        self.assertNotIn("/agentic", rf)
        self.assertNotIn("team_agentic", _src("teamserver.py"))

    def test_bundle_has_no_agentic(self):
        names = ast.literal_eval(_assigned("teamup.py", "FILE_NAMES"))
        self.assertEqual([n for n in names if "agentic" in n], [])
        self.assertIn("workflow_{t}.json", names)
        self.assertTrue(_regex("teamup.py", "NAME_OK").match("agentic_20260101-20261015.json"))   # 받는 쪽 규칙과 같다
        self.assertNotIn('f"agentic_{tag}.json"', _src("export.py"))

    def test_team_report_and_aggregate(self):
        import aggregate
        import team_report
        for n in ("load_agentic", "norm_agentic", "build_team_agentic"):
            self.assertFalse(hasattr(aggregate, n), n)
        for n in ("collect_agentic_all", "merge_candidates", "cand_refine", "load_adjust", "ADJUST_FILE", "CAND_FILE"):
            self.assertFalse(hasattr(team_report, n), n)
        self.assertEqual([f for f in team_report.CACHE_FILES if "cand" in f or "agentic" in f], [])
        src = _src("team_report.py")
        self.assertIn("9. 프로그램 사용", src)
        self.assertIn("8. 과제별 워크플로우", src)
        self.assertNotIn("Agentic AI 과제 적합률", src)


class Reports(unittest.TestCase):
    def test_freeze_island_contract_kept(self):
        import freeze
        self.assertNotIn("/api/agentic", freeze.FREEZE_EPS)
        src = _src("freeze.py")
        self.assertIn('"agentic": {}', src)                                 # 옛 취합 도구가 찾는 키 — 빈 객체로 남긴다
        self.assertNotIn("Agentic AI 과제 매칭", src)

    def test_report_out_sections(self):
        import report_out
        self.assertFalse(hasattr(report_out, "_task_count"))
        src = _src("report_out.py")
        self.assertIn("7. 산정 근거와 신뢰도", src)
        self.assertIn("8. raw 단서", src)
        self.assertIn("n0=9)", src)                                          # 동료·연관 업무·워크플로 요약은 9절부터
        self.assertIn("공통업무 — 표준화·자동화 후보", src)
        self.assertNotIn("Agentic", src)


class Config(unittest.TestCase):
    def test_no_agentic_keys(self):
        for fn in ("config.default.json", "config.json"):
            with open(os.path.join(ROOT, "config", fn), encoding="utf-8-sig") as f:
                c = json.load(f)
            self.assertNotIn("agentic", c, fn)
            self.assertNotIn("_agentic_설명", c, fn)
            self.assertNotIn("agenticMaxWork", c.get("copilotAuto") or {}, fn)

    def test_flow_rule_share_default(self):
        import flow
        self.assertEqual(flow.RULE_SHARE, 0.8)                              # 설정에 agentic 블록이 없어도 기본값으로 돈다


if __name__ == "__main__":
    unittest.main()
