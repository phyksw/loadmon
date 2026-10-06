# -*- coding: utf-8 -*-
r"""가짜 정제 파이프(합성 — 시험 전용). ``lm27_pipe.py`` 의 요약 줄·종료 코드만 흉내 낸다(계약 §8.2).

    "<PY>" -X utf8 -B fake_pipe.py --behave <json 파일> [lm27_pipe.py 인자…]

behave(JSON): ``{"exit": 코드, "hang_s": 초(EOF 뒤 멈춤 — 대기 초과 시험), "record_to": 파일(받은 줄을 저장 —
_cursor 전달 여부 단언용), "collector_status_from_stdin": bool}``. 레코드 줄(``_`` 로 시작하지 않는 JSON)을 세어
``stored = rows_in`` 으로 요약한다. ``_cursor`` 를 받았으면 ``cursor_saved = (exit in 0·2)``.
"""
import argparse
import json
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--behave", required=True)
    a, _rest = ap.parse_known_args()
    with open(a.behave, "rb") as fh:
        b = json.loads(fh.read().decode("utf-8"))
    rows, cursor, status, seen = 0, False, None, []
    for raw in sys.stdin.buffer:
        s = raw.strip()
        if not s:
            continue
        seen.append(s)
        try:
            obj = json.loads(s.decode("utf-8"))
        except ValueError:
            continue
        if isinstance(obj, dict) and len(obj) == 1 and next(iter(obj)).startswith("_"):
            k = next(iter(obj))
            if k == "_cursor":
                cursor = True
            elif k == "_status":
                status = obj[k]
            continue
        rows += 1
    if b.get("record_to"):
        with open(b["record_to"], "wb") as fh:            # 시험 전용(%TEMP% 샌드박스)
            fh.write(b"\n".join(seen) + b"\n")
    if b.get("hang_s"):
        time.sleep(float(b["hang_s"]))
    code = int(b.get("exit", 0))
    summ = {"ok": code in (0, 2), "mode": "append", "rows_in": rows, "stored": rows if code in (0, 2) else 0,
            "dropped": {"ad": 0}, "errors": {}, "rules_ver": "2026.10.0", "kid": "k00000000",
            "cursor_saved": bool(cursor and code in (0, 2))}
    if status is not None:
        summ["collector_status"] = status
    sys.stdout.write(json.dumps(summ) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
