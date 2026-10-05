# LM27 Copilot 브리지 명세 (COPILOT_BRIDGE.md)

| 항목 | 값 |
|---|---|
| 판 | v1.1 (2026-10-05) — 설계 확정본, 구현 전. v1 은 제품명을 LM26 으로 잘못 붙여 작성됐다. 이 판은 제품명을 **LoadMonitor27(LM27)** 로 바로잡고(트리 `D:\배포\loadmon27\`, 패키지 `lm27`, PC 자리 `%LOCALAPPDATA%\LoadMonitor27\`), 결정 메모 §10.1(Copilot 계정 등급·업무 탭·웹 근거)과 형제 명세 대조 결과를 보탰다(§0.1) |
| 이름 충돌 | `D:\배포\LM26` 은 다른 AI 도구가 만든 별개 프로젝트다(읽기만). 이 명세의 경로·포트·작업 이름·프롬프트 머리표는 그쪽(127.0.0.1:8765~8767)과도, LM24 Copilot 디버그 포트(9333)와도 겹치지 않는다(LM27 기본 9343~9352) |
| 대상 코드 | `lm27/bridge/**`, `tools/bridge.py`, `tests/bridge/**` |
| 상위 결정 | 오케스트레이터 결정 메모 §1(운영 원칙)·§2(데이터 접근)·§5(시간 원칙)·§6(코파일럿)·§7(정제)·§9(품질)·§10.1(코파일럿 탐침: 계정 등급·Work 탭·웹 근거 토글) |
| 근거 | 이전 판 조사 `copilot.md`, LM24 `tools/copilot_auto.py`(1,507줄, L0/L1 이식 대상), `teams.md`·`privacy.md`·`hierarchy-reports.md`·`lessons.md`·`critic.md`·`other-lm26.md`(별개 프로젝트 조사) |
| 관련 명세 | 같은 `docs\` 의 `PRIVACY.md`(게이트 G3 §13, 열 허용 목록 §10), `COLLECTION.md`(경로 ID·사유 코드 R-*·탐침 P-CP·커버리지 원장), `COLLECT_MAIL.md`(§11.4 `mail.copilot` 어댑터), `TEAM_AND_BUNDLE.md`(번들 배치 §1.1, PC 능력 기록 §1.5, 팀 묶음의 `quality.copilot`). 형제 명세는 LM27 판으로 옮겨지는 중이다 — `PRIVACY.md` v1.1 은 이미 `D:\배포\loadmon27\docs\` 에 있고 이 판은 `PRIVACY.md` §0.2 정합 결정 H1·H4 를 반영했다, 나머지는 아직 LM26 가칭 초안으로 `D:\배포\loadmon26\docs\` 에 있다. 이 문서는 **파일 이름·절 번호로만** 참조하고, 모듈·경로 이름은 LM27 기준으로 쓴다(§16 Q24). 시간·계층·과정 마이닝 명세와 맞출 지점은 §16 에 적었다 |
| 검증 시제품 | 이 문서의 L2 분류표와 L1 완료 판정 규칙은 브라우저 없는 시제품(가상 시계·가짜 페이지)으로 돌려 확인했다(§11.6) |
| 런타임 | 동봉 CPython 3.11 embeddable, **표준 라이브러리만**. Windows PowerShell 5.1 은 클립보드·프로세스 조회 보조에만 쓴다 |

---

## 0. 읽는 법과 용어

이 문서는 구현자가 그대로 코드로 옮길 수 있게 썼다. 자료구조는 파이썬 `dataclass` 표기, 절차는 의사코드, 수치는 모두 기본값과 범위를 같이 적는다. 수치 상수는 §3 설정 키에만 있고 코드에는 없다(관문 G-B2).

| 용어 | 뜻 |
|---|---|
| 전송(send) | Copilot 입력창에 프롬프트를 1회 넣어 보내고 답 1개를 회수하는 것. **L1** 의 단위 |
| 질의(ask) | 한 묶음에 대한 논리 요청 1건. 재시도 사다리를 포함해 최대 3회 전송. **L2** 의 단위 |
| 묶음(batch) | 한 질의에 실은 항목들. **L3** 이 만든다 |
| 항목(item) | 단계가 판정하는 최소 단위. 메시지 1건, 단위업무 후보 1건, 조회 구간 1개 등 |
| 단계(stage) | **L4** 정의 하나. 예: `task_label` |
| rid | 전송마다 새로 만드는 요청 번호. `R` + 5자(§6.1) |
| 서약(pledge) | 답의 맨 마지막 줄 `[[END <rid>]]` |
| 봉투(envelope) | 답 JSON `{"rid", "n", "items":[{"id", …}]}` |
| 사다리 단(rung) | 0 = 기본, 1 = 새 채팅 + 대기 절반, 2 = 새 채팅 + 대체 모델 |
| 커밋 | 검증을 통과한 항목 답을 저장소에 원자적으로 덧붙이는 것 |
| 규칙 폴백 | AI 답이 없을 때 쓰는 결정적 규칙 답. 출처를 `rule` 로 표시 |
| 내용 키(ck) | 항목의 '같은 질문인가'를 가리는 해시. 재개·재사용의 기준(§7.9) |
| 게이트 | 전송 직전 개인정보 재검사(§9) |
| 웹 노출(`web_exposed`) | 업무(Work) 모드이고 웹 근거가 꺼진 것까지 **둘 다 확인된 경우가 아니면** 참. 참이면 엄격 규칙(§9.7) |
| 계정 등급(`tier`) | `premium`(조회가 실제로 된 적 있음) / `basic`(업무 데이터 라이선스 없음 문구를 받음) / `unknown` (§4.11) |

### 0.1 v1.1 에서 바뀐 점

| 절 | 바뀐 점 | 이유 |
|---|---|---|
| 전체 | 제품명·트리·패키지·PC 자리·JS 표식·프롬프트 머리표를 LM27 로 | 사용자 지시(LM27). `D:\배포\LM26` 별개 프로젝트와의 이름 충돌 제거(조사 critic: 'LM26 이라는 이름은 다른 도구의 판과 겹친다') |
| §4.11 | `CopilotEnv`(계정 등급 Basic/Premium·업무 탭·업무 모드·웹 근거 토글·웹 노출 여부) 판별 | 결정 메모 §10.1 |
| §9.7 | 웹 노출 환경 엄격 규칙: 고객사·협력사 번호 제거, 금액+고객사 동시 항목 제외, 상대 도메인 미전송, 사람 키 평문화 | 결정 메모 §10.1 '웹 근거가 켜져 있으면 전송 직전 재검사 강화' |
| §6.2 | 분석 단계 프롬프트에 '웹 검색 없이' 규칙 1줄 | 웹 근거 모드에서 프롬프트 글이 검색어로 나가는 것을 줄인다(막는 장치는 §9.7) |
| §7.13, §8.1 | R-NOLIC 은 계정 단위 — 세 조회 능력에 같은 날짜로 함께 기록. 업무 모드가 아니면 조회 생략 | 결정 메모 §10.1 'Basic 이면 메일·팀즈 증인 경로 끔' |
| §8.1 | 조회 행 시각 `t` 를 날짜만으로, 증거 행은 `kind` = `mail`·`teams`·`cal` + `src=*.copilot` + `ts_precision="summary"` 고정, 어댑터 종료 코드·커버리지 셀 대응표, 설정 키 일원화 | 결정 메모 §5(코파일럿 요약은 시간 근거 아님), LM27 `PRIVACY.md` §0.2 H1(`copilot_ev` kind 폐기), `COLLECT_MAIL.md` §4.3 rc |
| §4.5 | Edge 프로필·디버그 포트는 역할(브리지·OWA·Teams 웹) 공용 한 벌(`bridge.edge.*`) | 같은 프로필을 두 포트로 띄우면 두 번째 기동이 첫 인스턴스로 넘어가 포트가 열리지 않는다 — 형제 명세의 별도 프로필·포트 키를 흡수(§16 Q23) |
| §7.16 | 재개 필터를 항목 게이트 **앞**으로, 조회 능력이 `suspect` 인 날은 같은 날 다시 보내지 않음 | v1 의사코드는 게이트가 재개보다 먼저여서 이미 AI 답이 있는 항목이 나중 호출의 게이트·엄격 규칙에 걸리면 규칙 답으로 덮였다(§9.2 문장 '재개로 건너뛴 항목은 제외'와도 어긋남) |
| §11.5, §11.6, §15 | 시험 T49~T55, 시제품 확인 표, 관문 G-B11·G-B12 | 보강분 검증 |

---

## 1. 원칙과 불변식

| 번호 | 원칙 | 강제 수단 |
|---|---|---|
| B1 | Copilot 은 **분류·명명·요약·연관성 서술**만 한다. 시간·MM·근무 구간·합계는 로컬 결정론 코드가 계산하며 프롬프트에 보내지도 않는다 | L4 `send_fields` 허용 목록, 응답의 시간형 필드 거부(§6.5), 관문 G-B8 |
| B2 | Copilot 에는 **개인정보 게이트를 통과한 항목만** 간다. 게이트는 정제기와 같은 규칙으로 항목 단위·프롬프트 전체를 두 번 본다 | §9, PII 카나리아 관문 G-B6 |
| B3 | Copilot 은 **클라우드 PC 한 곳**에서만 쓴다. PC1·PC2 는 로그인도, 브리지 실행도 하지 않는다. Edge 프로필은 `%LOCALAPPDATA%` 에 두고 운반 번들에 넣지 않는다 | §2.4 경로, §4.3 |
| B4 | **로그인은 사람이 한다.** 브리지는 비밀번호·토큰·쿠키를 읽거나 쓰지 않고, 로그인 화면에 아무것도 입력하지 않는다 | §4.7 |
| B5 | 완료 판정은 **fail-closed**. '못 찾으면 진행'으로 설계된 판정기(중지 버튼 탐지)를 '완료' 쪽 결정에 단독으로 쓰지 않는다 | §5.6, 시험 T02·T04·T28 |
| B6 | 한 번의 실패를 영구 실패로 단정하지 않는다. 치명 실패는 **조건 폴링 → 2-strike** 뒤에만 단계를 멈추고, 멈춰도 `resumable=true` | §7.7 |
| B7 | **항목 단위 저널 커밋.** 프로세스가 어느 순간에 죽어도 잃는 것은 진행 중이던 질의 1건뿐 | §7.8 |
| B8 | 성공 전에 기존 산출물을 무효화하지 않는다. 빈 값으로 기존 값을 덮지 않는다 | §7.10 접기 규칙 |
| B9 | 프롬프트·답 **원문을 디스크에 남기지 않는다.** 예외는 수동 경로의 프롬프트 파일(게이트 통과본, TTL)과 사용자가 켠 원문 캡처(게이트 통과본, TTL 7일)뿐 | §9.5, 관문 G-B7 |
| B10 | 한도·예산·재시도 공식은 **한 벌**. 단계 코드는 L3 가 준 값만 읽는다 | §3, 관문 G-B2 |
| B11 | 조용히 버리지 않는다. 상한·게이트·검증으로 버린 건수는 결과 봉투 `caps_hit`·`dropped` 에 남긴다 | §7.11 |
| B12 | 다른 사용자에게 수동 조작을 요구하지 않는다. 실패는 스스로 복구하고, 남은 항목은 **다음 실행이 자동으로 이어** 한다. 사람 몫은 '최초 로그인'과 '정책상 자동화가 막힌 PC의 붙여넣기'뿐 | §7.7, §10, §13 |
| B13 | 브리지는 **자기가 만든 탭만** 만지고, 정확한 호스트와 Copilot 고유 요소로 신원을 확인한 뒤에만 입력한다. 다른 탭은 닫지도 읽지도 않는다 | §4.6 |
| B14 | 사람 이름·계정·메일 주소·사내 코드네임은 프롬프트에 넣지 않는다. 과제는 레지스트리 ID(`P012` 등)와 팀이 쓴 중립 설명으로만 가리킨다 | §8.0, §9.3 |
| B15 | Copilot 의 **웹 노출을 기본으로 가정**한다. 업무 모드와 웹 근거 꺼짐이 둘 다 확인되기 전에는 엄격 규칙을 거쳐 보내고, 설정으로 웹 노출 환경의 전송을 아예 막을 수 있다. 브리지는 웹 근거 토글을 **읽기만** 하고 바꾸지 않는다 | §4.11, §9.7, 시험 T49~T53 |

---

## 2. 구조

### 2.1 계층도

```
                ┌─────────────────────────────────────────────────────────┐
 L4 단계 정의   │ lookup_mail · lookup_teams · lookup_calendar · speech_act │  프롬프트 머리말·항목 줄·
 (stages/*.py)  │ task_label · workflow_label · review_text ·               │  응답 스키마·검증·폴백·접기
                │ agentic_match · subagent_review                           │
                └───────────────▲─────────────────────────────────────────┘
                                │ StageSpec
                ┌───────────────┴─────────────────────────────────────────┐
 L3 배치 실행기 │ 패킹 · 반분 · 누락 재질의 · 서킷브레이커 · 예산 · 저널  │  runner.py · journal.py ·
                │ 커밋 · 재개 · 결과 봉투(stage_result) · 보정값 적용       │  budget.py · calibrate.py
                └───────────────▲─────────────────────────────────────────┘
                                │ ask(batch) → AskResult      ▲ gate.gate_items  
                ┌───────────────┴──────────────────────────┐  │
 L2 교환        │ rid 봉투 조립 · 프롬프트 게이트 ·          │  │ gate.gate_prompt / clean_answer
                │ 봉투 추출·잘림 복구 · 스키마 검증 ·        │──┘ (lm27.privacy 어댑터, gate.py)
                │ 상태 분류 10종 · 재시도 사다리             │  exchange.py · jsonx.py
                └───────────────▲──────────────────────────┘
                                │ roundtrip(SendRequest) → SendResult
                ┌───────────────┴──────────────────────────┐
 L1 전송        │ 주입 검증 · 전송 확인·재전송 · 회수(DOM    │  transport.py (CdpTransport)
                │ 1차/앵커 폴백) · fail-closed 완료 판정     │  transport_stub.py · manual.py
                └───────────────▲──────────────────────────┘
                                │ EdgeSession
                ┌───────────────┴──────────────────────────┐
 L0 세션        │ Edge 탐색·정책 확인·기동 · 포트·소유 확인  │  session.py · cdp.py · js.py
                │ 프로필 잠금 · 탭 소유·신원 · 로그인 감지   │  (웹 수집기와 공용)
                │ 계정 등급·업무 모드·웹 근거 판별           │  env.py
                └──────────────────────────────────────────┘
```

### 2.2 모듈 배치

모든 경로는 `D:\배포\loadmon27\` 기준. 패키지 `lm27` 은 진입점이 루트를 `sys.path` 에 넣은 뒤에만 임포트된다(내장 파이썬 `python311._pth` 때문).

| 파일 | 층 | 책임 |
|---|---|---|
| `tools/bridge.py` | 진입 | `ROOT` 를 `sys.path[0]` 에 넣고 `lm27.bridge.cli.main()` 호출. 그 밖의 코드 없음 |
| `lm27/bridge/__init__.py` | — | 공개 API 재수출: `run_stages`, `probe`, `calibrate`, `diagnose`, `manual_export`, `manual_import` |
| `lm27/bridge/clock.py` | 공용 | `Clock` 프로토콜, `RealClock`, `VirtualClock`, `Deadline`. **브리지에서 `time` 모듈을 부르는 유일한 파일** |
| `lm27/bridge/settings.py` | 공용 | 설정 레지스트리에서 `bridge.*` 를 읽어 `BridgeSettings` 로 검증·고정 |
| `lm27/bridge/cdp.py` | L0/L1 | 표준 라이브러리 WebSocket(RFC 6455)·CDP 호출·`/json` HTTP. LM24 이식 |
| `lm27/bridge/js.py` | L0/L1 | 페이지에서 평가할 JS 조각. 각 조각 머리에 `/*LM27:<이름>*/` 표식(가짜 CDP 가 이것으로 분기) |
| `lm27/bridge/session.py` | L0 | `EdgeSession`: Edge 탐색·정책·기동·포트·소유 확인·프로필 잠금·탭 소유·신원·로그인 대기·모델·업무 모드 |
| `lm27/bridge/env.py` | L0 | `CopilotEnv` 판별(계정 등급·업무 탭·업무 모드·웹 근거·웹 노출, §4.11)과 `bridge_profile.env` 기록 |
| `lm27/bridge/transport.py` | L1 | `Transport` 프로토콜, `SendRequest`, `SendResult`, `CdpTransport.roundtrip()` |
| `lm27/bridge/transport_stub.py` | L1 | `StubTransport`(환경 변수 `LM_COPILOT_STUB`), 시험용 |
| `lm27/bridge/jsonx.py` | L2 | 답 정규화, 봉투 후보 추출, 잘린 JSON 복구 |
| `lm27/bridge/exchange.py` | L2 | 프롬프트 조립, rid, 게이트 호출, 상태 분류, 재시도 사다리, `ask()` |
| `lm27/bridge/gate.py` | L2/L3 | 정제 명세(`PRIVACY.md`) `lm27.privacy` 의 G3 게이트·입수 정제 어댑터(§9)와 웹 노출 엄격 규칙(§9.7). `lm27.privacy` 를 임포트하는 유일한 브리지 파일 |
| `lm27/bridge/runner.py` | L3 | `run_stage()`: 패킹·반분·재질의·서킷·예산·커밋·재개·결과 봉투 |
| `lm27/bridge/budget.py` | L3 | 실행·단계 마감 계산 한 벌 |
| `lm27/bridge/journal.py` | L3 | 저널·항목 저장소 쓰기/읽기/접기, 원자적 덧붙이기 |
| `lm27/bridge/calibrate.py` | L3 | 입출력 한도 보정 프로브, 실행 중 적응 |
| `lm27/bridge/capability.py` | L3 | 조회 능력 기록(서로 다른 날 2회 확정·TTL·해제) |
| `lm27/bridge/manual.py` | L1 대체 | 수동 붙여넣기: 프롬프트 파일 내보내기, 답 반입, `ManualTransport` |
| `lm27/bridge/messages.py` | 공용 | 사용자 문구 표 `BR-*`(§13) |
| `lm27/bridge/trace.py` | 공용 | 전송 계측(길이·시간만) |
| `lm27/bridge/fsio.py` | 공용 | 파일 쓰기 세 함수(`append_line`·`write_atomic`·`write_text_ttl`). **브리지에서 쓰기 모드 `open` 을 부르는 유일한 파일**(관문 G-B7) |
| `lm27/bridge/cli.py` | 진입 | `run`·`probe`·`calibrate`·`diagnose`·`manual-export`·`manual-import`·`replay`·`unlock` |
| `lm27/bridge/stages/base.py` | L4 | `StageSpec` 기반 클래스, 필드 검사기, 공통 문구 |
| `lm27/bridge/stages/*.py` | L4 | 단계 9종(§8). `stages/__init__.py` 의 `REGISTRY` 에 등록 |
| `tools/bridge_trace_summary.py` | 진단 | 계측 요약(단계별 전송 수 × 재시도, §11.7) |
| `tests/bridge/` | 시험 | `fake_cdp.py`·`fake_http.py`·`stub_responder.py`·`test_*.py`·`fixtures/` (§11) |

### 2.3 프로세스 모델

- 브리지는 **호출 1회 = 프로세스 1개**다. 파이프라인(분석 실행기 또는 UI)이 `python\python.exe tools\bridge.py run --run-id <id> --stages <a,b,…>` 로 띄운다. 한 프로세스가 L0 세션을 잡고, 지정된 단계를 차례로 **같은 프로세스 안에서** L3 로 실행한 뒤 세션을 놓는다.
  - LM24 는 왕복마다 드라이버 자식 프로세스를 새로 띄웠다(매번 재연결·탭 탐색·모델 메뉴 확인). LM27 은 이것을 버린다.
  - 조사 권고의 '요청 파일 큐'는 두지 않는다. 단계 코드가 같은 프로세스에서 임포트되므로 파일 IPC 가 필요 없다. 대신 상류·하류 분석 모듈과는 **파일 계약**(`ai_in`·`ai_out`, §2.4)으로만 만난다.
- 파이프라인 안의 호출 지점(클라우드 PC):

| 순서 | 파이프라인 단계 | 브리지 호출 | 근거 |
|---|---|---|---|
| 1 | 수집 마무리(커버리지 원장의 빈 날만) | `run --stages lookup_mail,lookup_teams[,lookup_calendar]` | 로컬 색인·COM·웹 경로가 비운 날을 요약 증거로 보강 |
| 2 | 정규화 직후(화행 회색 지대만) | `run --stages speech_act` | 규칙 화행 점수가 애매한 메시지만 |
| 3 | 단위업무 후보 클러스터링 직후 | `run --stages task_label` | 규칙으로 못 정한 후보만 |
| 4 | 결정적 과정 마이닝 직후 | `run --stages workflow_label,agentic_match,subagent_review` | 워크플로우 라벨 → 매칭 → 서브에이전트 |
| 5 | 보고서 직전 | `run --stages review_text` | 주간·월간 리뷰 |

- 부모와의 통신: (a) 표준 출력 JSON 한 줄 이벤트(§7.15), (b) 단계 상태 파일(하트비트·진전, 공통 단계 상태 계약), (c) 끝에 `stage_result.json`. 부모는 프로세스 트리를 언제든 끊을 수 있다(저널이 보존).
- 동시성: 한 PC 에서 Edge 프로필을 모는 프로세스는 언제나 하나(§4.5 잠금). 웹 수집기(Outlook 웹·Teams 웹)도 같은 L0 를 쓰므로 같은 프로필·같은 포트 범위·같은 잠금을 공유한다(§4.5 '역할 공용 한 벌').
- 스레드: 주 루프 1개 + 하트비트 스레드 1개(실제 시계일 때만). 가상 시계 시험에서는 하트비트를 끈다.

### 2.4 파일과 경로

경로는 모두 공통 경로 로더(`lm27.paths`)가 만든다. 브리지 코드는 문자열 경로를 조립하지 않는다(관문 '데이터 경로 직접 접근 금지').

| 경로 | 내용 | 원문 | 이동 번들 포함 |
|---|---|---|---|
| `%LOCALAPPDATA%\LoadMonitor27\edge_copilot\` | 전용 Edge 프로필(쿠키 포함, DPAPI 로 이 PC 에 묶임). 브리지·OWA·Teams 웹 역할 공용(§4.5). 이름은 `TEAM_AND_BUNDLE.md` §1.1 과 같다 | — | **아니오** |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\session.lock.json` | 프로필 잠금·탭 소유 기록(§4.5) | 없음 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\profile_id.txt` | 프로필을 새로 만들 때 생성한 UUID(보정값 키, §4.10) | 없음 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\bridge_profile.json` | 보정값·학습한 DOM 선택자·조회 능력·건강 기록(§4.10) | 없음 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\trace.jsonl` | 전송 계측(4MB 교체) | 없음 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\probe_last.json` | 마지막 `probe` 결과(확인 항목·코드만, §12.2) | 없음 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\agent\copilot_manual\` | 수동 경로 프롬프트 파일·목록·`inbox\`(§10, 자리는 `PRIVACY.md` §13.3 과 같다) | 게이트 통과본, TTL 7일 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\rawcap\` | 원문 캡처(사용자가 켰을 때만) | 게이트 통과본, TTL 7일 | 아니오 |
| `%LOCALAPPDATA%\LoadMonitor27\bridge\diagnose\diagnose_<시각>.json` | DOM 진단 덤프(글자 형식 보존 마스킹, §12.4) | 없음 | 아니오 |
| `<ROOT>\data\derived\ai_in\<stage>.jsonl` | 상류 분석이 쓴 단계 입력(정제본 필드만, §2.5) | 정제본 | 예(파생, 재생성 가능) |
| `<ROOT>\data\derived\ai_out\<stage>.json` | 단계 산출(접은 결과) | AI 라벨(입수 정제 후) | 예(파생). 팀 업로드는 별도 허용 목록 |
| `<ROOT>\data\derived\bridge\store\<stage>.items.jsonl` | 항목 저장소(커밋, 실행을 넘어 유지 — 다시 묻지 않기 위한 캐시) | AI 라벨(입수 정제 후) | 예(파생) |
| `<ROOT>\data\derived\bridge\runs\<run_id>\<stage>.jsonl` | 질의·전송 저널(길이·해시·건수만) | 없음 | 예(파생) |
| `<ROOT>\data\derived\bridge\runs\<run_id>\<stage>.result.json` | 결과 봉투(§7.11) | 없음 | 예(파생) |
| `<ROOT>\data\derived\bridge\runs\<run_id>\capabilities.json` | 조회 능력 상태(§7.13) | 없음 | 예(파생) |

`<ROOT>` 는 프로그램 폴더, `<ROOT>\data` 는 운반 번들 루트, `derived\` 는 '파생 산출(언제든 재생성)' 자리다(`TEAM_AND_BUNDLE.md` §1.1). PC 에 남아야 하는 것(프로필·잠금·계측·수동 파일·원문 캡처)은 `%LOCALAPPDATA%` 에, 분석 입출력과 AI 답 저장소는 `data\derived\` 에 둔다. 실행 ID `run_id` 는 `YYYYMMDD-HHMMSS-xxxx`(xxxx = 무작위 16진 4자리).

### 2.5 상류·하류 파일 계약 (`ai_in` / `ai_out`)

브리지는 분석 모듈을 임포트하지 않는다. 상류는 `ai_in`, 하류는 `ai_out` 만 본다.

`data\derived\ai_in\<stage>.jsonl` — 한 줄이 항목 하나:

```json
{"key": "cand:7f3a19c2", "group": "P012", "fields": {"…": "단계별 허용 필드(§8)"}, "rule": {"…": "규칙 판정·후보·점수"},
 "src_ver": "rules-2026.10.1", "meta": {"priv_class": "work", "ad_band": "keep", "rules_ver": "2026.10.0"}}
```

| 필드 | 형 | 필수 | 뜻 |
|---|---|---|---|
| `key` | str ≤ 80 | 예 | 상류가 정한 안정 키. 같은 대상이면 실행이 바뀌어도 같다 |
| `group` | str ≤ 40 | 아니오 | 패킹 묶음 키(같은 과제끼리 등). 없으면 `""` |
| `fields` | obj | 예 | 단계의 `send_fields` 에 있는 키만. 그 밖의 키가 있으면 L3 가 **버리고 건수 기록**(보내지 않음) |
| `rule` | obj | 아니오 | 규칙 판정(폴백 재료). **보내지 않는다**. 단, 단계가 '후보'로 명시한 필드만 `fields` 로 옮겨 보낸다 |
| `src_ver` | str | 아니오 | 상류 규칙 판 — 내용 키에 넣지 않는다(규칙만 바뀌면 다시 묻지 않는다) |
| `meta` | obj | 아니오 | 정제 행에서 넘어온 `priv_class`·`ad_band`·`rules_ver`. **보내지 않는다**. 항목 게이트(§9.2)의 `GateItem.meta` 로만 쓴다 |

`data\derived\ai_out\<stage>.json`:

```json
{"schema": 1, "stage": "task_label", "stage_ver": "task_label/1.0", "run_id": "20261005-101500-3fa2",
 "registry_version": "r12",
 "items": {"cand:7f3a19c2": {"ans": {"project": "P012", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV",
                                     "title": "광학 모듈 공차 해석", "new": "", "conf": "h"},
                             "by": "ai", "rid": "R7F3QK", "asks": 1, "at": "2026-10-05T10:21:44+09:00"}},
 "stats": {"total": 120, "ai": 112, "manual": 0, "rule": 8, "pending": 0},
 "result": "data/derived/bridge/runs/20261005-101500-3fa2/task_label.result.json"}
```

`by` ∈ `ai | manual | rule | rule_pending`. `rule_pending` 은 아직 AI 를 기다리는 항목에 접기 시점에 임시로 채운 규칙 답이다(다음 실행이 다시 묻는다).

### 2.6 이전 조사 권고와 달라진 점

| 조사 권고(copilot.md) | 이 명세 | 이유 |
|---|---|---|
| 서약 `<<END rid>>` | `[[END rid]]` (`<<END rid>>` 도 인식) | `<…>` 는 Copilot 화면의 마크다운→HTML 처리에서 태그로 지워질 위험이 있다. LM24 의 `[[전송끝]]` 은 실측으로 화면에 남았다. 미결 Q5 에서 실측 확인 |
| 프로필 `data\bridge_profile` | `%LOCALAPPDATA%\LoadMonitor27\edge_copilot` | 결정 메모 §3: 프로필은 번들 밖 |
| 포트 9333 기본 | 9343 기본, 점유 시 +1 (최대 10개) | 같은 클라우드 PC 에서 LM24(9333)가 돌 수 있다. 결정 메모 §0 '포트가 겹치지 않게' |
| 메일 조회 100행 이하 | 행 상한 = 답 예산 ÷ 행 추정 길이(기본 32행), 설정 상한 100 | 답 한도 5,000자에서 100행은 물리적으로 잘린다(LM24 의 140/150행 잘림이 그 증상) |
| 단계가 요청 파일을 넣는 브리지 큐 | 같은 프로세스에서 단계 실행 + `ai_in/ai_out` 파일 계약 | IPC 를 없애 실패 경로를 줄인다. 프로세스 수명은 '실행 1회'로 같다 |
| 겹침 3항목 | 겹침은 '참고(답하지 말 것)' 문맥 줄로만 | 답 예산을 쓰지 않고, 겹친 항목의 두 답을 합치는 규칙이 필요 없다 |
| `bridge send` 명령 | `replay`(개발용)로 대체 | 원문 비저장이므로 입력 재료에서 프롬프트를 다시 만들어 보낸다 |

---

## 3. 설정 키

모든 키는 설정 레지스트리(단일 레지스트리)의 `bridge.*` 네임스페이스에 등록한다. 표의 '읽는 곳'에 없는 키는 만들지 않는다(죽은 키 금지, 관문 G-B3). 범위를 벗어난 값은 `settings.py` 가 **기본값으로 되돌리고 경고 1건**을 남긴다(실행을 막지 않는다).

### 3.1 동작 방식·세션(L0)

| 키 | 형 | 기본 | 범위 | 뜻 | 읽는 곳 |
|---|---|---|---|---|---|
| `bridge.mode` | str | `"auto"` | `auto`·`manual`·`off` | `auto` = CDP 자동, `manual` = 붙여넣기 경로, `off` = AI 단계를 모두 규칙 폴백으로 | cli, runner |
| `bridge.autoManualFallback` | bool | `true` | | `policy_blocked`·`edge_not_found` 가 확인되면 이 실행부터 수동 경로로 자동 전환 | runner |
| `bridge.url` | str | `"https://m365.cloud.microsoft/chat"` | `https://` 로 시작 | 새 탭과 새 채팅 폴백이 여는 주소 | session |
| `bridge.chatUrlPrefixes` | list[str] | `["https://m365.cloud.microsoft/chat", "https://copilot.cloud.microsoft/"]` | 1~8개, `https://` | 탭 신원 1차: URL 이 이 접두 중 하나로 **정확히** 시작(호스트 비교는 파싱 후) | session |
| `bridge.loginHosts` | list[str] | `["login.microsoftonline.com", "login.live.com", "login.microsoft.com"]` | 1~8개 | 이 호스트면 로그인 필요 | session |
| `bridge.edge.port` | int | `9343` | 1024~65535 | 디버그 포트 시작값(브리지·OWA·Teams 웹 역할 공용, §4.5) | session |
| `bridge.edge.portTries` | int | `10` | 1~50 | 남이 쓰는 포트면 +1 씩 시도할 개수 | session |
| `bridge.edge.profileDir` | str | `""` | | 빈 값 = `%LOCALAPPDATA%\LoadMonitor27\edge_copilot`. 역할 공용 — 웹 수집기에 따로 두지 않는다(§4.5) | session |
| `bridge.edge.diskCacheMB` | int | `200` | 0~4096 | 프로필 디스크 캐시 상한(0 = 상한 없음) | session |
| `bridge.edge.windowSize` | str | `"1150,900"` | `W,H` | 창 크기 | session |
| `bridge.edge.closeOnExit` | bool | `true` | | 브리지가 띄운 Edge 는 끝날 때 `Browser.close` 로 닫는다(디버그 포트 노출 시간 최소화) | session |
| `bridge.loginWaitMin` | int | `10` | 1~60 | 로그인 필요 시 사람을 기다리는 시간 | session |
| `bridge.readyWaitSec` | int | `60` | 10~300 | 입력창이 뜨기를 기다리는 시간 | session, transport |
| `bridge.modelFast` | str | `"빠른 응답"` | | 대량 분류용 모델 메뉴 이름(부분 일치, 표기 차이 무시). 빈 값 = 모델을 건드리지 않음 | session |
| `bridge.modelDeep` | str | `"깊이 생각하기"` | | 합성 작업용 모델 메뉴 이름 | session |
| `bridge.modelFallback` | str | `"자동"` | | 사다리 2단에서 쓰는 모델 | exchange |
| `bridge.preferWorkMode` | bool | `true` | | 업무(Work)/웹 전환이 보이면 업무 쪽으로 맞춘다 | session |
| `bridge.webExposure.policy` | str | `"strict"` | `strict`·`block` | 웹 노출 환경(§4.11)일 때: `strict` = 엄격 규칙(§9.7)을 거쳐 전송, `block` = 모든 AI 단계를 보내지 않고 규칙 폴백(`skipped(reason=web_exposed)`) | runner, gate |

### 3.2 전송·완료 판정(L1)

| 키 | 형 | 기본 | 범위 | 뜻 | 읽는 곳 |
|---|---|---|---|---|---|
| `bridge.pollSec` | float | `3` | 1~10 | 답 폴링 간격 | transport |
| `bridge.stablePolls` | int | `8` | 3~30 | 몸통이 이만큼 연속 같으면 stable 완료 | transport |
| `bridge.incompleteJsonFactor` | int | `2` | 1~5 | 봉투가 시작됐는데 엄격 파싱이 안 되면 stable 에 필요한 폴 수를 이 배수로 | transport |
| `bridge.firstTokenSec` | int | `180` | 30~600 | 첫 글자를 기다려 주는 유예. 지나도 비면 empty | transport |
| `bridge.replyTimeoutSec` | int | `480` | 60~1800 | 전송 1회의 답 대기 상한 | transport |
| `bridge.roundtripMaxSec` | int | `900` | 120~3600 | 질의 1건(사다리 포함)의 총 예산 | exchange |
| `bridge.waitIdleSec` | int | `45` | 5~180 | 전송 전 앞 답 생성이 끝나기를 기다리는 상한 | transport |
| `bridge.chatTurns` | int | `12` | 0~50 | 같은 채팅에서 이어 보낼 질의 수(0 = 질의마다 새 채팅) | exchange |

### 3.3 패킹·재시도·예산(L3)

| 키 | 형 | 기본 | 범위 | 뜻 | 읽는 곳 |
|---|---|---|---|---|---|
| `bridge.inputMaxChars` | int | `8000` | 2000~20000 | 보정값이 없을 때의 입력 패킹 예산 | runner |
| `bridge.answerMaxChars` | int | `5000` | 1500~12000 | 보정값이 없을 때의 답 패킹 예산 | runner |
| `bridge.calibSafety` | float | `0.85` | 0.5~0.95 | 패킹 예산 = 실측 한도 × 이 값 | calibrate |
| `bridge.calibrateTtlDays` | int | `30` | 1~365 | 보정값 유효 기간 | calibrate |
| `bridge.autoCalibrate` | bool | `true` | | 보정값이 없거나 만료면 첫 단계 전에 자동 보정 | runner |
| `bridge.overlapItems` | int | `3` | 0~10 | 앞 묶음 끝 항목을 '참고' 줄로 다시 보일 개수 | runner |
| `bridge.overlapChars` | int | `600` | 0~2000 | 겹침 줄의 글자 상한 | runner |
| `bridge.seenNamesMax` | int | `30` | 0~100 | '앞서 쓴 이름' 개수 상한 | runner |
| `bridge.seenNamesChars` | int | `600` | 0~2000 | '앞서 쓴 이름' 글자 상한 | runner |
| `bridge.splitMinItems` | int | `5` | 1~40 | 분류형 단계의 반분 최소 크기(생성형은 단계 정의의 `min_split`) | runner |
| `bridge.splitMaxDepth` | int | `3` | 0~6 | 반분 깊이 상한 | runner |
| `bridge.maxAsksPerItem` | int | `3` | 1~6 | 한 항목을 물을 수 있는 최대 횟수 | runner |
| `bridge.circuitSoft` | int | `3` | 1~20 | 연속 0건 질의가 이만큼이면 soft(반분·사다리 2단 끔) | runner |
| `bridge.circuitAbort` | int | `6` | 2~40 | 연속 0건 질의가 이만큼이면 단계 중단(재개 가능) | runner |
| `bridge.stageBudgetMin` | int | `120` | 0~600 | 단계 1개의 자기 예산(0 = 끔) | budget |
| `bridge.totalBudgetMin` | int | `300` | 0~1440 | 호출 1회(여러 단계)의 전체 예산(0 = 끔) | budget |
| `bridge.stageFloorMin` | int | `15` | 0~120 | 전체 예산을 앞 단계가 다 써도 각 단계에 주는 최소 몫 | budget |
| `bridge.finalReserveMin` | int | `30` | 0~240 | 호출의 마지막 단계 몫으로 미리 떼어 두는 시간 | budget |
| `bridge.minAskSec` | int | `120` | 30~900 | 남은 예산이 이보다 적으면 새 질의를 시작하지 않는다 | runner |

### 3.4 조회·능력·수동·기록

| 키 | 형 | 기본 | 범위 | 뜻 | 읽는 곳 |
|---|---|---|---|---|---|
| `bridge.lookup.windowDays` | int | `7` | 1~10 | 조회 구간 길이 | stages.lookup |
| `bridge.lookup.minWindowDays` | int | `1` | 1~7 | 쪼갤 수 있는 최소 구간 | stages.lookup |
| `bridge.lookup.maxRows` | int | `100` | 10~150 | 행 상한의 위 한계(실제 상한은 답 예산 ÷ 행 추정 길이와의 작은 값) | stages.lookup |
| `bridge.lookup.fullRatio` | float | `0.9` | 0.5~1.0 | 행 수가 상한 × 이 값 이상이면 '가득 참'으로 보고 구간을 쪼갠다 | stages.lookup |
| `bridge.capability.confirmDays` | int | `2` | 1~5 | '조회 불가' 확정에 필요한 서로 다른 날짜 수 | capability |
| `bridge.capability.ttlDays` | int | `14` | 1~90 | '조회 불가' 확정의 유효 기간(지나면 다시 확인) | capability |
| `bridge.manual.maxOpenBatches` | int | `10` | 1~50 | 수동 경로에서 한 번에 내보낼 프롬프트 파일 수 | manual |
| `bridge.manual.ttlDays` | int | `7` | 1~30 | 수동 프롬프트 파일 보존 기간 | manual |
| `bridge.rawCapture` | bool | `false` | | 켜면 게이트 통과 프롬프트와 입수 정제한 답을 `rawcap\` 에 TTL 보존(진단용) | exchange |
| `bridge.rawCaptureTtlDays` | int | `7` | 1~14 | 원문 캡처 보존 기간 | exchange |
| `bridge.traceMaxBytes` | int | `4000000` | 1e5~5e7 | 계측 파일 교체 크기 | trace |
| `bridge.stages` | obj | 아래 | 단계 ID → bool | 단계 켜기/끄기. 기본: `lookup_mail` true, `lookup_teams` true, `lookup_calendar` false, 나머지 true | runner |

### 3.5 화면 요소(DOM) — Copilot 화면이 바뀌면 여기만 고친다

| 키 | 형 | 기본 | 뜻 |
|---|---|---|---|
| `bridge.dom.inputSelectors` | list[str] | `["[contenteditable='true'][role='textbox']", ".fai-EditorInput__input", "span[contenteditable='true']", "div[contenteditable='true']", "textarea"]` | 입력창 후보(보이는 첫 요소) |
| `bridge.dom.inputAriaLabels` | list[str] | `["Copilot에 메시지 보내기", "Message Copilot"]` | 입력창 aria-label 부분 일치 후보. 일치하면 신원 확정 강도 `strong` |
| `bridge.dom.sendLabels` | list[str] | `["보내기", "전송", "Send"]` | 입력창의 작성 영역 **안에서만** 찾는 전송 버튼 aria-label |
| `bridge.dom.stopLabels` | list[str] | `["생성 중지", "응답 중지", "stop generating", "stop responding", "중지", "stop"]` | 생성 중 버튼(앞 4개 부분 일치, 뒤 2개 완전 일치) |
| `bridge.dom.newChatLabels` | list[str] | `["새 채팅", "새 대화", "new chat"]` | 새 채팅 버튼 |
| `bridge.dom.modelButtonLabels` | list[str] | `["모델", "model"]` | 모델 선택 버튼 aria-label 부분 일치 |
| `bridge.dom.workModeLabels` | obj | `{"work": ["업무", "Work"], "web": ["웹", "Web"]}` | 업무/웹 전환 버튼 |
| `bridge.dom.webGroundingLabels` | list[str] | `["웹 콘텐츠", "웹 검색", "웹 근거", "Web content", "Web search", "Web grounding"]` | 웹 근거 켜기/끄기 요소(스위치·체크 메뉴 항목)의 aria-label·글자 부분 일치 후보. **상태만 읽고 누르지 않는다**(§4.11) |
| `bridge.dom.assistantSelectors` | list[str] | `[]` | 답 메시지 노드 선택자. 빈 값이면 학습값(§5.5) → 앵커 폴백 순 |

환경 변수(설정 키 아님, **시험 전용**): `LM_COPILOT_STUB=<폴더>`(스텁 전송), `LM_NO_BROWSER=1`(Edge 를 띄우지 않음) — 수집 명세(`COLLECTION.md`)의 시험 주입점 이름과 같다. 패키징 관문이 배포 설정·바로가기에 이 변수가 없는지 확인한다.

---

## 4. L0 세션 — 프로필·Edge·로그인·탭 소유

### 4.1 책임과 경계

L0 는 '입력할 수 있는 Copilot 탭 하나'를 L1 에 넘겨주고, 끝나면 정리한다. Outlook 웹·Teams 웹 수집기도 같은 L0 를 쓴다(역할 `role` 만 다르다). L0 는 페이지 내용을 읽지 않는다. 신원 확인에 필요한 URL·제목·준비 상태·입력창 존재 여부만 본다.

허용 동작: Edge 실행 파일 탐색, 정책 레지스트리 **읽기**, 전용 프로필로 Edge 기동, `127.0.0.1` 디버그 포트 연결, 자기 탭 생성·이동·닫기, `Page.bringToFront`, 새로고침, 모델 메뉴·업무 모드 버튼 클릭(자기 탭 안).
금지 동작: 로그인 화면 입력, 쿠키·저장소 읽기(`Network.getCookies`, `Storage.*`, `IndexedDB.*` CDP 도메인 호출 금지), 남의 탭 닫기·읽기, `--remote-allow-origins=*`, `0.0.0.0` 바인딩, 관리자 권한 요구.

### 4.2 자료구조

```python
@dataclass
class EdgeInfo:
    path: str                 # msedge.exe 전체 경로
    version: str              # 예 "129.0.2792.65" (모르면 "")
    policy_debug: str         # "allowed" | "blocked" | "unset"   (§4.3)
    policy_devtools: str      # "allowed" | "blocked" | "unset"

@dataclass
class SessionInfo:
    role: str                 # "bridge" | "owa" | "teams_web"
    profile_dir: str
    profile_id: str           # 프로필 폴더를 새로 만들 때 만든 UUID — bridge\profile_id.txt. 보정값 키
    port: int
    browser_id: str           # /json/version 의 webSocketDebuggerUrl 끝 UUID
    launched_by_us: bool
    target_id: str            # 이 역할이 소유한 탭
    ws_url: str               # 그 탭의 webSocketDebuggerUrl
    state: str                # §4.7 상태
    identity: str             # "strong" | "weak" | ""   (입력창 aria-label 일치 여부)
    work_mode: str            # "work" | "web" | "unknown"
    model_current: str        # 마지막으로 확인한 모델 버튼 표기(60자)
    chat_seq: int             # new_chat 마다 +1 (모델 선택 캐시 키)
    env: "CopilotEnv"         # 계정 등급·업무 모드·웹 근거·웹 노출(§4.11). 호출 시작 때 1회 판별
```

잠금 파일 `session.lock.json`:

```json
{"schema": 1, "pid": 12345, "pid_ctime": 133722134567890000, "role": "bridge", "run_id": "20261005-101500-3fa2",
 "port": 9343, "browser_id": "6b0c…", "launched_by_us": true,
 "targets": {"bridge": ["C1A2…"], "owa": [], "teams_web": []},
 "acquired": "2026-10-05T10:15:00+09:00", "heartbeat": "2026-10-05T10:31:30+09:00"}
```

### 4.3 Edge 탐색·정책·기동

**탐색 순서**(첫 존재 경로): ① `HKLM` 과 `HKCU` 의 `SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe` 기본값(`winreg`), ② `%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe`, ③ `%ProgramFiles%\…`, ④ `%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe`. 없으면 `edge_not_found`.

**정책 읽기**(읽기만): `HKLM`·`HKCU` 의 `SOFTWARE\Policies\Microsoft\Edge` 아래 `RemoteDebuggingAllowed`(DWORD, 0 = 금지)와 `DeveloperToolsAvailability`(DWORD, 2 = 금지). 하나라도 금지면 `policy_*="blocked"`. 정책 이름은 실측 확인 대상(미결 Q2)이므로 **판단은 기능 확인이 최종**: 기동 후 20초 안에 `/json/version` 이 응답하지 않고 Edge 프로세스는 떠 있으면 `policy_blocked` 로 확정한다.

**포트 고르기**:

```text
def choose_port(cfg, profile_dir):
    # 1) 우리 프로필이 이미 떠 있는가 — DevToolsActivePort 로 확인
    dap = read_devtools_active_port(profile_dir)            # (port, browser_path) 또는 None
    if dap and debugger_alive(dap.port) and owns(dap.port, dap.browser_path):
        return dap.port, "reuse"
    # 2) 시작값부터 차례로
    for p in range(cfg.edge.port, cfg.edge.port + cfg.edge.portTries):
        if debugger_alive(p):
            if owns(p, dap.browser_path if dap else None):  # 우리 것
                return p, "reuse"
            continue                                        # 남의 디버그 Edge(LM24 등) — 절대 붙지 않는다
        if not can_bind("127.0.0.1", p):                    # 다른 프로그램이 점유
            continue
        return p, "launch"
    raise PhaseError("port_exhausted")

def owns(port, browser_path):
    # /json/version 의 webSocketDebuggerUrl 이 우리 프로필의 DevToolsActivePort 2째 줄과 같은 브라우저 ID 인가
    v = http_json(port, "/json/version")
    return browser_path is not None and v["webSocketDebuggerUrl"].endswith(browser_path)
```

`DevToolsActivePort` 는 크로미움이 `--remote-debugging-port` 로 뜰 때 `user-data-dir` 에 쓰는 2줄 파일(포트, `/devtools/browser/<uuid>`)이다. Edge 의 동작은 실측 확인 대상(미결 Q4). 파일이 없으면 소유 확인은 잠금 파일의 `port`·`browser_id` 와 `/json/version` 대조로 대신한다.

**기동 인자**(LM24 에서 유지·수정):

```python
args = [edge,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-timer-throttling",        # 배경 스로틀링 해제 3종(LM24 실측: 비활성 탭은 답이 자라지 않음)
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        f"--window-size={cfg.edge.windowSize}"]
if cfg.edge.diskCacheMB > 0:
    args.append(f"--disk-cache-size={cfg.edge.diskCacheMB * 1048576}")
if origin_mode == "explicit":                          # §4.4 확인 결과가 403 일 때만
    args.append(f"--remote-allow-origins=http://127.0.0.1:{port}")
args.append(cfg.url)
subprocess.Popen(args, creationflags=0x08000000)       # CREATE_NO_WINDOW (콘솔 창만 숨김)
```

`--remote-allow-origins=*` 는 **쓰지 않는다**(같은 PC 의 다른 웹 페이지가 로그인된 세션을 조종할 수 있음). `--remote-debugging-address` 도 주지 않는다(기본 `127.0.0.1`).

기동 대기: `debugger_alive(port)` 를 0.5초 간격 최대 20초. 실패 시 원인 구분:

| 관찰 | 단계(phase) |
|---|---|
| Edge 프로세스가 없음(Popen 직후 종료, 프로필 잠금 프로세스도 없음) | `launch_failed` |
| 우리 프로필을 쓰는 Edge 가 떠 있는데 포트 없음(사람이 같은 프로필을 일반 실행) | `profile_busy` — 30초 기다려 1회 재확인 |
| Edge 는 떴고 포트 무응답, 정책 레지스트리 금지 | `policy_blocked` |
| Edge 는 떴고 포트 무응답, 정책 미설정 | `launch_failed` (2-strike 대상) |

### 4.4 CDP 연결과 Origin 확인

- WebSocket 클라이언트는 LM24 `WS` 를 이식한다. 핸드셰이크에 `Origin` 헤더를 **보내지 않는다**(기본). 크로미움은 Origin 이 없는 연결은 허용하는 것으로 알려져 있으나 Edge 판에서 확인이 필요하다(미결 Q3).
- 핸드셰이크가 `403` 이면: 이 세션을 닫고 `origin_mode="explicit"` 로 Edge 를 다시 띄우며, 핸드셰이크에 `Origin: http://127.0.0.1:<port>` 를 넣는다. 결과는 `bridge_profile.json` 의 `health.origin_mode` 에 저장해 다음부터 바로 쓴다.
- CDP 호출 규약(LM24 유지): 호출마다 시간 한도, 소켓 `settimeout(min(남은 시간, 30))`, 시간 초과가 나면 그 연결은 재사용 금지 → `reconnect()`. `Runtime.evaluate` 는 `returnByValue=True`, 예외면 `RuntimeError("JS: …")`(메시지 200자, 페이지 원문 금지).
- 추가: 수신 프레임 길이 상한 64MB(넘으면 연결 폐기), 이벤트 메시지(id 없음)는 버린다.

### 4.5 프로필 잠금

```text
def acquire_lock(role, run_id):
    p = paths.edge_lock()
    for attempt in (1, 2):
        try:
            fd = os.open(p, O_CREAT | O_EXCL | O_WRONLY)       # 원자적 생성
            write_json(fd, new_lock(role, run_id)); return
        except FileExistsError:
            cur = read_json_or_none(p)
            if cur is None or lock_is_stale(cur):
                os.replace(p, p + ".stale")                    # 기록 보존 후 재시도
                continue
            raise PhaseError("lock_busy", owner_role=cur["role"], age_sec=...)

def lock_is_stale(cur):
    if not process_alive(cur["pid"], cur["pid_ctime"]):        # ctypes: OpenProcess + GetExitCodeProcess(259=STILL_ACTIVE) + GetProcessTimes
        return True
    return heartbeat_age(cur) > 30 * 60                        # 살아 있으나 30분 무응답 = 멈춘 프로세스로 본다
```

> 주의: 윈도우에서 `os.kill(pid, 0)` 은 '생존 확인'이 아니라 **그 프로세스를 종료**시킨다. 생존 확인은 반드시 `ctypes` 의 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetExitCodeProcess` 로 하고, PID 재사용을 막으려고 `GetProcessTimes` 의 생성 시각(`pid_ctime`)을 함께 비교한다.

- 하트비트: 30초마다 `heartbeat` 갱신(임시 파일 → `os.replace`).
- 같은 실행 안에서 역할을 바꿀 때(웹 수집기 → 브리지)는 잠금을 놓고 다시 잡는다. 다른 역할의 소유 탭은 `targets` 에 남아 있어도 건드리지 않는다.
- 해제: `finally` 에서 자기 탭 닫기(`closeOnExit=false` 일 때) → 잠금 파일 삭제.
- **역할 공용 한 벌**: 브리지(`bridge`)·Outlook 웹(`owa`)·Teams 웹(`teams_web`) 역할은 모두 같은 프로필(`bridge.edge.profileDir`)·같은 포트 범위(`bridge.edge.port` ~ `+portTries`)·같은 잠금을 쓴다. 크로미움 계열 브라우저는 같은 `--user-data-dir` 로 두 번째 기동을 하면 새 프로세스가 첫 인스턴스에 창 열기를 넘기고 곧 끝나므로, 두 번째 기동에 준 `--remote-debugging-port` 는 열리지 않는다(→ `launch_failed`·`profile_busy` 오진. Edge 에서의 확인은 Q4 와 함께). 그래서 웹 수집기는 별도 프로필·포트 설정 키를 두지 않고 `lm27.bridge.session.EdgeSession.open(role=…)` 만 부른다(관문 G-B12, §16 Q23).

### 4.6 탭 소유와 신원

```text
def own_tab(sess, role):
    tabs = [t for t in http_json(port, "/json") if t["type"] == "page"]
    prev = lock.targets.get(role, [])
    for t in tabs:
        if t["id"] in prev:                                    # 지난번 우리 탭이 살아 있으면 재사용
            return t
    t = http_json(port, "/json/new?" + quote(cfg.url, safe=""), method="PUT")   # 실패 시 GET 재시도(구버전)
    lock.targets[role] = [t["id"]]; save_lock()
    return t
```

- **남의 탭은 닫지 않는다.** LM24 `find_tab` 의 '첫 탭만 남기고 닫기'와 부분 문자열 호스트 목록(`office.com` 포함)이 Outlook 웹 탭을 Copilot 탭으로 잡고 진짜 Copilot 탭을 닫던 결함(조사 probe3)을 구조적으로 없앤다.
- 매 전송 전 `activate`: `Page.bringToFront` + `GET /json/activate/<id>`(실패해도 진행).

**신원 판정** `identity(sess) -> state` — JS `/*LM27:identity*/` 가 `{url, title, ready, input:{found, aria, sel}}` 을 돌려준다:

| 순서 | 조건 | 상태 |
|---|---|---|
| 1 | URL 호스트(파싱 후 소문자)가 `loginHosts` 중 하나 | `login_required` |
| 2 | URL 이 `about:blank`·빈 값·`chrome-error://`·`edge-error://`·`edge://` | `dead` (로딩 중이면 `loading`) |
| 3 | URL 이 `chatUrlPrefixes` 중 하나로 시작하지 않음 | `wrong_page` |
| 4 | `ready != "complete"` 이고 입력창 없음 | `loading` |
| 5 | 입력창 있음 + aria-label 이 `inputAriaLabels` 부분 일치 | `ready` (identity=`strong`) |
| 6 | 입력창 있음 + aria 불일치(선택자만 일치) | `ready` (identity=`weak`, 진단 경고 1회) |
| 7 | 입력창 없음 | `no_input` |

`weak` 는 동작은 하되 `probe` 가 `inputAriaLabels` 갱신을 권한다. URL 비교는 반드시 `urllib.parse` 로 호스트를 뽑아 **완전 일치**로 한다(부분 문자열 금지).

### 4.7 로그인·준비 상태 기계

```text
def ensure_ready(sess, deadline):
    st = identity(sess)
    if st == "wrong_page":   navigate(own_tab, cfg.url); st = poll_identity(20s)
    if st == "loading":      st = poll_identity(min(cfg.readyWaitSec, left(deadline)))
    if st == "login_required":
        notify("BR-LOGIN")                                   # 창을 앞으로 + 사용자 문구
        st = poll_identity(every=5s, up_to=min(cfg.loginWaitMin*60, left(deadline)),
                           until=lambda s: s not in ("login_required", "loading"))
        if st == "ready": notify("BR-LOGIN-OK")
        else: return "login_required"                        # L3 가 2-strike 처리
    if st == "no_input":
        st = poll_identity(min(cfg.readyWaitSec, left(deadline)))
        if st == "no_input":
            Page.reload(); st = poll_identity(min(cfg.readyWaitSec, left(deadline)))
        if st == "no_input": dump_diagnose(sess); return "input_not_found"
    if st == "dead":
        Page.reload(); st = poll_identity(20s)
        if st == "dead": record_health("dead_session"); return "dead_session"
    return st                                                # "ready"
```

**죽은 프로필 자동 복구**: `bridge_profile.json` 의 `health.dead_sessions` 에 서로 다른 호출 2회의 `dead_session` 이 쌓이면, 다음 호출 시작 때 Edge 를 닫고 프로필 폴더를 `edge_copilot.bad-<시각>` 으로 바꾼 뒤(이전 `.bad-*` 는 1개만 남김) 새 프로필로 띄운다 → 로그인 필요 흐름(BR-LOGIN). 사람에게 폴더 조작을 요구하지 않는다.

### 4.8 모델 선택과 업무 모드

- LM24 `js_pick_model`·`js_menu_open`·`js_pick_model_item`·`select_model` 를 이식한다(표기 차이 무시 비교, 이미 열린 메뉴 토글 방지, 하위 메뉴 3단).
- 수정: (a) **채팅마다 1회**만 선택한다(`chat_seq` 와 원하는 모델이 같으면 생략 — LM24 는 왕복마다 메뉴를 열었다), (b) 결과를 `ModelNote{wanted, picked, ok, menu_seen[≤8]}` 로 돌려주고 봉투에 `model_wanted`·`model_used` 로 기록, (c) 실패해도 진행(경고).
- 단계별 모델: `fast` 등급 → `modelFast`, `deep` 등급 → `modelDeep`, 사다리 2단 → `modelFallback`. 빈 문자열이면 건드리지 않는다.
- 업무 모드: JS `/*LM27:work_mode*/` 가 `workModeLabels` 로 전환 버튼을 찾아 `{mode, toggle}` 을 돌려준다(`aria-pressed`/`aria-checked`/`aria-selected` 로 상태 판별). `preferWorkMode=true` 이고 `mode=="web"` 이면 업무 쪽을 1회 클릭하고 다시 확인한다. 판별 불가면 `unknown` 으로 기록하고 진행한다. 조회 단계는 `web` 이 확정이면 실행하지 않는다(§8.1). 업무 모드 판별 결과는 계정 등급·웹 근거와 함께 `CopilotEnv` 로 모은다(§4.11).

### 4.9 세션 수명

```text
with EdgeSession.open(role="bridge", run_id=…) as sess:   # 잠금 → 포트 → 기동/재사용 → 탭 → ensure_ready
    … L1/L2/L3 …
# __exit__: 자기 탭 정리, launched_by_us 이고 closeOnExit 이면 브라우저 WS 로 Browser.close,
#           5초 안에 포트가 닫히지 않으면 그대로 둔다(사용자 브라우저를 강제 종료하지 않는다), 잠금 해제
```

### 4.10 `bridge_profile.json` (클라우드 PC 로컬, 계정 정보 없음)

```json
{"schema": 1,
 "profile_id": "0b8e3c7e-…",
 "calibration": [{"model": "빠른 응답", "edge_major": 129, "date": "2026-10-05",
                  "input_limit": 9050, "output_limit": 5560, "pack_in": 7690, "pack_out": 4720,
                  "server_trunc": false, "sends": 4}],
 "runtime_adjust": {"task_label": {"pack_out_factor": 0.8, "at": "2026-10-05T11:02:00+09:00"}},
 "dom": {"assistant_sel": "[data-testid='copilot-message-reply']", "learned_at": "2026-10-05T10:16:10+09:00",
         "verified": 14, "failures": 0},
 "capabilities": {"lookup_mail":  {"state": "ok", "checks": [{"date": "2026-10-05", "result": "ok"}], "until": null},
                  "lookup_teams": {"state": "suspect", "checks": [{"date": "2026-10-05", "result": "unavailable"}], "until": null}},
 "health": {"origin_mode": "none", "dead_sessions": [], "last_probe": "2026-10-05T10:15:20+09:00",
            "login_ok_at": "2026-10-05T10:15:40+09:00"},
 "env": {"tier": "premium", "work_toggle": "present", "work_mode": "work", "web_grounding": "unknown",
         "web_exposed": true, "evidence": ["toggle_present", "lookup_ok", "wg_missing"], "checked_at": "2026-10-05T10:15:42+09:00"}}
```

`profile_id` 는 프로필 폴더를 새로 만들 때 생성한다. 보정값의 키는 `(profile_id, model, edge_major)` 이다 — 계정·테넌트를 식별하는 정보를 쓰지 않으면서, 프로필을 새로 만들면 자동으로 다시 보정하게 된다.

### 4.11 계정 등급·업무 탭·웹 근거 판별 (`env.py`)

Copilot 이 사서함·Teams 를 근거로 쓸 수 있는지(계정 등급), 지금 업무(Work) 모드인지, 웹 검색 근거가 켜져 있는지를 매 호출 시작(`ensure_ready` 와 업무 모드 맞추기(§4.8) 직후, 첫 단계 전)에 한 번 판별한다. 판별은 **읽기만** 한다 — 업무 모드 전환 버튼만 `preferWorkMode` 에 따라 1회 누르고(§4.8), 웹 근거 토글은 계정 설정이므로 누르지 않으며 그 토글이 든 설정 메뉴도 열지 않는다.

```python
@dataclass
class CopilotEnv:
    tier: str            # "premium" | "basic" | "unknown"
    work_toggle: str     # "present" | "absent" | "unknown"
    work_mode: str       # "work" | "web" | "unknown"
    web_grounding: str   # "on" | "off" | "unknown"
    web_exposed: bool    # not (work_mode == "work" and web_grounding == "off")
    evidence: list[str]  # 코드만: toggle_present · toggle_absent · switch_failed · lookup_ok · nolic_reply · wg_on · wg_off · wg_missing
    checked_at: str      # ISO 시각(+09:00)
```

JS `/*LM27:env*/` 의 반환(페이지 글은 돌려주지 않는다):

```json
{"toggle": {"found": true, "work": true, "web": false}, "wg": {"found": false, "checked": null}}
```

- `toggle`: `dom.workModeLabels` 로 찾은 전환 요소. `work`·`web` 은 각 버튼의 `aria-pressed`·`aria-checked`·`aria-selected` 가 `"true"` 인가.
- `wg`: `dom.webGroundingLabels` 로 찾은 요소(스위치 `role=switch`, 체크 메뉴 항목 `role=menuitemcheckbox`, 체크박스). `checked` = `aria-checked` 또는 `checked` 값, 못 읽으면 `null`. 화면에 보이지 않으면(설정 메뉴 안) 찾지 못한 것으로 둔다.

```text
def detect_env(sess, caps) -> CopilotEnv:
    r = cdp.eval(js.env())                                       # 업무 모드 맞추기(§4.8)를 마친 뒤의 값
    if r.toggle.found:
        work_toggle = "present"
        work_mode = "work" if r.toggle.work else ("web" if r.toggle.web else "unknown")
        if work_mode == "web" and cfg.preferWorkMode: evidence.append("switch_failed")
    else:
        work_toggle = "absent" if sess.identity == "strong" else "unknown"   # 신원이 약하면 화면이 바뀐 것일 수 있다
        work_mode = "unknown"
    # 계정 등급은 화면 표기가 아니라 '실제로 조회가 됐는가'로 정한다(표기는 바뀌기 쉽다, Q21)
    if caps.any_ok_within(days=cfg.capability.ttlDays):              tier = "premium"    # lookup_ok
    elif caps.any_reason_within("R-NOLIC", days=cfg.capability.ttlDays): tier = "basic"  # nolic_reply
    else:                                                             tier = "unknown"
    if tier == "basic" and work_toggle != "present":
        work_mode = "web"                                        # 업무 탭 없는 무라이선스 = 웹 근거 전용
    web_grounding = ("on" if r.wg.found and r.wg.checked is True else
                     "off" if r.wg.found and r.wg.checked is False else "unknown")
    web_exposed = not (work_mode == "work" and web_grounding == "off")
    return CopilotEnv(tier, work_toggle, work_mode, web_grounding, web_exposed, evidence, now_iso())
```

판별 표(시제품 `proto_lm27.py` 로 6경우 확인, §11.6):

| 관찰 | tier | work_mode | web_grounding | web_exposed |
|---|---|---|---|---|
| 업무 탭 있음·업무 선택·웹 근거 끔 확인·조회 성공 이력 | premium | work | off | 거짓 |
| 위와 같은데 웹 근거 켜짐 | premium | work | on | 참 |
| 업무 선택·웹 근거 요소 못 찾음·이력 없음 | unknown | work | unknown | 참 |
| 업무 탭 없음·R-NOLIC 이력 | basic | web | unknown | 참 |
| 업무 탭 없음·이력 없음(첫 호출) | unknown | unknown | unknown | 참 |
| 업무 탭 있으나 전환 실패(웹 고정) | unknown | web | unknown | 참 |

쓰임:

1. `web_exposed` 이면 `bridge.webExposure.policy` 에 따라 엄격 규칙(§9.7) 또는 전송 차단(`skipped(reason=web_exposed)`, §7.16). 한 호출에서 BR-WEB-STRICT 또는 BR-WEB-BLOCK 을 1회 띄운다.
2. 조회 단계(§8.1)는 `work_mode == "web"` 이면 보내지 않는다(`skipped(reason=mode_web)`, BR-WEB-MODE). 계정 등급 `basic` 은 §7.13 능력 기록으로 `R-NOLIC` 이 확정되어 조회가 꺼진다(BR-NOLIC).
3. 분석 단계(화행·이름·라벨·리뷰·매칭·검토)는 등급과 무관하게 **프롬프트에 붙인 정제 텍스트만** 근거로 쓰도록 설계되어 있으므로(머리말이 혼자서 완결, §6.2) Basic 에서도 그대로 돈다. 다만 웹 노출이므로 엄격 규칙을 거친다.
4. 판별 결과는 `bridge_profile.json` 의 `env`(§4.10), `probe` 확인 항목 `tier`·`web_grounding`·`web_exposed`(§12.2), 결과 봉투의 `env`(§7.11), 계측 줄의 `web_exposed`(§5.9)에 남긴다. 계정·테넌트를 식별하는 정보는 쓰지 않는다.
5. 수동 경로(§10)는 화면을 읽지 못하므로 모든 값이 `unknown`, `web_exposed=true` 다.
6. 같은 호출 안에서 조회 단계가 `R-NOLIC` 이나 성공을 기록하면 `env` 의 `tier`·`work_mode`·`web_exposed` 를 즉시 다시 계산한다(화면은 다시 읽지 않는다). 그래서 뒤 단계의 판단과 결과 봉투의 `env` 가 그 호출의 마지막 관찰과 맞는다.

---

## 5. L1 전송 — 주입 검증·전송·회수·fail-closed 완료 판정

### 5.1 인터페이스

```python
class Transport(Protocol):
    kind: str                                  # "cdp" | "stub" | "manual"
    def open(self) -> str: ...                 # "ready" 또는 L1 단계(phase) 문자열
    def roundtrip(self, req: "SendRequest") -> "SendResult": ...
    def new_chat(self) -> bool: ...
    def close(self) -> None: ...

@dataclass(frozen=True)
class SendRequest:
    rid: str
    text: str                  # 게이트 통과 프롬프트(원문 저장 금지 — 메모리에만)
    fresh: bool                # 보내기 전에 새 채팅
    model: str                 # "" = 건드리지 않음
    reply_timeout_s: float
    first_token_s: float
    deadline: float            # clock.mono() 기준 절대 마감(질의 예산과 단계 예산의 작은 값)
    stage: str
    want_work_mode: bool

@dataclass
class SendResult:
    phase: str                 # §5.8 표
    body: str = ""             # 회수한 답(에코 제거). 실패여도 있는 만큼(복구 재료)
    done_by: str = ""          # "pledge" | "idle_json" | "stable" | ""
    pick: str = ""             # "dom" | "anchor" | "offset" | "fulltext" | "stub" | "manual"
    busy_seen: bool | None = None
    gen_sec: float = 0.0       # 전송 확인 ~ 완료
    first_token_sec: float | None = None
    in_chars: int = 0          # 보내려던 글자 수(정규화 후)
    injected_chars: int = 0    # 편집기에서 확인한 글자 수(정규화 후)
    resent: bool = False
    waited_idle_sec: float = 0.0
    model_note: str = ""
    model_used: str = ""
    work_mode: str = "unknown"
    chat_seq: int = 0
    error: str = ""            # 짧은 코드·예외 이름(페이지 원문 금지, 120자)
```

### 5.2 전송 1회 절차 (`CdpTransport.roundtrip`)

```text
def roundtrip(req):
    dl = Deadline(clock, req.deadline)
    st = session.ensure_ready(dl)                              # §4.7
    if st != "ready": return SendResult(phase=st)
    activate(tab)
    if req.fresh: new_chat()                                  # §5.7
    if req.want_work_mode: session.ensure_work_mode()          # §4.8
    note = session.select_model(req.model)                     # 채팅마다 1회
    waited = wait_idle(min(cfg.waitIdleSec, dl.left()))        # 앞 답 생성 중이면 기다림
    if still_generating: return SendResult(phase="busy_before_send", waited_idle_sec=waited)
    base = snapshot()                                          # {n_user, n_asst, page_len} — §5.5
    r = inject(req.text, dl)                                   # §5.3
    if r.phase != "ok": return SendResult(phase=r.phase, in_chars=r.want, injected_chars=r.got)
    s = send_and_confirm(req.text, base, dl)                   # §5.4
    if s.phase != "sent": return SendResult(phase=s.phase, …)
    return wait_complete(req, base, dl, note, s.resent, waited)   # §5.6
```

모든 대기는 `dl.left()` 로 자른다(LM24 `_RT_DEADLINE`·`_dl_left` 의 일반화). 모든 `sleep` 은 주입된 `clock.sleep` 이다.

### 5.3 주입과 주입 검증

```text
def norm(s):    # 비교용 정규화(저장하지 않음)
    s = s.replace("\r\n", "\n").replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()

def inject(text, dl):
    ins = poll(js.focus_input, until=ok, up_to=min(cfg.readyWaitSec, dl.left()))     # 입력창 포커스(§5.3.1)
    if not ins.ok: return Phase("input_not_found")
    clear_editor()                                             # 남은 글자 제거(Ctrl+A, Backspace) 후 비었는지 확인
    cdp.call("Input.insertText", {"text": text})               # 1차: IME/붙여넣기 수준 — 리치 에디터가 정상 수신
    sleep(0.4)
    got, want = norm(js.editor_text()), norm(text)
    if not match(got, want):
        clear_editor(); cdp.eval(js.insert_fallback(text)); sleep(0.4)   # 2차: execCommand → value+input 이벤트
        got = norm(js.editor_text())
    if match(got, want): return Phase("ok", want=len(want), got=len(got))
    clear_editor()                                             # 어긋난 글은 절대 보내지 않는다
    if len(got) < len(want) - 2 and want.startswith(got[:200]):
        return Phase("input_overflow", want=len(want), got=len(got))   # 입력 한도에서 꼬리가 잘림
    return Phase("inject_mismatch", want=len(want), got=len(got))

def match(got, want):
    return abs(len(got) - len(want)) <= 2 and got[-32:] == want[-32:]
```

- LM24 는 앞 15자만 확인해서 입력 한도에서 꼬리가 잘려도 그대로 보냈다(조사 pitfall). LM27 은 **길이 + 꼬리 32자**를 확인하고, 어긋나면 보내지 않는다.
- `input_overflow` 는 L2 에서 `truncated(side=input)` 가 되어 L3 가 입력 예산을 `got × calibSafety` 로 낮추고 다시 패킹한다(§7.5).

#### 5.3.1 입력창 찾기 (`/*LM27:focus_input*/`)

`inputSelectors` 순서로 보이는 요소(`width>40 && height>8 && !disabled`)를 찾는다. 후보가 여럿이면 `inputAriaLabels` 와 aria-label 이 맞는 것을 우선한다. 찾은 요소를 `window.__lm_input` 에 두고, **작성 영역**(`composer`) = `el.closest("form")` 또는 위로 6단계 안에서 버튼을 품은 첫 조상을 `window.__lm_composer` 에 둔다. 전송 버튼과 중지 버튼은 이 영역 안에서 먼저 찾는다.

### 5.4 전송과 전송 확인

```text
def send_and_confirm(text, base, dl):
    click = js.click_send()            # composer 안에서 sendLabels aria-label 일치 + 보임 + !disabled
    if not click.ok: press_enter()     # LM24 유지: Input.dispatchKeyEvent rawKeyDown/char/keyUp
    if sent_within(3s, base, text): return Phase("sent")
    # 클릭이 '중지' 버튼에 먹혔거나 무시됨 — 프롬프트가 입력창에 그대로 남아 있다(LM24 실측)
    wait_idle(min(30, dl.left()))
    click = js.click_send() or press_enter()
    if sent_within(3s, base, text): return Phase("sent", resent=True)
    clear_editor()
    return Phase("send_failed")

def sent_within(sec, base, text):
    # 둘 중 하나면 전송됨: (a) 편집기가 비었다(norm 길이 < 5), (b) 사용자 메시지 노드 수가 늘었다
    poll every 0.5s up to sec: e = norm(js.editor_text()); s = snapshot()
        if len(e) < 5 or s.n_user > base.n_user: return True
    return False
```

LM24 의 범용 전송 선택자(`button[type='submit']` 전역)는 쓰지 않는다. 엉뚱한 화면의 '보내기'를 누를 위험이 있기 때문이다(조사 discard).

### 5.5 회수 — DOM 1차, 앵커 폴백

**스냅샷** `/*LM27:poll*/` 은 한 번의 평가로 다음을 돌려준다(폴링 비용 절감):

```json
{"gen": true, "n_user": 3, "n_asst": 3, "last": "<마지막 답 노드 innerText, 60,000자 상한>", "sel": "learned"}
```

- `gen`: 중지 버튼 존재. composer 안 → 없으면 문서 전체에서 `stopLabels` 검사. composer 를 못 찾으면 `null`. **이 값은 fail-open 이다**(못 찾으면 '생성 중 아님'). 그래서 완료 쪽 결정에 단독으로 쓰지 않는다(§5.6).
- `n_asst`·`last`: 답 노드 선택자 = `dom.assistantSelectors`(설정) → 학습값(`bridge_profile.dom.assistant_sel`) → 없음. 선택자가 없으면 `n_asst=-1`, `last=""` 이고 앵커 폴백을 쓴다.
- **몸통(body)** = DOM 경로: `n_asst > base.n_asst` 일 때 `last`, 아니면 `""`(아직 새 답 없음). 폴백 경로: `/*LM27:chat_text*/`(main 의 innerText)에서 LM24 `build_anchor`·`pick_reply`·`strip_echo` 로 자른다(`pick` = `anchor`/`offset`/`fulltext`).

**답 노드 선택자 학습**(`probe`·`calibrate`·첫 전송에서 자동):

```text
def learn_assistant_selector(pledge, prompt_head15):
    # JS /*LM27:learn_asst*/: innerText 에 pledge 를 포함하고 prompt_head15 는 포함하지 않는 요소 중
    # innerText 가 가장 짧은 요소를 고르고, 그 요소 또는 조상(최대 6단계) 중 다음 안정 속성을 가진 첫 노드의 선택자를 만든다:
    #   [data-testid=…] → [data-message-author-role=…] → [role='article'][aria-roledescription] → 태그+클래스 토큰(숫자 없는 것 2개)
    # 그 선택자로 querySelectorAll 했을 때 마지막 노드가 pledge 를 포함해야 채택.
    sel = cdp.eval(js.learn_asst(pledge, prompt_head15))
    if sel.ok: save(dom.assistant_sel = sel.selector, verified=1)
```

- 학습값으로 회수한 답에서 서약을 못 찾았는데 같은 전송의 폴백 경로에서는 찾으면 `dom.failures += 1`. 2회 누적이면 학습값을 지우고 다음 서약 답에서 다시 학습한다.
- 학습은 페이지 구조(속성 이름)만 쓰고 텍스트를 저장하지 않는다.

### 5.6 완료 판정 (fail-closed)

시제품(§11.6)으로 확인한 규칙이다. 폴 주기 `pollSec`(3초).

```text
def wait_complete(req, base, dl, note, resent, waited):
    t0 = clock.mono(); last = None; same = 0; idle = 0; busy_seen = False; gens = []
    first_tok = None
    pledge_re = re.compile(r"(?:\[\[|<<)\s*END\s+" + req.rid + r"\s*(?:\]\]|>>)")
    end = min(t0 + req.reply_timeout_s, dl.at)
    while clock.mono() < end:
        clock.sleep(cfg.pollSec)
        snap = poll_snapshot()                                 # 시간 초과 시 reconnect 후 continue (LM24 유지)
        body = current_body(snap, base)                        # §5.5
        gen = snap.gen                                         # True | False | None
        if gen: busy_seen = True
        gens.append(gen)
        el = clock.mono() - t0
        if body.strip() and first_tok is None: first_tok = el
        # ① 서약: 몸통(DOM) 또는 에코를 뺀 몸통(폴백)에 이번 rid 의 서약이 있다
        if pledge_in(body, req, pick):                         # 폴백은 echo 몫을 빼고 센다(LM24 echo_sentinels 일반화)
            clock.sleep(1.0); body = current_body(poll_snapshot(), base) or body   # 렌더 꼬리 1회 더
            return done("pledge", body)
        b = body.strip()
        if not b:
            same = 0; idle = 0
            # 첫 글자 전 '생각' 구간은 멈춘 것이 아니다. 유예가 지나고 생성 중도 아니면 empty
            if el >= req.first_token_s and gen is not True:
                return SendResult(phase="empty_reply", busy_seen=busy_seen, gen_sec=el)
            last = body; continue
        same = same + 1 if body == last else 0
        started, parsed = envelope_state(body, req.rid)        # '{"rid"' 가 보이는가 / 엄격 json 파싱 + rid 일치인가
        # ② idle_json: 이 전송에서 중지 버튼을 본 적이 있고, 지금 2폴 연속 사라졌고, 몸통이 그대로이며, 봉투가 실제로 파싱된다
        idle = idle + 1 if (busy_seen and gen is False and same >= 1) else 0
        if idle >= 2 and parsed:
            return done("idle_json", body)
        # ③ stable: 몸통이 N폴 연속 같고 그 동안 gen 이 True 인 적이 없다.
        #    봉투가 시작됐는데 파싱이 안 되면(잘린 JSON 꼴) N × incompleteJsonFactor 폴을 요구한다
        need = cfg.stablePolls * (cfg.incompleteJsonFactor if (started and not parsed) else 1)
        if same >= need and all(g is not True for g in gens[-(same + 1):]):
            return done("stable", body)
        last = body
    return SendResult(phase="no_reply", body=(last or ""), busy_seen=busy_seen, gen_sec=clock.mono() - t0)
```

| 판정기 | 실패 방향 | 쓰는 곳 |
|---|---|---|
| 서약 `[[END rid]]` | 닫힘(서약 없으면 완료 아님) | 완료 ① |
| `gen`(중지 버튼) | **열림**(못 찾으면 False) | 단독 사용 금지. ② 는 `busy_seen` 게이트 + 실제 JSON 파싱과 묶고, ③ 는 'True 가 아님'만 요구 |
| 엄격 JSON 파싱 + rid 일치 | 닫힘 | ② 의 필수 조건 |
| 몸통 불변 N폴 | 닫힘(시간 기반) | ③ |
| 괄호 개수 비교(LM24 `_looks_closed`) | 열림(문자열 안의 `}` 에 속음, 조사 probe2) | **폐기** |

`stable` 로 끝난 답이 실제로는 잘렸다면(긴 생각 멈춤 + 버튼 숨김, 시제품 G 시나리오) L2 가 `truncated` 로 분류해 살린 항목만 커밋하고 빠진 항목을 다시 묻는다. 손실은 '왕복 1회 추가'로 제한된다.

### 5.7 새 채팅

```text
def new_chat():
    activate(tab)
    r = cdp.eval(js.new_chat())                                # newChatLabels 버튼(보이는 첫 것) 클릭
    if r.ok and poll(lambda: snapshot().n_user == 0, up_to=10s): ok
    else: navigate(own_tab, cfg.url); poll_identity(20s)       # URL 재진입(같은 탭)
    session.chat_seq += 1; chat_turn = 0
    activate(tab)
```

### 5.8 L1 단계(phase) 표

| phase | 뜻 | L2 상태(§6.6) |
|---|---|---|
| `replied` | 답 회수(완료 판정 ①②③ 중 하나) | 내용으로 분류 |
| `no_reply` | 답 대기 시간 초과(있는 몸통 반환) | 내용이 있으면 `truncated`, 없으면 `timeout` |
| `empty_reply` | 유예 뒤에도 몸통 없음 | `empty` |
| `input_overflow` | 입력 한도에서 꼬리 잘림(보내지 않음) | `truncated(side=input)` |
| `inject_mismatch` | 편집기 글이 프롬프트와 다름(보내지 않음) | `format(reason=inject_mismatch)` |
| `busy_before_send` | 앞 답이 계속 생성 중 | `service_error` |
| `send_failed` | 두 번 눌러도 전송 안 됨 | `service_error` |
| `cdp_error` | CDP 예외(재연결 1회 뒤에도) | 세션 건강 확인 → 살아 있으면 `service_error`, 죽었으면 `transport_fatal(tab_lost)` |
| `login_required`·`dead_session`·`input_not_found`·`wrong_tab`·`tab_lost` | 세션 상태 문제 | `transport_fatal` |
| `edge_not_found`·`launch_failed`·`policy_blocked`·`port_exhausted`·`profile_busy`·`lock_busy` | 기동 문제 | `transport_fatal` |
| `stub` | 스텁 답 | 내용으로 분류 |
| `manual_pending` | 수동 경로: 프롬프트 파일을 내보냄, 답 대기 | L3 가 단계를 `manual_wait` 로 멈춤 |

### 5.9 전송 계측

`trace.jsonl` 한 줄(원문 없음, LM24 `_traced` 의 확장):

```json
{"t": "2026-10-05T10:21:44+09:00", "run": "20261005-101500-3fa2", "stage": "task_label", "seq": 17, "rid": "R7F3QK",
 "rung": 0, "fresh": false, "chat_seq": 3, "chat_turn": 5, "phase": "replied", "status": "partial",
 "sec": 64.2, "gen_sec": 58.1, "first_token_sec": 12.0, "in": 7480, "injected": 7480, "reply": 4620,
 "done_by": "pledge", "pick": "dom", "busy_seen": true, "resent": false, "waited": 0.0,
 "model_wanted": "빠른 응답", "model_used": "빠른 응답", "work_mode": "work", "web_exposed": true}
```

---

## 6. L2 교환 — rid 봉투·검증·상태 분류·사다리

### 6.1 rid

- 형식: `R` + 5자, 글자판 `23456789ABCDEFGHJKMNPQRSTVWXYZ`(헷갈리는 0·1·I·L·O·U 제외). 정규식 `R[2-9A-HJ-NP-TV-Z]{5}`. 예: `R7F3QK`.
- `secrets.choice` 로 만들고, 한 실행에서 쓴 rid 집합과 겹치면 다시 뽑는다.
- **전송마다 새 rid**(사다리 재전송도 새 rid). 그래서 앞 전송의 늦은 답·다른 채팅의 답·지난 실행의 답을 기계적으로 거른다.

### 6.2 프롬프트 골격 (모든 단계 공통, 글자 그대로)

```text
[LM27 요청 {rid} · {title_ko} · 항목 {n}개]
{역할 1~3줄}                                   ← 단계 머리말(§8)
{규칙 줄들}
{참고 목록: 레지스트리·어휘·카탈로그}          ← 단계 context_block (축약 가능)
[앞서 쓴 이름] {이름 / 이름 / …}               ← 있을 때만(§7.4)
[참고 — 이미 처리한 항목, 답하지 마세요]        ← 겹침, 있을 때만(§7.4)
{참고 줄들}
[항목] {열 이름 | …}
1 | …
2 | …
[답 형식]
- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다. 코드 블록 밖에는 설명을 쓰지 않습니다.
- rid 에는 "{rid}" 를, n 에는 items 의 개수를 씁니다. 항목 번호 1~{n} 을 빠짐없이 한 번씩, 번호 순서대로 씁니다.
- 문자열 값은 큰따옴표로 감싸고 값 안에서 줄을 바꾸지 않습니다.
- 근거가 부족하면 지어내지 말고 {unknown_rule}.
- 사람 이름·전화번호·메일 주소·금액은 쓰지 않습니다. [전화]·[금액]·[사람] 같은 꺾쇠 표기는 가려진 값입니다.
{no_web_rule}                                  ← 조회 단계가 아닐 때만 한 줄
- 형식(<…> 자리에 실제 값): {format_line}
- 코드 블록이 끝나면 맨 마지막 줄에 [[END {rid}]] 만 씁니다.
```

- `format_line` 은 단계가 준다. 자리표시자는 `<…>` 로 써서 **예시 자체가 유효한 JSON 이 아니게** 한다(LM24 실측: 회수가 어긋나 예시가 답으로 저장된 사고의 방어). 예: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack|…>, "conf": <h|m|l>} ]}`.
- 프롬프트에 서약 문자열은 **딱 1번**(마지막 줄 지시) 나온다. DOM 경로에서는 사용자 메시지 노드가 따로라 에코가 문제되지 않고, 앵커 폴백에서는 에코 몫(앵커 뒤 프롬프트 꼬리의 서약 수)을 빼고 센다.
- 머리말은 질의마다 **전부** 싣는다(혼자서 완결). LM24 '계속입니다' 이어짐 프롬프트가 새 채팅에 떨어져 답이 엉킨 사고 때문이다.
- `no_web_rule`: 조회 단계(`kind="lookup"`)가 아니면 `- 웹 검색을 하지 말고 이 메시지에 적힌 내용만으로 답합니다.` 한 줄을 넣고, 조회 단계는 줄 자체를 뺀다(조회는 사서함·Teams 근거를 써야 한다). 웹 근거가 켜진 계정에서 프롬프트 글이 검색어로 나가는 일을 줄이려는 지시일 뿐이며, 막는 장치는 §9.7 엄격 규칙이다.

### 6.3 조립과 줄 지도

```python
@dataclass
class Assembled:
    text: str
    rid: str
    item_ids: list[int]          # 1..n
    id_to_key: dict[int, str]    # 프롬프트 번호 → 항목 key
    line_spans: dict[int, tuple[int, int]]   # 항목 번호 → text 안 (시작, 끝) 오프셋 — 게이트 적중 위치를 항목에 연결
    header_span: tuple[int, int] # 머리말·참고 목록 구간(여기 적중하면 단계 설정 문제)
    in_chars: int
