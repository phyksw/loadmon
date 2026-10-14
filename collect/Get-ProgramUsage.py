# -*- coding: utf-8 -*-
r"""
Get-ProgramUsage.py — 이 사용자 계정의 프로그램 실행 흔적 스냅샷(LM28 · 샘플러 없이 · 관리자 권한 불필요 · 1초 안팎).

왜: 사용자 요청 — 상용(Ansys·Creo 등 각종 시뮬레이션)·비상용(무료·자체 개발·프로토타입) 프로그램을 쓴 이력도 보고 싶다.
    LM28 은 창 샘플러를 없앴다(사용자 요청 — 상주 프로세스·예약 작업 금지). 그래서 Windows 가 이미 계정에 남겨 둔 실행
    흔적을 수집할 때마다 한 장씩 찍어 둔다. 흔적은 누적 카운터라 두 장의 차이가 그 사이 사용량이다
    (기간 계산은 core\extract.tool_usage — 투입 MM·로드율과 무관한 참고 지표).

읽는 곳(전부 읽기 전용 · 프로세스를 띄우지 않는다 · winreg 만)
  · UserAssist  HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist\{GUID}\Count — 탐색기·시작 메뉴·
      작업 표시줄로 띄운 프로그램. 값 이름은 ROT13. Win7+ 값은 72바이트: 실행 횟수 int32 @4 · 포커스 횟수 @8 ·
      포커스 시간(ms) uint32 @12 · 마지막 실행 FILETIME uint64 @60. 실행 파일 GUID{CEBFF5CD…}·바로 가기 GUID{F4E57C4B…}
      둘 다 본다. UEME_* 는 장부라 뺀다. 형식이 다른 값(옛 16바이트 등)은 건수만 센다.
  · FeatureUsage  HKCU\…\Explorer\FeatureUsage\AppSwitched·AppLaunch — 작업 표시줄 전환·실행 횟수(Win10 1809+).
  · BAM/DAM  HKLM\SYSTEM\CurrentControlSet\Services\bam\State\UserSettings\<내 SID> — 마지막 실행 시각(명령줄·자식
      프로세스까지 남는다). 보통 사용자 권한으로는 못 읽는 PC 가 있다 — 권한 오류·없음이면 건너뛰고 사유를 counts 에
      남긴다(실패가 아니다 — 개발 PC 실측: 보통 사용자는 denied).
  · '앱 실행 추적'(Start_TrackProgs=0)·정책 NoInstrumentation=1 이면 UserAssist 가 늘지 않는다 — ua_track=0 으로 남기고
      요약 줄에 사유를 적는다(화면이 '안 썼다' 와 '기록이 꺼졌다' 를 가른다).

개인정보(★): 전체 경로는 저장하지 않는다 — 사용자 이름·과제 폴더가 들어 있다. 남기는 것은
  · 실행 파일 이름(소문자, .exe 뗌) 또는 앱 이름(AUMID) · 경로 등급(pf · pf86 · windows · user · appdata · other_drive ·
    network · store · unknown) · 공급사 폴더(Program Files·ProgramData 바로 아래 폴더 — 'ansys inc'. 그 밖의 경로에서는
    core\programs.VENDOR_DIRS 에 있는 폴더일 때만 — D:\홍길동\… 의 첫 폴더는 사람·과제 이름일 수 있다).
  · appdata 는 사용자 계정에 설치된 앱(Slack·Zoom 같은 AppData\Local\Programs) — 자체 도구 후보에서 뺀다. ClickOnce
    배포(AppData\Local\Apps\2.0)는 사내 배포 도구의 흔한 자리라 user 로 본다. user·other_drive 실행 파일의 폴더(두 단계
    위까지)에 제거 프로그램(이름이 unins 로 시작하는 .exe — unins000·uninstall·'Uninstall <앱>')이 있으면 inst=1 — D:\ 에
    설치한 게임·방송·편집 도구가 '자체 도구' 로 읽히던 것(개발 PC 실측). 경로는 그 자리에서 확인만 하고 남기지 않는다.
  · 바로 가기(.lnk) 이름은 문서·폴더 이름일 수 있어 카탈로그(core\programs)에 맞는 것만 그 별칭으로 남긴다.
  · excludePathKeywords(개인 폴더 — core\privacy.excluded_keywords, 파일·Recent·git 수집기와 같은 규칙)에 걸리는 경로는
    이름도 남기지 않는다(건수만). 기본값의 downloads·temp 가 내려받은 설치 파일·임시 실행 파일을 함께 걸러 준다.
출력: data\programs\snap_<YYYYMMDD_HHMMSS>.json (원자적 쓰기) — 같은 날·같은 PC 의 앞선 스냅샷은 지우고(하루 1장 —
  분석은 날짜 단위라 그날의 마지막 장만 쓴다. 그래야 400장이 1년 넘게 간다) 최신 400장만 둔다. 읽을 수 있는 흔적이
  하나도 없으면 쓰지 않는다(빈 장 뒤의 다음 장이 누적값 전체를 '그 사이 사용' 으로 만든다).
마지막 줄: LMSTATUS {v,src:'programs',rc,reason,counts,ranges:[]} — counts 는 건수·짧은 사유 코드만.
  rc 0 정상 · 1 읽을 흔적 없음(종료 코드 0) · 3 R-NOREG(레지스트리 없음)·R-WRITE(저장 실패)(종료 코드 3).

  python collect\Get-ProgramUsage.py
"""
import codecs
import hashlib
import io
import json
import os
import re
import struct
import sys
import time
from datetime import UTC, datetime, timedelta

