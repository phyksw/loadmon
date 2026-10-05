# LM27 팀즈 수집기 명세 (COLLECT_TEAMS.md)

판: v1 · 대상 독자: 팀즈 수집기 구현자 · 상위 규율(순서대로 우선):
`docs/COLLECTION.md`(수집 공통 계약 — 레코드 스키마·경로 ID·사유 코드·커버리지 상태),
`docs/_decisions.md`(오케스트레이터 결정 메모), `docs/PRIVACY.md`(정제 명세 — 모듈 `lm27.privacy`),
`docs/COPILOT_BRIDGE.md`(코파일럿 브리지 5계층).

이 문서는 LM27 **팀즈(kind=`teams`)** 경로만 다룬다. 메일·일정·PC 사용·파일·git·수동 기록은 별도 명세다
(`COLLECT_MAIL.md`·`COLLECT_PC.md`). 구현자는 이 문서만으로 팀즈 수집기·탐침 기여분·스크립트를 코드로
옮길 수 있어야 한다. 공통 계약과 어긋나는 서술이 있으면 `COLLECTION.md` 가 이긴다(§17 미결에 불일치를 모았다).

---

## 0. 명칭·경로 주해 (먼저 읽을 것)

- 결정 메모(2026-10-05, 사용자 지시)에 따라 **이 제품은 LoadMonitor27(LM27)** 이다. 이 문서는 그 지시대로
  **새 명칭만** 쓴다: 파이썬 패키지 `lm27`, 정제 모듈 `lm27.privacy`, 상주 에이전트 `%LOCALAPPDATA%\LoadMonitor27`,
  작업명·뮤텍스 `LM27-<install_id>`, 프로그램 트리 `D:\배포\loadmon27`.
- **주의**: 형제 문서(`COLLECTION.md`·`PRIVACY.md`·`COLLECT_MAIL.md`·`COLLECT_PC.md`)는 이름 변경 지시보다
  먼저 작성되어 아직 `lm27`/`LoadMonitor27`/`LM27-` 로 적혀 있다. 그것은 **트리 일괄 개명 대기 상태**다(결정
  메모: "작업 중에는 임시로 `D:\배포\loadmon27` 에 문서가 쌓이고 있으며 곧 이름을 바꾼다"). 인터페이스는
  **1:1 대응**한다 — `lm27.privacy.*` → `lm27.privacy.*`, `%LOCALAPPDATA%\LoadMonitor27` → `…27`,
  `LM27-<install_id>` → `LM27-<install_id>`. 구현자는 패키지를 `lm27` 로 만든다.
- 이 문서 파일은 개명 전까지 **물리적으로 `D:\배포\loadmon27\docs\COLLECT_TEAMS.md`** 에 둔다(형제 문서와
  같은 폴더). 트리를 `loadmon27` 로 바꿀 때 형제 문서와 함께 옮기고 내부 `lm27→lm27` 치환을 일괄 수행한다(§17.1).
- `D:\배포\LM26`(대문자, 포트 8765~8767)은 **다른 AI 도구가 만든 별개 프로젝트**다. 읽기·수정·실행 금지,
  이름·포트가 겹치지 않게 한다.

---

## 1. 경계·원칙 (어기면 안 됨 — 설계에 명시)

- **문서화·지원되는 사용자 인터페이스만** 쓴다. 팀즈에서 쓰는 것: ① Teams 데스크톱 창의 **UI Automation
  (접근성 API)** 판독(`teams.uia`), ② **사용자 본인 전용 Edge 프로필**의 Teams 웹(teams.microsoft.com/v2)을
  CDP(127.0.0.1)로 판독(`teams.web`, 백필 PC), ③ M365 Copilot Chat 왕복(`teams.copilot`, 클라우드PC, 요약
  증인), ④ 사용자 수동 태깅.
- **설계에 넣지 않는 것(경계 금지, 명시)**: Microsoft Graph(권한 없음), **앱 내부 캐시 직접 판독(Teams
  IndexedDB/LevelDB)**, **Windows 알림 DB(`wpndatabase.db`)**, 숨김 메일함 폴더(비 IPM 루트·`TeamsMessagesData`),
  자격 증명 접근, 관리자 권한 요구, 보안 정책 우회, Edge 기동 인자 `--remote-allow-origins=*`. 막혀서 안 되는
  날은 §12 사유 코드로 커버리지 원장에 남길 뿐, 금지 경로로 우회하지 않는다. (근거: 결정 메모 §2 — 외부 조사
  단계에서 이 영역이 안전 분류기에 걸렸다. 채택하지 않은 이유는 §2 에 짧게 적는다.)
- **원문은 메모리/파이프에서만** 다룬다. 디스크에는 `lm27.privacy.sanitize_record()` 를 통과한 **열 허용
  목록 레코드만** 쓴다(§3·§13). 원문 덤프(`teams_window_raw.txt`·`teams_window_skipped.txt`·Copilot 응답
  `replies\*.txt`)는 **절대 남기지 않는다**(LM24 전부 폐기 — §14).
- 실명·계정·이메일·사내 코드네임을 코드·문서·샘플·프롬프트에 넣지 않는다(예시는 자리표시자 `과제A`·
  `고객사#1a2b`·`사람#3f9a`).
- **사용자를 대신해 로그인하지 않는다**. 웹 로그인은 사람이 1회(전용 Edge 창). 비밀번호·토큰·쿠키를
  다루지 않으며, 세션 자료를 운반 번들에 넣지 않는다(DPAPI 로 어차피 타 PC 무효 — §14).
- '첫 성공에서 멈추는 사슬'을 쓰지 않는다. **역할 분담 + `msg_key` 병합 + 셀 단위 커버리지 원장**(§8·§11).
  앱 창 몇 줄을 읽었다고 웹 백필을 건너뛰지 않는다.
- 이전 판 폴더(`D:\배포\loadmon24_v4`)는 **읽기 전용**. 코드는 '복사해 새 트리로 옮겨 다시 설계'만.

### 1.1 경로 ID·스크립트·역할

| 경로 ID | 수집기 스크립트 | 언어 | PC 역할 | 메커니즘(문서화된 UI만) |
|---|---|---|---|---|
| `teams.uia` | `Get-TeamsWindow.ps1` | PS 5.1 | 모든 PC(상주 샘플러) | Teams 데스크톱 **모든 최상위·팝아웃 창**의 UIA ContentView 판독, 가시일 때만, 2~5분 주기 |
| `teams.web` | `Get-TeamsWeb.py` | PY 3.11 | 백필 PC(기본 클라우드PC)만 | 본인 전용 Edge 프로필 CDP 로 teams.microsoft.com/v2 DOM 판독, **기간 전체 백필**, 채팅·채널·활동 피드 |
| `teams.copilot` | `Get-TeamsViaCopilot.py` | PY 3.11 | 클라우드PC만 | 커넥터 탐침 통과 시만, 요약 **증인**(시간 근거 아님) |
| (상주) | `Start-TeamsSampler.ps1` | PS 5.1 | 모든 PC | `teams.uia` 를 주기 실행하는 상주 루프(작업 스케줄러 등록) |
| (수동) | 보고서 UI 태깅 → `lm27.tagfeed` | — | 로컬 | 사람이 '이 메시지=지시/보고' 태그를 다는 분류기 보정 피드백 |

