# -*- coding: utf-8 -*-
r"""시험용 가짜 ``lm27_cli.py`` — 작업 관리자가 띄우는 하위 명령 흉내(표준 라이브러리만, lm27 를 import 하지 않는다).

    "<PY>" -X utf8 -B fake_cli.py <명령…> --job <id> --events jsonl

행동은 환경 변수 ``WP35_FAKE`` = ``{"<첫 명령 낱말>": {"sleep": 초, "rc": n, "result": {...}, "ignore_stop": bool}}``.
진행 이벤트(§8.6)를 0.1초마다 한 줄 JSON 으로 내고, 끝에 result·run_end 를 낸 뒤 rc 로 끝난다. 디스크에 쓰지 않는다.
"""
import json
import os
import sys
import time


def main(argv):
    args = list(argv)
    job = None
    if "--job" in args:
        i = args.index("--job")
        job = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if "--events" in args:
        i = args.index("--events")
        del args[i:i + 2]
    beh = {}
    try:
        beh = json.loads(os.environ.get("WP35_FAKE") or "{}").get(args[0] if args else "", {})
    except (ValueError, AttributeError):
        beh = {}
    seq = [0]

    def emit(ev, **kw):
        seq[0] += 1
        kw.update(seq=seq[0], ev=ev, ts="2026-10-06T00:00:00Z")
        sys.stdout.write(json.dumps(kw, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    emit("stage_start", stage=args[0] if args else "", text_ko="시작했습니다")
    sys.stdout.write("사람용 줄은 버린다\n")
    total = max(1, int(float(beh.get("sleep", 0.2)) * 10))
    for k in range(total):
        time.sleep(0.1)
        emit("progress", stage=args[0] if args else "", done=k + 1, total=total)
    emit("result", data=beh.get("result") or {"argv": args, "job": job})
    rc = int(beh.get("rc", 0))
    emit("run_end", rc=rc)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
