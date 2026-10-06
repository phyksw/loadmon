# -*- coding: utf-8 -*-
r"""브리지 사용자 문구 표 ``BR-*``(B §13) 와 L1 단계(phase) → 문구·치명 여부 대응(LM24 ``explain_failure`` 이식).

원칙(B §13): ① 무엇이 됐는지 → 무엇이 남았는지 → 프로그램이 스스로 무엇을 할지 ② 사용자에게 시키는 일은
'로그인'과 '붙여넣기'뿐 ③ 원문·이름·계정을 넣지 않는다 ④ 같은 코드는 한 실행에서 한 번만.

    render("BR-LOGIN", loginWaitMin=10)     → {"code", "title", "body", "action", "text_ko"}
    Notices().notify("BR-LOGIN", …)          → 처음 한 번만 표준 출력 이벤트 ``notice`` 를 내고 True
    explain_phase("login_required")          → ("BR-LOGIN", True)
"""
from __future__ import annotations

import string

# 코드: (화면 제목, 본문, 프로그램이 스스로 하는 일) — B §13 글자 그대로
BR: dict[str, tuple[str, str, str]] = {
    "BR-LOGIN": ("Copilot 로그인이 필요합니다",
                 "분석용 Edge 창을 앞으로 띄웠습니다. 그 창에서 회사 계정으로 한 번 로그인해 주세요. 로그인하면 자동으로 이어서 진행합니다.",
                 "최대 {loginWaitMin}분 동안 5초마다 확인"),
    "BR-LOGIN-OK": ("로그인을 확인했습니다", "남은 AI 분석을 이어서 진행합니다.", "—"),
    "BR-LOGIN-TIMEOUT": ("로그인을 기다리다 AI 분석을 멈췄습니다",
                         "지금까지 처리한 {done}건은 저장했습니다. 남은 {left}건은 규칙 분류로 임시 표시했고, "
                         "다음 분석 때 로그인되어 있으면 남은 것부터 자동으로 이어 합니다.",
                         "재개 표시, 다음 실행에서 이어 하기"),
    # 로그인 보류(계약 v1.3 §0.8 V18 — 회사 계정이 없는 PC). 세션(lm27.bridge.session)이 내고, 글자는 이 표가 정본이다
    "BR-LOGIN-PENDING": ("로그인 전이라 웹·AI 단계를 건너뜁니다",
                         "지난번에 로그인을 기다렸지만 로그인되지 않아, 이번에는 오래 기다리지 않고 로그인 상태만 확인했습니다. "
                         "회사 계정으로 로그인하려면 화면의 [분석용 Edge 창 앞으로]를 누른 뒤 그 창에서 로그인하세요. 그동안 분석은 "
                         "PC 자료로 진행합니다.",
                         "{sec}초만 확인한 뒤 건너뜀(다음 수집·분석에서 다시 확인)"),
    "BR-LOGIN-PERSONAL": ("회사(조직) 계정이 아닌 로그인 화면입니다",
                          "회사(조직) 계정이 아니면 메일·팀즈 웹 수집과 AI 판정은 건너뛰고 PC 자료로 분석합니다.",
                          "개인 계정으로는 로그인을 기다리지 않음(다음부터 짧게 확인)"),
    "BR-EDGE": ("Microsoft Edge 를 찾지 못했습니다",
                "이 PC 에서는 Copilot 자동 연결을 쓸 수 없어 '직접 붙여넣기' 방식으로 바꿨습니다.",
                "수동 경로 전환(설정에 따라)"),
    "BR-POLICY": ("회사 정책이 자동 연결을 막고 있습니다",
                  "이 PC 의 Edge 는 자동 조작(디버그 포트)이 허용되지 않습니다. '직접 붙여넣기' 방식으로 바꿨습니다. "
                  "결과는 같은 검증을 거칩니다.",
                  "수동 경로 전환"),
    "BR-MANUAL-SWITCH": ("직접 붙여넣기 방식으로 진행합니다",
                         "AI 에게 보낼 묶음 {k}개를 준비했습니다. [복사] → Copilot 창에 붙여넣기 → 답 전체를 복사해 "
                         "[답 붙여넣기]에 넣어 주세요. 순서는 상관없습니다.",
                         "반입마다 자동 검증·재질의 묶음 생성"),
    "BR-MANUAL-RID": ("이 요청의 답이 아닙니다",
                      "붙여넣은 답에서 대기 중인 요청 번호를 찾지 못했습니다. 다른 채팅이나 이전 답을 복사했을 수 있습니다. "
                      "해당 묶음의 Copilot 답을 다시 복사해 주세요.",
                      "저장소 변화 없음"),
    "BR-MANUAL-NOENV": ("답 형식을 찾지 못했습니다",
                        "붙여넣은 글에 JSON 답이 없습니다. Copilot 답 전체(코드 블록 포함)를 복사했는지 확인해 주세요.", "—"),
    "BR-MANUAL-DONE": ("답을 반영했습니다",
                       "{ok}건 반영, {retry}건은 다시 물을 묶음에 넣었습니다(남은 묶음 {k}개).", "다음 묶음 생성"),
    "BR-INPUT": ("Copilot 입력창을 찾지 못했습니다",
                 "화면을 새로 고치고 다시 확인했지만 입력창이 보이지 않습니다. 화면 구조 진단을 저장했습니다. "
                 "다음 분석 때 자동으로 다시 시도합니다.",
                 "진단 덤프, 재개 표시"),
    "BR-TAB": ("Copilot 창이 닫혔습니다", "분석용 탭을 다시 열어 이어서 진행합니다.", "자기 탭 재생성"),
    "BR-DEAD-PROFILE": ("분석용 Edge 의 로그인 정보가 손상되었습니다",
                        "새 분석용 프로필을 만들었습니다. 열린 Edge 창에서 한 번 로그인해 주세요.", "프로필 재생성 → BR-LOGIN"),
    "BR-LAUNCH": ("분석용 Edge 를 띄우지 못했습니다",
                  "다른 포트로 다시 시도했지만 실패했습니다. 다음 분석 때 자동으로 다시 시도합니다.", "재개 표시"),
    "BR-PROFILE-FOREIGN": ("설정한 Edge 프로필 폴더를 쓰지 않았습니다",
                           "설정의 Edge 프로필 폴더가 분석 전용 폴더가 아니어서(브라우저 기본 프로필이거나 다른 파일이 든 "
                           "폴더) 건드리지 않았습니다. 기본 분석 전용 프로필로 진행합니다.",
                           "기본 전용 프로필 사용(설정 폴더는 그대로 둠)"),
    "BR-PROFILE-BUSY": ("분석용 Edge 가 다른 방식으로 열려 있습니다",
                        "분석용 Edge 창이 자동 연결 없이 열려 있습니다. 30초 뒤 다시 확인합니다.", "30초 뒤 재확인"),
    "BR-LOCK-BUSY": ("다른 분석이 Copilot 을 쓰고 있습니다",
                     "이 PC 에서 다른 수집·분석이 같은 Edge 를 쓰는 중입니다. 끝나면 이어서 진행합니다.", "60초 간격 3회 재시도"),
    "BR-SLOW": ("Copilot 응답이 느립니다",
                "한 묶음에 {min}분째 답을 기다리고 있습니다. 새 채팅으로 다시 보내는 중입니다.", "사다리 진행"),
    "BR-SERVICE": ("Copilot 일시 오류",
                   "Copilot 이 일시적으로 응답하지 못했습니다. 새 채팅·다른 모델로 다시 보냈습니다.", "사다리·연기"),
    "BR-CIRCUIT-SOFT": ("같은 실패가 이어집니다",
                        "최근 {n}번 연속으로 답을 얻지 못해 재시도를 줄였습니다.", "soft 모드"),
    "BR-CIRCUIT": ("AI 분석을 잠시 멈췄습니다",
                   "{n}번 연속으로 답을 얻지 못했습니다. 처리한 {done}건은 저장했고, 남은 것은 다음 분석 때 자동으로 이어 합니다.",
                   "재개 표시"),
    "BR-BUDGET": ("AI 분석 시간 예산을 다 썼습니다",
                  "{stage} 단계에서 {done}/{total}건을 처리했습니다. 남은 {left}건은 규칙 분류로 임시 표시했고 "
                  "다음 분석 때 이어 합니다.",
                  "재개 표시"),
    "BR-REFUSED": ("Copilot 이 일부 항목 답을 거절했습니다", "{n}건은 규칙 분류로 처리했습니다.", "규칙 커밋"),
    "BR-GATE": ("개인정보 때문에 일부 항목을 보내지 않았습니다",
                "전송 전 재검사에서 {n}건이 걸렸습니다(유형별 건수: {hits}). 해당 항목은 규칙 분류로 처리했습니다.", "규칙 커밋"),
    "BR-GATE-BLOCKED": ("전송 직전 검사에서 AI 분석을 멈췄습니다",
                        "{stage} 단계의 보낼 글에서 개인정보 형식({types})이 발견되어 아무것도 보내지 않았습니다. "
                        "과제 설명·에이전트 목록 같은 팀 목록에 원인이 있을 수 있으니 팀 레지스트리 관리자에게 알리세요. "
                        "남은 항목은 규칙 분류로 임시 표시했습니다.",
                        "단계 중지(설정·템플릿 문제, 재시도 없음)"),
    "BR-HEADER": ("목록이 너무 깁니다",
                  "과제·어휘 목록이 Copilot 입력 한도를 넘어 {stage} 단계를 멈췄습니다. 팀 레지스트리 관리자에게 알리세요.",
                  "단계 중지"),
    "BR-LOOKUP-UNAVAILABLE": ("이 계정의 Copilot 은 {target}을 조회할 수 없습니다",
                              "서로 다른 날 {confirmDays}번 같은 답을 받아 확정했습니다. {ttlDays}일 뒤 자동으로 다시 확인합니다. "
                              "로컬 색인·웹 수집 결과는 그대로 씁니다.",
                              "능력 기록, 조회 생략"),
    "BR-LOOKUP-SUSPECT": ("Copilot 조회가 거절되었습니다",
                          "오늘 {source} 조회가 거절되었습니다. 다른 날 다시 확인한 뒤에만 '조회 불가'로 판단합니다.",
                          "다음 실행에서 재확인"),
    "BR-CALIB": ("Copilot 입력·답 한도를 측정했습니다", "입력 {in}자 · 답 {out}자. 이 값으로 묶음 크기를 정합니다.", "저장"),
    "BR-PROBE-BUSY": ("생성 중 표시를 찾지 못했습니다",
                      "Copilot 화면의 '중지' 버튼을 인식하지 못해 답 완료를 조금 늦게 판정합니다(결과에는 영향 없음).",
                      "설정 라벨 갱신 권고"),
    "BR-NOLIC": ("이 계정의 Copilot 은 메일·Teams 를 조회할 수 없습니다",
                 "계정 등급상 사서함·Teams 를 근거로 쓸 수 없습니다. 메일·Teams 조회는 건너뛰고, 분석은 정리된 글을 붙여 "
                 "보내는 방식으로 계속합니다. 로컬 색인·웹 수집 결과는 그대로 씁니다.",
                 "조회 단계 생략(능력 기록), 엄격 규칙"),
    "BR-WEB-STRICT": ("웹 검색이 켜질 수 있어 더 가려서 보냅니다",
                      "업무 모드와 웹 검색 꺼짐을 둘 다 확인하지 못했습니다. 고객사·협력사 번호를 지워 보내고, 금액과 고객사가 "
                      "함께 나오는 {n}건은 보내지 않고 규칙 분류로 표시했습니다.",
                      "엄격 규칙(§9.7), 다음 호출에서 재판별"),
    "BR-WEB-BLOCK": ("웹 검색이 켜질 수 있어 AI 분석을 보내지 않았습니다",
                     "설정(웹 노출 시 전송 안 함)에 따라 이번 분석은 규칙 분류로만 표시했습니다. 업무 모드와 웹 검색 꺼짐이 "
                     "확인되면 다음 분석에서 남은 것부터 자동으로 이어 합니다.",
                     "전 단계 skipped(web_exposed)"),
    "BR-WEB-MODE": ("업무(Work) 모드로 바꾸지 못했습니다",
                    "Copilot 화면이 웹 모드에 머물러 있어 이번에는 메일·Teams 조회를 건너뜁니다. 다음 분석 때 다시 시도합니다.",
                    "조회 skipped(mode_web)"),
}

