# 검토 — VV-3 MBSE HW 선검증

[검토 요약](README.md) · [VV-3 단계 계획](../VV-3_단계계획.md) · 2026-10-26 · (추정) = 계산한 값

**총평**
S0~S2(PoC·해석 플러그인·RVTM v1)는 범위를 조금 좁히면 일정 안에 들어옵니다. 하지만 5년 성과를 정하는 세 KPI(시제품 3→1~2차수, 가상-실측 상관 80%, 수율 정합 90%)는 공수가 아니라 시제품 일정·쌍 표본 수·데이터 소유가 결정하는데, 셋 다 아직 누구에게도 확약돼 있지 않습니다. 사람 쪽 병목은 '28 AI(VV-3 혼자 반기 약 1.0명분인데 3과제 확정 공급은 연 11 MM), 이미 130%인 회로 팀의 판정·시험 시간, '27.7 이후 확약 0명분인 MBSE 세 가지입니다. 업체 제품으로 계획이 크게 바뀌지는 않습니다. C3 조건에서 쓸 PLM 공식 MCP가 없고(Windchill은 Azure 필수·BOM 도구 없음, Teamcenter·3DEXPERIENCE는 없음), SI/PI의 실제 기반은 aedt-mcp가 아니라 PyEDB입니다. 고칠 것은 MBSE 툴 결정을 '29 H1에서 '27.2로 당기기, '28 Agent 범위를 AI 증원 여부별로 미리 나누기, 상관·수율 KPI의 산식·표본·소유를 '27 안에 고정하기입니다.

