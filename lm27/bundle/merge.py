# -*- coding: utf-8 -*-
r"""사본 분기 번들 합치기·소급 가림 재작성(계약 §2.6, TAB §1.13·§1.14, P §12.5).

``merge_bundle(paths, other_data_dir) -> MergeResult``
  · 폴더를 이동이 아니라 복사해 두 곳에서 쓰면 번들이 갈라진다. 두 ``bundle.json`` 의 ``person_key`` 가 다르면 거부.
  · 상대 쪽은 **읽기만** 한다. 이쪽은 ``BundleLock("merge")`` 를 쥐고:
    ① 상대 ``pcs\<pc_id>\`` 마다 — 상대 manifest 의 세그먼트 중 **이쪽에 같은 sha 가 없고 양쪽 어느 무덤표에도 없는
       것만** 복사(이름에 sha·install 이 있어 충돌 없음). 이쪽에 없는 pc_id 는 pc.json·manifest 까지 들인다. 둘 다 있으면
       ``adopt_orphans`` 로 편입하고 커서는 (install, 흐름) 별 더 앞선 쪽, ``observed_from`` 은 더 이른 값, 무덤표·gaps 는
       합집합, pc.json 의 installs·visits·capabilities.*.history 는 합집합.
    ② ``pc_aliases.json`` 결정 합집합 ③ ``outbox\team\*`` sha 기준 합집합(같은 sha 는 하나)
    ④ ``data\ai\store\<stage>.items.jsonl`` 커밋 합집합 — 같은 줄은 하나, ts 순으로 정렬해 (stage, ck) 별 마지막 줄이
       최신 커밋이 되게(B §7.8 접기).
  · 키링(``data\keys\``)은 정제 명세의 ``load_keyring`` 병합 규칙 소관이라 여기서 손대지 않는다. 파생물(``derived\``)은
    호출자가 다시 만든다(``MergeResult.derived_stale``).
  · 결과는 몇 번을 다시 해도 같다(sha 집합 합집합 — 두 번째는 쓰기 0, T-12·TAB B18).

``redact_rewrite_own(pcdir)`` — 소급 가림의 번들 쪽 절차(자기 pc_id 세그먼트만, ``BundleLock("redact")`` 안에서):
  ``local_only\redact_overlay.json`` 에 걸리는 행의 텍스트 열만 비운 새 세그먼트를 **같은 seq** 로 쓰고(머리말
  ``redacted_from`` = 옛 sha) → manifest 항목 교체 + 무덤표(``quarantine\tombstones.json`` 사본 포함) → 저장 → 옛 파일 삭제.
  행 수·id·키·시간 열은 그대로다. 다른 PC 세그먼트는 그 PC 에서 같은 절차가 돌 때 지워지며, 그 전까지는 로더의 읽기
  오버레이가 가린다.
"""
import os
import re
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lm27.bundle import manifest as mf
from lm27.bundle import segment as seg
from lm27.util import fsx

_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_OUTBOX_RX = re.compile(r"^lm27_team_bundle_[0-9A-Za-z_\-]+_([0-9a-f]{12})(?:\.json|\.meta\.json|\.json\.meta\.json)$")
_STAGE_FILE_RX = re.compile(r"^([a-z][a-z0-9_]{0,47})\.items\.jsonl$")
OUTBOX_STATES = ("pending", "sent", "failed", "dropped")
HISTORY_MAX = 30
VISITS_MAX = 200
_SegIdent = namedtuple("_SegIdent", "pc_id install_id agent_ver")   # 재작성 세그먼트의 머리말 신원(옛 머리말 그대로)


@dataclass
class MergeResult:
    """``rc`` 0 = 들인 것 있음 · 4 = 바뀐 것 없음 · 2 = 거부(다른 사람·번들 아님)."""
    rc: int = 4
    reason: str = ""
    pcs_added: list = field(default_factory=list)
    segments_copied: int = 0
    segments_skipped_tombstoned: int = 0
    segments_skipped_corrupt: int = 0
    manifests_saved: int = 0
    pc_json_saved: int = 0
    aliases_added: int = 0
    outbox_added: int = 0
    ai_lines_added: int = 0
    bundle_json_adopted: bool = False
    derived_stale: bool = False
    notes: list = field(default_factory=list)


