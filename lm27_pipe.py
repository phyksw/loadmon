# -*- coding: utf-8 -*-
r"""정제 파이프 진입점(P §3.5 · 계약 §2.1 · §7.3) — PowerShell 수집기·에이전트의 원시 NDJSON 을 stdin 으로 받아 정제·저장한다.

    "<PY>" -X utf8 -I -B "<LM27>\lm27_pipe.py" --kind <kind> --src <경로 ID> --pc <pc_id> --mode append

동봉 파이썬의 ``python311._pth`` 는 스크립트 폴더를 sys.path 에 넣지 않으므로 첫 실행문에서 자기 폴더를 넣는다(L-05 ·
계약 §9.1). 프로그램 폴더(``<ROOT>``)와 에이전트 bin 사본(``agent\bin\<ver>\``) 어디서나 같은 파일이다. 그 밖 코드는
두지 않는다 — 본체는 ``lm27.privacy.sanitize_stream.main``. 모듈 실행(-m) 형식은 쓰지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lm27.privacy.sanitize_stream import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
