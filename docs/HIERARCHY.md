# LM27 업무 계층·분류 명세 (HIERARCHY.md)

| 항목 | 값 |
|---|---|
| 판 | v1.0 (2026-10-05) — 설계 확정본, 구현 전 |
| 제품명 | **LoadMonitor27(LM27)**. 초기 설계 자료의 'LM26' 표기는 잘못 붙은 이름이다(사용자 지시: "LM27로 해달라는 걸 LM26으로 했다"). `D:\배포\LM26` 은 다른 AI 도구가 만든 별개 프로젝트이며 이 문서와 무관하다(읽기만). 이 문서의 모듈·경로·설정 키·스키마 이름은 모두 LM27 기준이다 |
| 대상 코드 | `lm27/hier/**`(계층·분류), `lm27/bridge/stages/task_label.py`·`taxonomy_bootstrap.py`·`taxonomy_consolidate.py`(코파일럿 단계 정의 — 브리지 명세의 L4 틀 위에 이 문서가 내용을 정한다), `tests/hier/**` |
| 소유 범위 | 업무 계층 모델(업무 영역·과제·역할 업무·단위 업무 라벨·업무 유형), **레지스트리의 의미 스키마**(과제·별칭·키워드·힌트·never·어휘·규칙·agentic 카탈로그), 레지스트리 병합(팀 ⊕ 개인), 결정적 규칙 분류기, 명명 군집과 이름, 코파일럿 분류 단계의 프롬프트·응답 스키마·적용 규칙, 새 과제 제안 큐, 초기 부트스트랩, 이름 병합 거버넌스, 업무 유형 판정, 라벨 신뢰도, 사용자 수정과 규칙 학습 |
| 소유하지 않는 것 | 단위업무 인스턴스의 **형성·경계·투입·MM**(`WORKTIME_METHOD.md` 소관 — 이 문서는 그 인스턴스에 라벨만 붙인다), 레지스트리의 운반·버전 관리·HTTP(`TEAM_AND_BUNDLE.md` §3.10·§5.3), 정제·가명화 규칙(`PRIVACY.md`), 브리지 L0~L3(전송·봉투·패킹·저널 — `COPILOT_BRIDGE.md`), 워크플로우 단계 마이닝·agentic 매칭 판정(워크플로우·분석 명세) |
| 상위 결정 | 오케스트레이터 결정 메모 §1(운영 원칙)·§4(명칭)·§5(코파일럿은 시간을 계산하지 않음)·§6(코파일럿 5계층)·§8(보고서)·§9(품질)·§10.4(팀 묶음 제목)·§10.5(온톨로지·agentic 카탈로그) |
| 근거 | 이전 판 조사 `hierarchy-reports.md`(LM20 계층 규율 taxonomy·LM24 snap·pair_score·cluster2·L1_META), `copilot.md`, `lessons.md`, `critic.md`(PM·PL 방향 축, 간트 계층), `other-lm26.md`(별개 프로젝트 조사 — 분류 부담 축소·반복 분류 규칙 학습 제안) |
| 형제 명세 계약 | `WORKTIME_METHOD.md` §1.1(계층 용어)·§2.2(`Msg.proj`·`DocE.proj`)·§4.5(과제 충돌 = 연결 금지)·§4.11(`unit_id`)·§5.4(버킷)·§6.1(`rollup`)·부록 A(`UnitTask`) / `COPILOT_BRIDGE.md` §2.5(`ai_in`·`ai_out`)·§6.2(프롬프트 골격)·§6.5(필드 명세 언어)·§8.0.3(B14 레지스트리를 프롬프트에 싣는 규칙)·§8.3(`task_label`)·§8.8(예약 `taxonomy_bootstrap`) / `TEAM_AND_BUNDLE.md` §0.4 R-8(`role_id`)·§2.3(`projects`·`proposals`·`roles`·`units`)·§3.10(레지스트리 운반)·§5.3(오프라인) / `PRIVACY.md` §8(사전 가명화 `[과제:ID]`)·§9.3(`keyed`)·§9.6(사람 사전)·§13(게이트)·§14(팀 라벨 검사) |
| 참조 구현 | `scratchpad\lm26_survey\design\hierarchy_lm27\hier_ref.py`(분류기·명명·프롬프트 조립·검증·병합·학습, 표준 라이브러리만) · `scenarios.py`(§15 시나리오 46개 → `golden.json`) · `make_examples.py` → `spec_prompt_task_label.txt`·`spec_prompt_bootstrap.txt`(조립된 프롬프트 실물). 이 문서의 수치(점수·글자 수·묶음 크기)는 그 참조 구현으로 계산했다(`lm26_survey` 는 작업 당시 임시 폴더 이름일 뿐 제품명과 무관) |
| 런타임 | 동봉 CPython 3.11 embeddable, **표준 라이브러리만**(JSON 스키마 검증도 손으로 쓴 검증기). PowerShell 5.1 은 이 문서 범위에서 쓰지 않는다 |
| 자리표시자 | 사람 홍길동·김철수, 과제 과제A~과제F(`P-0007` 등), 고객사A(`C01`), 협력사(`V01`), 도메인 `example.com`·`custa.example`. 실명·계정·이메일·사내 코드네임 없음. agentic 카탈로그 예시는 중립 예시뿐이다 |

---

## 0. 요약 — 내 업무가 어떻게 분류되는가 (사용자용 한 페이지)

1. **네 층과 한 꼬리표.** LM27 은 내 시간을 `업무 영역 → 과제 → 역할 업무 → 단위 업무` 네 층으로 정리하고, 단위 업무마다 `업무 유형`(개발·사무·현장·PM·PL·지원·교육) 꼬리표를 따로 붙입니다. 요구서의 '큰 업무 / 중간 업무 / 단일 업무 / 업무분류'를 각각 이 이름으로 바꿨습니다.
2. **업무 영역은 다섯 개로 고정**입니다: 개발 프로젝트 · 양산 프로젝트 · 외부 업무지원 · 공통 업무 · AX 프로젝트. 어느 쪽인지 모르면 '미분류'로 숨기지 않고 보여 줍니다.
3. **과제는 팀이 정한 번호(`P-0007`)로 셉니다.** 과제 이름·별칭·코드네임은 팀장이 팀 서버의 '레지스트리'에 적고, 각 PC 는 분석 전에 받아 씁니다. 사람마다 과제 이름을 따로 지어내지 않으므로 같은 과제가 여러 이름으로 갈려 MM 이 부풀지 않습니다.
4. **역할 업무 = 과제 × 분야 × 기능**입니다(예: 과제A의 광학·해석). 분야(기구·회로·SW·광학…)와 기능(설계·해석·시험·외주·구매·문서·회의…)은 정해진 목록에서만 고릅니다.
5. **단위 업무는 시간 엔진이 만든 '의뢰→작업→보고' 묶음**입니다. 이 문서는 거기에 과제·역할·유형·짧은 제목을 붙이기만 하고, 시간·시작·종료에는 손대지 않습니다.
6. **먼저 규칙, 그다음 코파일럿.** 메일 제목의 과제 표기, 레지스트리 키워드, 거래처 도메인, 작업 폴더, 쓰던 프로그램으로 대부분 정합니다. 규칙으로 못 정한 것만 코파일럿에게 "이 목록에서 고르고 짧은 제목을 달아 달라"고 묻습니다. 코파일럿이 모르는 새 과제를 말하면 바로 쓰지 않고 '새 과제 제안'으로 쌓아 두었다가 사람이 확정합니다.
7. **고치면 배웁니다.** 보고서에서 분류를 고치면 그 메일 스레드·문서·특징 낱말을 규칙으로 기억해 다음 분석부터 같은 실수를 하지 않습니다. 잘 안 맞는 규칙은 스스로 물러납니다.
8. **애매한 것은 묻습니다.** 투입이 큰데 과제를 못 정한 업무, 규칙과 코파일럿이 엇갈린 업무, 이름이 비슷한 새 과제 제안은 '확인 질문'으로 띄웁니다. 답하지 않아도 분석은 그대로 진행됩니다.
9. **코드네임은 밖으로 나가지 않습니다.** 코파일럿에게는 과제 번호와 팀이 적은 중립 설명만 보내고, 메일 속 코드네임은 `[과제:P-0007]` 로 바뀐 채 갑니다. 레지스트리가 비어 있는 첫 사용 때는 먼저 내 PC 에서 '과제 이름 후보'를 확인하고 나서 코파일럿 단계를 엽니다.

---

## 1. 계층 모델

### 1.1 다섯 개체와 명칭

요구서는 '큰 업무·중간 업무'를 가칭으로 두고 적절한 이름이 있으면 바꿔 달라고 했다. 결정 메모 §4 의 명칭을 확정한다.

| 요구서 표현 | LM27 명칭 | 영문 식별자 | 정체 | 개수·형식 | 누가 정하나 |
|---|---|---|---|---|---|
| 큰 업무 | **업무 영역** | `domain` | 고정 범주 | 5종 + 미분류: `DEV`·`MP`·`EXT`·`COM`·`AX`·`UNC` | 코드(고정). 레지스트리는 설명·키워드만 덮어쓴다 |
| (요구서에 없음 — 필수 층) | **과제** | `project` | 레지스트리 개체 | `P-\d{4}`(팀), `L-\d{4}`(개인 로컬), `P-99\d{2}`(예약 '영역 일반') | 팀장(레지스트리). 개인은 로컬 과제·제안만 |
| 중간 업무 | **역할 업무** | `role` | (과제, 분야, 기능) 세 값의 조합 | `role_id` = `r_` + 6hex(§1.4) | 결정적 계산(라벨 세 값에서) |
| 단일 업무 | **단위 업무** | `unit` | 시간 엔진이 만든 인스턴스 | `unit_id` = `u_` + 10hex | `WORKTIME_METHOD.md` §4(이 문서는 라벨만) |
| 업무분류 | **업무 유형** | `wtype` | 계층과 직교하는 꼬리표(패싯) | 어휘 7종(+확장) | 규칙 → 코파일럿 → 사람 |

부속 꼬리표 두 개를 더 둔다. 둘 다 계층을 바꾸지 않는다.

| 꼬리표 | 값 | 뜻 | 팀 묶음 |
|---|---|---|---|
| `ax_link` | bool | AX 가 아닌 영역의 단위업무에 AI 활용·자동화 성격이 있음(§10.3). MM 은 원래 영역에만 계상 | `units[].ax_link`(있음) |
| `stance`(참여 방식) | `DO` 실무 · `COORD` 조율 · `REVIEW` 검토 · `LEAD` 주도 | PM/PL 이 '유형'인지 '그 업무에서의 역할'인지 둘 다 기록하라는 조사 결론(hierarchy-reports open Q)에 따라 유형과 분리(§10.2) | 보내지 않음(개인 보고서 전용, v1) |

### 1.2 업무 영역 — 고정 메타 표(단일원)

LM24 `L1_META` 패턴을 그대로 쓴다: 영역의 이름·색·순서·설명·프롬프트 문구·규칙 키워드는 **`lm27/hier/vocab.py` 의 `DOMAIN_META` 한 표**에서만 파생한다. 화면(JS)·보고서·프롬프트·규칙은 접근 함수(`domain_name`·`domain_color`·`domain_order`·`domain_prompt_line`·`domain_keywords`)만 쓴다(lint 관문 G-H11 — 이 표 밖에서 영역 이름 문자열·색 하드코딩 금지).

| 코드 | 이름 | 순서 | 색 | 설명(프롬프트·화면 공용) |
|---|---|---|---|---|
| `DEV` | 개발 프로젝트 | 0 | `#2a78d6` | 포트폴리오 확장을 위한 제품 개발(선행·신제품·요소기술) |
| `MP` | 양산 프로젝트 | 1 | `#e08a00` | 사업을 위한 양산 이관·양산 대응·생산 지원 |
| `EXT` | 외부 업무지원 | 2 | `#0e8c7a` | 팀 직접 업무가 아닌 외부 지원(국책·산학·포럼·파견·교육) |
| `COM` | 공통 업무 | 3 | `#8b929b` | 회계·재무·예산·실험실 관리·특허·정보보안·총무 등 팀 운영 |
| `AX` | AX 프로젝트 | 4 | `#6c4fb8` | AI 를 활용한 업무 효율화·자동화(개발·양산과 연계하거나 별도) |
| `UNC` | 미분류 | 9 | `#c0c4cc` | 영역·과제를 정하지 못함(숨기지 않고 보인다) |

- 영역은 늘리지 않는다(요구서의 다섯 범주가 팀 보고서 1급 축). 레지스트리 `domain_meta` 는 `desc`·`keywords_add`·`keywords_remove` 만 덮어쓸 수 있다(§2.3.7). 새 코드를 넣은 레지스트리는 검증 오류 `bad_domain`.
- **스냅**: 바깥에서 들어온 영역 문자열(코파일럿 답·옛 파일·수동 입력)은 `snap_domain(s)` 로만 받는다. ① 코드 완전 일치 → ② 이름 완전 일치(`ukey` 비교, §9.2) → ③ 동의어 표 → ④ 모호하면 `""`(억지로 찍지 않는다 — LM24 snap1). 동의어 표(내장): 개발·선행·신제품·요소기술 → DEV / 양산·양산이관·생산·제조 → MP / 외부지원·국책·산학·대외 → EXT / 공통·사무·일반·운영 → COM / AX·ai·자동화·agentic → AX. LM24 의 '지원·교육 → 공통' 동의어는 **폐기**한다(외부 업무지원과 충돌 — hierarchy-reports pitfall).

### 1.3 과제

- 과제는 **정확히 하나의 영역**에 속하고, 그 소속은 레지스트리에 고정한다(코파일럿은 제안만). 집계 키는 이름이 아니라 ID 다. 이름은 표시 라벨일 뿐이다.
- ID 세 가지:

| ID 형식 | 출처 | 팀 묶음에서 | 비고 |
|---|---|---|---|
| `P-0001`~`P-9899` | 팀 레지스트리 | `projects[].project_id`·`roles[].project_id` 그대로 | `TEAM_AND_BUNDLE.md` §3.10, `PRIVACY.md` §14.2 `PROJECT_ID` |
| `P-9901`~`P-9905` | **예약 '영역 일반' 과제**(코드에 내장, 모든 레지스트리에 자동 주입) | 그대로(형식이 `PROJECT_ID` 와 같다) | 과제는 모르지만 영역은 아는 업무를 담는 자리. 레지스트리에 이 범위(`P-99xx`) 과제를 직접 만들 수 없다(`reserved_id`) |
| `L-0001`~`L-9999` | 개인 로컬 레지스트리(§3.3) | **project_id 로 보내지 않는다** → `proposals[]`(제안)로 보낸다 | 내 PC 에서만 과제로 쓰고 팀에는 제안으로 간다 |

- 예약 과제 표:

| ID | 영역 | 표시 이름 | 프롬프트 설명 |
|---|---|---|---|
| `P-9901` | DEV | 개발 프로젝트 일반 | (개발 프로젝트 — 과제 미지정) |
| `P-9902` | MP | 양산 프로젝트 일반 | (양산 프로젝트 — 과제 미지정) |
| `P-9903` | EXT | 외부 업무지원 일반 | (외부 업무지원 — 과제 미지정) |
| `P-9904` | COM | 공통 업무 일반 | (공통 업무 — 과제 미지정) |
| `P-9905` | AX | AX 프로젝트 일반 | (AX 프로젝트 — 과제 미지정) |

  예약 과제를 둔 이유: 팀 묶음의 `roles[]` 는 과제 ID 나 제안 ID 가 없으면 영역을 실을 칸이 없어 `UNC` 가 된다(`TEAM_AND_BUNDLE.md` §4.4). '8월 예산 정산'처럼 영역은 분명한데 과제 등록이 없는 업무를 공통 업무로 계상하려면 과제 자리가 필요하다. 팀장이 '예산 관리' 같은 공통 과제를 등록하면 그쪽으로 옮겨 간다(§6.6 재질의).
- 상태 `status`: `active`(분류 대상) · `proposed`(팀장이 검토 중 — 분류 후보에 넣지 않음) · `retired`(종료 — 새 분류 후보에서 뺌, 옛 라벨은 유지). `merged_into`: 팀장이 두 과제가 같다고 정하면 한쪽에 단다. 분류기는 매칭 결과를 `resolve(id)` 로 사슬 끝 대표 ID 로 바꿔 쓰고, 팀 서버도 취합 때 같은 사슬을 따른다(`TEAM_AND_BUNDLE.md` §3.10).

### 1.4 역할 업무

- 역할 업무 = **(과제, 분야, 기능)**. 과제 자리에는 `project_id`(P-…) 또는 `proposal_id`(pr_…, 제안 과제) 또는 `"UNC"`(과제·영역 모두 모름)가 온다.
- `role_id = "r_" + sha256("LM27.role|" + (project_id 또는 proposal_id 또는 "UNC") + "|" + field_code + "|" + func_code)[:6]` — `TEAM_AND_BUNDLE.md` §0.4 R-8 식 그대로. **분야·기능 자리에는 어휘 코드**(`OPT`, `ANALYSIS`)를 쓴다(표시 이름이 바뀌어도 ID 가 바뀌지 않게 — §16 정합 요청 X1). 예: `("P-0007", "OPT", "ANALYSIS")` → `r_8412d7`(참조 구현 H41).
- 한 사람이 한 과제에서 여러 분야·기능을 맡을 수 있다(역할 여러 개). 한 단위업무는 **정확히 하나의 역할**에 속한다(H-I1).
- 닫힌 어휘는 §2.3.4 의 `vocab.fields`·`vocab.functions`. 저장소 기본값(내장)은 아래와 같고, 팀 레지스트리가 항목을 더하거나(코드 새로), 이름·키워드를 고치거나, `status: retired` 로 숨길 수 있다. 내장 코드를 지울 수는 없다(옛 라벨 해석 보장).

**분야(field) 내장 기본값**

| 코드 | 이름 | 키워드(어휘 키워드 — `head` 모드, §4.3) | 앱 힌트(카탈로그 `app_id`·범주) | 확장자 힌트 |
|---|---|---|---|---|
| `MECH` | 기구 | 기구·기구설계·하우징·브라켓·금형·사출·도면·공차·체결·판금 | CAD 범주(SolidWorks·Creo·CATIA·NX·Inventor·AutoCAD) | .prt .asm .sldprt .sldasm .step .stp .igs .dwg .catpart .x_t |
| `ELEC` | 회로 | 회로·전원·pcb·아트웍·하네스·emc·부품선정·회로도 | EDA 범주(Altium·OrCAD·KiCad·LTspice·PADS·Allegro), FPGA 범주 | .sch .schdoc .pcbdoc .brd .dsn .kicad_pcb .asc |
| `SW` | 소프트웨어 | 소프트웨어·sw·펌웨어·코드·빌드·릴리즈·버그·알고리즘 | IDE·SW 범주(VS Code·Visual Studio·Eclipse·Keil·IAR·PyCharm) | .c .cpp .h .py .cs .java .js .ts |
| `OPT` | 광학 | 광학·렌즈·광정렬·광원·수광·광경로 | 광학 범주(Zemax·CODE V·LightTools·SPEOS) | .zmx .zos .seq |
| `THERM` | 열 | 열해석·방열·온도·발열·냉각 | Icepak·FloTHERM | — |
| `REL` | 신뢰성 | 신뢰성·수명·환경시험·진동·충격·내구 | — | — |
| `PROC` | 공정 | 공정·생산기술·조립·지그·수율·라인 | — | — |
| `QA` | 품질 | 품질·불량·8d·고객불만·입고검사·ppap | — | — |
| `SYS` | 시스템 | 시스템·요구사항·사양·아키텍처·사양서 | — | — |
| `ETC` | 기타 | — | — | — |

**기능(func) 내장 기본값**

| 코드 | 이름 | 키워드 | 구조 신호(§4.8) |
|---|---|---|---|
| `DESIGN` | 설계 | 설계·도면·모델링·레이아웃·아트웍 | CAD·EDA 귀속 분 |
| `IMPL` | 구현 | 구현·코딩·빌드·디버깅·포팅 | IDE 귀속 분 |
| `ANALYSIS` | 해석·분석 | 해석·시뮬레이션·분석·계산 | 해석(sim) 귀속 분, 해석 결과 파일 |
| `TEST` | 시험·검증 | 시험·평가·측정·검증·테스트·실험·성적서·입고검사 | 계측 범주 귀속 분 |
| `OUTSRC` | 외주 관리 | 외주·용역·업체관리 | `[협력사:ID]` 토큰 |
| `PURCHASE` | 구매·발주 | 구매·발주·견적·납기·입고 | — |
| `DOC` | 문서·보고 | 보고서·문서·작성·보고자료·발표자료 | REPORT_ONLY 업무, 사무 앱 비중 ≥ 0.6 |
| `MEET` | 회의·조율 | 회의·미팅·조율·협의 | 조율형(COORD) 업무, 회의 귀속 비중 ≥ 0.5 |
| `PM` | 과제 관리 | 일정·마일스톤·wbs·과제관리·착수·종료보고 | 조율형(COORD) 업무 |
| `TRANSFER` | 양산 이관 | 양산이관·이관·초도품 | — |
| `SUPPORT` | 기술 지원·대응 | 대응·지원·이슈대응·고객대응 | — |
| `STUDY` | 조사·학습 | 조사·동향·벤치마킹·학습·수강 | — |
| `ADMIN` | 행정·사무 | 정산·품의·결재·신청·등록 | — |
| `ETC` | 기타 | — | — |

LM24 의 '활동 9종'(설계/해석·시뮬레이션/SW개발/검증·평가/입고검사·현장/자재·발주/불량·대응/회의·협업/문서·보고)을 기능 어휘로 펼쳐 계승했다(`SW개발` → `IMPL`, `입고검사·현장` → 기능 `TEST` + 유형 `FIELD`, `불량·대응` → 분야 `QA` + 기능 `SUPPORT`).

### 1.5 단위 업무 — 시간 방법론의 정의를 그대로 따른다

`WORKTIME_METHOD.md` §1.1 의 정의를 바꾸지 않고 옮긴다:

> **단위 업무**(unit task) = 단일 업무. 시작 근거·종료 근거·투입 슬롯을 가진 **인스턴스**. 같은 일의 재의뢰는 같은 인스턴스의 차수(cycle).

- 인스턴스는 시간 코어의 `build_tasks()`(`WORKTIME_METHOD.md` §4)가 만든다. 종류 `kind` ∈ `S1`(받은 의뢰) · `ACK`(수락으로 시작) · `COORD`(내가 보낸 지시 — 조율형) · `SELF`(자체 업무) · `APP`(문서 키 없는 공학 앱 업무) · `REPORT_ONLY`(단발 보고) · `MANUAL`(수동 기록). 경계 근거 코드(S1·S1o·S2a·S2M·S2m·S2p / E1·E1i·E1d·E2h·E2l·E3M·E3c·E3i·NEXT_REQ·OPEN), 등급(A~E·O·Z·M), 상태(closed·estimated·open·not_started)도 그 문서가 정한다.
- `unit_id = "u_" + keyed(kr, "unit", <시작 근거 키>, 10)`(`WORKTIME_METHOD.md` §4.11). **이 문서는 unit_id 를 만들거나 바꾸지 않는다.**
- 이 문서가 단위업무에 하는 일은 **라벨 붙이기 하나**다: `UnitTask.labels`(부록 A 의 필드)를 채운다. 인스턴스를 만들거나·쪼개거나·합치지 않고, 시작·종료·차수·투입·등급을 읽기만 한다(H-I5). §5 의 '명명 군집'은 **이름을 같게 붙이기 위한 묶음**일 뿐 인스턴스를 합치지 않는다(군집 안의 단위업무는 각자 `unit_id`·투입·리드타임을 그대로 가진다).
- 시간 코어가 분류에서 받는 것은 **증거 단위 과제 꼬리표**(`Msg.proj`·`DocE.proj`) 하나뿐이다(§4.5). 이 꼬리표는 결정적 규칙에서만 나온다 — 코파일럿 답은 시간 코어로 되먹이지 않는다(H-I6).
- 수동 기록(`manual`)에 사용자가 적은 `project_id`·`role_field`·`role_func`(`PRIVACY.md` §10.2)는 `MANUAL` 업무의 라벨로 바로 쓴다(출처 `user`).

### 1.6 업무 유형(패싯)

| 코드 | 이름 | 뜻(판정 규칙은 §10.1) |
|---|---|---|
| `DEV` | 개발 | 공학 앱(CAD·해석·EDA·IDE·계측)으로 산출물을 만드는 일 |
| `OFFICE` | 사무 | 문서·메일·정산·행정 중심의 일 |
| `FIELD` | 현장 | 라인·입고검사·고객사 방문·설치·시운전 등 PC 밖 현장 업무 |
| `PM` | PM | 일정·예산·고객·계약을 다루는 과제 관리(조율형 + 일정·외부 신호) |
| `PL` | PL | 사내 기술 리드 — 지시·검토로 다른 사람의 기술 작업을 이끄는 일(조율형 + 사내) |
| `SUPPORT` | 지원 | 다른 팀·외부의 요청을 돕는 일(외부 업무지원 영역의 비개발 업무 포함) |
| `EDU` | 교육·학습 | 교육·세미나·학회 참석·강의 |

- 유형은 계층과 **직교**한다: 같은 역할 업무 안의 단위업무들이 서로 다른 유형을 가질 수 있다. MM 롤업은 유형 축으로도 따로 한다(`WORKTIME_METHOD.md` §6.1 `MM(m, x)`).
- 코드 `DEV`·`PM` 이 영역·기능 어휘의 같은 철자 코드와 겹치지만 **어휘 이름공간이 다르다**(영역·분야·기능·유형은 각자 집합). 프롬프트는 이름공간마다 다른 머리표(`[업무영역]`·`[기능]`·`[업무유형]`)로 싣는다.

### 1.7 미분류의 세 종류(서로 섞지 않는다)

| 이름 | 어디 | 뜻 | 보고서 |
|---|---|---|---|
| 영역 미분류 `UNC` | 단위업무 라벨 | 단위업무는 있는데 과제·영역을 정하지 못함(규칙·코파일럿·사람 모두 미결) | 영역 막대의 '미분류' 칸. 확인 질문 H01 |
| 과제 미지정 `P-99xx` | 단위업무 라벨 | 영역은 알지만 등록 과제가 없음 | 해당 영역 안의 '<영역> — 과제 미지정' 행 |
| 근무 중 미분류(버킷 5종) | 시간 코어 | 어느 단위업무에도 귀속되지 않은 근무 시간(`B_GENERIC`·`B_COMM`·`B_MEET`·`B_OFFPC`·`B_UNKNOWN`) | '근무 중 미분류' 별도 막대(`WORKTIME_METHOD.md` §5.4). 이 문서는 버킷을 분류하지 않는다 |

- `B_MEET` 의 회의 시리즈에 레지스트리 키워드가 맞아도 **MM 을 과제로 옮기지 않는다**. 개인 보고서의 '근무 중 미분류(회의)' 막대 안에 '이 중 과제A 관련으로 보이는 회의 n h' 를 **보조 표시**로만 단다. 옮기면 개인 보고서의 과제 MM 이 팀 묶음(`alloc_daily` 에 버킷이 없다)과 어긋나 개인 = 팀 항등식(`WORKTIME_METHOD.md` §6.6 I2·I3)이 깨진다(§16 정합 요청 X7).

### 1.8 계층 불변식(관문 G-H3 이 검사)

| 번호 | 불변식 | 위반 시 |
|---|---|---|
| H-I1 | 모든 단위업무는 라벨을 정확히 하나 가진다: (과제 자리 1개, 분야 1개, 기능 1개, 유형 1개). 빈 값은 `UNC`·`ETC` 로 채운다 | 코드 결함 — 분석 중단 |
| H-I2 | 과제 → 영역은 레지스트리(또는 예약 표)의 값이다. 라벨의 `domain` 은 과제에서 **유도**하며 따로 저장한 값과 다르면 유도값이 이긴다. 제안 과제는 제안의 `dom_guess`, 과제 없음은 `UNC` | 경고 + 유도값 |
| H-I3 | 롤업 보존: Σ_영역 MM + 근무 중 미분류 MM = 개인 MM(정수 분 표에서, `WORKTIME_METHOD.md` §6.6 I3). 유형 축도 같다 | 분석 중단(fail-closed) |
| H-I4 | `role_id` 는 라벨 세 값에서 R-8 식으로 다시 계산한 값과 같다 | 팀 묶음 빌드 실패 |
| H-I5 | 분류 단계 전후로 단위업무 수·`unit_id`·경계·투입·`alloc_daily` 바이트가 같다 | 분석 중단 |
| H-I6 | 코파일럿 답·제안 이름은 증거 꼬리표(`proj`)·학습 규칙·레지스트리 힌트로 들어가지 않는다 | lint 관문 G-H7 |
| H-I7 | 같은 입력(증거·레지스트리·학습 규칙·수정 기록·저장된 AI 답)이면 같은 라벨·같은 군집·같은 제목 | 관문 G-H1 |

---

## 2. 팀 레지스트리 형식

### 2.1 원칙

1. **ID 가 정본, 이름은 라벨.** 모든 집계·연결은 `P-0007` 같은 ID 로 한다. LM24 의 '사람·PC·실행마다 이름을 지어내고 사후에 7종 캐시로 합치는' 구조를 버린다(hierarchy-reports discard).
2. **코드네임은 레지스트리에만.** 과제 별칭·코드네임·고객사 이름은 팀 레지스트리(팀 서버)와 개인 로컬 레지스트리에만 있다. 저장소 기본값·코드·샘플·문서·프롬프트에는 없다(결정 메모 §1, `PRIVACY.md` §17.3 패키징 lint).
3. **운반·버전·HTTP 는 팀 명세, 뜻은 이 문서.** 형식의 운반 최소형(스키마 이름·`version`·pepper·calendar·members·customers·partners·internal_domains)은 `TEAM_AND_BUNDLE.md` §3.10 이 정하고, 이 절은 **분류에 쓰는 필드의 뜻·형식·검증**을 정한다. 두 문서의 필드는 겹치지 않게 나눴고, 같은 파일 하나(`lm27.registry/1`)에 함께 담긴다.
4. **모든 추가 필드는 선택**이다. 이 절의 필드가 없는 레지스트리(팀 명세 §3.10 예시 그대로)도 유효하고, 분류기는 기본값으로 동작한다.
5. **AI 가 만든 이름은 레지스트리에 자동으로 들어가지 않는다.** 들어가는 길은 팀장의 승인(제안 → 등록)뿐이다(LM24 discovered 순환 폐기).