## 단계별 현실성 문제
| 단계 | 문제 | 심각도 | 근거 | 제안 |
|---|---|---|---|---|
| S0 | P0 결재(기한 10/15)와 판정 기준서(10/8)·PLM 계정 신청(10/15)·보안 검토(10/23)가 기한 경과. P0 미승인이면 '27 VV-3 24.8 MM 조달 근거가 없음 | 높음 | 원장 D-VV3-05·P-VV3-01·03·05, 통합본 decisions | 10/27 확인 결과로 Gate 1 자료를 두 갈래로 준비(승인: 계획대로 / 미승인: H6만 '27.1, H4는 '27 Q2) |
| S0 | 골든셋(전·후 BOM + 실제 불일치) 마감이 10/30인데 PLM 계정이 없어 누가 BOM을 뽑을지 정해지지 않음 | 중간 | P-VV3-02 10/30, PLM 회신 11/13(추정) | 제안자 3명이 각자 PLM 권한으로 export해 사내 공유폴더에 둠(LLM 미사용). 골든셋 마감 11/13, 판정 12/15 유지 |
| S0 | 규칙 비교(품번·리비전·수량)는 PLM 내장 구조 비교가 이미 하는 일이라, 기준선 없이 재면 대체 MM이 부풀려짐. 운영 목표 'L2 60~80% 대체'는 LLM 요약을 포함한 값인데 PoC는 규칙만 잼 | 중간 | Windchill Compare to Part Structure(기존 기능), 2차보완보고 슬라이드 13, 판정 지표에서 LLM 제외 | 내장 비교를 기준선으로 1회 실행하고, 그보다 더 잡은 것(도면↔BOM 교차, 누락 변경)만 대체 MM으로. '28.10 운영 목표값은 규칙 기반 실측에서 다시 정함 |
| S0 | A·B 준비 24.5인일로 3과제 중 가장 많음. '26.9.26 기록 최대 188% | 중간 | 원장 P-VV3-01~09 effort 합, 준비 상한 약 95인일(추정) | MBSE 범위서(P-VV3-06) 초안은 '27.1 투입할 시스템 엔지니어가 쓰고 A·B는 검수만(−3~5인일, 추정) |
| S0→S1 | MBSE 툴 후보가 Capella·Cameo 둘뿐이고, 비교 기준에 사내 보유 요구·ALM 도구와 SysML v2 표준 API가 없음. 다기종 재판단이 '29 H1이라 1기종 모델과 H7을 만든 뒤에 바꾸게 됨 | 중간 | SysML v2 정식 채택 2025-06-30, Magic 2026x TWC SysML v2 API(제약 있음), Capella↔SysML v2는 '첫 단계'(vendor plm) | 12/11 범위서에 기준 4개(사내 보유·SysML v2 API·헤드리스 접근·비용)와 1D Echo Gen2 요구 원본 형식을 넣고, '27.2에 최종 결정 |
| S1 | 회로 팀은 이미 130%인데 '27.4 VV-3 몫이 판정 0.69명분 + 시민개발 0.3명분 ≈ 1.0명분(6명의 약 17%). v4의 'P0 30% 점검 통과(5/5)'는 기존 130%를 빼고 본 값 | 높음 | 빅플랜 p.26, model27 DOM_CIR 4월 0.69, v4 시민개발 '27.1~4 | 회로 DRI가 담당 1~2명을 지명하고 판정은 월 1회 배치. 골든셋은 기존 수작업 해석 재현(해석 대 해석)으로 신규 측정 없이. H4 회로 판정을 3월에 끝내 4월 H5 착수와 겹치지 않게 |
| S1 | HFSS·SIwave·Maxwell 배치는 '27.2, Icepak·Fluent는 '27.5에 필요한데 v4 비용표의 CAE 배치 라이선스 증분은 3·4분기(야간 배치)부터만 잡혀 있음 | 중간 | v4 비용표(Q3·Q4 각 2,490만, '야간 배치부터'), model27 deps LIC_HFSS·LIC_THERM | 11/30 투자심의 기안 때 상반기분 견적을 받아 '27 예산에 반영. 안 되면 상반기는 대화형 좌석을 야간에 쓰고 엔지니어 좌석과 충돌을 점검 |
| S1 | aedt-mcp 문서에 SIwave·EDB·3D Layout 언급이 0회. H4 SI/PI의 실제 기반은 PyEDB(Beta) | 중간 | ansys-aedt-mcp 도구 문서, PyEDB 0.85.0(2026-10-15) | H4 범위와 CAE 전환 인원 필수 역량에 PyEDB를 명시하고 버전 고정. P-VV3-08 체크리스트에 Python 3.13 venv(aedt-mcp 0.3.0)와 PI용 SIwave vs HFSS-PI 라이선스 추가 |
| S1 | MBSE 확보 0.5명분(1~3월 겸직 → 4~6월 DRI 팀 직접)으로 6개월 안에 Capella 시스템 모델과 RVTM v1을 만들어야 함. '27.7 이후 확약 0명분 | 높음 | v4 MBSE 수요 0.58 vs 확보 0.5, R6 MBSE 확보 난이도 '매우 높음'(채용 5~12개월) | M-VV3-10은 'RVTM v1 = 요구↔검증 링크 완결'로 지키고, Capella 모델은 HW 선검증 관련 하위 시스템만 '27.9까지. 시스템 엔지니어 1명 지명 |
| S2 | 공차 자동화의 입력은 도면 공차인데 도면 치수 추출(H1)은 '28로 이월됐고, 상용 공차 툴은 API·MCP가 확인되지 않음 | 중간 | v4 H1 '28 이월, H9 CAE 1.7 MM·3개월, vendor cae(CETOL·3DCS·EZtol) | H9를 '1D 공차 체인 + 몬테카를로 계산기 + 입력 템플릿'으로 명시하고 3D GD&T는 범위 밖으로 |
| S2 | 열은 AL-1 A5 β('27.7)에 묶여 있음. A5는 C3 처리 선행조건(필요 5월, 자체 온프렘 7월)을 브리지로 메우는 구조 | 중간 | model27 checks deps(A5 필요 5월·확보 7월) | H9 순서를 공차('27.7~8) → 열 연결('27.9)로 |
| S2 | exit의 '도메인별 10~20쌍'과 KPI의 '10~20쌍(합계)'이 다름 | 낮음 | plan S2 exit_criteria vs kpi_track | '27은 합계 10~20(도메인당 2~5)으로 문구 통일 |
| S2 | 쌍 정의(산식 초안 '27.12)보다 수집('27.7~)이 먼저 시작됨. 기존 시험 기록은 해석 조건·설계 리비전이 안 맞을 수 있음 | 중간 | plan S2 risks, 상관 정의서 초안 '27.12 | '27.9에 쌍 스키마(측정 항목·조건·허용오차·장비·리비전)를 먼저 동결하고 수집 |
| S2 | H11 수율 PoC의 데이터 제공처가 미정. ML은 VV-1 DRI 팀(인지 SW) 시간 0.2~0.25명분이고, 시제품 수율은 표본이 작음 | 높음 | plan S2 depends '수율·시제품 이력 데이터 제공처 (미정)', v4 ML 역할 | '27.6.30까지 품질·생산과 데이터 제공을 합의. PoC를 '공차 몬테카를로 → 조립·정렬 1차 수율 예측'으로 한정 |
| S2→S3 | 대상 기종 PM이 'VP 판정 = 시제품 발주 조건'을 받아들인다는 합의가 없음. 판정만 하고 시제품이 원래 계획대로 가면 차수는 줄지 않음 | 높음 | plan to_be '시제품 발주 전 VP 판정', 대상 기종은 '27.12 RW에서 고정 | '27.12에 대상 기종 PM과 'VP Pass면 계획 차수 2'를 문서로 합의 |
| S3 | '28 H1 VV-3 AI가 약 1.0명분인데 3과제 확정 공급은 연 11 MM(수요 37.9). VV-3 비례 몫은 연 약 3.3 MM(추정)으로 H2(AI 2.0) + H3(AI 1.6) 정도 | 높음 | 통합본 load28, v4 H2·H3·H7 AI 1.99·1.57·1.04 MM | AI 증원별로 '28 범위를 미리 정함(아래 일정·인력 표). '27.10.31 확정 전에는 'H2 + H3'를 기본안으로 |
| S3 | '28 H1에 'VP 대상 기종 시제품'에서 실측 20~40쌍을 모은다고 했는데, VP('28.6)가 발주 전 판정이면 그 시제품은 H1에 아직 없음 | 높음 | plan S3 scope·goal | '28 H1 쌍은 다른 진행 기종이나 같은 기종 이전 차수에서 모음. VP 판정 차수의 실측은 '28.9~11(추정)로 표기 |
| S3 | '26.10 PLM 신청은 PoC export용. 에이전트 서비스 계정, C3 라우팅, 변경 객체(ECR) 읽기는 2차 심사가 필요할 공산이 큼. MCP 서버 egress와 큰 도구 결과의 디스크 저장도 C3가 새는 경로 | 높음 | vendor mcpops(Agent SDK가 2.5만 토큰 넘는 결과를 파일로 저장, 사용자 위임 EMA 지원 클라이언트 0) | '27.6에 'PLM 읽기 MCP 보안 설계서'(읽기 전용, 범위 제한 계정 또는 사용자 위임, 감사 로그, egress 차단, STP는 경로만 반환, ECR·ECN 포함)를 내고 '27.12 승인 목표. 위임 직접 구현 +0.3~0.5 MM(추정) |
| S3 | 쌍당 시험 0.5~1인일은 EMC에는 작음(챔버 셋업·구성 변경). 시험 장비·챔버 보유도 미확인 | 중간 | plan S3 resource_drivers | EMC 쌍 1~2인일(추정)로 잡으면 +0.25~1.0 MM. 외부 시험소면 비용 별도 |
| S3 | VV-1도 '28 H1 이월 10.2 MM로 과부하라 VP 입력(센서모델·엔진 출력 '28.4~6)이 늦을 수 있음 | 중간 | 통합본 resource_bridge '28 H1 | VP 판정은 HW 4도메인만으로 성립시키고 VV-1 항목은 '있으면 포함' |
| S4 | 도메인별 80%를 10~20쌍으로 판정하면 관측 80%의 95% 신뢰구간 하한이 49~58%. 쌍 1~2개로 합·불이 뒤집힘 | 높음 | Wilson 구간: n=10 49~94%, n=20 58~92%, n=40 65~90% | '28.3 정의서에 연속 오차 지표(쌍당 여러 측정점), 도메인당 최소 n=20, 기준 사전 등록을 넣음. EMC는 참고 지표로 |
| S4 | 측정 마감 '28.11.30까지 VP 판정 차수의 실측 여유가 0~2개월(발주→제작→시험 3~5개월, 추정) | 높음 | VP '28.6, 마감 '28.11.30 | 조건부안(선행 지표 3종 + 다른 기종 쌍)을 기본 시나리오로 준비 |
| S4 | H12는 A9 운영 '28.7·광학 '28.10·KB '28.12가 한 창에 몰리고 가동이 '28.11. 마감까지 1개월이라 Gate 2 기여가 거의 없음 | 중간 | plan S4 depends | H12를 '29 H1(H8과 함께)로. 보완설계 실적은 'VP Fail → 설계 변경 반영 기록(사람 5단계 + 플러그인 결과)'으로 |
| S4 | 도면 치수 추출이 3개월('28.7~9). 한국어 표제란·주기와 사내 양식 정확도가 검증되지 않음 | 중간 | Werk24 한국어 미지원, eDOCr2 미검증(vendor plm) | '28.10 운영은 BOM만. 도면 치수는 '28 H1 INF-1 사전 시험(사내 도면 50~100장, 추정) 뒤 '29 H1 |
| S4 | 'ECR 이벤트로 실행'에는 PLM 쪽 구독·이벤트 설정(관리자 변경)이 필요한데 의존 목록에 없음 | 중간 | plan S4 exit '수동 작업 없이 ECR 이벤트로' | sh-data-query가 ECR 목록을 주기적으로 조회(폴링)해 실행. PLM 설정을 바꾸지 않음 |
| S4 | 추적성 100%를 1기종 링크 완결률로 좁혔음. 원안 범위와 다르고 ECR마다 유지 인력이 필요 | 중간 | 빅플랜 p.11, plan '1D Echo Gen2 기준은 추정' | Gate 1에 '1기종·링크 완결률' 정의를 기록하고 RVTM 유지 시간을 확약 |
| S5 | '29 H1 차수 확정은 VP 적용 기종의 시제품 단계가 끝나야 가능. 1기종(n=1)으로는 설계 재사용률 같은 요인과 구분되지 않음 | 높음 | M-VV3-08b, 기종별 시제품 기간 미확인 | '29 H1은 중간 지표(1차 시제품 합격·VP 사전 탐지율). 확정은 '29 H2 이후 2개 기종 이상에서 과거 평균 차수와 비교 |
| S5 | 3개 이상 기종 확대: 기종당 VP CAE 1.2·판정 1.2 MM('28 1기종 기준)에 새 RVTM까지. '29 MBSE 0.3·CAE 0.3~0.5명분의 공급원이 미정 | 높음 | plan S3·S5 resource_drivers | '29는 2개 기종으로. MBSE 공급원(지명 시스템 엔지니어)을 '28.6에 확정 |
| S6 | 全기종: 신규 기종이 연 6건(빅플랜 p.26 '26 과제 수, 추정)이면 VP CAE가 연 3.6~7.2 MM(자동화 50~0%)으로 '30 CAE 0.2~0.3명분(2.4~3.6 MM)보다 큼. 표준 편입 권한은 개발기획에 있음 | 중간 | plan '28 VP 1기종 CAE 1.2 MM, '30 resource | 대상을 '30.1 이후 시제품을 발주하는 신규 기종으로 좁히고, 판정 자동화율 목표를 '29 H2에 정함 |
| S7 | 수율 정합 90%는 산식·소유·데이터가 없음. '30 H2에 VV-3가 예측한 기종의 양산 수율이 나올지도 불확실(설계→양산 2~3년, 추정)하고 AF-4는 P2 | 높음 | 빅플랜 p.20(Yield Prediction AF-1/AF-4), 2차보완보고 슬라이드 7 | KPI를 '설계 단계 예측 vs 파일럿·시제품 1차 수율, ±X%p 이내 비율'로 정의하거나 소유를 AF-4로. '27.6.30 결정 |

## 업체 옵션
| 단계 | 업체·제품 (상태) | 계획에서 바뀌는 것 | 공수 변화 | 비용 | 위험 | 추천 |
|---|---|---|---|---|---|---|
| S0·S4 | PLM 내장 구조 비교: Windchill Compare to Part Structure·구조 비교 리포트 (GA 기존 기능, 이번 재확인 못 함). Teamcenter 대응 기능은 미확인. [PTC 도움말](https://support.ptc.com/help/wnc/r12.0.2.0/en/Windchill_Help_Center/PMStructureComparePartStart.html) (재확인 못 함, 2026-10-26) | PoC 판정 기준선. '28 H1 규칙 비교 일부를 내장 기능 호출로 | S0 +1~2인일, H1 −0.2~0.5 MM (추정) | 기존 라이선스 안 (추정) | 사내 PLM 미확인, API 호출 가능 여부 미확인 | 시범 |
| S0·S1 | Capella 7.1.0 (출시) + py-capellambse 0.8.1 (Production/Stable, Apache-2.0, 헤드리스). [Capella 릴리즈](https://github.com/eclipse-capella/capella/releases) (2026-10-26 확인), [capellambse PyPI](https://pypi.org/pypi/capellambse/json) (2026-01-20) | 없음 (H6 추적표 자동 추출·H7 모델 읽기의 기준안) | 파서 개발 없음 (R3 기준) | 0 | 지원 Capella 버전 미명시라 7.1에서 시험 필요. SysML v2 아님 | 도입 |
| S0·S1·S5 | CATIA Magic 2026x + Teamwork Cloud SysML v2 REST API (GA, 온프렘 TWC, createCommit·derived property 제약, MCP 없음). [No Magic 문서](https://docs.nomagic.com/SYSML2CM/2026x/standard-sysml-v2-rest-http-api-286557225.html) (2026-10-26 확인). SysML v2 정식 채택 2025-06-30: [sysml-v2-release](https://github.com/systems-modeling/sysml-v2-release) (2026-10-26 확인) | 툴 비교에 넣고 '27.2에 최종 결정, '29 H1 재판단은 없앰 | Capella로 갔다가 '29~'30에 옮기면 H7 접근 계층 재작성 1~2 MM (추정) | 5석 연 약 0.5억 (v4 보수안) + TWC 견적 | '100% 적합'은 업체 주장이고 문서에는 제약이 있음 | 관찰 → '27.2 결정 |
| S0·S3 | Cameo 커뮤니티 MCP: cameo-mcp-bridge (MIT, 162 도구, Groovy 임의 실행, 무인증 포트, CORS *). [GitHub](https://github.com/ajhcs/cameo-mcp-bridge) (2026-10-26 확인) | Cameo를 골라도 그대로 쓰지 않음 | 도입하면 T1 검증 0.45~0.65 MM이 절감보다 큼 | 0 | 코드 실행, 무인증 | 안 씀 |
| S1·S3 | Obeo AI for Capella (상용 MCP+API, GA·배포·가격 미기재, 시험 클라이언트 전부 클라우드 LLM). [Obeo](https://www.obeosoft.com/en/products/ai-for-capella/) (2026-10-26 확인) | H7 모델 도구 계층을 사서 씀 | 최대 −0.4 MM (추정) | 견적 | C3 모델은 온프렘 LLM 클라이언트로만 붙여야 함, Obeo 종속 | 관찰 ('27.2 견적·배포 형태 확인) |
| S1·S3·S4 | Jama Connect MCP 9.35 (GA, self-hosted 별도 애드온, LLM 비호스팅, 쓰기 8·읽기 6·검색 1). [Jama 데이터시트](https://www.jamasoftware.com/media/2026/05/Jama-Connect-MCP-Datasheet.pdf) (PDF 2026-04-28, 2026-10-26 확인) | 사내 보유 시 RVTM의 요구·검증 링크는 Jama에, Capella는 시스템 모델만 | 보유 시 H7 −0.5~0.8 MM (추정). 미보유면 도입·이관 비용이 더 큼 | Named Creator + Interchange + MCP Connector, 비공개 | 쓰기 도구가 기본 포함이라 읽기 허용 목록 필요 | 보유 시 시범, 미보유 시 안 씀 |
| S1·S3 | Siemens Polarion ALM 2606 (온프렘 custom LLM connector, MCP 없음) + peakflames PolarionMcpServers (MIT, 읽기 15 도구). [Polarion 2606](https://blogs.sw.siemens.com/polarion/polarion-alm-2606-whats-new-and-noteworthy/) (2026-05-28), [GitHub](https://github.com/peakflames/PolarionMcpServers) (2026-10-26 확인) | 사내 보유 시 H7 요구 조회·중복 점검을 로컬 LLM으로 | 보유 시 −0.2~0.5 MM, T2 검증 약 0.3 MM (추정) | Copilot 애드온 유료 (비공개) | 2512 Copilot은 고객 Azure라 C3 불가, 로컬 커넥터 지원 모델 미확인 | 보유 시 시범 |
| S1·S3 | IBM ELM 7.2·DOORS Next + Engineering AI Hub 1.1 (GA, MCP 없음, LLM 위치 미확인), PTC Codebeamer AI 1.0 (GA, LLM 위치 미확인, 커뮤니티 MCP MIT 19 도구). [IBM](https://www.ibm.com/new/announcements/new-ai-automations-for-model-based-systems-engineering) (2025-12-18), [IoT Now](https://www.iot-now.com/2026/01/19/154960-ptc-delivers-new-ai-functionality-for-software-driven-product-development-with-new-alm-releases/) (2026-01-19) | 사내 보유 시 OSLC·REST를 사내 MCP로 감싸 H7 요구 조회 | 보유 시 H7 일부 (추정), 미보유 0 | 비공개 | LLM 위치 미확인, 2025 DOORS AI는 IBM Cloud 시제품 | 보유 시 관찰, 미보유 시 안 씀 |
| S1 (H4) | Ansys PyEDB 0.85.0 (Beta, MIT). [PyPI](https://pypi.org/pypi/pyedb/json) (2026-10-15) | H4 SI/PI 사내 MCP 도구 4~6개(컷아웃·포트·SIwave 실행·결과)의 기반으로 명시 | 0.3~0.5 MM, H4 3.7 MM 안 (순증 없음, 추정) | 0 (SIwave·HFSS 라이선스 별도) | Beta이고 '26.9~10에 5회 릴리즈 → 버전 고정·회귀 시험 | 도입 |
| S1 (H5) | ansys-aedt-mcp 0.3.1 (Alpha, Apache-2.0, 0.3.0은 Python 3.13 필수 breaking). [PyPI](https://pypi.org/pypi/ansys-aedt-mcp/json) (2026-10-23), [도구 문서](https://aedt-mcp.docs.pyansys.com/version/stable/user_guide/tools_and_capabilities.html) (2026-10-26 확인) | H5 HFSS·Maxwell 세션·해석·export 계층 (v4대로). H4에는 쓰지 않음 | 3.13 venv +0.1 MM. 절감은 0으로 셈 (R3 수정값 H5 0.02~0.05) | 무료 | run_python_* 임의 실행, 1주에 breaking 2회 → 해시 고정·해석 VM 격리 | 도입 (버전 고정 조건) |
| S1·S3 | Ansys SIwave EMI Scanner·EMI Xplorer (GA, SIwave 포함 기능, 스크립트·API 언급 없음). [SIwave](https://ansys.synopsys.com/products/electronics/ansys-siwave) (2026-10-26 확인) | H5·hw-precheck EMC를 'Scanner 규칙 스크리닝 → HFSS·Maxwell 확인' 2단으로 | 보유하고 배치 호출이 되면 −0.2~0.4 MM (추정) | SIwave 계약 범위 확인 | 배치 호출이 안 되면 무인 실행에 못 씀 | 시범 ('27.4 H5 착수 때 호출 시험) |
| S1·S3 | Siemens HyperLynx DRC 2604 (GA, 규칙 90여 개 + Python 사용자 규칙). [Siemens 블로그](https://blogs.sw.siemens.com/electronic-systems-design/2026/04/27/whats-new-in-hyperlynx-2604/) (2026-04-27) | EMI Scanner의 대안 (둘 중 하나만) | −0.3~0.6 MM (추정) | 견적 | 입력 형식(ODB++·IPC-2581) 미확인, 사내가 Siemens EDA가 아니면 툴이 하나 늘어남 | 관찰 (사내 툴이 Xpedition·HyperLynx일 때만) |
| S1 (H4) | Keysight ADS 2027 MCP·SIPro/PIPro MCP (2026-10-06 발표, 2차 출처뿐) + EDA AI 어시스턴트 (early access, 사내 Linux 추론 가능). [Wevolver](https://www.wevolver.com/article/keysight-mcp-servers-ai-agents-rf-design) (2026-10-09), [Keysight EDA.AI](https://www.keysight.com/at/de/lib/resources/miscellaneous/eda-ai.html) (2026-10-26 확인) | ADS·SIPro를 이미 쓸 때만 H4 대안 | 미보유면 0. 보유해도 execute_python T1 검증 때문에 서버당 0.72 MM을 넘기기 어려움 (추정) | ADS 2027 구독 포함으로 추정 | 공식 문서 미확인, 임의 실행 | 관찰 |
| S1·S5 | Cadence AuraStack (2026-07-15 발표, 출시·배포 미확인, MCP 없음), Siemens EDA Fuse (2026-03-16 공개, GA 미확인), Zuken CR-8000 AI (MCP 없음). [Futurum](https://futurumgroup.com/?p=93366) (2026-07-16), [Siemens](https://news.siemens.com/en-us/siemens-fuse-eda-ai-agent/) (2026-03-16) | 사내 PCB 툴이 해당 업체면 '28 H2에 재평가 | '27~'28 0 | 비공개 (AuraStack은 소비형 과금) | 온프렘·GA 미확인 | 관찰 |
| S2 (H9) | 공차 해석 상용 CETOL 6σ·3DCS·EZtol 3.2.1 (MCP·AI·API 못 찾음, EZtol 경로 자동 설정은 SOLIDWORKS판만). [DE247](https://www.digitalengineering247.com/article/sigmetrix-eztol-v3.2.1-tolerance-analysis-software-adds-stackup-cloning) (2026-05-22) | 자동화 엔진으로는 사지 않음. 사내 보유분은 1D 계산기의 골든셋 기준값으로만 | 사도 API가 없어 자동화 공수 감소 0 | 견적 | API·CAD 연동 미확인 | 안 씀 (자동화용) |
| S2·S3 | Keysight MCP for Instrument Control v0.1 (2026-05, 오프라인·Windows, VNA S-파라미터·1-port SOLT, 스코프는 화면 캡처만). [릴리즈 노트](https://helpfiles.keysight.com/kmsic/English/keysight_mcp_for_instrument_control/Content/release-notes.html) (2026-05) | 비교 쌍 측정 기록 표준화 (VNA 중심) | −0.2 MM (추정, VISA·VNA일 때) | 미확인 | v0.1, 2-port 교정 미지원, 시험실 장비 제어 권한 | 관찰 |
| S3 (H2) | 사내 PLM 읽기 MCP(sh-data-query) 직접 개발 (기준안). Teamcenter·3DEXPERIENCE 공식 MCP 없음: [Teamcenter 2606](https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/) (2026-10-26 확인), [3DS 보도자료](https://www.3ds.com/newsroom/press-releases/dassault-systemes-expands-3dexperience-ai-native-agentic-platform-new-virtual-companion-skills-co-engineer-humans) (2026-07-23) | 없음. 2026-07-28 사양, mcp 2.2.0·1.30.0 이상 고정, ECR·ECN 읽기 포함 | H2 2.7 MM 유지 + 사용자 위임 0.3~0.5 MM (추정) | 0 (PLM API 사용자 라이선스 미확인) | 2차 보안 심사 | 도입 |
| S3 | Teamcenter SOA/REST(JSON) + Knowledge Pulse (2606 신규, 상세 미확인). [Mendix 문서](https://docs.mendix.com/appstore/industry/teamcenter-connector/services-not-included/) (2026-10-26 확인) | PLM이 Teamcenter면 H2가 감쌀 하위 API. Knowledge Pulse로 BOM 전개·where-used 계층 대체 검토 | tc-mcp(라이선스 없음) 설계 참고로 −0.03~0.08 MM. Knowledge Pulse 효과 미확인 | 기존 라이선스 (API·Knowledge Pulse 라이선스 미확인) | 버전마다 서비스가 다름 | 도입 (조건부: Teamcenter) |
| S3·S4 | Teamcenter Copilot·AI BOM Agent·MBSE AI (2606 GA. C3 가능 구성은 완전 온프렘 Llama 4.0 Scout뿐, BOM Agent 온프렘 동작 미확인, MCP 아님). [Copilot](https://blogs.sw.siemens.com/teamcenter/teamcenter-plm-ai-copilot/) (2026-06-25), [AI BOM agent](https://blogs.sw.siemens.com/teamcenter/ai-bom-agent-plm-engineering-change/) (2026-06-23) | H3 앞단(영향 어셈블리·ECN 초안)과 H7 요구 점검 일부를 PLM 안에서 | −0.5~1.5 MM (추정, Teamcenter + 온프렘 Llama 승인 시). 우리 Agent가 부를 수 없어 H2는 그대로 | 비공개 (견적) | Llama 4 Scout(109B MoE)가 INF-1 부하를 더함, Siemens 종속 | 관찰 ('27.12 RW 견적) |
| S3 | PTC Windchill AI Assistant MCP 2026.1.0.11 (GA, 도구 6개 모두 문서용, BOM 도구 없음, 온프렘도 고객 Azure 필수). [PTC 도움말](https://support.ptc.com/help/windchill/ai_plugin/en/Windchill_Help_Center/document_vault/WCAIAssistAIPluginMCPServer.html) (2026-10-26 확인) | 없음 | 0 | Azure 구독 + 견적 | C3 반출 | 안 씀 |
| S3 | Windchill 커뮤니티 MCP: rweisssieker (MIT, 부품·BOM 읽기), Cars-10 (ISC, 64개 이상 도구, 쓰기·DELETE 포함). [GitHub](https://github.com/rweisssieker-xp/GBL-CREO-WINDCHILL-MCP) (2026-10-26 확인) | PLM이 Windchill이면 H2 도구 설계 참고, 읽기 도구 일부 재사용 | −0.08 MM 이하 | 0 | 소규모, 버전 호환 미검증, 쓰기 도구는 허용 목록 필수 | 시범 (조건부: Windchill, 읽기만) |
| S3 | Dassault 3DEXPERIENCE Virtual Companions (2026-07-23 GA, OUTSCALE 클라우드 전용, MCP 없음). [3DS 보도자료](https://www.3ds.com/newsroom/press-releases/dassault-systemes-expands-3dexperience-ai-native-agentic-platform-new-virtual-companion-skills-co-engineer-humans) (2026-07-23) | 없음. PLM이 3DEXPERIENCE여도 H2는 사내 개발 | 0 | 미공개 | C3 반출 | 안 씀 |
| S3 | Aras 커뮤니티 MCP: aras-claude-agent (MIT, 도구 5개, ArasLabs fork 실재), aras-plm-mcp (MIT, 69~71 도구). [GitHub](https://github.com/DaanTheoden/aras-claude-agent) (2026-10-26 확인) | PLM이 Aras면 H2 도구 계층 재사용 | −0.3~0.6 MM (추정) | 0 | 쓰기 도구(create·method·promote) 포함 | 시범 (조건부: Aras) |
| S3 | IBM ContextForge MCP Gateway 1.1.0 (Apache-2.0, PyPI Beta, 망분리 UI 빌드). [GitHub](https://github.com/IBM/mcp-context-forge) (2026-10-26 확인) | PLM이 REST를 주면 sh-data-query 일부를 REST→MCP 변환으로 | H2 −0.3~0.8 MM (추정) | 0 | 변환 도구는 인자 검증이 느슨해지기 쉬움, arm64 운영 미지원, 2026-07-28 사양 대응 미확인 | 관찰 (공통 C13 게이트웨이 결정과 함께) |
| S4 (H1) | Werk24 (EU 클라우드, 온프렘은 맞춤 계약, 'several European languages'), CADDi Explorer·Agent (SaaS로 보임). [werk24 llms.txt](https://werk24.io/llms.txt) (2026-10-26 확인), [SiliconANGLE](https://siliconangle.com/2026/09/16/caddi-raises-114m-at-1-2b-valuation-to-bring-manufacturing-ai-to-north-america/) (2026-09-16) | 없음 | 0 | Werk24 €1.25/쪽, 계약 €18,000/년부터 | C3 반출 + 한국어 도면 미지원 | 안 씀 |
| S4 (H1) | eDOCr2 (MIT, ★82) + 로컬 VLM, Docling 2.142.1·docling-mcp 3.3.0 (MIT, 로컬). [eDOCr2](https://github.com/javvi51/edocr2) (2026-10-26 확인), [Docling PyPI](https://pypi.org/pypi/docling/json) (2026-10-23) | 도면 치수는 '28 H1 INF-1 사전 시험 뒤 범위 확정. BOM 표 추출은 Docling | eDOCr2 −0.3~0.6 MM, 사전 시험 +0.2 MM (추정) | 0 | 한국어·사내 양식 정확도 미검증, eDOCr2 저장소가 작음, Docling은 버전 고정 | eDOCr2 시범, Docling 도입 |
| S4 (H1) | STP 형상 비교 K-Compare(Kubotek Kosmos)·CompareVidia (현황 미확인). [Kubotek 도움말](https://help.kubotekkosmos.com/K-Compare/Validate) (로드 실패, 2026-10-26) | STP 형상 비교를 H1에 넣을 때만 | 범위 밖이면 0 | CompareVidia 약 $2,850 (3자 출처, 날짜 없음) | 버전·가격·API 미확인 | 관찰 |
| S4·S5 | Ansys optiSLang + PyOptiSLang 1.7.0 (제품 GA, 래퍼 Beta). [PyPI](https://pypi.org/project/ansys-optislang-core/) (2026-09-29) | H12 doe-planner 공용 엔진, H9 강건성 해석 일부 | H12 −0.3~0.5 MM, 래퍼·학습 +0.3~0.5 MM (추정) | 견적 (사내 Ansys 계약 포함 여부 미확인) | Beta 래퍼, Ansys 종속 | 관찰 (AL-1 A9 결정을 따름) |
| S4·S5 | Synopsys AgentEngineer·Autopilot (2026-09-28 발표, 2026년 말 GA 예정, 온프렘·MCP 언급 없음). [Synopsys 보도자료](https://www.synopsys.com/ko-kr/korean/press-releases/26-09-28-synopsys-powers-autonomous-engineering.html) (2026-09-28) | '28 H2에 hw-precheck SI 외부 조달 후보로 재평가 | '27~'28 0 | 비공개 | 평가판이 클라우드, 반도체 중심 | 관찰 |
| S5 | Ansys SimAI (Pro·Premium Customer Hosted는 사내 처리 가능, 해석 30~100건으로 학습). [SimAI](https://ansys.synopsys.com/products/simai) (2026-10-26 확인) | '29 기종 확대 때 열·구조 반복 판정용 대리모델 검토. 수율 예측과 Gate 2 판정에는 쓰지 않음 | '28 0, '29 검토 | 비공개 | PySimAI Alpha, 망분리 라이선스 미확인 | 관찰 ('29) |

## 일정·인력 변경 제안
| 항목 | 지금 | 제안 | 이유 |
|---|---|---|---|
| 골든셋 마감 | '26.10.30 | '26.11.13, 제안자 PLM 권한으로 export (판정 12/15 유지) | 계정·보안 회신 전 |
| PoC 대체 MM | 규칙 비교 결과 전체 | PLM 내장 비교 대비 추가 탐지분만 | 부풀림 방지 |
| MBSE 범위서 작성 | A·B (P-VV3-06) | 시스템 엔지니어 초안, A·B 검수 | A·B 188%, −3~5인일 (추정) |
| MBSE 툴 결정 | '27.2 Capella 기준, 다기종은 '29 H1 재판단 | '27.2 최종 결정 (기준 4개). H7은 툴 중립 추적 저장소 위에 | '29~'30 이관 시 H7 재작성 1~2 MM 회피 (추정) |
| MBSE 인력 | '27 H1 0.5명분, '27.7 이후 확약 0 | 시스템 엔지니어 1명 지명: '27 H1 0.6 → '27.7~'28.12 0.2 → '29 0.3명분 | RVTM 유지·H7·추적성 측정·다기종. '27 H2~'28 +1.0~1.9 MM (추정, 시스템 팀 30% 안) |
| H6 산출물 | Capella 모델 + RVTM v1 ('27.6) | RVTM v1(요구↔검증 링크) '27.6 + HW 관련 하위 시스템 모델 '27.9 | M-VV3-10을 지키려면 |
| 회로 판정 | DRI 팀 공유, 4월 0.69명분 + 시민개발 0.3명분 | 담당 1~2명 지명, 월 1회 배치, H4 판정은 3월에 종료, 골든셋은 해석 대 해석 | 130% 팀 |
| CAE 배치 라이선스 예산 | '27 3·4분기부터 (연 1억 기준) | 상반기분(HFSS·SIwave·Maxwell '27.2, Icepak '27.5) 견적 11/30 → '27 예산 | H4·A5 무인 실행 |
| H9 | 공차 스택업 자동화 + 열 '27.7~9 | 1D 체인 + MC 계산기, 공차 '27.7~8 → 열 '27.9 | 도면 치수는 '28, A5 의존 |
| 비교 쌍 | 산식 초안 '27.12, 누적 40~80, 쌍당 0.5~1인일 | 쌍 스키마 '27.9 동결. 열·공차·SI/PI는 도메인당 n≥20, EMC는 참고 지표·쌍당 1~2인일 | 신뢰구간, EMC 현실성. +0.25~1.0 MM (추정) |
| H11 수율 PoC | 표 데이터 수율 예측, 데이터 미정 | 공차 MC → 조립·정렬 1차 수율 예측, 데이터 합의 '27.6.30 | 데이터·ML 없음 |
| '28 Agent 범위 | H1: H2·H3·H7 + VP / H2: H1·H12 | AI +1 없음: H2·H3만('28 전체), VP는 CAE·도메인 수작업 집계. AI +1: H2·H3·H7 + VP. H12와 도면 치수는 어느 경우든 '29 H1 | VV-3 AI 비례 몫 연 약 3.3 MM (추정), AI +1이면 약 6.6 MM (추정) |
| Gate 2 보완설계 실적 | 내부 ECR → lead → hw-precheck → redesign-draft → g6 | VP Fail → 설계 변경 반영 기록(사람 5단계 + 플러그인 결과)도 근거로 | Agent 일정과 분리 |
| diff-review 실행 방식 | ECR 이벤트 | sh-data-query 폴링 | PLM 설정 변경 없음 |
| PLM 보안 승인 | '26.10 신청 (PoC·export용) | '27.6 에이전트 운영용 보안 설계서 → '27.12 승인 | H2 '28.1 착수 조건 |
| 시제품 차수 확정 | '29 H1, 1기종 | '29 H1 중간 지표, 확정은 '29 H2 이후 2개 기종 이상 + 과거 기준선 | n=1, 시제품 기간 |
| 기종 확대 | '29 3개 이상 | '29 2개 | MBSE·CAE 공급원 미정 |
| 全기종 표준 대상 | 진행 중인 全기종 | '30.1 이후 시제품을 발주하는 신규 기종 | CAE 연 3.6~7.2 MM (추정) |
| 수율 KPI | '30 H2 90%, 정의·소유는 Gate 2('28.12) | 정의·소유·데이터 '27.6.30. 설계 단계 예측 vs 파일럿·시제품 1차 수율 | H11 방향과 '29 ML 폭(0.5~1.0 vs 0.1~0.2명분)이 여기서 갈림 |

## 새 의존·결정
| 언제 | 무엇 | 누구에게 |
|---|---|---|
| '26.10.27 | P0 결재·기한 경과 5건 상태, PLM 제품·버전·API 방식(SOA·REST·OData)·API 사용자 라이선스 | 개발담당 리더·결재권자, IT·PLM 담당 (A·B가 확인) |
| '26.11.13 | PLM 내장 BOM 구조 비교 사용·API 호출 가능 여부, PLM AI 애드온 보유(Teamcenter Copilot·Knowledge Pulse 또는 Windchill AI Assistant) | PLM 담당 |
| '26.11.13 | 사내 요구·ALM·MBSE 툴 보유(Jama·Polarion·DOORS·Codebeamer·Cameo·Rhapsody), 1D Echo Gen2 요구 원본 형식(ReqIF·엑셀·ALM) | IT, 시스템 팀 |
| '26.11.30 | 사내 PCB·SI/PI 툴 스택(SIwave·Sigrity·HyperLynx·ADS/SIPro), AEDT 버전(gRPC), EMI Scanner 계약·배치 호출, PI용 SIwave vs HFSS-PI 라이선스, Python 3.13 venv 허용 (P-VV3-08 체크리스트에 추가) | 회로 DRI 팀, IT 라이선스 |
| '26.11.30 | '27 상반기 CAE 배치 라이선스 견적과 예산 (투자심의 기안과 함께) | IT 라이선스, A·B |
| '26.12.11 | MBSE 비교 기준 4개 확정 + 시스템 엔지니어 1명 지명 ('27 H1 0.6, 이후 0.2명분) | C엔지니어, 시스템 팀장 |
| '26.12.15 | 회로 판정 담당 1~2명 지명, 판정 월 1회 배치 | 회로 DRI 팀장 |
| '27.2 | MBSE 툴 최종 결정 (Capella면 이관 조건과 H7 툴 중립 설계를 기록, Cameo면 TWC 포함 예산) | C엔지니어 |
| '27.3 | 공차 범위(1D·MC vs 3D)와 공차 입력 출처(도면 수기·CAD PMI) | 기구 DRI 팀, CAE |
| '27.6 | PLM 읽기 MCP 보안 설계서 제출 (읽기 전용·위임·감사 로그·egress 차단·STP 경로 반환·ECR 포함) | A·B·MLOps → 정보보안 |
| '27.6.30 | 수율 KPI 정의·소유(VV-3 설계 단계 / AF-4)와 데이터 제공 합의 | 개발담당 리더, 품질·생산, AF-4 담당 |
| '27.9 | 쌍 스키마 동결, 시험 장비·EMC 챔버 슬롯 | C엔지니어, 회로·기구 DRI 팀 |
| '27.12 | VP 대상 기종 PM 합의 (VP Pass면 계획 차수 2, VP 판정을 발주 조건으로) | 대상 기종 개발 PM, C엔지니어 |
| '27.12 RW | PLM 업체 AI 재확인 (Teamcenter 2612·2706 MCP, PTC 부품·변경 Agent), 해당 시 Teamcenter Copilot 견적 | A·B |
| '28.3 | 상관 정의서 통계 기준 (연속 오차 지표, 도메인당 n≥20, EMC 참고 지표) | DRI·CTO |
| '28.6 | '29 MBSE·CAE 공급원 (기종 확대 2개 기준) | 개발담당 리더 |
| '28.12 Gate 2 | 시제품 차수 확정 기준 (2개 기종 이상, 과거 평균 차수 기준선) | Gate 2 심의 |

## 그대로 둬도 되는 것
- '26.12 PoC를 PLM export 오프라인·규칙 기반으로 판정하고 LLM 요약을 판정 지표에서 뺀 것. PLM·보안 회신이 늦어도 판정할 수 있습니다.
- PLM 읽기 MCP(H2)를 사내 개발로 둔 것. C3 조건에서 쓸 공식 PLM MCP가 없습니다(Teamcenter·3DEXPERIENCE 없음, Windchill은 BOM 도구 없고 Azure 필수).
- 외부 MCP를 Ansys 2개(aedt·mechanical)로 한정하고 사내 미러·버전·해시를 고정하는 것.
- 도면 치수를 eDOCr2 + 로컬 VLM으로 사내에서 만드는 전제와 Werk24를 뺀 것.
- VP '28.6을 광학 제외·플러그인 결과 수작업 집계로 판정하는 기본안.
- M-VV3-08을 08a(VP '28.6)와 08b(시제품 차수)로 나눈 것.
- 단일 상관 정의서 '28.3 + VV-3 부록 '28.6, 열 도메인 쌍을 AL-1 대조와 한 벌로 모으는 것.
- '27 H2 쌍 매칭을 하반기 CAE 여유(월 0.3~0.7명분)로 하는 것. CAE 일이라 역할이 맞습니다.
- 외부 순환(AF-3·AF-4·QE-1·CO-1)을 '3과제 밖 — 조건부' 보조 근거로 둔 것.
- H11을 '27에 남기고 v4 이월 레버를 쓰지 않은 것 (범위만 줄임).
- Agent 1개당 월 0.1명분 운영 공수와 '만든 사람이 운영' 규칙.
- '28은 반기 단위로 계획하고 직전 4Q Rolling Wave로 월 일정을 정하는 방식.
