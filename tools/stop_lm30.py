# -*- coding: utf-8 -*-
r"""tools\stop_lm30.py — LoadMonitor30-강제종료.bat 의 입구: PowerShell 이 못 켜져도 끝까지 끝낸다 (LM28 2026-10-15).

  python tools\stop_lm30.py [-Status] [-IncludeTeamServer]

왜: 개발 PC(2026-10-15)에서 강제종료 bat 이 바로 띄운 powershell 이 켜지는 순간 실패해(0xc0000142) 오류 창만 남기고
    Stop-LM28.ps1 이 한 줄도 돌지 않았다 — 비상 단추가 정작 필요할 때 듣지 않았다.
  1) tools\Stop-LM30.ps1 을 tools\ps_launch 로 띄운다 — 오류 창 없이, 켜지다 실패하면 3초·8초 뒤 두 번 다시 띄운다.
     인자는 그대로 넘기고 이 파이썬의 pid 를 -KeepPid 로 붙인다(이 파이썬과 그 부모 줄기 — 강제종료 bat 창 — 는 끝내지 않게).
  2) 그래도 PowerShell 이 켜지지 못하면 같은 규칙으로 파이썬이 직접 끝낸다: select_targets 는 Stop-LM30.ps1 의
     Select-LmTargets 를 그대로 옮긴 순수 함수이고, 프로세스 목록 읽기·끝내기는 ctypes(표준 라이브러리)만 쓴다 —
     새 프로세스·WMI·관리자 권한·임시 파일 없음. 화면 문구도 Stop-LM30.ps1 과 같다.
규칙(무엇을 끝내고 무엇을 두나)의 원본은 Stop-LM30.ps1 머리말이다 — 고칠 때는 둘을 함께 고친다
(tests\test_p24_stop_startfail.py 가 같은 가짜 프로세스 목록으로 둘의 결과를 대조한다).
"""
import collections
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "tools") not in sys.path:          # 내장 파이썬(._pth)은 스크립트 폴더를 sys.path 에 넣지 않는다
    sys.path.insert(0, os.path.join(ROOT, "tools"))
import ps_launch  # noqa: E402  — tools\ps_launch.py(오류 창 막기·다시 띄우기)

STOP_PS1 = os.path.join(ROOT, "tools", "Stop-LM30.ps1")
FALLBACK_LINE = "  PowerShell 을 끝내 띄우지 못해 파이썬으로 같은 규칙대로 끝냅니다"

PY_NAMES = ("python.exe", "pythonw.exe", "py.exe")
PS_NAMES = ("powershell.exe", "pwsh.exe")
BROWSER_NAMES = ("msedge.exe", "chrome.exe", "firefox.exe", "whale.exe", "brave.exe", "opera.exe", "iexplore.exe")
SKIP_NAMES = ("conhost.exe", "explorer.exe")
KIND_KO = collections.OrderedDict([
    ("console", "콘솔 창(bat)"),
    ("python", "파이썬(대시보드·분석·수집)"),
    ("powershell", "PowerShell(수집기)"),
    ("edge", "전용 Edge(Copilot·웹 읽기)"),
    ("other", "그 밖의 자식 프로세스"),
])


def _say(s):
    print(s, flush=True)


# 프로세스 한 줄(Win32_Process 꼴) — created 는 epoch 초(모르면 None)
Proc = collections.namedtuple("Proc", "pid ppid name cmd exe created")
# 고른 항목(Stop-LM30.ps1 의 Pid·Name·Kind·Why·Keep·Created·Ppid)
Item = collections.namedtuple("Item", "pid name kind why keep created ppid")


# ── 고르기(순수 함수 — Stop-LM30.ps1 의 같은 이름 함수를 그대로 옮겼다) ─────────────────────────────
def norm(s):
    """ConvertTo-LmNorm — / → \\ · 소문자."""
    return (s or "").replace("/", "\\").lower()


