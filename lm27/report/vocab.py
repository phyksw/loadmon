# -*- coding: utf-8 -*-
r"""보고서 화면 어휘 단일원(R §2.2 `vocab.py` · §3.4 · §3.5 · §4.4.3 · §4.6 · §4.7 · §4.8 · §4.9 · §5.8 · §8.4, 계약 §6.1 · §6.6).

- 사유 코드 → 화면 문구 `REASON_UI`(R §5.8 — 짧은 이름 + 사용자 행동/프로그램 행동 문장). 사유 코드의 **뜻**은 계약 §6.1·
  C §4.2 소유이고, 화면 문구는 이 표가 소유한다. §5.8 표에 없는 §6.1 코드도 같은 문체로 적었다. 모르는 코드는
  '기타' + 코드 그대로 + "다음 수집에서 다시 확인합니다"(R §5.8 마지막 행).
- 리드타임 초과 원인 코드 `CAUSES`(R §4.4.3) · 측정 품질 사유 `QUALITY_TEXT`(R §4.9) · 축 이름 `AXIS_NAMES` ·
  분석 경고 `WARN_TEXT` · 차트 이름 `CHARTS`(R §8.4 — 부록 A CHARTS 이름 정본, X-281) · 라벨 출처 꼬리표 `LABEL_BY`(R §3.5).
- 닫힌 어휘: 온톨로지 노드·관계(`ONTO_NODES`·`ONTO_RELS` — 결정 §10.5 · 계약 §6.6) · 추천 종류(`REC_KINDS`, R §4.6.3) ·
  빈도 등급(`FREQ`, R §4.7.2) · agentic 등급(`AGENT_GRADES`) · 서브에이전트 판정(`VERDICTS`)·why(`SUB_WHY`) ·
  규칙 매칭 이유(`RULE_WHY`) · 리뷰 사실 상태(`FACT_STATUS`) · 확장자군 이름(`EXT_CLASS_NAMES`).
- 업무 영역의 이름·색·순서는 `lm27.hier.vocab.DOMAIN_META` 를 접근 함수(`domain_name`·`domain_color`·`domain_order`)로만
  읽는다(L-25 — 이 파일에 영역 이름·색을 적지 않는다). 분야·기능·유형·단계 유형의 이름은 유효 레지스트리 어휘
  (H §2.3.4)에서 **코드로** 찾고, 없으면 내장 어휘(`lm27.hier.vocab` · `lm27.vocab.steps`)를 쓴다.

화면 문구 규칙(R §5.0.4 · RPT-40): '무엇이 됐고 → 무엇이 남았고 → 프로그램이 스스로 무엇을 하는지'. 다른 사람에게 수동 조작을
요구하거나 재설치를 권하는 문구를 쓰지 않는다. 시간·MM 을 '대신할 수 있는 양'으로 바꾸는 표현을 쓰지 않는다(RP4).

표준 라이브러리 + `lm27.hier.vocab`·`lm27.vocab.steps`(접근 함수)만 쓴다. 파일을 쓰지 않는다.
"""
from __future__ import annotations

from collections.abc import Mapping

from lm27.hier import vocab as _hv
from lm27.vocab import steps as _steps

__all__ = [
    "AGENT_GRADES",
    "AXIS_NAMES",
    "CAUSES",
    "CHARTS",
    "CYCLE_MARKS",
    "EXT_CLASS_NAMES",
    "FACT_STATUS",
    "FREQ",
    "GRADE_NAMES",
    "LABEL_BY",
    "ONTO_NODES",
    "ONTO_RELS",
    "ONTO_RELS_INFERRED",
    "QUALITY_GRADES",
    "QUALITY_PERIOD_TEXT",
    "QUALITY_TEXT",
    "REASON_UI",
    "REC_KINDS",
    "RULE_WHY",
    "SUB_WHY",
    "VERDICTS",
    "WARN_TEXT",
    "cause_name",
    "domain_color",
    "domain_name",
    "domain_order",
    "domains",
    "field_name",
    "func_name",
    "reason_short",
    "reason_text",
    "step_name",
    "vocab_name",
    "warn",
    "wtype_name",
]

