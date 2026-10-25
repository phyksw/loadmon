# 단계 계획 현실성 검토 — 업체 MCP·AI 기능 포함

2026-10-26 · 대상: [단계 계획](../README.md) ('26 4Q – '30 H2) · 기준: '27 리소스 플랜 v4 (10/22), 새 인원 한도 3명 (사용자 결정 10/22), 업체 자료 10/26 확인 · (추정) = 계산한 값, 업체 사실은 링크에 적힌 날짜 기준

| 문서 | 내용 |
|---|---|
| [AL-1](AL-1.md) · [VV-1](VV-1.md) · [VV-3](VV-3.md) · [공통 기반](공통.md) | 단계별 현실성 문제 · 업체 옵션 · 일정·인력 변경 · 새 결정 · 그대로 둘 것 |
| [업체 지형 전체](업체지형_전체.md) | 5개 분야 133건 — 공식 MCP · API·SDK · AI 기능 · 상용 · 발표 · 커뮤니티 · 없음 확인 |

이 검토로 바로 고친 것은 하나입니다. 덱·데이터가 '28 AI 부족의 첫 레버로 둔 '4명안(AI 2명, '26.11.15)'을 모두 뺐습니다. 새 인원 한도 3명(10/22 확정)과 충돌했습니다. 나머지 제안은 단계 계획에 아직 넣지 않았습니다.

## 1. 결론

1. **'28이 가장 약합니다.** AI 수요 38 MM(공통 미산정을 넣으면 41~43) vs 확정 공급 11 MM. 플랫폼 운영(4.2)과 '27에 릴리즈한 Agent·플러그인 운영(약 7, v4 규칙)을 빼면 새 개발에 남는 AI는 거의 없습니다. Agent 6건을 '29 H1로 미뤄도 약 20 MM, '28 AI +1(한도 재결정)까지 해도 약 9 MM 모자랍니다 → 2장.
2. **업체 공식 MCP는 늘었지만 '27~'28 공수는 거의 줄지 않습니다.** 16곳 39개 중 사내 설치가 되는 것이 18개, 그중 GA는 Jama 1개입니다. 계획이 쓰는 Ansys 2개(aedt·mechanical)는 alpha이고 `run_python_code`를 끌 수 없습니다. 절감은 0으로 두고 허용 스크립트 래퍼(+0.2~0.4 MM)와 분기 1회 묶음 갱신(서버당 연 0.3~0.4 MM)을 더합니다.
3. **C3(도면·STP·BOM)를 넣을 수 있는 PLM 공식 MCP는 없습니다.** Teamcenter·3DEXPERIENCE는 MCP가 없고, Windchill MCP는 고객 Azure가 필수이며 BOM 도구가 없습니다. PLM 읽기 MCP(H2)는 사내 개발을 유지합니다.
4. **사서 실익이 나는 곳은 두 군데입니다.** Ansys 계약에 이미 들어 있으면 optiSLang(A9 −0.8~1.3 MM)·HPS(A7 −0.5~1.0 MM)·SimAI Customer Hosted(S5 −2~4 MM). 그리고 무료인 Isaac Sim 6.2·ovrtx로 '27 외부 시뮬레이터 계약이 필요 없어집니다. 그래도 도구 구매로 줄일 수 있는 '28 AI 공수는 순 1~2.5 MM(부족의 4~9%)입니다.
5. **LiteLLM은 C3 경계에서 뺍니다.** 2026년 CISA KEV 3건 중 2건이 MCP 경로입니다. agentgateway로 '27 Q1 PoC를 하고, 등급 라우팅을 모델 호출뿐 아니라 도구 결과·MCP 서버 egress·임시 파일까지 넓힙니다. 브리지('27.2~6)는 C3 전용 망으로 물리 분리합니다.
6. **Gate 2 수치는 무엇을 셀지가 비어 있습니다.** 판정 셀 20개면 80% 통과의 95% 신뢰구간이 58~92%입니다. 보정 셀과 판정 셀을 나누고, 판정 셀 30개 이상(VV-1)·도메인당 20쌍 이상(VV-3, EMC는 참고 지표), 허용 오차는 측정 전에 고정, 커버리지 분모는 '28.5 CTO 서명, AL-1 L/T는 사람 접촉 시간, 채택률 분모는 의뢰 건으로 정합니다.
7. **실측과의 첫 대조가 너무 늦습니다.** VV-1 센서 모델은 '28.6 기준선 전까지 실측과 한 번도 대보지 않습니다 → '27.3 벤치 5~8셀(0.3~0.5 MM)로 당깁니다. VV-3 '28 H1 비교 쌍은 VP 대상 기종 시제품이 아직 없으므로 다른 기종·이전 차수에서 모읍니다.
8. **'27에도 여유가 0인 고리가 여럿입니다.** CAE 1명이 A3·A5·H4·H5(4월 1.94 vs 1.8명분), Icepak·Fluent 라이선스 확보 월 = 필요 월, RT 코어 GPU 2~3월 공백, 회로 팀(이미 130%)에 VV-3 몫 약 1.0명분, MBSE는 '27.7 이후 확약 0, 야간 해석 실행 위치 미확인.
9. **'29~'30 운영이 새 인원 3명을 묶습니다.** 플랫폼과 업체 MCP 반입(연 1.5~3.5 MM)은 DRI 팀이 받을 수 없습니다. 이관을 3층(사용·판정 / 스킬·평가셋 / 플랫폼·반입)으로 나누고 플랫폼 소유 조직은 '28.12 Gate 2에서 정합니다. AL-1 설계안 생성 v1은 최적화 중심으로 좁힙니다(약 8 → 4.5 MM).

## 2. '28 AI — 새 인원 3명 한도로 다시 센 값

| 경우 (추정, 1명 = 연 약 11 MM) | 남는 AI 부족 (MM) | 공통 검토 반영 시 |
|---|---|---|
| 3명 그대로 (한도 확정 '26.10.22) | 27 | 30~32 |
| + Agent 6건을 '29 H1로 (아래, AI 약 7.4) | 약 20 | 약 20~24 |
| + '28 AI +1 (3명 한도를 '27.6.30에 다시 정할 때) | 약 9 | 약 9~13 |
| + DRI 개발자 '28 연장 중 Agent 개발 몫 (3~6, DRI 팀 합의) | 약 3~6 | 약 3~10 |

