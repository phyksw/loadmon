# R3 외부 MCP 활용, 3과제 개발 공수를 얼마나 줄이는가 (2027 리소스 플랜 개정용)

**요약**
1. 3과제에 바로 연결해 쓸 수 있는 **공식** 외부 MCP는 사실상 **Ansys(PyAnsys) 서버 묶음**뿐입니다. ansys-aedt-mcp(HFSS, Maxwell, Icepak, Circuit)와 ansys-mechanical-mcp(구조와 열)는 2026-07~10월에 PyPI에 처음 올라왔고, 아직 **Alpha 0.2~0.3** 단계입니다. PLM(Teamcenter), MBSE(Capella), LiDAR 시뮬레이터 쪽은 공식 MCP가 없습니다. 있어도 문서 검색용이거나, 상용 제품이거나, 커뮤니티 수준입니다. 그래서 이 영역은 **사내 개발을 그대로 두고 외부 서버는 참고 구현으로만** 씁니다.
2. 작업 패키지(WP)마다 "직접 짜지 않아도 되는 통합 코드" 몫을 더하면, 개발 인력 공수 절감은 **보수 1.0 / 기준 3.5 / 낙관 7.7 MM**입니다. 매핑한 WP의 개발 공수 75 MM 중 1~10%이고, 바이브 코딩 효과를 적용하기 전 값입니다.
3. 반면 외부 MCP 9개를 들여와 보안 검증하고 재검토하는 공수는 **보수 7.1 / 기준 4.2 / 낙관 2.0 MM**(추정)입니다. 그래서 **기준 시나리오의 순효과는 약 −0.7 MM**입니다. 1개당 절감이 검증 공수보다 확실히 큰 것은 Ansys 2개(AEDT, Mechanical)뿐입니다. 외부 MCP를 공수를 줄이는 수단으로 크게 잡으면 안 됩니다.
4. 실제 가치는 공수 절감 밖에 있습니다. ① Ansys API가 바뀔 때 따라가는 부담을 벤더가 집니다. ② 같은 MCP 도구를 **Claude Agent SDK와 LangGraph(`langchain.mcp`, beta)가 함께 씁니다.** 그래서 1안(투트랙)이든 2안(로컬 LLM)이든 도구 계층을 두 번 만들지 않습니다. ③ 사내 MCP(PLM 읽기, lidar-engine)를 만들 때 설계를 참고할 수 있습니다.
5. 공급망 위험은 실제로 일어났습니다. 2025-09 postmark-mcp(처음 확인된 악성 MCP), 2026-02 SANDWORM_MODE(AI 코딩 도구 설정에 악성 MCP 몰래 등록), 2026-04 OX Security STDIO 설계 결함(Anthropic은 "의도된 동작"이라고 답함), 2026-05 NSA CSI가 있었습니다. 그래서 **사내 미러, 버전과 해시 고정, 망분리 샌드박스 시험, 허용 목록**이 필수입니다. 서버 1개당 검증 공수는 **0.15 / 0.30 / 0.45 MM**(낙관 / 기준 / 보수, 추정)입니다.

- 조사일: **2026-10-21 (KST)**. 저장소와 패키지 수치는 이날 GitHub API, PyPI, npm 레지스트리를 직접 조회한 값입니다.
- 범위: 웹과 문서 조사만 했습니다. **아무것도 설치와 실행하지 않았습니다.** 사내 시스템(PLM 제품명과 버전, VCS, 모니터링 스택)은 확인하지 못했습니다.
- 조사 중 웹 검색 한도에 걸렸습니다. 그래서 일부 항목(Isaac Sim 커뮤니티 서버 상세, mcp-atlassian의 Data Center 지원, 로컬 스캐너 대안)은 **미확인**으로 남겼습니다(8장).

---

## 0. 표기 원칙

| 항목 | 내용 | 근거 |
|---|---|---|
| 3값 | 공수와 비용 파라미터는 **hi = 보수(큰 값)**, base = 기준, lo = 낙관입니다. **절감률(saving)은 hi = 보수(작은 값)**입니다. `model27.py`의 `SAVE_KEY`, `mcp_saving()`과 같은 정의입니다. | model27.py L297, L325 |
| 절감률 정의 | WP의 개발 인력(AI, CAE, ML, SIM, DATA, OPS, MBSE) 공수 중 외부 MCP가 대신해 주는 몫입니다. 대신하는 것은 **도구 연결 코드**(세션 관리와 파일 전송, 실행, 결과 내보내기와 도구 스키마와 로깅)입니다. 도메인 스크립트(경계조건, 메시, 판정), 평가, 도메인 인력, AX는 빼고 셉니다. 바이브 코딩 배수는 모델이 따로 곱하므로 겹치지 않습니다. | model27.py L340 `v × (1 − mcp) × vibe` |
| 공식 / 커뮤니티 | **공식**: 제품 벤더나 프로젝트 조직이 저장소 소유자이자 패키지 퍼블리셔입니다. **커뮤니티**: 개인이나 제3자입니다. |, |
| 망분리 실행 | ○ = 사내 미러로 설치하고 인터넷 없이 실행할 수 있음. △ = 조건이 있음(모델 사전 캐시, 사내 서버 필요 등). × = 클라우드 엔드포인트가 반드시 필요함. | 각 행 출처 |
| 신뢰도 | **상**: 벤더 공식 문서와 레지스트리 조회. **중**: 언론과 보안업체 1차 보고. **하**: 블로그와 집계 사이트, 또는 검색 요약으로만 확인. | R0와 같음 |
| 추정 / 미확인 | 근거가 없는 계산값은 **추정**, 찾지 못한 값은 **미확인**으로 적었습니다. 공급사 마케팅 수치에는 "(공급사 주장)"을 붙였습니다. |, |

---

## 1. 카테고리별 결론

| 카테고리 | 공식 MCP 현황 (2026-10) | 3과제 판정 | 출처 |
|---|---|---|---|
| Ansys/PyAnsys | **있음**. ansys 조직에 aedt, mechanical, mapdl, fluent, cfx, lumerical, common 7개 저장소(Apache-2.0)가 있고 모두 Alpha입니다. | **도입**: AL-1 구조와 열, VV-3 SI/PI, EMC | https://github.com/orgs/ansys/repositories?q=mcp (조회 2026-10-21, 상) |
| MATLAB | **있음**. MathWorks 공식 MATLAB MCP Server v0.15.0이 있습니다. | **조건부**: 최적화나 공차 계산에 MATLAB을 쓸 때만 | https://github.com/matlab/matlab-mcp-server (상) |
| 광학(Zemax, CODE V) | 공식은 **없습니다**. OpticStudio용 커뮤니티 서버가 1개 있고, CODE V용은 확인하지 못했습니다. | **참고 구현**: A11, H12 | https://glama.ai/mcp/servers/xbthp6dblz (하, 검색 요약) |
| PLM | Windchill은 **공식이 있지만 문서 검색과 요약 도구뿐**이고 BOM, 부품 도구가 없습니다. Teamcenter와 3DEXPERIENCE는 공식이 **없습니다**. Aras는 커뮤니티 서버가 있습니다. | **사내 PLM API로 직접 개발**합니다(H2). 외부 서버는 설계 참고만. | 2-2 표 |
| CAD/STEP | 공식은 없습니다. 커뮤니티 서버는 FreeCAD, build123d, OCC(읽기 전용) 쪽에서 활발합니다. | **조건부와 참고**: H1 STEP 정합성 확인 | 2-3 표 |
| MBSE | Capella는 Obeo의 **상용** "AI for Capella"(MCP+API, Early Adopter)만 있습니다. SysML v2, SysON, Cameo는 커뮤니티 서버입니다. | **참고**(H6, H7). 상용 제품을 사면 H7 절감이 커집니다. | 2-4 표 |
| 시뮬레이션 | NVIDIA 공식 MCP는 **문서와 코드 검색용**이고, 실행 중인 시뮬레이터를 제어하지 않습니다. Isaac Sim, CARLA 제어 서버는 커뮤니티 것입니다. ROS 2는 커뮤니티 서버(★1.5k)가 성숙한 편입니다. OpenSCENARIO용 MCP는 없습니다. | **참고**. 엔진이 ROS 2 기반이면 ros-mcp-server를 조건부로 씁니다. | 2-5 표 |
| 데이터와 검색 | Qdrant, Milvus, Chroma, OpenSearch는 공식이 있습니다. Elasticsearch의 기존 MCP는 **지원 중단**(Agent Builder로 대체)됐습니다. Postgres 레퍼런스는 **지원 중단 + SQL 인젝션**이 있어 Google MCP Toolbox가 대안입니다. | **도입**: 벡터DB 1개(사내에서 고른 DB에 맞춤) | 2-6 표 |
| 문서 파싱 | Docling MCP(LF AI & Data, MIT)는 활발합니다. MarkItDown MCP는 alpha입니다. Unstructured MCP는 클라우드 전용이고 유지보수가 끝났습니다. | **도입**: Docling | 2-7 표 |
| ML | MLflow MCP는 MLflow에 내장된 실험 기능이고 **trace 도구만** 있습니다. W&B MCP는 클라우드이거나 셀프호스트 W&B가 필요합니다. HF MCP는 원격 서버입니다. | **조건부**: MLflow | 2-8 표 |
| 인프라 | Kubernetes MCP(Go, 읽기 전용 설정 가능)와 Grafana 공식 MCP(Prometheus 질의 포함)가 있습니다. Slurm용은 커뮤니티 서버뿐입니다. | **도입**: Grafana. **조건부**: K8s. Slurm은 참고만. | 2-9 표 |
| 협업 | GitHub 공식(로컬 서버는 GHES 지원), GitLab 내장(self-managed는 beta), Atlassian Rovo(Cloud 전용), Microsoft Agent 365(클라우드)가 있습니다. | 개발 흐름용으로만 씁니다. **C3 데이터에는 쓰지 않습니다.** | 2-10 표 |
| 기타 | 레퍼런스 서버(filesystem, git, fetch, memory)와 Playwright가 있습니다. | **도입**: LangGraph 트랙에 filesystem, git(Claude 하네스 내장 도구를 대체) | 2-11 표 |

---

## 2. 서버 목록 (조회 2026-10-21)

### 2-1. CAE (Ansys, MATLAB, 기타)

| 서버 | URL | 제공자 | 라이선스 | 성숙도 (최근 릴리즈와 커밋) | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **ansys-aedt-mcp** (PyAEDT-MCP) | https://github.com/ansys/pyaedt-mcp | 공식. PyPI 퍼블리셔는 "Synopsys, Inc. and ANSYS, Inc."입니다. | Apache-2.0 | v0.2.4 (2026-10-01). 첫 릴리즈는 0.1.0 (2026-07-15)이고 석 달 동안 9번 릴리즈했습니다. 분류는 "3 - Alpha", 마지막 push 2026-10-20, 커밋 166, ★25 | ○ pip 설치이고 Python 3.12 이상, AEDT 2022 R2 이상(gRPC)이 필요합니다. 라이선스 서버는 사내에 둡니다. | 도구 20개 중 `run_python_code`, `run_python_script`는 **임의 코드 실행**입니다. gRPC 인증 설명이 문서에 없습니다. `clear_aedt`는 열린 프로젝트를 모두 닫습니다. SIwave, EDB 전용 도구는 **없습니다.** | https://pypi.org/project/ansys-aedt-mcp/ , https://aedt-mcp.docs.pyansys.com/version/stable/user_guide/tools_and_capabilities.html (상) |
| **ansys-mechanical-mcp** (PyMechanical-MCP) | https://github.com/ansys/pymechanical-mcp | 공식 (ANSYS, Inc.) | Apache-2.0 | v0.3.0 (2026-10-14). PyPI 7회 릴리즈, Alpha, 마지막 push 2026-10-21, 커밋 134, ★27 | ○ 기본은 stdio입니다. HTTP는 "신뢰망 또는 인증과 TLS 뒤에서"만 쓰라고 권고합니다. Docker로 띄운 원격 Mechanical도 지원합니다. | 도구 28개(launch, connect, 파일 업로드와 다운로드, solve, 결과 export, 속성 변경, `run_python_code`)입니다. 자체 인증은 없고 mTLS는 옵션입니다. | https://pypi.org/project/ansys-mechanical-mcp/ , GitHub README (상) |
| ansys-mapdl-mcp | https://github.com/ansys/pymapdl-mcp | 공식 | Apache-2.0 | v0.3.2 (2026-10-07), Alpha, ★11 | ○ | 위와 같은 계열(코드 실행) | PyPI, GitHub API (상) |
| ansys-fluent-mcp / pycfx-mcp / pylumerical-mcp | https://github.com/ansys/pyfluent-mcp 외 | 공식 | Apache-2.0 | Fluent 0.5.0 (2026-09-25)은 도구 20개이고 trusted publishing으로 배포합니다. CFX는 v0.2.0 (2026-08-19), Lumerical은 마지막 push 2026-10-19입니다. | ○ | HTTP는 신뢰망에서만 쓰라고 권고합니다. | https://pypi.org/project/ansys-fluent-mcp/ , https://glama.ai/mcp/servers/ansys/pycfx-mcp (상과 중). 3과제의 직접 대상은 아닙니다(유동과 광자). |
| ansys-common-mcp | https://github.com/ansys/pyansys-common-mcp | 공식 | Apache-2.0 | 0.3.6 (2026-10-05), Alpha, 월 다운로드 약 3.3만(pypistats, 검색 요약) | ○ | 샌드박스와 허용 목록 기능은 문서에 없습니다. | https://pypi.org/project/ansys-common-mcp/ (상). 사내 MCP를 만들 때 지속 세션과 수명주기 패턴의 **참고 구현**으로 씁니다. |
| 커뮤니티 Ansys 래퍼 (LaplaceYoung/ansys-aedt-mcp, vorobjewsen30-max 등) | https://glama.ai/mcp/servers/vorobjewsen30-max/ansys-mcp-server | 커뮤니티 | LaplaceYoung 것은 PolyForm **Noncommercial**(glama 표기, GitHub에는 NOASSERTION) | 2026-05-21 생성, ★51 |, | 상용 목적으로 쓸 수 없는 라이선스이고 검증도 되지 않았습니다. | 검색 요약 (하). **제외합니다.** 공식 서버가 있으니 필요도 없습니다. |
| **MATLAB MCP Server** (옛 이름 MATLAB MCP Core Server) | https://github.com/matlab/matlab-mcp-server | 공식 (MathWorks) | BSD 유사 라이선스이지만 "**MathWorks 제품과 함께 쓰는 용도로만**" 쓰도록 제한합니다. | v0.15.0 (2026-10-15), ★1,697. 2025-10-31 공개(블로그는 2025-11-03) | ○ Go 바이너리이고 로컬에 MATLAB R2020b 이상이 있어야 합니다. | MATLAB 코드를 실행합니다. v0.14.0 (2026-09-25)에 "telemetry collection 갱신"이 있어 **망분리 환경에서는 꺼야 하고, 꺼졌는지 확인해야 합니다.** | https://blogs.mathworks.com/deep-learning/2025/11/03/releasing-the-matlab-mcp-core-server-on-github/ , https://github.com/matlab/matlab-mcp-core-server/releases (상) |
| zemax-mcp-server (OpticStudio ZOS-API) | https://glama.ai/mcp/servers/xbthp6dblz | 커뮤니티 | **미확인** | README 기준 OpticStudio 2025 R2.02에서 검증 | △ 로컬 OpticStudio와 pythonnet이 필요합니다. | 라이선스를 모르므로 코드 재사용은 보류합니다. | 검색 요약 (하) |
| CODE V / optiSLang / 공차(CETOL, 3DCS) MCP |, |, |, | **미확인** (못 찾음) |, |, |, |

