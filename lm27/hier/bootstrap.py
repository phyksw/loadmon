# -*- coding: utf-8 -*-
r"""레지스트리가 빈 초기 — 코드네임 후보 검토 · 코파일럿 단계 열림 판정 · taxonomy 부트스트랩 결과 처리(H §8 · §3.5).

- `codename_candidates(feats, groups, reg, cfg)` — 코파일럿을 열기 전에 **내 PC 에서만** 코드네임 후보를 보여 준다(H §8.1).
  재료는 정제문(메일·회의 제목, 첨부·파일 이름, 창 제목, 그룹 대화방 이름)뿐이다. 상용구·어휘·영역 키워드·범용 줄기·업무
  일반어(`common_words.txt`)·프로그램 이름·이미 등록된 이름·무시한 후보(`codename_review.ignored` = ukey sha1 앞 8자)를 빼고,
  군집 ≥ `hier.bootstrap.codenameMinGroups` · 주 ≥ `codenameMinWeeks` 인 낱말을 점수(코드 모양 2.0 · 파일 이름 접두 1.0 ·
  꺾쇠 1.0 · 0.5×log2(군집 수) · 4주 이상 0.5) 순으로 `codenameTopN` 개.
  **과제 이름이 될 수 없는 것**(W2 검토 C06·C15 · 개발 PC 실측 N2)도 후보 재료에서 먼저 뺀다: 정제 토큰(`[사람#…]`·`[고객사:…]`
  ·`[과제:…]` 등 계약 §4.6 — 그 안의 조각 'a1b'·'C01' 이 이름이 되지 않게) · 판·차수·기간 표기(v2·rev3·w2·q3·2026·20260930·
  1차) · 낱말 + 연도·날짜 꼬리(signals_2026) · 기술 표기(utf8·x64·sha256) · 파일 확장자 조각(py·json·xlsx) · 두 글자 이하
  영문 · 앱 범주 이름(CAD·해석 …) · 프로그래밍 동사·범용 낱말(`common_words.txt` 의 개발 절 — get·load·judge·refine …) ·
  **프로그램·자료 파일 이름 안에서만 나온 조각**(get_signals.py 의 signals — 다른 출처에 한 번도 안 나온 것).
  창 제목은 ' - ' 마디로 읽는다: 앱 이름 마디는 버리고, 확장자가 있는 마디는 파일 이름, 개발 도구(카탈로그 범주 SW) 창의
  나머지 마디는 **작업 폴더(저장소·프로젝트 폴더) 이름** — 마디 통째가 후보 하나다(`Cand.folder`). 표기는 가장 많이 나온
  꼴(동률은 사전순 — 해시 씨앗과 무관하게 결정적).
- `copilot_allowed(reg, cfg)` — `hier.copilot.requireCodenameReview` 이면 레지스트리에 비예약 과제가 하나도 없고 검토를 마치거나
  건너뛰지 않은 동안 코파일럿 분류를 열지 않는다(H §3.5 · T-H05 — 분석은 막지 않고 안내 한 줄).
- `needs_bootstrap(reg, labels, last_run, cfg)` — 1회차 자동 조건(H §8.2): 비예약 active 과제 0 · 명명 군집 ≥ `minGroups` ·
  검토 완료/건너뜀, 또는 최근 30일 투입 중 미분류·예약·제안 비중 ≥ `unclassifiedShare` 이고 지난 부트스트랩 뒤 ≥ `cooldownDays`.
- `apply_bootstrap(rows, ...)` — 1회차 답 처리(H §8.4): 행 수가 `hier.bootstrap.maxModels` 를 넘으면 넘는 행은 버리고
  `caps_hit`(§8.2) · code 있음 → 보고에만 · code='' project → 제안 · common → 제안(영역 COM·EXT 밖이면 COM) · nonwork →
  표식만(시간·라벨 불변). `consolidate_pairs` — 2회차 답 h·m 쌍만 AI 통합 근거(+1.0)로(제안 큐 `consolidate` 가 S2 점수로 본다).
  부트스트랩은 과제를 만들지 않는다 — 제안 큐로만 간다(H-I6). 코드네임 검토의 버튼 기록은 `proposals.from_codename`·
  `mark_codename_review`(개인 로컬 레지스트리 쓰기는 그 모듈 하나).

표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from lm27.hier import match as _match
from lm27.hier import vocab as _vocab
from lm27.hier.features import default_cfg, get
from lm27.hier.learn import excluded_tokens
from lm27.hier.names import ukey
from lm27.hier.proposals import codename_hash
from lm27.time.calendar import d_of

__all__ = [
    "CODE_RX", "Cand", "apply_bootstrap", "codename_candidates", "consolidate_pairs", "copilot_allowed",
    "domain_vote", "is_code_like", "name_parts", "needs_bootstrap", "review_state", "rule_auto_projects",
    "strip_san_tokens",
]

CODE_RX = re.compile(r"[A-Za-z]{1,8}[-_]?\d{1,4}[A-Za-z]?|[A-Z][A-Z0-9]{1,7}[-_][A-Z0-9]{1,4}|[A-Z][A-Z0-9]{2,}")
_CODE_FULL = re.compile(r"(?:[A-Za-z]{1,8}[-_]?\d{1,4}[A-Za-z]?|[A-Z][A-Z0-9]{1,7}[-_][A-Z0-9]{1,4}|[A-Z][A-Z0-9]{2,})")
WINDOW_DAYS = 30
# 후보 재료가 되는 분류 특징 종류(features.Feature.kind — 증거 kind(계약 §3.1) 표가 아니다: file·win·git·summary 포함)
CAND_FEATURE_SOURCES = ("mail", "cal", "teams", "file", "win", "git", "manual", "summary")

# ── 과제 이름이 될 수 없는 낱말(C06 · N2) ──
# 표기(소문자) 기준: 판 표기 v2·ver3·rev1·r2 · 한 글자 + 숫자(차수·단계 w2·q3·p1) · 기술 표기(utf8·x64·sha256·mp4)
_JUNK_SURF = re.compile(r"^(?:(?:v|ver|rev|r)[._]?\d{1,3}[a-z]?|[a-z]\d{1,2}"
                        r"|(?:utf|cp|x|win|amd|arm|sha|md|base|py|ipv|h|mp|tls|ssl|http|iso)[-_]?\d{1,4})$")
# ukey 기준: 연도·연월·날짜(2026·202609·20260930) · 숫자 + 짧은 꼬리(1차·2nd·3d) · 분기·반기·회계연도 · 낱말 + 연도·날짜 꼬리
_JUNK_KEY = re.compile(r"^(?:(?:19|20)\d{2}(?:[01]\d(?:[0-3]\d)?)?|\d{6,8}|\d+[a-z가-힣]{0,2}|[qh][1-4]|(?:fy|cy)\d{2,4}"
                       r"|[a-z가-힣]+(?:19|20)\d{2}(?:[01]\d(?:[0-3]\d)?)?)$")
_SHORT_ASCII = re.compile(r"[a-z]{1,2}")
# 파일 확장자(조각이 이름이 되지 않게) · 그중 프로그램·자료 파일(이름 조각은 모듈·함수 이름이지 과제가 아니다 — N2)
CODE_EXTS = frozenset((
    "py pyw pyi ipynb js mjs cjs ts tsx jsx json jsonl ndjson yaml yml toml ini cfg conf env xml html htm css scss less "
    "sql bat cmd ps1 psm1 sh bash h hpp c cc cpp cs java kt go rs rb php swift vb vbs lua pl m v vhd lock map md rst "
    "log").split())
FILE_EXTS = CODE_EXTS | frozenset((
    "txt csv tsv db sqlite exe dll so lib obj gz zip 7z rar tar tgz bak tmp svg png jpg jpeg gif bmp ico webp mp3 mp4 "
    "wav avi mov pdf doc docx xls xlsx xlsm ppt pptx hwp hwpx dwg dxf step stp igs iges stl msg eml").split())
_APP_WORDS = frozenset({"microsoft", "insiders", "preview", "community", "professional", "enterprise"})
_SEG_RX = re.compile(r"\s+[-–—]\s+")                         # 창 제목 마디 구분(' - ' · ' – ' · ' — ')
_BRACKET_RX = re.compile(r"\[[^\[\]]{0,40}\]|\([^()]{0,40}\)")   # '[SSH: …]' · '(Workspace)' 꾸밈
_DECOR = " \t●○•*✳⦿\\/"
_NAME_EXT_RX = re.compile(r"\.([0-9A-Za-z]{1,6})$")


@dataclass(frozen=True)
class Cand:
    token: str                       # 표기(가장 많이 나온 꼴 — 동률은 사전순)
    score: float
    n_groups: int
    n_weeks: int
    examples: tuple[str, ...] = ()   # 정제문 예시(로컬 화면 전용)
    hash8: str = ""                  # sha1(ukey)[:8] — [무시] 기록용
    folder: bool = False             # 개발 도구 창 제목의 작업 폴더(저장소·프로젝트 폴더) 마디로 나왔다
    kinds: tuple[str, ...] = ()      # 나온 출처(특징 종류) — 여러 출처일수록 과제 이름답다

    def auto_score(self) -> float:
        """규칙 제안 과제(V15) 순위 점수 = H §8.1 점수 + 작업 폴더 1.5 + 출처 하나 더할 때마다 0.5(최대 1.0)."""
        return self.score + 1.5 * self.folder + 0.5 * (min(len(self.kinds), 3) - 1 if self.kinds else 0)


def is_code_like(t: str) -> bool:
    return bool(_CODE_FULL.fullmatch(str(t or "")))


def _hash8(t: str) -> str:
    return codename_hash(t)


@lru_cache(maxsize=1)
def _app_names() -> frozenset[str]:
    from lm27 import catalog                        # 지연 import — 프로그램 카탈로그 표시 이름(APP_NAMES)
    out = set()
    for p in catalog.entries():
        out.add(ukey(p.name))
        out.update(ukey(w) for w in re.split(r"[\s/·]+", p.name) if len(w) >= 2)
    out.update(ukey(c) for c in catalog.CATEGORIES)  # 앱 범주 이름(CAD·해석 …)도 과제 이름이 아니다(C06 — ' - CAD' 꼬리)
    return frozenset(x for x in out if x)


@lru_cache(maxsize=1)
def _san_token_rx() -> re.Pattern:
    """정제 토큰 문법(계약 §4.6 — 단일원은 정제 규칙 `lm27.privacy.rules.TOKEN_RX`)."""
    from lm27.privacy.rules import TOKEN_RX          # 지연 import — 정제 패키지는 분류 패키지를 import 하지 않는다(X-304)
    return TOKEN_RX


def strip_san_tokens(text) -> str:
    """정제문에서 정제 토큰을 지운다(C15 — '[사람#a1b2c3]' 의 'a1b'·'[고객사:C01]' 의 'C01' 이 이름이 되지 않게).
    사용자가 직접 쓴 꺾쇠('[QX-12]')는 남긴다."""
    return _san_token_rx().sub(" ", unicodedata.normalize("NFKC", str(text or "")))


def _name_ext(name: str) -> str:
    m = _NAME_EXT_RX.search(name.strip())
    e = m.group(1).lower() if m else ""
    return e if e in FILE_EXTS else ""


def _is_app_seg(seg: str, apps: frozenset[str]) -> bool:
    ws = [ukey(w) for w in re.split(r"[\s/·]+", seg) if w]
    return ukey(seg) in apps or (bool(ws) and all(w in apps or w in _APP_WORDS for w in ws))


def _seg_clean(seg: str) -> str:
    return " ".join(_BRACKET_RX.sub(" ", seg).strip(_DECOR).split())


def _tokens(s: str) -> set[str]:
    return set(CODE_RX.findall(s)) | _match.match_tokens(s)


def name_parts(f, apps: frozenset[str] | None = None) -> tuple[tuple[str, str, bool], ...]:
    """특징 하나 → 후보 재료 [(표기, 역할, 파일 이름 접두)]. 역할: folder(개발 도구 창 제목의 작업 폴더 마디 — 통째) ·
    doc(문서 파일 이름 조각) · code(프로그램·자료 파일 이름 조각) · text(제목·본문·커밋 메시지 등 사람이 쓴 글).
    정제 토큰은 먼저 지운다(C15)."""
    apps = _app_names() if apps is None else apps
    raw = strip_san_tokens(getattr(f, "text", "") or "")
    if not raw.strip():
        return ()
    out: list[tuple[str, str, bool]] = []

    def add_name(nm: str, ext: str = "") -> None:
        nm = strip_san_tokens(nm).strip(_DECOR)
        if not nm:
            return
        role = "code" if (ext or _name_ext(nm)) in CODE_EXTS else "doc"
        kn = ukey(nm)
        for t in sorted(_tokens(nm)):
            out.append((t, role, kn.startswith(ukey(t))))

    kind = getattr(f, "kind", "")
    names = [nm for _fk, nm in (getattr(f, "names", ()) or ()) if nm]
    if kind == "file":
        ext = next(iter(sorted(e.lstrip(".").lower() for e in (getattr(f, "exts", ()) or ()) if e)), "")
        for nm in names or [raw]:
            add_name(nm, ext if ext in FILE_EXTS else "")
        return tuple(out)
    if kind == "win":
        sw = getattr(f, "app_cat", "") == "SW"
        segs = [_seg_clean(s) for s in _SEG_RX.split(raw)]
        segs = [s for s in segs if s and not _is_app_seg(s, apps)]
        plain = [s for s in segs if not _name_ext(s)]
        for s in segs:
            if _name_ext(s):
                add_name(s)
        lead = segs[0] if (len(plain) >= 2 and segs and segs[0] == plain[0]) else None   # 'Welcome - 폴더 - 앱' 의 탭 이름
        for s in plain:
            if sw and s is not lead and 2 <= len(s) <= 40 and not s.replace(" ", "").isdigit():
                out.append((s, "folder", False))
            else:
                out.extend((t, "text", False) for t in sorted(_tokens(s)))
        return tuple(out)
    rest = raw
    for nm in names:
        add_name(nm)
        rest = rest.replace(strip_san_tokens(nm), " ")
    out.extend((t, "text", False) for t in sorted(_tokens(rest)))
    return tuple(out)


def _junk(t: str, k: str) -> bool:
    """과제 이름이 될 수 없는 낱말(C06 · N2): 판·차수·기간·연도·날짜 꼬리·기술 표기·확장자·짧은 영문·토큰 조각."""
    low = t.lower()
    return (len(k) < 2 or k.isdigit() or bool(_JUNK_SURF.match(low)) or bool(_JUNK_KEY.match(k))
            or bool(_SHORT_ASCII.fullmatch(k)) or k in FILE_EXTS or "#" in t or "@" in t)


def _candidates(feats: Iterable, reg, cfg, feat_groups: Mapping | None, parts: dict | None) -> tuple[list, dict]:
    """후보 전부(H §8.1 점수 순 — 상한 없음)와 낱말별 통계. parts = 특징 id → name_parts 메모(호출자와 나눠 쓴다)."""
    min_g = int(cfg["hier.bootstrap.codenameMinGroups"])
    min_w = int(cfg["hier.bootstrap.codenameMinWeeks"])
    review = reg.codename_review or {}
    ignored = {str(x) for x in (review.get("ignored") or ())}
    excl = set(excluded_tokens(reg, cfg))
    for kind in ("fields",):
        for it in reg.vocab.get(kind, {}).values():
            excl.update(str(x).lower() for x in it.keywords)
    common = _match.common_words()
    apps = _app_names()
    fg = feat_groups or {}
    memo = parts if parts is not None else {}
    kmemo: dict[str, str] = {}
    stats: dict[str, dict] = {}
    feats = list(feats)
    exts = {e.lstrip(".").lower() for f in feats for e in f.exts if e}           # 파일 확장자 조각은 과제 이름이 아니다
    for f in feats:
        if f.kind not in CAND_FEATURE_SOURCES:
            continue
        ps = memo.get(f.id)
        if ps is None:
            ps = memo[f.id] = name_parts(f, apps)
        if not ps:
            continue
        week = ""
        if f.t:
            y, w, _ = d_of(f.t).isocalendar()
            week = f"{y}-{w:02d}"
        gs = fg.get(f.id, f.id)
        gs = (gs,) if isinstance(gs, str) else tuple(gs)
        low = strip_san_tokens(f.text).lower() if "[" in (f.text or "") else ""      # 사용자 꺾쇠('[QX-12]') 점수용
        per: dict[str, list] = {}
        for t, role, pre in ps:
            k = kmemo.get(t)
            if k is None:
                k = kmemo[t] = ukey(t)
            e = per.setdefault(k, [set(), False, []])
            e[0].add(role)
            e[1] = e[1] or (pre and role == "doc")          # 접두 점수는 문서 이름에서만(프로그램 파일의 'get_…' 은 아님)
            e[2].append(t)
        for k, (roles, pre, forms) in per.items():
            s = stats.setdefault(k, {"forms": defaultdict(int), "groups": set(), "weeks": set(), "n": 0, "prefix": 0,
                                     "br": False, "ex": [], "roles": set(), "kinds": set()})
            s["groups"].update(gs)
            if week:
                s["weeks"].add(week)
            s["n"] += 1
            s["prefix"] += int(pre)
            s["roles"] |= roles
            s["kinds"].add(f.kind)
            for t in forms:
                s["forms"][t] += 1
                if low and not s["br"] and "[" + t.lower() + "]" in low:
                    s["br"] = True
            subj = f.subject or f.text
            if len(s["ex"]) < 3 and subj not in s["ex"]:
                s["ex"].append(subj[:80])
    out = []
    for k in sorted(stats):
        s = stats[k]
        t = min(s["forms"].items(), key=lambda kv: (-kv[1], kv[0]))[0]    # 가장 많이 나온 꼴(동률 사전순)
        s["tok"] = t
        if _junk(t, k) or s["roles"] <= {"code"}:                       # 프로그램·자료 파일 이름 조각뿐(N2)
            continue
        if t.lower() in excl or k in excl or t.lower() in common or k in common or k in apps or k in exts:
            continue
        if k in reg.alias_ix or _hash8(t) in ignored:
            continue
        ng, nw = len(s["groups"]), len(s["weeks"])
        if ng < min_g or nw < min_w:
            continue
        sc = 2.0 * is_code_like(t) + 1.0 * (s["prefix"] / max(s["n"], 1) >= 0.5) + 1.0 * s["br"] \
            + 0.5 * math.log2(ng) + 0.5 * (nw >= 4)
        out.append(Cand(t, round(sc, 3), ng, nw, tuple(s["ex"]), _hash8(t), "folder" in s["roles"],
                        tuple(sorted(s["kinds"]))))
    out = _drop_covered(out, stats)
    return sorted(out, key=lambda c: (-c.score, c.token)), stats


def codename_candidates(feats: Iterable, groups: Iterable, reg, cfg=None, *,
                        feat_groups: Mapping | None = None, parts: dict | None = None) -> list[Cand]:
    """코드네임 후보(H §8.1). feat_groups = 특징 id → 군집 키(또는 군집 키 묶음 — 없으면 특징의 단위업무를 모른다: 특징 id 를
    군집으로 센다). parts = 특징 id → `name_parts` 메모(선택)."""
    cfg = default_cfg(cfg)
    out, _stats = _candidates(feats, reg, cfg, feat_groups, parts)
    return out[:int(cfg["hier.bootstrap.codenameTopN"])]


RULE_AUTO_MAX = 8                 # 규칙 제안 과제 상한(LM24 규칙 대체 — 자주 나온 규칙 과제 8개)
RULE_AUTO_MIN_GROUPS = 2          # 그 이름이 든 미분류 단위업무가 이만큼은 돼야 과제로 세운다(LM24 — 근거 2개 이상)


def _feat_units(gl: list, units: Mapping, feats: list) -> dict[str, set]:
    """원 특징 id → 그 특징이 든 단위업무 id 들(군집 구성원). 단위업무 증거 모음의 합집합 특징('fam:<문서군>'·
    'app:<업무>:<앱>')은 원 특징으로 풀어 센다 — 문서군은 같은 문서군 키를 가진 특징, 앱은 그 업무 구간에 겹친 같은 앱 창 특징."""
    from bisect import bisect_left
    ids = {f.id for f in feats}
    by_fam: dict[str, list] = defaultdict(list)
    by_app: dict[str, list] = defaultdict(list)
    for f in feats:
        for fk in f.fams:
            by_fam[fk].append(f)
        if f.kind == "win" and f.app:
            by_app[f.app].append(f)
    app_t = {a: [x.t for x in fs] for a, fs in by_app.items()}       # feats 는 (t, id) 순
    out: dict[str, set] = defaultdict(set)
    for g in gl:
        for m in g.members:
            u = units.get(m)
            if u is None:
                continue
            for f, _w, _r in get(u, "ev", ()) or ():
                fid = f.id
                if fid in ids:
                    out[fid].add(m)
                elif fid.startswith("fam:"):
                    for x in by_fam.get(fid[4:], ()):
                        out[x.id].add(m)
                elif fid.startswith("app:") and f.app in by_app:
                    s = int(get(u, "start", 0) or 0)
                    e = int(get(u, "end", 0) or 0) or s + 86400
                    if not s:
                        continue
                    lst, ts = by_app[f.app], app_t[f.app]
                    for x in lst[bisect_left(ts, s - 3600):bisect_left(ts, e)]:
                        if x.t < e and (x.t_end or x.t + 60) > s:
                            out[x.id].add(m)
    return out


def rule_auto_projects(labels: Mapping, groups: Iterable, units: Mapping, feats: Iterable, reg, cfg, props, *,
                       ai: Mapping | None = None, at: str = "", label_check=None) -> dict:
    """AI 답이 없고 과제를 못 정한(UNC) 군집에 '자주 나온 이름'(코드네임 후보 점수 — H §8.1)으로 **규칙 제안 과제**를 붙인다
    (계약 v1.3 §0.8 V15 — LM24 의 규칙 대체 '지정 과제 + 자주 나온 규칙 과제'와 같은 자리). 팀·개인 과제가 하나도 없을 때만
    (`hier.ruleAutoProjects`, 기본 켜짐). 제안은 사람이 받기 전까지 과제가 아니다(H-I6) — MM 은 제안 과제로 계상(H §7.1).
    AI 답이 있는 군집(NONE 포함)·사람이 고친 단위업무는 건드리지 않는다. labels 를 제자리에서 고치고 통계를 돌려준다.

    이름 고르기(W2 검토 C06 · N2): 군집마다 **그 군집 증거에서 가장 많이 나온 후보 이름**(동률은 `Cand.auto_score` = H §8.1
    점수 + 작업 폴더 + 여러 출처 순위)이 그 군집의 이름이다 — 군집이 한 번 스친 범용 이름('v2'·여러 과제에 두루 붙는 문서
    종류)이 구체적인 과제 코드를 이기지 않게. 그 이름이 미분류 단위업무 2개 이상의 이름인 것 중 순위 상위 8개만 세운다
    (근거 수는 단위업무로 센다 — 한 군집에 여러 주의 단위업무가 묶인 작업 폴더도 서게). 후보 통계의 '군집 수'(H §8.1
    `codenameMinGroups`)도 그 이름이 든 단위업무 수다. 의미 있는 이름이 없으면 군집은 '과제 없음'(UNC) 그대로 둔다 — 쓰레기
    이름으로 채우지 않는다. 영역은 그 이름이 붙은 군집 증거의 영역 키워드 다수결(`domain_vote`, 없으면 DEV — H §8.1).
    label_check = 팀 라벨 검사(제안 큐가 통과 못 한 이름을 대체 이름으로 바꾼다)."""
    from lm27.hier.apply import level_of, role_slot
    from lm27.hier.unitlabel import role_id
    cfg = default_cfg(cfg)
    st: Counter = Counter()
    if not bool(cfg["hier.ruleAutoProjects"]) or _non_reserved(reg):
        return {}
    ai = ai or {}
    gl = list(groups)
    todo = []
    for g in gl:
        rep = labels.get(g.rep)
        hit = ai.get(g.key)
        if rep is None or rep.project or rep.proposal_id or (isinstance(hit, Mapping) and hit.get("by") in ("ai", "manual")):
            continue
        if any(getattr(labels.get(m), "src", {}).get("project") == "user" for m in g.members):
            continue
        todo.append(g)
    if not todo:
        return {}
    feats = sorted(feats, key=lambda f: (f.t, f.id))
    fu = _feat_units(gl, units, feats)
    parts: dict = {}
    cands, _stats = _candidates(feats, reg, cfg, fu, parts)
    st["todo"], st["names"] = len(todo), len(cands)
    order = sorted(cands, key=lambda c: (-c.auto_score(), -c.n_groups, c.token))
    rank = {ukey(c.token): i for i, c in enumerate(order)}
    unit_cnt: dict[str, Counter] = defaultdict(Counter)
    for f in feats:
        us = fu.get(f.id)
        if not us:
            continue
        ks = {ukey(t) for t, _r, _p in parts.get(f.id) or ()} & rank.keys()
        if ks:
            for uid in us:
                unit_cnt[uid].update(ks)
    # 군집마다 그 군집 증거에서 가장 많이 나온 이름(동률은 순위) — 군집이 한 번 스친 이름이 아니라 그 군집의 이름(C06)
    dom_name: dict[str, str] = {}
    support: Counter = Counter()
    for g in todo:
        c: Counter = Counter()
        for m in g.members:
            c.update(unit_cnt.get(m, {}))
        if c:
            k = min(c, key=lambda x: (-c[x], rank[x]))
            dom_name[g.key] = k
            support[k] += len(g.members)
    # LM24 의 규칙 대체처럼 '자주 나온 이름 상위 8개, 각각 근거(단위업무) 2개 이상'만 과제로 세운다 — 잘게 흩어지지 않게
    chosen: set[str] = set()
    for c in order:
        if len(chosen) >= RULE_AUTO_MAX:
            break
        k = ukey(c.token)
        if support.get(k, 0) >= RULE_AUTO_MIN_GROUPS:
            chosen.add(k)
    pick = {gk: k for gk, k in dom_name.items() if k in chosen}
    if len(todo) > len(pick):
        st["no_name"] = len(todo) - len(pick)              # 의미 있는 이름이 없는 군집 — '과제 없음'(UNC) 그대로
    doms: dict[str, str] = {}
    name_eff: Counter = Counter()                                  # 제안 최소 투입(hier.proposals.minEffortMin)은 이름 전체로 본다 —
    for g in todo:                                                 # 작은 군집도 이미 선 이름이면 그 제안으로 간다
        if g.key in pick:
            name_eff[pick[g.key]] += int(g.effort_min)
    for k in sorted(set(pick.values())):
        fs = [f for g in todo if pick.get(g.key) == k for m in g.members
              for f, _w, _r in (get(units.get(m), "ev", ()) or ())]
        d = domain_vote(fs, reg)
        doms[k] = d if d in _vocab.DOMAINS else "DEV"
    for g in todo:
        k = pick.get(g.key)
        if k is None:
            continue
        asg = props.on_new_name(order[rank[k]].token, doms[k], g.key, "bootstrap", reg, cfg=cfg,
                                effort_min=name_eff[k], conf="l", at=at, label_check=label_check)
        pid = getattr(asg, "proposal", None)
        if not pid:
            st["skip_" + (str(getattr(asg, "src", "") or "none"))] += 1
            continue
        for m in g.members:
            lb = labels.get(m)
            if lb is None or lb.src.get("project") == "user":
                continue
            lb.project, lb.proposal_id = None, pid
            lb.domain = props.dom_of(pid)
            for fl in ("proposal", "rule_auto"):
                if fl not in lb.flags:
                    lb.flags.append(fl)
            lb.src["project"], lb.conf["project"] = "rule", "l"
            lb.level = level_of("rule", "l", None, pid, None)
            lb.role_id = role_id(role_slot(None, pid, reg), lb.field, lb.func)
        st["assigned"] += 1
    return dict(sorted(st.items()))


def _drop_covered(cands: list[Cand], stats: Mapping[str, Mapping]) -> list[Cand]:
    """코드 모양 후보(예 PROJ-X)의 조각(proj)이 같은 군집에서만 나오면 조각은 뺀다 — 같은 이름을 두 번 묻지 않는다."""
    code = [(ukey(c.token), stats[ukey(c.token)]["groups"]) for c in cands if is_code_like(c.token)]
    keep = []
    for c in cands:
        k = ukey(c.token)
        if any(k != ck and k in ck and stats[k]["groups"] <= cg for ck, cg in code):
            continue
        keep.append(c)
    return keep


def _non_reserved(reg) -> list[str]:
    return [pid for pid, p in reg.projects.items() if p.origin != "reserved"]


def review_state(reg) -> str:
    """초기 코드네임 검토 상태: not_needed(비예약 과제 있음) · done · skipped · pending."""
    if _non_reserved(reg):
        return "not_needed"
    r = reg.codename_review or {}
    if r.get("skipped"):
        return "skipped"
    if r.get("done_at"):
        return "done"
    return "pending"


def copilot_allowed(reg, cfg=None) -> tuple[bool, str]:
    """코파일럿 분류 단계를 열어도 되는가(H §3.5·§8.1). (가능, 안내 문구 — 막히면 한 줄)."""
    cfg = default_cfg(cfg)
    if not bool(cfg["hier.copilot.requireCodenameReview"]):
        return True, ""
    st = review_state(reg)
    if st == "pending":
        return False, "과제 이름 후보를 확인하면 코파일럿 분류를 켭니다"
    if st == "skipped":
        return True, "레지스트리 없이 코파일럿을 쓰면 제목 속 과제 이름이 그대로 갈 수 있습니다"
    return True, ""


def needs_bootstrap(reg, labels: Mapping, last_run: str | date | None, cfg=None, *, groups: Iterable = (),
                    user_request: bool = False, as_of: date | None = None) -> bool:
    """taxonomy_bootstrap 1회차를 돌릴까(H §8.2). last_run = 지난 부트스트랩 날짜(없으면 None)."""
    cfg = default_cfg(cfg)
    if user_request:
        return True
    min_groups = int(cfg["hier.bootstrap.minGroups"])
    share_min = float(cfg["hier.bootstrap.unclassifiedShare"])
    cooldown = int(cfg["hier.bootstrap.cooldownDays"])
    gl = list(groups)
    if not reg.active_ids() and len(gl) >= min_groups and review_state(reg) in ("done", "skipped"):
        return True
    today = as_of
    if today is None:
        return False
    if last_run:
        lr = last_run if isinstance(last_run, date) else date.fromisoformat(str(last_run)[:10])
        if (today - lr).days < cooldown:
            return False
    lo = today - timedelta(days=WINDOW_DAYS)
    tot = weak = 0
    for g in gl:
        t = int(get(g, "last_t", 0) or 0)
        if not t or d_of(t) < lo:
            continue
        lab = labels.get(g.rep)
        eff = int(g.effort_min)
        tot += eff
        proj = get(lab, "project", None)
        if proj is None or str(proj).startswith("P-99"):          # 미분류·제안 과제(과제 자리 없음)·예약 과제
            weak += eff
    return bool(tot) and weak / tot >= share_min


def apply_bootstrap(rows: Iterable[Mapping], samples: list[Mapping], proposals, reg, cfg=None, *,
                    efforts: Mapping[str, int] | None = None, at: str = "", label_check=None) -> dict:
    """1회차 답 처리(H §8.4). rows = 답 행 {name, code, dom, kind, match, obs}, samples = 보낸 표본(번호 = 위치 + 1).
    행 수가 `hier.bootstrap.maxModels` 를 넘으면 넘는 행은 버린다(§8.2 — `caps_hit`).
    반환 {report: [(행 id, 코드, 표본 번호)], proposals: [(행 id, Assign)], nonwork: [군집 키], caps_hit: 버린 행 수}."""
    cfg = default_cfg(cfg)
    cap = int(cfg["hier.bootstrap.maxModels"])
    rows = list(rows)
    out = {"report": [], "proposals": [], "nonwork": [], "caps_hit": max(0, len(rows) - cap)}
    seen = set()
    for i, r in enumerate(rows[:cap], start=1):
        obs = [int(x) for x in (r.get("obs") or ()) if isinstance(x, int) and 1 <= x <= len(samples)]
        keys = [str(samples[x - 1].get("key")) for x in obs]
        code = str(r.get("code") or "")
        kind = r.get("kind")
        if code:
            out["report"].append((i, code, obs))
            continue
        if kind == "nonwork":
            out["nonwork"].extend(keys)
            continue
        name = str(r.get("name") or "")
        k = ukey(name)
        if kind not in ("project", "common") or len(k) < 2 or k in seen:
            continue
        seen.add(k)
        dom = str(r.get("dom") or "")
        if kind == "common" and dom not in ("COM", "EXT"):
            dom = "COM"
        if dom not in _vocab.DOMAINS:
            continue
        eff = sum(int((efforts or {}).get(key, 0)) for key in keys)
        first = keys[0] if keys else ""
        asg = proposals.on_new_name(name, dom, first, "bootstrap", reg, cfg=cfg, effort_min=eff, conf="m", at=at,
                                    label_check=label_check)
        p = proposals.get(asg.proposal) if asg.proposal else None
        if p is not None:
            for key in keys[1:]:
                if key not in p["groups"]:
                    p["groups"] = sorted(set(p["groups"]) | {key})
            mw = [str(w)[:20] for w in (r.get("match") or ())][:5]
            p["match_words"] = sorted(set(p.get("match_words") or ()) | set(mw))
        out["proposals"].append((i, asg))
    out["nonwork"] = sorted(set(out["nonwork"]))
    return out


def consolidate_pairs(answers: Iterable[Mapping], items: list[Mapping]) -> frozenset:
    """2회차 답 → AI 통합 제안 쌍(ukey frozenset) — conf h·m 인 (id, same_as) 만(H §8.3). 자기 자신·범위 밖은 버린다."""
    pairs = set()
    for a in answers:
        try:
            i = int(a.get("id"))
            j = int(a.get("same_as"))
        except (TypeError, ValueError):
            continue
        if a.get("conf") not in ("h", "m") or j == 0 or i == j or not (1 <= i <= len(items)) or \
                not (1 <= j <= len(items)):
            continue
        na = str((items[i - 1].get("rule") or {}).get("name") or (items[i - 1].get("fields") or {}).get("name") or "")
        nb = str((items[j - 1].get("rule") or {}).get("name") or (items[j - 1].get("fields") or {}).get("name") or "")
        if ukey(na) and ukey(nb) and ukey(na) != ukey(nb):
            pairs.add(frozenset((ukey(na), ukey(nb))))
    return frozenset(pairs)


def domain_vote(feats: Iterable, reg) -> str:
    """후보가 나온 증거의 영역 키워드 다수결(없으면 DEV) — [과제 이름] 으로 표시할 때의 기본 영역(H §8.1)."""
    from lm27.hier.rules import rule_ctx, score_domains
    c = rule_ctx(reg)
    votes: dict[str, float] = defaultdict(float)
    for f in feats:
        for d, v in score_domains(f, reg, ctx=c).items():
            votes[d] += v
    if not votes:
        return "DEV"
    return min(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
