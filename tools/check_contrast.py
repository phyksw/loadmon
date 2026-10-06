# -*- coding: utf-8 -*-
r"""색·대비 관문(REPORTS G-R7 · 계약 L-19) — WP-28.

사용
  "<PY>" -X utf8 -B tools\check_contrast.py [--root <트리>] [--json]

토큰 값의 단일원은 web\common\lm27.css 의 :root 와 lm27\hier\vocab.py 의 DOMAIN_META 다. 이 파일은 16진 색 값을 들고 있지 않고
토큰 이름 · 표(REPORTS §8.1)의 대비 수치 · 용도별 하한만 들고, CSS·DOMAIN_META 의 실제 값으로 WCAG 2.1 대비를 다시 계산한다.

검사
  C1 토큰    §8.1 표의 토큰이 :root 에 모두 있고 형식이 #rrggbb · color-scheme: light · 글자 크기 토큰 하한
             (--fs-body ≥ 13px · --fs-table ≥ 12px · --fs-small ≥ 12px — LM24 밀도, 사용자 결정 2026-10-06)
  C2 대비    토큰 쌍 대비 = 표의 실측값(표기 자릿수로 half-up 반올림해 그 값 이상) · 용도 하한(글자 4.5 · 큰 글자·비글자 3.0 · 순차 밝은 끝 2.0)
  C3 팔레트  범주 팔레트 순서·같은 자리(정규 = DEV · 연장 = MP · 야간 = AX · 휴일 = COM · 무리 업무 = DEV · 산출 = EXT · 사람 = MP ·
             UNC = --ink-faint), 영역 5색 흰 바탕 3:1 이상 — DOMAIN_META 가 아직 없으면(WP-21 전) 경고만
  C4 순차    --seq-1..5: OKLab 명도 단조 감소 · 이웃 ΔL ≥ 0.06 · 색상각 폭 ≤ 10°
  C5 표 칸   --heat-0..5: 명도 단조 감소 · 글자 대비(--ink on 1~4 ≥ 6.1 · --surface on 5 ≥ 6.6)
  C6 위치    web\** 의 .js·.html·.svg 에 16진 색 0(lm27.css 만 허용 — L-19 의 .svg 보강)
종료 코드: 0 통과 · 1 실패 · 2 인자 오류(lm27.css 없음).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # L-05 · 계약 §9.1 — tools\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import ast
import json
import math
import re

CSS_REL = ("web", "common", "lm27.css")
VOCAB_REL = ("lm27", "hier", "vocab.py")
HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
HEX_ANY = re.compile(r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")

TEXT = 4.5          # 본문·표·보조 글자
LARGE = 3.0         # 큰 글자(24px·19px 굵게)·아이콘·차트 마크·비글자 경계
SEQ_LIGHT = 2.0     # 순차 밝은 끝(칸마다 숫자를 늘 씀)

# (앞 토큰, 바탕 토큰, 표의 실측 대비(문자열 — 표기 자릿수 보존) 또는 None, 용도 하한, 용도) — REPORTS §8.1.1~§8.1.3
PAIRS = (
    ("--ink", "--surface", "18.3", TEXT, "본문"),
    ("--ink", "--bg", "16.6", TEXT, "본문(페이지 바탕)"),
    ("--ink-2", "--surface", "9.86", TEXT, "제목 보조·표 머리"),
    ("--ink-2", "--surface-2", "9.26", TEXT, "표 머리"),
    ("--ink-muted", "--surface", "5.38", TEXT, "보조 글자·축 눈금"),
    ("--ink-muted", "--bg", "4.88", TEXT, "보조 글자(페이지 바탕)"),
    ("--ink-muted", "--surface-3", "4.87", TEXT, "보조 글자(선택 행)"),
    ("--ink-faint", "--surface", "3.14", LARGE, "비글자(아이콘·장식선·리드 띠 테두리)"),
    ("--blue", "--surface", "4.42", LARGE, "채움·큰 글자"),
    ("--blue-ink", "--surface", "6.63", TEXT, "링크·활성 pill 글자"),
    ("--blue-ink", "--surface-3", "6.00", TEXT, "활성 pill 글자"),
    ("--blue-ink", "--bg", "6.02", TEXT, "링크(페이지 바탕)"),
    ("--surface", "--blue-btn", "4.97", TEXT, "주 버튼 흰 글자"),
    ("--danger-ink", "--surface", "6.23", TEXT, "위험 버튼"),
    ("--st-good-ink", "--surface", "5.44", TEXT, "상태 글자 good"),
    ("--st-warn-ink", "--surface", "5.93", TEXT, "상태 글자 warn"),
    ("--st-serious-ink", "--surface", "6.57", TEXT, "상태 글자 serious"),
    ("--st-bad-ink", "--surface", "7.75", TEXT, "상태 글자 bad"),
    ("--tag-regular", "--surface", None, LARGE, "꼬리표 정규"),
    ("--tag-extended", "--surface", None, LARGE, "꼬리표 연장"),
    ("--tag-night", "--surface", None, LARGE, "꼬리표 야간"),
    ("--tag-holiday", "--surface", None, LARGE, "꼬리표 휴일"),
    ("--grp-work", "--surface", None, LARGE, "연관 그래프 업무"),
    ("--grp-artifact", "--surface", None, LARGE, "연관 그래프 산출·도구"),
    ("--grp-person", "--surface", None, LARGE, "연관 그래프 사람"),
    ("--seq-1", "--surface", "2.11", SEQ_LIGHT, "순차 밝은 끝"),
    ("--lead-stroke", "--surface", "3.14", LARGE, "리드 띠 테두리"),
    ("--ink", "--heat-1", None, 6.1, "표 칸 농도 1"),
    ("--ink", "--heat-2", None, 6.1, "표 칸 농도 2"),
    ("--ink", "--heat-3", None, 6.1, "표 칸 농도 3"),
    ("--ink", "--heat-4", None, 6.1, "표 칸 농도 4"),
    ("--surface", "--heat-5", "6.63", 6.6, "표 칸 농도 5(흰 글자)"),
)
SEQ = ("--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5")
HEAT = ("--heat-0", "--heat-1", "--heat-2", "--heat-3", "--heat-4", "--heat-5")
OTHER_TOKENS = ("--surface-detail", "--border", "--border-strong", "--grid", "--blue-wash", "--st-good", "--st-warn",
                "--st-serious", "--st-bad", "--lead-fill", "--unattr", "--night-band", "--disabled-bg")
DOMAIN_ORDER = ("DEV", "MP", "EXT", "COM", "AX", "UNC")
# 같은 자리(§8.1.3): CSS 토큰 → 같은 값이어야 하는 업무 영역 코드
SAME_AS_DOMAIN = (("--tag-regular", "DEV"), ("--tag-extended", "MP"), ("--tag-night", "AX"), ("--tag-holiday", "COM"),
                  ("--grp-work", "DEV"), ("--grp-artifact", "EXT"), ("--grp-person", "MP"), ("--ink-faint", "UNC"))
SEQ_MIN_DL = 0.06
SEQ_MAX_HUE = 10.0


# ───────────────────────────── 색 산식 ─────────────────────────────
def hex_rgb(hx):
    h = hx.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(hx):
    """WCAG 2.1 상대 휘도."""
    r, g, b = (_lin(c) for c in hex_rgb(hx))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def oklab(hx):
    r, g, b = (_lin(c) for c in hex_rgb(hx))
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
            1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
            0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc)


def half_up(x, digits):
    s = 10 ** digits
    return math.floor(x * s + 0.5) / s


def digits_of(doc):
    return len(doc.split(".", 1)[1]) if "." in doc else 0


# ───────────────────────────── 읽기 ─────────────────────────────
def parse_root_tokens(css_text):
    """:root { --name: value; … } 의 토큰 사전(주석 제거, 마지막 선언이 이김)."""
    text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    out = {}
    for m in re.finditer(r":root\s*\{([^}]*)\}", text):
        for d in re.finditer(r"(--[A-Za-z0-9-]+)\s*:\s*([^;]+);", m.group(1)):
            out[d.group(1)] = d.group(2).strip()
    return out


def parse_domain_meta(src):
    """vocab.py 의 DOMAIN_META 사전 리터럴에서 {code: color}(실행·import 없이 AST 로만). (사전|None, 문제|None)."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return None, f"vocab.py 구문 오류({e.msg})"
    node = None
    for st in tree.body:
        tg = st.targets if isinstance(st, ast.Assign) else [st.target] if isinstance(st, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "DOMAIN_META" for t in tg):
            node = st.value
    if node is None:
        return None, "DOMAIN_META 가 vocab.py 에 없음"
    if not isinstance(node, ast.Dict):
        return None, "DOMAIN_META 가 사전 리터럴이 아님"
    out = {}
    for k, v in zip(node.keys, node.values, strict=True):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Dict)):
            continue
        for kk, vv in zip(v.keys, v.values, strict=True):
            if isinstance(kk, ast.Constant) and kk.value == "color" and isinstance(vv, ast.Constant):
                out[k.value] = str(vv.value)
    return out, None


