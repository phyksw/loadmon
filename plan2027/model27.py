# -*- coding: utf-8 -*-
"""AX 3대 과제(AL-1·VV-1·VV-3) 2027 리소스 모델 — 작업 패키지(WP) → 역할별 공수 → 월별 FTE → 공급 대비 차이 → 조달.
모든 합계는 이 데이터 한 벌에서 나온다. 출력: model27.json (HTML 이 그대로 읽음)."""
import argparse
import io
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = r"D:\AX프로젝트_준비"
M = list(range(1, 13))  # 2027-01 … 2027-12

ap = argparse.ArgumentParser()
ap.add_argument("--method", default=os.path.join(HERE, "method.json"))
ap.add_argument("--option", default=None, help="A = 1안 투트랙, B = 2안 로컬 단일, C = 혼합안 (기본: method.json pick)")
ap.add_argument("--vibe", default="base", choices=["hi", "base", "lo"], help="바이브 코딩·MCP 효과 — hi 보수 / base 기준 / lo 낙관")
ap.add_argument("--sourcing", default=None, help="조달 계획 JSON — 목록, 또는 {sourcing: [...], shift: {WP: 개월}} (설계안 비교용)")
ap.add_argument("--out", default=os.path.join(HERE, "model27.json"))
ap.add_argument("--quiet", action="store_true")
ARGS = ap.parse_args()
METHOD = json.load(io.open(ARGS.method, encoding="utf-8"))
OPT = ARGS.option or METHOD["pick"]
OPTD = METHOD["options"][OPT]
VL = ARGS.vibe

# ---------------------------------------------------------------- 역할
ROLES = [
    # id, 이름, 묶음, 하는 일, 필요 역량, 경력·급, 현재 공급원
    ("AX", "AX 추진 (A·B)", "AX 추진",
     "3과제 일정·범위·의존 관리, Agent 구조(카드·MCP·게이트) 결정, 데이터 등급·승인 거버넌스, 투자심의·예산·조달·채용, 유관팀 조율, 골든셋·평가 스크립트, Agent 등록·실행 기록, 성과 측정(L/T·채택률·대체 MM)",
     ["과제 관리·Rolling Wave 운영", "Agent 아키텍처(Skill·MCP·A2A) 판단", "정보보안·데이터 등급 협의", "투자심의 기안·비용 산정", "평가셋 설계·자동 채점(Python)", "유관팀 5곳 이상 조율"],
     "사람 구분 없이 A·B 가 나눠 맡음", "기존 2명"),
    ("AI", "AI·LLM Agent 엔지니어", "개발",
     "Agent 본체 개발 — LLM 툴 호출·MCP 연결, RAG(설계지식), 입력 해석·조건 추출·보고서 생성, 오케스트레이터(lead)·야간 배치 로직, 품질 평가",
     ["LLM 애플리케이션(툴 호출·MCP 서버/클라이언트)", "RAG — 임베딩·리랭크·검색 평가", "평가셋 기반 품질 관리·회귀 테스트", "Python 서비스 개발(FastAPI·큐)", "온프렘 모델 특성 이해(오픈 웨이트)"],
     "선임·책임급 · 3~7년", "없음 (신규)"),
    ("CAE", "CAE 자동화 엔지니어", "개발",
     "Ansys 해석 자동화 스크립트 — 도메인별 셋업·메쉬·솔버·후처리 자동화, 배치(무인) 실행·라이선스 풀, 해석 결과 검증",
     ["PyAEDT·PyMechanical·PyFluent·ACT 스크립팅", "HFSS·Maxwell·SIwave·Mechanical·Icepak 해석 이해", "HPC 배치·작업 스케줄러·라이선스 관리", "결과 후처리·리포트 자동화"],
     "선임·책임급 · 3~8년", "DRI 팀 툴 개발자 일부"),
    ("ML", "ML 엔지니어", "개발",
     "VV-1 합성데이터 인지모델 학습·검증(Sim2Real), VV-3 수율 선예측 PoC — 학습 파이프라인·평가 지표",
     ["3D 포인트클라우드 인지(PointPillars·CenterPoint 류)", "합성→실측 도메인 적응", "PyTorch 학습·분산 학습·평가", "표 데이터 예측 모델(수율) 경험 우대"],
     "선임·책임급 · 3~7년", "없음 (신규)"),
    ("SIM", "LiDAR 시뮬레이션 엔지니어", "개발",
     "LiDAR 센서 물리 모델(ToF·FMCW 빔·노이즈·반사율), 시뮬레이터·연산엔진 연동, ODD 시나리오 설계·확충, 커버리지 측정",
     ["LiDAR 물리 모델링", "시뮬레이터(자체 엔진·상용) 연동 API", "OpenSCENARIO·ODD 분류 체계", "C++·Python"],
     "선임·책임급 · 3~8년", "VV-1 플랫폼 개발자 일부"),
    ("DATA", "데이터 엔지니어", "개발",
     "PLM/PDM 데이터 추출·MCP(읽기), 도면·BOM 파싱, 설계지식 문서 수집·정제, 합성데이터·GT 파이프라인, 벡터DB",
     ["PLM/PDM API·export 연동", "도면(2D/3D)·BOM 파싱", "ETL·데이터 품질·카탈로그", "벡터DB·대용량 데이터셋 관리"],
     "선임급 · 3~6년", "없음 (신규)"),
    ("OPS", "MLOps·인프라 엔지니어", "개발",
     "온프렘 GPU 서버·LLM 서빙(vLLM)·게이트웨이·등급 라우팅·감사 로그, 학습 환경(K8s·Slurm), 모니터링·보안 하드닝·백업",
     ["온프렘 GPU 서버·쿠버네티스", "LLM 서빙(vLLM·TensorRT-LLM)", "모니터링·로그·보안 하드닝·망분리", "HPC 스케줄러(Slurm)"],
     "선임·책임급 · 4~8년", "없음 (신규) · 전사 지원 조직 공용 여부 확인"),
    ("MBSE", "MBSE 엔지니어", "개발",
     "RVTM 추적체계(요구→시스템 모델→검증) 정의, SysML/Capella 모델·툴 도입, 변경 영향 추적 규칙",
     ["SysML v2·Capella·Cameo", "요구사항 추적(RVTM)·변경 영향 분석", "ISO 26262·ASPICE 이해", "LiDAR 시스템 아키텍처"],
     "책임급 · 5년↑", "없음 (신규·외부 전문가)"),
    ("DOM_ANA", "해석 도메인 전문가", "도메인(DRI 팀)",
     "골든셋 제공·판정, 파일럿 사용자, 야간 결과 아침 판정", ["EM·구조·열 해석 실무"], "현업", "AL-1, VV-3 DRI 팀"),
    ("DOM_CIR", "회로 도메인 전문가", "도메인(DRI 팀)",
     "SI/PI·EMC 판정 기준·골든셋, 선검증 결과 판정", ["SI/PI·EMC 설계·해석"], "현업", "현업 회로 엔지니어"),
    ("DOM_MEC", "기구 도메인 전문가", "도메인(DRI 팀)",
     "구조·열·공차 판정, 파일럿 사용자, 수율 선예측 데이터", ["기구 구조·열·공차"], "현업", "현업 기구 엔지니어"),
    ("DOM_OPT", "광학 도메인 전문가", "도메인(DRI 팀)",
     "센서 광학 파라미터, 재설계안 판정", ["광학 설계(Zemax)"], "현업", "현업 광학 엔지니어"),
    ("DOM_SYS", "시스템 도메인 전문가", "도메인(DRI 팀)",
     "센서·신호 파라미터, ODD·Sim2Real 판정, RVTM 요구 정의", ["LiDAR 시스템·신호처리·인지"], "현업", "현업 시스템 엔지니어 (VV-1 DRI 팀)"),
]
ROLE_IDS = [r[0] for r in ROLES]
DEV = ["AI", "CAE", "ML", "SIM", "DATA", "OPS", "MBSE"]
DOM = ["DOM_ANA", "DOM_CIR", "DOM_MEC", "DOM_OPT", "DOM_SYS"]

