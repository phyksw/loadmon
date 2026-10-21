# -*- coding: utf-8 -*-
r"""예전 판 PC 가동 기록 가져오기 (LoadMonitor30v1 · LM30(2026-10-21) — LM30v1 2026-10-21 이 판으로 옮김).

왜: Windows는 PC를 켜고 끈 기록(이벤트 로그)을 몇 주만 보관합니다. 새로 깐 LM30v1은 그 몇 주만 읽고, 그 앞 달은 PC 기록 없이
메일·파일 흔적이 있는 평일을 하루 8시간으로 채웠습니다(야근·주말 근무가 거의 잡히지 않음 — 제보: 이 PC 101% · 다른 PC 131%).
같은 PC에서 다른 판(LM28·LM29·LM30 등 — 이름이 LoadMonitor 로 시작하는 설치)을 돌렸다면 그 판의 원장(data\pc\pc_spans.csv — 추가
전용)에 그때 읽은 기록이 남아 있습니다.
이 모듈은 그 원장을 찾아 이 설치의 원장으로 가져옵니다. 대시보드·run.py 프로세스 안에서 돕니다(새 프로세스를 띄우지 않습니다).

규칙
 · 찾기(candidates) — 이 설치 폴더의 형제 폴더(1단)와 사용자 폴더의 다운로드·바탕 화면·문서(OneDrive의 바탕 화면·문서 포함) 아래
   1~2단에서 'LoadMonitor*.bat'과 data\pc\pc_spans.csv가 함께 있는 폴더(LM28·LM29·LM30 등 판 이름은 보지 않습니다). 폴더 300개·2초까지만
   봅니다. 이 설치 자신(_is_self — 이 설치 폴더, 이 설치의 data와 그 안, 원장 자리가 정션 등으로 이 설치의 data\pc와 같은 곳인 폴더)은
   찾지도 가져오지도 않습니다(LM30v1 2026-10-21).
   다른 Windows 계정의 프로필 아래 폴더는 건너뜁니다. 읽기만 합니다 — 찾은 폴더에는 아무것도 쓰지 않습니다.
 · 같은 PC인가(identify) — 그 폴더의 data\pc_id.txt와 이 PC의 MachineGuid · 없으면 data\pc_name.txt와 COMPUTERNAME · 그것도
   없으면 data\coverage_ledger.json의 host. 셋 다 없으면 모르는 PC입니다.
 · 가져오기(import_folder) — 같은 PC면 이 설치의 data\pc 원장으로(pc_ledger.append_spans — 원장 잠금 · 같은 행은 건너뜀 → 여러 번
   눌러도 한 번). 이 설치가 이미 기록한 날(직접 모은 행이 있는 날 — 출처 무관)은 건너뜁니다 — 가져오기는 이 설치가 기록하지 못한 날만
   채우고, 이미 잰 날의 숫자를 바꾸지 않습니다(자정에서 나눠 그 날 조각만 뺍니다). PC를 켜고 끈 행은 그대로이고 live 행만 event-gap으로
   바꿉니다(원장은 live 행의 끝을 시작 시각으로 갈아 끼우므로 예전 끝이 지금 세션을 줄이지 않게). 브라우저 방문 행(hint)은 이 PC
   앵커(첫 사용 시각) 뒤만 씁니다. 창 샘플러(sampler)·구판
   이행(migr)·pc_on.csv·report\ 는 계산 결과라 가져오지 않습니다. 다른 PC·모르는 PC, 그리고 그 폴더의 data\추가PC\* 원장은
   이 설치의 data\추가PC\<이름>\pc 로 갑니다(분석은 모든 PC의 구간을 합집합으로 셉니다 — 같은 시간을 두 번 세지 않습니다).
   가져온 행의 seen은 'import:<폴더 이름>'입니다(pc_ledger.IMPORT_SEEN — 분석은 이 표시로 '이 설치가 직접 모은 기록'과 가른다).
   끝나면 pc_on.csv 캐시를 다시 만들고 data\pc\pc_import.json 에 무엇을 가져왔는지 남깁니다.
 · 개인정보 — 이 PC 안에서만 읽고 씁니다. 가져온 시각 행은 이 PC의 data\ 에만 있고 팀 서버·공유폴더로 가지 않습니다.
"""
import csv
import json
import os
import re
import time
from datetime import datetime, timedelta

import pc_ledger as L

