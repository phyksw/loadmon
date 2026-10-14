# -*- coding: utf-8 -*-
r"""tests\test_p13_flow.py — 담당자 워크플로우 미생성(이슈 D) 보강. LM29 — Agentic 매칭(agentic.py)을 빼며 그 시험도 뺐다.

  · flow    : 일시 오류 1회 → 쉬고 한 번 더 / 전부 실패 → rc 1 · 상태 파일 failed·stop.kind fail · 사유 ≠ '파싱 실패' /
              마감이 이미 지남 → stop_kind budget(run_ai_stage 재시도 없음) / 지난 흐름 키를 오늘 키로 스냅해 이어받기 ·
              flows 객체·문자열 단계 수용 / 정제본 없이도 원본 mm_rows 의 Level 1 로 상위 · 규칙 판정 단위는 묻지 않음 /
              세부 병합 왕복은 마감·연속 2실패에서 접고 판정이 Copilot 문제로 중단된 직후엔 건너뜀
  · run.py  : 선예약(워크플로우) 마감 · run_ai_stage --carry · flow 재시도 --no-merge · 120초 대기 · stop_kind 재시도 생략
실제 Copilot·Edge 는 쓰지 않는다 — judge.copilot_send 를 가짜로 바꾸고, 운영 폴더 대신 임시 폴더(flow.ROOT·
details 캐시 경로)를 쓴다. G3 문맥은 시험용(빈 Ctx + 가짜 카나리아 하나)으로 고정한다.
"""
import contextlib
import csv
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

import _boot  # noqa: F401  — 경로 등록

import copilot_auto as ca  # noqa: E402
import privacy  # noqa: E402
import judge  # noqa: E402
import details  # noqa: E402
import budget as budget_mod  # noqa: E402
import flow  # noqa: E402
import run as R  # noqa: E402

CANARY = "zzcanaryzz"                 # 시험용 카나리아(실재하지 않는 값)
MM_COLS = ["Function", "Level 1", "제품", "유형", "Level 2", "Level 3", "이름", "상세설명",
           "share", "mm", "근거", "확신도", "활동일수"]
SIG_COLS = ["time", "source", "who", "project", "activity", "weight", "text",
            "model", "worktype", "detail", "judge", "flag"]
STEP3 = [{"order": i, "name": f"단계{i}", "desc": "설명", "evidence": "근거", "cycle": "수시", "agent": "중",
          "agent_how": "방안"} for i in (1, 2, 3)]


def _mm_row(l2, l3, mm, l1="개발", kind="개발", desc=""):
    return {"Level 1": l1, "유형": kind, "Level 2": l2, "Level 3": l3, "상세설명": desc,
            "share": "0.1", "mm": str(mm), "근거": "메일3", "확신도": "중", "활동일수": "3"}


def _sigs(l2, l3, n=3, judge_v="AI", day0=5):
    return [{"time": f"2026-01-{day0 + i:02d} 10:00", "source": "메일(발신)", "who": "나", "project": l2,
             "activity": l3, "weight": "1", "text": f"{l3} 진행 {i}", "model": l2, "worktype": "개발",
             "detail": l3, "judge": judge_v, "flag": ""} for i in range(n)]


