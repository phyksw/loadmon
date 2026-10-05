# -*- coding: utf-8 -*-
r"""LM27 관문 검사기 — 계약 §11.1 lint L-01~L-30 의 정적 부분(WP-04, CR-05·06·07·14).

사용
  python tools\hook_check.py <파일…>           파일 단위 검사(훅 규칙 묶음). 문제 있으면 exit 2
  python tools\hook_check.py                    훅 모드 — Claude Code PostToolUse 가 stdin 으로 주는 UTF-8 JSON 에서
                                                편집한 파일 경로를 꺼내 같은 검사(exit 2 = 결과가 편집자에게 되돌아간다)
  python tools\hook_check.py --repo [L-nn …]    저장소 전역 검사(인자 없으면 L-01~L-30 전부). 오류 있으면 exit 1
  python tools\hook_check.py --list             규칙 목록
  선택: --root <트리>   --rules L-nn,…(파일 모드 규칙 지정)   --l12-full(W2 통합 창부터 L-12 죽은 키 전면 실패 — CR-05)

훅 규칙 묶음(파일 단위 부분, 한 파일 2초 안): L-01·02·03·04·05·06·07·09·10·11·16·18·19·20·26.
저장소 전역(--repo): 위 규칙을 모든 파일에 + L-08·12·13·14·15·17·21·22·23·24·25·27·28·29·30.

원칙
- 대상이 아직 없는 검사(모듈·레지스트리·스크립트가 아직 생기지 않음)는 건너뛰고 '경고'만 남긴다 — W0·W1 의
  다른 작업 패키지를 막지 않는다. 대상이 생기면 그 순간부터 실패로 센다.
- L-26 금지어 목록 = %LOCALAPPDATA%\LoadMonitor27\dev\forbidden_words.txt(UTF-8, 한 줄 한 낱말, '#' 주석) — 저장소 밖.
  없거나 비면 실패(fail-closed, CR-06). 위반은 '목록 n번째 항목'으로만 알리고 낱말 자체는 어디에도 출력하지 않는다.
  시험 복제 트리(WP-05 tests\fixtures\tree.py — LM27T_CLONE 이 있음)는 %LOCALAPPDATA% 를 샌드박스로 돌리므로, 그 안에
  목록이 없을 때만 tree.py 가 넘긴 실제 목록 위치(LM27T_FORBIDDEN_WORDS)를 읽는다. 복제 밖에서는 이 변수를 보지 않는다.
- 예외 표(CR-14, 경로 단위): 사설 IP·비예시 이메일 검사는 docs\*.md 와 lm27\privacy\corpus\regress_v1.jsonl 을 뺀다.
  검사 규칙 표를 담은 이 파일과 tools\lint.ps1 은 문자열 패턴 검사(L-05 문자열·08·12 읽기 수집·13·14·15·16·19·21·
  22·23 사본·25·28·29)에서 뺀다(X-313). 금지어(L-26)는 이 파일에도 적용한다.
- 개인정보 규칙(L-21 사설 IP·L-26 금지어·이메일)은 확장자가 아니라 내용으로 텍스트를 판정한다(.csv·.xml·.eml·.ics·.reg·
  .cmd·.psm1·확장자 없는 파일 — UTF-16 은 BOM 으로, .gz 는 풀어서). 인코딩 규칙(L-02) 등은 확장자 집합 그대로.
- 저장소 전역 검사가 보지 않는 곳(python\ · data\ · out\ · .wf\ · .git\ · __pycache__ · config\config.json · *.part)은
  훅·파일 모드도 보지 않는다. 규칙이 스스로 깨지면 '관문 도구 내부 오류' 지적 1건(오류)으로 드러낸다.
- 저장소의 코드를 실행해야 하는 검사(L-23·24·30)는 %TEMP% 를 작업 폴더로 한 자식 파이썬(-B -I)에서만 돈다
  (트리 안에 __pycache__ 를 만들지 않는다).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # L-05 · 계약 §9.1 — tools\*.py 는 첫 실행문에서 자기 루트를 넣는다

import ast
import gzip
import importlib.util
import io
import json
import re
import shutil
import subprocess
import tempfile
import time
import zlib

GATE_VERSION = "lm27-lint/1.0"

ALL_RULES = tuple(f"L-{i:02d}" for i in range(1, 31))
HOOK_RULES = ("L-01", "L-02", "L-03", "L-04", "L-05", "L-06", "L-07", "L-09", "L-10", "L-11",
              "L-16", "L-18", "L-19", "L-20", "L-26")
RULE_TITLES = {
    "L-01": "제어문자 0",
    "L-02": "인코딩·줄끝(.bat CP949+CRLF · .ps1 BOM+CRLF · 그 밖 UTF-8 LF)",
    "L-03": "ruff(ruff.toml, --no-cache)",
    "L-04": "zoneinfo.ZoneInfo 0",
    "L-05": "python -m lm27 0 · 진입 스크립트 ROOT sys.path 삽입",
    "L-06": "except ImportError 로 삼키기 0",
    "L-07": "최종 파일 쓰기(쓰기 open·로그 핸들러·임시 파일·sqlite·shutil 복사 …)는 fsx·store.writer·bridge.fsio 에만",
    "L-08": "단일 로더 — data 경로 조립은 paths.py, data\\pcs 는 bundle 7모듈",
    "L-09": "수집기 PS 디스크 쓰기 금지(대상 무관 — 운영 파일·시험 주입 -OutDir 만 예외)",
    "L-10": "수집기 파이썬 import 허용 목록",
    "L-11": "저장 경로 우회 0(SanitizedRow·_SEAL·봉인 행 복제·변경·store 경로)",
    "L-12": "설정 키 ⊂ 레지스트리 · 죽은 키 0 · §5.2 = 레지스트리 · snake_case 0",
    "L-13": "사유 코드 ⊂ 계약 §6.1",
    "L-14": "경로 ID·kind 상수 ⊂ 계약 §6.5·§3.1",
    "L-15": "작업·뮤텍스 이름에 install_id · 시험 작업 LM27T-",
    "L-16": "Edge 플래그·프로필 키는 브리지 안 · office.com 0 · os.kill 0",
    "L-17": "브리지 G-B1·B2·B3·B7",
    "L-18": "시간 미전송(send_fields·프롬프트 템플릿)",
    "L-19": "화면 위험 API·색·반올림·외부 참조·데이터 섬",
    "L-20": "서버 SO_REUSEADDR·allow_reuse_address 0",
    "L-21": "팀 서버 기본 주소 고정 · 사설 IP 금지",
    "L-22": "팀 빌더 통째 전달 0 · 팀 레지스트리 읽는 모듈 제한",
    "L-23": "TEAM_SPEC_V1 = TAB §2.3.2 = P §14.5",
    "L-24": "정제 규칙 잠금 · 배포 기본값 빈 값",
    "L-25": "분류 AI 되먹임 금지 · 영역 이름·색 단일원",
    "L-26": "실명·코드네임 금지어 · 이메일은 example 만",
    "L-27": "JS 문법 node --check(개발 PC 전용)",
    "L-28": "별개 프로젝트·이전 판 포트·작업 이름 0",
    "L-29": "폐기 산출물·금지 접근 경로(Graph·앱 캐시·OST/PST·자격 증명·브라우저 DB) 0",
    "L-30": "브리지 stages import 무부작용",
}

CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
LF_EXT = frozenset({".py", ".md", ".json", ".jsonl", ".js", ".css", ".html", ".svg", ".txt", ".toml"})
TEXT_EXT = LF_EXT | {".ps1", ".bat"}
TEXT_NAMES = frozenset({".gitattributes", ".gitignore"})
PS_EXT = frozenset({".ps1", ".psm1"})
BAT_EXT = frozenset({".bat", ".cmd"})
CODE_EXT = frozenset({".py", ".js"}) | PS_EXT | BAT_EXT
# 개인정보 규칙(L-21·L-26)은 확장자 목록이 아니라 내용으로 텍스트를 판정한다(.csv·.xml·.eml·.ics·.reg·.cmd·.psm1·
# 확장자 없는 파일·.gz 시험 자료 — 반입 수집기 형식과 같은 자료에 실데이터가 섞이는 자리). L-02 등은 확장자 집합 그대로.
PRIVACY_MAX = 32 * 1024 * 1024
WEB_EXT = frozenset({".js", ".html", ".css"})
TOP_SKIP = frozenset({".git", "python", "data", "out", ".wf"})
ANY_SKIP = frozenset({".git", "__pycache__", ".ruff_cache", "node_modules"})
FILE_SKIP = frozenset({"config/config.json"})
RULE_TABLE_FILES = frozenset({"tools/hook_check.py", "tools/lint.ps1"})
CR14_EXEMPT = re.compile(r"^(?:docs/[^/]+\.md|lm27/privacy/corpus/regress_v1\.jsonl)$")
FORBIDDEN_REL = os.path.join("LoadMonitor27", "dev", "forbidden_words.txt")
FORBIDDEN_SHOW = r"%LOCALAPPDATA%\LoadMonitor27\dev\forbidden_words.txt"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# 계약 표를 읽지 못할 때만 쓰는 사본(계약 v1.0.1). 평소에는 docs\CONTRACT.md 에서 읽는다.
FALLBACK_PATH_IDS = frozenset({
    "mail.com", "mail.index", "mail.owa", "mail.copilot", "mail.import", "cal.com", "cal.index", "cal.owa",
    "cal.copilot", "cal.import", "teams.uia", "teams.web", "teams.copilot", "pc.sampler", "pc.events",
    "pc.files", "pc.mru", "pc.recent", "pc.git", "pc.compute", "manual"})
FALLBACK_KINDS = frozenset({"mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual"})
FALLBACK_DOMAINS = {"DEV": ("개발 프로젝트", "#2a78d6"), "MP": ("양산 프로젝트", "#c47400"),
                    "EXT": ("외부 업무지원", "#0e8c7a"), "COM": ("공통 업무", "#a61b4a"),
                    "AX": ("AX 프로젝트", "#6c4fb8"), "UNC": ("미분류", "#8b929b")}
# 팀 서버 기본 주소(사용자 지시 고정값, L-21). 사설 IP 금지 검사의 유일한 예외 값이다.
TEAM_HOST = ".".join(("10", "115", "147", "68"))
TEAM_PORT = 9310
TEAM_URL = f"http://{TEAM_HOST}:{TEAM_PORT}"
TEAM_IP_OK = frozenset({"lm27/team/client.py", "config/settings_registry.json"})


# ───────────────────────────── 결과 ─────────────────────────────
class Finding:
    """한 건의 지적. warn=True 는 막지 않는 경고(대상 미생성·도구 없음 등)."""
    __slots__ = ("rule", "rel", "line", "msg", "warn")

    def __init__(self, rule, rel, line, msg, warn=False):
        self.rule, self.rel, self.line, self.msg, self.warn = rule, rel, int(line or 0), msg, bool(warn)

    def __str__(self):
        loc = f"{self.rel}:{self.line}" if self.line else (self.rel or "(저장소)")
        return f"{self.rule} {loc}: {self.msg}" + (" [경고]" if self.warn else "")

    __repr__ = __str__


def _f(rule, s, line, msg, warn=False):
    return Finding(rule, s.rel if s is not None else "", line, msg, warn)


# ───────────────────────────── 원천 파일 ─────────────────────────────
class Src:
    """검사 대상 파일 하나 — 바이트·텍스트·AST 를 한 번씩만 만든다."""

    def __init__(self, root, path):
        self.path = os.path.abspath(path)
        root = os.path.abspath(root)
        if _is_under(self.path, root):
            self.rel = os.path.relpath(self.path, root)
        else:
            self.rel = self.path
        self.rp = self.rel.replace("\\", "/")
        self.name = os.path.basename(self.path)
        self.ext = os.path.splitext(self.name)[1].lower()
        self._raw = self._text = self._tree = self._lines = None
        self._tree_done = False
        self._parents = None
        self._docs = None
        self._ptext = False                       # False = 아직 안 봄, None = 텍스트 아님

    # 성질
    @property
    def is_text(self):
        return self.ext in TEXT_EXT or self.name in TEXT_NAMES

    @property
    def privacy_text(self):
        """개인정보 검사(L-21·L-26)용 텍스트 — 확장자와 무관하게 내용으로 판정. 텍스트가 아니면 None.
        UTF-16(BOM) 은 BOM 을 보고, .gz 는 풀어서, 그 밖은 UTF-8 → CP949 순으로 디코드한다."""
        if self._ptext is False:
            self._ptext = self.text if self.is_text else _decode_any(self.raw, self.ext)
        return self._ptext

    @property
    def is_texty(self):
        return self.is_text or self.privacy_text is not None

    @property
    def is_py(self):
        return self.ext == ".py"

    @property
    def is_code(self):
        return self.ext in CODE_EXT

    @property
    def is_test(self):
        return self.rp.startswith("tests/")

    @property
    def is_doc(self):
        return self.rp.startswith("docs/")

    @property
    def is_product(self):
        return not (self.is_test or self.is_doc or self.rp.startswith(".claude/") or os.path.isabs(self.rp))

    @property
    def rule_table(self):
        return self.rp in RULE_TABLE_FILES

    def under(self, *prefixes):
        return any(self.rp.startswith(p) for p in prefixes)

    # 내용
    @property
    def raw(self):
        if self._raw is None:
            with open(self.path, "rb") as fh:
                self._raw = fh.read()
        return self._raw

    @property
    def text(self):
        if self._text is None:
            raw = self.raw
            if self.ext in BAT_EXT:
                self._text = raw.decode("cp949", errors="replace")
            elif raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                self._text = raw.decode("utf-16", errors="replace")
            else:
                self._text = raw.decode("utf-8-sig", errors="replace")
            self._text = self._text.replace("\r\n", "\n")
        return self._text

    @property
    def lines(self):
        if self._lines is None:
            self._lines = self.text.split("\n")
        return self._lines

    @property
    def tree(self):
        if not self._tree_done:
            self._tree_done = True
            if self.is_py:
                try:
                    self._tree = ast.parse(self.text, filename=self.rel)
                except (SyntaxError, ValueError):
                    self._tree = None
        return self._tree

    def parent(self, node):
        if self._parents is None:
            self._parents = {}
            if self.tree is not None:
                for p in ast.walk(self.tree):
                    for c in ast.iter_child_nodes(p):
                        self._parents[id(c)] = p
        return self._parents.get(id(node))

    def is_docstring(self, node):
        if self._docs is None:
            self._docs = set()
            if self.tree is not None:
                for n in ast.walk(self.tree):
                    if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
                        b = n.body[0]
                        if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                            self._docs.add(id(b.value))
        return id(node) in self._docs

    def str_consts(self, docstrings=False):
        """(노드, 값) — 문자열 상수. 기본은 docstring 제외."""
        if self.tree is None:
            return
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if docstrings or not self.is_docstring(n):
                    yield n, n.value

    def code_lines(self):
        """(줄 번호, 줄) — 주석만 있는 줄을 뺀 텍스트 줄(.ps1 .bat .js .html .css 용 정규식 검사)."""
        in_block = False
        for i, ln in enumerate(self.lines, 1):
            t = ln.strip()
            if self.ext in PS_EXT:
                if in_block:
                    if "#>" in t:
                        in_block = False
                    continue
                if t.startswith("<#"):
                    in_block = "#>" not in t[2:]
                    continue
                if t.startswith("#"):
                    continue
            elif self.ext in BAT_EXT:
                if t.lower().startswith(("rem ", "::")) or t.lower() == "rem":
                    continue
            elif self.ext in (".js", ".css"):
                if in_block:
                    if "*/" in t:
                        in_block = False
                    continue
                if t.startswith("/*"):
                    in_block = "*/" not in t[2:]
                    continue
                if t.startswith("//"):
                    continue
            elif self.ext == ".py":
                if t.startswith("#"):
                    continue
            yield i, ln


def _is_under(path, root):
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root)).rstrip("\\/")
    return p == r or p.startswith(r + os.sep)


def _gunzip(raw):
    """gzip(여러 멤버)을 PRIVACY_MAX 까지 푼다. 깨진 꼬리는 버리고 앞부분만."""
    out = []
    n = 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        while n < PRIVACY_MAX:
            try:
                chunk = gz.read(1 << 16)
            except (OSError, EOFError, zlib.error):
                break
            if not chunk:
                break
            out.append(chunk)
            n += len(chunk)
    return b"".join(out)


def _decode_any(raw, ext):
    """내용으로 텍스트 판정 — NUL 이 없고 UTF-8(BOM 허용)·CP949 로 읽히거나, BOM 있는 UTF-16 이면 텍스트. 아니면 None."""
    if len(raw) > PRIVACY_MAX:
        return None
    if ext == ".gz" or raw[:2] == b"\x1f\x8b":
        try:
            raw = _gunzip(raw)
        except (OSError, EOFError, zlib.error):
            return None
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16").replace("\r\n", "\n")
        except UnicodeDecodeError:
            return None
    if b"\x00" in raw:
        return None
    for enc in (("cp949", "utf-8-sig") if ext in BAT_EXT else ("utf-8-sig", "cp949")):
        try:
            return raw.decode(enc).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return None


def _line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return (base or "?") + "." + node.attr
    if isinstance(node, ast.Call):
        return _dotted(node.func) + "()" if _dotted(node.func) else "?()"
    return ""


def _last(node):
    """Name 이면 id, Attribute 면 attr, 아니면 ''."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


