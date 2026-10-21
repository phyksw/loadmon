# R4. Agent 런타임 선택과 운영 구조, 외부 API, 로컬 LLM 겸용

- 조사일: **2026-10-21 (KST)**. 웹과 문서 조사만 했고 구축과 설치는 하지 않음 (계획 수립용)
- 대상: LiDAR 개발 '27 우선 3과제 (AL-1 자율 설계와 해석, VV-1 LiDAR 가상검증, VV-3 MBSE HW 선검증), Agent 13개 (lead/sub 구조, MCP, A2A 표준)
- 전제: C3 (도면, STP, BOM 원본)는 외부 API로 반출 금지 → 온프렘 LLM 필수 (8× RTX PRO 6000 서버 2대, '27.7 가동, 그 전에는 브리지). AX 추진 인원 A와 B 2명. 외주 없음 (경력 채용과 사내 전환과 사내 지원)
- 표기
  - 값은 hi = 보수 (공수와 비용이 큰 쪽), base = 기준, lo = 낙관 순서로 적음
  - **추정** = 계산이나 판단으로 낸 값, **미확인** = 확인하지 못한 값
  - 공급사 발표 수치는 "(벤더 발표)"로 표시
  - 신뢰도: 상 = 공식 문서와 PyPI 메타데이터와 제조사 / 중 = 언론과 2차 문서 / 하 = 블로그와 검색 요약
  - 출처는 [S#]로 적고, 8장 출처 목록에 URL, 발표일을 정리함. [R0]는 같은 폴더의 `R0_단가조사_2026-10-20.md`

## 요약

1. **1안 (Claude 하네스 주력 + LangGraph/API 보조)은 실제로는 경로가 3개다.** C3는 트랙 A와 B 어느 쪽으로도 외부 API에 보낼 수 없으므로 온프렘 경로를 하나 더 둬야 한다. 13개 Agent 가운데 과반이 C3를 입력으로 받을 것으로 보이며 (**추정**), 이 경우 플랫폼 운영에만 기준 1.8 FTE가 든다. 2명으로 맡기에는 운영 부담이 세 안 중 가장 크다.
2. **기준안으로 혼합안을 권장한다.**
   - Agent 정의는 특정 런타임에 묶이지 않는 자산으로 관리한다: SKILL.md, 서브에이전트 정의, MCP 도구, A2A 카드, 평가셋, 모델 클래스 표.
   - 운영 런타임은 Deep Agents/LangGraph (MIT, 모델 무관) 하나로 한다.
   - 게이트웨이가 데이터 등급별로 모델을 고른다: C0~C1은 Claude API, C3는 온프렘 vLLM.
   - 개발 (바이브 코딩)은 Claude Code/Agent SDK로 한다.
   - 1안이 대비하려던 "연결 장애"는 런타임을 이중화하지 않고 Claude 공급자를 이중화해 대응한다 (Anthropic API + Bedrock 또는 Foundry).
3. **Claude Agent SDK는 Claude 전용이다.**
   - 지원 공급자: Anthropic API, Bedrock, Claude Platform on AWS, Google Cloud Agent Platform (구 Vertex), Foundry.
   - `ANTHROPIC_BASE_URL`로 vLLM이나 Ollama에 연결할 수는 있다. 그러나 Anthropic은 "게이트웨이를 통한 비Claude 모델 라우팅은 지원하지 않는다"고 명시한다 [S19]. 따라서 C3 운영 경로로는 쓰지 않는다.
4. **로컬 도구 호출은 버전을 고정하고 회귀 평가를 돌려야 한다.**
   - vLLM 문서 스스로 인자 스키마 위반이 생길 수 있고, 스트리밍 중 파싱에 실패한 도구 호출은 버려진다고 적고 있다 [S25].
   - gpt-oss와 Qwen3.5/3.6 파서 수정이 2025-11부터 2026-04까지 이어졌다 [S28][S29].
   - vLLM은 6개월 동안 마이너 버전이 13번 올라갔다 [S27].
   - 따라서 모델, 파서, vLLM 버전을 고정하고, 평가셋으로 회귀 시험을 하는 것이 필수다.
5. **계획에 넣을 값 (기준, 모두 추정):** 이식 계층 구축 7 MM, 1안 투트랙 유지 추가 0.5 FTE, 2안 로컬 단일 운영 1.5 FTE, 팀 학습 5 MM. 13개 Agent를 운영하는 총인력은 혼합안 3.3 FTE, 1안 3.8 FTE, 2안 4.1 FTE다.

---

## 1. 런타임 비교 (2026-10-21 기준)

### 1-1. 에이전트 런타임

| 런타임 (최신 버전, 배포일) | 서브에이전트 | MCP | A2A | 로컬 모델 | 관측 | 라이선스 | 성숙도 | 출처 |
|---|---|---|---|---|---|---|---|---|
| **Claude Agent SDK** (Python 0.2.170, 2026-10-21). Claude Code 하네스를 라이브러리로 제공 | 코드 (`AgentDefinition`) 또는 `.claude/agents/*.md`로 정의. 서브에이전트마다 tools, model, skills, mcpServers, effort, maxTurns를 지정. 기본은 백그라운드 실행. 기본 한도는 중첩 깊이 3, 동시 20개이고 쿼리 예산 상한 (`max_budget_usd`)을 둘 수 있음 | 내장 (`mcpServers`, 서브에이전트별 지정) | 네이티브 기능 없음. a2a-sdk로 감싸야 함 (**추정**: SDK 문서에 A2A 언급이 없음) | **공식 지원은 Claude 모델뿐**: Anthropic API, Bedrock, Claude Platform on AWS, Google Cloud Agent Platform (구 Vertex), Microsoft Foundry. 게이트웨이는 Anthropic Messages 형식을 제공하면 `ANTHROPIC_BASE_URL`로 연결됨. 비Claude 모델 라우팅은 Anthropic이 "지원하지 않음"이라고 명시 | hooks, OTel. Langfuse 통합 가이드 있음 | 패키지는 MIT. **사용에는 Anthropic Commercial Terms가 적용됨.** 제3자 제품에 claude.ai 로그인을 제공하는 것은 금지 | 0.x. 번들된 Claude Code 바이너리를 따라 자주 릴리스됨 (빈도는 미집계) | S14, S15, S16, S17, S18, S19 |
| **LangChain 1.x `create_agent` + LangGraph** (langchain 1.4.6, 2026-10-14 / langgraph 1.2.16, 2026-10-16) | 미리 만든 서브에이전트 기능은 없음. 하위 그래프를 도구로 감싸거나 그래프 노드로 직접 구성. 미들웨어: 요약, HITL, 호출 한도, **모델 폴백**, PII, 할 일 계획, 도구 선택, 도구 재시도 등 | `langchain-mcp-adapters` 0.3.2 (2026-08-06). 의존성이 `mcp>=1.24,<2.0`으로 고정됨 | LangSmith Agent Server의 `/a2a/{assistant_id}`: A2A v1.0 JSON-RPC만 지원하고 gRPC, HTTP+JSON은 미구현. **Agent Server를 자체 호스팅하려면 Enterprise 플랜이 필요**하므로, OSS만 쓰면 a2a-sdk로 직접 감싸야 함 | 모델 무관. vLLM은 OpenAI 호환 엔드포인트, Ollama는 전용 패키지로 연결 (일반 사용법). `ModelFallbackMiddleware`로 모델 폴백 가능 | LangSmith (자체 호스팅은 Enterprise) 또는 Langfuse (MIT) | MIT | 1.0 GA 2025-10-22. "2.0 전까지 breaking change 없음"을 약속 | S1, S2, S3, S6, S7, S8, S9, S12 |
| **Deep Agents** (deepagents 0.7.29, 2026-10-20). LangGraph 위의 Claude Code류 하네스 | 내장 `task` 도구로 서브에이전트 생성. 동기 실행이 기본이고, 비동기 실행 (launch, check, update, cancel)도 지원 (v0.5, 2026-04, 2차 자료) | 지원 (문서: "fully support MCP"). 어댑터 경유 | Agent Server 경유 (위 행과 같음) | 모델 무관. 문서 예시는 Google, OpenAI, Anthropic, OpenRouter, Fireworks, Baseten, Ollama. vLLM은 OpenAI 호환 엔드포인트로 연결 가능 (**추정**) | 위 행과 같음 | MIT | 0.x. 7개월 사이 0.4.10 (2026-03-11)에서 0.7.29로 올라갔고, v0.7에서 계획 기능을 opt-in으로 바꾸는 등 API 변동이 큼 | S4, S5, S54 |
| **OpenAI Agents SDK** (0.24.0, 2026-10-15) | handoffs, agents-as-tools (2차 자료) | 지원 | 네이티브 기능 **미확인** (없는 것으로 봄) | `litellm`, `any-llm` extra로 타사와 로컬 모델 연결 | **기본 설정이 트레이스를 OpenAI 백엔드로 보냄.** C3 작업에서는 `OPENAI_AGENTS_DISABLE_TRACING=1`이 필수 | MIT | 0.x | S33, S34 |
| **Google ADK** (2.12.0, 2026-10-13) | 멀티에이전트 지원. 2.0에서 그래프형 Workflow Runtime 추가 (2차 자료) | 지원 (원문 미확인) | 노출 (Python, Go, Java)과 소비 (Python, Go, Java, Kotlin) 모두 지원하나 문서 상태가 **Experimental**. `a2a` extra는 `a2a-sdk>=0.3.4,<2` | `LiteLlm` 래퍼로 Ollama, vLLM 연결 | 미확인 | Apache-2.0 | Python 2.0 GA 2026-05-19 (**2차 자료**) | S35, S36, S37, S38 |
| **Microsoft Agent Framework** (1.22.0, 2026-10-15). Semantic Kernel, AutoGen 후속 | 멀티에이전트 오케스트레이션, YAML 선언형 워크플로 | 지원 | .NET은 A2A v1 호스팅 (prerelease 패키지). Python은 `agent-framework-a2a` 1.0.0b261015 (**Beta**, `a2a-sdk>=1.0`) | 커넥터: Foundry, Azure OpenAI, OpenAI, Anthropic, Bedrock, Gemini, Ollama | 미확인 | MIT | 1.0 GA 2026-04-03 | S39, S40, S41, S42 |

- 참고: LiteLLM 문서에는 Claude Agent SDK에 비Anthropic 모델 (예: Bedrock Nova)을 붙이는 튜토리얼이 있다 [S31]. 이것은 LiteLLM 측 주장이고 Anthropic의 공식 지원 범위는 아니다 [S19].

### 1-2. 표준과 공통 부품

| 항목 | 2026-10 현황 | 계획상 의미 | 출처 |
|---|---|---|---|
| A2A 프로토콜 | v1.0.0 (2026-03-12, 첫 안정판), v1.0.1 (2026-05-26). LF 1주년 발표 (2026-04-09): 지원 조직 150곳 이상, Azure AI Foundry, Copilot Studio, Bedrock AgentCore Runtime에 통합, SDK 5개 언어 (Python, JS, Java, Go, .NET), Signed Agent Card | 표준 자체는 안정됐지만 런타임별 구현 수준이 다름: LangSmith는 JSON-RPC만, ADK는 Experimental, MAF Python은 Beta | S43, S44 |
| a2a-sdk (Python) | 1.2.3 (2026-10-19), Apache-2.0. A2A 1.0을 구현하고 0.3 호환 모드 제공. JSON-RPC, REST, gRPC | 어느 런타임이든 Agent를 A2A로 노출하는 공통 래퍼 후보 | S45 |
| MCP 스펙 | 2026-07-28 개정: 상태 비저장 요청/응답 방식으로 전환. initialize 핸드셰이크와 `Mcp-Session-Id` 폐지. Roots, Sampling, Logging과 HTTP+SSE 전송은 폐기 예고 (최소 12개월 유지). Python, TS, Go, C# SDK가 지원 | 사내 MCP 서버 (PLM, Ansys, RVTM)는 새 스펙 기준으로 작성. 구형 클라이언트와 섞어 쓰는 기간을 관리해야 함 | S46 |
| MCP Python SDK와 LangChain 어댑터의 버전 차이 | `mcp`는 2.3.0인데 `langchain-mcp-adapters` 0.3.2는 `mcp<2.0`으로 고정됨 | LangGraph 쪽에서 새 스펙 MCP 서버에 연결할 수 있는지 **미확인**. PoC 항목으로 둠 | S6, S47 |
| AAIF (Linux Foundation Agentic AI Foundation) | 2025-12-09 출범. MCP, goose, AGENTS.md가 이관됨 | MCP와 AGENTS.md는 특정 벤더가 아닌 중립 기관이 관리 | S48 |
| Agent Skills (SKILL.md) | Deep Agents 문서에 "Agent Skills 표준을 따른다"고 명시. Cursor도 공식 문서로 지원. Codex, Copilot, Gemini CLI 채택은 2차 자료로만 확인 | SKILL.md를 Claude 쪽과 LangChain 쪽이 공유하는 자산으로 쓸 수 있음 | S5, S49 |
| AGENTS.md / CLAUDE.md | Deep Agents는 AGENTS.md를 메모리 파일로 쓰고, Claude Code는 CLAUDE.md를 씀 | 내용은 하나로 두고 파일만 둘로 생성 (**추정**) | S5, S15 |
| LiteLLM (게이트웨이 후보) | Claude Agent SDK, ADK, OpenAI Agents SDK 모두 LiteLLM 연동 경로가 있음. **2026-03-24 PyPI에 악성 코드가 든 1.82.7, 1.82.8이 배포된 공급망 침해 사고가 있었고**, 1.83.0부터 새 배포 파이프라인 적용 | 게이트웨이를 쓰면 버전 고정, 해시 검증, 사내 미러가 필수 | S31, S32, S33, S35 |
| vLLM | 0.32.0 (2026-10-18). 0.19.1 (2026-04-18) 이후 6개월 동안 마이너 버전 13회. Anthropic Messages 엔드포인트를 제공해 Claude Code 연결 가이드가 있음 | 업그레이드 주기가 짧으므로 버전을 고정하고, 올릴 때마다 회귀 평가 | S24, S27 |
| Ollama | 0.14.0 이상에서 Anthropic Messages API 호환 (2026-01-16 발표) | 개인 시험용. 다중 사용자 서빙은 vLLM으로 | S30 |
| Langfuse | 코어 MIT, 자체 호스팅 무료 (관측, 평가, 프롬프트, 데이터셋 포함). 엔터프라이즈 라이선스는 프로젝트 RBAC, 감사로그 등을 더하는 선택 사항. 2026-01 ClickHouse가 인수. 구성: web, worker, ClickHouse, Postgres, Redis, blob 스토리지 | 두 런타임이 함께 쓰는 관측과 평가 저장소로 적합 | S12, S13, S14 |
| LangSmith | 자체 호스팅에는 Enterprise 플랜과 라이선스 키가 필요. 일반 라이선스는 beacon.langchain.com 접속이 필요하고, 오프라인 라이선스는 별도 협의 (검색 요약). 가격은 LSU 단위이며 비공개 (자체 관리형 배포는 agent run당 0.01 LSU) | 망분리 환경에서 쓰려면 오프라인 라이선스 견적이 필요 | S9, S10, S11 |

### 1-3. 로컬 쪽: vLLM 도구 호출과 구조화 출력의 신뢰도

| 항목 | 내용 | 계획상 의미 | 출처 |
|---|---|---|---|
| 자동 도구 선택 (`tool_choice=auto`)의 한계 | 문서: "arguments may occasionally be malformed or violate the function's parameter schema" | 도구 인자 스키마 검증과 재시도 미들웨어가 필수 | S25 |
| 도구 지정 (named / `required`)의 한계 | 문서: "guaranteed a validly-parsable function call - not a high-quality one" | 형식은 보장되지만 내용 품질은 평가로 확인해야 함 | S25 |
| 스트리밍 | 도구 호출 구간이 파싱된 뒤 한 번에 내보냄. 파싱에 실패한 호출은 "dropped" (오류 없이 사라짐) | 배치 Agent는 비스트리밍으로 돌리는 것이 안전 (**추정**) | S25 |
| gpt-oss (Harmony 형식, `--tool-call-parser openai`) | vLLM 공식 Claude Code 연동 예시가 gpt-oss-120b를 씀. 2025-11 PR #29236에서 스트림 버퍼 안의 도구 호출 누락과 채널 누출을 수정 | 파서 버그 수정 이력이 있으므로 vLLM 버전을 고정 | S24, S28 |
| Qwen3.5/3.6 (`qwen3_coder`, `qwen3_xml` 파서) | 2026-04 커뮤니티 패치에 8개 PR이 묶여 있음: `<think>` 안 도구 호출 누락 (#39055), 추론이 본문으로 새는 문제 (#36224, #35982), 파서 재작성 (#40785, #40787) 등 | 2026 상반기까지 파서 수정이 계속됐으므로, 채택하는 모델마다 도구 호출 회귀셋이 필요 | S29 |
| 구조화 출력 | 백엔드는 xgrammar, guidance. JSON Schema (`response_format`), regex, grammar, structural_tag 지원. Qwen3 Coder는 추론 파싱이 꺼져 있으면 구조화 출력이 비활성될 수 있어 `enable_in_reasoning` 옵션이 필요 | 정합성 판정과 BOM 대조 결과처럼 JSON으로 받아야 하는 산출물은 구조화 출력으로 강제 | S26 |
| Claude Code 하네스를 vLLM에 연결할 때 | `ANTHROPIC_BASE_URL`과 `--served-model-name`으로 연결 (모델명에 '/' 사용 불가). Claude Code는 adaptive thinking, effort, context_management 같은 Claude 전용 필드를 보내므로, 받는 쪽이 거부하면 `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`이 필요. 게이트웨이는 Claude Code 릴리스마다 호환성을 다시 맞춰야 함 | C3 운영 경로로 쓰면 Claude Code가 업데이트될 때마다 깨질 위험이 있음 | S20, S24 |
| RTX PRO 6000 위 모델별 도구 호출 성공률 | **미확인** | PoC에서 측정 (5장 권고 4) |, |

---

## 2. '바이브 코딩 서브에이전트 구성' 요소를 런타임별로 대응시키면

| 요소 | Claude Code / Claude Agent SDK | Deep Agents / LangGraph | 이식 판단 | 출처 |
|---|---|---|---|---|
| lead 에이전트 | `query()` 메인 루프 | `create_deep_agent()` / `create_agent()` | 프롬프트는 그대로 옮기되, 동작은 모델별로 다시 조정해야 함 | S5, S15 |
| 서브에이전트 정의 | `.claude/agents/*.md` (프런트매터 name, description, tools, model + 본문 프롬프트) 또는 `AgentDefinition` | `subagents=[{name, description, system_prompt, tools, model}]` | 필드가 거의 1:1로 대응해 변환기를 만들기 쉬움 (**추정**) | S5, S17 |
| 스킬 | `.claude/skills/<name>/SKILL.md` | Agent Skills 표준 SKILL.md | 그대로 공유 | S5, S15 |
| 내장 도구 | Read, Edit, Write, Bash, Glob, Grep, WebFetch 등 | ls, read_file, write_file, edit_file, glob, grep. `execute`는 샌드박스 백엔드에서만 | 이름과 동작이 다르므로, 업무용 도구는 MCP로 만들어야 옮길 수 있음 | S5, S15 |
| MCP | `mcpServers` | langchain-mcp-adapters | MCP 서버 자체는 공유. 스펙 버전 호환은 확인 필요 (1-2) | S6, S46 |
| 권한과 훅 | permission mode, allow/deny 규칙, hooks | `interrupt_on` (HITL), 미들웨어 | 정책 코드는 옮길 수 없어 런타임마다 다시 구현 (양은 적음) | S5, S7, S15 |
| 메모리 | CLAUDE.md | AGENTS.md | 내용은 공유하고 파일명만 다름 | S5 |
| 병렬 실행과 한도 | 깊이 3, 동시 20, 예산 상한 | 비동기 서브에이전트, 호출 한도 미들웨어 | 런타임마다 따로 설정 | S5, S7, S17 |
| A2A | 없음 (감싸서 제공) | Agent Server (Enterprise) 또는 a2a-sdk로 감쌈 | a2a-sdk 공통 래퍼로 통일 | S8, S45 |
| 모델 지정 | Claude 별칭 (fable, opus, sonnet, haiku) 또는 모델 ID | 임의의 LangChain 모델 | "모델 클래스"로 추상화하고 게이트웨이가 실제 모델로 해석 (3-1) | S5, S17 |

---

## 3. 운영 구조: Agent를 이식 가능한 자산으로 두고 런타임을 교체

### 3-1. 이식 가능한 자산

| 자산 | 형식 | 담는 내용 | 런타임을 바꿀 때 | 출처 |
|---|---|---|---|---|
| 스킬 | SKILL.md (Agent Skills 표준) | 해석 절차 (EM, 구조, 열, SI/PI, EMC), 설계 규칙, 검증 체크리스트, 설계지식 RAG 사용법 | 그대로 사용 | S5, S49 |
| 서브에이전트 정의 | Markdown + YAML 프런트매터 (name, description, tools, model_class, data_class) | 역할 프롬프트, 허용 도구, 모델 클래스, 데이터 등급 | 로더가 Agent SDK `AgentDefinition` 또는 Deep Agents `subagents`로 변환 | S5, S17 |
| MCP 도구 | MCP 서버 (2026-07-28 스펙) | PLM 조회, 도면과 BOM 메타데이터, PyAnsys 해석 제출과 결과 회수, RVTM 조회, 시나리오 DB | 그대로 사용 (클라이언트만 교체) | S46 |
| A2A 카드 | Agent Card JSON (A2A 1.0) | 다른 과제가 호출하는 lead Agent의 기능과 엔드포인트 | 그대로 사용 (서버 래퍼만 교체) | S43, S45 |
| 평가셋 | JSONL (입력과 기대 출력과 채점 기준과 데이터 등급) + 채점 스크립트 | Agent별 골든셋, 도구 호출 회귀셋, 구조화 출력 스키마 검증 | 런타임 × 모델 조합으로 다시 실행 | **추정** (설계안) |
| 모델 클래스 표 | YAML: model_class × data_class → endpoint | 예: 대형 추론 클래스는 C0~C1이면 `claude-opus-5-5`, C3이면 온프렘 Qwen3.5-122B-A10B FP8 또는 gpt-oss-120b. 작업용 클래스는 C0~C1이면 `claude-sonnet-5-5`/`claude-haiku-5-5`, C3이면 Qwen3.6-27B, 35B-A3B | 게이트웨이 설정만 바꿈 | R0 2-1, R0 6-1 |

### 3-2. 구조도

```
[자산 저장소 (Git)]
  skills/*/SKILL.md, agents/*.md, mcp/, a2a-cards/, evals/, model-classes.yaml
        │ 로더 (자산 → 런타임별 정의 생성)
        ├──▶ 런타임 A: Claude Agent SDK ─────────▶ [게이트웨이] ──▶ Claude API (C0~C1)
        └──▶ 런타임 B: Deep Agents / LangGraph ──▶ [게이트웨이] ─┬▶ Claude API (C0~C1)
                                                               └▶ 온프렘 vLLM (C3)
  MCP 서버 (PLM, Ansys, RVTM) ◀── 두 런타임이 함께 사용 (C3 작업은 사내 MCP만 허용)
  A2A (a2a-sdk) ◀── 과제 경계에서만 사용 (예: VV-3 → AL-1 해석 Agent)
  Langfuse (자체 호스팅) ◀── 두 런타임의 트레이스와 평가 결과
```

### 3-3. 운영 원칙

| 원칙 | 내용 | 근거 |
|---|---|---|
| 전환은 '작업' 단위로 | 런타임마다 세션 상태 형식이 달라 실행 중인 세션은 옮기지 않는다. 실패한 작업을 다른 경로에서 처음부터 다시 실행 | **추정**. Agent SDK는 세션과 서브에이전트 기록을 자체 파일로 저장함 [S17] |
| A2A는 과제 경계에서만 | 과제 안의 lead→sub 호출은 런타임 내부 서브에이전트로 처리하고, 과제 사이 호출만 A2A로 | 런타임별 A2A 구현 수준이 다름 [S8][S36][S42] |
| 등급 라우팅은 게이트웨이가 강제 | 모든 모델 호출은 게이트웨이를 거친다. data_class 태그가 없는 호출은 차단하고, C3는 온프렘 엔드포인트로만 보냄 | **추정** (설계안). Claude Code는 managed settings의 `allowedProviders`로 게이트웨이 외 경로를 막을 수 있음 (v2.1.285 이상) [S19] |
| 추론 외 트래픽 차단 | Claude Code 단말에는 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `skipWebFetchPreflight: true`, `DISABLE_FEEDBACK_COMMAND=1`을 설정. 메트릭에는 코드, 프롬프트, 경로가 들어가지 않지만, WebFetch 사전 검사는 호스트명을 `api.anthropic.com`으로 보냄. OpenAI Agents SDK는 트레이싱을 끔 | S21, S22, S34 |
| 외부 MCP는 등급별 허용목록으로 | 제3자 MCP 서버는 C0~C1 작업에만 허용하고, C3 작업에는 사내 MCP만 | **추정** (정책안) |
| 버전 고정 + 회귀 평가 | vLLM, 파서, 모델, 런타임 버전을 고정. 올릴 때마다 평가셋 조합 전체를 다시 실행 | S25, S27, S28, S29 |
| 평가 조합 | Agent 13개 × 런타임 1~2개 × 모델 클래스 2~3개 | **추정** |

---

## 4. 운영안 비교

### 4-1. 1안: 바이브 코딩 하네스 주력 + LangGraph/API 보조 (투트랙)

```
트랙 A (주):   Claude Code / Agent SDK ──▶ Claude API
트랙 B (보조): Deep Agents / LangGraph ──▶ 대체 API (예: Bedrock, Foundry의 Claude, 또는 타사 API)
C3 경로 (추가 필수): 트랙 B + 온프렘 vLLM   ← '27.7 전에는 브리지 범위에서만 가능
전환: 게이트웨이 헬스체크 실패 → 해당 작업을 트랙 B에서 다시 실행
전제: 13개 Agent 모두가 두 트랙에서 평가를 통과한 상태여야 전환이 의미 있음
```

- **1안에서 C3는 어디로 가는가:** 트랙 A와 B 모두 외부 API를 쓰므로 C3는 둘 다 받을 수 없다. 남은 방법은 두 가지다.
  - ① 트랙 B 런타임에 온프렘 vLLM을 붙인 별도 경로.
  - ② Claude Code 하네스를 게이트웨이로 vLLM에 연결 [S24]. 기술적으로는 되지만 Anthropic이 지원하지 않고 [S19], Claude Code 릴리스마다 호환성이 깨질 위험이 있다 [S20]. 따라서 운영 경로에서는 제외한다.
  - 결과적으로 1안은 "투트랙 + C3 트랙", 즉 경로 3개를 운영하게 된다.

### 4-2. 2안: 온프렘 로컬 LLM 단일

```
런타임: Deep Agents / LangGraph (Claude Code를 vLLM에 붙이는 방식은 Anthropic 비지원)
모델:   서버 2대 (8× RTX PRO 6000 × 2)의 vLLM, gpt-oss-120b, Qwen3.5-122B-A10B FP8, Qwen3.6-27B 등 [R0 2-1, 2-4]
전환:   서버 1 장애 → 서버 2 (모델이 서버 1대에 들어가게 복제 배치한 경우) / 두 대 모두 장애 → 작업 대기열
개발:   2a) 개발 도구도 로컬 모델 / 2b) C3 데이터가 없는 코드에 한해 Claude Code 사용 (사내 정책으로 판단)
```

### 4-3. 혼합안: 단일 운영 런타임 + 등급 라우팅 게이트웨이 + Claude Code 개발

```
운영 런타임: Deep Agents / LangGraph 하나
게이트웨이 라우팅: C0~C1 → Claude API (Opus/Sonnet/Haiku 5.5)
                    C2    → 사내 정책에 따라 API 또는 온프렘 (미확인)
                    C3    → 온프렘 vLLM
개발 (바이브 코딩): Claude Code / Agent SDK로 Agent 코드, 스킬, MCP 서버를 작성 (C3 데이터는 넣지 않는 조건)
전환: API 장애 → C0~C1 작업을 로컬 모델로 낮춰 실행하거나 대기 / 온프렘 장애 → C3 작업 대기 (외부로 대체 금지)
가용성: Claude 공급자를 이중화 (Anthropic API + Bedrock 또는 Foundry), 하네스는 그대로 두고 엔드포인트만 바꿈 [S16][S23]
변형 (혼합-B): C0~C1 Agent는 Agent SDK, C3 Agent는 Deep Agents, Agent마다 런타임은 하나 (중복 없음)
```

### 4-4. 비교

| 항목 | 1안 (하네스 주력 + LangGraph/API 보조) | 2안 (온프렘 로컬 단일) | 혼합안 (단일 런타임 + 등급 라우팅) | 출처 |
|---|---|---|---|---|
| 실행 경로 수 | 3 (트랙 A, 트랙 B, C3 온프렘) | 1 | 런타임 1개 × 모델 계열 2개 | 4-1~4-3 |
| C3 처리 | 트랙 A와 B로는 불가하므로 별도 온프렘 경로 필요 | 전부 온프렘 | 게이트웨이가 C3를 온프렘으로 강제 | S19, S24 |
| '27.7 이전 | C0~C1 Agent는 바로 운영 가능, C3 Agent는 대기 (브리지 범위만) | 브리지 범위 밖은 운영 불가 → '27 상반기 성과 위험 | C0~C1은 운영 가능, C3는 대기 | 전제 |
| 장애 시 전환 | Claude 장애 시 트랙 B에서 작업 재실행. 두 런타임 모두 평가 통과 상태를 유지해야 함 | 서버 이중화 (모델이 1대에 들어갈 때). 외부 대체 없음 | 엔드포인트만 교체 (그래프는 동일). Claude 공급자 이중화로 대부분 흡수 | S16, S23, **추정** |
| 품질 | C0~C2는 최상 (Claude 모델 + Claude 전용 하네스). C3는 로컬 모델 수준 | 전 Agent가 로컬 모델 수준이고 Claude Code 하네스의 이점도 없음 | C0~C1은 Claude 모델이지만 하네스는 Deep Agents (Claude Code보다 성숙도 낮음, **추정**). C3는 로컬 모델 수준 | S4, S15 |
| 품질 차이의 크기 | 공개 벤치마크는 하네스와 벤치마크 버전이 달라 직접 비교할 수 없음. 사내 평가셋으로 측정해야 함 (**미확인**). 참고: Qwen3.6-27B SWE-bench Verified 77.2 (벤더 발표) | 같음 | 같음 | R0 2-1 |
| 외부 비용 | API 비용이 가장 큼 (API 계약 2건 가능) | API 비용 0. GPU, 전력은 R0 기준 | C0~C1 몫의 API 비용만 | R0 6-4, R0 10 |
| 인력 비용 (플랫폼, 기준) | 1.8 FTE | 1.5 FTE + Agent 품질 보정분 | 1.3 FTE | 4-5 |
| 운영 부담 | 가장 큼: 런타임 2벌, 게이트웨이, 온프렘, 이중 평가, Claude Code 릴리스 추종 | 중간: vLLM, 모델 교체, 용량 관리에 집중 | 가장 작음 | S20, S27 |
| 벤더 종속 | 높음 (하네스와 모델 모두 Anthropic) | 낮음 | 중간 (모델만 Anthropic, 하네스는 MIT OSS) | S4, S15 |
| 약관과 라이선스 위험 | Claude Code, Agent SDK를 비Claude 모델에 연결하는 사용이 약관상 허용되는지 **미확인** | OSS만 사용 | OSS + API 약관 | S15, S19 |

### 4-5. 운영 인력: 13개 Agent 정상 운영 기준 (FTE, 값 순서는 낙관 / 기준 / 보수, 모두 **추정**)

| 구성 요소 | 1안 | 2안 | 혼합안 | 근거 |
|---|---|---|---|---|
| (a) 온프렘 LLM 서빙: vLLM, 모델 교체, GPU, 파서 회귀 | 0.3 / 0.4 / 0.6 | 0.5 / 0.8 / 1.2 | 0.3 / 0.5 / 0.7 | vLLM은 6개월에 마이너 13회 [S27], 파서 수정 이력 [S28][S29]. 1안은 C3 경로분만 해당 |
| (b) 런타임, 게이트웨이, 관측 | 0.6 / 0.9 / 1.5 | 0.3 / 0.4 / 0.7 | 0.4 / 0.5 / 0.7 | 1안은 런타임이 2벌이고, Claude Code 릴리스마다 게이트웨이 호환성을 유지해야 함 [S19][S20] |
| (c) 평가와 회귀 | 0.3 / 0.5 / 0.7 | 0.2 / 0.3 / 0.6 | 0.2 / 0.3 / 0.4 | 1안은 Agent마다 런타임 2개로 평가, 2안은 모델 교체 때마다 전량 재평가 |
| **플랫폼 소계** | **1.2 / 1.8 / 2.8** | **1.0 / 1.5 / 2.5** | **0.9 / 1.3 / 1.8** | (a) + (b) + (c) |
| (d) Agent별 유지보수 (도메인 오너, Agent당 0.10 / 0.15 / 0.25) | 1.3 / 2.0 / 3.3 | 1.6 / 2.6 / 4.9 | 1.3 / 2.0 / 3.3 | **추정**. 2안은 로컬 모델 품질 보정 계수 ×1.2 / 1.3 / 1.5 적용 |
| **합계** | **2.5 / 3.8 / 6.1** | **2.6 / 4.1 / 7.4** | **2.2 / 3.3 / 5.1** | |
| 인건비 환산 (기준값) | 약 4.7억원/년 | 약 5.0억원/년 | 약 4.0억원/년 | [R0 10장 #23] 1인당 1.224억원/년 × 기준 FTE |
| 인력 배치 | AX 2명이 플랫폼에 거의 전부 묶여 신규 Agent 개발 여력이 없음 | 플랫폼 1.5 FTE. LLM 서빙과 MLOps 경력 1명 채용이 사실상 필요 | AX A = 플랫폼 (약 1.0), AX B = 런타임과 lead Agent (약 0.3 + 개발). Agent마다 도메인 오너를 지정 (팀 34명 중) | **추정** |

### 4-6. 장단점

| 안 | 장점 | 단점 | 맞는 경우 |
|---|---|---|---|
| 1안 | C0~C2 품질이 가장 높음. 바이브 코딩 도구와 운영 런타임이 같아 학습 비용이 적음 (트랙 A만 볼 때). '27.7 전부터 C0~C1 성과를 낼 수 있음 | C3 경로가 따로 필요해 경로 3개가 됨. 트랙 B는 평소 쓰지 않으므로 평가 상태를 유지하기 어려움 (**추정**). Claude Code 릴리스를 계속 따라가야 함. 벤더 종속이 가장 큼 | C3 Agent가 소수이고, 인력이 3명 이상이며, API 예산이 확보된 경우 |
| 2안 | 데이터 반출 위험이 구조적으로 0. API 비용 0. 런타임 1개 | 전 Agent 품질이 로컬 모델 수준. 도구 호출 신뢰도 위험 (1-3). '27.7 전에는 성과를 내기 어려움. 서빙과 MLOps 인력이 필요 | 사내 정책이 모든 등급의 외부 API를 금지하거나, 사내 평가에서 로컬 모델이 목표를 충족한 경우 |
| 혼합안 | C3 준수가 구조로 보장됨 (게이트웨이). C0~C1은 Claude 품질. 런타임 1개로 운영 부담이 가장 작음. 모델을 바꿀 때 설정만 변경 | Claude Code 하네스의 일부 기능 (내장 편집과 bash 도구, 컨텍스트 관리 등)을 운영에서 직접 쓰지 못함. Deep Agents 0.x의 API 변동 위험 [S4]. 같은 Agent가 등급에 따라 다른 모델로 돌면 품질이 들쭉날쭉할 수 있음 | C3 Agent가 많고 AX 인력이 2명인 현재 조건 |

### 4-7. 판단 기준: 어떤 조건이면 어느 안

| 조건 (확인할 사실) | 판단 | 근거 |
|---|---|---|
| 13개 중 C3를 입력으로 받는 Agent가 약 1/3 이상 (AL-1, VV-3 대부분으로 추정) | 혼합안 (또는 2안) | 1안은 C3 전용 경로가 추가됨 (4-1). 1/3이라는 경계값은 **추정** |
| 사내 정책상 모든 등급의 외부 API 사용 금지, 또는 API 예산 0 | 2안 | 4-4 |
| C0~C1 Agent가 대부분이고, '27 상반기 성과가 필요하며, 인력 3명 이상 확보 | 1안으로 시작하되 '27.7 이후 혼합안으로 수렴 | 4-4, 4-5 |
| AX 2명에 사내 지원이 1 FTE 이하 | 혼합안 (단일 런타임) 필수. 1안은 불가 | 1안은 플랫폼에만 기준 1.8 FTE |
| 사내 평가에서 로컬 모델의 도구 호출 성공률이나 과제 정확도가 목표에 못 미침 | C3 Agent는 사람 승인 단계를 늘리고 범위를 줄임. 2안은 배제 | 1-3 |
| "연결이 안 되는" 원인이 Anthropic 장애 (가용성) | 런타임 이중화 대신 Claude 공급자 이중화 (같은 하네스로 Anthropic API, Bedrock, Foundry 등) | S16, S23 |
| "연결이 안 되는" 원인이 사내망과 보안 정책 (차단) | 외부 API 경로 전체가 불확실하므로 혼합안 또는 2안 | 4-4 |
| Claude Code 내장 기능 (파일 편집, bash, 컨텍스트 관리)에 크게 의존하는 Agent (예: 해석 스크립트 생성과 디버깅)이고 데이터가 C0~C2 | 그 Agent만 Agent SDK로 운영 (혼합-B) | S15 |

---

## 5. 계획 반영 권고

1. **운영 기준안은 혼합안으로 한다.** 운영 런타임은 Deep Agents/LangGraph 하나, 게이트웨이가 등급별로 모델을 고르고, 개발은 Claude Code로 바이브 코딩한다. 1안의 장애 대비는 Claude 공급자 이중화로 대체한다.
2. **Agent 정의 형식을 2027 1분기에 확정한다.** 대상은 SKILL.md, 서브에이전트 md (data_class와 model_class 필드 포함), MCP 서버, A2A 카드, 평가셋, 모델 클래스 표다. 확정 뒤 13개 Agent를 이 형식으로 작성한다.
3. **'27.7 전 (브리지 기간)에는 C0~C1부터 운영한다.** C0~C1 Agent와 평가 하네스를 API로 먼저 돌린다. 로컬 후보 모델은 브리지 환경에서 도구 호출 회귀셋으로 측정한다. 서버가 가동되면 C3 Agent를 온프렘으로 전환한다.
4. **2027 1분기에 PoC 게이트 4개를 둔다.**
   - ① langchain-mcp-adapters가 MCP 2026-07-28 스펙 서버에 연결되는지
   - ② vLLM 0.32.x에서 gpt-oss-120b와 Qwen3.5-122B-A10B의 도구 호출 성공률과 구조화 출력 준수율
   - ③ 같은 자산에서 Agent SDK 정의와 Deep Agents 정의를 모두 생성할 수 있는지
   - ④ a2a-sdk 1.x 래퍼로 과제 간 호출이 되는지
5. **관측은 Langfuse 자체 호스팅 (MIT)을 기본으로 한다.** LangSmith는 Agent Server의 A2A, 배포 기능이 꼭 필요할 때만 Enterprise 오프라인 라이선스 견적을 받는다.
6. **공급망을 관리한다.** LiteLLM, MCP 서버, PyPI, npm 패키지는 버전 고정, 해시 검증, 사내 미러를 기본으로 한다 (LiteLLM 침해 사례 [S32]). 외부 MCP는 C0~C1 작업에만 허용한다.
7. **인력을 배치한다.** AX A는 플랫폼 (게이트웨이, 서빙, 평가), AX B는 런타임과 lead Agent를 맡는다. Agent 13개에는 각각 도메인 오너를 지정한다 (기준 0.15 FTE). 2안을 택하거나 보수 시나리오가 되면 LLM 서빙과 MLOps 경력 1명을 채용한다.
8. **약관을 확인한다.** Claude Code나 Agent SDK를 비Claude 모델에 연결하는 사용은 법무 확인 전까지 운영 경로에서 뺀다.

---

## 6. 계획에 넣을 값

### 6-1. 이식 계층 구축 공수 내역 (MM, 모두 추정)

바이브 코딩 효과는 METR 연구를 근거로 반영했다. 2026 RCT 결과는 약 4~20% 단축으로, 저자가 하한값이자 약한 근거라고 밝혔다 [S50]. 2025 RCT에서는 오히려 19% 느려졌다 [S51]. 자기보고 조사에서는 1.4~2배였다 [S52]. 이를 바탕으로 보수 1.0배, 기준 약 1.2배, 낙관 약 1.5배 단축으로 가정했다.

| 구성 | 보수 (hi) | 기준 (base) | 낙관 (lo) | 근거 |
|---|---|---|---|---|
| LLM 게이트웨이: 등급 라우팅, C3 차단, 감사로그, 인증 (LiteLLM 기반 또는 자체 구현) | 2.5 | 1.7 | 0.8 | 추정 |
| 모델 어댑터와 자산 로더: 자산에서 Agent SDK / Deep Agents 정의를 생성하고 모델 클래스를 해석 | 3.5 | 2.0 | 1.0 | 추정. 필드가 1:1로 대응함 (2장) |
| A2A 래퍼 (a2a-sdk 1.x)와 Agent Card 레지스트리 | 1.5 | 1.0 | 0.5 | 추정 |
| 평가 하네스 (형식, 러너, 채점, 회귀 CI)와 Langfuse 자체 호스팅 | 4.5 | 2.3 | 1.7 | 추정 |
| **합계** | **12.0** | **7.0** | **4.0** | |

### 6-2. 팀 학습 공수 내역 (MM, 모두 추정)

| 대상 | 보수 | 기준 | 낙관 | 근거 |
|---|---|---|---|---|
| AX 핵심 2명: Agent SDK, Deep Agents/LangGraph, MCP 2026-07-28, A2A 1.0, vLLM 도구 파서, Langfuse | 4.0 (1인 2.0) | 3.0 (1인 1.5) | 2.0 (1인 1.0) | 추정 |
| 사내 지원과 전환 인력 (Agent 도메인 오너 8명 가정): Claude Code 사용, SKILL.md, 서브에이전트 정의와 평가셋 작성 | 4.0 (1인 0.5) | 2.0 (1인 0.25) | 1.0 (1인 0.125) | 추정 |
| **합계** | **8** | **5** | **3** | 안별 가감: 1안은 런타임이 2벌이라 +1~2 MM, 2안은 vLLM, 양자화, 파서 학습으로 +0.5~1 MM |

### 6-3. 계획 입력값

| key | 항목 | 단위 | hi (보수) | base (기준) | lo (낙관) | 근거 |
|---|---|---|---|---|---|---|
| portability_build_mm | 이식 계층 구축: 게이트웨이, 모델 어댑터와 자산 로더, A2A 래퍼, 평가 하네스 + Langfuse | MM | 12 | 7 | 4 | 6-1 내역 (추정). 바이브 코딩 효과 보수 1.0배 / 기준 1.2배 / 낙관 1.5배 [S50][S51][S52] |
| twotrack_ops_fte | 1안 투트랙을 유지하는 데 추가로 드는 FTE (혼합안 대비) | FTE | 1.0 | 0.5 | 0.3 | 4-5의 플랫폼 소계 차이 (1안 2.8/1.8/1.2 − 혼합 1.8/1.3/0.9). 내용: 런타임 2벌, 이중 평가, Claude Code 릴리스마다 게이트웨이 호환성 유지 [S20] (추정) |
| local_only_ops_fte | 2안 로컬 단일 운영 FTE (플랫폼: 서빙 + 런타임 + 평가. Agent 유지보수는 제외) | FTE | 2.5 | 1.5 | 1.0 | 4-5의 2안 플랫폼 소계. vLLM은 6개월에 마이너 13회 [S27], 파서 회귀 [S28][S29] (추정). Agent 유지보수에 품질 보정을 더하면 총 7.4 / 4.1 / 2.6 |
| framework_learning_mm | 팀 학습 MM (AX 2명 + 도메인 오너 8명) | MM | 8 | 5 | 3 | 6-2 내역 (추정) |
| (참고) hybrid_platform_ops_fte | 혼합안 플랫폼 운영 FTE | FTE | 1.8 | 1.3 | 0.9 | 4-5 (추정) |
| (참고) agent_maint_fte_per_agent | Agent 1개당 정상 운영 유지보수 FTE (도메인 오너) | FTE/Agent | 0.25 | 0.15 | 0.10 | 추정. 2안은 ×1.5 / 1.3 / 1.2 |

---

## 7. 미확인

- 13개 Agent별 데이터 등급 매핑 (C3 입력 비중). 본 문서의 "과반이 C3"는 과제 설명에서 추정한 값
- C2 처리 규칙 (외부 API 허용 여부), 사내망에서 Claude API에 접근하는 정책 (프록시와 DLP), Bedrock, Foundry 같은 대체 공급자 계약 가능 여부와 한국 리전 제공 여부
- Anthropic 약관상 Claude Code나 Agent SDK를 비Claude 모델 (vLLM, Ollama)에 연결해 쓰는 것이 허용되는지. Anthropic은 "지원하지 않음"이라고만 명시함 [S19]
- `langchain-mcp-adapters` (`mcp<2.0` 고정)가 MCP 2026-07-28 스펙과 `mcp` 2.x SDK를 지원하는지
- RTX PRO 6000 + vLLM 0.32.x 위 후보 모델 (gpt-oss-120b, Qwen3.5-122B-A10B, Qwen3.6-27B)의 도구 호출 성공률과 구조화 출력 준수율
- 사내 과제 기준 Claude Opus/Sonnet 5.5와 로컬 모델의 품질 차이 (공개 벤치마크로는 비교 불가)
- LangSmith Enterprise 자체 호스팅 가격 (LSU 단가)과 오프라인 라이선스 조건
- Google ADK 2.0 GA 일자 (2차 자료만 확인), ADK A2A의 Experimental 해제 시점, Microsoft Agent Framework Python A2A의 GA 시점
- OpenAI Agents SDK의 A2A 지원 여부와 0.24에서의 MCP 최신 스펙 지원 범위
- Claude Agent SDK의 릴리스 빈도 (집계하지 않음)와 A2A 계획
- 바이브 코딩 생산성의 사내 실측값 (METR 2026 결과는 저자 스스로 "weak evidence"라고 밝힘)
- Agent별 월 토큰 사용량 (API 비용 산정용, R0 6-4 단가표에 곱할 값)
- 브리지 기간 ('27.7 전)에 쓸 수 있는 온프렘 추론 자원의 규모

---

## 8. 출처 목록

| ID | 자료 | URL | 발표와 갱신일 | 신뢰도 |
|---|---|---|---|---|
| S1 | LangChain, LangGraph 1.0 발표 | https://blog.langchain.com/langchain-langgraph-1dot0 | 2025-10-22 | 상 |
| S2 | PyPI langchain 1.4.6 | https://pypi.org/project/langchain/1.4.6/ | 2026-10-14 | 상 |
| S3 | PyPI langgraph 1.2.16 | https://pypi.org/project/langgraph/1.2.16/ | 2026-10-16 | 상 |
| S4 | PyPI deepagents 0.7.29 (MIT). 0.4.10은 2026-03-11 | https://pypi.org/project/deepagents/0.7.29/ | 2026-10-20 | 상 |
| S5 | Deep Agents 개요 (서브에이전트, Agent Skills 표준, MCP, AGENTS.md, interrupt_on, v0.7 계획 opt-in) | https://docs.langchain.com/oss/python/deepagents/overview | 조회 2026-10-21 | 상 |
| S6 | PyPI langchain-mcp-adapters 0.3.2 (`mcp>=1.24,<2.0`) | https://pypi.org/project/langchain-mcp-adapters/0.3.2/ | 2026-08-06 | 상 |
| S7 | LangChain 미들웨어 레퍼런스 (ModelFallbackMiddleware, LLMToolSelectorMiddleware 등) | https://reference.langchain.com/python/langchain/middleware/ | 조회 2026-10-21 | 상 (검색 요약) |
| S8 | LangSmith Agent Server A2A (`/a2a/{assistant_id}`, v1.0 JSON-RPC, langgraph-api ≥ 0.4.21) | https://docs.langchain.com/langsmith/server-a2a | 조회 2026-10-21 | 상 |
| S9 | LangSmith 자체 호스팅 개요 (Enterprise 플랜, standalone server는 망분리에 적합) | https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview | 조회 2026-10-21 | 상 |
| S10 | LangSmith Enterprise 가격 (LSU 단가, 자체 관리형 배포는 agent run당 0.01 LSU) | https://www.langchain.com/enterprise-pricing | 조회 2026-10-21 | 상 |
| S11 | LangSmith 자체 호스팅 egress (beacon.langchain.com, 오프라인 라이선스) | https://docs.langchain.com/langsmith/self-host-egress | 조회 2026-10-21 | 중 (검색 요약) |
| S12 | Langfuse 설명 페이지 (MIT 코어, 엔터프라이즈 라이선스, 2026-01 ClickHouse 인수, 구성 요소) | https://langfuse.com/resources/engineering/clarifications | 2026-09-04 | 상 |
| S13 | Langfuse 자체 호스팅 가격 | https://langfuse.com/pricing-self-host | 조회 2026-10-21 | 중 (검색 요약) |
| S14 | Langfuse Claude Agent SDK 통합 | https://langfuse.com/integrations/frameworks/claude-agent-sdk | 조회 2026-10-21 | 중 (검색 요약) |
| S15 | Claude Agent SDK 개요 (기능, Commercial Terms, claude.ai 로그인 금지) | https://code.claude.com/docs/en/agent-sdk/overview | 조회 2026-10-21 | 상 |
| S16 | Claude Agent SDK 빠른 시작 (Bedrock, Claude Platform on AWS, Agent Platform, Foundry 인증) | https://code.claude.com/docs/en/agent-sdk/quickstart | 조회 2026-10-21 | 상 |
| S17 | Claude Agent SDK 서브에이전트 (AgentDefinition, 깊이 3, 동시 20, 예산 상한) | https://code.claude.com/docs/en/agent-sdk/subagents | 조회 2026-10-21 | 상 |
| S18 | PyPI claude-agent-sdk 0.2.170 (MIT, Commercial Terms 적용) | https://pypi.org/project/claude-agent-sdk/0.2.170/ | 2026-10-21 | 상 |
| S19 | Claude Code "Other LLM gateways" ("doesn't support routing Claude Code to non-Claude models", allowedProviders) | https://code.claude.com/docs/en/llm-gateway | 조회 2026-10-21 | 상 |
| S20 | Claude Code 게이트웨이 호환 가이드 (API 형식, 기능 전달, 릴리스 추종 필요) | https://code.claude.com/docs/en/llm-gateway-protocol | 조회 2026-10-21 | 상 |
| S21 | Claude Code 게이트웨이 연결 (Agent SDK env, 추론 외 트래픽 차단) | https://code.claude.com/docs/en/llm-gateway-connect | 조회 2026-10-21 | 상 |
| S22 | Claude Code 데이터 사용 (텔레메트리, WebFetch 사전 검사, 공급자별 기본값) | https://code.claude.com/docs/en/data-usage | 조회 2026-10-21 | 상 |
| S23 | Claude Code 엔터프라이즈 배포 (공급자 비교, 게이트웨이 변수) | https://code.claude.com/docs/en/third-party-integrations | 조회 2026-10-21 | 상 |
| S24 | vLLM Claude Code 연동 가이드 | https://docs.vllm.ai/en/latest/serving/integrations/claude_code/ | 2026-03-12 | 상 |
| S25 | vLLM 도구 호출 문서 (파서 목록, 신뢰도 경고) | https://docs.vllm.ai/en/latest/features/tool_calling/ | 페이지 하단 2026-10-19 | 상 |
| S26 | vLLM 구조화 출력 문서 | https://docs.vllm.ai/en/latest/features/structured_outputs/ | 조회 2026-10-21 | 상 |
| S27 | PyPI vllm 0.32.0. 0.19.1은 2026-04-18 | https://pypi.org/project/vllm/0.32.0/ | 2026-10-18 | 상 |
| S28 | vLLM PR #29236 (Harmony 도구 파서 누락과 채널 누출 수정) | https://github.com/vllm-project/vllm/pull/29236 | 2025-11 | 중 (검색 요약) |
| S29 | Qwen3.5/3.6 도구와 추론 파서 패치 모음 (8개 PR) | https://gist.github.com/juanqui/ad80d1dcdfd69f4b3fb6f92c0e41e393 | 2026-04-25 | 중 (커뮤니티) |
| S30 | Ollama Anthropic API 호환 (v0.14.0+) | https://docs.ollama.com/api/anthropic-compatibility , https://ollama.com/blog/claude | 2026-01-16 | 중상 |
| S31 | LiteLLM의 Claude Agent SDK 튜토리얼 | https://docs.litellm.ai/docs/tutorials/claude_agent_sdk | 조회 2026-10-21 (날짜 미표기) | 중 |
| S32 | LiteLLM 1.82.7, 1.82.8 공급망 침해 | https://www.bitsight.com/blog/litellm-versions-1-82-7-1-82-8-supply-chain-compromise | 2026-03 (사고일 2026-03-24) | 중 |
| S33 | PyPI openai-agents 0.24.0 (MIT, litellm, any-llm extra) | https://pypi.org/project/openai-agents/0.24.0/ | 2026-10-15 | 상 |
| S34 | OpenAI Agents SDK 트레이싱 (기본 활성, OpenAI 백엔드 전송, 끄는 방법) | https://openai.github.io/openai-agents-python/tracing/ | 조회 2026-10-21 | 상 |
| S35 | PyPI google-adk 2.12.0 (Apache-2.0, a2a, litellm extra) | https://pypi.org/project/google-adk/2.12.0/ | 2026-10-13 | 상 |
| S36 | ADK A2A 문서 (Experimental) | https://adk.dev/a2a/ | 조회 2026-10-21 | 상 |
| S37 | ADK 2.0 리뷰 (Python 2.0 GA 2026-05-19) | https://chatforest.com/reviews/google-adk-2-agent-development-kit-review/ | 2026 | 중하 (2차 자료) |
| S38 | ADK LiteLLM 모델 연동 | https://adk.dev/agents/models/litellm/ | 조회 2026-10-21 | 중 (검색 요약) |
| S39 | Microsoft Agent Framework 1.0 발표 | https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/ | 2026-04-03 | 상 (검색 요약) |
| S40 | PyPI agent-framework 1.22.0 (MIT) | https://pypi.org/project/agent-framework/1.22.0/ | 2026-10-15 | 상 |
| S41 | MAF A2A 호스팅 문서 (.NET, Python, Go) | https://learn.microsoft.com/en-us/agent-framework/hosting/self-hosting/a2a/server | 2026-09-28 갱신 | 상 |
| S42 | PyPI agent-framework-a2a 1.0.0b261015 (Beta, `a2a-sdk>=1.0`) | https://pypi.org/project/agent-framework-a2a/ | 2026-10 | 상 |
| S43 | A2A 릴리스 (v1.0.0 2026-03-12, v1.0.1 2026-05-26) | https://github.com/a2aproject/A2A/releases | 2026-05-26 | 상 |
| S44 | Linux Foundation A2A 1주년 발표 (150곳 이상, 클라우드 통합) | https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year | 2026-04-09 | 상 |
| S45 | PyPI a2a-sdk 1.2.3 (Apache-2.0, A2A 1.0 + 0.3 호환) | https://pypi.org/project/a2a-sdk/1.2.3/ | 2026-10-19 | 상 |
| S46 | MCP 2026-07-28 스펙 발표 | https://blog.modelcontextprotocol.io/posts/2026-07-28/ | 2026-07-28 | 상 |
| S47 | PyPI mcp 2.3.0 | https://pypi.org/project/mcp/ | 조회 2026-10-21 | 상 |
| S48 | Linux Foundation Agentic AI Foundation 출범 (MCP, goose, AGENTS.md) | https://rcpmag.com/Articles/2025/12/09/Linux-Foundation-Unites-Major-Tech-Firms.aspx | 2025-12-09 | 중 |
| S49 | Cursor Agent Skills 문서 / SKILL.md 채택 현황 (2차) | https://cursor.com/docs/skills , https://noqta.tn/en/news/skill-md-open-standard-30-ai-coding-tools-adoption-2026 | 조회 2026-10-21 / 2026 | 상 / 중하 |
| S50 | METR 개발자 생산성 실험 개정 (2026 RCT 결과와 한계) | https://metr.org/blog/2026-02-24-uplift-update/ | 2026-02-24 | 상 |
| S51 | METR 2025 RCT (AI 사용 시 19% 느려짐) | https://metr.org/Early_2025_AI_Experienced_OS_Devs_Study-paper.pdf | 2025-07 | 상 |
| S52 | METR 2026 기술직 자기보고 조사 (중앙값 1.4~2배) | https://metr.org/blog/2026-05-11-ai-usage-survey/ | 2026-05-11 | 상 |
| S54 | Deep Agents Code CLI (`dcode`) | https://docs.langchain.com/oss/python/deepagents/cli/overview | 조회 2026-10-21 | 상 |
| R0 | 단가 조사 (온프렘 모델 후보, API 단가, 내부 인건비) | research/R0_단가조사_2026-10-20.md | 2026-10-20 | 내부 |