- **수요** 37.9 = 3과제 33.7 (AL-1 14.2 · VV-1 8.1 · VV-3 11.4) + 플랫폼 운영 4.2. 공통 검토가 찾은 미산정 8줄(외부 MCP 반입·재검토, 사내 MCP 사양 추종, C3 egress, 플랫폼 운영 1.15 → 1.3명분, 공용 Registry, A2A 시범, 서버 설치, Gate 2 공통 패키지)의 AI 몫이 +2.6~5.5입니다. 2행부터는 공용 Registry·A2A도 '29 H1로 옮겨 −1~2를 뺐습니다.
- **공급** '27 사내 전환 AI 1명 연 약 11 MM만 확정입니다. A·B 개발 참여 '28 = 0(Gate 2 준비), '27 겸직 AI는 '27.6 종료.
- **새 개발에 남는 몫** = 11 − 플랫폼 운영 4.2 − '27 릴리즈분 운영 약 7 ≈ 0 (추정). '27 릴리즈분은 EM, AL-1 플러그인 3개, VV-1 3개(GT·합성 파이프라인·KPI 판정), VV-3 해석 Agent이고, v4 규칙(Agent당 월 0.1명분)의 AI 몫만 셌습니다. 3명 그대로면 '28로 넘긴 Agent 11개는 다른 공급원 없이 시작하지 못합니다.
- **'29 H1로 미루는 6건** (v4 단가 × 바이브 효과 약 0.88): AL-1 A2 설계지식DB(AI·데이터 4.0)·광학 파일럿(약 0.7), VV-3 H7 요구 추적(1.2)·H12 재설계안(0.8)·H1 도면 치수 부분(약 0.9), VV-1 vv1-safety-map(약 0.8) → 원 단가 8.4, 반영 약 7.4.
- **4명안은 없습니다.** v4의 '새 인원 4명이면'(AI 2명, 108.3 MM·마일스톤 11/14·8.1억)은 비교표였고 한도 3명이 10/22에 확정됐습니다. 검토 전 덱·데이터는 이것을 '26.11.15 레버로 두고 '4명안 + AI +1이면 약 1 MM'이라고 적었는데, 이번에 모두 고쳤습니다.
- **'27.6.30에 같이 정할 것**: '28 AI +1 여부(한도 재결정. 사내 전환이면 '27.10.31 확정 → '28.1 투입, '28 실효 약 10~11 MM / 경력이면 '27.7 품의 → '28 실효 약 7~10 MM), '29로 미룰 범위, DRI 개발자 연장, Sinequa PoC·ContextForge 구매.
- **AI를 늘리지 않을 때 지키는 순서**: Gate 2 직결(상관 정의서 '28.3 · VP '28.6 · 실측 수집·판정 · VV-1 커버리지) > '28 원안 마일스톤 > Agent 편의. VV-1은 vv1-scenario-gen을 먼저 하고 vv1-lead는 '28 Q3, VV-3는 H2·H3만 하고 VP는 수작업 집계, Gate 2 보완설계 실적은 'VP Fail → 설계 변경 반영 기록(사람 5단계 + 플러그인 결과)'으로도 셉니다.

## 3. 업체 지형 — 계획에 걸리는 것만 (2026-10-26 확인)

전체 133건(분야별 139건에서 분야 간 중복 6건 제외)은 [업체 지형 전체](업체지형_전체.md)에 있습니다. 여기서는 세 과제 단계에 실제로 걸리는 것만 추렸습니다. **사내 · C3** 칸은 도면·STP·BOM 같은 반출 금지 자료(C3)를 그 제품에 넣을 수 있는지입니다. ○ 사내 설치로 가능 · △ 조건부 · × 클라우드라 불가.

### 3-1. 공식 MCP — 실제로 나온 것

| 업체·제품 | 상태 | 사내 · C3 | 걸리는 단계 | 메모 |
|---|---|---|---|---|
| Ansys [ansys-aedt-mcp](https://pypi.org/pypi/ansys-aedt-mcp/json) (HFSS·Maxwell·Icepak·Circuit) | alpha 0.3.1 (10-23), 3.3개월에 11회 릴리즈, Python 3.13 필수 | ○ 로컬 AEDT·사내 라이선스 | AL-1 S2 열 · VV-3 S1 EMC | SIwave·EDB 도구 없음 → SI/PI 는 PyEDB 로 직접 |
| Ansys [ansys-mechanical-mcp](https://github.com/ansys/pymechanical-mcp) (구조·열) | alpha 0.3.0 (10-14), 도구 28개 | ○ stdio | AL-1 S1 구조 · S2 열 · VV-3 S2 | `run_python_code` 를 끄는 옵션이 없음 → 허용 목록 프록시 필요 |
| Keysight [ADS 2027 MCP](https://www.wevolver.com/article/keysight-mcp-servers-ai-agents-rf-design) (ads·nexus·SIPro/PIPro) | 공식, 로컬 실행파일 — 근거는 2차 출처 3건 | ○ | VV-3 S1 SI/PI (사내에 ADS 가 있을 때) | 회사 PCB·SI 툴이 Ansys 계열이면 해당 없음 |
| dSPACE [MCP Hub](https://github.com/dspace-group/dSPACE-MCP-Hub) 7종 (AURELION Manager·ControlDesk·VEOS 등) | 프리뷰 v0.1~0.2 (07~10월) | ○ 로컬 stdio | VV-1 S3 HIL 선행 · S5 · S6 | AURELION Manager 는 LiDAR 센서 생성·.xosc 검증 도구 39개 |
| MathWorks [MATLAB MCP Server](https://github.com/matlab/matlab-mcp-server) + Agentic Toolkit (Automotive·Lidar skill) | v0.15.0 (10-15) | ○ 오프라인 설치, 공유 서버 금지 | VV-1 (사내 MATLAB 툴박스가 있을 때) | MATLAB Copilot 은 클라우드 → C3 불가 |
| Foretellix [Foretify MCP Bridge](https://www.foretellix.com/foretellixs-mcp-bridge-brings-av-testing-to-your-ai-agent) | 고객 제공(공개 저장소 없음) | ○ 고객 인프라 | VV-1 S5 커버리지·SOTIF | Foretify 자체가 상용 구매 대상 |
| [Jama Connect MCP](https://www.jamasoftware.com/media/2026/05/Jama-Connect-MCP-Datasheet.pdf) (9.35) | GA, 별도 구매 애드온 | ○ self-hosted, 업체가 LLM 을 돌리지 않음 | VV-3 S1·S3 RVTM | 사내 요구관리 툴이 Jama 일 때만 |
| PTC [Windchill AI Assistant + MCP](https://support.ptc.com/help/windchill/ai_plugin/en/Windchill_Help_Center/document_vault/WCAIAssistAIPluginMCPServer.html) | GA 플러그인, 도구 6개 (BOM 없음) | × 온프렘이어도 고객 Azure 필요 | VV-3 S3 | C3 경로로는 못 씀 |
| NVIDIA [Isaac Sim MCP](https://docs.isaacsim.omniverse.nvidia.com/latest/development_tools/isaac_sim_mcp.html) | 문서 검색만 (시뮬레이터 제어 안 함) | △ 기본 클라우드 임베더 | VV-1 | 개발 보조 수준 |

### 3-2. 공식 MCP 가 없는 것 (2026-10-26 확인)

Siemens Teamcenter·Simcenter·NX, Dassault ENOVIA·3DEXPERIENCE, Cadence Allegro·Sigrity·Clarity, Ansys optiSLang·HPS·EDB/SIwave·Speos·Zemax·AVxcelerate·medini, NI VeriStand, FlexLM 라이선스 관리, 공차 해석 툴(CETOL·3DCS·EZtol). → 이 연결은 **사내 MCP 로 직접** 만듭니다(Python API·REST 위에 얇게). COMSOL 은 2027 버전에 MCP 를 발표(09-16)했고, IPG CarMaker 는 MCP 데모(10-15)만 있습니다.

### 3-3. 사서 쓸 수 있는 것 · 업체 AI 기능 — C3 기준으로 가른 것

| 영역 | 사내 설치 가능 (C3 ○) | 클라우드라 C3 불가 (C0 만) |
|---|---|---|
| CAE | optiSLang·HPS 1.4·Minerva(온프렘 명시), SimAI Pro·Premium Customer Hosted, Simcenter PhysicsAI(사내 GPU), Optuna 5.0·BoTorch·PhysicsNeMo(오픈소스) | Ansys Engineering Copilot(인터넷 필수, 제3자 제공자), Dassault Virtual Companions(OUTSCALE 전용), SimAI Premium SaaS |
| EDA·광학 | Keysight EDA AI(사내 추론 서버 요청 가능, early access), Siemens EDA AI system(온프렘 옵션), SIwave EMI Scanner, Zemax ZOS-API·ZOSPy, CODE V 2026 AI Start Expert(완전 온프렘) | — |
| PLM·MBSE | Teamcenter Copilot 2606 **온프렘 Llama 4 Scout 구성**(다른 구성은 LLM 이 클라우드), Polarion 2606 custom LLM 커넥터, CATIA Magic Teamwork Cloud SysML v2 REST, Capella 7.1 + py-capellambse, Docling + docling-mcp, eDOCr2, Sinequa(온프렘 검색 + 공식 MCP) | Windchill AI(Azure), Werk24(EU 클라우드·한국어 도면 지원 밖), CADDi(SaaS) |
| 센서 시뮬레이션 | Isaac Sim 6.2(사내 R&D 무료, RT 코어 GPU), ovrtx 0.6(LiDAR·EchoId·Velocity, 0.x), Cosmos LidarGen·Cosmos3 Transfer(공개 가중치), AVxcelerate Sensors 26R1, AURELION 26.3, Applied Intuition(air-gapped 명시), Hexagon VTD(Rocky Linux), CARLA 0.9.16 | MATLAB Copilot |
| MCP 운영 | agentgateway v1.6, Agent Router(AAIF), IBM ContextForge 1.1, microsoft/mcp-gateway v1.0, Kong AI Gateway, ToolHive·Obot(0.x), 공식 Registry 셀프호스트(preview), cisco-ai-mcp-scanner | Microsoft Agent 365·Work IQ MCP, Atlassian Rovo MCP |

### 3-4. 받아들일 때 조심할 것

- **릴리즈 속도**: ansys-aedt-mcp 는 3.3개월에 11회, 0.3.0 에서 Python 3.13 필수로 바뀌었습니다. 버전·해시 고정과 재검토 주기가 없으면 운영 중 깨집니다.
- **임의 코드 실행 도구**: Ansys 두 서버 모두 `run_python_code` 를 제공하고 끄는 옵션이 없습니다. C3 를 다루는 세션에서는 허용 스크립트만 통과시키는 프록시가 필요합니다.
- **보안 사고는 진행 중**: LiteLLM 이 2026년 CISA KEV 에 3건(그중 MCP stdio 명령 실행·MCP 인증 우회), MCP 공식 SDK 보안 권고 13건(09~10월), 커뮤니티 mcp-atlassian 은 7~8월에 high 이상 22건.
- **사양이 바뀌는 중**: MCP 사양 2026-07-28 판이 stateless·CIMD 로 바뀌었고 일부 기능은 Deprecated(최소 12개월 유예). 공식 Registry 는 아직 preview.
- **'28~'30 업체 로드맵은 연도가 적힌 공개 계획이 거의 없습니다.** 확인된 일정은 Synopsys AgentEngineer '2026 말 GA 예정', COMSOL 2027 MCP, ISO/AWI 8800-2 등록(10-07) 정도입니다.

## 4. 단계 계획에 넣을 변경 — 시기별

과제별 문서의 '일정·인력 변경 제안'에서 계획을 실제로 바꾸는 것만 모았습니다. 공수는 모두 추정입니다.

### 지금 – '26.12

| 과제 | 바꿀 것 | 이유·효과 |
|---|---|---|
| 3과제 | 11/15 안건 = 새 인원 3명 대상자 지정(사내 전환 AI·CAE·MLOps) + LLM 브리지. 4명안 삭제 (반영 완료) | 한도 3명 10/22 확정 |
| 3과제 | CAE 전환 대상자를 11/15에 지정하고 같은 사업부 안에서 옮김(리드 1개월). 1월에 못 오면 A3를 H4보다 먼저 | CAE 1명이 A3·A5·H4·H5, 4월 1.94 vs 1.8명분 |
| AL-1 | L/T ×40·97.5%↓ 판정을 사람 접촉 시간으로 (10/30 합의). 기계 실행·회신 시간은 도메인별 보고만 | 6분 안에 솔버까지 끝내기 어려움, 야간 회신은 하룻밤 |
| AL-1·VV-3 | Ansys MCP 2종 사내 적합성 시험을 '26.11~12로 당김 (DRI 개발자, 서버당 1~2일, Python 3.13 런타임) | 0.3.0부터 3.13 필수·도구 이름 변경, A·B는 188% |
| AL-1·VV-3 | 11/13 회신 묶음에 Icepak·Fluent 라이선스, Ansys 계약 범위(optiSLang·HPS·SimAI·Minerva), 서비스 계정 야간 사용을 합류 | 확보 월 = 필요 월. 계약에 있으면 A7·A9 공수가 줄어듦 |
| VV-1 | Gate 2 판정 대상 방식 1종(ToF 또는 FMCW)을 12월에 정하고 V1 고도화는 그 1종만 (4.7 MM 유지) | 공수 근거가 1종 기준 |
| VV-1 | 무료 장면 호스트 PoC(Isaac Sim 6.2 · ovrtx 0.6, 0.2~0.3 MM) '26.12~'27.1, 1/15 판정 → '27 외부 시뮬레이터 계약 없음 | '27 예산 0, V2 장면이 2월부터 필요 |
| VV-1 | 빅플랜 GPU(RTX PRO 6000) 1~2장을 '27.2~6 VV-1 개발·합성 생성에 | RT 코어 GPU 2~3월 공백 (A100·H100은 Isaac Sim 미지원) |
| VV-1 | 11/30 기안의 INF-2 금액을 2.1~4.2억 범위로 | RTX PRO 6000 카드값 18개월 +87% |
| VV-3 | 골든셋 마감 10/30 → 11/13 (제안자 PLM 권한 export). PoC 대체 MM은 PLM 내장 BOM 비교보다 더 잡은 것만 | PLM 계정 없음, 부풀림 방지 |
| VV-3 | MBSE 범위서에 툴 기준 4개(사내 보유 · SysML v2 API · 헤드리스 접근 · 비용)와 시스템 엔지니어 1명 지명 (12/11) | '29~'30에 툴을 바꾸면 H7 재작성 1~2 MM |
| VV-3 | 회로 판정 담당 1~2명 지명, 판정은 월 1회 배치 (12/15) | 회로 팀 이미 130% |
| 공통 | 11/30 보안 신청에 업체 MCP 4등급 반입 원칙(1~2쪽)과 체크리스트(OWASP MCP Top 10 · NSA CSI) 첨부 | 반입 판단 기준이 없음 |
| 공통 | LiDAR 관련 기술의 국가핵심기술 해당 여부 확인 → 해당하면 클라우드 MCP는 C0만 | R2 미확인 |

### '27

| 과제 | 바꿀 것 | 이유·효과 |
|---|---|---|
| AL-1 | 야간 실행 위치(HPC 스케줄러 / 워크스테이션) '27.3 확인, 없으면 CAE 계산 노드를 '27.8 기안에 | v4 인프라에 CAE 계산 노드 없음 |
| AL-1 | '27.4 A3 실측 MM으로 도메인 확장 표준 재보정 → A5·광학·H4·H5·H9 공수 | 같은 가정이 다섯 군데 복제 |
| AL-1 | Synopsys AgentEngineer CAE 열 에이전트 확인을 '27.6.30 → '27.3 | A5('27.5~9) 착수 전 |
| AL-1 | ZOSPy Standalone 1일 시험·광학 범위 확정 '27.8~9 → LIC_OPT 견적 조건(Standalone · 동시 인스턴스 · 서비스 계정) | 무인 실행이 막혔다는 보고 1건 |
| AL-1 | '27.10~12 CAE 여유로 A7·A9 CAE 몫 + HPS·스케줄러 PoC + optiSLang vs Optuna PoC (약 1.5 MM) | '28 H1 부하 완화 |
| AL-1 | 실측 수집 계획서·상관 정의서 초안을 '27.11로, 11~12월 A·B 개발 참여 0.8 → 0.4명분 | v4 밖 일이 12월 A·B에 몰림 |
| VV-1 | M-VV1-03 종료 기준에 벤치 실측 5~8셀(거리 × 반사율) 대비 거리·강도 오차 (0.3~0.5 MM) | 첫 실측 대조 '28.6 → '27.3 |
| VV-1 | 실측 라벨 200~300프레임 '27.4~5 사내 라벨링 (0.2~0.5 MM) | 외주 없음, V5 미세조정 데이터 |
| VV-1 | HIL 소유·VV-4 착수 결정을 '27.12 → '27.6.30. 미착수면 V11은 인터페이스만(0.6~0.8 MM), 발주는 '28.8 기안 | VV-1 판정 수치와 무관. '27 −0.9~1.1, '28 H1 −0.75 MM |
| VV-1 | '27 H2 시뮬레이션 0.3~0.5명분을 V8a·실측 파일럿·측정 프로토콜에 고정 | 인력 끊김, '28.4 피크 3.1명분 |
| VV-1 | '27.11~12 실측 파일럿 1셋업(셀 6~12개), '27.12에 측정 프로토콜·허용 오차·보정/판정 분리 동결, 센서퓨전 범위도 '27.12 (기본 LiDAR 단독) | 측정이 규칙보다 먼저 시작됨 |
| VV-3 | CAE 배치 라이선스 상반기분(HFSS·SIwave·Maxwell '27.2, Icepak '27.5) 견적을 11/30 기안과 함께 → '27 예산 | v4는 3분기부터만 잡음 |
| VV-3 | H4 SI/PI 기반을 PyEDB(Beta, 버전 고정)로 명시, aedt-mcp는 H5에만 | aedt-mcp에 SIwave·EDB 도구 없음 |
| VV-3 | MBSE 툴 최종 결정 '27.2 (Capella 7.1 + capellambse vs CATIA Magic Teamwork Cloud SysML v2 API), H7은 툴 중립 추적 저장소 위에 | '29 H1 재판단을 없앰 |
| VV-3 | H6 산출물 = RVTM v1 '27.6 + HW 관련 하위 시스템 모델 '27.9, 시스템 엔지니어 '27 H1 0.6 → 이후 0.2명분 | 0.5명분으로 6개월은 무리, '27.7 이후 확약 0 |
| VV-3 | H9 = 1D 공차 체인 + 몬테카를로 계산기, 공차 '27.7~8 → 열 '27.9 | 도면 치수 '28 이월, A5 β 의존 |
| VV-3 | 수율 KPI 정의·소유·데이터 제공 '27.6.30, 쌍 스키마 '27.9 동결, VP 대상 기종 PM과 'VP Pass면 계획 차수 2' 합의 '27.12 | 산식·표본·소유가 비어 있음 |
| VV-3 | PLM 읽기 MCP 보안 설계서 '27.6 제출 → '27.12 승인 (읽기 전용 · 위임 · 감사 로그 · egress 차단 · STP는 경로만 · ECR 포함) | H2 '28.1 착수 조건, 위임 구현 +0.3~0.5 MM |
| 공통 | 게이트웨이 = agentgateway '27 Q1 PoC (M-CTE-03과 함께), LiteLLM은 C3 경계 밖. PoC 게이트 ⑤ 추가(도구별 인가 · C3 Agent 온프렘 고정 · 구형 서버와 새 사양 혼재) | KEV 3건, C13 게이트웨이 1.7 MM 중 0.5~0.9가 설정으로 |
| 공통 | C13 순서: 등급 라우팅·도구 인가·C3 egress '27.3~5 먼저(+0.3~0.5 MM), 어댑터·평가 하네스 '27.6~8 | INF-1 '27.7 이관 전에 경계 |
| 공통 | 브리지 '27.2~6을 C3 전용 망으로 물리 분리 (외부 API 키 없음, egress 차단) | C13 완료 전 공백 |
| 공통 | C12 1.3 → 1.5~2.5 MM, C12b 0.18 → 0.3~0.4 MM. 코드 실행 도구는 C3 세션에서 허용 스크립트 ID만 | run_python_code 래퍼, Python 3.13 런타임, 릴리즈 속도 |
| 공통 | INF-1 모델 조합 '27.7 재평가 (GLM-5.3-Flash NVFP4 + Qwen3.8-27B 후보, 브리지 기간 회귀셋으로 측정) | v4 S안의 gpt-oss-120b는 SWE-V 33.6 |
| 공통 | '28 증설 '27.8 기안 = S안 추론 서버 1대 추가(2.8억) 기본, M안(HGX H200 5.7억)은 '28.3 사내 평가 조건부. INF-2를 INF-1 장애 대체로 지정 | 큰 모델 이득 +1.5%p, 차액 약 −2.9억 |
| 3과제 | '27.6.30: '28 AI +1 여부(한도 재결정) + '29로 미룰 범위 + DRI 개발자 연장 + 구매 2건(Sinequa PoC, ContextForge) | 2장 |

### '28

| 과제 | 바꿀 것 | 이유·효과 |
|---|---|---|
| AL-1 | A2 설계지식DB를 '29 H1 기본안으로 ('28 H2는 PLM 없는 색인 A2a만), 광학은 AI 미확정이면 개발 '28.4~9 · 파일럿 '28.10~11 · 릴리즈 '29 H1 | AI 부족, PLM 창구(H2)도 같은 부족 속 |
| AL-1 | '28.3에 채택률 분모 = 의뢰 건, 야간 100h = 승인 의뢰의 license_hours_used(flexlm_exporter), al1-g6 대리 승인자 | 정의가 곧 판정 |
| AL-1 | 실측 대조 N과 채택 N은 목표가 아니라 '28 시험 계획에서 역산, 채택은 '후보 채택'과 'ECR 반영'으로 나눔 | 실측 공수가 계획 밖 |
| VV-1 | AI +1이 없으면 V6는 vv1-scenario-gen 먼저('28.1~4), vv1-lead는 '28.7~9 | 커버리지에 직결되는 쪽부터 |
| VV-1 | 판정 셀 30개 이상 + 보정 셀 분리, 실측 셀 공수 = 셋업 5~6개 × (시험 2~4 + 정합 3~5인일) + 셀 분석 → 1.4~3.1 MM | 1~1.5 MM은 근거 없음 |
| VV-1 | 커버리지 분모 '28.5 CTO 서명(OpenODD), 70% = 판정까지 끝난 시뮬레이션 커버리지, 승인은 매개변수 시나리오 단위 | 분모 조작 여지, 승인 병목 |
| VV-3 | '28 Agent 범위: AI +1 없으면 H2·H3만, VP는 CAE·도메인 수작업 집계 / AI +1이면 H2·H3·H7 + VP. H12·도면 치수는 어느 경우든 '29 H1 | VV-3 AI 몫 연 약 3.3 MM |
| VV-3 | '28 H1 쌍은 다른 진행 기종·이전 차수에서, 도메인당 n≥20(EMC는 참고 지표, 쌍당 1~2인일) | VP 대상 기종 시제품은 H1에 없음 |
| VV-3 | diff-review는 ECR 이벤트 대신 sh-data-query 폴링 | PLM 관리자 설정 변경 없음 |
| 공통 | '28 플랫폼 운영 1.15 → 1.3명분(15.6 MM), 미산정 8줄을 '27.12 RW에 넣음 → 공통 27~33 MM (Registry·A2A를 '29 H1로 옮기면 25~30) | 미산정이 A·B와 AI를 잠식 |
| 공통 | '28 신규 외부 MCP 2개 이하, 업체 릴리즈는 분기 1회 묶음 갱신(breaking·CVE는 즉시) | 반입 1개 0.25~0.65 MM, 재검토 연 0.1~0.4 MM |
| 공통 | MLOps 전사 지원을 연중 0.25~0.5명분으로 바꾸거나 서버 설치를 IT 인프라로 | MLOps 몫 +3~6 MM |

### '29 – '30

| 과제 | 바꿀 것 | 이유·효과 |
|---|---|---|
| AL-1 | 설계안 생성 v1 = 최적화 중심(DOE·BO + 대리모델 선별), LLM 조건 생성·재축적은 v2('29 H2~) → 신규 약 8 → 4.5 MM | 운영이 새 인원 약 2명분을 묶음, 장시간 로컬 LLM 격차 약 28%p |
| AL-1 | S7 AL-4 통합 3.0 MM → 계약 스텁 0.3 MM, Gate 2 조건부 분기에 M-AL1-12 → '30 H1 명시 | 3과제 밖, 측정 기간 0 |
| VV-1 | 기종별 축소 상관 세트 5~8셀(기종당 0.3~1.0 MM)을 '29 H1에 정의 | '29 공수에 실측 몫 없음 |
| VV-1 | '30 표준: '29 H2 1~2기종 시범 → '30 H1 신규 착수 기종 100%, 운영 이관은 '29 H2 vv1-kpi-check 1개로 시범 | 개발 Gate 개정 리드타임 |
| VV-3 | 시제품 차수: '29 H1은 중간 지표, 확정은 '29 H2 이후 2개 기종 + 과거 평균 차수 기준선. '29 기종 확대는 2개 | n=1로는 구분 불가, MBSE·CAE 공급원 미정 |
| VV-3 | 全기종 표준 대상 = '30.1 이후 시제품을 발주하는 신규 기종 | VP CAE 연 3.6~7.2 MM |
| 공통 | 3층 이관: 사용·판정 '29 H1 / 스킬·평가셋 '29 H2 / 플랫폼·MCP 반입 '30 H1 전사 조직, 이관 준비 '29 H2 1~2 MM. 소유 조직은 '28.12 Gate 2 | DRI 팀은 플랫폼을 받을 수 없음 |
| 공통 | 업체 MCP 반입 승인은 '29 H1부터 정보보안 표준 절차, 미러·스캐너는 IT, AX는 규칙과 판정만 | 업체 MCP가 계속 늘어남 |

## 5. 새로 생긴 결정·확인 — 날짜순

과제별 문서의 '새 의존·결정' 70건에 인원 안건 2건('26.11.15 · '27.6.30)을 더했습니다. 원래 계획의 결정 캘린더는 [통합 문서](../통합_연결·Gate·부하·결정.md)에 있습니다.

### 지금 – '26.12 (21건)

| 언제 | 무엇 | 누구에게 | 과제 |
|---|---|---|---|
| '26.10.27 | 라이선스 신청 패키지(M-CTD-02) 제출 여부 확인, LIC_THERM·D-VV3-04 합류 | A·B → IT·사내시스템(라이선스) | AL-1 |
| '26.10.27 | P0 편입 결재(D-VV1-04) 상태를 확인합니다. 미승인에 대비해 '27 Q1 축소안(V2·V10만, V1은 조건부)을 만듭니다 | 개발담당 리더·결재권자 (축소안은 A·B) | VV-1 |
| '26.10.27 | P0 결재·기한 경과 5건 상태, PLM 제품·버전·API 방식(SOA·REST·OData)·API 사용자 라이선스 | 개발담당 리더·결재권자, IT·PLM 담당 (A·B가 확인) | VV-3 |
| '26.10.28 | 판정 기준서에 목표값과 이번 실측값을 나눠 적습니다. 골든셋('27.1)에 정확도 항목(거리·강도 오차)을 넣기로 정합니다 | D엔지니어 | VV-1 |
| '26.11~12 | Ansys MCP 2종 0단계 적합성 시험(사내 AEDT·Mechanical 버전, Python 3.13 런타임) → A3·A5 도구 계층 결정 | DRI 개발자 → 전사 AX 조직(C12) | AL-1 |
| '26.11.13 | PLM 내장 BOM 구조 비교 사용·API 호출 가능 여부, PLM AI 애드온 보유(Teamcenter Copilot·Knowledge Pulse 또는 Windchill AI Assistant) | PLM 담당 | VV-3 |
| '26.11.13 | 사내 요구·ALM·MBSE 툴 보유(Jama·Polarion·DOORS·Codebeamer·Cameo·Rhapsody), 1D Echo Gen2 요구 원본 형식(ReqIF·엑셀·ALM) | IT, 시스템 팀 | VV-3 |
| '26.11.13 (D-AL1-00 회신과 함께) | 기존 Ansys 계약 범위: optiSLang·HPS·SimAI·Minerva 포함 여부, 라이선스 방식(동시 사용/지정 사용자), 서비스 계정 야간 사용 허용, Synopsys 인수 뒤 정책 변경 | IT·사내시스템(라이선스) → Ansys(Synopsys) 영업 | AL-1 |
| '26.11.15 | 브리지 장비 모델·메모리 확인(빅플랜 p.21 vs v4 불일치) → 브리지에 올릴 모델 결정 | 전사 AX 조직, IT·사내시스템 | AL-1 |
| '26.11.15 | 안건을 '새 인원 3명 대상자 지정(사내 전환 AI·CAE·MLOps) + LLM 브리지'로 바꿈 — 4명안 비교는 한도 3명(10/22 확정)으로 삭제 (반영 완료) | 전사 AX 조직 상정 → 결재 주체 확인 | 3과제 |
| '26.11.15 (브리지 결정과 함께) | 빅플랜 GPU(RTX PRO 6000 9장) 집행 여부를 확인하고, 그중 1~2장을 '27.2~6 VV-1 개발·합성 생성에 배정합니다 | 전사 AX 조직 | VV-1 |
| '26.11.30 | 사내 PCB·SI/PI 툴 스택(SIwave·Sigrity·HyperLynx·ADS/SIPro), AEDT 버전(gRPC), EMI Scanner 계약·배치 호출, PI용 SIwave vs HFSS-PI 라이선스, Python 3.13 venv 허용 (P-VV3-08 체크리스트에 추가) | 회로 DRI 팀, IT 라이선스 | VV-3 |
| '26.11.30 | '27 상반기 CAE 배치 라이선스 견적과 예산 (투자심의 기안과 함께) | IT 라이선스, A·B | VV-3 |
| '26.11.30 (보안 승인 신청과 함께) | 업체 MCP 4등급 반입 원칙 초안(1~2쪽)과 OWASP MCP01~10 분류·NSA CSI 근거 체크리스트를 첨부합니다. A·B 부하가 188% 라 1~2인일 안에서만 작성합니다 | 정보보안 (A·B 작성) | 공통 |
| '26.11.30 (투자심의 기안) | INF-2 금액을 2.1~4.2억 범위로 적습니다. RTX PRO 6000 카드값이 18개월 사이 +87% 올랐습니다(R0) | 전사 AX 조직 | VV-1 |
| '26.12 | Gate 2 판정 대상 방식(ToF 또는 FMCW) 1종을 정합니다 | D엔지니어·CTO | VV-1 |
| '26.12 | LiDAR 관련 기술이 국가핵심기술에 해당하는지 확인합니다(R2 미확인). 해당하면 등급 4(클라우드 MCP) 범위를 C0 로 좁힙니다 | 정보보안·법무 | 공통 |
| '26.12 (11/13 회신 때 같이) | 사내 환경을 확인합니다: IdP 종류(Entra 인지 Okta 인지), 협업 도구 DC/Cloud, PLM 제품과 REST 범위, K8s 보유, 사내 PyPI·npm·OCI 미러 유무, 요구관리 도구(Jama 등) 보유. 게이트웨이·ContextForge·Jama 판단의 전제입니다 | IT·사내시스템 | 공통 |
| '26.12.11 | MBSE 비교 기준 4개 확정 + 시스템 엔지니어 1명 지명 ('27 H1 0.6, 이후 0.2명분) | C엔지니어, 시스템 팀장 | VV-3 |
| '26.12.15 | 회로 판정 담당 1~2명 지명, 판정 월 1회 배치 | 회로 DRI 팀장 | VV-3 |
| '26.12.15 (확약에 추가) | 벤치 실측 셀 5~8개('27.3), 실측 라벨 200~300프레임('27.4~5), 기존 개발 시험 기록 재사용을 확약에 넣습니다. 시스템 엔지니어 시간은 실제 담당 단위로 점검합니다 | DRI 팀 | VV-1 |

### '27 상반기 (20건)

| 언제 | 무엇 | 누구에게 | 과제 |
|---|---|---|---|
| '27 Q1 (M-CTE-03 과 같이) | 게이트웨이 제품 결정과 PoC 게이트 ⑤(도구별 인가, C3 Agent 온프렘 고정, 사양 혼재) | 전사 AX 조직(CT-E), 정보보안 | 공통 |
| '27.1 | Isaac Sim·ovrtx 사내 설치 보안을 검토합니다(오프라인 설치, 확장·자산 미러, 원격 텔레메트리 차단). NVIDIA Proprietary 라이선스 조항도 확인합니다 | 정보보안·IT/사내시스템 | VV-1 |
| '27.1 | VV-1 산출물(센서 파라미터·합성 점군·실측 기록)의 등급을 판정합니다. C3이면 vv1-* Agent는 온프렘 경로만 씁니다 | 정보보안, A·B | VV-1 |
| '27.1 | 라이선스에 딸린 업체 교육·기술지원과 합성 데이터 구매가 '외주 없음' 원칙에 걸리는지 정합니다. Ansys AVX 평가판 조건(기존 계약 묶음 여부)을 문의합니다 | 전사 AX 조직(결정권자 확인 필요), IT/사내시스템(라이선스) | VV-1 |
| '27.1 | 브리지 C3 전용 망(외부 API 키 없음, egress 차단)을 구성합니다 | IT 인프라·정보보안 | 공통 |
| '27.1.15 | 무료 장면 호스트 PoC를 판정하고(Isaac Sim 6.2 vs ovrtx 0.6), 자체 엔진 레이캐스트가 RT 코어에 의존하는지 확인합니다. 이 결과로 D-VV1-01을 '27 무료 기준선으로 확정합니다 | D엔지니어·VV-1 플랫폼 개발자 | VV-1 |
| '27.2 | MBSE 툴 최종 결정 (Capella면 이관 조건과 H7 툴 중립 설계를 기록, Cameo면 TWC 포함 예산) | C엔지니어 | VV-3 |
| '27.2 (V3 착수) | lidar-engine MCP를 MCP 사양 2026-07-28로 짓고, SDK 하한(mcp ≥2.2.0 또는 ≥1.30.0)을 고정합니다 | VV-1 플랫폼 개발자, A·B 검토 | VV-1 |
| '27.3 | 야간 실행 위치(HPC 클러스터·스케줄러 / 워크스테이션) 확인 | IT·사내시스템 | AL-1 |
| '27.3 | Synopsys AgentEngineer CAE 열 에이전트의 GA·온프렘·MCP 여부 → A5 범위 | A·B → IT 경유 업체 문의 | AL-1 |
| '27.3 | 공차 범위(1D·MC vs 3D)와 공차 입력 출처(도면 수기·CAD PMI) | 기구 DRI 팀, CAE | VV-3 |
| '27.3 | Ansys MCP 의 run_python_code 정책(끄기 vs 허용 스크립트 래퍼)과 aedt-mcp 용 Python 3.13 런타임 분리 | 해석 PL, CAE·AI 엔지니어 | 공통 |
| '27.3.31 | GPU 요청을 학습(비 RT 허용)과 생성(RT 필수)으로 나눕니다 | 전사 AX 조직 → 전사 지원 조직 | VV-1 |
| '27.4 | A3 실측 MM 으로 도메인 확장 표준 재보정 → A5·광학 공수 | A·B, 해석 PL | AL-1 |
| '27.6 | ODD 분류 체계 v0을 냅니다(V8a 분모의 근거) | CTO | VV-1 |
| '27.6 | PLM 읽기 MCP 보안 설계서 제출 (읽기 전용·위임·감사 로그·egress 차단·STP 경로 반환·ECR 포함) | A·B·MLOps → 정보보안 | VV-3 |
| '27.6.30 | 수율 KPI 정의·소유(VV-3 설계 단계 / AF-4)와 데이터 제공 합의 | 개발담당 리더, 품질·생산, AF-4 담당 | VV-3 |
| '27.6.30 | '28 반입 후보(2개 이하)와 라이선스 조건을 정합니다. MATLAB 공유 금지는 MathWorks 와 협의하고, dSPACE·Keysight 는 보유 여부를 봅니다. 구매 2건(Sinequa PoC, ContextForge)도 이때 판단합니다 | DRI 팀·IT(라이선스), 개발담당 리더 | 공통 |
| '27.6.30 | '28 AI +1 여부(새 인원 3명 한도 재결정) + '29 H1로 미룰 Agent 범위 + DRI 개발자 '28 연장 — 요약 2장 | 개발담당 리더·결재권자 (A·B 상정) | 3과제 |
| '27.6.30 (당김, 원래 '27.12) | HIL 소유(VV-1/VV-4)와 VV-4 착수 여부를 정합니다. 미착수면 V11은 인터페이스만 하고 발주는 보류합니다 | 개발담당 리더·CTO | VV-1 |

### '27 하반기 (15건)

| 언제 | 무엇 | 누구에게 | 과제 |
|---|---|---|---|
| '27.7 | INF-1 모델 조합 재평가. GLM-5.3 계열 라이선스(계열 합산 매출 조항)는 법무 확인 | 전사 AX 조직·법무 | 공통 |
| '27.8 | LIC_OPT 견적 조건: ZOS-API Standalone 허용·동시 인스턴스·Windows 서비스 계정 실행. CODE V 를 쓰면 Keysight 견적 + 자동화 API 확인 | IT·사내시스템(라이선스), DRI 광학 팀 | AL-1 |
| '27.8 | optiSLang·HPS·SimAI 견적(계약에 없을 때) + 필요 시 CAE 계산 노드를 '28 예산에 반영 | 전사 AX 조직 → 예산 | AL-1 |
| '27.8 | '28 증설 기안에 생성용 RT 서버를 학습 서버와 따로 적고, INF-1·INF-2 스케줄러 공유 시험 결과를 붙입니다 | 전사 AX 조직(A·B 기안) | VV-1 |
| '27.8 | '28 증설 기안: S안 추가를 기본, M안은 '28.3 평가 조건부 | 전사 AX 조직 → 투자심의 | 공통 |
| '27.8~9 | ZOSPy Standalone 1일 시험(기존 라이선스) + 광학 해석 범위(순차·비순차·공차) 확정, ZOSPy·Optuna·flexlm_exporter 사내 미러 반입 | CAE 엔지니어·DRI 광학 팀, 정보보안 | AL-1 |
| '27.9 | 쌍 스키마 동결, 시험 장비·EMC 챔버 슬롯 | C엔지니어, 회로·기구 DRI 팀 | VV-3 |
| '27.10 | 사내 MCP 가 Deprecated 기능(Roots·Sampling·Logging·SSE)을 쓰지 않는지 점검하고 제거 대응을 계획합니다 | AI 엔지니어 | 공통 |
| '27.10.31 | '28 AI 확정 결과로 광학 개발 착수 월·A2 시점 결정 | 전사 AX 조직, DRI(C엔지니어) | AL-1 |
| '27.12 | VP 대상 기종 PM 합의 (VP Pass면 계획 차수 2, VP 판정을 발주 조건으로) | 대상 기종 개발 PM, C엔지니어 | VV-3 |
| '27.12 (RW) | 측정 프로토콜을 동결합니다(셋업 단위 셀, 판정 셀 30개 이상·보정 셀 분리, 허용 오차 = 사양서 값, 날씨 셀 범위). 센서퓨전 범위도 여기서 정합니다(당김, 기본 LiDAR 단독) | D엔지니어·CTO | VV-1 |
| '27.12 (RW) | 외부 시뮬레이터 MCP를 들이면 게이트웨이 허용목록(delete_* 차단)과 T1 검증을 거칩니다 | A·B·정보보안 | VV-1 |
| '27.12 RW | PLM 업체 AI 재확인 (Teamcenter 2612·2706 MCP, PTC 부품·변경 Agent), 해당 시 Teamcenter Copilot 견적 | A·B | VV-3 |
| '27.12 RW | '28 공통 8줄 추가(+6.5~13 MM)와 M-CTA-07·M-CTE-05 의 '29 H1 이동 여부 | A·B → 전사 AX 조직 | 공통 |
| '27.12.31 (D-CTA-02 와 같이) | 공용 Registry 운영 주체와 공식 Registry 셀프호스트 채택 여부 | D-CTA-02 결정 주체 | 공통 |

### '28 이후 (16건)

| 언제 | 무엇 | 누구에게 | 과제 |
|---|---|---|---|
| '28.1 (당김, 원래 '28.3) | VV-1 판정 규칙을 먼저 승인합니다. 3과제 합본 승인은 '28.3을 유지합니다 | D엔지니어·CTO | VV-1 |
| '28~ 분기마다 | Ansys MCP·MCP SDK 재검토(연 0.3~0.6 MM, 추정)를 '28 공통 20 MM 에 추가 | 전사 AX 조직(CT) | AL-1 |
| '28.3 | 채택률 분모, 야간 100h 정의(승인 의뢰 license_hours), 측정 수단(flexlm_exporter), al1-g6 대리 승인자 | 해석 PL | AL-1 |
| '28.3 | 상관 정의서 통계 기준 (연속 오차 지표, 도메인당 n≥20, EMC 참고 지표) | DRI·CTO | VV-3 |
| '28.4 | SOTIF 트리거링 조건 목록 v0을 내고, ISO/PAS 8800 범위 포함 여부를 정합니다 | CTO | VV-1 |
| '28.5 | 40% 측정 전에 커버리지 분모를 동결합니다(OpenODD, CTO 서명) | CTO·D엔지니어 | VV-1 |
| '28.6 | SimAI Pro PoC 착수 여부(도메인 1개, 야간 결과 30건 이상) | 전사 AX 조직, 해석 PL | AL-1 |
| '28.6 | '29 MBSE·CAE 공급원 (기종 확대 2개 기준) | 개발담당 리더 | VV-3 |
| '28.6 | Enterprise-Managed Authorization(ID-JAG)의 클라이언트·IdP 지원을 다시 확인해 PLM 읽기 MCP 의 사용자 위임을 판단합니다 | IT(IdP) | 공통 |
| '28 4Q RW | Synopsys AgentEngineer·Ansys optiSLang MCP 출시 상태를 확인해 AL-1 S5(설계안 생성 '29)·A9 와 겹치는지 판단합니다 | 해석 PL, A·B | 공통 |
| '28.12 (Gate 2) | build vs buy 재판단: AgentEngineer(L3·L4)·SimAI·optiSLang·HPS | Gate 2 심의 | AL-1 |
| '28.12 (Gate 2) | '29 이후 플랫폼과 업체 MCP 반입을 맡을 조직(전사 IT/AI 조직, 정보보안)과 3층 이관 비중을 정합니다. 협업 도구가 DC 라면 EOL('29.3.28) 대응도 이때 정합니다 | Gate 2 심의, IT·사내시스템 | 공통 |
| '28.12 Gate 2 | 시제품 차수 확정 기준 (2개 기종 이상, 과거 평균 차수 기준선) | Gate 2 심의 | VV-3 |
| '29 H1 | 기종별 축소 상관 세트(5~8셀)를 정의하고, '30 표준 시범 기종 1~2개를 고릅니다 | D엔지니어·개발 프로세스 소유 조직 | VV-1 |
| '29 H1 | L안(B300 7.9억)은 모델 크기가 아니라 '28 에 실측한 세션 부하로 판단합니다 | 전사 AX 조직 → 투자심의 | 공통 |
| '29 4Q (RW) | AL-4 착수 확정 여부 → S7 통합 공수 반영 | 전사 AX 조직, AL-4 소유 조직 | AL-1 |

## 6. 아직 모르는 것

업체 옵션의 절반 이상이 아래 확인 결과에 따라 '도입'과 '안 씀' 사이를 오갑니다.

### 사내에서 확인할 것 (11/13 회신 · 12월 묶음)

| 무엇 | 갈리는 것 | 과제 |
|---|---|---|
| Ansys 계약 범위 — optiSLang · HPS · SimAI · Minerva · AVxcelerate 포함 여부, 동시 사용/지정 사용자, 서비스 계정 야간 사용, 망분리 라이선스, Synopsys 인수 뒤 정책 | A7·A9 구매 대체, S5 대리모델, VV-1 독립 기준 모델 | AL-1 · VV-1 · VV-3 |
| PLM 제품·버전·API 방식(SOA · REST · OData)·API 사용자 라이선스, 내장 BOM 구조 비교, PLM AI 애드온(Teamcenter Copilot · Knowledge Pulse · Windchill AI) | H2 설계, ContextForge 변환, PoC 기준선 | VV-3 · AL-1 |
| 요구·ALM·MBSE 툴 보유(Jama · Polarion · DOORS · Codebeamer · Cameo · Rhapsody), 1D Echo Gen2 요구 원본 형식(ReqIF · 엑셀 · ALM) | H7을 사서 쓸지, MBSE 툴 결정 | VV-3 |
| PCB·SI/PI 툴(SIwave · Sigrity · HyperLynx · ADS/SIPro), AEDT 버전(gRPC), EMI Scanner 배치 호출, PI용 SIwave vs HFSS-PI | H4·H5 도구 계층, Keysight·Siemens EDA 옵션 | VV-3 |
| HPC 스케줄러·야간 해석 실행 위치 | HPS 도입, CAE 계산 노드 예산 | AL-1 |
| 빅플랜 GPU 실제 구성(빅플랜 p.21 'RTX 5080 6대 + A6000 9대' vs v4 'RTX PRO 6000 9장')과 집행 여부 | 브리지 모델, VV-1 RT GPU 브리지 | AL-1 · VV-1 |
| MATLAB Lidar Toolbox · RoadRunner, dSPACE · Keysight · COMSOL 보유 | 해당 업체 MCP가 후보가 되는지 | VV-1 · 공통 |
| IdP(Entra · Okta), 협업 도구 DC/Cloud(Atlassian DC EOL '29.3.28), K8s 운영 역량, 사내 PyPI·npm·OCI 미러 | 게이트웨이 제품, 반입 경로, 위임 인가 | 공통 |
| 국가핵심기술 해당 여부 | 클라우드 MCP 범위(C0만 / C0~C1) | 공통 |
| 시험 장비 · EMC 챔버 · 시험 슬롯, VV-1 산출물(센서 파라미터 · 합성 점군 · 실측 기록) 등급 | 쌍·셀 수집 공수, vv1-* Agent 경로 | VV-1 · VV-3 |
| 라이선스에 딸린 업체 교육·기술지원, 합성 데이터 구매가 '외주 없음'에 걸리는지 | AVX 평가판, 상용 합성 데이터 | VV-1 |

### 업체에 물을 것

| 업체 | 질문 |
|---|---|
| Ansys (Synopsys) | aedt-mcp gRPC 인증, `run_python_code` 비활성 계획, Python 3.13 고정 기간 · HPS · SimAI Customer Hosted의 망분리 설치(공개 레지스트리 pull 대신 사내 미러) · optiSLang·Granta MCP 일정 · AgentEngineer CAE 열 에이전트 GA·온프렘·MCP · OpticStudio NEST의 ZOS-API 노출 |
| NVIDIA | ovrtx Proprietary 조항, Velocity 채널이 FMCW 반경속도인지 · Isaac Sim 오프라인 설치와 원격 텔레메트리 차단 |
| Siemens | Teamcenter 공식 MCP 계획(2612 · 2706) · Copilot 온프렘 Llama 4 Scout 구성 가격 · AI BOM Agent 온프렘 동작 · Polarion 로컬 LLM 커넥터 지원 모델 |
| PTC | Windchill AI Assistant의 Azure 없는 구성 · 부품·변경(BOM) 도구 계획 |
| Keysight | ADS 2027 MCP 공식 문서 · `execute_python` 비활성 · EDA AI 사내 추론 서버 조건 · CODE V 자동화 API |
| dSPACE | AURELION 온프렘 명시 · 커스텀 센서 인터페이스의 FMCW 지원 · MCP `delete_*` 비활성 |
| MathWorks | MCP 서버 다중 사용자 공유 금지 조항(야간 공유 서버 사용) |
| Jama · Obeo | Jama self-hosted MCP 애드온 가격 · Obeo AI for Capella 배포 형태와 로컬 LLM 지원 |
| Sinequa | MCP 출시 상태 · 망분리 설치 · BOM 범위 · 가격 |
| Foretellix | 센서 단품 ODD(날씨 · 반사율 · 거리) 표현 · 사내 설치 조건 · 평가판 |

## 7. 방법

- **업체 조사**: CAE · EDA·광학 · PLM·MBSE·요구·도면 · 센서 시뮬레이션·HIL · MCP 운영·보안 5개 분야에서 139건을 찾고, 1차 출처(업체 문서 · PyPI · GitHub 릴리즈 · 보도자료)로 다시 확인했습니다. 분야 간 중복 6건을 빼면 133건입니다. 확인일은 2026-10-26이고, 발표·출시일은 링크 옆에 적었습니다.
- **검토**: 과제 3개와 공통 기반을 단계마다 '이 일정·공수·전제가 성립하나'로 봤습니다. 근거는 '27 리소스 플랜 v4 모델(model27), 단계 계획 데이터(`data/`), 빅플랜·2차보완보고, '26.10.21 사전 조사 R0~R6입니다.
- **수치**: 업체·v4 값은 그대로 옮겼고, 나머지는 (추정)으로 표기한 계산값입니다. 공수 단위는 MM(1명 1개월), 명분은 달마다의 FTE입니다.
- **확인하지 못한 것**: 업체 가격은 거의 비공개입니다. Keysight ADS MCP·Sinequa는 2차 출처나 업체 마케팅이 근거입니다. agentgateway의 도구별 인가·헤더 등급 라우팅은 문서로 확인하지 못했습니다.