### 2.2 전체 모양(예시 — 값은 합성)

```json
{
  "schema": "lm27.registry/1",
  "version": 7,
  "updated_at": "2026-10-05T09:00:00+09:00",
  "updated_label": "팀장",
  "team": {"label": "팀A"},
  "pepper": "<64hex — 팀 서버가 응답 때만 합성(팀 명세 §3.7)>",
  "pepper_id": "9f2c01ab",
  "domains": ["DEV", "MP", "EXT", "COM", "AX", "UNC"],
  "domain_meta": {
    "EXT": {"desc": "", "keywords_add": ["기술지도"], "keywords_remove": []},
    "COM": {"keywords_add": ["팀 워크숍"], "keywords_remove": ["교정"]}
  },
  "projects": [
    {"id": "P-0007", "name": "과제A", "domain": "DEV", "status": "active", "merged_into": null,
     "aliases": ["과제A 모듈"], "codenames": ["PROJ-A"], "mask_name": false,
     "keywords": ["브라켓", "광학모듈"], "never": ["과제A 후속"],
     "mail_domains": ["custa.example"], "customers": ["C01"], "partners": [],
     "folders": ["과제A_설계"], "apps": [],
     "default_field": "OPT", "default_func": "", "ax_link": false,
     "shared_docs": ["팀공용_마스터"],
     "copilot_desc": "광학 모듈 신규 개발",
     "period": {"from": "2026-01", "to": ""},
     "adopted": [{"person_key": "p_7fa3c2d19e01", "proposal_id": "pr_3"}],
     "created_at": "2026-03-02", "note": ""},
    {"id": "P-0008", "name": "과제B", "domain": "MP", "status": "active",
     "codenames": ["PROJ-B"], "keywords": ["양산라인", "수율개선"], "customers": ["C01"],
     "copilot_desc": "센서 모듈 양산 대응"},
    {"id": "P-0013", "name": "과제E", "domain": "DEV", "status": "retired", "merged_into": "P-0007",
     "codenames": ["PROJ-E"], "copilot_desc": ""}
  ],
  "members": [{"id": "M003", "label": "홍길동"}],
  "vocab": {
    "fields": [{"code": "MECH", "name": "기구", "keywords": [], "apps": [], "exts": [], "status": "active"},
               {"code": "PHOTONICS", "name": "포토닉스", "keywords": ["광집적"], "apps": [], "exts": [],
                "status": "active"}],
    "functions": [{"code": "ANALYSIS", "name": "해석·분석", "keywords": ["해석"], "status": "active"}],
    "activity_types": [{"code": "DEV", "name": "개발", "status": "active"}],
    "step_types": [{"code": "REQ_IN", "name": "의뢰수신", "status": "active"}]
  },
  "rules": [
    {"id": "TR001", "if": {"token": "광정렬"}, "then": {"project": "P-0007"}, "w": 2.0, "status": "active",
     "note": "광정렬은 과제A 에서만 한다"},
    {"id": "TR002", "if": {"sender_label": "고객사:C01"}, "then": {"func": "SUPPORT"}, "w": 1.0, "status": "active"},
    {"id": "TR003", "if": {"ext": ".zmx"}, "then": {"field": "OPT"}, "w": 2.0, "status": "active"}
  ],
  "never_pairs": [["과제A 후속", "과제A"]],
  "agents_meta": {"catalog_version": "ag-3", "axes": {"X1": "설계·해석 자동화", "X2": "문서·보고 자동화"}},
  "agents": [{"id": "AG003", "name": "문서 초안 작성", "axis": "X2", "status": "running",
              "desc": "회의록·보고서 초안을 만든다", "copilot_desc": "보고서 초안 작성 도우미",
              "step_types": ["DOC_WRITE"], "inputs": ["메일 본문 요약"], "outputs": ["보고서 초안"],
              "keywords": ["초안"], "owner_label": ""}],
  "calendar": {"version": "kr-2026.3", "std_day_min": 480, "…": "팀 명세 §3.10·시간 명세 §2.5 소관"},
  "internal_domains": ["example.com"],
  "customers": [{"id": "C01", "names": [], "domains": []}],
  "partners": []
}
```

### 2.3 필드 정의

#### 2.3.1 최상위

| 필드 | 형 | 필수 | 기본 | 소유 | 뜻 |
|---|---|---|---|---|---|
| `schema` | str | 예 | — | 팀 | `"lm27.registry/1"` |
| `version` | int ≥ 0 | 예 | — | 팀 | `PUT` 마다 +1(§2.5) |
| `updated_at`·`updated_label`·`team` | — | 아니오 | — | 팀 | 표시용 |
| `pepper`·`pepper_id` | str | 아니오 | — | 팀·PRIVACY | 동료 가명 키. 분류기는 읽지 않는다 |
| `domains` | list | 아니오 | 6종 고정 | 이 문서 | 있으면 정확히 `["DEV","MP","EXT","COM","AX","UNC"]` 이어야 한다(다르면 `bad_domains`) |
| `domain_meta` | obj | 아니오 | `{}` | 이 문서 | 영역별 설명·키워드 덮어쓰기(§2.3.7) |
| `projects` | list ≤ 500 | 아니오 | `[]` | 이 문서(+팀 최소형) | §2.3.2 |
| `members` | list | 아니오 | `[]` | 팀 | 팀 명세 §3.11 |
| `vocab` | obj | 아니오 | 내장 기본값 | 이 문서 | §2.3.4 |
| `rules` | list ≤ 500 | 아니오 | `[]` | 이 문서 | 팀 공용 규칙(§2.3.5) |
| `never_pairs` | list ≤ 500 | 아니오 | `[]` | 이 문서 | 절대 합치면 안 되는 이름 쌍(§9) |
| `agents_meta`·`agents` | obj·list ≤ 200 | 아니오 | `{}`·`[]` | 이 문서 | agentic 카탈로그(§2.3.6) |
| `calendar` | obj | 아니오 | — | 시간·팀 | 분류기는 읽지 않는다 |
| `internal_domains`·`customers`·`partners` | list | 아니오 | `[]` | PRIVACY | 사전 가명화. 분류기는 `customers[].id`·`partners[].id` 를 과제 힌트의 참조 대상으로만 쓴다 |
| `public_domain_classes` | obj | 아니오 | 내장(§4.2) | 이 문서 | 외부 기관 도메인 접미사 → 계급(예 `{".ac.kr": "기관"}`) |

#### 2.3.2 `projects[]`

| 필드 | 형·제약 | 기본 | 분류에서의 쓰임 |
|---|---|---|---|
| `id` | `^P-\d{4}$`, `P-99xx` 금지 | 필수 | 집계 키 |
| `name` | str 1~40 | 필수 | 표시 라벨. `mask_name=true` 면 코드네임처럼 가명화 대상 |
| `domain` | `DEV·MP·EXT·COM·AX` | 필수 | 과제의 영역(H-I2) |
| `status` | `active·proposed·retired` | `active` | §1.3 |
| `merged_into` | `P-\d{4}` 또는 null | null | §1.3. 순환 금지 |
| `aliases` | list ≤ 20, 각 2~40자 | `[]` | 평문 별칭 매칭(§4.3 R3) |
| `codenames` | list ≤ 20 | `[]` | 정제기가 `[과제:<id>]` 로 가명화(`PRIVACY.md` §8). 정제 전에 수집된 행에서는 평문 별칭처럼 매칭 |
| `mask_name` | bool | false | `name` 도 코드네임 취급 |
| `keywords` | list ≤ 30, 각 2~40자 | `[]` | 과제 키워드(§4.3 R4, `name` 모드 매칭). **코파일럿에 보내지 않는다** |
| `never` | list ≤ 20 | `[]` | 이 낱말이 증거에 나오면 그 증거에서 이 과제 점수를 −∞(§4.3 R11). 이름 병합에서도 −∞(§9). 코드네임은 정제 뒤 `[과제:ID]` 토큰으로 바뀌므로 never 에는 코드네임을 뺀 구별 낱말(예 '후속'·'2세대')을 적는다(코드네임이 들어 있으면 경고 `never_has_codename`) |
| `mail_domains` | list ≤ 20, `^[a-z0-9.\-]{3,80}$` | `[]` | 상대 메일 도메인 → 과제(R6) |
| `customers` | list ≤ 10, 레지스트리 `customers[].id` | `[]` | `[고객사:C01]` → 과제(R5). 여러 과제가 같은 고객을 가지면 가중을 과제 수로 나눈다 |
| `partners` | list ≤ 10, `partners[].id` | `[]` | `[협력사:V01]` → 과제(R5′) |
| `folders` | list ≤ 20, 폴더 **한 단계 이름**(경로 아님), 2~60자 | `[]` | 작업 폴더 → 과제(R7). 로드 때 개인 키로 해시해 `dir_keys` 와 비교(§4.2) |
| `apps` | list ≤ 10, `APP_ID` | `[]` | 그 과제 전용 프로그램 → 과제(R8, 약함) |
| `default_field`·`default_func` | 어휘 코드 또는 `""` | `""` | 역할 판정의 사전 가점(§4.8) |
| `ax_link` | bool | false | 이 과제의 모든 단위업무에 `ax_link=true`(§10.3) |
| `shared_docs` | list ≤ 20, 문서 이름 줄기 | `[]` | 시간 코어의 '공용 문서' 표식(`WORKTIME_METHOD.md` §4.5) — 로드 때 `fam()` 정규화 후 `fam_key` 로 바꿔 넘긴다 |
| `copilot_desc` | str ≤ 40 | `""` | 코파일럿에 보내는 **유일한** 과제 설명(B14). 코드네임·별칭·이름(mask_name 일 때) 포함 금지(검증 `desc_has_codename`) |
| `period` | `{"from": "YYYY-MM", "to": "YYYY-MM"\|""}` | 없음 | 과제 기간. 기간 밖 증거의 과제 점수 × 0.5(R12) |
| `adopted` | list `{person_key, proposal_id}` | `[]` | 팀장이 누구의 어떤 제안을 이 과제로 받아들였는지(§7.6) |
| `created_at`·`note` | str | — | 표시용 |

#### 2.3.3 정규화 키 `ukey`

이름·별칭·키워드·제안 이름의 비교는 모두 `lm27/hier/names.py` 의 `ukey(s)` 하나로 한다: 구분자(`·・ㆍ‧_-/–—－／`)를 공백으로 → NFKC → 다시 구분자 치환 → 공백 접기 → `casefold()` → 공백 제거. **괄호 꼬리는 남긴다**(`(양산)`·`(선행)` 은 실제 구분, LM24 `ukey2`). 팀 서버의 별칭 중복 검사(`TEAM_AND_BUNDLE.md` §3.10 'ukey: NFKC·공백 접기·casefold')도 이 함수를 쓴다(같은 모듈 임포트 — §16 X2).

#### 2.3.4 `vocab`

```json
{"fields":         [{"code": "MECH", "name": "기구", "keywords": [], "apps": [], "exts": [], "status": "active",
                     "replaced_by": ""}],
 "functions":      [{"code": "DESIGN", "name": "설계", "keywords": [], "status": "active", "replaced_by": ""}],
 "activity_types": [{"code": "DEV", "name": "개발", "status": "active", "replaced_by": ""}],
 "step_types":     [{"code": "REQ_IN", "name": "의뢰수신", "status": "active", "replaced_by": ""}]}
```

| 필드 | 형·제약 | 뜻 |
|---|---|---|
| `code` | `^[A-Z][A-Z0-9_]{1,15}$` | 정본 값. 라벨·`role_id`·팀 묶음·프롬프트가 쓴다 |
| `name` | str 1~20 | 표시 이름(프롬프트에 `코드 이름` 쌍으로 실림) |
| `keywords` | list ≤ 30 | 어휘 키워드(`head` 모드). 팀이 덧붙인 값은 내장 키워드와 **합집합** |
| `apps` | list ≤ 30 `APP_ID` | 분야 힌트 앱(분야만) |
| `exts` | list ≤ 30 `^\.[0-9a-z]{1,8}$` | 분야 힌트 확장자(분야만) |
| `status` | `active·retired` | retired 는 프롬프트·규칙 후보에서 빠지고, 옛 라벨은 `replaced_by`(없으면 `ETC`)로 읽는다 |
| `replaced_by` | 코드 또는 `""` | 퇴역 코드의 대체 |

- **병합 규칙**: 유효 어휘 = 내장 기본값 ⊕ 팀 항목(같은 코드면 팀의 `name`·`status` 가 이기고 `keywords`·`apps`·`exts` 는 합집합) ⊕ 개인 로컬 추가(§3.3, 코드가 `L_` 로 시작).
- **옛 형식(문자열 목록) 호환**: 팀 명세 §3.10 예시처럼 `"fields": ["기구", "회로", "SW"]` 로 온 경우, 로더가 이름으로 내장 코드를 찾아 바꾼다(`ukey` 일치 — `회로` → `ELEC`). 내장에 없는 이름은 결정적 코드 `X_` + sha1(ukey(이름))[:6] 대문자(예 `광학검사` → `X_E42E7B`, 참조 구현 H40)로 만든다. 경고 `vocab_legacy_string` 을 남기고 팀장 화면에 '코드로 바꿔 저장' 버튼을 보인다(분석은 막지 않는다).
- `step_types` 의 의미(단계 유형 목록·판정)는 워크플로우 명세 소관이다. 이 문서는 형식만 정하고, 내장 기본값은 브리지 명세 §8.4 예시 코드(`REQ_IN`·`APP_CAE`·`DOC_XLS`·`MEET`·`REPORT_OUT` …)를 워크플로우 명세가 확정할 때까지 그대로 둔다.

#### 2.3.5 `rules[]` — 팀 공용 규칙

```json
{"id": "TR001", "if": {"token": "광정렬"}, "then": {"project": "P-0007"}, "w": 2.0, "status": "active", "note": ""}
```

| 필드 | 형·제약 | 뜻 |
|---|---|---|
| `id` | `REG_ID`(`^[A-Za-z][A-Za-z0-9_\-]{0,23}$`), 팀 규칙은 `TR` 로 시작 | |
| `if` | 아래 키 중 **정확히 하나** | 조건 |
| `if.token` | str 2~40 | 증거 토큰에 `name` 모드 적중 |
| `if.sender_label` | `PRIVACY.md` §10.2 `sender_label` 형식(`사내`·`고객사:C01`·`협력사:V01`·도메인) | 상대 도메인 계급 |
| `if.domain` | `^[a-z0-9.\-]{3,80}$` | 상대 메일 도메인(하위 도메인 포함) |
| `if.app` | `APP_ID` | 증거의 앱 |
| `if.ext` | `^\.[0-9a-z]{1,8}$` | 문서·첨부 확장자 |
| `if.folder` | 폴더 한 단계 이름 | `dir_keys` 적중(로드 때 해시) |
| `then` | 아래 키 중 **정확히 하나** | 결과 |
| `then.project` | `P-\d{4}`(예약 포함) | 과제 가점 |
| `then.domain` | 영역 코드 | 영역 가점(과제를 못 정할 때만 쓰임) |
| `then.field`·`then.func`·`then.wtype` | 어휘 코드 | 그 축의 가점 |
| `w` | 0.5~6.0 | 가중(기본 2.0 = `hier.rule.w.teamRule`) |
| `status` | `active·off` | |
| `note` | str ≤ 60 | 표시용 |

규칙은 **가점**이다(증거를 덮어쓰지 않는다). 사람이 단위업무에 직접 붙인 라벨만이 모든 것을 이긴다(§6.5).

#### 2.3.6 agentic 카탈로그 `agents[]`·`agents_meta`

LM24 `config\agentic_tasks.json` 의 `{axes, tasks[{id, axis, name, desc}]}` 구조를 레지스트리로 옮기고 필드를 넓힌다(결정 메모 §10.5). 매칭 판정·니즈 산출은 분석 명세 소관이고, 여기서는 형식만 정한다.

| 필드 | 형·제약 | 뜻 |
|---|---|---|
| `agents_meta.catalog_version` | `^[A-Za-z0-9._\-]{1,24}$` | 카탈로그 판(팀 묶음 `generator.catalog_version`·`agentic.catalog_version`) |
| `agents_meta.axes` | `{축코드: 설명 ≤ 60}` | 축(LM24 `axes`) |
| `agents[].id` | `REG_ID`, `AG` 로 시작 | 팀 묶음 `agent_id` |
| `name` | str 2~30 | 표시 이름 |
| `axis` | `agents_meta.axes` 의 키 | |
| `status` | `running`(운영 중 — '진행하는 agentic ai') · `planned`(계획) · `retired` | 매칭 대상은 running·planned, 보고서는 둘을 구분 표시 |
| `desc` | str ≤ 200 | 팀 화면 설명. **코파일럿에 보내지 않는다**(사내 과제 이름이 들어가기 쉽다 — LM24 실측 파일에 사내 계획명이 그대로 있었다) |
| `copilot_desc` | str ≤ 80 | 코파일럿 매칭 단계에 보내는 유일한 설명. `desc_has_codename` 검사 대상 |
| `step_types` | list ≤ 10, `vocab.step_types` 코드 | 적용 단계 유형 |
| `inputs`·`outputs` | list ≤ 5, 각 ≤ 20자 | 입력·출력 형태(서브에이전트 검토의 '정형 입력' 대조) |
| `keywords` | list ≤ 20 | 규칙 사전 점수용 |
| `owner_label` | str ≤ 20 | 표시용 |

저장소 기본값은 **빈 목록**이다. 문서·시험의 예시는 '문서 초안 작성'처럼 어느 회사에나 있는 중립 예시만 쓴다.

#### 2.3.7 `domain_meta` 덮어쓰기

```json
{"EXT": {"desc": "", "keywords_add": ["기술지도"], "keywords_remove": ["교육"]}}
```

- `desc` 가 비어 있지 않으면 내장 설명 대신 쓴다(화면·프롬프트). ≤ 60자, 코드네임 검사.
- 유효 영역 키워드 = 내장(§4.4) ∪ `keywords_add` − `keywords_remove`(개인 로컬의 같은 필드가 마지막에 한 번 더 적용).

### 2.4 JSON 스키마(문서용 — 구현은 손으로 쓴 검증기)

표준 라이브러리에는 JSON Schema 검증기가 없으므로 `lm27/hier/registry_schema.py` 의 `validate_registry(obj, side) -> list[Err]` 가 아래 스키마와 **같은 검사**를 손으로 한다(관문 G-H5 가 이 스키마의 각 제약마다 위반 사례 1개씩을 넣어 확인). 팀 서버 `PUT /api/registry` 검증(`TEAM_AND_BUNDLE.md` §3.10)은 이 함수를 부른다(§16 X2).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "lm27.registry/1",
  "type": "object",
  "required": ["schema", "version"],
  "properties": {
    "schema": {"const": "lm27.registry/1"},
    "version": {"type": "integer", "minimum": 0},
    "updated_at": {"type": "string"},
    "updated_label": {"type": "string", "maxLength": 20},
    "team": {"type": "object", "properties": {"label": {"type": "string", "maxLength": 20}}},
    "pepper": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "pepper_id": {"type": "string", "pattern": "^[0-9a-f]{8}$"},
    "domains": {"const": ["DEV", "MP", "EXT", "COM", "AX", "UNC"]},
    "domain_meta": {"type": "object", "propertyNames": {"enum": ["DEV", "MP", "EXT", "COM", "AX"]},
                    "additionalProperties": {"$ref": "#/$defs/domainOverride"}},
    "projects": {"type": "array", "maxItems": 500, "items": {"$ref": "#/$defs/project"}},
    "members": {"type": "array"},
    "vocab": {"$ref": "#/$defs/vocab"},
    "rules": {"type": "array", "maxItems": 500, "items": {"$ref": "#/$defs/rule"}},
    "never_pairs": {"type": "array", "maxItems": 500,
                    "items": {"type": "array", "minItems": 2, "maxItems": 2,
                              "items": {"type": "string", "minLength": 1, "maxLength": 40}}},
    "agents_meta": {"type": "object", "properties": {
        "catalog_version": {"type": "string", "pattern": "^[A-Za-z0-9._\\-]{1,24}$"},
        "axes": {"type": "object", "additionalProperties": {"type": "string", "maxLength": 60}}}},
    "agents": {"type": "array", "maxItems": 200, "items": {"$ref": "#/$defs/agent"}},
    "calendar": {"type": "object"},
    "internal_domains": {"type": "array", "items": {"$ref": "#/$defs/mailDomain"}},
    "customers": {"type": "array", "items": {"$ref": "#/$defs/party"}},
    "partners": {"type": "array", "items": {"$ref": "#/$defs/party"}},
    "public_domain_classes": {"type": "object", "maxProperties": 50,
                              "propertyNames": {"pattern": "^\\.[a-z0-9.\\-]{2,40}$"},
                              "additionalProperties": {"enum": ["기관", "학교", "공공", "협회"]}}
  },
  "$defs": {
    "pid": {"type": "string", "pattern": "^P-\\d{4}$"},
    "regId": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_\\-]{0,23}$"},
    "code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{1,15}$"},
    "appId": {"type": "string", "pattern": "^[a-z0-9_.\\-]{1,24}$"},
    "mailDomain": {"type": "string", "pattern": "^[a-z0-9.\\-]{3,80}$"},
    "kw": {"type": "string", "minLength": 2, "maxLength": 40},
    "domainCode": {"enum": ["DEV", "MP", "EXT", "COM", "AX"]},
    "domainOverride": {"type": "object", "additionalProperties": false, "properties": {
        "desc": {"type": "string", "maxLength": 60},
        "keywords_add": {"type": "array", "maxItems": 50, "items": {"$ref": "#/$defs/kw"}},
        "keywords_remove": {"type": "array", "maxItems": 50, "items": {"$ref": "#/$defs/kw"}}}},
    "party": {"type": "object", "required": ["id"], "properties": {
        "id": {"$ref": "#/$defs/regId"},
        "names": {"type": "array", "items": {"type": "string", "maxLength": 40}},
        "domains": {"type": "array", "items": {"$ref": "#/$defs/mailDomain"}}}},
    "project": {"type": "object", "required": ["id", "name", "domain"], "properties": {
        "id": {"$ref": "#/$defs/pid"},
        "name": {"type": "string", "minLength": 1, "maxLength": 40},
        "domain": {"$ref": "#/$defs/domainCode"},
        "status": {"enum": ["active", "proposed", "retired"]},
        "merged_into": {"anyOf": [{"$ref": "#/$defs/pid"}, {"type": "null"}]},
        "aliases": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/kw"}},
        "codenames": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/kw"}},
        "mask_name": {"type": "boolean"},
        "keywords": {"type": "array", "maxItems": 30, "items": {"$ref": "#/$defs/kw"}},
        "never": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/kw"}},
        "mail_domains": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/mailDomain"}},
        "customers": {"type": "array", "maxItems": 10, "items": {"$ref": "#/$defs/regId"}},
        "partners": {"type": "array", "maxItems": 10, "items": {"$ref": "#/$defs/regId"}},
        "folders": {"type": "array", "maxItems": 20,
                    "items": {"type": "string", "minLength": 2, "maxLength": 60, "pattern": "^[^\\\\/:*?\"<>|]+$"}},
        "apps": {"type": "array", "maxItems": 10, "items": {"$ref": "#/$defs/appId"}},
        "default_field": {"anyOf": [{"$ref": "#/$defs/code"}, {"const": ""}]},
        "default_func": {"anyOf": [{"$ref": "#/$defs/code"}, {"const": ""}]},
        "ax_link": {"type": "boolean"},
        "shared_docs": {"type": "array", "maxItems": 20, "items": {"type": "string", "minLength": 2, "maxLength": 80}},
        "copilot_desc": {"type": "string", "maxLength": 40},
        "period": {"type": "object", "properties": {
            "from": {"type": "string", "pattern": "^\\d{4}-\\d{2}$"},
            "to": {"type": "string", "pattern": "^(\\d{4}-\\d{2})?$"}}},
        "adopted": {"type": "array", "maxItems": 100, "items": {"type": "object", "required": ["person_key", "proposal_id"],
            "properties": {"person_key": {"type": "string", "pattern": "^p_[0-9a-f]{12}$"},
                           "proposal_id": {"type": "string", "pattern": "^pr_\\d{1,4}$"}}}},
        "created_at": {"type": "string"}, "note": {"type": "string", "maxLength": 200}}},
    "vocabItem": {"type": "object", "required": ["code", "name"], "properties": {
        "code": {"$ref": "#/$defs/code"}, "name": {"type": "string", "minLength": 1, "maxLength": 20},
        "keywords": {"type": "array", "maxItems": 30, "items": {"$ref": "#/$defs/kw"}},
        "apps": {"type": "array", "maxItems": 30, "items": {"$ref": "#/$defs/appId"}},
        "exts": {"type": "array", "maxItems": 30, "items": {"type": "string", "pattern": "^\\.[0-9a-z]{1,8}$"}},
        "status": {"enum": ["active", "retired"]},
        "replaced_by": {"anyOf": [{"$ref": "#/$defs/code"}, {"const": ""}]}}},
    "vocabList": {"type": "array", "maxItems": 100,
                  "items": {"anyOf": [{"$ref": "#/$defs/vocabItem"}, {"type": "string", "maxLength": 20}]}},
    "vocab": {"type": "object", "properties": {
        "fields": {"$ref": "#/$defs/vocabList"}, "functions": {"$ref": "#/$defs/vocabList"},
        "activity_types": {"$ref": "#/$defs/vocabList"}, "step_types": {"$ref": "#/$defs/vocabList"}}},
    "rule": {"type": "object", "required": ["id", "if", "then"], "properties": {
        "id": {"$ref": "#/$defs/regId"},
        "if": {"type": "object", "minProperties": 1, "maxProperties": 1, "properties": {
            "token": {"$ref": "#/$defs/kw"}, "sender_label": {"type": "string", "maxLength": 80},
            "domain": {"$ref": "#/$defs/mailDomain"}, "app": {"$ref": "#/$defs/appId"},
            "ext": {"type": "string", "pattern": "^\\.[0-9a-z]{1,8}$"},
            "folder": {"type": "string", "minLength": 2, "maxLength": 60}}, "additionalProperties": false},
        "then": {"type": "object", "minProperties": 1, "maxProperties": 1, "properties": {
            "project": {"$ref": "#/$defs/pid"}, "domain": {"$ref": "#/$defs/domainCode"},
            "field": {"$ref": "#/$defs/code"}, "func": {"$ref": "#/$defs/code"}, "wtype": {"$ref": "#/$defs/code"}},
            "additionalProperties": false},
        "w": {"type": "number", "minimum": 0.5, "maximum": 6.0},
        "status": {"enum": ["active", "off"]}, "note": {"type": "string", "maxLength": 60}}},
    "agent": {"type": "object", "required": ["id", "name"], "properties": {
        "id": {"type": "string", "pattern": "^AG[A-Za-z0-9_\\-]{0,22}$"},
        "name": {"type": "string", "minLength": 2, "maxLength": 30}, "axis": {"type": "string", "maxLength": 24},
        "status": {"enum": ["running", "planned", "retired"]},
        "desc": {"type": "string", "maxLength": 200}, "copilot_desc": {"type": "string", "maxLength": 80},
        "step_types": {"type": "array", "maxItems": 10, "items": {"$ref": "#/$defs/code"}},
        "inputs": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 20}},
        "outputs": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 20}},
        "keywords": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/kw"}},
        "owner_label": {"type": "string", "maxLength": 20}}}
  }
}
```

**스키마 밖의 의미 검사**(같은 함수가 이어서 한다 — 참조 구현 `validate_registry`, 시나리오 H39):

| 코드 | 검사 | 심각도(`side=server` PUT / `side=client` 로드) |
|---|---|---|
| `dup_id` | 과제·규칙·에이전트·어휘 코드 중복 | 거부 / 뒤의 것 무시 + 경고 |
| `reserved_id` | 과제 ID 가 `P-99\d{2}` | 거부 / 그 과제 무시 |
| `alias_collision` | `name`·`aliases`·`codenames` 의 `ukey` 가 서로 다른 과제끼리 겹침 | 거부 / 먼저 정의된 쪽 유지 |
| `desc_has_codename` | `copilot_desc`(과제·에이전트)·`domain_meta.desc` 에 어느 과제의 코드네임·별칭·(`mask_name` 이면) 이름의 `ukey` 가 부분 문자열로 들어 있음 | 거부 / 그 설명을 `""` 로 |
| `merge_cycle`·`merge_target_missing` | `merged_into` 사슬 순환, 없는 대상 | 거부 / `merged_into` 무시 |
| `retired_merge_target` | `merged_into` 대상이 `retired` 이고 그 대상도 `merged_into` 없음 | 경고 |
| `bad_ref` | `customers`·`partners`·`default_*`·`then.*`·`step_types` 가 없는 ID·코드를 가리킴 | 거부 / 그 값 무시 |
| `generic_keyword` | `keywords`·`aliases` 가 상용구·범용어(`WORKTIME_METHOD.md` §4.1 boilerplate, generic stems, 어휘 키워드)와 `ukey` 일치 | 경고(분류에서 그 낱말 무시) |
| `short_alias` | 별칭·코드네임 한글 < 2자, ASCII < 3자 | 거부 / 무시(`PRIVACY.md` §8.3 과 같은 문턱) |
| `never_has_codename` | `never` 낱말에 어느 과제의 코드네임(`mask_name` 이면 이름)의 `ukey` 가 들어 있음 | 경고(정제 뒤에는 맞지 않는 낱말) |
| `vocab_legacy_string` | 어휘가 문자열 목록 | 경고(§2.3.4 자동 변환) |
| `too_large` | 정규 바이트 > 2MB | 거부 |

### 2.5 버전 규칙

- `version`: 팀 서버가 `PUT` 마다 현재+1 을 요구한다(동시 편집 409 — 팀 명세 §3.10). 클라이언트는 더 큰 `version` 만 채택한다(오프라인 사본 포함, §3.2).
- `schema`: 주판 `lm27.registry/1`. 이 문서의 필드 추가는 모두 선택이므로 주판을 올리지 않는다. 필드의 **뜻**이 바뀔 때만 `/2`.
- **분류 해시** `hier_hash = sha256(canon_bytes({projects(이름·메모·created_at 제외), vocab, rules, never_pairs, domain_meta, public_domain_classes}))[:16]` — 분류 결과에 영향을 주는 부분만. 결과 메타(`hier_meta.json`)·팀 묶음에 싣는 값은 `registry_version`(정수)이고, `hier_hash` 는 재분류 필요 여부 판단(로컬)에만 쓴다.
- 레지스트리가 바뀌면 다음 분석에서 일어나는 일:

| 변경 | 결정적 분류(§4) | 코파일럿 답 재사용(§6.6) | 제안 큐(§7) |
|---|---|---|---|
| 과제 추가 | 다시 계산(매번 전체 재계산) | 이전 답이 `NONE`·`NEW`·`P-99xx` 인 묶음만 다시 묻는다(`regv`) | 별칭 일치 제안 → 자동 대응(`mapped`) |
| 과제 `merged_into` | 매칭 결과를 대표 ID 로 | 재사용(대표 ID 로 읽음) | — |
| 과제 영역 변경 | 라벨의 영역이 따라 바뀜(H-I2) | 재사용 | — |
| 과제 `retired`(병합 없음) | 새 후보에서 빠짐 | 그 과제로 답한 묶음 다시 묻기(`regv`), 답이 오기 전에는 옛 라벨 + 표식 '퇴역 과제' | — |
| 별칭·키워드·폴더·규칙 변경 | 다시 계산 → 증거 꼬리표가 바뀌면 시간 코어 연결도 바뀔 수 있음 | 재사용(규칙 확정이 AI 답을 이긴다, §6.5) | — |
| 어휘 퇴역 | 퇴역 코드 → `replaced_by`/`ETC` | 그 코드로 답한 묶음 다시 묻기 | — |

---

## 3. 배포·오프라인·개인 로컬 레지스트리

### 3.1 받기 — 팀 서버 `/api/registry`

HTTP·ETag·캐시 위치·pepper 분리 저장은 `TEAM_AND_BUNDLE.md` §3.10·§2.3.3 이 정한다. 분류기는 그 결과를 아래 순서로 고르는 함수 하나만 쓴다.

```python
# lm27/hier/registry.py
def load_effective(paths, cfg, now) -> tuple[EffectiveRegistry, RegistryStatus]:
    team, src = None, "builtin"
    r = team_client.fetch_registry(timeout_s=cfg["team.registry_timeout_s"])       # 팀 명세 클라이언트(If-None-Match)
    if r.status == 200 and not blocking(validate_registry(r.obj, side="client")):
        team, src = r.obj, "server"                                                 # 팀 클라이언트가 캐시를 원자 교체한 뒤
    elif r.status == 304:
        team, src = read_json(paths.team_registry_cache), "cache"
    else:                                                                           # 서버 불가(클라우드PC 등)
        cache = read_json(paths.team_registry_cache, default=None)
        off = read_json(paths.offline_registry, default=None)                       # team.offline_dir\lm27_registry.json
        if off and not blocking(validate_registry(off, "client")) and (not cache or off["version"] > cache["version"]):
            team, src = off, "offline"                                              # 팀 클라이언트가 캐시로도 채택(팀 명세 §5.3)
        elif cache:
            team, src = cache, "cache"
    local = read_json(paths.hier_local_registry, default=EMPTY_LOCAL)              # §3.3
    eff = merge(team or BUILTIN_EMPTY, local, cfg)                                  # §3.4 — 예약 과제·내장 어휘 주입 포함
    return eff, RegistryStatus(source=src, version=(team or {}).get("version", 0),
                               fetched_at=..., hier_hash=hier_hash(eff), warnings=eff.warnings)
