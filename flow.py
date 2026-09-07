# -*- coding: utf-8 -*-
r"""
flow.py — 담당자 워크플로우 분석 (LoadMonitor22: 과제 / 담당업무 단위)

**(과제, 담당 업무)** 마다 Copilot 에게 [시간순 신호 표본 + 정제 설명]을 주고 세 가지를 판정시킨다:
  ① 역할     — 이 담당 업무에서 사용자가 어떤 롤인가 (주도/실무/검토/조율 등 + 근거)
  ② 워크플로우 — 일이 실제로 흘러간 순서: 단계별로 무슨 일을 했고 어떤 주기로 반복되는지
  ③ Agent 가능성 — 각 단계를 Agentic AI 가 대체/보조할 수 있는지 (상/중/하 + 방안)

LoadMonitor20 과 다른 점:
  · 과제(model) 단위로 묶으면 관계없는 업무가 한 흐름으로 엮였다(실측) → (과제, 담당업무) 단위.
    신호 3건 미만인 단위는 흐름이라 할 수 없어 제외한다.
  · 먼저 세부업무 표기 병합 맵(core/details — 규칙 + Copilot, config\detail_aliases.json 캐시)을
    만들어 적용한다: '레이아웃 검토/수정/리뷰 회의' 처럼 조각난 이름이 한 단위가 된다. --no-merge 면
    규칙 병합만.
  · MM 은 AI 가 만들지 않는다 — mm_rows(정제본 우선) 실측 합을 프로그램이 붙인다(프롬프트에는
    신호 건수만 보낸다).
  · 판정(model) 열이 없는 기간은 규칙 축(project/activity)으로 만들되 basis:"규칙" 을 남긴다.

  python flow.py                          # 최신 결과 대상
  python flow.py --from ... --to ... [--no-merge] [--budget 7000]

묶음이 많은 사람이 통째로 실패하던 것(S2)에 대한 보강 — agentic.py 와 같은 규칙:
  · 묶음은 같은 채팅에서 이어 보낸다(fresh=None — 첫 왕복·실패 뒤·chatTurns 마다만 새 채팅, 앞 묶음의 표기를 기억)
    · 묶음당 단위 6개 상한(답이 잘리지 않게) · 잘린 JSON 복구(core/details.find_json)
  · fatal(로그인 만료·Edge 미기동) 즉시 중단 + 사유 hint · 연속 실패 3회 중단 · 적응 분할
  · 묶음별 저장 + 이어서 판정(지난 결과의 flows 는 두고 missing 만 보낸다, --redo 면 처음부터)
  · 신호 3건 이상인 단위가 없으면 실패가 아니라 '결과 없음'(ok:true, flows:[], empty_reason) 으로 저장한다.

출력: report\workflow_<기간>.json  →  UI '담당자 워크플로우' 탭 (f.model/role/summary/steps/mm.mm/signals)
  {ok, tag, generated, model_name, unit:"과제"|"과제/담당업무", basis, flows[{model:"과제"(기본) 또는 "과제 / 담당업무",
   level1:"신제품개발|기술 내재화|양산준비|일반업무"(상위 · 정제 단계가 채운다. 없으면 빈 문자열),
   project, detail, role, summary, steps[≤8], mm:{mm}, signals}], chunks, failed_chunks, salvaged_chunks,
   missing, missing_count, partial, note, last_error, dropped, merge:{rule, ai}, rows_units, empty_reason?}
"""
import glob
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from progress import progress  # noqa: E402
import details  # noqa: E402
from details import fold, _fresh_refined  # noqa: E402,F401  (호환: 옛 이름 유지)

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

PROMPT_BUDGET = 7000            # 한 번에 보낼 프롬프트 글자 수 상한 (입력 잘림 방지)


def _chat_note():
    """로그용 — 묶음을 같은 채팅에서 이어 보내는 정책(config.copilotAuto.chatTurns)"""
    try:
        import judge
        n = judge.chat_turns()
    except Exception:  # noqa: BLE001 - 로그 문구가 실행을 막지 않게
        return ""
    return " — 설정 chatTurns=0: 묶음마다 새 채팅" if n <= 0 else f" · 첫 왕복·실패 뒤·{n}회마다 새 채팅"
MIN_SIGNALS = 3                 # 이보다 적은 신호는 흐름이라 할 수 없다
SAMPLE_N = 14                   # 단위당 시간순 표본 수
MAX_UNITS_PER_CHUNK = 6         # 묶음당 단위 상한 — 답 길이(단위당 ≈1,100자)를 잘리지 않는 범위로
MAX_CHUNKS = 40                 # 한 실행의 묶음 상한 — 초과분은 다음 실행이 missing 을 보고 이어서
MAX_CONSEC_FAIL = 3             # 연속 실패 상한 — Copilot 이 안 되는 날 남은 묶음을 헛되이 기다리지 않게
UNIT = ""                      # 실행 시 workflow_unit() 로 채운다(아래) — 설정이 바뀌면 캐시가 무효화되어야 한다
KEY_JOIN = " / "                # flow.model = "과제 / 담당업무"


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def latest_tag():
    fs = sorted(glob.glob(os.path.join(ROOT, "report", "mm_meta_*.json")), key=os.path.getmtime)
    return os.path.basename(fs[-1])[len("mm_meta_"):-len(".json")] if fs else ""


def _spread(lst, n):
    """시간순 고른 표본 — 기간의 앞·중간·끝이 남아 흐름이 보인다."""
    if len(lst) <= n:
        return lst
    if n <= 1:
        return lst[:1]
    step = (len(lst) - 1) / (n - 1)
    return [lst[round(i * step)] for i in range(n)]


ETC_DETAIL = "기타 담당업무"      # 신호가 적어 따로 세우지 못한 것들을 과제 안에서 모으는 자리


def unit_key(md, dt):
    return f"{md}{KEY_JOIN}{dt}" if dt else str(md)