# ---------------------------------------------------------------- 선행 조건 (필요 월은 WP 가 정한다, 확보 예상 월은 지금 알려진 근거)
DEPS = {
    "PLM":      dict(name="PLM API 읽기 계정 (cad·bom·rev)", owner="IT·사내시스템", ref="D-AL1-04 · D-VV3-00", eta=0, eta_note="원장 추정 '26.11 — 신청 패키지 제출 여부 확인"),
    "SEC":      dict(name="설계 데이터 LLM 입력 허용 범위·온프렘 조건 승인", owner="정보보안", ref="D-AL1-01 · D-VV3-01", eta=0, eta_note="원장 추정 '26.11"),
    "ONPREM":   dict(name="온프렘 LLM 추론 (제한 등급 C3 처리)", owner="AX 추진 → 투자심의", ref="인프라 INF-1", eta=7, bridge_eta=2, eta_note="자체 투자 시 '27.7 가동 (기안 '26.11 → 심의 3개월 → 납품·설치)", bridge="브리지: 전사 지원 조직 공용 GPU·로컬 LLM 또는 빅플랜 GPU(RTX PRO 6000 9대) 선배정 — '26.11.15 결정"),
    "GPU_TRAIN":dict(name="인지모델 학습·합성데이터 GPU", owner="전사 지원 조직 / 투자심의", ref="D-VV1-02 · INF-2", eta=4, eta_note="원장 추정 '27.3.31 전사 지원 조직 배정", bridge="미배정 시 자체 투자 '27.7 → VV-1 Q2 학습이 Q3 로 밀림"),
    "STORAGE":  dict(name="데이터셋 스토리지 (합성데이터·GT)", owner="IT·사내시스템", ref="INF-3", eta=3, eta_note="기존 NAS 증설 — IT 일반 구매 '26.12 발주 → '27.2 증설 가정 (투자심의 묶음 밖)"),
    "LIC_MECH": dict(name="Ansys Mechanical 배치(무인) 라이선스", owner="IT·사내시스템(라이선스)", ref="D-AL1-00", eta=1, eta_note="원장 추정 '26.11"),
    "LIC_HFSS": dict(name="HFSS·SIwave·Maxwell 배치 라이선스", owner="IT·사내시스템(라이선스)", ref="D-VV3-04", eta=2, eta_note="원장 추정 '27.1.29"),
    "LIC_THERM":dict(name="Icepak·Fluent 배치 라이선스", owner="IT·사내시스템(라이선스)", ref="신규", eta=5, eta_note="'27 상반기 신청 가정"),
    "HPC_NIGHT":dict(name="야간 HPC 슬롯·라이선스 풀", owner="IT·사내시스템", ref="신규", eta=7, eta_note="'27.6 협의 가정"),
    "SIM_LIC":  dict(name="외부 시나리오 시뮬레이터 API·라이선스", owner="IT·정보보안·CTO", ref="D-VV1-01", eta=3, eta_note="원장 추정 '27.2.26 검토 → 계약 '27.3"),
    "MBSE_TOOL":dict(name="MBSE 툴 (Capella 무료 / Cameo 유료)", owner="AX 추진·DRI", ref="신규", eta=2, eta_note="Capella 로 시작하면 즉시"),
    "VIBE_SEC": dict(name="바이브 코딩 도구 사용 승인 (사내 코드 반출 범위·C3 금지)", owner="정보보안 · 그룹 IT(LG CNS–Anthropic 그룹 계약)", ref="신규", eta=OPTD["vibe_start"][VL],
                     eta_note="'26.11 신청 → 기준 3개월('27.2) · 보수 6 · 낙관 2 (R2). 2안은 로컬 코딩 모델이 브리지 GPU 에 올라가는 시점"),
}

# ---------------------------------------------------------------- 작업 패키지 (2027)
# s,e = 시작·끝 월(포함). eff = {역할: MM}. ms = 원장 마일스톤 ref. ag = 로스터 Agent key. deps = [(dep, 필요 월)]
WP = []
def wp(id, task, name, s, e, eff, out, basis, ms=(), ag=(), deps=(), lever=None, after=(), ss=False, prof=None, op=False, novibe=False, opt=None, was=None, ops_from=None):
    # novibe = 회의·승인·예산처럼 코딩 도구로 줄지 않는 일, opt = 그 운영안에서만 생기는 일
    if opt and opt != OPT:
        return
    # prof = 월별 FTE 12개 + eff = 역할 비중 → 운영처럼 달마다 늘어나는 공수. 없으면 기간에 고르게 배분
    share = None
    if prof:
        on = [i + 1 for i, v in enumerate(prof) if v > 0]
        s, e = on[0], on[-1]
        share = eff
        eff = {r: sum(prof) * k for r, k in share.items()}
    elif ops_from:  # (작업 WP, 개수, 이름) — 그 작업이 끝난 다음 달부터 운영 (남은 작업만)
        share, eff = eff, {}
    WP.append(dict(id=id, task=task, name=name, s=s, e=e, eff=eff, out=out, basis=basis, ms=list(ms), ag=list(ag),
                   deps=[dict(dep=d, need=n) for d, n in deps], lever=lever, after=list(after), ss=ss,
                   prof=[round(v, 3) for v in prof] if prof else None, share=share, op=op, novibe=novibe, opt=opt,
                   was=list(was) if was else None, ops_from=ops_from))

# 릴리즈된 Agent·플러그인 운영 — 릴리즈 다음 달부터 1개당 월 0.1 FTE (공용 플랫폼·Registry 위라 단독 운영 0.2~0.25 의 절반)
OPS_RATE = 0.1
def live(*items):  # (운영 시작 월, 개수) …
    p = [0.0] * 12
    for m0, n in items:
        for m in range(m0, 13):
            p[m - 1] += OPS_RATE * n
    return p

# ── AL-1 자율 설계·해석 (해석 자동화 플랫폼 · 3과제 공용 해석 창구)
wp("A1", "AL-1", "EM 해석 자동화 운영·개선", 1, 12, dict(AI=1.2, CAE=0.6, DOM_ANA=0.6, AX=0.4),
   "'26.10 릴리즈본 운영 · 결함 수정 · 사용자 대응 · 월 L/T 실측",
   "운영 중 Agent 1개 = 0.2~0.25 FTE (모니터링·사용자 대응·툴 업데이트)", ag=["al1-lead", "al1-sim-runner"], op=True)
wp("A2", "AL-1", "설계지식DB(RAG) 구축", 3, 6, dict(DATA=2.5, AI=1.5, DOM_ANA=0.8, AX=0.7),
   "설계지식 검색(sh-design-kb) v1 — 보고서·규격·과거 해석 결과 색인, 검색 평가셋",
   "문서 수집·정제 2~3 MM + 검색 파이프라인·평가 1.5 MM + 도메인 검수 0.8 MM · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음(착수 마일스톤은 A3 가 1월에 충족)", ms=["M-AL1-06"], ag=["sh-design-kb"],
   deps=[("PLM", 3), ("SEC", 3), ("ONPREM", 3)], was=(1, 4))
wp("A3", "AL-1", "구조 해석 자동화 개발", 1, 4, dict(CAE=2.5, AI=1.8, DATA=0.4, DOM_ANA=1.0, DOM_MEC=0.6, AX=0.8),
   "구조 도메인 셋업·솔버·후처리 자동화 + 형상·물성 추출(al1-entity) + RAG 재학습",
   "도메인 1개 확장 표준 = CAE 2.5 + AI 1.8 + 도메인 1.6 + 평가 0.6 MM (EM 1차 구축 '26.3→'26.10 경험을 기존 프레임 재사용으로 축소)",
   ms=["M-AL1-06"], ag=["al1-entity"], deps=[("ONPREM", 2), ("LIC_MECH", 1), ("SEC", 1)])
wp("A4", "AL-1", "구조 해석 파일럿 적용", 5, 6, dict(DOM_MEC=0.8, DOM_ANA=0.4, AI=0.6, CAE=0.4, AX=0.4),
   "구조 파일럿 — 실제 과제 해석 의뢰 처리, 골든셋 판정, L/T 실측", "파일럿 2개월 · 사용자 2~3명 × 20% + 개발 대응", ms=["M-AL1-07"])
wp("A5", "AL-1", "열 해석 자동화 (VV-3 기구 열 공용)", 5, 9, dict(CAE=2.5, AI=1.2, DATA=0.2, DOM_ANA=0.6, DOM_MEC=0.6, AX=0.4),
   "열 도메인 플러그인(Icepak·Mechanical thermal) — AL-1 소유, VV-3 기구 열이 호출",
   "도메인 1개 확장 표준. 열 플러그인은 1회만 만들고 VV-3 가 재사용 (중복 제거)", ms=["M-AL1-08"], deps=[("LIC_THERM", 5), ("ONPREM", 5)])
wp("A6", "AL-1", "해석 창구 확장 — 타 과제 위임 수용", 7, 9, dict(AI=1.0, AX=0.5),
   "al1-lead 가 VV-3 의 SI/PI·EMC·열·공차 의뢰를 받는 계약(입출력)·게이트", "오케스트레이터 기능 추가 1.0 MM + 계약·시험 0.5 · 선검증 Agent(H3) 직전으로 — 마일스톤 없음", ag=["al1-lead"], was=(2, 4))
wp("A7", "AL-1", "야간 무인해석 오케스트레이션 구축", 7, 9, dict(AI=2.0, OPS=1.2, CAE=0.8, DOM_ANA=0.4, AX=0.6),
   "al1-night-batch — 야간 큐·격리·롤백·재시도·아침 리포트, HPC 라이선스 풀 연동",
   "배치 오케스트레이터 2.0 + 스케줄러·모니터링 1.2 + 배치 안정화 0.8 MM", ag=["al1-night-batch"], deps=[("HPC_NIGHT", 7), ("ONPREM", 7)])
