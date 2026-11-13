# -*- coding: utf-8 -*-
r"""
teamserver.py — 조직장 팀 서버 (AgentFinder32 · spec §7 · D15 · D16). 조직장 PC 에서 AgentFinder32-팀서버.bat 으로 켠다.

받는 것(팀원이 [공유] 탭에서 미리 보고 직접 고른 것만 — 자동으로 오는 것은 없다)
  · 개인 리포트(공유용 HTML) — 조직장만 이 PC 에서 열어 본다. 정해진 꼴(REPORT_TAGS — 링크·외부 자원·양식 없음)만 받는다.
  · 익명 팀 집계 기여분 — Agentic AI 전환 후보 이름·업무 유형과 기간의 달만. 이름·IP·시각은 남기지 않는다(파일 이름은 임의 id,
    파일 시각은 받은 달 1일). 조직장 화면은 기여분을 하나씩 보이지 않고 익명 집계만 보인다.

팀원(사내망) 경로 — 모두 JSON. 공유는 X-AF32-Join(참여 코드), 지우기·상태는 X-AF32-Token
  GET    /af32/hello                         {product, schema, server_id, org_label, transport, personalOverHttp,
                                              minGroupSize, minCellSize, serverPersonalDays, serverTeamDays}
  POST   /af32/share/personal                {owner_id, owner, function, period, report_html} → {ok, token, expires}
                                              (새로 보낼 때 팀원이 만든 토큰(32~128 hex)을 X-AF32-Token 으로 주면 그것을 쓴다 —
                                              답을 못 받아도 팀원이 지울 수 있게. 다시 보낼 때는 앞서 쓴 토큰을 X-AF32-Token 으로)
  POST   /af32/share/team                    {contribution_id, month, personal_also, needs[]} → {ok, token, expires}
                                              (X-AF32-Token 에 팀원이 만든 토큰을 주면 그것을 쓴다)
  DELETE /af32/share/personal/<owner_id>     · /af32/share/team/<contribution_id>
  GET    /af32/share/<part>/<id>             → {ok, part, id, received|month, expires}
조직장 경로 — 이 PC(127.0.0.1·::1)에서만(설정 team.remoteView 가 true 이고 HTTPS 로 켰을 때만 사내망에서도). 조직장 키로
  로그인(8시간) — /login(GET 화면 · POST 키) · /logout · / (개인 리포트 목록 + 익명 팀 집계) · /report/<owner_id> ·
  /api/summary · POST /admin/delete/personal/<owner_id>
오류: 400 bad_bundle · 401 bad_join/login · 403 token_mismatch · 413 too_big · 429 rate_limited · 404 그 밖.

저장(teamdata\ — 이 PC 의 설치 폴더 안)
  server.json        {product, schema, server_id(임의 32 hex — 팀원 영수증이 이 서버를 알아본다), created, org_label,
                      personalOverHttp, personalOverHttp_decided, port, key{alg, iter, salt, hash}(조직장 키의 PBKDF2 — 키 원문은
                      남기지 않는다), key_changed, join, join_changed}
  접속정보.txt        주소와 참여 코드 두 줄(팀원에게 알려 줄 것)
  personal\<owner_id>.json · team\<contribution_id>.json · summary.json(하루 한 번 계산한 익명 집계) · tls\cert.pem+key.pem(있으면 HTTPS)
보관기한: 개인 리포트 retention.serverPersonalDays(≤90일, 받은 날부터) · 기여분 retention.serverTeamDays(≤180일, 받은 달 1일부터).
켤 때·한 시간마다·이 파일의 명령마다 지우고(purge), 처음 켤 때 만든 매일 정리 예약 작업(내 사용자 작업 — purge_task_name ·
pythonw 로 --purge 만 돈다)이 서버가 꺼져 있어도 하루 한 번 지운다. 다시 켤 때 그 작업이 없어졌으면 다시 만든다.
AF32_NO_TASK=1 이면 작업 스케줄러를 건드리지 않는다. [4 서버 자료 모두 삭제]가 자료를 다 지운 뒤 그 작업도 지운다.

  python teamserver.py                    서버 시작(처음이면 조직 이름·HTTP 개인 리포트 받기 여부를 묻고 조직장 키를 한 번 보여 준다)
  python teamserver.py --port 9400        이번 포트(LoadMonitor 포트는 받지 않는다)
  python teamserver.py --new-key          조직장 키 다시 만들기(한 번만 보여 준다 · 열려 있는 로그인은 끊긴다 · 받은 개인 리포트를
                                          지울지 묻는다 — 기본은 지운다)
  python teamserver.py --new-join         참여 코드 바꾸기(접속정보.txt 도 다시 쓴다)
  python teamserver.py --delete-all [--yes]   서버 자료 모두 삭제(teamdata\ 통째 — 서버가 꺼져 있을 때만 · 매일 정리 작업도 지운다)
  python teamserver.py --purge            보관기한이 지난 자료만 지운다(매일 정리 작업이 부른다)
"""
import collections
import hashlib
import hmac
import html
import http.client
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(ROOT, "core"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)        # 동봉 파이썬(._pth)은 스크립트 폴더를 sys.path 에 넣지 않는다
import afcfg  # noqa: E402
import lmname  # noqa: E402
import privacy  # noqa: E402
import team_summary  # noqa: E402
import teamaddr  # noqa: E402

TEAMDATA = os.path.join(ROOT, "teamdata")
SERVER_FILE = "server.json"
INFO_FILE = "접속정보.txt"
PID_FILE = "server.pid"
PERSONAL_DIR = "personal"
TEAM_DIR = team_summary.TEAM_DIR
TLS_DIR = "tls"
KNOWN_ENTRIES = {SERVER_FILE, INFO_FILE, PID_FILE, PERSONAL_DIR, TEAM_DIR, TLS_DIR, team_summary.SUMMARY_FILE}
P = lmname.SHARE_PREFIX                # /af32

MAX_BODY = 5 * 1024 * 1024             # 요청 1건 상한 5MB
DRAIN_MAX = 8 * 1024 * 1024            # 상한을 넘은 본문은 이만큼까지만 읽어 버리고 끊는다
SESSION_SEC = 8 * 3600
LOGIN_PER_MIN = 5
JOIN_FAIL_PER_MIN = 10
PBKDF2_ITER = 200_000
KEY_GROUPS = 5                          # 조직장 키 4자 × 5묶음(100비트)
PURGE_EVERY_SEC = 3600
NEEDS_MAX = 30                          # 익명 기여분 하나의 후보 수 상한
NEED_NAME_MAX = 200                     # 후보 이름 글자 수 상한
NEED_TYPE_MAX = 40
COOKIE = "af32_head"
ALPHABET = teamaddr.JOIN_ALPHABET
PURGE_TASK_TIME = "12:40"               # 매일 정리 예약 작업(조직장 PC) 시각
NO_WIN = 0x08000000
_ID_RX = re.compile(r"^[0-9a-f]{32}$")
_SID_RX = _ID_RX                         # server_id — 임의 32 hex
_TOKEN_RX = re.compile(r"^[0-9a-f]{32,128}$")   # 팀원이 만든 토큰(X-AF32-Token)
_MONTH_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_PERIOD_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])~\d{4}-(0[1-9]|1[0-2])$")
_MAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE_RX = re.compile(r"\d{2,4}[-.\s]\d{3,4}[-.\s]\d{4}")

PAGE_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'self'; base-uri 'none'; "
            "frame-ancestors 'none'")
# 팀원이 보낸 개인 리포트 — 스크립트·외부 자원·폼 없이 origin 을 떼어 보여 준다
REPORT_CSP = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; "
              "form-action 'none'; frame-ancestors 'none'")
# 받는 개인 리포트의 꼴(report_out 공유본이 쓰는 것만) — 링크·외부 자원·양식·프레임·스크립트·style 속성은 받지 않는다
REPORT_TAGS = frozenset(("html", "head", "meta", "title", "style", "body", "div", "span", "p", "h1", "h2", "h3", "b",
                         "strong", "i", "em", "small", "ol", "ul", "li", "table", "thead", "tbody", "tr", "th", "td", "br",
                         "hr"))
REPORT_ATTRS = frozenset(("class", "lang", "colspan", "rowspan"))
REPORT_META_NAMES = frozenset(("viewport", "referrer", "product", "af32-variant", "af32-tag"))
REPORT_VOID = frozenset(("meta", "br", "hr"))               # '<x/>' 꼴로 써도 되는 것(닫는 태그가 없는 요소)
# <style> 안 — 외부 자원을 부르는 CSS 와 '<'(브라우저가 거기서 style 을 끝내고 뒤를 태그로 읽을 수 있다)는 받지 않는다
_CSS_BAD = re.compile(r"<|url\s*\(|@import|@font-face|expression\s*\(|\\|behavior\s*:|-moz-binding|image-set\s*\(", re.I)
_ATTR_VAL_OK = re.compile(r"^[\w\- .]{0,120}$")
_DOCTYPE_RX = re.compile(r"\A\s*<!doctype\s+html\s*>", re.I)
# 글 안의 '<' 는 받는 태그의 시작·끝이어야 하고(본문 글자는 &lt; 로 온다) 그 태그는 다음 '<' 전에 '>' 로 닫혀야 한다 — HTML 읽개
# (html.parser)가 글로 넘기거나 읽지 않고 남긴 곳에 브라우저가 태그로 읽을 것이 숨지 않게, 읽개와 따로 먼저 본다
_RAW_LT_BAD = re.compile(r"<(?!/?(?:" + "|".join(sorted(REPORT_TAGS, key=len, reverse=True)) + r")(?=[\s/>]))", re.I)
_RAW_UNCLOSED = re.compile(r"<[^<>]*(?:<|\Z)")
PURPOSE = ("이 서버는 팀원이 직접 골라 보낸 Agentic AI 전환 후보만 받습니다. 사람을 평가하거나 근태·업무량을 보는 데 "
           "쓰지 않습니다.")
