# -*- coding: utf-8 -*-
"""
copilot_auto.py — 사람 개입 없는 M365 Copilot 연동 (Edge DevTools Protocol).

원리: 전용 Edge 프로필(최초 1회만 로그인)을 디버그 포트로 띄우고,
      채팅 입력창에 프롬프트를 넣고 전송 → 응답 텍스트가 안정화되면 회수.
      외부 라이브러리 없이 표준 라이브러리만 사용 (사내 PC pip 제약 대응).

사용:
  python tools\\copilot_auto.py --send prompt.txt --out reply.json   # 프롬프트 전송→응답 회수
  python tools\\copilot_auto.py --send prompt.txt --no-split         # 분할 없이 옛 방식(한 번에 주입)
  python tools\\copilot_auto.py --probe                              # 상태만 확인(로그인 여부 등)
  python tools\\copilot_auto.py --diagnose                           # 입력창/버튼 후보 덤프

종료 출력(stdout, JSON 한 건): {"ok":bool,"phase":str,"reply":str,"error":str,"hint":str,"parts":int,
                              "cut":bool}
  phase: ready | login_required | sent | replied | edge_not_found | launch_failed |
         input_not_found | no_reply | copilot_error | error | stub
  cut: 답 꼬리에 '생성 중단' 문구("OK, I've stopped generating the response.")가 있다 — 재시도
       사다리(새 채팅)로도 반복되면 잘린 앞부분을 ok+cut 으로 돌려주고, 호출자(judge/refine)가
       잘린 JSON 을 마지막 완전한 항목까지 복구한 뒤 나머지만 다시 묻는다(적응 분할).
  전송 전에는 앞 답의 생성이 끝났는지(중지 버튼) 확인하고, 전송 클릭이 '중지'에 먹혀 프롬프트가
  입력창에 남으면 한 번 더 보낸다 — 생성 중 전송이 앞 답을 끊고 다음 왕복까지 시간 초과로 끌던
  큰 사람(청크 20개 이상)의 연속 실패 경로.

긴 프롬프트(LM22, 보완툴 AutoSend 이식):
  · 입력 한도(약 9,000자)를 넘는 프롬프트는 줄 경계에서 8,000자 조각으로 나눠 **같은 채팅**에
    차례로 보내고, 마지막 조각이 "이제 전체를 보고 JSON 을 출력하라"고 시킨다.
  · 모든 답 끝에 [[전송끝]] 서약을 요구한다 — 서약이 보이면 안정 폴링을 기다리지 않고 즉시
    회수하고(조기 완료), 안 보이면 아무것도 보내지 않은 채 같은 탭을 다시 읽으며 기다린다
    (생성 중에 다음 조각을 보내면 전송 버튼이 '중지'가 되어 답을 끊는다 — 실측).
  · 나눔 조각에는 '새 채팅 재시도 사다리'를 쓰지 않는다(앞 조각 문맥이 지워진다) — 실패하면
    새 채팅에서 전체를 처음부터 1회 다시 보낸다.

테스트 전용 스텁(LM_COPILOT_STUB=<dir>):
  · --send 가 Edge 를 띄우지 않고 <dir> 의 JSON 파일을 응답으로 돌려준다(phase "stub").
    회귀 시험(run.py 경로는 자식 프로세스라 in-process 패치가 닿지 않음)만을 위한 분기이며,
    산출물에는 phase 로 '스텁 판정'임이 드러난다. 배포 환경에서는 이 변수를 두지 말 것.
"""
import argparse
import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WIN = 0x08000000

# ── 설정 (config.json 의 copilotAuto 로 덮어쓰기 가능) ──
DEFAULTS = {
    "url": "https://m365.cloud.microsoft/chat",
    "port": 9333,
    "profileDir": os.path.join(ROOT, "data", "copilot_profile"),
    # 입력창 후보 — 위에서부터 시도, 화면에 보이는 첫 요소 사용
    # 실측(2026-08): BizChat 입력창은 SPAN[contenteditable][role=textbox] aria-label="Copilot에 메시지 보내기"
    "inputSelectors": [
        "[contenteditable='true'][role='textbox']",
        ".fai-EditorInput__input",
        "span[contenteditable='true']",
        "div[contenteditable='true']",
        "[contenteditable='plaintext-only']",
        "textarea[placeholder]",
        "textarea",
    ],
    # 전송 버튼 후보 — 없으면 Enter 키로 대체
    "sendSelectors": [
        "button[aria-label*='보내기']", "button[aria-label*='전송']",
        "button[aria-label*='Send']", "button[data-testid*='send']",
        "button[type='submit']",
    ],
    # 응답을 읽을 영역 — 없으면 body 전체
    "chatRootSelectors": ["main", "[role='main']", "body"],
    "model": "GPT-5.6",          # Copilot 채팅의 모델 선택기에서 고를 모델 (부분일치)
    # 서약([[전송끝]]) 조기 완료가 있으므로 안정 폴링을 넉넉히 잡아도 평소 왕복은 느려지지 않는다
    # — 긴 답을 쓰다 잠시 멈춘 것을 완료로 오인해 조기 회수하던 결함(실측) 방지.
    "replyTimeoutSec": 300,
    "stablePolls": 6,          # innerText가 N회 연속 동일하면 응답 완료로 판정
    "pollSec": 2,
}

# ── 긴 프롬프트 분할 (보완툴 AutoSend 이식) ──
# flow.py 실측 주석: "과제 12~15개면 20,000~40,000자가 되어 입력 주입이 한도를 넘긴다".
# 드라이버는 주입 후 앞 15자만 확인하므로 입력창 한도에서 뒤가 잘려도 모른 채 전송된다 →
# 응답 회수 앵커(프롬프트 꼬리)도 못 찾아 실패가 연쇄된다. 그래서 한도 안 조각으로 나눈다.
SAFE_PROMPT = 9000                  # 이 길이까지는 한 번에 보낸다 (flow.py 의 실측 안전 예산)
PART_PROMPT = 8000                  # 조각 크기 (머리말 여유 포함)
SENTINEL = "[[전송끝]]"             # 답이 '다 쓰였다'는 서약 — 이것이 보이기 전에는
                                    # 어떤 클릭·다음 전송도 하지 않는다 (생성 중단 방지)
PLEDGE_TAIL = f"\n\n(답을 다 쓴 뒤 맨 마지막 줄에 {SENTINEL} 이라고 쓰세요.)"
# 호출자(judge/refine/agentic/flow)가 '한 번에 보내려면' 지켜야 할 프롬프트 예산 — SAFE_PROMPT 에서
# 서약 지시(PLEDGE_TAIL)와 여유를 뺀 값. judge.PROMPT_BUDGET 이 같은 값을 복제한다(드라이버 임포트 회피).
PROMPT_BUDGET = SAFE_PROMPT - len(PLEDGE_TAIL) - 550