# ───────────────────────────── 사유 코드 → 화면 문구(R §5.8) ─────────────────────────────
_OTHER_TAIL = "다음 수집에서 다시 확인합니다"
_IDX_TEXT = "Windows 검색 색인을 쓸 수 없습니다. 다른 경로로 채웁니다"
_COPILOT_LOOKUP = "이 계정의 Copilot 은 메일·팀즈를 조회할 수 없습니다. 조회는 건너뛰고 분석은 계속합니다"

REASON_UI: dict[str, tuple[str, str]] = {
    "R-NEWOL": ("새 Outlook 전용",
                "이 PC 에는 새 Outlook 만 있고 클래식 Outlook 이 없어 앱으로 메일을 읽을 수 없습니다. 이 PC 의 Outlook 웹 경로가 채웁니다"),
    "R-NOPROF": ("Outlook 계정 미설정", "Outlook 에 메일 계정이 설정돼 있지 않아 앱 경로를 건너뜁니다. Outlook 웹 경로가 채웁니다"),
    "R-WIZARD": ("Outlook 시작 마법사 위험",
                 "Outlook 을 자동으로 띄우면 시작 마법사에서 멈출 수 있어 앱 경로를 건너뜁니다. 색인·Outlook 웹 경로가 "
                 "채웁니다"),
    "R-DIALOG": ("Outlook 대화상자", "Outlook 에 열린 대화상자가 있어 읽지 못했습니다. 닫아 두면 다음 수집에서 다시 시도합니다"),
    "R-CLM": ("실행 제한", "이 PC 의 보안 설정이 스크립트 일부를 막습니다. 되는 경로만 씁니다"),
    "R-APPLOCKER": ("실행 차단", "회사 보안 정책이 이 PC 에서 일부 프로그램 실행을 막습니다. 되는 경로만 씁니다"),
    "R-OMG": ("주소 읽기 보호", "발신자·수신자 주소는 이 PC 에서 읽지 않습니다(보호 경고 방지). 제목·시각은 읽습니다"),
    "R-ELEV": ("권한 불일치", "관리자 권한으로 실행된 창과 Outlook 이 달라 붙지 못했습니다. 일반 권한으로 다시 실행하세요"),
    "R-ONLINE": ("온라인 모드", "Outlook 이 온라인 모드라 이 PC 색인에 메일이 없습니다. 웹 경로가 채웁니다"),
    "R-HORIZON": ("동기화 기간 밖", "이 날짜는 이 PC 의 Outlook 보관 기간 밖입니다. 웹 경로가 채웁니다"),
    "R-SUBFOLDER": ("하위 폴더 많음", "정리 규칙 폴더의 메일이 많습니다 — 모든 폴더를 읽고 색인으로 건수를 맞춰 봅니다"),
    "R-STALE": ("오래된 사본", "이 PC 의 Outlook 사본이 최근 것이 아닙니다"),
    "R-NOIDX": ("색인 꺼짐", _IDX_TEXT),
    "R-IDXPOLICY": ("색인 막힘", _IDX_TEXT),
    "R-IDXPAUSED": ("색인 일시정지", _IDX_TEXT),
    "R-EDGEPOL": ("Edge 자동화 막힘",
                  "회사 정책이 Edge 자동 연결을 막습니다. 웹 수집은 건너뛰고, Copilot 은 직접 붙여넣기로 바꿉니다"),
    "R-LOGIN": ("로그인 필요", "분석용 Edge 창에서 회사 계정으로 한 번 로그인해 주세요. 로그인하면 이어서 합니다"),
    "R-CA": ("접근 정책 차단", "회사 접근 정책이 이 PC 의 웹 접속을 막습니다"),
    "R-NOLIC": ("Copilot 조회 불가", _COPILOT_LOOKUP),
    "R-NOCONN": ("Copilot 조회 불가", _COPILOT_LOOKUP),
    "R-TZ": ("시간대 주의", "이 PC 의 시간대가 다릅니다(클라우드PC UTC 등). 시각은 근무 시간대로 바꿔 계산합니다"),
    "R-OFFICE": ("지원 종료 Office", "오래된 Office 라 일부 경로가 불안정할 수 있습니다"),
    "R-UIAEMPTY": ("팀즈 창 숨김", "팀즈 창이 최소화·숨김이라 읽지 못했습니다. 팀즈 웹 경로가 채웁니다"),
    "R-UIAELEV": ("팀즈 창 권한", "관리자 권한 창은 읽을 수 없습니다"),
    "R-NOADDR": ("내 주소 미확인", "내 메일 주소를 확인하지 못해 받는 메일의 직접/참조 구분이 '모름' 입니다"),
    "R-NOEVT": ("이벤트 로그 권한", "이 PC 의 일부 이벤트 기록을 읽을 권한이 없습니다"),
    "R-RECURINC": ("반복 일정 일부만", "반복 일정을 일부만 펼쳐 읽었습니다. 읽은 만큼 쓰고 다음 수집에서 다시 확인합니다"),
    "R-NOAPP": ("프로그램 없음", "이 PC 에는 이 경로의 대상 프로그램이 없습니다. 다른 경로로 채웁니다"),
    "R-CAP": ("상한 도달", "한 번에 읽을 수 있는 양을 넘어 일부만 읽었습니다. 다음 수집이 이어 읽습니다"),
    "R-BUDGET": ("시간 예산 소진", "정해진 시간 안에 끝내지 못했습니다. 다음 수집이 이어 합니다"),
    "R-TRANSPORT": ("일시 실패", "일시적인 연결·프로그램 오류입니다('불가' 판정에 쓰지 않음). 다음에 다시 시도합니다"),
    "R-COM-BUSY": ("Outlook 바쁨", "Outlook 이 바빠 응답하지 않았습니다. 다음 수집에서 다시 시도합니다"),
    "R-COMGAP": ("앱 경로 누락 의심",
                 "색인보다 Outlook 앱에서 읽은 건수가 적습니다. 하위 폴더·프로필을 다시 확인하고 색인 건수로 맞춰 봅니다"),
    "R-WEBSEL": ("웹 화면 인식 실패", "웹 화면의 구성을 알아보지 못했습니다. 화면 구성을 다시 익혀 다음 수집에서 다시 시도합니다"),
    "R-LISTVIRT": ("채팅 목록 일부만", "채팅 목록을 끝까지 넘기지 못해 일부만 읽었습니다. 다음 수집이 이어 읽습니다"),
    "R-ROOMGONE": ("대화방 일부만", "대화방 하나를 다시 찾지 못해 그 방만 일부 읽었습니다. 다음 수집에서 다시 시도합니다"),
    "R-NOGIT": ("git 없음", "git 이 없거나 저장소를 읽지 못했습니다. 코드 커밋 기록은 건너뜁니다"),
    "R-MRUEMPTY": ("최근 문서 없음", "Office 최근 문서 기록이 비어 있습니다. 파일 저장 기록으로 채웁니다"),
    "R-RECENTPOLICY": ("최근 문서 기록 꺼짐", "회사 정책이 최근 문서 기록을 남기지 않게 합니다. 파일 저장 기록으로 채웁니다"),
    "R-NOMACHGUID": ("PC 식별 대체", "이 PC 의 고유 번호를 읽지 못해 대체 식별자를 씁니다"),
    "R-STUCK": ("입력 기록 이상", "키보드·마우스 입력 기록이 멈춘 것처럼 보입니다. 그 구간은 낮은 신뢰로 계산합니다"),
    "R-SAMPLER-ZOMBIE": ("사용 기록기 멈춤", "PC 사용 기록기가 실행 중이지만 기록을 남기지 않습니다. 다음 수집에서 기록기를 다시 확인합니다"),
    "R-RULESMISMATCH": ("정제 규칙 판 다름", "이 PC 사용 기록기의 정제 규칙 판이 다릅니다. 자동으로 새 판으로 맞춥니다"),
    "R-NOKEY": ("기록 키 없음", "사용 기록기의 키가 없거나 손상되었습니다. 자동으로 다시 만듭니다"),
    # 번들 위치(TAB §1.5 탐침 표의 사유별 문장)
    "R-BUNDLE-NETWORK": ("번들 위치 — 네트워크 드라이브",
                         "프로그램 폴더가 네트워크 드라이브에 있어 잠금·파일 교체가 불안정할 수 있습니다. 수집은 계속합니다"),
    "R-BUNDLE-ONEDRIVE": ("번들 위치 — OneDrive",
                          "프로그램 폴더가 OneDrive 동기화 폴더 안에 있어 충돌 사본·잠금 위험이 있습니다. 수집은 계속합니다"),
    "R-BUNDLE-REDIRECT": ("번들 위치 — 리디렉션 폴더",
                          "프로그램 폴더가 서버로 리디렉션된 문서·바탕화면 폴더 안에 있습니다. 수집은 계속합니다"),
    "R-BUNDLE-READONLY": ("번들 쓰기 불가", "이 폴더에 쓸 수 없어 번들 쓰기를 하지 않았습니다. 쓰기 가능한 위치로 옮기면 이어서 합니다"),
    "R-BUNDLE-LOWSPACE": ("번들 위치 — 공간 부족", "프로그램 폴더 드라이브의 여유 공간이 500MB 보다 적습니다. 수집은 계속합니다"),
    "R-BUNDLE-LONGPATH": ("번들 위치 — 긴 경로", "프로그램 폴더 경로가 140자를 넘어 일부 파일 경로가 너무 길어질 수 있습니다"),
    # 팀 서버 도달(TAB §2.9 hello 판정 문장)
    "R-TEAM-TIMEOUT": ("팀 서버 응답 없음", "응답이 없습니다 — 다른 망(클라우드PC·재택)이거나 방화벽이 막고 있을 수 있습니다. 묶음은 그대로 대기합니다"),
    "R-TEAM-REFUSED": ("팀 서버 꺼짐", "그 주소의 PC 는 켜져 있으나 그 포트에 서버가 없습니다(팀 서버가 꺼졌거나 포트가 다름)"),
    "R-TEAM-DNS": ("팀 서버 이름 확인 실패", "팀 서버 주소의 이름을 찾지 못했습니다. 묶음은 그대로 대기합니다"),
    "R-TEAM-PROXY": ("프록시 응답", "팀 서버 대신 프록시가 응답했습니다. 묶음은 그대로 대기합니다"),
    "R-TEAM-LM24": ("이전 판 팀 서버",
                    "이 주소에는 LM27 이 아니라 이전 판(LM24) 팀 서버가 응답합니다. LM27 팀 서버의 포트를 확인해 설정에서 바꾸세요"),
    "R-TEAM-OTHERAPP": ("다른 프로그램 응답", "LM27 팀 서버가 아닌 프로그램이 응답합니다"),
    "R-TEAM-VERSION": ("팀 서버 판 다름", "팀 서버 판과 맞지 않습니다 — LM27 판을 맞추세요"),
}


