# -*- coding: utf-8 -*-
r"""
details.py — 세부업무(Level 3) 표기 병합 맵 (LoadMonitor22, 보완2 이식)

AI 가 청크마다 '렌즈 시뮬레이션'/'렌즈시뮬레이션', '레이아웃 검토'/'레이아웃 수정'/'레이아웃
리뷰 회의' 처럼 같은 일에 다른 이름을 붙이면 (과제 × 세부업무) 격자가 조각나 워크플로우가
쪼개지고 Agentic 근거 대조가 어긋난다. 여기서 (과제, 세부업무) → 대표 이름 맵을 만들어
agentic·flow·freeze(분석리포트)·judge 가 같은 축을 쓰게 한다.

  ① 규칙 — ukey3 동일(띄어쓰기·구분자 변형)만. 대표 = MM 큰 이름, 같으면 공백 정규화가
     짧은 이름('빌드  논의' 오타가 대표가 되지 않게).
  ② Copilot — 같은 과제 안에서 '같은 묶음의 일' 만. 보내는 것은 과제명·업무명뿐
     (사람 이름·MM 미전송). 결과는 _accept_group3(실재 이름·2개 이상·괄호 꼬리 동일)로만 채택.

캐시: config\detail_aliases.json — 데이터 리셋이 report\ 를 비워도 살아남는다
(config\excluded_work.json 과 같은 자리). 첫 로드 때 옛 report\보완툴\detail_aliases.json 이
있으면 한 번 흡수한다. 한 줄 지우면 그 병합만 원복.

※ 배포본 judge.merge_details 는 괄호를 토큰으로 갈라 '(양산)/(선행)' 을 오병합한다(실측) —
  여기 축(_fold3/ukey3/_note3)은 괄호 꼬리를 보존한다.
"""
import csv
import json
import os
import re
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "report")
CONFIG = os.path.join(ROOT, "config")
ALIAS_FILE = os.path.join(CONFIG, "detail_aliases.json")
LEGACY_ALIAS_FILE = os.path.join(REPORT, "보완툴", "detail_aliases.json")
KEY_SEP = "␟"                 # '␟' — JSON 키 "과제␟세부업무"

SECTION_BUDGET = 6000              # 과제 하나의 목록이 이보다 크면 겹침 2줄로 나눈다
BATCH_BUDGET = 7000                # Copilot 한 왕복 프롬프트 상한(입력 잘림 방지)
MAX_ROUNDTRIPS = 12                # 세부 병합에 쓰는 왕복 상한 — flow 앞에서 끝없이 기다리지 않게


def _say(msg, log=print):
    try:
        log(msg)
    except (UnicodeEncodeError, OSError, ValueError):
        pass


# ── 이름 비교 축 ──────────────────────────────────────────────────────────
_SEP3 = {"·": " ", "・": " ", "ㆍ": " ", "‧": " ", "（": "(", "）": ")",
         "－": "-", "–": "-", "—": "-", "／": "/", "_": " ", "-": " ", "/": " "}


def _fold3(s, drop_note=True):
    """구분자·공백·대소문자를 걷어낸 비교 축. drop_note=True 면 꼬리 괄호도 뗀다."""
    t = "".join(_SEP3.get(ch, ch) for ch in str(s or ""))
    t = unicodedata.normalize("NFKC", t)
    t = "".join(_SEP3.get(ch, ch) for ch in t)
    if drop_note:
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    return " ".join(t.split()).casefold()


def ukey3(s):
    """규칙 병합 키 — 괄호 꼬리는 남기고 공백만 전부 지운다('빌드  논의' == '빌드 논의')."""
    return _fold3(s, drop_note=False).replace(" ", "")


def _note3(s):
    """꼬리 괄호 안 표기 — '(양산)' vs '(선행)' 은 실제 구분이다."""
    m = re.search(r"\(([^)]*)\)\s*$", str(s or ""))
    return (m.group(1).strip().casefold() if m else "")


def fold(s):
    """agentic·flow 가 함께 쓰는 느슨한 축 — 괄호까지 공백으로 바꿔 토큰만 남긴다."""
    t = unicodedata.normalize("NFKC", str(s or ""))
    t = re.sub(r"[·・ㆍ‧/_\-()\[\]（）]", " ", t)
    return " ".join(t.split()).casefold()


# ── 자료 읽기 (agentic·flow·freeze 공용) ──────────────────────────────────
def _fresh_refined(plain, refined):
    """정제본을 써도 되는가 — 원본보다 오래된 정제본은 쓰지 않는다(배포본 규칙)."""
    if not os.path.exists(refined):
        return False
    try:
        return (not os.path.exists(plain)
                or os.path.getmtime(refined) >= os.path.getmtime(plain))
    except OSError:
        return True


