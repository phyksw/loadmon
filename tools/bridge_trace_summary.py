# -*- coding: utf-8 -*-
r"""브리지 전송 계측 요약(B §11.7, LM24 ``tools\trace_summary.py`` 후계) — ``trace.jsonl`` 에서 단계마다:
질의 수 · 전송 수 · 단별 전송 수(0/1/2) · 상태 분포 · 완료 판정 분포(pledge/idle_json/stable) · 회수 경로 분포
(dom/anchor/fulltext) · 중지 버튼 본 비율 · 평균·최대 생성 초 · 평균 답 길이.

    python\python.exe -X utf8 -B tools\bridge_trace_summary.py [--file <trace.jsonl>] [--run <run_id>] [--json]

기록에는 길이·시간·코드만 있고 원문은 없다(B9) — 이 요약도 그렇다. 경고(B §11.7): ``done_by=stable`` 비율이 30% 를
넘거나 ``pick=fulltext`` 가 하나라도 있으면 서약·DOM 회수가 깨졌다는 신호다. 종료 코드 0 요약 · 1 기록 없음·인자 오류.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import json
from collections import Counter, defaultdict

from lm27.bridge import fsio
from lm27.bridge.trace import iter_rows

STABLE_WARN = 0.3
USAGE = "사용: bridge_trace_summary.py [--file <trace.jsonl>] [--run <run_id>] [--json]"


def summarize(rows) -> dict:
    """계측 줄들 → {단계: 지표}. 전송 줄(kind send·resend)만 센다."""
    by = defaultdict(list)
    for r in rows:
        if r.get("kind") in ("send", "resend"):
            by[str(r.get("stage") or "?")].append(r)
    out = {}
    for stage in sorted(by):
        v = by[stage]
        gens = [float(r.get("gen_sec") or 0) for r in v]
        replies = [int(r.get("reply") or 0) for r in v]
        busy = [r.get("busy_seen") for r in v if r.get("busy_seen") is not None]
        done = Counter(str(r.get("done_by") or "-") for r in v)
        pick = Counter(str(r.get("pick") or "-") for r in v)
        warns = []
        if v and done.get("stable", 0) / len(v) > STABLE_WARN:
            warns.append("stable_over_30pct")
        if pick.get("fulltext", 0) > 0:
            warns.append("fulltext_pick")
        out[stage] = {
            "asks": sum(1 for r in v if r.get("kind") == "send"), "sends": len(v),
            "rungs": {k: sum(1 for r in v if int(r.get("rung") or 0) == int(k)) for k in ("0", "1", "2")},
            "statuses": dict(sorted(Counter(str(r.get("status") or "-") for r in v).items())),
            "done_by": dict(sorted(done.items())), "pick": dict(sorted(pick.items())),
            "busy_seen_ratio": round(sum(1 for b in busy if b) / len(busy), 3) if busy else None,
            "gen_sec_avg": round(sum(gens) / len(gens), 1) if gens else 0.0,
            "gen_sec_max": round(max(gens), 1) if gens else 0.0,
            "reply_avg": round(sum(replies) / len(replies), 1) if replies else 0.0,
            "warnings": warns}
    return out


def _text(summary: dict) -> str:
    lines = []
    for stage, s in summary.items():
        lines.append(f"■ {stage}: 질의 {s['asks']} · 전송 {s['sends']} (단 0/1/2 = {s['rungs']['0']}/"
                     f"{s['rungs']['1']}/{s['rungs']['2']})")
        lines.append("   상태 " + " · ".join(f"{k} {v}" for k, v in s["statuses"].items()))
        lines.append("   완료 판정 " + " · ".join(f"{k} {v}" for k, v in s["done_by"].items())
                     + " / 회수 " + " · ".join(f"{k} {v}" for k, v in s["pick"].items()))
        lines.append(f"   생성 평균 {s['gen_sec_avg']}초 · 최대 {s['gen_sec_max']}초 · 답 평균 {s['reply_avg']}자"
                     + (f" · 중지 버튼 봄 {s['busy_seen_ratio']}" if s["busy_seen_ratio"] is not None else ""))
        for w in s["warnings"]:
            lines.append("   ▶ 경고: " + {"stable_over_30pct": "stable 완료 판정이 30% 를 넘습니다(서약 회수 확인)",
                                         "fulltext_pick": "전문 회수(fulltext)가 있습니다(DOM·앵커 회수 확인)"}[w])
    return "\n".join(lines)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path, run, as_json = None, None, False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--file", "--run") and i + 1 < len(args):
            if a == "--file":
                path = args[i + 1]
            else:
                run = args[i + 1]
            i += 2
            continue
        if a == "--json":
            as_json = True
        elif a in ("-h", "--help"):
            sys.stderr.write(USAGE + "\n")
            return 0
        else:
            sys.stderr.write(USAGE + "\n")
            return 1
        i += 1
    if path is None:
        from lm27.paths import Paths
        path = fsio.bridge_file(Paths(), "trace")
    rows = [r for r in iter_rows(path) if run is None or r.get("run") == run]
    if not rows:
        sys.stderr.write("계측 기록이 없습니다\n")
        return 1
    s = summarize(rows)
    if as_json:
        sys.stdout.write(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_text(s) + "\n")
    return 0


if __name__ == "__main__":
    for _st in (sys.stdout, sys.stderr):
        _rc = getattr(_st, "reconfigure", None)
        if _rc is not None:
            _rc(encoding="utf-8", errors="replace")
    sys.exit(main())