def reason_text(code: str) -> tuple[str, str]:
    """사유 코드 → (짧은 이름, 화면 문장). 모르는 코드는 ('기타', '<코드> · 다음 수집에서 다시 확인합니다')."""
    v = REASON_UI.get(str(code))
    if v is not None:
        return v
    return "기타", f"{code} · {_OTHER_TAIL}"


def reason_short(code: str) -> str:
    """사유 코드 → 짧은 이름(CH-H01 `reasonText` 입력)."""
    return reason_text(code)[0]


# ───────────────────────────── 리드타임 초과 원인(R §4.4.3) ─────────────────────────────
CAUSES: dict[str, tuple[str, str]] = {
    "WAIT": ("대기", "작업 사이 대기가 길었습니다(가장 긴 대기: {before} → {after} {days}영업일)."),
    "REWORK": ("재작업", "같은 일이 {n}차례 다시 의뢰되었습니다."),
    "PARALLEL": ("병행", "다른 일과 함께 진행했습니다(평균 병행도 {x})."),
    "SCOPE": ("작업량", "투입이 평소의 {r}배였습니다({h}h, 평소 {h0}h)."),
    "LATE_START": ("착수 지연", "의뢰 뒤 {d}근무일 지나 작업을 시작했습니다."),
    "DATA": ("근거 부족", "경계가 추정이거나 그 기간 메일·팀즈 기록이 비어 있어 리드타임이 부정확할 수 있습니다."),
    "UNEXPLAINED": ("원인 미상", "기록으로 설명되지 않는 지연입니다(오프라인 대기·외부 요인일 수 있음)."),
    "NO_BASELINE": ("비교 기준 없음", "비교할 완료 업무가 부족합니다."),
}


