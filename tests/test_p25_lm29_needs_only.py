# -*- coding: utf-8 -*-
r"""tests\test_p25_lm29_needs_only.py — LM29 의 Agentic AI = '니즈 후보 발굴' 만(팀 과제 매칭·오할당 검증 없음).

다시 들어오지 않게 막는 시험(가드) — 파일·소스·모듈 값:
  · config\agentic_tasks.json 없음 · 프롬프트에 계획 과제·match·misassigned·적합률 없음 · 결과 파일에 match·misassigned 없음
  · 대시보드 Agentic 탭에 과제 표·오할당 [제외] 버튼·커버리지 칩 없음 · 팀 화면에 과제 × 인원 열지도·Agentic 지표 없음
되살린 것이 도는지 보는 시험(가짜 Copilot — judge.copilot_send 를 바꿔 끼운다 · 새 프로세스 없음 · 임시 폴더만):
  · 프롬프트(첫 줄 domainHint · <...> 예시는 답으로 파싱되지 않음 · MM 미전송) · merge_new(이름 fold 병합·자리표시자 버림)
  · 실행: '#번호' → 원본 쌍 keys · evidence_rows · 후보 0건은 실패 아님 · 되돌아온 프롬프트는 실패 · rows_done 으로 남은 행만 ·
    --carry 이어받기 · 규칙 판정 행 보내지 않음 · 관문은 그 행만 · 일시 오류 1회 쉬고 한 번 더 · 사용량 제한은 그 자리에서 멈춤
  · LM28 꼴 파일(match·misassigned·mm_recalc)을 읽으면 그 키를 버린다(recalc_file·화면 /api/agentic·리포트·팀 취합)
  · run.py 단계 순서(정제 → Agentic 니즈 발굴 → 워크플로우)·기록 이름 · 팀 니즈 후보 병합(aggregate.merge_needs) ·
    팀 통합 보고서 5절·인별 복원 리포트 4절 · 업로드 묶음에 agentic 파일
"""
import ast
import contextlib
import csv
import glob
import io
import json
import os
import re
import tempfile
import time
import unittest
from unittest import mock

import _boot

import agentic  # noqa: E402
import details  # noqa: E402
import test_p13_flow as p13  # noqa: E402
import test_p15_ui_reports as p15  # noqa: E402

ROOT = _boot.ROOT
TAG = p13._Env.TAG
SEP = details.KEY_SEP


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


def _ids(prompt):
    return [int(x) for x in re.findall(r"^· #(\d+) ", prompt, re.M)]


def _ok(obj):
    return {"ok": True, "reply": json.dumps(obj, ensure_ascii=False)}


# LM28 이 만든 꼴의 결과 — 과제 매칭·오할당·MM 실측이 함께 든 파일
def _lm28_file(new):
    return {"tag": TAG, "axes": {"축1": "시험 축"},
            "match": [{"task": "AL1", "axis": "축1", "name": "계획 과제 하나", "fit": 70, "load_mm": 3.5,
                       "work": ["설계 검토"], "keys": [f"프로젝트A{SEP}설계 검토"]}],
            "misassigned": [{"row": "프로젝트B/일정 협의", "reason": "참조 위주"}],
            "mm_recalc": {"axis": "plain", "rule_rows": 0}, "unknown_tasks": [], "new": new}


# ── 가드: 파일·목록 ────────────────────────────────────────────────────────────────────────
class Files(unittest.TestCase):
    def test_module_back_task_plan_gone(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "agentic.py")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "config", "agentic_tasks.json")))   # 팀의 과제 계획 — 넣지 않는다

    def test_lists(self):
        need = ast.literal_eval(_assigned("자가점검.py", "NEED"))
        self.assertIn("agentic.py", need)
        self.assertEqual([p for p in need if "agentic_tasks" in p], [])
        files = _src("FILES.txt")
        self.assertIn("agentic.py", files)
        self.assertNotIn("agentic_tasks", files)
        self.assertIn('"agentic.py"', _src("tools/check_l1.py"))           # _stage_budget 사본 재출현 관문

    def test_no_matching_code(self):
        for n in ("load_tasks", "merge_match", "merge_mis", "_task_resolver", "_fit", "recalc_mm", "sig_stats"):
            self.assertFalse(hasattr(agentic, n), n)
        self.assertEqual(agentic.KIND, "needs")
        for k in ("match", "misassigned", "mm_recalc", "axes", "unknown_tasks"):
            self.assertNotIn(k, agentic.NEEDS_KEYS)