```

- 캐시 `data\team\registry.json` 은 프로그램 폴더(번들)와 함께 움직인다. 그래서 사내망 PC1 에서 받은 레지스트리가 폴더째 클라우드PC 로 가서 분석에 쓰인다(클라우드PC 에서 팀 서버가 안 닿아도 된다 — 결정 메모 §10.4).
- 화면 표시: "레지스트리 v7(10-03 받음, 서버) 사용 중" / "레지스트리 v7(오프라인 사본)" / "팀 레지스트리 없음 — 초기 상태(§8)". 받은 지 `hier.registry.staleWarnDays`(14일)가 지나면 노란 표식.
- 분석은 **그 순간의 레지스트리 하나로 기간 전체를 다시 분류**한다(라벨은 매 실행 재계산 — 증분 상태 없음). 그래서 과제 병합·영역 변경이 과거 달에도 일관되게 적용된다. 결과 메타와 팀 묶음에 `registry_version` 을 싣는다.

### 3.2 오프라인 사본

- 팀 서버의 `publish_dir` 게시(`<publish_dir>\lm27_registry.json`)와 클라이언트의 `team.offline_dir` 채택 규칙은 `TEAM_AND_BUNDLE.md` §5.3 그대로다(버전이 캐시보다 클 때만, 검증 통과 시).
- 사본도 같은 `validate_registry(side="client")` 를 거친다. 거부 수준 오류(§2.4 표의 '거부' 열 중 `bad_domains`·`too_large`·형식 위반)가 있으면 사본을 버리고 캐시를 쓴다(경고 1줄 — 조용히 삼키지 않는다).
- 패키지 동봉 기본 레지스트리는 **빈 과제·빈 별칭·빈 코드네임·빈 규칙·빈 카탈로그**다(내장 어휘·예약 과제는 코드가 주입하므로 파일에 없다). 패키징 lint 가 확인한다(`PRIVACY.md` §17.3).

### 3.3 개인 로컬 레지스트리 `data\local_only\hier\registry_local.json`

팀 레지스트리를 기다리지 않고 내 PC 에서 분류를 바로잡는 자리다. `data\local_only\` 아래라서 **코파일럿·팀 묶음·패키지에 들어가지 않고**, 프로그램 폴더와 함께 PC 사이를 움직인다(`PRIVACY.md` §3.1 의 local_only 규칙과 같다).

```json
{
  "schema": "lm27.registry_local/1",
  "updated_at": "2026-10-05T10:00:00+09:00",
  "projects": [
    {"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "status": "active",
     "aliases": [], "codenames": ["PROJ-X"], "mask_name": false, "keywords": ["광센서"], "never": [],
     "mail_domains": [], "customers": [], "partners": [], "folders": [], "apps": [],
     "default_field": "OPT", "default_func": "", "ax_link": false,
     "copilot_desc": "광센서 선행 검토", "proposal_id": "pr_2", "maps_to": null,
     "created_from": "user", "created_at": "2026-10-05"}
  ],
  "overlays": {"P-0007": {"aliases": ["A모듈"], "keywords": ["광축"], "never": [], "folders": ["A_시험"],
                          "mail_domains": [], "default_field": ""}},
  "roots": {"R03": "P-0007"},
  "domain_meta": {"COM": {"keywords_add": ["팀 워크숍"], "keywords_remove": []}},
  "vocab_add": {"fields": [{"code": "L_PHOTO", "name": "포토닉스", "keywords": ["광집적"], "maps_to": "OPT"}],
                "functions": [], "activity_types": []},
  "never_pairs": [["광센서 선행", "광센서 양산"]],
  "person": {"default_field": "OPT", "default_func": ""},
  "codename_review": {"done_at": "2026-10-05T10:00:00+09:00", "ignored": ["3f9a1c2e"], "skipped": false}
}
```

| 필드 | 뜻·제약 |
|---|---|
| `projects[]` | 개인 과제. `id` = `L-\d{4}`(로컬 순번), 나머지 필드는 팀 과제(§2.3.2)와 같다. `proposal_id` = 이 과제를 팀에 올릴 때 쓰는 제안 ID(§7). `maps_to` = 팀 과제로 대응된 뒤의 `P-…`(그때부터 이 과제의 라벨은 그 ID 로 읽는다). `created_from` ∈ `user·bootstrap·task_label·codename_review` |
| `overlays{P-id}` | 팀 과제에 내가 덧붙이는 별칭·키워드·never·폴더·메일 도메인·기본 분야. 팀 과제의 `id`·`name`·`domain`·`status` 는 바꿀 수 없다 |
| `roots{R..}` | 수집 감시 루트 ID(`pc_file.root_id`, `PRIVACY.md` §10.2) → 과제(규칙 R7 과 같은 가중). 감시 루트는 PC 마다 사용자가 정하므로 팀 레지스트리에 둘 수 없다 |
| `domain_meta` | §2.3.7 과 같은 형식. 팀 덮어쓰기 뒤에 한 번 더 적용 |
| `vocab_add` | 개인 어휘. 코드는 `L_` 로 시작. `maps_to` = 팀 묶음에 실을 때 바꿀 팀·내장 코드(없으면 `ETC`) — 팀 서버 검증(`roles[].field` 는 레지스트리 어휘)을 통과시키기 위해서다 |
| `never_pairs` | §9 이름 병합의 개인 금지 쌍 |
| `person` | 내 기본 분야·기능(역할 판정의 사전 가점 +1.0). 팀 묶음의 `person.function` 과 같은 값을 쓴다 |
| `codename_review` | 초기 코드네임 검토 완료 여부(§8.1). `ignored` 는 '과제 이름 아님'으로 표시한 후보의 `ukey` sha1 앞 8자 |

- 학습 규칙(`rules_learned.json`)·수정 기록(`corrections.jsonl`)·제안 큐(`proposals.json`)·제목 캐시(`title_cache.json`)는 같은 폴더의 별도 파일이다(§11·§7·§5.4).
- 쓰기는 `lm27.util.fsx.atomic_write`(팀 명세 §0.3) 하나. 읽기는 `read_json`(BOM 허용·중복 키 거부).
- 개인 로컬의 코드네임도 정제기의 사전 가명화 대상이어야 한다: 정제 문맥(`build_context`)이 쓰는 과제 코드네임 사전 = **유효 레지스트리**(팀 ⊕ 개인 로컬)의 `codenames`(+`mask_name` 이름), 토큰 ID 는 `P-…`·`L-…` 그대로(§16 X4).

### 3.4 병합 규칙 — 유효 레지스트리 = 내장 ⊕ 팀 ⊕ 개인 로컬

`merge(team, local, cfg) -> EffectiveRegistry` 는 순수 함수다(같은 입력 → 같은 출력, 순서 무관).

| 대상 | 규칙 | 충돌 시 |
|---|---|---|
| 예약 과제 `P-9901~9905` | 코드가 항상 주입. 팀·개인 파일의 같은 ID 는 무시 | 경고 `reserved_id` |
| 팀 과제 | 그대로. `retired` 이고 `merged_into` 없는 과제는 매칭 후보에서 빠진다(라벨 해석에는 남음) | — |
| 개인 과제 `L-…` | 추가. `maps_to` 가 있으면 그 팀 과제의 별칭처럼 동작하고 라벨은 `maps_to` 로 읽는다 | — |
| 개인 과제 이름·별칭 ↔ 팀 과제 이름·별칭 | `ukey` 가 같으면 **자동 대응**: 개인 과제의 `maps_to` = 그 팀 ID(파일에 기록, 화면에 "광센서 선행 → 팀 과제 P-0021 로 연결됨" 알림) | 팀이 이긴다 |
| 팀 `adopted[]` 에 내 `person_key`·제안 ID | 그 제안을 가진 개인 과제의 `maps_to` = 그 팀 과제 | — |
| `overlays` | 팀 과제의 별칭·키워드·never·폴더·메일 도메인에 **합집합**, 기본 분야는 팀 값이 비었을 때만 | 개인 별칭이 **다른** 팀 과제의 별칭과 `ukey` 같으면 그 개인 별칭을 버리고 경고 `local_alias_conflict` |
| `roots` | 그대로 | 대상 과제가 없으면 무시 |
| 어휘 | 내장 ⊕ 팀(§2.3.4) ⊕ 개인 `vocab_add` | 개인 코드가 팀 코드와 같으면 개인 것을 버림 |
| `rules` | 팀 규칙 + 개인 학습 규칙(§11.4). 둘 다 가점이라 '충돌'은 점수 합으로 해결 | — |
| `domain_meta` | 내장 → 팀 → 개인 순서로 덮기(키워드는 add/remove 를 차례로 적용) | — |
| `never_pairs` | 합집합 | — |
| `agents`·`agents_meta` | 팀만(개인은 카탈로그를 바꾸지 않는다 — 개인의 새 니즈는 분석 산출물) | — |
| `customers`·`partners`·`internal_domains` | PRIVACY 규칙(팀 ∪ `privacy.*` 설정) | PRIVACY §8.3 |

`EffectiveRegistry` 자료구조(구현자가 그대로 옮긴다):

```python
@dataclass(frozen=True)
class ProjectView:
    id: str; name: str; domain: str; status: str; merged_into: str | None; origin: str   # team | local | reserved
    aliases: tuple[str, ...]; codenames: tuple[str, ...]; keywords: tuple[str, ...]; never: tuple[str, ...]
    mail_domains: tuple[str, ...]; customers: tuple[str, ...]; partners: tuple[str, ...]
    folder_keys: frozenset[str]          # folders 를 개인 키로 해시한 값(§4.2) — 평문 폴더명은 들고 다니지 않는다
    apps: tuple[str, ...]; default_field: str; default_func: str; ax_link: bool
    shared_fams: frozenset[str]; copilot_desc: str; period: tuple[str, str] | None; proposal_id: str | None

@dataclass(frozen=True)
class EffectiveRegistry:
    version: int; hier_hash: str; source: str
    projects: dict[str, ProjectView]                 # 예약·팀·개인 모두(ID → 뷰)
    alias_ix: dict[str, str]                         # ukey(이름·별칭·코드네임) → 과제 ID(대표)
    folder_ix: dict[str, str]                        # 폴더 키 → 과제 ID
    root_ix: dict[str, str]                          # root_id → 과제 ID
    vocab: dict[str, dict[str, VocabItem]]           # fields/functions/activity_types/step_types → code → 항목
    domain_kw: dict[str, tuple[str, ...]]            # 영역 → 유효 키워드
    rules: tuple[Rule, ...]                          # 팀 규칙 + 개인 학습 규칙(active 만)
    never_pairs: frozenset[frozenset[str]]           # ukey 쌍
    public_suffix: dict[str, str]
    agents: tuple[Agent, ...]; catalog_version: str
    warnings: tuple[str, ...]
    def resolve(self, pid: str) -> str: ...          # merged_into·maps_to 사슬 끝(순환이면 사슬 안 사전순 첫 ID)
    def domain_of(self, pid: str | None) -> str: ... # 예약 표·과제 영역, None → 'UNC'
    def active_ids(self) -> list[str]: ...           # 분류 후보: 팀 active + maps_to 없는 개인 active(L-…), 예약 제외, ID 정렬
```

### 3.5 레지스트리가 없거나 비었을 때(초기 상태)

- 유효 레지스트리 = 예약 과제 5개 + 내장 어휘 + 내장 영역 키워드. 결정적 분류는 영역 키워드·앱·확장자로 **영역·분야·기능·유형**까지는 정하고, 과제 자리는 `P-99xx` 또는 `UNC` 가 된다.
- 코파일럿 분류 단계는 `hier.copilot.requireCodenameReview` 를 **켰을 때만** 초기 코드네임 검토(§8.1)를 마치거나 건너뛰기를 고른 뒤에 열린다(계약 v1.3 §0.8 V12 — 기본 false: LM24 처럼 바로 판정). 켰는데 검토 전이면 규칙 라벨만 쓰고 화면에 "과제 이름 후보를 확인하면 코파일럿 분류를 켭니다" 한 줄을 띄운다(분석은 막지 않는다).
- 부트스트랩 taxonomy 왕복(§8.2)은 이 상태에서 제안을 만드는 유일한 일괄 경로다.

### 3.6 팀 서버에서의 쓰임

팀 서버는 분류기를 돌리지 않는다. 서버가 이 문서의 모듈에서 쓰는 것은 `validate_registry(side="server")`(PUT 검증), `ukey`(별칭 중복), `EffectiveRegistry.resolve`(취합의 과제 병합 사슬), 예약 과제 표(팀 묶음의 `P-99xx` 를 영역으로 읽기), 그리고 §9.6 의 '팀원 제안 묶기 화면' 계산뿐이다. 개인 로컬 레지스트리는 서버에 가지 않는다.

---

## 4. 결정적 규칙 분류기

### 4.0 흐름과 위치

```text
분석 실행(클라우드PC 또는 분석 담당 PC) — 시간 코어와 맞물리는 순서
  reg  = load_effective()                                  §3
  F    = features_of(records, reg, person_dir, catalog)    §4.1~4.2   정제·병합이 끝난 행만
  tags = tag_evidence(F, reg)                              §4.5       → time.normalize(…, registry=tags) 가 Msg.proj·DocE.proj 로
  tasks, attrib = time.build_tasks(…), time.attribute(…)   (WORKTIME_METHOD §4·§5 — 이 문서 밖)
  UI   = unit_inputs(tasks, F, attrib, catalog)            §4.6
  R    = {u: unit_rule_label(UI[u], reg)}                  §4.7       과제·영역
  FF   = {u: field_func(UI[u], reg, R[u])}                 §4.8       분야·기능
  Y    = {u: decide_wtype(UI[u], FF[u], R[u])}             §10        유형·참여 방식·AX 연계
  G    = name_groups(tasks, R)                             §5
  ai_in = build_task_label_items(G, R, FF, Y, …)           §6.1       규칙 미확정·이름 약함만
  (브리지 run --stages task_label)                         COPILOT_BRIDGE §2.3 호출 지점 3
  L    = apply_labels(R, FF, Y, ai_out, corrections, title_cache)   §6.5
  Q    = hier_queue(L, …);  proposals.update(L, …)         §11.2·§7
  time.month_mm(…); time.rollup(month, L)                  WORKTIME_METHOD §6.1
```

- 결정적 분류는 **매 실행 전체를 다시 계산**한다(빠르다 — 참조 구현 기준 증거 1만 건에 수 초). 캐시하는 것은 코파일럿 답(브리지 저장소)과 제목 캐시뿐이다.
- 코파일럿·브리지가 꺼져 있거나(`bridge.mode=off`) 실패해도 규칙 라벨만으로 끝까지 간다(fail-soft). 이때 라벨 출처는 `rule`·`rule_probable`·`domain_rule`·`none` 이고 보고서에 '코파일럿 미사용' 배지.

### 4.1 증거 레코드 → 분류 특징 `Feat`

입력은 정제기(`PRIVACY.md` §10)를 통과하고 병합(msg_key 중복 제거)이 끝난 공통 증거 레코드다. 원문은 없다.

```python
@dataclass(frozen=True)
class Feat:
    id: str                         # 레코드 id
    kind: str                       # mail | teams | cal | file | win | git | compute | manual | summary
    t: int                          # 근무 시간대 로컬 초(시간 코어와 같은 축) — 기간 밖 판정(R12)용
    toks: frozenset[str]            # tokens_of(text) — §4.3
    ent: dict[str, frozenset[str]]  # {'과제': {...}, '고객사': {...}, '협력사': {...}} — 텍스트의 [과제:ID] 등
    dom_labels: frozenset[str]      # 상대 계급: '사내' | '개인메일' | '고객사:C01' | '협력사:V01' | '기관' | <도메인>
    app: str                        # app_id('' 없음, 'unknown:<exe>' 미상)
    app_cat: str                    # 프로그램 카탈로그 범주(COLLECT_PC §6.1: CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통·'')
    exts: frozenset[str]            # 문서·첨부 확장자
    dir_keys: frozenset[str]        # 상위 폴더 세그먼트 키(§4.2)
    root_id: str                    # 감시 루트 ID('' 없음)
    conv: str                       # thread_key / chat_key('' 없음)
    fams: frozenset[str]            # 문서군 키(doc_key·attach_keys·file_keys, git 은 'repo:<doc_key>')
    manual: dict | None             # manual 행의 {project_id, role_field, role_func} 또는 None
    weight_mult: float = 1.0        # summary(코파일럿 요약 증인) 0.5, 그 밖 1.0
```

| 원천 kind(src) | `text`(토큰 재료) | 그 밖 특징 |
|---|---|---|
| `mail` | `subject_masked` + 첨부 `attach_names_masked` + `categories_masked` | `dom_labels` = 받은 메일 `sender_label` ∪ 상대 계급(아래), `exts`=`attach_exts`, `conv`=`thread_key`, `fams`=`attach_keys` |
| `teams` | 그룹·채널·회의방 `chat_title_masked` + `body_masked` 앞 120자 + `file_names_masked` | `dom_labels`=상대 계급, `conv`=`chat_key`(채널은 답글 루트 `thread_key`), `fams`=`file_keys` |
| `cal` | `subject_masked` + `categories_masked` | `dom_labels`=주최자·참석자 계급(개인 일정·사적 판정은 제외) |
| `pc_file` | `name_masked` | `exts`={`ext`}, `root_id`, `dir_keys`, `fams`={`doc_key`} |
| `pc_session`(`pc.sampler`) | `title_masked`(사무·CAD·해석·EDA·IDE·PDF 창만 채워져 있다) | `app`, `app_cat`, `fams`={`doc_key`}(있을 때) |
| `pc_git` | `msg_masked` | `exts`, `fams`={`'repo:'+doc_key`} |
| `pc_compute` | — | `app`, `app_cat` |
| `manual` | `text_masked` + `work_category` | `manual` = {`project_id`, `role_field`, `role_func`} |
| `*.copilot`(요약 증인) | `text_masked` | `weight_mult=0.5`. 시간 근거는 아니지만 분류 단서로는 약하게 쓴다 |

- **상대 계급**: 레코드의 `counterpart_keys`(who_key)를 로컬 사람 사전(`data\local_only\person_dir.json`, `PRIVACY.md` §9.6)으로 주소 도메인에 대응시킨 뒤 계급으로 바꾼다: 사내 도메인 → `사내`, 고객사 사전 도메인 → `고객사:<id>`, 협력사 → `협력사:<id>`, `public_domain_classes` 접미사(내장 `.ac.kr`·`.re.kr`·`.go.kr`·`.or.kr`·`.edu` → `기관`), 공용 개인 메일 → `개인메일`, 그 밖 → 도메인 소문자(로컬 전용 — 이 값은 프롬프트·팀으로 가지 않는다). 사전에 없는 who_key 는 계급 없음.
- 사적·친목·광고(`priv_class ∈ {private, social}`, `flags.ad`) 행은 분류 특징을 만들지 않는다(시간 코어와 같은 원칙 — `WORKTIME_METHOD.md` §2.1-4).

### 4.2 폴더 힌트 — `dir_keys`

`pc_file` 은 전체 경로를 저장하지 않는다(`PRIVACY.md` §10.2). 폴더로 과제를 알아보려면 **폴더 세그먼트의 키 해시**가 필요하다.

- 요구 열(§16 X3): `pc_file.dir_keys` = 파일의 가까운 상위 폴더 세그먼트 최대 3개(가까운 것부터)에 대해 `"s" + keyed(kr, "path", "seg:" + seg_norm(seg), 16)`. `seg_norm(seg)` = NFKC → casefold → `[\s_\-.]+` 를 `_` 로 → 앞뒤 `_` 제거. 사용자 폴더(`%USERPROFILE%` 이하 표준 폴더 이름 — 바탕 화면·문서·다운로드·OneDrive)와 드라이브 루트는 세그먼트에서 뺀다.
- 레지스트리 `folders`(팀)·`overlays.folders`(개인)는 로드 때 같은 식으로 키를 만들어 `folder_ix` 에 넣는다. 평문 폴더명은 유효 레지스트리 밖으로 들고 다니지 않는다.
- `dir_keys` 열이 없는 옛 행·수집 경로에서는 폴더 규칙만 조용히 빠지고(건수 감사 `hier.no_dir_keys`), 감시 루트 대응(`roots`)과 문서 이름 토큰은 그대로 동작한다.

### 4.3 과제 규칙 표

토큰화와 매칭은 한 모듈(`lm27/hier/match.py`)이다.

```python
TOKEN_RX   = r"\[(과제|고객사|협력사):([A-Za-z][A-Za-z0-9_\-]{0,23})\]"      # 정제기 토큰 문법(PRIVACY §5.2)
SPECIAL_RX = r"\[[^\[\]]{1,40}\]"                                              # 그 밖의 꺾쇠 토큰([사람#…]·[금액]·[이메일@…])
SPLIT_RX   = r"[\s_\-.,/()\[\]+&~:;!?'\"…·「」<>{}|=*#]+"
RE_PREFIX  = r"^\s*((re|fw|fwd|회신|전달|답장)\s*[:：]\s*)+"                   # 대소문자 무시

def tokens_of(text) -> set[str]:
    t = NFKC(text); t = sub(RE_PREFIX, '', t); t = sub(SPECIAL_RX, ' ', t)    # 꺾쇠 토큰은 ent 로 따로 뽑았다
    return {w for w in split(SPLIT_RX, t.lower())
            if len(w) >= 2 and not w.isdigit() and w not in BOILERPLATE
            and not fullmatch(r"v\d+|rev\d+|r\d+|\d{6,8}", w)}
    # BOILERPLATE = WORKTIME_METHOD §4.1 episode.tokens.boilerplate ∪ {안녕하세요, 감사합니다, 드림, 올립니다, 입니다,
    #               했습니다, 해주세요, 주세요, 바랍니다, 진행, 내용, 건으로} — 설정 hier.tokens.boilerplateAdd

def kw_hit(k, toks, mode) -> bool:          # mode = 'name'(과제 키워드·별칭) | 'head'(어휘·영역 키워드)
    parts = [p for p in split(SPLIT_RX, NFKC(k).lower()) if len(p) >= 2]
    if not parts: return False
    def one(p):
        if p in toks: return True
        if has_hangul(p):
            if any(t.startswith(p) for t in toks): return True                  # 조사 붙은 꼴(과제a의) — 앞 경계
            return mode == 'head' and any(t.endswith(p) and len(t) - len(p) <= 3 for t in toks)   # 합성어 머리(열해석 ⊃ 해석)
        if len(p) >= 4 and any(t.startswith(p) or t.endswith(p) for t in toks): return True
        return len(p) >= 5 and any(len(t) >= 4 and SequenceMatcher(None, p, t).ratio() >= 0.9 for t in toks)
    return all(one(p) for p in parts)
    # 예외: 키워드 'ai' 는 토큰이 아니라 원문(소문자)에 정규식 (?<![a-z])ai(?![a-z]) 로 본다
