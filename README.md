# LoadMonitor25 개발 프로젝트

**v25.4 수집 개선(2026-09-30):** 메일 하위 폴더·본문, Teams 탐색·문맥 보존, 경로별 범위 판정, 누적 병합과 AI 문맥 전달을 보강했습니다. [수집 워크플로우와 사용 설정](LoadMonitor25/docs/LM25_수집개선.md), [구현·검증 기록](docs/LM25_COLLECTION_RELIABILITY.md)을 참고하세요. 별도 개선 브랜치 `codex/lm25-collection-reliability`에서 기존 v25.3 작업을 보존해 진행했습니다.

**집계 미표시 재검증(2026-09-14, v25.3):** MM 문자열·비유한 숫자·잘못된 실행 단계 형식이 전체 집계 화면을 막는 사례와 상단 날짜 변경이 집계에 반영되지 않는 사례를 실제 전체 PAGE·HTTP·브라우저에서 재현하고 수정했습니다. 집계는 독립 요청으로 먼저 표시하며 숫자표를 기본으로 펼칩니다. 세부 실행 기록은 [집계 재검증 결과](D:/배포_gpt/LM25_집계재검증_20260914/집계_재현과_수정결과.md)에 남깁니다.

**이전 구조 변경: [2026-09-13 목적 기반 재설계](docs/LM25_REDESIGN.md).** v25.2는 수집 기록의 독립 기간 조회, 저장된 일별 장부를 사용하는 주·월 리뷰, 부분 PC 기록과 기계 산출 구분, 게시 완료 상태, 팀 참고 흐름을 연결합니다. 아래 문서의 이전 완료 기록과 현재 구현 범위를 구분합니다.

LM20·LM24의 목적과 구현을 읽고 **근거 있는 인적 투입 추정, 업무 구조화, 팀의 AI 적용 대상 검토**를 중심으로 LM25를 개선한 개발 프로젝트입니다. LM20·LM24 설치와 저장소의 LM24 기준선은 변경하지 않습니다.

현재 변경·검증·남은 한계는 [2026-09-12 목적 재검토와 개선](docs/LM25_REASSESSMENT.md)에 정리했습니다. 무인 솔버·결측·제외 MM, 업무/근거 식별, 기간 정합성, 후보 중복 안분, 팀 비교와 전송 원자성을 보강했습니다. 기존 9월 9일 검토는 당시 문제의 기록이며 최신 상태와 구분합니다.

PC를 순서대로 옮겨 쓰는 흐름을 위해 **PC 이동 준비에 ZIP 생성을 통합**했습니다. 담당자 워크플로우의 상위·과제 접기, PC 자료 보존·표시, 월간 리뷰 기간 선택과 코멘트 보존도 보강했습니다. [사용 안내](LoadMonitor25/docs/빠른이동.md), [회귀 보완 기록](docs/LM25_REGRESSION_RECOVERY.md), [최초 속도 개선 검증](docs/LM25_SPEED_VALIDATION.md)을 참고하세요. 기존 전체 설계 검토의 다른 제품 결함을 모두 해결한 것은 아닙니다.

## 구성

| 위치 | 역할 |
|---|---|
| `LoadMonitor25/` | 현재 개발 대상. LM25 실행 파일명·배포 도구·내장 Python 포함 |
| `LoadMonitor24/` | 수정하지 않는 원본 비교용 기준선 |
| [목적 재검토와 개선](docs/LM25_REASSESSMENT.md) | 최신 수정, 독립 검토, 예상 문제와 대응안 |
| [최초 전체 기능 설계 검토](docs/LM25_FULL_DESIGN_REVIEW.md) | 9월 9일의 결함·우선순위와 완료 기준 |
| [개선 계획](docs/LM25_PLAN.md) | 재현한 문제, 우선순위, 완료 조건 |
| [개발 안내](docs/DEVELOPMENT.md) | 린트·검증·훅 설치와 적용 범위 |
| [서브에이전트](docs/SUBAGENTS.md) | 측정 / 업무·AI / 보고서 / 독립 검증 4개 역할 |
| [LM25 검증 기록](docs/LM25_VALIDATION.md) | 이번 구축에서 실행한 검사 결과 |
| [검토 재현 자료](docs/LM25_REVIEW_EVIDENCE.json) | 합성 사례의 관찰값과 기대 개선값 |
| [기존 작업 맥락](docs/PROJECT_CONTEXT.md) | Markdown 22개와 LM24 코드 검토 기록 |

## 작업 명령

```powershell
Set-Location 'D:\배포\_gpt'
# 편집 후 빠른 검사
python -B scripts/quality.py --quick
# 완료 전: 정적 검사 + TEMP 패키지 검사 + 회귀
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Test-Project.ps1
# Git 훅 설치(이 저장소에는 설치 완료)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Install-Hooks.ps1
# 제품 문제 3개를 합성 자료로 재현(개선 완료 테스트가 아님)
python -B scripts/review_probes.py
```

실행은 내장 Python 3.11.9를 사용합니다. 개발 검증은 Python 3.11 이상·Ruff·Node.js·PowerShell·Git이 필요하며 이 PC에서 확인했습니다. 검사기는 빠진 도구를 성공으로 처리하지 않습니다.

Codex 설정은 `.codex/`에 있습니다. 이 프로젝트 폴더를 작업 루트로 열고, Codex의 훅 검토 화면(`/hooks`)에서 새 정의를 신뢰해야 자동 실행됩니다. 이 대화의 시작 폴더는 상위 `D:\배포`이므로 현재 대화에 새 프로젝트 설정이 자동 적용되었다고 단정하지 않습니다. Git `pre-commit`은 로컬 저장소에 연결되어 있습니다.

실사용 시작 파일은 [LoadMonitor25-UI.bat](LoadMonitor25/LoadMonitor25-UI.bat)입니다. 실행 전 개인 `config/config.json`을 설정합니다. Git으로 새로 받은 경우 `config.default.json`을 `config.json`으로 복사합니다. 이번 작업에서는 실제 수집·Copilot·팀 업로드를 실행하지 않았습니다.

개발 저장소는 `phyksw/loadmon`의 `lm25` 브랜치입니다. 2026-09-09 초기 준비본 이후의 변경과 검증 결과는 [목적 재검토 기록](docs/LM25_REASSESSMENT.md)과 Git 이력에서 확인합니다.