def cause_name(code: str) -> str:
    return CAUSES.get(code, (code, ""))[0]


# ───────────────────────────── 측정 품질(R §4.9) ─────────────────────────────
AXIS_NAMES: dict[str, str] = {"mail_in": "메일 받음", "mail_out": "메일 보냄", "cal": "일정", "teams": "팀즈", "pc": "PC"}
QUALITY_GRADES = ("reliable", "caution", "unreliable", "")
GRADE_NAMES: dict[str, str] = {"reliable": "신뢰", "caution": "주의", "unreliable": "측정 불충분", "": "판단 안 함"}
QUALITY_TEXT: dict[str, str] = {
    "pc_cov_bad": "PC 기록이 있는 근무일이 {p}% 입니다 — 에이전트가 없던 PC·기간이 있습니다",
    "pc_cov_low": "PC 기록이 있는 근무일이 {p}% 입니다 — 에이전트가 없던 PC·기간이 있습니다",
    "comms_cov_bad": "메일 발신·팀즈 기록이 모두 절반 넘게 비었습니다 — 홈의 능력 표에서 막힌 출처를 확인하세요",
    "mail_cov_low": "{axis} 기록이 비어 있는 근무일이 있습니다({p}%)",
    "teams_cov_low": "{axis} 기록이 비어 있는 근무일이 있습니다({p}%)",
    "cal_cov_low": "{axis} 기록이 비어 있는 근무일이 있습니다({p}%)",
    "estimated_bad": "근무시간의 {p}% 가 낮은 신뢰(PC 하한·흔적 창 등)로 채워졌습니다",
    "estimated_high": "근무시간의 {p}% 가 낮은 신뢰(PC 하한·흔적 창 등)로 채워졌습니다",
    "unattributed_high": "근무시간의 {p}% 가 업무에 묶이지 않았습니다",
    "no_evidence_days": "근거가 하나도 없는 근무일이 {n}일 있습니다(확인 질문 Q09)",
    "sampler_absent": "PC 사용 기록기(샘플러)가 없는 날이 많습니다 — 시간이 낮은 신뢰로 계산됩니다",
    "no_envelope": "이 달은 근무시간이 계산되지 않았습니다",
    "mining_coarse": "단계 정밀도가 낮습니다 — 시간 결과에 단계 정보가 없습니다",
}
# 기간 전체 카드의 문구가 달 문구와 달라야 하는 사유(그런 달의 수 {n} — `quality.period_texts`)
QUALITY_PERIOD_TEXT: dict[str, str] = {
    "no_envelope": "근무시간이 계산되지 않은 달이 {n}개 있습니다 — 그 달은 기록이 없거나 수집 전입니다",
}