```

### 6.4 답에서 봉투 꺼내기 (`jsonx.extract`)

```text
def extract(reply, rid) -> Extracted(kind, obj, how, cut, pledge):
    pledge = re.search(PLEDGE(rid), reply) is not None
    t, cut = normalize(reply)
        # normalize: ① 꼬리 400자 안의 '생성 중단' 문구(STOP_MARKS) 위치에서 자르고 cut=True
        #            ② 코드펜스 ```json / ``` 제거  ③ 굽은 따옴표 “ ” „ ‟ ＂ → "
        #            ④ 모든 서약 [[END R…]] / <<END R…>> 를 줄바꿈으로 치환
    cands = []                                            # 뒤에서부터 '{' 를 거슬러 raw_decode, 'rid' 키 있는 dict 만(최대 600 시도)
    mine = [c for c in cands if upper(strip(c.rid)) == rid]
    if mine: return ("env", mine[0], "strict", cut, pledge)          # 가장 뒤의 것
    for m in reversed(finditer(r'\{\s*"rid"\s*:', t)):             # 잘린 봉투 복구
        o = close_truncated(t, m.start(), list_key="items")
        if o and upper(o.rid) == rid: return ("env", o, "salvaged", cut, pledge)
    if cands:
        return ("stale" if re.fullmatch(RID_RE, cands[0].rid) else "echo", cands[0], …)
    if "<요청번호>" in t or "<번호>" in t: return ("echo", None, …)   # 예시 골격 에코
    return ("none", None, "", cut, pledge)