### 2-2. PLM

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **Windchill AI Assistant MCP** | https://support.ptc.com/help/windchill/ai_plugin/en/Windchill_Help_Center/document_vault/WCAIAssistAIPluginMCPServer.html | 공식 (PTC) | 상용 플러그인 | 플러그인 2026.1.0.11에서 추가됐습니다(검색 요약). | △ 엔드포인트는 사내 서버(`https://<host>/Windchill/WCPlugins/wcaiassistant/mcp`)에 있습니다. 하지만 AI 추론 도구 3개가 어디서 처리되는지는 **문서에 없습니다.** | 도구 6개는 **문서와 도움말 검색과 요약뿐이고 부품과 BOM 도구는 없습니다.** 인증은 basic 또는 SSO이고, SSO를 지원하지 않는 클라이언트는 프록시가 필요합니다. | 상 |
| Windchill/Codebeamer MCP 로드맵 | https://community.ptc.com/windchill-10/windchillpdmlink-and-mcp-172038 | PTC 커뮤니티 |, | 2026-02 글: "로드맵 평가 중" |, | 사용자가 직접 만든 사례만 있습니다. | 중 |
| Teamcenter 공식 |, | **없음** |, | 2026-10-01까지 공개 발표에 없습니다. Siemens AI Registry에 있는 MCP는 개발자 포털 문서용입니다. Teamcenter 2606의 AI BOM agent는 Siemens 자체 에이전트이고 MCP가 아닙니다. |, |, | https://inteliscience.net/teamcenter-mcp-server/ (2026-10-05, 하), https://news.siemens.com/en-us/realize-live-americas-2026-recap-day-1/ (2026-06, 중) |
| tc-mcp | https://github.com/goenninger-b-t/tc-mcp | 커뮤니티 | **라이선스 없음**이라 코드를 재사용할 수 없습니다. | ★8. 2026-03-19에 만든 뒤로 push가 없습니다. Teamcenter 2412 이상, 도구 30여 개 | ○ | 쓰기 도구가 들어 있습니다. | GitHub API (상). **설계 참고만** 합니다. |
| 3DEXPERIENCE | https://glama.ai/mcp/servers/integrations/dassault-systemes | 공식 **미확인** |, | 공식 발표를 찾지 못했습니다. |, |, | 하 |
| aras-claude-agent | https://github.com/DaanTheoden/aras-claude-agent | 커뮤니티. Aras Labs가 fork해서 CWS, InnovatorEdge 지원을 더했습니다. | MIT | ★16, 마지막 push 2025-06-17 | ○ OAuth 2.0과 OData를 씁니다. | create item 같은 쓰기 도구가 있습니다. | https://community.aras.com/tag/aras%20labs (중) |

### 2-3. CAD / STEP

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| freecad-mcp | https://github.com/neka-nat/freecad-mcp | 커뮤니티 | MIT | PyPI 0.1.27 (2026-10-13), ★2,980 | ○ 로컬 FreeCAD에 연결합니다. | 도구 상세는 **미확인**이고, 코드 실행 도구가 있을 것으로 추정합니다. | GitHub API, PyPI (상) |
| build123d-mcp | https://github.com/pzfreo/build123d-mcp | 커뮤니티 | Apache-2.0 | PyPI 0.3.91 (2026-10-15). 릴리즈가 잦습니다. | ○ | Python 코드를 실행합니다. 벤치 점수는 저자가 직접 낸 것입니다. | PyPI (상), 검색 요약 (하) |
| cad-mcp-server (OCC 8.0 WASM, **읽기 전용**) | https://mcpservers.org/servers/mattmohandiss/cad-mcp-server | 커뮤니티 | **미확인** | npm 0.8.1 (2026-10-19) | ○ 커널이 패키지에 들어 있습니다. | 읽기 전용이라 위험이 낮습니다. `npx -y`로 매번 최신판을 받아 쓰는 방식은 금지합니다. | npm 조회 (상), 검색 요약 (하). H1 STEP 정합성의 후보입니다. |
| cadquery-mcp-server | https://glama.ai/mcp/servers/@rishigundakaram/cadquery-mcp-server | 커뮤니티 |, | 생성 도구가 아직 빈 껍데기(stub)입니다. |, |, | 하. 제외합니다. |

### 2-4. MBSE

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **AI for Capella** (Obeo) | https://www.obeosoft.com/en/products/ai-for-capella/ | 공식 (Capella 주 개발사) | **상용** (견적 요청) | 제품 목록에 "Early Adopter Program"으로 표기돼 있고 날짜는 없습니다. | 배포 형태와 로컬 LLM 지원은 **문서에 없습니다.** | 모델 편집과 다이어그램 수정을 하지만, 권한 범위 안에서만 한다고 설명합니다. | https://www.obeosoft.com/en/products/ (상, 날짜 미표기). 사면 외주가 아니라 도구 구매입니다(사용자 조건과 충돌하지 않음). |
| @casys/mcp-syson (SysML v2, SysON) | https://jsr.io/@casys/mcp-syson/0.6.0/README.md | 커뮤니티 | **미확인** | 0.6.0, 도구 31개. SysON v2026.7.0을 셀프호스트해야 합니다. | ○ | 모델 편집 도구가 있습니다. | 검색 요약 (하) |
| SysML v2 REST API MCP | https://3dswym.3dexperience.3ds.com/en/post/catia-mbse-cyber-systems/mcp-for-sysml-v2-rest-api-200-productivity-increase_esend0xeT_6tMsOIzOh0xA | 커뮤니티 (3DSwym) | 미확인 | 작성자 스스로 "초기 WIP"라고 합니다. **"200% 생산성"은 게시자 주장입니다.** |, | 관리자 토큰을 씁니다. | 하 |
| Cameo Bridge (CATIA Magic) | https://mcpmarket.com/server/cameo-bridge | 퍼블리셔 **미확인** | 미확인 |, |, | **Groovy 스크립트 실행**과 Java API 전체 노출 → 위험이 높습니다. | 하 |
| 학술: SysML v2 API용 MCP 프레임워크 | https://cris.fau.de/publications/366869202 (DOI 10.1017/pds.2026.10630) | Bazzal et al. 2026 |, | 논문 |, |, | 중 |
| py-capellambse 기반 MCP |, | **미확인** |, | 못 찾음 |, |, |, |

### 2-5. 시뮬레이션

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| NVIDIA kit-usd-agents (USD Code, Kit, OmniUI, Isaac Sim MCP) | https://github.com/NVIDIA-Omniverse/kit-usd-agents | 공식 (NVIDIA) | Apache-2.0 | ★114, 마지막 push 2026-10-13, 릴리즈 태그 없음 | △ 기본 설정은 **NVIDIA 클라우드 embedder, reranker(API 키)**를 씁니다. 로컬 NIM으로 돌리려면 GPU 2장이 필요합니다. | **문서와 코드 검색용입니다.** 실행 중인 시뮬레이터를 제어하지 않습니다. 그래서 통합 코드 절감은 0이고, 효과는 바이브 코딩 보조 몫입니다. | https://docs.isaacsim.omniverse.nvidia.com/latest/development_tools/isaac_sim_mcp.html (상) |
| Isaac Sim 실시간 제어 MCP (커뮤니티 여러 개) | https://glama.ai/mcp/servers/m0aaewzh5q , https://mcpservers.org/servers/whats2000/isaacsim-mcp-server | 커뮤니티 | **미확인** | Isaac Sim 5.1.0용, Ubuntu 전용(검색 요약) | ○ | 코드 실행이 포함됩니다. | 하. 상세 **미확인** |
| CARLA-MCP | https://glama.ai/mcp/servers/codebymov/CARLA-MCP | 커뮤니티 | MIT | ★1. 2026-06-08 생성, carla 0.9.15 | ○ | LLM이 직접 코드를 쓰지 않고 검증된 manifest 안에서 도구만 고르는 구조라 위험이 낮습니다. | GitHub API (상). V8 시나리오 생성의 **참고 구현**입니다. |
| OpenSCENARIO MCP |, | **없음** |, | ScenarioRunner가 OpenSCENARIO 파일을 실행합니다. |, |, | https://scenario-runner.readthedocs.io/en/latest/getting_started/ (상) |
| **ros-mcp-server** | https://github.com/robotmcp/ros-mcp-server | 커뮤니티 (robotmcp) | Apache-2.0 | v3.1.2 (2026-09-23), ★1,502, 커밋 401. ROS 1과 ROS 2(Jazzy, Humble) 지원 | ○ rosbridge를 거쳐 연결합니다. | 토픽 발행, 서비스와 액션 호출, 파라미터 설정을 합니다. 즉 **장비와 시뮬레이터에 명령을 보냅니다.** rosbridge의 노출과 인증은 **미확인**이라 localhost 바인딩을 권고합니다. | GitHub API, PyPI `ros-mcp` (상) |
| WiseVision mcp_server_ros_2 | https://enterprisedna.co/directories/mcp/wisevision-mcp-server-ros-2 | 커뮤니티 | MPL-2.0 | 마지막 갱신 2026-05-08(집계 사이트) | ○ |, | 하 |

### 2-6. 데이터와 검색

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **MCP Toolbox for Databases** | https://github.com/googleapis/mcp-toolbox | 공식 (Google) | Apache-2.0 | ★16,696, 마지막 push 2026-10-21 | ○ 바이너리나 컨테이너로 셀프호스트합니다. | Postgres, MySQL, SQL Server, Oracle 등을 지원하고, README에 SQLite는 없습니다. 미리 만들어 둔 `execute_sql`은 쓰기도 할 수 있으므로 **파라미터 SQL로 정의한 사용자 도구만 노출**합니다. | 상 |
| postgres-mcp (Crystal DBA) | https://github.com/crystaldba/postgres-mcp | 커뮤니티 (업체) | MIT | ★3,413. PyPI 0.3.0 (2025-05-16) 이후 릴리즈가 없습니다(push는 2026-08-17). | ○ | 릴리즈가 멈춰 있습니다. | GitHub API, PyPI (상) |
| Postgres 레퍼런스 (@modelcontextprotocol/server-postgres) |, | 레퍼런스 |, | npm 0.6.2 (2024-12-04), **지원 중단** |, | **SQL 인젝션으로 읽기 전용을 우회할 수 있고 npm 패키지는 패치되지 않았습니다**(Datadog 2025-08-21). | https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/ (중). **사용 금지** |
| SQLite 레퍼런스 (mcp-server-sqlite) |, | 레퍼런스 |, | PyPI 2025.4.25 이후 릴리즈가 없습니다. | ○ | 유지보수가 끝난 것으로 추정합니다. | PyPI (상). 비권장 |
| mcp-server-qdrant | https://github.com/qdrant/mcp-server-qdrant | 공식 | Apache-2.0 | v0.8.1 (2025-12-10), ★1,552 | △ FastEmbed 모델(all-MiniLM-L6-v2)을 미리 캐시해 둬야 합니다. | 저장(store) 도구가 쓰기를 합니다. | 상 |
| mcp-server-milvus | https://github.com/zilliztech/mcp-server-milvus | 공식 (Zilliz) | Apache-2.0 | ★245, 마지막 push 2026-08-11, 릴리즈 태그 없음 | ○ | insert, delete, create_collection 도구가 있어 **읽기 전용으로 구성**해야 합니다. | 상 |
| chroma-mcp | https://github.com/chroma-core/chroma-mcp | 공식 | Apache-2.0 | PyPI 0.2.6 (2025-08-14), 마지막 push 2025-09-17로 **1년째 정체**입니다. | △ | 외부 임베딩 API 옵션이 있습니다. | 상. 비권장 |
| Elasticsearch MCP (옛 서버) | https://github.com/elastic/mcp-server-elasticsearch | 공식 | Apache-2.0 | **지원 중단**, 중요 보안 패치만 나옵니다. 대체품은 Agent Builder MCP 엔드포인트(Elastic 9.2.0 이상)입니다. | ○ | Agent Builder가 어느 라이선스 등급에 포함되는지는 **미확인**입니다. | 상 |
| opensearch-mcp-server-py | https://github.com/opensearch-project/opensearch-mcp-server-py | 공식 | Apache-2.0 | PyPI 0.12.0 (2026-09-17), ★155 | ○ | `GenericOpenSearchApiTool`이 **아무 API나 호출**할 수 있어 비활성화해야 합니다. | 상 |

