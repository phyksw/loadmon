# -*- coding: utf-8 -*-
r"""LM27 자체 시험 관문 — ``python\python.exe -B tools\lm27_selftest.py privacy [--update-lock]``(계약 §2.18·§7.3).

  privacy          정제 회귀 말뭉치 관문(P §18 · 계약 T-08) = ``lm27.privacy.selftest.run_selftest()``
  --update-lock    말뭉치 전부 통과할 때만 ``lm27\privacy\rules.lock.json`` 을 지금 규칙으로 갱신(P §16.4 ④)

종료 코드: 0 = 통과, 1 = 실패·인자 오류. 결과 줄은 stderr(사람용, 계약 §8.6) — 말뭉치 id·건수·코드·해시만(원문 없음).
``lm27 selftest privacy`` 와 같은 함수를 부른다. 동봉 파이썬의 ``python311._pth`` 가 스크립트 폴더를 sys.path 에 넣지
않으므로 첫 실행문에서 ROOT 를 넣는다(L-05 · 계약 §9.1).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lm27.privacy.selftest import run_selftest
from lm27.util import events

USAGE = "사용: lm27_selftest.py privacy [--update-lock]"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        sys.stderr.write(USAGE + "\n")
        return 0 if args else 1
    if args[0] != "privacy" or any(a != "--update-lock" for a in args[1:]):
        sys.stderr.write(USAGE + "\n")
        return 1
    events.configure(mode="text")
    return run_selftest(update_lock="--update-lock" in args[1:])


if __name__ == "__main__":
    for _st in (sys.stdout, sys.stderr):
        _rc = getattr(_st, "reconfigure", None)
        if _rc is not None:
            _rc(encoding="utf-8", errors="replace")
    sys.exit(main())