# ── 가드 + 되살림: 프롬프트·병합 ──────────────────────────────────────────────────────────────────
class Prompt(p13._Env):
    ROW = {"Level 2": "과제A", "Level 3": "설계", "유형": "개발", "근거": "메일3", "상세설명": "검토", "mm": "1.0", "_rid": 1}

    def setUp(self):
        super().setUp()
        p = mock.patch.object(agentic, "ROOT", self.tmp)
        p.start()
        self._patches.append(p)

    def test_needs_only_prompt(self):
        self.wjson(os.path.join(self.tmp, "config", "config.json"), {"agentic": {"domainHint": "시험용 업무 영역"}})
        p = agentic.ag_prompt([self.ROW])
        self.assertIn("시험용 업무 영역", p.splitlines()[0])
        self.assertIn("니즈", p.splitlines()[0])
        self.assertIn("· #1 과제A / 설계 / 개발 — 검토", p)
        for s in ("계획 과제", "[계획", "match", "misassigned", "fit", "적합", "오할당", "load_mm"):
            self.assertNotIn(s, p, s)
        self.assertIn('"new"', p)
        self.assertNotIn("MM", re.sub(r"\(MM 순\)", "", p))                  # 행에 MM 값이 없다
        self.assertEqual(details.find_json(p, "new"), ({}, ""))               # 되돌아온 프롬프트의 예시는 답이 아니다
        self.wjson(os.path.join(self.tmp, "config", "config.json"), {"agentic": {"domainHint": ""}})
        self.assertIn(agentic.DOMAIN_HINT_DEFAULT, agentic.ag_prompt([self.ROW]).splitlines()[0])

    def test_merge_new(self):
        news = []
        n = agentic.merge_new(news, {"new": [{"name": "<후보 이름>", "work": ["#1"]},
                                             {"name": "보고서 초안 자동화", "logic": "", "work": "#1, #2"}]})
        self.assertEqual((n, len(news)), (1, 1))                             # 자리표시자 베낀 후보는 버린다
        n = agentic.merge_new(news, {"new": {"보고서·초안 자동화": {"logic": "표 → 초안", "work": ["#3"]}}})
        self.assertEqual((n, len(news)), (0, 1))                             # 이름 fold 가 같으면 합친다
        self.assertEqual((news[0]["logic"], news[0]["work"]), ("표 → 초안", ["#1", "#2", "#3"]))
        self.assertEqual(agentic._clean_list("#1, #2;#3", cap=0), ["#1", "#2", "#3"])
        self.assertEqual(agentic._clean_list([{"id": "#4"}, "#5, #6"], cap=0), ["#4", "#5", "#6"])

    def test_evidence_no_mm_and_gate(self):
        out = {"new": [{"name": "후보", "logic": "l", "reason": "r", "work": ["설계"], "load_mm": 2.0, "load_mm_ai": 1.0}]}
        agentic.recalc_evidence(out, [dict(self.ROW)])
        self.assertEqual(out["new"][0]["evidence_rows"], 1)
        self.assertNotIn("load_mm", out["new"][0])
        self.assertNotIn("load_mm_ai", out["new"][0])
        rows = [dict(self.ROW), dict(self.ROW, **{"상세설명": "연락처 010-1234-5678"})]
        self.assertEqual(len(agentic.g3_part(rows)), 1)                       # G3 관문 — 연락처 든 행은 뺀다

    def test_needs_only_drops_lm28_keys(self):
        o = agentic.needs_only(_lm28_file([{"name": "후보"}, "깨진 항목"]))
        self.assertEqual(o["kind"], "needs")
        self.assertEqual([n["name"] for n in o["new"]], ["후보"])
        for k in ("match", "misassigned", "mm_recalc", "axes", "unknown_tasks"):
            self.assertNotIn(k, o)