IMPORT_SEEN = L.IMPORT_SEEN
RECORD_FILE = "pc_import.json"
EXTRA_DIR = "추가PC"                      # extract.EXTRA_PC_DIR 과 같은 값
SKIP_SRC = (L.SAMPLER_SRC, L.MIGR_SRC)    # 계산 결과 — 가져오지 않는다
SCAN_MAX_DIRS = 300
SCAN_BUDGET_S = 2.0
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ════════════════════════════════ PC 식별 ════════════════════════════════
def machine_id():
    r"""이 PC의 MachineGuid(run.machine_id 와 같은 규칙 — 못 읽으면 "")."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0]).strip()
    except (OSError, ImportError, IndexError, ValueError):
        return ""


def here_identity():
    """(MachineGuid, COMPUTERNAME) — 이 PC"""
    return machine_id(), os.environ.get("COMPUTERNAME", "").strip()


def _txt(p, limit=400):
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            return f.read(limit).strip()
    except OSError:
        return ""


def identify(src_data, here_id="", here_name=""):
    r"""예전 판 data 폴더 → (같은 PC인가 True|False|None(모름), 근거 'pc_id'|'pc_name'|'ledger_host'|'', 그 PC 이름표)."""
    pid = _txt(os.path.join(src_data, "pc_id.txt"))
    name = _txt(os.path.join(src_data, "pc_name.txt"))
    if pid and here_id:
        return pid.lower() == here_id.lower(), "pc_id", name
    if name and here_name:
        return name.lower() == here_name.lower(), "pc_name", name
    host = ""
    try:
        with open(os.path.join(src_data, "coverage_ledger.json"), encoding="utf-8-sig") as f:
            host = str((json.load(f) or {}).get("host") or "").strip()
    except (OSError, ValueError, AttributeError):
        host = ""
    if host and (here_id or here_name):
        return host.lower() in {x.lower() for x in (here_id, here_name) if x}, "ledger_host", name
    return None, "", name


# ════════════════════════════════ 찾기 ════════════════════════════════
def _norm(p):
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(p)))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(p))


def _has_bat(folder):
    try:
        return any(n.lower().startswith("loadmonitor") and n.lower().endswith(".bat") for n in os.listdir(folder))
    except OSError:
        return False


def is_install(folder):
    r"""LM 설치 폴더인가 — 'LoadMonitor*.bat' 과 data\pc\pc_spans.csv 가 함께 있다."""
    return _has_bat(folder) and os.path.isfile(os.path.join(folder, "data", "pc", "pc_spans.csv"))


def source_dirs(folder):
    r"""가져올 폴더 → (data 폴더 | None, pc 폴더) — 설치 폴더(data\pc\pc_spans.csv) · data 폴더(pc\pc_spans.csv) · pc 폴더(pc_spans.csv)
    를 받는다(사람이 직접 고른 폴더 — 다른 PC에서 복사해 온 data\pc 등). 아니면 (None, None)."""
    folder = os.path.abspath(folder)
    for data, pcd in ((os.path.join(folder, "data"), os.path.join(folder, "data", "pc")),
                      (folder, os.path.join(folder, "pc")), (None, folder)):
        if os.path.isfile(os.path.join(pcd, "pc_spans.csv")):
            if data is None and os.path.basename(os.path.normpath(folder)).lower() == "pc":
                data = os.path.dirname(os.path.normpath(folder))
            return data, pcd
    return None, None


def _other_account(path):
    r"""다른 Windows 계정의 프로필 아래인가(C:\Users\<다른 계정>\…)"""
    prof = os.environ.get("USERPROFILE", "")
    if not prof:
        return False
    users = _norm(os.path.dirname(prof))
    p = _norm(path)
    return p.startswith(users + os.sep) and not (p == _norm(prof) or p.startswith(_norm(prof) + os.sep))


def _bases(root):
    """(찾을 폴더, 깊이) — 형제 폴더 1단 · 사용자 폴더 2단"""
    out = [(os.path.dirname(os.path.abspath(root)), 1)]
    prof = os.environ.get("USERPROFILE", "")
    if prof:
        for sub in ("Downloads", "Desktop", "Documents"):
            out.append((os.path.join(prof, sub), 2))
        try:
            ods = sorted(os.path.join(prof, n) for n in os.listdir(prof) if n.lower().startswith("onedrive"))
        except OSError:
            ods = []
        for od in ods:
            for sub in ("Desktop", "Documents", "바탕 화면", "문서"):
                out.append((os.path.join(od, sub), 2))
    seen, uniq = set(), []
    for b, dep in out:
        k = _norm(b)
        if k not in seen and os.path.isdir(b):
            seen.add(k)
            uniq.append((b, dep))
    return uniq


def _is_self(folder, data_dir, root=None):
    r"""LM30v1(2026-10-21) 이 설치 자신인가 — 가져올 곳으로 보지 않는다(찾기·가져오기 공용). realpath 로 견주므로 대소문자·정션·
    바로 가기 경로로 이어진 같은 폴더도 잡는다:
      · 이 설치 폴더(root 와 data_dir 의 위 폴더) · 이 설치의 data(data_dir)와 그 안의 폴더
      · 그 폴더의 원장 자리(source_dirs — data\pc · pc · 그 폴더)가 이 설치의 원장(data_dir\pc)과 같은 곳이거나 이 설치의 data 안"""
    d = _norm(data_dir)
    f = _norm(folder)
    roots = {_norm(os.path.dirname(os.path.abspath(data_dir)))} | ({_norm(root)} if root else set())
    if f == d or f.startswith(d + os.sep) or f in roots:
        return True
    _sd, spc = source_dirs(folder)
    if spc is None:
        return False
    sp = _norm(spc)
    return sp == _norm(os.path.join(data_dir, "pc")) or sp == d or sp.startswith(d + os.sep)


def candidates(root, max_dirs=SCAN_MAX_DIRS, budget_s=SCAN_BUDGET_S, bases=None, data_dir=None):
    r"""다른 판 설치 폴더 찾기 → ([폴더, …], 본 폴더 수). 판 이름은 보지 않는다 — 'LoadMonitor*.bat' + data\pc\pc_spans.csv 면
    LM28·LM29·LM30 등 모두. 이 설치 자신(_is_self — data_dir 가 없으면 root\data)과 다른 계정의 폴더는 뺀다. 읽기만 한다(폴더 목록만)."""
    me = _norm(root)
    data_dir = data_dir or os.path.join(root, "data")
    t_end = time.monotonic() + float(budget_s)
    found, seen, n = [], {me}, 0
    for base, depth in (bases if bases is not None else _bases(root)):
        level = [base]
        for _d in range(int(depth)):
            nxt = []
            for parent in level:
                try:
                    names = sorted(os.listdir(parent))
                except OSError:
                    continue
                for nm in names:
                    if n >= max_dirs or time.monotonic() > t_end:
                        return found, n
                    p = os.path.join(parent, nm)
                    k = _norm(p)
                    if k in seen or not os.path.isdir(p) or nm.startswith((".", "$")):
                        continue
                    seen.add(k)
                    n += 1
                    if _other_account(p) or _is_self(p, data_dir, root):
                        continue
                    if is_install(p):
                        found.append(p)
                    else:
                        nxt.append(p)
            level = nxt
    return found, n


# ════════════════════════════════ 읽기·계획 ════════════════════════════════
def _src_rows(pcd, data):
    r"""그 폴더의 원장 행(data\pc\pc_spans.csv + 옛 자리 data\pc_spans.csv) — 읽기만"""
    rows, _bad = L.read_spans(pcd)
    if data and _norm(data) != _norm(pcd):
        more, _bad2 = L.read_spans(data)
        rows += more
    return rows


def _plan(rows, anchor=None):
    r"""원장 행 → 가져올 행 [(a, b, src)] — sampler·migr·모르는 출처는 빼고, live 는 event-gap, hint 는 anchor 뒤만(자른다)."""
    out = []
    for a, b, s, _seen in rows:
        s = (s or "event").strip().lower()
        if s in SKIP_SRC:
            continue
        if s == L.LIVE_SRC:
            s = "event-gap"
        if s not in L.EVENT_SRC and s != L.HINT_SRC:
            continue
        if s == L.HINT_SRC and anchor is not None:
            if b <= anchor:
                continue
            a = max(a, anchor)
        if b > a:
            out.append((a, b, s))
    return out


def native_days(pcdir):
    r"""이 설치의 원장(pcdir)에 직접 모은 행(가져온 것 빼고 — 출처 무관)이 있는 날짜 집합 — 같은 PC 를 가져올 때 이 날들은 건너뛴다"""
    rows, _bad = L.read_spans(pcdir)
    out = set()
    for a, b, _s, seen in rows:
        if str(seen or "").startswith(IMPORT_SEEN):
            continue
        cur = a
        while cur < b:
            out.add(cur.date())
            cur = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
    return out


def _skip_days(rows, skip):
    r"""[(a, b, src)] → 자정에서 나눠 skip 날짜의 조각을 뺀다(이어진 조각은 다시 한 행으로) — 같은 PC 의 기록은 이 설치가 이미 그 날을
    기록했으면 그 기록이 맞다(가져오기는 이 설치가 기록하지 못한 날만 채운다 · 그 날의 숫자를 바꾸지 않는다)."""
    if not skip:
        return list(rows)
    out = []
    for a, b, s in rows:
        pieces, cur = [], a
        while cur < b:
            nxt = min(b, datetime(cur.year, cur.month, cur.day) + timedelta(days=1))
            if cur.date() not in skip:
                if pieces and pieces[-1][1] == cur:
                    pieces[-1] = (pieces[-1][0], nxt)
                else:
                    pieces.append((cur, nxt))
            cur = nxt
        out += [(x, y, s) for x, y in pieces if y > x]
    return out


def _range(rows, hint):
    ds = sorted({a.date() for a, _b, s in rows if (s == L.HINT_SRC) == hint})
    return [ds[0].isoformat(), ds[-1].isoformat()] if ds else []


def _new_count(target_pcd, rows):
    have = set()
    if os.path.isdir(target_pcd):
        cur, _bad = L.read_spans(target_pcd)
        have = {(a, b, s) for a, b, s, _x in cur}
    return sum(1 for r in set(rows) if r not in have)


def _safe_name(s, dflt="예전PC"):
    s = _BAD_NAME.sub("_", str(s or "")).strip().strip(".").strip()
    return (s[:40] or dflt)


def _extras(data):
    r"""그 폴더의 data\추가PC\<이름>\pc 원장 → [(이름, pc 폴더)]"""
    base = os.path.join(data, EXTRA_DIR) if data else ""
    out = []
    try:
        names = sorted(os.listdir(base)) if base and os.path.isdir(base) else []
    except OSError:
        names = []
    for nm in names:
        pcd = os.path.join(base, nm, "pc")
        if os.path.isfile(os.path.join(pcd, "pc_spans.csv")):
            out.append((nm, pcd))
    return out


def folder_label(folder):
    r"""폴더 이름표 — 'pc'·'data' 폴더를 고르면 그 위 폴더 이름(…\클라우드PC\data\pc → 클라우드PC)"""
    p = os.path.normpath(os.path.abspath(folder))
    while os.path.basename(p).lower() in ("pc", "data") and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return os.path.basename(p) or os.path.basename(os.path.normpath(folder)) or str(folder)


def _targets(folder, data_dir, here_id, here_name):
    r"""가져올 묶음 계획 → (정보 dict, [(대상 pc 폴더, 이름표, 같은 PC인가, 가져올 행)])"""
    src_data, src_pc = source_dirs(folder)
    info = {"folder": os.path.abspath(folder), "name": folder_label(folder),
            "same_pc": None, "how": "", "pc_name": "", "ok": src_pc is not None}
    if src_pc is None:
        return info, []
    same, how, pname = identify(src_data, here_id, here_name) if src_data else (None, "", "")
    info.update(same_pc=same, how=how, pc_name=pname)
    rows = _src_rows(src_pc, src_data)
    plans = []
    own_pc = os.path.join(data_dir, "pc")
    if same:
        anchor = L.read_anchor(own_pc)
        plans.append((own_pc, "pc", True, _skip_days(_plan(rows, anchor), native_days(own_pc))))
    else:
        nm = _safe_name(pname or info["name"])
        plans.append((os.path.join(data_dir, EXTRA_DIR, nm, "pc"), EXTRA_DIR + "\\" + nm, False, _plan(rows, None)))
    for nm, pcd in _extras(src_data):
        nm2 = _safe_name(nm)
        plans.append((os.path.join(data_dir, EXTRA_DIR, nm2, "pc"), EXTRA_DIR + "\\" + nm2, False, _plan(_src_rows(pcd, None), None)))
    all_rows = [r for _t, _n, _s, rs in plans for r in rs]
    info["events"] = _range(all_rows, False)
    info["hints"] = _range(all_rows, True)
    info["rows"] = len(all_rows)
    return info, plans


# ════════════════════════════════ 기록(pc_import.json) ════════════════════════════════
def record_path(data_dir):
    return os.path.join(data_dir, "pc", RECORD_FILE)


def read_record(data_dir):
    r"""data\pc\pc_import.json → {"v": 1, "imports": [{folder, name, when, same_pc, target, added, total, events, hints}]}"""
    try:
        with open(record_path(data_dir), encoding="utf-8-sig") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("imports"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"v": 1, "imports": []}


def _write_record(data_dir, entry):
    d = read_record(data_dir)
    key = _norm(entry["folder"])
    old = next((x for x in d["imports"] if isinstance(x, dict) and _norm(str(x.get("folder") or "")) == key), None)
    entry["total"] = int((old or {}).get("total") or 0) + int(entry.get("added") or 0)
    d["imports"] = [x for x in d["imports"] if x is not old] + [entry]
    p = record_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        L._replace_retry(tmp, p)
    except OSError:
        pass


# ════════════════════════════════ 미리 보기·가져오기 ════════════════════════════════
def preview(folder, data_dir, here_id=None, here_name=None):
    r"""한 폴더 미리 보기 → {folder, name, same_pc, how, pc_name, events:[처음, 끝], hints:[처음, 끝], rows, new(새로 들어갈 행),
    targets:[이름표], done(전에 가져온 적 있음), when(그때)}. 쓰지 않는다."""
    if here_id is None or here_name is None:
        hid, hnm = here_identity()
        here_id, here_name = (hid if here_id is None else here_id), (hnm if here_name is None else here_name)
    info, plans = _targets(folder, data_dir, here_id, here_name)
    info["new"] = sum(_new_count(t, rs) for t, _n, _s, rs in plans)
    info["targets"] = [n for _t, n, _s, _r in plans]
    rec = next((x for x in read_record(data_dir)["imports"] if isinstance(x, dict)
                and _norm(str(x.get("folder") or "")) == _norm(info["folder"])), None)
    info["done"] = bool(rec)
    info["when"] = str((rec or {}).get("when") or "")
    return info


def import_folder(folder, data_dir, here_id=None, here_name=None, root=None):
    r"""한 폴더의 PC 가동 기록을 이 설치로 가져온다 → {ok, folder, name, same_pc, how, added, targets:[{target, added}], events,
    hints, error}. 원장 잠금(pc_ledger)을 지키고, 같은 행은 건너뛴다(여러 번 해도 한 번). 그 폴더에는 아무것도 쓰지 않는다."""
    if here_id is None or here_name is None:
        hid, hnm = here_identity()
        here_id, here_name = (hid if here_id is None else here_id), (hnm if here_name is None else here_name)
    out = {"ok": False, "folder": os.path.abspath(folder), "name": folder_label(folder), "added": 0, "targets": [], "error": ""}
    if not os.path.isdir(folder):
        out["error"] = "폴더가 없습니다"
        return out
    src_data, src_pc = source_dirs(folder)
    if src_pc is None:
        out["error"] = "이 폴더에 PC 가동 기록(pc_spans.csv)이 없습니다"
        return out
    # LM30v1(2026-10-21) 이 설치 자신은 가져오지 않는다 — 이 설치 폴더(root · data 의 위 폴더)·data 와 그 안, 원장 자리가 이 설치의 원장과
    # 같은 곳(정션·대소문자만 다른 경로 포함 — _is_self)
    if _is_self(folder, data_dir, root):
        out["error"] = "이 설치 폴더 자신(또는 그 안의 폴더)입니다"
        return out
    info, plans = _targets(folder, data_dir, here_id, here_name)
    own_pc = os.path.join(data_dir, "pc")
    if info.get("same_pc") and L.read_anchor(own_pc) is None:
        # 이 설치가 아직 한 번도 수집하지 않았다 — 앵커(이 PC 첫 사용 시각)를 먼저 만들고 그 뒤 방문만 쓴다
        os.makedirs(own_pc, exist_ok=True)
        L.ensure_anchor(own_pc, own_pc=True)
        info, plans = _targets(folder, data_dir, here_id, here_name)
    out.update({k: info.get(k) for k in ("same_pc", "how", "pc_name", "events", "hints")})
    seen = IMPORT_SEEN + _safe_name(out["name"], "folder")
    try:
        for target, label, same, rows in plans:
            if not rows:
                continue
            os.makedirs(target, exist_ok=True)
            if same:
                added, _lu, _cl = L.append_spans(target, rows, seen=seen)
            else:
                ev = [r for r in rows if r[2] != L.HINT_SRC]
                added, _lu, _cl = L.append_spans(target, ev, seen=seen) if ev else (0, 0, 0)
                anchor = L.ensure_anchor(target, own_pc=False)      # 남의 폴더 — 그 PC 의 첫 물리 이벤트
                hn = [r for r in rows if r[2] == L.HINT_SRC]
                if hn:
                    a2, _lu2, _cl2 = L.append_spans(target, hn, seen=seen, anchor=anchor)
                    added += a2
            L.regen_pc_on(target, anchor=L.read_anchor(target))
            out["targets"].append({"target": label, "added": added})
            out["added"] += added
    except L.LedgerBusy as e:
        out["error"] = f"원장 잠금을 얻지 못했습니다 — 다른 수집이 쓰는 중입니다({e})"
        return out
    except (OSError, ValueError, csv.Error) as e:
        out["error"] = f"가져오지 못했습니다({type(e).__name__})"
        return out
    out["ok"] = True
    _write_record(data_dir, {"folder": out["folder"], "name": out["name"], "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                             "same_pc": out.get("same_pc"), "targets": [t["target"] for t in out["targets"]],
                             "added": out["added"], "events": out.get("events") or [], "hints": out.get("hints") or []})
    return out


def scan(root, data_dir, here_id=None, here_name=None, bases=None):
    r"""찾기 + 미리 보기 → {"found": [preview…], "scanned": 본 폴더 수, "secs": 걸린 초, "record": pc_import.json 의 imports}."""
    t0 = time.monotonic()
    if here_id is None or here_name is None:
        hid, hnm = here_identity()
        here_id, here_name = (hid if here_id is None else here_id), (hnm if here_name is None else here_name)
    found, n = candidates(root, bases=bases, data_dir=data_dir)
    pv = []
    for f in found:
        try:
            pv.append(preview(f, data_dir, here_id, here_name))
        except (OSError, ValueError, csv.Error):
            continue
    return {"found": pv, "scanned": n, "secs": round(time.monotonic() - t0, 2), "record": read_record(data_dir)["imports"]}


def native_first(data_dir):
    r"""이 설치(data\pc)가 직접 모은 PC 켜고 끈 기록(가져온 것·브라우저 방문·창 샘플러 빼고)의 첫 시각 — 없으면 None. 읽기만 한다."""
    rows, _bad = L.read_spans(os.path.join(data_dir, "pc"))
    starts = [a for a, _b, s, seen in rows if s not in (L.HINT_SRC, L.SAMPLER_SRC) and not str(seen or "").startswith(IMPORT_SEEN)]
    return min(starts) if starts else None


def needs_hint(data_dir, d0):
    r"""[분석 실행] 안내를 찾아볼 만한가 — 이 설치의 원장이 있고, 직접 모은 첫 PC 켜고 끈 기록이 분석 시작(d0 — 'YYYY-MM-DD' 또는 date)보다
    뒤다(그 앞 달은 PC 기록이 없다). 원장이 없으면(아직 수집 전) False."""
    if not os.path.isfile(os.path.join(data_dir, "pc", "pc_spans.csv")):
        return False
    first = native_first(data_dir)
    try:
        start = datetime.strptime(str(d0)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return first is None or first > start


def same_pc_text(v):
    """같은 PC 표시(쉬운 말)"""
    return {True: "이 PC", False: "다른 PC"}.get(v, "어느 PC인지 모름")


def hint_line(root, data_dir, here_id=None, here_name=None, bases=None):
    r"""[분석 실행] 진행 로그 한 줄 — 새로 가져올 행이 있는 예전 판 폴더가 있으면 안내, 없으면 "". 폴더 이름만 적는다(경로 없음)."""
    try:
        s = scan(root, data_dir, here_id, here_name, bases=bases)
    except (OSError, ValueError, csv.Error):
        return ""
    todo = [x for x in s["found"] if int(x.get("new") or 0) > 0]
    if not todo:
        return ""
    names = ", ".join(f"{x['name']}({same_pc_text(x.get('same_pc'))})" for x in todo[:4]) + (" 등" if len(todo) > 4 else "")
    return (f"[PC 기록] 예전 판 폴더 {len(todo)}곳({names})에 이 설치가 아직 가져오지 않은 PC 가동 기록이 "
            f"{sum(int(x.get('new') or 0) for x in todo):,}줄 있습니다 — 대시보드 'MM 산정 근거' 카드의 "
            "[예전 판 PC 가동 기록 가져오기]를 누른 뒤 [재분석만]을 하면 PC 기록이 없던 달을 다시 잽니다.")