```

- 부분 문자열 전면 허용은 금지다('정렬' ⊂ '재정렬', 'ai' ⊂ 'email' 오탐 실측 — LM24 `projmap._kw_hit`). 한글은 `name` 모드에서 앞 경계만, `head` 모드에서 앞 경계 또는 짧은 접두(≤ 3자) 뒤 꼬리를 허용한다(참조 구현 H43: `정렬⊄재정렬(name)`, `해석⊂열해석(head)`, `과제A⊂과제a의`, `ai⊄email`, `lidar-x` 는 두 조각 모두 일치해야).

**과제 점수 규칙**(증거 하나 `f` 에 대해, 과제마다 가점 합 — `score_projects(f, reg) -> dict[pid, float]`):

| 번호 | 규칙 | 조건 | 가점(설정 키 `hier.rule.w.*`) | 비고 |
|---|---|---|---|---|
| R1 | 과제 토큰 | `f.ent['과제']` 에 그 ID | **6.0** `token` | 정제기가 코드네임을 바꾼 것. `resolve()` 로 대표 ID 에 |
| R2 | 학습 키 규칙 | `f.conv`·`f.fams`·`f.dir_keys` 가 학습 규칙의 키와 같음 | **5.0** `keyRule` | 사람 수정에서 배운 것(§11.4) |
| R3 | 평문 별칭·코드네임 | 유효 레지스트리 `alias_ix` 의 어떤 `ukey` 가 `kw_hit(name)` 이거나 `ukey(text)` 의 부분 문자열(3자 이상) | **4.0** `alias` | 정제 전 수집 행, 개인 별칭(가명화 안 된 overlays.aliases) |
| R4 | 과제 키워드 | 그 과제 `keywords` 중 `kw_hit(name)` 개수 n | `min(2.0 × n, 4.0)` `keyword`·`keywordCap` | 서로 다른 키워드만 센다 |
| R5 | 고객사 | `f.ent['고객사']` 또는 `f.dom_labels` 의 `고객사:C` 가 그 과제 `customers` 에 | `1.5 ÷ (C 를 가진 과제 수)` `customer` | 고객 하나가 여러 과제를 가지면 나눈다(H06: 0.75 씩) |
| R5′ | 협력사 | 같은 식(`partners`) | `1.0 ÷ k` `partner` | |
| R6 | 메일 도메인 | `f.dom_labels` 의 도메인이 그 과제 `mail_domains` 와 같거나 하위 | `1.5 ÷ k` `mailDomain` | |
| R7 | 폴더·감시 루트 | `f.dir_keys ∩ folder_ix` 또는 `root_ix[f.root_id]` | **3.0** `folder` | |
| R8 | 앱 | `f.app ∈` 그 과제 `apps` | 1.0 `app` | |
| R9 | 팀 규칙 | `rules[]` 의 `then.project`, 조건 적중 | 규칙 `w`(기본 2.0 `teamRule`) | |
| R10 | 학습 토큰 규칙 | `active` 학습 토큰 규칙 적중 | 2.5 `learnedToken` | `candidate` 는 쓰지 않음 |
| R11 | never | 그 과제 `never` 중 하나가 `kw_hit(name)` | 그 과제 **−∞**(이 증거에서만) | H05 |
| R12 | 기간 밖 | `f.t` 의 달이 그 과제 `period` 밖 | 그 과제 점수 × 0.5 | |
| R13 | 퇴역 | `status=retired` 이고 `merged_into` 없음 | 후보에서 뺌 | 옛 라벨 해석에는 남음 |

가점은 `f.weight_mult` 를 곱한다(요약 증인 0.5). 점수는 정렬해 쓰며 동률은 과제 ID 사전순.

### 4.4 영역 키워드(과제를 못 정할 때)

`score_domains(f, reg) -> dict[domain, float]`. 과제가 없어도 영역은 알아야 '공통 업무'·'외부 업무지원'의 MM 이 미분류로 새지 않는다.

| 영역 | 내장 키워드(`head` 모드) | 가점/키워드 |
|---|---|---|
| `EXT` | 국책·정부과제·산학·산학협력·공동연구·위탁연구·포럼·학회·세미나·컨퍼런스·파견·교육·강의·강연·워크숍·외부심사·자문·위원회·전시회·기술지도 + 상대 계급 `기관`(1.5) | 2.0 |
| `COM` | 회계·재무·예산·결산·정산·품의·법인카드·자산실사·총무·비품·사무용품·인사·근태·노무·연말정산·실험실·랩관리·장비관리·검교정·교정·안전점검·보건·소방·정보보안·보안점검·보안교육·법정교육·안전교육·사내교육·의무교육·특허·지재권·출원·내부감사·내부통제·팀운영 | 2.0 |
| `AX` | ai(원문 정규식)·llm·gpt·copilot·코파일럿·rpa·에이전트·agentic·에이전틱·프롬프트·자동화·머신러닝·딥러닝·챗봇·rag·생성형 | 1.5 |
| `MP` | 양산·양산이관·생산·라인·수율·공정불량·8d·출하·ppap·초도품·양산대응 | 1.0 |
| `DEV` | 선행·신제품·시제품·프로토·요소기술·개발샘플·목업 | 1.0 |

판정(증거 하나):

1. 모든 적중 `(키워드 길이, 영역, 키워드)` 를 모은다.
2. **긴 키워드가 그 안에 든 짧은 키워드를 덮는다**: '보안교육'이 맞으면 같은 증거의 '교육'(EXT)은 버린다(H08a: 사내 보안교육은 공통 업무).
3. 남은 적중 영역이 둘 이상이면 **우선순위 EXT > AX > COM > MP > DEV 의 첫 영역 하나**만 남긴다. EXT 를 COM 보다 먼저 보는 이유는 LM24 의 '교육·지원 → 공통' 오분류(hierarchy-reports pitfall), AX 를 COM 보다 먼저 보는 이유는 '실험실 자동화'는 사무가 아니라 AX 이기 때문이다(H08c).
4. 그 영역의 점수 = 가점 × min(그 영역 적중 수, 2).

예(참조 구현): '정보보안 보안교육 수강 안내' → COM 4.0 / '산학 세미나 발표 자료' → EXT 4.0 / '실험실 자동화 스크립트' → AX 1.5 / '8월 예산 정산' → COM 4.0 / 'LLM 기반 메일 분류' → AX 1.5.

### 4.5 증거 꼬리표 — 시간 코어에 넘기는 `proj`

```python
def tag_evidence(F, reg) -> dict[str, tuple[str | None, float]]:    # 증거 id·문서군 키 → (과제 ID | None, 최고 점수)
    out = {}
    for f in F:                                                       # 메시지·일정
        sc = score_projects(f, reg); top, second = best_two(sc)       # −∞ 는 후보에서 뺌
        out[f.id] = (top.id, top.v) if top.v >= EV_MIN and top.v - second.v >= EV_MARGIN else (None, top.v)
    for fam, evs in group_by_family(F):                               # 문서군: 그 문서군의 파일·창·첨부 특징을 합집합으로
        f = union_feat(evs);  …같은 판정…;  out['fam:' + fam] = …
    return out
# EV_MIN = hier.rule.evidenceMin(4.0), EV_MARGIN = hier.rule.evidenceMargin(2.0)
```

- 시간 코어는 이 값을 `Msg.proj`·`DocE.proj` 로 받아 **과제가 서로 다르면 연결 금지**, 같으면 +0.7 로 쓴다(`WORKTIME_METHOD.md` §4.5). 잘못된 꼬리표는 맞는 연결을 막으므로 문턱을 보수적으로 둔다: 키워드 하나(2.0)·고객사 하나(≤1.5)로는 붙지 않고, 토큰(6.0)·별칭(4.0)·학습 키(5.0)·키워드 2개(4.0)·폴더 + 키워드(5.0)부터 붙는다(H01~H04·H07·H37).
- 2위와의 차가 2.0 미만이면(두 과제 키워드가 같이 나옴) 붙이지 않는다 — 연결 제약을 걸지 않는 쪽이 안전하다.
- 꼬리표는 결정적 규칙에서만 나온다. 코파일럿 답은 여기에 쓰지 않는다(H-I6). 사람 수정은 학습 규칙(R2·R10)을 거쳐서만 들어온다.

### 4.6 단위업무별 증거 모음 — `unit_inputs`

```python
@dataclass(frozen=True)
class UnitIn:
    unit_id: str; kind: str                         # UnitTask.kind
    ev: tuple[tuple[Feat, float, str], ...]         # (특징, 가중, 역할) 역할 ∈ boundary|msg|doc|meet|app|manual
    app_min: dict[str, int]                          # 카탈로그 범주 → 이 업무에 귀속된 L3 분(사무·소통 포함)
    meet_min: int                                    # L2 회의 귀속 분
    offpc_min: int                                   # PC 밖 슬롯(다리·흔적 창·원격 발신 창) 귀속 분
    effort_min: int                                  # 총 투입 분(시간 코어 정수 분 표)
    peers_ext: bool                                  # 상대에 고객사·협력사 계급이 있음
    organizer_meetings: int                          # 내가 주최한 연결 회의 수
    sent_requests: int                               # 이 업무 대화에서 내가 보낸 request 수
```

| 역할 | 무엇 | 가중 `hier.unit.w.*` |
|---|---|---|
| `boundary` | 시작 근거 메시지(S1·S1o·ACK 의 그 메시지), 종료 근거 메시지(E1·E1i), 중간 보고(E1p) | 2.0 |
| `msg` | 같은 대화의 추가 지시·진행 발신, 그리고 시간 코어가 토큰으로 이 업무에 연결한 무연결 발신(`WORKTIME_METHOD.md` §4.6) | 1.0 |
| `doc` | 연결 문서군(강도 3 → 1.5, 강도 2 → 1.0, 자체 업무의 자기 문서군 1.5). 문서군 하나는 합집합 특징 하나 | 1.5 × 강도/3 |
| `meet` | 연결 회의(L2 대상) | 1.0 |
| `app` | APP 업무의 앱 사용, 그 밖 업무의 L3 앱 조각(앱마다 1건) | 1.0 |
| `manual` | 수동 기록·확인 응답의 ref | (라벨 직행, §4.7) |

`app_min` 은 시간 코어 귀속 결과(`attrib.jsonl` 의 L3 조각을 `app_id` → 카탈로그 범주로)에서 정수 분으로 만든다. 분은 분류 단서이며 코파일럿에는 보내지 않는다(B1).

### 4.7 단위업무 과제·영역 판정 — `unit_rule_label`

```python
def unit_rule_label(u: UnitIn, reg) -> RuleLabel:
    S, D, W, decisive = {}, {}, 0.0, None
    for f, w, role in u.ev:
        if f.manual and f.manual.get('project_id'):                     # 사람이 적은 라벨 — 최우선
            p = reg.resolve(f.manual['project_id'])
            return RuleLabel(project=p, score=1.0, source='user', conf='h', cands=[], domain=reg.domain_of(p))
        W += w
        sc = score_projects(f, reg)
        for pid, v in sc.items():
            s = -1.0 if v == -inf else min(v, EV_MIN) / EV_MIN         # 증거 하나가 꼬리표 문턱을 넘으면 1
            S[pid] = S.get(pid, 0.0) + w * s
        if role == 'boundary' and len(f.ent['과제']) == 1:
            p = reg.resolve(only(f.ent['과제']))                         # 의뢰·보고 메시지에 과제 토큰이 하나
            if sc.get(p) != -inf: decisive = p                           # 같은 증거의 never 가 걸리면 결정 토큰이 아니다
        for dom, v in score_domains(f, reg).items():
            D[dom] = D.get(dom, 0.0) + w * min(v, EV_MIN) / EV_MIN
    mass = max(W, MIN_MASS)                                              # hier.unit.minMass 3.0 — 증거가 적으면 점수도 작게
    cands = top3(((p, round(v / mass, 2)) for p, v in S.items() if v > 0), key=(-score, id))
    if decisive: return RuleLabel(decisive, 1.0, 'token', 'h', cands, reg.domain_of(decisive))
    if cands:
        top, sec = cands[0][1], (cands[1][1] if len(cands) > 1 else 0.0)
        if top >= CONFIRM and top - sec >= MARGIN:                       # 0.6 / 0.25
            return RuleLabel(cands[0][0], top, 'rule', 'h' if top >= 0.8 else 'm', cands, reg.domain_of(cands[0][0]))
        if top >= FALLBACK and top - sec >= PROB_MARGIN:                 # 0.5 / 0.1
            return RuleLabel(cands[0][0], top, 'rule_probable', 'l', cands, reg.domain_of(cands[0][0]))
    dl = sorted(((v / mass, d) for d, v in D.items()), key=(-score, DOMAIN_ORDER))
    if dl:
        top, dom = dl[0]; sec = dl[1][0] if len(dl) > 1 else 0.0
        rid = RESERVED_BY_DOMAIN[dom]                                    # P-9901 … P-9905
        if top >= D_CONFIRM and top - sec >= D_MARGIN:                   # 0.5 / 0.2
            return RuleLabel(rid, round(top, 2), 'domain_rule', 'm', cands, dom)
        cands = cands + [(rid, round(top, 2))]                           # 영역 후보도 코파일럿에 보여 준다
    return RuleLabel(None, cands[0][1] if cands else 0.0, 'none', 'l', cands[:3], 'UNC')
```

참조 구현 결과(골든):

| 시나리오 | 증거 | 결과 |
|---|---|---|
| H10 | 의뢰 메일에 `[과제:P-0007]` + 문서 + 보고 메일 | `P-0007`, token, h |
| H11 | 자체 업무: '광학모듈 브라켓 설계'(키워드 2) 문서, '브라켓 공차'(키워드 1) 문서, 같은 창 | `P-0007` 0.81, rule, h |
| H44 | 키워드 2개 문서 2개 + 키워드 1개 창 | `P-0007` 0.88, rule, h |
| H12 | `[고객사:C01]` 만(두 과제가 공유) | 미확정 — 후보 `P-0007 0.09`·`P-0008 0.09` → 코파일럿 |
| H13 | '8월 예산 정산 자료 요청' + '예산정산_8월.xlsx' | `P-9904`(공통 업무 일반), domain_rule, m |
| H14 | '메모.txt' 하나 | 미확정, 후보 없음 → 코파일럿 |
| H15 | '브라켓 수율개선 요청' + '양산라인 브라켓.xlsx' — 두 과제 키워드가 섞임 | 미확정(0.50 동률) → 코파일럿, 후보 `P-0007 0.5`·`P-0008 0.5`·`P-9902 0.36` |

### 4.8 분야·기능 판정 — `field_func`

```python
def vocab_hits(toks, table) -> dict[code, int]:      # 토큰마다 가장 긴 어휘 키워드 하나만 센다(입고검사 ⊃ 입고)
    …

def field_func(u: UnitIn, reg, rl: RuleLabel) -> FieldFunc:
    toks = ∪ f.toks;  exts = ∪ f.exts;  cats = {f.app_cat for f in ev if f.app_cat};  apps = {f.app …}
    tot = Σ u.app_min.values() or 1
    fs = {}                                                        # 분야 점수
    for code, n in vocab_hits(toks, fields).items(): fs[code] += min(1.0 × n, 3.0)
    for item in fields: fs[item.code] += 1.5 × |exts ∩ item.exts|;  fs[item.code] += 2.0 if apps ∩ item.apps
    for cat in cats: if CAT_FIELD.get(cat): fs[CAT_FIELD[cat]] += 2.0        # CAD→MECH, EDA·FPGA→ELEC, SW→SW, 광학→OPT
    if project(rl).default_field: fs[it] += 1.5;   if person.default_field: fs[it] += 1.0
    cs = {}                                                        # 기능 점수
    if u.kind == 'COORD': cs['MEET'] += 1.5; cs['PM'] += 1.0
    if u.kind == 'REPORT_ONLY': cs['DOC'] += 2.0
    for cat, m in u.app_min.items(): if CAT_FUNC.get(cat): cs[CAT_FUNC[cat]] += 3.0 × m / tot
        # CAD·EDA·FPGA·광학 → DESIGN, 해석 → ANALYSIS, SW → IMPL, 계측 → TEST
    office = app_min['사무'];  tech = Σ app_min[c] for c in TECH_CATS   # TECH = CAD·해석·광학·EDA·FPGA·SW·계측
    if u.effort_min and office / u.effort_min >= 0.6 and tech == 0: cs['DOC'] += 1.5
    if u.effort_min and u.meet_min / u.effort_min >= 0.5: cs['MEET'] += 2.0
    for code, n in vocab_hits(toks, functions).items(): cs[code] += min(1.0 × n, 3.0)
    if any f.ent['협력사']: cs['OUTSRC'] += 1.0
    if project(rl).default_func: cs[it] += 1.0
    + 팀 규칙·학습 규칙의 then.field / then.func 가점(규칙 w)
    return pick(fs, fallback=person.default_field or 'ETC'), pick(cs, fallback='ETC')

def pick(d, fallback):           # 동률은 코드 사전순
    top, sec = best_two(d)
    if top >= 2.0 and top - sec >= 1.0: return top.code, ('h' if top >= 3.5 else 'm')     # hier.vocab.top/margin/high
    if top >= 1.0: return top.code, 'l'                                                   # hier.vocab.low
    return fallback, 'l'
```

참조 구현 결과: H16 CAD 300분 + '하우징_v2.sldprt' → `MECH`(h)·`DESIGN`(m) / H17 해석 200분 + '방열 열해석 요청' → `THERM`(m)·`ANALYSIS`(m) / H18 조율형 + 회의 60분 → 기능 `MEET` / H45 '입고검사 결과 정리' + 사무 60분 → 분야 `QA`, 기능 `DOC`(입고 ⊂ 입고검사 이므로 `PURCHASE` 가 아니다).

---

## 5. 단위업무 명명 군집과 이름

### 5.1 목적과 경계

- 시간 코어는 '같은 일'을 여러 인스턴스로 만든다: 매주 손대는 주간보고(ISO 주마다 1개 — `WORKTIME_METHOD.md` §4.4 W20), 휴면으로 갈린 자체 업무(`splitWd`), 같은 의뢰자가 같은 첨부로 다시 맡긴 일(재의뢰 창 밖). 이것들은 **인스턴스로는 따로**(리드타임·투입·간트 막대가 따로)이되 **이름과 과제는 같아야** 한다.
- **명명 군집**(name group)은 이름·라벨을 함께 붙이기 위한 묶음이다. 군집은 인스턴스를 합치지 않는다(H-I5). 코파일럿에는 군집 하나를 항목 하나로 보낸다 — 같은 일을 같은 이름으로 부르게 되고 질의 수도 준다.

### 5.2 군집 규칙 — `name_groups(tasks, rule_labels)`

합집합-찾기(union-find)로 묶는다. 순회 순서는 `unit_id` 사전순(결정적).

| 번호 | 묶는 조건 | 근거 |
|---|---|---|
| G1 | `B.follow_of == A.id`(같은 문서군의 앞 인스턴스 — 반복 문서·범위를 넘은 같은 키) | `WORKTIME_METHOD.md` §4.4 `follow_of` |
| G2 | 둘 다 `SELF` 이고 **범용이 아닌** 문서군 키를 공유 | 휴면 분리된 같은 자체 업무 |
| G3 | 범용이 아닌 강한 문서군(강도 3 — 첨부·must_link)을 공유하고 주 상대(`peer`)가 같음 | 같은 의뢰자의 같은 문서 재요청 |

제약(하나라도 어기면 그 합치기를 건너뛴다 — LM24 cluster2 처럼 '무리 안에서' 강제):

- 군집 안의 **확정 과제**(출처 `user`·`token`·`rule` — §4.7)가 둘 이상이 되면 안 된다(H24: 같은 문서군이라도 `P-0007` 확정과 `P-0008` 확정은 따로).
- 군집 크기 ≤ `hier.name.maxGroup`(60 — 주간보고 1년치가 들어가는 크기).
- 범용 문서군(`WORKTIME_METHOD.md` §4.1 `is_generic`: 보고서·자료·문서·회의록·untitled …)으로는 묶지 않는다(H24: 같은 '보고서.pptx' 를 첨부한 두 의뢰는 따로).
- `APP` 업무는 앱이 같다는 것만으로 묶지 않는다(같은 해석 프로그램으로 여러 과제를 한다).

**대표와 키**: 군집 대표 = 첫 차수 시작이 가장 이른 구성원(동률 `unit_id` 사전순). `anchor_key` = 대표의 `UnitTask.first_key`(시작 근거 키 — msg_key·`fam_key|날짜` 등). 군집 키 `grp:` + sha1(`anchor_key`)[:12]. 군집이 뒤로 자라도(다음 주 주간보고) 대표가 바뀌지 않으므로 키가 안정하다.

참조 구현 H24: 주간보고 8주 인스턴스 → 군집 1개, 같은 문서군 자체 업무 2개 → 1개, 범용 '보고서' 첨부 의뢰 2개 → 따로, 확정 과제가 다른 같은 문서군 → 따로.

### 5.3 규칙 이름 — `rule_title(group)`

이름 후보를 아래 순서로 찾는다. 처음 성공한 것을 쓰고, 그 출처(`title_src`)를 남긴다.

| 순서 | 출처 `title_src` | 재료 | 품질 |
|---|---|---|---|
| 1 | `doc` | 군집의 **범용이 아닌** 문서군 중 귀속 분 합이 가장 큰 것의 최근 `name_masked`(또는 첨부명) → `display_stem` | 명확 |
| 2 | `subject` | 대표의 시작 근거 메시지 제목(`subject_masked`·팀즈는 본문 요지) → `subject_title` | 명확 |
| 3 | `app` | 앱 범주 이름 + ' 작업'(예 '해석 프로그램 작업') | 약함 |
| 4 | `generic` | '<분야 이름>·<기능 이름> 단위업무'(예 '광학·해석·분석 단위업무') | 약함 |

```python
TAIL = r"([_\-\s]?(v\d+(\.\d+)?|rev\d+|r\d+|최종|final|수정본?|사본|copy|\(\d+\)|\d{6,8}))$"   # 대소문자 무시

def display_stem(name):
    x = NFKC(name); x = sub(r"\.[0-9A-Za-z]{1,5}$", "", x)                     # 확장자
    x = sub(r"\[과제:[^\]]+\]|\[사람[^\]]*\]|\[나\]", " ", x)                    # 과제 토큰은 계층에 이미 있다. 사람 토큰 제거
    repeat ≤ 5: x = sub(TAIL, "", x).strip(" _-")                               # 판·날짜·사본 꼬리
    x = sub(r"[_\-]+", " ", x); return " ".join(x.split())

def subject_title(subj):
    x = sub(RE_PREFIX, "", NFKC(subj))
    x = sub(r"\[과제:[^\]]+\]|\[사람[^\]]*\]|\[나\]|\[이메일@[^\]]*\]|\[전화\]|\[금액\]", " ", x)
    words = [w for w in x.split() if w.lower().strip(".,") not in BOILERPLATE
             and not any(w.startswith(b) and len(w) - len(b) <= 2 for b in ("부탁", "요청", "검토", "송부", "공유", "회신", "보고"))]
    return " ".join(words).strip(" .,")

def clip_title(t, n=hier.name.titleMax(25)):
    if len(t) <= n: return t
    cut = t[:n]; sp = cut.rfind(" ")
    return (cut[:sp] if sp >= 8 else cut).strip()
```

- `[고객사:C01]`·`[협력사:V01]` 토큰은 이름에 남겨도 된다(팀 라벨 허용 토큰 — `PRIVACY.md` §14.4). 개인 화면은 로컬 레지스트리로 고객사 표시명을 풀어 보인다.
- 길이 2자 미만·범용 줄기(`is_generic`)·숫자만 남은 결과는 실패로 보고 다음 순서로 간다.
- 예(참조 구현): `[과제:P-0012]_공차해석_v3.xlsx` → '공차해석'(H25) / `RE: [과제:P-0012] 브라켓 체결부 검토 부탁드립니다` → '브라켓 체결부'(H26) / `주간보고_20261007.xlsx` → '주간보고'(H27) / 재료 없음 + 분야 OPT·기능 ANALYSIS → '광학·해석·분석 단위업무'(H28).

### 5.4 이름 고정 — 제목 캐시 `data\local_only\hier\title_cache.json`

실행마다 이름이 흔들리면 간트·추이가 끊긴다(LM24: 청크마다 세부업무 이름이 흔들려 로드가 분할). 한 번 정한 이름은 캐시로 고정한다.

```json
{"schema": "lm27.title_cache/1",
 "groups": {"5d1c0a9e7b21": {"title": "광학 모듈 공차 해석", "src": "ai", "conf": "h", "at": "2026-10-05T10:21:44+09:00",
                             "prompt_ver": "task_label/1.1", "anchor": "m3b9…"}}}
```

- 키 = 군집 키의 12hex(`anchor_key` 해시). 값의 `anchor` 는 대표 시작 근거 키(로컬 키 — local_only 이므로 허용).
- 이름 우선순위(높은 것이 이긴다): 사용자 입력 > 캐시(사용자) > 캐시(AI h·m) > 이번 AI 답(h·m) > 규칙 이름(`doc`·`subject`) > AI 답(l) > 규칙 이름(`app`·`generic`).
- 캐시는 군집이 사라지면(대표 인스턴스가 재수집으로 바뀜) `hier.name.cacheKeepDays`(400일) 뒤 지운다.

### 5.5 인스턴스 표시

- 군집 구성원은 같은 이름을 갖는다. 개인 화면과 간트 툴팁은 구별을 위해 시작 날짜를 덧붙여 보인다(예 '주간보고 · 10/7 주') — **표시 전용**이고 저장하지 않는다.
- 팀 묶음 `units[].title` 에는 군집 이름을 그대로 싣는다(`team.unit_title_mode=label`). `generic` 모드·[제목 가림]이면 `<분야 이름>·<기능 이름> 단위업무 #n`(팀 명세 §2.5).

---

## 6. 코파일럿 분류 단계 — `task_label/1.1`

브리지(`COPILOT_BRIDGE.md`)의 L0~L3(세션·전송·rid 봉투·패킹·반분·저널·재개·게이트)은 그대로 쓰고, 이 절은 L4 단계의 **내용**(무엇을 보내고, 무엇을 받고, 어떻게 적용하는가)을 정한다. 브리지 §8.3 의 `task_label/1.0` 에서 바뀐 점은 §6.8 에 모았다.

### 6.1 무엇을 보내는가 — 선택 규칙

군집 g 를 `ai_in\task_label.jsonl` 에 쓰는 조건(모두 참):

1. 구성원 중 **사용자 라벨**이 없다.
2. (a) 과제 미확정 — 대표 라벨의 출처가 `none` 또는 `rule_probable`, **또는** (b) 이름이 약함 — `title_src ∈ {app, generic}` 이고 제목 캐시에 사용자·AI(h·m) 이름이 없음 (`hier.copilot.askTitleWeak`, 기본 true), **또는** (c) 분야·기능 확신이 **둘 다** `l` 이고 군집 투입 ≥ `hier.copilot.vocabAskMinEffortH`(1h). 예약 과제(`domain_rule`)로 끝난 군집은 (a)에 넣는다(같은 영역의 등록 과제로 구체화될 수 있으므로 — §6.5) — 단 레지스트리에 그 영역의 active 과제가 하나도 없으면 넣지 않는다.
3. 브리지 저장소에 같은 내용 키의 답이 없다(재개·재사용 — 브리지 §7.9). 내용 키가 같아도 다시 묻는 경우는 §6.6.

- 순서: 군집 투입 분 합의 내림차순(큰 일부터). 한 실행 상한 `hier.copilot.maxGroupsPerRun`(300) — 넘는 군집은 다음 실행으로 넘어간다(`rule_pending` 으로 접힘, 브리지 §2.5).
- `group`(패킹 묶음 키) = 후보 1위 과제 ID 또는 `""`. `group_strict=False`(같은 과제끼리 모으되 강제하지 않음).
- 규칙으로 과제가 확정되고 이름이 명확한 군집은 보내지 않는다. 참조 구현 기준으로 레지스트리가 잘 채워진 팀에서는 군집의 대부분이 여기서 끝나야 한다(관측 지표 `hier.stats.ai_share` 를 결과 메타에 남긴다).

### 6.2 `ai_in` 항목 형식

```json
{"key": "grp:5d1c0a9e7b21", "group": "P-0007",
 "fields": {"kinds": "메일수신 2·메일발신 3·팀즈 3·문서 2",
            "subjects": ["[과제:P-0007] 공차 해석 결과 공유", "RE: 공차 해석 조건 확인"],
            "files": ["공차해석_v3.xlsx", "브라켓_조립도.pdf"],
            "apps": ["해석 프로그램", "엑셀"],
            "domains": ["[고객사:C01]", "사내"],
            "cands": [["P-0007", 0.62], ["P-0008", 0.21]],
            "hint": "OPT/ANALYSIS/DEV",
            "regv": ""},
 "rule": {"project": "P-0007", "score": 0.62, "source": "rule", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV",
          "title": "공차해석", "title_src": "doc"},
 "src_ver": "hier/1",
 "meta": {"priv_class": "work", "ad_band": "keep", "rules_ver": "2026.10.0"}}
```

| 필드 | 형·상한 | 만드는 법 |
|---|---|---|
| `kinds` | str ≤ 60 | 군집 전체 증거의 종류별 건수: 메일수신·메일발신·팀즈수신·팀즈발신·회의·문서·앱·수동, 0 인 것은 뺀다. 건수는 분류 단서이며 시간이 아니다 |
| `subjects` | list ≤ 3, 각 ≤ 60 | 대표의 시작 근거 메시지 제목, 마지막 종료 근거 메시지 제목, 그 밖 가장 잦은 대화 제목(서로 `ukey` 다른 것만). 회의는 회의 제목 |
| `files` | list ≤ 5, 각 ≤ 40 | 귀속 분이 큰 문서군 순서로 그 이름(`name_masked`·첨부명, 확장자 유지), 범용 이름은 뒤로 |
| `apps` | list ≤ 3 | 앱 **범주** 이름(아래 표). 미상 프로그램은 '미상 프로그램'(exe 이름을 보내지 않는다 — 사내 도구 이름 = 코드네임일 수 있다, `TEAM_AND_BUNDLE.md` R-9 와 같은 이유) |
| `domains` | list ≤ 3 | 상대 계급: `사내`, `[고객사:C01]`, `[협력사:V01]`, `기관`, `외부`. **도메인 원문은 보내지 않는다**(고객사 사전에 없는 외부 도메인은 `외부`) |
| `cands` | list ≤ 3 `[ID, 점수]` | §4.7 후보(영역 후보 `P-99xx` 포함). 규칙이 예약 과제(`domain_rule`)로 끝났으면 그 예약 과제와 영역 점수를 맨 앞에 둔다. 점수 소수 2자리 |
| `hint` | `"<분야>/<기능>/<유형>"` 코드 | §4.8·§10 의 규칙 판정. 확신이 낮아도 싣는다(코파일럿이 확인·수정) |
| `regv` | `""` 또는 8hex | §6.6 재질의 표식. 평소 `""` 라 내용 키가 바뀌지 않는다 |

앱 범주 이름 표(카탈로그 `cat` → 프롬프트 이름): CAD → 'CAD 프로그램', 해석 → '해석 프로그램', 광학 → '광학 설계 프로그램', EDA → '회로 설계 프로그램', FPGA → 'FPGA 도구', SW → '개발 도구', 계측 → '계측 프로그램', 사무 → 앱별('엑셀'·'워드'·'파워포인트'·'PDF'·'메모'), 소통 → '메일'·'메신저', 미상 → '미상 프로그램'.

`content_key_fields = ("kinds", "subjects", "files", "apps", "domains", "regv")` — `cands`·`hint` 는 규칙이 바뀌어도 다시 묻지 않도록 내용 키에서 뺀다(브리지 §2.5 `src_ver` 와 같은 취지).

### 6.3 프롬프트 전문(입력 상한 8,000자 전제)

브리지 §6.2 골격(첫 줄·머리말·참고 목록·앞서 쓴 이름·겹침·항목·답 형식·서약)을 그대로 쓴다. 아래는 이 단계가 채우는 부분까지 조립한 **실물**이다(참조 구현 `spec_prompt_task_label.txt`, 2,576자 — 레지스트리 과제 4개 + 예약 5개, 항목 3개).