# ── 되살림: 실행(가짜 Copilot) ─────────────────────────────────────────────────────────────────
class Runs(p13._Env):
    ROWS = [p13._mm_row("프로젝트A", "설계 검토", 2.0), p13._mm_row("프로젝트A", "회로 시뮬레이션", 1.5),
            p13._mm_row("프로젝트B", "시험 보고", 1.0, kind="사무"), p13._mm_row("프로젝트B", "일정 협의", 0.5, kind="협업")]
    NEW1 = {"name": "설계 검토 의견 자동 작성", "logic": "설계 문서 → 검토 의견 초안", "reason": "매주 반복되는 검토",
            "work": ["#1", "#2"]}

    def setUp(self):
        super().setUp()
        p = mock.patch.object(agentic, "ROOT", self.tmp)
        p.start()
        self._patches.append(p)

    def _sigs(self, rule_pair=None):
        out = []
        for i, r in enumerate(self.ROWS):
            pair = (r["Level 2"], r["Level 3"])
            out += p13._sigs(*pair, judge_v="규칙" if pair == rule_pair else "AI", day0=3 + i * 4)
        return out

    def _file(self):
        return self.rjson(f"agentic_{TAG}.json")

    def test_ids_keys_evidence(self):
        self.data(self.ROWS, self._sigs())
        self.reply = lambda p, n: _ok({"new": [self.NEW1]})
        rc, js, out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual((js["ok"], js["new"], js["stop_kind"]), (True, 1, ""))
        a = self._file()
        self.assertEqual(a["kind"], "needs")
        self.assertLessEqual(set(a), set(agentic.NEEDS_KEYS))
        for k in ("match", "misassigned", "mm_recalc"):
            self.assertNotIn(k, a)
        n = a["new"][0]
        self.assertEqual(n["keys"], sorted([f"프로젝트A{SEP}설계 검토", f"프로젝트A{SEP}회로 시뮬레이션"]))
        self.assertEqual((n["evidence_rows"], n["work"]), (2, ["설계 검토", "회로 시뮬레이션"]))
        self.assertNotIn("load_mm", n)
        self.assertEqual((a["rows_analyzed"], a["rows_total"], a["rows_pending"], a["partial"]), (4, 4, 0, False))
        prompt = self.calls[0][1]
        self.assertIn("· #1 프로젝트A / 설계 검토 / 개발", prompt)
        self.assertNotIn("MM", re.sub(r"\(MM 순\)", "", prompt))
        self.assertEqual(self.calls[0][0], f"{TAG}-ag1")
        st = json.load(open(os.path.join(self.rep, f"stage_state_{TAG}_agentic.json"), encoding="utf-8"))
        self.assertEqual(st["state"], "done")
        self.assertIn("Agentic AI 니즈 후보 1건", out)

    def test_no_candidates_is_not_failure(self):
        self.data(self.ROWS, self._sigs())
        self.reply = lambda p, n: _ok({"new": []})
        rc, js, out = self.run_main(agentic)
        self.assertEqual((rc, js["ok"], js["new"]), (0, True, 0))
        self.assertEqual((self._file()["new"], self._file()["rows_pending"]), ([], 0))
        self.assertIn("후보 0건(실패 아님)", out)

    def test_echoed_prompt_is_not_an_answer(self):
        self.data(self.ROWS, self._sigs())
        self.reply = lambda p, n: {"ok": True, "reply": p}                   # 회수가 어긋나 우리 프롬프트가 되돌아왔다
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 1)
        self.assertFalse(js["ok"])
        self.assertTrue(self.bad)                                             # 다음 왕복은 새 채팅에서
        self.assertIn(f"{TAG}-ag1-1", [n for n, _p in self.calls])            # 해석 실패는 반으로 나눠 다시
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"agentic_{TAG}.json")))

    def test_resume_rows_done(self):
        rows = [p13._mm_row("프로젝트A", f"반복 업무 {i:02d} 정리", round(3.0 - i * 0.05, 3)) for i in range(40)]
        self.data(rows, [s for r in rows for s in p13._sigs(r["Level 2"], r["Level 3"], n=1)])
        self.reply = lambda p, n: _ok({"new": [{"name": "반복 업무 정리 자동화", "logic": "l", "reason": "r",
                                                "work": [f"#{i}" for i in _ids(p)]}]})
        budget = str(len(agentic.ag_prompt([])) + agentic.OVERLAY_CHARS + 500)
        rc, js, _out = self.run_main(agentic, "--budget", budget, "--max-chunks", "1")
        self.assertEqual((rc, js["stop_kind"]), (2, "budget"), js)            # 묶음 상한 — 남은 행은 다음 실행이
        self.assertGreater(js["rows_pending"], 0)
        ids1 = set(_ids(self.calls[0][1]))
        n1 = len(self.calls)
        rc, js, _out = self.run_main(agentic, "--budget", budget)
        self.assertEqual(rc, 0, js)
        ids2 = {i for _n, p in self.calls[n1:] for i in _ids(p)}
        self.assertTrue(ids1.isdisjoint(ids2))                                # 이미 본 행은 다시 보내지 않는다
        self.assertEqual(ids1 | ids2, set(range(1, 41)))
        a = self._file()
        self.assertEqual((a["rows_pending"], a["rows_analyzed"], len(a["new"])), (0, 40, 1))
        self.assertEqual(a["new"][0]["evidence_rows"], 40)                    # 두 실행의 근거가 합쳐졌다

    def test_carry_other_tag_and_redo_without_carry(self):
        tag_a = "20260101-20260130"
        self.data(self.ROWS, self._sigs(), tag=tag_a)
        self.reply = lambda p, n: _ok({"new": [dict(self.NEW1, work=[f"#{i}" for i in _ids(p)][:2])]})
        rc, js, _out = self.run_main(agentic, d1="2026-01-30")
        self.assertEqual(rc, 0, js)
        n1 = len(self.calls)
        self.data([dict(r, mm=str(float(r["mm"]) * 2)) for r in self.ROWS], self._sigs())   # 다음 날 — MM 만 바뀜
        rc, js, _out = self.run_main(agentic, "--carry")
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), n1)                                 # 왕복 0
        self.assertEqual(js["carried_from"], tag_a)
        b = self._file()
        self.assertEqual((b["carried_from"], b["matched_since"]), (tag_a, time.strftime("%Y-%m-%d")))
        self.assertEqual((b["new"][0]["name"], b["new"][0]["evidence_rows"]), (self.NEW1["name"], 2))
        rc, js, _out = self.run_main(agentic)                                 # 화면 [니즈 후보 발굴 실행] — 처음부터
        self.assertEqual(rc, 0, js)
        self.assertGreater(len(self.calls), n1)

    def test_rule_rows_not_sent(self):
        self.data(self.ROWS, self._sigs(rule_pair=("프로젝트B", "일정 협의")))
        self.reply = lambda p, n: _ok({"new": []})
        rc, js, out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertNotIn("일정 협의", self.calls[0][1])
        a = self._file()
        self.assertEqual((a["rule_rows"], a["rows_pending"], a["rows_rule"]), (1, 0, ["프로젝트B|일정 협의|협업"]))
        self.assertIn("AI 판정 대기", out)

    def test_gate_one_row_only(self):
        self.data(list(self.ROWS) + [p13._mm_row(f"{p13.CANARY} 과제", "자료 정리", 0.7)], self._sigs())
        self.reply = lambda p, n: _ok({"new": [dict(self.NEW1, work=[f"#{i}" for i in _ids(p)])]})
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn(p13.CANARY, self.calls[0][1])
        self.assertEqual(len(_ids(self.calls[0][1])), 4)                     # 나머지 4행은 그대로 보냈다
        a = self._file()
        self.assertEqual((a["gate_skipped_rows"], a["rows_pending"], len(a["new"][0]["keys"])), (1, 0, 4))

    def test_cooldown_once_then_hard_stop(self):
        self.data(self.ROWS, self._sigs())
        seq = [{"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류"}]
        self.reply = lambda p, n: seq.pop(0) if seq else _ok({"new": [self.NEW1]})
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual([n for n, _p in self.calls], [f"{TAG}-ag1", f"{TAG}-ag1-c"])   # 반분 없음
        self.assertEqual(self.sleeps, [90.0])                                 # 쉬기는 정확히 한 번
        self.assertEqual(self._file()["cooldowns"], 1)
        self.calls.clear()
        self.reply = lambda p, n: {"ok": False, "phase": "throttled", "error": "Copilot 사용량 제한(일시)", "hard": True}
        rc, js, _out = self.run_main(agentic, "--redo")
        self.assertEqual((rc, len(self.calls), js["stop_kind"]), (1, 1, "throttle"))   # 그 자리에서 멈춘다

    def test_recalc_drops_lm28_keys(self):
        self.data(self.ROWS, self._sigs())
        self.wjson(os.path.join(self.rep, f"agentic_{TAG}.json"), dict(
            _lm28_file([{"name": "설계 검토 자동화", "logic": "l", "reason": "r", "work": ["설계 검토"],
                         "keys": [f"프로젝트A{SEP}설계 검토", f"프로젝트A{SEP}회로 시뮬레이션"], "load_mm": 2.0},
                        {"name": "옛 이름 근거 후보", "work": ["시험 보고"]}]),
            rows_done=[], row_keys={"sent": [], "rule": [], "gate": []}))
        rc, js, _out = self.run_main(agentic, "--recalc")
        self.assertEqual((rc, js["ok"], js["recalc"]), (0, True, True))
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"stage_state_{TAG}_agentic.json")))   # 상태 파일 안 엶
        a = self._file()
        for k in ("match", "misassigned", "mm_recalc", "axes", "unknown_tasks"):
            self.assertNotIn(k, a)
        self.assertEqual(a["kind"], "needs")
        self.assertEqual([n["evidence_rows"] for n in a["new"]], [2, 1])     # 키 근거 · 옛 이름 근거
        self.assertNotIn("load_mm", a["new"][0])
        self.assertEqual(self.calls, [])                                      # 왕복 없음