wp("A8", "AL-1", "야간 무인해석 시범 운영", 10, 12, dict(DOM_ANA=0.6, AI=0.6, OPS=0.3, AX=0.3),
   "DAY-NIGHT-MORNING 루프 시범 — 아침 판정 루틴, 채택률 측정", "시범 3개월 · 아침 판정 0.2 FTE + 대응", ms=["M-AL1-09"])
wp("A9", "AL-1", "최적화 탐색 Agent", 8, 12, dict(AI=1.5, CAE=0.8, DOM_ANA=0.5),
   "al1-optimizer — 설계 변수 DOE·탐색 (doe-planner)", "Agent 1개(중) 2.8 MM", ag=["al1-optimizer"], lever="'28 1Q 로 미루면 2.8 MM 절감 — '28 광학 확장 전에만 있으면 됨")
wp("A10", "AL-1", "성과 측정·Gate 2 준비", 1, 12, dict(AX=1),
   "분기별 L/T·채택률·대체 MM 실측, Gate 2('28말) 근거 축적", "분기 0.25 MM")
wp("A11", "AL-1", "'28 광학 해석 확장 선행", 10, 12, dict(DOM_OPT=0.6, CAE=0.6, AI=0.6, DATA=0.3),
   "광학 골든셋 20건 · 광학 툴(Zemax·CODE V) API 자동화 범위 · 플러그인 설계 → '28.1 개발 착수",
   "빅플랜 p.16 '28 1Q '광학 해석 확장 착수' — 도메인 확장 표준 6.5 MM 중 설계·골든셋 몫(약 1/3)을 4Q 에")
wp("A12", "AL-1", "릴리즈 기능 운영 (AL-1)", None, None, dict(AI=0.4, CAE=0.3, DATA=0.3), "", "릴리즈 다음 달부터 1개당 월 0.1 FTE, 만든 사람이 운영(결함 수정, 재색인, 사용자 대응)하고 AX 는 판정과 우선순위만", op=True,
   ops_from=[("A3", 1, "형상·물성 추출"), ("A2", 1, "설계지식 검색"), ("A4", 1, "구조 플러그인"), ("A5", 1, "열 플러그인")])

# ── VV-1 LiDAR 가상검증 플랫폼
wp("V1", "VV-1", "LiDAR 센서 물리 모델 고도화", 1, 3, dict(SIM=3.0, DOM_SYS=1.2, DOM_OPT=0.5),
   "ToF·FMCW 빔·노이즈·반사율 모델 — 합성데이터 품질의 기준", "센서 모델 1종 고도화 3.0 MM + 파라미터·검증 1.7 MM", ms=["M-VV1-03"])
wp("V2", "VV-1", "GT 자동생성 파이프라인", 1, 3, dict(DATA=1.5, ML=0.8, SIM=0.4, AX=0.3),
   "vv1-gt-label — 시뮬레이터 장면 → 3D 박스·세그 라벨 자동 생성·검수", "파이프라인 1.5 + 라벨 규격·검증 1.2 MM", ms=["M-VV1-03"], ag=["vv1-gt-label"])
wp("V3", "VV-1", "시뮬레이터·연산엔진 연동", 2, 4, dict(SIM=0.8, OPS=0.4, AI=0.4, AX=0.3),
   "연산엔진·외부 시뮬레이터 실행 API(MCP 후보 lidar-engine), 라이선스·반출 검토", "연동 1.2 + 계약·보안 검토 0.3 · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음", deps=[("SIM_LIC", 4)], was=(1, 3))
wp("V4", "VV-1", "합성데이터 대량 생성 파이프라인", 4, 6, dict(DATA=1.2, SIM=1.2, OPS=0.4),
   "도메인 랜덤화·장면 배치 생성·데이터셋 버전 관리 — 학습 GPU(4월) 도착과 함께 시작", "2.8 MM · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음", deps=[("GPU_TRAIN", 4), ("STORAGE", 4)], after=["V1"], ss=True, was=(3, 5))
wp("V5", "VV-1", "합성데이터 인지모델 학습", 4, 6, dict(ML=3.0, DOM_SYS=0.4, OPS=0.3),
   "3D 검출·분할 모델 학습(합성 → 실측 소량 미세조정), 평가 지표", "ML 1명 × 3개월", ms=["M-VV1-04"], deps=[("GPU_TRAIN", 4)], after=["V4"], ss=True)
wp("V6", "VV-1", "엔진 검증 조율·ODD 시나리오 생성 Agent", 5, 8, dict(AI=1.8, SIM=0.8, AX=0.8, DOM_SYS=0.4),
   "vv1-lead + vv1-scenario-gen — 시나리오 생성 → 승인 → 라벨 → KPI 판정 흐름", "Agent 2개(lead 1·sub 1) 3.8 MM · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음", ag=["vv1-lead", "vv1-scenario-gen"], was=(4, 7))
wp("V7", "VV-1", "인지모델 검증·Sim2Real 기준선", 7, 9, dict(ML=2.0, DOM_SYS=0.8, DATA=0.4, AI=0.4),
   "vv1-perception-verify — 실측 대비 상관 측정 방법·기준선(Gate 2 80% 의 출발점)", "3.6 MM", ms=["M-VV1-05"], ag=["vv1-perception-verify"])
wp("V8", "VV-1", "ODD 시나리오 확충", 6, 9, dict(SIM=1.8, DOM_SYS=0.6, AX=0.4),
   "ODD 조합 확대(날씨·조도·반사율·거리) — 커버리지 40% 목표 분모 확정", "2.8 MM", ms=["M-VV1-05"])
wp("V9", "VV-1", "ODD 커버리지 측정·40% 달성", 10, 12, dict(ML=0.8, SIM=0.8, DOM_SYS=0.5, AX=0.5),
   "커버리지 리포트 자동화, 40% 판정·'28 70% 계획", "2.6 MM", ms=["M-VV1-06"])
wp("V10", "VV-1", "엔진 KPI 판정 자동화 운영", 1, 12, dict(AX=0.4, AI=0.3, DOM_SYS=0.3),
   "vv1-kpi-check — 릴리즈별 레이턴시·정확도 판정", "운영 0.08 FTE", ag=["vv1-kpi-check"], op=True)
wp("V11", "VV-1", "'28 HIL 벤치 선행", 10, 12, dict(SIM=0.5, DOM_SYS=0.6, OPS=0.3, ML=0.3),
   "HIL 벤치 사양 · 센서↔연산엔진↔시뮬레이터 인터페이스 정의 · 장비 견적·발주(납기 약 3개월)",
   "빅플랜 p.16 '28 1Q 'HIL 벤치 구축' — 장비 투자는 '28 예산(C7b)에 올림")
wp("V12", "VV-1", "릴리즈 기능 운영 (VV-1)", None, None, dict(AI=0.4, SIM=0.2, DATA=0.4), "", "릴리즈 다음 달부터 1개당 월 0.1 FTE, 만든 사람이 운영(결함 수정, 재색인, 사용자 대응)하고 AX 는 판정과 우선순위만", op=True,
   ops_from=[("V2", 1, "GT 자동생성"), ("V4", 1, "합성데이터 파이프라인"), ("V6", 2, "검증 조율·시나리오 생성"), ("V7", 1, "인지 검증")])

# ── VV-3 MBSE HW 선검증
wp("H1", "VV-3", "도면·BOM 정합성 운영 전환", 4, 6, dict(AI=1.0, DATA=0.8, DOM_CIR=0.3, DOM_MEC=0.3, AX=0.7),
   "diff-review PoC → 운영, 도면 치수 추출('27 범위)", "운영 전환 3.1 MM · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음(PLM 조회 창구 H2 뒤)", ag=["vv3-diff-review"], deps=[("PLM", 4), ("ONPREM", 4)], was=(1, 3))
wp("H2", "VV-3", "PLM 연동·설계데이터 조회 (AL-1 공용)", 2, 5, dict(DATA=1.8, OPS=0.4, AI=0.4, AX=0.3),
   "PLM 읽기 MCP + sh-data-query — 제한 등급 원본은 이 창구로만", "MCP 서버 1개(읽기) 2.2 + 계정·보안 0.7 MM · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음", ag=["sh-data-query"], deps=[("PLM", 2), ("SEC", 2)], was=(1, 4))
wp("H3", "VV-3", "설계변경 검토 조율·회로/기구 선검증 Agent", 9, 12, dict(AI=1.8, AX=0.8, DOM_CIR=0.4, DOM_MEC=0.4),
   "vv3-lead + vv3-hw-precheck — 변경 → 영향 → 선검증 의뢰(AL-1 해석 창구) → 판정", "Agent 2개 3.4 MM · 6~8월 AI 봉우리를 4분기로 폄 — 마일스톤 없음, 운영은 '28 부터(해석 창구 A6 뒤)", ag=["vv3-lead", "vv3-hw-precheck"], was=(2, 5), after=["A6"], ss=True)
