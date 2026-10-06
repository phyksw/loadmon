# -*- coding: utf-8 -*-
r"""새 과제 제안 큐 — `data\local_only\hier\proposals.json`(`lm27.proposals/1`, H §7 · §3.3, 계약 §3.15 · X-240 · X-252).

- 코파일럿·부트스트랩이 말한 새 과제 이름은 **제안**일 뿐이다(H-I6): 레지스트리·규칙·다음 프롬프트 과제 목록에 자동으로
  들어가지 않는다. 들어가는 길은 사람 결정 둘뿐 — [내 과제로 받기](개인 로컬 과제 `L-…`) · 팀장 등록(`adopted`·별칭).
- 그래도 MM 이 미분류로 새지 않게, 제안에 붙은 단위업무는 **제안 과제**로 계상한다(라벨 과제 자리 = `proposal_id`,
  영역 = `domain_guess`). 영역 필드 이름은 `domain_guess`(X-240).
- `on_new_name(label, dom, group, src, reg)`: 등록 과제 별칭이면 그 과제로 · 거절한 이름이면 예약 과제 · 군집 투입 <
  `hier.proposals.minEffortMin` 이면 예약 과제 · 같은 사람의 제안과 `pair_score` 자동 구간이면 그 제안에 붙이고, 질문 구간이면
  새 제안 + H04 재료. `ai_out.proposals` 는 폐지됐다(X-252) — NEW 답은 이 함수로만 들어온다.
- `proposal_id` = `pr_` + 순번(`^pr_\d{1,4}$`) — 이 사람 안에서 유일하고 다시 쓰지 않는다. 파일이 깨지면 `.bak` 로 복구하고,
  둘 다 깨지면 빈 큐 + 경고, 순번은 `min_seq`(호출자가 아는 최대 번호 + 1)부터.
- 쓰기는 `fsx.atomic_write`(직전 판 `.bak`). 시각은 호출자가 주입한다(결정성).
- 개인 로컬 레지스트리(`registry_local.json`) 쓰기는 `update_local` 하나로 한다(읽기 → 바꾸기 → `validate_local` → `.bak` →
  원자 쓰기): [내 과제로 받기](`accept_local`) · 코드네임 검토 [과제 이름](`from_codename` — H §8.1, `codenames=[후보]`,
  설명은 비운다) · [무시]·[이대로 진행]·[건너뛰기](`mark_codename_review`).
- `consolidate(ai_pairs, reg)` — 부트스트랩 2회차 AI 통합 쌍(H §8.3·§8.4)을 같은 사람의 제안 ↔ 제안(S2) 점수로 본다.
  AI 근거만으로는 질문 구간을 넘지 못하므로(§9.3) 그런 쌍은 H04 재료로만 남는다.

표준 라이브러리만 쓴다.
"""
import copy
import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from lm27.hier import vocab as _vocab
from lm27.hier.features import default_cfg
from lm27.hier.merge import MergeCtx, merge_ctx_for, pair_score, zone
from lm27.hier.names import ukey
from lm27.util import fsx

__all__ = [
    "LIVE", "PROPOSALS_SCHEMA", "STATUSES", "Assign", "ProposalQueue", "codename_hash", "fallback_label",
    "mark_codename_review", "normalize_label", "proposal_num", "update_local",
]

PROPOSALS_SCHEMA = "lm27.proposals/1"
STATUSES = ("pending", "accepted_local", "mapped", "rejected", "merged")
LIVE = ("pending", "accepted_local")
SOURCES = ("task_label", "bootstrap", "user", "codename_review")
FILE = "proposals.json"
BAK = "proposals.json.bak"
LOCAL_REG = "registry_local.json"
LOCAL_REG_BAK = "registry_local.json.bak"
LABEL_MAX = 20
_PR_RX = re.compile(r"^pr_(\d{1,4})$")
_LID_RX = re.compile(r"^L-(\d{4})$")
_TOKENS = re.compile(r"\[과제:[^\]]*\]|\[사람[^\]]*\]|\[나\]")