def _refine_orig(tag, rep=None):
    r"""report\refine_map_<tag>.json → {"정제L2/정제L3": [(원본L2, 원본L3), …]}. 없으면 빈 dict."""
    import json
    p = os.path.join(rep or details.REPORT, f"refine_map_{tag}.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {}
    mp = o.get("map") if isinstance(o, dict) else None
    out = {}
    for k, v in (mp.items() if isinstance(mp, dict) else []):
        pairs = [(str(it[0] or "").strip(), str(it[1] or "").strip())
                 for it in (v if isinstance(v, list) else []) if isinstance(it, (list, tuple)) and len(it) >= 2]
        if pairs:
            out[str(k).strip()] = pairs
    return out


# ── 재료 (보완2.wf_materials 이식) ────────────────────────────────────────
def gather(rep, tag, amap=None):
    """(과제, 담당 업무) 단위 재료 → (mats, basis, err).
    signals 를 (model|project, detail|activity) 로 묶고 MIN_SIGNALS 미만 제외, 시간순 표본,
    mm 은 mm_rows(정제본 우선) (Level 2, Level 3) fold 합, desc 는 정제 상세설명."""
    sigs = details.read_signals(tag, rep)
    if not sigs:
        return [], "", f"signals_{tag}.csv 가 없거나 비었습니다 — 그 기간을 다시 분석하세요"
    head = sigs[0] or {}
    if "model" in head:
        basis = "판정"
    elif "project" in head or "activity" in head:
        basis = "규칙"
    else:
        return [], "", f"signals_{tag}.csv 에 판정(model)·규칙(project) 열이 모두 없습니다"
    # ★ MM 은 **판정 축**(원본 mm_rows)에서 읽는다. 예전에는 정제본을 우선해서 읽었는데, refine 이
    #   이름을 합치고 바꾸므로 신호(signals)의 (과제, 담당업무) 키와 하나도 맞지 않아 **모든 단위의 MM 이
    #   0.0** 으로 나왔다(실데이터 실측: 12/12 단위 0.0, 원본으로 바꾸면 합 0.339 로 정상 복구).
    #   MM 총량을 다시 계산하는 것이 아니라 '조회 축'만 바로잡는 것이라 로드율에는 영향이 없다.
    rows, _fn = details.read_rows(tag, rep, plain=True)
    if amap:
        details.apply_detail_map(rows, sigs, amap)
    mm_by, desc_by = {}, {}
    for r in rows:
        # 신호 쪽 기본값('공통'/'기타')과 같은 축으로 — 과제나 세부업무가 빈 행의 MM 이 단위에 붙지 않던 것
        k = (fold((r.get("Level 2") or "").strip() or "공통"), fold((r.get("Level 3") or "").strip() or "기타"))
        mm_by[k] = mm_by.get(k, 0.0) + r["_mm"]
        d = " ".join((r.get("상세설명") or "").split())
        if d:
            desc_by.setdefault(k, d[:120])
    # 정제 상세설명은 정제본에만 있다 — refine_map 으로 원본 이름에 되짚어 얹는다(설명이라 중복은 무해).
    # MM 은 여기서 손대지 않는다: 정제 행 하나가 원본 여럿에서 왔을 때 원본마다 같은 MM 을 붙이면 총량이 부푼다.
    # 상위(Level 1)는 판정 단계에서 빈칸이고 정제 단계만 채운다 — 정제본에서 원본 이름 축으로 되짚어 온다.
    l1_w = {}          # fold(과제) → {상위: mm 합}  (가장 무거운 상위를 그 과제의 상위로 본다)
    try:
        rrows, _rfn = details.read_rows(tag, rep)
        if _rfn and _rfn.endswith("_refined.csv"):
            rmap = _refine_orig(tag, rep)
            for r in rrows:
                l1 = " ".join((r.get("Level 1") or "").split())
                d = " ".join((r.get("상세설명") or "").split())
                l2 = (r.get("Level 2") or "").strip()
                l3 = (r.get("Level 3") or "").strip()
                pairs = rmap.get(f"{l2}/{l3}", []) or [(l2, l3)]
                for (o2, o3) in pairs:
                    if d:
                        desc_by.setdefault((fold(o2 or "공통"), fold(o3 or "기타")), d[:120])
                    if l1:
                        # 정제 행 하나가 원본 여럿에서 왔으면 MM 을 나눠 싣는다(총량이 부풀지 않게)
                        w = r["_mm"] / max(1, len(pairs))
                        g = l1_w.setdefault(fold(o2 or "공통"), {})
                        g[l1] = g.get(l1, 0.0) + w
    except Exception:  # noqa: BLE001 - 설명·상위가 없어도 워크플로우는 나와야 한다
        pass

    # 과제 안의 세부업무 MM 배분 — 과제 단위 카드가 LM20 처럼 '무엇에 얼마' 를 보여 주는 재료.
    parts_by, dsc_by = {}, {}
    for r in rows:
        l2 = (r.get("Level 2") or "").strip() or "공통"
        l3 = (r.get("Level 3") or "").strip() or "기타"
        f2 = fold(l2)
        parts_by.setdefault(f2, {})
        parts_by[f2][l3] = parts_by[f2].get(l3, 0.0) + r["_mm"]
        d = " ".join((r.get("상세설명") or "").split())
        if d:
            dsc_by.setdefault(f2, []).append(f"{l3}: {d[:80]}")

    unit = workflow_unit()
    groups = {}
    for s in sigs:
        # 이름 속 개행·탭은 공백으로 — '## 과제 / 담당업무' 머리말이 두 줄로 갈라지면 키를 못 맞춘다
        md = " ".join((s.get("model") or s.get("project") or "").split())
        dt = " ".join((s.get("detail") or s.get("activity") or "").split())
        if not md and not dt:
            continue
        # 기본(LM20 과 같음)은 과제 하나가 한 단위다 — 담당업무로 더 쪼개지 않는다.
        groups.setdefault((md or "공통", (dt or "기타") if unit == "과제/담당업무" else ""), []).append(s)

    # 담당업무 단위일 때만 문턱을 쓴다. 미달분은 버리지 않고 같은 과제의 '기타 담당업무' 로 모은다
    # (실측: 그냥 버리면 16조합·신호 19건=12% 가 화면에서 사라졌다).
    # 과제 단위(기본)에는 문턱을 두지 않는다 — LM20 도 두지 않았고, 과제는 원래 수가 적다.
    floor = MIN_SIGNALS if unit == "과제/담당업무" else 1
    if unit == "과제/담당업무":
        small = {}
        for (md, dt), ss in list(groups.items()):
            if len(ss) < floor:
                small.setdefault(md, []).extend(ss)
                del groups[(md, dt)]
        for md, ss in small.items():
            if len(ss) >= floor:
                groups[(md, ETC_DETAIL)] = groups.get((md, ETC_DETAIL), []) + ss
    # 표본 수도 LM20 과 같은 눈금 — 단위가 적으면 과제마다 더 많이 보여 준다
    per_cap = SAMPLE_N if unit == "과제/담당업무" else (30 if len(groups) <= 3 else 20)
    out = []
    for (md, dt), ss in groups.items():
        if len(ss) < floor:
            continue
        ss.sort(key=lambda r: str(r.get("time") or ""))
        ev = [f"- {(r.get('time') or '')[5:16]} [{r.get('source')}] "
              f"{' '.join((r.get('text') or '').split())[:80]}"
              for r in _spread(ss, per_cap)]
        f2 = fold(md)
        if dt:
            mm = round(mm_by.get((f2, fold(dt)), 0.0), 3)
            desc = desc_by.get((f2, fold(dt)), "")
            parts = []
        else:
            # 과제 단위: 그 과제의 세부업무 MM 을 모두 더하고, 배분은 parts 로 함께 넘긴다(LM20 과 같은 카드).
            pv = parts_by.get(f2) or {}
            mm = round(sum(pv.values()), 3)
            parts = [[n, round(v, 3)] for n, v in sorted(pv.items(), key=lambda kv: -kv[1])[:8] if v > 0]
            desc = " · ".join((dsc_by.get(f2) or [])[:6])
        g1 = l1_w.get(f2) or {}
        level1 = max(g1.items(), key=lambda kv: kv[1])[0] if g1 else ""
        out.append({"model": md, "detail": dt, "key": unit_key(md, dt), "signals": len(ss),
                    "level1": level1, "mm": mm, "desc": desc, "parts": parts, "evidence": ev})
    if not out:
        return [], basis, (f"흐름을 만들 단위가 없습니다 (단위 {len(groups)}개 · 신호 {len(sigs)}건)")
    # 상위(업무 성격)로 먼저 묶고 그 안에서 무거운 순 — LM20 처럼 상위 단위로도 읽히게 한다.
    L1_ORDER = {"신제품개발": 0, "기술 내재화": 1, "양산준비": 2, "일반업무": 3}
    out.sort(key=lambda x: (L1_ORDER.get(x.get("level1") or "", 9), x.get("level1") or "힣",
                            -(x["mm"] * 100 + x["signals"])))
    return out, basis, ""


def build_prompt(mats):
    # 단위가 '과제' 인지 '과제/담당업무' 인지에 따라 말을 바꾼다 — 프롬프트가 단위와 어긋나면
    # 모델이 한 흐름 안에서 여러 업무를 섞거나, 반대로 과제를 더 쪼개려 든다.
    by_task = not any(m.get("detail") for m in mats)
    unit_word = "과제" if by_task else "담당 업무"
    lines = [
        f"당신은 업무 프로세스 분석가입니다. 아래는 한 담당자의 **{unit_word}별** 활동 흔적입니다",
        f"({unit_word} 단위, 시간순 신호 표본).",
        "",
        f"{unit_word}마다 판정하세요 — 반드시 아래 근거에서 관찰되는 것만, 지어내지 말 것:",
        f"1. role  — 이 {unit_word}에서 이 사람의 역할 한 줄. 근거가 약하면 '판단 유보'.",
        f"2. steps — 그 {unit_word}가 실제로 흘러간 순서 3~6단계. 각 단계:",
        "   name(단계명) · desc(1문장) · evidence(근거 조각 하나) · cycle(주기) ·",
        "   agent(상|중|하: Agentic AI 대체 가능성 — 상=정형 반복 자동화 가능 / 중=보조 가능 /",
        "   하=판단·협상·책임) · agent_how(무슨 데이터를 입력받아 무엇을 자동으로 하는지 1문장).",
        f"   ★ **다른 {unit_word}의 일을 이 흐름에 섞지 마세요.** 한 흐름은 그 안에서만 이어집니다.",
        f"3. summary — 그 {unit_word}에서 실제로 한 일 2문장.",
        "",
        "출력은 JSON 하나만 (설명 문장 금지). <...> 자리에 실제 값을 넣으세요:",
        # 자리표시자를 <...> 로 둬 **이 예시 자체가 유효한 JSON 이 아니게** 한다 —
        # 회수가 어긋나 우리 프롬프트가 되돌아와도 이것이 답으로 파싱되지 않는다(실측 사고).
        '{"flows": [ {"key": <아래 목록의 머리말 이름을 그대로>, "role": <한 줄>,',
        '   "summary": <2문장>, "steps": [ {"order": 1, "name": <단계명>, "desc": <1문장>,',
        '     "evidence": <근거 조각>, "cycle": <주기>, "agent": <상|중|하>,',
        '     "agent_how": <방안 1문장>} ]} ]}',
        "",
    ]
    for m in mats:
        lines.append(f"## {m['key']}  (신호 {m['signals']}건)"
                     + (f"  [상위: {m['level1']}]" if m.get("level1") else ""))
        if m.get("parts"):
            # 과제 단위일 때 그 안의 세부업무 배분을 알려 준다 — 단계를 나눌 재료가 된다(LM20 과 같은 정보량)
            lines.append("[세부업무] " + " · ".join(f"{n} {v}MM" for n, v in m["parts"]))
        if m.get("desc"):
            lines.append(f"[정제 설명] {m['desc']}")
        lines += m["evidence"]
        lines.append("")
    return "\n".join(lines)


ECHO_MARK = "출력은 JSON 하나만"


def strip_echo(reply, prompt):
    r"""회수 결과에서 '되돌아온 우리 프롬프트' 를 잘라 낸다.

    Copilot 화면에서 답을 집어 올 때 앵커를 못 찾으면 우리가 보낸 말풍선까지 함께 딸려온다.
    그대로 두면 프롬프트 안의 예시·지시문이 답으로 읽힌다(실측 사고). 프롬프트의 마지막
    긴 줄을 기준으로 그 뒤만 남긴다."""
    if not reply or not prompt:
        return reply
    tail = [ln.strip() for ln in prompt.splitlines() if len(ln.strip()) >= 25]
    for ln in reversed(tail[-6:]):
        i = reply.rfind(ln)
        if i >= 0:
            return reply[i + len(ln):]
    return reply


def looks_like_echo(reply):
    """답이 아니라 우리 프롬프트가 돌아온 것으로 보이는가"""
    return ECHO_MARK in (reply or "")


def rfind_json(reply, want_key):
    """호환 — 정상 파싱 + 코드펜스·따옴표 정규화 + 잘린 JSON 복구까지(core/details.find_json)."""
    return details.find_json(reply, want_key)[0]


AGENT_OK = {"상", "중", "하"}

# 같은 뜻으로 쓰이는 구분자들 — 표기만 다른 것을 한 축으로 모은다
_SEP = {"·": "·", "・": "·", "ㆍ": "·", "‧": "·",
        "（": "(", "）": ")", "－": "-", "–": "-", "—": "-",
        "／": "/", "’": "'", "“": '"', "”": '"'}


def _fold_sep(t):
    return "".join(_SEP.get(ch, ch) for ch in t)


def _norm_model(s, drop_note=False):
    r"""이름 비교 축 — 표기 차이를 걷어 내고 남는 알맹이.

    응답이 '## 광학 설계 / 렌즈 시뮬레이션  (신호 12건)' 처럼 머리말을 옮겨 적거나 공백이 하나
    늘어난 것만으로 통째로 버려져 '파싱 실패' 가 되던 것을 막는다. 구분자(·/・/ㆍ, 전각 괄호,
    각종 대시)도 한 축으로 모은다 — NFKC 만으로는 ㆍ(U+318D)가 엉뚱한 글자로 바뀌므로
    **NFKC 앞뒤로 한 번씩** 접어야 한다(실측).

    drop_note=True 면 꼬리 괄호 주석·꼬리 대시 설명까지 떼어 낸다."""
    t = _fold_sep(str(s or "").strip())
    t = unicodedata.normalize("NFKC", t)
    t = _fold_sep(t)
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"^과제\s*[:：]\s*", "", t)
    t = re.sub(r"\s*[(]\s*신호[^)]*[)]\s*$", "", t)
    if drop_note:
        t = _strip_tails(t)
    return " ".join(t.split()).casefold()