### 2-7. 문서 파싱

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **docling-mcp** | https://github.com/docling-project/docling-mcp | 공식 (LF AI & Data, IBM Research가 시작) | MIT (모델은 각자 라이선스) | v3.3.0 (2026-10-06), ★776. mcp SDK 2.x에 의존합니다. | △ local 모드로 돌릴 수 있지만 레이아웃과 OCR 모델을 미리 내려받아 둬야 합니다. | URL 입력을 받으면 외부에서 가져옵니다 → 허용 경로를 제한합니다. | 상 |
| markitdown-mcp | https://github.com/microsoft/markitdown | 공식 (Microsoft) | MIT | **0.0.1a7 (2026-09-14, alpha)** | ○ | 외부 변환 서비스(Azure 등) 옵션은 끕니다. | PyPI (상) |
| UNS-MCP (Unstructured) | https://github.com/Unstructured-IO/UNS-MCP | 공식 | 표기 없음 | "**not actively maintained**" | × Unstructured API 키가 필요합니다. |, | 상. **제외** |

### 2-8. ML

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **MLflow MCP** (내장) | https://mlflow.org/docs/latest/genai/mcp/ | 공식 | Apache-2.0 | MLflow 3.5.1 이상에 들어 있는 **experimental** 기능입니다. 최신 MLflow는 3.17.2 (2026-10-21)입니다. | ○ 로컬 tracking 서버를 씁니다. | 도구 10개가 **모두 trace, assessment용**이고, 실험이나 run 지표를 조회하는 도구는 없습니다. `delete_traces` 같은 쓰기 도구가 있습니다. | 상 |
| wandb-mcp-server | https://github.com/wandb/wandb-mcp-server | 공식 | MIT | 0.4 라인, ★72 | × 호스팅판은 mcp.withwandb.com입니다. △ 셀프 관리판은 Helm 컴포넌트를 켜야 하고 계정팀이 활성화해 줘야 합니다. | `WANDB_MCP_ACCESS_MODE=read-only`가 있습니다. | 상. W&B를 이미 쓰는 경우에만 해당합니다. |
| hf-mcp-server | https://github.com/huggingface/hf-mcp-server | 공식 | MIT | v0.4.31 (2026-10-19) | × Hub에 인터넷으로 접속해야 합니다. |, | 상. C0 개발 PC에서만 씁니다. |

### 2-9. 인프라

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **kubernetes-mcp-server** | https://github.com/containers/kubernetes-mcp-server | `containers` 조직(Red Hat 계열인지는 **미확인**) | Apache-2.0 | v0.0.67 (2026-09-18), ★2,174. 1.0 이전입니다. | ○ Go 단일 바이너리입니다. | `read_only`와 `denied_resources`로 막을 수 있습니다. helm, kubevirt 도구 묶음은 기본 꺼짐이고, HTTP 모드는 OAuth/OIDC를 씁니다. | 상 |
| **mcp-grafana** | https://github.com/grafana/mcp-grafana | 공식 | Apache-2.0 | v2.1.1 (2026-10-20), ★3,584 | ○ 셀프호스트 Grafana 9 이상을 지원합니다. | `--disable-write`와 `--disable-query`가 있고, 네트워크 모드는 bearer 토큰과 TLS를 씁니다. **Prometheus, Loki 질의가 들어 있어 Prometheus MCP를 따로 둘 필요가 없습니다.** | 상 |
| prometheus-mcp-server | https://github.com/pab1it0/prometheus-mcp-server | 커뮤니티 | MIT | ★519, 마지막 push 2026-10-19 | ○ |, | 상. Grafana MCP로 대체합니다. |
| Slurm MCP (mcp-slurm 등 여러 개) | https://mcpmarket.com/server/slurm , https://glama.ai/mcp/servers/gj6wld13o4 | 커뮤니티 | 라이선스와 테스트 표기가 없습니다. |, | ○ SSH로 연결합니다. | sbatch, scancel 권한을 씁니다. | 하. **참고만** |

### 2-10. 협업

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **GitHub MCP** | https://github.com/github/github-mcp-server | 공식 | MIT | v2.0.2 (2026-10-08), ★33,807 | ○ 로컬판(Docker, 바이너리)은 GHES를 지원합니다(`--gh-host`). 원격판은 GHES를 지원하지 않습니다. | `--read-only`와 toolsets가 있습니다. 2025-05에 공개 이슈의 prompt injection으로 비공개 저장소가 유출된 사례가 있습니다(3장). | 상 |
| GitLab MCP (내장 `/api/v4/mcp`) | https://innfactory.ai/en/services/companygpt/integrations/gitlab/ | 공식 | GitLab 라이선스 | self-managed에서는 18.6부터 **beta**라고 합니다(2차 출처). GA 여부는 **미확인**입니다. | ○ | GitLab Duo가 필요합니다. | 하. MCP 클라이언트 쪽은 18.8에서 GA: https://git.isis.vanderbilt.edu/help/user/gitlab_duo/model_context_protocol/mcp_clients.md (중) |
| Atlassian Rovo MCP | https://developer.atlassian.com/cloud/rovo-mcp/ | 공식 | 상용 | GA | × **Cloud 전용**입니다. |, | 상 |
| mcp-atlassian | https://github.com/sooperset/mcp-atlassian | 커뮤니티 | MIT | v0.23.1 (2026-08-19), ★6,022 | ○ | Server/Data Center 지원 여부는 **이번 조사에서 확인하지 못했습니다.** | GitHub API (상) |
| Microsoft Agent 365 MCP (Teams, Outlook, SharePoint) | https://www.scalekit.com/blog/microsoft365-mcp-vs-api | 공식 | M365 Copilot, Agent 365 라이선스 | "2026-05-01 GA"는 2차 출처 주장이고, Microsoft 문서에는 Frontier preview라고 돼 있어 서로 **어긋납니다.** | × 클라우드 |, | 하 |
| ms-365-mcp-server | https://github.com/Softeria/ms-365-mcp-server | 커뮤니티 | MIT | v0.170.2 (2026-10-19), ★1,063 | × Graph API | 메일과 파일 쓰기 권한을 씁니다. | 상 |

### 2-11. 기타 (레퍼런스 서버 등)

| 서버 | URL | 제공자 | 라이선스 | 성숙도 | 망분리 | 보안 위험 | 출처와 신뢰도 |
|---|---|---|---|---|---|---|---|
| **filesystem** | https://github.com/modelcontextprotocol/servers | 레퍼런스 (MCP 프로젝트) | 저장소는 NOASSERTION | npm 2.0.0 (2026-10-19) | ○ | **CVE-2025-53109, 53110**(심볼릭 링크와 접두어 비교로 허용 디렉터리를 벗어남)이 있었고 2025.7.1에서 고쳐졌습니다. | https://cymulate.com/blog/cve-2025-53109-53110-escaperoute-anthropic/ (중) |
| **git** | 같음 | 레퍼런스 | MIT (PyPI) | PyPI 2026.10.19 | ○ | **CVE-2025-68143, 68144, 68145**가 있었고 2025.12.18에서 고쳐졌습니다. 악성 README나 이슈만 읽혀도 터질 수 있는 결함이었고, filesystem과 함께 쓰면 코드 실행까지 이어졌습니다. | https://thehackernews.com/2026/01/three-flaws-in-anthropic-mcp-git-server.html , https://www.theregister.com/2026/01/20/anthropic_prompt_injection_flaws/ (중) |
| fetch | 같음 | 레퍼런스 | MIT | PyPI 2026.10.19 | △ | 망분리 환경에서는 사내 URL에 접근할 수 있어 **SSRF 경로**가 됩니다. | PyPI (상) |
| memory | 같음 | 레퍼런스 |, | npm 2.0.0 (2026-10-19) | ○ | 지식 그래프 파일에 **등급이 다른 데이터가 섞입니다.** | npm (상) |
| Playwright MCP | https://github.com/microsoft/playwright-mcp | 공식 (Microsoft) | Apache-2.0 | v0.0.83 (2026-09-28), ★38,446 | ○ | 웹 콘텐츠를 거친 prompt injection 경로가 됩니다. | 상 |
| mcp-remote | npm `mcp-remote` | 커뮤니티 |, | 0.15.2 (2026-10-20) |, | **CVE-2025-6514** (CVSS 9.6, OAuth 엔드포인트를 통한 OS 명령 실행)가 있었고 0.1.16에서 고쳐졌습니다. | https://jfrog.com/blog/2025-6514-critical-mcp-remote-rce-vulnerability/ (중) |

### 2-12. 런타임과 레지스트리 (1안 / 2안 연결)

| 항목 | 내용 | 출처와 신뢰도 |
|---|---|---|
| MCP 스펙 | 최신판은 **2026-07-28**입니다. 기본 프로토콜이 stateless로 바뀌었고 Tasks 확장(장시간 작업)이 들어왔습니다. 도구 설명은 "신뢰할 수 있는 서버가 아니면 믿지 말 것"이라고 적혀 있습니다. | https://modelcontextprotocol.io/specification/latest (상) |
| Python `mcp` SDK | 2.3.0 (2026-10-02)입니다. docling-mcp 3.x는 mcp 2.x를 요구하므로 **서버마다 SDK 메이저 버전을 맞춰야 합니다.** | https://pypi.org/project/mcp/ (상) |
| LangGraph 연결 | `langchain.mcp` (`langchain[mcp]>=1.4.0`, **beta**, FastMCP 기반)가 `langchain-mcp-adapters`를 대체했습니다. 옛 저장소는 **archived** 상태입니다(GitHub API, 마지막 push 2026-09-16). stdio와 Streamable HTTP를 지원합니다. | https://docs.langchain.com/oss/python/migrate/langchain-mcp-adapters (상) |
| Claude Agent SDK | Claude Code 하네스를 라이브러리로 제공하고 MCP 클라이언트가 내장돼 있습니다. 배포는 직접 합니다. | claude-api 스킬 캐시 2026-10-06 |
| 공식 MCP Registry | 2025-09-08부터 preview이고, API는 v0.1로 동결돼 있으며 GA는 발표되지 않았습니다(2026-09-26 확인, 2차 출처). 이름공간 검증은 **메타데이터를 누가 올렸는지만 증명하고, 엔드포인트가 그 사람 것인지는 증명하지 않습니다.** | https://developertoolkit.ai/en/ecosystem/mcp/registry-and-gateways/ (하) |
| Docker MCP Catalog / Gateway | Docker가 빌드한 서버는 서명돼 있고 SBOM과 출처 정보(provenance)가 붙습니다. `docker mcp gateway run --verify-signatures`로 확인합니다. 아직 **Beta**이고 Docker 스스로 "best-effort"라고 합니다. | https://docs.docker.com/ai/mcp-catalog-and-toolkit/catalog/ (상) |
| snyk/agent-scan (옛 Invariant mcp-scan) | Apache-2.0, ★3,155입니다. 분석할 때 **도구 이름, 설명, 서버 설정을 Snyk API로 보냅니다.** 그래서 망분리 환경에서는 그대로 쓸 수 없고 `inspect`(분석 없이 목록만 보기) 정도만 됩니다. | https://github.com/snyk/agent-scan (상) |

---

## 3. MCP 공급망 보안 사례 (2025~2026)