# ───────────────────────────── 실행 문맥 ─────────────────────────────
class Ctx:
    """한 번 실행의 공유 상태 — 계약 표·금지어·레지스트리·도구 탐색을 한 번만 한다."""

    def __init__(self, root=None, forbidden_path=None, l12_full=False, python=None):
        self.root = os.path.abspath(root or ROOT)
        self.forbidden_path = forbidden_path
        self.l12_full = bool(l12_full)
        self._python = python
        self._c = {}
        self.once = set()

    def memo(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def exists(self, rp):
        return os.path.isfile(self.p(*rp.split("/")))

    def doc(self, name):
        def load():
            fp = self.p("docs", name)
            if not os.path.isfile(fp):
                return None
            with open(fp, "rb") as fh:
                return fh.read().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
        return self.memo("doc:" + name, load)

    # 계약 표
    @property
    def contract(self):
        return self.doc("CONTRACT.md")

    @property
    def cfg_keys(self):
        return self.memo("cfg_keys", lambda: parse_cfg_keys(self.contract) if self.contract else set())

    @property
    def old_keys(self):
        return self.memo("old_keys", lambda: parse_old_keys(self.contract, self.cfg_keys) if self.contract else set())

    @property
    def rcodes(self):
        return self.memo("rcodes", lambda: parse_rcodes(self.contract) if self.contract else (set(), set()))

    @property
    def path_ids(self):
        return self.memo("path_ids", lambda: (parse_path_ids(self.contract) if self.contract else None)
                         or set(FALLBACK_PATH_IDS))

    @property
    def kinds(self):
        return self.memo("kinds", lambda: (parse_kinds(self.contract) if self.contract else None)
                         or set(FALLBACK_KINDS))

    @property
    def domains(self):
        return self.memo("domains", lambda: (parse_domains(self.contract) if self.contract else None)
                         or dict(FALLBACK_DOMAINS))

    @property
    def cfg_namespaces(self):
        return self.memo("cfg_ns", lambda: {k.split(".", 1)[0] for k in self.cfg_keys})

    # 금지어(CR-06)
    def forbidden(self):
        def load():
            p = self.forbidden_path
            if p is None:
                lad = os.environ.get("LOCALAPPDATA", "")
                p = os.path.join(lad, FORBIDDEN_REL) if lad else ""
                if not (p and os.path.isfile(p)) and os.environ.get("LM27T_CLONE"):
                    # 시험 복제 트리의 샌드박스 %LOCALAPPDATA% — tree.py 가 넘긴 실제 목록 위치(내용은 복사하지 않음)
                    p = os.environ.get("LM27T_FORBIDDEN_WORDS", "") or p
            if not p or not os.path.isfile(p):
                return None, f"금지어 목록 없음({FORBIDDEN_SHOW}) — 목록 없이는 통과시키지 않는다(fail-closed, CR-06)"
            try:
                with open(p, "rb") as fh:
                    txt = fh.read().decode("utf-8-sig")
            except (OSError, UnicodeDecodeError) as e:
                return None, f"금지어 목록 읽기 실패({type(e).__name__}) — UTF-8 한 줄 한 낱말"
            words = []
            for ln in txt.splitlines():
                w = ln.strip()
                if w and not w.startswith("#"):
                    words.append(w.lower())
            if not words:
                return None, "금지어 목록이 비어 있음 — 목록 없이는 통과시키지 않는다(CR-06)"
            return words, None
        return self.memo("forbidden", load)

    # 설정 레지스트리(WP-01 소유)
    def registry(self):
        def load():
            fp = self.p("config", "settings_registry.json")
            if not os.path.isfile(fp):
                return None, None
            try:
                with open(fp, "rb") as fh:
                    obj = json.loads(fh.read().decode("utf-8-sig"), object_pairs_hook=_no_dup)
            except (ValueError, UnicodeDecodeError) as e:
                return None, f"settings_registry.json 읽기 실패({type(e).__name__}: {str(e)[:80]})"
            ent = registry_entries(obj)
            if not ent:
                return None, "settings_registry.json 에서 키 목록을 찾지 못함(keys 사전·목록 또는 키→메타 사전)"
            return ent, None
        return self.memo("registry", load)

    # 도구
    @property
    def python(self):
        if self._python:
            return self._python
        emb = self.p("python", "python.exe")
        return emb if os.path.isfile(emb) else sys.executable

    def run_py(self, code, timeout=60):
        """%TEMP% 를 작업 폴더로 한 자식 파이썬(-X utf8 -B -I). 반환 (rc, out, err)."""
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            p = subprocess.run([self.python, "-X", "utf8", "-B", "-I", "-c", code], capture_output=True,
                               timeout=timeout, cwd=tempfile.gettempdir(), env=env, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return 124, "", "시간 초과"
        except OSError as e:
            return 127, "", f"파이썬 실행 실패({type(e).__name__})"
        dec = lambda b: (b or b"").decode("utf-8", errors="replace")  # noqa: E731
        return p.returncode, dec(p.stdout), dec(p.stderr)

    def ruff_cmd(self):
        return self.memo("ruff", _find_ruff)

    def node(self):
        def find():
            exe = shutil.which("node")
            if exe:
                return exe
            for c in (r"C:\Program Files\nodejs\node.exe",):
                if os.path.isfile(c):
                    return c
            return None
        return self.memo("node", find)


def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"중복 키 {k!r}")
        d[k] = v
    return d


def registry_entries(obj):
    """레지스트리 JSON 에서 {키: 메타} 를 꺼낸다(WP-01 형식에 관대하게)."""
    if isinstance(obj, dict):
        for name in ("keys", "settings", "registry", "entries"):
            v = obj.get(name)
            if isinstance(v, dict) and v:
                return {k: (m if isinstance(m, dict) else {"default": m}) for k, m in v.items()}
            if isinstance(v, list) and v:
                return {e["key"]: e for e in v if isinstance(e, dict) and isinstance(e.get("key"), str)}
        ks = [k for k in obj if isinstance(k, str) and "." in k]
        if ks:
            return {k: (obj[k] if isinstance(obj[k], dict) else {"default": obj[k]}) for k in ks}
    if isinstance(obj, list):
        return {e["key"]: e for e in obj if isinstance(e, dict) and isinstance(e.get("key"), str)}
    return {}


def _find_ruff():
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    py = shutil.which("python")
    if py and os.path.normcase(os.path.abspath(py)) != os.path.normcase(os.path.abspath(sys.executable)):
        try:
            p = subprocess.run([py, "-m", "ruff", "--version"], capture_output=True, timeout=20,
                               creationflags=NO_WINDOW)
            if p.returncode == 0:
                return [py, "-m", "ruff"]
        except (OSError, subprocess.SubprocessError):
            pass
    return None


# ───────────────────────────── 계약 문서 읽기 ─────────────────────────────
def _section(text, head):
    """'### 5.2' 같은 머리말부터 같은 수준 이상의 다음 머리말 앞까지."""
    if not text:
        return ""
    i = text.find("\n" + head)
    if i < 0:
        if text.startswith(head):
            i = -1
        else:
            return ""
    start = i + 1
    level = len(head.split(" ", 1)[0])
    m = re.compile(r"\n#{1," + str(level) + "} ").search(text, start + len(head))
    return text[start:m.start() if m else len(text)]


def _first_cell(line):
    parts = line.split("|")
    return parts[1] if len(parts) > 2 else ""


def parse_cfg_keys(contract):
    """계약 §5.2 키 표 → 키 집합. 한 칸에 '·' 로 묶인 하위 키('.ask')는 앞 키의 마지막 마디를 바꿔 펼친다."""
    keys = set()
    for line in _section(contract, "### 5.2").split("\n"):
        if not line.startswith("| `"):
            continue
        base = None
        for tok in _first_cell(line).split("·"):
            m = re.search(r"`([^`]+)`", tok)
            if not m:
                continue
            k = m.group(1).strip()
            if k.startswith("."):
                if not base:
                    continue
                k = base.rsplit(".", 1)[0] + k
            else:
                base = k
            keys.add(k)
    return keys


def parse_old_keys(contract, current):
    """계약 §5.4 왼쪽 칸의 옛 설정 키(점 포함·와일드카드 없음, 현행 키 제외)."""
    out = set()
    for line in _section(contract, "### 5.4").split("\n"):
        if not line.startswith("| ") or line.startswith(("| 명세", "|---")):
            continue
        for k in re.findall(r"`([^`]+)`", _first_cell(line)):
            k = k.strip()
            if "." in k and "*" not in k and " " not in k and k not in current:
                out.add(k)
    return out


RCODE_RE = re.compile(r"(?<![A-Za-z0-9_-])R-[A-Z]{2,}(?:-[A-Z0-9]+)*(?![A-Za-z0-9_])")


def parse_rcodes(contract):
    """계약 §6.1 → (등재 코드 집합, 폐지 코드 집합)."""
    sec = _section(contract, "### 6.1")
    reg, dep = set(), set()
    for line in sec.split("\n"):
        if line.startswith("| R-"):
            reg.update(RCODE_RE.findall(_first_cell(line)))
    for line in sec.split("\n"):
        if line.startswith("- 폐지"):
            dep.update(c for c in RCODE_RE.findall(line) if c not in reg)
    return reg, dep


def parse_path_ids(contract):
    out = set()
    for line in _section(contract, "### 6.5").split("\n"):
        m = re.match(r"\| `([a-z.]+)` \|", line)
        if m:
            out.add(m.group(1))
    return out


def parse_kinds(contract):
    for line in _section(contract, "### 3.1").split("\n"):
        if line.startswith("| `kind`"):
            cells = line.split("|")
            if len(cells) > 2:
                ks = set(re.findall(r"`([a-z_]+)`", cells[2]))
                if ks:
                    return ks
    return set()


def parse_domains(contract):
    """계약 §6.6 업무 영역 이름·색 → {코드: (이름, 색)}."""
    sec = _section(contract, "### 6.6")
    names, colors = {}, {}
    for line in sec.split("\n"):
        if line.startswith("| 업무 영역 |"):
            for code, name in re.findall(r"`([A-Z]{2,3})` ([^·|`]+)", line):
                names[code] = re.sub(r"\(.*?\)", "", name).strip()
        elif line.startswith("| 영역 색 |"):
            for code, col in re.findall(r"([A-Z]{2,3}) `(#[0-9a-fA-F]{6})`", line):
                colors[code] = col.lower()
    if not names or set(names) != set(colors):
        return None
    return {c: (names[c], colors[c]) for c in names}


def parse_team_fields(tab, privacy):
    """TAB §2.3.2 표·P §14.5 표의 최상위 필드 이름 → (TAB 집합, P 집합)."""
    def tops(sec):
        out = set()
        for line in sec.split("\n"):
            if not line.startswith("| `"):
                continue
            for tok in re.findall(r"`([^`]+)`", _first_cell(line)):
                tok = tok.strip()
                if tok.startswith("."):
                    continue
                m = re.match(r"([a-z_]+)", tok)
                if m:
                    out.add(m.group(1))
        return out
    return tops(_section(tab or "", "#### 2.3.2")), tops(_section(privacy or "", "### 14.5"))


# ───────────────────────────── 규칙 등록 ─────────────────────────────
FILE_RULES = {}   # rid -> [fn(src, ctx)]
REPO_RULES = {}   # rid -> [fn(ctx, srcs, selected)]


def file_rule(rid):
    def deco(fn):
        FILE_RULES.setdefault(rid, []).append(fn)
        return fn
    return deco


def repo_rule(rid):
    def deco(fn):
        REPO_RULES.setdefault(rid, []).append(fn)
        return fn
    return deco


# ───────────────────────────── L-01 제어문자 ─────────────────────────────
@file_rule("L-01")
def _l01(s, ctx):
    if not s.is_text:
        return
    bad = [i for i, ln in enumerate(s.lines, 1) if CTRL_RE.search(ln)]
    if bad:
        yield _f("L-01", s, bad[0], f"제어문자 {len(bad)}줄 (예: {bad[:5]}) — 이스케이프가 문자로 들어갔는지 확인"
                 "(경로 'data\\activity' → 'data<BEL>ctivity' 사고)")


# ───────────────────────────── L-02 인코딩 ─────────────────────────────
def _lone_lf(raw):
    return sum(1 for i, b in enumerate(raw) if b == 10 and (i == 0 or raw[i - 1] != 13))


def _lone_cr(raw):
    n = len(raw)
    return sum(1 for i, b in enumerate(raw) if b == 13 and (i + 1 >= n or raw[i + 1] != 10))


@file_rule("L-02")
def _l02(s, ctx):
    if not s.is_text:
        return
    raw = s.raw
    bom = raw[:3] == b"\xef\xbb\xbf"
    if s.ext == ".bat":
        if bom:
            yield _f("L-02", s, 1, "BOM 이 있습니다 — bat 은 BOM 없는 CP949 여야 합니다")
        lone = _lone_lf(raw) + _lone_cr(raw)
        if lone:
            yield _f("L-02", s, 0, f"CR·LF 단독 {lone}개 — bat 은 CRLF 여야 합니다")
        try:
            raw.decode("cp949")
        except UnicodeDecodeError as e:
            yield _f("L-02", s, 0, f"CP949 로 읽을 수 없는 바이트({e.start}) — bat 은 CP949 로 저장해야 합니다")
        lines = [ln.strip().lower() for ln in s.lines]
        while lines and not lines[-1]:
            lines.pop()
        if not lines or lines[0] != "@echo off":
            yield _f("L-02", s, 1, "첫 줄은 '@echo off' 여야 합니다")
        if len(lines) < 2 or lines[1] != ">nul chcp 949":
            yield _f("L-02", s, 2, "둘째 줄은 '>nul chcp 949' 여야 합니다")
        if not any('pushd "%temp%"' in ln for ln in lines):
            yield _f("L-02", s, 0, "pushd \"%TEMP%\" 가 없습니다 — 작업 폴더를 %TEMP% 로 옮겨 폴더 잠금을 막는다(TAB §1.9)")
        return
    if s.ext == ".ps1":
        if not bom:
            yield _f("L-02", s, 1, "UTF-8 BOM 없음 — PowerShell 5.1 이 CP949 로 오독합니다")
        lone = _lone_lf(raw) + _lone_cr(raw)
        if lone:
            yield _f("L-02", s, 0, f"CR·LF 단독 {lone}개 — ps1 은 CRLF 여야 합니다")
    else:
        if bom:
            yield _f("L-02", s, 1, f"UTF-8 BOM 이 있습니다 — {s.ext or s.name} 는 BOM 없는 UTF-8 이어야 합니다")
        crs = raw.count(b"\r")
        if crs:
            yield _f("L-02", s, 0, f"CR {crs}개 — {s.ext or s.name} 는 LF 줄끝이어야 합니다")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as e:
        yield _f("L-02", s, 0, f"UTF-8 디코드 실패({e.start}바이트)")


# ───────────────────────────── L-03 ruff ─────────────────────────────
RUFF_LINE = re.compile(r"^(.*?):(\d+):(\d+): (.*)$")


def ruff_args(ctx, paths):
    cmd = list(ctx.ruff_cmd() or [])
    args = ["check", "--no-cache", "--output-format", "concise"]
    cfg = ctx.p("ruff.toml")
    if os.path.isfile(cfg):
        args += ["--config", cfg]
    return cmd + args + list(paths)


def _run_ruff(ctx, srcs):
    out = []
    if not ctx.ruff_cmd():
        if "ruff-missing" not in ctx.once:
            ctx.once.add("ruff-missing")
            out.append(Finding("L-03", "", 0, "ruff 를 찾지 못해 건너뜀(개발 PC 관문 — python -m ruff 또는 ruff.exe)",
                               warn=True))
        return out
    by_path = {os.path.normcase(s.path): s for s in srcs}
    for i in range(0, len(srcs), 80):
        chunk = srcs[i:i + 80]
        try:
            # --config 를 주면 ruff 는 per-file-ignores·exclude 를 작업 폴더 기준으로 푼다 → 트리 루트에서 돈다
            p = subprocess.run(ruff_args(ctx, [s.path for s in chunk]), capture_output=True, timeout=180,
                               cwd=ctx.root, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            out.append(Finding("L-03", "", 0, f"ruff 실행 실패({type(e).__name__})"))
            continue
        text = (p.stdout or b"").decode("utf-8", errors="replace") + (p.stderr or b"").decode("utf-8", errors="replace")
        if p.returncode not in (0, 1):
            out.append(Finding("L-03", "", 0, "ruff 오류: " + " | ".join(text.strip().splitlines()[-3:])))
            continue
        for ln in text.splitlines():
            m = RUFF_LINE.match(ln.strip())
            if not m:
                continue
            s = by_path.get(os.path.normcase(os.path.abspath(m.group(1))))
            rel = s.rel if s else m.group(1)
            out.append(Finding("L-03", rel, int(m.group(2)), m.group(4)))
    return out


@file_rule("L-03")
def _l03(s, ctx):
    if not s.is_py:
        return
    if s.tree is None:
        yield _f("L-03", s, 0, "파이썬 구문 해석 실패 — AST 검사를 하지 못했습니다")
    if getattr(ctx, "batch_ruff", False):
        return
    yield from _run_ruff(ctx, [s])


# ───────────────────────────── L-04 zoneinfo ─────────────────────────────
@file_rule("L-04")
def _l04(s, ctx):
    if not s.is_py or s.tree is None:
        return
    seen = set()
    for n in ast.walk(s.tree):
        hit = False
        if isinstance(n, ast.ImportFrom) and n.module == "zoneinfo":
            hit = any(a.name in ("ZoneInfo", "*") for a in n.names)
        elif isinstance(n, ast.Attribute) and n.attr == "ZoneInfo":
            hit = True
        elif isinstance(n, ast.Name) and n.id == "ZoneInfo":
            hit = True
        if hit and n.lineno not in seen:
            seen.add(n.lineno)
            yield _f("L-04", s, n.lineno, "zoneinfo.ZoneInfo 금지 — 동봉 파이썬에 tzdata 없음. lm27.util.tz 를 쓰세요")


# ───────────────────────────── L-05 진입점 ─────────────────────────────
DASH_M_RE = re.compile(r"(?i)(?<![\w-])-m\s+[\"']?lm27(?![\w])")


def _is_entry(s):
    parts = s.rp.split("/")
    return s.is_py and (len(parts) == 1 or (len(parts) == 2 and parts[0] in ("tools", "collect")))


def _is_path_insert(st):
    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
        c = st.value
        if _dotted(c.func) == "sys.path.insert" and c.args and isinstance(c.args[0], ast.Constant) \
                and c.args[0].value == 0:
            return True
    if isinstance(st, ast.If):
        return any(_is_path_insert(x) for x in st.body)
    return False


def _mentions_lm27(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == "lm27":
            return True
    return False


AGENT_MAIN = "lm27/agent/main.py"   # CR-04: agent_main.py 의 저장소 원본 — bin\<ver>\agent_main.py 로 복사돼 스크립트로 돈다


def _body_no_doc(tree):
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def _is_main_guard(st):
    return isinstance(st, ast.If) and isinstance(st.test, ast.Compare) and _dotted(st.test.left) == "__name__" \
        and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in st.test.comparators)


def _imports_lm27(st):
    """최상위 문장이 lm27 를 import 하는가(상대 import 포함 — 스크립트로 돌 때는 부모 패키지가 없다)."""
    if isinstance(st, ast.Import):
        return any(a.name.split(".")[0] == "lm27" for a in st.names)
    if isinstance(st, ast.ImportFrom):
        return st.level > 0 or (st.module or "").split(".")[0] == "lm27"
    return False


def _agent_main_problem(tree):
    """CR-04 원본(lm27\\agent\\main.py)은 패키지 모듈로도 import 되고 bin 사본(agent_main.py)으로는 스크립트로 돈다.
    → 최상위 lm27 import 는 최상위 sys.path.insert(0, …) 뒤에만, 그리고 ``if __name__ == "__main__":`` 블록이 있어야 하며
    최상위 삽입이 없으면 그 블록의 첫 실행문이 sys.path.insert(0, <자기 폴더>) 여야 한다. 문제 줄 또는 None."""
    top_insert, guard = False, None
    for st in _body_no_doc(tree):
        if _is_main_guard(st):
            guard = guard or st
            continue
        if _is_path_insert(st):
            top_insert = True
            continue
        if not top_insert and _imports_lm27(st):
            return st.lineno
    if guard is None:
        return 1
    if top_insert:
        return None
    first = guard.body[0] if guard.body else guard
    return None if _is_path_insert(first) else first.lineno


def _entry_problem(tree):
    body = _body_no_doc(tree)
    for st in body:
        if _is_path_insert(st):
            return None
        if isinstance(st, ast.Import) and not any(a.name.split(".")[0] == "lm27" for a in st.names):
            continue
        if isinstance(st, ast.ImportFrom) and st.level == 0 and st.module \
                and st.module.split(".")[0] != "lm27":
            continue
        if isinstance(st, (ast.Assign, ast.AnnAssign)) and not _mentions_lm27(st):
            continue
        return st.lineno
    return 1


@file_rule("L-05")
def _l05(s, ctx):
    if not s.is_code:
        return
    if s.is_py and s.tree is not None:
        for n in ast.walk(s.tree) if not s.rule_table else ():
            if isinstance(n, (ast.List, ast.Tuple)):
                el = n.elts
                for a, b in zip(el, el[1:], strict=False):
                    if isinstance(a, ast.Constant) and a.value == "-m" and isinstance(b, ast.Constant) \
                            and isinstance(b.value, str) and re.match(r"^lm27(\.|$)", b.value):
                        yield _f("L-05", s, n.lineno, "'-m lm27' 실행 금지 — lm27_cli.py 를 스크립트로 부르세요")
        for n, v in s.str_consts() if not s.rule_table else ():
            if DASH_M_RE.search(v):
                yield _f("L-05", s, n.lineno, "'python -m lm27' 금지 — lm27_cli.py 를 스크립트로 부르세요")
        if _is_entry(s):
            ln = _entry_problem(s.tree)
            if ln is not None:
                yield _f("L-05", s, ln, "진입 스크립트는 lm27 import·실행문보다 먼저 sys.path.insert(0, ROOT) 를 해야 합니다"
                         "(python311._pth 가 스크립트 폴더를 넣지 않는다)")
        elif s.rp == AGENT_MAIN:
            ln = _agent_main_problem(s.tree)
            if ln is not None:
                yield _f("L-05", s, ln, "에이전트 진입(CR-04 원본 — bin\\<ver>\\agent_main.py 로 복사돼 스크립트로 돈다): "
                         "최상위 lm27·상대 import 금지(지연 import), if __name__ == '__main__': 블록의 첫 실행문은 "
                         "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))")
    elif not s.is_py and not s.rule_table:
        for i, ln in s.code_lines():
            if DASH_M_RE.search(ln):
                yield _f("L-05", s, i, "'python -m lm27' 금지 — lm27_cli.py 를 스크립트로 부르세요")


# ───────────────────────────── L-06 except ImportError ─────────────────────────────
IMPORT_ERRORS = ("ImportError", "ModuleNotFoundError")


def _handler_catches_import(h):
    t = h.type
    if t is None:
        return False
    elts = t.elts if isinstance(t, ast.Tuple) else [t]
    return any(_last(e) in IMPORT_ERRORS for e in elts)


def _walk_no_defs(nodes):
    stack = list(nodes)
    while stack:
        n = stack.pop()
        yield n
        for c in ast.iter_child_nodes(n):
            if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                stack.append(c)


def _handler_surfaces(h):
    for n in _walk_no_defs(h.body):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call) and _dotted(n.func) in ("sys.exit", "exit", "os._exit", "SystemExit"):
            return True
        if isinstance(n, ast.Return) and n.value is not None:
            v = n.value
            if isinstance(v, ast.Constant) and isinstance(v.value, int) and not isinstance(v.value, bool) \
                    and v.value != 0:
                return True
            nm = _last(v) if isinstance(v, (ast.Name, ast.Attribute)) else ""
            if nm and re.fullmatch(r"[A-Z][A-Z0-9_]*", nm) and nm not in ("NONE", "OK", "RC_OK"):
                return True
    return False


@file_rule("L-06")
def _l06(s, ctx):
    if not s.is_py or s.tree is None or s.is_test or s.is_doc:
        return
    for n in ast.walk(s.tree):
        if isinstance(n, ast.ExceptHandler) and _handler_catches_import(n) and not _handler_surfaces(n):
            yield _f("L-06", s, n.lineno, "except ImportError 로 기능을 조용히 삼킴 — 다시 올리거나(raise) rc≠0 으로 끝내세요")


# ───────────────────────────── L-07 최종 파일 쓰기 ─────────────────────────────
WRITE_OK = frozenset({"lm27/util/fsx.py", "lm27/store/writer.py", "lm27/bridge/fsio.py"})
TTL_OK = frozenset({"lm27/bridge/manual.py", "lm27/bridge/exchange.py", "lm27/bridge/fsio.py"})
OPEN_MODULES = frozenset({"io", "gzip", "codecs", "bz2", "lzma", "builtins", "tarfile"})
O_WRITE = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"})


def _arg(call, pos, kw):
    if len(call.args) > pos:
        return call.args[pos]
    for k in call.keywords:
        if k.arg == kw:
            return k.value
    return None


MODE_STR = re.compile(r"^[rwaxbtU+]{1,4}$")


def _mode_writes(mode):
    """open 의 mode 인자 → 쓰기인가. 없으면 읽기, 문자열 상수면 w·a·x·+ 포함 여부, 그 밖(변수·조건식·f-string 등)은
    알 수 없으므로 쓰기로 본다(fail-closed)."""
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(c in mode.value for c in "wax+")
    return True


def _write_open(call):
    """open 계열 호출이 쓰기 모드면 True(모드가 상수가 아니면 쓰기로 본다)."""
    f = call.func
    if isinstance(f, ast.Name) and f.id in ("open", "fdopen", "FileIO"):
        return _mode_writes(_arg(call, 1, "mode"))
    if isinstance(f, ast.Attribute) and f.attr in ("open", "fdopen", "FileIO"):
        base = _last(f.value) if isinstance(f.value, ast.Name) else ""
        if base == "os" and f.attr == "open":
            flags = _arg(call, 1, "flags")
            if flags is None:
                return False
            if isinstance(flags, ast.Constant):
                return isinstance(flags.value, int) and flags.value != 0
            names = [x.attr if isinstance(x, ast.Attribute) else x.id for x in ast.walk(flags)
                     if isinstance(x, (ast.Attribute, ast.Name))]
            # O_RDONLY 같은 읽기 플래그만이면 읽기, 쓰기 플래그·알 수 없는 변수면 쓰기(fail-closed)
            return any(nm in O_WRITE or not nm.startswith("O_") and nm != "os" for nm in names)
        if base in OPEN_MODULES or base == "os":
            return _mode_writes(_arg(call, 1, "mode"))
        # Path(...).open(mode) 같은 메서드 — 모드가 키워드거나 모드 모양 상수일 때만 판정(EdgeSession.open(role)·
        # webbrowser.open(url) 같은 동명 메서드를 파일 열기로 오인하지 않는다)
        kw = next((k.value for k in call.keywords if k.arg == "mode"), None)
        if kw is not None:
            return _mode_writes(kw)
        a0 = call.args[0] if call.args else None
        return isinstance(a0, ast.Constant) and isinstance(a0.value, str) and bool(MODE_STR.match(a0.value)) \
            and any(c in a0.value for c in "wax+")
    return False


# open 이 아닌 디스크 쓰기 API(L-07 — 원문이 로그·임시 파일·DB 로 새는 길)
LOG_HANDLERS = frozenset({"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler", "WatchedFileHandler"})
TEMP_FILES = frozenset({"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "mkstemp"})
SHUTIL_WRITES = frozenset({"copy", "copy2", "copyfile", "copyfileobj", "move", "copytree"})
SHUTIL_DISTINCT = frozenset({"copyfile", "copy2", "copyfileobj", "copytree"})   # from shutil import … 로 불러도 알아보는 이름


def _bytesio_names(tree):
    """io.BytesIO()·BytesIO() 를 대입받은 이름 — 메모리 안 zip 은 디스크 쓰기가 아니다."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and _last(n.value.func) == "BytesIO":
            out.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return out


def _sqlite_readonly(call):
    a0 = call.args[0] if call.args else None
    if isinstance(a0, ast.Constant) and a0.value == ":memory:":
        return True
    uri = any(k.arg == "uri" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords)
    return uri and a0 is not None and any(isinstance(x, ast.Constant) and isinstance(x.value, str) and "mode=ro" in x.value
                                          for x in ast.walk(a0))


def _other_write(call, bio):
    """open 이 아닌 쓰기 API 면 짧은 이름, 아니면 None."""
    name, last = _dotted(call.func), _last(call.func)
    if last in LOG_HANDLERS:
        return f"logging.{last}"
    if last == "basicConfig" and any(k.arg == "filename" for k in call.keywords):
        return "logging.basicConfig(filename=…)"
    if last in TEMP_FILES:
        return f"tempfile.{last}"
    if name == "os.write":
        return "os.write"
    if name == "sqlite3.connect" and not _sqlite_readonly(call):
        return "sqlite3.connect"
    if name.startswith("shutil.") and last in SHUTIL_WRITES or isinstance(call.func, ast.Name) and last in SHUTIL_DISTINCT:
        return f"shutil.{last}"
    if last == "ZipFile":
        mode = _arg(call, 1, "mode")
        a0 = call.args[0] if call.args else None
        in_mem = isinstance(a0, ast.Call) and _last(a0.func) == "BytesIO" or isinstance(a0, ast.Name) and a0.id in bio
        if mode is not None and _mode_writes(mode) and not in_mem:
            return "zipfile.ZipFile(쓰기)"
    if name in ("shelve.open", "dbm.open"):
        return name
    return None


@file_rule("L-07")
def _l07(s, ctx):
    if not s.is_py or s.tree is None or not s.is_product:
        return
    collector = s.under("lm27/collect/", "collect/")
    bio = _bytesio_names(s.tree) if s.rp not in WRITE_OK else set()
    for n in ast.walk(s.tree):
        if not isinstance(n, ast.Call):
            continue
        name = _dotted(n.func)
        last = _last(n.func)
        if s.rp not in WRITE_OK:
            wo = _write_open(n)
            other = None if wo else _other_write(n, bio)
            if wo:
                yield _f("L-07", s, n.lineno, "쓰기 모드 open(모드가 상수가 아니면 쓰기로 본다) — 최종 파일은 "
                         "lm27.util.fsx.atomic_write·append_line(증거는 lm27.store.SegmentWriter, 브리지는 fsio)만 씁니다")
            elif other:
                yield _f("L-07", s, n.lineno, f"{other} — 디스크 쓰기는 fsx.atomic_write·append_line·SegmentWriter 로만"
                         "(로그·임시 파일·DB 에도 원문 0, 계약 §1.5)")
            elif isinstance(n.func, ast.Attribute) and last in ("write_text", "write_bytes"):
                yield _f("L-07", s, n.lineno, f".{last}() 직접 쓰기 — fsx.atomic_write 를 쓰세요")
        if last == "write_text_ttl" and s.rp not in TTL_OK:
            yield _f("L-07", s, n.lineno, "write_text_ttl 호출은 bridge\\manual.py·exchange.py 에만(G-B7)")
        if collector and name in ("json.dump", "csv.writer"):
            yield _f("L-07", s, n.lineno, f"수집 경로에서 {name}( 금지 — 저장은 정제 관문(SegmentWriter)·fsx 로만(P §3.4)")


# ───────────────────────────── L-08 단일 로더 ─────────────────────────────
BUNDLE_LOADERS = frozenset(f"lm27/bundle/{m}.py" for m in
                           ("loader", "segment", "manifest", "export", "pcreg", "merge", "move"))
DATA_TOP = frozenset({"data", "out"})
PCS_SEGS = frozenset({"pcs"})
DATA_PREFIX_RE = re.compile(r"^(?:data|out)[\\/]+\w", re.I)
PCS_RE = re.compile(r"(?i)(?:^|[\\/])data[\\/]+pcs(?:[\\/]|$)")


def _path_seg0(v):
    v = v.strip().strip("\\/")
    return re.split(r"[\\/]", v, maxsplit=1)[0].lower() if v else ""


def _join_consts(n):
    """경로 조립 노드에서 문자열 상수들."""
    if isinstance(n, ast.Call):
        nm = _dotted(n.func)
        if nm.endswith("path.join") or nm in ("Path", "pathlib.Path", "PurePath", "PureWindowsPath") \
                or _last(n.func) == "joinpath":
            return [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
        return [x.value for x in (n.left, n.right) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
    return []


@repo_rule("L-08")
def _l08_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l08_file(s, ctx)


# lm27.paths.Paths 의 데이터 계열 메서드(data\·out\·store) — 그 반환값 뒤에 경로를 붙이면 '데이터 경로 조립'이다.
# 새 파일·폴더가 필요하면 paths.py 에 메서드를 더한다(CR — 계약 §2.1, 계획 §3.3).
PCS_M = frozenset({"pcs", "pc_dir", "seg_dir", "pc_json", "manifest", "manifest_prev", "move_ready", "quarantine"})
DATA_M = PCS_M | frozenset({
    "data", "bundle_json", "bundle_lock", "pc_aliases", "keys", "keyring", "secrets", "local_only", "local_only_file",
    "hier_local", "hier_local_file", "team_dir", "registry_cache", "registry_etag", "team_overrides", "outbox",
    "ai_store", "ai_run", "import_dir", "derived", "coverage_ledger", "teams_coverage", "todo", "verify_cache",
    "collect_stage_results", "stage_result_file", "blanks_file", "ai_in", "ai_out", "analysis", "analysis_current",
    "logs", "out_dir", "out_personal", "store_root", "store_dir", "store_file", "raw_cursor", "raw_cursor_lock",
    "exe_meta", "privacy_audit_file"})
PATH_CTORS = ("Path", "pathlib.Path", "PurePath", "PureWindowsPath", "WindowsPath")
# data\pcs 를 열거나·읽거나·쓰거나·나열·삭제하는 호출(인자에 PCS_M 이 들면 bundle 7모듈 밖에서는 금지)
PCS_IO_FUNCS = frozenset({"open", "read_bytes", "read_json", "read_text", "read_segment", "listdir", "scandir", "walk",
                          "atomic_write", "append_line", "remove", "unlink", "rmtree", "rename", "replace", "move",
                          "copy", "copy2", "copyfile", "copytree", "rmdir", "makedirs", "mkdir", "ensure_dir",
                          "write_segment", "iter_segment", "FileIO"})
PCS_AMBIG = frozenset({"replace", "copy", "move", "rename", "remove", "walk", "open"})   # 동명 메서드가 흔한 이름 —
# 모듈 함수(os.replace·shutil.copy·builtins open …)로 부를 때만 인자를 본다
# (str(...).replace 같은 동명 문자열 메서드와 섞이지 않게 replace 는 함수 인자로만 본다 — os.replace)
PCS_IO_METHODS = frozenset({"open", "iterdir", "glob", "rglob", "read_bytes", "read_text", "write_bytes", "write_text",
                            "unlink", "rmdir", "mkdir", "touch", "rename"})


def _data_call(node):
    """``<expr>.<m>(…)`` 꼴이고 m ∈ DATA_M 이면 m, 아니면 ''."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in DATA_M:
        return node.func.attr
    return ""


def _pathish_recv(call):
    """Paths 객체로 보이는 수신자(paths·self.paths·ctx.paths·_paths …)인가."""
    return "path" in _last(call.func.value).lower() if isinstance(call.func, ast.Attribute) else False


def _div_chain(n):
    """a / b / c 의 (가장 왼쪽 피연산자, 나머지 피연산자들)."""
    rest = []
    while isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
        rest.append(n.right)
        n = n.left
    return n, rest


def _strish(x):
    return isinstance(x, ast.JoinedStr) or isinstance(x, ast.Constant) and isinstance(x.value, str)


def _assembles_data(n, s):
    """경로 조립 노드의 가장 왼쪽이 Paths 데이터 메서드 호출이면 (메서드 이름), 아니면 ''."""
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
        par = s.parent(n)
        if isinstance(par, ast.BinOp) and isinstance(par.op, ast.Div) and par.left is n:
            return ""                                    # 사슬의 바깥 노드에서 한 번만
        left, rest = _div_chain(n)
        m = _data_call(left)
        # 수 나눗셈(stats.data() / total)과 구별: 수신자가 Paths 이거나 붙이는 쪽에 문자열이 있을 때만
        if m and (_pathish_recv(left) or any(_strish(r) for r in rest)):
            return m
        return ""
    if isinstance(n, ast.Call):
        nm = _dotted(n.func)
        if nm.endswith("path.join") or nm in PATH_CTORS:
            if len(n.args) >= 2:
                return _data_call(n.args[0])
        elif _last(n.func) == "joinpath" and isinstance(n.func, ast.Attribute):
            return _data_call(n.func.value)
    return ""


def _pcs_in(nodes):
    for root in nodes:
        for x in ast.walk(root):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in PCS_M:
                return x.func.attr
    return ""


def _pcs_io(n):
    """data\\pcs 를 여는 호출이면 그 Paths 메서드 이름, 아니면 ''."""
    if not isinstance(n, ast.Call):
        return ""
    last = _last(n.func)
    hit = ""
    modish = isinstance(n.func, ast.Name) or (isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                                              and n.func.value.id in ("os", "shutil", "fsx", "io", "gzip", "builtins"))
    if last in PCS_IO_FUNCS and (modish or last not in PCS_AMBIG):
        hit = _pcs_in(list(n.args) + [k.value for k in n.keywords])
    if not hit and isinstance(n.func, ast.Attribute) and last in PCS_IO_METHODS:
        hit = _pcs_in([n.func.value])
    return hit


def _l08_file(s, ctx):
    if not s.is_py or s.tree is None or not s.is_product or s.rule_table or s.rp == "lm27/paths.py":
        return
    loader = s.rp in BUNDLE_LOADERS
    seen = set()

    def once(line, kind):
        if (line, kind) in seen:
            return False
        seen.add((line, kind))
        return True
    for n in ast.walk(s.tree):
        for v in _join_consts(n):
            seg = _path_seg0(v)
            if seg in DATA_TOP:
                yield _f("L-08", s, n.lineno, f"데이터 경로 조립('{seg}') — 경로는 lm27.paths 로만 만듭니다(단일 로더)")
            elif seg in PCS_SEGS and not loader:
                yield _f("L-08", s, n.lineno, "data\\pcs 경로 조립 — lm27\\bundle 의 7개 모듈만(loader·segment·manifest·"
                         "export·pcreg·merge·move)")
        m = _assembles_data(n, s)
        if m and not (loader and m in PCS_M) and once(n.lineno, "join"):
            if m in PCS_M:
                yield _f("L-08", s, n.lineno, f"data\\pcs 경로 조립(paths.{m}() 뒤에 경로를 붙임) — lm27\\bundle 의 7개 "
                         "모듈만(loader·segment·manifest·export·pcreg·merge·move)")
            else:
                yield _f("L-08", s, n.lineno, f"데이터 경로 조립(paths.{m}() 뒤에 경로를 붙임) — 데이터 경로는 lm27\\paths.py "
                         "메서드로만 만듭니다(새 경로는 CR)")
        if not loader:
            p = _pcs_io(n)
            if p and once(n.lineno, "io"):
                yield _f("L-08", s, n.lineno, f"data\\pcs 열기·나열·쓰기(paths.{p}()) — lm27\\bundle 의 7개 모듈만"
                         "(단일 로더: 읽기는 loader.iter_records)")
    for n, v in s.str_consts():
        if PCS_RE.search(v) and not loader:
            yield _f("L-08", s, n.lineno, "data\\pcs 경로 문자열 — lm27\\bundle 7개 모듈·lm27.paths 만")
        elif DATA_PREFIX_RE.match(v):
            yield _f("L-08", s, n.lineno, "데이터 경로 문자열 상수 — lm27.paths 메서드를 쓰세요")


# ───────────────────────────── L-09 수집기 PS 쓰기 ─────────────────────────────
# 수집기 .ps1 의 쓰기는 대상과 무관하게 실패(fail-closed). 원문은 stdout NDJSON 으로만 나간다(P §3.4·계약 §1.5 —
# 어떤 임시 파일에도 원문 0). 예외는 아래 운영 파일(계약 X-307)과 시험 주입 -OutDir(계약 §11.3 — 기본값이 빈 값일 때만).
PS_WRITE_RE = re.compile(
    r"(?i)(?:\b(?:Out-File|Set-Content|Add-Content|Export-Csv|Export-Clixml|Start-Transcript)\b"
    r"|\bTee-Object\b(?![^|]*-Var)"
    r"|\[(?:System\.)?IO\.(?:File|StreamWriter|FileStream|BinaryWriter)\]::(?:Write\w*|Append\w*|Create\w*|OpenWrite|new)\b)")
# 인자가 따옴표 안에 있을 수 있는 것은 원래 줄로 본다
PS_NEWITEM_RE = re.compile(r"(?i)\bNew-Item\b")
PS_NEWITEM_ARG_RE = re.compile(r"(?i)-Value\b|-ItemType\s+['\"]?File\b")
PS_NEWOBJ_RE = re.compile(r"(?i)\bNew-Object\b")
PS_NEWOBJ_ARG_RE = re.compile(r"(?i)\bIO\.(?:StreamWriter|FileStream|BinaryWriter)\b")
PS_OPEN_WRITE_RE = re.compile(r"(?i)\[(?:System\.)?IO\.File\]::Open\s*\(")
PS_MODE_WRITE_RE = re.compile(r"(?i)FileMode\]?::\s*(?:Create|CreateNew|Append|Truncate|OpenOrCreate)\b|"
                              r"FileAccess\]?::\s*(?:Write|ReadWrite)\b|['\"](?:Create|CreateNew|Append|Truncate|OpenOrCreate)['\"]")
PS_HERE_WRITE_RE = re.compile(r"(?i)\bFile\.(?:Write\w*|Append\w*|Create\w*|OpenWrite)\s*\(|\bnew\s+(?:System\.IO\.)?"
                              r"(?:StreamWriter|FileStream|BinaryWriter)\s*\(")
PS_REDIR_RE = re.compile(r"(?<![\w-])(?:[1-6*])?>>?(?!&)\s*(\$null\b)?", re.I)
PS_ASSIGN_RE = re.compile(r"(?i)^\s*\$(?:script:|global:|local:)?(\w+)\s*=(?!=)\s*(.+)$")
PS_VAR_RE = re.compile(r"(?i)\$(?:script:|global:|local:)?(\w+)")
PS_OUTDIR_DEFAULT_RE = re.compile(r"(?i)\$OutDir\s*=\s*(?!['\"]{2}|\$null\b)\S")
PS_LOG_DIR = ("logs\\", "logs/", "'logs'", '"logs"')
PS_OPS_FILES = {"collect/agent/agent.ps1": ("heartbeat.json", "harvest_done.json", ".harvest.lock") + PS_LOG_DIR,
                "collect/agent/harvest.ps1": ("heartbeat.json", "harvest_done.json", ".harvest.lock") + PS_LOG_DIR,
                "collect/agent/register-agent.ps1": (".xml",),   # schtasks /XML 대체 경로의 작업 정의(원문 없음, 계약 §7.3)
                "collect/move/prepare-move.ps1": ("move_ready.json",)}


def _ps_blank(line):
    """PS 한 줄 — 따옴표 문자열 내용을 공백으로 지우고 줄 끝 주석을 뗀다(문자열 안 '>'·'#' 를 연산자로 오인하지 않게)."""
    out, i, q = [], 0, None
    while i < len(line):
        c = line[i]
        if q:
            if c == "`" and q == '"' and i + 1 < len(line):
                out.append("  ")
                i += 2
                continue
            if c == q:
                if i + 1 < len(line) and line[i + 1] == q:      # '' · "" 이스케이프
                    out.append("  ")
                    i += 2
                    continue
                q = None
                out.append(c)
            else:
                out.append(" ")
        elif c in "'\"":
            q = c
            out.append(c)
        elif c == "<" and line[i + 1:i + 2] == "#":            # 줄 안 블록 주석 <# … #>
            j = line.find("#>", i + 2)
            if j < 0:
                break
            out.append(" " * (j + 2 - i))
            i = j + 2
            continue
        elif c == "#" and (i == 0 or line[i - 1] in " \t;|"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _ps_lines(s):
    """(줄 번호, 원래 줄, 문자열 지운 줄, here-string 안인가) — 블록·줄 주석 제외."""
    here = None
    for i, ln in s.code_lines():
        t = ln.strip()
        if here:
            if t.startswith(here + "@"):
                here = None
            yield i, ln, "", True
            continue
        m = re.search(r"(?:^|(?<=[\s=(,;|]))@(['\"])\s*$", ln)   # 'a@' 같은 문자열 끝은 here-string 시작이 아니다
        if m:
            here = m.group(1)
            yield i, ln[:m.start()], _ps_blank(ln[:m.start()]), False
            continue
        yield i, ln, _ps_blank(ln), False


def _ps_tracked(lines, seeds):
    """seeds(소문자 토큰)가 든 값이나 그런 변수를 대입받은 변수 이름(소문자) 집합 — 간단한 '$v = …' 추적."""
    assigns = []
    for _i, ln, _b, here in lines:
        m = None if here else PS_ASSIGN_RE.match(ln)
        if m:
            assigns.append((m.group(1).lower(), m.group(2).lower()))
    good = set()
    for _ in range(4):
        before = len(good)
        for v, rhs in assigns:
            if any(t in rhs for t in seeds) or any(x.lower() in good for x in PS_VAR_RE.findall(rhs)):
                good.add(v)
        if len(good) == before:
            break
    return good


@file_rule("L-09")
def _l09(s, ctx):
    if s.ext not in PS_EXT or not s.under("collect/"):
        return
    ok = tuple(x.lower() for x in PS_OPS_FILES.get(s.rp.lower(), ()))
    lines = list(_ps_lines(s))
    ok_vars = _ps_tracked(lines, ok) if ok else set()
    outdir_vars = _ps_tracked(lines, ("$outdir",)) | {"outdir"}
    outdir_bad = next((i for i, ln, _b, here in lines if not here and PS_OUTDIR_DEFAULT_RE.search(ln)), None)
    for i, ln, blank, here in lines:
        if here:
            hit = PS_HERE_WRITE_RE.search(ln)
        else:
            hit = PS_WRITE_RE.search(blank) \
                or (PS_NEWITEM_RE.search(blank) and PS_NEWITEM_ARG_RE.search(ln)) \
                or (PS_NEWOBJ_RE.search(blank) and PS_NEWOBJ_ARG_RE.search(ln)) \
                or (PS_OPEN_WRITE_RE.search(blank) and PS_MODE_WRITE_RE.search(ln))
            if not hit:
                for m in PS_REDIR_RE.finditer(blank):
                    if not m.group(1):                   # > $null · 2>$null 은 버리기
                        hit = True
                        break
        if not hit:
            continue
        low = ln.lower()
        used = {x.lower() for x in PS_VAR_RE.findall(ln)}
        if ok and (any(x in low for x in ok) or used & ok_vars):
            continue
        if used & outdir_vars and outdir_bad is None:
            continue
        yield _f("L-09", s, i, "수집기 .ps1 의 디스크 쓰기 금지(Out-File·Set-Content·Add-Content·Export-*·Tee-Object·"
                 "Start-Transcript·[IO.File]::Write*·StreamWriter·리디렉션 — 대상 무관) — NDJSON 을 stdout 으로만"
                 "(예외: agent.ps1·harvest.ps1 운영 파일·Register-Agent.ps1 작업 XML·시험 주입 -OutDir)")
    if outdir_bad is not None:
        yield _f("L-09", s, outdir_bad, "시험 주입 -OutDir 에 기본값이 있습니다 — 기본은 빈 값이어야 쓰기 예외가 됩니다(계약 §11.3)")


# ───────────────────────────── L-10 수집기 import ─────────────────────────────
COLLECTOR_ALLOWED = ("lm27.store", "lm27.paths", "lm27.config", "lm27.util", "lm27.catalog", "lm27.bridge")


def _mod_ok(mod):
    if mod == "lm27.privacy.sanitize" or mod.startswith("lm27.privacy.sanitize."):
        return True
    return any(mod == a or mod.startswith(a + ".") for a in COLLECTOR_ALLOWED)


@file_rule("L-10")
def _l10(s, ctx):
    if not s.is_py or s.tree is None or not s.under("collect/"):
        return
    for n in ast.walk(s.tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] == "lm27" and not _mod_ok(a.name):
                    yield _f("L-10", s, n.lineno, f"수집기 import 금지 '{a.name}' — lm27.privacy 는 sanitize 만, 그 밖은 "
                             "store·paths·config·util·catalog·bridge")
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and n.module.split(".")[0] == "lm27":
            mod = n.module
            if mod == "lm27.privacy":
                bad = [a.name for a in n.names if a.name != "sanitize"]
            elif mod == "lm27":
                bad = [a.name for a in n.names if not _mod_ok("lm27." + a.name)]
            else:
                bad = [] if _mod_ok(mod) else [a.name for a in n.names]
            if bad:
                yield _f("L-10", s, n.lineno, f"수집기 import 금지 'from {mod} import {', '.join(bad)}' — "
                         "정제는 lm27.privacy.sanitize 한 모듈만")


# ───────────────────────────── L-11 저장 경로 우회 ─────────────────────────────
SEAL_OK = frozenset({"lm27/privacy/records.py", "lm27/store/writer.py"})
# 로컬 원장(store)·감사·수집 커서 경로 — 그 경로를 아는 것은 store·privacy·paths 뿐(SegmentWriter 를 건너뛴 쓰기 방지)
STORE_PATH_M = frozenset({"store_file", "store_dir", "store_root", "privacy_audit_file", "raw_cursor", "raw_cursor_lock"})
ROW_NAME_RE = re.compile(r"(?i)^(?:\w+_)?s?row\d*$|^sanitized\w*$")
# 봉인 행은 정제~SegmentWriter 사이에만 있다 — 저장된 dict 행만 읽는 분석·표시 층은 행 변경 검사에서 뺀다
ROW_SCOPE_SKIP = ("lm27/time/", "lm27/hier/", "lm27/report/", "lm27/ui/", "lm27/team/", "lm27/vocab/")
ROW_COPY_CALLS = frozenset({"dataclasses.replace", "copy.copy", "copy.deepcopy", "object.__new__", "object.__setattr__",
                            "object.__delattr__"})
ROW_MUTATORS = frozenset({"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"})


def _rowish(node):
    """봉인 행으로 보이는 표현(row·*_row·x.row·SanitizedRow 이름)."""
    nm = _last(node)
    return bool(nm) and (bool(ROW_NAME_RE.match(nm)) or nm == "SanitizedRow")


def _row_data_target(node):
    """row.data[…] · row.data · row.__dict__[…] · vars(row)[…] 꼴이면 True."""
    while isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute) and node.attr in ("data", "__dict__") and _rowish(node.value):
        return True
    return isinstance(node, ast.Call) and _last(node.func) == "vars" and node.args and _rowish(node.args[0])


def _seal_bypass(n, from_dc):
    """봉인 행 위조·변경이면 짧은 설명, 아니면 None."""
    if isinstance(n, ast.Call):
        name = _dotted(n.func)
        if isinstance(n.func, ast.Name) and n.func.id in from_dc:
            name = "dataclasses.replace"
        a0 = n.args[0] if n.args else None
        if name in ROW_COPY_CALLS and a0 is not None and _rowish(a0):
            return f"{name}(행)"
        if isinstance(n.func, ast.Attribute) and n.func.attr in ROW_MUTATORS and _row_data_target(n.func.value):
            return f"행.data.{n.func.attr}("
        if _last(n.func) == "__replace__" and isinstance(n.func, ast.Attribute) and _rowish(n.func.value):
            return "행.__replace__("
    elif isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
        tg = n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]
        for t in tg:
            if _row_data_target(t) or (isinstance(t, ast.Attribute) and _rowish(t.value) and t.attr in ("data", "_seal")):
                return "행.data 변경"
    return None


@file_rule("L-11")
def _l11(s, ctx):
    if not s.is_py or s.tree is None or not s.is_product:
        return
    seal_ok = s.rp in SEAL_OK
    store_ok = s.under("lm27/store/", "lm27/privacy/") or s.rp == "lm27/paths.py"
    from_dc = {a.asname or a.name for n in ast.walk(s.tree) if isinstance(n, ast.ImportFrom) and n.module == "dataclasses"
               for a in n.names if a.name == "replace"}
    for n in ast.walk(s.tree):
        if isinstance(n, ast.Call) and _last(n.func) == "SanitizedRow" and s.rp != "lm27/privacy/records.py":
            yield _f("L-11", s, n.lineno, "SanitizedRow 생성은 lm27\\privacy\\records.py 안에서만(봉인)")
        elif isinstance(n, (ast.Name, ast.Attribute)) and _last(n) == "_SEAL" and not seal_ok:
            yield _f("L-11", s, n.lineno, "_SEAL 외부 참조 — 봉인 토큰은 records.py(와 writer.py 의 봉인 검사)만")
        elif isinstance(n, ast.Call) and _last(n.func) in STORE_PATH_M and isinstance(n.func, ast.Attribute) \
                and not store_ok:
            yield _f("L-11", s, n.lineno, f"{n.func.attr}() 경로 직접 사용 — 로컬 원장·감사·수집 커서는 lm27.store"
                     "(SegmentWriter·read_store_since·cursor)·lm27.privacy 로만")
        elif not seal_ok and not s.under(*ROW_SCOPE_SKIP):
            why = _seal_bypass(n, from_dc)
            if why:
                yield _f("L-11", s, getattr(n, "lineno", 0), f"봉인 행 위조·변경({why}) — 정제 뒤 행은 바꾸지 않습니다. "
                         "새 값이 필요하면 records.py 의 정제 함수로 다시 만듭니다(P I2)")


# ───────────────────────────── L-12 설정 키 ─────────────────────────────
CFG_SHAPE = re.compile(r"^[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_]+)+$")
CAMEL_KEY = re.compile(r"^[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$")
FILE_EXT_TAIL = re.compile(r"\.(?:json|jsonl|gz|txt|csv|py|ps1|bat|html|js|css|svg|lock|log|exe|dll|md|toml|xml|zip)$",
                           re.I)
OWNER_SPLIT = re.compile(r"[\s,;·|()+]+")
MOD_TOKEN = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+$")
SCRIPT_TOKEN = re.compile(r"^(?:[A-Za-z0-9_\\/.-]*[\\/])?([A-Z][A-Za-z0-9]*-[A-Za-z0-9]+|[A-Za-z0-9_]+)\.(ps1|py)$|"
                          r"^([A-Z][a-z]+-[A-Z][A-Za-z0-9]+)$")


def _looks_cfg(ctx, k):
    if not CFG_SHAPE.match(k) or FILE_EXT_TAIL.search(k) or k in ctx.path_ids:
        return False
    ns = k.split(".", 1)[0]
    return ns in ctx.cfg_namespaces or k in ctx.old_keys


def _cfg_scan(ctx, srcs):
    """제품 코드에서 (직접 읽기 [(src, line, key)], 증거 상수 집합, 접두 읽기 집합)."""
    def scan():
        direct, consts, prefixes = [], set(), set()
        for s in srcs:
            if not s.is_product or s.rule_table:
                continue
            if s.is_py and s.tree is not None:
                for n in ast.walk(s.tree):
                    key = None
                    if isinstance(n, ast.Subscript):
                        sl = n.slice
                        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                            key = sl.value
                    elif isinstance(n, ast.Call) and _last(n.func) == "get" and n.args \
                            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                        key = n.args[0].value
                    if key is not None and _looks_cfg(ctx, key):
                        direct.append((s, n.lineno, key))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str):
                        consts.add(n.value)
                    elif isinstance(n, ast.JoinedStr) and n.values and isinstance(n.values[0], ast.Constant) \
                            and isinstance(n.values[0].value, str):
                        prefixes.add(n.values[0].value)
                    elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and isinstance(n.left, ast.Constant) \
                            and isinstance(n.left.value, str) and n.left.value.endswith("."):
                        prefixes.add(n.left.value)
                    elif isinstance(n, ast.Call) and _last(n.func) == "startswith" and n.args \
                            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) \
                            and n.args[0].value.endswith("."):
                        prefixes.add(n.args[0].value)
            elif s.ext in (".ps1", ".js"):
                consts.update(re.findall(r"""['"]([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+)['"]""", s.text))
        prefixes = {p for p in prefixes if p and "." in p and p.split(".", 1)[0] in ctx.cfg_namespaces}
        return direct, consts, prefixes
    return ctx.memo("cfg_scan", scan)