# 꼬리 대시 '설명'만 뗀다 — 대시 양쪽에 공백이 하나도 없는 'LiDAR-2 개발' 같은 이름 속 하이픈이나,
# ' / ' 를 품은 꼬리(담당업무 부분 전체)는 이름이다. 예전 정규식 `[-–—]\s*[^-–—]{1,20}$` 은
# 'LiDAR-2 개발 / 빌드 논의' 를 'lidar' 로 만들어 엉뚱한 단위에 스냅시켰다(F2).
_DASH_TAIL = re.compile(r"(?:\s+[-–—]\s*|\s*[-–—]\s+)[^-–—/]{1,20}$")
_PAREN_TAIL = re.compile(r"\s*[(][^)]*[)]\s*$")


def _strip_tails(t, paren=True):
    """꼬리 대시 설명과(paren=True 면) 꼬리 괄호를 순서와 무관하게 뗀다 — 'X(양산) — 설명' 도 'X'."""
    for _ in range(3):
        u = _DASH_TAIL.sub("", t)
        if paren:
            u = _PAREN_TAIL.sub("", u)
        if u == t:
            break
        t = u
    return t


def _tail_note(s):
    """이름 끝 괄호 꼬리('수광부 해석(양산)' → '양산') — 표기 차이·대시 설명을 걷어낸 뒤. 없으면 ''."""
    t = _fold_sep(unicodedata.normalize("NFKC", _fold_sep(str(s or "").strip())))
    t = re.sub(r"\s*[(]\s*신호[^)]*[)]\s*$", "", t)
    t = _strip_tails(t, paren=False)
    m = re.search(r"[(]([^()]*)[)]\s*$", t)
    return " ".join(m.group(1).split()).casefold() if m else ""


