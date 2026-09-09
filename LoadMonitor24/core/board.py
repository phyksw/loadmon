# -*- coding: utf-8 -*-
"""
board.py — 팀 MM 배분표 엔진.

이 도구의 전제(실측으로 확인됨):
  MM은 '측정값'이 아니라 '배분값'이다. 사람별 mm_12mo 합계는 12(=12개월) 근방에 수렴하며,
  표가 묻는 것은 "내 12개월을 100%로 놓고 어디에 얼마씩 갔나"이다.
  따라서 이 엔진은 시간을 추정하지 않는다. 배분을 편집·검증·집계할 뿐이다.

책임:
  1) 매핑데이터 로드            load_board()
  2) 파생 15열 재계산            recompute()      — 사람이 채우는 건 8열뿐
  3) 집계 3종 산출              aggregates()     — AX과제·파트·프로젝트X과제
  4) 정합성 검증                validate()       — 이중계상·정원초과·빈 상세설명 등
  5) 엑셀 되쓰기                write_board()    — 항상 사본에 먼저
"""
import os
from collections import Counter, defaultdict

MAP_SHEET = "매핑데이터"
COLS = ["row_id", "Function", "Level 1", "Level 2", "Level 3", "이름", "상세설명",
        "mm_12mo", "mm_avg", "과제코드1", "과제코드2", "과제코드3", "대표AI", "근거",
        "확신도", "인원구분", "단계", "mm_run3", "n코드", "분할mm", "인원카운트",
        "인원카운트(≥0.1)", "파트인원헬퍼"]
# 사람이 실제로 입력하는 열 (나머지는 전부 파생)
INPUT_COLS = ["Function", "Level 1", "Level 2", "Level 3", "이름", "상세설명",
              "mm_12mo", "mm_run3", "과제코드1", "과제코드2", "과제코드3", "확신도", "인원구분"]
STAGE_BY_L1 = {"신제품개발": "개발", "기술 내재화": "개발", "양산준비": "양산준비",
               "일반업무": "기타", "표준 특허": "기타"}
MIN_SHARE = 0.1        # '실질 관여' 임계 (월 0.1MM ≈ 반나절/월)


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _s(v):
    return "" if v is None else str(v).strip()


