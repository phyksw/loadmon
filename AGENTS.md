# LM25 프로젝트 작업 지침

## 목적과 기준

- 사용자 지시를 우선한다. 현재 개발 대상은 `LoadMonitor25/`이다. `LoadMonitor24/`와 `docs/BASELINE.json`은 최초 ZIP 기준선이며 수정하지 않는다.
- 먼저 `README.md`, `docs/LM25_PLAN.md`, `docs/DEVELOPMENT.md`를 읽는다. 이전 목적과 이력은 `docs/PROJECT_CONTEXT.md`, 최초 검증은 `docs/VERIFICATION.md`에 보존한다.
- 목표는 활동 근거에서 신뢰도와 한계를 드러내는 업무 투입 분석, 추적 가능한 업무 흐름, 검증 가능한 자동화 후보를 제공하는 것이다.
- AI가 연결한 업무의 전체 MM을 절감량이라고 부르지 않는다. 총 투입시간 추정·과제별 가중 배분·AI 적합도·예상 절감량을 구분한다.

## 분담과 완료 조건

- 역할은 `.codex/agents/`와 `docs/SUBAGENTS.md`를 따른다. 측정/수집은 `lm25_measurement`, 업무 식별·AI 근거는 `lm25_workflow`, 수치·화면은 `lm25_reporting`, 독립 검증은 `lm25_quality`에 맡긴다.
- 독립 작업은 병렬로 처리하되 작업자는 최대 3명이다. 부모가 변경 파일의 단독 소유자를 정하고 같은 파일 동시 편집을 피한다. 최종 검토는 구현자와 다른 사람이 수행한다.
- 작은 수정에도 불필요하게 모든 역할을 호출하지 않는다. 각 위임에 대상·완료 조건·허용 파일·검증 범위를 명시한다. 확정 결함과 가설을 구분해 파일:행, 재현, 영향, 해결안, 검증 결과로 보고한다.
- 편집 뒤 `python -B scripts/quality.py --quick`, 완료 전 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Test-Project.ps1`을 실행한다. 이미 통과한 같은 코드의 검사를 이유 없이 반복하지 않는다.
- 린트 성공을 제품 품질 검증으로 대신하지 않는다. 변경한 행동을 검증하는 합성 사례를 사용한다. 알려진 제품 결함과 통과한 기반 검사를 분리해서 보고한다.

## 데이터와 동작

- 원본 설치, 실제 `data/`, `report/`, `teamdata/`, 로그인 프로필과 개인 설정을 시험용으로 삭제·덮어쓰기·복사하지 않는다. 수정은 이 프로젝트의 위임된 파일에서 한다.
- 기능 검증은 TEMP의 코드·기본설정·합성 자료 복제본에서 수행한다. 실제 수집, UI/팀 서버, Copilot, 작업 스케줄러, 업로드는 작업 범위에 필요한 경우에만 실행한다.
- 시간/MM은 근거와 산식에서 계산한다. 업무 성격/과제/담당 업무/활동 유형을 구분하고, LM24의 사용자 상위 지정·혼재 표시·제약 클러스터링을 보존한다.
- AI 근거는 해당 업무·기간의 신호에 연결되어야 한다. 잘못된 근거나 미확정 판정을 조용히 확정값으로 채우지 않는다. 실제 외부 연결 검증 없이 Copilot·Outlook·Teams 성공을 주장하지 않는다.

## 파일과 배포

- 프로그램 BAT는 CP949+CRLF, PS1은 UTF-8 BOM+CRLF를 유지한다. HTML 안 JS는 Python 해석 후 브라우저에 전달되는 문자열로 검사한다. Git 훅은 LF를 사용한다.
- 프로그램 변경 후 `LoadMonitor25/python/python.exe -B LoadMonitor25/tools/update_files.py`로 `FILES.txt`를 갱신한다. 새 배포 파일은 `자가점검.py`의 NEED 목록에도 추가한다.
- 배포 ZIP은 `LoadMonitor25/tools/Make-Package.ps1`로 만든다. 개발용 루트 전체를 압축하거나 실데이터를 저장소에 넣지 않는다. 배포/업로드 완료는 실제로 수행한 경우에만 말한다.
- 훅은 검사만 하며 파일 자동수정·자동 add/commit·정책 완화를 하지 않는다. Codex 훅 신뢰 설정을 임의로 우회하지 않는다.