| 날짜 | 사례 | 유형 | 내용 | 3과제 시사점 | 출처와 신뢰도 |
|---|---|---|---|---|---|
| 2025-04 | Invariant Labs의 tool poisoning 시연 | 도구 설명 오염 | 겉보기에 무해한 "add" 도구의 설명 속에 `~/.ssh/id_rsa`를 읽으라는 숨은 지시를 넣었습니다. | 도구 설명 원문을 검토하고 해시를 고정합니다. | https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-tool-poisoning-ai-agent-exfiltration-2/ (2026-07-02, 중) |
| 2025-05 | GitHub MCP prompt injection | 위험한 흐름(toxic flow) | 공개 이슈에 숨긴 지시를 읽은 에이전트가 권한이 큰 토큰으로 비공개 저장소 내용을 공개 PR에 올렸습니다. | read-only로 쓰고 토큰 범위를 최소화합니다. 외부 콘텐츠를 읽는 에이전트와 C3 데이터를 쥔 에이전트를 분리합니다. | 위와 같음 (중) |
| 2025-06~07 | MCP Inspector CVE-2025-49596 (CVSS 9.4, Oligo), Filesystem CVE-2025-53109/53110, Cursor CVE-2025-54136 (승인 뒤 도구가 바뀌는 rug pull 유형, 8.8) | RCE, 경로 탈출과 rug pull | 개발 도구와 레퍼런스 서버 자체에서 나온 결함입니다. | 개발 도구도 검증 대상에 넣습니다. 승인한 뒤에도 도구 정의가 바뀌는지 감시합니다. | https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-by-design-rce-ox-security-20260420/ (중), https://www.waxell.ai/blog/mcp-rug-pull-attack (하) |
| 2025-07 | mcp-remote CVE-2025-6514 (CVSS 9.6) | 클라이언트 RCE | 악성 서버가 보낸 OAuth URL로 Windows에서 임의 명령을 실행했습니다. | 원격 MCP는 사내 TLS로만 연결합니다. 프록시 패키지도 버전을 고정합니다. | https://jfrog.com/blog/2025-6514-critical-mcp-remote-rce-vulnerability/ (중) |
| 2025-08-21 | Postgres 레퍼런스 서버 SQL 인젝션 | 읽기 전용 우회 | `COMMIT;`를 끼워 넣어 읽기 전용 트랜잭션을 끝냈습니다. 지원이 중단된 뒤에도 주 2.1만 회 다운로드되고 있었습니다. | **지원 중단 패키지는 쓰지 않습니다.** DB 권한은 DB 계정 수준에서 읽기 전용으로 겁니다. | https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/ (중) |
| 2025-09 (1.0.16, 09-17) | **postmark-mcp**, 처음 확인된 실전 악성 MCP | 이름 사칭(typosquat)한 뒤 악성 업데이트 | 정상 버전을 여러 번 낸 뒤, 코드 한 줄을 추가해 모든 메일을 공격자에게 숨은 참조(BCC)로 보냈습니다. 주 약 1,500회 다운로드됐습니다. | **버전을 고정하고, 업데이트 전후 차이를 검토**합니다. 저장소 퍼블리셔가 진짜 벤더인지 확인합니다. | https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/ (2025-09-25, 중), https://csoonline.com/article/4064009/trust-in-mcp-takes-first-in-the-wild-hit-via-squatted-postmark-connector.html (중) |
| 2025-06 (공개 2025-10) | Smithery 호스팅 경로 탈출 | 레지스트리와 호스팅 침해 | 빌드 경로 조작으로 Fly.io 토큰이 노출됐고, 호스팅 서버 3,000여 개가 위험했습니다. | **외부 호스팅 MCP를 쓰지 않고**, 사내에서 직접 빌드합니다. | https://scworld.com/news/smithery-ai-fixes-path-traversal-flaw-that-exposed-3000-mcp-servers (중) |
| 2026-01 공개 | Anthropic mcp-server-git CVE-2025-68143/68144/68145 | prompt injection → 경로와 인자 주입 | 기본 설치에서도 영향을 받았고, filesystem과 함께 쓰면 코드 실행까지 갔습니다. 2025.12.18에서 고쳐졌습니다. | **공식 레퍼런스 서버도 검증 대상입니다.** LangGraph 트랙의 git, filesystem은 최신 버전으로 고정합니다. | https://thehackernews.com/2026/01/three-flaws-in-anthropic-mcp-git-server.html (중) |
| 2026-02-17 | Clinejection (cline@2.3.0) | 배포 토큰 탈취 | AI 이슈 분류 봇에 prompt injection을 넣어 CI 자격 증명을 얻은 뒤 악성 버전을 배포했습니다. 8시간 동안 약 4,000회 다운로드됐습니다(OSV MAL-2026-1380). | **`npx`, `uvx`로 실행할 때마다 최신판을 받는 방식을 금지**하고 사내 미러를 씁니다. | https://security.snyk.io/package/npm/cline/2.3.0 , https://osv.dev/vulnerability/MAL-2026-1380 (중) |
| 2026-02 (보도 02-26) | **SANDWORM_MODE** (Socket) | 웜 + 악성 MCP 주입 | 이름을 사칭한 npm 패키지 19개(`claud-code` 등)가 퍼졌습니다. McpInject 모듈이 가짜 MCP 서버(index_project, lint_check, scan_dependencies)를 AI 코딩 도구 설정에 등록했습니다. 그 도구 설명에 SSH, AWS, npm 비밀값을 몰래 모으고 "사용자에게 말하지 말라"는 지시가 들어 있었습니다. | 바이브 코딩 PC의 **MCP 설정 파일 변경을 감시**하고 허용 목록을 강제합니다. | https://heise.de/-11190731 (중), https://thehackernews.com/2026/02/malicious-npm-packages-harvest-crypto.html (중, 본문 403) |
| 2026-02 | ClawHub 악성 skill 1,184개 (Antiy CERT) | 에이전트 마켓 오염 | MCP가 아니라 OpenClaw skill 마켓에서 일어났습니다. | Skills, 서브에이전트 템플릿도 같은 반입 절차를 거칩니다. | https://blog.cyberdesserts.com/ai-agent-security-risks/ (하) |
| 2026-03-31 | Axios npm 침해 (UNC1069) | 메인테이너 계정 탈취 | MCP 전용 사고는 아닙니다. 하지만 npm에 기대는 MCP 서버와 AI 도구가 모두 노출됐고, 노출 시간은 약 3시간이었습니다. | npm 계열 서버는 lockfile과 `npm ci`로 설치하고 이미지 digest를 고정합니다. | https://labs.cloudsecurityalliance.org/research/csa-research-note-axios-npm-supply-chain-unc1069-20260401-cs/ (중하. AI 보조로 쓴 노트이고 CSA 검토를 거치지 않음) |
| 2026-04-15 | **OX Security "MCP by design" STDIO 명령 실행** | SDK 설계 문제 | 공식 SDK 4종(Python, TS, Java, Rust)이 STDIO 설정의 `command`를 그대로 실행합니다. OX 추정은 다운로드 약 1.5억, 공개 서버 7,000개 이상, 취약 인스턴스 최대 20만입니다. 레지스트리 11곳 중 9곳이 악성 PoC를 심사 없이 받았습니다. Anthropic은 "의도된 동작"이라며 SECURITY.md만 고쳤습니다. | **설정 파일(`command`)을 실행 표면으로 취급**합니다. 허용 목록은 모델이 바꿀 수 없는 곳에 둡니다. | https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-by-design-rce-ox-security-20260420/ (2026-04-20, 중. 수치는 OX 추정), https://www.tomshardware.com/tech-industry/artificial-intelligence/anthropics-model-context-protocol-has-critical-security-flaw-exposed (중) |
| 2026-05-20 | NSA CSI "MCP: Security Design Considerations for AI-Driven Automation" | 정부 지침 | MCP 도입 속도가 보안 모델을 앞질렀다고 경고했습니다. 접근 통제, 승인 흐름, 감사 로그, 토큰과 세션 관리가 핵심입니다. | 사내 검증 체크리스트의 근거로 씁니다. | https://executivegov.com/articles/nsa-model-context-protocol-deployment (중. NSA 원문 페이지는 403) |
| 2026 상반기 | 노출 서버와 CVE 집계 | 통계 | Trend Micro는 노출 서버를 1,467개로, 다른 집계는 원격 서버의 약 40%가 인증이 없다고 봅니다. nginx-ui MCP CVE-2026-33032 (9.8)는 실제 공격에 쓰였다고 합니다. 집계마다 수치가 다릅니다. | 외부에 노출하지 않습니다. HTTP 모드에는 인증을 반드시 겁니다. | https://www.trendmicro.com/vinfo/us/security/news/vulnerabilities-and-exploits/update-on-exposed-mcp-servers-the-threat-widens-to-the-cloud , https://adversa.ai/blog/top-mcp-security-resources-june-2026/ (하) |
| 상시 | OWASP MCP Top 10 | 위험 분류 | MCP01~10(토큰 관리, 권한 확대, tool poisoning, 공급망, 명령 주입, 그림자 서버 등)이고 아직 **beta**입니다. | 검증 항목의 분류 체계로 씁니다. | https://owasp.org/www-project-mcp-top-10/ (상) |

---

## 4. 사내 도입 검증 절차와 공수

### 4-1. 위험 등급 (서버마다 정함)

| 등급 | 기준 | 2027 후보 | 근거 |
|---|---|---|---|
| T1 (높음) | 코드를 실행하거나, 해석, 장비, 클러스터에 명령을 보내거나, C3 원본을 다룹니다. | ansys-aedt-mcp, ansys-mechanical-mcp, kubernetes-mcp-server, git, (ros-mcp-server, MATLAB) | 2-1, 2-5, 2-9, 2-11 표의 위험 열 |
| T2 (중간) | 사내 데이터를 읽고 일부 쓰기를 합니다. | 벡터DB MCP, MLflow MCP, mcp-grafana, filesystem, (MCP Toolbox) | 2-6, 2-8, 2-9 표 |
| T3 (낮음) | 로컬 변환만 하거나 읽기 전용 유틸리티입니다. | docling-mcp, (cad-mcp-server) | 2-7, 2-3 표 |

### 4-2. 절차와 단계별 일수 (추정, 1 MM = 20 근무일)

| 단계 | 할 일 | 도구와 근거 | T1 일 | T2 일 | T3 일 | 출처 |
|---|---|---|---|---|---|---|
| 0. 적합성 사전 시험 | 사내 버전(AEDT, Mechanical, DB)에서 1~2일 붙여 봅니다. **안 맞으면 여기서 멈춥니다.** | 보수 시나리오 손실을 막는 게이트 | 1~2 | 0.5~1 | 0.5 | 추정 |
| 1. 출처와 라이선스 | 저장소 소유자와 패키지 퍼블리셔가 같은지(PyPI trusted publishing), SPDX 라이선스, 유지보수 신호(최근 릴리즈와 이슈 대응)를 봅니다. | 라이선스 없음(tc-mcp), PolyForm NC, MathWorks 제한 같은 사례를 거릅니다. | 0.5 | 0.5 | 0.5 | 2장 표, https://www.backslash.security/learning/how-to-vet-an-mcp-server-before-you-approve-it-internally (하) |
| 2. 정적 검토 | 도구 설명 원문, 네트워크 호출, subprocess, eval을 소스에서 확인합니다. 의존성 CVE를 스캔(SCA)하고 SBOM을 만들고 비밀값 스캔을 합니다. | postmark-mcp처럼 한 줄 추가로 들어오는 악성 코드를 잡습니다. | 2~3 | 1~1.5 | 0.5~1 | https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/ |
| 3. 도구 줄이기 | read-only 플래그를 켭니다(GitHub `--read-only`, Grafana `--disable-write`, K8s `read_only`, W&B read-only). 위험한 도구(`run_python_code`, `GenericOpenSearchApiTool`, `execute_sql`)는 끄거나 허용 스크립트만 쓰게 합니다. | 각 README | 1 | 0.5 | 0.25 | 2장 표 |
| 4. 격리 동적 시험 | 망분리 샌드박스(egress 차단, DNS, 연결 로그)에서 실제 시나리오와 **prompt injection 문서와 이슈**, 경로 탈출 시험을 돌립니다. | CVE-2025-68143/53109 같은 유형을 재현합니다. | 2~3 | 1~1.5 | 0.5~1 | https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-by-design-rce-ox-security-20260420/ |
| 5. 반입과 고정 | 사내 PyPI, npm, 컨테이너 미러로 반입합니다. 버전과 해시를 고정하고(uv lock, `npm ci`, 이미지 digest) **`npx`, `uvx`로 최신판을 받는 방식은 금지**합니다. 도구 정의 해시를 기록해 rug pull을 감지합니다. | Clinejection, Axios 사례 | 1 | 0.5 | 0.5 | 3장 |
| 6. 실행 구성 | stdio를 기본으로 씁니다. HTTP를 쓸 때는 localhost에 바인딩하고 인증과 TLS(Ansys gRPC는 mTLS)를 겁니다. 서비스 계정 권한을 최소화하고, **C3 결과는 온프렘 LLM으로만 보내도록 등급 라우팅**하며 감사 로그를 남깁니다. | NSA CSI, 스펙의 "도구 호출 전 사용자 동의" | 1~2 | 0.5~1 | 0.25 | https://modelcontextprotocol.io/specification/latest , NSA CSI |
| 7. 승인과 등록 | Registry(C6) 카드에 버전, 해시, 권한, 담당자를 적고 허용 목록에 올립니다. | https://cerbos.dev/blog/mcp-server-vetting-checklist (2026-08-16, 하) | 0.5 | 0.5 | 0.25 |, |
| **합계 (첫 도입)** | | | **9~13일 = 0.45~0.65 MM** | **5~7일 = 0.25~0.35 MM** | **3~4일 = 0.15~0.2 MM** | 추정 |
| 8. 재검토 (매년) | 버전을 올릴 때 차이를 검토(도구 정의 변경 확인)하고, 분기마다 1회 보고 CVE를 감시합니다. Ansys 서버는 2~3주마다 릴리즈되므로 분기에 한 번 올립니다. | https://www.softwareseni.com/how-to-govern-and-operationalise-mcp-server-infrastructure-across-an-engineering-organisation (하) | 4~6일/년 | 2~3일/년 | 1일/년 | 추정 |
| 공통 1회 구축 | 사내 미러 경로, 샌드박스 VM, 체크리스트, 로컬 스캐너 구성을 한 번 만듭니다. agent-scan은 외부로 데이터를 보내므로 망분리용 대안이 필요합니다. | C11(바이브 코딩)과 C6(Registry)과 일부 공유합니다. |, |, |, | 추정: 0.25~1.0 MM |

### 4-3. 1개당 검증 공수 → 계획 값

| 시나리오 | 9개 구성 가중 평균. T1 4개(aedt, mechanical, K8s, git), T2 4개(벡터DB, MLflow, Grafana, filesystem), T3 1개(docling) | 계획 값 (`mcp_vetting_mm_per_server`) | 근거 |
|---|---|---|---|
| 보수 hi | T1 0.65, T2 0.35, T3 0.2 → (2.6+1.4+0.2)/9 = 0.47 | **0.45 MM** | 4-2 상단값. 사전 시험에서 실패하는 서버까지 포함한 값입니다. |
| 기준 base | T1 0.5, T2 0.28, T3 0.17 → (2.0+1.12+0.17)/9 = 0.37. 두 번째 서버부터 절차와 샌드박스를 재사용해 −15~20% 조정 | **0.30 MM** | 추정 |
| 낙관 lo | 공식 서버만 고르고 벤더 증명(trusted publishing, 서명 이미지와 SBOM)이 있어 정적 검토가 줄어든다고 가정 | **0.15 MM** | 추정, Docker 서명과 SBOM 문서 |

