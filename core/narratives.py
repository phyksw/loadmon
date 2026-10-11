# -*- coding: utf-8 -*-
r"""
narratives.py — 월별 리뷰 코멘트(report\ai_narratives_<tag>.json) 읽기·쓰기의 단일 접점 (LM28)

tag 는 분석 기간('YYYYMMDD-YYYYMMDD')이다. 기본 기간 '올해'는 오늘에서 끝나므로 tag 가 **날마다 바뀌고**,
그날 첫 실행의 코멘트 파일은 늘 새 파일이다. 같은 달의 코멘트는 기간이 달라도 그 달의 것이므로
쓰는 쪽(judge)도 읽는 쪽(화면 /api/extra · report_out)도 이 모듈로 다른 기간 파일의 달을 이월해 본다.
(제보: '월간 리뷰 코멘트가 사라짐' — 예전에는 judge 가 달마다 하는 중간 저장이 이월 없이 오늘 파일을 만들어,
narrate 가 도는 20~60분 동안 이전 달이 화면에서 가려졌고 그때 끊기면 그대로 굳었다. 화면은 파일이 비었을 때만,
그것도 가장 최근 파일 하나로만 대신했고, 리포트는 정확한 tag 파일만 읽어 '5. 월별 리뷰 코멘트' 절이 통째로 빠졌다.)

  period_months(tag)                     기간 안의 'YYYY-MM' 목록(양끝 포함) — tag 형식이 아니면 None
  load_merged(rep, tag, months=None)     자기 파일의 달 + 다른 기간 파일에서 아직 없는 달(최근 파일 먼저 · from_tag)
  save(rep, tag, fresh, months=None, earlier=())
                                         이월·기간 필터·원자 저장(details.save_json_atomic) — 저장했으면 True

항목(달 → dict) 키:
  summary · projects[{name, story, worktypes}]  모델 답(과제 이름은 judge 가 그 달의 체계 표기로 맞춘다)
  n · n_ai · made     그 달 신호 수 · AI 판정 행 수 · 작성 시각('YYYY-MM-DD HH:MM') — 다음 실행이 n_ai 로
                      '데이터가 바뀐 달'을 가린다(없으면 예전 판 항목 — 한 번 다시 만든다)
  from_tag            다른 기간 파일에서 이월한 달 — 그 파일의 tag(이미 이월된 항목이면 원래 출처를 그대로)
  earlier             이번 실행에서 새로 만들지 못해 이전 코멘트를 유지한 달(AI 판정 부족·실패·관문·덮어쓰기 방지)
"""
import json
import os
import re
import time
from datetime import datetime

PREFIX = "ai_narratives_"
_TAG_RX = re.compile(r"^(\d{8})-(\d{8})$")
_FILE_RX = re.compile(r"^ai_narratives_(\d{8}-\d{8})\.json$")     # .json.tmp·.json.corrupt 는 읽지 않는다


def path_of(rep, tag):
    """그 기간(tag)의 코멘트 파일 경로."""
    return os.path.join(rep, f"{PREFIX}{tag}.json")


def period_months(tag):
    """'YYYYMMDD-YYYYMMDD' → 그 사이의 'YYYY-MM' 목록(양끝 포함).
    형식이 아니거나 날짜가 틀리거나 거꾸로면 None — 호출자는 None 이면 달을 거르지 않는다."""
    m = _TAG_RX.match(str(tag or "").strip())
    if not m:
        return None
    try:
        d0 = datetime.strptime(m.group(1), "%Y%m%d")
        d1 = datetime.strptime(m.group(2), "%Y%m%d")
    except ValueError:
        return None
    if d0 > d1:
        return None
    out, y, mo = [], d0.year, d0.month
    while (y, mo) <= (d1.year, d1.month):
        out.append(f"{y:04d}-{mo:02d}")
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return out


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _read(p):
    """파일 → (dict 또는 None, 상태). 상태: 'ok' · 'missing'(없음) · 'bad'(잘린·깨진 JSON 이거나 dict 가 아님)
    · 'io'(있는데 읽지 못함 — 잠김 등)."""
    try:
        with open(p, encoding="utf-8-sig") as f:
            obj = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except ValueError:                 # JSONDecodeError·UnicodeDecodeError — 쓰다 끊긴 파일
        return None, "bad"
    except OSError:
        return None, "io"
    if not isinstance(obj, dict):
        return None, "bad"
    return obj, "ok"