def make_parts(prompt, reserve=0):
    """긴 프롬프트를 줄 경계에서 조각내고, 조각마다 진행 안내 머리말을 붙인다.
    마지막 조각이 '이제 전체를 분석해 JSON 을 출력하라'고 시킨다.
    reserve: 한 조각일 때 뒤에 덧붙일 서약 지시 길이 — 그만큼 여유를 두고 분할을 결정한다."""
    prompt = str(prompt or "")
    if len(prompt) + int(reserve or 0) <= SAFE_PROMPT:
        return [prompt]
    bodies, cur, size = [], [], 0
    for ln in prompt.splitlines(keepends=True):
        while len(ln) > PART_PROMPT:              # 한 줄이 조각보다 긴 극단 방어
            if cur:
                bodies.append("".join(cur))
                cur, size = [], 0
            bodies.append(ln[:PART_PROMPT])
            ln = ln[PART_PROMPT:]
        if cur and size + len(ln) > PART_PROMPT:
            bodies.append("".join(cur))
            cur, size = [], 0
        cur.append(ln)
        size += len(ln)
    if cur:
        bodies.append("".join(cur))
    total = len(bodies)
    parts = []
    for i, body in enumerate(bodies, 1):
        if i < total:
            pre = (f"[긴 자료 나눔 {i}/{total}] 지시와 자료가 길어 {total}번에 나눠 보냅니다. "
                   f"전체를 받을 때까지 분석·JSON 출력을 시작하지 말고, 이 조각을 기억한 뒤 "
                   f"'받았습니다 {i}/{total} {SENTINEL}' 라고만 답하세요.\n\n")
        else:
            pre = (f"[긴 자료 나눔 {total}/{total} — 마지막] 아래가 자료의 끝입니다. "
                   f"이제 지금까지 받은 조각 전체를 하나의 자료로 보고, 첫 조각의 지시와 "
                   f"출력 형식(JSON) 그대로 분석해 JSON 하나만 출력한 뒤, "
                   f"그 다음 줄에 {SENTINEL} 이라고 쓰세요.\n\n")
        parts.append(pre + body)
    return parts


def echo_sentinels(prompt, anchor, how):
    """응답 슬라이스에 섞여 들어오는 **프롬프트 에코 몫**의 서약 개수.
    pick_reply 가 'anchor' 로 잘랐으면 앵커 뒤 꼬리만 에코로 남고, 'offset' 이면 에코 전체가
    남는다. 프롬프트 자체가 서약 지시("…[[전송끝]] 이라고 쓰세요")를 담고 있으므로 이 몫을
    빼지 않으면 답이 오기도 전에 '서약이 보인다'고 오판한다."""
    prompt = str(prompt or "")
    if how == "anchor" and anchor:
        pos = prompt.rfind(anchor)
        if pos >= 0:
            return prompt[pos + len(anchor):].count(SENTINEL)
    return prompt.count(SENTINEL)


def has_pledge(reply, prompt, anchor, how):
    """이번 답 안에 서약이 있는가 — 에코 몫을 넘는 서약이 있어야 참. 'fulltext' 는 이전
    대화의 옛 서약을 오인할 수 있어 항상 거짓(안정 폴링으로 완료 판정)."""
    if how == "fulltext":
        return False
    return str(reply or "").count(SENTINEL) > echo_sentinels(prompt, anchor, how)


def strip_echo(reply, prompt, anchor, how):
    """응답 슬라이스 앞에 붙은 **프롬프트 에코**를 걷어낸다 — 앵커는 '마지막 8줄 중 가장 긴
    줄'이라 그 뒤 최대 7줄(수백 자)이 답 앞에 따라온다. 그대로 두면 짧은 오류 문구가
    500자 상한을 넘겨 is_error_reply 가 놓치고(재시도 불발), 나눔 조각의 '받았습니다' 확인도
    흐려진다. 공백을 무시한 접두 일치일 때만 자르고, 조금이라도 다르면(렌더 변형·'더 보기'
    접힘) 자르지 않는다 — 잘못 자르면 여는 '{' 가 날아간다."""
    reply = str(reply or "")
    prompt = str(prompt or "")
    if how == "fulltext" or not prompt:
        return reply
    echo = prompt
    if how == "anchor" and anchor:
        pos = prompt.rfind(anchor)
        if pos < 0:
            return reply
        echo = prompt[pos + len(anchor):]
    want = re.sub(r"\s+", "", echo)
    if not want:
        return reply
    i, j, n = 0, 0, len(reply)
    while i < n and j < len(want):
        c = reply[i]
        if c.isspace():
            i += 1
            continue
        if c != want[j]:
            return reply
        i += 1
        j += 1
    return reply[i:] if j == len(want) else reply


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            user = json.load(f).get("copilotAuto") or {}
        cfg.update({k: v for k, v in user.items() if v})
    except Exception:
        pass
    return cfg