NO_PRESSURE = "공유하지 않아도 불이익이 없고, 조직장은 공유를 요구하거나 권하지 않습니다."

# 매일 정리 예약 작업은 pythonw.exe 로 돈다 — 창도 표준 출력도 없다(sys.stdout 이 None). 그때는 감싸지 않는다(print 는 조용히 넘어간다)
if __name__ == "__main__" and getattr(sys.stdout, "buffer", None) is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프=utf-8


def esc(v):
    """남이 보낸 값을 화면에 낼 때 반드시 거친다 — 저장형 XSS 방지"""
    return html.escape(str("" if v is None else v), quote=True)


def _today():
    return date.today()


def _ymd(d):
    return d.isoformat()


def _say(msg):
    print(f"[team] {msg}", flush=True)


# ── 파일 ──────────────────────────────────────────────────────────────────────
def _write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


def _is_link(p):
    """정션·심볼릭 링크인가(lstat 못 하면 참 — 모르면 들어가지 않는다)."""
    try:
        st = os.lstat(p)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool((getattr(st, "st_file_attributes", 0) or 0) & 0x400)


def _rm_file(p):
    for i in range(3):
        try:
            os.remove(p)
        except FileNotFoundError:
            return True
        except PermissionError:
            try:
                os.chmod(p, stat.S_IWRITE)
                os.remove(p)
            except OSError:
                pass
        except OSError:
            pass
        if not os.path.lexists(p):
            return True
        time.sleep(0.2 * (i + 1))
    return False


def _unlink_dir_link(p):
    """정션·폴더 링크 자체만 떼어 낸다(가리키는 곳은 건드리지 않는다) → 떼었나."""
    try:
        os.rmdir(p)                 # 정션·폴더 심볼릭 링크 — 링크만 지운다
        return True
    except OSError:
        pass
    try:
        os.remove(p)                # 파일 심볼릭 링크
        return True
    except OSError:
        return not os.path.lexists(p)


def rm_tree(path):
    r"""폴더를 통째로 지운다 — 정션·링크는 들어가지 않고 링크 자체만 떼어 낸다. → (지운 파일 수, 못 지운 상대 경로들).
    위에서부터 내려가며(topdown) 링크 폴더를 걸러 낸 뒤에만 들어간다 — 파이썬 3.11 의 os.walk 는 정션을 링크로 보지 않아
    아래부터(topdown=False) 돌면 정션 너머(teamdata 밖)의 파일까지 지운다."""
    n, left = 0, []
    if not os.path.lexists(path):
        return 0, []
    if _is_link(path):
        if not _unlink_dir_link(path):
            left.append(os.path.basename(path))
        return 0, left
    seen = []
    for cur, dirs, files in os.walk(path, topdown=True, onerror=lambda _e: None):
        keep = []
        for d in dirs:
            dp = os.path.join(cur, d)
            if _is_link(dp):
                if not _unlink_dir_link(dp):
                    left.append(os.path.relpath(dp, path))
            else:
                keep.append(d)
        dirs[:] = keep              # 링크 폴더에는 들어가지 않는다
        seen.append(cur)
        for f in files:
            fp = os.path.join(cur, f)
            if _rm_file(fp):        # 파일 심볼릭 링크는 링크만 지운다
                n += 1
            else:
                left.append(os.path.relpath(fp, path))
    for d in sorted(seen, key=len, reverse=True):
        try:
            os.rmdir(d)
        except OSError:
            if d != path and os.path.lexists(d):
                left.append(os.path.relpath(d, path))
    return n, left


# ── 조직장 키·참여 코드 ─────────────────────────────────────────────────────────
def new_secret(groups):
    s = "".join(secrets.choice(ALPHABET) for _ in range(4 * groups))
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def norm_key(v):
    return unicodedata.normalize("NFKC", str(v or "")).upper().replace("-", "").replace(" ", "").strip()


def hash_key(key, *, salt=None, iterations=PBKDF2_ITER):
    """조직장 키 → {"alg","iter","salt","hash"} (PBKDF2-HMAC-SHA256). 키 원문은 어디에도 남기지 않는다."""
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", norm_key(key).encode("utf-8"), bytes.fromhex(salt), int(iterations))
    return {"alg": "pbkdf2_sha256", "iter": int(iterations), "salt": salt, "hash": h.hex()}


def verify_key(key, rec):
    if not isinstance(rec, dict) or rec.get("alg") != "pbkdf2_sha256":
        return False
    try:
        h = hashlib.pbkdf2_hmac("sha256", norm_key(key).encode("utf-8"), bytes.fromhex(str(rec.get("salt"))),
                                int(rec.get("iter")))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(h.hex(), str(rec.get("hash") or ""))


def _token_hash(tok):
    return hashlib.sha256(str(tok or "").encode("utf-8")).hexdigest()


