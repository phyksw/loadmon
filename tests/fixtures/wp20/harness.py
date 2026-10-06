# -*- coding: utf-8 -*-
r"""WP-20 시험 하네스 — WP-19 시나리오 작성기(`tests.time.scenarios`, 읽기만)로 만든 합성 세계를 `analyze_time` 에 넣고,
결과를 참조 구현(`design\worktime_sim.py`)의 표기로 되돌려 골든·동치 대조를 한다.

- 업무 표지 대응(완료 기준 'unit_id 대응 어댑터는 시험 안'): 제품 표지는 키로만 만든다(`S1:<대화 키>#n` ·
  `SELF:<문서군 키>@MM-DD` …). 여기서 시나리오가 아는 이름으로 되돌린다(대화 키 → 대화 이름, 문서 키 → 문서군 이름,
  msg_key → 메시지 키).
- 동률 순서 대조용 unit_id: 참조 구현은 `u_ + HMAC(시뮬레이터 키, '종류|키')` 의 사전순으로 동률을 깬다. 골든·동치
  시험은 같은 동률 순서를 쓰도록 `ref_unit_key(names)`(호출 가능 unit_id 키 — 제품 API `person_key` 의 한 형태)를 넘긴다.
  시뮬레이터 키는 참조 구현의 공개 시험 상수다(제품 키 아님).
- 자리표시자만(사람 P1~P40 · 과제A~J · 고객사A). 실데이터 없음.
"""
from __future__ import annotations

import hashlib
import hmac
import random
from dataclasses import dataclass, field

from tests.time import scenarios as X
from lm27.time import analyze_time
from lm27.time.calendar import SLOT, d_of, day0

SIM_KEY = b"lm27-sim-person-key"                 # 참조 구현 시뮬레이터 키(공개 시험 상수 — 동률 순서 대조 전용)
TEST_KEY = hashlib.sha256(b"lm27-wp20-synthetic-unit-key").digest()   # 시험 전용 'unit' 하위 키(32B)
TAG_KO = {v: k for k, v in X.TAG_CODES.items()}  # regular → 정규 …


@dataclass
class Names:
    """제품 키 → 시나리오 이름(참조 표기)."""
    msg: dict = field(default_factory=dict)      # msg_key → 메시지 키(k1 …)
    conv: dict = field(default_factory=dict)     # thread_key·chat_key → 대화 이름
    fam: dict = field(default_factory=dict)      # doc_key(d16) → 문서군 이름(fam)
    ref: dict = field(default_factory=dict)      # 수동 기록 참조 doc_key → 원래 참조 이름
    meet: dict = field(default_factory=dict)     # 일정 msg_key(e24) → 회의 id(mt1 …)


def names_of(w) -> Names:
    n = Names()
    for m in w.msgs:
        n.msg[X.msg_key(m["key"])] = m["key"]
        n.conv[X.thread_key(m["conv"]) if m["ch"] == "mail" else X.chat_key(m["conv"])] = m["conv"]
    docs = [s["doc"] for s in w.samples if s["doc"]] + [d["doc"] for d in w.docs] + \
        [a for m in w.msgs for a in m["atts"]] + [c["doc"] for c in w.comps if c["doc"]]
    for nm in docs:
        n.fam[X.doc_key(nm)] = X.fam(nm)
    for m in w.manual:
        if m["ref"] and m["kind"] != "attended":
            n.ref[X.doc_key(m["ref"])] = m["ref"]
            n.fam.setdefault(X.doc_key(m["ref"]), X.fam(m["ref"]))
    for mt in w.meets:
        n.meet[X.cal_key(mt["id"])] = mt["id"]
    return n


def _fam_name(names: Names, f: str) -> str:
    base = f.split("@", 1)[0]
    return names.fam.get(base, f)


def ref_start_key(names: Names, start: str, kind: str) -> str:
    """제품 시작 근거 키 → 참조 구현의 키(동률 순서 대조용)."""
    if kind in ("S1", "ACK", "COORD", "REPORT_ONLY"):
        return names.msg.get(start, start)
    if kind == "SELF":
        f, _, d = start.rpartition("|")
        return f"{_fam_name(names, f)}|{d}"
    if kind == "MANUAL" and start.startswith("manual:"):
        r = start[len("manual:"):]
        return "manual:" + names.ref.get(r, r)
    return start


