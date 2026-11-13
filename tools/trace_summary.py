# -*- coding: utf-8 -*-
r"""Copilot 왕복 계측 요약 — report\copilot_trace_YYYYMMDD.jsonl(날짜별 파일)을 읽어 '왜 느린가' 를 숫자로 말한다.

기록에는 프롬프트·답의 **길이와 시간(초)만** 있고 원문·하루 중 시각은 없다(PC 밖으로 나가지 않는다). 그래서 이 요약은
남에게 보여도 된다. 다른 사용자의 자료(종료 코드 4)거나 지우는 중(3)이면(core\consent) 읽지 않는다. 사용 예:
    python tools\trace_summary.py                 (이 폴더의 report\copilot_trace_*.jsonl 전부 — 날짜순)
    python tools\trace_summary.py --last 1        (마지막 날 1일분만 — 기록에는 날짜만 있어 실행 경계는 날짜다)
    python tools\trace_summary.py --file <경로>    (파일 하나만)

날짜별 파일은 그날이 지나면 더 바뀌지 않고, 보관기한 정리(그 밖의 작업 파일 — intermediateDays)가 통째로 지운다. 예전 한 파일
기록(report\copilot_trace.jsonl · .1)이 남아 있으면 함께 읽는다(드라이버가 처음 쓸 때 지운다).

무엇을 보는가
  · done_by  pledge=서약을 보고 즉시 / idle=중지 버튼 사라짐 / stable=같은 텍스트 반복(가장 느림)
  · busy     그 왕복에서 '중지' 버튼을 한 번이라도 봤는가 — False 만 계속 나오면 버튼 선택자가 이 UI 와 안 맞는 것
  · cut/retry/repaired  잘린 답·재시도 — 이것이 많으면 '왕복 수' 가 늘어 분석이 느려진다
  · 채팅 정리(LM28) stage 'chat' 줄 — 만든 채팅 · 지움 · 남김(사유 코드). 왕복 수·시간에는 넣지 않는다
    (Edge 닫기 등 왕복이 아닌 줄도 — 왕복 줄에는 prompt 길이가 있다)
"""
import glob
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))

GAP_MIN = 30           # (예전 기록 — 시각이 있던 줄) 이보다 오래 비면 다른 실행으로 본다
TRACE_RX = re.compile(r"copilot_trace_(\d{8})(\.1)?\.jsonl$", re.I)
LEGACY = ("copilot_trace.jsonl.1", "copilot_trace.jsonl")      # 예전 한 파일 기록(옛 순서: 갈아 끼운 .1 이 먼저)


def trace_files(rep):
    """report 폴더의 계측 파일 → 읽을 순서의 경로 목록: 예전 한 파일(있으면) → 날짜별 파일(날짜순 · 그날의 .1 이 먼저)."""
    out = [os.path.join(rep, n) for n in LEGACY if os.path.isfile(os.path.join(rep, n))]
    days = []
    for p in glob.glob(os.path.join(rep, "copilot_trace_*.jsonl")):
        m = TRACE_RX.search(os.path.basename(p))
        if m:
            days.append((m.group(1), 0 if m.group(2) else 1, p))
    return out + [p for _d, _k, p in sorted(days)]


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


def load_all(paths):
    rows = []
    for p in paths:
        rows += load(p)
    return rows


