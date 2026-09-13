# -*- coding: utf-8 -*-
r"""Copilot 왕복 계측 요약 — report\copilot_trace.jsonl 을 읽어 '왜 느린가' 를 숫자로 말한다.

기록에는 프롬프트·답의 **길이와 시간만** 있고 원문은 없다(팀 서버로도 나가지 않는다). 그래서 이 요약은
남에게 보여도 된다. 사용 예:
    python tools\trace_summary.py                 (이 폴더의 report\copilot_trace.jsonl)
    python tools\trace_summary.py --last 1        (마지막 실행 1회분만 — 실행 경계는 30분 공백)

무엇을 보는가
  · done_by  pledge=서약을 보고 즉시 / idle=중지 버튼 사라짐 / stable=같은 텍스트 반복(가장 느림)
  · busy     그 왕복에서 '중지' 버튼을 한 번이라도 봤는가 — False 만 계속 나오면 버튼 선택자가 이 UI 와 안 맞는 것
  · cut/retry/repaired  잘린 답·재시도 — 이것이 많으면 '왕복 수' 가 늘어 분석이 느려진다
"""
import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))

GAP_MIN = 30           # 이보다 오래 비면 다른 실행으로 본다


def load(path):
    rows = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        return []
    return rows


def _t(r):
    try:
        return datetime.strptime(str(r.get("t", ""))[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def split_runs(rows):
    """시각 공백으로 실행을 나눈다 — 파일에는 여러 날의 실행이 이어 붙어 있다."""
    runs, cur, prev = [], [], None
    for r in rows:
        t = _t(r)
        if prev is not None and t is not None and (t - prev).total_seconds() > GAP_MIN * 60 and cur:
            runs.append(cur)
            cur = []
        cur.append(r)
        if t is not None:
            prev = t
    if cur:
        runs.append(cur)
    return runs


def fmt_sec(s):
    s = float(s or 0)
    return f"{s / 60:.0f}분 {s % 60:.0f}초" if s >= 60 else f"{s:.0f}초"


def summarize(rows, label):
    n = len(rows)
    if not n:
        print(f"{label}: 기록 없음")
        return
    tot = sum(float(r.get("sec") or 0) for r in rows)
    by = Counter(str(r.get("done_by") or ("실패" if not r.get("ok") else "?")) for r in rows)
    ok = sum(1 for r in rows if r.get("ok"))
    cut = sum(1 for r in rows if r.get("cut"))
    retry = sum(1 for r in rows if r.get("retry"))
    fresh = sum(1 for r in rows if r.get("fresh"))
    pledge = sum(1 for r in rows if r.get("pledge"))
    busy_vals = [r.get("busy") for r in rows if r.get("busy") is not None]
    busy_seen = sum(1 for b in busy_vals if b)
    t0, t1 = _t(rows[0]), _t(rows[-1])
    span = (t1 - t0).total_seconds() if (t0 and t1) else tot
    print(f"{label}")
    print(f"   왕복 {n}회 · 왕복 시간 합 {fmt_sec(tot)} · 실행 구간 {fmt_sec(span)}"
          f" · 왕복당 평균 {tot / n:.0f}초 · 성공 {ok}/{n}")
    print("   완료 판정: " + " · ".join(f"{k} {v}회" for k, v in by.most_common()))
    print(f"   서약 봄 {pledge}회({100 * pledge / n:.0f}%) · 잘린 답(cut) {cut}회 · 재시도 {retry}회 · 새 채팅 {fresh}회")
    if busy_vals:
        print(f"   중지 버튼 봄: {busy_seen}/{len(busy_vals)}회"
              + ("  ← 한 번도 못 봤다 = 버튼 선택자가 이 UI 와 안 맞음(지름길 불가, 예전 규칙으로 판정)" if not busy_seen else ""))
    else:
        print("   중지 버튼 계측(busy) 없음 — 이 기록은 그 계측이 들어가기 전 판본의 것")
    # 단계별
    st = defaultdict(list)
    for r in rows:
        st[str(r.get("stage") or "?")].append(r)
    print("   단계별:")
    for k, v in sorted(st.items(), key=lambda x: -sum(float(r.get("sec") or 0) for r in x[1])):
        s = sum(float(r.get("sec") or 0) for r in v)
        rp = [float(r.get("reply") or 0) for r in v if r.get("ok")]
        idle_stable = sum(1 for r in v if r.get("done_by") in ("idle", "stable"))
        print(f"      {k:<12} {len(v):>3}회 · {fmt_sec(s):>8} · 평균 {s / len(v):>4.0f}초"
              f" · 답 평균 {sum(rp) / len(rp) if rp else 0:>5.0f}자 · 서약 못 봄 {idle_stable}회"
              f" · 잘림 {sum(1 for r in v if r.get('cut'))}회 · 재시도 {sum(1 for r in v if r.get('retry'))}회")
    # 해석
    hints = []
    if n and by.get("stable", 0) / n > 0.3:
        hints.append("stable(같은 텍스트 반복) 판정이 30% 를 넘는다 — 서약을 자주 못 보고 있고 지름길도 안 탄다: 왕복마다 stablePolls×pollSec 을 통째로 기다린다")
    if n and by.get("idle", 0) / n > 0.3 and (cut or retry):
        hints.append("idle 판정이 많은데 잘림·재시도도 많다 — '중지' 버튼 판정이 답을 쓰는 도중에 회수한 신호(선택자 불일치 의심)")
    if n and retry / n > 0.15:
        hints.append("재시도가 15% 를 넘는다 — 왕복 수 자체가 불어 느려진 것. 잘린 답(cut)·서약 누락과 함께 보라")
    if busy_vals and not busy_seen:
        hints.append("중지 버튼을 한 번도 못 봤다 — 새 UI 표기일 수 있다. 화면 스크린샷을 보여 주면 선택자를 맞출 수 있다")
    for h in hints:
        print("   ▶ " + h)


def main():
    path = os.path.join(ROOT, "report", "copilot_trace.jsonl")
    for i, a in enumerate(sys.argv):
        if a == "--file" and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
    last = 0
    for i, a in enumerate(sys.argv):
        if a == "--last" and i + 1 < len(sys.argv):
            try:
                last = int(sys.argv[i + 1])
            except ValueError:
                last = 0
    rows = load(path)
    if not rows:
        print(f"기록이 없습니다: {path}")
        print("  (AI 정제를 한 번이라도 돌린 뒤 생깁니다 — LoadMonitor24_v2 부터 기록)")
        return 1
    runs = split_runs(rows)
    print(f"[trace] {path} — 왕복 {len(rows)}회 · 실행 {len(runs)}회분")
    pick = runs[-last:] if last else runs
    for k, run in enumerate(pick, 1):
        t0 = str(run[0].get("t", ""))[:16]
        summarize(run, f"\n■ 실행 {k if last else runs.index(run) + 1}/{len(runs)} — {t0} 시작")
    return 0


if __name__ == "__main__":
    sys.exit(main())
