# LM25 v25.9 기간 원문 수집

## v25.9 — 메일 7건·Teams 0건, 긴 대기 후 무결과 재검토

사용자 테스트 PC에는 접근하지 못했다. 따라서 아래는 코드·합성 DOM으로 재현한 결함이며, 실제 7건/0건의 단일 원인을 단정하는 보고서가 아니다. 기존 버튼 연결 수정만으로 앱/웹 화면 파싱과 계정 준비 문제까지 해결되지는 않았다.

| 확정 결함 | 수정 및 검증 범위 |
|---|---|
| Outlook 목록 추출은 row/grid를 지원하지만 스크롤은 listbox/option만 지원 | 공통 목록 인식과 실제 스크롤 부모 탐색. 첫 화면 7개+가상 다음 페이지 2개를 합성 DOM에서 누적 수집 |
| Outlook 검색 초점은 combobox도 찾지만 입력 검증은 다른 선택자 사용 | 같은 입력 요소·검색어 readback·결과 전환 확인. 검색이 실행되지 않은 경우 빈 결과로 완료 처리하지 않음 |
| 기존 CSV 존재 시 새 기간 수집을 생략 | 파일 존재만으로 범위 완료를 판단하는 조기 반환 제거 |
| Teams 빈 role=main 셸을 준비 완료로 판단 | 채팅 목록/메시지/명시 빈 상태로 준비 판정. 구/신 선택자와 접근성 역할·대화 식별자 지원 |
| 완전한 날짜 뒤의 시각 전용 메시지와 1~2글자 답변 탈락 | 동일 화면에서 확인된 날짜만 이어받고 짧은 본문 보존. 날짜 불명확 원문은 분석 CSV와 분리 보류. 다른 방의 재사용 DOM ID로 보류 자료가 지워지지 않도록 대화 범위 유지 |
| 빈 날짜 검색 최대 30일 반복, 고정 sleep 누적 | 빈 검색 2회 후 목록 수집, 검색은 전체 예산 25%·최대60초. Outlook은 상태 변화 기반 대기로 교체 |
| Edge 최대20초 대기 루프가 probe5초×41회로 최대225초 | 단조 시계의 절대 마감 시각과 probe별 잔여 timeout 적용. HTTP/CDP 생성·호출·재연결에도 남은 예산 전달 |
| 수집 완료 후 마지막12줄만 표시, 시간 초과 시 출력 소실 | stdout/stderr 실시간 표시·15초 heartbeat·시간 초과의 부분 출력 보존. 실행한 작업 프로세스만 종료하며 사용자 Outlook/Edge를 종료하지 않음 |

Outlook 본문은 메시지 ID·선택행·제목·유일 본문 영역을 확인한 경우에만 연결한다. 발신자/제목/분 단위 시각만 같은 다른 메일을 혼동할 수 있는 본문 폴백은 독립 검토에서 제거했다. 웹 본문은 설정한 길이의 발췌이고 전체 평문 보관을 보장하지 않는다.

`collection_diagnostics`는 COM을 실행하지 않고 등록·프로필 존재를 확인한다. COM 미등록 또는 프로필이 없고 클래식 Outlook 실행도 확인되지 않으면 불필요한 활성화 대기를 생략한다. 조회 권한 등으로 기능을 확인하지 못한 경우는 지원 불가로 단정하지 않는다. Microsoft 365 구독의 클래식 Outlook은 기존 COM 경로, 새 Outlook과 웹은 웹/허용된 Graph 경로를 사용한다. 실행 중인 앱의 이름·숫자 버전만 최대4초의 별도 읽기 조회로 기록한다.

메일 웹 기본 예산은 collection.mailWebBudgetSec=180, Teams는 teamsWebBudgetSec=300이다. 기존 개인 설정은 자동 변경하지 않는다. 파싱 실패·진행 없음은 예산을 다 쓰지 않고 중단하며 부분 결과와 재개 정보를 보존한다. 예산을 줄인 것은 완주를 뜻하지 않으며 긴 기간은 여러 번 실행할 수 있다. COM/Graph/PC/파일 단계까지 합친 전체 시간이 3~5분이라는 의미는 아니다.