def _other_paths(other, cls=None):
    r"""상대 위치 → Paths(이쪽과 같은 경로 규칙 클래스). ``data\`` 폴더(``bundle.json`` 이 든 곳) 또는 그 위 프로그램
    폴더를 받는다."""
    if cls is None:
        from lm27.paths import Paths as cls
    p = Path(os.path.abspath(os.fspath(other)))
    cand = cls(p)
    if os.path.isfile(fsx.longp(cand.bundle_json())):
        return cand
    if p.name.lower() == "data":
        cand = cls(p.parent)
        if os.path.isfile(fsx.longp(cand.bundle_json())):
            return cand
    return None


def _same(a, b) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _write_if_changed(path, data: bytes) -> bool:
    try:
        if fsx.read_bytes(path) == data:
            return False
    except FileNotFoundError:
        pass
    fsx.atomic_write(path, data)
    return True


def _cursor_merge(mine: dict, other: dict) -> None:
    for inst, per in sorted((other.get("cursors") or {}).items()):
        if not isinstance(per, dict):
            continue
        for stream, cur in sorted(per.items()):
            mf.advance_cursor(mine, inst, stream, cur)


def _union_list(a, b, key=None) -> list:
    out, seen = [], set()
    for x in list(a or []) + list(b or []):
        k = fsx.canon_bytes(key(x) if key else x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _merge_manifest_meta(mine: dict, other: dict) -> None:
    _cursor_merge(mine, other)
    of = mine.setdefault("observed_from", {})
    for inst, t in (other.get("observed_from") or {}).items():
        if isinstance(t, str) and (inst not in of or t < of[inst]):
            of[inst] = t
    mine["gaps"] = _union_list(mine.get("gaps"), other.get("gaps"))
    mine["tombstones"] = _union_list(mine.get("tombstones"), other.get("tombstones"),
                                     key=lambda t: t.get("old_sha256") if isinstance(t, dict) else t)
    sa, sb = mine.get("agent_status"), other.get("agent_status")
    if isinstance(sb, dict) and (not isinstance(sa, dict) or str(sb.get("checked_at") or "") >
                                 str(sa.get("checked_at") or "")):
        mine["agent_status"] = sb


def _merge_pc_json(mine, other) -> dict:
    """installs·visits·capabilities.*.history 합집합. 그 밖 필드는 이쪽 값(없으면 상대 값)."""
    if not isinstance(mine, dict):
        return other
    out = dict(mine)
    for k, v in other.items():
        out.setdefault(k, v)
    out["installs"] = _union_list(mine.get("installs"), other.get("installs"),
                                  key=lambda e: e.get("install_id") if isinstance(e, dict) else e)
    vis = _union_list(mine.get("visits"), other.get("visits"),
                      key=lambda e: [e.get("at"), e.get("install_id")] if isinstance(e, dict) else e)
    out["visits"] = sorted(vis, key=lambda e: str(e.get("at") if isinstance(e, dict) else ""))[-VISITS_MAX:]
    out["flags"] = sorted(set(mine.get("flags") or []) | set(other.get("flags") or []))
    caps = dict(mine.get("capabilities") or {})
    for key, ent in (other.get("capabilities") or {}).items():
        if not isinstance(ent, dict):
            continue
        if key not in caps or not isinstance(caps[key], dict):
            caps[key] = ent
            continue
        a = dict(caps[key])
        hist = _union_list(a.get("history"), ent.get("history"))
        hist = sorted(hist, key=lambda h: str(h.get("date") if isinstance(h, dict) else ""))
        # 버린 수: 두 쪽 기록과 이번 넘침 중 큰 값(다시 합쳐도 늘지 않게 — 멱등)
        dropped = max(int(a.get("history_dropped") or 0), int(ent.get("history_dropped") or 0),
                      len(hist) - HISTORY_MAX)
        hist = hist[-HISTORY_MAX:]
        if dropped > 0:
            a["history_dropped"] = dropped
        if hist != a.get("history"):
            from lm27.bundle.pcreg import verdict
            a["history"] = hist
            a["verdict"] = verdict(hist)
        caps[key] = a
    out["capabilities"] = caps
    for k in ("first_seen", "anchor_since"):
        if isinstance(other.get(k), str) and isinstance(mine.get(k), str):
            out[k] = min(mine[k], other[k])
    if isinstance(other.get("last_seen"), str) and isinstance(mine.get("last_seen"), str):
        out["last_seen"] = max(mine["last_seen"], other["last_seen"])
    return out


def _copy_segment(src_pcdir, dst_pcdir, s, res) -> bool:
    rel = str(s.get("file") or "")
    if not rel.startswith("seg/") or not seg.parse_segment_name(os.path.basename(rel)):
        res.segments_skipped_corrupt += 1
        return False
    try:
        data = fsx.read_bytes(Path(src_pcdir).joinpath(*rel.split("/")))
    except OSError:
        res.segments_skipped_corrupt += 1
        res.notes.append({"code": "source_missing", "file": rel})
        return False
    if fsx.sha256_hex(data) != s.get("sha256"):
        res.segments_skipped_corrupt += 1
        res.notes.append({"code": "source_sha_mismatch", "file": rel})
        return False
    dst = Path(dst_pcdir).joinpath(*rel.split("/"))
    if os.path.exists(fsx.longp(dst)):
        if fsx.sha256_hex(fsx.read_bytes(dst)) == s.get("sha256"):
            return False
        res.notes.append({"code": "name_conflict", "file": rel})
        return False
    fsx.atomic_write(dst, data)
    res.segments_copied += 1
    return True


def _merge_pc(paths, op, pid, dead_all, res) -> None:
    src_dir, dst_dir = op.pc_dir(pid), paths.pc_dir(pid)
    om = mf.load_manifest(src_dir, quarantine=False)
    dead = dead_all | mf.tombstoned_shas(om)
    new_pc = not os.path.isdir(fsx.longp(dst_dir))
    mine = mf.new_manifest(pid) if new_pc else mf.load_manifest(dst_dir, quarantine=False)
    dead |= mf.tombstoned_shas(mine)
    have = {s.get("sha256") for s in mine["segments"]}
    before = mf.manifest_body(mine) if not new_pc else b""
    for s in sorted(om["segments"], key=lambda x: (str(x.get("kind")), x.get("seq") or 0, str(x.get("file")))):
        sha = s.get("sha256")
        if sha in have:
            continue
        if sha in dead:
            res.segments_skipped_tombstoned += 1
            continue
        _copy_segment(src_dir, dst_dir, s, res)
    mf.adopt_orphans(dst_dir, mine, quarantine=False)
    _merge_manifest_meta(mine, om)
    if new_pc or mf.manifest_body(mine) != before:
        fsx.ensure_dir(dst_dir)
        if new_pc:
            mine["gen"] = int(om.get("gen") or 0)
        mf.save_manifest(dst_dir, mine)
        res.manifests_saved += 1
        if mine.get("tombstones"):
            mf.write_tomb_copy(dst_dir, mine["tombstones"])
    from lm27.bundle import pcreg
    opc = pcreg.load_pc(src_dir)
    if opc:
        merged = _merge_pc_json(pcreg.load_pc(dst_dir), opc)
        if pcreg.save_pc(dst_dir, merged):
            res.pc_json_saved += 1
    if new_pc:
        res.pcs_added.append(pid)
        mr = fsx.read_json(op.move_ready(pid), None, want=dict)
        if mr and mr.get("pc_id") == pid:
            _write_if_changed(paths.move_ready(pid), fsx.canon_bytes(mr))


def _merge_aliases(paths, op, res) -> None:
    from lm27.bundle import aliases
    a, b = aliases.load_aliases(paths), aliases.load_aliases(op)
    merged = _union_list(a["decisions"], b["decisions"])
    add = len(merged) - len(a["decisions"])
    if add:
        aliases.save_aliases(paths, {"decisions": merged})
        res.aliases_added += add


def _outbox_files(p) -> dict:
    """outbox 의 sha12 → (상태, [파일 이름…]) — 같은 sha 가 여러 상태에 있으면 상태 순서상 앞의 것 하나."""
    out = {}
    for st in OUTBOX_STATES:
        try:
            names = sorted(os.listdir(fsx.longp(p.outbox(st))))
        except (FileNotFoundError, NotADirectoryError):
            continue
        per = {}
        for n in names:
            m = _OUTBOX_RX.match(n)
            if m:
                per.setdefault(m.group(1), []).append(n)
        for sha, files in per.items():
            out.setdefault(sha, (st, files))
    return out


def _outbox_file(p, state, name):
    r"""outbox 파일 경로 — ``Paths.outbox_file(state, name)``(계약 v1.2 §0.7 C19 — 경로 조립은 lm27.paths 에만, L-08)."""
    return p.outbox_file(state, name)


def _merge_outbox(paths, op, res) -> None:
    mine = _outbox_files(paths)
    todo = [(sha, st, files) for sha, (st, files) in sorted(_outbox_files(op).items()) if sha not in mine]
    if not todo:
        return
    for sha, st, files in todo:
        body = [n for n in files if not n.endswith(".meta.json")]
        if not body:
            continue                                   # 묶음 본문 없이 메타만 있으면 들이지 않는다
        blobs = {n: fsx.read_bytes(_outbox_file(op, st, n)) for n in files}
        if any(fsx.sha256_hex(blobs[n])[:12] != sha for n in body):
            res.notes.append({"code": "outbox_sha_mismatch", "sha12": sha})
            continue
        for n in files:
            if _write_if_changed(_outbox_file(paths, st, n), blobs[n]):
                res.outbox_added += 1


def _ts_key(line_obj):
    ts = line_obj.get("ts") if isinstance(line_obj, dict) else None
    try:
        t = datetime.fromisoformat(str(ts))
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        return ""


def _read_lines(path) -> list:
    try:
        raw = fsx.read_bytes(path)
    except FileNotFoundError:
        return []
    out = []
    for ln in raw.decode("utf-8", "replace").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = fsx.loads_strict(ln)
        except ValueError:
            continue                                   # 끊긴 줄(torn) — 합치기 대상 아님
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _ai_store_dir(p):
    r"""``data\ai\store\`` — ``Paths.ai_store_dir()``(계약 v1.2 §0.7 C19)."""
    return p.ai_store_dir()


def _merge_ai_store(paths, op, res) -> None:
    d = _ai_store_dir(op)
    try:
        names = sorted(os.listdir(fsx.longp(d)))
    except (FileNotFoundError, NotADirectoryError):
        return
    for n in names:
        m = _STAGE_FILE_RX.match(n)
        if not m:
            continue
        stage = m.group(1)
        other = _read_lines(op.ai_store(stage))
        mine_path = paths.ai_store(stage)
        mine = _read_lines(mine_path)
        have = {fsx.canon_bytes(x) for x in mine}
        add = [x for x in other if fsx.canon_bytes(x) not in have]
        uniq = []
        for x in add:
            c = fsx.canon_bytes(x)
            if c not in have:
                have.add(c)
                uniq.append(x)
        if not uniq:
            continue
        allx = sorted(mine + uniq, key=lambda x: (_ts_key(x), str(x.get("rid") or ""), fsx.canon_bytes(x)))
        body = "".join(fsx.canon_bytes(x).decode("utf-8") + "\n" for x in allx).encode("utf-8")
        fsx.atomic_write(mine_path, body)
        res.ai_lines_added += len(uniq)


def merge_bundle(paths, other_data_dir, *, cfg=None, timeout_s=None) -> MergeResult:
    """다른 사본의 data 폴더(또는 그 프로그램 폴더)를 이 번들에 합집합으로 합친다. 상대는 읽기만 한다."""
    from lm27.bundle.lock import BundleLock
    res = MergeResult()
    op = _other_paths(other_data_dir, type(paths))
    if op is None:
        res.rc, res.reason = 2, "not_bundle"
        return res
    if _same(op.data(), paths.data()):
        res.rc, res.reason = 4, "same_bundle"
        return res
    ob = fsx.read_json(op.bundle_json(), None, want=dict)
    if not ob or not isinstance(ob.get("person_key"), str):
        res.rc, res.reason = 2, "not_bundle"
        return res
    if cfg is None and timeout_s is None:
        from lm27.bundle.loader import program_cfg
        cfg = program_cfg(paths, None)
    with BundleLock(paths, "merge", timeout_s, cfg=cfg):
        mb = fsx.read_json(paths.bundle_json(), None, want=dict)
        if mb and mb.get("person_key") != ob.get("person_key"):
            res.rc, res.reason = 2, "other_person"
            return res
        if not mb:
            fsx.atomic_write(paths.bundle_json(), fsx.canon_bytes(ob))
            res.bundle_json_adopted = True
        from lm27.bundle.loader import list_pc_ids
        mine_ids, other_ids = set(list_pc_ids(paths)), list_pc_ids(op)
        dead_all = set()
        for pid in sorted(mine_ids | set(other_ids)):
            for p in (paths, op):
                if os.path.isdir(fsx.longp(p.pc_dir(pid))):
                    dead_all |= mf.tombstoned_shas(mf.load_manifest(p.pc_dir(pid), quarantine=False))
        for pid in other_ids:
            _merge_pc(paths, op, pid, dead_all, res)
        _merge_aliases(paths, op, res)
        _merge_outbox(paths, op, res)
        _merge_ai_store(paths, op, res)
    changed = (res.segments_copied or res.pcs_added or res.manifests_saved or res.pc_json_saved
               or res.aliases_added or res.outbox_added or res.ai_lines_added or res.bundle_json_adopted)
    res.derived_stale = bool(changed)
    res.rc = 0 if changed else 4
    return res


# ── 소급 가림 재작성 ─────────────────────────────────────────────────────────
def _paths_of(pcdir: Path):
    from lm27.paths import Paths
    return Paths(pcdir.parents[2])


def redact_rewrite_own(pcdir, *, overlay=None, clear_row=None, now=None) -> dict:
    """자기 pc_id 세그먼트의 소급 가림을 디스크에 반영한다(번들 잠금 안에서 부른다).
    ``overlay`` = ``{"chat": {...}, "msg": [...]}``(기본 ``local_only\\redact_overlay.json``),
    ``clear_row(row) -> (row, changed)`` = 텍스트 열 비우기(기본 ``loader.blank_text`` = ``lm27.privacy.records.redact_row``
    — 비울 열 단일원 ``redact_fields(kind)``: 정제문 열 + act_cues, 계약 v1.2 §0.7 C11).
    반환 ``{rc, rewritten, rows_changed, segments}`` — rc 0 바꿈 · 4 할 일 없음."""
    from lm27.bundle import loader
    pcdir = Path(pcdir)
    if not _PC_RX.match(pcdir.name):
        raise ValueError("redact_rewrite_own: pcdir 이름이 pc_id 가 아닙니다")
    paths = _paths_of(pcdir)
    ov = overlay if overlay is not None else loader.load_overlay(paths)
    clear = clear_row or loader.blank_text
    out = {"rc": 4, "rewritten": 0, "rows_changed": 0, "segments": []}
    if not os.path.isdir(fsx.longp(pcdir)) or not (ov.get("chat") or ov.get("msg")):
        return out
    m = mf.load_manifest(pcdir, quarantine=True)
    dead = mf.tombstoned_shas(m)
    now = now or fsx.utcnow_iso()
    for s in sorted(m["segments"], key=lambda x: (str(x.get("kind")), x.get("seq") or 0)):
        if s.get("sha256") in dead or s.get("kind") not in ("mail", "cal", "teams"):
            continue
        old_path = pcdir.joinpath(*str(s["file"]).split("/"))
        try:
            head, recs = seg.read_segment_full(old_path, s.get("sha256"))
        except (OSError, seg.SegmentCorrupt):
            continue
        n_ch, new_recs = 0, []
        for r in recs:
            if loader.overlay_hit(r, ov):
                r2, ch = clear(r)
                if ch:
                    n_ch += 1
                    r = r2
            new_recs.append(r)
        if not n_ch:
            continue
        ident = _SegIdent(pcdir.name, head["install_id"], head.get("agent_ver"))
        info = seg.write_segment(pcdir, head["kind"], ident, new_recs, rules_ver=head.get("rules_ver"),
                                 kid=head.get("kid"), src_from=head.get("src_from"), src_to=head.get("src_to"),
                                 created=head.get("created"), seq=head["seq"], redacted_from=s["sha256"])
        m["segments"] = [x for x in m["segments"] if x.get("sha256") != s["sha256"]] + [info]
        mf.add_tombstone(m, seq=head["seq"], kind=head["kind"], old_sha256=s["sha256"],
                         new_sha256=info["sha256"], reason="redact", at=now, pcdir=pcdir)
        mf.save_manifest(pcdir, m, now=now)
        try:
            os.remove(fsx.longp(old_path))
        except OSError:
            out.setdefault("notes", []).append({"code": "old_segment_kept", "file": s["file"]})
        out["rewritten"] += 1
        out["rows_changed"] += n_ch
        out["segments"].append({"old": s["sha256"], "new": info["sha256"], "rows": n_ch})
    if out["rewritten"]:
        out["rc"] = 0
    return out