def _owner_tokens(meta):
    o = meta.get("owner") if isinstance(meta, dict) else None
    if isinstance(o, list):
        toks = []
        for x in o:
            if isinstance(x, str):
                toks += OWNER_SPLIT.split(x)
        return [t for t in toks if t]
    if isinstance(o, str):
        return [t for t in OWNER_SPLIT.split(o) if t]
    return []


def _owner_exists(ctx, tok):
    """None = 해석 불가 토큰, True/False = 그 모듈·스크립트 파일이 트리에 있는가."""
    tok = tok.strip().strip("`'\"")
    return ctx.memo("owner:" + tok, lambda: _owner_lookup(ctx, tok))


def _owner_lookup(ctx, tok):
    if re.search(r"\.(?:ps1|py)$", tok) and re.search(r"[\\/]", tok):
        return os.path.isfile(ctx.p(*[x for x in re.split(r"[\\/]", tok) if x]))
    m = SCRIPT_TOKEN.match(tok)
    if m:
        stem = m.group(1) or m.group(3)
        for _dp, _dn, fns in os.walk(ctx.p("collect")):
            for fn in fns:
                if os.path.splitext(fn)[0].lower() == stem.lower() and fn.lower().endswith((".ps1", ".py")):
                    return True
        return os.path.isfile(ctx.p("tools", stem + ".py")) or os.path.isfile(ctx.p(stem + ".py"))
    if MOD_TOKEN.match(tok):
        parts = tok.split(".")
        if parts[0] != "lm27":
            parts = ["lm27"] + parts
        if os.path.isfile(ctx.p(*parts[:-1], parts[-1] + ".py")) or os.path.isfile(ctx.p(*parts, "__init__.py")):
            return True
        if len(parts) > 2 and os.path.isfile(ctx.p(*parts[:-2], parts[-2] + ".py")):
            return True
        return False
    return None


