# -*- coding: utf-8 -*-
r"""
lmname.py — LM30v1 이름 단일원 (포트·Edge 프로필·%TEMP% 접두·bat 이름·설치 폴더 해시).

왜: 같은 PC 에 LM24(OLD_CDP_PORT·data\<OLD_PROFILE>·대시보드 91xx 대역·%TEMP%\lm_*)나
    LM28(OLD_LM28_CDP_PORT·data\<OLD_LM28_PROFILE>·대시보드 9248~9267·%TEMP%\lm28_*)·
    LM29(OLD_LM29_CDP_PORT·data\<OLD_LM29_PROFILE>·대시보드 9268~9287·%TEMP%\lm29_*)·
    LM30(OLD_LM30_CDP_PORT·data\<OLD_LM30_PROFILE>·대시보드 9288~9307·%TEMP%\lm30_*)이 함께 있어도
    Edge 를 조종하거나 임시 파일을 덮어쓰지 않게 한다. 다른 판의 코드는 고칠 수 없으므로 LM30v1 쪽 이름을 그 규칙 밖에 둔다.
    · LM30v1 은 LM30(LM29 를 이은 출퇴근 추정 시험판)에서 1MM 기준을 바꿔 보려고 갈라 낸 시험판이라 같은 PC 에
      LM28·LM29·LM30 과 함께 깔릴 수 있다.
    · LM30v1(2026-10-19) 이 판의 이름은 앞 판 이름으로 시작한다('LM30v1' 은 'LM30' 으로, 'LoadMonitor30v1' 은
      'LoadMonitor30' 으로). 그래서 이름으로 남을 고르는 곳은 앞부분만 견주지 않는다 — %TEMP% 접두는 'lm30v1_'(LM30 의 접두가
      이것의 앞부분이 아니다), 프로필 'lm30v1_edge' 에는 OLD_LM30_PROFILE 이 들어 있지 않고, 팀 서버 주소 환경변수는 LM30V1_TA_*,
      설치 폴더는 끝 구분자까지 견주고(강제종료·PC 이동 준비), 판 표식은 통째로 견준다(team_recalc.version_of).
    · LM30v1 에는 창·팀즈 샘플러가 없다 — 예약 작업·뮤텍스 이름을 두지 않는다.
    · <h6> 는 설치 폴더 해시 — 같은 PC 의 LM30v1 두 벌(개발 사본·배포본)을 가른다.
    · 이 값이 config.json 의 옛 판 값(OLD_*)보다 우선한다 — LM24·LM28·LM29·LM30 의 config.json 을 옮겨 와도
      그 판의 포트·프로필(로그인)로 붙지 않는다(fix_edge_cfg).
    · %LOCALAPPDATA% 는 쓰지 않는다 — 모든 상태는 설치 폴더 안(폴더째 이동 모델 유지).
    · 팀 서버 기본 주소·포트·업로드 형식은 판과 무관하게 같다(core\teamaddr.py) — 여기서 다루지 않는다.

PowerShell 쪽은 collect\LmName.ps1(Get-LmH6·Get-LmNames)이 같은 규칙을 둔다 — 하나를 바꾸면 둘 다 바꾼다
(tests\test_p0_names.py 가 같은 고정 경로의 h6 와 Short·Product·TmpPrefix 를 양쪽에서 비교한다).
"""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRODUCT = "LoadMonitor30v1"        # bat·창 제목·배포 폴더 이름
SHORT = "LM30v1"                   # 짧은 이름 접두
BAT_PREFIX = PRODUCT               # LoadMonitor30v1.bat · LoadMonitor30v1-*.bat
# 대시보드 대역 9350~9369 — LM24 대역·LM28 9248~9267·LM29 9268~9287·LM30 9288~9307 과 겹치지 않고, 팀 서버 기본 포트 9310 과
# LM24 전용 Edge 포트(OLD_CDP_PORT)도 비켜 간다(LM30v1(2026-10-19) — LM30 대역 바로 뒤 9308~ 은 팀 서버 9310 이 끼어 있어 건너뛰었다)
UI_PORTS = range(9350, 9370)
CDP_PORT = 9563                    # 전용 Edge 디버그 포트 (LM24·LM28·LM29·LM30 의 OLD_*_CDP_PORT 와 다름)
EDGE_PROFILE_NAME = "lm30v1_edge"  # 이름에 옛 판의 프로필 이름(OLD_PROFILES — OLD_LM30_PROFILE 포함)이 들어가면 안 된다
EDGE_PROFILE_REL = "data\\" + EDGE_PROFILE_NAME
EDGE_PROFILE = os.path.join(ROOT, "data", EDGE_PROFILE_NAME)
TMP_PREFIX = "lm30v1_"             # %TEMP% 아래 우리 파일·폴더 접두 (LM24 lm_ · LM28 lm28_ · LM29 lm29_ · LM30 lm30_ — 서로의 앞부분이 아니다)
TEAM_ADDR_ENV = ("LM30V1_TA_HOST", "LM30V1_TA_PORT")   # 팀서버주소.bat → teamaddr --set-env 환경변수(LM30 bat 의 것과 이름이 다르다)