```

`close_truncated`(LM24 `judge._close_truncated` 일반화): 문자열·이스케이프 상태를 추적하며 최상위 객체를 훑고, `items` 목록(깊이 2)의 **마지막 완전한 원소** 뒤에서 `]}` 로 닫아 `json.loads`. 원소가 하나도 완전하지 않으면 `"items": [` 직후에서 닫아 rid·n 만이라도 얻는다. 괄호 개수 근사는 쓰지 않는다.

> 시제품 확인(§11.6): `{"rid":"R7F3QK","n":3,"items":[{"id":1,…},{"id":2,"act":"report","note":"설계안} 검토 후 B` 처럼 문자열 안에 `}` 가 있는 잘린 답에서 항목 1 만 정확히 살리고 `truncated` 로 분류한다.

### 6.5 항목 검증 — 필드 명세 언어

표준 라이브러리만 쓰므로 작은 명세 언어를 둔다(`stages/base.py`).

```python
@dataclass(frozen=True)
class F:
    name: str
    kind: str                     # "str" | "int" | "bool" | "enum" | "code" | "list" | "obj" | "nullable_obj"
    required: bool = True
    enum: tuple = ()              # kind == "enum"
    codes: str = ""               # kind == "code": ctx 의 허용 코드 집합 이름(예 "projects", "vocab.field", "catalog")
    extra_codes: tuple = ()       # code 에 더해 허용하는 값(예 ("NONE", "NEW"))
    max_len: int = 0              # str: 초과 시 잘라 쓰고 표식 trunc(거부 아님). 0 = 무제한
    hard_max: int = 0             # str: 이 길이를 넘으면 거부(too_long). 0 = 없음
    min_len: int = 0              # str: 미만이면 거부(too_short)
    max_items: int = 0            # list: 초과분은 버리고 caps_hit 기록
    item: tuple = ()              # list/obj 의 하위 F 들
    pattern: str = ""             # str: fullmatch 정규식(불일치 → bad_pattern)
```

검증 순서(항목 하나):
1. `id` 를 `int(str(id).strip())` 로 읽는다. 실패 → `extra`(셈만). 요청 번호 집합 밖 → `extra`. 이미 본 번호 → `dup`(첫 것만 채택).
2. **시간형 키 거부**: 키 이름이 `(?i)^(start|end|begin|finish|time|date|datetime|hours?|minutes?|mins?|mm|man_?month|duration|effort|lead_?time)$` 이면 그 항목은 `forbidden_field` 로 무효(B1). 조회 단계(`lookup_*`)만 예외(`allow_time=True`, 자기 스키마의 `t`·`st`·`en` 필드).
3. 명세에 없는 다른 키 → 버리고 `extra_fields` 셈.
4. 각 `F` 검사 → 실패하면 사유 코드(`missing:<f>`, `bad_enum:<f>`, `unknown_code:<f>`, `too_long:<f>`, `too_short:<f>`, `bad_pattern:<f>`)로 항목 무효.
5. 단계 `validate(ans, item, ctx)` 추가 검사(단계 간 일관성 — 예: `project=="NEW"` 이면 `new` 필수).
6. 단계 `normalize(ans, item, ctx)`: NFKC, 앞뒤 공백·따옴표 제거, 긴 글 자르기(`…`), 금지 표현 제거(예: 리뷰 문장의 시간 수치), 입수 정제(§9.3 ③).

### 6.6 상태 분류 (`exchange.classify`) — 시제품으로 확인한 순서

| 순서 | 조건 | 상태 | 세부 사유 |
|---|---|---|---|
| 0 | L1 phase = `manual_pending`(수동 경로가 프롬프트 파일을 내보냄) | `manual_pending` | 내부 상태 — 분류·행동 없음, 답은 반입 때 같은 표로 분류(§10.4) |
| 1 | L1 phase ∈ 세션·기동 문제(§5.8) | `transport_fatal` | phase 그대로 |
| 2 | phase = `input_overflow` | `truncated` | `side=input` |
| 3 | phase = `inject_mismatch` | `format` | `inject_mismatch` |
| 4 | phase = `empty_reply` | `empty` | |
| 5 | phase ∈ {`busy_before_send`, `send_failed`} 또는 살아 있는 세션의 `cdp_error` | `service_error` | phase |
| 6 | phase = `no_reply` 이고 몸통 비었음 | `timeout` | |
| 7 | 몸통 < 500자이고 앞 300자에 `ERROR_MARKS`(LM24 유지) | `service_error` | `error_reply` |
| 8 | 봉투(이번 rid) 있음 → 검증(§6.5). (a) `how=salvaged` 또는 `cut` 또는 phase=`no_reply` | `truncated` | `side=output` |
| 8b | (b) 유효 항목 0개 | `format` | `no_valid_items` |
| 8c | (c) 빠진 번호 또는 무효 항목 있음 | `partial` | |
| 8d | (d) 그 밖 | `ok` | `dup`·`extra` 는 셈만 |
| 9 | 봉투 없음, 다른 rid 의 봉투 | `echo` | `stale` |
| 10 | 봉투 없음, 예시 골격·자리표시자 | `echo` | `example` |
| 11 | 조회 단계이고 `UNAVAILABLE_MARKS`(조회 도구 없음·권한 없음 등) | `refusal` | `unavailable` |
| 12 | `REFUSAL_MARKS`(도와드릴 수 없·답변드릴 수 없·I can't help with …) | `refusal` | `policy` |
| 13 | phase = `no_reply` | `timeout` | |
| 14 | 몸통 빔 | `empty` | |
| 15 | 그 밖 | `format` | `no_envelope` |

조회 단계(`kind="lookup"`)는 요청 번호 집합이 없으므로 8 을 다음으로 바꾼다: 잘림이면 `truncated`, `n != len(items)` 면 `partial`, 그 밖은 `ok`(`n=0`, `items=[]` 도 정상 = '그 기간 0건').

### 6.7 행동표 (한 벌)

L2 는 질의 1건 안에서 **같은 묶음을 다시 보내는** 것까지만 하고, 묶음을 바꾸는 일(반분·재질의·연기)은 L3 가 한다.

| 상태 | L2 (질의 안) | L3 (질의 뒤) | 서킷 0건 셈 | 항목 질문 횟수 +1 |
|---|---|---|---|---|
| `ok` | 끝 | 전부 커밋 | 초기화 | 아니오 |
| `partial` | 끝 | 유효 항목 커밋, 빠진·무효 항목 재큐(무효 사유를 다음 질의 머리말 끝에 '주의' 1줄로) | 커밋 > 0 이면 초기화 | 빠진·무효 항목만 |
| `truncated(output)` | 끝 | 살린 항목 커밋, 나머지 재큐, 다음 질의는 **새 채팅**, 같은 단계에서 2회째면 답 예산 × 0.8(하한 1,500) | 커밋 > 0 이면 초기화 | 나머지 항목 |
| `truncated(input)` | 끝 | 커밋 없음. 입력 예산 = `injected × calibSafety`(하한 2,000)로 낮추고 전부 재패킹 | 셈 안 함 | 아니오 |
| `echo` | 새 채팅에서 1회 재전송(새 rid) | 그래도 `echo` 면 반분 | +1 | 예 |
| `format` | 새 채팅에서 1회 재전송(새 rid, 형식 지시 끝에 '반드시 JSON 코드 블록 하나' 1줄 추가) | 그래도 `format` 이면 반분 | +1 | 예 |
| `empty` | 사다리 1단 → 2단(예산 안에서) | 그래도 `empty` 면 반분 | +1 | 예 |
| `service_error` | 사다리 1단 → 2단 | 그래도면 묶음을 큐 **뒤로 연기**(1회), 두 번째면 반분 | +1 | 예 |
| `timeout` | 끝(사다리 없음 — 이미 대기 상한을 다 씀) | 반분 | +1 | 예 |
| `refusal(policy)` | 단계 `rephrase` 가 있으면 화법을 바꿔 새 채팅 1회 | 그래도면 그 항목들 `ai_refused` → 규칙 폴백 커밋 | 셈 안 함 | — |
| `refusal(unavailable)` | 조회 단계: `rephrase`(검색형 화법) 1회 | 능력 기록(§7.13), 이 실행의 그 조회 단계 중지(`stop_kind=refused`) | 셈 안 함 | — |
| `transport_fatal` | 끝 | 조건 폴링 → 2-strike(§7.7) | 셈 안 함 | 아니오 |

**재시도 사다리**(LM24 `run_roundtrip` 이식·일반화):

| 단 | 채팅 | 모델 | `reply_timeout_s` | `first_token_s` |
|---|---|---|---|---|
| 0 | 채팅 정책(§6.9) | 단계 등급 모델 | `replyTimeoutSec`(480) | `firstTokenSec`(180) |
| 1 | 새 채팅 | 단계 등급 모델 | max(120, 0단 ÷ 2) | max(30, 0단 ÷ 2) |
| 2 | 새 채팅 | `modelFallback` | 1단과 같음 | 1단과 같음 |

각 단의 대기는 다시 `min(…, 질의 마감 − 60초)` 로 자른다. 질의 마감까지 `minAskSec`(120초) 미만이 남으면 다음 단을 건너뛴다. soft 서킷(§7.6) 상태에서는 2단을 쓰지 않는다.

### 6.8 `ask()` 의사코드

```python
@dataclass
class AskResult:
    status: str                       # §6.6 의 10종 + 내부 상태 manual_pending(수동 경로로 내보냄, 답 대기)
    reason: str
    answers: dict[int, dict]          # 프롬프트 번호 → 정규화된 답(커밋 후보)
    missing: list[int]
    invalid: dict[int, str]           # 번호 → 사유 코드
    dup: int; extra: int; extra_fields: int
    rids: list[str]                   # 이 질의에서 보낸 rid 들(사다리 포함)
    sends: int; rung: int
    done_by: str; pick: str; sec: float
    transport_phase: str
    model_used: str; work_mode: str
    gate: dict                        # {"dropped": n, "hits": {유형: 건수}}
    in_chars: int; reply_len: int
    side: str                         # truncated 의 input|output
    injected_chars: int

def ask(spec, batch, ctx) -> AskResult:
    deadline = min(clock.mono() + cfg.roundtripMaxSec, ctx.stage_deadline)
    rung, resent_fmt, rephrased, deferred_note = 0, False, False, ctx.notes_for(batch)
    fresh = ctx.chat.need_fresh(spec)                      # §6.9
    while True:
        rid = new_rid(ctx.used_rids)
        asm = assemble(spec, batch, ctx, rid, rephrase=rephrased, strict_format=resent_fmt, note=deferred_note)
        g = gate_prompt(asm)                              # §9.3 ② — 실패면 StageGateError(전송하지 않고 단계 중지)
        req = SendRequest(rid, asm.text, fresh=fresh or rung > 0, model=model_for(spec, rung),
                          reply_timeout_s=timeouts(rung)[0], first_token_s=timeouts(rung)[1],
                          deadline=deadline, stage=spec.id, want_work_mode=spec.want_work_mode)
        journal.req(spec, ctx, asm, rung, req, g)
        res = transport.roundtrip(req)
        if res.phase == "manual_pending":                    # 수동 경로: 답은 나중에 반입(§10.4)
            journal.req_exported(spec, ctx, asm); return AskResult(status="manual_pending", transport_phase=res.phase, …)
        status, info = classify(spec, res, asm)
        journal.resp(spec, ctx, asm, rung, res, status, info)
        trace.write(…)
        ctx.chat.after_send(status, fresh=req.fresh)
        if rawcapture_on: rawcap.write(asm.text, res.body)   # 게이트 통과본, TTL
        if status in ("ok", "partial", "truncated", "timeout", "transport_fatal"):
            return result(status, info, …)
        if status == "refusal":
            if not rephrased and spec.has_rephrase():
                rephrased = True; fresh = True; continue
            return result(status, info, …)
        if status in ("echo", "format"):
            if not resent_fmt and left(deadline) >= cfg.minAskSec:
                resent_fmt = True; fresh = True; continue
            return result(status, info, …)
        if status in ("empty", "service_error"):
            max_rung = 1 if ctx.circuit_soft else 2
            if rung < max_rung and left(deadline) >= cfg.minAskSec:
                rung += 1; continue
            return result(status, info, …)
```

### 6.9 채팅 정책

| 단계 `chat_policy` | 새 채팅을 여는 때 |
|---|---|
| `continue` (분류·라벨 단계) | 단계의 첫 질의 / 직전 질의가 `ok`·`partial` 이 아님 / 같은 채팅의 질의 수가 `chatTurns` 에 닿음 / `chatTurns == 0` |
| `fresh_each` (조회·리뷰) | 질의마다 |

같은 채팅에서 이어 보내는 이유는 앞 묶음에서 쓴 이름을 Copilot 이 기억해 표기가 덜 흔들리기 때문이다(LM24 실측). 서로 독립인 요청(월별 리뷰·조회)을 앞 대화가 남은 채팅에서 보내면 다른 달의 내용이 섞인다(LM24 실측 사고) — 그래서 항상 새 채팅이다.

---

## 7. L3 배치 실행기 — 모든 단계 공용 한 벌

### 7.1 자료구조

```python
@dataclass
class WorkItem:
    key: str
    group: str
    fields: dict                 # send_fields 만 남긴 것
    rule: dict                   # 폴백 재료(보내지 않음)
    ck: str                      # 내용 키(§7.9)
    asks: int = 0                # 이 항목을 물은 횟수(이번 실행)
    notes: list[str] = field(default_factory=list)   # 직전 무효 사유(다음 질의 '주의' 줄)

@dataclass
class Pinned:                    # 반분으로 만든 '묶음 고정' 단위
    items: list[WorkItem]
    depth: int
    deferred: int = 0

@dataclass
class StageRun:
    spec: "StageSpec"
    run_id: str
    pending: deque[WorkItem]     # 일반 대기열(단계 순서)
    pinned: deque[Pinned]        # 앞에서 먼저 처리
    committed: set[str]          # 이번 실행에서 커밋한 ck
    pack_in: int                 # 현재 입력 예산
    pack_out: int                # 현재 답 예산
    zero_streak: int = 0
    circuit_soft: bool = False
    fatal_strikes: int = 0
    trunc_out_count: int = 0
    stats: Counter
    caps_hit: Counter
    deadline: float              # 단계 마감(mono)
```

### 7.2 예산 정하기

```text
calib = calibration.current(profile_id, model_for(spec, 0), edge_major)    # 유효기간 안의 최신
pack_in  = clamp(calib.pack_in  if calib else cfg.inputMaxChars,  2000, 20000)
pack_out = clamp(calib.pack_out if calib else cfg.answerMaxChars, 1500, 12000)
pack_out = int(pack_out * runtime_adjust.get(spec.id, 1.0))                  # 지난 실행의 적응값(§7.12)
```

### 7.3 패킹

```text
def next_batch(run) -> Pinned | list[WorkItem] | None:
    if run.pinned: return run.pinned.popleft()
    if not run.pending: return None
    hdr = spec.header(ctx, compact=False) + footer_len(spec)
    ctxb = context_block(run)                                   # 앞서 쓴 이름 + 겹침(§7.4)
    room = run.pack_in - len(hdr) - len(ctxb)
    if room < run.pack_in * 0.25:                               # 목록이 너무 길다 — 축약 머리말
        hdr = spec.header(ctx, compact=True) + footer_len(spec); room = run.pack_in - len(hdr) - len(ctxb)
        if room < run.pack_in * 0.25: raise StageConfigError("header_too_large")   # 단계 중지, BR-HEADER
    batch, used_in, used_out = [], 0, ENVELOPE_OVERHEAD(80) + spec.est_out_fixed
    cur_group = None
    while run.pending and len(batch) < spec.max_items:
        it = run.pending[0]
        line = spec.item_line(it, len(batch) + 1)
        if len(line) > room:                                    # 항목 하나가 예산보다 크다
            line = spec.shrink(it, room)                        # 단계별 필드 축약 사다리
            if line is None:
                run.pending.popleft(); commit_rule(it, "oversize"); run.caps_hit["oversize"] += 1; continue
        out = spec.est_out(it)
        if batch and (used_in + len(line) + 1 > room or used_out + out > run.pack_out): break
        if batch and spec.group_strict and it.group != cur_group and not group_fits(run, it.group, room - used_in):
            break                                               # 묶음 경계에서 끊는다(같은 과제는 한 질의에)
        run.pending.popleft(); batch.append(it); used_in += len(line) + 1; used_out += out; cur_group = it.group
    return batch
```

- 다부 분할(긴 프롬프트를 여러 메시지로 나눠 보내기)은 **쓰지 않는다**. 패킹이 한도를 보장하고, 한 항목이 너무 크면 필드를 줄인다(`shrink`). LM24 `make_parts`·`_run_parts` 의 왕복 2배·조기 분석 위험을 없앤다.
- `est_out(it)` = 단계 상수(`est_out_per_item`) 또는 항목 크기 함수(워크플로우는 단계 수에 비례). 실행 중 실제 평균 답 길이를 지수 이동 평균(α = 0.3)으로 갱신해 `est_out_per_item` 을 보정한다(하한 = 설계값의 0.7배, 상한 = 2배).

### 7.4 겹침과 '앞서 쓴 이름'

- **앞서 쓴 이름**: 단계가 `names_field`(예: `title`, `label`)를 정의하면, 이번 실행과 저장소의 커밋 답에서 그 필드를 빈도순으로 모아 `seenNamesMax`(30)개·`seenNamesChars`(600자) 안에서 ` / ` 로 잇는다. 같은 일을 같은 이름으로 부르게 하는 장치(LM24 judge·refine 실측).
- **겹침**: 직전 묶음의 마지막 `overlapItems`(3)개 항목을 `[참고 — 이미 처리한 항목, 답하지 마세요]` 아래에 `항목 줄 + → 답한 이름` 형태로 `overlapChars`(600자) 안에서 싣는다. 번호를 매기지 않으므로 답 예산을 쓰지 않는다.

### 7.5 반분·재질의·연기

```text
def after_ask(run, batch, depth, ar: AskResult):
    commit_answers(run, batch, ar.answers)                         # 검증·정규화 끝난 답만, 항목 단위 원자 커밋
    unresolved = [it for it in batch if it.ck not in run.committed]
    if ar.status == "truncated" and ar.side == "input":
        run.pack_in = max(2000, int(ar.injected_chars * cfg.calibSafety))
        requeue_front(run, unresolved); return                      # asks 증가 없음
    if ar.status == "transport_fatal": requeue_front(run, unresolved); return handle_fatal(run, ar)   # §7.7
    if ar.status == "refusal":
        for it in unresolved: commit_rule(it, "ai_refused")
        return
    for it in unresolved:                                          # 이 질의에서 답을 못 얻은 항목
        it.asks += 1
        it.notes = [note_for(ar.invalid.get(id_of(it)))] if id_of(it) in ar.invalid else []
    alive = [it for it in unresolved if it.asks < cfg.maxAsksPerItem]
    for it in unresolved:
        if it.asks >= cfg.maxAsksPerItem: commit_rule(it, "ai_failed")
    whole_fail = ar.status in ("echo", "format", "empty", "timeout") or \
                 (ar.status == "service_error" and batch_deferred_once(batch))
    if ar.status in ("partial", "truncated"):
        requeue_front(run, alive)                                  # 빠진 것만 다시(다음 패킹에서 먼저)
    elif ar.status == "service_error" and not batch_deferred_once(batch):
        run.pending.extend(alive); mark_deferred(alive)             # 뒤로 연기 1회
    elif whole_fail:
        can_split = (not run.circuit_soft) and depth < cfg.splitMaxDepth and len(alive) >= 2 * spec.min_split
        if can_split:
            h = len(alive) // 2
            run.pinned.appendleft(Pinned(alive[h:], depth + 1)); run.pinned.appendleft(Pinned(alive[:h], depth + 1))
        else:
            requeue_back(run, alive)
    update_circuit(run, ar)                                        # §7.6
```

- `spec.min_split`: 분류형(`speech_act`·`task_label`·`agentic_match`) = `splitMinItems`(5), 생성형(`workflow_label`·`subagent_review`) = 1, 단건형(`review_text`) = 1(반분 없음), 조회형 = 구간 쪼개기(§8.1).
- 항목 하나당 최대 `maxAsksPerItem`(3)회. 넘으면 규칙 폴백을 `ai_failed` 로 커밋한다(다음 실행에서 1회 더 시도, §7.9).

### 7.6 서킷브레이커

```text
def update_circuit(run, ar):
    if ar.status in ("transport_fatal", "refusal") or (ar.status == "truncated" and ar.side == "input"):
        return                                     # 크기·세션 문제는 셈하지 않는다
    if newly_committed(ar) > 0: run.zero_streak = 0; return
    run.zero_streak += 1
    if run.zero_streak >= cfg.circuitSoft and not run.circuit_soft:
        run.circuit_soft = True; notice("BR-CIRCUIT-SOFT")            # 반분·사다리 2단 끔
    if run.zero_streak >= cfg.circuitAbort:
        stop(run, kind="circuit", resumable=True)                    # 남은 항목은 rule_pending
```

### 7.7 치명 실패: 조건 폴링 → 2-strike

치명(`transport_fatal`)은 L0 가 이미 조건 폴링(§4.7)을 마친 뒤의 결과다. L3 는 한 번 더 '확인 질의'를 한다.

| L1 phase | 1차 복구(L3) | 2차 실패 시 |
|---|---|---|
| `login_required` | (L0 가 `loginWaitMin` 동안 이미 기다림) 탭을 새로 만들고 60초 폴링 후 같은 묶음 재전송 | 단계·남은 단계 중지, `stop_kind=fatal`, `reason=login_required`, BR-LOGIN-TIMEOUT |
| `input_not_found` | 새로고침 → `readyWaitSec` 폴링 → 재전송 | 중지 + 진단 덤프 + BR-INPUT |
| `wrong_tab`·`tab_lost` | 자기 탭을 새로 만들고 신원 확인 → 재전송 | 중지 + BR-TAB |
| `dead_session` | 새로고침 → 실패면 이번 호출 끝에 `dead_sessions` 기록(2회면 다음 호출에서 프로필 재생성, §4.7) | 중지 + BR-DEAD-PROFILE |
| `launch_failed`·`port_exhausted` | 다음 포트로 다시 기동 | 중지 + BR-LAUNCH |
| `profile_busy` | 30초 뒤 다시 기동 | 중지 + BR-PROFILE-BUSY |
| `policy_blocked`·`edge_not_found` | (구조적) `autoManualFallback` 이면 **즉시 수동 경로로 전환**(§10) | 수동 전환 불가면 중지 + BR-POLICY / BR-EDGE |
| `lock_busy` | 60초 간격 3회 재시도 | 중지 + BR-LOCK-BUSY |

- strike 수는 '연속' 치명 실패만 센다. 성공 질의가 하나라도 나오면 0.
- 2-strike 로 멈춘 단계는 `state=partial`(커밋이 있으면) 또는 `failed`, `resumable=true`. 같은 호출의 남은 단계도 전송이 필요하므로 `skipped(stop_kind=fatal)` 로 표시하고, 다음 호출이 저장소 기준으로 이어 한다.
- 일시적인 것과 구조적인 것을 구분해 기록한다: `bridge_profile.health` 에 `{date, phase, transient: bool}`.

### 7.8 저널 (항목 단위 커밋)

- 위치: `data\derived\bridge\runs\<run_id>\<stage>.jsonl`(질의·응답 기록), `data\derived\bridge\store\<stage>.items.jsonl`(커밋, 실행을 넘어 유지).
- 쓰기: `open(path, "a", encoding="utf-8")` → `json.dumps(rec, ensure_ascii=False) + "\n"` 한 번에 `write` → `flush()` → `os.fsync()`. 한 줄은 64KB 이하(넘으면 답의 긴 필드를 잘라 표식). 읽을 때 `json.loads` 가 실패하는 줄(끊긴 마지막 줄)은 건너뛰고 `torn_lines` 를 센다.
- 원문을 쓰지 않는다: 프롬프트는 `prompt_sha256` 과 길이만, 답은 길이·상태·번호 목록만. 커밋의 `ans` 는 **검증·정규화·입수 게이트를 통과한 답 필드**다.

질의 기록 `req`:

```json
{"t": "req", "ts": "2026-10-05T10:20:40+09:00", "stage": "task_label", "seq": 17, "rid": "R7F3QK", "rung": 0,
 "fresh": false, "chat_seq": 3, "depth": 0, "n": 30,
 "items": [{"n": 1, "key": "cand:7f3a19c2", "ck": "9c1e…"}],
 "in_chars": 7480, "est_out": 3600, "prompt_ver": "task_label/1.0", "prompt_sha256": "4be1…",
 "gate_prompt": {"ok": true, "counts": {}}, "model_wanted": "빠른 응답"}
```

응답 기록 `resp`:

```json
{"t": "resp", "ts": "2026-10-05T10:21:44+09:00", "stage": "task_label", "seq": 17, "rid": "R7F3QK", "rung": 0,
 "transport": "cdp", "phase": "replied", "status": "partial", "reason": "", "done_by": "pledge", "pick": "dom",
 "sec": 64.2, "reply_len": 4620, "ok": 28, "missing": [29, 30], "invalid": {"12": "unknown_code:project"},
 "dup": 0, "extra": 0, "extra_fields": 1, "how": "strict", "model_used": "빠른 응답", "work_mode": "work"}
```

커밋 기록(저장소):

```json
{"t": "commit", "ts": "2026-10-05T10:21:44+09:00", "stage": "task_label", "schema": "task_label/1",
 "ck": "9c1e…", "key": "cand:7f3a19c2", "reg": "r12", "run": "20261005-101500-3fa2", "rid": "R7F3QK",
 "by": "ai", "asks": 1, "final": true,
 "ans": {"project": "P012", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "광학 모듈 공차 해석", "new": "", "conf": "h"}}
```

규칙 커밋은 `"by": "rule"`, `"why": "ai_failed|ai_refused|gated:<사유>|oversize"`, `"retry_runs"`(이 항목을 다시 시도한 실행 수, 처음 0), `"final"`: `ai_failed` 는 `false`(다음 실행에서 1회 더 시도하고 `retry_runs=1` 로 다시 커밋, 그 뒤 `true`), 나머지는 `true`. 게이트로 빠진 항목은 `"confirm": true`(하류 확인 큐)도 단다.

저장소 정리: 파일이 20MB 를 넘으면 `ck` 마다 마지막 커밋만 남겨 임시 파일에 쓰고 `os.replace` 한다(호출 시작 시에만, 잠금 안에서).

### 7.9 내용 키와 재개

```text
def content_key(spec, item, ctx):
    payload = {"s": spec.schema_major,                         # 스키마 주판이 바뀌면 다시 묻는다
               "r": ctx.registry_version if spec.uses_registry else "",
               "f": {k: canon(item.fields.get(k)) for k in spec.content_key_fields}}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))).hexdigest()[:24]

def canon(v):   # 문자열: NFKC + 공백 정리, 목록: 원소마다 canon, 숫자: 그대로
```

- `content_key_fields` 에는 **변하는 값(MM·시간·건수)을 넣지 않는다**(LM24 agentic 재개 키에 MM 이 들어가 재계산마다 깨진 결함).
- 재개 = 단계 시작 때 저장소를 읽어 `ck → 마지막 커밋` 지도를 만들고, 다음 항목만 대기열에 넣는다: (a) 커밋이 없음, (b) 마지막 커밋이 `by=rule, final=false`(그리고 `retry_runs < 1`), (c) 마지막 커밋의 `reg` 가 현재 레지스트리 판과 다르고 그 답의 코드가 새 레지스트리에 없음, (d) 마지막 커밋이 `why="gated:web_combo"`(§9.7 S3)이고 이번 호출의 `web_exposed` 가 거짓.
- 그래서 같은 호출을 다시 돌리면 **이미 답한 항목은 묻지 않는다**(프로세스가 죽은 경우 진행 중 질의 1건만 다시 묻는다).

### 7.10 접기(fold)와 산출

```text
def fold(spec, run, ctx):
    latest = {}                                   # key → 커밋(같은 key 의 ck 가 여럿이면 현재 ck 의 것)
    for item in all_items_of_ai_in:
        c = store.last(item.ck)
        if c and c.by in ("ai", "manual"): latest[item.key] = c
        elif c and c.by == "rule":         latest[item.key] = c
        else:                              latest[item.key] = rule_answer(item, by="rule_pending")
    out = spec.fold(ctx, latest)                  # 단계별 산출 모양(§8)
    write_atomic(paths.ai_out(spec.id), out)      # 임시 파일 → os.replace. 실패하면 이전 파일 유지(B8)
```

- 항목 답이 비어 있으면 이전 산출의 같은 key 값을 덮지 않는다(B8).
- 접기는 멱등이다. 같은 저장소면 몇 번 접어도 같은 산출이 나온다(키 정렬, 동률은 `ts` → `rid` 순).

### 7.11 결과 봉투와 rc

모든 단계는 `finally` 에서 `data\derived\bridge\runs\<run_id>\<stage>.result.json` 을 쓴다(실패·예외·중지 모두).

```json
{"schema": 1, "stage": "task_label", "run_id": "20261005-101500-3fa2", "state": "partial",
 "items_total": 120, "items_ok": 112, "items_ai": 112, "items_manual": 0, "items_rule": 8,
 "items_failed": 2, "items_pending": 0, "items_gated": 1, "items_oversize": 0,
 "stop_kind": null, "resumable": true, "reason": "", "hint": "",
 "caps_hit": {"seen_names": 4, "lookup_rows": 0, "list_items": 1, "oversize": 0},
 "dropped": {"extra_fields": 3, "out_of_window": 0, "forbidden_field": 1},
 "asks": 6, "sends": 7, "rungs": {"0": 6, "1": 1, "2": 0},
 "statuses": {"ok": 4, "partial": 1, "truncated": 1},
 "sec": 812.4, "pack": {"in": 7690, "out": 4720}, "model": {"wanted": "빠른 응답", "used": ["빠른 응답"]},
 "transport": "cdp", "env": {"tier": "premium", "work_mode": "work", "web_grounding": "unknown", "web_exposed": true}}
```

| state | 조건 | rc |
|---|---|---|
| `done` | `items_pending == 0` 이고 `items_failed == 0` | 0 |
| `partial` | `items_pending > 0` 또는 `items_failed > 0` 또는 `stop_kind` 있음(커밋 > 0) | 2 |
| `failed` | `items_total > 0` 이고 AI·수동 커밋 0 이고 `stop_kind` 있음 | 1 |
| `skipped` | 단계 꺼짐(`bridge.stages`)·`mode=off`·입력 0건·웹 노출 차단(`reason=web_exposed`)·조회 생략(`reason=capability_unavailable`·`mode_web`) | 0 |

`stop_kind` ∈ `budget | fatal | circuit | refused | manual_wait | header | gate | cancelled | null`. 봉투에는 게이트 요약 `gate`(§9.4)도 싣는다. `rc` 는 이 표에서 기계적으로만 정한다(단계별 예외 규약 없음 — LM24 의 단계마다 다른 rc2 뜻을 없앤다). CLI `run` 의 종료 코드는 단계 rc 의 최댓값(1 > 2 > 0 순 우선: 1 이 하나라도 있으면 1).

팀 묶음의 `quality.copilot`(`TEAM_AND_BUNDLE.md`)은 이 봉투들에서 기계적으로 만든다: `used` = 어느 단계든 `items_ai + items_manual > 0`, `items` = Σ`items_total`, `failed_items` = Σ`items_failed`.

`items_failed` = 질문 상한·서킷·거절로 규칙 답이 들어간 항목. `items_pending` = 예산·치명·수동 대기로 아직 묻지 못한 항목(`rule_pending` 으로 접힘). 항등식: `items_total = items_ai + items_manual + items_rule + items_pending`, `items_ok = items_ai + items_manual`, 그리고 `items_failed`·`items_gated`·`items_oversize` 는 `items_rule` 의 부분 집합이다(결과 봉투를 쓸 때 assert).

### 7.12 예산 (`budget.py`, 한 벌)

```text
def call_plan(stages, clock):
    total_dl = clock.mono() + cfg.totalBudgetMin * 60 if cfg.totalBudgetMin > 0 else INF
    return Plan(total_dl, reserve_last=cfg.finalReserveMin * 60 if len(stages) > 1 else 0)

def stage_deadline(plan, idx, n_stages, clock):
    own = clock.mono() + cfg.stageBudgetMin * 60 if cfg.stageBudgetMin > 0 else INF
    cap = plan.total_dl - (plan.reserve_last if idx < n_stages - 1 else 0)
    dl = min(own, cap)
    return max(dl, clock.mono() + cfg.stageFloorMin * 60)     # 앞 단계가 다 써도 최소 몫
```

- 질의 시작 조건: `stage_deadline − now ≥ minAskSec`. 아니면 단계 중지 `stop_kind=budget`, `resumable=true`.
- 실행 중 적응(`runtime_adjust`): 한 단계에서 `truncated(output)` 가 2회 나면 `pack_out × 0.8`(하한 1,500)로 낮추고 `bridge_profile.runtime_adjust[stage]` 에 저장(다음 실행 시작값). 5회 연속 `ok` 면 1.0 쪽으로 0.1씩 회복.

### 7.13 조회 능력 기록 (`capability.py`)

| 현재 | 관찰 | 다음 |
|---|---|---|
| `unknown`·`ok`·`suspect` | `ok`(행 0건 포함) | `ok`, `checks` 초기화 |
| `unknown`·`ok` | `refusal(unavailable)` 이고 수송 정상 | `suspect`(그 날짜 기록) |
| `suspect` | 다른 날짜의 `refusal(unavailable)` 이 쌓여 날짜 수 ≥ `confirmDays`(2) | `unavailable`, `until = 오늘 + ttlDays(14)` |
| `suspect` | 같은 날 그 조회 단계를 다시 호출 | 보내지 않는다(`skipped(capability_unavailable)`, §7.16). `suspect` 유지(날짜 수 그대로) |
| `unavailable` | `until` 지남 | `unknown` → 다음 호출에서 1일 구간 1회로 다시 확인 |
| 아무 상태 | 수송 실패(`transport_fatal`·`timeout`) | **변화 없음**(수송 실패는 능력 판단 근거가 아니다) |

- **R-NOLIC 은 계정 단위다.** 어느 조회 단계든 `NOLIC_MARKS` 거절을 받으면 그 날짜의 `unavailable` 관찰을 `lookup_mail`·`lookup_teams`·`lookup_calendar` 세 능력에 **함께** 기록한다(같은 날 다른 조회를 또 보내 확인하지 않는다). `R-NOCONN`(조회 도구 없음)은 단계별로만 기록한다 — 메일은 되고 Teams 커넥터만 없는 테넌트가 있다(LM24 실측). 업무 모드가 아니어서 생략한 조회(`mode_web`)는 관찰이 아니다(상태 변화 없음).
- 사유 코드는 수집 명세(`COLLECTION.md` §4.2)의 R-* 를 쓴다: 조회 도구 없음 문구 → `R-NOCONN`, 업무 데이터 근거(라이선스) 없음 문구(`NOLIC_MARKS`: "업무 데이터에 액세스할 수 없"·"work content isn't available" 류) → `R-NOLIC`, 로그인 → `R-LOGIN`, 정책 → `R-EDGEPOL`, 수송 실패 → `R-TRANSPORT`(능력 판단에 쓰지 않음).
- 내보내는 기록에는 두 형제 명세의 형식을 함께 싣는다:

```json
{"mail.copilot": {"state": "suspect", "ok": null, "reasons": ["R-NOCONN"], "confirmed_days": 1,
                  "verdict": "불가(잠정)", "until": null, "checks": [{"date": "2026-10-05", "result": "unavailable"}]}}
```

  `ok`·`reasons`·`confirmed_days` 는 수집 명세 `pc.json.capability.<출처>`, `verdict` 는 `TEAM_AND_BUNDLE.md` `capabilities` 어휘다. 출처 키는 `mail.copilot`·`teams.copilot`·`cal.copilot`.
- `unavailable` 인 조회 단계는 호출되면 `skipped(reason=capability_unavailable)` 로 끝난다. 화면의 '다시 확인' 은 상태를 `unknown` 으로 돌리는 것뿐이다(사용자 본인의 선택. 다른 사용자에게 요구하지 않는다).
- 호출 끝에 `data\derived\bridge\runs\<run_id>\capabilities.json`(상태·날짜·사유 코드만)을 써서 소스 건강 매트릭스가 읽게 한다. PC 능력 기록(`TEAM_AND_BUNDLE.md` §1.5 `pc.json.capabilities`)의 판정 어휘로는 `ok`→`가능`, `suspect`→`불가(잠정)`, `unavailable`→`불가(확정)`, `unknown`→`미확인` 으로 옮기고, 키는 `copilot_connector`(조회 단계별 하위 값 `mail`·`teams`·`calendar`)를 쓴다.

### 7.14 보정 프로브 (`calibrate.py`)

**입력 한도** — 전송 없이 주입만으로 잰다:

```text
def measure_input(sess):
    lo, hi = 2000, 40000
    filler = make_filler(hi)       # 50자 줄 반복: "검증용 문장 0001 가나다라마바사아자차카타파하 abcdefghij 0123\n" (개인정보 없음)
    while hi - lo > 250 and iters < 10:
        mid = (lo + hi) // 2
        ok = inject(filler[:mid]).phase == "ok"; clear_editor()
        lo, hi = (mid, hi) if ok else (lo, mid)
    # 서버 쪽 잘림 확인: lo 길이의 채움 글 끝에 확인 코드 한 줄을 붙여 1회 전송
    code = rand_code(6)
    ask "채움 글의 맨 마지막 줄에 있는 확인 코드를 답하라" → {"rid", "n":1, "items":[{"id":1,"code":<코드>}]}
    if 답 code != code: lo = int(lo * 0.9); 최대 2회 반복, server_trunc=True
    return lo
```

**출력 한도** — 잘림 지점을 직접 관찰한다:

```text
def measure_output(sess):
    for k in (60, 100, 140):                       # 항목당 약 90자 → 5,400 / 9,000 / 12,600자 목표
        ask: "1부터 k 까지 번호마다 {"id":번호,"t":"<그 번호를 한글로 읽은 말과 80자 안팎의 아무 문장>"} 를 써라"
        r = 결과
        if r.status == "ok": best = max(best, r.reply_len); continue
        if r.status == "truncated": return r.reply_len   # 잘린 길이가 곧 한도
    return best                                    # 다 성공했으면 마지막 성공 길이(하한 추정)
```

- 저장: `input_limit`, `output_limit`, `pack_in = input_limit × calibSafety`, `pack_out = output_limit × calibSafety`, 범위로 자름(§7.2). 키는 `(profile_id, model, edge_major)`.
- 자동 실행: `autoCalibrate=true` 이고 유효한 값이 없거나 `calibrateTtlDays` 가 지났으면 호출의 첫 단계 전에 1회(전송 4~6회, 약 3~6분). 실패해도 기본값(8,000/5,000)으로 진행한다.
- 채움 글·확인 코드에는 업무 내용·개인정보가 없다(게이트 대상 아님, 그래도 게이트를 통과시킨다).

### 7.15 진행·하트비트·표준 출력

- 단계 상태 파일(공통 단계 상태 계약): `done` = 커밋 항목 수(규칙 커밋 포함), `total` = 대기열 크기, `updated` = 30초 하트비트. 한 묶음 안의 사다리·반분 재질의도 커밋이 생기면 진전으로 보인다 — LM24 의 '무진전 감시가 정상 반분 재시도를 끊는' 결함을 막는다.
- 표준 출력 이벤트(한 줄 JSON, UTF-8):

```json
{"ev": "stage_start", "stage": "task_label", "total": 120, "resume_skipped": 64}
{"ev": "progress", "stage": "task_label", "done": 90, "total": 120, "asks": 4, "last": "partial"}
{"ev": "notice", "code": "BR-LOGIN", "title": "Copilot 로그인이 필요합니다", "body": "…"}
{"ev": "stage_end", "stage": "task_label", "state": "partial", "rc": 2}
{"ev": "run_end", "rc": 2}
```

### 7.16 `run_stage` 전체 의사코드

```text
def run_stage(spec, ctx, transport, plan, idx, n):
    run = StageRun(spec, …, deadline=budget.stage_deadline(plan, idx, n, clock))
    result = Result(stage=spec.id)
    try:
        if not cfg.stages.get(spec.id, True) or cfg.mode == "off":
            return result.skipped("disabled")
        if ctx.env.web_exposed and cfg.webExposure.policy == "block":
            return result.skipped("web_exposed")              # §4.11 — 전송 0, 접기는 rule_pending(정책이 풀리면 다음 호출이 묻는다)
        if spec.kind == "lookup":
            st = caps.state(spec.id)
            if st == "unavailable" or (st == "suspect" and caps.checked_today(spec.id)):
                return result.skipped("capability_unavailable")    # 확정, 또는 오늘 이미 거절을 봄(같은 날 다시 보내지 않음, §7.13)
            if ctx.env.work_mode == "web":
                return result.skipped("mode_web")
        items = load_ai_in(spec)                          # send_fields 외 필드 버림(dropped.extra_input_fields). ck 는 여기서(게이트 전 필드로) 계산
        queue = resume_filter(items, store)               # §7.9 — 이미 답한 항목은 게이트도 전송도 건너뛴다(§9.2 '재개로 건너뛴 항목은 제외')
        queue = gate_items(run, queue)                    # §9.3 ① (+ 웹 노출이면 §9.7 엄격 규칙) — 걸린 항목은 rule 커밋(gated:<사유>)
        run.pending.extend(order(queue, spec))            # 단계 순서(group → key)
        emit("stage_start", …)
        while True:
            if run.stopped: break
            if budget_left(run) < cfg.minAskSec: stop(run, "budget", resumable=True); break
            b = next_batch(run)                           # Pinned 또는 list
            if b is None: break
            items_b, depth = (b.items, b.depth) if isinstance(b, Pinned) else (b, 0)
            ar = exchange.ask(spec, items_b, ctx_with(run))
            if ar.status == "manual_pending":           # 수동 경로: 묶음을 내보내고 계속 패킹(§10.3)
                mark_awaiting(items_b)                    # 대기열에서 빼고 manifest 에 기록(커밋 아님)
                if manual.open_count() >= cfg.manual.maxOpenBatches or not (run.pending or run.pinned):
                    stop(run, "manual_wait", resumable=True); break
                continue
            after_ask(run, items_b, depth, ar)            # §7.5 (치명이면 handle_fatal 이 stop 할 수 있음)
            emit("progress", …)
    except StageConfigError as e:
        stop(run, "header", resumable=False, reason=str(e))
    except StageGateError:                                # ② 프롬프트 게이트 실패 또는 GateSpecError
        stop(run, "gate", resumable=False, reason="gate_blocked")
    except Exception as e:                                # 예상 못 한 예외도 결과 봉투는 쓴다
        stop(run, "fatal", resumable=True, reason=type(e).__name__)
    finally:
        fold(spec, run, ctx)                              # 산출은 항상 새로 접는다(저장소 기준, 멱등)
        result.fill_from(run); write_atomic(paths.stage_result(ctx.run_id, spec.id), result)
        emit("stage_end", …)
    return result
```

---

## 8. L4 단계 정의

### 8.0 공통

#### 8.0.1 `StageSpec` (기반 클래스 `stages/base.py`)

```python
class StageSpec:
    id: str                       # "task_label"
    title_ko: str                 # 프롬프트 첫 줄·화면 표기
    prompt_ver: str               # "task_label/1.0" — 문구만 바뀌면 부판(커밋 재사용)
    schema_major: int             # 응답 스키마 주판 — 바뀌면 내용 키가 바뀌어 다시 묻는다
    kind: str                     # "items" | "lookup" | "single"
    model_class: str              # "fast" | "deep"
    chat_policy: str              # "continue" | "fresh_each"
    want_work_mode: bool
    max_items: int
    min_split: int
    est_out_per_item: int         # 답 추정 글자(항목당)
    est_out_fixed: int            # 답 추정 글자(묶음당 고정분)
    group_strict: bool            # 같은 group 을 한 질의에 모으기
    send_fields: tuple[str, ...]  # ai_in.fields 중 보낼 수 있는 키(허용 목록)
    text_fields: tuple[str, ...]  # send_fields 중 자유 텍스트(게이트 재검사·엄격 규칙 대상). 기본 = 문자열·문자열 목록 필드 전부
    web_drop_fields: tuple[str, ...] = ()   # 웹 노출일 때 보내지 않는 필드(§9.7 S4)
    gate_max_chars: int = 400     # 항목 게이트의 텍스트 필드 길이 상한(목록형은 이은 길이)
    content_key_fields: tuple[str, ...]
    uses_registry: bool
    names_field: str              # '앞서 쓴 이름' 재료가 되는 답 필드("" = 없음)
    item_schema: tuple[F, ...]    # §6.5
    def header(self, ctx, compact=False) -> str: ...
    def columns(self) -> str: ...                   # [항목] 열 이름 줄
    def item_line(self, it, n) -> str: ...
    def shrink(self, it, max_chars) -> str | None: ...
    def format_line(self) -> str: ...
    def unknown_rule(self) -> str: ...
    def validate(self, ans, it, ctx) -> str: ...    # 추가 검사, "" = 통과
    def normalize(self, ans, it, ctx) -> dict: ...
    def est_out(self, it) -> int: ...
    def rephrase(self) -> str | None: ...           # 거절 시 바꿔 쓸 머리말(없으면 None)
    def fallback(self, it, ctx, why) -> dict | None: ...
    def fold(self, ctx, latest) -> dict: ...
```

#### 8.0.2 단계 한눈표

| id | 목적 | kind | 모델 | 채팅 | max_items | 항목당 답 추정 | min_split | 산출 |
|---|---|---|---|---|---|---|---|---|
| `lookup_mail` | 메일 요약 증거 | lookup | fast | fresh_each | 구간 1 | 행 130 | 구간 쪼개기 | 증거 행 |
| `lookup_teams` | 팀즈 요약 증거 | lookup | fast | fresh_each | 구간 1 | 행 120 | 구간 쪼개기 | 증거 행 |
| `lookup_calendar` | 일정 요약 증거(기본 꺼짐) | lookup | fast | fresh_each | 구간 1 | 행 110 | 구간 쪼개기 | 증거 행 |
| `speech_act` | 화행 분류 보조 | items | fast | continue | 40 | 45 | 5 | 화행·확신 |
| `task_label` | 단위업무 이름·과제/역할 고르기 | items | fast | continue | 30 | 120 | 5 | 과제 ID·분야·기능·유형·이름 |
| `workflow_label` | 워크플로우 단계 라벨 | items | deep | continue | 6 | 200 + 110×단계 | 1 | 역할·단계 라벨·요약 |
| `review_text` | 주간·월간 리뷰 문장 | single | deep | fresh_each | 1 | 1,200(주)/1,800(월) | — | 요약·하이라이트·관계·다음 |
| `agentic_match` | 에이전트 매칭·새 니즈 | items | deep | continue | 15 | 260 | 5 | 매칭·니즈 |
| `subagent_review` | 서브에이전트 도입 검토 | items | deep | continue | 5 | 600 | 1 | 판정·구성안 |

모델 등급은 조사 권고(대량 분류·추출 = 빠른 모델, 합성 = 깊이 생각하기)를 따른다. 품질 비교는 미결 Q8.

#### 8.0.3 레지스트리·어휘를 프롬프트에 싣는 규칙 (B14)

- 과제는 **레지스트리 ID**(예: `P012`)와 팀장이 레지스트리에 적은 `copilot_desc`(중립 설명, 40자 이내)로만 보인다. 과제 이름·별칭·코드네임은 싣지 않는다. 패키징·실행 관문이 `copilot_desc` 에 코드네임 목록의 단어가 없는지 검사한다(BR-HEADER).
- 신호 텍스트 안의 과제 코드네임·별칭은 정제기의 사전 가명화로 이미 `[과제:<ID>]` 토큰이 되어 있다(`PRIVACY.md` §5.9·§8). 고객사는 `[고객사:<ID>]`, 협력사는 `[협력사:<ID>]`, 사람은 게이트가 `[사람#6hex]` 를 `[사람]` 으로 줄여 보내고(§9.3), 본인은 `[나]`. 이 토큰들은 정제기의 보호 구간이라 다시 가려지지 않는다.
- 어휘(분야·기능·업무유형·단계 유형)는 `코드 한글명` 쌍으로 싣는다. 코드는 영문 대문자·숫자·밑줄.
- 머리말 축약(`compact=True`): 목록을 '이 묶음 항목의 후보에 나온 코드 + 상위 빈도 코드'로 줄인다. 그래도 넘치면 BR-HEADER 로 단계 중지(설정 문제이므로 다시 시도해도 같다).

---

### 8.1 조회 단계 `lookup_mail` · `lookup_teams` · `lookup_calendar` — 요약 증거

**언제**: 수집 마무리에서 커버리지 원장이 '이 날짜는 메일/팀즈 출처가 비었다'고 표시한 날만. 상류(수집 오케스트레이터)가 빈 날을 `windowDays`(7일) 이하 구간으로 묶어 `ai_in` 에 쓴다. 능력 상태가 `unavailable` 이면 실행하지 않는다(§7.13). 업무 모드가 `web` 으로 확정되면(업무 탭 없는 `basic` 등급 포함, §4.11) 실행하지 않는다(`skipped(reason=mode_web)`).

**ai_in**:

```json
{"key": "lookup_mail:2026-09-01:2026-09-07", "fields": {"d0": "2026-09-01", "d1": "2026-09-07"}}
```

| 필드 | 형 | 뜻 |
|---|---|---|
| `d0`, `d1` | `YYYY-MM-DD` | 양 끝 포함 구간(로컬 시각 기준). `d1 − d0 + 1 ≤ windowDays` |

**행 상한**: `max_rows = min(cfg.lookup.maxRows, floor((pack_out − 200) / est_row))`, `est_row` = 메일 130·팀즈 120·일정 110(시각을 묻지 않아 v1 보다 줄었다). 기본 답 예산 5,000자면 메일 36행·팀즈 40행·일정 43행이다.

**머리말 — 메일**(글자 그대로, `{}` 는 채움):

```text
[LM27 요청 {rid} · 메일 조회 · 구간 {d0}~{d1}]
내 Outlook 메일(받은 편지함과 보낸 편지함)에서 {d0}부터 {d1}까지(양 끝 포함) 주고받은 업무 메일을 검색해 주세요.
규칙:
- 실제로 검색된 메일만 씁니다. 예시·추정으로 행을 만들지 않고, 확실하지 않은 행은 뺍니다.
- 자동 알림·광고·뉴스레터·시스템 메일은 뺍니다.
- 상대는 사람 이름 대신 메일 도메인(예: @example.com)만 쓰고, 모르면 "-" 로 씁니다.
- 제목은 요지만 40자 이내로 쓰고 전화번호·계좌·금액·주소는 뺍니다.
- 날짜만 씁니다. 시각은 쓰지 않습니다.
- 최대 {max_rows}행까지만 씁니다. 더 있으면 more 를 true 로 씁니다.
```

`format_line`(메일):

```text
{"rid": <요청번호>, "n": <쓴 행 수>, "more": <true|false>, "items": [ {"id": <1부터>, "t": <"YYYY-MM-DD">, "d": <"in"|"out">, "who": <상대 도메인 또는 "-">, "rcv": <"to"|"cc"|"bulk"|"-">, "s": <제목 요지>, "th": <RE:·FW: 를 뗀 스레드 제목 요지>} ]}
```

`unknown_rule`: `"이 기간에 메일이 정말 없으면 items 를 빈 목록, n 을 0 으로 씁니다"`.

**팀즈**는 첫 두 줄과 행 형식만 다르다:

```text
[LM27 요청 {rid} · 팀즈 조회 · 구간 {d0}~{d1}]
내 Microsoft Teams 채팅에서 {d0}부터 {d1}까지(양 끝 포함) 주고받은 업무 메시지를 검색해 주세요.
(규칙 줄은 메일과 같고, '상대' 줄만: - 상대는 이름을 쓰지 말고 대화 종류만 씁니다.)
```

```text
{"rid": <요청번호>, "n": <쓴 행 수>, "more": <true|false>, "items": [ {"id": <1부터>, "t": <"YYYY-MM-DD">, "d": <"in"|"out">, "chat": <"1:1"|"group"|"channel"|"meeting"|"-">, "act": <"request"|"report"|"other">, "s": <요지 40자 이내>} ]}
```

**일정**(기본 꺼짐): `{"id", "t": <"YYYY-MM-DD">, "allday": <true|false>, "busy": <0|1|2|3>, "s": <제목 요지>, "loc": <"teams"|"room"|"-">}`. 시각은 묻지 않는다 — 일정의 분 단위 시각은 COM·색인·OWA 몫이고, Copilot 요약은 시간 근거가 아니다(결정 메모 §5).

**`rephrase`**(거절·조회 불가 시 1회): 첫 문장을 `"내 Outlook 메일에서 {d0}~{d1} 기간의 업무 메일을 검색해서, 찾은 것만 아래 형식으로 정리해 주세요."` 로 바꾼다(LM24 검색형 화법 계승).

**행 검증**(`allow_time=True`):

| 필드 | 규칙 | 실패 시 |
|---|---|---|
| `t` | `^(\d{4}-\d{2}-\d{2})( \d{1,2}:\d{2})?$` 로 파싱하고 **날짜만 남긴다**(시각이 붙어 오면 떼고 `dropped.time_dropped` 셈) | 행 버림(`bad_time`) |
| `t` 날짜 | `d0 ≤ 날짜 ≤ d1` | 행 버림(`out_of_window`) — 환각 방어 |
| `d` | `in`·`out` | 행 버림 |
| `who` | `^@[A-Za-z0-9.-]+$` 또는 `-` | `-` 로 바꿈 |
| `rcv`·`chat`·`act` | 열거 | `-`·`other` 로 바꿈 |
| `s`·`th` | 60자에서 자름 | — |
| 전체 | 입수 정제(§9.3 ③) | 치환·건수 |

**구간 쪼개기**: 결과가 `truncated` 이거나 `more==true` 이거나 `n ≥ floor(max_rows × fullRatio)` 이면 '가득 참'. 구간이 `minWindowDays` 보다 길면 `[d0, mid]`, `[mid+1, d1]` 두 항목을 `Pinned` 로 앞에 넣고(이 구간의 행은 커밋하지 않음 — 쪼갠 구간에서 다시 받음), 더 못 쪼개면 받은 행을 커밋하고 `capped=true`, `caps_hit.lookup_rows += 1`.

**수집 명세와의 관계**: 수집 명세(`COLLECTION.md`)의 출처 `mail.copilot`·`teams.copilot`(그리고 일정 `cal.copilot`)은 이 조회 단계로 구현한다. 그쪽 수집기 파일(`Get-MailViaCopilot.py`·`Get-TeamsViaCopilot.py`)은 얇은 어댑터다: 커버리지 원장의 빈칸 계획기가 배정한 날을 `ai_in` 으로 쓰고 → `tools\bridge.py run --stages lookup_mail` 을 부르고 → `ai_out` 의 행을 `lm27.privacy.sanitize_record(kind, raw, rc)`(`kind` = `mail`·`teams`·`cal`, `rc.source="copilot"`)로 정제해 세그먼트에 쓴다. 능력 탐침 `probe_copilot.py`(P-CP)도 `lm27.bridge.probe(lookup=True)` 를 부르는 얇은 어댑터다. 조회 구간 크기·행 상한의 설정 키는 이 단계의 `bridge.lookup.windowDays`·`bridge.lookup.maxRows` 한 벌이다 — `COLLECT_MAIL.md` §13 의 `mail.copilot.chunkDays`·`mail.copilot.maxRows` 는 같은 뜻이므로 두지 않는다(단일 레지스트리·죽은 키 금지, §16 Q23).

**산출**: 커밋 단위는 구간(ck = 단계 + `d0`·`d1`). 접기 결과 `ai_out\lookup_mail.json` 의 `items[key].ans = {"rows": [...], "capped": bool, "more": bool}`. 위 어댑터가 이것을 증거 행으로 바꿔 쓴다(LM27 `PRIVACY.md` §0.2 H1 — 별도 `copilot_ev` kind 는 두지 않는다): `kind` = `mail`·`teams`·`cal`(그 조회 단계의 종류), `src` = `mail.copilot`·`teams.copilot`·`cal.copilot`, `ts_utc` = 그 날짜 00:00(분석 근무 시간대, 기본 +09:00)을 UTC 로 바꾼 값, `ts_local_offset`, `ts_precision="summary"` **고정**, `confidence=0.3`(`COLLECTION.md` §3.4 'Copilot summary 증인'), `direction` = `d`(메일·팀즈), 팀즈의 `chat_type` = 행의 `chat` 값, 그 kind 의 정제 문자열 열(메일·일정 `subject_masked`, 팀즈 `body_masked` — 열 이름은 `PRIVACY.md` §10.2 가 정본)에 `s`(메일은 `s` 와 `th` 를 ` / ` 로 이은 것, ≤200), `msg_key` 는 비운다(병합 대상이 아님). 메시지·메일 행과 **병합하지 않는다**(조사 teams.md: 해시 키가 영영 맞지 않아 이중 계상). 결정 메모 §5: date-only·코파일럿 요약 신호는 시간 근거로 쓰지 않는다.

**폴백**: 없음(조회는 규칙으로 대신할 수 없다). 실패 구간은 커버리지 원장에 '코파일럿 조회 실패(사유 코드)'로 남는다.

**어댑터의 커버리지 셀·종료 코드 대응**(`COLLECTION.md` §5 셀 상태, `COLLECT_MAIL.md` §4.3 rc). 셀 키는 `(account, date, kind_axis, src, pc_id)`, `kind_axis` 는 메일이면 `d` 에 따라 `mail_in`·`mail_out`, 팀즈 `teams`, 일정 `cal`:

| 브리지 결과(구간 단위) | 그 구간 각 날짜의 셀 `status` | 셀 `reason` |
|---|---|---|
| 커밋됨, 그 날짜 행 ≥ 1 | `ok`(`n` = 행 수, `n_date` = 행 수, `n_minute` = 0) | — |
| 커밋됨, 그 날짜 행 0 | `zero_ok`(`n=0`). 단 Copilot 은 **존재 증인**이라 없음을 증명하지 못한다 — 일자 합성(`COLLECTION.md` §5.3)에서 Copilot 출처의 `zero_ok` 는 다른 출처의 '근거 없음'(`blocked`·`transport_fail`·`out_of_horizon`·`not_attempted`)을 '활동 없음'으로 바꾸지 못한다(§16 Q23 ⑤) | — |
| 커밋됨, `capped=true` | `partial`, `cap_hit=true` | `R-CAP` |
| `skipped(capability_unavailable)` | `blocked` | 능력 기록의 사유(`R-NOLIC`·`R-NOCONN`) |
| `skipped(mode_web)` | `tier=basic` 이면 `blocked`, 아니면 `not_attempted`(다음 호출에서 다시 배정) | `R-NOLIC`(basic 일 때) |
| 미질의 — `stop_kind=fatal`, `reason=login_required` | `blocked` | `R-LOGIN` |
| 미질의 — `policy_blocked`(수동 경로 전환 포함) | `blocked` | `R-EDGEPOL` |
| 미질의 — `budget`·`circuit`·그 밖 수송 실패 | `transport_fail` | `R-BUDGET` 또는 `R-TRANSPORT`('불가' 근거 아님) |

| 어댑터 rc | 조건(우선순위 위에서부터) |
|---|---|
| `2` 로그인 필요 | 어느 구간이든 `R-LOGIN` |
| `3` 드라이버 불가/불완전 | 커밋 0 이고 `blocked`·`transport_fail` 구간이 있음 |
| `0` 저장 | 새 증거 행 ≥ 1 |
| `4` 읽었지만 신규 0 | 모든 구간이 재개로 건너뛰어짐(이미 증인 기록) |
| `1` 대상 없음/0건 | 그 밖(배정된 구간 0 이거나 모든 구간 행 0) |

---

### 8.2 `speech_act` — 화행 분류 보조

**언제**: 정규화 단계의 규칙 화행 분류기(공통 모듈)가 점수 회색 지대(정규화 명세의 문턱 사이)라고 표시한 메시지만. 대부분의 메시지는 규칙으로 끝나고 여기 오지 않는다.

**ai_in**:

```json
{"key": "msg:4c1d…", "group": "", "fields": {"ch": "teams", "dir": "in", "chat": "1:1", "prev": "-",
 "text": "[과제:P012] 도면 검토 부탁드립니다. 금요일까지요"}, "rule": {"act": "request", "score": 0.48}}
```

| 필드 | 형 | 뜻 |
|---|---|---|
| `ch` | `mail`·`teams` | 채널 |
| `dir` | `in`·`out` | 방향(나 기준) |
| `chat` | `1:1`·`group`·`channel`·`meeting`·`to`·`cc`·`bulk` | 대화 종류(메일은 수신 구분) |
| `prev` | 화행 코드 또는 `-` | 같은 대화의 직전 메시지 화행(규칙 판정) |
| `text` | str ≤ 120 | 정제본 본문 요지 |

`content_key_fields = ("ch", "dir", "chat", "text")`.

**머리말**:

```text
[LM27 요청 {rid} · 화행 분류 · 항목 {n}개]
당신은 업무 메시지의 말하기 의도(화행)를 분류합니다. 각 메시지를 읽고 아래 7가지 중 하나를 고르세요.
- request : 나에게 일을 맡기거나 요청·지시·검토를 부탁함 (예: ~해 주세요, ~까지 부탁드립니다)
- ack : 요청을 받아들이거나 확인함 (예: 네 알겠습니다, 확인했습니다)
- question : 정보를 묻지만 일을 맡기지는 않음
- report : 결과·완료·송부·공유를 알림 (예: 송부드립니다, 완료했습니다, 결과 공유드립니다)
- info : 그 밖의 업무 대화·정보 전달
- social : 인사·감사·잡담 등 업무 내용이 없는 말
- notice : 여러 사람에게 보내는 공지·안내·자동 알림
규칙: 메시지에 쓰인 것만 보고 판단합니다. 방향이 out 이면 내가 보낸 말입니다. 확신이 낮으면 conf 를 l 로 씁니다.
```

`columns`: `[항목] 번호 | 채널 | 방향 | 대화 | 앞 화행 | 내용`
`item_line`: `"{n} | {ch} | {dir} | {chat} | {prev} | {text}"`
`format_line`: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack|question|report|info|social|notice>, "conf": <h|m|l>} ]}`
`unknown_rule`: `"act 는 info, conf 는 l 로 씁니다"`

**스키마**: `F("act", "enum", enum=ACTS)`, `F("conf", "enum", enum=("h","m","l"))`.
**shrink**: `text` 를 60자로 → 그래도 크면 `None`(oversize).
**폴백**: `{"act": rule.act, "conf": "l"}`. 규칙 판정이 없으면 `info`.
**산출**: `items[key].ans = {"act", "conf"}`. 하류(에피소드 페어링)는 `by=ai` 이고 `conf ∈ {h, m}` 일 때만 규칙 판정을 덮어쓴다(`l` 은 참고만).

---

### 8.3 `task_label` — 단위업무 이름·과제/역할 고르기

**언제**: 단위업무 후보 클러스터링 뒤, 결정적 규칙(레지스트리 키워드·도메인·폴더·앱)으로 과제를 확정하지 못했거나(최고 점수 < 문턱) 이름이 없는 후보만.

**ai_in**:

```json
{"key": "cand:7f3a19c2", "group": "P012",
 "fields": {"kinds": "메일발신 3·메일수신 2·팀즈 3·문서 1",
            "subjects": ["[과제:P012] 공차 해석 결과 공유", "RE: 공차 해석 조건 확인"],
            "files": ["공차해석_v3.xlsx"], "apps": ["해석 프로그램"], "domains": ["@partner.example"],
            "cands": [["P012", 0.62], ["P003", 0.21]], "field_hint": "OPT"},
 "rule": {"project": "P012", "score": 0.62, "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "공차 해석"}}
```

| 필드 | 형·상한 | 뜻 |
|---|---|---|
| `kinds` | str ≤ 60 | 흔적 종류별 건수(건수는 분류 단서이지 시간이 아니다) |
| `subjects` | list ≤ 3, 각 ≤ 60 | 정제된 제목·대화 요지 |
| `files` | list ≤ 5, 각 ≤ 40 | 정제된 파일 이름(확장자 유지) |
| `apps` | list ≤ 3 | 앱 범주 이름(프로그램 카탈로그의 범주명) |
| `domains` | list ≤ 3 | 상대 도메인 |
| `cands` | list ≤ 3 `[ID, 점수]` | 규칙 후보(레지스트리 ID) |
| `field_hint` | 분야 코드 또는 `""` | 담당자 기본 분야 |

`content_key_fields = ("kinds", "subjects", "files", "apps", "domains")`, `uses_registry = True`, `names_field = "title"`, `group_strict = False`, `text_fields = ("subjects", "files", "apps", "domains")`, `web_drop_fields = ("domains",)`(상대 도메인은 고객사를 가리킬 수 있다 — 웹 노출이면 보내지 않음, §9.7).

**머리말**:

```text
[LM27 요청 {rid} · 단위업무 이름·과제/역할 고르기 · 항목 {n}개]
당신은 한 엔지니어의 업무 흔적 묶음(단위업무 후보)을 팀 과제 목록에 맞춰 분류합니다.
항목마다 다음을 고르세요.
- project : 아래 [과제 목록]의 코드 하나. 어느 과제에도 속하지 않는 공통·지원 업무면 NONE, 목록에 없는 새 과제가 분명하면 NEW.
- field : [분야] 코드 하나 / func : [기능] 코드 하나 / wtype : [업무유형] 코드 하나
- title : 이 단위업무를 부르는 짧은 이름(명사구, 25자 이내). 과제 코드·사람 이름·금액은 넣지 않습니다.
- new : project 가 NEW 일 때만 새 과제의 짧은 이름(20자 이내), 아니면 "".
- conf : 확신 h(높음)·m(보통)·l(낮음)
규칙:
- [과제:P012] 처럼 꺾쇠 안의 코드는 그 과제를 가리킵니다. 후보 점수는 프로그램이 계산한 참고값입니다.
- 목록에 있는 코드만 씁니다. 코드를 바꾸거나 지어내지 않습니다.
- [앞서 쓴 이름]에 같은 일이 있으면 그 이름을 그대로 다시 씁니다(같은 일은 같은 이름).
[과제 목록] 코드 · 업무영역 · 설명
{P012 · 개발 프로젝트 · 광학 모듈 신규 개발}
{…}
[분야] {MECH 기구 · ELEC 회로 · SW 소프트웨어 · OPT 광학 · …}
[기능] {DESIGN 설계 · ANALYSIS 해석/분석 · TEST 시험 · OUTSRC 외주 · PURCHASE 구매 · DOC 문서 · MEET 회의/조율 · PM 관리 · …}
[업무유형] {DEV 개발 · OFFICE 사무 · FIELD 현장 · PM · PL · SUPPORT 지원 · …}
```

(목록의 실제 코드·이름은 팀 레지스트리에서 온다. 위는 모양을 보이는 예시.)

`columns`: `[항목] 번호 | 흔적 | 제목 요지 | 파일 | 앱 | 상대 | 후보`
`item_line`: `"{n} | {kinds} | {' / '.join(subjects)} | {', '.join(files)} | {', '.join(apps)} | {', '.join(domains)} | {', '.join(f'{p} {s:.2f}' for p, s in cands)}"`
`format_line`: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "project": <코드|NONE|NEW>, "field": <분야 코드>, "func": <기능 코드>, "wtype": <업무유형 코드>, "title": <짧은 이름>, "new": <새 과제 이름 또는 "">, "conf": <h|m|l>} ]}`
`unknown_rule`: `"project 는 NONE, conf 는 l 로 쓰고 title 은 흔적에서 보이는 그대로 짧게 씁니다"`

**스키마**:

```python
(F("project", "code", codes="projects", extra_codes=("NONE", "NEW")),
 F("field", "code", codes="vocab.field"), F("func", "code", codes="vocab.func"), F("wtype", "code", codes="vocab.wtype"),
 F("title", "str", min_len=2, max_len=30, hard_max=80),
 F("new", "str", required=False, max_len=20),
 F("conf", "enum", enum=("h", "m", "l")))
```

`validate`: `project=="NEW"` 이면 `new` 가 2자 이상(아니면 `missing:new`). `title`·`new` 에 숫자+통화 단위(`\d[\d,]*\s?(원|만원|억|달러|USD|KRW)`)가 있으면 `bad_pattern:title`.
`normalize`: NFKC, 따옴표·꺾쇠 제거, `title` 끝의 '업무'·'작업' 중복 제거 금지(그대로 둠), 입수 게이트.
**shrink**: `subjects` 를 1개로 → `files` 2개로 → `domains` 제거 → 그래도 크면 `None`.
**폴백**: `rule.score ≥ 0.5` 면 `rule.project`, 아니면 `NONE`; `field/func/wtype` 은 `rule` 값(없으면 `field_hint`·`ETC`·`OFFICE`); `title` = `rule.title` 또는 `"미분류 업무"`; `conf="l"`.
**산출**: `items[key].ans` 그대로. `project=="NEW"` 인 답은 `ai_out` 의 `proposals` 배열(`{"name": new, "from": key}`)에도 모아 레지스트리 '제안 대기'로 보낸다(사람이 확정, 계층 명세).

---

### 8.4 `workflow_label` — 워크플로우 단계 라벨

**언제**: 결정적 과정 마이닝이 역할 업무(사람 × 과제 × 분야 × 기능)마다 단계 유형 순서와 전이를 만든 뒤. Copilot 은 이름과 설명만 붙인다(단계를 만들거나 합치지 않는다).

**ai_in**:

```json
{"key": "ws:W031", "group": "P012",
 "fields": {"project": "P012", "field": "OPT", "func": "ANALYSIS",
            "steps": [["S1", "REQ_IN", 12], ["S2", "APP_CAE", 30], ["S3", "DOC_XLS", 8], ["S4", "MEET", 5], ["S5", "REPORT_OUT", 9]],
            "trans": [["S1", "S2", 10], ["S2", "S3", 7], ["S3", "S5", 6]],
            "tasks": ["광학 모듈 공차 해석", "시험 지그 설계"]}}
```

| 필드 | 형·상한 | 뜻 |
|---|---|---|
| `steps` | list ≤ 8 `[S코드, 단계유형, 관측 횟수]` | 순서 있는 단계 |
| `trans` | list ≤ 6 `[S, S, 횟수]` | 자주 이어진 전이 |
| `tasks` | list ≤ 5 | 이 역할 업무의 단위업무 이름(앞 단계 산출) |

`content_key_fields = ("project", "field", "func", "steps_types", "tasks")` — `steps_types` 는 `steps` 에서 횟수를 뺀 `[S, 유형]` 목록(횟수는 변하는 값이라 키에서 뺀다). `names_field = ""`, `group_strict = True`(같은 과제의 역할 업무를 한 질의에).

**머리말**:

```text
[LM27 요청 {rid} · 워크플로우 단계 이름 붙이기 · 항목 {n}개]
당신은 업무 프로세스 분석가입니다. 각 항목은 한 사람의 역할 업무 하나에서 프로그램이 기록으로부터 뽑아낸 단계 순서입니다(단계 코드·단계 유형·관측 횟수, 자주 이어진 전이, 단위업무 예).
항목마다 다음을 씁니다.
- role : 이 역할 업무에서 이 사람의 역할 한 줄(40자 이내). 근거가 약하면 "판단 유보".
- steps : 주어진 단계 코드마다 label(단계 이름 15자 이내)과 desc(무슨 일을 하는지 한 문장, 60자 이내). 주어진 코드만, 주어진 순서대로 씁니다. 단계를 새로 만들거나 합치지 않습니다.
- summary : 이 역할 업무의 흐름 요약 2문장(120자 이내).
규칙: 관측 횟수와 전이는 참고용입니다. 시간·공수·인원수는 쓰지 않습니다. 사람 이름은 쓰지 않습니다.
[단계 유형] {REQ_IN 의뢰 수신 · ACK_OUT 수락 회신 · APP_CAD 설계 프로그램 · APP_CAE 해석 프로그램 · APP_SIM 시뮬레이터 · APP_IDE 개발 도구 · DOC_PPT 발표 자료 · DOC_DOC 문서 · DOC_XLS 표 계산 · MEET 회의 · MAIL_OUT 메일 발신 · REPORT_OUT 보고 발신 · FILE_SAVE 파일 저장 · COMMIT 코드 커밋 · …}
[분야] {…} [기능] {…}
```

(단계 유형 어휘는 과정 마이닝 명세가 정한다. 위는 예시.)

`columns`: `[항목] 번호 | 과제·분야·기능 | 단계 | 전이 | 단위업무 예`
`item_line`: `"{n} | 과제 {project} · 분야 {field} · 기능 {func} | " + " → ".join(f"{s} {t} {c}회" for s, t, c in steps) + " | " + ", ".join(f"{a}→{b} {c}" for a, b, c in trans) + " | " + " / ".join(tasks)`
`format_line`: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "role": <한 줄>, "summary": <2문장>, "steps": [ {"s": <단계 코드>, "label": <단계 이름>, "desc": <한 문장>} ]} ]}`
`unknown_rule`: `"role 은 \"판단 유보\", label 은 단계 유형의 한글명을 그대로 씁니다"`
`est_out(it) = 200 + 110 × len(steps)`.

**스키마**: `F("role", "str", max_len=40, hard_max=120)`, `F("summary", "str", max_len=160, hard_max=400)`, `F("steps", "list", max_items=8, item=(F("s","str",pattern=r"S\d{1,2}"), F("label","str",max_len=20,hard_max=60), F("desc","str",max_len=80,hard_max=200)))`.
`validate`: 답의 `s` 집합 ⊆ 입력 `S` 집합, 순서 보존(입력 순서의 부분열). 빠진 `S` 는 정규화에서 폴백 라벨로 채운다(항목 무효로 하지 않음, `filled_steps` 셈). 낯선 `S` 가 있으면 `bad_pattern:steps`.
`normalize`: `summary`·`desc` 에서 `\d+\s*(시간|h|MM|M/M|분|일|%)` 표현을 문장 단위로 지운다(B1, 셈).
**shrink**: `tasks` 2개로 → `trans` 3개로 → `None`.
**폴백**: `role="판단 유보"`, 각 단계 `label` = 단계 유형 한글명, `desc=""`, `summary` = 템플릿(`"{기능 한글명} 업무가 {첫 단계 한글명}에서 시작해 {마지막 단계 한글명}로 이어집니다."`).
**산출**: `items[key].ans = {"role", "summary", "steps": [{"s", "type", "label", "desc"}]}`(`type` 은 입력에서 붙임).

---

### 8.5 `review_text` — 주간·월간 리뷰 문장

**언제**: 보고서 직전. 기간(주·월)마다 항목 1개, **질의마다 새 채팅**.

**ai_in**:

```json
{"key": "review:week:2026-W40", "fields": {"kind": "week", "period": "2026-09-28~2026-10-04",
 "facts": [["F1", "완료", "광학 모듈 공차 해석", "P012", "해석/분석"], ["F2", "진행", "시험 지그 설계", "P012", "설계"]],
 "peers": [["동료1", 3]],
 "edges": []}}
```

| 필드 | 형·상한 | 뜻 |
|---|---|---|
| `kind` | `week`·`month` | |
| `period` | str | 표시용 기간 |
| `facts` | list ≤ 25 `[F번호, 상태(완료·진행·시작·보류), 단위업무 이름, 과제 ID, 기능 한글명]` | 프로그램이 확정한 사실 |
| `peers` | list ≤ 8 `[번호표, 함께 한 단위업무 수]` | 번호표 `동료1`… 은 이 질의에서만 쓰는 이름. 번호표 → `who_key`(로컬 사람 가명 `w`+16hex, LM27 `PRIVACY.md` §0.2 H4) 대응은 메모리에만 두고 `ai_out` 의 `peers_map` 에 적는다(§9.3) |
| `edges` | list ≤ 12 `[E번호, 출발, 관계, 도착]` (월간만) | 온톨로지 그래프의 상위 관계(과제–역할 업무–단위업무–산출물 종류–앱 범주–동료 가명) |

`content_key_fields = ("kind", "period", "facts", "peers", "edges")`.

**머리말**:

```text
[LM27 요청 {rid} · {주간|월간} 리뷰 문장 · {period}]
당신은 한 엔지니어의 {주간|월간} 업무 리뷰를 씁니다. 아래 [사실 목록]은 프로그램이 기록에서 확정한 것입니다. 이 목록에 있는 사실만 씁니다.
쓸 것:
- summary : 이 기간의 업무를 3~4문장으로 요약(300자 이내)
- highlights : 중요한 일 최대 5개. 각각 text(80자 이내)와 근거 refs(사실 번호 목록, 예 ["F1","F3"])
- relations : (월간만) 과제·업무·산출물·동료 사이의 연관 최대 3개. 각각 text(80자 이내)와 refs(관계 번호 목록, 예 ["E2"])
- next : 다음 기간에 이어질 일 최대 3개(각 60자 이내). '진행'·'시작' 상태 사실에서만 고릅니다
규칙: 시간·공수·MM·퍼센트 같은 숫자는 쓰지 않습니다(프로그램이 따로 붙입니다). 사람은 동료1·동료2 같은 번호표만 씁니다. 목록에 없는 일을 지어내지 않습니다.
[사실 목록] 번호 | 상태 | 단위업무 | 과제 | 기능
{F1 | 완료 | 광학 모듈 공차 해석 | P012 | 해석/분석}
[함께 한 동료] {동료1 — 함께 한 단위업무 3건}
[관계] {(월간만) E1 P012 —산출물→ 표 계산 문서}
```

`kind="single"` 이므로 `[항목]` 줄은 `1 | {period}` 한 줄이다.
`format_line`: `{"rid": <요청번호>, "n": 1, "items": [ {"id": 1, "summary": <요약>, "highlights": [ {"text": <문장>, "refs": [<F번호>]} ], "relations": [ {"text": <문장>, "refs": [<E번호>]} ], "next": [<문장>]} ]}`
`unknown_rule`: `"사실이 적으면 summary 를 짧게 쓰고 highlights 를 빈 목록으로 둡니다"`

**스키마**: `F("summary","str",max_len=300,hard_max=800)`, `F("highlights","list",max_items=5,item=(F("text","str",max_len=80,hard_max=200), F("refs","list",max_items=6)))`, `F("relations","list",required=False,max_items=3,item=(…))`, `F("next","list",required=False,max_items=3)`.
`validate`: `refs` 의 모든 값이 입력 `F…`/`E…` 번호(아니면 그 하이라이트만 버리고 `bad_refs` 셈. 하이라이트가 모두 버려지고 summary 도 비면 무효). 문장 안의 번호표(`동료` + 숫자)는 `peers` 에 있는 것만(아니면 `동료` 로 치환).
`normalize`: 시간·공수 숫자 표현 문장 제거(§8.4 와 같은 정규식), 입수 게이트.
**폴백**(결정적 템플릿): `summary = "이번 {기간}에는 {완료 n}건을 마쳤고 {진행 m}건을 진행했습니다. 주요 과제는 {상위 과제 ID 2개}입니다."`, `highlights` = 완료 사실 상위 3개(`refs` 1개씩), `next` = 진행 사실 상위 2개.
**산출**: `items[key].ans` + `peers_map`(번호표 → `who_key`). 개인 보고서 렌더러가 번호표를 로컬 사람 사전의 표시명으로 바꾸고(로컬 전용), 숫자(MM·시간)는 옆에 따로 붙인다. 팀 묶음에는 리뷰 문장을 싣지 않는다(팀 묶음 명세의 허용 목록).

---

### 8.6 `agentic_match` — 에이전트 매칭과 새 니즈

**언제**: 워크플로우 라벨 뒤. 사람마다 (단계 유형 × 그 단계를 쓰는 역할 업무들)를 항목으로 만든다. 카탈로그는 팀 레지스트리의 `agents[]`.

**ai_in**:

```json
{"key": "ag:DOC_XLS", "group": "",
 "fields": {"type": "DOC_XLS", "label": "결과 정리", "freq": "주 3회 이상", "io": "디지털 입력·디지털 출력",
            "apps": "표 계산", "ws": ["P012 해석/분석", "P003 시험"]}}
```

| 필드 | 형·상한 | 뜻 |
|---|---|---|
| `type` | 단계 유형 코드 | |
| `label` | str ≤ 20 | 앞 단계에서 붙인 대표 라벨 |
| `freq` | `주 3회 이상`·`주 1~2회`·`월 몇 회`·`드묾` | 빈도 등급(시간·MM 이 아님) |
| `io` | str ≤ 30 | 입출력 성격(결정적 체크) |
| `apps` | str ≤ 30 | 앱 범주 |
| `ws` | list ≤ 4 | 이 단계가 나오는 역할 업무(과제 ID + 기능명) |

**머리말**:

```text
[LM27 요청 {rid} · Agentic AI 매칭·새 니즈 · 항목 {n}개]
당신은 업무 자동화(Agentic AI) 기획 분석가입니다. [에이전트 목록]은 팀이 운영하거나 계획한 에이전트이고, [항목]은 한 사람의 업무 단계(단계 유형별)입니다.
항목마다 다음을 씁니다.
- m : 이 단계를 대신하거나 도울 수 있는 에이전트 최대 3개. 각각 a(에이전트 코드), fit(상: 지금 바로 대부분 대신 / 중: 사람 확인을 곁들여 보조 / 하: 일부만 보조), why(근거 40자 이내). 맞는 것이 없으면 빈 목록.
- need : 목록에 없지만 이 단계에 필요한 새 에이전트가 분명하면 name(20자 이내)·logic(무엇을 입력받아 무엇을 자동으로 하는지 80자 이내)·in(입력 40자 이내)·out(출력 40자 이내). 없으면 null.
규칙: 절감 시간이나 MM 같은 수치는 쓰지 않습니다. 억지로 맞추지 않습니다.
[에이전트 목록] 코드 · 이름 · 입력 → 출력 · 적용 단계 유형
{AG01 · 보고서 초안 생성 · 표·메모 → 문서 초안 · DOC_PPT, DOC_DOC}
{…}
```

`columns`: `[항목] 번호 | 단계 유형 | 대표 라벨 | 빈도 | 입출력 | 앱 | 쓰이는 역할 업무`
`format_line`: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "m": [ {"a": <에이전트 코드>, "fit": <상|중|하>, "why": <근거>} ], "need": <null 또는 {"name": <이름>, "logic": <로직>, "in": <입력>, "out": <출력>}>} ]}`
`unknown_rule`: `"m 은 빈 목록, need 는 null 로 씁니다"`

**스키마**: `F("m","list",max_items=3,item=(F("a","code",codes="catalog"), F("fit","enum",enum=("상","중","하")), F("why","str",max_len=40,hard_max=120)))`, `F("need","nullable_obj",item=(F("name","str",max_len=20,min_len=2), F("logic","str",max_len=80), F("in","str",max_len=40), F("out","str",max_len=40)))`.
`validate`: `m` 안에서 같은 `a` 중복 → 첫 것만. `need.name` 을 정규화(ukey: 공백·구분자·대소문자 무시)했을 때 카탈로그 이름과 같으면 `need` 를 버리고 `need_dup_catalog` 셈.
**폴백**: 카탈로그에서 적용 단계 유형에 `type` 이 든 에이전트를 `fit="중"`, `why="단계 유형 일치(규칙)"` 로 최대 3개, `need=null`.
**산출**: `items[key].ans`. 팀 취합은 `need` 를 이름 ukey 로 모아 '니즈 발굴' 표를 만든다(팀 보고서 명세). MM·절감량은 쓰지 않는다(조사 결정 'AX 가능 MM 미채택').

---

### 8.7 `subagent_review` — 서브에이전트 도입 검토

**언제**: 워크플로우 라벨 뒤, 역할 업무마다. 결정적 체크리스트 플래그를 프로그램이 먼저 계산해 함께 보낸다.

**ai_in**:

```json
{"key": "sa:W031", "group": "P012",
 "fields": {"project": "P012", "role": "해석 담당",
            "steps": [["S1", "의뢰 접수", "REQ_IN", "D1 R1 B0 L1 S1"], ["S2", "해석 수행", "APP_CAE", "D1 R1 B1 L0 S1"],
                      ["S3", "결과 정리", "DOC_XLS", "D1 R1 B1 L1 S1"], ["S5", "결과 보고", "REPORT_OUT", "D1 R1 B0 L0 S0"]]}}
```

체크리스트 플래그(프로그램 계산, 1 = 해당): `D` 입력·출력이 디지털, `R` 주 1회 이상 반복, `B` 규칙으로 판단 가능(같은 유형 단계의 결과가 정형), `L` 책임이 낮고 되돌리기 쉬움, `S` 다음 단계 입력이 정형.

**머리말**:

```text
[LM27 요청 {rid} · 서브에이전트 도입 검토 · 항목 {n}개]
당신은 업무 흐름에 AI 서브에이전트를 넣을 수 있는지 검토합니다. 각 항목은 한 역할 업무의 단계 흐름과, 단계마다 프로그램이 확인한 조건 플래그입니다.
플래그: D=입출력이 디지털, R=주 1회 이상 반복, B=규칙으로 판단 가능, L=책임이 낮고 되돌리기 쉬움, S=다음 단계 입력이 정형 (1=해당, 0=아님)
항목마다 다음을 씁니다.
- verdict : 적합 / 부분 / 부적합
- orch : 전체를 조율하는 오케스트레이터가 맡을 일(60자 이내). 부적합이면 "".
- subs : 서브에이전트 구성 최대 4개. 각각 steps(맡을 단계 코드 목록), role(40자 이내), io(입력→출력 60자 이내), check(사람이 확인할 지점 40자 이내). 부적합이면 빈 목록.
- risk : 도입 시 주의점(80자 이내)
규칙: 주어진 단계 코드만 씁니다. 플래그가 대부분 0 인 단계는 사람 몫으로 둡니다. 절감 시간이나 MM 은 쓰지 않습니다.
```

`columns`: `[항목] 번호 | 과제 · 역할 | 단계(코드 라벨 유형 플래그)`
`item_line`: `"{n} | {project} · {role} | " + " → ".join(f"{s} {label}({type}) [{flags}]" for s, label, type, flags in steps)`
`format_line`: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "verdict": <적합|부분|부적합>, "orch": <한 줄>, "subs": [ {"steps": [<단계 코드>], "role": <역할>, "io": <입력→출력>, "check": <확인 지점>} ], "risk": <주의점>} ]}`
`unknown_rule`: `"verdict 는 부분, subs 는 빈 목록으로 씁니다"`

**스키마**: `F("verdict","enum",enum=("적합","부분","부적합"))`, `F("orch","str",max_len=60,hard_max=160,required=False)`, `F("subs","list",max_items=4,item=(F("steps","list",max_items=8), F("role","str",max_len=40), F("io","str",max_len=60), F("check","str",max_len=40)))`, `F("risk","str",max_len=80,hard_max=200)`.
`validate`: 모든 `subs[].steps` ⊆ 입력 S 코드(낯선 코드가 있는 sub 는 버리고 셈). `verdict=="부적합"` 이고 `subs` 가 있으면 `subs` 를 비운다(셈).
**폴백**(규칙): 단계마다 플래그 합 ≥ 4 → '서브에이전트 후보'. 후보 단계 비율 ≥ 0.5 → `적합`, > 0 → `부분`, 0 → `부적합`. `subs` = 연속한 후보 단계 묶음마다 1개(`role` = 단계 라벨을 이은 것, `io` = `"{첫 유형} → {끝 유형}"`, `check` = `"결과 검토"`), `orch` = `"{역할} 흐름 조율"`, `risk` = `"규칙 판정 — 사람 검토 필요"`.
**산출**: `items[key].ans`.

---

### 8.8 예약: `taxonomy_bootstrap`

팀 레지스트리가 비어 있는 첫 도입 때 LM20 식 '계층 규율' 과제 체계 제안 왕복이 필요할 수 있다(조사 hierarchy-reports keep). v1 범위 밖이며, 넣을 때는 이 문서의 L2/L3 를 그대로 쓰고 결과는 레지스트리 '제안 대기'로만 보낸다(자동 확정 금지).

---

## 9. 개인정보 재검사 게이트 연결

게이트의 함수·자료구조·판정 규칙은 **정제 명세 `PRIVACY.md` §3.3·§13(관문 G3)** 이 정의한다. 이 절은 브리지가 그것을 **어디서 부르고 결과를 어떻게 다루는지**만 정한다. 브리지 안에서 `lm27.privacy` 를 임포트하는 파일은 `lm27/bridge/gate.py` 하나다.

### 9.1 위치

```
 ai_in(정제본) ─▶ [① 항목 게이트 · L3 · gate_copilot] ─▶ 패킹 ─▶ 조립 ─▶ [② 프롬프트 게이트 · L2 · gate_prompt_text] ─▶ L1 전송
                                                                                                                   │
 ai_out ◀─ 커밋 ◀─ [③ 입수 정제 · L2 · sanitize(…, "copilot_answer")] ◀─ 검증 ◀─ 봉투 추출 ◀─────────────── 답 ◀─┘
       감사: 정제 명세의 AuditSink(범주별 건수·rules_ver 만) + 결과 봉투의 gate 요약
