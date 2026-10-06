# -*- coding: utf-8 -*-
r"""오프라인 대체(공유폴더·USB, TAB §5) — 내용·검증은 HTTP 와 완전히 같다(같은 ``ingest_bytes``).

클라이언트
  ``export_to_dir(item, folder)``   대기 항목의 정규 바이트를 폴더로(원자 쓰기 + 되읽기 sha 확인) → 상태 ``exported``.
  ``read_offline_registry(cfg)``     ``team.offlineDir\lm27_registry.json``(서버가 게시한 사본) — 형식만 보고 돌려준다.
서버
  ``scan_inboxes(store, cfg)``       ``<store>\inbox\``(성공 → done\, 실패 → rejected\ + 사유) + ``teamServer.inboxDirs``
                                     (남의 폴더 — 옮기거나 지우지 않고 ``run\inbox_seen.json`` 으로 한 번만).
  ``import_files(store, path, cfg)`` ``lm27 team-import`` — 저장소 잠금이 비면 직접 반입 + 재취합, 서버가 돌면 inbox 로 복사만.
  ``publish_registry(store, cfg)``   ``teamServer.publishDir\lm27_registry.json``(pepper 포함 — 그 폴더 권한 = pepper 권한).

원칙: 파일 이름은 ``fullmatch`` 화이트리스트(LM24 ``NAME_OK`` 의 ``$`` 개행 통과 결함 방어). 신원은 파일명이 아니라 본문의
person_key(대리 반입이어도 원저자 유지 — 본문을 고치지 않는다). 개인 보고서·원문·``data\keys\`` 는 내보내지 않는다.
"""
from __future__ import annotations

import os
import re
import time

from lm27.paths import OFFLINE_REGISTRY_NAME as REGISTRY_FILE   # 오프라인 사본 이름 단일원(계약 v1.2 C19)
from lm27.util import fsx

NAME_RX = re.compile(r"lm27_team_bundle(_[0-9A-Za-z_\-]{1,80})?\.json")
COPY_QUIET_SEC = 60                                  # 1분 이내 수정 = 복사 중 → 다음 회차
_FILE_ATTRIBUTE_HIDDEN = 0x2


class UserError(Exception):
    """사람에게 한국어 한 줄로 보일 오류(경로 오타·폴더 없음·바이트 불일치)."""


def _get(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def export_to_dir(item, folder, *, mark=None) -> str:
    """TAB §5.1 — 절대경로(또는 \\\\서버\\공유)만, 단일 파일 원자 쓰기, 되읽어 sha 확인. 반환: 쓴 파일 경로.
    ``item`` = 대기열 항목(``path`` · ``meta``). 상태 표시는 ``lm27.team.queue.mark(item, "exported", 문구)``(주입 가능)."""
    folder = os.path.expandvars(str(folder or "").strip().strip('"').strip("'"))
    if not os.path.isabs(folder):
        raise UserError("절대경로나 \\\\서버\\공유 형식이어야 합니다")
    if not os.path.isdir(fsx.longp(folder)):
        raise UserError("폴더가 없거나 이 망에서 닿지 않습니다")
    meta = _get(item, "meta") or {}
    want = str(meta.get("sha256") or "")
    raw = fsx.read_bytes(_get(item, "path"))
    if not want or fsx.sha256_hex(raw) != want:
        raise UserError("묶음 파일이 미리보기 이후 바뀌었습니다 — 다시 만드세요")
    pk, per = str(meta.get("person_key") or ""), str(meta.get("period_key") or "")
    if not re.fullmatch(r"p_[0-9a-f]{12}", pk) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}", per):
        raise UserError("대기 항목 정보가 깨졌습니다 — 다시 만드세요")
    name = f"lm27_team_bundle_{pk}_{per}_{want[:12]}.json"
    dst = os.path.join(folder, name)
    fsx.atomic_write(fsx.longp(dst), raw)                     # .part → replace: 반쪽 파일이 서버에 반입되지 않게
    if fsx.sha256_hex(fsx.read_bytes(fsx.longp(dst))) != want:
        raise UserError("저장 확인 실패 — 다시 시도하세요")
    if mark is None:
        from lm27.team.queue import mark                       # WP-34 대기열 상태 기계(계약 §2.15)
    mark(item, "exported", "공유폴더로 내보냈습니다 — 팀 서버 반영은 /api/members 로 확인합니다")
    return dst