# ── L1 단계(phase) — B §5.8 ─────────────────────────────────────────────────
CONTENT_PHASES = ("replied", "no_reply", "empty_reply", "stub")
SEND_PHASES = ("input_overflow", "inject_mismatch", "busy_before_send", "send_failed", "cdp_error")
SESSION_PHASES = ("login_required", "dead_session", "input_not_found", "wrong_tab", "tab_lost")
LAUNCH_PHASES = ("edge_not_found", "launch_failed", "policy_blocked", "port_exhausted", "profile_busy", "lock_busy")
MANUAL_PHASES = ("manual_pending",)
ALL_PHASES = CONTENT_PHASES + SEND_PHASES + SESSION_PHASES + LAUNCH_PHASES + MANUAL_PHASES
FATAL_PHASES = frozenset(SESSION_PHASES + LAUNCH_PHASES)       # L2 transport_fatal(B §6.6 순서 1)
MANUAL_SWITCH_PHASES = frozenset({"edge_not_found", "policy_blocked"})   # autoManualFallback 대상(B §3.1)

PHASE_BR = {
    "login_required": "BR-LOGIN",
    "edge_not_found": "BR-EDGE",
    "policy_blocked": "BR-POLICY",
    "input_not_found": "BR-INPUT",
    "tab_lost": "BR-TAB",
    "wrong_tab": "BR-TAB",
    "dead_session": "BR-DEAD-PROFILE",
    "launch_failed": "BR-LAUNCH",
    "port_exhausted": "BR-LAUNCH",
    "profile_busy": "BR-PROFILE-BUSY",
    "lock_busy": "BR-LOCK-BUSY",
    "busy_before_send": "BR-SERVICE",
    "send_failed": "BR-SERVICE",
    "cdp_error": "BR-SERVICE",
    "no_reply": "BR-SLOW",
    "empty_reply": "BR-SERVICE",
}


