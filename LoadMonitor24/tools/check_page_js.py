# -*- coding: utf-8 -*-
r"""화면 스크립트(PAGE·TEAM_PAGE 안의 <script>) 문법 검사.

왜 필요한가: JS 문법 오류가 하나라도 있으면 스크립트 전체가 실행되지 않아
**모든 버튼이 죽는다**. 화면은 멀쩡히 그려지므로(HTML 은 유효하다) 눈으로는
구분이 안 되고, 파이썬 문법 검사·ruff·PowerShell 파서 어느 것도 잡지 못한다.

실측 사고: 배너를 넣으며 쓴 변수 `nb` 가 같은 함수 안에 이미 있었다.
`SyntaxError: Identifier 'nb' has already been declared` 하나로 분석 실행·중지·
진단 등 버튼 11개가 전부 반응하지 않았다.

node 가 있으면 진짜 파서로 검사하고, 없으면 자체 검사기로 같은 결함군을 잡는다.

  python tools\check_page_js.py
"""
import ast
import io
import os
import re
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page_scripts(py_path):
    r"""app.py 의 PAGE / TEAM_PAGE 에서 <script> 본문을 뽑는다 — **브라우저가 받는 형태**로.

    소스 그대로 검사하면 안 된다: 파이썬 문자열 안의 `\\u` 는 소스에서는 유효하지만 실제로
    나가는 것은 `\u` 라, `report\upload_pending` 같은 경로가 브라우저에서
    'Invalid Unicode escape sequence' 로 스크립트 전체를 죽인다(실측 — 버튼이 전부 먹통).
    그래서 ast 로 리터럴의 '값'을 얻어 검사한다."""
    src = open(py_path, encoding="utf-8").read()
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        # 조용히 통과하면 안 된다 — 파이썬이 깨졌으면 화면도 안 뜬다
        out.append(("PYTHON", getattr(e, "lineno", 0) or 0, None))
        return out
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        name = getattr(node.targets[0], "id", "")
        if name not in ("PAGE", "TEAM_PAGE") or not isinstance(node.value.value, str):
            continue
        body = node.value.value                      # ← 브라우저가 받는 바로 그 문자열
        base = node.lineno
        for sm in re.finditer(r"<script[^>]*>(.*?)</script>", body, re.S):
            line0 = base + body[:sm.start(1)].count("\n")
            out.append((name, line0, sm.group(1)))
    return out


def check_node(js):
    """진짜 JS 파서로 검사 — node 가 있을 때."""
    exe = None
    for c in ("node", r"C:\Program Files\nodejs\node.exe"):
        try:
            subprocess.run([c, "--version"], capture_output=True, timeout=20, check=True)
            exe = c
            break
        except (OSError, subprocess.SubprocessError):
            continue
    if not exe:
        return None
    fd, p = tempfile.mkstemp(suffix=".js")
    os.close(fd)
    try:
        # 함수 본문으로 감싼다 — 화면 스크립트는 최상위 return/await 를 쓰지 않는다
        open(p, "w", encoding="utf-8").write(js)
        r = subprocess.run([exe, "--check", p], capture_output=True, timeout=60)
        if r.returncode == 0:
            return []
        err = (r.stderr or b"").decode("utf-8", "replace")
        keep = [ln for ln in err.splitlines()
                if "Error" in ln or "^" in ln or ln.strip().startswith("Syntax")]
        return keep[:6] or err.splitlines()[:6]
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


DECL = re.compile(r"(?<![\w.$])(const|let)\s+([A-Za-z_$][\w$]*)")