def root_key(path):
    """Get-LmRootKey — 'c:\\...\\loadmonitor28\\' (끝 \\ 까지 붙여야 'loadmonitor28-old\\' 를 이 폴더로 보지 않는다)."""
    return norm(os.path.abspath(path).rstrip("\\/")) + "\\"


def older(parent, child):
    """Test-LmOlder — 부모가 자식보다 먼저 생겼나(아니면 PID 재사용). 시각을 모르면 믿는다."""
    a, b = parent.created, child.created
    if a is None or b is None:
        return True
    return a <= b


def get_keep(p):
    """Get-LmKeep — 'teamserver' | 'move' | ''."""
    name, cmd = (p.name or "").lower(), norm(p.cmd)
    if name in PY_NAMES and re.search(r"teamserver\.py", cmd):
        return "teamserver"
    if name in PS_NAMES and re.search(r"prepare-move\.ps1", cmd):
        return "move"
    return ""


def dedicated_edge(cmd, data_key):
    """Test-LmDedicatedEdge — --user-data-dir 가 이 폴더 data\\ 아래."""
    return re.search('--user-data-dir="?' + re.escape(data_key), cmd, re.I) is not None


def root_bat(cmd, key):
    """Test-LmRootBat — 명령줄이 이 폴더의 .bat."""
    return re.search(re.escape(key) + r'[^"]*?\.bat', cmd, re.I) is not None


def get_kind(p, key, data_key):
    """Get-LmKind — 맨 위 단계의 판정: 'python' | 'powershell' | 'edge' | ''."""
    name, cmd, exe = (p.name or "").lower(), norm(p.cmd), norm(p.exe)
    if name in PY_NAMES:
        return "python" if (key in cmd or exe.startswith(key)) else ""
    if name in PS_NAMES:
        # 이 폴더 안의 .ps1 을 돌린다(-File "<폴더>\collect\X.ps1") — '-Root "<폴더>"' 처럼 인자로만 나오는 것은 아니다
        return "powershell" if re.search(re.escape(key) + r"""[^"']*?\.ps1(?=["'\s]|$)""", cmd, re.I) else ""
    if name == "msedge.exe" and dedicated_edge(cmd, data_key):
        return "edge"
    return ""


def _item(p, kind, why, keep):
    return Item(int(p.pid), p.name or "", kind, why, keep, p.created, int(p.ppid))


def self_chain(by_pid, pids):
    """자기 줄기 — pids 각각과 그 부모들(생성 시각으로 PID 재사용을 거른다, 64단 까지). 끝내지 않는다."""
    out = set()
    for start in pids:
        cur, n = int(start or 0), 0
        while n < 64 and cur and cur not in out:
            out.add(cur)
            if cur not in by_pid:
                break
            pp = int(by_pid[cur].ppid)
            if pp not in by_pid or not older(by_pid[pp], by_pid[cur]):
                break
            cur, n = pp, n + 1
    return out