- 팀즈 '내용'은 **계정 단위** 자료다. **기간 전체 백필은 백필 PC(기본 클라우드PC)에서 한 번**만(`teams.web`).
  PC1·PC2 는 그 PC에서 실시간으로 되는 경로(`teams.uia`)와 '이 PC Teams 사용 시간'만 담당한다. 중복은
  `msg_key` 로 병합(§5·§8).
- 백필 담당 PC 는 공통 설정 `collect.backfillPc`(기본 `"cloud"`). 클라우드PC 가 없으면 사용자가 1대를 지정.

---

## 2. 채택하지 않은 경로와 이유 (설계 경계의 근거)

결정 메모 §2 와 공통 계약에 따라 **설계에서 영구 제외**한다. 조사 단계에서 후보로 거론됐더라도(LM24 조사의
P3·P4) 다음 이유로 넣지 않는다. 구현자는 이 경로들을 **탐침·수집 어디에서도 시도하지 않는다**.

| 제외 경로 | 왜 제외하는가 |
|---|---|
| Teams IndexedDB/LevelDB 직접 판독(새 Teams `EBWebView\WV2Profile_tfw\IndexedDB`, 클래식 `Teams\IndexedDB`) | **앱 내부 캐시 직접 판독**이라 데이터 접근 원칙 위반. 스키마가 비공개·버전마다 변동, 캐시가 부분적/빈 경우가 많음(조사 PC 는 약 11KB·`.ldb` 없음), EDR·보안정책 위반 소지, 비표준 파서 의존. 안전 경계를 넘는다. |
| Windows 알림 DB `wpndatabase.db` 토스트 회수 | **앱/OS 내부 저장소 직접 판독**. 보존 기간 짧음·미리보기 잘림·알림 꺼짐/방해금지 시 공백·형식 변경 위험. 데이터 접근 원칙상 금지. |
| Microsoft Graph(`/me/chats`·device-code) | 권한 없음(사용자 전제). 기본 사슬에서 제외. 권한이 생기면 꽂을 **어댑터 인터페이스 자리만** 남기되(§9.1), 기본 수집·탐침에서는 쓰지 않는다. |
| 숨김 폴더(`TeamsMessagesData`·비 IPM 루트), OST/PST 직접 파싱 | 숨김 저장소 탐색·바이너리 직접 파싱 금지. |
| Edge 기동 인자 `--remote-allow-origins=*` | 로컬 웹 페이지가 로그인된 디버그 세션을 조종할 수 있는 보안 위험. CDP 는 **자기 포트로만** origin 제한(§9.2). |
| 마스킹 없는 원문 덤프 저장(`teams_window_raw.txt`·Copilot `replies\*.txt`) | 이동 폴더에 원문이 실려 나감. 정제 전 원문은 디스크에 쓰지 않는다(§1·§13). |

---

## 3. 정규 메시지 레코드

팀즈는 두 겹으로 다룬다: 수집기가 **메모리에서** 만드는 **원시 입력 레코드**(§3.1)와, `lm27.privacy.sanitize_record`
가 통과시켜 세그먼트에 쓰는 **저장 열 허용 목록 레코드**(§3.2). 수집기는 **구조에서 읽히는 것만** 원시 레코드에
담고, 의미 판정(화행 `act`·공사 구분 `priv_class`)과 키 HMAC·마스킹은 정제 계층이 한다(§6·§13).

### 3.1 원시 입력 레코드 (메모리 전용, 수집기 → 정제기)

`schema_in = "teams.raw/1"`. 한 줄 = 한 메시지. NDJSON 으로 stdout(PS) 또는 in-process dict(PY).

| 필드 | 형 | 설명·예시 |
|---|---|---|
| `source` | str | `teams.uia` / `teams.web` / `teams.copilot` |
| `message_id` | str\|null | DOM `data-mid` 또는 `id='content-<epoch_ms>'`(웹). UIA·없으면 `null` |
| `chat_raw_id` | str\|null | 대화방 원 ID(웹 `data-tid`/대화 ID). UIA 는 창 제목·룸 머리에서 **합성 ID**(예 `uia:<win_class>:<제목정규화>`) |
| `thread_raw_id` | str\|null | reply-to/스레드 원 ID(채널 글타래). 없으면 `null` |
| `chat_type` | str | `1:1`/`group`/`channel`/`meeting`/`self`/`unknown` — **구조로 판정**(§4.2) |
| `n_participants` | int\|null | 참여 인원(로스터·머리에서 구조로). 미상 `null` |
| `author_name` | str\|null | 작성자 표시명(원문, 메모리) |
| `author_smtp` | str\|null | 있으면 소문자 주소(웹 프로필 카드 등) |
| `author_id` | str\|null | 안정 작성자 ID(있으면 — 방향·person_key 1순위) |
| `direction_cue` | str | 구조 단서 결과 `self`/`other`/`unknown`(§4.1). 표시명 집합 적용은 정제기가 최종 수행 |
| `mentions_me` | bool | 나 @멘션 여부(DOM 멘션 요소/UIA aria) |
| `file_names` | list[str] | 첨부·공유 파일명(원문, 메모리). 없으면 `[]` |
| `body_text` | str | 원문 본문(메모리, 자르기 전). 정제기가 `body_masked`(≤300) 로 축약 |
| `ts_utc` | str\|null | `<time datetime>` 의 UTC ISO(웹에서 노출 시). 예 `2026-09-01T04:05:00Z` |
| `ts_wall` | str\|null | 화면 표기 벽시계 `YYYY-MM-DD HH:MM`(UIA 지역 파서 결과, §7.3) |
| `ts_precision` | str | `exact`(ISO) / `minute`(벽시계 분) / `date`(날짜만) / `unknown`(날짜 미상 — §7.4) |
| `offhours_hint` | bool | 수집기가 로컬 표준창 밖으로 본 1차 힌트(최종 판정은 시간 명세) |
| `participants` | list[obj] | `[{"name","smtp?"}]` — person_dir 적재용(메모리, 행에는 키만 저장) |

- 수집기는 `ts_utc`·`ts_wall` 중 **가진 것만** 채운다. 둘 다 없고 날짜도 못 짚으면 `ts_precision="unknown"`
  로 격리하되 **버리지 않고** 넘긴다(정제기·시간 명세가 격리 버킷으로 처리, §7.4).
- 작성자 없는 **연속 메시지**는 수집기가 직전 작성자를 상속해 `author_name`/`author_id` 를 채운다. 끝내
  불명이면 `author_name=null`·`direction_cue="unknown"`(수신 단정 금지, §4.1).

### 3.2 저장 열 허용 목록 레코드 (PRIVACY §10.2 teams 와 동일)

`schema = "teams/1"`. 공통 열(`rules_ver`·`kid`·`pc_id`·`source`·`ts_utc`·`ts_local`·`ts_precision`·`priv_class`·`san`)
은 PRIVACY §10.1 과 같다. 팀즈 추가 열:

| 열 | 형 | 설명 |
|---|---|---|
| `msg_key` | `m`+24hex | 병합 키. `tid:<message_id>` 우선, 없으면 `teams:<날짜>|<chat_raw_id>|<작성자정규화>|<HH:MM>|<sha256(본문정규화)[:16]>` 를 HMAC(§5) |
| `chat_key` | `t`+16hex | 대화방 키(`chat_raw_id` HMAC). **끝까지 보존**(페어링 1차 근거) |
| `thread_key` | `t`+16hex\|null | 스레드/글타래 키(`thread_raw_id` HMAC) |
| `chat_type` | str | `1:1`/`group`/`channel`/`meeting`/`self` |
| `n_participants` | int | 참여 인원(미상이면 2 로 보수 추정하고 `abs_hint` 표기) |
| `author_key` | str | `self` 또는 `person_key`(`p`+16hex) |
| `direction` | str | `sent`/`received`/`unknown` |
| `mentions_me` | bool | |
| `has_file` | bool | `len(file_names)>0` |
| `file_names_masked` | list[str] | 정제된 첨부 파일명(≤5개 × ≤80자). 사적/social 이면 `[]` |
| `file_keys` | list[str] | 첨부 파일명 **줄기+확장자 HMAC**(≤5, `a`+16hex) — 보고서에서 '문서작성완료→팀즈보고' 를 PC 파일 이력(`pc_file.attach`/`doc_key`)과 잇는 교차검증 키(종료②). COLLECTION §3.2 의 `attach_keys` 와 같은 값 |
| `body_masked` | str | 정제 본문 ≤300자. 사적/social 이면 `""` |
| `chat_title_masked` | str\|null | `group`·`channel`·`meeting` 만 ≤60자. **`1:1` 은 저장 안 함**(1:1 방 이름 = 상대 이름) |
| `act` | str | `request`/`ack`/`question`/`report`/`info`/`social`/`notice`/`""` — **정제 계층 분류기**가 채움(§6). 수집기는 `""` |
| `act_score` | float | 0.0~1.0 |
| `abs_hint` | obj | 부재/구조 힌트(`{n_part_est:bool, cont_inherited:bool, date_unknown:bool}`) |
| `priv_score_base` | int | 방 성향 제외 사적 점수(방 성향 재계산용, PRIVACY §12.4) |
| `priv_score` | int | 최종 사적 점수 |
| `priv_class` | str | `work`/`private`/`social` |

- `confidence`(COLLECTION §3.4): `exact`/`minute`+구조 작성자 확정 = 0.8, 작성자 상속 추정 = 0.3,
  `teams.copilot` 요약 = 0.3, `date`·`unknown` = 시간 근거 아님.
- **레코드 예시**(저장 1줄):
```json
{"schema":"teams/1","rules_ver":"2026.10.0","kid":"k1a2b3c4","pc_id":"PCH#3f9a","source":"teams.web",
 "ts_utc":"2026-09-01T04:05:00Z","ts_local":"2026-09-01T13:05:00+09:00","ts_precision":"minute",
 "msg_key":"m8f0a…(24hex)","chat_key":"t9d2f…(16hex)","thread_key":null,"chat_type":"group","n_participants":5,
 "author_key":"self","direction":"sent","mentions_me":false,"has_file":true,"file_names_masked":["보고_초안.pptx"],
 "file_keys":["af10c…"],"body_masked":"[과제:P0001] 검토본 공유드립니다 …","chat_title_masked":"과제A 설계",
 "act":"report","act_score":0.82,"abs_hint":{"n_part_est":false,"cont_inherited":false,"date_unknown":false},
 "priv_score_base":-4,"priv_score":-4,"priv_class":"work","san":{}}
```

---

## 4. 판정 규칙 (구조는 수집기, 의미는 공통 모듈)

### 4.1 방향(direction) — 구조 단서 > 표시명 집합, 불명은 unknown

우선순위(위에서 먼저 맞는 것):
1. **ID 일치**: `author_id`(또는 `message_id` 소유)가 내 계정 ID 와 같으면 `sent`.
2. **구조 단서**(`direction_cue`): 웹 — 말풍선이 내 쪽(오른쪽) 정렬·`aria`='You'/'보낸 사람'·내 메시지 그룹
   컨테이너 클래스. UIA — 작성자 생략 + 오른쪽 정렬/내 쪽 그룹. → `self`/`other`.
3. **표시명 집합**: 작성자 표시명이 본인 이름 집합(§4.4)에 들어가면 `sent`, 아니면 `received`.
4. 어느 것도 아니면 **`unknown`**. **수신으로 단정하지 않는다**(LM24 결함: 짧은 연속 메시지를 작성자로
   오인·수신 단정 → §14).

정제기가 2→3 순서로 `direction_cue` 와 표시명 집합을 적용해 최종 `direction` 을 확정한다. `R-NOADDR`(내
주소/표시명 미확정)이면 표시명 단계를 건너뛰어 `unknown` 비중이 커질 수 있음을 커버리지에 표기.

### 4.2 대화 유형(chat_type)·단체 판정 — **구조로만**

- 쉼표 수(LM24 결함)·대화방 이름 문자열로 판정 **금지**.
- 웹: 라우트/패널 유형(`/conversations/` 채팅 vs `/channel/` vs 회의 채팅)·`data-tid` 종류·로스터 인원으로
  `1:1`/`group`/`channel`/`meeting` 판정. `n_participants` 는 로스터·머리에서.
- UIA: 창/패널 클래스·팝아웃 유형·머리의 참여자 수로 판정. 미상이면 `chat_type="group"`·`n_participants=2`
  보수 추정 + `abs_hint.n_part_est=true`(단정 금지).
- `self`(내 메모/내게 보낸 채팅)는 전용 유형으로 둔다.

### 4.3 멘션·첨부

- `mentions_me`: DOM 멘션 요소(내 표시명 대상)·UIA aria 멘션 문구로 **구조에서** 판정.
- `has_file`/`file_names`: 첨부·공유 파일 카드에서 파일명 수집. 정제기가 `file_names_masked` + `file_keys`
  (HMAC)로 저장. `file_keys` 는 PC 파일 이력과의 교차검증(종료②)에 쓴다(§3.2).

### 4.4 본인 이름 집합 (LM24 `Get-SelfNames` 계승·일원화)

소스: 설정 `teams.selfNames`(§16) + `owner` + Windows 계정(`%USERNAME%`) + LogonUI 표시명(레지스트리,
오프라인 즉시) + AD `UserPrincipal.DisplayName`(설정·레지스트리 모두 없을 때만, 마지막 수단) + 고정값
`나`·`본인`·`you`·`me`. 소문자·공백 제거·`님`/`씨` 접미 제거 변형을 모두 집합에 넣는다. **경로마다 따로
구현하지 않고**(LM24 3~4벌 결함) 공통 모듈 1벌로 한다. 재생 모드(원문이 타 PC)는 설정값만 쓴다.

---

## 5. 키·중복 제거 (날짜 포함)

- `msg_key`(PRIVACY §9.3): `tid:<message_id>` **우선**, 없으면
  `teams:<YYYY-MM-DD>|<chat_raw_id>|<norm(author)>|<HH:MM>|<sha256(norm(body))[:16]>` → HMAC `m`+24hex.
  **키에 날짜를 반드시 포함**(LM24 웹 결함: HH:MM 만이라 매일 같은 시각 정형 메시지가 하루치로 뭉개짐 — §14).