def rows_path(tag, rep=None):
    rep = rep or REPORT
    plain = os.path.join(rep, f"mm_rows_{tag}.csv")
    ref = os.path.join(rep, f"mm_rows_{tag}_refined.csv")
    if _fresh_refined(plain, ref):
        return ref
    return plain if os.path.exists(plain) else (ref if os.path.exists(ref) else plain)


def read_rows(tag, rep=None):
    """mm_rows(정제본 우선) → (행 목록, 파일명). 각 행에 _mm(float) 을 붙인다."""
    p = rows_path(tag, rep)
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
    except (OSError, ValueError):
        return [], ""
    for r in rows:
        r["_mm"] = _f(r.get("mm"))
    return rows, os.path.basename(p)


def read_signals(tag, rep=None):
    p = os.path.join(rep or REPORT, f"signals_{tag}.csv")
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            return list(csv.DictReader(f))
    except (OSError, ValueError):
        return []


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


# ── 캐시 ──────────────────────────────────────────────────────────────────
def _cycle_rep(members):
    """순환 구성원 중 결정적 대표 — 공백 정규화가 짧은 이름 → 짧은 이름 → 사전순(MM 무관)."""
    return min(members, key=lambda x: (len(" ".join(x.split())), len(x), x))


def _flatten3_map(amap, log=None):
    """사슬(A→B→C)을 끝까지 풀어 모든 항목이 최종 대표를 가리키게 한다.
    한 번의 실행에서 규칙 대표와 Copilot 대표가 달라 2단 사슬이 생기면, 단일 룩업만
    하는 적용부가 병합을 반쪽으로 만든다(검증 확정).
    순환(A↔B)은 예전처럼 둘 다 조용히 지우지 않는다 — 그러면 그 실행에서 병합이 사라지고 캐시
    항목도 소실됐다(F4). 구성원 중 하나를 결정적으로 대표로 삼아 나머지를 붙이고, log 가 있으면
    알린다(양쪽이 같은 일이라고 말한 것이니 병합 자체는 유지)."""
    out, cycles = {}, []
    for (pj, a), v in amap.items():
        seen = [a]
        while (pj, v) in amap and v not in seen:
            seen.append(v)
            v = amap[(pj, v)]
        if (pj, v) in amap and v in seen:               # 순환 — 되돌아온 지점부터가 구성원
            members = seen[seen.index(v):]
            v = _cycle_rep(members)
            mk = (pj, tuple(sorted(members)))
            if mk not in cycles:
                cycles.append(mk)
        if v != a:
            out[(pj, a)] = v
    if cycles and log is not None:
        for pj, mem in cycles[:5]:
            _say(f"    [!] detail_aliases: '{pj}' 의 병합 방향이 서로를 가리킵니다"
                 f"({' ↔ '.join(mem[:3])}) — '{_cycle_rep(mem)}' 를 대표로 둡니다", log)
    return out


def _parse_alias_obj(o):
    """파일 내용 → {(과제, 이름): 대표}. 형태가 깨졌으면 None(손편집 방어)."""
    mp = o.get("map") if isinstance(o, dict) else None
    if not isinstance(mp, dict):
        return None
    amap = {}
    for k, v in mp.items():
        if isinstance(k, str) and KEY_SEP in k and isinstance(v, str) and v.strip():
            pj, name = k.split(KEY_SEP, 1)
            if name.strip() and name.strip() != v.strip():
                amap[(pj.strip(), name.strip())] = v.strip()
    return amap


