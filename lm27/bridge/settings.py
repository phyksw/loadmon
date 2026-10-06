# -*- coding: utf-8 -*-
r"""브리지 설정 한 벌(B §3, 계약 §5.2 bridge.*) — 설정 레지스트리에서 ``bridge.*`` 를 읽어 ``BridgeSettings`` 로 고정한다.

규칙
  · 키 선언·기본값·범위의 원천은 ``config\settings_registry.json``(``lm27.config``). 이 모듈은 **읽기만** 한다.
    범위·형을 벗어난 값은 ``lm27.config.Cfg`` 가 기본값으로 되돌리고 경고를 남기며, 여기서는 키끼리의 일관성
    (예: ``circuitAbort > circuitSoft``, ``https://`` 접두, ``W,H`` 창 크기)을 한 번 더 보고 어긋나면 기본값 + 경고 1건.
    실행은 막지 않는다(B §3).
  · 관문 G-B2: 한도 숫자 상수는 이 파일에만 둔다. B 본문의 고정값(설정 키가 아닌 대기·폴링 간격·상한)도
    아래 '고정값' 절에 모았다 — 다른 브리지 파일은 숫자를 직접 쓰지 않고 ``settings.<이름>`` 을 쓴다.
  · 관문 G-B3: 레지스트리의 모든 ``bridge.*`` 키를 ``KEYS`` 표로 읽는다(죽은 키·유령 키 0). 조회 능력 TTL·확정 횟수는
    계약 §5.4 개명대로 ``collect.confirmTtlDays``·``collect.confirmBlockedCount`` 를 읽는다.
"""
from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# ───────────────────────── 고정값(B 본문 — 설정 키 아님) ─────────────────────────
ROLES = ("bridge", "owa", "teams_web")                 # L0 역할(프로필·포트·잠금 공용, B §4.5)
STAGE_IDS = ("lookup_mail", "lookup_teams", "lookup_calendar", "speech_act", "task_label", "taxonomy_bootstrap",
             "taxonomy_consolidate", "workflow_label", "review_text", "agentic_match", "subagent_review")

HTTP_TIMEOUT_S = 5.0            # /json HTTP 한 번(LM24 http_json)
CDP_CALL_TIMEOUT_S = 25.0       # CDP 호출 기본 한도(LM24 CDP.call)
CDP_SLOW_EVAL_S = 30.0          # 큰 DOM innerText 평가 한도
CDP_SOCKET_CAP_S = 30.0         # 소켓 settimeout 상한(B §4.4 min(남은 시간, 30))
CDP_SOCKET_MIN_S = 0.5
WS_MAX_FRAME = 64 * 1024 * 1024  # 수신 프레임 길이 상한(B §4.4)
WS_HANDSHAKE_MAX = 16 * 1024    # 핸드셰이크 응답 머리 상한
JS_ERROR_MAX = 200              # JS 예외 문구 상한(B §4.4)
ERROR_CODE_MAX = 120            # SendResult.error 상한(B §5.1)

