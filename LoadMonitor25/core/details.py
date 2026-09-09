# -*- coding: utf-8 -*-
r"""
details.py — 세부업무(Level 3) 표기 병합 맵 (LoadMonitor25, 보완2 이식)

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
from datetime import date as _date2

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


def read_rows(tag, rep=None, plain=False):
    """mm_rows(정제본 우선) → (행 목록, 파일명). 각 행에 _mm(float) 을 붙인다.

    plain=True 면 정제본을 건너뛰고 원본 mm_rows_<tag>.csv 만 읽는다 — 신호(signals)와 **같은 이름 축**이
    필요한 곳(워크플로우 MM 조회)에서 쓴다. 정제본은 refine 이 이름을 합치고 바꾸므로
    (예: '판정엔진'·'검증' → '판정엔진 고도화 및 검증') 신호 축 키로 찾으면 하나도 안 맞는다(실측)."""
    p = os.path.join(rep or REPORT, f"mm_rows_{tag}.csv") if plain else rows_path(tag, rep)
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
def _snap3(pool):
    """이름 → 실재 이름 스냅 표. 답이 표기를 흔들어 되돌려 줘도 알아보게 한다.
    후보가 둘 이상인 축 값은 버린다(모호하면 안 쓴다 — flow._uniq_map 과 같은 규칙)."""
    out = {}
    for ax in (lambda x: x, lambda x: x.strip().casefold(), ukey3, _ukey3p):
        seen = {}
        for nm in pool:
            k = ax(nm)
            if not k:
                continue
            seen.setdefault(k, []).append(nm)
        for k, v in seen.items():
            if len(v) == 1 and k not in out:
                out[k] = v[0]
    return out


def _accept_group3(grp, pool, weight=None):
    """Copilot 그룹 검증 → (대표, [나머지]) / 거부면 None.

    · 실재 이름만 — 다만 **정확일치만 보지 않는다**. 답이 공백 하나만 흔들어도 묶음이 통째로
      버려졌다(감사 실측: '한 이름만 표기 흔들림' → 그룹 거부). flow._resolve_key 가 같은 문제에
      여러 축을 쓰는 것과 같이, 여기서도 실재 이름으로 스냅한 뒤 판정한다.
    · 괄호 꼬리('(양산)' vs '(선행)')는 **그룹 거부가 아니라 멤버 배제**로 바꿨다. 예전에는 꼬리가
      다른 이름 하나가 섞이면 나머지 유효한 병합까지 함께 사라졌다(실측: 유효 2건 동반 소실).
      가장 많은 꼬리 쪽을 남기고 다른 꼬리는 뺀 뒤, 남은 것이 2개 이상이면 채택한다.
    · 대표는 MM 이 큰 이름 — '리뷰 회의' 같은 곁가지가 묶음의 이름이 되면 어색하다."""
    if not isinstance(grp, (list, tuple)):
        return None
    snap = _snap3(pool)
    seen, names = set(), []
    for x in grp:
        s = str(x or "").strip()
        if not s:
            continue
        hit = (s if s in pool else
               snap.get(s) or snap.get(s.casefold()) or snap.get(ukey3(s)) or snap.get(_ukey3p(s)))
        if hit and hit not in seen:
            seen.add(hit)
            names.append(hit)
    if len(names) < 2:
        return None
    notes = {}
    for x in names:
        notes.setdefault(_note3(x), []).append(x)
    if len(notes) > 1:
        keep = max(notes.values(), key=lambda v: (len(v), -len(v[0])))
        names = [x for x in names if x in keep]
        if len(names) < 2:
            return None
    w = weight or {}
    canon = max(names, key=lambda x: (w.get(x, 0.0), len(" ".join(x.split())), -len(x), x))
    return canon, [x for x in names if x != canon]


# ── 담당업무(Level 3) 구조 규칙 ────────────────────────────────────────────
# ukey3 하나로는 '공백·구분자·대소문자' 만 접힌다. 실제 응답은 꼬리 문장부호('샘플 평가.'),
# 어미('검토'/'검토 작업'), 어순('설계 검증'/'검증 설계'), 낱말 하나 차이('금형 수정'/'금형 수정 요청')
# 로 흔들린다. 아래 규칙은 전부 **표기·구조** 만 본다 — 도메인 어휘 목록을 쓰지 않는다.
_TAIL3 = re.compile(r"[.…,~!?:;·\-\s]+$")
# 2자 이상 조사만 뗀다. 1자 조사(도·이·가·은·는·로·에·만)를 넣으면 '설계도' 가 '설계' 로 접혀
# 오병합된다(실측) — 넣지 말 것.
_JOSA3 = ("으로", "에서", "부터", "까지", "에게", "및", "의", "와", "과")
MIN_HEAD3 = 4                  # 접두 규칙에서 짧은 쪽이 이보다 짧으면 쓰지 않는다
MAX_TAIL3 = 3                  # 접두 규칙에서 붙는 꼬리 길이 상한 — 4자면 '검토'/'검토 반려 대응' 이 붙는다


def _ukey3p(s):
    """ukey3 에 꼬리 문장부호까지 걷어낸 축 — '샘플 평가.' == '샘플 평가'."""
    return _TAIL3.sub("", _fold3(s, drop_note=False)).replace(" ", "")


def _toks3(s):
    """조사·꼬리부호를 뗀 토큰 집합 — 어순이 바뀌어도 같은 값이 되게."""
    out = set()
    for t in _TAIL3.sub("", _fold3(s, drop_note=False)).split():
        for j in _JOSA3:
            if len(t) > len(j) + 1 and t.endswith(j):
                t = t[:-len(j)]
                break
        if t:
            out.add(t)
    return out


def _same_detail3(a, b):
    """같은 담당업무로 볼 수 있는가 → 사유 문자열 또는 "".
    괄호 꼬리·숫자 토큰이 다르면 무조건 아니다(차수·버전·양산/선행 구분을 지운다)."""
    if _note3(a) != _note3(b) or _nums2(a) != _nums2(b):
        return ""
    ka, kb = _ukey3p(a), _ukey3p(b)
    if ka == kb:
        return "표기 동일"
    lo, hi = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(lo) >= MIN_HEAD3 and hi.startswith(lo) and len(hi) - len(lo) <= MAX_TAIL3:
        return f"앞부분 동일(꼬리 {len(hi) - len(lo)}자)"
    ta, tb = _toks3(a), _toks3(b)
    if ta and ta == tb:
        return "낱말 같음(어순 무시)"
    if len(ta & tb) >= 2 and len(ta ^ tb) == 1:
        return "낱말 하나 차이"
    return ""


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


# ── 중위(과제) 표기 병합 ──────────────────────────────────────────────────
# Level 3 에는 신원 축(ukey3)과 병합 캐시가 있는데 Level 2 에는 없었다 — judge.to_model 의
# 소문자 정확 일치가 전부라, 띄어쓰기 하나만 흔들려도 새 과제가 생겼다. 그 변형은 다시
# entities_*.json 에 discovered 로 적립돼 다음 실행의 후보로 되먹여져 분할이 영구화된다.
# 갈라지면 (1) 워크플로우 카드가 여러 장이 되고 (2) _detail_pools 의 파티션 키가 raw Level 2 라
# 세부업무 병합까지 반쪽이 되며 (3) MM 은 fold 축에서 조회되므로 갈라진 카드마다 같은 MM 이
# 붙어 총합이 부푼다(감사 합성 실측: 1.8 MM vs 실제 1.2).
#
# 여기서는 **Copilot 왕복을 새로 만들지 않는다** — 표기 규칙과 이미 저장소에 있는 증거
# (refine_map · 담당업무 집합 · 제품 열 · 신호 시간대)만 쓴다. 도메인 어휘는 한 글자도 쓰지 않는다.
PROJ_ALIAS_FILE = os.path.join(CONFIG, "project_aliases.json")
GENERIC2 = {"공통", "기타", "미분류", "일반"}   # 기본값 이름 — 병합 후보에서 제외
MAX_ABSORB2 = 4        # 한 대표가 한 실행에서 흡수할 수 있는 다른 이름 수
MAX_GROUP2 = 5         # 한 병합 무리의 최대 크기 — 넘으면 그 무리를 통째로 거부
DICE2 = 0.60           # 이름 유사도 문턱(2-gram Dice)
JACCARD2 = 0.50        # 담당업무 집합 겹침 문턱
MIN_SPAN_GAP2 = 14     # 신호 시간대 비겹침 판정의 최소 간격(일)


# ── 상위(Level 1) 신원 축 ──────────────────────────────────────────────────
# 상위는 **4개 고정 범주**인데, refine 이 모델이 돌려준 문자열을 검증 없이 그대로 저장했다
# (Level 2·3·활동은 스냅·화이트리스트로 지키면서 여기만 무방비였다). 그래서 '기술내재화'(공백 없음)
# 같은 표기 변형이 다섯 번째 상위처럼 화면에 떴다(감사 실측). 고정 목록이 있으므로 스냅하면 끝난다.
LEVEL1_SET = ("신제품개발", "기술 내재화", "양산준비", "일반업무")


def ukey1(s):
    """상위 신원 축 — ukey2 와 같은 규칙(공백·구분자·대소문자 무시)."""
    return _fold3(s, drop_note=True).replace(" ", "")


_L1_BY_KEY = {ukey1(x): x for x in LEVEL1_SET}


def snap1(s):
    """모델이 돌려준 상위 문자열 → 고정 범주 이름. 못 짚으면 "" (억지로 찍지 않는다).
    앞부분 일치는 **후보가 유일할 때만** 쓴다 — 모호하면 쓰지 않는 것이 이 저장소의 규칙(_snap3)."""
    k = ukey1(s)
    if not k:
        return ""
    if k in _L1_BY_KEY:
        return _L1_BY_KEY[k]
    cand = {v for kk, v in _L1_BY_KEY.items() if kk.startswith(k[:3]) or k.startswith(kk[:3])}
    return next(iter(cand)) if len(cand) == 1 else ""


def ukey2(s):
    """중위(과제) 신원 축 — ukey3·team_report.ukey 와 **같은 규칙**.
    괄호 꼬리는 남기고(='(양산)'/'(선행)' 은 실제 구분) 공백·구분자·대소문자는 무시한다."""
    return _fold3(s, drop_note=False).replace(" ", "")


def note2(s):
    """이름 끝 괄호 표기 — 다르면 무조건 합치지 않는다(_note3 의 대칭 이름)."""
    return _note3(s)


def bigram_dice(a, b):
    """이름 유사도 — team_report.bigram_dice 와 같은 축(개인·팀이 같은 값을 본다)."""
    def bg(t):
        t = _fold3(t).replace(" ", "")
        return {t[i:i + 2] for i in range(len(t) - 1)} or {t}
    x, y = bg(a), bg(b)
    return 2 * len(x & y) / (len(x) + len(y) or 1)


_NUM2 = re.compile(r"\d+")


def _nums2(s):
    """이름 안 숫자 토큰 — '2차'/'3차', 'v1'/'v2' 는 다른 과제다(표기 규칙이지 도메인 어휘가 아니다)."""
    return set(_NUM2.findall(_fold3(s, drop_note=False)))


def _toks2(s):
    return set(_fold3(s, drop_note=False).split())


def _jac2(a, b):
    a, b = set(a or ()), set(b or ())
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _pair2(a, b):
    return frozenset((ukey2(a), ukey2(b)))


# ── 캐시 (config\project_aliases.json) ────────────────────────────────────
def _flatten2_map(pmap, log=None):
    """사슬(A→B→C) 평탄화 — _flatten3_map 의 2층판(스코프 없음). 순환은 지우지 않고 대표를 정한다."""
    out, cycles = {}, []
    for a, v in pmap.items():
        seen = [a]
        while v in pmap and v not in seen:
            seen.append(v)
            v = pmap[v]
        if v in pmap and v in seen:
            members = seen[seen.index(v):]
            v = _cycle_rep(members)
            mk = tuple(sorted(members))
            if mk not in cycles:
                cycles.append(mk)
        if v != a:
            out[a] = v
    if cycles and log is not None:
        for mem in cycles[:5]:
            _say(f"    [!] project_aliases: 병합 방향이 서로를 가리킵니다({' ↔ '.join(mem[:3])})"
                 f" — '{_cycle_rep(mem)}' 를 대표로 둡니다", log)
    return out


def _final2(pmap, name, limit=32):
    seen, v = {name}, name
    while v in pmap and pmap[v] not in seen and len(seen) < limit:
        v = pmap[v]
        seen.add(v)
    return v if v not in pmap else name


def _set_alias2(pmap, x, canon):
    """x → canon 을 **캐시 방향을 지키며** 넣는다 → 새로 넣었으면 True(_set_alias 의 2층판)."""
    x, canon = str(x or "").strip(), str(canon or "").strip()
    if not x or not canon or x == canon or x in pmap:
        return False
    rep = _final2(pmap, canon)
    if rep == x:
        return False
    pmap[x] = rep
    return True


def _parse_proj_obj(o):
    """파일 → (맵, never 비교키 집합, never 원문쌍). 형태가 깨졌으면 맵 자리에 None."""
    if not isinstance(o, dict):
        return None, set(), []
    never_keys, never_raw = set(), []
    for pr in (o.get("never") or []):
        if isinstance(pr, (list, tuple)) and len(pr) == 2:
            a, b = str(pr[0] or "").strip(), str(pr[1] or "").strip()
            if a and b:
                never_keys.add(_pair2(a, b))
                never_raw.append([a, b])
    mp = o.get("map")
    if not isinstance(mp, dict):
        return None, never_keys, never_raw
    pmap = {}
    for k, v in mp.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip() and k.strip() != v.strip():
            pmap[k.strip()] = v.strip()
    return pmap, never_keys, never_raw


def load_project_aliases():
    """config\\project_aliases.json → (맵, never 비교키, never 원문쌍). 사슬은 풀어서 돌려준다."""
    try:
        with open(PROJ_ALIAS_FILE, encoding="utf-8-sig") as f:
            pmap, nk, nr = _parse_proj_obj(json.load(f))
    except (OSError, ValueError):
        return {}, set(), []
    return _flatten2_map(pmap or {}), nk, nr


def save_project_aliases(pmap, never_raw=(), note=None):
    """맵 저장(사슬 평탄화 후). 손편집으로 깨진 캐시는 백업으로 옮기고 새로 쓴다."""
    pmap = _flatten2_map(dict(pmap or {}))
    p = PROJ_ALIAS_FILE
    if os.path.exists(p):
        broken = False
        try:
            with open(p, encoding="utf-8-sig") as f:
                cur, _nk, _nr = _parse_proj_obj(json.load(f))
            broken = cur is None
        except (OSError, ValueError):
            broken = True
        if broken:
            bak = p + time.strftime(".깨짐백업_%Y%m%d_%H%M%S")
            try:
                os.replace(p, bak)
                _say(f"    [!] project_aliases.json 이 깨져 있어 {os.path.basename(bak)} 로 옮겨 두고 "
                     "새로 만듭니다 — 필요한 줄은 거기서 복사해 오세요")
            except OSError:
                pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    body = {"_설명": "과제(중위) 표기 병합 맵 — '변형' → '대표'. 한 줄 지우면 그 병합만 원복됩니다. "
                     "다만 띄어쓰기·구분자만 다른 이름은 규칙이 다음 실행에 다시 합치므로, "
                     "영영 갈라 두려면 never 에 [\"이름A\", \"이름B\"] 쌍을 적으세요.",
            "updated": time.strftime("%Y-%m-%d %H:%M"),
            "map": dict(sorted(pmap.items())),
            "never": [list(x) for x in (never_raw or [])]}
    if note:
        body["note"] = note
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


# ── 채택 가드 ──────────────────────────────────────────────────────────────
def _accept_pair2(a, b, ev, never_keys, ctx):
    """두 과제 이름을 합쳐도 되는가 → (채택, 사유 한 줄).

    never 다음은 **표기 동일(ukey2)** 이다. 그 아래 구조 검사는 표기만 다른 쌍에는 정의상 무의미한데
    (정규화하면 같은 문자열이라 괄호 꼬리·숫자 토큰·토큰 집합이 반드시 같다), 예전에는 채택이 거부
    규칙 **뒤에** 있어서 '담당업무 완전 배타'·'신호 시간대 비겹침'·'둘 다 지정 과제' 에 걸렸다.
    표기가 갈린 과제는 대개 기간이 나뉘어 담당업무가 안 겹치는 바로 그 모습이라, **가장 안전한
    병합이 가장 자주 막혔다**(감사 실측). 게다가 pinned 검사는 ukey2 가 같으면 한 항목을 두 번
    보는 셈이라 지정 과제의 표기 변형을 늘 거부했다.
    표기가 다르면 그때 구조 검사를 모두 거치고, 서로 독립인 근거가 2개 이상일 때만 채택한다 —
    서로 다른 업무가 한 카드에 섞이는 것이 이 기능의 유일한 심각한 실패이므로 애매하면 합치지 않는다."""
    if _pair2(a, b) in never_keys:
        return False, "never 목록(사용자가 다르다고 표시)"
    if ev.get("ukey2"):
        return True, "표기 동일(공백·구분자·대소문자만 다름)"
    if note2(a) != note2(b):
        return False, f"괄호 꼬리 상이('{note2(a)}' vs '{note2(b)}')"
    if _nums2(a) != _nums2(b):
        return False, "숫자 토큰 상이(차수·버전)"
    ta, tb = _toks2(a), _toks2(b)
    if (ta < tb or tb < ta) and len(ta ^ tb) >= 2:
        return False, "한쪽이 다른 쪽의 진부분집합 + 잔여 토큰 2개 이상(상위/하위 관계 의심)"
    la, lb = ctx["l3"].get(a) or set(), ctx["l3"].get(b) or set()
    if len(la) >= 2 and len(lb) >= 2 and not (la & lb):
        return False, "담당업무 집합이 완전 배타"
    sa, sb = ctx["span"].get(a), ctx["span"].get(b)
    lim = int(ctx.get("half_days") or 0)
    if sa and sb and lim:
        gap = (max(sa[0], sb[0]) - min(sa[1], sb[1])).days
        if gap >= lim:
            return False, f"신호 시간대 비겹침({gap}일 간격)"
    pin = ctx.get("pinned") or set()
    if ukey2(a) in pin and ukey2(b) in pin:
        return False, "둘 다 사용자 지정 과제(config\\projects.json)"
    hit = [k for k in ("dice", "refine", "l3", "product") if ev.get(k)]
    if len(hit) >= 2:
        return True, f"독립 근거 {len(hit)}개({'·'.join(hit)})"
    return False, f"근거 부족({len(hit)}개 — 2개 필요)"


# ── 점수와 제약 클러스터링 ────────────────────────────────────────────────
# 예전에는 근거를 **개수로 세고**(2개 이상) 그 앞에 **하드 비토**를 뒀다. 그래서 담당업무 집합이
# 완전히 같은(Jaccard 1.0) 두 과제가 '근거 부족 1개' 로 거부되고, 이름이 닮고 제품이 같은 짝이
# '담당업무 완전 배타' 로 거부됐다 — 기간이 갈린 같은 과제가 바로 그 모습이라, 가장 안전한 병합이
# 가장 자주 막혔다(감사 실측). 이제 **가중치를 합산**하고 두 문턱으로 나눈다.
#
# 절대 뒤집으면 안 되는 것(사용자 의사·차수/버전 구분)만 -∞ 로 남긴다: never · 괄호 꼬리 · 숫자 토큰.
# 나머지(담당업무 배타·시간대 비겹침·진부분집합)는 **감점**이다 — 다른 근거가 충분히 세면 이길 수 있다.
W_MERGE = 1.0            # 이 점수 이상이면 병합
W_ASK = 0.35             # 이 점수 이상 W_MERGE 미만은 '애매' — 합치지 않고 사람에게 보여 준다
NEG_INF = float("-inf")


def pair_score(a, b, ev, never_keys, ctx):
    """두 과제 이름의 병합 점수 → (점수, 사유 한 줄). -inf 면 절대 병합 금지."""
    if _pair2(a, b) in never_keys:
        return NEG_INF, "never 목록(사용자가 다르다고 표시)"
    if note2(a) != note2(b):
        return NEG_INF, f"괄호 꼬리 상이('{note2(a)}' vs '{note2(b)}')"
    if _nums2(a) != _nums2(b):
        return NEG_INF, "숫자 토큰 상이(차수·버전)"
    if ev.get("ukey2"):
        return 10.0, "표기 동일(공백·구분자·대소문자만 다름)"
    pin = ctx.get("pinned") or set()
    if ukey2(a) in pin and ukey2(b) in pin:
        return NEG_INF, "둘 다 사용자 지정 과제(config\\projects.json)"

    sc, why = 0.0, []
    dice = bigram_dice(a, b)
    if dice > 0.45:
        v = 2.4 * (dice - 0.45)
        sc += v
        why.append(f"이름 {dice:.2f}")
    la, lb = ctx["l3"].get(a) or set(), ctx["l3"].get(b) or set()
    if la and lb:
        j = _jac2(la, lb)
        if j > 0:
            v = 2.0 * j
            sc += v
            why.append(f"담당업무 {j:.2f}")
        elif len(la) >= 2 and len(lb) >= 2:
            sc -= 0.8
            why.append("담당업무 배타 -0.8")
    if ev.get("refine"):
        sc += 1.0
        why.append("정제가 함께 묶음")
    if ev.get("product"):
        sc += 1.2
        why.append("제품 일치")
    ta, tb = _toks2(a), _toks2(b)
    if (ta < tb or tb < ta) and len(ta ^ tb) >= 2:
        sc -= 0.5
        why.append("진부분집합 -0.5")
    sa, sb = ctx["span"].get(a), ctx["span"].get(b)
    lim = int(ctx.get("half_days") or 0)
    if sa and sb and lim:
        gap = (max(sa[0], sb[0]) - min(sa[1], sb[1])).days
        if gap >= lim:
            sc -= 0.6
            why.append(f"시간대 비겹침 {gap}일 -0.6")
    return sc, (" · ".join(why) + f" → {sc:.2f}" if why else "근거 없음")


def _cost2(part, W):
    """상관 클러스터링 목적함수 — 무리 안 음수 간선의 절댓값 + 무리 밖 양수 간선의 합."""
    where = {}
    for i, grp in enumerate(part):
        for x in grp:
            where[x] = i
    c = 0.0
    for (x, y), w in W.items():
        if w == NEG_INF:
            c += 1e6 if where.get(x) == where.get(y) else 0.0
        elif where.get(x) == where.get(y):
            c += -w if w < 0 else 0.0
        else:
            c += w if w > 0 else 0.0
    return c


def _ok_group(grp, W, cap):
    """무리가 제약을 지키는가 — 금지(-inf) 간선이 안에 없고 크기가 상한 안."""
    if len(grp) > cap:
        return False
    g = sorted(grp)
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            if W.get((g[i], g[j]), 0.0) == NEG_INF:
                return False
    return True


def cluster2(names, W, order, cap):
    """Pivot(KwikCluster) + 국소탐색. 표준 라이브러리만.

    ★ 제약은 **무리 안에서** 강제한다. 쌍 단위 거부만 하던 예전에는 never 로 갈라 둔 두 이름이
    제3의 이름을 경유해 같은 무리가 됐다(감사 확인) — 쌍 거부는 추이적으로 우회된다.
    order 는 결정적이어야 한다(MM 내림 → 사전순, 캐시 대표 우선) — 그래야 기간이 바뀌어도
    같은 자료면 같은 파티션이 나온다(예전에는 MM 값만 달라져도 셋으로 갈렸다)."""
    part, placed = [], set()
    for p in order:
        if p in placed:
            continue
        grp = [p]
        placed.add(p)
        for x in order:
            if x in placed:
                continue
            if W.get((min(p, x), max(p, x)), 0.0) < W_MERGE:
                continue
            if _ok_group(grp + [x], W, cap):
                grp.append(x)
                placed.add(x)
        part.append(grp)
    # 국소탐색 — 한 이름을 다른 무리(또는 단독)로 옮겨 목적함수가 줄면 옮긴다
    for _ in range(6):
        best = _cost2(part, W)
        moved = False
        for gi, grp in enumerate(list(part)):
            if len(grp) <= 1:
                continue
            for x in list(grp):
                for gj in list(range(len(part))) + [-1]:
                    if gj == gi:
                        continue
                    cand = [list(g) for g in part]
                    cand[gi] = [y for y in cand[gi] if y != x]
                    if gj == -1:
                        cand.append([x])
                    else:
                        cand[gj] = cand[gj] + [x]
                        if not _ok_group(cand[gj], W, cap):
                            continue
                    cand = [g for g in cand if g]
                    c = _cost2(cand, W)
                    if c < best - 1e-9:
                        best, part, moved = c, cand, True
                        break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break
    return part


# ── 맵 만들기 ──────────────────────────────────────────────────────────────
def project_merge_map(rows, sigs=None, refmap=None, pinned=(), log=print):
    """과제(중위) 표기 병합 맵 → (pmap, 규칙 병합 수, 증거 병합 수, 기록).

    기록 = {"pairs": [...], "rejects": [...]} — 무엇을 왜 합쳤고 무엇을 왜 거부했는지.
    rows = mm_rows(plain) · sigs = signals · refmap = flow._refine_orig 결과 ·
    pinned = config\\projects.json 의 지정 과제명. Copilot 왕복 없음."""
    rows = rows or []
    names, mm_w, l3, prod, sig_n = set(), {}, {}, {}, {}
    for r in rows:
        pj = (r.get("Level 2") or "").strip()
        if not pj or pj in GENERIC2:
            continue
        names.add(pj)
        mm_w[pj] = mm_w.get(pj, 0.0) + (r["_mm"] if "_mm" in r else _f(r.get("mm")))
        d = (r.get("Level 3") or "").strip()
        if d:
            l3.setdefault(pj, set()).add(ukey3(d))
        p = (r.get("제품") or "").strip()
        if p:
            prod.setdefault(pj, set()).add(_fold3(p))
    if len(names) < 2:
        return {}, 0, 0, {"pairs": [], "rejects": []}

    span = {}
    for s2 in (sigs or []):
        pj = (s2.get("model") or s2.get("project") or "").strip()
        if pj not in names:
            continue
        sig_n[pj] = sig_n.get(pj, 0) + 1
        t = str(s2.get("time") or "")[:10]
        try:
            dd = _date2.fromisoformat(t)
        except ValueError:
            continue
        cur = span.get(pj)
        span[pj] = (min(cur[0], dd), max(cur[1], dd)) if cur else (dd, dd)
    all_days = 0
    if span:
        all_days = (max(v[1] for v in span.values()) - min(v[0] for v in span.values())).days
    ctx = {"l3": l3, "span": span, "half_days": max(MIN_SPAN_GAP2, all_days // 2),
           "pinned": {ukey2(p) for p in (pinned or []) if p}}

    # refine 이 한 정제 행으로 덮은 원본들이 서로 다른 과제였다면, refine 은 그 둘을 같은 일로 본 것이다
    # (flow._seed_from_refine 은 '과제를 넘나드는 병합' 이라며 이 정보를 버린다 — 여기서 근거로만 줍는다)
    ref_pairs = set()
    for _rk, prs in (refmap or {}).items():
        pjs = sorted({str(p or "").strip() for p, _d in prs if str(p or "").strip()})
        if 2 <= len(pjs) <= MAX_GROUP2:
            for i in range(len(pjs)):
                for j in range(i + 1, len(pjs)):
                    ref_pairs.add(_pair2(pjs[i], pjs[j]))

    pmap, never_keys, never_raw = load_project_aliases()
    cached_reps = set(pmap.values())
    n_rule = n_ev = 0
    pairs, rejects, absorbed = [], [], {}

    def _canon2(group):
        """대표 — 캐시가 이미 대표로 쓰는 이름이 무리에 있으면 그것을 고정(방향 뒤집힘 방지),
        없으면 MM 큰 이름 → **띄어쓰기가 살아 있는 이름** → 원문 짧은 이름 → 사전순.

        Level 3 의 _rule_canon 은 '공백 정규화가 짧은 이름' 을 고르는데, 그것을 과제에 그대로 쓰면
        '광학 설계'/'광학설계' 에서 붙여 쓴 쪽이 대표가 되어 카드 머리말이 읽기 나빠진다(실측).
        과제 이름은 화면에 그대로 보이므로 team_report.local_groups 와 같이 '정보가 많은 표기' 를
        고른다. 그러면서도 '빌드  논의'(공백 둘) 같은 오타는 원문 길이 비교에서 걸러진다 —
        정규화하면 길이가 같고, 원문이 긴 쪽이 지기 때문이다."""
        cached = [x for x in group if x in cached_reps]
        pool = cached or list(group)
        return max(pool, key=lambda x: (mm_w.get(x, 0.0), len(" ".join(x.split())), -len(x), x))

    def _take(x, canon, why, kind):
        # 흡수 한도(MAX_ABSORB2)는 폐기했다 — 그 쌍의 '지역 대표' 를 세는 값이라 사슬로 우회됐고
        # (감사 실측: 상한 4·5인데 6개가 한 무리), 이제는 무리 크기를 클러스터링이 직접 지킨다.
        nonlocal n_rule, n_ev
        if not _set_alias2(pmap, x, canon):
            return
        absorbed[ukey2(canon)] = absorbed.get(ukey2(canon), 0) + 1
        pairs.append({"from": x, "to": _final2(pmap, canon), "why": why,
                      "mm": round(mm_w.get(x, 0.0), 3), "signals": sig_n.get(x, 0)})
        if kind == "rule":
            n_rule += 1
        else:
            n_ev += 1

    # ── 점수 그래프 ─────────────────────────────────────────────────────────
    # 모든 쌍에 점수를 매긴다. -inf 는 절대 금지(never·괄호꼬리·숫자토큰·둘 다 지정 과제),
    # 10.0 은 표기 동일(무조건 병합), 나머지는 근거 가중치의 합이다.
    ns = sorted(names)
    W, pair_why, ask = {}, {}, []
    for i2 in range(len(ns)):
        for j2 in range(i2 + 1, len(ns)):
            a, b = ns[i2], ns[j2]
            ev = {"ukey2": ukey2(a) == ukey2(b),
                  "refine": _pair2(a, b) in ref_pairs,
                  "product": bool((prod.get(a) or set()) & (prod.get(b) or set()))}
            w, why = pair_score(a, b, ev, never_keys, ctx)
            W[(a, b)] = w
            pair_why[(a, b)] = why
            if W_ASK <= w < W_MERGE:
                ask.append({"a": a, "b": b, "why": why})
            elif w != NEG_INF and w < W_ASK and (ev["refine"] or ev["product"] or bigram_dice(a, b) >= 0.5):
                rejects.append({"a": a, "b": b, "why": why})
            elif w == NEG_INF:
                rejects.append({"a": a, "b": b, "why": why})

    # ── 제약 클러스터링 ─────────────────────────────────────────────────────
    # 순서는 결정적이어야 한다 — 캐시가 이미 대표로 쓰는 이름 먼저, 그다음 MM 내림, 사전순.
    # 예전 그리디는 MM 값만 달라져도 파티션이 셋으로 갈렸다(감사 실측).
    order = sorted(ns, key=lambda x: (0 if x in cached_reps else 1, -mm_w.get(x, 0.0), x))
    for grp in cluster2(ns, W, order, MAX_GROUP2):
        if len(grp) < 2:
            continue
        canon = _canon2(grp)
        for x in sorted(grp):
            if x == canon:
                continue
            key = (min(x, canon), max(x, canon))
            why = pair_why.get(key) or "같은 무리"
            kind = "rule" if W.get(key, 0.0) >= 10.0 else "ev"
            _take(x, canon, why, kind)

    pmap = _flatten2_map(pmap, log=log)
    if n_rule or n_ev:
        try:
            save_project_aliases(pmap, never_raw, note=f"규칙 {n_rule} · 증거 {n_ev}")
        except OSError as e:
            _say(f"    [!] project_aliases.json 저장 실패({type(e).__name__}) — 이번 실행에만 적용", log)
    # 한 과제가 전체 MM 의 60% 를 넘게 빨아들였으면 채택은 하되 눈에 띄게 알린다
    tot = sum(mm_w.values())
    if tot > 0:
        after = {}
        for n in names:
            after[_final2(pmap, n)] = after.get(_final2(pmap, n), 0.0) + mm_w.get(n, 0.0)
        big = [k for k, v in after.items() if v > 0.6 * tot]
        if big and len(after) > 1:
            _say(f"    [!] 병합 뒤 '{big[0]}' 하나가 전체 MM 의 60% 를 넘습니다 — 과병합이 아닌지 확인하세요", log)
    # 애매한 쌍(점수가 문턱 사이) — 합치지 않고 사람에게 보여 준다. 문헌의 3분할과 같은 취지:
    # 자동으로 처리할 수 있는 구간만 자동으로 하고, 경계는 사람이 한 번 정하면 캐시가 기억한다.
    return pmap, n_rule, n_ev, {"pairs": pairs, "rejects": rejects, "ask": ask[:20]}


# ── 적용 ──────────────────────────────────────────────────────────────────
def apply_project_map(rows, sigs, pmap):
    """mm_rows 행의 Level 2 와 신호의 model|project 를 대표 이름으로 — 원본 파일은 무수정.

    **반드시 apply_detail_map 보다 먼저** 부른다. 세부업무 맵의 키가 (과제, 이름) 이라
    과제 이름이 먼저 대표가 돼야 맞고, _detail_pools 의 파티션 키도 raw Level 2 라서
    과제가 갈린 채로 두면 세부 병합까지 반쪽이 된다(감사 실측)."""
    if not pmap:
        return rows, sigs
    for r in (rows or []):
        pj = (r.get("Level 2") or "").strip()
        nv = pmap.get(pj)
        if nv and nv != pj:
            r["Level 2"] = nv
    for s2 in (sigs or []):
        for k in ("model", "project"):
            if s2.get(k) is None:
                continue
            v = str(s2.get(k) or "").strip()
            nv = pmap.get(v)
            if nv and nv != v:
                s2[k] = nv
    return rows, sigs


def remap_detail_scope(amap, pmap):
    """세부업무 맵의 '과제' 스코프를 과제 병합 대표로 접는다.
    과제를 합치면 (옛 과제, 이름) 키가 고아가 되어 이미 지불한 세부 병합이 조용히 사라진다."""
    if not amap or not pmap:
        return amap
    return {(pmap.get(pj, pj), d): v for (pj, d), v in amap.items()}


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
        # ukey3 로 먼저 묶고, 그 대표들끼리 구조 규칙(_same_detail3)으로 한 겹 더 묶는다.
        by_k = {}
        for d in ds:
            by_k.setdefault(ukey3(d), []).append(d)
        heads = sorted(by_k.values(), key=lambda v: (-mm_w.get((pj, v[0]), 0.0), v[0]))
        merged_into = {}
        for i, vi in enumerate(heads):
            hi = vi[0]
            if hi in merged_into:
                continue
            for vj in heads[i + 1:]:
                hj = vj[0]
                if hj in merged_into or not _same_detail3(hi, hj):
                    continue
                merged_into[hj] = hi
                by_k[ukey3(hi)] = by_k.get(ukey3(hi), []) + vj
                by_k[ukey3(hj)] = []
        for v in list(by_k.values()):
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
