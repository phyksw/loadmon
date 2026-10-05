# -*- coding: utf-8 -*-
r"""기계·설치 식별자(계약 §2.6·§4.1, TAB §1.2) — ``identify_pc() -> PcIdentity``.

  · ``pc_id`` = ``"pc_" + sha256("LM27.pc|" + MachineGuid.lower())[:16]`` — 키 없는 값이라 키링이 생기기 전
    (설치 전용 진입점)에도 정해지고, 키링이 바뀌어도 불변이다. MachineGuid 원값은 어디에도 저장하지 않는다.
    읽기 실패 → ``"pcx_" + sha256("LM27.pcx|" + COMPUTERNAME + "|" + USERPROFILE 폴더 생성시각)[:16]``,
    ``id_source="fallback"``, 사유 ``R-NOMACHGUID``(경고). 형식 ``^pcx?_[0-9a-f]{16}$``.
  · ``install_id`` = ``agent\agent.json`` 의 값(32hex, 재설치·판 올림에도 유지). 없으면 이 프로세스 안에서 하나를
    새로 만들어 재호출에도 같은 값을 준다(저장은 에이전트 설치 ``lm27.agent.install.ensure_agent`` 가 한다).
  · ``kind_guess`` = cloud · vdi · laptop · desktop(TAB §1.5): 모델 문자열 ``Cloud PC``·호스트 접두 ``CPC-`` → cloud,
    가상 모델 + 원격 세션 → vdi, 배터리 → laptop, 그 밖 desktop. 근거는 참·거짓만 남긴다(모델·호스트 이름 원문 없음).
  · ``tz`` = ``{"utc_offset_min": lm27.util.tz.capture_offset_min(지금), "windows_tz": TimeZoneKeyName}``.

에이전트 bin 사본(계약 §1.3 · X-305)에서도 돌아야 하므로 표준 라이브러리와 사본 안 모듈(``lm27`` ·
``lm27.util`` · ``lm27.paths``)만 import 한다. 실기계 조회는 ``_WinProbe`` 한 곳에 모았고, 시험은 ``probe=`` 로 가짜를 넣는다.
"""
import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lm27 import LM27_VERSION
from lm27.util import fsx

PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
INSTALL_ID_RX = re.compile(r"^[0-9a-f]{32}$")
KINDS = ("desktop", "laptop", "vdi", "cloud")
R_NOMACHGUID = "R-NOMACHGUID"
CLOUD_HOST_PREFIX = "CPC-"                      # Windows 365 클라우드PC 기본 장치 이름 접두
VIRTUAL_MODEL_WORDS = ("virtual machine", "vmware", "virtualbox", "kvm", "qemu", "xen", "hyper-v")
CLOUD_MODEL_WORDS = ("cloud pc",)

_process_install_id = None                      # agent.json 이 없을 때 이 프로세스에서 쓸 install_id


@dataclass(frozen=True)
class PcIdentity:
    """계약 §2.6 의 여섯 필드 + 보조 필드(reasons · kind_evidence · install_source)."""
    pc_id: str
    id_source: str                              # machineguid | fallback
    install_id: str                             # 32hex
    agent_ver: str
    kind_guess: str                             # desktop | laptop | vdi | cloud
    tz: dict                                    # {"utc_offset_min": int, "windows_tz": str}
    reasons: tuple = ()                         # 사유 코드(R-NOMACHGUID)
    kind_evidence: dict = field(default_factory=dict)
    install_source: str = "agent_json"          # agent_json | new(아직 저장 안 됨)


# ── 순수 함수(시험·재계산용) ─────────────────────────────────────────────────
def pc_id_from_guid(machine_guid: str) -> str:
    """MachineGuid → pc_id. 대소문자 무관."""
    if not isinstance(machine_guid, str) or not machine_guid.strip():
        raise ValueError("pc_id_from_guid: MachineGuid 가 비었습니다")
    return "pc_" + hashlib.sha256(("LM27.pc|" + machine_guid.lower()).encode("utf-8")).hexdigest()[:16]


def pc_id_fallback(computer_name: str, profile_ctime: str) -> str:
    """MachineGuid 를 못 읽을 때의 대체식(TAB §1.2)."""
    raw = "LM27.pcx|" + (computer_name or "") + "|" + (profile_ctime or "")
    return "pcx_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def guess_kind(ev: dict) -> str:
    """kind 추정(TAB §1.5): cloud > vdi > laptop > desktop."""
    if ev.get("model_cloud") or ev.get("host_prefix_cloud"):
        return "cloud"
    if ev.get("model_virtual") and ev.get("rdp_session"):
        return "vdi"
    if ev.get("battery") or any(c in (8, 9, 10, 14, 30, 31, 32) for c in ev.get("chassis") or ()):
        return "laptop"
    return "desktop"


