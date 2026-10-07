# -*- coding: utf-8 -*-
r"""
lm_fixenc.py — bat·ps1 인코딩 정규화 도우미 (LM28).

왜: 편집 도구는 UTF-8(BOM 없음·LF)로 쓴다. 그런데
    · .bat 은 CP949 + CRLF 여야 한다 — cmd 는 UTF-8 한글을 깨뜨리고, LF 단독 줄은 레이블·goto 를 어긋나게 한다.
    · .ps1 은 UTF-8 BOM + CRLF 여야 한다 — BOM 이 없으면 Windows PowerShell 5.1 이 CP949 로 오독해
      한글로 끝나는 줄이 다음 줄을 삼킨다(실사고).
    그래서 각 작업 묶음 끝에 그 묶음이 새로 만들거나 고친 .bat/.ps1 에 이 도구를 1회 돌린다.
    tools\lint.ps1 관문 4·5 와 tests\test_p0_names.py 가 같은 규칙을 검사한다.

  python tools\lm_fixenc.py --bat <파일…> [--ps1 <파일…>]   # 변환(바뀐 파일만 다시 쓴다)
  python tools\lm_fixenc.py --check [<파일…>]               # 검사만(파일이 없으면 ROOT 아래 전부) — 문제 있으면 exit 1
  python tools\lm_fixenc.py --all                           # ROOT 아래 .bat·.ps1 전부 변환

변환 규칙: 읽을 때는 UTF-8(BOM 허용) → 실패하면 CP949 로 읽는다(이미 변환된 파일도 그대로 통과 — 멱등).
줄끝은 CRLF 하나로 맞춘다. bat 에 CP949 로 쓸 수 없는 글자(— 등)가 있으면 쓰지 않고 그 줄을 알린다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOM = b"\xef\xbb\xbf"
SKIP_DIRS = {".git", "python", "data", "report", "teamdata", "__pycache__", ".ruff_cache", ".wf", ".claude"}


def _decode(b):
    """UTF-8(BOM 허용) → 실패하면 CP949. (텍스트, 읽은 인코딩)"""
    if b.startswith(BOM):
        b = b[len(BOM):]
    try:
        return b.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return b.decode("cp949"), "cp949"          # 둘 다 아니면 UnicodeDecodeError 를 그대로 올린다


def _crlf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def _lone_lf(b):
    n = 0
    for i, x in enumerate(b):
        if x == 10 and (i == 0 or b[i - 1] != 13):
            n += 1
    return n


def check_bat(b):
    """bat 바이트의 문제 목록 — BOM 없음 · CP949 로 디코드 · LF 단독 0."""
    bad = []
    if b.startswith(BOM):
        bad.append("BOM 있음(bat 은 BOM 없는 CP949)")
    try:
        b.decode("cp949")
    except UnicodeDecodeError as e:
        bad.append(f"CP949 로 읽을 수 없음(위치 {e.start})")
    n = _lone_lf(b)
    if n:
        bad.append(f"LF 단독 {n}개(CRLF 이어야 함)")
    return bad


def check_ps1(b):
    """ps1 바이트의 문제 목록 — UTF-8 BOM · UTF-8 로 디코드 · LF 단독 0."""
    bad = []
    if not b.startswith(BOM):
        bad.append("UTF-8 BOM 없음")
    try:
        b[len(BOM):].decode("utf-8") if b.startswith(BOM) else b.decode("utf-8")
    except UnicodeDecodeError as e:
        bad.append(f"UTF-8 로 읽을 수 없음(위치 {e.start})")
    n = _lone_lf(b)
    if n:
        bad.append(f"LF 단독 {n}개(CRLF 이어야 함)")
    return bad


def to_bat_bytes(b):
    """임의(UTF-8/CP949) 바이트 → CP949 + CRLF 바이트. CP949 로 못 쓰는 글자는 ValueError(줄 번호 포함)."""
    text, _enc = _decode(b)
    text = _crlf(text)
    try:
        return text.encode("cp949")
    except UnicodeEncodeError as e:
        line = text.count("\n", 0, e.start) + 1
        raise ValueError(f"{line}행 '{text[e.start:e.end]}' 는 CP949 로 쓸 수 없습니다 — 다른 글자로 바꾸세요") from None


def to_ps1_bytes(b):
    """임의(UTF-8/CP949) 바이트 → UTF-8 BOM + CRLF 바이트."""
    text, _enc = _decode(b)
    return BOM + _crlf(text).encode("utf-8")


def fix_file(path, kind):
    """kind = 'bat'|'ps1'. 바뀌었으면 다시 쓰고 True. 실패는 예외."""
    with open(path, "rb") as f:
        b = f.read()
    nb = to_bat_bytes(b) if kind == "bat" else to_ps1_bytes(b)
    if nb == b:
        return False
    tmp = path + ".lmfix.tmp"
    with open(tmp, "wb") as f:
        f.write(nb)
    os.replace(tmp, path)
    return True


def scan(root=ROOT):
    """ROOT 아래 .bat·.ps1 (배포 밖 폴더 제외) → [(경로, 'bat'|'ps1')]"""
    out = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in (".bat", ".ps1"):
                out.append((os.path.join(cur, fn), ext[1:]))
    return out


def check_files(items):
    """[(경로, kind)] → {경로: [문제…]} (문제 있는 것만)"""
    res = {}
    for p, kind in items:
        with open(p, "rb") as f:
            b = f.read()
        bad = check_bat(b) if kind == "bat" else check_ps1(b)
        if bad:
            res[p] = bad
    return res


def _kind_of(p):
    ext = os.path.splitext(p)[1].lower()
    return "bat" if ext in (".bat", ".cmd") else "ps1" if ext == ".ps1" else ""


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    items, mode, cur = [], "fix", None
    for a in argv:
        if a == "--check":
            mode = "check"
        elif a == "--all":
            items += scan()
        elif a in ("--bat", "--ps1"):
            cur = a[2:]
        else:
            p = os.path.abspath(a)
            k = cur or _kind_of(p)
            if not k:
                print(f"[fixenc] 종류를 알 수 없는 파일: {a} (--bat / --ps1 뒤에 두세요)")
                return 2
            items.append((p, k))
    if mode == "check" and not items:
        items = scan()
    missing = [p for p, _k in items if not os.path.isfile(p)]
    if missing:
        print("[fixenc] 파일 없음: " + ", ".join(missing))
        return 2
    if mode == "check":
        res = check_files(items)
        for p, bad in res.items():
            print(f"[fixenc] {os.path.relpath(p, ROOT)}: " + " · ".join(bad))
        print(f"[fixenc] 검사 {len(items)}개 — 문제 {len(res)}개")
        return 1 if res else 0
    changed, failed = 0, 0
    for p, k in items:
        try:
            if fix_file(p, k):
                changed += 1
                print(f"[fixenc] 변환: {os.path.relpath(p, ROOT)} → " + ("CP949+CRLF" if k == "bat" else "UTF-8 BOM+CRLF"))
        except (ValueError, UnicodeDecodeError, OSError) as e:
            failed += 1
            print(f"[fixenc] 실패: {os.path.relpath(p, ROOT)} — {e}")
    print(f"[fixenc] {len(items)}개 중 {changed}개 변환, 실패 {failed}개")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