# ── 가드 + 되살림: run.py ─────────────────────────────────────────────────────────────────────
class RunPipeline(unittest.TestCase):
    def test_stage_order_and_names(self):
        import run as R
        self.assertEqual(R.AI2_STAGES, ("agentic.py", "flow.py"))
        for n in ("agentic_recalc_inproc", "agentic_deadline", "ai_reserves"):
            self.assertTrue(callable(getattr(R, n, None)), n)
        self.assertEqual(set(R._AI_RES), {"flow", "ag"})
        src = _src("run.py")
        self.assertNotIn("Agentic 매칭", src)
        self.assertIn("── Agentic AI 니즈 발굴 (반복 업무에서 자동화 니즈 후보 찾기)", src)
        self.assertIn('record("Agentic 니즈 발굴", False, 0.0, _skip)', src)   # 판정 실패면 건너뜀 기록
        i_ref = src.index('os.path.join(ROOT, "refine.py")')
        i_ag = src.index('run_ai_stage("agentic.py"')
        i_fl = src.index('run_ai_stage("flow.py"')
        self.assertLess(i_ref, i_ag)
        self.assertLess(i_ag, i_fl)
        self.assertGreater(src.find("agentic_recalc_inproc(d0, d1)", i_fl), i_fl)   # 워크플로우 뒤 근거 행 다시 세기
        self.assertLess(src.index("_dl_ag = agentic_deadline()"), i_ag)


