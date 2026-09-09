# -*- coding: utf-8 -*-
r"""FILES.txt 재생성 — 자가점검.py 의 NEED 순서대로 크기·crc32 를 적는다.

  python tools\update_files.py              # 이 트리(tools\ 의 부모)의 FILES.txt 를 다시 쓴다
  python tools\update_files.py --check      # 쓰지 않고 지금 FILES.txt 와 실제 파일을 대조만 (불일치·누락이면 exit 1)
  python tools\update_files.py <root>       # 다른 트리를 지정 (--check 와 같이 써도 된다)

파일을 하나라도 고쳤으면 배포 전에 한 번 돌린다. tools\Make-Package.ps1 이 FILES.txt 의 크기·crc 를
실제 파일과 대조해 다르면 담지 않고 멈춘다 — README·ui\app.py 를 고친 뒤 FILES.txt 를 다시 만들지
않아 낡은 목록이 배포 zip 에 실렸던 일(실측)의 재발 방지. 형식(NEED 순서 · '크기 B  crc32')은 그대로다.
"""
import ast
import io
import os
import re
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

HEAD = ["LoadMonitor23 필수 파일 목록 - 복사 시 전부 있어야 합니다.",
        "(data/ report/ teamdata/ 는 복사 금지 - 개인정보)", ""]
LINE_RE = re.compile(r"^(\S.*?)\s{2,}([\d,]+) B\s+([0-9a-f]{8})\s*$")


def need_list(root):
    """자가점검.py 의 NEED — 임포트하지 않고(실행하면 점검이 돌고 sys.exit) ast 로만 읽는다."""
    src = open(os.path.join(root, "자가점검.py"), encoding="utf-8-sig").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "NEED":
            return list(ast.literal_eval(node.value))
    raise SystemExit("[!] 자가점검.py 에서 NEED 를 찾지 못했습니다")


def crc_of(path):
    b = open(path, "rb").read()
    return len(b), f"{zlib.crc32(b) & 0xffffffff:08x}"


def build(root, need):
    lines = HEAD + [f"총 {len(need)}개", ""]
    miss = []
    for rel in need:
        if rel == "FILES.txt":
            lines.append(f"{rel:<50} {'(이 파일)':>12}")
            continue
        p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(p):
            miss.append(rel)
            continue
        size, crc = crc_of(p)
        lines.append(f"{rel:<50} {size:>9,} B  {crc}")
    return lines, miss


def parse(files_txt):
    """FILES.txt → {rel: (size, crc)} — tools\\Make-Package.ps1 과 같은 규칙으로 읽는다."""
    out = {}
    for ln in open(files_txt, encoding="utf-8-sig"):
        m = LINE_RE.match(ln.rstrip("\n"))
        if m:
            out[m.group(1).strip()] = (int(m.group(2).replace(",", "")), m.group(3))
    return out


def check(root, need):
    files_txt = os.path.join(root, "FILES.txt")
    if not os.path.exists(files_txt):
        return ["FILES.txt 없음"]
    listed = parse(files_txt)
    bad = []
    for rel in need:
        if rel == "FILES.txt":
            continue
        p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(p):
            bad.append(f"{rel}: 파일 없음")
        elif rel not in listed:
            bad.append(f"{rel}: FILES.txt 에 없음")
        elif crc_of(p) != listed[rel]:
            size, crc = crc_of(p)
            bad.append(f"{rel}: FILES.txt {listed[rel][0]:,} B {listed[rel][1]} != 실제 {size:,} B {crc}")
    bad += [f"{rel}: NEED 에 없는 항목" for rel in sorted(set(listed) - set(need))]
    return bad


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    root = os.path.abspath(args[0]) if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    need = need_list(root)
    if "--check" in argv:
        bad = check(root, need)
        if bad:
            print(f"[!] FILES.txt 가 현재 트리와 다릅니다 ({len(bad)}건) — python tools\\update_files.py 로 다시 만드세요")
            for x in bad:
                print("    " + x)
            return 1
        print(f"[OK] FILES.txt 일치 — {len(need)}개")
        return 0
    lines, miss = build(root, need)
    if miss:
        print("[!] 누락:", miss)
        return 1
    with open(os.path.join(root, "FILES.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"FILES.txt {len(need)}줄 작성 — {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