```text
[LM27 요청 R7F3QK · 단위업무 이름·과제/역할 고르기 · 항목 3개]
당신은 한 엔지니어의 업무 흔적 묶음(단위업무)을 팀 과제 목록과 어휘에 맞춰 분류합니다.
항목마다 다음을 고르세요.
- project : [과제 목록]의 코드 하나. P-99 로 시작하는 코드는 과제는 모르지만 업무 영역은 알 때 씁니다. 업무가 아니거나 판단할 수 없으면 NONE, 목록에 없는 새 과제가 분명하면 NEW.
- field : [분야] 코드 하나 / func : [기능] 코드 하나 / wtype : [업무유형] 코드 하나
- title : 이 단위업무를 부르는 짧은 이름(명사구, 25자 이내). 과제 코드·사람 이름·금액·날짜는 넣지 않습니다.
- new : project 가 NEW 일 때만 새 과제의 짧은 이름(20자 이내), 아니면 "".
- dom : project 가 NEW 일 때만 새 과제의 업무영역 코드, 아니면 "".
- conf : 확신 h(높음)·m(보통)·l(낮음)
규칙:
- [과제:P-0012] 처럼 꺾쇠 안의 코드는 그 과제를 가리킵니다. 후보·규칙안은 프로그램이 계산한 참고값이며 틀릴 수 있습니다.
- 목록에 있는 코드만 씁니다. 코드를 바꾸거나 지어내지 않습니다.
- 'OO 설계'·'OO 보고서 작성' 같은 활동 이름은 새 과제가 아닙니다. 여러 업무를 묶는 제품·프로젝트·과제일 때만 NEW 입니다.
- [앞서 쓴 이름]에 같은 일이 있으면 그 이름을 그대로 다시 씁니다(같은 일은 같은 이름).
[업무영역] DEV 개발 프로젝트 · MP 양산 프로젝트 · EXT 외부 업무지원 · COM 공통 업무 · AX AX 프로젝트
[과제 목록] 코드 · 업무영역 · 설명
P-0007 · DEV · 광학 모듈 신규 개발
P-0008 · MP · 센서 모듈 양산 대응
P-0011 · AX · 메일 자동 분류 도구
P-0012 · EXT · 대학 공동연구 지원
P-9901 · DEV · (개발 프로젝트 — 과제 미지정)
P-9902 · MP · (양산 프로젝트 — 과제 미지정)
P-9903 · EXT · (외부 업무지원 — 과제 미지정)
P-9904 · COM · (공통 업무 — 과제 미지정)
P-9905 · AX · (AX 프로젝트 — 과제 미지정)
[분야] MECH 기구 · ELEC 회로 · SW 소프트웨어 · OPT 광학 · THERM 열 · REL 신뢰성 · PROC 공정 · QA 품질 · SYS 시스템 · ETC 기타
[기능] DESIGN 설계 · IMPL 구현 · ANALYSIS 해석·분석 · TEST 시험·검증 · OUTSRC 외주 관리 · PURCHASE 구매·발주 · DOC 문서·보고 · MEET 회의·조율 · PM 과제 관리 · TRANSFER 양산 이관 · SUPPORT 기술 지원·대응 · STUDY 조사·학습 · ADMIN 행정·사무 · ETC 기타
[업무유형] DEV 개발 · OFFICE 사무 · FIELD 현장 · PM PM · PL PL · SUPPORT 지원 · EDU 교육·학습
[앞서 쓴 이름] 광학 모듈 공차 해석 / 시험 지그 설계
[항목] 번호 | 흔적 | 제목 요지 | 파일 | 앱 | 상대 | 후보 | 규칙안
1 | 메일수신 2·메일발신 3·팀즈 3·문서 2 | [과제:P-0007] 공차 해석 결과 공유 / RE: 공차 해석 조건 확인 | 공차해석_v3.xlsx, 브라켓_조립도.pdf | 해석 프로그램, 엑셀 | [고객사:C01], 사내 | P-0007 0.62, P-0008 0.21 | OPT/ANALYSIS/DEV
2 | 문서 4·앱 1 | - | 열해석_모델.cas, 열해석_결과정리.xlsx | 해석 프로그램 | - | - | THERM/ANALYSIS/DEV
3 | 메일수신 1·메일발신 1·문서 1 | 8월 [금액] 정산 품의 요청 | 정산내역.xlsx | 엑셀 | 사내 | P-9904 0.55 | ETC/ADMIN/OFFICE
[답 형식]
- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다. 코드 블록 밖에는 설명을 쓰지 않습니다.
- rid 에는 "R7F3QK" 를, n 에는 items 의 개수를 씁니다. 항목 번호 1~3 을 빠짐없이 한 번씩, 번호 순서대로 씁니다.
- 문자열 값은 큰따옴표로 감싸고 값 안에서 줄을 바꾸지 않습니다.
- 근거가 부족하면 지어내지 말고 project 는 NONE, conf 는 l 로 쓰고 title 은 흔적에서 보이는 그대로 짧게 씁니다.
- 사람 이름·전화번호·메일 주소·금액은 쓰지 않습니다. [전화]·[금액]·[사람] 같은 꺾쇠 표기는 가려진 값입니다.
- 웹 검색을 하지 말고 이 메시지에 적힌 내용만으로 답합니다.
- 형식(<…> 자리에 실제 값): {"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "project": <코드|NONE|NEW>, "field": <분야 코드>, "func": <기능 코드>, "wtype": <업무유형 코드>, "title": <짧은 이름>, "new": <새 과제 이름 또는 "">, "dom": <영역 코드 또는 "">, "conf": <h|m|l>} ]}
- 코드 블록이 끝나면 맨 마지막 줄에 [[END R7F3QK]] 만 씁니다.
```

조립 규칙(`stages/task_label.py`):

| 부분 | 규칙 |
|---|---|
| 첫 줄 | 브리지 골격 그대로(`title_ko` = '단위업무 이름·과제/역할 고르기') |
| 머리말 | 위 13줄 고정 문구. 문구만 바꾸면 `prompt_ver` 부판(`task_label/1.2`), 커밋 재사용 |
| `[업무영역]` | `DOMAIN_META` 에서 생성(UNC 제외) |
| `[과제 목록]` | `active_ids()`(팀 active 과제 + 내가 받아들인 개인 과제 `L-…` — active, `maps_to` 없음) ID 정렬 → `코드 · 영역코드 · copilot_desc`(비었으면 `(설명 없음)`), 이어서 예약 5줄. **과제 이름·별칭·코드네임은 싣지 않는다**(B14). 아직 사람이 받아들이지 않은 제안(§7, `pending`)은 싣지 않는다(AI 이름이 AI 힌트로 되먹이는 순환 방지 — LM24 discovered 교훈) |
| `[분야]`·`[기능]`·`[업무유형]` | 유효 어휘의 active 항목 `코드 이름` 을 ` · ` 로. 개인 `L_` 코드는 싣지 않는다(팀 묶음에 못 가므로) |
| 축약(`compact=True`) | 브리지 §7.3: 남는 자리가 입력 예산의 25% 미만이면 `[과제 목록]` 을 '이 묶음 항목의 `cands` 코드 + 예약 5줄'로 줄이고 끝에 `(목록은 이번 항목의 후보만 보입니다. 맞는 것이 없으면 NONE 또는 P-99 코드)` 한 줄 |
| `[앞서 쓴 이름]` | 브리지 §7.4(`names_field="title"`, 30개·600자) |
| 겹침 | 브리지 §7.4(`[참고 — 이미 처리한 항목, 답하지 마세요]`, `항목 줄 → 답한 이름`) |
| `[항목]` 열 | `번호 \| 흔적 \| 제목 요지 \| 파일 \| 앱 \| 상대 \| 후보 \| 규칙안` |
| 항목 줄 | `"{n} \| {kinds} \| {' / '.join(subjects) or '-'} \| {', '.join(files) or '-'} \| {', '.join(apps) or '-'} \| {', '.join(domains) or '-'} \| {', '.join(f'{p} {s:.2f}' for p, s in cands) or '-'} \| {hint}"` |
| 웹 노출(`web_exposed`) | 브리지 §9.7: `domains` 를 보내지 않는다(`web_drop_fields=("domains",)`) — 열은 그대로 두고 값만 `-` |

### 6.4 예산과 묶음 크기(참조 구현 실측, 항목 줄 평균 180자)

| 레지스트리 과제 수(예약 제외) | 고정부(머리말+목록+앞서 쓴 이름 20개+겹침 1줄) | 축약 | 묶음당 항목 | 첫 묶음 프롬프트 |
|---|---|---|---|---|
| 0 | 2,429자 | 아니오 | 30(상한) | 7,770자 |
| 10 | 2,776자 | 아니오 | 28 | 7,753자 |
| 40 | 3,844자 | 아니오 | 22 | 7,729자 |
| 80 | 5,268자 | 아니오 | 15 | 7,879자 |
| 150 | 7,760자 | **예** | 29 | 7,708자 |

- 입력 예산 `bridge.inputMaxChars`(8,000, 보정값 우선)·답 예산 5,000자. 답 추정 항목당 120자 → 30항목 3,680자로 답 예산 안이다. 레지스트리가 커도 축약 머리말이 묶음 크기를 지킨다.
- 한 달 군집 300개면 묶음 11~20개(질의 11~20회). 대부분은 규칙으로 끝나므로(§6.1) 실제로는 그보다 적다.
- `StageSpec` 값(브리지 §8.0.1): `id="task_label"`, `prompt_ver="task_label/1.1"`, `schema_major=1`, `kind="items"`, `model_class="fast"`, `chat_policy="continue"`, `max_items=30`, `min_split=5`, `est_out_per_item=120`, `est_out_fixed=80`, `group_strict=False`, `send_fields=("kinds","subjects","files","apps","domains","cands","hint","regv")`, `text_fields=("subjects","files","apps","domains")`, `web_drop_fields=("domains",)`, `uses_registry=True`, `names_field="title"`.

### 6.5 응답 스키마·검증·적용

**스키마**(브리지 §6.5 필드 명세 언어):

```python
(F("project", "code", codes="projects", extra_codes=("NONE", "NEW")),     # projects = active_ids ∪ 예약 5개
 F("field", "code", codes="vocab.field"), F("func", "code", codes="vocab.func"), F("wtype", "code", codes="vocab.wtype"),
 F("title", "str", min_len=2, max_len=30, hard_max=80),
 F("new", "str", required=False, max_len=20),
 F("dom", "enum", required=False, enum=("DEV", "MP", "EXT", "COM", "AX", "")),
 F("conf", "enum", enum=("h", "m", "l")))
```

`validate`(단계 추가 검사): `project=="NEW"` 이면 `new` 2자 이상(`missing:new`)·`dom` 이 5종 중 하나(`missing:dom`). `title`·`new` 에 `\d[\d,]*\s?(원|만원|억|달러|USD|KRW)` 이 있으면 `bad_pattern:title`. 시간형 키(`hours`·`date`…)가 있으면 항목 무효(`forbidden_field`, 브리지 §6.5-2). 참조 구현 H30: 목록 밖 코드 → `unknown_code:project`, NEW + 이름 없음 → `missing:new`, 제목에 금액 → `bad_pattern:title`, `hours` 키 → `forbidden_field`.

`normalize`: NFKC, 따옴표·꺾쇠 기호 정리, `title` 앞뒤 공백·마침표 제거, `title` 에 `[과제:…]` 가 있으면 제거, 입수 게이트(브리지 §9.3 ③ — 답에 섞인 개인정보를 정제기로 한 번 더).

**폴백**(브리지 `fallback` — AI 답이 없을 때): `project` = `rule.project`(규칙이 확정·유력·영역이면) 아니면 `NONE`; `field`·`func`·`wtype` = 규칙 값; `title` = 규칙 이름; `conf="l"`; `by="rule"`.

**적용 — `apply_labels`**: 군집 답을 구성원 모두에 적용하되, 필드마다 아래 우선순위를 따른다(숫자가 큰 쪽이 이긴다).

| 출처 | 순위 | 비고 |
|---|---|---|
| `user`(사용자 수정·수동 기록) | 100 | 언제나 이긴다 |
| `token`(시작·종료 메시지의 과제 토큰) | 85 | |
| `rule`(확정, 학습 키 규칙 포함) | 80 | |
| `domain_rule`(예약 과제) | 75 | 단, 아래 '구체화' 예외 |
| `ai_h` | 70 | |
| `rule_probable` | 60 | |
| `ai_m` | 55 | |
| `ai_l` | 30 | |
| `none`·폴백 | 0~10 | |

- **과제**: 높은 순위가 이긴다. 예외 '구체화' — 규칙이 `domain_rule`(예: `P-9904`)이고 AI 가 **같은 영역의 등록 과제**를 `h`·`m` 으로 고르면 AI 가 이긴다(공통 업무 일반 → '예산 관리' 과제). 군집 구성원 중 자기 확정 과제(`user`·`token`·`rule`)가 있는 인스턴스는 그 과제를 지킨다(군집 답은 과제만 빼고 이름·분야·기능·유형을 준다).
- **충돌 질문**: AI 가 `h` 로 고른 과제가 규칙 확정 과제와 다르면 규칙을 지키고 확인 질문 H02. AI `h` 가 규칙 유력(점수 ≥ 0.4) 1위와 다른 과제를 골라 이겼을 때도 H02(참조 구현 H31·H32). AI `m` 은 규칙 유력을 이기지 못한다(H33).
- **NONE**: 규칙에 예약 과제·유력 과제가 있으면 그대로, 없으면 `UNC`.
- **NEW**: 군집을 새 과제 제안에 붙인다(§7). 라벨의 과제 자리는 그 제안의 `proposal_id`, 영역은 `dom`.
- **분야·기능·유형**: 규칙 확신 `h` 면 규칙, `m` 이면 AI `h` 가 이김, `l` 이면 AI `h`·`m` 이 이김. AI `l` 은 규칙을 이기지 못한다.
- **이름**: §5.4 의 우선순위.
- 결과 라벨은 출처·확신을 필드마다 남긴다(§11.1).

### 6.6 재질의 정책 — `regv`

브리지 저장소는 내용 키가 같으면 다시 묻지 않는다. 그런데 레지스트리에 과제가 새로 생기면 예전에 `NONE`·`NEW`·`P-99xx` 로 답한 군집은 다시 물어야 한다. 이때만 `fields.regv` 를 채워 내용 키를 바꾼다.

```python
def regv_for(prev_ans, reg_now, reg_at_answer_hash) -> str:
    if prev_ans is None: return ""
    if set_hash(reg_now.active_ids()) == reg_at_answer_hash: return ""          # 과제 목록이 그대로면 다시 묻지 않음
    p = prev_ans['project']
    if p in ('NONE', 'NEW') or is_reserved(p) or reg_now.status(p) != 'active':
        return set_hash(reg_now.active_ids())                                     # sha1('|'.join(정렬 ID))[:8]
    return ""
```

- 답을 커밋할 때 그 순간의 과제 목록 해시를 `ai_out` 항목 메타(`reg_set`)에 남긴다(브리지 저장소에 함께 저장 — §16 X5).
- 참조 구현 H42: 과제가 하나 늘었을 때 `NONE` 답 → 다시 묻기, `P-0007` 답 → 재사용, `P-9904` 답 → 다시 묻기, 과제 목록이 그대로면 → 재사용.
- 그 밖에 다시 묻는 경우: 이전 답이 `conf=l` 이고 군집 증거 건수가 그때의 2배 이상으로 늘었을 때(`regv` 에 `'g' + 건수 단계` — 같은 방식으로 내용 키만 바꾼다). 사용자가 [다시 분류] 버튼을 눌렀을 때(그 군집만, `regv='u' + 시각 해시`).

### 6.7 실패·부분 실패

- 단계 결과 봉투(브리지 §7.11)의 `rule_pending`·`failed` 항목은 규칙 라벨로 접히고 다음 실행이 자동으로 다시 묻는다(B12 — 사용자 조작 없음).
- 코파일럿이 `NONE` 을 너무 많이 돌려줘도(예: 레지스트리 설명이 부실) 그대로 받는다. 보고서는 '미분류 비중'과 '코파일럿 NONE 비율'을 함께 보이고, 팀장 화면은 'copilot_desc 가 빈 과제' 목록을 띄운다.

### 6.8 브리지 `task_label/1.0`(COPILOT_BRIDGE §8.3) 대비 바뀐 점

| 항목 | 1.0 | 1.1(이 문서) | 이유 |
|---|---|---|---|
| 과제 목록 | 등록 과제만, 공통·지원은 `NONE` | 예약 '영역 일반' 5개 추가, `NONE` = 업무 아님·판단 불가 | 영역은 알고 과제는 모르는 업무를 공통 업무 등으로 계상(§1.3) |
| 응답 `dom` | 없음 | `NEW` 일 때 새 과제 영역 | 제안의 `domain_guess` 필요(팀 묶음 `proposals[]`) |
| 항목 열 `규칙안` | 없음(`field_hint` 는 보내지 않음) | `hint` = 규칙 분야/기능/유형 | 규칙이 맞으면 확인만 하면 되므로 답 품질·일관성이 오른다 |
| `domains` 값 | 상대 도메인(`@partner.example`) | 계급(`사내`·`[고객사:C01]`·`기관`·`외부`) | 도메인 원문은 고객사를 가리킨다 — 웹 노출이 아니어도 보내지 않는다 |
| 내용 키 | kinds·subjects·files·apps·domains | + `regv` | 레지스트리 변경 때 선택적 재질의(§6.6) |
| 머리말 규칙 | — | '활동 이름은 새 과제가 아니다'(LM20 계층 규율) 한 줄 | NEW 남발 방지 |
| 항목 키 | `cand:…` | `grp:…`(명명 군집) | 군집 단위 질의(§5) |

---

## 7. 새 과제 제안 큐

### 7.1 원칙

- AI(코파일럿)가 말한 새 과제 이름은 **제안**일 뿐이다. 레지스트리에도, 규칙에도, 다음 프롬프트의 과제 목록에도 자동으로 들어가지 않는다(H-I6). 들어가는 길은 두 가지 사람 결정뿐이다: 내가 [내 과제로 받기](개인 로컬 과제) 또는 팀장이 레지스트리에 등록(팀 과제).
- 그래도 MM 이 미분류로 새지 않도록, 제안에 붙은 단위업무는 **제안 과제**로 계상한다: 라벨의 과제 자리 = `proposal_id`, 영역 = 제안의 `dom_guess`. 팀 서버도 같은 규칙으로 '제안 과제' 표시를 달아 계상한다(`TEAM_AND_BUNDLE.md` §4.4).
- 제안은 같은 사람 안에서 **이름 병합 거버넌스(§9)** 로 중복을 줄이고, 팀원 사이의 같은 제안은 팀 서버가 팀장에게 묶음 후보로만 보인다(§9.6).

### 7.2 출처

| 출처 `from` | 언제 | 처음 상태 |
|---|---|---|
| `task_label` | 코파일럿이 `project=NEW`·`new`·`dom` 으로 답함(§6.5) | `pending` |
| `bootstrap` | 부트스트랩 1회차의 `code=""` 행(§8.4) | `pending` |
| `user` | 수정 화면의 [새 과제 만들기] | `accepted_local`(바로 개인 과제) |
| `codename_review` | 초기 코드네임 검토에서 [과제 이름]으로 표시(§8.1) | `accepted_local` |

### 7.3 자료구조 `data\local_only\hier\proposals.json`

```json
{"schema": "lm27.proposals/1", "next_seq": 4,
 "items": [
  {"proposal_id": "pr_3", "kind": "project", "label": "방열 모듈", "ukey": "방열모듈", "dom_guess": "DEV",
   "status": "pending", "local_project": null, "mapped_to": null, "merged_into": null,
   "sources": [{"from": "task_label", "group": "grp:5d1c0a9e7b21", "conf": "m", "at": "2026-10-05T10:21:44+09:00"}],
   "groups": ["grp:5d1c0a9e7b21", "grp:0b44e1f2a9c3"], "n_units": 3, "effort_min": 720,
   "first_at": "2026-09-14", "last_at": "2026-10-02",
   "match_words": ["방열", "열해석"], "evidence_keys": ["d1a2…", "t09f…"],
   "history": [{"at": "2026-10-05T10:21:44+09:00", "event": "created", "by": "task_label"}]}]}
```

| 필드 | 뜻 |
|---|---|
| `proposal_id` | `pr_` + 순번(`^pr_\d{1,4}$`, 팀 묶음 `PROPOSAL_ID`). 이 사람 안에서 유일하고 다시 쓰지 않는다 |
| `kind` | `project`(v1). `role` 은 팀 스키마에 자리만 있다(미사용) |
| `label` | 정규화된 이름(≤ 20자, `check_team_label` 통과 — 실패하면 `'<영역 이름> 새 과제 #<순번>'`) |
| `dom_guess` | 5종 중 하나 |
| `status` | `pending` → `accepted_local`(개인 과제 생성) → `mapped`(팀 과제로 대응) / `rejected`(거절) / `merged`(다른 제안에 합쳐짐) |
| `local_project` | 받아들였을 때 만든 `L-…` |
| `mapped_to` | 팀 과제 `P-…`(§7.6) |
| `groups`·`n_units`·`effort_min`·`first_at`·`last_at` | 매 실행 다시 계산(근거 표시용, 로컬 전용) |
| `match_words` | 부트스트랩·사용자가 준 알아볼 낱말 — **제안 상태에서는 규칙으로 쓰지 않는다**. 받아들일 때 사용자가 고른 것만 개인 과제 `keywords` 로 |
| `evidence_keys` | 군집들의 문서군·대화 키 합집합(§9 공유 근거 점수 재료, 로컬 키 — local_only) |

### 7.4 생성·중복 제거 — `on_new_name(label, dom, group, src)`

```python
def on_new_name(label, dom, group, src, reg, queue):
    label = normalize_label(label)                         # NFKC·공백 접기·≤20·[과제:…]·[사람…] 제거·check_team_label
    k = ukey(label)
    if k in reg.alias_ix:                                  # 코파일럿이 등록 과제를 NEW 로 답함 → 그 과제로 바로
        return Assign(project=reg.resolve(reg.alias_ix[k]), src='ai_alias')
    if k in rejected_ukeys(): return Assign(project=RESERVED_BY_DOMAIN[dom], src='rejected_name')
    if group_effort_min(group) < cfg['hier.proposals.minEffortMin']:          # 60분 미만 군집은 제안을 만들지 않음
        return Assign(project=RESERVED_BY_DOMAIN[dom], src='too_small')
    live = [p for p in proposals if p.status in ('pending', 'accepted_local')]
    scored = sorted(((pair_score(label, p.label, ctx_for(group, p)), p) for p in live), key=lambda x: (-x[0][0], x[1].proposal_id))
    if scored and zone(scored[0][0][0]) == 'auto':
        p = scored[0][1]; p.sources.append(...); p.groups.add(group); return Assign(proposal=p.proposal_id)
    p = new_proposal(label, dom, group, src)
    if scored and zone(scored[0][0][0]) == 'ask':
        queue.add('H04', a=p.proposal_id, b=scored[0][1].proposal_id, score=scored[0][0][0])
    return Assign(proposal=p.proposal_id)
```

- `ctx_for` 는 두 쪽의 `evidence_keys`(공유 근거)·고객사 토큰·영역 추정을 §9.3 점수에 넘긴다.
- 거절된 이름(`rejected`)의 `ukey` 는 다시 제안하지 않는다(사용자 의사 존중). 사용자가 [거절 취소]로 되돌릴 수 있다.

### 7.5 개인 화면의 결정

| 버튼 | 결과 |
|---|---|
| [내 과제로 받기] | 개인 로컬 레지스트리에 `L-…` 생성(이름 = label, 영역 = `dom_guess`(바꿀 수 있음), `copilot_desc` = label, `keywords` = 사용자가 체크한 `match_words`), 제안 상태 `accepted_local`. 이 과제는 다음 실행부터 프롬프트 과제 목록에 실리고 규칙 R4 가 쓴다 |
| [기존 과제와 같음] → 과제 고르기 | 그 팀 과제의 개인 `overlays.aliases` 에 label 추가, 제안 `mapped`(`mapped_to`), 붙어 있던 단위업무 라벨이 그 과제로 |
| [이름 바꾸기] | label 변경(§9 중복 검사 다시) |
| [거절] | `rejected`, 붙어 있던 군집은 다음 실행에 `regv` 로 다시 묻는다(답이 또 NEW 이고 같은 이름이면 예약 과제로) |
| [다른 제안과 합치기] | `merged_into` 기록, 군집 이동 |

### 7.6 팀으로 — 팀 묶음 `proposals[]` 와 팀 레지스트리의 받아들이기

- 팀 묶음 빌드 때: 라벨이 제안을 가리키는 역할이 하나라도 있는 제안(`pending`·`accepted_local`)을 `proposals[]` 에 싣는다 — `{"proposal_id", "kind": "project", "label": team_text(label, 40), "domain_guess": dom_guess}`(팀 명세 §2.3.2). 개인 과제 `L-…` 의 역할은 `project_id` 가 아니라 그 과제의 `proposal_id` 로 싣는다(`L-` ID 는 팀에 의미가 없다).
- 미리보기에서 제안 행을 [빼기] 하면 그 제안의 역할은 `proposal_id=null, project_id=null`(=`UNC`)로 실린다(시간은 그대로 — 팀 명세 §2.5 원칙).
- 팀장이 `/admin` 에서 받아들이는 방법은 둘이다: (a) 새 과제를 만들고 `adopted` 에 `{person_key, proposal_id}` 를 남긴다, (b) 기존 과제의 `aliases` 에 제안 이름을 넣는다.
- 클라이언트가 새 레지스트리를 받으면(§3.4): (a) `adopted` 에 내 `person_key`·제안 ID 가 있으면 그 제안과 개인 과제를 `mapped`·`maps_to` 로, (b) 제안·개인 과제 이름의 `ukey` 가 팀 과제 별칭과 같으면 자동 대응. 화면 알림 "제안 '방열 모듈' → 팀 과제 P-0021 로 연결됨". 사용자 조작은 필요 없다.

---

## 8. 레지스트리가 빈 초기 — 코드네임 검토와 taxonomy 부트스트랩

### 8.1 0단계(로컬) — 과제 이름 후보 검토

레지스트리가 비어 있으면 정제기는 어떤 낱말이 사내 코드네임인지 모른다. 그 상태로 코파일럿에 제목·파일명을 보내면 코드네임이 그대로 나간다(B14 위반). 그래서 코파일럿 분류를 열기 전에 **내 PC 에서만** 코드네임 후보를 보여 주고 표시를 받는다.

```python
def codename_candidates(F, groups, reg, cfg) -> list[Cand]:
    # 재료: 메일·회의 제목, 첨부·파일 이름, 창 제목, 그룹 대화방 이름(정제문 — 사람·번호는 이미 가려짐)
    stats = {}
    for f in F:
        raw = NFKC(f.text)
        toks = set(CODE_RX.findall(raw)) | tokens_of(raw)          # CODE_RX: [A-Za-z]{1,8}[-_]?\d{1,4}[A-Za-z]? | [A-Z][A-Z0-9]{2,}
        for t in toks: stats[norm(t)].add((f.group, iso_week(f.t), f.kind, f.is_file_prefix(t), f.in_brackets(t)))
    out = []
    for t, s in stats.items():
        if len(t) < 2 or t in BOILERPLATE ∪ VOCAB_KEYWORDS ∪ DOMAIN_KEYWORDS ∪ GENERIC_STEMS ∪ COMMON_WORDS ∪ APP_NAMES: continue
        if ukey(t) in reg.alias_ix or sha1(ukey(t))[:8] in ignored: continue
        n_groups = |{g}|; n_weeks = |{w}|
        if n_groups < 3 or n_weeks < 2: continue
        score = 2.0 * is_code_like(t) + 1.0 * (file_prefix_share >= 0.5) + 1.0 * any(in_brackets) \
                + 0.5 * log2(n_groups) + 0.5 * (n_weeks >= 4)
        out.append(Cand(t, score, n_groups, n_weeks, examples=local_examples(t, 3)))
    return sorted(out, key=lambda c: (-c.score, c.token))[:cfg['hier.bootstrap.codenameTopN']]   # 30
```

- `COMMON_WORDS` 는 `lm27/hier/data/common_words.txt`(업무 일반어 약 300개 — 회의·보고·일정·검토·설계·해석·시험·자료·요청·공유 …, 사내 어휘 없음)다. `APP_NAMES` 는 프로그램 카탈로그의 표시 이름.
- 화면(개인 보고서 '초기 설정' 카드, 127.0.0.1 전용): 후보마다 건수·주 수·예시 제목 3개(로컬 원문 복원 없이 정제문)와 버튼 [과제 이름(코드네임)] · [고객사 이름] · [무시]. 맨 아래 [이대로 진행(나머지 무시)]·[건너뛰기].
  - [과제 이름] → 개인 과제 `L-…` 생성(`codenames=[후보]`, 영역은 그 후보가 나온 증거의 영역 키워드 다수결 — 없으면 DEV, 드롭다운으로 바꿈), 제안 `accepted_local`(§7.2).
  - [고객사 이름] → 개인 설정 `privacy.customers` 에 `{"id": "C9xx", "names": [후보]}` 추가(PRIVACY §17 키).
  - [무시] → `codename_review.ignored` 에 해시.
  - [건너뛰기] → `skipped=true`. 코파일럿 단계가 열리지만 화면에 "레지스트리 없이 코파일럿을 쓰면 제목 속 과제 이름이 그대로 갈 수 있습니다" 경고를 남긴다.
- 표시가 끝나면 그 뒤 모든 전송은 브리지 게이트(`PRIVACY.md` §13 — 전송 직전 같은 정제기, **현재** 유효 레지스트리 문맥)가 새 코드네임을 `[과제:L-…]` 로 바꿔 보낸다. 이미 저장된 행은 로컬에만 있으므로 다시 쓰지 않는다.
- 이 단계는 레지스트리에 비예약 과제가 하나라도 생기면(팀이든 개인이든) 다시 띄우지 않는다. 팀 레지스트리가 나중에 채워지면 팀 코드네임이 우선한다.

### 8.2 1회차 — `taxonomy_bootstrap/1.0`(과제 체계 제안)

LM20 의 '계층 규율' taxonomy 프롬프트(사용자가 '나름 잘했다'고 한 부분 — hierarchy-reports keep)를 LM27 계층에 맞게 옮긴다. 결과는 **제안 큐로만** 간다(브리지 §8.8 예약 자리를 이 문서가 채운다).

