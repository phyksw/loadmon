# -*- coding: utf-8 -*-
r"""
agentic.py — Agentic AI 12과제 매칭 분석 (LoadMonitor24: 업무 분할 + MM 실측 내장)

Copilot 에게 [계획 과제 상세설명 + 본인 업무(과제·세부업무·유형·신호 근거·설명)]을 주고
세 가지를 판정시킨다:
  ① 매칭   — 각 Agentic AI 과제에 지금 내 현업이 얼마나 걸치는지: 적합률(0~100)·근거 업무·사유
  ② 발굴   — 12과제에 없는 신규 Agentic AI 후보: 자동화 로직·사유·근거 업무
  ③ 오할당 — 내 업무가 아닌데 내 업무로 분류된 것으로 의심되는 행: 근거

LoadMonitor20 과 다른 점:
  · 업무 행을 **7,000자 묶음으로 나눠** 보낸다(전체 한 번에 보내면 업무가 많은 사람만 실패 —
    실측). 과제 목록은 매번 전부, 묶음 경계는 앞 묶음 끝 3행(600자) 겹침으로 문맥 유지.
    겹친 행은 rows_analyzed 에 세지 않는다. 묶음 일부가 실패해도 나머지로 결과를 만든다.
  · **MM 은 프롬프트에 넣지 않는다**(사람·MM 미전송 원칙). load_mm 은 AI 가 준 값이 아니라
    프로그램이 **내 mm_rows 실측**으로 붙인다(recalc_mm): 근거 업무명 → 행 대조 → 실측 합.
    같은 업무를 여러 과제가 물면 겹친 과제 수로 안분한 load_mm_split 도 남긴다.
    근거 업무명을 내 자료에서 못 찾으면 '[근거 없음]' 표식(억지 매칭 의심).

묶음이 많은 사람(업무 수백 행)이 통째로 실패하던 것(S2)에 대한 보강:
  · 묶음은 **같은 채팅에서 이어** 보낸다(fresh=None) — Copilot 이 앞 묶음의 매칭·표기를 기억해 묶음 간 판정이 일관되게
    (제보: 묶음마다 새 채팅이라 기억이 안 이어짐). 첫 왕복·실패 뒤·config.copilotAuto.chatTurns 마다만 새 채팅.
    되풀이돼 섞여 오는 앞 답은 strip_prompt_echo·find_json 이 걷어낸다.
  · 잘린 JSON·코드펜스·굽은 따옴표·'stopped generating' 답은 core/details.find_json 이 복구한다
    (부분 결과는 salvaged_chunks 에 정직하게 센다). 프롬프트의 출력 예시는 <...> 자리표시자라
    되돌아온 프롬프트가 답으로 파싱되지 않는다(실측 사고: 예시가 매칭으로 저장됐다).
  · 로그인 만료·Edge 미기동 같은 **사람이 손대야 하는 실패는 첫 묶음에서 바로 접고**(fatal), 그 밖의
    실패는 연속 3회면 접는다 — 남은 묶음을 헛되이 기다리지 않는다. 마지막 줄 JSON 의 error/hint 에
    실제 사유(무엇이 막혔고 무엇을 하면 되는지)를 싣는다.
  · 답이 없거나 잘린 묶음은 반으로 나눠 1회 더 묻는다(적응 분할).
  · 묶음이 끝날 때마다 저장하고(중단돼도 그때까지의 결과가 남는다), 어느 행까지 판정했는지
    rows_done 을 남겨 **다음 실행은 남은 행만 이어서** 보낸다(--redo 면 처음부터).
  · 모든 묶음이 정상인데 매칭이 0건이면 실패가 아니라 '매칭 없음' 결과다(옛 판은 rc1 로 재시도했다).

  python agentic.py                          # 최신 결과 대상
  python agentic.py --from ... --to ... [--redo] [--budget 7000] [--max-chunks 30]
  python agentic.py --recalc [--from --to]   # 왕복 없이 MM 실측만 다시 계산

출력: report\agentic_<기간>.json  → UI 'Agentic AI' 탭 · 리포트 · 팀 취합(team_agentic.html)
  {tag, axes, match[{task,axis,name,fit,load_mm,work,reason, load_mm_split,evidence_rows,
   evidence_missing,shared_tasks,load_mm_ai}], new[{name,logic,reason,load_mm,work}],
   misassigned[{row,reason}], rows_analyzed, rows_total, rows_pending, rows_done[], partial,
   chunks, failed_chunks, salvaged_chunks, note, last_error, generated, mm_recalc}
"""
import glob
import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from progress import progress  # noqa: E402
import details  # noqa: E402
from details import fold, _fresh_refined  # noqa: E402,F401  (호환: 옛 이름 유지)

PROMPT_BUDGET = 7000           # 한 왕복 프롬프트 글자 상한 (입력 잘림 방지 — 실측 9,000 초과 시 실패)


def _chat_note():
    """로그용 — 묶음을 같은 채팅에서 이어 보내는 정책(config.copilotAuto.chatTurns)"""
    try:
        import judge
        n = judge.chat_turns()
    except Exception:  # noqa: BLE001 - 로그 문구가 실행을 막지 않게
        return ""
    return " — 설정 chatTurns=0: 묶음마다 새 채팅" if n <= 0 else f" · 첫 왕복·실패 뒤·{n}회마다 새 채팅"