def load_merged(rep, tag, months=None):
    """자기 파일(ai_narratives_<tag>.json)의 달은 그대로 쓰고, 빠진 달은 다른 기간 파일에서 채운다 → {달: 항목}(달 순).
    · 다른 파일은 수정 시각이 최근인 것부터 — 같은 달이 여러 파일에 있으면 최근 파일의 것.
    · 채운 항목은 사본에 from_tag 를 붙인다(이미 이월된 항목이면 원래 출처를 그대로). 원본 dict 는 바꾸지 않는다.
    · months(기간의 달 목록)를 주면 그 달만 — 다른 기간의 달(예: 작년 12월)이 섞이지 않게. 다 채우면 일찍 멈춘다.
    · 깨진 파일·dict 가 아닌 항목은 건너뛴다(읽기 전용 — 고치거나 지우지 않는다)."""
    want = set(months) if months is not None else None
    own, _st = _read(path_of(rep, tag))
    out = {k: v for k, v in (own or {}).items()
           if isinstance(v, dict) and (want is None or k in want)}
    if want is None or not want <= set(out):
        try:
            names = os.listdir(rep)
        except OSError:
            names = []
        others = []
        for fn in names:
            m = _FILE_RX.match(fn)
            if m and m.group(1) != str(tag):
                p = os.path.join(rep, fn)
                others.append((_mtime(p), m.group(1), p))
        for _mt, t, p in sorted(others, reverse=True):
            obj, _st = _read(p)
            for k, v in (obj or {}).items():
                if isinstance(v, dict) and k not in out and (want is None or k in want):
                    out[k] = dict(v, from_tag=str(v.get("from_tag") or t))
            if want is not None and want <= set(out):
                break
    return dict(sorted(out.items()))


def save(rep, tag, fresh, months=None, earlier=(), say=print, quiet=False):
    """이번에 만든 달(fresh)을 이월·기간 필터와 함께 원자 저장한다 → 저장했으면 True.
    quiet=True 면 '0개'·이월 요약 줄을 찍지 않는다(달마다 하는 중간 저장 — 같은 줄이 달마다 되풀이되지 않게).
    깨진·잠긴 파일 안내는 늘 찍는다.
    ① 자기 파일이 깨져 있으면(쓰다 끊긴 JSON) '<파일>.corrupt' 로 옮겨 보존한다 — 예전에는 깨진 파일을 빈 것으로
       보고 덮어써 같은 기간의 달이 사라졌다. 있는데 읽지 못하면(잠김) 이번 저장은 건너뛴다(기존 파일을 지킨다).
    ② 바탕 = load_merged(자기 파일 + 다른 기간 파일에서 빠진 달, 기간 필터) — 중간 저장도 늘 이월하므로
       narrate 가 도는 동안·끊긴 뒤에도 이전 달이 가려지지 않는다.
    ③ fresh 의 달(기간 안)은 from_tag·earlier 표식을 뗀 사본으로 덮는다 — 이번 실행에서 새로 만든 코멘트.
    ④ earlier 의 달 중 이번에 새로 만들지 못했고 바탕에 있는 달은 earlier=True — 화면이 '이전 실행 코멘트'라고 말한다.
       표식은 새 코멘트가 그 달을 덮을 때까지 남는다(같은 실행의 마지막 저장이 earlier 없이 불려도 지우지 않는다).
    ⑤ 하나도 없으면 아무것도 쓰지 않는다 — 빈 {} 파일이 화면을 '코멘트 없음'으로 굳히던 일 방지."""
    p = path_of(rep, tag)
    _obj, st = _read(p)
    for i in range(3):                     # 잠깐 잠긴 파일(백신·색인기) — 짧게 쉬고 다시 읽는다
        if st != "io":
            break
        time.sleep(0.3 * (i + 1))
        _obj, st = _read(p)
    if st == "bad":
        try:
            os.replace(p, p + ".corrupt")
        except OSError as e:
            say(f"        월별 코멘트 파일이 깨져 있는데 옮기지 못해 이번 저장은 건너뜁니다"
                f"({type(e).__name__}) — {os.path.basename(p)}")
            return False
        say(f"        월별 코멘트 파일이 깨져 있어 {os.path.basename(p)}.corrupt 로 보존하고 "
            "다른 기간 파일의 코멘트로 다시 씁니다")
    elif st == "io":
        say(f"        월별 코멘트 파일을 읽지 못해 이번 저장은 건너뜁니다(기존 파일 보존) — {os.path.basename(p)}")
        return False
    want = set(months) if months is not None else None
    base = load_merged(rep, tag, months)
    made = set()
    for k, v in (fresh or {}).items():
        if isinstance(v, dict) and (want is None or k in want):
            base[k] = {kk: vv for kk, vv in v.items() if kk not in ("from_tag", "earlier")}
            made.add(k)
    for k in (earlier or ()):
        if k not in made and k in base:
            base[k] = dict(base[k], earlier=True)
    if not base:
        if not quiet:
            say("        월별 내러티브 0개 — 파일을 만들지 않습니다(기존 파일도 그대로 둡니다)")
        return False
    from details import save_json_atomic
    os.makedirs(rep, exist_ok=True)
    save_json_atomic(p, dict(sorted(base.items())))
    carried = sorted(k for k, v in base.items() if v.get("from_tag"))
    if carried and not quiet:
        say(f"        월별 코멘트 {len(carried)}개월은 이전 기간에서 이월했습니다: "
            + ", ".join(carried[:6]) + (" …" if len(carried) > 6 else ""))
    return True