def _read_alias_file(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return _parse_alias_obj(json.load(f))
    except (OSError, ValueError):
        return None


def load_detail_aliases():
    """config\\detail_aliases.json → {(과제, 세부업무): 대표}. 사슬은 풀어서 돌려준다.
    config 파일이 아직 없고 옛 report\\보완툴\\detail_aliases.json 이 있으면 한 번 흡수한다."""
    amap = _read_alias_file(ALIAS_FILE) if os.path.exists(ALIAS_FILE) else None
    if amap is None and not os.path.exists(ALIAS_FILE) and os.path.exists(LEGACY_ALIAS_FILE):
        old = _read_alias_file(LEGACY_ALIAS_FILE)
        if old:
            amap = _flatten3_map(old)
            try:
                save_detail_aliases(amap, note=f"흡수: {LEGACY_ALIAS_FILE}")
            except OSError:
                pass
    return _flatten3_map(amap or {})


def save_detail_aliases(amap, note=None):
    """맵 저장(사슬 평탄화 후). 손편집으로 깨진 캐시는 백업으로 옮기고 새로 쓴다."""
    amap = _flatten3_map(dict(amap or {}))
    p = ALIAS_FILE
    if os.path.exists(p) and _read_alias_file(p) is None:
        # 조용히 덮으면 누적된 Copilot 병합이 소실된다(검증 확정) — 옮겨 두고 새로 만든다
        bak = p + time.strftime(".깨짐백업_%Y%m%d_%H%M%S")
        try:
            os.replace(p, bak)
            _say(f"    [!] detail_aliases.json 이 깨져 있어 {os.path.basename(bak)} 로 옮겨 두고 "
                 "새로 만듭니다 — 필요한 줄은 거기서 복사해 오세요")
        except OSError:
            pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    body = {"_설명": "세부업무 표기 병합 맵 — 키 '과제␟이름' → 대표 이름. 한 줄 지우면 그 병합만 원복.",
            "updated": time.strftime("%Y-%m-%d %H:%M"),
            "map": {KEY_SEP.join(k): v for k, v in sorted(amap.items())}}
    if note:
        body["note"] = note
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


# ── Copilot 결과 채택 가드 ────────────────────────────────────────────────
def _accept_group3(grp, pool, weight=None):
    """Copilot 그룹 검증: 실재 이름만, 2개 이상, 괄호 꼬리가 서로 다르면 거부.
    대표는 MM 이 큰 이름 — '리뷰 회의' 같은 곁가지가 묶음의 이름이 되면 어색하다.
    반환 (대표, [나머지]) / 거부면 None."""
    if not isinstance(grp, (list, tuple)):
        return None
    seen, names = set(), []
    for x in grp:
        s = str(x or "").strip()
        if s and s in pool and s not in seen:
            seen.add(s)
            names.append(s)
    if len(names) < 2:
        return None
    if len({_note3(x) for x in names}) > 1:       # '(양산)' vs '(선행)' → 거부
        return None
    w = weight or {}
    canon = max(names, key=lambda x: (w.get(x, 0.0), -len(" ".join(x.split())), -len(x), x))
    return canon, [x for x in names if x != canon]


def _rule_canon(names, pj, mm_w):
    """규칙 병합 대표 — MM 큰 이름, 같으면 공백 정규화가 짧은 이름, 그다음 원문 짧은 이름."""
    return max(names, key=lambda x: (mm_w.get((pj, x), 0.0),
                                     -len(" ".join(x.split())), -len(x), x))


def _final3(amap, pj, name, limit=32):
    """캐시 사슬을 끝까지 따라간 최종 대표. 사슬이 순환하면 name 자신."""
    seen, v = {name}, name
    while (pj, v) in amap and amap[(pj, v)] not in seen and len(seen) < limit:
        v = amap[(pj, v)]
        seen.add(v)
    return v if (pj, v) not in amap else name


def _set_alias(amap, pj, x, canon):
    """(pj, x) → canon 을 **캐시 방향을 지키며** 넣는다 → 새로 넣었으면 True.
    · canon 이 이미 다른 대표로 흡수돼 있으면 그 최종 대표로 치환한다.
    · 그 최종 대표가 x 자신이면(캐시가 x 를 대표로 정해 둔 것) 역방향 간선을 만들지 않는다.
    · x 가 이미 캐시 키(사용자 손편집·지난 실행)면 그대로 둔다 — 캐시가 먼저다.
    순환(A→B, B→A)은 평탄화에서 둘 다 지워져 병합이 격번으로 사라지고 손편집 방향도 지워졌다(F4)."""
    x, canon = str(x or "").strip(), str(canon or "").strip()
    if not x or not canon or x == canon or (pj, x) in amap:
        return False
    rep = _final3(amap, pj, canon)
    if rep == x:
        return False
    amap[(pj, x)] = rep
    return True


def _detail_pools(rows):
    """행 → 과제별 세부업무 집합·(과제, 세부업무) MM 가중치."""
    by_pj, mm_w = {}, {}
    for r in rows:
        pj = (r.get("Level 2") or "").strip() or "공통"
        d = (r.get("Level 3") or "").strip()
        if d:
            by_pj.setdefault(pj, set()).add(d)
            mm = r["_mm"] if "_mm" in r else _f(r.get("mm"))
            mm_w[(pj, d)] = mm_w.get((pj, d), 0.0) + mm
    return by_pj, mm_w


def merge_prompt_sections(by_pj, amap):
    """과제별 목록 조각 [(과제, 텍스트)] — 한 과제가 SECTION_BUDGET 을 넘으면 겹침 2줄로 나눈다.
    pools = {과제: 보낸 이름 집합}(채택 가드용)."""
    pools, secs = {}, []
    for pj, ds in sorted(by_pj.items()):
        todo = sorted({amap.get((pj, d), d) for d in ds})
        if len(todo) < 2:
            continue
        pools[pj] = set(todo)
        piece, psize = [], 0
        for line in (f"- {d}" for d in todo):
            if piece and psize + len(line) > SECTION_BUDGET:
                secs.append((pj, f"[과제] {pj}\n" + "\n".join(piece)))
                piece = piece[-2:]             # 겹침 2줄 — 잘린 자리 앞뒤를 같이 보게
                psize = sum(len(x) for x in piece)
            piece.append(line)
            psize += len(line)
        if piece:
            secs.append((pj, f"[과제] {pj}\n" + "\n".join(piece)))
    return pools, secs


MERGE_HEAD = (
    "다음은 여러 과제의 세부업무 이름 목록이다. **같은 과제 안에서만**, 같은 묶음의 "
    "일(한 덩어리 업무의 검토/수정/회의 같은 국면들)이면 묶어라.\n"
    "확실할 때만 묶고, 성격이 다른 업무·다른 과제끼리는 절대 묶지 마라.\n"
    "이름 끝 괄호 표기('(양산)'/'(선행)' 등)가 다르면 절대 묶지 마라 — 실제 구분이다.\n"
    "이름은 아래 목록의 표기를 **그대로** 옮겨 적어라(줄이거나 고치지 말 것).\n"
    'JSON 만 출력: {"groups": [{"project": "과제명", '
    '"items": [["대표이름", "이름2", ...], ...]}, ...]}\n'
    '묶을 것이 없으면 {"groups": []}\n\n')


def merge_batches(secs, budget=BATCH_BUDGET):
    batches, cur, size = [], [], 0
    for pj, txt in secs:
        if cur and size + len(txt) > budget:
            batches.append(cur)
            cur, size = [], 0
        cur.append((pj, txt))
        size += len(txt)
    if cur:
        batches.append(cur)
    return batches


def _rfind_json(reply, want_key):
    try:
        import judge
        return judge.rfind_json(reply, want_key)
    except ImportError:
        pass
    dec = json.JSONDecoder()
    i = reply.rfind("{")
    n = 0
    while i != -1 and n < 600:
        try:
            o, _ = dec.raw_decode(reply, i)
            if isinstance(o, dict) and want_key in o:
                return o
        except ValueError:
            pass
        n += 1
        i = reply.rfind("{", 0, i)
    return {}


# ── 응답 JSON 회수·복구 (agentic·flow·details 공용) ───────────────────────
# Copilot 실측: 답이 길면 중간에 끊기거나("OK, I've stopped generating the response.") 마크다운으로
# 변형된다(코드펜스·굽은 따옴표). 엄격 파서(rfind_json)는 그런 답을 통째로 버려 그 묶음이 '실패'가
# 됐고, 묶음이 많은 사람일수록 전부 버려져 rc1 이 됐다. 여기서 정규화 → 잘린 JSON 복구 순으로
# 한 번 더 건진다. 복구본은 '부분 결과'라 호출자가 how=="salvaged" 를 보고 정직하게 표시한다.
SENTINEL = "[[전송끝]]"
STOP_MARKS = ("stopped generating", "stopped the response", "생성을 중지", "생성이 중지", "생성을 멈췄",
              "응답 생성을 중단", "응답을 중단했")
_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n?")
_SMART_Q = {"“": '"', "”": '"', "„": '"', "‟": '"', "＂": '"'}
_KEY_START = r'\{\s*"%s"\s*:'


def _normalize_reply(text):
    """중단 문구 뒤·서약·코드펜스를 걷어 내고 굽은 따옴표를 곧게 편다(엄격 파싱이 실패했을 때만 쓴다)."""
    t = str(text or "")
    low = t.lower()
    cut = max((low.rfind(m.lower()) for m in STOP_MARKS), default=-1)
    if cut > 0:
        t = t[:cut]
    t = t.replace(SENTINEL, "\n")
    t = _FENCE_RE.sub("\n", t)
    return "".join(_SMART_Q.get(ch, ch) for ch in t)


def _closers(s):
    """열린 문자열·배열·객체를 닫는 꼬리 — 잘린 JSON 을 파싱 가능하게 만드는 최소 보정."""
    stack, instr, esc = [], False, False
    for ch in s:
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        elif ch == '"':
            instr = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    tail = '"' if instr else ""
    if esc:                                   # 역슬래시 직후에서 잘림 — 그 역슬래시는 버린다
        return None
    return tail + "".join("}" if c == "{" else "]" for c in reversed(stack))


def _last_struct_comma(s):
    """문자열 밖의 마지막 ',' 위치(없으면 -1) — 잘린 마지막 항목을 통째로 버리는 절단점."""
    last, instr, esc = -1, False, False
    for i, ch in enumerate(s):
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        elif ch == '"':
            instr = True
        elif ch == ",":
            last = i
    return last


def _salvage_from(s, want_key, max_cuts):
    s = s.rstrip()
    for _ in range(max_cuts):
        closers = _closers(s)
        if closers is not None:
            try:
                o = json.loads(s + closers)
            except ValueError:
                o = None
            if isinstance(o, dict) and want_key in o:
                return o
        p = _last_struct_comma(s)
        if p <= 0:
            return {}
        s = s[:p].rstrip()
    return {}


def salvage_json(text, want_key, max_cuts=80):
    """잘린 JSON 복구 — '{"want_key":' 로 시작하는 마지막 후보부터, 열린 괄호를 닫아 보고 안 되면
    문자열 밖 마지막 ',' 에서 잘라 다시 시도(마지막 불완전 항목만 버린다). 없으면 {}."""
    text = str(text or "")
    cands = [m.start() for m in re.finditer(_KEY_START % re.escape(want_key), text)]
    first = text.find("{")
    if first >= 0 and first not in cands:
        cands.append(first)
    for start in sorted(set(cands), reverse=True):
        o = _salvage_from(text[start:], want_key, max_cuts)
        if o:
            return o
    return {}


def find_json(reply, want_key):
    """응답에서 {want_key: …} dict → (obj, how). how: "strict"(정상) · "normalized"(펜스·따옴표 정규화)
    · "salvaged"(잘린 JSON 복구 = 부분 결과) · ""(없음, obj {})."""
    text = str(reply or "")
    if not text.strip():
        return {}, ""
    o = _rfind_json(text, want_key)
    if o:
        return o, "strict"
    norm = _normalize_reply(text)
    if norm != text:
        o = _rfind_json(norm, want_key)
        if o:
            return o, "normalized"
    o = salvage_json(norm, want_key)
    if o:
        return o, "salvaged"
    return {}, ""


def strip_prompt_echo(reply, prompt, min_len=25):
    """회수 결과에서 '되돌아온 우리 프롬프트' 를 잘라 낸다 — 앵커를 못 찾으면 보낸 말풍선까지 딸려오고,
    그러면 프롬프트 안의 예시가 답으로 읽힌다(실측 사고). 프롬프트 끝쪽 긴 줄을 기준으로 그 뒤만."""
    reply, prompt = str(reply or ""), str(prompt or "")
    if not reply or not prompt:
        return reply
    tail = [ln.strip() for ln in prompt.splitlines() if len(ln.strip()) >= min_len]
    for ln in reversed(tail[-6:]):
        i = reply.rfind(ln)
        if i >= 0:
            return reply[i + len(ln):]
    return reply


def reply_diagnosis(reply, prompt=""):
    """JSON 을 못 찾은 응답이 '무엇이었는지' 한 줄 — 화면 hint 용."""
    r = str(reply or "").replace(SENTINEL, "").strip()
    if not r:
        return "빈 응답 — Copilot 이 답을 쓰지 않았거나 회수 시점이 일렀습니다"
    low = r.lower()
    if any(m.lower() in low for m in STOP_MARKS):
        return "Copilot 이 답 생성을 중단했습니다('stopped generating') — 답이 길어 잘렸습니다"
    if prompt and len(r) > 200 and r[:120].strip() and r[:120].strip() in prompt:
        return "응답 대신 프롬프트가 되돌아왔습니다 — 답을 다 쓰기 전에 회수했거나 입력이 잘렸을 수 있습니다"
    head = " ".join(r[:80].split())
    return f"JSON 형식이 아닌 답(앞부분: {head})"


# ── 왕복 실패 사유 (드라이버 phase → 사람이 할 일) ─────────────────────────
# tools/copilot_auto.py 의 phase 를 화면·기록에 그대로 두면 '왕복 실패' 한 마디만 남는다(실측).
# fatal = 사람이 손대야 풀리는 상태 — 남은 묶음을 보내도 같은 결과이므로 즉시 접는다.
FATAL_PHASES = {"login_required", "edge_not_found", "launch_failed", "input_not_found"}
PHASE_TEXT = {
    "login_required": ("Copilot 로그인 필요(만료)",
                       "전용 Edge 창(자동 프로필)에서 회사 계정으로 로그인한 뒤 다시 실행 — [AI 연결 진단]으로 확인"),
    "edge_not_found": ("Microsoft Edge 실행 파일을 찾지 못함", "Edge 설치 확인 후 다시 실행"),
    "launch_failed": ("Edge(자동 프로필)를 디버그 포트로 띄우거나 Copilot 탭을 만들지 못함",
                      "이미 열려 있는 자동 프로필 Edge 창(data\\copilot_profile)을 모두 닫고 다시 실행 · "
                      "회사 보안 정책이 디버그 포트를 막으면 [AI 연결 진단]으로 확인"),
    "input_not_found": ("Copilot 채팅 입력창을 찾지 못함",
                        "Copilot 화면이 바뀌었을 수 있습니다 — data\\copilot_auto_debug.json 을 확인"),
    "no_reply": ("Copilot 응답 시간 초과", "Copilot 창에서 생성이 멈췄는지 확인하고 잠시 뒤 다시 실행"),
    "copilot_error": ("Copilot 일시 오류 응답", "잠시 뒤 다시 실행 — 반복되면 Copilot 창 상태 확인"),
    "stub": ("스텁 응답 없음(LM_COPILOT_STUB)", "스텁 폴더에 응답 파일을 두거나 환경 변수를 지우세요"),
    "timeout": ("왕복 시간 초과", "Copilot 응답 지연 — 잠시 뒤 다시 실행"),
}
_FATAL_ERRORS = ("드라이버 실행 실패", "프롬프트 파일 쓰기 실패")


def explain_failure(res):
    """실패 dict(드라이버·judge.copilot_send) → (사유 한 줄, 조치, fatal)."""
    res = res if isinstance(res, dict) else {}
    phase = str(res.get("phase") or "").strip()
    err = str(res.get("error") or "").strip()
    hint = str(res.get("hint") or "").strip()
    if phase in PHASE_TEXT and phase != "error":
        why, how = PHASE_TEXT[phase]
        if phase == "no_reply" and hint:
            how = hint
        return why, how, phase in FATAL_PHASES
    if not phase and "시간 초과" in err:
        return PHASE_TEXT["timeout"][0], hint or PHASE_TEXT["timeout"][1], False
    fatal = any(err.startswith(x) for x in _FATAL_ERRORS)
    return (err or "왕복 실패"), hint, fatal


def _call_sender(sender, prompt, tag, name, fresh):
    """sender 계약(prompt, tag, name[, fresh]) — fresh 를 모르는 옛 sender 도 받는다."""
    try:
        return sender(prompt, tag, name, fresh=fresh)
    except TypeError as e:
        if "fresh" not in str(e):
            raise
        return sender(prompt, tag, name)


def ask_json(sender, prompt, tag, name, want_key, fresh=None):
    """왕복 1회 + JSON 회수 → (obj, info).
    obj: want_key 를 가진 dict(없으면 {}). info: {"ok", "how", "error", "hint", "phase", "fatal", "kind",
    "model", "retry", "reply_len"} — kind 는 "roundtrip"(왕복 자체 실패) / "parse"(답은 왔으나 JSON 없음).
    fresh=None(기본): 묶음을 **같은 채팅에서 이어** 보낸다 — 새 채팅 여부는 sender(judge.copilot_send)가 정한다(첫 왕복·
    실패 뒤·config.copilotAuto.chatTurns 마다). 앞 묶음의 답이 되풀이돼 섞여 오는 것은 strip_prompt_echo·find_json 이 걷어낸다.
    fresh=True 는 문맥 오염이 곧 오답인 왕복(팀 유사 항목 정리처럼 앞 묶음과 무관한 목록)에만."""
    try:
        res = _call_sender(sender, prompt, tag, name, fresh)
    except Exception as e:  # noqa: BLE001 - sender 예외가 단계 전체를 죽이지 않게
        res = {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {str(e)[:80]}"}
    if not isinstance(res, dict) or not res.get("ok"):
        why, how, fatal = explain_failure(res)
        return {}, {"ok": False, "kind": "roundtrip", "error": why, "hint": how, "fatal": fatal,
                    "phase": str((res or {}).get("phase") or "") if isinstance(res, dict) else ""}
    reply = str(res.get("reply") or "")
    body = strip_prompt_echo(reply, prompt)
    o, how = find_json(body, want_key)
    if not o and body != reply:
        o, how = find_json(reply, want_key)
    if not o:
        return {}, {"ok": False, "kind": "parse", "error": "응답에서 JSON 을 찾지 못함",
                    "hint": reply_diagnosis(reply, prompt), "fatal": False, "phase": "parse",
                    "reply_len": len(reply)}
    return o, {"ok": True, "how": how, "model": str(res.get("model") or ""),
               "retry": res.get("retry"), "reply_len": len(reply)}


LAST_FAIL = {}           # detail_merge_map 의 마지막 왕복 실패 info — flow 가 읽어 fatal 이면 왕복을 접는다


def save_json_atomic(path, obj, tries=6):
    """tmp 에 쓰고 os.replace — 윈도우에서 백신·색인기가 목표 파일을 잠깐 잡고 있으면 PermissionError
    (WinError 5/32)가 난다(실측: 묶음마다 저장하는 흐름에서 재현). 짧게 쉬고 다시 시도하고, 끝내
    안 되면 직접 덮어쓴다 — 저장 한 번 실패로 판정 전체가 죽지 않게."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            time.sleep(0.2 * (i + 1))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return path


def detail_merge_map(tag, sender=None, rows=None, log=print):
    r"""(과제, 세부업무) 병합 맵 → (amap, n_rule, n_ai). 캐시에 누적 저장한다.

    sender: judge.copilot_send 계약 — sender(prompt_text, tag, name) -> {"ok","reply",...}.
      None 이면 규칙 병합만(Copilot 이 안 되는 날·--no-merge). sender 가 주어졌으면 왕복
      여부는 호출자 책임 — env 게이트를 또 걸면 모의 sender 테스트·수동 호출까지 막힌다(실측).
    rows: 이미 읽은 mm_rows 행(없으면 tag 로 읽는다)."""
    if rows is None:
        rows, _fn = read_rows(tag)
    by_pj, mm_w = _detail_pools(rows)
    amap = load_detail_aliases()
    loaded = dict(amap)
    reps_by = {}                          # 과제별 캐시 대표(값) 집합 — 규칙 대표 선택에 우선한다
    for (p, _k), rv in amap.items():
        reps_by.setdefault(p, set()).add(rv)
    n_rule = 0
    for pj, ds in by_pj.items():
        by_k = {}
        for d in ds:
            by_k.setdefault(ukey3(d), []).append(d)
        for v in by_k.values():
            if len(v) > 1:
                # 캐시가 이미 대표로 쓰는 이름이 무리 안에 있으면 그것을 대표로 고정한다 — 기간별
                # MM 에 따라 대표가 뒤집혀 캐시와 반대 방향의 간선이 생기고, 평탄화가 그 순환을 통째로
                # 지워 병합이 격번으로 빠지던 결함(F4). 없으면 예전대로 MM 큰 이름.
                fixed = [x for x in v if x in reps_by.get(pj, ())]
                canon = _rule_canon(fixed or v, pj, mm_w)
                for x in v:
                    if _set_alias(amap, pj, x, canon):
                        n_rule += 1
    amap = _flatten3_map(amap, log)

    n_ai = 0
    if sender is not None:
        # 과제마다 따로 왕복하면 과제 수만큼 Copilot 을 기다려 멈춘 것처럼 보인다(제보) —
        # 여러 과제를 한 프롬프트에 묶어 7,000자 단위로만 나눈다.
        pools, secs = merge_prompt_sections(by_pj, amap)
        batches = merge_batches(secs)
        if len(batches) > MAX_ROUNDTRIPS:
            _say(f"  [details] 세부 병합 묶음 {len(batches)}개 중 앞 {MAX_ROUNDTRIPS}개만 "
                 "Copilot 에 묻습니다(왕복 상한)", log)
            batches = batches[:MAX_ROUNDTRIPS]
        if batches:
            _say(f"  [details] 세부업무 병합 — 과제 {len(pools)}개를 Copilot {len(batches)}회 "
                 "왕복으로 묶어 물어봅니다 (보내는 것: 과제명·업무명뿐)", log)
        rejected = 0
        LAST_FAIL.clear()
        for bi, batch in enumerate(batches, 1):
            o, info = ask_json(sender, MERGE_HEAD + "\n\n".join(t for _pj, t in batch),
                               f"{tag}-d3-{bi}", "detail3", "groups")
            if not info.get("ok"):
                LAST_FAIL.update(info)
                if info.get("kind") == "parse":
                    _say(f"    [!] 병합 왕복 {bi}/{len(batches)} 응답에 groups JSON 이 없습니다"
                         f"({info.get('hint', '')[:60]}) — 건너뜀", log)
                    continue
                _say(f"    [!] 병합 왕복 {bi}/{len(batches)} 실패({info.get('error', '')[:60]}"
                     + (f" — {info.get('hint', '')[:80]}" if info.get("hint") else "")
                     + ") — 규칙 병합만 반영하고 남은 왕복은 접습니다", log)
                break                            # Copilot 이 안 되는 날 — 더 기다리게 하지 않는다
            if info.get("how") == "salvaged":
                _say(f"    [!] 병합 왕복 {bi}/{len(batches)} 응답이 잘려 복구한 부분만 씁니다", log)
            for grp in (o.get("groups") or []):
                if not isinstance(grp, dict):
                    continue
                pj = str(grp.get("project") or "").strip()
                pool = pools.get(pj)
                if not pool:
                    rejected += 1                # 지어낸 과제명·다른 과제 섞기 방지
                    continue
                for items in (grp.get("items") or []):
                    if not isinstance(items, list):
                        continue
                    acc = _accept_group3(items, pool, {d: mm_w.get((pj, d), 0.0) for d in pool})
                    if not acc:
                        if len([x for x in items if str(x or "").strip() in pool]) >= 2:
                            _say(f"    [가드] {pj}: 괄호 꼬리가 다른 묶음 거부 — "
                                 f"{' / '.join(str(x)[:20] for x in items[:3])}", log)
                        rejected += 1
                        continue
                    canon, alts = acc
                    for x in alts:
                        if _set_alias(amap, pj, x, canon):     # 캐시 방향 우선(F4)
                            n_ai += 1
        if rejected:
            _say(f"    [가드] 채택하지 않은 묶음 {rejected}개(실재하지 않는 이름·1개짜리·"
                 "괄호 꼬리 상이·모르는 과제)", log)
    amap = _flatten3_map(amap, log)
    if amap != loaded or not os.path.exists(ALIAS_FILE):
        try:
            save_detail_aliases(amap)
        except OSError as e:
            _say(f"    [!] detail_aliases.json 저장 실패({type(e).__name__}) — 이번 실행에만 적용", log)
    return amap, n_rule, n_ai


# ── 적용 ──────────────────────────────────────────────────────────────────
def apply_detail_map(rows, sigs, amap):
    """mm_rows 행과 신호의 Level 3 표기를 병합 맵의 대표 이름으로 — 원본 파일은 무수정.
    (rows/sigs 를 제자리에서 바꾼다. 원본을 지키려면 사본을 넘길 것.)"""
    if not amap:
        return rows, sigs
    for r in (rows or []):
        pj = (r.get("Level 2") or "").strip() or "공통"
        d = (r.get("Level 3") or "").strip()
        nd = amap.get((pj, d), d)
        if nd != d:
            r["Level 3"] = nd
    for s2 in (sigs or []):
        pj = (s2.get("model") or s2.get("project") or "").strip() or "공통"
        d = (s2.get("detail") or s2.get("activity") or "").strip()
        nd = amap.get((pj, d), d)
        if nd == d:
            continue
        if s2.get("detail") is not None:
            s2["detail"] = nd
        elif s2.get("activity") is not None:
            s2["activity"] = nd
    return rows, sigs


def merge_report_rows(rows):
    """분석리포트 업무별 상세용 — 같은 (Level 2, Level 3) 행을 한 줄로(mm·share 합산)."""
    by, order = {}, []
    for r in rows:
        k = ((r.get("Level 2") or "").strip(), (r.get("Level 3") or "").strip())
        if k in by:
            g = by[k]
            g["mm"] = str(round(_f(g.get("mm")) + _f(r.get("mm")), 3))
            g["share"] = str(round(_f(g.get("share")) + _f(r.get("share")), 4))
            if "_mm" in g or "_mm" in r:
                g["_mm"] = _f(g.get("_mm")) + _f(r.get("_mm"))
            if r.get("상세설명") and r["상세설명"] not in (g.get("상세설명") or ""):
                g["상세설명"] = ((g.get("상세설명") or "") + " · " + r["상세설명"]).strip(" ·")
            if r.get("근거") and r["근거"] not in (g.get("근거") or ""):
                g["근거"] = ((g.get("근거") or "") + "·" + r["근거"]).strip("·")
        else:
            by[k] = dict(r)
            order.append(k)
    return [by[k] for k in order]


if __name__ == "__main__":
    # python core\details.py <tag>  → 규칙 병합만 실행하고 맵을 출력(진단용)
    import sys
    _tag = sys.argv[1] if len(sys.argv) > 1 else ""
    if _tag:
        _amap, _nr, _na = detail_merge_map(_tag, None)
        print(json.dumps({"rule": _nr, "ai": _na,
                          "map": {KEY_SEP.join(k): v for k, v in _amap.items()}},
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps({"map": {KEY_SEP.join(k): v for k, v in load_detail_aliases().items()}},
                         ensure_ascii=False, indent=1))
