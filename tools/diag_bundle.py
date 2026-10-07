# -*- coding: utf-8 -*-
r"""diag_bundle.py — 메일·일정·팀즈 수집이 왜 비는지 보는 '진단 묶음' 한 파일 (LM28).

LoadMonitor28-수집진단.bat 이 Diagnose-Collectors.ps1 다음에 부른다. 이 PC 의 실행 기록(report\last_run.json)·
날짜별 원장(data\coverage_ledger.json)·출처별 상태(data\outlook\*.json·src\*.json·m365\*.json)·수집 진단
(report\collect_diag.txt)·수집 CSV 의 **월별 건수**를 바탕화면 텍스트 파일 하나로 모은다.

담지 않는 것: 메일·일정·채팅의 제목·본문·사람 이름·주소·방 이름. 이메일 주소, 사용자 폴더 경로, PC·계정 이름은 가린다.
이름·제목·주소처럼 보이는 키(name·title·subject·addr·from·to·me …)의 값은 '<가림>' 으로 바꾼다.
보내기 전에 파일을 열어 직접 확인할 수 있다 — 그래서 바이너리(zip)가 아니라 텍스트다.

  python tools\diag_bundle.py [--out <파일>] [--root <설치 폴더>]
"""
import csv
import glob
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSONAL_KEY = re.compile(r"(name|title|subject|addr|address|email|mail_?box|who|from|to|cc|bcc|sender|recipient|"
                          r"participant|owner|account|user|upn|display|me|my_?addrs|organizer|attendee|body|text|"
                          r"preview|path|folder|file)s?$", re.I)
