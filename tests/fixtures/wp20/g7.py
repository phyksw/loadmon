# -*- coding: utf-8 -*-
r"""W-G7 구현 동치 — 참조 구현(`<DESIGN>\worktime_sim.py`)과 제품 시간 코어를 무작위 세계에서 대조한다.

- 참조 사본은 **%TEMP% 아래 임시 폴더에 복사해** `sys.dont_write_bytecode` 로 적재한다(참조 폴더에 __pycache__ 를 만들지
  않는다 — 구현 계획 §2.8). 참조 달력은 제품 `config\calendar.json` 으로 바꿔 끼운다(같은 공휴일 — 대조 조건).
- 참조 위치: 환경 변수 `LM27T_WORKTIME_REF`(파일 경로) → 설계 조사 폴더(<SURVEY> = 시스템 %TEMP% 아래, 구현 계획 §0.2).
  없으면 살아 있는 대조는 건너뛰고, 고정 서명(`g7_ref.json` — 참조로 계산해 둔 세계별 서명)과 대조한다.
- 세계: 참조 `gates.py` 의 퍼즈 분포(기본 하루 · 확장 3일 PC 2대)를 옮기되 두 가지를 제품 입력 모양에 맞췄다 —
  대화 이름은 채널마다 따로(메일 M· · 팀즈 C· — 제품은 thread_key·chat_key 가 다른 키), 회의 참석자 = (주최자, 나)
  (주최자 키가 저장되지 않아 '의뢰자 동석'을 참석자로 판정 — X-204).
- 대조: 봉투 슬롯 집합 · 슬롯별 귀속(대상 → 초) · 업무 경계(종류·등급·근거·시작·끝·차수). 계약 §5.3 동률 규칙
  (u_ 먼저 — 참조는 키 사전순이라 B_ 먼저)에서 오는 ±1초 차이만 허용하고 그 수를 센다.
- 고정 서명은 동률에 둔감한 형(슬롯 · 업무 경계 · 대상별 투입 0.01h)의 sha256 앞 16자다. 다시 만들 때(참조가
  있을 때만, 저장소 루트에서): ``"<PY>" -X utf8 -B -c "import sys; sys.path.insert(0, '.');
  from tests.fixtures.wp20 import g7; g7.main(['freeze', '1000'])" > tests\fixtures\wp20\g7_ref.json``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X
from tests.time.scenarios import W

REF_ENV = "LM27T_WORKTIME_REF"
SURVEY_REL = ("claude", "D----", "64a51721-9ee5-4a94-9a38-158457bc0490", "scratchpad", "lm26_survey", "design",
              "worktime_sim.py")
FROZEN = Path(__file__).resolve().parent / "g7_ref.json"
GEN = "g7/1"
SEEDS = {"base": 7, "ext": 26}
DAY = "2026-10-14"
DOCS = ["설계서_과제A.docx", "원가표_과제B.xlsx", "도면_과제C.dwg"]
CLS = ["office", "office", "cad", "browser", "mail", "chat", "explorer", "other"]
DAYS2 = ["2026-10-16", "2026-10-17", "2026-10-19"]
EPOCH_SHIFT_DAYS = 2192                                # 참조 원점 2026-01-01 − 제품 원점 2020-01-01(일)


def _tmp_base() -> Path:
    from tests.fixtures import tree
    return tree._TMP_BASE


def find_reference() -> Path | None:
    env = os.environ.get(REF_ENV)
    if env and Path(env).is_file():
        return Path(env)
    p = _tmp_base().joinpath(*SURVEY_REL)
    return p if p.is_file() else None


def load_reference(path: Path):
    """참조 사본을 임시 폴더에서 적재(바이트코드 쓰기 없음)."""
    tmp = Path(tempfile.mkdtemp(prefix="lm27t_ref_"))
    dst = tmp / "worktime_sim_ref.py"
    shutil.copyfile(path, dst)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("worktime_sim_ref", dst)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["worktime_sim_ref"] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    mod._CAL = mod.Calendar(path=X.CAL_PATH)
    mod.__lm27_tmp__ = tmp
    return mod


def unload_reference(mod) -> None:
    sys.modules.pop("worktime_sim_ref", None)
    tmp = getattr(mod, "__lm27_tmp__", None)
    if tmp is not None:
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────────── 무작위 세계 ─────────────────────────────
def hm(m: int, day: str = DAY) -> str:
    m = max(0, min(m, 24 * 60 - 1))
    return f"{day} {m // 60:02d}:{m % 60:02d}"


def _conv(r: random.Random, ch: str) -> str:
    return f"M{r.randrange(3)}" if ch == "mail" else f"C{r.randrange(3)}"


def world_base(r: random.Random) -> W:
    n = W("G7", DAY, DAY, "2026-10-30 18:00")
    if r.random() < 0.85:
        n.on("PC1", hm(r.choice([510, 530, 540, 780])), hm(r.choice([1020, 1085, 1140, 1380])))
    if r.random() < 0.6:
        t = 540
        while t < 1080 + r.choice([0, 0, 120, 240]):
            ln = r.choice([5, 10, 20, 30, 45, 60])
            st = r.choices(["active", "idle", "locked"], [0.7, 0.15, 0.15])[0]
            cls = r.choice(CLS)
            doc = r.choice(DOCS) if cls in ("office", "cad") else ""
            n.samp("PC1", hm(t), hm(t + ln), cls if st == "active" else "other", doc if st == "active" else "",
                   state=st)
            t += ln + r.choice([0, 0, 0, 5, 15])
    for _ in range(r.randrange(0, 4)):
        n.doc(hm(r.randrange(480, 1380)), r.choice(["save", "save", "export"]), r.choice(DOCS))
    for _ in range(r.randrange(0, 4)):
        ch = r.choice(["mail", "teams"])
        n.msg(hm(r.randrange(480, 1380)), "out", r.choice(["info", "report", "ack", "request"]), _conv(r, ch), "P1",
              ch, atts=((r.choice(DOCS),) if r.random() < 0.3 else ()), tokens=r.choice([(), ("과제A",), ("원가표",)]))
    for _ in range(r.randrange(0, 5)):
        ch = r.choice(["mail", "teams"])
        n.msg(hm(r.randrange(480, 1200)), "in", r.choice(["info", "request", "question", "report"]), _conv(r, ch),
              r.choice(["P1", "P2"]), ch, direct=r.random() < 0.8, tokens=r.choice([(), ("과제A", "설계서"), ("원가표",)]))
    if r.random() < 0.3:
        a = r.choice([600, 840, 960])
        org = r.choice(["P1", "P2"])
        n.meet(hm(a), hm(a + 60), org, (org, "ME"), ("과제A", "리뷰"), n_att=r.choice([2, 8]))
    return n


def world_ext(r: random.Random) -> W:
    n = W("G7X", DAYS2[0], DAYS2[-1], "2026-10-30 18:00")
    if r.random() < 0.3:
        n.leave(DAYS2[2], r.choice(["am", "pm", "full"]))
    for day in DAYS2:
        for pc in ("PC1", "PC2"):
            if r.random() < 0.5:
                a = r.choice([420, 530, 720, 1200])
                n.on(pc, hm(a, day), hm(min(a + r.choice([60, 240, 600, 900]), 1439), day))
            if r.random() < 0.6:
                t = r.choice([480, 540, 780, 1140])
                end = t + r.choice([120, 300, 600])
                while t < min(end, 1435):
                    ln = r.choice([5, 10, 20, 30, 45, 60])
                    st = r.choices(["active", "idle", "locked"], [0.65, 0.15, 0.2])[0]
                    cls = r.choice(CLS + ["remote", "ide", "cae"])
                    pv = "private" if (st == "active" and r.random() < 0.08) else ("media" if r.random() < 0.03
                                                                                   else "work")
                    doc = r.choice(DOCS) if cls in ("office", "cad") else ""
                    n.samp(pc, hm(t, day), hm(min(t + ln, 1439), day), cls if st == "active" else "other",
                           doc if st == "active" else "", state=st, priv=pv if st == "active" else "work")
                    t += ln + r.choice([0, 0, 5, 15, 40])
        for _ in range(r.randrange(0, 4)):
            n.doc(hm(r.randrange(360, 1440), day), r.choice(["save", "save", "export"]), r.choice(DOCS),
                  pc=r.choice(["PC1", "PC2"]))
        for _ in range(r.randrange(0, 4)):
            ch = r.choice(["mail", "teams"])
            n.msg(hm(r.randrange(360, 1440), day), "out", r.choice(["info", "report", "ack", "request"]), _conv(r, ch),
                  r.choice(["P1", "P2"]), ch, atts=((r.choice(DOCS),) if r.random() < 0.3 else ()),
                  tokens=r.choice([(), ("과제A",), ("원가표",)]))
        for _ in range(r.randrange(0, 6)):
            ch = r.choice(["mail", "teams"])
            n.msg(hm(r.randrange(420, 1260), day), "in", r.choice(["info", "request", "report"]), _conv(r, ch),
                  r.choice(["P1", "P2"]), ch, direct=r.random() < 0.8,
                  tokens=r.choice([(), ("과제A", "설계서"), ("원가표",)]))
        if r.random() < 0.4:
            a = r.choice([600, 750, 840, 1140])
            org = r.choice(["P1", "P2"])
            n.meet(hm(a, day), hm(a + r.choice([30, 60, 90]), day), org, (org, "ME"), ("과제A", "리뷰"),
                   status=r.choice(["accepted", "accepted", "tentative"]), n_att=r.choice([3, 8]))
        if r.random() < 0.15:
            a = r.choice([900, 1020])
            n.comp("PC1", hm(a, day), hm(min(a + 300, 1439), day), "cae", "도면_과제C.dwg")
        if r.random() < 0.2:
            t = r.randrange(600, 1000)
            n.man("work", a=hm(t, day), b=hm(t + 30, day), ref="현장지원")
    return n


def worlds(kind: str, n: int):
    r = random.Random(SEEDS[kind])
    gen = world_base if kind == "base" else world_ext
    for _ in range(n):
        yield gen(r)


# ───────────────────────────── 서명 ─────────────────────────────
def to_ref_world(S, w):
    n = S.W(w.name, w.d0, w.d1, w.as_of, w.note)
    for a in ("samples", "pcon", "msgs", "meets", "docs", "comps", "commits", "manual"):
        setattr(n, a, [dict(x) for x in getattr(w, a)])
    n.leaves, n.coverage, n.cfg, n.shared_docs = dict(w.leaves), dict(w.coverage), dict(w.cfg), set(w.shared_docs)
    return n


def sig_ref(r) -> tuple:
    shift_s = EPOCH_SHIFT_DAYS * 86400
    lab = {t.id: t.label for t in r.tasks}
    slots = sorted(s + shift_s // 300 for s in r.env["slots"])
    asg = {s + shift_s // 300: dict(sorted((lab.get(k, k), v) for k, v in d.items())) for s, d in r.assign.items()}
    tasks = sorted((t.label, t.kind, t.grade, t.cycles[0]["sb"], t.cycles[-1]["eb"], t.cycles[0]["s"] + shift_s,
                    None if t.cycles[-1]["e"] is None else t.cycles[-1]["e"] + shift_s, len(t.cycles))
                   for t in r.tasks)
    return slots, asg, tasks


def sig_prod(res, names) -> tuple:
    lab = {t.id: H.ref_label(names, t.label) for t in res.tasks}
    slots = sorted(res.env.slots)
    asg = {s: dict(sorted((lab.get(k, k), v) for k, v in d.items())) for s, d in res.assign.items()}
    tasks = sorted((H.ref_label(names, t.label), t.kind, t.grade, t.cycles[0].sb, t.cycles[-1].eb, t.cycles[0].s,
                    t.cycles[-1].e, len(t.cycles)) for t in res.tasks)
    return slots, asg, tasks


def tie_only(a: dict, b: dict) -> bool:
    """슬롯 귀속 차이가 정수 동률 규칙(계약 §5.3)의 ±1초뿐인가: 같은 대상·같은 합·각 차 ≤ 1."""
    return set(a) == set(b) and sum(a.values()) == sum(b.values()) and all(abs(a[k] - b[k]) <= 1 for k in a)


def compare(sa: tuple, sb: tuple) -> tuple[list[str], int]:
    """(문제 목록, 동률 차이 슬롯 수)."""
    probs, ties = [], 0
    if sa[0] != sb[0]:
        probs.append("slots")
    for s in sorted(set(sa[1]) | set(sb[1])):
        x, y = sa[1].get(s), sb[1].get(s)
        if x == y:
            continue
        if x is not None and y is not None and tie_only(x, y):
            ties += 1
            continue
        probs.append(f"assign@{s}")
        break
    if sa[2] != sb[2]:
        probs.append("tasks")
    return probs, ties


def robust_digest(sig: tuple) -> str:
    """동률에 둔감한 서명: 슬롯 · 업무 경계 · 대상별 투입(0.01h)."""
    eff: dict = {}
    for d in sig[1].values():
        for k, v in d.items():
            eff[k] = eff.get(k, 0) + v
    body = {"slots": sig[0], "tasks": [list(t) for t in sig[2]],
            "eff": {k: round(v / 3600, 2) for k, v in sorted(eff.items())}}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def run_prod(w, cfg):
    res, names = H.run(w, cfg)
    return sig_prod(res, names)


def freeze(n: int) -> dict:
    ref = find_reference()
    if ref is None:
        raise SystemExit("참조 구현이 없습니다 — " + REF_ENV + " 를 지정하세요")
    S = load_reference(ref)
    cfg = X.base_cfg()
    out = {"schema": "lm27t.g7/1", "generator": GEN, "n": n, "seeds": SEEDS, "digests": {}, "tie_worlds": {}}
    try:
        for kind in ("base", "ext"):
            ds, tw = [], []
            for i, w in enumerate(worlds(kind, n)):
                sr = sig_ref(S.run(to_ref_world(S, w)))
                sp = run_prod(w, cfg)
                ds.append(robust_digest(sr))
                probs, ties = compare(sr, sp)
                if probs:
                    raise SystemExit(f"참조와 다름({kind} #{i}: {probs}) — 고정하지 않는다")
                if robust_digest(sp) != ds[-1]:
                    tw.append(i)
            out["digests"][kind] = ds
            out["tie_worlds"][kind] = tw
    finally:
        unload_reference(S)
    return out


def main(argv) -> int:
    """`freeze <건수>` — 고정 서명 JSON 을 표준 출력으로(파일은 호출자가 받는다)."""
    if len(argv) >= 1 and argv[0] == "freeze":
        k = int(argv[1]) if len(argv) > 1 else 1000
        sys.stdout.write(json.dumps(freeze(k), ensure_ascii=True, sort_keys=True, indent=0) + "\n")
        return 0
    sys.stderr.write("사용: g7.main(['freeze', '<건수>'])\n")
    return 1