def find_edge():
    for p in (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")):
        if os.path.exists(p):
            return p
    return None


def http_json(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def debugger_alive(port):
    try:
        http_json(port, "/json/version")
        return True
    except Exception:
        return False


# ── 최소 WebSocket 클라이언트 (RFC6455, 클라이언트 마스킹/조각 프레임/ping 처리) ──
class WS:
    def __init__(self, url, timeout=30):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("ws handshake: connection closed")
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("ws handshake rejected: " + resp[:120].decode(errors="replace"))

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("ws: connection closed")
            buf += chunk
        return buf

    def send_text(self, text):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = b"\x81"                       # FIN + text
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv_text(self):
        """다음 완결 텍스트 메시지 1건 (조각 프레임 조립, ping 자동 응답)"""
        parts = []
        while True:
            b1, b2 = self._read_exact(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(n) if n else b""
            if opcode == 9:                    # ping → pong
                mask = os.urandom(4)
                masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                self.sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + mask + masked)
                continue
            if opcode == 8:
                raise ConnectionError("ws: closed by server")
            if opcode in (1, 2, 0):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = WS(ws_url)
        self.next_id = 0

    def call(self, method, params=None, timeout=25):
        self.next_id += 1
        mid = self.next_id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while True:
            remain = end - time.time()
            if remain <= 0:
                raise TimeoutError(f"CDP {method}: {timeout}초 내 무응답")
            # per-call 데드라인을 소켓에 실제로 전달 — 고정 30초에 묶이면 timeout 인자가 무의미해진다
            self.ws.sock.settimeout(max(0.5, min(remain, 30.0)))
            try:
                msg = json.loads(self.ws.recv_text())
            except TimeoutError as e:
                # 타임아웃이 프레임 중간에 나면 스트림 동기가 깨질 수 있으므로 이 연결은 재사용 금지
                raise TimeoutError(f"CDP {method}: {timeout}초 내 무응답 (연결 재수립 필요)") from e
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error']}")
                return msg.get("result", {})

    def reconnect(self):
        """타임아웃 후 스트림 desync 대비 — 새 소켓으로 재접속"""
        try:
            self.ws.close()
        except Exception:
            pass
        self.ws = WS(self.ws_url)

    def eval(self, expr, timeout=25):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": False},
                      timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError("JS: " + str(res.get("description", ""))[:200])
        return res.get("value")

    def close(self):
        self.ws.close()


# ── Edge 수명주기 ──
def ensure_edge(cfg):
    """디버그 포트가 살아있으면 재사용, 없으면 전용 프로필로 새로 띄운다"""
    if os.environ.get("LM_NO_BROWSER"):        # 회귀 시험용 — 실제 Edge 를 띄우지 않는다(스텁 드라이버는 무관)
        return None
    port = cfg["port"]
    if debugger_alive(port):
        return "reused"
    edge = find_edge()
    if not edge:
        return None
    os.makedirs(cfg["profileDir"], exist_ok=True)
    subprocess.Popen(
        [edge, f"--user-data-dir={cfg['profileDir']}", f"--remote-debugging-port={port}",
         "--remote-allow-origins=*", "--no-first-run", "--no-default-browser-check",
         "--window-size=1150,900", cfg["url"]],
        creationflags=NO_WIN)
    for _ in range(40):                        # 최대 20초 대기
        time.sleep(0.5)
        if debugger_alive(port):
            return "launched"
    return None


def find_tab(cfg):
    """Copilot 탭을 찾고 없으면 만든다 → ws URL 반환"""
    port = cfg["port"]
    tabs = [t for t in http_json(port, "/json") if t.get("type") == "page"]
    want = cfg["url"].split("//", 1)[-1].split("/", 1)[0]        # 호스트로 매칭
    for t in tabs:
        if want in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    for t in tabs:                              # 로그인 리디렉트 중인 탭도 인정
        if "login.microsoftonline" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    from urllib.parse import quote
    for method in ("PUT", "GET"):               # 신버전은 PUT, 구버전은 GET
        try:
            t = http_json(port, "/json/new?" + quote(cfg["url"], safe=""), method=method)
            return t["webSocketDebuggerUrl"]
        except Exception:
            continue
    if tabs:
        return tabs[0]["webSocketDebuggerUrl"]
    return None


# ── 페이지 조작 ──
def js_state():
    return "({url: location.href, title: document.title, ready: document.readyState})"


def login_required(state):
    u = (state or {}).get("url", "")
    return ("login.microsoftonline" in u) or ("login.live.com" in u) or (u == "about:blank")


def js_chat_text(cfg):
    sels = json.dumps(cfg["chatRootSelectors"])
    return ("(function(){for(const s of " + sels + "){const el=document.querySelector(s);"
            "if(el&&el.innerText&&el.innerText.length>0)return el.innerText;}"
            "return document.body?document.body.innerText:'';})()")


def js_pick_model(model):
    """모델 선택기(실측 aria-label '모델 선택기')를 열고 이름이 일치하는 항목을 클릭.
    이미 선택돼 있으면 스킵. 실패해도 전체 왕복은 계속한다(베스트 에포트)."""
    m = json.dumps(model)
    return ("""(function(){
  const want=""" + m + """.toLowerCase();
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const btns=[...document.querySelectorAll("button")].filter(b=>vis(b)&&
    ((b.getAttribute("aria-label")||"").includes("모델")||(b.getAttribute("aria-label")||"").toLowerCase().includes("model")));
  if(!btns.length)return {ok:false,err:"selector_not_found"};
  const btn=btns[0];
  const cur=(btn.getAttribute("aria-label")||"")+" "+(btn.innerText||"");
  if(cur.toLowerCase().includes(want))return {ok:true,already:true,cur:cur.slice(0,60)};
  // 이미 열려 있으면 다시 누르면 '닫힌다'(토글). 실측에서 이 때문에 모델 선택이 매번
  // 실패했다 — 열려 있는지 먼저 확인하고, 닫혀 있을 때만 연다.
  const open=[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")]
    .filter(vis).length;
  if(open>0)return {ok:true,opened:true,alreadyOpen:true,items:open};
  btn.click();
  return {ok:true,opened:true};
})()""")


def js_menu_open():
    return ("""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  return {open:[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")]
    .filter(vis).length};
})()""")


def js_pick_model_item(model):
    """열린 메뉴에서 목표 모델을 클릭. 최상위에 없으면 'GPT ›' 같은 하위 메뉴를 열어야 하므로
    submenu 후보를 돌려준다 — 실측(2026-08) Copilot 메뉴가
    [자동 / 빠른 응답 / 깊이 생각하기 / GPT ›] 구조로 바뀌어 평면 검색만으로는 못 찾는다."""
    m = json.dumps(model)
    return (r"""(function(){
  const want=""" + m + r""".toLowerCase();
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  // 메뉴 role 이 있는 항목만 — li/button 전역 탐색은 무관한 화면 요소를 클릭할 위험(실측 메뉴는 전부 role 보유)
  const nodes=[...document.querySelectorAll("[role='menuitemradio'],[role='menuitem'],[role='option']")]
    .filter(vis);
  const txt=e=>(e.innerText||e.getAttribute("aria-label")||"").trim();
  // 표기 차이를 무시하고 비교한다 — 설정은 'GPT-5.6' 인데 메뉴 실제 이름은
  // 'GPT 5.6 깊이 생각하기'(하이픈이 아니라 공백)라 그대로 비교하면 영원히 못 찾는다(실측).
  const norm=x=>x.toLowerCase().replace(/[-\s._]/g,"");
  const wantN=norm(want);
  // 1) 목표 모델이 그대로 보이면 클릭
  const hit=nodes.find(e=>norm(txt(e)).includes(wantN));
  if(hit){hit.click();return {ok:true,picked:txt(hit).slice(0,60)};}
  // 2) 없으면 하위 메뉴 후보 — 목표 이름의 앞 토큰(예: 'GPT-5.6' → 'gpt')을 품고
  //    펼침 표시(aria-haspopup / aria-expanded / › 아이콘)가 있는 항목
  const head=norm(want).replace(/[0-9].*$/,"") || want.split(/[-\s._]/)[0];
  const sub=nodes.find(e=>{
    const t=norm(txt(e));
    if(!t||t.length>40)return false;
    const looksParent=e.getAttribute("aria-haspopup")||e.getAttribute("aria-expanded")!==null
      ||/[›>❯»]/.test(txt(e))||(e.querySelector&&e.querySelector("svg"));
    return t.includes(head)&&looksParent;
  });
  if(sub){sub.click();return {ok:false,submenu:txt(sub).slice(0,40)};}
  return {ok:false,err:"item_not_found",seen:nodes.slice(0,12).map(txt).filter(Boolean).slice(0,8)};
})()""")


def select_model(cdp, cfg, override=None):
    """전송 전에 모델을 선택한다 — 실패는 경고로만 남기고 진행.
    메뉴가 [모드 목록 + 'GPT ›' 하위 메뉴]로 바뀌었으므로 하위 메뉴를 한 단계 열어본다.
    override 는 재시도 사다리의 '자동 모델 폴백'용."""
    model = (override or cfg.get("model") or "").strip()
    if not model:
        return "모델 미지정"
    try:
        r1 = cdp.eval(js_pick_model(model)) or {}
        if r1.get("already"):
            return f"모델 유지({model})"
        if not r1.get("ok"):
            return "모델 선택기 없음 — 기본 모델 사용"
        time.sleep(0.9)
        # 클릭했는데 안 열렸으면(렌더 지연·클릭 무시) 한 번 더 연다
        if not r1.get("alreadyOpen"):
            chk = cdp.eval(js_menu_open()) or {}
            if not chk.get("open"):
                cdp.eval(js_pick_model(model))
                time.sleep(1.0)
        seen = []
        for _depth in range(3):                     # 최상위 → 하위 메뉴 → 그 하위까지
            r2 = cdp.eval(js_pick_model_item(model)) or {}
            if r2.get("ok"):
                time.sleep(0.7)
                return f"모델 선택: {r2.get('picked', model)}"
            if r2.get("submenu"):
                time.sleep(0.9)                     # 하위 메뉴 열림 대기
                continue
            seen = r2.get("seen") or seen
            break
        cdp.eval("(function(){document.body.click();return 1;})()")   # 메뉴 닫기
        hint = (" · 메뉴: " + ", ".join(seen)) if seen else ""
        return f"모델 '{model}' 항목 없음 — 기본 모델 사용{hint}"
    except Exception as e:
        return f"모델 선택 실패({type(e).__name__}) — 기본 모델 사용"


def js_focus(cfg):
    """입력창을 찾아 포커스만 준다 — 실제 주입은 CDP Input.insertText가 정석
    (React/Lexical류 리치 에디터는 execCommand/DOM 조작을 무시하는 경우가 많음)"""
    sels = json.dumps(cfg["inputSelectors"])
    return ("""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>40&&r.height>8;};
  let el=null,sel='';
  for(const s of """ + sels + """){
    for(const c of document.querySelectorAll(s)){ if(vis(c)&&!c.disabled){el=c;sel=s;break;} }
    if(el)break;
  }
  if(!el)return {ok:false,err:'input_not_found'};
  el.focus();
  window.__lm_input=el;
  return {ok:true,tag:el.tagName,sel:sel};
})()""")


def js_editor_text():
    return ("(function(){const el=window.__lm_input;if(!el)return '';"
            "return el.value!==undefined&&el.tagName!=='DIV'?el.value:(el.innerText||el.textContent||'');})()")


def js_insert_fallback(prompt):
    """Input.insertText가 안 먹은 경우의 예비: execCommand → 값 직접 설정 + input 이벤트"""
    p = json.dumps(prompt)
    return ("""(function(){
  const el=window.__lm_input; if(!el)return {ok:false};
  el.focus();
  const p=""" + p + """;
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){
    const d=Object.getOwnPropertyDescriptor(el.__proto__,'value');
    if(d&&d.set){d.set.call(el,p);}else{el.value=p;}
    el.dispatchEvent(new Event('input',{bubbles:true}));
  }else{
    let done=false;
    try{done=document.execCommand('insertText',false,p);}catch(e){}
    if(!done){
      el.textContent=p;
      el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:p}));
    }
  }
  return {ok:true};
})()""")


def js_click_send(cfg):
    sels = json.dumps(cfg["sendSelectors"])
    return ("""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  for(const s of """ + sels + """){
    for(const b of document.querySelectorAll(s)){
      if(vis(b)&&!b.disabled){b.click();return {ok:true,sel:s};}
    }
  }
  return {ok:false};
})()""")


def press_enter(cdp):
    for t, key in (("rawKeyDown", None), ("char", "\r"), ("keyUp", None)):
        params = {"type": t, "key": "Enter", "code": "Enter",
                  "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
        if key:
            params["text"] = key
        cdp.call("Input.dispatchKeyEvent", params)


def js_diagnose():
    return """(function(){
  const info=el=>{const r=el.getBoundingClientRect();
    return {tag:el.tagName,visible:r.width>0&&r.height>0,w:Math.round(r.width),
      aria:el.getAttribute('aria-label')||'',testid:el.getAttribute('data-testid')||'',
      role:el.getAttribute('role')||'',ph:el.getAttribute('placeholder')||''};};
  return {url:location.href,title:document.title,
    editors:[...document.querySelectorAll("[contenteditable],[role='textbox'],textarea,input")].slice(0,10).map(info),
    buttons:[...document.querySelectorAll('button')].filter(b=>{const r=b.getBoundingClientRect();return r.width>0;}).slice(0,40).map(info)};
})()"""


# Copilot 일시 오류 응답 — 이 문구가 오면 내용이 아니라 서비스 상태 문제다 (실측 스크린샷)
# '다시 시도' 단독은 정상 분석문에 인용될 수 있어 트리거에서 제외 — 서비스 오류를
# 단정할 수 있는 정형 문구만 쓴다 (스크린샷 문구는 '응답할 수 없습니다'로 잡힌다)
ERROR_REPLY_MARKS = ("응답할 수 없습니다", "응답 할 수 없습니다", "문제가 발생했",
                     "무언가 잘못", "죄송합니다. 지금은",
                     "sorry, i can't respond", "something went wrong", "can't respond right now")


def is_error_reply(reply):
    """짧고 정형화된 오류 문구인지 — 정상 분석문에 인용된 경우를 배제하려고
    길이(500자 미만)와 앞부분(300자) 매칭을 함께 본다."""
    r = (reply or "").strip()
    if not r or len(r) > 500:
        return False
    head = r[:300].lower()
    return any(m.lower() in head for m in ERROR_REPLY_MARKS)


# 생성이 중간에 끊긴 답 — 생성 중에 전송 버튼을 누르면(그때는 '중지' 버튼이다) Copilot 이 남기는 정형
# 문구(실측 "OK, I've stopped generating the response."). 오류 응답과 달리 **앞부분에 정상 답(잘린 JSON)이
# 붙어 있을 수 있어** 꼬리에서 찾고, 호출자가 잘린 JSON 을 복구해 쓸 수 있게 ok 는 유지한 채 cut 표식만 단다.
CUT_REPLY_MARKS = ("i've stopped generating", "stopped generating the response", "stopped generating",
                   "응답 생성을 중지", "응답 생성을 중단", "생성을 중지했", "생성이 중지되", "생성을 중단했")


def is_cut_reply(reply):
    """답의 꼬리(300자)에 '생성 중단' 문구가 있는가."""
    tail = (reply or "").strip()[-300:].lower()
    return bool(tail) and any(m in tail for m in CUT_REPLY_MARKS)


def js_is_generating():
    """아직 답을 쓰는 중인가 — 전송 자리에 '중지' 버튼이 떠 있으면 생성 중이다.
    UI 표기가 바뀌어도 죽지 않게 후보 문구를 넓게 잡고, 못 찾으면 '생성 중 아님'(진행)."""
    return r"""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const b=[...document.querySelectorAll("button")].filter(vis).find(e=>{
    const t=((e.getAttribute("aria-label")||"")+" "+(e.getAttribute("title")||"")).toLowerCase().trim();
    return t.includes("생성 중지")||t.includes("응답 중지")||t.includes("stop generating")||
           t.includes("stop responding")||t==="stop"||t==="중지";});
  return !!b;})()"""


def wait_idle(cdp, secs=45):
    """앞 답의 생성이 끝날 때까지 기다린다(최대 secs). 생성 중에 다음 프롬프트를 보내면 전송 버튼이
    '중지'라 클릭이 **앞 답을 끊고**(잘린 JSON) 새 프롬프트는 입력창에 남는다(실측) — 큰 사람(청크 20개
    이상)에서 연속 실패의 시작점이었다. returns 기다린 초(0 = 바로 진행)."""
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            if not cdp.eval(js_is_generating()):
                break
        except (TimeoutError, RuntimeError, OSError):
            break
        time.sleep(2)
    return round(time.time() - t0, 1)


def js_new_chat():
    return r"""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const cands=[...document.querySelectorAll("button,a")].filter(vis).filter(e=>{
    const t=((e.getAttribute("aria-label")||"")+" "+(e.innerText||"")).toLowerCase();
    return t.includes("새 채팅")||t.includes("새 대화")||t.includes("new chat");});
  if(!cands.length)return {ok:false};
  cands[0].click();
  return {ok:true,label:(cands[0].getAttribute("aria-label")||cands[0].innerText||"").slice(0,30)};
})()"""


def new_chat(cdp, cfg):
    """새 채팅으로 전환 — 버튼을 찾으면 클릭, 없으면 채팅 URL 재진입(새 대화로 열림)."""
    try:
        r = cdp.eval(js_new_chat()) or {}
        if r.get("ok"):
            time.sleep(3)
            return "새 채팅 버튼"
    except Exception:
        pass
    try:
        cdp.eval("(function(){location.href=" + json.dumps(cfg["url"]) + ";return 1;})()")
        for _ in range(20):
            time.sleep(1)
            st = cdp.eval(js_state())
            if st and st.get("ready") in ("interactive", "complete"):
                break
        time.sleep(2)
        return "URL 재진입"
    except Exception:
        return "실패"


def run_roundtrip(cfg, prompt, fresh=False):
    """프롬프트 전송 → 응답 회수. Copilot 일시 오류('응답할 수 없습니다')나 무응답이면
    단계적으로 재시도한다: ① 새 채팅에서 같은 모델로 ② 새 채팅 + 자동 모델로.
    어느 단계에서 성공했는지 retry 노트로 남긴다."""
    how = ensure_edge(cfg)
    if how is None:
        return {"ok": False, "phase": "edge_not_found" if not find_edge() else "launch_failed",
                "error": "Edge 실행 실패",
                "hint": "Edge 설치 여부 확인 · 보안 정책이 디버그 포트를 막는 환경이면 클립보드(수동) 방식 사용"}
    ws_url = find_tab(cfg)
    if not ws_url:
        return {"ok": False, "phase": "launch_failed", "error": "Copilot 탭을 만들 수 없음",
                "hint": "열린 Edge(자동 프로필) 창에서 직접 주소를 열어보세요: " + cfg["url"]}
    cdp = CDP(ws_url)
    try:
        if fresh:
            # 판정처럼 '깨끗한 문맥'이 필요한 왕복은 새 채팅에서 시작한다 —
            # 앞선 실패 대화(예: 팀즈 조회 거절)가 문맥에 남으면 답이 오염된다.
            try:
                new_chat(cdp, cfg)
            except Exception:
                pass
        res = _roundtrip_once(cdp, cfg, prompt)
        # 끊긴 답(cut)도 재시도 사유다 — 다만 앞부분에 잘린 JSON 이 남아 있을 수 있어 전부 실패하면
        # 그 답을 ok+cut 으로 돌려주고 호출자가 복구·부분 재시도한다(judge/refine 의 적응 분할).
        bad = ((res.get("ok") and (is_error_reply(res.get("reply")) or res.get("cut")))
               or res.get("phase") == "no_reply")
        if not bad:
            return res
        # ① 새 채팅에서 같은 모델로 재시도 (대화 문맥 오염·일시 오류 해소)
        how2 = new_chat(cdp, cfg)
        res2 = _roundtrip_once(cdp, cfg, prompt)
        if res2.get("ok") and not is_error_reply(res2.get("reply")) and not res2.get("cut"):
            res2["retry"] = f"1단계 재시도 성공 (새 채팅 · {how2})"
            return res2
        # ② 새 채팅 + 자동 모델 폴백 (특정 모델 라우팅 장애 대비)
        new_chat(cdp, cfg)
        res3 = _roundtrip_once(cdp, cfg, prompt, model_override="자동")
        if res3.get("ok") and not is_error_reply(res3.get("reply")) and not res3.get("cut"):
            res3["retry"] = "2단계 재시도 성공 (새 채팅 + 자동 모델)"
            return res3
        # 전부 실패 — 마지막 결과에 실패 이력. 끊긴 답 중에는 가장 긴 것을 남긴다(복구 재료).
        cuts = [r for r in (res, res2, res3) if r.get("ok") and r.get("cut") and not is_error_reply(r.get("reply"))]
        if cuts:
            final = max(cuts, key=lambda r: len(r.get("reply") or ""))
            final["retry"] = "끊긴 답 — 새 채팅·자동 모델 재시도에도 반복(잘린 앞부분만 회수)"
            return final
        final = res3 if res3.get("reply") else (res2 if res2.get("reply") else res)
        if final.get("ok") and is_error_reply(final.get("reply")):
            final = {"ok": False, "phase": "copilot_error", "reply": final.get("reply", ""),
                     "error": "Copilot 일시 오류 — 3단계 재시도 모두 실패",
                     "hint": "잠시 후 다시 실행하거나 Copilot 창에서 상태를 확인하세요"}
        final["retry"] = "새 채팅·자동 모델 재시도 모두 실패"
        return final
    finally:
        cdp.close()


def build_anchor(prompt):
    """에코 앵커 — 페이지 텍스트에서 프롬프트 끝을 찾기 위한 표식.

    **반드시 개행이 없는 단 한 줄**이어야 한다. 예전에는 40자가 될 때까지 여러 줄을
    모아 공백으로 이어 붙였는데, 페이지 innerText 의 같은 자리에는 개행이 있어
    rfind 가 구조적으로 실패했다(실증: 현실적 4케이스 중 3개 -1). 앵커를 못 찾으면
    오프셋 폴백으로 떨어지고, 그 오프셋이 틀리면 응답 앞부분이 잘린다.

    마지막 8줄 중 '가장 긴 줄'을 쓴다 — 길수록 고유해서 에코 중간에 잘못 걸릴 위험이 낮다.
    """
    cands = [ln.strip() for ln in str(prompt or "").strip().splitlines() if ln.strip()][-8:]
    if not cands:
        return ""
    best = max(cands, key=len)
    return best[-100:] if len(best) >= 20 else ""


def pick_reply(txt, base, anchor):
    """페이지 전체 텍스트에서 '이번 응답'만 잘라낸다.

    ① 앵커를 찾았고 위치가 그럴듯하면 그 뒤 — 가장 정확하다.
    ② 앵커가 없어도 오프셋이 믿을 만하면 그 뒤.
    ③ 둘 다 아니면 **전문**. 자르는 것보다 안전하다 — 소비자는 rfind('{') 로 뒤에서부터
       JSON 을 찾으므로 앞에 메뉴·이전 대화가 섞여도 파싱에 지장이 없다. 반대로 잘못
       자르면 여는 '{' 가 날아가 응답이 통째로 버려진다.
    """
    if anchor:
        pos = txt.rfind(anchor)
        if pos >= 0 and pos >= base - 2000:
            return txt[pos + len(anchor):], "anchor"
    if base and base <= len(txt):
        # 오프셋이 페이지 안쪽을 가리킨다 = 아직 믿을 수 있다. 뒤가 짧아도(응답이 짧거나
        # 아직 도착 전) 그대로 쓴다 — 여기서 전문으로 넘기면 메뉴·이전 대화가 응답에
        # 섞인다(LM13 에서 고쳤던 결함의 재발 경로).
        return txt[base:], "offset"
    # base 가 페이지 길이보다 크다 = 인사말·추천 카드가 사라져 텍스트가 줄었다는 뜻.
    # 그 오프셋으로 자르면 응답 앞부분(여는 '{')이 날아간다 — 자르지 않는 편이 안전하다.
    return txt, "fulltext"


def _roundtrip_once(cdp, cfg, prompt, model_override=None):
    if True:
        # 페이지 로드/로그인 확인
        state = None
        for _ in range(30):
            state = cdp.eval(js_state())
            if state and state.get("ready") in ("interactive", "complete") and not login_required(state):
                break
            time.sleep(1)
        if login_required(state):
            return {"ok": False, "phase": "login_required",
                    "error": "로그인 필요 (최초 1회)",
                    "hint": "방금 열린 Edge 창에서 회사 계정으로 로그인해 두세요 — 이후에는 무개입으로 동작합니다"}
        time.sleep(2)                          # SPA 렌더 여유
        # 앞 답이 아직 생성 중이면 끝날 때까지 기다린다 — 생성 중 전송 클릭은 '중지'가 되어 앞 답을
        # 끊고(잘린 JSON) 이번 프롬프트는 입력창에 남는다. 큰 사람의 연속 실패가 여기서 시작됐다.
        waited = wait_idle(cdp)
        note_model = select_model(cdp, cfg, override=model_override)

        # 대형 DOM(긴 대화)에서 innerText 평가가 25초를 넘겨 왕복 전체가 error 로 죽던
        # 결함(검증 확정) — 응답 대기 루프(아래)와 같은 재수립 가드를 준다. 폴백은 0이
        # 아니라 재시도다: baseline=0 이면 앵커 미발견 시 페이지 전문이 응답으로 회수된다.
        try:
            baseline = len(cdp.eval(js_chat_text(cfg), timeout=30) or "")
        except TimeoutError:
            try:
                cdp.reconnect()
            except Exception:
                pass
            baseline = len(cdp.eval(js_chat_text(cfg), timeout=45) or "")
        ins = cdp.eval(js_focus(cfg))
        if not (ins and ins.get("ok")):
            dbg = cdp.eval(js_diagnose())
            dump = os.path.join(ROOT, "data", "copilot_auto_debug.json")
            os.makedirs(os.path.dirname(dump), exist_ok=True)
            with open(dump, "w", encoding="utf-8") as f:
                json.dump(dbg, f, ensure_ascii=False, indent=1)
            return {"ok": False, "phase": "input_not_found",
                    "error": "채팅 입력창을 찾지 못함",
                    "hint": "data\\copilot_auto_debug.json 과 화면 스크린샷을 Claude에게 보여주면 선택자를 맞춰줄 수 있습니다"}
        # 주입: CDP Input.insertText(IME/붙여넣기 수준 — 리치 에디터가 정상 수신) → 실패 시 예비 경로
        cdp.call("Input.insertText", {"text": prompt})
        time.sleep(0.4)
        got_in = cdp.eval(js_editor_text()) or ""
        if prompt.strip()[:15] not in got_in:
            cdp.eval(js_insert_fallback(prompt))
            time.sleep(0.4)
        time.sleep(0.5)
        sent = cdp.eval(js_click_send(cfg))
        if not (sent and sent.get("ok")):
            press_enter(cdp)                   # 전송 버튼이 없으면 Enter
        # 전송 확인 — 클릭이 '중지' 버튼에 먹혔으면(앞 답 생성 중) 프롬프트가 입력창에 그대로 남는다.
        # 그때는 생성이 멎기를 기다렸다 한 번만 다시 보낸다(안 보내면 응답 대기가 통째로 시간 초과).
        resent = False
        time.sleep(1.0)
        try:
            left = cdp.eval(js_editor_text()) or ""
        except (TimeoutError, RuntimeError, OSError):
            left = ""
        head15 = prompt.strip()[:15]
        if head15 and head15 in left and len(left) >= len(prompt.strip()) * 0.8:
            wait_idle(cdp, secs=30)
            sent = cdp.eval(js_click_send(cfg))
            if not (sent and sent.get("ok")):
                press_enter(cdp)
            resent = True

        # 에코 앵커: 프롬프트 마지막 줄을 채팅 텍스트에서 찾아 그 뒤를 응답으로 본다.
        # 문자 오프셋(baseline)만 쓰면 앞부분 재렌더(인사말 소멸·상대시각 갱신)에 슬라이스가 밀린다
        # 앵커는 '충분히 긴' 프롬프트 꼬리여야 한다 — "]" 한 글자면 에코 중간에 걸려 응답이 잘린다
        anchor = build_anchor(prompt)

        # 전송 직후 baseline 을 한 번 다시 잰다 — 새 채팅의 인사말·추천 카드는 첫 메시지를
        # 보내는 순간 DOM 에서 사라진다. innerText 가 append-only 가 아니라는 뜻이라,
        # 전송 전 baseline 을 그대로 쓰면 응답 앞부분(여는 '{' 포함)이 잘려 나간다.
        time.sleep(1.0)
        try:
            base = min(baseline, len(cdp.eval(js_chat_text(cfg), timeout=30) or ""))
        except (TimeoutError, OSError):
            base = 0                # 못 재면 자르지 않는다 — 전문 폴백이 안전하다

        # 응답 대기: 프롬프트 전송 이후 '새로 늘어난' 텍스트가 N회 연속 동일하면 완료
        deadline = time.time() + cfg["replyTimeoutSec"]
        how = "anchor"
        last, stable = None, 0
        while time.time() < deadline:
            time.sleep(cfg["pollSec"])
            try:
                txt = cdp.eval(js_chat_text(cfg), timeout=30) or ""
            except TimeoutError:
                # 대형 DOM innerText가 렌더러를 오래 점유한 경우 — 연결 재수립 후 계속 대기
                try:
                    cdp.reconnect()
                except Exception:
                    pass
                continue
            new, how = pick_reply(txt, base, anchor)
            if has_pledge(new, prompt, anchor, how):
                # 조기 완료: 서약([[전송끝]])은 답의 맨 마지막 줄이므로 보이는 순간 생성이 끝난
                # 것이다 — stablePolls 를 기다리지 않는다(그래서 stablePolls 를 넉넉히 잡아도
                # 평소 왕복이 느려지지 않는다). 한 번만 더 읽어 렌더 꼬리(각주 등)를 담는다.
                time.sleep(1.0)
                try:
                    txt2 = cdp.eval(js_chat_text(cfg), timeout=30) or ""
                    new2, how2 = pick_reply(txt2, base, anchor)
                    if has_pledge(new2, prompt, anchor, how2):
                        new, how = new2, how2
                except (TimeoutError, OSError, RuntimeError):
                    pass
                return _reply_result(strip_echo(new, prompt, anchor, how), note_model, how, True,
                                     waited, resent)
            if new.strip() and new == last:
                stable += 1
                if stable >= cfg["stablePolls"]:
                    # 어떤 경로로 회수했는지 남긴다 — fulltext 가 잦으면 앵커가 깨진 것이다
                    return _reply_result(strip_echo(new, prompt, anchor, how), note_model, how, False,
                                         waited, resent)
            else:
                stable = 0
            last = new
        return {"ok": False, "phase": "no_reply", "error": "응답 시간 초과",
                "reply": (last or "").strip(), "sentinel": False,
                "hint": "Copilot 창이 응답을 생성 중인지 확인 — 반복되면 화면 스크린샷을 Claude에게"}


def _reply_result(reply, note_model, how, sentinel, waited=0, resent=False):
    """회수 결과 dict — cut(생성 중단 문구가 꼬리에 있음)·waited(앞 답 생성 대기 초)·resent(전송 재클릭)
    를 함께 남겨 호출자가 잘린 답을 복구·부분 재시도할 수 있게 한다."""
    reply = (reply or "").strip()
    out = {"ok": True, "phase": "replied", "reply": reply, "model": note_model, "pick": how,
           "sentinel": bool(sentinel), "cut": is_cut_reply(reply)}
    if waited:
        out["waited"] = waited
    if resent:
        out["resent"] = True
    return out


# ── 분할 전송 (보완툴 AutoSend 이식) ──────────────────────────────────────
def _wait_rest(cdp, cfg, prompt, secs=300):
    """서약이 안 보인다 = 아직 쓰는 중일 수 있다 — **아무것도 보내지 않고** 같은 탭을
    다시 읽으며 서약이 나올 때까지 기다린다. 앵커(이번 프롬프트 꼬리)를 못 찾으면 None
    (이번 답의 시작점을 모르면 옛 서약을 오인할 수 있다). 60초째 그대로면 '끝났는데 서약만
    빠뜨린 답' 으로 보고 그 텍스트를 돌려준다."""
    anchor = build_anchor(prompt)
    if not anchor:
        return None
    deadline = time.time() + secs
    last, quiet = None, 0
    while time.time() < deadline:
        time.sleep(5)
        try:
            txt = cdp.eval(js_chat_text(cfg), timeout=30) or ""
        except TimeoutError:
            try:
                cdp.reconnect()
            except Exception:
                pass
            continue
        except (OSError, RuntimeError):
            continue                     # 대형 DOM 평가 지연은 다음 폴에
        reply, how = pick_reply(txt, 0, anchor)
        if how != "anchor":
            return None
        if has_pledge(reply, prompt, anchor, how):
            return strip_echo(reply, prompt, anchor, how).strip()
        quiet = quiet + 1 if reply == last else 0
        last = reply
        if quiet >= 12:                  # 60초째 그대로 = 끝났는데 서약만 빠뜨린 답
            return strip_echo(reply, prompt, anchor, how).strip() or None
    return strip_echo(last or "", prompt, anchor, "anchor").strip() or None


def _run_parts(cdp, cfg, parts, fresh):
    """같은 CDP·같은 채팅에서 조각을 차례로 보낸다 — 조각별 _roundtrip_once, 사다리 없음.
    조각마다 서약을 확인하고, 없으면 _wait_rest 로 기다린 뒤에만 다음 조각을 보낸다."""
    total = len(parts)
    if fresh:
        try:
            new_chat(cdp, cfg)
        except Exception:
            pass
    res = {"ok": False, "phase": "error", "error": "왕복 시작 실패"}
    for i, part in enumerate(parts, 1):
        res = _roundtrip_once(cdp, cfg, part)
        if not res.get("ok"):
            res["error"] = f"나눔 {i}/{total}: " + str(res.get("error") or "왕복 실패")
            return res
        reply = res.get("reply") or ""
        if not res.get("sentinel"):
            more = _wait_rest(cdp, cfg, part)
            if more:
                reply = more
                res["reply"] = more
                res["sentinel"] = SENTINEL in more      # _wait_rest 는 에코를 걷어낸 답만 돌려준다
            if not res.get("sentinel"):
                if not reply.strip():
                    return {"ok": False, "phase": "no_reply",
                            "error": f"나눔 {i}/{total}: 응답을 받지 못했습니다",
                            "hint": "Copilot 창에서 생성이 멈췄는지 확인하세요"}
                if more is None:
                    # 관찰이 불가능했다 — 생성 중일 수 있으니 넉넉히 기다린 뒤 진행
                    # (생성 중에 다음을 보내면 전송 버튼이 '중지'가 되어 답을 끊는다)
                    time.sleep(30)
                res["note"] = f"나눔 {i}/{total}: 서약 없이 생성 정지 확인 후 진행"
        if is_error_reply(reply):
            # 중간 조각의 일시 오류도 실패다 — 그 조각을 '받지 못한' 채 이어 가면 마지막
            # 답이 반쪽 자료로 만들어진다. 스테이지 전체를 새 채팅에서 다시 보낸다(호출자).
            return {"ok": False, "phase": "copilot_error", "reply": reply,
                    "error": f"나눔 {i}/{total}: Copilot 일시 오류 응답", "hint": reply[:80]}
        if i < total and "받았습니다" not in reply and len(reply) > 400:
            # 중간 조각에 확인 문구 대신 긴 답이 왔다 = 자료를 다 받기 전에 분석을 시작했을 수 있다.
            # 마지막 답이 앞 조각만으로 만들어질 위험 — 실패는 아니므로 표식만 남긴다(호출자 로그).
            res["note"] = f"나눔 {i}/{total}: 확인 문구 없이 긴 답({len(reply)}자) — 조기 분석 가능성"
    res["parts"] = total
    return res


def run_roundtrip_split(cfg, prompt, fresh=False):
    """--send 의 기본 경로. 한 조각이면 서약 지시를 덧붙여 기존 run_roundtrip(재시도 사다리
    유지). 여러 조각이면 같은 채팅에 차례로 보내고, 실패하면 새 채팅에서 전체를 1회 재시도.
    결과 dict 형식은 run_roundtrip 과 같고 parts(조각 수)만 더한다."""
    parts = make_parts(prompt, reserve=len(PLEDGE_TAIL))
    if len(parts) == 1:
        res = run_roundtrip(cfg, prompt + PLEDGE_TAIL, fresh=fresh)
        res["parts"] = 1
        return res
    how = ensure_edge(cfg)
    if how is None:
        return {"ok": False, "phase": "edge_not_found" if not find_edge() else "launch_failed",
                "error": "Edge 실행 실패", "parts": len(parts),
                "hint": "Edge 설치 여부 확인 · 보안 정책이 디버그 포트를 막는 환경이면 클립보드(수동) 방식 사용"}
    res = {"ok": False, "phase": "error", "error": "왕복 시작 실패"}
    for attempt in (1, 2):
        ws_url = find_tab(cfg)
        if not ws_url:
            return {"ok": False, "phase": "launch_failed", "error": "Copilot 탭을 만들 수 없음",
                    "parts": len(parts),
                    "hint": "열린 Edge(자동 프로필) 창에서 직접 주소를 열어보세요: " + cfg["url"]}
        cdp = CDP(ws_url)
        try:
            res = _run_parts(cdp, cfg, parts, fresh=(fresh or attempt == 2))
        except Exception as e:
            res = {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {e}"}
        finally:
            cdp.close()
        if res.get("ok"):
            if attempt == 2:
                res["retry"] = "나눔 전송 실패 → 새 채팅에서 전체 재전송 성공"
            res["parts"] = len(parts)
            return res
        if attempt == 1 and res.get("phase") in ("login_required", "input_not_found"):
            break                        # 사람이 개입해야 하는 상태 — 재시도해도 같다
    res["parts"] = len(parts)
    res["retry"] = "나눔 전송 · 새 채팅 전체 재시도 모두 실패"
    return res


# ── 테스트 전용 스텁 ─────────────────────────────────────────────────────
# LM_COPILOT_STUB=<dir> 이면 --send 가 Edge 를 띄우지 않고 <dir> 의 JSON 파일을 응답으로
# 돌려준다. 회귀 시험 전용 — run.py 경로는 judge/refine/agentic/flow 가 자식 프로세스라
# in-process 모의 sender 가 닿지 않기 때문에 드라이버에 분기가 있어야 한다.
# 배포 환경에서는 이 변수를 두지 않는다. 산출물에는 phase "stub" 으로 흔적이 남는다.
# 파일 선택: 프롬프트의 출력 형식 예시에서 **가장 앞에 나오는** 키가 최상위 키다
# (taxonomy 는 {"models":[{"name","match"…}]} 라 "match" 도 품고, groups 는 "items" 를
# 품는다 — 먼저 나온 키를 고르면 바깥 키가 이긴다). 키가 없는 판정 이어짐 청크("계속입니다…")는
# 본문 형식(#번호 | 시각 | …)으로 알아본다. <dir>/stub_map.json ({"부분문자열": "파일명"}) 이
# 있으면 그것을 먼저 본다. 아무것도 안 맞으면 default.json.
STUB_KEYS = (
    ('"flows"', ("flow.json", "flows.json")),                      # flow.py
    ('"match"', ("agentic.json", "match.json")),                   # agentic.py
    ('"groups"', ("groups.json", "detail3.json")),                 # core/details 세부업무 병합
    ('"items"', ("refine.json", "items.json")),                    # refine.py
    ('"summary"', ("narrative.json", "summary.json")),             # judge 월별 내러티브
    ('"j":', ("judge_rows.json", "judge.json", "j.json")),         # judge 신호 판정
    ('"models"', ("judge_models.json", "models.json")),            # judge 체계 수립·통합
)
STUB_BODY_PATTERNS = (
    (re.compile(r"^#\d+ \| \d{4}-\d{2}-\d{2}", re.M), ("judge_rows.json", "judge.json", "j.json")),
)


def stub_candidates(prompt):
    """프롬프트 → 스텁 파일 후보 이름 목록(우선순위 순)."""
    hits = [(prompt.find(k), k, names) for k, names in STUB_KEYS if k in prompt]
    cands = []
    if hits:
        cands.extend(min(hits)[2])
    else:
        for pat, names in STUB_BODY_PATTERNS:
            if pat.search(prompt):
                cands.extend(names)
                break
    cands.append("default.json")
    return cands


def stub_dir():
    d = (os.environ.get("LM_COPILOT_STUB") or "").strip()
    return d if d and os.path.isdir(d) else ""


def run_stub(cfg, prompt, fresh=False, sdir=None):
    """스텁 응답 — 프롬프트 키로 고른 파일 내용 + 서약. 파일이 없으면 실패(빈 스텁 = 실패 경로)."""
    sdir = sdir or stub_dir()
    prompt = str(prompt or "")
    parts = len(make_parts(prompt, reserve=len(PLEDGE_TAIL)))
    if not sdir:
        return {"ok": False, "phase": "stub", "error": "LM_COPILOT_STUB 폴더 없음", "parts": parts}
    cands = []
    try:
        with open(os.path.join(sdir, "stub_map.json"), encoding="utf-8-sig") as f:
            for k, v in (json.load(f) or {}).items():
                if isinstance(k, str) and isinstance(v, str) and k in prompt:
                    cands.append(v)
    except (OSError, ValueError, AttributeError):
        pass
    cands.extend(stub_candidates(prompt))
    for name in cands:
        p = os.path.join(sdir, name)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    body = f.read().strip()
            except OSError:
                continue
            try:                         # 기록: 어떤 프롬프트가 어느 파일로 답해졌는지
                with open(os.path.join(sdir, "_stub_log.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "file": name,
                                        "chars": len(prompt), "parts": parts, "fresh": bool(fresh),
                                        "head": prompt[:60]}, ensure_ascii=False) + "\n")
            except OSError:
                pass
            return {"ok": True, "phase": "stub", "reply": body + "\n" + SENTINEL,
                    "model": "stub", "stub_file": name, "parts": parts, "sentinel": True}
    return {"ok": False, "phase": "stub", "error": "스텁 응답 파일 없음",
            "hint": f"{sdir} 에 {', '.join(cands[:3])} 중 하나를 두세요", "parts": parts}


def run_probe(cfg):
    how = ensure_edge(cfg)
    if how is None:
        return {"ok": False, "phase": "edge_not_found", "error": "Edge 실행 실패"}
    ws_url = find_tab(cfg)
    if not ws_url:
        return {"ok": False, "phase": "launch_failed", "error": "탭 생성 실패"}
    cdp = CDP(ws_url)
    try:
        time.sleep(1.5)
        state = cdp.eval(js_state())
        if login_required(state):
            return {"ok": False, "phase": "login_required",
                    "error": "로그인 필요 (최초 1회)",
                    "hint": "열린 Edge 창에서 회사 계정으로 로그인해 두세요"}
        return {"ok": True, "phase": "ready", "url": (state or {}).get("url", "")}
    finally:
        cdp.close()


def run_diagnose(cfg):
    how = ensure_edge(cfg)
    if how is None:
        return {"ok": False, "phase": "edge_not_found"}
    ws_url = find_tab(cfg)
    cdp = CDP(ws_url)
    try:
        time.sleep(2)
        dbg = cdp.eval(js_diagnose())
        dump = os.path.join(ROOT, "data", "copilot_auto_debug.json")
        with open(dump, "w", encoding="utf-8") as f:
            json.dump(dbg, f, ensure_ascii=False, indent=1)
        return {"ok": True, "phase": "ready", "debug_file": dump,
                "editors": len((dbg or {}).get("editors", [])),
                "buttons": len((dbg or {}).get("buttons", []))}
    finally:
        cdp.close()


def run_diagnose_model(cfg):
    """모델 선택 메뉴를 실제로 열고 그 안의 항목을 그대로 덤프한다 —
    Copilot UI가 바뀔 때 추측하지 않고 눈으로 확인하기 위한 진단."""
    how = ensure_edge(cfg)
    if how is None:
        return {"ok": False, "phase": "edge_not_found"}
    cdp = CDP(find_tab(cfg))
    try:
        time.sleep(2)
        opened = cdp.eval(js_pick_model(cfg.get("model") or "GPT")) or {}
        time.sleep(1.2)
        dump = cdp.eval(r"""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const out=[];
  document.querySelectorAll("[role='menu'],[role='listbox'],[role='dialog'],ul,div")
   .forEach(c=>{ if(!vis(c))return; const r=c.getBoundingClientRect(); if(r.width>460||r.height>560)return;
     const kids=[...c.querySelectorAll("[role='menuitem'],[role='menuitemradio'],[role='option'],li,button")]
       .filter(vis).map(e=>({t:(e.innerText||"").trim().slice(0,40),
                             role:e.getAttribute("role")||e.tagName,
                             pop:e.getAttribute("aria-haspopup")||"",
                             exp:e.getAttribute("aria-expanded")||""}))
       .filter(x=>x.t);
     if(kids.length>=2&&kids.length<=15)out.push({box:c.getAttribute("role")||c.tagName,items:kids});});
  return {menus:out.slice(0,4)};
})()""") or {}
        return {"ok": True, "phase": "ready", "opened": opened, "menu": dump}
    finally:
        cdp.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", help="프롬프트 파일(UTF-8) 전송 후 응답 회수")
    ap.add_argument("--out", help="응답 저장 파일 (기본: stdout JSON에 포함)")
    ap.add_argument("--fresh", action="store_true",
                    help="새 채팅에서 시작 (앞선 대화 문맥 오염 방지 — 판정용)")
    ap.add_argument("--no-split", action="store_true",
                    help="긴 프롬프트를 나누지 않고 한 번에 주입 (옛 동작 — 서약 지시도 붙이지 않음)")
    ap.add_argument("--probe", action="store_true", help="상태 확인만")
    ap.add_argument("--diagnose", action="store_true", help="입력창/버튼 후보 덤프")
    ap.add_argument("--diagnose-model", action="store_true", help="모델 선택 메뉴를 열어 항목 덤프")
    ap.add_argument("--url", help="대상 URL 덮어쓰기 (테스트용)")
    ap.add_argument("--port", type=int, help="디버그 포트 덮어쓰기")
    a = ap.parse_args()
    cfg = load_cfg()
    if a.url:
        cfg["url"] = a.url
    if a.port:
        cfg["port"] = a.port
    try:
        if a.probe:
            res = run_probe(cfg)
        elif a.diagnose:
            res = run_diagnose(cfg)
        elif getattr(a, "diagnose_model", False):
            res = run_diagnose_model(cfg)
        elif a.send:
            with open(a.send, encoding="utf-8-sig") as f:
                prompt = f.read()
            if stub_dir():
                res = run_stub(cfg, prompt, fresh=bool(a.fresh))       # 테스트 전용 — Edge 미기동
            elif a.no_split:
                res = run_roundtrip(cfg, prompt, fresh=bool(a.fresh))
            else:
                res = run_roundtrip_split(cfg, prompt, fresh=bool(a.fresh))
            if a.out and res.get("reply"):
                with open(a.out, "w", encoding="utf-8") as f:
                    f.write(res["reply"])
        else:
            ap.print_help()
            return 2
    except Exception as e:
        res = {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {e}",
               "hint": "이 메시지를 Claude에게 보여주세요"}
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
