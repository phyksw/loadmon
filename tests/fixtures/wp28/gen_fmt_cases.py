# -*- coding: utf-8 -*-
r"""RPT-11 파이썬 쪽 — 표시 함수 교차 사례를 파이썬으로 계산해 JSON 으로 낸다(tests\web\common_test.js 가 JS 결과와 대조).

    "<PY>" -X utf8 -B tests\fixtures\wp28\gen_fmt_cases.py      → stdout {"source", "h1", "mm2", "pct0"}

사례 격자는 참조 시제품 fmt_check.js 와 같다(분 0~20,000 · 분모 4종 · 비율 분모 4종 = 11,530 사례).
lm27\report\fmt.py(WP-30)가 트리에 있으면 그 함수를, 없으면 REPORTS §3.1 의 정수 half-up 참조식을 쓴다(source 에 표시).
시험 자료만 만든다 — 파일을 쓰지 않는다.
"""
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def ref_h1(minutes):
    q = (minutes * 10 * 2 + 60) // 120
    return f"{q // 10}.{q % 10}"


def ref_ratio(num, den, digits):
    if den <= 0:
        return None
    s = 10 ** digits
    q = (num * s * 2 + den) // (2 * den)
    return f"{q // s}.{q % s:0{digits}d}" if digits else str(q)


def pick():
    """(출처 이름, fmt_h1, fmt_ratio) — 실물 fmt.py 가 있으면 그것(없으면 참조식)."""
    if os.path.isfile(os.path.join(ROOT, "lm27", "report", "fmt.py")):
        sys.path.insert(0, ROOT)
        mod = importlib.import_module("lm27.report.fmt")
        return "lm27.report.fmt", mod.fmt_h1, mod.fmt_ratio
    return "REPORTS §3.1 참조식", ref_h1, ref_ratio


def cases(fmt_h1, fmt_ratio):
    out = {"h1": {}, "mm2": {}, "pct0": {}}
    for m in range(0, 20001, 7):
        out["h1"][str(m)] = fmt_h1(m)
    for d in (9600, 10560, 8880, 7680):
        for n in range(0, 14001, 13):
            out["mm2"][f"{n}/{d}"] = fmt_ratio(n, d, 2)
    for d in (8880, 11520, 199, 200):
        for n in range(0, 12001, 11):
            out["pct0"][f"{n}/{d}"] = fmt_ratio(n * 100, d, 0)
    return out


def main():
    src, h1, ratio = pick()
    data = cases(h1, ratio)
    data["source"] = src
    sys.stdout.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