def select_targets(procs, root, include_team=False, self_pid=0, keep_pids=()):
    """Select-LmTargets — 프로세스 목록에서 이 폴더의 LM30 것을 고른다 → {'targets': [Item], 'kept': [Item]}(pid 순).
    self_pid·keep_pids 와 그 부모 줄기(강제종료 bat 창·이 파이썬)는 끝내지 않는다."""
    key = root_key(root)
    data_key = key + "data\\"
    by_pid, kids = {}, collections.defaultdict(list)
    for p in procs:
        if p is None:
            continue
        by_pid[int(p.pid)] = p
    for p in by_pid.values():
        if int(p.ppid) != int(p.pid):
            kids[int(p.ppid)].append(p)
    mine = self_chain(by_pid, [self_pid] + [int(x) for x in keep_pids or ()])
    sel, kept = {}, {}
    # ① 맨 위 — 이 폴더를 가리키는 것
    for pid, p in by_pid.items():
        if pid in mine:
            continue
        kind, why = get_kind(p, key, data_key), "path"
        if not kind and (p.name or "").lower() in PY_NAMES:
            par = by_pid.get(int(p.ppid))
            if par is not None and (par.name or "").lower() == "cmd.exe" and older(par, p) and root_bat(norm(par.cmd), key):
                kind, why = "python", "bat"
        if not kind:
            continue
        keep = get_keep(p)
        if keep == "move" or (keep == "teamserver" and not include_team):
            kept[pid] = _item(p, kind, why, keep)
            continue
        sel[pid] = _item(p, kind, why, keep)
    # ② 자손 — 고른 것이 띄운 것(PID 재사용은 생성 시각으로 거른다)
    queue = collections.deque(sel.values())
    while queue:
        n = queue.popleft()
        np_ = by_pid.get(n.pid)
        for c in kids.get(n.pid, ()):
            cid = int(c.pid)
            if cid in mine or cid in sel or cid in kept:
                continue
            if np_ is not None and not older(np_, c):
                continue
            cname = (c.name or "").lower()
            if cname in SKIP_NAMES:
                continue
            if cname in BROWSER_NAMES:
                # 대시보드를 연 사람의 브라우저(webbrowser.open 이 띄웠으면 부모가 우리다)는 빼고, 전용 Edge 와 그 자식만
                if n.kind == "edge" or (cname == "msedge.exe" and dedicated_edge(norm(c.cmd), data_key)):
                    sel[cid] = _item(c, "edge", f"child:{n.pid}", "")
                    queue.append(sel[cid])
                continue
            keep = get_keep(c)
            if keep == "move" or (keep == "teamserver" and not include_team):
                kept[cid] = _item(c, "python", f"child:{n.pid}", keep)
                continue
            kind = "other"
            if cname in PY_NAMES:
                kind = "python"
            elif cname in PS_NAMES:
                kind = "powershell"
            elif cname == "cmd.exe":
                kind = "console"
            sel[cid] = _item(c, kind, f"child:{n.pid}", keep)
            queue.append(sel[cid])
    # ③ 위를 띄운 이 폴더 bat 의 콘솔 창(강제종료 bat 자신은 빼고)
    for x in list(sel.values()):
        par = by_pid.get(x.ppid)
        if par is None:
            continue
        pid2 = int(par.pid)
        if pid2 in mine or pid2 in sel or pid2 in kept:
            continue
        if (par.name or "").lower() != "cmd.exe" or not older(par, by_pid[x.pid]):
            continue
        pc = norm(par.cmd)
        if not root_bat(pc, key) or "강제종료" in pc:
            continue
        sel[pid2] = _item(par, "console", f"parent:{x.pid}", "")
    return {"targets": sorted(sel.values(), key=lambda t: t.pid), "kept": sorted(kept.values(), key=lambda t: t.pid)}


def format_age(created, now):
    """Format-LmAge — 띄운 지 얼마나('12초'·'3분'·'2시간 5분'·'?')."""
    if created is None:
        return "?"
    s = int(round(max(0.0, now - created)))
    if s < 60:
        return f"{s}초"
    if s < 3600:
        return f"{s // 60}분"
    return f"{s // 3600}시간 {(s % 3600) // 60}분"


def format_state(sel, now):
    """Format-LmState — 화면에 찍을 줄들: 종류별 개수 · PID(띄운 지 얼마나) · 둔 것."""
    lines = []
    t = list(sel["targets"])
    if not t:
        lines.append("  끝낼 LM30 작업이 없습니다.")
    else:
        lines.append(f"  끝낼 것 {len(t)}개")
        for k, ko in KIND_KO.items():
            g = [x for x in t if x.kind == k]
            if not g:
                continue
            ids = " ".join(f"{x.pid}({format_age(x.created, now)})" for x in g)
            lines.append(f"   · {ko} {len(g)}개 - pid {ids}")
    for x in sel["kept"]:
        if x.keep == "teamserver":
            lines.append(f"  [둠] 팀 서버 pid {x.pid}({format_age(x.created, now)}) - 팀 전체가 쓰는 서버라 두었습니다"
                         "(함께 끄려면 LoadMonitor30-강제종료.bat -IncludeTeamServer)")
        else:
            lines.append(f"  [둠] PC 이동 준비 창 pid {x.pid} - 폴더 정리 중일 수 있어 두었습니다(그 창의 안내대로 끝내세요)")
    return lines


