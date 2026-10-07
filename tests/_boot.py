# -*- coding: utf-8 -*-
r"""tests\_boot.py — 시험 공통 준비: 모듈 경로 등록 + PowerShell 시험 결과 읽기.

모든 tests\test_*.py 는 맨 위에서 `import _boot` 한다(run_tests.py 가 tests\ 를 sys.path 에 넣는다).
  · ROOT·core·collect·tools·ui 를 sys.path 에 넣는다 — 운영 코드를 같은 프로세스에서 임포트한다.
  · ps_result(name) — run_tests.py --ps 가 tests\ps\Run-PsTests.ps1 을 **1회** 돌려 LM_PS_RESULTS 파일에 남긴
    결과 중 tests\ps\Test-<name>.ps1 의 것을 돌려준다. --ps 없이 돌면 None — 그 시험은 건너뛴다(skip).
  · 임시 폴더는 tempfile.TemporaryDirectory 만 쓴다(끝나면 지워진다 — %TEMP% 에 사본을 남기지 않는다).
"""
import json
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
for _p in (os.path.join(ROOT, "ui"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "collect"),
           os.path.join(ROOT, "core"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PS = {"path": None, "data": None}


def ps_results():
    """LM_PS_RESULTS 파일 전체({이름: 결과}) — 없거나 깨졌으면 {}."""
    p = os.environ.get("LM_PS_RESULTS", "")
    if not p or not os.path.isfile(p):
        return {}
    if _PS["path"] != p:
        try:
            with open(p, encoding="utf-8-sig") as f:
                _PS["data"] = json.load(f) or {}
        except (OSError, ValueError):
            _PS["data"] = {}
        _PS["path"] = p
    return _PS["data"]


def ps_result(name):
    """tests\\ps\\Test-<name>.ps1 의 결과(dict) — --ps 로 돌지 않았으면 None."""
    return ps_results().get(name)


def read_text(path):
    """운영 파일 텍스트 — .bat 은 CP949, 그 밖은 UTF-8(BOM 허용)."""
    with open(path, "rb") as f:
        b = f.read()
    if path.lower().endswith((".bat", ".cmd")):
        return b.decode("cp949", "replace")
    return b.decode("utf-8-sig", "replace")