def _t(r):
    """줄의 시각 — 'YYYY-MM-DD HH:MM:SS'(예전 기록) 또는 'YYYY-MM-DD'(날짜만 — 지금 기록). 읽지 못하면 None."""
    s = str(r.get("t", ""))
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def _day(r):
    s = str(r.get("t", ""))[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""


def split_runs(rows):
    """실행을 나눈다 — 날짜가 바뀌면 다른 실행이다(지금 기록에는 날짜만 있다). 예전 기록(시각 있음)은 같은 날이라도 30분 넘게
    비면 나눈다. 파일에는 여러 날의 실행이 이어 붙어 있다."""
    runs, cur, prev, prev_day = [], [], None, None
    for r in rows:
        t, day = _t(r), _day(r)
        new = bool(cur) and (
            (day and prev_day and day != prev_day)
            or (prev is not None and t is not None and len(str(r.get("t", ""))) > 10
                and (t - prev).total_seconds() > GAP_MIN * 60))
        if new:
            runs.append(cur)
            cur = []
        cur.append(r)
        if t is not None:
            prev = t
        if day:
            prev_day = day
    if cur:
        runs.append(cur)
    return runs


def fmt_sec(s):
    s = float(s or 0)
    return f"{s / 60:.0f}분 {s % 60:.0f}초" if s >= 60 else f"{s:.0f}초"


def chat_summary(rows):
    """stage 'chat' 줄(LM28 채팅 정리) → 한 줄 — 만든 채팅 · 지움 · 남김(사유 코드별). 없으면 ""."""
    ch = [r for r in rows if r.get("stage") == "chat"]
    made = sum(1 for r in ch if r.get("act") == "made")
    ret = Counter(str(r.get("code") or "?") for r in ch if r.get("act") == "retire")
    lost = sum(1 for r in ch if r.get("act") == "lost")
    if not (made or ret or lost):
        return ""
    kept = {k: v for k, v in ret.items() if k != "deleted"}
    if lost:
        kept["lost"] = kept.get("lost", 0) + lost
    return (f"   채팅 정리: 만든 {made} · 지움 {ret.get('deleted', 0)} · 남김 {sum(kept.values())}"
            + (" (" + " · ".join(f"{k} {v}" for k, v in sorted(kept.items(), key=lambda x: -x[1])) + ")" if kept else ""))


def account_summary(rows):
    """stage 'account' 줄(보내기 전 계정 확인 — 코드와 근거 종류만 남는다) → 한 줄. 없으면 "".
    코드: ok(회사 계정 확인) · unknown(못 읽음) · external(회사 밖) · personal(개인 계정) · nolist(회사 도메인 모름).
    근거: dom(계정 단추·계정 창) · msal·idt(로그인 저장소) · sweep(채팅 정리 때 본 것)."""
    ac = Counter((str(r.get("code") or "?"), str(r.get("src") or "")) for r in rows if r.get("stage") == "account")
    if not ac:
        return ""
    return "   계정 확인: " + " · ".join(f"{c} {n}회" + (f"(근거 {s})" if s else "")
                                     for (c, s), n in sorted(ac.items(), key=lambda x: (-x[1], x[0])))


def summarize(rows, label):
    chat = chat_summary(rows)
    acct = account_summary(rows)
    rows = [r for r in rows if "prompt" in r]          # 왕복 줄만(채팅 정리·계정 확인·Edge 닫기 줄은 왕복이 아니다)
    n = len(rows)
    if not n:
        print(f"{label}: 기록 없음")
        for ln in (acct, chat):
            if ln:
                print(ln)
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
    print(f"{label}")
    timed = all(len(str(r.get("t", ""))) > 10 for r in (rows[0], rows[-1]))
    if timed:
        t0, t1 = _t(rows[0]), _t(rows[-1])
        span = (t1 - t0).total_seconds() if (t0 and t1) else tot
        where = f"실행 구간 {fmt_sec(span)}"
    else:                                              # 날짜만 있는 기록 — 구간은 날짜로만 말한다
        d0, d1 = _day(rows[0]), _day(rows[-1])
        where = f"날짜 {d0}" + (f"~{d1}" if d1 and d1 != d0 else "")
    print(f"   왕복 {n}회 · 왕복 시간 합 {fmt_sec(tot)} · {where}"
          f" · 왕복당 평균 {tot / n:.0f}초 · 성공 {ok}/{n}")
    print("   완료 판정: " + " · ".join(f"{k} {v}회" for k, v in by.most_common()))
    print(f"   서약 봄 {pledge}회({100 * pledge / n:.0f}%) · 잘린 답(cut) {cut}회 · 재시도 {retry}회 · 새 채팅 {fresh}회")
    if busy_vals:
        print(f"   중지 버튼 봄: {busy_seen}/{len(busy_vals)}회"
              + ("  ← 한 번도 못 봤다 = 버튼 선택자가 이 UI 와 안 맞음(지름길 불가, 예전 규칙으로 판정)" if not busy_seen else ""))
    else:
        print("   중지 버튼 계측(busy) 없음 — 이 기록은 그 계측이 들어가기 전 판본의 것")
    for ln in (acct, chat):
        if ln:
            print(ln)
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


def _consent_rc():
    """시작 확인(core\\details.consent_gate) → None(내 자료이고 지우는 중이 아님) | 종료 코드(다른 사용자의 자료 4 · 지우는 중 3 —
    안내 한 줄과 마지막 줄 JSON 은 관문이 찍는다)."""
    core = os.path.join(ROOT, "core")
    if core not in sys.path:
        sys.path.insert(0, core)
    try:
        import details
    except Exception as e:  # noqa: BLE001 - 내 자료인지 확인할 수 없으면 읽지 않는다
        print(json.dumps({"ok": False, "code": "no_consent", "reason": type(e).__name__,
                          "error": "내 자료인지 확인하지 못해 읽지 않았습니다"}, ensure_ascii=False))
        return 3
    return details.consent_gate("trace_summary", ROOT)


def main():
    rc = _consent_rc()
    if rc:
        return rc
    rep = os.path.join(ROOT, "report")
    paths = []
    for i, a in enumerate(sys.argv):
        if a == "--file" and i + 1 < len(sys.argv):
            paths = [sys.argv[i + 1]]
    shown = paths[0] if paths else os.path.join(rep, "copilot_trace_*.jsonl")
    if not paths:
        paths = trace_files(rep)
    last = 0
    for i, a in enumerate(sys.argv):
        if a == "--last" and i + 1 < len(sys.argv):
            try:
                last = int(sys.argv[i + 1])
            except ValueError:
                last = 0
    rows = load_all(paths)
    if not rows:
        print(f"기록이 없습니다: {shown}")
        print("  (AI 판정·정제를 한 번이라도 돌린 뒤 생깁니다 — 이 PC 안에만 남고 보관기한이 지나면 지워집니다)")
        return 1
    runs = split_runs(rows)
    print(f"[trace] {shown} — 파일 {len(paths)}개 · 왕복 {sum(1 for r in rows if 'prompt' in r)}회 · 실행 {len(runs)}회분")
    pick = runs[-last:] if last else runs
    for k, run in enumerate(pick, 1):
        t0 = str(run[0].get("t", ""))[:16]
        summarize(run, f"\n■ 실행 {k if last else runs.index(run) + 1}/{len(runs)} — {t0} 시작")
    return 0


if __name__ == "__main__":
    sys.exit(main())
