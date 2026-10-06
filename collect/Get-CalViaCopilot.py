# -*- coding: utf-8 -*-
r"""cal.copilot — Copilot 일정 존재 증인 어댑터(B §8.1 · 계약 §2.17 · §3.2 · §6.5 · X-084). 클라우드PC 에서 브리지 조회 단계
``lookup_calendar``(**기본 꺼짐** — ``bridge.stages.lookup_calendar=false``)를 부른다. 흐름·셀·rc·커서·상태 줄은
``Get-MailViaCopilot.py`` 의 ``run(src, …)`` 한 벌. 꺼져 있으면 묻지 않고 rc 1(대상 없음) + ``skipped: "disabled"``.

    "<PY>" -X utf8 -I -B collect\Get-CalViaCopilot.py --pc <pc_id> --run-id <run_id>
           [--blanks-file F] [--from D --to D] [--force] [--events jsonl|text|off]

증인 행(kind ``cal``, src ``cal.copilot``): 그 날짜 하루 구간(00:00~다음 날 00:00, 근무 시간대) · ``ts_precision="summary"`` ·
``confidence`` 0.3 · 글 = 제목 요지. 시각은 묻지 않는다 — 일정의 분 단위 시각은 COM·색인·OWA 몫이고 Copilot 요약은 시간 근거가
아니다(D-9). 셀 축 ``cal``.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import importlib.util

SRC = "cal.copilot"


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
