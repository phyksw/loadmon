# R5, 온프렘 로컬 LLM 은 Agent 업무를 어디까지 감당하나 (운영 2안 판단 근거)

> **요약**
> 1. 768GB 서버(8× RTX PRO 6000)에 올릴 수 있는 상위 오픈 웨이트 모델(GLM-5.3-Flash, DeepSeek-V4.1-Flash, Qwen3.8-27B)은 **정해진 이슈 수정과 도구 호출**에서 프런티어와 차이가 작다. 독립 측정 기준 SWE-bench Verified 5~11%p, BFCL v4 다중턴 0.4%p(구세대 비교), τ²-bench 는 거의 만점에 수렴.
> 2. **장시간과 다단계 과제**에서는 차이가 크다. Terminal-Bench 4.0(과제당 최대 8시간)에서 Claude Opus 5.5 65.15% vs 로컬 최상위 37.37%(GLM-5.3-Flash)로 **28%p** 차이다. 로컬 최상위가 Claude Haiku 5.5(36.36%)와 비슷한 수준이다. 27B급은 AA 측정 5.6%로 무너진다.
> 3. 처리량은 RTX PRO 6000 4장 기준 GLM-5.3-Flash NVFP4 단일 281 tok/s, 동시 8건 합계 898 tok/s, Qwen3.5-397B NVFP4 는 64K 컨텍스트와 동시 32건에서 합계 1,271 tok/s(커뮤니티 실측)다. 에이전트 부하(프리필과 도구 턴)를 보정하면 **장당 활성 세션 5개(보수 2 / 낙관 10)**로 본다(추정).
> 4. 정리하면, 2안(로컬 단독)은 RAG, 추출, 분류, 고정 도구 워크플로우(C3 처리)에는 충분하다. 반면 바이브 코딩과 서브에이전트 조율과 장시간 자율 실행에서는 효과가 줄어 **공수 1.4배(1.15~1.8, 추정)**가 든다. 근거상으로는 개발(C0~C2)은 외부 프런티어, C3 런타임은 로컬(vLLM + LangGraph 고정 그래프)로 나누는 혼합 운영이 유리하다. vLLM 이 Anthropic Messages API 와 OpenAI 호환 API 를 함께 제공하므로, 같은 에이전트 코드에서 백엔드만 바꿀 수 있다.
> 5. 권장 조합(서버 1대): **GLM-5.3-Flash NVFP4(TP4, MIT) + Qwen3.8-27B FP8 2~3개 복제(Apache 2.0) + 임베딩과 리랭커**. 2대째는 DeepSeek-V4.1-Flash(TP4, MIT)를 두거나 같은 구성을 복제한다. K-EXAONE 2.0 은 Apache 2.0 이라 사용에는 문제가 없지만, 서버 1대를 통째로 쓰는 데 비해 에이전트 점수가 낮아 PoC 용도로 본다.