- `chat_key`/`thread_key` = 원 ID 의 HMAC `t`+16hex. 원 ID 가 없는 UIA 는 합성 ID(§3.1)를 HMAC — 같은 PC
  안에서는 안정, PC 간에는 다를 수 있으므로 웹 경로가 백필한 `chat_key` 를 우선 병합 기준으로 삼는다(§8).
- **정제 전 원문으로** HMAC 계산(PC·규칙 버전이 달라도 같은 메시지 1회 계상). 중복 제거는 읽기 시 파생
  (불변 세그먼트 덮어쓰기 금지, COLLECTION §7).
- 키 충돌(PC별 키 생성 후 합쳐짐)은 PRIVACY §9.6 보조 키로 흡수.

---

## 6. 화행(act)·공사(公私) 구분 — 공통 모듈 (`lm27.privacy.classify`)

- **수집기는 `act` 를 판정하지 않는다**(COLLECTION §3.1). 본문은 저장되지 않으므로, 본문이 메모리에 있는
  **정제 경계(`sanitize_record`의 `derive_features`)** 에서 공통 분류기 `lm27.privacy.classify.act_of()` 가
  `act`/`act_score`/`abs_hint` 를 계산해 저장 행에 남긴다. 경로(uia/web/copilot)에 **같은 규칙**을 적용한다
  (LM24 결함: order 판정이 Graph·Copilot 에만 있어 실동작 경로는 지시 신호 0건 — §14).
- `act ∈ {request, ack, question, report, info, social, notice}`. 가중: 문말 어미(`~해 주세요`·`부탁드립니다`·
  `요청드립니다`·`바랍니다`·`회신 바랍니다`), 기한(`~까지`·`언제까지`), @멘션, 1:1 질문형 → `request`(수신일 때
  시작 신호). `넵`·`알겠습니다`·`확인했습니다` → `ack`(단정 어미이면 `request` 아님). 발신 + 완료·송부·
  `공유드립니다`·`보고드립니다`·반영·업로드·결과·첨부 → `report`(종료①). 단어 부분일치(LM24 `ORDER_HINTS`
  `확인`·`공유`·`일정`·`가능`·`필요`)로 판정 **금지**. 상급자/PM 가중 목록은 설정(해시, §16·§17).
- 공사 구분: `lm27.privacy.classify.private_score(body_masked, chat_type=…, offhours=…, room_prior=…,
  user_private_chat=…)`(PRIVACY §12.3). `priv_class ∈ {work, private, social}`. `private`/`social` 이면
  `body_masked`·`file_names_masked` 를 비우고(메타만 남김) **시간 근거에서 제외**. 방 성향(`room_prior`,
  PRIVACY §12.4)과 사용자 지정 사적방(`private_chats.json`)으로 방 전체 소급 가림(읽기 오버레이 + 자기 PC
  세그먼트 재작성, PRIVACY §12.5). `priv_score_base`(방 성향 제외)를 저장해 적재 시 방 성향 재계산.

---

## 7. `teams.uia` — UIA 샘플러 v2 (`Get-TeamsWindow.ps1`)

### 7.1 스크립트 계약

```
powershell -NoProfile -ExecutionPolicy Bypass -File collect\Get-TeamsWindow.ps1 `
    -PcId <pc_id> -Root <루트> [-MaxElements 4000] [-KeepChatList] [-RawFile <원문.txt>]
```
- 출력: **파일에 직접 쓰지 않는다**. 원시 teams.raw 레코드를 **NDJSON 으로 stdout** 한 줄씩. 오케스트레이터가
  `python -m lm27.privacy.sanitize_stream --kind teams --src teams.uia --pc <pc_id> --out <seg.jsonl.gz>` 파이프로 받는다(§13).
- 진단·안내는 **stderr**(또는 `Write-Host`)로. 숫자·사유만, 원문 금지.
- `-RawFile`: 시험/재생 — 원문 텍스트 파일을 창 대신 입력(실데이터 세그먼트를 건드리지 않음, 설정값만으로 본인 판정).
- 종료 코드(COLLECTION §8.4): `0` 신규 레코드 방출 · `1` Teams 창 없음(미실행/트레이) · `3` UIA/드라이버 불가
  · `4` 읽었지만 신규 0(모든 가시 창이 렌더 0줄). **`exit 0` 고정 금지**(LM24 결함: 항상 0 이라 실패가 안 보임 — §14).

### 7.2 창 열거 — 모든 최상위·팝아웃, 가시일 때만

- `ms-teams`(새)·`Teams`(클래식) 프로세스의 **모든 최상위 창**을 열거한다(`EnumWindows` + 프로세스 매칭).
  `MainWindowHandle` 하나만 읽지 않는다(LM24 결함: 팝아웃 채팅 창 누락 — §14).
- **가시 판정**: `IsWindowVisible` + 비최소화(`IsIconic=false`) + 화면 교집합 면적>0. 트레이·최소화·숨김은
  읽지 않고 `R-UIAEMPTY` 로 그 주기 커버리지에 표기(0건을 '성공'으로 숨기지 않는다).
- 관리자 권한 창(UIA 트리 접근 불가)은 `R-UIAELEV`.
- 창마다 UIA `ContentView` 요소를 `CacheRequest` 로 최대 `teams.uia.maxElements`(기본 4000) 읽는다.
  **창당 15초 워치독**(초과면 그 창 skip + `R-CAP`). 전체 주기 예산 `probe.budgetSec` 와 별도 `teams.uia` 예산.

### 7.3 채팅 목록 열 제외 + 헤더/본문 분리 + 지역 파서 (LM24 계승)

- **채팅 목록 열 제외**(LM24 `Get-ListColumn` 계승, LM22 회귀 교훈 포함): 목록 열은 '창 왼쪽 25% 안에서
  시작하고 왼쪽 45% 안에서 끝남', 항목 3개 이상, 넓은 메시지 항목이 하나라도 보일 때만, 후보가 여럿이면
  **가장 왼쪽**(가장 많은 것 아님). `-KeepChatList` 로 해제.
- **안전 밸브**: 목록으로 보고 뺐는데 남은 줄에 시각이 0줄이면 그 판정이 틀린 것 → 뺀 줄을 되돌려 다시 읽는다.
- **헤더/본문 분리**(LM24 계승): 날짜·발신자는 **시각 앞(헤더)** 에서만 찾는다. 본문의 `8/15 까지` 는 날짜로
  보지 않는다. 날짜·발신자는 화면이 '이 메시지의 시각'이라 말하는 조각에서만.
- **지역 설정 시각 파서**(LM24 계승): Windows 지역 설정(AM/PM 지정자·구분자·월 이름·요일)에서 정규식을
  자동 구성 → 0줄이면 일반 형식(`숫자:숫자`/`숫자.숫자`) 재시도 → `teams.timeRegex` 설정이 있으면 최우선.
  원문을 PC 밖으로 보내지 않고 그 PC 안에서 형식을 알아낸다.

### 7.4 날짜 미상 격리 (LM24 '수집일 추정' 폐기)

- 날짜 표기를 끝내 못 짚은 줄은 **수집일로 추정하지 않는다**(LM24 결함: 며칠 전 대화가 엉뚱한 날 근무 신호로
  — §14). `ts_precision="unknown"` 으로 **격리**해 넘긴다(버리지 않음). 시간 명세가 '미상 버킷'으로 받아
  시간 계산에서 제외하거나 같은 방 날짜 구분선으로 보정한다. 커버리지에는 `n_unknown` 으로 센다.

### 7.5 이 PC 의 Teams 사용 시간 (같은 주기, 별도 신호)

- 같은 샘플링 주기에 **'이 PC 의 Teams 사용 시간'** 신호를 **별도로** 방출한다: `kind=pc_session`·
  `source=teams.uia`·`app_id="teams"`·`layer="L3"`·`flags.teams_visible=true`, `ts_utc`/`ts_end`=이 주기 중
  Teams 창이 전경/가시였던 구간. 보고서 KPI '이 PC Teams 사용 시간'과 세션 가중에 쓴다.
- **중복 계상 방지**: 근무 봉투(COLLECTION/COLLECT_PC 의 PC 샘플러)가 전경 시간의 **1차 소유자**다. 이
  신호는 '팀즈 가시 시간 중 메시지 활동 비율' 교차검증용 2차 신호다. 봉투에 다시 더하지 않는다(§17 조정 항목).

---

## 8. `teams.web` — 웹 DOM 리더 v2 (`Get-TeamsWeb.py`)

### 8.1 스크립트 계약

```
python\python.exe collect\Get-TeamsWeb.py --from 2026-06-01 --to 2026-06-30 `
    --pc-id <pc_id> --root <루트> [--max-chats 0] [--budget-sec 900] [--include-channels] [--include-activity] [--force]
```
- 본인 전용 Edge 프로필(`teams.web.profileDir`, **PC 고정·이동 금지**)을 `--remote-debugging-port`(`teams.web.port`,
  127.0.0.1 바인딩)로 띄워 CDP 로 붙는다. **탭을 스스로 열고 작업이 끝나면 그 탭과 디버그 Edge 를 닫는다**
  (탭 소유·종료). `--remote-allow-origins` 는 **자기 포트로만** 제한(§2).
