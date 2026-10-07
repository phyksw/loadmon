# -*- coding: utf-8 -*-
r"""tests\test_p5_edge.py — WP5: 전용 Edge·Copilot 드라이버(우리 Edge 만 닫기·잠금·정책·계정) + G3 Copilot 직전 관문.

실제 Edge·Copilot·네트워크를 쓰지 않는다 — copilot_auto 의 http_json·CDP·debugger_alive·subprocess.Popen·소켓·정책 읽기를
가짜로 바꾼다. 운영 폴더(report·data)에 쓰지 않는다 — 프로필·report 는 임시 폴더, judge.ROOT·agentic.ROOT 도 임시 폴더로 돌린다.
G3 문맥은 시험용(빈 사전 Ctx + 가짜 카나리아 하나)으로 고정한다 — 이 PC 의 설정·메일 주소에 기대지 않는다.
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
import flow  # noqa: E402
import agentic  # noqa: E402
import refine  # noqa: E402

ROOT = _boot.ROOT
CANARY = "zzcanaryzz"                 # 시험용 카나리아(실재하지 않는 값)


def _cfg(tmp, **kw):
    c = dict(ca.DEFAULTS)
    c.update(profileDir=os.path.join(tmp, "data", "lm28_edge"), port=9533)
    c.update(kw)
    return c


class FakeBrowser:
    """디버그 포트의 브라우저 흉내 — /json/version·/json·Browser.close 만."""

    def __init__(self, alive=True, bid="/devtools/browser/aaa", tabs=None):
        self.alive, self.bid, self.tabs, self.closes = alive, bid, list(tabs or []), 0

    def http_json(self, port, path, method="GET"):
        if not self.alive:
            raise OSError("connection refused")
        if path == "/json/version":
            return {"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}{self.bid}"}
        if path == "/json":
            return list(self.tabs)
        if path.startswith("/json/new"):
            return {"webSocketDebuggerUrl": "ws://127.0.0.1:9533/devtools/page/new"}
        return {}

    def debugger_alive(self, port):
        return self.alive

    def cdp_class(self):
        fb = self

        class C:
            def __init__(self, ws):
                self.ws_url = ws

            def call(self, method, params=None, timeout=25):
                if method == "Browser.close":
                    fb.closes += 1
                    fb.alive = False
                return {}

            def close(self):
                pass
        return C


class FakeCdp:
    """탭 하나의 CDP 흉내 — 상태·AADSTS·본문 글만 돌려주고, 부른 메서드를 기록한다."""

    def __init__(self, url, aadsts="", body=""):
        self.url, self.aadsts, self.body, self.calls = url, aadsts, body, []

    def eval(self, expr, timeout=25):
        if "location.href" in expr:
            return {"url": self.url, "title": "", "ready": "complete"}
        if "AADSTS" in expr:
            return self.aadsts
        if "innerText" in expr:
            return self.body
        return None

    def call(self, method, params=None, timeout=25):
        self.calls.append(method)
        return {}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t5_")
        self.tmp = self._tmp.name
        self.cfg = _cfg(self.tmp)
        ca._PRIV.clear()
        ca._PRIV.update(cfg={}, ctx=privacy.Ctx(), cans=(CANARY,))
        ca._NOTICED.clear()
        ca._POLICY.clear()
        ca.LAST.update(reason="", keep=False, breakaway=True)
        self._patches = [mock.patch.object(ca, "trace", lambda *a, **k: None),
                         mock.patch.object(ca, "_sleep", lambda s: None)]
        for p in self._patches:
            p.start()
        self._err_cm = contextlib.redirect_stderr(io.StringIO())
        self.err = self._err_cm.__enter__()

    def tearDown(self):
        self._err_cm.__exit__(None, None, None)
        for p in self._patches:
            p.stop()
        ca._PRIV.clear()
        ca._POLICY.clear()
        ca.LAST.update(reason="", keep=False, breakaway=True)
        self._tmp.cleanup()

    def browser(self, fb):
        return [mock.patch.object(ca, "http_json", fb.http_json),
                mock.patch.object(ca, "debugger_alive", fb.debugger_alive),
                mock.patch.object(ca, "CDP", fb.cdp_class())]


def _enter(stack, patches):
    for p in patches:
        stack.enter_context(p)


# ── 1) 호스트 분류 — 정확·마디 접미 일치(부분 문자열 금지) ─────────────────────────
class HostTable(_Base):
    WORK = ("https://m365.cloud.microsoft/chat", "https://copilot.cloud.microsoft/",
            "https://outlook.office.com/mail/", "https://contoso.sharepoint.com/sites/a")
    PERSONAL = ("https://copilot.microsoft.com/", "https://login.live.com/oauth20_authorize.srf?client_id=x")
    LOGIN = ("https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
             "https://login.microsoft.com/common/login", "https://certauth.login.microsoftonline.com/x/certauth")
    ADFS = ("https://sts.example.com/adfs/ls/?wa=wsignin1.0",)

    def test_table(self):
        self.assertEqual((len(self.WORK), len(self.PERSONAL), len(self.LOGIN), len(self.ADFS)), (4, 2, 3, 1))
        for kind, urls in (("work", self.WORK), ("personal", self.PERSONAL), ("login", self.LOGIN),
                           ("adfs", self.ADFS)):
            for u in urls:
                self.assertEqual(ca.page_kind(u), kind, u)

    def test_traps(self):
        for u in ("https://example.com/?next=login.microsoftonline.com", "https://m365.cloud.microsoft.example.com/chat",
                  "https://notoffice.com/", "https://example.com/myadfs/x", "https://evil.example/chat"):
            self.assertEqual(ca.page_kind(u), "other", u)
        self.assertEqual(ca.page_kind("https://www.office.com/chat"), "mixed")
        self.assertEqual(ca.page_kind("https://www.microsoft365.com/chat"), "mixed")
        self.assertEqual(ca.page_kind("about:blank"), "blank")
        self.assertEqual(ca.page_kind("chrome-error://chromewebdata/"), "dead")
        # 루프백 가짜 채팅(시험용)만 cfg.url 호스트를 업무로 본다 — 바깥 호스트는 아니다
        self.assertEqual(ca.page_kind("http://127.0.0.1:8123/chat", {"url": "http://127.0.0.1:8123/chat"}), "work")
        self.assertEqual(ca.page_kind("https://evil.example/chat", {"url": "https://evil.example/chat"}), "other")

    def test_chat_tab_excludes_outlook_teams_personal(self):
        want = "m365.cloud.microsoft"
        self.assertTrue(ca._is_chat_tab("https://m365.cloud.microsoft/chat", want))
        self.assertTrue(ca._is_chat_tab("https://login.microsoftonline.com/x", want))
        for u in ("https://outlook.office.com/mail/", "https://teams.microsoft.com/v2/",
                  "https://copilot.microsoft.com/", "https://contoso.sharepoint.com/x"):
            self.assertFalse(ca._is_chat_tab(u, want), u)


# ── 2) AADSTS 번호 → 사유 ─────────────────────────────────────────────────────────
class AadstsTable(unittest.TestCase):
    def test_table(self):
        want = {"53000": "R-LOGIN-DEVICE", "53001": "R-LOGIN-DEVICE", "50097": "R-LOGIN-DEVICE",
                "50005": "R-LOGIN-DEVICE", "50158": "R-LOGIN-WAIT", "53002": "R-CA", "53003": "R-CA",
                "53004": "R-CA", "530032": "R-CA", "53999": "R-CA", "50126": "R-LOGIN", "": "R-LOGIN",
                "abc": "R-LOGIN"}
        for code, r in want.items():
            self.assertEqual(ca.aadsts_reason(code), r, code)
        self.assertEqual(ca.aadsts_kind(53000), "device")
        self.assertEqual(ca.aadsts_kind("x53000"), "")


# ── 3) 우리 Edge 만 닫는다(owner.json + Browser.close) ───────────────────────────
class CloseOwnEdge(_Base):
    def _owner(self, **kw):
        o = {"pid": 1, "port": 9533, "browser": "/devtools/browser/aaa"}
        o.update(kw)
        self.assertTrue(ca._write_json(ca.owner_path(self.cfg), o))

    def _close(self, fb, cfg=None, **kw):
        with contextlib.ExitStack() as st:
            _enter(st, self.browser(fb))
            return ca.close_own_edge(cfg or self.cfg, "test", **kw)

    def test_no_owner_no_close(self):
        fb = FakeBrowser()
        r = self._close(fb)
        self.assertEqual((r["closed"], r["why"], fb.closes), (False, "not_ours", 0))

    def test_owner_close_once_then_delete(self):
        self._owner()
        fb = FakeBrowser()
        r = self._close(fb)
        self.assertTrue(r["closed"])
        self.assertEqual(fb.closes, 1)
        self.assertFalse(os.path.exists(ca.owner_path(self.cfg)))

    def test_keep_edge_open(self):
        self._owner()
        fb = FakeBrowser()
        r = self._close(fb, dict(self.cfg, keepEdgeOpen=True))
        self.assertEqual((r["closed"], r["why"], fb.closes), (False, "keep", 0))
        self.assertTrue(os.path.exists(ca.owner_path(self.cfg)))

    def test_login_pending_kept(self):
        self._owner()
        ca._after(self.cfg, {"ok": False, "phase": "login_required"})      # 로그인 대기 표시
        self.assertTrue(ca.read_owner(self.cfg).get("login_pending"))
        fb = FakeBrowser()
        r = self._close(fb)
        self.assertEqual((r["why"], fb.closes), ("login_pending", 0))
        ca._after(self.cfg, {"ok": True, "phase": "replied"})              # 성공하면 대기 표시가 풀린다
        r = self._close(fb)
        self.assertEqual((r["closed"], fb.closes), (True, 1))

    def test_foreign_browser_not_closed(self):
        self._owner(browser="/devtools/browser/old")
        fb = FakeBrowser(bid="/devtools/browser/someone_else")
        r = self._close(fb)
        self.assertEqual((r["closed"], fb.closes), (False, 0))
        self.assertFalse(os.path.exists(ca.owner_path(self.cfg)))           # 낡은 표식만 치운다


# ── 4) 기동: 정책·Job 이탈 플래그·Origin·소유 확인 ───────────────────────────────
class EnsureEdge(_Base):
    def _launch(self, policies, fail_breakaway=False, fb=None):
        fb = fb or FakeBrowser(alive=False)
        calls = []

        class P:
            pid = 4321

        def fake_popen(args, creationflags=0, **kw):
            calls.append((list(args), creationflags))
            if fail_breakaway and creationflags & ca.CREATE_BREAKAWAY_FROM_JOB:
                raise OSError(13, "Access is denied", None, ca.ERROR_ACCESS_DENIED)
            fb.alive = True
            return P()
        with contextlib.ExitStack() as st:
            _enter(st, self.browser(fb))
            st.enter_context(mock.patch.object(ca, "read_edge_policies", lambda: dict(policies)))
            st.enter_context(mock.patch.object(ca, "find_edge", lambda: r"C:\fake\Edge\msedge.exe"))
            st.enter_context(mock.patch.object(ca.subprocess, "Popen", fake_popen))
            how = ca.ensure_edge(self.cfg)
        return how, calls

    def test_policy_remote_debugging_off(self):
        how, calls = self._launch({"RemoteDebuggingAllowed": 0})
        self.assertIsNone(how)
        self.assertEqual(ca.LAST["reason"], "R-EDGEPOL")
        self.assertEqual(calls, [])
        self.assertEqual(ca.edge_fail(self.cfg).get("reason"), "R-EDGEPOL")

    def test_policy_user_data_dir(self):
        how, calls = self._launch({"UserDataDir": r"D:\forced"})
        self.assertEqual((how, ca.LAST["reason"], calls), (None, "R-EDGEPOL", []))

    def test_policy_clear_on_exit_keep_notice(self):
        how, calls = self._launch({"ClearBrowsingDataOnExit": 1})
        self.assertEqual(how, "launched")
        self.assertTrue(ca.LAST["keep"])
        self.assertIn("keepEdgeOpen", self.err.getvalue())
        self.assertEqual(len(calls), 1)
        args, flags = calls[0]
        self.assertTrue(flags & 0x01000000, "CREATE_BREAKAWAY_FROM_JOB 없음")
        self.assertIn("--remote-allow-origins=http://127.0.0.1:9533", args)
        self.assertFalse(any(a == "--remote-allow-origins=*" for a in args))
        own = ca.read_owner(self.cfg)
        self.assertEqual((own["pid"], own["port"], own["browser"]), (4321, 9533, "/devtools/browser/aaa"))
        self.assertEqual(os.path.normcase(own["root"]), os.path.normcase(ca.ROOT))
        res = {"ok": True, "phase": "replied"}
        ca._after(self.cfg, res)
        self.assertEqual(res.get("edge_keep"), "R-EDGEKEEP")

    def test_cookie_session_only_keep(self):
        how, _calls = self._launch({"DefaultCookiesSetting": 4})
        self.assertEqual((how, ca.LAST["keep"]), ("launched", True))

    def test_breakaway_denied_retry_without_flag(self):
        how, calls = self._launch({}, fail_breakaway=True)
        self.assertEqual(how, "launched")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][1] & ca.CREATE_BREAKAWAY_FROM_JOB)
        self.assertFalse(calls[1][1] & ca.CREATE_BREAKAWAY_FROM_JOB)
        self.assertFalse(ca.LAST["breakaway"])

    def test_foreign_debugger_not_reused(self):
        os.makedirs(self.cfg["profileDir"])
        with open(os.path.join(self.cfg["profileDir"], "DevToolsActivePort"), "w", encoding="utf-8") as f:
            f.write("9533\n/devtools/browser/mine\n")
        fb = FakeBrowser(alive=True, bid="/devtools/browser/someone_else")
        with contextlib.ExitStack() as st:
            _enter(st, self.browser(fb))
            self.assertIsNone(ca.ensure_edge(self.cfg))
            self.assertEqual(ca.LAST["reason"], "R-EDGEFOREIGN")
            fb.bid = "/devtools/browser/mine"
            self.assertEqual(ca.ensure_edge(self.cfg), "reused")

    def test_policy_read_is_cached_and_safe(self):
        ca._POLICY.clear()
        p = ca.read_edge_policies()
        self.assertIsInstance(p, dict)
        self.assertEqual(ca.edge_policy_reason({}), ("", ""))


# ── 5) 같은 프로필은 직렬로 — edge_lock ──────────────────────────────────────────
class EdgeLock(_Base):
    def test_second_holder_gets_busy(self):
        import msvcrt
        path = ca.lock_path(self.cfg)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        other = open(path, "a+b")                    # 다른 프로세스의 잠금 흉내(다른 핸들)
        try:
            other.seek(0)
            msvcrt.locking(other.fileno(), msvcrt.LK_NBLCK, 1)
            with mock.patch.object(ca, "_sleep", time.sleep):
                with self.assertRaises(ca.EdgeBusy) as cm:
                    with ca.edge_lock(self.cfg, timeout=0.3):
                        pass
            self.assertEqual(cm.exception.reason, "R-EDGEBUSY")
            with mock.patch.object(ca, "gate_ok", lambda p: True), mock.patch.object(ca, "stub_dir", lambda: ""):
                r = ca._send(self.cfg, "판정 요청", lock_wait=0.2)
            self.assertEqual((r["ok"], r["reason"]), (False, "R-EDGEBUSY"))
            other.seek(0)
            msvcrt.locking(other.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            other.close()
        with ca.edge_lock(self.cfg, timeout=1):
            with ca.edge_lock(self.cfg, timeout=0):          # 같은 프로세스 안 재진입
                pass
        with ca.edge_lock(self.cfg, timeout=0):                  # 다 풀렸다
            pass


# ── 6) send_inproc — --send 와 같은 dict · 내부 데드라인 ───────────────────────────
class SendInproc(_Base):
    FIXED = {"ok": True, "phase": "replied", "reply": '{"j":[]}', "model": "m", "pick": "anchor",
             "sentinel": True, "cut": False, "parts": 1}

    def _cli(self, prompt):
        pf = os.path.join(self.tmp, "p.md")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt)
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["copilot_auto.py", "--send", pf]), contextlib.redirect_stdout(out):
            rc = ca.main()
        return rc, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_keys_equal_cli(self):
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(ca, "run_roundtrip_split",
                                               lambda cfg, prompt, fresh=False: dict(self.FIXED)))
            st.enter_context(mock.patch.object(ca, "load_cfg", lambda cfg_path=None: dict(self.cfg)))
            st.enter_context(mock.patch.object(ca, "stub_dir", lambda: ""))
            rc, cli = self._cli("판정 요청")
            inp = ca.send_inproc("판정 요청", cfg=self.cfg)
            self.assertEqual(rc, 0)
            self.assertEqual(set(cli), set(inp))
            self.assertEqual(cli, inp)
            # 관문 차단 — 둘 다 같은 꼴(status blocked)
            with mock.patch.object(ca, "gate_ok", lambda p: False):
                rc2, cli2 = self._cli("판정 요청")
                inp2 = ca.send_inproc("판정 요청", cfg=self.cfg)
            self.assertEqual((rc2, cli2.get("status"), set(cli2)), (1, "blocked", set(inp2)))

    def test_keys_equal_cli_stub(self):
        sd = os.path.join(self.tmp, "stub")
        os.makedirs(sd)
        with open(os.path.join(sd, "default.json"), "w", encoding="utf-8") as f:
            f.write('{"x": 1}')
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.dict(os.environ, {"LM_COPILOT_STUB": sd}))
            st.enter_context(mock.patch.object(ca, "load_cfg", lambda cfg_path=None: dict(self.cfg)))
            rc, cli = self._cli("아무 요청")
            inp = ca.send_inproc("아무 요청", cfg=self.cfg)
        self.assertEqual((rc, set(cli)), (0, set(inp)))

    def test_deadline_caps_budget(self):
        seen = {}

        def fake_send(cfg, prompt, fresh=False, no_split=False, lock_wait=600):
            seen.update(cfg=cfg, lock_wait=lock_wait, stage=os.environ.get("LM_STAGE"))
            return {"ok": True}
        before = os.environ.get("LM_STAGE")
        with mock.patch.object(ca, "_send", fake_send):
            ca.send_inproc("p", deadline=time.time() + 200, cfg=dict(self.cfg, roundtripMaxSec=900), stage="chunk1")
        self.assertLessEqual(seen["cfg"]["roundtripMaxSec"], 200)
        self.assertLessEqual(seen["lock_wait"], 140)
        self.assertEqual(seen["stage"], "chunk1")
        self.assertEqual(os.environ.get("LM_STAGE"), before)

    def test_inprocess_false_kept(self):
        cp = os.path.join(self.tmp, "config.json")
        with open(cp, "w", encoding="utf-8") as f:
            json.dump({"copilotAuto": {"inProcess": False, "requireWorkAccount": False, "model": ""}}, f)
        c = ca.load_cfg(cp)
        self.assertIs(c["inProcess"], False)
        self.assertIs(c["requireWorkAccount"], False)
        self.assertEqual(c["model"], ca.DEFAULTS["model"])            # 빈 값은 여전히 기본값


# ── 7) judge.copilot_send — inProcess 면 Popen 0 · 아니면 taskkill 없이 ─────────────
class JudgeTransport(_Base):
    def test_inprocess_no_popen(self):
        got = {}

        def fake_inproc(prompt, fresh=False, deadline=None, cfg=None, stage=""):
            got.update(n=got.get("n", 0) + 1, deadline=deadline, stage=stage)
            return {"ok": True, "phase": "replied", "reply": '{"j":[]}'}

        def boom(*a, **k):
            raise AssertionError("자식 프로세스를 띄웠다")
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(judge, "ROOT", self.tmp))
            st.enter_context(mock.patch.object(judge, "_copilot_cfg", lambda: {"inProcess": True}))
            st.enter_context(mock.patch.object(judge.subprocess, "Popen", boom))
            st.enter_context(mock.patch.object(judge.subprocess, "run", boom))
            st.enter_context(mock.patch.object(ca, "send_inproc", fake_inproc))
            res = judge.copilot_send("판정 요청", "t", "chunk1")
        self.assertTrue(res["ok"])
        self.assertEqual(got["n"], 1)
        self.assertGreater(got["deadline"], time.time())
        self.assertEqual(got["stage"], "chunk1")

    def test_popen_path_without_taskkill(self):
        n = {"popen": 0}

        class FP:
            def __init__(self, *a, **k):
                n["popen"] += 1
                self.stdout = io.BytesIO(b'{"ok": true, "reply": "{}"}\n')
                self.returncode, self.pid = 0, 1

            def poll(self):
                return 0

        def boom(*a, **k):
            raise AssertionError("taskkill 등 다른 프로세스를 띄웠다")
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(judge, "ROOT", self.tmp))
            st.enter_context(mock.patch.object(judge, "_copilot_cfg", lambda: {"inProcess": False}))
            st.enter_context(mock.patch.object(judge.subprocess, "Popen", FP))
            st.enter_context(mock.patch.object(judge.subprocess, "run", boom))
            res = judge.copilot_send("판정 요청", "t", "chunk2")
        self.assertTrue(res["ok"])
        self.assertEqual(n["popen"], 1)

    def test_blocked_prompt_not_written(self):
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(judge, "ROOT", self.tmp))
            st.enter_context(mock.patch.object(judge, "_transport",
                                               lambda *a, **k: self.fail("관문에 걸린 프롬프트를 보냈다")))
            res = judge.copilot_send(f"보고 {CANARY} 연락처", "t", "chunk3")
        self.assertEqual((res["phase"], res.get("status")), ("blocked", "blocked"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "report", "judge_chunk3_t.md")))

    def test_no_taskkill_in_sources(self):
        for rel in ("judge.py", os.path.join("tools", "copilot_auto.py"), "refine.py"):
            src = _boot.read_text(os.path.join(ROOT, rel))
            self.assertIsNone(re.search(r"[\"']taskkill[\"']", src), rel)
        self.assertFalse(hasattr(judge, "kill_tree"))


# ── 8) G3 관문에 막힌 배치 6개 연속 → 규칙 전체로 떨어지지 않고 나머지는 전송 ─────────
class JudgeGateSkips(_Base):
    TAG = "20260101-20260131"

    def _signals(self):
        rep = os.path.join(self.tmp, "report")
        os.makedirs(rep)
        p = os.path.join(rep, f"signals_{self.TAG}.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "source", "who", "project", "activity", "weight", "text", "flag"])
            for i in range(40):
                w.writerow([f"2026-01-{1 + i % 28:02d} 09:{i % 60:02d}", "메일", "", "과제A", "설계", "1",
                            f"설계 검토 {i}", ""])
            for i in range(2):
                w.writerow([f"2026-01-{10 + i:02d} 10:00", "메일", "", "과제A", "설계", "1", f"할인 행사 안내 {i}", "ad"])
        return rep, p

    def test_six_blocked_then_rest_sent(self):
        rep, sp = self._signals()
        sent, blocked = [], {"n": 0}

        def fake_gate(text):
            if "판정 형식:" in str(text) and blocked["n"] < 6:
                blocked["n"] += 1
                return False
            return True

        def fake_transport(prompt_text, pf, name, want_fresh, lim):
            sent.append(name)
            if name == "taxonomy":
                return {"ok": True, "phase": "replied", "reply": json.dumps(
                    {"models": [{"name": "과제A", "match": ["설계"]}, {"name": "공통", "match": []}]},
                    ensure_ascii=False)}
            idxs = [int(x) for x in re.findall(r"^#(\d+) \|", prompt_text, re.M)]
            self.assertNotIn("할인 행사", prompt_text)                 # 광고 의심 행은 보내지 않는다
            return {"ok": True, "phase": "replied", "reply": json.dumps(
                {"j": [[i, "y", "과제A", "개발", "설계 검토"] for i in idxs]}, ensure_ascii=False)}
        argv = ["judge.py", "--from", "2026-01-01", "--to", "2026-01-31", "--chunk", "5",
                "--no-narrate", "--fast", "--redo"]
        out = io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(judge, "ROOT", self.tmp))
            st.enter_context(mock.patch.object(judge, "g3_prompt", fake_gate))
            st.enter_context(mock.patch.object(judge, "_transport", fake_transport))
            st.enter_context(mock.patch.object(sys, "argv", argv))
            st.enter_context(contextlib.redirect_stdout(out))
            rc = judge.main()
        with open(os.path.join(rep, f"ai_judgments_{self.TAG}.json"), encoding="utf-8") as f:
            aj = json.load(f)
        self.assertEqual(rc, 0, out.getvalue()[-800:])
        self.assertEqual(blocked["n"], 6)
        self.assertEqual(aj["chunks"], 8)
        self.assertEqual(aj["skipped_chunks"], 6)
        self.assertEqual(aj["failed_chunks"], 0)
        self.assertFalse(aj["aborted"])
        self.assertEqual(aj["judged"], 10)
        self.assertEqual(aj["ad_rows"], 2)
        self.assertEqual(sent, ["taxonomy", "chunk7", "chunk8"])
        with open(sp, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertIn("flag", rows[0])                                # 되쓸 때 flag 열이 남는다
        self.assertEqual(len(rows), 40)                               # 광고 의심 2행은 비업무로 빠졌다
        self.assertEqual(sum(1 for r in rows if r["judge"] == "AI"), 10)
        self.assertEqual(sum(1 for r in rows if r["judge"] == "규칙"), 30)


# ── 9) G3 행 관문·최종 검사 ─────────────────────────────────────────────────────
class GateRows(_Base):
    def test_gate_rows(self):
        items = [{"text": "설계 검토"}, {"text": "할인 안내", "flag": "ad"}, {"text": "연락처 010-1234-5678 회신"},
                 {"text": f"{CANARY} 보고"}, {"text": "참조 [이메일@vendor.com] 회신"}, {"text": "참조 [이메일@사내] 회신"}]
        kept, why = ca.gate_rows(items, ("text",))
        self.assertEqual([k["text"] for k in kept], ["설계 검토", "참조 [이메일@외부] 회신", "참조 [이메일@사내] 회신"])
        self.assertEqual(why.get("광고의심"), 1)
        self.assertEqual(why.get("개인정보:phone"), 1)
        self.assertEqual(why.get("카나리아"), 1)
        self.assertEqual(items[4]["text"], "참조 [이메일@vendor.com] 회신")         # 원본은 그대로

    def test_gate_prompt(self):
        self.assertTrue(ca.gate_ok("설계 검토 회의"))
        self.assertFalse(ca.gate_ok("연락처 010-1234-5678"))
        self.assertFalse(ca.gate_ok(f"보고 {CANARY}"))
        self.assertTrue(judge.g3_prompt("설계 검토 회의"))
        self.assertTrue(judge.is_ad_row({"flag": "ad"}))
        self.assertFalse(judge.is_ad_row({"flag": "lead"}))

    def test_org_label_not_canary(self):
        ca._PRIV.clear()
        with mock.patch.object(privacy, "make_ctx", lambda cfg, d: privacy.Ctx(internal_domains=["acme.co.kr"])), \
                mock.patch.object(privacy, "canaries", lambda cfg, d: ("acme", "person01")):
            _full, _ctx, cans = ca.privacy_ctx(refresh=True)
        self.assertEqual(cans, ("person01",))


# ── 10) 페이지 판정 — 업무 Copilot 호스트에서만 보낸다 ────────────────────────────
class PageGate(_Base):
    def _once(self, cdp, cfg=None):
        with mock.patch.object(ca.time, "sleep", lambda s: None):
            return ca._roundtrip_once(cdp, cfg or self.cfg, "판정 요청")

    def test_personal_not_sent(self):
        c = FakeCdp("https://copilot.microsoft.com/")
        r = self._once(c)
        self.assertEqual((r["phase"], r["reason"]), ("login_required", "R-PERSONAL"))
        self.assertNotIn("Input.insertText", c.calls)

    def test_mixed_host_navigates_once_then_refuses(self):
        c = FakeCdp("https://www.office.com/chat")
        r = self._once(c)
        self.assertEqual(r["reason"], "R-ACCOUNT")
        self.assertEqual(c.calls.count("Page.navigate"), 1)
        self.assertNotIn("Input.insertText", c.calls)

    def test_login_aadsts_policy(self):
        c = FakeCdp("https://login.microsoftonline.com/common/oauth2", aadsts="53003")
        r = self._once(c)
        self.assertEqual((r["phase"], r["reason"], r.get("aadsts")), ("login_required", "R-CA", "53003"))
        c = FakeCdp("https://sts.example.com/adfs/ls/")
        self.assertEqual(self._once(c)["reason"], "R-LOGIN")

    def test_dead_profile_network_not_counted(self):
        c = FakeCdp("chrome-error://chromewebdata/", body="ERR_INTERNET_DISCONNECTED")
        r = self._once(c)
        self.assertEqual(r["reason"], "R-NET")
        self.assertEqual(int(ca._state(self.cfg).get("dead") or 0), 0)

    def test_dead_profile_two_then_recreate(self):
        os.makedirs(self.cfg["profileDir"])
        c = FakeCdp("chrome-error://chromewebdata/", body="")
        with mock.patch.object(ca, "close_own_edge", lambda *a, **k: {}), \
                mock.patch.object(ca, "debugger_alive", lambda p: False), \
                mock.patch.object(ca, "ensure_edge", lambda cfg: None):
            r1 = self._once(c)
            self.assertEqual((r1["reason"], r1.get("recreated")), ("R-DEADPROFILE", None))
            self.assertTrue(os.path.isdir(self.cfg["profileDir"]))
            r2 = self._once(c)
        self.assertTrue(r2.get("recreated"))
        self.assertFalse(os.path.isdir(self.cfg["profileDir"]))
        bad = [n for n in os.listdir(os.path.dirname(self.cfg["profileDir"])) if n.startswith("lm28_edge.bad-")]
        self.assertEqual(len(bad), 1)
        self.assertEqual(int(ca._state(self.cfg).get("dead") or 0), 0)


# ── 11) 탭 — Outlook·Teams 탭은 닫지도 옮기지도 않는다 · WS 403 → 자기 포트 Origin ────────
class TabsAndOrigin(_Base):
    def _tab(self, tid, url):
        return {"type": "page", "id": tid, "url": url, "webSocketDebuggerUrl": f"ws://127.0.0.1:9533/devtools/page/{tid}"}

    def test_find_tab_keeps_app_tabs(self):
        fb = FakeBrowser(tabs=[self._tab("o", "https://outlook.office.com/mail/"),
                               self._tab("t", "https://teams.microsoft.com/v2/"),
                               self._tab("c1", "https://m365.cloud.microsoft/chat?a=1"),
                               self._tab("c2", "https://m365.cloud.microsoft/chat")])
        closed = []
        with mock.patch.object(ca, "http_json", fb.http_json), \
                mock.patch.object(ca, "_close_tab", lambda port, tid: closed.append(tid) or True):
            ws = ca.find_tab(self.cfg)
        self.assertTrue(ws.endswith("/c1"))
        self.assertEqual(closed, ["c2"])

    def test_find_tab_new_tab_instead_of_moving_app_tab(self):
        fb = FakeBrowser(tabs=[self._tab("o", "https://outlook.office.com/mail/"),
                               self._tab("t", "https://teams.microsoft.com/v2/")])
        with mock.patch.object(ca, "http_json", fb.http_json), \
                mock.patch.object(ca, "_close_tab", lambda port, tid: self.fail("탭을 닫았다")), \
                mock.patch.object(ca, "CDP", lambda ws: self.fail("남의 탭을 옮겼다")):
            ws = ca.find_tab(self.cfg)
        self.assertTrue(ws.endswith("/new"))

    def test_ws_403_retries_with_own_origin(self):
        class FakeSock:
            def __init__(self, resp):
                self.resp, self.sent, self.closed = resp, b"", False

            def settimeout(self, t):
                pass

            def sendall(self, b):
                self.sent += b

            def recv(self, n):
                r, self.resp = self.resp[:n], self.resp[n:]
                return r

            def close(self):
                self.closed = True
        socks = [FakeSock(b"HTTP/1.1 403 Forbidden\r\n\r\n"), FakeSock(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")]
        q = list(socks)
        with mock.patch.object(ca.socket, "create_connection", lambda addr, timeout=None: q.pop(0)):
            ws = ca.ws_open("ws://127.0.0.1:9533/devtools/page/AB")
        self.assertEqual(ws.origin, "http://127.0.0.1:9533")
        self.assertNotIn(b"Origin:", socks[0].sent)
        self.assertTrue(socks[0].closed)
        self.assertIn(b"Origin: http://127.0.0.1:9533\r\n", socks[1].sent)


# ── 12) flow — MM 미전송 · 표본 관문 ────────────────────────────────────────────
class FlowPrompt(_Base):
    def test_no_mm_numbers(self):
        mats_detail = [{"model": "과제A", "detail": "설계", "key": "과제A / 설계", "signals": 5, "level1": "",
                        "mm": 1.234, "desc": "", "parts": [], "episodes": ["요청 'a' → 산출 'b'"],
                        "evidence": ["- 01-02 10:00 [메일] 설계 검토"]}]
        mats_task = [{"model": "과제A", "detail": "", "key": "과제A", "signals": 5, "level1": "", "mm": 1.25,
                      "desc": "", "parts": [["설계", 0.75], ["시험", 0.5]], "episodes": [],
                      "evidence": ["- 01-02 10:00 [메일] 설계 검토"]}]
        for mats in (mats_detail, mats_task):
            p = flow.build_prompt(mats)
            self.assertIsNone(re.search(r"\d+(?:\.\d+)?\s*MM", p), p[-400:])
            for v in ("1.234", "1.25", "0.75", "0.5"):
                self.assertNotIn(v, p)
        self.assertIn("설계 · 시험", flow.build_prompt(mats_task))

    def test_flow_gate(self):
        rows = [{"text": "설계 검토", "time": "2026-01-02 10:00", "source": "메일"},
                {"text": "연락처 010-1234-5678", "time": "2026-01-03 10:00", "source": "메일"},
                {"text": "할인 안내", "flag": "ad", "time": "2026-01-04 10:00", "source": "메일"}]
        self.assertEqual([r["text"] for r in flow._g3_rows(rows)], ["설계 검토"])
        self.assertEqual(flow._g3_texts(["요청 '설계' → 산출 '보고'", f"요청 '{CANARY}' → 산출 'x'"]),
                         ["요청 '설계' → 산출 '보고'"])


# ── 13) agentic — 첫 줄은 config 값 · 대체 MM 산출 없음 ───────────────────────────
class AgenticPrompt(_Base):
    TASKS = [{"id": "T1", "axis": "a", "name": "과제 하나", "desc": "설명"}]
    ROWS = [{"Level 2": "과제A", "Level 3": "설계", "유형": "개발", "근거": "메일3", "상세설명": "검토", "mm": "1.0"}]

    def _with_cfg(self, obj):
        os.makedirs(os.path.join(self.tmp, "config"), exist_ok=True)
        with open(os.path.join(self.tmp, "config", "config.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def test_first_line_from_config(self):
        self._with_cfg({"agentic": {"domainHint": "시험용 업무 영역"}})
        with mock.patch.object(agentic, "ROOT", self.tmp):
            p = agentic.ag_prompt(self.TASKS, self.ROWS)
        self.assertIn("시험용 업무 영역", p.splitlines()[0])
        self._with_cfg({"agentic": {"domainHint": ""}})
        with mock.patch.object(agentic, "ROOT", self.tmp):
            p = agentic.ag_prompt(self.TASKS, self.ROWS)
        self.assertIn(agentic.DOMAIN_HINT_DEFAULT, p.splitlines()[0])
        src = _boot.read_text(os.path.join(ROOT, "agentic.py"))
        self.assertNotIn("LiDAR", src)
        self.assertNotIn("MM", re.sub(r"\(MM 순\)", "", p))           # 행에 MM 값이 없다

    def test_no_replaceable_mm(self):
        out = {"match": [{"task": "T1", "fit": 50, "work": ["설계"], "reason": "r", "load_mm": 9, "load_mm_ai": 3}],
               "new": [{"name": "후보", "logic": "l", "reason": "r", "work": ["설계"], "load_mm": 2.0,
                        "load_mm_ai": 1.0}]}
        agentic.recalc_mm(out, [dict(r) for r in self.ROWS])
        blob = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("load_mm_ai", blob)
        self.assertNotIn("load_mm", out["new"][0])
        self.assertNotIn("sum_new_load_mm", out["mm_recalc"])
        self.assertEqual(out["new"][0]["evidence_rows"], 1)
        self.assertAlmostEqual(out["match"][0]["load_mm"], 1.0)         # 매칭 근거 행의 실측 투입은 남는다
        n = agentic.merge_new([], {"new": [{"name": "x", "work": ["설계"], "load_mm": 5}]})
        self.assertEqual(n, 1)

    def test_agentic_gate(self):
        rows = [dict(self.ROWS[0]), dict(self.ROWS[0], **{"상세설명": "연락처 010-1234-5678"})]
        self.assertEqual(len(agentic.g3_part(rows)), 1)


# ── 14) refine — 제외어 단일원 · 근거 줄 관문 ────────────────────────────────────
class RefineGate(_Base):
    def test_load_exclude_single_source(self):
        with mock.patch.object(refine, "ROOT", self.tmp):
            kws = refine.load_exclude()
        self.assertIn("이력서", kws)                                   # 내장 EXCLUDE 가 설정이 없어도 들어간다
        self.assertEqual(sorted(kws), sorted(k for k in privacy.excluded_keywords({}) if len(k) >= 2))

    def test_sanitize_evidence(self):
        ev = "\n".join(["## #0 과제A / 설계", "- 2026-01-02 [메일] 이력서 정리",
                        "- 2026-01-03 [메일] 연락처 010-1234-5678 회신",
                        "- 2026-01-04 [메일] 설계 검토 [이메일@vendor.com]"])
        txt, dropped, hits = refine.sanitize_evidence(ev, ["이력서"])
        self.assertEqual(dropped, 2)
        self.assertNotIn("이력서", txt)
        self.assertNotIn("010-1234", txt)
        self.assertIn("## #0 과제A / 설계", txt)
        self.assertIn("[이메일@외부]", txt)
        self.assertIn("이력서", hits)

    def test_refiner_blocked_is_skipped_not_retried(self):
        calls = []

        def fake_send(prompt, tag, name, fresh=None):
            calls.append(name)
            return {"ok": False, "status": "blocked", "phase": "blocked"}
        rep = os.path.join(self.tmp, "report")
        os.makedirs(rep)
        rows = [(i, {"Level 2": "과제A", "Level 3": f"업무{i}", "share": "0.1", "활동일수": "1", "근거": "메일1"})
                for i in range(12)]
        rf = refine.Refiner("t", rep, None, "", [], say=lambda *a: None)
        with mock.patch.object(refine, "copilot_send", fake_send):
            n = rf.run(rows, set(), "1")
        self.assertEqual((n, calls), (0, ["refine1"]))                # 반분 재시도 없음
        self.assertEqual((rf.st["gated_items"], rf.st["failed_items"], rf.st["roundtrips"]), (12, 0, 0))

    def test_signal_evidence_skips_ad(self):
        rep = os.path.join(self.tmp, "report")
        os.makedirs(rep)
        with open(os.path.join(rep, "signals_t.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "source", "who", "project", "activity", "weight", "text", "model", "detail", "flag"])
            w.writerow(["2026-01-02 09:00", "메일", "", "과제A", "설계", "1", "설계 검토", "과제A", "설계", ""])
            w.writerow(["2026-01-03 09:00", "메일", "", "과제A", "설계", "1", "할인 안내", "과제A", "설계", "ad"])
        by, judged = refine.load_signal_evidence(rep, "t")
        self.assertTrue(judged)
        self.assertEqual(len(by[("과제A", "설계")]), 1)


# ── 15) judge 공지 예시는 일반어 · 제외어는 단일원 ─────────────────────────────────
class JudgeText(_Base):
    def test_generic_notice_example(self):
        p = judge.judge_prompt([], 0, [{"name": "공통", "match": []}])
        for w in ("인화원", "윤리사무국", "innoHR", "정부24"):
            self.assertNotIn(w, p)

    def test_mine_exclude_single_source(self):
        self.assertEqual(judge._mine_exclude({"excludePathKeywords": ["사적폴더"]}),
                         privacy.excluded_keywords({"excludePathKeywords": ["사적폴더"]}))
        self.assertIn("이력서", judge._mine_exclude({}))


if __name__ == "__main__":
    unittest.main()