@dataclass(frozen=True)
class Assign:
    """새 이름의 배정 결과. project = 과제 ID(별칭 일치·예약), proposal = 제안 ID. ask = H04 재료(질문 구간 쌍)."""
    project: str | None = None
    proposal: str | None = None
    src: str = "proposal"                    # proposal | ai_alias | mapped | rejected_name | too_small | invalid
    ask: Mapping | None = None


def proposal_num(pid) -> int:
    m = _PR_RX.match(str(pid or ""))
    return int(m.group(1)) if m else -1


def normalize_label(label) -> str:
    """NFKC · 과제·사람 토큰 제거 · 따옴표·꺾쇠 기호 정리 · 공백 접기 · 20자."""
    s = unicodedata.normalize("NFKC", str(label or ""))
    s = _TOKENS.sub(" ", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    s = s.replace('"', " ").replace("'", " ").replace("<", " ").replace(">", " ")
    return " ".join(s.split())[:LABEL_MAX].strip()


def fallback_label(dom: str, seq: int) -> str:
    """팀 라벨 검사를 통과하지 못한 이름의 대체 '<영역 이름> 새 과제 #<순번>'(H §7.3 · §14)."""
    return f"{_vocab.domain_name(dom)} 새 과제 #{seq}"


def codename_hash(token) -> str:
    """코드네임 검토 [무시] 기록 값 — sha1(ukey(후보))[:8](H §8.1). 원 낱말은 남기지 않는다."""
    return hashlib.sha1(ukey(token).encode("utf-8")).hexdigest()[:8]


def _read(path):
    if path is None:
        return None, None
    try:
        raw = fsx.read_bytes(path)
    except OSError:
        return None, None
    try:
        obj = fsx.loads_strict(raw)
    except (ValueError, UnicodeDecodeError):
        return None, None
    return (obj, raw) if isinstance(obj, Mapping) else (None, None)


@dataclass
class ProposalQueue:
    items: list = field(default_factory=list)
    next_seq: int = 1
    path: object = None
    bak: object = None
    raw: bytes | None = None
    warnings: list = field(default_factory=list)
    asks: list = field(default_factory=list)                 # 이번 실행의 H04 재료(질문 구간 쌍)

    # ── 적재·저장 ──
    @classmethod
    def for_paths(cls, paths, *, min_seq: int = 1) -> "ProposalQueue":
        return cls.load(paths.hier_local_file(FILE), paths.hier_local_file(BAK), min_seq=min_seq)

    @classmethod
    def load(cls, path=None, bak=None, *, min_seq: int = 1) -> "ProposalQueue":
        """깨졌으면 .bak, 둘 다 깨지면 빈 큐 + 경고. 파일이 없으면 빈 큐(첫 실행의 정상 상태)."""
        obj, raw = _read(path)
        warns = []
        if obj is None and raw is None and path is not None:
            exists = _exists(path)
            if exists:
                warns.append("proposals_broken")
                obj, _ = _read(bak)
                if obj is not None:
                    warns.append("proposals_from_bak")
        items = []
        nxt = max(1, int(min_seq))
        if isinstance(obj, Mapping) and obj.get("schema") == PROPOSALS_SCHEMA:
            for it in obj.get("items") or []:
                if isinstance(it, Mapping) and proposal_num(it.get("proposal_id")) >= 0:
                    items.append(_clean_item(it))
            n = obj.get("next_seq")
            if isinstance(n, int) and not isinstance(n, bool):
                nxt = max(nxt, n)
        nxt = max([nxt] + [proposal_num(it["proposal_id"]) + 1 for it in items])
        q = cls(sorted(items, key=lambda x: proposal_num(x["proposal_id"])), nxt, path, bak, raw, warns)
        return q

    def to_obj(self) -> dict:
        return {"schema": PROPOSALS_SCHEMA, "next_seq": self.next_seq,
                "items": [self.items[i] for i in range(len(self.items))]}

    def save(self) -> bool:
        if self.path is None:
            raise ValueError("ProposalQueue.save: 경로가 없습니다")
        data = fsx.canon_bytes(self.to_obj())
        if self.raw is not None and data == self.raw:
            return False
        if self.raw is not None and self.bak is not None:
            fsx.atomic_write(self.bak, self.raw)
        fsx.atomic_write(self.path, data)
        self.raw = data
        return True

    # ── 조회 ──
    def get(self, pid: str) -> dict | None:
        return next((it for it in self.items if it["proposal_id"] == pid), None)

    def live(self) -> list[dict]:
        return [it for it in self.items if it["status"] in LIVE]

    def rejected_ukeys(self) -> set[str]:
        return {it["ukey"] for it in self.items if it["status"] == "rejected"}

    def dom_of(self, pid: str) -> str:
        it = self.get(pid)
        return it["domain_guess"] if it is not None else "UNC"

    # ── 생성·중복 제거(H §7.4) ──
    def on_new_name(self, label, dom, group: str, src: str, reg, *, cfg=None, effort_min: int = 0, conf: str = "",
                    at: str = "", evidence_keys: Iterable[str] = (), customers: Iterable[str] = (),
                    label_check: Callable[[str], bool] | None = None, ctx: MergeCtx | None = None) -> Assign:
        """새 이름(코파일럿 NEW·부트스트랩) → 배정. `label_check(s) -> bool` 은 팀 라벨 검사(P check_team_label 통과면 참)."""
        cfg = default_cfg(cfg)
        d = dom if dom in _vocab.DOMAINS else ""
        lab = normalize_label(label)
        if len(lab) < 2 or not d:
            return Assign(project=None, src="invalid")
        k = ukey(lab)
        if k in reg.alias_ix:                                        # 등록 과제를 NEW 로 답함 → 그 과제로
            return Assign(project=reg.resolve(reg.alias_ix[k]), src="ai_alias")
        if k in self.rejected_ukeys():
            return Assign(project=_vocab.RESERVED_BY_DOMAIN[d], src="rejected_name")
        done = self._settled(k, reg)                                # 이미 대응·합친 이름 → 그 결과를 따른다(새 제안 없음)
        if done is not None:
            if done.get("status") in LIVE:
                self._attach(done, group, src, conf, at, frozenset(str(x) for x in evidence_keys if x),
                             frozenset(str(x) for x in customers if x))
                return Assign(proposal=done["proposal_id"])
            return Assign(project=reg.resolve(done["mapped_to"]), src="mapped")
        if int(effort_min) < int(cfg["hier.proposals.minEffortMin"]):
            return Assign(project=_vocab.RESERVED_BY_DOMAIN[d], src="too_small")
        ev = frozenset(str(x) for x in evidence_keys if x)
        cs = frozenset(str(x) for x in customers if x)
        mc = ctx if ctx is not None else merge_ctx_for(reg, cfg)
        me = {"label": lab, "domain_guess": d, "status": "pending", "evidence_keys": ev, "customers": cs}
        scored = []
        for p in self.live():
            s, why = pair_score(lab, p["label"], _s2_ctx(mc, me, p))
            scored.append((s, p, why))
        scored.sort(key=lambda x: (-(x[0] if x[0] != float("-inf") else -1e18), proposal_num(x[1]["proposal_id"])))
        top = scored[0] if scored else None
        if top is not None and zone(top[0], auto=mc.auto, ask=mc.ask) == "auto":
            p = top[1]
            self._attach(p, group, src, conf, at, ev, cs)
            return Assign(proposal=p["proposal_id"])
        p = self._new(lab, d, group, src, conf, at, ev, cs, label_check)
        ask = None
        if top is not None and zone(top[0], auto=mc.auto, ask=mc.ask) == "ask":
            ask = {"a": p["proposal_id"], "b": top[1]["proposal_id"], "score": top[0], "why": top[2],
                   "names": [p["label"], top[1]["label"]]}
            self.asks.append(ask)
        return Assign(proposal=p["proposal_id"], ask=ask)

    def _settled(self, k: str, reg) -> dict | None:
        """ukey 가 같은 대응(mapped)·합친(merged) 제안의 끝: 살아 있는 대표 제안 또는 대응된 제안. 없으면 None."""
        for it in sorted(self.items, key=lambda x: proposal_num(x["proposal_id"])):
            if it["ukey"] != k or it["status"] not in ("mapped", "merged"):
                continue
            end = self.get(self.resolve(it["proposal_id"])) if it["status"] == "merged" else it
            if end is None:
                continue
            if end["status"] in LIVE:
                return end
            if end["status"] == "mapped" and end.get("mapped_to") and reg.resolve(end["mapped_to"]):
                return end
        return None

    def _attach(self, p: dict, group: str, src: str, conf: str, at: str, ev, cs) -> None:
        if group and not any(s.get("group") == group and s.get("from") == src for s in p["sources"]):
            p["sources"].append({"from": src, "group": group, "conf": conf, "at": at})
        if group and group not in p["groups"]:
            p["groups"] = sorted(set(p["groups"]) | {group})
        p["evidence_keys"] = sorted(set(p.get("evidence_keys") or ()) | set(ev))
        p["customers"] = sorted(set(p.get("customers") or ()) | set(cs))

    def _new(self, lab: str, dom: str, group: str, src: str, conf: str, at: str, ev, cs, label_check) -> dict:
        seq = self.next_seq
        self.next_seq += 1
        pid = f"pr_{seq}"
        label = lab
        if label_check is not None and not label_check(lab):
            label = fallback_label(dom, seq)
            self.warnings.append("proposal_label_rejected")
        it = {"proposal_id": pid, "kind": "project", "label": label, "ukey": ukey(lab), "domain_guess": dom,
              "status": "accepted_local" if src in ("user", "codename_review") else "pending",
              "local_project": None, "mapped_to": None, "merged_into": None,
              "sources": [{"from": src, "group": group, "conf": conf, "at": at}] if group else [],
              "groups": [group] if group else [], "n_units": 0, "effort_min": 0, "first_at": None, "last_at": None,
              "match_words": [], "evidence_keys": sorted(ev), "customers": sorted(cs),
              "history": [{"at": at, "event": "created", "by": src}]}
        self.items.append(it)
        return it

    # ── 사람 결정(H §7.5) ──
    def _event(self, it: dict, event: str, at: str, by: str = "user", **extra) -> None:
        e = {"at": at, "event": event, "by": by}
        e.update(extra)
        it["history"].append(e)

    def accept_local(self, pid: str, keywords: Iterable[str] = (), *, paths=None, local_path=None, local_bak=None,
                     dom: str | None = None, at: str = "", created_from: str = "task_label",
                     codenames: Iterable[str] = (), desc: str | None = None) -> str:
        """[내 과제로 받기] → 개인 로컬 레지스트리에 `L-…`(이름 = label, 영역 = domain_guess 또는 dom, copilot_desc = desc
        또는 label, keywords = 사용자가 고른 match_words, codenames = 코드네임 검토 후보) 를 만들고 제안을 accepted_local 로.
        만든 L-ID 를 돌려준다."""
        it = self.get(pid)
        if it is None or it["status"] not in LIVE:
            raise ValueError(f"accept_local: 받을 수 없는 제안 {pid!r}")
        if it["status"] == "accepted_local" and it.get("local_project"):
            return it["local_project"]
        d = dom if dom in _vocab.DOMAINS else it["domain_guess"]
        kws = [w for w in dict.fromkeys(str(x) for x in keywords if str(x).strip()) if 2 <= len(w) <= 40][:30]
        cns = [w for w in dict.fromkeys(unicodedata.normalize("NFKC", str(x)).strip() for x in codenames)
               if 2 <= len(w) <= 40][:20]
        cdesc = it["label"][:40] if desc is None else str(desc)[:40]
        box: dict = {}

        def add(obj: dict) -> None:
            projects = [dict(p) for p in (obj.get("projects") or []) if isinstance(p, Mapping)]
            used = [int(m.group(1)) for p in projects for m in [_LID_RX.match(str(p.get("id") or ""))] if m]
            lid = f"L-{(max(used) + 1 if used else 1):04d}"
            projects.append({"id": lid, "name": it["label"], "domain": d, "status": "active", "aliases": [],
                             "codenames": cns, "mask_name": False, "keywords": kws, "never": [], "mail_domains": [],
                             "customers": [], "partners": [], "folders": [], "apps": [], "default_field": "",
                             "default_func": "", "ax_link": False, "copilot_desc": cdesc,
                             "proposal_id": pid, "maps_to": None, "created_from": created_from,
                             "created_at": at[:10] if at else ""})
            obj["projects"] = projects
            box["lid"] = lid

        update_local(add, paths=paths, local_path=local_path, local_bak=local_bak)
        lid = box["lid"]
        it["status"] = "accepted_local"
        it["local_project"] = lid
        it["domain_guess"] = d
        self._event(it, "accepted_local", at, project=lid)
        return lid

    def from_codename(self, token: str, dom: str, reg, *, paths=None, local_path=None, local_bak=None,
                      at: str = "") -> str:
        """코드네임 검토 [과제 이름](H §8.1) → 제안 accepted_local + 개인 과제 `L-…`(codenames=[후보], 설명 비움 — 프롬프트에는
        `L-… · 영역 · (설명 없음)` 만 간다). 이미 등록된 이름이면 그 과제 ID 를 돌려주고 아무것도 쓰지 않는다."""
        lab = normalize_label(token)
        d = dom if dom in _vocab.DOMAINS else "DEV"
        k = ukey(lab)
        if len(lab) < 2:
            raise ValueError("from_codename: 후보가 너무 짧습니다")
        if k in reg.alias_ix:
            return reg.resolve(reg.alias_ix[k])
        p = next((x for x in self.items if x["ukey"] == k and x["status"] in LIVE), None)
        if p is None:
            p = self._new(lab, d, "", "codename_review", "h", at, frozenset(), frozenset(), None)
        if p.get("local_project"):
            return p["local_project"]
        return self.accept_local(p["proposal_id"], (), paths=paths, local_path=local_path, local_bak=local_bak,
                                 dom=d, at=at, created_from="codename_review", codenames=[token], desc="")

    def map_to(self, pid: str, project: str, *, at: str = "", by: str = "user") -> None:
        """[기존 과제와 같음] 또는 팀 등록(adopted·별칭) → mapped."""
        it = self.get(pid)
        if it is None:
            raise ValueError(f"map_to: 모르는 제안 {pid!r}")
        it["status"] = "mapped"
        it["mapped_to"] = project
        self._event(it, "mapped", at, by, project=project)

    def reject(self, pid: str, *, at: str = "") -> None:
        it = self.get(pid)
        if it is None:
            raise ValueError(f"reject: 모르는 제안 {pid!r}")
        it["status"] = "rejected"
        self._event(it, "rejected", at)

    def unreject(self, pid: str, *, at: str = "") -> None:
        it = self.get(pid)
        if it is None or it["status"] != "rejected":
            raise ValueError(f"unreject: 거절 상태가 아닌 제안 {pid!r}")
        it["status"] = "pending"
        self._event(it, "unrejected", at)

    def rename(self, pid: str, label: str, *, at: str = "") -> None:
        it = self.get(pid)
        lab = normalize_label(label)
        if it is None or len(lab) < 2:
            raise ValueError("rename: 제안이 없거나 이름이 짧습니다")
        it["label"] = lab
        it["ukey"] = ukey(lab)
        self._event(it, "renamed", at)

    def merge(self, pid: str, into: str, *, at: str = "", by: str = "user") -> None:
        """[다른 제안과 합치기] — 군집·근거를 옮기고 merged_into 를 남긴다(먼저 만든 쪽이 대표 — ID 안정)."""
        a, b = self.get(pid), self.get(into)
        if a is None or b is None or a is b:
            raise ValueError("merge: 제안이 없습니다")
        a["status"] = "merged"
        a["merged_into"] = into
        b["groups"] = sorted(set(b["groups"]) | set(a["groups"]))
        b["sources"] = b["sources"] + [s for s in a["sources"] if s not in b["sources"]]
        b["evidence_keys"] = sorted(set(b.get("evidence_keys") or ()) | set(a.get("evidence_keys") or ()))
        self._event(a, "merged", at, by, into=into)

    def resolve(self, pid: str | None) -> str | None:
        """merged_into 사슬 끝(순환이면 시작 ID)."""
        seen = set()
        cur = pid
        while cur and cur not in seen:
            seen.add(cur)
            it = self.get(cur)
            if it is None or it["status"] != "merged" or not it.get("merged_into"):
                return cur
            cur = it["merged_into"]
        return pid

    # ── 부트스트랩 2회차 통합 쌍(H §8.3·§8.4 — S2) ──
    def consolidate(self, ai_pairs: Iterable, reg, cfg=None, *, at: str = "",
                    ctx: MergeCtx | None = None) -> tuple[list[tuple[str, str]], list[dict]]:
        """AI 통합 제안 쌍(ukey frozenset) 중 둘 다 살아 있는 제안인 쌍을 S2 점수로 본다. 자동 구간(사람이 볼 근거 포함)이면
        늦게 만든 pending 제안을 먼저 만든 쪽에 합치고, 질문 구간이면 H04 재료(`asks`). AI 근거만으로는 질문 구간을 넘지 못한다
        (`pair_score`). 반환 ([(합쳐진 제안, 대표)], [이번에 만든 질문 재료])."""
        cfg = default_cfg(cfg)
        pairs = sorted({tuple(sorted(p)) for p in (ai_pairs or ()) if len(frozenset(p)) == 2})
        if not pairs:
            return [], []
        mc = ctx if ctx is not None else merge_ctx_for(reg, cfg)
        mc = MergeCtx(never=mc.never, never_words=mc.never_words, registry_ids=mc.registry_ids,
                      ai_pairs=frozenset(frozenset(p) for p in pairs), auto=mc.auto, ask=mc.ask,
                      span_gap_days=mc.span_gap_days)
        by_key: dict[str, dict] = {}
        for p in sorted(self.live(), key=lambda x: proposal_num(x["proposal_id"])):
            by_key.setdefault(p["ukey"], p)
        merged, asks = [], []
        for ka, kb in pairs:
            a, b = by_key.get(ka), by_key.get(kb)
            if a is None or b is None or a is b or a["status"] not in LIVE or b["status"] not in LIVE:
                continue
            first, second = sorted((a, b), key=lambda x: proposal_num(x["proposal_id"]))
            s, why = pair_score(second["label"], first["label"], _s2_ctx(mc, second, first))
            z = zone(s, auto=mc.auto, ask=mc.ask)
            if z == "auto" and second["status"] == "pending":
                self.merge(second["proposal_id"], first["proposal_id"], at=at, by="auto")
                merged.append((second["proposal_id"], first["proposal_id"]))
            elif z in ("auto", "ask"):
                ask = {"a": second["proposal_id"], "b": first["proposal_id"], "score": s, "why": why,
                       "names": [second["label"], first["label"]], "scope": "S2"}
                self.asks.append(ask)
                asks.append(ask)
        return merged, asks

    # ── 팀 레지스트리 반영(H §7.6) ──
    def sync_registry(self, reg, person_key: str | None, *, at: str = "") -> list[tuple[str, str]]:
        """팀 `adopted` 에 내 person_key·제안 ID 가 있으면, 또는 제안·개인 과제 이름이 팀 과제 별칭과 같으면 mapped.
        반환 [(제안 ID, 팀 과제 ID)] — 화면 알림 '제안 → 팀 과제 P-… 로 연결됨'. 사용자 조작은 필요 없다."""
        out = []
        adopted = {}
        team_alias = {}
        for pid in sorted(reg.projects):
            p = reg.projects[pid]
            if p.origin != "team":
                continue
            for pk, pr in p.adopted:
                adopted[(pk, pr)] = reg.resolve(pid)
            for a in (p.name, *p.aliases, *p.codenames):
                team_alias.setdefault(ukey(a), reg.resolve(pid))
        for it in self.items:
            if it["status"] not in LIVE:
                continue
            tgt = adopted.get((person_key, it["proposal_id"])) if person_key else None
            if tgt is None:
                tgt = team_alias.get(it["ukey"])
            if tgt is None and it.get("local_project"):
                lp = reg.projects.get(it["local_project"])
                if lp is not None and lp.maps_to:
                    tgt = reg.resolve(lp.maps_to)
            if tgt is not None:
                self.map_to(it["proposal_id"], tgt, at=at, by="registry")
                out.append((it["proposal_id"], tgt))
        return out

    # ── 매 실행 다시 계산하는 근거(H §7.3) ──
    def refresh(self, labels: Mapping, groups: Iterable, *, efforts: Mapping[str, int] | None = None,
                days: Mapping[str, tuple[str, str]] | None = None) -> None:
        """이번 실행의 라벨로 groups·n_units·effort_min·first_at·last_at 를 다시 센다(근거 표시용, 로컬 전용).
        labels = {unit_id: UnitLabel 또는 사전}, groups = 군집(구성원), efforts = unit_id → 투입 분, days = unit_id → (첫, 끝 날짜)."""
        gmap = {}
        for g in groups:
            for m in getattr(g, "members", ()):
                gmap[m] = g.key
        acc: dict[str, dict] = {}
        for uid in sorted(labels):
            lb = labels[uid]
            pr = lb.get("proposal_id") if isinstance(lb, Mapping) else getattr(lb, "proposal_id", None)
            if not pr:
                continue
            a = acc.setdefault(pr, {"groups": set(), "n": 0, "eff": 0, "first": None, "last": None})
            a["n"] += 1
            if uid in gmap:
                a["groups"].add(gmap[uid])
            a["eff"] += int((efforts or {}).get(uid, 0))
            f, la = (days or {}).get(uid, (None, None))
            if f and (a["first"] is None or f < a["first"]):
                a["first"] = f
            if la and (a["last"] is None or la > a["last"]):
                a["last"] = la
        for it in self.items:
            a = acc.get(it["proposal_id"])
            if a is None:
                it.update({"n_units": 0, "effort_min": 0})
                continue
            it.update({"groups": sorted(a["groups"] | set(it["groups"])), "n_units": a["n"], "effort_min": a["eff"],
                       "first_at": a["first"], "last_at": a["last"]})

    def team_payload(self, labels: Mapping) -> list[dict]:
        """팀 묶음 `proposals[]`(H §7.6): 라벨이 가리키는 live 제안만 `{proposal_id, kind, label, domain_guess}`."""
        used = set()
        for lb in labels.values():
            pr = lb.get("proposal_id") if isinstance(lb, Mapping) else getattr(lb, "proposal_id", None)
            if pr:
                used.add(pr)
        out = []
        for it in sorted(self.items, key=lambda x: proposal_num(x["proposal_id"])):
            if it["proposal_id"] in used and it["status"] in LIVE:
                out.append({"proposal_id": it["proposal_id"], "kind": "project", "label": it["label"],
                            "domain_guess": it["domain_guess"]})
        return out

    def snapshot(self) -> dict:
        """이번 실행 시점의 사본(proposals_snapshot.json) — 근거 키는 로컬 전용이라 그대로 담는다(분석 폴더도 로컬)."""
        return self.to_obj()


def _s2_ctx(mc: MergeCtx, a: Mapping, b: Mapping) -> MergeCtx:
    """제안 두 개(label·domain_guess·status·evidence_keys·customers)의 S2 비교 문맥 — 받아들인 개인 과제의 영역은 확정."""
    two = (a, b)
    return MergeCtx(never=mc.never, never_words=mc.never_words, registry_ids=mc.registry_ids,
                    dom={x["label"]: x["domain_guess"] for x in two},
                    dom_confirmed=frozenset(x["label"] for x in two if x.get("status") == "accepted_local"),
                    shared={x["label"]: frozenset(x.get("evidence_keys") or ()) for x in two},
                    cust={x["label"]: frozenset(x.get("customers") or ()) for x in two}, span={},
                    ai_pairs=mc.ai_pairs, auto=mc.auto, ask=mc.ask, span_gap_days=mc.span_gap_days)


def update_local(mutate: Callable[[dict], None], *, paths=None, local_path=None, local_bak=None) -> dict:
    """개인 로컬 레지스트리 고쳐 쓰기: 읽기(없으면 빈 `lm27.registry_local/1`) → mutate(사본) → `validate_local`(파일 단위 위반이면
    ValueError, 아무것도 쓰지 않음) → 직전 판 `.bak` → 원자 쓰기. 깨진 파일은 덮지 않는다(.bak 복구가 먼저). 반환: 쓴 객체."""
    lp = paths.hier_local_file(LOCAL_REG) if paths is not None else local_path
    lb = paths.hier_local_file(LOCAL_REG_BAK) if paths is not None else local_bak
    if lp is None:
        raise ValueError("update_local: 개인 로컬 레지스트리 경로가 없습니다")
    obj, raw = _read(lp)
    if obj is None:
        if _exists(lp):
            raise ValueError("개인 로컬 레지스트리가 깨져 있습니다(.bak 복구 필요)")
        obj = {"schema": "lm27.registry_local/1"}
    new = copy.deepcopy(dict(obj))
    mutate(new)
    from lm27.hier.registry_schema import blocking, validate_local     # 지연 import — 개인 레지스트리 검증 단일원
    if blocking(validate_local(new)):
        raise ValueError("개인 로컬 레지스트리 검증 실패")
    if raw is not None and lb is not None:
        fsx.atomic_write(lb, raw)
    fsx.atomic_write(lp, fsx.canon_bytes(new))
    return new


def mark_codename_review(*, paths=None, local_path=None, local_bak=None, ignore: Iterable[str] = (),
                         done_at: str | None = None, skipped: bool | None = None) -> dict:
    """코드네임 검토 표시(H §8.1): [무시] → `ignored` 에 `codename_hash`, [이대로 진행] → `done_at`, [건너뛰기] → `skipped`.
    반환: 기록된 `codename_review`."""
    def mut(obj: dict) -> None:
        cr = dict(obj.get("codename_review") or {})
        ign = {str(x) for x in (cr.get("ignored") or ())}
        ign |= {codename_hash(t) for t in ignore if ukey(t)}
        if ign:
            cr["ignored"] = sorted(ign)
        if done_at is not None:
            cr["done_at"] = str(done_at)
        if skipped is not None:
            cr["skipped"] = bool(skipped)
        obj["codename_review"] = cr

    return dict(update_local(mut, paths=paths, local_path=local_path, local_bak=local_bak).get("codename_review") or {})


def _exists(path) -> bool:
    import os
    try:
        return os.path.exists(fsx.longp(path))
    except (OSError, TypeError, ValueError):
        return False


def _clean_item(it: Mapping) -> dict:
    d = dict(it)
    d.setdefault("kind", "project")
    d["label"] = str(d.get("label") or "")
    d.setdefault("ukey", ukey(d["label"]))
    dg = d.get("domain_guess") or d.get("dom_guess") or ""
    d["domain_guess"] = dg if dg in _vocab.DOMAINS else "COM"
    d.pop("dom_guess", None)
    if d.get("status") not in STATUSES:
        d["status"] = "pending"
    for k in ("sources", "groups", "match_words", "evidence_keys", "customers", "history"):
        v = d.get(k)
        d[k] = list(v) if isinstance(v, list | tuple) else []
    for k in ("local_project", "mapped_to", "merged_into", "first_at", "last_at"):
        d.setdefault(k, None)
    for k in ("n_units", "effort_min"):
        v = d.get(k)
        d[k] = int(v) if isinstance(v, int) and not isinstance(v, bool) else 0
    return d