def l12_problems(ctx, srcs, only_ns=None):
    """(오류 [Finding], 경고 [Finding]) — only_ns 가 있으면 그 네임스페이스만(G-B3)."""
    errs, warns = [], []
    rule = "L-17" if only_ns else "L-12"

    def inns(k):
        return only_ns is None or k.split(".", 1)[0] == only_ns
    if not ctx.contract:
        errs.append(Finding(rule, "docs/CONTRACT.md", 0, "계약 문서가 없어 §5.2 키 표를 읽을 수 없음"))
        return errs, warns
    table = ctx.cfg_keys
    reg, rerr = ctx.registry()
    if rerr:
        errs.append(Finding(rule, "config/settings_registry.json", 0, rerr))
    known = set(reg) if reg else set(table)
    rel_reg = "config\\settings_registry.json"
    if reg is not None:
        miss = sorted(k for k in table - set(reg) if inns(k))
        extra = sorted(k for k in set(reg) - table if inns(k))
        if miss:
            errs.append(Finding(rule, rel_reg, 0, f"§5.2 표에 있는데 레지스트리에 없는 키 {len(miss)}개(예: {miss[:5]})"))
        if extra:
            errs.append(Finding(rule, rel_reg, 0, f"§5.2 표에 없는 레지스트리 키 {len(extra)}개(예: {extra[:5]})"))
        snake = sorted(k for k in reg if inns(k) and not CAMEL_KEY.match(k))
        if snake:
            errs.append(Finding(rule, rel_reg, 0, f"camelCase 가 아닌 키(snake_case 등) {len(snake)}개(예: {snake[:5]})"))
        old = sorted(k for k in reg if inns(k) and k in ctx.old_keys)
        if old:
            errs.append(Finding(rule, rel_reg, 0, f"§5.4 옛 이름 키 {len(old)}개(예: {old[:5]})"))
    elif not rerr:
        warns.append(Finding(rule, rel_reg, 0, "레지스트리가 아직 없음 — 코드 읽기는 §5.2 표로만 대조, 죽은 키 검사 건너뜀",
                             warn=True))
    direct, consts, prefixes = _cfg_scan(ctx, srcs)
    for s, ln, k in direct:
        if not inns(k):
            continue
        if k in ctx.old_keys:
            errs.append(_f(rule, s, ln, f"폐지된 설정 키 '{k}' — 계약 §5.4 의 정본 이름을 쓰세요"))
        elif k not in known:
            errs.append(_f(rule, s, ln, f"미등록 설정 키 '{k}' — 레지스트리에 없는 키는 읽지 못합니다(새 키는 CR)"))
        elif not CAMEL_KEY.match(k):
            errs.append(_f(rule, s, ln, f"snake_case 설정 키 '{k}'"))
    if reg:
        dead_err, dead_warn = [], []
        for k, meta in sorted(reg.items()):
            if not inns(k) or k in consts or any(k.startswith(p) for p in prefixes):
                continue
            res = [r for r in (_owner_exists(ctx, t) for t in _owner_tokens(meta)) if r is not None]
            if ctx.l12_full or (res and all(res)):
                dead_err.append(k)
            else:
                dead_warn.append(k)
        for k in dead_err:
            errs.append(Finding(rule, rel_reg, 0, f"죽은 키 '{k}' — 읽는 모듈(owner)이 있는데 코드에서 읽히지 않습니다"))
        if dead_warn:
            warns.append(Finding(rule, rel_reg, 0, f"아직 읽히지 않는 키 {len(dead_warn)}개 — owner 모듈 미생성이라 경고만"
                                 f"(CR-05, W2 통합 창부터 --l12-full 로 실패). 예: {dead_warn[:3]}", warn=True))
    return errs, warns