OVERLAY_ROWS = 3               # 묶음 경계 겹침 행 수
OVERLAY_CHARS = 600            # 겹침 행 글자 상한 (예산 안에 포함해 계산한다)
MAX_WORK = 12                  # 과제별 근거 업무 상한
MAX_CHUNKS = 30                # 한 실행의 묶음 상한 — 초과분은 rows_done 을 남겨 다음 실행이 이어서
MAX_CONSEC_FAIL = 3            # 연속 실패 상한 — Copilot 이 안 되는 날 남은 묶음을 헛되이 기다리지 않게
SPLIT_MIN_ROWS = 4             # 이 이상인 묶음이 답 없이/잘려 실패하면 반으로 나눠 1회 재시도
WEAK_SOURCES = ("메일(CC)", "메일(수신전용)", "팀즈(단체)", "팀즈(수신)")


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def _cfg_int(key, default):
    """config.copilotAuto.<key> 정수 — 없거나 이상하면 default."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = (json.load(f).get("copilotAuto") or {}).get(key)
        n = int(v)
        return n if n > 0 else int(default)
    except (OSError, ValueError, TypeError, AttributeError):
        return int(default)


def load_tasks():
    """→ (tasks, axes, err). err 는 파일이 없거나 깨졌을 때의 사유(화면 hint 용)."""
    p = os.path.join(ROOT, "config", "agentic_tasks.json")
    if not os.path.exists(p):
        return [], {}, "config\\agentic_tasks.json 이 없습니다"
    try:
        with open(p, encoding="utf-8-sig") as f:
            o = json.load(f)
    except OSError as e:
        return [], {}, f"config\\agentic_tasks.json 을 읽지 못함({type(e).__name__})"
    except ValueError as e:
        return [], {}, f"config\\agentic_tasks.json 의 JSON 형식이 깨졌습니다({str(e)[:60]})"
    if not isinstance(o, dict):
        return [], {}, "config\\agentic_tasks.json 의 최상위가 객체({...})가 아닙니다"
    tasks = [t for t in (o.get("tasks") or []) if isinstance(t, dict) and t.get("id")]
    if not tasks:
        return [], (o.get("axes") or {}), "config\\agentic_tasks.json 에 tasks(id 있는 과제)가 없습니다"
    return tasks, (o.get("axes") if isinstance(o.get("axes"), dict) else {}), ""


def latest_tag():
    fs = sorted(glob.glob(os.path.join(ROOT, "report", "mm_meta_*.json")), key=os.path.getmtime)
    return os.path.basename(fs[-1])[len("mm_meta_"):-len(".json")] if fs else ""


def rfind_json(reply, want_key):
    """호환 — 정상 파싱 + 정규화 + 잘린 JSON 복구까지(core/details.find_json)."""
    return details.find_json(reply, want_key)[0]


# ── 프롬프트 ───────────────────────────────────────────────────────────────
def _one_line(s, n):
    """이름·설명 속 개행·탭을 공백으로 — 한 행이 여러 줄로 갈라지면 묶음 형식이 깨진다."""
    return " ".join(str(s or "").split())[:n]


def row_line(r, stat=None):
    """행 한 줄 — MM 은 넣지 않는다. '· 과제 / 세부업무 / 유형 / 신호 근거 — 설명[:60] (수동 m/n)'
    stat=(총 신호, 수동 신호) — 오할당 판정 근거를 행 끝에 붙인다(옛 별도 절보다 짧다)."""
    s = f"· {_one_line(r.get('Level 2'), 40)} / {_one_line(r.get('Level 3'), 60)} / {_one_line(r.get('유형'), 10)}"
    ev = _one_line(r.get("근거"), 40)
    if ev:
        s += f" / 신호 {ev}"
    d = _one_line(r.get("상세설명"), 60)
    if d:
        s += f" — {d}"
    if stat:
        total, weak = stat
        s += f" (수동 {weak}/{total})"
    return s


def row_key(r):
    return (fold(r.get("Level 2")), fold(r.get("Level 3")))


def row_sig(r):
    """행 식별자(이어서 판정용) — 과제|세부업무|유형|MM."""
    return (f"{_one_line(r.get('Level 2'), 80)}|{_one_line(r.get('Level 3'), 120)}|"
            f"{_one_line(r.get('유형'), 10)}|{details._f(r.get('mm')):.3f}")


def ag_prompt(tasks, rows, stats=None):
    """rows: 업무 행 목록(MM 미전송) · stats: {row_key: (총 신호, 수동 신호)} — 행 끝 '(수동 m/n)'.
    출력 예시는 <...> 자리표시자 — **예시 자체가 유효한 JSON 이 아니게** 한다: 회수가 어긋나 우리
    프롬프트가 되돌아와도 예시가 답으로 파싱되지 않는다(실측 사고: 'AL-1 70% 렌즈 시뮬레이션' 저장)."""
    lines = [
        "당신은 LiDAR 개발팀의 Agentic AI 과제 기획 분석가입니다.",
        "[계획 과제]는 팀이 개발하기로 한 Agentic AI 과제이고,",
        "[현재 업무]는 한 팀원의 실제 업무(PC 흔적 기반 자동 분석) 목록입니다.",
        "",
        "세 가지를 판정하세요:",
        "1. match — 과제마다: 이 사람의 아래 업무 중 그 과제가 자동화·대체할 수 있는 것이",
        "   얼마나 있는가. task(과제 코드)·fit(적합률 0~100)·",
        "   work(관련 업무 이름들 — **아래 목록의 세부업무 표기를 그대로**, 임의로 줄이거나 고치지 말 것)·",
        "   reason(근거 1~2문장). 관련이 없으면 넣지 말 것. 억지로 만들지 말 것.",
        "2. new — 계획 과제에 없지만 이 사람의 반복 업무에서 발굴되는 신규 Agentic AI 후보.",
        "   name·logic(무엇을 입력받아 무엇을 자동화하는지)·reason·",
        "   work(근거가 된 아래 업무 이름들 — 표기 그대로). 근거가 약하면 빈 배열.",
        "3. misassigned — 이 사람 본인의 업무가 아닌데 잘못 분류된 것으로 의심되는 행:",
        "   근거는 수신전용·CC 신호만으로 구성, 단순 참조·공지 성격, 다른 사람 업무의 흔적.",
        "   각 행 끝의 '(수동 m/n)' 은 그 업무 신호 n건 중 참조·수신(CC·수신전용·단체) m건 —",
        "   수동 비중이 높으면 의심. row(과제/세부업무 그대로)·reason.",
        "",
        "출력은 JSON 하나만 (설명 문장·코드펜스 금지, 짧게). <...> 자리에 실제 값을 넣으세요:",
        '{"match":[{"task":<과제 코드>,"fit":<0~100>,"work":[<세부업무 표기 그대로>],"reason":<근거 1~2문장>}],',
        ' "new":[{"name":<후보 이름>,"logic":<자동화 로직>,"reason":<사유>,"work":[<근거 업무>]}],',
        ' "misassigned":[{"row":<과제/세부업무>,"reason":<근거>}]}',
        "",
        "[계획 과제]",
    ]
    for t in tasks:
        lines.append(f"· {t.get('id')} ({t.get('axis', '')}) {_one_line(t.get('name'), 60)} — "
                     f"{_one_line(t.get('desc'), 120)}")
    lines += ["", "[현재 업무 — 과제 / 세부업무 / 유형 / 신호 근거 — 설명 (수동 m/n)]  (MM 순)"]
    stats = stats or {}
    for r in rows:
        lines.append(row_line(r, stats.get(row_key(r))))
    return "\n".join(lines)


def sig_stats(sigs):
    """signals → {(fold 과제, fold 세부업무): (신호 n건, 수동(참조·수신) m건)}"""
    by = defaultdict(Counter)
    for s in sigs or []:
        md = (s.get("model") or s.get("project") or "").strip() or "공통"
        dt = (s.get("detail") or s.get("activity") or "").strip()
        by[(md, dt)][(s.get("source") or "").strip()] += 1
    out = {}
    for (md, dt), cnt in by.items():
        total = sum(cnt.values())
        weak = sum(v for k, v in cnt.items() if k in WEAK_SOURCES)
        out[(fold(md), fold(dt))] = (total, weak)
    return out


def stats_for(rows, stats_by):
    """호환 — 옛 별도 절 대신 행별 (총, 수동) 튜플 맵을 돌려준다."""
    if not stats_by:
        return {}
    return {row_key(r): stats_by[row_key(r)] for r in rows if row_key(r) in stats_by}


def split_rows(tasks, rows, budget=PROMPT_BUDGET, ov_n=OVERLAY_ROWS, ov_chars=OVERLAY_CHARS,
               stats_by=None):
    """업무 행을 프롬프트 예산 단위로 나눈다 → [(rows_part, n_new)].

    MM 내림차순으로 정렬해 큰 업무가 앞 묶음에 오게 하고, 머리말(과제 목록)+겹침 여유(ov_chars)+행 합이
    budget 을 넘으면 자른다. 다음 묶음 앞에는 앞 묶음 끝 ov_n 행(ov_chars 이내)을 겹쳐 붙인다(오버레이) —
    겹친 행은 두 번 판정돼도 병합이 흡수하고, n_new(실판정 행 수)에는 세지 않는다.
    (옛 판은 겹침을 예산 밖에 얹어 2번째 묶음부터 7,000 을 넘겼다 — 실측 7,571자.)"""
    rows = sorted(rows, key=lambda r: -(r["_mm"] if "_mm" in r else details._f(r.get("mm"))))
    base = len(ag_prompt(tasks, [], {})) + ov_chars
    stats_by = stats_by or {}
    sizes = {}
    for r in rows:
        sizes[id(r)] = len(row_line(r, stats_by.get(row_key(r)))) + 1
    chunks, cur, size = [], [], 0
    for r in rows:
        one = sizes[id(r)]
        if cur and base + size + one > budget:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += one
    if cur:
        chunks.append(cur)
    parts = []
    for i, ch in enumerate(chunks):
        if i == 0:
            parts.append((ch, len(ch)))
            continue
        ov, ov_sz = [], 0
        for r in reversed(chunks[i - 1]):
            s1 = sizes[id(r)]
            if len(ov) >= ov_n or ov_sz + s1 > ov_chars:
                break
            ov.insert(0, r)
            ov_sz += s1
        parts.append((ov + ch, len(ch)))
    return parts


# ── 응답 병합 ──────────────────────────────────────────────────────────────
def _placeholder(s):
    """프롬프트의 <...> 자리표시자를 그대로 베낀 값 — 근거·이름으로 쓰면 안 된다."""
    s = str(s or "").strip()
    return len(s) >= 2 and s[0] == "<" and s[-1] == ">"


def _clean_list(v, cap=MAX_WORK):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for w in v:
        s = " ".join(str(w or "").split())
        if s and not _placeholder(s) and s not in out:
            out.append(s)
    return out[:cap]


def merge_match(best, o, tmap):
    """한 묶음 응답(o)을 best(과제별 누적)에 합친다 → 이 묶음의 매칭 건수.
    과제별 최고 fit·그때 reason, work 는 합집합(MAX_WORK 상한)."""
    got = 0
    for m in (o.get("match") or []):
        if not isinstance(m, dict):
            continue
        tid = str(m.get("task") or "").strip().upper()
        if tid not in tmap:
            continue
        try:
            fit = max(0, min(100, int(float(m.get("fit") or 0))))
        except (TypeError, ValueError):
            fit = 0
        if not fit:
            continue
        work = _clean_list(m.get("work"))
        reason = "" if _placeholder(m.get("reason")) else str(m.get("reason") or "")[:300]
        cur = best.get(tid)
        if cur is None:
            best[tid] = {"task": tid, "axis": tmap[tid].get("axis", ""),
                         "name": tmap[tid].get("name", tid), "fit": fit, "load_mm": 0.0,
                         "work": work, "reason": reason}
        else:
            if fit > cur["fit"]:
                cur["fit"] = fit
                cur["reason"] = reason or cur["reason"]
            for w in work:
                if w not in cur["work"] and len(cur["work"]) < MAX_WORK:
                    cur["work"].append(w)
        got += 1
    return got


def merge_new(news, o):
    n = 0
    for x in (o.get("new") or []):
        if not isinstance(x, dict) or not str(x.get("name") or "").strip() or _placeholder(x.get("name")):
            continue
        item = {"name": str(x["name"]).strip()[:60], "logic": str(x.get("logic") or "")[:300],
                "reason": str(x.get("reason") or "")[:300], "load_mm": 0.0,
                "work": _clean_list(x.get("work"))}
        dup = next((u for u in news if fold(u["name"]) == fold(item["name"])), None)
        if dup is None:
            news.append(item)
            n += 1
        else:
            for w in item["work"]:
                if w not in dup["work"] and len(dup["work"]) < MAX_WORK:
                    dup["work"].append(w)
            for k in ("logic", "reason"):
                if not dup[k] and item[k]:
                    dup[k] = item[k]
    return n


def merge_mis(mis, o):
    n = 0
    for x in (o.get("misassigned") or []):
        if not isinstance(x, dict) or not str(x.get("row") or "").strip() or _placeholder(x.get("row")):
            continue
        row = str(x["row"]).strip()[:80]
        if any(u["row"] == row for u in mis):
            continue
        mis.append({"row": row, "reason": str(x.get("reason") or "")[:250]})
        n += 1
    return n


def _has_items(o):
    """응답에 판정 내용이 하나라도 있는가 — 복구본(salvaged)이 빈 껍데기면 성공으로 세지 않는다."""
    return any(isinstance(o.get(k), list) and o.get(k) for k in ("match", "new", "misassigned"))


# ── MM 실측 재계산 (보완2 fix_agentic 이식 — 파일이 아니라 dict 대상) ─────────
_MARK_RE = re.compile(r"\s*\[(근거 없음|겹침)[^\]]*\]")


def _row_index(rows):
    """fold 축 인덱스 — Level 3 · 'Level 2 Level 3' 두 키, 공백 제거판도 함께.
    Copilot 이 '렌즈시뮬레이션'처럼 붙여 쓰면 근거를 못 찾아 과소 계상되던 것을 막는다(검증 확정).
    병합 맵을 적용하기 전 판정 이름(_raw3)도 같이 색인한다 — Copilot 은 프롬프트에 보낸 원 표기(work)로 답하는데
    판정 단계가 캐시를 더 쓰지 않으므로(상위·중위·하위 복원) 행의 Level 3 만 대표 이름으로 바뀐다(재검증 실측:
    '레이아웃 리뷰 회의' 근거가 [근거 없음]으로 떨어지고 MM 이 대표 이름 쪽에 몰림)."""
    idx, idx_ns = {}, {}
    for r in rows:
        keys = {fold(r.get("Level 3")), fold(f"{r.get('Level 2')} {r.get('Level 3')}")}
        raw3 = r.get("_raw3")
        if raw3 and raw3 != r.get("Level 3"):
            keys |= {fold(raw3), fold(f"{r.get('Level 2')} {raw3}")}
        for key in keys:
            if key:
                idx.setdefault(key, []).append(r)
                idx_ns.setdefault(key.replace(" ", ""), []).append(r)
    return idx, idx_ns


def find_rows(name, idx, idx_ns):
    f = fold(name)
    if not f:
        return []
    if f in idx:
        return idx[f]
    ns = f.replace(" ", "")
    if ns in idx_ns:
        return idx_ns[ns]
    # 부분 일치 폴백 — 양쪽 다 4자 이상일 때만('세부'·'교육' 같은 짧은 이름이 전부를 물지 않게)
    if len(ns) < 4:
        return []
    hit = [r for k, rs in idx_ns.items() if len(k) >= 4 and (ns in k or k in ns) for r in rs]
    return list({id(r): r for r in hit}.values())


def recalc_mm(out, rows, amap=None, rows_file=""):
    """Copilot 이 준 load_mm 대신 **실측 MM** 을 붙이고 매칭 근거를 대조한다(out 을 제자리 갱신).

    · 한 업무를 여러 과제가 물면 그 MM 이 과제마다 통째로 잡혀 합계가 부푼다 →
      실측 합(load_mm)과 함께, 겹치는 과제 수로 나눈 안분값(load_mm_split)을 남긴다.
    · 근거 업무명이 내 자료에 없으면 evidence_missing + reason 표식 '[근거 없음 …]'.
    · amap(세부업무 병합 맵)이 있으면 행 Level 3 에 먼저 적용해 인덱스를 만든다.
    · load_mm_ai(AI 원 추정치)는 setdefault — 두 번째 실행부터 실측값을 덮지 않는다."""
    rows = [dict(r) for r in rows]
    for r in rows:
        if "_mm" not in r:
            r["_mm"] = details._f(r.get("mm"))
        r.setdefault("_raw3", r.get("Level 3"))       # 맵 적용 전 이름 — 근거 대조는 원 표기·대표 이름 둘 다로
    if amap:
        details.apply_detail_map(rows, None, amap)
    idx, idx_ns = _row_index(rows)

    match = [m for m in (out.get("match") or []) if isinstance(m, dict)]
    claims = {}
    found = {}
    for m in match:
        if not m.get("fit"):
            continue
        hit, miss = [], []
        for w in _clean_list(m.get("work")):
            rs = find_rows(w, idx, idx_ns)
            if rs:
                hit += rs
            else:
                miss.append(w)
        hit = list({id(r): r for r in hit}.values())
        found[id(m)] = (hit, miss)
        for r in hit:
            claims.setdefault(id(r), []).append(m.get("task"))

    for m in match:
        m.setdefault("load_mm_ai", m.get("load_mm", 0))
        if not m.get("fit"):
            m.update(load_mm=0.0, load_mm_split=0.0, evidence_rows=0,
                     evidence_missing=[], shared_tasks=[])
            continue
        rs, miss = found.get(id(m), ([], []))
        real = round(sum(r["_mm"] for r in rs), 3)
        split = round(sum(r["_mm"] / max(1, len(claims.get(id(r), [1]))) for r in rs), 3)
        shared = sorted({t for r in rs for t in claims.get(id(r), []) if t != m.get("task")})
        m["load_mm"] = real
        m["load_mm_split"] = split
        m["evidence_rows"] = len(rs)
        m["evidence_missing"] = miss[:6]
        m["shared_tasks"] = shared[:8]
        # 화면(Agentic 탭)은 reason 을 그대로 보여준다 — 여기에 붙여 두면 UI 를 더 고치지
        # 않고도 '근거 없음/겹침'이 대시보드에서 바로 읽힌다
        base = _MARK_RE.sub("", str(m.get("reason") or "")).strip()
        marks = []
        if not rs:
            marks.append("[근거 없음 — 이 업무명을 내 자료에서 찾지 못함]")
        elif shared:
            marks.append(f"[겹침 {', '.join(shared[:3])} · 안분 {split:.2f} MM]")
        m["reason"] = (base + (" " + " ".join(marks) if marks else ""))[:400]

    new_sum = 0.0
    for n in (out.get("new") or []):
        if not isinstance(n, dict):
            continue
        n.setdefault("load_mm_ai", n.get("load_mm", 0))
        hit, miss = [], []
        for w in _clean_list(n.get("work")):
            rs = find_rows(w, idx, idx_ns)
            if rs:
                hit += rs
            else:
                miss.append(w)
        hit = list({id(r): r for r in hit}.values())
        n["load_mm"] = round(sum(r["_mm"] for r in hit), 3)
        n["evidence_rows"] = len(hit)
        n["evidence_missing"] = miss[:6]
        new_sum += n["load_mm"]

    hits = [m for m in match if m.get("fit")]
    no_ev = [m for m in hits if not m.get("evidence_rows")]
    dup = [m for m in hits if m.get("shared_tasks")]
    out["match"] = sorted(match, key=lambda x: (-int(x.get("fit") or 0), -float(x.get("load_mm") or 0)))
    out["mm_recalc"] = {
        "at": time.strftime("%Y-%m-%d %H:%M"), "rows_file": rows_file,
        "rows_total_mm": round(sum(r["_mm"] for r in rows), 2),
        "sum_load_mm": round(sum(m["load_mm"] for m in hits), 2),
        "sum_load_mm_split": round(sum(m["load_mm_split"] for m in hits), 2),
        "sum_new_load_mm": round(new_sum, 2),
        "matched_tasks": len(hits), "no_evidence": len(no_ev), "overlapped": len(dup),
        "aliases": len(amap or {})}
    return out


def _save_json(path, obj):
    details.save_json_atomic(path, obj)


def _load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def recalc_file(tag, rep=None, log=print):
    """agentic_<tag>.json 을 읽어 MM 실측만 다시 계산해 저장(왕복 없음).
    UI 의 오할당 제외(/api/exclude)·retag 뒤에 부른다. 반환: 저장 경로 / 실패 None."""
    rep = rep or os.path.join(ROOT, "report")
    ap = os.path.join(rep, f"agentic_{tag}.json")
    ag = _load_json(ap)
    if ag is None:
        return None
    rows, fn = details.read_rows(tag, rep)
    if not rows:
        return None
    try:
        amap = details.load_detail_aliases()
    except Exception:  # noqa: BLE001
        amap = {}
    recalc_mm(ag, rows, amap, fn)
    _save_json(ap, ag)
    mr = ag["mm_recalc"]
    try:
        log(f"[agentic] MM 실측 재계산: 매칭 {mr['matched_tasks']}과제 · 실측 합 {mr['sum_load_mm']:.2f} · "
            f"안분 합 {mr['sum_load_mm_split']:.2f} / 전체 {mr['rows_total_mm']:.2f} MM ({fn})")
    except (UnicodeEncodeError, OSError, ValueError):
        pass
    return ap


# ── 실행 ───────────────────────────────────────────────────────────────────
def _print_recalc(mr):
    print(f"[agentic] 실측 재계산 — 내 전체 업무 {mr['rows_total_mm']:.2f} MM · "
          f"과제별 실측 합 {mr['sum_load_mm']:.2f}"
          + (" (전체보다 큼 = 같은 업무를 여러 과제가 물고 있음)"
             if mr["sum_load_mm"] > mr["rows_total_mm"] else "")
          + f" · 겹침 안분 합 {mr['sum_load_mm_split']:.2f}")
    if mr.get("no_evidence"):
        print(f"[agentic] [주의] 근거 업무를 내 자료에서 찾지 못한 매칭 {mr['no_evidence']}개 — "
              "적합률이 높아도 실제 업무 근거가 없는 매칭(억지 매칭 의심)")


def _fail_summary(fails):
    """실패 목록 → (대표 사유, 조치). fatal 이 있으면 그것, 아니면 가장 잦은 사유."""
    if not fails:
        return "", ""
    fatal = next((f for f in fails if f.get("fatal")), None)
    if fatal:
        return str(fatal.get("error") or "왕복 실패"), str(fatal.get("hint") or "")
    top = Counter(str(f.get("error") or "왕복 실패") for f in fails).most_common(1)[0][0]
    hint = next((str(f.get("hint") or "") for f in fails if str(f.get("error") or "왕복 실패") == top), "")
    return top, hint


def _seed_prev(prev, tmap):
    """이어서 판정할 때 지난 결과를 누적판(best·news·mis)으로 되살린다."""
    best, news, mis = {}, [], []
    for m in (prev.get("match") or []):
        if not isinstance(m, dict) or not m.get("fit"):
            continue
        tid = str(m.get("task") or "").strip().upper()
        if tid not in tmap:
            continue
        best[tid] = {"task": tid, "axis": tmap[tid].get("axis", ""), "name": tmap[tid].get("name", tid),
                     "fit": int(m.get("fit") or 0), "load_mm": 0.0, "work": _clean_list(m.get("work")),
                     "reason": _MARK_RE.sub("", str(m.get("reason") or "")).strip()[:300],
                     "load_mm_ai": m.get("load_mm_ai", 0)}
    merge_new(news, {"new": prev.get("new") or []})
    merge_mis(mis, {"misassigned": prev.get("misassigned") or []})
    return best, news, mis


def main():
    import judge
    d0, d1 = arg("--from"), arg("--to")
    tag = (f"{d0.replace('-', '')}-{d1.replace('-', '')}" if d0 and d1 else latest_tag())
    rep = os.path.join(ROOT, "report")
    if not tag:
        print("[agentic] 분석 결과가 없습니다 — 먼저 [분석 실행]")
        print(json.dumps({"ok": False, "error": "no result",
                          "hint": "report\\ 에 분석 결과(mm_meta)가 없습니다 — 먼저 [분석 실행]"}, ensure_ascii=False))
        return 1
    if "--recalc" in sys.argv:
        ap = recalc_file(tag, rep)
        print(json.dumps({"ok": bool(ap), "tag": tag, "recalc": True,
                          **({} if ap else {"error": "no file",
                                            "hint": f"agentic_{tag}.json 또는 mm_rows_{tag}.csv 가 없습니다"})},
                         ensure_ascii=False))
        return 0 if ap else 1
    tasks, axes, terr = load_tasks()
    if not tasks:
        print(f"[agentic] {terr}")
        print(json.dumps({"ok": False, "error": "no tasks", "hint": terr}, ensure_ascii=False))
        return 1
    rows, rows_fn = details.read_rows(tag, rep)
    if not rows:
        exists = os.path.exists(os.path.join(rep, f"mm_rows_{tag}.csv")) or \
            os.path.exists(os.path.join(rep, f"mm_rows_{tag}_refined.csv"))
        hint = (f"mm_rows_{tag}(_refined).csv 에 업무 행이 없습니다(0행) — 그 기간의 신호가 없거나 전부 제외됐습니다"
                if exists else
                f"report\\mm_rows_{tag}.csv(또는 _refined) 가 없습니다 — 화면 기간({tag})과 결과 파일 기간이 다르면 "
                "그 기간을 [분석 실행]으로 다시 만드세요")
        print(f"[agentic] 업무 행이 없습니다 — {hint}")
        print(json.dumps({"ok": False, "error": "no rows", "hint": hint}, ensure_ascii=False))
        return 1
    try:
        amap = details.load_detail_aliases()
    except Exception as e:  # noqa: BLE001 - 캐시가 깨져도 매칭은 돈다
        print(f"[agentic] 세부업무 병합 맵을 읽지 못해 무시합니다({type(e).__name__})")
        amap = {}

    stats_by = sig_stats(details.read_signals(tag, rep))
    try:
        budget = max(1500, int(arg("--budget", PROMPT_BUDGET)))    # 튜닝·테스트용 묶음 예산
    except ValueError:
        budget = PROMPT_BUDGET
    try:
        max_chunks = max(1, int(arg("--max-chunks", _cfg_int("agenticMaxChunks", MAX_CHUNKS))))
    except ValueError:
        max_chunks = MAX_CHUNKS
    tmap = {str(t.get("id")): t for t in tasks if t.get("id")}
    ap = os.path.join(rep, f"agentic_{tag}.json")

    # 이어서 판정 — 지난 실행이 같은 자료(행 수·파일)에서 일부 행만 끝냈으면 남은 행만 보낸다
    sig_all = [row_sig(r) for r in rows]
    prev = None if "--redo" in sys.argv else _load_json(ap)
    done_prev = set()
    if (prev and prev.get("tag") == tag and prev.get("rows_total") == len(rows)
            and prev.get("rows_file") == rows_fn and isinstance(prev.get("rows_done"), list)):
        done_prev = set(prev["rows_done"]) & set(sig_all)
        if done_prev >= set(sig_all):
            done_prev = set()                    # 다 끝난 결과 — 처음부터 다시(재매칭)
    todo = [r for r in rows if row_sig(r) not in done_prev] if done_prev else list(rows)
    if done_prev:
        best, news, mis = _seed_prev(prev, tmap)
        print(f"[agentic] 지난 실행이 {len(rows) - len(todo)}/{len(rows)}행까지 판정했습니다 — "
              f"남은 {len(todo)}행만 이어서 보냅니다(처음부터 하려면 --redo)")
    else:
        best, news, mis = {}, [], []

    parts = split_rows(tasks, todo, budget=budget, stats_by=stats_by)
    deferred = 0
    if len(parts) > max_chunks:
        deferred = sum(n for _p, n in parts[max_chunks:])
        print(f"[agentic] 묶음이 {len(parts)}개라 이번 실행은 앞 {max_chunks}묶음만 보냅니다 — "
              f"남은 {deferred}행은 다음 실행(재매칭)이 이어서 판정합니다")
        parts = parts[:max_chunks]
    print(f"[agentic] 과제 매칭 왕복 — 업무 {len(todo)}행을 {len(parts)}묶음으로 나눠 보냅니다 "
          f"(과제 목록은 매번 전부 · 묶음 경계는 앞 행 겹침 · MM 미전송 · 같은 채팅에서 이어서{_chat_note()})")

    done_sigs = set(done_prev)
    failed, salvaged, model_name, fails = 0, 0, str((prev or {}).get("model_name") or "") if done_prev else "", []
    consec, stopped, n_sent = 0, "", 0

    def ask(part, name):
        nonlocal model_name, n_sent
        n_sent += 1
        # fresh=None — 묶음을 같은 채팅에서 이어 보낸다(첫 왕복·실패 뒤·chatTurns 마다만 새 채팅). 앞 묶음의 과제 매칭·표기를
        # Copilot 이 기억해 묶음 간 판정이 일관된다(제보: 묶음마다 새 채팅이라 기억이 안 이어짐)
        o, info = details.ask_json(judge.copilot_send, ag_prompt(tasks, part, stats_by), f"{tag}-{name}",
                                   "agentic", "match", fresh=None)
        if info.get("ok"):
            model_name = model_name or str(info.get("model") or "")
            if info.get("how") == "salvaged" and not _has_items(o):
                return {}, {"ok": False, "kind": "parse", "error": "응답이 잘려 건질 내용이 없음",
                            "hint": "답이 길어 중간에 끊겼습니다 — 묶음을 나눠 다시 묻습니다", "fatal": False}
        return o, info

    def absorb(o, part_rows, n_new, ci, note=""):
        nonlocal salvaged
        got = merge_match(best, o, tmap)
        merge_new(news, o)
        merge_mis(mis, o)
        for r in part_rows[-n_new:]:
            done_sigs.add(row_sig(r))
        print(f"[agentic] {ci}/{len(parts)}{note} — 업무 {n_new}행(겹침 {len(part_rows) - n_new}) → 매칭 {got}건")

    def write_out(final=False):
        pending = [s for s in sig_all if s not in done_sigs]
        analyzed = len(sig_all) - len(pending)
        # 분할 재시도로 결국 성공한 묶음의 실패는 사유에 남기지 않는다 — 남은 행·실패 묶음이 있을 때만
        why, how = _fail_summary(fails) if (pending or failed) else ("", "")
        out = {"tag": tag, "axes": axes, "match": list(best.values()), "new": news[:8],
               "misassigned": mis[:12],
               # 실제로 판정에 쓰인 행 수만 적는다(겹침 제외) — 반쪽 결과가 완전한 결과처럼 보이면 안 된다
               "rows_analyzed": analyzed, "rows_total": len(rows), "rows_pending": len(pending),
               "rows_done": sorted(done_sigs), "rows_file": rows_fn,
               "partial": bool(pending), "chunks": len(parts), "failed_chunks": failed,
               "salvaged_chunks": salvaged, "roundtrips": n_sent,
               "note": ("" if not pending else
                        (f"{len(pending)}행 미판정 — " + (stopped or "다시 실행(재매칭)하면 남은 행만 이어서 판정합니다"))),
               "last_error": ({"error": why, "hint": how} if why else {}),
               "generated": time.strftime("%Y-%m-%d %H:%M"), "model_name": model_name,
               "by": "LM22(업무 분할·MM 실측)"}
        recalc_mm(out, rows, amap, rows_fn)
        _save_json(ap, out)
        return out

    for ci, (part, n_new) in enumerate(parts, 1):
        progress("Agentic 분석", ci - 1, len(parts))
        o, info = ask(part, f"ag{ci}")
        if info.get("ok"):
            if info.get("how") == "salvaged":
                salvaged += 1
                print(f"[agentic] {ci}/{len(parts)} 응답이 잘려 앞부분만 복구했습니다(부분 결과)")
            absorb(o, part, n_new, ci)
            consec = 0
            write_out()
            continue
        fails.append(info)
        print(f"[agentic] {ci}/{len(parts)} 실패: {info.get('error', '')[:80]}"
              + (f" — {info.get('hint', '')[:100]}" if info.get("hint") else "")
              + f" (report\\judge_agentic_{tag}-ag{ci}.md)")
        if info.get("fatal"):
            stopped = f"{info.get('error', '')} — {info.get('hint', '')}".strip(" —")
            failed += len(parts) - ci + 1
            print(f"[agentic] 사람이 손대야 풀리는 상태라 남은 {len(parts) - ci}묶음은 보내지 않습니다")
            break
        # 적응 분할 — 답이 없거나 잘린 묶음은 반으로 나눠 한 번 더(겹침 없이, 새 행만)
        fresh_rows = part[-n_new:]
        if n_new >= SPLIT_MIN_ROWS and info.get("kind") in ("parse", "roundtrip") \
                and str(info.get("phase") or "") in ("parse", "no_reply", "copilot_error", "", "timeout"):
            half = (n_new + 1) // 2
            halves = [h for h in (fresh_rows[:half], fresh_rows[half:]) if h]
            ok_half = 0
            print(f"[agentic] {ci}/{len(parts)} 묶음을 {len(halves)}개로 나눠 다시 묻습니다(적응 분할)")
            for hi, sub in enumerate(halves, 1):
                o2, info2 = ask(sub, f"ag{ci}-{hi}")
                if info2.get("ok"):
                    ok_half += 1
                    if info2.get("how") == "salvaged":
                        salvaged += 1
                    absorb(o2, sub, len(sub), ci, note=f" (분할 {hi}/{len(halves)})")
                else:
                    fails.append(info2)
                    print(f"[agentic] {ci}/{len(parts)} 분할 {hi}/{len(halves)} 실패: {info2.get('error', '')[:80]}")
                    if info2.get("fatal"):
                        stopped = f"{info2.get('error', '')} — {info2.get('hint', '')}".strip(" —")
                        break
            if ok_half:
                consec = 0
                if ok_half < len(halves):
                    failed += 1                  # 반쪽만 됐다 — 이 묶음은 실패로 센다(남은 행은 pending)
                write_out()
                if stopped:
                    failed += len(parts) - ci
                    break
                continue
            if stopped:
                failed += len(parts) - ci + 1
                break
        failed += 1
        consec += 1
        if consec >= MAX_CONSEC_FAIL and ci < len(parts):
            stopped = (f"{consec}묶음 연속 실패({info.get('error', '')[:40]}) — "
                       "Copilot 상태를 확인한 뒤 [재매칭]으로 이어서")
            failed += len(parts) - ci
            print(f"[agentic] {consec}묶음 연속 실패 — 남은 {len(parts) - ci}묶음은 보내지 않습니다 "
                  "(잠시 뒤 재실행하면 남은 행만 이어서 판정합니다)")
            break
    progress("Agentic 분석", len(parts), len(parts))

    analyzed_now = len([s for s in sig_all if s in done_sigs])
    if not analyzed_now and not best and not news:
        # 기존 agentic_<tag>.json 은 손대지 않는다 — 반쪽 실패가 멀쩡한 옛 결과를 지우지 않게
        why, how = _fail_summary(fails)
        print(f"[agentic] 만들지 못했습니다 — {failed}/{len(parts)} 묶음이 실패했습니다: {why} — {how}")
        print(json.dumps({"ok": False, "error": why or "roundtrip",
                          "hint": (how + " · " if how else "") + f"{failed}/{len(parts)} 묶음 실패 — 기존 결과 파일은 그대로 둡니다",
                          "chunks": len(parts), "failed_chunks": failed}, ensure_ascii=False))
        return 1

    out = write_out(final=True)
    hit = out["match"]
    if not hit and not out["new"] and not out["rows_pending"]:
        print(f"[agentic] 업무 {len(rows)}행을 모두 판정했지만 12과제에 걸치는 현업이 없습니다 — 매칭 0건(실패 아님)")
    print(f"[agentic] 매칭 {len(hit)}/{len(tasks)}과제 · 신규 후보 {len(out['new'])}건 · "
          f"오할당 의심 {len(out['misassigned'])}건 → agentic_{tag}.json")
    for m in hit[:6]:
        print(f"   {m['task']} {m['name'][:24]:25s} 적합 {m['fit']:3d}% · 로드 {m['load_mm']:.2f} MM"
              + (f" (안분 {m['load_mm_split']:.2f})" if m.get("shared_tasks") else "")
              + (" [근거 없음]" if not m.get("evidence_rows") else ""))
    _print_recalc(out["mm_recalc"])
    if out["rows_pending"]:
        print(f"[agentic] [!] 업무 {out['rows_analyzed']}/{len(rows)}행만 판정했습니다 — {out['note']}")
    print(json.dumps({"ok": True, "tag": tag, "matched": len(hit), "new": len(out["new"]),
                      "misassigned": len(out["misassigned"]), "chunks": len(parts),
                      "failed_chunks": failed, "salvaged_chunks": salvaged,
                      "rows_analyzed": out["rows_analyzed"], "rows_total": len(rows),
                      "rows_pending": out["rows_pending"], "partial": out["partial"],
                      "note": out["note"], **({"hint": out["note"]} if out["rows_pending"] else {}),
                      **({"last_error": out["last_error"]} if out["last_error"] else {})},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
