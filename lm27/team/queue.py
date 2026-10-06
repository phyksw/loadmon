# -*- coding: utf-8 -*-
r"""팀 묶음 대기열·재시도·보내기(TAB §2.7 · §2.8 · §2.9 · §5.1, 계약 §2.15 · §3.23 outbox meta · §6.4 outbox state · §8.3).

    items = list_items()                 # cli `team list` — QueueItem(name · folder · meta · rc · message, .path)
    preview(item) · approve(item) · mark(item, "dropped", "사유")
    send_item(item, cfg)                 # 항목 하나(계약 O-14 ① 결정 — 이 모듈) = 승인 + 전송
    send_due(cfg, trigger=…)             # 승인된 대기분(화면 기동·빌드 직후·15분마다·[팀 업로드]·[수집] 끝)
    reconcile_delivered(members)         # 오프라인으로 내보낸 항목 ↔ /api/members 의 sha12 → '전달 확인'

파일: ``data\outbox\team\{pending,sent,failed,dropped}\lm27_team_bundle_<period_key>_<sha12>.json`` + 옆 ``….json.meta.json``
(``lm27.outbox/1``) + 보내는 동안만 ``….json.lease``. 경로는 ``Paths.outbox_file(state, name)`` 로만 만든다(L-08 — 계약 v1.2
C19). 상태 → 폴더: 대기 계열(pending·sending·retry_wait·auth_needed·wrong_server·exported) = pending, sent·delivered = sent,
failed = failed, dropped = dropped.

- **미리보기 = 실전송**(TAB §2.7): 보내기·내보내기·미리보기는 모두 그 파일 바이트를 읽어 meta 의 sha256 과 대조한 뒤
  쓴다. 본문은 절대 고치지 않고, 보낸 시각·클라이언트 판은 HTTP 헤더로만 보낸다(TAB §6 LM24 결함 행).
- 재시도(TAB §2.8): 승인된 항목만(``team.autoSend`` 면 막힘 없는 항목 전부). 네트워크 오류·시간 초과·429·5xx → retry_wait
  (``team.retryScheduleSec`` 간격, ±10% 흔들기 — sha·횟수로 정해지는 결정적 값), ``team.retryMaxAttempts`` 를 넘으면
  failed(retry_exhausted). 400·411·413·415·422 → failed([다시 만들기]만), 401 → auth_needed(토큰이 바뀌면 자동 재개),
  hello 가 LM27 아님·404·410 → wrong_server(주소 설정이 바뀌면 자동 재개, POST 0). [수집]·화면 기동 계기에서는 next_at 을
  기다리지 않고 hello 를 한 번 해 보고, 안 닿으면 시도 횟수를 올리지 않는다(클라우드PC 에서 며칠 머물러도 소진되지 않게).
- 중복 전송 방지: 보내기 전에 번들 잠금 안에서 lease(``{pid, until}``)를 확인·기록한다 — 살아 있는 lease 가 있으면
  건너뛴다(서버도 sha 멱등이라 겹쳐도 안전). 표준 라이브러리 + LM27 공개 함수만.
- 가림(TAB §2.5 · C16): 미리보기 가림(``data\team\overrides.json``)을 바꾼 뒤 아직 다시 만들지 않은 묶음 — 바이트가 지금
  가림보다 덜 가려진 것(``mask_gaps``) — 은 승인·보내기·자동 전송·미리보기 [보내기] 모두 하지 않는다(rc 2 ``STALE_MASK``).
  가림을 바꾸는 쪽(``build.set_mask``·``drop_need``)은 ``unapprove_masked`` 로 그런 대기 묶음의 승인도 푼다.
- 미리보기 확인 기록(TAB §2.8 · C17): 화면 미리보기가 그 바이트를 보여 줄 때 ``mark_previewed`` 가 meta 에
  ``previewed_sha``·``previewed_at`` 을 남긴다(화면 [보내기]·[승인만]은 승인 전이면 이 기록이 있어야 한다 — ``lm27.ui.api_team``).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from lm27.util import fsx

__all__ = ["APPROVABLE", "FINAL", "FOLDER_OF", "QueueError", "QueueItem", "SENDABLE", "STALE_MASK", "STATES",
           "SendResult", "TRIGGERS", "approve", "find_item", "find_pending", "list_items", "mark", "mark_previewed",
           "mask_gaps", "new_meta", "preview", "previewed", "prune_sent", "reconcile_delivered", "send_due", "send_item",
           "supersede", "unapprove_masked", "write_pending"]

STATES = ("pending", "sending", "sent", "retry_wait", "failed", "auth_needed", "wrong_server", "dropped", "exported",
          "delivered")
FOLDER_OF = {"pending": "pending", "sending": "pending", "retry_wait": "pending", "auth_needed": "pending",
             "wrong_server": "pending", "exported": "pending", "sent": "sent", "delivered": "sent", "failed": "failed",
             "dropped": "dropped"}
FOLDERS = ("pending", "sent", "failed", "dropped")
FINAL = frozenset({"sent", "delivered", "dropped"})
SENDABLE = frozenset({"pending", "sending", "retry_wait", "auth_needed", "wrong_server"})
APPROVABLE = frozenset({"pending", "retry_wait", "auth_needed", "wrong_server", "exported"})
TRIGGERS = ("manual", "collect", "startup", "timer", "build")
META_SCHEMA = "lm27.outbox/1"
META_SUFFIX = ".meta.json"
LEASE_SUFFIX = ".lease"
LEASE_SEC = 600
PREVIEW_LOCK_S = 3                      # 미리보기 확인 기록이 번들 잠금을 기다리는 최대 초(화면 GET 이 길게 막히지 않게)
HISTORY_MAX = 50
JITTER = 0.10
BODY_RX = re.compile(r"lm27_team_bundle_(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})_([0-9a-f]{12})\.json")
_UTC_RX = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
STALE_MASK = ("가림을 바꾼 뒤 아직 다시 만들지 않은 묶음이라 보내지 않습니다 — [팀 묶음 만들기]로 다시 만들면 바뀐 가림으로 "
              "보냅니다")
MASK_NOTE = ("시간 수치(근무시간·업무별 분)는 가릴 수 없습니다 — 빼면 개인과 팀 합계가 달라집니다. 업무를 통째로 숨기려면 "
             "[세부 가림]을 쓰세요.")


class QueueError(Exception):
    """대기열 파일을 다룰 수 없음(경로 메서드 없음 등) — 한국어 한 줄."""


# ───────────────────────────── 시각·경로 ─────────────────────────────
def _now(now=None) -> datetime:
    n = now or datetime.now(UTC)
    return n if n.tzinfo is not None else n.replace(tzinfo=UTC)


def _ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(s) -> datetime | None:
    if not isinstance(s, str) or not _UTC_RX.fullmatch(s):
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _default_paths(paths=None):
    if paths is not None:
        return paths
    from lm27.paths import Paths
    return Paths()


def _ofile(paths, folder: str, name: str):
    """대기열 파일 경로 — ``Paths.outbox_file(state, name)``(계약 v1.2 §0.7 C19, W1 통합 창에서 생김 · L-08)."""
    return paths.outbox_file(folder, name)


# ───────────────────────────── 항목 ─────────────────────────────
@dataclass
class QueueItem:
    """대기열 항목 하나. ``path``·``meta_path`` 는 계산 속성(결과 출력에는 이름·폴더·meta 만 — 절대 경로 없음).
    ``rc``·``message`` = 마지막 동작의 결과(계약 §8.3 — cli 는 ``rc`` 를 읽는다)."""
    name: str = ""
    folder: str = ""
    meta: dict = field(default_factory=dict)
    rc: int = 0
    message: str = ""
    problems: list = field(default_factory=list)

    @classmethod
    def at(cls, paths, name: str, folder: str, meta: dict) -> QueueItem:
        it = cls(name=name, folder=folder, meta=meta)
        it._paths = paths
        return it

    @classmethod
    def result(cls, rc: int, message: str, *, problems=()) -> QueueItem:
        """파일이 없는 결과(만들 수 없음·검사 실패)."""
        return cls(rc=rc, message=message, problems=list(problems))

    @property
    def paths(self):
        return getattr(self, "_paths", None)

    @property
    def path(self) -> str | None:
        if not self.name or self.paths is None:
            return None
        return os.fspath(_ofile(self.paths, self.folder, self.name))

    @property
    def meta_path(self) -> str | None:
        if not self.name or self.paths is None:
            return None
        return os.fspath(_ofile(self.paths, self.folder, self.name + META_SUFFIX))

    @property
    def state(self) -> str:
        return str(self.meta.get("state") or "")

    @property
    def sha256(self) -> str:
        return str(self.meta.get("sha256") or "")

    @property
    def period_key(self) -> str:
        return str(self.meta.get("period_key") or "")


def new_meta(sha: str, nbytes: int, period_key: str, person_key: str, built_at: str, built_on: str, blockers, *,
             now=None, warnings=(), check=None) -> dict:
    """``lm27.outbox/1``(계약 §3.23 · TAB §2.8). built_on = PC 라벨(label_auto — 호스트명 아님)."""
    return {"schema": META_SCHEMA, "sha256": sha, "bytes": int(nbytes), "period_key": period_key,
            "person_key": person_key, "built_at": built_at, "built_on": built_on or "", "blockers": list(blockers),
            "warnings": list(warnings), "check": dict(sorted((check or {}).items())),
            "approved": False, "approved_at": None, "state": "pending", "attempts": 0, "next_at": None,
            "last_error": None, "last_target": None, "history": [{"at": _ts(_now(now)), "event": "built"}]}


def _synth_meta(paths, folder: str, name: str) -> dict:
    """meta 가 없거나 깨진 항목 — 본문 바이트로 sha 를 다시 세고 폴더로 상태를 정한다(승인은 다시 받는다)."""
    m = BODY_RX.fullmatch(name)
    try:
        raw = fsx.read_bytes(_ofile(paths, folder, name))
    except OSError:
        raw = b""
    st = {"pending": "pending", "sent": "sent", "failed": "failed", "dropped": "dropped"}[folder]
    meta = new_meta(fsx.sha256_hex(raw), len(raw), m.group(1) if m else "", "", "", "", [])
    meta["state"] = st
    meta["history"] = [{"at": _ts(_now()), "event": "meta_rebuilt"}]
    return meta


def _load(paths, folder: str, name: str) -> QueueItem:
    meta = fsx.read_json(_ofile(paths, folder, name + META_SUFFIX), None, want=dict)
    if not isinstance(meta, dict) or meta.get("schema") != META_SCHEMA:
        meta = _synth_meta(paths, folder, name)
    return QueueItem.at(paths, name, folder, meta)


def list_items(*, paths=None) -> list[QueueItem]:
    r"""대기열 전부(pending → sent → failed → dropped, 그 안은 기간·만든 시각·이름 순)."""
    paths = _default_paths(paths)
    out = []
    for folder in FOLDERS:
        d = paths.outbox(folder)
        try:
            names = sorted(os.listdir(fsx.longp(d)))
        except (FileNotFoundError, NotADirectoryError):
            continue
        for n in names:
            if BODY_RX.fullmatch(n):
                out.append(_load(paths, folder, n))
    out.sort(key=lambda it: (FOLDERS.index(it.folder), it.period_key, str(it.meta.get("built_at") or ""), it.name))
    return out


def find_item(paths, name: str) -> QueueItem | None:
    for it in list_items(paths=paths):
        if it.name == name or it.name[:-5] == name:
            return it
    return None


def find_pending(paths, sha: str) -> QueueItem | None:
    """같은 바이트(sha256)가 대기 중이면 그 항목(TAB §2.7 — 승인 상태 유지)."""
    for it in list_items(paths=paths):
        if it.folder == "pending" and it.sha256 == sha and it.state not in FINAL:
            return it
    return None


def _reload(item: QueueItem) -> QueueItem | None:
    paths = _default_paths(item.paths)
    for folder in (item.folder, *FOLDERS):
        if folder and os.path.isfile(fsx.longp(_ofile(paths, folder, item.name))):
            return _load(paths, folder, item.name)
    return None


def _write_meta(item: QueueItem) -> None:
    fsx.atomic_write(_ofile(item.paths, item.folder, item.name + META_SUFFIX), fsx.canon_bytes(item.meta))


def _history(meta: dict, now: datetime, event: str, why: str | None = None) -> None:
    h = [x for x in (meta.get("history") or ()) if isinstance(x, dict)]
    e = {"at": _ts(now), "event": event}
    if why:
        e["why"] = why
    h.append(e)
    meta["history"] = h[-HISTORY_MAX:]


def _remove_quiet(p) -> None:
    try:
        os.remove(fsx.longp(p))
    except FileNotFoundError:
        pass
    except OSError:
        from lm27.util import events
        events.emit("warn", text_ko="대기열 조각을 지우지 못했습니다(다음에 다시)")


def _move(item: QueueItem, folder: str) -> None:
    """상태에 맞는 폴더로 — 새 meta 를 먼저 쓰고, 본문을 옮기고(os.replace), 옛 meta·lease 를 지운다."""
    paths = item.paths
    if folder == item.folder:
        _write_meta(item)
        return
    old = item.folder
    src = _ofile(paths, old, item.name)
    dst = _ofile(paths, folder, item.name)
    fsx.atomic_write(_ofile(paths, folder, item.name + META_SUFFIX), fsx.canon_bytes(item.meta))
    fsx.ensure_dir(os.path.dirname(os.fspath(dst)))
    os.replace(fsx.longp(src), fsx.longp(dst))
    _remove_quiet(_ofile(paths, old, item.name + META_SUFFIX))
    _remove_quiet(_ofile(paths, old, item.name + LEASE_SUFFIX))
    item.folder = folder


def write_pending(paths, period_key: str, raw: bytes, meta: dict) -> QueueItem:
    r"""정규 바이트 1벌 + meta 를 ``pending\`` 에 원자 쓰기(호출자가 번들 잠금 ``team_build`` 를 쥔다)."""
    name = f"lm27_team_bundle_{period_key}_{meta['sha256'][:12]}.json"
    if not BODY_RX.fullmatch(name):
        raise QueueError("대기열 파일 이름 형식이 아닙니다(기간·sha)")
    fsx.atomic_write(_ofile(paths, "pending", name), raw)
    fsx.atomic_write(_ofile(paths, "pending", name + META_SUFFIX), fsx.canon_bytes(meta))
    return QueueItem.at(paths, name, "pending", meta)


def _lease_valid(paths, folder: str, name: str, now: datetime) -> bool:
    from lm27.util.proc import pid_alive
    cur = fsx.read_json(_ofile(paths, folder, name + LEASE_SUFFIX), None, want=dict)
    if not isinstance(cur, dict):
        return False
    until, pid = _parse_ts(cur.get("until")), cur.get("pid")
    return bool(until and until > now and isinstance(pid, int) and not isinstance(pid, bool) and pid_alive(pid))


def supersede(paths, period_key: str, keep_sha: str, *, now=None) -> list[QueueItem]:
    """같은 기간의 다른 미전송 항목 → dropped(superseded)(TAB §2.7 · U09). 보내는 중(lease)인 것은 건드리지 않는다."""
    now = _now(now)
    out = []
    for it in list_items(paths=paths):
        if it.folder == "pending" and it.period_key == period_key and it.sha256 != keep_sha \
                and it.state in APPROVABLE and not _lease_valid(paths, it.folder, it.name, now):
            out.append(mark(it, "dropped", "superseded", now=now))
    return out


# ───────────────────────────── 상태 바꾸기 ─────────────────────────────
def _lock(paths, cfg=None):
    from lm27.bundle.lock import BundleLock
    return BundleLock(paths, "team_build", cfg=cfg)


def mark(item: QueueItem, state: str, why: str, *, now=None, rc: int = 0, extra=None) -> QueueItem:
    """상태 하나로(TAB §2.8 상태 기계) — 폴더 이동·이력·마지막 오류. 이미 그 상태면 rc 4, 끝난 항목(sent·delivered·dropped)
    은 바꾸지 않는다(rc 4). ``extra`` = meta 에 함께 둘 값(next_at·attempts·last_target·fp…)."""
    if state not in STATES:
        raise ValueError(f"대기열 상태가 아닙니다: {state}")
    now = _now(now)
    paths = _default_paths(item.paths)
    with _lock(paths):
        cur = _reload(QueueItem.at(paths, item.name, item.folder, item.meta)) if item.name else None
        if cur is None:
            item.rc, item.message = 4, "대기열에 그 항목이 없습니다"
            return item
        st = cur.state
        if st == state and not extra:
            cur.rc, cur.message = 4, "이미 그 상태입니다"
            return cur
        if st in FINAL and not (st == state and extra):
            cur.rc, cur.message = 4, "이미 끝난 항목입니다(보냄·전달 확인·치움)"
            return cur
        m = dict(cur.meta)
        m["state"] = state
        if state in ("failed", "auth_needed", "wrong_server", "retry_wait"):
            m["last_error"] = why
        if state in ("pending", "retry_wait") and st == "failed":
            m["attempts"], m["next_at"] = 0, None
        if state == "sent":
            m["sent_at"], m["last_error"], m["next_at"] = _ts(now), None, None
        if state == "delivered":
            m["delivered_at"] = _ts(now)
        for k, v in (extra or {}).items():
            m[k] = v
        _history(m, now, state, why)
        cur.meta = m
        _move(cur, FOLDER_OF[state])
    cur.rc, cur.message = rc, why
    return cur


def approve(item: QueueItem, *, now=None) -> QueueItem:
    """미리보기에서 [보내기]·[승인만](TAB §2.8) — 막힌 항목(blockers)은 승인하지 않는다(rc 2)."""
    now = _now(now)
    paths = _default_paths(item.paths)
    with _lock(paths):
        cur = _reload(QueueItem.at(paths, item.name, item.folder, item.meta)) if item.name else None
        if cur is None:
            item.rc, item.message = 4, "대기열에 그 항목이 없습니다"
            return item
        if cur.meta.get("blockers"):
            cur.rc, cur.message = 2, "막힌 묶음은 승인할 수 없습니다: " + "; ".join(map(str, cur.meta["blockers"]))
            return cur
        if cur.state not in APPROVABLE:
            cur.rc, cur.message = 4, "이미 보냈거나 치운 항목입니다"
            return cur
        if mask_gaps(cur):
            cur.rc, cur.message = 2, STALE_MASK
            return cur
        if cur.meta.get("approved"):
            cur.rc, cur.message = 4, "이미 승인했습니다"
            return cur
        cur.meta["approved"], cur.meta["approved_at"] = True, _ts(now)
        _history(cur.meta, now, "approved")
        _write_meta(cur)
    cur.rc, cur.message = 0, "승인했습니다 — 팀 서버에 닿는 때 자동으로 보냅니다"
    return cur


# ───────────────────────────── 미리보기 ─────────────────────────────
def preview(item: QueueItem) -> dict:
    """미리보기(TAB §2.7 · R §5.5.2) — 파일 바이트를 읽어 sha 를 다시 세고 대조한 뒤 요약·가림 표·원문 JSON(같은 바이트).
    rc 0 = 대조 일치, 1 = 미리보기 이후 바뀜(보내지 않는다)."""
    from lm27.team import schema as S
    paths = _default_paths(item.paths)
    cur = _reload(QueueItem.at(paths, item.name, item.folder, item.meta)) if item.name else None
    if cur is None:
        return {"rc": 4, "message": "대기열에 그 항목이 없습니다"}
    raw = fsx.read_bytes(cur.path)
    sha = fsx.sha256_hex(raw)
    ok = sha == cur.sha256
    out = {"rc": 0 if ok else 1, "name": cur.name, "state": cur.state, "folder": cur.folder,
           "approved": bool(cur.meta.get("approved")), "sha256": sha, "sha12": sha[:12], "bytes": len(raw),
           "sha_ok": ok, "period_key": cur.period_key, "built_at": cur.meta.get("built_at"),
           "built_on": cur.meta.get("built_on"), "blockers": list(cur.meta.get("blockers") or ()),
           "warnings": list(cur.meta.get("warnings") or ()), "check": dict(cur.meta.get("check") or {}),
           "can_send": ok and not cur.meta.get("blockers") and cur.state in SENDABLE | {"exported"},
           "mask_note": MASK_NOTE,
           "message": "" if ok else "미리보기 이후 파일이 바뀌었습니다 — 다시 만드세요"}
    try:
        obj = S.loads_bundle(raw)
    except ValueError:
        out["rc"], out["message"] = 1, "묶음 파일을 읽을 수 없습니다 — 다시 만드세요"
        return out
    from lm27.team.build import load_overrides
    ov = load_overrides(paths)
    dom_of_role = {}
    proj_dom = {p.get("project_id"): p.get("domain") for p in obj.get("projects") or ()}
    prop_dom = {p.get("proposal_id"): p.get("domain_guess") for p in obj.get("proposals") or ()}
    for r in obj.get("roles") or ():
        dom_of_role[r.get("role_id")] = proj_dom.get(r.get("project_id")) or prop_dom.get(r.get("proposal_id")) or "UNC"
    unit_role = {u.get("unit_id"): u.get("role_id") for u in obj.get("units") or ()}
    doms: dict = {}
    for _d, uid, _t, mins in (obj.get("alloc_daily") or {}).get("rows") or ():
        k = dom_of_role.get(unit_role.get(uid), "UNC")
        doms[k] = doms.get(k, 0) + int(mins)
    out["summary"] = {
        "months": [{"month": m.get("month"), "mm": m.get("mm"), "envelope_min": m.get("envelope_min"),
                    "attributed_min": m.get("attributed_min"), "unattributed_min": m.get("unattributed_min")}
                   for m in (obj.get("summary") or {}).get("months") or ()],
        "domains": {k: doms[k] for k in sorted(doms)}, "units": len(obj.get("units") or ()),
        "peers": len(obj.get("peers") or ()), "needs": len((obj.get("agentic") or {}).get("needs") or ())}
    from lm27.team.build import mask_gaps as _gaps
    gaps = _gaps(obj, ov)
    gap_units = {g.split(":")[1] for g in gaps if g.startswith("unit:")}
    out["units"] = [{"unit_id": u.get("unit_id"), "title": u.get("title"), "title_mode": u.get("title_mode"),
                     "role_id": u.get("role_id"), "effort_min": u.get("effort_min"), "grade": u.get("grade"),
                     "status": u.get("status"), "mask": (ov.get("units") or {}).get(u.get("unit_id"), ""),
                     "mask_applied": u.get("unit_id") not in gap_units}
                    for u in obj.get("units") or ()]
    out["mask_gaps"] = gaps
    out["stale_mask"] = bool(gaps)
    if gaps:                                             # 가림을 바꿨지만 이 바이트는 그 전 것 — 보내지 않는다(C16)
        out["can_send"] = False
        if ok:
            out["message"] = STALE_MASK
    ag = obj.get("agentic") or {}
    out["needs"] = [{"need_id": n.get("need_id"), "step_type": n.get("step_type"), "label": n.get("label"),
                     "grade": n.get("grade")} for n in ag.get("needs") or ()]
    out["matches"] = [{"agent_id": m.get("agent_id"), "role_id": m.get("role_id"), "step_type": m.get("step_type"),
                       "grade": m.get("grade")} for m in ag.get("matches") or ()]
    out["subagents"] = [{"role_id": s.get("role_id"), "fit": s.get("fit")} for s in ag.get("subagents") or ()]
    out["guard"] = S.bytes_guard_hits(raw)
    out["json"] = raw.decode("utf-8")
    return out


# ───────────────────────────── 가림 변경 · 미리보기 확인(C16 · C17) ─────────────────────────────
def mask_gaps(item: QueueItem) -> list:
    """그 항목 바이트가 지금 가림(``overrides.json``)보다 덜 가려진 곳(``lm27.team.build.mask_gaps`` — 'unit:<id>:title' 등).
    빈 목록 = 지금 가림이 다 들어간 바이트(또는 읽을 수 없는 파일 — 그 판정은 sha 대조가 한다)."""
    from lm27.team import schema as S
    from lm27.team.build import load_overrides
    from lm27.team.build import mask_gaps as _gaps
    paths = _default_paths(item.paths)
    if not item.name:
        return []
    try:
        raw = fsx.read_bytes(_ofile(paths, item.folder, item.name))
        obj = S.loads_bundle(raw)
    except (OSError, ValueError):
        return []
    return _gaps(obj, load_overrides(paths))


def _unapprove(cur: QueueItem, now: datetime, why: str) -> None:
    m = dict(cur.meta)
    m["approved"], m["approved_at"] = False, None
    _history(m, now, why)
    cur.meta = m
    _write_meta(cur)


def unapprove_masked(paths=None, *, now=None) -> list[QueueItem]:
    """가림을 바꾼 뒤(TAB §2.5 — 가림을 바꾸면 이전 미전송 묶음은 보내지 않는다) 지금 가림보다 덜 가려진 대기 묶음의
    승인을 푼다(이력 ``mask_changed``). 반환 = 그런 대기 묶음 전부(승인 여부와 무관 — 화면이 다시 만들 기간을 고른다).
    끝난 항목(보냄·치움)과 다른 곳에서 보내는 중(lease)인 항목의 승인은 건드리지 않는다."""
    paths = _default_paths(paths)
    now = _now(now)
    out = []
    with _lock(paths):
        for it in list_items(paths=paths):
            if it.folder != "pending" or it.state in FINAL or not mask_gaps(it):
                continue
            if it.meta.get("approved") and not _lease_valid(paths, it.folder, it.name, now):
                _unapprove(it, now, "mask_changed")
            it.rc, it.message = 2, STALE_MASK
            out.append(it)
    return out


def mark_previewed(item: QueueItem, sha: str, *, now=None) -> QueueItem | None:
    """미리보기가 그 바이트(sha256)를 사람에게 보여 줬다는 기록(meta ``previewed_sha``·``previewed_at``). 화면의 [보내기]·
    [승인만]은 승인 전 묶음이면 이 기록이 그 바이트와 같아야 한다(TAB §2.8 '미리보기에서 [보내기] = approved' — C17)."""
    from lm27.bundle.lock import BundleLock
    paths = _default_paths(item.paths)
    now = _now(now)
    with BundleLock(paths, "team_build", PREVIEW_LOCK_S):   # 미리보기 응답을 오래 붙잡지 않는다(못 잡으면 BundleBusy)
        cur = _reload(QueueItem.at(paths, item.name, item.folder, item.meta)) if item.name else None
        if cur is None or cur.sha256 != sha or cur.state in FINAL or cur.meta.get("previewed_sha") == sha:
            return cur
        cur.meta["previewed_sha"], cur.meta["previewed_at"] = sha, _ts(now)
        _write_meta(cur)
    return cur


def previewed(item: QueueItem) -> bool:
    """이미 승인됐거나, 미리보기가 지금 바이트를 보여 준 적이 있는가(화면 [보내기]·[승인만]의 조건 — C17)."""
    m = item.meta or {}
    return bool(m.get("approved")) or (bool(m.get("previewed_sha")) and m.get("previewed_sha") == m.get("sha256"))


# ───────────────────────────── 보내기 ─────────────────────────────
def _targets_fp(cfg) -> str:
    vals = [str(cfg["team.serverHost"]), str(cfg["team.serverPort"]), *map(str, cfg["team.serverAlternates"] or ())]
    return hashlib.sha256("|".join(vals).encode("utf-8")).hexdigest()[:8]


def _jitter(sha: str, attempts: int) -> float:
    """±10% 흔들기 — sha·횟수로 정해지는 값(같은 입력 = 같은 시각, 여러 항목은 흩어진다)."""
    h = int(hashlib.sha256(f"{sha}|{attempts}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return (h * 2 - 1) * JITTER


def _retry(item: QueueItem, cfg, now: datetime, why: str, fp: dict) -> QueueItem:
    attempts = int(item.meta.get("attempts") or 0) + 1
    if attempts > int(cfg["team.retryMaxAttempts"]):
        return mark(item, "failed", f"다시 보내기를 {attempts - 1}번 했지만 보내지 못했습니다 — [다시 시도]를 누르세요"
                    "(retry_exhausted)", now=now, rc=1, extra={"attempts": attempts, "fp": fp})
    sched = [int(x) for x in (cfg["team.retryScheduleSec"] or ()) if isinstance(x, int) and x > 0] or [60]
    base = sched[min(attempts - 1, len(sched) - 1)]
    nxt = now + timedelta(seconds=round(base * (1 + _jitter(item.sha256, attempts))))
    return mark(item, "retry_wait", why, now=now, rc=2, extra={"attempts": attempts, "next_at": _ts(nxt), "fp": fp})


def _lease_take(item: QueueItem, now: datetime) -> bool:
    if _lease_valid(item.paths, item.folder, item.name, now):
        return False
    fsx.atomic_write(_ofile(item.paths, item.folder, item.name + LEASE_SUFFIX),
                     fsx.canon_bytes({"pid": os.getpid(), "until": _ts(now + timedelta(seconds=LEASE_SEC))}))
    return True


def send_item(item: QueueItem, cfg, *, now=None, approve: bool = True, picked=None, hello_fn=None) -> QueueItem:
    """항목 하나 보내기(TAB §2.9) — 계약 O-14 ①: ``lm27.team.queue.send_item(item, cfg)``(= 승인 + 전송, cli
    ``team send <item>``). 반환 QueueItem.rc: 0 보냄 · 2 retry_wait·auth_needed·wrong_server·막힘 · 1 failed · 4 보낼 상태가
    아님·다른 곳에서 보내는 중. ``picked`` = 미리 고른 (target, hello, pick)(``send_due`` 가 한 번만 묻는다)."""
    now = _now(now)
    paths = _default_paths(item.paths)
    with _lock(paths, cfg):
        cur = _reload(QueueItem.at(paths, item.name, item.folder, item.meta)) if item.name else None
        if cur is None or cur.folder != "pending" or cur.state not in SENDABLE:
            out = cur or item
            out.rc, out.message = 4, "보낼 수 있는 상태가 아닙니다(보냄·실패·치움·내보냄)"
            return out
        if cur.meta.get("blockers"):
            cur.rc, cur.message = 2, "막힌 묶음은 보낼 수 없습니다: " + "; ".join(map(str, cur.meta["blockers"]))
            return cur
        if mask_gaps(cur):                               # 가림을 바꾼 뒤 다시 만들지 않은 바이트 — 보내지 않고 승인을 푼다
            if cur.meta.get("approved"):
                _unapprove(cur, now, "mask_changed")
            cur.rc, cur.message = 2, STALE_MASK
            return cur
        if not _lease_take(cur, now):
            cur.rc, cur.message = 4, "다른 곳에서 이 묶음을 보내는 중입니다"
            return cur
        if approve and not cur.meta.get("approved"):
            cur.meta["approved"], cur.meta["approved_at"] = True, _ts(now)
            _history(cur.meta, now, "approved")
        cur.meta["state"] = "sending"
        _write_meta(cur)
    try:
        return _send(cur, cfg, now, picked, hello_fn)
    finally:
        _remove_quiet(_ofile(paths, cur.folder, cur.name + LEASE_SUFFIX))


def _send(cur: QueueItem, cfg, now: datetime, picked, hello_fn) -> QueueItem:
    from lm27 import LM27_VERSION
    from lm27.team import client as C
    paths = cur.paths
    raw = fsx.read_bytes(cur.path)
    sha = cur.sha256
    if fsx.sha256_hex(raw) != sha:
        return mark(cur, "failed", "묶음 파일이 미리보기 이후 바뀌었습니다 — 다시 만드세요", now=now, rc=1)
    token = C.upload_token(paths)
    fp = {"targets": _targets_fp(cfg), "token": C.token_fp(token)}
    tgt, h, pick = picked if picked is not None else C.pick_target(cfg, hello_fn=hello_fn)
    if tgt is None:
        if pick.version_mismatch:
            return mark(cur, "failed", C.TEXT_KO["wrong_major"], now=now, rc=1, extra={"fp": fp})
        if pick.all_unreachable:
            return _retry(cur, cfg, now, "이 망에서 팀 서버에 닿지 않습니다(" + pick.describe_ko() +
                          ") — 묶음은 그대로 대기합니다", fp)
        return mark(cur, "wrong_server", pick.describe_ko(), now=now, rc=2, extra={"fp": fp})
    if h.auth_upload and not token:
        return mark(cur, "auth_needed", "팀 서버가 업로드 토큰을 요구합니다 — 설정 > 팀 서버 > 토큰", now=now, rc=2,
                    extra={"fp": fp, "last_target": tgt.name})
    hdr = {"Content-Type": "application/json; charset=utf-8", C.SHA_HEADER: sha, C.CLIENT_HEADER: LM27_VERSION,
           C.SENT_HEADER: _ts(now)}
    if token:
        hdr[C.TOKEN_HEADER] = token
    r = C.http_post(tgt.base + "/api/bundles", raw, hdr, float(cfg["team.uploadTimeoutSec"]),
                    proxy=bool(cfg["team.useSystemProxy"]))
    extra = {"fp": fp, "last_target": tgt.name}
    body = r.obj or {}
    st = r.status
    if st == 200:
        if str(body.get("sha256") or "").lower() == sha:
            msg = {"stored": "팀 서버에 보냈습니다", "already_have": "팀 서버에 이미 있는 묶음입니다(같은 바이트)",
                   "stale_kept": "팀 서버에 더 새 묶음이 있어 보관만 했습니다"}.get(str(body.get("status")), "팀 서버에 보냈습니다")
            extra["server_status"] = str(body.get("status") or "")
            return mark(cur, "sent", msg, now=now, rc=0, extra=extra)
        return _retry(cur, cfg, now, "팀 서버가 받은 바이트가 다릅니다 — 다시 보냅니다", fp)
    if st is None or st in (408, 429) or st >= 500:
        why = C.TEXT_KO.get(r.error or "", "") or (f"팀 서버가 바쁩니다(HTTP {st}) — 잠시 뒤 다시 보냅니다" if st else
                                                   "팀 서버에 보내지 못했습니다")
        return _retry(cur, cfg, now, why, fp)
    err = f"팀 서버가 거절했습니다({body.get('code') or st}): {str(body.get('error') or '')[:120]}"
    detail = [str(x)[:120] for x in (body.get("detail") or ())][:20]
    if st == 401:
        return mark(cur, "auth_needed", err + " — 설정 > 팀 서버 > 토큰", now=now, rc=2, extra=extra)
    if st in (404, 410):
        return mark(cur, "wrong_server", err, now=now, rc=2, extra=extra)
    extra["reject_detail"] = detail
    return mark(cur, "failed", err + " — [다시 만들기]가 필요합니다", now=now, rc=1, extra=extra)


@dataclass
class SendResult:
    """``send_due`` 결과 — rc(계약 §8.3 `team send`): 0 보냄 · 2 다시 시도 대기·인증 필요·다른 서버 · 1 실패 · 4 할 일 없음."""
    rc: int = 4
    sent: int = 0
    retry: int = 0
    failed: int = 0
    auth_needed: int = 0
    wrong_server: int = 0
    delivered: int = 0
    waiting: int = 0
    skipped: int = 0
    items: list = field(default_factory=list)
    message: str = ""


def _due(it: QueueItem, cfg, now: datetime, trigger: str, fp_now: dict, auto: bool) -> bool:
    m = it.meta
    if it.folder != "pending" or it.state not in SENDABLE or m.get("blockers"):
        return False
    if not (m.get("approved") or auto):
        return False
    fp = m.get("fp") if isinstance(m.get("fp"), dict) else {}
    if it.state == "retry_wait" and trigger in ("timer", "build"):
        na = _parse_ts(m.get("next_at"))
        if na is not None and na > now:
            return False
    if it.state == "auth_needed" and trigger != "manual" and (not fp_now["token"] or fp.get("token") == fp_now["token"]):
        return False
    if it.state == "wrong_server" and trigger != "manual" and fp.get("targets") == fp_now["targets"]:
        return False
    return True


def send_due(cfg, *, paths=None, now=None, trigger: str = "manual", only=None, hello_fn=None) -> SendResult:
    """승인된 대기분 보내기(TAB §2.8) — cli ``team send``·[수집] 끝(trigger="collect")·화면 기동("startup")·15분마다
    ("timer")·빌드 직후("build"). 대상은 한 번만 고른다(hello). [수집]·기동에서 안 닿으면 시도 횟수를 올리지 않는다.
    오프라인으로 내보낸 항목은 닿는 서버의 ``/api/members`` 로 '전달 확인'을 맞춘다(O05)."""
    from lm27.team import client as C
    if trigger not in TRIGGERS:
        raise ValueError(f"trigger 는 {TRIGGERS} 중 하나")
    paths = _default_paths(paths)
    now = _now(now)
    res = SendResult()
    items = [it for it in list_items(paths=paths) if it.folder == "pending"]
    if only:
        names = set(only)
        items = [it for it in items if it.name in names]
    auto = bool(cfg["team.autoSend"])
    token = C.upload_token(paths)
    fp_now = {"targets": _targets_fp(cfg), "token": C.token_fp(token)}
    due = [it for it in items if _due(it, cfg, now, trigger, fp_now, auto)]
    stale = [it for it in due if mask_gaps(it)]          # 가림을 바꾼 뒤 다시 만들지 않은 묶음은 보내지 않는다(C16)
    due = [it for it in due if it not in stale]
    res.skipped = sum(1 for it in items if it.state in SENDABLE and it not in due)
    waiting_ok = sum(1 for it in items if it.state in SENDABLE and not it.meta.get("blockers")
                     and not (it.meta.get("approved") or auto))
    exported = [it for it in items if it.state == "exported"]
    if not due and not exported:
        prune_sent(paths, int(cfg["team.sentKeep"]))
        if stale:
            res.rc, res.message = 2, f"가림을 바꾼 팀 묶음 {len(stale)}개는 다시 만들어야 보냅니다 — [팀 묶음 만들기]를 누르세요"
        elif waiting_ok:
            res.rc, res.message = 2, f"승인을 기다리는 팀 묶음 {waiting_ok}개 — 미리보기에서 [보내기]를 누르세요"
        else:
            res.rc, res.message = 4, "보낼 묶음이 없습니다"
        return _said(res)
    picked = C.pick_target(cfg, hello_fn=hello_fn)
    tgt, h, pick = picked
    if exported and tgt is not None:
        r = C.fetch_members(tgt.base, timeout=float(cfg["team.connectTimeoutSec"]),
                            token=token if h.auth_read else None, proxy=bool(cfg["team.useSystemProxy"]))
        if r.status == 200 and isinstance(r.obj, dict):
            res.delivered = reconcile_delivered(r.obj, paths=paths, now=now)
    if tgt is None and pick.all_unreachable and trigger in ("collect", "startup"):
        res.waiting = len(due)
        res.rc = 2 if due else (0 if res.delivered else 4)
        res.message = "이 망에서 팀 서버에 닿지 않아 다음 계기에 다시 보냅니다(시도 횟수는 그대로)"
        return _said(res)
    for it in due:
        out = send_item(it, cfg, now=now, approve=False, picked=picked)
        res.items.append({"name": out.name, "state": out.state, "message": out.message})
        st = out.state
        if st == "sent":
            res.sent += 1
        elif st == "retry_wait":
            res.retry += 1
        elif st == "failed":
            res.failed += 1
        elif st == "auth_needed":
            res.auth_needed += 1
        elif st == "wrong_server":
            res.wrong_server += 1
    prune_sent(paths, int(cfg["team.sentKeep"]))
    if res.failed:
        res.rc = 1
    elif res.retry or res.auth_needed or res.wrong_server:
        res.rc = 2
    elif res.sent or res.delivered:
        res.rc = 0
    else:
        res.rc = 4
    res.message = (f"보냄 {res.sent} · 다시 시도 대기 {res.retry} · 실패 {res.failed} · 인증 필요 {res.auth_needed} · "
                   f"다른 서버 {res.wrong_server} · 전달 확인 {res.delivered}")
    return _said(res)


def _said(res):
    """사람용 한 줄(계약 §8.6 — text 모드 stderr · jsonl 모드 이벤트). 값·주소 없이 결과 문구만."""
    from lm27.util import events
    events.emit("warn" if res.rc in (1, 2) else "msg", text_ko=res.message or "팀 묶음 전송")
    return res


def reconcile_delivered(members, *, paths=None, now=None) -> int:
    """TAB §3.11 · §5.1 — 내보낸(exported) 항목 중 서버 ``/api/members`` 의 내 person_key(연결 키 포함) 기간 sha12 와 같은
    것을 ``delivered`` 로. 반환 = 바꾼 수."""
    paths = _default_paths(paths)
    shas: dict = {}
    for mem in (members or {}).get("members") or ():
        if not isinstance(mem, dict):
            continue
        keys = [mem.get("person_key"), *(mem.get("linked") or ())]
        got = {str(p.get("sha12")) for p in mem.get("periods") or () if isinstance(p, dict) and p.get("sha12")}
        for k in keys:
            if isinstance(k, str):
                shas.setdefault(k, set()).update(got)
    n = 0
    for it in list_items(paths=paths):
        if it.state == "exported" and it.sha256[:12] in shas.get(str(it.meta.get("person_key") or ""), set()):
            mark(it, "delivered", "팀 서버 반영을 확인했습니다", now=now)
            n += 1
    return n


def prune_sent(paths, keep: int) -> int:
    """sent·dropped 폴더는 최근 ``team.sentKeep`` 개만 남긴다(본문·meta 함께). 반환 = 지운 항목 수."""
    gone = 0
    for folder in ("sent", "dropped"):
        its = [it for it in list_items(paths=paths) if it.folder == folder]
        its.sort(key=lambda it: (str(it.meta.get("sent_at") or it.meta.get("delivered_at") or ""),
                                 str((it.meta.get("history") or [{}])[-1].get("at") or ""), it.name), reverse=True)
        for it in its[max(0, int(keep)):]:
            for suffix in ("", META_SUFFIX, LEASE_SUFFIX):
                _remove_quiet(_ofile(paths, folder, it.name + suffix))
            gone += 1
    return gone