# ───────────────────────────── 분석 경고(모델 flags.warnings — {code, text_ko}) ─────────────────────────────
WARN_TEXT: dict[str, str] = {
    "mining_coarse": "단계 정밀도가 낮습니다 — 시간 결과에 단계 정보가 없습니다",
    "labels_missing": "분류 결과가 없어 모두 미분류로 보입니다",
    "peers_unverified": "동료 관계를 기록으로 다시 확인하지 못해 시간 결과의 관계를 그대로 씁니다",
    "registry_missing": "팀 레지스트리가 없어 과제 이름 대신 ID 를, 에이전트 목록 없이 보입니다",
    "catalog_empty": "에이전트 목록이 없습니다 — 팀 레지스트리를 받으면 채워집니다",
    # 로컬 카탈로그(config\agentic_tasks.json — V13) 경고. 모델은 lm27.hier.registry.LOCAL_CATALOG_WARNS 의 구체 문구를 싣는다
    "local_catalog": "로컬 Agentic 카탈로그(config\\agentic_tasks.json)를 그대로 쓰지 못했습니다",
    "fallback_unavailable": "규칙 라벨 단계를 불러오지 못해 단계 이름만 보입니다",
    "units_empty": "이 기간에 만들어진 단위업무가 없습니다",
    "calendar_mismatch": "달력 판이 다릅니다 — 다시 분석하면 맞춰집니다",
    "model_over_cap": "보고서 모델이 상세를 줄인 뒤에도 크기 상한을 넘습니다({mb}MB / 상한 {cap}MB) — 보고서는 그대로 "
                      "보이지만 화면·내보낸 파일이 무거울 수 있습니다. 분석 기간을 나눠 보면 작아집니다",
}