**언제**(하나라도):

| 조건 | 설정 |
|---|---|
| 유효 레지스트리의 비예약 active 과제(팀 + 개인) 0개, 명명 군집 ≥ 20, 코드네임 검토 완료·건너뜀 | `hier.bootstrap.minGroups`(20) |
| 사용자가 [과제 체계 제안 받기] | — |
| 최근 30일 투입 중 `UNC`·예약 과제·제안 과제 비중 ≥ 0.5 이고 마지막 부트스트랩 후 30일 이상 | `hier.bootstrap.unclassifiedShare`(0.5)·`cooldownDays`(30) |

**표본**: 군집을 투입 내림차순으로 놓고, 같은 규칙 이름(`ukey`)은 3개까지만, 최대 `hier.bootstrap.maxLines`(100)줄을 고른 뒤 입력 예산에 맞을 때까지 뒤에서 뺀다. 참조 구현 H46: 줄 평균 80자, 빈 레지스트리 80줄·과제 10개 레지스트리 75줄이 8,000자에 들어간다.

| 열 | 값 |
|---|---|
| 영역후보 | 규칙 영역 코드(§4.7, 예약 과제면 그 영역), 모르면 `-` |
| 이름안 | 규칙 이름(§5.3) |
| 파일 | 문서 이름 ≤ 2개 |
| 제목 요지 | 대표 시작 근거 제목 1개 ≤ 50자 |
| 상대 | 상대 계급 ≤ 2개(§6.2 와 같은 값) |

**프롬프트 실물**(참조 구현 `spec_prompt_bootstrap.txt`, 표본 4줄 — 1,642자):

```text
[LM27 요청 R3KQ7M · 과제 체계 제안 · 표본 4줄]
당신은 한 엔지니어의 업무 흔적을 팀 과제 체계로 정리하는 설계자입니다. 아래 [표본]은 이 사람의 단위업무 묶음을 투입이 큰 순서로 고른 것입니다.
이 사람의 업무를 묶는 '상위 과제' 목록을 제안하세요.
규칙(계층 규율):
- 과제는 제품·프로젝트·과제 코드·고객 대응 건처럼 여러 업무를 묶는 상위 대상만입니다.
- 'OO 설계'·'OO 보고서 작성'·'OO 검토' 같은 활동 이름은 과제가 아닙니다. 그 활동이 속한 상위 과제를 세우고 활동은 쓰지 않습니다.
- 파일 이름 조각·코드 모듈 이름·확장자·날짜·버전은 과제가 아닙니다. 한 도구의 여러 부품은 그 도구 이름 하나로 묶습니다.
- 같은 대상의 표기 변형(띄어쓰기·대소문자·한영·약칭)은 이름 하나로 씁니다. 괄호 꼬리((양산)·(선행))나 차수 숫자가 다르면 따로 씁니다.
- 과제가 아닌 팀 운영·사무는 kind 를 common 으로, 업무가 아닌 것은 nonwork 로 씁니다.
- 과제마다 업무영역 dom 을 [업무영역] 코드 하나로 고릅니다.
- [이미 있는 과제]와 같은 대상이면 새로 만들지 말고 그 코드를 code 에 씁니다(이름은 비워도 됩니다).
- obs 에는 근거가 된 [표본] 번호를 최대 5개, match 에는 그 과제를 알아볼 낱말을 최대 5개(각 20자 이내) 씁니다.
- 과제는 많아야 15개입니다. [표본]에 흔적이 없는 것은 넣지 않습니다.
[업무영역] DEV 개발 프로젝트 · MP 양산 프로젝트 · EXT 외부 업무지원 · COM 공통 업무 · AX AX 프로젝트
[이미 있는 과제] 코드 · 업무영역 · 설명
(없음)
[표본] 번호 | 영역후보 | 이름안 | 파일 | 제목 요지 | 상대
1 | DEV | 공차해석 | 공차해석_v3.xlsx | [과제:L-0001] 공차 해석 결과 공유 | [고객사:C01]
2 | MP | 수율 개선 대책 | 수율개선_대책.pptx | 라인 수율 개선 회의 | 사내
3 | COM | 8월 정산 | 정산내역.xlsx | 8월 [금액] 정산 품의 | 사내
4 | - | 해석 프로그램 작업 | - | - | -
[답 형식]
- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다. 코드 블록 밖에는 설명을 쓰지 않습니다.
- rid 에는 "R3KQ7M" 를, n 에는 items 의 개수를 씁니다. id 는 1부터 차례로 씁니다.
- 문자열 값은 큰따옴표로 감싸고 값 안에서 줄을 바꾸지 않습니다.
- 근거가 부족하면 지어내지 말고 그 과제를 빼고 씁니다.
- 사람 이름·전화번호·메일 주소·금액은 쓰지 않습니다. [전화]·[금액]·[사람] 같은 꺾쇠 표기는 가려진 값입니다.
- 웹 검색을 하지 말고 이 메시지에 적힌 내용만으로 답합니다.
- 형식(<…> 자리에 실제 값): {"rid": <요청번호>, "n": <과제 수>, "items": [ {"id": <1부터>, "name": <과제 이름 20자 이내>, "code": <이미 있는 과제 코드 또는 "">, "dom": <업무영역 코드>, "kind": <project|common|nonwork>, "match": [<낱말>], "obs": [<표본 번호>]} ]}
- 코드 블록이 끝나면 맨 마지막 줄에 [[END R3KQ7M]] 만 씁니다.
```

- 표본 1의 `[과제:L-0001]` 은 0단계에서 표시한 코드네임이 게이트에서 토큰으로 바뀐 모습이다. `[이미 있는 과제]` 에는 개인 과제도 `L-0001 · DEV · <copilot_desc>` 로 실린다(이 예는 0단계를 건너뛴 경우의 '(없음)').
- `StageSpec`: `id="taxonomy_bootstrap"`, `prompt_ver="taxonomy_bootstrap/1.0"`, `kind="single"`(**행 봉투** — 요청 번호 집합이 없고 `n == len(items)` 로 검증, 브리지 §6.6 의 조회 단계 규칙과 같되 `no_web_rule` 은 넣는다 — §16 X6), `model_class="deep"`, `chat_policy="fresh_each"`, `est_out_fixed=80`, 행당 답 150자 × `max_models`(15) = 2,250자, `names_field=""`(앞서 쓴 이름 없음), `send_fields=("dom","title","files","subject","peer")`, `text_fields=("title","files","subject","peer")`.
- **행 스키마**:

```python
(F("name", "str", required=False, max_len=20),
 F("code", "code", codes="projects_nonreserved", extra_codes=("",)),     # 팀·개인 active, 예약 제외
 F("dom", "enum", enum=("DEV", "MP", "EXT", "COM", "AX")),
 F("kind", "enum", enum=("project", "common", "nonwork")),
 F("match", "list", required=False, max_items=5, item=(F("_", "str", max_len=20),)),
 F("obs", "list", required=False, max_items=5, item=(F("_", "int"),)))
```

  `validate`: `code==""` 이면 `name` 2자 이상, `obs` 는 1~표본 줄 수, 같은 답 안에서 `ukey(name)` 중복은 뒤의 것 버림, `name` 에 금액 패턴·`[사람` 이 있으면 행 무효. 시간형 키는 행 무효. 행 수가 `max_models` 를 넘으면 넘는 행은 버리고 `caps_hit`.

### 8.3 2회차 — `taxonomy_consolidate/1.0`(통합 확인)

LM20 의 consolidate 왕복을 남기되, 결과는 **병합이 아니라 병합 근거 하나**(§9.3 'AI 통합 제안 +1.0')로만 쓴다.

- 입력 항목 = 1회차 `code=""`·`kind ∈ {project, common}` 행(≤ 15) + 이미 있는 `pending` 제안(≤ 15). 항목 줄: `{n} | {이름} | {영역} | {알아볼 낱말 ≤3}`.
- 프롬프트(머리말 — 골격은 브리지 §6.2):

```text
[LM27 요청 {rid} · 과제 체계 통합 확인 · 항목 {n}개]
아래는 한 엔지니어의 업무를 분류하려고 초안으로 뽑은 '상위 과제' 목록입니다. 같은 대상이 다른 이름으로 갈린 것을 찾아 주세요.
규칙:
- 같은 제품·프로젝트의 축약·확장·한영 표기, 상위·하위로 겹치는 것만 같은 대상으로 봅니다.
- 괄호 꼬리((양산)·(선행))나 차수·버전 숫자가 다르면 같은 대상이 아닙니다.
- 확실하지 않으면 묶지 않습니다(same_as 를 0 으로).
[항목] 번호 | 이름 | 영역 | 알아볼 낱말
1 | 방열 모듈 | DEV | 방열, 열해석
2 | 방열모듈 개발 | DEV | 방열
…
```

  `format_line`: `{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "same_as": <같은 대상인 다른 항목 번호 또는 0>, "conf": <h|m|l>} ]}`, `unknown_rule`: `"same_as 는 0, conf 는 l 로 씁니다"`.
- 스키마 `F("same_as", "int")`(0 또는 다른 항목 번호, 자기 자신이면 무효), `F("conf", "enum", enum=("h","m","l"))`. `kind="items"`, `model_class="deep"`, `max_items=30`, `est_out_per_item=40`.
- 쓰임: `conf ∈ {h, m}` 인 `(id, same_as)` 쌍만 `ai_pairs`(이름 `ukey` 쌍)로 §9.3 에 넘긴다.

### 8.4 결과 처리

| 1회차 행 | 처리 |
|---|---|
| `code` 가 있음(이미 있는 과제) | 부트스트랩 보고에만 표시("코파일럿이 표본 1·4 를 P-0007 로 보았습니다"). 라벨·규칙·후보에 쓰지 않는다(H-I6) |
| `code=""`, `kind=project` | `on_new_name(name, dom, 표본의 군집들, 'bootstrap')` → 제안. `match` 는 `match_words`(비활성) |
| `code=""`, `kind=common` | 같은 처리, 단 `dom ∉ {COM, EXT}` 이면 `COM` |
| `kind=nonwork` | 표본 군집에 표식 `nonwork_hint`(보고서 배지 '업무가 아닌 것으로 보임'). 시간·라벨은 바꾸지 않는다 — 업무 여부는 정제기·시간 코어의 사적 판정 소관 |

- 2회차 쌍은 §9 점수로 묶음 후보가 되고, 자동 구간이라도 **AI 근거만으로는 질문 구간을 넘지 못한다**(§9.3). 질문 H04 로 사람에게 묻는다.
- 부트스트랩은 과제를 만들지 않는다. 결과 화면은 '제안 n개'와 [모두 내 과제로 받기]·[하나씩 보기]를 보인다.

---

## 9. 이름 병합 거버넌스 — 자동 / 질문 / 거부

### 9.1 무엇을 합치는가 — 범위별 권한

| 범위 | 대상 | 자동 병합 | 질문 | 누가 결정 |
|---|---|---|---|---|
| S1 | 같은 역할 업무 안의 **단위업무 이름**(명명 군집 사이) | 허용 | H04 | 본인 |
| S2 | 같은 사람의 **제안 ↔ 제안** | 허용 | H04 | 본인 |
| S3 | **제안 ↔ 등록 과제**(별칭 후보) | `ukey` 동일일 때만 | 그 밖 자동·질문 구간 모두 H04 | 본인(개인 별칭) / 팀장(팀 별칭) |
| S4 | **등록 과제 ↔ 등록 과제** | **금지** | 팀장 화면 제안 목록 | 팀장(`merged_into`) |
| S5 | **팀원 사이 제안**(팀 서버) | 금지 | 팀장 화면 묶음 후보 | 팀장(§9.6) |
| S6 | agentic 새 니즈 라벨 | 금지 — 나란히 보인다 | — | 팀장(카탈로그 승격, 팀 명세 §4.7) |

역할 업무 이름은 병합 대상이 아니다(역할은 코드 세 값의 조합이라 이름이 없다). 서로 다른 역할의 단위업무 이름은 비교하지 않는다.

### 9.2 비교 축(`lm27/hier/names.py` 하나)

| 함수 | 정의 |
|---|---|
| `fold(s, drop_note)` | 구분자(`·・ㆍ‧_-/–—－／`)를 공백으로 → NFKC → 다시 치환 → (drop_note 면 끝 괄호 제거) → 공백 접기 → casefold |
| `ukey(s)` | `fold(s, drop_note=False)` 에서 공백 제거 — 괄호 꼬리 보존 |
| `note(s)` | 끝 괄호 안 표기(casefold) |
| `num_tokens(s)` | 숫자 덩어리 집합(차수·버전) |
| `name_toks(s)` | `fold(s, False).split()` 집합 |
| `bigram_dice(a, b)` | `fold(·).replace(" ","")` 의 2-gram Dice |

LM24 의 `ukey2`·`ukey3`·`team_report.ukey` 세 벌을 이 한 벌로 통일한다(팀 서버 별칭 중복 검사도 같은 함수 — §16 X2).

### 9.3 점수 — `pair_score(a, b, ctx) -> (score, why)`

LM24 `details.pair_score` 를 옮기고 LM27 개체에 맞게 근거를 바꿨다.

| 순서 | 조건 | 점수 |
|---|---|---|
| 1 | `{ukey(a), ukey(b)}` 가 `never_pairs`(팀·개인) 또는 한쪽 과제의 `never` 에 있음 | **−∞** |
| 2 | `note(a) ≠ note(b)`('(양산)' vs '(선행)') | **−∞** |
| 3 | `num_tokens(a) ≠ num_tokens(b)`('2차' vs '3차') | **−∞** |
| 4 | 둘 다 등록 과제 이름·별칭이고 ID 가 다름 | **−∞**(클라이언트는 S4 를 하지 않는다) |
| 5 | 두 쪽 영역이 모두 **확정**(등록 과제·받아들인 개인 과제)이고 다름 | **−∞** |
| 6 | `ukey(a) == ukey(b)` | **10.0** |
| 7 | `d = bigram_dice(a, b) > 0.45` | + 2.4 × (d − 0.45) |
| 8 | 공유 근거 Jaccard `j`(두 쪽 군집의 문서군·대화·상대 키) | + 2.0 × j, 단 j = 0 이고 양쪽 근거 ≥ 2 면 − 0.8 |
| 9 | 고객사 토큰 공유 | + 1.2 |
| 10 | 영역 추정이 다름(확정 아님) | − 0.8 |
| 11 | 한쪽 이름 토큰이 다른 쪽의 진부분집합이고 대칭차 ≥ 2 | − 0.5 |
| 12 | 근거 시기 비겹침: 마지막·첫 근거 사이 ≥ `hier.merge.spanGapDays`(120일) | − 0.6 |
| 13 | AI 통합 제안(§8.3 `ai_pairs`) | + 1.0. **단 7~9 의 비AI 가점 합 ≤ 0 이면 점수를 `auto` 문턱 바로 아래(0.99)로 제한** — AI 단독 근거로는 자동 병합하지 않는다 |

참조 구현(H34): '광학설계' vs '광학 설계' → 10.0 자동 / '과제A 후속' vs '과제A' → 0.52 질문 / '브라켓(양산)' vs '브라켓(선행)' → −∞ / '센서 2차' vs '센서 3차' → −∞ / 'AX' vs 'Agentic AI'(AI 통합 제안만) → 0.99 질문 / '과제A' vs '과제B'(둘 다 등록) → −∞ / '공차해석 자동화' vs '공차 해석 자동화 툴' → 1.135 자동.

### 9.4 세 구간

| 구간 | 점수 | 행동 |
|---|---|---|
| 자동 | ≥ `hier.merge.auto`(1.0) | 범위가 허용하면(§9.1) 합친다. 대표: 이름은 투입 큰 쪽, 제안은 먼저 만든 쪽(ID 안정). `merge_log` 기록 |
| 질문 | [`hier.merge.ask`(0.35), 1.0) | 합치지 않고 H04 로 묻는다. 답 '같다' → 합침, '다르다' → 개인 `never_pairs` |
| 거부 | < 0.35 또는 −∞ | 아무것도 하지 않는다(−∞ 는 사유를 로그에) |

### 9.5 제약 클러스터링

쌍 단위 판정만 하면 never 로 갈라 둔 두 이름이 제3의 이름을 거쳐 합쳐진다(LM24 실측). 그래서 무리 안에서 제약을 강제한다.

```python
def cluster(names, W, order, cap=hier.merge.cap(5)):
    # W[(a,b)] = pair_score, order = 결정적 순서(대표 후보 우선 → 투입 내림 → ukey 오름)
    part, placed = [], set()
    for p in order:                                   # Pivot(KwikCluster)
        if p in placed: continue
        grp = [p]; placed.add(p)
        for x in order:
            if x in placed or W.get(pair(p, x), 0) < W_MERGE: continue
            if len(grp) + 1 <= cap and all(W.get(pair(x, y), 0) != -inf for y in grp):
                grp.append(x); placed.add(x)
        part.append(grp)
    return local_search(part, W, rounds=6)            # 한 이름을 다른 무리·단독으로 옮겨 목적함수(무리 안 음수 + 무리 밖 양수)가 줄면 이동, −∞ 무리 금지
```

- 크기 상한을 넘는 무리는 만들지 않는다(과병합 방지). 참조 구현 H35: '열해석'·'열 해석'·'열해석(양산)' → `[열 해석, 열해석]`, `[열해석(양산)]`.

### 9.6 기록·되돌리기·팀 서버

- `data\local_only\hier\merge_log.jsonl`(추가 전용): `{"at", "scope", "a", "b", "score", "zone", "why", "applied", "by"}`. 화면의 [되돌리기]는 그 쌍을 개인 `never_pairs` 에 넣는다(다음 실행에서 갈라짐) — 로그 줄을 지우는 방식이 아니라 반대 결정을 남기는 방식이라 방향 뒤집힘(LM24 F4 순환)이 없다.
- 팀 서버 `/admin` 의 '제안 묶음 후보': 모든 팀원 묶음의 `proposals[]` 를 모아 `pair_score`(근거는 이름·`domain_guess` 뿐 — 서버에는 근거 키가 없다)로 자동·질문 구간 쌍을 보이고, 각 묶음에 사람 수·제안 과제 MM 합(서버 재계산)을 단다. 팀장이 [새 과제로 등록](adopted 일괄)·[기존 과제의 별칭으로]·[무시]를 고른다. 서버는 스스로 합치지 않는다.

---

## 10. 업무 유형 판정 · 참여 방식 · AX 연계

### 10.1 업무 유형 — `decide_wtype(u, ff, rl) -> (code, conf, why)`

유형은 '이 단위업무에서 한 일의 종류'다. 결정 목록을 **위에서부터** 보고 처음 맞는 줄을 쓴다(결정적).

| 순서 | 조건 | 유형 | 확신 |
|---|---|---|---|
| 0 | 사용자 라벨·수동 기록의 유형 | 그 값 | h |
| 1 | 팀 규칙·학습 규칙의 `then.wtype` 적중 | 그 값 | m |
| 2 | 현장 낱말(현장·출장·라인·입고검사·방문·설치·시운전·필드 — `head` 모드) 적중 **또는** PC 밖 귀속 비중 `offpc_min / effort_min ≥ 0.5` | `FIELD` | 둘 다면 m(PC 밖 ≥ 0.3), 하나면 l |
| 3 | 교육 낱말(교육·강의·세미나·학회·수강·워크숍) 적중 **그리고** (영역 ∈ {EXT, COM} 또는 기능 = `STUDY`) | `EDU` | m |
| 4 | `kind == COORD`(내가 보낸 지시로 시작한 조율형) | PM 낱말(일정·예산·마일스톤·wbs·견적·계약·고객) 적중 또는 상대에 고객사·협력사 → `PM`, 아니면 `PL` | m |
| 5 | 기능 = `PM` | `PM` | l |
| 6 | 공학 앱 비중 `tech/effort ≥ 0.3`, 또는 기능 ∈ {DESIGN, ANALYSIS, TEST, IMPL} 이고 공학 앱 분 > 0 | `DEV` | ≥ 0.5 h, ≥ 0.3 m, 그 밖 l |
| 7 | 영역 = EXT 또는 기능 = `SUPPORT` | `SUPPORT` | l |
| 8 | 그 밖 | `OFFICE` | 공학 앱 비중 < 0.1 이면 m, 아니면 l |

- '공학 앱'은 카탈로그 범주 CAD·해석·광학·EDA·FPGA·SW·계측(§4.8 `TECH_CATS`). 사무 앱·메일·메신저·브라우저는 아니다.
- 문턱은 설정 `hier.wtype.techShareDev`(0.3)·`techShareHigh`(0.5)·`offpcFieldShare`(0.5)·`offpcFieldBoth`(0.3) — 미보정(★) 표식.
- 참조 구현(H16~H22): CAD 300분 → DEV(h) / 해석 200분 → DEV(h) / 조율형·사내 → PL(m) / 조율형·고객사 → PM(m) / '입고검사 현장 방문' + PC 밖 240분 → FIELD(m) / '산학 세미나 발표 요청' + EXT → EDU(m) / '8월 예산 정산' + 사무 앱만 → OFFICE(m).
- 코파일럿 답의 `wtype` 은 §6.5 규칙으로 섞는다(규칙 h 는 지킨다).

### 10.2 참여 방식 `stance`(개인 보고서 전용, v1)

PM·PL 이 '유형'인지 '그 업무에서의 역할'인지 조사에서 열린 질문이었다. 둘 다 기록한다: 유형(§10.1)과 별도로 참여 방식을 둔다.

| 순서 | 조건 | 값 |
|---|---|---|
| 1 | `kind == COORD` | `COORD`(조율) |
| 2 | 내가 주최한 연결 회의 ≥ 1 **그리고** 이 업무 대화에서 내가 보낸 `request` ≥ 1 | `LEAD`(주도) |
| 3 | `kind == S1`, 투입 < 30분, 원문(정제문)에 `검토\|리뷰\|확인\|승인` | `REVIEW`(검토) |
| 4 | 그 밖 | `DO`(실무) |

- '검토'는 토큰화에서 상용구로 빠지므로(§4.3) 3번은 토큰이 아니라 정제문에 정규식으로 본다.
- 팀 묶음에는 싣지 않는다(v1). 팀에서도 필요하면 `units[].stance` MINOR 추가를 요청한다(§17 미결 Q4).

### 10.3 AX 연계 `ax_link`

요구서: AX 프로젝트는 '개발·양산 등과 연계하거나 별도'. MM 을 두 번 세지 않는다.

```python
def ax_link(u, domain, reg, project) -> bool:
    if domain == 'AX': return False                                  # AX 영역 과제 자체 — 연계 표식 불필요
    if project and reg.projects[project].ax_link: return True        # 팀장이 과제 단위로 지정
    hits = {k for k in domain_kw['AX'] if (k == 'ai' and re.search(r'(?<![a-z])ai(?![a-z])', text_lower(u)))
                                          or (k != 'ai' and kw_hit(k, toks(u), 'head'))}
    strong = {'llm', 'rag', 'copilot', '코파일럿', '에이전트', 'agentic', '에이전틱', '생성형'}
    return bool(hits & strong) or len(hits) >= cfg['hier.ax.minHits']   # 2
```

- MM 은 그 단위업무의 과제 영역(DEV·MP·…)에만 계상한다. 팀 보고서는 영역별 막대 안에 'AX 연계 MM'(그 영역 중 `ax_link=true` 단위업무의 alloc 합)을 빗금으로 보인다(팀 명세 §4.5 의 같은 식에서 `x` = `ax_link`).
- 참조 구현 H23: `[과제:P-0007] LLM 기반 시험 성적서 자동 분류`(DEV) → true, 같은 문장이 AX 과제(`P-0011`)면 false.

---

## 11. 신뢰도 · 확인 질문 · 사용자 수정과 규칙 학습

### 11.1 라벨 자료구조와 신뢰 등급

```python
@dataclass
class UnitLabel:
    unit_id: str
    group: str                          # 'grp:<12hex>'
    project: str | None                 # 'P-…' | 'L-…' | 'P-99xx' | None(UNC)
    proposal_id: str | None             # 제안 과제면 'pr_…' (project 는 None), 개인 과제면 그 과제의 proposal_id
    domain: str                         # 유도값(H-I2) — 'DEV'…'AX' | 'UNC'
    field: str; func: str; wtype: str   # 어휘 코드(빈 값 없음 — ETC·OFFICE 로)
    stance: str                         # DO|COORD|REVIEW|LEAD
    ax_link: bool
    role_id: str                        # R-8 식(과제 자리 = project(P-) 또는 proposal_id 또는 'UNC')
    title: str; title_src: str          # user|ai|rule_doc|rule_subject|rule_app|rule_generic
    src: dict[str, str]                 # 필드 → user|token|rule|domain_rule|rule_probable|ai_h|ai_m|ai_l|fallback|none
    conf: dict[str, str]                # 필드 → h|m|l
    level: str                          # confirmed|high|medium|low|unclassified (과제 축 요약)
    cands: list[tuple[str, float]]
    why: list[str]                      # 설명 원장 조각(규칙 ID·가점) — 로컬 전용
    flags: list[str]                    # proposal|retired_project|ai_conflict|nonwork_hint|rejected_name|too_small …
```

| 과제 축 출처 | `level` | 화면 배지 |
|---|---|---|
| `user` | `confirmed` | 확인됨 |
| `token`, `rule`(h), `ai_h` 이면서 규칙 후보 1위와 같음 | `high` | 높음 |
| `rule`(m), `domain_rule`, `ai_h`(규칙 지지 없음), `ai_m` | `medium` | 보통 |
| `rule_probable`, `ai_l`, `fallback`, 제안 과제 | `low` | 낮음 |
| `none`(UNC) | `unclassified` | 미분류 |

- 개인 보고서 KPI: **분류 신뢰 비중** = (`confirmed` + `high` 단위업무 투입) ÷ 전체 단위업무 투입, **미분류 비중** = `unclassified` 투입 ÷ 전체 단위업무 투입. 둘 다 정수 분 표에서 낸다.
- 보고서는 관측(규칙)과 추정(AI·유력)을 시각적으로 구분한다(결정 메모 §8). 각 단위업무 행의 [왜?] 를 누르면 `why` 를 보인다(예: `과제 P-0007 ← 토큰 [과제:P-0007](의뢰 메일) +6.0 · 키워드 '브라켓' +2.0 → 증거 점수 1.00 × 가중 2.0`).

### 11.2 확인 질문 H01~H06

시간 명세의 확인 큐(`WORKTIME_METHOD.md` §7.3 Q01~Q18)와 **같은 화면**에 띄우되 코드를 `H` 로 구분하고 주간 상한을 따로 센다.

| 코드 | 이름 | 조건 | 묻는 것(선택지) | 응답 → 수정 기록 |
|---|---|---|---|---|
| H01 | 과제미정 | 군집 `level == unclassified`, 또는 예약 과제 + `low`, 그리고 군집 투입 ≥ `hier.queue.minEffortH`(2h) | 어느 과제인가요?(후보 3개 · 영역 일반 · 새 과제 · 업무 아님) | `set.project` |
| H02 | 규칙·AI충돌 | §6.5 충돌(AI h ≠ 규칙 확정, 또는 AI h 가 규칙 유력 1위를 이김) | 둘 중 무엇인가요?(규칙 과제 · AI 과제 · 그 밖) | `set.project` |
| H03 | 새과제확인 | 제안 `pending` 이고 (`n_units ≥ 2` 또는 투입 ≥ 4h) | 내 과제로 받기 · 기존 과제와 같음 · 거절 | §7.5 |
| H04 | 이름병합애매 | §9.4 질문 구간 쌍(이름·제안) | 같은 것인가요?(같다 · 다르다) | 병합 / `never_pairs` |
| H05 | 유형애매 | 유형 `conf == l` 이고 투입 ≥ 4h | 이 업무의 유형은?(7종) | `set.wtype` |
| H06 | 퇴역과제 | 병합 없이 퇴역한 과제로 라벨된 군집, 재질의 후에도 그대로, 투입 ≥ 2h | 어느 과제로 옮길까요? | `set.project` |

- `qid = sha1(코드 + "|" + 군집 키(또는 쌍의 ukey 정렬) + "|" + 핵심 근거)[:12]` — 다시 분석해도 같은 질문은 같은 ID(두 번 묻지 않는다).
- 우선순위 = (영향 투입 h + 0.01) × 가중(H01 1.0 · H02 0.8 · H03 0.7 · H06 0.6 · H05 0.4 · H04 0.3). ISO 주마다 상위 `hier.queue.maxPerWeek`(10)건.
- 질문은 선택 사항이다. 답이 없어도 라벨·보고서·팀 묶음은 그대로 만든다(답이 오면 다음 실행에 반영). 다른 사용자에게 묻지 않는다(본인 화면에서만).

### 11.3 사용자 수정 기록 `data\local_only\hier\corrections.jsonl`

수정은 단위업무 행·군집 행의 [분류 고치기], 확인 질문 응답, 수동 기록에서 온다. 추가 전용으로 쌓고, 분석은 매번 전체를 다시 적용한다(증분 상태 없음).

```json
{"at": "2026-10-06T09:12:00+09:00", "id": "c_7a1e09b2",
 "target": {"group": "grp:5d1c0a9e7b21", "anchor": "m3b9a…(시작 근거 키)",
            "unit_keys": ["m3b9a…", "m77c1…"], "fam_keys": ["d1a2f…"], "conv_keys": ["t0123…"], "dir_keys": []},
 "set": {"project": "P-0007", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "광학 모듈 공차 해석"},
 "scope": "similar", "from_queue": "H01:4f2a9c1d0e3b", "note": ""}
```