class _Env(unittest.TestCase):
    TAG = "20260101-20260131"
    D0, D1 = "2026-01-01", "2026-01-31"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t13_")
        self.tmp = self._tmp.name
        self.rep = os.path.join(self.tmp, "report")
        os.makedirs(self.rep)
        os.makedirs(os.path.join(self.tmp, "config"))
        self.wjson(os.path.join(self.tmp, "config", "config.json"), {})
        ca._PRIV.clear()
        ca._PRIV.update(cfg={}, ctx=privacy.Ctx(), cans=(CANARY,))
        self.calls, self.sleeps, self.bad = [], [], []
        self.reply = None                          # (prompt, name) → 드라이버 결과 dict
        self._patches = [
            mock.patch.object(flow, "ROOT", self.tmp),
            mock.patch.object(details, "ALIAS_FILE", os.path.join(self.tmp, "config", "detail_aliases.json")),
            mock.patch.object(details, "LEGACY_ALIAS_FILE", os.path.join(self.tmp, "report", "옛", "detail_aliases.json")),
            mock.patch.object(details, "PROJ_ALIAS_FILE", os.path.join(self.tmp, "config", "project_aliases.json")),
            mock.patch.object(judge, "copilot_send", self._send),
            mock.patch.object(judge, "note_bad_reply", lambda: self.bad.append(1)),
            mock.patch.object(time, "sleep", lambda s: self.sleeps.append(s)),
            # flow 의 쉬기는 판정 모듈의 쉬는 시간 합계(judge.wait_room·note_waited)를 함께 쓴다 — 시험마다 새로
            mock.patch.object(judge, "_COOLED", [0.0]),
            mock.patch.dict(os.environ, {}),
        ]
        for p in self._patches:
            p.start()
        for k in ("LM_AI_DEADLINE", "LM_RUN_ID"):
            os.environ.pop(k, None)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        ca._PRIV.clear()
        self._tmp.cleanup()

    # ── 도우미 ──
    def wjson(self, path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def rjson(self, name):
        with open(os.path.join(self.rep, name), encoding="utf-8-sig") as f:
            return json.load(f)

    def wcsv(self, name, cols, rows):
        with open(os.path.join(self.rep, name), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})

    def data(self, rows, sigs, tag=None, refined=None, rmap=None):
        tag = tag or self.TAG
        self.wcsv(f"mm_rows_{tag}.csv", MM_COLS, rows)
        self.wcsv(f"signals_{tag}.csv", SIG_COLS, sigs)
        if refined is not None:
            self.wcsv(f"mm_rows_{tag}_refined.csv", MM_COLS, refined)
            self.wjson(os.path.join(self.rep, f"refine_map_{tag}.json"), {"tag": tag, "map": rmap or {}})

    def _send(self, prompt, tag, name, fresh=None):
        # sender 계약(judge.copilot_send) — tag 자리가 '<기간>-<묶음 이름>', name 자리가 단계(flow)
        self.calls.append((tag, prompt))
        return self.reply(prompt, tag)

    def run_main(self, mod, *extra, d1=None):
        argv = [f"{mod.__name__}.py", "--from", self.D0, "--to", d1 or self.D1] + list(extra)
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
            rc = mod.main()
        out = buf.getvalue()
        last = [ln for ln in out.splitlines() if ln.startswith("{") and ln.rstrip().endswith("}")]
        return rc, (json.loads(last[-1]) if last else {}), out


def _ok(obj):
    return {"ok": True, "reply": json.dumps(obj, ensure_ascii=False)}