@repo_rule("L-12")
def _l12_repo(ctx, srcs, selected):
    e, w = l12_problems(ctx, srcs)
    yield from e
    yield from w


# ───────────────────────────── L-13 사유 코드 ─────────────────────────────
@repo_rule("L-13")
def _l13_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l13_file(s, ctx)


def _l13_file(s, ctx):
    if not s.is_text or s.rule_table:
        return
    reg, dep = ctx.rcodes
    if not reg:
        if "L-13:contract" not in ctx.once:
            ctx.once.add("L-13:contract")
            yield Finding("L-13", "docs/CONTRACT.md", 0, "계약 §6.1 사유 코드 표를 읽지 못함(문서 없음·해석 실패)")
        return
    text = s.text
    for m in RCODE_RE.finditer(text):
        code = m.group(0)
        if code in reg:
            continue
        if text[m.end():m.end() + 2] == "-*" and any(c.startswith(code + "-") for c in reg):
            continue
        if s.is_doc and code in dep:
            continue
        why = "폐지된 사유 코드" if code in dep else "계약 §6.1 에 없는 사유 코드"
        yield _f("L-13", s, _line_of(text, m.start()), f"{why} '{code}' — 새 코드는 §6.1 에 먼저 등재(CR)")


# ───────────────────────────── L-14 경로 ID·kind ─────────────────────────────
PATH_ID_SHAPE = re.compile(r"^(?:mail|cal|teams|pc)\.[a-z]{2,10}$")
KIND_SHAPE = re.compile(r"^(?:pc_[a-z_]+|mails?|cals?|calendar|e?mail|teams?|teams_[a-z_]+|manuals?|privacy_audit)$")
KINDS_NAME = re.compile(r"^_?(?:[A-Z0-9]+_)*KINDS$")
KIND_IDENT = ("kind", "_kind")


def _kind_ctx(node):
    if isinstance(node, ast.Name):
        return node.id in KIND_IDENT
    if isinstance(node, ast.Attribute):
        return node.attr in KIND_IDENT
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value in KIND_IDENT
    return False


