# LM27 수집 계층 명세 (COLLECTION.md)

판: v1 · 대상 독자: 수집기 구현자 · 상위 규율: `docs/_decisions.md`(오케스트레이터 결정 메모), `docs/PRIVACY.md`(정제 명세), `docs/CONTRACT.md`(계약·관문)

이 문서는 LM27 **수집 계층**의 전체 개요와 모든 수집기가 지키는 공통 계약을 정한다. 구현자는 이 문서만으로 수집기·탐침·원장·계획기·오케스트레이터를 코드로 옮길 수 있어야 한다. 분석·시간추론·분류·보고서는 이 문서의 범위가 아니다(별도 명세).

규칙 요약(어기면 안 됨):

- **문서화·지원되는 사용자 인터페이스만** 쓴다. 설계에 넣지 않는 것: Microsoft Graph, 앱 내부 캐시 직접 판독(Teams IndexedDB/LevelDB, 알림 DB `wpndatabase.db`), OST/PST 직접 파싱, 숨김 메일함 폴더 탐색, 자격 증명 접근, 관리자 권한 요구, 보안 정책 우회. 이 경계를 넘는 경로는 어느 출처에도 없다.
- **원문은 메모리에서만** 다룬다. 디스크에는 `lm27.privacy.sanitize_record(kind, record)` 를 통과한 **열 허용 목록 레코드만** 쓴다(§3·§11). 원문 CSV/덤프/프롬프트 파일을 남기지 않는다.
- 실명·계정·이메일·사내 코드네임을 코드·문서·샘플·프롬프트에 넣지 않는다(예시는 자리표시자 홍길동·과제A·고객사#).
- 사용자를 대신해 로그인하지 않는다. 로그인은 사람이 1회. 다른 사용자에게 수동 조작(재분석 버튼·zip 풀기)을 요구하지 않는다 — 자동 복구.
- 이전 판 폴더(`D:\배포\loadmon2x`), 다른 도구의 `D:\배포\LM26`(포트 8765~8767) 는 **읽기 전용**. LM27 수집 산출물·포트는 이들과 겹치지 않는다.

---

## 0. 저장 배치와 운반 모델

수집은 두 저장소로 나뉜다.

### 0.1 상주 에이전트 저장소 (이 PC에 머문다)

`%LOCALAPPDATA%\LoadMonitor27\agent\<install_id>\`

```
store\<pc_id>\
  raw_cursor.json              # 소스별 마지막 관측 커서 (증분 수집용)
  evidence\<kind>\<src>\*.jsonl.gz   # 정제 통과 레코드(로컬 1차 적재, 추가 전용)
  sanitize_audit.jsonl         # 정제 감사(유형별 건수만)
heartbeat.json                 # 마지막 틱·pid·버전·저장 경로·에이전트 버전
```

- 샘플러·이벤트 수확기·로컬 원장은 전부 여기. 폴더 드래그·OneDrive 동기화와 무관하다.
- Copilot 전용 Edge 프로필(`bridge_profile`)도 에이전트 쪽(`%LOCALAPPDATA%`)에 둔다 — **운반 번들에 넣지 않는다**.
- 작업명·뮤텍스는 `LM27-<install_id>` 로 한다(판 공통 이름 금지).

### 0.2 운반 번들 (사용자가 폴더째 드래그한다)

프로그램 폴더 `D:\배포\loadmon27\data\bundle\`

```
manifest.json                  # 세그먼트 목록·sha256·내보내기 커서
pcs\<pc_id>\
  pc.json                      # PC 레지스트리 + 능력 탐침 결과(§4)
  seg\<seq>_<from_utc>_<to_utc>.jsonl.gz   # 출처 무관 통합 세그먼트(불변)
coverage_ledger.jsonl          # 계정×날짜×종류×출처×PC 셀(§5)
todo.json                      # 빈칸 계획기 작업 목록(§6)
```

- 세그먼트는 **불변**이다. `<seq>` 는 pc_id 안에서 단조 증가. 같은 PC에 다시 와도 세그먼트를 **덧붙이기만** 한다. 다른 `pc_id` 자료는 절대 rename·이동하지 않는다.
- 번들 안 모든 파일명에 `pc_id` 가 들어가 OneDrive 공유 시 동명 충돌이 없다.
- 흐름 PC1 → PC2 → 클라우드PC 에서 각 PC가 [수집]을 누르면: ① 에이전트 설치·자가검증 → ② 소스별 커서 이후만 증분 수확(로컬 store) → ③ 그 pc_id 의 마지막 내보내기 커서 이후를 새 세그먼트로 번들에 내보냄 → ④ pc.json 능력 탐침 갱신 → ⑤ 커버리지 원장·todo 갱신.

---

## 1. 수집 단위와 역할 분담

수집 단위는 **(PC, 계정)** 이다. PC 단위 자료(가동·창·파일·git)는 그 PC에서만 수집한다. 계정 단위 자료(메일·일정·팀즈 '내용')의 **기간 전체 백필은 백필 담당 PC(기본 클라우드PC)에서 한 번**만 하고, PC1·PC2는 자기 PC에서 로컬로 되는 경로만 돌린다. 중복은 §7 병합으로 제거한다.

| 역할 | PC1 / PC2 (업무 PC) | 클라우드PC (백필·분석 담당) |
|---|---|---|
| 능력 탐침 | 매 수집 앞 (pc.json) | 매 수집 앞 (pc.json) |
| PC 가동·세션 | pc.sampler(상주), pc.events | pc.sampler, pc.events (VDI 세션 경계 포함) |
| 파일·문서·git | pc.files, pc.mru, pc.recent, pc.git, pc.compute | 해당 PC에서 작업했으면 동일 |
| 메일·일정(로컬) | mail.com/cal.com, mail.index/cal.index (되는 PC만) | 클래식 Outlook 있으면 동일 |
| 메일·일정(계정 백필) | — (안 함) | **mail.owa/cal.owa 기간 전체, mail.copilot 증인** |
| 팀즈 실시간 | teams.uia (상주 샘플러) | teams.uia |
| 팀즈 계정 백필 | — | **teams.web 기간 전체, teams.copilot 증인** |
| 반입 | mail.import/cal.import (사용자 반입 폴더) | 동일 |
| 수동 기록 | manual | manual |
| Copilot 분석·정제 게이트 | — (로그인 없음) | 유일하게 여기서 (별도 명세) |

규칙:

- **Copilot 로그인·사용은 클라우드PC 한 곳**. PC1·PC2는 Copilot/웹 백필을 돌리지 않는다. Edge 디버그 프로필은 클라우드PC에만.
- 백필 담당 PC는 `config: collect.backfillPc`(기본 `"cloud"`)로 지정. 클라우드PC가 없으면 사용자가 1대를 백필 담당으로 지정.
- "안 함"은 로컬 경로가 없다는 뜻이 아니라 **계정 백필(기간 전체 되감기)을 그 PC에서 하지 않는다**는 뜻. PC1에서 COM이 되면 그 PC의 봉투 근거로 수집한다. 계정 전체 공백은 백필 PC가 채운다.

---

## 2. 출처 목록과 경로 ID

각 출처는 경로 ID로 식별한다. 수집기 스크립트는 `collect\` 아래. PowerShell은 PS 5.1(.ps1 = UTF-8 BOM+CRLF), 파이썬은 동봉 CPython 3.11 표준 라이브러리(ctypes 가능).

| 경로 ID | kind | 수집기 | 언어 | 메커니즘(문서화된 UI만) |
|---|---|---|---|---|
| `mail.com` | mail | `Get-OutlookCom.ps1` | PS | 클래식 Outlook COM(실행 중 프로필). 저장소의 모든 메일 폴더 재귀, DASL UTC 필터, GetTable |
| `mail.index` | mail | `Get-OutlookIndex.ps1` | PS | Windows Search `Search.CollatorDSO` OLE DB, `System.Kind='email'`, `ItemUrl LIKE 'mapi%'` |
| `mail.owa` | mail | `Get-OutlookWeb.py` | PY | 본인 전용 Edge 프로필을 CDP(127.0.0.1)로 붙어 outlook.office.com 판독(백필 PC만) |
| `mail.copilot` | mail | `Get-MailViaCopilot.py` | PY | M365 Copilot Chat 왕복(클라우드PC만, 존재·건수 증인) |
| `mail.import` | mail | `Import-MailCal.py` | PY | 사용자 반입 폴더의 EML·CSV 판독(정식 대체 경로) |
| `cal.com` | cal | `Get-OutlookCom.ps1` | PS | COM 기본 일정 폴더, `IncludeRecurrences=$true`+`Sort('[Start]')`, 응답 상태 |
| `cal.index` | cal | `Get-OutlookIndex.ps1` | PS | SystemIndex `System.Kind='calendar'`(반복 회의 미전개 → 불완전 표기) |
| `cal.owa` | cal | `Get-OutlookWeb.py` | PY | OWA 주 보기(회차 전개). 색인이 못 하는 반복 회의 보완(백필 PC만) |
| `cal.import` | cal | `Import-MailCal.py` | PY | 반입 폴더의 ICS 판독 |
| `teams.uia` | teams | `Get-TeamsWindow.ps1` | PS | Teams 데스크톱 창 UI Automation(접근성 API) 판독. 상주 샘플러 |
| `teams.web` | teams | `Get-TeamsWeb.py` | PY | 본인 Edge 프로필 CDP로 teams.microsoft.com/v2 DOM 판독(백필 PC만) |
| `teams.copilot` | teams | `Get-TeamsViaCopilot.py` | PY | Copilot 요약 증인(커넥터 있을 때만, 클라우드PC) |
| `pc.sampler` | pc_session | `Start-ActivitySampler.ps1` / `sampler.py` | PS/PY | 전경 창·입력 유휴·세션 상태 Win32 API 폴링(상주) |
| `pc.events` | pc_session | `Get-EventActivity.ps1` | PS | 이벤트 로그(전원·세션·RDP) 사용자 권한 채널 |
| `pc.files` | pc_file | `Get-FileActivity.ps1` | PS | 지정 폴더 파일 mtime 스캔, OOXML 작성자·TotalTime |
| `pc.mru` | pc_file | `Get-OfficeMru.ps1` | PS | HKCU Office MRU(14.0/15.0/16.0 전수) + Jump Lists |
| `pc.recent` | pc_file | `Get-RecentFiles.ps1` | PS | Windows Recent(.lnk) 바로가기 |
| `pc.git` | pc_git | `Get-GitActivity.py` | PY | 본인 신원 `git log`(전 브랜치, LC_ALL=C) |
| `pc.compute` | pc_compute | (샘플러 파생) + `Get-LicenseUsage.ps1`(옵트인) | PS | 비시스템 프로세스 CPU 차분 compute 구간 + 본인 FlexLM 행(옵트인) |
| `manual` | manual | `Add-WorkLog.ps1` | PS | 수동 업무 기록(키보드 밖 업무의 유일한 신뢰 근거) |

**경계 금지(명시)**: 위 어느 경로도 Graph API, Teams IndexedDB/LevelDB, `wpndatabase.db`, OST/PST 직접 파싱, 숨김 폴더(TeamsMessages 비IPM 루트 등), 자격 증명, 관리자 권한을 쓰지 않는다. 막혀서 안 되는 날은 §5 커버리지 원장에 사유 코드로 남길 뿐, 금지 경로로 우회하지 않는다.

---

## 3. 공통 증거 레코드 스키마

모든 수집기는 **같은 JSONL 레코드 한 벌**로 쓴다(세그먼트 파일 `seg\*.jsonl.gz` 한 줄 = 한 레코드). `kind` 가 레코드 종류를 정하고, 종류별 필수/선택 필드는 아래 표를 따른다. `src` 는 §2 경로 ID.

### 3.1 공통 필드 (모든 kind 필수)

| 필드 | 형 | 설명 |
|---|---|---|
| `id` | str | 레코드 안정 ID = `sha1(src + '|' + pc_id + '|' + ts_utc + '|' + msg_key_or_doc_key + '|' + body_hash)`[:16]. 재수집해도 동일 |
| `kind` | str | `mail` / `cal` / `teams` / `pc_session` / `pc_file` / `pc_git` / `pc_compute` / `manual` |
| `src` | str | §2 경로 ID |
| `pc_id` | str | MachineGuid 의 HMAC(§11 키). 번들에는 해시만 |
| `ts_utc` | str | ISO 8601 UTC(`2026-09-01T04:05:00Z`). 레코드의 1차 시각 |
| `ts_local_offset` | str | 관측 당시 로컬 UTC 오프셋(`+09:00`). 분석이 로컬로 되돌릴 때 씀 |
| `ts_precision` | str | `exact` / `minute` / `date` / `summary` / `unknown`. `date`·`summary`는 시간 근거로 쓰지 않음 |
| `ts_end` | str\|null | 구간성 레코드(cal·pc_session·pc_compute)의 끝 UTC. 점 신호는 `null` |
| `direction` | str | `in`/`out`/`unknown`(mail), `sent`/`received`/`unknown`(teams), `null`(그 외) |
| `act` | str | **항상 빈 문자열** `""`. 화행(지시/수락/보고)은 **정규화 단계**에서 채운다(수집기는 판정하지 않음) |
| `thread_key` | str\|null | 스레드/대화 묶음 키(메일 대화 해시, 팀즈 reply_to). HMAC |
| `chat_key` | str\|null | 팀즈 대화방 키(HMAC). mail/cal 은 `null` |
| `counterpart_keys` | list[str] | 상대 가명 키 목록(나 제외). 발신자·수신자·주최자·참석자·작성자의 HMAC |
| `n_participants` | int | 참여 인원 수(수신+참조+나, 또는 대화방 인원) |
| `subject_tokens` | list[str] | 정제 통과 제목/본문 토큰(PII·금액·이름 치환 후). mail·cal·teams·git |
| `title_masked` | str\|null | 창 제목에서 추출·정제한 값(pc_session). doc 패턴이면 `doc_key`로 분리 |
| `doc_key` | str\|null | 문서 basename 정규화값(Office/CAD 창·파일·커밋 대상) |
| `app_id` | str\|null | 정규화 앱 ID(프로세스·앱 종류). pc_session·pc_file·pc_compute |
| `attach_keys` | list[str] | 첨부 파일명 줄기+확장자의 HMAC(문서작성완료→메일보고 연결용) |
| `flags` | obj | 불리언/열거 플래그 사전(§3.3) |
| `confidence` | float | 0.0~1.0. 출처·정밀도에 따른 기본값(§3.4) |
| `rules_ver` | str | 레코드를 정제한 `lm27.privacy` 규칙 버전(예 `"pii-2026.10"`) |
| `observed_at` | str | 수집한 시각 UTC(ISO) |

`msg_key`(병합용 키)는 mail/cal/teams 에 필수(§7). 공통 표에 두지 않고 종류별 표에 둔다.

### 3.2 종류별 필드

필수 = ✔, 선택 = ○, 해당없음 = —. 공통 필드(3.1) 외 추가/제약만 표기.

| 필드 | mail | cal | teams | pc_session | pc_file | pc_git | pc_compute | manual |
|---|---|---|---|---|---|---|---|---|
| `msg_key` | ✔ | ✔ | ✔ | — | — | — | — | — |
| `box`(inbox/sent) | ✔ | — | — | — | — | — | — | — |
| `folder_role` | ✔ | — | — | — | ○ | — | — | — |
| `direction` | ✔ | — | ✔ | — | — | — | — | — |
| `n_to`/`n_cc` | ✔ | — | — | — | — | — | — | — |
| `chat_type`(1:1/group/channel/meeting) | — | — | ✔ | — | — | — | — | — |
| `mentions_me` | — | — | ✔ | — | — | — | — | — |
| `ts_end` | — | ✔ | — | ✔ | — | — | ✔ | ○ |
| `subject_tokens` | ✔ | ✔(제목) | ✔(본문≤300자 정제) | — | — | ✔(커밋제목) | — | ○ |
| `attach_keys` | ✔ | — | ○ | — | — | — | — | — |
| `doc_key` | — | — | — | ○ | ✔ | ✔(repo) | ○ | ○ |
| `app_id` | — | — | — | ✔ | ✔ | — | ✔ | ○ |
| `title_masked` | — | — | — | ○ | — | — | — | — |
| `session_state` | — | — | — | ✔ | — | — | — | — |
| `idle_sec` | — | — | — | ✔ | — | — | — | — |
| `layer`(L0~L4) | — | — | — | ✔ | — | — | — | — |
| `ext` | — | — | — | — | ✔ | — | — | — |
| `n_commits` | — | — | — | — | — | ✔ | — | — |
| `work_category` | — | — | — | — | — | — | — | ✔ |
| `hours` | — | — | — | — | — | — | — | ✔ |

종류별 메모:

- **mail**: `box` 는 폴더 역할(EntryID 대조, 이름 아님)로 판정. `direction=out` 은 보낸편지함 또는 발신자=나. `folder_role` ∈ {inbox, sent, deleted(수집 제외), junk(제외), archive(설정 시)}. `n_to`/`n_cc` 로 bulk 판정. 회의 요청·응답 발신은 `flags.meeting_response=true` 로 별도 능동 신호.
- **cal**: `msg_key` = `GlobalAppointmentID` HMAC + 시작 UTC, 없으면 `(시작·끝 UTC, 제목 해시)`. `flags.response`(0~5), `flags.meeting_status`(취소 5·7), `flags.recurrence_incomplete`(색인 경로), `flags.organizer_me`, `flags.online_meeting`, `flags.all_day`.
- **teams**: `msg_key` = 메시지 ID(DOM/UIA 에 안정적으로 노출될 때) HMAC, 없으면 `hash(date + chat_key + author_key + 'HH:MM' + body_hash)`. `chat_type` 은 구조로 판정(쉼표 수 금지). 연속 메시지 작성자 상속, 불명은 `direction=unknown`(수신 단정 금지).
- **pc_session**: `session_state` ∈ {active, locked, disconnected, remote}. `idle_sec` = `(TickCount64 차) mod 2^32`, 음수·비단조는 0. `layer` ∈ {L0 전원/부팅, L1 세션, L2 입력활동, L3 전경앱/문서}. `flags.end_uncertain`(지어낸 끝), `flags.stuck`(idle 고착), `flags.always_on`, `flags.remote`.
- **pc_file**: `flags.view_only`/`edit`(target_mtime 비교), `flags.author_other`(OOXML lastModifiedBy≠나), `flags.pdf_export`, `flags.final_name`. 선택 수치 `ooxml_totaltime`(편집 분), `ooxml_revision`.
- **pc_git**: `counterpart_keys` 는 보통 비움(본인 커밋). `doc_key`=repo 정규화명. 날짜별 커밋 묶음은 `n_commits`.
- **pc_compute**: 샘플러 CPU 차분으로 만든 구간. `flags.solver`(카탈로그 라벨). 라이선스 옵트인 행은 `src=pc.compute`, `app_id`=제품명, 본인 체크아웃만.
- **manual**: `work_category`(출장·장비점검 등 자리표시자), `hours`(double), `ts_utc`=그 날 00:00+offset, `ts_precision='date'`.

### 3.3 flags 공통 열거

`ad`(광고 점수≥임계), `bulk`, `cc`, `list_unsub`, `precedence`, `esp`, `sensitivity`(0~2), `private`(사적 점수≥임계), `recurring`, `meeting_response`, `online_meeting`, `end_uncertain`, `stuck`, `always_on`, `remote`, `cap_hit`(상한 절단됨), `utc_suspect`, `view_only`, `author_other`, `pdf_export`, `final_name`, `solver`, `recurrence_incomplete`, `organizer_me`, `all_day`, `mentions_me`, `has_file`. 없으면 생략(기본 false).

### 3.4 confidence 기본값(출처×정밀도)

| 조건 | confidence |
|---|---|
| COM/색인 분 단위, 샘플러 active, git, 파일 mtime | 1.0 |
| OWA minute, UIA 날짜 확정, Office MRU[T] | 0.8 |
| OWA/Copilot date-only, 이벤트 로그 추정 끝, 브라우저 방문 힌트 | 0.4 |
| Copilot summary 증인, 작성자 상속 추정 | 0.3 |

### 3.5 레코드 예시(JSONL 한 줄)

```json
{"id":"7a1c9f2b0e4d6a81","kind":"mail","src":"mail.com","pc_id":"PCH#3f9a","ts_utc":"2026-09-01T23:40:00Z","ts_local_offset":"+09:00","ts_precision":"minute","ts_end":null,"direction":"out","act":"","thread_key":"T#9d2f","chat_key":null,"counterpart_keys":["P#1a2b","P#7c4e"],"n_participants":3,"n_to":2,"n_cc":1,"box":"sent","folder_role":"sent","msg_key":"M#e81f0a","subject_tokens":["보고","초안","과제A"],"attach_keys":["A#f10c.pptx"],"doc_key":null,"app_id":null,"flags":{"meeting_response":false},"confidence":1.0,"rules_ver":"pii-2026.10","observed_at":"2026-09-02T01:12:30Z"}
```

---

## 4. 능력 탐침 (probe)

수집 **앞에 매번** 돌린다. 내용은 기록하지 않고 **숫자·열거값·사유 코드만** 남긴다. 결과는 `pc.json` 의 `capability` 절에 들어가 §5 원장과 §9 진단이 '되는 사람/안 되는 사람'을 숫자로 설명하게 한다.

### 4.1 무엇을 재는가 (전수)

| 묶음 | 재는 값(숫자·열거) | 수집기 |
|---|---|---|
| P-ENV | PowerShell LanguageMode, `Get-ExecutionPolicy -List`, 현재 프로세스 권한 상승 여부, 시간대 ID+UTC 오프셋, 도메인·AAD 가입 여부, 내장 python ctypes 실행 가능 여부 | `Invoke-CapabilityProbe.ps1` |
| P-OL-INST | OUTLOOK.EXE 경로·버전, C2R/MSI 병존, 새 Outlook(olk) Appx·`UseNewOutlook`·마이그레이션 키, 프로필 수, 기본 프로필 해시, Office 지원 종료 여부 | 동 |
| P-OL-COM | (자식 프로세스+20초 워치독, 떠 있을 때만) Version, ExchangeConnectionMode, IsCachedExchange, Stores 수·유형, 동기화 기간(정책·레지스트리), 받은/보낸편지함 지평선(최고·최신 ReceivedTime), 기본 폴더 밖 메일 비중, Object Model Guard 상태(정책 키+보안센터 백신 상태+보호 속성 1회 시험 읽기) | 동 |
| P-IDX | WSearch 상태, PreventIndexingOutlook 등 정책, 카탈로그 상태·일시정지 사유, 색인 Outlook 메일·일정 30/90/365일 건수, 최고·최신 시각, 확장 속성 지원 | 동 |
| P-EDGE | Edge 설치, RemoteDebuggingAllowed·DeveloperToolsAvailability 정책, 전용 프로필 존재 | 동 |
| P-OWA(백필 PC) | 로그인 상태·AADSTS 코드, 최근 1주 표본의 분 정밀도 비율, 행 키 종류(대화 보기 여부) | `probe_owa.py` |
| P-TEAMS | 새/클래식 Teams 설치·버전, 최상위 창 핸들·UIA 텍스트 줄 수, 시각 패턴 일치 수 | `Invoke-CapabilityProbe.ps1` |
| P-CP(클라우드PC) | Copilot 메일·팀즈 커넥터 가능 여부(무해한 1행 질문, 2-strike), 모델·Work 모드, 입력/출력 실측 한도(calibrate) | `probe_copilot.py` |
| P-PC | 이벤트 채널별 읽기 권한, 샘플러 구현 자기시험 결과, Recent/MRU 정책(ClearRecentDocsOnExit 등), git 설치 | `Invoke-CapabilityProbe.ps1` |

규칙: P-OL-COM 의 보호 속성 시험 읽기는 **경고 없음이 확인될 때만** 실제 속성을 읽고, 시간 제한을 둔다. 부제목·주소·본문을 한 글자도 남기지 않는다(건수·bool만).

### 4.2 사유 코드 R-* 표

| 코드 | 뜻 | 트리거 |
|---|---|---|
| `R-NEWOL` | 새 Outlook 전용 → COM·색인 불가 | olk 전용, `UseNewOutlook=1` |
| `R-NOPROF` | Outlook 프로필 0 | 프로필 수 0 |
| `R-WIZARD` | 구판 MSI 등록 → 시작 마법사 무한대기 | COM 미등록 or 병존 MSI, New-Object 금지 |
| `R-DIALOG` | Outlook 모달·대화상자에 막힘 | 떠 있는데 GetActiveObject 실패 |
| `R-CLM` | 제한 언어 모드/실행정책/AppLocker → COM·OleDb 불가 | LanguageMode≠FullLanguage |
| `R-OMG` | Object Model Guard 경고 가능 | 백신 상태≠Valid or 정책 '항상 경고' |
| `R-ELEV` | 권한 상승 불일치 → GetActiveObject 실패 | 현재 프로세스 상승, Outlook 일반 |
| `R-ONLINE` | 온라인 모드 → 로컬 색인 비어 있음 | IsCachedExchange=false |
| `R-HORIZON` | 캐시 동기화 기간 밖 | 요청 기간이 지평선보다 오래됨 |
| `R-SUBFOLDER` | 기본 폴더 밖 비중 높음 → COM 누락 위험 | 기본 폴더 밖 메일 비중>임계 |
| `R-STALE` | OST 신선도 오래됨 | 최신 수신 시각이 now−임계보다 과거 |
| `R-NOIDX` | WSearch 꺼짐/색인 비활성 | 서비스 중지 or Outlook 항목 0 |
| `R-IDXPOLICY` | 색인 정책 차단 | PreventIndexingOutlook 등 |
| `R-IDXPAUSED` | 색인 일시정지·재구축 중 | PausedReason 있음 |
| `R-EDGEPOL` | Edge 원격 디버깅 차단 | RemoteDebuggingAllowed=0 / DevTools=2 |
| `R-LOGIN` | 웹 로그인 필요/세션 만료 | OWA·Teams·Copilot 로그인 화면 |
| `R-CA` | 조건부 액세스 차단 | AADSTS 코드 |
| `R-NOLIC` | Copilot 사서함 근거 라이선스 없음 | 무라이선스 Chat |
| `R-NOCONN` | Copilot 커넥터 없음 | Teams/Mail 조회 도구 부재 |
| `R-TZ` | 시간대 UTC/사서함 시간대 불일치 위험 | 클라우드PC UTC 등 |
| `R-OFFICE` | 지원 종료 Office 버전 | 버전 EOL |
| `R-UIAEMPTY` | UIA 텍스트 0(창 숨김·최소화) | 핸들 0 or 줄 0 |
| `R-UIAELEV` | 관리자 권한 창 → UIA 불가 | elevated/no-tree |
| `R-NOADDR` | 내 주소 미확정 → rcv unknown | whoami/upn 실패 등 |
| `R-NOEVT` | 이벤트 채널 읽기 권한 없음 | 채널 unauthorized |
| `R-CAP` | 상한 도달(절단) | 조용한 상한에 걸림 |
| `R-BUDGET` | 시간 예산 소진 | 스테이지 예산 초과 |
| `R-TRANSPORT` | 수송 실패(드라이버·네트워크) — **'불가' 아님** | 타임아웃·드라이버 오류 |

`R-TRANSPORT` 는 '불가' 확정 근거로 쓰지 않는다(§6).

### 4.3 워치독·타임아웃

- 모든 COM 호출은 자식 프로세스 + 20초 워치독에서 한다(PID 먼저 내보내고, 초과면 그 프로세스를 직접 종료). `New-Object` 는 프로필이 있고 떠 있지 않을 때만. 떠 있는데 못 붙으면 `R-DIALOG` 로 skip.
- 탐침 전체 예산 기본 60초(`config: probe.budgetSec`). OWA/Copilot 탐침은 백필·클라우드 PC에서만.
- 보호 속성 시험 읽기 2초 제한. 초과·거부면 `R-OMG`.

### 4.4 pc.json capability 절(형)

```json
{
  "pc_id":"PCH#3f9a","label":"홍길동-노트북","kind":"laptop",
  "tz":"Asia/Seoul","utc_offset":"+09:00","anchor_since":"2025-04-01T00:00:00Z",
  "first_seen":"2026-08-01T...","last_seen":"2026-09-02T...","agent_ver":"26.1.0",
  "capability":{
    "env":{"language_mode":"FullLanguage","elevated":false,"ctypes_ok":true,"domain_joined":true},
    "mail.com":{"ok":true,"horizon_oldest":"2025-09-01","horizon_newest":"2026-09-02","subfolder_ratio":0.12,"reasons":[]},
    "mail.index":{"ok":true,"n_30d":812,"n_365d":9123,"reasons":[]},
    "mail.owa":{"ok":false,"reasons":["R-EDGEPOL"]},
    "mail.copilot":{"ok":null,"reasons":["R-NOLIC"]},
    "teams.uia":{"ok":true,"uia_lines":214,"reasons":[]},
    "pc.sampler":{"ok":true,"impl":"ps","reasons":[]}
  },
  "probe_sig":"2026-09-02T01:10:00Z|hash",
  "confirmed_blocked":{"mail.owa":2}
}
```

`ok` ∈ {true, false, null(불확정)}. `reasons` 는 R-* 목록. `confirmed_blocked` 는 서로 다른 날 확인 횟수(§6).

---

## 5. 커버리지 원장 (coverage_ledger)

번들의 `coverage_ledger.jsonl` 에 셀 단위로 쓴다. PC1→PC2→클라우드PC 로 이동하며 합성된다.

### 5.1 셀 키와 상태

- 셀 = `(account, date, kind_axis, src, pc_id)`.
  - `kind_axis` ∈ `{mail_in, mail_out, cal, teams, pc}` (요구의 5축; mail 은 수신/발신 분리).
  - `account` 는 계정 가명 키(기본 단일 사용자면 상수).
- 상태 `status` ∈:

| 상태 | 뜻 |
|---|---|
| `ok` | 읽었고 건수>0 |
| `zero_ok` | 읽었고 0건(정상 — 그 날 그 종류 활동 없음) |
| `partial` | 상한·예산으로 일부만(절단됨) |
| `out_of_horizon` | 동기화 기간/보존 밖(서버에만) → 백필 대상 |
| `blocked` | 사유 코드로 막힘(R-*) |
| `transport_fail` | 수송 실패(드라이버·네트워크) — '불가' 아님 |
| `not_attempted` | 시도 안 함(그 PC에 그 경로 없음) |

### 5.2 셀 레코드 필드

| 필드 | 형 | 설명 |
|---|---|---|
| `account`/`date`/`kind_axis`/`src`/`pc_id` | str | 셀 키 |
| `status` | str | 위 열거 |
| `n` | int | 레코드 수 |
| `n_minute`/`n_date` | int | 분 정밀·date-only 건수 |
| `horizon_oldest`/`horizon_newest` | str\|null | 그 경로가 본 지평선 |
| `reason` | list[str] | R-* (status=blocked/transport_fail) |
| `budget_hit`/`cap_hit` | bool | 예산·상한에 걸렸는가 |
| `probe_sig` | str | 이 셀을 만든 탐침 서명 |
| `run_id` | str | 세그먼트 run |
| `observed_at` | str | UTC |

### 5.3 합성과 시간 모델 규칙

- **일자 합성 상태** = 그 (account, date, kind_axis) 의 출처 중 **최선 값**. 출처 간 건수가 1.3배 넘게 어긋나면(`config: ledger.mismatchRatio`) 'COM 누락 의심' 사유를 붙인다.
- **미관측을 0h 로 보지 않는다**: `not_attempted`/`blocked`/`transport_fail`/`out_of_horizon` 날은 '근거 없음'으로 표시해 '일 안 한 날'(`zero_ok`)과 구분한다. 시간 모델(별도 명세)은 이 구분을 입력으로 받는다.
- `date-only`(n_date) 는 존재·건수 증거일 뿐, 시간 근거로 승격하지 않는다.

---

## 6. 빈칸 계획기 (todo.json)

원장의 빈 셀에 대해 '다음에 가능한 출처·PC'를 번들 `todo.json` 작업으로 남긴다. 다음 PC/다음 실행이 자동으로 집어 간다. 사람에게 수동 조작을 요구하지 않는다(브라우저 1회 로그인·대화상자 닫기 안내만).

### 6.1 작업 레코드

```json
{"todo_id":"owa-2026-07","account":"self","date_range":["2026-07-01","2026-07-31"],
 "kind_axis":"mail_in","want_src":"mail.owa","want_pc":"cloud","reason":["R-HORIZON"],
 "attempts":[{"pc_id":"PCH#3f9a","date":"2026-09-01","result":"R-HORIZON"}],
 "state":"open","updated":"2026-09-02T01:20:00Z"}
```

- `state` ∈ {`open`(배정 대기), `assigned`(백필 PC 할당), `blocked_confirmed`(불가 확정), `released`(자동 해제)}.
- 배정 규칙: 빈 셀 사유 → 가능 출처 매핑(예: `R-HORIZON`/`R-NEWOL`/`R-ONLINE` → `mail.owa`@백필PC; 색인만 불완전한 일정 → `cal.owa`; 그래도 비면 `*.copilot` 증인).

### 6.2 '불가' 확정과 자동 해제

- **불가 확정**: 서로 다른 날 **2회 이상** 같은 사유로 막힘 + **그 사유가 `R-TRANSPORT` 아님** 일 때만 `blocked_confirmed`. 확정 횟수는 `config: confirmBlockedCount`(기본 2).
- **자동 해제**: 탐침 값이 바뀌면(예: 클래식 Outlook 실행됨, 로그인 완료, Edge 정책 변경) 관련 `blocked_confirmed` 를 `released` 로 돌리고 다시 `open`. 수동 삭제·플래그 파일에 의존하지 않는다.

---

## 7. 병합 규칙

출처·PC 가 겹쳐도 같은 메시지·일정·메시지를 두 번 세지 않는다. 세그먼트는 불변이므로 병합은 **읽기 시 파생**으로 한다(세그먼트를 덮어쓰지 않음).

### 7.1 msg_key 우선순위

출처 신뢰 순위: `COM > 색인 > OWA(minute) > OWA(date) > Copilot`. 같은 `msg_key` 레코드는 필드 단위로 가장 좋은 값을 골라 하나의 병합 레코드를 만들고, 모든 출처를 `provenance` 목록으로 남긴다(원 세그먼트는 보존).

### 7.2 키 생성

- 메일: `Message-ID` HMAC 이 있으면 그대로. 없으면 퍼지 키 `(box, UTC 분 ±2, thread_key, counterpart 집합)`.
- 일정: `GlobalAppointmentID` HMAC + 시작 UTC, 없으면 `(시작·끝 UTC, 제목 해시)`.
- 팀즈: 메시지 ID HMAC, 없으면 `hash(date + chat_key + author_key + 'HH:MM' + body_hash)`.
- **중복 제거 키는 정제 '전' 원문으로 HMAC** 을 계산해 저장한다(§11). PC마다 정제 결과가 달라도 같은 메시지가 두 번 세어지지 않게.

### 7.3 date-only 흡수와 PC·경로 중복

- 같은 `(date, box, thread_key)` 에 분 단위 정확 사본이 있으면 `date-only` 레코드는 병합에서 버린다(존재 증거 역할 끝).
- PC 간·경로 간 중복은 `msg_key` 로 union. 시간대는 UTC 로 정규화해 비교(Copilot UTC·클라우드PC UTC 어긋남 방지).

---

## 8. 수집 실행 오케스트레이션

진입점: `python -m lm27 collect [옵션]` (동봉 python, 루트를 스스로 sys.path 에 넣는다).

### 8.1 옵션

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `--mode` | `auto` | `auto`(bat 더블클릭·무질문) / `probe-only` / `recollect` |
| `--since` / `--until` | 설정 기간 | 수집 대상 기간(로컬) |
| `--pc-role` | 자동 | `pc1`/`pc2`/`cloud` 강제(자동 추정 실패 시) |
| `--only` | (없음) | 특정 src 만(쉼표). 진단용 |
| `--budget-sec` | 설정 | 전체 시간 예산 |

### 8.2 단계 순서와 병렬

1. **probe**(§4) — 항상 먼저. pc.json 갱신.
2. **pc 묶음**(모든 PC): sampler 생존 보장 → events → files → mru → recent → git → compute. 서로 독립이라 `config: collect.parallelMax`(기본 2)까지 병렬. 샘플러는 상주이므로 '등록·생존 확인'만.
3. **mail/cal 로컬**: `com`(되면) → `index`(항상, 교차검증). COM 은 자식 프로세스 직렬. 색인은 병렬 가능.
4. **teams 로컬**: `uia`(상주 샘플러 생존 확인).
5. **백필·클라우드 전용**(백필 PC일 때만): `owa`(일정 전 기간·메일 빈 셀) → `teams.web`(기간 전체) → `copilot`(빈 날 증인). 이 단계는 로그인 필요 시 `R-LOGIN` 안내 후 폴링(최대 10분).
6. **반입·수동**: `import`, `manual` 은 언제든(폴더에 파일 있으면).

'첫 성공에서 멈추는 사슬'을 쓰지 않는다. 각 셀(날짜×종류)이 `ok`/`zero_ok` 가 될 때까지 §6 계획기가 다음 출처를 배정한다. 싼 것(로컬) 먼저, 빈칸만 비싼 것(웹·Copilot).

### 8.3 증분 커서

소스마다 `raw_cursor.json` 에 `(pc_id, src)` 커서(마지막 관측 시각·파일 핸들·마지막 msg_key)를 둔다. 커서 이후만 읽는다. 스테이지 예산은 **커서 진전량**으로 감시한다(매번 전 기간 재스캔 금지).

### 8.4 rc 계약과 stage_result.json

- 수집기(개별 스크립트) 종료 코드: `0` 저장(신규 있음) · `1` 대상 없음/0건 · `2` 로그인 필요 · `3` 드라이버 불가/불완전 · `4` 읽었지만 신규 0. 오케스트레이터가 이를 §5 원장 상태와 §6 todo 로 번역한다.
- 각 스테이지는 `finally` 에서 `report\stage_result_<stage>.json` 을 원자적으로(tmp→replace) 쓴다:

```json
{"stage":"mail_local","state":"partial","items_total":820,"items_ok":790,
 "items_failed":0,"items_pending":30,"stop_kind":"budget","resumable":true,
 "reason":"R-BUDGET","hint":"다음 실행이 커서 이후 30일을 이어 읽음","caps_hit":false,
 "rc":2,"updated":"2026-09-02T01:30:00Z"}
```

- **collect 명령 rc**: 모든 스테이지가 성공(0)이면 **0**, 하나라도 부분(partial)이면 **2**, 치명 실패면 **1**. (수집기 rc 2 부분·3 불완전은 원장·todo 에 남는 한 collect rc 0/2 로 흡수; 완전 실패만 1.)
- 감시: 30초 하트비트(생존)와 커밋 수(진전)를 분리. stdout·하트비트 15분 무응답 = 정체, 진전 45분 정지 = 무진전 → kill_tree. 절대 상한 기본 꺼짐.
- '성공 전 무효화 금지', '빈 값 비덮어쓰기', 서명 기반 재개를 지킨다.

---

## 9. 진단 리포트

외부 반출 없이 **그 PC 화면에서** 끝난다. 원장·pc.json 을 읽어 렌더(별도 데이터 반출 금지). 창 제목·이름은 마스킹, '개발자에게 보내라' 문구 금지, 재설치 권유 금지.

- **PC 카드**: `pc.json` 의 탐침 숫자(지평선·색인 건수·UIA 줄 수 등)와 R-* 사유, 그 PC에서 할 수 있는 조치('이 날은 R-HORIZON → 백필 PC의 OWA가 채울 예정' 같은 문장).
- **출처 매트릭스**: 계정×날짜×종류 히트맵에 출처 색(COM/색인/OWA/Copilot). 셀 상태(ok/zero_ok/partial/out_of_horizon/blocked/transport_fail/not_attempted)를 색·배지로.
- **사유 분포**: 팀 단위로 R-* 분포를 세어 '되는 사람/안 되는 사람'을 숫자로 설명(이름 없이 가명 키). 구조적 결손('팀즈 지시 신호 0건')도 경고.

---

## 10. 시험 — 합성 페르소나 12종 E2E

수집기의 시험 주입점(`LM_OUTLOOK_SELFTEST`, `LM_INDEX_FAKE`, `LM_OWA_FAKE`, `LM_TEAMSWEB_FAKE`, `LM_COPILOT_STUB`, sampler `-TestSamples`, 가상 시계)으로 실데이터 없이 돌린다. 각 페르소나는 기대 원장 상태·todo·rc 를 assert.

| # | 페르소나 | 기대 결과(판정 기준) |
|---|---|---|
| 1 | 새 Outlook 전용 PC | mail.com/index 셀 `blocked:R-NEWOL`, todo→owa@백필PC, PC 수집은 정상 |
| 2 | COM 무한대기(프로필 0·구판 MSI) | New-Object 호출 안 함, `R-NOPROF`/`R-WIZARD`, 20초 내 skip, 전체 멈춤 없음 |
| 3 | 규칙 하위 폴더 정리(기본 폴더 밖 다수) | COM 재귀로 수집, index 교차검증 건수 일치, `subfolder_ratio` 기록, COM 누락 0 |
| 4 | 보관 사서함 사용 | 설정 켜면 archive store 포함, 끄면 `out_of_horizon`→owa todo |
| 5 | 색인 꺼짐(WSearch 중지) | index `blocked:R-NOIDX`, COM 있으면 COM 으로, 없으면 owa todo |
| 6 | 온라인 모드(색인 0) | index `blocked:R-ONLINE`, 지평선 기록, owa 백필 배정 |
| 7 | 웹 로그인 필요 | owa/teams.web rc 2, `R-LOGIN` 안내+폴링, 로그인 전 '불가' 확정 안 함 |
| 8 | date-only(어제 이전 날짜만) | n_date>0·n_minute=0, 시간 근거 기여 0, 분 사본 있으면 흡수 |
| 9 | Copilot 불가(무라이선스·커넥터 없음) | copilot `blocked:R-NOLIC/R-NOCONN`, 다른 날 2회 전엔 미확정, 탐침 바뀌면 해제 |
| 10 | UTC 클라우드PC | ts_utc·offset 정합, 병합 시 중복 2배 없음, `utc_suspect` 플래그, `R-TZ` 표기 |
| 11 | 멀티PC 재방문(PC1→PC2→PC1) | 세그먼트 덧붙임만, 같은 기계 두 루트 분열 없음, 커서 이후분 자연 합류 |
| 12 | 팀즈 창 숨김(최소화) | teams.uia `R-UIAEMPTY`, 그 날 blocked, teams.web 백필 todo, 0건을 '성공'으로 숨기지 않음 |

공통 판정(모든 페르소나): 원장 상태가 기대값과 일치, date-only 시간 기여 0, **PII 카나리아 0건**(세그먼트·프롬프트·팀 페이로드), 중복 병합 후 건수 보존, 상한 걸리면 반드시 `partial`/`cap_hit`, 제어문자 0, 설정 키 단일 레지스트리(죽은 키 금지), bat/ps1 인코딩.

---

## 11. 정제 계약(수집기 측 의무)

각 수집기는 원문을 메모리에서만 다루고, 레코드를 쓰기 직전 `lm27.privacy` 를 통과시킨다. PRIVACY.md 가 작성 중이면 인터페이스는 다음으로 가정한다:

```
sanitize_record(kind: str, record: dict) -> (record: dict | None, audit: dict)
```

- 반환이 `None` 이면 그 레코드는 **버린다**(광고·사적·자격증명 행). `audit` 의 유형별 건수만 `sanitize_audit.jsonl` 에 누적(원문·경로 미기록).
- 통과 레코드는 **열 허용 목록**(§3)만 포함한다. `subject_tokens`/`title_masked`/`attach_keys`/`counterpart_keys` 는 이미 PII·금액·이름·고객사가 치환·HMAC 된 값. 원 제목·주소·본문·헤더 원문은 레코드에 없다.
- **PowerShell 수집기는 레코드를 직접 디스크에 쓰지 않는다**. 원시 후보 레코드를 **NDJSON 으로 stdout** 에 한 줄씩 내보내고, 오케스트레이터가 그 스트림을 `python -m lm27.privacy.sanitize_stream --kind <kind> --src <src> --pc <pc_id> --out <seg.jsonl.gz>` 파이프로 받아 `sanitize_record` 를 줄마다 호출해 **통과분만** gzip 세그먼트에 쓴다(원문은 파이프에만 존재, 디스크에 안 남음). 파이썬 수집기는 `sanitize_record` 를 in-process 로 호출.
- `rules_ver` 를 레코드마다 기록. 클라우드PC 는 Copilot 전송 직전 같은 정제기로 프롬프트를 재검사(게이트, 별도 명세).

---

## 반환 요약

- 경로: `D:\배포\loadmon27\docs\COLLECTION.md`
- 공통 증거 레코드 1벌(JSONL)로 모든 수집기가 쓰고, `act` 는 수집 단계에서 항상 빈 값(화행은 정규화 단계).
- 저장 전 `lm27.privacy.sanitize_record` 를 통과한 열 허용 목록만 디스크로, 원문은 메모리/파이프에만.
- 능력 탐침 → 역할 분담 → 불변 세그먼트 → msg_key 병합 → 커버리지 원장 → 빈칸 계획기 → 진단, 전부 '첫 성공에서 멈추는 사슬' 대신 셀 단위 계획.