def load_board(path, sheet=MAP_SHEET):
    """엑셀 → [dict] (읽기 전용). openpyxl 필요."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    hdr = [_s(h) for h in next(it)]
    rows = []
    for n, r in enumerate(it, start=2):          # n = 실제 시트 행 번호(헤더가 1행)
        if not any(c not in (None, "") for c in r):
            continue
        d = {hdr[i]: r[i] for i in range(min(len(hdr), len(r))) if hdr[i]}
        if not _s(d.get("이름")):
            continue
        # 빈 행·소계 행을 건너뛰므로 리스트 순번 ≠ 시트 행이다. write_board 가 순번으로
        # 되쓰면 그 아래 전원의 값이 한 칸씩 밀려 남의 행을 덮어쓴다 — 실제 행을 들고 다닌다.
        d["_sheet_row"] = n
        rows.append(d)
    wb.close()
    return rows


def codes_of(row):
    return [_s(row.get(f"과제코드{i}")) for i in (1, 2, 3) if _s(row.get(f"과제코드{i}"))]


def recompute(rows, lookup=None):
    """파생 15열을 규칙으로 다시 채운다. (원본 값은 건드리지 않고 새 dict 반환)
    lookup: {과제코드1: (대표AI, 근거)} — 없으면 데이터에서 최빈값으로 학습한다."""
    if lookup is None:
        lookup = learn_lookup(rows)
    out = [dict(r) for r in rows]
    for r in out:
        mm12 = _num(r.get("mm_12mo"))
        r["mm_avg"] = round(mm12 / 12.0, 6)
        r["n코드"] = len(codes_of(r))
        r["분할mm"] = round(r["mm_avg"] / r["n코드"], 6) if r["n코드"] else 0.0
        r["단계"] = STAGE_BY_L1.get(_s(r.get("Level 1")), "기타")
        c1 = _s(r.get("과제코드1"))
        if c1 in lookup:
            ai, ev = lookup[c1]
            r["대표AI"] = r.get("대표AI") or ai
            r["근거"] = r.get("근거") or ev
    # 인원카운트류 — 같은 사람이 같은 코드/파트에 여러 행을 가져도 합이 정수(고유 인원수)가 되게
    def _share(key_fn, cond):
        grp = defaultdict(int)
        for r in out:
            if cond(r):
                grp[key_fn(r)] += 1
        for r in out:
            if not cond(r):
                r["__v"] = 0.0
            else:
                n = grp[key_fn(r)]
                r["__v"] = round(1.0 / n, 6) if n else 0.0

    _share(lambda r: (_s(r["이름"]), _s(r.get("과제코드1"))), lambda r: r["mm_avg"] > 0)
    for r in out:
        r["인원카운트"] = r.pop("__v")
    _share(lambda r: (_s(r["이름"]), _s(r.get("과제코드1"))), lambda r: r["mm_avg"] >= MIN_SHARE)
    for r in out:
        r["인원카운트(≥0.1)"] = r.pop("__v")
    _share(lambda r: (_s(r["이름"]), _s(r.get("Function"))),
           lambda r: r["mm_avg"] > 0 and _s(r.get("인원구분")) == "재직")
    for r in out:
        r["파트인원헬퍼"] = r.pop("__v")
    for i, r in enumerate(out):
        r.setdefault("row_id", i)
    return out


def learn_lookup(rows):
    """과제코드1 → (대표AI, 근거) 룩업을 데이터에서 학습 (사실상 고정 테이블)"""
    ai = defaultdict(Counter)
    ev = defaultdict(Counter)
    for r in rows:
        c = _s(r.get("과제코드1"))
        if not c:
            continue
        if _s(r.get("대표AI")):
            ai[c][_s(r["대표AI"])] += 1
        if _s(r.get("근거")):
            ev[c][_s(r["근거"])] += 1
    return {c: (ai[c].most_common(1)[0][0] if ai[c] else "",
                ev[c].most_common(1)[0][0] if ev[c] else "") for c in set(ai) | set(ev)}


def aggregates(rows, headcount=None):
    """집계 3종 — 전부 매핑데이터의 group-by (엑셀 시트와 전 셀 일치 검증됨)"""
    headcount = headcount or {}
    funcs = sorted({_s(r.get("Function")) for r in rows if _s(r.get("Function"))})
    tot = sum(_num(r.get("mm_avg")) for r in rows) or 1e-9

    # ① AX 과제별
    by_code = {}
    for r in rows:
        c1 = _s(r.get("과제코드1"))
        if not c1:
            continue
        d = by_code.setdefault(c1, {"code": c1, "mm": 0.0, "by_func": defaultdict(float),
                                    "plan": 0.0, "conf_high": 0.0, "run3": 0.0,
                                    "people": 0.0, "people_01": 0.0, "rows": 0})
        mm = _num(r.get("mm_avg"))
        d["mm"] += mm
        d["by_func"][_s(r.get("Function"))] += mm
        if _s(r.get("인원구분")) != "재직":
            d["plan"] += mm
        if _s(r.get("확신도")) == "상":
            d["conf_high"] += mm
        d["run3"] += _num(r.get("mm_run3"))
        d["people"] += _num(r.get("인원카운트"))
        d["people_01"] += _num(r.get("인원카운트(≥0.1)"))
        d["rows"] += 1
    split = defaultdict(float)          # 분할배분 — 코드1~3에 나눠 담아 총량 보존
    for r in rows:
        for c in codes_of(r):
            split[c] += _num(r.get("분할mm"))
    for c, d in by_code.items():
        d["split_mm"] = round(split.get(c, 0.0), 4)
        d["share"] = d["mm"] / tot
        d["by_func"] = {f: round(d["by_func"].get(f, 0.0), 4) for f in funcs}
        for k in ("mm", "plan", "conf_high", "run3", "people", "people_01"):
            d[k] = round(d[k], 4)

    # ② 파트별 로드율
    by_part = {}
    for f in funcs:
        rs = [r for r in rows if _s(r.get("Function")) == f]
        mm_active = sum(_num(r.get("mm_avg")) for r in rs if _s(r.get("인원구분")) == "재직")
        mm_all = sum(_num(r.get("mm_avg")) for r in rs)
        named = sum(_num(r.get("파트인원헬퍼")) for r in rs)
        cap = _num(headcount.get(f), 0)
        by_part[f] = {"part": f, "정원": cap, "실명인원": round(named, 3),
                      "월평균mm_재직": round(mm_active, 3), "월평균mm_계획포함": round(mm_all, 3),
                      "배분율_재직": round(mm_active / cap, 3) if cap else None,
                      "배분율_계획포함": round(mm_all / cap, 3) if cap else None}

    # ③ 프로젝트 × 과제코드
    cross = defaultdict(lambda: defaultdict(float))
    for r in rows:
        c1 = _s(r.get("과제코드1"))
        if c1:
            cross[_s(r.get("Level 2"))][c1] += _num(r.get("mm_avg"))
    cross = {p: {c: round(v, 4) for c, v in d.items()} for p, d in cross.items()}
    return {"by_code": by_code, "by_part": by_part, "cross": cross,
            "total_mm": round(tot, 4), "funcs": funcs}


def validate(rows, headcount=None):
    """정합성 검증 — 실제 파일에서 발견된 결함 유형을 규칙화"""
    headcount = headcount or {}
    issues = []

    def add(sev, kind, msg, where=""):
        issues.append({"severity": sev, "kind": kind, "msg": msg, "where": where})

    # 1) 한 사람이 여러 파트에 존재 (이중계상/동명이인)
    by_name = defaultdict(lambda: defaultdict(float))
    for r in rows:
        by_name[_s(r["이름"])][_s(r.get("Function"))] += _num(r.get("mm_12mo"))
    for nm, fs in by_name.items():
        if len([f for f in fs if f]) > 1:
            add("high", "인원 중복",
                f"'{nm}' 이(가) 파트 {len(fs)}곳에 존재 — 합 {sum(fs.values()):.1f}MM "
                f"({', '.join(f'{f} {v:.1f}' for f, v in fs.items())})", nm)

    # 2) 사람별 총 MM 이 12개월 규모를 벗어남
    for nm, fs in by_name.items():
        tot = sum(fs.values())
        kind = [_s(r.get("인원구분")) for r in rows if _s(r["이름"]) == nm]
        planned = kind and all(k != "재직" for k in kind)
        if planned:
            continue
        if tot > 15 or tot < 9:
            add("medium" if tot <= 20 else "high", "MM 총량",
                f"'{nm}' 12개월 합 {tot:.1f}MM (정상 범위 9~15) — 배분 재확인 필요", nm)

    # 3) 상세설명 미기입 (빈칸 또는 '0' 플레이스홀더)
    empty = [r for r in rows if _s(r.get("상세설명")) in ("", "0")]
    if empty:
        who = Counter(_s(r["이름"]) for r in empty).most_common(4)
        add("medium", "상세설명 미기입",
            f"{len(empty)}행 (상위: {', '.join(f'{n} {c}' for n, c in who)}) — AI 초안 대상",
            f"{len(empty)}행")

    # 4) MM 0 인데 코드가 붙은 행
    z = [r for r in rows if _num(r.get("mm_12mo")) == 0 and codes_of(r)]
    if z:
        add("low", "빈 배분", f"mm=0 인데 과제코드가 있는 행 {len(z)}개 — 삭제 또는 배분 필요", f"{len(z)}행")

    # 5) 파트 실명 인원 vs 정원
    ag = aggregates(rows, headcount)
    for f, d in ag["by_part"].items():
        if d["정원"] and d["실명인원"] > d["정원"] + 0.01:
            add("high", "정원 초과",
                f"{f}: 실명 인원 {d['실명인원']:.1f}명 > 정원 {d['정원']:.0f}명", f)

    # 6) 사용되지 않는 과제코드 (코드 체계가 실무를 못 덮음)
    # by_code 는 과제코드1 만 키로 삼는다 — 2·3순위 전용 코드가 분할mm 을 많이 받아도
    # '미사용'으로 오탐되던 결함(검증 확정). 코드1~3 × 분할mm 으로 직접 재계산한다.
    used = {c for r in rows for c in codes_of(r)}
    tot_by_code = defaultdict(float)
    for r in rows:
        for c in codes_of(r):
            tot_by_code[c] += _num(r.get("분할mm"))
    live = {c for c, v in tot_by_code.items() if v > 0.05}
    dead = sorted(used - live)
    if dead:
        add("low", "미사용 코드", f"배분이 거의 없는 코드: {', '.join(dead)} — 코드 체계 점검", "")
    return issues, ag


def diff_vs_file(rows, recomputed, cols=None):
    """파일에 적힌 파생값 vs 규칙 재계산값 비교 — 표가 최신 상태인지 확인"""
    cols = cols or ["mm_avg", "n코드", "분할mm", "인원카운트", "인원카운트(≥0.1)",
                    "파트인원헬퍼", "단계"]
    bad = defaultdict(list)
    for a, b in zip(rows, recomputed):   # noqa: B905 — strict= 는 3.10+ 전용, bat 안내(3.9+)와 맞춘다
        for c in cols:
            va, vb = a.get(c), b.get(c)
            if isinstance(vb, float):
                if abs(_num(va) - vb) > 0.0005:
                    bad[c].append((_s(a.get("이름")), va, round(vb, 4)))
            elif _s(va) != _s(vb):
                bad[c].append((_s(a.get("이름")), va, vb))
    return dict(bad)


def write_board(src_path, dst_path, rows, agg=None):
    """사본에 되쓰기 — 원본은 절대 건드리지 않는다"""
    import openpyxl
    if os.path.abspath(src_path) == os.path.abspath(dst_path):
        raise ValueError("원본과 대상이 같습니다 — 반드시 사본에 쓰세요")
    wb = openpyxl.load_workbook(src_path)
    ws = wb[MAP_SHEET]
    hdr = [_s(c.value) for c in ws[1]]
    pos = {h: i + 1 for i, h in enumerate(hdr) if h}
    for i, r in enumerate(rows, start=2):
        row_no = r.get("_sheet_row") or i          # load_board 가 기록한 실제 시트 행
        for h, col in pos.items():
            if h in r:
                ws.cell(row_no, col).value = r[h]
    wb.save(dst_path)
    return dst_path