def warn(code: str, **kw) -> dict:
    """분석 경고 한 줄 {code, text_ko}(+ 숫자·키 보조 필드)."""
    out = {"code": code, "text_ko": WARN_TEXT.get(code, code)}
    out.update({k: v for k, v in kw.items() if v is not None})
    return out


# ───────────────────────────── 라벨 출처(R §3.5) · 닫힌 어휘 ─────────────────────────────
LABEL_BY: dict[str, str] = {"ai": "AI", "manual": "AI(붙여넣기)", "rule": "규칙", "rule_pending": "규칙", "user": "내 지정"}
FREQ: tuple[str, ...] = ("주 3회 이상", "주 1~2회", "월 몇 회", "드묾")
AGENT_GRADES: tuple[str, ...] = ("상", "중", "하")
VERDICTS: tuple[str, ...] = ("적합", "조건부", "부적합")
SUB_WHY: dict[str, str] = {
    "digital_io": "입출력 디지털", "repeat_weekly": "주 1회 이상 반복", "repeat_monthly": "월 1회 이상 반복",
    "structured_input": "정형 입력", "low_accountability": "책임 낮음", "verifiable": "검증 가능",
    "tool_access": "도구 접근 가능",
}
RULE_WHY: dict[str, str] = {"type": "단계 유형 일치", "input": "입력 일치", "output": "출력 일치", "keyword": "핵심어 일치"}
FACT_STATUS: tuple[str, ...] = ("완료", "시작", "진행", "보류")
CYCLE_MARKS: dict[str, str] = {"re_request": "재의뢰", "quiet_add": "조용한 뒤 추가 요청"}
EXT_CLASS_NAMES: dict[str, str] = {"doc": "문서", "ppt": "발표 자료", "xls": "표 계산 문서", "pdf": "PDF 문서",
                                   "txt": "텍스트 문서", "cad": "설계 도면", "code": "코드"}

# 온톨로지(R §4.6.1 · 결정 §10.5 · 계약 §6.6) — 노드 종류 → (이름, 무리). 무리 코드는 렌더러(lm27charts.js GROUP_OF)와 같다:
# work 업무 · artifact 산출·도구 · person 사람
ONTO_NODES: dict[str, tuple[str, str]] = {"P": ("과제", "work"), "R": ("역할 업무", "work"), "U": ("단위업무", "work"),
                                          "D": ("문서", "artifact"), "A": ("앱", "artifact"), "C": ("동료", "person")}
ONTO_RELS: tuple[str, ...] = ("소속", "의뢰함", "보고함", "산출함", "사용함", "함께함", "선행함", "같은문서", "같은과제")
ONTO_RELS_INFERRED: frozenset[str] = frozenset({"선행함", "같은문서"})
REC_KINDS: dict[str, tuple[str, str]] = {
    "same": ("같은 일 의심", "같은 일이 둘로 나뉘었을 수 있습니다"),
    "chain": ("이어진 일", "앞뒤로 이어진 일입니다(인계)"),
    "ref": ("참고할 일", "다른 과제에서 같은 문서를 썼습니다"),
    "related": ("관련 일", "같은 사람·도구를 공유합니다"),
}