# ── 가드 + 되살림: 대시보드 ────────────────────────────────────────────────────────────────────
class Dashboard(unittest.TestCase):
    def test_tab_api_and_card(self):
        import app
        self.assertEqual(app.TOOL_JOBS["agentic"], ("agentic.py", "Agentic AI 니즈 발굴"))
        p = app.PAGE
        for s in ('data-t="agentic"', 'id="tab-agentic"', "loadAgentic", 'startTool("/api/agentic")'):
            self.assertIn(s, p, s)
        body = p[p.index("async function loadAgentic"):p.index("// ── 수집 현황 카드", p.index("async function loadAgentic"))]
        for s in ("Agentic AI 니즈 후보 발굴", "니즈 후보 발굴 실행", "동작 로직", "발굴 사유", "근거 업무",
                  "팀 과제와 매칭하지 않고, 내 반복 업무에서 Agentic AI 로 자동화할 만한 니즈 후보만 찾습니다"):
            self.assertIn(s, body, s)
        for s in ("적합률", "fitBar", "data-ex", "오할당", "/api/exclude", "등록된 과제", "agCover", "misassigned", ".match",
                  "재매칭"):
            self.assertNotIn(s, body, s)
        src = _src("ui/app.py")
        self.assertIn('elif self.path in ("/api/workflow", "/api/agentic"):', src)
        self.assertIn('elif self.path == "/api/agentic":', src)
        self.assertTrue(callable(app.exclude_work))                            # [제외] 버튼은 없지만 처리 기능은 남는다
        self.assertIn('"/api/exclude"', src)

    def test_team_page(self):
        import app
        t = app.TEAM_PAGE
        for s in ("팀 Agentic AI 니즈 후보", 'id="needlist"', "D.needs", 'id="commtbl"'):
            self.assertIn(s, t, s)
        for s in ('id="heat"', "k_ag", "D.tasks", "적합률", "newlist", "/team/agentic", "D.agentic||", "a.match"):
            self.assertNotIn(s, t, s)
        self.assertNotIn("/team/agentic", app.TEAM_FILES)