# ── 윈도 프로세스 읽기·끝내기(ctypes 만) ─────────────────────────────────────────────────────
_SNAPPROCESS = 0x2                 # TH32CS_SNAPPROCESS
_QUERY_LIMITED = 0x1000            # PROCESS_QUERY_LIMITED_INFORMATION
_TERMINATE = 0x0001                # PROCESS_TERMINATE
_STILL_ACTIVE = 259
_NO_SUCH_PROCESS = 87              # ERROR_INVALID_PARAMETER — 그 pid 의 프로세스가 없다
_CMDLINE_CLASS = 60                # ProcessCommandLineInformation(Windows 8.1+)
_EPOCH_TICKS = 116444736000000000  # 1601-01-01 → 1970-01-01 (100ns)


class WinProcs:
    """프로세스 목록(CreateToolhelp32Snapshot + OpenProcess·QueryFullProcessImageNameW·NtQueryInformationProcess·
    GetProcessTimes)과 끝내기(TerminateProcess). 내 계정 프로세스만 끝낼 수 있다 — 관리자 권한을 청하지 않는다."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes as W

        class _Entry(ctypes.Structure):            # PROCESSENTRY32W
            _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                        ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        class _UStr(ctypes.Structure):             # UNICODE_STRING
            _fields_ = [("Length", W.USHORT), ("MaximumLength", W.USHORT), ("Buffer", ctypes.c_void_p)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)   # 전용 인스턴스 — argtypes 가 다른 모듈에 번지지 않게
        ft = ctypes.POINTER(ctypes.c_ulonglong)
        for fn, args, res in (
                ("CreateToolhelp32Snapshot", [W.DWORD, W.DWORD], W.HANDLE),
                ("Process32FirstW", [W.HANDLE, ctypes.POINTER(_Entry)], W.BOOL),
                ("Process32NextW", [W.HANDLE, ctypes.POINTER(_Entry)], W.BOOL),
                ("OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
                ("CloseHandle", [W.HANDLE], W.BOOL),
                ("QueryFullProcessImageNameW", [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)], W.BOOL),
                ("GetProcessTimes", [W.HANDLE, ft, ft, ft, ft], W.BOOL),
                ("GetExitCodeProcess", [W.HANDLE, ctypes.POINTER(W.DWORD)], W.BOOL),
                ("TerminateProcess", [W.HANDLE, W.UINT], W.BOOL)):
            f = getattr(k, fn)
            f.argtypes, f.restype = args, res
        nt = ctypes.WinDLL("ntdll")
        nt.NtQueryInformationProcess.argtypes = [W.HANDLE, W.ULONG, ctypes.c_void_p, W.ULONG, ctypes.POINTER(W.ULONG)]
        nt.NtQueryInformationProcess.restype = ctypes.c_long
        self.ct, self.W, self.k, self.nt, self._Entry, self._UStr = ctypes, W, k, nt, _Entry, _UStr
        self._img = ctypes.create_unicode_buffer(32768)

    def list(self):
        """지금 프로세스 전체 → [Proc]. 열 수 없는 것(시스템·다른 계정)은 이름·부모만 — WMI 의 빈 명령줄과 같다."""
        ct, k = self.ct, self.k
        snap = k.CreateToolhelp32Snapshot(_SNAPPROCESS, 0)
        if not snap or snap == ct.c_void_p(-1).value:
            raise OSError(ct.get_last_error(), "프로세스 목록을 읽지 못했습니다")
        rows = []
        try:
            e = self._Entry()
            e.dwSize = ct.sizeof(self._Entry)
            ok = k.Process32FirstW(snap, ct.byref(e))
            while ok:
                rows.append((int(e.th32ProcessID), int(e.th32ParentProcessID), e.szExeFile))
                ok = k.Process32NextW(snap, ct.byref(e))
        finally:
            k.CloseHandle(snap)
        return [self._detail(pid, ppid, name) for pid, ppid, name in rows]

    def _detail(self, pid, ppid, name):
        exe = cmd = ""
        created = None
        h = self.k.OpenProcess(_QUERY_LIMITED, False, pid) if pid else None
        if h:
            try:
                exe = self._image(h)
                created = self._created(h)
                cmd = self._cmdline(h)
            finally:
                self.k.CloseHandle(h)
        return Proc(pid, ppid, name, cmd or exe, exe, created)    # 명령줄을 못 읽으면 실행 파일 경로로

    def _image(self, h):
        n = self.W.DWORD(len(self._img))
        if self.k.QueryFullProcessImageNameW(h, 0, self._img, self.ct.byref(n)):
            return self._img.value
        return ""

    def _created(self, h):
        ct = self.ct
        c, x, kt, ut = (ct.c_ulonglong() for _ in range(4))
        if self.k.GetProcessTimes(h, ct.byref(c), ct.byref(x), ct.byref(kt), ct.byref(ut)) and c.value:
            return (c.value - _EPOCH_TICKS) / 1e7
        return None

    def _cmdline(self, h):
        ct = self.ct
        n, got = 4096, self.W.ULONG(0)
        for _ in range(3):
            buf = ct.create_string_buffer(n)
            st = self.nt.NtQueryInformationProcess(h, _CMDLINE_CLASS, buf, n, ct.byref(got))
            if st == 0:
                us = self._UStr.from_buffer(buf)
                return ct.wstring_at(us.Buffer, us.Length // 2) if us.Buffer and us.Length else ""
            need = int(got.value)
            if need <= n or need > (1 << 17):
                return ""                                 # 이 Windows 가 지원하지 않음 · 권한 없음
            n = need
        return ""

    def _alive(self, h):
        code = self.W.DWORD(0)
        return bool(self.k.GetExitCodeProcess(h, self.ct.byref(code))) and code.value == _STILL_ACTIVE

    def _why(self, err):
        msg = (self.ct.FormatError(err) or "").strip()
        return f"{msg} ({err})" if msg else f"Windows 오류 {err}"

    def stop(self, pid, created):
        """→ None(끝냄 · 이미 없음 · 생성 시각이 달라 PID 재사용으로 보고 건드리지 않음) | 실패 사유."""
        k = self.k
        h = k.OpenProcess(_TERMINATE | _QUERY_LIMITED, False, int(pid))
        if not h:
            err = self.ct.get_last_error()
            return None if err == _NO_SUCH_PROCESS else self._why(err)
        try:
            if not self._alive(h):
                return None
            if created is not None:
                now_created = self._created(h)
                if now_created is not None and abs(now_created - created) > 2:
                    return None
            if k.TerminateProcess(h, 1):
                return None
            err = self.ct.get_last_error()
            return self._why(err) if self._alive(h) else None
        finally:
            k.CloseHandle(h)


def stop_targets(targets, osapi):
    """Stop-LmTargets — 콘솔 창 → 파이썬 → PowerShell → 전용 Edge → 나머지 순서로 끝낸다 → {pid: 실패 사유}."""
    fail = {}
    for k in KIND_KO:
        for t in [x for x in targets if x.kind == k]:
            why = osapi.stop(t.pid, t.created)
            if why:
                fail[t.pid] = why
    return fail


def run_fallback(root, status=False, include_team=False, *, osapi=None, say=None, sleep=time.sleep, now=time.time,
                 self_pid=None, keep_pids=()):
    """Invoke-StopLm 을 파이썬으로 → 0(다 끝냄·목록만·끝낼 것 없음) | 1(남음·오류)."""
    say = say or _say
    try:
        osapi = osapi or WinProcs()
        me = os.getpid() if self_pid is None else self_pid
        return _invoke(root, status, include_team, osapi, say, sleep, now, me, keep_pids)
    except Exception as e:  # noqa: BLE001 - Stop-LM30.ps1 의 catch 와 같다 — 사유를 보여 주고 exit 1
        say(f"  [!] 강제 종료 중 오류: {e}")
        return 1


def _invoke(root, status, include_team, osapi, say, sleep, now, me, keep_pids):
    for ln in ("", " ==========================================================",
               "  LoadMonitor30 강제 종료 - 이 폴더의 LM30 작업만 끝냅니다",
               " ==========================================================", f"  폴더: {root}", ""):
        say(ln)
    before = select_targets(osapi.list(), root, include_team, me, keep_pids)
    say("  [지금]")
    for ln in format_state(before, now()):
        say(ln)
    say("")
    if status:
        say("  (-Status - 목록만 보여 주고 아무것도 끝내지 않았습니다)")
        return 0
    n0 = len(before["targets"])
    if n0 == 0:
        say("  [결과] 이미 모두 끝나 있습니다 - 끝낼 LM30 작업이 없습니다.")
        return 0
    say("  끝내는 중...")
    fail = stop_targets(before["targets"], osapi)
    sleep(2)
    after = select_targets(osapi.list(), root, include_team, me, keep_pids)
    say("")
    say("  [끝낸 뒤]")
    for ln in format_state(after, now()):
        say(ln)
    say("")
    left = after["targets"]
    if not left:
        say(f"  [결과] LM30 작업을 모두 끝냈습니다({n0}개).")
        if any(x.keep == "teamserver" for x in after["kept"]):
            say("         팀 서버는 팀 전체가 쓰므로 그대로 두었습니다.")
        return 0
    say(f"  [결과] {len(left)}개가 아직 남아 있습니다:")
    for x in left:
        why = f"끝내지 못했습니다({fail[x.pid]})" if x.pid in fail else "끝내는 사이에 새로 시작됐습니다 - 한 번 더 실행하세요"
        say(f"   · pid {x.pid} {x.name} - {why}")
    say("         다른 계정으로 실행됐거나 보안 프로그램이 막았을 수 있습니다. PC 를 다시 시작하면 모두 끝납니다.")
    return 1


# ── 입구 ───────────────────────────────────────────────────────────────────────────────
def parse_opts(argv):
    """PowerShell 스위치처럼 읽는다(대소문자 무시 · 앞부분만 써도 됨 · -Status:$false) → (status, include_team)."""
    status = team = False
    for a in argv:
        s = str(a).strip().lower()
        if len(s) < 2 or not s.startswith("-"):
            continue
        name, _, val = s.lstrip("-").partition(":")
        on = val not in ("$false", "false", "0")
        if name and "status".startswith(name):
            status = on
        elif name and "includeteamserver".startswith(name):
            team = on
    return status, team


def main(argv, *, runner=None, sleep=None, clock=None, say=None, fallback=None):
    """Stop-LM30.ps1 을 띄우고(→ 그 종료 코드), 끝내 못 켜지면 파이썬으로 같은 규칙대로 끝낸다."""
    say = say or _say
    args = list(argv) + ["-KeepPid", str(os.getpid())]
    rc, failed = ps_launch.launch(STOP_PS1, args, runner=runner, sleep=sleep, clock=clock, say=say)
    if not failed:
        return ps_launch.exit_code(rc)
    say(FALLBACK_LINE)
    status, team = parse_opts(argv)
    if fallback is not None:
        return fallback(ROOT, status, team, say=say)
    return run_fallback(ROOT, status, team, say=say)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(1)