def _str_elems(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if isinstance(node, ast.Call) and _last(node.func) in ("frozenset", "set", "tuple", "list") and node.args:
        return _str_elems(node.args[0])
    if isinstance(node, ast.Dict):
        return [k for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return []


@repo_rule("L-14")
def _l14_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l14_file(s, ctx)


def _l14_file(s, ctx):
    if not s.is_code or not s.is_product or s.rule_table:
        return
    pids, kinds = ctx.path_ids, ctx.kinds | {"privacy_audit"}
    if s.is_py and s.tree is not None:
        for n, v in s.str_consts():
            if PATH_ID_SHAPE.match(v) and v not in pids and not FILE_EXT_TAIL.search(v):
                yield _f("L-14", s, n.lineno, f"계약 §6.5 에 없는 경로 ID '{v}'")
        for n in ast.walk(s.tree):
            cands = []
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                tg = n.targets if isinstance(n, ast.Assign) else [n.target]
                if any(isinstance(t, ast.Name) and KINDS_NAME.match(t.id) for t in tg) and n.value is not None:
                    els = _str_elems(n.value)
                    if any(e.value in kinds for e in els):      # 증거 kind 표일 때만(STOP_KINDS 등 다른 열거 제외)
                        for e in els:
                            if e.value not in kinds:
                                yield _f("L-14", s, e.lineno, f"kind 상수 표에 계약 §3.1 밖 값 '{e.value}'")
            elif isinstance(n, ast.Compare):
                sides = [n.left] + list(n.comparators)
                if any(_kind_ctx(x) for x in sides):
                    for x in sides:
                        cands += _str_elems(x)
            elif isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values, strict=True):
                    if isinstance(k, ast.Constant) and k.value in KIND_IDENT:
                        cands += _str_elems(v)
            elif isinstance(n, ast.keyword) and n.arg in KIND_IDENT:
                cands += _str_elems(n.value)
            for e in cands:
                if KIND_SHAPE.match(e.value) and e.value not in kinds:
                    yield _f("L-14", s, e.lineno, f"계약 §3.1 에 없는 kind '{e.value}'")
    elif not s.is_py:
        for i, ln in s.code_lines():
            for v in re.findall(r"""['"]((?:mail|cal|teams|pc)\.[a-z]{2,10})['"]""", ln):
                if v not in pids and not FILE_EXT_TAIL.search(v):
                    yield _f("L-14", s, i, f"계약 §6.5 에 없는 경로 ID '{v}'")
            for v in re.findall(r"""(?i)--src\s+['"]?([a-z][a-z.]*)""", ln):
                if v not in pids:
                    yield _f("L-14", s, i, f"계약 §6.5 에 없는 경로 ID '{v}'")
            for v in re.findall(r"""(?:--kind\s+|['"]?_kind['"]?\s*[:=]\s*)['"]?([a-z][a-z_]*)""", ln):
                if v not in kinds:
                    yield _f("L-14", s, i, f"계약 §3.1 에 없는 kind '{v}'")


# ───────────────────────────── L-15 작업·뮤텍스 이름 ─────────────────────────────
TASK_CONST = re.compile(r"^(?:(?:Local|Global)\\)?LM27-[A-Za-z0-9]")
TASK_TEXT = re.compile(r"(?<![\w-])LM27-(?![\$\{<(\[`'\"\s]|$)[A-Za-z0-9]")
XML_ROOT = re.compile(r"(?:lm27_cli|PSScriptRoot|\$Root\b|\bROOT\b)")


@repo_rule("L-15")
def _l15_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l15_file(s, ctx)


def _l15_file(s, ctx):
    if not s.is_code or s.is_doc or s.rule_table:
        return
    why_t = "시험 작업 이름은 'LM27T-' 접두" if s.is_test else "작업·뮤텍스 이름은 'LM27-<install_id>'(판 공통 이름 금지)"
    if s.is_py and s.tree is not None:
        for n, v in s.str_consts():
            if isinstance(s.parent(n), ast.JoinedStr):
                continue
            if TASK_CONST.match(v):
                yield _f("L-15", s, n.lineno, f"고정 작업·뮤텍스 이름 '{v[:40]}' — {why_t}")
    elif not s.is_py:
        for i, ln in s.code_lines():
            if TASK_TEXT.search(ln):
                yield _f("L-15", s, i, f"고정 작업·뮤텍스 이름 — {why_t}")
    if s.is_product:
        for i, ln in s.code_lines():
            if re.search(r"WorkingDirectory|<Command>|<Arguments>", ln) and XML_ROOT.search(ln):
                yield _f("L-15", s, i, "작업 XML 의 Action·WorkingDirectory 가 ROOT 를 가리킴 — 에이전트 bin 사본·agent\\ 폴더만")


# ───────────────────────────── L-16 Edge·os.kill ─────────────────────────────
EDGE_FLAGS = ("--user-data-dir", "--remote-debugging-port")
EDGE_KEYS = ("bridge.edge.profileDir", "bridge.edge.port", "bridge.edge.portTries")
ALLOW_ALL_ORIGINS = "--remote-allow-origins=" + "*"


@file_rule("L-16")
def _l16(s, ctx):
    if not s.is_code or not s.is_product or s.rule_table:
        return
    in_bridge = s.under("lm27/bridge/")
    items = [(n.lineno, v) for n, v in s.str_consts()] if s.is_py else list(s.code_lines())
    for i, ln in items:
        if ALLOW_ALL_ORIGINS in ln:
            yield _f("L-16", s, i, "--remote-allow-origins=* 금지(B §4.4 — Origin 없이, 403 이면 127.0.0.1 만)")
        if "office.com" in ln.lower():
            yield _f("L-16", s, i, "'office.com' 부분 문자열 호스트 금지(G-B9)")
        if not in_bridge:
            for fl in EDGE_FLAGS + EDGE_KEYS:
                if fl in ln:
                    yield _f("L-16", s, i, f"'{fl}' 는 lm27\\bridge\\ 밖에 둘 수 없습니다 — EdgeSession.open(role=…) 경유(G-B12)")
        if not s.is_py and re.search(r"\bos\.kill\(", ln):
            yield _f("L-16", s, i, "os.kill 금지 — lm27.util.proc.kill_tree")
    if s.is_py and s.tree is not None:
        for n in ast.walk(s.tree):
            if isinstance(n, ast.Call) and _dotted(n.func) == "os.kill":
                yield _f("L-16", s, n.lineno, "os.kill 금지 — lm27.util.proc.kill_tree(taskkill /T /F)")


# ───────────────────────────── L-17 브리지 ─────────────────────────────
GB2_NUMS = frozenset({9000, 8400, 8300, 8000, 7000, 5500, 5000, 900, 480, 180})
TIME_CALLS = ("time.sleep", "time.time", "time.monotonic")


def _l17_file(s, ctx):
    if not s.is_py or s.tree is None or not s.under("lm27/bridge/"):
        return
    clock = s.rp == "lm27/bridge/clock.py"
    settings = s.rp == "lm27/bridge/settings.py"
    for n in ast.walk(s.tree):
        if not clock:
            if isinstance(n, ast.Import) and any(a.name == "time" for a in n.names):
                yield _f("L-17", s, n.lineno, "브리지에서 import time 은 clock.py 에만(G-B1 시계 주입)")
            elif isinstance(n, ast.ImportFrom) and n.module == "time":
                yield _f("L-17", s, n.lineno, "브리지에서 from time import 는 clock.py 에만(G-B1)")
            elif isinstance(n, ast.Call) and _dotted(n.func) in TIME_CALLS:
                yield _f("L-17", s, n.lineno, f"{_dotted(n.func)}( 는 clock.py 에만(G-B1)")
        if not settings and isinstance(n, ast.Constant) and type(n.value) in (int, float) \
                and n.value in GB2_NUMS:
            line = s.lines[n.lineno - 1] if n.lineno - 1 < len(s.lines) else ""
            if "noqa: G-B2" not in line:
                yield _f("L-17", s, n.lineno, f"한도 숫자 {n.value} 는 bridge\\settings.py 에만(G-B2, 예외는 '# noqa: G-B2')")


@repo_rule("L-17")
def _l17_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l17_file(s, ctx)
    if "L-12" not in selected and os.path.isdir(ctx.p("lm27", "bridge")):
        e, w = l12_problems(ctx, srcs, only_ns="bridge")
        yield from e
        yield from w


# ───────────────────────────── L-18 시간 미전송 ─────────────────────────────
TIME_KEY_RE = re.compile(
    r"(?i)^(?:ts|t0|t1|date|dates|day|days|month|months|week|weeks|time|times|hour|hours|minute|minutes|min|mins|"
    r"sec|secs|second|seconds|mm|duration|start|end|effort|lead|wd|when|at)(?:_|$)|"
    r"(?:^|_)(?:utc|ts|date|day|days|time|hours?|h|min|mins|minutes|sec|secs|seconds|mm|wd|at|start|end|"
    r"duration|effort)$")
TIME_TEXT_RE = re.compile(r"\d+(\.\d+)?\s*(MM|M/M|시간|h)\b")


def _send_field_nodes(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.keyword) and n.arg == "send_fields":
            yield n.value
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            tg = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(_last(t).lower() == "send_fields" for t in tg) and n.value is not None:
                yield n.value
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "send_fields":
                    yield v


@file_rule("L-18")
def _l18(s, ctx):
    if not s.is_py or s.tree is None or not s.under("lm27/"):
        return
    for node in _send_field_nodes(s.tree):
        for e in _str_elems(node):
            if TIME_KEY_RE.search(e.value):
                yield _f("L-18", s, e.lineno, f"send_fields 에 시간형 키 '{e.value}' — 코파일럿에 시간 정보를 보내지 않습니다(B1)")
    if s.under("lm27/bridge/stages/") or "prompt" in s.name.lower():
        for n, v in s.str_consts():
            m = TIME_TEXT_RE.search(v)
            if m:
                yield _f("L-18", s, n.lineno, f"프롬프트 템플릿에 시간 수치 '{m.group(0)}' — 시간·MM 은 보내지 않습니다(G-B8)")


# ───────────────────────────── L-19 화면 ─────────────────────────────
JS_BANNED = (("innerHTML", r"\binnerHTML\b"), ("outerHTML", r"\bouterHTML\b"),
             ("insertAdjacentHTML", r"\binsertAdjacentHTML\b"), ("document.write", r"\bdocument\.write(?:ln)?\b"),
             ("eval(", r"(?<![\w.])eval\s*\("), ("new Function", r"\bnew\s+Function\b"),
             ("setTimeout(문자열", r"\bset(?:Timeout|Interval)\s*\(\s*['\"`]"), ("DOMParser", r"\bDOMParser\b"),
             ("toFixed(", r"\.toFixed\s*\("))
HEX_RE = re.compile(r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
EXT_URL_RE = re.compile(r"(?i)https?://(?!www\.w3\.org/|127\.0\.0\.1|localhost)[\w.-]+")
EXT_REF_RE = re.compile(r"(?i)(?:url\(\s*['\"]?(?:https?:)?//|(?:src|href)\s*=\s*['\"](?:https?:)?//|@font-face|@import)")
HTML_TAG_RE = re.compile(r"(?i)<\s*/?\s*(?:html|head|body|div|span|table|thead|tbody|tr|td|th|script|style|svg|p|a|li|ul|"
                         r"ol|h[1-6]|meta|link|title|section|header|footer|main|button|input|form|img|br|g|path|rect|text|"
                         r"tspan|line|circle|polyline|polygon|label|select|option|textarea|nav|details|summary|pre|code|"
                         r"em|strong|small|b|i)\b")
NUM_NAME_RE = re.compile(r"(?i)(?:^|_)(?:min|mins|minutes|sec|secs|seconds|mm|effort|hours)$")
HTML_PY_SCOPE = ("lm27/report/", "lm27/ui/")
HTML_PY_EXEMPT = frozenset({"lm27/report/export.py", "lm27/team/report.py"})


def _numberish(n):
    if isinstance(n, ast.Constant) and type(n.value) in (int, float):
        return True
    nm = _last(n)
    if not nm and isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
        nm = n.slice.value
    return bool(nm) and bool(NUM_NAME_RE.search(nm))


@file_rule("L-19")
def _l19(s, ctx):
    if s.rule_table:
        return
    if s.under("web/") and s.ext in WEB_EXT:
        css_ok = s.rp == "web/common/lm27.css"
        for i, ln in s.code_lines():
            if s.ext in (".js", ".html"):
                for label, pat in JS_BANNED:
                    if re.search(pat, ln):
                        yield _f("L-19", s, i, f"위험 API '{label}' 금지 — textContent·createElementNS·lm27ui.fmt*(G-R4·G-R11)")
            if not css_ok and HEX_RE.search(ln):
                yield _f("L-19", s, i, "16진 색은 web\\common\\lm27.css·DOMAIN_META 에만(G-R7)")
            if EXT_URL_RE.search(ln) or EXT_REF_RE.search(ln):
                yield _f("L-19", s, i, "외부 참조(http·CDN·웹 글꼴) 금지(G-R5)")
            if s.ext in (".js", ".css") and re.search(r"(?i)</(?:script|style)", ln):
                yield _f("L-19", s, i, "인라인될 JS·CSS 에 '</script'·'</style' 금지(G-R6 데이터 섬)")
        return
    if not s.is_py or s.tree is None or not s.is_product:
        return
    report = s.under("lm27/report/")
    html_scope = s.under(*HTML_PY_SCOPE) or s.rp == "lm27/team/report.py"
    hex_scope = html_scope or s.under("lm27/team/", "lm27/hier/")
    for n in ast.walk(s.tree):
        if hex_scope and s.rp != "lm27/hier/vocab.py" and isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and not s.is_docstring(n) and HEX_RE.search(n.value):
            yield _f("L-19", s, n.lineno, "16진 색 하드코딩 — lm27.css 토큰·DOMAIN_META 를 쓰세요(G-R7)")
        if html_scope and isinstance(n, ast.Constant) and isinstance(n.value, str) and EXT_URL_RE.search(n.value):
            yield _f("L-19", s, n.lineno, "보고서·화면에 외부 URL 금지(G-R5)")
        if html_scope and s.rp not in HTML_PY_EXEMPT:
            bad = False
            if isinstance(n, ast.JoinedStr) and any(isinstance(v, ast.FormattedValue) for v in n.values):
                bad = any(isinstance(v, ast.Constant) and isinstance(v.value, str) and HTML_TAG_RE.search(v.value)
                          for v in n.values)
            elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod) and isinstance(n.left, ast.Constant) \
                    and isinstance(n.left.value, str) and HTML_TAG_RE.search(n.left.value):
                bad = True
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format" \
                    and isinstance(n.func.value, ast.Constant) and isinstance(n.func.value.value, str) \
                    and HTML_TAG_RE.search(n.func.value.value):
                bad = True
            if bad:
                yield _f("L-19", s, n.lineno, "HTML 문자열에 값 직접 결합(f-string·%·format) 금지 — 섬 삽입 함수만(G-R4)")
        if report and s.rp != "lm27/report/fmt.py":
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "round":
                yield _f("L-19", s, n.lineno, "round( 는 lm27\\report\\fmt.py 안에서만(G-R11)")
            elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and (_numberish(n.left) or _numberish(n.right)):
                yield _f("L-19", s, n.lineno, "분·MM 나눗셈은 lm27\\report\\fmt.py 안에서만(RP1·G-R11)")


@repo_rule("L-19")
def _l19_repo(ctx, srcs, selected):
    vp = ctx.p("lm27", "hier", "vocab.py")
    if os.path.isfile(vp):
        s = next((x for x in srcs if x.rp == "lm27/hier/vocab.py"), None) or Src(ctx.root, vp)
        yield from _domain_meta_check(ctx, s)
    cc = ctx.p("tools", "check_contrast.py")
    if os.path.isfile(cc):
        rc, out, err = ctx.run_py(f"import runpy, sys; sys.argv=[{cc!r}]; runpy.run_path({cc!r}, run_name='__main__')",
                                  timeout=120)
        if rc != 0:
            tail = " | ".join((out + err).strip().splitlines()[-3:])
            yield Finding("L-19", "tools\\check_contrast.py", 0, f"색·대비 관문 실패(rc {rc}, G-R7): {tail[:300]}")


def _domain_meta_check(ctx, s):
    tree = s.tree
    if tree is None:
        yield _f("L-19", s, 0, "vocab.py 구문 해석 실패 — DOMAIN_META 를 대조하지 못함")
        return
    node = None
    for n in tree.body:
        tg = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "DOMAIN_META" for t in tg):
            node = n.value
    if node is None:
        yield _f("L-19", s, 0, "DOMAIN_META 가 vocab.py 에 없음(계약 §2.10)")
        return
    if not isinstance(node, ast.Dict):
        yield _f("L-19", s, getattr(node, "lineno", 0), "DOMAIN_META 가 사전 리터럴이 아니라 색을 대조하지 못함", warn=True)
        return
    want = {c: col for c, (_n, col) in ctx.domains.items()}
    got = {}
    for k, v in zip(node.keys, node.values, strict=True):
        if isinstance(k, ast.Constant) and isinstance(v, ast.Dict):
            for kk, vv in zip(v.keys, v.values, strict=True):
                if isinstance(kk, ast.Constant) and kk.value == "color" and isinstance(vv, ast.Constant):
                    got[k.value] = str(vv.value).lower()
    for code, col in want.items():
        if got.get(code) != col:
            yield _f("L-19", s, node.lineno, f"DOMAIN_META['{code}'] 색이 계약 §6.6 값({col})과 다름: {got.get(code)}")


# ───────────────────────────── L-20 서버 재사용 ─────────────────────────────
SERVER_CLASSES = ("HTTPServer", "ThreadingHTTPServer", "TCPServer", "ThreadingTCPServer")


@file_rule("L-20")
def _l20(s, ctx):
    if not s.is_py or s.tree is None or not s.is_product:
        return
    for n in ast.walk(s.tree):
        if isinstance(n, (ast.Name, ast.Attribute)) and _last(n) == "SO_REUSEADDR":
            yield _f("L-20", s, n.lineno, "SO_REUSEADDR 금지 — SO_EXCLUSIVEADDRUSE(덧바인드 방지)")
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            tg = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(_last(t) == "allow_reuse_address" for t in tg) and isinstance(n.value, ast.Constant) \
                    and n.value.value:
                yield _f("L-20", s, n.lineno, "allow_reuse_address=True 금지(계약 §10.4)")
        elif isinstance(n, ast.ClassDef) and any(_last(b).endswith(("HTTPServer", "TCPServer")) for b in n.bases):
            off = any(isinstance(st, ast.Assign) and any(_last(t) == "allow_reuse_address" for t in st.targets)
                      and isinstance(st.value, ast.Constant) and not st.value.value for st in n.body)
            if not off:
                yield _f("L-20", s, n.lineno, f"서버 클래스 {n.name} 에 allow_reuse_address = False 가 없음"
                         "(기본값 1 이면 덧바인드 성공 — 실측)")
        elif isinstance(n, ast.Call) and _last(n.func) in SERVER_CLASSES:
            if not any(k.arg == "bind_and_activate" and isinstance(k.value, ast.Constant) and not k.value.value
                       for k in n.keywords):
                yield _f("L-20", s, n.lineno, f"{_last(n.func)}( 직접 생성 — 기본 allow_reuse_address=1. "
                         "allow_reuse_address=False 인 하위 클래스를 쓰세요")


# ───────────────────────────── L-21 팀 서버 주소·사설 IP ─────────────────────────────
PRIV_IP_RE = re.compile(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
                        r"192\.168\.\d{1,3}\.\d{1,3})(?![\d])(?!\.\d)")


def _l21_file(s, ctx):
    if s.rule_table or CR14_EXEMPT.match(s.rp):
        return
    text = s.privacy_text
    if text is None:
        return
    for m in PRIV_IP_RE.finditer(text):
        ip = m.group(0)
        if ip == TEAM_HOST and (s.rp in TEAM_IP_OK or s.is_test):
            continue
        what = "팀 서버 기본 주소는 lm27\\team\\client.py·레지스트리 기본값에만" if ip == TEAM_HOST else "사설 IP 리터럴 금지"
        yield _f("L-21", s, _line_of(text, m.start()), f"{what} — 시험 값은 런타임에 조립(CR-14 예외: docs·정제 말뭉치)")


@repo_rule("L-21")
def _l21_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l21_file(s, ctx)
    reg, rerr = ctx.registry()
    if reg is None:
        if not rerr:
            yield Finding("L-21", "config\\settings_registry.json", 0, "레지스트리가 아직 없어 기본 주소 대조를 건너뜀", warn=True)
    else:
        host = (reg.get("team.serverHost") or {}).get("default")
        port = (reg.get("team.serverPort") or {}).get("default")
        if host != TEAM_HOST or port != TEAM_PORT or isinstance(port, bool):
            yield Finding("L-21", "config\\settings_registry.json", 0,
                          f"team.serverHost·serverPort 기본값이 고정 주소와 다름(DEFAULT_TEAM_URL 바이트 일치 필요): {host!r}:{port!r}")
    cp = ctx.p("lm27", "team", "client.py")
    if os.path.isfile(cp):
        s = next((x for x in srcs if x.rp == "lm27/team/client.py"), None) or Src(ctx.root, cp)
        val = None
        if s.tree is not None:
            for n in s.tree.body:
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_TEAM_URL"
                                                     for t in n.targets) and isinstance(n.value, ast.Constant):
                    val = n.value.value
        if val != TEAM_URL:
            yield _f("L-21", s, 0, f"DEFAULT_TEAM_URL 상수가 없거나 고정 주소와 다름({val!r}) — 바꾸는 '옵션'만 허용")
    for s in srcs:
        if s.is_py and s.tree is not None and s.is_product and not s.rule_table and s.rp != "lm27/team/client.py":
            for n in ast.walk(s.tree):
                if isinstance(n, ast.Assign) and any(_last(t) == "DEFAULT_TEAM_URL" for t in n.targets):
                    yield _f("L-21", s, n.lineno, "DEFAULT_TEAM_URL 은 lm27\\team\\client.py 한 곳에만(CR-13)")


# ───────────────────────────── L-22 팀 빌더 ─────────────────────────────
REG_READERS = frozenset({"lm27/team/build.py", "lm27/team/client.py", "lm27/hier/registry.py", "lm27/paths.py"})


@repo_rule("L-22")
def _l22_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l22_file(s, ctx)


def _l22_file(s, ctx):
    if not s.is_py or s.tree is None or not s.is_product or s.rule_table:
        return
    builder = s.rp == "lm27/team/build.py"
    reader_ok = s.rp in REG_READERS or s.under("lm27/privacy/")
    for n in ast.walk(s.tree):
        if builder:
            if isinstance(n, ast.Dict) and any(k is None for k in n.keys):
                yield _f("L-22", s, n.lineno, "팀 빌더에서 **dict 통째 전달 금지 — 허용 목록 필드만 생성")
            elif isinstance(n, ast.Call):
                nm = _last(n.func)
                if any(k.arg is None for k in n.keywords):
                    yield _f("L-22", s, n.lineno, "팀 빌더에서 **kwargs 통째 전달 금지")
                if nm == "dict" and len(n.args) == 1 and not isinstance(n.args[0], (ast.Dict, ast.List, ast.Tuple,
                                                                                     ast.ListComp, ast.GeneratorExp)):
                    yield _f("L-22", s, n.lineno, "팀 빌더에서 dict(obj) 통째 복사 금지")
                if nm == "deepcopy" and any("analysis" in ast.unparse(a).lower() for a in n.args):
                    yield _f("L-22", s, n.lineno, "팀 빌더에서 deepcopy(analysis…) 금지")
            if isinstance(n, ast.Constant) and n.value == "host_display" or \
                    (isinstance(n, (ast.Attribute, ast.Name)) and _last(n) == "host_display"):
                yield _f("L-22", s, n.lineno, "팀 빌더는 host_display 를 읽지 않는다(TAB §2.3.3)")
        if not reader_ok:
            if isinstance(n, ast.Call) and _last(n.func) == "registry_cache":
                yield _f("L-22", s, n.lineno, "data\\team\\registry.json 은 team.build·client·privacy·hier.registry 만 읽음")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                    re.search(r"team[\\/]+registry\.json", n.value):
                yield _f("L-22", s, n.lineno, "data\\team\\registry.json 경로 — 허용 모듈만")