class AgenticApi(p15._Base):
    """GET /api/agentic — LM28 꼴 파일이어도 화면에는 니즈 후보만 · 결과가 없으면 상태 파일의 사유."""

    def test_lm28_file_needs_only(self):
        self.signals()
        p15._w(os.path.join(self.rep, f"agentic_{p15.TAG}.json"), _lm28_file([{"name": "보고서 초안 자동 작성"}]))
        st, out = self.serve().req("GET", "/api/agentic")
        self.assertEqual(st, 200)
        a = out["analysis"]
        self.assertEqual((a["kind"], [n["name"] for n in a["new"]]), ("needs", ["보고서 초안 자동 작성"]))
        for k in ("match", "misassigned", "mm_recalc", "axes"):
            self.assertNotIn(k, a)
        self.assertEqual((out["tag"], out["running"], out["manual"]), (p15.TAG, False, None))

    def test_no_file_reason(self):
        self.signals()
        p15._w(os.path.join(self.rep, f"stage_state_{p15.TAG}_agentic.json"),
               {"schema": 1, "stage": "agentic", "tag": p15.TAG, "state": "failed", "updated": time.time(),
                "stop": {"kind": "throttle", "reason": "Copilot 사용량 제한 — 남은 묶음 보내지 않음"}, "error": {}})
        _st, out = self.serve().req("GET", "/api/agentic")
        self.assertIsNone(out["analysis"])
        self.assertEqual((out["stage_kind"], out["stage_reason"]), ("throttle", "Copilot 사용량 제한 — 남은 묶음 보내지 않음"))


# ── 팀: 묶음 · 서버 · 취합 · 보고서 ────────────────────────────────────────────────────────────────
MM_COLS = p13.MM_COLS