if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽(시험)의 stdout 이 교체·GC 되면 출력이 죽는다
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# core 의 카탈로그(바로 가기 별칭·공급사 폴더)·제외어 단일원 — 없으면(수집기 단독 사본) 바로 가기는 남기지 않고 설정 제외어만 쓴다
sys.path.insert(0, os.path.join(ROOT, "core"))
try:
    import programs as _P
except ImportError:
    _P = None
try:
    import privacy as _PV
except ImportError:
    _PV = None

OUT_DIR = os.path.join(ROOT, "data", "programs")
KEEP = 400
UA_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
UA_EXE = "{CEBFF5CD-ACE2-4F4F-9178-9926F41749EA}"      # 실행 파일
UA_LNK = "{F4E57C4B-2036-45F0-A9AB-443BCFE33D9F}"      # 바로 가기
UA_SIZE = 72
FU_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage"
FU_SUBS = (("AppSwitched", "fu_sw"), ("AppLaunch", "fu_la"))
BAM_KEYS = (r"SYSTEM\CurrentControlSet\Services\bam\State\UserSettings",
            r"SYSTEM\CurrentControlSet\Services\bam\UserSettings",            # 1709 이전 자리
            r"SYSTEM\CurrentControlSet\Services\dam\State\UserSettings",
            r"SYSTEM\CurrentControlSet\Services\dam\UserSettings")