LAUNCH_WAIT_S = 20.0            # 기동 뒤 /json/version 응답 대기(B §4.3)
LAUNCH_POLL_S = 0.5
PROFILE_BUSY_RECHECK_S = 30.0   # profile_busy 30초 뒤 1회 재확인(B §4.3)
CLOSE_WAIT_S = 5.0              # Browser.close 뒤 포트 닫힘 대기(B §4.9)
LOCK_HEARTBEAT_S = 30.0         # 잠금 하트비트 간격(B §4.5)
LOCK_STALE_S = 30 * 60          # 살아 있으나 30분 무응답 = 멈춘 소유자(B §4.5)
LOCK_BUSY_RETRIES = 3           # BR-LOCK-BUSY: 60초 간격 3회 재시도(B §13)
LOCK_BUSY_WAIT_S = 60.0
LOGIN_POLL_S = 5.0              # 로그인 대기 폴링(B §4.7)
LOGIN_PENDING_CHECK_S = 30.0    # 로그인 보류(지난 대기가 로그인 없이 끝남) — 다음 실행은 이만큼만 로그인 상태를 본다(v1.3 V18)
LOGIN_RECHECK_S = 60.0          # login_required 1차 복구: 탭 재진입 뒤 폴링 상한(B §7.7 — 보류 중이면 다시 기다리지 않음)
LOGIN_GRACE_S = 3.0             # 로그인 화면이 이만큼(폴링 2회 이상) 이어질 때만 창을 앞으로·BR-LOGIN — SSO 로 한순간 지나가면 조용히(L1)
LOGIN_PERSIST_DAYS = 7          # 직전 로그인 확인 뒤 이 안에 새로 띄운 Edge 가 다시 로그인 화면이면 '로그인 유지 안 됨' 안내(H2)
# 개인(Microsoft) 계정 로그인 화면 호스트 — 회사(조직) 계정이 아니다(V18). bridge.loginHosts 의 부분집합이어야 대기 판정이 같다
# (Microsoft 365 URL 목록 ID 97·116 — login.live.com · account.live.com)
PERSONAL_LOGIN_HOSTS = ("login.live.com", "account.live.com")
# 로그인 흐름이 끝난 뒤의 Microsoft 앱 호스트(접미사 — Microsoft 365 URL 목록 ID 1·12·147·184). 브리지가 로그인 화면을 본 뒤
# 이 밖의 호스트(회사 IdP — AD FS·PingFederate 등)에 있으면 아직 로그인 중으로 본다(H3). 부분 문자열이 아니라 마디 단위 접미사.
MS_APP_HOST_RX = re.compile(r"(?:^|\.)(?:cloud\.microsoft|microsoft\.com|microsoft365\.com|office\.com|office365\.com"
                            r"|outlook\.com|live\.com|bing\.com|m365copilot\.com)$")
EDGE_HOLD_MAX_S = 4 * 3600.0    # 한 작업(수집→분석) 동안 Edge 를 닫지 않고 이어 쓰는 표지의 최대 수명(주인이 풀지 못한 경우의 안전판, H2)
FRONT_TTL_S = 3600.0            # [분석용 Edge 창 앞으로]·작업 보류가 남긴 디버그 포트 Edge 를 정리하는 유휴 한도(L12)
MODEL_ALIASES = {"빠른 응답": ("Quick response",), "깊이 생각하기": ("Think deeper",), "자동": ("Auto",)}  # 영어 화면(L11)
# 화면 등급 표식(제품 안 라벨 'Copilot (Premium)'·'Copilot Chat (Basic)' — 읽기만, 'copilot' 이 든 짧은 글에서만, L11)
TIER_LABELS = {"premium": ("(premium)", "(프리미엄)"), "basic": ("(basic)", "(기본)")}
IDENTITY_POLL_S = 1.0           # 신원 재확인 간격
IDENTITY_SETTLE_S = 20.0        # wrong_page 이동·dead 새로고침 뒤 재확인 상한(B §4.7)
DEAD_SESSION_LIMIT = 2          # 서로 다른 호출 2회 dead_session → 프로필 재생성(B §4.7)
BAD_PROFILE_KEEP = 1            # 이전 .bad-* 는 1개만 남김
DIAG_MASK_CHARS = 40            # diagnose 형식 보존 마스킹 앞 40자(B §12.4)
DIAG_MAX_NODES = 40