def _member(share, owner, ag=None, rows=None):
    d = os.path.join(share, owner)
    os.makedirs(d)
    with open(os.path.join(d, "member.json"), "w", encoding="utf-8") as f:
        json.dump({"owner": owner, "tag": TAG, "period": ["2026-01-01", "2026-01-31"], "total_mm": 1.5, "avail_mm": 3.0,
                   "load_pct": 50}, f, ensure_ascii=False)
    with open(os.path.join(d, f"mm_rows_{TAG}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MM_COLS)
        w.writeheader()
        for r in rows or [p13._mm_row("프로젝트A", "설계 검토", 1.0), p13._mm_row("프로젝트B", "시험 보고", 0.5)]:
            w.writerow({c: r.get(c, "") for c in MM_COLS})
    if ag is not None:
        with open(os.path.join(d, f"agentic_{TAG}.json"), "w", encoding="utf-8") as f:
            json.dump(ag, f, ensure_ascii=False)


class Team(unittest.TestCase):
    def test_server_and_bundle_lists(self):
        ok = _regex("teamserver.py", "NAME_OK")
        self.assertTrue(ok.fullmatch(f"agentic_{TAG}.json"))
        self.assertNotIn("/agentic", ast.literal_eval(_assigned("teamserver.py", "REPORT_FILES")))
        self.assertNotIn("team_agentic", _src("teamserver.py"))
        names = ast.literal_eval(_assigned("teamup.py", "FILE_NAMES"))
        self.assertIn("agentic_{t}.json", names)
        self.assertTrue(_regex("teamup.py", "NAME_OK").match(f"agentic_{TAG}.json"))
        self.assertIn('f"agentic_{tag}.json"', _src("export.py"))

    def test_bundle_carries_needs_file(self):
        import teamup
        with tempfile.TemporaryDirectory(prefix="lm29_p25_") as d:
            rep = os.path.join(d, "report")
            os.makedirs(rep)
            with open(os.path.join(rep, f"mm_rows_{TAG}.csv"), "w", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=MM_COLS).writeheader()
            with open(os.path.join(rep, f"mm_meta_{TAG}.json"), "w", encoding="utf-8") as f:
                json.dump({"total_mm": 1.0, "avail_mm": 2.0, "mm_basis": {}}, f)
            with open(os.path.join(rep, f"agentic_{TAG}.json"), "w", encoding="utf-8") as f:
                json.dump({"tag": TAG, "kind": "needs", "new": [{"name": "후보", "evidence_rows": 1}]}, f, ensure_ascii=False)
            with mock.patch.object(teamup, "REPORT", rep), mock.patch.object(teamup, "PENDING", os.path.join(rep, "p")), \
                    contextlib.redirect_stdout(io.StringIO()):
                path = teamup.build({"owner": "홍길동"}, "2026-01-01", "2026-01-31")
            with open(path, encoding="utf-8") as f:
                b = json.load(f)
        self.assertIn(f"agentic_{TAG}.json", b["files"])
        self.assertEqual(b["blocked"], [])
        self.assertEqual(json.loads(b["files"][f"agentic_{TAG}.json"])["kind"], "needs")

    def test_merge_needs(self):
        import aggregate
        got = aggregate.merge_needs([
            {"owner": "홍길동", "new": [{"name": "보고서 초안 자동 작성", "logic": "짧은", "reason": "r", "evidence_rows": 2},
                                     {"name": "일정 알림", "evidence_rows": "abc"}, "깨진 항목"]},
            {"owner": "김철수", "new": [{"name": "보고서·초안  자동 작성", "logic": "더 긴 로직 설명", "evidence_rows": 3}]},
            {"owner": "이영희", "new": "깨진 값"}])
        self.assertEqual([(g["name"], g["n"], g["ev"]) for g in got], [("보고서 초안 자동 작성", 2, 5), ("일정 알림", 1, 0)])
        self.assertEqual((got[0]["who"], got[0]["logic"]), (["김철수", "홍길동"], "더 긴 로직 설명"))
        self.assertEqual(len(got[0]["names"]), 2)
        for n in ("build_team_agentic", "norm_agentic"):
            self.assertFalse(hasattr(aggregate, n), n)

    def test_team_data_report_and_member_report(self):
        import aggregate
        import team_report
        for n in ("collect_agentic_all", "merge_candidates", "cand_refine", "load_adjust", "ADJUST_FILE", "CAND_FILE"):
            self.assertFalse(hasattr(team_report, n), n)
        self.assertEqual([f for f in team_report.CACHE_FILES if "cand" in f or "agentic" in f], [])
        with tempfile.TemporaryDirectory(prefix="lm29_p25s_") as share:
            _member(share, "홍길동", {"tag": TAG, "kind": "needs",
                                     "new": [{"name": "보고서 초안 자동 작성", "logic": "시험 결과 → 보고서 초안",
                                              "reason": "매주 반복", "evidence_rows": 2}]})
            _member(share, "김철수", _lm28_file([{"name": "보고서·초안 자동 작성", "evidence_rows": 3}]))   # LM28 묶음
            _member(share, "이영희")                                             # 니즈 후보 파일 없음
            with contextlib.redirect_stdout(io.StringIO()):
                data = aggregate.collect_team_data(share)
                full = team_report.build(share, log=lambda *a: None)
            self.assertEqual(data["agentic_n"], 2)
            self.assertEqual([(aggregate.needs_key(g["name"]), g["n"], g["ev"], g["who"]) for g in data["needs"]],
                             [("보고서 초안 자동 작성", 2, 5, ["김철수", "홍길동"])])
            self.assertEqual(full["needs"], 1)
            doc = open(full["full"], encoding="utf-8").read()
            self.assertIn("5. 팀 Agentic AI 니즈 후보", doc)
            self.assertIn(data["needs"][0]["name"], doc)
            self.assertIn("표기 2종 통합", doc)
            for s in ("계획 과제 하나", "적합률", "AL1"):
                self.assertNotIn(s, doc, s)                                   # LM28 묶음의 과제 매칭은 싣지 않는다
            mine = [p for p in glob.glob(os.path.join(share, team_report.MEMBER_HTML_DIR, "**", "*.html"), recursive=True)
                    if "홍길동" in os.path.basename(p)]
            self.assertTrue(mine, "인별 복원 리포트 없음")
            mdoc = open(mine[0], encoding="utf-8").read()
            self.assertIn("4. Agentic AI 니즈 후보", mdoc)
            self.assertIn("시험 결과 → 보고서 초안", mdoc)
        src = _src("team_report.py")
        for s in ("9. 과제별 워크플로우", "8-1. 담당자", "8-2. 담당 업무 활동 간트"):
            self.assertIn(s, src, s)
        self.assertNotIn("Agentic AI 과제 적합률", src)


# ── 가드 + 되살림: 보고서 · 설정 ─────────────────────────────────────────────────────────────────
class Reports(unittest.TestCase):
    def test_freeze(self):
        import freeze
        self.assertIn("/api/agentic", freeze.FREEZE_EPS)
        src = _src("freeze.py")
        self.assertIn('"agentic": {"kind": "needs", "new": ag_new}', src)   # 데이터 섬 계약 키 — 니즈 후보만
        self.assertIn("4. Agentic AI 니즈 후보", src)
        self.assertIn("5. 근무 꼬리표", src)
        self.assertIn("n0=6)", src)
        self.assertNotIn("Agentic AI 과제 매칭", src)

    def test_report_out(self):
        import report_out
        self.assertFalse(hasattr(report_out, "_task_count"))
        src = _src("report_out.py")
        for s in ("7. Agentic AI 니즈 후보", "8. 산정 근거와 신뢰도", "9. raw 단서", "n0=10)", "공통업무 — 표준화·자동화 후보"):
            self.assertIn(s, src, s)
        self.assertNotIn("Agentic AI 과제 매칭", src)


class Config(unittest.TestCase):
    def _cfg(self, fn):
        with open(os.path.join(ROOT, "config", fn), encoding="utf-8-sig") as f:
            return json.load(f)

    def test_keys(self):
        c = self._cfg("config.default.json")
        self.assertEqual(c["agentic"], {"domainHint": "", "ruleRowShare": 0.8})   # 과제 목록 없음
        self.assertIn("니즈 후보", c["_agentic_설명"])
        self.assertNotIn("agentic_tasks", c["_agentic_설명"])
        for fn in ("config.default.json", "config.json"):
            self.assertEqual(self._cfg(fn)["copilotAuto"]["agenticMaxWork"], 60, fn)
            with open(os.path.join(ROOT, "config", fn), "rb") as f:
                self.assertTrue(f.read(3) == b"\xef\xbb\xbf", fn)               # BOM 유지

    def test_flow_rule_share_default(self):
        import flow
        self.assertEqual(flow.RULE_SHARE, 0.8)
        self.assertEqual(agentic.RULE_ROW_SHARE, flow.RULE_SHARE)


if __name__ == "__main__":
    unittest.main()
