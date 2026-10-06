# -*- coding: utf-8 -*-
r"""teams.copilot — Copilot 팀즈 존재 증인 어댑터(B §8.1 · CT §9 · 계약 §2.17 · §3.2 · §6.5 · X-138). 클라우드PC 에서 브리지
조회 단계 ``lookup_teams`` 를 부른다 — 흐름·셀·rc·커서·상태 줄은 ``Get-MailViaCopilot.py`` 의 ``run(src, …)`` 한 벌.

    "<PY>" -X utf8 -I -B collect\Get-TeamsViaCopilot.py --pc <pc_id> --run-id <run_id>
           [--blanks-file F] [--from D --to D] [--force] [--events jsonl|text|off]

증인 행(kind ``teams``, src ``teams.copilot``): ``ts_precision="summary"`` · ``confidence`` 0.3 · 글 = 요지(``text_masked`` ≤ 200)
· 셀 축 ``teams``. 메시지(teams.uia·teams.web)와 **병합하지 않는다**(재서술 행의 해시가 영영 맞지 않아 이중 계상 — CT §9).
켜고 끄는 스위치는 ``bridge.stages.lookup_teams`` 하나(X-138 — 능력 판정이 불가면 브리지가 skipped 로 끝낸다).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import importlib.util

SRC = "teams.copilot"


def engine():
    """같은 폴더의 ``Get-MailViaCopilot.py``(어댑터 한 벌)를 모듈로 불러온다."""
    name = "lm27_collect_copilot_adapter"
    m = sys.modules.get(name)
    if m is not None:
        return m
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     "Get-MailViaCopilot.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def run(argv=None, **kw) -> int:
    return engine().run(SRC, argv, **kw)


if __name__ == "__main__":
    sys.exit(engine().main(None, SRC))
