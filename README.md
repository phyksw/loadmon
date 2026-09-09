# LoadMonitor25 개발 프로젝트

LM24 풀패키지에서 LM25 작업본을 만들고, 린트·훅·분야별 서브에이전트·검증 절차를 갖춘 프로젝트입니다. 현재 단계는 **개발 기반 구축과 목적 중심 검토**이며, LM25 제품 기능 개선을 모두 마친 배포본은 아닙니다.

목적은 활동 흔적에서 업무 투입을 분석하고, 과제·담당 업무·워크플로우를 정리해 검증 가능한 AI 자동화 후보를 찾는 것입니다. 전체 검토에 따른 현재 우선순위는 **측정·제외 기준 → 업무·근거 식별 → 동일 실행의 개인·팀 집계 → 현장 검증**입니다. 기능의 범위는 목적에 맞지만 정량 의사결정에 사용하기 전 아래 검토의 핵심 결함을 개선해야 합니다.

## 구성

| 위치 | 역할 |
|---|---|
| `LoadMonitor25/` | 현재 개발 대상. LM25 실행 파일명·배포 도구·내장 Python 포함 |
| `LoadMonitor24/` | 수정하지 않는 원본 비교용 기준선 |
| [전체 기능 설계 검토](docs/LM25_FULL_DESIGN_REVIEW.md) | 현재 종합 판단, 영역별 기능표, 우선순위와 완료 기준 |
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

소스는 로컬 Git 저장소에 준비되어 있으며 자동 커밋·원격 연결·배포는 하지 않았습니다.