FOCUS_POLL_S = 1.0              # 입력창 찾기 폴링
INJECT_SETTLE_S = 0.4           # 주입 뒤 편집기 확인까지(B §5.3)
MATCH_LEN_TOL = 2               # 주입 검증: 길이 차 ≤ 2
MATCH_TAIL = 32                 # 주입 검증: 꼬리 32자 일치
OVERFLOW_HEAD = 200             # input_overflow 판정: 앞 200자 접두
SEND_CONFIRM_S = 3.0            # 전송 확인 폴링 상한(B §5.4)
SEND_CONFIRM_POLL_S = 0.5
SENT_EMPTY_LEN = 5              # 편집기 정규화 길이 < 5 = 비었음
SEND_RETRY_IDLE_S = 30.0        # 전송 실패 뒤 생성 끝 대기 상한
WAIT_IDLE_POLL_S = 2.0          # 앞 답 생성 중 확인 간격(LM24 wait_idle)
PLEDGE_TAIL_S = 1.0             # 서약 확인 뒤 렌더 꼬리 1회 더(B §5.6)
LAST_TEXT_CAP = 60_000          # 스냅샷 마지막 답 노드 글자 상한(B §5.5)
NEW_CHAT_WAIT_S = 10.0          # 새 채팅 전환 확인(B §5.7)
NEW_CHAT_POLL_S = 0.5
ANCHOR_LINES = 8                # 앵커 폴백: 마지막 8줄 중 가장 긴 줄(LM24 build_anchor)
ANCHOR_MIN = 20
ANCHOR_MAX = 100
ANCHOR_SLACK = 2000             # 앵커 위치 허용 오차(LM24 pick_reply)
DOM_FAIL_LIMIT = 2              # 학습 선택자 실패 2회 → 지우고 다시 학습(B §5.5)
LEARN_HEAD = 15                 # 학습 시 프롬프트 앞 15자 배제

MODEL_NOTE_MAX = 60             # 모델 버튼 표기 상한(B §4.2)
MENU_SEEN_MAX = 8               # ModelNote.menu_seen 상한(B §4.8)
MENU_DEPTH = 3                  # 하위 메뉴 3단(LM24 select_model)
MENU_SETTLE_S = 0.9
MENU_REOPEN_S = 1.0
MENU_PICK_S = 0.7
WORK_MODE_SETTLE_S = 1.0        # 업무 모드 버튼 클릭 뒤 재확인까지
FRONT_NUDGE_S = 0.3             # [분석용 Edge 창 앞으로]: 창을 내렸다 되살리는 사이(Windows 가 다른 프로세스 창을 앞으로 못 올릴 때)
FRONT_CALL_TIMEOUT_S = 5.0      # [분석용 Edge 창 앞으로] CDP 호출 한 번(화면 요청 안에서 끝나야 한다)

TRACE_STR_MAX = 60              # 계측 줄 문자열 값 상한(원문 없음)
RUNG_REPLY_FLOOR_S = 120        # 사다리 1·2단 답 대기 하한(B §6.7)
RUNG_FIRST_FLOOR_S = 30         # 사다리 1·2단 첫 글자 유예 하한