def _read(path):
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


# ───────────────────────────── 검사 ─────────────────────────────
class Report:
    def __init__(self):
        self.items = []

    def add(self, level, check, msg):
        self.items.append({"level": level, "check": check, "msg": msg})

    @property
    def errors(self):
        return [i for i in self.items if i["level"] == "error"]

    @property
    def warnings(self):
        return [i for i in self.items if i["level"] == "warn"]


def check_tokens(tok, rep):
    need = {t for p in PAIRS for t in p[:2]} | set(SEQ) | set(HEAT) | set(OTHER_TOKENS)
    for name in sorted(need):
        v = tok.get(name)
        if v is None:
            rep.add("error", "C1", f"토큰 {name} 이 lm27.css :root 에 없음")
        elif not HEX6.match(v):
            rep.add("error", "C1", f"토큰 {name} 값 형식이 #rrggbb 가 아님")


# 글자 크기 하한(R §8.1.5 — LM24 밀도, 사용자 결정 2026-10-06: 본문 13px · 표 12.5px · 주석 12px). 이보다 작게 쓰지 않는다.
FONT_FLOOR = (("--fs-body", 13.0, "본문"), ("--fs-table", 12.0, "표"), ("--fs-small", 12.0, "작은 글자"))
_PX = re.compile(r"^(\d+(?:\.\d+)?)px$")


