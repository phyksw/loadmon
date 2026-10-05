# LM27 화면·보고서 명세 (REPORTS.md)

| 항목 | 값 |
|---|---|
| 판 | v1.0 (2026-10-05) — 설계 확정본, 구현 전 |
| 제품명 | **LoadMonitor27(LM27)**. 초기 설계 자료와 작업 폴더 이름의 'LM26' 은 잘못 붙은 이름이다(사용자 지시: "LM27로 해달라는걸 LM26으로 했네요"). `D:\배포\LM26` 은 다른 AI 도구가 만든 별개 프로젝트(127.0.0.1:8765~8767)이며 이 문서와 무관하다(읽기만). 이 문서의 모듈·경로·설정 키·포트는 모두 LM27 기준이다. 참조 시제품이 있는 `scratchpad\lm26_survey\` 는 작업 당시 임시 폴더 이름일 뿐이다 |
| 대상 코드 | `lm27/report/**`(보고서 분석층·보고서 모델·내보내기), `lm27/ui/**`(로컬 앱 서버), `web/common/**`·`web/app/**`(화면·차트 렌더러 한 벌), `web/team/**`·`lm27/team/report.py`(팀 대시보드·팀 보고서 렌더 — 데이터 산식은 TEAM_AND_BUNDLE 소관), `tests/report/**`·`tests/web/**` |
| 소유 범위 | ① 로컬 앱 화면 6개(홈·수집·분석·개인 보고서·팀·설정)의 구성·동작·API ② 개인 보고서 ③ 팀 보고서(대시보드·자기완결 HTML·공유판)의 화면 구성과 해석 문장 ④ **보고서 분석층**: 결정적 과정 마이닝(단계 유형 어휘·순서·소요·전이·대기·병목), 리뷰 사실·초과 원인, 같이 일한 동료, 온톨로지 그래프·연관도, agentic 규칙 매칭·니즈 후보, 서브에이전트 5기준 검토, 측정 품질 등급 ⑤ 디자인 시스템(LM20 언어) ⑥ 산출 파일(HTML·CSV·JSON)과 화면·절별 데이터 계약 |
| 소유하지 않는 것 | 근무 봉투·귀속·MM·등급·확인 큐 산식(`WORKTIME_METHOD.md` — 이 문서는 그 정의를 **그대로** 읽어 보인다), 업무 영역·과제·역할·유형 **분류**와 영역 메타·어휘(`HIERARCHY.md`), 정제 규칙·키(`PRIVACY.md`), 번들·팀 묶음 필드·팀 서버·팀 취합 산식(`TEAM_AND_BUNDLE.md`), 코파일럿 전송·단계 프롬프트(`COPILOT_BRIDGE.md`), 수집기·탐침·커버리지 원장(`COLLECTION.md`·`COLLECT_*.md`) |
| 상위 결정 | 오케스트레이터 결정 메모 §1(운영 원칙)·§4(명칭)·§5(시간 원칙)·§8(보고서·디자인)·§9(품질)·§10.2(간트 그리기)·§10.4(팀 묶음 제목·업로드)·§10.5(온톨로지·서브에이전트·agentic 카탈로그) |
| 형제 명세 계약 | `WORKTIME_METHOD.md` v1.0 §1(용어)·§4.10(등급)·§4.11(팀 코드 대응·간트 띠)·§5.4~5.6(버킷·병행도·정수 분 표)·§6(MM·초과·로드)·§7(신뢰·확인 큐·원장·결과 파일), `TEAM_AND_BUNDLE.md` v1 §1.5(pc.json)·§1.11~1.12(이동·도착)·§2(팀 묶음)·§3.2·§3.4·§3.12(서버 설정·포트 진단·정적 제공)·§4(취합·간트·team_data)·§7.1(클라이언트 설정), `COPILOT_BRIDGE.md` v1.1 §2.5(ai_in/ai_out)·§8.4~8.7(워크플로우·리뷰·agentic·서브에이전트 단계)·§10.5(수동 붙여넣기 화면)·§13(문구), `PRIVACY.md` v1.1 §9.6(로컬 사람 사전)·§14(팀 허용 목록)·§15.5(로컬 감사 화면), `COLLECTION.md` §4(탐침·사유 코드)·§5(커버리지 원장)·§6(todo)·§9(진단 리포트), `HIERARCHY.md` hier/1 §1.2(영역 메타 `DOMAIN_META`)·§1.3~1.7(과제·역할·유형·미분류)·§7(제안 큐)·§8.1(코드네임 검토)·§11(라벨·H 질문·수정·학습)·§12(산출·화면 요소) |
| 참조 시제품 | `scratchpad\lm26_survey\design\reports\proto_report.py`(과정 마이닝·서브에이전트·연관도·초과 원인·간트 줄 배치·밀도 단계·정수 반올림), 결과 `golden_report.json`, 표시 함수 교차 검사 `fmt_check.js`+`fmt_cmp.py`(파이썬 = JS, 11,530 사례 불일치 0). 이 문서의 골든 수치(§4·부록 B)는 이 시제품으로 계산했다(동봉 파이썬 3.11.9 로 실행) |
| 런타임 | 동봉 CPython 3.11 embeddable, **표준 라이브러리만**(진입점이 ROOT 를 스스로 `sys.path` 에 넣는다 — 시제품 실행에서도 `python311._pth` 때문에 같은 폴더 모듈 import 가 실패함을 다시 확인). 화면은 Edge/Chromium 계열 브라우저의 정적 HTML·CSS·JS(외부 CDN·웹 글꼴 없음). 보조 명령은 Windows PowerShell 5.1 |
| 자리표시자 | 사람 = 홍길동(본인)·김철수(동료), 과제 = 과제A~C, 고객 = 고객사A, 메일 도메인 = example.com. 실명·계정·이메일·사내 코드네임 없음 |

---

## 0. 요약 — 화면과 보고서가 무엇을 보여 주는가 (사용자용 한 페이지)

1. **LM27 은 내 PC 안에서 열리는 화면(로컬 앱)** 입니다. `LoadMonitor27.bat` 을 누르면 브라우저에 `http://127.0.0.1:19280` 이 열리고, 위쪽 가로 메뉴로 **홈 · 수집 · 분석 · 개인 보고서 · 팀 · 설정** 을 오갑니다. 이 화면은 내 PC 밖에서는 열리지 않습니다.
2. **홈**은 지금 상태를 한눈에 보여 줍니다: 최근 수집 현황(메일·일정·팀즈·PC 기록이 어느 날 비었는지), **PC × 출처 능력 표**(PC1 에서는 Outlook 앱이 되고 웹은 막혀 있다 같은 사실), 그리고 **다음 할 일**(예: "클라우드PC 에서 Outlook 웹 로그인이 필요합니다", "확인 질문 3건").
3. **개인 보고서**의 숫자는 모두 시간 산식 명세(`WORKTIME_METHOD.md`)의 정수 분 표에서 나옵니다. 그래서 팀 서버가 다시 계산한 값과 소수점까지 같습니다. 이번 달 MM·로드율·연장/야간/휴일 시간·미귀속 비율·측정 신뢰도를 카드로 보여 주고, 업무 영역 → 과제 → 역할 → 단위업무 트리를 따라 내려가며 **수준마다 워크플로우**(어떤 단계를 어떤 순서로, 얼마나 걸려, 어디서 막혔는지)를 봅니다.
4. 워크플로우의 단계와 순서·소요·대기 시간은 **프로그램이 기록에서 결정적으로 계산**합니다(같은 자료면 언제나 같은 결과). 코파일럿은 단계에 이름과 설명만 붙입니다. 코파일럿 답이 없으면 규칙 이름을 쓰고 '규칙' 표시를 답니다.
5. **주간·월간 리뷰**는 새로 시작한 일, 끝낸 일, 리드타임(의뢰~보고)과 투입(실제로 쓴 시간)을 나란히 보이고, 리드타임이 평소보다 길어진 일에는 **원인 코드**(대기·재작업·병행·작업량·착수 지연·근거 부족)를 붙입니다.
6. **같이 일한 동료**는 같은 단위업무에 함께 등장한 사람입니다. 이름은 **내 PC 화면에서만** 보이고, 팀에는 가명 키로만 갑니다. **연관 그래프**는 과제–역할–단위업무–문서–프로그램–동료의 관계를 그리고, 같은 문서·동료를 공유하는 업무를 '연관 업무'로 추천합니다.
7. **Agentic AI** 절은 팀이 정한 에이전트 목록과 내 워크플로우 단계 유형을 맞춰 적합도(상·중·하)와 근거를 보이고, 목록에 없는 새 니즈를 제안합니다. **서브에이전트 검토표**는 단계마다 반복성·입출력 정형성·도구 접근·검증 가능성·위험을 0~2점으로 계산해 적합/조건부/부적합을 판정합니다. '대체 가능 MM' 같은 추정 수치는 만들지 않고 **관련 업무의 실측 투입**만 보입니다.
8. 모든 숫자는 **근거로 내려가 볼 수 있습니다**: 월 → 날짜 → 그날의 구간(관측/추정/미귀속 무늬) → 단위업무의 시작·종료 근거와 투입 내역. 관측(실제 기록)과 추정(규칙으로 채움)은 언제나 모양(채움/빗금)과 글자로 구분합니다.
9. **팀 보고서**는 팀 서버가 팀원들의 묶음을 합쳐 만듭니다: 업무 영역별 투입, 과제 × 인원, 역할·업무 유형 분포와 해석 문장, agentic 매칭·니즈 취합, **담당자별 업무 영역/과제/역할 간트**(여러 달). 간트 막대를 누르면 그 사람의 그 업무 워크플로우가 옆 패널에 열립니다. 사람마다 측정 품질 배지가 붙고, 측정 불충분인 사람은 합계에는 넣되 비교에서는 뺍니다.
10. 보고서는 **자기완결 HTML**(인터넷 없이 열림)·**CSV**(엑셀)·**JSON** 으로 내보냅니다. 개인 보고서 HTML 의 '전체판'에는 동료 이름 같은 로컬 정보가 들어 있으므로 내 PC 밖으로 보내지 않습니다. 남에게 보여 줄 때는 이름과 근거 원문을 뺀 '가림판'을 씁니다.

---

## 1. 원칙과 불변식

| 번호 | 원칙 | 강제 수단 |
|---|---|---|
| RP1 | **숫자의 출처는 하나.** MM·시간·투입·미귀속은 시간 코어의 정수 분 표(`team_tables.json`, WORKTIME §5.6)와 월 결과(`mm_month.json`)에서만 낸다. 보고서 층은 분(정수)을 더하기만 하고 나누기는 표시 직전 한 번 한다 | 관문 G-R2(개인 = 팀 재합산 일치), 보고서 모듈의 `float` 누적 금지(lint: `lm27/report/` 에서 분 필드에 `/` 연산은 `fmt.py`·`ratio()` 안에서만) |
| RP2 | **관측과 추정을 언제나 구분해 보인다.** 귀속 분은 O(관측)·I(추정)·X(미귀속) 세 갈래(WORKTIME §7.1), 단위업무 경계는 등급 A~E·O·Z·M(§4.10). 화면은 채움/빗금/점선과 글자 꼬리표를 함께 쓴다(색만으로 구분 금지) | §8.3 표시 규칙, 시험 RPT-21 |
| RP3 | **코파일럿은 이름·설명·문장만.** 단계 순서·소요·대기·병목·점수·판정·MM 은 프로그램이 계산한다. 코파일럿 답은 출처 꼬리표(`AI`·`AI(붙여넣기)`·`규칙`)를 달고 보인다. 답이 없으면 같은 단계의 규칙 폴백을 쓴다(브리지 단계의 `fallback()` 한 벌) | §3.5, §4.10, 관문 G-R12 |
| RP4 | **근거 없는 수치를 만들지 않는다.** '대체 가능 MM'·'AX 가능 MM'·'절감 시간'을 계산하지 않는다(조사 결정). agentic·서브에이전트 절의 수치는 관련 단위업무의 **실측 투입**과 빈도뿐이다 | 시험 RPT-33(문자열 '대체 가능'·'절감' 0건) |
| RP5 | **로컬 이름은 로컬에만.** 동료 표시명·문서 이름·메일 제목(모두 정제본)은 로컬 앱과 개인 '전체판' 파일에만 나타난다. 팀 묶음·팀 보고서·개인 '가림판'에는 가명 키·번호표·정제 라벨만 | §3.6, 관문 G-R8(카나리아·사람 사전 이름 0건) |
| RP6 | **결정성.** 같은 입력(분석 결과 파일·레지스트리 판·설정)이면 같은 보고서 모델 바이트, 같은 HTML 바이트(머리말의 `built_at` 한 줄 제외). 모든 정렬에 동률 깨기 규칙을 둔다(코드 순서 → ID 사전순) | 관문 G-R1 |
| RP7 | **정직한 화면.** 빈 상태·부분 결과·상한 탈락·추정 비중·라벨 출처를 숨기지 않는다. 문구는 '무엇이 됐고 → 무엇이 남았고 → 프로그램이 스스로 무엇을 하는지' 순서. '개발자에게 보내라'·재설치 권유·남에게 수동 조작 요구 문구 금지 | §5.0.4 문구 규칙, 시험 RPT-40 |
| RP8 | **기간과 결과 선택은 명시적.** 화면이 보는 분석 결과는 `current.json` 이 가리키는 실행 또는 사용자가 이력에서 고른 실행 하나다. 'mtime 최신 파일 고르기'·조용한 기본 기간 폴백 금지. 화면 머리에 기간·기준 시각·기간 출처를 늘 표시 | §2.4.3, 시험 RPT-04 |
| RP9 | **데이터 접근은 단일 로더로만.** 화면·보고서 코드는 `lm27.paths` 와 각 명세의 단일 로더(번들 `lm27.bundle.loader`, 시간 결과 `lm27.time` 결과 읽기, 브리지 `ai_out`)만 쓴다. 경로 문자열 조립 금지 | lint G-R10(AST: `lm27/report`·`lm27/ui` 에서 `os.path.join`·`open(` 에 `data` 경로 상수 금지) |
| RP10 | **렌더러는 한 벌.** 로컬 앱·자기완결 개인 보고서·팀 대시보드·자기완결 팀 보고서가 같은 JS 차트 모듈(`web/common/lm27charts.js`)과 같은 CSS(`web/common/lm27.css`)를 쓴다. 파이썬 쪽 SVG 생성기를 따로 두지 않는다(LM24 사본 drift 교훈) | 관문 G-R3(정적 JS 문법·vnode 골든) |
| RP11 | **업로드된·수집된 문자열은 글자로만 그린다.** JS 는 `textContent`·`setAttribute` 만 쓰고 `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write`·`eval`·`new Function` 을 쓰지 않는다. 데이터 섬(`<script type="application/json">`)의 `<`·`>`·`&`·U+2028·U+2029 는 `\u003c` 등으로 바꾼다. 사람·라벨을 JS 객체 키로 쓰지 않고 정수 인덱스로 참조 | 관문 G-R4·G-R6, 악성 이름 픽스처 시험 RPT-30 |
| RP12 | **외부 자원 0.** 화면·보고서 HTML 에 `http(s)://` 자원 참조, 웹 글꼴, CDN, 원격 이미지가 없다. 아이콘은 로컬 SVG 스프라이트 | 관문 G-R5 |
| RP13 | **접근성 기본값.** 본문 16px·표 14px, 모든 차트에 제목·한 줄 요약·'표로 보기', 색 아닌 두 번째 부호(글자·모양·무늬), 키보드로 모든 조작, 텍스트 대비 4.5:1 이상 | §8.5, 관문 G-R7 |
| RP14 | **보고서는 분석을 다시 돌리지 않고 다시 만들 수 있다.** 보고서 모델은 분석 결과 파일만으로 결정적으로 다시 만든다(`lm27 report build`). 보고서 판(`report/1`)이 바뀌어도 코파일럿 재질의 없이 갱신 | §2.4 |
| RP15 | **개인 = 팀.** 팀 묶음에 실리는 워크플로우·agentic·서브에이전트·품질 값은 개인 보고서 모델과 같은 함수의 같은 결과다(팀 묶음 빌더는 보고서 모델에서 허용 목록 필드만 고른다) | §9.5, 시험 RPT-12 |
| RP16 | **미분류를 숨기지 않는다.** 분류 없는 업무는 `미분류(UNC)`, 단위업무에 묶이지 않은 근무는 '근무 중 미분류'(버킷 5종) 행으로 늘 보인다. 버킷 분을 과제에 나눠 주지 않는다(개인 = 팀 보존을 위해 WORKTIME §5.4 의 'B_MEET 과제 직접 귀속' 선택지는 보고서 숫자에 쓰지 않고 주석으로만 보인다 — §13 요청 W-3) | §6.3, 시험 RPT-13 |

---

## 2. 구조

### 2.1 계층도

```
  분석 산출(읽기 전용)                                   보고서 분석층(결정적, lm27/report/analysis/*)
 ┌──────────────────────────────────────────┐        ┌─────────────────────────────────────────────┐
 │ 시간 결과 time\*  (WORKTIME §7.5)        │──┐     │ activity.py  단위업무 활동 로그(§4.1)        │
 │ 분류 라벨 hier\*   (HIERARCHY §12)        │  ├────▶│ mining.py    과정 마이닝(§4.2~4.3)           │
 │ ai_out\*.json     (COPILOT §2.5)         │  │     │ review.py    리뷰 사실·초과 원인(§4.4)        │
 │ 레지스트리 캐시 data\team\registry.json   │  │     │ peers.py     같이 일한 동료(§4.5)            │
 │ 사람 사전 data\local_only\person_dir.json │  │     │ ontology.py  연관 그래프·추천(§4.6)          │
 │ 번들 현황 pcs\*\pc.json·manifest·원장·todo │  │     │ agentic.py   규칙 매칭·니즈 후보(§4.7)       │
 └──────────────────────────────────────────┘  │     │ subagent.py  5기준 검토(§4.8)                │
                                               │     │ quality.py   측정 품질 등급(§4.9)            │
                                               │     │ ai_items.py  코파일럿 ai_in 만들기·반영(§4.10)│
                                               │     └──────────────────────┬──────────────────────┘
                                               │                            ▼
                                               │     ┌─────────────────────────────────────────────┐
                                               └────▶│ model.py  보고서 모델 report_model.json(§9.2)│
                                                     └───────┬─────────────────┬───────────────────┘
                                         ┌───────────────────┘                 └─────────────┐
                                         ▼                                                   ▼
                     ┌────────────────────────────────────┐            ┌──────────────────────────────────┐
                     │ 로컬 앱(lm27/ui) 127.0.0.1:19280    │            │ 내보내기(lm27/report/export.py)   │
                     │ /api/* → 모델 조각·작업(job)         │            │ HTML(전체판·가림판)·CSV·JSON      │
                     └──────────────┬─────────────────────┘            └──────────────┬───────────────────┘
                                    ▼                                                 ▼
                     ┌──────────────────────────────────────────────────────────────────────────────────┐
                     │ 렌더러 한 벌: web/common/lm27charts.js(차트 = 순수 함수 → 가상 노드) · lm27ui.js(마운트·│
                     │ 탭·툴팁·서랍·표 보기) · lm27.css · icons.svg  ── 팀 대시보드·팀 보고서도 같은 파일        │
                     └──────────────────────────────────────────────────────────────────────────────────┘
  팀 묶음 빌더(TEAM §2.4)는 report_model 에서 허용 목록 필드만 골라 담는다 → 팀 서버 취합(TEAM §4) → team_data.json
  → 같은 렌더러로 팀 대시보드(/)·team_report.html·team_report_share.html
```

### 2.2 모듈 배치

모든 경로는 개발 트리 `D:\배포\loadmon27\`(배포 시 `LoadMonitor27\`) 기준.

| 파일 | 책임 |
|---|---|
| `lm27/report/__init__.py` | 공개 API 재수출: `build_report(run_id) -> Path`, `load_model(run_id) -> dict`, `export(run_id, formats, variants, out_dir) -> ExportResult` |
| `lm27/report/inputs.py` | `load_inputs(run_id) -> ReportInputs` — §2.5 표의 파일을 단일 로더로 읽어 한 객체로. 파일 없음·형식 깨짐은 `inputs.missing[]`·`warnings[]` 로(조용히 삼키지 않음) |
| `lm27/report/vocab.py` | 사유 코드 화면 문구(§5.8)·리드 초과 원인 코드(§4.4)·차트 이름 표 **단일원**. 업무 영역의 이름·색·순서는 분류 명세의 `lm27/hier/vocab.py` `DOMAIN_META`(HIERARCHY §1.2)를 접근 함수(`domain_name`·`domain_color`·`domain_order`)로만 읽고, 분야·기능·유형 이름은 유효 레지스트리 어휘(HIERARCHY §2.3.4)에서 코드로 찾는다 |
| `lm27/vocab/steps.py` | 단계 유형 어휘(§3.3) 단일원 — 시간 코어·보고서·브리지·레지스트리 기본값 공용 |
| `lm27/report/fmt.py` | 정수 반올림 표시 함수(§3.1)·영업 시간(§3.2)·ISO 주 계산. 분석층·내보내기·CSV 가 쓰는 유일한 나눗셈 자리 |
| `lm27/report/analysis/activity.py` | 단위업무 활동 로그(§4.1) |
| `lm27/report/analysis/mining.py` | 과정 마이닝 역할·단위·과제·영역 수준(§4.2·§4.3) |
| `lm27/report/analysis/review.py` | 주간·월간 리뷰 사실·리드·초과 원인(§4.4) |
| `lm27/report/analysis/peers.py` | 같이 일한 동료(§4.5) |
| `lm27/report/analysis/ontology.py` | 연관 그래프·연관도·추천(§4.6) |
| `lm27/report/analysis/agentic.py` | agentic 규칙 사전 점수·매칭 합치기·니즈 후보(§4.7) |
| `lm27/report/analysis/subagent.py` | 서브에이전트 5기준(§4.8) |
| `lm27/report/analysis/quality.py` | 측정 품질 등급(§4.9) — 팀 묶음 `quality.grade` 도 이 함수 |
| `lm27/report/analysis/ai_items.py` | 코파일럿 단계 입력 `ai_in` 쓰기(§4.10)·`ai_out` 읽어 반영·폴백 |
| `lm27/report/resolve.py` | 로컬 표시 해석(§3.6): who_key → 표시명, fam_key → 정제 문서 이름, msg_key → 정제 제목. 변형(full·redacted·team)별 동작 |
| `lm27/report/model.py` | `build_model(inputs, cfg) -> dict`(§9.2) + `model_meta.json`(입력 다이제스트) |
| `lm27/report/export.py` | 자기완결 HTML(§9.4)·CSV(§9.3)·JSON 쓰기, 보관 정리 |
| `lm27/report/drill.py` | 근거 드릴다운 조각(날짜 원장·구간 원장·업무 원장·증거 줄, §6.10) — 로컬 앱 API 와 전체판 내보내기 공용 |
| `lm27/ui/server.py` | 로컬 앱 HTTP 서버(§2.3): 정적 고정 사전·API·보안 헤더 |
| `lm27/ui/api_*.py` | 화면별 API 처리기(`api_home`·`api_collect`·`api_analysis`·`api_report`·`api_team`·`api_settings`·`api_privacy`) |
| `lm27/ui/jobs.py` | 오래 걸리는 작업(수집·분석·내보내기·팀 빌드…)을 하위 프로세스로 띄우고 진행을 모으는 작업 관리자(§2.3.5) |
| `lm27/ui/nextactions.py` | 다음 할 일 목록 계산(§5.7) |
| `web/common/lm27.css` | 디자인 토큰·구성 요소 CSS(§8) |
| `web/common/lm27charts.js` | 차트 = 순수 함수(입력 차트 명세 → 가상 노드 트리). DOM 을 만지지 않는다(§8.6) |
| `web/common/lm27ui.js` | 가상 노드 마운트(`createElementNS`·`textContent`), pill 메뉴·탭·툴팁·서랍·표 보기·펼침·키보드·숫자 표시 함수(§3.1 JS 판) |
| `web/common/icons.svg` | 아이콘 스프라이트(§8.2.9) |
| `web/app/index.html` · `web/app/app.js` | 로컬 앱 껍데기와 화면 6개 로직(API 호출·상태) |
| `web/app/report.js` | 개인 보고서 화면 로직 — 로컬 앱과 자기완결 HTML 이 같은 파일(데이터 출처만 API ↔ 데이터 섬) |
| `web/team/index.html` · `web/team/team.js` · `web/team/admin.html` | 팀 대시보드·관리 화면(TEAM §3.12 의 고정 사전에 공용 파일 3개 추가 요청 — §13 T-6) |
| `tests/report/` | 파이썬 `unittest`: 분석층 골든·모델 결정성·개인=팀·CSV·HTML 정적 검사 |
| `tests/web/run_node_tests.js` | (개발 PC 전용) 차트 순수 함수 골든·표시 함수 골든·악성 문자열 렌더 — 실행 환경에는 node 가 필요 없다 |

### 2.3 로컬 앱 서버

#### 2.3.1 실행

- 진입: `LoadMonitor27.bat`(CP949 + CRLF, `>nul chcp 949`, `pushd "%TEMP%"`) → `"<ROOT>\python\pythonw.exe" <단일 진입점> ui`. 콘솔 창 없이 뜨고, 기동 실패는 `%LOCALAPPDATA%\LoadMonitor27\ui\ui_start_error.txt` 와 Windows 알림 대신 bat 쪽 `python.exe … ui --check` 의 한국어 출력으로 알린다. 서버 프로세스의 cwd 는 `%TEMP%`(TEAM §1.9 규칙 3 — 폴더 이동을 막지 않게). [이동 준비]는 그래도 이 서버를 내린다(python.exe 가 ROOT 안에 있으므로, TEAM §1.11).
- 명령: `lm27 ui [--port N] [--no-browser] [--check]`. `--check` 는 바인드 가능 여부·정적 파일 존재·설정 경고만 출력하고 끝낸다.
- **단일 인스턴스**: `%LOCALAPPDATA%\LoadMonitor27\ui\ui_server.json` = `{"pid", "port", "started_at", "instance_id", "root_id"}`(`root_id` = `sha256(ROOT 정규화 경로)[:8]`). 기동 시 이 파일의 pid 가 살아 있고 `GET http://127.0.0.1:<port>/api/hello` 의 `instance_id`·`root_id` 가 같으면 새로 띄우지 않고 브라우저만 그 주소로 연다. 다른 ROOT 의 LM27 화면이 떠 있으면 다음 포트로 띄운다(두 설치본 공존).
- 브라우저 열기: `ui.openBrowser`(true)면 `os.startfile("http://127.0.0.1:<port>/")`. 서버는 사용자가 [서버 종료](설정 화면) 또는 [이동 준비]를 누를 때까지 산다. `ui.idleShutdownMin`(0 = 끔)이 양수면 마지막 요청 후 그 시간이 지나면 스스로 끝난다.

#### 2.3.2 포트

- 기본 `ui.port = 19280`, 바인드 주소는 **127.0.0.1 고정**(설정 없음 — 다른 PC 에서 열 수 없다).
- 정한 이유(이 PC 실측 2026-10-05): 동적(임시) 포트 범위가 `1024~15000` 이라 그 안의 포트는 바깥 연결이 잠깐 차지할 수 있다(TEAM §3.4 실측과 같음). 예약 범위는 `11300`·`29999` 뿐이었고 19280 은 비어 있었다. 피하는 포트: `D:\배포\LM26`(8765~8767), LM24 대시보드 대역(9148~9167), 팀 서버(9310), LM24 코파일럿(9333), LM27 코파일럿(9343~9352), 팀 서버 대체 포트 후보(19310~19330).
- 바인드 실패(`WinError 10048`·`10013`) 시 `19281…19289`(`ui.portFallbackCount` = 9)를 차례로 시도하고, 위 회피 집합·예약 범위(`netsh interface ipv4 show excludedportrange protocol=tcp`)를 건너뛴다. 모두 실패하면 TEAM §3.4 `diagnose_port()` 를 같은 함수로 불러 원인을 한국어로 보이고 rc 3.
- 실제 포트는 `ui_server.json` 에 쓰고, 팀 서버의 대체 포트 제안(TEAM §3.4 `suggest_port` 의 `cfg.ui.port`)은 설정값과 실제값을 둘 다 피한다(§13 요청 T-7).

#### 2.3.3 보안

| 항목 | 규칙 |
|---|---|
| Host 검사 | `Host` 가 `127.0.0.1:<port>` 또는 `localhost:<port>` 가 아니면 421 `bad_host`(DNS 재바인딩 방어) |
| 쓰기 요청 토큰 | 서버 기동 때 `secrets.token_hex(16)` 을 만들고 `index.html` 을 내보낼 때 `<meta name="lm27-ui-token" content="…">` 자리표시자를 채운다(파일은 바꾸지 않고 응답 때만). `POST`·`PUT`·`PATCH`·`DELETE` 는 헤더 `X-LM27-UI-Token` 이 같아야 한다(`hmac.compare_digest`) — 아니면 403 `ui_token`. 다른 사이트 페이지가 127.0.0.1 로 보내는 위조 요청을 막는다 |
| 본문 형식 | 쓰기 요청은 `Content-Type: application/json` 만(415). 본문 상한 2MB(413) — 단 `/api/bridge/manual/import` 는 `bridge` 답 붙여넣기 때문에 4MB |
| 교차 출처 | `Access-Control-Allow-*` 헤더를 보내지 않는다. `OPTIONS` 는 405 |
| 응답 헤더 | `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` · `X-Content-Type-Options: nosniff` · `Referrer-Policy: no-referrer` · API 는 `Cache-Control: no-store` |
| 정적 제공 | **고정 사전**만(§2.3.4). 요청 경로를 파일 경로로 조합하지 않는다 |
| 로그 | `%LOCALAPPDATA%\LoadMonitor27\ui\logs\ui_YYYYMMDD.log` 에 메서드·경로(쿼리 제외)·상태·소요 ms 만. 본문·라벨·이름 금지. 보관 `ui.logKeepDays`(14) |
| 종료 | `POST /api/shutdown` 은 토큰 + 루프백에서만, 200 응답 뒤 0.5초 후 종료 |

#### 2.3.4 정적 고정 사전

```python
STATIC = {"/": ("web/app/index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("web/app/app.js", "text/javascript; charset=utf-8"),
          "/static/report.js": ("web/app/report.js", "text/javascript; charset=utf-8"),
          "/static/lm27charts.js": ("web/common/lm27charts.js", "text/javascript; charset=utf-8"),
          "/static/lm27ui.js": ("web/common/lm27ui.js", "text/javascript; charset=utf-8"),
          "/static/lm27.css": ("web/common/lm27.css", "text/css; charset=utf-8"),
          "/static/icons.svg": ("web/common/icons.svg", "image/svg+xml")}
```

화면 이동은 해시 경로(`/#home`, `/#collect`, `/#analysis`, `/#report/<section>`, `/#team`, `/#settings/<group>`)로 한 페이지 안에서 한다(서버 경로 추가 없음).

#### 2.3.5 작업(job) 모델

오래 걸리는 일은 서버 안에서 직접 하지 않고 하위 프로세스로 띄운다(화면이 멈추지 않고, 작업이 죽어도 서버가 산다).

```python
@dataclass
class Job:
    job_id: str          # "j" + 시각(YYYYMMDDHHMMSS) + 4hex
    kind: str            # 아래 표
    lane: str            # "bundle"(번들 쓰기 — 동시에 하나) | "net"(팀 전송·레지스트리) | "local"(읽기 전용·빠른 일)
    argv: list[str]      # [python.exe, 진입점, <명령>, ..., "--job", job_id, "--events", "jsonl"]
    state: str           # queued | running | done | partial | failed | cancelled
    started: str | None; ended: str | None; rc: int | None
    events: list[dict]   # 하위 프로세스 표준 출력의 JSON 한 줄 이벤트(최근 ui.jobEventsKeep=500)
    result: dict | None  # 마지막 이벤트 {"ev":"result", ...}
```

| kind | 명령 | lane | 성공 뒤 화면이 하는 일 |
|---|---|---|---|
| `collect` | `collect --auto` / `--mode probe-only` / `--mode recollect --since D --until D` | bundle | 홈·수집 화면 다시 읽기 |
| `move_prepare` | `move-prepare` | bundle | 도우미 창이 뜨고 서버 종료(TEAM §1.11) |
| `bundle_merge` | `bundle merge <dir>` | bundle | 수집 화면 갱신 |
| `analyze` | `analyze --from D --to D [--as-of T] [--no-ai]` (분석 파이프라인 명세) | bundle | 분석 화면, 성공 시 `current.json` 갱신 알림 |
| `report_build` | `report build --run <id>` | local | 보고서 다시 읽기 |
| `report_export` | `report export --run <id> --formats … --variant …` | local | 만든 파일 목록(ROOT 상대 경로)과 [폴더 열기] |
| `quick_reanalyze` | `analyze --rerun <id> --stages time,mining,report --no-ai` | bundle | 확인 질문 응답 뒤 자동(§6.9) |
| `team_build` | `team build --from D --to D` | bundle | 미리보기 열기 |
| `team_send` | `team send <item>` | net | 대기열 갱신 |
| `registry_fetch` | `team registry-fetch` | net | 레지스트리 판 표시 갱신 |
| `team_server` | `team-server --host H --port N` | (분리) | 서버 PC 카드에 상태(§5.5.3) — 화면이 꺼져도 서버는 산다(분리 프로세스, `DETACHED_PROCESS`) |
| `agent_repair` | `agent repair` | local | 수집 화면의 에이전트 상태 갱신 |

- 같은 lane 의 두 번째 작업은 409 `busy` + "지금 '<작업 이름>'이 진행 중입니다 — 끝나면 다시 눌러 주세요"(대기열에 몰래 쌓지 않음).
- 화면은 실행 중인 작업을 `GET /api/jobs/<id>?since=<seq>` 로 `ui.jobPollMs`(1000ms)마다 읽는다(SSE·웹소켓 없이 표준 라이브러리로 충분).
- 취소: `POST /api/jobs/<id>/cancel` → 명령별 정지 플래그 파일을 쓰고 5초 기다린 뒤 프로세스 트리를 끊는다(`taskkill /T /F /PID`). 모든 작업 명령은 재개 가능해야 한다(각 명세의 저널·커서 계약).
- 작업 기록 `%LOCALAPPDATA%\LoadMonitor27\ui\jobs\<job_id>.json`(상태·rc·이벤트 꼬리 200줄, 이름·원문 없음). 서버가 다시 떠도 마지막 20건을 '최근 작업'으로 보인다.
- 이벤트 형식(하위 명령 공통, 각 명세의 표준 출력 이벤트를 그대로 통과): `{"seq": n, "ts": "…", "ev": "stage|progress|warn|msg|result", "stage": "…", "text_ko": "…", "done": n, "total": n}`. `text_ko` 는 각 명세의 사용자 문구 표 문장만(원문·경로 금지).

#### 2.3.6 API 목록

모든 응답은 JSON(UTF-8). 오류 형식은 팀 서버와 같은 `{"ok": false, "code": "<영문>", "error": "<한국어>", "detail": [...]}`.

| 메서드·경로 | 화면 | 요청 | 응답(요지) |
|---|---|---|---|
| `GET /api/hello` | 공통 | — | `{"app":"LM27-ui","version","instance_id","root_id","pc":{"label_auto","kind","roles"},"token_meta":false}` |
| `GET /api/home` | 홈 | — | §5.1.5 `HomeModel` |
| `GET /api/next-actions` | 홈·전역 배지 | — | `[NextAction]`(§5.7) |
| `GET /api/collect/status` | 수집 | — | 이 PC·번들·에이전트·최근 수집 결과·커버리지 요약·todo(§5.2.1) |
| `GET /api/collect/coverage?from&to` | 수집·홈 | 날짜(최대 400일) | 일자×축 합성 상태 + 출처별 셀(§8.4 CH-H01) |
| `POST /api/collect/run` | 수집 | `{"mode":"auto\|probe-only\|recollect","since"?,"until"?}` | `{"job_id"}` |
| `POST /api/worklog` | 수집 | §5.2.4 수동 기록 | `{"ok":true,"id"}` — 정제 후 `manual` 세그먼트로(COLLECT_PC §10) |
| `POST /api/pc/label` | 수집 | `{"label_user"}`(≤20자) | 이 PC `pc.json.label_user` 갱신(로컬 전용) |
| `POST /api/pc/roles` | 수집 | `{"roles":[…]}` | `pc.json.roles` 갱신(TEAM §1.5) |
| `POST /api/move/prepare` · `POST /api/bundle/merge` | 수집 | — / `{"dir"}` | `{"job_id"}` |
| `GET /api/analysis/runs` | 분석 | — | 실행 이력(§5.3.4) |
| `GET /api/analysis/run/<run_id>` | 분석 | — | `run_status.json` + 라벨 출처 통계 + 경고(§5.3.5) |
| `POST /api/analysis/run` | 분석 | `{"from","to","as_of"?,"ai":true\|false}` | `{"job_id"}` |
| `POST /api/analysis/current` | 분석 | `{"run_id"}` | `current.json` 교체(명시 선택) |
| `GET /api/bridge/status` · `GET /api/bridge/manual` · `POST /api/bridge/manual/copy` · `POST /api/bridge/manual/import` | 분석 | — / — / `{"seq"}` / `{"text"}` | COPILOT §10.5 화면 요소(프롬프트 글은 복사 응답에만, 저장·로그 금지) |
| `GET /api/report?run=<id>&variant=full` | 개인 보고서 | — | `report_model.json`(§9.2) — `variant=redacted` 면 가림판 변환본 |
| `GET /api/report/unit/<unit_id>?run=<id>` | 개인 보고서 | — | 단위업무 근거 드릴다운(§6.10.3) |
| `GET /api/report/day/<YYYY-MM-DD>?run=<id>` | 개인 보고서 | — | 날짜 원장 + 구간 원장(§6.10.2) |
| `POST /api/queue/answer` | 개인 보고서 | `{"qid","answer":{…}}` | `{"ok":true,"reanalyze_job"?}`(§6.9) |
| `POST /api/report/export` | 개인 보고서 | `{"run_id","formats":[…],"variants":[…]}` | `{"job_id"}` |
| `POST /api/agentic/need/drop` | 개인 보고서 | `{"need_id","drop":true}` | TEAM §2.5 `overrides.json` 의 `needs` 갱신 |
| `GET /api/hier/state` | 개인 보고서 › 분류 | — | 레지스트리 상태·분류 요약·제안 큐·학습 규칙·코드네임 후보·미적용 수정(§6.11) |
| `POST /api/hier/correction` | 개인 보고서 | `{"unit_id"\|"group", "set": {"project"?, "field"?, "func"?, "wtype"?, "title"?}, "scope": "this\|similar", "from_queue"?}` | HIERARCHY §11.3 수정 기록 추가(대상 증거 키는 서버가 라벨·단위업무에서 채움) → `{"ok": true, "reanalyze_job"?}` |
| `POST /api/hier/proposal` | 개인 보고서 | `{"proposal_id", "action": "accept\|map\|rename\|merge\|reject\|unreject", …}` | HIERARCHY §7.5 |
| `POST /api/hier/codename` | 개인 보고서 | `{"cand", "action": "project\|customer\|ignore\|proceed\|skip"}` | HIERARCHY §8.1 |
| `POST /api/hier/rule` | 개인 보고서 | `{"rule_id", "action": "off\|on\|copy_team"}` | HIERARCHY §11.4(`copy_team` = 팀장에게 전할 문구를 돌려줌) |
| `GET /api/team/status` | 팀 | — | 설정·레지스트리 판·대기열·서버 도달 결과(§5.5) |
| `POST /api/team/ping` | 팀 | `{"host","port"}` | TEAM §2.9 `hello()` 판정 + 문구 |
| `PUT /api/team/settings` | 팀 | `{"server_host","server_port","server_alternates","self_label","member_id","unit_title_mode","share_unknown_apps","auto_send"}` | 검증 결과(§5.5.1) |
| `POST /api/team/settings/reset-address` | 팀 | — | `10.115.147.68:9310` 으로 정확히 되돌림 |
| `POST /api/team/token` | 팀 | `{"token"}` | `data\keys\secrets.json` 에 저장(응답에 값 없음) |
| `POST /api/team/build` · `GET /api/team/outbox` · `GET /api/team/preview/<item>` · `POST /api/team/approve/<item>` · `POST /api/team/send/<item>` · `POST /api/team/drop/<item>` · `POST /api/team/export/<item>` · `POST /api/team/mask` | 팀 | TEAM §2.5·§2.7~2.9·§5.1 그대로 | TEAM 명세 CLI 와 같은 함수 |
| `POST /api/team/registry/fetch` | 팀 | — | `{"job_id"}` |
| `GET /api/teamserver/local` · `POST /api/teamserver/start` · `POST /api/teamserver/stop` · `POST /api/teamserver/diagnose` | 팀 | `{"bind_host","bind_port","store_dir"?,"display_name"?}` | 이 PC 에서 팀 서버 운영(§5.5.3) |
| `GET /api/settings` · `PUT /api/settings` · `POST /api/settings/reset` | 설정 | `{key: value}` / `{"key"}` | 단일 설정 레지스트리 검증 결과(§5.6) |
| `GET /api/privacy/audit?from&to` · `POST /api/privacy/testbench` · `GET /api/privacy/ad-suspects` · `POST /api/privacy/ad-decision` | 설정 | PRIVACY §15.5 | 정제 감사·시험대(메모리만)·광고 의심 큐 |
| `GET /api/calibration` · `POST /api/calibration/apply` | 설정 | WORKTIME §8.3 | 보정 보고·승인 |
| `GET /api/jobs` · `GET /api/jobs/<id>?since=` · `POST /api/jobs/<id>/cancel` | 공통 | — | §2.3.5 |
| `POST /api/shutdown` | 설정 | — | §2.3.3 |

### 2.4 보고서 만들기 흐름

#### 2.4.1 명령

| 명령 | 하는 일 | rc |
|---|---|---|
| `lm27 report build --run <run_id> [--force]` | `load_inputs` → 분석층(§4) → `report_model.json`·`model_meta.json` 을 `data\derived\analysis\<run_id>\report\` 에 원자적으로 쓴다. 입력 다이제스트·보고서 판이 같으면 건너뜀(rc 4) | 0 / 4 / 2(입력 일부 없음 — 만들되 경고) / 1 |
| `lm27 report export --run <run_id> --formats html,csv,json --variant full,redacted [--out <dir>]` | §9.1 파일들을 `ROOT\out\personal\<from>_<to>_<run8>\` 에 쓴다 | 0 / 1 |
| `lm27 report ai-items --run <run_id>` | 코파일럿 단계 입력 `ai_in\workflow_label.jsonl`·`agentic_match.jsonl`·`subagent_review.jsonl`·`review_text.jsonl` 쓰기(§4.10) | 0 / 4 |

분석 파이프라인(분석 파이프라인 명세 소관)은 마이닝 단계에서 `report ai-items` → 브리지 `run --stages workflow_label,agentic_match,subagent_review` → 리뷰 사실 → `report ai-items --stage review_text` → 브리지 `run --stages review_text` → `report build` 순으로 부른다(COPILOT §2.3 호출 지점 4·5). 코파일럿이 없는 PC 에서는 브리지 호출을 건너뛰고 `report build` 가 폴백을 쓴다(§4.10.3).

#### 2.4.2 결정성·다이제스트

`model_meta.json` = `{"report_version": "report/1", "inputs": {"<논리 이름>": "<sha256 앞 16자>"}, "cfg_used": {…report.* 키…}, "built_at": "…"}`. 입력 다이제스트는 §2.5 표의 각 파일 바이트 sha256(없으면 `"missing"`). 모델 JSON 은 `canon_bytes`(TEAM §0.3)로 쓰고 `built_at` 은 모델 안에 넣지 않는다(meta 에만) — 같은 입력이면 모델 바이트가 같다(관문 G-R1).

#### 2.4.3 '지금 보는 결과' 선택

- `data\derived\analysis\current.json` = `{"run_id","from","to","as_of","built_at","report_version","chosen":"auto|explicit","chosen_at"}`. 분석 파이프라인이 성공적으로 `report build` 까지 마치면 `chosen="auto"` 로 원자 교체한다. 사용자가 분석 이력에서 [이 결과 보기]를 누르면 `chosen="explicit"`.
- 화면은 `current.json` 하나만 본다. 없으면 '아직 분석 결과가 없습니다 — [분석] 화면에서 기간을 정해 실행하세요'(빈 상태). 가리키는 실행의 `report_model.json` 이 없거나 판이 다르면 `report_build` 작업을 자동으로 1회 띄우고 "보고서를 새 형식으로 다시 만드는 중입니다"(코파일럿 재질의 없음, RP14).
- 기간 출처 표시: 화면 머리 띠에 `기간 2026-09-01 ~ 2026-10-04 · 기준 10-04 18:00 · 분석 10-05 10:15(자동 선택)`.

### 2.5 입력 계약 (`ReportInputs`)

| 논리 이름 | 파일(모두 `lm27.paths` 경유) | 소유 명세 | 보고서가 읽는 것 | 없을 때 |
|---|---|---|---|---|
| `time.env_slots` | `data\derived\analysis\<run>\time\env_slots.jsonl` | WORKTIME §7.5 | `date, slot, tag, basis, conf, on_leave, pcs` | 보고서 생성 거부(rc 1, "시간 결과가 없습니다") |
| `time.day_ledger` | `…\time\day_ledger.jsonl` | 〃 | 날짜 원장(구성요소 기여·차감·제외·꼬리표·신뢰 비중·커버리지·표식) | 드릴다운만 비움 + 경고 |
| `time.interval_ledger` | `…\time\interval_ledger.jsonl` | 〃 | 구간 원장(시각·꼬리표·근거·대상·분 등급 O/I/X) | 〃 |
| `time.tasks` | `…\time\tasks.json` | 〃 | 단위업무: `id`(unit_id)·`kind`·`cycles[{s,sb,e,eb,s_ref,e_ref,interim}]`·`grade`·`status`·리드·영업 리드·투입·레벨 내역(L1~L7)·병행도·`machine_s`·`pre_request_s`·`flags`·`peers`·`docs{fam:n}`·`first_key` | 거부(rc 1) |
| `time.attrib` | `…\time\attrib.jsonl` | 〃 + **§13 요청 W-1** | 슬롯 귀속 `{slot, target, sec, level, obs, app, fam}` — `obs`·`app`·`fam` 은 이 문서가 요청한 열 | `obs` 없음 → 활동 로그를 L1·L2·L4 근거와 버킷 종류만으로 만들고 '단계 정밀도 낮음' 경고(§4.1.4) |
| `time.team_tables` | `…\time\team_tables.json` | 〃 §5.6 | `envelope_daily`·`alloc_daily`(정수 분) | 거부(rc 1) |
| `time.mm_month` | `…\time\mm_month.json` | 〃 §6 | 월 MM·꼬리표·초과 두 기준·가용·로드·업무 MM | 거부(rc 1) |
| `time.queue` | `…\time\confirm_queue.json` | 〃 §7.3 | 확인 큐 항목 | 확인 질문 절 비움 |
| `time.run_meta` | `…\time\run_meta.json` | 〃 | `core_version`·`calendar_version`·`cfg_used`·`as_of`·`audit`·경고 | 거부(rc 1) |
| `labels` | `data\derived\analysis\<run>\hier\labels.json`·`groups.json`·`queue.json`·`hier_meta.json`(HIERARCHY §12.1 — 그쪽 표기 `data\analysis\<run>\hier\` 는 §13 W-2 와 같은 규칙으로 `derived` 아래) | HIERARCHY | `UnitLabel`(§11.1): `project`(P-·L-·P-99xx)·`proposal_id`·`domain`·`field`·`func`·`wtype`(어휘 **코드**)·`stance`·`ax_link`·`role_id`·`title`·`title_src`·`src`·`conf`·`level`·`flags`·`why`(로컬 전용) · 확인 질문 H01~H06 · `ai_share`·`unclassified_share` | 모든 단위업무 `UNC` + 제목 = 시간 코어 `label`(정제본) + 경고 |
| `hier_local` | `data\local_only\hier\proposals.json`·`rules_learned.json`·`corrections.jsonl`·코드네임 검토 상태 | HIERARCHY §7.3·§8.1·§11.3·§11.4 | 분류 절(§6.11) | 해당 카드 빈 상태 |
| `ai.workflow_label` · `ai.agentic_match` · `ai.subagent_review` · `ai.review_text` | `data\derived\ai_out\<stage>.json` | COPILOT §2.5 | `items[key].ans`·`by` | 단계별 규칙 폴백(§4.10.3) |
| `registry` | `data\team\registry.json` → **유효 레지스트리**(팀 ⊕ 개인 로컬, `lm27.hier.registry.load_effective` — HIERARCHY §3.4) | TEAM §3.10·HIERARCHY §2·§3 | `version`·`projects`(이름·영역·`mask_name`·`status`·`merged_into`)·`vocab`·`agents`·`calendar.version`·`members`(라벨만). **`pepper` 는 읽지 않는다** | 과제 이름 = ID, 에이전트 목록 없음 배너 |
| `person_dir` | `data\local_only\person_dir.json` | PRIVACY §9.6 | `people{who_key: {names, internal, self}}` | 동료 표시명 = `동료 #k` |
| `evidence` | 번들 단일 로더 + 정규화(WORKTIME §2) | TEAM §1.15·WORKTIME §2 | 근거 드릴다운 줄의 정제 필드(제목·시각·방향·상대 키·첨부 문서군 키) | 드릴다운의 증거 줄만 비움 |
| `bundle_state` | `data\pcs\*\pc.json`·`manifest.json`·`move_ready.json`, `data\derived\coverage_ledger.jsonl`·`todo.json` | TEAM §1·COLLECTION §5·§6 | 홈·수집 화면, 측정 품질(§4.9) | 해당 카드 '정보 없음' |
| `outbox` | `data\outbox\team\*\*.meta.json` | TEAM §2.8 | 팀 화면 대기열 | 빈 목록 |

- `ReportInputs` 는 위 파일을 **열고·다 읽고·닫는다**(TEAM §0.2). JSON 은 `read_json`(TEAM §0.3 — 중복 키·NaN 거부, BOM 허용).
- 모든 시각은 시간 코어가 정한 근무 시간대 로컬 벽시계(`time.tzOffsetMin`, 기본 +540)로 다룬다. `zoneinfo.ZoneInfo` 금지(관문 — WORKTIME §10 G10 과 같은 검사).

---

## 3. 공통 어휘와 산식

### 3.1 표시 반올림 — 정수 half-up, 파이썬 = JS

화면(JS)과 CSV·해석 문장(파이썬)이 같은 숫자를 다르게 반올림하지 않도록, 표시는 **정수 연산만** 쓰는 함수 한 벌로 한다. `Number.prototype.toFixed`·파이썬 `round()`(은행가 반올림)·`format(x, '.2f')` 는 표시에 쓰지 않는다(관문 G-R11: `web/**/*.js` 에 `toFixed(` 0건, `lm27/report/**` 에서 `round(` 은 `fmt.py` 안에서만).

```python
# lm27/report/fmt.py   (web/common/lm27ui.js 의 fmtH1·fmtRatio 와 글자 단위로 같은 결과 — 교차 골든 시험)
def fmt_h1(minutes: int) -> str:              # 분 → 시간, 소수 1자리, half-up. minutes ≥ 0
    q = (minutes * 10 * 2 + 60) // 120
    return f"{q // 10}.{q % 10}"

def fmt_ratio(num: int, den: int, digits: int) -> str | None:   # num/den 을 digits 자리, half-up. num ≥ 0
    if den <= 0: return None
    s = 10 ** digits; q = (num * s * 2 + den) // (2 * den)
    return f"{q // s}.{q % s:0{digits}d}" if digits else str(q)

def fmt_mm(env_min: int, denom_min: int) -> str | None: return fmt_ratio(env_min, denom_min, 2)
def fmt_pct(num: int, den: int, digits: int = 0) -> str | None: return fmt_ratio(num * 100, den, digits)
def fmt_days(biz_min: int, std_day_min: int = 480) -> str: return fmt_ratio(biz_min, std_day_min, 1)   # 영업일
def fmt_signed(fn, num, *a) -> str:            # 부호 있는 값(증감)은 절댓값을 같은 함수로 → '+'·'−'(U+2212) 붙임, 0 은 '±0'
```

```javascript
// web/common/lm27ui.js
function fmtH1(min){ const q = Math.floor((min*10*2 + 60)/120); return Math.floor(q/10)+'.'+(q%10); }
function fmtRatio(num, den, digits){ if(den<=0) return null; const s=Math.pow(10,digits);
  const q=Math.floor((num*s*2+den)/(2*den)); return digits ? Math.floor(q/s)+'.'+String(q%s).padStart(digits,'0') : String(q); }
```

입력은 언제나 **정수 분**(또는 정수 분자·분모)이다. 분 값은 2^53 보다 훨씬 작으므로(사람 1명 10년 = 약 5.3×10^6분) JS 의 정수 연산이 정확하다. 골든(시제품 `golden_report.json` 의 `fmt`):

| 함수 | 입력 | 결과 | 입력 | 결과 |
|---|---|---|---|---|
| `fmt_h1` | 3 | `0.1` | 87 | `1.5` |
| `fmt_h1` | 2 | `0.0` | 9483 | `158.1` |
| `fmt_mm` | 9480 / 9600 (W51 158h ÷ 160h) | `0.99` | 11520 / 10560 (TEAM §2.3.1 7월) | `1.09` |
| `fmt_mm` | 4799 / 9600 | `0.50` | 0 / 9600 | `0.00` |
| `fmt_pct` | 9480 / 8880 (W51 로드 158h ÷ 148h) | `107` | 1 / 200 | `1` |

교차 검사: JS 판과 파이썬 판에 같은 11,530 개 입력(분 0~20,000, 분모 4종, 비율 4종)을 넣어 불일치 0(시제품 `fmt_cmp.py`).

표시 단위 규칙: MM 2자리(`0.99 MM`), 시간 1자리(`158.0h`), 비율·로드율 정수 %(`107%`, 1% 미만이면 1자리 `0.4%`), 영업일 1자리(`3.2영업일`), 병행도 1자리(`×1.8`). 0 은 `0.0h` 로 쓰되 '자료 없음'은 `—`(긴 줄표)로 구분한다.

### 3.2 영업 시간과 근무일

- **영업 분** `biz_min(a, b)` = 로컬 시각 구간 [a, b) 중 근무일(달력 `calendar.json`, WORKTIME §2.5)의 정규 구역(개인 표준창 − 점심, 기본 09:00~12:00·13:00~18:00) 분의 합. 반차·연차는 빼지 않는다(리드타임은 달력 기준 경과다 — 개인 휴가로 리드가 짧아 보이지 않게).
- **영업일 표시** = `biz_min / mm.stdDayMin`(480) 을 §3.1 `fmt_days` 로.
- `wd_between(d1, d2)` = (d1, d2] 의 근무일 수(WORKTIME 부록 A `Calendar.wd_between` 그대로).
- 골든(2026-09 검증 달력: 9/24·9/25 추석, 10/5·10/9 공휴일):

| 구간 | `biz_min` | 해설 |
|---|---|---|
| 09-04(금) 16:00 → 09-07(월) 10:00 | 180 | 금 16~18 = 120 + 월 09~10 = 60 |
| 09-23(수) 17:00 → 09-28(월) 09:00 | 60 | 수 17~18 만. 9/24·25 공휴일, 주말 |
| 09-22(화) 12:00 → 09-30(수) 13:00 | 1920 | 화 300 + 수 480 + 월 480 + 화 480 + 수 09~12 180 |

### 3.3 단계 유형 어휘 (과정 마이닝의 닫힌 어휘)

COPILOT_BRIDGE §16 Q13('과정 마이닝 단계 유형 어휘와 체크리스트 플래그의 계산 정의 — 워크플로우 명세')을 이 절과 §4.8 이 정한다. 어휘는 공용 모듈 `lm27/vocab/steps.py`(이 문서 소유) 하나에 두고, 시간 코어(§13 요청 W-1)·보고서·브리지·팀 레지스트리 기본값이 모두 이것을 읽는다.

| 코드 | 한글명 | 종류 | 묶음 | 근거(무엇이 이 단계가 되나) | 도구 접근 기본 | 검증 가능성 기본 |
|---|---|---|---|---|---|---|
| `REQ_IN` | 의뢰 수신 | 점 | 소통 | 차수 시작 근거 S1·S1d(받은 의뢰), S2M(확인한 오프라인 지시 — 표식 `offline`) | 2 | 0 |
| `REQ_OUT` | 지시 발신 | 점 | 소통 | 시작 근거 S1o(내가 보낸 지시 — 조율형) | 2 | 0 |
| `ACK_OUT` | 수락 회신 | 점 | 소통 | S2a 수락 발신, 또는 S1 업무에서 의뢰 뒤 첫 `ack` 발신(표식 시각) | 2 | 1 |
| `REPORT_OUT` | 보고 발신 | 점 | 소통 | 종료 근거 E1·E1d, 중간 보고 E1p(표식 `interim`), E3M(확인한 오프라인 보고 — `offline`) | 2 | 1 |
| `REPORT_IN` | 보고 수신 | 점 | 소통 | 종료 근거 E1i(조율형 업무가 받은 보고) | 2 | 1 |
| `COMM` | 메일·채팅 작성 | 구간 | 소통 | L3 메일·채팅 창 조각, L4 발신 직전 창(보고 메일 작성 포함) | 2 | 1 |
| `MEET` | 회의 | 구간 | 회의 | L2 회의 귀속(분할 포함), L3 회의 창 | 0 | 0 |
| `REVIEW` | 검토 회의 | 구간 | 회의 | L2 회의 중 그 업무의 S2m·E3c 회의이거나 제목 토큰이 `episode.reviewWords` 에 든 회의 | 0 | 0 |
| `DOC_DOC` | 문서 작성 | 구간 | 문서 | L3 문서 조각·L4 저장 앵커의 확장자군 `doc`(doc·docx·hwp·hwpx·odt·rtf) | 2 | 1 |
| `DOC_PPT` | 발표 자료 | 구간 | 문서 | 확장자군 `ppt`(ppt·pptx·odp) | 2 | 1 |
| `DOC_XLS` | 표 계산 | 구간 | 문서 | 확장자군 `xls`(xls·xlsx·xlsm·xlsb·csv·ods) | 2 | 2 |
| `DOC_PDF` | PDF 검토 | 구간 | 문서 | 확장자군 `pdf` | 2 | 1 |
| `DOC_ETC` | 기타 문서 | 구간 | 문서 | 확장자군 `txt`(txt·md·xml·json·yaml·ini·log) 와 미상 확장자의 문서 키 | 1 | 1 |
| `APP_CAD` | 설계 프로그램 | 구간 | 공학 | 앱 분류 `cad`, 또는 확장자군 `cad`(prt·asm·sldprt·sldasm·dwg·dxf·step·stp·igs·iges·catpart·catproduct·ipt·iam·x_t) | 1 | 1 |
| `APP_CAE` | 해석 프로그램 | 구간 | 공학 | 앱 분류 `cae`(해석기 GUI·전처리기), 솔버 제출 앵커 | 1 | 2 |
| `APP_SIM` | 시뮬레이터 | 구간 | 공학 | 앱 분류 `sim` | 1 | 2 |
| `APP_EDA` | 회로 설계 도구 | 구간 | 공학 | 앱 분류 `eda` | 1 | 2 |
| `APP_IDE` | 개발 도구 | 구간 | 코드 | 앱 분류 `ide`, 확장자군 `code`(py·c·h·cpp·hpp·cs·java·js·ts·m·v·sv·vhd·vhdl·ipynb·sql·ps1·bat) | 2 | 2 |
| `APP_ENG` | 기타 공학 도구 | 구간 | 공학 | 앱 분류 `eng`(계측·광학·열 해석 보조 등 카탈로그 '공학') | 1 | 1 |
| `COMMIT` | 코드 커밋 | 구간 | 코드 | L4 커밋 앵커(직전 창 45분) | 2 | 2 |
| `WEB` | 웹 자료 조사 | 구간 | 조사 | L3 브라우저 조각 중 정제기 `work_site` 판정(PRIVACY §12.6) — 일반 브라우저는 L3 '일반' 관측이라 업무 귀속이 L5·L6 로만 되므로 단계가 되지 않는다 | 2 | 1 |
| `OFFLINE` | 오프라인 업무 | 구간 | 오프라인 | L1 수동 기록 귀속 | 0 | 0 |

- **종류**: `점`(milestone) 은 시각만 있고 소요 0, `구간`(activity) 은 귀속 분을 가진다. 점 단계는 순서·대기 계산에만 쓰이고 '작업 병목'·서브에이전트 투입 가중에는 들어가지 않는다.
- **묶음**(class) 7종 `소통·회의·문서·공학·코드·조사·오프라인` 은 단위업무 타임라인의 줄(§4.3.1)과 영역 수준 구성(§4.3.3)에 쓴다.
- **도구 접근 기본**(§4.8 TOOL 점수): 2 = 열린 파일 형식·자동화 인터페이스로 에이전트가 직접 다룰 수 있음(오피스·메일·채팅·브라우저·코드), 1 = 상용 GUI 도구라 스크립트·배치 인터페이스가 있어야 함(CAD·해석·시뮬·EDA·기타 공학), 0 = 사람의 자리(회의·오프라인). 팀 레지스트리 `vocab.step_tool_access{code: 0|1|2}` 로 덮어쓸 수 있다(예: 사내에 해석기 배치 API 가 있으면 `APP_CAE: 2`).
- **검증 가능성 기본**(§4.8 VER 점수): 2 = 결과를 규칙·재실행으로 확인 가능(표 계산·해석·시뮬·코드), 1 = 사람이 빠르게 검토 가능한 문서·메시지, 0 = 판단·합의(회의·오프라인·의뢰). 레지스트리 `vocab.step_verifiable` 로 덮어쓰기.
- **확장자 → 확장자군**: `lm27/vocab/steps.py: ext_class(ext) -> 'doc'|'ppt'|'xls'|'pdf'|'txt'|'cad'|'code'|''`(소문자, 점 없이). 위 표의 목록이 기본값이며 `report.mining.extClassExtra{ext: class}` 로 추가(제거는 불가 — 결정성).
- 팀 레지스트리의 `vocab.step_types` 는 **이 코드 목록**을 쓰고 한글명은 `vocab.step_type_names{code: 한글명}` 에 둔다(§13 요청 T-1 — TEAM 예시의 `"의뢰수신"` 같은 한글 값을 코드로 바꾼다). 코파일럿 프롬프트에는 `코드 한글명` 쌍으로 실린다(COPILOT §8.0.3).

### 3.4 관측·추정·미귀속 — 무엇을 어떻게 구분해 보이나

| 층 | 값 | 정의(출처) | 화면 부호 |
|---|---|---|---|
| 귀속 분 등급 | **O 관측** | 귀속 단계 L1(수동)·L2(회의 전체)·L3(PC 맥락) (WORKTIME §7.1) | 채움(solid) + 글자 '관측' |
| | **I 추정** | L2 분할(대형분할·불참의심)·L4(앵커 직전 창)·L5(흡수·공백·하한근접)·L6(비례) | 45° 빗금(`#hatch-est`) + 글자 '추정' |
| | **X 미귀속** | 버킷 5종(`B_GENERIC`·`B_COMM`·`B_MEET`·`B_OFFPC`·`B_UNKNOWN`) | 회색 채움 + 135° 빗금(`#hatch-unattr`) + 글자 '미분류' |
| 슬롯 신뢰 | high·mid·low | 봉투 근거 코드(WORKTIME §7.1 표) | 날짜 막대: low 비중 ≥ 30% 인 날은 막대 전체에 빗금 + '낮은 신뢰' 표식 |
| 단위업무 경계 등급 | A·B·C·D·E·O·Z·M | WORKTIME §4.10 | 배지(§8.2.6): A·B 실선 테두리, C 점선, D·E 짧은 점선 + '추정 경계', O '진행 중 ▸', Z '미착수', M '수동' |
| 경계 근거 | S1…/E1… 코드 | WORKTIME §1.3 | 근거 드릴다운에서 코드·시각·근거 키(로컬 해석 제목) |
| 라벨 출처 | ai·manual·rule | §3.5 | 작은 꼬리표 `AI`·`AI(붙여넣기)`·`규칙` |

- 보고서 모델의 모든 분 합계는 `obs_min + est_min + unattr_min = env_min` 을 만족한다(날·월·기간 각각, 정수 — 관문 G-R2 의 일부). 귀속 분의 O/I 구분은 `attrib.jsonl` 의 `level` 로 센다(L2 의 전체/분할 구분은 `level` 값 `L2회의`·`L2회의(대형분할)`·`L2회의(불참의심)` 그대로).
- 정수 분 표(팀 묶음 alloc)는 슬롯 초를 분으로 최대잉여 반올림한 값이다. O/I 분은 **같은 최대잉여 함수**(`lr_minutes`, WORKTIME 부록 A)를 (날짜, 꼬리표, 업무) 칸 안에서 다시 적용해 `obs_min + est_min = alloc 분` 이 정확히 맞게 나눈다(동률은 'O' 가 먼저).

### 3.5 라벨 출처 표시

| `by` | 꼬리표 | 뜻 | 출처 |
|---|---|---|---|
| `ai` | `AI` | 코파일럿 자동 경로 답 | `ai_out` (COPILOT §2.5) |
| `manual` | `AI(붙여넣기)` | 수동 붙여넣기 경로 답 | 〃 |
| `rule` · `rule_pending` · (ai_out 없음) | `규칙` | 단계 폴백(§4.10.3). `rule_pending` 은 다음 분석에서 다시 물을 항목 | 〃 / 보고서 폴백 |
| (사용자 지정) | `내 지정` | 확인 질문 응답·수동 기록으로 사람이 정한 값 | worklog |

분석 화면과 보고서 머리 띠에 단계별 비율(`AI 112 · 규칙 8`)을 보인다. 규칙 비율이 50% 를 넘으면 머리 띠에 "AI 라벨이 절반 넘게 비어 있습니다 — 클라우드PC 에서 분석하면 채워집니다"(PC1·PC2 에서 분석한 경우의 정상 상태를 설명).

### 3.6 이름 해석과 보고서 변형

`lm27/report/resolve.py` 가 키를 사람이 읽는 글자로 바꾼다. 무엇으로 바꾸는지는 **변형**(variant)이 정한다.

| 키 | `full`(로컬 앱·개인 전체판) | `redacted`(개인 가림판) | `team`(팀 묶음·팀 보고서) |
|---|---|---|---|
| 동료 `who_key`(w+16hex) | 사람 사전 `names[0]`(PRIVACY §9.6). 없으면 `동료 #k` | `동료 #k` | 사내 주소면 `peer_key`(c_…, TEAM §2.3.3), 팀 화면에서는 같은 `self_peer_key` 를 가진 팀원 라벨, 아니면 `동료-<KEY4>` |
| 본인 | 사람 사전 `self` 이름, 없으면 `나` | `나` | `person.self_label` 또는 서버 라벨 |
| 외부 상대 | 도메인 계급 토큰(`[고객사:C01]`·`[협력사:V02]`·`외부`) + 정제된 표시명 | 도메인 계급 토큰만 | `peers_external` 건수만 |
| 문서군 `fam_key` | 정제된 문서 이름(수집 레코드의 `title_masked`/문서명 정제본) | `문서 #k` | 싣지 않음 |
| 메시지 `msg_key` | 정제된 제목(`subject_masked`) | 싣지 않음 | 싣지 않음 |
| 회의 ID | 정제된 회의 제목 | `회의` + 날짜 | 싣지 않음 |
| 단위업무 제목 | 분류 단계 제목(정제본) | 팀 묶음과 같은 제목(`team_text` 통과분, 아니면 generic `<분야>·<기능> 단위업무 #n` — TEAM §2.5) | 같음 + 미리보기 가림 |
| 과제 이름 | 레지스트리 `name`(로컬 레지스트리 캐시) | 레지스트리 `mask_name=true` 면 과제 ID, 아니면 이름 | 서버 레지스트리 라벨 |
| 앱 | 카탈로그 표시명, 미상은 `미상 프로그램(…exe)` | 카탈로그 표시명, 미상은 `미상 프로그램` | 카탈로그 앱 ID, 미상은 분 합계만 |
| PC | `label_user` 또는 `label_auto` | `label_auto`(PC1·클라우드PC) | `label_auto` |

- 번호표 `k`: 보고서 모델 안에서 **공유 투입 분 내림차순 → 공동 단위업무 수 내림차순 → 키 사전순**으로 1부터. 같은 모델이면 같은 번호(결정성). 코파일럿 리뷰의 `동료1…`(COPILOT §8.5 `peers_map`)은 그 질의 안 번호이므로, 화면에 낼 때 `peers_map` → who_key → 이 절의 해석으로 바꾼다(번호가 둘이 섞이지 않게).
- `full` 변형의 산출 파일은 **로컬 전용**이다. 내보내기 화면과 파일 머리에 "이 파일에는 동료 이름·문서 이름이 들어 있습니다 — 내 PC 밖으로 보내지 마세요(공유는 가림판)"를 적는다. 팀 업로드 경로는 이 파일을 읽지 않는다(TEAM §2.4 허용 목록 빌더).
- `redacted` 변형은 모델을 **허용 목록 방식**으로 다시 만든다(§9.2.4) — `full` 모델에서 이름을 지우는 방식이 아니다(지우다 빠뜨리는 길을 없앰).

---

## 4. 보고서 분석층 (결정적 산식)

모든 함수는 순수하다: 입력(§2.5)과 설정(§10)만 보고, 시계·난수·파일 순서·해시 시드에 의존하지 않는다. 모든 정렬은 표에 적은 동률 깨기 규칙을 끝까지 적는다. 결과는 보고서 모델(§9.2)의 해당 절이 된다.

### 4.1 단위업무 활동 로그

#### 4.1.1 자료구조

```python
# lm27/report/analysis/activity.py
@dataclass(frozen=True)
class Run:                       # 한 단위업무 안에서 같은 단계 유형(obs)이 이어진 슬롯 구간
    unit_id: str
    type: str                    # §3.3 구간 단계 코드
    a: int; b: int               # 로컬 분(2026-01-01 00:00 기준 정수, lsec // 60) — [a, b)
    sec: int                     # 그 업무에 귀속된 초 합(분할 슬롯은 그 업무 몫만)
    obs_sec: int                 # 그중 O 등급 초
    levels: frozenset[str]       # 포함된 귀속 단계(L1~L6 표기)
    apps: tuple[tuple[str, int], ...]   # (app_id, 초) — 초 내림차순, 같으면 app_id 순
    fams: tuple[tuple[str, int], ...]   # (fam_key, 초)

@dataclass(frozen=True)
class Milestone:
    unit_id: str
    type: str                    # §3.3 점 단계 코드
    t: int                       # 로컬 분
    cycle: int                   # 차수 번호(0부터)
    key: str                     # 근거 키(msg_key·회의 ID·'manual:<id>') — 로컬 드릴다운 전용
    flags: frozenset[str]        # offline · interim · date_only

ActivityLog = dict[str, list[Run | Milestone]]   # unit_id → 시각순(정렬 키: (a 또는 t, 0 if Milestone else 1, 코드 순번))
```

#### 4.1.2 만들기

```text
build_activity(tasks, attrib, days, cfg) -> ActivityLog
  # ① 구간: attrib 행 중 target 이 단위업무(u_…)이고 obs ≠ '' 인 것
  for (unit, obs) 별로 slot 오름차순:
      연속 슬롯(slot == 이전 slot + 1) 이고 같은 obs 면 한 Run 으로 잇는다(a = 첫 슬롯 시작, b = 마지막 슬롯 끝)
      sec·obs_sec·levels·apps·fams 를 더한다(O 등급 = WORKTIME §7.1)
  # ② 점: tasks.json 의 차수 근거 코드에서(§3.3 '근거' 열)
      sb ∈ {S1, S1d} → REQ_IN(t = s, flags: date_only if S1d) ; sb = S1o → REQ_OUT ; sb = S2M → REQ_IN(offline)
      sb = S2a → ACK_OUT(t = s) ; S1 업무의 표식 '수락 HH:MM' → ACK_OUT(t = 그 시각)
      eb ∈ {E1, E1d} → REPORT_OUT(t = e, date_only if E1d) ; eb = E1i → REPORT_IN ; eb = E3M → REPORT_OUT(offline)
      interim 의 각 E1p → REPORT_OUT(interim)
      S2p·S2m·E2h·E2l·E3c·E3i·NEXT_REQ·OPEN 은 점 단계를 만들지 않는다 — 추정 경계는 단계가 아니라 타임라인의 경계 표식(§4.3.1)이다.
      (S2m 의 의뢰자 회의·E3c 의 검토 회의 자체는 L2 귀속이 있으면 REVIEW 구간으로 이미 들어 있다)
  # ③ 정렬: 위 정렬 키. 같은 시각 점 둘이면 코드 순번(§3.3 표 순서)
```

#### 4.1.3 L5·L6 분의 취급

L5(흡수·공백·하한근접)·L6(비례) 귀속 분은 `obs` 가 없으므로 단계가 되지 않는다. 단위업무의 `effort_min` 에는 들어가지만(시간 코어 그대로), 워크플로우 단계 소요(`median_min`)에는 들어가지 않는다. 그래서 단계 소요 합 ≤ 투입이며, 단위업무 패널에 `단계로 설명된 투입 82%` 처럼 비율을 보인다(정직한 표시).

#### 4.1.4 `obs` 열이 없을 때(시간 코어 구판)

`time.attrib` 에 `obs` 가 없으면(§13 요청 W-1 이 반영되기 전) 구간 단계는 다음만 만든다: L1 → `OFFLINE`, L2 → `MEET`(검토 여부 모름), L4 → `COMM`(발신·저장·커밋 구분 불가). L3 분은 단계 없음으로 둔다. 모델 `flags.warnings` 에 `mining_coarse`("단계 정밀도가 낮습니다 — 시간 결과에 단계 정보가 없습니다")를 넣고, 팀 묶음의 워크플로우에도 같은 표식(`quality.reasons` 에 `mining_coarse`)을 단다.

### 4.2 과정 마이닝 — 역할 업무 수준

입력: 한 사람의 한 역할 업무(role_id)에 속한 단위업무 중 상태가 `not_started`(Z)가 아니고 투입 > 0 인 것 U(시작 시각순). 미분류 역할(과제·제안 없음)도 같은 방법으로 만든다.

#### 4.2.1 절차

```text
mine_role(U, log, cfg) -> RoleWorkflow
  N = |U|
  # ① 흔적 정리: 단위업무마다 log 를 시각순으로 훑어
  collapse(items, keep=None):
      구간 단계 중 sec < minStepSec(600초 = 10분) 인 Run 은 버린다(알트탭·잠깐 본 창). 점 단계는 버리지 않는다
      keep 이 주어지면 keep 밖의 단계를 버린다
      바로 앞 항목과 단계 코드가 같으면 하나로 합친다(a = min, b = max, sec·obs_sec 합, 횟수 n += 1)
  T0[u] = collapse(log[u])
  # ② 지지도: sup[c] = c 가 한 번이라도 나온 단위업무 수, tot[c] = c 의 sec 합
  thr = max(1, ceil(minSupportRatio(0.3) × N))
  cand = [c | sup[c] ≥ thr], 정렬 (−sup, −tot, 코드 순번)
  forced = cand ∩ {REQ_IN, REQ_OUT, REPORT_OUT, REPORT_IN}           # 시작·끝 점은 항상 남긴다
  keep = forced + (cand − forced)[: maxSteps(8) − |forced|]
  dropped = cand − keep ∪ {c | sup[c] < thr}                          # 화면에 '드물어 뺀 단계' 로 보인다
  T[u] = collapse(log[u], keep)                                        # 빠진 단계 사이의 같은 단계는 다시 합쳐진다
  # ③ 순서: 단계 c 의 위치 pos(u, c) = (c 의 첫 출현 시각 − u 시작) / (u 끝 − u 시작)
  #     u 시작 = 첫 차수 시작(추정 경계 포함), u 끝 = 마지막 차수 끝(진행 중이면 분석 시각)
  #     구간 길이 0 이면 pos = 흔적 안 순번 / (길이 − 1) (길이 1 이면 0). pos 는 [0, 1] 로 자른다
  order = keep 을 (median(pos(·, c)), 코드 순번) 으로 정렬 → 단계 번호 1..k
  # ④ 단계 통계(단계 c 가 나온 단위업무만 대상)
  median_min = 점 단계 0, 구간 단계는 median(단위업무별 c 의 sec 합 / 60) 을 정수 half-up
  p75_min    = 같은 표본의 75 백분위(최근순위 방식: 정렬 후 ceil(0.75 × n) 번째)
  obs_share  = Σ obs_sec / Σ sec (구간 단계만)
  freq_month = (c 가 나온 Run·점 개수) / max(1, 그 역할에 투입이 있는 달 수)
  # ⑤ 전이(직접 이어짐): T[u] 의 이웃 쌍 (x, y) 마다 edges[(no(x), no(y))] += 1
  #     대기 wait = biz_min(x.b, y.a)  (점은 a = b = t) → waits_in[no(y)] 에 추가
  edges 정렬 (−n, i, j), 상위 maxEdges(12) 만 그린다(나머지는 표에만)
  wait_in_median_min[j] = median(waits_in[j]) 정수 half-up, 표본 없으면 None
  rework = i > j 인 전이(되돌림) — 역방향 화살표로 그린다
  # ⑥ 작업 비중: work_share[c] = median_min[c] / Σ_구간 median_min (소수 3자리)
  # ⑦ 병목(N ≥ minUnitsForBottleneck(3) 일 때만, 아니면 sample = 'thin' 으로 '표본 부족' 표시)
      대기 병목 = wait_in_median_min 이 가장 큰 단계(동률은 번호 작은 쪽), 값 ≥ waitBottleneckMin(480 = 1영업일)
      작업 병목 = work_share 가 가장 큰 구간 단계(동률은 번호 작은 쪽), 값 ≥ workBottleneckShare(0.4)
      둘 다 해당하면 둘 다 표시(같은 단계일 수도 있다)
  # ⑧ 역할 요약: 리드(영업 분) 중앙값·75 백분위, 투입 중앙값, 병행도 중앙값(시간 코어 단위업무 병행도), 완료 비율
```

#### 4.2.2 자료구조

```python
@dataclass
class Step:
    no: int; code: str; name: str; kind: str            # kind ∈ {'M', 'A'} (점·구간)
    n: int                                              # 지지도(나온 단위업무 수)
    freq_month: float                                   # 월 평균 출현 횟수(소수 1자리로 표시)
    median_min: int; p75_min: int; obs_share: float | None
    wait_in_median_min: int | None; work_share: float | None
    label: str; desc: str; label_by: str                # §4.10 — 코파일럿 라벨 또는 규칙 폴백
    agent_grade: str                                    # '상'·'중'·'하'·'' — §4.7 매칭 중 이 단계 유형의 최고 등급
    subagent: str                                       # '적합'·'조건부'·'부적합' — §4.8 단계 판정(최종)
    why: list[str]                                      # §4.8 why 어휘

@dataclass
class RoleWorkflow:
    role_id: str; units: list[str]; units_n: int; support_threshold: int
    steps: list[Step]; edges: list[list[int]]; rework: list[list[int]]
    bottlenecks: list[dict]                             # {"no", "kind": "wait"|"work", "value_min"|"share"}
    dropped: list[str]; sample: str                     # 'ok' | 'thin'
    traces: dict[str, list[str]]                        # unit_id → 정리된 단계 코드 열(드릴다운용)
    lead_biz_median_min: int | None; lead_biz_p75_min: int | None
    effort_median_min: int; parallel_median: float | None; done_ratio: float
    ai_role: str; ai_summary: str; ai_by: str           # 코파일럿 workflow_label 의 role·summary
```

#### 4.2.3 골든 — 과제A · 회로 · 해석/분석(홍길동), 단위업무 4개 (시제품 `mine_role_A`)

입력 흔적(9월, 검증 달력):

| 단위업무 | 시작 → 끝 | 흔적(시각순) |
|---|---|---|
| u_a1 | 09-01 09:30 → 09-04 16:00 | REQ_IN 09-01 09:30 · APP_CAE 09-01 10~12, 09-02 09~11 · COMM 09-02 11:00~11:05(5분 — 버림) · DOC_XLS 09-03 14~16 · MEET 09-04 10~11 · REPORT_OUT 09-04 16:00 |
| u_a2 | 09-07 10:00 → 09-16 11:00 | REQ_IN · APP_CAE 09-07 13~17 · DOC_XLS 09-08 09~10 · APP_CAE 09-10 13~15 · DOC_XLS 09-15 13~15 · REPORT_OUT 09-16 11:00 |
| u_a3 | 09-14 09:10 → 09-18 17:30 | REQ_IN · APP_CAE 09-14 10~12, 09-15 09~10 · DOC_XLS 09-16 15:00~16:30 · DOC_PPT 09-17 09:00~09:08(8분 — 버림) · MEET 09-18 14~15 · REPORT_OUT 09-18 17:30 |
| u_a4 | 09-21 11:00 → 10-02 10:00 | REQ_IN · APP_CAE 09-22 09~12 · DOC_XLS 09-30 13:00~14:30 · REPORT_OUT 10-02 10:00 |

결과(지지도 문턱 = ceil(0.3 × 4) = 2):

| 번호 | 단계 | n | 위치 중앙 | 중앙 소요 | 들어오는 대기 중앙(영업 분) | 작업 비중 |
|---|---|---|---|---|---|---|
| 1 | REQ_IN 의뢰 수신 | 4 | 0.000 | 0 | — | — |
| 2 | APP_CAE 해석 프로그램 | 4 | 0.011 | **210분** (240·360·180·180 의 중앙) | 120 | **0.560** |
| 3 | DOC_XLS 표 계산 | 4 | 0.592 | **105분** (120·180·90·90) | **720** (600·60·1320·720·1920) | 0.280 |
| 4 | MEET 회의 | 2 | 0.945 | 60분 | 495 | 0.160 |
| 5 | REPORT_OUT 보고 발신 | 4 | 1.000 | 0 | 270 | — |

- 전이(횟수 내림차순): 2→3 ×5, 1→2 ×4, 3→4 ×2, 3→5 ×2, 4→5 ×2, **3→2 ×1(되돌림 — u_a2 의 해석 재수행)**.
- 병목: **대기 병목 = 3 표계산**(들어오는 대기 중앙 720분 = 1.5영업일 ≥ 480), **작업 병목 = 2 해석 프로그램**(작업 비중 0.56 ≥ 0.4).
- 화면 문장(규칙 생성, §6.3.3): "해석 프로그램 작업이 이 역할 투입의 56%로 가장 큽니다. 해석을 마치고 표 계산을 시작하기까지 보통 1.5영업일을 기다립니다(대기 병목)."

### 4.3 단위업무·과제·업무 영역 수준 워크플로우

#### 4.3.1 단위업무 수준 (`UnitWorkflow`)

```text
unit_workflow(u, log, task) -> {
  lanes:      log 에 나온 묶음(§3.3) 을 고정 순서 [소통, 회의, 문서, 공학, 코드, 조사, 오프라인] 로
  runs:       [{type, class, a, b, min, obs_min}]            # collapse 하지 않은 원 Run(10분 미만 포함 — 근거 보존)
  milestones: [{type, t, flags}]
  boundaries: [{cycle, side: 'start'|'end', code(S1… / E1…), t, grade_part, estimated: bool}]   # 추정 경계 S2p·S2m·E2l·E3c·E3i·NEXT_REQ 는 estimated
  waits:      collapse(log[u]) 의 이웃 쌍마다 {after, before, biz_min} ; longest_wait = biz_min 최대(동률 앞쪽)
  explained_ratio: Σ runs.min / effort_min                    # §4.1.3
  cycles:     차수별 [시작, 끝] 과 차수 사이 '재의뢰'·'조용한 뒤 추가 요청' 표식
}
```

#### 4.3.2 과제 수준 (`ProjectWorkflow`)

한 사람의 한 과제(또는 제안 과제) 안에서:

```text
project_workflow(P, units_by_role, log, cfg) -> {
  roles: 과제 안 역할 업무를 (첫 단위업무 시작 시각, role_id) 순으로
  lanes: 역할마다 단위업무 막대(§8.4 CH-P06 간트 규칙 — 리드 띠 + 주 밀도)
  handoffs: 역할 사이 인계
     단위업무 a(역할 x) → b(역할 y ≠ x): a.마지막 끝 날짜 ≤ b.시작 날짜, wd_between(a.끝, b.시작) ≤ handoffWd(3),
     그리고 (a.docs ∩ b.docs ≠ ∅ 또는 a.peers ∩ b.peers ≠ ∅)
     b 마다 선행자는 하나: 조건을 만족하는 a 중 끝이 가장 늦은 것(동률 unit_id 사전순)
     집계: (x, y) 별 {n, gap_biz_median_min, via: {doc: n, peer: n}}
  role_mix: 역할별 투입 분·비중, 역할별 RoleWorkflow 요약(병목 1줄)
}
```

- 화면은 역할 레인 간트 위에 인계를 '역할 x → 역할 y · 3회 · 중앙 0.4영업일 · 문서 공유 2' 표로 보이고, 간트에서 인계 쌍을 가는 곡선으로 잇는다(선택 시에만 — 평소에는 숨김, 그림 혼잡 방지).
- 골든(시제품 `relatedness` 의 순서 판정과 같은 규칙): u_a2(해석, 09-16 끝) → u_b1(설계, 09-17 시작), 근무일 1일, 문서군 `f3` 공유 → 인계 1건(via doc).

#### 4.3.3 업무 영역 수준 (`DomainWorkflow`) · 사람 전체

```text
domain_workflow(k, units, log) -> {
  projects: 그 영역의 과제(투입 내림차순, 과제 키 순)
  class_mix: 묶음별 Run 분 합(구간 단계만) → 비중. 단계로 설명되지 않은 투입(L5·L6)은 '단계 없음' 으로 따로
  top_bottlenecks: 그 영역 모든 RoleWorkflow 의 병목을 (대기 병목 값 내림차순, 작업 병목은 비중 × 역할 투입) 로 상위 3
  units_n·done_n·lead_biz_median_min·effort_median_min
}
```

사람 전체(트리 뿌리)도 같은 함수로 모든 영역을 합쳐 만든다.

### 4.4 주간·월간 리뷰

#### 4.4.1 기간

- **주** = ISO 주(월요일 시작, 근무 시간대 날짜). 분석 기간과 겹치는 주만. 기간 경계에 걸린 주는 '부분 주(n/5 근무일)' 표시.
- **월** = 달력 달. 부분월은 WORKTIME §6.4 처럼 '부분월(c/W 근무일)'.

#### 4.4.2 기간별 사실

| 필드 | 정의 |
|---|---|
| `env_min`·`by_tag`·`attributed_min`·`unattr_min`·`obs_min`·`est_min` | 그 기간 날짜의 정수 분 표 합(§3.4) |
| `top_projects` | 과제(제안·UNC 포함)별 alloc 분 내림차순 상위 5(동률 과제 키) |
| `active` | 그 기간 alloc > 0 인 단위업무(분 내림차순) |
| `started` | 첫 차수 시작이 기간 안인 단위업무. 추정 시작(S2p·S2m)은 '추정 시작' 표식 |
| `finished` | 마지막 차수 끝이 기간 안이고 상태 `closed`·`estimated` 인 단위업무(E3i·NEXT_REQ 끝은 '추정 종료') |
| `continuing` | `active` 중 시작·끝이 기간 밖 |
| `unstarted` | 미착수(Z) 의뢰 중 의뢰 시각이 기간 안 |
| `lead_table` | `finished` 각각: 리드(달력 분)·영업 리드·투입·병행도·등급·`overrun`·`causes` |
| `ot_units` | 연장·야간·휴일 꼬리표 alloc 분이 큰 단위업무 상위 5 + 초과 꼬리표의 미귀속 분 |
| `peers_top` | 그 기간 active 단위업무의 동료(§4.5) 상위 5 |
| `facts` | 코파일럿 리뷰 입력(§4.10.1) |
| `ai` | 코파일럿 `review_text` 답: `summary`·`highlights[{text, refs}]`·`relations`·`next`·`by` |

#### 4.4.3 리드타임 초과와 원인 코드

```text
baseline(u) = 같은 역할 업무에서 u 를 뺀 완료 단위업무 중 끝이 u 의 끝 이전 baselineMonths(6)개월 안인 것들의
              영업 리드 중앙값 L₀ 와 투입 중앙값 E₀. 표본 < baselineMinUnits(3) 이면 같은 업무 영역·같은 기능으로 넓히고,
              그래도 3 미만이면 baseline 없음 → 원인 'NO_BASELINE'(초과 판정 안 함)
overrun(u) = biz_lead(u) > leadOverrunRatio(1.5) × L₀
causes(u) (해당하는 것 모두, 이 순서):
  WAIT        (biz_lead − effort) / biz_lead ≥ 0.7  그리고  u 의 최장 대기(§4.3.1) ≥ 480 영업 분 — 그 대기 앞뒤 단계를 함께 보인다
  REWORK      차수 ≥ 2 (재의뢰·조용한 뒤 추가 요청)
  PARALLEL    u 의 병행도 ≥ parallelHigh(3.0)
  SCOPE       effort ≥ scopeRatio(1.5) × E₀
  LATE_START  wd_between(첫 차수 시작 날짜, 첫 진행 근거 날짜) ≥ lateStartWd(3)
  DATA        등급 D·E, 또는 리드 구간에 커버리지 결손일(mail_out·teams 가 blocked·transport_fail·out_of_horizon·not_attempted)이 있음
  해당 없음 → UNEXPLAINED
```

| 코드 | 화면 이름 | 설명 문장(규칙) |
|---|---|---|
| `WAIT` | 대기 | "작업 사이 대기가 길었습니다(가장 긴 대기: {앞 단계} → {뒤 단계} {d}영업일)." |
| `REWORK` | 재작업 | "같은 일이 {n}차례 다시 의뢰되었습니다." |
| `PARALLEL` | 병행 | "다른 일 {p}건과 함께 진행했습니다(평균 병행도 ×{p})." |
| `SCOPE` | 작업량 | "투입이 평소의 {r}배였습니다({h}h, 평소 {h0}h)." |
| `LATE_START` | 착수 지연 | "의뢰 뒤 {d}근무일 지나 작업을 시작했습니다." |
| `DATA` | 근거 부족 | "경계가 추정이거나 그 기간 메일·팀즈 기록이 비어 있어 리드타임이 부정확할 수 있습니다." |
| `UNEXPLAINED` | 원인 미상 | "기록으로 설명되지 않는 지연입니다(오프라인 대기·외부 요인일 수 있음)." |
| `NO_BASELINE` | 비교 기준 없음 | "비교할 완료 업무가 부족합니다." |

골든(시제품 `overrun_u_a4`·`overrun_u_a5`, 기준 = u_a1·u_a2·u_a3 의 영업 리드 1770·3420·2360 → 중앙 **2360분**, 문턱 1.5 × 2360 = 3540):

| 단위업무 | 영업 리드 | 투입 | 최장 대기 | 차수 | 병행도 | 착수 | 판정 |
|---|---|---|---|---|---|---|---|
| u_a4 (09-21 11:00 → 10-02 10:00) | 3300 | 270 | 1920 | 1 | 2.4 | 1근무일 | 초과 아님(3300 ≤ 3540) |
| u_a5 (10-12 10:00 → 10-27 15:00, 가상) | 5520 | 300 | 2880 | 2 | 3.2 | 3근무일 | **초과 — WAIT·REWORK·PARALLEL·LATE_START** (SCOPE 아님: 300 < 1.5 × 210 = 315) |

#### 4.4.4 초과 근무의 원인

기간의 초과 분(연장 + 야간 + 휴일, `mm.overtimeBasis = window`)을 단위업무별로 나눠 상위 5를 보이고, 초과 꼬리표 슬롯의 미귀속 분(버킷)은 "업무에 묶이지 않은 초과 {h}h" 한 줄로 보인다. `daily8h` 기준을 고른 사용자는 일 8h 초과분을 그날 단위업무 분 비율로 나눠(최대잉여, 정수 분) 같은 표를 만든다.

### 4.5 같이 일한 동료

```text
peers_of(u) = who_key 집합, 각자의 관계 꼬리표:
  requester  : u 의 시작 근거 메시지(S1·S1d·S1o 의 상대 — S1o 면 지시 받은 사람)
  reporter   : 종료 근거 보고(E1·E1d 의 직접 수신자, E1i 의 보낸 사람)
  thread     : u 에 연결된 대화(conv)에서 그 사람과 주고받은 메시지가 peerMinMsgs(2)건 이상
  meeting    : u 에 연결된 회의(L2 대상이 u 이거나 S2m·E3c 회의)의 참석자, 참석 인원 ≤ peerMaxMeetingSize(10)
  제외: 본인, 참석 > 10명 회의만으로 엮인 사람, CC·단체(bulk) 수신만 있는 사람, 사적·광고 판정 메시지(정규화에서 이미 빠짐)
동료 c 의 지표:
  units = |{u | c ∈ peers_of(u)}| ; shared_effort_min = Σ effort(u) ; roles = 관계 꼬리표별 횟수
  projects = c 와 함께한 단위업무의 과제(분 내림차순 상위 3) ; first·last = 함께한 단위업무 근거 첫·마지막 날짜
  internal = 사람 사전 internal(사내 도메인) ; 외부는 개인이 아니라 도메인 계급(고객사·협력사·그 밖)으로 묶는다
정렬: shared_effort_min 내림차순 → units 내림차순 → who_key 사전순. 화면 상위 peersTopN(20), 나머지 '그 밖 n명'
```

- 팀 묶음 `peers[]`(TEAM §2.3.1)의 `units`·`shared_effort_min` 은 이 값이다(scope·peer_key 는 TEAM 빌더가 사람 사전으로 계산). `peers_external` 은 도메인 계급별 **사람 수**.
- '사람 사전에 주소가 없는 사람'은 팀 묶음에서 빠지고 `quality.reasons` 에 `peer_unresolved:<수>`(TEAM §2.3.3).

### 4.6 온톨로지 그래프 · 연관도 · 연관 업무 추천

#### 4.6.1 노드와 관계(닫힌 어휘, 결정 메모 §10.5)

| 노드 | 키 | 무리(색) | 모양 |
|---|---|---|---|
| 과제 P | 과제 키(레지스트리 ID·제안 ID·`UNC`) | 업무(파랑) | 둥근 사각형 |
| 역할 업무 R | role_id | 업무 | 원(큼) |
| 단위업무 U | unit_id | 업무 | 원(작음) |
| 문서 D | fam_key | 산출·도구(청록) | 사각형 |
| 앱 A | app_id | 산출·도구 | 마름모 |
| 동료 C | who_key(외부는 도메인 계급 노드 1개씩) | 사람(주황) | 삼각형 |

| 관계 | 방향 | 성립 조건 | 가중치 `w`(근거 수)·`h`(분) |
|---|---|---|---|
| 소속 | U→R→P | 분류 라벨(구조 간선 — 관계 어휘와 별도, 회색 가는 선) | — |
| 의뢰함 | C→U | C 가 u 의 requester | 메시지 수 |
| 보고함 | U→C | C 가 u 의 reporter | 메시지 수 |
| 산출함 | U→D | u 의 Run 중 그 문서군 초 ≥ 1분, 또는 u 의 보고 첨부·완료 후보(E2) 문서 | 저장·첨부 수, 그 문서 Run 분 |
| 사용함 | U→A | u 의 Run 중 그 앱 초 ≥ ontologyAppMinMin(15분) | Run 수, 분 |
| 함께함 | U–C | thread·meeting 관계 | 메시지·회의 수 |
| 선행함 | U→U | §4.3.2 인계 조건(역할이 같아도 됨) | 1 |
| 같은문서 | U–U | 두 단위업무가 같은 문서군을 산출함 | 공유 문서 수 |
| 같은과제 | U–U | 같은 과제(구조로 이미 보이므로 그리지 않고 연관도 계산에만) | — |

#### 4.6.2 연관도

```text
rel(u, v) = w_doc·J(D_u, D_v) + w_peer·J(C_u, C_v) + w_app·J(A_u, A_v) + w_seq·seq(u, v)
  J = 자카드 |A∩B| / |A∪B| (둘 다 비면 0)
  seq = 1   : u→v 또는 v→u 선행함
        0.5 : 같은 역할이고 리드 구간(날짜)이 겹침
        0   : 그 밖
  가중치 기본 w = {doc 0.4, peer 0.3, app 0.1, seq 0.2} (합 1.0, report.ontology.weights)
  값은 소수 4자리 half-up 로 저장(결정성), 화면은 소수 2자리
```

골든(시제품 `relatedness`):

| 쌍 | 문서 J | 동료 J | 앱 J | seq | rel |
|---|---|---|---|---|---|
| u_a1(문서 f1·f2, 동료 w1) ~ u_a2(f2·f3, w1·w2) | 1/3 | 1/2 | 1 | 1(09-04 → 09-07, 근무일 1, 문서 공유) | **0.5833** |
| u_a2 ~ u_b1(f3, w2, 앱 eda — 설계 역할) | 1/2 | 1/2 | 0 | 1(09-16 → 09-17) | **0.55** |
| u_a1 ~ u_b1 | 0 | 0 | 0 | 0 | 0 |

#### 4.6.3 연관 업무 추천

단위업무 u 를 고르면 다른 단위업무 v 를 rel 내림차순(동률 v 의 시작 시각 → unit_id)으로 보이되 rel ≥ ontologyMinRel(0.25) 만, 최대 5개. 각 추천에 **종류**를 붙인다(첫 번째로 맞는 것):

| 종류 | 조건 | 화면 문구 | 행동 |
|---|---|---|---|
| 같은 일 의심 | 같은 역할 ∧ rel ≥ sameWorkRel(0.6) ∧ 리드 구간 겹침 또는 seq = 1 | "같은 일이 둘로 나뉘었을 수 있습니다" | [합치기 질문 만들기] → 확인 큐 Q12 응답 형식 `must_link`(WORKTIME §2.7)로 worklog 에 기록 |
| 이어진 일 | seq = 1 | "앞뒤로 이어진 일입니다(인계)" | — |
| 참고할 일 | 다른 과제 ∧ 문서 J > 0 | "다른 과제에서 같은 문서를 썼습니다" | — |
| 관련 일 | 그 밖 | "같은 사람·도구를 공유합니다" | — |

#### 4.6.4 그래프 범위(그리기 대상)

- 중심 과제 1개(기본 = 선택 달 투입 최대 과제, 사용자가 바꿈). 그 과제의 R·U 전부(U 가 ontologyMaxUnits(40) 를 넘으면 투입 상위 40 + '기타 n' 노드), 바깥 고리의 D·A·C 는 연결 가중치(Σ h, 같으면 Σ w) 상위 ontologyTopN(12) + 무리별 '기타 n'.
- 다른 과제와의 관계는 바깥쪽 '연관 과제' 칩으로: 과제 간 rel = 과제 단위로 모은 D·C·A 집합의 위 식(seq 제외, 가중치 재정규화 0.5·0.375·0.125), 상위 3.
- 좌표 규칙은 §8.4 CH-P13.

### 4.7 Agentic 매칭과 새 니즈

#### 4.7.1 카탈로그

팀 레지스트리 `agents[]`(TEAM §3.10): `{id(AG…), name, axis, desc, step_types[], inputs[], outputs[], keywords[]}`. 저장소 기본 레지스트리는 중립 예시만 둔다(결정 메모 §10.5). 카탈로그가 비면 매칭 절은 '에이전트 목록이 없습니다 — 팀 레지스트리를 받으면 채워집니다'와 니즈 후보만 보인다.

#### 4.7.2 항목(단계 유형 단위)

한 사람의 모든 RoleWorkflow 에서 단계 유형 c 마다 항목 하나:

| 필드 | 정의 |
|---|---|
| `type` | c |
| `label` | c 를 가진 역할들의 코파일럿 단계 라벨 중 가장 많이 쓰인 것(동률: 그 역할 투입 큰 쪽), 없으면 한글명 |
| `occ_week` | c 의 Run·점 개수 / 그 사람이 투입한 ISO 주 수 |
| `freq` | `주 3회 이상`(occ_week ≥ 3) · `주 1~2회`(≥ 1) · `월 몇 회`(occ_week × 4.345 ≥ 1) · `드묾` |
| `io` | `"{디지털\|대면} 입력·{정형\|비정형} 출력"` — D·S 플래그(§4.8) |
| `apps` | c 의 Run 앱 범주 한글명 상위 2(카탈로그 범주), ≤ 30자 |
| `ws` | c 가 나오는 역할 업무 최대 4개 `"{과제 ID\|NONE} {기능 한글명}"`(역할 투입 내림차순) |
| `units` | c 가 나오는 단위업무 ID 목록 |
| `related_min` | c 의 Run 분 합(실측 — 점 단계는 그 점이 속한 단위업무 투입이 아니라 0) |

#### 4.7.3 규칙 사전 점수(코파일럿 답이 없거나 검증용)

```text
rule_score(a, item) =
    0.5 · [item.type ∈ a.step_types]
  + 0.2 · [a.inputs 토큰 ∩ item 입력 토큰 ≠ ∅]      # 입력 토큰: io 의 '디지털/대면', 앱 범주, 앞 단계 유형 한글명
  + 0.2 · [a.outputs 토큰 ∩ item 출력 토큰 ≠ ∅]     # 출력 토큰: 단계 유형 한글명, 확장자군 이름(표·문서·발표·코드…)
  + 0.1 · [a.keywords 토큰 ∩ item 단위업무 제목 토큰 ≠ ∅]   # 토큰 = WORKTIME §4.1 raw_tokens, 부분 문자열 일치 tok_sim > 0
rule_grade = 상(≥ gradeHigh 0.8) · 중(≥ gradeMid 0.5) · 하(> 0) · 없음(0)
```

#### 4.7.4 매칭 확정

- 코파일럿 `agentic_match` 답(`m[{a, fit, why}]`)이 있으면 그 등급을 쓰고, 규칙 등급과 **2단계 이상 차이**(상↔하, 상/중↔없음)면 `disagree` 표식(화면에 '규칙 판정과 다름')을 단다. 코파일럿이 카탈로그에 없는 코드를 답하면 브리지 검증에서 이미 버려진다(COPILOT §8.6).
- 답이 없으면 규칙 등급(꼬리표 `규칙`).
- 결과 행: `{agent_id, step_type, grade, by, why_ai, why_rule[], roles[], units[], related_min, disagree}`. 사람 단위 에이전트 요약 = 단계별 최고 등급, 관련 투입 = 등급 ≥ 하 인 단계의 `related_min` 합(**같은 Run 분을 두 에이전트가 함께 갖는 것은 막지 않되 사람 합계에서는 한 번만** — '중복 포함' 표기).
- 팀 묶음 `agentic.matches[]` = (agent_id, role_id, step_type, grade, units) 로 펼친 것(TEAM §2.3.1). 단계 `agent_grade`(§4.2.2) = 그 단계 유형의 최고 등급.

#### 4.7.5 새 니즈

| 출처 | 조건 | 내용 |
|---|---|---|
| AI | 코파일럿 답의 `need`(이름·로직·입력·출력) | 그대로, 꼬리표 `AI` |
| 규칙 | 단계 유형 c 가 `freq` ∈ {주 3회 이상, 주 1~2회} ∧ D = 1 ∧ 서브에이전트 단계 판정 ≥ 조건부 ∧ c 에 등급 ≥ 중 인 에이전트 없음 | 이름 = "{한글명} 자동화", 로직 = "{apps} 로 하는 {한글명} 단계를 입력 → 출력으로 자동화", 꼬리표 `규칙`, 월 빈도 = occ_week × 4.345 |

- `need_id` = `"n_" + sha1(type + "|" + ukey(name))[:6]`(같은 니즈는 재분석해도 같은 ID). 이름이 카탈로그 이름과 ukey 로 같으면 버린다(COPILOT §8.6 validate 와 같은 규칙).
- 니즈 **등급**(코파일럿은 니즈에 등급을 주지 않으므로 출처와 무관하게 규칙으로): 상 = `freq` 가 '주 3회 이상' ∧ 그 단계 서브에이전트 최종 판정 '적합', 하 = `freq` 가 '월 몇 회'·'드묾', 그 밖 중.
- 팀 묶음 `agentic.needs[]`: `{need_id, step_type, label(이름, ≤ 40자 team_text), grade, freq_per_month(소수 1자리), units}`. 사용자가 개인 보고서에서 [팀에 올리지 않기]를 누르면 TEAM §2.5 `overrides.json` 의 `needs` 에 `drop`.

### 4.8 서브에이전트 도입 적합성 — 5기준

#### 4.8.1 단계별 통계(입력)

RoleWorkflow 의 단계 c 마다 그 역할 단위업무들의 Run·점에서:

| 통계 | 정의 |
|---|---|
| `weeks_active` | 그 역할에 투입이 있는 ISO 주 수 |
| `occ` | c 의 정리된 흔적 항목 수(collapse 후 Run 개수 + 점 개수) |
| `digital_share` | c 의 분 중 L3·L4 귀속 분의 비율(점 단계: 근거가 디지털 메시지면 1.0, `offline` 표식이면 0) |
| `structured_share` | c 의 Run 이 다룬 문서군 중 정형 확장자군(`xls`·`txt`·`code`) 비율 — 또는 같은 문서군이 그 역할 단위업무 3개 이상에 반복(반복 양식) 하면 정형으로 친다. 점 단계는 첨부 문서군 기준 |
| `tool_class_min` | c 의 Run 분을 앱 분류의 도구 접근 점수(§3.3, 레지스트리 덮어쓰기 반영)별로 합친 `{0\|1\|2: 분}` |
| `rework_rate` | c 가 나온 단위업무 중 차수 ≥ 2 이거나 c 앞으로 되돌림 전이가 있는 비율 |
| `external_share` | c 가 나온 단위업무 중 외부 상대(고객사·협력사)가 requester·reporter 인 비율 |
| `money_hit` | c 가 나온 단위업무의 제목·근거 정제 텍스트에 `[금액]` 토큰이 있음(정제기 감사 범주 `money`) |

#### 4.8.2 점수(각 0~2)

| 기준 | 계산 | 플래그(코파일럿 D·R·B·L·S + T) | why 어휘 |
|---|---|---|---|
| **REP 반복성** | 2: occ / weeks_active ≥ 1(주 1회 이상) · 1: occ / (weeks_active / 4.345) ≥ 1(월 1회 이상) · 0 | R = (REP = 2) | `repeat_weekly` · `repeat_monthly` |
| **IO 입출력 정형성** | D + S, D = (digital_share ≥ 0.8), S = (structured_share ≥ 0.5) | D, S | `digital_io` · `structured_input` |
| **TOOL 도구 접근** | `tool_class_min` 에서 분이 가장 큰 점수(동률이면 작은 점수 — 보수적). Run 없는 점 단계는 그 유형의 기본값 | T = (TOOL = 2) — **추가 플래그(§13 요청 B-1)** | `tool_access`(**추가 어휘 — §13 T-2**) |
| **VER 검증 가능성** | 유형 기본값(§3.3) 을 rework_rate 로 깎음: < 0.3 그대로 · < 0.6 이면 min(기본, 1) · 그 이상 0 | B = (VER = 2) | `verifiable` |
| **RISK 위험**(높을수록 나쁨) | min(2, [external_share ≥ 0.3] + [money_hit] + [c ∈ {REPORT_OUT, REQ_OUT, REVIEW}]) | L = (RISK = 0) | `low_accountability` |

점수 = REP + IO + TOOL + VER + (2 − RISK) (0~10).

#### 4.8.3 판정

```text
단계 판정(규칙):
  D = 0 또는 TOOL = 0 또는 RISK = 2          → 부적합   (사람의 자리·위험 큼)
  점수 ≥ fitScore(7) ∧ TOOL = 2 ∧ RISK = 0   → 적합
  점수 ≥ condScore(5)                        → 조건부
  그 밖                                       → 부적합
역할 판정(규칙): 구간 단계의 단계 판정을 그 단계 Run 분으로 가중
  적합 단계 분 / 구간 단계 분 합 ≥ roleFitShare(0.5) → 적합
  적합·조건부 단계가 하나라도 있음            → 조건부
  그 밖                                       → 부적합
최종 = 규칙 판정과 코파일럿 의견(subagent_review.verdict: 적합·부분·부적합 → 적합·조건부·부적합) 중 더 보수적인 쪽
       (코파일럿이 더 낙관적이어도 규칙의 하드 조건을 넘지 못한다. 반대로 코파일럿이 더 보수적이면 그 의견을 따른다)
코파일럿 구성안(subs)의 단계 중 규칙 판정이 '부적합'인 단계는 화면에서 '사람 확인 필요' 로 표시한다(지우지 않음)
```

#### 4.8.4 골든(시제품 `subagent_rows`·`subagent_role`, 과제A 해석 역할, 5주)

| 단계 | REP | IO(D+S) | TOOL | VER | RISK | 점수 | 규칙 판정 | 플래그 D R B L S T |
|---|---|---|---|---|---|---|---|---|
| APP_CAE 해석 프로그램 (occ 7, 디지털 1.0, 정형 0.2, 도구 {1: 900분, 2: 30분}, 재작업 0.25) | 2 | 1 (1+0) | 1 | 2 | 0 | 8 | **조건부**(TOOL ≠ 2) | 1 1 1 1 0 0 |
| DOC_XLS 표 계산 (occ 5, 정형 0.9, 도구 {2: 480분}) | 2 | 2 | 2 | 2 | 0 | 10 | **적합** | 1 1 1 1 1 1 |
| MEET 회의 (occ 2, 디지털 0) | 1 | 0 | 0 | 0 | 0 | 3 | **부적합** | 0 0 0 1 0 0 |
| REPORT_OUT 보고 발신 (외부 상대 0.5) | 1 | 2 | 2 | 1 | 2 | 6 | **부적합**(RISK = 2) | 1 0 0 0 1 1 |
| REQ_IN 의뢰 수신 | 1 | 1 | 2 | 0 | 0 | 6 | **조건부** | 1 0 0 1 0 1 |

역할 판정: 구간 단계 분 APP_CAE 900 · DOC_XLS 480 · MEET 120 → 적합 분 480 / 1500 = 0.32 < 0.5, 적합·조건부 단계 있음 → **조건부**. 코파일럿 '적합' → 최종 조건부(규칙이 더 보수적), '부분' → 조건부, '부적합' → 부적합.

#### 4.8.5 표시와 팀 묶음

- 검토표(§6.8)는 단계마다 다섯 점수(점 막대 ●●○)·점수 합·규칙 판정·AI 의견·최종·근거(why 칩)·AI 의 확인 지점(check)을 보인다.
- 팀 묶음: `workflows[].steps[].subagent` = 단계 최종 판정, `why[]` = 위 why 어휘(§13 T-2 의 `tool_access` 추가 전에는 `tool_access` 를 싣지 않는다 — 검증 실패 방지), `agentic.subagents[]` = `{role_id, fit: 역할 최종, chain: [{step_no, proposal: 코파일럿 subs[].role(≤ 40자 team_text) 또는 규칙 '"{라벨} 단계 보조"'}]}`.

### 4.9 측정 품질 등급

개인 보고서의 '신뢰도' 카드와 팀 묶음 `quality.grade`·`reasons`(TEAM §2.3.1)는 이 함수 하나로 계산한다(팀 서버는 값을 바꾸지 않고 사람의 선택된 달 중 가장 나쁜 등급을 쓴다 — TEAM §4.5).

```text
quality_month(m) — m 안의 분석 기간 근무일 W(분석 시각 이전), 0 이면 grade = "" (판단 안 함)
  cov(axis) = (그 축의 일자 합성 상태(COLLECTION §5.3)가 ok·zero_ok 인 근무일 + 0.5 × partial 근무일) / W
              axis ∈ {mail_out, mail_in, cal, teams, pc}; pc 축 = 그날 pc_session(샘플러 또는 이벤트) 관측이 있음
  sampler_ratio = 샘플러(C1) 근거 슬롯이 있는 근무일 / W
  est_ratio     = 신뢰 low 슬롯 분 / 봉투 분 (봉투 0 이면 1.0)
  unattr_ratio  = 미귀속 분 / 봉투 분
  no_ev         = 봉투 0 이고 연차·확인된 부재가 아닌 근무일 수
  reasons = []  # 아래 검사 순서대로 해당 코드
  unreliable 조건: cov(pc) < covBad(0.5) → pc_cov_bad ; cov(mail_out) < 0.5 ∧ cov(teams) < 0.5 → comms_cov_bad ;
                   est_ratio > estBad(0.5) → estimated_bad ; 봉투 합 0 → no_envelope
  caution 조건:    cov(pc) < covLow(0.8) → pc_cov_low ; cov(mail_out) < 0.8 → mail_cov_low ; cov(teams) < 0.8 → teams_cov_low ;
                   cov(cal) < 0.8 → cal_cov_low ; est_ratio > estLow(0.25) → estimated_high ; unattr_ratio > unattrHigh(0.3) → unattributed_high ;
                   no_ev > noEvidenceDays(2) → no_evidence_days ; sampler_ratio < samplerLow(0.5) → sampler_absent
  grade = unreliable(그 조건 하나라도) / caution(그 조건 하나라도) / reliable
기간 등급 = 달 등급 중 가장 나쁜 것, reasons = 그 달들의 reasons 합집합(코드 순)
```

| 코드 | 화면 문구 |
|---|---|
| `pc_cov_bad`·`pc_cov_low` | PC 기록이 있는 근무일이 {p}% 입니다 — 에이전트가 없던 PC·기간이 있습니다 |
| `comms_cov_bad` | 메일 발신·팀즈 기록이 모두 절반 넘게 비었습니다 — 홈의 능력 표에서 막힌 출처를 확인하세요 |
| `mail_cov_low`·`teams_cov_low`·`cal_cov_low` | {축} 기록이 비어 있는 근무일이 있습니다({p}%) |
| `estimated_bad`·`estimated_high` | 근무시간의 {p}% 가 낮은 신뢰(PC 하한·흔적 창 등)로 채워졌습니다 |
| `unattributed_high` | 근무시간의 {p}% 가 업무에 묶이지 않았습니다 |
| `no_evidence_days` | 근거가 하나도 없는 근무일이 {n}일 있습니다(확인 질문 Q09) |
| `sampler_absent` | PC 사용 기록기(샘플러)가 없는 날이 많습니다 — 시간이 낮은 신뢰로 계산됩니다 |
| `no_envelope` | 이 달은 근무시간이 계산되지 않았습니다 |
| `mining_coarse` | 단계 정밀도가 낮습니다(§4.1.4) — 등급에는 영향 없음, 표시만 |

### 4.10 코파일럿 단계 입력·반영·폴백

#### 4.10.1 `ai_in` 만들기 (`lm27 report ai-items`)

모든 항목은 정제된 필드만 담는다(COPILOT §2.5 `fields` 는 단계의 `send_fields` 허용 목록 — 그 밖의 키는 브리지가 버림). `key` 는 실행이 바뀌어도 같은 대상이면 같아야 한다.

| 단계 | 항목 단위 | `key` | `group` | `fields` |
|---|---|---|---|---|
| `workflow_label` | 역할 업무 1개 | `"ws:" + role_id` | 과제 키 | `project`(레지스트리 ID·제안이면 `NEW`·미분류 `NONE`), `field`·`func`(어휘 코드), `steps`[[`S{no}`, 단계 코드, 지지도 n] ≤ 8], `trans` 상위 6 [[`S{i}`, `S{j}`, n]], `tasks` 투입 상위 5 단위업무 제목(COPILOT §8.4) |
| `agentic_match` | 단계 유형 1개(§4.7.2) | `"ag:" + type` | `""` | `type`·`label`·`freq`·`io`·`apps`·`ws` (COPILOT §8.6) |
| `subagent_review` | 역할 업무 1개 | `"sa:" + role_id` | 과제 키 | `project`, `role`(코파일럿 역할 한 줄, 없으면 `"{분야}·{기능}"`), `steps`[[`S{no}`, 단계 라벨, 단계 코드, `"D1 R1 B0 L1 S1"`]] (COPILOT §8.7) — T 플래그는 §13 B-1 반영 뒤 `"… T1"` |
| `review_text` | 주 1개·달 1개 | `"review:week:2026-W40"`·`"review:month:2026-09"` | `""` | `kind`·`period`·`facts`·`peers`·`edges`(달만) (COPILOT §8.5) |

- `review_text` 의 `facts`(≤ 25): `[F{n}, 상태, 단위업무 제목, 과제 ID, 기능 한글명]`. 상태 = `완료`(finished) → `시작`(started, 끝나지 않음) → `진행`(continuing, 기간 alloc 상위) → `보류`(OPEN 이고 기간 alloc 0 이며 20근무일 넘게 열림) 순으로 채우고, 같은 상태 안은 기간 alloc 분 내림차순 → unit_id. 동료 `peers` ≤ 8: `[동료k, 함께 한 단위업무 수]`(k 는 이 질의 번호, `peers_map` 은 메모리에서 who_key 로 — COPILOT §8.5). 달 `edges` ≤ 12: 온톨로지 관계 중 그 달 활동 단위업무가 끝점인 것의 가중치 상위를 `[E{n}, 출발 라벨, 관계, 도착 라벨]`(라벨은 과제 ID·역할 '분야·기능'·단위업무 제목·문서는 확장자군 이름(`표 계산 문서`)·앱 범주·`동료k` — 문서 이름·사람 이름은 보내지 않는다).
- **시간·MM 은 보내지 않는다**(COPILOT B1·G-B8): `steps` 의 세 번째 값은 지지도(건수)이지 분이 아니다. `freq` 는 등급 문구이지 시간이 아니다.

#### 4.10.2 `ai_out` 반영

| 단계 | 반영 대상 | 규칙 |
|---|---|---|
| `workflow_label` | `Step.label/desc/label_by`, `RoleWorkflow.ai_role/ai_summary` | 답의 `s` 코드로 단계를 찾는다(번호가 바뀌면 — 재분석으로 단계 구성이 달라지면 — 내용 키가 달라져 브리지가 다시 묻는다. 그 사이에는 같은 단계 **코드**의 이전 라벨을 쓰고 `label_by = rule_pending`) |
| `agentic_match` | §4.7.4 | `need` 는 §4.7.5 |
| `subagent_review` | §4.8.3 최종 판정·구성안·주의점 | `subs[].steps` 의 S 코드 → 현재 단계 번호 |
| `review_text` | 리뷰 `ai` | `refs` 의 F·E 번호 → 사실 행. 하이라이트 옆에 프로그램이 숫자(그 사실의 투입 h·리드)를 붙인다 |

#### 4.10.3 폴백 — 한 벌

`ai_out` 이 없거나 항목이 없으면 **브리지 단계 정의의 `fallback()`** 을 그대로 부른다(`lm27.bridge.stages.REGISTRY[stage].fallback(item, ctx, why="no_ai_out")`). 단계 모듈은 임포트만으로 세션·전송·파일 쓰기를 하지 않아야 한다(§13 요청 B-2 — 임포트 무부작용 관문). 폴백 결과는 `by = "rule"`. 같은 규칙을 보고서 쪽에 다시 쓰지 않는다(한 벌, RP3).

---

## 5. 로컬 앱 화면 (A)

### 5.0 공통 틀

#### 5.0.1 배치

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ LoadMonitor27  로컬 전용 · 외부 전송 없음                   [PC1 · 데스크톱]  [작업 1 ⟳]    │  ← 머리(h1 24px)
│ ( 홈 ³ )( 수집 )( 분석 )( 개인 보고서 )( 팀 ¹ )( 설정 )                                   │  ← 상단 가로 pill 메뉴
│ 기간 2026-09-01 ~ 2026-10-04 · 기준 10-04 18:00 · 분석 10-05 10:15(자동 선택) · AI 112 · 규칙 8 │  ← 머리 띠(분석 결과가 있을 때)
├──────────────────────────────────────────────────────────────────────────────────────────┤
│  화면 본문(최대 폭 1280px, 좌우 여백 24px — 폭 < 600px 이면 16px)                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **pill 메뉴**는 `<nav aria-label="주 메뉴">` 안의 `<a href="#home">` 6개(§8.2.1). 현재 화면은 `aria-current="page"`. 숫자 배지(³)는 그 화면의 '다음 할 일' 중 막힘·위험 등급 건수(§5.7). 폭이 좁으면 pill 줄이 가로로 스크롤된다(줄바꿈하지 않음 — 순서 기억).
- **작업 표시**: 실행 중 작업이 있으면 오른쪽 위 `[작업 1 ⟳]` 버튼 → 서랍(§8.2.7)에 작업 목록·진행 막대·최근 메시지(`text_ko`)·[중지].
- **머리 띠**는 §2.4.3 의 기간 출처와 라벨 출처 비율(§3.5)을 한 줄로. 경고(달력 불일치·UTC 의심·보고서 판 다름)가 있으면 띠 아래 노란 알림 줄(§8.2.8).
- 모든 화면은 처음 열릴 때 필요한 API 를 한 번 부르고, 작업이 끝나면(§2.3.5 표의 '성공 뒤') 다시 읽는다. **버튼을 누르는 순간 서버가 파일을 다시 읽는다**(화면 메모리의 옛 판단으로 '보낼 결과가 없다'고 말하지 않게 — LM24 교훈).

#### 5.0.2 상태 표시 어휘

| 상태 | 아이콘 | 글자 | 색 토큰(§8.1) |
|---|---|---|---|
| 정상·가능 | ✓ (`#i-ok`) | 가능 / 정상 / 완료 | `--st-good` |
| 주의·잠정 | ! (`#i-warn`) | 불가(잠정) / 주의 / 일부 | `--st-warn` |
| 위험·확정 | ✕ (`#i-bad`) | 불가(확정) / 실패 / 측정 불충분 | `--st-bad` |
| 미확인 | ? (`#i-unknown`) | 미확인 | `--ink-muted` |
| 해당 없음 | – | 해당 없음 | `--ink-muted` |
| 진행 중 | ⟳ (`#i-run`) | 진행 중 | `--blue` |

상태 색은 언제나 아이콘·글자와 함께 쓴다(색만으로 구분 금지, §8.5).

#### 5.0.3 빈 상태

각 카드는 자료가 없을 때 그 이유와 다음 행동 한 줄을 보인다. 예: 개인 보고서 — "아직 분석 결과가 없습니다. [분석] 화면에서 기간을 정해 실행하세요." / 팀 대기열 — "보낼 묶음이 없습니다. 분석을 마친 뒤 [팀 묶음 만들기]를 누르세요." / 능력 표 — "이 번들에는 아직 PC 기록이 없습니다. [수집]을 누르면 이 PC 부터 기록합니다."

#### 5.0.4 문구 규칙

1. 순서: 무엇이 됐는지 → 무엇이 남았는지 → 프로그램이 스스로 무엇을 할지(COPILOT §13 원칙과 같음).
2. 사용자에게 시키는 일은 로그인·붙여넣기·확인 질문 응답·버튼 누르기뿐. 파일 압축 풀기·폴더 지우기·재설치 요구 금지. '개발자에게 보내 주세요' 금지(회사 PC 자료는 반출할 수 없다 — LM24 교훈).
3. 원문·사람 이름·경로·계정을 문구에 넣지 않는다(파일 위치는 ROOT 상대 경로 `out\personal\…` 로만).
4. 성공 경로에 `[!]`·'오류' 낱말 금지.
5. 수치는 §3.1 표시 함수만.

### 5.1 홈

#### 5.1.1 구성(위에서 아래로)

1. **다음 할 일** 카드(§5.7) — 상위 8건, 등급 순. 각 줄: 아이콘·제목·이유 한 줄·행동 버튼. [모두 보기]는 서랍.
2. **수집 현황** 카드 — 요약 줄 + 커버리지 히트맵(CH-H01, 최근 `ui.homeCoverageDays` = 35일) + 축별 근무일 커버리지 % 막대 5개(메일 받음·메일 보냄·일정·팀즈·PC).
3. **PC × 출처 능력 표**(CH-H02).
4. **최근 분석** 카드 — `current.json` 이 있으면 KPI 미니 타일 5개(이번 달 MM·로드율·초과 h·미귀속 %·측정 품질 배지)와 [개인 보고서 열기]. 없으면 빈 상태.
5. **팀** 카드 — 레지스트리 판·받은 시각, 대기열(승인 대기·실패·보냄), 마지막 팀 서버 도달 결과 문구(TEAM §2.9 표), [팀 화면].

#### 5.1.2 수집 현황 요약 줄

`마지막 수집 10-05 09:02(PC1) · PC 3대(정상 2 · 기록 끊김 1) · 최근 30근무일 커버리지 메일 보냄 97% · 팀즈 80% · PC 100% · 가장 최근 빈 날 10-02(팀즈 — 팀즈 창 숨김)`.

- '기록 끊김' = 그 PC 에이전트 `heartbeat` 가 `agent.heartbeat_stale_s`(600s) 넘게 멈춤(지금 이 PC) 또는 그 PC 마지막 내보내기 이후 7일 넘게 그 PC 에서 [수집]이 없음(다른 PC — "그 뒤 기록은 PC1 에 남아 있음, PC1 에서 [수집]하면 들어옴", TEAM §1.7).

#### 5.1.3 PC × 출처 능력 표 — 열과 해당 여부

| 열 묶음 | 키(pc.json `capabilities.<키>`) | 열 이름 | 해당하는 PC 역할(TEAM §1.5 `roles`) |
|---|---|---|---|
| 메일 | `mail.com` · `mail.index` · `mail.owa` · `mail.copilot` · `mail.import` | Outlook 앱 · 검색 색인 · Outlook 웹 · Copilot 조회 · 반입 파일 | `mail_local`(com·index) · `account_backfill`(owa) · `copilot`(copilot) · 모두(import) |
| 일정 | `cal.com` · `cal.index` · `cal.owa` · `cal.import` | 〃 | 〃 |
| 팀즈 | `teams.uia` · `teams.web` · `teams.copilot` | 팀즈 창 읽기 · 팀즈 웹 · Copilot 조회 | `teams_window` · `account_backfill` · `copilot` |
| PC | `pc.sampler` · `pc.events` · `pc.files` · `pc.mru` · `pc.recent` · `pc.git` · `pc.compute` | 사용 기록기 · 이벤트 로그 · 폴더 파일 · Office 최근 문서 · 최근 항목 · git · 연산 감지 | `pc_usage` |
| 환경 | `env` · `edge_cdp_policy` · `web_login` · `copilot_connector` · `copilot_env` · `bundle_location` · `team_server_reach` | 실행 환경 · Edge 자동화 정책 · 웹 로그인 · Copilot 커넥터 · Copilot 등급·모드 · 번들 위치 · 팀 서버 도달 | 모두(env·bundle·team) · `account_backfill`·`copilot`(나머지) |

- 칸 값 = `verdict`(TEAM §1.5 — 가능·불가(잠정)·불가(확정)·미확인). 그 PC 역할에 해당하지 않으면 `해당 없음`(측정하지 않은 칸을 '불가'로 그리지 않는다). `pc.json` 에 키가 없으면 `미확인`.
- 칸 안: 상태 아이콘 + 글자(좁으면 아이콘만, 툴팁에 글자). 툴팁·펼침: 사유 코드 → §5.8 문구, 측정값 요약(`value` 의 숫자 — 예 '색인 메일 30일 812건', 'UIA 줄 214'), 최근 10회 `history` 를 작은 네모 10개(오래된 → 최근, 상태 색 + 아이콘 없이 툴팁), 마지막 측정일.
- 행 머리: PC 라벨(`label_user` 또는 `label_auto`), 종류(데스크톱·노트북·VDI·클라우드), 역할 칩, '이 PC' 표시.
- 마지막 행 **계정 합성**: 축(메일 받음·보냄·일정·팀즈)별 최근 30근무일 커버리지 % 와 그 축의 최선 출처(예 '메일 보냄 97% — Outlook 앱(PC1)·Outlook 웹(클라우드PC)').
- 표 아래 '되는 사람/안 되는 사람' 설명 문장(규칙): 막힌 칸마다 대체 경로를 하나씩 — 예 "PC2 의 Outlook 앱은 새 Outlook 전용이라 읽을 수 없습니다(R-NEWOL). 이 날들은 클라우드PC 의 Outlook 웹이 채웁니다(할 일 owa-2026-09 대기)." 대체 경로는 COLLECTION §6.1 배정 규칙의 `want_src`·`want_pc` 를 그대로 문장으로 바꾼다.

#### 5.1.4 커버리지 히트맵 데이터

`GET /api/collect/coverage?from&to` → `{"axes": ["mail_in","mail_out","cal","teams","pc"], "days": [{"d": "2026-10-02", "wd": true, "hol": false, "s": {"mail_in": "ok", "mail_out": "ok", "cal": "ok", "teams": "blocked", "pc": "ok"}, "why": {"teams": ["R-UIAEMPTY"]}, "src": {"teams": [["teams.uia", "blocked"], ["teams.web", "not_attempted"]]}}]}`. 일자 합성 상태 = COLLECTION §5.3 '출처 중 최선 값'(Copilot `zero_ok` 는 다른 출처의 근거 없음을 덮지 못함 — COPILOT §8.1 예외). `pc` 축은 그날 pc_session 관측 유무(`ok`/`not_attempted`).

#### 5.1.5 `HomeModel`

```json
{"pc": {"label": "PC1", "kind": "desktop", "roles": ["pc_usage","mail_local","teams_window"], "is_this": true},
 "collect": {"last": {"at": "2026-10-05T09:02:00+09:00", "pc": "PC1", "rc": 0, "state": "done",
                      "new": {"pc_session": 1440, "pc_file": 31, "mail": 54, "cal": 6, "teams": 88}},
             "pcs": {"total": 3, "ok": 2, "stale": 1}, "bundle_mb": 41.2},
 "coverage": {"from": "2026-09-01", "to": "2026-10-05", "ratio30": {"mail_in": 0.97, "mail_out": 0.97, "cal": 1.0, "teams": 0.8, "pc": 1.0},
              "last_gap": {"d": "2026-10-02", "axis": "teams", "reasons": ["R-UIAEMPTY"]}},
 "matrix": {"cols": [{"key": "mail.com", "group": "메일", "label": "Outlook 앱"}],
            "rows": [{"pc": "PC1", "kind": "desktop", "this": true, "roles": ["pc_usage"],
                      "cells": {"mail.com": {"verdict": "가능", "applies": true, "reasons": [], "summary": "받은편지함 지평선 2025-09-01~",
                                             "hist": ["ok","ok","fail","ok"], "last": "2026-10-05"}}}],
            "account": [{"axis": "mail_out", "ratio30": 0.97, "best": ["mail.com@PC1", "mail.owa@클라우드PC"]}],
            "explain": ["PC2 의 Outlook 앱은 …"]},
 "next_actions": [],
 "analysis": {"run_id": "20261005-101500-3fa2", "month": "2026-09",
              "kpi": {"mm": "0.99", "load_pct": "107", "ot_h": "10.0", "unattr_pct": "5", "quality": "reliable"}},
 "team": {"registry": {"version": 7, "fetched_at": "2026-10-03T09:00:00+09:00"}, "outbox": {"pending": 1, "approved": 1, "failed": 0, "sent": 4},
          "reach": {"result": "timeout", "target": "primary", "text_ko": "응답이 없습니다 — 다른 망(클라우드PC·재택)이거나 방화벽이 막고 있을 수 있습니다"}}}
```

### 5.2 수집

#### 5.2.1 구성

1. **수집 실행** 카드: [수집](기본, `collect --auto`) · [탐침만] · [기간 다시 수집](시작·끝 날짜 입력 → `recollect`). 실행 중이면 단계 목록(탐침 → PC 기록 → 메일·일정(로컬) → 팀즈(로컬) → 백필(백필 PC 만) → 반입·수동 → 내보내기 → 커버리지 다시 만들기 → 대기 묶음 전송)과 단계별 상태(§5.0.2)·처리 수·사유. 끝나면 결과 요약: kind 별 새 레코드 수, 격리 세그먼트 수, 탐침 판정이 바뀐 칸('Outlook 웹: 불가(잠정) → 가능'), 남은 할 일 수, 대기 묶음 전송 결과.
2. **이 PC** 카드: 라벨(직접 이름 붙이기, 로컬 전용) · 종류(추정값 + [맞음] 확정) · 수집 역할 칩(켜고 끄기 — `POST /api/pc/roles`) · 에이전트 상태(구현 py/ps, 마지막 틱, 작업 이름 `LM27-<inst8>`, 정상/멈춤) + [에이전트 복구] · 번들 위치 탐침(TEAM §1.5 `bundle_location` 사유 문구).
3. **번들 현황** 카드: PC 별 표 — 라벨 · 종류 · 처음/마지막 방문 · 마지막 내보내기 · 세그먼트 수 · MB · 에이전트 상태 · 이동 준비 결과. 도착 점검 결과(TEAM §1.12 문구 그대로, 누락 세그먼트 표). 용량 경고(상위 소비처). [이동 준비](확인 대화상자: "이 화면을 닫고 이동 시험 창을 엽니다. 창에 '[완료]'가 나오면 폴더를 옮기세요.") · [다른 번들 합치기](폴더 경로 입력).
4. **커버리지 원장** 카드: CH-H01(기간 선택 최대 92일) + 출처별 셀 표(주 단위 행 × 출처 열: `n`·`n_minute`·`n_date`·상태) + **할 일(todo)** 표(COLLECTION §6: 대상 기간·축·원하는 출처@PC·사유·시도 이력·상태 — 이 PC 역할에 배정된 것은 굵게).
5. **수동 업무 기록** 카드(§5.2.4).
6. **반입 폴더** 카드: 반입 폴더 위치(ROOT 상대), 대기 파일 수(EML·CSV·ICS), 마지막 반입 결과. 안내 "웹·앱 어디서도 못 읽는 기간은 Outlook 에서 내보낸 파일을 이 폴더에 넣으면 다음 [수집]에서 읽습니다".

#### 5.2.2 수집 결과 읽기

화면은 수집 명령의 단계 결과 파일(COLLECTION §8.4 `stage_result_<stage>.json`)과 작업 이벤트를 읽는다. 파일 위치는 `lm27.paths.collect_stage_results(run)` 하나로 정한다(COLLECTION 의 `report\` 표기는 TEAM §1.1 배치에 맞춰 `data\derived\collect\<run_id>\` 로 옮기도록 §13 요청 L-1).

#### 5.2.3 `rc` → 화면 문구

| collect rc | 머리 문구 | 본문 |
|---|---|---|
| 0 | 수집을 마쳤습니다 | 새 기록 {n}건. 남은 할 일 {k}건은 해당 PC 에서 [수집]하면 이어 받습니다 |
| 2 | 일부를 수집했습니다 | 끝내지 못한 단계: {단계}({사유}). 다음 [수집]이 이어 읽습니다(커서 보존) |
| 1 | 수집을 끝내지 못했습니다 | {사유 문구}. 이미 받은 기록은 저장했습니다. 다시 [수집]을 누르면 남은 것부터 합니다 |

#### 5.2.4 수동 업무 기록

| 입력 | 형 | 규칙 |
|---|---|---|
| 날짜 | date | 기본 오늘, 분석 기간 밖도 허용 |
| 시작·끝 | HH:MM ×2 (선택) | 둘 다 있으면 구간(끝 > 시작, 자정 넘김 불가 — 둘로 나눠 입력) |
| 시간 | 0.25~16 (선택) | 구간이 없을 때 필수. 0.25 단위 |
| 종류 | 선택 | `업무`(work) · `외근·출장·현장`(offsite) · `오프라인 지시 받음`(instr) · `오프라인 보고함`(report) · `부재`(absence) · `업무 아님`(exclude) — WORKTIME §2.7 `Man.kind` |
| 과제 | 선택 | 레지스트리 과제 + 제안 과제 + '모름' |
| 분야·기능 | 선택(선택 사항) | 레지스트리 어휘 |
| 관련 문서·대화 | 선택 | 최근 문서군·대화 목록(로컬 해석 제목)에서 고름 → `ref`/`key` 로 저장(이름이 아니라 키) |
| 메모 | 글 ≤ 200자 | 저장 전 정제(PRIVACY `sanitize`) — 화면에 "저장할 때 개인정보·금액은 자동으로 가려집니다" |

- 저장: `POST /api/worklog` → `manual` 레코드(COLLECT_PC §10 `worklog` 열)를 이 PC 세그먼트로(번들 잠금). 저장 후 "다시 분석하면 반영됩니다 — [빠른 재분석]".
- 목록: 최근 30건(날짜·종류·시간·과제·메모 정제본). **삭제** 대신 [취소 기록]: 같은 `id` 를 가리키는 `retract` 수동 레코드를 덧붙인다(세그먼트 불변 — §13 요청 L-2: 로더가 retract 된 기록을 빼고 읽도록).

### 5.3 분석

#### 5.3.1 구성

1. **분석 실행** 카드: 기간(시작·끝 날짜 + 빠른 선택 `이번 달`·`지난달`·`최근 3개월`(기본, `report.defaultRangeMonths` = 3)·`올해`), 기준 시각(기본 지금 — 미래 불가), [AI 분석 사용] 체크(이 PC 역할에 `copilot` 이 없으면 끄고 "이 PC 는 Copilot 역할이 아닙니다 — 규칙 분류로 분석합니다. 클라우드PC 에서 분석하면 AI 라벨이 붙습니다"), [분석 실행].
2. **진행** 카드(실행 중): 단계 목록(§5.3.2)·처리 수·남은 수·예상(브리지 진행 이벤트 그대로)·[중지]. Copilot 문구(COPILOT §13 BR-*)가 오면 카드 위 알림 줄로(같은 코드는 한 번).
3. **Copilot 상태** 카드(이 PC 역할에 `copilot` 이 있을 때): 방식(자동·직접 붙여넣기·꺼짐) · 계정 등급(premium·basic·unknown) · 웹 노출 여부(엄격 규칙 적용 중) · 마지막 탐침 결과 · 보정 한도(입력·답 글자) · [분석용 Edge 창 앞으로](로그인 필요할 때).
4. **직접 붙여넣기** 카드(대기 묶음이 있을 때 — COPILOT §10.5 그대로): 상단 배지 `Copilot: 직접 붙여넣기 방식 · 남은 묶음 {k}개`, 묶음 표(순번·단계 한글명·항목 수·글자 수·상태·[복사]·[답 붙여넣기]), 답 상자(여러 답 한꺼번에 가능), 반입 결과 표. [복사]는 `POST /api/bridge/manual/copy` 응답의 글을 `navigator.clipboard.writeText` 로(127.0.0.1 은 보안 문맥이라 허용) — 실패하면 글 상자를 열어 사용자가 직접 선택·복사.
5. **분석 이력** 카드(§5.3.4).
6. **결과 요약** 카드(현재 결과): 단계별 라벨 출처(AI·붙여넣기·규칙 건수), 시간 코어 감사(버린 건수 — 시각 불명·미래 시각·사적·광고), 경고(달력 미확인 연도·UTC 의심·`mining_coarse`), 확인 질문 수(열림·응답), [개인 보고서 열기].

#### 5.3.2 단계 목록

분석 파이프라인(분석 파이프라인 명세 소관)이 `data\derived\analysis\<run_id>\run_status.json` 에 쓰는 단계 상태를 그대로 보인다. 이 화면이 기대하는 형(§13 요청 A-1):

```json
{"schema": "lm27.runstatus/1", "run_id": "20261005-101500-3fa2", "from": "2026-09-01", "to": "2026-10-04",
 "as_of": "2026-10-04T18:00:00+09:00", "started": "…", "ended": "…", "state": "done|partial|failed|running",
 "stages": [{"id": "load", "name_ko": "기록 읽기", "state": "done", "counts": {"records": 51234}, "rc": 0, "reason": null, "resumable": false},
            {"id": "normalize", "name_ko": "정리·병합"}, {"id": "classify", "name_ko": "분류(규칙)"},
            {"id": "ai:task_label", "name_ko": "AI 업무 이름·분류"}, {"id": "time", "name_ko": "근무시간·단위업무"},
            {"id": "mining", "name_ko": "워크플로우 계산"}, {"id": "ai:workflow", "name_ko": "AI 단계 이름·매칭·검토"},
            {"id": "review", "name_ko": "리뷰 사실"}, {"id": "ai:review_text", "name_ko": "AI 리뷰 문장"},
            {"id": "report", "name_ko": "보고서 만들기"}]}
```

`state` ∈ `pending · running · done · partial · failed · skipped`, `skipped` 의 `reason` 예: `no_copilot_role`·`ai_off`·`web_exposed`(BR-WEB-BLOCK). `partial` 은 `resumable=true` 와 함께 "다음 분석이 남은 것부터 이어 합니다".

#### 5.3.3 분석 rc → 문구

| 결과 | 문구 |
|---|---|
| 성공 | "분석을 마쳤습니다. 개인 보고서를 이 결과로 바꿨습니다." |
| 부분(코파일럿 일부 미완) | "분석을 마쳤습니다. AI 이름 붙이기 {n}건은 규칙 이름으로 임시 표시했고, 다음 분석에서 이어 묻습니다." |
| 거부 — 달력 미확인 연도 | "{연도}년 공휴일 달력이 확인되지 않아 분석하지 않았습니다(MM 분모가 틀어질 수 있음). 팀 레지스트리를 받으면 다시 시도합니다 — [레지스트리 받기]" |
| 거부 — 보존 법칙 실패 | "계산 검사(근무시간 보존)에 실패해 결과를 만들지 않았습니다. 이전 결과를 그대로 보여 줍니다. 오류 기록은 이 PC 의 `data\logs\` 에 남았습니다." (WORKTIME §2.8 — 코드 결함, 화면은 숨기지 않고 이전 결과 유지) |
| 실패 — 기타 | "분석을 끝내지 못했습니다({단계}: {사유}). 이전 결과를 그대로 보여 줍니다." |

#### 5.3.4 분석 이력

표: 실행 ID(앞 8자) · 기간 · 기준 시각 · 분석 시각 · 상태 · AI 비율 · 보고서 판 · 현재 표시. 행 동작: [이 결과 보기](`current.json` 을 explicit 로) · [보고서 다시 만들기](`report_build`) · [내보내기]. 보관: 분석 결과 폴더는 `report.analysisKeep`(10)개까지 두고 그보다 오래된 것은 분석 파이프라인이 정리한다(현재 표시 중인 것은 지우지 않음).

#### 5.3.5 `GET /api/analysis/run/<run_id>` 응답

`{"status": <run_status.json>, "labels": {"task_label": {"ai": 112, "manual": 0, "rule": 8, "pending": 0}, "workflow_label": {…}, "agentic_match": {…}, "subagent_review": {…}, "review_text": {…}}, "time_audit": {"격리_시각불명": 0, "미래시각_폐기": 2, "사적·광고_시간근거제외": 141}, "warnings": [{"code": "utc_suspect", "text_ko": "…"}], "queue": {"open": 3, "answered": 11}}`

### 5.4 개인 보고서

로컬 앱의 '개인 보고서' 화면은 §6 의 구성 전부를 같은 렌더러(`web/app/report.js`)로 보인다. 데이터 출처만 다르다: 로컬 앱 = `/api/report`·`/api/report/unit/*`·`/api/report/day/*`, 자기완결 HTML = 데이터 섬(§9.4). 로컬 앱에서만 되는 것: 확인 질문 응답, [팀에 올리지 않기], [합치기 질문 만들기], 내보내기, 근거 증거 줄 전체(HTML 은 상한까지).

### 5.5 팀

#### 5.5.1 팀 서버 주소(팀원 쪽)

| 요소 | 동작 |
|---|---|
| IP 칸 · 포트 칸 | 현재 `team.server_host`·`team.server_port`. 저장 전 검증: 포트 1~65535 정수, IP 는 `ipaddress.ip_address` 통과 + `team.allow_public_host=false` 면 사설 IPv4(10/8·172.16/12·192.168/16)·루프백만, 호스트 이름 불가(TEAM §7.1). 잘못되면 저장하지 않고 칸 아래 빨간 글자로 이유 |
| [연결 확인] | `POST /api/team/ping` → TEAM §2.9 `hello()` 판정 문구 그대로(ok·other_lm·lm24·other_app·timeout·refused·dns), 걸린 ms. `ok` 면 서버 이름·판·레지스트리 판·pepper_id 일치 여부 |
| 대체 주소 목록 | `host:port` 줄 단위 편집(최대 5). 각 줄 [확인]. 순서 = 시도 순서 |
| [기본값으로] | `10.115.147.68:9310` 으로 **정확히** 되돌림(TEAM §7.1 — 기본값 바이트 고정 관문) |
| 업로드 토큰 | 마스킹된 상태 `설정됨/없음` + [변경](입력 상자 — 응답·화면에 값을 다시 보이지 않음, `data\keys\secrets.json`) |
| 내 표시 라벨 | `team.self_label`(≤ 20자, 저장 전 `check_team_label` — 실패 사유 표시. 실명 입력 허용 여부는 TEAM 미결 2) |
| 구성원 ID | 레지스트리 `members` 목록에서 고름(선택) |
| 단위업무 제목 | `label`(기본) / `generic` 라디오 + 설명 "generic 은 모든 제목을 '<분야>·<기능> 단위업무 #n' 으로 바꿔 보냅니다" |
| 미상 프로그램 이름 제안 | `team.share_unknown_apps`(기본 끔) |
| 자동 전송 | `team.auto_send`(기본 끔) + 설명 "끄면 기간마다 처음 한 번 미리보기에서 [보내기]를 눌러야 합니다" |

#### 5.5.2 팀 묶음 대기열·미리보기

- [팀 묶음 만들기]: 기간(기본 = 현재 분석 결과 기간) → `team_build` 작업 → 끝나면 미리보기 열기.
- **대기열 표**(TEAM §2.8 상태): 기간 · 만든 곳(`built_on` PC 라벨) · 만든 시각 · 크기 · sha 앞 12자 · 상태(승인 대기·보내는 중·다시 시도 대기(다음 시각)·보냄·실패·인증 필요·다른 서버·내보냄·전달 확인·대체됨) · 마지막 오류 문구 · 행동([미리보기]·[보내기]·[파일로 내보내기]·[치우기]·[다시 시도]).
- **미리보기**(TEAM §2.7 — 같은 바이트를 읽어 sha 대조 후):
  1. 요약: 월별 MM·영역별 분·단위업무 수·동료 키 수·니즈 수.
  2. **가림 표**: 단위업무 행마다 제목(보낼 값)·역할·투입 h·등급 + [제목 가림]·[세부 가림]·[되돌리기](TEAM §2.5). 니즈·매칭·서브에이전트 행마다 [빼기]. 표 위 한 줄: "시간 수치(근무시간·업무별 분)는 가릴 수 없습니다 — 빼면 개인과 팀 합계가 달라집니다. 업무를 통째로 숨기려면 [세부 가림]을 쓰세요."
  3. 금지 내용 검사 결과: `0건`(통과) 또는 경로·코드 목록(값은 보이지 않음 — TEAM §2.4).
  4. 원문 JSON 보기(같은 바이트, 접힘 기본, 고정폭 14px, 줄바꿈).
  5. sha256 앞 12자·크기, blockers(있으면 [보내기]·[파일로 내보내기] 비활성 + 사유).
  6. [보내기](승인 + 전송) · [승인만](다음 [수집] 때 자동 전송 — 클라우드PC 처럼 서버가 안 닿는 곳에서).
- 가림을 바꾸면 다시 빌드(새 sha) — 화면은 "가림을 바꿔 묶음을 다시 만들었습니다(이전 묶음은 대체됨)".

#### 5.5.3 이 PC 에서 팀 서버 운영

팀장 PC(또는 팀 공용 PC)에서만 쓰는 카드. 접힘 기본, 제목 `이 PC 를 팀 서버로 쓰기`.

| 요소 | 동작 |
|---|---|
| 받는 주소 | `team_server.bind_host` — 선택 목록: `모든 인터페이스(0.0.0.0)` + 이 PC 의 IPv4 목록(`socket.getaddrinfo(socket.gethostname(), None, AF_INET)` + 루프백) |
| 포트 | `team_server.bind_port`(기본 9310) |
| 저장소 위치 | `team_server.store_dir`(비면 `%LOCALAPPDATA%\LoadMonitor27\teamserver`), 서버 이름 `display_name` |
| 토큰 | 업로드 토큰·관리 토큰 설정(sha256 만 저장 — TEAM §3.2), `read_requires_token` 체크 |
| [시작] | `team_server` 분리 작업. 실패하면 TEAM §3.4 `diagnose_port` 결과(kind 별 문구·[대체 포트 N 으로 시작]·[다시 시도]) |
| 상태 | "내 서버" 증명(TEAM §3.3 — instance_id·pid 대조)되면 `가동 중 · http://<IP>:<포트> (팀원에게 알릴 주소)` 목록, 오늘 업로드 수, 마지막 취합 세대·상태, 외부 요청 수 |
| [중지] | 내 서버일 때만(`/api/shutdown` 로컬). 남의 프로세스는 끄지 않는다(TEAM §3.4) |
| [방화벽 진단] | TEAM §3.14 결과 문구 그대로 |
| [대시보드 열기] | `http://127.0.0.1:<port>/` 새 탭 |
| 경고 | ROOT 가 개인 번들 폴더면 "팀 서버는 옮기지 않는 별도 설치 폴더에서 운영하세요 — 이 폴더를 옮기면 서버가 멈춥니다"(TEAM §3.1) |

#### 5.5.4 레지스트리

판·받은 시각·출처(서버·공유폴더 파일), 과제 수·에이전트 수·달력 판, [지금 받기](`registry_fetch` — `If-None-Match`). 받지 못하면 "레지스트리 v7(10-03 받음) 사용 중"(TEAM §3.10).

### 5.6 설정

#### 5.6.1 묶음

| 묶음 | 키 접두 | 비고 |
|---|---|---|
| 근무 프로필 | `time.window.*`, `time.tzOffsetMin` | 표준창·점심·저녁·야간·반차·요일 |
| MM·초과 | `mm.*` | 분모 정의(근무일/달력 평일 — 사용자 확인 항목 D1), 초과 기준(window/daily8h — D2), 추정 부재 |
| 시간 추론(고급) | `time.envelope.*`, `time.attrib.*`, `time.queue.*`, `episode.*` | ★ 미보정 표식(WORKTIME §8.1). 기본 접힘 |
| 수집 | `collect.*`, `probe.*`, `agent.*`, `bundle.*`, `move.*` | |
| 개인정보 | `privacy.*` + 정제 감사·시험대·광고 의심 큐(§5.6.3) | |
| Copilot | `bridge.*` | 클라우드PC 에서만 의미가 있다는 안내 |
| 팀 | `team.*`(주소는 팀 화면에서) | |
| 보고서 | `report.*`, `team_report.*`(서버 쪽 — 팀 서버 PC 에서만 표시) | |
| 화면 | `ui.*` | |
| 보정 | WORKTIME §8.3 보정 보고 | §5.6.4 |

#### 5.6.2 설정 줄

각 줄: 한글 이름 · 키(작은 고정폭) · 값 입력(형에 맞는 컨트롤: 수 → number, 불 → 스위치, 열거 → 라디오/선택, 시각 범위 → 두 시각, 목록 → 줄 편집) · 기본값 · ★ 미보정 배지 · [기본값] · 검증 오류 글자. 값은 `PUT /api/settings` 로 보내고 서버가 **단일 설정 레지스트리**로 검증한다: 미등록 키 → 거부, 형 불일치 → 거부(저장 안 함) + 이유. 설정 파일에 이미 잘못된 값이 있으면 화면 위에 `config_warnings` 목록(기본값으로 동작 중).

설정 레지스트리 항목이 화면에 필요로 하는 메타(§13 요청 G-1): `group`, `label_ko`, `help_ko`(한 줄), `type`, `default`, `range`/`choices`, `uncalibrated`(★), `secret`(값 비표시), `scope`(`personal`·`team_server`), `restart`(바꾸면 화면 서버 재시작 필요 — `ui.port`).

#### 5.6.3 개인정보(PRIVACY §15.5)

- **정제 감사 표**: 기간·출처별 가린 범주 건수, 버린 행 사유 건수, 사적·광고 판정 건수, 경로별 `ad_partial` 비율, 에이전트 `no_key` 건수(`privacy_audit` 세그먼트 합계).
- **정제 시험대**: 입력 상자 → `POST /api/privacy/testbench`(메모리만, 저장·로그 없음) → 전후 비교와 걸린 범주. 오탐이면 [허용 패턴 후보로] → `privacy.allow_patterns` 후보(검증 후 저장).
- **광고 의심 큐**: 정제 제목 + [차단]·[허용].

#### 5.6.4 보정

WORKTIME §8.3 `calibration_report.json` 을 표로: 키 · 현재값 · 후보값 · J(목적 함수) · 봉투 h 변화 · 등급 분포 변화 · 표본 날 수. [적용]은 사용자가 누를 때만(자동 적용 금지), 적용한 키는 '보정됨(날짜·J)' 배지.

### 5.7 다음 할 일 카탈로그

`lm27/ui/nextactions.py: next_actions(state) -> list[NextAction]`. 등급 순서 **막힘(분석·전송 불가) → 위험(자료 손실·오판 위험) → 향상(정확도) → 정보**, 같은 등급 안에서는 코드 순, 같은 코드는 대상 키 순.

```python
@dataclass
class NextAction:
    code: str            # N01…
    level: str           # block | risk | improve | info
    title_ko: str; why_ko: str
    action: dict | None  # {"label": "[수집]", "goto": "#collect", "api": "POST /api/collect/run", "body": {...}}
    target: str          # 대상 키(PC 라벨·기간·qid 묶음 등) — 같은 것을 두 번 띄우지 않게
```

| 코드 | 등급 | 조건 | 제목 | 행동 |
|---|---|---|---|---|
| N01 | block | 분석이 '달력 미확인 연도'로 거부됨 | {연도}년 공휴일 달력이 필요합니다 | [레지스트리 받기] |
| N02 | block | 이 PC 의 번들 위치가 쓰기 불가(`R-BUNDLE-READONLY`) | 이 폴더에 쓸 수 없습니다 | 설명(쓰기 가능한 위치로 옮기기) |
| N03 | block | 팀 묶음 상태 `wrong_server`·`auth_needed`·`failed` | 팀 묶음을 보내지 못했습니다 | [팀 화면] |
| N04 | risk | 이 PC 에이전트 멈춤(heartbeat stale) 또는 미설치 | 이 PC 의 사용 기록기가 멈췄습니다 | [에이전트 복구] |
| N05 | risk | 도착 점검 누락 세그먼트 | {PC} 의 기록 {n}개가 복사되지 않았습니다 | 설명(TEAM §1.12 문구) |
| N06 | risk | 다른 PC 의 마지막 내보내기가 7일 넘음 | {PC} 기록이 {d}일째 들어오지 않았습니다 | 설명("그 PC 에서 [수집]") |
| N07 | risk | 이 PC 역할에 `account_backfill`·`copilot` 이 있고 `web_login` 이 `불가` 이며 사유 `R-LOGIN` | Outlook 웹·Copilot 로그인이 필요합니다 | [분석용 Edge 창 앞으로] |
| N08 | risk | 확인된 수집 결손이 새로 생김(`blocked_confirmed` 새 항목) | {출처} 를 이 계정에서 쓸 수 없습니다 | 대체 경로 안내(반입 폴더 등) |
| N09 | improve | 이 PC 에 배정된 todo `open`·`assigned` 가 있음 | 백필 할 일 {k}건 | [수집] |
| N10 | improve | 직접 붙여넣기 대기 묶음 | Copilot 붙여넣기 {k}묶음 남음 | [분석 화면] |
| N11 | improve | 이번 주 노출 확인 질문(WORKTIME §7.3, 응답 안 함) | 확인 질문 {n}건 | [개인 보고서 › 확인 질문] |
| N12 | improve | 마지막 수집(번들 manifest 최신 gen 시각)이 현재 분석의 기준 시각보다 24시간 넘게 뒤 | 분석이 최근 수집보다 오래되었습니다 | [분석 실행] |
| N13 | improve | 확인 질문에 응답했지만 아직 재분석 전 | 응답 {n}건이 아직 반영되지 않았습니다 | [빠른 재분석] |
| N14 | improve | 레지스트리 없음 또는 `team.registry_refresh_h` × 2 넘게 못 받음 | 팀 레지스트리를 받지 못했습니다 | [지금 받기] |
| N15 | improve | 승인 대기 팀 묶음 | 팀 묶음이 승인을 기다립니다 | [미리보기] |
| N16 | info | `config_warnings` 있음 | 설정 {n}개가 잘못되어 기본값을 씁니다 | [설정] |
| N17 | info | 번들 위치 경고(OneDrive·네트워크·긴 경로·공간 부족) | 번들 위치 주의 | 설명 |
| N18 | info | ROOT 아래 브라우저 프로필 흔적(TEAM §1.10) | 폴더 안에 브라우저 프로필이 있습니다 | 설명 |
| N19 | info | 오늘 [수집]을 안 했고 마지막 수집이 근무일 2일 넘게 전 | 최근 수집이 {d}일 전입니다 | [수집] |

### 5.8 사유 코드 → 화면 문구

COLLECTION §4.2 의 사유 코드 뜻은 그쪽 소유이고, 화면 문구(짧은 이름 + 사용자 행동/프로그램 행동)는 이 표가 소유한다(`lm27/report/vocab.py: REASON_UI`).

| 코드 | 짧은 이름 | 화면 문장(프로그램이 하는 일 포함) |
|---|---|---|
| `R-NEWOL` | 새 Outlook 전용 | 이 PC 는 새 Outlook 만 있어 앱으로 메일을 읽을 수 없습니다. 이 기간은 백필 PC 의 Outlook 웹이 채웁니다 |
| `R-NOPROF` | Outlook 프로필 없음 | Outlook 프로필이 없어 앱 경로를 건너뜁니다 |
| `R-WIZARD` | Outlook 시작 마법사 위험 | Outlook 을 자동으로 띄우면 멈출 수 있어 앱 경로를 건너뜁니다. Outlook 을 직접 한 번 열어 두면 다음 수집에서 다시 확인합니다 |
| `R-DIALOG` | Outlook 대화상자 | Outlook 에 열린 대화상자가 있어 읽지 못했습니다. 닫아 두면 다음 수집에서 다시 시도합니다 |
| `R-CLM` | 실행 제한 | 이 PC 의 보안 설정이 스크립트 일부를 막습니다. 되는 경로만 씁니다 |
| `R-OMG` | 주소 읽기 보호 | 발신자·수신자 주소는 이 PC 에서 읽지 않습니다(보호 경고 방지). 제목·시각은 읽습니다 |
| `R-ELEV` | 권한 불일치 | 관리자 권한으로 실행된 창과 Outlook 이 달라 붙지 못했습니다. 일반 권한으로 다시 실행하세요 |
| `R-ONLINE` | 온라인 모드 | Outlook 이 온라인 모드라 이 PC 색인에 메일이 없습니다. 웹 경로가 채웁니다 |
| `R-HORIZON` | 동기화 기간 밖 | 이 날짜는 이 PC 의 Outlook 보관 기간 밖입니다. 웹 경로가 채웁니다 |
| `R-SUBFOLDER` | 하위 폴더 많음 | 정리 규칙 폴더의 메일이 많습니다 — 모든 폴더를 읽고 색인으로 건수를 맞춰 봅니다 |
| `R-STALE` | 오래된 사본 | 이 PC 의 Outlook 사본이 최근 것이 아닙니다 |
| `R-NOIDX` · `R-IDXPOLICY` · `R-IDXPAUSED` | 색인 꺼짐·막힘·일시정지 | Windows 검색 색인을 쓸 수 없습니다. 다른 경로로 채웁니다 |
| `R-EDGEPOL` | Edge 자동화 막힘 | 회사 정책이 Edge 자동 연결을 막습니다. 웹 수집은 건너뛰고, Copilot 은 직접 붙여넣기로 바꿉니다 |
| `R-LOGIN` | 로그인 필요 | 분석용 Edge 창에서 회사 계정으로 한 번 로그인해 주세요. 로그인하면 이어서 합니다 |
| `R-CA` | 접근 정책 차단 | 회사 접근 정책이 이 PC 의 웹 접속을 막습니다 |
| `R-NOLIC` · `R-NOCONN` | Copilot 조회 불가 | 이 계정의 Copilot 은 메일·팀즈를 조회할 수 없습니다. 조회는 건너뛰고 분석은 계속합니다 |
| `R-TZ` | 시간대 주의 | 이 PC 의 시간대가 다릅니다(클라우드PC UTC 등). 시각은 근무 시간대로 바꿔 계산합니다 |
| `R-OFFICE` | 지원 종료 Office | 오래된 Office 라 일부 경로가 불안정할 수 있습니다 |
| `R-UIAEMPTY` | 팀즈 창 숨김 | 팀즈 창이 최소화·숨김이라 읽지 못했습니다. 팀즈 웹 백필이 채웁니다 |
| `R-UIAELEV` | 팀즈 창 권한 | 관리자 권한 창은 읽을 수 없습니다 |
| `R-NOADDR` | 내 주소 미확인 | 내 메일 주소를 확인하지 못해 받는 메일의 직접/참조 구분이 '모름' 입니다 |
| `R-NOEVT` | 이벤트 로그 권한 | 이 PC 의 일부 이벤트 기록을 읽을 권한이 없습니다 |
| `R-CAP` | 상한 도달 | 한 번에 읽을 수 있는 양을 넘어 일부만 읽었습니다. 다음 수집이 이어 읽습니다 |
| `R-BUDGET` | 시간 예산 소진 | 정해진 시간 안에 끝내지 못했습니다. 다음 수집이 이어 합니다 |
| `R-TRANSPORT` | 일시 실패 | 일시적인 연결·프로그램 오류입니다('불가' 판정에 쓰지 않음). 다음에 다시 시도합니다 |
| `R-BUNDLE-*` | 번들 위치 | TEAM §1.5 표의 사유별 문장 |
| `R-TEAM-*` | 팀 서버 도달 | TEAM §2.9 hello 판정 문장 |
| (그 밖·모름) | 기타 | 코드 그대로 + "다음 수집에서 다시 확인합니다" |

---

## 6. 개인 보고서 (B)

### 6.1 구성과 기간 선택

- 둘째 줄 pill 메뉴(절 메뉴): **요약 · 업무 트리 · 워크플로우 · 리뷰 · 동료 · 연관 그래프 · Agentic · 서브에이전트 · 확인 질문 · 분류 · 근거**. 해시 `#report/<절>`(자기완결 HTML 에서도 같은 해시로 이동).
- **달 선택** pill 줄(요약·업무 트리·워크플로우·Agentic·서브에이전트 절 위): 분석 기간의 달들 + `기간 전체`. 기본 = 기준 시각(`as_of`)의 달(기간 밖이면 기간의 마지막 달). 선택은 브라우저 `localStorage` 의 `lm27.report.month`(실패해도 기본값으로 동작 — 읽기·쓰기는 try/catch).
- 각 절 머리에 그 절의 기간과 '부분월(c/W 근무일)' 표식.
- 변형 표시: 자기완결 HTML 의 머리에 `전체판(로컬 전용)` 또는 `가림판` 배지(§3.6).

### 6.2 요약

#### 6.2.1 KPI 카드(선택 달 — '기간 전체'면 기간 합)

| 카드 | 큰 값 | 작은 줄 | 산식(모델 필드) | 누르면 |
|---|---|---|---|---|
| 이번 달 MM | `0.99 MM` | `158.0h ÷ 160h(근무일 20일 × 8h)` + 부분월이면 `부분월 10/14까지` | `fmt_mm(months[m].env_min, months[m].denom_min)` — 분모 정의 문장 `denominator.text` 를 툴팁에(WORKTIME §6.1, 사용자 확인 항목 D1) | 근거 › 월 |
| 로드율 | `107%` | `가용 18.5일 기준(연차 1 · 반차 0.5)` | `fmt_pct(env_min, avail_min)` — `avail_min` = `std_day_min × avail_days`(WORKTIME §6.4, 오늘은 표준창 경과 비율이라 소수일 수 있음)를 정수 분 half-up. 가용 0 이면 `—` + `가용 0`. 팀 묶음의 `load_pct` 는 TEAM §2.3.2 식(`covered_workdays − absence_days`)이라 분석 당일에는 개인 값과 조금 다를 수 있다(미결 R-Q4) | 근거 › 월 |
| 초과 근무 | `10.0h` | `연장 4.0 · 야간 2.0 · 휴일 4.0` (+ `휴가 중 근무 0.3` 이 있으면) | `mm.overtimeBasis` 에 따라 `overtime_window_min` 또는 `overtime_daily8h_min`. 기준 이름을 작은 글자로(`근무창 밖 기준`·`일 8시간 초과 기준`) | 리뷰 › 초과 원인 |
| 미귀속 비율 | `5%` | `근무 중 미분류 8.0h — 일반 앱 3.0 · 소통 2.0 · 회의 1.5 · PC 밖 1.0 · 미상 0.5` | `fmt_pct(unattr_min, env_min)` (= 1 − 귀속률, WORKTIME §5.4) | 업무 트리 › 근무 중 미분류 |
| 신뢰도 | 배지 `신뢰`·`주의`·`측정 불충분` | `관측 78% · 추정 17% · 미분류 5% · A·B 업무 72% · 분류 신뢰 82%` | §4.9 등급, §3.4 O/I/X 비율, 등급 A·B 단위업무 alloc 분 / 귀속 분, **분류 신뢰** = 라벨 `level` 이 `confirmed`·`high` 인 단위업무 alloc 분 / 단위업무 alloc 분(HIERARCHY §11.1 — 정수 분 표에서) | 펼침: 사유 문구(§4.9 표) + 분류 미정 비중 |
| 단위업무 | `완료 4 · 진행 3` | `새로 시작 5 · 미착수 의뢰 1 · 중앙 리드 3.2영업일` | 그 달 `finished`·`continuing`·`started`·`unstarted` 수(§4.4.2), 완료 업무 영업 리드 중앙 | 리뷰 › 월간 |

#### 6.2.2 요약 차트

1. **월별 투입(CH-P02)** — 기간의 달마다 꼬리표 누적 막대 + 1MM 기준선. 막대 위 `0.99`.
2. **업무 영역 구성(CH-P04)** — 선택 달 영역별 비중 가로 100% 막대 + 미귀속 회색 빗금.
3. **단위업무 등급 분포(CH-P17)** — A·B·C·D·E·O·M 별 alloc 분(Z 는 0 이라 건수만 옆 글자).
4. **주요 단위업무 표** — 선택 달 alloc 상위 10: 제목(라벨 출처 꼬리표)·과제·역할·투입 h(관측/추정 막대)·리드·등급·상태.
5. **한 줄 요약**(규칙 문장, 3개까지): ① 최대 영역 비중 ② 초과가 가장 많았던 단위업무 ③ 측정 품질 사유 첫 번째. 예 "이번 달 투입의 64%가 개발 프로젝트였습니다." "초과 근무 10.0h 중 6.5h 가 '전원부 검증' 에 쓰였습니다."

### 6.3 업무 트리와 수준별 워크플로우

#### 6.3.1 트리 표

| 열 | 내용 |
|---|---|
| 이름 | 들여쓰기 4단: 업무 영역(색 칩) → 과제(레지스트리 이름, 제안 과제는 점선 테두리 `제안` 배지, 개인 과제 `내 과제`, 예약 과제 `P-99xx` 는 '<영역> — 과제 미지정' 행 — HIERARCHY §1.3·§12.5, `AX 연계` 꼬리표) → 역할 업무(`분야 · 기능` 이름 — 코드는 툴팁, 코파일럿 역할 한 줄은 작은 글자 + 출처 꼬리표) → 단위업무(제목 + 등급 배지 + 상태) |
| 선택 달 MM | §3.1 `fmt_mm(분, denom)` — 영역·과제·역할은 소속 단위업무 alloc 합 |
| 기간 MM | 달별 MM 의 합(WORKTIME §6.1 — 기간 평일로 나누지 않음) |
| 투입 | h + 관측/추정 비율 막대(가로 60px, 채움 = 관측, 빗금 = 추정) |
| 단위업무 | 완료/진행/미착수 수 |
| 중앙 리드 | 완료 단위업무 영업 리드 중앙(영업일) |
| 병목 | 역할 행: 대기·작업 병목 단계 이름(없으면 빈칸, 표본 부족이면 `표본 부족`) |
| 분류 | 단위업무 행: 분류 신뢰 배지(`확인됨`·`높음`·`보통`·`낮음`·`미분류` — HIERARCHY §11.1 `level`) + [분류 고치기]·[왜?](§6.11). 영역·과제·역할 행: 소속 단위업무 투입의 `level` 분포 작은 막대(서열 5칸: 확인됨 `--seq-5` · 높음 `--seq-4` · 보통 `--seq-2` · 낮음 `--seq-1` · 미분류 흰 칸 + 1px 점선 테두리, 칸마다 툴팁 글자) |

- 맨 아래 고정 행 **근무 중 미분류**(버킷 5종 자식 행 — 일반 앱·소통·회의·PC 밖·미상)와 **미분류(UNC)** 영역(과제 없는 역할). 숨기지 않는다(RP16). 미귀속 회의 중 회의 시리즈 키가 레지스트리 과제 키워드와 맞는 것은 그 과제 행에 주석 `관련 미귀속 회의 1.5h(MM 미포함)` 만 단다.
- 정렬: 영역 = 고정 순서(DEV·MP·EXT·COM·AX·UNC), 그 안은 기간 MM 내림차순 → 키.
- 행을 누르면 오른쪽 **수준 패널**(폭 ≥ 1100px 이면 표 오른쪽 46%, 좁으면 표 아래)이 그 수준의 워크플로우를 연다. 키보드: 방향키 위아래 이동, 오른쪽 펼침, 왼쪽 접기, Enter 패널 열기(WAI-ARIA treegrid).
- 표 위 토글 `표 | 간트`: 간트(CH-P06)는 같은 계층(영역 → 과제 → 역할 행, 단위업무 막대)을 기간 전체로 보인다.

#### 6.3.2 수준 패널

| 수준 | 패널 내용 | 데이터 |
|---|---|---|
| 업무 영역 | KPI 3개(기간 MM·단위업무 수·중앙 리드) · 단계 묶음 구성(CH-P10) · 상위 병목 3(역할 이름 + 병목 단계 + 값, 누르면 그 역할 패널) · 과제 목록(MM 막대) | `workflows.domains[k]` |
| 과제 | 역할 레인 간트(CH-P09) · 역할 간 인계 표(`역할 x → 역할 y · n회 · 중앙 대기 d영업일 · 문서 공유 a · 동료 공유 b`) · 역할 구성(투입 비중 막대) | `workflows.projects[key]` |
| 역할 업무 | 코파일럿 역할 한 줄·요약 2문장(출처 꼬리표) · **프로세스 맵(CH-P07)** · 규칙 문장(§6.3.3) · 단계 표(번호·단계 라벨(AI)·유형 한글명·n·월 빈도·중앙/75% 소요·들어오는 대기·작업 비중·관측 비율·Agentic 등급·서브에이전트 판정) · 단위업무 목록(제목·시작→끝 근거 코드·등급·리드·투입·병행도·정리된 흔적 `의뢰 수신 → 해석 → 표 계산 → 보고`) · '드물어 뺀 단계' 한 줄 | `workflows.roles[role_id]` |
| 단위업무 | 단위업무 타임라인(CH-P08) · 경계 근거(시작·끝 코드·시각·등급 — 추정이면 이유 문장) · 투입 내역(L1~L7 분, O/I) · 대기 목록과 최장 대기 · 단계로 설명된 투입 비율 · 연관 업무 추천(§4.6.3) · 동료 · 문서·앱 · [근거 보기](§6.10.3) | `workflows.units[unit_id]`, `/api/report/unit/<id>` |

#### 6.3.3 역할 워크플로우 규칙 문장(코파일럿 없이도 항상)

순서대로 해당하는 것만(최대 4문장, 숫자는 §3.1):

1. 작업 병목: "{단계 라벨} 작업이 이 역할 투입의 {p}%로 가장 큽니다."
2. 대기 병목: "{앞 단계 라벨}을 마치고 {단계 라벨}을 시작하기까지 보통 {d}영업일을 기다립니다." (앞 단계 = 그 단계로 들어오는 전이 중 횟수 최대)
3. 되돌림: "{n}건의 단위업무에서 {뒤 단계}를 하다가 {앞 단계}로 되돌아갔습니다."
4. 표본: N < 3 이면 "단위업무가 {N}건뿐이라 병목은 판단하지 않았습니다."

### 6.4 주간·월간 리뷰

- 기간 고르기: `주간 | 월간` 토글 + 기간 목록(최근이 위). 각 기간 카드:
  1. **숫자 줄**: 근무 {h}h(정규·연장·야간·휴일) · 귀속 {p}% · 관측 {p}% · 새로 시작 {n} · 끝냄 {n} · 미착수 의뢰 {n}.
  2. **AI 요약**(출처 꼬리표; 폴백이면 `규칙` 템플릿 문장): `summary` 문단 + `highlights` 목록 — 각 하이라이트 끝에 프로그램이 붙이는 숫자 `(투입 6.5h · 리드 3.2영업일)`(refs 의 사실 행에서). 문장 안 `동료k` 는 §3.6 해석 이름으로 바뀐다.
  3. **끝낸 일** 표: 제목·과제·역할·시작→끝(근거 코드)·리드(영업일)·투입·병행도·등급·**초과 판정**(`초과` 배지 + 원인 칩 — §4.4.3 표 이름, 칩을 누르면 설명 문장).
  4. **새로 시작한 일**·**계속한 일**(투입 순)·**미착수 의뢰**(의뢰 시각·상대 — 확인 질문 Q02 링크).
  5. **리드타임 점 그림**(CH-P11, 월간만): 끝낸 일의 영업 리드를 역할별 줄에 점으로, 역할 기준 중앙(눈금)과 1.5배 문턱(점선), 초과 점은 링.
  6. **초과 근무 원인**(§4.4.4): 단위업무별 연장·야간·휴일 h 상위 5 + '업무에 묶이지 않은 초과'.
  7. **함께한 동료** 상위 5(§4.5, 그 기간만).
  8. (월간) **관계**: AI `relations` 문장 + 근거 관계(E 번호 → 그래프 간선, 누르면 연관 그래프 절이 그 간선을 강조).
  9. **다음**: AI `next` 또는 규칙(진행·시작 상태 사실 상위 2).
- 주간 카드는 기본 접힘(최근 2주만 펼침), 월간은 선택 달 펼침.

### 6.5 같이 일한 동료

- 상단 문장: "같은 단위업무에 함께 등장한 사람입니다(요청·보고·대화 2건 이상·10명 이하 회의). 이름은 이 PC 에서만 보입니다. 팀에는 가명 키로만 갑니다."
- **동료 막대(CH-P12)**: 공동 단위업무 수(기본) / 공유 투입 h 토글. 상위 20 + '그 밖 n명'.
- **표**: 이름(full: 사람 사전 이름, redacted: `동료 #k`) · 사내/외부(외부는 `[고객사:C01]` 처럼 계급 토큰) · 공동 단위업무 · 공유 투입 h · 관계(의뢰 n · 보고 n · 대화 n · 회의 n) · 함께한 과제 상위 3 · 처음~마지막. 행 펼침: 공동 단위업무 목록(제목·역할·기간·투입).
- 팀 쪽 표시 안내 한 줄: "팀 보고서에서는 이 사람이 팀원이면 팀원 라벨, 아니면 '동료-xxxx' 로 보입니다."

### 6.6 연관 그래프(온톨로지)

- **방사형 그래프(CH-P13)**: 중심 과제 선택(과제 칩 목록 — 기간 MM 순), 관계 종류 체크(의뢰함·보고함·산출함·사용함·함께함·선행함·같은문서), 바깥 노드 수(8·12·20).
- **연관 업무 추천** 목록(선택한 단위업무 기준, 없으면 중심 과제의 투입 최대 단위업무): 대상 제목 · 연관도(소수 2자리) · 종류(§4.6.3) · 근거(공유 문서 n · 공유 동료 n · 공유 앱 n · 인계) · 행동([합치기 질문 만들기] — 같은 일 의심일 때만).
- **연관 과제** 칩: 과제 간 연관도 상위 3 + 근거.
- 표로 보기: 노드 표(종류·이름·연결 수·가중치)와 간선 표(출발·관계·도착·근거 수·분).

### 6.7 Agentic

1. **매칭 격자(CH-P14)**: 행 = 에이전트(카탈로그 순, 매칭 1개 이상인 것 — [모두 보기]로 전체), 열 = 내 단계 유형(월 빈도 내림차순). 칸 = 등급(상·중·하) + 출처 꼬리표(`AI`·`규칙`) + 규칙과 다름 표식(◇). 행 끝 = 관련 투입 h(실측)·단위업무 수, 열 머리 = 빈도 문구.
2. **매칭 표**: 에이전트 · 이름 · 단계 유형 · 등급 · 근거(AI `why` + 규칙 이유 칩: `단계 유형 일치`·`입력 일치`·`출력 일치`·`핵심어 일치`) · 쓰이는 역할 · 단위업무 수 · 관련 투입 h. 표 아래 "관련 투입은 그 단계에 실제로 쓴 시간입니다. 에이전트가 대신할 수 있는 시간을 뜻하지 않습니다(중복 포함 — 같은 시간이 여러 에이전트에 걸릴 수 있음)."
3. **새 니즈** 목록: 이름 · 무엇을(로직) · 입력 → 출력 · 단계 유형 · 월 빈도 · 등급 · 출처 · 관련 단위업무 · [팀에 올리지 않기](토글, `overrides.json`).

### 6.8 서브에이전트 검토표

- 역할 업무마다 카드(투입 내림차순). 카드 머리: 역할 이름 · **최종 판정 배지**(적합·조건부·부적합) · 규칙 판정 · AI 의견(출처 꼬리표) · 판정 근거 한 줄("적합 단계 분 비율 32% — 적합 단계 '표 계산', 해석 프로그램은 도구 접근이 막혀 조건부").
- **단계 표(CH-P15)**: 번호 · 단계 라벨 · 유형 · 반복성 · 입출력 정형성 · 도구 접근 · 검증 가능성 · 위험(각 ●●○ 점 + 숫자) · 점수 /10 · 규칙 판정 · 최종 · 근거 칩(why) · 사람 확인 지점(AI `check`).
- **AI 구성안**(있으면): 오케스트레이터 한 줄(`orch`) + 서브에이전트 목록(맡을 단계 번호 → 역할 · 입력→출력 · 확인 지점), 규칙상 부적합 단계가 끼어 있으면 그 단계에 '사람 확인 필요' 꼬리표. 주의점(`risk`).
- 카드 아래 기준 설명(접힘): §4.8.2 표 요약.

### 6.9 확인 질문

- 목록: WORKTIME §7.3 의 Q01~Q18 이번 주 노출분과 HIERARCHY §11.2 의 H01~H06 이번 주 노출분(주간 상한은 각자 — `time.queue.maxPerWeek`·`hier.queue.maxPerWeek`)을 우선순위 순으로 한 목록에 섞고, 코드 머리 글자(Q·H)와 묶음 꼬리표(`시간`·`분류`)로 구분한다. 각 줄: 유형 이름 · 대상(단위업무 제목·날짜) · 영향 h · 왜 묻는지(근거 키를 로컬 해석해 '10-12 의뢰 메일 이후 보고 기록 없음') · 응답 컨트롤.
- 응답 컨트롤(유형별): Q01 = '지시받은 때'(날짜·시각) / '보고한 때' / '다른 업무와 같은 일'(같은 역할 단위업무 고르기) · Q02 = 착수 안 함 / 다른 업무에 포함 / 오프라인으로 처리함(시각·h) · Q04 = 업무 / 사적 · Q05 = 외근·출장·현장(시각) / 정정 · Q08 = 오프라인 업무(시각·업무) · Q09 = 부재 / 근무(h) · Q10·Q16 = 맞음 / 업무 아님 · Q12 = 나누기 / 합치기 · Q13 = 그 경로가 UTC 저장(시간 오프셋 설정) · Q14·Q15 = 참석함 / 불참 · Q17 = 업무 고르기(후보 3) / 개인 시간 · Q18 = 공용 문서 / 특정 업무 것 · Q03 = 끝남(시각) / 진행 중 · Q07 = 의뢰·보고 시각 · Q06 = 근무 h · Q11 = 결과 확인 시간(선택).
- H 질문 응답 컨트롤: H01 = 과제 고르기(후보 3 · 영역 일반 · 새 과제 · 업무 아님) · H02 = 규칙 과제 / AI 과제 / 그 밖 · H03 = 내 과제로 받기 / 기존 과제와 같음 / 거절 · H04 = 같다 / 다르다 · H05 = 유형(7종) · H06 = 옮길 과제. 응답은 `POST /api/hier/correction`(H03 은 `/api/hier/proposal`, H04 는 병합 또는 `never_pairs`) → HIERARCHY §11.3 수정 기록(증거 키 기준 — 재분석해도 따라간다).
- 응답 → `POST /api/queue/answer` → WORKTIME §2.7 `Man` 형 수동 레코드(증거 키 기준)를 worklog 로 → 줄에 `응답함 — 다시 분석하면 반영`. `ui.autoReanalyzeAfterAnswers`(true)면 마지막 응답 뒤 `ui.reanalyzeDebounceSec`(20초) 동안 더 응답이 없을 때 `quick_reanalyze` 작업(분류(규칙)·시간·마이닝·보고서만, 코파일럿 없음 — 3개월 약 수 초, WORKTIME G9. 분류 수정은 학습 규칙·증거 꼬리표를 바꿔 시간 결과까지 달라질 수 있으므로 분류 단계부터 다시 돈다)을 자동으로 띄운다. 끄면 다음 할 일 N13.
- 응답은 업무 ID 가 아니라 증거 키로 저장되므로 재분석 뒤에도 따라간다(WORKTIME §2.7).

### 6.10 근거 드릴다운(관측/추정 구분)

#### 6.10.1 단계

```
KPI·트리 숫자 ─▶ 월(일별 막대 CH-P03) ─▶ 날짜(날짜 원장 + 24시간 띠 CH-P16 + 구간 원장 표) ─▶ 구간 ─▶ 단위업무(업무 원장) ─▶ 증거 줄
```

어느 숫자에서 시작하든 같은 길을 따라 내려간다. 각 단계 머리에 '어디서 왔는지'(빵부스러기 `2026-09 › 09-22 › 13:00~15:00 › 전원부 검증`).

#### 6.10.2 날짜 (`GET /api/report/day/<d>`)

```json
{"d": "2026-09-22", "hol": false, "s_eff": ["09:00", "18:00"], "leave": 0,
 "ledger": {"total_min": 590, "components": [["샘플러", 560], ["샘플러다리", 30]], "deductions": [["사적차감", -30]],
            "excluded": [], "by_tag": {"regular": 480, "extended": 110}, "conf_min": {"high": 560, "mid": 30, "low": 0},
            "coverage": {"mail_out": "ok", "teams": "ok", "pc": "ok"}, "flags": []},
 "intervals": [{"a": "09:00", "b": "10:00", "tag": "regular", "basis": "샘플러", "targets": [["u_3e9a01c2d4", 60, "O"]], "note": ""},
               {"a": "10:00", "b": "10:35", "tag": "regular", "basis": "회의",
                "targets": [["B_MEET", 18, "X"], ["u_0b1c2d3e4f", 17, "I"]], "note": "대형 회의 중 다른 업무 PC 입력(0.5/0.5)"}],
 "labels": {"u_3e9a01c2d4": "전원부 검증", "u_0b1c2d3e4f": "시험 지그 설계"}}
```

- `ledger` = WORKTIME §7.4 날짜 원장, `intervals` = 구간 원장(같은 출처·귀속·등급이 이어지는 구간). 분은 정수(구간 원장의 초 → 분은 그날 표에서 최대잉여로 맞춘 값).
- 화면: 24시간 띠(CH-P16) 위에 구간 원장 표(시각·꼬리표·근거·대상·분·등급 O/I/X·비고). 빼거나 버린 시간도 줄로 보인다(사적 차감·창 밖 무자격 제외 — WORKTIME 'W26' 같은 사례).

#### 6.10.3 단위업무 (`GET /api/report/unit/<unit_id>`)

```json
{"unit_id": "u_3e9a01c2d4", "title": "전원부 검증", "title_by": "ai", "grade": "B", "status": "closed",
 "cycles": [{"no": 0, "start": {"code": "S1", "t": "2026-07-03 10:12", "estimated": false, "evidence": "e1"},
             "end": {"code": "E2h", "t": "2026-07-09 16:40", "estimated": false, "evidence": "e7", "score": 0.8}}],
 "levels_min": {"L1": 0, "L2": 60, "L3": 900, "L4": 40, "L5": 60, "L6": 200, "L7": 0}, "obs_min": 960, "est_min": 300,
 "runs": [{"type": "APP_SIM", "a": "2026-07-03 13:00", "b": "2026-07-03 17:00", "min": 240, "obs_min": 240, "apps": [["spice", 240]]}],
 "evidence": [{"id": "e1", "kind": "mail", "dir": "in", "t": "2026-07-03 10:12", "prec": "minute", "who": "김철수",
               "title": "[과제:P-0007] 전원부 검증 요청", "role": "시작 근거(S1 디지털 의뢰)"},
              {"id": "e7", "kind": "file", "op": "export", "t": "2026-07-09 16:40", "doc": "전원부_검증결과", "role": "완료 후보(E2h, 점수 0.8: 내보내기 0.3 · 최종 이름 0.2 · 조용 0.4)"}],
 "explain": "의뢰 메일로 시작해 결과 파일을 내보낸 뒤 3근무일 동안 다른 작업이 없어 그 시각을 끝으로 봤습니다(등급 B)."}
```

- `evidence[]` 는 시간 코어가 이 단위업무에 쓴 근거 키(경계·진행·문서·회의)를 번들 로더·정규화 레코드에서 찾아 **정제된 열만** 로컬 해석한 것(§3.6 `full`). 원문은 애초에 없다(PRIVACY). 상한 `report.drill.maxEvidencePerUnit`(200), 넘으면 '그 밖 n건'.
- `explain` 은 경계 코드 조합(WORKTIME §4.10.3 처리표)에서 고른 규칙 문장. 추정 경계(S2p·S2m·E2l·E3c·E3i·NEXT_REQ)면 무엇으로 추정했는지와 [확인 질문으로 바로잡기](Q01 응답 폼) 버튼.
- 자기완결 HTML(`full`)에는 단위업무별 `evidence` 를 상한까지 넣는다(§9.4). `redacted` 에는 `evidence` 를 넣지 않고 경계 코드·시각·투입 내역만.

### 6.11 분류(HIERARCHY 연동)

분류 명세(HIERARCHY §12.5)가 화면에 맡긴 요소를 이 절이 모은다. 숫자(투입·비율)는 정수 분 표에서, 라벨·제안·규칙의 상태는 분류 명세의 파일에서 읽는다(`GET /api/hier/state`). 자기완결 HTML 에서는 머리 줄과 분류 요약만 보이고 버튼은 빠진다(쓰기는 로컬 앱에서만).

1. **머리 줄**: 레지스트리 상태(HIERARCHY §3.1 `RegistryStatus` — `레지스트리 v7(10-03 받음) · 팀 과제 24 · 내 과제 2 · 예약 5`), 분류 요약 막대(단위업무 투입의 `level` 5칸 — 확인됨·높음·보통·낮음·미분류, 칸 비율 글자), AI 분류 비율(`hier_meta.ai_share`).
2. **초기 설정(코드네임 검토)** 카드 — HIERARCHY §8.1 의 표시 조건일 때만, 다른 카드보다 위: 후보 표(낱말 · 나온 묶음 수 · 주 수 · 예시 제목 3개(정제문)) + 행마다 [과제 이름(코드네임)]·[고객사 이름]·[무시], 표 아래 [이대로 진행(나머지 무시)]·[건너뛰기]. [건너뛰기] 뒤에는 카드 자리에 경고 줄 "레지스트리 없이 코파일럿을 쓰면 제목 속 과제 이름이 그대로 갈 수 있습니다"(HIERARCHY §8.1)를 남긴다.
3. **새 과제 제안** 카드 — 제안 큐(HIERARCHY §7.3): 이름 · 영역 추정(색 칩) · 단위업무 수 · 투입 h · 처음~마지막 · 출처(AI·부트스트랩·내가 만듦) · 상태. 행 동작 [내 과제로 받기](영역 고르기 + 알아볼 낱말 체크) · [기존 과제와 같음](과제 고르기) · [이름 바꾸기] · [다른 제안과 합치기] · [거절] · [거절 취소]. 레지스트리를 새로 받아 자동 대응된 제안은 알림 줄 "제안 '…' → 팀 과제 P-0021 로 연결됨"(HIERARCHY §7.6).
4. **학습한 규칙** 표 — HIERARCHY §11.4: 종류(대화방·문서·폴더·낱말·앱) · 조건(로컬 해석 — 대화방 정제 제목·문서 이름·낱말) · 결과(과제·분야·기능·유형) · 상태(active·candidate·retired·superseded) · 적중·일치·불일치 · [끄기]·[다시 켜기]·[팀 규칙으로 제안](팀장에게 전할 문구를 클립보드로).
5. **미적용 수정** 목록 — 대상 단위업무를 찾지 못한 수정 기록(HIERARCHY §11.3): 날짜 · 바꾼 값 · 대상 근거 수. 지우지 않는다(추가 전용) — "다시 수집·분석해서 대상이 돌아오면 자동으로 적용됩니다".
6. **[분류 고치기] 대화상자**(업무 트리·단위업무 패널·확인 질문에서 연다): 과제(유효 레지스트리 과제 · 내 과제 · '<영역> 일반' · 새 과제 만들기 · 업무 아님), 분야·기능·유형(어휘 **이름** 목록 — 저장은 코드), 제목(≤ 25자), 범위 라디오 `이 업무만` / `비슷한 업무도`(기본 — HIERARCHY §11.3 `similar`), [저장] → `POST /api/hier/correction` → 빠른 재분석(§6.9 와 같은 작업).
7. **[왜?]**: `UnitLabel.why` 줄(로컬 전용 — 가림판·팀에 없음), 필드별 `src`·`conf` 표, 과제 후보 `cands` 상위 3과 점수.
8. 이름 풀기: 영역·분야·기능·유형 코드는 `lm27.hier.vocab`·유효 레지스트리 어휘의 이름으로만 화면에 낸다(코드는 툴팁·CSV 코드 열). 단계 유형 코드(§3.3 `MEET` 등)와 기능 어휘 코드(`MEET`·`DOC` 등)는 이름공간이 달라 같은 철자여도 섞지 않는다(HIERARCHY §1.6 과 같은 원칙).

---

## 7. 팀 보고서 (C)

### 7.0 어디서 무엇으로

| 산출 | 위치 | 데이터 | 비고 |
|---|---|---|---|
| 팀 대시보드(살아 있는 화면) | 팀 서버 `/` (TEAM §3.12) | `GET /api/team`(team_data.json), 드릴다운 `GET /api/team/detail?person=&role=` | 같은 렌더러. 팀장·팀원이 브라우저로 연다 |
| 자기완결 팀 보고서 | `/report` → `out\gen_N\team_report.html` | 데이터 섬 = team_data + `details`(§7.8.2) | TEAM §3.9: `render_team_report(td, share=False)` |
| 공유판 | `/report/share` → `team_report_share.html` | 위에서 사람별 로드율·초과 시간 열 제거 | TEAM 관문: 제거 키가 HTML 전체 0회 |
| 팀 표 CSV(요청) | `out\gen_N\team_tables\*.csv` | §9.3.3 | §13 요청 T-5 |

팀 서버에는 코파일럿이 없다. 팀 보고서의 문장은 모두 **결정적 템플릿**(§7.4.4)이고, 단계 라벨·니즈 이름은 팀원 묶음에 실려 온 값이다.

머리: 팀 이름(레지스트리 `team.label`) · 기간(묶음들의 달 범위, 24개월 넘으면 최근 24개월 + '앞 N개월 생략') · 세대 번호·취합 시각 · 레지스트리 판·달력 판 · 경고 배지(TEAM §4.8 불변식 위반 수 — 누르면 목록).

### 7.1 KPI

| 카드 | 큰 값 | 작은 줄 | 산식(team_data) |
|---|---|---|---|
| 인원 | `8명` | `신뢰 6 · 주의 1 · 측정 불충분 1` | `people[]` 수, `quality` 별 |
| 팀 투입 | `21.4 MM`(기간) | `이번 달 7.2 MM · 미귀속 0.4 MM` | Σ_p MM(p, m) (TEAM §4.5), 이번 달 = 마지막 달 |
| 초과 근무 | `86.0h` | `연장 52 · 야간 14 · 휴일 20`(팀 합) | Σ by_tag(extended·night·holiday) — 공유판에도 팀 합계는 남는다(사람별 열만 제거) |
| 업무 영역 | `개발 62% · 양산 21% …` 상위 3 | `미분류 3%` | domains total |
| 단위업무 | `완료 41 · 진행 17` | `중앙 리드 4.1영업일` | §7.8.1 `units_stats` |
| 측정 품질 | 배지 분포 | `사람×출처 커버리지 평균 92%` | §7.7 |

### 7.2 업무 영역별 리소스(MM) 투입

1. **월별 영역 누적 막대(CH-T02)**: 달마다 영역별 MM 누적 + 미귀속(회색 빗금). 측정 불충분 사람 몫은 같은 영역 색 위에 빗금(TEAM §4.5 '합계 포함·빗금'). 막대 위 팀 MM.
2. **영역 × 사람 표**: 행 = 영역(+미귀속), 열 = 사람(정수 인덱스 순서 = 기간 MM 내림차순 → person_key), 칸 = MM(2자리) + 칸 배경 단색 순차 농도(§8.1 순차 램프, 칸 글자 대비 4.5:1 유지). 측정 불충분 열 머리 회색 + 빗금 배지. 공유판에서도 이 표는 남는다(MM 은 로드율이 아님 — TEAM 공유판 정의).
3. **영역 → 과제 펼침**: 영역 행을 펼치면 과제 행(§7.3 와 같은 값).

### 7.3 과제 × 인원

- 표: 과제(레지스트리 라벨, 제안 과제 `제안` 꼬리표, 병합된 과제는 대표로 합쳐 `병합: P-0003` 주석) · 영역 · 기간 MM · 사람별 MM 인라인 막대(같은 색 한 가지 — 사람마다 색을 주지 않는다. 막대를 사람 순 조각으로 나누고 조각 사이 2px 틈, 조각 툴팁에 이름·MM) · 단위업무 수 · 역할 수. 0.3 MM 미만 과제는 '작은 과제 n개(합 x MM)' 한 줄로 접힘(펼침 가능).
- 과제 행 펼침: 역할 업무 행(분야·기능 · 사람별 MM).

### 7.4 역할·단위업무·업무 유형 분포와 해석

#### 7.4.1 역할(분야 × 기능) 표

행 = 분야, 열 = 기능, 칸 = 팀 MM(귀속분 기준) + 단색 순차 농도 + 칸 안 비율(%). 칸을 누르면 그 (분야, 기능) 의 역할 업무 목록(과제·사람·MM). 분포 비율은 귀속분 기준이고 미귀속은 따로(TEAM §4.5).

#### 7.4.2 업무 유형 작은 배수

업무 유형(레지스트리 `vocab.activity_types` — 개발·사무·현장·PM·PL·지원 …)마다 작은 가로 막대 묶음: 영역별 MM(단색). 유형마다 같은 축 범위(비교 가능). 유형 6개 이상이어도 색을 늘리지 않는다(작은 배수 — §8.3 규칙).

#### 7.4.3 단위업무 통계

- 상태 분포(완료·추정 완료·진행·미착수는 묶음에 없음) · 등급 분포(A~E) 막대(단색 + 글자).
- **리드타임 점 그림(CH-T06)**: 영역별 줄에 완료 단위업무 영업 리드 점, 중앙 눈금. 이름 없이 점 툴팁에 `과제 · 역할 · 리드 · 투입`.

#### 7.4.4 해석 문장(결정적 템플릿)

`lm27/team/report.py: interpret(td, cfg) -> list[{code, text_ko, refs}]` — 아래 순서대로 조건에 맞는 것만, 최대 6문장. 측정 불충분 사람은 비율 계산에서 뺀다(합계 문장 TI-01 은 포함하고 "(측정 불충분 n명 포함)").

| 코드 | 조건 | 문장 |
|---|---|---|
| TI-01 | 항상 | "기간 동안 {영역}이 팀 투입의 {p}%({mm} MM)로 가장 큽니다." |
| TI-02 | 마지막 완전한 달과 그 전달이 있고, 영역 비중 변화 \|Δ\| 최대값 ≥ `team_report.shiftPp`(5%p) | "{영역} 비중이 전월보다 {d}%p {늘었/줄었}습니다({m0} {p0}% → {m1} {p1}%)." |
| TI-03 | (분야, 기능) 최대 비중 ≥ `team_report.concentrationShare`(0.4) | "{분야}·{기능} 역할에 귀속 투입의 {p}%가 몰려 있습니다." |
| TI-04 | 업무 유형 중 '사무' 비중 ≥ `team_report.officeShareNote`(0.3), 아니면 최대 유형 | "업무 유형으로는 {유형}이 {p}%입니다." |
| TI-05 | 미귀속 비중 ≥ `team_report.unattributedNote`(0.15) | "근무시간의 {p}%가 단위업무에 묶이지 않았습니다(근무 중 미분류) — 측정 품질 절을 확인하세요." |
| TI-06 | AX 연계(`ax_link`) 단위업무 비중 ≥ `team_report.axLinkNote`(0.1) | "AX 연계 표시가 붙은 업무가 투입의 {p}%입니다(개발·양산 영역에 계상)." |
| TI-07 | 완료 단위업무 ≥ 5 인 영역이 2개 이상 | "{영역} 단위업무의 중앙 리드타임이 {d}영업일로 가장 깁니다." |
| TI-08 | 측정 불충분 ≥ 1명 | "{n}명은 측정이 불충분해 비교 집계에서 뺐습니다(합계에는 포함, 빗금)." |

### 7.5 Agentic 매칭·니즈 취합

1. **에이전트 × 업무 영역 격자(CH-T07)**: 칸 = (사람 수, 단위업무 수) + 칸 농도 = 관련 투입 MM(단색 순차), 칸 안 최고 등급 글자. 행 끝 = 팀 관련 투입 MM(중복 제외 — 같은 단위업무 분은 한 번, TEAM §4.7) · 사람 수 · 역할 수. 표기 "관련 투입은 실측이며 대체 가능 시간을 뜻하지 않습니다".
2. **새 니즈 표**: (단계 유형, 이름) 묶음별 — 이름 · 단계 유형 · 사람 수 · 월 빈도 합 · 관련 투입 MM · 등급 분포(상 n · 중 n · 하 n) · 출처(AI/규칙 사람 수). 같은 단계 유형의 비슷한 이름은 **합치지 않고 나란히**(자동 이름 병합 금지 — TEAM §4.7), 단계 유형별 소계 행. 팀장 안내: "카탈로그로 올리려면 관리 화면에서 에이전트를 추가하세요."
3. **서브에이전트 적합성 분포**: 역할 업무(분야·기능)별 적합·조건부·부적합 사람 수 막대 + 제안 체인 목록(역할 · 단계 번호 → 제안 문구, 사람 수).

### 7.6 담당자별 업무 영역/과제/역할 간트(다월)

#### 7.6.1 행 계층과 피벗

- 기본(결정 메모 §10.2): **담당자 → 업무 영역 → 과제 → 역할 업무**. 피벗 토글: **업무 영역 → 과제 → 역할 업무 → 담당자**. 토글은 같은 막대를 다른 순서로 묶을 뿐 값은 같다.
- 행 = 계층 마디. 맨 아래 마디(역할 업무 또는 담당자) 행에 단위업무 막대가 놓인다. 위 마디 행에는 소속 막대들의 **요약 띠**(리드 띠 합집합 + 주 밀도 합, 같은 그리기 규칙)를 그린다(접혔을 때도 모양이 보이게).
- 기본 펼침: 행이 `team_report.ganttExpandRows`(150) 이하면 모두 펼침, 넘으면 첫 계층만 펼침. 측정 불충분 사람 행은 이름 옆 빗금 배지.
- 정렬: 담당자 = 기간 MM 내림차순 → person_key, 영역 = 고정 순서, 과제·역할 = 기간 MM 내림차순 → 키.

#### 7.6.2 막대(단위업무 하나)

TEAM §4.6 데이터(`gantt[].units[]`: `spans` 의 lead 1개, `density` 주별 분, `effort_min`·`parallel`·`grade`·`status`)를 §8.4 CH-T08 규칙으로 그린다: 옅은 **리드타임 띠** + 진한 **투입 밀도 칸**(주 단위, 고정 5단계 — 사람·과제 간 비교 가능). **막대 길이는 투입이 아니다** — 범례에 그 문장을 쓴다. 행 끝 열: `투입 h · 병행도 ×p · 리드 d일`.

#### 7.6.3 클릭 → 워크플로우 패널

막대·행(역할 업무 또는 담당자 마디)을 누르거나 포커스 후 Enter → 오른쪽 **서랍 패널**(폭 ≥ 1100px 이면 화면 오른쪽 520px, 좁으면 전체 폭 아래에서 올라옴):

1. 머리: 담당자 라벨 · 영역 칩 · 과제 · 역할(분야 · 기능) · 측정 품질 배지.
2. KPI 4: 투입 h · 단위업무 n · 중앙 리드 · 평균 병행도.
3. **프로세스 맵(CH-P07 와 같은 그림)** — 데이터 = 그 사람 묶음의 `workflows[role_id]`. 단계 라벨은 그 사람이 보낸 라벨(코파일럿 또는 규칙). 묶음에 대기·병목 필드가 있으면(§13 요청 T-3) 같은 표시, 없으면 생략.
4. 단계 표: 번호 · 라벨 · 유형 · n · 중앙 소요 · Agentic 등급 · 서브에이전트 · 근거 칩.
5. 단위업무 목록: 제목(가림이면 generic) · 시작→끝 종류 · 등급 · 상태 · 리드 · 투입 · 병행도 · 작은 간트(그 단위업무만).
6. Agentic 매칭(그 역할의 에이전트·단계·등급).
- 데이터: 대시보드는 `GET /api/team/detail?person=<person_key>&role=<role_id>`(TEAM §4.6), 자기완결 보고서는 데이터 섬의 `details["<i>|<role_id>"]`(§7.8.2). 피벗 모드에서 담당자 행을 눌러도 같은 (사람, 역할) 상세.
- Esc·[닫기]로 닫고 포커스는 누른 막대로 돌아간다. 패널이 열린 동안 해시 `#gantt/<i>/<role_id>` (뒤로 가기로 닫힘).

### 7.7 측정 품질 — 사람 × 출처 커버리지

- 표(CH-T09): 행 = 사람(라벨), 열 = 메일 받음 · 메일 보냄 · 일정 · 팀즈 · PC(축 5개) + 등급 배지 + PC 수 + 표식(달력 다름·산식 설정 다름·pepper 다름). 칸 = 근무일 커버리지 %(묶음 `quality.coverage[axis].days` 의 (ok + zero_ok + 0.5 × partial) / 합) + 상태 아이콘(≥ 0.8 ✓, ≥ 0.5 !, 그 밖 ✕).
- 행 펼침: 그 사람의 PC 표(TEAM §2.3.1 `quality.pcs` — 라벨·종류·에이전트 구현·관측일·탐침 판정 요약)와 사유 코드 문구(§4.9 표), 코파일럿 사용 여부·실패 항목 수, 확인 질문 열림/응답 수, 추정 분 비율.
- 표 위 문장: "측정 불충분 인원은 팀 합계에는 들어가지만(빗금) 평균·순위·분포 비교에서는 빠집니다. 수집이 안 된 것을 일이 적은 것으로 읽지 않기 위해서입니다."

### 7.8 `team_data.json` 에 이 문서가 요구하는 형

TEAM §4.9 의 `roles`·`activity_types`·`agentic`·`quality` 는 '…' 로 남아 있다. 렌더러가 읽는 형을 여기서 정한다(TEAM 취합기가 같은 커밋에서 채운다 — §13 요청 T-4). 모든 사람 참조는 정수 인덱스 `i`.

#### 7.8.1 필드

```json
{"roles": [{"role_id": "r_5c0d11", "project_id": "P-0007", "proposal": false, "domain": "DEV", "field": "ELEC", "function": "DESIGN",
            "total_mm": 1.42, "by_person": [[0, 0.81], [3, 0.61]], "units": 6, "lead_biz_median_min": 1530, "effort_median_min": 420,
            "subagent": {"적합": 1, "조건부": 1, "부적합": 0}}],
 "role_matrix": {"fields": ["MECH", "ELEC", "SW"], "functions": ["DESIGN", "ANALYSIS", "TEST"],
                 "cells": [["ELEC", "DESIGN", 3.1, 0.18]]},
 "vocab_names": {"field": {"MECH": "기구", "ELEC": "회로", "SW": "소프트웨어"}, "func": {"DESIGN": "설계", "ANALYSIS": "해석·분석", "TEST": "시험·검증"},
                "wtype": {"DEV": "개발", "OFFICE": "사무", "FIELD": "현장", "PM": "PM", "PL": "PL", "SUPPORT": "지원", "EDU": "교육·학습"}},
 "activity_types": {"types": ["DEV", "OFFICE", "FIELD", "PM", "PL", "SUPPORT", "EDU"],
                    "by_domain": {"DEV": {"DEV": 9.8, "OFFICE": 1.1}}, "total": {"DEV": 12.4, "OFFICE": 4.0}, "by_person": [[0, {"DEV": 1.2}]]},
 "units_stats": {"by_status": {"closed": 41, "estimated": 6, "open": 17}, "by_grade": {"A": 12, "B": 20, "C": 9, "D": 4, "E": 2},
                 "lead_points": [{"domain": "DEV", "biz_lead_min": 2360, "effort_min": 420, "project_id": "P-0007", "role_id": "r_5c0d11", "i": 0}],
                 "lead_median_by_domain": {"DEV": 1960}},
 "agentic": {"matches": [{"agent_id": "AG003", "name": "문서 초안 작성", "by_domain": {"DEV": {"people": 3, "units": 9, "related_mm": 0.42, "best": "상"}},
                          "people": 4, "roles": 5, "units": 12, "related_mm": 0.61, "overlap": true}],
             "needs": [{"step_type": "DOC_XLS", "label": "사양 비교표 자동 작성", "people": 2, "freq_per_month": 7.0, "related_mm": 0.3,
                        "grades": {"상": 1, "중": 1, "하": 0}, "src": {"ai": 1, "rule": 1}}],
             "subagents": [{"field": "ELEC", "function": "ANALYSIS", "fit": {"적합": 0, "조건부": 2, "부적합": 1},
                            "chains": [{"proposal": "결과 정리 서브에이전트", "people": 2, "step_types": ["DOC_XLS"]}]}]},
 "quality": {"excluded_from_comparison": [2],
             "matrix": [{"i": 0, "grade": "reliable", "reasons": [], "axes": {"mail_in": 0.97, "mail_out": 0.97, "cal": 1.0, "teams": 0.8, "pc": 1.0},
                         "pcs": 2, "flags": [], "copilot": {"used": true, "failed_items": 2}, "queue": {"open": 3, "resolved": 11},
                         "estimated_min_ratio": 0.08}]},
 "interpretation": [{"code": "TI-01", "text_ko": "기간 동안 개발 프로젝트가 팀 투입의 62%(13.3 MM)로 가장 큽니다.", "refs": {"domain": "DEV"}}]}
```

- 수치는 서버가 정수 분에서 계산해 마지막에 나눈 값(TEAM §4.1), JSON 에는 소수 그대로(표시는 렌더러 §3.1). `lead_points` 는 이름·제목 없이.

#### 7.8.2 자기완결 보고서의 `details`

`render_team_report` 가 팀 데이터 섬에 함께 넣는 드릴다운 사전: 키 `"<i>|<role_id>"`, 값 = TEAM §4.6 `/api/team/detail` 응답과 같은 형(`person`·`role`·`workflow`·`units`·`agentic`). 크기가 `team_report.maxDetailMb`(12MB)를 넘으면 `units[]` 를 빼고 `workflow` 만 넣으며 패널에 "단위업무 목록은 팀 대시보드에서 보세요". 공유판도 같은 `details` 를 넣되 사람별 로드율·초과 열은 원래 없다.

### 7.9 팀 서버 관리 화면(`/admin`)

TEAM §3.12 의 `/admin`(`web/team/admin.html`)은 팀장이 레지스트리를 편집하고 팀원 묶음을 관리하는 화면이다. 쓰기 API 는 관리 토큰 또는 그 PC(루프백)에서만(TEAM §3.2 `admin_token_sha256`). 의미 검증은 `lm27.hier.registry_schema.validate_registry(side="server")`(HIERARCHY §2.4·§16 X2), 운반·버전 검증은 TEAM §3.10.

| 탭(pill) | 내용 | 동작·API |
|---|---|---|
| 과제 | 표: ID · 이름 · 영역 · 상태(active·proposed·retired) · 별칭 · 키워드 · 코드네임 · `mask_name` · `copilot_desc` · 공용 문서 · `merged_into` · 최근 기간 MM(취합 결과) | 행 편집 서랍, [새 과제](ID 자동 `P-` 다음 번호, `P-99xx` 금지), [병합](대상 고르기 — 순환 검사), [퇴역]. 저장 = `PUT /api/registry`(`version` = 현재+1) |
| 어휘 | 분야·기능·업무 유형·단계 유형(코드·이름·키워드·상태, 단계 유형은 도구 접근·검증 가능성 덮어쓰기 0/1/2) | 내장 코드는 지울 수 없고 `retired` 만(HIERARCHY §1.4) |
| 에이전트 | 카탈로그 `agents[]`: ID(`AG…`) · 이름 · 축 · 설명 · 적용 단계 유형(§3.3 코드 다중 선택) · 입력 · 출력 · 핵심어 | [새 에이전트] — 팀 니즈 표(§7.5)의 행에서 [카탈로그로 올리기]를 누르면 이름·단계 유형이 채워진 새 행 |
| 달력 | 공휴일·회사 휴무(날짜 · 이름 · 종류 · 근거 URL · 확인일 — 근거 없는 항목은 저장 거부, 결정 메모 §10.3), 표준 근무일 분 | 저장 뒤 재취합 |
| 구성원 | 레지스트리 `members[]`(ID · 표시 라벨) + 서버 roster(사람 키 · 라벨 · 연결 · 퇴직) | `PATCH /api/members/<person_key>`(TEAM §3.6) |
| 제안 | 팀원 묶음의 `proposals[]` 모음: 이름 · 영역 추정 · 사람 수 · 관련 MM · 처음 받은 날 · 같은 이름(ukey) 묶음 후보(HIERARCHY §9.6 — 자동 병합 없음) | [새 과제로 등록](`adopted` 에 `{person_key, proposal_id}` 기록) · [기존 과제 별칭으로](과제 고르기) · [보류] |
| 업로드 | `/api/members` 표(TEAM §3.11): 사람 · 기간 · 받은 시각 · 사용한 달 · 판 · 품질 · 표식 | [이 기간 빼기](`drop_period`), [지금 다시 취합](`POST /api/aggregate`) |

- 동시 편집: 저장이 409 `registry_version_conflict` 면 "다른 곳에서 레지스트리를 바꿨습니다(v8) — 최신 판을 불러와 내 변경을 다시 적용했습니다. 확인 후 다시 저장하세요"(화면이 최신 판 위에 바뀐 칸만 다시 얹고, 충돌 칸은 노란 표시).
- 검증 오류는 칸 옆에 코드·한국어 문구(`bad_domain`·`reserved_id`·`dup_alias`·`cycle_merge`·`bad_holiday_source` …), 저장 버튼 비활성.
- 화면 글자는 모두 `textContent`(RP11), 표·폼은 §8.2 구성 요소. 레지스트리 JSON 원문 보기(읽기 전용)와 [JSON 내려받기]·[JSON 올리기](검증 통과 시에만 적용).

---

## 8. 디자인 시스템 (D) — LM20 언어

LM20 화면(`ui/app.py` 의 인라인 CSS, 2026-09-01 판)의 언어를 잇는다: **#f2f4f7 회색 바탕 · 흰 카드 · #e4e7eb 테두리 · #2a78d6 파랑 · 상단 가로 pill · KPI 카드 · 표 + 펼침**. 바꾼 것: 글자 크기(LM20 본문 11~13px → 본문 16px·표 14px), 흐린 글자색(LM20 `#8b929b` 는 흰 바탕 대비 3.14:1 이라 글자에는 쓰지 않음), 주황(LM20 `#e08a00` 은 흰 바탕 2.69:1 → `#c47400`), 차트를 손그림 CSS 막대에서 SVG 로.

### 8.1 토큰 (`web/common/lm27.css` 의 `:root` — 색 값은 이 파일과 업무 영역 메타 `lm27/hier/vocab.py` `DOMAIN_META` 에만, lint G-R7)

#### 8.1.1 바탕·글자·선

| 토큰 | 값 | 용도 | 대비(실측) |
|---|---|---|---|
| `--bg` | `#f2f4f7` | 페이지 바탕 | — |
| `--surface` | `#ffffff` | 카드·차트 바탕 | — |
| `--surface-2` | `#f6f8fa` | 표 머리·보조 면 | — |
| `--surface-3` | `#eef4fd` | 선택 행·활성 pill 바탕 | — |
| `--border` | `#e4e7eb` | 카드·표 테두리 | — |
| `--border-strong` | `#c9cfd8` | 입력·버튼 테두리, 축 기준선 | — |
| `--grid` | `#eef0f3` | 차트 격자(가로만) | — |
| `--ink` | `#12151a` | 본문 | 흰 바탕 18.3:1 · `--bg` 16.6:1 |
| `--ink-2` | `#3d444c` | 제목 보조·표 머리 | 흰 바탕 9.86:1 · `--surface-2` 9.26:1 |
| `--ink-muted` | `#646b75` | 보조 글자·축 눈금·단위 | 흰 바탕 5.38:1 · `--bg` 4.88:1 · `--surface-3` 4.87:1 |
| `--ink-faint` | `#8b929b` | **글자 아님** — 글자가 함께 있는 아이콘·장식선·리드 띠 테두리 | 흰 바탕 3.14:1(비글자 3:1 충족) |
| `--blue` | `#2a78d6` | 브랜드 파랑: 채움·테두리·초점 고리·차트 1번 | 흰 바탕 4.42:1(채움·큰 글자용) |
| `--blue-ink` | `#1c5cab` | 링크·활성 pill 글자·파랑 글자 | 흰 바탕 6.63:1 · `--surface-3` 6.00:1 · `--bg` 6.02:1 |
| `--blue-btn` | `#2770c7` | 주 버튼 바탕(흰 글자) — `#2a78d6` 계열을 AA 로 보정 | 흰 글자 4.97:1 |
| `--blue-wash` | `#eaf2fd` | 프로세스 맵 노드·선택 바탕 | — |
| `--danger-ink` | `#c0122f` | 위험 버튼 글자·테두리(LM20 값) | 흰 바탕 6.23:1 |
| `--focus` | `0 0 0 3px rgba(42,120,214,.45)` | 초점 고리 | — |

#### 8.1.2 상태 색(고정 — 차트 계열로 다시 쓰지 않음)

| 토큰 | 채움(아이콘·칩) | 글자 토큰 | 글자 대비 |
|---|---|---|---|
| good | `--st-good: #0ca30c` | `--st-good-ink: #1f7a1f` | 5.44:1 |
| warn | `--st-warn: #fab219` | `--st-warn-ink: #8a5a00` | 5.93:1 |
| serious | `--st-serious: #ec835a` | `--st-serious-ink: #b42318` | 6.57:1 |
| bad | `--st-bad: #d03b3b` | `--st-bad-ink: #a8071a` | 7.75:1 |

채움 색은 아이콘 모양(✓ ! ▲ ✕)과 글자 없이 쓰지 않는다(warn·serious 채움은 흰 바탕 3:1 미만 — 의도된 것, 아이콘 + 글자가 보완).

#### 8.1.3 차트 색 — 검증된 팔레트

| 계열 | 순서·값 | 검증(dataviz 팔레트 검사기, 흰 바탕 `#ffffff`, 2026-10-05) |
|---|---|---|
| **업무 영역**(범주) | DEV `#2a78d6` · MP `#c47400` · EXT `#0e8c7a` · COM `#a61b4a` · AX `#6c4fb8` · UNC `#8b929b`(중립 회색, '미분류' 글자 필수) — 색상 배정(MP 주황·EXT 청록)은 HIERARCHY §1.2 `DOMAIN_META` 를 따르고 **값만** 검증값으로(§13 요청 H-1: MP `#e08a00`→`#c47400`, COM `#8b929b`→`#a61b4a`, UNC `#c0c4cc`→`#8b929b`) | 인접 쌍(DEV→MP→EXT→COM→AX 순): CVD ΔE 최저 9.5(COM↔EXT, 녹색맹 모의), 정상 시각 최저 20.6(AX↔COM), 명도대·채도 하한 통과, 5색 모두 ≥ 3:1. HIERARCHY 원안 값은 검사기에서 실패(MP 대비 2.69:1, COM 회색 채도 0.016 — 실제 영역이 '미분류'처럼 보임, COM↔EXT 정상 시각 ΔE 12.9 < 15) |
| **근무 꼬리표**(범주) | 정규 `#2a78d6` · 연장 `#c47400` · 야간 `#6c4fb8` · 휴일 `#a61b4a` | 인접 CVD 최저 18.7, 정상 20.6, 모두 ≥ 3:1 (CSS 토큰 `--tag-regular`·`--tag-extended`·`--tag-night`·`--tag-holiday`) |
| **연관 그래프 무리**(모든 쌍) | 업무 `#2a78d6` · 산출·도구 `#0e8c7a` · 사람 `#c47400` | 모든 쌍 CVD 최저 11.0, 정상 17.0 — 모든 쌍 검사는 3색까지만 통과하므로 노드 종류(6)는 색이 아니라 **모양**으로 가른다 |
| **순차·서열**(밀도 5단계) | `--seq-1 #86b6ef` · `--seq-2 #5598e7` · `--seq-3 #2a78d6` · `--seq-4 #1c5cab` · `--seq-5 #0d366b` | 서열 검사: 명도 단조, 인접 ΔL ≥ 0.06, 밝은 끝 2.11:1(≥ 2:1), 단일 색상(색상각 폭 4°) |
| **표 칸 농도**(연속값 6구간) | 0 `#ffffff` · 1 `#eaf2fd` · 2 `#cde2fb` · 3 `#9ec5f4` · 4 `#5598e7` · 5 `#1c5cab`(흰 글자) | 칸마다 숫자를 늘 쓴다(밝은 칸 대비 보완). 글자 대비: `--ink` on 구간 1~4 ≥ 6.1:1, 흰 글자 on 5 = 6.63:1 |
| **리드 띠** | 채움 `--lead-fill #e4e7eb` + 테두리 `--lead-stroke #8b929b` 1px | 테두리 3.14:1 로 띠 경계가 보인다 |
| **미귀속** | 채움 `--unattr #c9cfd8` + 135° 빗금(`#8b929b`) | 글자 '미분류' 함께 |

- 영역 색은 CSS 에 두지 않는다: 보고서 모델·팀 데이터의 `domains[].color`(= `domain_color(code)`)를 JS 가 그대로 `fill` 에 쓴다(값 형식 `^#[0-9a-f]{6}$` 검사 후). CSS 토큰 `--dom-*` 는 만들지 않는다(두 곳 정의 금지).
- 범주 색은 **고정 순서로 배정하고 순환하지 않는다**. 영역은 6개뿐이라 넘치지 않는다. 사람·과제처럼 개수가 정해지지 않은 대상에는 색을 주지 않는다(단색 + 순서·틈·글자).
- 같은 색상(hue)이 영역 차트와 꼬리표 차트에 다른 뜻으로 쓰인다(파랑 = DEV / 정규). 두 계열은 한 차트에 함께 나오지 않고, 각 차트에 범례와 직접 라벨이 있다. 화면 한 카드 안에 두 계열 차트를 나란히 두지 않는다(요약 절의 CH-P02 와 CH-P04 는 다른 카드).
- 다크 모드는 v1 에서 지원하지 않는다(LM20 언어가 밝은 화면뿐, 사내 PC 사용). `color-scheme: light` 를 선언하고, 윈도우 고대비(`forced-colors: active`)는 §8.5 로 지원한다(미결 R-Q7).

#### 8.1.4 무늬(`<defs>` 한 번 — 페이지마다 숨은 SVG 하나에)

| id | 모양 | 쓰는 곳 |
|---|---|---|
| `hatch-est` | 45° 흰 선 1.5px, 간격 5px, 투명도 0.75 — 바탕 채움 위에 덧칠 | 추정 분(I), 낮은 신뢰 날, 측정 불충분 몫 |
| `hatch-unattr` | 135° `#8b929b` 선 1px, 간격 5px, 바탕 `#c9cfd8` | 미귀속(X), 근무 중 미분류 |
| `hatch-bad` | 45° `#a8071a` 선 1px, 간격 6px, 투명 바탕 | 막힘(blocked)·수송 실패 칸 |

#### 8.1.5 글꼴·크기·간격

| 토큰 | 값 |
|---|---|
| 글꼴 | `"Malgun Gothic", "맑은 고딕", system-ui, -apple-system, "Segoe UI", sans-serif` (웹 글꼴 없음). 고정폭(키·해시·JSON) `Consolas, "D2Coding", monospace` |
| 본문 | 16px / 줄 1.6 |
| 표 | 14px / 줄 1.5, 숫자 열 `font-variant-numeric: tabular-nums` 오른쪽 정렬 |
| 작은 글자(주석·칩·배지) | 13px (이보다 작게 쓰지 않음) |
| 차트 눈금·축 | 12px `--ink-muted` (SVG 안에서만 — 같은 값이 표로 보기에 14px 로 있음) |
| h1 · h2 · h3 | 24px/700 · 19px/700 · 16px/700 |
| KPI 값 · 라벨 · 보조 | 30px/800(비례 숫자) · 14px `--ink-muted` · 14px `--ink-muted` |
| 간격 단위 | 4 · 8 · 12 · 16 · 24 · 32 px |
| 모서리 | 카드 8px · 입력·버튼 6px · 배지 4px · pill 999px |
| 그림자 | 없음(LM20 평면 — 테두리로만 구분). 서랍·툴팁만 `0 4px 16px rgba(18,21,26,.18)` |

### 8.2 구성 요소

#### 8.2.1 pill 메뉴(주 메뉴·절 메뉴)

```html
<nav class="pills" aria-label="주 메뉴">
  <a class="pill" href="#home" aria-current="page">홈<span class="pill-badge" aria-label="할 일 3건">3</span></a>
  <a class="pill" href="#collect">수집</a> …
</nav>
```

| 상태 | 모양 |
|---|---|
| 기본 | 흰 바탕 · 1px `--border-strong` · 글자 `--ink-2` 15px · 안쪽 여백 8px 18px · 높이 40px(누르기 영역 ≥ 40px) |
| 마우스 올림 | 테두리 `--blue` · 글자 `--blue-ink` |
| 현재(`aria-current`) | 바탕 `--surface-3` · 테두리 `--blue` · 글자 `--blue-ink` 700 |
| 초점 | `--focus` 고리 |
| 사용 불가 | 글자 `--ink-muted` · 테두리 `--border` · `aria-disabled="true"` + 이유 툴팁 |
| 배지 | 오른쪽 위 원형 18px, 바탕 `--st-bad` 아님(색만의 경고 금지) → 바탕 `--ink`·흰 글자 12px 숫자, `aria-label` 로 뜻 |

절 메뉴(개인 보고서)는 같은 모양에 높이 36px·글자 14px. 줄이 넘치면 가로 스크롤(줄바꿈 없음, 스크롤 그림자로 더 있음을 표시).

#### 8.2.2 KPI 카드

- 격자: 폭 ≥ 1100px 3열(요약 6개 = 2줄), 700~1099px 2열, 그 밖 1열. 카드 = 흰 바탕·1px `--border`·8px 모서리·안쪽 16px 20px.
- 순서: 라벨(14px muted) → 값(30px/800 ink) → 보조 줄(14px muted, 한 줄, 넘치면 말줄임 + 툴팁 전체) → 선택 배지.
- 카드 전체가 버튼이면(드릴다운) `<button class="kpi">` 로 만들고 초점 고리를 준다.
- 값이 없으면 `—` 와 이유(보조 줄).

#### 8.2.3 카드·절

- 카드 제목 h2(19px) + 제목 오른쪽 작은 상태 글자(LM20 `.state`) + 오른쪽 끝 도구(표로 보기·내보내기 아이콘 버튼).
- 카드 사이 12px. 2열 격자(`grid2`)는 폭 ≥ 1100px 에서만.

#### 8.2.4 표 + 펼침

- `<table>` 14px. 머리 `--surface-2` 바탕·`--ink-2` 700·아래 2px `--border`. 칸 안쪽 8px 10px, 줄 1px `--border` 아래선. 줄무늬 없음. 마우스 올린 행 `--surface-3`.
- 펼침 행: 첫 칸 버튼 `▸`/`▾`(`aria-expanded`, `aria-controls`), 펼친 내용은 바로 아래 `<tr class="detail"><td colspan>` 바탕 `#fafbfc`. 키보드 Enter/Space 로 토글.
- 트리 표(§6.3.1)는 `role="treegrid"`·`aria-level`·`aria-expanded`.
- 표가 500행을 넘으면 첫 500행 + [더 보기(500)] — 정렬은 서버 모델 순서 그대로(화면이 다시 정렬하면 결정성 보장이 깨지므로 열 정렬은 표로 보기에서만 허용, 원래 순서로 돌아가기 버튼).
- 머리 고정(`position: sticky`)은 표 스크롤 상자 안에서.

#### 8.2.5 버튼·입력

| 종류 | 모양 |
|---|---|
| 주 버튼 | 바탕 `--blue-btn`, 흰 글자 16px/700, 6px 모서리, 안쪽 10px 20px. 올림 `--blue-ink` |
| 보조 | 흰 바탕, 1px `--border-strong`, 글자 `--ink-2` |
| 위험 | 흰 바탕, 1px `--danger-ink`, 글자 `--danger-ink` |
| 사용 불가 | 바탕 `#e4e7eb`, 글자 `--ink-muted`, `aria-disabled` + 이유 툴팁(이유 없는 회색 버튼 금지) |
| 입력 | 높이 40px, 16px, 1px `--border-strong`, 초점 고리, 라벨은 위, 오류 글자 14px `--st-bad-ink` + ✕ 아이콘 |

#### 8.2.6 배지

| 배지 | 모양 |
|---|---|
| 등급 A·B | 글자 굵게, 1px 실선 `--ink-2` 테두리 |
| 등급 C | 1px 점선(`4 2`) 테두리 + 툴팁 '한 경계가 추정' |
| 등급 D·E | 1px 짧은 점선(`2 2`) 테두리 + 꼬리 글자 `추정` |
| O · Z · M | `진행 중 ▸` · `미착수` · `수동` |
| 라벨 출처 | `AI`(테두리 `--blue`, 글자 `--blue-ink`) · `AI(붙여넣기)` · `규칙`(테두리 `--border-strong`, 글자 `--ink-muted`) · `내 지정` |
| 측정 품질 | ✓ `신뢰` · ! `주의` · ✕ `측정 불충분` (상태 아이콘 + 글자, 바탕 흰색) |
| 판정 | ✓ `적합` · ! `조건부` · ✕ `부적합` |

#### 8.2.7 서랍(옆 패널)

- 오른쪽에서 열리는 패널: 폭 ≥ 1100px 이면 520px(간트 드릴다운)·46%(트리 수준 패널은 서랍이 아니라 나란한 칸), 좁으면 전체 폭·아래에서. `role="dialog"`·`aria-modal="false"`·`aria-labelledby`. 열면 초점을 패널 제목으로, Esc·[닫기]로 닫고 초점을 연 요소로 되돌린다. 패널 안 스크롤.

#### 8.2.8 알림 줄

info(ⓘ `--blue-ink`)·warn(! `--st-warn-ink`)·bad(✕ `--st-bad-ink`) — 흰 바탕 + 왼쪽 4px 색 띠 + 아이콘 + 글자. `role="status"`(정보)·`role="alert"`(막힘)만.

#### 8.2.9 아이콘(`web/common/icons.svg` 스프라이트 — `<symbol id="i-…">`, 20×20, `currentColor`)

`i-ok ✓` · `i-warn !` · `i-serious ▲` · `i-bad ✕` · `i-unknown ?` · `i-run ⟳` · `i-info ⓘ` · `i-pc` · `i-cloud` · `i-mail` · `i-cal` · `i-chat` · `i-doc` · `i-app` · `i-person` · `i-link` · `i-table`(표로 보기) · `i-download` · `i-upload` · `i-play` · `i-stop` · `i-lock` · `i-expand ▸` · `i-collapse ▾` · `i-close`. 자기완결 HTML 에는 스프라이트를 인라인한다.

#### 8.2.10 툴팁

- 바탕 `--ink`, 흰 글자 14px, 최대 폭 320px, 안쪽 8px 10px, 6px 모서리, 그림자. 마우스 올림 **그리고** 키보드 초점에서 뜨고, Esc 로 닫힌다. 화면 밖으로 넘치면 반대쪽으로 뒤집는다. 내용은 `textContent` 로만(RP11).
- 차트 툴팁 형식: 첫 줄 굵게(대상 이름), 다음 줄들 `이름 값` 쌍(값 오른쪽 정렬·tabular-nums), 마지막 줄 행동 안내(`누르면 근거 보기`).

### 8.3 차트 공통 규칙

1. **형태 고르기**: 크기 비교 = 막대, 시간 변화 = 막대(달·날 단위가 듬성하므로 선 대신), 구성 = 100% 가로 막대(한 줄) 또는 작은 배수, 순서·대기 = 프로세스 맵, 기간 = 간트, 분포 = 점 그림, 행렬 = 표 칸 농도. 원형(도넛)은 쓰지 않는다(LM20 의 도넛 폐기 — 칸 비교가 부정확).
2. **축 하나**: 이중 축 금지. 단위가 다른 두 값은 두 차트 또는 툴팁.
3. **마크**: 막대 두께 = 띠의 70%(최소 4px), 데이터 끝 모서리 3px(바닥은 직각), 누적 조각·이웃 막대 사이 2px 바탕색 틈, 선 2px, 점 지름 ≥ 8px, 격자는 가로선만 `--grid` 1px, 기준선 1px `--border-strong`, 눈금 4~6개 '보기 좋은 값'(1·2·2.5·5 × 10ⁿ).
4. **범례**: 계열 ≥ 2 면 늘 범례, 계열 ≤ 4 면 직접 라벨도. 계열 1개면 범례 없이 제목이 이름. 범례 견본은 무늬까지 같은 모양.
5. **글자는 글자색**: 값·라벨·범례 글자는 `--ink`/`--ink-muted`. 계열 색으로 글자를 칠하지 않는다.
6. **숫자**: §3.1 표시 함수로만. 막대 끝 값 라벨은 선택적으로(합계·최댓값·선택 막대) — 모든 막대에 숫자를 달지 않는다.
7. **마우스·키보드**: 막대·칸·점·노드마다 툴팁, 누르기 영역은 마크보다 크게(최소 24×24px 투명 사각형). 누를 수 있는 마크는 `tabindex="0"`·`role="button"`·`aria-label`(툴팁과 같은 글).
8. **표로 보기**: 모든 차트 카드 오른쪽 위 `i-table` 버튼 → 같은 차트 명세의 `table`(§8.6) 을 `<table>` 로. 화면 낭독기는 차트 대신 표를 읽게 SVG 에 `role="img"` + `aria-labelledby`(제목·한 줄 요약)·`<desc>`.
9. **빈 자료**: 빈 축을 그리지 않고 빈 상태 문장(§5.0.3).
10. **좁은 화면**(< 600px): 세로 막대 → 가로 막대, 프로세스 맵 → 세로 배치, 간트는 카드 안 가로 스크롤.
11. **움직임 없음**: 전환 애니메이션 없음.
12. **결정성**: 같은 명세면 같은 가상 노드(좌표는 소수 1자리로 반올림 — `round1(x) = Math.round(x * 10) / 10`, 정수 연산 아님이지만 표시 문자열이 아니라 좌표이므로 허용).

### 8.4 차트 카탈로그 — 데이터 필드와 그리는 규칙

표기: **데이터** = 차트 명세가 읽는 모델 경로·필드, **그리기** = 마크·축·색·라벨, **상호** = 툴팁·누르기, **표** = 표로 보기 열.

#### CH-H01 수집 커버리지 히트맵 (홈·수집)

- **데이터**: `/api/collect/coverage` `days[{d, wd, hol, s{axis: status}, why{axis: [R-*]}, src{axis: [[src, status]]}}]`, `axes`.
- **그리기**: 행 = 축 5개(왼쪽 라벨 열 96px: 메일 받음·메일 보냄·일정·팀즈·PC), 열 = 날짜(왼쪽이 과거). 칸 14×14px, 틈 2px. 칸 모양: `ok` = `--st-good` 채움 · `zero_ok` = 흰 채움 + 2px `--st-good` 테두리 · `partial` = `--st-warn` 채움 · `out_of_horizon` = `--st-serious` 채움 · `blocked` = `--st-bad` 채움 + `hatch-bad` · `transport_fail` = `--st-warn` 채움 + `hatch-bad` · `not_attempted` = 흰 채움 + 1px 점선 `--border-strong`. 주말·공휴일 열은 열 뒤에 `--surface-2` 띠, 날짜 머리 글자 `--ink-muted`. 위 축: 매주 월요일 `MM-DD`(12px). 오늘 열 위 작은 ▼.
- **상호**: 칸 툴팁 `10-02(금) · 팀즈 · 막힘 — 팀즈 창 숨김(R-UIAEMPTY) · 팀즈 창 읽기: 막힘 / 팀즈 웹: 시도 안 함`. 누르면 수집 화면 커버리지 카드의 그날 행.
- **표**: 날짜 · 메일 받음 · 메일 보냄 · 일정 · 팀즈 · PC(상태 글자) · 사유.
- 범례: 7상태 견본 + 글자.

#### CH-H02 PC × 출처 능력 표 (홈)

HTML 표(§5.1.3). 칸 = 상태 아이콘 + 글자(폭 < 900px 이면 아이콘만), 열 묶음 머리 2줄(묶음 · 출처). 해당 없음 칸 바탕 `--surface-2`. 칸 누르면 펼침 행(측정값·사유 문구·`history` 네모 10개). 표로 보기 = 이 표 자체(SVG 없음).

#### CH-P02 월별 투입 (개인 요약)

- **데이터**: `months[{m, env_min, by_tag{regular, extended, night, holiday}, denom_min, partial, load_pct}]`.
- **그리기**: x = 달(띠), y = MM(0 ~ max(1.2, 최대 MM 올림 0.2 단위)). 조각 값 = 꼬리표 분 / `denom_min`(아래부터 정규 → 연장 → 야간 → 휴일, 꼬리표 색). 1MM 기준선: 가로 점선 1px `--ink-muted` + 오른쪽 끝 글자 `1 MM`. 막대 위 합계 MM(`fmt_mm`). 부분월 막대는 바깥 1px 점선 테두리 + 아래 축 라벨 옆 `부분`.
- **상호**: 툴팁 `2026-09 · 0.99 MM(158.0h ÷ 160h) · 정규 148.0h · 연장 4.0h · 야간 2.0h · 휴일 4.0h · 로드 107%`. 누르면 근거 › 월.
- **표**: 월 · 정규 h · 연장 h · 야간 h · 휴일 h · 합 h · 분모 h · MM · 로드율.

#### CH-P03 일별 근무 (근거 › 월)

- **데이터**: `days[{d, hol, by_tag, conf_min{high, mid, low}, leave, flags}]` 중 그 달.
- **그리기**: x = 날짜 띠(그 달 전체), y = 시간(0 ~ max(10, 최대 일 h 올림)). 꼬리표 누적. low 분 / 그날 합 ≥ 0.3 이면 막대 전체에 `hatch-est` + 막대 위 작은 `낮은 신뢰` 표식(▽ 아이콘). 8h 기준 점선. 주말·공휴일 띠 배경. 연차(1) 날은 막대 자리에 `연차` 글자, 반차는 막대 아래 `반차`.
- **상호**: 툴팁 `09-22(화) 9.8h · 정규 8.0 · 연장 1.8 · 신뢰 높음 9.3 · 중간 0.5 · 낮음 0 · 확인 질문 Q08`. 누르면 날짜 드릴다운.
- **표**: 날짜 · 꼬리표별 h · 합 · 신뢰(높음·중간·낮음) h · 표식.

#### CH-P04 업무 영역 구성 (개인 요약)

- **데이터**: `tree.nodes[영역].min_by_month[m]`, `months[m].unattr_min`.
- **그리기**: 가로 막대 한 줄(높이 32px, 폭 100%), 조각 = 영역 고정 순서 + 마지막 미귀속(`hatch-unattr`), 조각 사이 2px 틈. 조각 안에는 글자를 쓰지 않는다(영역 색 위 흰 글자는 색에 따라 AA 미달 — DEV 4.42:1). 대신 막대 바로 아래 범례 줄에 영역 순서대로 `■ 개발 프로젝트 64% · 1.01 MM` 형식(견본 + 글자색 `--ink`)으로 쓴다. 0 인 영역은 범례에서 뺀다.
- **표**: 영역 · MM · 비중 · 단위업무 수.

#### CH-P06 개인 간트 · CH-P09 과제 역할 레인 · CH-T08 팀 간트 (같은 그리기)

- **데이터**(개인): `units[{unit_id, title, spans[[from, to, kind]], density{iso_week: {obs, est}}, effort_min, parallel, grade, status, start{kind, precision}, end{kind, precision}}]` + 행 계층(`tree`). (팀): `gantt[{person, domain, project_id, role_id, row_end, units[{unit_id, title, spans, density{iso_week: min}, effort_min, parallel, grade, status}]}]`(TEAM §4.9).
- **배치**: 왼쪽 라벨 열 280px(폭 < 900px 이면 180px, 이름 말줄임 + 툴팁), 오른쪽 행 끝 열 170px, 가운데 시간 축. 라벨 열과 행 끝 열은 고정, 시간 축만 카드 안에서 가로 스크롤(행 높이를 세 부분이 같은 값으로 공유).
- **시간 척도**: 시작 d₀ = 첫 달 1일, 끝 = 마지막 달 말일(팀: 최근 24개월까지). 하루 폭 `dayW` = `월 보기`: max(2, 가용 폭 / 일수) · `주 보기`: 16px. x(d) = (d − d₀) × dayW.
- **눈금**: 달 시작마다 세로선 `--border` 1px + 위 라벨 `YYYY-MM`(12px). dayW ≥ 10 이면 ISO 주 시작 세로선 `--grid` + dayW ≥ 14 이면 `W27` 라벨. 기준일(as_of) 세로 점선 `--ink-muted` + `기준일` 라벨.
- **행**: 묶음 행(사람·영역·과제) 높이 28px — 14px 굵은 라벨 + 소속 막대들의 요약 띠(높이 8px, 리드 합집합 + 주 밀도 합). 잎 행(역할 업무, 피벗이면 담당자) 높이 = 8 + 줄 수 × 18px. 줄 배정 = 시제품 `lanes()`: 막대를 (리드 시작, 리드 끝, unit_id) 순으로 놓으며 마지막 끝 날짜 < 시작 날짜인 첫 줄에, 없으면 새 줄(골든: u1 7/3~7/9 → 0, u2 7/8~7/20 → 1, u3 7/10~7/15 → 0, u4 7/21~7/30 → 0).
- **막대**(단위업무): 리드 띠 사각형 x = x(lead_from), 폭 = x(lead_to + 1일) − x(lead_from)(최소 4px), y = 줄 y + 2, 높이 14, `--lead-fill` + 1px `--lead-stroke`, 모서리 3px. **밀도 칸**: 투입이 있는 ISO 주마다 x = max(주 시작, d₀)…min(주 끝, 끝) + 1일, y = 줄 y + 4, 높이 10, 색 = 서열 단계(주당 분 m: 1~119 → `--seq-1`, 120~359 → `--seq-2`, 360~719 → `--seq-3`, 720~1199 → `--seq-4`, ≥ 1200 → `--seq-5` — TEAM §4.6 고정 단계 `[0, 120, 360, 720, 1200]`, 시제품 골든 119→1·120→2·1199→4·1200→5). 개인 간트는 그 주 `est / (obs + est) ≥ 0.5` 이면 칸에 `hatch-est`. 밀도 칸이 리드 띠 밖(의뢰 전 작업)에 있어도 그린다(툴팁 '의뢰 전 작업').
- **경계 표시**: 시작 정밀도 `none`(S2p 추정)이면 리드 띠 왼쪽 테두리를 점선(`3 2`)으로, 상태 `estimated`(E2l·E3i·NEXT_REQ 끝)면 오른쪽 테두리 점선, `open` 이면 리드 띠를 기준일까지 그리고 오른쪽 끝에 ▸(8px) — 끝 테두리 없음.
- **라벨 공간 규칙**(개인 간트·주 보기만): 막대 오른쪽에 같은 줄 다음 막대까지 120px 이상 비면 제목(12px `--ink-muted`, 120px 에서 말줄임)을 그 자리에.
- **행 끝 열**: `21.0h · ×1.8 · 7일`(투입 h · 평균 병행도 · 리드 합집합 일수 — TEAM §4.6), 13px 오른쪽 정렬.
- **범례**(차트 위 한 줄): 리드 띠 견본 `리드타임(의뢰~보고) — 막대 길이는 투입이 아닙니다` · 밀도 5칸 `주당 투입 2h 미만 · 2~6h · 6~12h · 12~20h · 20h 이상` · 점선 끝 `추정 경계` · ▸ `진행 중` · (개인) 빗금 `추정 비중 ≥ 50%` · (팀) 측정 불충분 행 배지.
- **상호**: 막대 툴팁 `전원부 검증 · 과제A › 회로·설계 · 07-03 10:12(의뢰) → 07-09 16:40(완료 파일) · 등급 B · 투입 21.0h · 병행 ×1.8 · 가장 바쁜 주 W28 16.0h`. 누르기·Enter → 개인: 단위업무 수준 패널, 팀: §7.6.3 서랍. 키보드: 막대는 행 순·시간 순으로 Tab, ←/→ 같은 행 앞뒤 막대, ↑/↓ 이웃 행에서 x 가 가장 가까운 막대. 묶음 행 머리 ▸/▾ 접기.
- **피벗**(팀): 토글 `담당자 기준 | 업무 기준`. 기준이 바뀌어도 막대 위치·색은 같다.
- **표**: 행 경로(사람 › 영역 › 과제 › 역할) · 단위업무 · 시작 · 끝 · 등급 · 상태 · 투입 h · 병행도 · 리드 일 · 가장 바쁜 주.
- (CH-P09) 과제 수준 패널은 행 = 역할 업무. [인계 보기]를 켜면 인계 쌍(§4.3.2)마다 앞 막대 끝 → 뒤 막대 시작을 잇는 1.5px `--ink-muted` 곡선(아래로 볼록) + 끝 화살표.

#### CH-P07 프로세스 맵 (역할 워크플로우 — 개인 패널·팀 드릴다운 공용)

- **데이터**: `RoleWorkflow.steps[{no, code, name, kind, n, median_min, wait_in_median_min, work_share, label, label_by}]`, `edges[[i, j, n]]`, `rework`, `bottlenecks[{no, kind, value_min|share}]`, `dropped`. 팀: 묶음 `workflows[].steps[{no, type, label, n, median_min, …}]`·`edges`(대기·병목 필드는 §13 T-3 반영 뒤).
- **배치**(폭 W ≥ 560px — 가로): 단계 k 개를 왼쪽→오른쪽 번호 순. x_i = 70 + (i − 1) × (W − 140)/(k − 1)(k = 1 이면 W/2), 기준 y = 130, SVG 높이 260(앞으로 건너뛰는 호 단계가 3 을 넘으면 넘는 단계마다 +20).
- **노드**: 구간 단계 = 112×44 둥근 사각형(6px), `--blue-wash` 채움·1.5px `--blue` 테두리, 1줄 라벨(13px 700 `--ink`, 9자 넘으면 말줄임) · 2줄 `중앙 3.5h`(12px `--ink-muted`, 소요 0 이면 `—`). 노드 아래 4px 작업 비중 막대(폭 = 100 × work_share px, `--blue`). 점 단계 = 지름 20 마름모(흰 채움·1.5px `--blue`), 라벨은 아래 12px. 라벨 출처(AI·규칙)는 노드에 표시하지 않고 단계 표에서 보인다.
- **간선**: 바로 다음 단계(j = i + 1) = 노드 사이 직선 + 화살촉(8px). 건너뛰는 앞 간선(j > i + 1) = 위쪽 호(제어점 y = 130 − 22 − 24 − 14 × (j − i − 1)). 되돌림(j < i) = 아래쪽 호(제어점 y = 130 + 22 + 24 + 14 × (i − j − 1)), 점선 `5 4`. 선 굵기 = 1.5 + 4.5 × n / n_max(0.5 단위 반올림), 색 `--ink-muted`(선택·올림 `--blue`). 횟수 라벨 `×5`(12px)은 n 상위 3 간선의 중점에만.
- **병목**: 대기 병목 단계 노드 = 3px `--st-bad` 테두리 + 노드 위 배지(▲ `--st-serious` 아이콘 + `대기 병목 · 1.5영업일`, 12px `--ink`), 그 단계로 들어오는 가장 굵은 간선 위에 `대기 1.5일` 라벨. 작업 병목 = 같은 테두리 + `작업 병목 · 56%`. 둘 다면 배지 두 줄.
- **좁은 화면**(W < 560): 세로 배치(y_i = 40 + (i − 1) × 76, 노드 가운데 x = W/2 − 30), 앞 건너뛰기 호는 오른쪽, 되돌림 호는 왼쪽.
- **상호**: 노드 툴팁 `S3 표 계산(AI 라벨: 결과 정리) · 4/4 단위업무 · 중앙 105분(75% 180분) · 들어오는 대기 중앙 1.5영업일 · 관측 92% · Agentic 상 · 서브에이전트 적합`. 누르면 단계 표의 그 행 강조 + 그 단계가 나온 단위업무 목록 필터. 간선 툴팁 `표 계산 → 회의 ×2 · 대기 중앙 1.0영업일`.
- **캡션**: `드물어 뺀 단계: PDF 검토(1/4)` · `표본 부족(단위업무 2건) — 병목 판단 안 함`.
- **표**: 단계 표(§6.3.2)와 간선 표(앞 단계 · 뒤 단계 · 횟수 · 대기 중앙 · 되돌림 여부).

#### CH-P08 단위업무 타임라인

- **데이터**: `UnitWorkflow{lanes, runs[{type, class, a, b, min, obs_min}], milestones[{type, t, flags}], boundaries[{side, code, t, estimated}], waits, longest_wait}`.
- **배치**: 날짜 열(단위업무 리드 구간의 날짜들, 근무일 아닌 날은 폭 1/3), 열 폭 cw = max(24, W / 날짜 수)(넘치면 가로 스크롤), 열 안 x = 0~24시 선형. 줄 = 맨 위 '근거' 줄(점·경계) + 묶음 줄(나온 것만, 높이 22px).
- **마크**: Run = 묶음 줄 안 사각형(높이 14, `--blue`, obs_min < min 이면 `hatch-est` 덧칠). 점 단계 = 근거 줄 마름모 10px(`offline` 이면 속 빈 마름모 + `오프라인` 툴팁, `interim` 이면 작은 마름모). 경계 = 전 줄을 가로지르는 세로선(정확 = 실선 `--ink-2`, 추정 = 점선 `--ink-muted`) + 위 라벨 `S1`·`E2h`. 최장 대기 = 앞 Run 끝 → 뒤 Run 시작 사이 아래쪽 꺾쇠선 + `대기 2.3영업일`.
- **상호**: Run 툴팁 `09-22 13:00~15:30 · 해석 프로그램(앱 spice 2.5h) · 관측 2.5h`. 누르면 그날 날짜 드릴다운.
- **표**: 시각 · 단계 · 묶음 · 분 · 관측 분 · 앱·문서(로컬 해석).

#### CH-P10 단계 묶음 구성 (영역 수준)

- **데이터**: `workflows.domains[k].class_mix{class: min}` 과 과제별 같은 값.
- **그리기**: 작은 배수 — 과제마다(투입 상위 8, 나머지 '그 밖') 묶음 7개 가로 막대 목록, 단색 `--blue`, 모든 작은 그림이 같은 x 범위(0~100%), 막대 끝 값 `34%`. 마지막 줄 '단계 없음(추정 배분)' 은 `hatch-unattr` 가 아니라 `--lead-fill` + `hatch-est`(추정임을 표시).
- **표**: 과제 · 묶음 · 분 · 비중.

#### CH-P11 리드타임 점 그림(개인 월간) · CH-T06(팀, 줄 = 영역)

- **데이터**: 그 기간 `finished` 의 `{unit_id, role_id, biz_lead_min, overrun, causes}` + 역할 기준 중앙 `baseline_biz_min`.
- **그리기**: 줄 = 역할(팀은 영역), x = 영업일(0 ~ 최대 올림, 눈금 보기 좋은 값). 점 지름 8 `--blue`, 같은 x(±4px)가 겹치면 결정적 순서(unit_id)로 위아래 3px 번갈아 벌림. 기준 중앙 = 줄마다 세로 짧은 선(12px, `--ink-2`), 1.5배 문턱 = 짧은 점선. 초과 점 = 2px `--st-bad` 고리 + 오른쪽에 원인 짧은 이름(12px).
- **상호·표**: 점 툴팁 = 제목·리드·투입·원인 문장. 표 = 단위업무 · 역할 · 영업 리드 · 기준 · 배수 · 원인.

#### CH-P12 동료 막대

- **데이터**: `peers.internal[{k, name, units, shared_effort_min, roles{requester, reporter, thread, meeting}}]`.
- **그리기**: 가로 막대(단색 `--blue`, 계열 하나 — 범례 없음), 왼쪽 이름, 막대 끝 `단위 6 · 12.5h`. 토글로 x 축을 공동 단위업무 수 ↔ 공유 투입 h.
- **표**: §6.5 표.

#### CH-P13 연관 그래프(방사형)

- **데이터**: `ontology{center, nodes[{id, type, group, label, weight_min, angle?}], edges[{from, to, rel, w, h, inferred}], recs[...]}`(§4.6).
- **배치**(정사각 S = min(카드 폭, 720)): 가운데 (S/2, S/2) 에 과제 노드. 역할 고리 r₁ = 0.22S: 역할마다 각도 구간 = 역할 투입 비중 × 360°(−90° 에서 시계 방향, 역할 투입 내림차순 → role_id), 역할 노드는 구간 가운데. 단위업무 고리 r₂ = 0.36S: 역할 구간 안에 시작 시각 순으로 균등. 바깥 고리 r₃ = 0.46S: D·A·C 노드의 각도 = 연결된 단위업무 각도의 가중(h) 원형 평균, 그 각도로 정렬한 뒤 최소 간격 δ = max(360°/(노드 수 × 1.2), 7°) 보다 가까운 이웃을 앞에서부터 밀어낸다(결정적).
- **노드**: 크기 = √(가중 분) 비례(과제 22, 역할 10~18, 단위업무 5~10, 바깥 6~10 px 반지름), 모양 = 과제 둥근 사각형 · 역할 큰 원 · 단위업무 작은 원 · 문서 사각형 · 앱 마름모 · 동료 삼각형, 색 = 무리(업무·산출·도구·사람 3색 — §8.1.3), 테두리 흰 2px(겹침 가독). 라벨: 과제·역할·바깥 노드는 늘(바깥은 고리 바깥쪽, 각도에 따라 왼쪽/오른쪽 정렬, 14자 말줄임), 단위업무는 올림·선택 때만.
- **간선**: 구조(소속) = `--border-strong` 1px 직선. 관계 = 바깥 노드 → 단위업무 직선, 바깥 노드 무리 색 투명도 0.45, 굵기 1~4px(w 비례). 단위업무 ↔ 단위업무(선행함·같은문서) = 고리 안쪽으로 휘는 곡선, 추정 관계(선행함)는 점선. 관계 종류는 색이 아니라 **선 모양**(실선 = 관측된 관계: 의뢰함·보고함·산출함·사용함·함께함, 점선 = 추론 관계: 선행함·같은문서)과 툴팁 글자로.
- **상호**: 노드 올림 → 이웃만 진하게, 나머지 투명도 0.15. 단위업무 누르기 → 추천 목록 갱신 + 단위업무 패널. 바깥 '기타 n' 노드 누르기 → 바깥 노드 수 늘리기.
- **표**: 노드 표·간선 표(§6.6).

#### CH-P14 Agentic 매칭 격자(개인) · CH-T07(팀, 열 = 업무 영역)

- HTML 표(칸 = `<td>`, 화면 낭독 친화). 칸 모양: 상 = 바탕 `#1c5cab` 흰 글자 `상` · 중 = 바탕 `#86b6ef` `--ink` 글자 `중` · 하 = 흰 바탕 + 1px `#86b6ef` 테두리 `하` · 없음 = `·`(`--ink-muted`). 출처가 규칙이면 글자 뒤 작은 `규칙`, 규칙과 다르면 `◇`. 팀(CH-T07) 칸 = `3명 · 9건` + 최고 등급 글자, 바탕 = 관련 투입 MM 의 표 칸 농도(§8.1.3 6구간, 표 최댓값 기준 비율 (0, .2] … (.8, 1]).
- 행 끝·열 머리: §6.7·§7.5.

#### CH-P15 서브에이전트 점수 표

- HTML 표. 점수 칸 = 점 3개(지름 10px): 채운 점 `--blue`, 빈 점 1px `--border-strong` 테두리, 옆 숫자 `2`. 위험(RISK)은 '높을수록 나쁨'이라 점을 `--st-bad-ink` 로 채우고 글자 `낮음·중간·높음`. 판정 칸 = 배지(§8.2.6). 규칙 판정과 최종이 다르면 최종 칸에 `AI 의견보다 보수적` 툴팁.

#### CH-P16 하루 24시간 띠

- **데이터**: `/api/report/day/<d>` `intervals[{a, b, tag, basis, targets[[id, min, grade]]}]`, 근무창.
- **그리기**: 폭 = 카드 폭, x = 0~24시(눈금 3시간마다). 위 10px 띠 = 시간대 배경(정규 구역 `--surface-3`, 야간 22~06 `#e4e7eb`, 점심 흰색). 본 띠 28px = 구간마다 사각형: 대상이 단위업무이고 등급 O = `--blue` · I = `--blue` + `hatch-est` · 버킷 X = `--unattr` + `hatch-unattr` · 한 구간에 대상이 여럿(분할)이면 구간을 분 비율로 세로로 나눠 쌓는다(위에서부터 대상 키 순). 차감·제외 구간 = 흰 채움 + 1px 점선 `--st-bad-ink` 테두리 + 띠 아래 `차감` 글자. 봉투 밖 시간은 비움.
- **상호**: 구간 툴팁(시각·꼬리표·근거·대상·분·등급·비고), 단위업무 구간 누르기 → 업무 원장.
- **표**: 구간 원장 표(§6.10.2).

#### CH-P17 단위업무 등급 분포

- 가로 막대(단색 `--blue`), 줄 = A·B·C·D·E·O(진행 중)·M(수동), 값 = 그 등급 단위업무 alloc 분 → h, 막대 끝 `62.5h · 40%`. 등급 글자 배지(§8.2.6)를 줄 머리에. Z(미착수)는 투입 0 이라 막대 없이 아래 `미착수 의뢰 n건` 한 줄.

#### CH-T02 월별 업무 영역 투입(팀)

- **데이터**: `domains[{code, by_month{m: {mm, by_person[[i, mm]]}}}]`, `unattributed`, `people[i].quality`, `months`, `workdays`.
- **그리기**: x = 달, y = MM. 조각 = 영역 고정 순서(아래 DEV → 위 AX·UNC) + 맨 위 미귀속(`hatch-unattr`). 각 영역 조각 안에서 측정 불충분 사람 몫을 조각 위쪽에 같은 색 + `hatch-est` 로 나눠 그린다. 막대 위 팀 MM. 묶음이 없는 사람·달은 0 이 아니라 '자료 없음' — 막대 아래 작은 `n명 자료 없음`.
- **상호·표**: 툴팁 = 영역별 MM + 사람 수, 표 = 월 × 영역 MM + 미귀속 + 자료 없음 인원.

#### CH-T09 측정 품질 행렬

HTML 표(§7.7). 칸 = 아이콘 + `%`. 행 머리 = 사람 라벨 + 품질 배지. 열 머리 = 축. 측정 불충분 행은 바탕 `--surface-2`.

### 8.5 접근성

| 항목 | 규칙 | 확인 |
|---|---|---|
| 글자 대비 | 본문·표·보조 글자 4.5:1 이상(§8.1 표 실측값). 큰 글자(24px 이상·19px 굵게)·아이콘·차트 마크 3:1 이상 | G-R7 대비 검사(토큰 쌍 표) |
| 색만으로 뜻 전달 금지 | 상태 = 아이콘 + 글자, 관측/추정 = 채움/빗금 + 글자, 등급 = 테두리 모양 + 글자, 노드 종류 = 모양, 관계 = 선 모양 | 시험 RPT-21 (흑백 렌더 스냅숏 검토 목록) |
| 키보드 | 모든 버튼·pill·표 펼침·차트 마크·서랍을 Tab/Enter/Space/Esc/방향키로. 초점 고리 늘 보임(`:focus-visible`) | 점검표 KB-1~KB-9(§12.3) |
| 화면 낭독 | `lang="ko"`, 랜드마크(`header`·`nav`·`main`), 차트 `role="img"` + 제목·한 줄 요약 + 표로 보기, 알림 `role="status"/"alert"`, 진행 막대 `role="progressbar"` + `aria-valuenow` | 점검표 |
| 확대 | 200% 확대에서 가로 스크롤 없이 다시 흐름(간트·넓은 표는 카드 안 스크롤만) | 점검표 |
| 누르기 영역 | 최소 24×24px(pill·버튼 40px) | — |
| 고대비 모드 | `@media (forced-colors: active)`: 채움 대신 `CanvasText` 테두리 + 무늬, 상태 아이콘 유지, 막대 = `Highlight` | 점검표 |
| 움직임 | 애니메이션 없음 | — |
| 시간 제한 | 자동으로 닫히는 알림 없음(작업 완료 토스트는 [닫기]까지 유지) | — |
| 언어 | 화면 문구 한국어, 코드(`R-NEWOL`·`S1`)는 늘 한국어 이름과 함께 | — |

### 8.6 렌더러 한 벌 — 구조와 보안

#### 8.6.1 가상 노드와 차트 함수

```javascript
// web/common/lm27charts.js — DOM·전역 상태·시계에 손대지 않는 순수 함수만
function h(tag, attrs, children) { return {t: tag, a: attrs || {}, c: children || []}; }   // 글자 = 문자열 자식
// 모든 차트: (명세, 선택) → {svg: vnode, table: {cols: [..], rows: [[..]]}, legend: [{label, swatch}], caption: {title, summary}}
function chartMonthlyMM(spec, opt) { … }      // CH-P02
function chartGantt(spec, opt) { … }          // CH-P06·P09·T08
function chartProcessMap(spec, opt) { … }     // CH-P07
function chartRadial(spec, opt) { … }         // CH-P13
// … 카탈로그 §8.4 의 CH-* 마다 하나. 이름 표 CHARTS = {"CH-P02": chartMonthlyMM, …}
function toString(v) { … }                    // 시험용 직렬화(글자·속성 값 & < > " 이스케이프)
```

- 차트 함수는 **모델 값을 바꾸지 않고**, 좌표만 계산한다. 숫자 글자는 `fmtH1`·`fmtRatio`(§3.1)로만 만든다. 색은 토큰 이름(`var(--dom-dev)`)으로만 쓴다.
- 결정성: 같은 명세·같은 폭이면 같은 vnode(`toString` 이 같은 문자열 — 시험 RPT-25 골든).

#### 8.6.2 마운트·상호

```javascript
// web/common/lm27ui.js
function mount(v, parent, inSvg) { … }   // createElementNS(SVG 이름공간)/createElement + setAttribute + createTextNode 만
const ATTR_OK = /^(class|id|x|y|x1|x2|y1|y2|cx|cy|r|rx|ry|width|height|d|points|transform|fill|stroke|stroke-width|
                  stroke-dasharray|opacity|fill-opacity|text-anchor|dominant-baseline|font-size|font-weight|viewBox|
                  role|tabindex|aria-[a-z]+|data-[a-z0-9-]+|href|marker-end|clip-path|pattern[A-Za-z]*|preserveAspectRatio)$/;
// ATTR_OK 밖의 속성 이름(on*, style, xlink:href 의 javascript: 등)은 마운트에서 버린다. href 값은 '#' 으로 시작할 때만 허용
```

- 이벤트는 위임 하나: 문서에 `click`·`keydown`·`mouseover`·`focusin` 수신기를 두고 `data-act`(예 `drill-day`·`open-unit`·`toggle-row`)와 `data-ref`(정수 인덱스·ID)로 처리한다. 마크에 함수 속성을 달지 않는다.
- 사람·라벨을 객체 키로 쓰지 않는다: 팀 데이터의 사람은 `people[i]` 의 `i`, 단위업무는 `unit_id`(형식 고정 `^u_[0-9a-f]{10}$`), 역할은 `role_id`.

#### 8.6.3 금지(관문 G-R4)

`web/**/*.js` 에 `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write`·`eval(`·`new Function`·`setTimeout("`·`DOMParser`·`toFixed(` 가 0건. `lm27/**/*.py` 의 HTML 생성은 `lm27/report/export.py`·`lm27/team/report.py` 의 껍데기 틀 채우기뿐이고, 모든 값은 JSON 섬으로만 들어간다(HTML 본문에 값을 문자열로 끼워 넣지 않는다 — 제목 `<title>` 도 고정 문자열 `LM27 개인 보고서`·`LM27 팀 보고서`).

---

## 9. 산출 파일과 데이터 계약 (E)

### 9.1 산출 파일

#### 9.1.1 개인(`lm27 report export`, 화면 [내보내기])

폴더 `ROOT\out\personal\<from>_<to>_<run8>\`(run8 = run_id 의 마지막 8자 — 날짜·무작위 부분). 폴더 이름·파일 이름에 사람 이름·과제 이름을 넣지 않는다.

| 파일 | 변형 | 내용 | 반출 |
|---|---|---|---|
| `report_full.html` | full | 자기완결 개인 보고서(§9.4) — 동료 이름·문서 이름·근거 줄 포함 | **로컬 전용**(머리 배지·첫 화면 안내) |
| `report_redacted.html` | redacted | 이름·문서명·메시지 제목·근거 줄 없음(§3.6) | 공유용 |
| `report_model.json` | full | 보고서 모델(§9.2) | 로컬 전용 |
| `report_model_redacted.json` | redacted | 가림판 모델(§9.2.4) | 공유용 |
| `csv_full\*.csv` · `csv_redacted\*.csv` | 각각 | §9.3.1 표 15종 | full 은 로컬 전용 |
| `manifest.json` | — | `{"schema": "lm27.export/1", "run_id", "report_version", "built_at", "files": [{"path", "variant", "format", "bytes", "sha256"}]}` | — |

- 형식·변형 선택: `report.export.formats`(기본 `["html","csv","json"]`), `report.export.variants`(기본 `["full","redacted"]`). 화면 [내보내기] 대화상자에서 고른 값이 이번 한 번에 우선.
- 쓰기: 같은 폴더에 `.part` 로 쓰고 `os.replace`(TEAM §0.3 `atomic_write`). 같은 이름 폴더가 있으면(같은 실행을 다시 내보냄) 그 안의 파일을 원자 교체한다.
- 보관: `ROOT\out\personal\` 아래 폴더를 만든 시각 순으로 `report.export.keep`(10)개 넘으면 오래된 것부터 지운다 — **이 문서가 만든 이름 형식(`^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_[0-9a-f-]{8}$`)인 폴더만**, 다른 폴더·파일은 건드리지 않는다.
- 결과 화면: 만든 파일 목록(ROOT 상대 경로·크기)과 [폴더 열기](`os.startfile`), full 파일 옆 `로컬 전용` 배지.

#### 9.1.2 팀(팀 서버, TEAM §3.9)

| 파일 | 내용 |
|---|---|
| `out\gen_N\team_data.json` | TEAM §4.9 + 이 문서 §7.8.1 필드 |
| `out\gen_N\team_report.html` | 자기완결 팀 보고서(§9.4 와 같은 구조, 데이터 섬 = team_data + details) |
| `out\gen_N\team_report_share.html` | 공유판 — 사람별 `load_pct`·초과 시간 열 제거(TEAM 관문: 제거 키가 HTML 전체에 0회) |
| `out\gen_N\team_tables\*.csv` | (§13 요청 T-5) §9.3.3 표 — 전체판·공유판 두 벌(`team_tables\share\`) |

### 9.2 `report_model.json` (스키마 `lm27.report` 1.0)

#### 9.2.1 전체 모양(값은 합성 — 배열은 일부만)

```json
{"schema": "lm27.report", "schema_version": "1.0",
 "generator": {"app_version": "0.1.0", "report_version": "report/1", "core_version": "timecore/1", "rules_ver": "2026.10.0",
               "registry_version": 7, "calendar_version": "kr-2026.3", "catalog_version": "ag-3",
               "stage_versions": {"workflow_label": "workflow_label/1.0", "agentic_match": "agentic_match/1.0",
                                  "subagent_review": "subagent_review/1.0", "review_text": "review_text/1.0"}},
 "variant": "full",
 "run": {"run_id": "20261005-101500-3fa2", "from": "2026-09-01", "to": "2026-10-04", "as_of": "2026-10-04T18:00",
         "tz_offset_min": 540, "chosen": "auto"},
 "flags": {"copilot": "ai|partial|rule_only", "registry": {"version": 7, "fetched_at": "2026-10-03T09:00"},
           "warnings": [{"code": "mining_coarse", "text_ko": "…"}],
           "label_sources": {"task_label": {"ai": 112, "manual": 0, "rule": 8}}},
 "denominator": {"basis": "workdays", "std_day_min": 480, "text_ko": "1MM = 8시간 × 그 달 근무일(주말·공휴일·회사 휴무 제외)"},
 "domains": [{"code": "DEV", "name": "개발 프로젝트", "color": "#2a78d6", "order": 0}],
 "months": [{"m": "2026-09", "workdays": 20, "covered_workdays": 20, "denom_min": 9600, "partial": null,
             "env_min": 9480, "by_tag": {"regular": 8880, "extended": 240, "night": 120, "holiday": 240},
             "attributed_min": 9000, "unattr_min": 480, "buckets": {"B_GENERIC": 180, "B_COMM": 120, "B_MEET": 90, "B_OFFPC": 60, "B_UNKNOWN": 30},
             "obs_min": 7400, "est_min": 1600, "conf_min": {"high": 8800, "mid": 500, "low": 180},
             "avail_days": 18.5, "avail_min": 8880, "absence_days": 1.5, "load_pct": 106.76, "overtime_window_min": 600, "overtime_daily8h_min": 540,
             "holiday_night_min": 0, "on_leave_min": 20, "units": {"started": 5, "finished": 4, "continuing": 3, "unstarted": 1},
             "quality": {"grade": "reliable", "reasons": [], "cov": {"mail_in": 0.97, "mail_out": 0.97, "cal": 1.0, "teams": 0.8, "pc": 1.0},
                         "est_ratio": 0.019, "unattr_ratio": 0.051, "no_ev": 0, "sampler_ratio": 1.0}}],
 "days": [{"d": "2026-09-22", "hol": false, "by_tag": {"regular": 480, "extended": 110}, "env_min": 590,
           "conf_min": {"high": 560, "mid": 30, "low": 0}, "obs_min": 520, "est_min": 40, "unattr_min": 30, "leave": 0, "flags": ["Q08"]}],
 "projects": [{"key": "P-0007", "project_id": "P-0007", "proposal_id": null, "label": "과제A", "label_src": "registry",
               "domain": "DEV", "mask_name": false, "merged_from": []}],
 "roles": [{"role_id": "r_5c0d11", "project_key": "P-0007", "field": "ELEC", "field_name": "회로", "function": "ANALYSIS",
            "function_name": "해석·분석", "label": "회로 · 해석·분석"}],
 "units": [{"unit_id": "u_3e9a01c2d4", "title": "전원부 검증", "title_by": "ai", "role_id": "r_5c0d11", "project_key": "P-0007",
            "domain": "DEV", "field": "ELEC", "function": "ANALYSIS", "activity_type": "DEV", "stance": "DO", "ax_link": false,
            "label_level": "high", "kind": "S1",
            "cycles": [{"s": "2026-07-03T10:12", "sb": "S1", "e": "2026-07-09T16:40", "eb": "E2h", "interim": []}],
            "start": {"kind": "S1i", "precision": "minute"}, "end": {"kind": "E2", "precision": "exact"},
            "grade": "B", "status": "closed", "lead_min": 9028, "biz_lead_min": 2668, "effort_min": 1260, "obs_min": 960, "est_min": 300,
            "levels_min": {"L1": 0, "L2": 60, "L3": 900, "L4": 40, "L5": 60, "L6": 200}, "parallel": 1.8, "machine_min": 0,
            "pre_request_min": 0, "flags": [], "first_evidence": "2026-07-03", "last_evidence": "2026-07-09",
            "spans": [["2026-07-03", "2026-07-09", "lead"], ["2026-07-03", "2026-07-03", "active"], ["2026-07-08", "2026-07-09", "active"]],
            "density": {"2026-W27": {"obs": 240, "est": 60}, "2026-W28": {"obs": 720, "est": 240}},
            "by_month": {"2026-07": 1260}, "by_tag": {"regular": 1140, "extended": 120},
            "steps": ["REQ_IN", "APP_SIM", "DOC_XLS", "REPORT_OUT"], "step_min": {"APP_SIM": 600, "DOC_XLS": 300},
            "peers": [3, 7], "apps": [["spice", 600], ["excel", 300]], "apps_unknown_min": 0, "docs": [12, 15], "queue": ["9f2c01ab3e4d"]}],
 "tree": {"order": ["DEV", "MP", "EXT", "COM", "AX", "UNC", "UNATTR"],
          "nodes": {"DEV": {"level": "domain", "children": ["P-0007"], "min_by_month": {"2026-09": 6100}, "min_total": 6100,
                            "units": {"done": 4, "open": 2, "unstarted": 0}, "lead_biz_median_min": 1770},
                    "P-0007": {"level": "project", "parent": "DEV", "children": ["r_5c0d11"]},
                    "r_5c0d11": {"level": "role", "parent": "P-0007", "children": ["u_3e9a01c2d4"], "bottleneck": "wait:3|work:2"},
                    "UNATTR": {"level": "unattributed", "children": ["B_GENERIC", "B_COMM", "B_MEET", "B_OFFPC", "B_UNKNOWN"]}}},
 "workflows": {"roles": {"r_5c0d11": {"…": "§4.2.2 RoleWorkflow"}}, "units": {"u_3e9a01c2d4": {"…": "§4.3.1"}},
               "projects": {"P-0007": {"…": "§4.3.2"}}, "domains": {"DEV": {"…": "§4.3.3"}}, "person": {"…": "§4.3.3"}},
 "reviews": {"weeks": [{"key": "2026-W38", "from": "2026-09-14", "to": "2026-09-20", "partial": null, "…": "§4.4.2"}],
             "months": [{"key": "2026-09", "…": "§4.4.2"}]},
 "peers": {"internal": [{"k": 1, "ref": 3, "name": "김철수", "units": 6, "shared_effort_min": 750,
                         "roles": {"requester": 3, "reporter": 2, "thread": 4, "meeting": 1}, "projects": ["P-0007"],
                         "first": "2026-07-03", "last": "2026-09-30"}],
           "external": {"customer": 4, "partner": 2, "other": 1}},
 "ontology": {"center": "P-0007", "nodes": [], "edges": [], "recs": {"u_3e9a01c2d4": [{"unit_id": "u_0b1c2d3e4f", "rel": 0.5833, "kind": "chain"}]},
              "related_projects": [{"key": "P-0003", "rel": 0.21}]},
 "agentic": {"catalog_version": "ag-3", "catalog_n": 12, "items": [], "matches": [], "needs": []},
 "subagent": {"roles": [{"role_id": "r_5c0d11", "steps": [], "rule": "조건부", "ai": {"verdict": "부분", "orch": "…", "subs": [], "risk": "…", "by": "ai"},
                         "final": "조건부", "fit_share": 0.32}]},
 "queue": [{"qid": "9f2c01ab3e4d", "code": "Q01", "target": "u_3e9a01c2d4", "impact_min": 540, "week": "2026-W38", "status": "open",
            "proposal": {"…": "WORKTIME §7.3"}}],
 "quality": {"grade": "reliable", "reasons": [], "by_month": {"2026-09": "reliable"}},
 "refs": {"people": {"3": {"key": "w3fa9c1d2e4b50617", "name": "김철수", "internal": true}},
          "docs": {"12": {"key": "d1a2b3…", "name": "전원부_검증결과", "ext": "xlsx"}},
          "apps": {"spice": {"name": "회로 시뮬레이터", "cls": "sim"}}}}
```

#### 9.2.2 필드 규칙

| 경로 | 형 | 규칙 |
|---|---|---|
| `schema`·`schema_version` | str | `lm27.report`·`MAJOR.MINOR`. 화면은 MAJOR 가 다르면 보고서를 다시 만든다(§2.4.3) |
| 모든 `*_min` | int ≥ 0 | 정수 분. 소수 분 없음 |
| `months[].env_min` | int | = Σ 그 달 `days[].env_min` = `team_tables.envelope_daily` 그 달 합(관문 G-R2) |
| `months[].attributed_min + unattr_min` | int | = `env_min`. `obs_min + est_min` = `attributed_min` |
| `months[].buckets` | obj | 버킷 5종 합 = `unattr_min` |
| `months[].avail_min` · `load_pct` | int · float \| null | `avail_min` = `std_day_min × avail_days` 를 정수 분으로 half-up(WORKTIME §6.4 의 오늘 경과 비율 때문에 avail_days 가 소수일 수 있다), `load_pct = env_min / avail_min × 100`, avail 0 → null. 표시는 `fmt_pct(env_min, avail_min)`(§3.1) |
| `units[].effort_min` | int | = Σ `alloc_daily` 의 그 unit 행(TEAM I6) |
| `units[].obs_min + est_min` | int | = `effort_min` |
| `units[].peers` · `docs` | list[int] | `refs.people`·`refs.docs` 의 정수 참조 — 키를 여러 번 반복하지 않고, 가림판에서 `refs` 만 바꾸면 되게 |
| `refs.people[n].key` | str | full 변형에만. redacted 는 `{"name": "동료 #k"}` 만(키 없음) |
| 시각 문자열 | str | 근무 시간대 로컬 `YYYY-MM-DDTHH:MM`(초·오프셋 없음 — `run.tz_offset_min` 하나로 해석) |
| 날짜 키 | str | `YYYY-MM-DD`, 주 `YYYY-Www`(ISO), 달 `YYYY-MM` |
| 정렬 | — | 배열은 모두 명시 순서: `months`·`days` 시간순, `units` (첫 차수 시작, unit_id), `projects` (영역 순서, 기간 분 내림차순, key), `peers.internal` §4.5 |
| 크기 | — | 사람 1명 3개월 약 1~3MB(설계 추정 — 단위업무 300·날 92·동료 80 기준). `report.export.maxModelMb`(32) 초과 시 `days` 를 남기고 `workflows.units` 의 `runs` 를 요약(§11) |

#### 9.2.3 모델을 만드는 순서(`model.build_model`)

```text
inp = load_inputs(run_id)                       # §2.5
assert_time_inputs(inp)                         # 없으면 rc 1
labels = apply_labels(inp.time.tasks, inp.labels, inp.registry)        # 영역·과제·역할·유형·제목
tables = int_tables(inp.time.team_tables, inp.time.attrib)            # §3.4 O/I 분 나누기(최대잉여)
months, days = month_day_rows(tables, inp.time.mm_month, inp.time.env_slots, inp.bundle_state)   # + quality(§4.9)
log = build_activity(inp.time.tasks, inp.time.attrib, days, cfg)       # §4.1
wf_roles = {r: mine_role(U_r, log, cfg) for r in roles}                # §4.2
wf_units, wf_projects, wf_domains = …                                  # §4.3
apply_ai(wf_roles, inp.ai.workflow_label)                              # §4.10.2 (없으면 폴백)
agentic = agentic_layer(wf_roles, inp.registry.agents, inp.ai.agentic_match)          # §4.7
subagent = subagent_layer(wf_roles, log, inp.ai.subagent_review)                      # §4.8 → Step.subagent 채움
peers = peers_layer(inp.time.tasks, inp.evidence, inp.person_dir)                     # §4.5
ontology = ontology_layer(units, log, peers, cfg)                                     # §4.6
reviews = review_layer(units, tables, log, peers, ontology, inp.ai.review_text)       # §4.4
model = assemble(...); model = canon(model)      # 키 정렬·정수 확인·NaN 금지
check_model(model)                               # §9.2.2 등식 assert — 실패하면 rc 1(보고서를 만들지 않고 이전 보고서 유지)
```

#### 9.2.4 가림판 모델 — 허용 목록으로 다시 만들기

`redact_model(full) -> dict` 는 full 모델을 **복사해서 지우지 않고**, 아래 표의 필드만 골라 새 dict 를 만든다(TEAM §2.4 와 같은 방식).

| 절 | 가림판에 남는 것 | 바뀌는 것 | 빠지는 것 |
|---|---|---|---|
| `months`·`days`·`denominator`·`domains`·`quality` | 전부 | — | — |
| `projects` | key·project_id·domain·label | `mask_name=true` 면 label = 과제 ID | `merged_from` |
| `units` | 숫자·코드·등급·상태·spans·density·steps·step_min | title = 팀 묶음 제목(§3.6) | `cycles[].s_key/e_key`, `apps` 중 미상 프로그램 이름, `docs`, `queue` |
| `workflows` | 단계·간선·대기·병목·라벨(코파일럿 라벨은 정제 라벨) | units 수준 `runs` 의 앱·문서 → 앱 범주만 | units 수준의 근거 키 |
| `reviews` | 숫자·코드·AI 문장(동료 번호표 → `동료 #k`) | — | `peers_top` 의 이름 |
| `peers` | k·units·shared_effort_min·roles·projects·first·last | name = `동료 #k` | `refs.people[*].key`·이름 |
| `ontology` | 노드 종류·관계·가중치·연관도·추천 | 문서 노드 이름 = `문서 #k`, 동료 = `동료 #k` | — |
| `agentic`·`subagent` | 전부 | — | — |
| `queue` | 코드·영향 분·상태 | — | `proposal` 의 근거 키 |
| `refs` | `apps`(카탈로그 앱만) | people·docs = 번호표만 | 키·이름 |

가림판 생성 뒤 검사(관문 G-R8): 직렬화 바이트에 사람 사전의 모든 이름(한글 2자 이상·ASCII 4자 이상)·who_key 형식·msg/doc 키 형식(PRIVACY §14.3 `forbidden:who_key`·`local_key`)·카나리아가 0건. 걸리면 내보내기 실패(rc 1, 필드 경로만 표시).

### 9.3 CSV

#### 9.3.1 공통 규칙

- 인코딩 UTF-8 **BOM 포함**, 줄 끝 CRLF(엑셀 한글 호환 — `.py`·`.json` 의 UTF-8 LF 규칙과 다른 이유). `csv.writer(f, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)`.
- 파일 이름은 ASCII(압축·공유 도구 호환), 첫 줄 = 한글 열 이름(아래 표의 '열'). 기계용 값은 같은 내용이 `report_model.json` 에 있다.
- 분은 정수, MM·비율은 §3.1 함수로 만든 글자(`0.99`), 날짜는 `YYYY-MM-DD`.
- **수식 주입 방어**: 글자 칸이 `=`·`+`·`-`·`@`·탭·CR 로 시작하면 앞에 `'` 를 붙인다(숫자 열 제외).
- 가림판 CSV 는 §9.2.4 의 가림판 모델에서 만든다.

#### 9.3.2 개인 CSV 15종

| 파일 | 열 |
|---|---|
| `monthly.csv`(월별) | 월 · 근무일 · 분모(분) · 근무(분) · 정규 · 연장 · 야간 · 휴일 · 귀속 · 미귀속 · 관측 · 추정 · MM · 로드율(%) · 가용일 · 초과(근무창 밖) · 초과(일 8시간) · 부분월 · 측정 품질 · 품질 사유 |
| `daily.csv`(일별) | 날짜 · 휴일 · 정규 · 연장 · 야간 · 휴일근무 · 근무 · 신뢰 높음 · 중간 · 낮음 · 관측 · 추정 · 미귀속 · 휴가 · 표식 |
| `units.csv`(단위업무) | 단위업무 ID · 제목 · 제목 출처 · 업무 영역 · 과제 · 역할 ID · 분야 코드 · 분야 · 기능 코드 · 기능 · 업무 유형 코드 · 업무 유형 · 참여 방식 · 분류 신뢰 · AX 연계 · 종류 · 시작 근거 · 시작 · 종료 근거 · 종료 · 등급 · 상태 · 리드(분) · 영업 리드(분) · 투입 · 관측 · 추정 · 병행도 · 기계 시간 · 선행 착수 · 차수 · 동료 수 · 표식 |
| `alloc_daily.csv`(업무별 일 투입) | 날짜 · 단위업무 ID · 꼬리표 · 분 — 팀 묶음 `alloc_daily` 와 같은 행 |
| `buckets_daily.csv`(미귀속 일별) | 날짜 · 버킷 · 꼬리표 · 분 |
| `rollup.csv`(계층 합계) | 월 · 수준(영역·과제·역할·유형) · 키 · 이름 · 분 · MM |
| `workflow_steps.csv`(워크플로우 단계) | 역할 ID · 번호 · 단계 코드 · 한글명 · 라벨 · 라벨 출처 · 종류 · 지지도 · 월 빈도 · 중앙 소요 · 75% 소요 · 관측 비율 · 들어오는 대기 중앙 · 작업 비중 · 병목 · Agentic 등급 · 서브에이전트 |
| `workflow_edges.csv`(전이) | 역할 ID · 앞 번호 · 뒤 번호 · 횟수 · 대기 중앙 · 되돌림 |
| `reviews.csv`(리뷰) | 종류(주·월) · 기간 키 · 시작 · 끝 · 근무 · 귀속 · 새로 시작 · 끝냄 · 미착수 · 초과 · 요약 출처 |
| `lead_overrun.csv`(리드 초과) | 기간 키 · 단위업무 ID · 제목 · 역할 ID · 영업 리드 · 기준 · 배수 · 초과 · 원인 |
| `peers.csv`(동료) | 번호 · 이름(가림판: 동료 #k) · 사내 · 공동 단위업무 · 공유 투입 · 의뢰 · 보고 · 대화 · 회의 · 과제 · 처음 · 마지막 |
| `agentic_matches.csv`(에이전트 매칭) | 에이전트 ID · 이름 · 단계 유형 · 등급 · 출처 · 규칙과 다름 · 역할 · 단위업무 수 · 관련 투입 · AI 근거 · 규칙 근거 |
| `agentic_needs.csv`(니즈) | 니즈 ID · 이름 · 로직 · 입력 · 출력 · 단계 유형 · 월 빈도 · 등급 · 출처 · 팀 제외 |
| `subagent.csv`(서브에이전트) | 역할 ID · 번호 · 단계 코드 · 라벨 · 반복성 · 입출력 · 도구 접근 · 검증 · 위험 · 점수 · 규칙 판정 · 최종 · 근거 · 확인 지점 |
| `ontology_edges.csv`(연관 관계) | 출발 종류 · 출발 · 관계 · 도착 종류 · 도착 · 근거 수 · 분 · 추론 |

#### 9.3.3 팀 CSV(요청 T-5 — 팀 서버 `team_tables\`)

| 파일 | 열(공유판에서 빠지는 열은 *) |
|---|---|
| `person_monthly.csv`(사람 월별) | 사람 라벨 · 월 · MM · 근무(분) · 정규* · 연장* · 야간* · 휴일* · 가용일* · 로드율* · 측정 품질 · 부분월 |
| `domain_monthly.csv`(영역 월별) | 영역 · 월 · MM · 측정 불충분 몫 MM |
| `project_people.csv`(과제 × 인원) | 과제 · 영역 · 사람 라벨 · MM |
| `roles.csv`(역할) | 역할 ID · 과제 · 분야 · 기능 · MM · 단위업무 수 · 중앙 리드 · 중앙 투입 |
| `activity_types.csv`(업무 유형) | 업무 유형 · 영역 · MM |
| `units.csv`(단위업무) | 사람 라벨 · 역할 ID · 단위업무 ID · 제목 · 시작 종류 · 종료 종류 · 등급 · 상태 · 리드(h) · 투입(분) · 병행도 |
| `agentic.csv` · `needs.csv` · `quality.csv` | §7.5·§7.7 표 열 |

### 9.4 자기완결 HTML

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>LM27 개인 보고서</title>
<style>/* web/common/lm27.css 내용 그대로 */</style>
</head>
<body data-variant="full" data-kind="personal">
<!-- LM27 report/1 · run 20261005-101500-3fa2 · built 2026-10-05T10:21:44+09:00 -->
<svg hidden aria-hidden="true">/* icons.svg 의 symbol 들 + §8.1.4 무늬 defs */</svg>
<header>…고정 껍데기(제목·변형 배지·기간 띠 자리)…</header>
<main id="app" tabindex="-1"></main>
<script type="application/json" id="lm27-data">{…보고서 모델(변형)…}</script>
<script type="application/json" id="lm27-drill">{"units": {"u_…": {…§6.10.3…}}, "days": {"2026-09-22": {…§6.10.2…}}}</script>
<script>/* web/common/lm27charts.js */</script>
<script>/* web/common/lm27ui.js */</script>
<script>/* web/app/report.js */</script>
</body>
</html>
```

- **데이터 섬 이스케이프**: `island(obj) = canon_bytes(obj).decode()` 를 `<`→`\u003c`, `>`→`\u003e`, `&`→`\u0026`, U+2028→`\u2028`, U+2029→`\u2029` 로 바꾼 것(LM24 저장형 XSS 실측 방어 계승 — `</` 만 바꾸는 방식은 `<!--<script` 이중 탈출을 허용했다). JS 는 `JSON.parse(document.getElementById('lm27-data').textContent)`.
- 인라인하는 JS·CSS 파일에 `</script`·`</style` 글자열이 없어야 한다(관문 G-R6 — 있으면 빌드 실패).
- `report.js` 는 데이터 섬이 있으면 오프라인 모드(드릴다운은 `lm27-drill` 섬에서, 없으면 '이 파일에는 근거 상세가 없습니다 — 로컬 앱에서 보세요'), 없으면 로컬 앱 API 모드.
- `built_at` 은 HTML 주석 한 줄에만 — 그 줄을 빼면 같은 입력의 두 내보내기가 같은 바이트(관문 G-R1).
- 크기 상한 `report.export.maxHtmlMb`(20): 넘으면 ① `lm27-drill` 의 `days` → ② `units` 의 `evidence` → ③ `units` 전체 순으로 빼고, 뺀 것을 머리 알림 줄에 적는다. 모델 본체는 빼지 않는다.
- 외부 참조 0(관문 G-R5): `http://`·`https://`·`//` 로 시작하는 `src`·`href`·CSS `url(` 이 없다. 아이콘·무늬는 인라인 SVG.
- 가림판 HTML 은 `data-variant="redacted"`, `lm27-drill` 섬에 `units` 의 증거 줄 없이 경계 코드·투입 내역만.
- 팀 보고서는 같은 구조에 `data-kind="team"`·`<title>LM27 팀 보고서</title>`·스크립트 `web/team/team.js`, 데이터 섬 `lm27-data` = team_data, `lm27-detail` = §7.8.2 `details`. TEAM §3.12 CSP `sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox` 아래에서 인라인 스크립트가 돈다(CSP 에 `script-src` 가 없으므로 인라인 허용).

### 9.5 화면·절 ↔ 데이터 계약

| 화면·절 | 가져오는 곳 | 모델·응답 필드 | 상류 출처 |
|---|---|---|---|
| 홈 › 다음 할 일 | `GET /api/next-actions` | `NextAction[]` | §5.7 — pc.json·manifest·move_ready·todo·outbox·bridge manual manifest·confirm_queue·current.json·config_warnings |
| 홈 › 수집 현황 | `GET /api/home` `.collect`·`.coverage` | §5.1.5 | manifest·heartbeat(TEAM §1.4·§1.6), coverage_ledger(COLLECTION §5) |
| 홈 › 능력 표 | `GET /api/home` `.matrix` | §5.1.3 | pc.json `capabilities`(TEAM §1.5, COLLECTION §4, COPILOT §7.13) |
| 홈 › 최근 분석 | `GET /api/home` `.analysis` | KPI 5 | report_model `months[as_of 달]`·`quality` |
| 홈 › 팀 | `GET /api/home` `.team` | 레지스트리 판·대기열 수·도달 | registry.json·outbox meta·pc.json `team_server_reach` |
| 수집 › 실행·결과 | 작업 이벤트 + `GET /api/collect/status` | 단계 결과·새 레코드 수 | COLLECTION §8.4 stage_result, TEAM §1.7 `CollectResult` |
| 수집 › 이 PC·번들 | `GET /api/collect/status` | pc·agents·pcs[]·arrival | TEAM §1.5·§1.6·§1.11·§1.12 |
| 수집 › 커버리지·할 일 | `GET /api/collect/coverage`, `/status.todo` | CH-H01·todo 표 | COLLECTION §5·§6 |
| 수집 › 수동 기록 | `POST /api/worklog` | — | COLLECT_PC §10 `worklog`, WORKTIME §2.7 |
| 분석 › 단계·결과 | `GET /api/analysis/run/<id>` | §5.3.5 | run_status.json(분석 파이프라인), ai_out stats(COPILOT §2.5), time run_meta audit(WORKTIME §7.5) |
| 분석 › 붙여넣기 | `/api/bridge/manual*` | 묶음 목록·반입 결과 | COPILOT §10 manifest |
| 개인 › 요약 KPI | `/api/report` `.months[m]`·`.quality`·`.units` | §6.2.1 | mm_month·team_tables·env_slots(WORKTIME §6·§5.6·§7.5) |
| 개인 › 월별·영역 구성·등급 | `.months`·`.tree.nodes[영역].min_by_month`·`.units[].grade` | CH-P02·P04·P17 | 〃 + labels |
| 개인 › 업무 트리 | `.tree`·`.projects`·`.roles`·`.units` | §6.3.1 | labels(분류 명세)·tasks.json·team_tables |
| 개인 › 수준 패널 | `.workflows.{domains,projects,roles,units}` | §4.2~4.3 | activity log(attrib `obs`·tasks) + ai_out workflow_label |
| 개인 › 리뷰 | `.reviews` | §4.4.2 | tasks·team_tables·ai_out review_text |
| 개인 › 동료 | `.peers`·`.refs.people` | §4.5 | tasks(peers)·evidence·person_dir |
| 개인 › 연관 그래프 | `.ontology` | §4.6 | activity log·peers·tasks.docs |
| 개인 › Agentic | `.agentic` | §4.7 | registry.agents·ai_out agentic_match |
| 개인 › 서브에이전트 | `.subagent`·`.workflows.roles[].steps[].subagent` | §4.8 | activity log·ai_out subagent_review |
| 개인 › 확인 질문 | `.queue` + `POST /api/queue/answer` | §6.9 | confirm_queue.json(WORKTIME §7.3) |
| 개인 › 근거 | `/api/report/day/*`·`/api/report/unit/*` (HTML: `lm27-drill`) | §6.10 | day_ledger·interval_ledger·tasks·evidence |
| 팀(로컬) › 주소·대기열·미리보기 | `/api/team/*` | TEAM §2.5~2.9 | TEAM 명세 함수 그대로 |
| 팀(로컬) › 서버 운영 | `/api/teamserver/*` | 상태·포트 진단 | TEAM §3.3·§3.4·§3.14 |
| 설정 | `/api/settings`·`/api/privacy/*`·`/api/calibration` | 레지스트리 메타 | 설정 레지스트리(§13 G-1)·PRIVACY §15.5·WORKTIME §8.3 |
| 팀 보고서 › KPI·영역·과제 | `/api/team` 또는 섬 `lm27-data` | `people`·`domains`·`projects`·`unattributed` | TEAM §4.4·§4.5·§4.9 |
| 팀 보고서 › 역할·유형·통계·해석 | 〃 | §7.8.1 `roles`·`role_matrix`·`activity_types`·`units_stats`·`interpretation` | TEAM 취합기(§13 T-4) |
| 팀 보고서 › agentic | 〃 `agentic` | §7.8.1 | 묶음 `agentic`(TEAM §4.7) |
| 팀 보고서 › 간트·드릴다운 | 〃 `gantt` + `/api/team/detail` 또는 섬 `lm27-detail` | TEAM §4.6 | 묶음 `units`·`alloc_daily`·`workflows` |
| 팀 보고서 › 측정 품질 | 〃 `quality.matrix` | §7.8.1 | 묶음 `quality`(이 문서 §4.9 값) |

---

## 10. 설정 키

이 문서가 소유하는 키(단일 설정 레지스트리에 그대로 등록 — 미등록 키 오류, 읽히지 않는 키 금지: 관문 G-R9). ★ = **미보정 정책값**(실측 근거 없음 — 화면 설정 옆 '미보정' 배지, 사용자 자료로 조정 대상).

### 10.1 화면(`ui.*`)

| 키 | 형 | 기본 | 뜻 |
|---|---|---|---|
| `ui.port` | int | `19280` | 로컬 앱 포트(127.0.0.1). 바꾸면 화면 서버 재시작 |
| `ui.portFallbackCount` | int | `9` | 기본 포트가 막히면 +1…+n 시도 |
| `ui.openBrowser` | bool | `true` | 기동 때 기본 브라우저로 열기 |
| `ui.idleShutdownMin` | int | `0` | 마지막 요청 뒤 자동 종료(0 = 끔) |
| `ui.jobPollMs` | int | `1000` | 작업 진행 읽기 주기 |
| `ui.jobEventsKeep` | int | `500` | 작업당 보관 이벤트 줄 |
| `ui.logKeepDays` | int | `14` | 화면 서버 로그 보관 |
| `ui.homeCoverageDays` | int | `35` | 홈 히트맵 일수 |
| `ui.autoReanalyzeAfterAnswers` | bool | `true` | 확인 질문 응답 뒤 빠른 재분석 자동 |
| `ui.reanalyzeDebounceSec` | int | `20` | 마지막 응답 뒤 기다림 |
| `ui.tableMaxRows` | int | `500` | 표 한 번에 보이는 행 |

### 10.2 보고서(`report.*`)

| 키 | 형 | 기본 | 뜻·근거 |
|---|---|---|---|
| `report.defaultRangeMonths` | int | `3` | 분석 화면 기본 기간(이번 달 포함 최근 n개월) — 기간 출처 '기본값' 으로 표시 |
| `report.analysisKeep` | int | `10` | 분석 결과 보관 수(분석 파이프라인이 정리할 때 따름) |
| `report.export.formats` | list | `["html","csv","json"]` | 내보내기 형식 |
| `report.export.variants` | list | `["full","redacted"]` | 내보내기 변형 |
| `report.export.keep` | int | `10` | `out\personal\` 보관 폴더 수 |
| `report.export.maxHtmlMb` | int | `20` | 자기완결 HTML 상한(§9.4) |
| `report.export.maxModelMb` | int | `32` | 모델 상한(§9.2.2) |
| `report.csv.bom` | bool | `true` | CSV BOM |
| `report.drill.maxEvidencePerUnit` | int | `200` | 단위업무 근거 줄 상한 |
| `report.mining.minStepSec` | int | `600` ★ | 단계로 치는 최소 Run(10분) |
| `report.mining.maxSteps` | int | `8` | 역할 워크플로우 최대 단계(COPILOT `workflow_label` steps ≤ 8 과 같음) |
| `report.mining.minSupportRatio` | float | `0.3` ★ | 단계 지지도 문턱 |
| `report.mining.maxEdges` | int | `12` | 그리는 전이 수 |
| `report.mining.waitBottleneckMin` | int | `480` ★ | 대기 병목(영업 분, 1영업일) |
| `report.mining.workBottleneckShare` | float | `0.4` ★ | 작업 병목 비중 |
| `report.mining.minUnitsForBottleneck` | int | `3` | 병목 판단 최소 단위업무 |
| `report.mining.handoffWd` | int | `3` ★ | 역할 인계·선행함 근무일 |
| `report.mining.extClassExtra` | dict | `{}` | 확장자 → 확장자군 추가(§3.3) |
| `report.review.leadOverrunRatio` | float | `1.5` ★ | 리드 초과 배수 |
| `report.review.baselineMonths` | int | `6` | 기준 표본 기간 |
| `report.review.baselineMinUnits` | int | `3` | 기준 최소 표본 |
| `report.review.lateStartWd` | int | `3` ★ | 착수 지연 |
| `report.review.parallelHigh` | float | `3.0` ★ | 병행 원인 |
| `report.review.scopeRatio` | float | `1.5` ★ | 작업량 원인 |
| `report.review.maxFacts` | int | `25` | 리뷰 사실 상한(COPILOT §8.5 facts ≤ 25) |
| `report.peers.minMsgs` | int | `2` ★ | 대화 관계 최소 메시지 |
| `report.peers.maxMeetingSize` | int | `10` ★ | 회의 관계 최대 인원 |
| `report.peers.topN` | int | `20` | 화면 상위 동료 |
| `report.ontology.weights` | dict | `{"doc":0.4,"peer":0.3,"app":0.1,"seq":0.2}` ★ | 연관도 가중치(합 1.0 검증) |
| `report.ontology.minRel` | float | `0.25` ★ | 추천 문턱 |
| `report.ontology.sameWorkRel` | float | `0.6` ★ | 같은 일 의심 문턱 |
| `report.ontology.appMinMin` | int | `15` | '사용함' 최소 분 |
| `report.ontology.topN` | int | `12` | 바깥 고리 노드 수 |
| `report.ontology.maxUnits` | int | `40` | 단위업무 노드 상한 |
| `report.agentic.gradeHigh` · `gradeMid` | float | `0.8` · `0.5` ★ | 규칙 등급 문턱 |
| `report.subagent.fitScore` · `condScore` | int | `7` · `5` ★ | 적합·조건부 점수 문턱 |
| `report.subagent.roleFitShare` | float | `0.5` ★ | 역할 '적합' 분 비율 |
| `report.quality.covLow` · `covBad` | float | `0.8` · `0.5` ★ | 커버리지 주의·불충분 |
| `report.quality.estLow` · `estBad` | float | `0.25` · `0.5` ★ | 낮은 신뢰 비율 |
| `report.quality.unattrHigh` | float | `0.3` ★ | 미귀속 비율 |
| `report.quality.noEvidenceDays` | int | `2` | 무근거 근무일 |
| `report.quality.samplerLow` | float | `0.5` ★ | 샘플러 있는 날 비율 |

### 10.3 팀 보고서(`team_report.*` — 팀 서버 쪽)

| 키 | 형 | 기본 | 뜻 |
|---|---|---|---|
| `team_report.shiftPp` | float | `5.0` | TI-02 영역 비중 변화 문턱(%p) |
| `team_report.concentrationShare` | float | `0.4` | TI-03 역할 집중 |
| `team_report.officeShareNote` | float | `0.3` | TI-04 사무 비중 |
| `team_report.unattributedNote` | float | `0.15` | TI-05 미귀속 |
| `team_report.axLinkNote` | float | `0.1` | TI-06 AX 연계 |
| `team_report.smallProjectMm` | float | `0.3` | 과제 표에서 접는 작은 과제 |
| `team_report.ganttExpandRows` | int | `150` | 간트 기본 모두 펼침 행 수 |
| `team_report.maxDetailMb` | int | `12` | 자기완결 보고서 드릴다운 섬 상한 |

### 10.4 이 문서가 읽기만 하는 다른 명세의 키

`time.tzOffsetMin`·`time.window.*`(근무창·정규 구역), `mm.stdDayMin`·`mm.denominator`·`mm.overtimeBasis`(WORKTIME §8.2), `episode.reviewWords`(REVIEW 단계 판정), `team.server_host`·`team.server_port`·`team.server_alternates`·`team.self_label`·`team.member_id`·`team.unit_title_mode`·`team.share_unknown_apps`·`team.auto_send`·`team.allow_public_host`·`team.registry_refresh_h`(TEAM §7.1 — 팀 화면이 편집), `team_server.*`(TEAM §3.2 — 서버 운영 카드가 편집), `team_server.gantt_merge_gap_days`(간트 active 이음), `agent.heartbeat_stale_s`, `bridge.mode`(COPILOT §3), `privacy.*`(설정 › 개인정보).

---

## 11. 예외 처리

| 상황 | 처리 | 화면 |
|---|---|---|
| `current.json` 없음 | 보고서 화면 빈 상태 | "아직 분석 결과가 없습니다" |
| `current.json` 이 가리키는 실행 폴더가 없음(정리됨) | 남은 실행 중 기준 시각이 가장 늦은 것을 고르지 **않는다**(조용한 대체 금지) — 빈 상태 + 이력 목록 | "보던 결과(…)가 정리되었습니다 — 이력에서 고르세요" |
| 보고서 모델 판이 다름·없음 | `report_build` 자동 1회 | "보고서를 새 형식으로 다시 만드는 중" |
| 시간 결과 파일 없음·깨짐 | `report build` rc 1, 이전 보고서 유지 | 분석 화면 '보고서 만들기 실패(시간 결과 없음)' |
| `labels` 없음 | 모두 UNC·시간 코어 라벨, 경고 | 머리 알림 '분류 결과가 없어 모두 미분류로 보입니다' |
| `attrib.obs` 없음 | §4.1.4 거친 마이닝 + `mining_coarse` | 워크플로우 절 머리 알림 |
| `ai_out` 단계 없음·깨짐 | 그 단계 폴백(§4.10.3), JSON 깨짐은 경고 1줄 | 라벨 출처 `규칙` |
| 레지스트리 없음 | 과제 이름 = ID, 에이전트 목록 없음, 단계 이름 = 한글명 | 배너 + 다음 할 일 N14 |
| 레지스트리 달력 판 ≠ 시간 결과 달력 판 | 숫자는 시간 결과 그대로(개인 MM 은 그 달력으로 계산됨), 경고 | '달력 판이 다릅니다(분석 kr-2026.2 / 현재 kr-2026.3) — 다시 분석하면 맞춰집니다' |
| 그 달 가용 0 | 로드율 `—` + `가용 0` | — |
| 그 달 봉투 0 | MM `0.00`, 품질 `no_envelope` | 신뢰도 카드 '이 달은 근무시간이 계산되지 않았습니다' |
| 단위업무 0개 | 트리·워크플로우·Agentic·서브에이전트 절 빈 상태 | "이 기간에 만들어진 단위업무가 없습니다(근무 중 미분류 n h)" |
| 역할 단위업무 1~2개 | 마이닝은 하되 `sample='thin'`, 병목 생략 | 캡션 '표본 부족' |
| 같은 unit_id 가 두 실행에서 다른 역할 | 지금 실행 값만 쓴다(보고서는 실행 하나) | — |
| 사람 사전 없음 | 동료 이름 = `동료 #k` | 동료 절 안내 |
| 모델 등식 검사 실패(§9.2.2) | rc 1, 보고서 안 만듦, 이전 유지, 오류 보고(경로·차이 분) | "보고서 검사에 실패해 이전 보고서를 그대로 보여 줍니다" |
| 내보내기 쓰기 실패(권한·공간) | 그 파일만 실패 목록, `.part` 정리 | 실패 파일과 이유 |
| 자기완결 HTML 상한 초과 | §9.4 순서로 줄임 | 파일 머리 알림 |
| 가림판 검사 실패(이름·키 검출) | 가림판 만들지 않음(rc 1), full 은 만듦 | "가림판에서 지워지지 않은 이름이 발견되어 만들지 않았습니다(필드: peers.internal[3].name)" — 값은 보이지 않음 |
| 화면 API 오류(5xx) | 그 카드만 오류 상태 + [다시 읽기], 다른 카드는 정상 | 카드 오류 문구 |
| 작업 하위 프로세스가 결과 없이 끝남 | 작업 `failed`, rc·마지막 이벤트 보존 | 작업 서랍 |
| 브라우저 `localStorage` 막힘 | 기본값으로 동작(try/catch) | — |
| 클립보드 API 실패 | 글 상자 열기(직접 복사) | COPILOT §10.5 |
| 팀 서버 `/api/team/detail` 404(그 사람·역할 없음) | 서랍에 '이 업무의 워크플로우가 묶음에 없습니다(규칙 이전 판 묶음)' | — |
| 팀 데이터 `warnings` 있음 | 머리 배지(개수) + 목록 | — |
| 매우 큰 팀(사람 > 60, 간트 행 > 2000) | 간트는 첫 계층만 펼침, 행 가상화(보이는 행 ±50만 마운트) | — |

---

## 12. 시험 시나리오와 관문

모든 시험은 `%TEMP%` 복제 트리에서 합성 자료로만 돈다(`assert ROOT != 실제 설치 경로`, 실제 메일·팀즈 수집 금지 — TEAM §9 와 같은 규칙). 시간 결과 입력은 WORKTIME §9 시나리오 83개의 참조 구현 출력(`design\worktime\golden.json`)과 이 문서 시제품 픽스처(`design\reports\golden_report.json`)를 쓴다.

### 12.1 시나리오

| # | 시나리오 | 입력 | 기대 |
|---|---|---|---|
| RPT-01 | 결정성 | 같은 실행으로 `report build --force` 2회, `report export` 2회 | 모델 바이트 동일, HTML 은 `built` 주석 줄만 다름 |
| RPT-02 | 입력 순서 무관 | attrib 행·tasks 목록·사람 사전 키 순서 섞기 4회 | 모델 sha 동일 |
| RPT-03 | 결과 선택 | ① current 없음 ② explicit 선택 ③ 가리키는 실행 폴더 삭제 | ① 빈 상태 ② 재기동 후에도 같은 실행 ③ 빈 상태 + 이력(다른 실행으로 조용히 바꾸지 않음) |
| RPT-04 | 기간 출처 | 기본 기간으로 분석 | 머리 띠 `기간 출처: 기본값(최근 3개월)` |
| RPT-05 | 보고서 판 | `report_version` 이 다른 모델 | `report_build` 자동 1회, 코파일럿 호출 0 |
| RPT-10 | 개인 = 팀(G-R2) | WORKTIME 시나리오 83개 + 퍼즈 1,000 | 모든 달: `months.env_min` = Σ envelope_daily, `attributed+unattr = env`, `obs+est = attributed`, 단위업무 `effort = Σ alloc`, `fmt_mm` 이 팀 재합산 MM 의 같은 표시 문자열 |
| RPT-11 | 표시 함수 | §3.1 골든 + 교차 11,530 사례 | 파이썬 = JS 불일치 0 |
| RPT-12 | 팀 묶음 일치(RP15) | 같은 모델로 팀 묶음 빌드 | 묶음 `workflows`·`agentic`·`peers`·`quality` 값 = 모델 값 |
| RPT-13 | 미분류 숨김 없음 | 버킷 5종 + 과제 키워드와 맞는 B_MEET | 트리 맨 아래 '근무 중 미분류' 행 5개, B_MEET 분이 과제 MM 에 더해지지 않음(주석만) |
| RPT-14 | 영업 분 | §3.2 골든 3건 | 180 · 60 · 1920 |
| RPT-15 | 마이닝 골든 | §4.2.3 의 4개 단위업무 | 단계 5개(순서·n·중앙 소요 210·105·60), 전이 6개(되돌림 3→2), 대기 병목 3(720분), 작업 병목 2(0.56), 버린 Run 2개(COMM 5분·DOC_PPT 8분) |
| RPT-16 | 표본 부족 | 같은 역할 단위업무 2개 | `sample = thin`, 병목 없음, 캡션 '표본 부족' |
| RPT-17 | 단계 상한 | 한 역할에 단계 유형 11개(모두 지지도 충족) | REQ_IN·REPORT_OUT 포함 8개 남김, 나머지 `dropped`, 캡션 |
| RPT-18 | obs 없음 | `attrib` 에 obs 열 없음 | §4.1.4 거친 단계 + `mining_coarse` 경고(화면·묶음 reasons) |
| RPT-19 | 과제 인계 | u_a2(해석, 09-16 끝) → u_b1(설계, 09-17 시작, 문서 f3 공유) | 인계 1건 via doc, 대기 근무일 1 |
| RPT-20 | 리드 초과 | §4.4.3 골든 | u_a4 초과 아님(3300 ≤ 3540), u_a5 초과 `WAIT·REWORK·PARALLEL·LATE_START`, 같은 역할 완료 2건뿐이고 영역·기능도 2건 → `NO_BASELINE` |
| RPT-21 | 색 외 부호 | 모든 차트 명세 골든 | 추정 마크에 `hatch-est` 무늬, 미귀속에 `hatch-unattr`, 상태 칸에 아이콘 `<use>` + 글자, 그래프 노드 종류별 모양 다름 — vnode 검사 |
| RPT-22 | 연관도 | §4.6.2 골든 | rel 0.5833 · 0.55 · 0. u_a1 의 추천 = u_a2 '이어진 일'(아래 주), u_a2 의 추천 = u_a1 '이어진 일'·u_b1 '이어진 일', u_a1~u_b1 은 문턱 0.25 미만이라 추천 없음 |
| RPT-23 | 서브에이전트 | §4.8.4 골든 | 단계 판정 5개, 역할 규칙 '조건부', AI '적합' → 최종 조건부, AI '부분' → 조건부, AI '부적합' → 부적합 |
| RPT-24 | agentic | 카탈로그 3개(단계 유형 일치·불일치·핵심어만) | 규칙 등급 중·없음·하, AI 가 '상' 준 불일치 칸에 `disagree`, 규칙 니즈 1건(주 1~2회·D=1·조건부 이상·매칭 없음), 카탈로그 이름과 같은 니즈 버림, need_id 재분석 동일 |
| RPT-25 | 차트 골든(node) | CH-P02·CH-P07(§4.2.3)·CH-T08(줄 골든) 명세 | `toString(vnode)` 이 골든 문자열과 같음, 밀도 단계 119→1·120→2·1199→4·1200→5 |
| RPT-26 | 측정 품질 | 합성 달 4개(정상·팀즈 70%·PC 40%·봉투 0) | reliable · caution(`teams_cov_low`) · unreliable(`pc_cov_bad`) · unreliable(`no_envelope`) |
| RPT-27 | 동료 | CC 만 받은 사람, 30명 회의 참석자, 대화 1건 사람, 의뢰자 | 앞 셋 제외, 의뢰자만 동료, 정렬 규칙 |
| RPT-28 | 리뷰 사실·코파일럿 입력 | 한 달 단위업무 40개 | facts 25개(완료→시작→진행→보류 순), `ai_in` 에 시간형 숫자(`\d+(\.\d+)?\s*(MM\|시간\|h\|분)`) 0건 |
| RPT-29 | 폴백 한 벌 | `ai_out` 없음 | 모든 라벨 `by=rule`, 문장 = 브리지 단계 `fallback()` 결과와 바이트 동일, 브리지 단계 모듈 임포트 뒤 소켓·파일 쓰기 0 |
| RPT-30 | 악성 문자열 | 단위업무 제목 `</script><img src=x onerror=alert(1)>`, 동료 이름 `<svg onload=alert(1)>`, 과제 이름에 U+2028 | 데이터 섬에 `<` 원문자 0개(모두 `\u003c`), 렌더 뒤 DOM 에 데이터에서 온 `img`·`svg onload` 요소 0, 글자로만 보임 |
| RPT-31 | 가림판 | 사람 사전 이름 20개·카나리아 3종을 심은 자료 | `report_redacted.html`·`report_model_redacted.json`·`csv_redacted\*` 에 이름·카나리아·who_key·local_key 형식 0건 |
| RPT-32 | CSV | 제목 `=1+1`·`-합계`·`@SUM` | 셀 `'=1+1` 등, 파일 BOM·CRLF, 엑셀에서 한글 깨짐 없음(수동 확인 1회) |
| RPT-33 | 금지 표현 | 모든 산출물 | '대체 가능'·'절감'·'AX 가능 MM' 문자열 0건 |
| RPT-34 | 외부 참조 0 | 모든 HTML | `http://`·`https://`·`//` 자원 참조, CSS `url(http` 0건 |
| RPT-35 | HTML 상한 | 상한을 1MB 로 낮춘 내보내기 | days 섬 → 증거 → units 순으로 빠지고 머리 알림, 모델 본체 유지 |
| RPT-36 | 로컬 앱 보안 | ① Host `evil.example:19280` ② 토큰 없는 POST ③ `text/plain` POST ④ OPTIONS ⑤ `/static/../config/config.json` | 421 · 403 · 415 · 405 · 404 |
| RPT-37 | 포트 | 19280 을 다른 소켓이 잡음 / 19280~19289 모두 잡음 | 19281 로 기동·ui_server.json 기록 / rc 3 + diagnose 문구 |
| RPT-38 | 단일 인스턴스 | 같은 ROOT 로 두 번 기동 | 두 번째는 서버를 띄우지 않고 브라우저만 |
| RPT-39 | 작업 | ① 수집 중 분석 요청 ② 분석 취소 ③ 서버 재기동 | ① 409 busy ② `cancelled`, 다음 분석이 재개 ③ 최근 작업 20건 표시 |
| RPT-40 | 문구 규칙 | `web/**`·`lm27/ui/**` 문자열 | '개발자에게'·'재설치'·성공 문구의 `[!]` 0건 |
| RPT-41 | 다음 할 일 | 합성 상태(에이전트 멈춤·도착 누락·로그인 필요·질문 3건·승인 대기) | N04·N05·N07·N11·N15 가 등급 순서(risk → improve)로, 같은 대상 중복 없음 |
| RPT-42 | 능력 표 해당 여부 | PC1 역할 `pc_usage, mail_local, teams_window` | `mail.owa`·`teams.web`·`*.copilot` 칸 '해당 없음', pc.json 에 없는 키 '미확인' |
| RPT-43 | 팀 주소 | ① `8.8.8.8:9310`(allow_public_host=false) ② 포트 70000 ③ [기본값으로] ④ 토큰 저장 후 GET | ①② 저장 거부 + 이유 ③ 정확히 `10.115.147.68:9310` ④ 응답에 토큰 값 없음 |
| RPT-44 | 팀 보고서 | 합성 팀 8명(측정 불충분 1명, 9월 개발 비중 +8%p) | TI-01·TI-02·TI-08 문장 골든, 공유판에 `load_pct`·초과 열 0회, 피벗 전후 막대 집합 동일, 측정 불충분 몫 빗금·비교 표 제외 |
| RPT-45 | 간트 드릴다운(LM24 결함 회귀) | 같은 역할을 하는 2명 | A 의 막대를 누르면 A 의 워크플로우(단계 라벨·n)가 열리고 팀 합의 체인이 아님. 자기완결 보고서에서도 `details` 섬으로 같음 |
| RPT-46 | 성능 | 1명 3개월(단위업무 300·신호 4.3만) / 팀 30명 12개월 | `report build` ≤ 10초, `report_full.html` ≤ 20MB, 첫 화면 그리기 ≤ 2초(개발 PC) / `team_report.html` ≤ 15MB(LM24 30명 8.7MB 문제 재발 감시), 간트 첫 그리기 ≤ 3초 |
| RPT-47 | 접근성 | §12.3 점검표 | 전 항목 통과(수동, 배포 전 1회) |
| RPT-48 | 확인 질문 | Q01 응답(오프라인 지시 시각) → 빠른 재분석 | worklog 에 `instr` 레코드(증거 키), 그 단위업무 등급 E → B(WORKTIME W47a), 재분석으로 unit_id 가 바뀌어도 응답 유지 |
| RPT-49 | 분류 고치기 | 단위업무 하나를 [분류 고치기]로 과제 P-0007·범위 `비슷한 업무도` | `corrections.jsonl` 에 증거 키 기록, 빠른 재분석(분류부터) 뒤 같은 대화방의 다른 단위업무도 P-0007(HIERARCHY H36·H37), 트리 분류 배지 '확인됨', 가림판·팀 묶음에 `why` 없음 |
| RPT-50 | 관리 화면 | ① 두 창에서 같은 판 저장 ② 근거 URL 없는 공휴일 ③ `P-9903` 새 과제 | ① 두 번째 409 + 최신 판 재적용 안내 ② 저장 거부 ③ `reserved_id` 오류 |

RPT-22 주: u_a1~u_a2 는 rel 0.5833 < 0.6 이라 '같은 일 의심'이 아니고 seq = 1 이라 '이어진 일'이다(§4.6.3 표의 첫 번째로 맞는 종류).

### 12.2 관문

| 관문 | 내용 | 실패 시 |
|---|---|---|
| **G-R1 결정성** | RPT-01·02 | 머지 차단 |
| **G-R2 개인 = 팀·등식** | RPT-10 + 모델 등식 assert(§9.2.2)를 실제 분석에서도 상시 | 보고서 생성 중단(rc 1, 이전 유지) / 머지 차단 |
| **G-R3 JS** | `node --check web/**/*.js` + RPT-25 vnode 골든(개발 PC 전용 — 배포물에는 node 불필요) | 머지 차단 |
| **G-R4 위험 API** | `web/**/*.js` 에 §8.6.3 금지어 0건, `lm27/**/*.py` 의 HTML 껍데기에 값 직접 삽입 0건(AST: f-string·`%`·`.format` 으로 HTML 문자열에 변수 결합 금지 — `export.py`·`team/report.py` 의 섬 삽입 함수 1곳만 예외) | 머지 차단 |
| **G-R5 외부 참조 0** | RPT-34 | 머지 차단 |
| **G-R6 데이터 섬** | 섬 문자열에 `<`·`>`·`&`·U+2028·U+2029 원문자 0, 인라인 JS·CSS 파일에 `</script`·`</style` 0 | 빌드 실패 |
| **G-R7 색·대비** | 색 16진 값은 `web/common/lm27.css`·`lm27/hier/vocab.py`(`DOMAIN_META`) 에만, `DOMAIN_META` 의 색이 §8.1.3 표와 같음, §8.1 토큰 쌍 대비 표를 `tools/check_contrast.py`(WCAG 2.1 상대 휘도 식, 표준 라이브러리)로 재계산해 표의 하한 이상, 범주 팔레트 순서가 §8.1.3 과 같음 | 머지 차단 |
| **G-R8 이름·카나리아** | RPT-31 + 팀 묶음 경로는 TEAM·PRIVACY 관문 | 내보내기 실패 / 머지 차단 |
| **G-R9 설정 read-check** | §10 의 모든 키가 코드에서 읽히고, 섭동하면 결과(모델 서명·화면 상태)가 바뀌며, 코드가 읽는 `ui.*`·`report.*`·`team_report.*` 키가 모두 등록 | 머지 차단 |
| **G-R10 단일 로더** | `lm27/report/**`·`lm27/ui/**` 에서 `data` 경로 상수를 `os.path.join`·`open(`·`Path(...) /` 로 조립 0건(AST), 읽기는 `lm27.paths`·각 명세 로더로만 | 머지 차단 |
| **G-R11 표시 함수** | `toFixed(` 0건, 파이썬 `round(` 은 `fmt.py` 안에서만, RPT-11 | 머지 차단 |
| **G-R12 폴백 한 벌** | RPT-29 + `lm27/report/**` 에 브리지 단계 폴백 문장 템플릿 사본 0건(브리지 `stages/*.py` 의 템플릿 문자열을 grep) | 머지 차단 |

### 12.3 접근성 점검표(배포 전 수동 1회 + 바뀐 화면마다)

| # | 점검 |
|---|---|
| KB-1 | 마우스 없이 홈 → 수집 → 분석 → 개인 보고서(10개 절) → 팀 → 설정을 모두 오가고, 모든 버튼을 누를 수 있다 |
| KB-2 | 트리 표: 방향키로 이동·펼침·접기, Enter 로 수준 패널 |
| KB-3 | 간트: Tab 으로 막대, ←/→·↑/↓ 이동, Enter 로 서랍, Esc 로 닫고 초점 복귀 |
| KB-4 | 모든 차트에 '표로 보기'가 있고 화면 낭독기가 제목·한 줄 요약을 읽는다 |
| KB-5 | 200% 확대에서 페이지 가로 스크롤 없음(카드 안 스크롤만) |
| KB-6 | 윈도우 고대비 모드에서 막대·칸·상태가 구분된다(무늬·테두리·아이콘) |
| KB-7 | 흑백 인쇄(또는 회색조 필터)에서 관측/추정/미귀속·등급·판정이 구분된다 |
| KB-8 | 초점 고리가 모든 상호 요소에서 보인다 |
| KB-9 | 확인 질문 응답 폼: 라벨·오류 문구가 낭독되고, 오류 시 초점이 첫 오류 칸으로 |

---

## 13. 형제 명세에 요청하는 것(정합)

| 번호 | 대상 | 요청 | 이유 | 반영 전 동작 |
|---|---|---|---|---|
| W-1 | WORKTIME | `attrib.jsonl` 행에 `obs`(§3.3 단계 코드 — `lm27/vocab/steps.py: obs_of(level, cls, ext_class, anchor_kind, meeting_role)`), `app`(그 슬롯·그 업무의 최다 app_id), `fam`(최다 문서군 키) 열 추가 → `timecore/1.1`(MINOR) | 과정 마이닝·agentic·온톨로지가 단계·앱·문서를 슬롯 단위로 알아야 한다. L3 조각을 훑는 시간 코어가 이 값을 이미 손에 쥐고 있다 | §4.1.4 거친 마이닝 |
| W-2 | WORKTIME §7.5 | 결과 위치 `data\analysis\<run_id>\time\` → `data\derived\analysis\<run_id>\time\`(TEAM §1.1 번들 배치의 파생물 자리) | 번들 배치 단일화 | `lm27.paths` 한 곳에서 대응 |
| W-3 | WORKTIME §5.4 | B_MEET '롤업 단계 과제 직접 귀속' 선택지를 MM 숫자에는 쓰지 않는다고 명시 | 개인 = 팀 보존(팀 묶음 alloc 은 단위업무만) | 보고서는 주석으로만 보임(RP16) |
| W-4 | WORKTIME §7.5 `tasks.json` | 단위업무별 `peers` 에 관계 꼬리표(requester·reporter·thread·meeting)와 `docs` 에 조작 수(save·export·attach) | §4.5·§4.6 계산 재료 | 보고서가 증거(정규화 레코드)에서 다시 계산(느림) |
| W-5 | WORKTIME §6.4 · TEAM §2.3.2 | 가용일 정의 일치(오늘 경과 비율 포함 여부) | 분석 당일 개인·팀 로드율 차이 | 미결 R-Q4 |
| T-1 | TEAM §3.10 | 레지스트리 `vocab.step_types` = §3.3 코드, 한글명 `vocab.step_type_names{code: 이름}`, 선택 `vocab.step_tool_access`·`vocab.step_verifiable` | 코파일럿 프롬프트(코드 + 한글명)·팀 검증·화면이 같은 어휘 | 보고서는 코드로 쓰고 한글명은 `lm27/vocab/steps.py` 기본값 |
| T-2 | TEAM §2.3.2 | `workflows[].steps[].why[]` 어휘에 `tool_access` 추가(MINOR 1.1) | §4.8 TOOL 기준 | 반영 전에는 `tool_access` 를 싣지 않음 |
| T-3 | TEAM §2.3 | `workflows[].steps[]` 에 선택 필드 `wait_in_median_min`·`work_share`·`bottleneck`(`wait`·`work`·`both`·`""`), `workflows[]` 에 `sample`(`ok`·`thin`) (MINOR) | 간트 드릴다운에서 개인 화면과 같은 병목 표시 | 팀 패널에서 대기·병목 생략 |
| T-4 | TEAM §4.9 | `team_data.json` 의 `roles`·`role_matrix`·`activity_types`·`units_stats`·`agentic`·`quality.matrix`·`interpretation` 형을 §7.8.1 로, `render_team_report` 가 `details` 섬(§7.8.2) 포함 | 팀 보고서 절(C)의 렌더 계약 | — |
| T-5 | TEAM §3.9·§3.7 | `out\gen_N\team_tables\*.csv`(전체·공유) 산출 | 요구 (E) CSV | 대시보드 '표로 보기'만 |
| T-6 | TEAM §3.12 | 고정 사전에 `/static/lm27charts.js`·`/static/lm27ui.js`·`/static/lm27.css` 추가(파일은 `web/common/`) | 렌더러 한 벌(RP10) | — |
| T-7 | TEAM §3.4 | `suggest_port` 의 회피 집합에 설정 `ui.port` 와 실제 `ui_server.json.port` 둘 다 | 화면 서버가 대체 포트로 떠 있을 때 충돌 방지 | — |
| T-8 | TEAM §2.3 | 선택 `units[].effort_obs_min`(관측 분) (MINOR) | 팀 간트의 추정 빗금·관측 비율 | 팀 간트는 빗금 없이 |
| T-9 | TEAM §2.3.1 `quality` | `quality.grade`·`reasons` 계산을 이 문서 §4.9 가 소유함을 명시 | 정의 부재 | — |
| B-1 | COPILOT §8.7 | `subagent_review` 플래그에 `T`(도구 접근) 추가 → `subagent_review/1.1`(머리말 플래그 설명 줄 1줄 추가, 내용 키 주판은 그대로) | 요구의 '도구 접근' 기준 | T 없이 보내고 규칙 판정에서만 반영(§4.8.3 하드 조건) |
| B-2 | COPILOT §2.2·§15 | `lm27/bridge/stages/*.py` 임포트 무부작용(세션·소켓·파일 쓰기 없음)과 `fallback(item, ctx, why)` 이 세션 없이 호출 가능함을 관문으로 | 보고서 폴백 한 벌(§4.10.3) | — |
| B-3 | COPILOT §16 Q13 | 단계 유형 어휘·D·R·B·L·S 계산 정의 = 이 문서 §3.3·§4.8 로 해소 | — | — |
| B-4 | COPILOT §8.4 | `workflow_label` 입력 `steps` 의 세 번째 값이 '관측 횟수(지지도)'임을 확인 — 분이 아님 | B1(시간 미전송) | — |
| C-1 | HIERARCHY §12.1 | 결과 위치 `data\analysis\<run_id>\hier\` → `data\derived\analysis\<run_id>\hier\`(W-2 와 같은 규칙) | 번들 배치 단일화 | `lm27.paths` 대응 |
| H-1 | HIERARCHY §1.2 `DOMAIN_META` | 영역 색 값을 §8.1.3 검증값으로: MP `#c47400`, COM `#a61b4a`, UNC `#8b929b`(DEV·EXT·AX 그대로) | 원안 값이 팔레트 검사 실패(대비·채도·인접 구분) | 보고서는 `domain_color()` 값을 그대로 쓰되 G-R7 관문이 불일치를 머지 차단 |
| H-2 | HIERARCHY §17.3 Q5 | `step_types` 어휘 = 이 문서 §3.3(`lm27/vocab/steps.py`)으로 확정 | 그쪽 미결 해소 | — |
| H-3 | HIERARCHY §17.3 Q8 | 팀 서버 `/admin`(레지스트리 편집·제안 묶음) 화면 = 이 문서 §7.9 | 그쪽 미결 해소 | — |
| H-4 | HIERARCHY §11.3·§12.5 | 분류 수정 뒤 빠른 재분석이 분류(규칙 — 코파일럿 없음)부터 다시 돈다는 실행 계약(`analyze --rerun <id> --stages classify,time,mining,report --no-ai`) | 학습 규칙이 증거 꼬리표를 바꿔 시간 결과까지 바뀔 수 있음 | 다음 전체 분석 때 반영 |
| A-1 | 분석 파이프라인 명세 | `run_status.json` 형(§5.3.2)·단계 ID·`current.json` 갱신 규칙(§2.4.3)·`analyze --rerun <id> --stages …`(빠른 재분석) | 분석 화면·확인 질문 재분석 | 분석 화면은 작업 이벤트만으로 표시 |
| L-1 | COLLECTION §8.4 | `stage_result_<stage>.json` 위치를 `data\derived\collect\<run_id>\` 로(LM24 식 `report\` 폐기) | 번들 배치 단일화 | `lm27.paths` 대응 |
| L-2 | COLLECT_PC §10 · TEAM §1.15 | 수동 기록 `retract`(취소) 레코드와 로더의 취소 반영 | 세그먼트 불변 + 수동 기록 정정 | 화면에서 취소 버튼 숨김 |
| P-1 | PRIVACY §1.3 I1 | 개인 보고서 전체판(`report_full.html`·`report_model.json`·`csv_full\`)을 `person_dir` 과 같은 '로컬 전용 산출물'로 목록에 추가(반출 금지 대상) | 동료 이름 포함 | 화면·파일 머리 안내로만 |
| G-1 | 설정 레지스트리(공통 계약) | 항목 메타 `group`·`label_ko`·`help_ko`·`type`·`default`·`range\|choices`·`uncalibrated`·`secret`·`scope`·`restart` | 설정 화면 자동 생성(§5.6.2) | 화면이 키 이름만 표시 |

---

## 14. 미결(사용자·오케스트레이터 확인 필요)

| # | 질문 | 이 문서의 기본 | 막히면 |
|---|---|---|---|
| R-Q1 | 동료 실명이 들어간 개인 '전체판' 파일을 만들어도 되는가(내 PC 안 로컬 전용)? | 만든다(기본 `variants = full, redacted`), 머리 경고 | `report.export.variants = ["redacted"]` 로 전체판을 끔 — 로컬 앱 화면에서만 이름 표시 |
| R-Q2 | '같이 일한 동료'를 로컬 화면에서 사람 사전 이름으로 보이는 것이 허용되는가 | 보인다(로컬 전용) | `동료 #k` 만 |
| R-Q3 | 단계 유형 어휘(22종)·도구 접근·검증 가능성 기본값이 팀 업무에 맞는가(예: 사내 해석기에 배치 API 가 있으면 `APP_CAE` 도구 접근 2) | §3.3 표 | 레지스트리 덮어쓰기 |
| R-Q4 | 분석 당일 로드율의 개인(오늘 경과 비율 포함, WORKTIME)·팀(근무일 단위, TEAM) 차이를 어느 쪽으로 맞출지 | 개인 화면은 WORKTIME, 팀은 TEAM 식 그대로 + 툴팁 설명 | — |
| R-Q5 | ★ 정책값(마이닝 문턱·초과 원인·서브에이전트·품질)의 보정 방법 | 기본값 + 미보정 배지 | WORKTIME §8.3 보정 도구에 보고서 키 확장(정답 세트: 사용자가 '병목 맞음/아님' 표시) — 다음 판 |
| R-Q6 | 팀 보고서 해석 문장(코파일럿 없이 템플릿 8종)의 표현이 팀장이 원하는 수준인가 | §7.4.4 | 문장 끄기 설정 |
| R-Q7 | 다크 모드 필요 여부 | v1 미지원(LM20 언어) | 토큰을 다크 값으로 따로 검증해 추가 |
| R-Q8 | 분석 기본 기간 | 최근 3개월 | 설정 `report.defaultRangeMonths` |
| R-Q9 | 서브에이전트 최종 판정을 '규칙과 AI 중 보수적인 쪽'으로 하는 것 | 보수적 | AI 의견을 최종으로(규칙은 참고) — 설정 추가 필요 |
| R-Q10 | 연관 업무 '같은 일 의심'에서 [합치기 질문 만들기] 가 너무 자주 뜨는지 | rel ≥ 0.6 + 같은 역할 + 겹침/인계 | 문턱 상향 |
| R-Q11 | 팀 간트가 사람별 단위업무 투입을 팀 전체에 보이는 것(공유판에도 남음) | TEAM 공유판 정의(로드율·초과만 제거)를 따름 | 공유판에서 간트 사람 행을 '담당자-n' 가명으로 — TEAM 결정 필요 |
| R-Q12 | 'KPI 이번 달' 기본이 부분월(분석 기준 시각의 달)이어도 되는가 | 부분월 + 배지 | 마지막 완전한 달을 기본으로 |
| R-Q13 | 에이전트 카탈로그 초기 내용(저장소 기본은 중립 예시만)을 누가 채우는가 | 팀장(레지스트리) | 니즈 후보만 보임 |
| R-Q14 | 로컬 앱 포트 19280 이 사내 보안 도구(로컬 HTTP 차단)에 걸리는지 | 127.0.0.1 전용이라 대개 허용 | `ui.port` 변경·자기완결 HTML 로 대신 보기 |
| R-Q15 | 개인 보고서 '가림판'에 남는 단위업무 제목(팀 묶음과 같은 수준)이 공유에 충분히 안전한가 | 팀 묶음 제목 규칙과 같음 | 가림판 제목을 generic 으로(설정 추가) |

---

## 부록 A. 구현 인터페이스

```python
# lm27/vocab/steps.py   (이 문서 소유 — 시간 코어·보고서·브리지·레지스트리 기본값 공용)
STEP_TYPES: dict[str, StepType]          # code → StepType(name, kind('M'|'A'), cls, tool_default, verify_default, order)
CLASSES: tuple[str, ...] = ("소통", "회의", "문서", "공학", "코드", "조사", "오프라인")
def ext_class(ext: str) -> str: ...      # 'doc'|'ppt'|'xls'|'pdf'|'txt'|'cad'|'code'|''
def obs_of(level: str, cls: str | None, ext_cls: str, anchor_kind: str | None, meeting_role: str | None) -> str: ...
def tool_access(code: str, registry: dict | None) -> int: ...
def verifiable(code: str, registry: dict | None) -> int: ...

# lm27/report/fmt.py
def fmt_h1(minutes: int) -> str: ...
def fmt_ratio(num: int, den: int, digits: int) -> str | None: ...
def fmt_mm(env_min: int, denom_min: int) -> str | None: ...
def fmt_pct(num: int, den: int, digits: int = 0) -> str | None: ...
def fmt_days(biz_min: int, std_day_min: int = 480) -> str: ...
def biz_min(a: int, b: int, cal: "Calendar", window: "Window") -> int: ...     # 로컬 분
def iso_week(d: date) -> str: ...                                                 # 'YYYY-Www'

# lm27/report/inputs.py
@dataclass
class ReportInputs:
    run_id: str; time: "TimeFiles"; labels: dict | None; ai: dict[str, dict | None]; registry: dict | None
    person_dir: dict | None; evidence: "EvidenceIndex | None"; bundle_state: "BundleState"; outbox: list[dict]
    missing: list[str]; warnings: list[dict]
def load_inputs(run_id: str) -> ReportInputs: ...

# lm27/report/analysis/*.py
def build_activity(tasks, attrib, days, cfg) -> dict[str, list["Run | Milestone"]]: ...
def mine_role(units: list[dict], log: dict, cfg) -> "RoleWorkflow": ...
def unit_workflow(unit: dict, log: dict, cal) -> dict: ...
def project_workflow(project_key: str, units_by_role: dict, log: dict, cfg) -> dict: ...
def domain_workflow(code: str, units: list[dict], log: dict, roles: dict) -> dict: ...
def review_periods(units, tables, log, peers, ontology, ai_review, cfg) -> dict: ...        # {"weeks": [...], "months": [...]}
def overrun_causes(unit: dict, baseline: tuple[int, int] | None, cfg) -> dict: ...
def peers_layer(tasks, evidence, person_dir, cfg) -> dict: ...
def relatedness(u: dict, v: dict, cfg) -> tuple[float, float]: ...                          # (rel, seq)
def ontology_layer(units, log, peers, cfg) -> dict: ...
def agentic_layer(roles_wf, catalog: list[dict], ai_out: dict | None, cfg) -> dict: ...
def rule_score(agent: dict, item: dict) -> float: ...
def subagent_step(stat: dict, cfg, registry) -> dict: ...
def subagent_layer(roles_wf, log, ai_out: dict | None, cfg) -> dict: ...
def final_verdict(rule: str, ai: str | None) -> str: ...
def quality_month(month_ctx: dict, cfg) -> dict: ...                                         # {"grade", "reasons", "cov", ...}
def write_ai_items(run_id: str, stage: str | None = None) -> dict[str, int]: ...             # 단계별 항목 수

# lm27/report/model.py · export.py · drill.py · resolve.py
def build_model(inp: ReportInputs, cfg) -> dict: ...
def check_model(model: dict) -> list[str]: ...                 # 등식 위반 목록(빈 목록 = 통과)
def redact_model(full: dict, registry: dict | None) -> dict: ...
def export(run_id: str, formats: list[str], variants: list[str], out_dir: Path | None = None) -> "ExportResult": ...
def island(obj) -> str: ...                                     # §9.4 이스케이프
def day_drill(run_id: str, d: date, variant: str) -> dict: ...
def unit_drill(run_id: str, unit_id: str, variant: str) -> dict: ...
class Resolver:
    def __init__(self, variant: str, person_dir: dict | None, registry: dict | None, evidence: "EvidenceIndex | None"): ...
    def person(self, who_key: str) -> str: ...; def doc(self, fam_key: str) -> str: ...; def msg(self, msg_key: str) -> str | None: ...

# lm27/ui/server.py · jobs.py · nextactions.py
def serve(cfg, port: int | None = None, open_browser: bool = True) -> int: ...     # rc 0/3
class JobManager:
    def start(self, kind: str, argv: list[str], lane: str) -> "Job": ...         # 같은 lane 실행 중이면 BusyError
    def get(self, job_id: str, since: int = 0) -> dict: ...
    def cancel(self, job_id: str) -> None: ...
def next_actions(state: "UiState") -> list["NextAction"]: ...

# lm27/team/report.py   (렌더 부분 — 산식은 TEAM §4)
def interpret(td: dict, cfg) -> list[dict]: ...                 # §7.4.4
def build_details(store, td: dict, max_mb: int) -> dict: ...     # §7.8.2
def render_team_report(td: dict, share: bool = False) -> str: ...
```

```javascript
// web/common/lm27charts.js
function h(tag, attrs, children) {}            // 가상 노드
function toString(vnode) {}                     // 시험용
const CHARTS = {"CH-H01": coverageHeatmap, "CH-P02": monthlyMM, "CH-P03": dailyBars, "CH-P04": domainShare,
                "CH-P06": gantt, "CH-P07": processMap, "CH-P08": unitTimeline, "CH-P09": gantt, "CH-P10": classMix,
                "CH-P11": leadDots, "CH-P12": peerBars, "CH-P13": radial, "CH-P16": dayBand, "CH-P17": gradeBars,
                "CH-T02": teamDomainBars, "CH-T06": leadDots, "CH-T08": gantt};
// 각 함수: (spec, opt{width, mode, variant}) → {svg, table:{cols, rows}, legend, caption:{title, summary}}
// web/common/lm27ui.js
function mount(vnode, parent) {}  function fmtH1(min) {}  function fmtRatio(num, den, digits) {}
function openDrawer(contentVnode, opts) {}  function tooltip(target, lines) {}  function tableView(chartResult) {}
function delegate(root, handlers) {}           // data-act 위임
```

---

## 부록 B. 참조 시제품 결과

| 파일 | 내용 | 실행 |
|---|---|---|
| `scratchpad\lm26_survey\design\reports\proto_report.py` | §3.2 영업 분, §4.2 마이닝, §4.4.3 초과 원인, §4.6.2 연관도, §4.8 서브에이전트, §8.4 간트 줄 배치·밀도 단계, §3.1 표시 함수 | `python\python.exe -B proto_report.py` → `golden_report.json` |
| `…\reports\fmt_check.js` + `fmt_cmp.py` | 표시 함수 파이썬 = JS 교차 검사 | `node fmt_check.js > fmt_js.json` → `python -B fmt_cmp.py` → `cases 11530 mismatch 0` |
| `…\reports\golden_report.json` | 위 결과(RPT-11·14·15·19·20·22·23·25 골든 원본) | — |

실측 메모(2026-10-05, 이 PC — Windows 11 Pro, 동봉 파이썬 3.11.9):
- 동봉 파이썬은 스크립트 폴더를 `sys.path` 에 넣지 않아 같은 폴더 모듈 `import proto_report` 가 `ModuleNotFoundError` 로 실패했다(결정 메모 §0 재확인) → 시험 하네스·진입점은 경로를 스스로 넣는다.
- 이 PC 의 TCP 동적 포트 범위 1024~15000, 예약 범위 11300·29999 — 기본 화면 포트 19280 은 둘 다 밖이고 비어 있었다(§2.3.2).
- 콘솔 코드 페이지(CP949)에서 파이썬 표준 출력의 한글이 깨져 보였다 — 로컬 앱 작업 이벤트는 파일·JSON(UTF-8)으로만 주고받고 콘솔 출력에 의존하지 않는다(§2.3.5).
- 팔레트·대비 수치는 dataviz 팔레트 검사기(OKLab CVD 모의·WCAG 대비)로 흰 바탕 `#ffffff` 기준 계산했다(§8.1.3). LM20 주황 `#e08a00` 대비 2.69:1 → `#c47400` 으로 교체, LM20 흐린 글자 `#8b929b` 3.14:1 → 글자용 `#646b75`(5.38:1), 브랜드 파랑 `#2a78d6` 위 흰 글자 4.42:1 → 버튼 바탕 `#2770c7`(4.97:1).
