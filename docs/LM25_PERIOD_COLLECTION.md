# LM25 v25.7 기간 원문 수집

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