```

수집기 경계의 '저장 전 정제'(G1)가 1차 방어다. ①②는 같은 정제기를 전송 직전에 다시 돌리는 G3, ③은 Copilot 이 이름·번호를 섞어 돌려주는 경우를 막는 브리지 몫의 입수 정제다. 웹 노출 환경(§4.11)에서는 ① 바로 뒤에 ①' 엄격 규칙(§9.7)이 붙고, ② 에 번호 토큰 잔여 검사(S5)가 더해진다.

### 9.2 호출 대응

| 브리지 자리 | `lm27.privacy` 호출 | 때 |
|---|---|---|
| ① 항목 게이트(L3) | `gate_copilot(items: list[GateItem], stage: privacy.StageSpec, gctx: GateContext) -> GateResult` | 단계 시작 때 대기열 전체에 1회(재개로 건너뛴 항목은 제외) |
| ② 프롬프트 게이트(L2) | `gate_prompt_text(prompt: str, gctx) -> (ok: bool, counts: dict)` | 조립 직후·L1 전송 직전, 사다리 재전송을 포함해 **전송마다** |
| ①' 엄격 규칙(L3, 웹 노출일 때) | 없음 — 브리지 자체 규칙(§9.7). 감사만 `gctx.audit.flush(…)` | ① 직후, 같은 대기열에 1회 |
| ③ 입수 정제(L2) | `sanitize(text, "copilot_answer", gctx.sctx, max_len=<필드 상한>)` | 검증을 통과한 답의 문자열 필드마다(조회 행 포함) |
| 문맥 | `GateContext(sctx=build_context(cfg, registry, local, keyring), canaries=…, person_tokens=<privacy.copilot.person_tokens>, audit=AuditSink(<정제 명세 감사 경로>, pc_id, stage="copilot:<stage>", src="copilot"))` | 호출 1회에 1개 |

L4 `StageSpec` 은 정제 명세의 `privacy.StageSpec` 을 만들어 준다:

```python
def privacy_spec(self) -> "privacy.StageSpec":
    return privacy.StageSpec(name=self.id,
                             allowed_fields=frozenset(self.send_fields),
                             text_fields=frozenset(self.text_fields),      # 자유 텍스트 필드(재검사 대상)
                             max_item_chars=self.gate_max_chars)            # 기본 400, 목록형 텍스트 필드는 합친 길이 기준
