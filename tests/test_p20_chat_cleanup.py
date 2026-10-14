# -*- coding: utf-8 -*-
r"""tests\test_p20_chat_cleanup.py — Copilot 채팅 정리(LM28): LM28 이 연 대화만, 다 쓴 때에 대화 목록에서 지운다.

실제 Edge·Copilot 을 쓰지 않는다 — 채팅 탭은 Page(아래)가 흉내 낸다. 운영 JS 를 실행하지 않고 머리 표식(/*LM28:chat_row*/ ·
chat_menu · chat_confirm)과 운영 JS 의 다른 표지(location.href · innerText · 새 채팅 단추 JS)로 알아보고, 그 화면에서 운영 JS 가
'무엇을 보고했을지'(숫자·코드만)를 낸다. 신뢰 입력(CDP Input.dispatchMouseEvent·dispatchKeyEvent)은 좌표로 받는다.
  · 소유 — 연 채팅(보내기 전) → 보냄(앵커 해시) → 이어 보냄 · 화면이 다른 대화면 놓음 · 남이 연 대화는 끝까지 우리 것 아님
  · 앵커 해시 — 상태 파일·기록에 프롬프트 원문이 없다 · 공백 차이·앞뒤에 덧붙은 글에도 찾는다
  · 지우기 판정표 — 끔 · 우리 것 아님 · 보낸 적 없음 · 앵커 없음 · 다른 대화 id · 항목 없음 · 여럿 · 갈림 · 메뉴에 정확한 '삭제' 없음
    · 확인 창은 정확히 '삭제' 단추만 · 확인 창 없음 · 지운 뒤에도 남음(멈춤 — 이 프로세스·다른 프로세스, 판이 바뀌면 풀림) · 목록 펼침
  · 사다리 — 실패한 채팅을 지운 뒤 새 채팅 · 나눔 전송의 새 채팅도 같다
  · 실행 끝 — close_own_edge 가 닫기 전에 지운다(우리 Edge 만 · 막혀도 닫는다 · tidy=False · keepEdgeOpen)
  · 설정 기본값·끄는 값 · run.py 의 'Copilot 채팅 정리' 단계 · 단계 로그 한 줄 · [AI 연결 진단] 줄
임시 폴더만 쓴다(프로필·상태 파일·last_run). 새 프로세스를 띄우지 않는다."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

import _boot

import app  # noqa: E402  — ui\app.py (임포트 부작용 없음)
import copilot_auto as ca  # noqa: E402
import judge  # noqa: E402
import run as R  # noqa: E402

ROOT = _boot.ROOT
BASE = "https://m365.cloud.microsoft/chat"
GREETING = "Copilot\n무엇을 도와 드릴까요?\n오늘 할 일을 정리해 줘\n회의록 요약"
ROW_X, ROW_Y0, ROW_H, MORE_X = 120, 100, 40, 260          # 대화 목록 k 번째 줄 가운데 y = ROW_Y0 + ROW_H·k · 그 줄의 '…' 단추 x
MENU_X, MENU_Y0, MENU_H = 400, 300, 30                    # 열린 메뉴 j 번째 항목
DLG_X0, DLG_W, DLG_Y = 600, 100, 500                      # 확인 창 j 번째 단추
TOGGLE = (20, 20)                                         # 대화 목록 펼침 단추
PROMPT = ("판정 요청입니다. 아래 신호를 판정하세요.\n"
          "#1 | 2026-10-01 09:00 | 메일 | 설계 검토 회의 준비 자료 정리(시험 줄 하나)")
PROMPT2 = ("판정 요청입니다. 아래 신호를 판정하세요.\n"
           "#2 | 2026-10-02 10:30 | 팀즈 | 시험 장비 일정 조율과 결과 공유(시험 줄 둘)")


class Page:
    """Copilot 채팅 탭 흉내 — 대화 목록(최근 순)·지금 대화·'…' 메뉴·확인 창. CDP 객체 자리(eval·call·close·reconnect).
    깃발: ids_in_url(주소에 대화 id) · links(목록 링크에 id) · current(지금 대화 항목에 '현재' 표시) · more('…' 단추 — 항목 위에
    마우스가 있어야 보인다) · menu(메뉴 항목 글) · confirm(확인 창 단추 글 — 비면 확인 창 없이 바로 지운다) · nav_after(지우면 새 채팅
    화면으로) · collapsed(목록 접힘 · toggle 펼침 단추) · dup_current(다른 항목에도 '현재') · split('현재' 가 다른 항목) ·
    wrong_delete(삭제가 다른 대화를 지운다 — 잘못된 화면) · raise_on(그 JS 에서 응답 없음)."""

    def __init__(self, **f):
        self.f = {"ids_in_url": True, "links": True, "current": True, "more": True, "menu": ("이름 바꾸기", "삭제"),
                  "confirm": ("취소", "삭제"), "nav_after": True, "collapsed": False, "toggle": True, "dup_current": False,
                  "split": False, "wrong_delete": False, "raise_on": "", **f}
        self.convs, self.order, self.cur, self.stale = {}, [], None, []
        self.menu_for = self.dialog_for = None
        self.events, self.deleted, self.confirm_clicked = [], [], []
        self.collapsed, self.hover, self.n = bool(self.f["collapsed"]), None, 0

    # ── 화면 모델 ──
    def url(self):
        return BASE + (f"/conversation/{self.cur}" if self.cur and self.f["ids_in_url"] else "")

    def text(self):
        if self.cur is None:
            return GREETING
        return "\n".join(self.convs[self.cur] if self.cur in self.convs else self.stale)

    def new_conv(self, lines=()):
        self.n += 1
        cid = f"a1b2c3d4-0000-4000-8000-{self.n:012d}"
        self.convs[cid] = list(lines)
        self.order.insert(0, cid)
        return cid

    def send(self, prompt, reply='{"j": []}'):
        if self.cur is None:
            self.cur = self.new_conv()
        self.convs[self.cur] += ["나", *str(prompt).splitlines(), "Copilot", reply]
        self.order.remove(self.cur)
        self.order.insert(0, self.cur)

    def fresh(self):
        self.cur = None
        self.events.append(("newchat",))

    def clicks(self):
        return [e for e in self.events if e[0] in ("click", "move")]

    # ── CDP 자리 ──
    def eval(self, js, timeout=25):
        js = str(js)
        m = re.match(r"\s*/\*LM28:(\w+)\*/", js)
        name = m.group(1) if m else ""
        if name and name == self.f["raise_on"]:
            raise TimeoutError("시험 — 응답 없음")
        if name == "chat_row":
            return self._row(js)
        if name == "chat_menu":
            return self._menu()
        if name == "chat_confirm":
            return self._confirm()
        if "location.href" in js:
            return {"url": self.url(), "title": "", "ready": "complete"}
        if "cands[0].click()" in js:                          # js_new_chat
            self.fresh()
            return {"ok": True, "label": "새 채팅"}
        if "innerText" in js:                                 # js_chat_text
            if self.f["raise_on"] == "text":
                raise TimeoutError("시험 — 응답 없음")
            return self.text()
        return None

    def call(self, method, params=None, timeout=25):
        p = params or {}
        if method == "Input.dispatchMouseEvent":
            x, y = p.get("x"), p.get("y")
            if p.get("type") == "mouseMoved":
                self.hover = (x, y)
                self.events.append(("move", x, y))
            elif p.get("type") == "mouseReleased":
                self.events.append(("click", x, y))
                self._click(x, y)
        elif method == "Input.dispatchKeyEvent" and p.get("type") == "rawKeyDown":
            self.events.append(("key", p.get("key")))
            if p.get("key") == "Escape":
                self.menu_for = self.dialog_for = None
        elif method == "Page.navigate":
            self.fresh()
        return {}

    def close(self):
        pass

    def reconnect(self):
        pass

    # ── 운영 JS 가 보고했을 것 ──
    def _row(self, js):
        m = re.search(r'const CONV=("(?:[^"\\]|\\.)*"),ACT=("(?:[^"\\]|\\.)*")', js)
        conv, act = json.loads(m.group(1)), json.loads(m.group(2))
        hr, cr = [], []
        if not self.collapsed:
            hr = [i for i, c in enumerate(self.order) if self.f["links"] and conv and conv in c]
            if self.f["current"] and self.cur in self.order:
                cr.append(self.order.index(self.cur))
            if self.f["dup_current"]:
                cr += [i for i in range(len(self.order)) if i not in cr][:1]
            if self.f["split"]:
                cr = [i for i, c in enumerate(self.order) if c != self.cur][:1]
        if len(hr) > 1:
            return {"r": "many", "nh": len(hr), "nc": len(cr)}
        if len(hr) == 1:
            row, how = hr[0], "href"
            if cr:
                if row not in cr:
                    return {"r": "split", "nh": 1, "nc": len(cr)}
                how = "both"
        elif len(cr) == 1:
            row, how = cr[0], "cur"
        elif len(cr) > 1:
            return {"r": "many", "nh": 0, "nc": len(cr)}
        else:
            if self.collapsed and self.f["toggle"]:
                return {"r": "none", "nh": 0, "nc": 0, "tg": list(TOGGLE)}
            return {"r": "none", "nh": 0, "nc": 0, "ntg": 0}
        y = ROW_Y0 + ROW_H * row
        if act == "find":
            return {"r": "ok", "how": how, "x": ROW_X, "y": y, "nh": len(hr), "nc": len(cr)}
        if not self.f["more"] or self.hover != (ROW_X, y):
            return {"r": "nomore", "how": how}
        return {"r": "ok", "how": how, "x": MORE_X, "y": y, "nb": 1}

    def _menu(self):
        if self.menu_for is None:
            return {"r": "nomenu"}
        hits = [j for j, t in enumerate(self.f["menu"]) if t.strip().lower() in ca.CHAT_DELETE_LABELS]
        n = len(self.f["menu"])
        if not hits:
            return {"r": "nodelete", "n": n}
        if len(hits) > 1:
            return {"r": "many", "n": n}
        return {"r": "ok", "x": MENU_X, "y": MENU_Y0 + MENU_H * hits[0], "n": n}

    def _confirm(self):
        if self.dialog_for is None:
            return {"r": "none"}
        hits = [j for j, t in enumerate(self.f["confirm"]) if t.strip().lower() in ca.CHAT_CONFIRM_LABELS]
        if not hits:
            return {"r": "nobtn", "n": 1}
        if len(hits) > 1:
            return {"r": "many", "n": 1}
        return {"r": "ok", "x": DLG_X0 + DLG_W * hits[0], "y": DLG_Y, "n": 1}

    def _click(self, x, y):
        if (x, y) == TOGGLE and self.collapsed:
            self.collapsed = False
            return
        if x == MORE_X:
            k = (y - ROW_Y0) // ROW_H
            if 0 <= k < len(self.order):
                self.menu_for = self.order[k]
            return
        if x == MENU_X and self.menu_for is not None:
            label = self.f["menu"][(y - MENU_Y0) // MENU_H]
            cid, self.menu_for = self.menu_for, None
            if label.strip().lower() in ca.CHAT_DELETE_LABELS:
                if self.f["confirm"]:
                    self.dialog_for = cid
                else:
                    self._delete(cid)
            return
        if y == DLG_Y and self.dialog_for is not None:
            label = self.f["confirm"][(x - DLG_X0) // DLG_W]
            self.confirm_clicked.append(label)
            cid, self.dialog_for = self.dialog_for, None
            if label.strip().lower() in ca.CHAT_CONFIRM_LABELS:
                self._delete(cid)
            return
        if x == ROW_X:
            k = (y - ROW_Y0) // ROW_H
            if 0 <= k < len(self.order):
                self.cur = self.order[k]

    def _delete(self, cid):
        if self.f["wrong_delete"]:
            others = [c for c in self.order if c != cid]
            if not others:
                return
            cid = others[0]
        self.deleted.append(cid)
        self.events.append(("delete", cid))
        self.order.remove(cid)
        lines = self.convs.pop(cid, [])
        if cid == self.cur:
            if self.f["nav_after"]:
                self.cur = None
            else:
                self.stale = lines                            # 화면만 늦다 — 지운 대화 글이 그대로 보인다


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_p20_")
        self.tmp = self._tmp.name
        self.cfg = dict(ca.DEFAULTS, profileDir=os.path.join(self.tmp, "data", "lm28_edge"), port=9533)
        os.makedirs(os.path.dirname(self.cfg["profileDir"]), exist_ok=True)
        self.traces = []
        self.real_load_cfg = ca.load_cfg                                   # 설정 읽기 시험만 진짜를 쓴다
        self._saved = (json.loads(json.dumps(ca._CHAT_PROC)), ca._CHAT_KILL[0])
        ca._CHAT_PROC.clear()
        ca._CHAT_PROC.update(made=0, deleted=0, kept=0, failed=0, notfresh=0, why={})
        ca._CHAT_KILL[0] = False
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.object(ca, "trace", lambda stage, **kw: self.traces.append(dict(kw, stage=stage))))
        st.enter_context(mock.patch.object(ca, "_sleep", lambda s: None))
        st.enter_context(mock.patch.object(ca, "load_cfg", lambda cfg_path=None: dict(self.cfg)))
        st.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        ca._CHAT_PROC.clear()
        ca._CHAT_PROC.update(self._saved[0])
        ca._CHAT_KILL[0] = self._saved[1]
        self._tmp.cleanup()

    def state(self):
        return ca.chat_state(self.cfg)

    def totals(self):
        return ca.chat_totals(self.cfg)

    def own(self, page, prompt=PROMPT, cfg=None):
        """운영 순서 그대로 — 새 채팅 열기(_chat_opened) → 보내기 전 확인 → 보냄 → 보낸 뒤 → 답 뒤 주소. → 그 대화 id."""
        cfg = cfg or self.cfg
        pre = ca._chat_url(page)
        page.fresh()
        ca._chat_opened(page, cfg, "새 채팅 버튼", pre)
        own = ca._chat_before_send(page, cfg, page.text())
        page.send(prompt)
        ca._chat_after_send(page, cfg, prompt, own)
        ca._chat_seen(page, cfg)
        return page.cur


# ── 1) 소유 — 연 채팅만 우리 것 · 이어 보내기 · 다른 대화면 놓는다 ─────────────────────────────────────
class Ownership(_Base):
    def test_created_then_sent(self):
        page = Page()
        ca._chat_opened(page, self.cfg, "새 채팅 버튼", "")
        st = self.state()
        self.assertEqual((st["ours"], st["sent"], st["pid"]), (True, 0, os.getpid()))
        self.assertTrue(ca._chat_before_send(page, self.cfg, page.text()))
        page.send(PROMPT)
        ca._chat_after_send(page, self.cfg, PROMPT, True)
        ca._chat_seen(page, self.cfg)
        st = self.state()
        sha, n = ca.anchor_key(PROMPT)
        self.assertEqual((st["sent"], st["anchor_sha"], st["alen"]), (1, sha, n))
        self.assertEqual((st["conv"], st["href"]), (page.cur, BASE + "/conversation/" + page.cur))
        self.assertEqual(self.totals()["made"], 1)
        self.assertEqual(ca._CHAT_PROC["made"], 1)

    def test_continued_updates_anchor(self):
        page = Page()
        a = self.own(page)
        self.assertTrue(ca._chat_before_send(page, self.cfg, page.text()))
        page.send(PROMPT2)
        ca._chat_after_send(page, self.cfg, PROMPT2, True)
        st = self.state()
        self.assertEqual((st["sent"], st["anchor_sha"], page.cur), (2, ca.anchor_key(PROMPT2)[0], a))
        self.assertEqual(self.totals()["made"], 1)                          # 이어 보낸 것은 새로 만든 채팅이 아니다

    def test_other_conversation_lets_go(self):
        page = Page()
        b = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        self.own(page)
        page.cur = b                                                         # 누군가 탭을 다른 대화로 옮겼다
        own = ca._chat_before_send(page, self.cfg, page.text())
        self.assertFalse(own)
        page.send(PROMPT2)
        ca._chat_after_send(page, self.cfg, PROMPT2, own)
        st, t = self.state(), self.totals()
        self.assertFalse(st["ours"])                                         # 남의 대화에 이어 보낸 것은 우리 것이 아니다
        self.assertEqual((t["kept"], t["why"]), (1, {"lost": 1}))

    def test_never_ours_without_opening(self):
        page = Page()
        page.cur = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        own = ca._chat_before_send(page, self.cfg, page.text())
        page.send(PROMPT)
        ca._chat_after_send(page, self.cfg, PROMPT, own)
        self.assertFalse(own)
        self.assertFalse(self.state().get("ours"))
        self.assertEqual(self.totals()["made"], 0)

    def test_pending_of_other_process_not_trusted(self):
        page = Page()
        ca._chat_opened(page, self.cfg, "새 채팅 버튼", "")
        st = self.state()
        st["pid"] = os.getpid() + 1
        ca._chats_save(self.cfg, st)
        self.assertFalse(ca._chat_before_send(page, self.cfg, page.text()))
        self.assertFalse(self.state()["ours"])
        self.assertEqual(self.totals()["kept"], 0)                           # 보낸 적 없는 채팅은 목록에 없다 — 세지 않는다

    def test_open_failed_or_same_conversation(self):
        page = Page()
        ca._chat_opened(page, self.cfg, "실패", "")
        self.assertFalse(self.state()["ours"])
        page.cur = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        same = page.url()
        ca._chat_opened(page, self.cfg, "새 채팅 버튼", same)              # 새 채팅 단추를 눌렀는데 주소가 그 대화 그대로
        self.assertFalse(self.state()["ours"])
        self.assertEqual(self.totals()["notfresh"], 1)
        self.assertIn("새 채팅으로 확인되지 않아 맡지 않은 채팅 1", ca.chat_line())

    def test_dead_new_chat_button_falls_back_to_start_url(self):
        page = Page()
        page.cur = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        with mock.patch.object(ca, "new_chat", lambda cdp, cfg: "새 채팅 버튼"):        # 단추를 눌렀는데 화면이 그 대화 그대로
            how = ca._fresh_chat(page, self.cfg, "fresh")
        self.assertEqual(how, "새로 고침")
        self.assertIsNone(page.cur)                                                     # 채팅 시작 주소로 다시 들어갔다(새 채팅 하나)
        st = self.state()
        self.assertEqual((st["ours"], st["sent"], self.totals()["notfresh"]), (True, 0, 0))
        self.assertEqual(page.deleted, [])

    def test_url_without_ids(self):
        page = Page(ids_in_url=False)
        a = self.own(page)
        self.assertEqual(self.state()["conv"], "")
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")    # '현재' 표시로 항목을 찾는다
        self.assertEqual(page.deleted, [a])


# ── 2) 대화 id·앵커 해시 ─────────────────────────────────────────────────────────────────────────
class AnchorAndIds(_Base):
    def test_conv_id(self):
        gid = "a1b2c3d4-0000-4000-8000-000000000007"
        for u in (BASE, BASE + "/", BASE + "?auth=2&origindomain=microsoft365", BASE + "/agents", "", "not a url"):
            self.assertEqual(ca.conv_id(u, self.cfg), "", u)
        self.assertEqual(ca.conv_id(BASE + "/conversation/" + gid, self.cfg), gid)
        self.assertEqual(ca.conv_id(BASE + "#/c/abcd1234efgh5678ij", self.cfg), "abcd1234efgh5678ij")
        self.assertEqual(ca.conv_id(BASE + "?conversationId=AbCdEf0123456789xyz&auth=2", self.cfg), "AbCdEf0123456789xyz")
        self.assertEqual(ca._plain_href(BASE + "/conversation/" + gid + "?q=1#x"), BASE + "/conversation/" + gid)

    def test_anchor_match(self):
        sha, n = ca.anchor_key(PROMPT)
        line = PROMPT.splitlines()[-1]
        self.assertTrue(sha and n >= 20)
        self.assertTrue(ca.page_has_anchor("머리\n" + line + "\n꼬리", sha, n))
        self.assertTrue(ca.page_has_anchor("나: " + line, sha, n))                       # 앞에 이름표
        self.assertTrue(ca.page_has_anchor(line + " · 편집됨", sha, n))                   # 뒤에 덧붙은 글
        self.assertTrue(ca.page_has_anchor(line.replace(" | ", "  |   "), sha, n))       # 공백 차이
        self.assertFalse(ca.page_has_anchor(GREETING, sha, n))
        self.assertFalse(ca.page_has_anchor(None, sha, n))
        self.assertFalse(ca.page_has_anchor(line, "", n))
        self.assertEqual(ca.anchor_key("짧은 줄\n{}"), ("", 0))                            # 20자 미만 — 확인할 수 없다

    def test_no_prompt_text_in_state_or_trace(self):
        mark = "비밀표식ZQXJ"
        prompt = f"판정 요청입니다.\n#9 | 2026-10-03 11:00 | 메일 | {mark} 거래처 회신 내용 정리(시험 줄 셋)"
        page = Page()
        self.own(page, prompt)
        raw = open(ca._chats_path(self.cfg), encoding="utf-8").read()
        for s in (mark, prompt.splitlines()[-1][-60:], "판정 요청"):
            self.assertNotIn(s, raw)
        ca.retire_chat(page, self.cfg, "t")
        raw = open(ca._chats_path(self.cfg), encoding="utf-8").read()
        self.assertNotIn(mark, raw)
        self.assertNotIn(mark, json.dumps(self.traces, ensure_ascii=False))
        self.assertTrue(self.traces)                                                       # 기록은 있다(숫자·코드만)


# ── 3) 지우기 판정표 ───────────────────────────────────────────────────────────────────────────────
class RetireTable(_Base):
    def test_deleted_with_exact_confirm(self):
        page = Page()
        a = self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")
        self.assertEqual((page.deleted, page.confirm_clicked), ([a], ["삭제"]))       # '취소' 는 누르지 않았다
        self.assertEqual([e[0] for e in page.events if e[0] != "move"], ["click", "click", "click", "delete"])
        st, t = self.state(), self.totals()
        self.assertFalse(st["ours"])
        self.assertEqual((t["made"], t["deleted"], t["kept"]), (1, 1, 0))
        self.assertEqual([r["code"] for r in self.traces if r.get("act") == "retire"], ["deleted"])

    def test_off_values(self):
        for v in (False, "false", 0, "off", "no", "0"):
            self.assertFalse(ca._chat_on({"deleteChats": v}), v)
        for v in (True, "true", 1, "", None):
            self.assertTrue(ca._chat_on({"deleteChats": v}), v)
        self.assertTrue(ca._chat_on({}))
        page = Page()
        a = self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, dict(self.cfg, deleteChats="false"), "t"), "off")
        self.assertEqual((page.events, page.deleted, a in page.order), ([], [], True))
        t = self.totals()
        self.assertEqual((t["kept"], t["why"], t["failed"], t["last_fail"]), (1, {"off": 1}, 0, ""))

    def test_not_ours_and_unsent(self):
        page = Page()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "none")
        self.assertFalse(os.path.exists(ca._chats_path(self.cfg)))
        ca._chat_opened(page, self.cfg, "새 채팅 버튼", "")
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "unsent")
        self.assertFalse(self.state()["ours"])
        self.assertEqual(page.events, [])
        t = self.totals()
        self.assertEqual((t["made"], t["kept"]), (0, 0))

    def test_anchor_lost(self):
        page = Page()
        b = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        a = self.own(page)
        page.cur = b
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "lost")
        self.assertEqual((page.events, page.deleted), ([], []))
        self.assertIn(a, page.order)

    def test_other_conversation_id_with_same_line(self):
        page = Page()
        a = self.own(page)
        b = page.new_conv(list(page.convs[a]))                                          # 같은 줄을 담은 다른 대화
        page.cur = b
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "lost")
        self.assertEqual((page.events, page.deleted), ([], []))

    def test_no_item(self):
        page = Page(links=False, current=False)
        self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "noitem")
        self.assertEqual((page.clicks(), page.deleted), ([], []))
        self.assertEqual(self.totals()["failed"], 1)

    def test_ambiguous(self):
        for flags in ({"links": False, "dup_current": True}, {"split": True}):
            page = Page(**flags)
            page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
            self.own(page)
            page.events.clear()
            self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "ambiguous", flags)
            self.assertEqual((page.clicks(), page.deleted), ([], []), flags)

    def test_menu_without_exact_delete(self):
        for menu in (("이름 바꾸기", "삭제하기"), ("Delete forever",), ("공유", "고정")):
            page = Page(menu=menu)
            a = self.own(page)
            page.events.clear()
            self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "nodelete", menu)
            self.assertEqual(page.deleted, [], menu)
            self.assertIn(("key", "Escape"), page.events)                              # 연 메뉴는 닫는다
            self.assertEqual(sum(1 for e in page.events if e[0] == "click"), 1)          # '…' 만 눌렀다
            self.assertIn(a, page.order)

    def test_confirm_only_exact_button(self):
        page = Page(confirm=("취소", "삭제하기"))
        a = self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "noconfirm")
        self.assertEqual((page.deleted, page.confirm_clicked, page.dialog_for), ([], [], None))   # 아무 단추도 안 누름 · Esc
        self.assertIn(a, page.order)
        page = Page(confirm=("Cancel", "Delete"))
        a = self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")
        self.assertEqual((page.deleted, page.confirm_clicked), ([a], ["Delete"]))

    def test_no_dialog_menu_is_final(self):
        page = Page(confirm=())
        a = self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")
        self.assertEqual(page.deleted, [a])

    def test_stale_screen_but_row_gone(self):
        page = Page(nav_after=False)
        a = self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")               # 링크로 찾은 항목이 목록에서 사라졌다
        self.assertEqual(page.deleted, [a])

    def test_collapsed_list_toggle_once(self):
        page = Page(collapsed=True)
        a = self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")
        self.assertEqual(next(e for e in page.events if e[0] == "click"), ("click",) + TOGGLE)
        self.assertEqual(page.deleted, [a])

    def test_error_without_touch(self):
        page = Page(raise_on="chat_row")
        self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "error")
        self.assertEqual(page.events, [])                                                # 누른 것이 없으면 Esc 도 없다
        self.assertFalse(self.state()["ours"])

    def test_mismatch_stops_deleting(self):
        page = Page(wrong_delete=True)
        b = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        a = self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "mismatch")
        self.assertEqual(page.deleted, [b])                                              # 잘못된 화면 — 다른 대화가 지워졌다
        self.assertIn(a, page.order)
        self.assertTrue(ca._CHAT_KILL[0])
        self.assertTrue(self.totals()["hold"])
        self.assertIn("삭제 멈춤", ca.chat_line())
        page.f["wrong_delete"] = False
        self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "hold")                   # 이 프로세스는 더 지우지 않는다
        self.assertEqual(page.events, [])
        ca._CHAT_KILL[0] = False                                                         # 다른 프로세스 — 상태 파일의 멈춤
        self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "hold")
        self.own(page)
        self.assertEqual(ca.retire_current(self.cfg, "t"), "hold")                      # 실행 끝도 화면에 닿지 않고 세기만 한다
        c = self.own(page)
        with mock.patch.object(ca, "CHAT_REV", ca.CHAT_REV + 1):                         # 새 판(화면 규칙을 고친 배포)이면 풀린다
            self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")
        self.assertEqual(page.deleted, [b, c])


# ── 4) 사다리·나눔 — 실패한 채팅을 지운 뒤 새 채팅 ─────────────────────────────────────────────────
class Ladder(_Base):
    ERR = {"ok": True, "phase": "replied", "reply": "죄송합니다. 지금은 응답할 수 없습니다.", "sentinel": False}
    OK = {"ok": True, "phase": "replied", "reply": '{"j": []}', "sentinel": True}

    def drive(self, page, replies):
        def once(cdp, cfg, prompt, model_override=None):
            own = ca._chat_before_send(cdp, cfg, cdp.text())
            cdp.send(prompt)
            ca._chat_after_send(cdp, cfg, prompt, own)
            return dict(replies.pop(0))
        for p in (mock.patch.object(ca, "ensure_edge", lambda cfg: "reused"),
                  mock.patch.object(ca, "find_tab", lambda cfg: "ws://127.0.0.1:9533/devtools/page/c"),
                  mock.patch.object(ca, "CDP", lambda ws: page),
                  mock.patch.object(ca, "new_chat", lambda cdp, cfg: (cdp.fresh(), "새 채팅 버튼")[1]),
                  mock.patch.object(ca, "_roundtrip_once", once)):
            self.stack.enter_context(p)

    def test_ladder_retires_failed_chat_first(self):
        page = Page()
        self.drive(page, [self.ERR, self.OK])
        res = ca.run_roundtrip(self.cfg, PROMPT, fresh=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["retry"].startswith("1단계 재시도 성공"))
        a = page.deleted[0]
        self.assertEqual(len(page.deleted), 1)
        ev = page.events
        last_new = len(ev) - 1 - ev[::-1].index(("newchat",))
        self.assertLess(ev.index(("delete", a)), last_new)                              # 지운 뒤에 새 채팅을 열었다
        st, t = self.state(), self.totals()
        self.assertEqual((st["ours"], st["sent"], st["conv"]), (True, 1, page.cur))
        self.assertNotEqual(page.cur, a)
        self.assertEqual((t["made"], t["deleted"], t["kept"]), (2, 1, 0))
        self.assertEqual(sum(1 for e in ev if e == ("newchat",)), 2)                     # 새 채팅 수는 그대로(처음·사다리 1단계)

    def test_split_fresh_retires_previous(self):
        page = Page()
        a = self.own(page)
        replies = [dict(self.OK, reply="받았습니다 1/2 [[전송끝]]"), dict(self.OK, reply='{"j": []} [[전송끝]]')]
        self.drive(page, replies)
        parts = ["[긴 자료 나눔 1/2] 첫 조각입니다 — 시험용 첫 조각 줄이 충분히 깁니다",
                 "[긴 자료 나눔 2/2 — 마지막] 둘째 조각입니다 — 시험용 둘째 조각 줄이 충분히 깁니다"]
        res = ca._run_parts(page, self.cfg, parts, fresh=True)
        self.assertTrue(res["ok"])
        self.assertEqual(page.deleted, [a])
        st = self.state()
        self.assertEqual((st["ours"], st["sent"]), (True, 2))
        self.assertEqual(self.totals()["made"], 2)


# ── 5) 실행 끝 — close_own_edge 가 닫기 전에 지운다 ───────────────────────────────────────────────
class CloseEdge(_Base):
    def setUp(self):
        super().setUp()
        self.page = page = Page()
        self.a = self.own(page)
        page.events.clear()
        self.assertTrue(ca._write_json(ca.owner_path(self.cfg), {"pid": 1, "port": 9533, "browser": "/devtools/browser/aaa"}))
        self.alive = alive = {"v": True}
        self.closes = closes = []

        class Browser:
            def __init__(self, ws):
                pass

            def call(self, method, params=None, timeout=25):
                if method == "Browser.close":
                    closes.append(1)
                    page.events.append(("close",))
                    alive["v"] = False
                return {}

            def close(self):
                pass

        def http_json(port, path, method="GET"):
            if not alive["v"]:
                raise OSError("닫힘")
            if path == "/json/version":
                return {"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/aaa"}
            if path == "/json":
                return [{"type": "page", "id": "o", "url": "https://outlook.office.com/mail/",
                         "webSocketDebuggerUrl": "ws://127.0.0.1:9533/devtools/page/o"},
                        {"type": "page", "id": "c", "url": page.url(),
                         "webSocketDebuggerUrl": "ws://127.0.0.1:9533/devtools/page/c"}]
            return {}

        def cdp(ws):
            if ws.endswith("/devtools/page/o"):
                raise AssertionError("Outlook 탭에 붙었다")
            return page if "/devtools/page/" in ws else Browser(ws)
        for p in (mock.patch.object(ca, "http_json", http_json),
                  mock.patch.object(ca, "debugger_alive", lambda port: alive["v"]),
                  mock.patch.object(ca, "CDP", cdp)):
            self.stack.enter_context(p)

    def test_deletes_then_closes(self):
        r = ca.close_own_edge(self.cfg, "run_end")
        self.assertEqual((r["closed"], r.get("chats"), self.closes), (True, "deleted", [1]))
        self.assertEqual(self.page.deleted, [self.a])
        self.assertLess(self.page.events.index(("delete", self.a)), self.page.events.index(("close",)))

    def test_blocked_page_still_closes_quickly(self):
        self.page.f["raise_on"] = "text"
        t0 = time.time()
        r = ca.close_own_edge(self.cfg, "run_end")
        self.assertLess(time.time() - t0, 5)
        self.assertEqual((r["closed"], r.get("chats"), self.closes), (True, "error", [1]))
        t = self.totals()
        self.assertEqual((t["kept"], t["why"]), (1, {"error": 1}))

    def test_busy_lock_skips_tidy_but_closes(self):
        import msvcrt
        path = ca.lock_path(self.cfg)
        other = open(path, "a+b")                                                     # 다른 프로세스가 전용 Edge 를 쓰는 중
        try:
            other.seek(0)
            msvcrt.locking(other.fileno(), msvcrt.LK_NBLCK, 1)
            with mock.patch.object(ca, "CHAT_LOCK_WAIT", 0.2):
                r = ca.close_own_edge(self.cfg, "run_end")
            other.seek(0)
            msvcrt.locking(other.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            other.close()
        self.assertEqual((r["closed"], r.get("chats"), self.page.deleted), (True, "busy", []))
        self.assertTrue(self.state()["ours"])                                         # 다음 프로세스가 확인한다

    def test_tidy_false_and_keep_and_not_ours(self):
        r = ca.close_own_edge(dict(self.cfg, keepEdgeOpen=True), "run_end")
        self.assertEqual((r["closed"], r["why"], r.get("chats"), self.closes), (False, "keep", "deleted", []))
        self.own(self.page)
        self.page.events.clear()
        r = ca.close_own_edge(self.cfg, "dead_profile", force=True, tidy=False)
        self.assertEqual((r["closed"], self.page.clicks()), (True, []))
        self.assertTrue(self.state()["ours"])
        seen = {}
        with mock.patch.object(ca, "close_own_edge", lambda cfg, reason="", force=False, tidy=True: seen.update(tidy=tidy)), \
                mock.patch.object(ca, "debugger_alive", lambda port: True):
            ca.recreate_profile(self.cfg)
        self.assertIs(seen["tidy"], False)                                            # 죽은 프로필 교체는 지우지 않는다
        self.assertFalse(os.path.exists(ca.owner_path(self.cfg)))                     # 위에서 닫으며 표식을 치웠다
        self.alive["v"] = True
        r = ca.close_own_edge(self.cfg, "run_end")
        self.assertEqual((r["why"], self.page.clicks()), ("not_ours", []))            # 우리가 띄운 Edge 가 아니면 손대지 않는다


# ── 6) 설정 — 기본 켬 · 두 배포 설정 · 끄는 값 ───────────────────────────────────────────────────────
class Config(_Base):
    def test_defaults_and_files(self):
        self.assertIs(ca.DEFAULTS["deleteChats"], True)
        for name in ("config.default.json", "config.json"):
            with open(os.path.join(ROOT, "config", name), encoding="utf-8-sig") as f:
                c = json.load(f)
            self.assertIs(c["copilotAuto"].get("deleteChats"), True, name)
            self.assertIn("false", c["_copilotAuto_옵션_설명"]["deleteChats"], name)

    def test_load_cfg_values(self):
        cp = os.path.join(self.tmp, "config.json")
        for v, want in ((False, False), ("false", False), (0, False), ("off", False), (True, True), ("", True), (None, True)):
            with open(cp, "w", encoding="utf-8") as f:
                json.dump({"copilotAuto": {"deleteChats": v}}, f)
            self.assertIs(ca._chat_on(self.real_load_cfg(cp)), want, v)               # 0 도 '끔'(빈 값만 기본값)
        with open(cp, "w", encoding="utf-8") as f:
            json.dump({"copilotAuto": {}}, f)
        self.assertTrue(ca._chat_on(self.real_load_cfg(cp)))


# ── 7) run.py — 실행 끝 'Copilot 채팅 정리' 단계 ──────────────────────────────────────────────────────
T0 = {"made": 2, "deleted": 2, "kept": 0, "failed": 0, "notfresh": 0, "why": {}, "last_fail": "", "ours": False, "hold": False}
T1 = {"made": 5, "deleted": 4, "kept": 1, "failed": 1, "notfresh": 0, "why": {"noitem": 1}, "last_fail": "noitem",
      "ours": False, "hold": False}


class RunStage(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p20r_")
        self._saved = (dict(R.REPORT_DIR), dict(R.RUN), list(R.RUN["stages"]), dict(R.CHATS), R._CHAT_TOTALS,
                       dict(R.EDGE), R._CLOSE_EDGE, dict(R.STATE))
        R.REPORT_DIR["p"] = os.path.join(self._td.name, "report")
        R.RUN["stages"] = []
        R.EDGE["closed"] = False
        R.STATE["login_pending"] = False
        R._CLOSE_EDGE = lambda cfg, why: {"closed": True, "why": why}

    def tearDown(self):
        rep, run, stages, chats, tot, edge, close, state = self._saved
        R.REPORT_DIR.clear()
        R.REPORT_DIR.update(rep)
        R.RUN.clear()
        R.RUN.update(run)
        R.RUN["stages"] = stages
        R.CHATS.clear()
        R.CHATS.update(chats)
        R._CHAT_TOTALS, R._CLOSE_EDGE = tot, close
        R.EDGE.clear()
        R.EDGE.update(edge)
        R.STATE.clear()
        R.STATE.update(state)
        self._td.cleanup()

    def test_main_snapshot_then_stage_before_end(self):
        seq = [dict(T0), dict(T1)]
        R._CHAT_TOTALS = lambda cfg: seq.pop(0)
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["run.py", "--from", "2026-10-01", "--to", "2026-10-14", "--web-only", "x"]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(R._main(), 1)                                            # 시작·누계를 남기고 일찍 끝나는 길
            self.assertEqual(R.CHATS["t0"], T0)
            R.record("완료", True, 0.0)
            R.close_edge_once(R.STATE, "run_end")
        names = [x["name"] for x in R.RUN["stages"]]
        self.assertEqual(names, ["시작", "Copilot 채팅 정리", "완료"])               # 끝 단계 앞 — 화면의 '마지막 단계' 를 가리지 않는다
        ent = R.RUN["stages"][1]
        self.assertFalse(ent["ok"])
        self.assertEqual(ent["note"], "만든 3 · 지운 2 · 남긴 1 (사유: 대화 목록에서 못 찾음 1)")
        self.assertIn("── Copilot 채팅 정리", out.getvalue())
        with open(os.path.join(R.REPORT_DIR["p"], "last_run.json"), encoding="utf-8") as f:
            self.assertEqual([x["name"] for x in json.load(f)["stages"]], names)
        self.assertIsNone(R.CHATS["t0"])

    def test_no_activity_no_stage(self):
        R._CHAT_TOTALS = lambda cfg: dict(T0)
        R.CHATS["t0"] = dict(T0)
        with contextlib.redirect_stdout(io.StringIO()):
            R.close_edge_once({}, "run_end")
        self.assertEqual(R.RUN["stages"], [])
        R.EDGE["closed"] = False
        R.CHATS["t0"] = None                                                           # 시작 누계가 없으면(시험·직접 호출) 적지 않는다
        R._CHAT_TOTALS = lambda cfg: dict(T1)
        with contextlib.redirect_stdout(io.StringIO()):
            R.close_edge_once({}, "run_end")
        self.assertEqual(R.RUN["stages"], [])

    def test_run_capture_skips_chat_line(self):
        lines = ["[agentic] 진짜 사유 줄", ca.CHAT_LINE_HEAD + "만든 1 · 지운 0 · 남긴 0", '{"ok": false, "stop_kind": ""}']

        class FP:
            pid = 1

            def wait(self):
                return 1

        def watch(p, on, label):
            for x in lines:
                on(x)
            return ""
        with mock.patch.object(R.subprocess, "Popen", lambda *a, **k: FP()), \
                mock.patch.object(R.proc, "attach", lambda p: None), \
                mock.patch.object(R.proc, "release", lambda j, pid: None), \
                mock.patch.object(R, "watch_child", watch), contextlib.redirect_stdout(io.StringIO()):
            rc, why = R._run_capture(["python", "agentic.py"], {})
        self.assertEqual((rc, why), (1, "[agentic] 진짜 사유 줄"))
        self.assertTrue(ca.CHAT_LINE_HEAD.startswith(R.CHAT_LINE_HEAD))


# ── 8) 단계 로그 한 줄 · [AI 연결 진단] ───────────────────────────────────────────────────────────────
class Lines(_Base):
    def test_stage_line(self):
        self.assertEqual(ca.chat_line(), "")
        st = {}
        for code in ("made", "made", "deleted", "noitem"):
            ca._chat_tally(st, code)
        line = ca.chat_line()
        self.assertEqual(line, ca.CHAT_LINE_HEAD + "만든 2 · 지운 1 · 남긴 1 (사유: 대화 목록에서 못 찾음 1)")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            judge.chat_note()
        self.assertEqual(out.getvalue(), line + "\n")
        self.assertNotIn("{", line)                                                    # 마지막 줄 JSON 으로 읽히지 않는다

    def test_status_line(self):
        self.assertEqual(ca.chat_status(self.cfg), "아직 정리한 채팅 없음")
        page = Page()
        self.own(page)
        ca.retire_chat(page, self.cfg, "t")
        s = ca.chat_status(self.cfg)
        self.assertIn("지움 · 누계 만든 1 · 지운 1 · 남긴 0", s)
        self.assertIn("설정으로 끔", ca.chat_status(dict(self.cfg, deleteChats=False)))

    def test_cli_retire_line(self):
        pf = os.path.join(self.tmp, "p.txt")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(PROMPT)
        seen = []

        def fake_send(cfg, prompt, fresh=False, no_split=False, lock_wait=600, reload=False):
            seen.append(("send", bool(fresh)))
            ca._CHAT_PROC["made"] += 1
            return {"ok": True, "phase": "replied", "reply": '{"ok":"연결됨"}'}

        def fake_retire(cfg=None, why="", budget=25):
            seen.append(("retire", why))
            ca._CHAT_PROC["deleted"] += 1
            return "deleted"
        out = io.StringIO()
        with mock.patch.object(ca, "_send", fake_send), mock.patch.object(ca, "retire_current", fake_retire), \
                mock.patch.object(ca, "stub_dir", lambda: ""), \
                mock.patch.object(sys, "argv", ["copilot_auto.py", "--send", pf, "--fresh", "--retire"]), \
                contextlib.redirect_stdout(out):
            rc = ca.main()
        res = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual((rc, res["chats"], seen), (0, "만든 1 · 지운 1 · 남긴 0", [("send", True), ("retire", "diag")]))

    def test_ui_wiring(self):
        src = _boot.read_text(os.path.join(ROOT, "ui", "app.py"))
        self.assertIn('"--send", pf, "--fresh", "--retire"', src)
        self.assertIn('if(d.chats)L.push("Copilot 채팅 정리: "+d.chats);', app.PAGE)


# ── 9) 화면 JS — 표식·정확한 이름·소스에 아이콘 글꼴 문자 없음 ─────────────────────────────────────────
class Js(unittest.TestCase):
    def test_markers_and_labels(self):
        row = ca.js_chat_row('a"b', "more")
        self.assertTrue(row.startswith("/*LM28:chat_row*/"))
        self.assertIn('const CONV="a\\"b",ACT="more";', row)
        self.assertIn("data-lm28-pre", row)
        menu, confirm = ca.js_chat_menu(), ca.js_chat_confirm()
        self.assertTrue(menu.startswith("/*LM28:chat_menu*/") and confirm.startswith("/*LM28:chat_confirm*/"))
        self.assertIn("const WANT=" + json.dumps(list(ca.CHAT_DELETE_LABELS), ensure_ascii=False) + ";", menu)
        self.assertIn("const WANT=" + json.dumps(["삭제", "delete"], ensure_ascii=False) + ";", confirm)
        self.assertIn("data-lm28-pre", menu)                                          # 누르기 전부터 보이던 메뉴는 뺀다
        self.assertIn("data-lm28-pred", confirm)
        for bad in ("취소", "cancel", "닫기", "close"):
            self.assertNotIn(bad, ca.CHAT_DELETE_LABELS + ca.CHAT_CONFIRM_LABELS)
        pua = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")
        self.assertIsNone(pua.search(_boot.read_text(os.path.join(ROOT, "tools", "copilot_auto.py"))))


if __name__ == "__main__":
    unittest.main()