def check_selfmade(js):
    """node 가 없을 때 — 같은 블록에서의 const/let 중복 선언과 괄호 균형만 본다.
    문자열·주석·정규식 리터럴을 지우고 나서 본다(그 안의 괄호에 속지 않게)."""
    s = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    s = re.sub(r"(?m)//.*$", " ", s)
    s = re.sub(r"`(?:\\.|[^`\\])*`", '""', s, flags=re.S)
    s = re.sub(r"'(?:\\.|[^'\\\n])*'", '""', s)
    s = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', s)
    errs = []
    depth, scopes = 0, [{}]
    line = 1
    for ch in s:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
            scopes.append({})
        elif ch == "}":
            depth -= 1
            if depth < 0:
                errs.append(f"{line}행: 닫는 중괄호가 더 많다")
                depth = 0
            elif len(scopes) > 1:
                scopes.pop()
    if depth:
        errs.append(f"중괄호 불균형: {depth}개가 닫히지 않았다")
    for br, name in (("()", "소괄호"), ("[]", "대괄호")):
        if s.count(br[0]) != s.count(br[1]):
            errs.append(f"{name} 불균형 ({s.count(br[0])} vs {s.count(br[1])})")
    # 중복 선언 — 블록 단위로 다시 훑는다
    depth, seen, line = 0, [{}], 1
    pos = 0
    for m in DECL.finditer(s):
        seg = s[pos:m.start()]
        line += seg.count("\n")
        for ch in seg:
            if ch == "{":
                depth += 1
                seen.append({})
            elif ch == "}":
                depth -= 1
                if len(seen) > 1:
                    seen.pop()
        pos = m.start()
        kw, nm = m.group(1), m.group(2)
        if nm in seen[-1]:
            errs.append(f"{line}행: '{nm}' 가 같은 블록에서 {kw} 로 다시 선언됐다 "
                        f"(먼저 {seen[-1][nm]}행) — 스크립트 전체가 죽는다")
        else:
            seen[-1][nm] = line
    return errs



def check_escapes(js):
    r"""문자열 리터럴 안의 잘못된 \u / \x 이스케이프 — 윈도우 경로를 그대로 적었을 때 난다.

    `"report\upload_pending"` 처럼 쓰면 JS 는 \u 를 유니코드 이스케이프로 보고
    'Invalid Unicode escape sequence' 로 **스크립트 전체**를 버린다(실측: 버튼 14개 전부 먹통).
    역슬래시를 두 번(\\) 쓰거나 슬래시를 쓰면 된다."""
    errs, line = [], 1
    i, n = 0, len(js)
    quote = None
    while i < n:
        ch = js[i]
        if ch == "\n":
            line += 1
        if quote is None:
            if ch in ("'", '"', "`"):
                quote = ch
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            nxt = js[i + 1]
            if nxt == "u":
                rest = js[i + 2:i + 6]
                okhex = len(rest) == 4 and all(c in "0123456789abcdefABCDEF" for c in rest)
                okbrace = js[i + 2:i + 3] == "{"
                if not okhex and not okbrace:
                    errs.append(f"{line}행: 잘못된 \\u 이스케이프 — {js[max(0, i - 24):i + 16]!r} "
                                "(윈도우 경로면 역슬래시를 두 번 쓰세요)")
            elif nxt == "x":
                rest = js[i + 2:i + 4]
                if not (len(rest) == 2 and all(c in "0123456789abcdefABCDEF" for c in rest)):
                    errs.append(f"{line}행: 잘못된 \\x 이스케이프 — {js[max(0, i - 24):i + 14]!r}")
            if nxt == "\n":
                line += 1
            i += 2
            continue
        if ch == quote:
            quote = None
        i += 1
    return errs[:6]


def main():
    bad = 0
    for py in (os.path.join(ROOT, "ui", "app.py"),
               os.path.join(ROOT, "teamserver.py")):
        if not os.path.exists(py):
            continue
        for name, line0, js in page_scripts(py):
            if js is None:                      # 파이썬 문법 자체가 깨진 경우
                bad += 1
                print(f"[X] {os.path.basename(py)}: 파이썬 문법 오류 (줄 {line0}) — 화면이 뜨지 않습니다")
                continue
            errs = check_node(js)
            how = "node"
            if errs is None:
                errs, how = check_selfmade(js), "자체검사"
            # 이스케이프 검사는 node 유무와 무관하게 항상 — 이 유형은 화면 전체를 죽인다
            errs = list(errs or []) + check_escapes(js)
            tag = f"{os.path.basename(py)}:{name}(줄 {line0}~, {how})"
            if errs:
                bad += 1
                print(f"[X] {tag}")
                for e in errs:
                    print(f"    {e}")
            else:
                print(f"[OK] {tag} — 문법 정상")
    if bad:
        print("\n화면 스크립트에 문법 오류가 있습니다. 이 상태로는 **버튼이 하나도 안 눌립니다.**")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