def _uniq_map(keys, fn):
    """{fn(k): k} — 같은 비교 축 값에 재료 키가 2개 이상 걸리면(모호) 그 값은 뺀다.
    '수광부 해석(양산)'/'(선행)' 의 괄호를 뗀 축에서 dict 마지막 항목이 조용히 이겨 응답이
    엉뚱한 단위에 스냅되던 결함(F2) — 모호하면 다음 축으로 넘기고, 끝까지 없으면 버린다."""
    out, dup = {}, set()
    for k in keys:
        v = fn(k)
        if not v:
            continue
        if v in out and out[v] != k:
            dup.add(v)
        else:
            out[v] = k
    for v in dup:
        out.pop(v, None)
    return out


def _resolve_key(raw, keys, low_map, fold_map, norm_map, note_map, ns_map=None, fns_map=None):
    """응답의 key 를 재료 키로 스냅 — 정확 → 소문자 → fold → _norm_model → 공백 제거 →
    괄호·꼬리 제거 → 앞부분 유일 일치 → 담당업무 이름 유일 일치 순. 못 찾으면 ''.
    각 축은 후보가 유일할 때만 인정한다(_uniq_map 으로 만든 맵)."""
    if raw in keys:
        return raw
    hit = low_map.get(raw.lower()) or fold_map.get(fold(raw)) or norm_map.get(_norm_model(raw))
    if hit:
        return hit
    nr = _norm_model(raw)
    # 대시 설명만 뗀 축('X(양산) — 해석 반복' → 'x(양산)', 괄호 꼬리는 남긴다)과 공백 제거 비교
    # ('광학설계/수광부해석(양산)' 처럼 붙여 쓴 응답)
    nd = " ".join(_strip_tails(nr, paren=False).split())
    hit = (norm_map.get(nd) or (ns_map or {}).get(nd.replace(" ", ""))
           or (fns_map or {}).get(fold(raw).replace(" ", "")))
    if hit:
        return hit
    # 꼬리(괄호·대시 설명)를 뗀 축 — 응답이 꼬리를 빠뜨렸을 때. 응답 자신의 괄호 꼬리가 후보의
    # 것과 다르면('(선행)' vs '(양산)') 다른 단위이므로 스냅하지 않는다.
    hit = note_map.get(_norm_model(raw, True))
    if hit and _tail_note(raw) in ("", _tail_note(hit)):
        return hit
    nk = nr.rstrip(". …")
    if len(nk) >= 8:
        # 앞부분 일치는 이름 경계에서만 — 'lidar-2 개발' 이 'lidar-2 개발자 …' 에 걸리지 않게
        cands = [v for k, v in norm_map.items()
                 if k.startswith(nk) and (len(k) == len(nk) or not k[len(nk)].isalnum())]
        if len(cands) == 1:
            return cands[0]
    # '/' 없이 담당업무 이름만 온 경우 — 세부업무 fold 가 딱 하나에만 걸리면 인정
    fr = fold(raw)
    if fr:
        frn = fr.replace(" ", "")
        cands = [k for k, m in keys.items()
                 if fold(m["detail"]) == fr or fold(m["detail"]).replace(" ", "") == frn]
        if len(cands) == 1:
            return cands[0]
    return ""


