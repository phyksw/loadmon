# -*- coding: utf-8 -*-
"""lint 관문 8 — 상위(Level 1) 어휘 단일원 검사.

v2 까지는 어휘·색·정렬·엑셀 단계·프롬프트가 5~7곳에 raw 사전으로 흩어져 있어, 범주를 바꿀 때
'한 세트'를 사람이 기억해야 했고 빠진 곳은 회색·맨뒤·'기타'로 **조용히** 틀렸다(v24.15·v24.18
실제 반복). v3 는 details.L1_META 단일원에서 파생한다 — 이 검사는 그 계약이 다시 깨지는 것을
기계가 막는다:
  ① L1_META 가 LEVEL1_SET 전부와 별칭 대상 전부를 덮는가(색·정렬·단계·프롬프트 파생 가능)
  ② 단일원 밖 하드코딩 재출현 금지 — 색 사전·STAGE_BY_L1·JS L1C 리터럴·프롬프트 리터럴
사용: python tools/check_l1.py   (저장소 루트에서 · exit 0/1)
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
fail = 0


def bad(msg):
    global fail
    fail = 1
    print("[l1] " + msg)


# ── ① 단일원 완결성 ──
try:
    import details as D
except ImportError as e:
    print(f"[l1] core/details 임포트 실패: {e}")
    sys.exit(1)

need = set(D.LEVEL1_SET) | set(D.LEVEL1_ALIAS.values())
missing = sorted(n for n in need if n not in D.L1_META and (D.snap1(n) or n) not in D.L1_META)
if missing:
    bad(f"L1_META 에 없는 상위 이름: {missing} — 색·정렬·단계가 기본값으로 조용히 틀립니다")
for n in sorted(need | set(D.LEVEL1_ALIAS)):
    c, o, st = D.l1_color(n), D.l1_order(n), D.l1_stage(n)
    if not (isinstance(c, str) and c.startswith("#") and isinstance(o, int) and st):
        bad(f"파생 실패: {n!r} → color={c!r} order={o!r} stage={st!r}")

# ── ② 단일원 밖 하드코딩 재출현 금지 ──
RULES = [
    # (파일, 정규식, 설명) — details.py 자신은 검사 대상이 아니다
    ("flow.py", r"L1_ORDER\s*=\s*\{[^}]*\d", "flow 에 정렬 사전 재출현"),
    ("freeze.py", r"_L1C\s*=\s*\{[^}]*#[0-9a-f]{6}", "freeze 에 색 사전 리터럴 재출현"),
    ("core/board.py", r"STAGE_BY_L1\s*=\s*\{[^}]*:", "board 에 단계 사전 재출현"),
    ("ui/app.py", r'const\s+L1C\s*=\s*\{\s*"', "ui JS 에 색 사전 리터럴 재출현"),
    ("refine.py", r'l1 = 업무 성격 \(개발', "refine 프롬프트 하드코딩 재출현(l1_prompt_lines 을 쓰세요)"),
]
for rel, pat, why in RULES:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    try:
        src = open(p, encoding="utf-8").read()
    except OSError:
        bad(f"{rel} 을 읽지 못했습니다")
        continue
    m = re.search(pat, src)
    if m:
        ln = src[:m.start()].count(chr(10)) + 1
        bad(f"{rel}:{ln}: {why} — details.L1_META 파생 함수(l1_color/l1_order/l1_stage)를 쓰세요")

# 프롬프트 생성 마커 — refine 이 단일원 생성을 실제로 쓰는가
rp = open(os.path.join(ROOT, "refine.py"), encoding="utf-8").read()
if "l1_prompt_lines()" not in rp:
    bad("refine.py 가 l1_prompt_lines() 를 쓰지 않습니다 — 상위 정의가 프롬프트에 하드코딩됐을 수 있음")

if fail == 0:
    print(f"[l1] 단일원 OK — 범주 {len(D.L1_META)}개 · 별칭 {len(D.LEVEL1_ALIAS)}개 파생 일치")
sys.exit(fail)