MAX_ITEMS = 6000             # 병적 레지스트리 방어 — 보통 수백 건
TS_FMT = "%Y-%m-%d %H:%M:%S"
_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
PATH_ONLY_KW = {"temp", "downloads", "다운로드", "임시"}   # core/extract.PATH_ONLY_KW 와 같은 목록(폴더명 완전 일치)
EXEC_EXTS = (".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".py", ".pyw", ".jar", ".appref-ms")

# 알려진 폴더(KNOWNFOLDERID) → 그 폴더 자리의 가짜 경로 앞부분(소문자). 사용자 폴더 자리는 '*' — 실제 계정 이름은 모르고
# 남기지도 않는다. 경로 등급은 이 앞부분을 붙인 가짜 경로로 path_class 가 정한다(진짜 경로와 같은 규칙).
_U = "c:\\users\\*"
_SM = "\\microsoft\\windows\\start menu"
KNOWN = {
    "{905E63B6-C1BF-494E-B29C-65B732D3D21A}": "c:\\program files",
    "{6D809377-6AF0-444B-8957-A3773F02200E}": "c:\\program files",
    "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": "c:\\program files (x86)",
    "{F7F1ED05-9F6D-47A2-AAAE-29D317C6F066}": "c:\\program files\\common files",
    "{6365D5A7-0F0D-45E5-87F6-0DA56B6A4F7D}": "c:\\program files\\common files",
    "{DE974D24-D9C6-4D3E-BF91-F4455120B917}": "c:\\program files (x86)\\common files",
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": "c:\\windows\\system32",
    "{D65231B0-B2F1-4857-A4CE-A8E7C6EA7D27}": "c:\\windows\\syswow64",
    "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": "c:\\windows",
    "{62AB5D82-FDC1-4DC3-A9DD-070D1D495D97}": "c:\\programdata",
    "{0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8}": "c:\\programdata" + _SM + "\\programs",
    "{A4115719-D62E-491D-AA7C-E74B8BE3B067}": "c:\\programdata" + _SM,
    "{82A5EA35-D9CD-47C5-9629-E15D2F714E6E}": "c:\\programdata" + _SM + "\\programs\\startup",
    "{D0384E7D-BAC3-4797-8F14-CBA229B392B5}": "c:\\programdata" + _SM + "\\programs\\administrative tools",
    "{DFDF76A2-C82A-4D63-906A-5644AC457385}": "c:\\users\\public",
    "{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}": "c:\\users\\public\\desktop",
    "{ED4824AF-DCE4-45A8-81E2-FC7965083634}": "c:\\users\\public\\documents",
    "{5E6C858F-0E22-4760-9AFE-EA3317B67173}": _U,
    "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}": _U + "\\desktop",
    "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}": _U + "\\documents",
    "{374DE290-123F-4565-9164-39C4925E467B}": _U + "\\downloads",
    "{4BD8D571-6D19-48D3-BE97-422220080E43}": _U + "\\music",
    "{33E28130-4E1E-4676-835A-98395C3BC3BB}": _U + "\\pictures",
    "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}": _U + "\\videos",
    "{1777F761-68AD-4D8A-87BD-30B759FA33DD}": _U + "\\favorites",
    "{A52BBA46-E9E1-435F-B3D9-28DAA648C0F6}": _U + "\\onedrive",
    "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}": _U + "\\appdata\\local",
    "{A520A1A4-1780-4FF6-BD18-167343C5AF16}": _U + "\\appdata\\locallow",
    "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}": _U + "\\appdata\\roaming",
    "{5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}": _U + "\\appdata\\local\\programs",
    "{BCBD3057-CA5C-4622-B42D-BC56DB0AE516}": _U + "\\appdata\\local\\programs\\common",
    "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}": _U + "\\appdata\\roaming" + _SM + "\\programs",
    "{625B53C3-AB48-4EC1-BA1F-A1EF4146FC19}": _U + "\\appdata\\roaming" + _SM,
    "{B97D20BB-F46A-4C97-BA10-5E3608430854}": _U + "\\appdata\\roaming" + _SM + "\\programs\\startup",
    "{724EF170-A42D-4FEF-9F26-B60E846FBA4F}": _U + "\\appdata\\roaming" + _SM + "\\programs\\administrative tools",
    "{9E3995AB-1F9C-4F13-B827-48B24B6C7174}": _U + "\\appdata\\roaming\\microsoft\\internet explorer\\quick launch\\user pinned",
    "{52A4F021-7B75-48A9-9F6B-4B87A210BC8F}": _U + "\\appdata\\roaming\\microsoft\\internet explorer\\quick launch",
}
_GUID_RX = re.compile(r"^(\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\})(.*)$")
_AUMID_OFFICE = re.compile(r"^microsoft\.office\.([a-z0-9]+)\.exe\.\d+$")   # Microsoft.Office.WINWORD.EXE.15
_PKG_HASH = re.compile(r"_[a-z0-9]{13}$")                                  # 패키지 계열 이름 끝 _8wekyb3d8bbwe
_HEX_TAIL = re.compile(r"-[0-9a-f]{16}$")                                  # Firefox-308046B0AF4A39CB
_SNAP_RX = re.compile(r"^snap_(\d{8})_(\d{6})\.json$")


class WinReg:
    """실제 레지스트리 — 읽기만 한다(KEY_READ). 시험은 같은 두 메서드(values·subkeys)를 가진 가짜를 넣는다.
    없는 키는 FileNotFoundError, 권한이 없으면 PermissionError(둘 다 OSError) 를 그대로 올린다."""

    def __init__(self):
        import winreg
        self.w = winreg
        self.hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}

    def _open(self, hive, path):
        acc = self.w.KEY_READ | (self.w.KEY_WOW64_64KEY if hive == "HKLM" else 0)
        return self.w.OpenKey(self.hives[hive], path, 0, acc)

    def values(self, hive, path):
        """[(이름, 값, 형식)]"""
        with self._open(hive, path) as k:
            out = []
            for i in range(self.w.QueryInfoKey(k)[1]):
                try:
                    out.append(self.w.EnumValue(k, i))
                except OSError:
                    break
            return out

    def subkeys(self, hive, path):
        with self._open(hive, path) as k:
            out = []
            for i in range(self.w.QueryInfoKey(k)[0]):
                try:
                    out.append(self.w.EnumKey(k, i))
                except OSError:
                    break
            return out


