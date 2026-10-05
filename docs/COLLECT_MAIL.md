# LM27 메일·일정 수집기 명세 (COLLECT_MAIL.md)

판: v1 · 대상 독자: 메일·일정 수집기 구현자 · 상위 규율(순서대로 우선):
`docs/COLLECTION.md`(수집 공통 계약 — 레코드 스키마·경로 ID·사유 코드·커버리지 상태),
`docs/_decisions.md`(오케스트레이터 결정 메모), `docs/PRIVACY.md`(정제 명세 — `lm27.privacy`),
`docs/COPILOT_BRIDGE.md`(코파일럿 브리지 5계층).

이 문서는 LM27 **메일·일정(kind=`mail`,`cal`)** 경로만 다룬다. 팀즈·PC 사용·파일·git·수동 기록은 별도 명세다.
구현자는 이 문서만으로 메일·일정 수집기·탐침 기여분·스크립트를 코드로 옮길 수 있어야 한다. 공통 계약과
어긋나는 서술이 있으면 `COLLECTION.md` 가 이긴다(§13 미결에 불일치를 모았다).

---

## 0. 경계·원칙 (어기면 안 됨 — 설계에 명시)

- **문서화·지원되는 사용자 인터페이스만** 쓴다. 메일·일정에서 쓰는 것: ① 클래식 Outlook COM(실행 중/기본
  프로필), ② Windows Search 색인(SystemIndex OLE DB), ③ **사용자 본인 전용 Edge 프로필**의 Outlook 웹을
  CDP(127.0.0.1)로 판독(백필 PC), ④ M365 Copilot Chat 왕복(클라우드PC, 존재 증인), ⑤ 사용자 반입 파일
  (EML·ICS·CSV).
- **설계에 넣지 않는 것(경계 금지, 명시)**: Microsoft Graph, OST/PST 직접 파싱, `.msg` 바이너리 직접 파싱,
  Teams/알림 앱 내부 캐시, 숨김 메일함 폴더(비 IPM 루트), 자격 증명 접근, 관리자 권한 요구, 보안 정책 우회.
  막혀서 안 되는 날은 §8 사유 코드로 커버리지 원장에 남길 뿐, 금지 경로로 우회하지 않는다.
