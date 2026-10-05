# -*- coding: utf-8 -*-
r"""파일 한 개 즉시 검사 — Claude Code PostToolUse 훅과 tools\lint.ps1 이 같이 쓴다.

  python tools\hook_check.py <파일>      # 문제 있으면 exit 2 (훅 규약: 결과가 편집자에게 되돌아간다)

검사(파일 종류별):
  .py   ruff(이 트리의 ruff.toml) · 제어문자
  .ps1  UTF-8 BOM + CRLF(LF 단독 0) · 제어문자 — BOM 이 없으면 PowerShell 5.1 이 CP949 로 오독한다(LM 실측)
  .bat  BOM 없음 + CRLF + CP949 로 디코드 가능 — 아니면 cmd 가 한글 줄을 깨뜨린다(LM 실측)
  .md .json .html .js .css .txt .toml  UTF-8 디코드 · 제어문자
제어문자(0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F)는 경로 문자열이 'data\activity' → 'data<BEL>ctivity' 로 깨진
LM24 실측 결함(Register-Samplers.ps1) 의 재발을 막는다.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTRL = set(range(0, 9)) | {11, 12} | set(range(14, 32))
TEXT_EXT = {".py", ".ps1", ".bat", ".md", ".json", ".html", ".js", ".css", ".txt", ".toml", ".svg"}


def _ctrl_lines(text):
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        if any(ord(c) in CTRL for c in line):
            out.append(i)
    return out


def check(path):
    """문제 목록(문자열) — 빈 목록이면 통과."""
    probs = []
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXT or not os.path.isfile(path):
        return probs
    raw = open(path, "rb").read()
    name = os.path.relpath(path, ROOT) if path.lower().startswith(ROOT.lower()) else path
    if ext == ".bat":
        if raw[:3] == b"\xef\xbb\xbf":
            probs.append(f"{name}: BOM 이 있습니다 — bat 은 BOM 없는 CP949 여야 합니다")
        lone = sum(1 for i, b in enumerate(raw) if b == 10 and (i == 0 or raw[i - 1] != 13))
        if lone:
            probs.append(f"{name}: LF 단독 {lone}개 — bat 은 CRLF 여야 합니다")
        try:
            text = raw.decode("cp949")
        except UnicodeDecodeError:
            probs.append(f"{name}: CP949 로 읽을 수 없는 바이트 — bat 은 CP949 로 저장해야 합니다")
            text = raw.decode("cp949", errors="replace")
    else:
        if ext == ".ps1":
            if raw[:3] != b"\xef\xbb\xbf":
                probs.append(f"{name}: UTF-8 BOM 없음 — PowerShell 5.1 이 CP949 로 오독합니다")
            lone = sum(1 for i, b in enumerate(raw) if b == 10 and (i == 0 or raw[i - 1] != 13))
            if lone:
                probs.append(f"{name}: LF 단독 {lone}개 — ps1 은 CRLF 여야 합니다")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            probs.append(f"{name}: UTF-8 디코드 실패({e.start}바이트)")
            text = raw.decode("utf-8", errors="replace")
    bad = _ctrl_lines(text.replace("\r\n", "\n"))
    if bad:
        probs.append(f"{name}: 제어문자 {len(bad)}줄 (예: {bad[:5]}) — 이스케이프가 문자로 들어갔는지 확인")
    if ext == ".py":
        p = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--config",
                            os.path.join(ROOT, "ruff.toml"), "--output-format", "concise", path],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode not in (0,):
            out = (p.stdout or "") + (p.stderr or "")
            if "No module named ruff" in out:
                pass                      # ruff 가 없는 PC(사용자 배포 환경) — 린트는 개발 PC 관문에서만
            else:
                probs.append(out.strip())
    return probs


def _stdin_paths():
    """훅 모드(인자 없음) — Claude Code 가 stdin 으로 주는 UTF-8 JSON 에서 편집한 파일 경로를 꺼낸다.
    로케일(CP949)로 읽으면 한글 경로가 깨져 조용히 통과한다(실측) — 바이트로 읽어 직접 디코드한다."""
    import json
    raw = sys.stdin.buffer.read()
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return []
    f = ((d.get("tool_input") or {}).get("file_path") or (d.get("tool_response") or {}).get("filePath") or "")
    return [f] if f and os.path.abspath(f).lower().startswith(ROOT.lower()) else []


def main(argv):
    probs = []
    for f in (argv or _stdin_paths()):
        probs += check(os.path.abspath(f))
    if probs:
        sys.stderr.write("\n".join(probs) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    for _st in (sys.stdout, sys.stderr):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