def sanitize_flows(raw_flows, keys, mats_by=None, dropped=None):
    """응답 형태 방어 — 스칼라·null·모르는 키·이상 agent 값을 정규화한다.
    keys: {"과제 / 담당업무": mat}. 정말 모르는 키의 flow 만 버린다(지어낸 단위 방지);
    버린 이름은 dropped 에 담아 사유로 쓸 수 있게 한다."""
    flows = raw_flows if isinstance(raw_flows, list) else []
    keys = keys or {}
    if mats_by is None:
        mats_by = keys
    # 모든 비교 축은 후보가 유일할 때만 쓴다(F2 — 모호한 축 값은 빠진다)
    low_map = _uniq_map(keys, str.lower)
    fold_map = _uniq_map(keys, fold)
    norm_map = _uniq_map(keys, _norm_model)
    note_map = _uniq_map(keys, lambda k: _norm_model(k, True))
    ns_map = _uniq_map(keys, lambda k: _norm_model(k).replace(" ", ""))
    fns_map = _uniq_map(keys, lambda k: fold(k).replace(" ", ""))
    out, seen = [], set()
    for f in flows:
        if not isinstance(f, dict):
            continue
        raw_name = str(f.get("key") or f.get("model") or "").strip()
        key = (_resolve_key(raw_name, keys, low_map, fold_map, norm_map, note_map, ns_map, fns_map)
               if raw_name else "")
        if not key:
            if dropped is not None and raw_name:
                dropped.append(raw_name)
            continue
        if key in seen:
            continue
        steps_raw = f.get("steps")
        steps_raw = steps_raw if isinstance(steps_raw, list) else []
        steps = []
        for s in steps_raw[:8]:
            if not isinstance(s, dict):
                continue
            ag = str(s.get("agent") or "").strip()
            i = len(steps) + 1                 # 건너뛴 항목이 있어도 번호가 비지 않게
            steps.append({"order": i,
                          "name": str(s.get("name") or "")[:40] or f"단계 {i}",
                          "desc": str(s.get("desc") or "")[:200],
                          "evidence": str(s.get("evidence") or "")[:120],
                          "cycle": str(s.get("cycle") or "")[:20],
                          "agent": ag if ag in AGENT_OK else "중",
                          "agent_how": str(s.get("agent_how") or "")[:200]})
        if not steps:
            if dropped is not None:
                dropped.append(f"{raw_name}(단계 없음)")
            continue
        seen.add(key)
        hit = mats_by.get(key) or {}
        out.append({"model": key, "level1": hit.get("level1", ""),
                    "project": hit.get("model", ""), "detail": hit.get("detail", ""),
                    "role": str(f.get("role") or "")[:160],
                    "summary": str(f.get("summary") or "")[:400],
                    "steps": steps,
                    # MM 은 실측(mm_rows) — AI 숫자가 아니라 프로그램이 붙인다
                    "mm": {"mm": hit.get("mm", 0.0)},
                    "signals": hit.get("signals", 0)})
    return out