---

## 5. WP별 외부 MCP 매핑 (wp_map)

- **개발 MM**은 `model27.py` WP의 개발 역할(AI, CAE, ML, SIM, DATA, OPS, MBSE) 합계입니다. 운영 WP(A12, V12, H15)는 `live()` 프로파일 합계입니다. C13은 `portability_build_mm`이 아직 없어 2.5 MM으로 가정했습니다(추정).
- **절감률 hi = 보수(작은 값)**입니다. 기준 9개 서버(4-3)를 도입한다고 가정했습니다. 조건부 서버(ros2, Toolbox, MATLAB, 상용 Capella)는 lo에만 넣었습니다.

| WP | 쓸 외부 MCP | 개발 MM | saving hi / base / lo | 절감 MM (base) | 근거 (대신하는 통합 코드) |
|---|---|---|---|---|---|
| A1 EM 운영과 개선 | ansys-aedt-mcp (기존 PyAEDT 도구 계층을 점진적으로 대체) | 1.8 | 0 / 0.03 / 0.06 | 0.05 | '26.10 릴리즈본은 자체 도구 계층으로 이미 만들어져 있습니다. 바꾸면 이전 비용이 들고, 유지보수 몫만 줄어듭니다. |
| A2 설계지식DB(RAG) | docling-mcp, 벡터DB MCP 1개 (Qdrant/Milvus/OpenSearch 중 사내에서 고른 것) | 4.0 | 0.02 / 0.05 / 0.10 | 0.20 | 색인 배치는 MCP가 아니라 Docling 라이브러리를 직접 씁니다. 줄어드는 것은 에이전트가 쓰는 검색 도구 래퍼뿐이고, 등급별 접근 제어와 하이브리드 검색과 리랭크는 직접 만들어야 합니다. |
| A3 구조 해석 자동화 | **ansys-mechanical-mcp** (도구 28개) | 4.7 | 0.05 / 0.12 / 0.20 | 0.56 | 세션 시작과 연결, 파일 전송, solve, 결과 요약과 export, 속성 변경 도구를 직접 짜지 않습니다. 경계조건과 메시 스크립트와 al1-entity는 그대로 남습니다. Alpha 단계이고 사내 Mechanical 버전과 맞는지는 미확인입니다. |
| A5 열 해석 자동화 | ansys-aedt-mcp (Icepak) + ansys-mechanical-mcp (thermal) | 3.9 | 0.04 / 0.10 / 0.18 | 0.39 | Icepak은 AEDT 서버의 design type으로 들어 있습니다. Mechanical 쪽은 A3에서 연결한 것을 재사용합니다. |
| A7 야간 무인해석 | mcp-grafana (아침 리포트 지표), kubernetes-mcp-server (read-only 작업 상태). Slurm은 참고만 | 4.0 | 0.02 / 0.05 / 0.10 | 0.20 | 큐, 격리, 롤백은 결정론적 코드로 직접 만듭니다. 줄어드는 것은 에이전트가 하는 상태 조회와 리포트 질의 코드입니다. HPC 라이선스 풀용 MCP는 없습니다. |
| A9 최적화 탐색 | (조건부) MATLAB MCP Server | 2.3 | 0 / 0.02 / 0.08 | 0.05 | MATLAB 최적화 툴박스를 쓸 때만 해당합니다. Python(scipy, optuna)을 쓰면 0입니다. |
| A11 '28 광학 선행 | zemax-mcp-server (커뮤니티, ZOS-API), 참고 구현 | 1.5 | 0 / 0.05 / 0.10 | 0.08 | API 자동화 범위를 정할 때 참고합니다. 라이선스가 미확인이고, CODE V용은 없습니다. |
| A12 릴리즈 기능 운영 | ansys-aedt-mcp, ansys-mechanical-mcp | 2.5 | 0 / 0.02 / 0.05 | 0.05 | 벤더가 API 변경을 따라가 주지만 버전 올릴 때마다 재검증해야 해서 거의 상쇄됩니다. |
| V3 시뮬레이터와 엔진 연동 | 참고: ros-mcp-server, Isaac Sim 커뮤니티 서버, ansys-common-mcp 패턴. (조건부) 엔진이 ROS 2 기반이면 ros-mcp-server를 직접 씁니다. | 1.6 | 0.02 / 0.06 / 0.20 | 0.10 | lidar-engine MCP는 사내 API라서 직접 만들어야 합니다. lo는 ROS 2 토픽으로 바로 연결되는 경우입니다. |
| V6 엔진 검증 조율과 ODD Agent | MLflow MCP (에이전트 실행 trace), CARLA-MCP (참고, manifest 방식) | 2.6 | 0.02 / 0.06 / 0.12 | 0.16 | trace, 평가 기록 도구를 직접 짜지 않습니다. 시나리오 생성기는 직접 만듭니다. |
| V7 인지모델 검증과 Sim2Real | MLflow MCP (trace만), (조건부) W&B MCP | 2.8 | 0 / 0.03 / 0.08 | 0.08 | MLflow MCP에는 run 지표 도구가 없어 효과가 제한적입니다. |
| V8 ODD 시나리오 확충 | CARLA-MCP, ScenarioRunner, 참고 | 1.8 | 0 / 0.03 / 0.08 | 0.05 | OpenSCENARIO MCP는 없습니다. |
| V9 ODD 커버리지 측정 | mcp-grafana, (조건부) MCP Toolbox | 1.6 | 0 / 0.02 / 0.06 | 0.03 | 커버리지 DB 질의와 대시보드 조회만 해당합니다. |
| V10 엔진 KPI 판정 운영 | mcp-grafana (지연 지표) | 0.3 | 0 / 0.05 / 0.10 | 0.01 |, |
| V12 릴리즈 기능 운영 | MLflow, Grafana MCP | 2.9 | 0 / 0.02 / 0.04 | 0.06 | 운영 질의만 해당합니다. |
| H1 도면과 BOM 정합성 | docling-mcp (PDF 도면과 표), (조건부) cad-mcp-server (STEP 읽기 전용) | 1.8 | 0.02 / 0.05 / 0.10 | 0.09 | 도면 치수 추출은 전용 비전 모델이 필요해 직접 만듭니다. BOM은 사내 PLM에서 옵니다. |
| H2 PLM 연동 | **외부 MCP 없음**. 참고: tc-mcp(설계만, 라이선스 없음), aras-claude-agent(MIT), ansys-common-mcp 패턴, Windchill MCP(문서용) | 2.6 | 0 / 0.03 / 0.08 | 0.08 | 사내 PLM API용 MCP는 직접 만듭니다. 참고 구현을 재사용하는 몫만 셉니다. 사내 PLM 제품은 미확인입니다. |
| H3 설계변경 검토 Agent | (해당 거의 없음), 알림은 사내 메일과 메신저 API로 직접 | 1.8 | 0 / 0.03 / 0.06 | 0.05 | M365, Atlassian 공식 MCP는 클라우드 전용이라 C3 흐름에 쓸 수 없습니다. |
| H4 SI/PI 해석 | ansys-aedt-mcp (HFSS, Circuit, 3D Layout) | 2.6 | 0.02 / 0.06 / 0.12 | 0.16 | SIwave, EDB 전용 도구가 없어 PCB SI/PI 쪽은 pyedb로 직접 만듭니다. |
| H5 EMC 해석 | ansys-aedt-mcp (HFSS, Maxwell) | 2.6 | 0.03 / 0.07 / 0.14 | 0.18 | design type이 바로 들어 있습니다. |
| H6 RVTM 정의 | 참고: AI for Capella(상용), @casys/mcp-syson | 3.5 | 0 / 0.02 / 0.05 | 0.07 | 대부분 방법론과 모델링 작업이라 통합 코드 몫이 작습니다. |
| H7 요구 추적 Agent | (조건부) **Obeo AI for Capella** (상용 MCP). 아니면 py-capellambse로 직접 | 2.0 | 0 / 0.05 / 0.20 | 0.10 | lo는 상용 제품을 산 경우입니다. 가격과 배포 형태는 미확인입니다. |
| H8 설계자료 구성 Agent | filesystem, docling-mcp | 1.2 | 0.03 / 0.06 / 0.12 | 0.07 | 파일 묶기와 변환 도구를 직접 짜지 않습니다. PLM 조회는 H2 것을 씁니다. |
| H9 기구 열과 공차 | ansys-mechanical-mcp (열은 A5 재사용), (조건부) MATLAB | 2.2 | 0 / 0.03 / 0.08 | 0.07 | 공차 스택업 도구용 MCP는 미확인입니다. |
| H10 회로와 기구 1차 통합 | ansys MCP (이미 붙어 있음) | 1.4 | 0 / 0.02 / 0.05 | 0.03 | 통합 판정은 사내 로직입니다. |
| H11 AFM, 수율 PoC | (조건부) MCP Toolbox | 2.3 | 0 / 0.01 / 0.05 | 0.02 | 표 데이터 ML이 중심입니다. |
| H12 재설계안 Agent (광학) | zemax-mcp-server (참고, 라이선스가 확인되면 직접) | 1.2 | 0 / 0.06 / 0.15 | 0.07 | ZOS-API 도구 계층을 직접 짜지 않는 몫입니다. |
| H13 해석 Agent 운영 | ansys MCP | 1.2 | 0 / 0.02 / 0.04 | 0.02 | A12와 같습니다. |
| H14 '28 VP 선행 | ansys MCP | 1.2 | 0 / 0.02 / 0.05 | 0.02 | 설계 단계입니다. |
| H15 릴리즈 Agent 운영 | filesystem, docling | 3.9 | 0 / 0.01 / 0.03 | 0.04 |, |
| C3 LLM, 학습 플랫폼 운영 | mcp-grafana, kubernetes-mcp-server (read-only) | 3.0 | 0 / 0.02 / 0.05 | 0.06 | 운영 질의 스크립트를 대신합니다. |
| C13 Agent 이식 계층 | filesystem, git(레퍼런스), `langchain.mcp` | 2.5 (추정) | 0.05 / 0.12 / 0.25 | 0.30 | LangGraph 런타임에서 Claude 하네스 내장 도구(파일과 git)에 해당하는 도구를 직접 짜지 않습니다. 같은 MCP 서버를 두 런타임이 같이 씁니다. |
| **합계** | | **75.3** | | **3.51** (hi 0.96 / lo 7.68) | 계산 |

**제외한 WP**(외부 MCP가 대신할 통합 코드가 없음):
- A4, A8, 파일럿과 시범 운영
- A6, A2A 계약은 사내 오케스트레이터 몫
- A10, AX만 투입
- V1, 물리 모델링
- V2, GT 생성은 시뮬레이터 내장 기능과 라이브러리 몫
- V4, 배치 파이프라인
- V5, 학습
- V11, 인터페이스 정의
- C1, C2, C4, 플랫폼 구축
- C5~C12, C14, C15, 거버넌스이거나 바이브 코딩 미적용(novibe) WP

### 5-1. 순효과 (계획 판단용)

