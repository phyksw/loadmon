# 검토 — AL-1 자율 설계·해석

[검토 요약](README.md) · [AL-1 단계 계획](../AL-1_단계계획.md) · 2026-10-26 · (추정) = 계산한 값

**총평**
'26 4Q~'27(S0~S2)은 v4 근거가 있어 대체로 실현 가능하지만, CAE 1명·LIC_THERM·브리지·야간 실행 위치처럼 여유가 0인 고리가 여럿입니다. 가장 큰 문제는 '28(S3·S4)로, 이월 4건·광학 개발·A2 가 겹쳐 AL-1 만으로 AI 월 약 1.2명분이 필요한데 3과제 AI 공급은 월 약 0.6명분이고, 부족을 메울 첫 레버인 4명안은 v4 가정표의 '새 인원 한도 3명 확정(2026-10-22)'과 충돌합니다(이 검토 뒤 덱·데이터에서 뺐습니다). KPI 는 정의에 따라 판정이 갈립니다 — 'L/T 0.1hr 全도메인'은 기계 시간을 넣으면 열 CFD·광학 공차에서 성립하기 어렵고, 채택률 30%/50% 는 분모가 없으며, 야간 월 100시간은 라이선스 용량보다 A9 가 큐를 채우느냐에 달렸습니다. 업체 쪽 공식 MCP 는 Ansys 2개(Alpha)뿐이라 공수 절감이 거의 없고 실익은 계약 포함 여부가 미확인인 optiSLang·HPS·SimAI 와 ZOSPy 에서 나오며, '29~'30 은 운영이 새 인원 약 2명분을 묶으므로 설계안 생성 v1 은 최적화 중심으로 좁히고 AL-4 통합 공수는 확정 전까지 빼는 편이 맞습니다.