def ref_unit_key(names: Names):
    """참조 구현과 같은 unit_id(u_ + HMAC(SIM_KEY, '종류|키')[:10]) — 동률 순서가 참조와 같아진다."""
    def fn(start: str, kind: str) -> str:
        key = ref_start_key(names, start, kind)
        return "u_" + hmac.new(SIM_KEY, f"{kind}|{key}".encode(), hashlib.sha256).hexdigest()[:10]
    return fn


def ref_label(names: Names, label: str) -> str:
    """제품 업무 표지 → 참조 표지."""
    kind, _, rest = label.partition(":")
    if kind in ("S1", "COORD", "ACK"):
        conv, _, num = rest.rpartition("#")
        return f"{kind}:{names.conv.get(conv, conv)}#{num}"
    if kind == "SELF":
        f, _, mmdd = rest.rpartition("@")
        return f"SELF:{_fam_name(names, f)}@{mmdd}"
    if kind == "REPORT":
        return f"REPORT:{names.conv.get(rest, rest)}"
    if kind == "MANUAL":
        return f"MANUAL:{names.ref.get(rest, rest)}"
    return label


def run(w, cfg=None, *, unit_key=None, ref_ids=True, shuffle=None, labels=None, records=None):
    """W(중립 세계) → (TimeResult, Names). shuffle = 입력 행 순서를 섞을 난수 시드."""
    base = cfg or X.base_cfg()
    recs, profile, as_of, tags, over = X.to_inputs(w, base)
    if records is not None:
        recs = records
    if shuffle is not None:
        recs = list(recs)
        random.Random(shuffle).shuffle(recs)
    c = base.derive(over) if over else base
    names = names_of(w)
    uk = unit_key if unit_key is not None else (ref_unit_key(names) if ref_ids else TEST_KEY)
    res = analyze_time(uk, recs, profile, X.calendar(), as_of, cfg=c, tags=tags, labels=labels)
    return res, names


def gen_months(months: float = 3, seed: int = 26, per_day=(300, 250, 150, 4, 6)):
    """성능 세계(참조 `gates.gen` 분포 — 사람 1명, 근무일당 샘플 300·메시지 250·저장 150·회의 4·커밋 6, 의뢰 6건).
    반환 (W, 신호 수). 대화 이름은 채널마다 따로(메일 R… · 팀즈 T…)."""
    import datetime as dt
    n_seg, n_msg, n_save, n_meet, n_commit = per_day
    r = random.Random(seed)
    d0 = dt.date(2026, 9, 1)
    d1 = d0 + dt.timedelta(days=int(30 * months) - 1)
    cal = X.calendar()
    w = X.W("PERF", d0.isoformat(), d1.isoformat(), f"{(d1 + dt.timedelta(days=1)).isoformat()} 09:00")
    fam_pool, threads = [], []
    tok = ["원가", "회로", "도면", "시험", "해석", "센서", "하네스", "모터", "브라켓", "사양", "일정", "품질", "양산", "보정"]
    req = 0
    d = d0
    while d <= d1:
        s = d.isoformat()
        if cal.is_holiday(d):
            d += dt.timedelta(days=1)
            continue
        for _k in range(6):
            req += 1
            ch = r.choice(["mail", "teams"])
            th = (f"R{req}", ch)
            tk = tuple(r.sample(tok, 2))
            fam_pool.append(f"{tk[0]}_{tk[1]}_과제{req % 37}.xlsx")
            threads.append(th)
            mm = r.randrange(9 * 60, 17 * 60)
            w.msg(f"{s} {mm // 60:02d}:{mm % 60:02d}", "in", "request", th[0], f"P{r.randrange(20)}", ch, tokens=tk)
        active = fam_pool[-25:]
        w.on("PC1", f"{s} 08:50", f"{s} 18:10")
        step = (8 * 60) / n_seg
        for k in range(n_seg):
            a = int(9 * 60 + k * step)
            if 12 * 60 <= a < 13 * 60:
                a += 60
            a = min(a, 18 * 60 - 2)
            b = min(a + max(1, int(step)), 18 * 60)
            if b <= a:
                continue
            cls = r.choice(["office", "office", "office", "cad", "browser", "mail", "chat", "explorer"])
            doc = r.choice(active) if cls in ("office", "cad") else ""
            w.samp("PC1", f"{s} {a // 60:02d}:{a % 60:02d}", f"{s} {b // 60:02d}:{b % 60:02d}", cls, doc)
        w.samp("PC1", f"{s} 12:00", f"{s} 13:00", "other", state="locked")
        if r.random() < 0.2:
            w.samp("PC1", f"{s} 20:00", f"{s} 21:30", "office", r.choice(active))
            w.doc(f"{s} 21:20", "save", r.choice(active))
        for _k in range(n_save):
            mm = r.randrange(9 * 60, 18 * 60)
            w.doc(f"{s} {mm // 60:02d}:{mm % 60:02d}", r.choice(["save", "save", "save", "export"]), r.choice(active))
        for _k in range(n_msg):
            mm = r.randrange(8 * 60, 19 * 60)
            dirn = "in" if r.random() < 0.65 else "out"
            th = r.choice(threads[-60:])
            act = r.choice(["info", "info", "question", "ack", "notice"]) if dirn == "in" else \
                r.choice(["info", "ack", "report", "question"])
            atts = (r.choice(active),) if (dirn == "out" and act == "report" and r.random() < 0.7) else ()
            w.msg(f"{s} {mm // 60:02d}:{mm % 60:02d}", dirn, act, th[0], f"P{r.randrange(20)}", th[1],
                  direct=r.random() < 0.7, atts=atts, tokens=tuple(r.sample(tok, 2)))
        for _k in range(n_meet):
            mm = r.choice([9 * 60 + 30, 10 * 60 + 30, 14 * 60, 15 * 60 + 30, 16 * 60 + 30])
            org = f"P{r.randrange(20)}"
            w.meet(f"{s} {mm // 60:02d}:{mm % 60:02d}", f"{s} {(mm + 60) // 60:02d}:{(mm + 60) % 60:02d}",
                   org, (org, "ME"), tuple(r.sample(tok, 2)))
        for _k in range(n_commit):
            mm = r.randrange(9 * 60, 18 * 60)
            w.commit(f"{s} {mm // 60:02d}:{mm % 60:02d}", "repoA")
        d += dt.timedelta(days=1)
    total = len(w.samples) + len(w.msgs) + len(w.docs) + len(w.meets) + len(w.commits) + len(w.pcon)
    return w, total


