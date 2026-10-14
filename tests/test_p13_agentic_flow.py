# -*- coding: utf-8 -*-
r"""tests\test_p13_agentic_flow.py — Agentic 매칭 MM 급감·담당자 워크플로우 미생성(이슈 D) 보강.

  · agentic : 업무 #번호 매칭('70%' 적합률) → 원본 쌍 keys · load_mm = 원본 MM 합 / 누적 번호 80개 → keys 80 · 표시 work 상한 /
              정제본 삭제 뒤 recalc_file → load_mm 그대로(키 축) · 옛 결과(키 없음)는 이름 대조 / 오할당 '#3' → '과제/세부업무' /
              카나리아가 든 행 하나만 관문 · 나머지는 보냄 / 규칙 판정 80% 이상 행은 보내지 않음(rule_mm) /
              --carry 로 다른 기간 결과 이어받기(왕복 0) · --carry 없이 다 끝난 결과면 처음부터 / 일시 오류 1회 → 쉬고 같은 묶음
              한 번 더(분할 없음) · 해석 실패 → note_bad_reply
  · flow    : 일시 오류 1회 → 쉬고 한 번 더 / 전부 실패 → rc 1 · 상태 파일 failed·stop.kind fail · 사유 ≠ '파싱 실패' /
              마감이 이미 지남 → stop_kind budget(run_ai_stage 재시도 없음) / 지난 흐름 키를 오늘 키로 스냅해 이어받기 ·
              flows 객체·문자열 단계 수용 / 정제본 없이도 원본 mm_rows 의 Level 1 로 상위 · 규칙 판정 단위는 묻지 않음 /
              세부 병합 왕복은 마감·연속 2실패에서 접고 판정이 Copilot 문제로 중단된 직후엔 건너뜀
  · run.py  : 선예약(워크플로우·Agentic) 마감 · run_ai_stage --carry · flow 재시도 --no-merge · 120초 대기 · stop_kind 재시도 생략
실제 Copilot·Edge 는 쓰지 않는다 — judge.copilot_send 를 가짜로 바꾸고, 운영 폴더 대신 임시 폴더(agentic.ROOT·flow.ROOT·
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
import agentic  # noqa: E402
import flow  # noqa: E402
import run as R  # noqa: E402

CANARY = "zzcanaryzz"                 # 시험용 카나리아(실재하지 않는 값)
MM_COLS = ["Function", "Level 1", "제품", "유형", "Level 2", "Level 3", "이름", "상세설명",
           "share", "mm", "근거", "확신도", "활동일수"]
SIG_COLS = ["time", "source", "who", "project", "activity", "weight", "text",
            "model", "worktype", "detail", "judge", "flag"]
TASKS = {"axes": {"축1": "시험 축"},
         "tasks": [{"id": "AL1", "axis": "축1", "name": "설계 검토 자동화", "desc": "설계 문서를 읽어 검토 의견을 만든다"},
                   {"id": "AL2", "axis": "축1", "name": "시험 보고 자동화", "desc": "시험 결과로 보고서 초안을 만든다"}]}
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
        self.wjson(os.path.join(self.tmp, "config", "config.json"), {"agentic": {"domainHint": ""}})
        self.wjson(os.path.join(self.tmp, "config", "agentic_tasks.json"), TASKS)
        ca._PRIV.clear()
        ca._PRIV.update(cfg={}, ctx=privacy.Ctx(), cans=(CANARY,))
        self.calls, self.sleeps, self.bad = [], [], []
        self.reply = None                          # (prompt, name) → 드라이버 결과 dict
        self._patches = [
            mock.patch.object(agentic, "ROOT", self.tmp),
            mock.patch.object(flow, "ROOT", self.tmp),
            mock.patch.object(details, "ALIAS_FILE", os.path.join(self.tmp, "config", "detail_aliases.json")),
            mock.patch.object(details, "LEGACY_ALIAS_FILE", os.path.join(self.tmp, "report", "옛", "detail_aliases.json")),
            mock.patch.object(details, "PROJ_ALIAS_FILE", os.path.join(self.tmp, "config", "project_aliases.json")),
            mock.patch.object(judge, "copilot_send", self._send),
            mock.patch.object(judge, "note_bad_reply", lambda: self.bad.append(1)),
            mock.patch.object(time, "sleep", lambda s: self.sleeps.append(s)),
            # agentic·flow 의 쉬기는 판정 모듈의 쉬는 시간 합계(judge.wait_room·note_waited)를 함께 쓴다 — 시험마다 새로
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
        # sender 계약(judge.copilot_send) — tag 자리가 '<기간>-<묶음 이름>', name 자리가 단계(agentic·flow)
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


def _ids(prompt):
    return [int(x) for x in re.findall(r"^· #(\d+) ", prompt, re.M)]


def _ok(obj):
    return {"ok": True, "reply": json.dumps(obj, ensure_ascii=False)}


class AgenticMatch(_Env):
    ROWS = [_mm_row("프로젝트A", "설계 검토", 2.0), _mm_row("프로젝트A", "회로 시뮬레이션", 1.5),
            _mm_row("Alpha-X", "시험 보고", 1.0, kind="사무"), _mm_row("Alpha-X", "일정 협의", 0.5, kind="협업")]

    def _sigs(self, rule_pair=None):
        out = []
        for i, r in enumerate(self.ROWS):
            pair = (r["Level 2"], r["Level 3"])
            out += _sigs(*pair, judge_v="규칙" if pair == rule_pair else "AI", day0=3 + i * 4)
        return out

    def test_ids_fit_percent_keys_plain_mm(self):
        self.data(self.ROWS, self._sigs())
        self.reply = lambda p, n: _ok({"match": [{"task": "AL1", "fit": "70%", "work": ["#1", "#2"],
                                                  "reason": "설계 검토 반복"}],
                                       "misassigned": [{"row": "#3", "reason": "참조 위주"}]})
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual(js["stop_kind"], "")
        a = self.rjson(f"agentic_{self.TAG}.json")
        m = next(x for x in a["match"] if x["task"] == "AL1")
        self.assertEqual(m["fit"], 70)                                         # '70%' 가 버려지지 않는다
        sep = details.KEY_SEP
        self.assertEqual(m["keys"], sorted([f"프로젝트A{sep}설계 검토", f"프로젝트A{sep}회로 시뮬레이션"]))
        self.assertAlmostEqual(m["load_mm"], 3.5)
        self.assertEqual(a["mm_recalc"]["axis"], "plain")
        prompt = self.calls[0][1]
        self.assertIn("· #1 프로젝트A / 설계 검토 / 개발", prompt)
        self.assertNotIn("신호 메일", prompt)                                   # 신호 근거 꼬리는 뺐다
        self.assertNotIn("MM", re.sub(r"\(MM 순\)", "", prompt))
        # 오할당 '#3' → '과제/세부업무' — 화면의 [제외](app.exclude_work)는 이 키를 '/' 로 갈라 신호를 찾는다
        self.assertEqual(a["misassigned"][0]["row"], "Alpha-X/시험 보고")
        md, dt = (x.strip() for x in a["misassigned"][0]["row"].split("/", 1))
        sigs = details.read_signals(self.TAG, self.rep)
        self.assertTrue(any((s["model"], s["detail"]) == (md, dt) for s in sigs))
        st = json.load(open(os.path.join(self.rep, f"stage_state_{self.TAG}_agentic.json"), encoding="utf-8"))
        self.assertEqual(st["state"], "done")

    def test_cumulative_ids_uncapped_keys(self):
        rows = [_mm_row("프로젝트A", f"업무 {i:02d}", round(2.0 - i * 0.01, 3)) for i in range(80)]
        sigs = [s for r in rows for s in _sigs(r["Level 2"], r["Level 3"], n=1)]
        self.data(rows, sigs)
        self.wjson(os.path.join(self.tmp, "config", "config.json"),
                   {"agentic": {"domainHint": ""}, "copilotAuto": {"agenticMaxWork": 60}})
        seen = set()

        def reply(p, n):                                   # 같은 채팅이 앞 목록을 되풀이 — 누적 번호
            seen.update(_ids(p))
            return _ok({"match": [{"task": "AL1", "fit": 80, "work": [f"#{i}" for i in sorted(seen)]}]})
        self.reply = reply
        with mock.patch.object(agentic, "ROOT", self.tmp):
            base = len(agentic.ag_prompt(TASKS["tasks"], [], {})) + agentic.OVERLAY_CHARS
        rc, js, _out = self.run_main(agentic, "--budget", str(base + 1100))
        self.assertEqual(rc, 0, js)
        self.assertGreaterEqual(len(self.calls), 3)
        m = self.rjson(f"agentic_{self.TAG}.json")["match"][0]
        self.assertEqual(len(m["keys"]), 80)                                  # 근거 키는 상한 없음
        self.assertLessEqual(len(m["work"]), 60)                               # 표시 이름만 agenticMaxWork
        self.assertAlmostEqual(m["load_mm"], round(sum(float(r["mm"]) for r in rows), 3), places=3)

    def test_recalc_after_refined_removed_and_legacy(self):
        refined = [_mm_row("프로젝트A", "설계 검토 및 시뮬레이션", 3.5), _mm_row("Alpha-X", "시험 보고", 1.0, kind="사무"),
                   _mm_row("Alpha-X", "일정 협의", 0.5, kind="협업")]
        rmap = {"프로젝트A/설계 검토 및 시뮬레이션": [["프로젝트A", "설계 검토"], ["프로젝트A", "회로 시뮬레이션"]],
                "Alpha-X/시험 보고": [["Alpha-X", "시험 보고"]], "Alpha-X/일정 협의": [["Alpha-X", "일정 협의"]]}
        self.data(self.ROWS, self._sigs(), refined=refined, rmap=rmap)
        self.reply = lambda p, n: _ok({"match": [{"task": "AL1", "fit": 60, "work": ["#1"]}]})
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertIn("· #1 프로젝트A / 설계 검토 및 시뮬레이션", self.calls[0][1])
        a = self.rjson(f"agentic_{self.TAG}.json")
        self.assertEqual(a["rows_file"], f"mm_rows_{self.TAG}_refined.csv")
        self.assertAlmostEqual(a["match"][0]["load_mm"], 3.5)
        # 오할당 제외가 정제본·매핑을 지운 뒤의 재계산 — 키가 원본 축이라 load_mm 이 그대로다
        os.remove(os.path.join(self.rep, f"mm_rows_{self.TAG}_refined.csv"))
        os.remove(os.path.join(self.rep, f"refine_map_{self.TAG}.json"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(agentic.recalc_file(self.TAG, self.rep, log=lambda m: None))
        a2 = self.rjson(f"agentic_{self.TAG}.json")
        self.assertAlmostEqual(a2["match"][0]["load_mm"], 3.5)
        self.assertEqual(a2["mm_recalc"]["rows_file"], f"mm_rows_{self.TAG}.csv")
        self.assertEqual(a2["mm_recalc"]["axis"], "plain")
        # 키 없는 옛 결과는 예전처럼 이름으로 찾는다
        self.wjson(os.path.join(self.rep, f"agentic_{self.TAG}.json"),
                   {"tag": self.TAG, "match": [{"task": "AL1", "fit": 60, "work": ["회로 시뮬레이션"], "reason": "r"}]})
        self.assertTrue(agentic.recalc_file(self.TAG, self.rep, log=lambda m: None))
        a3 = self.rjson(f"agentic_{self.TAG}.json")
        self.assertAlmostEqual(a3["match"][0]["load_mm"], 1.5)
        self.assertEqual(a3["mm_recalc"]["axis"], "rows")

    def test_gate_one_row_only(self):
        rows = list(self.ROWS) + [_mm_row(f"{CANARY} 과제", "자료 정리", 0.7)]
        self.data(rows, self._sigs())
        self.reply = lambda p, n: _ok({"match": [{"task": "AL1", "fit": 50, "work": [f"#{i}" for i in _ids(p)]}]})
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn(CANARY, self.calls[0][1])
        self.assertEqual(len(_ids(self.calls[0][1])), 4)                      # 나머지 4행은 그대로 보냈다
        a = self.rjson(f"agentic_{self.TAG}.json")
        self.assertEqual(a["gate_skipped_rows"], 1)
        self.assertEqual(a["rows_pending"], 0)
        self.assertEqual(len(a["match"][0]["keys"]), 4)
        self.assertAlmostEqual(a["mm_recalc"]["gate_mm"], 0.7)

    def test_rule_rows_not_sent(self):
        self.data(self.ROWS, self._sigs(rule_pair=("Alpha-X", "일정 협의")))
        self.reply = lambda p, n: _ok({"match": [{"task": "AL1", "fit": 50, "work": [f"#{i}" for i in _ids(p)]}]})
        rc, js, out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertNotIn("일정 협의", self.calls[0][1])
        a = self.rjson(f"agentic_{self.TAG}.json")
        self.assertEqual(a["rule_rows"], 1)
        self.assertEqual(a["rows_pending"], 0)
        self.assertEqual(a["rows_rule"], ["Alpha-X|일정 협의|협업"])
        self.assertAlmostEqual(a["mm_recalc"]["rule_mm"], 0.5)
        self.assertEqual(a["mm_recalc"]["rule_rows"], 1)
        self.assertIn("AI 판정 대기", out)
        self.assertEqual(details.rule_share(self._sigs(rule_pair=("Alpha-X", "일정 협의")))[("Alpha-X", "일정 협의")], (3, 3))

    def test_carry_other_tag_and_full_rematch_without_carry(self):
        tag_a = "20260101-20260130"
        self.data(self.ROWS, self._sigs(), tag=tag_a)
        self.reply = lambda p, n: _ok({"match": [{"task": "AL1", "fit": 50, "work": [f"#{i}" for i in _ids(p)]}]})
        rc, js, _out = self.run_main(agentic, d1="2026-01-30")
        self.assertEqual(rc, 0, js)
        n1 = len(self.calls)
        # 다음 날 — MM 이 바뀐 같은 업무 행(식별자에 MM 이 없어 이어진다)
        rows_b = [dict(r, mm=str(float(r["mm"]) * 2)) for r in self.ROWS]
        self.data(rows_b, self._sigs())
        rc, js, _out = self.run_main(agentic, "--carry")
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), n1)                                  # 왕복 0
        self.assertEqual(js["carried_from"], tag_a)
        b = self.rjson(f"agentic_{self.TAG}.json")
        self.assertEqual(b["carried_from"], tag_a)
        self.assertEqual(b["matched_since"], time.strftime("%Y-%m-%d"))
        self.assertAlmostEqual(b["match"][0]["load_mm"], 10.0)                 # 새 MM 으로 다시 셌다
        # 화면 [재매칭](--carry 없음)은 다 끝난 결과면 처음부터 다시 묻는다
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertGreater(len(self.calls), n1)

    def test_cooldown_once_no_split(self):
        self.data(self.ROWS, self._sigs())
        seq = [{"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류"}]

        def reply(p, n):
            return seq.pop(0) if seq else _ok({"match": [{"task": "AL2", "fit": 40, "work": ["#3"]}]})
        self.reply = reply
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertEqual([n for n, _p in self.calls], [f"{self.TAG}-ag1", f"{self.TAG}-ag1-c"])   # 반분 없음
        self.assertEqual(self.sleeps, [90.0])                                  # 쉬기는 정확히 한 번
        a = self.rjson(f"agentic_{self.TAG}.json")
        self.assertEqual(a["cooldowns"], 1)
        self.assertEqual(a["match"][0]["task"], "AL2")

    def test_driver_cooled_or_hard_is_respected(self):
        self.data(self.ROWS, self._sigs())
        self.reply = lambda p, n: {"ok": False, "phase": "copilot_error", "error": "제한", "cooldowns": 2}
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 1)
        self.assertEqual(self.sleeps, [])                                      # 드라이버가 이미 쉬었다
        self.calls.clear()
        self.reply = lambda p, n: {"ok": False, "phase": "throttled", "error": "Copilot 사용량 제한(일시)", "hard": True}
        rc, js, _out = self.run_main(agentic, "--budget", "1500")
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.calls), 1)                                   # hard — 그 자리에서 멈춘다
        self.assertEqual(js["stop_kind"], "throttle")

    def test_parse_failure_fresh_chat_and_split(self):
        self.data(self.ROWS, self._sigs())
        seq = [{"ok": True, "reply": "표로 정리하면 다음과 같습니다"}]

        def reply(p, n):
            return seq.pop(0) if seq else _ok({"match": [{"task": "AL1", "fit": 50, "work": [f"#{i}" for i in _ids(p)]}]})
        self.reply = reply
        rc, js, _out = self.run_main(agentic)
        self.assertEqual(rc, 0, js)
        self.assertTrue(self.bad)                                              # 다음 왕복은 새 채팅에서
        self.assertEqual(self.sleeps, [])
        self.assertIn(f"{self.TAG}-ag1-1", [n for n, _p in self.calls])        # 해석 실패는 반분

    def test_helpers(self):
        self.assertEqual([agentic._fit(v) for v in ("70%", 0.7, "상", "약 55점", None, "x")], [70, 70, 80, 55, 0, 0])
        self.assertEqual(agentic._clean_list("#1, #2;#3", cap=0), ["#1", "#2", "#3"])
        self.assertEqual(agentic._clean_list([{"id": "#4"}, "#5, #6"], cap=0), ["#4", "#5", "#6"])
        tmap = {t["id"]: t for t in TASKS["tasks"]}
        res = agentic._task_resolver(tmap)
        self.assertEqual([res("al-1"), res("시험 보고 자동화"), res("AL2: 보고서"), res("다른 과제")],
                         ["AL1", "AL2", "AL2", ""])
        self.assertEqual(agentic._sig_norm("A|B|개발|0.123"), "A|B|개발")


class FlowRuns(_Env):
    def _data(self, rule=True):
        rows = [_mm_row("모듈 설계", "회로시뮬레이션", 2.0), _mm_row("모듈 설계", "내구 시험", 1.0)]
        sigs = _sigs("모듈 설계", "회로시뮬레이션", n=4) + _sigs("모듈 설계", "내구 시험", n=4, day0=12)
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
        self.assertEqual(sorted(f["model"] for f in w["flows"]), ["모듈 설계 / 내구 시험", "모듈 설계 / 회로시뮬레이션"])
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
                    "flows": [{"model": "모듈설계 / 회로 시뮬레이션", "role": "주도", "summary": "s", "steps": STEP3}]})
        # 답이 flows 를 객체로, 단계를 문장 목록으로 보낸다
        self.reply = lambda p, n: _ok({"flows": {"모듈 설계 / 내구 시험": {"role": "실무", "steps": [
            "1. 시험 계획 정리", "2. 내구 측정", "3. 결과 보고"]}}})
        rc, js, _out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("## 모듈 설계 / 회로시뮬레이션", self.calls[0][1])    # 이어받은 단위는 묻지 않는다
        w = self.rjson(f"workflow_{self.TAG}.json")
        by = {f["model"]: f for f in w["flows"]}
        self.assertEqual(by["모듈 설계 / 회로시뮬레이션"]["role"], "주도")        # 지난 키를 오늘 키로 스냅
        self.assertEqual([s["name"] for s in by["모듈 설계 / 내구 시험"]["steps"]], ["시험 계획 정리", "내구 측정", "결과 보고"])

    def test_carry_other_tag(self):
        self._data(rule=False)
        tag_a = "20260101-20260130"
        self.wjson(os.path.join(self.rep, f"workflow_{tag_a}.json"),
                   {"ok": True, "tag": tag_a, "unit": "과제/담당업무", "generated": "2026-01-30 09:00",
                    "flows": [{"model": "모듈 설계 / 회로시뮬레이션", "role": "주도", "summary": "s", "steps": STEP3,
                               "asked_at": time.strftime("%Y-%m-%d")},
                              {"model": "모듈 설계 / 내구 시험", "role": "검토", "summary": "s", "steps": STEP3,
                               "asked_at": "2020-01-01"}]})
        self.reply = lambda p, n: self._flows(p)
        rc, js, _out = self.run_main(flow, "--no-merge", "--carry")
        self.assertEqual(rc, 0, js)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("## 모듈 설계 / 내구 시험", self.calls[0][1])             # 오래된 흐름만 다시 묻는다
        self.assertNotIn("## 모듈 설계 / 회로시뮬레이션", self.calls[0][1])
        w = self.rjson(f"workflow_{self.TAG}.json")
        self.assertEqual((w["carried_from"], w["carried"], w["expired"]), (tag_a, 1, 1))

    def test_merge_map_deadline_and_two_failures(self):
        rows = [_mm_row("모듈 설계", "회로시뮬레이션", 2.0), _mm_row("모듈 설계", "내구 시험", 1.0)]
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
        self.assertEqual(flow._norm_model("모듈 설계 / 회로 (신호 12건) [상위: 개발]"), flow._norm_model("모듈 설계 / 회로"))
        keys = {"과제A / 설계": {"model": "과제A", "detail": "설계", "mm": 1.0, "signals": 3}}
        got = flow.sanitize_flows({"key": "과제A / 설계 (신호 3건)", "steps": {"1": {"name": "a"}, "2": "b 단계"}}, keys)
        self.assertEqual([s["name"] for s in got[0]["steps"]], ["a", "b 단계"])
        self.assertEqual(flow._key_resolver(keys)("과제A/설계"), "과제A / 설계")


class RunStage(unittest.TestCase):
    def test_reserves_and_deadlines(self):
        self.assertEqual(R.ai_reserves({}, 300), (120.0, 30.0))
        self.assertEqual(R.ai_reserves({"agenticReserveMin": 20}, 300)[1], 20.0)
        self.assertEqual(R.ai_reserves({}, 100), (60.0, 15.0))
        old = (R._AI_T0, R._AI_TOT_MIN, dict(R._AI_RES))
        with mock.patch.dict(os.environ, {}):
            try:
                fr, ag, pre = R.start_ai_clock({}, 300, now=1000.0)
                self.assertEqual((fr, ag, pre), (120.0, 30.0, 150.0))
                self.assertAlmostEqual(float(os.environ["LM_AI_DEADLINE"]), 1000.0 + 150 * 60)
                late = 1000.0 + 175 * 60                                   # 판정·정제가 늦게 끝났다
                self.assertGreaterEqual(R.agentic_deadline(now=late), late + 30 * 60)
                early = 1000.0 + 60 * 60                                   # 일찍 끝났으면 남은 시간을 다 쓴다
                self.assertAlmostEqual(R.agentic_deadline(now=early), 1000.0 + 180 * 60)
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
        rc, _n, cmds, sleeps = self._stage("agentic.py", [(1, "x"), (1, "y")])
        self.assertEqual(rc, 1)
        self.assertIn("--carry", cmds[1])
        self.assertNotIn("--no-merge", cmds[1])
        rc, _n, cmds, _s = self._stage("refine.py", [(1, "x"), (0, "")])
        self.assertNotIn("--carry", cmds[0])

    def test_no_retry_kinds(self):
        for last, why in (({"stop_kind": "gate"}, "관문"), ({"stop_kind": "login"}, "로그인"),
                          ({}, "Copilot 사용량 제한(일시)"), ({}, "R-THROTTLE 사유")):
            rc, _n, cmds, sleeps = self._stage("agentic.py", [(1, why)], last)
            self.assertEqual((rc, len(cmds), sleeps), (1, 1, []), why)


if __name__ == "__main__":
    unittest.main()