def _chunks(mats, budget=PROMPT_BUDGET, max_units=None):
    r"""단위를 프롬프트 크기 기준으로 나눈다 — 한 묶음이 너무 커지지 않게.
    단위 하나가 예산을 넘으면 그 하나만으로 한 묶음(더 쪼갤 수 없다).
    max_units: 묶음당 단위 수 상한 — 신호가 적어 짧은 단위가 15개씩 들어가면 **답**이 1.5만 자를 넘어
    Copilot 이 중간에 끊는다(실측 v22 픽스처: 1묶음 15단위 → 예상 답 16,500자). 입력 예산과 별개로 묶는다."""
    out, cur, size = [], [], 0
    base = len(build_prompt([]))
    cap = max_units or MAX_UNITS_PER_CHUNK
    for m in mats:
        one = len(build_prompt([m])) - base
        if cur and (base + size + one > budget or len(cur) >= cap):
            out.append(cur)
            cur, size = [], 0
        cur.append(m)
        size += one
    if cur:
        out.append(cur)
    return out or [mats]


def _save_json(path, obj):
    details.save_json_atomic(path, obj)


def _load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def workflow_unit():
    """워크플로우 한 단위를 무엇으로 볼 것인가 — config.workflowUnit.

    "과제"(기본, LM20 과 같음)   : 과제 하나가 한 흐름. 그 안의 세부업무는 MM 배분으로 보여 준다.
    "과제/담당업무"              : 담당 업무마다 따로 흐름을 만든다(LM22 방식 — 잘게 쪼개진다).

    LM22 에서 기본을 '과제/담당업무' 로 바꿨더니 실데이터에서 단위가 2.4배(5→12)가 되어
    "너무 파편적" 이라는 제보가 왔다. 기본을 LM20 과 같게 되돌린다."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = str(json.load(f).get("workflowUnit") or "").strip()
    except (OSError, ValueError, TypeError, AttributeError):
        v = ""
    return "과제/담당업무" if v.replace(" ", "") in ("과제/담당업무", "detail", "과제담당업무") else "과제"


def _sync_unit():
    """모듈 상수 UNIT 을 지금 설정값으로 맞춘다. 출력 JSON 의 unit 과 캐시 유효성 판정(prev.unit == UNIT)이
    이 값을 보므로, 설정을 바꾸면 지난 흐름 캐시가 저절로 버려진다 — 단위가 달라졌는데 옛 결과를
    되쓰면 화면과 설정이 어긋난다."""
    global UNIT
    UNIT = workflow_unit()
    return UNIT


def _cfg_int(key, default):
    """config.copilotAuto.<key> 정수 — 없거나 이상하면 default."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = (json.load(f).get("copilotAuto") or {}).get(key)
        n = int(v)
        return n if n > 0 else int(default)
    except (OSError, ValueError, TypeError, AttributeError):
        return int(default)


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