def fmt_t(t: int | None) -> str:
    """참조 fmt('%m-%d %H:%M')."""
    if t is None:
        return "-"
    d = d_of(t)
    m = (t - day0(d)) // 60
    return f"{d.month:02d}-{d.day:02d} {m // 60:02d}:{m % 60:02d}"


def summarize(res, names: Names) -> dict:
    """참조 `scenarios.golden_of` 와 같은 모양(h 소수 2자리 · 한글 꼬리표)."""
    eff = res.effort()
    tasks = []
    for t in res.tasks:
        c0, cl = t.cycles[0], t.cycles[-1]
        lead = None
        if cl.e is not None and not c0.unstarted:
            lead = round(sum(c.e - c.s for c in t.cycles if c.e is not None) / 3600, 2)
        tasks.append([ref_label(names, t.label), t.kind, round(eff.get(t.id, 0) / 3600, 2), t.grade, c0.sb, cl.eb,
                      fmt_t(c0.s), fmt_t(cl.e) if cl.e is not None else "-", lead, len(t.cycles),
                      round(t.pre_request_s / 3600, 2), round(t.machine_s / 3600, 2)])
    tags = {}
    for code, mins in sorted(res.env.tag_minutes().items(), key=lambda x: TAG_KO[x[0]]):
        tags[TAG_KO[code]] = round(mins / 60, 2)
    buckets = {k: round(v / 3600, 2) for k, v in sorted(res.bucket_sec().items()) if v > 0}
    queue = sorted({q.code for q in res.queue})
    mm = {}
    for (y, m), row in sorted(res.months.items()):
        if not row["env_min"] and not row["covered_workdays"]:
            continue
        lp = row["load_pct"]
        mm[f"{y}-{m:02d}"] = {"mm": round(row["mm"], 4), "load": (round(lp / 100, 4) if lp else None),
                              "avail": round(row["avail_days"], 2), "ot": round(row["overtime_window_min"] / 60, 2),
                              "wd": row["workdays"]}
    return {"env": round(len(res.env.slots) * SLOT / 3600, 2), "tags": tags, "buckets": buckets, "queue": queue,
            "mm": mm, "tasks": tasks}
