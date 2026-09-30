# LM25 v25.4 수집 신뢰성 개선

2026-09-30. 대상: `LoadMonitor25/`. 수집 개선 당시 LM24 기준선 내용은 변경하지 않았습니다. 이후 사용자 요청으로 이 브랜치를 LM25 전용으로 정리하여 비교용 LM24 폴더와 기준선 목록을 제거했습니다. 원래 `lm25` 작업 폴더의 미커밋 v25.3 변경 31개를 별도 커밋으로 보존한 뒤 개선합니다. 개인 설정·수집 자료·보고서·인증 프로필은 변경이나 배포 대상에 포함하지 않습니다.

## 구현

- `core/collection_state.py`: 출처 식별자와 보수적인 레거시 매칭, 원자적 CSV 누적 저장, 요청 기간·시각을 검증하는 상태 파일.
- `core/communication.py` 및 `run.py`: 단계 성공·CSV 시각 대신 명시된 수집 범위로 보충 여부 결정. 메일/일정 개별 판정, 예산·옵션·중단 이유 기록, 프로세스 실패 시 완료 판정 강등.
- Outlook 수집기: 기본 저장소 메일 폴더 탐색, 제한된 본문 발췌, 폴더 범위 변경에 따른 완료 표 갱신, 선택적 웹 본문 읽기, 모든 보충 결과 누적 저장.
- Teams 수집기: Graph 페이지·오류·상한 판정, 웹 가상 목록과 과거 기간 탐색, 페이지별 저장, 날짜 포함 중복 키, 앱 확장 CSV 읽기와 시간 정밀도 표시.
- 추출/분석/정제: 기존 표시문·식별자 호환성을 유지하면서 문맥·출처 별도 전달. AI 입력 예산과 생략 표시. 추정을 사실로 복원하지 않도록 지시.
- UI: 요청 기간과 일치 여부, 경로별 상태·범위·이유 표시. 독립 활동 기간 조회에서도 상태 표 유지.

## 독립 검토에서 보강한 사례

같은 ID에 짧은 보충 본문이 긴 본문을 덮는 문제, 동명 Teams 대화의 서로 다른 대화 ID가 합쳐지는 문제, 날짜만 있는 보충 관측이 정확한 시각을 덮는 문제를 합성 자료로 재현해 수정했습니다. 프로세스가 실패해도 완료 체크포인트를 믿는 경로와 활동 기간 조회가 범위 표를 지우는 경로도 보강했습니다.

Git pre-commit 내부의 합성 저장소 테스트가 부모 저장소 환경을 상속하는 결함도 수정했습니다. staged snapshot 검사는 유지하고, 그 내부 테스트 프로세스에만 Git의 로컬 저장소 환경변수를 제거합니다. 부모 index 보존 회귀를 추가했습니다.

## 검증 범위

실제 사내 계정으로 수집·Copilot·업로드를 실행하지 않습니다. 합성 TEMP 파일, 주입한 Graph 응답·DOM, 실제 PowerShell↔Python 저장 경로, 실제 추출→판정 프롬프트, Node UI 렌더 함수로 검증합니다.

재현 명령:

```powershell
python -B scripts/quality.py --quick
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Test-Project.ps1
```

신규 회귀: `test_communication_collection.py`, `test_outlook_collection_reliability.py`, `test_teams_collection_reliability.py`, `test_collection_context.py`, `test_collection_coverage_ui.py`.

최종 실행 결과: 전체 420개 중 419개 통과·환경 조건 1개 건너뜀, 실패 0개. 구문·Ruff·인코딩·PowerShell/JavaScript 파서·필수 파일·FILES CRC·기존 lint 7관문 모두 통과했습니다. 새 수집·문맥·UI 회귀 70개를 포함합니다.

풀패키지의 파일 113개(필수 79개+Python 런타임 34개)를 소스와 바이트 단위로 대조했고, 개인 데이터 경로 파일 0개 및 기본 설정 사용을 확인했습니다. ZIP SHA-256: `97268ec382850d46858192373a1b2fa2a710ccec1d74b3c115a1d7faa7cd9c80`.

배포본은 `LoadMonitor25/tools/Make-Package.ps1`의 FILES 허용 목록으로만 생성합니다. 실제 조직 정책, 설치별 UI·색인·동기화 차이, 전체 원문·첨부·채널 대화 확보는 별도 실제 환경 검증이 필요합니다. 제품 수준과 설정은 [사용 안내](../LoadMonitor25/docs/LM25_수집개선.md)에 설명합니다.