wp("H4", "VV-3", "회로 SI/PI 해석 자동화", 1, 4, dict(CAE=2.2, DOM_CIR=1.2, AI=0.4),
   "SI/PI 플러그인(SIwave·HFSS) — AL-1 해석 플랫폼 위에 구축", "도메인 확장 표준(플랫폼 재사용으로 AI 몫 축소)", ms=["M-VV3-03"], deps=[("LIC_HFSS", 2)])
wp("H5", "VV-3", "EMC 해석 확대 (HFSS·Maxwell)", 4, 6, dict(CAE=2.2, DOM_CIR=1.0, AI=0.4), "EMC 플러그인", "도메인 확장 표준", ms=["M-VV3-04"], deps=[("LIC_HFSS", 4)])
wp("H6", "VV-3", "RVTM 추적체계 정의 (MBSE)", 1, 6, dict(MBSE=3.5, DOM_SYS=0.8, DOM_CIR=0.3, DOM_MEC=0.3, AX=0.8),
   "1D Echo Gen2 1개 프로젝트 요구 → 시스템 모델 → 검증 RVTM 템플릿·툴 도입", "MBSE 전문가 0.6 FTE × 6개월 + 도메인", ms=["M-VV3-10", "M-VV3-00"], deps=[("MBSE_TOOL", 2)])
wp("H7", "VV-3", "요구 추적 Agent", 9, 12, dict(AI=1.2, MBSE=0.8, AX=0.4), "vv3-rvtm (rvtm-trace)", "Agent 1개 2.4 MM · 6~8월 AI 봉우리를 4분기로 폄 — 마일스톤 없음, 운영은 '28 부터", ag=["vv3-rvtm"], was=(6, 9))
wp("H8", "VV-3", "설계자료 구성 Agent", 10, 12, dict(AI=0.8, DATA=0.4, AX=0.3), "vv3-design-pack — PLM 설계자료 묶음", "Agent 1개(소) 1.5 MM · 6~8월 AI 봉우리를 4분기로 폄 — 마일스톤 없음, 운영은 '28 부터", ag=["vv3-design-pack"], was=(5, 7),
   lever="원장에 마일스톤 없음 — '28 로 미루면 1.5 MM 절감")
wp("H9", "VV-3", "기구 열·공차 해석 자동화", 7, 9, dict(CAE=1.8, DOM_MEC=1.0, AI=0.4),
   "공차 스택업 자동화 + 열은 A5 플러그인 재사용", "열 재사용으로 표준 대비 축소", ms=["M-VV3-05"], deps=[("LIC_THERM", 7)])
wp("H10", "VV-3", "회로·기구 해석 자동화 1차 통합·검증", 10, 12, dict(CAE=0.8, AI=0.6, DOM_CIR=0.5, DOM_MEC=0.5, AX=0.5),
   "SI/PI·EMC·열·공차 통합 판정, 시제품 차수 영향 측정 시작", "2.9 MM", ms=["M-VV3-06"])
wp("H11", "VV-3", "AFM/AFMEA·수율 선예측 PoC", 7, 12, dict(ML=1.5, DATA=0.8, DOM_MEC=0.6, DOM_OPT=0.3),
   "기구 구조·열·광학 확대 판단 근거 + 수율 예측 PoC(표 데이터)", "PoC 3.2 MM", ms=["M-VV3-07"], lever="PoC 를 '28 상으로 미루면 3.2 MM·ML 0.25 FTE 절감 — 2차보완보고 H2 일정은 지연")
wp("H12", "VV-3", "재설계안 후보 Agent (광학)", 9, 12, dict(AI=0.8, CAE=0.4, DOM_OPT=0.6), "vv3-redesign-draft", "Agent 1개(소) 1.8 MM", ag=["vv3-redesign-draft"],
   lever="'28 로 미루면 1.8 MM 절감 — Virtual Prototype('28.2Q) 전에만 있으면 됨")
wp("H13", "VV-3", "해석 Agent 운영 (SI/PI·EMC·공차)", 5, 12, dict(AI=0.6, CAE=0.6, AX=0.3), "릴리즈된 플러그인 운영·결함 대응", "운영 0.19 FTE", op=True)
wp("H14", "VV-3", "'28 Virtual Prototype 선행", 10, 12, dict(AI=0.6, CAE=0.3, DOM_CIR=0.3, DOM_MEC=0.3, DATA=0.3),
   "1차 통합(H10) 결과로 VP 통합 범위 · 해석 플러그인 연결 · 판정 기준 설계",
   "빅플랜 p.16 '28 2Q 'Virtual Prototype 통합검증' — 2Q 완료에 필요한 설계를 4Q 에")
wp("H15", "VV-3", "릴리즈 Agent 운영 (VV-3)", None, None, dict(AI=0.5, DATA=0.5), "", "릴리즈 다음 달부터 1개당 월 0.1 FTE, 만든 사람이 운영(결함 수정, 재색인, 사용자 대응)하고 AX 는 판정과 우선순위만", op=True,
   ops_from=[("H2", 1, "PLM 조회"), ("H1", 1, "도면·BOM 정합성"), ("H3", 2, "선검증"), ("H8", 1, "설계자료"), ("H7", 1, "요구 추적")])

# ── 공통 기반 (3과제를 돌리는 데 꼭 필요한 것만 — CO-1·공용 확산은 이 계획 밖)
wp("C1", "공통", "LLM 브리지 환경 (자체 온프렘 가동 전)", 1, 2, dict(OPS=1.0, AX=0.2),
   "전사 지원 조직 공용 GPU·로컬 LLM 또는 빅플랜 GPU 선배정으로 C3 처리 임시 환경", "1.2 MM", deps=[("SEC", 1)])
wp("C2", "공통", "온프렘 LLM 플랫폼 정식 구축·이관", 7, 8, dict(OPS=1.2, AI=0.3, AX=0.2),
   "서빙(vLLM)·감사 로그·모니터링, 브리지 → 정식 이관 (게이트웨이·등급 라우팅은 C13)", "1.7 MM", deps=[("ONPREM", 7)])
wp("C3", "공통", "LLM·Agent 플랫폼 운영 — 서빙·런타임·게이트웨이·관측·평가", None, None, dict(OPS=1.0),
   "vLLM·모델 교체·파서 회귀 · 런타임·게이트웨이·Langfuse · Agent × 모델 회귀 평가 — 운영안마다 다름",
   "R4 플랫폼 소계(1안 1.8 · 2안 1.5 · 혼합 1.3 FTE) — 3~6월은 API·브리지만이라 50%", prof=[0, 0] + [0.5] * 4 + [1.0] * 6, op=True)
wp("C4", "공통", "학습·데이터 환경 구성", 3, 4, dict(OPS=0.8), "K8s/Slurm·데이터셋 스토리지 연결", "0.8 MM", deps=[("GPU_TRAIN", 4), ("STORAGE", 3)])
wp("C5", "공통", "거버넌스·승인·반출 등급 운영", 1, 12, dict(AX=1.4), "ct-guard·승인 게이트·정보보안 패키지 갱신", "0.12 FTE", ag=["ct-guard"], novibe=True)
wp("C6", "공통", "Agent 등록·실행 기록 (3과제 Agent)", 1, 12, dict(AX=0.6), "3과제 Agent 13개의 카드·Manifest 검사·실행 기록 — 공용 확산·CO-1 은 이 계획 밖", "0.05 FTE")
wp("C7", "공통", "투자심의·예산·조달", 1, 3, dict(AX=0.5), "온프렘 투자심의 대응·발주", "0.5 MM", novibe=True)
wp("C7b", "공통", "'28 예산·투자 계획", 8, 10, dict(AX=0.3), "'28 예산 편성", "0.3 MM", novibe=True)
wp("C8", "공통", "월별 진척·P0 투입률 점검·Rolling Wave", 1, 12, dict(AX=1.4), "월 점검·'28 상세 일정('27 4Q)·Gate 2 로드맵", "0.12 FTE", novibe=True)
wp("C9", "공통", "교육·변화관리·채택률", 3, 12, dict(AX=0.8, DOM_ANA=0.2, DOM_CIR=0.1, DOM_MEC=0.2, DOM_SYS=0.1),
   "사용자 교육·현업 챔피언·채택률 측정", "1.4 MM", novibe=True)
wp("C10", "공통", "채용·사내 조달 관리", 1, 6, dict(AX=0.6), "경력 채용 면접·사내 공모·전환배치 협의·온보딩", "0.6 MM", novibe=True)