# ───────────────────────────── L-23 TEAM_SPEC_V1 ─────────────────────────────
@repo_rule("L-23")
def _l23_repo(ctx, srcs, selected):
    sp = ctx.p("lm27", "team", "schema.py")
    for s in srcs:
        if s.is_py and s.tree is not None and s.is_product and not s.rule_table and s.rp != "lm27/team/schema.py":
            for n in ast.walk(s.tree):
                if isinstance(n, (ast.Assign, ast.AnnAssign)):
                    tg = n.targets if isinstance(n, ast.Assign) else [n.target]
                    if any(_last(t) == "TEAM_SPEC_V1" for t in tg):
                        yield _f("L-23", s, n.lineno, "TEAM_SPEC_V1 사본 — 단일원은 lm27\\team\\schema.py(X-270)")
    if not os.path.isfile(sp):
        yield Finding("L-23", "lm27\\team\\schema.py", 0, "아직 없음 — TEAM_SPEC_V1 대조 건너뜀", warn=True)
        return
    s = next((x for x in srcs if x.rp == "lm27/team/schema.py"), None) or Src(ctx.root, sp)
    if s.tree is None or not any(isinstance(n, (ast.Assign, ast.AnnAssign)) and
                                 any(_last(t) == "TEAM_SPEC_V1" for t in
                                     (n.targets if isinstance(n, ast.Assign) else [n.target]))
                                 for n in s.tree.body):
        yield _f("L-23", s, 0, "schema.py 최상위에 TEAM_SPEC_V1 이 없음")
        return
    tab, pri = parse_team_fields(ctx.doc("TEAM_AND_BUNDLE.md"), ctx.doc("PRIVACY.md"))
    if not tab:
        yield Finding("L-23", "docs/TEAM_AND_BUNDLE.md", 0, "TAB §2.3.2 표를 읽지 못함")
        return
    code = _probe_code(ctx, "from lm27.team import schema as m\n"
                            "s = m.TEAM_SPEC_V1\nprint(json.dumps(sorted(s) if isinstance(s, dict) else None))\n")
    rc, out, err = ctx.run_py(code)
    if rc != 0:
        yield _f("L-23", s, 0, f"schema.py import 실패(rc {rc}): {(err.strip().splitlines() or [''])[-1][:200]}")
        return
    try:
        top = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        top = None
    if top is None:
        yield _f("L-23", s, 0, "TEAM_SPEC_V1 이 최상위 필드 사전이 아니라 표 대조를 못함 — 형을 알려 주세요(CR)", warn=True)
        return
    top = set(top)
    miss = sorted(tab - top)
    if miss:
        yield _f("L-23", s, 0, f"TAB §2.3.2 표의 필드가 TEAM_SPEC_V1 에 없음: {miss}")
    pm = sorted(pri - top)
    if pm:
        yield _f("L-23", s, 0, f"P §14.5 표의 필드가 TEAM_SPEC_V1 에 없음: {pm}")
    extra = sorted(top - tab - pri)
    if extra:
        yield _f("L-23", s, 0, f"TAB·P 표에 없는 TEAM_SPEC_V1 필드: {extra}")


# ───────────────────────────── L-24 정제 규칙 잠금·빈 기본값 ─────────────────────────────
EMPTY_DEFAULT_KEYS = (
    "privacy.customers", "privacy.partners", "privacy.internalDomains", "privacy.allowPatterns",
    "privacy.extraCtx.account", "privacy.extraCtx.passport", "privacy.extraCtx.license", "privacy.extraCtx.money",
    "privacy.extraCtx.ip", "privacy.extraCtx.card", "privacy.names.extraStopwords", "privacy.ad.blockDomains",
    "privacy.ad.allowDomains", "privacy.ad.blockSubjectRegex", "privacy.ad.extraWords", "privacy.private.extraWords",
    "privacy.private.extraWorkWords", "privacy.window.workTitlePatterns", "pc.watchFolders", "pc.programsExtra",
    "pc.git.repos", "pc.git.scanRoots", "pc.license.servers", "team.selfLabel", "team.memberId",
    "team.serverAlternates", "teamServer.allowCidrs", "teamServer.allowedHosts", "teamServer.inboxDirs",
    "teamServer.uploadTokenSha256", "teamServer.adminTokenSha256", "teamServer.displayName", "teams.pmWhoKeys",
    "collect.ownerAddress", "hier.tokens.boilerplateAdd", "teams.timeRegex")


@repo_rule("L-24")
def _l24_repo(ctx, srcs, selected):
    lock = ctx.p("lm27", "privacy", "rules.lock.json")
    rules = ctx.p("lm27", "privacy", "rules.py")
    if os.path.isfile(rules) and not os.path.isfile(lock):
        yield Finding("L-24", "lm27\\privacy\\rules.lock.json", 0, "rules.py 는 있는데 rules.lock.json 이 없음")
    elif os.path.isfile(rules):
        try:
            with open(lock, "rb") as fh:
                want = json.loads(fh.read().decode("utf-8-sig"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            want = None
            yield Finding("L-24", "lm27\\privacy\\rules.lock.json", 0, f"잠금 파일 읽기 실패({type(e).__name__})")
        if isinstance(want, dict):
            code = _probe_code(ctx, "from lm27.privacy import rules as m\n"
                                    "h = getattr(m, 'RULES_HASH', None)\nh = h if h is not None else m.rules_hash()\n"
                                    "print(json.dumps([getattr(m, 'RULES_VERSION', None), h]))\n")
            rc, out, err = ctx.run_py(code)
            if rc != 0:
                yield Finding("L-24", "lm27\\privacy\\rules.py", 0,
                              f"규칙 import 실패(rc {rc}): {(err.strip().splitlines() or [''])[-1][:200]}")
            else:
                try:
                    ver, h = json.loads(out.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    ver = h = None
                if h != want.get("rules_hash") or ver != want.get("rules_ver"):
                    yield Finding("L-24", "lm27\\privacy\\rules.lock.json", 0,
                                  f"규칙 잠금 불일치 — 코드 ({ver}, {h}) ≠ 잠금 ({want.get('rules_ver')}, "
                                  f"{want.get('rules_hash')}). 규칙이 바뀌었으면 판·말뭉치를 올리고 --update-lock(P §16.4)")
    else:
        yield Finding("L-24", "lm27\\privacy\\rules.py", 0, "아직 없음 — 규칙 잠금 대조 건너뜀", warn=True)
    reg, _err = ctx.registry()
    if reg:
        for k in EMPTY_DEFAULT_KEYS:
            if k in reg:
                d = reg[k].get("default") if isinstance(reg[k], dict) else None
                if d not in (None, "", [], {}):
                    yield Finding("L-24", "config\\settings_registry.json", 0,
                                  f"배포 기본값은 빈 값이어야 함: {k}(고객·과제·별칭·코드네임·구성원·규칙·카탈로그 0)")
    gi = ctx.p(".gitignore")
    if os.path.isfile(gi):
        with open(gi, "rb") as fh:
            lines = {ln.strip() for ln in fh.read().decode("utf-8", errors="replace").splitlines()}
        for need in ("data/", "out/", "config/config.json"):
            if need not in lines:
                yield Finding("L-24", ".gitignore", 0, f"'{need}' 줄이 없음 — 개인 자료·설정이 커밋·패키지에 섞인다")


# ───────────────────────────── L-25 분류 ─────────────────────────────
@file_rule("L-25")
def _l25(s, ctx):
    if not s.is_code or not s.is_product or s.rule_table:
        return
    if s.rp in ("lm27/hier/learn.py", "lm27/hier/rules.py") and s.tree is not None:
        for n in ast.walk(s.tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods = [(n.module or "")] + [(n.module or "") + "." + a.name for a in n.names]
            if any(re.search(r"(?:proposals|copilot_io|ai_out)", m) or m.startswith("lm27.bridge") for m in mods):
                yield _f("L-25", s, n.lineno, "learn.py·rules.py 는 ai_out·proposals 를 읽지 않는다(G-H7 AI 되먹임 금지)")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and re.search(r"ai_out|proposals", n.value) \
                    and not s.is_docstring(n):
                yield _f("L-25", s, n.lineno, "learn.py·rules.py 에 ai_out·proposals 경로 문자열(G-H7)")
            elif isinstance(n, ast.Call) and _last(n.func) in ("ai_out", "read_ai_out", "ProposalQueue"):
                yield _f("L-25", s, n.lineno, "learn.py·rules.py 에서 AI 답·제안 읽기(G-H7)")
    if s.rp == "lm27/hier/vocab.py":
        return
    names = {nm for nm, _c in ctx.domains.values()}
    cols = {c for _n, c in ctx.domains.values()}
    if s.is_py and s.tree is not None:
        for n, v in s.str_consts():
            if v.strip() in names:
                yield _f("L-25", s, n.lineno, f"영역 이름 '{v.strip()}' 하드코딩 — DOMAIN_META·domain_name() 만(G-H11)")
            elif v.strip().lower() in cols:
                yield _f("L-25", s, n.lineno, "영역 색 하드코딩 — DOMAIN_META·domain_color() 만(G-H11)")
    elif s.rp != "web/common/lm27.css":
        for i, ln in s.code_lines():
            for q in re.findall(r"""['"]([^'"\n]{1,20})['"]""", ln):
                if q.strip() in names:
                    yield _f("L-25", s, i, f"영역 이름 '{q.strip()}' 하드코딩(G-H11)")
            for c in re.findall(r"#[0-9a-fA-F]{6}\b", ln):
                if c.lower() in cols:
                    yield _f("L-25", s, i, "영역 색 하드코딩(G-H11)")


# ───────────────────────────── L-26 실명·이메일 ─────────────────────────────
EMAIL_RE = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,})"
                      r"(?![\w-])")


def _email_ok(domain):
    d = domain.lower()
    return d == "example.com" or d.endswith(".example.com") or d == "example" or d.endswith(".example")


U_ESC_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape_u(text):
    r"""JSON \uXXXX 이스케이프를 푼 사본(ensure_ascii 로 쓴 실명도 찾게). 줄 수는 그대로."""
    return U_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)) if m.group(1).lower() not in ("000a", "000d") else " ", text)


@file_rule("L-26")
def _l26(s, ctx):
    text = s.privacy_text
    if text is None:
        return
    words, err = ctx.forbidden()
    if err:
        if "forbidden" not in ctx.once:
            ctx.once.add("forbidden")
            yield Finding("L-26", "", 0, err)
    else:
        low = text.lower()
        lows = (low, _unescape_u(low)) if "\\u" in low else (low,)
        rpl = s.rp.lower()
        for idx, w in enumerate(words, 1):
            src = next((x for x in lows if w in x), None)
            if src is not None:
                pos = src.find(w)
                n = src.count(w)
                yield _f("L-26", s, _line_of(src, pos), f"금지어 목록 {idx}번째 항목과 일치 {n}곳 — 실명·계정·코드네임은 "
                         "자리표시자(홍길동·김철수·과제A·고객사A)로")
            elif w in rpl:
                yield _f("L-26", s, 0, f"파일 경로가 금지어 목록 {idx}번째 항목을 포함")
    if s.rule_table or CR14_EXEMPT.match(s.rp):
        return
    for m in EMAIL_RE.finditer(text):
        if not _email_ok(m.group(1)):
            yield _f("L-26", s, _line_of(text, m.start()), "이메일은 example.com·*.example 만 — 시험 값은 런타임에 조립")


