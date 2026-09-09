# LM25 개발·검증·훅

## 린트와 검증

`python -B scripts/quality.py --quick`은 LM25·프로젝트 Python 전체 Ruff, Python/JSON/TOML 문법, BAT/PS1 인코딩·줄바꿈, PowerShell 파서, Python이 실제로 내보내는 PAGE/TEAM_PAGE JavaScript를 검사합니다. `ui/app.py`도 항상 포함합니다.

`--full`은 위 검사와 함께 TEMP의 코드·배포 기본설정 복제본에서 필수 파일, FILES.txt 크기·CRC, 기존 7관문 및 `tests/` 회귀를 실행합니다. 실제 수집·UI 서버·Copilot·업로드는 시작하지 않습니다. 개인 `config.json`과 데이터/보고서는 읽지 않습니다. `Test-Project.ps1`은 full 실행과 로그 저장용 진입점입니다.

프로그램 파일 수정 후 다음 명령으로 목록을 갱신합니다. 훅이 파일을 자동수정하지는 않습니다.

```powershell
.\LoadMonitor25\python\python.exe -B .\LoadMonitor25\tools\update_files.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Project.ps1
```

## 연결한 훅

| 훅 | 동작 |
|---|---|
| Codex `PostToolUse` | Bash/apply_patch/Edit/Write 후 소스 해시가 바뀌면 quick 검사. 실패 근거를 모델에 돌려주며 도구 결과를 버리지 않음 |
| Codex `Stop` | 완료 전 full 검사. 실패하면 수정하도록 한 번 이어가고, 다시 실패하면 경고를 남겨 무한 반복 방지. 실패를 통과로 표시하지 않음 |
| Git `pre-commit` | 개인/생성 파일 스테이징 거부. Git 인덱스의 전체 스냅샷을 TEMP로 내보내 full 검사. 작업 폴더만 고치고 인덱스에 오류를 남긴 부분 스테이징도 검출 |

Codex 캐시는 `.codex/.state/`에 소스 해시와 통과 여부를 저장합니다. 데이터/보고서/개인 설정/프로필을 해시에 넣지 않고 검증기와 같은 파일 목록을 사용합니다. 검사 도중 다른 에이전트가 코드를 바꾸면 성공을 캐시하지 않습니다. 같은 코드가 이미 통과한 경우만 검사를 생략합니다. 도구 설치 상태를 바꾼 뒤에는 `quality.py --full`을 직접 실행하세요.

`scripts/Install-Hooks.ps1`은 이 저장소의 `core.hooksPath=.githooks`만 설정합니다. 개인 전역 Git 설정이나 상위 폴더의 기존 훅은 바꾸지 않습니다. Git 훅에는 외부 전송이나 자동 커밋 기능이 없습니다.

## Codex 자동 적용 범위

프로젝트는 `.codex/config.toml`, `.codex/hooks.json`, `.codex/agents/*.toml`을 사용합니다. 새 설정을 쓰려면 `D:\배포\_gpt`를 작업 루트로 엽니다. 시작 폴더가 `D:\배포`인 기존 대화에 하위 프로젝트 설정이 즉시 반영되었다고 가정하지 않습니다.

Codex는 새 훅 정의를 신뢰하기 전 자동 실행하지 않습니다. `/hooks`의 검토·신뢰 절차가 필요합니다. 이번에는 정의 작성, 직접 이벤트 입력 검증, Git 훅 설치를 수행하며 신뢰 저장소를 임의로 수정하거나 우회하지 않습니다. 공식 근거: [Hooks](https://learn.chatgpt.com/docs/hooks).

역할 파일은 모델·권한 설정을 상속하며 최대 작업자 수는 본체 제외 3명입니다. [역할과 호출 예](SUBAGENTS.md), [공식 Subagents 형식](https://learn.chatgpt.com/docs/agent-configuration/subagents)을 참고합니다.

## 의존성과 한계

- 앱 실행: 동봉 CPython 3.11.9.
- 검사: 시스템 Python 3.11 이상, Ruff(준비 시 0.16.3), Node.js, Windows PowerShell, Git.
- 새 PC에서 Ruff가 없으면 개발 Python에 `python -m pip install ruff==0.16.3`으로 설치합니다. 실행용 내장 Python에는 pip를 추가하지 않습니다.
- Node 없이 자체 문자열 검사만으로 JavaScript 정상이라고 판정하지 않습니다.
- `review_probes.py`는 기존 제품 문제를 재현합니다. `issue_reproduced=true`는 개선 성공이 아니며 full 통과 테스트에 포함하지 않습니다.