# ── 개발 방법 — 바이브 코딩 · 외부 MCP · 이식 계층 (사내 직접 개발의 전제)
wp("C11", "공통", "바이브 코딩 도입 — 도구·보안 승인·개발 규칙", 1, 2, dict(AX=0.6, OPS=0.5, AI=0.3),
   "코딩 도구·정보보안 승인(C0~C2 코드만 외부, C3 금지) · managed settings·WSL2 표준 · 공통 CLAUDE.md·Skills·서브에이전트 템플릿 · 검증 게이트(테스트·SAST·비밀·의존성) · PyAEDT 문서 MCP",
   "도입 1회 1.4 MM — 숙련 기간(효과 절반)은 ramp 로 따로", novibe=True, deps=[("VIBE_SEC", OPTD["vibe_start"][VL])])
wp("C12", "공통", "외부 MCP 선정·보안 검증", 1, 6, dict(OPS=0.5, AI=0.3, AX=0.2),
   "후보 MCP(Ansys AEDT·Mechanical 우선) 소스·권한·네트워크 검토 → 사내 미러·버전·해시 고정 · 허용 목록 · 망분리 시험",
   "서버 수 × 1개당 검증 + 구축 (R3) — Ansys 2개는 1분기, 나머지는 쓰는 WP 착수 전에 하나씩", novibe=True, was=(1, 3))
wp("C12b", "공통", "외부 MCP 재검토 (버전 추종·rug pull 감시)", None, None, dict(OPS=0.6, AI=0.4),
   "도입한 MCP 서버의 버전 갱신·도구 정의 해시 비교·재승인", "서버 수 × 연 재검토 공수 (R3)", prof=[0] * 6 + [1.0] * 6, op=True, novibe=True)
wp("C13", "공통", "Agent 이식 계층 — 게이트웨이·등급 라우팅·모델 어댑터·평가 하네스", 3, 8, dict(AI=0.5, OPS=0.5),
   "Agent 정의 자산(SKILL.md·서브에이전트·MCP·A2A 카드·평가셋) 로더 · 게이트웨이(C0~C1 → API, C3 → 온프렘) · 1Q PoC 게이트 4개",
   "R4 이식 계층 7 MM (2안은 외부 경로가 없어 ×0.7) · 외주 0 재배치 — 1분기 사내 인력 한도 때문에 옮김, '27 마일스톤 영향 없음 — 온프렘 가동(7월) 전 게이트웨이 완료", after=["C11"], ss=True, was=(2, 7))
wp("C16", "공통", "팀 학습 — LangGraph·MCP·A2A·바이브 코딩 규칙", 1, 6, dict(AI=0.3, OPS=0.2, DATA=0.2, AX=0.2, CAE=0.1),
   "런타임·MCP 스펙·A2A 1.0·검증 게이트 실습 — 입사자는 입사 램프에 포함", "R4 framework_learning 5 MM — 상반기에 나눠서", novibe=True, was=(1, 4))
wp("C17", "공통", "C3 비식별·합성 픽스처 (외부 코딩 도구용)", 1, 3, dict(DATA=0.6, CAE=0.3, DOM_ANA=0.1, DOM_MEC=0.1),
   "도면·BOM·STP 의 구조만 남긴 합성 데이터 — 외부 바이브 코딩이 C3 를 보지 않고 개발하게", "R1 권고 — 공수는 추정")

# ---------------------------------------------------------------- 작업 순서 (선행 WP — 기본은 끝-시작, ss=True 는 시작-시작)
AFTER = {"A4": (["A3"], False), "A8": (["A7"], False), "A9": (["A5"], True), "H9": (["A5"], True), "H10": (["H4", "H5", "H9"], False),
         "H7": (["H6"], True), "H13": (["H4"], False), "V7": (["V5"], True), "V9": (["V8"], False), "V8": (["V6"], True), "V6": (["V3"], False),
         "C2": (["C1"], False), "C3": (["C1"], False), "A7": (["A3"], False),
         "H14": (["H10"], True), "C13": (["C11"], True)}
for w in WP:
    if w["id"] in AFTER and all(any(x["id"] == p for x in WP) for p in AFTER[w["id"]][0]):
        w["after"], w["ss"] = AFTER[w["id"]]

MERGE = METHOD.get("merge", {})
for a_, b_ in MERGE.items():
    for w in WP:
        for key in ("eff", "share"):
            d_ = w.get(key)
            if d_ and a_ in d_:
                d_[b_] = round(d_.get(b_, 0) + d_.pop(a_), 4)
    src_ = next(r for r in ROLES if r[0] == a_)
    i_ = next(i for i, r in enumerate(ROLES) if r[0] == b_)
    t_ = ROLES[i_]
    ROLES[i_] = (t_[0], METHOD.get("merge_names", {}).get(b_, t_[1]), t_[2], t_[3] + " / " + src_[3], t_[4] + src_[4], t_[5], t_[6])
    ROLES[:] = [r for r in ROLES if r[0] != a_]
ROLE_IDS[:] = [r[0] for r in ROLES]
DEV[:] = [r for r in DEV if r not in MERGE]

# ---------------------------------------------------------------- 공급(가정 — HTML 에서 바꿀 수 있게 기본값만)
SUPPLY = {
    "AX": dict(fte=2.0, avail=0.8, who="A·B 2명 × 80% (나머지 20% = CO-1·P1·P2 과제·CT 트랙·교육 — 우선 3과제 위주)"),
    "CAE": dict(fte=0.5, avail=1.0, who="DRI 팀 툴 개발자 0.5 FTE (확인 필요)"),
    "SIM": dict(fte=0.5, avail=1.0, who="VV-1 플랫폼 개발자 0.5 FTE (확인 필요)"),
}
DOM_CAP = {  # P0 투입률 30% 보장(빅플랜 p.16) × 관련 인원 — 넘으면 과부하 경고
    "DOM_ANA": dict(people=4, note="해석 DRI 팀 4명 가정"), "DOM_CIR": dict(people=6, note="회로 6명"),
    "DOM_MEC": dict(people=7, note="기구 7명"), "DOM_OPT": dict(people=10, note="광학 10명"), "DOM_SYS": dict(people=10, note="시스템 10명"),
}
LEAD = {"채용(경력)": 6, "사내 공모": 3, "사내 전환배치": 2, "사내 지원(겸직)": 1, "DRI 시민개발": 1, "DRI 팀 직접": 1, "전사 지원": 1, "일정 조정": 0,
        "A·B 개발 투입": 0}  # 개월 — 외주 없음
for k, v in METHOD.get("lead", {}).items():
    if k in LEAD:
        LEAD[k] = v[VL]
INHOUSE = set(LEAD)

# ---------------------------------------------------------------- 조달 계획 — 사내 직접 개발만 (외주 0)
SOURCING = [
    dict(role="AI", kind="채용(경력)", fte=2.0, s=5, e=12, note="2명 — '26.11 품의 → '27.5 입사(6개월)"),
    dict(role="AI", kind="사내 공모", fte=1.0, s=2, e=12, note="사내 SW 인력 공모 — '26.11 공고 → '27.2"),
    dict(role="AI", kind="사내 지원(겸직)", fte=1.0, s=1, e=4, note="사내 SW 조직 겸직 — 경력 입사 전"),
    dict(role="CAE", kind="사내 전환배치", fte=1.0, s=1, e=12, note="해석 스크립트 경험자 1명"),
    dict(role="CAE", kind="DRI 시민개발", fte=0.5, s=1, e=6, dom="DOM_CIR", note="현업 회로 엔지니어가 SI/PI·EMC 후처리 스크립트를 바이브 코딩으로"),
    dict(role="ML", kind="채용(경력)", fte=1.0, s=5, e=12, note="Sim2Real·수율 예측"),
    dict(role="ML", kind="사내 지원(겸직)", fte=0.3, s=1, e=4, note="사내 인지 SW 경험자 겸직 — GT 규격"),
    dict(role="SIM", kind="사내 지원(겸직)", fte=0.8, s=1, e=4, note="VV-1 플랫폼 개발자 추가 투입(VV-1 DRI 팀)"),
    dict(role="DATA", kind="채용(경력)", fte=1.0, s=5, e=12, note="'28 데이터 순환체계"),
    dict(role="DATA", kind="사내 전환배치", fte=1.0, s=1, e=12, note="IT·PLM 데이터 담당 전환 — PLM MCP·설계지식DB"),
    dict(role="OPS", kind="전사 지원", fte=0.8, s=1, e=4, note="브리지·게이트웨이 구성"),
    dict(role="OPS", kind="채용(경력)", fte=1.0, s=5, e=12, note="LLM 서빙·MLOps"),
    dict(role="MBSE", kind="사내 전환배치", fte=0.8, s=1, e=12, note="시스템 엔지니어 MBSE 전환(Capella)"),
    dict(role="AX", kind="일정 조정", fte=0.4, s=1, e=4, note="A·B 1~4월 80% → 100% — CO-1·P1·P2·CT 업무를 5월 이후로"),
]
SHIFT, DEFER = {}, []
if ARGS.sourcing:
    _src = json.load(io.open(ARGS.sourcing, encoding="utf-8"))
    if isinstance(_src, dict):
        SOURCING, SHIFT, DEFER = _src["sourcing"], _src.get("shift", {}), _src.get("defer", [])
    else:
        SOURCING = _src