## 단계별 현실성 문제
| 단계 | 문제 | 심각도 | 근거 | 제안 |
|---|---|---|---|---|
| S0 | 'L/T 0.1hr(×40)' 산식이 아직 없음. 0.1hr 는 6분이라 기계 실행(솔버)을 넣으면 EM 도 모델 크기에 따라 빠듯하고, '28 全도메인(Icepak CFD·광학 공차·최적화)에서는 성립이 어려움. 야간 운영이면 의뢰→결과가 하룻밤 | 높음 | 계획 open_issues(AS-IS 4hr 은 사람 작업 포함, elapsed_hr 는 기계 시간, 19:00→07:30 과 충돌). 3D 전자기·CFD·공차 몬테카를로는 실행만 수십 분~수 시간이 흔함(업계 일반, 추정) | 10/30 합의(M-CTD-03)에서 ×40·97.5%↓ 판정 기준을 '사람 접촉 시간'으로 정하고, 기계 실행·회신 시간은 목표 없이 도메인별로 보고 |
| S0 | '28 AI 부족을 메우는 첫 레버가 '26.11.15 4명안인데, v4 가정표는 '새 인원 한도 3명 — 사용자 결정(2026-10-22) 확정'. 4명안이 닫히면 '28 AI +1 을 해도 3과제 AI 부족은 약 16 MM | 높음 | v4 가정과 출처 표, 통합본 load28(부족 27 MM → AI +1 이면 16, 4명안 + AI +1 이면 약 1) | 3명을 기본으로 S3·S4 범위를 다시 짬(변경 제안 2·12·13). '28 AI +1 은 '27.6.30 에 한도를 다시 정할 때만. 4명안은 뺌(반영 완료) |
| S0 | 기한 경과 9건(공통 M-CTD-02 포함)과 EM 릴리즈(M-AL1-03) 완료가 미확인. 실사용이 11월로 밀리면 12/10 입력까지 실측 기간은 4주 안팎 | 중간 | 원장 기한('26.10.25 대조), A·B [필수] 항목만 최대 188%('26.9.26 점검) | 10/27 확인 때 '실사용 시작일'을 같이 기록. 11월 이후면 Gate 1 은 5건 하한만 지키고 골든셋 확대는 '27 Q1 EM 보완(계획의 Gate 1 미달 분기)으로 |
| S0 | Ansys MCP 2종의 0단계 적합성 시험(사내 AEDT·Mechanical 버전)이 S0 범위에 없음. ansys-aedt-mcp 는 0.3.0 부터 Python 3.13 필수, mechanical-mcp 는 지원 버전 미기재 | 중간 | R3 권고 2('26.11~12 에 마쳐야 1월 착수 WP 에 반영), 업체 검증 cae(0.3.0 breaking 10-21, 3.3개월 11회 릴리즈) | DRI 개발자(기존)가 '26.11~12 에 서버당 1~2일. A·B 몫에서는 뺌 |
| S0 | 라이선스 신청(M-CTD-02 '26.10.23) 제출 여부 미확인. Icepak·Fluent(LIC_THERM)는 '27 상반기 신청 가정이라 11/13 회신 묶음 밖 | 중간 | model27 deps(LIC_THERM 확보 5월 = 필요 5월, 여유 0). 증분 구매는 견적·품의로 수개월(추정). Synopsys 인수 뒤 라이선스 정책 변경 여부 미확인(업체 검증 cae gaps) | 10/27 에 제출 여부 확인. LIC_THERM·HFSS 배치(D-VV3-04)를 같은 패키지로 묶고, 서비스 계정 야간 사용 허용 여부도 같이 질의 |
| S1 | CAE 자동화 엔지니어는 사내 전환 1명이고 A3·A5·H4·H5 를 모두 맡음. 4월 CAE 수요 1.94명분 vs 공급 1.8명분. 전환이 늦으면 A3('27.1~4)·구조 파일럿('27.5~6)이 바로 밀림 | 높음 | v4 CAE 연 15.0 MM·가장 많은 달 1.94명분, model27 supply_m(4월 1.8)·램프 [0.6, 0.85], R6 전환배치 1/2/4개월(사업부 간 이동이나 정기 인사 대기면 4개월) | 11/15 에 대상자 지정, 같은 사업부 안 전환으로 리드 1개월. 1월에 못 오면 A3 를 H4 보다 먼저(파일럿 마일스톤 우선) |
| S1 | 브리지 미결정 + 장비 불일치(빅플랜 p.21 'RTX 5080 6대 + A6000 9대' vs v4 'RTX PRO 6000 9장'). 브리지가 없으면 M-AL1-06 +3·07 +5·08 +2개월 | 중간 | v4 브리지 지연표, 계획 open_issues(GPU 구성). R5 7장: 추출·RAG 는 로컬 적합도 '상'이라 al1-entity 는 27B급 1장으로도 가능(추정) | 11/15 에 브리지 장비 모델·메모리 확인, al1-entity 용 27B급 모델만 먼저 올림. 큰 모델은 INF-1 뒤 |
| S1 | A3 6.7 MM 은 '도메인 확장 표준'(CAE 2.5 + AI 1.8 + 도메인 1.6 + 평가 0.6) 가정이고 v4 에서도 '확인 필요'. 같은 표준이 A5·광학·H4·H5·H9 에 그대로 복제됨 | 중간 | v4 가정표, EM 1차 구축 '26.3→'26.10(7개월), R1(도메인 확장 5회 반복 = 자연 실험) | '27.4 A3 종료 때 실측 MM 으로 표준을 다시 잡아 A5('27.5 착수)·광학('28) 공수에 바로 반영 |
| S1 | ansys-mechanical-mcp 는 Alpha(0.3.0 에서 도구 이름 변경)이고 run_python_code 를 끄는 옵션이 없음 | 낮음 | 업체 검증 cae, R3 V-5('27 순효과 −0.4~0 MM) | 계획대로 쓰되 절감은 0 으로 잡음. 허용 스크립트 프록시 +0.2~0.4 MM(추정)을 C12 에 넣고, 막히면 PyMechanical 직접(계획 그대로) |
| S2 | 야간 실행 위치(HPC 클러스터·스케줄러인지 워크스테이션인지)가 미확인이고 v4 인프라에 CAE 계산 노드가 없음. HPC_NIGHT 는 '27.6 협의 '가정' | 높음 | model27 deps HPC_NIGHT(가정), 업체 검증 cae gaps('사내 HPC 스케줄러 종류와 CAE 배치 실행 위치 미확인'), v4 인프라표(INF-1 추론·INF-2 시뮬·학습 GPU 뿐) | '27.3 까지 확인. 없으면 CAE 계산 노드를 '27.8 '28 예산 기안에 넣음(금액 미산정, 견적 필요). INF-2 야간 공유는 VV-1 학습과 겹침(추정) |
| S2 | 광학 무인 실행 경로가 검증되지 않음. ZOS-API 는 Windows 전용이고, 무인 실행에 필요한 Standalone 모드가 Enterprise 라이선스에서도 막혔다는 보고가 1건 있음. CODE V 는 Keysight 로 공급사가 바뀌었고 자동화 API 미확인. '광학 해석' 범위(순차 설계·비순차 미광·공차)도 미정 | 높음 | 업체 검증 eda(ZOS-API, zemax-mcp-server IsValidLicenseForAPI=false, CODE V 2026), 계획 open_issues(광학 API 는 CAE 필수 역량 밖) | '27.8~9 기존 라이선스로 ZOSPy Standalone 1일 시험 + 범위 확정 → '27.8 LIC_OPT 견적 조건에 반영(변경 제안 10) |
| S2 | '27.12 에 실측 수집 계획서·상관 정의서 초안·'28 반기 계획·시험 슬롯 확약·RW 가 A·B 에 몰림. 모두 v4 21.6 MM 밖의 일이고, 하반기 A·B 개발 참여는 0.8명분으로 잡혀 있음 | 중간 | 계획 S2 resource('v4 21.6 MM 밖'), v4(A·B 가동률 97%, 10월 105%) | 계획서·정의서 초안을 '27.11 로 당기고 11~12월 A·B 개발 참여를 0.8 → 0.4명분으로 |
| S2 | '28 AI +1 을 경력으로 뽑으면 '27.7 품의 → 입사 '28.1(보수 '28.4) + 램프 4개월 → '28 H1 실효 약 1.5~4.4 MM(추정). S3 가 기대하는 '28.1 투입 효과가 안 나옴 | 중간 | R6(착수→입사 6/9개월, 램프 손실 1.65 MM/인), model27 램프(경력 [0.3, 0.5, 0.7, 0.85], 전환 [0.6, 0.85]) | 사내 전환을 기본으로('27.6.30 결정 → '27.10.31 확정, H1 실효 약 5.5 MM, 추정) |
| S2 | v4 는 CAE 배치 라이선스 증분을 '27 Q3 부터(0.5억) 잡았는데 야간 배치(A7·A8)는 '28 로 넘어감 | 낮음 | v4 비용표('야간 배치부터', '27 4,980만) | 증분이 A5·H4·H5 주간 배치용인지 확인. 야간 전용이면 '28.1 로 옮김('27 증분 현금 약 0.5억 감소) |
| S3 | 한 반기에 A6·A7·A9 이월, 광학 개발, VP 구조 지원, '28.3 기준서·정의서가 겹침. AL-1 AI 월 약 1.2명분 vs 3과제 AI 공급 월 약 0.6명분(플랫폼 운영 제외), 4월 피크 3명분+ | 높음 | 계획 S3 resource(17.6 MM, AI 7.1), 통합본 load28(AI 수요 38 vs 확정 공급 11 MM) | AI +1 이 있어도 3과제 부족 16 MM 중 AL-1 몫 약 6~7 MM(추정, AI 수요 비중 42%)을 '29 H1 로. A2 5.0·광학 파일럿 2.5 이동(변경 제안 12·13). 3명 그대로면 더 넘겨야 함(요약 2장) |
| S3 | 야간 월 100시간은 라이선스 용량보다 큐 물량이 관건. 단건 EM·구조는 수 분~수십 분이라 단건만으로 100시간을 채우려면 월 수백 건이 필요(추정). 실제로 채우는 건 A9 DOE·최적화와 열 CFD·광학 공차라서 A9 β('28.4)가 늦으면 곧 미달 | 중간 | v4 라이선스 가정(솔버 2 + HPC 팩) → 2 Job × 12시간 × 22일 ≈ 월 528시간 용량(추정), 계획 S3 위험('A9 β 지연 → 단순 실행만') | '28.3 물량 표를 원천별(단건·DOE·열·광학)로 역산. KPI 에 완료 건수·격리율을 같이 두고, 측정은 flexlm_exporter 로 |
| S3 | 야간 큐 입구인 al1-g6(6단계 승인)을 해석 PL 1명이 맡음. 부재 시 큐가 빔. 아침 판정도 같은 해석 DRI 팀 몫 | 중간 | 로스터 al1-g6 = 해석 PL, model27 dom_cap(해석 4명 가정 → 30% = 1.2명분) | '28.3 판정 기준서에 대리 승인자와 승인 배치(예: 주 2회)를 명시 |
| S3 | 광학 개발('28.1~7) 담당이 비어 있음. 광학 API 는 CAE 필수 역량 밖이고, AI 는 가장 부족한 역할이며, 시민개발은 플러그인에 기준 5% 만 맡을 수 있음 | 중간 | v4 CAE 필수 역량(PyAEDT·PyMechanical·PyFluent), R6 4-3(플러그인 0.05, 셋업 매크로 0.3), dom_cap 광학 10명 | 플러그인 골격(ZOSPy 래퍼·큐 연결)은 CAE, 셋업 매크로·골든셋 판정은 광학 시민개발(30% 안)로 나눠 '27.12 RW 에 배정 |
| S4 | S4 도 AI 7.1 MM(월 약 1.2명분)이라 부족이 이어짐. A2(5.0 MM, AI 중심)는 PLM 창구(VV-3 H2, '28 H1 AI 부족 속 2.7 MM) 뒤라 두 번 밀릴 수 있음 | 높음 | 계획 S4 resource, open_issues(H2 → A2 순서), 업체 검증(Teamcenter 공식 MCP 없음 → H2 직접 개발 유지) | A2 를 '29 H1 기본안으로. '28 H2 에는 PLM 없는 색인(A2a)만 작게 |
| S4 | 全도메인 L/T 97.5%↓ 에 광학이 들어가는데, 광학 릴리즈 '28.10 부터 11.30 마감까지 실측은 1~2개월뿐 | 중간 | 통합본 gates 위험('광학 실측 1~2개월뿐'), S0 산식 문제 | Gate 2 L/T 는 접촉 시간 기준으로 내고 광학은 파일럿 실측 건수를 밝혀 보조로. 광학이 '29 H1 로 가면 3종으로 제출(계획의 AI 미증원 분기) |
| S4 | 해석-실측 대조 N 과 보완설계 채택 N 이 '28.3 까지 미정이고, 실측 공수는 v4·'28 87 MM 밖(3과제 3.7 MM 추정, AL-1 은 미산정). 채택 기록은 L2 정규 5개월('28.7~11) 안에 실제 설계 반영(ECR) 주기를 거쳐야 함 | 중간 | 통합본 issues·load28, VV-3 계획(비교 쌍 '27 H2 10~20, 시제품 1사이클이 '28 안에 안 끝날 수 있음) | N 은 목표로 정하지 말고 '28 시험 계획(시제품 차수 × 시험 항목)에서 역산해 '27.12 계획서에 확정. 채택은 '후보 채택'과 'ECR 반영'으로 나눠 셈 |
| S4 | M안(HGX H200 5.7억) 판단 근거에 '야간 정규 운영'이 들어 있으나, 야간 루프는 결정론 단계 + LLM 감시 구조 | 낮음 | 계획 S3 위험(결정론 단계 우선), R5 7장(고정 워크플로우 로컬 적합도 '상'), v4 인프라 문구 | M안 근거에서 야간 운영을 빼고 S5 조건 생성 평가 결과로만 판단 |
| S5 | 설계안 생성 v1 은 반기에 신규 약 8 MM 인데, '29 에는 AL-1 운영 월 약 1명분 + 공통 플랫폼 1.15명분으로 새 인원 3명 중 약 2명분이 운영에 묶임(이관 0% 가정) | 높음 | 계획 resource_outlook '29, v4 플랫폼 운영 1.15명분 | v1 을 최적화 중심(DOE·BO + 대리모델 선별)으로 좁히고 LLM 조건 생성·재축적은 v2('29 H2~)로. 신규 약 4.5 MM(추정) |
| S5 | 야간 LLM 조건 생성(RAG→생성→자기검증)은 C3 라 로컬 모델이 맡는데, 다단계·장시간 과제에서 로컬은 프런티어보다 약 28%p 낮음 | 중간 | R5(TB4.0 Opus 5.5 65.15 vs GLM-5.3-Flash 37.37, 장시간 자율 실행 로컬 적합도 '하') | LLM 은 템플릿·변수 범위 제안까지만, 탐색은 결정론 최적화기로. 모델을 바꿀 때마다 회귀 평가 |
| S5 | Gate 2 조건부 분기에서 v1 을 '29.12 로 옮기면 '29 H2 채택률 30% 측정 기간이 0 인데, M-AL1-12 이동은 분기 표에 없음 | 중간 | 계획 S5 위험, 통합본 gate_branches | 분기 표에 'M-AL1-12 → '30 H1'을 명시 |
| S6 | 채택률 산식이 없음('28.3 확정 예정). 분모를 '생성 후보 전체'로 하면 30% 는 어렵고 '의뢰 건'이나 '아침 검수 상위 k개'로 하면 쉬워짐. 정의가 곧 판정 결과. 공개된 업계 기준값 없음(미확인) | 높음 | 원장 M-AL1-12·13(산식 원본 없음), 빅플랜 p.16(값만 있음) | '28.3 에 분모 = 의뢰 건(채택 후보 1개 이상), 보조 지표 = ECR 반영 건으로 정함. '28.7~11 L2 기준선으로 Gate 2 에서 30%/50% 를 다시 확인 |
| S7 | AL-4 는 3과제 밖이고 '개발팀 단독 착수 불가'(빅플랜 p.33)인데, S7 13.1 MM 에 AL-4 통합 시험 3.0 MM 이 들어 있음 | 중간 | 계획 S7 resource·depends_on | 기본 계획에서 빼고 계약 스텁만(약 0.3 MM, 추정). '29 4Q RW 에서 AL-4 가 확정되면 추가 |
| S8 | 이관 50%면 운영 7.3 MM 중 약 3.7 MM(반기, 월 약 0.6명분)이 DRI 팀으로 감. 해석 팀(4명 가정)이 받으면 30% 상한 1.2명분의 절반이고, 코드 유지보수(Python·LangGraph·MCP)는 DRI 팀 역량 밖 | 중간 | 계획 S8 resource, model27 dom_cap, P0 30% 상한(빅플랜 p.16) | 이관 범위를 '큐 관리·판정·1차 대응'으로 정의하고 코드 유지보수는 플랫폼 쪽에 둠. '28.12 이관 비중 안건에 이 정의를 포함 |

## 업체 옵션
| 단계 | 업체·제품 (상태) | 계획에서 바뀌는 것 | 공수 변화 | 비용 | 위험 | 추천 |
|---|---|---|---|---|---|---|
| S0·S2 | Ansys [ansys-aedt-mcp 0.3.1](https://pypi.org/pypi/ansys-aedt-mcp/json) (Alpha, 2026-10-23. [0.3.0](https://github.com/ansys/pyaedt-mcp/releases) 2026-10-21 부터 Python 3.13 필수) | EM 운영 계층(A1)은 교체하지 않음. 사내 AEDT 적합성 시험을 '26.11~12 로 당기고 A5 Icepak 에만 씀 | 런타임 분리 +0.1~0.2 MM(추정). 절감 A1 0.03·A5 0.08 MM(R3 V-4) → '27 순 −0.5~−0.2 MM(R3 V-5) | 무료(Apache-2.0). 솔버·HPC 라이선스는 그대로 소모 | 3.3개월에 11회 릴리즈, run_python_code 임의 실행, gRPC 인증 설명 없음, SIwave·EDB 미지원 | 시범 — Icepak 한정. 절감은 0 으로 잡고 벤더 API 추종 가치만 봄 |
| S1·S2 | Ansys [ansys-mechanical-mcp 0.3.0](https://github.com/ansys/pymechanical-mcp) (Alpha, 2026-10-14, 확인 2026-10-26) | A3 세션·solve·export 도구 계층(v4 그대로) + 허용 스크립트 프록시 추가. A5 thermal 은 A3 연결 재사용 | 프록시 +0.2~0.4 MM(추정). 절감 A3 약 0.23 MM(R3 V-4) → '27 순 −0.4~0 MM(R3 V-5) | 무료 | 0.3.0 도구 이름 변경, 지원 Mechanical 버전 미기재, 자체 인증·읽기 전용 모드 없음 | 도입(조건부) — S0 적합성 시험을 통과할 때만. 실패하면 PyMechanical 직접 |
| S1 | Stacklok [ToolHive v0.56.0](https://github.com/stacklok/toolhive) (OSS 0.x, 2026-10-22) | run_python_code 를 격리 컨테이너 안에서만 실행(프록시 대안, C12 범위) | 샌드박스 몫 −0.2~0.4 MM(추정) | OSS 무료 | 0.x 라 변경이 잦음, 기본 검증 정책이 warn, 라이선스에 묶인 AEDT 세션은 컨테이너 격리가 어려움(추정) | 시범 — Mechanical 만 |
| S1 | Ansys [Engineering Copilot](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/copilot_ug/copilot_ug_requirements.html) (GA, 확인 2026-10-26) | 새 CAE 인원 적응 기간에 C0 일반 질의만 가능 | ≈0 | AI+ 라이선스 조건, Copilot 자체는 추가 비용 없다는 문구 | 인터넷 필수, [사용자 고지](https://ansysgpt.ansys.com/ansysgpt-user-notice/)에 제3자 제공자 조항·수출통제 정보 입력 금지 → 정보보안 승인 1건 추가 | 안 씀 — 승인 공수가 효과보다 큼 |
| S1·S5 | Ansys [Mesh Agent·GeomAI (2026 R1)](https://news.synopsys.com/2026-03-11-Synopsys-Launches-Ansys-2026-R1-to-Re-Engineer-Engineering-with-Joint-Solutions-and-AI-Powered-Products) (Mesh Agent 'exploratory use', 2026-03-11) | 없음. 메시 재시도 규칙은 A3·A7 에서 직접 만듦 | 0 | 미확인 | GUI 대화형, 처리 위치·배치 호출 미확인, 사내 2026 R1 이상 필요 | 관찰 — GeomAI 는 S5 착수 전에 재평가 |
| S2 | Synopsys AgentEngineer CAE 열 에이전트 (발표만. [2026-07-26](https://news.synopsys.com/2026-07-26-Synopsys-Showcases-Comprehensive-Autonomous-Engineering-Workflows-from-Silicon-to-Systems,-Developed-with-NVIDIA-Technology) 'H2 2026', [2026-09-28](https://news.synopsys.com/2026-09-28-Synopsys-Powers-Autonomous-Engineering-with-a-Broad-Portfolio-of-Long-Horizon-Agents-and-Autopilot-Platform) 전체 'end of 2026') | GA·온프렘이 확인되면 A5(Icepak·PyAEDT) 셋업·후처리 일부를 대체 | A5 5.2 MM 중 −0.5~1.5 MM(추정, 조건부) | 미공개 | 평가 경로가 Microsoft Discovery(클라우드)라 C3 불가, LiDAR 모듈 열해석 적합성 미확인 | 관찰 — 확인 시점을 '27.6.30 → '27.3 으로 당김 |
| S2·S3 | Ansys(Synopsys) [Zemax ZOS-API](https://developer.synopsys.com/docs/zemax) (GA, 확인 2026-10-26) + [ZOSPy 2.2.0](https://pypi.org/pypi/zospy/json) (MIT, Stable, 2026-09-21) | A11 API 범위를 ZOSPy + Standalone 모드로 정함. '27.8~9 기존 라이선스로 1일 시험, LIC_OPT 견적 조건에 Standalone 허용·동시 인스턴스·서비스 계정 실행을 명시 | 래퍼 −0.3~0.5 MM(추정), 시험 +0.05 MM(추정) | ZOSPy 무료, OpticStudio 는 연 구독(정가 미확인) | Standalone 이 Enterprise 에서도 막혔다는 [커뮤니티 보고](https://github.com/webworn/zemax-mcp-server) 1건, Windows 전용이라 야간 노드도 Windows, 학술 그룹 유지 | 도입(조건부) — Standalone 시험 통과 시 |
| S2 | 커뮤니티 [zemax-mcp-server](https://github.com/webworn/zemax-mcp-server) (10커밋, Inactive, 확인 2026-10-26) | 도구 목록 설계 참고만 | 0 | 라이선스 불명확(LICENSE 404) | zemax_eval 임의 실행, 헤드리스 미검증 | 안 씀 — 코드 재사용 금지 |
| S2 | Keysight [CODE V 2026 AI Start Expert](https://www.keysight.com/blogs/en/tech/sim-des/code-v-faster-optical-design-ai-driven-starting-points) (GA, 확인 2026-10-26) | CODE V 를 쓰면 LIC_OPT 견적처가 Keysight 로 바뀜 | 0 (가시광 굴절·축대칭 한정이라 근적외 LiDAR 에는 해당 없음, 추정) | 미확인 | 자동화 API 언급 없음, 공급사 변경 | 안 씀 — CODE V 가 주 툴이면 자동화 API 를 확인한 뒤 재판단 |
| S2·S3 | [COMSOL MCP Server](https://www.comsol.com/press-release/system-level-modeling-and-agentic-ai-take-the-spotlight-in-comsol-multiphysics-version-2027-14722) (Multiphysics 2027, 발표만, 2026-09-16) | 사내에 COMSOL 이 있을 때만 해당 | 0 (보유 시 T1 검증 0.72 MM 이 붙음, R3) | COMSOL 라이선스 | 출시 전, 도구·실행 위치 미공개, 코드 실행 | 안 씀 — 보유 확인 전까지 |
| S3 | Ansys [Zemax OpticStudio 2026 R1 NEST·Requirements Editor](https://ansys.synopsys.com/blog/whats-new-ansys-optics-2026-r1) (NEST GA, Editor 'Coming Soon', 2026-04-16) | 광학 공차 셋업 자동화 후보 | API 로 노출되면 −0.2~0.4 MM(추정), 지금은 0 | 기존 구독 | ZOS-API 노출 여부·출시일 미확인 | 관찰 |
| S3·S4 | Ansys [HPS 1.4.0](https://ansyshelp.ansys.com/public/Views/Secured/hpcplat/v140/en/rep_ug/hps_compatibility.html) (GA, 확인 2026-10-26) + [PyHPS 0.13.0](https://pypi.org/project/ansys-hps-client/) (Beta, 2026-08-10) | A7 제출·감시·회수 계층을 HPS 로. 격리·롤백·al1-g6·라이선스 상한은 직접 만듦. S5 회로 SI/PI 야간 큐(AEDT·SIwave 네이티브)에도 씀 | A7 −0.5~1.0 MM, HPS 운영 MLOps +0.3~0.5 MM/년(추정) | 과금 조건이 문서에 없음, 계약 포함 여부 미확인 | DB 3종이 들어간 무거운 스택, [공개 레지스트리 pull](https://ansyshelp.ansys.com/public/Views/Secured/hpcplat/v140/en/hps_dg/core_deployment_overview.html) → 사내 미러 필요, 사내 스케줄러 유무 미확인, '28 MLOps 가용 약 0.2명분 | 시범(조건부) — 계약 포함 + 사내 스케줄러가 있을 때. '27.10~12 PoC |
| S3·S5 | Ansys [optiSLang 2026 R1](https://ansys.synopsys.com/en-gb/webinars/ansys-2026-r1-ansys-optislang-whats-new) (GA) + [PyOptiSLang 1.7.0](https://pypi.org/project/ansys-optislang-core/) (Beta, 2026-09-29) | A9 al1-optimizer·doe-planner 엔진을 구매로 바꾸고 VV-3 H12 와 공용. '27.10~12 CAE 여유로 Optuna 와 비교 PoC. OpticStudio 결합은 근거 미확인 | A9 −0.8~1.3 MM, 학습·래퍼 +0.3~0.5 MM(추정) | 견적. 기존 계약에 있으면 순효과가 커짐 | PyOptiSLang Beta, CAE 필수 역량 밖, Ansys 종속, 동시 Job 수는 솔버 라이선스 수로 제한 | 시범 → 계약에 포함돼 있으면 도입 |
| S3 | [Optuna 5.0.0](https://pypi.org/project/optuna/) (2026-09-07) · [BoTorch 0.18.1](https://pypi.org/project/botorch/) (Beta, 2026-06-08) · SMT·OpenMDAO (OSS) | A9 직접 개발 기준선(현 계획). optiSLang PoC 의 비교 대상 | 기준(A9 2.6 MM 그대로) | 무료 | Optuna 5.0 은 메이저 변경이라 버전 고정, 강건성·MOP 자동 선택·HPS 연동은 직접 | 도입 — 기준선 |
| S3·S4 | FlexLM: 공식 MCP 없음 → flexlm_exporter + [Grafana 대시보드 3854](https://grafana.com/grafana/dashboards/3854) (확인 2026-10-26) | license_hours_used(야간 100h KPI)를 exporter 로 집계. 라이선스 풀 상한은 결정론 코드 | 구성 +0.1~0.2 MM(추정), 집계 코드를 직접 짜는 몫을 대체 | 무료 | lmstat 출력 형식이 벤더 데몬마다 다름 | 도입 — MCP 가 아닌 exporter 로 |
| S3 | IBM [lsf-mcp-server](https://github.com/IBMSpectrumComputing/lsf-mcp-server) (비공식 지원, 0.1.0 2026-02-25) · Slurm 커뮤니티 MCP | 작업 상태 조회만 대신함 | ≈0 | 무료 | 자격증명 평문 저장, kill·delete 쓰기 도구, 읽기 전용 모드 없음 | 안 씀 |
| S3 | LangChain [langchain.mcp](https://docs.langchain.com/oss/python/langchain/mcp) (langchain 1.4.7 2026-10-21, 네임스페이스 베타) | A7 LangGraph 오케스트레이터(M-CTE-03)의 MCP 연결 경로. 옛 adapters(2026-09-17 archived, mcp<2.0 고정)는 쓰지 않음 | R4 PoC −0.1~0.2 MM(추정) | 무료 | 베타 API 변경, FastMCP 3.x·4.x 병행 릴리즈 → 버전 고정·회귀 시험 필요 | 도입 — 버전 고정 |
| S3~S8 | [MCP 로드맵](https://modelcontextprotocol.io/development/roadmap) (2026-08-22 갱신, 날짜 약속 없음) · [Python SDK 보안 권고](https://github.com/modelcontextprotocol/python-sdk/security/advisories) (6건, 2026-09-28~10-05) | 야간 완료 알림을 Tasks·webhook 표준으로 바꿀 후보. ansys-common-mcp 가 mcp<3.0 전 범위를 허용하므로 lock 하한 지정 | 서버당 사양 개정 0.2~0.4 MM, SDK 재검토 연 0.3~0.6 MM(추정) — '28 공통 20 MM 에 없음 | 무료 | tools/call 재설계로 호환이 깨질 수 있음 | 관찰 — 재검토 공수만 '28 공통에 추가 |
| S4 | Ansys [Minerva 2026 R1](https://ansys.synopsys.com/ja-jp/products/connect/ansys-minerva) (GA, 온프렘 가능, 확인 2026-10-26) | A2 과거 해석 결과 색인·계보, 해석-실측 대조 목록 저장소 | A2 −0.5~1.0 MM, 대신 구축·운영 공수 발생(추정) | 견적 | PLM 과 역할·데이터 이중 | 안 씀 — 이미 계약에 있으면 재검토 |
| S4→S5 | Ansys [SimAI Pro·Premium Customer Hosted](https://ansys.synopsys.com/products/simai) (GA, 확인 2026-10-26) + [PySimAI 0.4.8](https://pypi.org/project/ansys-simai-core/) (Alpha, 2026-10-19) | '28 H2 야간 결과 30~100건으로 도메인 1개 대리모델 PoC → S5 에서 해석 전 후보 선별(license_hours 절약) | S5 대리모델 개발 −2~4 MM, PoC +0.5~1.0 MM(추정) | 가격 비공개. Customer Hosted 는 K8s 를 사내가 운영 | 망분리 라이선스 미확인, 도메인별 정확도 별도 검증, Premium SaaS 는 C3 불가 | 시범 — '28.6 착수 여부, Gate 2 에서 판단 |
| S5 | NVIDIA [PhysicsNeMo 2.2.2](https://pypi.org/project/nvidia-physicsnemo/) (OSS, 2026-09-11) | 대리모델을 직접 구축 | +2~4 MM ML + 운영(추정) | 무료 | 새 인원 3명에 ML 엔지니어 없음 | 안 씀 — ML 공급원이 정해지기 전까지 |
| S3~S5 | Synopsys [S&A AgentEngineer 로드맵](https://teratec.eu/media/wp-content/uploads/2026/06/6-Luc_Pontoire_Seminaire_IA_NAFEMS_Teratec_2.pdf) (발표만, L3 2027+·L4 2028+, 2026-06 업로드, 신뢰도 낮음) | 사내 코드를 도구 계층(MCP)과 판정·격리 경계로 얇게 짬. Gate 2 에서 build vs buy 재판단 | 0 | 해당 없음 | 'Confidential' 표기 자료, 연도가 '+'(이후) 표기 | 관찰 |
| S3·S5 | Siemens [Simcenter PhysicsAI](https://news.siemens.com/ko-kr/siemens-simcenter-summer-2026/) (GA, 2026-07-28) · [HEEDS 2510](https://blogs.sw.siemens.com/simcenter/?p=70083) (GA, 2025-11-20) · ESTECO modeFRONTIER 2026R1([VOLTA MCP 발표만](https://um26.esteco.com/agenda/proceedings/), 2026-06) | 없음 (optiSLang·SimAI 대안) | 0 (Ansys 결과 변환 공수가 붙음) | 견적, Simcenter X 토큰 풀 | HEEDS·Simcenter X 는 클라우드 named-user 인증이라 망분리와 충돌 가능 | 안 씀 — Ansys 묶음 계약이 없을 때만 비교 |
| S5 | Neural Concept([2023-06 글](https://www.neuralconcept.com/post/one-day-to-prod-a-customer-software-deployment-process)) · [PhysicsX](https://www.physicsx.ai/) · Monolith | 없음 (SimAI 대안) | 0 | 견적 | 온프렘 근거가 2023년 글뿐이거나 없음 | 관찰 — 온프렘 문의 전 보류 |
| S5 | [Optiland 0.6.3](https://pypi.org/pypi/optiland/json) (MIT, 2026-10-11) · RayOptics 0.9.10 (OSS) | 광학 후보를 야간에 대량 사전 선별 → Zemax 로 확인 | LIC_OPT 동시 Job 감소 가능(추정) | 무료 | Zemax 와 결과 차이(재질·비순차) | 관찰 — 판정에는 쓰지 않음 |
| 전체 | Dassault [3DEXPERIENCE Virtual Companions](https://www.3ds.com/newsroom/press-releases/dassault-systemes-expands-3dexperience-ai-native-agentic-platform-new-virtual-companion-skills-co-engineer-humans) (GA, OUTSCALE 클라우드, 2026-07-23) · Abaqus 커뮤니티 MCP | 없음 | 0 | 3DEXPERIENCE 구독 | 클라우드 전용이라 C3 불가. Abaqus MCP 는 CAE 를 띄워 둬야 해서 야간 무인에 부적합 | 안 씀 |

## 일정·인력 변경 제안
| 항목 | 지금 | 제안 | 이유 |
|---|---|---|---|
| 1. Gate 1·2 L/T 판정 기준 | L/T 하나, 접촉·기계를 따로 기록(산식은 10/30 합의) | ×40·97.5%↓ 판정 = 사람 접촉 시간. 기계 실행·회신 시간은 도메인별 보고(목표 없음) | 기계 시간을 넣으면 열 CFD·광학 공차·3D EM 에서 6분은 어려움(추정), 야간 회신은 하룻밤 |
| 2. 기본 인원 가정 | '26.11.15 3명안 vs 4명안 비교, 4명안이 '28 부족의 첫 레버 | 3명(확정)을 기본으로 '28 계획을 다시 짬. '28 AI +1 은 한도 재결정 선택지('27.6.30). 4명안은 뺌(반영 완료) | v4 '새 인원 한도 3명 확정'. 3명 그대로면 부족 27, Agent 6건 '29 이동 뒤 약 20, AI +1 까지 약 9 MM(요약 2장) |
| 3. '28 AI +1 경로 | 경력('27.7 품의) 또는 사내 전환('27.10.31) | 사내 전환 기본, '27.6.30 결정 | '28 H1 실효: 경력 1.5~4.4 MM vs 전환 약 5.5 MM(R6·model27 램프, 추정) |
| 4. Ansys MCP 적합성 시험 | '27 1Q(C12) | '26.11~12, DRI 개발자가 서버당 1~2일(사내 AEDT·Mechanical 버전 + Python 3.13) | 1월 착수 WP 에 반영하려면 필요(R3), A·B 는 188% |
| 5. LIC_THERM 신청 | '27 상반기 신청, 필요 '27.5 | '26.11.13 회신 묶음(D-AL1-00·D-VV3-04)에 합류, 늦어도 '27.2 회신 | 확보 월 = 필요 월, 여유 0 |
| 6. CAE 전환 대상자 | 11/15 결정 → '27.1 투입(리드 2개월) | 11/15 에 대상자 지정, 같은 사업부 안 전환(리드 1개월). 1월에 못 오면 A3 를 H4 보다 먼저 | CAE 1명이 A3·A5·H4·H5, 4월 1.94 vs 1.8명분, 전환 1~4개월(R6) |
| 7. AgentEngineer 열 에이전트 확인 | '27.6.30 중간 점검 | '27.3 (A5 착수 전) | A5 는 '27.5~9 라 6월 말이면 이미 절반 진행 |
| 8. 야간 실행 위치·계산 노드 | HPC_NIGHT '27.6 협의 가정, 인프라 항목 없음 | '27.3 확인, 없으면 CAE 계산 노드를 '27.8 '28 예산 기안에 | '28.4 시범 전에 심의·납기 기간이 필요 |
| 9. A7·A9 CAE 몫 | '27.6.30 '선행 검토' | '27.10~12 확정 배치: HPS·스케줄러 연동 PoC + optiSLang vs Optuna PoC(약 1.5 MM) | v4 '27 H2 CAE 여유 월 0.3~0.7명분, 역할이 맞음, '28 H1 부하 완화 |
| 10. 광학 선행 순서 | 견적 '27.8 → A11 '27.10~12(API 범위 '27.11) → 신청 '27.11 | ZOSPy Standalone 1일 시험·범위 확정 '27.8~9 → 견적 조건에 반영 → A11 '27.10 | 배치 가능 여부를 모른 채 견적·신청하면 '28.1 착수가 막힐 수 있음 |
| 11. '27.12 문서 묶음 | 실측 수집 계획서·상관 정의서 초안·'28 계획 모두 '27.12 | 계획서·정의서 초안 '27.11, 11~12월 A·B 개발 참여 0.8 → 0.4명분 | v4 밖 작업이 12월 A·B 에 몰림 |
| 12. A2 sh-design-kb | '28.7~11, 운영 '28.12 | '29 H1 기본안('28 H2 는 PLM 없는 색인 A2a 만). VV-3 H12 연결 '29 H1, H8 '29 H2 | '28 H2 도 AI 부족, PLM 창구(H2)도 AI 부족 속에 있음 |
| 13. 광학 개발·릴리즈 | 개발 '28.1~7, 파일럿 '28.8~9, 릴리즈 '28.10 | '27.10.31 AI 확정 결과로 분기. 미확정이면 '28.1~3 ZOSPy 배치 PoC(저강도, M-AL1-10 착수는 유지), 본 개발 '28.4~9, 파일럿 '28.10~11, 릴리즈 '29 H1. VV-3 H12 광학 위임·M-VV3-07 도 같이 이동 | AI 부족 16 MM, 광학 API 는 CAE 역량 밖 |
| 14. 야간 100h 판정 | '28.10~11 월 100h 2개월 연속 | 100h(승인 의뢰의 license_hours_used, flexlm_exporter 측정) + 완료 건수·격리율 병기. A9 β 가 늦으면 판정 월을 '28.11~12 로 | 물량은 A9·열·광학 같은 긴 작업이 채움 |
| 15. 설계안 생성 v1 범위 | '29.6, 신규 약 8 MM(조건 생성 2.0·재축적 1.5 포함) | v1 = 최적화 중심(DOE·BO + 대리모델 선별), LLM 은 의뢰 해석·리포트만. 조건 생성·재축적은 v2('29 H2~) → 신규 약 4.5 MM(추정) | 새 인원 약 2명분이 운영에 묶임, 로컬 장시간 격차 약 28%p |
| 16. Gate 2 조건부 분기 | v1 은 '29.12 로, M-AL1-12 는 '29 H2 유지 | 같은 분기에서 M-AL1-12 → '30 H1 | 측정 기간이 0 |
| 17. S7 AL-4 통합 | 3.0 MM 포함 | 스텁 약 0.3 MM(추정)만, '29 4Q RW 에서 AL-4 확정 시 추가 | 3과제 밖, 단독 착수 불가(빅플랜 p.33) |
| 18. 운영 이관 정의 | 이관 50%(추정) — 운영 7.3 중 3.7 MM | 이관 = 큐 관리·판정·1차 대응, 코드 유지보수는 플랫폼 쪽 | 해석 팀 30% 상한, 역량 |
| 19. '28 A·B | 110% 넘는 달에 C 투입 검토 | '28.6 에 C 투입 결정(Gate 2 준비 전) | AX 최대 3명, '28 3과제 A·B 몫 5.3 → 11.6 MM(통합본) |
| 20. CAE 배치 라이선스 증분 시작 | '27 Q3(0.5억) | 용도 확인 후 야간 전용이면 '28.1 부터 | 야간 배치가 '28 로 이월됨 |

## 새 의존·결정
| 언제 | 무엇 | 누구에게 |
|---|---|---|
| '26.10.27 | 라이선스 신청 패키지(M-CTD-02) 제출 여부 확인, LIC_THERM·D-VV3-04 합류 | A·B → IT·사내시스템(라이선스) |
| '26.11.13 (D-AL1-00 회신과 함께) | 기존 Ansys 계약 범위: optiSLang·HPS·SimAI·Minerva 포함 여부, 라이선스 방식(동시 사용/지정 사용자), 서비스 계정 야간 사용 허용, Synopsys 인수 뒤 정책 변경 | IT·사내시스템(라이선스) → Ansys(Synopsys) 영업 |
| '26.11~12 | Ansys MCP 2종 0단계 적합성 시험(사내 AEDT·Mechanical 버전, Python 3.13 런타임) → A3·A5 도구 계층 결정 | DRI 개발자 → 전사 AX 조직(C12) |
| '26.11.15 | 브리지 장비 모델·메모리 확인(빅플랜 p.21 vs v4 불일치) → 브리지에 올릴 모델 결정 | 전사 AX 조직, IT·사내시스템 |
| '27.3 | 야간 실행 위치(HPC 클러스터·스케줄러 / 워크스테이션) 확인 | IT·사내시스템 |
| '27.3 | Synopsys AgentEngineer CAE 열 에이전트의 GA·온프렘·MCP 여부 → A5 범위 | A·B → IT 경유 업체 문의 |
| '27.4 | A3 실측 MM 으로 도메인 확장 표준 재보정 → A5·광학 공수 | A·B, 해석 PL |
| '27.8 | LIC_OPT 견적 조건: ZOS-API Standalone 허용·동시 인스턴스·Windows 서비스 계정 실행. CODE V 를 쓰면 Keysight 견적 + 자동화 API 확인 | IT·사내시스템(라이선스), DRI 광학 팀 |
| '27.8 | optiSLang·HPS·SimAI 견적(계약에 없을 때) + 필요 시 CAE 계산 노드를 '28 예산에 반영 | 전사 AX 조직 → 예산 |
| '27.8~9 | ZOSPy Standalone 1일 시험(기존 라이선스) + 광학 해석 범위(순차·비순차·공차) 확정, ZOSPy·Optuna·flexlm_exporter 사내 미러 반입 | CAE 엔지니어·DRI 광학 팀, 정보보안 |
| '27.10.31 | '28 AI 확정 결과로 광학 개발 착수 월·A2 시점 결정 | 전사 AX 조직, DRI(C엔지니어) |
| '28.3 | 채택률 분모, 야간 100h 정의(승인 의뢰 license_hours), 측정 수단(flexlm_exporter), al1-g6 대리 승인자 | 해석 PL |
| '28.6 | SimAI Pro PoC 착수 여부(도메인 1개, 야간 결과 30건 이상) | 전사 AX 조직, 해석 PL |
| '28.12 (Gate 2) | build vs buy 재판단: AgentEngineer(L3·L4)·SimAI·optiSLang·HPS | Gate 2 심의 |
| '28~ 분기마다 | Ansys MCP·MCP SDK 재검토(연 0.3~0.6 MM, 추정)를 '28 공통 20 MM 에 추가 | 전사 AX 조직(CT) |
| '29 4Q (RW) | AL-4 착수 확정 여부 → S7 통합 공수 반영 | 전사 AX 조직, AL-4 소유 조직 |

## 그대로 둬도 되는 것
- '26.10.27 기한 경과 확인과 'Gate 1 직결 > 승인·보안 요청 > 나머지' 컷 규칙
- 접촉 시간·기계 실행을 산식 합의 전에 따로 실측하는 방식
- 근거 로그 100% 코드 강제, 격리(신뢰도<θ·재시도 3회), al1-g6 승인. 업체 도구를 들여도 이 경계는 사내에 둠(AgentEngineer 로드맵을 봐도 같은 경계)
- 플러그인 인터페이스 v1 '27.1 고정(A3·VV-3 H4 공용). H4 는 SIwave·EDB MCP 가 없어 pyedb 직접이므로 인터페이스는 MCP 유무와 무관하게 유지
- 열 플러그인 1벌(AL-1 소유, VV-3 H9 재사용)
- '28 야간 = L2(6단계 승인 + 아침 사람 판정)와 Gate 1 G1-EV-11 승인 요청
- 야간 루프 = 결정론 단계 + LLM 감시(R5 고정 워크플로우 로컬 적합도 '상')
- 외부 MCP 는 Ansys 공식 2개만, 사내 미러·버전·해시 고정, 막히면 PyMechanical 직접
- C3 는 온프렘 경로만. Engineering Copilot·Dassault Virtual Companions·SimAI Premium SaaS 는 쓰지 않음
- A9 를 '28 1Q 로 넘긴 판단(광학 확장 전에만 있으면 됨). 단 CAE 몫은 '27 H2 에 선행
- A2 를 PLM 창구 뒤에 두고, PLM 이 늦으면 A2a/A2b 로 나누는 대응
- 브리지 '26.11.15 결정, INF-1 이 늦으면 브리지 연장
- 실측 수집을 별도 줄로 두고 '27.12 계획서에서 확정하는 방식
- Gate 1 미달 분기('27 Q1 EM 보완, A3 착수 유지)