# ───────────────────────────── L-27 JS 문법 ─────────────────────────────
@repo_rule("L-27")
def _l27_repo(ctx, srcs, selected):
    js = [s for s in srcs if s.ext == ".js" and s.under("web/", "tests/web/")]
    if not js:
        return
    node = ctx.node()
    if not node:
        yield Finding("L-27", "web", 0, "node 없음 — JS 문법 검사 건너뜀(개발 PC 전용)", warn=True)
        return
    for s in js:
        try:
            p = subprocess.run([node, "--check", s.path], capture_output=True, timeout=60,
                               cwd=tempfile.gettempdir(), creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            yield _f("L-27", s, 0, f"node 실행 실패({type(e).__name__})")
            continue
        if p.returncode != 0:
            msg = (p.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
            line = 0
            for ln in msg:
                m = re.search(r":(\d+)\s*$", ln)
                if m:
                    line = int(m.group(1))
                    break
            err = next((ln for ln in msg if "Error" in ln), msg[-1] if msg else "")
            yield _f("L-27", s, line, f"JS 문법 오류: {err.strip()[:200]}")


# ───────────────────────────── L-28 별개 프로젝트·이전 판 ─────────────────────────────
OLD_PORTS = frozenset({8765, 8766, 8767, 9333})
# '--port 9333' · 'port=9333' · '$cdpPort = 9333' · 'const uiPort=8765' · '{port: 8766}' · ':9333'
PORT_TEXT_RE = re.compile(r"(?i)(?:(?<![\w])-{0,2}port[\"']?\s*[=:]?\s*|\w*port[\"']?\s*[=:]\s*|:)(876[5-7]|9333)(?!\d)")
OLD_NAMES = ("LoadMonitor" + "26", "LM2" + "6-")
REGISTRY_RP = "config/settings_registry.json"


def _old_port_values(v, portish, depth=0):
    """레지스트리 값(기본값·선택지) 안의 옛 포트 — 포트 키면 정수, 어디서든 'host:9333' 꼴 문자열."""
    if depth > 6:
        return
    if isinstance(v, bool):
        return
    if isinstance(v, int):
        if portish and v in OLD_PORTS:
            yield v
    elif isinstance(v, str):
        m = PORT_TEXT_RE.search(v)
        if m:
            yield int(m.group(1))
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _old_port_values(x, portish, depth + 1)
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _old_port_values(x, portish or "port" in str(k).lower(), depth + 1)


def _l28_registry(s, ctx):
    """설정 레지스트리: 포트 키(마지막 마디가 port·…Port)와 모든 int 키의 기본값·선택지에 옛 포트가 있으면 실패.
    (범위 min..max 는 연속 구간이라 1024~65535 처럼 옛 포트를 언제나 품는다 — 범위는 보지 않고 값만 본다.
    사용자가 고르는 값의 거부는 실행 시 검사 몫.)"""
    try:
        obj = json.loads(s.text, object_pairs_hook=_no_dup)
    except (ValueError, RecursionError) as e:
        yield _f("L-28", s, 0, f"레지스트리 해석 실패({type(e).__name__}) — 포트 기본값을 대조하지 못함")
        return
    for key, meta in sorted(registry_entries(obj).items()):
        portish = bool(re.search(r"(?i)port", key.rsplit(".", 1)[-1])) or meta.get("type") == "int"
        for fld in ("default", "choices"):
            for p in _old_port_values(meta.get(fld), portish):
                ln = s.text.find(f'"{key}"')
                yield _f("L-28", s, _line_of(s.text, ln) if ln >= 0 else 0,
                         f"설정 '{key}' 의 {fld} 에 포트 {p} — 별개 프로젝트 8765~8767·이전 판 9333 과 겹침")


def _l28_file(s, ctx):
    if s.is_doc or s.rule_table or not (s.is_code or s.ext in (".html", ".json") and s.under("config/", "web/")):
        return
    if s.rp == REGISTRY_RP:
        yield from _l28_registry(s, ctx)
    items = [(n.lineno, v) for n, v in s.str_consts()] if s.is_py else list(s.code_lines())
    for i, ln in items:
        for nm in OLD_NAMES:
            if nm in ln:
                yield _f("L-28", s, i, f"별개 프로젝트·이전 판 이름 '{nm}' — 이름·작업 이름을 겹치지 않는다")
    if s.is_py and s.tree is not None:
        for n in ast.walk(s.tree):
            if isinstance(n, ast.Constant) and type(n.value) is int and n.value in OLD_PORTS:
                yield _f("L-28", s, n.lineno, f"포트 {n.value} 사용 금지(별개 프로젝트 8765~8767·이전 판 9333)")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and PORT_TEXT_RE.search(n.value):
                yield _f("L-28", s, n.lineno, "포트 8765~8767·9333 사용 금지")
    else:
        for i, ln in s.code_lines():
            if PORT_TEXT_RE.search(ln):
                yield _f("L-28", s, i, "포트 8765~8767·9333 사용 금지")


@repo_rule("L-28")
def _l28_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l28_file(s, ctx)


# ───────────────────────────── L-29 폐기 산출물·금지 접근 경로 ─────────────────────────────
RETIRED_OUT = [re.compile(p) for p in (
    r"(?<![\w.])mail\.csv\b", r"(?<![\w])replies[\\/]", r"(?<![\w])mail_prompt_[\w*]*\.txt\b",
    r"(?<![\w])mail_source\.json\b", r"(?<![\w])coverage\.json\b", r"(?<![\w])teams_window[\w*]*\.csv\b",
    r"(?<![\w])teams_window_raw\.txt\b", r"(?<![\w])teams_web\.csv\b", r"(?<![\w])sanitize_audit\.jsonl\b",
    r"(?<![\w])completion_ledger\.jsonl\b", r"(?<![\w])git_source\.json\b")]
BANNED_ACCESS = re.compile("(?i)(" + "|".join(re.escape(x) for x in (
    "graph." + "microsoft.com", "Indexed" + "DB", "Level" + "DB", "wpn" + "database")) + ")")
OST_EXT = re.compile(r"(?i)\.(?:ost|pst)$")
OST_TEXT_RE = re.compile(r"(?i)\b(?:Get-Content|Copy-Item|OpenRead|OpenText|ReadAllBytes|ReadAllText|ReadAllLines|"
                         r"FileStream|Open)\b[^\r\n#]*\.(?:ost|pst)\b")
OPEN_LIKE = ("open", "copy", "copy2", "copyfile", "startfile", "read_bytes", "read_text", "FileIO")
OST_OPENERS = frozenset(OPEN_LIKE) | {"connect", "fdopen", "copyfileobj", "move"}
# D-3 자격 증명·브라우저 내부 DB(계약 §11.1 L-29 ② 확장 — CR). 'Local State'·'Cookies' 낱말 자체는 이동 준비의
# 브라우저 프로필 흔적 경고 목록(TAB §1.11)에 쓰이므로 경로 꼴(Network\Cookies)만 본다.
CRED_ACCESS = re.compile("(?i)(" + "|".join((
    r"\bCred(?:Read|Enumerate|Write)\w*", r"\bCryptUnprotectData\b", r"\bPasswordVault\b", r"\bcmd" + r"key\b",
    r"\bvault" + r"cmd\b", r"\bLogin Data\b", r"\bWeb Data\b", r"\bNetwork[\\/]+Cookies\b")) + ")")
CRED_IDENT = re.compile(r"^(?:Cred(?:Read|Enumerate|Write)\w*|CryptUnprotectData|PasswordVault)$")
EXCL_KEY = re.compile(r"(?i)exclu|skip|ignore|deny|block|banned|forbid")
PS_OST_RE = re.compile(r"(?i)\.(?:ost|pst)\b")
PS_OST_EXCL_RE = re.compile(r"""(?i)-Exclude\b|-not(?:like|match|in)\b|@\(|['"][^'"]*\.(?:ost|pst)['"]\s*,|"""
                            r""",\s*['"][^'"]*\.(?:ost|pst)['"]""")
PS_READ_RE = re.compile(r"(?i)\[(?:System\.)?IO\.File\]::(?:Open\w*|Read\w*|Copy)|\bGet-Content\b|\bCopy-Item\b|"
                        r"\bIO\.(?:FileStream|StreamReader|BinaryReader)\b|\bOpenRead\b")


def _listed(s, node):
    """제외 목록 표기인가 — 리스트·튜플·집합 리터럴 원소, 또는 exclude·skip 류 키의 값."""
    par = s.parent(node)
    if isinstance(par, (ast.List, ast.Tuple, ast.Set)):
        return True
    if isinstance(par, ast.Dict):
        for k, v in zip(par.keys, par.values, strict=True):
            if v is node and isinstance(k, ast.Constant) and isinstance(k.value, str) and EXCL_KEY.search(k.value):
                return True
    if isinstance(par, ast.keyword) and par.arg and EXCL_KEY.search(par.arg):
        return True
    return False


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _scopes(tree):
    """(범위 노드, 그 범위에 속한 노드들) — 모듈 최상위와 함수마다(안쪽 함수·클래스 제외, 기본 인자 포함)."""
    yield tree, list(_walk_no_defs([st for st in tree.body if not isinstance(st, _DEFS)]))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            seeds = list(a.defaults) + [d for d in a.kw_defaults if d is not None]
            seeds += n.body if isinstance(n.body, list) else [n.body]
            yield n, list(_walk_no_defs([x for x in seeds if not isinstance(x, _DEFS)]))


def _ost_scope_hits(s):
    """.ost/.pst 상수(제외 목록 표기 아님)와 열기 호출이 같은 범위에 있으면 그 상수 줄들 — glob('*.ost') 뒤 read_bytes,
    ext='.pst' 기본 인자 뒤 open 같은 간접 열기."""
    out = set()
    for _scope, nodes in _scopes(s.tree):
        consts = [x for x in nodes if isinstance(x, ast.Constant) and isinstance(x.value, str)
                  and OST_EXT.search(x.value.strip()) and not s.is_docstring(x) and not _listed(s, x)]
        if consts and any(isinstance(x, ast.Call) and _last(x.func) in OST_OPENERS for x in nodes):
            out.update(c.lineno for c in consts)
    return sorted(out)


def _l29_file(s, ctx):
    if not s.is_code or s.is_doc or s.rule_table:
        return
    items = [(n.lineno, v) for n, v in s.str_consts()] if s.is_py else list(s.code_lines())
    for i, ln in items:
        m = BANNED_ACCESS.search(ln)
        if m:
            yield _f("L-29", s, i, "금지 접근 경로 문자열(Graph·앱 내부 캐시 — D-3) — 허용 경로만 구현합니다")
    if s.is_py and s.tree is not None:
        for n, v in s.str_consts():
            if CRED_ACCESS.search(v) and not _listed(s, n):
                yield _f("L-29", s, n.lineno, "자격 증명·브라우저 내부 DB 접근(D-3 — Credential Manager·DPAPI·"
                         "Login Data·Cookies) — 허용 경로만 구현합니다")
        for n in ast.walk(s.tree):
            if isinstance(n, (ast.Name, ast.Attribute)) and CRED_IDENT.match(_last(n)):
                yield _f("L-29", s, n.lineno, f"자격 증명 API '{_last(n)}'(D-3) — 자격 증명은 읽지 않습니다")
        for ln in _ost_scope_hits(s):
            yield _f("L-29", s, ln, "OST·PST 파일을 찾아 여는 코드(glob·확장자 비교 + 열기, D-3) — 제외 목록 표기만 허용")
    elif not s.is_py:
        lines = list(s.code_lines())
        reads = any(PS_READ_RE.search(ln) for _i, ln in lines) if s.ext in PS_EXT else False
        for i, ln in lines:
            if CRED_ACCESS.search(ln):
                yield _f("L-29", s, i, "자격 증명·브라우저 내부 DB 접근(D-3 — cmdkey·PasswordVault·Login Data·Cookies)")
            if reads and PS_OST_RE.search(ln) and not PS_OST_EXCL_RE.search(ln) and not OST_TEXT_RE.search(ln):
                yield _f("L-29", s, i, "OST·PST 파일을 찾아 여는 코드(-Filter *.ost 등 + 열기, D-3) — 제외 목록 표기만 허용")
    if s.is_py and s.tree is not None:
        for n, v in s.str_consts():
            for rx in RETIRED_OUT:
                if rx.search(v):
                    yield _f("L-29", s, n.lineno, f"폐기된 산출물 이름 '{rx.search(v).group(0)}' — 계약 §1.2 의 위치만")
                    break
        for n in ast.walk(s.tree):
            if isinstance(n, ast.Call) and _last(n.func) in OPEN_LIKE:
                tgt = n.args[0] if n.args else (n.func.value if isinstance(n.func, ast.Attribute) else None)
                for x in ast.walk(tgt) if tgt is not None else ():
                    if isinstance(x, ast.Constant) and isinstance(x.value, str) and OST_EXT.search(x.value.strip()):
                        yield _f("L-29", s, n.lineno, "OST·PST 파일 직접 열기 금지(D-3)")
                        break
    else:
        for i, ln in s.code_lines():
            for rx in RETIRED_OUT:
                if rx.search(ln):
                    yield _f("L-29", s, i, f"폐기된 산출물 이름 '{rx.search(ln).group(0)}'")
                    break
            if OST_TEXT_RE.search(ln):
                yield _f("L-29", s, i, "OST·PST 파일 직접 열기 금지(D-3)")


@repo_rule("L-29")
def _l29_repo(ctx, srcs, selected):
    for s in srcs:
        yield from _l29_file(s, ctx)


# ───────────────────────────── L-30 stages import 무부작용 ─────────────────────────────
L30_PROBE = r'''
import os, sys
sys.path.insert(0, @ROOT@)
BAD = {"subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.posix_spawn", "socket.connect",
       "socket.bind", "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.link", "os.symlink",
       "shutil.copyfile", "shutil.rmtree", "shutil.move", "os.truncate", "os.chmod", "winreg.SetValue"}
W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
def hook(ev, args):
    if ev == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and isinstance(flags, int) and flags & W):
            raise RuntimeError("부작용: 파일 쓰기")
    elif ev in BAD or ev.startswith("winreg.Set") or ev.startswith("winreg.Create"):
        raise RuntimeError("부작용: " + ev)
sys.addaudithook(hook)
import importlib
importlib.import_module(@MOD@)
print("ok")
'''


def _probe_code(ctx, body):
    """자식 파이썬에 넘길 코드 — 트리 루트를 sys.path 맨 앞에 넣고 body 를 실행."""
    return "import sys, json\nsys.path.insert(0, " + repr(ctx.root) + ")\n" + body


@repo_rule("L-30")
def _l30_repo(ctx, srcs, selected):
    d = ctx.p("lm27", "bridge", "stages")
    if not os.path.isdir(d):
        yield Finding("L-30", "lm27\\bridge\\stages", 0, "아직 없음 — import 무부작용 검사 건너뜀", warn=True)
        return
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py"):
            continue
        mod = "lm27.bridge.stages" + ("" if fn == "__init__.py" else "." + fn[:-3])
        code = L30_PROBE.replace("@ROOT@", repr(ctx.root)).replace("@MOD@", repr(mod))
        rc, out, err = ctx.run_py(code, timeout=60)
        if rc != 0 or "ok" not in out:
            last = (err.strip().splitlines() or ["?"])[-1]
            yield Finding("L-30", "lm27\\bridge\\stages\\" + fn, 0, f"import 에 부작용·오류 — {last[:200]}(R B-2: 세션 없이 "
                          "fallback 이 불려야 함)")


# ───────────────────────────── 실행기 ─────────────────────────────
def iter_files(root):
    root = os.path.abspath(root)
    for dp, dns, fns in os.walk(root):
        top = os.path.normcase(os.path.abspath(dp)) == os.path.normcase(root)
        dns[:] = sorted(d for d in dns if d not in ANY_SKIP and not (top and d in TOP_SKIP))
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rp = os.path.relpath(p, root).replace("\\", "/")
            if rp in FILE_SKIP or fn.endswith(".part"):
                continue
            yield p


def _excluded(rp):
    """저장소 전역 검사가 보지 않는 곳(동봉 파이썬·개인 자료·작업 폴더·캐시)은 훅·파일 모드도 보지 않는다."""
    if os.path.isabs(rp):
        return False
    parts = rp.split("/")
    return parts[0] in TOP_SKIP or any(p in ANY_SKIP for p in parts[:-1]) or rp in FILE_SKIP or rp.endswith(".part")


def _norm_rules(rules, default):
    if not rules:
        return tuple(default)
    out = []
    for r in rules:
        for x in str(r).replace(",", " ").split():
            x = x.strip().upper()
            if re.fullmatch(r"\d{1,2}", x):
                x = f"L-{int(x):02d}"
            elif re.fullmatch(r"L-?\d{1,2}", x):
                x = f"L-{int(x.replace('L', '').replace('-', '')):02d}"
            if x not in ALL_RULES:
                raise ValueError(f"알 수 없는 규칙 {x}")
            out.append(x)
    return tuple(dict.fromkeys(out))


# 저장소 전역 실행 때 파일 단위 함수가 아니라 저장소 함수 안에서 파일을 도는 규칙(파일 단위 부분 포함)
_FILE_PART_IN_REPO = {"L-08": _l08_file, "L-13": _l13_file, "L-14": _l14_file, "L-15": _l15_file, "L-17": _l17_file,
                      "L-21": _l21_file, "L-22": _l22_file, "L-28": _l28_file, "L-29": _l29_file}


def check_file(path, root=None, rules=None, ctx=None, **opts):
    """파일 1개 — 기본은 훅 규칙 묶음. 반환 [Finding]."""
    ctx = ctx or Ctx(root, **opts)
    sel = _norm_rules(rules, HOOK_RULES)
    if not os.path.isfile(path):
        return []
    s = Src(ctx.root, path)
    if _excluded(s.rp) or not s.is_texty:
        return []
    out = []
    for rid in sel:
        for fn in FILE_RULES.get(rid, ()):
            out.extend(_safe(rid, s.rel, fn, s, ctx))
        part = _FILE_PART_IN_REPO.get(rid)
        if part is not None:
            out.extend(_safe(rid, s.rel, part, s, ctx))
    return out


def _safe(rid, rel, fn, *args):
    """규칙 하나를 돈다. 파일이 도중에 사라지면 경고, 규칙 자체가 깨지면 오류(관문 도구 결함 — 통과로 치지 않는다)."""
    try:
        return list(fn(*args))
    except OSError as e:
        return [Finding(rid, rel, 0, f"파일을 읽지 못해 건너뜀({type(e).__name__})", warn=True)]
    except Exception as e:  # noqa: BLE001 — 관문 도구 결함을 지적 1건으로 드러낸다
        return [Finding(rid, rel, 0, f"관문 도구 내부 오류({type(e).__name__}: {str(e)[:120]}) — hook_check.py 결함, "
                        "검사 대상 탓이 아님(WP-04 에 알림)")]


def check_repo(root=None, rules=None, ctx=None, **opts):
    """저장소 전역 — 기본은 L-01~L-30 전부. 반환 [Finding]."""
    ctx = ctx or Ctx(root, **opts)
    sel = _norm_rules(rules, ALL_RULES)
    srcs = [Src(ctx.root, p) for p in iter_files(ctx.root)]
    srcs = [s for s in srcs if s.is_texty]        # 확장자 규칙(L-01·02·13 …)은 각 규칙이 is_text 로 다시 거른다
    ctx.batch_ruff = True
    out = []
    for rid in sel:
        for fn in FILE_RULES.get(rid, ()):
            for s in srcs:
                out.extend(_safe(rid, s.rel, fn, s, ctx))
        if rid == "L-03":
            out.extend(_safe(rid, "", _run_ruff, ctx, [s for s in srcs if s.is_py]))
        for fn in REPO_RULES.get(rid, ()):
            out.extend(_safe(rid, "", fn, ctx, srcs, sel))
    return out


def _stdin_paths(root):
    """훅 모드 — Claude Code 가 stdin 으로 주는 UTF-8 JSON 에서 편집한 파일 경로를 꺼낸다.
    로케일(CP949)로 읽으면 한글 경로가 깨져 조용히 통과한다(실측) — 바이트로 읽어 직접 디코드한다."""
    raw = sys.stdin.buffer.read()
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(d, dict):
        return []
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    tr = d.get("tool_response") if isinstance(d.get("tool_response"), dict) else {}
    f = ti.get("file_path") or ti.get("notebook_path") or tr.get("filePath") or ""
    if not isinstance(f, str) or not f:
        return []
    return [f] if _is_under(f, root) else []


def _reconf():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root, rules, repo, l12_full, listing, files = None, None, False, False, False, []
    i = 0
    try:
        while i < len(argv):
            a = argv[i]
            if a == "--root":
                root = argv[i + 1]
                i += 1
            elif a == "--rules":
                rules = [argv[i + 1]]
                i += 1
            elif a == "--repo":
                repo = True
            elif a == "--l12-full":
                l12_full = True
            elif a == "--list":
                listing = True
            elif a in ("-h", "--help"):
                print(__doc__)
                return 0
            elif repo and re.fullmatch(r"(?i)L-?\d{1,2}(,L-?\d{1,2})*", a):
                rules = (rules or []) + [a]
            elif a.startswith("--"):
                sys.stderr.write(f"알 수 없는 옵션 {a}\n")
                return 2
            else:
                files.append(a)
            i += 1
    except IndexError:
        sys.stderr.write("옵션 값이 빠졌습니다\n")
        return 2
    if listing:
        for rid in ALL_RULES:
            mode = "훅+전역" if rid in HOOK_RULES else "전역"
            print(f"{rid}  [{mode}]  {RULE_TITLES[rid]}")
        return 0
    ctx = Ctx(root, l12_full=l12_full)
    try:
        if repo:
            t0 = time.monotonic()
            found = check_repo(ctx=ctx, rules=rules)
            errs = [f for f in found if not f.warn]
            warns = [f for f in found if f.warn]
            for f in sorted(errs, key=lambda x: (x.rule, x.rel, x.line)):
                print(f)
            for f in sorted(warns, key=lambda x: (x.rule, x.rel, x.line)):
                print(f)
            sel = _norm_rules(rules, ALL_RULES)
            bad = sorted({f.rule for f in errs})
            print(f"[lint] {GATE_VERSION} 규칙 {len(sel)}개 · 오류 {len(errs)}건{(' ' + ','.join(bad)) if bad else ''}"
                  f" · 경고 {len(warns)}건 · {time.monotonic() - t0:.1f}초")
            return 1 if errs else 0
        hook = not files
        paths = files or _stdin_paths(ctx.root)
        probs, warns = [], []
        for f in paths:
            for x in check_file(os.path.abspath(f), ctx=ctx, rules=rules):
                (warns if x.warn else probs).append(x)
    except ValueError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    if probs:
        sys.stderr.write("\n".join(str(p) for p in probs) + "\n")
        return 2
    if warns and not hook:
        print("\n".join(str(w) for w in warns))
    return 0


if __name__ == "__main__":
    _reconf()
    sys.exit(main())