- 저장: in-process `lm27.privacy.sanitize_record("teams", raw, rc)` → `SegmentWriter.append(SanitizedRow)`
  (PY 수집기는 파이프 없이 직접, PRIVACY §3.5). 원문 CSV 저장 금지(LM24 `teams_web.csv` 폐기 — §14).
- 종료 코드: `0` 저장(신규 있음) · `1` 아무것도 못 읽음/신규 0 · `2` 로그인 필요(전용 Edge 창 1회) ·
  `3` 드라이버/CDP 불가. `2` 는 오케스트레이터가 `R-LOGIN` 안내 후 `teams.web.loginWaitSec`(기본 600초) 폴링.

### 8.2 목록 가상 스크롤 순회 + 채널 + 활동(멘션) 피드

- 채팅 목록을 **가상 스크롤로 끝까지 순회**한다(LM24 결함: 렌더된 항목만, 상한 40 → 목록 아래 방 누락 — §14).
  `--max-chats 0` = 예산 안에서 무제한.
- `--include-channels`(기본 켬): 채널 글타래 순회(채널 지시 누락 방지). `--include-activity`(기본 켬): 활동(멘션)
  피드 순회. 선택자는 **여러 벌**을 두고 '무엇으로 몇 개를 잡았는지' 숫자만 로그(원문 반출 없이 원격 진단).
- 선택자 전부 실패(화면 구조 변경) → `R-WEBSEL`(§12). 목록을 끝까지 못 내림 → `R-LISTVIRT`(partial).

### 8.3 메시지 ID·`<time datetime>` 우선, 대화방별 체크포인트 증분

- 각 메시지의 `message_id`(DOM `data-mid` 또는 `id='content-<epoch_ms>'`)와 `<time datetime>`(UTC)을
  **1순위**로 잡는다. 있으면 `ts_precision="exact"`, `msg_key=tid:<id>`. 없으면 날짜 구분선·`title`·`aria-label`
  '머리'에서 날짜(본문 날짜 금지), `ts_precision="minute"`/`date`.
- **대화방별 체크포인트**: `teams.web.checkpoint.json` = `{"<chat_raw_id>": {"last_msg_id": "...", "oldest_done":
  "YYYY-MM-DD", "newest_done": "YYYY-MM-DD"}}`. 다음 실행은 방마다 체크포인트 **이후/바깥만** 읽는다(증분).
  요소 핸들 대신 **대화 ID 로 재탐색**(재렌더 'gone' 대응). 재탐색 실패 방은 `R-ROOMGONE`(그 방만 skip, 경로
  전체 실패 아님).
- 되감기 상한 `teams.web.maxScroll`(기본 12). 기간보다 오래된 날짜에 닿거나 2회 되감아 신규 0 이면 그 방 종료.

### 8.4 시간 예산·증분 저장

- 전체 예산 `--budget-sec`(기본 900) 안에 **반드시 저장까지 끝낸다**(LM24 교훈: 상한 초과 강제 종료 시 회수분
  전부 소실). `deadline = monotonic()+budget`. 예산 소진 시 남은 방을 포기하고 지금까지 읽은 것을 세그먼트에
  저장(`partial`·`R-BUDGET`), 체크포인트를 남겨 다음 실행이 이어 읽는다.
- 대화 열기·pane 교체는 **고정 sleep 금지** — pane 변경 감지(`wait_pane`)로만 대기(LM24 계승).

---

## 9. `teams.copilot` — 요약 증거 계층 (`Get-TeamsViaCopilot.py`)

- **클라우드PC만**. `COPILOT_BRIDGE.md` 의 커넥터 탐침(P-CP)이 Teams 조회 커넥터를 **통과할 때만** 돈다.
  불가면 `R-NOCONN`/`R-NOLIC`, 능력 기억 플래그로 다음부터 왕복 생략(성공 시 해제, LM24 계승).
- 7일 이하 조각, 행 상한 50, JSON 스키마 + 종료 표식. 기간 밖 행은 환각으로 폐기. 입력 8,000자 조각 규칙 계승.
- 결과는 `kind=copilot_ev`(PRIVACY §10.2)로 **따로** 저장(`ts_precision="summary"` 고정, `src_kind="teams"`,
  `text_masked≤200`). **메시지(`teams/1`)와 병합하지 않는다**(LM24 결함: LLM 재서술 행 해시 불일치 → 이중
  계상 — §14). 다른 경로가 비운 (일자×대화방) 셀의 **존재 증인**으로만, 시간 근거 아님.

---

## 10. 수동 태깅

- 보고서 UI 에서 사람이 '이 메시지 = 지시/보고' 를 태그한다(분류기 보정). 피드백은 로컬 전용 파일
  `data\local_only\tag_feedback.json` = `{"<msg_key>": {"act": "request", "by": "user", "at": "<UTC>"}}`
  (키·열거만, 원문 없음). 정규화가 `act` 자동판정을 이 태그로 덮어쓴다(`act_source="manual"`).
- 오프라인 지시/보고로 페어가 비는 경우, 수동 업무 기록(`kind=manual`, COLLECT_PC §)이 유일한 신뢰 근거다.
  다른 사용자에게 수동 조작을 요구하지 않는다 — 태깅은 본인 선택 보강일 뿐 기본 동작으로 완결된다.