- **대상은 증거 키로 저장한다**(unit_id 가 아니다): 시간 명세 §2.7 과 같은 이유 — 자체 업무가 나중에 의뢰 메일을 얻어 unit_id 가 바뀌어도 수정이 따라간다.
- 적용 `apply_corrections(units, corrections)`: 단위업무 u 가 대상이면(① `u.first_key == anchor` ② u 의 경계 메시지 키 ∩ `unit_keys` ≠ ∅ ③ u 문서군 키 ∩ `fam_keys` 비율 ≥ 0.5 이고 대화 키 공유 — 이 순서로 먼저 맞는 것) `set` 의 필드를 출처 `user` 로 덮는다. 같은 필드를 고친 기록이 여럿이면 `at` 이 늦은 것이 이긴다. 어느 단위업무에도 맞지 않는 기록은 지우지 않고 '미적용 수정' 목록으로 보인다.
- `scope`: `this`(이 업무만) / `similar`(규칙으로 학습 — §11.4, 화면 기본값). 군집 행에서 고치면 군집 구성원 모두가 대상이다.
- 사용자가 고른 과제가 '새 과제'면 §7.5 [내 과제로 받기]와 같은 절차로 `L-…` 를 만들고 그 ID 를 `set.project` 에 쓴다.

### 11.4 규칙 학습 `learn_rules(corrections) -> rules_learned.json`

```python
def learn_from(c, feats_of_target, df, n_groups, existing) -> list[LearnedRule]:
    P = c.set.project; out = []
    if c.scope != 'similar' or not P: return out
    for k in c.target.conv_keys:  out.append(KeyRule('conv', k, P))        # 같은 메일 스레드·대화방 → 같은 과제
    for k in c.target.fam_keys:   if not generic(k): out.append(KeyRule('fam', k, P))   # 같은 문서군(첨부·자기 문서)
    if c.target.dir_keys and all_docs_share(c.target.dir_keys): out.append(KeyRule('dir', common_dir, P))
    cnt = Counter(t for f in feats_of_target for t in f.toks)
    cand = [t for t, n in cnt.items() if n >= 2 and len(t) >= 2 and df[t] / n_groups <= TOKEN_DF_MAX   # 0.05
            and t not in BOILERPLATE ∪ VOCAB_KEYWORDS ∪ DOMAIN_KEYWORDS ∪ GENERIC_STEMS]
    for t in sorted(cand, key=lambda t: (df[t], -cnt[t], t))[:TOKEN_MAX]:                              # 3
        prev = find(existing, token=t, project=P)
        sup = prev.support + 1 if prev else 1
        out.append(TokenRule(t, P, status='active' if sup >= TOKEN_SUPPORT else 'candidate', support=sup))  # 2
    # 분야·기능·유형: 사용자가 바꾼 축이 있고 그 업무의 주 앱(app_min 비중 ≥ 0.5)이 있으면 AppRule(app → 그 값), support 2 에서 active
    return out
```

| 규칙 종류 | 조건 키 | 가중 | 활성 조건 | 비고 |
|---|---|---|---|---|
| `key`(conv·fam·dir·repo) | 정확한 로컬 키 | 5.0(R2) | 바로(support 1) | 키는 HMAC 이라 오탐이 거의 없다 |
| `token` | 낱말(`name` 모드) | 2.5(R10) | 같은 과제로 2번 수정(support 2) | 문서 빈도 5% 이하의 드문 낱말만, 한 수정당 3개까지 |
| `app`(분야·기능·유형) | `app_id` | 2.0 | support 2 | |

- 참조 구현 H36: 첫 수정 → 대화 키 규칙 active + 토큰 규칙 2개 candidate('지그'는 문서 빈도 9% 라 제외), 같은 과제로 두 번째 수정 → 토큰 규칙 active. H37: 학습한 대화 키 규칙만으로 같은 스레드의 새 메시지가 증거 꼬리표 `P-0007`(5.0) 을 받는다.
- **정밀도 추적**(매 실행): 활성 학습 규칙마다 적중한 군집 수와, 그중 사용자·토큰 라벨이 있는 군집에서 규칙 과제와 일치/불일치를 센다. 적중 ≥ `hier.learn.retireMinHits`(5) 이고 정밀도 < `retireMinPrec`(0.6) 이면 `retired`(사유·날짜 기록 — H38: 2/6 → retired). 은퇴한 규칙은 사용자가 [다시 켜기] 전에는 돌아오지 않는다.
- 같은 키 규칙이 다른 과제를 가리키게 되면(나중 수정) 늦은 것이 이기고 앞의 것은 `superseded`.
- 학습 규칙은 개인 로컬이다(팀·코파일럿으로 가지 않음). 화면의 [팀 규칙으로 제안]은 v1 에서 팀장에게 전할 문구(조건·결과·적중 수)를 복사해 주는 것까지만 한다(§17 미결 Q3).

```json
{"schema": "lm27.rules_learned/1",
 "rules": [{"id": "LK-conv-t0123456", "kind": "key", "if": {"conv": "t0123456789abcdef"}, "then": {"project": "P-0007"},
            "w": 5.0, "status": "active", "support": 1, "from": ["c_7a1e09b2"],
            "hits": 4, "agree": 4, "disagree": 0, "created_at": "2026-10-06", "updated_at": "2026-10-20", "reason": ""},
           {"id": "LT-df9d6881", "kind": "token", "if": {"token": "광정렬"}, "then": {"project": "P-0007"},
            "w": 2.5, "status": "candidate", "support": 1, "from": ["c_7a1e09b2"],
            "hits": 0, "agree": 0, "disagree": 0, "created_at": "2026-10-06", "updated_at": "2026-10-06", "reason": ""}]}
```

### 11.5 무엇이 규칙이 되지 않는가

- 코파일럿 답(과제·이름·분야…)은 규칙·증거 꼬리표·레지스트리 힌트로 들어가지 않는다(H-I6). 들어가는 길은 사람의 수정(§11.3)과 팀장의 등록뿐이다. 관문 G-H7 이 `lm27/hier/learn.py` 의 입력이 `corrections.jsonl` 리더뿐인지 검사한다.
- 부트스트랩의 `match` 낱말도 사용자가 받아들일 때 고른 것만 개인 과제 키워드가 된다(§7.5).

---

## 12. 산출물과 인터페이스

### 12.1 결과 파일(분석 1회, `data\analysis\<run_id>\hier\`)

| 파일 | 내용 |
|---|---|
| `labels.json` | `{unit_id: UnitLabel}`(§11.1). `why` 포함 — 로컬 전용 |
| `groups.json` | 명명 군집 `{group_key: {"anchor", "members": [unit_id…], "title", "title_src", "project", "effort_min"}}` |
| `evidence_tags.jsonl` | 증거·문서군 꼬리표 `{id, proj, score, top2}` — 시간 코어에 넘긴 값의 기록(설명·디버그) |
| `queue.json` | 확인 질문 H01~H06(`QueueItem` 형 — 시간 명세 부록 A 와 같은 형) |
| `proposals_snapshot.json` | 이 실행 시점의 제안 큐 사본 |
| `hier_meta.json` | `{"hier_version": "hier/1", "registry_version": 7, "registry_source": "cache", "hier_hash": "…", "counts": {"units":…, "groups":…, "ai_items":…, "by_level": {…}}, "ai_share": 0.18, "unclassified_share": 0.06, "warnings": […], "cfg_used": {…}}` |

`labels.json` 한 항목 예:

```json
{"u_3e9a01c2d4": {"group": "grp:5d1c0a9e7b21", "project": "P-0007", "proposal_id": null, "domain": "DEV",
                  "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "stance": "DO", "ax_link": false,
                  "role_id": "r_8412d7", "title": "광학 모듈 공차 해석", "title_src": "ai",
                  "src": {"project": "rule", "field": "rule", "func": "ai_h", "wtype": "rule", "title": "ai_h"},
                  "conf": {"project": "m", "field": "h", "func": "h", "wtype": "h", "title": "h"},
                  "level": "medium", "cands": [["P-0007", 0.62], ["P-0008", 0.21]],
                  "why": ["P-0007 ← token [과제:P-0007] +6.0 (boundary m3b9a…)", "P-0007 ← keyword 브라켓 +2.0 (doc d1a2f…)"],
                  "flags": []}}
```

### 12.2 모듈과 함수 시그니처(`lm27/hier/`)

개인 PC·클라우드PC·팀 서버가 같은 모듈을 쓴다(사본 drift 금지 — LM24 X5 교훈). 결과에 `hier_version`(형식 `hier/<판>`, 이 문서 = `hier/1`)을 싣고, 이 문서의 산식·기본값이 바뀌어 같은 입력의 결과가 달라지면 판을 올린다.

```python
# lm27/hier/names.py
def fold(s: str, drop_note: bool = True) -> str: ...
def ukey(s: str) -> str: ...;  def note(s: str) -> str: ...;  def num_tokens(s: str) -> set[str]: ...
def name_toks(s: str) -> set[str]: ...;  def bigram_dice(a: str, b: str) -> float: ...

# lm27/hier/vocab.py  — 영역·어휘 단일원
DOMAIN_META: dict[str, dict]; RESERVED: dict[str, str]; BUILTIN_VOCAB: dict[str, list[VocabItem]]
def snap_domain(s: str) -> str: ...;  def domain_name(c: str) -> str: ...;  def domain_color(c: str) -> str: ...
def domain_order(c: str) -> int: ...;  def domain_prompt_line() -> str: ...
def legacy_code(name: str, kind: str) -> str: ...            # 문자열 어휘 → 코드(§2.3.4)

# lm27/hier/registry_schema.py
def validate_registry(obj: dict, side: Literal['server', 'client']) -> list[Err]: ...      # §2.4
def validate_local(obj: dict) -> list[Err]: ...

# lm27/hier/registry.py
def load_effective(paths, cfg, now) -> tuple[EffectiveRegistry, RegistryStatus]: ...    # §3.1
def merge(team: dict, local: dict, cfg) -> EffectiveRegistry: ...                        # §3.4
def hier_hash(reg: EffectiveRegistry) -> str: ...

# lm27/hier/match.py
def tokens_of(text: str) -> set[str]: ...;  def ent_tokens(text: str) -> dict[str, set[str]]: ...
def kw_hit(k: str, toks: set[str], mode: Literal['name', 'head']) -> bool: ...

# lm27/hier/features.py
def features_of(records: Iterable[dict], reg, person_dir, catalog, cfg) -> list[Feat]: ...   # §4.1

# lm27/hier/rules.py
def score_projects(f: Feat, reg) -> dict[str, float]: ...                                # §4.3
def score_domains(f: Feat, reg) -> dict[str, float]: ...                                 # §4.4
def tag_evidence(feats: list[Feat], reg, cfg) -> HierTags: ...                           # §4.5

# lm27/hier/unitlabel.py
def unit_inputs(tasks, feats, attrib, catalog) -> dict[str, UnitIn]: ...                 # §4.6
def unit_rule_label(u: UnitIn, reg, cfg) -> RuleLabel: ...                               # §4.7
def field_func(u: UnitIn, reg, rl: RuleLabel, cfg) -> FieldFunc: ...                     # §4.8
def decide_wtype(u: UnitIn, ff: FieldFunc, rl: RuleLabel, reg, cfg) -> tuple[str, str, str]: ...   # §10.1
def decide_stance(u: UnitIn) -> str: ...;  def ax_link(u: UnitIn, domain: str, reg, project) -> bool: ...
def role_id(project_or_proposal: str | None, field: str, func: str) -> str: ...

# lm27/hier/groups.py
def name_groups(tasks, rule_labels, cfg) -> list[Group]: ...                             # §5.2
def rule_title(group: Group, ctx) -> tuple[str, str]: ...                                 # §5.3
def display_stem(name: str) -> str: ...;  def subject_title(subj: str) -> str: ...

# lm27/hier/copilot_io.py  (브리지와는 ai_in/ai_out 파일로만 만난다 — 브리지 모듈을 임포트하지 않는다)
def build_task_label_items(groups, labels, ff, wt, store_index, reg, cfg) -> list[dict]: ...   # §6.1·§6.2
def read_ai_out(path) -> dict[str, dict]: ...
def build_bootstrap_samples(groups, labels, reg, cfg) -> list[dict]: ...                 # §8.2
def build_consolidate_items(rows, proposals) -> list[dict]: ...                          # §8.3

# lm27/hier/apply.py
def apply_labels(rule, ff, wt, ai, corrections, title_cache, proposals, reg, cfg) -> dict[str, UnitLabel]: ...  # §6.5

# lm27/hier/proposals.py
class ProposalQueue:
    def load(path) -> 'ProposalQueue': ...;  def on_new_name(label, dom, group, src, reg) -> Assign: ...
    def accept_local(pid, keywords) -> str: ...;  def map_to(pid, project) -> None: ...;  def reject(pid) -> None: ...
    def sync_registry(reg, person_key) -> list[str]: ...          # adopted·별칭 일치 → mapped(§7.6)
    def team_payload(labels) -> list[dict]: ...                    # 팀 묶음 proposals[]

# lm27/hier/merge.py
def pair_score(a: str, b: str, ctx: MergeCtx) -> tuple[float, str]: ...;  def zone(score: float) -> str: ...
def cluster(names: list[str], W: dict, order: list[str], cap: int) -> list[list[str]]: ...

# lm27/hier/learn.py
def apply_corrections(units, corrections) -> tuple[dict[str, dict], list[str]]: ...      # (unit → user set, 미적용 id)
def learn_rules(corrections, feats_by_unit, df, n_groups, existing) -> list[LearnedRule]: ...
def track_precision(rules, labels, hits) -> list[LearnedRule]: ...

# lm27/hier/queue.py
def hier_queue(labels, groups, proposals, conflicts, merge_asks, cfg) -> list[QueueItem]: ...

# lm27/hier/bootstrap.py
def codename_candidates(feats, groups, reg, cfg) -> list[Cand]: ...                      # §8.1
def needs_bootstrap(reg, labels, last_run, cfg) -> bool: ...

# lm27/hier/team_out.py
def team_parts(labels, reg, proposals, overrides) -> dict: ...    # projects[]·proposals[]·roles[]·units[] 라벨 필드(§12.4)

# lm27/hier/__init__.py
def classify_all(run_ctx) -> HierResult: ...    # §4.0 의 순서. 시간 코어와는 HierTags·labels 로만 만난다
```

### 12.3 시간 코어와의 연결

| 방향 | 무엇 | 형 |
|---|---|---|
| 분류 → 시간 | 증거 꼬리표 | `HierTags` = `{"msg": {msg_key: proj}, "fam": {fam_key: proj}, "shared_fams": set[fam_key]}`. `WORKTIME_METHOD.md` 부록 A `normalize(…, registry)` 의 `registry` 인자로 넘긴다 — 시간 코어는 이 세 값만 읽는다(§16 X8) |
| 시간 → 분류 | 단위업무·귀속 | `list[UnitTask]`(kind·conv·docs·cycles·first_key·follow_of·peer), 슬롯 귀속(`attrib.jsonl` 의 L2·L3·L5 조각 → `app_min`·`meet_min`·`offpc_min`), 정수 분 투입 |
| 분류 → 시간(롤업) | 라벨 | `rollup(month, labels)` 의 `labels[unit_id] = {"domain", "project", "role", "wtype", "ax_link"}`. 과제 자리는 **팀 묶음과 같은 값**(`P-…` 또는 제안 ID, 개인 과제는 그 제안 ID)으로 넘겨 개인 롤업과 팀 재합산이 같은 키를 쓰게 한다 |

### 12.4 팀 묶음 매핑(`TEAM_AND_BUNDLE.md` §2.3)

| 팀 묶음 필드 | 만드는 법 |
|---|---|
| `projects[]` | 라벨에 쓰인 `P-…`(예약 포함) 마다 `{"project_id", "domain"}`. `domain` 은 유효 레지스트리 값(서버는 자기 레지스트리 값을 우선한다) |
| `proposals[]` | §7.6 |
| `roles[]` | 라벨의 (과제 자리, field, func) 마다 `{"role_id", "project_id" 또는 null, "proposal_id" 또는 null, "field", "function"}`. **field·function 은 어휘 코드**(개인 `L_` 코드는 `maps_to` 또는 `ETC` 로 바꾸고 role_id 도 바꾼 코드로 다시 계산) |
| `units[].role_id` | 위 역할 |
| `units[].title`·`title_mode` | 군집 이름(§5) → `team_text(title, 40)`, 실패하면 `<분야 이름>·<기능 이름> 단위업무 #n` 과 `title_mode="generic"`(팀 명세 §2.4·§2.5) |
| `units[].activity_type` | 유형 코드 |
| `units[].ax_link` | §10.3 |
| `person.function` | 개인 로컬 `person.default_field` 코드 |
| `generator.registry_version`·`catalog_version` | 유효 레지스트리 값 |

- `stance`·`level`·`src`·`why`·`cands` 는 싣지 않는다(v1). 팀 보고서의 '분류 추정 비율'이 필요하면 `units[].label_level` MINOR 추가를 요청한다(§17 미결 Q4).

### 12.5 개인 보고서·화면에 주는 것

- 계층 트리(업무 영역 > 과제 > 역할 업무 > 단위업무)의 각 마디: 투입 h·건수·`level` 분포 막대. 제안 과제는 점선 테두리 + '제안' 배지, 예약 과제는 '<영역> — 과제 미지정' 행.
- 단위업무·군집 행의 [분류 고치기](과제·분야·기능·유형·이름, 범위 라디오 '이 업무만 / 비슷한 업무도') · [왜?] · [다시 분류].
- '초기 설정' 카드(§8.1), '새 과제 제안' 카드(§7.5), '학습한 규칙' 표(적중·정밀도·[끄기]·[다시 켜기]), '레지스트리 상태' 한 줄(§3.1).
- 근무 중 미분류(회의) 막대의 '과제 관련으로 보이는 회의' 보조 표시(§1.7 — MM 은 옮기지 않음).

---

## 13. 설정 키

단일 설정 레지스트리(결정 메모 §9 '죽은 키 금지')에 그대로 등록한다. 미등록 키는 오류, 형 불일치는 기본값 + 경고(시간 명세 §2.8 과 같은 규약). ★ = 미보정 정책값(사람 수정 비율로 보정할 대상 — §17 미결 Q7). 읽힌 키와 값은 `hier_meta.json` 의 `cfg_used` 에 남는다.

### 13.1 규칙 분류(`hier.rule.*`·`hier.domain.*`·`hier.tokens.*`)

| 키 | 기본 | 단위 | 근거 |
|---|---|---|---|
| `hier.rule.w.token` | 6.0 | 점 | 과제 토큰 = 정제기가 레지스트리 코드네임을 바꾼 것(가장 강함) |
| `hier.rule.w.keyRule` | 5.0 | 점 | 사람 수정에서 배운 정확 키 |
| `hier.rule.w.alias` | 4.0 | 점 | 평문 별칭(정제 전 행) — 단독으로 꼬리표 문턱 |
| `hier.rule.w.keyword` ★ / `keywordCap` | 2.0 / 4.0 | 점 | 키워드 2개부터 꼬리표 문턱 |
| `hier.rule.w.customer` ★ / `partner` / `mailDomain` | 1.5 / 1.0 / 1.5 | 점 | 공유 수로 나눔 |
| `hier.rule.w.folder` ★ | 3.0 | 점 | 폴더 + 키워드 1개면 문턱 |
| `hier.rule.w.app` | 1.0 | 점 | 과제 전용 앱(약함) |
| `hier.rule.w.teamRule` | 2.0 | 점 | 팀 규칙의 기본 `w` |
| `hier.rule.w.learnedToken` ★ | 2.5 | 점 | 학습 토큰 규칙 |
| `hier.rule.summaryMult` | 0.5 | 배 | 코파일럿 요약 증인 행 |
| `hier.rule.periodOutsideMult` | 0.5 | 배 | 과제 기간 밖 증거 |
| `hier.rule.evidenceMin` ★ / `evidenceMargin` ★ | 4.0 / 2.0 | 점 | 증거 꼬리표(시간 코어 연결 제약) 문턱 — 보수적 |
| `hier.domain.w` | `{"EXT": 2.0, "COM": 2.0, "AX": 1.5, "MP": 1.0, "DEV": 1.0, "기관": 1.5}` | 점 | 영역 키워드 가점 |
| `hier.domain.order` | `["EXT","AX","COM","MP","DEV"]` | — | 한 증거에 여러 영역이 맞을 때의 우선순위 |
| `hier.domain.confirm` ★ / `hier.domain.margin` | 0.5 / 0.2 | 비 | 예약 과제 확정 |
| `hier.tokens.boilerplateAdd` | `[]` | — | 상용구 추가(시간 명세 boilerplate 에 더함) |
| `hier.publicSuffix` | `{".ac.kr":"기관", ".re.kr":"기관", ".go.kr":"기관", ".or.kr":"기관", ".edu":"기관"}` | — | 레지스트리 `public_domain_classes` 가 덮는다 |

### 13.2 단위업무 판정(`hier.unit.*`·`hier.vocab.*`·`hier.wtype.*`·`hier.ax.*`)

| 키 | 기본 | 근거 |
|---|---|---|
| `hier.unit.w` | `{"boundary": 2.0, "msg": 1.0, "doc": 1.5, "meet": 1.0, "app": 1.0}` | 의뢰·보고 메시지가 가장 강한 단서 |
| `hier.unit.minMass` | 3.0 | 증거가 적은 업무의 점수를 낮춘다(문서 하나로 확정하지 않음) |
| `hier.unit.confirm` ★ / `margin` / `high` | 0.6 / 0.25 / 0.8 | 규칙 확정·확신 h |
| `hier.unit.fallback` / `probableMargin` | 0.5 / 0.1 | 규칙 유력(브리지 폴백 0.5 와 같음) |
| `hier.vocab.top` ★ / `margin` / `high` / `low` | 2.0 / 1.0 / 3.5 / 1.0 | 분야·기능 확신 |
| `hier.vocab.officeDocShare` / `meetShare` | 0.6 / 0.5 | 기능 DOC·MEET 구조 신호 |
| `hier.wtype.techShareDev` ★ / `techShareHigh` | 0.3 / 0.5 | 유형 DEV |
| `hier.wtype.offpcFieldShare` ★ / `offpcFieldBoth` | 0.5 / 0.3 | 유형 FIELD |
| `hier.ax.minHits` | 2 | AX 연계(강한 낱말은 1개로 충분) |

### 13.3 명명·코파일럿·제안·부트스트랩

| 키 | 기본 | 근거 |
|---|---|---|
| `hier.name.maxGroup` | 60 | 주간보고 1년치 |
| `hier.name.titleMax` | 25 | 프롬프트 지시와 같음(답 검증은 30 에서 자름·80 거부) |
| `hier.name.cacheKeepDays` | 400 | 제목 캐시 보존 |
| `hier.copilot.enabled` | true | false 면 규칙만(브리지 `bridge.mode=off` 와 별개로 이 단계만 끔) |
| `hier.copilot.askTitleWeak` | true | 이름이 약한 군집도 묻기 |
| `hier.copilot.vocabAskMinEffortH` | 1.0 | 분야·기능이 둘 다 l 인 군집을 물을 최소 투입 |
| `hier.copilot.maxGroupsPerRun` | 300 | 한 실행 상한(나머지는 다음 실행) |
| `hier.copilot.requireCodenameReview` | false | 켜면 초기 코드네임 검토 전 코파일럿 금지(§8.1) — v1.3 §0.8 V12 |
| `hier.copilot.reaskGrowth` | 2.0 | `conf=l` 답의 재질의: 증거 건수 배수 |
| `hier.proposals.minEffortMin` | 60 | 이보다 작은 군집은 제안을 만들지 않고 예약 과제로 |
| `hier.bootstrap.minGroups` | 20 | 1회차 자동 조건 |
| `hier.bootstrap.maxLines` / `maxModels` | 100 / 15 | 표본 줄·제안 상한 |
| `hier.bootstrap.unclassifiedShare` / `cooldownDays` | 0.5 / 30 | 재실행 조건 |
| `hier.bootstrap.codenameTopN` / `codenameMinGroups` / `codenameMinWeeks` | 30 / 3 / 2 | 코드네임 후보 |
| `hier.registry.staleWarnDays` | 14 | 오래된 레지스트리 표식 |

### 13.4 병합·학습·질문

| 키 | 기본 | 근거 |
|---|---|---|
| `hier.merge.auto` ★ / `ask` ★ | 1.0 / 0.35 | LM24 W_MERGE·W_ASK |
| `hier.merge.cap` | 5 | 무리 크기 상한(LM24 MAX_GROUP2) |
| `hier.merge.spanGapDays` | 120 | 시기 비겹침 감점 |
| `hier.learn.tokenDfMax` / `tokenMax` / `tokenSupport` / `appSupport` | 0.05 / 3 / 2 / 2 | 학습 규칙 |
| `hier.learn.retireMinHits` / `retireMinPrec` | 5 / 0.6 | 은퇴 |
| `hier.queue.minEffortH` / `wtypeMinEffortH` / `proposalMinEffortH` | 2.0 / 4.0 / 4.0 | 질문 대상 최소 투입 |
| `hier.queue.maxPerWeek` | 10 | 시간 질문(15)과 별도 |
| `hier.queue.weights` | `{"H01":1.0,"H02":0.8,"H03":0.7,"H06":0.6,"H05":0.4,"H04":0.3}` | 우선순위 |

다른 명세 소관이지만 이 문서가 읽는 키: `team.registry_refresh_h`·`team.registry_timeout_s`·`team.offline_dir`(팀), `bridge.inputMaxChars`·`bridge.answerMaxChars`·`bridge.mode`(브리지), `privacy.customers`·`privacy.partners`·`privacy.internal_domains`(정제), `episode.docs.genericStems`·`episode.tokens.boilerplate`(시간).

---

## 14. 예외 처리

| 상황 | 처리 | 기록 |
|---|---|---|
| 팀 레지스트리 JSON 깨짐·형식 위반 | 오프라인 사본 → 캐시 → 내장 순서로 대체(§3.1) | 경고 1줄 + 화면 '레지스트리 사용 불가 — 캐시 v6 사용' |
| 레지스트리 항목 단위 위반(클라이언트) | 그 항목만 무시(§2.4 표) | 경고 코드별 건수 |
| 레지스트리가 비었음 | 초기 상태(§3.5) | 화면 안내 |
| 예약 ID(`P-99xx`)를 팀·개인 파일이 씀 | 그 항목 무시 | `reserved_id` |
| `merged_into` 순환·없는 대상 | `merged_into` 무시 | `merge_cycle`·`merge_target_missing` |
| 라벨·수정·제안이 가리키는 과제가 레지스트리에서 사라짐 | 퇴역처럼 다룬다: 라벨 유지 + `retired_project` 표식, 재질의(`regv`), H06 | 경고 |
| 과제 토큰 `[과제:X]` 의 X 가 유효 레지스트리에 없음(예: 옛 개인 과제를 지움) | 그 토큰은 점수 0 | `hier.unknown_token_id` 건수 |
| 경계 메시지에 과제 토큰이 둘 이상 | 결정 토큰으로 쓰지 않고 점수 합산으로 | — |
| `pc_file.dir_keys` 열 없음 | 폴더 규칙 생략(루트·이름은 그대로) | `hier.no_dir_keys` 건수 |
| 사람 사전 없음·who_key 미등록 | 상대 계급 없음(받은 메일 `sender_label` 만) | — |
| 카탈로그에 없는 앱 | `app_cat=""`, 프롬프트 '미상 프로그램' | — |
| 코파일럿 답 검증 실패·전송 실패 | 브리지 사다리·반분 → 끝내 실패하면 규칙 폴백(`rule_pending`), 다음 실행이 자동 재질의 | 브리지 결과 봉투 |
| 답의 과제가 병합된 과제 | `resolve()` 로 대표 ID | — |
| `NEW` 이름이 팀 라벨 검사 실패 | 제안 이름 = '<영역 이름> 새 과제 #n' | `hier.proposal_label_rejected` |
| 답 `title` 이 정제 검사 실패 | 규칙 이름 사용 | `hier.title_rejected` |
| 군집 합치기가 크기 상한·확정 과제 충돌 | 합치지 않음(따로 이름) | 건수 |
| 수정 기록의 대상이 사라짐 | 기록 유지, '미적용 수정' 목록 | 원장 표식 |
| 학습 키 규칙이 서로 다른 과제를 가리킴 | 늦은 것 우선, 앞의 것 `superseded` | — |
| 개인 파일(`proposals.json` 등) 깨짐 | 쓰기마다 남긴 직전 판 `.bak` 로 복구, 둘 다 깨지면 빈 파일 + 경고. 제안 순번은 팀 대기열·보낸 묶음의 최대 `pr_` 번호 + 1 부터(ID 재사용 금지) | 경고 |
| H-I3 롤업 보존 실패 | **분석 중단**(결과·팀 묶음 생성 안 함 — 코드 결함) | 오류 리포트(달·차이 분) |
| H-I5 분류 전후 시간 값 변화 | **분석 중단** | 오류 리포트 |
| `role_id` 24비트 충돌(서버 경고) | 클라이언트는 할 일 없음(서버가 따로 셈 — 팀 명세 R-8) | — |
| 미등록 설정 키 / 형 불일치 | 오류 중단 / 기본값 + 경고 | `run_meta.warnings` |

---

## 15. 시험 시나리오와 관문

### 15.1 골든 시나리오(참조 구현 `scenarios.py` → `golden.json`, 46건)

합성 레지스트리: `P-0007` 과제A(DEV, 별칭 '과제A 모듈', 코드네임 'PROJ-A', 키워드 브라켓·광학모듈, 고객 C01, 메일 도메인 custa.example, 폴더 '과제A_설계', 기본 분야 OPT) · `P-0008` 과제B(MP, 코드네임 PROJ-B, 키워드 양산라인·수율개선, 고객 C01, never '과제B 후속') · `P-0011` 과제C(AX) · `P-0012` 과제D(EXT) · `P-0013` 과제E(퇴역, `merged_into` P-0007, 코드네임 PROJ-E).

