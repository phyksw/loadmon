# -*- coding: utf-8 -*-
r"""에이전트 로컬 원장 → 번들 세그먼트 내보내기(계약 §2.6, TAB §1.7 ③) — ``export_agent_streams(pcdir, ident, cfg)``.

  · 커서는 번들 쪽(그 PC 의 manifest ``cursors[install_id]["<kind>/<src>"] = {file, offset, last_ts}``)에 둔다 — 사본
    번들이 둘이면 각자 받지 못한 분량을 내보내야 하기 때문이다. 시각 커서는 늦게 수확된 과거 사건을 놓치므로 쓰지 않는다.
  · 읽기는 ``lm27.store.reader.read_store_since(paths, pc_id, kind, src, cursor) -> (records, new_cursor, gap|None)``
    (완전한 gzip 멤버까지만, 일자 파일 경계를 넘어 쓰기 순서대로 — WP-11). 시험은 ``reader=`` 로 가짜를 넣는다.
  · 순서: 고아 편입(``adopt_orphans``) → 흐름마다 읽기 → (선택) 재정제 훅 → ``anchor_since`` 이전 흔적 제외 →
    로컬 달·크기로 나눠 ``write_segment`` → 커서 전진 → 모두 끝난 뒤 manifest 를 한 번 저장(2단계). 중간에 죽으면
    다음 내보내기의 고아 편입이 마지막 묶음의 ``src_to`` 로 커서를 맞춘다(앞 묶음만 남았으면 커서는 그대로 → 다시 읽고
    같은 id 는 로더가 접는다).
  · 정제 감사 ``privacy_audit/agent``: 이벤트 본문(P §15.2)에 봉투 ``id = sha256(canon_bytes(이벤트))[:16]`` ·
    ``kind = privacy_audit`` · ``src = 단계 이름``(agent) 을 붙인다(계약 §3.13).
  · 그 PC 자기 폴더에만 쓴다(pcdir 이름 = ident.pc_id). 번들 잠금을 쥔 채로 부른다(호출자 책임 — 보통 ``lock("export")``).
"""
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lm27.bundle import manifest as mf
from lm27.bundle import segment as seg
from lm27.util import fsx

AGENT_STREAMS = ("pc_session/pc.sampler", "pc_session/pc.events", "pc_file/pc.files", "pc_file/pc.mru",
                 "pc_file/pc.recent", "pc_compute/pc.compute", "teams/teams.uia", "privacy_audit/agent")
AUDIT_KIND = "privacy_audit"
AUDIT_STAGES = ("agent", "collect", "load", "copilot", "team")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_VER_RX = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,3}$")
_KID_RX = re.compile(r"^k[0-9a-f]{8}$")
UNKNOWN_RULES_VER = "0.0.0"
UNKNOWN_KID = "k00000000"


@dataclass
class ExportResult:
    """``rc`` 0 = 새 레코드 있음 · 4 = 새것 없음. ``new`` = kind 별 새 레코드 수."""
    rc: int = 4
    pc_id: str = ""
    install_id: str = ""
    new: dict = field(default_factory=dict)
    segments: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    adopted: int = 0
    skipped: dict = field(default_factory=dict)
    manifest_gen: int = 0
    saved: bool = False
    collision: bool = False
    notes: list = field(default_factory=list)


def agent_streams(ident=None, manifest=None) -> list:
    """내보낼 흐름 ``<kind>/<src>`` — 고정 목록 ∪ 이 설치의 manifest 커서에 이미 있는 흐름(정렬)."""
    out = set(AGENT_STREAMS)
    if manifest is not None and ident is not None:
        out |= {k for k in (manifest.get("cursors", {}).get(ident.install_id) or {}) if isinstance(k, str) and "/" in k}
    return sorted(out)


def _paths_of(pcdir: Path):
    from lm27.paths import Paths
    return Paths(pcdir.parents[2])


def _default_reader():
    from lm27.store.reader import read_store_since          # WP-11 — 없으면 ImportError 그대로(삼키지 않는다)
    return read_store_since