```

`WorkItem` → `GateItem` 변환: `item_id = key`, `meta = ai_in.meta`(상류가 넘긴 `priv_class`·`ad_band`·`rules_ver`, 보내지 않음), `fields` = 보낼 필드. **문자열 목록인 텍스트 필드**(`subjects`·`files`·`tasks` 등)는 원소의 줄바꿈을 공백으로 바꾼 뒤 `"\n"` 으로 이어 한 문자열로 넘기고, 돌아온 값을 `"\n"` 으로 다시 나눈다. 코드·숫자 목록(`steps`·`cands`·`trans`)은 텍스트 필드가 아니므로 그대로 넘긴다.

### 9.3 결과 다루기

| 게이트 결과 | 브리지 처리 |
|---|---|
| ① `GateResult.kept` | 재가림된 `fields` 로 `WorkItem.fields` 를 바꿔 대기열에 넣는다 |
| ① `GateResult.dropped (item_id, 사유)` | 그 항목은 **보내지도 다시 묻지도 않는다**. 규칙 폴백을 `by=rule`, `why="gated:<사유>"`, `final=true`, `confirm=true`(하류 확인 큐 표시)로 커밋. 결과 봉투 `items_gated` |
| ① `GateSpecError` | 허용 밖 필드 = 프로그래밍 오류. 아무것도 보내지 않고 단계 중지 `stop_kind=gate`, `resumable=false`, BR-GATE-BLOCKED |
| ② `ok=False` | 그 질의를 **보내지 않는다**. 항목 게이트를 통과한 뒤의 탐지이므로 템플릿·머리말(레지스트리 설명·카탈로그)·직렬화 결함으로 보고 재시도하지 않는다 → 단계 중지 `stop_kind=gate`, `resumable=false`, 저널에 `{"t":"gate_blocked","counts":{…}}`(건수만), BR-GATE-BLOCKED. 남은 항목은 `rule_pending` |
| ③ `drop=True` | 그 필드 값을 `"[삭제]"` 로 바꿔 커밋하고 셈(`answer_drop`) |
| ③ 적중 | 치환된 글(토큰)을 커밋하고 범주별로 셈(`answer_hits`) |

```text
def gate_items(run, items):                                      # L3, §7.16
    g = privacy.gate_copilot(to_gate_items(items), run.spec.privacy_spec(), gctx)
    for item_id, why in g.dropped: commit_rule(item_by_key(item_id), f"gated:{why}", final=True, confirm=True)
    kept = g.kept
    if ctx.env.web_exposed:                                      # §9.7 (policy=block 이면 단계가 여기 오기 전에 skipped)
        kept, wdrop, wc = strict_web(kept, run.spec)
        for item_id, why in wdrop: commit_rule(item_by_key(item_id), f"gated:{why}", final=True, confirm=True)
        run.gate_web.update(wc)
    return [from_gate_item(x) for x in kept]

