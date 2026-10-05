# -*- coding: utf-8 -*-
r"""LoadMonitor27 단일 진입점 — ``lm27 <명령>`` = ``"<ROOT>\python\python.exe" -X utf8 -B "<ROOT>\lm27_cli.py" <명령>``.

동봉 파이썬의 ``python311._pth`` 는 스크립트 폴더를 sys.path 에 넣지 않으므로 첫 실행문에서 ROOT 를 스스로 넣는다
(계약 §9.1 · L-05). 모듈 실행(-m) 형식은 쓰지 않는다. 그 밖 코드는 두지 않는다 — 명령 분배는 ``lm27.cli``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lm27.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