def check_base(css_text, tok, rep):
    """밝은 화면 선언과 글자 크기 토큰 하한(본문 ≥ 13px · 표 ≥ 12px · 작은 글자 ≥ 12px — R §8.1.5)."""
    if not re.search(r":root\s*\{[^}]*color-scheme\s*:\s*light", re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)):
        rep.add("error", "C1", ":root 에 color-scheme: light 선언 없음")
    for name, floor, use in FONT_FLOOR:
        m = _PX.match(tok.get(name) or "")
        if not m:
            rep.add("error", "C1", f"토큰 {name} 이 없거나 px 값이 아님({use} 글자 크기)")
        elif float(m.group(1)) + 1e-9 < floor:
            rep.add("error", "C1", f"토큰 {name} {m.group(1)}px < 하한 {floor:g}px({use} 글자 — R §8.1.5)")


def _hex(tok, name):
    v = tok.get(name)
    return v.lower() if v and HEX6.match(v) else None


def check_pairs(tok, rep):
    for fg, bg, doc, floor, use in PAIRS:
        a, b = _hex(tok, fg), _hex(tok, bg)
        if not a or not b:
            continue                                   # C1 에서 이미 오류
        r = contrast(a, b)
        if r + 1e-9 < floor:
            rep.add("error", "C2", f"{fg} / {bg} 대비 {half_up(r, 2):.2f}:1 < 하한 {floor}:1 ({use})")
        if doc is not None:
            d = digits_of(doc)
            if half_up(r, d) + 1e-9 < float(doc):
                rep.add("error", "C2", f"{fg} / {bg} 대비 {half_up(r, 2):.2f}:1 < 표의 값 {doc}:1 ({use}, REPORTS §8.1)")
        rep.add("ok", "C2", f"{fg} / {bg} {half_up(r, 2):.2f}:1 ({use})")


def check_palette(tok, domains, rep):
    if domains is None:
        rep.add("warn", "C3", "DOMAIN_META 가 아직 없어 영역 팔레트 대조를 건너뜀(WP-21 전)")
        return
    missing = [c for c in DOMAIN_ORDER if c not in domains]
    if missing:
        rep.add("error", "C3", f"DOMAIN_META 에 영역 코드 없음: {', '.join(missing)}")
    present = [c for c in domains if c in DOMAIN_ORDER]
    if present != [c for c in DOMAIN_ORDER if c in domains]:
        rep.add("error", "C3", f"DOMAIN_META 순서가 §8.1.3(DEV MP EXT COM AX UNC)과 다름: {' '.join(present)}")
    for code in DOMAIN_ORDER:
        col = domains.get(code)
        if col is None:
            continue
        if not re.match(r"^#[0-9a-f]{6}$", col):
            rep.add("error", "C3", f"DOMAIN_META['{code}'] 색 형식이 ^#[0-9a-f]{{6}}$ 가 아님")
            continue
        if code != "UNC" and contrast(col, tok.get("--surface", "#ffffff").lower()) + 1e-9 < LARGE:
            rep.add("error", "C3", f"DOMAIN_META['{code}'] 색이 흰 바탕 3:1 미만")
    for token, code in SAME_AS_DOMAIN:
        a, b = _hex(tok, token), (domains.get(code) or "").lower()
        if a and b and a != b:
            rep.add("error", "C3", f"{token} 와 DOMAIN_META['{code}'] 가 같은 값이어야 함(§8.1.3 같은 자리)")