class FlowRuns(_Env):
    def _data(self, rule=True):
        rows = [_mm_row("모듈 설계", "구조시뮬레이션", 2.0), _mm_row("모듈 설계", "부품 시험", 1.0)]
        sigs = _sigs("모듈 설계", "구조시뮬레이션", n=4) + _sigs("모듈 설계", "부품 시험", n=4, day0=12)
        if rule:
            rows.append(_mm_row("공통", "기타", 3.0, l1="공통", kind="사무"))
            sigs += _sigs("공통", "기타", n=5, judge_v="규칙", day0=20)
        self.data(rows, sigs)

    @staticmethod
    def _flows(prompt):
        keys = re.findall(r"^## (.+?)  \(신호 \d+건\)", prompt, re.M)
        return _ok({"flows": [{"key": k, "role": "실무", "summary": "요약", "steps": STEP3} for k in keys]})

    def test_cooldown_then_ok(self):
        self._data()
        seq = [{"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류"}]
        self.reply = lambda p, n: seq.pop(0) if seq else self._flows(p)
        rc, js, _out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 0, js)
        self.assertEqual([n for n, _p in self.calls], [f"{self.TAG}-wf1", f"{self.TAG}-wf1-c"])
        self.assertEqual(self.sleeps, [90.0])
        w = self.rjson(f"workflow_{self.TAG}.json")
        self.assertEqual(sorted(f["model"] for f in w["flows"]), ["모듈 설계 / 구조시뮬레이션", "모듈 설계 / 부품 시험"])
        self.assertTrue(all(f["asked_at"] == time.strftime("%Y-%m-%d") for f in w["flows"]))
        self.assertTrue(all(f["level1"] == "개발" for f in w["flows"]))       # 정제본 없이도 원본 Level 1 로 상위
        self.assertEqual(w["rule_units_count"], 1)                             # '공통 / 기타'(규칙 판정)는 묻지 않았다
        self.assertNotIn("## 공통 / 기타", self.calls[0][1])
        self.assertEqual(w["cooldowns"], 1)

    def test_all_fail_reports_real_reason(self):
        self._data(rule=False)
        self.reply = lambda p, n: {"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류"}
        rc, js, _out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 1)
        self.assertNotEqual(js["error"], "파싱 실패")
        self.assertEqual(js["stop_kind"], "fail")
        st = json.load(open(os.path.join(self.rep, f"stage_state_{self.TAG}_flow.json"), encoding="utf-8"))
        self.assertEqual((st["state"], st["stop"]["kind"]), ("failed", "fail"))
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"workflow_{self.TAG}.json")))

    def test_budget_passed_and_no_retry(self):
        self._data(rule=False)
        self.reply = lambda p, n: self._flows(p)
        with mock.patch.object(budget_mod, "stage_budget", lambda **kw: (time.monotonic() - 5, 1.0)):
            rc, js, _out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 1)
        self.assertEqual(js["stop_kind"], "budget")
        self.assertEqual(self.calls, [])
        st = json.load(open(os.path.join(self.rep, f"stage_state_{self.TAG}_flow.json"), encoding="utf-8"))
        self.assertEqual(st["stop"]["kind"], "budget")
        # run.py 는 같은 벽(시간 예산)에 다시 닿을 재시도를 하지 않는다
        cmds = []

        def cap(cmd, env):
            cmds.append(cmd)
            R.LAST_JSON.clear()
            R.LAST_JSON.update(js)
            return 1, "시간 예산 초과 — 보내지 못한 업무가 남음"
        with mock.patch.object(R, "_run_capture", cap), contextlib.redirect_stdout(io.StringIO()):
            rc2, _note = R.run_ai_stage("flow.py", self.D0, self.D1)
        self.assertEqual((rc2, len(cmds)), (1, 1))
        self.assertEqual(self.sleeps, [])

    def test_resolver_keeps_prev_and_odd_shapes(self):
        self._data(rule=False)
        today = time.strftime("%Y-%m-%d")
        self.wjson(os.path.join(self.rep, f"workflow_{self.TAG}.json"),
                   {"ok": True, "tag": self.TAG, "unit": "과제/담당업무", "generated": f"{today} 09:00",
                    "flows": [{"model": "모듈설계 / 구조 시뮬레이션", "role": "주도", "summary": "s", "steps": STEP3}]})
        # 답이 flows 를 객체로, 단계를 문장 목록으로 보낸다
        self.reply = lambda p, n: _ok({"flows": {"모듈 설계 / 부품 시험": {"role": "실무", "steps": [
            "1. 시험 계획 정리", "2. 부품 측정", "3. 결과 보고"]}}})
        rc, js, _out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("## 모듈 설계 / 구조시뮬레이션", self.calls[0][1])    # 이어받은 단위는 묻지 않는다
        w = self.rjson(f"workflow_{self.TAG}.json")
        by = {f["model"]: f for f in w["flows"]}
        self.assertEqual(by["모듈 설계 / 구조시뮬레이션"]["role"], "주도")        # 지난 키를 오늘 키로 스냅
        self.assertEqual([s["name"] for s in by["모듈 설계 / 부품 시험"]["steps"]], ["시험 계획 정리", "부품 측정", "결과 보고"])

    def test_carry_other_tag(self):
        self._data(rule=False)
        tag_a = "20260101-20260130"
        self.wjson(os.path.join(self.rep, f"workflow_{tag_a}.json"),
                   {"ok": True, "tag": tag_a, "unit": "과제/담당업무", "generated": "2026-01-30 09:00",
                    "flows": [{"model": "모듈 설계 / 구조시뮬레이션", "role": "주도", "summary": "s", "steps": STEP3,
                               "asked_at": time.strftime("%Y-%m-%d")},
                              {"model": "모듈 설계 / 부품 시험", "role": "검토", "summary": "s", "steps": STEP3,
                               "asked_at": "2020-01-01"}]})
        self.reply = lambda p, n: self._flows(p)
        rc, js, _out = self.run_main(flow, "--no-merge", "--carry")
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("## 모듈 설계 / 부품 시험", self.calls[0][1])             # 오래된 흐름만 다시 묻는다
        self.assertNotIn("## 모듈 설계 / 구조시뮬레이션", self.calls[0][1])
        w = self.rjson(f"workflow_{self.TAG}.json")
        self.assertEqual((w["carried_from"], w["carried"], w["expired"]), (tag_a, 1, 1))

    def test_merge_map_deadline_and_two_failures(self):
        rows = [_mm_row("모듈 설계", "구조시뮬레이션", 2.0), _mm_row("모듈 설계", "부품 시험", 1.0)]
        sent = []

        def sender(prompt, tag, name, fresh=None):
            sent.append(fresh)
            return {"ok": True, "reply": "설명만 있는 답"}             # JSON 없음 — 해석 실패
        with mock.patch.object(details, "merge_batches", lambda secs, budget=None: [[("모듈 설계", "## 모듈 설계")]] * 4):
            details.detail_merge_map(self.TAG, sender, rows=rows, log=lambda m: None, deadline=time.monotonic() - 1)
            self.assertEqual(sent, [])                                         # 마감이 지났으면 묻지 않는다
            details.detail_merge_map(self.TAG, sender, rows=rows, log=lambda m: None)
        self.assertEqual(sent, [None, True])                                   # 2묶음 연속 실패로 접고 · 둘째는 새 채팅

    def test_merge_skipped_after_judge_abort(self):
        self._data(rule=False)
        self.wjson(os.path.join(self.rep, f"ai_judgments_{self.TAG}.json"), {"aborted": True, "abort_kind": "throttle"})
        self.reply = lambda p, n: self._flows(p)
        rc, js, out = self.run_main(flow)
        self.assertEqual(rc, 0, js)
        self.assertFalse(any("-d3-" in n for n, _p in self.calls))
        w = self.rjson(f"workflow_{self.TAG}.json")
        self.assertIn("Copilot 사용량 제한", w["merge_skipped"])

    def test_shapes_and_heads(self):
        self.assertEqual(flow._norm_model("모듈 설계 / 구조 (신호 12건) [상위: 개발]"), flow._norm_model("모듈 설계 / 구조"))
        keys = {"과제A / 설계": {"model": "과제A", "detail": "설계", "mm": 1.0, "signals": 3}}
        got = flow.sanitize_flows({"key": "과제A / 설계 (신호 3건)", "steps": {"1": {"name": "a"}, "2": "b 단계"}}, keys)
        self.assertEqual([s["name"] for s in got[0]["steps"]], ["a", "b 단계"])
        self.assertEqual(flow._key_resolver(keys)("과제A/설계"), "과제A / 설계")