| 항목 | hi (보수) | base | lo (낙관) | 근거 |
|---|---|---|---|---|
| 외부 MCP 공수 절감 (개발 인력, 바이브 코딩 전) | 0.96 MM | 3.51 MM | 7.68 MM | 5장 합계 |
| 검증 공수 (9개 × 1개당 공수) | 4.05 | 2.70 | 1.35 | 4-3 |
| 공통 1회 구축 | 1.0 | 0.5 | 0.25 | 4-2 (추정) |
| 재검토 ('27, 9개월분) | 2.03 | 1.01 | 0.41 | 4-2 (추정) |
| **순효과** | **−6.1 MM** | **−0.7 MM** | **+5.7 MM** | 계산. 바이브 코딩 배수를 곱하면 절감 쪽은 더 작아집니다. |
| 서버별 판단 (base) | | | | |
| ansys-mechanical-mcp | 절감 약 0.85 vs 비용 0.41 → **+0.4** | | | A3, A5, H9, 운영 |
| ansys-aedt-mcp | 절감 약 0.62 vs 비용 0.41 → **+0.2** | | | A1, A5, H4, H5, 운영 |
| 그 밖의 7개 | 1개당 절감 0.05~0.3 vs 비용 0.2~0.4 → **0 근처이거나 음수** | | | 공수보다는 운영 편의와 이식성 때문에 들이는 서버들 |

---

## 6. 1안 / 2안 관점

| 항목 | 1안 (하네스 + LangGraph 투트랙) | 2안 (온프렘 로컬 LLM 단일) | 출처 |
|---|---|---|---|
| 같은 MCP 서버를 재사용할 수 있나 | ○ Claude Agent SDK(내장 MCP)와 LangGraph(`langchain.mcp`)가 **같은 서버**를 씁니다. 도구 계층을 두 번 짜지 않습니다. | ○ LangGraph와 vLLM(OpenAI 호환) 위에서 같은 서버를 씁니다. | https://docs.langchain.com/oss/python/migrate/langchain-mcp-adapters (상) |
| C3 데이터 | MCP 서버 자체는 데이터를 밖으로 보내지 않습니다. **하지만 도구 결과를 읽는 LLM이 데이터를 받습니다.** 그래서 C3를 다루는 서버(Ansys 모델, PLM, STEP)는 **온프렘 LLM 경로에만** 연결합니다. 외부 API 하네스에는 C0~C2 서버만 붙입니다. | 모두 온프렘이라 단순합니다. | 과제 데이터 등급 규칙, MCP 스펙 데이터 프라이버시 원칙 |
| 위험 | `langchain.mcp`가 beta라 API가 바뀔 수 있어 버전을 고정합니다. MCP 스펙 2026-07-28(stateless)로 SDK 메이저 버전이 바뀌는 중입니다. | 로컬 모델의 도구 호출 품질이 낮으면 도구 설명 오염(tool poisoning)에 더 약할 수 있습니다(추정). | 2-12 표 |
| 바이브 코딩 PC | 외부 MCP 설정 파일이 공격 표면입니다(SANDWORM_MODE, OX). 허용 목록과 설정 변경 감시가 필요합니다. | 같습니다. | 3장 |

---

## 7. 계획에 넣을 값

| key | hi (보수) | base | lo (낙관) | 단위 | 근거 |
|---|---|---|---|---|---|
| `mcp_vetting_mm_per_server` | **0.45** | **0.30** | **0.15** | MM/서버 | 4-2 단계별 일수 × 9개 위험 등급 구성(T1 4, T2 4, T3 1). 추정 |
| `mcp_servers_27` (`method.json mcp.servers`) | 12 | **9** | 7 | 개 | base 9개 = ansys-aedt, ansys-mechanical, docling, 벡터DB 1개, MLflow, Grafana, K8s(read-only), filesystem, git. hi는 여기에 ros2, Toolbox, MATLAB을 더하고, lo는 K8s, git을 뺍니다. 모델은 단일 값이라 base를 씁니다. |
| `mcp_vetting_setup_mm` (선택) | 1.0 | 0.5 | 0.25 | MM (1회) | 사내 미러, 샌드박스, 체크리스트, 로컬 스캐너 구성입니다. C11, C6과 일부 공유합니다. 모델 코드를 바꾸지 않으려면 1개당 값에 setup÷9를 더합니다(0.56 / 0.36 / 0.18). 추정 |
| `mcp_rereview_mm_per_server_year` (선택) | 0.30 | 0.15 | 0.06 | MM/서버와 년 | 분기 1회와 메이저 버전 업그레이드 때 차이 검토. Ansys 서버는 2~3주마다 릴리즈합니다(PyPI 이력). 운영 WP(C3, C6)에 넣습니다. 추정 |
| `mcp_saving_total_mm_27` (참고와 계산) | 0.96 | 3.51 | 7.68 | MM | 5장 wp_map × 개발 MM, 바이브 코딩 전 |
| `mcp_net_mm_27` (참고와 계산) | −6.1 | −0.7 | +5.7 | MM | 5-1 |

---

## 8. 권고 (계획 반영)

1. **외부 MCP 절감은 작게 잡습니다.** wp_map 기준 3.5 MM이고, 그중 실제 이득이 큰 것은 Ansys 2개뿐입니다. 동시에 C12 검증 공수(9 × 0.3 = 2.7 MM + 구축 0.5)를 반드시 같이 잡습니다. 그러지 않으면 계획이 공수를 과소 계상합니다.
2. **Ansys 공식 MCP를 먼저 들입니다.** ansys-mechanical-mcp는 A3(1~4월)에, ansys-aedt-mcp는 H4, H5, A5(Icepak)에 씁니다. 둘 다 Alpha이므로 **0단계 적합성 사전 시험(사내 AEDT, Mechanical 버전)을 '26.11~12에 마쳐야** 1월 착수 WP에 반영할 수 있습니다. `run_python_code`는 해석 VM 격리와 허용 스크립트 정책을 붙이고 씁니다.
3. **PLM(H2)과 lidar-engine(V3)은 사내 MCP를 직접 개발합니다.** ansys-common-mcp(지속 세션과 수명주기)와 tc-mcp, aras-claude-agent는 **설계만 참고**합니다. tc-mcp는 라이선스가 없어 코드를 재사용할 수 없습니다.
4. **망분리 원칙**: × 판정 서버(HF, W&B 호스팅과 Atlassian Rovo, Agent 365, UNS-MCP)는 C3 흐름에 쓰지 않습니다. △ 판정 서버(Qdrant의 FastEmbed, Docling 모델, NVIDIA kit-usd-agents)는 모델을 미리 캐시하거나 로컬 NIM으로 바꾼 뒤 반입합니다.
5. **공급망 통제**: 사내 미러로만 설치하고 버전과 해시를 고정합니다. `npx`, `uvx`로 최신판을 받는 방식은 금지합니다. 도구 정의 해시를 기록하고(rug pull 감지), 허용 목록은 모델이 바꿀 수 없는 위치에 둡니다. 바이브 코딩 PC의 MCP 설정 변경을 감시합니다. 지원이 중단된 레퍼런스(Postgres, SQLite)와 Elasticsearch 옛 MCP는 쓰지 않습니다.
6. **이식성**: MCP 도구 계층을 1안과 2안 공통 자산으로 정합니다. LangGraph 쪽은 `langchain[mcp]>=1.4` beta이므로 C13에서 버전을 고정하고 회귀 시험을 둡니다.
7. **조건부 결정**은 '26년 안에 확인합니다. 엔진이 ROS 2 기반인지, MATLAB 라이선스가 있는지, 사내 Grafana, K8s, MLflow를 표준으로 쓰는지, Capella 상용 MCP를 살지(H7 lo).

---

## 9. 미확인

| 항목 | 왜 중요한가 | 확인 방법 |
|---|---|---|
| 사내 PLM 제품과 버전 (Teamcenter? Windchill?) | H2 외부 MCP 판정과 Windchill AI Assistant 플러그인 사용 가능 여부가 달라집니다. | IT, PLM 담당 |
| 사내 AEDT, Mechanical 버전과 Ansys MCP 호환성 | Alpha 서버는 Python 3.12~3.13 이상, AEDT 2022 R2 이상 gRPC가 필요합니다. 커뮤니티 보고로는 AEDT 2026 R1에 버그가 있다고 합니다. | 0단계 사전 시험 |
| Ansys MCP의 텔레메트리와 외부 호출 여부 | 망분리 반입 조건 | 소스 검토 (4-2 2단계) |
| Windchill MCP의 AI 추론 도구가 처리되는 위치 (PTC 호스팅 여부) | C3 반출 여부 | PTC 문의 |
| Obeo AI for Capella의 가격과 배포 형태(온프렘), 로컬 LLM 지원 | H7 lo 시나리오 | Obeo 견적 |
| zemax-mcp-server, cad-mcp-server, @casys/mcp-syson, Isaac Sim 커뮤니티 서버의 라이선스와 상세 | 참고 구현을 재사용할 수 있는지 | 저장소 LICENSE 확인 (검색 한도 때문에 이번에 못 봄) |
| CODE V, optiSLang, 공차 해석 툴용 MCP | A11, H9 | 벤더 문의 |
| mcp-atlassian의 Server/Data Center 지원, GitLab 내장 MCP의 self-managed GA 여부 | 사내 협업 도구가 DC, self-managed일 때 | 저장소와 릴리즈 노트 |
| Microsoft Agent 365 MCP의 GA 여부 (2차 출처끼리 엇갈림) | 사내 M365를 쓸 때 (C0~C1 한정) | Microsoft Learn |
| 망분리용 로컬 MCP 스캐너 (agent-scan은 외부 API로 전송) | 4-2 2, 4단계 도구 | 대안 조사 (Cisco mcp-scanner 등은 이번에 미확인) |
| NSA CSI 원문 권고 목록 (원문 403) | 체크리스트 근거 | NSA PDF |
| 공식 MCP Registry의 GA 시점 (2차 출처) | 출처 확인 절차 간소화 | modelcontextprotocol.io |
| `portability_build_mm` (C13 개발 MM) | C13 절감 MM 계산 (2.5 MM으로 가정) | method.json 확정값 |
| 사내 MCP 1개당 검증 공수 실측 | 7장 값은 모두 추정 | 첫 2개(Ansys)를 검증할 때 실측해서 고칩니다. |

---

## 독립 검증 (2026-10-21)

- 방법: 핵심 출처 13건을 직접 열람(WebFetch, WebSearch, 2026-10-21)했습니다. 그 결과를 `model27.py`(L74 `DEV`, L297~340 계산식), `method.json`, `R1_바이브코딩_생산성.md`와 대조했고, 합계는 스크립트로 다시 계산했습니다. 설치하거나 실행한 것은 없습니다.
- 결론
  1. **사실관계(버전, 날짜, 도구 수와 보안 사례)는 대체로 맞습니다.** 다만 틀렸거나 근거가 약한 곳이 있습니다.
     - AEDT 도구 수는 21개이고, 문서에 3D Layout, SIwave, EDB가 없습니다.
     - postmark-mcp의 "첫 사례와 주 1,500회"는 Koi Security의 주장입니다. 인용한 Snyk 글은 이를 확인하지 않습니다.
     - Docker `--verify-signatures`와 Beta 표기는 인용한 페이지에 없습니다.
     - langchain-mcp-adapters가 archived라는 내용은 인용한 페이지에 없습니다.
     - OX 공개일 04-15는 출처에서 확인되지 않습니다.
  2. **계획 수치는 절감 쪽이 과대하고, 비용 쪽이 과소합니다.** 이유는 네 가지입니다.
     - 바이브 코딩과 겹칩니다.
     - AEDT 절감을 이중으로 셌습니다(A1 자체 계층, WP 기준값의 "플랫폼 재사용").
     - 기준 9개 서버에 없는 조건부 서버의 절감이 base 값에 들어 있습니다.
     - 검증 공수의 lo, base가 보고서 자체 4-2 표로 계산한 값보다 낮습니다.
  3. 수정 후 '27 순효과는 **보수 −8.5 / 기준 −3.8 / 낙관 −0.2 MM**입니다. 사내 개발이라도 어차피 거칠 검증 단계를 빼고 증분 비용만 보면 −6.1 / −2.4 / +0.7 MM입니다. 어느 쪽으로 봐도 **'27 단년 공수로는 Ansys 2개를 포함해 회수되지 않습니다.** 그래서 외부 MCP는 벤더 API 추종, 이식성, 보안 표준화 수단으로 계획에 넣고, C12 검증 공수는 **순증**으로 잡습니다.

### V-1. 출처 직접 확인

| # | 보고서 주장 | 직접 확인 결과 | 판정 | 출처 (열람 2026-10-21) |
|---|---|---|---|---|
| 1 | ansys-aedt-mcp v0.2.4 (2026-10-01). 0.1.0 (07-15) 이후 9회 릴리즈, Alpha, Python 3.12 이상 | 일치합니다. 추가로 **Trusted Publishing과 PyPI attestation**이 있습니다. 퍼블리셔는 "Synopsys, Inc. and ANSYS, Inc."입니다. | 확인 | https://pypi.org/project/ansys-aedt-mcp/ |
| 2 | AEDT 도구 20개, `run_python_code`, `run_python_script`, SIwave, EDB 도구 없음 | 문서상 **21개**(선택 도구 `get_guidelines_for` 포함)입니다. design type은 HFSS, Maxwell, Icepak, Circuit만 적혀 있고 **3D Layout, SIwave, EDB, Q3D는 언급이 없습니다.** gRPC 인증 설명도 없습니다(보고서와 같음). | 부분 수정. H4 매핑의 "3D Layout"은 근거가 없습니다. | https://aedt-mcp.docs.pyansys.com/version/stable/user_guide/tools_and_capabilities.html |
| 3 | ansys-mechanical-mcp v0.3.0 (2026-10-14), 도구 28개, Alpha, stdio, HTTP, mTLS | 일치합니다. 다만 세 가지가 더 있습니다. ① **0.3.0에서 도구 이름이 바뀌었습니다(breaking change).** `get_session_diagnostics`가 `check_mechanical_status`로 바뀌었습니다. ② 지원하는 Mechanical 버전이 README에 없습니다. ③ `run_python_code`를 끌 수 있는지 문서에 없습니다. | 확인. 위험 요인을 추가합니다. | https://pypi.org/project/ansys-mechanical-mcp/ , https://github.com/ansys/pymechanical-mcp |
| 4 | `langchain.mcp`: beta, `langchain[mcp]>=1.4.0`, FastMCP 기반, 옛 저장소 archived | beta, 1.4.0, FastMCP, stdio, Streamable HTTP는 일치합니다. 옛 패키지는 "대체됨"으로만 적혀 있습니다. **archived 여부는 인용 페이지에 없고**, GitHub API를 다시 조회했지만 403이었습니다. | archived는 **미확인** | https://docs.langchain.com/oss/python/migrate/langchain-mcp-adapters |
| 5 | MLflow MCP: 3.5.1 이상, experimental, 도구 10개 모두 trace, assessment용 | 일치합니다. 다만 `MLFLOW_MCP_TOOLS` 설정에 "experiments", "runs" 범주 이름이 있습니다. 그래서 "run 지표 도구 없음"은 최신판에서 달라졌을 수 있습니다. | 확인(최신판 run 도구는 **미확인**) | https://mlflow.org/docs/latest/genai/mcp/ |
| 6 | OX STDIO 설계 결함(2026-04-15). 수치는 OX 추정, Anthropic은 "의도된 동작"이라 답함 | CSA 노트는 2026-04-20에 나왔고, 수치가 OX의 추정이자 하한이라는 점과 SECURITY.md만 고쳤다는 점은 맞습니다. **공개일 04-15는 노트에 없습니다**("2026-04"로만 적혀 있음). | 날짜 **미확인** | https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-by-design-rce-ox-security-20260420/ |
| 7 | NSA CSI (2026-05-20) | 기사 날짜가 2026-05-21이고 "수요일에 발표"라고 썼으므로 2026-05-20이 맞습니다. 문서 제목 전문은 기사에 없습니다. | 확인 | https://executivegov.com/articles/nsa-model-context-protocol-deployment |
| 8 | postmark-mcp: 처음 확인된 실전 악성 MCP, 주 약 1,500회 다운로드, 이름 사칭 | 인용한 Snyk 글(2025-09-25)은 "perhaps the first media coverage case"라고만 쓰고, 주간 다운로드와 사칭 여부는 확인하지 않습니다. "첫 사례"는 **Koi Security(보안업체) 주장**입니다. 다운로드 수는 보도마다 다릅니다(Infosecurity, SC World는 주 1,500회, THN은 누적 1,643회). | 출처를 보강하고 "보안업체 주장"으로 표시 | https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/ , https://thehackernews.com/2025/09/first-malicious-mcp-server-found.html |
| 9 | SANDWORM_MODE | Socket이 찾았습니다. npm 패키지 19개, `claud-code`, McpInject 모듈, 도구 3개, "Do not mention…" 지시까지 모두 일치합니다. | 확인 | https://heise.de/-11190731 |
| 10 | snyk/agent-scan은 외부 API로 전송하므로 망분리 환경에서 쓸 수 없음. 로컬 대안은 미확인 | 전송 대상(도구 이름, 설명, 서버 설정)과 `SNYK_TOKEN` 필수는 일치합니다. 대안으로 **Cisco mcp-scanner의 YARA 엔진이 오프라인으로 동작합니다**(2차 출처). LLM 판정 엔진은 로컬 엔드포인트를 지정할 수 있습니다. 다만 YARA는 오탐이 많아 사람이 다시 검토해야 합니다. | 확인. 미확인 일부가 풀립니다. | https://github.com/snyk/agent-scan , https://pypi.org/project/cisco-ai-mcp-scanner/ (본문 로드 실패), https://appsecsanta.com/research/mcp-server-security-audit-2026 (하) |
| 11 | Docker 카탈로그: 서명과 SBOM이 있고 `--verify-signatures`로 확인하며 Beta. 이것이 검증 공수 낙관값의 근거 | 서명, SBOM, provenance는 맞습니다. 하지만 **`--verify-signatures`, Beta, best-effort 표기는 인용 페이지에 없습니다.** 또 **Ansys 같은 CAE 서버는 카탈로그에 없습니다.** | 낙관 근거가 약해짐. Ansys 서버에 있는 증명은 PyPI trusted publishing(출처 증명)뿐이고, 코드가 안전하다는 증명은 아닙니다. | https://docs.docker.com/ai/mcp-catalog-and-toolkit/catalog/ |
| 12 | 검증 일수 벤치마크 없음 | Backslash(2026-10-07)와 Cerbos(2026-08-16) 모두 시간 추정이 없습니다. Cerbos는 인가(authorization) 제품 공급사이고, "도구 실행 전 서버 밖에서 인가 판정"을 권합니다. 이를 따르면 게이트웨이 공수가 늘어납니다. | 확인 | https://www.backslash.security/learning/how-to-vet-an-mcp-server-before-you-approve-it-internally , https://cerbos.dev/blog/mcp-server-vetting-checklist |
| 13 | Teamcenter 공식 MCP 없음 | 다시 검색해도 Siemens의 공식 발표는 없습니다. Teamcenter 2606 소개 글에도 MCP 언급이 없습니다. | 유지(하) | https://www.drwe.de/en/blog/expert-knowledge-3/teamcenter-2606-is-here-here-are-three-new-features-you-should-know-about-411 |

### V-2. 반박과 수정한 주장

| # | 원 주장 | 문제 | 수정 | 근거 |
|---|---|---|---|---|
| R1 | "바이브 코딩 배수는 모델이 따로 곱하므로 겹치지 않습니다"(0장) | **겹칩니다.** `v × (1 − mcp) × vibe`라는 곱셈식은 MCP가 대신하는 glue 코드와 남는 도메인 코드에 같은 바이브 배수를 적용합니다. 그런데 바이브 코딩 이득이 가장 큰 곳이 바로 greenfield 주류 Python, 즉 MCP SDK 래퍼입니다(R1의 vibe_AI 근거). 그래서 MCP 절감은 과대로, 남는 공수는 과소로 계산됩니다. | 모델에 넣는 절감률에 k를 곱합니다. k = f_glue ÷ f_평균 = **0.75 / 0.70 / 0.60**(보수 / 기준 / 낙관, 추정). 낙관 시나리오일수록 바이브 효과가 커서 겹침도 커집니다. | R1 4-2 표(vibe_AI base 0.82, glue 추정 0.55 → 0.67. vibe_CAE 0.96, glue 추정 0.65 → 0.68), R1 F2(greenfield 30~40% vs brownfield 0~10%) |
| R2 | A5, H4, H5에서 ansys-aedt-mcp로 0.10 / 0.06 / 0.07 절감 | A1에서 보고서 스스로 "'26.10 릴리즈본은 자체 PyAEDT 도구 계층"이라고 했습니다. 또 `model27.py`의 H4, H5, A5 기준값은 이미 "플랫폼 재사용"으로 줄여 놓은 값입니다. AEDT 세션은 하나이고 Icepak, HFSS, Maxwell은 그 안의 design type이라서, 세션, solve, export 몫을 **두 번 셉니다.** 게다가 AEDT 문서에는 3D Layout, SIwave, EDB가 없습니다. | base를 A5 0.03, H4 0.02, H5 0.03으로 낮춥니다(k 적용 전). | model27.py L121, L134, L190, L192, V-1 #2 |
| R3 | A5의 Mechanical thermal 절감 | 보고서 스스로 "A3에서 연결한 것을 재사용"한다고 했으므로 A3에서 이미 센 몫입니다. | R2에 포함했습니다. | 5장 A5 행 |
| R4 | A3 절감률 0.12 | 이 값에는 다음이 반영되지 않았습니다. ① Alpha 단계이고 0.3.0에 breaking change가 있습니다. ② 사내 Mechanical 버전과 맞는지 미확인입니다. ③ `run_python_code`를 "허용 스크립트만"으로 막으려면 프록시나 포크가 필요합니다. ④ A3 WP 자체가 EM 프레임 재사용으로 이미 줄어 있습니다. | 0.05 / 0.12 / 0.20 → **0.03 / 0.07 / 0.15**(k 적용 전) | V-1 #3, model27.py L128~131 |
| R5 | 조건부 서버(ros2, Toolbox, MATLAB, 상용 Capella)는 lo에만 넣었다(5장 머리말) | 실제로는 base에도 들어 있습니다. A9(MATLAB) 0.02, H11(Toolbox) 0.01, H7(Capella, py-capellambse) 0.05가 그렇습니다. A11, H12(zemax, 라이선스 미확인)와 H3("해당 거의 없음")도 base가 0이 아닙니다. | 해당 base를 0이나 참고 수준(0.01~0.02)으로 낮춥니다. | 5장 표와 머리말 |
| R6 | C13 0.12, 개발 MM 2.5 가정("portability_build_mm 아직 없음") | ① LangGraph 쪽 deepagents의 `FilesystemMiddleware`가 ls, read_file, write_file, edit_file, glob, grep을 기본으로 줍니다. 그래서 반사실(MCP가 없을 때의 대안)은 "직접 짜기"가 아닙니다. ② C13 WP 정의 자체가 이미 MCP 도구 공유를 전제로 합니다. ③ `method.json`에는 이미 `portability_build_mm` 4.0 / 3.0 / 2.0이 있습니다. | **0.02 / 0.05 / 0.12**(k 적용 전), 개발 MM은 4.0 / 3.0 / 2.0 | method.json L19, model27.py L237~239, https://docs.langchain.com/oss/python/deepagents/backends |
| R7 | A2: 벡터DB MCP로 검색 도구 래퍼를 줄임 | 등급(C0~C3)별 접근 제어를 직접 만들면, ACL이 없는 벡터DB MCP 검색 도구는 에이전트에 붙일 수 없습니다. 그러면 줄어드는 것이 거의 없습니다. | 0.02 / 0.05 / 0.10 → **0 / 0.02 / 0.06** | 2-6 표(qdrant 쓰기 도구, milvus 읽기 전용 설정 필요) |
| R8 | V6: "trace, 평가 기록 도구를 직접 짜지 않음" | trace 기록은 MLflow SDK autolog가 합니다. MCP는 조회와 피드백 기록만 대신합니다. | V6 → **0.01 / 0.03 / 0.08**, V7 → **0 / 0.02 / 0.06** | V-1 #5 |
| R9 | 검증 공수 0.45 / 0.30 / 0.15 MM/서버 | **보고서 자체의 4-2 표와 맞지 않습니다.** 9개 가중 계산을 다시 하면 하한(T1 9일과 T2 5일과 T3 3일)이 6.6일 = 0.33 MM이고, 재사용 −20%를 적용해도 0.26입니다. 중앙값은 0.40, −15%를 적용하면 0.34입니다. 상한은 9.3일 = 0.47입니다. 그런데 lo 0.15는 "9개 모두 T3"인 셈이고, base 0.30과 hi 0.45도 표 산술보다 낮습니다. | **0.55 / 0.35 / 0.25**. hi에는 사전 시험에서 떨어지는 서버와 보안팀 왕복 +15%를 넣었습니다. | 4-2, 4-3 표 재계산 |
| R10 | 검증 공수 낙관값의 근거 "벤더 증명(서명 이미지와 SBOM)" | Ansys 서버는 Docker 카탈로그에 없습니다. trusted publishing은 출처만 증명하고 코드 안전성은 증명하지 않습니다. T1 서버(코드 실행)의 정적 검토는 줄일 수 없습니다. | R9의 lo 0.25에 반영했습니다. | V-1 #1, #11 |
| R11 | 재검토 공수 0.30 / 0.15 / 0.06 MM/서버와 년 | lo 0.06(1.2일/년)은 자체 표의 하한(T1 4일과 T2 2일과 T3 1일, 가중 2.8일 = 0.14 MM)보다 낮습니다. Alpha의 breaking change(Mechanical 0.3.0)와 MCP 스펙 2026-07-28에 따른 SDK 2.x 전환도 반영되지 않았습니다. | **0.35 / 0.18 / 0.12** | 4-2 표, V-1 #3, 2-12 표 |
| R12 | 1회 구축 공수 1.0 / 0.5 / 0.25 MM | 사내 PyPI, npm, 컨테이너 미러가 있는지 미확인입니다. 허용 목록을 모델 밖에 두는 인가 게이트(OX, Cerbos 권고)도 필요합니다. 반면 로컬 스캐너(Cisco YARA)는 있어 lo 값은 유지할 근거가 있습니다. | **1.5 / 0.6 / 0.3** | V-1 #6, #10, #12 |
| R13 | "1개당 절감이 검증 공수보다 확실히 큰 것은 Ansys Mechanical(+0.4)과 AEDT(+0.2)"(요약 3) | T1 서버 1개의 비용을 다시 세면 기준 **0.72 MM**입니다(검증 0.47 + 구축 몫 0.07 + 재검토 9개월 0.19). 보정한 절감은 Mechanical 0.48(k 적용 시 0.33), AEDT 0.28(k 적용 시 0.19)입니다. 그래서 **기준 시나리오에서 '27 단년으로는 둘 다 0 이하**입니다. 낙관 시나리오에서만 Mechanical +0.1~+0.6입니다. | "확실히 큼" 표현을 삭제합니다. '28 이후 운영과 도메인 확장을 할 때 회수되는 구조로 기술합니다. | V-5 |
| R14 | 서버 수 lo 7 (K8s, git 제외) | lo 절감에는 조건부 서버(MATLAB, ros2, Toolbox, Capella)가 들어 있습니다. lo 절감을 쓰려면 서버 수는 오히려 12에 가깝습니다. 그래서 순효과 lo가 과대입니다. | 값은 유지합니다. 모델은 base 9만 씁니다. 순효과는 9개로 계산하고, 이 모순을 주석에 적습니다. | 4-3, 5장 |
| R15 | A12: "재검증으로 거의 상쇄"라고 쓰고 5-1에서 재검토 비용을 따로 뺌 | 비용이 이중으로 계상됐습니다(보수 방향). | A12 절감은 총량으로 보고, 재검토 비용은 별도 항목으로 유지합니다. 영향은 0.05 MM 미만입니다. | 5장과 5-1 |
| R16 | 순효과에서 검증 공수를 전부 뺌 | 사내에서 직접 개발한 도구도 0(적합성), 4(인젝션 시험), 6(실행 구성), 7(등록) 단계와 미러를 거칩니다. 외부 MCP 때문에 **새로 생기는 비용**은 그 일부입니다. | 순효과를 "전체 비용"과 "증분 비용"(검증 ×0.65, 구축 ×0.5, 재검토 ×1.0, 추정) 두 가지로 표시합니다. | V-5 |

### V-3. 수정 후 계획 값

| key | 원 hi / base / lo | **수정 hi / base / lo** | 단위 | 변경 이유 | 출처 |
|---|---|---|---|---|---|
| `mcp_vetting_mm_per_server` | 0.45 / 0.30 / 0.15 | **0.55 / 0.35 / 0.25** | MM/서버 | R9, R10. 4-2 표를 다시 계산했습니다. 추정 | 4-2 표, V-1 #1, #11, #12 |
| `mcp_servers_27` | 12 / 9 / 7 | **12 / 9 / 7**(유지) | 개 | lo 모순은 R14에 적었습니다. 벡터DB, filesystem, git을 빼는 것은 V-7에서 검토합니다. | 4-3 |
| `mcp_vetting_setup_mm` | 1.0 / 0.5 / 0.25 | **1.5 / 0.6 / 0.3** | MM(1회) | R12. 추정 | V-1 #10, #12 |
| `mcp_rereview_mm_per_server_year` | 0.30 / 0.15 / 0.06 | **0.35 / 0.18 / 0.12** | MM/서버와 년 | R11. 추정 | 4-2 표, https://pypi.org/project/ansys-mechanical-mcp/ |
| `mcp_vibe_overlap_k` (신규) |, | **0.75 / 0.70 / 0.60** | 배수 | R1. 모델에 넣는 wp_map 절감률 = 조건 보정 절감률 × k. 2안(로컬 단일)은 바이브 효과가 작아 0.85 안팎으로 봅니다(추정). 2안의 합계 차이는 0.2 MM 미만입니다. | R1_바이브코딩_생산성.md 4-2 표 |
| `mcp_saving_gross_previbe_mm_27` (신규와 참고) |, | **0.38 / 1.72 / 5.24** | MM | 조건 보정만 한 절감률 × 개발 MM이고, k와 바이브 배수는 적용하지 않았습니다(C13은 4.0 / 3.0 / 2.0). | V-4 |
| `mcp_saving_total_mm_27` (참고와 계산) | 0.96 / 3.51 / 7.68 | **0.28 / 1.20 / 3.14** | MM | wp_map_corrected(모델 투입값) × 개발 MM입니다. 모델이 바이브 배수를 곱하기 전에 빼는 몫입니다. | V-4 |
| `mcp_net_mm_27` (참고와 계산) | −6.1 / −0.7 / +5.7 | **−8.5 / −3.8 / −0.2** | MM | 9개 서버, 전체 비용 기준입니다. 증분 비용 기준으로는 −6.1 / −2.4 / +0.7입니다. | V-5 |
| (참고) C12 한 파라미터로 접을 때 | 0.56 / 0.36 / 0.18 | **0.98 / 0.55 / 0.37** | MM/서버 | 검증 + 구축 ÷ 9 + 재검토 × 0.75로 계산했습니다. 모델에 재검토 WP가 없을 때 씁니다. | 계산 |

### V-4. wp_map 수정 (모델 투입값 = 조건 보정 × k)

| WP | 원 hi / base / lo | 조건 보정 (k 적용 전) | **모델 투입 (× k)** | 절감 MM (base, 모델) | 수정 이유 |
|---|---|---|---|---|---|
| A1 | 0 / 0.03 / 0.06 | 0 / 0.02 / 0.05 | **0 / 0.014 / 0.03** | 0.03 | 자체 PyAEDT 계층을 옮기는 비용이 들고, 줄어드는 것은 유지보수 몫뿐입니다. |
| A2 | 0.02 / 0.05 / 0.10 | 0 / 0.02 / 0.06 | **0 / 0.014 / 0.036** | 0.06 | R7 |
| A3 | 0.05 / 0.12 / 0.20 | 0.03 / 0.07 / 0.15 | **0.022 / 0.049 / 0.09** | 0.23 | R4 |
| A5 | 0.04 / 0.10 / 0.18 | 0.01 / 0.03 / 0.08 | **0.007 / 0.021 / 0.048** | 0.08 | R2, R3 |
| A7 | 0.02 / 0.05 / 0.10 | 0.01 / 0.03 / 0.08 | **0.007 / 0.021 / 0.048** | 0.08 | 아침 리포트는 결정론적 코드가 Prometheus API를 직접 부릅니다. 줄어드는 것은 에이전트의 상태 질의 몫뿐입니다. |
| A9 | 0 / 0.02 / 0.08 | 0 / 0 / 0.06 | **0 / 0 / 0.036** | 0 | R5 (MATLAB은 기준 서버가 아님) |
| A11 | 0 / 0.05 / 0.10 | 0 / 0.02 / 0.08 | **0 / 0.014 / 0.048** | 0.02 | zemax 라이선스가 미확인이라 읽어서 참고만 합니다. |
| A12 | 0 / 0.02 / 0.05 | 0 / 0.02 / 0.05 | **0 / 0.014 / 0.03** | 0.04 | R15 |
| V3 | 0.02 / 0.06 / 0.20 | 0 / 0.03 / 0.15 | **0 / 0.021 / 0.09** | 0.03 | ros-mcp는 조건부입니다. ansys-common-mcp 패턴(Apache-2.0)을 재사용하는 몫만 셉니다. |
| V6 | 0.02 / 0.06 / 0.12 | 0.01 / 0.03 / 0.08 | **0.007 / 0.021 / 0.048** | 0.05 | R8 |
| V7 | 0 / 0.03 / 0.08 | 0 / 0.02 / 0.06 | **0 / 0.014 / 0.036** | 0.04 | R8 |
| V8 | 0 / 0.03 / 0.08 | 0 / 0.01 / 0.05 | **0 / 0.007 / 0.03** | 0.01 | CARLA-MCP는 ★1이고 참고용입니다. |
| V9 | 0 / 0.02 / 0.06 | 0 / 0.01 / 0.05 | **0 / 0.007 / 0.03** | 0.01 | Toolbox는 조건부라 Grafana 조회만 셉니다. |
| V10 | 0 / 0.05 / 0.10 | 0 / 0.03 / 0.10 | **0 / 0.021 / 0.06** | 0.01 | 개발 MM이 0.3이라 영향이 거의 없습니다. |
| V12 | 0 / 0.02 / 0.04 | 0 / 0.02 / 0.04 | **0 / 0.014 / 0.024** | 0.04 | 유지 |
| H1 | 0.02 / 0.05 / 0.10 | 0.01 / 0.03 / 0.08 | **0.007 / 0.021 / 0.048** | 0.04 | PoC를 운영으로 전환하는 WP라 기존 파싱을 옮기는 비용이 듭니다. cad-mcp-server는 라이선스가 미확인입니다. |
| H2 | 0 / 0.03 / 0.08 | 0 / 0.02 / 0.06 | **0 / 0.014 / 0.036** | 0.04 | 참고 구현만 씁니다(tc-mcp는 라이선스 없음). |
| H3 | 0 / 0.03 / 0.06 | 0 / 0 / 0.03 | **0 / 0 / 0.018** | 0 | R5 |
| H4 | 0.02 / 0.06 / 0.12 | 0 / 0.02 / 0.06 | **0 / 0.014 / 0.036** | 0.04 | R2 (3D Layout, SIwave, EDB 미지원) |
| H5 | 0.03 / 0.07 / 0.14 | 0.01 / 0.03 / 0.08 | **0.007 / 0.021 / 0.048** | 0.05 | R2 |
| H6 | 0 / 0.02 / 0.05 | 0 / 0 / 0.04 | **0 / 0 / 0.024** | 0 | R5 |
| H7 | 0 / 0.05 / 0.20 | 0 / 0.01 / 0.15 | **0 / 0.007 / 0.09** | 0.01 | R5. 상용 Capella를 사면 구매비가 따로 듭니다. py-capellambse로 직접 만드는 것은 외부 MCP가 아닙니다. |
| H8 | 0.03 / 0.06 / 0.12 | 0.01 / 0.04 / 0.10 | **0.007 / 0.028 / 0.06** | 0.03 | 하네스와 deepagents에 파일 도구가 이미 들어 있습니다. |
| H9 | 0 / 0.03 / 0.08 | 0 / 0.02 / 0.05 | **0 / 0.014 / 0.03** | 0.03 | 열 해석은 A5, A3에서 이미 셌습니다. |
| H10 | 0 / 0.02 / 0.05 | 0 / 0.01 / 0.04 | **0 / 0.007 / 0.024** | 0.01 | 통합 판정은 사내 로직입니다. |
| H11 | 0 / 0.01 / 0.05 | 0 / 0 / 0.04 | **0 / 0 / 0.024** | 0 | R5 |
| H12 | 0 / 0.06 / 0.15 | 0 / 0.02 / 0.10 | **0 / 0.014 / 0.06** | 0.02 | zemax 라이선스가 미확인입니다. |
| H13 | 0 / 0.02 / 0.04 | 0 / 0.02 / 0.04 | **0 / 0.014 / 0.024** | 0.02 | 유지 |
| H14 | 0 / 0.02 / 0.05 | 0 / 0.01 / 0.04 | **0 / 0.007 / 0.024** | 0.01 | 설계 단계 |
| H15 | 0 / 0.01 / 0.03 | 0 / 0.01 / 0.03 | **0 / 0.007 / 0.018** | 0.03 | 유지 |
| C3 | 0 / 0.02 / 0.05 | 0 / 0.02 / 0.05 | **0 / 0.014 / 0.03** | 0.04 | 유지 |
| C13 | 0.05 / 0.12 / 0.25 | 0.02 / 0.05 / 0.12 | **0.015 / 0.035 / 0.072** | 0.11 | R6 (개발 MM 3.0) |
| **합계** | 0.96 / 3.51 / 7.68 | **0.38 / 1.72 / 5.24** | **0.28 / 1.20 / 3.14** | 1.20 | 개발 MM은 75.8입니다(C13 = 3.0). |

### V-5. 순효과 다시 계산 ('27, 서버 9개)

| 항목 | hi (보수) | base | lo (낙관) | 근거 |
|---|---|---|---|---|
| 절감: 조건 보정, k, 바이브 적용 전 | 0.38 | 1.72 | 5.24 | V-4 |
| 절감: 모델 투입(× k) | 0.28 | 1.20 | 3.14 | V-4. 모델이 바이브 배수를 곱하면 실제 계획 MM은 더 작아집니다. |
| 검증 (9 × 1개당 공수) | 4.95 | 3.15 | 2.25 | V-3 |
| 공통 1회 구축 | 1.50 | 0.60 | 0.30 | V-3 |
| 재검토 (9 × 연간 공수 × 0.75년) | 2.36 | 1.22 | 0.81 | V-3 |
| **순효과 (전체 비용 기준)** | **−8.5** | **−3.8** | **−0.2** | 계산 |
| 순효과 (증분 비용 기준: 검증 ×0.65, 구축 ×0.5) | −6.1 | −2.4 | +0.7 | R16. 비율은 추정입니다. |
| 서버별 판단: ansys-mechanical-mcp | 절감 0.16(k 적용 0.12) vs 1.04 | 0.48(k 적용 0.33) vs 0.72(증분 0.52) → **−0.4 ~ 0** | 1.10(k 적용 0.66) vs 0.54 → **+0.1 ~ +0.6** | 귀속 비율: A3, A5의 ½, H9, A12의 ½, H13의 ⅓, H10, H14의 ½. T1 1개 비용 = 검증 + 구축 ÷ 9 + 재검토 |
| 서버별 판단: ansys-aedt-mcp | 0.05 vs 1.04 | 0.28(k 적용 0.19) vs 0.72(증분 0.52) → **−0.5 ~ −0.2** | 0.76(k 적용 0.45) vs 0.54 → **−0.1 ~ +0.2** | 귀속 비율: A1, A5의 ½, H4, H5, A12의 ½, H13의 ⅔, H10, H14의 ½ |

### V-6. 신뢰도

| 항목 | 신뢰도 | 이유 |
|---|---|---|
| 사실관계 (버전, 날짜, 도구 수와 라이선스) | 상 | PyPI와 공식 문서를 직접 확인했습니다. 어긋난 곳은 V-1에 적었습니다. |
| 보안 사례 (postmark, SANDWORM, OX, NSA) | 중 | 1차 보도와 보안업체 보고입니다. 수치는 업체 추정입니다. |
| 검증, 구축, 재검토 공수 | 하 | 공개된 일수 벤치마크가 없습니다(Backslash, Cerbos 모두 없음). 모두 추정입니다. |
| wp_map 절감률 | 하 | 사내 코드 구조('26.10 EM 도구 계층)를 확인하지 못했습니다. 모두 추정입니다. |
| 중복 보정 k | 하 | R1 파라미터에서 유도했고, glue 코드의 바이브 배수를 실측한 자료는 없습니다. |
| **종합** | **중하** | 방향(절감 과대와 비용 과소)은 확신합니다. 크기는 Ansys 2개를 실측하기 전까지 ±50%로 봅니다. |

### V-7. 계획 반영 권고

1. `method.json`의 `mcp` 항목을 다음과 같이 고칩니다.
   - `wp` ← V-4의 모델 투입값
   - `vetting_mm_per_server` ← 0.55 / 0.35 / 0.25
   - `servers` ← 9
   - 재검토 WP가 따로 없으면 C12에 0.98 / 0.55 / 0.37을 넣습니다.
2. R1을 반영할 때 **"공식 Ansys MCP가 확인됐다"는 이유로 `vibe_CAE`를 올리지 않습니다.** 같은 효과를 이 보고서의 wp_map이 이미 셉니다. 코딩 에이전트가 개발 중에 Ansys MCP로 스크립트를 시험하는 효과는 R1 쪽에서만 셉니다.
3. Ansys 2개의 0단계(적합성)와 1~2단계(출처와 정적 검토)는 '26.12까지 실측합니다. 1개당 0.25 MM 이하가 나오면 V-3 값을 원 보고서 값 쪽으로 되돌립니다.
4. 기준 9개 중 벡터DB MCP, filesystem, git은 다음 두 가지를 확정한 뒤 빼는 것을 검토합니다.
   - 등급별 ACL 검색 설계(A2)
   - deepagents 내장 도구 사용 여부(C13)
   하나를 빼면 서버당 약 0.55 MM(검증 + 구축 몫 + 재검토)을 아끼고, 잃는 절감은 0.1 MM 미만입니다.
5. 요약 2, 3번 문장은 고칩니다. 외부 MCP는 '27 공수를 **늘리는** 항목이고, 가치는 벤더 API 추종, 1안과 2안 공통 도구 계층, '28 이후 운영 절감에 있다고 씁니다.
