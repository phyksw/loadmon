# -*- coding: utf-8 -*-
r"""tests\test_p10_judge_scale.py — 수천 행 AI 판정(LM28 진단 A) + judge.main 의 과제명 관문 연결(진단 B).

이어서 판정 캐시(다른 날짜 기간·메일 라벨 바뀜) · 같은 내용 묶음(대표만 보냄) · 같은 내용 키 재사용 · 짧은 팀즈 대화 ·
쉬었다 다시 보내기(사용량 제한)·강한 제한(hard) · 로그인 만료 중단 · 드라이버의 사용량 제한 문구(사다리 없음)·새로 고침 ·
AI 가 못 본 행 채우기 · 묶음마다 캐시 저장(중간 종료) · chatTurns 회전 새로 고침 · 사람 이름·공지류 과제 없음 · 규칙 폴백 표식.
실제 Copilot·Edge 를 쓰지 않는다 — judge._transport·g3_prompt·g3_rows·_cooldown 과 copilot_auto.throttle_state·note_throttle 을
가짜로 바꾸고 judge.ROOT 는 임시 폴더다. 사람 이름은 시험용 가명만 쓴다.
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
import details  # noqa: E402
import extract  # noqa: E402
import judge  # noqa: E402
import privacy  # noqa: E402
import stage_state  # noqa: E402

CANARY = "zzcanaryzz"                 # 시험용 카나리아(실재하지 않는 값)
TAG = "20260101-20261012"             # 오늘 기간
YDAY = "20260101-20261011"            # 어제 기간(기본 기간 '올해'는 날마다 tag 가 바뀐다)
COLS = ["time", "source", "who", "project", "activity", "weight", "text", "flag"]
TAX = {"models": [{"name": "LiDAR-X", "match": ["lidar"], "obs": "보정 데이터 검토"},
                  {"name": "공통", "match": []}]}
THROTTLED = {"ok": False, "phase": "throttled", "reason": "R-THROTTLE", "error": "Copilot 사용량 제한(일시)"}
# 일시 오류(사용량 제한이 아닌 것) — 2·5·10분 쉬는 사다리 시험용. 사용량 제한은 LM28 부터 한 번만 쉰다(tests\test_p22_throttle.py)
COPILOT_ERR = {"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류 — 3단계 재시도 모두 실패"}
LOGIN = {"ok": False, "phase": "login_required", "reason": "R-LOGIN", "error": "로그인 필요 (최초 1회)"}


def _ok(reply):
    return {"ok": True, "phase": "replied",
            "reply": reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)}


def _idxs(prompt):
    return [int(x) for x in re.findall(r"^#(\d+) \|", prompt, re.M)]


def _t(day, minute):
    """2026-03-<day> 09:00 + minute 분."""
    h, m = divmod(9 * 60 + minute, 60)
    return f"2026-03-{day:02d} {h:02d}:{m:02d}"


def _row(t, text, source="메일(수신)", who="", project="", activity="검토", flag=""):
    return {"time": t, "source": source, "who": who, "project": project, "activity": activity, "weight": "1",
            "text": text, "flag": flag}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t10_")
        self.tmp = self._tmp.name
        self.rep = os.path.join(self.tmp, "report")
        os.makedirs(self.rep)
        self.sent, self.cool, self.notes, self.thr = [], [], [], None
        ca._PRIV.clear()
        ca._PRIV.update(cfg={}, ctx=privacy.Ctx(), cans=(CANARY,))
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        for k in ("LM_AI_DEADLINE", "LM_COPILOT_STUB", "LM_RUN_ID"):
            os.environ.pop(k, None)
        # 프로세스 전역 상태(새 채팅·쉬기·강한 제한)는 시험마다 새로 — 다른 시험에 새지 않게
        for name, val in (("ROOT", self.tmp), ("_FIRST_SEND", [True]), ("_NEED_FRESH", [False]), ("_TURNS", [0]),
                          ("_CHAT_TURNS", [None]), ("_HARD", [False]), ("_COOLED", [0.0]), ("_COOLDOWNS", [0]),
                          ("_MODEL_FALLBACK", [""]), ("_THR_CHECKED", [False]), ("_WAIT_TICKS", [0]),
                          ("_LAST_PROMPT", [None]), ("_STUB_NOTED", [True])):
            st.enter_context(mock.patch.object(judge, name, val))
        st.enter_context(mock.patch.object(judge, "g3_prompt", lambda text: True))
        st.enter_context(mock.patch.object(judge, "g3_rows", lambda rows, *a, **k: ([dict(r) for r in rows], {})))
        st.enter_context(mock.patch.object(judge, "_transport", self._transport))
        st.enter_context(mock.patch.object(judge, "_cooldown", lambda sec: self.cool.append(sec)))
        st.enter_context(mock.patch.object(judge, "_copilot_cfg", lambda: {}))
        st.enter_context(mock.patch.object(ca, "throttle_state", lambda *a, **k: self.thr))
        st.enter_context(mock.patch.object(ca, "note_throttle", lambda *a, **k: self.notes.append(dict(k)) or True))
        st.enter_context(mock.patch.object(extract, "load_cfg", lambda: {}))
        self.out = io.StringIO()
        st.enter_context(contextlib.redirect_stdout(self.out))

    def tearDown(self):
        cur = stage_state.current()
        if cur is not None:
            cur.finish("failed")              # 끝나지 않은 실행의 상태 파일 하트비트를 멈춘다
        self.stack.close()
        ca._PRIV.clear()
        self._tmp.cleanup()

    # ── 가짜 드라이버 ──
    def _transport(self, prompt_text, pf, name, want_fresh, lim, reload=False, model=None):
        self.sent.append({"name": name, "prompt": prompt_text, "fresh": bool(want_fresh), "reload": bool(reload),
                          "model": model or ""})
        return self.reply(name, prompt_text)

    def reply(self, name, prompt):
        if name == "taxonomy":
            return _ok(TAX)
        return _ok({"j": [[i, "y", "LiDAR-X", "개발", "보정 검토"] for i in _idxs(prompt)]})

    # ── 입출력 ──
    def write_signals(self, rows):
        with open(os.path.join(self.rep, f"signals_{TAG}.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in COLS})

    def signals(self):
        with open(os.path.join(self.rep, f"signals_{TAG}.csv"), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def aj(self):
        with open(os.path.join(self.rep, f"ai_judgments_{TAG}.json"), encoding="utf-8") as f:
            return json.load(f)

    def cache_items(self):
        with open(os.path.join(self.rep, judge.JUDGE_CACHE), encoding="utf-8") as f:
            return json.load(f)["items"]

    def run_main(self, chunk=40, narrate=False):
        argv = ["judge.py", "--from", "2026-01-01", "--to", "2026-10-12", "--chunk", str(chunk), "--fast"]
        if not narrate:
            argv.append("--no-narrate")
        with mock.patch.object(sys, "argv", argv):
            return judge.main()

    def chunk_sends(self):
        return [s for s in self.sent if s["name"].startswith("chunk")]

    def sent_idxs(self):
        return [i for s in self.chunk_sends() for i in _idxs(s["prompt"])]


# ── 1) 다른 날짜 기간의 판정을 이어받는다 + 캐시에는 원문이 없다 ─────────────────────────────────
class CrossDayResume(_Base):
    def test_yesterday_tag_reused(self):
        old = [_row(_t(2, i), f"LiDAR-X 보정 데이터 검토 {i}번") for i in range(40)]
        items = {str(i): {"work": True, "model": "LiDAR-X", "worktype": "개발", "detail": "보정 검토",
                          "sig": judge.signal_sig(r)} for i, r in enumerate(old)}
        with open(os.path.join(self.rep, f"ai_judgments_{YDAY}.json"), "w", encoding="utf-8") as f:
            json.dump({"judged": 40, "items": items}, f, ensure_ascii=False)
        # 절반은 메일 라벨이 바뀌었다(보낸 사람이 5통을 넘겨 메일(수신)→메일(수신전용))
        rows = [dict(r, source=("메일(수신전용)" if i % 2 else r["source"])) for i, r in enumerate(old)]
        rows += [_row(_t(3, k * 5), f"레이더 신호 처리 회의 {k}번 안건") for k in range(3)]
        self.write_signals(rows)
        rc = self.run_main()
        self.assertEqual(rc, 0, self.out.getvalue()[-1500:])
        self.assertEqual(sorted(self.sent_idxs()), [40, 41, 42])
        aj = self.aj()
        self.assertEqual(aj["cache_reused"], 40)
        self.assertIn("지난 실행(다른 날짜 포함) 40건 재사용", self.out.getvalue())
        items = self.cache_items()
        self.assertEqual(len(items), 43)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{20}", k) for k in items))
        with open(os.path.join(self.rep, judge.JUDGE_CACHE), encoding="utf-8") as f:
            raw = f.read()
        for r in rows:
            self.assertNotIn(r["text"], raw)                        # 캐시에는 신호 원문이 없다
        sig = self.signals()
        self.assertEqual(len(sig), 43)
        self.assertTrue(all(r["judge"] == "AI" for r in sig))


# ── 2) 라벨이 바뀐 행 — 캐시 키(sig2)가 같아 다시 묻지 않는다 ─────────────────────────────────
class LabelFlip(_Base):
    def test_cache_hit_after_label_change(self):
        a = _row(_t(4, 0), "LiDAR-X 보정 결과 회신 드립니다", source="메일(수신)")
        b = dict(a, source="메일(수신전용)")
        self.assertEqual(judge.signal_sig2(a), judge.signal_sig2(b))
        self.assertNotEqual(judge.signal_sig(a), judge.signal_sig(b))
        self.assertEqual(judge._sig2_from_legacy(judge.signal_sig(a)), judge.signal_sig2(b))
        cache = {"v": 1, "since": 0, "items": {judge._ckey(judge.signal_sig2(a)): {
            "w": 1, "m": "LiDAR-X", "t": "개발", "d": "보정 회신", "at": "2026-10-01"}}}
        self.assertTrue(judge.save_judge_cache(self.rep, cache, "2026-01-01"))
        self.write_signals([b])
        self.run_main()
        self.assertEqual(self.chunk_sends(), [])
        got = self.signals()[0]
        self.assertEqual((got["judge"], got["model"], got["detail"]), ("AI", "LiDAR-X", "보정 회신"))


# ── 3·4) 같은 내용 묶음 — 대표만 보내고, 다음 실행은 왕복 없음 · 옛 스레드의 새 회신은 키로 재사용 ─────────
class Grouping(_Base):
    def rows(self):
        out = []
        for i in range(30):
            out.append(_row(_t(5 + i % 3, i * 7), ("RE: " if i % 2 else "FW: ") + "[PX] 일정 조율",
                            source=("메일(수신)" if i % 2 else "메일(발신)"),
                            who=("홍길동/책임/개발팀" if i % 3 else "John Smith")))
        for k in range(10):
            out.append(_row(_t(9, k * 11), f"광학 모듈 설계 검토 {k}번째 회의 안건"))
        return out

    def test_group_once_then_nothing(self):
        self.write_signals(self.rows())
        rc = self.run_main()
        self.assertEqual(rc, 0, self.out.getvalue()[-1500:])
        self.assertEqual(len(self.sent_idxs()), 11)                  # 묶음 대표 1 + 서로 다른 제목 10
        aj = self.aj()
        self.assertEqual((aj["group_rows"], aj["reps"]), (29, 11))
        sig = self.signals()
        self.assertEqual(len(sig), 40)
        self.assertTrue(all(r["judge"] == "AI" and r["model"] == "LiDAR-X" for r in sig))
        self.assertIn("[judge] 구조: 신호 40", self.out.getvalue())
        # 다시 — 새 행이 없으면 묶음 왕복도 체계 왕복도 없다(지난 정상 체계 재사용)
        self.sent.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.aj()["cache_reused"], 40)

    def test_new_reply_in_old_thread(self):
        rows = self.rows()
        self.write_signals(rows)
        self.run_main()
        self.sent.clear()
        self.write_signals(rows + [_row(_t(8, 1), "RE: RE: [PX] 일정 조율", who="김철수 책임")])
        self.run_main()
        self.assertEqual(self.chunk_sends(), [])
        aj = self.aj()
        self.assertEqual((aj["cache_key_reused"], aj["cache_reused"]), (1, 41))
        new = [r for r in self.signals() if r["time"] == _t(8, 1)]
        self.assertEqual((new[0]["judge"], new[0]["model"]), ("AI", "LiDAR-X"))


# ── 5) 짧은 팀즈 대화 — 보내지 않고 같은 대화의 판정으로 채운다(버리지 않는다) ───────────────────────
class LowInfo(_Base):
    def test_short_chat_filled_from_neighbour(self):
        rows = [_row(_t(10, 0), "LiDAR-X 보정 데이터 공유드립니다 확인 부탁드려요", source="팀즈(수신)", who="김철수"),
                _row(_t(10, 3), "네", source="팀즈(수신)", who="김철수"),
                _row(_t(10, 5), "감사합니다", source="팀즈(발신)", who="나"),
                _row(_t(10, 8), "ㅎㅎ", source="팀즈(수신)", who="김철수"),
                _row(_t(11, 0), "레이더 시험 계획 검토 요청"),
                _row(_t(20, 0), "ㅋㅋ", source="팀즈(수신)", who="홍길동")]
        self.write_signals(rows)
        rc = self.run_main()
        self.assertEqual(sorted(self.sent_idxs()), [0, 4])
        sig = {r["time"]: r for r in self.signals()}
        self.assertEqual(len(sig), 6)                                # 비업무로 버린 행 없음
        for t in (_t(10, 3), _t(10, 5), _t(10, 8)):
            self.assertEqual((sig[t]["judge"], sig[t]["model"]), ("AI(유사)", "LiDAR-X"))
        far = sig[_t(20, 0)]                                         # 이웃 판정이 없는 짧은 대화 — 규칙, 협업
        self.assertEqual((far["judge"], far["worktype"]), ("규칙", "협업"))
        aj = self.aj()
        self.assertEqual((aj["lowinfo_rows"], aj["filled_rows"]["conv"]), (4, 3))
        self.assertEqual(rc, 0)                                      # 짧은 대화는 실패가 아니다


# ── 6) 일시 오류 두 번 → 쉬고 새로 고친 뒤 성공(나누지 않음) ─────────────────────────────────
# (사용량 제한은 LM28 부터 이 사다리를 타지 않고 throttleWaitSec 한 번만 쉰다 — tests\test_p22_throttle.py)
class ThrottleRecovery(_Base):
    def reply(self, name, prompt):
        if name == "chunk1" and sum(1 for s in self.sent if s["name"] == "chunk1") <= 2:
            return dict(COPILOT_ERR)
        return super().reply(name, prompt)

    def test_cools_down_and_resends(self):
        self.write_signals([_row(_t(12, i), f"LiDAR-X 보정 항목 {i}번 정리") for i in range(10)])
        rc = self.run_main()
        c1 = [s for s in self.sent if s["name"] == "chunk1"]
        self.assertEqual(len(c1), 3)
        self.assertEqual([s["reload"] for s in c1], [False, True, True])
        self.assertTrue(all(s["fresh"] for s in c1[1:]))
        self.assertEqual(self.cool, [120.0, 300.0])
        aj = self.aj()
        self.assertEqual((aj["retries"], aj["aborted"], aj["cooldowns"], aj["model_fallback"]), (0, False, 2, ""))
        self.assertEqual((aj["judged"], aj["roundtrips"], aj["abort_kind"]), (10, 3, ""))
        self.assertEqual(self.notes, [])                             # 강한 제한 기록 없음
        self.assertEqual(rc, 0)


# ── 7) 일시 오류로 계속 막힘 → 쉬는 사다리 3단 뒤 강한 제한, 남은 묶음·월별 코멘트는 보내지 않음 ──────────────
# (사용량 제한으로 계속 막히면 한 번 쉬고 멈춘다 — tests\test_p22_throttle.py JudgeMainThrottle)
class PersistentThrottle(_Base):
    def reply(self, name, prompt):
        if name.startswith(("chunk", "narr_")):
            return dict(COPILOT_ERR)
        return super().reply(name, prompt)

    def test_hard_stop(self):
        self.write_signals([_row(_t(13, i * 3), f"LiDAR-X 측정 로그 {i}번 분석") for i in range(20)])
        rc = self.run_main(5, narrate=True)
        names = [s["name"] for s in self.sent]
        self.assertEqual(names.count("chunk1"), 4)                   # 1 + 쉬고 다시 3
        self.assertFalse([n for n in names if n.startswith("chunk") and n != "chunk1"])
        self.assertFalse([n for n in names if n.startswith("narr_")])
        c1 = [s for s in self.sent if s["name"] == "chunk1"]
        self.assertEqual([s["model"] for s in c1], ["", "", "", "자동"])  # 두 번 쉬고도 막히면 대체 모델
        self.assertEqual(len(self.cool), 3)
        self.assertTrue(any(n.get("hard") for n in self.notes))      # 다음 단계 프로세스가 알게 기록
        aj = self.aj()
        self.assertTrue(aj["aborted"])
        self.assertEqual(aj["abort_kind"], "throttle")
        self.assertIn("사용량 제한", aj["abort_reason"])
        self.assertEqual((aj["cooldowns"], aj["model_fallback"]), (3, "자동"))
        for k in ("cache_reused", "group_rows", "reps", "lowinfo_rows", "filled_rows", "rule_rows", "abort_reason"):
            self.assertIn(k, aj)
        self.assertEqual(rc, 3)
        self.assertIn("중단 throttle", self.out.getvalue())

    def test_narrate_stops_once_hard(self):
        judge._HARD[0] = True                                        # 이 프로세스가 이미 강한 제한을 봤다
        kept = [{"time": f"2026-{mon:02d}-{1 + i:02d} 10:00", "source": "메일(수신)", "who": "", "model": "LiDAR-X",
                 "worktype": "개발", "detail": "보정 검토", "judge": "AI", "text": f"LiDAR-X 보정 {mon}월 {i}번"}
                for mon in (7, 8, 9) for i in range(12)]
        self.assertEqual(judge.narrate(kept, 1.0, TAG), {})
        self.assertEqual(len([s for s in self.sent if s["name"].startswith("narr_")]), 1)
        self.assertEqual(self.cool, [])                              # 쉬지 않고 바로 멈춘다


# ── 8) 로그인 만료 — 쉬지 않고 바로 중단(abort_kind login) · explain_failure 갈래 ───────────────────
class LoginStop(_Base):
    def reply(self, name, prompt):
        return dict(LOGIN)

    def test_login_aborts_without_cooldown(self):
        self.write_signals([_row(_t(14, i), f"LiDAR-X 설계 변경 {i}번 공유") for i in range(12)])
        rc = self.run_main(5)
        self.assertEqual([s["name"] for s in self.sent], ["taxonomy", "chunk1"])
        self.assertEqual(self.cool, [])
        aj = self.aj()
        self.assertEqual((aj["aborted"], aj["abort_kind"]), (True, "login"))
        self.assertEqual(rc, 3)

    def test_explain_failure_kinds(self):
        ef = details.explain_failure
        self.assertTrue(ef({"phase": "throttled", "hard": True})[2])
        self.assertIn("사용량 제한", ef({"phase": "throttled", "hard": True})[0])
        self.assertFalse(ef({"phase": "throttled"})[2])
        self.assertFalse(ef(dict(THROTTLED))[2])
        self.assertFalse(ef(ca.busy_result())[2])                    # 다른 작업이 전용 Edge 사용 중 — 쉬었다 다시
        self.assertTrue(ef(dict(LOGIN))[2])
        self.assertTrue(judge._is_transient(ca.busy_result()))
        self.assertTrue(judge._is_transient(dict(THROTTLED)))
        self.assertTrue(judge._is_transient({"ok": False, "error": "왕복 시간 초과"}))
        self.assertFalse(judge._is_transient(dict(LOGIN)))
        self.assertFalse(judge._is_transient({"ok": False, "phase": "blocked"}))
        self.assertFalse(judge._is_transient(dict(THROTTLED, hard=True)))
        self.assertEqual(judge._abort_kind_of(dict(THROTTLED, hard=True)), "throttle")
        self.assertEqual(judge._abort_kind_of(dict(LOGIN)), "login")
        self.assertEqual(judge._abort_kind_of({"phase": "input_not_found"}), "fatal")


# ── 첫 왕복 전 강한 제한 기록 · 전체 마감 ─────────────────────────────────────────────────
class PreThrottle(_Base):
    def test_recent_hard_record_waits_then_hard(self):
        self.thr = (120.0, True)                                     # 2분 전 다른 단계가 남긴 강한 제한
        self.reply = lambda name, prompt: dict(THROTTLED)
        res = judge.copilot_send("판정 요청 본문", "t", "chunk1")
        self.assertEqual(self.cool, [480.0])                         # 남은 8분만 한 번 쉰다
        self.assertEqual(len(self.sent), 1)                          # 그래도 막히면 사다리 없이 hard
        self.assertTrue(res.get("hard"))
        self.assertTrue(details.explain_failure(res)[2])

    def test_deadline_leaves_no_room(self):
        os.environ["LM_AI_DEADLINE"] = str(time.time() + 140)       # 쉴 수 있는 시간 20초 — 쉬지 않고 실패를 돌려준다
        self.reply = lambda name, prompt: dict(THROTTLED)
        res = judge.copilot_send("판정 요청 본문", "t", "chunk1")
        self.assertEqual((self.cool, len(self.sent)), ([], 1))
        self.assertFalse(res.get("hard"))
        self.assertFalse(details.explain_failure(res)[2])


# ── 9) 드라이버 — 사용량 제한 문구는 사다리 없이 throttled · 새로 고침 · 기록 파일 ─────────────────────
class _FakeCdp:
    def __init__(self):
        self.calls = []

    def eval(self, expr, timeout=25):
        if "location.href" in expr:
            return {"url": "https://m365.cloud.microsoft/chat", "title": "", "ready": "complete"}
        return None

    def call(self, method, params=None, timeout=25):
        self.calls.append(method)
        return {}

    def close(self):
        pass


class DriverThrottle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t10d_")
        self.cfg = dict(ca.DEFAULTS, profileDir=os.path.join(self._tmp.name, "data", "lm28_edge"), port=9533)
        os.makedirs(os.path.dirname(self.cfg["profileDir"]), exist_ok=True)
        self.traces, self.once, self.newchat = [], [], []
        self.cdp = _FakeCdp()
        self.reply = "죄송합니다. 잠시 후 다시 시도해 주세요."
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.object(ca, "trace", lambda stage, **kw: self.traces.append(kw)))
        st.enter_context(mock.patch.object(ca, "_sleep", lambda s: None))
        st.enter_context(mock.patch.object(ca, "ensure_edge", lambda cfg: "reuse"))
        st.enter_context(mock.patch.object(ca, "find_tab", lambda cfg: "ws://127.0.0.1:9533/devtools/page/x"))
        st.enter_context(mock.patch.object(ca, "CDP", lambda ws: self.cdp))
        st.enter_context(mock.patch.object(ca, "new_chat", lambda cdp, cfg: self.newchat.append(1) or "새 채팅 버튼"))
        st.enter_context(mock.patch.object(ca, "_roundtrip_once", self._once))
        st.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def _once(self, cdp, cfg, prompt, model_override=None):
        self.once.append(model_override)
        return {"ok": True, "phase": "replied", "reply": self.reply, "sentinel": False}

    def test_marks(self):
        self.assertTrue(ca.is_throttle_reply("죄송합니다. 잠시 후 다시 시도해 주세요."))
        self.assertTrue(ca.is_throttle_reply("You've reached the limit for now. Please try again later."))
        self.assertFalse(ca.is_throttle_reply('{"j":[[0,"y","LiDAR-X","개발","rate limit 검토"]]}'))
        self.assertFalse(ca.is_throttle_reply("분석 결과 " * 250 + "try again later"))
        self.assertFalse(ca.is_throttle_reply(""))
        self.assertFalse(ca.is_throttle_reply("죄송합니다. 지금은 응답할 수 없습니다."))   # 일반 오류 문구 — 사다리 대상

    def test_throttle_no_ladder(self):
        res = ca.run_roundtrip(self.cfg, "판정 요청")
        self.assertEqual((res["ok"], res["phase"], res["reason"]), (False, "throttled", "R-THROTTLE"))
        self.assertEqual((len(self.once), self.newchat), (1, []))   # 보낸 것은 한 번 — 새 채팅·자동 모델 재전송 없음
        age, hard = ca.throttle_state(self.cfg)
        self.assertFalse(hard)
        self.assertLess(age, 60)
        self.assertEqual((self.traces[-1].get("phase"), self.traces[-1].get("reason")), ("throttled", "R-THROTTLE"))

    def test_error_reply_still_ladders(self):
        self.reply = "죄송합니다. 지금은 응답할 수 없습니다."
        res = ca.run_roundtrip(self.cfg, "판정 요청")
        self.assertEqual(self.once, [None, None, "자동"])
        self.assertEqual(res["phase"], "copilot_error")

    def test_reload_instead_of_new_chat(self):
        self.reply = '{"j":[[0,"y","LiDAR-X","개발","보정 검토"]]}'
        res = ca.run_roundtrip(self.cfg, "판정 요청", fresh=True, reload=True)
        self.assertTrue(res["ok"])
        self.assertIn("Page.navigate", self.cdp.calls)
        self.assertEqual(self.newchat, [])
        self.assertTrue(self.traces[-1].get("reload"))

    def test_throttle_state_file(self):
        self.assertIsNone(ca.throttle_state(self.cfg))
        ca.note_throttle(self.cfg, hard=True)
        self.assertTrue(ca.throttle_state(self.cfg)[1])
        ca.note_throttle(self.cfg)                                   # 약한 관찰이 와도 강한 제한 표식은 남는다
        self.assertTrue(ca.throttle_state(self.cfg)[1])
        ca._after(self.cfg, {"ok": True, "phase": "replied"})        # 성공 왕복이 지운다
        self.assertIsNone(ca.throttle_state(self.cfg))


# ── 10) AI 가 못 본 행 채우기 — 규칙 토큰은 채우고, 비업무와 닮은 행은 버리지 않고, 닮은 것이 없으면 규칙 ──────
class FillUnjudged(_Base):
    def reply(self, name, prompt):
        if name == "taxonomy":
            return _ok(TAX)
        if name != "chunk1":
            return dict(LOGIN)                                       # 첫 묶음 뒤 로그인 만료로 중단
        return _ok({"j": [[i, "y", "LiDAR-X", "개발", "보정 분석"] if i < 5 else [i, "n"] for i in _idxs(prompt)]})

    def test_fill_after_abort(self):
        rows = [_row(_t(15, i), f"lidar 보정 데이터 {i}번 분석", project="lidar") for i in range(5)]
        rows += [_row(_t(15, 10 + i), f"점심 메뉴 투표 qv{i}") for i in range(5)]
        rows += [_row(_t(16, i), f"현장 측정 결과 정리 tq{i}", project="lidar") for i in range(10)]
        rows += [_row(_t(17, i), f"점심 메뉴 투표 다시 qw{i}") for i in range(5)]
        rows += [_row(_t(18, i), f"고유 항목 zz{i}") for i in range(15)]
        rows += [_row(_t(19, i), f"할인 행사 안내 {i}", flag="ad") for i in range(2)]
        self.write_signals(rows)
        seen = {}
        with mock.patch.object(judge, "rehours_meta", lambda kept, dropped, *a, **k: seen.update(dropped=list(dropped))):
            rc = self.run_main(10)
        self.assertEqual(rc, 2, self.out.getvalue()[-1500:])
        sig = {r["text"]: r for r in self.signals()}
        for i in range(10):
            r = sig[f"현장 측정 결과 정리 tq{i}"]
            self.assertEqual((r["judge"], r["model"], r["worktype"], r["detail"]), ("AI(유사)", "LiDAR-X", "개발", "보정 분석"))
        for i in range(5):
            self.assertEqual(sig[f"점심 메뉴 투표 다시 qw{i}"]["judge"], "규칙")    # 비업무와 닮아도 버리지 않는다
            self.assertNotIn(f"점심 메뉴 투표 qv{i}", sig)                       # AI 가 비업무로 본 행
        for i in range(15):
            self.assertEqual(sig[f"고유 항목 zz{i}"]["judge"], "규칙")
        aj = self.aj()
        self.assertEqual(aj["abort_kind"], "login")
        self.assertEqual(aj["filled_rows"], {"same": 0, "conv": 0, "token": 10, "sim": 0})
        self.assertEqual((aj["failed_rows"], aj["rule_rows"], aj["judged"]), (30, 20, 10))
        self.assertEqual(sorted(r.get("judge") for r in seen["dropped"]), ["AI-n"] * 5 + ["ad"] * 2)
        self.assertEqual(len(self.cache_items()), 10)                # 채운 판정은 캐시에 넣지 않는다

    def test_sim_fill_unit(self):
        rows = [_row(_t(25, 0), "광학 모듈 정렬 지그 제작 kx1"), _row(_t(25, 5), "사내 동호회 모집 kq2"),
                _row(_t(26, 0), "정렬 지그 도면 회신 kx1 rev"), _row(_t(26, 3), "동호회 회비 안내 kq2 추가"),
                _row(_t(26, 9), "전혀 다른 내용 pp9")]
        judged = {0: {"work": True, "model": "LiDAR-X", "worktype": "개발", "detail": "지그 제작"},
                  1: {"work": False, "model": "", "worktype": "", "detail": ""}}
        fills = judge.fill_unjudged(rows, judged, [2, 3, 4])
        self.assertEqual(fills[2][1], "sim")
        self.assertEqual((fills[2][0]["model"], fills[2][0]["detail"]), ("LiDAR-X", "지그 제작"))
        self.assertNotIn(3, fills)                                   # 가장 닮은 행이 비업무 — n 을 옮기지 않는다
        self.assertNotIn(4, fills)


# ── 11) 묶음마다 캐시 저장 — 중간에 끊겨도 다음 실행은 남은 묶음만 ─────────────────────────────
class Checkpoint(_Base):
    crash = True

    def reply(self, name, prompt):
        if name == "chunk4" and self.crash:
            raise SystemExit(9)
        return super().reply(name, prompt)

    def test_cache_saved_per_chunk(self):
        self.write_signals([_row(_t(21, i * 2), f"LiDAR-X 펌웨어 빌드 {i}번 점검") for i in range(20)])
        with self.assertRaises(SystemExit):
            self.run_main(5)
        cur = stage_state.current()
        if cur is not None:
            cur.finish("failed")
        self.assertEqual(len(self.cache_items()), 15)
        self.crash = False
        self.sent.clear()
        self.assertEqual(self.run_main(5), 0)
        self.assertEqual(sorted(self.sent_idxs()), list(range(15, 20)))
        self.assertEqual(self.aj()["cache_reused"], 15)


# ── chatTurns 회전 — 새 채팅으로 넘어갈 때 페이지도 새로 고친다 ───────────────────────────────
class RotationReload(_Base):
    def test_rotation_reloads_page(self):
        judge._CHAT_TURNS[0] = 2
        self.write_signals([_row(_t(22, i * 4), f"LiDAR-X 보정 표 {i}번 갱신") for i in range(15)])
        self.run_main(5)
        by = {s["name"]: s for s in self.sent}
        self.assertFalse(by["taxonomy"]["reload"])
        self.assertFalse(by["chunk1"]["reload"])
        self.assertTrue(by["chunk2"]["reload"] and by["chunk2"]["fresh"])
        self.assertFalse(by["chunk3"]["reload"])


# ── 진단 B — 판정 반영: 사람 이름·공지류 과제 없음 · 사람 이름 세부업무는 활동명 · 공지 제목 규칙 행 ───────────
class NamesInMain(_Base):
    PLAN = {0: "홍길동", 1: "근태공지", 2: "김철수 책임", 3: "LiDAR-X", 4: "레이더 신호처리"}

    def reply(self, name, prompt):
        if name == "taxonomy":
            return _ok({"models": [{"name": "LiDAR-X", "match": ["lidar"], "obs": "보정"},
                                   {"name": "홍길동", "match": ["홍길동"], "obs": "회의"},
                                   {"name": "근태공지", "match": ["근태"], "obs": "공지"},
                                   {"name": "공통", "match": []}]})
        return _ok({"j": [[i, "y", self.PLAN.get(i, "LiDAR-X"), "사무", "홍길동" if i == 3 else "협의"]
                          for i in _idxs(prompt) if i != 5]})        # 5번(공지 제목)은 모델이 빠뜨렸다 — 규칙으로

    def test_no_person_or_notice_models(self):
        rows = [_row(_t(23, 0), "주간 회의 자료 공유 부탁드립니다", who="홍길동/책임/개발팀"),
                _row(_t(23, 5), "10월 근태 입력 확인 바랍니다 x1", who="John Smith"),
                _row(_t(23, 9), "회의실 예약 변경 안내 y2", who="김철수 책임"),
                _row(_t(23, 14), "LiDAR-X 보정 일정 재조정 z3", who="홍길동/책임/개발팀"),
                _row(_t(23, 20), "레이더 신호처리 알고리즘 검토 w4"),
                _row(_t(23, 30), "[근태공지] 10월 근태 마감 안내", activity="공지")]
        self.write_signals(rows)
        self.run_main()
        sig = {r["time"]: r for r in self.signals()}
        models = [r["model"] for r in sig.values()]
        for bad in ("홍길동", "근태공지", "김철수 책임"):
            self.assertNotIn(bad, models)
        self.assertEqual([sig[_t(23, m)]["model"] for m in (0, 5, 9)], ["공통", "공통", "공통"])
        self.assertEqual((sig[_t(23, 14)]["model"], sig[_t(23, 14)]["detail"]), ("LiDAR-X", "검토"))
        self.assertEqual(sig[_t(23, 20)]["model"], "레이더 신호처리")
        notice = sig[_t(23, 30)]
        self.assertEqual((notice["model"], notice["detail"], notice["judge"]), ("공통", "공지·근태", "규칙"))
        with open(os.path.join(self.rep, f"entities_{TAG}.json"), encoding="utf-8") as f:
            ent = json.load(f)
        names = [m["name"] for m in ent["models"]]
        self.assertIn("LiDAR-X", names)
        for bad in ("홍길동", "근태공지", "김철수 책임"):
            self.assertNotIn(bad, names)
        self.assertEqual(ent.get("discovered"), ["레이더 신호처리"])
        self.assertNotIn("fallback", ent)


class FallbackFlag(_Base):
    def reply(self, name, prompt):
        if name == "taxonomy":
            return _ok("지금은 체계를 만들 수 없습니다.")                # 산문 — 체계 파싱 실패 → 규칙 폴백
        return super().reply(name, prompt)

    def test_fallback_entities_flagged(self):
        rows = [_row(_t(24, i), f"lidar 보정 로그 {i}번", project="lidar") for i in range(6)]
        rows += [_row(_t(24, 30 + i), f"홍길동 회의 메모 {i}", project="홍길동", who="홍길동/책임/개발팀")
                 for i in range(3)]
        self.write_signals(rows)
        self.run_main()
        with open(os.path.join(self.rep, f"entities_{TAG}.json"), encoding="utf-8") as f:
            ent = json.load(f)
        self.assertIs(ent.get("fallback"), True)
        names = [m["name"] for m in ent["models"]]
        self.assertIn("lidar", names)
        self.assertNotIn("홍길동", names)                           # 사람 이름 규칙 토큰은 폴백 체계에도 없다
        self.assertTrue(all(m.get("obs") in ("규칙 폴백", "판정 중 발견") for m in ent["models"]))
        self.assertTrue(details.entities_is_fallback(ent))
        self.assertEqual(judge._load_prev_entities(self.rep), ([], ""))   # 다음 실행의 지난 체계로 되먹지 않는다


# ── 순수 함수 ─────────────────────────────────────────────────────────────────────
class Helpers(unittest.TestCase):
    def test_group_key_and_lowinfo(self):
        gk = judge.group_key
        a = gk({"source": "메일(수신)", "text": "RE: [PX] 일정 조율"})
        self.assertIsNotNone(a)
        self.assertEqual(a, gk({"source": "메일(발신)", "text": "FW:  [PX]  일정 조율 "}))
        self.assertNotEqual(gk({"source": "메일(수신)", "text": "설계 검토 1"}), gk({"source": "메일(수신)", "text": "설계 검토 2"}))
        self.assertIsNone(gk({"source": "커밋", "text": "LiDAR-X 보정 수정 반영"}))
        self.assertIsNone(gk({"source": "팀즈(수신)", "text": "네 넵"}))
        self.assertNotEqual(gk({"source": "메일(수신)", "text": "LiDAR-X 회의 안건"}),
                            gk({"source": "팀즈(수신)", "text": "LiDAR-X 회의 안건"}))
        il = judge.is_lowinfo
        self.assertTrue(il({"source": "팀즈(수신)", "text": "네"}))
        self.assertTrue(il({"source": "팀즈(발신)", "text": "확인했습니다!"}))
        self.assertTrue(il({"source": "팀즈(수신)", "text": "[사람] 님 ㅎㅎ"}))
        self.assertFalse(il({"source": "메일(수신)", "text": "네"}))
        self.assertFalse(il({"source": "팀즈(수신)", "text": "LiDAR-X 보정 데이터 공유드립니다"}))

    def test_group_reps_cap(self):
        rows = [{"time": f"2026-03-01 10:{i:02d}", "text": "같은 내용", "weight": "1"} for i in range(5)]
        keys = [("메일", "같은 내용")] * 5
        reps, members = judge.group_reps(rows, range(5), keys, cap=2)
        self.assertEqual(len(reps), 3)                               # 2·2·1 로 나눠 대표 셋
        self.assertEqual(sum(len(v) for v in members.values()), 2)

    def test_cache_roundtrip_and_prune(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t10c_") as tmp:
            cache = {"v": 1, "since": 0, "items": {
                "a" * 20: {"w": 1, "m": "LiDAR-X", "t": "개발", "d": "보정", "at": "2024-01-01"},    # 너무 오래 — 뺀다
                "b" * 20: {"w": 0, "at": "2026-09-01"},
                "c" * 20: {"w": 1, "m": "공통", "t": "사무", "d": "회의", "at": "2026-10-01"},
                "d" * 20: {"w": 1, "m": "공통", "t": "사무", "d": "보고", "at": "2026-10-02"}}}
            with mock.patch.object(judge, "CACHE_MAX", 2):
                self.assertTrue(judge.save_judge_cache(tmp, cache, "2026-01-01"))
            got = judge.load_judge_cache(tmp)
            self.assertEqual(sorted(got["items"]), ["c" * 20, "d" * 20])     # 상한 — 오래 안 쓴 것부터 뺀다
            self.assertEqual(judge._from_cache(got["items"]["c" * 20]),
                             {"work": True, "model": "공통", "worktype": "사무", "detail": "회의"})
            self.assertEqual(judge.load_judge_cache(os.path.join(tmp, "없음"))["items"], {})

    def test_sig2(self):
        r = {"time": "2026-03-01 09:00", "source": "메일(수신)", "text": "LiDAR-X  보정\n결과"}
        self.assertEqual(judge.signal_sig2(r), "2026-03-01 09:00|메일|LiDAR-X 보정 결과")
        self.assertRegex(judge._ckey(judge.signal_sig2(r)), r"^[0-9a-f]{20}$")


if __name__ == "__main__":
    unittest.main()