_URL_PREFIX = "https://"
# 로그인 호스트: 정확 일치 또는 '.' 으로 시작하면 마디 단위 접미사(예 '.microsoftonline.com' — certauth·logincert 등, H3)
_HOST_RX = re.compile(r"^\.?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_WINDOW_RX = re.compile(r"^\d{2,5},\d{2,5}$")
_PORT_MAX = 65535


def host_in(host: str, entries) -> bool:
    """호스트가 목록에 드는가 — 정확 일치, '.' 으로 시작하는 항목은 마디 단위 접미사(부분 문자열 비교 금지, G-B9)."""
    h = str(host or "").lower().rstrip(".")
    if not h:
        return False
    for e in entries or ():
        e = str(e or "").lower()
        if e.startswith("."):
            if h.endswith(e) and len(h) > len(e):
                return True
        elif h == e:
            return True
    return False


def model_names(name: str) -> tuple[str, ...]:
    """모델 메뉴 이름(설정 값) → 찾아볼 표기 목록. '|' 로 나눈 별칭 + 한국어 기본 이름의 영어 표기(L11 — 영어 화면)."""
    out: list[str] = []
    for part in str(name or "").split("|"):
        p = part.strip()
        if p and p not in out:
            out.append(p)
        for alias in MODEL_ALIASES.get(p, ()):
            if alias not in out:
                out.append(alias)
    return tuple(out)


# ───────────────────────── 설정 묶음 ─────────────────────────
@dataclass(frozen=True)
class EdgeCfg:
    port: int
    port_tries: int
    profile_dir: str
    disk_cache_mb: int
    window_size: str
    close_on_exit: bool


@dataclass(frozen=True)
class LookupCfg:
    window_days: int
    min_window_days: int
    max_rows: int
    full_ratio: float


@dataclass(frozen=True)
class ManualCfg:
    max_open_batches: int
    ttl_days: int


@dataclass(frozen=True)
class DomCfg:
    input_selectors: tuple[str, ...]
    input_aria_labels: tuple[str, ...]
    send_labels: tuple[str, ...]
    stop_labels: tuple[str, ...]
    new_chat_labels: tuple[str, ...]
    model_button_labels: tuple[str, ...]
    work_labels: tuple[str, ...]          # bridge.dom.workModeLabels.work
    web_labels: tuple[str, ...]           # bridge.dom.workModeLabels.web
    web_grounding_labels: tuple[str, ...]
    assistant_selectors: tuple[str, ...]
    toggle_labels: tuple[str, ...] = ()   # bridge.dom.workModeLabels.toggle — 단일 토글 'Work IQ'(부분 일치, H13)
    account_labels: tuple[str, ...] = ()  # bridge.dom.workModeLabels.account — 탐색 창 프로필 아래 'Work' 표시(정확 일치, H4)
    shield_labels: tuple[str, ...] = ()   # bridge.dom.workModeLabels.shield — 녹색 데이터 보호 방패 aria·title(부분 일치, H4)


@dataclass(frozen=True)
class BridgeSettings:
    """``bridge.*`` 실효 값(읽기 전용). 하위 묶음 ``edge``·``lookup``·``manual``·``dom``."""

    mode: str
    auto_manual_fallback: bool
    url: str
    chat_url_prefixes: tuple[str, ...]
    login_hosts: tuple[str, ...]
    edge: EdgeCfg
    login_wait_min: int
    ready_wait_sec: int
    model_fast: str
    model_deep: str
    model_fallback: str
    prefer_work_mode: bool
    web_exposure_policy: str
    poll_sec: float
    stable_polls: int
    incomplete_json_factor: int
    first_token_sec: int
    reply_timeout_sec: int
    roundtrip_max_sec: int
    wait_idle_sec: int
    chat_turns: int
    input_max_chars: int
    answer_max_chars: int
    calib_safety: float
    calibrate_ttl_days: int
    auto_calibrate: bool
    overlap_items: int
    overlap_chars: int
    seen_names_max: int
    seen_names_chars: int
    split_min_items: int
    split_max_depth: int
    max_asks_per_item: int
    circuit_soft: int
    circuit_abort: int
    stage_budget_min: int
    total_budget_min: int
    stage_floor_min: int
    final_reserve_min: int
    min_ask_sec: int
    lookup: LookupCfg
    manual: ManualCfg
    raw_capture: bool
    raw_capture_ttl_days: int
    trace_max_bytes: int
    stages: tuple[tuple[str, bool], ...]
    dom: DomCfg
    confirm_count: int                    # collect.confirmBlockedCount(조회 능력 확정 날짜 수 — 계약 §5.4)
    confirm_ttl_days: int                 # collect.confirmTtlDays(조회 능력 확정 TTL·계정 등급 판별 창)
    warnings: tuple[dict, ...] = field(default=(), compare=False)

    # 편의 ------------------------------------------------------------------
    def stage_on(self, stage_id: str) -> bool:
        """``bridge.stages`` 의 켜짐 여부(표에 없는 단계는 켜짐)."""
        return dict(self.stages).get(stage_id, True)

    def stages_map(self) -> dict:
        return dict(self.stages)

    def model_for(self, model_class: str) -> str:
        """단계 등급(fast·deep·fallback) → 모델 메뉴 이름. 빈 문자열 = 건드리지 않음."""
        return {"fast": self.model_fast, "deep": self.model_deep, "fallback": self.model_fallback}.get(model_class, "")

    def login_host(self, host: str) -> bool:
        """``bridge.loginHosts`` 판정 — 정확 일치, '.' 으로 시작하는 항목은 마디 단위 접미사(H3)."""
        return host_in(host, self.login_hosts)

    def rung_timeouts(self, rung: int) -> tuple[float, float]:
        """재시도 사다리 단 → (답 대기 초, 첫 글자 유예 초)(B §6.7 한 벌). 0단 = 설정값, 1·2단 = 절반(하한 120·30)."""
        reply, first = float(self.reply_timeout_sec), float(self.first_token_sec)
        if rung <= 0:
            return reply, first
        return float(max(RUNG_REPLY_FLOOR_S, int(reply) // 2)), float(max(RUNG_FIRST_FLOOR_S, int(first) // 2))

    def window_wh(self) -> tuple[int, int]:
        w, h = self.edge.window_size.split(",")
        return int(w), int(h)

    def ports(self) -> range:
        """디버그 포트 후보(시작값부터 portTries 개 — 역할 공용, B §4.5)."""
        return range(self.edge.port, min(_PORT_MAX, self.edge.port + self.edge.port_tries - 1) + 1)

    def profile_dir(self, paths) -> Path:
        """Edge 전용 프로필 폴더. 빈 값 = ``lm27.paths.Paths.edge_profile()``(계약 §5.1-7 예외 경로 키)."""
        raw = self.edge.profile_dir.strip()
        if not raw:
            return Path(paths.edge_profile())
        return Path(os.path.abspath(os.path.expandvars(raw)))

    def replace(self, **kw) -> BridgeSettings:
        """일부 값만 바꾼 사본(실행 중 적응·시험용). 하위 묶음은 ``edge=dataclasses.replace(s.edge, …)`` 로."""
        return dataclasses.replace(self, **kw)


# ───────────────────────── 키 표(G-B3 — 레지스트리의 bridge.* 전부) ─────────────────────────
# (설정 키, 속성 경로)
KEYS: tuple[tuple[str, str], ...] = (
    ("bridge.mode", "mode"),
    ("bridge.autoManualFallback", "auto_manual_fallback"),
    ("bridge.url", "url"),
    ("bridge.chatUrlPrefixes", "chat_url_prefixes"),
    ("bridge.loginHosts", "login_hosts"),
    ("bridge.edge.port", "edge.port"),
    ("bridge.edge.portTries", "edge.port_tries"),
    ("bridge.edge.profileDir", "edge.profile_dir"),
    ("bridge.edge.diskCacheMb", "edge.disk_cache_mb"),
    ("bridge.edge.windowSize", "edge.window_size"),
    ("bridge.edge.closeOnExit", "edge.close_on_exit"),
    ("bridge.loginWaitMin", "login_wait_min"),
    ("bridge.readyWaitSec", "ready_wait_sec"),
    ("bridge.modelFast", "model_fast"),
    ("bridge.modelDeep", "model_deep"),
    ("bridge.modelFallback", "model_fallback"),
    ("bridge.preferWorkMode", "prefer_work_mode"),
    ("bridge.webExposure.policy", "web_exposure_policy"),
    ("bridge.pollSec", "poll_sec"),
    ("bridge.stablePolls", "stable_polls"),
    ("bridge.incompleteJsonFactor", "incomplete_json_factor"),
    ("bridge.firstTokenSec", "first_token_sec"),
    ("bridge.replyTimeoutSec", "reply_timeout_sec"),
    ("bridge.roundtripMaxSec", "roundtrip_max_sec"),
    ("bridge.waitIdleSec", "wait_idle_sec"),
    ("bridge.chatTurns", "chat_turns"),
    ("bridge.inputMaxChars", "input_max_chars"),
    ("bridge.answerMaxChars", "answer_max_chars"),
    ("bridge.calibSafety", "calib_safety"),
    ("bridge.calibrateTtlDays", "calibrate_ttl_days"),
    ("bridge.autoCalibrate", "auto_calibrate"),
    ("bridge.overlapItems", "overlap_items"),
    ("bridge.overlapChars", "overlap_chars"),
    ("bridge.seenNamesMax", "seen_names_max"),
    ("bridge.seenNamesChars", "seen_names_chars"),
    ("bridge.splitMinItems", "split_min_items"),
    ("bridge.splitMaxDepth", "split_max_depth"),
    ("bridge.maxAsksPerItem", "max_asks_per_item"),
    ("bridge.circuitSoft", "circuit_soft"),
    ("bridge.circuitAbort", "circuit_abort"),
    ("bridge.stageBudgetMin", "stage_budget_min"),
    ("bridge.totalBudgetMin", "total_budget_min"),
    ("bridge.stageFloorMin", "stage_floor_min"),
    ("bridge.finalReserveMin", "final_reserve_min"),
    ("bridge.minAskSec", "min_ask_sec"),
    ("bridge.lookup.windowDays", "lookup.window_days"),
    ("bridge.lookup.minWindowDays", "lookup.min_window_days"),
    ("bridge.lookup.maxRows", "lookup.max_rows"),
    ("bridge.lookup.fullRatio", "lookup.full_ratio"),
    ("bridge.manual.maxOpenBatches", "manual.max_open_batches"),
    ("bridge.manual.ttlDays", "manual.ttl_days"),
    ("bridge.rawCapture", "raw_capture"),
    ("bridge.rawCaptureTtlDays", "raw_capture_ttl_days"),
    ("bridge.traceMaxBytes", "trace_max_bytes"),
    ("bridge.stages", "stages"),
    ("bridge.dom.inputSelectors", "dom.input_selectors"),
    ("bridge.dom.inputAriaLabels", "dom.input_aria_labels"),
    ("bridge.dom.sendLabels", "dom.send_labels"),
    ("bridge.dom.stopLabels", "dom.stop_labels"),
    ("bridge.dom.newChatLabels", "dom.new_chat_labels"),
    ("bridge.dom.modelButtonLabels", "dom.model_button_labels"),
    ("bridge.dom.workModeLabels", "dom.work_mode_labels"),
    ("bridge.dom.webGroundingLabels", "dom.web_grounding_labels"),
    ("bridge.dom.assistantSelectors", "dom.assistant_selectors"),
    ("collect.confirmBlockedCount", "confirm_count"),
    ("collect.confirmTtlDays", "confirm_ttl_days"),
)


def _warn(code: str, key: str, text_ko: str) -> dict:
    return {"code": code, "key": key, "text_ko": text_ko}


def _tup(v) -> tuple:
    return tuple(v) if isinstance(v, list | tuple) else ()


def _https_ok(u) -> bool:
    if not isinstance(u, str) or not u.startswith(_URL_PREFIX):
        return False
    from urllib.parse import urlsplit
    try:
        return bool(urlsplit(u).hostname)
    except ValueError:
        return False


class _Reader:
    """Cfg 에서 값을 읽고(읽힘 기록), 일관성 검사로 기본값을 되돌릴 때 경고를 모은다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.warnings: list[dict] = []

    def get(self, key: str):
        return self.cfg[key]

    def default(self, key: str):
        return self.cfg.meta(key).default

    def revert(self, key: str, why: str):
        meta = self.cfg.meta(key)
        self.warnings.append(_warn("inconsistent", key, f"{meta.label_ko}: {why} — 기본값을 씁니다"))
        return meta.default


def from_cfg(cfg) -> BridgeSettings:
    """``lm27.config.Cfg`` → ``BridgeSettings``. 레지스트리에 없는 키를 읽으면 ``UnknownKeyError``(fail-closed)."""
    r = _Reader(cfg)
    raw = {key: r.get(key) for key, _attr in KEYS}

    url = raw["bridge.url"]
    if not _https_ok(url):
        url = r.revert("bridge.url", "https:// 로 시작하는 주소가 아닙니다")
    prefixes = tuple(p for p in _tup(raw["bridge.chatUrlPrefixes"]) if _https_ok(p))
    if len(prefixes) != len(_tup(raw["bridge.chatUrlPrefixes"])) or not prefixes:
        prefixes = tuple(r.revert("bridge.chatUrlPrefixes", "https:// 로 시작하지 않는 접두가 있습니다"))
    hosts = tuple(h.strip().lower() for h in _tup(raw["bridge.loginHosts"]) if isinstance(h, str))
    if not hosts or not all(_HOST_RX.match(h) for h in hosts):
        hosts = tuple(h.lower() for h in r.revert("bridge.loginHosts", "호스트 이름 형식이 아닌 값이 있습니다"))
    window = raw["bridge.edge.windowSize"]
    if not isinstance(window, str) or not _WINDOW_RX.match(window):
        window = r.revert("bridge.edge.windowSize", "'가로,세로' 형식이 아닙니다")
    port, tries = raw["bridge.edge.port"], raw["bridge.edge.portTries"]
    if port + tries - 1 > _PORT_MAX:
        tries = r.revert("bridge.edge.portTries", "포트 범위가 65535 를 넘습니다")
        if port + tries - 1 > _PORT_MAX:
            port = r.revert("bridge.edge.port", "포트 범위가 65535 를 넘습니다")
    soft, abort = raw["bridge.circuitSoft"], raw["bridge.circuitAbort"]
    if abort <= soft:
        soft = r.revert("bridge.circuitSoft", "중단 문턱(circuitAbort)보다 작아야 합니다")
        abort = r.revert("bridge.circuitAbort", "soft 문턱(circuitSoft)보다 커야 합니다")
    wd, mwd = raw["bridge.lookup.windowDays"], raw["bridge.lookup.minWindowDays"]
    if mwd > wd:
        mwd = r.revert("bridge.lookup.minWindowDays", "조회 구간 길이(windowDays)보다 클 수 없습니다")
        if mwd > wd:
            wd = r.revert("bridge.lookup.windowDays", "최소 구간보다 짧을 수 없습니다")
    wml = raw["bridge.dom.workModeLabels"] or {}
    work_labels, web_labels = _tup(wml.get("work")), _tup(wml.get("web"))
    if not work_labels or not web_labels:
        wml = r.revert("bridge.dom.workModeLabels", "업무·웹 라벨이 비었습니다")
        work_labels, web_labels = _tup(wml.get("work")), _tup(wml.get("web"))
    toggle_labels = _tup(wml.get("toggle"))
    account_labels, shield_labels = _tup(wml.get("account")), _tup(wml.get("shield"))
    stages_raw = raw["bridge.stages"] or {}
    stages = tuple((sid, bool(stages_raw.get(sid, True))) for sid in STAGE_IDS)

    # 경고 거르기도 리터럴 키 표(KEYS)로만 — 접두 조립을 두지 않아 L-12 죽은 키 검사가 접두로 가려지지 않는다(W1a R11)
    key_set = frozenset(key for key, _attr in KEYS)
    cfg_warn = tuple(w for w in getattr(cfg, "config_warnings", ()) if w.get("key") in key_set)
    return BridgeSettings(
        mode=raw["bridge.mode"],
        auto_manual_fallback=bool(raw["bridge.autoManualFallback"]),
        url=url,
        chat_url_prefixes=prefixes,
        login_hosts=hosts,
        edge=EdgeCfg(port=int(port), port_tries=int(tries), profile_dir=str(raw["bridge.edge.profileDir"] or ""),
                     disk_cache_mb=int(raw["bridge.edge.diskCacheMb"]), window_size=window,
                     close_on_exit=bool(raw["bridge.edge.closeOnExit"])),
        login_wait_min=int(raw["bridge.loginWaitMin"]),
        ready_wait_sec=int(raw["bridge.readyWaitSec"]),
        model_fast=str(raw["bridge.modelFast"]),
        model_deep=str(raw["bridge.modelDeep"]),
        model_fallback=str(raw["bridge.modelFallback"]),
        prefer_work_mode=bool(raw["bridge.preferWorkMode"]),
        web_exposure_policy=raw["bridge.webExposure.policy"],
        poll_sec=float(raw["bridge.pollSec"]),
        stable_polls=int(raw["bridge.stablePolls"]),
        incomplete_json_factor=int(raw["bridge.incompleteJsonFactor"]),
        first_token_sec=int(raw["bridge.firstTokenSec"]),
        reply_timeout_sec=int(raw["bridge.replyTimeoutSec"]),
        roundtrip_max_sec=int(raw["bridge.roundtripMaxSec"]),
        wait_idle_sec=int(raw["bridge.waitIdleSec"]),
        chat_turns=int(raw["bridge.chatTurns"]),
        input_max_chars=int(raw["bridge.inputMaxChars"]),
        answer_max_chars=int(raw["bridge.answerMaxChars"]),
        calib_safety=float(raw["bridge.calibSafety"]),
        calibrate_ttl_days=int(raw["bridge.calibrateTtlDays"]),
        auto_calibrate=bool(raw["bridge.autoCalibrate"]),
        overlap_items=int(raw["bridge.overlapItems"]),
        overlap_chars=int(raw["bridge.overlapChars"]),
        seen_names_max=int(raw["bridge.seenNamesMax"]),
        seen_names_chars=int(raw["bridge.seenNamesChars"]),
        split_min_items=int(raw["bridge.splitMinItems"]),
        split_max_depth=int(raw["bridge.splitMaxDepth"]),
        max_asks_per_item=int(raw["bridge.maxAsksPerItem"]),
        circuit_soft=int(soft),
        circuit_abort=int(abort),
        stage_budget_min=int(raw["bridge.stageBudgetMin"]),
        total_budget_min=int(raw["bridge.totalBudgetMin"]),
        stage_floor_min=int(raw["bridge.stageFloorMin"]),
        final_reserve_min=int(raw["bridge.finalReserveMin"]),
        min_ask_sec=int(raw["bridge.minAskSec"]),
        lookup=LookupCfg(window_days=int(wd), min_window_days=int(mwd), max_rows=int(raw["bridge.lookup.maxRows"]),
                         full_ratio=float(raw["bridge.lookup.fullRatio"])),
        manual=ManualCfg(max_open_batches=int(raw["bridge.manual.maxOpenBatches"]),
                         ttl_days=int(raw["bridge.manual.ttlDays"])),
        raw_capture=bool(raw["bridge.rawCapture"]),
        raw_capture_ttl_days=int(raw["bridge.rawCaptureTtlDays"]),
        trace_max_bytes=int(raw["bridge.traceMaxBytes"]),
        stages=stages,
        dom=DomCfg(input_selectors=_tup(raw["bridge.dom.inputSelectors"]),
                   input_aria_labels=_tup(raw["bridge.dom.inputAriaLabels"]),
                   send_labels=_tup(raw["bridge.dom.sendLabels"]),
                   stop_labels=_tup(raw["bridge.dom.stopLabels"]),
                   new_chat_labels=_tup(raw["bridge.dom.newChatLabels"]),
                   model_button_labels=_tup(raw["bridge.dom.modelButtonLabels"]),
                   work_labels=work_labels, web_labels=web_labels,
                   web_grounding_labels=_tup(raw["bridge.dom.webGroundingLabels"]),
                   assistant_selectors=_tup(raw["bridge.dom.assistantSelectors"]),
                   toggle_labels=toggle_labels, account_labels=account_labels, shield_labels=shield_labels),
        confirm_count=int(raw["collect.confirmBlockedCount"]),
        confirm_ttl_days=int(raw["collect.confirmTtlDays"]),
        warnings=cfg_warn + tuple(r.warnings),
    )


def load_settings(paths=None, *, cfg=None, overrides=None) -> BridgeSettings:
    """설정을 읽어 ``BridgeSettings`` 로. ``cfg`` 를 주면 그것을, 아니면 ``lm27.config.load_config(paths)``.
    ``overrides`` = 키 → 값(시험·보정용, 미등록 키는 UnknownKeyError)."""
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths, overrides=overrides)
    elif overrides:
        cfg = cfg.derive(overrides)
    return from_cfg(cfg)
