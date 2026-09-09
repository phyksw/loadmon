# LM25 기반 구축 검증

2026-09-09 검증. LM25 제품 기능 전체의 출시 검증과 구분합니다.

| 항목 | 결과 |
|---|---|
| LM24 원본 SHA-256 | 101/101 파일 불변 |
| LM25 실행 준비 | 내장 Python 3.11.9, LM25 BAT 파일명/참조 갱신 |
| Ruff | LM25 전체 Python, UI 및 프로젝트 도구/테스트 통과 |
| 구문 | Python/JSON/TOML, PowerShell 파서, Node의 PAGE/TEAM_PAGE 모두 통과 |
| 인코딩 | BAT CP949·CRLF, PS1 UTF-8 BOM·CRLF 통과 |
| 필수 파일 | TEMP 기본설정 복제본 67/67 존재, FILES.txt 크기·CRC 일치 |
| 기존 린트 | UI를 포함하도록 보완한 7관문 통과 |
| 회귀 | 훅/캐시/부분 스테이징/개인자료 제외 13개 통과 |
| Codex 명령 직접 호출 | LM25 하위 폴더에서 실제 hooks.json 명령에 PostToolUse·Stop JSON 입력, 정상 반환 |
| 동일 코드 캐시 | 두 번째 Stop이 캐시를 사용해 정상 반환 |
| Git 연결 | 로컬 `core.hooksPath=.githooks`, `git hook run pre-commit` 호출 성공(실제 저장소에 스테이징된 파일 없음) |
| 서브에이전트 | TOML 4개 파싱·필수 필드·모델/권한 상속 확인 |
| 실데이터 | LM24/LM25의 data·report 파일 0개 유지 |

최종 전체 검사는 `RESULT: PASS (0 failed gates)`였습니다. 실행 로그는 `verification/lm25-check-20260909-222107-888.txt`, 이후 실제 Stop 명령 검증 로그는 `.codex/.state/full-last.txt`에 있습니다. 로그·검사 캐시는 Git에서 제외합니다.

## 결함 검출 검증

합성 TEMP 폴더에서 Python·JSON·TOML 문법 오류, PS1/BAT 인코딩 오류, PAGE/TEAM_PAGE의 중복 JavaScript 선언이 실패로 잡히는 것을 확인했습니다.

회귀 13개는 다음을 포함합니다: 코드 변경/삭제 및 루트 대문자 확장자 변경의 캐시 무효화, DATA/Report/copilot_profile/개인설정 제외, 성공만 캐시, 검사 도중 파일 변경 시 성공 캐시 금지, Stop의 한 차례 후속 실행과 실패 표시, Plan 모드 제외, 잘못된 stdin, 인덱스 오류+정상 작업 파일 조합의 실패, 정상 인덱스+오류 작업 파일 조합의 성공, 대문자 개인자료 디렉터리 스테이징 거부.

독립 검토에서 발견한 캐시 대상 누락과 디렉터리 대소문자 문제는 공통 파일 열거기로 수정하고 회귀에 반영했습니다.

## 적용 상태와 한계

Codex CLI 0.153.4의 `doctor --strict-config` 진단에서 `config.load=ok`를 확인했습니다. 이는 설정 로드 확인이며, 이 대화에서 새 프로젝트의 역할 파일이 자동 선택되거나 훅 신뢰·실제 이벤트 전달까지 검증되었다는 뜻은 아닙니다. 현재 대화의 시작 위치는 `D:\배포`이고 설정은 하위 `_gpt/.codex`에 있습니다. `_gpt`를 작업 루트로 사용하고 Codex 훅 검토·신뢰 절차를 거쳐야 자동 적용됩니다.

실제 Git 커밋/배포 ZIP 생성/프로그램 UI 시작/수집/작업 스케줄러 등록/Copilot/Outlook/Teams 연결/팀 업로드는 수행하지 않았습니다.

[제품 검토에서 재현한 문제 3개](LM25_REVIEW_EVIDENCE.json)는 아직 남아 있습니다. 린트·기반 회귀 통과를 그 문제의 수정 완료로 해석하면 안 됩니다. 구현 우선순위와 완료 조건은 [LM25_PLAN.md](LM25_PLAN.md)에 있습니다.