RX_WEB_RESIDUE = re.compile(r"\[(?:고객사|협력사):|\[이메일@(?:고객사|협력사):|\[사람#")

def gate_prompt(asm):                                            # L2, ask() 안 — 전송마다
    ok, counts = privacy.gate_prompt_text(asm.text, gctx)
    if ok and ctx.env.web_exposed and RX_WEB_RESIDUE.search(asm.text):   # §9.7 S5 — 머리말·템플릿 결함
        ok, counts = False, {"web_residue": 1}
    if not ok:
        journal.append({"t": "gate_blocked", "stage": spec.id, "seq": seq, "counts": counts})
        raise StageGateError(counts)                             # run_stage 가 stop(kind="gate", resumable=False)
```

`person_tokens="plain"`(정제 명세 기본)이면 게이트가 `[사람#6hex]` 를 `[사람]` 으로 줄인다. 그래서 프롬프트 안에서 사람을 구별해야 하는 단계(리뷰의 '함께 한 동료')는 토큰 대신 **질의 안에서만 쓰는 번호표** `동료1`·`동료2` 를 쓰고, 번호표 → `who_key` 대응은 메모리에 두었다가 `ai_out` 의 `peers_map` 에만 적는다(§8.5).

### 9.4 감사와 결과 봉투 요약

- 감사는 정제 명세의 `AuditSink` 한 벌로 한다(범주별 건수·`rules_ver`·`rules_hash` 만, 원문·위치·항목 key 없음). 브리지가 따로 감사 파일을 만들지 않는다.
- 결과 봉투(§7.11)에 요약을 싣는다:

```json
"gate": {"rules_ver": "2026.10.0", "items_in": 31, "dropped": {"pii:phone": 1, "class_private": 0}, "remask": {"amount": 2, "person": 3},
         "prompt_blocked": 0, "answer_hits": {"person": 1}, "answer_drop": 0,
         "web": {"exposed": true, "policy": "strict", "id_strip": 4, "person_plain": 0, "combo_drop": 1, "field_drop": {"domains": 6}}}
```

개인 보고서의 '가려진 정보' 칸과 팀 묶음의 품질 칸은 이 건수만 읽는다.

### 9.5 원문이 디스크에 닿는 두 경우

| 경우 | 내용 | 조건 | 위치 | 지우는 때 |
|---|---|---|---|---|
| 수동 경로 프롬프트 파일 | ② 를 통과한 프롬프트 | 수동 경로일 때만 | `%LOCALAPPDATA%\LoadMonitor27\agent\copilot_manual\`(`PRIVACY.md` §13.3 과 같은 자리, 번들 밖) | 그 rid 의 답 반입 성공 즉시, 또는 `manual.ttlDays`(7일) 경과(브리지 시작 때마다 청소) |
| 원문 캡처 | ② 통과 프롬프트 + ③ 처리한 답 | `rawCapture=true`(기본 꺼짐, 진단용) | `%LOCALAPPDATA%\LoadMonitor27\bridge\rawcap\` | `rawCaptureTtlDays`(7일) 경과 |

모든 파일 쓰기는 `lm27/bridge/fsio.py` 의 세 함수(`append_line`, `write_atomic`, `write_text_ttl`)로만 한다. `write_text_ttl` 을 부를 수 있는 곳은 `manual.py` 와 `exchange.py`(원문 캡처)뿐이다(관문 G-B7).

### 9.6 PII 카나리아

정제 명세의 카나리아(`GateContext.canaries`, 불변식 I11, 관문 `PRIVACY.md` §18)에 더해, 브리지 시험은 합성 카나리아(형식상 유효한 가짜 전화·주민번호·계좌 문맥·카드 시험 번호·메일 로컬 파트·고객사 사전 단어·코드네임 사전 단어)를 `ai_in` 필드에 섞어 넣고 (a) 가짜 CDP 가 받은 모든 프롬프트, (b) 수동 프롬프트 파일, (c) 저널·계측·결과 봉투·`ai_out`·항목 저장소에서 카나리아 원형이 **0건**인지 확인한다(관문 G-B6). 가짜 Copilot 이 답에 카나리아를 섞어 돌려주는 시나리오(T23)에서도 저장소·`ai_out` 에 0건이어야 한다.

### 9.7 웹 노출 환경의 엄격 규칙 (`gate.strict_web`)

**언제**: `CopilotEnv.web_exposed == True`(§4.11)이고 `bridge.webExposure.policy == "strict"`. 웹 근거가 켜진 Copilot 은 프롬프트의 일부를 웹 검색어로 내보낼 수 있다. 그래서 테넌트 안에서는 문제없는 '가명 번호'도 웹 쪽에서 서로 이어 붙일 수 없게 줄이고, 수주 금액 정황(금액 + 고객사)을 담은 항목은 아예 보내지 않는다. 이 규칙은 정제기의 판정을 바꾸지 않는다 — 이미 정제·재검사된 토큰을 더 거칠게 만들 뿐이다.

| 번호 | 규칙 | 대상 | 결과 | 셈 |
|---|---|---|---|---|
| S1 | `[고객사:ID]`→`[고객사]`, `[협력사:ID]`→`[협력사]`, `[이메일@고객사:ID]`→`[이메일@고객사]`, `[이메일@협력사:ID]`→`[이메일@협력사]` | 단계 `text_fields` | 치환 | `id_strip` |
| S2 | `[사람#6hex]`→`[사람]` (설정 `privacy.copilot.person_tokens` 가 `keyed` 여도) | 단계 `text_fields` | 치환 | `person_plain` |
| S3 | 한 항목의 텍스트 필드 전체에 금액형 토큰(`[금액]`·`[비율]`)과 고객사형 토큰(`[고객사]`·`[고객사:ID]`·`[이메일@고객사…]`)이 **함께** 있음 | 항목 | 항목 제외 → 규칙 커밋 `gated:web_combo`, `confirm=true`. 웹 노출이 풀린 호출에서 다시 묻는다(§7.9 (d)) | `combo_drop` |
| S4 | 단계의 `web_drop_fields`(예: `task_label` 의 `domains`) | 필드 | 빈 값(`""`·`[]`) | `field_drop:<필드>` |
| S5 | 조립된 프롬프트에 `[고객사:`·`[협력사:`·`[이메일@고객사:`·`[이메일@협력사:`·`[사람#` 이 남아 있음 | 프롬프트 | ② 실패와 같이 처리(보내지 않음, `stop_kind=gate`, BR-GATE-BLOCKED) — 머리말·템플릿 결함 | `prompt_blocked` |

`[과제:ID]` 는 그대로 둔다(팀 레지스트리 번호이며 과제 고르기의 핵심 단서다. 과제 이름·코드네임은 정제 단계에서 이미 이 번호로 바뀌어 있다). ID 글자판 `[A-Za-z0-9_\-]{1,16}` 은 `PRIVACY.md` §5 의 보호 구간 정규식과 같다(관문 G-B11 이 대조).

```python
RX_MAIL_ORG   = re.compile(r"\[이메일@(고객사|협력사):[A-Za-z0-9_\-]{1,16}\]")
RX_ORG_ID     = re.compile(r"\[(고객사|협력사):[A-Za-z0-9_\-]{1,16}\]")
RX_PERSON_KEY = re.compile(r"\[사람#[0-9a-f]{6}\]")
RX_AMOUNT     = re.compile(r"\[(?:금액|비율)\]")
RX_CUSTOMER   = re.compile(r"\[(?:이메일@)?고객사(?::[A-Za-z0-9_\-]{1,16})?\]")

def strict_web(gitems, spec) -> tuple[list[GateItem], list[tuple[str, str]], Counter]:
    kept, dropped, c = [], [], Counter()
    for gi in gitems:                                         # gate_copilot 이 남긴 항목(목록형 텍스트는 "\n" 으로 이어진 상태, §9.2)
        tf = [f for f in spec.text_fields if f in gi.fields]
        blob = "\n".join(str(gi.fields[f]) for f in tf)
        if RX_AMOUNT.search(blob) and RX_CUSTOMER.search(blob):          # S3
            dropped.append((gi.item_id, "web_combo")); c["combo_drop"] += 1
            continue
        nf = dict(gi.fields)
        for f in tf:                                                      # S1, S2
            t = str(nf[f])
            t, n1 = RX_MAIL_ORG.subn(lambda m: "[이메일@" + m.group(1) + "]", t)
            t, n2 = RX_ORG_ID.subn(lambda m: "[" + m.group(1) + "]", t)
            t, n3 = RX_PERSON_KEY.subn("[사람]", t)
            nf[f] = t; c["id_strip"] += n1 + n2; c["person_plain"] += n3
        for f in spec.web_drop_fields:                                    # S4
            if nf.get(f):
                c["field_drop:" + f] += 1
                nf[f] = [] if isinstance(nf[f], list) else ""
        kept.append(GateItem(gi.item_id, nf, gi.meta))
    if gctx.audit:
        gctx.audit.flush(stage="copilot:" + spec.id + ":web", items_in=len(gitems), kept=len(kept), **c)
    return kept, dropped, c
```

- 순서: `gate_copilot`(①) → `strict_web`(①') → 패킹 → 조립 → `gate_prompt`(② + S5). 제외 항목은 ① 의 제외와 똑같이 다룬다(`by=rule`, `why="gated:web_combo"`, `final=true`, `confirm=true`, 이 호출에서는 다시 묻지 않음).
- S1~S4 는 내용 키(§7.9)에 영향을 주지 않는다. 내용 키는 `ai_in` 필드로 계산하므로 같은 항목은 웹 노출 여부와 무관하게 같은 키다. 그래서 웹 노출 중에 받은 답도 재사용된다.
- 엄격 규칙이 걸린 호출은 결과 봉투 `gate.web`(§9.4)에 건수를 남기고 BR-WEB-STRICT 를 1회 띄운다.
- `policy="block"` 이면 이 함수까지 오지 않는다 — 단계가 시작 전에 `skipped(reason=web_exposed)` 로 끝난다(§7.16).
- 시제품 확인(§11.6): 항목 4개 중 '금액+고객사' 1개 제외, 고객사·협력사 번호 2건·사람 키 1건 축약, 상대 도메인 2건 미전송, 남은 글에 번호 토큰 0.

---

## 10. 수동 붙여넣기 대체 경로

### 10.1 언제

- `bridge.mode = "manual"`(사용자 선택), 또는
- `autoManualFallback = true` 이고 L0 가 `policy_blocked`(회사 정책이 디버그 포트를 막음) 또는 `edge_not_found` 를 확인했을 때 — 이 호출부터 자동 전환하고 BR-MANUAL-SWITCH 를 띄운다.

수동 경로는 **같은 L3·L2** 를 쓴다. 바뀌는 것은 L1(`ManualTransport`)뿐이다. 그래서 패킹·rid 봉투·게이트·검증·상태 분류·커밋·재개가 자동 경로와 완전히 같다.

### 10.2 흐름

```
 L3 패킹 ─▶ L2 조립·게이트 ─▶ ManualTransport.roundtrip
                                   │ 프롬프트 파일 + 목록(manifest) 기록, phase=manual_pending
                                   ▼
 (사람) UI [복사] ─▶ Copilot 창에 붙여넣기 ─▶ 답 전체 복사 ─▶ UI [답 붙여넣기] 또는 inbox 폴더에 저장
                                   ▼
 manual.import_text(text) ─▶ rid 별로 나눔 ─▶ L2 classify(같은 함수) ─▶ L3 after_ask(같은 함수) ─▶ 커밋
                                   ▼
 빠진·무효 항목이 있으면 다음 수동 묶음을 자동으로 만든다(재질의) ─▶ 목록 갱신
```

### 10.3 내보내기 (`manual-export`, 또는 `run` 이 수동 모드일 때)

- L3 는 수동 모드에서 질의마다 멈추지 않고, 열린 묶음이 `manual.maxOpenBatches`(10)개가 될 때까지 패킹·조립·게이트를 계속한다. 내보낸 묶음의 항목은 상태 `awaiting` 으로 표시해 대기열에서 뺀다. 그 뒤 단계를 `stop_kind=manual_wait`, `resumable=true`, rc 2 로 끝낸다.
- 파일: `%LOCALAPPDATA%\LoadMonitor27\agent\copilot_manual\<seq:03d>_<stage>_<rid>.prompt.txt` — 내용은 **조립된 프롬프트 그대로**(안내 문구를 섞지 않는다), UTF-8 BOM + CRLF(메모장 호환).
- 목록 `...\copilot_manual\manifest.json`:

```json
{"schema": 1, "batches": [
  {"seq": 1, "stage": "task_label", "rid": "R7F3QK", "file": "001_task_label_R7F3QK.prompt.txt",
   "items": [{"n": 1, "key": "cand:7f3a19c2", "ck": "9c1e…"}], "in_chars": 7480,
   "created": "2026-10-05T10:20:40+09:00", "state": "open", "answered": null, "result": null}]}
```

`state` ∈ `open | answered | expired | superseded`. 같은 항목이 새 묶음으로 다시 나가면 앞 묶음은 `superseded`.

### 10.4 반입 (`manual-import`)

입력 경로 세 가지 — 모두 같은 함수 `manual.import_text(text)` 로 간다:
1. UI 의 '답 붙여넣기' 상자(로컬 앱이 받아 호출),
2. `tools\bridge.py manual-import --file <경로>` 또는 `--clipboard`(PowerShell `Get-Clipboard -Raw` 를 `-NoProfile -NonInteractive` 로 실행해 읽음),
3. `...\copilot_manual\inbox\*.txt` — 브리지가 시작할 때마다 훑고, 반입한 파일은 지운다.

```text
def import_text(text):
    opened = {b.rid: b for b in manifest.batches if b.state == "open"}
    found = jsonx.all_envelopes(text)                       # 'rid' 키 가진 봉투(완전·잘린 것 모두), 뒤에서부터
    if not found: return Report(error="BR-MANUAL-NOENV")
    results = []
    for env in found:
        b = opened.get(env.rid)
        if b is None:
            results.append(("reject", env.rid, "BR-MANUAL-RID" if not answered(env.rid) else "already")); continue
        res = SendResult(phase="replied", body=env.segment_text, pick="manual", done_by="manual")
        status, info = exchange.classify(spec_of(b), res, asm_meta(b))   # 같은 분류
        runner.after_ask_manual(b, status, info)            # 같은 커밋·재큐 규칙(사다리 대신 '다음 수동 묶음')
        b.state = "answered"; delete(b.file)
        results.append((status, env.rid, counts(info)))
    manifest.save(); runner.manual_continue()               # 남은 항목으로 다음 묶음을 만들어 목록에 추가
    return Report(results)
```

- **여러 답을 한꺼번에 붙여넣어도** rid 로 나눠 반입한다. 순서가 뒤섞여도 된다.
- rid 가 목록에 없으면(다른 채팅·지난 실행의 답을 복사한 경우) 반입하지 않고 BR-MANUAL-RID 를 띄운다. 이것이 수동 경로에서 rid 가 하는 일이다.
- 서약이 없어도 된다(사람이 다 쓴 답을 복사했다고 본다). 잘린 답은 복구 후 `truncated` 로, 빠진 항목은 다음 수동 묶음으로 간다.
- 수동 경로에는 사다리가 없다. `echo`·`format`·`empty`·`service_error` 는 같은 묶음을 새 rid 로 다시 내보내고(1회), 그다음은 반분 규칙을 따른다. 사람에게 '같은 것을 다시 붙여넣으세요' 이상을 요구하지 않는다.

### 10.5 화면

| 요소 | 내용 |
|---|---|
| 상단 배지 | `Copilot: 직접 붙여넣기 방식 · 남은 묶음 {k}개(약 {k}번 붙여넣기)` |
| 묶음 목록 | 순번 · 단계 한글명 · 항목 수 · 글자 수 · 상태 · [복사] · [답 붙여넣기] |
| [복사] | 프롬프트를 클립보드에 넣는다(PowerShell `Set-Clipboard` 또는 브라우저 Clipboard API). 원문은 화면 메모리에서만 |
| 답 상자 | 붙여넣은 글을 `import_text` 로 보내고 결과를 표로(커밋 n건 · 다시 물을 항목 m건 · 거부 사유) |
| 안내 | §13 의 BR-MANUAL-* 문구 |

### 10.6 한계

- 수동 경로에서는 보정 프로브를 돌릴 수 없으므로 패킹 예산은 기본값(8,000/5,000)이다.
- 조회 단계(`lookup_*`)는 수동 경로에서도 같은 프롬프트로 지원하지만, 구간이 많으면 붙여넣기 횟수가 늘어난다. 화면에 예상 횟수를 보여 주고 사용자가 단계별로 끌 수 있다(`bridge.stages`).
- 수동 경로에서는 Copilot 화면을 읽을 수 없으므로 `CopilotEnv` 가 모두 `unknown`, `web_exposed=true` 다 — 엄격 규칙(§9.7)이 항상 걸린다. 화면 신호 없이 사람의 진술만으로 이 보호를 낮추지 않는다.

---

## 11. 시험 하네스 — 스텁·가상 시계·가짜 CDP

### 11.1 시계 주입

```python
class Clock(Protocol):
    def mono(self) -> float: ...      # 단조 초
    def now(self) -> float: ...       # 벽시계 epoch(기록용)
    def sleep(self, s: float) -> None: ...

class VirtualClock:
    def __init__(self, start_epoch=1_790_000_000.0): self.t = 0.0; self.base = start_epoch
    def mono(self): return self.t
    def now(self): return self.base + self.t
    def sleep(self, s): self.t += max(0.0, s)           # 잠들지 않고 시간만 민다

@dataclass
class Deadline:
    clock: Clock; at: float
    def left(self) -> float: return max(0.0, self.at - self.clock.mono())
```

브리지의 모든 모듈은 `Clock` 을 생성자 인자로 받는다. `time` 모듈은 `clock.py` 에서만 임포트한다(관문 G-B1). 그래서 480초 대기·900초 예산·10분 로그인 대기도 시험에서는 밀리초 안에 돈다.

### 11.2 가짜 HTTP (`fake_http.py`)

`/json/version`, `/json`, `/json/new`, `/json/close/<id>`, `/json/activate/<id>` 를 흉내 낸다. 상태: 포트별 '브라우저'(소유 프로필 경로·browser_id), 탭 목록. `DevToolsActivePort` 파일은 임시 프로필 폴더에 실제로 쓴다. 남의 디버그 Edge(다른 프로필)가 같은 포트를 쓰는 경우, 포트는 열렸지만 CDP 가 아닌 경우를 만들 수 있다.

### 11.3 가짜 CDP (`fake_cdp.py`)

`cdp.eval(expr)` 는 JS 조각 머리의 `/*LM27:<이름>*/` 표식으로 처리기를 고른다. JS 를 실행하지 않고, 페이지 모형의 상태를 돌려준다. `call("Input.insertText")`·`Input.dispatchKeyEvent`·`Page.*`·`Browser.close` 도 모형에 반영한다.

```python
@dataclass
class FakeReply:
    text: str | Callable[[str, str], str]     # (프롬프트, rid) → 답 원문. 보통 stub_responder 가 만든다
    think_s: float = 5                        # 첫 글자까지
    cps: float = 60                           # 초당 글자
    pauses: tuple = ()                        # ((글자 위치, 멈춤 초, 멈춤 중 중지 버튼 보임), …)
    button: bool = True                       # 생성 중 중지 버튼이 선택자에 잡히는가
    cut_at: int | None = None                 # 이 위치에서 끊고 "OK, I've stopped generating the response." 를 덧붙임
    error: str = ""                           # 바로 이 오류 문구로 답

@dataclass
class FakePage:
    url: str = "https://m365.cloud.microsoft/chat"
    ready: str = "complete"
    login_until_s: float | None = None        # 이 시각까지 로그인 화면(None = 처음부터 로그인됨)
    input_appear_s: float = 0                 # 입력창이 늦게 뜸
    input_limit: int = 9000                   # 편집기 글자 상한(넘으면 꼬리 잘림)
    input_aria: str = "Copilot에 메시지 보내기"
    swallow_sends: int = 0                    # 앞에서 n번의 전송 클릭을 '중지'로 먹음
    assistant_dom: bool = True                # 답 노드 선택자가 맞는가(False 면 앵커 폴백)
    work_mode: str = "work"
    work_toggle: bool = True                  # 업무/웹 전환 요소가 있는가(False = 무라이선스 화면 흉내)
    web_grounding: str | None = None          # "on" | "off" | None(웹 근거 요소 없음). 클릭 기록은 clicks 에 남는다
    clicks: list = field(default_factory=list)      # 눌린 요소 이름(시험이 '웹 근거 토글 클릭 0' 을 단언)
    model_menu: tuple = ("자동", "빠른 응답", "깊이 생각하기")
    replies: deque = field(default_factory=deque)   # 전송마다 하나씩 꺼냄
    sent_texts: list = field(default_factory=list)  # 받은 프롬프트(메모리만 — 카나리아 검사용)
```

### 11.4 스텁 전송과 스텁 응답기

- `StubTransport`(L1 대체): L2·L3 시험에서 브라우저 층 없이 쓴다. `responder(prompt, rid, stage) -> (phase, body)`.
- `stub_responder.py`: 프롬프트의 `[항목]` 줄에서 번호를 읽고 단계 스키마에 맞는 답을 만든다. 모드: `ok`, `partial:<비율>`, `truncate:<비율>`, `echo`, `stale`, `empty`, `format`, `refusal`, `unavailable`, `service_error`, `forbidden_time`, `unknown_code`, `pii_in_answer`. 시나리오는 질의 순번별 모드 목록으로 준다(예: `["truncate:0.6", "ok", "ok"]`).
- 하위 프로세스 E2E(합성 E2E: PC1→PC2→클라우드 → 분석 → 업로드): 환경 변수 `LM_COPILOT_STUB=<폴더>` 이면 `run` 이 `StubTransport` 를 쓴다. 폴더의 `<stage>.json` 이 단계별 답을 정한다 — LM24 의 '프롬프트 첫 키로 파일 고르기'(키 순서 의존) 대신 단계 ID 로 직접 고른다.

```json
{"mode": ["ok"], "default": {"act": "info", "conf": "m"},
 "by_key": {"msg:4c1d…": {"act": "request", "conf": "h"}}}
```

스텁 답에는 rid 와 번호가 자동으로 채워진다. 결과 봉투의 `transport` 가 `"stub"` 이라 산출물에 흔적이 남는다.

### 11.5 시나리오 (자동 시험 `tests/bridge/test_*.py`, `unittest`)

| 번호 | 층 | 준비 | 기대(단언) |
|---|---|---|---|
| T01 | L1 | 정상 스트리밍 + 서약 | `done_by=pledge`, 전송 1, 몸통 전부 |
| T02 | L1 | 생각 150초, 중지 버튼 선택자 불일치 | `empty_reply` 아님, `pledge` 완료(약 177초) |
| T03 | L1 | 출력 없이 200초 생각, 버튼 없음 | 180초에 `empty_reply`; L2 사다리 1단에서 첫 글자 유예 90초 |
| T04 | L1 | 서약 누락, JSON 완결, 버튼 정상 | `idle_json`(서약 없이도 빠른 완료) |
| T05 | L1 | 중간 30초 멈춤, 버튼 숨김 | `incompleteJsonFactor` 덕에 서약까지 기다림 |
| T06 | L1+L2 | 중간 60초 멈춤, 버튼 숨김 | `stable` 조기 회수 → L2 `truncated` → 살린 항목 커밋, 나머지 재질의 |
| T07 | L1 | 서약 누락, 버튼 선택자 불일치 | `stable`(24초 뒤) 완료, 몸통 전부 |
| T08 | L1 | `input_limit=9000`, 프롬프트 10,500자 | 전송 안 함, `input_overflow`, `injected≈9000`; L3 입력 예산 7,650 으로 재패킹 |
| T09 | L1 | 첫 전송 클릭이 '중지'에 먹힘 | `resent=True`, 정상 완료 |
| T10 | L0 | `/json` 첫 탭이 Outlook 웹, 둘째가 Copilot | 브리지는 새 자기 탭을 만들고 **어느 탭도 닫지 않음** |
| T11 | L0 | 9343 에 남의 디버그 Edge | 9344 선택, 남의 브라우저에 연결 시도 0 |
| T12 | L0 | 잠금 보유 프로세스 살아 있음 | `lock_busy`, BR-LOCK-BUSY |
| T13 | L0 | 잠금 파일의 PID 죽음 | 잠금 인수, `.stale` 백업 |
| T14 | L0 | 로그인 화면, 3분 뒤 로그인 | BR-LOGIN → BR-LOGIN-OK, strike 0, 정상 진행 |
| T15 | L0+L3 | 로그인 안 함 | 10분 폴링 → strike 1 → 확인 재전송 실패 → 단계 중지 `fatal`, `resumable`, 남은 단계 `skipped` |
| T16 | L0 | 입력창 40초 늦게 뜸 | 정상(일시 지연을 영구 실패로 보지 않음) |
| T17 | L0 | `chrome-error://` 두 호출 연속 | 다음 호출에서 프로필 `edge_copilot.bad-*` 로 바꾸고 새 프로필 → BR-LOGIN |
| T18 | L2 | 예시 골격 에코 | `echo` → 새 채팅 재전송(새 rid) → `ok` |
| T19 | L2 | 다른 rid 의 답(지난 답) | `echo(stale)` → 재전송 |
| T20 | L2 | '도와드릴 수 없습니다' 2회 | 화법 변형 1회 → 그 항목 `ai_refused` 규칙 커밋 |
| T21 | L2 | '응답할 수 없습니다' | 사다리 1단 성공, `rung=1` 기록 |
| T22 | L2 | 사다리 3단 모두 `service_error`, 질의 예산 부족 | 2단 건너뜀 기록, L3 연기 1회 → 다시 실패 시 반분 |
| T23 | 게이트 | 답에 가짜 전화·이름 섞임 | 저장소·`ai_out` 에 토큰만, `answer_hits` 증가 |
| T24 | 게이트 | `ai_in` 에 카나리아 | 프롬프트·파일 어디에도 카나리아 0, 그 항목 `gated:pii:*` 규칙 커밋, 재질의 없음 |
| T25 | 게이트 | 레지스트리 설명에 전화번호 | `gate_prompt_text` 실패 → 전송 0, 단계 중지 `stop_kind=gate`, BR-GATE-BLOCKED |
| T26 | L3 | 40개 중 3개 빠짐 | 3개만 재질의, 질문 횟수 +1 은 그 3개만 |
| T27 | L3 | 한 항목 3회 연속 무효 | `ai_failed` 규칙 커밋(`final=false`), 다음 실행에서 1회 더 시도 후 `final=true` |
| T28 | L2 | 문자열 안 `}` 가 든 잘린 JSON | `_looks_closed` 류 오판 없음, `truncated`, 완전 원소만 커밋 |
| T29 | L2 | `n=40`, items 38개 | `partial` |
| T30 | L2 | 같은 id 두 번 + 낯선 id | 첫 것 채택, `dup=1`, `extra=1` |
| T31 | L2 | `project:"P999"`(레지스트리에 없음) | 그 항목 무효(`unknown_code`) → 다음 질의 '주의' 줄과 함께 재질의 |
| T32 | L2 | 분류 답에 `"start": "09:00"` | 그 항목 무효(`forbidden_field`) |
| T33 | L3 | 한 항목이 예산보다 큼 | `shrink` 사다리 → 그래도 크면 `oversize` 규칙 커밋, `caps_hit.oversize=1` |
| T34 | L3 | 연속 0건 질의 3회 / 6회 | soft(반분·2단 끔) / 단계 중지 `circuit`, `resumable` |
| T35 | L3 | 7번째 커밋 직후 프로세스 강제 종료 | 재실행 시 7건 건너뜀, 추가 전송은 '진행 중이던 질의 1건' 분량뿐 |
| T36 | L3 | 단계 예산 10분, 질의당 4분 | 2~3 질의 뒤 `stop_kind=budget`, `resumable`, 남은 항목 `rule_pending` |
| T37 | L3 | `chatTurns=12` | 13번째 질의 전에 새 채팅 |
| T38 | L3 | 같은 단계에서 `truncated(output)` 2회 | 답 예산 × 0.8, `runtime_adjust` 저장 |
| T39 | 조회 | 7일 구간이 '가득 참' | 3·4일로 쪼개 다시, 첫 결과는 커밋 안 함 |
| T40 | 조회 | 구간 밖 날짜 행 섞임 | 그 행 버림, `dropped.out_of_window` |
| T41 | 조회 | 같은 날 `unavailable` 2회 → 다른 날 1회 | 첫날 `suspect` 유지 → 둘째 날 `unavailable`(14일), `transport_fatal` 은 능력 판단에 영향 없음 |
| T42 | 보정 | 가짜 입력 한도 9,000·출력 5,560 | `pack_in=7650`, `pack_out=4726`, 저장 키 `(profile_id, model, edge_major)` |
| T43 | 수동 | 묶음 3개 내보냄, 답 2개를 순서 바꿔 한꺼번에 붙여넣음 | 2개 반입, 1개 열림 유지, 프롬프트 파일 2개 삭제 |
| T44 | 수동 | 다른 rid 의 답 붙여넣음 | 반입 거부, BR-MANUAL-RID, 저장소 변화 없음 |
| T45 | 수동 | 반입한 답이 `partial` | 빠진 항목으로 새 묶음 자동 생성 |
| T46 | 전체 | `LM_NO_BROWSER=1`, 스텁 없음, `autoManualFallback=true` | `edge_not_found` → 수동 전환, BR-MANUAL-SWITCH |
| T47 | 전체 | `closeOnExit=true`, 우리가 띄운 Edge / 원래 떠 있던 Edge | 앞은 `Browser.close`, 뒤는 건드리지 않음 |
| T48 | 전체 | 결과 봉투 | 모든 종료 경로(정상·예외·중지)에서 `stage_result.json` 존재, rc 표와 일치 |
| T49 | L0+조회 | 업무 탭 없음, `lookup_mail` 답이 'NOLIC' 문구 | `tier=basic`·`work_mode=web`, 세 조회 능력에 같은 날짜 `R-NOLIC`, 같은 호출의 `lookup_teams` 는 전송 0 으로 `skipped(capability_unavailable)`(오늘 이미 관찰), 분석 단계는 엄격 규칙으로 진행, BR-NOLIC |
| T50 | 게이트 | `web_exposed=true`, 항목 4개(§11.6 시제품 입력) | '금액+고객사' 1개 `gated:web_combo` 규칙 커밋(`confirm`), 가짜 CDP 가 받은 프롬프트에 `[고객사:`·`[협력사:`·`[사람#`·상대 도메인 0, `gate.web` 건수 일치 |
| T51 | 게이트 | T50 다음 호출에서 업무 모드 + 웹 근거 끔 확인 | `web_combo` 항목만 다시 묻고(§7.9 (d)) 번호 토큰을 그대로 보냄, 나머지 3개는 재사용 |
| T52 | L3 | `web_exposed=true`, `policy=block` | 모든 단계 `skipped(reason=web_exposed)`, 전송 0, 항목 `rule_pending`, BR-WEB-BLOCK |
| T53 | L0 | 웹 근거 요소가 `aria-checked=true` | `web_grounding=on`, `web_exposed=true`, `clicks` 에 웹 근거 토글 0건 |
| T54 | 조회 | 행 `t` 가 "2026-09-02 14:30" | 저장 행은 날짜만, `dropped.time_dropped=1`, 증거 행 `ts_precision="summary"`, 셀 `n_minute=0` |
| T55 | L0 | 브리지가 잠금을 쥔 동안 OWA 역할이 같은 프로필을 열려 함 | `lock_busy`(두 번째 기동 없음), 웹 수집기 설정에 별도 프로필·포트 키 없음(G-B12) |

### 11.6 시제품 확인 결과 (이 문서 작성 중, 브라우저 없음)

설계 검증용 시제품을 `scratchpad\lm26_survey\design\copilot_bridge\` 에서 돌렸다(`proto_l2.py`, `proto_l1.py`, v1.1 보강분은 `lm27\proto_lm27.py`). 저장소는 바꾸지 않았다. v1.1 작성 때 앞의 두 시제품을 다시 돌려 아래 두 표와 같은 결과를 확인했다.

L2 분류(§6.6 표의 순서):

| 입력 | 결과 |
|---|---|
| 정상 봉투 + 서약 | `ok` |
| 굽은 따옴표 | `ok`(정규화) |
| 1개 빠짐 | `partial`, missing=[3] |
| 문자열 안 `}` 가 든 잘린 JSON | `truncated`, ok=[1], how=salvaged |
| '생성 중단' 문구 꼬리 | `truncated`, cut=true |
| 예시 골격 에코 | `echo(example)` |
| 다른 rid | `echo(stale)` |
| 열거 위반 전부 | `format` |
| 시간형 필드 1개 | `partial`(그 항목 무효) |
| 정형 오류 문구 | `service_error` |
| 거절 문구 | `refusal(policy)` |
| 무응답 + 앞부분 JSON | `truncated` |
| `items: []`, n=3 | `format(no_valid_items)` |
| 중복·낯선 id | `ok`(dup=1, extra=1) |
| 조회 `n=0` | `ok` |
| 조회 '조회 도구가 없어…' | `refusal(unavailable)` |

L1 완료 판정(폴 3초, stable 8폴, 첫 글자 유예 180초):

| 시나리오 | 결과 | 시각 | 회수 |
|---|---|---|---|
| 정상 스트리밍 + 서약 | pledge | 33초 | 전부 |
| 생각 150초 · 버튼 선택자 불일치 | pledge | 177초 | 전부(빈 답 오판 없음) |
| 출력 없는 생각 | empty | 180초 | — |
| 서약 누락 · JSON 완결 · 버튼 정상 | idle_json | 42초 | 전부 |
| 중간 30초 멈춤 · 버튼 보임 | pledge | 63초 | 전부 |
| 중간 30초 멈춤 · 버튼 숨김 | pledge | 63초 | 전부(잘린 JSON 꼴이면 stable 2배) |
| 중간 60초 멈춤 · 버튼 숨김 | stable | 66초 | 절반 → L2 `truncated` 로 회복(T06) |
| 서약 누락 · 버튼 선택자 불일치 | stable | 60초 | 전부 |

v1.1 보강분(`proto_lm27.py`, 모두 기대와 일치):

| 대상 | 입력 | 결과 |
|---|---|---|
| `detect_env` | §4.11 판별 표의 6경우 | 표와 같음(웹 근거 꺼짐 확인 + 업무 모드일 때만 `web_exposed=false`) |
| `strict_web` | `[고객사:C01] 2차 미팅 준비` + 도메인 / `[고객사:C01] 견적 [금액] 확인 요청` / `[이메일@협력사:V02] 납기 확인` + 파일 `[사람#a1b2c3] 검토.xlsx` / `[과제:P0012] 공차 해석 [비율] 개선` | 2번 `web_combo` 제외, `id_strip=2`, `person_plain=1`, `field_drop:domains=2`, 남은 글에 번호 토큰 0, `[과제:P0012]` 유지 |
| 조회 행 `t` | `2026-09-02` / `2026-09-02 14:30` / `2026-08-31` / `9/2` (구간 09-01~09-07) | 통과 / 날짜만 남김(`time_dropped`) / `out_of_window` / `bad_time` |

### 11.7 회귀 지표 — 단계별 전송 수 × 재시도

`tools\bridge_trace_summary.py`(LM24 `trace_summary.py` 의 후계)가 `trace.jsonl` 에서 단계마다 다음을 낸다: 질의 수, 전송 수, 단별 전송 수(0/1/2), 상태 분포, `done_by` 분포(pledge/idle_json/stable), `pick` 분포(dom/anchor/fulltext), `busy_seen` 비율, 평균·최대 `gen_sec`, 평균 답 길이.

- **골든 고정**: 합성 고정 입력(speech_act 400 · task_label 300 · workflow_label 30 · review_text 6 · agentic_match 40 · subagent_review 30)을 '무결점 가짜 Copilot' 으로 돌린 전송 수를 첫 구현에서 측정해 `tests\bridge\golden_sends.json` 에 고정한다. 이후 **+10% 를 넘으면 실패**.
- **잡음 시나리오**: 질의별로 partial 10%·truncated 5%·empty 3%·service_error 2% 를 섞으면 전송 수 ≤ 골든 × 1.35, 2단 전송 비율 ≤ 3%, 모든 항목이 커밋(ai 또는 rule)돼야 한다.
- 실제 환경에서는 `done_by=stable` 비율이 30% 를 넘거나 `pick=fulltext` 가 하나라도 나오면 `probe` 가 경고한다(서약·DOM 회수가 깨졌다는 신호).

---

## 12. 진단 명령

진입: `python\python.exe tools\bridge.py <명령> [옵션]`. 모든 명령은 결과를 표준 출력 JSON 한 건(또는 이벤트 줄 + 마지막 결과)으로 내고, 사람이 읽을 요약을 표준 오류로 낸다.

### 12.1 명령 표

| 명령 | 하는 일 | 주요 옵션 | 종료 코드 |
|---|---|---|---|
| `run` | 단계 실행(§7.16) | `--run-id`, `--stages a,b`, `--mode auto\|manual` | 단계 rc 의 최악값(1>2>0) |
| `probe` | 연결 진단(§12.2) | `--no-roundtrip`, `--lookup` | 0 정상 / 2 제한적(수동 권장·경고) / 1 경로 없음 |
| `calibrate` | 입출력 한도 보정(§7.14) | `--force`, `--model fast\|deep` | 0 / 1 |
| `diagnose` | 화면 구조 덤프(§12.4) | `--model`(모델 메뉴 열어 항목 덤프) | 0 / 1 |
| `manual-export` | 수동 묶음 내보내기 | `--stages` | 0(내보낼 것 없음) / 2(대기 생김) |
| `manual-import` | 답 반입 | `--file`, `--clipboard` | 0 / 2(남은 묶음) / 1(반입 0) |
| `replay` | 개발용: 저널의 질의를 입력 재료로 다시 조립해 1회 보냄 | `--run-id`, `--stage`, `--seq` | 0 / 1 |
| `unlock` | 죽은 잠금 정리(살아 있는 소유자는 건드리지 않음) | — | 0 / 1 |

`replay` 는 원문을 저장하지 않으므로 같은 `ai_in` 과 같은 `prompt_ver` 로 프롬프트를 다시 만든다. 만든 프롬프트의 `sha256` 이 저널의 `prompt_sha256` 과 다르면(입력이 바뀜) 경고 후 그대로 보낸다.

### 12.2 `probe` 확인 항목

| id | 확인 | 성공 조건 | 실패·경고 코드 |
|---|---|---|---|
| `edge` | Edge 탐색 | 경로·버전 | `edge_not_found` |
| `policy` | 정책 레지스트리 읽기 | 금지 아님 | `policy_blocked_suspect` |
| `stub_env` | 시험 변수 | 없음 | `stub_env_set`(배포 환경 경고) |
| `lock` | 프로필 잠금 | 획득 | `lock_busy` |
| `port` | 포트 선택·소유 확인 | 선택됨 | `port_exhausted` |
| `launch` | 기동·재사용 | 20초 안 응답 | `launch_failed` / `policy_blocked` |
| `origin` | WS 핸드셰이크 | 101 | `origin_explicit`(정보) |
| `tab` | 자기 탭 | 생성·재사용 | `tab_lost` |
| `identity` | 신원 | `ready/strong` | `weak_identity`(경고) / `wrong_page` / `no_input` |
| `login` | 로그인 | ready | `login_required` |
| `work_mode` | 업무 모드 | `work` 또는 `unknown` | `web_mode` |
| `tier` | 계정 등급(§4.11, `--lookup` 이면 이번 조회 결과 포함) | `premium` | `basic`(경고: 조회 단계 생략) / `unknown`(정보) |
| `web_grounding` | 웹 근거 토글 상태(읽기만) | `off` | `web_on`·`wg_missing`(정보: 엄격 규칙으로 진행) |
| `web_exposed` | 웹 노출 여부 | 거짓 | `web_exposed`(정보. `policy=block` 이면 경고 — AI 단계가 모두 규칙 폴백) |
| `model` | 모델 메뉴 | 메뉴 있음, `modelFast`·`modelDeep` 항목 있음 | `model_menu_missing` / `model_item_missing` |
| `roundtrip` | 연결 확인 질의 1회(§12.3) | `ok`, `done_by=pledge` | 상태 코드 |
| `busy` | 중지 버튼 선택자 | 시험 질의에서 `busy_seen` | `busy_unseen`(완료가 느린 경로로만 판정됨) |
| `dom` | 답 노드 선택자 | 학습·검증 성공 | `anchor_fallback`(경고) |
| `calib` | 보정값 | 유효 | `calib_none` / `calib_stale` |
| `lookup_mail`·`lookup_teams` | (`--lookup`) 어제 하루 조회 | `ok`(0건 포함) | `unavailable` / 상태 코드 |

출력:

```json
{"ok": true, "recommend": "auto", "sec": 41.2,
 "env": {"tier": "premium", "work_toggle": "present", "work_mode": "work", "web_grounding": "unknown", "web_exposed": true},
 "checks": [{"id": "edge", "ok": true, "value": "129.0.2792.65", "code": "", "hint": ""},
            {"id": "busy", "ok": false, "value": "", "code": "busy_unseen", "hint": "BR-PROBE-BUSY"}]}
```

`recommend`: 모든 필수 항목(edge·launch·tab·identity·login·roundtrip) 통과면 `auto`, `policy_blocked`·`edge_not_found` 면 `manual`, 그 밖의 실패면 `none`(원인 문구 표시). 결과는 `bridge_profile.health.last_probe` 와 `%LOCALAPPDATA%\LoadMonitor27\bridge\probe_last.json` 에 남는다. PC 능력 탐침(`TEAM_AND_BUNDLE.md` §1.5 `pc.json.capabilities`)은 이 파일에서 세 값을 옮겨 적는다: `edge_cdp_policy`(← `policy`·`launch`: 통과 `가능`, `policy_blocked` 확인 `불가(확정)`, 레지스트리만 금지 `불가(잠정)`), `web_login`(← `login`: `ready` 면 `가능`, 아니면 `미확인` — 로그인 안 됨은 능력 부재가 아니다), `copilot_connector`(← `--lookup` 결과와 §7.13 능력 상태). 탐침 P-CP(`COLLECTION.md` §4.1)의 '모델·Work 모드' 칸에는 `env` 다섯 값(`tier`·`work_toggle`·`work_mode`·`web_grounding`·`web_exposed`)을 판정 어휘 없이 값 그대로 `copilot_env` 로 옮긴다.

### 12.3 연결 확인 질의(글자 그대로)

```text
[LM27 요청 {rid} · 연결 확인 · 항목 2개]
연결 확인입니다. 각 항목의 단어를 그대로 돌려주세요.
[항목] 번호 | 단어
1 | 사과
2 | 바다
[답 형식]
(공통 답 형식 줄들)
- 형식(<…> 자리에 실제 값): {"rid": <요청번호>, "n": 2, "items": [ {"id": <번호>, "w": <단어>} ]}
- 코드 블록이 끝나면 맨 마지막 줄에 [[END {rid}]] 만 씁니다.
```

이 질의가 서약 답을 돌려주면 답 노드 선택자 학습(§5.5)도 함께 한다.

### 12.4 `diagnose` 덤프 (형식 보존 마스킹)

`%LOCALAPPDATA%\LoadMonitor27\bridge\diagnose\diagnose_<시각>.json`:

```json
{"url_host": "m365.cloud.microsoft", "url_path": "/chat", "ready": "complete",
 "editors": [{"tag": "SPAN", "role": "textbox", "aria": "Copilot에 메시지 보내기", "testid": "", "visible": true, "w": 640}],
 "composer_buttons": [{"aria": "보내기", "testid": "", "disabled": false}],
 "stop_candidates": [],
 "message_candidates": [{"tag": "DIV", "role": "article", "testid": "copilot-message-reply", "cls": ["fui-Flex", "message"],
                         "children": 4, "text_len": 812, "text_mask": "가가 가가가 xxxx 00 …"}],
 "model_menu": ["자동", "빠른 응답", "깊이 생각하기", "GPT ›"],
 "learned_assistant_sel": "[data-testid='copilot-message-reply']"}
```

마스킹 규칙: 페이지 글은 모두 형식 보존 마스킹(한글 → `가`, 영문 → `x`, 숫자 → `0`, 앞 40자). aria-label 은 (a) 입력창, (b) 작성 영역 안 버튼, (c) 설정 라벨 목록에 있는 문구, (d) 모델 메뉴 항목만 원문으로 두고 나머지는 마스킹한다(사이드바의 지난 채팅 제목은 프롬프트에서 나온 글일 수 있다). 클래스 토큰은 숫자가 든 것을 뺀다. 이 덤프는 원문 없이 선택자를 맞추는 재료다.

### 12.5 표준 출력 이벤트

§7.15 의 이벤트에 더해 `probe`·`calibrate` 는 `{"ev": "check", "id": …, "ok": …}` 를 진행 중에 낸다. UI 는 이벤트 줄만 해석하고 사람용 요약은 보이지 않는다.

---

## 13. 사용자에게 보이는 문구

원칙: (1) 무엇이 됐는지 → 무엇이 남았는지 → 프로그램이 스스로 무엇을 할지 순서로 쓴다. (2) 사용자에게 시키는 일은 '로그인'과 '붙여넣기'뿐이다. (3) 원문·이름·계정을 넣지 않는다. (4) 같은 코드는 한 실행에서 한 번만 띄우고, 상태 배지는 바꾸되 본문을 새로 그리지 않는다.

| 코드 | 화면 제목 | 본문 | 프로그램이 스스로 하는 일 |
|---|---|---|---|
| BR-LOGIN | Copilot 로그인이 필요합니다 | 분석용 Edge 창을 앞으로 띄웠습니다. 그 창에서 회사 계정으로 한 번 로그인해 주세요. 로그인하면 자동으로 이어서 진행합니다. | 최대 {loginWaitMin}분 동안 5초마다 확인 |
| BR-LOGIN-OK | 로그인을 확인했습니다 | 남은 AI 분석을 이어서 진행합니다. | — |
| BR-LOGIN-TIMEOUT | 로그인을 기다리다 AI 분석을 멈췄습니다 | 지금까지 처리한 {done}건은 저장했습니다. 남은 {left}건은 규칙 분류로 임시 표시했고, 다음 분석 때 로그인되어 있으면 남은 것부터 자동으로 이어 합니다. | 재개 표시, 다음 실행에서 이어 하기 |
| BR-EDGE | Microsoft Edge 를 찾지 못했습니다 | 이 PC 에서는 Copilot 자동 연결을 쓸 수 없어 '직접 붙여넣기' 방식으로 바꿨습니다. | 수동 경로 전환(설정에 따라) |
| BR-POLICY | 회사 정책이 자동 연결을 막고 있습니다 | 이 PC 의 Edge 는 자동 조작(디버그 포트)이 허용되지 않습니다. '직접 붙여넣기' 방식으로 바꿨습니다. 결과는 같은 검증을 거칩니다. | 수동 경로 전환 |
| BR-MANUAL-SWITCH | 직접 붙여넣기 방식으로 진행합니다 | AI 에게 보낼 묶음 {k}개를 준비했습니다. [복사] → Copilot 창에 붙여넣기 → 답 전체를 복사해 [답 붙여넣기]에 넣어 주세요. 순서는 상관없습니다. | 반입마다 자동 검증·재질의 묶음 생성 |
| BR-MANUAL-RID | 이 요청의 답이 아닙니다 | 붙여넣은 답에서 대기 중인 요청 번호를 찾지 못했습니다. 다른 채팅이나 이전 답을 복사했을 수 있습니다. 해당 묶음의 Copilot 답을 다시 복사해 주세요. | 저장소 변화 없음 |
| BR-MANUAL-NOENV | 답 형식을 찾지 못했습니다 | 붙여넣은 글에 JSON 답이 없습니다. Copilot 답 전체(코드 블록 포함)를 복사했는지 확인해 주세요. | — |
| BR-MANUAL-DONE | 답을 반영했습니다 | {ok}건 반영, {retry}건은 다시 물을 묶음에 넣었습니다(남은 묶음 {k}개). | 다음 묶음 생성 |
| BR-INPUT | Copilot 입력창을 찾지 못했습니다 | 화면을 새로 고치고 다시 확인했지만 입력창이 보이지 않습니다. 화면 구조 진단을 저장했습니다. 다음 분석 때 자동으로 다시 시도합니다. | 진단 덤프, 재개 표시 |
| BR-TAB | Copilot 창이 닫혔습니다 | 분석용 탭을 다시 열어 이어서 진행합니다. | 자기 탭 재생성 |
| BR-DEAD-PROFILE | 분석용 Edge 의 로그인 정보가 손상되었습니다 | 새 분석용 프로필을 만들었습니다. 열린 Edge 창에서 한 번 로그인해 주세요. | 프로필 재생성 → BR-LOGIN |
| BR-LAUNCH | 분석용 Edge 를 띄우지 못했습니다 | 다른 포트로 다시 시도했지만 실패했습니다. 다음 분석 때 자동으로 다시 시도합니다. | 재개 표시 |
| BR-PROFILE-BUSY | 분석용 Edge 가 다른 방식으로 열려 있습니다 | 분석용 Edge 창이 자동 연결 없이 열려 있습니다. 30초 뒤 다시 확인합니다. | 30초 뒤 재확인 |
| BR-LOCK-BUSY | 다른 분석이 Copilot 을 쓰고 있습니다 | 이 PC 에서 다른 수집·분석이 같은 Edge 를 쓰는 중입니다. 끝나면 이어서 진행합니다. | 60초 간격 3회 재시도 |
| BR-SLOW | Copilot 응답이 느립니다 | 한 묶음에 {min}분째 답을 기다리고 있습니다. 새 채팅으로 다시 보내는 중입니다. | 사다리 진행 |
| BR-SERVICE | Copilot 일시 오류 | Copilot 이 일시적으로 응답하지 못했습니다. 새 채팅·다른 모델로 다시 보냈습니다. | 사다리·연기 |
| BR-CIRCUIT-SOFT | 같은 실패가 이어집니다 | 최근 {n}번 연속으로 답을 얻지 못해 재시도를 줄였습니다. | soft 모드 |
| BR-CIRCUIT | AI 분석을 잠시 멈췄습니다 | {n}번 연속으로 답을 얻지 못했습니다. 처리한 {done}건은 저장했고, 남은 것은 다음 분석 때 자동으로 이어 합니다. | 재개 표시 |
| BR-BUDGET | AI 분석 시간 예산을 다 썼습니다 | {stage} 단계에서 {done}/{total}건을 처리했습니다. 남은 {left}건은 규칙 분류로 임시 표시했고 다음 분석 때 이어 합니다. | 재개 표시 |
| BR-REFUSED | Copilot 이 일부 항목 답을 거절했습니다 | {n}건은 규칙 분류로 처리했습니다. | 규칙 커밋 |
| BR-GATE | 개인정보 때문에 일부 항목을 보내지 않았습니다 | 전송 전 재검사에서 {n}건이 걸렸습니다(유형별 건수: {hits}). 해당 항목은 규칙 분류로 처리했습니다. | 규칙 커밋 |
| BR-GATE-BLOCKED | 전송 직전 검사에서 AI 분석을 멈췄습니다 | {stage} 단계의 보낼 글에서 개인정보 형식({types})이 발견되어 아무것도 보내지 않았습니다. 과제 설명·에이전트 목록 같은 팀 목록에 원인이 있을 수 있으니 팀 레지스트리 관리자에게 알리세요. 남은 항목은 규칙 분류로 임시 표시했습니다. | 단계 중지(설정·템플릿 문제, 재시도 없음) |
| BR-HEADER | 목록이 너무 깁니다 | 과제·어휘 목록이 Copilot 입력 한도를 넘어 {stage} 단계를 멈췄습니다. 팀 레지스트리 관리자에게 알리세요. | 단계 중지 |
| BR-LOOKUP-UNAVAILABLE | 이 계정의 Copilot 은 {대상(메일·Teams 대화)}을 조회할 수 없습니다 | 서로 다른 날 {confirmDays}번 같은 답을 받아 확정했습니다. {ttlDays}일 뒤 자동으로 다시 확인합니다. 로컬 색인·웹 수집 결과는 그대로 씁니다. | 능력 기록, 조회 생략 |
| BR-LOOKUP-SUSPECT | Copilot 조회가 거절되었습니다 | 오늘 {source} 조회가 거절되었습니다. 다른 날 다시 확인한 뒤에만 '조회 불가'로 판단합니다. | 다음 실행에서 재확인 |
| BR-CALIB | Copilot 입력·답 한도를 측정했습니다 | 입력 {in}자 · 답 {out}자. 이 값으로 묶음 크기를 정합니다. | 저장 |
| BR-PROBE-BUSY | 생성 중 표시를 찾지 못했습니다 | Copilot 화면의 '중지' 버튼을 인식하지 못해 답 완료를 조금 늦게 판정합니다(결과에는 영향 없음). | 설정 라벨 갱신 권고 |
| BR-NOLIC | 이 계정의 Copilot 은 메일·Teams 를 조회할 수 없습니다 | 계정 등급상 사서함·Teams 를 근거로 쓸 수 없습니다. 메일·Teams 조회는 건너뛰고, 분석은 정리된 글을 붙여 보내는 방식으로 계속합니다. 로컬 색인·웹 수집 결과는 그대로 씁니다. | 조회 단계 생략(능력 기록), 엄격 규칙 |
| BR-WEB-STRICT | 웹 검색이 켜질 수 있어 더 가려서 보냅니다 | 업무 모드와 웹 검색 꺼짐을 둘 다 확인하지 못했습니다. 고객사·협력사 번호를 지워 보내고, 금액과 고객사가 함께 나오는 {n}건은 보내지 않고 규칙 분류로 표시했습니다. | 엄격 규칙(§9.7), 다음 호출에서 재판별 |
| BR-WEB-BLOCK | 웹 검색이 켜질 수 있어 AI 분석을 보내지 않았습니다 | 설정(웹 노출 시 전송 안 함)에 따라 이번 분석은 규칙 분류로만 표시했습니다. 업무 모드와 웹 검색 꺼짐이 확인되면 다음 분석에서 남은 것부터 자동으로 이어 합니다. | 전 단계 `skipped(web_exposed)` |
| BR-WEB-MODE | 업무(Work) 모드로 바꾸지 못했습니다 | Copilot 화면이 웹 모드에 머물러 있어 이번에는 메일·Teams 조회를 건너뜁니다. 다음 분석 때 다시 시도합니다. | 조회 `skipped(mode_web)` |

---

## 14. `copilot_auto.py` 이식 표 (유지 / 수정 / 폐기)

줄 번호는 `D:\배포\loadmon24_v4\tools\copilot_auto.py`(1,507줄). '대상'은 LM27 모듈.

| 줄 | 이름 | 판정 | 대상 | 내용 |
|---|---|---|---|---|
| 53-55 | `sys.stdout.reconfigure`, `ROOT`, `NO_WIN` | 수정 | cli, session | 표준 출력 UTF-8 은 cli 진입에서만. `ROOT` 는 `lm27.paths` |
| 58-102 | `DEFAULTS` | 수정 | settings | §3 설정 키로. 범용 선택자(`button[type='submit']`, `textarea` 전역)는 작성 영역 범위로 좁힘 |
| 108-109 | `SAFE_PROMPT`, `PART_PROMPT` | 폐기 | — | 패킹이 한도를 보장(다부 분할 없음) |
| 110-118 | `_RT_DEADLINE`, `_dl_left` | 수정 | clock(`Deadline`) | 전역 변수 대신 `Deadline` 객체를 인자로 |
| 121-126 | `SENTINEL`, `PLEDGE_TAIL`, `PROMPT_BUDGET` | 폐기 | exchange | rid 서약 `[[END rid]]` 와 공통 답 형식으로 대체 |
| 129-164 | `make_parts` | 폐기 | — | 왕복 2배·조기 분석 위험 |
| 167-177 | `echo_sentinels` | 수정 | transport(폴백) | rid 서약 정규식으로 에코 몫 계산 |
| 180-185 | `has_pledge` | 수정 | transport | rid 일치 서약만. DOM 경로에서는 에코 계산 불필요 |
| 188-217 | `strip_echo` | 유지 | transport(폴백) | 앵커 폴백 경로 전용 |
| 220-228 | `load_cfg` | 폐기 | settings | 설정 레지스트리 단일 로더 |
| 231-237 | `find_edge` | 유지+ | session | App Paths 레지스트리 탐색 추가 |
| 240-243 | `http_json` | 유지 | cdp | 주입 가능한 함수로(가짜 HTTP) |
| 246-251 | `debugger_alive` | 유지 | cdp | |
| 255-326 | `WS` | 유지+ | cdp | 선택적 `Origin` 헤더, 프레임 길이 상한 64MB |
| 329-374 | `CDP` | 유지 | cdp | 호출별 시간 한도·시간 초과 후 재연결 금지·`reconnect` 그대로. 이벤트 메시지 버림 |
| 378-407 | `ensure_edge` | 수정 | session | `--remote-allow-origins=*` 제거, 포트 고르기·소유 확인·정책 확인·`profile_id`, 기동 실패 원인 구분 |
| 414-416 | `CHAT_HOSTS` | 폐기 | — | 부분 문자열 호스트 목록(`office.com` 등)이 Outlook 웹 탭 오인의 원인 |
| 419-421 | `_is_chat_tab` | 폐기 | session(`identity`) | 정확 접두 + 입력창 aria |
| 424-429 | `_close_tab` | 수정 | session | 자기 소유 targetId 만 |
| 432-476 | `find_tab` | 폐기 | session(`own_tab`) | '첫 탭만 남기고 닫기'·'남의 탭 이동' 금지 |
| 479-486 | `activate` | 유지+ | session | `/json/activate/<id>` 병행 |
| 490-491 | `js_state` | 수정 | js(`identity`) | 입력창 존재·aria 를 함께 |
| 494-496 | `login_required` | 수정 | session | URL 파싱 후 호스트 완전 일치 |
| 499-503 | `js_chat_text` | 유지 | js(`chat_text`) | 앵커 폴백 전용 |
| 506-530 | `js_pick_model` | 유지 | js | 표기 차이 무시·열린 메뉴 토글 방지 그대로 |
| 533-538 | `js_menu_open` | 유지 | js | |
| 541-572 | `js_pick_model_item` | 유지 | js | 하위 메뉴 탐색 그대로 |
| 575-610 | `select_model` | 수정 | session | 채팅마다 1회, `ModelNote` 반환, 단계 등급별 모델 |
| 613-628 | `js_focus` | 수정 | js(`focus_input`) | aria 우선·작성 영역 기록 |
| 631-633 | `js_editor_text` | 유지 | js | |
| 636-656 | `js_insert_fallback` | 유지 | js | |
| 659-669 | `js_click_send` | 수정 | js(`click_send`) | 작성 영역 안 + `sendLabels` 만 |
| 672-678 | `press_enter` | 유지 | transport | |
| 681-690 | `js_diagnose` | 수정 | js(`diagnose`) | 답 노드 후보·형식 보존 마스킹(§12.4) |
| 696-708 | `ERROR_REPLY_MARKS`, `is_error_reply` | 유지 | exchange | 500자·앞 300자 규칙 그대로 |
| 714-721 | `CUT_REPLY_MARKS`, `is_cut_reply` | 수정 | jsonx | LM24 `details.STOP_MARKS` 와 한 벌로 합침, 꼬리 400자 |
| 724-733 | `js_is_generating` | 유지(주석 강화) | js(`poll` 의 `gen`) | fail-open 임을 명시, 작성 영역 우선 범위, `null` 반환 추가 |
| 736-748 | `wait_idle` | 유지 | transport | 시계 주입 |
| 751-760 | `js_new_chat` | 유지 | js | |
| 763-785 | `new_chat` | 수정 | transport | 사용자 메시지 수 0 으로 전환 확인, `chat_seq` 증가 |
| 788-833 | `TRACE_MAX`, `trace`, `_traced` | 수정 | trace | rid·상태·단·pick·work_mode 추가, 설정 키 `traceMaxBytes` |
| 836-917 | `run_roundtrip` | 수정 | exchange(`ask` 사다리) + transport | 사다리 3단·대기 절반·질의 예산 그대로, 전송마다 새 rid, 상태 분류는 L2 |
| 922-936 | `build_anchor` | 유지 | transport(폴백) | |
| 939-959 | `pick_reply` | 유지 | transport(폴백) | |
| 962-1138 | `_roundtrip_once` | 수정 | transport(`roundtrip`) | 주입 검증(길이+꼬리 32자), 전송 확인(편집기 비움·사용자 메시지 수), DOM 1차 회수, fail-closed 완료(§5.6) |
| 1141-1147 | `_looks_closed` | 폐기 | — | 문자열 안 `}` 오판(조사 probe2) → 실제 JSON 파서 |
| 1150-1169 | `_reply_result` | 수정 | transport(`SendResult`) | dataclass 로 |
| 1173-1204 | `_wait_rest` | 폐기 | — | 다부 분할 전용 |
| 1207-1255 | `_run_parts` | 폐기 | — | 다부 분할 전용 |
| 1258-1301 | `run_roundtrip_split` | 폐기 | — | 다부 분할 전용 |
| 1314-1325 | `STUB_KEYS`, `STUB_BODY_PATTERNS` | 폐기 | — | 프롬프트 키 순서 의존 → 단계 ID 로 고르는 스텁 |
| 1329-1330 | `_traced` 적용 | 수정 | trace | 함수 장식 대신 `ask` 안에서 명시 기록 |
| 1332-1386 | `stub_candidates`, `stub_dir`, `run_stub` | 수정 | transport_stub | `LM_COPILOT_STUB`(이름 유지), 단계 ID 기반, rid·번호 자동 채움 |
| 1389-1406 | `run_probe` | 수정 | cli(`probe`) | §12.2 확인 표 |
| 1409-1425 | `run_diagnose` | 수정 | cli(`diagnose`) | 마스킹·답 노드 후보 |
| 1428-1455 | `run_diagnose_model` | 유지 | cli(`diagnose --model`) | |
| 1458-1503 | `main` | 수정 | cli | 명령 체계 §12.1, 표준 출력 이벤트 |

LM24 의 다른 파일에서 가져오는 것:

| 원본 | 대상 | 판정 |
|---|---|---|
| `judge.py` `_close_truncated`·`repair_json`(340-433) | `jsonx.close_truncated` | 수정(키 `items` 고정, 원소 0개면 rid 만 복구) |
| `core/details.py` `_normalize_reply`·`_closers`(1160-1200) | `jsonx.normalize` | 수정(꼬리 400자 안 중단 문구만 자름) |
| `core/details.py` `explain_failure`·`PHASE_TEXT`(1300-1343) | `messages` | 수정(BR-* 코드 표로) |
| `core/budget.py` `stage_budget` | `budget` | 수정(시계 주입, 마지막 단계 몫·최소 몫 그대로) |
| `collect/Get-MailViaCopilot.py`·`Get-TeamsViaCopilot.py` 프롬프트·`UNABLE_MARKS`·`EMPTY_MARKS`·구간 밖 행 제거 | `stages/lookup.py` | 수정(JSON 봉투, 행 상한 계산, 2일 확정) |
| `judge.py`·`flow.py`·`agentic.py` 의 출력 예시 `<…>` 자리표시자 원칙, 앞서 쓴 이름 동봉, 겹침 | `exchange`·`runner` | 유지 |
| `core/stage_state.py`·`core/watch.py` 하트비트/진전 분리 | 공통 단계 상태 계약 | 유지(브리지는 계약 사용자) |

---

## 15. 관문 (lint·시험) — 브리지 몫

| 번호 | 관문 | 방법 |
|---|---|---|
| G-B1 | 시계 주입 | `lm27/bridge/**` 에서 `import time`·`time.sleep(`·`time.time(`·`time.monotonic(` 은 `clock.py` 에만 |
| G-B2 | 한도 상수 한 벌 | `\b(9000\|8400\|8300\|8000\|7000\|5500\|5000\|900\|480\|180)\b` 숫자 상수가 `settings.py` 밖에 없을 것(`# noqa: G-B2` 로만 예외) |
| G-B3 | 설정 키 읽기 확인 | 레지스트리의 모든 `bridge.*` 키가 코드에서 읽히고, 코드가 읽는 키가 모두 레지스트리에 있음(죽은 키·유령 키 0) |
| G-B4 | 단계 완결성 | `REGISTRY` 의 모든 단계에 `prompt_ver`·`item_schema`·`format_line`(`<요청번호>` 포함)·폴백(조회 제외)·스텁 고정 답이 있음. 머리말에 메일 주소·IPv4·코드네임 사전 단어 없음 |
| G-B5 | 가상 시계 시뮬 | §11.5 시나리오 전부 통과, 골든 전송 수 +10% 이내 |
| G-B6 | PII 카나리아 | §9.6 — 프롬프트·파일 어디에도 카나리아 0 |
| G-B7 | 원문 쓰기 금지 | 브리지에서 쓰기 모드 `open(` 은 `fsio.py` 에만, `write_text_ttl` 호출은 `manual.py`·`exchange.py` 에만 |
| G-B8 | 시간 정보 미전송 | 모든 단계 `send_fields` 에 시간형 키 없음, 고정 입력 프롬프트에 `\d+(\.\d+)?\s*(MM\|M/M\|시간\|h)\b` 없음 |
| G-B9 | 폐기 결함 재유입 금지 | 브리지 코드에 `remote-allow-origins=*`, `"office.com"` 류 부분 문자열 호스트, `os.kill(` 가 없음 |
| G-B10 | 결과 봉투 | T48 — 모든 종료 경로에서 `stage_result.json` 존재, `rc` 가 표와 일치 |
| G-B11 | 웹 노출 엄격 규칙 | T49~T53 통과. `web_exposed=true` 고정 입력으로 만든 모든 프롬프트에 `[고객사:`·`[협력사:`·`[사람#` 0건. 엄격 규칙 정규식의 ID 글자판이 `PRIVACY.md` §5 보호 구간 정규식과 같음 |
| G-B12 | Edge 프로필·포트 한 벌 | 브리지 밖 코드(`collect/**`, `lm27/**` 의 다른 패키지)에 `--user-data-dir`·`--remote-debugging-port` 문자열과 Edge 프로필·포트용 설정 키가 없음(모두 `EdgeSession.open(role=…)` 경유) |

---

## 16. 미결 사항

| 번호 | 질문 | 확인 방법 | 막히면 |
|---|---|---|---|
| Q1 | Copilot 화면에서 답 메시지 노드의 안정 속성(role·data-testid)은 무엇인가 | `diagnose` 덤프, `probe` 학습 결과 | 앵커 폴백(LM24 방식)으로 동작 — 느리지만 정확 |
| Q2 | 클라우드 PC(Windows 365/AVD)에서 Edge 원격 디버깅이 정책으로 허용되는가, 정책 값 이름이 `RemoteDebuggingAllowed`·`DeveloperToolsAvailability` 가 맞는가 | `probe` 의 `policy`·`launch` | 수동 경로 자동 전환 |
| Q3 | `Origin` 헤더 없는 WS 연결을 현재 Edge 가 받는가 | `probe` 의 `origin` | `--remote-allow-origins=http://127.0.0.1:<port>` + Origin 헤더(자동) |
| Q4 | Edge 가 `DevToolsActivePort` 를 프로필 폴더에 쓰는가 | `probe` | 잠금 파일의 browser_id 대조로 대신 |
| Q5 | 서약 `[[END rid]]` 가 화면 글(innerText)에 그대로 남는가, Copilot 이 rid 를 정확히 옮겨 쓰는 비율은 | `probe` 연결 확인 질의 20회, 계측 `done_by` 분포 | `<<END rid>>` 병행 인식 중, 안 되면 idle_json/stable 로 완료(느려짐) |
| Q6 | 클라우드 PC 계정·모델의 실제 입력·출력 한도 | `calibrate` | 기본 8,000/5,000 |
| Q7 | 업무(Work)/웹 전환 버튼의 DOM 과, 전환 상태가 조회 성공·데이터 경계에 주는 영향 | `diagnose`, 조회 성공률 비교 | `unknown` 으로 기록하고 진행 |
| Q8 | 현재 모델 메뉴의 정확한 이름, 빠른 모델과 깊이 생각하기 모델의 분류 일치율 | `diagnose --model`, 같은 고정 입력 두 모델 비교 | 설정 키만 바꿔 대응 |
| Q9 | 테넌트 Copilot 의 Teams 커넥터 존재 여부(LM24 실측: 없음) | `probe --lookup` | 능력 기록으로 자동 생략 |
| Q10 | 게이트 계약은 `PRIVACY.md` §3.3·§13 으로 정해졌다. 남은 것: ③ 입수 정제의 `sanitize(field_name="copilot_answer")` 를 정제 명세가 받아 주는지, 목록형 텍스트 필드를 줄바꿈으로 이어 `GateItem` 에 넣는 방식(§9.2)과 `max_item_chars` 해석, 레지스트리 `copilot_desc` 필드(계층 명세) | 정제·계층 명세와 대조 | 어댑터(`gate.py`)에서만 맞춤 |
| Q11 | 게이트를 통과한 요약을 테넌트 내 Copilot 에 보내는 것이 사내 정보보안 정책상 허용되는가, 고객 정보는 사전 치환으로 충분한가 | 사용자 확인 | `bridge.mode=off` 로 전 단계 규칙 폴백 |
| Q12 | 화행 회색 지대 문턱, task_label 규칙 확정 문턱 | 정규화·계층 명세 | 상류 설정 |
| Q13 | 과정 마이닝 단계 유형 어휘와 체크리스트 플래그(D·R·B·L·S)의 계산 정의 | 워크플로우 명세 | — |
| Q14 | 에이전트 카탈로그(`agents[]`) 필드와 관리 주체 | 계층·팀 서버 명세 | — |
| Q15 | 클라우드 PC 의 클립보드 정책(가상 데스크톱의 복사·붙여넣기 제한) | 현장 확인 | 파일 열기·inbox 폴더 경로 |
| Q16 | 공통 단계 상태 계약의 파일 경로·필드 이름 | CONTRACT 문서 | 브리지는 계약을 따른다 |
| Q17 | 보정용 채움 글 왕복(30일마다 4~6회)이 허용되는가 | 사용자 확인 | `autoCalibrate=false` + 런타임 적응만 |
| Q18 | Copilot 전용 Edge 프로필 폴더 이름이 형제 명세끼리 다르다(`TEAM_AND_BUNDLE.md` `edge_copilot` / `COLLECTION.md`·`COLLECT_MAIL.md`·`COLLECT_PC.md` `bridge_profile`). 이 명세는 `edge_copilot` 을 쓴다 | 오케스트레이터 결정 | 설정 키 `bridge.edge.profileDir` 기본값만 바꾸면 됨 |
| Q19 | PC 능력 기록 형식이 형제 명세끼리 다르다(`COLLECTION.md` `capability.<출처>.ok/reasons` / `TEAM_AND_BUNDLE.md` `capabilities.<키>.verdict/history`) | 오케스트레이터 결정 | 브리지는 두 형식을 함께 내보낸다(§7.13) |
| Q20 | 원문 캡처(`rawCapture`, 기본 꺼짐)가 정제 명세의 '원문 비저장' 원칙과 맞는가(게이트 통과본·TTL 7일·번들 밖) | 정제 명세와 대조 | 기능을 빼도 나머지 설계에 영향 없음 |
| Q21 | 계정 등급(Basic/Premium)을 화면에서 바로 알 수 있는 안정 표식(업무 탭 유무·제품 표기)이 있는가 | `diagnose` 덤프, 라이선스 있는/없는 계정 비교 | 조회 결과(성공·NOLIC 문구)로만 판정(§4.11) — 첫 호출에 조회 1회 비용 |
| Q22 | 웹 근거 토글의 위치·라벨·상태 속성, 관리자 정책으로 꺼진 경우의 화면 | `diagnose`, `probe` 의 `web_grounding` | 항상 `unknown` → 엄격 규칙(안전 쪽) |
| Q23 | 형제 명세 정합: ① `COLLECT_MAIL.md` §13 `mail.copilot.chunkDays`·`maxRows` → `bridge.lookup.*` 로 일원화, ② `mail.owa.profileDir`·`mail.owa.port`(Teams 웹의 같은 키 포함) → `bridge.edge.*` 로 일원화(§4.5), ③ `*.copilot` 증거 행(`kind` = `mail`·`teams`·`cal`)에서 `msg_key` 를 비워 둘 수 있게 `COLLECTION.md` §3.2 필수 표에 예외 추가(LM27 `PRIVACY.md` §0.2 H1 이 `copilot_ev` 를 폐기했으므로 `COLLECT_MAIL.md` §11.4 의 `copilot_ev` 표기도 고친다), ④ 증거 행 텍스트 열 이름(`subject_masked`·`body_masked`)을 LM27 `PRIVACY.md` §10.2 확정본과 대조, ⑤ `COLLECTION.md` §5.3 일자 합성에 'Copilot 출처의 `zero_ok` 는 근거 없음을 덮지 못한다' 예외 추가 | 오케스트레이터 결정 | ③ 이 안 되면 어댑터가 `msg_key` 를 `"cp:" + sha256(src + 날짜 + 행 번호)[:16]` 로 채우고 병합기는 `src=*.copilot` 행을 병합에서 뺀다 |
| Q24 | LM27 이관: `PRIVACY.md` 를 뺀 형제 명세(`COLLECTION.md`·`COLLECT_MAIL.md`·`COLLECT_PC.md`·`TEAM_AND_BUNDLE.md`)가 아직 `D:\배포\loadmon26\docs\` 에 LM26 가칭(모듈 `lm26.*`, `%LOCALAPPDATA%\LoadMonitor26\`, 작업 이름 `LM26-…`)으로 있다 | 오케스트레이터가 같은 규칙으로 이름을 바꿔 `D:\배포\loadmon27\docs\` 로 옮김 | 이 문서는 파일 이름·절 번호만 참조하므로 내용 대응은 그대로다 |
| Q25 | 웹 노출 환경의 '금액+고객사' 항목 제외(S3)가 분류 품질을 얼마나 낮추는가, 정책을 `block` 으로 둘 팀이 있는가 | 계측(`gate.web.combo_drop` 비율), 사용자 확인 | 설정 `bridge.webExposure.policy` |

---

## 부록 A. 한 질의의 전 과정 예시 (`speech_act`, 항목 3개)

프롬프트(게이트 통과본, 메모리에만 존재):

````text
[LM27 요청 R7F3QK · 화행 분류 · 항목 3개]
당신은 업무 메시지의 말하기 의도(화행)를 분류합니다. 각 메시지를 읽고 아래 7가지 중 하나를 고르세요.
- request : 나에게 일을 맡기거나 요청·지시·검토를 부탁함 (예: ~해 주세요, ~까지 부탁드립니다)
- ack : 요청을 받아들이거나 확인함 (예: 네 알겠습니다, 확인했습니다)
- question : 정보를 묻지만 일을 맡기지는 않음
- report : 결과·완료·송부·공유를 알림 (예: 송부드립니다, 완료했습니다, 결과 공유드립니다)
- info : 그 밖의 업무 대화·정보 전달
- social : 인사·감사·잡담 등 업무 내용이 없는 말
- notice : 여러 사람에게 보내는 공지·안내·자동 알림
규칙: 메시지에 쓰인 것만 보고 판단합니다. 방향이 out 이면 내가 보낸 말입니다. 확신이 낮으면 conf 를 l 로 씁니다.
[항목] 번호 | 채널 | 방향 | 대화 | 앞 화행 | 내용
1 | teams | in | 1:1 | - | [과제:P012] 도면 검토 부탁드립니다. 금요일까지요
2 | teams | out | 1:1 | request | 네 확인했습니다
3 | mail | out | to | - | RE: 시험 결과 송부드립니다 [사람]님 확인 부탁드립니다
[답 형식]
- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다. 코드 블록 밖에는 설명을 쓰지 않습니다.
- rid 에는 "R7F3QK" 를, n 에는 items 의 개수를 씁니다. 항목 번호 1~3 을 빠짐없이 한 번씩, 번호 순서대로 씁니다.
- 문자열 값은 큰따옴표로 감싸고 값 안에서 줄을 바꾸지 않습니다.
- 근거가 부족하면 지어내지 말고 act 는 info, conf 는 l 로 씁니다.
- 사람 이름·전화번호·메일 주소·금액은 쓰지 않습니다. [전화]·[금액]·[사람] 같은 꺾쇠 표기는 가려진 값입니다.
- 웹 검색을 하지 말고 이 메시지에 적힌 내용만으로 답합니다.
- 형식(<…> 자리에 실제 값): {"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack|question|report|info|social|notice>, "conf": <h|m|l>} ]}
- 코드 블록이 끝나면 맨 마지막 줄에 [[END R7F3QK]] 만 씁니다.
````

답(화면 글):

````text
```json
{"rid":"R7F3QK","n":3,"items":[{"id":1,"act":"request","conf":"h"},{"id":2,"act":"ack","conf":"h"},{"id":3,"act":"report","conf":"h"}]}
```
[[END R7F3QK]]
````

저널(`speech_act.jsonl`) — 원문 없음:

```json
{"t": "req", "stage": "speech_act", "seq": 1, "rid": "R7F3QK", "rung": 0, "n": 3, "in_chars": 1186, "prompt_sha256": "…", "prompt_ver": "speech_act/1.0", "gate": {"dropped": 0, "hits": {}}}
{"t": "resp", "stage": "speech_act", "seq": 1, "rid": "R7F3QK", "phase": "replied", "status": "ok", "done_by": "pledge", "pick": "dom", "sec": 21.4, "reply_len": 156, "ok": 3, "missing": []}
```

저장소(`speech_act.items.jsonl`) 커밋 3줄, `ai_out\speech_act.json` 에 3개 항목, 결과 봉투 `state=done`, rc 0.

## 부록 B. 실패가 섞인 단계 실행의 흐름 예시 (`task_label`, 항목 70개)

| 순서 | 질의 | 결과 | 다음 |
|---|---|---|---|
| 1 | 항목 1~30, rid R2…, 0단 | `partial`: 28 커밋, 2 빠짐 | 빠진 2개를 대기열 앞으로 |
| 2 | 빠진 2 + 31~58, 0단(같은 채팅) | `truncated(output)`: 19 커밋 | 11개 앞으로, 다음은 새 채팅 |
| 3 | 11 + 59~70 → 묶음 23개, 새 채팅 | 0단 `empty` → 1단(대기 절반) `ok`: 23 커밋 | 대기열 빔 |
| — | 접기 | 70개 모두 `by=ai` | `state=done`, rc 0, 전송 4회(질의 3) |

이 실행이 2번 질의 도중 강제 종료됐다면: 재실행 시 1번 질의의 28개는 저장소에서 건너뛰고, 2번 질의부터 다시 묻는다(잃는 것은 진행 중이던 질의 1건).