def _clean(v, cap):
    """남이 보낸 짧은 글 — NFKC · 제어/서식 문자 제거 · 공백 접기. cap 글자를 넘으면 None."""
    s = unicodedata.normalize("NFKC", str(v if v is not None else ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    s = " ".join(s.split())
    return s if len(s) <= cap else None


def _month_start(d):
    return datetime(d.year, d.month, 1)


def coarse_times(path, ts):
    """파일·폴더의 시각(만든·바꾼·읽은)을 모두 ts 로 — 익명 기여분이 언제 왔는지(달보다 자세히) 남기지 않는다.
    윈도는 만든 시각(st_ctime)도 남으므로 SetFileTime 으로 함께 바꾼다(실패하면 바꾼·읽은 시각만)."""
    try:
        os.utime(path, (ts, ts))
    except OSError:
        pass
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.HANDLE)
        k32.SetFileTime.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        # FILE_WRITE_ATTRIBUTES · 모두 공유 · OPEN_EXISTING · FILE_FLAG_BACKUP_SEMANTICS(폴더도)
        h = k32.CreateFileW(str(path), 0x100, 7, None, 3, 0x02000000, None)
        if not h or h == ctypes.c_void_p(-1).value:
            return
        try:
            ft = int((ts + 11644473600) * 10_000_000)
            f = wintypes.FILETIME(ft & 0xFFFFFFFF, ft >> 32)
            k32.SetFileTime(h, ctypes.byref(f), ctypes.byref(f), ctypes.byref(f))
        finally:
            k32.CloseHandle(h)
    except (AttributeError, OSError, ValueError):
        pass


# ── 받는 개인 리포트의 꼴 ────────────────────────────────────────────────────────
class _ReportShape(HTMLParser):
    """개인 리포트 HTML 이 정해진 꼴(REPORT_TAGS·REPORT_ATTRS)만 쓰는가 — 처음 어긋난 곳을 .bad 에."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bad = ""
        self._style = False
        self._css = []

    def _no(self, why):
        if not self.bad:
            self.bad = why

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs)
        if tag == "style":
            self._style = True

    def handle_startendtag(self, tag, attrs):
        if tag not in REPORT_VOID:
            return self._no(f"selfclose {tag[:20]}")     # 브라우저는 '<style/>'·'<div/>' 를 여는 태그로 읽는다 — 읽개와 어긋난다
        return self._tag(tag, attrs)

    @property
    def open_style(self):
        """<style> 이 닫히지 않은 채 끝났나(그 뒤는 읽개가 보지 못했다)."""
        return self._style

    def css_done(self):
        """모은 <style> 글을 본다(조각으로 나뉘어 와도 이어서)."""
        css, self._css = "".join(self._css), []
        if _CSS_BAD.search(css):
            self._no("style")

    def _tag(self, tag, attrs):
        if tag not in REPORT_TAGS:
            return self._no(f"tag {tag[:20]}")
        names = [k for k, _v in attrs]
        if len(set(names)) != len(names):
            return self._no("attr twice")
        d = {k: str(v or "") for k, v in attrs}
        if tag == "meta":
            if set(d) == {"charset"} and d["charset"].lower() == "utf-8":
                return None
            if set(d) == {"name", "content"} and d["name"].lower() in REPORT_META_NAMES:
                return None
            if set(d) == {"http-equiv", "content"} and d["http-equiv"].lower() == "content-security-policy" \
                    and not _CSS_BAD.search(d["content"]):
                return None
            return self._no("meta")
        for k, v in d.items():
            if k not in REPORT_ATTRS:
                return self._no(f"attr {k[:20]}")
            if not _ATTR_VAL_OK.match(v):
                return self._no(f"value {k}")
        return None

    def handle_endtag(self, tag):
        if tag == "style":
            self._style = False
            self.css_done()

    def handle_data(self, data):
        if self._style:
            self._css.append(data)

    def handle_comment(self, data):
        self._no("comment")

    def handle_decl(self, decl):
        if decl.strip().lower() != "doctype html":
            self._no("decl")

    def handle_pi(self, data):
        self._no("pi")

    def unknown_decl(self, data):
        self._no("decl")


def report_html_problem(text):
    """받을 수 없는 개인 리포트면 까닭(짧은 영문), 아니면 None — 링크(<a>·<link>·<base>)·양식·프레임·이미지·스크립트·style 속성·
    외부 자원을 부르는 CSS(url(·@import)·주석이 있으면 받지 않는다(남이 보낸 HTML 이 조직장 화면에서 다른 곳을 부르지 않게).
    세 번 본다: ① 글 안의 모든 '<' 가 받는 태그의 시작·끝이고 '>' 로 닫히는가(맨 앞 <!doctype html> 하나는 된다) ② HTML 읽개로
    태그·속성·<style> ③ 읽개가 끝까지 읽었는가(html.parser 는 '</style>' 꼴이 아닌 끝 태그 뒤를 읽지 않고 남긴다 — 브라우저는
    '</style/>' 에서도 style 을 끝내고 뒤를 태그로 읽는다)."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if "<script" in text.lower():
        return "script"
    body = _DOCTYPE_RX.sub("", text, count=1)
    if _RAW_LT_BAD.search(body) or _RAW_UNCLOSED.search(body):
        return "markup"
    p = _ReportShape()
    try:
        p.feed(text)
        p.close()
        p.css_done()
    except Exception:  # noqa: BLE001 - 읽지 못하는 HTML 은 받지 않는다
        return "parse"
    if p.bad:
        return p.bad
    if p.open_style or getattr(p, "cdata_elem", None) or getattr(p, "rawdata", ""):
        return "unparsed"
    return None


# ── 서버 설정(teamdata\server.json) ────────────────────────────────────────────
def conf_path(teamdata=None):
    return os.path.join(teamdata or TEAMDATA, SERVER_FILE)


def load_conf(teamdata=None):
    d = _read_json(conf_path(teamdata))
    if not d or d.get("product") != lmname.PRODUCT or not isinstance(d.get("key"), dict):
        return None
    if not teamaddr.norm_join(d.get("join")):
        return None
    if not _SID_RX.match(str(d.get("server_id") or "")):
        d["server_id"] = secrets.token_hex(16)   # server_id 가 없던 server.json — 한 번 만들어 남긴다(팀원 영수증이 이 서버를 알아본다)
        try:
            save_conf(d, teamdata)
        except OSError:
            pass
    return d


def save_conf(conf, teamdata=None):
    _write_json(conf_path(teamdata), conf)


def address_for(port, tls, host=None):
    r"""팀원에게 알려 줄 주소 — 이 PC 의 IPv4(없으면 PC 이름). host 를 주면 그것(--bind 127.0.0.1 시험)."""
    if not host:
        ips = teamaddr.local_ipv4s()
        host = ips[0] if ips else (socket.gethostname() or "localhost").lower()
    return f"{'https' if tls else 'http'}://{host}:{port}"


def write_info(conf, teamdata=None, *, port=None, tls=None, host=None):
    r"""teamdata\접속정보.txt — 주소와 참여 코드 두 줄만."""
    td = teamdata or TEAMDATA
    tls = has_tls(td) if tls is None else tls
    p = os.path.join(td, INFO_FILE)
    addr = address_for(port or conf.get("port") or teamaddr.DEFAULT_PORT, tls, host)
    text = f"주소: {addr}\r\n참여 코드: {conf['join']}\r\n"
    os.makedirs(td, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)
    os.replace(tmp, p)
    return p


def has_tls(teamdata=None):
    td = os.path.join(teamdata or TEAMDATA, TLS_DIR)
    return os.path.isfile(os.path.join(td, "cert.pem")) and os.path.isfile(os.path.join(td, "key.pem"))


def tls_context(teamdata=None):
    td = os.path.join(teamdata or TEAMDATA, TLS_DIR)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.path.join(td, "cert.pem"), os.path.join(td, "key.pem"))
    return ctx


def legacy_teamdata(teamdata=None):
    """LoadMonitor 팀 서버가 남긴 사람별 폴더(member.json)가 있으면 그 이름들."""
    td = teamdata or TEAMDATA
    out = []
    try:
        for n in os.listdir(td):
            p = os.path.join(td, n)
            if n in KNOWN_ENTRIES or not os.path.isdir(p) or _is_link(p):
                continue
            if os.path.isfile(os.path.join(p, "member.json")):
                out.append(n)
    except OSError:
        pass
    return sorted(out)


# ── 보관기한 정리 ──────────────────────────────────────────────────────────────
def _now_dt(now):
    if now is None:
        return datetime.now()
    if isinstance(now, datetime):
        return now
    if isinstance(now, date):
        return datetime(now.year, now.month, now.day)
    return datetime.fromtimestamp(float(now))


def personal_expires(received, cfg):
    try:
        d = date.fromisoformat(str(received)[:10])
    except ValueError:
        return None
    return d + timedelta(days=int(afcfg.get(cfg, "retention.serverPersonalDays")))


def team_expires(stored_month_start, cfg):
    return stored_month_start.date() + timedelta(days=int(afcfg.get(cfg, "retention.serverTeamDays")))


def purge(teamdata_dir, cfg, *, now=None):
    r"""보관기한이 지난 개인 리포트·기여분을 지운다 → {"deleted","personal","team","errors"}.
    개인 리포트: 받은 날 + serverPersonalDays 가 오늘 이하면. 기여분: 받은 달 1일(파일 시각) + serverTeamDays 가 오늘 이하면.
    기여분을 지웠으면 오늘의 익명 집계는 숫자를 보이지 않는다(team_summary.invalidate)."""
    nowd = _now_dt(now)
    today = nowd.date()
    res = {"deleted": 0, "personal": 0, "team": 0, "errors": []}
    pdir = os.path.join(teamdata_dir, PERSONAL_DIR)
    tdir = os.path.join(teamdata_dir, TEAM_DIR)
    for d, part in ((pdir, "personal"), (tdir, "team")):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            fp = os.path.join(d, n)
            if not os.path.isfile(fp) or _is_link(fp):
                continue
            try:
                mt = os.path.getmtime(fp)
            except OSError:
                continue
            if n.endswith(".tmp"):
                expired = nowd.timestamp() - mt > 86400
            elif part == "personal":
                rec = _read_json(fp)
                exp = personal_expires((rec or {}).get("received"), cfg) if rec else None
                if exp is None:
                    exp = date.fromtimestamp(mt) + timedelta(days=int(afcfg.get(cfg, "retention.serverPersonalDays")))
                expired = today >= exp
            else:
                expired = today >= team_expires(datetime.fromtimestamp(mt), cfg)
            if not expired:
                continue
            if _rm_file(fp):
                res["deleted"] += 1
                if not n.endswith(".tmp"):
                    res[part] += 1
            else:
                res["errors"].append(f"{part}\\{n}")
    try:
        for n in os.listdir(teamdata_dir):
            fp = os.path.join(teamdata_dir, n)
            if n.endswith(".tmp") and os.path.isfile(fp) and nowd.timestamp() - os.path.getmtime(fp) > 86400:
                if _rm_file(fp):
                    res["deleted"] += 1
    except OSError:
        pass
    if res["team"]:
        team_summary.invalidate(teamdata_dir, today=today)
    return res


# ── 서버 상태 ──────────────────────────────────────────────────────────────────
class App:
    """한 서버의 상태 — 설정·세션·요청 제한. 처리기는 self.server.app 으로 닿는다."""

    def __init__(self, teamdata, cfg, *, tls=False, port=0):
        self.dir = teamdata
        self.cfg = cfg
        self.tls = bool(tls)
        self.port = int(port)
        self.lock = threading.RLock()
        self.sessions = {}
        self.login_hits = collections.defaultdict(collections.deque)
        self.join_fails = collections.defaultdict(collections.deque)
        self._conf = (None, None)

    @property
    def remote_view_wanted(self):
        return bool(afcfg.get(self.cfg, "team.remoteView"))

    @property
    def remote_view(self):
        """사내망에서 조직장 화면을 여나 — team.remoteView 이고 HTTPS 일 때만(HTTP 면 키·쿠키가 암호화 없이 오가므로 열지 않는다)."""
        return self.remote_view_wanted and self.tls

    def conf(self):
        """server.json — 바뀌면(--new-key·--new-join) 다시 읽는다(서버를 다시 켜지 않아도 된다)."""
        p = conf_path(self.dir)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            mt = None
        with self.lock:
            if self._conf[0] != mt or self._conf[1] is None:
                self._conf = (mt, load_conf(self.dir))
            return self._conf[1]

    def hello(self):
        c = self.conf() or {}
        g = afcfg.get
        return {"product": lmname.PRODUCT, "schema": lmname.SHARE_SCHEMA, "server_id": str(c.get("server_id") or ""),
                "org_label": c.get("org_label") or "",
                "transport": "https" if self.tls else "http",
                "personalOverHttp": bool(c.get("personalOverHttp") is True),
                "minGroupSize": team_summary.threshold(self.cfg), "minCellSize": team_summary.cell_min(self.cfg),
                "serverPersonalDays": int(g(self.cfg, "retention.serverPersonalDays")),
                "serverTeamDays": int(g(self.cfg, "retention.serverTeamDays"))}

    def _hit(self, table, ip, limit, *, count=True):
        """1분 창 안의 기록 수가 limit 이상이면 True(막는다). count 면 이번 것을 센다."""
        now = time.monotonic()
        with self.lock:
            if len(table) > 2000:
                for k in [k for k, q in table.items() if not q or now - q[-1] > 60]:
                    del table[k]
            q = table[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return True
            if count:
                q.append(now)
            return False

    def login_limited(self, ip):
        return self._hit(self.login_hits, ip, LOGIN_PER_MIN)

    def join_limited(self, ip):
        return self._hit(self.join_fails, ip, JOIN_FAIL_PER_MIN, count=False)

    def join_failed(self, ip):
        self._hit(self.join_fails, ip, 10 ** 6)

    def key_fp(self):
        c = self.conf() or {}
        return str((c.get("key") or {}).get("hash") or "")[:16]

    def new_session(self):
        sid = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            for k in [k for k, v in self.sessions.items() if v["exp"] < now]:
                del self.sessions[k]
            self.sessions[sid] = {"exp": now + SESSION_SEC, "kfp": self.key_fp(), "csrf": secrets.token_urlsafe(24)}
        return sid

    def session(self, sid):
        if not sid:
            return None
        with self.lock:
            s = self.sessions.get(sid)
            if not s:
                return None
            if s["exp"] < time.time() or not hmac.compare_digest(s["kfp"], self.key_fp()):
                self.sessions.pop(sid, None)
                return None
            return s

    def end_session(self, sid):
        with self.lock:
            self.sessions.pop(sid, None)


class ExclusiveServer(ThreadingHTTPServer):
    r"""배타 bind — 같은 포트를 쥔 다른 서버 위에 덧바인딩하지 않는다(윈도 SO_REUSEADDR 대신 SO_EXCLUSIVEADDRUSE)."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        ex = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if ex is not None:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, ex, 1)
            except OSError:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        pass                      # 끊긴 연결·TLS 실패를 콘솔에 쏟지 않는다(누가 접속했는지도 남기지 않는다)


def _loopback(ip):
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_loopback


# ── 화면 조각 ──────────────────────────────────────────────────────────────────
PAGE_STYLE = """<style>
body{font:14px/1.6 'Segoe UI','Malgun Gothic',sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#23282e;background:#fff}
h1{font-size:20px} h2{font-size:15px;margin:22px 0 8px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #e4e8ec;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#5a6169;font-weight:600;background:#f7f8fa}
.note{color:#6b727b;font-size:12px} .warn{color:#a15c00}
form.inline{display:inline;margin:0}
button,input[type=submit]{border:1px solid #c9cfd8;border-radius:6px;padding:4px 12px;background:#fff;cursor:pointer;font-size:13px}
input[type=password]{padding:6px 8px;border:1px solid #c9cfd8;border-radius:6px;width:260px;font-size:14px}
a{color:#1b5fae}
</style>"""


def page(title, body):
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title>{PAGE_STYLE}</head><body>{body}</body></html>")


def login_page(msg=""):
    return page(f"{lmname.PRODUCT} 팀 서버 — 조직장 로그인", (
        f"<h1>{esc(lmname.PRODUCT)} 팀 서버 — 조직장 로그인</h1>"
        f"<p class='note'>{esc(PURPOSE)}</p>"
        + (f"<p class='warn'>{esc(msg)}</p>" if msg else "")
        + "<form method='post' action='/login'><p><label>조직장 키 "
          "<input type='password' name='key' autocomplete='off' autofocus></label> "
          "<input type='submit' value='로그인'></p></form>"
          "<p class='note'>조직장 키는 서버를 처음 켤 때 한 번만 보여 줍니다. 잊었으면 AgentFinder32-팀서버.bat 의 "
          "[2 조직장 키 다시 만들기]로 새로 만듭니다.</p>"))


# ── 요청 처리 ──────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "AF32Team"
    sys_version = ""
    timeout = 30                    # 느린 연결이 일꾼을 붙잡지 않게

    def log_message(self, fmt, *a):
        pass                        # 접속 기록(IP·시각)을 남기지 않는다

    def setup(self):
        if isinstance(self.request, ssl.SSLSocket):
            self.request.settimeout(self.timeout)
            self.request.do_handshake()          # TLS 악수는 일꾼 스레드에서(받는 쪽을 붙잡지 않게)
        super().setup()

    @property
    def app(self):
        return self.server.app

    def _client_ip(self):
        return str(self.client_address[0])

    # 응답 ────────────────────────────────────────────────────────────────
    def _send(self, code, body, ctype, headers=()):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _err(self, code, error):
        self._json(code, {"ok": False, "error": error})

    def _html(self, code, text, headers=()):
        self._send(code, text, "text/html; charset=utf-8",
                   (("Content-Security-Policy", PAGE_CSP), ("X-Frame-Options", "DENY"),
                    ("X-DNS-Prefetch-Control", "off")) + tuple(headers))

    def _redirect(self, where, headers=()):
        self.send_response(303)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()

    def _drain(self):
        """읽지 않은 본문을 DRAIN_MAX 까지만 읽어 버린다 — 읽지 않고 답하면 보내는 쪽이 RST 로 끊겨 이 답조차 못 받는다."""
        try:
            left = min(max(int(self.headers.get("Content-Length") or 0), 0), DRAIN_MAX)
        except ValueError:
            left = 0
        try:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:
            pass
        self.close_connection = True

    def _refuse(self, code, error):
        """본문을 읽기 전에 거절 — 본문을 비우고 답한다."""
        if self.command in ("POST", "DELETE"):
            self._drain()
        self._err(code, error)

    def _body(self, cap=MAX_BODY):
        """본문 바이트 → bytes | None(이미 답함)."""
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        try:
            n = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            n = -1
        if te or n < 0:
            self._err(400, "bad_bundle")
            self.close_connection = True
            return None
        if n > cap:
            self._drain()
            self._err(413, "too_big")
            return None
        try:
            return self.rfile.read(n) if n else b""
        except OSError:
            self.close_connection = True
            return None

    def _json_body(self):
        b = self._body()
        if b is None:
            return None
        try:
            d = json.loads(b.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._err(400, "bad_bundle")
            return None
        if not isinstance(d, dict):
            self._err(400, "bad_bundle")
            return None
        return d

    def _path(self):
        return urllib.parse.urlsplit(self.path).path

    # 팀원 확인 ────────────────────────────────────────────────────────────
    def _join_ok(self):
        ip = self._client_ip()
        if self.app.join_limited(ip):
            self._refuse(429, "rate_limited")
            return False
        c = self.app.conf()
        got = teamaddr.norm_join(self.headers.get("X-AF32-Join") or "")
        if not c or not got or not hmac.compare_digest(got, c["join"]):
            self.app.join_failed(ip)
            self._refuse(401, "bad_join")
            return False
        return True

    def _token_ok(self, rec):
        tok = (self.headers.get("X-AF32-Token") or "").strip()
        return bool(tok) and hmac.compare_digest(_token_hash(tok), str(rec.get("token_sha256") or ""))

    def _new_token(self):
        """새 기록의 토큰 — 팀원이 X-AF32-Token 으로 준 것(32~128 hex)을 쓴다(답을 못 받아도 팀원 영수증으로 지울 수 있게).
        없으면 서버가 만든다(옛 판 팀원). 형식이 틀리면 None."""
        tok = (self.headers.get("X-AF32-Token") or "").strip()
        if not tok:
            return secrets.token_hex(24)
        return tok if _TOKEN_RX.match(tok) else None

    # 조직장 확인 ──────────────────────────────────────────────────────────
    def _head_allowed(self):
        if self.app.remote_view:
            return True
        if not _loopback(self._client_ip()):
            return False
        host = (self.headers.get("Host") or "").strip().lower()
        p = self.app.port
        return host in (f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}")

    def _sid(self):
        try:
            c = SimpleCookie(self.headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001 - 깨진 쿠키는 로그인 안 함으로 본다
            return ""
        m = c.get(COOKIE)
        return m.value if m else ""

    def _session(self):
        return self.app.session(self._sid())

    def _cookie(self, sid, max_age):
        attrs = f"{COOKIE}={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        return attrs + ("; Secure" if self.app.tls else "")

    def _same_origin(self):
        o = self.headers.get("Origin")
        if not o:
            return True
        want = f"{'https' if self.app.tls else 'http'}://{(self.headers.get('Host') or '').strip().lower()}"
        return o.strip().lower() == want

    # GET ───────────────────────────────────────────────────────────────
    def do_GET(self):
        path = self._path()
        if path == P + "/hello":
            return self._json(200, self.app.hello())
        m = re.fullmatch(re.escape(P) + r"/share/(personal|team)/([0-9a-f]{32})", path)
        if m:
            return self._share_status(m.group(1), m.group(2))
        if path in ("/", "/index.html", "/login", "/logout", "/api/summary") or path.startswith("/report/"):
            if not self._head_allowed():
                return self._err(404, "not_found")
            if path == "/login":
                if self._session():
                    return self._redirect("/")
                return self._html(200, login_page())
            if path == "/logout":
                return self._logout()
            s = self._session()
            if not s:
                if path == "/api/summary":
                    return self._err(401, "login")
                return self._redirect("/login")
            if path == "/api/summary":
                return self._json(200, team_summary.cached(self.app.dir, self.app.cfg))
            if path.startswith("/report/"):
                return self._report(path[len("/report/"):])
            return self._index(s)
        return self._err(404, "not_found")

    do_HEAD = do_GET

    def _share_status(self, part, pid):
        d = os.path.join(self.app.dir, PERSONAL_DIR if part == "personal" else TEAM_DIR)
        fp = os.path.join(d, pid + ".json")
        rec = _read_json(fp)
        if not rec:
            return self._err(404, "not_found")
        if not self._token_ok(rec):
            return self._err(403, "token_mismatch")
        out = {"ok": True, "part": part, "id": pid}
        if part == "personal":
            exp = personal_expires(rec.get("received"), self.app.cfg)
            out.update(received=rec.get("received"), expires=exp.isoformat() if exp else "")
        else:
            try:
                ms = datetime.fromtimestamp(os.path.getmtime(fp))
            except OSError:
                ms = datetime.now()
            out.update(month=rec.get("month"), expires=team_expires(ms, self.app.cfg).isoformat())
        return self._json(200, out)

    def _personal_list(self):
        out = []
        d = os.path.join(self.app.dir, PERSONAL_DIR)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json") or not _ID_RX.match(n[:-5]):
                continue
            rec = _read_json(os.path.join(d, n))
            if not rec:
                continue
            exp = personal_expires(rec.get("received"), self.app.cfg)
            out.append({"id": n[:-5], "owner": rec.get("owner"), "function": rec.get("function"),
                        "period": rec.get("period"), "received": rec.get("received"),
                        "expires": exp.isoformat() if exp else ""})
        out.sort(key=lambda r: (str(r["received"] or ""), str(r["owner"] or "")), reverse=True)
        return out

    def _index(self, s):
        c = self.app.conf() or {}
        h = self.app.hello()
        rows = []
        for r in self._personal_list():
            rows.append(
                f"<tr><td>{esc(r['owner'])}</td><td>{esc(r['function'])}</td><td>{esc(r['period'])}</td>"
                f"<td>{esc(r['received'])}</td><td>{esc(r['expires'])}</td>"
                f"<td><a href='/report/{esc(r['id'])}' target='_blank' rel='noopener noreferrer'>열기</a> "
                f"<form class='inline' method='post' action='/admin/delete/personal/{esc(r['id'])}'>"
                f"<input type='hidden' name='csrf' value='{esc(s['csrf'])}'>"
                f"<button type='submit'>삭제</button></form></td></tr>")
        summary = team_summary.cached(self.app.dir, self.app.cfg)
        body = (
            f"<h1>{esc(lmname.PRODUCT)} 팀 서버 — {esc(c.get('org_label'))}</h1>"
            f"<p class='note'>{esc(PURPOSE)} {esc(NO_PRESSURE)}</p>"
            f"<p class='note'>전송 방식 {esc(h['transport'].upper())} · 보관기한: 개인 리포트 {h['serverPersonalDays']}일 · "
            f"익명 기여분 {h['serverTeamDays']}일 (서버를 켤 때·한 시간마다·매일 정리 작업이 지웁니다) · "
            "<a href='/logout'>로그아웃</a></p>"
            "<h2>공유받은 개인 리포트</h2>"
            "<p class='note'>팀원이 직접 골라 보낸 공유용 리포트입니다. 조직장만 이 화면에서 봅니다. "
            "팀원이 공유를 거두거나 자료를 모두 지우면 여기서도 지워집니다. 이름·파트는 팀원이 공유 탭에 적은 그대로이고 서버가 확인한 것이 아닙니다.</p>"
            "<table><tr><th>팀원이 적은 이름</th><th>파트</th><th>기간</th><th>받은 날</th><th>보관기한</th><th></th></tr>"
            + ("".join(rows) or "<tr><td colspan='6' class='note'>공유받은 개인 리포트가 없습니다.</td></tr>")
            + "</table>"
            "<h2>익명 팀 집계</h2>"
            + team_summary.render_html(summary))
        return self._html(200, page(f"{lmname.PRODUCT} 팀 서버", body))

    def _report(self, pid):
        if not _ID_RX.match(pid):
            return self._err(404, "not_found")
        rec = _read_json(os.path.join(self.app.dir, PERSONAL_DIR, pid + ".json"))
        if not rec or not isinstance(rec.get("report_html"), str):
            return self._err(404, "not_found")
        return self._send(200, rec["report_html"], "text/html; charset=utf-8",
                          (("Content-Security-Policy", REPORT_CSP), ("X-Frame-Options", "DENY"),
                           ("X-DNS-Prefetch-Control", "off")))

    def _logout(self):
        self.app.end_session(self._sid())
        return self._redirect("/login", (("Set-Cookie", self._cookie("", 0)),))

    # POST ──────────────────────────────────────────────────────────────
    def do_POST(self):
        path = self._path()
        if path == P + "/share/personal":
            return self._post_personal()
        if path == P + "/share/team":
            return self._post_team()
        if path in ("/login", "/logout") or path.startswith("/admin/"):
            if not self._head_allowed():
                return self._refuse(404, "not_found")
            if path == "/login":
                return self._login()
            if path == "/logout":
                return self._logout()
            m = re.fullmatch(r"/admin/delete/personal/([0-9a-f]{32})", path)
            if m:
                return self._admin_delete(m.group(1))
        return self._refuse(404, "not_found")

    def _login(self):
        if self.app.login_limited(self._client_ip()):
            self._drain()                        # 본문(키)을 읽지 않고 답하면 RST 로 끊겨 이 안내조차 못 받는다
            return self._html(429, login_page("잠시 뒤 다시 시도하세요 — 1분에 5번까지만 시도할 수 있습니다."))
        b = self._body(cap=4096)
        if b is None:
            return None
        form = urllib.parse.parse_qs(b.decode("utf-8", "replace"), max_num_fields=4)
        key = (form.get("key") or [""])[0]
        c = self.app.conf()
        if not c or not verify_key(key, c.get("key")):
            return self._html(401, login_page("조직장 키가 맞지 않습니다."))
        sid = self.app.new_session()
        return self._redirect("/", (("Set-Cookie", self._cookie(sid, SESSION_SEC)),))

    def _admin_delete(self, pid):
        s = self._session()
        if not s:
            self._drain()                        # 읽지 않은 본문이 있으면 RST — 로그인 화면으로 보내는 답을 먼저 받게
            return self._redirect("/login")
        b = self._body(cap=4096)
        if b is None:
            return None
        form = urllib.parse.parse_qs(b.decode("utf-8", "replace"), max_num_fields=4)
        tok = (form.get("csrf") or [""])[0]
        if not self._same_origin() or not hmac.compare_digest(tok, s["csrf"]):
            return self._err(403, "token_mismatch")
        with self.app.lock:
            _rm_file(os.path.join(self.app.dir, PERSONAL_DIR, pid + ".json"))
        _say("조직장이 개인 리포트 1건을 지웠습니다")
        return self._redirect("/")

    def _post_personal(self):
        if not self._join_ok():
            return None
        if not self.app.tls and not self.app.hello()["personalOverHttp"]:
            return self._refuse(403, "http_personal_refused")
        d = self._json_body()
        if d is None:
            return None
        oid = str(d.get("owner_id") or "")
        owner = _clean(d.get("owner"), 40)
        func = _clean(d.get("function"), 40)
        period = str(d.get("period") or "")
        rep = d.get("report_html")
        if (not _ID_RX.match(oid) or not owner or func is None or not _PERIOD_RX.match(period)
                or report_html_problem(rep) is not None):
            return self._err(400, "bad_bundle")
        fp = os.path.join(self.app.dir, PERSONAL_DIR, oid + ".json")
        with self.app.lock:
            old = _read_json(fp) if os.path.exists(fp) else None
            if os.path.exists(fp):
                if not old or not self._token_ok(old):
                    return self._err(403, "token_mismatch")
                token = (self.headers.get("X-AF32-Token") or "").strip()
            else:
                token = self._new_token()
                if token is None:
                    return self._err(400, "bad_bundle")
            today = _today()
            rec = {"product": lmname.PRODUCT, "owner_id": oid, "owner": owner, "function": func, "period": period,
                   "report_html": rep, "token_sha256": _token_hash(token), "received": _ymd(today)}
            try:
                _write_json(fp, rec)
                day = datetime(today.year, today.month, today.day).timestamp()
                coarse_times(fp, day)                    # 파일 시각도 받은 날까지만(시각을 남기지 않는다 — D10)
                coarse_times(os.path.dirname(fp), day)
            except OSError:
                return self._err(500, "server_error")
        exp = personal_expires(rec["received"], self.app.cfg)
        _say("개인 리포트 1건을 받았습니다" if old is None else "개인 리포트 1건이 새로 바뀌었습니다")
        return self._json(200, {"ok": True, "token": token, "expires": exp.isoformat()})

    def _needs_ok(self, needs):
        if not isinstance(needs, list) or not 1 <= len(needs) <= NEEDS_MAX:
            return None
        out = []
        for x in needs:
            if not isinstance(x, dict):
                return None
            name = _clean(x.get("name"), NEED_NAME_MAX)
            tt = _clean(x.get("task_type"), NEED_TYPE_MAX)
            if not name or tt is None:
                return None
            joined = f"{name} {tt}"
            if (_MAIL_RX.search(joined) or _PHONE_RX.search(joined) or privacy.has_identifier(joined)
                    or privacy.sensitive_hit(joined, self.app.cfg)):
                return None
            out.append({"name": name, "task_type": tt})
        return out

    def _post_team(self):
        if not self._join_ok():
            return None
        d = self._json_body()
        if d is None:
            return None
        cid = str(d.get("contribution_id") or "")
        month = str(d.get("month") or "")
        pa = d.get("personal_also")
        needs = self._needs_ok(d.get("needs"))
        if not _ID_RX.match(cid) or not _MONTH_RX.match(month) or not isinstance(pa, bool) or needs is None:
            return self._err(400, "bad_bundle")
        fp = os.path.join(self.app.dir, TEAM_DIR, cid + ".json")
        token = self._new_token()
        if token is None:
            return self._err(400, "bad_bundle")
        ms = _month_start(_today())
        with self.app.lock:
            if os.path.exists(fp):
                return self._err(403, "token_mismatch")
            rec = {"product": lmname.PRODUCT, "contribution_id": cid, "month": month, "personal_also": pa,
                   "needs": needs, "token_sha256": _token_hash(token)}
            try:
                _write_json(fp, rec)
                coarse_times(fp, ms.timestamp())        # 파일 시각도 받은 달 1일로 — 달보다 자세한 시각을 남기지 않는다
                coarse_times(os.path.dirname(fp), ms.timestamp())
            except OSError:
                return self._err(500, "server_error")
        # 익명 기여분은 화면에도 알리지 않는다 — 개인 리포트를 받은 직후의 줄과 이어 보면 누가 보냈는지 짐작된다
        return self._json(200, {"ok": True, "token": token, "expires": team_expires(ms, self.app.cfg).isoformat()})

    # DELETE ────────────────────────────────────────────────────────────
    def do_DELETE(self):
        m = re.fullmatch(re.escape(P) + r"/share/(personal|team)/([0-9a-f]{32})", self._path())
        if not m:
            return self._refuse(404, "not_found")
        part, pid = m.group(1), m.group(2)
        fp = os.path.join(self.app.dir, PERSONAL_DIR if part == "personal" else TEAM_DIR, pid + ".json")
        with self.app.lock:
            rec = _read_json(fp)
            if not rec:
                return self._err(404, "not_found")
            if not self._token_ok(rec):
                return self._err(403, "token_mismatch")
            if not _rm_file(fp):
                return self._err(500, "server_error")
        if part == "team":
            team_summary.invalidate(self.app.dir)
            coarse_times(os.path.dirname(fp), _month_start(_today()).timestamp())
        else:
            t = _today()
            coarse_times(os.path.dirname(fp), datetime(t.year, t.month, t.day).timestamp())
            _say("팀원 요청으로 개인 리포트 1건을 지웠습니다")
        return self._json(200, {"ok": True, "deleted": True})


def make_server(teamdata, cfg, *, bind="0.0.0.0", port=None, tls=None, handler=Handler):
    """서버 객체(아직 serve_forever 전) — TLS 인증서가 있으면 HTTPS. 시험은 bind='127.0.0.1' 로 부른다."""
    use_tls = has_tls(teamdata) if tls is None else tls
    srv = ExclusiveServer((bind, int(port)), handler)
    if use_tls:
        srv.socket = tls_context(teamdata).wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    srv.app = App(teamdata, cfg, tls=use_tls, port=srv.server_address[1])
    return srv


# ── 켜져 있나 ──────────────────────────────────────────────────────────────────
def _pid_alive(pid):
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong(0)
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259          # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except (AttributeError, OSError, ValueError):
        return False


def local_hello(port, tls=False, timeout=2.0):
    """127.0.0.1:port 의 /af32/hello — 이 PC 에서 켜진 서버가 누구인지(없으면 {})."""
    try:
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE                 # 내 PC 의 내 서버 확인용(비밀을 보내지 않는다)
            c = http.client.HTTPSConnection("127.0.0.1", int(port), timeout=timeout, context=ctx)
        else:
            c = http.client.HTTPConnection("127.0.0.1", int(port), timeout=timeout)
        c.request("GET", P + "/hello")
        r = c.getresponse()
        body = r.read(65536)
        c.close()
        if r.status != 200:
            return {}
        d = json.loads(body.decode("utf-8", "replace"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
        return {}


def running(teamdata=None):
    """이 폴더의 서버가 켜져 있나 → (bool, 포트)."""
    d = _read_json(os.path.join(teamdata or TEAMDATA, PID_FILE)) or {}
    pid, port = d.get("pid"), d.get("port")
    if not pid or not port or not _pid_alive(pid):
        return False, port
    return local_hello(port, bool(d.get("tls"))).get("product") == lmname.PRODUCT, port


# ── 명령 ──────────────────────────────────────────────────────────────────────
def _arg(argv, flag, d=""):
    if flag in argv:
        i = argv.index(flag) + 1
        if i < len(argv) and not argv[i].startswith("--"):
            return argv[i]
    return d


def _ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return None


def _yes(v):
    return str(v or "").strip().lower() in ("y", "yes", "예", "네", "1", "true")


def _print_key(key):
    print()
    print("  ┌──────────────────────────────────────────────────────────────┐")
    print(f"  │ 조직장 키: {key}")
    print("  │ 이 키는 지금 한 번만 보여 줍니다. 적어서 안전하게 보관하세요.")
    print("  │ 서버에는 키 원문을 남기지 않습니다(되돌릴 수 없는 PBKDF2 값만).")
    print("  └──────────────────────────────────────────────────────────────┘")
    print()


def wizard(argv, teamdata=None, port=None):
    """처음 시작 — 조직 이름 · HTTP 로 개인 리포트를 받을지(기본 아니오, 날짜와 함께 남긴다) · 조직장 키(한 번만 보여 줌)."""
    td = teamdata or TEAMDATA
    print()
    print("  [처음 시작] 이 PC 를 조직장 팀 서버로 준비합니다. 한 서버에는 조직장 한 명만 둡니다.")
    org = _arg(argv, "--org-label") or None
    if org is None:
        org = _ask("  조직 이름(팀원 공유 화면에 '〈조직 이름〉에게 공유' 로 보입니다): ")
    org = _clean(org, 40) if org is not None else None
    if not org:
        print("  [!] 조직 이름이 없어 시작하지 않았습니다 — AgentFinder32-팀서버.bat 에서 다시 하세요(40자까지).")
        return None
    v = _arg(argv, "--personal-over-http") or None
    if v is None:
        print("  개인 리포트는 HTTPS(teamdata\\tls 에 cert.pem·key.pem 을 둔 경우)로 받는 것이 원칙입니다.")
        v = _ask("  인증서 없이 사내망 HTTP(암호화 없음)로도 팀원 개인 리포트를 받을까요? [y/N]: ")
        if v is None:
            print("  [!] 답이 없어 시작하지 않았습니다 — AgentFinder32-팀서버.bat 에서 다시 하세요.")
            return None
    over_http = _yes(v)
    key = new_secret(KEY_GROUPS)
    today = _ymd(_today())
    conf = {"product": lmname.PRODUCT, "schema": lmname.SHARE_SCHEMA, "server_id": secrets.token_hex(16),
            "created": today, "org_label": org, "personalOverHttp": over_http, "personalOverHttp_decided": today,
            "port": int(port or teamaddr.DEFAULT_PORT), "key": hash_key(key), "key_changed": today,
            "join": new_secret(3), "join_changed": today}
    save_conf(conf, td)
    write_info(conf, td)
    print(f"  조직 이름: {org} · HTTP 로 개인 리포트 받기: {'예' if over_http else '아니오'} ({today} 결정)")
    _print_key(key)
    return conf


def _personal_files(teamdata=None):
    r"""teamdata\personal 의 개인 리포트 파일 이름들(링크는 빼고)."""
    d = os.path.join(teamdata or TEAMDATA, PERSONAL_DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [n for n in names if n.endswith(".json") and _ID_RX.match(n[:-5]) and not _is_link(os.path.join(d, n))]


def delete_personal_reports(teamdata=None):
    """받은 개인 리포트를 모두 지운다 → (지운 수, 못 지운 파일 이름들)."""
    td = teamdata or TEAMDATA
    n, left = 0, []
    for name in _personal_files(td):
        if _rm_file(os.path.join(td, PERSONAL_DIR, name)):
            n += 1
        else:
            left.append(name)
    return n, left


def cmd_new_key(teamdata=None, *, delete_reports=None):
    r"""조직장 키 다시 만들기. 받은 개인 리포트가 있으면 지울지 묻는다(기본: 지운다 — 받는 사람은 그 조직장 한 사람이다.
    조직장이 바뀌면 새 조직장이 예전 공유를 열지 않게). delete_reports 를 주면 묻지 않는다(True 지움 · False 둠)."""
    td = teamdata or TEAMDATA
    conf = load_conf(td)
    if not conf:
        print("  [!] 아직 서버를 준비하지 않았습니다 — [1 서버 시작]을 먼저 하세요.")
        return 2
    have = _personal_files(td)
    if have:
        if delete_reports is None:
            print(f"  받은 개인 리포트가 {len(have)}건 있습니다. 공유받은 사람은 그 리포트를 받은 조직장입니다 — 조직장이 바뀌면 "
                  "지우고, 팀원이 새 조직장에게 공유할지 다시 고릅니다.")
            ans = _ask("  받은 개인 리포트를 모두 지울까요? [Y/n] (그냥 Enter = 지움): ")
            delete_reports = ans is None or not str(ans).strip() or _yes(ans)
        if delete_reports:
            n, left = delete_personal_reports(td)
            print(f"  받은 개인 리포트 {n}건을 지웠습니다." + (f" {len(left)}건은 지우지 못했습니다(다른 프로그램이 쓰는 중)."
                                                         if left else ""))
        else:
            print("  받은 개인 리포트는 그대로 둡니다 — 새 키로도 열어 볼 수 있습니다.")
    key = new_secret(KEY_GROUPS)
    conf["key"] = hash_key(key)
    conf["key_changed"] = _ymd(_today())
    save_conf(conf, td)
    print("  조직장 키를 새로 만들었습니다. 예전 키와 열려 있던 로그인은 더 쓰지 못합니다.")
    _print_key(key)
    return 0


def cmd_new_join(teamdata=None):
    td = teamdata or TEAMDATA
    conf = load_conf(td)
    if not conf:
        print("  [!] 아직 서버를 준비하지 않았습니다 — [1 서버 시작]을 먼저 하세요.")
        return 2
    conf["join"] = new_secret(3)
    conf["join_changed"] = _ymd(_today())
    save_conf(conf, td)
    p = write_info(conf, td)
    print(f"  참여 코드를 바꿨습니다: {conf['join']}")
    print(f"  팀원에게 새 참여 코드를 알려 주세요({p}). 이미 공유한 팀원이 공유를 거두는 것(삭제)은 그대로 됩니다.")
    return 0


def cmd_delete_all(argv, teamdata=None, *, root=None):
    td = teamdata or TEAMDATA
    on, port = running(td)
    if on:
        print(f"  [!] 팀 서버가 켜져 있습니다(포트 {port}) — 서버 창에서 Ctrl+C 로 끈 뒤 다시 하세요.")
        return 2
    if not os.path.lexists(td):
        _say_task_removed(unregister_purge_task(root), root)
        print("  지울 서버 자료가 없습니다.")
        return 0
    if "--yes" not in argv:
        print("  서버 자료를 모두 지웁니다: 받은 개인 리포트·익명 기여분·집계·조직장 키·참여 코드·접속 정보(teamdata\\ 전체)와 "
              "매일 정리 예약 작업.")
        ans = _ask("  되돌릴 수 없습니다. 계속하려면 '삭제' 를 입력하세요: ")
        if (ans or "").strip() != "삭제":
            print("  지우지 않았습니다.")
            return 1
    n, left = rm_tree(td)
    if left:
        # 남은 자료가 있으면 매일 정리 작업은 그대로 둔다(남은 것의 보관기한이 지켜지게) — 다 지워진 뒤에 작업도 지운다
        print(f"  파일 {n}개를 지웠고 {len(left)}개는 지우지 못했습니다(다른 프로그램이 쓰는 중): {', '.join(left[:5])}")
        print("  남은 자료가 있어 매일 정리 예약 작업은 그대로 둡니다 — 그 프로그램을 닫고 다시 하세요.")
        return 1
    _say_task_removed(unregister_purge_task(root), root)
    print(f"  서버 자료를 모두 지웠습니다(파일 {n}개). 다시 켜면 처음 시작 절차를 밟습니다.")
    return 0


# ── 매일 정리 예약 작업(조직장 PC — 서버가 꺼져 있어도 보관기한이 지난 자료를 지운다) ──────────────
def purge_task_name(root=None):
    """사용자 예약 작업 이름 'AgentFinder32 팀 서버 보관기한 정리 <h6>'(설치 폴더마다 하나 — 팀원 쪽 작업과 다른 이름)."""
    return f"{lmname.PRODUCT} 팀 서버 보관기한 정리 {lmname.h6(root or ROOT)}"


def purge_task_command(root=None):
    r"""(실행 파일, 인자) — <root>\python\pythonw.exe -I -X utf8 -B "<root>\teamserver.py" --purge (지우기만 한다)."""
    r = os.path.abspath(str(root or ROOT))
    return os.path.join(r, "python", "pythonw.exe"), f'-I -X utf8 -B "{os.path.join(r, "teamserver.py")}" --purge'


def _xml_esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def purge_task_xml(root=None):
    r = os.path.abspath(str(root or ROOT))
    exe, args = purge_task_command(r)
    user = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
    start = _today().isoformat() + "T" + PURGE_TASK_TIME + ":00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{_xml_esc(lmname.PRODUCT)} 팀 서버에서 보관기한이 지난 자료를 지웁니다</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{_xml_esc(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{_xml_esc(exe)}</Command><Arguments>{_xml_esc(args)}</Arguments><WorkingDirectory>{_xml_esc(r)}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def _schtasks(args, timeout=30):
    try:
        p = subprocess.run(["schtasks.exe"] + list(args), capture_output=True, timeout=timeout,
                           creationflags=NO_WIN if os.name == "nt" else 0)
        return p.returncode
    except (OSError, subprocess.SubprocessError, ValueError):
        return -1


def _tasks_allowed():
    """예약 작업을 건드려도 되나 — 윈도이고 AF32_NO_TASK 가 없을 때만(시험·개발 PC 는 AF32_NO_TASK=1)."""
    return os.name == "nt" and not os.environ.get("AF32_NO_TASK")


def register_purge_task(root=None):
    r"""매일 1회 팀 서버 보관기한 정리 사용자 작업을 만든다(있으면 바꾼다) → True 성공 · False 실패 · None 만들지 않음
    (AF32_NO_TASK · 윈도가 아님 · <root>\python\pythonw.exe 없음). 예외를 던지지 않는다."""
    try:
        if not _tasks_allowed():
            return None
        r = os.path.abspath(str(root or ROOT))
        exe, _a = purge_task_command(r)
        if not os.path.isfile(exe):
            return None
        xml = os.path.join(tempfile.gettempdir(), f"{lmname.TMP_PREFIX}teamtask_{lmname.h6(r)}_{os.getpid()}.xml")
        try:
            with open(xml, "w", encoding="utf-16") as f:
                f.write(purge_task_xml(r))
            rc = _schtasks(["/Create", "/TN", purge_task_name(r), "/XML", xml, "/F"])
        finally:
            try:
                os.remove(xml)
            except OSError:
                pass
        return rc == 0
    except Exception:  # noqa: BLE001 - 실패는 False(서버 창이 알린다)
        return False


def unregister_purge_task(root=None):
    """매일 정리 작업을 지운다 → True(지웠다) · False(못 지웠다) · None(지울 것이 없다 — 그 작업이 없음 · 건드리지 않음:
    AF32_NO_TASK·윈도가 아님). 예외를 던지지 않는다."""
    try:
        if not _tasks_allowed():
            return None
        name = purge_task_name(root)
        q = _schtasks(["/Query", "/TN", name])
        if q < 0:
            return False
        if q != 0:
            return None
        return _schtasks(["/Delete", "/TN", name, "/F"]) == 0
    except Exception:  # noqa: BLE001
        return False


def purge_task_registered(root=None):
    """매일 정리 작업이 있나 → True · False · None(알 수 없음 — AF32_NO_TASK·윈도가 아님·작업 스케줄러에 묻지 못함). 읽기만 한다."""
    try:
        if not _tasks_allowed():
            return None
        rc = _schtasks(["/Query", "/TN", purge_task_name(root)])
        return None if rc < 0 else rc == 0
    except Exception:  # noqa: BLE001
        return None


def ensure_purge_task(root=None, *, first=False):
    """서버를 켤 때 — 처음 켜는 것이면(first) 매일 정리 작업을 만들고, 다시 켜는 것이면 그 작업이 없어졌을 때만 다시 만든다
    (처음에 만들지 못했거나 누가 지운 때 — 서버가 꺼져 있어도 보관기한이 지켜지게). → register_purge_task 의 값 | None(그대로 둠)."""
    if not first and purge_task_registered(root) is not False:
        return None
    task = register_purge_task(root)
    if task is True:
        _say(f"매일 한 번 보관기한이 지난 서버 자료를 지우는 예약 작업('{purge_task_name(root)}')을 "
             + ("만들었습니다" if first else "다시 만들었습니다") + " — [4 서버 자료 모두 삭제]가 지웁니다")
    elif task is False or _tasks_allowed():         # None 인데 건드려도 되는 PC 면 동봉 파이썬(python\pythonw.exe)이 없는 것
        _say("[!] 매일 정리 예약 작업을 만들지 못했습니다" + ("" if task is False else "(python\\pythonw.exe 없음)")
             + " — 서버를 켤 때·한 시간마다·팀서버 bat 메뉴를 쓸 때 지웁니다")
    return task


def _say_task_removed(res, root=None):
    if res is True:
        print("  매일 정리 예약 작업도 지웠습니다.")
    elif res is False:
        print(f"  [!] 매일 정리 예약 작업('{purge_task_name(root)}')을 지우지 못했습니다 — Windows 작업 스케줄러에서 직접 지울 수 "
              "있습니다.")


def cmd_purge(teamdata=None, cfg=None, *, quiet=False):
    """보관기한이 지난 개인 리포트·기여분만 지운다(서버가 켜져 있어도 된다) → purge 결과. 명령마다·매일 정리 작업이 부른다."""
    td = teamdata or TEAMDATA
    if not os.path.isdir(td) or _is_link(td):
        return {"deleted": 0, "personal": 0, "team": 0, "errors": []}
    if cfg is None:
        cfg, _w = afcfg.load_effective(ROOT)
    try:
        r = purge(td, cfg)
    except Exception as e:  # noqa: BLE001 - 정리 실패로 명령을 막지 않는다(다음 명령·매일 작업 때 다시)
        r = {"deleted": 0, "personal": 0, "team": 0, "errors": [type(e).__name__]}
    if not quiet and r["deleted"]:
        print(f"  보관기한이 지난 서버 자료 {r['deleted']}건을 지웠습니다.")
    return r


def _purge_loop(srv, stop):
    while not stop.wait(PURGE_EVERY_SEC):
        try:
            r = purge(srv.app.dir, srv.app.cfg)
            if r["deleted"]:
                _say(f"보관기한이 지난 자료 {r['deleted']}건을 지웠습니다")
        except Exception as e:  # noqa: BLE001 - 정리 실패로 서버가 죽지 않게(다음 시간에 다시)
            _say(f"보관기한 정리 실패({type(e).__name__}) — 한 시간 뒤 다시 합니다")


def start(argv):
    import install
    import retention
    cfg, warns = afcfg.load_effective(ROOT)
    # 명령마다 보관기한이 지난 서버 자료부터 지운다 — 아래에서 멈춰도(설치 위치·포트·인증서) 받은 자료가 기한을 넘겨 남지 않게
    r = cmd_purge(TEAMDATA, cfg, quiet=True)
    if r["deleted"]:
        _say(f"보관기한이 지난 자료 {r['deleted']}건을 지웠습니다")
    msg = install.startup_check(ROOT)
    if msg:
        _say(msg)
        return 4
    retention.purge_legacy(ROOT)
    for w in warns:
        _say(f"설정 경고: {w}")
    retention.purge(ROOT, cfg)
    old = legacy_teamdata()
    if old:
        _say(f"teamdata 에 LoadMonitor 팀 자료가 남아 있습니다({len(old)}개 폴더) — 섞이지 않게 시작하지 않습니다. "
             "AgentFinder32-팀서버.bat 의 [4 서버 자료 모두 삭제]로 지운 뒤 다시 켜세요.")
        return 4
    os.makedirs(TEAMDATA, exist_ok=True)
    port = None
    if _arg(argv, "--port"):
        port, err = teamaddr.check_port(_arg(argv, "--port"))
        if port is None:
            _say(f"--port 값을 쓸 수 없습니다 — {err}")
            return 2
    conf = load_conf()
    first = not conf
    if first:
        conf = wizard(argv, port=port)
        if not conf:
            return 2
    ensure_purge_task(ROOT, first=first)            # 서버가 꺼져 있어도 매일 한 번 보관기한 정리(처음 켤 때 만든다)
    if port is None:
        port, err = teamaddr.check_port(conf.get("port") or teamaddr.DEFAULT_PORT)
        if port is None:
            _say(f"설정된 포트를 쓸 수 없습니다 — {err} (--port 로 다른 번호를 주세요)")
            return 2
    tls = has_tls()
    if tls:
        try:
            tls_context()
        except (OSError, ssl.SSLError, ValueError) as e:
            _say(f"teamdata\\tls 의 인증서를 읽지 못해 시작하지 않습니다({type(e).__name__}) — cert.pem·key.pem 을 확인하세요")
            return 1
    bind = _arg(argv, "--bind") or "0.0.0.0"
    try:
        srv = make_server(TEAMDATA, cfg, bind=bind, port=port, tls=tls)
    except OSError as e:
        code = getattr(e, "winerror", 0) or e.errno or 0
        _say(f"포트 {port} 을 열지 못했습니다 (오류 {code})")
        who = local_hello(port, tls) or local_hello(port, not tls)
        if who.get("product") == lmname.PRODUCT:
            _say("이 PC 에서 AgentFinder32 팀 서버가 이미 켜져 있습니다 — 그 창을 쓰세요.")
        else:
            _say("다른 프로그램이 이 포트를 쓰고 있습니다 — 그 프로그램은 끄지 않습니다. --port 로 다른 번호를 주세요.")
        return 3
    try:
        _write_json(os.path.join(TEAMDATA, PID_FILE), {"pid": os.getpid(), "port": port, "tls": tls})
    except OSError:
        pass
    only_here = "127.0.0.1" if _loopback(bind) else None        # --bind 127.0.0.1: 이 PC 안에서만(시험)
    try:
        write_info(conf, TEAMDATA, port=port, tls=tls, host=only_here)
    except OSError:
        pass
    stop = threading.Event()
    threading.Thread(target=_purge_loop, args=(srv, stop), name="af32-purge", daemon=True).start()
    h = srv.app.hello()
    _say(f"{lmname.PRODUCT} 팀 서버 — 조직: {h['org_label']}")
    _say(f"팀원 공유 주소: {address_for(port, tls, only_here)} (전송 방식 {h['transport'].upper()}"
         + (")" if tls else " · 사내망 · 암호화 없음)") + (" — 이 PC 안에서만 열었습니다" if only_here else ""))
    if tls:
        _say("개인 리포트: HTTPS 로 받습니다")
    else:
        _say("개인 리포트: " + ("HTTP 로도 받습니다" if h["personalOverHttp"] else "받지 않습니다(HTTP) — 익명 팀 집계만 받습니다")
             + f" ({conf.get('personalOverHttp_decided') or '-'} 결정)")
    _say(f"팀원에게 알려 줄 주소·참여 코드: {os.path.join(TEAMDATA, INFO_FILE)}")
    if srv.app.remote_view:
        _say("[!] team.remoteView 가 켜져 있어 조직장 화면이 사내망에도 열립니다(HTTPS)")
        _say(f"조직장 화면: {address_for(port, tls)}/ (조직장 키로 로그인)")
    else:
        if srv.app.remote_view_wanted:
            _say("[!] team.remoteView 는 HTTPS(teamdata\\tls 의 cert.pem·key.pem)로 켤 때만 씁니다 — HTTP 에서는 조직장 키가 "
                 "암호화 없이 오가므로 조직장 화면을 이 PC 에서만 엽니다")
        _say(f"조직장 화면: {'https' if tls else 'http'}://127.0.0.1:{port}/ (이 PC 에서만 · 조직장 키로 로그인)")
    _say(f"보관기한: 개인 리포트 {h['serverPersonalDays']}일 · 익명 기여분 {h['serverTeamDays']}일 — 켤 때·한 시간마다·"
         "매일 정리 작업이 지웁니다")
    _say("종료: Ctrl+C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        _say("종료")
    finally:
        stop.set()
        srv.server_close()
        try:
            d = _read_json(os.path.join(TEAMDATA, PID_FILE)) or {}
            if d.get("pid") == os.getpid():
                os.remove(os.path.join(TEAMDATA, PID_FILE))
        except OSError:
            pass
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--delete-all" in argv:
        return cmd_delete_all(argv)                 # 통째로 지운다(+ 매일 정리 작업)
    if "--purge" in argv:                           # 매일 정리 작업 — 보관기한이 지난 것만
        return 1 if cmd_purge()["errors"] else 0
    if "--new-key" in argv or "--new-join" in argv:
        cmd_purge()                                 # 명령마다 보관기한이 지난 자료부터 지운다(서버가 꺼져 있어도)
        return cmd_new_key() if "--new-key" in argv else cmd_new_join()
    return start(argv)                              # 켤 때도 지운다(start 안)


if __name__ == "__main__":
    sys.exit(main())