class _Blank(dict):
    def __missing__(self, key):
        return "-"


_FMT = string.Formatter()


def _fill(s: str, kw: dict) -> str:
    try:
        return _FMT.vformat(s, (), _Blank(kw))
    except (ValueError, IndexError, KeyError):
        return s


def render(code: str, **kw) -> dict:
    """문구 1건 → ``{code, title, body, action, text_ko}``. 빠진 자리 값은 '-'. 모르는 코드는 KeyError.
    자리 값에는 숫자·코드·단계 이름만 넘긴다(원문·이름·경로 금지 — 호출자 책임)."""
    title, body, action = BR[code]
    t, b = _fill(title, kw), _fill(body, kw)
    return {"code": code, "title": t, "body": b, "action": _fill(action, kw), "text_ko": f"{t} — {b}"}


def explain_phase(phase: str) -> tuple[str, bool]:
    """L1 단계 → (BR 코드 또는 '', 치명 여부). 치명 = 같은 세션으로 남은 묶음을 보내도 같은 결과(L2 transport_fatal)."""
    return PHASE_BR.get(phase, ""), phase in FATAL_PHASES


class Notices:
    """한 실행 안에서 같은 코드를 한 번만 띄운다(B §13 원칙 ④). ``emit`` 은 ``lm27.util.events.emit`` 형
    호출 가능 객체(None = 이벤트를 내지 않고 기록만). 띄운 기록은 ``shown``(코드 목록, 순서대로)."""

    def __init__(self, emit=None):
        self._emit = emit
        self.shown: list[str] = []

    def notify(self, code: str, **kw) -> bool:
        if code in self.shown:
            return False
        rec = render(code, **kw)
        self.shown.append(code)
        if self._emit is not None:
            self._emit("notice", code=code, title=rec["title"], body=rec["body"], text_ko=rec["text_ko"])
        return True

    def seen(self, code: str) -> bool:
        return code in self.shown


def default_notices() -> Notices:
    """표준 출력 이벤트(``lm27.util.events.emit``)로 내는 Notices."""
    from lm27.util import events
    return Notices(events.emit)