def kind_evidence(model: str, computer_name: str, battery, rdp_session: bool, chassis=()) -> dict:
    """원문(모델·호스트 이름)은 남기지 않고 참·거짓 근거만 만든다."""
    low = (model or "").lower()
    return {"battery": battery, "chassis": sorted(int(c) for c in chassis),
            "model_virtual": any(w in low for w in VIRTUAL_MODEL_WORDS),
            "model_cloud": any(w in low for w in CLOUD_MODEL_WORDS),
            "rdp_session": bool(rdp_session),
            "host_prefix_cloud": (computer_name or "").upper().startswith(CLOUD_HOST_PREFIX)}


# ── 실기계 조회 ──────────────────────────────────────────────────────────────
class _WinProbe:
    """이 PC 의 값을 읽는다(사용자 권한·읽기 전용). 시험은 같은 메서드를 가진 가짜를 넣는다."""

    def machine_guid(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                v, _t = winreg.QueryValueEx(k, "MachineGuid")
        except OSError:
            return None
        return v if isinstance(v, str) and v.strip() else None

    def computer_name(self) -> str:
        return os.environ.get("COMPUTERNAME", "")

    def profile_ctime(self) -> str:
        up = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        try:
            return str(int(os.stat(up).st_ctime))     # Windows: 생성 시각
        except OSError:
            return ""

    def offset_min(self) -> int:
        from lm27.util import tz                       # WP-02 소유 — 수집 순간 오프셋 단일원(계약 §9.1)
        return tz.capture_offset_min(datetime.now(UTC))

    def windows_tz(self) -> str:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as k:
                v, _t = winreg.QueryValueEx(k, "TimeZoneKeyName")
        except OSError:
            return ""
        return v.strip("\x00 ") if isinstance(v, str) else ""

    def model(self) -> str:
        import winreg
        parts = []
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
                for name in ("SystemManufacturer", "SystemProductName"):
                    try:
                        v, _t = winreg.QueryValueEx(k, name)
                    except OSError:
                        continue
                    if isinstance(v, str):
                        parts.append(v)
        except OSError:
            return ""
        return " ".join(parts)

    def battery(self):
        """배터리 있음 True · 없음 False · 알 수 없음 None(GetSystemPowerStatus.BatteryFlag 128 = 없음, 255 = 모름)."""
        import ctypes
        from ctypes import wintypes

        class _SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

        st = _SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return None
        if st.BatteryFlag == 255:
            return None
        return not (st.BatteryFlag & 128)

    def rdp_session(self) -> bool:
        import ctypes
        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))   # SM_REMOTESESSION

    def chassis(self):
        return ()                                       # WMI 없이는 못 읽는다 — 배터리로 노트북을 가른다


def _install_from_agent_json(paths):
    """agent.json 의 (install_id, agent_ver). 없거나 형식이 틀리면 (None, None)."""
    aj = fsx.read_json(paths.agent_json(), None, want=dict)
    if not aj:
        return None, None
    iid = aj.get("install_id")
    ver = aj.get("agent_ver")
    iid = iid if isinstance(iid, str) and INSTALL_ID_RX.match(iid) else None
    ver = ver if isinstance(ver, str) and ver else None
    return iid, ver


def _new_install_id() -> str:
    global _process_install_id
    if _process_install_id is None:
        _process_install_id = uuid.uuid4().hex
    return _process_install_id


def identify_pc(paths=None, *, probe=None) -> PcIdentity:
    """이 PC 의 식별(계약 §2.6). ``paths`` = ``lm27.paths.Paths``(없으면 기본 Paths — agent.json 위치를 정한다).
    ``probe`` = 실기계 조회 대체(시험). 같은 기계에서 다시 불러도 같은 pc_id 를 낸다."""
    if paths is None:
        from lm27.paths import Paths                   # 사본에도 있는 모듈(계약 §1.3)
        paths = Paths()
    pr = probe if probe is not None else _WinProbe()
    reasons = []
    guid = pr.machine_guid()
    if isinstance(guid, str) and guid.strip():
        pc_id, id_source = pc_id_from_guid(guid), "machineguid"
    else:
        pc_id, id_source = pc_id_fallback(pr.computer_name(), pr.profile_ctime()), "fallback"
        reasons.append(R_NOMACHGUID)
    iid, ver = _install_from_agent_json(paths)
    install_source = "agent_json"
    if iid is None:
        iid, install_source = _new_install_id(), "new"
    ev = kind_evidence(pr.model(), pr.computer_name(), pr.battery(), pr.rdp_session(), pr.chassis())
    tz = {"utc_offset_min": int(pr.offset_min()), "windows_tz": pr.windows_tz() or ""}
    return PcIdentity(pc_id=pc_id, id_source=id_source, install_id=iid, agent_ver=ver or LM27_VERSION,
                      kind_guess=guess_kind(ev), tz=tz, reasons=tuple(reasons), kind_evidence=ev,
                      install_source=install_source)