# 옛 판 값 판별용(이 값을 쓰지 않는다 — config 에 남아 있으면 덮는다). 이름 검사 시험의 허용 목록에 있다.
OLD_CDP_PORT = 9333                # LM24 의 전용 Edge 디버그 포트
OLD_PROFILE = "copilot_profile"    # LM24 의 전용 Edge 프로필 폴더 이름
OLD_LM28_CDP_PORT = 9533           # LM28 의 전용 Edge 디버그 포트 — LM28 config.json 을 옮겨 오면 남는다
OLD_LM28_PROFILE = "lm28_edge"     # LM28 의 전용 Edge 프로필 폴더 이름(data\ 아래)
OLD_LM29_CDP_PORT = 9543           # LM29 의 전용 Edge 디버그 포트 — LM29 config.json 을 옮겨 오면 남는다
OLD_LM29_PROFILE = "lm29_edge"     # LM29 의 전용 Edge 프로필 폴더 이름(data\ 아래)
OLD_LM30_CDP_PORT = 9553           # LM30 의 전용 Edge 디버그 포트 — LM30 config.json 을 옮겨 오면 남는다(LM30v1(2026-10-19))
OLD_LM30_PROFILE = "lm30_edge"     # LM30 의 전용 Edge 프로필 폴더 이름(data\ 아래)
OLD_CDP_PORTS = (OLD_CDP_PORT, OLD_LM28_CDP_PORT, OLD_LM29_CDP_PORT, OLD_LM30_CDP_PORT)
OLD_PROFILES = (OLD_PROFILE, OLD_LM28_PROFILE, OLD_LM29_PROFILE, OLD_LM30_PROFILE)


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
    r"""이 설치본의 전용 Edge 프로필 절대경로(<ROOT>\data\lm30v1_edge)."""
    return os.path.join(str(root or ROOT), "data", EDGE_PROFILE_NAME)


def is_old_edge(port=None, profile_dir=None):
    """옛 판(LM24·LM28·LM29·LM30) 값인가 — 포트가 OLD_CDP_PORTS 중 하나이거나 프로필 경로에 OLD_PROFILES 중 하나가 들어 있다."""
    try:
        if port is not None and int(port) in OLD_CDP_PORTS:
            return True
    except (TypeError, ValueError):
        pass
    pd = str(profile_dir or "").lower()
    return any(x in pd for x in OLD_PROFILES)


def fix_edge_cfg(cfg, root=None):
    r"""copilotAuto 실효 설정에서 옛 판 값(LM24 OLD_CDP_PORT·…\<OLD_PROFILE> · LM28 OLD_LM28_CDP_PORT·…\<OLD_LM28_PROFILE> ·
    LM29 OLD_LM29_CDP_PORT·…\<OLD_LM29_PROFILE> · LM30 OLD_LM30_CDP_PORT·…\<OLD_LM30_PROFILE>)을 LM30v1 값으로 덮는다.
    LM24·LM28·LM29·LM30 의 config.json 을 그대로 옮겨 오면 그 판이 띄운 Edge(같은 포트)를 재사용하거나 그 판의 프로필(로그인)을
    조종하게 된다 — 그래서 config 보다 이 상수가 우선한다. 바꾼 항목을 사람이 읽을 문장 목록으로 돌려준다.
    LM30v1(2026-10-19): 프로필은 경로에 옛 이름이 '들어 있나' 로 본다 — 이 판의 'lm30v1_edge' 에는 OLD_LM30_PROFILE 이 들어 있지
    않아 한 번 덮은 값을 다시 옛 판 것으로 오인하지 않는다(시험 test_p0)."""
    warn = []
    try:
        old = int(cfg.get("port") or 0)
        if old in OLD_CDP_PORTS:
            cfg["port"] = CDP_PORT
            warn.append(f"port {old}→{CDP_PORT}")
    except (TypeError, ValueError):
        cfg["port"] = CDP_PORT
        warn.append(f"port(형식 오류)→{CDP_PORT}")
    pd = str(cfg.get("profileDir") or "").lower()
    if any(x in pd for x in OLD_PROFILES):
        cfg["profileDir"] = edge_profile(root)
        warn.append(f"profileDir→{EDGE_PROFILE_REL}")
    return warn