---

## 11. 커버리지 셀 (일자×대화방) + 빈칸 계획기

- 팀즈 전용 하위 원장 `teams_coverage.jsonl`: 셀 = `(account, date, chat_key, src)`. 상태는 COLLECTION §5.1
  열거(`ok`/`zero_ok`/`partial`/`out_of_horizon`/`blocked`/`transport_fail`/`not_attempted`). 필드: `n`,
  `n_unknown`(날짜 미상), `reason[]`(R-*), `checkpoint`(web), `probe_sig`, `run_id`, `observed_at`.
- 이 하위 원장은 COLLECTION §5 공통 원장의 `kind_axis="teams"` 셀로 **롤업**된다(그 (account,date)의 모든
  chat_key·src 중 최선 상태). 즉 팀즈는 공통 원장보다 **방 단위로 더 잘게** 추적하고, 공통 원장은 날짜 단위로 집계.
- **빈칸 계획기**(COLLECTION §6): 어떤 (일자×대화방)이 아직 안 덮였는지로 `teams.web` 백필 작업을 배정한다.
  `teams.uia` 로 그날 그 방 몇 줄을 읽었어도, 그 방의 과거 구간이 비었으면 `teams.web` 백필 todo 를 연다
  ('첫 성공에서 멈춤' 금지). 불가 확정은 서로 다른 날 2회 + `R-TRANSPORT` 아님(COLLECTION §6.2).

---

## 12. 능력 탐침 기여분 (COLLECTION §4 에 추가)

수집 앞에 매번. 내용 미열람, 숫자·열거·사유만. `pc.json` capability 에 기록.

| 묶음 | 재는 값 | 비고 |
|---|---|---|
| P-TEAMS | 새/클래식 Teams 설치·버전, **모든 최상위·팝아웃 창 수**·핸들, 가시 창 수, UIA 텍스트 줄 수, 시각 패턴 일치 수 | `Invoke-CapabilityProbe.ps1` |
| P-EDGE | Edge 설치, `RemoteDebuggingAllowed`·`DeveloperToolsAvailability` 정책, 본인 전용 프로필 존재 | teams.web 가능 여부 |
| P-WEB(백필 PC) | teams.microsoft.com 로그인 상태(`R-LOGIN`/`R-CA`), 최근 표본의 `message_id`·`<time datetime>` 노출 비율, 목록 가상화 여부 | `probe_teamsweb.py` |
| P-CP(클라우드PC) | Teams 커넥터 가능 여부(무해한 1행, 2-strike), 모델·Work 모드, 입출력 실측 한도 | `COPILOT_BRIDGE` |

### 12.1 사유 코드 (COLLECTION §4.2 재사용 + 팀즈 추가)

재사용: `R-UIAEMPTY`(창 숨김/최소화), `R-UIAELEV`(관리자 창), `R-EDGEPOL`(원격 디버깅 차단),
`R-LOGIN`(로그인 필요), `R-CA`(조건부 액세스), `R-NOCONN`/`R-NOLIC`(코파일럿), `R-NOADDR`(내 표시명 미확정
→ direction unknown), `R-CAP`(상한 절단), `R-BUDGET`(예산 소진), `R-TRANSPORT`(수송 실패 — '불가' 아님).

팀즈 추가(§17 에 COLLECTION §4.2 등재 요청):
- `R-WEBSEL`: 웹 선택자 전부 실패(화면 구조 변경) — blocked.
- `R-LISTVIRT`: 채팅 목록을 끝까지 스크롤하지 못함 — partial.
- `R-ROOMGONE`: 대화 요소 재탐색 실패(그 방만) — 방 단위 partial.

---

## 13. 정제 연동 (파이프/인프로세스)