- 조사일: **2026-10-21 (KST)**. 기준 프런티어는 **Claude Opus 5.5 (2026-09-22 출시)**, 로컬 서버는 **8× RTX PRO 6000 Blackwell 96GB = 768GB, NVLink 없음(PCIe 5.0)** 2대('27.7 가동)
- 표기
  - 3값: **hi = 보수 / base = 기준 / lo = 낙관**. 세션 수처럼 클수록 좋은 값은 hi 가 작은 값임에 주의
  - **추정** = 계산과 가정이 들어간 값(식 병기). **미확인** = 찾지 못한 값
  - 신뢰도: **상**(공식과 독립 측정 기관) / **중**(집계 사이트, 공급사 모델카드) / **하**(블로그와 커뮤니티, 검색 요약)
  - "공급사 발표"라고 적은 점수는 마케팅 성격이 있으며 독립 측정보다 높게 나오는 경향이 있음(1장)
- 제약: 조사 도중 세션의 웹 검색 한도가 소진되어, 이후는 이미 알고 있던 URL 을 직접 열어 확인했다. 그래서 일부 항목(BFCL 최신 모델, EXAONE 그룹 내부 조건 등)은 **미확인**으로 남았다.

---

## 1. 점수를 읽기 전에, 공급사 발표와 독립 측정의 차이

같은 Terminal-Bench 2.1 이라도 공급사 모델카드 값이 독립 측정(Vals AI, Terminus 2 하네스)보다 **12~21%p 높다**. 그래서 이 보고서의 격차 계산은 독립 측정을 우선한다.

| 모델 | 공급사 발표 TB2.1 | Vals 독립 측정 TB2.1 | 차이(%p) | 출처 (발표일) | 신뢰도 |
|---|---|---|---|---|---|
| DeepSeek-V4.1-Flash | 90.6 | 74.53 | -16.1 | https://braindetox.kr/en/posts/deepseek_v4_1_flash_1017_update_2026.html (2026-10-17), https://www.vals.ai/benchmarks/terminal-bench-2-1 (갱신 2026-09-28) | 중 / 상 |
| GLM-5.3 | 88.2 | 71.54 | -16.7 | https://www.yottalabs.ai/post/glm-5-3-hardware-requirements-gpu-memory-2026 (2026-09-21), Vals 상동 | 중하 / 상 |
| GLM-5.3-Flash | 84.3 | 62.92 | -21.4 | https://benchlm.ai/models/glm-5-3-flash (Z.AI 블로그 인용, 2026-10-20 조회), Vals 상동 | 중 / 상 |
| Qwen3.8-27B | 73.0 | 58.43 | -14.6 | https://huggingface.co/Qwen/Qwen3.8-27B (2026-08), Vals 상동 | 상(카드) / 상 |
| MiniMax-M3 | 66.0 | 53.56 | -12.4 | https://benchlm.ai/models/minimax-m3 (MiniMax 블로그 인용), Vals 상동 | 중 / 상 |
| 참고: Claude Opus 5.5 | TB4.0 66.4 (발표) | TB4.0 65.15 (Vals), 64.85 (tbench 공식), 59.6 (AA) | -1.3 ~ -6.8 | https://www.anthropic.com/news/claude-opus-5-5 (2026-09-22), https://www.vals.ai/benchmarks/terminal-bench-4 (2026-10-19) | 상 |

- 공급사 표는 하네스와 시도 횟수와 타임아웃이 서로 다르다. 예를 들어 Qwen3.8-27B 의 SWE-bench Pro 는 Claude Code 하네스, TB2.1 은 Terminus 하네스로 측정했다(모델카드 각주).
- Terminal-Bench 2.x, SWE-bench Verified 는 상위권이 포화되어 Vals 에서 "보관(archived)" 처리되었다. 차세대 기준은 **Terminal-Bench 4.0**(66과제, 과제당 최대 8시간)이다.

---

## 2. 프런티어 대비 격차 (독립 측정 우선)

### 2-1. 벤치마크별 비교, "로컬 적재 가능" 모델만

로컬 적재 가능 여부는 3장 판정을 따른다(768GB 에 4bit 이하로 올라가는지).

| 벤치마크 (측정 주체, 하네스, 일자) | 과제 성격 | 프런티어 | 로컬 적재 가능 모델 | 격차 (%p) | 출처 | 신뢰도 |
|---|---|---|---|---|---|---|
| SWE-bench Verified (Vals, mini-SWE-agent, 2026-09-01, 포화로 보관) | 정해진 레포의 단일 이슈 수정 | Claude Opus 5: 97.0 | GLM-5.3 95.4 / GLM-5.3-Flash 92.0 / DeepSeek-V4-Flash-0731 88.8 / Qwen3.8-27B 86.0 / gpt-oss-120b 33.6 | 1.6 / 5.0 / 8.2 / 11.0 / 63.4 | https://www.vals.ai/benchmarks/swebench | 상. Opus 5.5 는 미등재 |
| Terminal-Bench 2.1 (Vals, Terminus 2, 2026-09-28) | 터미널 다단계 과제(수십 분) | Opus 5.5: 87.64 (과제당 $0.50, 6분 23초) | DS-V4.1-Flash 74.53 / GLM-5.3 71.54 / GLM-5.3-Flash 62.92 / Qwen3.8-27B 58.43 / MiniMax-M3 53.56 | 13.1 / 16.1 / 24.7 / 29.2 / 34.1 | https://www.vals.ai/benchmarks/terminal-bench-2-1 | 상. 소요시간은 GLM-5.3-Flash 16분 06초, Qwen3.8-27B 14분 53초로 Opus 5.5 의 2.3~2.5배(API 서빙 기준) |
| **Terminal-Bench 4.0** (Vals, mini-swe-agent, avg@3, 과제당 8시간 한도, 2026-10-19) | 장시간 자율 실행 | Opus 5.5: **65.15** ($13.20/과제, 1시간 04분), Sonnet 5.5 64.14, **Haiku 5.5 36.36** | GLM-5.3 38.89 / **GLM-5.3-Flash 37.37** / DS-V4.1-Flash-1017 31.82 / MiniMax-M3 1.01 | 26.3 / **27.8** / 33.3 | https://www.vals.ai/benchmarks/terminal-bench-4 | 상. 로컬 최상위가 Haiku 5.5 수준 |
| Terminal-Bench 4.0 (tbench 공식, Claude Code 하네스, 2026-10-19 스냅샷) | 상동 | Opus 5.5 (max): 64.85 | GLM-5.3 (max) 41.82 / GLM-5.3-Flash 35.76 | 23.0 / 29.1 | https://www.benchlm.ai/benchmarks/terminal-bench-4 | 중(집계 사이트 미러). 오픈 모델도 Claude Code 하네스로 돌아간다는 근거가 됨 |
| Terminal-Bench 4.0 (Artificial Analysis, mini-swe-agent, 3회 평균) | 상동 | Opus 5.5: 59.6 | GLM-5.3-Flash 32.8 / **Qwen3.8-27B 5.6** | 26.8 / **54.0** | https://artificialanalysis.ai/evaluations/terminalbench-v4-0 , https://benchlm.ai/models/qwen3.8-27b , https://benchlm.ai/models/glm-5-3-flash (2026-10-20) | 중상. 27B dense 는 장시간 과제에서 무너짐 |
| MCP-Atlas (BenchLM 집계, 2026-10-20) | 실제 MCP 서버 다수를 쓰는 도구 조합 | Claude Opus 5: 85.8 | MiniMax M3 74.2(라이선스 제약, 5장) / DS-V4-Flash-0731 69.0 / Qwen3.6-35B-A3B 62.8 | 11.6 / 16.8 / 23.0 | https://benchlm.ai/benchmarks/mcpatlas | 중. 평가 설정이 공개되지 않았고 일부는 공급사 발표. Opus 5.5 는 미등재 |
| OpenHands Index (BenchLM 미러, 2026-09-28) | 이슈 해결, 프런트엔드, 신규 개발, 테스트, 정보 수집 종합 | Claude Opus 4.8: 71.9 (Fable 5: 81.0) | GLM-5.1 58.2(4bit 8장) / MiniMax M3 57.2 / Qwen3-Coder-Next 43.8 / MiniMax M2.7 43.4 | 13.7 / 14.7 / 28.1 / 28.5 | https://benchlm.ai/benchmarks/openhandsindex | 중. Opus 5.5 와 신규 오픈 모델(GLM-5.3 계열)은 미등재 |
| BFCL v4 (UC Berkeley 공식, 갱신 2026-04-12) | 함수 호출(단일, 다중턴, 웹검색, 메모리) | Claude Opus 4.5: 77.47 (다중턴 68.38, 메모리 73.76) | GLM-4.6: 72.38 (다중턴 68.00, 메모리 55.70) | 5.1 (다중턴 0.4, 메모리 18.1) | https://gorilla.cs.berkeley.edu/leaderboard.html , https://gorilla.cs.berkeley.edu/data_overall.csv | 상(측정) / 하(현재성). 2026 하반기 모델은 미등재 |
| τ²-bench (Artificial Analysis 값, BenchLM 인용) | 고객응대형 정책 준수 도구 호출 | Opus 5.5 **미확인** | MiniMax M3 88.9 / gpt-oss-120b 65.8 / GLM-5.2 99.1(최고치) |, (상위권 포화) | https://benchlm.ai/models/minimax-m3 , https://benchlm.ai/models/gpt-oss-120b , https://benchlm.ai/benchmarks/tau2-bench | 중. 후속인 τ³-bench 로 이전 중 |
| SWE-bench Pro (Scale 공개 리더보드) | 다파일과 장문 이슈 | 최신 모델 미등재(Opus 4.6 51.9가 최신) | qwen3-coder-480b 38.7, gpt-oss-120b 16.2 | 참고만 | https://labs.scale.com/leaderboard/swe_bench_pro_public (날짜 미표기) | 하(현재성). 공급사 발표로는 Qwen3.8-27B 61.7(Claude Code 하네스), Opus 5.5 89.9(시스템카드 인용, 원문 미확인) |

### 2-2. 거시 지표 (최상위 오픈 모델 기준이며, 768GB 적재 모델은 이보다 한 단계 아래)

| 지표 | 값 | 기준일 | 출처 | 비고/신뢰도 |
|---|---|---|---|---|
| Epoch Capabilities Index 기준 오픈 vs 클로즈드 격차 | 평균 **약 4개월**(ECI 8점 ≈ GPT-5 와 GPT-5.5 의 차이). 2025-10 측정치는 약 3개월로, 격차가 소폭 커짐 | 2026-05-29 | https://epoch.ai/data-insights/open-closed-eci-gap | 상. 비교 대상은 1T급 이상의 최상위 오픈 모델 |
| NIST CAISI 의 DeepSeek V4 Pro 평가 | 미국 프런티어보다 **약 8개월** 뒤처짐(비공개 벤치마크 포함 9종). 공급사 자체 발표로는 Opus 4.6, GPT-5.4 수준 | 2026-05 | https://www.nist.gov/news-events/news/2026/05/caisi-evaluation-deepseek-v4-pro | 중상. 방법론 비판 보도 있음(decrypt.co) |
| OpenHands 팀 평가 | "Claude 가 추세보다 몇 달 앞서 있고, 그다음이 GPT". 테스트 작성은 Claude 가 명확한 1위, 병렬 도구 호출로 Claude, GPT 가 가장 빠름 | 2026-05-11 | https://hub.openhands.dev/blog/openhands-index-3-months-out | 중 |
| 768GB 적재 모델의 추가 격차 | Kimi K3(2.8T), MiMo-V2.6-Pro(1T) 같은 최상위 오픈 모델은 768GB 에 올라가지 않는다. 적재 가능한 GLM-5.3-Flash(320B)는 TB2.1 에서 Kimi K3 보다 18%p 낮음(80.90 vs 62.92) | 2026-09-28 | https://www.vals.ai/benchmarks/terminal-bench-2-1 , https://artificialanalysis.ai/models/open-source | 상. 같은 온프렘에서도 "4개월 격차"보다 실제 격차가 큼(추정) |

### 2-3. 해석, 과제가 길고 열려 있을수록 격차가 벌어진다

| 과제 난도와 길이 | 대표 벤치마크 | 로컬 최상위(적재 가능) vs Opus 5.5 격차 | 근거 |
|---|---|---|---|
| 형식이 정해진 단일 도구 호출과 정책 준수 | BFCL v4 다중턴, τ²-bench | **0~5%p** | 2-1 표 BFCL, τ² 행 |
| 실제 MCP 서버 조합, 단일 이슈 수정 | MCP-Atlas, SWE-bench Verified | **5~17%p** | 2-1 표 |
| 수십 분짜리 터미널 다단계 | TB2.1 | **13~25%p** (27B 는 29%p) | Vals TB2.1 |
| 1시간 이상 자율 실행 | TB4.0 | **26~33%p** (27B 는 54%p) | Vals, AA TB4.0 |

---

## 3. 8× RTX PRO 6000 (768GB) 적재 가능성

계산식(**추정**): 가중치(GB) ≈ 총 파라미터(B) × 바이트/파라미터(BF16 2, FP8 1, NVFP4, INT4 약 0.5~0.56). KV 캐시와 활성화로 GPU 당 10~30% 여유가 필요하다. RTX PRO 6000 은 NVLink 가 없으므로 **TP ≤ 4 + 복제 구성**을 우선한다(4-2).

| 모델 (공개일) | 총 / 활성 파라미터 | 정밀도별 가중치 | RTX PRO 6000 필요 장수 | 실측 여부 | 판정 | 출처 | 신뢰도 |
|---|---|---|---|---|---|---|---|
| **GLM-5.3-Flash** (2026-08 말) | 320B / 18B | FP8 약 306GiB, NVFP4 약 170~180GB(추정) | NVFP4: 4장 권장(2장도 가능하나 KV 899K 토큰으로 빠듯), FP8: 4장 빠듯, 8장 여유 | **있음**(4장과 2장) | **적재 가능과 권장** | https://huggingface.co/zai-org/GLM-5.3-Flash , https://www.yottalabs.ai/post/glm-5-3-hardware-requirements-gpu-memory-2026 , https://github.com/local-inference-lab/rtx6kpro/blob/master/models/glm-5.3-flash.md | 상(사양) / 하(커뮤니티 실측) |
| **DeepSeek-V4.1-Flash(-1017)** (2026-09-10 / 10-17) | 552B 백본 + Engram 196B / 디코드 16B | FP4 전문가 + FP8 혼합. 체크포인트 크기 **미확인** | 4장(TP4, 커뮤니티 프로필). Engram 테이블 약 189GiB 는 호스트 RAM 또는 디스크에 둠 | **있음**(4장) | **적재 가능** | https://braindetox.kr/en/posts/deepseek_v4_1_flash_1017_update_2026.html , https://github.com/local-inference-lab/rtx6kpro/blob/master/models/deepseek-v4.1-flash.md | 중 / 하. 서버 호스트 메모리 192GB 이상 필요(추정) |
| **Qwen3.8-27B** (2026-08-14) | 27B dense (비전 포함 28B) | BF16 55.6GB, FP8 약 28GB(추정) | 1장(복제 운용) | 부분(TP1~4 런북 존재, 수치 미확인) | **적재 가능과 권장**(서브 에이전트용) | https://huggingface.co/Qwen/Qwen3.8-27B , https://www.orcarouter.ai/blog/qwen-3-8-27b-benchmarks (2026-08-17) | 상 |
| Qwen3.5-397B-A17B (2026-02) | 397B / 17B | NVFP4 약 200~220GB(추정), FP8 약 400GB | NVFP4 4장, FP8 8장 | **있음**(4장과 8장) | 적재 가능. 다만 GLM-5.3-Flash, DS-V4.1-Flash 보다 구세대 | https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/inference-throughput/README.md (2026-03-14) | 하(커뮤니티) |
| GLM-5.3 (2026-08-25) | 753B / 40B | FP8 약 744GB(768GB 에 KV 여유 없음), 4bit 약 372GB | 4bit 8장(서버 1대 전체) | GLM-5(구판) NVFP4 8장 실측만 있음 | 적재는 가능하나 **비권장**: TB4.0 에서 Flash 보다 1.5%p 높을 뿐인데 GPU 는 2배 | https://www.yottalabs.ai/post/glm-5-3-hardware-requirements-gpu-memory-2026 , https://www.vals.ai/benchmarks/terminal-bench-4 | 중 |
| **K-EXAONE 2.0** (2026-07-31) | 750B / 37B | FP8 약 750GB(여유 없음), NVFP4 체크포인트 약 530GB(R0) | NVFP4 8장(서버 1대 전체) | RTX PRO 6000 실측 **미확인**. 모델카드 예시는 H200 8장 × 2노드. vLLM, SGLang 모두 저자 포크가 필요 | **PoC 용**: TB2.1 43.8, SWE-V 68.2(공급사 발표)로 Qwen3.8-27B 공급사 발표치(73.0)보다 낮음 | https://huggingface.co/LGAI-EXAONE/K-EXAONE-2.0-750B-A37B , https://lg.co.kr/media/release/30411 | 상 |
| EXAONE 4.5 (2026-04-09) | 33B dense (VLM) | BF16 약 66GB(추정) | 1장 |, | 라이선스 때문에 업무 사용 불가(5장) | https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B | 상 |
| gpt-oss-120b (2025-08) | 117B / 5.1B | MXFP4 약 63GB | 1장 | **있음**(1장) | 적재 가능. 분류와 라우팅용(SWE-V Vals 33.6 으로 코딩 부적합) | https://huggingface.co/openai/gpt-oss-120b , https://www.databasemart.com/blog/vllm-gpu-benchmark-pro6000 | 상 |
| MiniMax-M3 (2026-06) | 428B / 23B | BF16 854GB, FP8 약 428GB, 4bit 약 242GB | 4bit 4장, FP8 8장 | 미확인 | 라이선스 협의 필요(5장). TB4.0 1.01% | https://www.vals.ai/benchmarks/terminal-bench-4 , 검색 요약(howaiworks.ai, minimax-ai.chat) | 중하 |
| Kimi K2.5/K2.6 | 1T / 32B | INT4 약 594GB | 8장 | **있음**(K2.5: 단일 32~101 tok/s, 동시 100건이면 사용자당 9 tok/s) | 비권장(동시성 낮음) | https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/results.md | 하 |
| Qwen3-Coder-Next / Qwen3.6-35B-A3B | 80B / 3B, 35B / 3B | FP8 80GB, 35GB | 1장 | 미확인 | 적재 가능. OpenHands 문서가 첫 로컬 모델로 Qwen3.6-35B-A3B 를 권장(2026-05-21) | https://docs.openhands.dev/openhands/usage/llms/local-llms , https://benchlm.ai/benchmarks/openhandsindex | 중 |
| Devstral 2 (123B) / Devstral Small 2 (24B) | dense | FP8 123GB / 24GB | 2장 / 1장 | 미확인 | Devstral 2 는 라이선스상 불가, Small 2 는 가능(5장) | https://simonwillison.net/2025/Dec/9/devstral-2/ (2025-12-09) | 중 |
| 768GB 초과 (참고) | Kimi K3 2.8T, MiMo-V2.6-Pro 1T, DeepSeek-V4-Pro 1.6T |, | 다중 노드 |, | 적재 불가 | https://artificialanalysis.ai/models/open-source | 중 |

---

## 4. 처리량과 동시 세션 (RTX PRO 6000 실측)

### 4-1. 실측값

| 모델과 구성 | 동시 요청 | 합계 출력 tok/s | 사용자당 tok/s | 프리필 (32K 비캐시) | 기준일, 출처 | 신뢰도 |
|---|---|---|---|---|---|---|
| GLM-5.3-Flash NVFP4, 4장 TP4, vLLM, MTP3, FP8 KV | 1 / 8 | 281.3 / 897.6 | 281 / 112 | 13,816 tok/s. KV 용량 5,595,903 토큰(공유) | 2026-09-22 빌드, https://github.com/local-inference-lab/rtx6kpro/blob/master/models/glm-5.3-flash.md | 하(커뮤니티, Max-Q 카드) |
| GLM-5.3-Flash NVFP4, 2장 TP2 | 1 / 4 | 186.5 / 403.1 | 187 / 101 | 10,919 tok/s. KV 약 899K 토큰(빠듯) | 2026-09-22 빌드, https://github.com/local-inference-lab/rtx6kpro/blob/master/models/glm-5.3-flash-spark-tp2.md | 하 |
| DeepSeek-V4.1-Flash, 4장 TP4, vLLM, FP8 KV | 1 / 8 | 249.1 / 805.5 | 249 / 101 | 17,982 tok/s. KV 4,727,748 토큰 | 2026-09-22 빌드, https://github.com/local-inference-lab/rtx6kpro/blob/master/models/deepseek-v4.1-flash.md | 하 |
| Qwen3.5-397B-A17B NVFP4(nvidia 체크포인트), 4장 TP4, vLLM 0.17, MTP, **컨텍스트 64K** | 16 / 32 / 64 / 128 | 877 / 1,271 / 1,912 / 2,159 | 55 / 40 / 30 / 17 |, | 2026-03-14, https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/inference-throughput/README.md | 하. 디코드 중심 측정(턴마다 들어오는 프리필은 미반영) |
| 상동, **컨텍스트 128K** | 32 / 64 / 128 | 1,164 / 1,620 / 2,138 | 36 / 25 / 17 |, | 상동 | 하 |
| NVFP4 품질 손실 (Qwen3.5-397B, FP8 대비) |, | KLD 0.035~0.036, GPQA 86.6~88.5% 로 통계적 차이 없음 |, |, | 2026-03-11~14, https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/nvfp4-quantization-comparison.md | 하. 에이전트 과제의 품질 영향은 **미확인** |
| MiniMax-M2.5 AWQ, 2장, vLLM | 64 | 930 (최대 1,551) | 약 15 (TPOT 56ms) |, | https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/results.md | 하 |
| Kimi K2.5 INT4, 8장, vLLM, 컨텍스트 40K | 100 | 900 | 9 |, | 상동 | 하. P2P 를 끄면 단일 65 → 44 tok/s |
| GLM-5 NVFP4, 8장, SGLang, MTP | 3 | 133~135 | 약 45 |, | 상동 | 하. 750B급 동시성의 한계를 보여줌 |
| gpt-oss-120b, 1장, vLLM (입력 100 / 출력 600, 짧은 컨텍스트) | 50 | 1,778.77 | 약 31 (TPOT 32.24ms) |, | 갱신 2026-10-07(또는 07-10), https://www.databasemart.com/blog/vllm-gpu-benchmark-pro6000 | 중하 |
| 참고: gpt-oss-120b, H200 1장, 에이전트 트레이스(입력 64K / 출력 400) | 32 | GPU 당 1,256 | 47.5 |, | https://docs.nvidia.com/dynamo/v1.5.0/recipes/gpt-oss-120b.md (R0 2-2) | 상 |
| NVLink 없는 8장 TP 스케일링 |, | Qwen3 235B: 4장 58 tok/s → 8장 37 tok/s(더 느려짐) |, |, | https://www.mindstudio.ai/blog/rtx-pro-6000-8x-camino-grando-workstation | 하(검색 요약). TP ≤ 4 + 복제 구성이 유리 |

### 4-2. 장당 동시 에이전트 세션 산정 (**추정**)

정의: 사용자당 디코드 **25~30 tok/s 이상**, 컨텍스트 64~128K 를 유지하는 **활성 세션**(지금 LLM 을 호출 중인 세션). 해석 솔버를 기다리는 동안처럼 도구 실행 중인 세션은 제외한다. 논리 세션 수는 이 값의 2~3배가 될 수 있다(추정).

| 구성 | 디코드만 볼 때 장당 세션 | 에이전트 보정 | 결과 | 계산 근거 |
|---|---|---|---|---|
| 중형 MoE (활성 17~18B: GLM-5.3-Flash, Qwen3.5-397B), NVFP4 4장 | 64K: 동시 64건에 30 tok/s → 16 / 128K: 동시 32건에 36 tok/s → 8 | × 0.5 | **4~8 → 기준 5** | 보정 계수 0.5(추정): 세션 32개가 15초마다 새 토큰 5K 를 넣으면 프리필 수요가 10.7K tok/s 로, 4장 프리필 용량(13.8K)의 77% 를 차지해 디코드가 지연됨 |
| 소형 (gpt-oss-120b 1장, Qwen3.8-27B 1장) | gpt-oss: 50건에 31 tok/s(짧은 컨텍스트). H200 에이전트 트레이스 32세션 × 대역폭비(1.8 / 4.8 TB/s = 0.375) ≈ 12 |, | **약 10 (낙관)** | R0 의 장당 10세션 추정과 같은 수준 |
| 대형 (GLM-5.3, K-EXAONE 2.0, Kimi, 4bit 8장) | GLM-5: 3건에 45 tok/s, Kimi: 100건에 9 tok/s |, | **≤ 2 (보수)** | 750B~1T급은 PCIe TP8 이라 동시성이 낮음 |

- 서버 1대 규모 감(추정): 권장 조합 A(8장)는 GLM-5.3-Flash 4장 × 5 = 20 + Qwen3.8-27B 3장 × 8 = 24 → **활성 세션 약 40~45개**. 2대면 80~90개다. 34명 팀 + '27 Agent 13개 + 야간 배치 수준이면 대수는 충분하다는 계산이지만, 실부하 측정은 **미확인**이다.

---

## 5. 라이선스, LG이노텍 내부 업무 사용 관점

| 모델 | 라이선스 | LG이노텍 업무 사용 | 근거, 출처 | 신뢰도 |
|---|---|---|---|---|
| **K-EXAONE 2.0** | Apache 2.0 | **가능**. 외부 공개 라이선스이므로 그룹사라고 별도 조건이 붙지 않음 | 2026-07-31 LG 보도자료 "라이선스 전면 개방", https://lg.co.kr/media/release/30411 , https://huggingface.co/LGAI-EXAONE/K-EXAONE-2.0-750B-A37B | 상 |
| EXAONE 4.5 (33B), EXAONE 4.0 | EXAONE AI Model License 1.2 - NC (라이선서: LG경영개발원) | **연구와 교육 목적만 허용**. §3.1 상업적 이용 금지, §2.2 명시되지 않은 이용은 서면 동의 필요. 사내 업무 적용은 별도 상업 라이선스가 필요함. **그룹 계열사 대상 내부 제공 조건은 미확인** | https://scancode-licensedb.aboutcode.org/exaone-ai-model-1.2-nc.yml , https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B | 상(조문) / 미확인(그룹 내부 조건) |
| Qwen3.8-27B, Qwen3.5/3.6 계열 | Apache 2.0 | 가능 | https://huggingface.co/Qwen/Qwen3.8-27B | 상 |
| GLM-5.3-Flash | MIT | 가능 | https://www.noze.it/en/insights/glm-5-3-weights-licence-benchmark-method/ (2026-09-02) | 상 |
| GLM-5.3 | glm-5.3 커스텀(MIT 에 가까움) | 조건은 **MaaS(제3자에게 추론 제공) 사업 + 계열 합산 연매출 100억 달러 초과**일 때 Z.AI 보안심사. 사내 사용은 MaaS 에 해당하지 않는 것으로 보이지만, LG 계열 합산 매출이 기준을 넘으므로 **법무 확인 필요** | 상동 | 중 |
| DeepSeek-V4.1-Flash | MIT | 가능 | https://braindetox.kr/en/posts/deepseek_v4_1_flash_1017_update_2026.html | 중 |
| gpt-oss-120b | Apache 2.0 | 가능 | https://huggingface.co/openai/gpt-oss-120b | 상 |
| MiniMax-M3 | MiniMax Community License | 연매출 2,000만 달러 초과 시 **사전 서면 승인 필요** → LG이노텍 해당. 군사 용도 금지 조항도 있음 | 검색 요약(minimax-ai.chat/guide/minimax-m3-license, howaiworks.ai) | 중하. 원문 미확인 |
| Devstral 2 (123B) | modified MIT | 월매출 2,000만 달러 초과 기업은 권리 없음 → **불가**(상용 라이선스 또는 API 필요) | https://simonwillison.net/2025/Dec/9/devstral-2/ | 중 |
| Devstral Small 2 (24B) | Apache 2.0 | 가능 | 상동 | 중 |
| Kimi K2.x | modified MIT | 조건 원문 **미확인** |, |, |

---

## 6. 코딩 에이전트 하네스를 로컬 모델로 돌린 실사용 보고

| 항목 | 내용 | 기준일, 출처 | 신뢰도 |
|---|---|---|---|
| vLLM → Claude Code 연결 | vLLM 이 **Anthropic Messages API** 를 구현하므로 `ANTHROPIC_BASE_URL` 로 Claude Code 를 로컬 vLLM 에 붙일 수 있다. `ANTHROPIC_DEFAULT_OPUS/SONNET/HAIKU_MODEL` 로 등급별 모델(서브에이전트 포함)을 매핑하며, 공식 예시는 gpt-oss-120b. 경고: Claude Code 가 요청마다 시스템 프롬프트에 해시를 넣어 **프리픽스 캐시가 깨지는 문제**가 있고, vLLM 0.17.1 초과 버전에서 자동 처리된다 | 2026-03-12, https://docs.vllm.ai/en/stable/serving/integrations/claude_code/ | 상 |
| 공급사 평가에 쓰인 하네스 | Qwen3.8-27B 의 SWE-bench Pro, DeepSWE, GLM-5.3-Flash 의 TB2.1(Claude Code 2.1.207), DS-V4.1-Flash-1017 의 TB4.0, tbench 공식 TB4.0 의 GLM-5.3 항목이 모두 **Claude Code 하네스**로 측정됨. 오픈 모델을 Claude Code 하네스에서 돌리는 것이 평가 관행이 됨 | 2026-08~10, 각 모델카드, https://www.benchlm.ai/benchmarks/terminal-bench-4 | 중 |
| OpenHands 로컬 모델 안내 | 첫 로컬 모델로 Qwen3.6-35B-A3B 권장(2026-05-21). 컨텍스트 22K 이상(32K 권장). "컨텍스트가 커도 일부 로컬 모델은 도구 사용이 불안정하며, 챗봇처럼 행동하거나 도구 호출이 계속 실패하면 모델이 원인인 경우가 많다" | https://docs.openhands.dev/openhands/usage/llms/local-llms | 상 |
| codecentric 실무 시험 (Claude Code, 노트북 M3 Max 36GB) | Opus 4.8 은 가장 자율적이고 결과가 완벽, GLM-5.2(클라우드)는 가성비 1위. **Qwen3.6-27b 로컬은 2.5시간 동안 두 번째 과제를 끝내지 못함.** 약한 모델은 도구를 명시해 주면 복구되지만 개발자 숙련도가 필요. 결론은 "업무용은 로컬 PC 보다 클라우드와 프라이빗 클라우드" | 2026-08-13, https://www.codecentric.de/en/knowledge-hub/blog/local-llms-in-a-software-developers-day-to-day-work | 중. 서버가 아닌 노트북 기준이며 1회 시험 |
| 50과제 비교 (Qwen3-Coder Q4, 16GB GPU vs Claude Sonnet 5, 15점 만점) | 단일 파일 생성 13.1 vs 13.0, 단위 테스트 13.0 vs 12.8, 버그 진단 12.5 vs 13.8, **다파일 리팩터링 11.4 vs 13.6**, 코드 리뷰 12.0 vs 12.8, 종합 12.4 vs 13.2. "Claude Code 를 로컬 백엔드로 써도 완전 오프라인은 아님"이라는 주장도 있음 | 갱신 2026-07-12, https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark.md | 하(개인 블로그). 폐쇄망 동작 여부는 미확인 |
| OpenHands Index 정성 평가 | 이슈 해결은 "많은 모델이 좋은 결과", 신규 개발은 Claude, GPT 우세, 테스트는 Claude 가 명확한 1위. GLM-5.1 은 프런트엔드에서 상위권에 근접 | 2026-05-11, https://hub.openhands.dev/blog/openhands-index-3-months-out | 중 |
| 장시간 실행 사례 (프런티어) | Opus 5.5: 고객 사례로 무인 18시간 이상, 6개 저장소, 68만 줄 마이그레이션 하루 미만, 서브에이전트 위임 개선(공급사 발표) | 2026-09-22, https://www.anthropic.com/news/claude-opus-5-5 | 중(공급사 발표와 고객 사례) |
| 장시간 실행 사례 (로컬 모델) | 같은 수준의 측정과 사례를 **찾지 못함**. METR 시간 지평(time horizon)도 오픈 모델 값은 미공개 |, | 미확인 |

---

## 7. 업무 유형별 로컬 적합도

| 업무 유형 | 로컬 적합도 | 근거 (격차) | 적용 조건과 보완 | '27 과제 적용 예 | 출처 |
|---|---|---|---|---|---|
| **RAG 질의응답과 문서 추출과 분류** | **상** | 도구 호출과 정책 준수 격차 0~5%p(BFCL 다중턴, τ²). 장문 성능은 K-EXAONE 2.0 MRCR 94.4, Qwen3.5 93.0(공급사 발표). 처리량 여유 큼 | 임베딩과 리랭커는 GPU 1장 일부로 충분(R0 2-3). 한국어 기술문서와 도면 OCR 품질은 사내 평가셋으로 확인 | AL-1 설계지식 RAG, VV-3 BOM, 도면 속성 추출, RVTM 요구사항 분류 | 2-1 표, https://huggingface.co/LGAI-EXAONE/K-EXAONE-2.0-750B-A37B |
| **고정 도구 호출 워크플로우** (순서가 정해진 MCP, 스크립트 호출) | **상** | MCP-Atlas 격차 12~17%p 이지만, 순서를 그래프(LangGraph)가 정하고 모델은 인자만 채우면 BFCL 형 과제(0~5%p)로 축소됨(추정). vLLM 구조화 출력과 도구 파서 지원 | 단계마다 스키마 검증 + 재시도. 실패 시 사람에게 넘기는 분기를 둠 | AL-1 야간 무인해석(메시 → 해석 → 결과 추출 → 리포트), VV-3 PLM 연동 MCP 조회 | 2-1 표, https://docs.vllm.ai/en/stable/serving/integrations/claude_code/ |
| **다단계 서브에이전트 조율** (lead 가 계획, 위임, 통합) | **중** | 종합 에이전트 지표 OpenHands Index 격차 14~28%p, MCP-Atlas 17~23%p. 계획 실패 사례(codecentric: MiniMax 계획 부실과 허위 저장소 생성). 서브에이전트 조율 전용 벤치마크는 미확인 | lead 는 결정적 그래프로 두고 sub 만 LLM 에 맡기거나, C3 가 없는 단계의 lead 는 외부 프런티어로 둠. 로컬 lead 는 GLM-5.3-Flash급 이상 | VV-3 SI/PI, EMC, 열, 공차 해석 조율, VV-1 ODD 시나리오 생성 → 검증 반복 | 2-1 표, codecentric |
| **코드 생성과 수정 (바이브 코딩)** | **중** | 단일 이슈 수정 5~11%p(SWE-V), 단일 파일은 거의 동등(13.1 vs 13.0), 다파일 리팩터링은 열세(11.4 vs 13.6). TB2.1 13~29%p | 개발 대상 코드(플러그인과 MCP 서버와 파이프라인)는 대부분 C0~C2 → 외부 프런티어 사용 가능. C3 샘플은 마스킹과 합성 데이터로 대체. 로컬은 C3 가 섞인 코드와 스크립트 수정에 한정 | AL-1 Ansys 플러그인 코드, VV-1 합성데이터와 GT 생성 파이프라인 | 2-1 표, kunalganglani |
| **장시간 자율 실행** (수 시간, 목표만 주고 맡김) | **하** | TB4.0(8시간 한도) 격차 26~33%p. 27B급은 5.6% 로 무너짐. 로컬 모델의 장시간 측정 사례 없음 | 로컬로는 열린 과제를 장시간 맡기지 말고, 체크포인트가 있는 고정 그래프(위 "고정 워크플로우")로 바꿔 운영. 열린 과제는 외부 프런티어(C3 제외) | 야간 무인 "개발" 작업. 반면 야간 무인 "해석"은 고정 워크플로우라서 상 | https://www.vals.ai/benchmarks/terminal-bench-4 , AA TB4.0 |

---

## 8. 서버 용량 안의 권장 모델 조합

### 8-1. 서버 1대(8장) 조합안

| 조합 | GPU 배분 | 모델, 정밀도, 라이선스 | 역할 | 근거 | 비고 |
|---|---|---|---|---|---|
| **A (권장 기본)** | GPU 0~3 | **GLM-5.3-Flash** NVFP4 TP4, MIT | lead, 코딩, 다단계 (로컬 최상위) | TB4.0 37.37(Vals), SWE-V 92.0. 단일 281 tok/s, 동시 8건 898 tok/s, KV 560만 토큰 | 활성 세션 약 20(4-2) |
| | GPU 4~6 | **Qwen3.8-27B** FP8 × 3 복제(TP1), Apache 2.0 | 서브에이전트, 문서와 이미지 추출, 분류, 고정 도구 호출 | SWE-V 86.0, TB2.1 58.43(Vals). 이미지와 동영상 입력 지원. 단, **TB4.0 5.6% 이므로 장시간 과제에는 쓰지 않음** | 활성 세션 약 24 |
| | GPU 7 | Qwen3-Embedding-8B + 리랭커 (+ gpt-oss-120b MXFP4 는 여유가 있을 때) | RAG 임베딩과 리랭크, 라우팅 | R0 2-3 | gpt-oss-120b(63GB)와 임베딩(16GB)을 한 장에 같이 올릴 수 있는지는 미확인 |
| **B (보수와 단순)** | GPU 0~5 | Qwen3.8-27B FP8 × 6 복제 | 전 업무 | 운영이 단순하고 장당 세션이 많음 | 다단계와 장시간 품질은 가장 낮음(TB4.0 5.6%) |
| | GPU 6~7 | gpt-oss-120b × 1 + 임베딩 | 분류, 라우팅, RAG | | |
| **C (2대째 서버)** | GPU 0~3 | **DeepSeek-V4.1-Flash** TP4, MIT | 두 번째 대형 모델(교차 검증, A/B, 장애 대비) | TB2.1 74.53(Vals, 로컬 적재 모델 중 최고), 프리필 18K tok/s. TB4.0 은 31.82 로 GLM-5.3-Flash 보다 낮음 | 호스트 RAM 약 189GiB(Engram) 필요 |
| | GPU 4~7 | 조합 A 의 Qwen3.8-27B, 임베딩 복제, 또는 LiDAR 센서 시뮬레이션과 인지모델 학습(RT 코어) | 확장과 야간 배치 | R0 1-3, 3장: RTX PRO 6000 은 Isaac Sim RTX 센서를 쓸 수 있음 | 학습과 같이 쓰면 추론 세션은 절반 |

### 8-2. 비권장과 그 이유

| 모델 | 이유 | 출처 |
|---|---|---|
| GLM-5.3 (753B) 4bit TP8 | TB4.0 에서 Flash 대비 +1.5%p(38.89 vs 37.37)인데 서버 1대 전체를 쓰고, PCIe TP8 이라 동시성이 낮음 | https://www.vals.ai/benchmarks/terminal-bench-4 , 4-1 GLM-5 행 |
| K-EXAONE 2.0 (750B) | 라이선스(Apache 2.0)는 좋음. 그러나 NVFP4 로도 서버 1대 전체, 공급사 발표 기준 TB2.1 43.8 / SWE-V 68.2 로 27B 모델보다 낮음. RTX PRO 6000 실측 없음, 저자 포크 필요. 한국어 지표(KMMLU-Pro 69.1)도 Qwen3.5(77.4)보다 낮음(공급사 표) → **그룹 정책상 필요하면 PoC 로 평가** | https://huggingface.co/LGAI-EXAONE/K-EXAONE-2.0-750B-A37B |
| Kimi K2.x (1T) | INT4 594GB 로 서버 1대 전체, 동시 100건이면 사용자당 9 tok/s | 4-1 |
| MiniMax-M3 | 라이선스 사전승인 필요, TB4.0 1.01% | 5장, Vals TB4.0 |
| EXAONE 4.5 | NC 라이선스 | 5장 |
| Devstral 2 | 매출 기준 라이선스 제한 | 5장 |

---

## 9. 운영안 판단 근거 (1안 vs 2안)

| 판단 항목 | 1안: 바이브 코딩 하네스 + LangGraph/LangChain 투트랙, 외부 API | 2안: 온프렘 로컬 LLM 으로 관리 | 근거 |
|---|---|---|---|
| C3(도면, STP, BOM 원본) 처리 | **불가**(외부 반출 금지) | **가능** | 과제 전제 |
| 가용 시점 | 즉시 | '27.7 서버 가동 이후(그 전에는 브리지) | 과제 전제 |
| 바이브 코딩 효과 | 기준(1.0) | 공수 **1.4배**(1.15~1.8, 추정) | 10장 local_vibe_factor |
| 다단계와 장시간 품질 | TB4.0 65.15 (Opus 5.5) | TB4.0 37.37 (GLM-5.3-Flash) | Vals TB4.0 |
| RAG, 추출, 고정 워크플로우 품질 | 최고 | 격차 0~17%p | 2-3 |
| 과제당 비용 감 (TB4.0) | Opus 5.5 $13.20, Haiku 5.5 $3.12 | 한계비용 0 (서버와 전력은 고정비) | Vals TB4.0 |
| 하네스 호환 | Claude Code, Agent SDK, LangGraph | 같은 vLLM 이 Anthropic Messages API(Claude Code, Agent SDK)와 OpenAI 호환 API(LangChain, LangGraph, OpenHands)를 함께 제공 → **같은 에이전트 코드에서 백엔드만 교체 가능** | vLLM 문서, OpenHands 문서 |
| 리스크 | 외부 서비스 장애와 정책 변경 | 모델 교체 주기 1~3개월(재평가 공수), 도구 호출 파서와 프리픽스 캐시 이슈, NVLink 없는 TP 스케일링 | 6장, 4-1 |

- **근거가 가리키는 방향(계획 반영 제안)**: 둘 중 하나를 고르기보다 **데이터 등급으로 나누는 혼합**이다.
  - 개발(바이브 코딩, C0~C2 코드와 합성/마스킹 데이터)은 1안(외부 프런티어 + Claude Code/Agent SDK)으로 한다.
  - C3 를 만지는 런타임 Agent 는 2안(로컬 vLLM + LangGraph 고정 그래프, 필요하면 같은 하네스를 vLLM 에 연결)으로 한다.
  - 단계별 모델은 7장 적합도를 따른다(상 = 로컬 단독, 중 = 로컬 + 그래프 보강, 하 = C3 를 빼고 외부).

---

## 10. 계획에 넣을 값

| key | 항목 | 단위 | hi (보수) | base (기준) | lo (낙관) | 근거 |
|---|---|---|---|---|---|---|
| `local_quality_gap_pct` | 프런티어(Opus 5.5) 대비 로컬(768GB 적재 모델) 에이전트 과제 성공률 격차 | %p | **30** | **20** | **12** | hi: Vals TB4.0 65.15 vs GLM-5.3-Flash 37.37 = 27.8, tbench 공식 29.1, TB2.1 GLM-5.3-Flash 24.7, Qwen3.8-27B 29.2. lo: TB2.1 DS-V4.1-Flash 13.1, MCP-Atlas 11.6~16.8, SWE-V 5~11. base: '27 업무 구성(RAG, 고정 워크플로우 약 절반, 다단계와 코딩 약 절반)으로 가중한 값(**추정**). 출처: https://www.vals.ai/benchmarks/terminal-bench-4 , https://www.vals.ai/benchmarks/terminal-bench-2-1 , https://www.vals.ai/benchmarks/swebench , https://benchlm.ai/benchmarks/mcpatlas |
| `local_sessions_per_gpu` | RTX PRO 6000 장당 동시 활성 에이전트 세션 (사용자당 25~30 tok/s 이상, 64~128K 컨텍스트) | 세션/장 | **2** | **5** | **10** | hi: 750B~1T급 PCIe TP8(GLM-5 3건에 133 tok/s, Kimi 100건에 사용자당 9 tok/s). base: Qwen3.5-397B NVFP4 4장, 64K 에서 동시 64건 30 tok/s → 장당 16 / 128K 동시 32건 36 tok/s → 장당 8, 여기에 에이전트 보정 0.5 를 곱해 4~8. lo: gpt-oss-120b 1장 50건 31 tok/s, H200 32세션 × 대역폭비 0.375 ≈ 12. 모두 **추정**(커뮤니티 실측 기반). 출처: https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/inference-throughput/README.md , https://github.com/local-inference-lab/rtx6kpro/blob/master/models/glm-5.3-flash.md , https://www.databasemart.com/blog/vllm-gpu-benchmark-pro6000 , https://docs.nvidia.com/dynamo/v1.5.0/recipes/gpt-oss-120b.md |
| `local_vibe_factor` | 로컬 모델로 바이브 코딩할 때 공수 배수 (외부 프런티어 = 1.0) | 배수 | **1.8** | **1.4** | **1.15** | 성공률 비(재시도 횟수는 1/성공률에 비례한다고 가정): TB4.0 65.15 / 37.37 = 1.74, TB2.1 87.64 / 62.92 = 1.39, SWE-V 97.0 / 92.0 = 1.05. 실사용: 단일 파일 13.1 vs 13.0(약 1.0), 다파일 13.6 vs 11.4(1.19). 약한 모델은 숙련자의 개입이 더 필요함(codecentric). base 계산: 단일과 정형 40% × 1.06 + 다파일 40% × 1.3 + 장시간 20% × 1.74 ≈ 1.29 에 개입 공수를 더해 1.4(**추정**). 출처: Vals TB4.0, TB2.1, SWE-V, https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark.md , https://www.codecentric.de/en/knowledge-hub/blog/local-llms-in-a-software-developers-day-to-day-work |

---

## 11. 미확인

1. **Claude Opus 5.5, Sonnet 5.5 의 τ²/τ³-bench, BFCL v4, MCP-Atlas, OpenHands Index 점수.** 이번 비교에서는 Opus 5, 4.8 값으로 대체했다.
2. **BFCL v4 의 2026 하반기 모델 점수.** 공식 리더보드는 2026-04-12 갱신분까지로, GLM-5.3, Qwen3.8, DS-V4.1 이 없다.
3. **K-EXAONE 2.0 의 RTX PRO 6000 실측**(NVFP4 TP8 처리량과 동시성)과 독립 측정 에이전트 점수(Vals, AA 미등재).
4. **EXAONE(4.5 등 NC 라이선스 모델)의 LG 계열사 내부 제공 조건.** 그룹 내 무상과 별도 계약 여부, 제공 창구를 LG AI연구원과 LG경영개발원에 확인해야 한다.
5. **GLM-5.3 라이선스의 "계열 합산 매출" 조항이 사내 전용 사용에 적용되는지**(법무 확인), MiniMax-M3, Kimi K2.x 라이선스 원문.
6. **Claude Code CLI 를 타사와 로컬 모델 백엔드로 쓰는 것의 약관상 지위**, 그리고 완전 폐쇄망(인터넷 차단)에서의 동작 여부(텔레메트리, 인증, 업데이트).
7. **에이전트 실부하(프리필 + 도구 턴)에서 RTX PRO 6000 의 동시 세션 실측.** 이번 값은 디코드 중심 벤치에 보정 계수 0.5(추정)를 곱한 것이다.
8. **NVFP4, 4bit 양자화가 에이전트 과제 성공률에 주는 영향.** GPQA, KLD 로는 차이가 없었으나 TB, SWE 류 측정은 없다.
9. **로컬 모델의 장시간(수 시간) 자율 실행 사례와 METR 시간 지평 값.**
10. **서브에이전트 조율(lead/sub, A2A) 전용 벤치마크에서의 오픈 vs 프런티어 격차.**
11. **한국어 기술문서와 도면(이미지) 이해 품질**(Qwen3.8-27B VLM, K-EXAONE 2.0). 공개 벤치마크로는 판단할 수 없어 사내 평가셋이 필요하다.
12. **DeepSeek-V4.1-Flash 체크포인트의 디스크와 VRAM 크기**와 Engram 테이블을 디스크에 둘 때의 성능 영향.
13. **gpt-oss-120b 와 임베딩 모델을 한 장에 함께 올렸을 때의 메모리와 처리량.**
14. **Opus 5.5 SWE-bench Pro 89.9%**, 집계 사이트가 시스템카드를 인용한 값이며 원문은 확인하지 못했다.

---

## 독립 검증 (2026-10-21)

- 검증 방법: 핵심 주장 12개의 출처를 직접 열어(WebFetch, 2026-10-21) 숫자, 날짜, 측정 조건을 대조했다. 판정은 **확인**(숫자와 조건 일치) / **조건 불일치**(숫자는 맞으나 계획 적용 조건과 다름) / **반박**(원문과 다르거나 일반화가 틀림) / **미확인**(원문에서 확인 불가) 네 가지다.
- 결론: 벤치마크 원값은 대부분 원문과 일치한다. 다만 (1) TB2.1 기반 격차는 측정 주체에 따라 최대 21%p 흔들리고, (2) 처리량 근거 일부는 컨텍스트와 입력 길이 조건이 계획 정의(64~128K)와 다르며, (3) 공수 배수는 숙련자와 소규모 실험을 일반화한 것이다. 그래서 3개 값 중 2개를 보수 쪽으로 고쳤다. **종합 신뢰도: 중**

### V-1. 출처 대조 결과

| # | 주장 (보고서 위치) | 원문 확인 내용 | 판정 | 출처 (확인일 2026-10-21) |
|---|---|---|---|---|
| 1 | Vals TB4.0: Opus 5.5 65.15 / Sonnet 5.5 64.14 / Haiku 5.5 36.36 / GLM-5.3 38.89 / GLM-5.3-Flash 37.37 / DS-V4.1-Flash-1017 31.82 / MiniMax-M3 1.01 (2-1) | 모두 일치. mini-swe-agent, 66과제, avg@3, 과제당 8시간, 갱신 2026-10-19. 그런데 **1017 이전판 "DeepSeek V4.1 Flash"는 19.70**(격차 45.5%p)이고, Opus 5 는 53.53 이어서 Opus 5 → 5.5 사이에 +11.6%p 차이가 남 | 확인 | https://www.vals.ai/benchmarks/terminal-bench-4 |
| 2 | Vals TB2.1: Opus 5.5 87.64 / DS-V4.1-Flash 74.53 / GLM-5.3 71.54 / GLM-5.3-Flash 62.92 / Qwen3.8-27B 58.43 (2-1) | 숫자 일치(Terminus 2, 갱신 2026-09-28, 보관 처리). 다만 74.53 은 **1017 이전판** 값이다. 보고서는 TB2.1 에서는 이전판, TB4.0 에서는 1017판을 써서 판이 섞였다 | 조건 불일치 | https://www.vals.ai/benchmarks/terminal-bench-2-1 |
| 3 | "공급사 발표 TB2.1 이 독립 측정보다 12~21%p 높다" (1장, 요약) | AA 독립 측정(같은 Terminus 2 하네스)에서 GLM-5.3-Flash 는 **84.3 으로 공급사 값(84.3)과 같고**, Qwen3.8-27B 는 **79.8 로 공급사 값(73.0)보다 높다**. 차이를 만든 쪽은 Vals 측정이며, 공급사 부풀림으로 일반화할 수 없다. 같은 하네스를 써도 측정 주체(서빙 공급자와 설정)에 따라 오픈 모델 점수가 최대 21%p 다르다 | **반박** | https://benchlm.ai/models/glm-5-3-flash , https://benchlm.ai/models/qwen3.8-27b (2026-10-20 갱신), https://artificialanalysis.ai/evaluations/terminalbench-v2-1 (방법론: Terminus 2, e2b, 3회) |
| 4 | tbench 공식 TB4.0: Opus 5.5 64.85 vs GLM-5.3-Flash 35.76 = 29.1%p (hi 근거) | 숫자는 맞지만 GLM-5.3-Flash 는 **reasoning "none"** 설정이고 Opus 5.5 는 max 다. 조건을 맞춘 비교(GLM-5.3 max 41.82)로는 23.0%p | 조건 불일치 | https://www.benchlm.ai/benchmarks/terminal-bench-4 (2026-10-19 스냅샷) |
| 5 | AA TB4.0: Opus 5.5 59.6 / GLM-5.3-Flash 32.8 / Qwen3.8-27B 5.6 (2-1, 요약 "27B 무너짐") | Opus 5.5 59.6 은 AA 페이지에서 확인했다. GLM 32.8, Qwen 5.6 은 BenchLM 미러로만 확인했다(AA 페이지 본문에는 표시되지 않음). Qwen3.8-27B 는 같은 AA 의 TB2.1 에서 79.8 인데 TB4.0 이 5.6 이라, 평가 실패(타임아웃과 컨텍스트 초과 등) 이상치일 가능성이 있다 | Qwen 5.6 은 **단일 출처와 하** | https://artificialanalysis.ai/evaluations/terminalbench-v4-0 , https://benchlm.ai/models/qwen3.8-27b |
| 6 | Vals SWE-V: Opus 5 97.0, GLM-5.3-Flash 92.0, Qwen3.8-27B 86.0, gpt-oss-120b 33.6 (2-1) | 숫자 일치(갱신 2026-09-01, 포화로 보관). 비교 상대가 **Opus 5.5 가 아닌 Opus 5** 이고, 점수가 상한에 몰려 있어 격차가 압축되어 보인다 | 조건 불일치(격차 과소) | https://www.vals.ai/benchmarks/swebench |
| 7 | MCP-Atlas: Opus 5 85.8 / MiniMax M3 74.2 / DS-V4-Flash-0731 69.0 / Qwen3.6-35B-A3B 62.8 (lo 근거 11.6) | 숫자 일치(2026-10-20). 그러나 값마다 공급사 발표인지 독립 측정인지 **표기가 없다**. Opus 5.5, GLM-5.3-Flash, Qwen3.8-27B, DS-V4.1 은 미등재. lo 근거 11.6 은 라이선스 문제로 제외된 MiniMax M3 의 값이다 | 조건 불일치 | https://benchlm.ai/benchmarks/mcpatlas |
| 8 | BFCL v4 다중턴 격차 0.4%p (요약과 7장 "0~5%p") | Opus 4.5 77.47 / 68.38 / 73.76, GLM-4.6 72.38 / 68.00 / 55.70 으로 일치. 그러나 다중턴만 골라 쓴 값이다. **종합 5.1%p, 메모리 18.1%p** 이고, 구세대 모델 비교이며 2026 하반기 모델은 없다 | 조건 불일치(선택적 인용) | https://gorilla.cs.berkeley.edu/data_overall.csv |
| 9 | GLM-5.3-Flash NVFP4 4장: 단일 281.3 / C8 897.6 tok/s, 프리필 13,816 (4-1) | 숫자 일치. 조건은 **디코드 컨텍스트 0**, MTP3 투기적 디코딩, **Max-Q 카드**, C1, C8 만 측정. 별도 5회 재측정한 C1 값은 265.7~277.0 이다. 64~128K 에이전트 컨텍스트를 대표하지 않는다 | 조건 불일치 | https://github.com/local-inference-lab/rtx6kpro/blob/master/models/glm-5.3-flash.md (2026-09-22 빌드) |
| 10 | Qwen3.5-397B NVFP4 4장 64K: C64 1,912 → 사용자당 30 / 128K: C32 1,164 → 36 (4-2 base 근거) | 합계 값은 일치(nvidia 체크포인트, MTP2, vLLM 0.17.0rc1, **Server Edition**, 2026-03-14). 사용자당 값은 원문이 아니라 합계 ÷ 동시 수로 계산한 것이다. 출력은 요청당 512 로 제한했고, 디코드만 측정했다 | 확인(조건 주의) | https://github.com/local-inference-lab/rtx6kpro/blob/master/benchmarks/inference-throughput/README.md |
| 11 | gpt-oss-120b 1장 50건: 합계 출력 1,778.77, 사용자당 31 (4-1, lo 근거) | 1,778.77 은 입력을 포함한 **total** 처리량이고 출력은 1,524.66 이다. TPOT 32.24ms 로 사용자당 31 은 맞다. 다만 **입력 100 / 출력 600 토큰**의 짧은 컨텍스트라 64~128K 정의에 맞지 않는다 | 조건 불일치 | https://www.databasemart.com/blog/vllm-gpu-benchmark-pro6000 (갱신 2026-10-07) |
| 12 | Dynamo H200 에이전트 트레이스: 장당 32세션과 사용자당 47.5 → × 0.375 ≈ 12 (lo 근거) | 8× H200, 동시 256, GPU 당 1,256 tok/s, 사용자당 47.5 로 일치. EAGLE3, KV 인지 라우팅, CPU KV 오프로드를 썼다. 원문 안에 "15% trace"와 "90% KV hit" 표기가 **서로 다르다**. 대역폭 비율만 적용하고 메모리 차이(141GB 대 96GB)는 반영하지 않아 상한값이다 | 조건 불일치(상한) | https://docs.nvidia.com/dynamo/v1.5.0/recipes/gpt-oss-120b.md |
| 13 | vLLM 이 Anthropic Messages API 를 제공 → "같은 에이전트 코드에서 백엔드만 교체" (6, 9장) | Messages API 구현, `ANTHROPIC_BASE_URL`, 등급별 모델 매핑, 프리픽스 캐시 해시 문제(0.17.1 초과판에서 해결)는 확인했다(2026-03-12). 그러나 모델별 `--tool-call-parser`, `--served-model-name` 설정이 필요하고, 문서는 "모델이 도구 호출을 잘 지원해야 한다"고 한다. 폐쇄망 동작 절차는 없다. 연결은 되지만 **동작이 같다는 보장은 없다** | 부분 반박(과장) | https://docs.vllm.ai/en/stable/serving/integrations/claude_code/ |
| 14 | 실사용 근거: kunalganglani 다파일 11.4 vs 13.6, codecentric "Qwen 27B 2.5시간 실패" (6장, vibe 근거) | kunalganglani: 16GB GPU 의 Qwen3-Coder Q4 와 Sonnet 5 를 비교했다. 범주당 10과제이고 분산을 보고하지 않았으며 채점자도 밝히지 않았다. codecentric: 실패 원인은 **M3 Max 노트북의 속도**(초기화 30분과 계획 1시간 이상, 타임아웃)라 서버 환경에 그대로 옮길 수 없다. "개발자 숙련도가 더 필요하다"는 문장은 클라우드 MiniMax-m2.5 에 대한 것이다 | 조건 불일치 | https://www.kunalganglani.com/blog/local-llm-vs-claude-coding-benchmark.md (갱신 2026-07-12), https://www.codecentric.de/en/knowledge-hub/blog/local-llms-in-a-software-developers-day-to-day-work (2026-08-13) |
| 15 | Opus 5.5 발표 TB4.0 66.4, 무인 18시간과 68만 줄 (1, 6장) | 66.4(±2.6, xhigh), 출시 2026-09-22 로 일치. 18시간과 68만 줄은 고객과 익명 테스터 사례다(보고서 표기와 같음) | 확인 | https://www.anthropic.com/news/claude-opus-5-5 |

### V-2. 이중 계산과 적용 범위 점검

| 점검 항목 | 문제 | 계획 반영 규칙 | 근거 |
|---|---|---|---|
| `local_quality_gap_pct` 와 `local_vibe_factor` 가 같은 TB4.0, TB2.1 자료에서 나옴 | 같은 작업에 두 값을 함께 적용하면 이중 계산이 된다 | 격차(%p)는 **런타임 Agent**(C3 처리 자동화율과 사람 검토 부담)에만, 공수 배수는 **개발 공수**에만 적용 | V-1 #1, #2 |
| 바이브 코딩 효과와 외부 MCP 재사용 절감과 겹침 | 1.4배를 바이브 코딩 이전 기준 공수에 곱하면, 다른 보고서에서 잡은 바이브 코딩과 MCP 절감과 순서가 꼬인다 | 공수 = (기준 공수 − MCP 재사용분) × (1 − 바이브 코딩 절감률) × 로컬 배수. 외부 MCP 를 그대로 쓰는 부분은 코딩이 없으므로 배수를 적용하지 않음 | 추정 |
| 혼합 운영(9장 권장)에서의 적용 범위 | 개발(C0~C2)을 외부 프런티어로 하면 로컬 배수는 C3 가 섞인 코드에만 해당한다 | 1안과 혼합 운영: 로컬 개발 비중 × 배수 + 나머지 × 1.0 / 2안(로컬 단독): 전체에 배수 적용 | 9장 |
| 숙련자 실험을 신규 인력에 적용 | 근거 실험은 숙련 개발자(codecentric)나 개인 블로거가 한 것이다. '27 개발 인력은 경력 채용과 사내 전환자이고 HW 엔지니어도 섞여 있어, 약한 모델을 보정하는 능력이 낮을 수 있다 | 공수 배수를 보수 쪽으로 올림(V-3) | V-1 #14 |
| 지연 시간 | TB2.1 소요시간이 로컬 모델은 Opus 5.5 의 2.3~2.5배다(API 서빙 기준). 부하가 걸린 로컬 서버의 사용자당 속도는 25~30 tok/s 다. 바이브 코딩에서는 사람이 기다리는 시간이 공수가 되는데, 원 계산에는 빠져 있다 | 배수 base 에 +0.1~0.2 반영 | V-1 #2, 4-2 |

### V-3. 수정값

| key | 원래 (hi / base / lo) | 수정 (hi / base / lo) | 수정 이유 | 신뢰도 |
|---|---|---|---|---|
| `local_quality_gap_pct` (%p) | 30 / 20 / 12 | **33 / 22 / 12** | hi: 2대째 권장 모델인 DS-V4.1-Flash-1017 의 TB4.0 격차가 33.3 이고, NVFP4 양자화가 에이전트 과제에 주는 영향은 미확인이다. tbench 29.1 은 조건이 맞지 않으므로(#4) 근거에서 뺀다. 같은 조건의 TB4.0 격차는 26.8(AA)~27.8(Vals)로 측정 주체가 달라도 안정적이다. base: 작은 격차 쪽 근거(SWE-V, MCP-Atlas, BFCL)가 Opus 5 / 4.5 와 비교한 값이고(Opus 5 → 5.5 는 TB4.0 에서 +11.6), BFCL 은 선택적으로 인용됐다(#8). 그래서 18.5(재계산: RAG, 고정 절반 약 11 + 다단계 절반 약 26)에 +3 을 더해 22 로 한다(추정). lo: 유지. TB2.1 은 측정 주체에 따라 ±20%p 흔들려(#3) 신뢰도가 하이고, MiniMax 값(11.6)은 제외해도 DS 0731 의 16.8, SWE-V 의 5 사이에 있다 | 중 (TB4.0 은 상, 나머지는 하~중) |
| `local_sessions_per_gpu` (세션/장) | 2 / 5 / 10 | **2 / 4 / 8** | base: 보고서 자체의 프리필 가정(세션마다 15초에 5K 토큰)을 적용하면 64K, 장당 16(4장 64세션)은 프리필 수요가 21.3K tok/s 로 4장의 용량 13.8K 를 넘어 성립하지 않는다. 프리필 예산을 50% 로 잡으면 GLM-5.3-Flash 4장에 약 21세션(장당 약 5)이고, 128K 에서는 프리필이 더 느려 장당 3~4 다. Qwen3.8-27B 1장은 6 안팎(실측 없음)으로 본다. 조합 A 추론 7장 평균은 (4×3.5 + 3×6)/7 ≈ 4.6 이므로 4 로 내린다. lo: gpt-oss 근거는 짧은 컨텍스트(#11), Dynamo 근거는 상한값이다(#12). 소형 모델만 장당 10~12 가 가능하고, 함대 평균은 (4×6 + 3×10)/7 ≈ 7.7 이므로 8 로 한다. hi: 유지. 모두 **추정**이다. 서버 1대(조합 A)의 활성 세션은 4-2 의 40~45 가 아니라 **약 30~35** 로 고친다 | 하~중 (에이전트 실부하 실측 없음) |
| `local_vibe_factor` (배수) | 1.8 / 1.4 / 1.15 | **2.0 / 1.5 / 1.15** | hi: DS-V4.1-Flash-1017 의 TB4.0 성공률 비가 65.15 / 31.82 = 2.05 이고, 지연 시간(2.3~2.5배)은 반영되지 않았다. base: SWE-V, TB2.1 은 상한에 몰려 격차가 압축되어 보이므로, 단일과 정형 40% × 1.1 + 다파일 40% × 1.4 + 장시간 20% × 1.74 = 1.35 로 다시 계산하고, 비숙련 인력의 개입과 대기 시간 +0.15 를 더해 1.5 로 한다(추정). lo: 유지(단일 파일은 거의 동등, 1회 측정). 적용 범위는 V-2 규칙을 따른다 | 하~중 (성공률 비 → 공수 비 변환은 검증되지 않은 가정) |

### V-4. 요약 문장 수정 제안

| 원래 문장 | 수정 문장 | 근거 |
|---|---|---|
| "공급사 발표 TB2.1 점수는 독립 측정보다 12~21%p 높다" | "TB2.1 오픈 모델 점수는 측정 주체에 따라 최대 21%p 다르다(Vals 가 낮고, AA 는 공급사 발표와 같거나 높다). 격차 계산은 측정 주체 간 차이가 작은 TB4.0 을 우선한다" | V-1 #3 |
| "Qwen3.8-27B 는 AA TB4.0 5.6% 로 무너진다" | "Qwen3.8-27B 는 AA TB4.0 5.6%(BenchLM 미러, 단일 출처)로, 같은 AA 의 TB2.1 79.8% 와 맞지 않아 이상치일 수 있다. 장시간 과제에 쓰지 않는다는 운영 원칙은 유지하되, 사내 PoC 로 확인한다" | V-1 #5 |
| "독립 측정 기준 SWE-bench Verified 5~11%p" | "Opus 5(5.5 아님)와 비교한 포화 벤치마크 기준 5~11%p 로, 실제 격차보다 작게 보일 수 있다" | V-1 #6 |
| "BFCL v4 다중턴 0.4%p" | "BFCL v4(구세대 비교): 종합 5.1%p, 다중턴 0.4%p, 메모리 18.1%p" | V-1 #8 |
| "GLM-5.3-Flash 단일 281 tok/s, 동시 8건 898 tok/s" | "컨텍스트 0, MTP3, Max-Q 조건에서 단일 266~281, 동시 8건 898 tok/s. 64~128K 실부하 값은 미확인" | V-1 #9 |
| "같은 에이전트 코드에서 백엔드만 바꿀 수 있다" | "같은 에이전트 코드를 vLLM 에 연결할 수 있으나, 모델별 도구 호출 파서 설정이 필요하고 동작과 품질이 같다는 보장은 없다(사내 회귀 테스트 필요)" | V-1 #13 |
| 4-2 "서버 1대 활성 세션 약 40~45개" | "약 30~35개(추정), 2대 60~70개" | V-3 |

### V-5. 남은 미확인 (검증 과정에서 추가)

1. DS-V4.1-Flash-1017 의 Vals TB2.1 값과 RTX PRO 6000 처리량(현재 프로필은 1017 이전 2026-09-22 빌드).
2. AA TB4.0 페이지 원문에서 GLM-5.3-Flash 32.8, Qwen3.8-27B 5.6 확인(이번에는 미러로만 확인).
3. Opus 5.5 의 AA TB2.1 값(AA 기준으로 같은 조건의 TB2.1 격차를 계산할 수 없었음).
4. 사내 서버가 Server Edition(600W)인지 Max-Q(300W)인지. 프리필 용량이 달라져 세션 수 추정이 바뀐다.
