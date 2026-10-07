# -*- coding: utf-8 -*-
r"""
lmname.py — LM28 이름 단일원 (포트·Edge 프로필·%TEMP% 접두·bat 이름·설치 폴더 해시).

왜: 같은 PC 에 LM24(OLD_CDP_PORT·data\<OLD_PROFILE>·대시보드 91xx 대역·%TEMP%\lm_*)가 함께 있어도
    Edge 를 조종하거나 임시 파일을 덮어쓰지 않게 한다. LM24 코드는 고칠 수 없으므로 LM28 쪽 이름을 그 규칙 밖에 둔다.
    · LM28 에는 창·팀즈 샘플러가 없다 — 예약 작업·뮤텍스 이름을 두지 않는다.
    · <h6> 는 설치 폴더 해시 — 같은 PC 의 LM28 두 벌(개발 사본·배포본)을 가른다.
    · 이 값이 config.json 의 옛 값(OLD_CDP_PORT·OLD_PROFILE)보다 우선한다 — LM24 config.json 을 옮겨 와도
      옛 포트·프로필로 붙지 않는다(fix_edge_cfg).
    · %LOCALAPPDATA% 는 쓰지 않는다 — 모든 상태는 설치 폴더 안(폴더째 이동 모델 유지).

PowerShell 쪽은 collect\LmName.ps1(Get-LmH6·Get-LmNames)이 같은 규칙을 둔다 — 하나를 바꾸면 둘 다 바꾼다
(tests\test_p0_names.py 가 같은 고정 경로의 h6 를 양쪽에서 비교한다).
"""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRODUCT = "LoadMonitor28"          # bat·창 제목·배포 폴더 이름
SHORT = "LM28"                     # 짧은 이름 접두
BAT_PREFIX = PRODUCT               # LoadMonitor28.bat · LoadMonitor28-*.bat
UI_PORTS = range(9248, 9268)       # 대시보드 대역 9248~9267 (LM24 대역과 겹치지 않음)
CDP_PORT = 9533                    # 전용 Edge 디버그 포트 (LM24 는 OLD_CDP_PORT)
EDGE_PROFILE_NAME = "lm28_edge"    # 이름에 LM24 의 종료 패턴(OLD_PROFILE)이 들어가면 안 된다
EDGE_PROFILE_REL = "data\\" + EDGE_PROFILE_NAME
EDGE_PROFILE = os.path.join(ROOT, "data", EDGE_PROFILE_NAME)
TMP_PREFIX = "lm28_"               # %TEMP% 아래 우리 파일·폴더 접두
TEAM_ADDR_ENV = ("LM28_TA_HOST", "LM28_TA_PORT")   # 팀서버주소.bat → teamaddr --set-env 환경변수

# 옛 값 판별용(이 값을 쓰지 않는다 — config 에 남아 있으면 덮는다). 이름 검사 시험의 허용 목록에 있다.
OLD_CDP_PORT = 9333
OLD_PROFILE = "copilot_profile"


def norm_root(path=None):
    r"""h6 의 입력 — GetFullPathNameW → GetLongPathNameW → 끝 구분자 제거 → 소문자.
    없는 경로는 GetLongPathNameW 가 실패하므로 전체 경로까지만 쓴다(LmName.ps1 과 같은 규칙)."""
    p = str(path or ROOT)
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        buf = ctypes.create_unicode_buffer(32768)
        n = k32.GetFullPathNameW(p, 32768, buf, None)
        if 0 < n < 32768:
            p = buf.value
        n = k32.GetLongPathNameW(p, buf, 32768)
        if 0 < n < 32768:
            p = buf.value
    except (AttributeError, OSError, ImportError):
        p = os.path.abspath(p)
    p = p.rstrip("\\/")
    return p.lower()


def h6(path=None):
    """설치 폴더 해시 6자리 — sha1(UTF-8(norm_root))[:6]."""
    return hashlib.sha1(norm_root(path).encode("utf-8")).hexdigest()[:6]


def names(path=None):
    """폴더별 이름 묶음 — 키는 LmName.ps1 Get-LmNames 와 같다."""
    return {"H6": h6(path)}


H6 = names(ROOT)["H6"]


def edge_profile(root=None):
    r"""이 설치본의 전용 Edge 프로필 절대경로(<ROOT>\data\lm28_edge)."""
    return os.path.join(str(root or ROOT), "data", EDGE_PROFILE_NAME)


def is_old_edge(port=None, profile_dir=None):
    """옛 판(LM24) 값인가 — 포트가 OLD_CDP_PORT 이거나 프로필 경로에 OLD_PROFILE 이 들어 있다."""
    try:
        if port is not None and int(port) == OLD_CDP_PORT:
            return True
    except (TypeError, ValueError):
        pass
    return OLD_PROFILE in str(profile_dir or "").lower()


def fix_edge_cfg(cfg, root=None):
    r"""copilotAuto 실효 설정에서 옛 값(OLD_CDP_PORT·…\<OLD_PROFILE>)을 LM28 값으로 덮는다.
    LM24 의 config.json 을 그대로 옮겨 오면 LM24 가 띄운 Edge(같은 포트)를 재사용하거나 LM24 프로필을
    조종하게 된다 — 그래서 config 보다 이 상수가 우선한다. 바꾼 항목을 사람이 읽을 문장 목록으로 돌려준다."""
    warn = []
    try:
        if int(cfg.get("port") or 0) == OLD_CDP_PORT:
            cfg["port"] = CDP_PORT
            warn.append(f"port {OLD_CDP_PORT}→{CDP_PORT}")
    except (TypeError, ValueError):
        cfg["port"] = CDP_PORT
        warn.append(f"port(형식 오류)→{CDP_PORT}")
    if OLD_PROFILE in str(cfg.get("profileDir") or "").lower():
        cfg["profileDir"] = edge_profile(root)
        warn.append(f"profileDir→{EDGE_PROFILE_REL}")
    return warn