def _vt(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def _head_ver_kid(rows):
    vers = [r.get("rules_ver") for r in rows if isinstance(r.get("rules_ver"), str) and _VER_RX.match(r["rules_ver"])]
    kids = Counter(r.get("kid") for r in rows if isinstance(r.get("kid"), str) and _KID_RX.match(r["kid"]))
    rv = max(vers, key=_vt) if vers else UNKNOWN_RULES_VER
    kid = sorted(kids.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if kids else UNKNOWN_KID
    return rv, kid


def audit_envelope(ev: dict) -> dict:
    """감사 이벤트 → 세그먼트 행(봉투 id·kind·src). id 는 봉투를 붙이기 전 이벤트의 정규 바이트로 계산(재내보내도 같다)."""
    body = dict(ev)
    row = dict(body)
    row["id"] = fsx.sha256_hex(fsx.canon_bytes(body))[:16]
    row["kind"] = AUDIT_KIND
    st = body.get("stage")
    row["src"] = st if st in AUDIT_STAGES else "agent"
    return row


def _dedupe_batch(rows):
    """한 묶음 안 같은 id 는 observed_at 최대(같으면 나중 줄) 하나 — 진행 중 구간의 새 판(X-032)."""
    best, order = {}, {}
    for i, r in enumerate(rows):
        k = r["id"]
        cur = best.get(k)
        if cur is None or str(r.get("observed_at") or "") >= str(cur.get("observed_at") or ""):
            best[k] = r
            order.setdefault(k, i)
    return [best[k] for k in sorted(best, key=lambda k: order[k])]


def _first_seen_install(paths, ident, now):
    aj = fsx.read_json(paths.agent_json(), None, want=dict) or {}
    if aj.get("install_id") == ident.install_id and isinstance(aj.get("installed_at"), str) \
            and _UTC_RX.match(aj["installed_at"]):
        return aj["installed_at"]
    return now


def _agent_status(paths, ident, now):
    hb = fsx.read_json(paths.heartbeat(), None, want=dict)
    if not hb or hb.get("install_id") != ident.install_id:
        return None
    return {"install_id": ident.install_id, "impl": hb.get("impl"), "last_tick": hb.get("last_tick"),
            "healthy": None, "checked_at": now}


def export_agent_streams(pcdir, ident, cfg, *, paths=None, reader=None, resanitize=None, streams=None, now=None,
                         created=None, agent_status=None) -> ExportResult:
    """store → 세그먼트(커서 이후분). ``resanitize(kind, row) -> row|None`` = 재정제 훅(현재 규칙, 단조 — P §10.5),
    ``agent_status`` = 생존 판정 결과(dict, 주면 manifest 에 남김). 반환 ``ExportResult``."""
    pcdir = Path(pcdir)
    if pcdir.name != ident.pc_id or not _PC_RX.match(ident.pc_id):
        raise ValueError("export_agent_streams: 자기 pc_id 폴더에만 씁니다")
    paths = paths if paths is not None else _paths_of(pcdir)
    if os.path.normcase(os.path.abspath(paths.pc_dir(ident.pc_id))) != os.path.normcase(os.path.abspath(pcdir)):
        raise ValueError("export_agent_streams: pcdir 이 paths 의 번들 밖입니다")
    rd = reader if reader is not None else _default_reader()
    now = now or fsx.utcnow_iso()
    res = ExportResult(pc_id=ident.pc_id, install_id=ident.install_id)
    fsx.ensure_dir(pcdir)
    m = mf.load_manifest(pcdir, quarantine=True, notes=res.notes)
    before = mf.manifest_body(m)
    res.adopted = mf.adopt_orphans(pcdir, m, quarantine=True, now=now)
    from lm27.bundle import pcreg
    pc = pcreg.load_pc(pcdir) or {}
    anchor = pc.get("anchor_since") if isinstance(pc.get("anchor_since"), str) else ""
    skipped = Counter()
    for stream in (streams if streams is not None else agent_streams(ident, m)):
        kind, src = stream.split("/", 1)
        cur = (m.get("cursors", {}).get(ident.install_id) or {}).get(stream)
        recs, new_cur, gap = rd(paths, ident.pc_id, kind, src, cur)
        if gap:
            g = {"install_id": ident.install_id, "stream": stream, "from_t": gap.get("from_t"),
                 "to_t": gap.get("to_t"), "reason": gap.get("reason") or "store_pruned"}
            if g not in m["gaps"]:
                m["gaps"].append(g)
                res.gaps.append(g)
        rows = []
        for r in recs or ():
            if not isinstance(r, dict):
                skipped["bad_row"] += 1
                continue
            if kind == AUDIT_KIND:
                if r.get("pc_id") != ident.pc_id or not _UTC_RX.match(str(r.get("ts_utc"))):
                    skipped["foreign"] += 1
                    continue
                rows.append(audit_envelope(r))
                continue
            if r.get("kind") != kind or r.get("pc_id") != ident.pc_id or not _UTC_RX.match(str(r.get("ts_utc"))):
                skipped["foreign"] += 1
                continue
            if any(isinstance(k, str) and k.startswith("_") for k in r):
                r = {k: v for k, v in r.items() if not (isinstance(k, str) and k.startswith("_"))}
            if resanitize is not None:
                r = resanitize(kind, r)
                if r is None:
                    skipped["dropped"] += 1
                    continue
            if anchor and r["ts_utc"] < anchor:
                skipped["before_anchor"] += 1
                continue
            rows.append(r)
        rows = _dedupe_batch(rows)
        chunks = seg.split_records(rows, cfg)
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            rv, kid = _head_ver_kid(chunk)
            info = seg.write_segment(pcdir, kind, ident, chunk, rules_ver=rv, kid=kid,
                                     src_from={src: cur}, src_to={src: new_cur} if last else None,
                                     created=created or now, manifest=m)
            if not any(s.get("sha256") == info["sha256"] for s in m["segments"]):
                m["segments"].append(info)
                res.segments.append(info)
                res.new[kind] = res.new.get(kind, 0) + info["n"]
        if new_cur is not None:
            mf.advance_cursor(m, ident.install_id, stream, new_cur)
    m["observed_from"].setdefault(ident.install_id, _first_seen_install(paths, ident, now))
    st = agent_status if agent_status is not None else _agent_status(paths, ident, now)
    if st is not None:
        m["agent_status"] = st
    res.skipped = dict(skipped)
    if m.get("_recovered") or mf.manifest_body(m) != before:      # 복구한 목록은 그 PC 의 쓰기 주체가 저장한다
        mf.save_manifest(pcdir, m, now=now)
        res.saved = True
    res.manifest_gen = int(m.get("gen") or 0)
    res.collision = pcreg.mark_collisions(pcdir, manifest=m)
    res.rc = 0 if res.new else 4
    _log_export(paths, ident, res, now)
    return res


def _log_export(paths, ident, res, now) -> None:
    """에이전트 쪽 ``export_log.jsonl``(진단용 — 판단 근거 아님). 못 써도 내보내기는 성공이다."""
    line = fsx.canon_bytes({"at": now, "pc_id": ident.pc_id, "install_id": ident.install_id,
                            "gen": res.manifest_gen, "new": res.new, "gaps": len(res.gaps)}).decode("utf-8")
    try:
        fsx.append_line(paths.export_log(), line)
    except OSError:
        res.notes.append({"code": "export_log_unwritable"})