DEFERRED = [dict(id=w["id"], task=w["task"], name=w["name"], mm=round(sum(w["eff"].values()), 2)) for w in WP if w["id"] in DEFER]
WP[:] = [w for w in WP if w["id"] not in DEFER]  # '28 로 넘긴 범위 — 마일스톤이 걸린 WP 를 넘기면 연결 점검이 잡는다
DROPPED = []
_kept = {w["id"] for w in WP}
for w in WP:
    gone = [q for q in w.get("after", []) if q not in _kept]
    if gone:
        DROPPED.append(dict(wp=w["id"], name=w["name"], pred=gone))
        w["after"] = [q for q in w["after"] if q in _kept]
for w in WP:  # 일정 이동(설계안) — 기간은 그대로, 시작·끝만 민다
    k = SHIFT.get(w["id"], 0)
    if k and not w.get("prof") and not w.get("ops_from"):
        w["s"], w["e"] = w["s"] + k, min(12, w["e"] + k)
        w["shifted"] = k
_byid0 = {w["id"]: w for w in WP}
for w in list(WP):
    if not w.get("ops_from"):
        continue
    pr, items = [0.0] * 12, []
    for src_id, n_, label_ in w["ops_from"]:
        sw = _byid0.get(src_id)
        if sw and sw.get("e") and sw["e"] < 12:
            for m in range(sw["e"] + 1, 13):
                pr[m - 1] += OPS_RATE * n_
            items.append(f"{label_} '27.{sw['e'] + 1}~")
    if sum(pr) <= 0:
        WP.remove(w)
        continue
    on_ = [i + 1 for i, v in enumerate(pr) if v > 0]
    w["s"], w["e"], w["prof"] = on_[0], on_[-1], [round(v, 3) for v in pr]
    w["eff"] = {r: sum(pr) * k_ for r, k_ in w["share"].items()}
    w["out"] = ", ".join(items)

def mlabel(m):
    return f"2027-{m:02d}" if m >= 1 else f"2026-{12 + m:02d}"

TODAY = -2  # 2026-10 (오늘 2026-10-21)
for x in SOURCING:
    x["lead"] = LEAD[x["kind"]]
    x["start_by"] = x["s"] - x["lead"]
    x["start_by_label"] = mlabel(x["start_by"])
    x["late"] = x["start_by"] < TODAY

# ---------------------------------------------------------------- 계산
V = METHOD["vibe"]
MCP = METHOD["mcp"]
SAVE_KEY = {"hi": "saving_hi", "base": "saving_base", "lo": "saving_lo"}
# 방법 WP 의 공수는 method.json 값으로
def scale(w, tot):
    t0 = sum(w["eff"].values())
    w["eff"] = {r: round(v / t0 * tot, 3) for r, v in w["eff"].items()}


for w in WP:
    if w["id"] == "C12":
        scale(w, MCP["servers"][VL] * MCP["vetting_mm_per_server"][VL] + MCP["setup_mm"][VL])
    if w["id"] == "C12b":
        f = MCP["servers"][VL] * MCP["rereview_mm_per_server_year"][VL] / 12
        w["prof"] = [v * f for v in w["prof"]]
        w["eff"] = {r: round(sum(w["prof"]) * k, 3) for r, k in w["share"].items()}
    if w["id"] == "C13":
        scale(w, METHOD["portability_build_mm"][VL] * OPTD["portability_mult"])
    if w["id"] == "C16":
        scale(w, METHOD["learning_mm"][VL])
    if w["id"] == "C3":  # 운영안별 플랫폼 운영 FTE — 역할 비중을 그대로 프로필에
        sh = {r: v[VL] for r, v in OPTD["platform"].items()}
        w["share"] = sh
        w["eff"] = {r: round(sum(w["prof"]) * k, 3) for r, k in sh.items()}


def vibe_factor(role, m, level, op):
    """역할·월의 공수 배수 — 승인 전 1.0, 숙련 기간은 효과 절반, 2안은 로컬 모델이라 효과 일부만."""
    key = "RUN" if (op and role != "AX") else role
    start = OPTD["vibe_start"][level]
    if key not in V["ext"] or m < start:
        return 1.0
    f = V["ext"][key][level]
    if OPTD["coding"] == "local":
        f = 1 - (1 - f) * V["local_effect"][level]
    if m < start + V["ramp_months"][level]:
        f = 1 - (1 - f) / 2
    return f


def mcp_saving(w, role, level):
    if role not in DEV:
        return 0.0
    x = MCP["wp"].get(w["id"])
    return x[SAVE_KEY[level]] if x else 0.0


def monthly(w, m, level=VL, raw=False, mcp_only=False):
    if w.get("prof"):
        base = {r: w["prof"][m - 1] * k for r, k in w["share"].items()}
    else:
        n = w["e"] - w["s"] + 1
        base = {r: mm / n for r, mm in w.get("eff0", w["eff"]).items()}  # 항상 원래 추정에서 출발 — 반영값에 또 곱하지 않게
    if w.get("op") and w["id"] not in ("C3", "C12b"):  # 2안은 로컬 모델 품질 보정으로 Agent 유지보수가 늘어남 (R4)
        base = {r: v * OPTD["run_mult"] for r, v in base.items()}
    if raw or w.get("novibe"):
        return base
    if mcp_only:
        return {r: v * (1 - mcp_saving(w, r, level)) for r, v in base.items()}
    return {r: v * (1 - mcp_saving(w, r, level)) * vibe_factor(r, m, level, w.get("op")) for r, v in base.items()}


def demand(level=VL, raw=False, mcp_only=False):
    d = {r: [0.0] * 12 for r in ROLE_IDS}
    dt = defaultdict(lambda: {r: [0.0] * 12 for r in ROLE_IDS})
    for w in WP:
        for m in range(w["s"], w["e"] + 1):
            for r, v in monthly(w, m, level, raw, mcp_only).items():
                d[r][m - 1] += v
                dt[w["task"]][r][m - 1] += v
    return d, dt


raw_dem, _ = demand(raw=True)
dem, dem_task = demand()
for w in WP:  # WP 공수 = 반영 후 값, 원래 추정은 eff0
    w["eff0"] = {r: round(v, 3) for r, v in w["eff"].items()}
    acc = defaultdict(float)
    for m in range(w["s"], w["e"] + 1):
        for r, v in monthly(w, m).items():
            acc[r] += v
    w["eff"] = {r: round(v, 4) for r, v in acc.items()}

tot_role = {r: round(sum(dem[r]), 2) for r in ROLE_IDS}
tot_task = {t: round(sum(sum(v) for v in d.values()), 2) for t, d in dem_task.items()}
tot_wp = round(sum(sum(w["eff"].values()) for w in WP), 2)
peak = {r: round(max(dem[r]), 2) for r in ROLE_IDS}
avg = {r: round(sum(dem[r]) / 12, 2) for r in ROLE_IDS}

def qend(date):
    d = str(date)
    if "-Q" in d:
        return int(d[-1]) * 3
    if "-H" in d:
        return 6 if d.endswith("H1") else 12
    return 12

# ---------------------------------------------------------------- 점검
INP = os.path.join(HERE, "inputs", "ledger_2027.json")  # 원장·로스터 중 2027 몫만 뽑은 사본 — 이 폴더만 있어도 돌아가게
if os.path.isfile(INP):
    _inp = json.load(io.open(INP, encoding="utf-8"))
    L, R = _inp["ledger"], _inp["roster"]
else:
    L = json.load(io.open(os.path.join(PROJ, "_build", "final_data.json"), encoding="utf-8"))
    R = json.load(io.open(os.path.join(PROJ, "_build", "agent_roster.json"), encoding="utf-8"))
ms27 = []
for t in L["tasks"]:
    if t["code"] in ("AL-1", "VV-1", "VV-3"):
        for m in t["milestones"]:
            if str(m.get("date", "")).startswith("2027"):
                ms27.append(dict(ref=m["ref"], task=t["code"], date=m["date"], label=m["label"],
                                 kind="start" if any(k in m["label"] for k in ("착수", "개시")) else "end"))
covered = {r for w in WP for r in w["ms"]}
ag27 = [a for a in R["agents"] if a["task"] in ("AL-1", "VV-1", "VV-3") and str(a.get("phase", "")).startswith("'27")]
ag_cov = {k for w in WP for k in w["ag"]}
checks = []
miss_ms = [m for m in ms27 if m["ref"] not in covered]
checks.append(dict(id="ms", label="'27 원장 마일스톤 → 작업 패키지 연결", ok=not miss_ms, n=len(ms27) - len(miss_ms), of=len(ms27),
                   detail=[f"{m['ref']} {m['label']}" for m in miss_ms]))