class RunStage(unittest.TestCase):
    def test_reserves_and_deadlines(self):
        self.assertEqual(R.flow_reserve({}, 300), 120.0)
        self.assertEqual(R.flow_reserve({}, 100), 60.0)                    # 바닥 60분
        self.assertEqual(R.flow_reserve({"flowBudgetMin": 90}, 300), 90.0)
        self.assertFalse(hasattr(R, "agentic_deadline"))                   # LM29 — Agentic 몫 선예약 없음
        old = (R._AI_T0, R._AI_TOT_MIN, dict(R._AI_RES))
        with mock.patch.dict(os.environ, {}):
            try:
                fr, pre = R.start_ai_clock({"agenticReserveMin": 20}, 300, now=1000.0)   # 옛 키는 무시
                self.assertEqual((fr, pre), (120.0, 180.0))
                self.assertAlmostEqual(float(os.environ["LM_AI_DEADLINE"]), 1000.0 + 180 * 60)
                self.assertEqual(R._AI_RES, {"flow": 120.0})
            finally:
                R._AI_T0, R._AI_TOT_MIN = old[0], old[1]
                R._AI_RES.clear()
                R._AI_RES.update(old[2])

    def _stage(self, script, results, last=None):
        cmds, sleeps = [], []

        def cap(cmd, env):
            cmds.append(list(cmd))
            R.LAST_JSON.clear()
            R.LAST_JSON.update(last or {})
            return results.pop(0)
        with mock.patch.object(R, "_run_capture", cap), mock.patch.object(R.time, "sleep", sleeps.append), \
                contextlib.redirect_stdout(io.StringIO()):
            rc, note = R.run_ai_stage(script, "2026-01-01", "2026-01-31")
        return rc, note, cmds, sleeps

    def test_carry_retry_wait_and_no_merge(self):
        rc, note, cmds, sleeps = self._stage("flow.py", [(1, "Copilot 일시 오류"), (0, "")])
        self.assertEqual((rc, note), (0, "1회 재시도 후 성공"))
        self.assertIn("--carry", cmds[0])
        self.assertNotIn("--no-merge", cmds[0])
        self.assertIn("--no-merge", cmds[1])
        self.assertEqual(sleeps, [120])
        rc, _n, cmds, sleeps = self._stage("flow.py", [(1, "x"), (1, "y")])
        self.assertEqual(rc, 1)
        self.assertIn("--carry", cmds[1])
        self.assertIn("--no-merge", cmds[1])
        self.assertEqual(R.AI2_STAGES, ("flow.py",))                        # LM29 — agentic.py 단계 없음
        rc, _n, cmds, _s = self._stage("refine.py", [(1, "x"), (0, "")])
        self.assertNotIn("--carry", cmds[0])

    def test_no_retry_kinds(self):
        for last, why in (({"stop_kind": "gate"}, "관문"), ({"stop_kind": "login"}, "로그인"),
                          ({}, "Copilot 사용량 제한(일시)"), ({}, "R-THROTTLE 사유")):
            rc, _n, cmds, sleeps = self._stage("flow.py", [(1, why)], last)
            self.assertEqual((rc, len(cmds), sleeps), (1, 1, []), why)


if __name__ == "__main__":
    unittest.main()