def main():
    import judge
    _sync_unit()               # 출력 JSON 의 unit·캐시 유효성 판정을 지금 설정에 맞춘다
    d0, d1 = arg("--from"), arg("--to")
    tag = (f"{d0.replace('-', '')}-{d1.replace('-', '')}" if d0 and d1 else latest_tag())
    rep = os.path.join(ROOT, "report")
    if not tag:
        print("[flow] 분석 결과가 없습니다 — 먼저 [분석 실행]")
        print(json.dumps({"ok": False, "error": "no result",
                          "hint": "report\\ 에 분석 결과(mm_meta)가 없습니다 — 먼저 [분석 실행]"}, ensure_ascii=False))
        return 1
    dst = os.path.join(rep, f"workflow_{tag}.json")

    # ① 세부업무 표기 병합 맵 — 규칙 + (--no-merge 아니면) Copilot. 실패해도 워크플로우는 돈다.
    sender = None if "--no-merge" in sys.argv else judge.copilot_send
    amap, n_rule, n_ai = {}, 0, 0
    try:
        amap, n_rule, n_ai = details.detail_merge_map(tag, sender, log=lambda m: print(f"[flow]{m}"))
        if n_rule or n_ai:
            print(f"[flow] 세부업무 유사 병합: 규칙 {n_rule}건 · Copilot {n_ai}건 → "
                  "config\\detail_aliases.json (한 줄 지우면 그 병합만 원복)")
        elif amap:
            print(f"[flow] 세부업무 병합 맵 {len(amap)}건 적용(캐시)")
    except Exception as e:  # noqa: BLE001 - 병합 실패가 워크플로우를 막지 않게
        print(f"[flow] (세부업무 병합 건너뜀: {type(e).__name__}: {str(e)[:80]})")
    merge_fail = dict(getattr(details, "LAST_FAIL", {}) or {})

    # ② 재료
    mats, basis, err = gather(rep, tag, amap)
    if not mats:
        if not basis:
            # 신호 파일 자체가 없다/열이 없다 — 이것은 결과 없음이 아니라 전제가 깨진 것
            print(f"[flow] {err}")
            print(json.dumps({"ok": False, "error": err,
                              "hint": f"report\\signals_{tag}.csv 를 만드는 [분석 실행]을 그 기간으로 다시 돌리세요"},
                             ensure_ascii=False))
            return 1
        # 신호는 있는데 흐름이라 할 단위가 없다 — 실패가 아니라 '결과 없음'. 옛 판은 rc1 로 재시도까지 했다.
        out = {"ok": True, "tag": tag, "generated": time.strftime("%Y-%m-%d %H:%M"), "model_name": "",
               "unit": UNIT, "basis": basis, "flows": [], "chunks": 0, "failed_chunks": 0, "missing": [],
               "dropped": [], "merge": {"rule": n_rule, "ai": n_ai, "aliases": len(amap or {})},
               "rows_units": 0, "empty_reason": err}
        _save_json(dst, out)
        print(f"[flow] 워크플로우를 만들 단위가 없습니다 — {err} (실패 아님: 더 긴 기간을 분석하거나 신호가 쌓인 뒤 다시)")
        print(json.dumps({"ok": True, "flows": 0, "units": 0, "chunks": 0, "failed_chunks": 0,
                          "basis": basis, "empty_reason": err, "note": err}, ensure_ascii=False))
        return 0
    if basis == "규칙":
        print("[flow] 판정(model) 열이 없어 규칙 분류(project/activity) 축으로 만듭니다 — "
              "과제명이 AI 가 정리한 상위개체가 아니라 품질이 낮습니다(basis: 규칙)")
    keys = {m["key"]: m for m in mats}

    # 세부 병합 왕복이 '사람이 손대야 하는' 이유로 죽었으면 흐름 왕복도 같은 이유로 죽는다 — 헛되이 보내지 않는다
    if merge_fail.get("fatal") and sender is not None:
        why, how = str(merge_fail.get("error") or "왕복 실패"), str(merge_fail.get("hint") or "")
        print(f"[flow] Copilot 왕복이 막혀 있습니다({why}) — {how}")
        print(json.dumps({"ok": False, "error": why, "hint": how or "조치 후 다시 실행"}, ensure_ascii=False))
        return 1

    # 이어서 판정 — 같은 기간·같은 단위 축의 지난 결과가 있으면 그 단위는 두고 빠진 단위만 보낸다
    prev = None if "--redo" in sys.argv else _load_json(dst)
    kept = []
    if prev and prev.get("tag") == tag and prev.get("unit") == UNIT and isinstance(prev.get("flows"), list):
        for f in prev["flows"]:
            if not isinstance(f, dict) or f.get("model") not in keys or not f.get("steps"):
                continue
            hit = keys[f["model"]]
            f = dict(f, project=hit["model"], detail=hit["detail"], mm={"mm": hit["mm"]}, signals=hit["signals"])
            kept.append(f)
        if len(kept) >= len(keys):
            kept = []                            # 다 끝난 결과 — 처음부터 다시(재분석)
    done_keys = {f["model"] for f in kept}
    todo = [m for m in mats if m["key"] not in done_keys]
    if kept:
        print(f"[flow] 지난 실행이 {len(kept)}/{len(keys)}개 업무를 끝냈습니다 — 남은 {len(todo)}개만 이어서 보냅니다"
              "(처음부터 하려면 --redo)")

    # ③ 묶음 왕복 — 부분 실패는 계속
    try:
        budget = max(1500, int(arg("--budget", PROMPT_BUDGET)))    # 튜닝·테스트용 묶음 예산
    except ValueError:
        budget = PROMPT_BUDGET
    try:
        max_chunks = max(1, int(arg("--max-chunks", _cfg_int("flowMaxChunks", MAX_CHUNKS))))
    except ValueError:
        max_chunks = MAX_CHUNKS
    chunks = _chunks(todo, budget, _cfg_int("flowUnitsPerChunk", MAX_UNITS_PER_CHUNK))
    if len(chunks) > max_chunks:
        print(f"[flow] 묶음이 {len(chunks)}개라 이번 실행은 앞 {max_chunks}묶음만 보냅니다 — "
              f"남은 {sum(len(c) for c in chunks[max_chunks:])}개 업무는 다음 실행(재분석)이 이어서 판정합니다")
        chunks = chunks[:max_chunks]
    print(f"[flow] 담당 업무 {len(todo)}개 워크플로우 왕복 ({len(chunks)}회로 나눠 보냄 — "
          f"한 흐름이 다른 업무로 넘어가지 않게 업무 단위로 물어봅니다 · 같은 채팅에서 이어서{_chat_note()})")
    dropped, flows, fails = [], list(kept), []
    model_name = str((prev or {}).get("model_name") or "") if kept else ""
    failed, salvaged, consec, stopped, n_sent = 0, 0, 0, "", 0

    def ask(part, name):
        nonlocal model_name, n_sent
        n_sent += 1
        # fresh=None — 묶음을 같은 채팅에서 이어 보낸다(첫 왕복·실패 뒤·chatTurns 마다만 새 채팅)
        o, info = details.ask_json(judge.copilot_send, build_prompt(part), f"{tag}-{name}", "flow",
                                   "flows", fresh=None)
        if not info.get("ok"):
            return [], info
        model_name = model_name or str(info.get("model") or "")
        got = sanitize_flows(o.get("flows"), {m["key"]: m for m in part}, keys, dropped)
        if not got:
            why = ("응답이 잘려 건질 흐름이 없음" if info.get("how") == "salvaged" else
                   ("응답의 업무명이 분석된 단위와 달라 전부 버림: " + ", ".join(dropped[-3:]) if dropped
                    else "응답에 flows 가 없거나 형식이 다름"))
            return [], {"ok": False, "kind": "parse", "error": why[:120], "fatal": False, "phase": "parse",
                        "hint": "묶음을 나눠 다시 묻습니다 — 반복되면 report\\judge_flow_*.md 의 답을 확인"}
        return got, info

    def write_out():
        done = {f["model"] for f in flows}
        missing = [k for k in keys if k not in done]
        why, how = _fail_summary(fails) if (missing or failed) else ("", "")
        out = {"ok": True, "tag": tag, "generated": time.strftime("%Y-%m-%d %H:%M"),
               "model_name": model_name, "unit": UNIT, "basis": basis, "flows": flows,
               "chunks": len(chunks), "failed_chunks": failed, "salvaged_chunks": salvaged, "roundtrips": n_sent,
               # 왜 어떤 단위가 비었는지 나중에도 알 수 있게 남긴다
               "missing": missing[:200], "missing_count": len(missing), "dropped": dropped[:20],
               "partial": bool(missing),
               "note": ("" if not missing else
                        f"{len(missing)}개 업무 미판정 — " + (stopped or "다시 실행(재분석)하면 남은 업무만 이어서 판정합니다")),
               "last_error": ({"error": why, "hint": how} if why else {}),
               "merge": {"rule": n_rule, "ai": n_ai, "aliases": len(amap or {})},
               "rows_units": len(mats)}
        _save_json(dst, out)
        return out

    for ci, part in enumerate(chunks, 1):
        progress("워크플로우 분석", ci - 1, len(chunks))
        got, info = ask(part, f"wf{ci}")
        if info.get("ok"):
            flows.extend(got)
            consec = 0
            print(f"[flow] {ci}/{len(chunks)} — 업무 {len(part)}개 중 {len(got)}개 판정")
            if info.get("how") == "salvaged":
                salvaged += 1
                # 답이 길어 잘렸다 — 빠진 단위만 작은 묶음으로 한 번 더 묻는다(답이 짧아져 잘리지 않는다)
                left = [m for m in part if m["key"] not in {f["model"] for f in got}]
                print(f"[flow] {ci}/{len(chunks)} 응답이 잘려 앞부분만 복구했습니다 — 빠진 {len(left)}개를 다시 묻습니다")
                if left:
                    got2, info2 = ask(left, f"wf{ci}-r")
                    if info2.get("ok"):
                        flows.extend(got2)
                        print(f"[flow] {ci}/{len(chunks)} (재질문) — 업무 {len(left)}개 중 {len(got2)}개 판정")
                    else:
                        fails.append(info2)
                        if info2.get("fatal"):
                            stopped = f"{info2.get('error', '')} — {info2.get('hint', '')}".strip(" —")
                            failed += len(chunks) - ci
                            write_out()
                            break
            write_out()
            continue
        fails.append(info)
        print(f"[flow] {ci}/{len(chunks)} 실패: {info.get('error', '')[:80]}"
              + (f" — {info.get('hint', '')[:100]}" if info.get("hint") else "")
              + f" (report\\judge_flow_{tag}-wf{ci}.md)")
        if info.get("fatal"):
            stopped = f"{info.get('error', '')} — {info.get('hint', '')}".strip(" —")
            failed += len(chunks) - ci + 1
            print(f"[flow] 사람이 손대야 풀리는 상태라 남은 {len(chunks) - ci}묶음은 보내지 않습니다")
            break
        # 적응 분할 — 답이 없거나 잘린 묶음은 반으로 나눠 한 번 더
        if len(part) >= 2 and str(info.get("phase") or "") in ("parse", "no_reply", "copilot_error", "", "timeout"):
            half = (len(part) + 1) // 2
            halves = [h for h in (part[:half], part[half:]) if h]
            ok_half = 0
            print(f"[flow] {ci}/{len(chunks)} 묶음을 {len(halves)}개로 나눠 다시 묻습니다(적응 분할)")
            for hi, sub in enumerate(halves, 1):
                got2, info2 = ask(sub, f"wf{ci}-{hi}")
                if info2.get("ok"):
                    ok_half += 1
                    if info2.get("how") == "salvaged":
                        salvaged += 1
                    flows.extend(got2)
                    print(f"[flow] {ci}/{len(chunks)} (분할 {hi}/{len(halves)}) — 업무 {len(sub)}개 중 {len(got2)}개 판정")
                else:
                    fails.append(info2)
                    print(f"[flow] {ci}/{len(chunks)} 분할 {hi}/{len(halves)} 실패: {info2.get('error', '')[:80]}")
                    if info2.get("fatal"):
                        stopped = f"{info2.get('error', '')} — {info2.get('hint', '')}".strip(" —")
                        break
            if ok_half:
                consec = 0
                if ok_half < len(halves):
                    failed += 1
                write_out()
                if stopped:
                    failed += len(chunks) - ci
                    break
                continue
            if stopped:
                failed += len(chunks) - ci + 1
                break
        failed += 1
        consec += 1
        if consec >= MAX_CONSEC_FAIL and ci < len(chunks):
            stopped = (f"{consec}묶음 연속 실패({info.get('error', '')[:40]}) — "
                       "Copilot 상태를 확인한 뒤 [재분석]으로 이어서")
            failed += len(chunks) - ci
            print(f"[flow] {consec}묶음 연속 실패 — 남은 {len(chunks) - ci}묶음은 보내지 않습니다 "
                  "(잠시 뒤 재실행하면 남은 업무만 이어서 판정합니다)")
            break
    progress("워크플로우 분석", len(chunks), len(chunks))

    # ④ 결과 — 없으면 기존 workflow_<tag>.json 보존
    if not flows:
        why, how = _fail_summary(fails)
        if not why:
            why = "파싱 실패"
            how = ("응답의 업무명이 분석된 단위와 달라 전부 버렸습니다: " + ", ".join(dropped[:8])
                   if dropped else "응답에 flows 가 없거나 형식이 달랐습니다")
        print(f"[flow] 만들지 못했습니다 — {why} — {how}")
        print(json.dumps({"ok": False, "error": why,
                          "hint": (how + " · " if how else "") + f"{failed}/{len(chunks)}개 묶음 실패 — 기존 결과는 그대로",
                          "chunks": len(chunks), "failed_chunks": failed}, ensure_ascii=False))
        return 1
    if dropped:
        print(f"[flow] 목록에 없는 업무명 {len(dropped)}개는 건너뜀: {', '.join(dropped[:3])}")

    out = write_out()
    for fl in flows:
        print(f"   {fl['model']}: 역할={fl['role'][:40]} · 단계 {len(fl['steps'])}개 · "
              f"Agent 상 {sum(1 for s in fl['steps'] if s['agent'] == '상')}건 · {fl['mm']['mm']} MM")
    if out["missing_count"]:
        print(f"[flow] [!] 업무 {len(flows)}/{len(mats)}개만 판정했습니다 — {out['note']}")
    print(f"[flow] → {dst}")
    print(json.dumps({"ok": True, "flows": len(flows), "units": len(mats), "chunks": len(chunks),
                      "failed_chunks": failed, "salvaged_chunks": salvaged, "basis": basis,
                      "missing": out["missing_count"], "partial": out["partial"], "note": out["note"],
                      **({"hint": out["note"]} if out["missing_count"] else {}),
                      **({"last_error": out["last_error"]} if out["last_error"] else {}),
                      "merge": {"rule": n_rule, "ai": n_ai}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