miss_ag = [a for a in ag27 if a["key"] not in ag_cov]
checks.append(dict(id="ag", label="'27 로스터 Agent → 작업 패키지 연결", ok=not miss_ag, n=len(ag27) - len(miss_ag), of=len(ag27),
                   detail=[f"{a['key']} {a['name']}" for a in miss_ag]))
late = []
for w in WP:
    for d in w["deps"]:
        D = DEPS[d["dep"]]
        if D["eta"] > d["need"]:
            late.append(dict(wp=w["id"], wpname=w["name"], dep=d["dep"], depname=D["name"], need=d["need"], eta=D["eta"], bridge=D.get("bridge", "")))
checks.append(dict(id="deps", label="선행 조건 확보 월 ≤ 필요 월", ok=not late, n=sum(len(w["deps"]) for w in WP) - len(late), of=sum(len(w["deps"]) for w in WP),
                   detail=[f"{x['wp']} {x['wpname']} — {x['depname']}: 필요 {x['need']}월 · 확보 예상 {x['eta']}월" for x in late]))
_wp_raw = sum(sum(w["eff"].values()) for w in WP)
sum_ok = abs(sum(sum(v) for v in dem.values()) - _wp_raw) < 0.01 and abs(sum(sum(sum(v) for v in d.values()) for d in dem_task.values()) - _wp_raw) < 0.01
checks.append(dict(id="sum", label="합계 일치 (작업 패키지 = 역할 합 = 과제 합)", ok=sum_ok, n=1 if sum_ok else 0, of=1,
                   detail=[f"WP {tot_wp} · 역할 {round(sum(tot_role.values()),2)} · 과제 {round(sum(tot_task.values()),2)}"]))
dom_over = []
citizen = {r: [0.0] * 12 for r in DOM_CAP}  # DRI 팀 엔지니어가 바이브 코딩으로 맡는 개발 = 그 팀의 P0 시간
for x in SOURCING:
    if x["kind"] in ("DRI 시민개발", "DRI 팀 직접"):
        for m in range(max(1, x["s"]), x["e"] + 1):
            citizen[x["dom"]][m - 1] += x["fte"]
for r, c in DOM_CAP.items():
    cap = c["people"] * 0.3
    pk = max(dem[r][i] + citizen[r][i] for i in range(12))
    if pk > cap + 1e-9:
        dom_over.append(f"{r} 피크 {pk:.2f} FTE > 상한 {cap:.1f}")
checks.append(dict(id="dom", label="도메인 투입 ≤ P0 투입률 30% 상한", ok=not dom_over, n=len(DOM_CAP) - len(dom_over), of=len(DOM_CAP), detail=dom_over))

# 작업 순서 — 끝-시작이면 선행 끝 다음 달부터, 시작-시작이면 선행과 같거나 뒤에 시작
byid = {w["id"]: w for w in WP}
seq_bad = []
for w in WP:
    for p in w.get("after", []):
        if p not in byid:
            seq_bad.append(f"{w['id']} {w['name']} — 선행 {p} 가 '28 로 넘어감")
            continue
        P = byid[p]
        ok = w["s"] >= (P["s"] if w.get("ss") else P["e"] + 1)
        if not ok:
            seq_bad.append(f"{w['id']} {w['name']} 시작 {w['s']}월 < 선행 {p} {'시작' if w.get('ss') else '끝'} {P['s'] if w.get('ss') else P['e']}월")
nseq = sum(len(w.get("after", [])) for w in WP)
checks.append(dict(id="seq", label="작업 순서 (선행 작업 뒤에 시작)", ok=not seq_bad, n=nseq - len(seq_bad), of=nseq, detail=seq_bad))

# 공급 = 기본 공급 + 조달 — 역할·월마다 수요 ≤ 공급 × 1.1 (10% 는 초과근무·일정 흡수로 봄)
supply_m = {r: [0.0] * 12 for r in ROLE_IDS}
for r, sp in SUPPLY.items():
    for i in range(12):
        supply_m[r][i] += sp["fte"] * sp["avail"]
RAMP = {k: v[VL] for k, v in METHOD.get("hire_ramp", {}).items() if not k.startswith("_")}  # 입사·전환 후 생산성 (R6)
ONBOARD = RAMP.get("채용(경력)", [0.5])
supply_src = defaultdict(lambda: [0.0] * 12)  # 출처별 (그래프·인원표)
for r, sp in SUPPLY.items():
    for i in range(12):
        supply_src["AX A·B" if r == "AX" else "DRI 개발자"][i] += sp["fte"] * sp["avail"]
for x in SOURCING:
    prof = RAMP.get(x["kind"], [])
    for m in range(max(1, x["s"]), x["e"] + 1):
        k = m - x["s"]
        f = prof[k] if k < len(prof) else 1.0
        supply_m[x["role"]][m - 1] += x["fte"] * f
        if x["kind"] == "A·B 개발 투입":  # A·B 시간에서 빼서 개발에 — A·B 본업 공급은 그만큼 준다
            supply_m["AX"][m - 1] -= x["fte"]
        supply_src["AX A·B" if x["kind"] in ("일정 조정", "A·B 개발 투입") else x["kind"]][m - 1] += x["fte"] * f
        if x["kind"] == "A·B 개발 투입":
            supply_src["AX A·B"][m - 1] -= x["fte"]
gaps = []
for r in ROLE_IDS:
    if r.startswith("DOM_"):
        continue
    for i in range(12):
        if dem[r][i] > supply_m[r][i] * 1.1 + 0.05:
            gaps.append(dict(role=r, m=i + 1, demand=round(dem[r][i], 2), supply=round(supply_m[r][i], 2)))
checks.append(dict(id="supply", label="역할별 월 수요 ≤ 공급(기본 + 조달) × 1.1", ok=not gaps, n=12 * len([r for r in ROLE_IDS if not r.startswith("DOM_")]) - len(gaps),
                   of=12 * len([r for r in ROLE_IDS if not r.startswith("DOM_")]), detail=[f"{g['role']} {g['m']}월 수요 {g['demand']} > 공급 {g['supply']}" for g in gaps]))
# 가동률 — 채용 역할은 연간 수요 ÷ 공급 ≥ 70% (남는 30% 이내는 미계획 대응·'28 선행으로 흡수)
util = {}
for r in ROLE_IDS:
    if r.startswith("DOM_"):
        continue
    sp = sum(supply_m[r])
    util[r] = round(sum(dem[r]) / sp, 3) if sp else None
hire_roles = [r for r in ROLE_IDS if any(x["role"] == r and x["kind"].startswith("채용") for x in SOURCING)]  # A·B 는 기존 인력이라 제외
low = [r for r in hire_roles if util[r] < 0.7]
checks.append(dict(id="util", label="경력 채용 역할 연간 가동률 ≥ 70% (수요 ÷ 공급)", ok=not low, n=len(hire_roles) - len(low), of=len(hire_roles),
                   detail=[f"{r} {util[r] * 100:.0f}% — 수요 {sum(dem[r]):.1f} / 공급 {sum(supply_m[r]):.1f} MM" for r in hire_roles]))
# AX(A·B) — 과제별 수요 vs 공급 (그래프용)
ax_pct = [dem["AX"][i] / supply_m["AX"][i] for i in range(12)]
axs = dict(supply=[round(v, 2) for v in supply_m["AX"]], by_task={t: [round(v, 3) for v in d["AX"]] for t, d in dem_task.items()},
           pct=[round(v * 100) for v in ax_pct], util=round(sum(dem["AX"]) / sum(supply_m["AX"]), 3),
           over=[i + 1 for i in range(12) if ax_pct[i] > 1.0], task_mm={t: round(sum(d["AX"]), 2) for t, d in dem_task.items()})
late_src = [x for x in SOURCING if x["late"]]
checks.append(dict(id="lead", label="조달 착수일이 오늘(2026-10) 이후", ok=not late_src, n=len(SOURCING) - len(late_src), of=len(SOURCING),
                   detail=[f"{x['role']} {x['kind']} — {x['start_by_label']} 착수 필요(이미 지남)" for x in late_src]))
def ms_end(m, S):
    wps = [w for w in WP if m["ref"] in w["ms"]]
    if not wps:  # 마일스톤 WP 를 '28 로 넘김 — 연말 뒤로 본다
        return 13
    return (min(S[w["id"]][0] for w in wps) if m["kind"] == "start" else max(S[w["id"]][1] for w in wps))


