# -*- coding: utf-8 -*-
r"""정제 파이프 본체(P §3.5 · 계약 §7.3 · §8.2 · X-104 · X-106 · X-300 · X-301) — ``lm27_pipe.py`` 가 ``main(argv)`` 를 부른다.

    <PY> -X utf8 -I -B "<LM27>\lm27_pipe.py" --kind <kind> --src <경로 ID> --pc <pc_id> --mode append [--out <store 일자 파일>]
    <PY> -X utf8 -I -B "<LM27>\lm27_pipe.py" --route-by-kind --src-map mail=mail.com,cal=cal.com --pc <pc_id> --mode append
    <PY> -X utf8 -I -B "<LM27>\lm27_pipe.py" --kind <kind> --src <경로 ID> --pc <pc_id> --out <파일> [--mode new]

입력(stdin, UTF-8 — 첫 줄 BOM 은 벗김): 한 줄 = 원시 레코드 JSON 1개(P §10.2 원시 이름). 빈 줄 무시, 한 줄 최대 1MB.
제어 줄(키 하나가 ``_`` 로 시작하는 객체)은 레코드로 세지 않는다: ``_meta.my_addrs``(메모리 전용 — 본인 주소, 저장 안 함),
``_cursor``(수집기 진전 — 출력 기록 성공 뒤에만 ``lm27.store.cursor.save_raw_cursor`` 로 저장, 혼합 라우팅은
``{경로 ID: 값}``), ``_status``(수집기 상태 줄 — CLM 모드에서 stdout 으로 온 것, 요약의 ``collector_status`` 로 넘긴다 — C1).
그 밖 제어 줄은 버린다. 커서에 HMAC 이 필요한 ``last_msg_key`` 가 비어 있으면 그 묶음의 마지막 저장 행에서 채운다(§3.10).

출력: ``--mode append``(에이전트·전경 로컬 원장) = ``lm27.store.SegmentWriter`` 로 그 (pc, kind, src) 의 **쓰기 UTC 날짜**
일자 파일에 gzip 멤버 하나를 덧붙인다(``--out`` 은 생략 가능 — 주면 같은 흐름의 store 일자 파일이어야 한다. 연결자는 store
경로를 조립하지 않는다 — L-11). ``--mode new`` = 시험·일회성 출력 파일 하나(``lm27.store.writer.write_rows_file``, 원자 쓰기,
``--route-by-kind`` 면 ``--out`` 에 ``{kind}`` 자리표시자 필수). 모든 쓰기는 EOF 뒤 한 번 — 중간에 죽으면 출력 없음.
감사 이벤트는 kind 마다 EOF 에서 1줄(P §15). 문맥 모드: 이 스크립트 옆에 ``data\`` 나 ``lm27_cli.py`` 가 있으면 프로그램 폴더
(키링), 없으면 에이전트 사본(하위 키 — ``Paths.mode()``).

stdout: EOF 뒤 요약 1줄만 ``{ok, mode, rows_in, stored, dropped{}, errors{}, rules_ver, kid, out_sha256, cursor_saved,
collector_status?}``. stderr: 예외 유형과 줄 번호만(원문·정제문 금지 — I8).
종료 코드(계약 §8.2): 0 정상 · 2 입력 형식 오류 줄 있음(그 줄만 버리고 계속) · 3 정제기 내부 오류(출력 미기록) ·
5 인자 오류(출력 미기록, ``--route-by-kind`` 에 ``--src-map`` 없음 포함) · 6 키 없음(에이전트 하위 키 없음·손상 — 키가
필요 없는 kind 만 저장하고 나머지는 ``no_key``). 커서는 0·2 일 때만 진전한다(3·5·6·99 는 그대로). 99(대기 초과)는 연결자 몫.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

from lm27.paths import Paths
from lm27.util import fsx

from . import keys as K
from .context import make_record_context
from .records import KINDS, SRCS_BY_KIND, sanitize_record
from .rules import RULES_VERSION

__all__ = ["EXIT_ARGS", "EXIT_BADLINES", "EXIT_INTERNAL", "EXIT_NOKEY", "EXIT_OK", "MAX_LINE", "main"]

EXIT_OK, EXIT_BADLINES, EXIT_INTERNAL, EXIT_ARGS, EXIT_NOKEY = 0, 2, 3, 5, 6
MAX_LINE = 1024 * 1024
_PC_CHARS = frozenset("pcx_0123456789abcdef")


class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):                       # argparse 기본은 exit 2 — 계약은 5
        raise _ArgError("args")


def _parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="lm27_pipe.py", add_help=False)
    ap.add_argument("--kind")
    ap.add_argument("--route-by-kind", action="store_true")
    ap.add_argument("--src")
    ap.add_argument("--src-map")
    ap.add_argument("--pc")
    ap.add_argument("--out")
    ap.add_argument("--mode", default="new", choices=("new", "append"))
    return ap


def _plan(a, paths: Paths) -> dict:
    """인자 → {kind: src}. 형식이 틀리면 _ArgError."""
    if not a.pc or not set(a.pc) <= _PC_CHARS or not K._PC_RX.match(a.pc):
        raise _ArgError("pc")
    if a.route_by_kind:
        if a.kind or not a.src_map:
            raise _ArgError("route")
        plan = {}
        for part in a.src_map.split(","):
            k, _, s = part.strip().partition("=")
            if k not in KINDS or s not in SRCS_BY_KIND[k] or k in plan:
                raise _ArgError("src-map")
            plan[k] = s
        if a.src and a.src not in plan.values():
            raise _ArgError("src")
    else:
        if a.kind not in KINDS or a.src_map or not a.src or a.src not in SRCS_BY_KIND[a.kind]:
            raise _ArgError("kind")
        plan = {a.kind: a.src}
    if a.mode == "new":
        if not a.out or (a.route_by_kind and "{kind}" not in a.out):
            raise _ArgError("out")
    elif a.out:
        if a.route_by_kind and "{kind}" not in a.out:
            raise _ArgError("out")
        for k, s in plan.items():
            want = paths.store_file(a.pc, k, s, "2020-01-01").parent.parent
            got = Path(a.out.replace("{kind}", k).replace("{src}", s)).parent.parent
            if os.path.normcase(os.path.abspath(got)) != os.path.normcase(os.path.abspath(want)):
                raise _ArgError("out")
    return plan


def _read_lines(inp):
    """(줄 번호, 바이트) — 첫 줄 BOM 제거·줄끝 제거. 너무 긴 줄은 None(형식 오류로 센다)."""
    first = True
    n = 0
    while True:
        line = inp.readline(MAX_LINE + 2)
        if not line:
            return
        n += 1
        if len(line) > MAX_LINE and not line.endswith(b"\n"):
            while True:                               # 나머지 버리기
                rest = inp.readline(MAX_LINE)
                if not rest or rest.endswith(b"\n"):
                    break
            yield n, None
            first = False
            continue
        if first and line.startswith(b"\xef\xbb\xbf"):
            line = line[3:]
        first = False
        yield n, line.rstrip(b"\r\n")


def _pick(rows, ts):
    cands = [r for r in rows if isinstance(r.get("msg_key"), str)]
    if ts:
        exact = [r for r in cands if r.get("ts_utc") == ts]
        cands = exact or cands
    return max(cands, key=lambda r: (r.get("ts_utc") or "", r["msg_key"])) if cands else None


def _fill_cursor(value, rows):
    """``last_msg_key`` 가 비어 있으면 그 묶음의 마지막 저장 행에서 채운다(계약 §3.10). 원래 값은 바꾸지 않는다."""
    if not isinstance(value, dict) or not rows:
        return value
    v = fsx.loads_strict(fsx.canon_bytes(value))
    box = v.get("box")
    if isinstance(box, dict):
        for b, e in box.items():
            if isinstance(e, dict) and "last_msg_key" in e and not e.get("last_msg_key"):
                p = _pick([r for r in rows if r.get("box") == b], e.get("last_ts_utc"))
                if p:
                    e["last_msg_key"] = p["msg_key"]
    if "last_msg_key" in v and not v.get("last_msg_key"):
        p = _pick(rows, v.get("last_ts_utc"))
        if p:
            v["last_msg_key"] = p["msg_key"]
    return v


def _summary(out, **fields) -> None:
    try:
        out.write(fsx.canon_bytes(fields).decode("utf-8") + "\n")
        out.flush()
    except (OSError, ValueError):
        pass


def _say(err, text: str) -> None:
    try:
        err.write(text + "\n")
        err.flush()
    except (OSError, ValueError):
        pass


def main(argv=None, *, stdin=None, stdout=None, stderr=None, paths: Paths | None = None, clock=None) -> int:
    """정제 파이프 1회. 반환 = 종료 코드(0·2·3·5·6). ``stdin``(바이트 스트림)·``paths``·``clock`` 은 시험 주입."""
    t0 = time.monotonic()
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    inp = stdin if stdin is not None else sys.stdin.buffer
    paths = paths or Paths()
    mode = paths.mode()
    try:
        a = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        plan = _plan(a, paths)
    except _ArgError:
        _say(err, "lm27_pipe: 인자 오류")
        _summary(out, ok=False, mode=mode, rows_in=0, stored=0, dropped={}, errors={}, rules_ver=RULES_VERSION,
                 kid=None, out_sha256=None, cursor_saved=False)
        return EXIT_ARGS
    stage = "collect" if mode == "program" else "agent"
    try:
        rcs = {k: make_record_context(paths.root if mode == "program" else None, s, a.pc, stage=stage,
                                      agent_dir=None if mode == "program" else paths.agent_dir(),
                                      paths=paths if mode == "program" else None, clock=clock)
               for k, s in plan.items()}
    except Exception as e:                               # noqa: BLE001 — 문맥을 못 만들면 아무것도 쓰지 않는다
        _say(err, f"lm27_pipe: 정제기 준비 실패({type(e).__name__})")
        _summary(out, ok=False, mode=mode, rows_in=0, stored=0, dropped={}, errors={type(e).__name__: 1},
                 rules_ver=RULES_VERSION, kid=None, out_sha256=None, cursor_saved=False)
        return EXIT_INTERNAL
    first_rc = next(iter(rcs.values()))
    kid = getattr(first_rc.keyring, "kid", K.NO_KID)
    rows = {k: [] for k in plan}
    rows_in = dict.fromkeys(plan, 0)
    dropped: dict = {}
    errors: dict = {}
    bad_lines = 0
    cursors: dict = {}
    status = None
    lineno = 0
    try:
        for n_line, line in _read_lines(inp):
            lineno = n_line
            if line is None:
                bad_lines += 1
                continue
            if not line.strip():
                continue
            try:
                obj = fsx.loads_strict(line)
            except ValueError:
                bad_lines += 1
                continue
            if not isinstance(obj, dict):
                bad_lines += 1
                continue
            if len(obj) == 1 and next(iter(obj)).startswith("_"):
                (ck, cv), = obj.items()
                if ck == "_meta" and isinstance(cv, dict):
                    for rc in rcs.values():
                        rc.add_my_addrs(cv.get("my_addrs") or ())
                elif ck == "_cursor":
                    if a.route_by_kind:
                        if isinstance(cv, dict):
                            for s, val in cv.items():
                                if s in plan.values():
                                    cursors[s] = val
                    else:
                        cursors[plan[a.kind]] = cv
                elif ck == "_status" and isinstance(cv, dict):
                    status = cv
                continue
            if a.route_by_kind:
                k = obj.pop("_kind", None)
                if k not in plan:
                    bad_lines += 1
                    continue
            else:
                k = a.kind
                rk = obj.get("_kind")
                if rk is not None and rk != k:
                    bad_lines += 1
                    continue
            rows_in[k] += 1
            res = sanitize_record(k, obj, rcs[k])
            obj = None
            if res.status == "stored":
                rows[k].append(res.row)
            elif res.status == "dropped":
                dropped[res.reason] = dropped.get(res.reason, 0) + 1
            else:
                errors[res.reason] = errors.get(res.reason, 0) + 1
    except Exception as e:                               # noqa: BLE001 — 내부 오류: 출력 미기록(원문 대체 저장 금지)
        _say(err, f"lm27_pipe: 정제기 오류({type(e).__name__}, 줄 {lineno})")
        _summary(out, ok=False, mode=mode, rows_in=sum(rows_in.values()), stored=0, dropped=dropped,
                 errors={**errors, type(e).__name__: errors.get(type(e).__name__, 0) + 1}, rules_ver=RULES_VERSION,
                 kid=kid, out_sha256=None, cursor_saved=False)
        return EXIT_INTERNAL
    no_key = mode == "agent" and isinstance(first_rc.keyring, K.NoKeys)
    code = EXIT_NOKEY if no_key else (EXIT_BADLINES if bad_lines else EXIT_OK)
    if bad_lines:
        dropped["bad_raw"] = dropped.get("bad_raw", 0) + bad_lines
    # ── 출력(EOF 뒤 한 번) ──
    shas: dict = {}
    try:
        for k, s in plan.items():
            if a.mode == "new":
                shas[k] = _write_new(a.out.replace("{kind}", k).replace("{src}", s), rows[k])
            elif rows[k]:
                from lm27.store import SegmentWriter     # 지연 import(store → privacy 방향 순환 회피)
                w = SegmentWriter(paths, a.pc, k, s, clock=clock)
                for r in rows[k]:
                    w.append(r)
                w.flush()
                w.close()
                shas[k] = w.last_member_sha256
    except Exception as e:                               # noqa: BLE001
        _say(err, f"lm27_pipe: 출력 기록 실패({type(e).__name__})")
        _summary(out, ok=False, mode=mode, rows_in=sum(rows_in.values()), stored=0, dropped=dropped,
                 errors={**errors, type(e).__name__: errors.get(type(e).__name__, 0) + 1}, rules_ver=RULES_VERSION,
                 kid=kid, out_sha256=None, cursor_saved=False)
        return EXIT_INTERNAL
    # ── 커서(종료 0·2 일 때만) ──
    saved = False
    if code in (EXIT_OK, EXIT_BADLINES) and cursors:
        from lm27.store.cursor import save_raw_cursor
        try:
            for k, s in plan.items():
                if s in cursors:
                    val = _fill_cursor(cursors[s], [r.data for r in rows[k]])
                    save_raw_cursor(paths, a.pc, s, val)
            saved = True
        except Exception as e:                           # noqa: BLE001 — 커서 실패: 다음 주기에 다시 읽고 id 로 흡수
            _say(err, f"lm27_pipe: 커서 저장 실패({type(e).__name__})")
    # ── 감사(kind 마다 1줄) ──
    dur = int((time.monotonic() - t0) * 1000)
    for i, (k, rc) in enumerate(rcs.items()):
        if i == 0 and bad_lines:
            rc.audit.add("dropped", "bad_raw", bad_lines)
        rc.audit.flush(rows_in=rows_in[k] + (bad_lines if i == 0 else 0), rows_out=len(rows[k]),
                       out_sha256=shas.get(k), dur_ms=dur)
    all_sha = [shas[k] for k in plan if shas.get(k)]
    out_sha = None
    if all_sha:
        out_sha = all_sha[0][:16] if len(all_sha) == 1 else hashlib.sha256("".join(all_sha).encode()).hexdigest()[:16]
    fields = {"ok": code in (EXIT_OK, EXIT_BADLINES), "mode": mode, "rows_in": sum(rows_in.values()) + bad_lines,
              "stored": sum(len(v) for v in rows.values()), "dropped": dict(sorted(dropped.items())),
              "errors": dict(sorted(errors.items())), "rules_ver": RULES_VERSION, "kid": kid, "out_sha256": out_sha,
              "cursor_saved": saved}
    if len(plan) > 1:
        fields["by_kind"] = {k: {"src": s, "stored": len(rows[k])} for k, s in plan.items()}
    if status is not None:
        fields["collector_status"] = status
    _summary(out, **fields)
    return code


def _write_new(path: str, rows) -> str:
    from lm27.store.writer import write_rows_file        # 지연 import(store → privacy 방향 순환 회피)
    return write_rows_file(path, rows)