def rot13(s):
    return codecs.decode(str(s or ""), "rot_13")


def filetime_local(ft):
    """FILETIME(1601 기준 100ns · UTC) → 이 PC 지역 시각(naive) · 0·깨진 값·2000년 이전·내일 이후면 None."""
    try:
        ft = int(ft or 0)
        if ft <= 0:
            return None
        t = (_EPOCH + timedelta(microseconds=ft // 10)).astimezone().replace(tzinfo=None)
    except (OverflowError, OSError, ValueError, TypeError):
        return None
    if t.year < 2000 or t > datetime.now() + timedelta(days=2):
        return None
    return t


def parse_ua(data):
    """UserAssist 값(Win7+ 72바이트) → (실행 횟수, 포커스 횟수, 포커스 ms, 마지막 실행 또는 None) · 형식이 다르면 None."""
    if not isinstance(data, (bytes, bytearray)) or len(data) != UA_SIZE:
        return None
    _sess, runs, focus, ms = struct.unpack_from("<IIII", data, 0)
    if runs > 10_000_000 or focus > 100_000_000:          # 깨진 값 — 누적이라도 이만큼은 없다
        return None
    return runs, focus, ms, filetime_local(struct.unpack_from("<Q", data, 60)[0])


def _vendor_ok(seg):
    return bool(_P and _P.vendor_of_folder(seg))


def path_class(low):
    """정규화한 경로(소문자 · '\\' 구분) → (경로 등급, 공급사 폴더).
    등급: pf(Program Files·ProgramData) · pf86 · windows · user(사용자 폴더·ClickOnce) · appdata(계정에 설치된 앱) ·
    other_drive(그 밖의 로컬 경로 — 다른 드라이브·C:\\ 의 표준 밖 폴더) · network · store · unknown."""
    if low.startswith("\\\\"):
        return "network", ""
    m = re.match(r"^[a-z?]:\\(.*)$", low)
    if not m:
        return "unknown", ""
    segs = [x for x in m.group(1).split("\\") if x]
    if len(segs) < 2:
        return "other_drive", ""                    # 드라이브 바로 아래 실행 파일 — 설치된 자리가 아니다
    s0 = segs[0]
    if s0 in ("program files", "program files (x86)"):
        if segs[1] == "windowsapps":
            return "store", ""
        vf = segs[1] if len(segs) > 2 else ""
        if vf == "common files":
            vf = segs[2] if len(segs) > 3 else ""
        return ("pf" if s0 == "program files" else "pf86"), vf[:40]
    if s0 == "programdata":
        return "pf", (segs[1] if len(segs) > 2 else "")[:40]
    if s0 == "windows":
        return "windows", ""
    if s0 == "users":
        if len(segs) > 3 and segs[2] == "appdata":
            if segs[3] == "local" and len(segs) > 5 and segs[4] == "apps" and segs[5] == "2.0":
                return "user", ""                   # ClickOnce — 사내 배포 도구의 흔한 자리(자체 도구 후보)
            return "appdata", ""
        return "user", ""
    return "other_drive", (s0[:40] if _vendor_ok(s0) else "")


def _app_seg(s):
    """AUMID·패키지 계열 이름 → 앱 이름 조각(카탈로그가 맞힐 수 있게): microsoft.windows.explorer → explorer."""
    for pre in ("microsoft.windows.", "microsoft.", "com.squirrel.", "windows."):
        if s.startswith(pre) and len(s) > len(pre):
            s = s[len(pre):]
            break
    return s.split(".")[0][:60]


def split_name(raw):
    """레지스트리 값 이름(ROT13 을 푼 것) → {"exe","cls","vf","lnk","path"} 또는 None(장부·자동 생성 이름·문서·폴더).
    path 는 개인 폴더 판정에만 쓰고 저장하지 않는다."""
    s = str(raw or "").strip().strip('"')
    if not s or s.upper().startswith("UEME_") or s.startswith("*"):      # 장부 · 작업 표시줄의 *PID 임시 번호
        return None
    unknown_guid = False
    m = _GUID_RX.match(s)
    if m:
        base = KNOWN.get(m.group(1).upper())
        rest = m.group(2).lower().replace("/", "\\")
        if not rest.startswith("\\"):
            rest = "\\" + rest
        low = (base + rest) if base else ("?:\\?" + rest)
        unknown_guid = base is None
    else:
        low = s.lower().replace("/", "\\")
    if low.startswith("microsoft.autogenerated."):
        return None
    if low.startswith("\\device\\"):                                     # BAM — \Device\HarddiskVolume3\… · \Device\Mup\…
        low = "\\\\" + low[len("\\device\\mup\\"):] if low.startswith("\\device\\mup\\") else re.sub(r"^\\device\\[^\\]+", "?:", low)
    if "\\" in low or re.match(r"^[a-z?]:", low):
        name = low.rstrip("\\").rsplit("\\", 1)[-1]
        lnk = name.endswith(".lnk")
        if not lnk and not name.endswith(EXEC_EXTS):
            return None                                                   # 문서·폴더 — 프로그램이 아니다
        cls, vf = ("unknown", "") if unknown_guid else path_class(low)
        if name.endswith(".appref-ms"):
            cls, vf = "user", ""                                          # ClickOnce 앱 참조 — 사내 배포 도구
        exe = name[:-4] if (lnk or name.endswith(".exe")) else name
        return {"exe": exe[:80], "cls": cls, "vf": vf, "lnk": lnk, "path": low} if exe else None
    m = _AUMID_OFFICE.match(low)
    if m:
        return {"exe": m.group(1), "cls": "pf", "vf": "", "lnk": False, "path": low}
    if "!" in low:                                                        # 패키지 앱 Microsoft.WindowsTerminal_8wekyb3d8bbwe!App
        exe, cls = _app_seg(_PKG_HASH.sub("", low.split("!", 1)[0])), "store"
    elif _PKG_HASH.search(low):                                           # BAM 의 패키지 계열 이름
        exe, cls = _app_seg(_PKG_HASH.sub("", low)), "store"
    else:
        exe = _app_seg(_HEX_TAIL.sub("", low))
        cls = "windows" if low.startswith("microsoft.windows.") else "unknown"
    return {"exe": exe, "cls": cls, "vf": "", "lnk": False, "path": low} if exe else None


def installed(low):
    """사용자 폴더·다른 드라이브의 실행 파일이 설치 프로그램으로 깔린 것인가 — 그 폴더나 두 단계 위까지에 제거 프로그램
    (unins000.exe · uninstall.exe · 'Uninstall <앱>.exe' — 이름이 unins 로 시작하는 .exe)이 있으면 그렇다. OBS 처럼 실행 파일이
    bin\\64bit 아래에 있고 제거 프로그램은 설치 뿌리에 있는 꼴이 흔하다(개발 PC 실측). 사내 도구·시험판은 보통 제거 프로그램
    없이 복사해 쓴다. 알려진 폴더 자리(c:\\users\\*)는 이 계정의 실제 폴더로 바꿔 확인만 한다(저장하지 않는다).
    네트워크·모르는 드라이브·확인 실패는 False(모름 — 자체 도구 후보로 둔다)."""
    if low.startswith("\\\\") or low.startswith("?"):
        return False
    real = low
    if real.startswith(_U + "\\"):
        prof = os.environ.get("USERPROFILE", "")
        if not prof:
            return False
        real = prof + real[len(_U):]
    folder = os.path.dirname(real)
    for _ in range(3):
        if len(folder) <= 3:                        # 드라이브 뿌리는 보지 않는다
            break
        try:
            if any(n.lower().startswith("unins") and n.lower().endswith(".exe") for n in os.listdir(folder)):
                return True
        except OSError:
            pass                                    # 없는 폴더·권한 — 위 폴더는 계속 본다
        folder = os.path.dirname(folder)
    return False


def make_excl(words):
    """excludePathKeywords 판정기 path → 걸린 키워드 또는 ''. 파일·Recent·git 수집기·core/extract._text_filter 와 같은 규칙:
     · 경로 전용 토큰(temp·downloads·임시·다운로드)은 폴더명 완전 일치('temp'⊄'temperature')
     · ASCII 키워드는 단어 경계 · 한글은 부분일치('개인'⊂'개인자료' — 마지막 방어선)"""
    kws = [str(k).strip().lower() for k in (words or []) if str(k).strip()]
    seg = {k for k in kws if k in PATH_ONLY_KW}
    kr = [k for k in kws if not k.isascii() and k not in PATH_ONLY_KW]
    asc = [k for k in kws if k.isascii() and k not in PATH_ONLY_KW]
    pat = re.compile("|".join(f"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])" for k in asc)) if asc else None

    def hit(path):
        low = str(path or "").lower()
        parts = [x for x in re.split(r"[\\/]+", low) if x]
        h = next((k for k in seg if k in parts), "")
        if not h:
            h = next((k for k in kr if k in low), "")
        if not h and pat:
            m = pat.search(low)
            h = m.group(0) if m else ""
        return h
    return hit


def _excl_words(cfg):
    if _PV is not None:
        try:
            return _PV.excluded_keywords(cfg)
        except Exception:  # noqa: BLE001 - 제외어 단일원이 깨져도 설정 목록으로는 거른다
            pass
    v = (cfg or {}).get("excludePathKeywords")
    return [v] if isinstance(v, str) else (v if isinstance(v, list) else [])


def collect(reg, cfg=None, sid=""):
    """레지스트리 → (항목 목록, counts, sources). 원천마다 따로 실패한다(하나가 막혀도 나머지는 남긴다).
    같은 (이름, 등급, 공급사 폴더, 바로 가기 여부)는 한 항목 — 횟수는 더하고 시각은 늦은 쪽(판이 둘인 같은 도구)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    extra = cfg.get("programsExtra") if isinstance(cfg.get("programsExtra"), list) else []
    hit = make_excl(_excl_words(cfg))
    items = {}
    c = {"ua": 0, "ua_lnk": 0, "ua_bad": 0, "lnk_skip": 0, "fu": 0, "bam": 0, "excluded": 0, "skipped": 0}
    src = {"ua": False, "fu": False, "bam": False, "bam_why": ""}

    def put(raw, **vals):
        nm = split_name(raw)
        if nm is None:
            c["skipped"] += 1
            return False
        if hit(nm["path"]):
            c["excluded"] += 1                          # 개인 폴더 — 이름도 남기지 않는다
            return False
        exe, k = nm["exe"], ""
        if nm["lnk"]:
            alias = _P.match_key(_P.lnk_key(exe), extra) if _P is not None else None
            if not alias:
                c["lnk_skip"] += 1                      # 카탈로그 밖 바로 가기(문서·폴더일 수 있다)는 남기지 않는다
                return False
            exe, k = alias, "lnk"
        key = (exe, nm["cls"], nm["vf"], k)
        it = items.get(key)
        if it is None:
            if len(items) >= MAX_ITEMS:
                return False
            it = items[key] = {"exe": exe, "cls": nm["cls"]}
            if nm["vf"]:
                it["vf"] = nm["vf"]
            if k:
                it["k"] = k
        if not k and nm["cls"] in ("user", "other_drive") and not it.get("inst") and installed(nm["path"]):
            it["inst"] = 1                              # 제거 프로그램과 함께 깔린 설치본 — 자체 도구 후보가 아니다
        for f, v in vals.items():
            if isinstance(v, datetime):
                s = v.strftime(TS_FMT)
                if s > it.get(f, ""):
                    it[f] = s
            elif v:
                it[f] = it.get(f, 0) + int(v)
        return True

    try:
        guids = reg.subkeys("HKCU", UA_KEY)
        src["ua"] = True
    except OSError:
        guids = []
    for g in guids:
        gu = str(g).upper()
        if gu not in (UA_EXE, UA_LNK):
            continue
        try:
            vals = reg.values("HKCU", UA_KEY + "\\" + g + "\\Count")
        except OSError:
            continue
        for name, data, _typ in vals:
            dec = rot13(name)
            if dec.upper().startswith("UEME_"):
                continue
            p = parse_ua(data)
            if p is None:
                c["ua_bad"] += 1
                continue
            runs, focus, ms, last = p
            if put(dec, ua_run=runs, ua_focus=focus, ua_ms=ms, ua_last=last):
                c["ua_lnk" if gu == UA_LNK else "ua"] += 1
    for sub, fld in FU_SUBS:
        try:
            vals = reg.values("HKCU", FU_KEY + "\\" + sub)
        except OSError:
            continue
        src["fu"] = True
        for name, data, _typ in vals:
            if isinstance(data, bool) or not isinstance(data, int) or data <= 0:
                continue
            if put(name, **{fld: data}):
                c["fu"] += 1
    if not sid:
        src["bam_why"] = "nosid"
    else:
        why = set()
        for base in BAM_KEYS:
            try:
                vals = reg.values("HKLM", base + "\\" + sid)
            except PermissionError:
                why.add("denied")
                continue
            except OSError:
                why.add("absent")
                continue
            src["bam"] = True
            for name, data, _typ in vals:
                if not isinstance(data, (bytes, bytearray)) or len(data) < 8:
                    continue                            # Version·SequenceNumber 같은 장부 값
                last = filetime_local(struct.unpack_from("<Q", data, 0)[0])
                if last and put(name, bam_last=last):
                    c["bam"] += 1
        if not src["bam"]:
            src["bam_why"] = "denied" if "denied" in why else "absent"
    return list(items.values()), c, src


TRACK_KEYS = (("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "Start_TrackProgs", 0),
              ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoInstrumentation", 1),
              ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoInstrumentation", 1))


def ua_tracking(reg):
    """UserAssist 가 갱신되는가 — '앱 실행 추적'(설정 > 개인 정보 > 일반 · Start_TrackProgs=0)이 꺼졌거나 정책
    NoInstrumentation=1 이면 False. 그러면 횟수가 늘지 않아 '안 썼다' 로 읽힌다 — 화면이 그 사유를 말하게 남긴다.
    값이 없으면 Windows 기본(켜짐) True."""
    for hive, path, name, off in TRACK_KEYS:
        try:
            for n, v, _typ in reg.values(hive, path):
                if str(n) == name and isinstance(v, int) and not isinstance(v, bool) and v == off:
                    return False
        except OSError:
            continue
    return True


def current_sid():
    """지금 계정의 SID 문자열(S-1-5-21-…) — 토큰을 읽는다(ctypes · 관리자 권한 불필요). 못 얻으면 ''."""
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.LocalFree.argtypes = (ctypes.c_void_p,)
        adv.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
        adv.OpenProcessToken.restype = wintypes.BOOL
        adv.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD))
        adv.GetTokenInformation.restype = wintypes.BOOL
        adv.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        adv.ConvertSidToStringSidW.restype = wintypes.BOOL
        tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):     # TOKEN_QUERY
            return ""
        try:
            n = wintypes.DWORD(0)
            adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(n))                         # TokenUser — 크기만
            if not n.value:
                return ""
            buf = ctypes.create_string_buffer(n.value)
            if not adv.GetTokenInformation(tok, 1, buf, n, ctypes.byref(n)):
                return ""
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]                       # TOKEN_USER.User.Sid
            out = ctypes.c_void_p()
            if not adv.ConvertSidToStringSidW(psid, ctypes.byref(out)) or not out.value:
                return ""
            try:
                return ctypes.wstring_at(out.value) or ""
            finally:
                k32.LocalFree(out)
        finally:
            k32.CloseHandle(tok)
    except Exception:  # noqa: BLE001 - SID 를 못 얻으면 BAM 만 건너뛴다
        return ""


def pc_key(reg, sid=""):
    """이 PC·이 계정의 열쇠(해시 12자) — 폴더째 다른 PC 로 옮겨도 두 PC 의 누적값을 한 줄로 빼지 않게 분석이 장을 가른다.
    MachineGuid(OS 설치 단위 — run.machine_id 와 같은 값)·SID 는 해시로만 남긴다."""
    mg = ""
    try:
        for name, data, _typ in reg.values("HKLM", r"SOFTWARE\Microsoft\Cryptography"):
            if str(name) == "MachineGuid":
                mg = str(data).strip()
    except OSError:
        pass
    base = (mg or os.environ.get("COMPUTERNAME", "")) + "|" + (sid or os.environ.get("USERNAME", ""))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]


def _snap_pc(path):
    try:
        with open(path, encoding="utf-8") as f:
            return str((json.load(f) or {}).get("pc") or "")
    except (OSError, ValueError, AttributeError):
        return None


def prune(out_dir, newest, pc, keep=KEEP):
    """같은 날·같은 PC 의 앞선 장을 지우고(하루 1장) 최신 keep 장만 남긴다. 죽은 쓰기의 1시간 넘은 임시 파일도 치운다 → 지운 수."""
    try:
        names = sorted(n for n in os.listdir(out_dir) if _SNAP_RX.match(n))
    except OSError:
        return 0
    day = newest[5:13]
    drop = [n for n in names if n != newest and n[5:13] == day and _snap_pc(os.path.join(out_dir, n)) == pc]
    rest = [n for n in names if n not in drop]
    if len(rest) > keep:
        drop += [n for n in rest[:len(rest) - keep] if n != newest]
    removed = 0
    for n in drop:
        try:
            os.remove(os.path.join(out_dir, n))
            removed += 1
        except OSError:
            pass
    now = time.time()
    try:
        for n in os.listdir(out_dir):
            p = os.path.join(out_dir, n)
            if n.endswith(".tmp") and now - os.path.getmtime(p) > 3600:
                os.remove(p)
    except OSError:
        pass
    return removed


def write_snapshot(out_dir, snap, now, keep=KEEP):
    """스냅샷 한 장을 원자적으로 쓴다(.<pid>.tmp → os.replace) → (경로, 남은 장 수, 지운 수)."""
    os.makedirs(out_dir, exist_ok=True)
    name = f"snap_{now:%Y%m%d_%H%M%S}.json"
    path = os.path.join(out_dir, name)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    removed = prune(out_dir, name, snap.get("pc", ""), keep)
    try:
        kept = sum(1 for n in os.listdir(out_dir) if _SNAP_RX.match(n))
    except OSError:
        kept = 0
    return path, kept, removed


def load_cfg():
    """config\\config.json (없거나 깨졌으면 {}) — excludePathKeywords·programsExtra 만 본다."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def lmstatus(rc, reason="", counts=None):
    """수집기 공통 마지막 줄 — run.py 가 rc·사유를 읽는다(원장 축이 아니라 ranges 는 비운다)."""
    print("LMSTATUS " + json.dumps({"v": 1, "src": "programs", "rc": rc, "reason": reason, "counts": counts or {},
                                    "ranges": []}, ensure_ascii=False, separators=(",", ":")))


def main(argv=None, reg=None, sid=None, now=None, out_dir=None, cfg=None):
    now = now or datetime.now()
    out_dir = out_dir or OUT_DIR
    if reg is None:
        try:
            reg = WinReg()
        except ImportError:
            print("[programs] 이 환경에는 Windows 레지스트리가 없습니다 — 실행 기록 스냅샷을 건너뜁니다")
            lmstatus(3, "R-NOREG")
            return 3
    cfg = load_cfg() if cfg is None else cfg
    sid = current_sid() if sid is None else sid
    items, c, src = collect(reg, cfg, sid)
    track = ua_tracking(reg)
    counts = dict(c, programs=len(items), bam_why=src["bam_why"], ua_track=int(track))
    if not items:
        print("[programs] 읽을 수 있는 실행 흔적이 없습니다(UserAssist·작업 표시줄 기록 없음) — 스냅샷을 남기지 않습니다")
        lmstatus(1, "", counts)
        return 0
    snap = {"v": 1, "taken": now.strftime(TS_FMT), "pc": pc_key(reg, sid),
            "sources": {"ua": src["ua"], "fu": src["fu"], "bam": src["bam"], "bam_why": src["bam_why"], "ua_track": track},
            "counts": c, "items": items}
    try:
        path, kept, removed = write_snapshot(out_dir, snap, now)
    except OSError as e:
        print(f"[programs] 스냅샷 저장 실패({type(e).__name__}) — 다음 수집에서 다시 찍습니다")
        lmstatus(3, "R-WRITE", counts)
        return 3
    counts.update(kept=kept, removed=removed)
    bam = (f"BAM {c['bam']}건" if src["bam"] else
           {"denied": "BAM 권한 없음(건너뜀 — 보통 사용자 PC 에서 정상)", "absent": "BAM 없음(건너뜀)",
            "nosid": "BAM 건너뜀(계정 SID 모름)"}.get(src["bam_why"], "BAM 건너뜀"))
    print(f"[programs] 실행 기록 스냅샷 — UserAssist {c['ua']}건(바로 가기 {c['ua_lnk']}) · 작업 표시줄 {c['fu']}건 · {bam}"
          f" → 프로그램 {len(items)}개 · 제외 폴더(개인·내려받기·임시 — excludePathKeywords) {c['excluded']}건"
          + (f" · 형식 다른 값 {c['ua_bad']}건" if c["ua_bad"] else "")
          + ("" if track else " · 주의: '앱 실행 추적' 이 꺼져 있어(설정 > 개인 정보 > 일반 또는 정책) 실행 횟수가 늘지 않습니다")
          + f" · {os.path.basename(path)} (보관 {kept}장)")
    lmstatus(0, "", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