SAFE_KEYS = {"source", "src", "status", "st", "reason", "rc", "axis", "from_date", "to_date", "date_only", "mode",
             "path_id", "kind", "state"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
DATE_COL = re.compile(r"^(time|date|start|ts|when|sent|received|datetime|start_time|ts_local)$", re.I)


def _maskers():
    pairs = []
    prof = os.environ.get("USERPROFILE", "")
    if prof:
        pairs.append((re.compile(re.escape(prof), re.I), "%USERPROFILE%"))
    for env, tag in (("USERNAME", "<계정>"), ("COMPUTERNAME", "<PC>"), ("USERDOMAIN", "<도메인>")):
        v = os.environ.get(env, "")
        if len(v) >= 3:
            pairs.append((re.compile(r"(?<![\w])" + re.escape(v) + r"(?![\w])", re.I), tag))
    return pairs


MASKS = _maskers()


def mask_text(s):
    s = EMAIL.sub("<메일주소>", str(s))
    for rx, tag in MASKS:
        s = rx.sub(tag, s)
    return s


def mask_obj(o, key=""):
    """JSON 값 가리기 — 이름·제목·주소 같은 키의 값은 '<가림>', 나머지 문자열은 메일·경로·PC 이름만 가린다."""
    if isinstance(o, dict):
        return {k: mask_obj(v, k) for k, v in o.items()}
    if isinstance(o, list):
        if key and PERSONAL_KEY.search(key) and key.lower() not in SAFE_KEYS:
            return f"<가림: {len(o)}개>"
        return [mask_obj(v, key) for v in o]
    if isinstance(o, str):
        if key and PERSONAL_KEY.search(key) and key.lower() not in SAFE_KEYS and o:
            return f"<가림: {len(o)}자>"
        return mask_text(o)
    return o


def _read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        return {"_읽기_실패": type(e).__name__}


def csv_month_counts(p):
    """CSV 의 월별 행 수(날짜 열을 이름으로 찾음)와 src·direction 별 수 — 내용은 읽지 않는다."""
    months, by_src = Counter(), Counter()
    rows = 0
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(p, encoding=enc, newline="") as f:
                rd = csv.DictReader(f)
                cols = rd.fieldnames or []
                dcol = next((c for c in cols if c and DATE_COL.match(c.strip())), None)
                for r in rd:
                    rows += 1
                    d = str(r.get(dcol) or "")[:7] if dcol else ""
                    months[d if re.match(r"^\d{4}-\d{2}$", d) else "(날짜 없음)"] += 1
                    for k in ("src", "source", "direction", "dir", "kind"):
                        v = str(r.get(k) or "")
                        if v and re.match(r"^[\w.:@-]{1,24}$", v) and "@" not in v:
                            by_src[f"{k}={v}"] += 1
            return rows, dict(sorted(months.items())), dict(by_src.most_common(12)), (dcol or "(날짜 열 못 찾음)")
        except UnicodeDecodeError:
            months.clear()
            by_src.clear()
            rows = 0
            continue
        except OSError as e:
            return 0, {}, {}, f"읽기 실패({type(e).__name__})"
    return rows, dict(months), dict(by_src), "인코딩 모름"


def ledger_summary(led):
    """원장 {날짜: {축: {st,...}}} 같은 모양을 축 × 상태 × 월 일수로 요약(모양이 달라도 죽지 않게)."""
    out = defaultdict(Counter)
    days = led.get("days") if isinstance(led, dict) and isinstance(led.get("days"), dict) else led
    if not isinstance(days, dict):
        return {}
    for d, axes in days.items():
        if not (isinstance(d, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", d) and isinstance(axes, dict)):
            continue
        for ax, v in axes.items():
            st = v.get("st") or v.get("status") if isinstance(v, dict) else v
            out[f"{ax}"][f"{d[:7]} {st}"] += 1
    return {ax: dict(sorted(c.items())) for ax, c in sorted(out.items())}


def build(root):
    data, rep = os.path.join(root, "data"), os.path.join(root, "report")
    L = [f"LM28 수집 진단 묶음 — 만든 시각 {time.strftime('%Y-%m-%d %H:%M')} · 설치 폴더 {mask_text(root)}",
         "담긴 것: 실행 기록·날짜별 원장 요약·출처별 상태·수집 진단·CSV 월별 건수. 제목·본문·이름·주소·방 이름은 없습니다.", ""]

    def section(title, obj):
        L.append("=" * 8 + f" {title}")
        L.append(json.dumps(obj, ensure_ascii=False, indent=1) if not isinstance(obj, str) else obj)
        L.append("")

    lr = os.path.join(rep, "last_run.json")
    section("실행 기록 report\\last_run.json", mask_obj(_read_json(lr)) if os.path.exists(lr) else "(없음 — 분석/수집을 한 번 돌린 뒤 다시 실행하세요)")
    led = os.path.join(data, "coverage_ledger.json")
    if os.path.exists(led):
        lj = _read_json(led)
        meta = {k: v for k, v in lj.items() if k != "days"} if isinstance(lj, dict) else {}
        section("날짜별 원장 요약(축 → '월 상태': 일수)", {"meta": mask_obj(meta), "요약": ledger_summary(lj)})
    else:
        section("날짜별 원장", "(없음)")
    status_files = sorted(set(glob.glob(os.path.join(data, "outlook", "*.json")) + glob.glob(os.path.join(data, "outlook", "src", "*.json"))
                              + glob.glob(os.path.join(data, "m365", "*.json")) + glob.glob(os.path.join(data, "*source*.json"))
                              + glob.glob(os.path.join(data, "activity", "sampler_status.json"))))
    for p in status_files:
        section(f"상태 {os.path.relpath(p, root)}", mask_obj(_read_json(p)))
    rooms = glob.glob(os.path.join(data, "**", "teams_web_rooms.json"), recursive=True)
    for p in rooms:
        j = _read_json(p)
        n = len(j) if isinstance(j, (list, dict)) else 0
        section(f"팀즈 방 목록 {os.path.relpath(p, root)}", f"방 {n}개(이름은 담지 않음)")
    csvs = sorted(glob.glob(os.path.join(data, "outlook", "*.csv")) + glob.glob(os.path.join(data, "outlook", "src", "*.csv"))
                  + glob.glob(os.path.join(data, "teams*", "*.csv")) + glob.glob(os.path.join(data, "*teams*.csv"))
                  + glob.glob(os.path.join(data, "m365", "*.csv")))
    counts = {}
    for p in csvs:
        rows, months, by, dcol = csv_month_counts(p)
        counts[os.path.relpath(p, root)] = {"행": rows, "날짜열": dcol, "월별": months, "구분": by}
    section("수집 CSV 월별 건수(내용 없음)", counts or "(CSV 없음)")
    diag = os.path.join(rep, "collect_diag.txt")
    if os.path.exists(diag):
        with open(diag, encoding="utf-8-sig", errors="replace") as f:
            section("수집 진단 report\\collect_diag.txt(마스킹본)", mask_text(f.read()))
    return "\n".join(L)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = argv[argv.index("--root") + 1] if "--root" in argv else ROOT
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(
        os.path.join(os.environ.get("USERPROFILE", root), "Desktop"), f"LM28_수집진단_{time.strftime('%Y%m%d_%H%M')}.txt")
    text = build(root)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text)
    print(f"[진단 묶음] {out}")
    print("  이 파일 하나를 개발 쪽에 보내 주세요 — 보내기 전에 열어서 내용을 확인할 수 있습니다(제목·이름·주소 없음).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