S_now = {w["id"]: [w["s"], w["e"]] for w in WP}
ms_late = [dict(ref=m["ref"], label=m["label"], due=qend(m["date"]), at=ms_end(m, S_now)) for m in ms27 if ms_end(m, S_now) > qend(m["date"])]
checks.append(dict(id="ms_sched", label="'27 마일스톤 기한 안 (작업 일정 기준)", ok=not ms_late, n=len(ms27) - len(ms_late), of=len(ms27),
                   detail=[f"{x['ref']} {x['label']} — 기한 {x['due']}월, 일정 {x['at']}월" for x in ms_late]))
cz = [0.0] * 12
for x in SOURCING:
    if x["kind"] == "DRI 시민개발":
        for m in range(max(1, x["s"]), x["e"] + 1):
            cz[m - 1] += x["fte"]
cz_cap = METHOD["citizen_dev_share"][VL]
cz_bad = [i + 1 for i in range(12) if cz[i] > cz_cap * dem["CAE"][i] + 1e-6]
checks.append(dict(id="citizen", label=f"DRI 시민개발 ≤ CAE 스크립트 수요의 {cz_cap * 100:.0f}% (R6)", ok=not cz_bad, n=12 - len(cz_bad), of=12,
                   detail=[f"{m}월 시민개발 {cz[m - 1]:.2f} > {cz_cap * dem['CAE'][m - 1]:.2f}" for m in cz_bad]))
outsrc = [x for x in SOURCING if x["kind"] not in INHOUSE]
checks.append(dict(id="inhouse", label="외주 0 — 조달은 모두 사내(채용·전환·공모·겸직·시민개발·전사 지원 조직)", ok=not outsrc, n=len(SOURCING) - len(outsrc), of=len(SOURCING),
                   detail=[f"{x['role']} {x['kind']}" for x in outsrc]))
# 보수 시나리오 — 바이브 코딩·MCP 효과가 보수값이면 같은 조달로 버티는가
hi_dem, _ = demand("hi")
hi_gaps = []
for r in ROLE_IDS:
    if r.startswith("DOM_"):
        continue
    for i in range(12):
        if hi_dem[r][i] > supply_m[r][i] * 1.1 + 0.05:
            hi_gaps.append(dict(role=r, m=i + 1, demand=round(hi_dem[r][i], 2), supply=round(supply_m[r][i], 2)))
hi_short = {}
for g in hi_gaps:
    hi_short[g["role"]] = round(hi_short.get(g["role"], 0) + g["demand"] - g["supply"] * 1.1, 2)
_ncell = 12 * len([r for r in ROLE_IDS if not r.startswith("DOM_")])
checks.append(dict(id="vibe_hi", label="바이브 코딩 효과가 보수값이어도 공급 충분", ok=not hi_gaps, n=_ncell - len(hi_gaps), of=_ncell,
                   detail=[f"{r} 부족 합 {v:.1f} MM" for r, v in hi_short.items()],
                   note="부족하면 범위 조정 레버('28 이월) 또는 '27.6 중간 점검에서 추가 채용"))

# 브리지 없음 시나리오 — 온프렘(C3) 대기 WP 를 자체 가동월로 밀고, 뒤따르는 WP 를 같이 민다 → 마일스톤 지연
def scenario(bridge):
    S = {w["id"]: [w["s"], w["e"]] for w in WP}
    changed = True
    while changed:
        changed = False
        for w in WP:
            s, e = S[w["id"]]
            dur = w["e"] - w["s"]
            need_start = w["s"]  # 원래 시작에서 출발 — 미룬 값에 또 미루지 않는다
            for d in w["deps"]:
                D = DEPS[d["dep"]]
                eta = D.get("bridge_eta", D["eta"]) if bridge else D["eta"]
                if eta > d["need"]:
                    need_start = max(need_start, w["s"] + (eta - d["need"]))
            for p in w.get("after", []):
                if p not in S:
                    continue
                ps, pe = S[p]
                need_start = max(need_start, ps if w.get("ss") else pe + 1)
            if need_start > s:
                S[w["id"]] = [need_start, need_start + dur]
                changed = True
    slips = []
    for m in ms27:
        wps = [w for w in WP if m["ref"] in w["ms"]]
        kind = "start" if any(k in m["label"] for k in ("착수", "개시")) else "end"
        if not wps:
            continue
        end = (min(S[w["id"]][0] for w in wps) if kind == "start" else max(S[w["id"]][1] for w in wps))
        due = qend(m["date"])
        if end > due:
            slips.append(dict(ref=m["ref"], task=m["task"], label=m["label"], due=due, end=end, slip=end - due,
                              wps=[w["id"] for w in wps if S[w["id"]][1] > due]))
    moved = {k: v for k, v in S.items() if v != [byid[k]["s"], byid[k]["e"]]}
    return dict(slips=slips, moved=moved)

scen = dict(bridge=scenario(True), nobridge=scenario(False))
checks.append(dict(id="bridge", label="브리지 확보 시 '27 마일스톤 지연 없음", ok=not scen["bridge"]["slips"], n=len(ms27) - len(scen["bridge"]["slips"]), of=len(ms27),
                   detail=[f"{s['ref']} {s['slip']}개월 지연" for s in scen["bridge"]["slips"]]))

sens = {}
for lv in ("hi", "base", "lo"):
    d_, _ = demand(lv)
    sens[lv] = {r: round(sum(d_[r]), 2) for r in ROLE_IDS}
byid_all = {w['id']: w for w in WP}
raw_tot = {r: round(sum(raw_dem[r]), 2) for r in ROLE_IDS}
mcp_dem, _ = demand(mcp_only=True)
METHOD_WP = {"C3": "플랫폼 운영 (서빙·런타임·게이트웨이·관측·평가)", "C13": "이식 계층 (게이트웨이·어댑터·평가 하네스)", "C16": "팀 학습",
             "C11": "바이브 코딩 도입·검증 게이트", "C17": "C3 합성 픽스처", "C12": "외부 MCP 검증", "C12b": "외부 MCP 재검토"}
parts = dict(task_raw=round(sum(sum(w["eff0"].values()) for w in WP if w["id"] not in METHOD_WP), 2),
             added={k: round(sum(byid_all[k]["eff0"].values()), 2) for k in METHOD_WP if k in byid_all},
             mcp=round(sum(sum(v) for v in raw_dem.values()) - sum(sum(v) for v in mcp_dem.values()), 2),
             vibe=round(sum(sum(v) for v in mcp_dem.values()) - sum(sum(v) for v in dem.values()), 2),
             total=round(sum(sum(v) for v in dem.values()), 2), labels=METHOD_WP)
out = dict(option=OPT, option_name=OPTD["name"], option_full=OPTD.get("full", ""), vibe_level=VL, method=METHOD, raw_role=raw_tot, sens=sens, hi_gaps=hi_gaps,
           hi_demand={r: [round(x, 3) for x in hi_dem[r]] for r in ROLE_IDS}, shift=SHIFT, deferred=DEFERRED, dropped_after=DROPPED, merge=MERGE, ramp=RAMP, parts=parts, supply_src={k: [round(x, 3) for x in v] for k, v in supply_src.items()},
           months=[f"2027-{m:02d}" for m in M], sourcing=SOURCING, supply_m={r: [round(x, 2) for x in v] for r, v in supply_m.items()}, gaps=gaps,
           scen=scen, roles=[dict(id=r[0], name=r[1], group=r[2], does=r[3], skills=r[4], level=r[5], source=r[6]) for r in ROLES],
           wp=WP, deps=DEPS, supply=SUPPLY, dom_cap=DOM_CAP, lead=LEAD, demand={r: [round(x, 3) for x in dem[r]] for r in ROLE_IDS},
           demand_task={t: {r: [round(x, 3) for x in v] for r, v in d.items()} for t, d in dem_task.items()},
           totals=dict(role=tot_role, task=tot_task, wp=tot_wp, peak=peak, avg=avg), util=util, axs=axs, onboard=ONBOARD, ops_rate=OPS_RATE, checks=checks, late=late, ms27=ms27)
io.open(ARGS.out, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
if ARGS.quiet:
    print(json.dumps(dict(option=OPT, vibe=VL, total=tot_wp, raw=round(sum(raw_tot.values()), 2), fails=[(c["id"], c["n"], c["of"]) for c in checks if not c["ok"]]), ensure_ascii=False))
    raise SystemExit
print(f"운영안 {OPT} {OPTD['name']} · 바이브 {VL} — 원래 추정 {sum(raw_tot.values()):.1f} MM → 반영 {tot_wp} MM")
print("총 공수", tot_wp, "MM =", round(tot_wp / 12, 1), "FTE 평균")
print("과제별", tot_task)
print("역할별 합/평균/피크")
for r in ROLE_IDS:
    print(f"  {r:8} {tot_role[r]:6.1f} MM  avg {avg[r]:4.2f}  peak {peak[r]:4.2f}  " + " ".join(f"{x:4.1f}" for x in dem[r]))
for c in checks:
    print(("OK " if c["ok"] else "!! ") + c["label"], f"{c['n']}/{c['of']}", c["detail"][:6])