- **PS 수집기(`teams.uia`)**: 원시 teams.raw 레코드를 **stdout NDJSON** 으로만. 디스크·임시파일 금지(PRIVACY
  §3.4 lint: `collect\*.ps1` 의 `Out-File`/`Add-Content`/`>>`→`data\` 금지). 오케스트레이터가
  `python\python.exe -X utf8 -I lm27_pipe.py --kind teams --source teams.uia --pc-id <pc_id> --root <루트>`
  파이프로 받아 `lm27.privacy.pipe.main()` → 줄마다 `sanitize_record` → 통과분만 gzip 세그먼트에 원자 기록.
- **PY 수집기(`teams.web`·`teams.copilot`)**: `from lm27.privacy import sanitize_record, SegmentWriter` 로
  in-process 호출. `SegmentWriter.append` 는 `SanitizedRow`(봉인 토큰) 만 받는다.
- 로컬 1차 적재: `%LOCALAPPDATA%\LoadMonitor27\agent\<install_id>\store\<pc_id>\evidence\teams\<src>\*.jsonl.gz`.
  운반 세그먼트: 프로그램 폴더 `data\pcs\<pc_id>\seg\*.jsonl.gz`(불변, pc_id 별).
- 정제가 사적/social 판정하면 본문·파일명 제거(§6). 클라우드PC 는 Copilot 전송 직전 같은 정제기로 재검사
  (게이트, PRIVACY §13). **PII 카나리아 0건**(세그먼트·프롬프트·팀 페이로드).

---

## 14. 이식할 LM24 코드와 고칠 점

읽기 전용 `D:\배포\loadmon24_v4\collect\` 에서 **복사해 새 트리로 옮겨 다시 설계**한다.

### 14.1 `Get-TeamsWindow.ps1` → `teams.uia`

| 계승(keep) | 고칠 점(fix) |
|---|---|
| `Get-SelfNames`/`Is-Self` 본인 이름 집합(L29–76) | **공통 모듈 1벌로** 일원화(경로별 중복 제거) |
| `Get-ListColumn` 채팅 목록 열 제외 + LM22 회귀 가드(L78–115) | 유지(가시 창마다 적용) |
| 지역 설정 시각 파서·요일·월 이름(L245–300) | 유지. `ts_wall`/`ts_precision` 로 방출(전역 offset 금지) |
| 헤더/본문 분리(L401–418), 안전 밸브(L431–448) | 유지 |
| 종료코드 0/4/1(L553–556) | **0/1/3/4** 로 확장(COLLECTION §8.4) |
| | `MainWindowHandle` 하나 → **모든 최상위·팝아웃 창 열거**(L185–203 결함) |
| | 날짜 미상 줄 '수집일 추정'(L309–312,404–405,513–526) → **`precision=unknown` 격리** |
| | `teams_window.csv`·`teams_window_raw.txt` 직접 저장(L226–233,449–534) → **NDJSON stdout → 파이프**(원문 비저장) |
| | `kind=sent/msg` 6열 CSV·`replied_time` 측정불가 열(L422,532) → **teams.raw 스키마**(`act` 는 정제기) |

### 14.2 `Start-TeamsSampler.ps1` → 상주 샘플러

| 계승 | 고칠 점 |
|---|---|
| 300초 주기 자식 PS 실행·누적(L1–33) | 주기 설정화(`teams.samplerIntervalSec` 120~300) |
| 창 없으면 조용히 다음 주기 | **기본 등록**(LM24 결함: `-Teams` 없으면 미등록인데 안내는 '5분 주기'라 거짓). 작업명 `LM27-<install_id>`, 등록 결과를 탐침으로 검증해 **결과에서 안내문 생성**(단일 진실원) |
| | 자식 실행 결과를 파이프로 적재(CSV 아님). 가시일 때만 읽어 부하 감소 |

### 14.3 `Get-TeamsWeb.py` → `teams.web`

| 계승 | 고칠 점 |
|---|---|
| 전용 Edge + CDP, 선택자 다벌·숫자 로그(L21–22,223–263) | 유지. `--remote-allow-origins`=**자기 포트만**(LM24 `*` 위험 폐기, tools/copilot_auto.py:395) |
| 날짜 구분선·`<time datetime>`·title·aria '머리'(L483–487), 본문 날짜 금지 | 유지 |
| 날짜 못 짚으면 버림(L488–491) | **`precision=unknown` 격리로 완화**(버리기 대신 넘김) |
| 시간 예산 안 증분 저장(L659–687) | 유지(기본 900초, 체크포인트 저장) |
| `LM_TEAMSWEB_FAKE` fixture(L23–24) | 유지(시험) |
| | 중복 키 `(from,HH:MM,chat,body10)` **날짜 없음**(L501,528–530) → **msg_id 우선, 없으면 날짜 포함 키**(§5) |
| | 목록 렌더분만·상한 40·인덱스 열기(L220–254,665) → **가상 스크롤 순회 + 대화 ID 재탐색 + 체크포인트** |
| | 채널·활동(멘션) 피드 미수집 → **추가**(`--include-channels`·`--include-activity`) |
| | 작성자 없는 연속 메시지 본문 조각을 작성자로 폴백(L190–207) → **직전 작성자 상속, 불명 unknown** |
| | `teams_web.csv` 직접 저장(L554–591) → **`sanitize_record`+`SegmentWriter`**(원문 비저장) |
| | 종료코드 0/1/2/3 유지하되 `1` 에 '신규 0' 흡수 |

### 14.4 폐기(discard, 넣지 않음)

Graph `Get-TeamsChats.py`(device-code·`ORDER_HINTS` 부분일치 — 어댑터 자리만 §2), 쉼표 수 단체 판정,
전역 `mailTimeOffsetH` 일괄 적용, Copilot 재서술 행을 메시지와 병합, 원문 덤프 기본 저장, 세션 토큰 운반,
경로별 중복 구현(본인 판정·키·날짜 3~4벌), IndexedDB/LevelDB·`wpndatabase.db` 판독(§2).

---

## 15. 시험 시나리오 (합성·실데이터 없음)

주입점: `-RawFile`(UIA 원문 재생), `LM_TEAMSWEB_FAKE`(웹 화면 fixture), `LM_COPILOT_STUB`, 가상 시계.
각 시나리오는 기대 저장 레코드·커버리지 상태·rc 를 assert.

| # | 시나리오 | 기대(판정 기준) |
|---|---|---|
| 1 | 팝아웃 채팅 창만 사용 | 모든 최상위 창 열거로 수집, `MainWindowHandle` 외 창 포함, 신규>0, rc 0 |
| 2 | Teams 창 최소화/트레이 | `teams.uia` `blocked:R-UIAEMPTY`, 그날 0건을 '성공'으로 숨기지 않음, rc 1/4, `teams.web` 백필 todo |
| 3 | Teams 표시 언어 ≠ Windows 지역 | 지역 파서 0줄 → 일반 형식 재시도 성공, `teams.timeRegex` 설정으로도 통과 |
| 4 | 날짜 표기 없는 UIA 줄 | `precision=unknown` 격리, 시간 근거 기여 0, `n_unknown` 집계, 수집일 추정 안 함 |
| 5 | 웹 목록 가상화(방 60개, 상한 밖) | 가상 스크롤 순회로 하단 방 수집, LM24 상한 40 재현 안 됨, `R-LISTVIRT` 없음 |
| 6 | 같은 메시지 UIA+웹 둘 다 | `msg_key` 병합 1회 계상(날짜 포함 키), 매일 같은 시각 정형 메시지가 하루치로 뭉개지지 않음 |
| 7 | 웹 재렌더 'gone' | 대화 ID 재탐색·체크포인트 재개, 실패 방만 `R-ROOMGONE`, 경로 전체 실패 아님 |
| 8 | 연속 메시지(작성자 생략) | 직전 작성자 상속, 짧은 본문을 작성자로 오인 안 함, 불명은 `direction=unknown`(수신 단정 금지) |
| 9 | 이름 붙은 단체방·채널 | `chat_type=group/channel` 구조 판정, 쉼표 수 미사용, `n_participants` 기록 |
| 10 | 지시 어미 수신 / `확인`·`공유` 포함 발신 | `act=request`(수신)·`report`(발신), 부분일치 오더 과대 없음, 경로 무관 동일 판정 |
| 11 | Edge 정책 차단 | 탐침 `R-EDGEPOL`, `teams.web` not_attempted, UIA 대체, 서로 다른 날 2회 전엔 불가 미확정 |
| 12 | 웹 로그인 필요 | rc 2, `R-LOGIN` 안내+폴링(600초), 로그인 전 '불가' 확정 안 함 |
| 13 | Copilot 커넥터 없음 | `teams.copilot` `R-NOCONN`, `copilot_ev` 와 메시지 **병합 안 됨**, 이중 계상 0, 탐침 바뀌면 해제 |
| 14 | 본문에 전화·계좌·금액 | 저장 전 `[전화]`/`[계좌]`/`[금액]` 치환, Copilot 게이트 재검사, 카나리아 0건 |
| 15 | 사적/친목 대화방 | `priv_class=private/social`, `body_masked`·`file_names_masked` 비움, 시간 근거 제외, 방 성향 소급 가림 |
| 16 | 예산 소진(백필 중) | `partial`·`R-BUDGET`, 지금까지 저장, 체크포인트로 다음 실행 이어 읽음 |
| 17 | 멀티PC 재방문(PC1→백필PC→PC1) | 세그먼트 덧붙임만, `chat_key` 병합, 같은 방 분열 없음 |
| 18 | 수동 태깅 | `tag_feedback.json` 의 `act` 가 자동판정 덮어씀(`act_source=manual`), 원문 미기록 |

공통 판정: date-only·unknown·summary 시간 기여 0, **PII 카나리아 0건**(세그먼트·프롬프트·팀 페이로드),
중복 병합 후 건수 보존, 상한 걸리면 `partial`/`cap_hit`, 제어문자 0, 설정 키 단일 레지스트리, ps1 인코딩(UTF-8 BOM+CRLF).

---

## 16. 설정 키 (단일 레지스트리, `teams.*`)

| 키 | 기본 | 뜻 |
|---|---|---|
| `collect.backfillPc` | `"cloud"` | 계정 백필 담당 PC(공통) |
| `teams.selfNames` | `[]` | 본인 표시명 — **HMAC `person_key` 로 저장**(실명 금지). 로컬 전용 입력 도구로 평문→키 변환(§17.6) |
| `teams.timeRegex` | `""` | UIA 시각 정규식 최우선 탈출구(그룹 1=앞표기,2=시,3=분,4=뒤표기) |
| `teams.samplerIntervalSec` | `300` | 상주 샘플러 주기(120~300) |
| `teams.sampler.visibleOnly` | `true` | 가시 창만 읽기 |
| `teams.uia.maxElements` | `4000` | 창당 UIA 요소 상한 |
| `teams.uia.windowWatchdogSec` | `15` | 창당 UIA 읽기 워치독 |
| `teams.web.profileDir` | (PC별) | 본인 전용 Edge 프로필 경로(이동 금지) |
| `teams.web.port` | (자동) | CDP 포트(127.0.0.1) |
| `teams.web.maxChats` | `0` | 0=예산 안 무제한(LM24 40 폐기) |
| `teams.web.budgetSec` | `900` | 웹 백필 전체 예산 |
| `teams.web.maxScroll` | `12` | 대화당 되감기 상한 |
| `teams.web.includeChannels` | `true` | 채널 글타래 순회 |
| `teams.web.includeActivity` | `true` | 활동(멘션) 피드 순회 |
| `teams.web.loginWaitSec` | `600` | 로그인 폴링 상한 |
| `teams.copilot.enabled` | `false` | 코파일럿 팀즈 증인 사용 |
| `teams.copilot.chunkDays` | `7` | 조각 길이(행 상한 50) |
| `teams.pmWeightKeys` | `[]` | 상급자/PM 가중(HMAC 키, 실명 금지) |
| `teams.privateChatsFile` | `data\local_only\private_chats.json` | 사용자 지정 사적방 |
| `confirmBlockedCount` | `2` | 불가 확정 횟수(공통) |
| `probe.budgetSec` | `60` | 탐침 예산(공통) |
| `ledger.mismatchRatio` | `1.3` | 출처 간 건수 괴리 경고(공통) |

---

## 17. 반환 요약 (오케스트레이터용)

- **경로**: 물리적으로 `D:\배포\loadmon27\docs\COLLECT_TEAMS.md`(트리 개명 전 — §0). 내용 명칭은 **LM27**.
- **요약**: 팀즈 3경로 + 수동 태깅을 '역할 분담 + `msg_key`(날짜 포함) 병합 + (일자×대화방) 커버리지'로 설계.
  `teams.uia`(모든 최상위·팝아웃 창, 가시일 때만, 2~5분 상주, 헤더/본문 분리·지역 파서 계승, 날짜 미상 격리,
  이 PC Teams 사용 시간) + `teams.web`(백필 PC, 기간 전체, 가상 스크롤+채널+활동, message_id·`<time datetime>`
  우선, 대화방별 체크포인트 증분, 탭 소유·종료, CDP 자기포트 제한) + `teams.copilot`(커넥터 통과 시 요약 증인,
  메시지와 병합 안 함). **앱 내부 캐시(IndexedDB/LevelDB)·알림 DB·Graph·숨김 폴더·`--remote-allow-origins=*`
  는 영구 제외**(§2). 원문은 메모리/파이프에서만, `lm27.privacy.sanitize_record` 통과 열 허용 목록만 저장.
- **인터페이스**:
  - PS(`Get-TeamsWindow.ps1`) → stdout NDJSON(`teams.raw/1`) → `python -m lm27.privacy.sanitize_stream
    --kind teams --src teams.uia --pc <pc_id> --out <seg.jsonl.gz>`(또는 `lm27_pipe.py --kind teams`).
  - PY(`Get-TeamsWeb.py`·`Get-TeamsViaCopilot.py`) → `lm27.privacy.sanitize_record("teams", raw, rc) ->
    RecordOutcome` + `SegmentWriter.append(SanitizedRow)`.
  - 공통 모듈: `lm27.privacy.classify.act_of()`/`private_score()`/`room_prior()`, 본인 이름 집합 1벌.
  - 원시 스키마 §3.1(`teams.raw/1`), 저장 열 §3.2(=PRIVACY §10.2 teams). 키 `msg_key`/`chat_key`/`thread_key`
    (PRIVACY §9.3). rc 0/1/2/3/4 + R-*(§12.1). 상주 샘플러 작업명 `LM27-<install_id>`.
- **설정 키**: §16 표(`teams.*` + 공통 `collect.backfillPc`·`confirmBlockedCount`·`probe.budgetSec`·`ledger.mismatchRatio`).
- **미결(open issues)**:
  1. **트리·명칭 일괄 개명(LM27→LM27)**: 사용자 지시로 제품은 LM27 인데 형제 문서(`COLLECTION.md`·`PRIVACY.md`·
     `COLLECT_MAIL.md`·`COLLECT_PC.md`)와 산출물(`LM27_*.zip`)은 아직 `lm27`/`LoadMonitor27`/`LM27-`. 트리
     `loadmon27→loadmon27`, 네임스페이스 `lm27.*→lm27.*`, 에이전트/작업명/패키지 일괄 치환이 **프로젝트
     전역 작업**으로 필요(단일 파일 작업 범위 밖). 이 문서는 선제적으로 LM27 을 쓴다 — 개명 전까지 구현자는
     `lm27.privacy`↔`lm27.privacy` 1:1 대응으로 읽을 것.
  2. **COLLECTION §3 ↔ PRIVACY §10.2 저장 열 이름 불일치(팀즈)**: `subject_tokens`(C) vs `body_masked`(P),
     `counterpart_keys`(C) vs `author_key`+participants(P), `attach_keys`(C) vs `file_names_masked`+`file_keys`(이
     문서). 이 문서는 PRIVACY §10.2 를 저장 진실로 삼고 `file_keys`(=`attach_keys`)를 **추가 보존**(종료② 교차검증).
     계약 소유자가 한쪽으로 통일 필요(COLLECT_MAIL 미결 #1 과 같은 문제).
  3. **`message_id`·`<time datetime>` 실측**: Teams v2 웹 DOM 에 `data-mid`/`id='content-<ms>'`·`<time datetime>`
     가 안정적으로 노출되는가(P-WEB 로 측정). 노출되면 정밀 시각과 경로 간 중복 키가 한 번에 해결.
  4. **`teams.uia` 사용시간 ↔ COLLECT_PC 봉투 조정**: 전경 시간 1차 소유자는 PC 샘플러. 팀즈 사용시간은 2차
     교차검증 신호로만 두어 봉투에 이중 가산되지 않게 하는 경계(§7.5) — COLLECT_PC 와 합의 필요.
  5. **UIA 합성 `chat_key` 의 PC 간 불안정**: 원 ID 없는 UIA 는 창 제목 기반 합성이라 PC·언어마다 다를 수
     있음. 웹 백필 `chat_key` 를 병합 기준으로 우선하는 규칙이 충분한지(아니면 UIA 방↔웹 방 매핑 보강 필요).
  6. **본인 이름·PM 목록의 해시 저장**: `teams.selfNames`·`teams.pmWeightKeys` 를 평문 금지·HMAC 저장으로
     두되, 로컬 평문→키 변환 도구의 위치·UX 확정 필요(실명 금지 원칙).
  7. **R-* 신규 코드 등재**: `R-WEBSEL`·`R-LISTVIRT`·`R-ROOMGONE` 를 COLLECTION §4.2 공식 표에 추가 요청.
  8. **지시가 주로 오는 채널 유형**(1:1/그룹/채널/회의)과 채널·활동 피드 수집 우선순위 — 실데이터 탐침 후 가중 조정.