def check_seq(tok, rep):
    vals = [_hex(tok, t) for t in SEQ]
    if not all(vals):
        return
    labs = [oklab(v) for v in vals]
    for i in range(1, len(labs)):
        dl = labs[i - 1][0] - labs[i][0]
        if dl < SEQ_MIN_DL:
            rep.add("error", "C4", f"{SEQ[i - 1]} → {SEQ[i]} 명도 차 {dl:.3f} < {SEQ_MIN_DL}(단조 감소·이웃 구분)")
    hues = [math.degrees(math.atan2(b, a)) for _l, a, b in labs]
    width = max(hues) - min(hues)
    if width > SEQ_MAX_HUE:
        rep.add("error", "C4", f"순차 색상각 폭 {width:.1f}° > {SEQ_MAX_HUE}°(단일 색상)")


def check_heat(tok, rep):
    vals = [_hex(tok, t) for t in HEAT]
    if not all(vals):
        return
    ls = [oklab(v)[0] for v in vals]
    for i in range(1, len(ls)):
        if ls[i] >= ls[i - 1]:
            rep.add("error", "C5", f"{HEAT[i]} 명도가 {HEAT[i - 1]} 보다 밝음(농도 단조 아님)")


def check_hex_places(root, rep):
    base = os.path.join(root, "web")
    if not os.path.isdir(base):
        return
    allowed = os.path.normcase(os.path.join(root, *CSS_REL))
    for dp, dns, fns in os.walk(base):
        dns[:] = sorted(d for d in dns if d not in ("__pycache__",))
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            if os.path.normcase(p) == allowed or os.path.splitext(fn)[1].lower() not in (".js", ".html", ".svg", ".css"):
                continue
            try:
                text = _read(p)
            except (OSError, UnicodeDecodeError) as e:
                rep.add("error", "C6", f"{os.path.relpath(p, root)} 읽기 실패({type(e).__name__})")
                continue
            for i, ln in enumerate(text.split("\n"), 1):
                if HEX_ANY.search(ln):
                    rep.add("error", "C6", f"{os.path.relpath(p, root)}:{i} 16진 색 — 색은 lm27.css 토큰·DOMAIN_META 에만(G-R7)")


def run(root):
    rep = Report()
    css_path = os.path.join(root, *CSS_REL)
    if not os.path.isfile(css_path):
        return None
    css_text = _read(css_path)
    tok = parse_root_tokens(css_text)
    check_tokens(tok, rep)
    check_base(css_text, tok, rep)
    check_pairs(tok, rep)
    vp = os.path.join(root, *VOCAB_REL)
    if os.path.isfile(vp):
        domains, why = parse_domain_meta(_read(vp))
        if why:
            rep.add("error", "C3", why)
        else:
            check_palette(tok, domains, rep)
    else:
        check_palette(tok, None, rep)
    check_seq(tok, rep)
    check_heat(tok, rep)
    check_hex_places(root, rep)
    return rep


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        rc = getattr(st, "reconfigure", None)
        if rc is not None:
            rc(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="check_contrast.py", description="LM27 색·대비 관문(G-R7)")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = run(os.path.abspath(a.root))
    if rep is None:
        print("check_contrast: web\\common\\lm27.css 없음", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"errors": rep.errors, "warnings": rep.warnings,
                          "ok": [i for i in rep.items if i["level"] == "ok"]}, ensure_ascii=False, indent=1))
    else:
        for it in rep.items:
            if it["level"] != "ok":
                print(f"[{'오류' if it['level'] == 'error' else '경고'}] {it['check']} {it['msg']}")
        print(f"check_contrast: 오류 {len(rep.errors)} · 경고 {len(rep.warnings)} · 대비 쌍 {len(PAIRS)}")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