- **원문은 메모리/파이프에서만** 다룬다. 디스크에는 `lm27.privacy.sanitize_record()` 를 통과한 **열 허용
  목록 레코드만** 쓴다(§4·§12). 원문 CSV·덤프·프롬프트·원문 응답 파일을 **절대 남기지 않는다**(LM24 의
  `data\outlook\mail.csv`·`replies\`·`mail_prompt_*.txt` 는 전부 폐기 — §11).
- 실명·계정·이메일·사내 코드네임을 코드·문서·샘플·프롬프트에 넣지 않는다(예시는 자리표시자 `과제A`·
  `고객사#1a2b`·`개인#3f9a`).
- **사용자를 대신해 로그인하지 않는다**. 웹 로그인은 사람이 1회. 비밀번호·토큰을 다루지 않는다.
- '첫 성공에서 멈추는 사슬'을 쓰지 않는다. **역할 분담 + msg_key 병합 + 셀 단위 커버리지 원장**(§2·§8).
- LM24 폴더(`D:\배포\loadmon24_v4`)는 **읽기 전용**. 코드는 '복사해 새 트리로 옮겨 다시 설계'만.

---

## 1. 경로 ID·스크립트·역할 (메일·일정)

| 경로 ID | kind | 수집기 스크립트 | 언어 | PC 역할 | 메커니즘 |
|---|---|---|---|---|---|
| `mail.com` | mail | `Get-OutlookCom.ps1 -Only mail` | PS 5.1 | 모든 PC(되면) | COM, 모든 메일 폴더 재귀, DASL UTC 필터, GetTable |
| `cal.com` | cal | `Get-OutlookCom.ps1 -Only cal` | PS 5.1 | 모든 PC(되면) | COM 기본 일정, `IncludeRecurrences`, 응답·주최·참석 |
| `mail.index` | mail | `Get-OutlookIndex.ps1 -Only mail` | PS 5.1 | 모든 PC(항상, 교차검증) | `Search.CollatorDSO` OLE DB, `System.Kind='email'` |
| `cal.index` | cal | `Get-OutlookIndex.ps1 -Only cal` | PS 5.1 | 모든 PC(항상) | SystemIndex `System.Kind='calendar'`(반복 미전개) |
| `mail.owa` | mail | `Get-OutlookWeb.py --kind mail` | PY | 백필 PC만 | 본인 Edge 프로필 CDP, 원장 **빈 셀만** |
| `cal.owa` | cal | `Get-OutlookWeb.py --kind cal` | PY | 백필 PC만 | OWA 주 보기(회차 전개), **기간 전체** |
| `mail.copilot` | mail | `Get-MailViaCopilot.py` | PY | 클라우드PC만 | Copilot Chat 존재·건수 증인(시간 근거 아님) |
| `mail.import` | mail | `Import-MailCal.py --kind mail` | PY | 모든 PC | 반입 폴더 EML·CSV(정식 대체) |
| `cal.import` | cal | `Import-MailCal.py --kind cal` | PY | 모든 PC | 반입 폴더 ICS·CSV |

- COM 은 attach 비용·마법사 위험 때문에 **단일 attach 당 하나의 kind**만 읽는 게 아니라, 한 번 attach 해
  메일·일정을 모두 읽는 `-Only`(기본 둘 다)·`-Only mail`·`-Only cal` 세 모드를 둔다. 오케스트레이터는 기본적으로
  `-Only`(둘 다) 한 번만 호출하고, kind 분리는 수집기가 stdout 에 **줄마다 `kind` 를 붙여** 흘리면 정제 파이프가
  kind 별 세그먼트로 라우팅한다(§4.4).
- `mail.com`/`cal.com`/`mail.index`/`cal.index` 는 PowerShell 이라 **디스크에 직접 쓰지 않는다**. 후보 레코드를
  **NDJSON 으로 stdout** 에 한 줄씩 내보내고 정제 파이프가 받는다(§4·§12). 파이썬 수집기는 `sanitize_record()`
  를 in-process 로 호출한다.

---

## 2. 역할 분담과 일자 셀 우선순위 (사용자 "로컬 색인 우선, 그다음 코파일럿")

메일·일정은 **로컬 우선**이되 '사슬'이 아니라 **셀(계정×날짜×종류) 단위 계획**이다.

1. **색인(mail.index/cal.index)**: Outlook 을 띄우지 않아 싸고 안전 → **항상 실행**(교차검증). COM 이 되는 PC
   에서는 일자별 건수를 COM 과 대조해 COM 누락(하위 폴더·프로필 오접속·0건)을 잡고, COM 불가 PC 에서는
   메일의 주 원천.
2. **COM(mail.com/cal.com)**: 되면 **분 단위 정밀 원장**. 모든 메일 폴더 재귀, 반복 회의 전개, 응답 상태,
   보호 열(주소·수신자). 범위 = `min(요청 기간, 지평선)`.
3. **OWA(mail.owa/cal.owa)**: **백필 PC(기본 클라우드PC)에서만**. 일정은 **기간 전체**(색인이 못 하는 반복
   회의 보완), 메일은 **원장의 빈 셀**(지평선 밖·blocked 일자)만. date-only 행은 존재·건수 증거.
4. **Copilot(mail.copilot)**: **클라우드PC에서만**, 위 1~3 뒤에도 비어 있는 일자의 **건수·스레드 존재만**.
   시간 근거로 승격하지 않는다(`ts_precision="summary"`).
5. **반입(mail.import/cal.import)**: 정식 대체 경로(원격 디버깅 정책이 막힌 PC·과거 사서함).

커버리지 원장(`COLLECTION.md §5`)의 빈 셀은 §6 계획기가 사유별로 다음 출처를 배정한다. 싼 것(색인·COM)
먼저, **빈칸만** 비싼 것(OWA·Copilot).

병합: §7 `msg_key`/`cal_key` 로 union, date-only 흡수. 세그먼트는 불변 → 병합은 읽기 시 파생.

---

## 3. 후보 레코드(메모리) 스키마 — 수집기가 정제기에 넘기는 원시 입력

수집기는 **원문을 메모리/stdout 파이프에서만** 다루고, 아래 '원시 후보 레코드' 한 벌을 `sanitize_record()`
(또는 정제 스트림)에 넘긴다. 저장되는 **열 허용 목록 레코드**는 `COLLECTION.md §3`(공통) + `PRIVACY.md §10.2`
(mail/cal)가 정한다. 수집기는 **저장 열을 만들지 않는다** — 원시 필드만 채우고 HMAC·가명화·마스킹·분류는
전부 `lm27.privacy` 가 한다.

### 3.1 mail 원시 후보 레코드(NDJSON 한 줄)

| 필드 | 형 | 필수 | 설명 / 어느 경로가 채우나 |
|---|---|---|---|
| `kind` | str | ✔ | `"mail"` (stdout 라우팅용 — §4.4) |
| `src` | str | ✔ | 경로 ID(`mail.com` 등) |
| `ts_utc` | str | ✔ | ISO 8601 UTC. COM 은 UTC proptag(§5.5), 색인은 OLE DB UTC, OWA/Copilot 은 화면 해석값 |
| `ts_local_offset` | str | ✔ | 관측 당시 로컬 오프셋(`+09:00`). §5.5(ctypes `GetDynamicTimeZoneInformation`) |
| `ts_precision` | str | ✔ | `minute`(COM·색인·OWA 시각 해석) / `date`(OWA 날짜만) / `summary`(Copilot) |
| `box` | str | ✔ | `inbox` / `sent` / `other`. **폴더 역할**로 판정(이름 아님 — §5.3) |
| `folder_path` | str | ○ | 폴더 경로 원문(**파이프에만**; 정제기가 `folder_class` 로 환원 후 폐기) |
| `folder_role_hint` | str | ○ | COM EntryID 대조 결과(`inbox`/`sent`/`archive`/`deleted`/`junk`/`subfolder`) |
| `internet_message_id` | str | ○ | Internet Message-ID 원문(정제기가 `msg_key` HMAC). 없으면 퍼지 키(§7.2) |
| `conversation_id` | str | ○ | `ConversationID`/`ConversationIndex` 원문 → `conv_key`/`thread_key` HMAC |
| `conversation_topic` | str | ○ | 대화 제목 원문(RE/FW 제거 정규화 후 해시 보조) |
| `sender_addr` | str | ○ | 발신 SMTP(보호 열 — B단, §5.4). → `sender_key`·`sender_label` |
| `sender_name` | str | ○ | 발신 표시 이름(보호 열). 정제기가 이름 가명화 |
| `my_addrs` | list[str] | ✔ | 내 주소·이름 후보(§5.6). rcv·발신 판정용. 못 구하면 `[]`(→ `R-NOADDR`) |
| `to` | list[obj] | ○ | `[{addr,name}]`(보호 열). → `n_to`·`peer_keys`·`rcv` |
| `cc` | list[obj] | ○ | `[{addr,name}]`(보호 열). → `n_cc`·`rcv` |
| `subject` | str | ○ | 제목 원문. → `subject_masked`(≤120) |
| `refw_depth` | int | ○ | 제목 앞 `RE/FW/FWD/답장/전달/회신` 접두 개수(§9 화행 단서) |
| `attach_names` | list[str] | ○ | 첨부 파일명 원문(≤10). → `attach_names_masked[]`·`attach_keys`(HMAC) |
| `has_attach` | bool | ○ | 첨부 유무 |
| `sensitivity` | int | ○ | `0`보통 `1`개인 `2`비공개 `3`기밀(공사 구분 §12) |
| `categories` | list[str] | ○ | Outlook 범주 원문(개인 범주 판정) |
| `importance` | int | ○ | `0/1/2` |
| `in_reply_to` | bool | ○ | 회신 여부(헤더 `In-Reply-To`/`ConversationIndex` 깊이>0) |
| `headers_text` | str | ○ | **COM·EML 만.** `PR_TRANSPORT_MESSAGE_HEADERS`(§10). 정제기가 bool 4종 추출 후 **즉시 폐기** |
| `body_text` | str | ○ | **선택.** 끝 4,000자 + 앞 1,000자만 메모리로(본문 수신거부 문구·화행·부재 힌트용, 저장 안 함) |
| `focused_other` | bool\|null | ○ | Focused Inbox '기타' 여부(읽히는 경로만; 아니면 `null`) |
| `meeting_response` | bool | ○ | 회의 수락·거절 **발신** 여부(Class≠43 라도 **버리지 않고** 능동 신호로 라벨) |

- 저장 레코드로 환원될 때 `act`(화행)는 **항상 빈 문자열** — 수집기는 화행을 판정하지 않는다(정규화 단계가
  `refw_depth`·`rcv`·`subject_masked`·`meeting_response` 등으로 채운다, `COLLECTION.md §3.1`).
- `direction`: 보낸편지함 또는 발신자=나 → `out`, 그 외 수신 → `in`, 미확정 → `unknown`.

### 3.2 cal 원시 후보 레코드(NDJSON 한 줄)

| 필드 | 형 | 필수 | 설명 |
|---|---|---|---|
| `kind` | str | ✔ | `"cal"` |
| `src` | str | ✔ | `cal.com` 등 |
| `ts_utc` | str | ✔ | 시작 UTC |
| `ts_end_utc` | str | ✔ | 끝 UTC(구간성 — `COLLECTION.md §3.1 ts_end`) |
| `ts_local_offset` | str | ✔ | 오프셋 |
| `ts_precision` | str | ✔ | `minute`(COM·OWA) / `date`(OWA 종일·날짜만) / `summary`(Copilot) |
| `global_appointment_id` | str | ○ | `GlobalAppointmentID` 원문 → `cal_key` HMAC. 없으면 `(시작·끝 UTC, 제목 해시)` |
| `subject` | str | ○ | 제목 원문 → `subject_masked`(사적이면 `""`) |
| `all_day` | bool | ○ | 종일 여부 |
| `busy` | str | ○ | `free`/`tentative`/`busy`/`oof`/`elsewhere`(`BusyStatus` 환원) |
| `sensitivity` | int | ○ | 공사 구분 |
| `categories` | list[str] | ○ | 범주 |
| `organizer_is_me` | bool | ○ | 내가 주최자인가 |
| `organizer` | obj | ○ | `{addr,name}`(보호 열) → 주최자 가명 키 |
| `attendees` | list[obj] | ○ | `[{addr,name}]`(보호 열) → `peer_keys`·`n_attendees` |
| `n_attendees` | int | ○ | 참석 인원 수 |
| `response` | str | ○ | `organizer`/`accepted`/`tentative`/`declined`/`none`(ResponseStatus 환원) |
| `meeting_status` | int | ○ | `MeetingStatus`(5·7=취소) → `flags.meeting_status` |
| `location_raw` | str | ○ | 장소 원문(**파이프에만**; 정제기가 `location_class`=online·room·external·none 로 환원 후 폐기) |
| `online_meeting` | bool | ○ | 온라인 회의(Teams/Zoom 링크 또는 `IsOnlineMeeting`) |
| `recurring` | bool | ○ | 반복 여부 |
| `recurrence_incomplete` | bool | ○ | **색인 경로 전용** — 반복 마스터만 보고 회차 미전개(`flags.recurrence_incomplete=true`) |

### 3.3 정제 통과 저장 레코드 (참고 — PRIVACY.md 가 생성)

- mail 저장 열: `msg_key`·`conv_key`·`box`·`folder_class`·`sender_key`·`sender_label`·`peer_keys[]`·`n_to`·
  `n_cc`·`rcv`·`subject_masked`·`attach_names_masked[]`·`sensitivity`·`cat_private`·`has_attach`·`is_reply`·
  `ad_score`·`ad_band`·`ad_why[]`·`ad_partial`·`priv_class`·`replied`·`i_sent_in_conv` + 공통 열.
- cal 저장 열: `cal_key`·`start_utc`·`end_utc`·`all_day`·`busy`·`sensitivity`·`cat_private`·`subject_masked`·
  `n_attendees`·`organizer_is_me`·`response`·`location_class`·`recurring`·`abs_hint`·`priv_class` + 공통 열.
- `ad_band=="drop"` 메일은 **저장하지 않는다**(광고 — 건수만 감사). `priv_class∈{private,social}` 행은 텍스트
  열을 비우고 메타만 남긴다(공사 구분 — §12). COLLECTION.md 공통 열 이름(`subject_tokens`·`counterpart_keys`·
  `thread_key`)과 PRIVACY.md 열 이름(`subject_masked`·`peer_keys`·`conv_key`)의 불일치는 §13 미결.

---

## 4. 저장 배치·정제 파이프·세그먼트

### 4.1 상주/번들 배치 (COLLECTION.md §0 그대로)

- 로컬 1차 적재: `%LOCALAPPDATA%\LoadMonitor27\agent\<install_id>\store\<pc_id>\evidence\mail\<src>\*.jsonl.gz`,
  `evidence\cal\<src>\*.jsonl.gz`. 커서는 같은 store 의 `raw_cursor.json`.
- 운반 번들: `D:\배포\loadmon27\data\bundle\pcs\<pc_id>\seg\<seq>_<from_utc>_<to_utc>.jsonl.gz`(불변, 덧붙이기만).
- 정제 감사: `data\pcs\<pc_id>\audit\privacy_YYYYMM.jsonl`(건수·규칙 버전·해시만).

### 4.2 증분 커서(`raw_cursor.json`)

`(pc_id, src)` 별로 둔다. 커서 이후만 읽는다(매번 전 기간 재스캔 금지).

| 경로 | 커서 내용 |
|---|---|
| `mail.com` | `{box: {last_ts_utc, last_msg_key}, cov_months: {"yyyy-MM": {status, read_from, read_to}}}` (LM24 `coverage.json` v2 개념을 승격 — §11) |
| `cal.com` | `{last_start_utc, cov_months}` |
| `mail.index`·`cal.index` | `{last_item_ts_utc}` (색인은 싸므로 겹침 재조회 허용, 병합이 중복 제거) |
| `mail.owa`·`cal.owa` | `{assigned_todo_ids[], done_ranges[]}` |
| `mail.copilot` | `{witnessed_days[]}` |

### 4.3 rc·사유·stage_result (COLLECTION.md §8.4 그대로)

수집기 종료 코드: `0` 저장(신규 있음) · `1` 대상 없음/0건 · `2` 로그인 필요 · `3` 드라이버 불가/불완전 ·
`4` 읽었지만 신규 0. 각 스크립트가 `finally` 에서 `report\stage_result_<stage>.json` 을 원자적으로 쓴다.

### 4.4 정제 파이프 (PowerShell 수집기)

PowerShell 수집기는 **직접 디스크에 쓰지 않는다**. stdout 에 NDJSON 후보 레코드를 흘리고, 오케스트레이터가
받아 `lm27.privacy` 로 통과분만 gzip 세그먼트에 쓴다. 원문은 파이프에만 존재한다.

- **kind 단일 스테이지**(`-Only mail` 또는 `-Only cal`):
  `Get-OutlookCom.ps1 -Only mail ... | python -m lm27.privacy.sanitize_stream --kind mail --src mail.com --pc <pc_id> --out <seg.jsonl.gz>`
  (`COLLECTION.md §11` 의 호출 그대로). `sanitize_stream` 은 줄마다 `sanitize_record("mail", raw, rc)` 를 호출,
  **EOF 에서** 세그먼트 1개를 임시 파일로 쓰고 `os.replace`. stdout 에 **요약 1줄만**
  `{"ok":true,"rows_in":812,"stored":640,"dropped":{"ad":160,"cred":2},"errors":{},"rules_ver":"2026.10.0","kid":"k1a2b3c4d"}`.
- **혼합 스테이지**(COM 1회 attach 로 메일·일정 동시): `Get-OutlookCom.ps1 -Only ...` 는 줄마다 `kind`
  필드를 붙여 흘리고, 정제 스트림을 **kind 라우팅 모드**(`--route-by-kind --src-map mail=mail.com,cal=cal.com
  --seg-dir <pcs\pc_id\seg>`)로 받아 kind 별 세그먼트 2개로 나눈다. 이 모드는 `sanitize_stream` 에 추가하되
  단일 `--kind` 계약을 유지한다(§13 미결로 계약 소유자 승인). **구현 기본값은 안전한 kind 단일 스테이지**
  (COM 을 `-Only mail`·`-Only cal` 로 두 번 호출; 두 번째 attach 는 `GetActiveObject` 재사용이라 쌈).
- 파이썬 수집기(`Get-OutlookWeb.py` 등)는 `from lm27.privacy import sanitize_record`/`SegmentWriter` 로
  in-process 정제·적재(파이프 없음). 정제 결과만 세그먼트에 쓴다.

---

## 5. `Get-OutlookCom.ps1` — mail.com + cal.com (클래식 Outlook COM)

**파일**: `collect\Get-OutlookCom.ps1` (PS 5.1, UTF-8 BOM + CRLF). LM24 `Get-OutlookData.ps1` 이식·개조(§11.1).

### 5.1 인자

| 인자 | 기본 | 뜻 |
|---|---|---|
| `-Only` | `''`(둘 다) | `mail`/`cal`/빈값. kind 단일 스테이지면 하나 지정 |
| `-Since` `-Until` | 설정 기간 | 로컬 `yyyy-MM-dd`. 내부에서 UTC·달 경계로 변환 |
| `-Pc` | (필수) | pc_id(HMAC 결과; 레코드 `pc_id` 그대로 통과) |
| `-ReadProtected` | `0` | `1` 이면 B단(주소·수신자) 읽기 허용. **오케스트레이터가 탐침 OMG 통과 PC 에서만 1** |
| `-CursorFile` | agent store | `raw_cursor.json` 경로 |
| `-BudgetSec` | 설정 | COM 전체 시간 예산(메일·일정 공유; 일정은 절반까지) |
| `-WatchdogSec` | `20` | 자식 COM 프로세스 워치독(COLLECTION.md §4.3) |
| `-SelfTest` | `0` | `LM_OUTLOOK_SELFTEST=N` — 가짜 메일·일정 N건(§14) |

### 5.2 워치독·대화상자 방어 (반드시)

- **모든 COM 호출은 자식 프로세스 + 20초 워치독**에서. 부모는 자식 PID 를 먼저 받아 두고, `-WatchdogSec`
  무진전이면 `Stop-Process -Id <pid> -Force`(PS5.1 `Stop-Job` 은 막힌 COM 을 기다리므로 금지). 부모는 자식
  stdout(NDJSON)을 그대로 자기 stdout 으로 통과시키고, 진행(레코드 수)과 생존(하트비트)을 분리 감시한다.
- attach 순서(LM24 `Get-OutlookData.ps1:567-601` 이식):
  1. `[Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')` 를 **먼저**(3회, 2초 간격).
     바쁜 순간 `RPC_E_CALL_REJECTED(8001010A)` 는 영구 실패 아님 → 짧게 재시도.
  2. **Outlook 이 실행 중인데(`Get-Process outlook`) 붙지 못하면 = 대화상자(시작 마법사·프로필 선택·암호·
     복구)에 막힘** → `New-Object` 를 **절대 호출하지 않는다**. 창 제목(마스킹)만 사유에 담고 `R-DIALOG` 로 skip.
  3. 떠 있지 않을 때만, **프로필이 1개 이상**일 때만 `New-Object -ComObject Outlook.Application`. 프로필 0 →
     마법사 무한 대기 위험 → `R-NOPROF`/`R-WIZARD` 로 건드리지 않고 skip(LM24 `:318-346`).
  4. `GetNamespace('MAPI').Logon($null,$null,$false,$false)`(`ShowDialog=false`).
- 새 Outlook(olk.exe·`UseNewOutlook=1`)은 COM 미제공 → `R-NEWOL`(경고만 하던 LM24 를 바꿔 **셀을 blocked**로).
- **HRESULT 코드로만** 분기(예외 메시지 단어 매칭 금지). `80040154/REGDB_E_CLASSNOTREG`=미등록,
  `8001010A/RPC_E_CALL_REJECTED`=대화상자, `80010001`=서버 거부. **재설치 권유 문구 금지**(LM24 `:740-757`).
- 현재 프로세스 권한 상승 ↔ Outlook 일반 권한 불일치면 `GetActiveObject` 실패를 '대화상자'로 오진하지 말고
  탐침의 `elevated` 로 `R-ELEV`.

### 5.3 메일 폴더 재귀 + 역할 태그 (LM24 최상위-만-읽기 결함 수정)

- **기본 저장소의 모든 메일 폴더를 재귀**로 훑는다(하위 폴더·규칙 폴더 포함). 설정 `mail.includeArchiveStore=true`
  면 **보관 사서함(2차 저장소)**도 포함.
- 폴더 역할은 **이름이 아니라 기본 폴더 EntryID 대조**로 판정(현지화·UI 언어 무관):
  - `inbox`=`GetDefaultFolder(6)`, `sent`=`(5)`, `calendar`=`(9)`, `deleted`=`(3)`, `junk`=`(23)`,
    `drafts`=`(16)`, `outbox`=`(4)`. 각 폴더의 `EntryID`+`StoreID` 를 이 기준과 비교.
  - **수집 제외**: deleted(3)·junk(23)·drafts(16)·outbox(4)·동기화 문제·대화 기록·RSS. `folder_role_hint` 에
    `inbox`/`sent`/`archive`(보관 저장소)/`subfolder`(기본 폴더 밖) 를 담는다.
  - `box`: sent 계열 EntryID 아래면 `sent`, 그 외 수신 폴더면 `inbox`. **발신 판정은 폴더뿐 아니라
    발신자=나(§5.6)도** 본다(IMAP·규칙 사본 대응).
  - `folder_class`(저장 열)는 정제기가 `folder_path`·`folder_role_hint` 로 환원.
- **기본 폴더 밖 비중**(`subfolder_ratio`)을 탐침·stage_result 에 기록. 임계 초과면 `R-SUBFOLDER`(색인 교차검증 강화).

### 5.4 비보호 열(A단) / 보호 열(B단) 분리 (OMG 방어)

LM24 는 수신자 접근 실패 시 `rcv='to'` 로 **오판정**했다(`:488`). LM27 은 통째로 버리지 않고 **B단 실패를
사유로** 남기고 `rcv='unknown'` 으로 둔다.

- **A단(항상 읽음, 비보호)**: `Subject`·`ReceivedTime`/`SentOn`(및 UTC proptag §5.5)·`ConversationTopic`·
  `ConversationID`·`Size`·`MessageClass`·`Categories`·`Sensitivity`·`Importance`·`GlobalAppointmentID`(cal).
  **`Folder.GetTable($dasl)` + `Table.Columns.Add(...)`** 로 지정 열만 빠르게 읽는다(항목당 왕복 제거).
- **B단(보호 — Object Model Guard 경고 가능)**: 발신 SMTP(`PropertyAccessor` `0x5D01001F`), 수신자
  `Recipients`·`To`/`CC`, 본문 `Body`, `PR_TRANSPORT_MESSAGE_HEADERS`(`0x007D001F`), `CurrentUser`.
  - **`-ReadProtected 1`(탐침이 OMG 통과 확인) PC 에서만** 읽는다. 각 항목 읽기에 2초 제한, 경고·거부면
    그 항목만 `R-OMG` 로 표시하고 **A단 행은 그대로 저장**(행 폐기 금지).
  - `-ReadProtected 0` PC: B단 전부 생략 → `rcv='unknown'`, `sender_addr=''`, `headers_text=''`(광고 판정은
    제목·도메인·광고어만 → `ad_partial=true`, PRIVACY §11.1).

### 5.5 로캘 무관 날짜 필터·UTC·정밀도 (LM24 'g' 로캘 결함 수정)

- LM24 `Restrict("[Start] < 'g로캘날짜'")`(`:378,445`)는 로캘 불일치 시 0건. LM27 은 **DASL `@SQL` + ISO 리터럴**:
  - 메일: `@SQL="urn:schemas:httpmail:datereceived" >= '2026-09-01T00:00:00Z' AND ... < '2026-10-01T00:00:00Z'`
    (DASL 날짜는 UTC 로 해석 — 로캘 무관). 발신은 `urn:schemas:httpmail:datesent`.
  - 일정: 겹침 필터 `"urn:schemas:calendar:dtstart" < '<end>' AND "urn:schemas:calendar:dtend" >= '<start>'`.
  - `Folder.GetTable($dasl)` 로 필터·열을 함께 지정(속도). 반복 회의는 GetTable 로 전개 안 되므로 일정만
    `Items.IncludeRecurrences=$true; Items.Sort('[Start]'); Items.Restrict($dasl)` 경로를 쓴다(§5.7).
- **UTC 저장**: `ReceivedTime`/`SentOn` 은 로컬 Kind → 신뢰하지 말고 **UTC proptag**을 PropertyAccessor(A단
  수준)로 읽는다: 수신 `PR_MESSAGE_DELIVERY_TIME 0x0E060040`, 발신 `PR_CLIENT_SUBMIT_TIME 0x00390040`,
  일정 시작 `0x820D0040`(dtstart, UTC)·끝 `0x820E0040`. 못 읽으면 로컬값 + `ts_local_offset` 로 환산하고
  `flags.utc_suspect` 가능성 기록.
- `ts_local_offset`: ctypes `GetDynamicTimeZoneInformation`(결정 메모 §10.3 — `zoneinfo.ZoneInfo` **금지**). PS
  에서는 `[System.TimeZoneInfo]::Local.GetUtcOffset($ts)` 를 분으로.
- COM 시각은 항상 `ts_precision="minute"`.

### 5.6 내 주소·발신 판정·rcv (LM24 `:614-626`, `:458-491` 이식)

- `my_addrs` 수집: `Namespace.Accounts[].SmtpAddress` → `CurrentUser.Name` → `CurrentUser.Address` →
  `CurrentUser.AddressEntry.GetExchangeUser().PrimarySmtpAddress` → `config.owner`. 소문자·2자 이상·유일.
  못 구하면 `[]` → `R-NOADDR`(rcv=unknown, bulk 로 버리지 않음). 다른 PC COM 이 확정한 주소 해시를 번들로
  공유해 재판정 가능(§13 미결).
- `rcv`(수신 구분, 저장 열): To 표시 문자열에 내가 있으면 `to`, CC 면 `cc`, 둘 다 없으면 `bulk`, 내 주소
  모름 `unknown`, 보낸 메일 `na`. 표시 문자열로 못 찾고 수신자 ≤12명이면 `Recipients` 의 `0x39FE001E`
  (PR_SMTP_ADDRESS)로 정밀 확인(B단). **수신자 열람 실패 시 `to` 로 올리지 않고 `unknown`**.

### 5.7 일정 (cal.com) — LM24 `:372-399` 이식

- `GetDefaultFolder(9)`, `Items.IncludeRecurrences=$true`, `Items.Sort('[Start]')`(오름차순 — COM 규칙; 내림차순이면
  회차 전개 깨짐), 겹침 `Restrict`(§5.5 DASL). 예산 절반·상한 8,000(깨진 반복 가드)에서 `R-CAP`/`R-BUDGET`.
- 읽는 값: 시작·끝(UTC proptag) · `AllDayEvent` · `BusyStatus`→`busy` · `Subject` · `Categories` · `Sensitivity` ·
  `GlobalAppointmentID` · `ResponseStatus`(0 없음/1 주최/2 미정/3 수락/4 거절/5 미응답)→`response` ·
  `MeetingStatus`(5·7 취소) · `Location`(→`location_class`) · `IsOnlineMeeting`/링크→`online_meeting` · 주최자·참석자(B단).
- **회의 요청·응답 발신(수락·거절)**: LM24 는 `Class≠43` 로 버렸다 → LM27 은 메일 쪽에서 `meeting_response=true`
  능동 신호로 **남긴다**(발신 보고/조율 근거).

### 5.8 예산·증분·커버리지

- 달 단위·최신 달부터, 예산 닿으면 '여기까지' 경계를 커서에 남겨 다음 실행이 잇는다(LM24 `coverage.json` v2
  개념 → `raw_cursor.json.cov_months` + 커버리지 원장 셀로 승격 — §4.2). **파일 통째 덮어쓰기·다른 경로가
  쓰면 coverage 삭제** 동작은 **폐기**(세그먼트 불변 — §11).
- 지평선 밖 달(캐시 동기화 기간 밖·보존 이동)은 '0건'이 아니라 커버리지 셀 `out_of_horizon`(+`R-HORIZON`) →
  §6 계획기가 OWA 백필 배정. 온라인 모드로 로컬 캐시 0 → `R-ONLINE`. 최신 수신이 now−임계보다 과거 → `R-STALE`.

### 5.9 rc·사유(mail.com/cal.com)

| 상황 | rc | 사유·stage_result |
|---|---|---|
| 신규 레코드 있음 | 0 | `state=ok`(예산 닿으면 `partial`+`R-BUDGET`) |
| attach OK·기간 내 0건 | 1 | `zero_ok` 후보(교차검증 뒤 확정) |
| attach OK·커서 이후 신규 0 | 4 | `state=done`, 신규 없음 |
| 새 Outlook 전용 | 3 | `R-NEWOL`, 셀 `blocked` |
| 프로필 0·구판 마법사 | 3 | `R-NOPROF`/`R-WIZARD` |
| 대화상자에 막힘 | 3 | `R-DIALOG`(창 제목 마스킹) |
| 제한 언어 모드 | 3 | `R-CLM`(OleDb·COM 형식 불가) |
| 상한 8000·20000 절단 | 0 | `partial`+`cap_hit`+`R-CAP` |
| 드라이버·타임아웃 | 3 | `R-TRANSPORT`(**'불가' 아님** — §6) |

---

## 6. `Get-OutlookIndex.ps1` — mail.index + cal.index (Windows Search 색인)

**파일**: `collect\Get-OutlookIndex.ps1` (PS 5.1). LM24 `Get-OutlookIndex.ps1` 이식·개조(§11.2).

### 6.1 인자·메커니즘

- 인자: `-Only mail|cal`, `-Since -Until`, `-Pc`, `-CursorFile`, `-CapMail 20000`, `-CapCal 8000`,
  `-SelfTest`(`LM_INDEX_FAKE=<json>`).
- `New-Object System.Data.OleDb.OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")`
  → 실패 시 `R-NOIDX`(서비스 꺼짐·색인 비활성), exit 1. Outlook 을 **띄우지 않는다**(마법사 무한대기 없음).
- **Outlook 항목만**: `System.ItemUrl LIKE 'mapi%'`(디스크 `.msg/.eml/.ics` 제외 — LM24 290건 오염 방지).
  날짜 리터럴은 **UTC**(현지 자정을 UTC 로 변환해 넣는다 — LM24 `:183-186`).
- 폴더는 **경로 조각 단위 정확 일치** 제외(정크·삭제·임시보관·Drafts·보관·RSS·동기화 문제), '보낸 편지함/Sent'
  조각이면 `sent`(LM24 `:224-226`). **하위 폴더 포함**.
- 확장 속성(`System.Message.ToName/CcName`·`System.Calendar.IsRecurring`) 거부되면 기본 속성으로 재시도
  (LM24 `Run-Query` `:168-180`). 거부 시 `ad_partial`·`recurrence_incomplete` 표시.
- 내 주소: `whoami /upn` → `UserPrincipal` → AD(도메인 PC, 5초 타임아웃) → Outlook 프로필 레지스트리 →
  `config.owner` → `USERNAME`(약한 단서). 못 구하면 `R-NOADDR`, rcv=unknown(LM24 `:66-121`).

### 6.2 메일 SQL (이식, UTC·상한 기록)

```sql
SELECT System.ItemDate, System.Message.DateReceived, System.Message.DateSent, System.Message.FromName,
       System.Message.FromAddress, System.Message.ToAddress, System.Message.CcAddress, System.Subject,
       System.ItemFolderPathDisplay, System.ItemUrl, System.Message.ToName, System.Message.CcName
FROM SYSTEMINDEX
WHERE System.Kind = 'email' AND System.ItemUrl LIKE 'mapi%'
  AND System.ItemDate >= '<sinceUTC>' AND System.ItemDate < '<untilUTC>'
ORDER BY System.ItemDate DESC
```

- `box`: 폴더 조각으로 inbox/sent. 시각: sent 는 `DateSent`, 아니면 `DateReceived`, `ItemDate` 순(UTC).
- `conversation_topic`: 제목에서 `RE/FW/FWD/답장/전달/회신` 접두 제거. rcv: `ToAddress/CcAddress/ToName/CcName`
  에서 내 주소·이름(한 항목 단위 정규식 — 부분 문자열 오판 방지, LM24 `Is-Me` `:187-195`).
- **상한 20000(메일)·8000(일정)에 걸리면 조용히 자르지 말고 셀 `partial`+`cap_hit`+`R-CAP`**(LM24 는 조용히 잘림).
  최신순 정렬이라 옛 달이 잘림 → 원장에 반드시 남긴다.
- 색인은 발신 SMTP 도메인·헤더를 못 읽으므로 광고 판정 `ad_partial=true`(제목·광고어만). `headers_text=''`.

### 6.3 일정 SQL (반복 미전개)

```sql
SELECT System.StartDate, System.EndDate, System.Subject, System.Calendar.Location,
       System.Calendar.ShowTimeAs, System.ItemUrl, System.Calendar.IsRecurring
FROM SYSTEMINDEX
WHERE System.Kind = 'calendar' AND System.ItemUrl LIKE 'mapi%'
  AND System.EndDate >= '<sinceUTC>' AND System.StartDate < '<untilUTC>'
```

- **반복 마스터(`IsRecurring=true`)는 회차 미전개** → 레코드에 `recurrence_incomplete=true`, 그 수를
  stage_result 에 기록. 반복 전개가 필요한 셀은 `cal.owa` 로 배정(exit 3 로 '불완전' 신호 — LM24 `:313-316`).
  `response`·`meeting_status` 는 색인에 없어 빈값.

### 6.4 rc·사유

| 상황 | rc | 사유 |
|---|---|---|
| 신규 있음 | 0 | `ok` |
| 색인 연결 실패 | 1(또는 3) | `R-NOIDX` |
| Outlook 항목 0 | 1 | `R-ONLINE`(온라인 모드)·새 Outlook·`R-IDXPOLICY`(PreventIndexingOutlook) 구분 |
| 재구축 중 | 3 | `R-IDXPAUSED` |
| 저장했지만 일정 불완전 | 3 | `recurrence_incomplete` → cal.owa todo |
| 상한 절단 | 0 | `partial`+`R-CAP` |
| 제한 언어 모드 | 3 | `R-CLM` |

---

## 7. 병합 (COLLECTION.md §7 메일·일정 상세)

- 출처 신뢰 순위: **COM > 색인 > OWA(minute) > OWA(date) > Copilot**. 같은 키 레코드는 필드 단위로 가장 좋은
  값을 고르고 모든 출처를 `provenance` 에 남긴다(원 세그먼트 보존 — 읽기 시 파생).
- 메일 `msg_key`: `internet_message_id` HMAC 우선. 없으면 퍼지 키 `(box, UTC 분 ±2, thread_key, counterpart 집합)`.
- 일정 `cal_key`: `global_appointment_id` HMAC + 시작 UTC. 없으면 `(시작·끝 UTC, 제목 해시)`.
- **중복 제거 키는 정제 '전' 원문으로 HMAC**(PC마다 정제 결과가 달라도 같은 메시지 2중 계수 금지 — PRIVACY §9).
- date-only 흡수: 같은 `(date, box, thread_key)` 에 분 단위 사본이 있으면 date-only 레코드는 병합에서 버린다.
- 시간대 UTC 정규화 후 비교(Copilot·클라우드PC UTC 어긋남 방지, `flags.utc_suspect`).

---

## 8. 커버리지 원장·사유 코드 (메일·일정 축)

- 셀 `kind_axis ∈ {mail_in, mail_out, cal}`(mail 수신/발신 분리). 상태 `ok/zero_ok/partial/out_of_horizon/
  blocked/transport_fail/not_attempted`(COLLECTION.md §5).
- **일자 합성 상태 = 출처 중 최선 값.** 색인 건수가 COM 의 `ledger.mismatchRatio`(기본 1.3)배를 넘으면
  'COM 누락 의심'(하위 폴더·프로필 오접속) 사유를 붙인다.
- **미관측 ≠ 0h**: `not_attempted`/`blocked`/`transport_fail`/`out_of_horizon` 는 '근거 없음'으로, `zero_ok`(읽었고
  0건)와 구분. 시간 모델이 이 구분을 입력으로 받는다.
- date-only·Copilot summary 는 존재·건수 증거일 뿐 시간 근거로 승격 금지.
- 메일·일정 관련 사유 코드(COLLECTION.md §4.2에서 발췌): `R-NEWOL R-NOPROF R-WIZARD R-DIALOG R-CLM R-OMG
  R-ELEV R-ONLINE R-HORIZON R-SUBFOLDER R-STALE R-NOIDX R-IDXPOLICY R-IDXPAUSED R-EDGEPOL R-LOGIN R-CA
  R-NOLIC R-NOCONN R-TZ R-OFFICE R-NOADDR R-CAP R-BUDGET R-TRANSPORT`.
- **'불가' 확정**: 서로 다른 날 2회 이상 같은 사유 + `R-TRANSPORT` 아님(COLLECTION.md §6). 탐침 값이 바뀌면
  (클래식 Outlook 실행·로그인 완료·Edge 정책 변경) 자동 해제.

---

## 9. 화행(speech-act) 단서 추출용 필드 (수집기가 raw 로 제공, 판정은 정규화 단계)

수집기는 화행(지시/수락/보고)을 **판정하지 않는다**(`act=""`). 아래 단서만 raw 로 제공한다.

| 단서 | 원시 필드 | 메모 |
|---|---|---|
| 제목 토큰 | `subject` → 정제 후 `subject_masked` → 정규화가 토큰화 | PII·금액·이름·고객사 치환 후 |
| RE/FW 깊이 | `refw_depth`(int) | 제목 앞 `RE/FW/FWD/답장/전달/회신` 접두 개수(스레드 깊이·보고/회신 신호) |
| 첨부명 키 | `attach_names` → `attach_keys`(HMAC) | '문서 작성 완료 → 메일 보고' 연결(파일 `doc_key` ↔ 메일 `attach_keys`) |
| 수신자 수 | `n_to`·`n_cc`(from `to`/`cc`) | bulk 판정·조율형 분별 |
| 나에게 직접/CC | `rcv ∈ {to,cc,bulk,unknown,na}` | S1i(받은 의뢰) vs 대량 공지 분별 |
| 회의 응답 발신 | `meeting_response` | 능동 산출 신호(E1o 조율형) |
| 방향 | `direction ∈ {in,out,unknown}` | S1o(내가 보낸 지시)·E1o(내가 보낸 보고) 축(결정 메모 §10.2) |
| 본문 단서 | `body_text`(메모리만) → 정제가 `act`,`act_score`,`abs_hint` | 본문 저장 안 함(PRIVACY §10.2) |

---

## 10. 광고 판정 헤더 단서 (COM 으로 얻는 것만)

- `headers_text` = `PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x007D001F")`
  (PR_TRANSPORT_MESSAGE_HEADERS, B단). 정제기가 메모리에서 **bool 4종만** 추출하고 **헤더 원문 즉시 폐기**:
  `list_unsub`(`^List-Unsubscribe:`), `precedence_bulk`(`^Precedence:\s*(bulk|list|junk)`), `esp`(대량 발송 서비스
  헤더군 — PRIVACY §11.1 `HDR_ESP`). 본문 수신거부 문구는 `body_text` 에서 `body_unsub`.
- 발신 SMTP 도메인: `PR_SENDER_SMTP_ADDRESS 0x5D01001F`, Exchange 발신자는
  `Sender.GetExchangeUser().PrimarySmtpAddress`(B단). 로컬파트는 HMAC, 도메인만 `sender_label` 로.
- 점수·임계·감점은 **수집기가 하지 않는다** — `lm27.privacy.classify.ad_score()`(PRIVACY §11)가 계산. 수집기는
  raw(`headers_text`·`sender_addr`·`subject`·`folder_role_hint`·`rcv`·`to`/`cc`·`focused_other`·`body_text`)만 채운다.
- **헤더를 못 읽는 경로**(색인·OWA·Copilot·새 Outlook): `ad_partial=true` 로 표시, 제목 `(광고)` 표기·도메인·
  광고어만으로 같은 임계 판정(보고서에 경로별 `ad_partial` 비율).
- 왕래 도메인 집합을 만들려면 **보낸 편지함을 먼저** 처리(PRIVACY §11.3 냉시작 오탐 방지) → mail.com/mail.index
  는 sent 를 inbox 보다 먼저 흘린다.

---

## 11. 이식할 LM24 코드와 고칠 점

### 11.1 `Get-OutlookData.ps1` → `Get-OutlookCom.ps1`

| 가져올 것(이식) | 라인 | 고칠 점(LM27) |
|---|---|---|
| GetActiveObject 우선·대화상자 skip·HRESULT 분기·재설치 금지 | `567-601, 740-757` | 그대로. `R-DIALOG`/`R-ELEV` 코드화, `UseNewOutlook`=`R-NEWOL`(경고만→blocked) |
| 프로필 사전 점검(마법사 방어) | `318-346` | 그대로. `R-NOPROF`/`R-WIZARD` |
| 일정 `IncludeRecurrences`+`Sort('[Start]')`+겹침 Restrict·응답/회의 상태 | `372-399` | Restrict 를 **DASL ISO**로(§5.5). 주최자·참석자·`GlobalAppointmentID`·온라인 회의 추가 |
| 달 단위 이어 수집·예산·경계 분 표식 | `7-21, 405-516, 517-540` | `coverage.json`→`raw_cursor.json.cov_months`+커버리지 셀로 승격. 파일 통째 덮어쓰기 폐기 |
| rcv to/cc/bulk·Recipients 정밀 확인 | `458-491` | **수신자 실패 시 `to`→`unknown`**(오판정 금지). B단은 `-ReadProtected` 게이트 |
| 내 주소 다출처 수집 | `614-626` | 그대로. 못 구하면 `R-NOADDR` |
| `time_precision` 열·self-test 주입 | `59-61, 26-27, 49-51` | `ts_precision`/`LM_OUTLOOK_SELFTEST` 유지(§14) |
| **폐기**: `GetDefaultFolder(6/5)` 최상위만 | `416-418, 443` | **모든 메일 폴더 재귀 + EntryID 역할 태그**(§5.3) |
| **폐기**: Restrict 'g' 로캘 날짜 | `100, 378, 445` | **DASL `@SQL` UTC**(§5.5) |
| **폐기**: `Class 43` 필터로 회의 응답 버림 | `453` | `meeting_response` 능동 신호로 남김 |
| **폐기**: `storeMailSubject=false` 가 제목 비움 | `24-25, 45-46` | 항상 '정제된 제목(`subject_masked`)+대화 키' — 열 허용 목록 |
| **폐기**: CSV 통째 저장·`mail_source.json` 단일 source | `186-209, 717-729` | 불변 세그먼트 + 커버리지 원장. 원문 CSV 미저장 |
| **승격**: COM 호출을 Diagnose 의 Start-Job+PID 종료 패턴으로 | `Diagnose-Collectors.ps1:66-80` | **모든 COM 호출을 자식 프로세스+20초 워치독**(§5.2) |

### 11.2 `Get-OutlookIndex.ps1` → `Get-OutlookIndex.ps1`(개조)

| 이식 | 라인 | 고칠 점 |
|---|---|---|
| `mapi%` 필터·UTC 리터럴·확장→기본 재시도 | `205-212, 183-186, 168-180` | 그대로 |
| 폴더 조각 정확 일치 제외·sent 판정 | `219-226` | 그대로(로캘 폴더명 목록은 설정 확장) |
| 내 주소 다출처(whoami/AD/프로필/owner) | `66-121` | 그대로. `R-NOADDR` |
| rcv 판정(한 항목 단위 정규식) | `240-251` | 그대로 |
| 반복 마스터 미전개 → exit 3 | `280-281, 313-316` | `recurrence_incomplete` 플래그 + cal.owa todo |
| self-test(`LM_INDEX_FAKE`) | `15-17, 124-166` | 유지(§14) |
| **폐기**: 조용한 상한 20000/8000 | `146, 212, 273` | 상한 걸리면 `partial`+`cap_hit`+`R-CAP` |
| **폐기**: 기존 파일 있으면 skip·`-Force` 통째 교체 | `59-64, 258` | 셀 단위 계획·불변 세그먼트. NDJSON stdout(디스크 직접 쓰기 폐기) |
| **폐기**: `storeMailSubject` 로 제목 비움 | `30-31, 236` | 정제된 제목 항상 |

### 11.3 `Get-OutlookWeb.py` → `Get-OutlookWeb.py`(개조) — mail.owa/cal.owa

`collect\Get-OutlookWeb.py`(PY, 백필 PC 전용). 인자 `--kind mail|cal --from --to --pc --profile <dir> --port
<n> --blanks-file <json>(mail) --login-wait-sec 600`.

| 이식 | 라인 | 고칠 점 |
|---|---|---|
| 전용 Edge 프로필 CDP(copilot_auto 의 ensure_edge·WS 클라이언트) | `255-` | **프로필을 `%LOCALAPPDATA%\...\bridge_profile`(번들 밖)로**(결정 §3). **자기 탭 소유+종료** |
| 날짜는 **머리 조각(title·aria-label)에서만**·본문 인용 머리글 금지·date-only=12:00+precision | `281-316` | 그대로(회신 인용 오독 방지 — 감사 확정 결함) |
| 폴더 슬라이스=box·rcv cc/to·스크롤 정체(슬라이스 전용 집합) | `322-357, 646-664` | 그대로 |
| 검색 질의 `received>=YYYY-MM-DD received<=YYYY-MM-DD`·listbox 스크롤 | `624-697` | **메일은 원장 빈 셀 날짜 범위만**(`--blanks-file`). 전체 재수집 폐기 |
| OWA 주 보기 일정(회차 전개)·다일 일정 한 행 | `700-734` | **일정은 기간 전체**(색인 반복 보완). 그대로 |
| 로그인 판정(login.microsoftonline…)·exit 2 | `547-566, 831-838` | `R-LOGIN`/`R-CA`(AADSTS). **최대 10분 폴링**(즉시 '불가' 금지) |
| **폐기**: CSV 통째 저장·`mail_source.json` 교체 | `750-766` | in-process `sanitize_record`+`SegmentWriter`. 원문 미저장 |
| **폐기**: 영구 생략 플래그 | — | 탐침 변화 시 자동 해제(§8) |

- rc: 0 저장 / 1 0건 / 2 `R-LOGIN`·`R-CA` / 3 `R-EDGEPOL`(RemoteDebuggingAllowed=0·DevTools=2). Edge 정책이
  막혔으면 **수동 붙여넣기/반입 경로**로 배정(COPILOT_BRIDGE.md).
- **탭 신원**: 정확한 호스트 허용 목록(`outlook.office.com` 등 §1 `HOSTS`)만. Copilot 탭·다른 탭을 건드리지
  않고 자기 탭을 소유, 끝나면 닫는다(LM24 가 탭을 안 닫아 Copilot 탭 오인 유발 — COPILOT_BRIDGE.md).

### 11.4 `Get-MailViaCopilot.py`(개조) — mail.copilot (증인 전용)

`collect\Get-MailViaCopilot.py`(PY, 클라우드PC 전용). COPILOT_BRIDGE.md 의 L0~L4 브리지를 쓴다.

- **존재·건수 증인만**: 빈 일자에 '그날 메일/스레드가 있었는가'만 묻는다(7~10일 조각, 100행 이하, 새 채팅·
  Work 모드). 결과는 `copilot_ev` kind, `ts_precision="summary"`, `text_masked≤200` — **시간 근거 아님**.
- 라이선스·커넥터 없음 → `R-NOLIC`/`R-NOCONN`, **2-strike + 조건 폴링**(LM24 영구 플래그 폐기). 다른 날 2회
  전엔 미확정, 탐침 바뀌면 해제.
- **전송 직전 개인정보 게이트**(PRIVACY §8·§14, COPILOT_BRIDGE.md): 같은 정제기로 재검사, 잔여 PII 행 제외,
  건수만 감사. **원문 응답·프롬프트 파일을 디스크에 남기지 않는다**(LM24 `replies\`·`mail_prompt_*.txt` 폐기).
- rc: 0 증인 기록 / 1 0건 / 2 로그인 / 3 커넥터·라이선스 불가.

### 11.5 `Import-MailCal.py`(신규) — mail.import / cal.import

`collect\Import-MailCal.py`(PY, 표준 라이브러리). 인자 `--kind mail|cal --in-dir <반입폴더> --pc`. 정식 대체.

- **EML**: stdlib `email` 모듈로 헤더·본문 파싱(`From/To/Cc/Subject/Date/Message-ID/In-Reply-To/References/
  List-Unsubscribe/Precedence`). `headers_text` 로 광고 헤더 bool 추출 가능. → mail 후보.
- **ICS**: `VEVENT` 최소 파서(`DTSTART/DTEND/SUMMARY/ORGANIZER/ATTENDEE/STATUS/RRULE/LOCATION/CLASS`).
  `RRULE` 전개는 단순 주기만(복잡 반복은 `recurrence_incomplete`). → cal 후보.
- **CSV**: 문서화된 반입 스키마(mail: `COLLECTION.md`의 열 이름 헤더; cal: 동). 열 수 방어(남는 열 버림·모자란
  열 빈칸 — LM24 `extract._read` 패턴).
- **`.msg` 는 지원하지 않는다**(바이너리 직접 파싱 = OST/PST 직접 파싱과 같은 경계 — §0). 반입 폴더에 `.msg`
  가 있으면 `skipped_msg` 건수만 안내하고 무시.
- 정제는 in-process `sanitize_record`. rc: 0 저장 / 1 대상 없음. 반입 성공 파일은 처리 표식만 남기고 **원본은
  건드리지 않는다**(무부작용).

---

## 12. 정제·공사(公私) 구분 계약 (수집기 측 의무)

- 각 수집기는 원문을 메모리/파이프에서만 다루고, 저장 직전 `lm27.privacy.sanitize_record(kind, raw, rc)` 를
  통과시킨다(PS 는 §4.4 스트림, PY 는 in-process). 반환 `RecordOutcome.outcome ∈ {stored, dropped, error}`:
  - `dropped`(reason `ad`/`cred`/`private_folder`/`bad_raw`…) 와 `error` 는 **저장하지 않는다**. 커버리지 원장
    에는 dropped 도 '관측 건수'로 센다(광고를 버려도 '그날 수집 성공'은 사실).
  - `stored` 는 **열 허용 목록**(§3.3)만. 원 제목·주소·본문·헤더 원문은 레코드에 없다.
- 공사 구분(PRIVACY §12): `sensitivity∈{1,2}`·개인 범주·사용자 지정 사적 대화는 즉시 `private`(제목 폐기,
  일정은 블록만). `priv_class∈{private,social}` 행은 텍스트 열을 비우고 메타만. **사적 구간은 근무 봉투·초과
  근무 근거에서도 빠진다**(시간 명세 R-P1~P6) — 심야·주말 사적 메일이 초과근무로 부풀지 않게.
- `rules_ver`·`kid` 를 레코드마다 기록(없으면 적재기가 버림). 클라우드PC 는 Copilot 전송 직전 같은 정제기로 재검사.

---

## 13. 설정 키 (단일 레지스트리, 죽은 키 금지)

| 키 | 기본 | 뜻 |
|---|---|---|
| `collect.backfillPc` | `"cloud"` | OWA·Copilot 백필 담당 PC |
| `collect.mail.period` | `{since,until}` | 수집 기간(로컬) |
| `mail.includeArchiveStore` | `false` | COM 보관 사서함 포함 |
| `mail.com.budgetSec` | `360` | COM 예산(일정은 절반) |
| `mail.com.watchdogSec` | `20` | 자식 COM 워치독 |
| `mail.com.readProtected` | `auto` | B단 읽기(탐침 OMG 통과 시 오케스트레이터가 1) |
| `mail.index.capMail` / `.capCal` | `20000` / `8000` | 색인 상한(걸리면 partial 기록) |
| `mail.index.excludeFolderNames` | 내장 ∪ 추가 | 로캘 폴더명 제외 목록(§6.1) |
| `ledger.mismatchRatio` | `1.3` | 색인↔COM 건수 불일치 'COM 누락 의심' 임계 |
| `mail.owa.loginWaitSec` | `600` | 로그인 폴링 상한 |
| `mail.owa.profileDir` | `%LOCALAPPDATA%\...\bridge_profile` | 본인 전용 Edge 프로필(번들 밖) |
| `mail.owa.port` | `9333` | CDP 포트(사용 중이면 자동 변경) |
| `mail.copilot.chunkDays` | `10` | Copilot 증인 조각 크기 |
| `mail.copilot.maxRows` | `100` | 조각당 상한 |
| `mail.import.inDir` | `data\import` | 반입 폴더 |
| `confirmBlockedCount` | `2` | '불가' 확정 횟수(서로 다른 날) |
| `probe.budgetSec` | `60` | 탐침 예산 |

- 팀 서버 기본 주소 `http://10.115.147.68:9310` 은 변경 금지(설정 옵션으로만) — 메일 경로와 무관하나 설정
  레지스트리 단일원 규칙을 공유.

---

## 14. 탐침 기여분 (메일·일정)

수집 **앞에 매번**(COLLECTION.md §4). 내용 0바이트, 숫자·열거·사유 코드만. `pc.json.capability` 에 기록.

- **P-OL-INST**: `OUTLOOK.EXE` 경로·버전, C2R/MSI 병존, 새 Outlook Appx·`UseNewOutlook`, 프로필 수, 기본
  프로필 해시, Office EOL(`R-OFFICE`).
- **P-OL-COM**(자식+20초 워치독, 떠 있을 때만): Version, `ExchangeConnectionMode`, `IsCachedExchange`, Stores
  수·유형, 동기화 기간, 받은/보낸편지함 지평선(최고·최신 시각), **기본 폴더 밖 메일 비중(`subfolder_ratio`)**,
  **OMG 상태**(정책 키+백신 보안센터 등록+보호 속성 1회 시험 읽기 2초 — 부제목·주소·본문 0글자, bool만).
- **P-IDX**: WSearch 상태·정책(`PreventIndexingOutlook`), 카탈로그 상태·일시정지 사유, 색인 Outlook 메일·일정
  30/90/365일 건수, 최고·최신 시각, 확장 속성 지원.
- **P-EDGE**(백필 PC): Edge 설치, `RemoteDebuggingAllowed`·`DeveloperToolsAvailability` 정책, 전용 프로필 존재.
- **P-OWA**(백필 PC): 로그인 상태·AADSTS, 최근 1주 표본 분 정밀도 비율, 행 키 종류(대화 보기 여부).
- **P-CP**(클라우드PC): 메일 커넥터 가능 여부(무해한 1행 질문, 2-strike), 모델·Work 모드, 입력/출력 실측 한도.

`ok ∈ {true,false,null}`, `reasons` = R-* 목록, `confirmed_blocked` = 서로 다른 날 확인 횟수.

---

## 15. 시험 시나리오 (합성 — 실데이터·브라우저 없이)

주입점: `LM_OUTLOOK_SELFTEST=N`(COM 가짜 메일·일정), `LM_INDEX_FAKE=<json>`(색인), `LM_OWA_FAKE=<json>`
(OWA), `LM_COPILOT_STUB`(Copilot), 가상 시계. 각 시나리오는 **커버리지 셀 상태·todo·rc·PII 카나리아 0**을 assert.

| # | 시나리오 | 기대(판정) |
|---|---|---|
| 1 | 새 Outlook 전용 PC | mail.com/cal.com 셀 `blocked:R-NEWOL`, todo→mail.owa@백필, index 는 시도, PC 수집 정상 |
| 2 | 프로필 0·구판 MSI 마법사 | `New-Object` 호출 안 함, `R-NOPROF`/`R-WIZARD`, 20초 내 skip, 전체 멈춤 없음 |
| 3 | 규칙 하위 폴더·보관 사서함 | COM 재귀로 수집, `folder_role_hint` 태그, `subfolder_ratio` 기록, 색인 교차검증 건수 일치(COM 누락 0) |
| 4 | 보관 사서함 off | `mail.includeArchiveStore=false` → 보관분 `out_of_horizon`→owa todo |
| 5 | 색인 꺼짐(WSearch 중지) | index `blocked:R-NOIDX`, COM 있으면 COM, 없으면 owa todo |
| 6 | 온라인 모드(색인 0) | index `blocked:R-ONLINE`, 지평선 기록, owa 백필 배정 |
| 7 | OMG '항상 경고' | B단 skip, `rcv=unknown`, A단 행은 저장, `ad_partial=true`, `R-OMG`(행 폐기 0) |
| 8 | 로캘 비한/영 폴더명·제한 언어 모드 | DASL ISO 로 로캘 무관 수집; `R-CLM` 이면 owa·import 로 배정 |
| 9 | 지평선 3개월 + 1년 요청 | 지평선 밖 달 `out_of_horizon:R-HORIZON`→owa todo, 예산 닿으면 `partial:R-BUDGET` |
| 10 | 상한 절단(20000/8000) | `partial`+`cap_hit`+`R-CAP`(조용히 자르지 않음) |
| 11 | date-only(어제 이전) OWA | `ts_precision=date`, 시간 기여 0, 분 사본 있으면 병합에서 흡수 |
| 12 | 색인 반복 마스터만 | cal.index `recurrence_incomplete`, exit 3, cal.owa 주 보기 todo, 회의 시간 과소 아님 |
| 13 | 회의 수락/거절 발신 | `meeting_response=true` 능동 신호로 남음(버리지 않음) |
| 14 | 광고 메일((광고)·List-Unsubscribe) | `ad_band=drop`→미저장, 건수만 감사, 카나리아 0; 왕래 협력사 업무 회신은 keep |
| 15 | 사적 메일(Sensitivity=1·개인 범주) | `priv_class=private`, 제목 폐기, 심야 사적 메일이 초과근무로 안 잡힘 |
| 16 | UTC 클라우드PC | `ts_utc`+offset 정합, 병합 중복 2배 없음, `utc_suspect`/`R-TZ` |
| 17 | Copilot 무라이선스 | mail.copilot `blocked:R-NOLIC`, 다른 날 2회 전 미확정, 탐침 바뀌면 해제, summary 시간 기여 0 |
| 18 | `.msg` 반입 | `skipped_msg` 건수만, EML·ICS·CSV 는 정상 반입 |
| 19 | 멀티PC 재방문(PC1→PC2→PC1) | 세그먼트 덧붙임만, 커서 이후분 자연 합류, 같은 메일 2중 계수 없음 |
| 20 | 내 주소 미확정(도메인 미가입) | `R-NOADDR`, rcv=unknown(bulk 로 안 버림), 다른 PC 주소 해시로 재판정 가능 |

공통 판정: date-only·summary 시간 기여 0, **PII 카나리아 0건**(세그먼트·프롬프트·팀 페이로드), 중복 병합 후
건수 보존, 상한 걸리면 반드시 `partial`/`cap_hit`, 제어문자 0, 설정 키 단일 레지스트리, bat/ps1 인코딩, 원문
디스크 잔재 0(CSV·replies·prompt 파일 없음).

---

## 16. 반환 요약 (오케스트레이터용)

- **경로**: `D:\배포\loadmon27\docs\COLLECT_MAIL.md`
- **요약**: 메일·일정 9개 경로(`mail.com cal.com mail.index cal.index mail.owa cal.owa mail.copilot mail.import
  cal.import`)를 '역할 분담 + 셀 커버리지 원장 + msg_key 병합'으로 설계. 로컬(색인 항상·COM 정밀) → OWA 빈칸만
  → Copilot 증인 → 반입. 모든 수집기는 원문을 메모리/파이프에서만 다루고 `lm27.privacy.sanitize_record` 통과
  열 허용 목록만 저장. 문서화 UI만(Graph·OST/PST·.msg·앱 캐시·숨김 폴더·관리자 권한 없음).
- **인터페이스**:
  - PS 수집기 → stdout NDJSON → `python -m lm27.privacy.sanitize_stream --kind <mail|cal> --src <id> --pc <id>
    --out <seg.jsonl.gz>`(혼합은 `--route-by-kind` — §4.4, §13 미결).
  - PY 수집기 → `lm27.privacy.sanitize_record(kind, raw, rc) -> RecordOutcome` + `SegmentWriter.append(SanitizedRow)`.
  - 원시 후보 레코드 스키마 §3.1(mail)·§3.2(cal). 저장 열 §3.3(PRIVACY §10.2).
  - 스크립트 계약: `Get-OutlookCom.ps1`(§5), `Get-OutlookIndex.ps1`(§6), `Get-OutlookWeb.py`(§11.3),
    `Get-MailViaCopilot.py`(§11.4), `Import-MailCal.py`(§11.5). rc 0/1/2/3/4 + 사유 코드 R-*(§8).
- **설정 키**: §13 표(`collect.backfillPc` `mail.includeArchiveStore` `mail.com.budgetSec` `mail.com.watchdogSec`
  `mail.com.readProtected` `mail.index.capMail` `mail.index.capCal` `mail.index.excludeFolderNames`
  `ledger.mismatchRatio` `mail.owa.loginWaitSec` `mail.owa.profileDir` `mail.owa.port` `mail.copilot.chunkDays`
  `mail.copilot.maxRows` `mail.import.inDir` `confirmBlockedCount` `probe.budgetSec`).
- **미결(open issues)**:
  1. **COLLECTION.md ↔ PRIVACY.md 저장 열 이름 불일치**: `subject_tokens`(C) vs `subject_masked`(P),
     `counterpart_keys`(C) vs `peer_keys`+`sender_key`(P), `thread_key`(C) vs `conv_key`(P), `folder_role`(C) vs
     `folder_class`(P), `flags` 사전(C) vs 분리 열(`ad_band`·`cat_private`)(P). 계약 소유자가 한쪽으로 통일 필요.
  2. **혼합 stdout kind 라우팅**: `sanitize_stream` 에 `--route-by-kind` 를 추가할지, COM 을 `-Only mail`·
     `-Only cal` 로 두 번 attach 할지(현 기본). 추가 시 단일 `--kind` 계약과의 정합성 승인 필요.
  3. **OWA date-only 분 정밀 비율 실측**: 어제 이전 메일 title/aria-label 에 분 단위가 들어오는 비율. 낮으면
     메일 시간 근거는 COM·색인 PC 에만 의존(탐침 P-OWA 로 측정).
  4. **OWA 대화 보기(data-convid)**: 스레드 1행 접힘 시 메시지 단위 열거 방법(검색 결과 보기 등) — 사용자
     설정을 바꾸지 않는 선에서.
  5. **보호 열 불가 PC(새 Outlook·OWA·색인)의 광고·동료 재료**: `ad_partial` 신뢰도 표기로 충분한지, 아니면
     해당 PC 의 광고 판정·`peer_keys` 를 비활성화할지.
  6. **내 주소 해시 번들 공유**: COM 이 확정한 `my_addrs` 해시를 번들로 공유해 `R-NOADDR` PC 의 rcv 를
     재판정하는 경로(가명 키 2층과의 정합) — 설계 확정 필요.
  7. **관리되지 않는 Edge 프로필을 조건부 액세스가 막는 사용자**: 본인 전용 프로필 대신 회사 로그인 기본
     프로필 사용을 허용할지(데이터 접근 원칙 §2와의 관계) — 사용자 확인.
  8. **회고 기간 vs 지평선·보관 사서함 포함 범위**(`mail.includeArchiveStore`), **1MM 분모 정의 표기** —
     사용자 확인 항목.