| ID | 입력 | 기대 |
|---|---|---|
| H01 | 'RE: [과제:P-0007] 브라켓 체결부 검토 부탁드립니다' | 꼬리표 `P-0007`, 8.0 |
| H02 | 'PROJ-A 일정 공유'(정제 전 평문 코드네임) | `P-0007`, 4.0 |
| H03 | '브라켓_v3.sldprt'(키워드 1개) | 꼬리표 없음, 2.0 |
| H04 | '광학모듈 브라켓 검토.pptx'(키워드 2개) | `P-0007`, 4.0 |
| H05 | '[과제:P-0008] 과제B 후속 기획 회의' | `P-0008` = −∞(never) |
| H06 | '[고객사:C01] 일정 문의' | P-0007 0.75 · P-0008 0.75(고객 공유) |
| H07 | '브라켓 해석.xlsx' + 폴더 '과제A_설계' | `P-0007`, 5.0 |
| H08a~e | 영역 키워드 | 보안교육 → COM 4.0 · 산학 세미나 → EXT 4.0 · 실험실 자동화 → AX 1.5 · 예산 정산 → COM 4.0 · LLM 분류 → AX 1.5 |
| H09 | 'PROJ-E 도면 송부'(퇴역·병합 과제 코드네임) | `P-0007`, 4.0 |
| H10 | 의뢰·보고에 과제 토큰 | `P-0007`, token, h |
| H11 | 키워드 문서 2 + 창 | `P-0007` 0.81, rule, h |
| H12 | 공유 고객만 | 미확정, 후보 0.09·0.09 |
| H13 | 예산 정산 | `P-9904`, domain_rule |
| H14 | '메모.txt' | 미확정, 후보 없음 |
| H15 | 두 과제 키워드 혼합 | 미확정, 후보 0.5·0.5·`P-9902` 0.36 |
| H16 | CAD 300분 | MECH(h)·DESIGN(m)·DEV(h) |
| H17 | 해석 200분 + '방열 열해석' | THERM(m)·ANALYSIS(m)·DEV(h) |
| H18 | 조율형·사내 | MEET · PL(m) |
| H19 | 조율형·고객사 | MEET · PM(m) |
| H20 | '입고검사 현장 방문' + PC 밖 240/300분 | TEST · FIELD(m) |
| H21 | '산학 세미나 발표 요청', EXT | DOC · EDU(m) |
| H22 | '8월 예산 정산 요청', 사무 앱 | DOC · OFFICE(m) |
| H23 | 'LLM 기반 … 자동 분류' | DEV 과제 ax_link=true, AX 과제 false |
| H24 | 주간보고 8주·같은 문서군 자체 업무 2·범용 첨부 의뢰 2·확정 과제 다른 같은 문서군 2 | 군집 `[w0~w7]`·`[s1,s2]`·`[r1]`·`[r2]`·`[x1]`·`[x2]` |
| H25~H28 | 규칙 이름 | '공차해석'(doc) · '브라켓 체결부'(subject) · '주간보고'(doc) · '광학·해석·분석 단위업무'(generic) |
| H29 | 프롬프트 예산(과제 0·10·40·80·150) | §6.4 표(묶음 30·28·22·15·축약 29) |
| H30a~e | 답 검증 | unknown_code:project · missing:new · bad_pattern:title · forbidden_field · 통과 |
| H31~H33 | 우선순위 | 규칙 확정 > AI h(+H02) · AI h > 규칙 유력(+H02) · AI m < 규칙 유력 |
| H34a~g | 이름 점수 | §9.3 끝 예 |
| H35 | 무리 제약 | `[열 해석, 열해석]`, `[열해석(양산)]` |
| H36 | 학습 | 키 규칙 active, 토큰 candidate → 두 번째 수정에 active |
| H37 | 학습 키 규칙만 있는 새 메시지 | 꼬리표 `P-0007` 5.0 |
| H38 | 정밀도 2/6 | retired |
| H39 | 레지스트리 검증 | reserved_id · desc_has_codename · alias_collision · bad_domain · merge_cycle×2 |
| H40 | 옛 어휘 문자열 | '회로' → ELEC, '광학검사' → X_E42E7B |
| H41 | `role_id("P-0007","OPT","ANALYSIS")` | `r_8412d7` |
| H42 | `regv` | NONE → 재질의 · P-0007 → 재사용 · P-9904 → 재질의 · 목록 불변 → 재사용 |
| H43 | `kw_hit` 경계 | 정렬⊄재정렬 · 해석⊂열해석(head) · 과제A⊂과제a의 · ai⊄email · lidar-x 두 조각 |
| H44 | 키워드 일관 | `P-0007` 0.88, rule, h |
| H45 | '입고검사 결과 정리' | QA · DOC(PURCHASE 아님) |
| H46 | 부트스트랩 표본 맞추기 | 빈 레지스트리 80줄 · 과제 10개 75줄(줄 80자) |

### 15.2 통합 시나리오(구현 단계에서 `tests/hier/test_*.py`, `unittest`)

| ID | 상황 | 기대 |
|---|---|---|
| T-H01 | 팀 레지스트리 v7 캐시 + 서버 불가 + 오프라인 사본 v8 | v8 채택, 상태 'offline' |
| T-H02 | 오프라인 사본 v9 가 `bad_domains` | 버리고 캐시 v7, 경고 |
| T-H03 | 개인 과제 '광센서 선행' + 팀이 별칭 '광센서 선행'으로 P-0021 등록 | 다음 실행에 `maps_to=P-0021`, 라벨·제안 `mapped`, 알림 |
| T-H04 | 팀 `adopted` 에 내 person_key·pr_3 | 제안 pr_3 → mapped, 단위업무 라벨 P-0021 |
| T-H05 | 빈 레지스트리, 코드네임 검토 전 | 코파일럿 단계 안 열림, 규칙 라벨만, 안내 1줄 |
| T-H06 | 검토에서 'PROJ-X' 를 [과제 이름] | L-0001 생성, 이후 프롬프트에 'PROJ-X' 0회·`[과제:L-0001]` 만(카나리아) |
| T-H07 | 과제 추가 후 재분석 | 이전 NONE·P-99xx 답 군집만 `regv` 로 재질의, 나머지 0회 |
| T-H08 | 자체 업무에 수정 → 나중에 백필된 의뢰 메일로 unit_id 변경 | 수정이 증거 키로 따라가 같은 라벨 |
| T-H09 | 같은 스레드에 수정 1회 | 다음 실행에 새 메시지 꼬리표 P-0007(학습 키 규칙), 시간 코어 연결 제약에 반영 |
| T-H10 | 학습 토큰 규칙이 5번 중 3번 틀림 | retired, 화면에 사유 |
| T-H11 | 팀 묶음 빌드 | `roles[].field/function` 이 어휘 코드, `role_id` 재계산 일치, 개인 `L_` 코드는 `maps_to` 로 바뀜 |
| T-H12 | 개인 과제 L-0001 단위업무 | 팀 묶음에서 `project_id=null`, `proposal_id=pr_…`, `proposals[]` 에 label |
| T-H13 | 미리보기에서 제안 [빼기] | 그 역할 `UNC`, alloc·effort 불변 |
| T-H14 | B_MEET 회의 시리즈가 P-0007 키워드 | 개인 보고서 보조 표시만, 과제 MM·팀 묶음 불변(I2·I3) |
| T-H15 | 같은 입력을 순서 바꿔 3번 | labels·groups·titles 바이트 동일(G-H1) |
| T-H16 | 코파일럿 꺼짐 | 규칙 라벨로 완주, '코파일럿 미사용' 배지 |
| T-H17 | 웹 노출 환경 | task_label 프롬프트에 `domains` 값 `-` |
| T-H18 | 부트스트랩 1·2회차 스텁 응답 | 제안 생성, AI 단독 통합 쌍은 H04 질문(자동 병합 0) |
| T-H19 | 제안 '방열 모듈'·'방열모듈' 연달아 | 같은 제안(ukey 동일 자동) |
| T-H20 | 레지스트리 과제 영역 DEV → MP 변경 | 라벨 영역·롤업이 따라감, 코파일럿 재질의 0 |
| T-H21 | 30명 × 월 300 군집 팀 서버 '제안 묶음 후보' | 자동·질문 쌍 목록, 서버 자동 병합 0 |

### 15.3 관문(lint·시험)

| ID | 관문 | 방법 |
|---|---|---|
| G-H1 | 결정성 | 입력 순서 셔플 3회 → `labels.json`·`groups.json` 정규 바이트 동일 |
| G-H2 | 코드네임 카나리아 | 레지스트리 코드네임·별칭·`mask_name` 이름에 카나리아 문자열 → 조립된 모든 프롬프트(task_label·bootstrap·consolidate)에서 0회 |
| G-H3 | 계층 불변식 H-I1~H-I4 | 골든·통합 시나리오 전부 + 퍼즈(무작위 라벨 5,000건) |
| G-H4 | 시간 불변(H-I5) | 분류 전후 `team_tables.json` 바이트 동일 |
| G-H5 | 레지스트리 스키마 | §2.4 제약마다 위반 사례 1개 → 기대 오류 코드 |
| G-H6 | 예약 ID | 팀·개인 파일의 `P-99xx` 거부 |
| G-H7 | AI 되먹임 금지(H-I6) | `lm27/hier/learn.py`·`rules.py` 가 `ai_out`·`proposals` 를 읽지 않음(임포트·경로 문자열 검사) |
| G-H8 | 골든 | 46건 일치 |
| G-H9 | 프롬프트 크기 | 과제 0~500 개 레지스트리에서 모든 묶음 ≤ `inputMaxChars` |
| G-H10 | 병합 제약 | 무작위 이름 집합 2,000회: 무리 안에 −∞ 쌍 0, 크기 ≤ cap |
| G-H11 | 영역·어휘 단일원 | `DOMAIN_META`·`BUILTIN_VOCAB` 밖에서 영역 이름·색 문자열 하드코딩 0(LM24 `check_l1` 계승) |
| G-H12 | 팀 묶음 라벨 | `validate_team_bundle` 통과, `roles[].field/function` ∈ 레지스트리 어휘 코드 |
| G-H13 | 저장소 기본값 | 패키지의 레지스트리·개인 파일 기본값에 과제·별칭·코드네임·키워드·규칙·카탈로그 0개 |

---

## 16. 형제 명세 정합 요청

| ID | 대상 | 요청 | 이유 |
|---|---|---|---|
| X1 | `TEAM_AND_BUNDLE.md` §2.3.1·§3.10·§4.6, `PRIVACY.md` §14.5 | 어휘 값의 정본을 **코드**로: 레지스트리 `vocab` 를 객체 목록(`{code, name, …}`)으로, 팀 묶음 예시의 `roles[].field "회로"` → `"ELEC"`, `function "설계"` → `"DESIGN"`, `units[].activity_type "개발"` → `"DEV"`, `person.function` → 코드, `/api/team/detail` 예시 동일. R-8 `role_id` 의 field·function 자리 = 코드. `ENUM:fields` 등 = 레지스트리 어휘 **코드** 집합. 서버 화면은 이름으로 풀어 보인다 | 이름을 고치면 `role_id`·집계 키가 바뀌는 문제 제거. 브리지 프롬프트도 코드로 고른다 |
| X2 | `TEAM_AND_BUNDLE.md` §3.10 | `PUT /api/registry` 검증 = `lm27.hier.registry_schema.validate_registry(side="server")`, 별칭 중복 = `lm27.hier.names.ukey`. §2.3 의 선택 필드를 받아들인다. `P-99xx` 거부(`reserved_id`). 취합의 유효 레지스트리에 예약 과제 5개를 주입해 팀 묶음의 `P-99xx` 가 `unknown_project` 경고를 내지 않게 | 의미 검증의 단일원 |
| X3 | `PRIVACY.md` §10.2·§14.3, `COLLECT_PC.md` §5.5 | `pc_file.dir_keys`(≤ 3, `s`+16hex, `keyed(kr, "path", "seg:"+seg_norm(seg), 16)`) 열 추가. 팀 금지 값 `forbidden:local_key` 정규식 첫 글자 집합에 `s` 추가. 시간 명세가 요청한 `pc_file.folder`(상위 폴더 해시 2단계)는 `dir_keys[:2]` 로 통일 | 폴더 힌트(§4.2) |
| X4 | `PRIVACY.md` §8.1·§13 | 과제 코드네임 사전 = **유효 레지스트리**(팀 ⊕ 개인 로컬 `L-…`)의 `codenames`(+`mask_name` 이름). 토큰 `[과제:L-0001]` 허용(ID 형식은 이미 맞음). 전송 직전 게이트는 **그 순간**의 유효 레지스트리로 문맥을 만든다 | 초기 코드네임 검토(§8.1)가 효과를 내려면 |
| X5 | `COPILOT_BRIDGE.md` §8.3·§2.5·§16 Q10·Q12 | `task_label/1.1`(§6.8 표): 예약 과제 코드, `dom` 필드, `hint` 열·send_field, `domains` 는 계급만, `regv` 를 `content_key_fields` 에, 항목 키 `grp:`, 과제 코드 집합에 받아들인 개인 과제 포함, 커밋 항목 메타에 `reg_set`(과제 목록 해시). Q10 의 `copilot_desc` 는 §2.3.2 로, Q12 의 task_label 확정 문턱은 §4.7(`hier.unit.*`)로 확정 | 이 문서가 L4 내용을 소유 |
| X6 | `COPILOT_BRIDGE.md` §6.6·§8.8 | `kind="single"` 의 검증 = 행 봉투(조회 단계와 같은 `n == len(items)` 규칙, 단 `no_web_rule` 포함). §8.8 예약 → `taxonomy_bootstrap/1.0`·`taxonomy_consolidate/1.0`(§8.2·§8.3) | 부트스트랩 응답은 입력 항목이 아니라 출력 행 |
| X7 | `WORKTIME_METHOD.md` §5.4 | `B_MEET` '롤업 단계에서 레지스트리 키워드로 과제에 직접 귀속할 수 있다' → '개인 보고서 보조 표시만(MM 이동 없음)' | 개인 = 팀(I2·I3) 보존 |
| X8 | `WORKTIME_METHOD.md` 부록 A `normalize(…, registry)`·§4.5 | `registry` 인자 = `HierTags{msg, fam, shared_fams}`. '팀 레지스트리 공용 문서 표식' = 레지스트리 `projects[].shared_docs` 를 `fam()` 정규화한 키 | 시간 코어가 레지스트리 형식을 몰라도 되게 |
| X9 | `TEAM_AND_BUNDLE.md` §4.4·§4.9 | 예약 과제는 '<영역> — 과제 미지정' 행으로 표시. 개인 과제는 제안(`proposal_id`)으로만 온다 | 표시 일관성 |
| X10 | `COLLECT_PC.md` §6 | 프로그램 카탈로그 범주 `cat` 값 목록(CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통)을 분석 모듈이 읽는 한 곳(`lm27/catalog.py`)으로, 값이 바뀌면 이 문서의 `CAT_FIELD`·`CAT_FUNC`·`TECH_CATS` 와 같은 커밋 | 분야·기능 규칙의 앱 범주 |

---

## 17. 한계 · 사용자 확인이 필요한 결정 · 미결

### 17.1 한계

1. **규칙 분류의 품질은 레지스트리 품질에 달려 있다.** 코드네임·키워드·고객 연결이 비어 있으면 과제 수준은 코파일럿·사람에 기대고, 영역 수준(공통·외부지원)만 규칙으로 잡힌다.
2. **코드네임 후보 추출은 휴리스틱이다.** 3개 미만 군집·2주 미만에만 나온 코드네임은 후보에 안 오르고, 게이트도 레지스트리에 없는 이름은 가리지 못한다. [건너뛰기]는 그 위험을 받아들이는 선택이다.
3. **한국어 형태 분석이 없다.** 앞 경계·짧은 접두 꼬리 규칙만 쓴다. 약칭·띄어쓰기 변형 일부는 놓치고(별칭 등록으로 보완), 짧은 한글 키워드는 오탐 여지가 있다(2자 키워드는 `generic_keyword` 경고 대상으로 검토).
4. **분야·기능·유형 문턱은 미보정(★)이다.** 사람 수정 비율로 맞춰야 한다(미결 Q7).
5. **명명 군집은 키(문서군·첨부·대화·`follow_of`)가 있어야 묶인다.** 같은 일을 다른 이름의 문서로 하면 다른 군집이 되고, 이름은 §9 병합·질문으로만 맞춰진다.
6. **코파일럿 답의 일관성**은 '앞서 쓴 이름'·제목 캐시로 줄이지만 새 군집은 다르게 이름 붙을 수 있다.
7. **팀 묶음 제목**은 팀 라벨 검사를 통과한 것만 간다. 실패하면 generic 라벨이다.
8. **참여 방식·AX 연계**는 낱말·구조 휴리스틱이다(보고서에 '추정' 표시).
9. **여러 팀에 걸친 과제**(다른 팀 레지스트리의 과제)는 v1 범위 밖이다 — 내 팀 레지스트리에 같은 과제를 등록해야 한다.

### 17.2 사용자 확인이 필요한 결정

| # | 결정 | 이 문서의 기본 | 선택지 | 영향 |
|---|---|---|---|---|
| D-H1 | 명칭 | 업무 영역 / 과제 / 역할 업무 / 단위 업무 / 업무 유형 | 다른 이름 | 화면·보고서 용어 |
| D-H2 | 업무 유형 어휘 | 7종(개발·사무·현장·PM·PL·지원·교육·학습) | 요구서 예시 5종 + 지원 | 유형 분포 |
| D-H3 | 분야·기능 기본 목록 | §1.4 표(분야 10·기능 14) | 팀이 확정·추가 | 역할 업무 축 |
| D-H4 | 과제는 모르고 영역만 아는 업무 | 예약 '영역 일반' 과제 `P-9901~9905` | 미분류(UNC)로 둠 | 공통 업무·외부지원 MM 이 미분류로 새는지 |
| D-H5 | AX 연계 계상 | 원래 영역에 MM, AX 연계는 표식(이중 계상 없음) | AX 영역으로 나눠 계상 | 영역별 MM |
| D-H6 | 확정 전 제안 과제의 계상 | 제안 과제로 계상('제안' 배지, 팀에도 제안으로) | 미분류로 계상 | 미분류 비중 대 제안 품질 |
| D-H7 | 레지스트리 없이 코파일럿 쓰기 | 코드네임 검토 뒤에만(건너뛰기 가능) | 검토 강제 / 검토 없음 | 코드네임 노출 위험 대 초기 분류 속도 |
| D-H8 | 레지스트리 관리 주체 | 팀장 단독 편집 + 팀원은 제안 | 팀원 편집 허용 | 이름 일관성 |
| D-H9 | 코드네임·과제명을 팀원 PC 에 배포 | 레지스트리 캐시로 배포(가명화에 필요) | 코드네임은 배포하지 않음(가명화 약화) | 보안 대 정제 품질 |
| D-H10 | 단위업무 제목 팀 업로드 | 기본 포함(결정 메모 §10.4), 항목별 가림·generic 모드 | 제외 모드 기본 | 간트 드릴다운 가독성 |

### 17.3 미결

| # | 질문 | 확인 방법 | 막히면 |
|---|---|---|---|
| Q1 | `dir_keys` 수집(OneDrive·SharePoint·네트워크 드라이브 경로의 세그먼트 규칙) | 수집 명세 실측 | 폴더 규칙 없이 루트 대응·이름만 |
| Q2 | `task_label` 의 실제 품질·NONE 비율, fast 대 deep 모델 | 같은 고정 입력 비교(브리지 Q8) | 모델 등급 설정만 바꿈 |
| Q3 | 학습 토큰 규칙을 팀 공용 규칙 후보로 올리는 경로 | 팀 묶음 `proposals[].kind="keyword"` MINOR 검토 | v1 은 복사 문구만 |
| Q4 | `units[].stance`·`label_level` 팀 묶음 추가 | 팀 보고서 요구 확인 | 개인 보고서만 |
| Q5 | `step_types` 어휘 확정 | 워크플로우 명세 | 브리지 §8.4 예시 코드 유지 |
| Q6 | `common_words.txt`(업무 일반어 약 300개) 작성·검토 | 합성 말뭉치로 후보 오탐률 측정 | 후보 상위 30개를 사람이 거름 |
| Q7 | 분야·기능·유형 문턱 보정 | 시간 명세 `tools/calibrate.py` 확장(사람 수정 = 정답) | 기본값 유지 + 질문 H05 |
| Q8 | 팀 서버 `/admin` 레지스트리 편집·제안 묶음 화면 | 화면 명세 | 레지스트리 JSON 직접 편집(검증 통과 시) |
| Q9 | 레지스트리 과제 500개 초과 팀 | 실측 | 축약 머리말로 동작(§6.3), 상한 상향은 MINOR |

---

## 부록 A. 한 달 한 사람의 전 과정 예시(합성)

**입력**(10월, 홍길동, 레지스트리 v7 — §15.1 합성 레지스트리):

| 단위업무 | 시간 코어가 만든 것 | 증거(정제문) |
|---|---|---|
| U1 `u_3e9a01c2d4` | S1 → E1, 등급 A, 투입 240분(해석 앱 180·사무 60) | 의뢰 메일 '[과제:P-0007] 공차 해석 요청', 첨부 연결 '공차해석_v3.xlsx', 보고 메일 'RE: [과제:P-0007] 공차 해석 결과 송부' |
| U2 `u_51c0e2a7f8` | SELF, 등급 E, 투입 660분(해석 600·사무 60) | 문서 '열해석_모델.cas'·'열해석_결과정리.xlsx' |
| U3 `u_0b1c2d3e4f` | S1 → E1, 등급 A, 투입 110분(사무) | '8월 예산 정산 요청', '정산내역.xlsx' |

**1) 증거 꼬리표(§4.5)**: U1 의 두 메일 → `P-0007`(토큰 6.0). U2·U3 문서 → 없음. 시간 코어는 U1 의 문서군 연결에 'P-0007 같음 +0.7' 을 쓴다.

**2) 규칙 라벨(§4.7·§4.8·§10)**:

| | 과제 | 분야 | 기능 | 유형 | 이름 |
|---|---|---|---|---|---|
| U1 | `P-0007` token h | OPT l(과제 기본 분야 1.5 > '공차' MECH 1.0, 차 0.5) | ANALYSIS m(해석 앱 3.0×180/240 = 2.25 + '해석' 1.0 = 3.25) | DEV h(공학 앱 비중 0.75) | '공차해석'(doc) |
| U2 | 없음(후보 없음) | THERM l('열해석' 1.0) | ANALYSIS h(해석 앱 2.73 + '열해석' ⊃ '해석' 1.0 = 3.73) | DEV h(0.91) | '열해석 모델'(doc) |
| U3 | `P-9904` domain_rule m('예산'·'정산' COM 4.0) | ETC l(재료 없음) | DOC l(사무 비중 1.0 → DOC 1.5 > '정산' ADMIN 1.0) | OFFICE m | '8월 예산 정산'(subject) |

**3) 코파일럿에 보내는 군집(§6.1)**: U1 — 과제 확정·이름 명확·기능 m → 보내지 않음. U2 — 과제 미확정(a) → 보냄. U3 — 예약 과제지만 레지스트리에 COM 과제가 없어 (a)는 아니고, 분야·기능이 둘 다 l 이고 투입 110분 ≥ 1h 라 (c)로 보냄. 항목 줄:

```text
1 | 문서 4·앱 1 | - | 열해석_모델.cas, 열해석_결과정리.xlsx | 해석 프로그램 | - | - | THERM/ANALYSIS/DEV
2 | 메일수신 1·메일발신 1·문서 1 | 8월 예산 정산 요청 | 정산내역.xlsx | 엑셀 | 사내 | P-9904 1.00 | ETC/DOC/OFFICE
```

**4) 답**:

```json
{"rid": "R7F3QK", "n": 2, "items": [
  {"id": 1, "project": "NEW", "field": "THERM", "func": "ANALYSIS", "wtype": "DEV",
   "title": "방열 모듈 열해석", "new": "방열 모듈", "dom": "DEV", "conf": "m"},
  {"id": 2, "project": "P-9904", "field": "ETC", "func": "ADMIN", "wtype": "OFFICE",
   "title": "8월 예산 정산", "new": "", "dom": "", "conf": "h"}]}
```

**5) 적용(§6.5·§7.4)**: U2 — 군집 투입 660분 ≥ 60분 → 제안 `pr_3` '방열 모듈'(DEV, pending) 생성, U2 라벨 과제 자리 = `pr_3`, 분야 THERM(규칙 l 을 AI m 이 이김 — 같은 값), 이름 '방열 모듈 열해석'(AI m > 규칙 doc), 확인 질문 H03(투입 11h ≥ 4h). U3 — 과제는 규칙 `domain_rule`(75) 이 AI h(70)와 같은 값으로 유지, 기능은 규칙 l 을 AI h 가 이겨 ADMIN, 이름은 AI h.

**6) 라벨 결과**:

| | 과제 자리 | 영역 | role_id | 유형 | level |
|---|---|---|---|---|---|
| U1 | `P-0007` | DEV | `r_8412d7`(P-0007·OPT·ANALYSIS) | DEV | high |
| U2 | `pr_3`(제안) | DEV | `r_f8befd`(pr_3·THERM·ANALYSIS) | DEV | low |
| U3 | `P-9904` | COM | `r_95052c`(P-9904·ETC·ADMIN) | OFFICE | medium |

**7) 팀 묶음 조각(§12.4)**: `projects` = `[{P-0007, DEV}, {P-9904, COM}]`, `proposals` = `[{pr_3, project, '방열 모듈', DEV}]`, `roles` = 3개(field·function 은 코드), `units[].title` = '공차해석'·'방열 모듈 열해석'·'8월 예산 정산'.

**8) 롤업(시간 명세 §6.1)**: 10월 분모 160h. DEV = (240 + 660)/60 = 15.0h → 0.094MM(U2 는 '제안 과제' 표시), COM = 110/60 = 1.83h → 0.011MM. 영역 합 + 근무 중 미분류 = 개인 MM(H-I3). 팀 서버도 같은 정수 분 표와 같은 라벨 키로 같은 값을 얻는다.

**9) 사용자가 H03 에 [내 과제로 받기]** → `L-0001` '방열 모듈'(DEV) 생성. 다음 실행부터 프롬프트 과제 목록에 `L-0001 · DEV · 방열 모듈` 이 실리고, U2 라벨 출처는 `user`(받아들임)로 `confirmed`. 팀장이 나중에 `P-0021` 로 등록하며 `adopted:[{person_key, pr_3}]` 를 남기면 다음 레지스트리 수신 때 `L-0001.maps_to = P-0021`, U2 라벨이 `P-0021` 로 바뀐다(사용자 조작 없음).

---

## 부록 B. LM20·LM24 에서 가져온 것과 버린 것

| 항목 | LM27 처리 | 근거 |
|---|---|---|
| L1_META 단일원 + snap(모호하면 빈값) | **계승** → `DOMAIN_META`·`snap_domain`(§1.2) | hierarchy-reports keep |
| LM20 taxonomy '계층 규율' 프롬프트 + consolidate | **계승** → 부트스트랩 1·2회차, 결과는 제안만(§8) | 사용자 평가 '나름 잘했다' |
| 괄호 꼬리·숫자 토큰·never 를 −∞, 무리 안 제약 클러스터링, 3구간 | **계승** → §9 | LM24 `pair_score`·`cluster2` |
| `ukey2/ukey3/team_report.ukey` 세 벌 | **통일** → `names.ukey` 하나(§9.2) | |
| 코파일럿에 이름 목록만·사람·MM 미전송, 실재 이름으로 스냅, `<…>` 자리표시자 예시 | **계승** → B1·B14·§6.5 | |
| '활동 9종' | **확장 계승** → 기능 어휘(§1.4) | |
| discovered 과제를 다음 실행 힌트로 순환 | **폐기** → 제안 큐(사람 확정 전 힌트 금지, H-I6) | 표기 분할 영구화 |
| 개인 2 + 팀 5 이름 캐시 | **폐기** → ID 레지스트리 + 개인 로컬 + 학습 규칙 | 순환·방향 뒤집힘(F4) |
| '지원·교육 → 공통' 동의어 | **폐기** → EXT 우선 영역 규칙(§4.4) | 외부 업무지원 충돌 |
| 신호 가중치 비중 MM 배분 | **폐기**(시간 명세 귀속으로 대체) — 분류는 MM 을 계산하지 않는다 | |
| 행 수(80) 청크 | **폐기** → 글자 예산 패킹(브리지 L3, §6.4) | 실측 실패 |
| 프롬프트에 박힌 팀·사내 문구 | **폐기** → 레지스트리 `copilot_desc` 만(§2.3.2) | |
| agentic_tasks.json `{axes, tasks}` | **계승·확장** → 레지스트리 `agents[]`(§2.3.6), `desc` 는 코파일럿 미전송 | |

## 부록 C. 참조 구현 파일

| 파일(`scratchpad\lm26_survey\design\hierarchy_lm27\`) | 내용 |
|---|---|
| `hier_ref.py` | names·토큰·`kw_hit`·영역 메타·레지스트리·검증·과제 점수·영역 점수·꼬리표·단위업무 판정·분야/기능·유형·AX·`role_id`·명명 군집·규칙 이름·task_label 조립·패킹·부트스트랩 조립·답 검증·우선순위·`pair_score`·`cluster`·학습·`regv` |
| `scenarios.py` → `golden.json`, `scenarios_out.txt` | §15.1 의 46건 |
| `make_examples.py` → `spec_prompt_task_label.txt`·`spec_prompt_bootstrap.txt` | §6.3·§8.2 의 프롬프트 실물 |

참조 구현의 축약: 앱 범주 대신 `app_class` 이름(cad·sim·ide)으로 같은 대응을 시험했고, §9.3 의 12번(시기 비겹침)·§4.3 의 R12(과제 기간)·§8.1 코드네임 후보·§12.4 팀 묶음 조각·국소 탐색(§9.5)은 의사코드로만 정의했다(구현 단계 시험 T-H 계열이 맡는다). 폴더 키는 시뮬레이터에서 무키 해시로 대신했다.

