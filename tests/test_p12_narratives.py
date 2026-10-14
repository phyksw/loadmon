# -*- coding: utf-8 -*-
r"""tests\test_p12_narratives.py — 월별 리뷰 코멘트가 사라지지 않게(이슈 C · judge 쪽).

core/narratives(이월·기간 필터·원자 저장·깨진 자기 파일 보존)와 judge.narrate(빠진 달·최근 달 먼저 · AI 판정이 적은 달은
이전 코멘트 유지 · 과제 이름 대조 완화 · 덮어쓰기 방지 · 관문 줄 빼고 재전송), judge.main(연속 실패 중단 뒤 한 달만 시험 ·
rc 3 이월 · --narrate-only 의 규칙 행 거부·--all)을 시험한다.
실제 Copilot·Edge 를 쓰지 않는다 — judge._transport·g3_prompt·g3_rows 를 가짜로 바꾸고 judge.ROOT 는 임시 폴더다.
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
import narratives  # noqa: E402

CANARY = "zzcanaryzz"                 # 시험용 카나리아(실재하지 않는 값)
TAG = "20260101-20261012"             # 오늘 기간
YDAY = "20260101-20261011"            # 어제 기간(기본 기간 '올해'는 날마다 tag 가 바뀐다)
BAD_REPLY = "형식을 맞추지 못했습니다."


def _ok(reply):
    return {"ok": True, "phase": "replied", "reply": reply}


def _reply(summary="이 달은 회로 설계와 시험 위주", projects=(("Orion-X", "회로 설계 검토와 시험"),)):
    return json.dumps({"summary": summary,
                       "projects": [{"name": n, "story": s, "worktypes": "개발 위주"} for n, s in projects]},
                      ensure_ascii=False)


def _entry(summary, n_ai=None, projects=None, **kw):
    e = {"summary": summary,
         "projects": projects if projects is not None else
         [{"name": "Orion-X", "story": "회로 설계 검토", "worktypes": "개발 위주"}]}
    if n_ai is not None:
        e["n_ai"] = n_ai
    e.update(kw)
    return e


def _write(rep, tag, obj, mtime=None):
    p = os.path.join(rep, f"ai_narratives_{tag}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _load(rep, tag):
    with open(os.path.join(rep, f"ai_narratives_{tag}.json"), encoding="utf-8") as f:
        return json.load(f)


def _rows(month, n_ai, n_rule=0, model="Orion-X"):
    """그 달의 판정된 행 — AI 판정 n_ai 행 + 규칙 n_rule 행(규칙 행 원문에는 '규칙행' 표식)."""
    out = []
    for i in range(n_ai + n_rule):
        ai = i < n_ai
        out.append({"time": f"{month}-{1 + i % 28:02d} {9 + i % 9:02d}:{i % 60:02d}", "source": "메일",
                    "who": "", "model": model if ai else "공통", "worktype": "개발" if ai else "사무",
                    "detail": "회로 설계" if ai else "기타", "judge": "AI" if ai else "규칙",
                    "text": f"{month} 회로 설계 검토 {i}" if ai else f"{month} 규칙행 {i}"})
    return out


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t12_")
        self.tmp = self._tmp.name
        self.rep = os.path.join(self.tmp, "report")
        os.makedirs(self.rep)
        self.sent, self.prompts = [], {}
        ca._PRIV.clear()
        ca._PRIV.update(cfg={}, ctx=privacy.Ctx(), cans=(CANARY,))
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        os.environ.pop("LM_AI_DEADLINE", None)
        st.enter_context(mock.patch.object(judge, "ROOT", self.tmp))
        st.enter_context(mock.patch.object(judge, "g3_prompt", lambda text: True))
        st.enter_context(mock.patch.object(judge, "g3_rows",
                                           lambda rows, *a, **k: ([dict(r) for r in rows], {})))
        st.enter_context(mock.patch.object(judge, "_transport", self._transport))
        # 판정 쪽 일시 제한 대기·강한 제한 상태(다른 시험이 남긴 것)가 이 시험에 닿지 않게 — 있을 때만
        if hasattr(judge, "_cooldown"):
            st.enter_context(mock.patch.object(judge, "_cooldown", lambda *a, **k: None))
        if isinstance(getattr(judge, "_HARD", None), list):
            st.enter_context(mock.patch.object(judge, "_HARD", [False]))
        if hasattr(ca, "throttle_state"):
            st.enter_context(mock.patch.object(ca, "throttle_state", lambda *a, **k: None))
        self.out = io.StringIO()
        st.enter_context(contextlib.redirect_stdout(self.out))

    def tearDown(self):
        self.stack.close()
        ca._PRIV.clear()
        self._tmp.cleanup()

    def reply_for(self, name, prompt):
        return _ok(_reply())

    def _transport(self, prompt_text, pf, name, want_fresh, lim, *a, **k):
        self.sent.append(name)
        self.prompts[name] = prompt_text
        return self.reply_for(name, prompt_text)

    def narr_sent(self):
        return [s for s in self.sent if s.startswith("narr_")]


# ── 1) 기간의 달 ──────────────────────────────────────────────────────────────
class Months(unittest.TestCase):
    def test_period_months(self):
        self.assertEqual(narratives.period_months("20251215-20260205"), ["2025-12", "2026-01", "2026-02"])
        self.assertEqual(narratives.period_months(TAG), [f"2026-{m:02d}" for m in range(1, 11)])
        self.assertEqual(narratives.period_months("20260301-20260331"), ["2026-03"])
        self.assertIsNone(narratives.period_months("bad"))
        self.assertIsNone(narratives.period_months("20261301-20261231"))       # 13월
        self.assertIsNone(narratives.period_months("20261012-20260101"))       # 거꾸로


# ── 2) 읽기 — 자기 파일 + 다른 기간 파일(최근 먼저) · 기간 필터 · 깨진 파일 건너뜀 ─────────────
class LoadMerged(_Base):
    def test_merge_order_and_period_filter(self):
        now = time.time()
        _write(self.rep, "20250101-20251231", {"2025-12": _entry("작년 12월")}, mtime=now - 400)
        _write(self.rep, "20260101-20261001", {"2026-05": _entry("옛 5월")}, mtime=now - 300)
        with open(os.path.join(self.rep, "ai_narratives_20260101-20260601.json"), "w", encoding="utf-8") as f:
            f.write('{"2026-06": {"summary": "잘린')                          # 깨진 다른 파일 — 건너뜀
        yday = {f"2026-{m:02d}": _entry(f"어제 {m}월") for m in range(1, 10)}
        yday["2026-02"]["from_tag"] = "20260101-20260930"                    # 이미 이월된 항목 — 원래 출처 유지
        _write(self.rep, YDAY, yday, mtime=now - 100)
        _write(self.rep, TAG, {"2026-10": _entry("오늘 10월"), "2025-11": _entry("기간 밖")}, mtime=now)
        nv = narratives.load_merged(self.rep, TAG, months=narratives.period_months(TAG))
        self.assertEqual(list(nv), [f"2026-{m:02d}" for m in range(1, 11)])
        self.assertNotIn("from_tag", nv["2026-10"])
        self.assertEqual(nv["2026-05"]["summary"], "어제 5월")                # 최근 파일이 이긴다
        self.assertEqual(nv["2026-05"]["from_tag"], YDAY)
        self.assertEqual(nv["2026-02"]["from_tag"], "20260101-20260930")
        self.assertNotIn("from_tag", _load(self.rep, YDAY)["2026-05"])        # 원본 파일은 그대로
        allm = narratives.load_merged(self.rep, TAG)                          # months 없이 — 거르지 않는다
        self.assertIn("2025-12", allm)
        self.assertIn("2025-11", allm)


# ── 3) 저장 — 중간 저장도 이월(끊겨도 이전 달이 가려지지 않음) · 기간 필터 · earlier 표식 ──────────
class SaveCarry(_Base):
    def test_midrun_save_carries(self):
        _write(self.rep, YDAY, {f"2026-{m:02d}": _entry(f"어제 {m}월", n_ai=12) for m in range(1, 10)})
        _write(self.rep, "20250101-20251231", {"2025-12": _entry("작년 12월")})
        # 중간 저장 한 번 뒤 [중지]된 상황 — 예전 호출 꼴(carry=False)도 이제 늘 이월한다
        self.assertTrue(judge.save_narratives({"2026-10": _entry("새 10월", n_ai=12)}, self.rep, TAG, carry=False))
        got = _load(self.rep, TAG)
        self.assertEqual(list(got), [f"2026-{m:02d}" for m in range(1, 11)])
        for m in range(1, 10):
            self.assertEqual(got[f"2026-{m:02d}"]["from_tag"], YDAY)
        self.assertNotIn("from_tag", got["2026-10"])
        self.assertNotIn("2025-12", got)                                      # 다른 기간의 달은 섞지 않는다
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"ai_narratives_{TAG}.json.tmp")))

    def test_nothing_to_save(self):
        self.assertFalse(judge.save_narratives({}, self.rep, TAG))
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"ai_narratives_{TAG}.json")))

    def test_earlier_flag(self):
        _write(self.rep, TAG, {"2026-03": _entry("3월"), "2026-04": _entry("4월")})
        judge.save_narratives({"2026-04": _entry("새 4월", earlier=True, from_tag="x")}, self.rep, TAG,
                              earlier={"2026-03", "2026-04", "2026-05"})
        got = _load(self.rep, TAG)
        self.assertTrue(got["2026-03"]["earlier"])
        self.assertEqual(got["2026-04"]["summary"], "새 4월")
        self.assertNotIn("earlier", got["2026-04"])
        self.assertNotIn("from_tag", got["2026-04"])
        self.assertNotIn("2026-05", got)
        judge.save_narratives({}, self.rep, TAG)                              # 멱등 — 표식은 남는다
        self.assertTrue(_load(self.rep, TAG)["2026-03"]["earlier"])


# ── 4) 깨진 자기 파일 — .corrupt 로 보존하고 다른 기간 파일로 다시 씀(달 손실 없음) ────────────
class CorruptOwnFile(_Base):
    def test_truncated_own_file(self):
        _write(self.rep, YDAY, {f"2026-{m:02d}": _entry(f"어제 {m}월") for m in range(1, 10)})
        p = os.path.join(self.rep, f"ai_narratives_{TAG}.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"2026-10": {"summary": "잘린')
        self.assertEqual(len(narratives.load_merged(self.rep, TAG, narratives.period_months(TAG))), 9)
        self.assertTrue(judge.save_narratives({"2026-10": _entry("새 10월")}, self.rep, TAG))
        self.assertTrue(os.path.exists(p + ".corrupt"))
        got = _load(self.rep, TAG)
        self.assertEqual(list(got), [f"2026-{m:02d}" for m in range(1, 11)])
        self.assertEqual(got["2026-10"]["summary"], "새 10월")
        self.assertIn(".corrupt", self.out.getvalue())


# ── 5) narrate 계획 — 빠진 달·최근 달 먼저, 바뀌지 않은 달(이월 포함)은 보내지 않음 ─────────────
class NarrateOrder(_Base):
    fail_after_first = True

    def reply_for(self, name, prompt):
        if self.fail_after_first and len(self.narr_sent()) > 1:
            return _ok(BAD_REPLY)
        return _ok(_reply())

    def test_missing_and_recent_first(self):
        _write(self.rep, YDAY, {f"2026-{m:02d}": _entry(f"어제 {m}월", n_ai=12) for m in range(1, 9)})
        kept = [r for m in range(1, 11) for r in _rows(f"2026-{m:02d}", 12)]
        nar = judge.narrate(kept, 1.0, TAG)
        self.assertEqual(self.sent, ["narr_2026-10", "narr_2026-09"], self.out.getvalue()[-800:])
        self.assertEqual(list(nar), ["2026-10"])
        got = _load(self.rep, TAG)
        for m in range(1, 9):
            self.assertEqual(got[f"2026-{m:02d}"]["summary"], f"어제 {m}월")
            self.assertEqual(got[f"2026-{m:02d}"]["from_tag"], YDAY)
        self.assertNotIn("2026-09", got)
        self.assertEqual((got["2026-10"]["n"], got["2026-10"]["n_ai"]), (12, 12))
        self.assertRegex(got["2026-10"]["made"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        # 달마다 저장은 조용히 — 이월 요약 줄은 호출자의 마지막 저장이 한 번만 찍는다
        self.assertEqual(self.out.getvalue().count("이전 기간에서 이월했습니다"), 0)
        self.assertTrue(judge.save_narratives(nar, self.rep, TAG))
        self.assertEqual(self.out.getvalue().count("이전 기간에서 이월했습니다"), 1)
        self.assertEqual(_load(self.rep, TAG), got)                         # 멱등

    def test_plan_priorities(self):
        self.fail_after_first = False
        _write(self.rep, TAG, {"2026-01": _entry("1월", n_ai=12),          # 그대로 — 보내지 않음
                               "2026-02": _entry("2월", n_ai=5),           # AI 행 수가 바뀜 — 다시
                               "2026-03": _entry("3월"),                   # 예전 판(n_ai 없음) — 다시
                               "2026-05": _entry("5월", n_ai=12)})         # 가장 최근 달 — 다시
        kept = [r for m in range(1, 6) for r in _rows(f"2026-{m:02d}", 12)]
        judge.narrate(kept, 1.0, TAG)
        self.assertEqual(self.sent, ["narr_2026-04", "narr_2026-05", "narr_2026-03", "narr_2026-02"])
        self.sent.clear()
        judge.narrate(kept, 1.0, TAG, force_all=True)
        self.assertEqual(self.sent, ["narr_2026-05", "narr_2026-04", "narr_2026-03", "narr_2026-02", "narr_2026-01"])

    def test_stops_after_consecutive_failures(self):
        kept = [r for m in range(1, 7) for r in _rows(f"2026-{m:02d}", 12)]
        with mock.patch.object(self, "reply_for", lambda name, prompt: _ok(BAD_REPLY)):
            self.assertEqual(judge.narrate(kept, 1.0, TAG), {})
            self.assertEqual(self.sent, ["narr_2026-06", "narr_2026-05"])
            self.sent.clear()
            judge.narrate(kept, 1.0, TAG, max_consec=1)
            self.assertEqual(self.sent, ["narr_2026-06"])
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"ai_narratives_{TAG}.json")))


# ── 6) AI 판정이 적은 달 — 보내지 않고 이전 코멘트 유지(earlier) · 표본은 AI 판정 행만 ──────────
class NarrateRuleHeavy(_Base):
    def test_rule_heavy_month_keeps_previous(self):
        _write(self.rep, TAG, {"2026-03": _entry("좋은 3월 코멘트", n_ai=40)})
        kept = _rows("2026-03", 5, 200) + _rows("2026-04", 15, 10)
        nar = judge.narrate(kept, 1.0, TAG)
        self.assertEqual(self.sent, ["narr_2026-04"])
        self.assertNotIn("규칙행", self.prompts["narr_2026-04"])               # 규칙 행은 표본에 없다
        self.assertEqual(list(nar), ["2026-04"])
        got = _load(self.rep, TAG)
        self.assertEqual(got["2026-03"]["summary"], "좋은 3월 코멘트")
        self.assertTrue(got["2026-03"]["earlier"])
        self.assertEqual((got["2026-04"]["n"], got["2026-04"]["n_ai"]), (25, 15))
        self.assertIn("2026-03 AI 판정 행이 적어(AI 5/전체 205)", self.out.getvalue())


# ── 7) 과제 이름 — 체계 표기로 맞추고, 전부 걸러진 답은 과제 줄이 있는 이전 코멘트를 덮지 않음 ─────
class NarrateNameGuard(_Base):
    def reply_for(self, name, prompt):
        if name == "narr_2026-05":
            return _ok(_reply(projects=(("Agentic AI 과제", "업무 자동화 시범"), ("프로젝트A", "예시 에코"),
                                        ("없는 과제", "목록에 없음"))))
        return _ok(_reply(summary="엉뚱한 요약", projects=(("다른 과제", "목록에 없음"), ("프로젝트A", "예시 에코"))))

    def test_names(self):
        _write(self.rep, TAG, {"2026-06": _entry("6월 기존", n_ai=12)})
        kept = _rows("2026-05", 12, model="Agentic AI") + _rows("2026-06", 12)
        nar = judge.narrate(kept, 1.0, TAG)
        self.assertEqual(self.sent, ["narr_2026-05", "narr_2026-06"])
        self.assertEqual([p["name"] for p in nar["2026-05"]["projects"]], ["Agentic AI"])
        self.assertNotIn("2026-06", nar)
        got = _load(self.rep, TAG)
        self.assertEqual([p["name"] for p in got["2026-05"]["projects"]], ["Agentic AI"])
        self.assertEqual(got["2026-06"]["summary"], "6월 기존")
        self.assertTrue(got["2026-06"]["earlier"])

    def test_name_match(self):
        real = {judge._nm_key(n): n for n in ("Agentic AI", "Orion-X", "공통")}
        self.assertEqual(judge._narr_name("Agentic AI 과제", real), "Agentic AI")
        self.assertEqual(judge._narr_name("orion x", real), "Orion-X")
        self.assertEqual(judge._narr_name("공통 업무", real), "공통")
        self.assertIsNone(judge._narr_name("프로젝트A", dict(real, **{judge._nm_key("프로젝트A"): "프로젝트A"})))
        self.assertIsNone(judge._narr_name("모듈 설계", real))


# ── 8) 관문(G3)에 걸린 줄만 빼고 한 번 더 보낸다 ───────────────────────────────────────
class NarrateGate(_Base):
    def test_blocked_lines_dropped_and_resent(self):
        kept = _rows("2026-07", 30)
        kept[3]["text"] = f"보고 {CANARY} 첨부"
        with mock.patch.object(judge, "g3_prompt", lambda text: CANARY not in str(text)):
            nar = judge.narrate(kept, 1.0, TAG)
        self.assertEqual(self.sent, ["narr_2026-07"])
        self.assertNotIn(CANARY, self.prompts["narr_2026-07"])
        self.assertIn("2026-07", nar)


# ── 9) judge.main — 연속 실패 중단 뒤 한 달만 시험 · rc 3 은 왕복 없이 이월 ───────────────────
class JudgeMain(_Base):
    ARGV = ["judge.py", "--from", "2026-01-01", "--to", "2026-10-12", "--chunk", "5", "--fast", "--redo"]
    mode = "abort"

    def reply_for(self, name, prompt):
        if name == "taxonomy":
            return _ok(json.dumps({"models": [{"name": "제어모듈", "match": ["제어"]}, {"name": "공통", "match": []}]},
                                  ensure_ascii=False))
        if name == "chunk1" and self.mode == "abort":
            idxs = [int(x) for x in re.findall(r"^#(\d+) \|", prompt, re.M)] or list(range(100))
            return _ok(json.dumps({"j": [[i, "y", "제어모듈", "개발", "시험 보고서"] for i in idxs]}, ensure_ascii=False))
        return _ok(BAD_REPLY)                       # 그 밖의 청크·월별 리뷰 — 답을 해석하지 못함(실패)

    def _signals(self, n=40):
        with open(os.path.join(self.rep, f"signals_{TAG}.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "source", "who", "project", "activity", "weight", "text", "flag"])
            for i in range(n):
                mon = 9 if i < n // 2 else 10
                w.writerow([f"2026-{mon:02d}-{1 + i % 28:02d} 09:{i % 60:02d}", "메일", "", "", "", "1",
                            f"제어 모듈 시험 보고서 {i}번 항목 검토 요청", ""])

    def _main(self):
        with mock.patch.object(sys, "argv", list(self.ARGV)):
            return judge.main()

    def _aj(self):
        with open(os.path.join(self.rep, f"ai_judgments_{TAG}.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_aborted_tries_one_month_and_carries(self):
        self._signals()
        _write(self.rep, YDAY, {f"2026-{m:02d}": _entry(f"어제 {m}월", n_ai=12) for m in range(1, 11)})
        rc = self._main()
        log = self.out.getvalue()
        self.assertIn(rc, (0, 2), log[-1500:])
        self.assertTrue(self._aj()["aborted"], log[-1500:])
        self.assertLessEqual(len(self.narr_sent()), 1, self.sent)
        got = _load(self.rep, TAG)
        self.assertEqual(list(got), [f"2026-{m:02d}" for m in range(1, 11)])
        for m in range(1, 11):
            self.assertEqual(got[f"2026-{m:02d}"]["summary"], f"어제 {m}월")
            self.assertEqual(got[f"2026-{m:02d}"]["from_tag"], YDAY)

    def test_rc3_carries_without_roundtrips(self):
        self.mode = "fail"
        self._signals()
        _write(self.rep, YDAY, {f"2026-{m:02d}": _entry(f"어제 {m}월") for m in range(1, 10)})
        rc = self._main()
        log = self.out.getvalue()
        self.assertEqual(rc, 3, log[-1500:])
        self.assertEqual(self.narr_sent(), [])
        got = _load(self.rep, TAG)
        self.assertEqual(list(got), [f"2026-{m:02d}" for m in range(1, 10)])
        self.assertTrue(all(v["from_tag"] == YDAY for v in got.values()))
        lines = [ln for ln in log.splitlines() if ln.strip()]
        i_carry = max(i for i, ln in enumerate(lines) if "이전 기간에서 이월했습니다" in ln)
        i_json = max(i for i, ln in enumerate(lines) if ln.startswith("{") and '"ok": false' in ln)
        self.assertLess(i_carry, i_json)                                      # 사유 JSON 줄이 마지막 쪽에 남는다

    def test_rc3_without_previous_writes_nothing(self):
        self.mode = "fail"
        self._signals()
        self.assertEqual(self._main(), 3)
        self.assertFalse(os.path.exists(os.path.join(self.rep, f"ai_narratives_{TAG}.json")))


# ── 10) --narrate-only — 규칙 행만이면 만들지 않음 · 기본은 빠진·최근·바뀐 달 · --all 은 전부 ─────────
class NarrateOnly(_Base):
    COLS = ["time", "source", "who", "project", "activity", "weight", "text",
            "model", "worktype", "detail", "judge", "flag"]

    def _judged_signals(self, spec):
        """spec = [(달, AI 행 수, 규칙 행 수)] — judge 가 되쓴 signals 꼴."""
        with open(os.path.join(self.rep, f"signals_{TAG}.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.COLS)
            w.writeheader()
            for mk, n_ai, n_rule in spec:
                for r in _rows(mk, n_ai, n_rule):
                    r.update(project=r["model"], activity=r["detail"], weight="1", flag="")
                    w.writerow({c: r.get(c, "") for c in self.COLS})

    def _run(self, *extra):
        with mock.patch.object(sys, "argv", ["judge.py", "--from", "2026-01-01", "--to", "2026-10-12",
                                             "--narrate-only", *extra]):
            return judge.main()

    def test_rule_rows_only(self):
        self._judged_signals([("2026-01", 0, 12), ("2026-02", 0, 12)])
        old = {"2026-01": _entry("좋은 1월", n_ai=12), "2026-02": _entry("좋은 2월", n_ai=12)}
        _write(self.rep, TAG, old)
        self.assertEqual(self._run(), 1)
        self.assertEqual(self.sent, [])
        self.assertEqual(_load(self.rep, TAG), old)
        self.assertIn("규칙 결과로는 코멘트를 만들지 않습니다", self.out.getvalue())

    def test_default_and_all(self):
        self._judged_signals([("2026-01", 12, 0), ("2026-02", 12, 0), ("2026-03", 12, 0)])
        _write(self.rep, TAG, {f"2026-0{m}": _entry(f"{m}월", n_ai=12) for m in (1, 2, 3)})
        self.assertEqual(self._run(), 0)
        self.assertEqual(self.sent, ["narr_2026-03"])
        self.sent.clear()
        self.assertEqual(self._run("--all"), 0)
        self.assertEqual(self.sent, ["narr_2026-03", "narr_2026-02", "narr_2026-01"])

    def test_nothing_to_remake(self):
        self._judged_signals([("2026-01", 12, 0), ("2026-02", 12, 0), ("2026-03", 0, 12)])
        _write(self.rep, TAG, {f"2026-0{m}": _entry(f"{m}월", n_ai=12) for m in (1, 2, 3)})
        self.assertEqual(self._run(), 0)
        self.assertEqual(self.sent, [])
        self.assertIn("다시 만들 달이 없습니다", self.out.getvalue())
        got = _load(self.rep, TAG)
        self.assertTrue(got["2026-03"]["earlier"])
        self.assertNotIn("earlier", got["2026-01"])


if __name__ == "__main__":
    unittest.main()