def read_offline_registry(cfg) -> dict | None:
    """``team.offlineDir\\lm27_registry.json`` — 운반 형식(schema·정수 version·pepper 64hex 또는 없음)만 확인해 돌려준다.
    채택(캐시보다 version 이 클 때만, ``validate_registry(side="client")`` 통과 시)은 분류 레지스트리 로더가 정한다(H §3.2)."""
    d = str(cfg["team.offlineDir"] or "").strip()
    if not d:
        return None
    obj = fsx.read_json(os.path.join(d, REGISTRY_FILE), None)
    if not isinstance(obj, dict) or obj.get("schema") != "lm27.registry/1":
        return None
    v = obj.get("version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        return None
    pep = obj.get("pepper")
    if pep is not None and not (isinstance(pep, str) and re.fullmatch(r"[0-9a-f]{64}", pep)):
        return None
    return obj


def publish_registry(store, cfg) -> bool:
    """레지스트리가 바뀔 때마다 ``teamServer.publishDir`` 에 원자 게시(pepper 포함 — TAB §5.3, 미결 3). 실패는 로그만."""
    d = str(cfg["teamServer.publishDir"] or "").strip()
    if not d:
        return False
    try:
        fsx.atomic_write(os.path.join(d, REGISTRY_FILE), fsx.canon_bytes(store.registry_for_client()))
    except OSError as e:
        store.log_line("publish", f"레지스트리 게시 실패 {type(e).__name__}")
        return False
    return True


# ───────────────────────────── 반입 ─────────────────────────────
def _candidates(folder: str, max_bytes: int, now: float):
    """폴더의 반입 후보 → (이름, 경로, 상태) — 상태: ok · name · part · hidden · empty · big · copying."""
    try:
        names = sorted(os.listdir(fsx.longp(folder)))
    except OSError:
        return
    for n in names:
        p = os.path.join(folder, n)
        try:
            st = os.stat(fsx.longp(p))
        except OSError:
            continue
        if not os.path.isfile(fsx.longp(p)):
            continue
        if n.endswith(".part") or ".part" in n:
            yield n, p, "part"
        elif n.startswith(".") or getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_HIDDEN:
            yield n, p, "hidden"
        elif not NAME_RX.fullmatch(n):
            yield n, p, "name"
        elif st.st_size == 0:
            yield n, p, "empty"
        elif st.st_size > max_bytes:
            yield n, p, "big"
        elif now - st.st_mtime < COPY_QUIET_SEC:
            yield n, p, "copying"
        else:
            yield n, p, "ok"


def _move_to(store, src: str, sub: str, name: str, sha8: str) -> str:
    dst_dir = store.inbox(sub)
    fsx.ensure_dir(dst_dir)
    dst = dst_dir / name
    if dst.exists():
        dst = dst_dir / f"{name[:-5]}.{sha8}.json"
    os.replace(fsx.longp(src), fsx.longp(dst))
    return dst.name


def scan_inboxes(store, cfg, *, now: float | None = None) -> dict:
    """반입 폴더 한 바퀴(TAB §5.2). 반환 {stored, already, stale, rejected, ignored, copying, results[{file, status|code}]}."""
    from lm27.team.store import ingest_bytes
    now = time.time() if now is None else now
    max_bytes = cfg["teamServer.maxBodyMb"] * 1024 * 1024
    out = {"stored": 0, "already": 0, "stale": 0, "rejected": 0, "ignored": 0, "copying": 0, "results": []}

    def tally(r, name):
        if r.ok:
            key = {"stored": "stored", "already_have": "already", "stale_kept": "stale"}[r.status]
            out[key] += 1
            out["results"].append({"file": name, "status": r.status})
        else:
            out["rejected"] += 1
            out["results"].append({"file": name, "code": r.code})
    # ① 저장소 inbox — 성공 done\, 실패 rejected\ + 사유
    for n, p, state in _candidates(str(store.inbox()), max_bytes, now):
        if state == "copying":
            out["copying"] += 1
            continue
        if state != "ok":
            out["ignored"] += 1
            continue
        raw = fsx.read_bytes(p)
        r = ingest_bytes(store, raw, source="inbox:" + n)
        sha8 = fsx.sha256_hex(raw)[:8]
        if r.ok:
            _move_to(store, p, "done", n, sha8)
        else:
            moved = _move_to(store, p, "rejected", n, sha8)
            fsx.atomic_write(store.inbox("rejected", moved + ".reason.json"),
                             fsx.canon_bytes({"code": r.code, "error": r.msg, "detail": r.detail}))
        tally(r, n)
    # ② 감시 폴더(남의 폴더일 수 있다) — 옮기거나 지우지 않는다, sha 로 한 번만
    seen = fsx.read_json(store.run_file("inbox_seen.json"), {}) or {}
    changed = False
    for d in cfg["teamServer.inboxDirs"] or ():
        for n, p, state in _candidates(str(d), max_bytes, now):
            if state == "copying":
                out["copying"] += 1
                continue
            if state != "ok":
                out["ignored"] += 1
                continue
            try:
                raw = fsx.read_bytes(p)
            except OSError:
                continue
            sha = fsx.sha256_hex(raw)
            if sha in seen:
                continue
            r = ingest_bytes(store, raw, source="inbox:" + n)
            seen[sha] = {"file": n, "at": store.clock().isoformat(), "result": r.status if r.ok else r.code}
            changed = True
            tally(r, n)
    if changed:
        fsx.atomic_write(store.run_file("inbox_seen.json"), fsx.canon_bytes(seen))
    return out


def import_files(store, path, cfg, *, aggregate_fn=None) -> dict:
    """``lm27 team-import <파일|폴더> [--store DIR]`` — 저장소 잠금이 비면 직접 반입 + 재취합(현재 세대 전환),
    서버가 실행 중(잠금 점유)이면 저장소 inbox 로 **복사만** 하고 안내. rc: 0 성공 · 2 일부 거절 · 3 경로 없음 · 4 할 일 없음."""
    from lm27.team.store import ingest_bytes
    path = os.path.expandvars(str(path or "").strip().strip('"'))
    if os.path.isfile(fsx.longp(path)):
        files = [(os.path.basename(path), path)]
        if not NAME_RX.fullmatch(files[0][0]):
            return {"rc": 2, "mode": "none", "results": [{"file": files[0][0], "code": "name"}],
                    "message_ko": "파일 이름이 lm27_team_bundle_….json 형식이 아닙니다"}
    elif os.path.isdir(fsx.longp(path)):
        files = [(n, p) for n, p, st in _candidates(path, 1 << 62, float("inf")) if st in ("ok", "copying")]
    else:
        return {"rc": 3, "mode": "none", "results": [], "message_ko": "파일·폴더가 없거나 이 망에서 닿지 않습니다"}
    if not files:
        return {"rc": 4, "mode": "none", "results": [], "message_ko": "반입할 팀 묶음 파일이 없습니다"}
    if not store.lock_server():
        past = time.time() - COPY_QUIET_SEC - 1
        for n, p in files:
            dst = store.inbox(n)
            fsx.atomic_write(dst, fsx.read_bytes(p))           # 원자 쓰기라 반쪽이 없다 — '복사 중' 대기를 건너뛰게 시각만 앞당김
            os.utime(fsx.longp(dst), (past, past))
        return {"rc": 0, "mode": "queued", "results": [{"file": n, "status": "queued"} for n, _p in files],
                "message_ko": f"팀 서버가 실행 중입니다 — {len(files)}개를 반입 폴더에 넣었습니다. 서버가 "
                              f"{cfg['teamServer.inboxPollSec']}초 안에 반영합니다."}
    try:
        results, stored = [], 0
        for n, p in files:
            r = ingest_bytes(store, fsx.read_bytes(p), source="inbox:" + n)
            results.append({"file": n, "status": r.status} if r.ok else {"file": n, "code": r.code})
            stored += r.ok and r.status == "stored"
        agg = None
        if stored:
            if aggregate_fn is None:
                from lm27.team.aggregate import aggregate as aggregate_fn
            gen = store.next_gen()
            res = aggregate_fn(store, gen)
            ok = res.ok if hasattr(res, "ok") else bool(res.get("ok"))
            if ok:
                store.publish_gen(gen, res.as_result_json() if hasattr(res, "as_result_json") else res)
            agg = {"gen": gen, "state": "done" if ok else "failed"}
    finally:
        store.release_server()
    bad = sum(1 for r in results if "code" in r)
    return {"rc": 2 if bad else 0, "mode": "direct", "results": results, "aggregate": agg,
            "message_ko": f"{len(results) - bad}개 반입, {bad}개 거절" + (" — 재취합 완료" if agg and agg["state"] == "done"
                                                                     else "")}


def default_export_dir(cfg) -> str:
    """[파일로 내보내기] 기본 폴더(``team.offlineDir`` — 비면 화면이 묻는다)."""
    return str(cfg["team.offlineDir"] or "")


def name_ok(name: str) -> bool:
    return bool(NAME_RX.fullmatch(name or ""))


__all__ = ["NAME_RX", "REGISTRY_FILE", "UserError", "default_export_dir", "export_to_dir", "import_files", "name_ok",
           "publish_registry", "read_offline_registry", "scan_inboxes"]