# 차트 이름(R §8.4 · 부록 A CHARTS — X-281: HTML 표 컴포넌트 CH-H02·P14·P15·T07·T09 는 CHARTS 밖이지만 이름은 여기)
CHARTS: dict[str, str] = {
    "CH-H01": "수집 커버리지 히트맵", "CH-H02": "PC × 출처 능력 표", "CH-P02": "월별 투입", "CH-P03": "일별 근무",
    "CH-P04": "업무 영역 구성", "CH-P06": "개인 간트", "CH-P07": "프로세스 맵", "CH-P08": "단위업무 타임라인",
    "CH-P09": "과제 역할 레인", "CH-P10": "단계 묶음 구성", "CH-P11": "리드타임 점 그림", "CH-P12": "동료 막대",
    "CH-P13": "연관 그래프", "CH-P14": "Agentic 매칭 격자", "CH-P15": "서브에이전트 점수 표", "CH-P16": "하루 24시간 띠",
    "CH-P17": "단위업무 등급 분포", "CH-T02": "월별 업무 영역 투입", "CH-T06": "리드타임 점 그림(팀)",
    "CH-T07": "Agentic 매칭 격자(팀)", "CH-T08": "팀 간트", "CH-T09": "측정 품질 행렬",
}


# ───────────────────────────── 업무 영역(DOMAIN_META 접근 함수로만 — L-25) ─────────────────────────────
def domain_name(code) -> str:
    return _hv.domain_name(code)


def domain_color(code) -> str:
    return _hv.domain_color(code)


def domain_order(code) -> int:
    return _hv.domain_order(code)


def domains() -> list[dict]:
    """모델 `domains[]`(R §9.2.1): 고정 순서(DEV·MP·EXT·COM·AX·UNC)의 {code, name, color, order}."""
    return [{"code": c, "name": _hv.domain_name(c), "color": _hv.domain_color(c), "order": _hv.domain_order(c)}
            for c in _hv.DOMAIN_ORDER]


# ───────────────────────────── 어휘 이름(유효 레지스트리 → 내장) ─────────────────────────────
def _reg_item(registry, kind: str, code: str):
    """유효 레지스트리(`EffectiveRegistry.vocab[kind][code]`) 또는 원본 dict(`vocab.<kind>` 객체 목록)의 항목."""
    if registry is None:
        return None
    if isinstance(registry, Mapping):
        vocab = registry.get("vocab")
        items = vocab.get(kind) if isinstance(vocab, Mapping) else None
        if isinstance(items, list):
            for it in items:
                if isinstance(it, Mapping) and it.get("code") == code:
                    return it
        return None
    vocab = getattr(registry, "vocab", None)
    table = vocab.get(kind) if isinstance(vocab, Mapping) else None
    return table.get(code) if isinstance(table, Mapping) else None


def vocab_name(kind: str, code, registry=None) -> str:
    """어휘 코드 → 표시 이름(kind = fields·functions·activity_types·step_types). 모르는 코드는 코드 그대로."""
    c = str(code or "")
    it = _reg_item(registry, kind, c)
    if it is not None:
        nm = it.get("name") if isinstance(it, Mapping) else getattr(it, "name", None)
        if isinstance(nm, str) and nm.strip():
            return nm.strip()
    if kind == "step_types":
        st = _steps.STEP_TYPES.get(c)
        if st is not None:
            return st.name
    b = _hv.builtin_item(kind, c) if kind in _hv.BUILTIN_VOCAB else None
    return b.name if b is not None else c


def field_name(code, registry=None) -> str:
    return vocab_name("fields", code, registry)


def func_name(code, registry=None) -> str:
    return vocab_name("functions", code, registry)


def wtype_name(code, registry=None) -> str:
    return vocab_name("activity_types", code, registry)


def step_name(code, registry=None) -> str:
    """단계 유형 코드 → 한글명(레지스트리 `vocab.step_types` 의 이름이 있으면 그것)."""
    return vocab_name("step_types", code, registry)
