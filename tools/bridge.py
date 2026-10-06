# -*- coding: utf-8 -*-
r"""브리지 진입점(B §2.2 · 계약 §2.18) — ``python\python.exe -X utf8 -B tools\bridge.py <명령> [옵션]``.

``lm27 bridge <명령>`` 과 같은 ``lm27.bridge.cli.main()`` 을 부른다(명령 표는 그 모듈 머리). 동봉 파이썬의
``python311._pth`` 가 스크립트 폴더를 sys.path 에 넣지 않으므로 첫 실행문에서 ROOT 를 넣는다(L-05 · 계약 §9.1).
그 밖의 코드는 두지 않는다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lm27.bridge.cli import main

if __name__ == "__main__":
    for _st in (sys.stdout, sys.stderr):
        _rc = getattr(_st, "reconfigure", None)
        if _rc is not None:
            _rc(encoding="utf-8", errors="replace")
    sys.exit(main())