수집 종료 후 `report/communication_diagnostics.json`을 원자 저장한다. 다운로드 API는 마지막 저장 원인표를 제공하며 기간·현재 실행 여부·경과 시간·관측 항목·날짜 미확인/보류 건수와 고정 사유를 담는다. 원본 reasons/log의 자유문자열, 제목·본문·계정·수신인·프로필 경로는 복사하지 않는다. Teams 보류 원문은 원인표가 아닌 로컬 보류 CSV에만 존재한다. 원인표만으로 수집 원문 내용을 공유하지 않고 실제 PC에서 실패한 경로를 다음에 구분할 수 있다.

회귀는 Windows/TEMP의 합성 데이터·가짜 registry·실제 짧은 합성 작업자·Node의 합성 DOM을 사용했다. 실제 회사 계정·로그인·원문 건수 대조와 모든 Teams/Outlook UI 버전은 미검증이다. 변경 구현자와 다른 사람이 시간 제한·본문 오귀속·날짜 보류·프로세스 종료 범위를 검토했다. 최종 전체 검사·배포 해시·Git 커밋은 배포검증.json에 기록한다.

공식 참고: [새/클래식 Outlook 기능 비교](https://support.microsoft.com/en-us/outlook/getstarted/feature-comparison-between-new-outlook-and-classic-outlook), [Teams 웹 전제 조건](https://learn.microsoft.com/en-us/microsoftteams/teams-client-web), [Outlook 웹 검색](https://support.microsoft.com/en-us/outlook/search-mail-and-people-in-outlook-on-the-web), [Teams 검색](https://support.microsoft.com/en-us/teams/chat/search-for-messages-and-more-in-microsoft-teams).

## v25.8 — 추가 PC 수집 버튼의 연결 누락 수정

사용자가 실제로 누른 `추가 PC 수집`은 `/api/run → run_job → --collect-only`로 실행됐다. 기본값 또는 이전 설정의 `collectOnlyHeadless=true` 때문에 Outlook·Teams 웹은 생략됐다. Graph가 미설정이면 보충 경로는 Outlook 색인과 Teams 열린 앱에 제한된다. COM은 이보다 앞서 별도 실행되지만, 새 Outlook에서 성공하는 경로는 아니다. TEMP에서 실제 UI 요청 처리·명령 생성·수집 경로 선택을 연결하여 이 결함을 재현했다. 다른 PC의 실제 0건 원인이 이것뿐이라고 단정하지 않는다.

UI의 두 수집 버튼은 이제 `--interactive-collect --no-mail-copilot --no-teams-copilot`을 전달한다. 추가 PC 버튼은 `--communications-only`를 전달하지 않아 PC 이력·파일·Git 수집을 유지한다. 무인 CLI의 headless 기본값과 사용자가 명시적으로 꺼 둔 웹 수집·보호 설정은 유지한다. 실제 웹 로그인·권한·화면 파싱이 실패하면 여전히 부분 수집이다.

추가 PC 버튼 아래 `collect2body`는 기본 체크이고 웹 메일을 열면서 읽음 표시가 바뀔 수 있음을 표시한다. `/api/run`이 `mail_body`를 검증하여 전달한다. 이전 페이지에서 옵션 없이 추가 PC 수집을 요청해도 본문 포함으로 처리한다. 체크 해제는 `--no-mail-web-body → --exclude-body`를 통해 저장 설정의 `mailWebBody=true`보다 우선한다. 별도 메일·Teams 전용 버튼의 체크는 기본 해제를 유지한다. 이 옵션은 웹 전용이며 Graph/COM의 별도 본문 보호 설정을 변경하지 않는다.

완료 메시지는 이번 실행 이후에 갱신된 동일 기간 근거 보고서만 사용하여 보관 자료의 고유 건수·본문 발췌 건수를 보여 준다. 이전 PC 자료를 포함한 누적 수이며 이번에 새로 받은 건수나 서버 전체 확보율이 아니다. 보고서가 없거나 오래됐거나 기간·건수가 잘못되면 `건수 확인 안 됨`으로 표시한다. 부분 종료 코드는 그대로 유지한다.

회귀 검증은 실제 PAGE 버튼 요청, API의 boolean 검증, 이전 headless 설정을 가진 PC의 경로 선택, 본문 포함/제외 우선순위, Copilot 제외, PC 수집 범위 유지, CLI 무인 수집 보존, 최신 보고서만 사용하는 완료 피드백을 포함한다. 계정·실데이터·실제 브라우저는 사용하지 않는다. 아래 v25.7 검증 수치는 이전 배포 이력이며 v25.8 실행 결과는 배포검증.json에 기록한다.

## v25.7 기반 구현

2026-09-30. v25.6에서도 다른 테스트 PC의 메일·Teams 누락이 반복되어 서버/앱/내보내기 입력 경로를 확장했다. 실제 회사 계정·PC는 접근하지 않았으며 합성 검증을 실제 서비스 성공으로 간주하지 않는다.

## 확정 결함과 변경

- `Get-OutlookData.ps1`은 기본 저장소만 열거했다. 이제 모든 연결 저장소와 이미 열린 PST의 하위 메일 폴더를 조회한다. 삭제/정크/임시보관/보낼편지함/가상/공용 폴더는 제외하며, 캘린더는 기본 계정 범위다. 이동된 발신 메일을 수신 시각으로 거르던 문제를 발신/수신 두 탐색과 실제 방향 날짜로 수정했다. COM 완료는 로컬 가시 범위이며 서버 동기화 완료가 아니다.
- 메일 서버 Graph 경로가 없었다. `Get-OutlookGraph.py`는 `/me/messages`의 수신/발신 기간 합집합을 모든 페이지로 읽고 ImmutableId와 계정/대화 ID를 보존한다. 실제 방향별 시각으로 요청 기간을 다시 검사한다. 기본 사서함 범위이며 온라인 보관함·공유/타인 사서함·영구 삭제·첨부 내용은 제외한다.
- Teams Graph는 채팅만 조회했고 재개 시 앞부분 반복 가능성이 있었다. 공통 `graph_client.PageRun`은 계정·기간·설정별 페이지 큐를 저장하며 CSV와 전체 평문 저장 성공 후에만 커서를 전진한다. `/me/chats`와 각 메시지, 선택한 경우 `/me/joinedTeams`→채널→원글→답글을 읽는다. 기간 이전 원글의 기간 내 답글도 탐색한다. 외부 호스트 팀의 공유 채널 및 권한 밖 자료는 범위 밖이다.
- `429`/일시적 서버 오류는 Retry-After를 존중하여 재시도하며 401은 앱 소유 OAuth 토큰의 정상 갱신 경로를 사용한다. nextLink/redirect가 다른 호스트로 자격증명을 보내지 못한다. 앱 ID·테넌트·동의 범위가 다른 저장 토큰을 재사용하지 않는다. 브라우저 세션·앱 자격증명을 추출하지 않는다.
- `Import-OutlookFiles.ps1`은 명시한 MSG 파일만 기존 Outlook의 OpenSharedItem으로 읽는다. PST 자동 장착·직접 해독은 하지 않는다. UI 작업은 임시 manifest만 만들고 작업 후 삭제한다. 원본 메시지는 저장하지 않고 닫는다.
- `communication_import`는 EML/MBOX에 Graph chatMessage JSON과 명시된 LM25 CSV/JSON/JSONL을 추가한다. 고정 10,000건 상한을 제거했고 JSONL은 스트리밍한다. 날짜·시간대·원문·ID가 없는 행은 사유/건수로 남긴다. 선택 파일 원본 건수는 필터 전 메시지 수와 대조하며 서버 전체 건수로 해석하지 않는다. 개인 Teams messages.json과 Purview HTML/XML의 미검증 스키마를 추측해 읽지 않으며 지정 형식으로 별도 변환해야 한다.
- `communication_archive`는 수집한 전체 평문을 `data/communication_originals/{mail,teams}`에 메시지 단위로 원자 저장한다. 분석 CSV는 문맥 기본 4,000자, AI 프롬프트는 기존 제한된 발췌 정책을 유지한다. Graph 최신 수정 시각이 확인된 짧아진 원문은 이전 긴 문맥을 대체하며 더 오래된 페이지는 최신 문맥을 되돌리지 않는다.

## 사용 설정

UI `메일·Teams 근거 확보`에서 기간을 선택하고 수집한다. 승인된 공용 클라이언트 앱이 있다면 앱 ID/테넌트를 입력하고 `설정 저장하고 Microsoft 로그인`으로 연결한다. 기본 위임 권한은 User.Read, offline_access, Mail.Read, Chat.Read다. 채널 선택 시 Team.ReadBasic.All, Channel.ReadBasic.All, ChannelMessage.Read.All을 추가한다. 테넌트의 사용자 동의·앱 등록 정책에 따라 관리자 승인이 필요할 수 있다.

서버 연결이 차단되면 기존 Outlook에 필요한 기간까지 동기화하고 이미 연 PST를 함께 수집하거나 명시한 내보내기 파일을 가져온다. 새 Outlook PST 내보내기는 지원되는 설치에서 설정→파일→내보내기 경로를 사용한다. 캐시된 자료만 내보내면 그 밖의 서버 메일은 빠진다. Teams 조직 내보내기는 적절한 관리자 권한과 원문이 필요하다.

가져오기 UI의 본인 메일 주소·원본 건수는 요청 단위 옵션이며 다른 개인 설정을 덮어쓰지 않는다. MSG 버튼은 파일 전체 경로만 지원한다. 일반 파일 버튼은 바로 아래 파일을 포함한 폴더 입력도 지원한다. 큰 파일 입력 제한은 `communicationImportMaxFileMB`(기본512), JSON/CSV `communicationImportMaxJsonMB`(기본64), 메시지 단위16MB이며 초과는 완료로 숨기지 않는다.

Graph 단계 예산은 collection.graphBudgetSec 기본900초, 메일/Teams 보충 총예산은 각각2400초다. Graph 호출에 매번 --force를 넣지 않는다. 같은 기간 재실행으로 미완료 페이지를 잇고 완주한 실행은 다음에 새 조회를 시작한다. 실행 중 데이터 변경까지 원자적 스냅샷을 보장하지 않는다.

PC 이동 ZIP에서는 Graph 로그인 토큰을 제외한다. 수집 원문·CSV·페이지 체크포인트는 보존하며 목적 PC에서 다시 로그인한다. MSG 작업자가 COM 응답을 기다리며 멈추면 UI의 330초 감시가 해당 수집 작업자만 종료하고 부분 상태를 남긴다. 사용자의 Outlook 프로세스는 종료하지 않는다.

## 검증과 배포 기준

새 검증은 TEMP 합성 입력만 사용한다. Graph 페이지/채널/답글/403/재시도/재개/저장 실패, 네이티브 다중 저장소와 발신 날짜, 파일 스트리밍/건수/오류 분류, 원문 보관, UI 연결/가져오기 요청, 분석 문맥 전달을 확인한다. 전체 프로젝트 검증과 배포 ZIP 파일 무결성 검증 결과는 커밋 및 작업 완료 기록에 남긴다.

최종 `scripts/Test-Project.ps1`: 542개 실행, 541개 통과·환경 의존 1개 생략, 128.037초. quick/문법/Ruff/PS 인코딩·파서/실제 PAGE JavaScript 파서/필수92파일·CRC/기존7관문 모두 통과했다. 로그는 `verification/lm25-check-20260930-161447-687.txt`(Git 제외)에 보관했다. HTML은 7개 섹션·2개 SVG·로컬 링크 구조를 검사했으며 브라우저 시각 렌더링은 실행하지 않았다. 기존 ResourceWarning은 테스트 실패로 처리되지 않았고 이번 수집 변경과 분리한다.

LM24 브랜치와 원본 설치/실데이터/개인 설정은 변경하지 않는다. Graph 동의, 회사 PC Outlook 버전·캐시, 실제 웹 DOM과 원본 건수 대조는 미실행이다. '누락 없이 수집 성공'을 주장하지 않는다.

## 공식 근거

- [Graph 메일 목록](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0), [메일 API 범위](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview?view=graph-rest-1.0)
- [채팅 메시지](https://learn.microsoft.com/en-us/graph/api/chat-list-messages?view=graph-rest-1.0), [채널 메시지](https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0), [답글](https://learn.microsoft.com/en-us/graph/api/chatmessage-list-replies?view=graph-rest-1.0)
- [PST 내보내기](https://support.microsoft.com/en-us/outlook/export-emails-contacts-and-calendar-items-to-outlook-using-a-pst-file), [MSG OpenSharedItem](https://learn.microsoft.com/en-us/office/vba/api/outlook.namespace.openshareditem), [Teams 조직 내보내기](https://learn.microsoft.com/en-us/microsoftteams/export-teams-content)
