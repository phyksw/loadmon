# -*- coding: utf-8 -*-
r"""[수집] 단계 순서·병렬·역할 표(계약 §2.5 · C §1 · §8.2 · CM §2 · CT §1.1 · D-6 · D-14) — 무엇을 어느 PC 에서 돌리나.

순수 모듈(입력 = 역할·탐침 결과·``--only``, 출력 = 단계 목록). 실행은 ``lm27.collect.run`` 이 한다.

  · 단계 순서(C §8.2): ``probe`` → ``pc_bundle``(샘플러 생존 · 수확 events·files·mru·recent · git · compute) →
    ``mail_local``(com → index) → ``cal_local`` → ``teams_uia_check`` → ``import`` → ``export`` → ``derive``(원장·빈칸) →
    [백필 PC] ``backfill_owa`` → ``backfill_teams_web`` → [클라우드PC] ``copilot_lookup`` → ``upload``.
    '첫 성공에서 멈추는 사슬'은 없다 — 싼 로컬 경로를 먼저 다 돌리고, 원장의 빈칸만 비싼 경로(OWA·팀즈 웹·코파일럿)로
    채운다(D-6). 색인은 항상 돈다(교차검증 — X-124).
  · 역할(TAB §1.5 roles): 업무 PC = ``pc_usage`` ``mail_local`` ``teams_window`` · 클라우드PC = ``pc_usage``
    ``account_backfill`` ``copilot``. 계정 백필(OWA·팀즈 웹)은 백필 PC(``collect.backfillPc`` — 기본 ``cloud``)에서만,
    코파일럿 증인은 ``copilot`` 역할(클라우드PC)에서만 돈다. 로컬 메일·일정·PC 경로는 모든 PC 에서 시도한다(되면 —
    클라우드PC 도 클래식 Outlook 이 있으면 같다, C §1).
  · 계획 단계의 건너뜀(``Stage.skip``): 방금 잰 탐침이 구조·사람 사유로 ``fail`` 이면(예 새 Outlook 전용 → COM) 또는 그
    능력이 ``불가(확정)``(계약 §6.4)이면 수집기를 띄우지 않고 '막힘 결과'(rc 3 + 사유)를 바로 남긴다 — 원장에는
    ``blocked`` 로 남아 빈칸 계획기가 다른 경로를 배정한다(못 돈 것을 0건으로 숨기지 않는다 — T-09).
  · 수집기 표(``COLLECTORS``): 경로 ID → 스크립트·언어·제어 줄 ``_in.cfg`` 키(계약 §7.3 · X-300)·관측 창 종류.
    PS 수집기의 설정 값은 연결자가 ``_in.cfg`` 로 넘긴다(계약 §5.1-10 — 레지스트리 owner 는 연결자).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lm27.collect import rcmap

__all__ = [
    "COLLECTORS", "PROBE_KEYS", "ROLES_CLOUD", "ROLES_PC", "ROLE_BACKFILL", "ROLE_COPILOT", "RUN_ORDER", "Spec",
    "Stage", "backfill_pc_id", "copilot_enabled", "is_backfill_pc", "license_enabled", "parallel_max", "pc_roles",
    "web_everywhere",
    "read_protected", "stage_plan", "stage_of",
]

ROLE_USAGE = "pc_usage"
ROLE_MAIL = "mail_local"
ROLE_TEAMS = "teams_window"
ROLE_BACKFILL = "account_backfill"
ROLE_COPILOT = "copilot"
ROLES_PC = (ROLE_USAGE, ROLE_MAIL, ROLE_TEAMS)
ROLES_CLOUD = (ROLE_USAGE, ROLE_BACKFILL, ROLE_COPILOT)
PC_ROLE_FLAGS = ("pc1", "pc2", "cloud")              # collect --pc-role
BACKFILL_CLOUD = "cloud"                             # collect.backfillPc 기본값 — 클라우드PC 가 백필 담당

# 실행 순서(계약 §8.5 COLLECT_STAGES 의 이름 — 순서는 C §8.2). export·derive 는 백필·코파일럿 뒤에 다시 돈다(run).
RUN_ORDER = ("probe", "pc_bundle", "mail_local", "cal_local", "teams_uia_check", "import", "export", "derive",
             "backfill_owa", "backfill_teams_web", "copilot_lookup", "upload")
MARKER_STAGES = frozenset({"probe", "export", "derive", "upload"})   # 경로 ID 없이 도는 단계

# 관측 창(원장이 '이번 실행이 이 날을 읽었다'고 볼 날짜 구간 — lm27.collect.ledger)
WIN_LOOKBACK = "lookback"     # since..until(없으면 오늘 − collect.lookbackDays + 1 ~ 오늘)
WIN_TODAY = "today"           # 오늘 하루(화면에 보이는 것·상주 생존 확인)
WIN_BLANKS = "blanks"         # 빈칸 계획기가 배정한 날짜 구간만
WIN_NONE = "none"             # 날짜 창 없음(반입 — 읽은 레코드의 날만)

_PS_SINCE = ("-Since", "-Until")
_PY_SINCE = ("--from", "--to")
_FILE_KEYS = ("pc.watchExtensions", "pc.excludeFolderNames", "pc.excludePackageDirs", "collect.lookbackDays")
_COM_KEYS = ("mail.com.budgetSec", "mail.com.watchdogSec", "mail.com.protectedReadSec", "mail.com.capMail",
             "mail.com.capCal", "mail.com.readProtected", "mail.includeArchiveStore", "collect.ownerAddress",
             "probe.subfolderRatio", "probe.ostStaleH", "collect.lookbackDays")
_IDX_KEYS = ("mail.index.capMail", "mail.index.capCal", "mail.index.excludeFolderNames", "collect.ownerAddress",
             "collect.lookbackDays")
_UIA_KEYS = ("teams.timeRegex", "teams.uia.visibleOnly", "teams.uia.maxElements", "teams.uia.windowWatchdogSec",
             "teams.uia.budgetSec")
_LIC_KEYS = ("pc.license.enabled", "pc.license.lmutilPath", "pc.license.servers")
PS_SLACK_S = 60               # PS 기동·Add-Type 컴파일·자식 워치독 여유(초)


@dataclass(frozen=True)
class Spec:
    """수집기 한 경로. ``lang`` = ``ps``(stdout → 정제 파이프) · ``py``(in-process 정제, 자식 프로세스) · ``agent``(상주 확인).
    ``cfg`` = PS 수집기 ``_in.cfg`` 로 넘길 설정 키(계약 §7.3), ``window`` = 원장 관측 창, ``limit`` = 감시 상한(초) 산정
    — 숫자면 그 초, 문자열이면 그 설정 키 값(초) + ``PS_SLACK_S``, 빈 값이면 감시 기본값(collect.watch.*)만."""
    src: str
    kind: str
    stage: str
    script: str = ""
    lang: str = "ps"
    args: tuple = ()
    cfg: tuple = ()
    self_names: bool = False
    window: str = WIN_LOOKBACK
    limit: object = ""
    harvest: bool = False
    probe_key: str = ""
    role: str = ""
    since_args: tuple = ()
    blanks: bool = False

    def limit_s(self, cfg) -> float | None:
        """감시 상한(초) — 그 수집기의 예산 + 기동 여유. 모르면 None(감시 기본값)."""
        if isinstance(self.limit, (int, float)) and not isinstance(self.limit, bool):
            return float(self.limit)
        if isinstance(self.limit, str) and self.limit and cfg is not None:
            v = cfg[self.limit]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return float(v) + PS_SLACK_S
        return None


COLLECTORS = {
    # pc_bundle — 상주 샘플러 확인 · 수확 4종(에이전트가 하고, 못 하면 전경이 대신) · git · 라이선스(옵트인)
    "pc.sampler": Spec("pc.sampler", "pc_session", "pc_bundle", lang="agent", window=WIN_TODAY, probe_key="pc.sampler"),
    "pc.events": Spec("pc.events", "pc_session", "pc_bundle", "Get-EventActivity.ps1", cfg=("collect.lookbackDays",),
                      limit=90, harvest=True, since_args=_PS_SINCE),
    "pc.files": Spec("pc.files", "pc_file", "pc_bundle", "Get-FileActivity.ps1",
                     cfg=("pc.watchFolders", "pc.autoDiscoverFolders", "pc.files.burstN", "pc.files.budgetSec",
                          "privacy.path.excludeKeywords", "episode.finalWords") + _FILE_KEYS,
                     limit="pc.files.budgetSec", harvest=True, since_args=_PS_SINCE),
    "pc.mru": Spec("pc.mru", "pc_file", "pc_bundle", "Get-OfficeMru.ps1",
                   cfg=("pc.mru.officeVersions", "pc.mru.jumpList", "episode.finalWords") + _FILE_KEYS, limit=180,
                   harvest=True, since_args=_PS_SINCE),
    "pc.recent": Spec("pc.recent", "pc_file", "pc_bundle", "Get-RecentFiles.ps1",
                      cfg=("episode.finalWords",) + _FILE_KEYS, limit=180, harvest=True, since_args=_PS_SINCE),
    "pc.git": Spec("pc.git", "pc_git", "pc_bundle", "Get-GitActivity.py", lang="py", limit=300, probe_key="pc.git",
                   since_args=_PY_SINCE),
    "pc.compute": Spec("pc.compute", "pc_compute", "pc_bundle", "Get-LicenseUsage.ps1", cfg=_LIC_KEYS,
                       window=WIN_TODAY, limit=180),
    # 메일·일정 로컬(kind 마다 파이프 하나 — COM 2회 붙기, 계약 §7.3)
    "mail.com": Spec("mail.com", "mail", "mail_local", "Get-OutlookCom.ps1", args=("-Only", "mail"), cfg=_COM_KEYS,
                     limit="mail.com.budgetSec", probe_key="mail.com", since_args=_PS_SINCE),
    "mail.index": Spec("mail.index", "mail", "mail_local", "Get-OutlookIndex.ps1", args=("-Only", "mail"),
                       cfg=_IDX_KEYS, limit=600, since_args=_PS_SINCE),
    "cal.com": Spec("cal.com", "cal", "cal_local", "Get-OutlookCom.ps1", args=("-Only", "cal"), cfg=_COM_KEYS,
                    limit="mail.com.budgetSec", probe_key="cal.com", since_args=_PS_SINCE),
    "cal.index": Spec("cal.index", "cal", "cal_local", "Get-OutlookIndex.ps1", args=("-Only", "cal"), cfg=_IDX_KEYS,
                      limit=600, since_args=_PS_SINCE),
    # 팀즈 창 — 상주 에이전트가 주기로 읽는다. 에이전트가 살아 있지 않으면 전경이 한 번 읽는다(오늘 보이는 것).
    "teams.uia": Spec("teams.uia", "teams", "teams_uia_check", "Get-TeamsWindow.ps1", cfg=_UIA_KEYS, self_names=True,
                      window=WIN_TODAY, limit="teams.uia.budgetSec", probe_key="teams.uia"),
    # 반입(정식 대체 경로) — 날짜 창 없음
    "mail.import": Spec("mail.import", "mail", "import", "Import-MailCal.py", lang="py", args=("--kind", "mail"),
                        window=WIN_NONE),
    "cal.import": Spec("cal.import", "cal", "import", "Import-MailCal.py", lang="py", args=("--kind", "cal"),
                       window=WIN_NONE),
    # 백필 PC — 메일은 원장 빈칸만(--blanks-file), 일정·팀즈 웹은 기간 전체(D-14 · CM §2 · CT §1.1)
    "mail.owa": Spec("mail.owa", "mail", "backfill_owa", "Get-OutlookWeb.py", lang="py", args=("--kind", "mail"),
                     window=WIN_BLANKS, probe_key="edge_cdp_policy", role=ROLE_BACKFILL, blanks=True),
    "cal.owa": Spec("cal.owa", "cal", "backfill_owa", "Get-OutlookWeb.py", lang="py", args=("--kind", "cal"),
                    probe_key="edge_cdp_policy", role=ROLE_BACKFILL, since_args=_PY_SINCE),
    "teams.web": Spec("teams.web", "teams", "backfill_teams_web", "Get-TeamsWeb.py", lang="py",
                      probe_key="edge_cdp_policy", role=ROLE_BACKFILL, since_args=_PY_SINCE),
    # 클라우드PC — 코파일럿 존재 증인(빈 날만 — B §8.1, 시간 근거 아님)
    "mail.copilot": Spec("mail.copilot", "mail", "copilot_lookup", "Get-MailViaCopilot.py", lang="py",
                         window=WIN_BLANKS, role=ROLE_COPILOT, blanks=True),
    "teams.copilot": Spec("teams.copilot", "teams", "copilot_lookup", "Get-TeamsViaCopilot.py", lang="py",
                          window=WIN_BLANKS, role=ROLE_COPILOT, blanks=True),
    "cal.copilot": Spec("cal.copilot", "cal", "copilot_lookup", "Get-CalViaCopilot.py", lang="py",
                        window=WIN_BLANKS, role=ROLE_COPILOT, blanks=True),
}
STAGE_SRCS = {}
for _s in COLLECTORS.values():
    STAGE_SRCS.setdefault(_s.stage, []).append(_s.src)
STAGE_SRCS = {k: tuple(v) for k, v in STAGE_SRCS.items()}
# 계획에서 볼 탐침 키(Invoke-CapabilityProbe.ps1 의 caps 키 — 계약 §6.7). 경로 자신의 능력 기록(pc.json)도 함께 본다.
PROBE_KEYS = tuple(sorted({s.probe_key for s in COLLECTORS.values() if s.probe_key}))
COPILOT_STAGE_OF = {"mail.copilot": "lookup_mail", "teams.copilot": "lookup_teams", "cal.copilot": "lookup_calendar"}


@dataclass(frozen=True)
class Stage:
    """계획된 단계 하나. ``srcs`` = 돌릴 경로 ID(순서대로), ``skip`` = 계획에서 건너뛴 경로 → ``{rc, reasons, why}``
    (rc 3 + 사유 = 원장 '막힘', rc None = 돌지 않음), ``parallel`` = 경로끼리 동시에 돌려도 되는가."""
    name: str
    srcs: tuple = ()
    skip: dict = field(default_factory=dict)
    parallel: bool = False

    @property
    def all_srcs(self) -> tuple:
        return tuple(self.srcs) + tuple(k for k in sorted(self.skip) if k not in self.srcs)


def stage_of(src: str) -> str:
    """경로 ID → 수집 단계 이름. 모르는 경로 ID 는 ValueError."""
    spec = COLLECTORS.get(src)
    if spec is None:
        raise ValueError(f"수집 경로 ID 가 아닙니다: {src!r}")
    return spec.stage


# ── 역할·백필 PC ────────────────────────────────────────────────────────────
def _label_match(pc: dict, want: str) -> bool:
    w = (want or "").strip()
    if not w:
        return False
    return w == pc.get("pc_id") or w == (pc.get("label_user") or "").strip() or w == (pc.get("label_auto") or "").strip()


def backfill_pc_id(pcs, cfg) -> str | None:
    """백필 담당 PC 의 pc_id(``collect.backfillPc`` — ``cloud`` = 처음 나타난 클라우드PC, 그 밖 = PC 라벨·pc_id). 없으면 None
    (클라우드PC 가 없고 사람이 정하지 않았으면 — 빈칸은 배정 대기로 남는다, C §1)."""
    want = str(cfg["collect.backfillPc"] or BACKFILL_CLOUD).strip()
    rows = sorted((p for p in pcs or () if isinstance(p, dict) and p.get("pc_id")),
                  key=lambda p: (str(p.get("first_seen") or ""), p["pc_id"]))
    if want == BACKFILL_CLOUD:
        for p in rows:
            if p.get("kind") == "cloud":
                return p["pc_id"]
        return None
    for p in rows:
        if _label_match(p, want):
            return p["pc_id"]
    return None


def is_backfill_pc(pc: dict, pcs, cfg, pc_role=None) -> bool:
    """이 PC 가 계정 백필 담당인가. ``--pc-role cloud`` 이고 백필 설정이 ``cloud`` 면 참."""
    want = str(cfg["collect.backfillPc"] or BACKFILL_CLOUD).strip()
    if want == BACKFILL_CLOUD and pc_role == "cloud":
        return True
    bid = backfill_pc_id(list(pcs or ()) + ([pc] if pc else []), cfg)
    return bool(pc) and bid == pc.get("pc_id")


def pc_roles(pc: dict | None, *, pcs=(), cfg=None, pc_role=None) -> tuple:
    """이 PC 에서 돌릴 역할(정렬). ``pc_role``(``--pc-role``)이 있으면 그 역할 묶음, 없으면 pc.json ``roles``(없으면
    kind 기본값). 백필 담당이면 ``account_backfill`` 을 더한다. 코파일럿은 클라우드PC 에서만(C §1 — 다른 PC 는 로그인 없음)."""
    pc = pc or {}
    if pc_role is not None and pc_role not in PC_ROLE_FLAGS:
        raise ValueError(f"--pc-role 은 {PC_ROLE_FLAGS} 중 하나")
    if pc_role == "cloud":
        roles = set(ROLES_CLOUD)
    elif pc_role in ("pc1", "pc2"):
        roles = set(ROLES_PC)
    else:
        given = [r for r in pc.get("roles") or () if isinstance(r, str)]
        roles = set(given) if given else set(ROLES_CLOUD if pc.get("kind") == "cloud" else ROLES_PC)
    if cfg is not None:
        # 버전 무관 웹 경로(Outlook 웹·팀즈 웹)는 모든 PC 에서 돈다(collect.webEverywhere — 기본 켜짐, LM24 와 같음).
        # 백필 PC 한 대에만 두면 그 PC(기본 클라우드PC)가 없거나 안 돈 동안 새 Outlook·온라인 모드 PC 의 메일과 팀즈가
        # 통째로 빈다(실측 제보). 끄면 예전처럼 백필 담당 PC(collect.backfillPc) 한 대만.
        if web_everywhere(cfg) or is_backfill_pc(pc, pcs, cfg, pc_role):
            roles.add(ROLE_BACKFILL)
        else:
            roles.discard(ROLE_BACKFILL)
    if ROLE_COPILOT in roles and not (pc_role == "cloud" or (pc_role is None and pc.get("kind") == "cloud")):
        roles.discard(ROLE_COPILOT)
    return tuple(sorted(roles))


# ── 설정 판단 ───────────────────────────────────────────────────────────────
# 같은 단계 안 수집기도 차례로 도는 단계(계약 v1.3 §0.8 V9). 웹·코파일럿 경로는 본인 전용 Edge 프로필 하나(배타 잠금)를
# 같이 쓴다 — 동시에 띄우면 뒤의 것이 잠금을 3분(60초 × 3) 기다리다 끝난다(실측: mail.owa 가 잠금을 쥔 동안 cal.owa
# R-TRANSPORT). 팀즈 창 판독은 화면 하나라 원래 차례로.
SERIAL_STAGES = ("teams_uia_check", "backfill_owa", "backfill_teams_web", "copilot_lookup")

def web_everywhere(cfg) -> bool:
    """버전 무관 웹 경로를 모든 PC 에서 돌리나(``collect.webEverywhere`` — 기본 True)."""
    if cfg is None:
        return True
    try:
        return bool(cfg["collect.webEverywhere"])
    except KeyError:
        return True


def parallel_max(cfg) -> int:
    """한 단계 안에서 동시에 돌릴 수집기 수(``collect.parallelMax`` — C §8.2). COM 은 단계가 달라 늘 직렬이다."""
    v = cfg["collect.parallelMax"] if cfg is not None else 2
    return max(1, int(v))


def license_enabled(cfg) -> bool:
    """라이선스 수집 옵트인(``pc.license.enabled`` — CP §8 · U-10)."""
    return bool(cfg["pc.license.enabled"]) if cfg is not None else False


def copilot_enabled(cfg, src: str) -> bool:
    """코파일럿 증인 경로가 켜져 있나(``bridge.stages`` 의 lookup_* — X-138, 일정은 기본 꺼짐)."""
    st = COPILOT_STAGE_OF.get(src)
    if st is None or cfg is None:
        return False
    stages = cfg["bridge.stages"]
    return bool(stages.get(st)) if isinstance(stages, dict) else False


B_ATTACH_OK = ("ok", "not_running")          # B단 auto 를 켤 수 있는 탐침 붙기 상태


def read_protected(cfg, caps) -> str:
    """COM B단(보호 열) 읽기 허용 ``"0"``·``"1"``(``mail.com.readProtected`` — auto 는 탐침이 OMG 없음을 판정한 PC 만 1,
    CM §5.4 · WP-17). 탐침 값이 없거나 OMG 미상(None)이면 0(경고창을 띄우지 않는 쪽).

    탐침 때 Outlook 이 꺼져 있었으면(``attach == "not_running"``) 탐침의 ``omg`` 는 정책·백신 상태(WSC GOOD)만으로 정한
    추정이다 — 예전에는 그런 PC(백신이 정상인 보통 회사 PC 대부분)에서 B단이 늘 꺼져 주소 없이 모였다(M365 조사 M17).
    추정이 틀려 경고창이 뜨면 수집기가 B단 카나리아(``pr_start`` 단계 워치독)에서 끊고 B단 없이 다시 붙는다(R-OMG)."""
    v = str(cfg["mail.com.readProtected"]) if cfg is not None else "auto"
    if v in ("0", "1"):
        return v
    cap = (caps or {}).get("mail.com") or {}
    val = cap.get("value") if isinstance(cap.get("value"), dict) else {}
    return "1" if val.get("omg") is False and val.get("attach") in B_ATTACH_OK else "0"


# ── 계획 ────────────────────────────────────────────────────────────────────
def _blocking(reasons) -> list:
    """계획 건너뜀의 근거가 되는 사유(구조·사람 — 지평선 제외)."""
    return [r for r in rcmap.norm_reasons(reasons) if r != "R-HORIZON"
            and rcmap.reason_class(r) in (rcmap.STRUCTURAL, rcmap.HUMAN) and rcmap.is_reason(r)]


def _skip_for(spec: Spec, caps: dict) -> dict | None:
    """탐침·능력 판정으로 이 경로를 건너뛸지 — 건너뛰면 ``{rc, reasons, why}``."""
    own = caps.get(spec.src) if isinstance(caps.get(spec.src), dict) else {}
    if own.get("verdict") == "불가(확정)":
        rs = _blocking(own.get("reasons")) or rcmap.norm_reasons(own.get("reasons"))
        return {"rc": 3, "reasons": sorted(r for r in rs if rcmap.is_reason(r)), "why": "confirmed"}
    if not spec.probe_key or spec.lang == "agent":
        return None
    cap = caps.get(spec.probe_key) if isinstance(caps.get(spec.probe_key), dict) else {}
    if cap.get("status") == "fail":
        rs = _blocking(cap.get("reasons"))
        if spec.probe_key == "edge_cdp_policy" and not _edge_debug_blocked(cap):
            rs = [r for r in rs if r != "R-EDGEPOL"]
        if rs:
            return {"rc": 3, "reasons": sorted(set(rs)), "why": "probe"}
    return None


def _edge_debug_blocked(cap: dict) -> bool:
    """Edge 원격 디버깅이 정책으로 막혔나 — 문서화된 통제는 ``RemoteDebuggingAllowed``(0 = 금지)뿐이다. 값이 남아 있으면 그것만
    본다(예전 탐침은 ``DeveloperToolsAvailability=2`` 만으로도 R-EDGEPOL 을 냈다 — 그런 기록으로 웹 경로를 건너뛰지 않는다,
    M365 조사 M3). 값이 없으면 사유를 믿는다."""
    val = cap.get("value") if isinstance(cap.get("value"), dict) else None
    if val is None or "remote_debugging" not in val:
        return True
    rd = val.get("remote_debugging")
    return isinstance(rd, int) and not isinstance(rd, bool) and rd == 0


def stage_plan(roles, caps, only, *, cfg=None) -> list:
    """계약 함수: 역할·탐침 결과·``--only`` → 단계 목록(실행 순서 — ``RUN_ORDER``).

    ``caps`` = ``{능력 키: {ok, status, reasons, value, verdict}}``(방금 잰 탐침 + pc.json 능력 기록). ``only`` = 경로 ID
    목록(진단용 — 모르는 이름은 ValueError) 또는 None. ``--only`` 를 주면 탐침·내보내기·원장은 돌고 업로드는 건너뛴다.
    ``cfg`` 가 있으면 라이선스 옵트인·코파일럿 단계 켜짐을 본다(없으면 둘 다 끔)."""
    roles = set(roles or ())
    caps = caps if isinstance(caps, dict) else {}
    want = None
    if only:
        want = []
        for s in only:
            if s not in COLLECTORS:
                raise ValueError(f"--only: 수집 경로 ID 가 아닙니다: {s!r}")
            want.append(s)
        want = set(want)
    out = []
    for name in RUN_ORDER:
        if name in MARKER_STAGES:
            if name == "upload" and want is not None:
                continue
            out.append(Stage(name))
            continue
        run, skip = [], {}
        for src in STAGE_SRCS.get(name, ()):
            spec = COLLECTORS[src]
            if want is not None and src not in want:
                continue
            if spec.role and spec.role not in roles:
                continue
            if src == "pc.compute" and not license_enabled(cfg):
                continue
            if spec.stage == "copilot_lookup" and not copilot_enabled(cfg, src):
                continue
            sk = _skip_for(spec, caps)
            if sk is not None:
                skip[src] = sk
            else:
                run.append(src)
        if run or skip:
            out.append(Stage(name, tuple(run), skip, parallel=name not in SERIAL_STAGES))
    return out
