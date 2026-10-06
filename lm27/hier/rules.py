# -*- coding: utf-8 -*-
r"""결정적 규칙 분류 — 과제 점수 R1~R13 · 영역 점수 · 증거 꼬리표(H §4.3~§4.5 · §2.3.5 · §11.4, 계약 §2.10 · §3.15).

- `score_projects(f, reg, cfg=None)` → `{과제 ID: 점수}`(−∞ = 그 증거에서 never). 규칙 R1 토큰 6.0 · R2 학습 키 5.0 ·
  R3 별칭 4.0 · R4 키워드 min(2n, 4) · R5 고객사·R5′ 협력사·R6 메일 도메인(공유 과제 수로 나눔) · R7 폴더·감시 루트 3.0 ·
  R8 앱 1.0 · R9 팀 규칙 w · R10 학습 토큰 2.5 · R11 never −∞ · R12 기간 밖 ×0.5 · R13 퇴역(병합 없음)은 후보 밖.
  모든 가점에 `f.weight_mult`(요약 증인 0.5)를 곱한다. 가중은 설정 `hier.rule.w.*`(H §13.1).
- `score_domains(f, reg, cfg=None)` → `{영역: 점수}`: 긴 키워드가 그 안의 짧은 키워드를 덮고, 남은 적중 영역이 둘 이상이면
  `hier.domain.order`(EXT > AX > COM > MP > DEV) 첫 영역 하나만, 점수 = 가점 × min(적중 수, 2). 상대 계급 '기관'(공공 계급)은
  EXT 적중 1건(가점 `hier.domain.w['기관']`). 키워드 'ai' 는 토큰이 아니라 정제문 정규식으로 본다. 팀 규칙 `then.domain` 가점을 더한다.
- `tag_evidence(feats, reg, cfg)` → `HierTags{msg: {msg_key: 과제}, fam: {문서군 키: 과제}, shared_fams}`(계약 §3.15 ·
  H X8 — 시간 코어는 이 세 값만 읽는다). 꼬리표 = 1위 ≥ `hier.rule.evidenceMin` 이고 1위 − 2위 ≥ `evidenceMargin`(보수적).
  문서군 꼬리표는 그 문서군의 파일·창·첨부 특징의 합집합 하나로 판정한다. 키는 시간 코어 `fam_key` 와 같다(W1a CR).
- 꼬리표·학습 규칙의 재료는 결정적 규칙뿐이다 — 이 모듈은 AI 답·제안 큐를 읽지 않는다(H-I6 · G-H7 · L-25).

`kw_hit` 판정은 `lm27.hier.match.kw_hit` 하나다. `KwIndex` 는 그 필요조건으로 후보만 좁힌 뒤 실물 kw_hit 으로 확정한다
(뜻은 같고 빠르다 — 증거 수만 건 × 과제 수백 개). 표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from lm27.hier import match as _match
from lm27.hier import vocab as _vocab
from lm27.hier.features import Feat, default_cfg, feat, month_of, union_feat
from lm27.hier.names import ukey

__all__ = [
    "NEG", "HierTags", "KwIndex", "RuleCtx", "SubIndex", "best_two", "family_feats", "rule_ctx", "score_domains",
    "score_projects", "tag_evidence", "tag_rows", "tags_from_rows",
]

NEG = float("-inf")
_FUZZY = 0.9                     # match.kw_hit 의 SequenceMatcher 문턱과 같다
KEY_CONDS = ("conv", "fam", "dir", "repo")          # 학습 키 규칙 조건(H §11.4)
PUBLIC_CLASS_KEY = "기관"                            # hier.domain.w 의 공공 계급 가점 키(H §13.1)
_PUBLIC_PSEUDO = "기관도메인"                         # 공공 계급 적중의 의사 키워드(덮기 판정에 걸리지 않는 낱말)


# ───────────────────────── 키워드 후보 색인 ─────────────────────────
class KwIndex:
    """키워드 → 값 색인. `hits(toks)` = `match.kw_hit(키워드, toks, mode)` 가 참인 (키워드, 값) 목록(키워드·값 순).

    후보 생성은 kw_hit 의 필요조건만 쓴다(조각 하나라도: 정확 일치 · 한글 조각 = 토큰 앞부분(head 는 짧은 접두 뒤 꼬리도) ·
    비한글 4자 이상 조각 = 토큰 앞·뒤 부분 · 비한글 5자 이상 조각 = 길이·quick_ratio 상한 ≥ 0.9). 확정은 실물 kw_hit 이다."""

    def __init__(self, items: Iterable[tuple[str, object]], mode: str):
        if mode not in ("name", "head"):
            raise ValueError("KwIndex: mode 는 'name' 또는 'head'")
        self.mode = mode
        self.items: list[tuple[str, object]] = []
        self.exact: dict[str, set[int]] = defaultdict(set)
        self.hangul: dict[str, set[int]] = defaultdict(set)
        self.ascii4: dict[str, set[int]] = defaultdict(set)
        self.fuzzy: list[tuple[str, int]] = []
        for kw, val in sorted(items, key=lambda x: (str(x[0]), repr(x[1]))):
            parts = _match.kw_parts(kw)
            if not parts:
                continue
            i = len(self.items)
            self.items.append((kw, val))
            for p in parts:
                self.exact[p].add(i)
                if _match.HANGUL_RX.search(p):
                    self.hangul[p].add(i)
                else:
                    if len(p) >= 4:
                        self.ascii4[p].add(i)
                    if len(p) >= 5:
                        self.fuzzy.append((p, i))
        self.max_h = max((len(p) for p in self.hangul), default=0)
        self.max_a = max((len(p) for p in self.ascii4), default=0)

    def __len__(self) -> int:
        return len(self.items)

    def candidates(self, toks: Iterable[str]) -> set[int]:
        cand: set[int] = set()
        tl = list(toks)
        for t in tl:
            c = self.exact.get(t)
            if c:
                cand |= c
            if self.hangul:
                for n in range(2, min(len(t), self.max_h) + 1):          # 한글 조각 = 토큰 앞부분(t.startswith(p))
                    c = self.hangul.get(t[:n])
                    if c:
                        cand |= c
                if self.mode == "head":                                   # 합성어 머리: t.endswith(p), 앞 ≤ 3자
                    for s in range(1, 4):
                        if len(t) - s >= 2:
                            c = self.hangul.get(t[s:])
                            if c:
                                cand |= c
            if self.ascii4:
                for n in range(4, min(len(t), self.max_a) + 1):          # 비한글 4자+ 조각 = 토큰 앞·뒤 부분
                    c = self.ascii4.get(t[:n])
                    if c:
                        cand |= c
                    c = self.ascii4.get(t[-n:])
                    if c:
                        cand |= c
        if self.fuzzy:
            longs = [t for t in tl if len(t) >= 4]
            for p, i in self.fuzzy:
                if i in cand:
                    continue
                for t in longs:
                    if 2.0 * min(len(p), len(t)) / (len(p) + len(t)) < _FUZZY:
                        continue
                    if SequenceMatcher(None, p, t).quick_ratio() >= _FUZZY:
                        cand.add(i)
                        break
        return cand

    def hits(self, toks) -> list[tuple[str, object]]:
        ts = toks if isinstance(toks, set | frozenset) else set(toks)
        return [self.items[i] for i in sorted(self.candidates(ts)) if _match.kw_hit(self.items[i][0], ts, self.mode)]


class SubIndex:
    """`ukey(정제문)` 의 부분 문자열 일치(별칭 R3 의 '3자 이상 부분 문자열') — 첫 두 글자로 후보를 좁힌다."""

    def __init__(self, items: Iterable[tuple[str, object]], min_len: int = 3):
        self.by2: dict[str, list[tuple[str, object]]] = defaultdict(list)
        for k, v in sorted(items, key=lambda x: (str(x[0]), repr(x[1]))):
            if isinstance(k, str) and len(k) >= min_len:
                self.by2[k[:2]].append((k, v))

    def hits(self, s: str) -> list[tuple[str, object]]:
        if not s or not self.by2:
            return []
        grams = {s[i:i + 2] for i in range(len(s) - 1)}
        out = []
        for g in sorted(grams & self.by2.keys()):
            out.extend((k, v) for k, v in self.by2[g] if k in s)
        return out


# ───────────────────────── 규칙 문맥 ─────────────────────────
@dataclass(frozen=True)
class _TextHits:
    alias: frozenset = frozenset()          # 별칭이 맞은 과제(대표 ID)
    kw: Mapping = field(default_factory=dict)       # 과제 → 맞은 서로 다른 키워드 수
    never: frozenset = frozenset()          # never 낱말이 맞은 과제
    tok_rules: frozenset = frozenset()      # 토큰 조건이 맞은 규칙 번호


def _resolve_cand(reg, pid, cand) -> str | None:
    r = reg.resolve(pid)
    return r if r in cand else None


class RuleCtx:
    """한 유효 레지스트리 + 설정에 대한 규칙 색인·가중(점수 함수가 공유한다). 설정 키는 리터럴로 읽는다(L-12)."""

    def __init__(self, reg, cfg=None, *, folder_key=None):
        cfg = default_cfg(cfg)
        self.reg, self.cfg, self.folder_key = reg, cfg, folder_key
        self.w_token = float(cfg["hier.rule.w.token"])
        self.w_key = float(cfg["hier.rule.w.keyRule"])
        self.w_alias = float(cfg["hier.rule.w.alias"])
        self.w_kw = float(cfg["hier.rule.w.keyword"])
        self.w_kw_cap = float(cfg["hier.rule.w.keywordCap"])
        self.w_cust = float(cfg["hier.rule.w.customer"])
        self.w_part = float(cfg["hier.rule.w.partner"])
        self.w_mdom = float(cfg["hier.rule.w.mailDomain"])
        self.w_folder = float(cfg["hier.rule.w.folder"])
        self.w_app = float(cfg["hier.rule.w.app"])
        self.w_team = float(cfg["hier.rule.w.teamRule"])
        self.w_ltok = float(cfg["hier.rule.w.learnedToken"])
        self.period_mult = float(cfg["hier.rule.periodOutsideMult"])
        self.ev_min = float(cfg["hier.rule.evidenceMin"])
        self.ev_margin = float(cfg["hier.rule.evidenceMargin"])
        self.dom_w = {str(k): float(v) for k, v in dict(cfg["hier.domain.w"]).items()}
        order = [d for d in cfg["hier.domain.order"] if d in _vocab.DOMAINS]
        self.dom_order = tuple(order + [d for d in ("EXT", "AX", "COM", "MP", "DEV") if d not in order])
        self.d_confirm = float(cfg["hier.domain.confirm"])
        self.d_margin = float(cfg["hier.domain.margin"])
        self.boiler = _match.boilerplate(cfg)
        self.cand = frozenset(reg.active_ids())
        self.public_classes = frozenset(str(v) for v in (reg.public_suffix or {}).values())
        self._build_projects()
        self._build_rules()
        self._build_domains()
        self._text_memo: dict[tuple, _TextHits] = {}
        self._dom_memo: dict[tuple, tuple] = {}
        self.unknown_token_feats: set[str] = set()           # 감사 hier.unknown_token_id(특징 수)

    # ── 과제 색인 ──
    def _build_projects(self) -> None:
        reg, cand = self.reg, self.cand
        alias = []
        for k, pid in reg.alias_ix.items():
            p = reg.projects.get(pid)
            rep = _resolve_cand(reg, pid, cand)
            if p is not None and p.origin != "reserved" and rep is not None:
                alias.append((k, rep))
        self.alias_kw = KwIndex(alias, "name")
        self.alias_sub = SubIndex(alias, 3)
        kw_items, nv_items = [], []
        self.cust_ix: dict[str, list[str]] = defaultdict(list)
        self.part_ix: dict[str, list[str]] = defaultdict(list)
        mdom: dict[str, set[str]] = defaultdict(set)
        self.app_ix: dict[str, list[str]] = defaultdict(list)
        self.period: dict[str, tuple[str, str]] = {}
        for pid in sorted(reg.projects):
            p = reg.projects[pid]
            if p.origin == "reserved" or p.status == "proposed" or (p.status == "retired" and not p.merged_into):
                continue
            rep = _resolve_cand(reg, pid, cand)
            if rep is None:
                continue
            for k in p.keywords:
                kw_items.append((k, (rep, ukey(k))))
            if pid == rep:
                for k in p.never:
                    nv_items.append((k, rep))
                if p.period:
                    self.period[rep] = p.period
            for c in p.customers:
                if rep not in self.cust_ix[c]:
                    self.cust_ix[c].append(rep)
            for c in p.partners:
                if rep not in self.part_ix[c]:
                    self.part_ix[c].append(rep)
            for d in p.mail_domains:
                mdom[str(d).lower()].add(rep)
            for a in p.apps:
                if rep not in self.app_ix[a]:
                    self.app_ix[a].append(rep)
        self.kw_index = KwIndex(kw_items, "name")
        self.never_index = KwIndex(nv_items, "name")
        self.mdom = tuple((d, tuple(sorted(ps))) for d, ps in sorted(mdom.items()))

    # ── 규칙 색인(팀 TR… + 학습 LK·LT…, active 만 — H §2.3.5 · §11.4) ──
    def _build_rules(self) -> None:
        self.rules: list = []                                   # (rule, w)
        tok_items = []
        for r in sorted(self.reg.rules, key=lambda x: (x.id, x.cond, x.then)):
            ck, cv = r.cond
            if r.origin == "learned":
                if ck == "token":
                    w = self.w_ltok
                elif ck in KEY_CONDS:
                    w = self.w_key
                else:
                    w = float(r.w) if r.w is not None else self.w_team
            else:
                w = float(r.w) if r.w is not None else self.w_team
            i = len(self.rules)
            self.rules.append((r, w))
            if ck == "token":
                tok_items.append((cv, i))
        self.tok_rule_index = KwIndex(tok_items, "name")
        self.folder_keys: dict[str, str] = {}
        if self.folder_key is not None:
            for r, _w in self.rules:
                if r.cond[0] == "folder":
                    self.folder_keys[r.cond[1]] = self.folder_key(r.cond[1])

    def _build_domains(self) -> None:
        items = []
        self.ai_doms: list[str] = []
        for d in _vocab.DOMAINS:
            for k in self.reg.domain_kw.get(d, ()):
                if str(k).strip().lower() == "ai":
                    self.ai_doms.append(d)
                else:
                    items.append((k, d))
        self.dom_index = KwIndex(items, "head")

    # ── 조회 ──
    def text_hits(self, f: Feat) -> _TextHits:
        if not f.toks and not f.text:
            return _TextHits()
        uk = ukey(f.text) if f.text else ""
        mk = (f.toks, uk)
        hit = self._text_memo.get(mk)
        if hit is not None:
            return hit
        alias = {v for _k, v in self.alias_kw.hits(f.toks)} | {v for _k, v in self.alias_sub.hits(uk)}
        kw: dict[str, set[str]] = defaultdict(set)
        for _k, (rep, uk_kw) in self.kw_index.hits(f.toks):
            kw[rep].add(uk_kw)
        never = {v for _k, v in self.never_index.hits(f.toks)}
        toks_r = {v for _k, v in self.tok_rule_index.hits(f.toks)}
        hit = _TextHits(frozenset(alias), {p: len(s) for p, s in kw.items()}, frozenset(never), frozenset(toks_r))
        self._text_memo[mk] = hit
        return hit

    def rule_hits(self, f: Feat, then_kind: str) -> list[tuple]:
        """조건이 맞은 규칙 [(Rule, w)] 중 결과 종류가 then_kind 인 것(규칙 ID 순)."""
        if not self.rules:
            return []
        toks_r = self.text_hits(f).tok_rules
        out = []
        for i, (r, w) in enumerate(self.rules):
            if r.then[0] != then_kind:
                continue
            ck, cv = r.cond
            if ck == "token":
                ok = i in toks_r
            elif ck == "sender_label":
                ok = cv in f.dom_labels
            elif ck == "domain":
                d = cv.lower()
                ok = any(x == d or x.endswith("." + d) for x in (f.dom_labels | f.mail_doms))
            elif ck == "app":
                ok = bool(f.app) and f.app == cv
            elif ck == "ext":
                e = cv.lower()
                ok = (e if e.startswith(".") else "." + e) in f.exts
            elif ck == "folder":
                fk = self.folder_keys.get(cv)
                ok = fk is not None and fk in f.dir_keys
            elif ck == "conv":
                ok = bool(f.conv) and f.conv == cv
            elif ck in ("fam", "repo"):
                ok = cv in f.fams
            elif ck == "dir":
                ok = cv in f.dir_keys
            else:
                ok = False
            if ok:
                out.append((r, w))
        return out

    def domain_hits(self, f: Feat) -> tuple:
        mk = (f.toks, f.text.lower() if self.ai_doms and f.text else "")
        hit = self._dom_memo.get(mk)
        if hit is None:
            hs = [(len(k), d, str(k)) for k, d in self.dom_index.hits(f.toks)]
            if self.ai_doms and f.text and _match.ai_hit(f.text):
                hs += [(2, d, "ai") for d in self.ai_doms]
            hit = tuple(hs)
            self._dom_memo[mk] = hit
        return hit


_CTX_CACHE: list = []


def rule_ctx(reg, cfg=None, *, folder_key=None) -> RuleCtx:
    """같은 (레지스트리, 설정, 폴더 키 함수) 의 규칙 문맥을 다시 쓴다(마지막 하나만 기억)."""
    for r, c, fk, ctx in _CTX_CACHE:
        if r is reg and c is cfg and fk is folder_key:
            return ctx
    ctx = RuleCtx(reg, cfg, folder_key=folder_key)
    _CTX_CACHE[:] = [(reg, cfg, folder_key, ctx)]
    return ctx


def _ctx(reg, cfg, ctx) -> RuleCtx:
    if ctx is not None and ctx.reg is reg:
        return ctx
    return rule_ctx(reg, cfg)


# ───────────────────────── 과제 점수(H §4.3) ─────────────────────────
def score_projects(f: Feat, reg, cfg=None, *, ctx: RuleCtx | None = None, why: dict | None = None) -> dict[str, float]:
    """증거 하나의 과제별 가점 합(−∞ = never). why 를 주면 과제 → 근거 조각 목록을 채운다(설명 원장 — 로컬 전용)."""
    c = _ctx(reg, cfg, ctx)
    sc: dict[str, float] = {}

    def add(pid, w: float, tag: str) -> None:
        if pid is None or pid not in c.cand:
            return
        sc[pid] = sc.get(pid, 0.0) + w
        if why is not None:
            why.setdefault(pid, []).append(f"{tag} +{w:g}")

    for tid in sorted(f.ent.get("과제", ())):                                    # R1 과제 토큰
        rep = _resolve_cand(reg, tid, c.cand)
        if rep is None:
            c.unknown_token_feats.add(f.id)                                        # 모르는·퇴역 과제 토큰은 점수 0(H §14)
            continue
        add(rep, c.w_token, f"token [과제:{tid}]")
    th = c.text_hits(f)
    for pid in sorted(th.alias):                                                   # R3 별칭·코드네임(과제마다 한 번)
        add(pid, c.w_alias, "alias")
    for pid in sorted(th.kw):                                                      # R4 키워드(서로 다른 것만)
        n = th.kw[pid]
        add(pid, min(c.w_kw * n, c.w_kw_cap), f"keyword×{n}")
    custs = set(f.ent.get("고객사", ())) | {lb.split(":", 1)[1] for lb in f.dom_labels if lb.startswith("고객사:")}
    for cid in sorted(custs):                                                      # R5 고객사(공유 과제 수로 나눔)
        ps = c.cust_ix.get(cid, ())
        for pid in ps:
            add(pid, c.w_cust / len(ps), f"customer {cid}")
    parts = set(f.ent.get("협력사", ())) | {lb.split(":", 1)[1] for lb in f.dom_labels if lb.startswith("협력사:")}
    for vid in sorted(parts):                                                      # R5′ 협력사
        ps = c.part_ix.get(vid, ())
        for pid in ps:
            add(pid, c.w_part / len(ps), f"partner {vid}")
    if c.mdom and (f.dom_labels or f.mail_doms):                                   # R6 메일 도메인(하위 도메인 포함)
        labels = f.dom_labels | f.mail_doms
        for d, ps in c.mdom:
            if any(x == d or x.endswith("." + d) for x in labels):
                for pid in ps:
                    add(pid, c.w_mdom / len(ps), "mail_domain")
    folder = {reg.folder_ix[k] for k in f.dir_keys if k in reg.folder_ix}         # R7 폴더·감시 루트(과제마다 한 번)
    if f.root_id and f.root_id in reg.root_ix:
        folder.add(reg.root_ix[f.root_id])
    for pid in sorted(folder):
        add(_resolve_cand(reg, pid, c.cand), c.w_folder, "folder")
    if f.app:                                                                      # R8 앱
        for pid in c.app_ix.get(f.app, ()):
            add(pid, c.w_app, "app")
    for r, w in c.rule_hits(f, "project"):                                        # R2·R9·R10 규칙
        add(_resolve_cand(reg, r.then[1], c.cand), w, r.id)
    for pid in list(sc):                                                           # R11 never
        if pid in th.never:
            sc[pid] = NEG
            if why is not None:
                why.setdefault(pid, []).append("never −∞")
    if c.period and f.t:                                                           # R12 기간 밖
        m = month_of(f.t)
        for pid in list(sc):
            per = c.period.get(pid)
            if per and sc[pid] != NEG and (m < per[0] or (per[1] and m > per[1])):
                sc[pid] *= c.period_mult
                if why is not None:
                    why.setdefault(pid, []).append(f"period ×{c.period_mult:g}")
    if f.weight_mult != 1.0:
        for pid in list(sc):
            if sc[pid] != NEG:
                sc[pid] *= f.weight_mult
    return sc


def best_two(sc: Mapping[str, float]) -> tuple[tuple[str | None, float], tuple[str | None, float]]:
    """(1위, 2위) — −∞ 는 후보에서 뺀다. 동률은 과제 ID 사전순. 없으면 (None, 0.0)."""
    good = sorted(((k, v) for k, v in sc.items() if v != NEG), key=lambda x: (-x[1], x[0]))
    top = good[0] if good else (None, 0.0)
    sec = good[1] if len(good) > 1 else (None, 0.0)
    return top, sec


# ───────────────────────── 영역 점수(H §4.4) ─────────────────────────
def score_domains(f: Feat, reg, cfg=None, *, ctx: RuleCtx | None = None) -> dict[str, float]:
    """증거 하나의 영역 점수. 증거 하나는 영역 하나(+ 팀 규칙 then.domain 가점)."""
    c = _ctx(reg, cfg, ctx)
    hits = list(c.domain_hits(f))
    for lb in sorted(f.dom_labels & c.public_classes):                              # 상대 계급 기관(공공 계급) → EXT
        hits.append((0, "EXT", _PUBLIC_PSEUDO + ":" + lb))
    keep: list[tuple[int, str, str]] = []
    for h in sorted(hits, key=lambda x: (-x[0], x[2], x[1])):
        if any(h[2] != k2 and h[2] in k2 for _n, _d, k2 in keep):                  # 긴 키워드가 짧은 키워드를 덮는다
            continue
        keep.append(h)
    out: dict[str, float] = {}
    if keep:
        doms = {d for _n, d, _k in keep}
        dom = next(d for d in c.dom_order if d in doms)
        pub_w = c.dom_w.get(PUBLIC_CLASS_KEY, c.dom_w.get("EXT", 1.0))
        w = max((pub_w if k.startswith(_PUBLIC_PSEUDO) else c.dom_w.get(dom, 1.0)) for _n, d, k in keep if d == dom)
        n = sum(1 for _n, d, _k in keep if d == dom)
        out[dom] = w * min(n, 2)
    for r, w in c.rule_hits(f, "domain"):
        d = r.then[1]
        if d in _vocab.DOMAINS:
            out[d] = out.get(d, 0.0) + w
    if f.weight_mult != 1.0:
        out = {d: v * f.weight_mult for d, v in out.items()}
    return out


# ───────────────────────── 증거 꼬리표(H §4.5) ─────────────────────────
@dataclass(frozen=True)
class HierTags:
    """시간 코어로 넘기는 증거 꼬리표(계약 §3.15 · H §12.3 · X8). 키는 시간 코어 키(msg_key · fam_key)."""
    msg: Mapping[str, str] = field(default_factory=dict)       # msg_key → 과제 ID
    fam: Mapping[str, str] = field(default_factory=dict)       # 문서군 키 → 과제 ID
    shared_fams: frozenset[str] = frozenset()                  # 공용 문서군 키(레지스트리 shared_docs)

    def to_obj(self) -> dict:
        return {"msg": dict(sorted(self.msg.items())), "fam": dict(sorted(self.fam.items())),
                "shared_fams": sorted(self.shared_fams)}


def family_feats(feats: Iterable[Feat]) -> dict[str, Feat]:
    """문서군 키 → 합집합 특징(그 문서군의 파일·창 특징 + 첨부 이름 특징 — H §4.5). 메일 본문·제목은 넣지 않는다."""
    parts: dict[str, list[Feat]] = defaultdict(list)
    for f in feats:
        if f.kind in ("file", "win"):
            for fk in f.fams:
                parts[fk].append(f)
        elif f.kind in ("mail", "teams"):
            for fk, nm in f.names:
                if fk:
                    parts[fk].append(_name_feat(f, fk, nm))
    return {fk: union_feat(sorted(fs, key=lambda x: (x.t, x.id)), "fam:" + fk) for fk, fs in sorted(parts.items())}


def _name_feat(f: Feat, fk: str, nm: str) -> Feat:
    return feat(f.id + "#" + fk, "file", nm, t=f.t, fams=(fk,), names=((fk, nm),))


def _row(fid: str, sc: Mapping[str, float], ev_min: float, ev_margin: float) -> dict:
    good = sorted(((k, v) for k, v in sc.items() if v != NEG), key=lambda x: (-x[1], x[0]))
    top = good[0] if good else (None, 0.0)
    sec = good[1][1] if len(good) > 1 else 0.0
    proj = top[0] if top[0] is not None and top[1] >= ev_min and top[1] - sec >= ev_margin else None
    score = top[1] if math.isfinite(top[1]) else 0.0
    return {"id": fid, "proj": proj, "score": score, "top2": [[k, v] for k, v in good[:2]]}


def tag_rows(feats: Iterable[Feat], reg, cfg=None, *, ctx: RuleCtx | None = None) -> list[dict]:
    """증거·문서군 꼬리표 행 `{id, proj, score, top2}`(evidence_tags.jsonl — 설명·디버그용). 문서군 행 id = 'fam:<키>'."""
    c = _ctx(reg, cfg, ctx)
    fs = list(feats)
    rows = []
    for f in sorted(fs, key=lambda x: x.id):
        if f.kind in ("mail", "teams", "cal", "summary", "file", "win", "git", "compute", "manual"):
            rows.append(_row(f.id, score_projects(f, reg, ctx=c), c.ev_min, c.ev_margin))
    for fk, uf in family_feats(fs).items():
        rows.append(_row("fam:" + fk, score_projects(uf, reg, ctx=c), c.ev_min, c.ev_margin))
    return rows


def tags_from_rows(rows: Iterable[Mapping], feats: Iterable[Feat], reg) -> HierTags:
    """꼬리표 행 → HierTags. 같은 msg_key 에 꼬리표가 엇갈리면 붙이지 않는다(연결 제약을 걸지 않는 쪽이 안전)."""
    by_id = {r["id"]: r.get("proj") for r in rows}
    msg: dict[str, str | None] = {}
    for f in sorted(feats, key=lambda x: x.id):
        if f.kind not in ("mail", "teams", "cal", "summary") or not f.key:
            continue
        p = by_id.get(f.id)
        if f.key in msg and msg[f.key] != p:
            msg[f.key] = None
        else:
            msg.setdefault(f.key, p)
    fam = {k[4:]: p for k, p in by_id.items() if k.startswith("fam:") and p}
    shared = set()
    for pid in sorted(reg.projects):
        p = reg.projects[pid]
        if p.origin != "reserved":
            shared |= set(p.shared_fams)
    return HierTags(msg={k: v for k, v in sorted(msg.items()) if v}, fam=dict(sorted(fam.items())),
                    shared_fams=frozenset(shared))


def tag_evidence(feats: Iterable[Feat], reg, cfg=None, *, ctx: RuleCtx | None = None) -> HierTags:
    """증거 꼬리표(H §4.5) — 시간 코어 `normalize(…, tags)` 로 넘기는 값. 결정적 규칙에서만 나온다(H-I6)."""
    fs = list(feats)
    return tags_from_rows(tag_rows(fs, reg, cfg, ctx=ctx), fs, reg)
