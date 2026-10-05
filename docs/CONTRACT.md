# LM27 통합 계약 (CONTRACT.md)

| 항목 | 내용 |
|---|---|
| 판 | v1.0.1 (2026-10-05) — 설계 확정, 구현 전. v1.0.1 = 반증 점검 보정(§10.O X-300~X-317) |
| 지위 | **단일 진실 원천.** 이 문서와 명세가 다르면 이 문서가 이긴다. 명세는 상세 근거다 |
| 제품 | LoadMonitor27(LM27) · 트리 `D:\배포\loadmon27` · 브랜치 `lm27` · 파이썬 패키지 `lm27` · 배포 이름 `LoadMonitor27\` · 패키지 `LoadMonitor27_풀패키지_<시각>.zip` |
| 독자 | LM27 의 모든 코드(`lm27\**`, `collect\**`, `web\**`, `tools\**`, `tests\**`) 구현자와 심사자 |
| 근거 | 명세 10종(COLLECTION · COLLECT_MAIL · COLLECT_TEAMS · COLLECT_PC · PRIVACY · COPILOT_BRIDGE · TEAM_AND_BUNDLE · WORKTIME_METHOD · HIERARCHY · REPORTS), 오케스트레이터 결정 메모 v1·v2, 사용자 원 요구 |
| 사람용 구조 | `docs\ARCHITECTURE.md` |
| 자리표시자 | 본인 홍길동 · 동료 김철수 · 과제A~F(P-0007 등) · 고객사A(C01) · 협력사(V01) · example.com |
| 별개 프로젝트 | `D:\배포\LM26`(다른 도구, 127.0.0.1:8765~8767)과 이전 판 폴더(`loadmon2x`)는 읽기 전용. 이름·포트·작업 이름을 겹치지 않는다 |

명세 약칭: **C** COLLECTION · **CM** COLLECT_MAIL · **CT** COLLECT_TEAMS · **CP** COLLECT_PC · **P** PRIVACY · **B** COPILOT_BRIDGE · **TAB** TEAM_AND_BUNDLE · **W** WORKTIME_METHOD · **H** HIERARCHY · **R** REPORTS · **결정** 결정 메모(§10 v2 포함).

---

## 0. 우선순위 규칙

### 0.1 순서

1. **사용자 원 요구와 운영 원칙**(결정 §1·§2): 실명·계정·이메일·사내 코드네임 금지, 사용자 대신 로그인 금지, 다른 사용자에게 수동 조작 요구 금지, 팀 서버 기본 주소 `http://10.115.147.68:9310` 고정(바꾸는 '옵션'만), 문서화·지원되는 사용자 인터페이스만 읽기.
2. **이 문서(CONTRACT.md).** 배치·ID·설정 키·코드·진입점·rc·인코딩·관문, 그리고 §10 에서 정한 해소 결정.
3. **결정 메모.** §10 v2 가 앞 절보다 우선한다. 결정 메모 원문은 docs 밖(작업 폴더)에 있으므로, 구속 조항은 §0.4 에 옮겨 적었다. 명세에 나오는 `docs/_decisions.md` 는 '이 문서 §0.4 와 결정 메모 원문'으로 읽는다.
4. **소유 명세**(§0.2 표). 자기 소유 범위 안에서만 정본이다.
5. **그 밖 명세.** 소유 범위 밖 서술은 참고다.

명세 안의 '이 문서가 우선한다'·'COLLECTION 이 이긴다' 같은 선언은 §0.2 의 소유 범위 안에서만 효력이 있다.

### 0.2 소유 표

| 영역 | 정본 명세 | 이 문서가 덮어쓴 것 |
|---|---|---|
| 수집 공통 의미: 경로 ID, 커버리지 상태, 사유 코드의 뜻, 수집기 rc, 빈칸 계획기, msg_key 병합 규칙, 페르소나 시험 | C | 배치·파일 형식·pc_id·레코드 열 이름(§1·§3·§4) |
| 메일·일정 수집기 | CM | 저장 열, 파이프 호출, Edge 프로필·포트 |
| 팀즈 수집기 | CT | 저장 열, 상주 방식, 화행 소유 |
| PC 수집기·프로그램 카탈로그·이벤트 대응 | CP | 에이전트 배치·설치 방식·키 위치 |
| **저장 열(열 허용 목록)**, 정제 규칙, HMAC 키, 게이트 G1~G4, 감사, 정제 파이프 | P | 파이프 출력 대상·연결자·제어 줄(§7.3), 일부 열 추가(§3.2), `check_team_payload` 의 spec 필수(§2.2) |
| 운반 번들·에이전트 배치·세그먼트·manifest·pc.json 그릇·팀 묶음 필드·팀 서버·취합 | TAB | 설정 키 표기, 일부 필드 이름(§3.18) |
| 코파일럿 L0~L3, 단계 틀, ai_in/ai_out, 수동 붙여넣기 | B | AI 답 저장소 위치, 프로필 공용 규칙 |
| 단계 **내용**: task_label·taxonomy_bootstrap·taxonomy_consolidate | H | — |
| 단계 **입력**: workflow_label·agentic_match·subagent_review·review_text | R | — |
| 시간 모델: 봉투·단위업무·귀속·MM·확인 큐 Q01~Q18 | W | 결과 위치·시간 단위·입력 대응(§3.14·§10) |
| 업무 계층·분류·레지스트리 의미·어휘 코드·DOMAIN_META | H | 영역 색 값(R 의 검증값) |
| 화면·보고서·분석층(마이닝·리뷰·동료·온톨로지·agentic·서브에이전트·측정 품질)·단계 유형 어휘 | R | — |
| **정규화**(화행·병합·토큰 파생·근태 대응), **분석 파이프라인**, 설정 레지스트리, 경로 로더, 진입점, 관문 | **이 문서** | 해당 명세가 아직 없다. 이 문서가 임시 정본이다(§12 미결) |

### 0.3 해석 규칙

- **R0-1** 한 명세 안에서 인터페이스 절(부록 A, H §12.2, R 부록 A 등) > 본문 의사코드 > 예시.
- **R0-2** 예시 값이 형식 정규식과 다르면 형식이 이긴다(예: `"PCH#3f9a"`, 7자리 kid, `P012`, `ws:W031` 은 모두 형식 위반 예시).
- **R0-3** 절 번호 참조가 틀렸으면 제목으로 찾는다(예: CM 의 '§13 미결' → §16, CP 의 '미결(§15)' → §17).
- **R0-4** `LM26`·`loadmon26`·`lm26` 표기는 LM27 로 읽는다. 단 별개 프로젝트 `D:\배포\LM26` 을 가리키는 문장은 예외다.
- **R0-5** 설정 키·경로·ID 는 이 문서의 이름만 쓴다. 명세 표기는 §5.4 개명표로 대응한다.
- **R0-6** 명세가 '미정'으로 남긴 값은 이 문서의 값을 쓴다. 여기에도 없으면 §12 미결이다.
- **R0-7** 이 문서가 명세의 함수·필드를 폐지하면, 구현은 폐지된 이름을 별칭으로라도 남기지 않는다(죽은 이름 금지).

### 0.4 결정 메모 구속 조항 요약

| # | 조항 | 결정 절 |
|---|---|---|
| D-1 | 동봉 CPython 3.11 embeddable, 표준 라이브러리만. `python311._pth` 가 루트를 sys.path 에 넣지 않으므로 진입점이 스스로 넣는다 | §0 |
| D-2 | 수집기는 Windows PowerShell 5.1 또는 파이썬 ctypes. .ps1 = UTF-8 BOM + CRLF, .bat = CP949 + CRLF + `>nul chcp 949`, .py/.md/.json = UTF-8 LF, `.gitattributes` 는 `* -text` | §0 |
| D-3 | 허용 경로: 클래식 Outlook COM, Windows Search 색인, 본인 전용 Edge 프로필 CDP(127.0.0.1), Teams 창 UIA, Office MRU·Recent, 사용자 권한 이벤트 로그, Win32 전경·유휴·세션, 지정 폴더 mtime, 본인 git log, 반입 파일, 수동 기록. 금지: Graph, 앱 내부 캐시(IndexedDB·LevelDB·wpndatabase.db·OST/PST), 숨김 폴더, 자격 증명, 관리자 권한, 정책 우회 | §2 |
| D-4 | 큰 흐름: 수집 → 운반 번들 → 정제(저장 전) → 병합 → 시간 추론 → 분류 → 분석 → 개인 보고서 → 팀 업로드 → 팀 서버 | §3 |
| D-5 | 상주 부분은 `%LOCALAPPDATA%\LoadMonitor27\agent\`, 운반 번들은 프로그램 폴더 `data\` 의 pc_id 별 불변 세그먼트. 다른 pc_id 자료는 rename·이동 금지. 코파일럿 Edge 프로필은 번들 밖 | §3 |
| D-6 | 계정 단위 자료의 기간 전체 백필은 백필 PC(기본 클라우드PC)에서 한 번. msg_key 로 병합. '첫 성공에서 멈추는 사슬' 금지, 역할 분담 + 일자×출처 커버리지 원장 | §3 |
| D-7 | '불가'는 서로 다른 날 2회 이상 + 수송 실패 아님일 때만 확정, 해제 가능 | §3 |
| D-8 | 업무 영역 5종(+미분류) / 과제 / 역할 업무 / 단위 업무 / 업무 유형 | §4 |
| D-9 | 근무 봉투(5분 슬롯 합집합) + 귀속(Σ귀속 = 봉투, 날마다 assert). 리드타임 ≠ 투입. 코파일럿은 시간·MM 을 계산하지 않는다. date-only·요약은 시간 근거 아님 | §5 |
| D-10 | 브리지 5계층, 입력 8,000자·답 5,000자 기본, fail-closed, 항목 단위 저널, 수동 붙여넣기 정식 지원, 전송 직전 재검사 | §6 |
| D-11 | 수집기 경계 정제, 열 허용 목록만 저장, 회귀 말뭉치 관문 | §7 |
| D-12 | 보고서 디자인 LM20 언어, 외부 CDN 금지, 관측/추정 구분 | §8 |
| D-13 | 관문 1일차부터: 시간 보존, 개인=팀, PII 카나리아, 단일 설정 레지스트리, 단일 로더, 제어문자 금지, 인코딩, 합성 E2E, 패키지=커밋 | §9 |
| D-14 | MS 경로 우선순위: 색인 항상 + COM 정밀 → 빈칸만 OWA(보낸 편지함은 항목을 열어 분 단위, 받은 메일은 날짜만) → 코파일럿 존재 증인 → 반입. COM A단/B단 분리. 구조적 공백은 0건이 아니다 | §10.1 |
| D-15 | 팀즈 '놓친 활동' 알림 메일 = 팀즈 수신 존재 간접 증거(시간은 상한으로만). 코파일럿 계정 등급·Work 탭·웹 근거 탐침 | §10.1 |
| D-16 | 방향 축 S1i·S1o·E1o·E1i, 다대다 짝짓기, E3c, 자동 저장, 솔버 기계 시간, 사적 차감은 봉투 마지막 단계, 무증거 슬롯은 직접 증거 비례 또는 버킷 | §10.2 |
| D-17 | zoneinfo.ZoneInfo 금지. 공휴일은 근거 URL·확인일이 있는 calendar.json. 관문: 2026-09·2026-10 평일 각 20일 | §10.3 |
| D-18 | manifest = 세그먼트 sha256 집합(멱등 합집합). 커버리지 원장·todo 는 파생물. 설치 전용 진입점. 가명 키 2층. 업로드 대기 자동 전송. 서버 SO_EXCLUSIVEADDRUSE | §10.4 |
| D-19 | 온톨로지 닫힌 관계 어휘, 서브에이전트 원장 수치 판정, agentic 카탈로그 = 레지스트리 agents[] | §10.5 |

### 0.5 변경 절차

- 계약 변경은 이 문서의 판을 올리고(v1.x), §10 에 행을 더하고, 영향받는 명세를 '반영 요청' 열에 적는다. 관문(§11)도 같은 커밋에서 갱신한다.
- 명세 문구는 이 문서와 맞추어 갱신하되, 갱신 전이라도 구현은 이 문서를 따른다.
- 구현 코드·시험·화면 문구는 이 문서의 이름(경로·키·코드·필드)만 쓴다.

---

## 1. 트리 배치

### 1.1 프로그램 폴더(ROOT) — 폴더째 이동

`<ROOT>` = 개발 시 `D:\배포\loadmon27\`, 배포 시 `LoadMonitor27\`.

```
<ROOT>\
├─ LoadMonitor27.bat                 로컬 앱(화면) 기동 — 기본 진입
├─ LoadMonitor27-수집.bat            [수집] = collect --auto (무질문)
├─ LoadMonitor27-에이전트설치.bat    agent install --only (설치 전용, 5초 안팎)
├─ LoadMonitor27-이동준비.bat        move-prepare (도우미 PS 를 %TEMP% 사본으로 띄움)
├─ LoadMonitor27-팀서버.bat          team-server
├─ lm27_cli.py                       단일 진입점: lm27 <명령> (§7)
├─ lm27_pipe.py                      정제 파이프 진입점(PS 수집기·에이전트용, P §3.5)
├─ lm27\                             파이썬 패키지(§2)
├─ collect\                          수집기 스크립트(.ps1 / .py) — §2.17
│   ├─ agent\                        agent.ps1 · harvest.ps1 · Register-Agent.ps1 (ps 구현·작업 등록)
│   └─ move\                         Prepare-Move.ps1
├─ web\
│   ├─ common\                       lm27.css · lm27charts.js · lm27ui.js · icons.svg (렌더러 한 벌)
│   ├─ app\                          index.html · app.js · report.js (로컬 앱·자기완결 보고서)
│   └─ team\                         index.html · team.js · admin.html (팀 대시보드·관리)
├─ config\
│   ├─ settings_registry.json        설정 키 선언 단일원(§5) — 배포 포함
│   ├─ calendar.json                 달력 내장본(확인된 해만, §3.21) — 배포 포함
│   └─ config.json                   개인 덮어쓰기(비밀 없음, 폴더와 동행, 패키지 제외)
├─ tools\                            lint.ps1 · hook_check.py · lm27_selftest.py · calibrate.py ·
│                                    bridge.py · bridge_trace_summary.py · check_contrast.py
├─ tests\                            privacy\ time\ hier\ bridge\ report\ web\ bundle\ team\ collect\ agent\ e2e\ fixtures\
├─ docs\                             CONTRACT.md · ARCHITECTURE.md · 명세 10종
├─ python\                           동봉 CPython 3.11 embeddable(수정 금지, _pth 그대로)
├─ data\                             운반 번들 + 개인 자료(§1.2, .gitignore)
└─ out\                              개인 보고서 내보내기(§1.2, .gitignore)
```

- 모든 bat 은 `pushd "%TEMP%"` 로 작업 폴더를 옮긴 뒤 `"<ROOT>\python\python.exe" "<ROOT>\lm27_cli.py" <명령>` 을 부른다(폴더 잠금 방지, TAB §1.9). 화면은 `pythonw.exe` 로 띄운다(R §2.3.1).
- `collect\` 의 파이썬 수집기는 스크립트 첫 줄에서 `<ROOT>` 를 sys.path 에 넣는다(D-1).

### 1.2 `data\` 와 `out\`

```
<ROOT>\data\
├─ bundle.json                       lm27.bundle/1 (bundle_id · person_key · created_on_pc)
├─ .bundle.lock                      번들 쓰기 잠금(msvcrt.locking, TAB §1.9)
├─ pc_aliases.json                   논리 PC 별칭(추가 전용, TAB §1.8)
├─ pcs\<pc_id>\                      ★ 번들 본체 — 그 PC 만 쓰고 다른 PC 는 읽기만
│   ├─ pc.json                       PC 레지스트리·능력 기록(lm27.pc/1)
│   ├─ manifest.json · manifest.prev.json   (lm27.manifest/1)
│   ├─ move_ready.json
│   ├─ seg\<kind>\<seq6>-<inst8>-<t0>-<t1>-<sha8>.jsonl.gz   kind 8종 + privacy_audit
│   └─ quarantine\ (+ tombstones.json)
├─ keys\                             privacy_keyring.json · secrets.json  — 폴더와 동행, 모든 반출 제외
├─ local_only\                       person_dir.json · corresp_domains.json · ad_lists.json · private_chats.json ·
│   │                                redact_overlay.json · person_alias.json · tag_feedback.json
│   └─ hier\                         registry_local.json · title_cache.json · proposals.json · corrections.jsonl ·
│                                    rules_learned.json · merge_log.jsonl (+ .bak)
├─ team\                             registry.json(pepper 포함, 반출 금지) · registry.etag · overrides.json
├─ outbox\team\{pending,sent,failed,dropped}\   lm27_team_bundle_<period_key>_<sha12>.json (+ .meta.json · .lease)
├─ ai\                               ★ AI 답 보존소(재생성 불가, 번들 합치기 때 합집합)
│   ├─ store\<stage>.items.jsonl     항목 커밋(B §7.8)
│   └─ runs\<run_id>\                <stage>.jsonl(저널) · <stage>.result.json(결과 봉투) · capabilities.json
├─ import\                           반입 폴더(EML·ICS·CSV, 원본 무변경)
├─ derived\                          ★ 언제든 재생성
│   ├─ coverage_ledger.jsonl · teams_coverage.jsonl · todo.json · verify_cache.json
│   ├─ collect\<run_id>\stage_result_<stage>.json
│   ├─ ai_in\<stage>.jsonl · ai_out\<stage>.json
│   └─ analysis\current.json · analysis\<run_id>\{run_status.json, time\, hier\, report\}
└─ logs\

<ROOT>\out\personal\<from>_<to>_<run8>\   report_full.html · report_redacted.html · report_model*.json ·
                                          csv_full\ · csv_redacted\ · manifest.json   (run8 = run_id 끝 8자)
```

**용어 정의(이 문서 전체에서 같은 뜻).**

| 용어 | 범위 | 성질 |
|---|---|---|
| **번들** | `data\bundle.json`, `data\pc_aliases.json`, `data\pcs\**` | 세그먼트 sha256 집합. 두 번들 합치기는 합집합이며 멱등이다(D-18) |
| **번들 합치기 대상** | 번들 + `data\ai\store\**` | AI 답은 (stage, ck) 별 최신 커밋을 남기는 합집합 |
| **폴더와 동행하지만 반출 금지** | `data\keys\`, `data\local_only\`, `data\team\registry.json`, `config\config.json` | manifest·세그먼트·팀 묶음·코파일럿·오프라인 내보내기·패키지 zip 어디에도 넣지 않는다 |
| **파생물** | `data\derived\**` | 지워도 다음 실행이 다시 만든다. 병합 뒤 재생성 |

### 1.3 `%LOCALAPPDATA%\LoadMonitor27\` — PC 에 남는 것

```
%LOCALAPPDATA%\LoadMonitor27\
├─ agent\                            상주 에이전트(평면, install_id 는 agent.json 안)
│   ├─ agent.json · agent_config.json · context_cache.json · heartbeat.json
│   ├─ person_dir_delta.json · export_log.jsonl
│   ├─ keys\subkeys.json             용도별 하위 키만(주 키 없음)
│   ├─ bin\<agent_ver>\              실행 사본(최대 2판). ROOT 를 참조하지 않는다
│   │   ├─ py311\                    python.exe · pythonw.exe(동봉 파이썬 사본)
│   │   ├─ lm27\                     __init__.py · paths.py · catalog.py · util\ · privacy\ · store\ · agent\ ·
│   │   │                            normalize\{__init__.py, cues.py}(정제 훅 act_cues) · bundle\{__init__.py, ids.py}(pc_id 재계산)
│   │   ├─ lm27_pipe.py · agent_main.py
│   │   └─ ps\                       agent.ps1 · harvest.ps1 · Get-EventActivity.ps1 · Get-FileActivity.ps1 ·
│   │                                Get-OfficeMru.ps1 · Get-RecentFiles.ps1 · Get-TeamsWindow.ps1
│   ├─ store\<pc_id>\evidence\<kind>\<src>\YYYYMM\YYYYMMDD.jsonl.gz   로컬 원장(쓰기 UTC 날짜, gzip 멤버 덧붙이기)
│   ├─ store\<pc_id>\raw_cursor.json · store\<pc_id>\exe_meta.json
│   ├─ store\privacy_audit\YYYYMM\YYYYMMDD.jsonl
│   ├─ run\                          stop.flag · harvest_now.flag · harvest_done.json · .harvest.lock
│   ├─ logs\agent_YYYYMMDD.log      예외 유형·시각·건수만
│   └─ copilot_manual\ (+ inbox\)   수동 붙여넣기 프롬프트(TTL 7일, B §10)
├─ edge_copilot\                     전용 Edge 프로필(역할 bridge·owa·teams_web 공용, 백필 PC 만)
├─ bridge\                           session.lock.json · profile_id.txt · bridge_profile.json · trace.jsonl ·
│                                    probe_last.json · rawcap\ · diagnose\
├─ ui\                               ui_server.json · ui_start_error.txt · logs\ · jobs\
└─ teamserver\                       팀 서버 저장소 기본값(§1.4, 팀 서버 PC 만)
```

- 작업 스케줄러 이름 `LM27-<install_id>`(작업은 하나, 감독 루프), 뮤텍스 `Local\LM27-<install_id>-agent`.
- 작업 Action 은 `agent\bin\<ver>\py311\pythonw.exe agent\bin\<ver>\agent_main.py --install-id <id>`(py 구현) 또는 `powershell.exe … -File agent\bin\<ver>\ps\agent.ps1 -InstallId <id>`(ps 구현), WorkingDirectory = `agent\`.
- bin 사본에 든 모듈은 **사본 안 모듈과 표준 라이브러리만** import 한다(사본에 없는 `lm27.config`·`lm27.hier`·`lm27.time` 등을 최상위·지연 어느 쪽으로도 부르지 않는다 — ImportError 를 삼키는 것도 금지, L-06). 그래서 `lm27\normalize\cues.py`(정제기 훅)와 `lm27\bundle\ids.py` 는 표준 라이브러리·`lm27.util` 만 쓴다(X-305).

### 1.4 팀 서버 저장소

`teamServer.storeDir`(비면 `%LOCALAPPDATA%\LoadMonitor27\teamserver\`). 구조는 TAB §3.7 그대로: `store.json`, `secrets\pepper.json`, `registry.json`, `registry_history\vNNNN.json`, `roster.json`, `members\<person_key>\{current.json, current.json.bak, bundles\<period_key>__<sha12>.json}`, `inbox\{done,rejected}\`, `out\gen_<N>\{team_data.json, team_report.html, team_report_share.html, team_tables\, result.json}`, `out\current.json`, `run\{server.lock, server.json, port_diag.json, inbox_seen.json, firewall_diag.json}`, `logs\`. 운영 위치는 옮기지 않는 별도 폴더를 권장한다.

### 1.5 임시 파일

| 파일 | 위치 | 수명 |
|---|---|---|
| 원자 쓰기 조각 | `<path>.<pid>.<thread>.<rand4>.part` | 쓰기 직후 os.replace, 실패 시 삭제 |
| 이동 도우미 | `%TEMP%\lm27_move_<rand>.ps1` | 이동 끝까지 |
| schtasks XML | `%TEMP%` (UTF-16 LE BOM) | 등록 직후 삭제 |
| 이름 바꾸기 시험 | `<ROOT>.__mvtest_<rand>` · `data\.probe_<rand>` | 시험 직후 |

원문(메일 본문·창 제목·대화)은 어떤 임시 파일에도 쓰지 않는다. 예외는 B §9.5 의 두 경우(수동 붙여넣기 프롬프트, 진단용 rawcap — 기본 꺼짐)뿐이며 둘 다 게이트를 통과한 텍스트다.

---

## 2. 모듈 지도

표기: `함수(인자) -> 반환`. '소유 §' 는 상세 근거 절이다. 명세들이 다른 경로를 제안한 경우의 결정은 각 표 아래 '경로 결정'과 §10 에 적었다.

### 2.1 루트 진입점과 공용 하위층 — `lm27\`(이 문서 소유)

| 파일 | 책임 | 공개 함수 | 소유 § |
|---|---|---|---|
| `<ROOT>\lm27_cli.py` | 단일 진입점. 첫 줄에서 ROOT 를 sys.path[0] 에 넣고 `lm27.cli.main()` 호출. 그 밖 코드 없음 | (스크립트) | 이 문서 §7 |
| `<ROOT>\lm27_pipe.py` | 정제 파이프 진입점. 자기 폴더를 sys.path[0] 에 넣고 `lm27.privacy.sanitize_stream.main(sys.argv[1:])` | (스크립트) | P §3.5 |
| `lm27\__init__.py` | 판 상수 | `LM27_VERSION = "0.1.0"` | 이 문서 |
| `lm27\cli.py` | 명령 분배(§7 표). 모든 명령은 rc 를 돌려준다 | `main(argv: list[str] \| None = None) -> int` | 이 문서 §7·§8 |
| `lm27\paths.py` | **경로 로더 단일원.** 모든 데이터 경로를 만든다. 다른 모듈은 경로 문자열을 조립하지 않는다 | `Paths(root: Path \| None)` · `.mode() -> "program"\|"agent"` · `.data()` `.bundle_json()` `.pcs()` `.pc_dir(pc_id)` `.seg_dir(pc_id, kind)` `.keys()` `.keyring()` `.secrets()` `.local_only()` `.hier_local()` `.team_dir()` `.registry_cache()` `.outbox(state)` `.ai_store(stage)` `.ai_run(run_id)` `.import_dir()` `.derived()` `.coverage_ledger()` `.teams_coverage()` `.todo()` `.collect_stage_results(run_id)` `.ai_in(stage)` `.ai_out(stage)` `.analysis(run_id)` `.analysis_current()` `.out_personal(from_, to, run_id)` `.logs()` · `.lad()` `.agent_dir()` `.agent_bin(ver)` `.store_dir(pc_id)` `.store_file(pc_id, kind, src, utc_date)` `.raw_cursor(pc_id)` `.privacy_audit_file(utc_date)` `.edge_profile()` `.bridge_dir()` `.edge_lock()` `.ui_dir()` `.teamserver_default()` | 이 문서 §1 |
| `lm27\config.py` | **설정 레지스트리 단일원.** `config\settings_registry.json` 선언 + `config\config.json` 덮어쓰기. 미등록 키 = 오류, 형 불일치 = 기본값 + 경고, 읽힌 키 기록 | `load_config(paths) -> Cfg` · `Cfg.__getitem__(key)` · `Cfg.used() -> dict` · `Cfg.hash() -> str` · `Cfg.agent_subset() -> dict` · `registry_meta(key) -> KeyMeta` | 이 문서 §5 |
| `lm27\util\fsx.py` | 쓰기 하위층 유일원(원자 쓰기·결정적 gzip·정규 JSON 바이트·긴 경로) | `canon_bytes(obj) -> bytes` · `atomic_write(path, data, *, fsync=True)` · `append_line(path, line: str)` · `read_bytes(path)` · `read_json(path, default=None, *, want=dict)` · `gzip_bytes(raw)` · `sha256_hex(b)` · `longp(p)` · `utcnow_iso()` | TAB §0.3 |
| `lm27\util\tz.py` | 시간대(zoneinfo 금지). 수집 순간 오프셋은 ctypes `GetDynamicTimeZoneInformation`/`GetTimeZoneInformationForYear` | `capture_offset_min(utc_dt) -> int` · `fmt_offset(min) -> "+09:00"` · `parse_offset(s) -> int` · `to_local(ts_utc, off_min)` | 결정 §10.3 |
| `lm27\util\proc.py` | 자식 프로세스 실행·감시·종료(창 없음, `taskkill /T /F`, os.kill 금지) | `run_child(argv, *, timeout_s, stdin=None, env=None) -> ChildResult` · `spawn(argv, ...) -> Child` · `kill_tree(pid)` | C §8.4 |
| `lm27\util\events.py` | 표준 출력 이벤트(§8.6) 한 줄 JSON | `emit(ev: str, **fields)` · `Heartbeat(interval_s=30)` | 이 문서 §8.6 |

### 2.2 `lm27\privacy\` — 정제 단일 관문(P 소유, 16개)

| 파일 | 책임 | 공개 함수(요지) |
|---|---|---|
| `__init__.py` | 공개 API 재수출(분석·브리지·팀 코드는 여기만 import) | `RULES_VERSION="2026.10.0"` · `RULES_HASH` · `KINDS` · P §3.3 함수 전부 + **`forbidden_codes(s, gctx) -> list[str]`** · **`write_context_cache(agent_dir, sctx_cfg) -> str`** · **`self_name_set`**(이 문서가 추가 요청) |
| `sanitize.py` | ★ 수집기 facade(수집기가 import 할 수 있는 유일 모듈) | 재수출: `sanitize` · `sanitize_record` · `make_record_context` · `scan` · `SanitizedRow` · `RecordOutcome` |
| `rules.py` · `rules.lock.json` | 버전 고정 규칙(정규식·어휘·임계) | `credential_hit` · `luhn_ok` · `rrn_checksum_ok` · `brn_ok` · `plausible_korean_name` · `RX` · `CTX` |
| `detect.py` | `sanitize()` 본체 | `sanitize(text, field_name="text", ctx=None, max_len=None) -> SanitizeResult` · `subkey` · `keyed_hex` |
| `scan.py` | 치환 없는 탐지, 토큰 파생 | `scan(text, ctx=None) -> list[Hit]` · `tokens_of(masked, max_tokens=30) -> list[str]` |
| `classify.py` | 광고·공사·창 분류·방 성향 | `ad_score(m) -> (int, band, why)` · `private_score(...)` · `room_prior(st)` · `window_class(fg_exe, title, app_class, wctx) -> WindowVerdict` |
| `records.py` | 열 허용 목록 `SCHEMAS`, 봉인 | `sanitize_record(kind, raw, rc: RecordContext) -> RecordOutcome` · `resanitize_row(kind, row, ctx)` · `record_id(row, spec)` · `path_excluded(path, rc)` · `redact_rewrite(...)` |
| `keys.py` | 키링·하위 키·HMAC·문서군 정규화 | `keyed(kr, purpose, value, n=16)` · `who_key(kr, ident)` · **`doc_fam(name) -> str`**(문서군 정규화 — §4.3) · `doc_key(kr, name) -> "d"+16hex` · `peer_key(...)` · `load_keyring(data_dir, audit, *, create=False)` · `write_agent_subkeys(kr, agent_dir, audit)` · `load_agent_keys(agent_dir, audit)` |
| `gate.py` | G3 코파일럿 게이트·G4 팀 검사 | `gate_copilot(items, stage, gctx)` · `gate_text` · `gate_prompt_text(prompt, gctx)` · `check_team_label(s, gctx, max_len=40)` · `check_team_payload(payload, gctx, spec)` — **`spec` 필수**(호출자 `lm27.team.schema`·`build`·`server` 가 `TEAM_SPEC_V1` 을 넘긴다). `lm27.privacy` 는 `lm27.team` 을 import 하지 않는다(team.schema → privacy 방향만 — 순환·에이전트 사본 깨짐 방지, X-304) |
| `audit.py` | 감사 기록기 | `AuditSink.open(data_dir, pc_id, stage, src, agent_dir=None)` · `.add(counter, key, n=1)` · `.flush(**numbers)` |
| `context.py` | 정제·레코드·게이트 문맥 | `build_context(cfg, registry, local, kr)` · `make_record_context(root, src, pc_id, *, agent_dir=None, stage="collect", my_addrs=())` · `make_gate_context(sctx, cfg, kr, *, stage, audit, web_grounding=False)` · **`self_name_set(local, cfg, os_names=None) -> list[str]`**(본인 표시명 집합 단일원 — CT §4.4: `person_dir.json` 의 `self:true` 이름 + OS 표시명(`%USERNAME%`·LogonUI 표시명, 둘 다 없을 때만 디렉터리 표시명) + `collect.ownerAddress` 로컬부 + 고정어 `나`·`본인`·`you`·`me`, 변형 = 소문자·공백 제거·`님`/`씨` 접미 제거. `SanitizeContext.self_names` 와 수집기 `_in.self_names` 가 이 함수 결과 하나를 쓴다 — X-306). 프로그램 폴더 모드의 `make_record_context` 가 쓰는 유효 레지스트리 사전(X-247)은 `lm27.hier.registry.load_effective` 를 **함수 안에서 지연 import** 해 얻고, 에이전트 모드는 `context_cache.json` 만 쓴다(`lm27.privacy` 최상위에서 `lm27.hier`·`lm27.team` import 금지 — X-304) |
| `sanitize_stream.py` | 정제 파이프 본체. 제어 줄 `_meta`·`_cursor`(§7.3)는 레코드로 세지 않고, 출력 기록 성공(종료 0·2) 뒤에만 `_cursor` 를 `lm27.store.cursor.save_raw_cursor` 로 저장, 요약 줄에 `cursor_saved` | `main(argv) -> int` (종료 코드 §8.2) |
| `selftest.py` · `corpus\regress_v1.jsonl` · `schemas_v1.json` | 회귀 말뭉치 관문 | `run_selftest(corpus_path=None, *, update_lock=False) -> int` · `rules_hash()` |

### 2.3 `lm27\store\` — 로컬 원장 쓰기·읽기(이 문서 소유, TAB R-7·§1.6.7·P I2, 4개)

| 파일 | 책임 | 공개 함수 |
|---|---|---|
| `__init__.py` | 재수출 | — |
| `writer.py` | **SanitizedRow 를 받는 유일한 저장 지점.** 봉인 검사(`row._seal is records._SEAL` 아니면 TypeError). 쓰기 UTC 날짜 파일에 묶음 = gzip 멤버 1개, write+flush+fsync 후 닫기 | `SegmentWriter(paths, pc_id, kind, src)` · `.append(row: SanitizedRow)` · `.flush() -> int` · `.close()` |
| `reader.py` | 완전한 gzip 멤버까지만 읽기, 커서 이후 | `read_store_since(paths, pc_id, kind, src, cursor) -> (records, new_cursor, gap\|None)` · `iter_store(paths, pc_id, kind, src, d0, d1)` |
| `cursor.py` | 수집 증분 커서 `raw_cursor.json`(§3.10) | `load_raw_cursor(paths, pc_id) -> dict` · `save_raw_cursor(paths, pc_id, src, value)` — 그 `src` 키만 바꾼다. 잠금(`raw_cursor.json.lock`, msvcrt.locking, 10초) 안에서 읽기 → 교체 → `atomic_write`(에이전트 수확과 전경 수집이 동시에 써도 다른 src 커서를 잃지 않게 — X-301) |

경로 결정: P 의 'SegmentWriter = 저장소 명세 소유', CP 의 `lm27.store.append`, TAB 의 `append_member`·`read_store_since` 를 이 패키지 하나로 모은다. 번들 세그먼트는 `lm27.bundle.segment.write_segment` 만 쓴다(§10 X-175).

### 2.4 `lm27\agent\` — PC 상주 에이전트(TAB §1.6·CP §1·§3, 6개)

| 파일 | 책임 | 공개 함수 |
|---|---|---|
| `__init__.py` | — | — |
| `install.py` | 설치·판 올림·작업 등록·생존 판정·자동 복구·제거 | `ensure_agent(ident) -> dict`(rc 0/3) · `agent_health(ident) -> {registered, action_ok, hb_fresh, store_fresh, healthy}` · `register_task(ident)` · `request_harvest_now(ident, wait_s)` · `uninstall(ident, purge)` · `self_test_impl(impl) -> bool`(-TestSamples 3) |
| `main.py`(사본 진입 `agent_main.py`) | 감독 루프: 뮤텍스, 샘플(60초), 플러시(300초·120행), heartbeat, teams.uia 자식(300초), 수확 자식(6시간·요청 시) | `main(install_id) -> int` |
| `sampler.py` | py 구현 샘플러(ctypes: user32·wtsapi32·kernel32). PS 구현과 같은 원시 틱 | `take_sample(prev) -> RawTick` · `idle_sec(tick64, last_input) -> int` · `session_state() -> str` |
| `harvest.py` | 수확 자식 기동(이벤트·파일·MRU·Recent, ps 스크립트 → 파이프) | `start_harvest_child(ident, streams) -> Child` |
| `exemeta.py` | 미지 프로그램 메타(`exe_meta.json`, 정제 통과 값만, atomic_write) | `observe_exe(exe_path) -> ExeMeta` · `save_exe_meta(paths, pc_id, meta)` |

경로 결정: CP 의 `collect\sampler.py` → `lm27\agent\sampler.py`. CP 의 `Start-ActivitySampler.ps1` 은 ps 구현 `collect\agent\agent.ps1` 안으로 합친다. CT 의 `Start-TeamsSampler.ps1` 은 폐지(감독 루프가 teams.uia 를 부른다). CP 의 `Install-Agent.ps1` 은 `lm27 agent install --only` 로, `Register-Samplers.ps1` 은 `collect\agent\Register-Agent.ps1` 로 대체한다.

### 2.5 `lm27\collect\` — 수집 오케스트레이터(C §4~§9·TAB §1.7, 10개, 이 문서가 파일을 정함)

| 파일 | 책임 | 공개 함수 |
|---|---|---|
| `__init__.py` | — | — |
| `run.py` | [수집] 한 번의 흐름(TAB §1.7): 번들 확인 → 에이전트 확인 → 탐침 → 수확 요청 → 전경 수집기 → 내보내기 → 파생 재생성 → 대기 업로드 전송 | `collect_here(paths, cfg, *, mode="auto", since=None, until=None, pc_role=None, only=None, budget_sec=None) -> CollectResult` |
| `plan.py` | 단계 순서와 병렬(C §8.2), 역할(PC1·PC2·cloud)별 단계 표 | `stage_plan(roles, caps, only) -> list[Stage]` |
| `probe.py` | 능력 탐침 묶음 실행과 기록 | `probe_capabilities(paths, ident, cfg) -> ProbeResult` · `record_probes(pcdir, pr, loc)` |
| `rcmap.py` | 수집기 rc·파이프 종료 코드 → 원장 상태·todo 번역(§8.1·§8.2) | `cell_status(rc, reasons, counts) -> str` · `pipe_failure(code) -> (rc, reason)` |
| `watch.py` | 단계 감시: 30초 하트비트(생존)와 진전(커밋 수)을 따로 본다. 정체 15분·무진전 45분 → kill_tree | `watch(child, policy) -> WatchResult` |
| `stage_result.py` | 단계 결과 파일(§8.5) 원자 기록, finally 에서 | `write_stage_result(paths, run_id, stage, **fields)` |
| `ledger.py` | 커버리지 원장 재생성(파생) — 세그먼트·stage_result·pc.json 이력에서 | `rebuild_coverage(paths) -> int` |
| `todo.py` | 빈칸 계획기(파생) — 백필 PC 배정·'불가' 반영 | `plan_todo(paths, cfg) -> list[Todo]` |
| `diagnose.py` | 진단 리포트(PC 카드·출처 매트릭스·사유 분포) 모델 | `diagnose_model(paths) -> dict` |

### 2.6 `lm27\bundle\` — 운반 번들(TAB §8.2, 11개)

| 파일 | 공개 함수 |
|---|---|
| `__init__.py` | — |
| `ids.py` | `identify_pc() -> PcIdentity(pc_id, id_source, install_id, agent_ver, kind_guess, tz)` |
| `lock.py` | `BundleLock(paths, purpose, timeout_s)` (BundleBusy) |
| `segment.py` | `write_segment(pcdir, kind, ident, records, *, rules_ver, kid, src_from=None, src_to=None) -> dict` · `read_segment(path, expect_sha=None)` · `verify_segment(path) -> (ok, reason)` |
| `manifest.py` | `load_manifest(pcdir)` · `save_manifest(pcdir, m)` · `rebuild_manifest(pcdir)` · `adopt_orphans(pcdir, m)` · `add_tombstone(...)` |
| `pcreg.py` | `ensure_pc_dir(paths, ident)` · `load_pc` · `update_pc` · `record_probe(pcdir, key, ok, value, reasons, status)` · **`verdict(history, cfg) -> str`**(§6.4 유일 판정) · `probe_bundle_location(paths)` |
| `aliases.py` | `logical_map(paths)` · `auto_alias(paths, cfg)` · `record_alias(...)` · `undo_alias(...)` |
| `export.py` | `export_agent_streams(pcdir, ident, cfg)` (읽기는 `lm27.store.reader`) |
| `loader.py` | **`data\pcs` 를 읽는 유일 모듈.** `iter_records(paths, kind, d0=None, d1=None, *, pcs=None, dedupe=True)` · `bundle_status(paths)` · `load_report()` |
| `merge.py` | `merge_bundle(paths, other_data_dir) -> MergeResult`(번들 + `data\ai\store` 합집합) · `redact_rewrite_own(pcdir)` |
| `move.py` | `prepare_move(paths, cfg) -> MoveLaunch` · `arrival_check(paths) -> list[Missing]` |

### 2.7 `lm27\normalize\` — 정규화(이 문서 소유, 6개)

정규화 명세가 아직 없다. 아래가 임시 정본이고, 규칙 근거는 C §7(병합)·CT §6(화행 어미 규칙)·P H3(토큰 파생)·W §2.4(시간 코어 형 변환)·P §12.7(부재 힌트)이다.

| 파일 | 책임 | 공개 함수 |
|---|---|---|
| `load.py` | 번들 로더 → 재정제(G2) → 병합 → 파생 열(`subject_tokens` 등 = `tokens_of(*_masked)`) 부착 | `load_evidence(paths, cfg, d0, d1) -> list[dict]` |
| `merge.py` | msg_key 병합(필드 단위 최선 값 + provenance, 신뢰 순위 COM > 색인 > OWA(minute) > OWA(date) > Copilot), date-only 흡수, *.copilot 은 병합 제외 | `merge_messages(rows) -> list[dict]` |
| `cues.py` | 화행 단서 추출(P 의 훅) | `extract(text: str) -> list[str]` (값 ⊂ act_cues 열거) |
| `act.py` | 화행 판정 7종(적재 시, 정제문 + act_cues + 구조), 수동 태깅 덮어쓰기 | `classify_act(row, ctx) -> (act, conf)` · `save_tag(paths, msg_key, act)` · `load_tags(paths)` |
| `absence.py` | 근태 대응: abs_hint·일정 플래그 → 회의 범주·부재일 | `meet_category(row) -> str` · `leaves(rows, cal) -> dict[date, str]` |

### 2.8 `lm27\catalog.py` — 프로그램 카탈로그(CP §6·H X10, 1개)

`classify(proc, extra) -> Prog | None` · `is_noise(proc) -> bool` · `solver_names() -> list[str]` · `app_class_of(app_id) -> str` · `cat_of(app_id) -> str`(한글 범주 CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통) · `CATALOG_VERSION`. LM24 `core/programs.py` 를 옮겨 다시 설계한다. 에이전트 bin 사본에 포함한다.

### 2.9 `lm27\time\` — 시간 코어(W 부록 A, 11개)

| 파일 | 공개 함수 |
|---|---|
| `__init__.py` | `analyze_time(person_key, records, profile, calendar_path, as_of, overrides=None, tags: HierTags \| None = None) -> TimeResult` |
| `calendar.py` | `Calendar(path, company_off=(), weekdays=None)` · `.is_holiday(d)` · `.wd_between(d1, d2)` · `.month_workdays(y, m)` · `.month_weekdays(y, m)` · `build_days(ev, cfg, cal)` · `slot_tag(slot, days, cfg)` |
| `intervals.py` | `U` · `I` · `SUB` · `L` · `IvIx` · `pre_iv` · `split_int(total, weights)` · `lr_minutes(sec_by_key, total_min)` |
| `tokens.py` | `fam_key(doc_key, name_masked, dir_keys, cfg) -> str` · `is_generic(name_masked, cfg)` · `raw_tokens(parts, boiler)` · `tok_sim(a, b, min_sub_len=2)` · `fam = lm27.privacy.keys.doc_fam`(재수출, 시험용) |
| `evidence.py` | `normalize(records, profile, cfg, as_of, tags: HierTags) -> (Evidence, audit)` · 형 `Samp` `PcSpan` `Msg` `Meet` `DocE` `Comp` `Commit` `Man` |
| `envelope.py` | `build_envelope(ev, cfg, days) -> Envelope` |
| `episodes.py` | `build_tasks(ev, env, days, cfg, cal) -> (list[UnitTask], list[QueueItem])` · `grade_of(sb, eb)` · `completion(task, cycle, nxt, ctx)`(E2 점수 유일원) |
| `attribute.py` | `attribute(ev, env, tasks, days, cfg) -> (assign, level)` · `resolve(fam_key, t, ctx)` |
| `mm.py` | `month_mm(env, assign, days, cfg, cal, as_of)` · `team_tables(slots, assign, days, cfg)` · `rollup(month, labels)` |
| `ledger.py` | `day_ledger` · `interval_ledger` · `task_ledger` |
| `queue.py` | `make_queue(...)` · `prioritize(items, cfg)` |

경로 결정: W 의 `lm27\time\registry.py` 는 폐지하고 `lm27.config` 를 쓴다(미보정 ★ 표식은 설정 선언 메타). W 의 `tokens.doc_key(name, folder)` 는 `fam_key(...)` 로 이름을 바꾼다(정제 후 해시 위에서 동작, §4.3).

### 2.10 `lm27\hier\` — 계층·분류(H §12.2, 19개)

`__init__.py`(`classify_all(run_ctx) -> HierResult`) · `names.py`(`fold` `ukey` `note` `num_tokens` `name_toks` `bigram_dice`) · `vocab.py`(`DOMAIN_META` `RESERVED` `BUILTIN_VOCAB` `snap_domain` `domain_name` `domain_color` `domain_order` `domain_keywords` `domain_prompt_line` `legacy_code`) · `registry_schema.py`(`validate_registry(obj, side)` `validate_local(obj)`) · `registry.py`(`load_effective(paths, cfg, now)` `merge` `hier_hash` `EffectiveRegistry.resolve/domain_of/active_ids`) · `match.py`(**`match_tokens(text) -> set`**·`ent_tokens`·`kw_hit`) · `features.py`(`features_of(records, reg, person_dir, catalog, cfg)`) · `rules.py`(`score_projects` `score_domains` `tag_evidence(feats, reg, cfg) -> HierTags`) · `unitlabel.py`(`unit_inputs` `unit_rule_label` `field_func` `decide_wtype` `decide_stance` `ax_link` `role_id`) · `groups.py`(`name_groups` `rule_title`) · `copilot_io.py`(`build_task_label_items` `read_ai_out` `build_bootstrap_samples` `build_consolidate_items` `regv_for`) · `apply.py`(`apply_labels`) · `proposals.py`(`ProposalQueue`) · `merge.py`(`pair_score` `zone` `cluster`) · `learn.py`(`apply_corrections` `learn_rules` `track_precision`) · `queue.py`(`hier_queue`) · `bootstrap.py`(`codename_candidates` `needs_bootstrap`) · `team_out.py`(`team_parts`) · `data\common_words.txt`.

경로 결정: H 의 `match.tokens_of` 는 P 의 `scan.tokens_of` 와 이름이 겹치므로 `match_tokens` 로 바꾼다.

### 2.11 `lm27\vocab\` — 단계 유형 어휘(R §3.3, 2개)

`__init__.py` · `steps.py`(`STEP_TYPES` `CLASSES` `ext_class` `obs_of` `tool_access` `verifiable`). 레지스트리 `vocab.step_types` 기본값의 원천.

### 2.12 `lm27\bridge\` — 코파일럿 브리지(B §2.2, 22 + stages 11)

본체: `__init__`(`run_stages` `probe` `calibrate` `diagnose` `manual_export` `manual_import`) · `clock` · `settings`(bridge.* 를 `lm27.config` 에서 읽어 고정) · `cdp` · `js` · `session`(`EdgeSession.open(role, run_id)` — 역할 bridge·owa·teams_web 공용) · `env`(`detect_env`) · `transport` · `transport_stub` · `jsonx` · `exchange`(`ask`) · `gate`(lm27.privacy 를 import 하는 유일 브리지 파일) · `runner`(`run_stage`) · `budget` · `journal` · `calibrate` · `capability`(PC 기록은 `lm27.bundle.pcreg.record_probe` 로) · `manual` · `messages` · `trace` · `fsio`(`lm27.util.fsx` 를 감싸는 얇은 층) · `cli`.

`stages\`: `__init__.py`(`REGISTRY` — 단계 11종) · `base.py` · `lookup.py`(lookup_mail·lookup_teams·lookup_calendar) · `speech_act.py` · `task_label.py`(H §6 내용) · `taxonomy_bootstrap.py` · `taxonomy_consolidate.py`(H §8) · `workflow_label.py` · `review_text.py` · `agentic_match.py` · `subagent_review.py`(R B-1: /1.1).

### 2.13 `lm27\pipeline\` — 분석 파이프라인(이 문서 소유, R A-1, 4개)

| 파일 | 책임 | 공개 함수 |
|---|---|---|
| `__init__.py` | — | — |
| `analyze.py` | 분석 실행: load → normalize → classify → ai:task_label → time → mining → ai:workflow → review → ai:review_text → report. 단계 결과를 `run_status.json` 에, 성공하면 `current.json` 을 원자 교체(chosen=auto) | `analyze(paths, cfg, *, from_, to, as_of=None, ai=True, rerun=None, stages=None) -> int` |
| `stages.py` | 단계 id·이름·의존 표 | `STAGES: list[StageDef]` |
| `retention.py` | 분석 결과 보관 정리(report.analysisKeep) | `prune_analysis(paths, keep)` |

### 2.14 `lm27\report\` · `lm27\ui\` — 보고서·화면(R 부록 A)

- `lm27\report\`(8 + analysis 10): `__init__`(`build_report` `load_model` `export`) · `inputs` · `vocab` · `fmt`(나눗셈·반올림 유일원) · `resolve` · `model` · `export` · `drill` · `analysis\{__init__, activity, mining, review, peers, ontology, agentic, subagent, quality, ai_items}`.
- `lm27\ui\`(11): `__init__` · `server`(`/api/jobs` 포함) · `jobs` · `nextactions` · `api_home` · `api_collect` · `api_analysis`(`/api/bridge/*` 포함) · `api_report`(`/api/hier/*`·`/api/queue/answer` 포함) · `api_team`(`/api/teamserver/*` 포함) · `api_settings`(`/api/calibration` 포함) · `api_privacy`.

### 2.15 `lm27\team\` — 팀 묶음·팀 서버·취합(TAB §8.2, 12개)

`__init__` · `schema`(`validate_team_bundle` · **`TEAM_SPEC_V1` 단일원** · `BYTES_GUARD` · `team_text` · `active_spans`) · `build`(`build_team_bundle` `build_and_queue`) · `queue` · `client`(`hello` `pick_target` `fetch_registry` `fetch_members`) · `server`(`serve`) · `store`(`open_store` `ingest_bytes`) · `aggregate` · `report`(R §7 내용, `render_team_report` `interpret` `build_details`) · `portdiag` · `firewall` · `offline`.

### 2.16 `web\`(R §2.2·§8)

`web\common\{lm27.css, lm27charts.js, lm27ui.js, icons.svg}` · `web\app\{index.html, app.js, report.js}` · `web\team\{index.html, team.js, admin.html}`. 팀 서버 고정 사전은 `/static/lm27.css`·`/static/lm27charts.js`·`/static/lm27ui.js`·`/static/icons.svg`·`/static/team.js` 를 제공한다(`team.css` 는 두지 않는다).

### 2.17 `collect\` — 수집기 스크립트(C §2·CM·CT·CP)

| 스크립트 | 경로 ID | 실행 위치 | 출력 | 소유 § |
|---|---|---|---|---|
| `Invoke-CapabilityProbe.ps1` | P-ENV·P-OL-INST·P-OL-COM·P-IDX·P-EDGE·P-TEAMS·P-PC | 모든 PC, 전경 | stdout JSON(숫자·열거·사유만) | C §4 |
| `probe_owa.py` · `probe_teamsweb.py` | P-OWA · P-WEB | 백필 PC | stdout JSON | CM §14 · CT §12 |
| `probe_copilot.py` | P-CP | 클라우드PC | `lm27.bridge.probe(lookup=True)` 어댑터 | B §8.1 |
| `Get-OutlookCom.ps1` | mail.com · cal.com | 전경 | NDJSON → 파이프(kind 단일, COM 2회 붙기) | CM §5 |
| `Get-OutlookIndex.ps1` | mail.index · cal.index | 전경 | NDJSON → 파이프 | CM §6 |
| `Get-OutlookWeb.py` | mail.owa · cal.owa | 백필 PC | in-process → `lm27.store.SegmentWriter` | CM §11.3 |
| `Get-MailViaCopilot.py` · `Get-TeamsViaCopilot.py` · `Get-CalViaCopilot.py` | mail.copilot · teams.copilot · cal.copilot | 클라우드PC | 브리지 lookup_* 를 부르는 얇은 어댑터 → SegmentWriter | B §8.1 |
| `Import-MailCal.py` | mail.import · cal.import | 전경 | in-process | CM §11.5 |
| `Get-TeamsWindow.ps1` | teams.uia | 에이전트(감독 루프 자식) | NDJSON → 파이프 | CT §7 |
| `Get-TeamsWeb.py` | teams.web | 백필 PC | in-process | CT §8 |
| `collect\agent\agent.ps1`(ps 구현) / `lm27\agent\sampler.py`(py 구현) | pc.sampler(+ pc.compute 구간) | 에이전트 | 파이프 `--mode append` / in-process | CP §3·TAB §1.6 |
| `Get-EventActivity.ps1` | pc.events | 에이전트 수확(6시간) | NDJSON → 파이프 | CP §4 |
| `Get-FileActivity.ps1` | pc.files(+ 열린 문서 폴링) | 에이전트 수확 | NDJSON → 파이프 | CP §5.1·§5.2 |
| `Get-OfficeMru.ps1` | pc.mru | 에이전트 수확 | NDJSON → 파이프 | CP §5.3 |
| `Get-RecentFiles.ps1` | pc.recent | 에이전트 수확 | NDJSON → 파이프 | CP §5.4 |
| `Get-GitActivity.py` | pc.git | 전경 | in-process | CP §9 |
| `Get-LicenseUsage.ps1` | pc.compute(옵트인) | 전경 | NDJSON → 파이프 | CP §8 |
| `Add-WorkLog.ps1` | manual | 전경(사용자) | NDJSON → 파이프 | CP §10 |
| `collect\agent\harvest.ps1` · `Register-Agent.ps1` | — | 에이전트·설치 | — | TAB §1.6 |
| `collect\move\Prepare-Move.ps1` | — | 이동 준비 | — | TAB §1.11 |

수집기 공통 의무: 원문은 메모리·파이프에만, 디스크 쓰기 금지(PS), 수집기 파이썬은 `lm27.privacy.sanitize` 만 import, 시험 주입점(§11.3)을 받는다. 커서·설정 값은 stdin 제어 줄 `_in` 으로 받고 진전은 `_cursor` 로 낸다(§7.3). 파일 수집기(`Get-FileActivity`·`Get-RecentFiles`·`Get-OfficeMru`)의 자기 제외 = `%LOCALAPPDATA%\LoadMonitor27\` 와 `data\bundle.json` 이 있는 폴더(프로그램 폴더 — 이름·위치와 무관). CP 의 `data\bundle` 제외 표기는 이것으로 읽는다(X-316).

### 2.18 `tools\`

| 파일 | 책임 |
|---|---|
| `lint.ps1` | 관문 실행기(§11.1 전부, ruff `--no-cache`) |
| `hook_check.py` | 파일 1개 즉시 검사(PostToolUse 훅·lint 공용) |
| `lm27_selftest.py` | `privacy` 회귀 말뭉치 관문(`--update-lock`) |
| `calibrate.py` | 시간 파라미터 격자 보정(W §8.3, 자동 적용 금지) |
| `bridge.py` | 브리지 진입점(B §2.2) — `lm27 bridge …` 와 같은 `lm27.bridge.cli.main()` |
| `bridge_trace_summary.py` | 브리지 계측 요약 |
| `check_contrast.py` | 색·대비 관문(R G-R7) |

### 2.19 `tests\`

`privacy\`(P §19 T1~T36) · `time\`(W G1~G12) · `hier\`(H T-H01~T-H21) · `bridge\`(B T01~T55, `fake_cdp.py` `fake_http.py` `stub_responder.py` `golden_sends.json`) · `report\`(R RPT-*) · `web\run_node_tests.js`(개발 PC 전용) · `bundle\`(TAB B01~B26) · `team\`(U·S·A·O) · `collect\`(C P1~P12, CM 1~20, CT 1~18, CP 1~14) · `agent\` · `e2e\`(합성 PC1→PC2→클라우드→분석→업로드→팀 보고서) · `fixtures\`.

### 2.20 패키지별 파일 수(요약)

| 패키지 | 파일 수 | 패키지 | 파일 수 |
|---|---|---|---|
| 루트 진입점(`lm27_cli.py`·`lm27_pipe.py`) | 2 | `lm27\`(init·cli·paths·config) + `util\`(4 + init) | 9 |
| `lm27\privacy\` | 16 | `lm27\store\` | 4 |
| `lm27\agent\` | 6 | `lm27\collect\` | 10 |
| `lm27\bundle\` | 11 | `lm27\normalize\` | 6(init 포함) |
| `lm27\catalog.py` | 1 | `lm27\time\` | 11 |
| `lm27\hier\` | 19 | `lm27\vocab\` | 2 |
| `lm27\bridge\` + `stages\` | 22 + 11 | `lm27\pipeline\` | 4 |
| `lm27\report\` | 18 | `lm27\ui\` | 11 |
| `lm27\team\` | 12 | `collect\`(+ agent·move) | 20 + 4 |
| `web\` | 10 | `tools\` | 7 |

---

## 3. 데이터 스키마

표기: ✔ 필수, `?` null 허용, `UTC` = `YYYY-MM-DDTHH:MM:SSZ`, `DATE` = `YYYY-MM-DD`(로컬), `w16` = `w`+16hex 등(§4). 모든 JSON 은 `canon_bytes` 로 쓰고 `read_json`(utf-8-sig 허용, 중복 키·NaN 거부)으로 읽는다. 스키마 이름은 모두 `lm27.*` 이다.

### 3.1 증거 레코드 공통 봉투 — 저장 열의 정본은 P §10.1

C §3.1 은 열의 **뜻**을, P §10.1 은 열의 **이름·형·검증**을 정한다. 둘이 다르면 P 가 이긴다(§10 X-061).

| 열 | 형·형식 | 뜻 |
|---|---|---|
| `id` ✔ | `^[0-9a-f]{16}$` | `sha1(src·pc_id·ts_utc·주키·sha1(정제 텍스트 열을 \x1f 로 이은 것))[:16]`. 주키 = msg_key → commit_key → path_key → doc_key 중 첫 값. 재수집해도 같다 |
| `kind` ✔ | `mail` `cal` `teams` `pc_session` `pc_file` `pc_git` `pc_compute` `manual` | 증거 종류 8종 |
| `src` ✔ | 경로 ID 21종(§6.5) | `^(?:(?:mail\|cal\|teams\|pc)\.[a-z]{2,10}\|manual)$` |
| `pc_id` ✔ | `^pcx?_[0-9a-f]{16}$` | 무키 해시(§4.1) |
| `ts_utc` ✔ | UTC | 사건 시각(구간이면 시작) |
| `ts_local_offset` ✔ | `^[+-](?:0\d\|1[0-4]):[0-5]\d$` | 수집 순간 로컬 오프셋. 분 단위를 정확히 표현하므로 결정 §10.3 '오프셋(분) 저장'을 만족한다. 적재기가 분으로 바꾼다 |
| `ts_precision` ✔ | `exact` `minute` `date` `summary` `unknown` | `date`·`summary`·`unknown` 은 시간 근거가 아니다 |
| `ts_end` | UTC `?` | cal·pc_session·pc_compute 는 필수, manual 은 구간이 있을 때만 |
| `direction` | mail `in` `out` `unknown` / teams `sent` `received` `unknown` / 그 밖 null | 수신 단정 금지 |
| `act` ✔ | 상수 `""` | 화행은 정규화 단계(§2.7)에서 판정, 저장하지 않는다 |
| `act_cues` | list enum{`req` `rep` `done` `ack` `ask` `sched` `cancel` `fyi`} ≤8 | `lm27.normalize.cues.extract` 결과 |
| `thread_key` | `t16` `?` | mail 대화, teams 채널 답글 루트, **cal 반복 시리즈** |
| `chat_key` | `h16` `?` | teams 대화방 |
| `counterpart_keys` | list `w16` ≤20 | 나를 뺀 상대 |
| `n_participants` | int[0,10000] | |
| `doc_key` | `d16` 또는 `r16` `?` | 문서군 키(§4.3). git 은 저장소 키 r |
| `app_id` | `^[a-z0-9_.:\-]{1,48}$` `?` | 카탈로그 slug 또는 `unknown:<exe>` |
| `attach_keys` | list `d16` ≤10 | **mail 전용**(teams 는 `file_keys`) |
| `flags` | obj | kind 별 허용 키만(§3.3), 없으면 생략 = false |
| `confidence` | float[0,1] | §3.4. `*.copilot` 은 ≤0.4 |
| `observed_at` ✔ | UTC | 관측(수집) 시각 |
| `rules_ver` ✔ | `^\d{4}\.\d{1,2}\.\d{1,3}$` | 예 `2026.10.0` |
| `kid` ✔ | `^k[0-9a-f]{8}$` | 키링 키 id |
| `san` | obj{범주: 건수} | 정제 치환 건수 |
| `priv_score` | int[-50,50] `?` | |
| `priv_class` ✔ | `work` `unknown` `media` `private` `social` | private·social 이면 텍스트 열을 비운다 |
| `priv_why` | list ≤8 | P §10.1 열거 |

**저장하지 않는 것**: `subject_tokens`(적재 시 `lm27.privacy.scan.tokens_of(subject_masked 또는 body_masked 또는 msg_masked 또는 text_masked)` 로 파생), 원문 텍스트, 폴더·파일 전체 경로, 주소·이름 평문, `schema`·`source`·`ts_local` 열(CT §3.2 의 것 — 세그먼트 머리말에만 schema 가 있다).

### 3.2 kind 별 저장 열 — P §10.2 정본 + 이 문서의 추가

| kind | 열(P §10.2 요지) | 이 문서가 추가·확정한 것 |
|---|---|---|
| mail | `msg_key` ✔ `m24` · `box` ✔ `inbox` `sent` `other` · `folder_role` ✔ `inbox` `sent` `junk` `deleted` `archive` `subfolder` `other`(deleted 행 폐기, junk 광고 확정) · `sender_key` `self`·`w16`·null · `sender_label` · `n_to` `n_cc` · `rcv` · `subject_masked` ≤120 · `attach_names_masked` ≤5×80 · `attach_exts` ≤10 · `categories_masked` ≤3×30 · `importance` 0~2 · `is_reply` · `refw_depth` 0~9 · `focused_other` · `ad_score` · `ad_band` `keep` `suspect` · `ad_why` · `ad_partial` · `abs_hint` · `replied` · `i_sent_in_conv` · `text_masked` ≤200(mail.copilot 만) | `rcv` 열거에 **`unknown`** 추가(R-NOADDR·B단 생략). flags 에 **`deferred`**(예약 발송) · **`teams_notice`**(팀즈 '놓친 활동' 알림 메일 — D-15) 추가 |
| cal | `msg_key` ✔ `e24` · `ts_end` ✔ · `subject_masked` ≤120 · `counterpart_keys` · `n_participants` · `busy` `free` `tentative` `busy` `oof` `elsewhere` · `location_class` `online` `room` `external` `none` · `categories_masked` · `abs_hint` · `text_masked` ≤200(cal.copilot 만) | `thread_key` = 반복 시리즈 키(반복 마스터 GlobalAppointmentID 의 HMAC). W 의 `Meet.series_key` 원천 |
| teams | `msg_key` ✔ `m24` · `chat_key` ✔ · `chat_type` ✔ `1:1` `group` `channel` `meeting` `self` · `thread_key` · `author_key` `self`·`w16`·null · `direction` · `counterpart_keys` · `file_names_masked` ≤5×80 · `file_keys` `d16` ≤10 · `body_masked` ≤300 · `chat_title_masked` ≤60(group·channel·meeting 만) · `priv_score_base` · `text_masked` ≤200(teams.copilot 만) | flags 에 **`n_part_est`**(참여자 수 추정) · **`author_inherited`**(연속 메시지 작성자 상속) 추가. CT 의 `abs_hint` obj 는 이 두 플래그와 `ts_precision=unknown` 으로 대체 |
| pc_session | `app_id` · `fg_exe` `^[a-z0-9_.\-]{1,64}\.exe$` · `app_class` · `title_masked` ≤120(TITLE_KEEP_CLASSES 만) · `doc_key` · `site_class` · `session_state` ✔ `active` `locked` `disconnected` `remote` · `idle_sec` int[0,4294968] · `layer` ✔ `L0`~`L3` · `event_class`(pc.events) · `ts_end` ✔ | `app_class` 열거에 **`remote`**(원격 데스크톱 클라이언트 전경) · **`meeting`**(회의 창 전경) 추가 → 18값. layer 규칙: pc.events 는 L0(전원)·L1(세션), pc.sampler 는 전경 앱이 `idle`·`system` 이 아니면 L3, 아니면 L2. L4(산출물)는 분석 개념이며 저장하지 않는다 |
| pc_file | `doc_key` · `path_key` `f16` · `name_masked` ≤80 · `ext` · `folder_role` `desktop` `documents` `downloads` `onedrive` `sharepoint` `root` `other` · `root_id` `^R\d{2}$` · `op` `create` `modify` `open` `save` · `size_bucket` · `ooxml_totaltime` · `ooxml_revision` | **`dir_keys`** list `s16` ≤3(상위 폴더 1~3단 HMAC, H X3·W `DocE.folder`). flags 에 **`autosave`**(OneDrive·SharePoint 자동 저장 문서) 추가 |
| pc_git | `doc_key` `r16` · `commit_key` `g16` · `msg_masked` ≤120 · `n_commits` ✔ · `n_files` · `exts` | — |
| pc_compute | `app_id` · `ts_end` ✔ · `cpu_core` float[0,256](무텍스트) | 라이선스 행은 `flags.license`, app_id 는 카탈로그 slug(제품명 평문 아님) |
| manual | `work_category` · `hours` float[0,24] · `ts_utc`/`ts_end`(시각 없으면 그 날 00:00+offset, `date`) · `text_masked` ≤200 · `project_id` · `role_field` · `role_func` | **`man_kind`** enum{`work` `offsite` `instr` `report` `absence` `exclude` `attended` `must_link` `cannot_link` `retract`} · **`ref_keys`** list(증거 키 msg_key·doc_key·chat_key) ≤5 · **`retract_of`** `?` id. 확인 큐 응답과 수동 기록은 모두 manual 행이다(별도 worklog 파일 없음) |

`*.copilot` 증인 행(B §8.1 어댑터): kind = mail·cal·teams, src = `mail.copilot` `cal.copilot` `teams.copilot`, `ts_precision` = `date` 또는 `summary`, `confidence` 0.3, 텍스트는 `text_masked` ≤200, `msg_key` 는 §4.2 의 'cp' 재료로 만든 형식 준수 HMAC. 메시지 행과 병합하지 않는다.

### 3.3 flags 허용 키(kind 별, C §3.3 공통 열거를 대체)

| kind | 허용 키 |
|---|---|
| mail | `has_file` `list_unsub` `precedence` `esp` `body_unsub` `bulk` `cc` `sensitivity`(int 0~3) `cat_private` `ad`(= suspect 띠) `private` `meeting_response` `cap_hit` `utc_suspect` `deferred` `teams_notice` |
| cal | `sensitivity` `cat_private` `private` `recurring` `all_day` `online_meeting` `organizer_me` `recurrence_incomplete` `response`(int 0~5) `meeting_status`(int 0~7, 5·7 취소) `cap_hit` `utc_suspect` |
| teams | `mentions_me` `has_file` `private` `cap_hit` `utc_suspect` `n_part_est` `author_inherited` |
| pc_session | `end_uncertain` `stuck` `always_on` `remote` `utc_suspect` `no_key` `inprivate` |
| pc_file | `view_only` `edit` `author_other` `pdf_export` `final_name` `has_file` `no_key` `autosave` |
| pc_git | `cap_hit` |
| pc_compute | `solver` `license` `end_uncertain` |
| manual | (없음) |

W 가 쓰는 `notice` 는 저장 플래그가 아니라 정규화 파생값(`act == notice`)이고, `utc` 는 `utc_suspect`(레코드)와 실행 단위 확인 설정 `time.envelope.mailTimeOffsetH` 로 대체한다.

### 3.4 confidence 기본값

| 값 | 경로 |
|---|---|
| 1.0 | COM·색인 분 단위, 샘플러 active, git, 파일 mtime, 이벤트 분 단위 |
| 0.8 | OWA minute, UIA 날짜 확정, teams.web exact·minute + 구조 작성자 확정, Office MRU `[T]` |
| 0.4 | OWA·Copilot date-only, 이벤트 로그 추정 끝(event-gap), 브라우저 방문 힌트 |
| 0.3 | Copilot summary 증인(`*.copilot`), 작성자 상속 추정 |

### 3.5 원시 입력 — 수집기 출력 이름은 P §10.2 원시 이름을 쓴다

| 수집기 명세 표기 | 원시 이름(정본) | 처리 |
|---|---|---|
| CM `kind`·`src` | `_kind`(라우팅용) / 없음 | src 는 `rc.src` 로만 정한다(원시로 덮어쓸 수 없음) |
| CM `my_addrs`(레코드마다) | 첫 줄 `{"_meta": {"my_addrs": [...]}}` | 정제 파이프가 메모리의 `RecordContext.my_addrs` 로만 쓰고 저장하지 않는다. in-process 수집기는 `make_record_context(..., my_addrs=...)` |
| CM `folder_path`·`folder_role_hint` | `folder_role` | 폴더 경로 원문은 파이프로 넘기지 않는다 |
| CM `precedence_bulk` | (헤더 텍스트 `headers_text`) | 정제기가 `flags.precedence` 로 판정 |
| CM cal `ts_utc`·`ts_end_utc`·`busy`·`response`(문자열)·`location_raw`·`online_meeting`·`recurring` | `start_utc`·`end_utc`·`busy_status`·`response_status`(int)·`location`·`online`·`is_recurring` | 수집기가 정본 이름으로 낸다 |
| CT `chat_raw_id`·`thread_raw_id`·`author_smtp`·`direction_cue` | `chat_id`·`reply_to_id`·`author_addr`·`is_me` | `author_id`(계정 ID 대조)는 수집기 메모리에서 `is_me` 판정에만 쓴다 |
| CT `ts_wall` | (없음) | 수집기가 수집 순간 오프셋으로 `ts_utc` 를 만든다. 못 만들면 `ts_precision=unknown` |
| CT `offhours_hint`·`source`·`schema_in` | (없음) | 근무창 판정은 시간 코어 몫 |
| CT `chat_title`(누락) | `chat_title` | 원시 입력에 포함 |
| CP `fg_title` 원문 | `fg_title` | 정제 후 폐기(title_masked·doc_key·app_class 만 남음) |

반입 CSV(`Import-MailCal.py`) 헤더는 위 원시 이름(영문)을 그대로 쓴다. 시각 열은 `ts_local`(오프셋 포함 ISO)이며 남는 열은 버리고 모자란 열은 빈칸이다.

### 3.6 세그먼트 파일 `lm27.seg/1`(TAB §1.3)

- 위치·이름: `data\pcs\<pc_id>\seg\<kind>\<seq:06d>-<inst8>-<t0>-<t1>-<sha8>.jsonl.gz`. `t0`·`t1` = `YYYYMMDDTHHMMZ`(콜론 없음), `inst8` = install_id 앞 8자, `sha8` = 압축 바이트 sha256 앞 8자. kind = 8종 + `privacy_audit`.
- 본문: gzip(mtime=0, filename='', level 6) 안의 JSONL. 첫 줄 머리말 `{_h:1, schema, kind, pc_id, install_id, seq, t0, t1, n, srcs, rules_ver, kid, agent_ver, created, src_from, src_to, redacted_from?}`, 끝 줄 꼬리말 `{_f:1, n}`. 레코드는 (ts_utc, id) 순, 세그먼트 안 id 중복 금지, pc_id 는 폴더와 같아야 한다.
- 분할: 로컬 달 경계 / `bundle.segmentMaxRecords`(50,000) / `bundle.segmentMaxRawMb`(16).
- 불변: 덮어쓰지 않는다. 소급 가림만 새 세그먼트 + 무덤표(TAB §1.14).

### 3.7 manifest `lm27.manifest/1`(PC 별, TAB §1.4)

`{schema, pc_id, gen, updated_at, segments:[{kind, seq, file, install_id, t0, t1, n, bytes, sha256, rules_ver, kid, created, src_to}], cursors:{<install_id>:{"<kind>/<src>":{file, offset, last_ts}}}, observed_from:{<install_id>: UTC}, gaps:[{install_id, stream, from_t, to_t, reason}], tombstones:[...], quarantine:[...], agent_status:{install_id, impl, last_tick, healthy, checked_at}}`.

- `cursors.*.file` 은 **`agent\store\` 기준 상대 경로**다: 증거 = `<pc_id>/evidence/<kind>/<src>/YYYYMM/YYYYMMDD.jsonl.gz`, 감사 = `privacy_audit/YYYYMM/YYYYMMDD.jsonl`. `offset` = 마지막 완전한 gzip 멤버 끝(평문은 마지막 `\n` 다음).
- '번들 manifest = 세그먼트 sha256 집합'(D-18)은 모든 `pcs\*\manifest.json` 의 `segments[].sha256` 합집합을 뜻한다.

### 3.8 `pc.json` `lm27.pc/1`(TAB §1.5)

`{schema, pc_id, id_source(machineguid|fallback), label_auto, label_user(로컬 전용), host_display(로컬 전용), host_class, kind(desktop|laptop|vdi|cloud), kind_evidence, kind_confirmed, tz{utc_offset_min, windows_tz, changes[]}, roles[], first_seen, last_seen, anchor_since, installs[], visits[], flags[], capabilities{<키>: {ok, value, reasons[], history[{date, status}], verdict}}}`.

- 그릇 이름은 **`capabilities`**(복수)다. C 의 `capability`·`confirmed_blocked`, B 의 `checks`·`confirmed_days` 는 쓰지 않는다.
- 키: 경로 ID 21종(`pc.sampler` 의 value 에 impl, `pc.events` 의 value 에 채널별 상태 ∈ `ok` `none` `unauthorized` `error` — CP §4.5 의 `error:<msg>` 는 메시지 없이 `error` + 예외 유형명만), `env`, `edge_cdp_policy`, `web_login`, `copilot_connector`(하위 mail·teams·calendar), `copilot_env`(tier·work_toggle·work_mode·web_grounding·web_exposed), `bundle_location`, `team_server_reach`.
- `history.status` ∈ `ok` `fail` `transport_fail` `unknown`(최근 30건). `verdict` 는 `lm27.bundle.pcreg.verdict()` 만 계산한다(§6.4).
- 쓰기는 `record_probe()` 하나로(수집 탐침·브리지 capability 모두).

### 3.9 에이전트 파일(TAB §1.6)

| 파일 | 스키마 | 핵심 필드 |
|---|---|---|
| `agent.json` | lm27.agent/1 | `install_id`(32hex, 재설치에도 유지) · `pc_id` · `agent_ver` · `installed_at` · `impl`(py·ps·none) · `task_name`(`LM27-<install_id>`) · `mutex`(`Local\LM27-<install_id>-agent`) · `bin` · `keep_bins` · `rules_hash` · `subkeys_kid` · `prior_install_ids`(정리 대상 판정용). `root` 필드 없음 |
| `agent_config.json` | lm27.agentcfg/1 | `Cfg.agent_subset()`: `agent.*` · `pc.*` · `teams.uia.*` · `teams.timeRegex` · `time.tzOffsetMin` · `collect.lookbackDays` · `privacy.pipe.waitSec` · `privacy.audit.retentionMonths` + 정제 설정 해시(config_hash). 에이전트·수확 자식이 읽는 비정제 키는 모두 여기 있어야 한다(X-303) |
| `context_cache.json` | lm27.ctxcache/1 | 정제 문맥 직렬화: 사전 이름 목록·허용 패턴·문맥어(`build_context` 결과) · 본인 표시명 `self_names`(`self_name_set` 결과) · 창 분류 문맥 `privacy.window.*` · 사적 폴더 낱말 `privacy.path.excludeKeywords` · 근무창 `work_window`(`time.window.*` 값 + 수집 기간 해의 달력 휴일 날짜 — `RecordContext.work_window`·offhours 판정용) · `episode.finalWords`. 키·주소 없음. 해시 = 에이전트 config_hash |
| `heartbeat.json` | lm27.hb/1 | `install_id` `pc_id` `pid` `agent_ver` `impl` `started_at` `last_tick` `interval_s` `samples_today` `harvest{last_at, last_rc, next_at}` `last_error`(유형·코드만, 200자) |
| `keys\subkeys.json` | lm27-subkeys/1 | `kid` · `written_utc` · `purposes{person, msg, thread, chat, doc, path, dir}`(base64 32B). 주 키 없음 |
| `store\<pc_id>\exe_meta.json` | lm27.exemeta/1 | `{<exe>: {company, product, desc, ver, signer, first_seen, guess_cat, guess_kind, source}}` — product·desc 는 정제 통과값 |

### 3.10 로컬 원장과 수집 커서

- 로컬 원장: `agent\store\<pc_id>\evidence\<kind>\<src>\YYYYMM\YYYYMMDD.jsonl.gz` — 파일 날짜 = **쓰기(플러시) 시각의 UTC 날짜**. 정제된 행 묶음 = gzip 멤버 1개, 덧붙이고 닫는다. 보존 `agent.storeKeepDays`(400). 같은 id 의 새 판(예: 진행 중 부팅 구간)은 덧붙이고, 로더가 observed_at 최대를 쓴다(upsert 없음).
- `raw_cursor.json`(`agent\store\<pc_id>\`): `{"<src>": {...}}`, 원문·원 ID 를 키로 쓰지 않는다. 읽기는 연결자(§7.3)가 `load_raw_cursor` 로 해서 수집기에 `_in.cursor` 로 넘기고, 쓰기는 정제 파이프(PS 수집기) 또는 PY 수집기가 출력 기록 성공 뒤 `save_raw_cursor(paths, pc_id, src, value)` 로만 한다(성공 전 진전 금지). 수집기가 낸 `_cursor` 에 HMAC 이 필요한 값(`last_msg_key` 등)이 비어 있으면 파이프가 그 묶음의 마지막 저장 행에서 채운다.

| src | 커서 내용 |
|---|---|
| mail.com | `{box: {inbox\|sent\|other: {last_ts_utc, last_msg_key}}, cov_months: {"YYYY-MM": {status, read_from, read_to}}}` |
| cal.com | `{last_start_utc, cov_months}` |
| mail.index · cal.index | `{last_item_ts_utc}` |
| mail.owa · cal.owa | `{assigned_todo_ids[], done_ranges[[from, to]]}` |
| teams.web | `{rooms: {<chat_key>: {last_msg_key, oldest_done, newest_done}}}` — CT 의 `teams.web.checkpoint.json` 을 대체 |
| *.copilot | `{witnessed_days[]}` |
| pc.events · pc.files · pc.mru · pc.recent · pc.git | `{last_ts_utc}` (+ pc.git `repos{<doc_key>: last_commit_key}`) |

### 3.11 커버리지 원장(파생) — `data\derived\coverage_ledger.jsonl`

셀 키 `(account, date, kind_axis, src, pc_id)`. 필드: `status`(§6.4) · `n` · `n_minute` · `n_date` · `n_unknown` · `horizon_oldest`·`horizon_newest` `?` · `reasons`(list R-*) · `budget_hit` · `cap_hit` · `probe_sig` · `run_id` · `observed_at`. `account` = 단일 사용자면 상수 `self`. `kind_axis` ∈ `mail_in` `mail_out` `cal` `teams` `pc`.

- 일자 합성 = 출처 중 최선 값(C §5.3). **예외**: `*.copilot` 출처의 `zero_ok` 는 다른 출처의 미관측을 덮지 못한다(B Q23⑤).
- 미관측(`not_attempted` `blocked` `transport_fail` `out_of_horizon`)은 0h 가 아니다.
- 팀즈 하위 원장 `data\derived\teams_coverage.jsonl`: 셀 `(account, date, chat_key, src, pc_id)` + `n_unknown`. 공통 원장 `kind_axis=teams` 로 롤업(최선 상태).

### 3.12 빈칸 계획기(파생) — `data\derived\todo.json`

`{todo_id, account, date_range:[from, to], kind_axis, want_src, want_pc, reasons[], attempts[{pc_id, date, result}], state, updated}`. `state` ∈ `open` `assigned` `blocked_confirmed` `released`. 영속 이력은 pc.json `capabilities.history` 에 있으므로 todo 는 매번 다시 만든다. `blocked_confirmed` ⇔ 해당 능력 verdict = `불가(확정)`.

### 3.13 정제 감사 `privacy_audit`

- 에이전트: `agent\store\privacy_audit\YYYYMM\YYYYMMDD.jsonl`(평문 JSONL, 덧붙이기) → 번들: `data\pcs\<pc_id>\seg\privacy_audit\*.jsonl.gz`.
- 이벤트 본문 키는 P §15.2 만(`ev ts_utc pc_id stage src rules_ver rules_hash config_hash kid rows_in rows_out dropped masked priv ad err out_sha256 dur_ms`). 세그먼트에 담을 때 **봉투 필드** `id`(= sha256(canon_bytes(이벤트))[:16])·`kind`(= `privacy_audit`)·`src`(= 단계 이름: `agent` `collect` `load` `copilot` `team`)를 덧붙인다. 이 src 는 경로 ID 가 아니며, `privacy_audit` 는 KINDS 밖의 스트림 이름이다. 로더는 증거 조회에서 이 스트림을 뺀다.
- `sanitize_audit.jsonl`(C·CP)과 `data\pcs\<pc_id>\audit\privacy_YYYYMM.jsonl`(CM)은 폐지한다.

### 3.14 시간 코어 결과(`timecore/1.1`) — `data\derived\analysis\<run_id>\time\`

W §7.5 + R W-1·W-4 요청 반영. **모든 시간량은 정수 초 또는 정수 분으로 저장**하고 시간(h)·MM 은 표시 때 `lm27.report.fmt` 로 만든다.

| 파일 | 핵심 필드 |
|---|---|
| `env_slots.jsonl` | `{date, slot, tag, basis, conf(high\|mid\|low), on_leave, pcs}` |
| `day_ledger.jsonl` | `{date, total_min, components[[이름, 분]], deductions[[이름, 분, 건수]], excluded[...], by_tag_min, conf_min, coverage, flags}` |
| `interval_ledger.jsonl` | `{date, a, b, tag, basis, targets[[id, min, grade(O\|I\|X)]], note}` |
| `tasks.json` | `{unit_id, kind, label, conv, peer, peers[{who_key, rel(requester\|reporter\|thread\|meeting)}], docs{<fam_key>: {n, ops}}, cycles[{s, sb, e, eb, s_ref, e_ref, interim, unstarted}], grade, status, lead_s, biz_lead_s, effort_s, levels_s{L1..L7}, parallel, machine_s, pre_request_s, flags, proj, first_key, follow_of}` |
| `attrib.jsonl` | `{slot, target, sec, level, obs(bool), app, fam}` |
| `team_tables.json` | `envelope_daily{cols, rows[[date, regular, extended, night, holiday]]}` · `alloc_daily{cols, rows[[date, unit_id, tag, min]]}` — 정수 분, Σalloc ≤ env |
| `mm_month.json` | `{month, workdays, covered_workdays, absence_days, avail_days, env_min, by_tag_min{regular, extended, night, holiday}, attributed_min, unattributed_min, buckets_min{B_GENERIC, B_COMM, B_MEET, B_OFFPC, B_UNKNOWN}, overtime_window_min, overtime_daily8h_min, holiday_night_min, on_leave_min, machine_min, mm(float), load_pct(float\|null), units_mm{...}, rollup{...}}` |
| `confirm_queue.json` | `{qid, code(Q01~Q18), target, impact_min, evidence_keys, proposal, status}` |
| `run_meta.json` | `{core_version:"timecore/1.1", calendar_version, cfg_used, cfg_hash, as_of, input_digest, audit, warnings}` |

로컬 초(lsec)·로컬 분의 기준점은 **2020-01-01 00:00 로컬**이다(음수 없음).

### 3.15 분류 결과(`hier/1`) — `data\derived\analysis\<run_id>\hier\`

`labels.json`(`{unit_id: UnitLabel}` — `group project proposal_id domain field func wtype stance ax_link role_id title title_src src conf level cands why flags`) · `groups.json` · `evidence_tags.jsonl`(`{id, proj, score, top2}`) · `queue.json`(H01~H06) · `proposals_snapshot.json` · `hier_meta.json`(`{hier_version, registry_version, registry_source, hier_hash, counts, ai_share, unclassified_share, warnings, cfg_used}`).

- `title_src` 저장값 ∈ `user` `ai` `rule_doc` `rule_subject` `rule_app` `rule_generic`(규칙 이름 함수 내부값 doc·subject·app·generic 에 `rule_` 접두).
- 시간 코어로는 **`HierTags{msg: {msg_key: proj}, fam: {fam_key: proj}, shared_fams: set}`** 만 넘긴다. 롤업용 `labels[unit_id] = {domain, project, role, wtype, ax_link}`.
- 로컬 상태 파일(`data\local_only\hier\`): `registry_local.json`(lm27.registry_local/1) · `title_cache.json`(lm27.title_cache/1) · `proposals.json`(lm27.proposals/1, 영역 필드 이름은 **`domain_guess`**) · `corrections.jsonl`(증거 키로 저장) · `rules_learned.json`(lm27.rules_learned/1) · `merge_log.jsonl`.

### 3.16 분석층 — `report_model.json`(`lm27.report` 1.0, R §9.2)

| 절 | 핵심(R 소유) |
|---|---|
| 워크플로우 | `workflows{roles{role_id: RoleWorkflow}, units, projects, domains, person}`. RoleWorkflow = `{role_id, units, support_threshold, steps[Step], edges, rework, bottlenecks[{no, kind(wait\|work), value_min\|share}], dropped, sample(ok\|thin), lead_biz_median_min, effort_median_min, parallel_median, done_ratio, ai_role, ai_summary, ai_by}`. Step = `{no, code(§6.6 단계 유형), name, kind(M\|A), n, freq_month, median_min, p75_min, obs_share, wait_in_median_min, work_share, label, desc, label_by, agent_grade, subagent, why}` |
| 리뷰 | `reviews{weeks, months}` — 기간 사실·lead_table·초과 원인 코드(§6.6)·ot_units·peers_top·ai |
| 동료 | `peers{internal[{k, ref, name, units, shared_effort_min, roles{requester, reporter, thread, meeting}, projects, first, last}], external{customer, partner, other}}` |
| 온톨로지 | `ontology{center, nodes[{id, type(P\|R\|U\|D\|A\|C), group, label, weight_min}], edges[{from, to, rel, w, h, inferred}], recs, related_projects}`. 관계 어휘(닫힘): 소속·의뢰함·보고함·산출함·사용함·함께함·선행함·같은문서·같은과제 |
| agentic | `agentic{catalog_version, catalog_n, items, matches[{agent_id, step_type, grade, by, why_ai, why_rule, roles, units, related_min, disagree}], needs[{need_id, ...}]}` |
| 서브에이전트 | `subagent.roles[{role_id, steps, rule, ai{verdict, orch, subs, risk, by}, final, fit_share}]`. 기준 REP·IO·TOOL·VER·RISK, 플래그 D·R·B·L·S·T |
| 측정 품질 | `quality{grade, reasons, by_month}` = `quality_month()`(팀 묶음 quality 도 같은 함수) |

모델 등식(관문): `attributed + unattr = env`, `obs + est = attributed`, `buckets 합 = unattr`, `units.effort = Σ alloc`. 가림판은 허용 목록 재구성(R §9.2.4).

### 3.17 브리지 파일(B §2.4·§2.5·§7)

| 파일 | 위치 | 핵심 |
|---|---|---|
| ai_in | `data\derived\ai_in\<stage>.jsonl` | `{key, group, fields, rule, src_ver, meta{priv_class, ad_band, rules_ver}}` |
| ai_out | `data\derived\ai_out\<stage>.json` | `{schema:1, stage, stage_ver, run_id, registry_version, items{key: {ans, by, rid, asks, at}}, stats, result}` — 항목 저장소에서 fold 로 재생성 가능 |
| 항목 저장소 | `data\ai\store\<stage>.items.jsonl` | 커밋 기록 `{t:"commit", ts, stage, schema, ck, key, reg, run, rid, by, asks, final, ans, why?, retry_runs?}` — 보존·합집합 |
| 저널 | `data\ai\runs\<run_id>\<stage>.jsonl` | req·resp·gate_blocked(원문 없음) |
| 결과 봉투 | `data\ai\runs\<run_id>\<stage>.result.json` | §8.5 공통 필드 + B §7.11 필드 |
| 조회 능력 | `data\ai\runs\<run_id>\capabilities.json` | 브리지 내부 상태. PC 기록은 pc.json `capabilities` 로 `record_probe` |
| 세션 잠금·상태 | `%LOCALAPPDATA%\LoadMonitor27\bridge\` | `session.lock.json`(역할 bridge·owa·teams_web) · `bridge_profile.json`(보정·DOM 학습·건강·env — **Edge 프로필 폴더가 아니다**) |

### 3.18 팀 묶음 `lm27.team_bundle` 1.0(TAB §2.3 + 이 문서의 확정)

TAB §2.3.1·§2.3.2 의 모양을 따르되 다음을 1.0 에 포함한다(구현 전이므로 판 올림 없이 확정).

| 필드 | 확정 |
|---|---|
| `person.field` | TAB 의 `person.function` 을 개명. 값 = 레지스트리 `vocab.fields` 코드(개인 기본 분야) |
| `person.member_id` | 설정이 `""` 이면 `null` 로 싣는다 |
| `person.work_tz_offset_min` | `time.tzOffsetMin` 값을 싣는다(별도 설정 키 없음) |
| `built_at` · `period.analyzed_until` | ISO 8601 + 오프셋(예 `+09:00`) — P 값 클래스 `DATETIME_OFFSET` |
| `projects[].domain` · `proposals[].domain_guess` | 5종(`DEV` `MP` `EXT` `COM` `AX`). `UNC` 는 과제가 없는 단위업무의 파생값으로만 존재 |
| `roles[].field` · `roles[].function` | 어휘 **코드**(예 `ELEC`·`DESIGN`). `role_id` 는 §4.4 식(코드 입력) |
| `units[].activity_type` | 업무 유형 코드 7종(`DEV` `OFFICE` `FIELD` `PM` `PL` `SUPPORT` `EDU`) |
| `units[].spans` | TAB 의 `gantt_spans` 를 개명(`[[from, to, lead\|active]]`, lead 정확히 1개). team_data·detail·report_model 도 `spans` |
| `units[].end.kind` | `E1o` `E1i` `E2` `E3c` `E3i` `M` `null`(E3i 추가) |
| `units[].grade` | `A`~`E` + `M`(수동 기록 전용 업무) |
| `workflows[].steps[]` | `type` = 단계 유형 코드(§6.6), `why[]` 어휘에 `tool_access` 추가, `wait_in_median_min` `work_share` `bottleneck(wait\|work\|both\|"")` `sample(ok\|thin)` 추가 |
| `agentic.needs[].need_id` | `"n_"+sha1(type+"\|"+ukey(name))[:6]` |
| `peers[]` | `{peer_key, scope, units, shared_effort_min}` |
| `privacy_counts` · `catalog_proposals[]{exe, company, product, n_days, minutes}` | 포함(P §14.5 표에 추가) |
| `quality` | `grade`·`reasons` 는 `lm27.report.analysis.quality.quality_month()` 계산 |

`TEAM_SPEC_V1` 은 `lm27\team\schema.py` 하나에서 정의하고, P §14.5 대조표는 이것에서 생성한다(관문 L-23).

### 3.19 레지스트리 `lm27.registry/1`(H §2 의미 + TAB §3.10 운반)

- 분류 필드(projects·vocab·rules·never_pairs·agents·agents_meta·domain_meta·public_domain_classes)의 의미와 검증은 H §2.3·§2.4, 운반 필드(schema·version·pepper·pepper_id·members·customers·partners·internal_domains·calendar)는 TAB §3.10.
- `vocab.{fields, functions, activity_types, step_types}` = 객체 목록 `{code, name, status, replaced_by, keywords?, apps?, exts?}`. `step_types` 항목은 `tool_access`(0~2)·`verifiable`(0~2)·`kind`(M|A)·`cls` 를 더 가진다(기본값 `lm27.vocab.steps`).
- `projects[].domain` 5종, `P-99xx` 는 팀 레지스트리에 둘 수 없다(PUT `reserved_id` 거부). 예약 과제 P-9901~P-9905 는 클라이언트·서버가 주입한다.
- `calendar` 는 §3.21 과 같은 모양이다. `std_window`·`lunch`·`night` 필드는 두지 않는다(근무창은 개인 설정 `time.window.*`).
- 별칭 중복 검사·`ukey` 는 `lm27.hier.names.ukey`, PUT 검증은 `lm27.hier.registry_schema.validate_registry(side="server")`.
- 크기 ≤2MB, 배포 기본값은 빈 과제·별칭·코드네임·고객·구성원·규칙·카탈로그(중립 예시만).

### 3.20 개인 로컬 레지스트리와 수동 상태

`lm27.registry_local/1`(H §3.3): `projects[]`(`L-\d{4}`, `proposal_id`, `maps_to`) · `overlays` · `roots` · `domain_meta` · `vocab_add`(`L_…` 코드) · `never_pairs` · `person{default_field, default_func}` · `codename_review`. 유효 레지스트리 = 내장 ⊕ 팀 ⊕ 개인 로컬(H §3.4).

### 3.21 달력 `calendar.json`(W §2.5 형 — `config\calendar.json` 이 실물)

`{version, std_day_min:480, weekdays:[0,1,2,3,4], note, years:[{year, holidays:[{date, name, kind, source_url, confirmed}]}], company_off:[DATE]}`.

- 우선순위: 팀 레지스트리 `calendar`(같은 모양) > `config\calendar.json`. 분석 기간에 years 에 없는 해가 섞이면 분석 거부(사유 '달력 미확인 연도').
- `std_day_min`·`weekdays` 는 달력 값만 쓴다(설정 키 없음).
- `scratchpad\…\calendar_verified.json` 은 검증 산출물일 뿐 입력 형식이 아니다.

### 3.22 팀 서버 산출 `team_data.json`(`lm27.teamdata/1`, TAB §4.9 + R §7.8.1)

`{schema, gen, built_at, registry_version, calendar_version, months, workdays, people[{i, person_key, label, quality, flags, months[{m, mm, env_min, by_tag, avail_days, load_pct, partial, src12}]}], domains, projects, roles, role_matrix, vocab_names, activity_types, unattributed, units_stats, gantt[{person, domain, project_id, role_id, row_end, units[{unit_id, title, spans, density, effort_min, parallel, grade, status}]}], agentic{matches, needs, subagents}, quality{excluded_from_comparison, matrix}, interpretation, warnings}`.

- 사람은 정수 `i` 로만 참조한다. 값은 반올림하지 않은 원값(정수 분·float MM)이고, 반올림은 표시 때만(TAB §4.1).
- `agentic.subagents` 는 묶음의 role 단위 기록을 취합기가 (field, function) 단위로 모은 것(TAB §4.7).
- 배지 코드 `cfg_mismatch`(산식 설정 상이), `calendar_mismatch`, `pepper_mismatch`.

### 3.23 기타 파일

| 파일 | 스키마 | 핵심 |
|---|---|---|
| `data\bundle.json` | lm27.bundle/1 | `bundle_id`(32hex) · `person_key`(`p_`+12hex, 최초 1회, 불변) · `created_at` · `created_on_pc` · `lm27_version` |
| `data\pc_aliases.json` | lm27.pcalias/1 | `decisions[{at, pc_id, logical, rule(auto_vdi\|user_undo\|manual), why?}]` |
| `move_ready.json` | lm27.moveready/1 | `at pc_id label_auto manifest_gen bundle_mb derived_mb sha_ok segments other_pcs_seen` |
| outbox meta | lm27.outbox/1 | `sha256 bytes period_key person_key built_at built_on approved state attempts next_at last_error last_target history` |
| `data\team\overrides.json` | lm27.team_overrides/1 | `units{unit_id: title\|detail}` · `needs{need_id: drop}` |
| `stage_result_<stage>.json` | lm27.stage/1 | §8.5 |
| `run_status.json` | lm27.runstatus/1 | `{run_id, from, to, as_of, started, ended, state, stages[{id, name_ko, state, counts, rc, reason, resumable}]}` |
| `analysis\current.json` | lm27.current/1 | `{run_id, from, to, as_of, built_at, report_version, chosen(auto\|explicit), chosen_at}` |
| `model_meta.json` | — | `{report_version:"report/1", inputs{논리 이름: sha16\|missing}, cfg_used, built_at}` |
| 내보내기 `manifest.json` | lm27.export/1 | `run_id report_version built_at files[{path, variant, format, bytes, sha256}]` |
| `ui_server.json` | — | `pid port started_at instance_id root_id` |
| 작업 `ui\jobs\<job_id>.json` | — | `job_id kind lane state started ended rc events(꼬리 200) result` |

---

## 4. ID·키 형식

### 4.1 기계·설치·실행 식별자(키 없는 값)

| 이름 | 형식 | 만드는 법 | 쓰는 곳 |
|---|---|---|---|
| `pc_id` | `^pcx?_[0-9a-f]{16}$` | `"pc_" + sha256("LM27.pc\|" + MachineGuid.lower())[:16]`. MachineGuid 를 못 읽으면 `pcx_` 대체식(TAB §1.2) + 사유 `R-NOMACHGUID` | 레코드·폴더·manifest. 키링이 생기기 전(설치 전용 진입점)에도 정해져야 하므로 키를 쓰지 않는다 |
| `install_id` | 32hex | `uuid4().hex`. 재설치·판 올림에도 유지 | agent.json · 작업명 · 세그먼트 이름 `inst8`(앞 8자) |
| 논리 PC | pc_id | `pc_aliases.json` 마지막 결정 | VDI·GUID 변동 병합(TAB §1.8) |
| `bundle_id` | 32hex | `uuid4().hex`, 최초 1회 | bundle.json |
| `person_key` | `^p_[0-9a-f]{12}$` | `"p_" + secrets.token_hex(6)`, 최초 1회, 복사·이동해도 불변 | **번들 소유자** 식별(팀 묶음·팀 서버). 개인 식별용 이름으로 쓰지 않는다 |
| `run_id` | `^\d{8}-\d{6}-[0-9a-f]{4}$` | 로컬 시각 `YYYYMMDD-HHMMSS` + 무작위 4hex | collect·analyze·bridge 공통. `run8` = 끝 8자 |
| `job_id` | `^j\d{14}[0-9a-f]{4}$` | 화면 작업 | R §2.3.5 |
| `todo_id` | `<want_src>:<from>:<to>` | 결정적 | todo.json |
| `qid` | 12hex | 시간 큐 `sha1(코드\|대상\|핵심 근거)[:12]`, 분류 큐 `sha1(코드\|군집 키\|근거)[:12]` | 확인 큐 |
| `rid` | `^R[2-9A-HJ-NP-TV-Z]{5}$` | 브리지 요청 번호 | B §6.1 |
| `period_key` | `<from>_<to>` | 팀 묶음 기간 | outbox·서버 |
| `sha12` · `sha8` | hex | 바이트 sha256 앞 12·8자 | 파일 이름 |

### 4.2 가명 키(HMAC) — 도메인 규칙

- **주 키**(L1): `data\keys\privacy_keyring.json`(`lm27-keyring/1`), `kid = "k" + sha256(secret)[:8]`. 폴더와 함께 이동해 PC1·PC2·클라우드PC 가 같은 키를 쓴다. manifest·세그먼트·팀 묶음·코파일럿·zip 에는 넣지 않는다.
- **하위 키**: `subkey(master, purpose) = HMAC-SHA256(master, b"lm27:" + purpose)`. `keyed(kr, purpose, value, n) = hex(HMAC-SHA256(subkey, value.encode("utf-8")))[:n]`. 키링(Keyring)과 에이전트 하위 키(AgentKeys)가 같은 값을 낸다(P T28).
- `PURPOSES = person msg thread chat cal doc path dir repo commit unit host peer` · 에이전트에 내려 주는 `AGENT_PURPOSES = person msg thread chat doc path dir`(dir 추가). `KEYS_VERSION = "lm27-keys/1"`.
- HMAC 재료는 **정제 전 원문**(메모리)으로 계산한다. 정제 후 해시 위에 다시 HMAC 을 걸지 않는다.
- **팀 비밀**(L2): 팀 pepper(64hex, 레지스트리로 배포) → `peer_key = "c_" + …[:12]`(P §9.7), `pepper_id` 8hex. 키 2층(D-18)의 '팀 비밀'이 이것이고, '개인 비밀'은 주 키다.

| 키 | 형식 | 용도(purpose) · 재료 |
|---|---|---|
| `who_key` | `w`+16hex | person · `smtp:<소문자>` 또는 `name:<norm_person>` — 사람(로컬 전용). CT 의 `person_key`(p+16hex) 표기는 who_key 로 읽는다 |
| `msg_key`(mail·teams) | `m`+24hex | msg · mail = `mid:<Message-ID>`, 없으면 퍼지 재료(box, UTC 분, thread, counterpart 집합). teams = `tid:<메시지 ID>`, 없으면 `teams:<로컬 날짜>\|<chat_id>\|<norm(author)>\|<HH:MM>\|<sha256(norm(body))[:16]>` |
| `msg_key`(cal) | `e`+24hex | cal · `<GlobalAppointmentID>\|<시작 UTC>`, 없으면 `(시작 UTC, 끝 UTC, 제목 해시)` |
| `msg_key`(*.copilot) | `m`·`e`+24hex | msg·cal · `cp:<src>\|<DATE>\|<sha256(canon_bytes(답 행))[:16]>` — 형식은 지키되 메시지 행과 병합하지 않는다 |
| `thread_key` | `t`+16hex | thread · 대화 ID / 채널 답글 루트 / 일정 반복 시리즈 |
| `chat_key` | `h`+16hex | chat · 대화방 ID(UIA 는 합성 ID — 웹 chat_key 를 병합 기준으로 우선) |
| `doc_key` | `d`+16hex | doc · `n:` + `doc_fam(이름)`(§4.3) |
| repo 키 | `r`+16hex | repo · 저장소 정규화 이름(pc_git 의 `doc_key` 열에 저장) |
| `path_key` | `f`+16hex | path · 전체 경로(소문자) |
| `dir_keys[i]` | `s`+16hex | dir · 상위 폴더 이름(1~3단) |
| `commit_key` | `g`+16hex | commit · 커밋 sha |
| `unit_id` | `u_`+10hex | unit · 시작 근거 키(W §4.11). 분석 산출 ID 이며 팀 묶음에 실을 수 있다(로컬 키 아님) |
| `host_class` | 4hex | host · 호스트 이름 앞 4자 대문자 |
| `peer_key` | `c_`+12hex | 팀 pepper · 상대 주소(외부는 None) |

팀 묶음에 실을 수 있는 식별자는 `person_key` `peer_key` `unit_id` `role_id` `project_id` `proposal_id` `need_id` `agent_id` 와 레지스트리 코드뿐이다. `who_key`·로컬 키(m·e·t·h·d·r·f·s·g)·`kid`·`pc_id`·GUID 는 금지 값이다(P §14.3 의 `forbidden:local_key` 첫 글자 목록에 `s` 추가).

### 4.3 문서군 정규화 — 한 함수

- `lm27.privacy.keys.doc_fam(name)`: NFKC → 소문자 → 확장자 제거(복합 확장자·Creo 판번호 포함) → 꼬리 반복 제거(최대 5회, `FAM_TAIL` = `v\d+(\.\d+)?` · `rev\d+` · `r\d+` · `최종` · `final` · `수정본?` · `사본` · `copy` · `(\d)` · `\d{6,8}` 와 그 앞 구분자). 규칙 원천은 W §4.1.
- `doc_key = "d" + keyed(kr, "doc", "n:" + doc_fam(name), 16)`. 창 제목 문서명·파일 이름·메일 첨부·팀즈 파일·클라우드 문서 탭에 같은 함수를 쓴다(문서 연결, P T27).
- 범용 이름(보고서.pptx·새 Microsoft Excel 워크시트 등)은 시간 코어가 구분한다: `lm27.time.tokens.fam_key(doc_key, name_masked, dir_keys, cfg)` = 범용이 아니면 `doc_key`, 범용이면 `doc_key + "@" + dir_keys[0:2]` 를 이은 것, dir_keys 가 없으면 `B_GENERIC` 처리. 범용 판정 목록은 `episode.docs.genericStems`.
- P 의 `doc_norm()` 은 폐지한다(P Q20 해소). git 은 `doc_key` 열의 `r` 키를 그대로 fam_key 로 쓴다(`repo:` 접두 없음).

### 4.4 키 없는 해시 ID

| ID | 형식 | 식 |
|---|---|---|
| `role_id` | `^r_[0-9a-f]{6}$` | `"r_" + sha256("LM27.role\|" + (project_id 또는 proposal_id 또는 "UNC") + "\|" + field_code + "\|" + func_code)[:6]` — 입력은 **어휘 코드**. 예 `("P-0007","OPT","ANALYSIS") → r_8412d7` |
| `need_id` | `^n_[0-9a-f]{6}$` | `"n_" + sha1(step_type + "\|" + ukey(name))[:6]` |
| 군집 키 | `grp:` + 12hex | `sha1(anchor_key)[:12]` |
| 내용 키 `ck` | 24hex | B §7.9 |
| 레코드 `id` | 16hex | §3.1 |

### 4.5 레지스트리 ID

| 대상 | 형식 |
|---|---|
| 팀 과제 | `^P-\d{4}$`(P-0001~P-9899). 예약 `P-9901` DEV · `P-9902` MP · `P-9903` EXT · `P-9904` COM · `P-9905` AX('<영역> 일반') — 레지스트리에 둘 수 없다 |
| 개인 과제 · 제안 | `^L-\d{4}$` · `^pr_\d{1,4}$`(재사용 금지) |
| 구성원 · 고객사 · 협력사 · 에이전트 · 팀 규칙 | `M…` · `C…` · `V…` · `AG…` · `TR…` (REG_ID `^[A-Za-z][A-Za-z0-9_\-]{0,23}$`) |
| 정제 토큰 안에 들어가는 ID(과제·고객사·협력사) | `^[A-Za-z][A-Za-z0-9_\-]{0,15}$`(≤16자 — P 토큰 문법과 같게, H TOKEN_RX 도 이 길이) |
| 어휘 코드 · 개인 어휘 · 옛 문자열 어휘 | `^[A-Z][A-Z0-9_]{1,15}$` · `L_…` · `X_` + sha1(ukey(이름))[:6] 대문자 |
| 학습 규칙 | `LK-…`(키) · `LT-…`(토큰) |

### 4.6 정제 토큰(P §5.2)

`[주민번호]` `[외국인등록번호]` `[생년월일]` `[카드]` `[전화]` `[사업자번호]` `[법인번호]` `[여권]` `[운전면허]` `[계좌]` `[IP]` `[URL]` `[경로]` `[금액]` `[비율]` `[회사]` `[나]` `[사람]` `[사람#6hex]` `[고객사:ID]` `[과제:ID]` `[협력사:ID]` `[이메일@<사내·개인메일·고객사:ID·협력사:ID·도메인>]`. 코파일럿 전송 때는 외부 도메인을 `[이메일@외부]`, 웹 노출이면 `[사람#…]` 를 `[사람]` 으로 줄인다.

### 4.7 OS·네트워크 이름

| 대상 | 이름 |
|---|---|
| 작업 스케줄러 | `LM27-<install_id>`(시험은 `LM27T-` 접두, 끝에 삭제). 옛 작업 정리는 `agent.json.prior_install_ids` 에 있는 `LM27-<32hex>` 만. `LoadMonitorNN-*` 등 남의 작업은 건드리지 않는다 |
| 뮤텍스 | `Local\LM27-<install_id>-agent` |
| 팀 서버 신원 · 프로토콜 | `app = "LM27-team"` · `proto = "lm27-team/1"` · 헤더 `X-LM27-Bundle-SHA256` `X-LM27-Client` `X-LM27-Sent-At` `X-LM27-Upload-Token` |
| 로컬 앱 신원 | `app = "LM27-ui"` |
| JS 표식 · 프롬프트 머리표 | `/*LM27:<이름>*/` · `[LM27 요청 …]` |
| 포트 | 로컬 앱 19280(+9) · 팀 서버 9310 · CDP 9343(+10). 피하는 포트: 8765~8767(별개 프로젝트), 9148~9167, 9333(이전 판 코파일럿) |

---

## 5. 설정 키 단일 레지스트리

### 5.1 규칙

1. **선언 단일원** = `config\settings_registry.json`. 키마다 `{default, type, range 또는 choices, owner(읽는 모듈), spec, uncalibrated(★), secret, scope(personal·agent·team_server), restart, label_ko, help_ko}`. W 의 `config/schema_time.json`, P 의 `config.default.json`, W 의 `lm27\time\registry.py` 는 이것으로 합친다.
2. **값** = 선언 기본값 ← `config\config.json`(개인 덮어쓰기). 비밀은 설정이 아니다: 업로드 토큰은 `data\keys\secrets.json`, 서버 토큰은 sha256 만 설정에 둔다.
3. **표기** = `네임스페이스.낱말` 의 camelCase. 단위는 접미로: `Sec` `Min` `H` `Days` `Wd`(근무일) `Mb` `Ms`. snake_case 키는 없다(§5.4 개명).
4. 목록형 기본값이 내장 목록인 키는 P §17.1 의미론(`내장 ∪ add − disable`, 값이 그냥 목록이면 내장을 대체)을 따른다. 표의 형 `list(+-)` 가 이것이다.
5. 미등록 키를 코드가 읽으면 **오류**(lint·실행 모두). `config.json` 에 미등록 키가 있으면 무시하고 경고(`config_warnings`, 화면 다음 할 일 N16)를 남긴다.
6. **죽은 키 금지**: 등록된 키는 코드에서 읽혀야 하고, 수치·선택 키는 값을 바꾸면 결과가 바뀌어야 한다(W G6·R G-R9). 실행 결과에 `cfg_used`(읽힌 키·값)를 남긴다.
7. 경로는 설정 키가 아니다(`lm27.paths`). 예외는 사용자가 고르는 바깥 경로뿐이다: `pc.watchFolders`, `collect.importDir`, `team.offlineDir`, `teamServer.storeDir`·`publishDir`·`inboxDirs`, `bridge.edge.profileDir`(빈 값 = `lm27.paths.edge_profile()`), `pc.git.exe`·`pc.git.repos`·`pc.git.scanRoots`, `pc.license.lmutilPath`(X-302).
8. 에이전트에는 `Cfg.agent_subset()`(`agent.*` `pc.*` `teams.uia.*` `teams.timeRegex` `time.tzOffsetMin` `collect.lookbackDays` `privacy.pipe.waitSec` `privacy.audit.retentionMonths` + 정제 설정 해시)만 `agent_config.json` 으로 내려간다. 정제에 쓰는 `privacy.*` 값·근무창은 `context_cache.json` 으로 간다(§3.9).
9. ★ = 실자료 보정 전 정책값. 화면에 '미보정' 배지, `tools\calibrate.py` 결과는 사용자 승인 뒤에만 반영.
10. **수집 스크립트가 쓰는 키.** §5.2 '읽는 곳'이 `.ps1` 수집기인 키는 그 스크립트를 띄우는 연결자(전경 = `lm27.collect.run`, 에이전트 = `lm27.agent.main`·`lm27.agent.harvest`, ps 구현 = `agent.ps1`·`harvest.ps1` 이 `agent_config.json` 에서)가 읽어 stdin 제어 줄 `_in.cfg` 로 넘긴다(§7.3). 레지스트리 `owner` 에는 연결자 모듈과 스크립트를 함께 적고, L-12 의 '읽힘'은 연결자 쪽 읽기로 판정한다. `collect\*.py` 수집기는 `lm27.config` 를 직접 읽어도 된다(L-10, X-300).

### 5.2 키 표

#### 수집(collect·probe·ledger·mail·teams)

| 키 | 기본값 | 형 | 읽는 곳 | 명세 § |
|---|---|---|---|---|
| `collect.backfillPc` | `"cloud"` | str(`cloud`·PC 라벨) | collect.plan | C §1 · CM §13 |
| `collect.lookbackDays` | 120 ★ | int | collect.run · agent.harvest(Get-EventActivity `-Days` 로) | 이 문서(CM collect.mail.period·CP -Days 통합, O-5) |
| `collect.parallelMax` | 2 | int | collect.plan | C §8.2 |
| `collect.budgetSec` | 0(끔) | int | collect.run | C §8.1 |
| `collect.watch.heartbeatSec` | 30 | int | collect.watch | C §8.4 |
| `collect.watch.stallMin` | 15 | int | collect.watch | C §8.4 |
| `collect.watch.noProgressMin` | 45 | int | collect.watch | C §8.4 |
| `collect.confirmBlockedCount` | 2 | int | bundle.pcreg.verdict | C §6.2 · B §3.4 |
| `collect.confirmTtlDays` | 14 | int | bundle.pcreg.verdict | B §3.4 |
| `collect.ownerAddress` | `""` | str(로컬 전용) | Get-OutlookCom·Index(내 주소 마지막 후보) | CM §5.6 |
| `collect.importDir` | `""`(= `data\import`) | path | Import-MailCal | CM §13 |
| `ledger.mismatchRatio` | 1.3 ★ | float | collect.ledger(넘으면 셀 사유 `R-COMGAP`) | C §5 · CM §13 |
| `probe.budgetSec` | 60 | int | collect.probe | C §4.3 |
| `probe.subfolderRatio` | 0.3 ★ | float | Invoke-CapabilityProbe(R-SUBFOLDER) | 이 문서(C 미명명) |
| `probe.ostStaleH` | 72 ★ | int | Invoke-CapabilityProbe(R-STALE) | 이 문서(C 미명명) |
| `mail.includeArchiveStore` | false | bool | Get-OutlookCom | CM §13 |
| `mail.com.budgetSec` | 360 | int | Get-OutlookCom(일정은 절반) | CM §13 |
| `mail.com.watchdogSec` | 20 | int | Get-OutlookCom · P-OL-COM | CM §5.2 |
| `mail.com.protectedReadSec` | 2 | int | Get-OutlookCom B단 · P-OL-COM | C §4.3 |
| `mail.com.readProtected` | `"auto"` | auto·0·1 | collect.plan | CM §13 |
| `mail.com.capMail` · `mail.com.capCal` | 20000 · 8000 | int | Get-OutlookCom | 이 문서 · CM §5.7 |
| `mail.index.capMail` · `mail.index.capCal` | 20000 · 8000 | int | Get-OutlookIndex | CM §13 |
| `mail.index.excludeFolderNames` | 내장 | list(+-) | Get-OutlookIndex | CM §6.1 |
| `teams.timeRegex` | `""` | str | Get-TeamsWindow | CT §16 |
| `teams.uia.intervalSec` | 300 | int(120~300) | agent.main | CT §16 |
| `teams.uia.visibleOnly` | true | bool | Get-TeamsWindow | CT §16 |
| `teams.uia.maxElements` | 4000 | int | Get-TeamsWindow | CT §16 |
| `teams.uia.windowWatchdogSec` | 15 | int | Get-TeamsWindow | CT §16 |
| `teams.uia.budgetSec` | 60 | int | agent.main | 이 문서(CT §7.2 미명명) |
| `teams.web.maxChats` | 0(예산 안 무제한) | int | Get-TeamsWeb | CT §16 |
| `teams.web.budgetSec` | 900 | int | Get-TeamsWeb | CT §16 |
| `teams.web.maxScroll` | 12 | int | Get-TeamsWeb | CT §16 |
| `teams.web.includeChannels` · `teams.web.includeActivity` | true · true | bool | Get-TeamsWeb | CT §16 |
| `teams.pmWhoKeys` | `[]` | list(w16) | normalize.act · report | CT §16 |

#### 에이전트·PC(agent·pc)

| 키 | 기본값 | 형 | 읽는 곳 | 명세 § |
|---|---|---|---|---|
| `agent.impl` | `"auto"` | auto·py·ps | agent.install | TAB §7.1 |
| `agent.sampleIntervalSec` | 60 | int(≥5) | agent.main | TAB §7.1 · CP §16 |
| `agent.flushIntervalSec` | 300 | int | agent.main | TAB §7.1 |
| `agent.flushMaxRows` | 120 | int | agent.main | CP §16 |
| `agent.harvestIntervalH` | 6 | int | agent.main | TAB §7.1 |
| `agent.harvestWaitSec` | 120 | int | collect.run | TAB §7.1 |
| `agent.storeKeepDays` | 400 | int | agent.main | TAB §7.1 |
| `agent.heartbeatStaleSec` | 600 | int | agent.install(생존 판정) | TAB §7.1 |
| `agent.filePoll.intervalSec` | 300 | int | agent.main(열린 문서 폴링) | CP §16 |
| `agent.filePoll.topN` | 40 | int | agent.main | CP §16 |
| `pc.watchFolders` | `[]` | list(path) | Get-FileActivity | CP §16 |
| `pc.watchExtensions` | 내장(이전 판 248종 이식) | list(+-) | Get-FileActivity | CP §16 |
| `pc.autoDiscoverFolders` | true | bool | Get-FileActivity | CP §16 |
| `pc.excludeFolderNames` | 내장 | list(+-) | Get-FileActivity | CP §16 |
| `pc.excludePackageDirs` | true | bool | Get-FileActivity | CP §16 |
| `pc.files.burstN` | 8 | int | Get-FileActivity(수집 상한 ×5+1) · time.evidence(뭉치 판정) | CP §5.1 · W §8.2.2 |
| `pc.files.budgetSec` | 180 | int | Get-FileActivity | CP §16 |
| `pc.compute.cpuCoreThreshold` | 0.5 ★ | float | sampler(compute 구간) | CP §16 |
| `pc.compute.consecutiveTicks` | 3 | int | sampler | CP §16 |
| `pc.programsExtra` | `[]` | list | catalog | CP §16 |
| `pc.solverProcesses` · `pc.solverProcessesExclude` | 내장 SOLVER_HINTS · 내장 | list(+-) | catalog | CP §16 |
| `pc.git.exe` · `pc.git.repos` · `pc.git.scanRoots` | `""` · `[]` · `[]` | str · list · list | Get-GitActivity | CP §16 |
| `pc.mru.officeVersions` | `["14.0","15.0","16.0"]` | list | Get-OfficeMru | CP §16 |
| `pc.mru.jumpList` | true | bool | Get-OfficeMru | CP §16 |
| `pc.license.enabled` | false | bool | collect.plan | CP §16 |
| `pc.license.lmutilPath` · `pc.license.servers` | `""` · `[]` | str · list | Get-LicenseUsage | CP §16 |

#### 정제(privacy)

| 키 | 기본값 | 형 | 읽는 곳 | 명세 § |
|---|---|---|---|---|
| `privacy.internalDomains` | `[]` | list | privacy.context · keys.peer_key | P §17.2 |
| `privacy.personalMailDomains` | 내장 13개 | list(+-) | privacy.context | P §17.2 |
| `privacy.customers` · `privacy.partners` | `[]` · `[]` | list({id,names,domains}) | privacy.context | P §17.2 |
| `privacy.allowPatterns` | `[]` | list(regex) | privacy.context(§17.3 검증) | P §17.2 |
| `privacy.extraCtx.account` · `.passport` · `.license` · `.money` · `.ip` · `.card` | `[]` | list(문자 그대로) | privacy.context | P §17.2 |
| `privacy.maskCompanySuffix` | true | bool | privacy.context | P §17.2 |
| `privacy.money.maskRates` | true | bool | privacy.context | P §17.2 |
| `privacy.names.extraStopwords` | `[]` | list | privacy.context → detect(NAME_STOP 합집합) | P §17.2 |
| `privacy.path.excludeKeywords` | 내장(개인·가족·사진·private·personal) | list(+-) | records.path_excluded | P §10.4 |
| `privacy.ad.blockDomains` · `privacy.ad.allowDomains` | `[]` | list | privacy.context | P §11.5 |
| `privacy.ad.blockSubjectRegex` | `[]` | list(regex) | privacy.context | P §11.5 |
| `privacy.ad.extraWords` | `[]` | list | records(광고 특징) | P §17.2 |
| `privacy.private.categories` | 내장 | list(+-) | records(mail·cal) | P §17.2 |
| `privacy.private.extraWords` · `.extraWorkWords` | `[]` | list | records.privacy_verdict | P §17.2 |
| `privacy.window.privateExes` | 내장 PRIVATE_EXES | list(+-) | privacy.context(WindowContext) | P §12.6 |
| `privacy.window.privateProfiles` | `["개인","Personal"]` | list | privacy.context | P §12.6 |
| `privacy.window.workTitlePatterns` | `[]` | list(regex) | privacy.context | P §12.6 |
| `privacy.time.regularPrivateRunMin` | 30 ★ | int(5의 배수, 5~240) | time.envelope(R-P3) | P §12.7 |
| `privacy.time.offhoursPrivateBreakMin` | 15 ★ | int(5의 배수, 5~240) | time.envelope(R-P4) | P §12.7 |
| `privacy.copilot.personTokens` | `"plain"` | plain·keyed | privacy.context.make_gate_context | P §13 |
| `privacy.audit.retentionMonths` | 24 | int | agent.main(로컬 감사 정리) | P §15 |
| `privacy.pipe.waitSec` | 120 | int(30~1800) | 파이프 연결자(collect.run · agent.main · agent.harvest, ps 구현은 agent.ps1·harvest.ps1) — 수집기 EOF 뒤 파이프가 이 시간 안에 끝나지 않으면 kill_tree, code 99 | P §3.5 · X-300 |

#### 코파일럿 브리지(bridge) — 읽는 곳은 모두 `lm27\bridge\*`

| 키 | 기본값 | 형 | 명세 § |
|---|---|---|---|
| `bridge.mode` | `"auto"` | auto·manual·off | B §3.1 |
| `bridge.autoManualFallback` | true | bool | B §3.1 |
| `bridge.url` | `"https://m365.cloud.microsoft/chat"` | str | B §3.1 |
| `bridge.chatUrlPrefixes` · `bridge.loginHosts` | B §3.1 목록 | list | B §3.1 |
| `bridge.edge.port` | 9343 | int — **역할 bridge·owa·teams_web 공용** | B §3.1 |
| `bridge.edge.portTries` | 10 | int | B §3.1 |
| `bridge.edge.profileDir` | `""`(= `%LOCALAPPDATA%\LoadMonitor27\edge_copilot`) | path — 역할 공용 | B §3.1 |
| `bridge.edge.diskCacheMb` | 200 | int | B §3.1 |
| `bridge.edge.windowSize` | `"1150,900"` | str | B §3.1 |
| `bridge.edge.closeOnExit` | true | bool | B §3.1 |
| `bridge.loginWaitMin` | 10 | int — 역할 공용(OWA·Teams 웹 로그인 대기 포함) | B §3.1 |
| `bridge.readyWaitSec` | 60 | int | B §3.1 |
| `bridge.modelFast` · `bridge.modelDeep` · `bridge.modelFallback` | `"빠른 응답"` · `"깊이 생각하기"` · `"자동"` | str | B §3.1 |
| `bridge.preferWorkMode` | true | bool | B §3.1 |
| `bridge.webExposure.policy` | `"strict"` | strict·block | B §3.1 |
| `bridge.pollSec` · `bridge.stablePolls` · `bridge.incompleteJsonFactor` | 3 · 8 · 2 | float·int·int | B §3.2 |
| `bridge.firstTokenSec` · `bridge.replyTimeoutSec` · `bridge.roundtripMaxSec` · `bridge.waitIdleSec` | 180 · 480 · 900 · 45 | int | B §3.2 |
| `bridge.chatTurns` | 12 | int | B §3.2 |
| `bridge.inputMaxChars` · `bridge.answerMaxChars` | 8000 · 5000 | int | B §3.3 |
| `bridge.calibSafety` · `bridge.calibrateTtlDays` · `bridge.autoCalibrate` | 0.85 · 30 · true | float·int·bool | B §3.3 |
| `bridge.overlapItems` · `bridge.overlapChars` · `bridge.seenNamesMax` · `bridge.seenNamesChars` | 3 · 600 · 30 · 600 | int | B §3.3 |
| `bridge.splitMinItems` · `bridge.splitMaxDepth` · `bridge.maxAsksPerItem` | 5 · 3 · 3 | int | B §3.3 |
| `bridge.circuitSoft` · `bridge.circuitAbort` | 3 · 6 | int | B §3.3 |
| `bridge.stageBudgetMin` · `bridge.totalBudgetMin` · `bridge.stageFloorMin` · `bridge.finalReserveMin` · `bridge.minAskSec` | 120 · 300 · 15 · 30 · 120 | int | B §3.3 |
| `bridge.lookup.windowDays` · `bridge.lookup.minWindowDays` · `bridge.lookup.maxRows` · `bridge.lookup.fullRatio` | 7 · 1 · 100 · 0.9 | int·int·int·float — 메일·팀즈·일정 조회 공용 | B §3.4 |
| `bridge.manual.maxOpenBatches` · `bridge.manual.ttlDays` | 10 · 7 | int | B §3.4 |
| `bridge.rawCapture` · `bridge.rawCaptureTtlDays` · `bridge.traceMaxBytes` | false · 7 · 4000000 | bool·int·int | B §3.4 |
| `bridge.stages` | 단계 11종 → bool. `lookup_calendar` 만 false, 나머지 true | obj | B §3.4 · H §6 |
| `bridge.dom.inputSelectors` · `.inputAriaLabels` · `.sendLabels` · `.stopLabels` · `.newChatLabels` · `.modelButtonLabels` · `.workModeLabels` · `.webGroundingLabels` · `.assistantSelectors` | B §3.5 목록 | list·obj | B §3.5 |

#### 번들·팀·팀 서버(bundle·move·team·teamServer)

| 키 | 기본값 | 형 | 읽는 곳 | 명세 § |
|---|---|---|---|---|
| `bundle.segmentMaxRecords` · `bundle.segmentMaxRawMb` | 50000 · 16 | int | bundle.segment | TAB §7.1 |
| `bundle.warnSizeMb` · `bundle.lockTimeoutSec` | 300 · 30 | int | bundle | TAB §7.1 |
| `bundle.autoAliasVdi` · `bundle.overlapToleranceMin` | true · 10 | bool·int | bundle.aliases | TAB §7.1 |
| `move.renameRetries` · `move.stopWaitSec` | 4 · 15 | int | bundle.move | TAB §7.1 |
| `team.serverHost` | `"10.115.147.68"` | str — **기본값 바이트 고정(관문 L-21)** | team.client | TAB §7.1 |
| `team.serverPort` | 9310 | int — 기본값 고정 | team.client | TAB §7.1 |
| `team.serverAlternates` | `[]` | list(`host:port`) | team.client | TAB §7.1 |
| `team.selfLabel` · `team.memberId` | `""` · `""` | str | team.build | TAB §7.1 |
| `team.unitTitleMode` | `"label"` | label·generic | team.build | TAB §2.5 |
| `team.shareUnknownApps` · `team.autoSend` | false · false | bool | team.build · team.queue | TAB §7.1 |
| `team.retryScheduleSec` · `team.retryMaxAttempts` | `[60,300,900,3600,10800,21600]` · 50 | list·int | team.queue | TAB §2.8 |
| `team.maxBundleMb` | 8 | int | team.build | TAB §7.1 |
| `team.connectTimeoutSec` · `team.uploadTimeoutSec` · `team.registryTimeoutSec` | 4 · 120 · 15 | int | team.client · hier.registry | TAB §7.1 · H §3.1 |
| `team.useSystemProxy` · `team.allowPublicHost` | false · false | bool | team.client | TAB §7.1 |
| `team.offlineDir` | `""` | path | team.offline · hier.registry | TAB §5 |
| `team.registryRefreshH` · `team.sentKeep` | 12 · 20 | int | team.client · team.queue | TAB §7.1 |
| `teamServer.bindHost` · `teamServer.bindPort` | `"0.0.0.0"` · 9310 | str·int | team.server | TAB §3.2 |
| `teamServer.storeDir` · `teamServer.displayName` · `teamServer.publishDir` | `""` | path·str·path | team.server | TAB §3.2 |
| `teamServer.uploadTokenSha256` · `teamServer.adminTokenSha256` | `""` | str(sha256 만) | team.server | TAB §3.2 |
| `teamServer.readRequiresToken` | false | bool | team.server | TAB §3.2 |
| `teamServer.allowCidrs` · `teamServer.allowedHosts` | `[]` | list | team.server | TAB §3.2 |
| `teamServer.maxBodyMb` · `teamServer.maxConcurrentUploads` · `teamServer.requestTimeoutSec` | 16 · 4 · 60 | int | team.server | TAB §3.2 |
| `teamServer.aggregateDebounceSec` · `.aggregateWaitSec` · `.aggregateTimeoutSec` | 3 · 20 · 300 | int | team.server | TAB §3.2 |
| `teamServer.historyKeep` · `teamServer.genKeep` · `teamServer.logKeepDays` | 5 · 3 · 30 | int | team.store | TAB §3.2 |
| `teamServer.inboxDirs` · `teamServer.inboxPollSec` | `[]` · 30 | list·int | team.offline | TAB §5.2 |
| `teamServer.suggestRanges` | `[[19310,19330],[9311,9330]]` | list | team.portdiag | TAB §3.4 |
| `teamServer.firewallHintAfterMin` · `teamServer.ganttMergeGapDays` | 30 · 2 | int | team.firewall · team.aggregate | TAB §3.2 |

#### 시간 코어(time·episode·mm) — 읽는 곳은 `lm27\time\*`

| 키 | 기본값 | 형 | 명세 § |
|---|---|---|---|
| `time.tzOffsetMin` | 540 | int — 근무 시간대(팀 묶음 `person.work_tz_offset_min`·P `RecordContext.off_min` 의 원천) | W §8.2 |
| `time.slotCoverSec` | 150 | int | W §8.2 |
| `time.window.std` · `.lunch` · `.dinner` · `.night` · `.halfAmOff` · `.halfPmOff` | `09:00-18:00` · `12:00-13:00` · `18:00-18:30` · `22:00-06:00` · `09:00-14:00` · `14:00-18:00` | 시각 구간 | W §8.2.1 |
| `time.envelope.stuckCoverH` · `.stuckIdleRatio` | 14 · 0.02 | h·비 | W §8.2.2 |
| `time.envelope.idleActiveSec` | 300 | int — 샘플 active 판정 | 이 문서(CP idleActiveSec·W 하드코딩) |
| `time.envelope.samplerBridgeMin` · `.sessionGapMin` · `.pcBridgeMin` · `.lockBreakMin` | 60★ · 45★ · 120★ · 15★ | 분 | W §8.2.2 |
| `time.envelope.preWindowMin.mail` · `.teams` · `.file` · `.code` · `.commit` · `.submit` | 20★ · 10★ · 30★ · 45★ · 45★ · 30★ | 분 | W §8.2.2 |
| `time.envelope.tracePadMin` · `.trimEdgesMin` · `.alwaysOnH` | 5 · 10 · 20 | 분·분·h | W §8.2.2 |
| `time.envelope.traceWindowPadMin` · `.traceWindowMinAnchors` · `.remoteSpanMinSends` · `.remoteLinkGapMin` | 30★ · 2 · 2 · 60★ | | W §8.2.2 |
| `time.envelope.afterHoursFgMin` · `.afterHoursAnchorMin` · `.skeletonPadMin` · `.skeletonAnchorPreMin` | 15★ · 15 · 30★ · 30 | 분 | W §8.2.2 |
| `time.envelope.passiveCreditMin` · `.passiveDayCapMin` · `.passiveMaxParticipants` · `.passiveChainGapMin` · `.passiveChainMinN` | 5★ · 60★ · 10 · 90★ · 3 | | W §8.2.2 |
| `time.envelope.dateOnlyGate` | false | bool | W §8.2.2 |
| `time.envelope.tentative` · `.tentativeEvidenceRatio` | `evidence` · 0.5 | count·evidence · 비 | W §8.2.2 |
| `time.envelope.solverMode` · `.solverCapH` | `anchor` · 4 | anchor·cap · h | W §8.2.2 |
| `time.envelope.futureSlackMin` · `.utcSuspectShare` · `.mailTimeOffsetH` · `.longDayH` | 5 · 0.6 · null · 16 | | W §8.2.2 |
| `time.attrib.pointWeightSec` · `.postPadMin` | 60 · 30 | | W §8.2.3 |
| `time.attrib.meetSplitMinAtt` · `.meetSplitShare` · `.meetAbsentCover` | 6★ · 0.5★ · 0.9★ | | W §8.2.3 |
| `time.attrib.gapSplitMaxMin` · `.absorbGenericMaxMin` · `.floorNearMin` · `.solverAbsorbGeneric` · `.l6MaxRatio` | 30★ · 10 · 30 · true · 1.0★ | | W §8.2.3 |
| `time.queue.gapMin` · `.bucketRunMin` · `.minEffortH` · `.maxPerWeek` · `.openLongWd` · `.solverDayH` | 90 · 60 · 0.5 · 15 · 20 · 8 | | W §8.2.4 |
| `time.queue.parallelSuspect` | 5.0 | float(Q12) | W §8.2.4(parallelMax 개명) |
| `episode.requestMaxParticipants` · `.reworkWindowWd` · `.reopenQuietWd` · `.supplementWd` | 5 · 10★ · 3 · 2 | | W §8.2.5 |
| `episode.preStartTolMin` · `.preWorkH` · `.linkWindowWd` | 60 · 24 · 3 | | W §8.2.5 |
| `episode.link.theta` · `.wToken` · `.wTime` · `.wProject` | 2.0★ · 2.5 · 0.5 · 0.7 | | W §8.2.5 |
| `episode.link.reportSim` · `.multiCloseSim` · `.sendTokenSim` | 0.3 · 0.6 · 0.6 | | W §8.2.5 |
| `episode.tokens.minSubLen` · `.idfMaxDf` · `.idfMinN` · `.boilerplate` | 2 · 0.3 · 20 · W 목록 | | W §8.2.5 |
| `episode.docs.genericStems` | W 목록 | list(+-) | W §8.2.5 |
| `episode.finalWords` · `.reviewWords` · `.interimWords` | W 목록 | list(+-) — `finalWords` 는 수집기 `flags.final_name` 판정에도 쓴다(context_cache) | W §8.2.5 |
| `episode.recurringMinWeeks` · `.recurringMaxDaysPerWeek` | 4★ · 2 | | W §8.2.5 |
| `episode.selfMergeSim` · `.selfMergeDays` · `.splitWd` · `.dormantWd` | 0.5 · 3 · 5★ · 5★ | | W §8.2.5 |
| `episode.quietWd` · `.autosaveQuietWd` | 3★ · 3★ | 근무일 — E2 조용한 기간 단일원 | W §8.2.5 |
| `episode.e2Weights` · `.e2High` · `.e2Low` · `.e2TailMin` | W 값★ · 0.7★ · 0.5★ · 120★ | | W §8.2.5 |
| `episode.s2PrePadMin` · `.e3PostPadMin` · `.s2MeetLookbackH` · `.e3cLookaheadH` · `.meetLinkMin` | 30★ · 30★ · 48★ · 24★ · 2.0 | | W §8.2.5 |
| `episode.sharedDocMinTasks` · `.giantNodes` · `.giantDays` · `.requireCommsCoverageForE3` · `.unstartedWd` | 3 · 500 · 90 · true · 10 | | W §8.2.5 |
| `mm.denominator` | `workdays` | workdays·weekdays — **개인 표시 전용**, 팀 묶음은 늘 workdays | W §8.2.6 |
| `mm.inferredAbsence` · `mm.overtimeBasis` | `confirm_only` · `window` | | W §8.2.6 |

#### 분류(hier) — 읽는 곳은 `lm27\hier\*`

| 키 | 기본값 | 명세 § |
|---|---|---|
| `hier.rule.w.token` · `.keyRule` · `.alias` · `.keyword`★ · `.keywordCap` | 6.0 · 5.0 · 4.0 · 2.0 · 4.0 | H §13.1 |
| `hier.rule.w.customer`★ · `.partner` · `.mailDomain` · `.folder`★ · `.app` · `.teamRule` · `.learnedToken`★ | 1.5 · 1.0 · 1.5 · 3.0 · 1.0 · 2.0 · 2.5 | H §13.1 |
| `hier.rule.summaryMult` · `.periodOutsideMult` · `.evidenceMin`★ · `.evidenceMargin`★ | 0.5 · 0.5 · 4.0 · 2.0 | H §13.1 |
| `hier.domain.w` · `hier.domain.order` · `hier.domain.confirm`★ · `hier.domain.margin` | H 값 · `["EXT","AX","COM","MP","DEV"]` · 0.5 · 0.2 | H §13.1 |
| `hier.tokens.boilerplateAdd` · `hier.publicDomainClasses` | `[]` · H 값(.ac.kr 등 → 기관) | H §13.1 |
| `hier.unit.w` · `.minMass` · `.confirm`★ · `.margin` · `.high` · `.fallback` · `.probableMargin` | H 값 · 3.0 · 0.6 · 0.25 · 0.8 · 0.5 · 0.1 | H §13.2 |
| `hier.vocab.top`★ · `.margin` · `.high` · `.low` · `.officeDocShare` · `.meetShare` | 2.0 · 1.0 · 3.5 · 1.0 · 0.6 · 0.5 | H §13.2 |
| `hier.wtype.techShareDev`★ · `.techShareHigh` · `.offpcFieldShare`★ · `.offpcFieldBoth` · `hier.ax.minHits` | 0.3 · 0.5 · 0.5 · 0.3 · 2 | H §13.2 |
| `hier.name.maxGroup` · `.titleMax` · `.cacheKeepDays` | 60 · 25 · 400 | H §13.3 |
| `hier.copilot.askTitleWeak` · `.vocabAskMinEffortH` · `.maxGroupsPerRun` · `.requireCodenameReview` · `.reaskGrowth` | true · 1.0 · 300 · true · 2.0 | H §13.3 |
| `hier.proposals.minEffortMin` | 60 | H §13.3 |
| `hier.bootstrap.minGroups` · `.maxLines` · `.maxModels` · `.unclassifiedShare` · `.cooldownDays` · `.codenameTopN` · `.codenameMinGroups` · `.codenameMinWeeks` | 20 · 100 · 15 · 0.5 · 30 · 30 · 3 · 2 | H §13.3 |
| `hier.registry.staleWarnDays` | 14 | H §13.3 |
| `hier.merge.auto`★ · `.ask`★ · `.cap` · `.spanGapDays` | 1.0 · 0.35 · 5 · 120 | H §13.4 |
| `hier.learn.tokenDfMax` · `.tokenMax` · `.tokenSupport` · `.appSupport` · `.retireMinHits` · `.retireMinPrec` | 0.05 · 3 · 2 · 2 · 5 · 0.6 | H §13.4 |
| `hier.queue.minEffortH` · `.wtypeMinEffortH` · `.proposalMinEffortH` · `.maxPerWeek` · `.weights` | 2.0 · 4.0 · 4.0 · 10 · H 값 | H §13.4 |

#### 화면·보고서(ui·report·teamReport)

| 키 | 기본값 | 읽는 곳 | 명세 § |
|---|---|---|---|
| `ui.port` · `ui.portFallbackCount` · `ui.openBrowser` · `ui.idleShutdownMin` | 19280 · 9 · true · 0 | ui.server | R §10.1 |
| `ui.jobPollMs` · `ui.jobEventsKeep` · `ui.logKeepDays` · `ui.homeCoverageDays` | 1000 · 500 · 14 · 35 | ui | R §10.1 |
| `ui.autoReanalyzeAfterAnswers` · `ui.reanalyzeDebounceSec` · `ui.tableMaxRows` | true · 20 · 500 | ui | R §10.1 |
| `report.defaultRangeMonths` · `report.analysisKeep` | 3 · 10 | ui · pipeline.retention | R §10.2 |
| `report.export.formats` · `.variants` · `.keep` · `.maxHtmlMb` · `.maxModelMb` | `["html","csv","json"]` · `["full","redacted"]` · 10 · 20 · 32 | report.export | R §10.2 |
| `report.csv.bom` · `report.drill.maxEvidencePerUnit` | true · 200 | report | R §10.2 |
| `report.mining.minStepSec`★ · `.maxSteps` · `.minSupportRatio`★ · `.maxEdges` · `.waitBottleneckMin`★ · `.workBottleneckShare`★ · `.minUnitsForBottleneck` · `.handoffWd`★ · `.extClassExtra` | 600 · 8 · 0.3 · 12 · 480 · 0.4 · 3 · 3 · `{}` | report.analysis.mining | R §10.2 |
| `report.review.leadOverrunRatio`★ · `.baselineMonths` · `.baselineMinUnits` · `.lateStartWd`★ · `.parallelHigh`★ · `.scopeRatio`★ · `.maxFacts` | 1.5 · 6 · 3 · 3 · 3.0 · 1.5 · 25 | report.analysis.review | R §10.2 |
| `report.peers.minMsgs`★ · `.maxMeetingSize`★ · `.topN` | 2 · 10 · 20 | report.analysis.peers | R §10.2 |
| `report.ontology.weights`★ · `.minRel`★ · `.sameWorkRel`★ · `.appMinMin` · `.topN` · `.maxUnits` | `{doc:0.4, peer:0.3, app:0.1, seq:0.2}` · 0.25 · 0.6 · 15 · 12 · 40 | report.analysis.ontology | R §10.2 |
| `report.agentic.gradeHigh`★ · `.gradeMid`★ | 0.8 · 0.5 | report.analysis.agentic | R §10.2 |
| `report.subagent.fitScore`★ · `.condScore`★ · `.roleFitShare`★ | 7 · 5 · 0.5 | report.analysis.subagent | R §10.2 |
| `report.quality.covLow`★ · `.covBad`★ · `.estLow`★ · `.estBad`★ · `.unattrHigh`★ · `.noEvidenceDays` · `.samplerLow`★ | 0.8 · 0.5 · 0.25 · 0.5 · 0.3 · 2 · 0.5 | report.analysis.quality | R §10.2 |
| `teamReport.shiftPp` · `.concentrationShare` · `.officeShareNote` · `.unattributedNote` · `.axLinkNote` · `.smallProjectMm` · `.ganttExpandRows` · `.maxDetailMb` | 5.0 · 0.4 · 0.3 · 0.15 · 0.1 · 0.3 · 150 · 12 | team.report | R §10.3 |

### 5.3 코드 상수(설정 아님 — 명세 값 고정)

| 상수 | 값 | 자리 |
|---|---|---|
| 샘플러 틱 상한 · 플러시 파이프 상한 | ≤2초 · `privacy.pipe.waitSec` | agent |
| OOXML 작성자 읽기 | 항목 2초 · 전체 90초 | Get-FileActivity |
| git 저장소당 · 단계 | 60초 · 240초 | Get-GitActivity |
| 이벤트 수확 한 번 | ≤60초 | Get-EventActivity |
| 활동 임계(5분 슬롯) | 300초, 덮임 150초 이상 = 봉투 | 시간 코어(슬롯 길이는 키가 아님) |
| 정수 분 최대잉여 동률 | 정렬 키 `(0 if key 가 "u_" 로 시작 else 1, key)` | `lm27.time.intervals.split_int` |
| 레지스트리 크기 · JSON 깊이 · drain 상한 | 2MB · 32 · 64MB | team |
| 확인 큐 유형 가중 | W §7.3 | time.queue |
| 수집 단계 절대 시간 상한 | 없음(C §8.4 '기본 꺼짐' — 켜는 키를 두지 않는다. 멈춤 판정은 `collect.watch.*`, 전체 예산은 `collect.budgetSec`) | collect.watch |
| 광고·사적 점수 임계 | `AD_DROP` 5 · `AD_SUSPECT` 3 · `PRIV_THRESHOLD` 2(규칙 고정 — `RULES_HASH` 에 포함, 설정 키 아님. C 의 '임계(키 미명명)'은 이것) | lm27.privacy.classify |

### 5.4 개명·폐지표(명세 표기 → 정본)

| 명세 표기 | 정본 | 사유 |
|---|---|---|
| `confirmBlockedCount`(C·CM·CT), `bridge.capability.confirmDays`(B) | `collect.confirmBlockedCount` | 네임스페이스, 두 벌 통합 |
| `bridge.capability.ttlDays` | `collect.confirmTtlDays` | 모든 능력에 같은 TTL |
| `collect.mail.period`(CM), CLI '설정 기간', `-Days 120`(CP) | `collect.lookbackDays` | 기간 키 하나 |
| `config.owner`(CM) | `collect.ownerAddress` | 미등재 키 등재 |
| `mail.import.inDir` | `collect.importDir` | 메일·일정 공용 |
| `mail.owa.loginWaitSec` · `teams.web.loginWaitSec` | `bridge.loginWaitMin` | L0 공용 |
| `mail.owa.profileDir` · `teams.web.profileDir` · `mail.owa.port`(9333) · `teams.web.port` | 폐지 → `bridge.edge.profileDir` · `bridge.edge.port` | B G-B12, 9333 은 이전 판 포트 |
| `mail.copilot.chunkDays` · `teams.copilot.chunkDays` · `mail.copilot.maxRows` · CT 행 상한 50 | `bridge.lookup.windowDays` · `bridge.lookup.maxRows` | B Q23① |
| `teams.copilot.enabled` | `bridge.stages.lookup_teams` | 한 스위치 |
| `teams.samplerIntervalSec` · `teams.sampler.visibleOnly` | `teams.uia.intervalSec` · `teams.uia.visibleOnly` | 감독 루프 안 |
| `teams.selfNames` | 폐지 → `data\local_only\person_dir.json` 의 `self:true` 항목 | 평문 필요(P self_names), 로컬 전용 |
| `teams.pmWeightKeys` | `teams.pmWhoKeys` | who_key 명명 |
| `teams.privateChatsFile` | 폐지(`lm27.paths`) | 경로는 설정 아님 |
| `agent.sampler.intervalSec` · `agent.sample_interval_s` | `agent.sampleIntervalSec` | |
| `agent.sampler.flushSec` · `agent.flush_interval_s` · `agent.sampler.flushN` | `agent.flushIntervalSec` · `agent.flushMaxRows` | |
| `agent.sampler.impl` | `agent.impl` | |
| `agent.harvest.eventIntervalHours` · `agent.harvest_interval_h` | `agent.harvestIntervalH` | |
| `agent.heartbeatStaleMin`(10) · `agent.heartbeat_stale_s`(600) | `agent.heartbeatStaleSec` = 600 | |
| `agent.harvest_wait_s` · `agent.store_keep_days` | `agent.harvestWaitSec` · `agent.storeKeepDays` | camelCase |
| `pc.fileBurstN`('이전 판 값') · `time.envelope.fileBurstN` | `pc.files.burstN` = 8 | 같은 개념 두 벌(이전 판도 한 값 8 을 공유) |
| `pc.completion.quietWorkdays` | `episode.quietWd` | E2 점수 소유 W |
| `STUCK_COVER_H` · `STUCK_IDLE_RATIO` | `time.envelope.stuckCoverH` · `.stuckIdleRatio` | |
| `idleActiveSec`(CP), W 하드코딩 300 | `time.envelope.idleActiveSec` | |
| `programsTeam` | 레지스트리 카탈로그(설정 아님) | |
| CP 본문 `parallelMax` · W `time.queue.parallelMax` | `collect.parallelMax` · `time.queue.parallelSuspect` | 뜻이 다른 두 키 |
| `person.work_tz_offset_min` | `time.tzOffsetMin` | 두 벌 |
| `mm.stdDayMin` · 레지스트리 `calendar.std_window`·`lunch`·`night` · `time.window.weekdays` | 폐지(달력 `std_day_min`·`weekdays`, 개인 `time.window.*`) | 원천 하나 |
| `mm.todayFraction` | 폐지 | 개인=팀 가용 식 통일(X-210) |
| `hier.copilot.enabled` | `bridge.stages.task_label` | 한 스위치 |
| `hier.publicSuffix` | `hier.publicDomainClasses` | 레지스트리 필드 이름과 맞춤 |
| `team.server_host` 등 `team.*` snake | `team.serverHost` · `team.serverPort` · `team.serverAlternates` · `team.selfLabel` · `team.memberId` · `team.unitTitleMode` · `team.shareUnknownApps` · `team.autoSend` · `team.retryScheduleSec` · `team.retryMaxAttempts` · `team.maxBundleMb` · `team.connectTimeoutSec` · `team.uploadTimeoutSec` · `team.useSystemProxy` · `team.allowPublicHost` · `team.offlineDir` · `team.registryRefreshH` · `team.sentKeep` | camelCase |
| `team.registry_timeout_s`(H, 미등재) | `team.registryTimeoutSec` = 15 | 등재 |
| `team.upload_token` | 비밀(`data\keys\secrets.json`), 설정 키 아님 | |
| `team_server.*` | `teamServer.*`(예 `bind_host` → `bindHost`, `upload_token_sha256` → `uploadTokenSha256`) | camelCase |
| `bundle.segment_max_records` 등 · `move.rename_retries` 등 | `bundle.segmentMaxRecords` · `bundle.segmentMaxRawMb` · `bundle.warnSizeMb` · `bundle.lockTimeoutSec` · `bundle.autoAliasVdi` · `bundle.overlapToleranceMin` · `move.renameRetries` · `move.stopWaitSec` | camelCase |
| `privacy.*` snake(예 `internal_domains`, `regular_private_run_min`) | `privacy.*` camelCase(§5.2 표) | camelCase |
| `team_report.*` | `teamReport.*` | camelCase |
| `bridge.edge.diskCacheMB` | `bridge.edge.diskCacheMb` | 단위 접미 규칙 |
| R 본문 짧은 이름(`peerMinMsgs` `ontologyMinRel` `minStepSec` 등) · CP 본문 짧은 이름(`mru.officeVersions` `filePoll.*` `programsExtra` `config.solverProcesses` `compute.*` `license.*` `files.budgetSec`) | §5.2 의 전체 이름 | 단일 레지스트리 |

---

## 6. 코드 레지스트리

### 6.1 사유 코드 `R-*` — 단일 표

분류: **구조**(환경이 막음) · **사람**(사람 조치 필요) · **일시**(다시 시도하면 될 수 있음) · **수송**(드라이버·네트워크·파이프) · **품질**(자료는 있으나 불완전) · **경고**(막지 않음). '확정' 열 ✔ = 서로 다른 날 `collect.confirmBlockedCount` 회 확인되면 '불가(확정)' 근거가 될 수 있다(§6.4 verdict). ✘ = 아무리 반복돼도 확정 근거가 아니다.

| 코드 | 뜻 | 분류 | 확정 | 정의 |
|---|---|---|---|---|
| R-NEWOL | 새 Outlook 전용(COM·색인 Outlook 항목 없음) | 구조 | ✔ | C §4.2 |
| R-NOPROF | Outlook 프로필 0 | 구조 | ✔ | C §4.2 |
| R-WIZARD | 구판 MSI 등록·시작 마법사(New-Object 금지) | 구조 | ✔ | C §4.2 |
| R-DIALOG | 모달 대화상자에 막힘 | 구조 | ✔ | C §4.2 |
| R-CLM | 제한 언어 모드·실행 정책(샘플러 두 구현 모두 실패 포함) | 구조 | ✔ | C §4.2 · CP §12.1 |
| R-APPLOCKER | AppLocker 등 실행 차단(동봉 python.exe·Add-Type) | 구조 | ✔ | TAB §1.6 |
| R-OMG | Object Model Guard — B단(보호 열)만 불가 | 구조 | ✔ | C §4.2 · CM §5.4 |
| R-ELEV | 권한 상승 불일치 | 구조 | ✔ | C §4.2 |
| R-ONLINE | 온라인 모드(색인 비어 있음) | 구조 | ✔ | C §4.2 |
| R-HORIZON | 캐시 동기화 기간 밖 — 셀 상태는 `out_of_horizon` | 구조 | ✘ | C §4.2 |
| R-SUBFOLDER | 기본 폴더 밖 비중 ≥ `probe.subfolderRatio` | 경고 | ✘ | C §4.2 |
| R-STALE | OST 신선도 > `probe.ostStaleH` | 경고 | ✘ | C §4.2 |
| R-NOIDX | WSearch 꺼짐·색인 연결 실패 | 구조 | ✔ | C §4.2 · CM §6.4 |
| R-IDXPOLICY | 색인 정책 차단 | 구조 | ✔ | C §4.2 |
| R-IDXPAUSED | 색인 일시정지·재구축 중 | 일시 | ✘ | C §4.2 |
| R-EDGEPOL | Edge 원격 디버깅 정책 차단 | 구조 | ✔ | C §4.2 · B §4.3 |
| R-LOGIN | 웹 로그인 필요·세션 만료 | 사람 | ✘ | C §4.2 |
| R-CA | 조건부 액세스 차단(AADSTS) | 구조 | ✔ | C §4.2 |
| R-NOLIC | Copilot 사서함 근거 라이선스 없음(Basic) | 구조 | ✔ | C §4.2 · B §4.11 |
| R-NOCONN | Copilot 커넥터 없음 | 구조 | ✔ | C §4.2 |
| R-TZ | 시간대·사서함 시간대 불일치 위험 | 경고 | ✘ | C §4.2 |
| R-OFFICE | 지원 종료 Office 버전 | 경고 | ✘ | C §4.2 |
| R-UIAEMPTY | UIA 텍스트 0(창 숨김·최소화) | 구조 | ✔ | C §4.2 · CT §7.2 |
| R-UIAELEV | 관리자 권한 창 | 구조 | ✔ | C §4.2 |
| R-NOADDR | 내 주소·표시명 미확정 → rcv·direction unknown | 품질 | ✘ | C §4.2 |
| R-NOEVT | 이벤트 채널 읽기 권한 없음 | 구조 | ✔ | C §4.2 · CP §4 |
| R-CAP | 상한 도달(절단) → partial + cap_hit | 품질 | ✘ | C §4.2 |
| R-BUDGET | 시간 예산 소진 → partial | 일시 | ✘ | C §4.2 |
| R-TRANSPORT | 수송 실패(드라이버·네트워크·정제 파이프 실패·대기 초과) | 수송 | ✘ | C §4.2 · 이 문서 §8.2 |
| R-COM-BUSY | COM 서버 바쁨(RPC_E_CALL_REJECTED 재시도 소진) | 일시 | ✘ | TAB §1.7 |
| R-COMGAP | 같은 셀의 출처 간 건수(색인 ÷ COM)가 `ledger.mismatchRatio` 초과 → COM 누락 의심(하위 폴더·프로필 오접속) | 경고 | ✘ | C §5.3 · CM §8 '`COM 누락 의심`' — 이 문서가 이름 붙임(X-311) |
| R-WEBSEL | 웹 선택자 전부 실패 | 구조 | ✔ | CT §12.1 |
| R-LISTVIRT | 채팅 목록 끝까지 스크롤 못함 → partial | 품질 | ✘ | CT §12.1 |
| R-ROOMGONE | 대화 요소 재탐색 실패(그 방만 partial) | 품질 | ✘ | CT §12.1 |
| R-NOGIT | git 없음·전 저장소 실패 | 구조 | ✔ | CP §12.1 |
| R-MRUEMPTY | Office MRU·Recent 0건 | 경고 | ✘ | CP §12.1 |
| R-RECENTPOLICY | 최근 문서 기록 정책 차단(ClearRecentDocsOnExit 등) | 구조 | ✔ | CP §12.1 |
| R-NOMACHGUID | MachineGuid 읽기 실패 → `pcx_` 대체 | 경고 | ✘ | CP §12.1 |
| R-STUCK | idle 0 고착 의심(품질 플래그) | 품질 | ✘ | CP §12.1 |
| R-SAMPLER-ZOMBIE | 생존 조건 ③(store 신선도) 거짓 — 뮤텍스는 쥐었는데 쓰지 않음 | 품질 | ✘ | CP §12.1 |
| R-RULESMISMATCH | 에이전트 정제기 사본 해시 불일치(자동 판 올림) | 일시 | ✘ | P §3.6 · TAB §1.6 |
| R-NOKEY | 에이전트 하위 키 없음·손상(파이프 rc 6, 자동 복구) | 일시 | ✘ | P §9.4 |
| R-BUNDLE-NETWORK · R-BUNDLE-ONEDRIVE · R-BUNDLE-REDIRECT · R-BUNDLE-LOWSPACE · R-BUNDLE-LONGPATH | 번들 도착 경로 경고 | 경고 | ✘ | TAB §1.5 |
| R-BUNDLE-READONLY | 번들 쓰기 불가 → 번들 쓰기 중단, collect rc 3 | 구조 | ✘(확정 개념 없음) | TAB §1.5 |
| R-TEAM-TIMEOUT · R-TEAM-REFUSED · R-TEAM-DNS · R-TEAM-PROXY | 팀 서버 도달 실패 | 수송 | ✘ | TAB §1.5(DNS·PROXY 는 이 문서 추가) |
| R-TEAM-LM24 · R-TEAM-OTHERAPP · R-TEAM-VERSION | 다른 앱(이전 판·기타)이 응답·주판 불일치 | 구조 | ✘ | TAB §1.5 · §2.9 |

- 폐지: `R-SAMPLER-CLM`(→ `R-CLM` 또는 `R-APPLOCKER`), REPORTS 의 `R-WEB-BLOCK` 표기(→ 브리지 문구 `BR-WEB-BLOCK`, 사유 코드 아님).
- 정규식: `^R-[A-Z]{2,}(-[A-Z0-9]+)*$`. 새 코드는 이 표에 먼저 등재한다(lint L-13).
- `team_server_reach.result` → 사유: timeout→R-TEAM-TIMEOUT, refused→R-TEAM-REFUSED, dns→R-TEAM-DNS, proxy→R-TEAM-PROXY, lm24→R-TEAM-LM24, other_lm·other_app·http_error→R-TEAM-OTHERAPP, wrong_major→R-TEAM-VERSION.

### 6.2 코드 이름공간

| 형태 | 뜻 | 인용 방법 |
|---|---|---|
| `R-<영문>` | 사유 코드(§6.1) | 그대로 |
| `R-P1`~`R-P9` | 정제 명세의 시간 근거 규칙(P §12.7, W 가 구현) | 그대로(사유 코드 아님) |
| `R-1`~`R-9` | TAB §0.4 계약 번호 | `TAB R-4` |
| `R-Q1`~`R-Q15` | REPORTS 미결 | `R.R-Q4` |
| `Q01`~`Q18` | 시간 확인 질문(W §7.3, 두 자리) | 그대로 |
| `H01`~`H06` | 분류 확인 질문(H §11.2) | 그대로. H 의 골든 시나리오 H01~H46 은 **`HG01`~`HG46`** 으로 인용 |
| 명세 미결 `Q1`… · `미결 n` | 각 명세의 열린 질문 | `P.Q14` · `B.Q18` · `H.Q5` · `TAB.미결12` · `CM.미결7` |
| `BR-*` | 브리지 사용자 문구(B §13) | 그대로 |
| `N01`~`N19` · `TI-01`~`TI-08` · `CH-*` | 다음 할 일 · 팀 해석 문장 · 차트(R) | 그대로 |
| 관문 | W `G1`~`G12`, P `G1`~`G4`(관문)·`I1`~`I12`(불변식), TAB `I1`~`I7`, H `G-H*`·`H-I*`, B `B1`~`B15`·`G-B*`, R `RP*`·`G-R*` | 겹치므로 `W-G5` · `P-G3` · `P-I7` · `TAB-I2` 처럼 명세 접두를 붙인다 |
| `P-ENV` 등 | 능력 탐침 묶음(§6.7) | 정제 명세 약칭 P 와 무관 |
| `X-nnn` · `L-nn` · `T-nn` · `U-n` · `O-n` | 이 문서의 해소 결정 · lint 관문 · 불변식 시험 · 사용자 결정 · 미결 | 그대로 |

### 6.3 확인 질문

| 코드 | 뜻 | 코드 | 뜻 |
|---|---|---|---|
| Q01 | 경계 확인 | Q10 | 장시간일 |
| Q02 | 미착수 의뢰 | Q11 | 솔버 대량 |
| Q03 | 오래 열림·보류 | Q12 | 분할 제안·분할 과다(`time.queue.parallelSuspect`) |
| Q04 | 원격 발신 | Q13 | UTC 저장 의심 |
| Q05 | 흔적 창·미등록 외근 | Q14 | 회의 불참 의심 |
| Q06 | date-only 게이트 | Q15 | 미정 회의 |
| Q07 | 요약 근거 | Q16 | 휴가 중 근무 |
| Q08 | 근무창 공백 | Q17 | 미귀속 블록 |
| Q09 | 추정 부재 | Q18 | 공용 문서 의심 |
| H01 | 과제 미정 | H04 | 이름 병합 애매 |
| H02 | 규칙·AI 충돌 | H05 | 유형 애매 |
| H03 | 새 과제 확인 | H06 | 퇴역 과제 |

주간 노출 상한은 시간 `time.queue.maxPerWeek`(15), 분류 `hier.queue.maxPerWeek`(10) 따로. 화면은 한 목록에 '시간'·'분류' 꼬리표로 묶는다. 응답은 manual 행(`man_kind`) 또는 `corrections.jsonl` 로 증거 키에 저장한다.

### 6.4 상태 열거와 판정

| 이름 | 값 | 소유 |
|---|---|---|
| 커버리지 셀 `status` | `ok` `zero_ok` `partial` `out_of_horizon` `blocked` `transport_fail` `not_attempted` | C §5.1 |
| `kind_axis` | `mail_in` `mail_out` `cal` `teams` `pc` | C §5 |
| todo `state` | `open` `assigned` `blocked_confirmed` `released` | C §6 |
| 능력 `history.status` | `ok` `fail` `transport_fail` `unknown` | TAB §1.5 |
| 능력 `verdict` | `미확인` `가능` `불가(잠정)` `불가(확정)`(화면에는 해당 역할이 없으면 `해당 없음`) | 이 문서(아래) |
| 단계 `state` | `done` `partial` `failed` `skipped` | §8.5 |
| `stop_kind` | `budget` `fatal` `circuit` `refused` `manual_wait` `header` `gate` `cancelled` `login` `stall` `no_progress` `null` | §8.5 |
| 화면 작업 `state` · `lane` | `queued` `running` `done` `partial` `failed` `cancelled` · `bundle` `net` `local` | R §2.3.5 |
| outbox `state` | `pending` `sending` `sent` `retry_wait` `failed` `auth_needed` `wrong_server` `dropped` `exported` `delivered` | TAB §2.8 |
| `RecordOutcome.status` · dropped 사유 | `stored` `dropped` `error` · `cred` `ad` `private_folder` `folder_excluded` `bad_raw` `no_key` | P §3.2 |
| 단위업무 등급 · 상태 · 종류 | `A`~`E` `O` `Z` `M` · `closed` `estimated` `open` `not_started` · `S1` `ACK` `COORD` `SELF` `APP` `REPORT_ONLY` `MANUAL` | W §4.10 |
| 경계 근거(시작) | `S1` `S1d` `S1o` `S2a` `S2M` `S2m` `S2p` | W §1.3 |
| 경계 근거(종료) | `E1` `E1d` `E1i` `E1p`(중간, 종료 아님) `E2h` `E2l` `E3M` `E3c` `E3i` `NEXT_REQ` `OPEN` | W §1.3 |
| 팀 묶음 start/end kind | 시작 `S1i` `S1o` `S2` `M`, 종료 `E1o` `E1i` `E2` `E3c` `E3i` `M` `null`(대응 W §4.11) | TAB §2.3 + 이 문서 |
| 귀속 단계 `level` | `L1` `L2회의` `L2회의(대형분할)` `L2회의(불참의심)` `L3PC` `L4앵커` `L4솔버cap` `L5흡수` `L5솔버흡수` `L5공백` `L5하한근접` `L6비례` `L7버킷` | W §5.3 |
| 분 등급 | `O`(관측 L1·L2·L3) `I`(추정) `X`(버킷) | W §7.1 |
| 버킷 | `B_GENERIC` `B_COMM` `B_MEET` `B_OFFPC` `B_UNKNOWN` | W §5.4 |
| 꼬리표 | `regular` `extended` `night` `holiday`(배타: 휴일 > 야간 > 연장 > 정규) | W §3.13 · TAB R-2 |
| 라벨 `level` · `src` | `confirmed` `high` `medium` `low` `unclassified` · `user` `token` `rule` `domain_rule` `rule_probable` `ai_h` `ai_m` `ai_l` `fallback` `none` | H §11.1 |
| 측정 품질 `grade` | `reliable` `caution` `unreliable` `""` | R §4.9 |
| 팀 서버 hello · reach `result` | `ok` `other_lm` `lm24` `other_app` `http_error` `timeout` `refused` `dns` `proxy` `wrong_major` | TAB §2.9 · §1.5 |
| 포트 진단 kind | `lm27_same` `lm27_other` `lm24` `other_lm` `other_program` `reserved` `ephemeral` `unknown` | TAB §3.4 |
| 브리지 L2 상태 · by · why | `ok` `partial` `truncated` `echo` `format` `empty` `service_error` `timeout` `refusal` `transport_fail` (+`manual_pending`) · `ai` `manual` `rule` `rule_pending` · `ai_failed` `ai_refused` `gated:<사유>` `oversize` `no_ai_out` | B §6.6 · §7.8 |
| CopilotEnv | tier `premium` `basic` `unknown` · work_mode `work` `web` `unknown` · web_grounding `on` `off` `unknown` · web_exposed bool | B §4.11 |

**verdict 판정(유일 구현 `lm27.bundle.pcreg.verdict`).** history 항목은 `{date, status, reasons, probe_sig}` 다(TAB 형에 reasons·probe_sig 추가).

1. 기록이 없으면 `미확인`.
2. 가장 최근 기록이 `ok` 면 `가능`.
3. 판정 창 = 마지막 `ok` 이후이면서 현재 `probe_sig` 와 같은 기록(탐침 값이 바뀌면 그 전 실패는 세지 않는다 = 자동 해제).
4. 창 안 `fail` 기록에서 §6.1 '확정 ✔' 사유별로 서로 다른 날짜 수를 센다. 어떤 사유가 `collect.confirmBlockedCount` 이상이고 그 사유의 마지막 확인이 `collect.confirmTtlDays` 안이면 `불가(확정)`(TTL 이 지나면 한 번 다시 시도하도록 `불가(잠정)` 로 내려간다).
5. 창 안에 `fail` 이 있으면 `불가(잠정)`.
6. 그 밖(`transport_fail`·`unknown` 만)은 `미확인`.

todo `blocked_confirmed` ⇔ verdict `불가(확정)`, `released` ⇔ 같은 셀이 다시 시도 대상이 됨(probe_sig 변화·TTL 만료·ok 관측).

### 6.5 경로 ID(21종)

| src | kind | kind_axis | 수집기 | 담당 PC | 시간 정밀도 |
|---|---|---|---|---|---|
| `mail.com` | mail | mail_in·mail_out | Get-OutlookCom.ps1 | 모든 PC(로컬) | minute |
| `mail.index` | mail | mail_in·mail_out | Get-OutlookIndex.ps1 | 모든 PC(항상, 교차검증) | minute |
| `mail.owa` | mail | mail_in·mail_out | Get-OutlookWeb.py | 백필 PC — 원장 빈칸만. 보낸 편지함은 항목을 열어 minute, 받은 메일은 date | minute·date |
| `mail.copilot` | mail | mail_in·mail_out | Get-MailViaCopilot.py | 클라우드PC | date·summary(증인) |
| `mail.import` | mail | mail_in·mail_out | Import-MailCal.py(EML·CSV) | 어디서나 | 파일 그대로 |
| `cal.com` | cal | cal | Get-OutlookCom.ps1 | 모든 PC | minute |
| `cal.index` | cal | cal | Get-OutlookIndex.ps1 | 모든 PC | minute(반복 미전개) |
| `cal.owa` | cal | cal | Get-OutlookWeb.py | 백필 PC — 기간 전체 | minute |
| `cal.copilot` | cal | cal | Get-CalViaCopilot.py(lookup_calendar, 기본 꺼짐) | 클라우드PC | date·summary |
| `cal.import` | cal | cal | Import-MailCal.py(ICS·CSV) | 어디서나 | 파일 그대로 |
| `teams.uia` | teams | teams | Get-TeamsWindow.ps1(에이전트 감독 루프) | 모든 PC | exact·minute·date·unknown |
| `teams.web` | teams | teams | Get-TeamsWeb.py | 백필 PC — 기간 전체 | exact·minute·date |
| `teams.copilot` | teams | teams | Get-TeamsViaCopilot.py | 클라우드PC | date·summary |
| `pc.sampler` | pc_session(+ pc_compute 구간) | pc | 에이전트 sampler(py·ps) | 모든 PC | exact |
| `pc.events` | pc_session | pc | Get-EventActivity.ps1 | 모든 PC(수확) | minute |
| `pc.files` | pc_file | pc | Get-FileActivity.ps1 | 모든 PC(수확) | minute |
| `pc.mru` | pc_file | pc | Get-OfficeMru.ps1 | 모든 PC(수확) | minute |
| `pc.recent` | pc_file | pc | Get-RecentFiles.ps1 | 모든 PC(수확) | minute |
| `pc.git` | pc_git | pc | Get-GitActivity.py | 모든 PC(전경) | minute |
| `pc.compute` | pc_compute | pc | sampler(구간) · Get-LicenseUsage.ps1(옵트인) | 모든 PC | exact·minute |
| `manual` | manual | (축 없음) | Add-WorkLog.ps1 · 화면 `/api/worklog` · 확인 큐 응답 | 어디서나 | minute·date |

### 6.6 분석 어휘(코드)

| 어휘 | 값 | 소유 |
|---|---|---|
| 업무 영역 | `DEV` 개발 프로젝트 · `MP` 양산 프로젝트 · `EXT` 외부 업무지원 · `COM` 공통 업무 · `AX` AX 프로젝트 · `UNC` 미분류(파생 전용) | H §1.2 |
| 영역 색 | DEV `#2a78d6` · MP `#c47400` · EXT `#0e8c7a` · COM `#a61b4a` · AX `#6c4fb8` · UNC `#8b929b` | H §1.2 + R H-1(대비 검증값) |
| 분야 field | `MECH` `ELEC` `SW` `OPT` `THERM` `REL` `PROC` `QA` `SYS` `ETC` | H §1.4 |
| 기능 func | `DESIGN` `IMPL` `ANALYSIS` `TEST` `OUTSRC` `PURCHASE` `DOC` `MEET` `PM` `TRANSFER` `SUPPORT` `STUDY` `ADMIN` `ETC` | H §1.4 |
| 업무 유형 wtype(= activity_type) | `DEV` `OFFICE` `FIELD` `PM` `PL` `SUPPORT` `EDU` | H §1.6 |
| 참여 방식 stance | `DO` `COORD` `REVIEW` `LEAD`(개인 보고서 전용) | H §10.2 |
| 단계 유형 step_types(22) | `REQ_IN` `REQ_OUT` `ACK_OUT` `REPORT_OUT` `REPORT_IN` `COMM` `MEET` `REVIEW` `DOC_DOC` `DOC_PPT` `DOC_XLS` `DOC_PDF` `DOC_ETC` `APP_CAD` `APP_CAE` `APP_SIM` `APP_EDA` `APP_IDE` `APP_ENG` `COMMIT` `WEB` `OFFLINE` | R §3.3 |
| 단계 묶음 | 소통 · 회의 · 문서 · 공학 · 코드 · 조사 · 오프라인 | R §3.3 |
| 화행 act(파생) | `request` `ack` `question` `report` `info` `social` `notice` | 이 문서 §2.7(CT §6 규칙) |
| 리드 초과 원인 | `WAIT` `REWORK` `PARALLEL` `SCOPE` `LATE_START` `DATA` `UNEXPLAINED` `NO_BASELINE` | R §4.4 |
| 온톨로지 노드 · 관계 | `P` `R` `U` `D` `A` `C` · 소속 의뢰함 보고함 산출함 사용함 함께함 선행함 같은문서 같은과제 | R §4.6 · 결정 §10.5 |
| agentic 등급 · 서브에이전트 판정 | 상 중 하 · 적합 조건부 부적합 | R §4.7·§4.8 |
| 서브에이전트 why | `repeat_weekly` `repeat_monthly` `digital_io` `structured_input` `tool_access` `verifiable` `low_accountability` | R §4.8 · TAB §2.3 |

### 6.7 능력 탐침 묶음

| 탐침 | 스크립트 | 무엇을 재나 | pc.json 키 | 소유 |
|---|---|---|---|---|
| P-ENV | Invoke-CapabilityProbe.ps1 | 언어 모드·권한 상승·ctypes·도메인 가입 | `env` | C §4.1 |
| P-OL-INST · P-OL-COM | 같은 스크립트 | Outlook 클래식/새, Office 버전·C2R, COM 붙기(자식 + `mail.com.watchdogSec`), A단 읽기, B단 보호 열 시험(`mail.com.protectedReadSec`, OMG), subfolder_ratio | `mail.com` · `cal.com` | C §4.1 · CM §14 · 결정 §10.1 |
| P-IDX | 같은 스크립트 | WSearch·정책·Outlook 항목 수 | `mail.index` · `cal.index` | C §4.1 |
| P-EDGE | 같은 스크립트 | Edge 설치·원격 디버깅 정책·전용 프로필 | `edge_cdp_policy` | C §4.1 · B §4.3 |
| P-TEAMS | 같은 스크립트 | 새/클래식 Teams, 최상위·팝아웃 창 수, 가시 창 수, UIA 줄 수, 시각 패턴 일치 수 | `teams.uia` | C §4.1 · CT §12 |
| P-PC | 같은 스크립트 + 에이전트 자기 시험 | 샘플러 구현·채널 권한·MRU·git | `pc.*` | C §4.1 · CP §1.3 |
| P-OWA | probe_owa.py(백필 PC) | 로그인·AADSTS·최근 1주 분 정밀 비율 | `mail.owa` · `cal.owa` · `web_login` | CM §14 |
| P-WEB | probe_teamsweb.py(백필 PC) | 로그인·메시지 ID·`<time datetime>` 노출 비율·목록 가상화 | `teams.web` | CT §12 |
| P-CP | probe_copilot.py(클라우드PC) | 커넥터(2-strike)·계정 등급·Work 탭·웹 근거·입출력 한도 | `copilot_connector` · `copilot_env` · `*.copilot` | B §4.11 · §8.1 |
| P-BUNDLE | lm27.bundle.pcreg.probe_bundle_location | 도착 경로(OneDrive·리디렉션·네트워크·쓰기·여유·경로 길이) | `bundle_location` | TAB §1.5 |
| P-TEAM | lm27.team.client.hello | `/api/hello` 도달·신원 | `team_server_reach` | TAB §1.5 · §2.9 |

탐침은 내용 0바이트, 숫자·열거·사유 코드만 남긴다. 예산 `probe.budgetSec`.

---

## 7. CLI·bat 진입점

### 7.1 `lm27 <명령>` = `"<ROOT>\python\python.exe" "<ROOT>\lm27_cli.py" <명령>`

`python -m lm27 …` 형식은 쓰지 않는다(동봉 파이썬 `_pth` 가 루트를 sys.path 에 넣지 않음, P H8). 화면이 띄우는 하위 명령은 끝에 `--job <job_id> --events jsonl` 을 붙인다.

| 명령 | 하는 일 | 모듈 | rc(§8.3) | 소유 § |
|---|---|---|---|---|
| `collect [--auto] [--mode auto\|probe-only\|recollect] [--since D] [--until D] [--pc-role pc1\|pc2\|cloud] [--only <src,…>] [--budget-sec N]` | [수집] 한 번(§2.5). `--auto` = `--mode auto` 무질문 + 끝에 대기 업로드 전송 | lm27.collect.run | 0·1·2·3·4 | C §8 · TAB §1.7 |
| `agent install [--only] [--reinstall]` · `agent status` · `agent repair` · `agent uninstall [--purge]` | 에이전트 설치·확인·복구·제거. `--only` = 설치 전용(수집·탐침·내보내기 없음) | lm27.agent.install | 0·2·3·4 | TAB §1.6 |
| `bundle status` · `bundle verify` · `bundle merge <dir>` · `bundle alias <pc_id> <logical>` · `bundle unalias <pc_id>` · `bundle redact` | 번들 관리 | lm27.bundle | 0·1·2·4 | TAB §1.13~§1.15 |
| `move-prepare` | 이동 준비(도우미 PS 를 `%TEMP%` 사본으로) | lm27.bundle.move | 0·2·3 | TAB §1.11 |
| `analyze --from D --to D [--as-of T] [--no-ai]` · `analyze --rerun <run_id> --stages <ids> [--no-ai]` | 분석 파이프라인(§2.13). 빠른 재분석 = `--stages classify,time,mining,report --no-ai` | lm27.pipeline.analyze | 0·1·2·4 | 이 문서 · R A-1 |
| `report build --run <run_id> [--force]` | 보고서 모델 | lm27.report | 0·1·2·4 | R §2.4 |
| `report export --run <run_id> --formats html,csv,json --variant full,redacted [--out <dir>]` | 내보내기 | lm27.report.export | 0·1 | R §9 |
| `report ai-items --run <run_id> [--stage <stage>]` | 코파일럿 단계 ai_in 쓰기 | lm27.report.analysis.ai_items | 0·4 | R §4.10 |
| `bridge run --run-id <id> --stages <a,b> [--mode auto\|manual]` · `bridge probe [--no-roundtrip] [--lookup]` · `bridge calibrate [--force] [--model fast\|deep]` · `bridge diagnose [--model]` · `bridge manual-export [--stages]` · `bridge manual-import [--file <경로>\|--clipboard]` · `bridge replay …` · `bridge unlock` | 코파일럿 브리지(= `tools\bridge.py`) | lm27.bridge.cli | B §12.1 | B §12 |
| `ui [--port N] [--no-browser] [--check]` | 로컬 앱(127.0.0.1) | lm27.ui.server | 0·3 | R §2.3 |
| `team build --from D --to D` · `team list` · `team preview <item>` · `team approve <item>` · `team send [<item>\|--all]` · `team drop <item>` · `team mask <unit_id> title\|detail\|none` · `team drop-need <need_id>` · `team export <item> --dir <폴더>` · `team ping [--host H --port N]` · `team registry-fetch` | 팀 묶음 | lm27.team | 0·1·2·4 | TAB §8.1 |
| `team-server [--host H] [--port N] [--store DIR]` | 팀 서버 | lm27.team.server | 0·3 | TAB §3 |
| `team-aggregate --store <dir> --gen N` | 재취합(서버 하위 프로세스) | lm27.team.aggregate | 0·1 | TAB §3.9 |
| `team-import <파일\|폴더> [--store DIR]` · `team-firewall-diag [--store DIR]` | 오프라인 반입 · 방화벽 진단 | lm27.team | 0·1·2 | TAB §5 · TAB §3.14 |
| `selftest privacy [--update-lock]` | 정제 회귀 말뭉치(= `tools\lm27_selftest.py`) | lm27.privacy.selftest | 0·1 | P §18 |

### 7.2 bat

모든 bat: CP949 + CRLF, BOM 없음, 첫 줄 `@echo off`, 둘째 줄 `>nul chcp 949`, `pushd "%TEMP%"` … `popd`.

| bat | 실행 |
|---|---|
| `LoadMonitor27.bat` | `"<ROOT>\python\pythonw.exe" "<ROOT>\lm27_cli.py" ui`. 기동 실패는 `python.exe … ui --check` 의 한국어 출력 |
| `LoadMonitor27-수집.bat` | `"<ROOT>\python\python.exe" "<ROOT>\lm27_cli.py" collect --auto` |
| `LoadMonitor27-에이전트설치.bat` | `… agent install --only` |
| `LoadMonitor27-이동준비.bat` | 도우미 PS 를 `%TEMP%\lm27_move_<rand>.ps1` 로 복사 → `start "" powershell -NoProfile -ExecutionPolicy Bypass -File …` → 즉시 종료 |
| `LoadMonitor27-팀서버.bat` | `… team-server [--host H] [--port N] [--store DIR]` |

### 7.3 수집기·도구 호출 형식

| 대상 | 형식 |
|---|---|
| PS 수집기 → 정제 파이프 | `powershell -NoProfile -ExecutionPolicy Bypass -File collect\<스크립트>.ps1 -Pc <pc_id> [-Since D -Until D] [스크립트 인자]` 의 stdout 을 `"<PY>" -X utf8 -I -B "<LM27>\lm27_pipe.py" --kind <kind> --src <경로 ID> --pc <pc_id> --out "<store 일자 파일>" --mode append` 의 stdin 으로. **연결자**(수집기와 파이프를 둘 다 띄우고 잇는 쪽) = 전경 `lm27.collect.run`, 에이전트 `lm27.agent.main`(teams.uia·샘플)·`lm27.agent.harvest`(수확), ps 구현은 `agent.ps1`·`harvest.ps1`. P §3.5 골격의 '수집기가 파이프를 띄우는' 방식은 쓰지 않는다. 연결자가 `privacy.pipe.waitSec` 대기·kill_tree(code 99)를 맡는다. 메일·일정은 kind 마다 파이프 하나(COM 2회 붙기, GetActiveObject 재사용) |
| 수집기 제어 줄 | **입력**: 연결자가 수집기 stdin 에 한 줄 `{"_in": {"cursor": <그 src 의 raw_cursor 값\|null>, "cfg": {<그 스크립트가 쓰는 §5.2 키: 값>}, "self_names": [..](팀즈 수집기만)}}` 을 쓰고 닫는다 — 커서·설정·이름·주소를 명령줄에 싣지 않는다(프로세스 목록·감사 로그 노출 방지). stdin 이 리디렉션되지 않았으면 기본값으로 돈다(시험 편의). **출력**: stdout 첫 줄 `{"_meta": {"my_addrs": [...]}}`(선택, §3.5), 레코드 줄들, 마지막 줄 `{"_cursor": {...}}`(§3.10 형, 원문·원 ID 없음). 파이프는 `_` 로 시작하는 제어 줄을 레코드로 세지 않는다. PY 수집기(`collect\*.py`)는 `_in` 대신 `lm27.store.cursor.load_raw_cursor`·`lm27.config` 를 직접 쓰고 `SegmentWriter.flush()` 성공 뒤 `save_raw_cursor` 를 부른다(X-300) |
| 백필 빈칸 파일 | `Get-OutlookWeb.py --blanks-file F` 의 F = `lm27.collect.todo` 가 그 실행 폴더에 쓰는 `data\derived\collect\<run_id>\blanks_<src>.json` = `[{todo_id, date_range:[from,to], kind_axis}]`(파생, 원문 없음 — X-315) |
| 혼합 라우팅(선택) | `lm27_pipe.py --route-by-kind --src-map mail=mail.com,cal=cal.com --pc <pc_id> --out "<…{kind}…>" --mode append`(줄의 `_kind`). `--src-map` 없으면 rc 5 |
| PS 수집기 공통 인자 | `-Pc <pc_id>` · `-Since`/`-Until`(로컬 날짜) · 시험 주입(§11.3). `-Root`·`-PcId`·쓰기용 `-OutDir`(시험 주입 제외)·`-CursorFile` 경로 조립 인자 금지 — 커서·설정 값은 연결자가 stdin 제어 줄 `_in` 으로 넘긴다(아래 '수집기 제어 줄') |
| PY 수집기 | `"<PY>" -X utf8 -I -B collect\<스크립트>.py --pc <pc_id> [--from D --to D] [인자]`. 예: `Get-OutlookWeb.py --kind mail\|cal [--blanks-file F]`, `Get-TeamsWeb.py [--max-chats N] [--budget-sec N] [--no-channels] [--no-activity] [--force]`(`--force` = 체크포인트 무시하고 기간 전체), `Import-MailCal.py --kind mail\|cal [--in-dir P]`, `Get-GitActivity.py [--scan P]`, `Get-*ViaCopilot.py --run-id <id>`. Edge 프로필·포트 인자 없음(`EdgeSession.open(role=…)`) |
| 작업 등록 | `collect\agent\Register-Agent.ps1 -InstallId <32hex> -AgentVer <v> -Impl py\|ps [-Remove] [-NoStart] [-DryRun]`(COM RegisterTaskDefinition 7인자, 실패 시 `schtasks /Create /TN LM27-<id> /XML <tmp> /F`) |
| 관문 | `powershell -NoProfile -File tools\lint.ps1` · `python\python.exe tools\hook_check.py <파일>` · `python\python.exe -B tools\lm27_selftest.py privacy` |
| 보정 | `python\python.exe -B tools\calibrate.py --keys <k,…> [--grid <json>]`(보고서만 쓰고 자동 적용 금지) |

`<PY>`·`<LM27>` = 프로그램 폴더 모드면 `<ROOT>\python\python.exe`·`<ROOT>`, 에이전트 모드면 `agent\bin\<ver>\py311\python.exe`·`agent\bin\<ver>`(옆에 `data\` 가 있으면 프로그램 폴더 모드).

---

## 8. rc·stage_result 계약

### 8.1 수집기 rc(C §8.4)와 원장 번역

| rc | 뜻 | 셀 상태 | 비고 |
|---|---|---|---|
| 0 | 저장(신규 있음) | `ok`, 상한·예산에 닿으면 `partial` + `cap_hit`/`budget_hit` + R-CAP/R-BUDGET | 예산 소진은 rc 0 + partial 이다(rc 2 아님) |
| 1 | 대상 없음·0건 | 지평선 안이고 막는 사유가 없을 때만 `zero_ok`, 아니면 `out_of_horizon` | |
| 2 | 로그인 필요(R-LOGIN·R-CA) | `blocked` + R-LOGIN(사람 사유 — 확정 안 함) 또는 R-CA(구조 — §6.1 확정 가능) | 오케스트레이터가 안내 + `bridge.loginWaitMin` 폴링 |
| 3 | 드라이버 불가·불완전 | `blocked`(구조 사유) 또는 `transport_fail`(R-TRANSPORT) | 사유 코드 필수. 막힌 사유가 있는 경로는 항상 rc 3(CM §6.4 의 'rc 1(또는 3)' 은 3) |
| 4 | 읽었지만 신규 0(커서 이후 0) | 이미 덮인 날은 `ok` 유지 | CT §14.3 의 'rc 1 이 4 흡수'는 폐지 |
| (시간 초과·kill) | — | `transport_fail` + R-TRANSPORT | stop_kind `stall`·`no_progress` |
| (돌지 않음) | — | `not_attempted` | |

`exit 0` 고정 금지. 수집기 rc 는 `stage_result.rc` 에 그대로 남는다.

### 8.2 정제 파이프 종료 코드(P §3.5) → 수집 단계

| 파이프 | 뜻 | 단계 처리 |
|---|---|---|
| 0 | 정상 | 수집기 rc 그대로 |
| 2 | 입력 형식 오류 줄 있음(계속) | 수집기 rc 그대로 + 감사 `bad_raw` 건수 + 경고 |
| 3 · 5 | 내부 오류 · 인자 오류(출력 미기록) | rc 3 + R-TRANSPORT, 문구 '정제기 실패'·'정제기 호출 오류', 다음 주기 재수집 |
| 6 | 키 없음(에이전트) | rc 3 + R-NOKEY, 에이전트 자동 복구 |
| 99 | `privacy.pipe.waitSec` 초과(연결자가 kill_tree — §7.3) | rc 3 + R-TRANSPORT |

요약 줄은 P §3.5 형(`ok mode rows_in stored dropped errors rules_ver kid out_sha256`) + `cursor_saved`(bool — §7.3 `_cursor` 를 저장했는가). 커서는 종료 0·2 일 때만 진전하고 3·5·6·99 면 그대로 둔다(다음 주기에 다시 읽고 중복은 id 로 흡수).

### 8.3 CLI 명령 rc(공통)

| rc | 뜻 |
|---|---|
| 0 | 성공(새 결과 있음) |
| 1 | 내부 오류·치명 실패 |
| 2 | 부분 성공 또는 사람 조치 필요(재개 가능) — 로그인 대기, 예산, 승인 대기, 붙여넣기 대기, 재시도 대기 |
| 3 | 환경 실패 — 번들 쓰기 불가(R-BUNDLE-READONLY), 포트 전부 실패, 실행 차단(R-CLM·R-APPLOCKER) |
| 4 | 할 일 없음 — 새것 0, 이미 최신, 이미 설치됨 |

명령별: `collect` 0(모든 단계 done, 새 레코드 ≥1) · 4(모두 done, 새 레코드 0) · 2(partial 하나라도) · 3 · 1. `agent install` 0 · 4(이미 정상) · 2(작업 등록 실패) · 3(두 구현 자기 시험 실패, impl=none). `report build` 0 · 4(다이제스트·판 같음) · 2(입력 일부 없음, 만들되 경고) · 1. `bridge run` = 단계 rc 최악값(failed 1 > partial 2 > done·skipped 0). `team send` 0(sent) · 2(retry_wait·auth_needed·wrong_server) · 4 · 1. `ui`·`team-server` 0 · 3.

### 8.4 브리지 단계 결과

결과 봉투 `state` → rc: `done` 0 · `skipped` 0 · `partial` 2 · `failed` 1. 항등식 `items_total = ai + manual + rule + pending`, `items_ok = ai + manual`(B §7.11).

### 8.5 단계 결과 공통 스키마 `lm27.stage/1`

모든 장기 단계(수집 단계·브리지 단계·분석 단계)는 아래 **공통 필드**를 갖는다. 각 명세의 추가 필드는 그 뒤에 붙인다.

```
{schema:"lm27.stage/1", run_id, stage, state:"done|partial|failed|skipped",
 items_total, items_ok, items_failed, items_pending,
 stop_kind:"budget|fatal|circuit|refused|manual_wait|header|gate|cancelled|login|stall|no_progress"|null,
 resumable:bool, reason:"<R-* 또는 단계 사유>"|null, hint:"<한국어 한 줄>", caps_hit:bool|{키:수},
 rc:int, updated:UTC, counts:{...}}
```

| 단계 계열 | 파일 | 추가 필드 |
|---|---|---|
| 수집 | `data\derived\collect\<run_id>\stage_result_<stage>.json`(finally 에서 원자 기록). stage = `probe` `pc_bundle` `mail_local` `cal_local` `teams_uia_check` `backfill_owa` `backfill_teams_web` `copilot_lookup` `import` `export` `derive` `upload` | `src`, `subfolder_ratio`, `recurrence_incomplete`, `skipped_msg`(반입 `.msg` 건수 — CM §11.5), 셀 요약. `rc` = 수집기 원 rc |
| 브리지 | `data\ai\runs\<run_id>\<stage>.result.json`(결과 봉투) | B §7.11 전부(asks·sends·rungs·statuses·pack·model·env·gate…) |
| 분석 | `data\derived\analysis\<run_id>\run_status.json` 의 `stages[]` | `id` `name_ko`(공통 필드 축약). 단계 id = `load` `normalize` `classify` `ai:task_label` `time` `mining` `ai:workflow` `review` `ai:review_text` `report` |

규칙: **성공 전 무효화 금지**(새 결과가 done 일 때만 이전 결과를 교체), **빈 값으로 덮지 않음**, 재개는 입력 서명(다이제스트) 기준. 별도 하트비트 파일은 두지 않는다(B Q16 해소) — 하트비트는 §8.6 의 progress 이벤트다.

### 8.6 표준 출력 이벤트(한 줄 JSON)

`{seq:int, ts:UTC, ev, stage?, text_ko?, done?, total?, …}`. `ev` ∈ `stage_start` `progress` `notice` `warn` `msg` `stage_end` `run_end` `result` `check`. 장기 하위 명령은 **30초마다 `progress`** 를 낸다(생존), `done` 증가가 진전이다(감시 §2.5 `watch`). `text_ko` 는 각 명세 사용자 문구 표(B §13 BR-*, R §5.8)의 문장만 쓰고 원문·경로를 넣지 않는다. B §12.5·R §2.3.5 의 이벤트는 이 형의 부분집합이다. 사람용 요약은 stderr.

### 8.7 종료와 취소

자식 종료는 `lm27.util.proc.kill_tree`(`taskkill /T /F /PID`), os.kill 금지. 취소는 정지 플래그(`agent\run\stop.flag`, 화면 작업은 작업별 플래그) → 5초 → kill_tree.

---

## 9. 인코딩·런타임 규칙

### 9.1 런타임

- **파이썬**: `<ROOT>\python\` 의 CPython 3.11 embeddable, 표준 라이브러리만(sqlite3·ctypes 포함). pip·외부 패키지 금지. `python311._pth` 는 수정하지 않는다.
- **진입점**: `lm27_cli.py`·`lm27_pipe.py`·`agent_main.py`·`tools\*.py`·`collect\*.py` 는 첫 실행문에서 자기 루트를 `sys.path.insert(0, ROOT)` 한다. `python -m` 은 쓰지 않는다. `except ImportError` 로 기능을 조용히 삼키지 않는다(이전 판 실측 결함).
- **실행 플래그**: 수집기·파이프 `-X utf8 -I -B`, CLI·화면 `-X utf8 -B`. 작업 폴더는 `%TEMP%`(bat 의 `pushd`). 표준 출력 UTF-8 설정은 진입점에서만.
- **PowerShell 5.1**: `-NoProfile -ExecutionPolicy Bypass`, P/Invoke 는 `Add-Type`, NDJSON 출력 전 `[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)`. 수집기는 디스크에 쓰지 않는다(예외: ps 구현 감독 `collect\agent\agent.ps1`·수확 `harvest.ps1` 의 원문 없는 운영 파일 `agent\heartbeat.json`·`agent\run\{harvest_done.json, .harvest.lock}`·`agent\logs\` — X-307).
- **시간대**: `zoneinfo.ZoneInfo` 금지(동봉 파이썬에 tzdata 없음). 수집 순간 오프셋은 `lm27.util.tz.capture_offset_min`(ctypes `GetDynamicTimeZoneInformation`), 분석 근무 시간대는 `time.tzOffsetMin`. UTC 는 `datetime.now(timezone.utc)` 로만 만든다.
- **시계 주입**: 브리지 `lm27.bridge.clock`(time 모듈은 clock.py 에만), 시간 코어 `as_of` 인자, 수집 시험 가상 시계.
- **프로세스**: 창 없이(`CREATE_NO_WINDOW`), 종료는 `kill_tree`. 수집 COM 호출은 자식 프로세스 + `mail.com.watchdogSec`(이전 판 `Stop-Job` 금지, PID 직접 종료).
- **네트워크**: 로컬 앱·CDP 는 127.0.0.1 바인드, 팀 서버 바인드는 설정(`teamServer.bindHost`). 시스템 프록시 미사용(`team.useSystemProxy=false`). CDP `--remote-allow-origins=*` 금지 — 기본은 Origin 없이, 403 이면 `http://127.0.0.1:<port>` 만(B §4.4).

### 9.2 파일 인코딩

| 파일 | 인코딩 | 줄끝 | 기타 |
|---|---|---|---|
| `.bat` | CP949, BOM 없음 | CRLF | `@echo off` 다음 `>nul chcp 949`, `pushd "%TEMP%"` |
| `.ps1` | UTF-8 **BOM** | CRLF | BOM 이 없으면 5.1 이 CP949 로 오독(실측) |
| `.py` `.md` `.json` `.jsonl` `.js` `.css` `.html` `.svg` `.txt` `.toml` | UTF-8, BOM 없음 | LF | JSON 읽기는 utf-8-sig 허용 |
| 내보내기 `.csv` | UTF-8 BOM | CRLF | `csv.writer(lineterminator="\r\n")`, 수식 주입 방어(`= + - @ 탭 CR` 앞에 `'`), ASCII 파일 이름 |
| 수동 프롬프트 `.prompt.txt` | UTF-8 BOM | CRLF | B §10.3 |
| schtasks 임시 XML | UTF-16 LE BOM | CRLF | 등록 직후 삭제 |
| gzip(세그먼트·store) | — | — | `GzipFile(filename='', mtime=0, compresslevel=6)` — 결정적 |
| 저장소 | `.gitattributes` = `* -text`(바이트 보존) | | |

모든 텍스트 소스에서 제어문자 `0x00-0x08 0x0B 0x0C 0x0E-0x1F` 금지(경로 리터럴이 `data<BEL>ctivity` 로 깨진 이전 판 결함).

### 9.3 쓰기·읽기

- 최종 파일 쓰기는 `lm27.util.fsx.atomic_write`(임시 `.part` → fsync → `os.replace`, PermissionError 재시도 0.1·0.2·0.4·0.8·1.6초). 덧붙이기는 증거면 `lm27.store.SegmentWriter`, 로그·jsonl 이면 `fsx.append_line`. 그 밖의 `open(..., "w"|"a")` 금지.
- 파일은 열고, 다 읽고, 즉시 닫는다. 240자 이상 경로는 `longp()`(`\\?\` 접두).
- 데이터 경로는 `lm27.paths` 로만 만든다. `data\pcs` 는 `lm27.bundle` 의 7개 모듈(loader·segment·manifest·export·pcreg·merge·move)만 읽고 쓴다.
- 다른 pc_id 폴더는 rename·이동·삭제하지 않는다.
- 결정성: `canon_bytes`(ensure_ascii=False, sort_keys, 구분자 `,` `:`, NaN 금지), 정렬 키 명시. 무작위는 ID 생성(uuid4·rand4)에만.

### 9.4 시각 표기

| 자리 | 형식 |
|---|---|
| 저장 시각 | `YYYY-MM-DDTHH:MM:SSZ` + `ts_local_offset` `+09:00` |
| 로컬 날짜 | `YYYY-MM-DD` |
| 사람에게 보이는 시각·팀 묶음 `built_at` | ISO 8601 + 오프셋 |
| 파일 이름 스탬프 | `YYYYMMDDTHHMMZ` |
| 시간 코어 로컬 초·분 | 2020-01-01 00:00 로컬 기준 정수 |
| run_id | `YYYYMMDD-HHMMSS-xxxx`(로컬) |

### 9.5 이름·화면

- 실명·계정·이메일·사내 코드네임을 코드·문서·샘플·시험·프롬프트에 넣지 않는다. 자리표시자만 쓴다. 레지스트리·설정 배포 기본값은 빈 값(중립 예시만).
- 화면: 외부 CDN·웹 글꼴 금지(로컬 SVG), DOM 은 `textContent`·`createElementNS` 로만, LM20 디자인 언어(상단 가로 pill 메뉴, 바탕 `#f2f4f7`, 파랑 `#2a78d6`, KPI 카드, 표 + 펼침 상세, 본문 16px·표 14px), `color-scheme: light`, 관측/추정을 무늬·아이콘으로 구분(색만으로 구분 금지).
- UI·문서·커밋 메시지는 한국어.

---

## 10. 명세 간 불일치 해소 표

'반영 요청' = 해당 명세의 문구를 이 결정에 맞춰 고칠 곳. 고치기 전에도 구현은 '결정'을 따른다. 근거가 같은 여러 어긋남은 한 행에 묶었다.

### 10.A 상위 규율·우선순위·명칭

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-001 | 상위 규율 문서 부재 | C·CM·CT·CP·P 머리말이 `docs/_decisions.md`·`docs/CONTRACT.md` 를 상위로 두지만 docs 에 없음 | 이 문서를 만든다. 결정 메모 구속 조항은 §0.4. `docs/_decisions.md` 참조는 §0.4 + 원문으로 읽는다 | 각 머리말: '상위 = CONTRACT.md' |
| X-002 | 우선순위 선언 충돌 | CM·CT·CP 'COLLECTION 이 이긴다', P '저장 열의 정본', TAB '이 문서가 우선', CM 의 우선 순서(C > 결정 > P > B) | §0.1 순서 + §0.2 소유 표. 선언은 소유 범위 안에서만 유효 | 각 명세 머리말 |
| X-003 | 명칭 잔재 | CT §0·§17.1 의 깨진 개명 주해('LM27→LM27'), CT 산출물 `LM27_*.zip`, CP agent_ver `26.1.0`, P 부록 B·B 머리표·B Q24 의 `loadmon26\docs` 경로, B 관련 명세 목록 누락(CT·H·R·W) | R0-4. 패키지 `LoadMonitor27_풀패키지_<시각>.zip`, agent_ver = 제품 판 `0.1.0`. CT §0·§17.1·미결 1 삭제, B 관련 명세 목록 갱신 | CT §0·§17 · CP §1.2 · P 부록 B · B 머리표·Q24 |
| X-004 | 명세 안 절 참조 오류 | CM '§13 미결'(→§16)·'self-test(§14)'(→§15), CP '미결(§15)'·'§13 미결'(→§17)·exe_meta '§6.4'(→§6.3)·'§4.4 aliases', CT '§9.1'·'§9.2'(→§8.1)·'§12'(→§12.1)·'COLLECT_PC §'(번호 없음), TAB '키링 충돌 §9.6'(→P §9.8), TAB 시험 B25·B26 순서 | R0-3(제목으로 찾는다) | 각 명세 정정 |
| X-005 | 명세 안 시그니처·예시 불일치 | H(tag_evidence·unit_rule_label·field_func·decide_wtype·name_groups·features_of·build_task_label_items·apply_labels·on_new_name·learn_from), R(unit_workflow·domain_workflow·review_layer·peers/agentic/subagent_layer·mount), W(team_tables), B 예시(`ws:W031`·`P012`), CT 예시(`PCH#3f9a`·kid 7hex) | R0-1(인터페이스 절 우선)·R0-2(형식 우선) | 각 명세 본문 정정 |
| X-006 | 경로 ID 개수 | C 는 '21종'이라 하나 표에는 20개, cal.copilot 누락 | cal.copilot 을 더해 21종(§6.5) | C §2 |

### 10.B 배치

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-010 | 번들 루트 | C·CM·CP `data\bundle\…` 대 TAB·P·R `data\pcs\<pc_id>\` | `data\pcs\<pc_id>\`. 결정 §3 '프로그램 폴더 data\'·§10.4 파생물 규칙과 맞고, 형제 4명세가 이미 그쪽 | C §0.2 · CM §4.1 · CP §2 |
| X-011 | manifest | C 번들 최상위 단일 `manifest.json` 대 TAB PC 별 `lm27.manifest/1` | PC 별(다른 PC 파일을 건드리지 않음). '집합'은 모든 PC manifest sha 합집합(§3.7) | C §0.2 · CP §2.3 |
| X-012 | 세그먼트 이름·단위 | C `seg\<seq>_<from_utc>_<to_utc>.jsonl.gz`(kind 통합, 이름에 ISO 콜론 → Windows 파일 이름 불가) 대 TAB `seg\<kind>\<seq6>-<inst8>-<t0>-<t1>-<sha8>` | TAB 형(§3.6) | C · CM · CP |
| X-013 | 내보내기 커서 | C·CP 시각 커서(`cursor.export_utc`, 위치 미정) 대 TAB (파일, 오프셋) | manifest `cursors[install_id]["<kind>/<src>"] = {file, offset, last_ts}`. 시각 커서는 늦게 수확된 과거 사건을 놓친다 | C §8.3 · CP §2.3 |
| X-014 | 원장·todo 영속 여부 | C 번들 최상위 영속 대 결정 §10.4·TAB·R `data\derived\` 파생 | 파생물(병합 후 재생성). '불가' 이력은 pc.json `capabilities.history` 에 영속 | C §5·§6 |
| X-015 | 에이전트 폴더 | C·CM·CT·CP `agent\<install_id>\` 대 결정 §3·TAB·P 평면 `agent\`, TAB 안에서도 §6·B16 이 `agent\<id>\` | **평면 `agent\`**, install_id 는 agent.json 안(한 Windows 사용자에 에이전트 하나). 오케스트레이터 작업 지시의 `agent\<install_id>\` 표기는 C 초안 표기로 보고 이것으로 대체 | C §0.1 · CM · CT · CP §1.1 · TAB §6·B16 |
| X-016 | 로컬 원장 파일 | C `evidence\<kind>\<src>\*.jsonl.gz`, CP `YYYYMM\DD.jsonl.gz`, TAB `YYYYMM\YYYYMMDD.jsonl.gz`(쓰기 날짜) | TAB 형: 쓰기(플러시) UTC 날짜 + gzip 멤버 덧붙이기(§3.10) | C · CP §2.2 |
| X-017 | 작업 이름·뮤텍스·상주 작업 수 | CT 는 Start-TeamsSampler, CP 는 Start-ActivitySampler 를 같은 `LM27-<install_id>` 로 각각 등록, 주기도 다름(120~300초 대 60초). 뮤텍스 `-sampler` 대 `-agent`, C `LM27-<install_id>` | 작업 하나(감독 루프 `agent_main.py`/`agent.ps1`): 샘플 60초, teams.uia `teams.uia.intervalSec`(300초) 자식, 수확 6시간. 뮤텍스 `Local\LM27-<install_id>-agent` | CT §7·§14.2 · CP §1.4·§1.7 |
| X-018 | 정제 감사 위치·형식 | C·CP `store\<pc_id>\sanitize_audit.jsonl`(가변), CM `data\pcs\<pc_id>\audit\privacy_YYYYMM.jsonl`, P·TAB `privacy_audit` 스트림. TAB 내보내기가 id·kind·src 를 덧붙이는데 P §15.2 는 '이 키 외 금지', src='agent' 는 경로 ID 아님 | privacy_audit 스트림(§3.13). P §15.2 는 이벤트 본문 키, id·kind·src 는 세그먼트 봉투 필드로 허용, 이 src 는 단계 이름 | C · CM §4.1 · CP §1.1 · P §15.2 문구 |
| X-019 | Edge 프로필 이름·자리 | C·CM·CP `bridge_profile`(CP 는 `agent\<id>\bridge_profile\`) 대 TAB·B `%LOCALAPPDATA%\LoadMonitor27\edge_copilot\`. B 는 같은 이름 `bridge_profile.json` 을 보정 파일로 씀 | `edge_copilot\`(역할 bridge·owa·teams_web 공용, B Q18 해소). `bridge\bridge_profile.json` 은 브리지 상태 파일 이름으로만 남긴다 | C §0.1 · CM §13 · CP §1.1 |
| X-020 | stage_result 위치 | C·CM·CP `report\stage_result_<stage>.json`(기준 폴더 미정, TAB 배치에 report\ 없음), B `stage_result.json`·`<stage>.result.json` 혼용 | 수집 `data\derived\collect\<run_id>\stage_result_<stage>.json`, 브리지 `data\ai\runs\<run_id>\<stage>.result.json`(R L-1 수용) | C §8.4 · B §2.3·T48·G-B10 |
| X-021 | 분석 결과 위치 | W·H `data\analysis\<run_id>\…` 대 R `data\derived\analysis\<run_id>\…` | `data\derived\analysis\<run_id>\{time,hier,report}\`(R W-2·C-1 수용) | W §7.5 · H §12.1 |
| X-022 | AI 답 저장소가 파생물 아래 | B `data\derived\bridge\store\…`(재생성 불가) 대 TAB 'derived 는 언제든 재생성, 병합 시 다시 만듦' | `data\ai\{store,runs}\` 로 옮긴다. 보존 대상이며 번들 합치기 때 (stage, ck) 별 최신 커밋 합집합 | B §2.4 · TAB §1.1·§1.13 |
| X-023 | 팀즈 체크포인트·하위 원장 | CT `teams.web.checkpoint.json`(위치 미정, 원 ID 키 — 1:1 방은 상대 이름이 키가 됨), `teams_coverage.jsonl`(위치 미정, pc_id 없음) | 체크포인트는 `raw_cursor.json` 의 `teams.web.rooms{<chat_key>}`, 하위 원장은 `data\derived\teams_coverage.jsonl`(셀에 pc_id 포함) | CT §8.3·§11 |
| X-024 | 상태 파일 쓰기 주체 | CP `git_source.json` 위치 미정, `exe_meta.json`·`completion_ledger.jsonl` 은 누가 쓰는지 없음(PS 가 쓰면 lint 위반) | git 상태는 stage_result + pc.json `capabilities["pc.git"]`(git_source.json 폐지). exe_meta 는 파이썬 감독이 정제값만 atomic_write. completion_ledger 폐지(열린 문서 저장은 pc_file op=save 행) | CP §1.1·§5.2·§9 |
| X-025 | 키 위치 | 결정 §10.4 '개인 비밀은 본인 %LOCALAPPDATA%, 키는 번들에 넣지 않음' 대 P H6 키링 정본 `data\keys\`(폴더 동행), CP 에이전트에 키링 사본 | 키링 정본 `data\keys\privacy_keyring.json`(PC 간 같은 키가 있어야 msg_key·who_key 병합이 된다). '번들' 정의(§1.2)에 keys 는 없으며 모든 반출에서 뺀다. 에이전트는 `agent\keys\subkeys.json` 하위 키만. 표시명 사전은 `data\local_only\`. 잔여 위험은 U-3 | CP §1.1 · P Q14 · TAB 미결 1 |
| X-026 | 에이전트 실행 위치 | CP Action = `agent.json.root\collect\Start-ActivitySampler.ps1`, `root` 필드, 파이프도 ROOT(폴더를 옮기면 끊김 — CP §1.1 '이동과 무관'과 모순) 대 TAB bin 사본 | bin 사본 실행, ROOT 참조 금지, agent.json `root` 폐지. 에이전트가 쓰는 PS 스크립트는 설치 때 `bin\<ver>\ps\` 로 복사. agent.json(`impl`, CP 의 `sampler_impl` 아님)·heartbeat.json 필드는 TAB 형(§3.9) | CP §1.2·§1.6·§3.6 |
| X-027 | 설치 진입점·작업 등록 | CP `collect\Install-Agent.ps1` + `Register-Samplers.ps1`, TAB `LoadMonitor27-에이전트설치.bat` → `agent install --only` + `Register-Agent.ps1`. CP §1.3 ⑦ 은 설치 때 pc.json 에 쓰면서 '%LOCALAPPDATA% 만 건드린다'고 함 | TAB 형. 설치 전용은 번들에 `pc.json` 최소 기록만 한다(TAB §1.6.6, D-18 '설치 전용 진입점') | CP §1.3·§1.4 |
| X-028 | 옛 작업 정리 정규식 | CP `^(?:LoadMonitor\d+\|LM27-[0-9a-f]+)-` 은 실제 이름 `LM27-<32hex>` 와 안 맞고 남의 `LoadMonitorNN-*` 를 지움 | `agent.json.prior_install_ids` 에 있는 `LM27-<32hex>` 만 지운다. 남의 작업 미접촉(TAB §1.6.4) | CP §1.4 |
| X-029 | 샘플러 구현 우선순위 | CP PS 먼저 → PY, TAB py → ps → none | py(ctypes) 먼저, 실패 시 ps, 둘 다 실패면 impl=none + R-CLM 또는 R-APPLOCKER | CP §3.5 |
| X-030 | 팀즈 사용 시간 신호 | CT §7.5 `pc_session` src=`teams.uia` + `flags.teams_visible`(P 의 pc_session src·flags 에 없음) | 폐지. 같은 정보는 pc.sampler 행(app_id = teams, 전경 구간)에서 파생한다. 근무 봉투 1차 소유자는 샘플러(CT 미결 4 해소) | CT §7.5 |
| X-031 | pcx_ 대체식 | TAB 식(`"LM27.pcx\|"+COMPUTERNAME+…`), P 는 정규식만 | TAB §1.2 식, 사유 R-NOMACHGUID | P §10.1 주석 |
| X-032 | 진행 중 구간 갱신 | CP §2.2 'live 구간 부팅당 1행 ts_utc 기준 upsert' 대 추가 전용·불변 세그먼트 | upsert 없음. 같은 id 의 새 판을 덧붙이고 로더가 observed_at 최대를 쓴다 | CP §2.2·§4.2 |

### 10.C 식별자·키

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-040 | pc_id 형식 | C·CP·CM `MachineGuid HMAC`(예 `PCH#3f9a`) 대 P H5·TAB 무키 `pc_`+16hex | 무키 `pc_`/`pcx_`(§4.1). 키링이 생기기 전(설치 전용)에도 정해져야 하고 PC 간 같아야 한다 | C §3.1 · CP §1 · CM §5.1 |
| X-041 | rules_ver 형식 | C `pii-2026.10` 대 P·CM·CP `2026.10.0` | `YYYY.MM.N` | C §3.1·§3.5 |
| X-042 | 가명 키 접두·이름 | C 예시 `T#`·`P#`·`M#`·`A#`·`PCH#`, CT chat_key `t`+16hex·author `person_key`(p+16hex)·file_keys `a`+16hex ≤5, P chat_key `h`·who_key `w`·file_keys `d` ≤10, TAB `person_key`=`p_`+12hex(번들 소유자) | P §9.3 형(§4.2). 사람 = `who_key`, `person_key` 는 번들 소유자 전용 | C §3.5 · CT §3.2·§5 |
| X-043 | doc_key 평문 여부와 정규화 규칙 | C 'basename 정규화값', CP 예시 평문(`과제A_열해석_v3`), P H7 HMAC + `doc_norm`(날짜 꼬리 유지), W `fam()`(버전·날짜 꼬리 제거) + `fam_key=HMAC(fam)`, W 의 '`fam(doc_key)`' 는 해시 위 재정규화 | doc_key = HMAC(`doc_fam(name)`) 한 함수(§4.3, W 의 FAM_TAIL 규칙, P Q20 해소). 범용 이름은 시간 코어가 dir_keys 로 구분(`fam_key`). P `doc_norm` 폐지 | C §3.1 · CP §3.4·§5.5 · P §9.3 · W §2.2·§4.1 |
| X-044 | 레코드 id 식 | C `sha1(src\|pc_id\|ts_utc\|msg_key_or_doc_key\|body_hash)` 에서 body_hash 미정의 | P §10.1(주키 후보 순서, 정제문 \x1f 연결 sha1) | C §3.1 |
| X-045 | msg_key 재료 | C `hash(date+chat_key+author_key+HH:MM+body_hash)`(HMAC 이후 값), CT·P 원문 재료, 날짜 기준(로컬·UTC) 미정 | 정제 전 원문으로 HMAC, 대체 재료의 날짜 = 수집 순간 오프셋 기준 로컬 날짜(§4.2) | C §3.2·§7.2 · CT §5 |
| X-046 | *.copilot 행 msg_key | C 필수, B 비움(Q23③), B 대안 `cp:`+sha256 은 P 형식 위반 | 'cp' 재료로 HMAC 해 형식(`m`/`e`+24hex)을 지키고, 병합에서 뺀다(§4.2) | B §8.1 · C §3.2 |
| X-047 | unit_id 분류 | TAB '행에 저장하는 로컬 키' 대 P 분석 산출(purpose unit) | 분석 산출 ID, 증거 행에 저장하지 않으며 팀 묶음에 싣는다 | TAB §2.4 표 |
| X-048 | role_id 입력 | TAB R-8 field·function 이름 대 H 코드 | 코드(§4.4) | TAB §0.4 R-8 |
| X-049 | need_id 형식 | TAB 예시 `n_01` 대 R `n_`+sha1[:6] | R 식 | TAB §2.3 예시 |
| X-050 | 토큰 안 ID 길이 | P 토큰 ID 1~16자 대 H TOKEN_RX 1~24자·REG_ID 24자 | 토큰에 들어가는 레지스트리 ID(과제·고객사·협력사)는 ≤16자, 그 밖 REG_ID 는 24자 | H §4 TOKEN_RX |
| X-051 | 함수 이름 충돌 `tokens_of` | P `scan.tokens_of(masked)->list`, H `match.tokens_of(text)->set`(규칙 다름) | P 이름 유지, H 는 `match_tokens` | H §4·§12.2 |
| X-052 | dir_keys 미등재 | H X3 `pc_file.dir_keys`(s+16hex ≤3), W `pc_file.folder`(상위 폴더 해시 2단계), P·CP 에 없음 | `dir_keys` 열 추가, W 의 folder = `dir_keys[:2]`, purpose `dir`(AGENT_PURPOSES 포함), 팀 금지 접두에 `s` | P §10.2·§9.4·§14.3 · CP §5.5 · W §2.2 |

### 10.D 레코드·열

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-060 | 저장 텍스트 열 | C `subject_tokens` 저장(W 소비) 대 P H3 `*_masked` 저장 + 파생(H 소비), CM 미결 1·CT 미결 2 | `*_masked` 저장, `subject_tokens` 는 `lm27.normalize.load` 가 `tokens_of` 로 붙이는 파생 열. W·H 모두 파생값을 쓴다 | C §3 · CP §9 · CM §16 · CT §17 |
| X-061 | 열 정본 | P §10 이 C §3 에 없는 열(kid·san·act_cues·priv_*·ad_*·sender_*·rcv·attach_*·busy·location_class·author_key·file_keys·chat_title_masked·priv_score_base·fg_exe·app_class·site_class·event_class·path_key·name_masked·root_id·op·size_bucket·commit_key·n_files·exts·cpu_core·text_masked·project_id·role_*)을 정의 | 열 이름·형은 P §10, 뜻은 C §3(§0.2). C §3.2 표는 P 를 인용하도록 바꾼다 | C §3 |
| X-062 | CM 저장 열 이름 | CM §3.3 초판 이름(conv_key·peer_keys·folder_class·cat_private·sensitivity 최상위·n_attendees·cal_key·start_utc/end_utc·organizer_is_me·recurring·all_day·response 문자열) | P H2 이름(thread_key·counterpart_keys·folder_role·flags.*·n_participants·msg_key `e`·ts_utc/ts_end·flags.response int) | CM §3.3 |
| X-063 | 원시 필드 이름 | CM·CT 원시 필드가 P §10.2 원시 이름과 다름 | P 원시 이름(§3.5 대응표) | CM §3.1·§3.2 · CT §3.1 |
| X-064 | 원시 kind·src | CM 원시 필드 `kind`·`src`, P 는 `_kind` 라우팅·src 는 rc.src 만 | P 형 | CM §3 |
| X-065 | my_addrs 전달 | CM 레코드마다 원시 필드, P `RecordContext.my_addrs`(PS 파이프 전달 방법 없음) | 파이프 첫 줄 `{"_meta":{"my_addrs":[…]}}`(메모리만, 저장 안 함), in-process 는 `make_record_context(my_addrs=…)` | P §3.5 · CM §5.6 |
| X-066 | rcv 열거 | CM `to cc bulk unknown na`, P `to cc bulk na` | `unknown` 추가(R-NOADDR·B단 생략 경로가 검증에 걸리지 않게) | P §10.2 |
| X-067 | junk·deleted 처리 위치 | CM 수집 단계에서 제외, P 정제기가 junk 광고 확정·deleted 폐기 | 수집기는 deleted·junk·drafts·outbox 를 읽지 않는다(1차), 정제기 규칙은 반입·OWA 등 폴더 표시가 오는 경로의 방어선(2차) | — |
| X-068 | 열거값 차이 | chat_type self(P 추가), box other(P 추가), folder_role subfolder·other(P 추가), sensitivity C 0~2 대 P·CM 0~3, layer C 표 'L0~L4' 대 C 메모·P L0~L3 대 CP §13.1 L4 | P 열거. layer 저장값 L0~L3, L4(산출물)는 분석 개념 | C §3.2·§3.3 · CP §13.1 |
| X-069 | flags 키 | C §3.3 공통 열거에 없는 키를 C cal 메모가 사용(response·meeting_status), P 허용 키(edit·cat_private·body_unsub·license·no_key·inprivate) C 에 없음, C flags.ad 뜻 다름, W 가 notice·deferred·utc 를 소비 | kind 별 허용 키 표(§3.3)로 대체. `deferred`·`teams_notice`(mail), `n_part_est`·`author_inherited`(teams), `autosave`(pc_file) 추가. notice 는 파생, utc 는 utc_suspect + 설정 | C §3.3 · P §10.2 · W §2.2 |
| X-070 | 팀즈 첨부 키 | C §3.2 teams `attach_keys` ○, P teams `file_keys` | attach_keys 는 mail 전용, teams 는 `file_keys`(d16 ≤10) | C §3.2 |
| X-071 | 라이선스 행 app_id | C 'app_id = 제품명', P flags.license + 카탈로그 slug | P | C §3.2 · CP §8 |
| X-072 | C 내부 필수 표기 | direction 공통 필수인데 표는 '—', ts_end 공통 필수인데 manual ○, 원장 reason(단수) 대 pc.json reasons(복수) | direction·ts_end 는 null 허용(§3.1), 원장 필드도 `reasons`(복수) | C §3.1·§5.2 |
| X-073 | idle_sec 처리 | C '음수·비단조는 0', CP 모듈로 식(항상 ≥0), P 범위 [0,4294968] | CP 모듈로 식 + P 범위 | C §3.2 |
| X-074 | fg_exe 형식 | CP '확장자 제거', P `….exe` 소문자 | P 형식 | CP §3.1 |
| X-075 | 창 분류 열 이름 | CP `title_class`·`app_class` 혼용, P `app_class`·`site_class` | `app_class`(18값: P 16값 + `remote`·`meeting`), `site_class`. `title_class` 이름 폐지 | CP §3.4 · P §10.2 |
| X-076 | pc_file 열 | CP `folder_class`(sharepoint 없음), op save 없음, C §3.2 는 pc_file app_id 필수인데 CP 예시는 null | P `folder_role`·op `save` 포함, app_id 는 null 허용(파일만으로 앱을 모를 수 있음) | CP §5.5 · C §3.2 |
| X-077 | 이벤트 분류 | CP 에 event_class 정의 없음, BOOT_IDS 에 21(RDP)·SLEEP_IDS 에 23·24, on 이벤트 1·107·507·7001·25 누락, L0 목록 누락 | 이벤트 ID → `event_class` 대응: 6005·12·100 boot / 6006·13·1074·200 shutdown / 6008·41 crash / 42·506 sleep / 1·107·507 wake / 7001·21·25 logon(21·25 는 rdp_connect 도) / 7002·23 logoff / 24 rdp_disconnect / 4800·4801 lock·unlock(보너스). boot·shutdown·sleep·wake·crash = L0, 나머지 L1 | CP §4.1·§4.3·§13.1 |
| X-078 | event-cap 꼬리표 | CP confidence 표에 event-cap 0.4 가 있으나 §4.2 는 20h 절단을 하지 않음 | event-cap 폐지 | CP §4.3 |
| X-079 | 샘플러 layer | CP 'L3 고정' 대 §13.1(session=L1, idle=L2) 대 P(L2·L3) | 전경 앱이 idle·system 이 아니면 L3, 아니면 L2(§3.2) | CP §3.1 |
| X-080 | 샘플러 레코드 누락 열 | CP 본문은 priv_class·site_class·inprivate·app_class 포함이라 하나 예시에 없음, interval 필드처럼 사용 | P 열 그대로, interval = ts_end − ts_utc | CP §3.1 |
| X-081 | manual 열 | CP start_utc·end_utc·kind 없음, P ts_utc·ts_end, W `Man.kind` 9종·ref·key, R retract 레코드 요구, 별도 worklog 파일 | P 열 + `man_kind`·`ref_keys`·`retract_of`(§3.2). 수동 기록·확인 응답·취소는 모두 manual 행 | P §10.2 · CP §10 · W §2.7 · R §5.2.4 |
| X-082 | copilot_ev kind 잔존 | CM §11.4·CT §9 `kind=copilot_ev`, P H1·B §8.1 폐기 | 폐기. kind = mail·cal·teams + src `*.copilot` | CM §11.4 · CT §9 |
| X-083 | 증인 행 텍스트 열 | B §8.1 subject_masked(메일·일정)·body_masked(팀즈) 대 P·CM·CT `text_masked`≤200 | `text_masked` | B §8.1(Q23④) |
| X-084 | cal.copilot 경로 | B·P 사용, C §2 표에 없음 | 경로 ID 추가, 어댑터 `Get-CalViaCopilot.py`, 단계 lookup_calendar(기본 꺼짐) | C §2 |
| X-085 | cal.import 형식·반입 CSV 열 | C ICS 만, CM ICS·CSV, CSV 열 '정의 없음' | ICS·CSV 둘 다, CSV 헤더 = P 원시 이름(§3.5) | C §2 · CM §11.5 |
| X-086 | teams.web confidence | C §3.4 표에 teams.web exact 없음, CT 0.8 | 0.8(§3.4) | C §3.4 |
| X-087 | CT 저장 열의 schema·source·ts_local·최상위 플래그 | CT 예시 `schema:"teams/1"`·`source`·`ts_local`(P 표에 없어 저장 불가), `mentions_me`·`has_file` 을 최상위 열로 둠(P 는 flags), P 공통 열(id·kind·act_cues·counterpart_keys·confidence·observed_at·priv_why·flags) 누락 | schema 는 세그먼트 머리말에만, mentions_me·has_file 은 flags, 공통 열은 P §10.1 전부 | CT §3.2 |
| X-088 | priv_class·chat_type 열거 | CT priv_class work·private·social(P 는 +unknown·media), CT 원시 chat_type unknown 허용(P 저장 enum 에 없음) | priv_class 는 P 5값. 원시 unknown 은 저장 때 `group` + n_participants 2 + `flags.n_part_est` | CT §3.2·§4.2·§6 |
| X-089 | abs_hint 이름 충돌 | CT obj{n_part_est, cont_inherited, date_unknown}, P enum(부재 힌트) | abs_hint 는 P enum. CT 의 구조 표식은 flags `n_part_est`·`author_inherited` + ts_precision unknown | CT §3.2 |
| X-090 | 화행 소유 | CT act·act_score 를 정제 경계 `lm27.privacy.classify.act_of()` 가 채움, C·P act="" + act_cues, P classify 에 act_of 없음 | 저장 act="" + act_cues. 화행 7종 판정은 적재 시 `lm27.normalize.act`(CT §6 어미 규칙), 코파일럿 speech_act(by=ai, conf h·m)가 덮고, 수동 태깅이 최우선. act_score 폐지 → conf | CT §3.2·§6 · CM §9 |
| X-091 | 수동 태깅 위치 | CT `lm27.tagfeed` | `lm27.normalize.act.save_tag` + `data\local_only\tag_feedback.json` | CT §10 |
| X-092 | 정제 kind 이름 | CP §0·§13.3 이 P 초판 kind(window·session·file·git·compute·worklog)를 쓰고, §13.3 '임시로 SegmentWriter 통과'와 §17 '전용 스키마 없이는 저장 불가'가 모순 | 정제 kind = 저장 kind 8종(P H1). pc.events·pc.compute 무텍스트 스키마는 P §10.2 에 이미 있다(CP §17 미결 해소) | CP §0·§13.3·§17 |

### 10.E 정제 인터페이스

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-100 | sanitize_record 시그니처 | C `(kind, record)->(record\|None, audit)`, CP `("window", raw, rc)`, P `(kind, raw, rc)->RecordOutcome` | P. 2-튜플이 필요하면 `as_pair()` | C §11 · CP §3.6 |
| X-101 | RecordOutcome 필드 | CM `outcome`, P `status`(+ no_key·folder_excluded) | `status` | CM §4.4 |
| X-102 | 수집기 import | CM·CT `from lm27.privacy import sanitize_record, SegmentWriter` 대 P lint(수집기는 `lm27.privacy.sanitize` 만, SegmentWriter 는 저장소 소유) | P lint. SegmentWriter 는 `lm27.store`(§2.3) | CM §4.4 · CT §13 |
| X-103 | 정제 파이프 호출 형식 | C·CM·CT `python -m lm27.privacy.sanitize_stream --kind --src --pc --out`, CT·CP `lm27_pipe.py --source --pc-id --root`, P `lm27_pipe.py --kind --src --pc --out [--mode]`(-m 금지) | P 형 하나(§7.3) | C §11 · CM §4.4 · CT §7.1·§13 · CP §3.6 |
| X-104 | 혼합 라우팅 | CM `--route-by-kind --src-map … --seg-dir`(줄의 kind), P `--route-by-kind --out {kind}`(줄의 `_kind`, src 하나 → cal 행 src 가 mail.com 이 됨) | 기본은 kind 단일 파이프 둘. 혼합은 `_kind` + `--out {kind}` + **`--src-map` 필수**(P 확장) | P §3.5 · CM §4.4·§16 |
| X-105 | 파이프 모듈 이름 | CT·CP `lm27.privacy.pipe.main()` | `lm27.privacy.sanitize_stream.main()` | CT §13 · CP §3.6 |
| X-106 | 파이프 출력 대상 | C·CM 세그먼트 직접 쓰기(`--out <seg.jsonl.gz>`), CP store 일자 파일, TAB 세그먼트는 write_segment 만 | 언제나 에이전트 store 일자 파일 `--mode append`. 세그먼트는 [수집]의 export 단계만 쓴다. `--mode new` 는 시험·일회성 출력용 | C §11 · CM §4.4 |
| X-107 | 파이프 종료 코드 번역 | 정의 없음 | §8.2 | CM §4.4 |
| X-108 | 파이프 요약 줄 | CM 예시에 mode·out_sha256 없음 | P §3.5 형 | CM §4.4 |
| X-109 | PS 쓰기 금지 목록 | CT·CP §3.6 은 Out-File·Add-Content·>> 만 인용 | 전체 목록(Out-File·Set-Content·Add-Content·Export-Csv·>·>>), 대상 data\·store\·%LOCALAPPDATA%(lint L-09) | CT §13 · CP §3.6 |
| X-110 | P 에 없는 공개 함수 | TAB 이 `forbidden_codes(s, gctx)` 재수출·`write_context_cache` 를 P 함수로 기대 | P 공개 API 에 둘 다 추가(§2.2) | P §3.3 |
| X-111 | 게이트 문맥 생성 | B 가 `GateContext(...)` 직접 생성·`AuditSink(<경로>, …)`(생성자 첫 인자는 SegmentWriter), web_grounding 미전달, StageSpec·GateItem 재수출 불명 | `make_gate_context(..., web_grounding=web_exposed)`·`AuditSink.open(...)`. P 가 `StageSpec`·`GateItem`·`GateContext`·`GateResult` 를 재수출 | B §9.2 · P §3.3 |
| X-112 | 웹 노출 강화 규칙 | P §13.3(웹 근거 켜짐 → person_tokens plain, ip·url·path 잔여 항목 제외) 대 B §9.7 S1~S5(web_exposed — unknown 포함) | 합집합을 적용하고 발동 조건은 더 엄격한 `web_exposed`. P 쪽 규칙은 `web_grounding=True` 로 켠다 | P §13.3 · B §9.7 |
| X-113 | 게이트 표기 | P StageSpec.name 예시(classify·refine…) 대 B 단계 id, P '`gate_prompt_text` 는 L3' 대 B L2, 결과 봉투 counts 접두 유무 | name = 단계 id, 호출은 L2(exchange), 결과 봉투 gate 키는 P 의 `drop:`·`remask:` 접두를 뗀 이름으로 옮긴다(표기 규칙만) | P §13.3·§13.4 |
| X-114 | P 내부 목록 | §3.2 dropped 목록에 folder_excluded 없음, gate_copilot 감사 키·AuditSink counter(merge·selftest·gate_team) 누락, 요약 `errors` 대 감사 `err`, 일부 함수·파일 모듈 위치 누락, `extra_stopwords` 적용 방법 없음 | 목록 보강(§2.2·§6.4), errors/err 는 형이 달라 그대로, `extra_stopwords` 는 NAME_STOP 합집합 | P §3.1·§3.2·§15 |
| X-115 | 본인 표시명 저장 | CT `teams.selfNames` 를 HMAC 로만 저장 → P self_names(평문 치환)·재생 모드와 안 맞음 | 설정 키 폐지. `person_dir.json` 의 `self:true` 항목(로컬 전용 평문) + OS 표시명. 재생 모드는 이 파일로 판정 | CT §4.4·§16 |
| X-116 | 에이전트 사유 코드 미등재 | TAB 목록에 R-NOKEY 없음, CP 에 R-RULESMISMATCH·R-NOKEY·R-APPLOCKER 없음 | §6.1 단일 표 | TAB · CP §12.1 |

### 10.F 수집 동작

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-120 | 수집기 rc 세부 | CT Get-TeamsWeb rc 1 이 '4 흡수', CM R-NOIDX 'exit 1'·'1(또는 3)', CM 예산 rc 0+partial 대 C 예시 rc 2 | C §8.4 그대로, 막힌 사유가 있으면 rc 3, 예산은 rc 0 + partial(§8.1) | CT §8.1·§14.3 · CM §6.1·§6.4 · C §8.4 예시 |
| X-121 | collect 명령 rc | C 0·2·1, TAB '반복 rc 4 = 새것 없음'·'읽기 전용이면 rc 3' | 공통 CLI rc 0·1·2·3·4(§8.3) | C §8.4 · TAB §1.7 |
| X-122 | stage_result.rc 체계 | C 예시 rc 2 + budget(rc 2 는 로그인 필요) | `rc` = 수집기 원 rc, 예산은 `state=partial`·`stop_kind=budget`·`reason=R-BUDGET` | C §8.4 |
| X-123 | 단계 상태 열거 | CM `ok partial done zero_ok`, B `done partial failed skipped` | `done partial failed skipped`. zero_ok 는 셀 상태 | CM §4.3 |
| X-124 | 새 Outlook 시나리오 | C P1 'mail.com/index blocked:R-NEWOL', CM #1 'index 는 시도' | index 를 시도하고 Outlook 항목이 없으면 `blocked:R-NEWOL` 로 남긴다(둘 다 참) | — |
| X-125 | R-NOIDX 트리거 | C 'Outlook 항목 0' 포함, CM 은 R-ONLINE·R-NEWOL·R-IDXPOLICY 로 분해 | CM 분해, R-NOIDX = 서비스 꺼짐·연결 실패만 | C §4.2 |
| X-126 | '불가' 확정 기준 | C 같은 사유 서로 다른 날 2회, TAB verdict 마지막 ok 이후 fail 일수(사유 무관), 어휘도 다름(todo state 대 verdict) | §6.4 verdict 하나(같은 확정 가능 사유 + 서로 다른 날 N회 + probe_sig 동일 + TTL), todo state 는 verdict 에서 파생 | C §6.2 · TAB §1.5 |
| X-127 | 확정 근거 제외 범주 | C 는 R-TRANSPORT 만, CP 는 R-STUCK·R-SAMPLER-ZOMBIE 도 | §6.1 '확정' 열 | C §6.2 · CP §12.1 |
| X-128 | R-* 단일 표 미등재 | CT R-WEBSEL·R-LISTVIRT·R-ROOMGONE, CP 6종, TAB 14종, P R-NOKEY | §6.1 에 모두 등재(+ R-TEAM-DNS·R-TEAM-PROXY) | C §4.2 |
| X-129 | 샘플러 실행 차단 코드 | CP §1.3·§3.5 R-CLM 대 §12.1·§15#9 R-SAMPLER-CLM, TAB R-CLM·R-APPLOCKER | R-CLM 또는 R-APPLOCKER, R-SAMPLER-CLM 폐지 | CP |
| X-130 | R-SAMPLER-ZOMBIE 트리거 | CP §1.6 '미귀속 좀비' 대 §12.1 '생존 조건 ③ 거짓' | 생존 조건 ③(store 신선도) 거짓 | CP §1.6 |
| X-131 | 일자 합성 예외 | C §5.3 '출처 중 최선 값', B·R 'Copilot zero_ok 는 다른 출처 근거 없음을 덮지 못함' | 예외 채택(§3.11) | C §5.3 |
| X-132 | 결정 v2 OWA 규칙 누락 | CM §11.3 에 '보낸 편지함은 항목을 열어 분 단위, 받은 메일은 날짜만' 없음 | 계약 조항(§6.5 mail.owa) | CM §11.3 |
| X-133 | 팀즈 '놓친 활동' 알림 메일 | 결정 §10.1 규칙이 CM·CT 에 없음, W 는 입력으로 기대 | 표식은 CM(정제기가 발신 도메인·제목 패턴으로 `flags.teams_notice`), 해석은 W(팀즈 수신 존재 증거, 시간은 상한으로만) | CM §10 · P §10.2 · W §2.2 |
| X-134 | 탐침 누락 | C 에 결정 v2 의 번들 도착 경로·/api/hello·COM A/B 분리·계정 등급·웹 근거 탐침 없음, CT P-WEB·P-TEAMS 확장 미등재, P-CP 수집기 이름 상이 | §6.7 표(P-BUNDLE·P-TEAM·P-WEB 추가, P-CP = `probe_copilot.py` → `lm27.bridge.probe(lookup=True)`) | C §4.1 · CT §12 |
| X-135 | COM 상한 키 | CM 상한 20000·8000 을 COM 경로 키 없이 언급 | `mail.com.capMail`·`mail.com.capCal` | CM §5.9 |
| X-136 | CM 설정 표 누락 | `collect.mail.period` 가 §16 요약에 없음, `config.owner` 미등재, `excludeFolderNames` 의미론(내장 ∪ 추가) | §5.2·§5.4, 목록 의미론은 P §17.1 | CM §13·§16 |
| X-137 | 시험 주입점 | B `LM_NO_BROWSER` 가 C 목록에 없음 | §11.3 단일 목록 | C §10 |
| X-138 | 팀즈 증인 기본값 | CT `teams.copilot.enabled=false` 대 B `bridge.stages.lookup_teams=true` | `bridge.stages.lookup_teams=true` 하나. 능력 verdict 가 불가면 자동 skipped | CT §9·§16 |
| X-139 | CDP Origin 허용 | CT '자기 포트로만 늘 지정', B '기본 없음, 403 일 때만 explicit' | B 규칙(§9.1) | CT §8.1 |
| X-140 | 웹 수집기 CLI 공백 | CT --include-channels·--include-activity 를 끄는 플래그 없음, `--force` 뜻 미정의, `--pc-id`·`--root` | `--no-channels`·`--no-activity` 추가, `--force` = 체크포인트 무시하고 기간 전체, `--pc` 로 통일, `--root` 폐지 | CT §8.1 |
| X-141 | 예산·상한 키 공백 | CT teams.uia 별도 예산 키 없음, 증인 행 상한 50 키 없음 | `teams.uia.budgetSec`, `bridge.lookup.maxRows` | CT §7.2·§9 |
| X-142 | 작업 시험 주입 부적합 | CP Get-OfficeMru `-MruTextDir`(레지스트리 출처와 안 맞음), Get-FileActivity 인자 미정의 | Get-OfficeMru `-MruRegFile`(reg 내보내기 텍스트 재생), Get-FileActivity 인자 = 공통(§7.3) + `-RecentDir`·`-MruTextDir`·`-NoToolMru` | CP §5.1·§5.3 |
| X-143 | 파일 뭉치 키 이중 | CP `pc.fileBurstN`('이전 판 값'), W `time.envelope.fileBurstN`(8) | `pc.files.burstN`=8 하나(수집 상한 ×5+1, 분석 뭉치 판정 — 이전 판도 한 값 공유) | CP §16 · W §8.2.2 |
| X-144 | 고착·활동 임계 상수 | CP `STUCK_COVER_H`·`STUCK_IDLE_RATIO`·`idleActiveSec`(레지스트리 밖), W 키·하드코딩 | `time.envelope.stuckCoverH`·`stuckIdleRatio`·`idleActiveSec` | CP §3.1·§3.7 · W |
| X-145 | 작성 완료 점수 소유 | CP `lm27.pc.completion.score_doc`(정수 가중·A/B/C) 대 W `episodes.completion`(소수 가중·e2High/e2Low), 최종 이름 낱말 목록 두 벌 | W 가 유일 소유. CP 는 입력만 보장, `lm27.pc.completion` 폐지. 최종 이름 판정(`flags.final_name`)도 `episode.finalWords`(context_cache 로 에이전트에 전달) | CP §7 · W §4.9.2 |
| X-146 | 라이선스 수집 범위 | 이전 판 전 사용자 수집 결함 | 본인 사용자·호스트 행만, 원시 금지(user·host·server) | — |
| X-147 | PS lint 예외 | CP 예외 heartbeat.json·sampler_errors.log(agent\<id>\store\) | ps 감독 `agent.ps1`·수확 `harvest.ps1` 의 원문 없는 운영 파일(`agent\heartbeat.json`·`agent\run\{harvest_done.json, .harvest.lock}`·`agent\logs\`)만(X-307 로 보강) | CP §14.1 |
| X-148 | UIA 합성 chat_key | CT 미결 5: PC·언어 간 불안정 | 웹 chat_key 우선 병합 + UIA 메시지는 날짜 포함 msg_key 로 병합. 방 매핑 보강은 O-7 | CT §17 |

### 10.G 능력 기록

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-160 | pc.json 그릇 | C·CM `capability`(단수)·`confirmed_blocked{src:n}`·평면 측정값, TAB `capabilities{ok,value,reasons,history,verdict}`, B `{state, ok, reasons, confirmed_days, verdict, until, checks[{date,result}]}` | TAB 그릇 + history 항목에 reasons·probe_sig. 기록은 `record_probe`, 판정은 `verdict()` 하나. 브리지 내부 상태(suspect·TTL)는 bridge_profile.json(B Q19 해소) | C §4.4 · CM §14 · B §7.13 |
| X-161 | 확정 횟수·TTL 키 | `confirmBlockedCount`·`bridge.capability.confirmDays`(둘 다 2), `bridge.capability.ttlDays`(14, TAB 에 없음) | `collect.confirmBlockedCount`·`collect.confirmTtlDays` | B §3.4 |
| X-162 | pc.json 기타 필드 | C label·tz 문자열·utc_offset·agent_ver '26.1.0', TAB label_auto/label_user/host_display/host_class·tz 객체·roles·installs·visits | TAB 형 | C §4.4 |

### 10.H 진입점·런타임

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-170 | 진입점 형식 | C `python -m lm27 collect`, TAB `python\python.exe <단일 진입점>`, P H8 '-m 은 동봉 파이썬에서 깨짐' | `<ROOT>\lm27_cli.py` 단일 진입점(`lm27 <명령>`), -m 금지 | C §8 · CM · CP §12 |
| X-171 | 단일 진입점·[수집] bat 이름 | TAB '진입점 이름은 공용 규약', [수집] bat 이름 없음 | `lm27_cli.py`, `LoadMonitor27-수집.bat`(§7.2) | TAB §8.1 |
| X-172 | 시간 오프셋 저장 | 결정 §10.3 '오프셋(분) 저장', C·P 문자열 `+09:00` | 문자열 저장(분 단위 정확), 적재기가 분으로 변환 — 결정의 뜻을 만족 | — |
| X-173 | 근무 시간대 설정 두 벌 | TAB `person.work_tz_offset_min`, W `time.tzOffsetMin` | `time.tzOffsetMin` 하나 | TAB §7.1 |
| X-174 | 로컬 초 기준점 | W lsec 기준 2026-01-01(2025 자료가 음수), R 같은 기준 | 2020-01-01 00:00 로컬 | W §3.1 · R §4.1 |
| X-175 | 쓰기 API 세 갈래 | CP `lm27.store.append`·`SegmentWriter`·파이프 | `lm27.store.SegmentWriter` 하나(파이프·PY 수집기·감독), 번들 세그먼트는 `write_segment` 만 | CP §3.6·§13.3 |
| X-176 | 브리지 쓰기 층 | B `fsio.py` 자체 구현, TAB `fsx` | fsio 는 fsx 를 감싸는 얇은 층(허용 파일 목록은 B G-B7 유지) | B §2.2 |
| X-177 | 설정 레지스트리 파일 | W `config/schema_time.json`·`lm27\time\registry.py`, P `config.default.json`, R 항목 메타 요구(G-1) | `config\settings_registry.json` + `lm27.config`(§5.1) | W 부록 A · P §17 |
| X-178 | 정규화·분석 파이프라인 명세 부재 | 화행·병합·근태 대응·analyze 실행 계약(run_status·current.json·--rerun)을 기대하나 소유 명세 없음 | 이 문서 §2.7·§2.13·§3.23 이 임시 정본(O-1) | R §13 A-1 |

### 10.I 설정 키 표기

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-180 | 표기 규칙 | C·CM·CT·CP·B·W·H·R camelCase, P·TAB snake_case(team.server_host·agent.heartbeat_stale_s) | camelCase + 단위 접미(§5.1), 개명표 §5.4 | P §17 · TAB §3.2·§7 |
| X-181 | parallelMax 충돌 | CP 본문 무네임스페이스 `parallelMax`, W `time.queue.parallelMax`=5.0(다른 뜻) | `collect.parallelMax`·`time.queue.parallelSuspect` | CP · W §8.2.4 |
| X-182 | 에이전트 키 이중 | CP agent.sampler.*·heartbeatStaleMin(10분) 대 TAB agent.sample_interval_s·heartbeat_stale_s(600초) 등 | §5.2 agent.* 표 | CP §16 · TAB §7.1 |
| X-183 | 조회 키 이중 | CM mail.copilot.chunkDays(10)·maxRows, CT teams.copilot.chunkDays(7)·행 50, B bridge.lookup.windowDays(7)·maxRows(100) | `bridge.lookup.*`(B Q23①) | CM §13 · CT §16 |
| X-184 | Edge·로그인 키 이중 | mail.owa.profileDir·port(9333 — 이전 판 코파일럿 포트와 충돌)·loginWaitSec, teams.web.profileDir·port·loginWaitSec 대 bridge.edge.*·loginWaitMin(G-B12 관문 실패) | bridge.* 하나, 웹 수집기는 `EdgeSession.open(role="owa"\|"teams_web")` 만 | CM §13 · CT §16 |
| X-185 | 분류 단계 스위치 이중 | `hier.copilot.enabled` 대 `bridge.stages.task_label` | 후자 | H §13.3 |
| X-186 | 표준일·평일 원천 셋 | `mm.stdDayMin`, 레지스트리 `calendar.std_day_min`, calendar.json; `time.window.weekdays` 대 달력 weekdays | 달력 값만(§3.21) | W §8.2 |
| X-187 | 근무창 원천 둘 | W `time.window.*`, TAB 레지스트리 `calendar.std_window`·`lunch`·`night` | 개인 `time.window.*`, 레지스트리 calendar 에서 창 필드 폐지 | TAB §3.10 |
| X-188 | 공공 도메인 계급 이름 셋 | H 설정 `hier.publicSuffix`, 레지스트리 `public_domain_classes`, 코드 `public_suffix` | `hier.publicDomainClasses` · 레지스트리 `public_domain_classes` | H §13.1 |
| X-189 | 미등재·죽은 키 위험 | H `team.registry_timeout_s`(TAB 표에 없음), H 가 '읽는다'는 `team.registry_refresh_h` 를 본문에서 안 씀 | `team.registryTimeoutSec` 등재, `team.registryRefreshH` 는 team.client 가 읽음 | H §3.1 · TAB §7.1 |
| X-190 | 본문 짧은 이름 | R 본문(ontologyMinRel·peerMinMsgs·minStepSec…), CP 본문(mru.officeVersions·filePoll.*·programsExtra·config.solverProcesses·completion.*·compute.*·license.*·fileBurstN·files.budgetSec·flushSec·flushN) | §5.2 전체 이름 | R §4 · CP 본문 |
| X-191 | 경로형 설정 | CT `teams.privateChatsFile` | 폐지(경로는 lm27.paths) | CT §16 |
| X-192 | 기본값 미정 | CP pc.watchExtensions·excludeFolderNames 'LM24 목록', 탐침 임계 R-SUBFOLDER·R-STALE 미명명 | 내장 목록 이식(list(+-)), `probe.subfolderRatio` 0.3★·`probe.ostStaleH` 72★ | CP §16 · C §4.2 |

### 10.J 시간 코어 입력·출력

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-200 | pc_file → DocE | W DocE.kind {create,save,export,open,result}·folder·autosave 대 CP op {create,modify,open}·P {+save}, export 는 flags.pdf_export, result 원천 없음 | DocE.kind: modify·save → save, create → create, open → open, `flags.pdf_export` 면 export, pc_compute 결과 파일이면 result(시간 코어가 fam 일치로 파생). folder = dir_keys[:2], autosave = flags.autosave | W §2.2 |
| X-201 | 앱 분류 대응 | W Samp.cls {office,cad,cae,sim,eda,ide,eng,browser,mail,chat,meet,remote,explorer,system,other} 대 P·CP app_class | 대응: office·pdf·viewer→office, cad→cad, sim→sim(W 의 cae·sim), eda→eda, ide→ide, 카탈로그 기타 공학→eng(앱 cat 이 공학 범주), browser→browser, mail_work→mail, chat_work·messenger_private→chat, meeting→meet, remote→remote, explorer 는 system 의 exe 가 explorer.exe 일 때, idle·system·media·game·other→system·other. WORK_CLS = office·cad·sim·eda·ide·eng | W §2.2.1 · P §10.2 |
| X-202 | 세션 상태 대응 | W Samp.state {active,idle,locked,disconnected,sleep} 대 저장 {active,locked,disconnected,remote} | active 이고 idle_sec ≤ `time.envelope.idleActiveSec` → active, 넘으면 idle, remote 는 idle 기준으로 active·idle(flags.remote), sleep 은 pc.events 의 sleep 구간. Samp.priv 의 social 은 pc_session 에서 나오지 않는다(W 쪽 처리는 무해) | W §2.2 |
| X-203 | Msg 방향·flags | W Msg.dir in·out 대 teams sent·received·unknown, notice·deferred·utc 원천 없음 | sent→out, received→in, unknown → in 취급(앵커 아님, 수신 크레딧만) + audit '방향미상'. flags 는 X-069 | W §2.2 |
| X-204 | Meet 필드 | W status 문자열·organizer·attendees·n_att·series_key·personal·category 대 저장 flags.response(int)·organizer_me·counterpart_keys·n_participants, W 내부에서 dataclass 에 series_key 없음 | response 0~5 → none·organizer·tentative·accepted·declined 대응(P §10.2), meeting_status 5·7 → cancelled, organizer = flags.organizer_me, attendees = counterpart_keys, series_key = thread_key, personal = sensitivity≥1·cat_private·priv_class private, category = `lm27.normalize.absence.meet_category`(abs_hint·location_class) | W §2.2.1 |
| X-205 | 커버리지 축 이름 | C `kind_axis`, W `coverage[(date, axis)]` | `kind_axis` | W §2.6 |
| X-206 | 달력 형식 셋 | W calendar.json{years[{holidays[{confirmed}]}], weekdays, company_off}, TAB 레지스트리 calendar{평면 holidays{checked}, std_window…}, 참조 calendar_verified.json | W 형(= `config\calendar.json` 실물), 레지스트리 calendar 도 같은 모양(§3.21) | TAB §3.10 |
| X-207 | 팀 묶음 등급·종료 근거 | W 수동 업무 등급 M 의 대응 행 없음, E3i 는 MINOR 요청 상태 | 팀 묶음 1.0 에 `grade M`·`end.kind E3i` 포함(§3.18) | TAB §2.3 |
| X-208 | 정수 분 동률 | TAB 'unit_id 사전순', W '업무·버킷 함께 키 사전순'('B_' < 'u_' 라 버킷이 먼저) | 정렬 키 `(업무 u_ 먼저, 키 사전순)`, 버킷은 뒤(§5.3) | TAB §0.4 R-3 · W §11.3 |
| X-209 | 분모 선택과 팀 무결성 | `mm.denominator=weekdays` 면 TAB integrity 422 | 팀 묶음은 늘 workdays, weekdays 는 개인 표시 전용 | W §6.1 |
| X-210 | 가용·로드 식 | W 오늘 경과 비율 포함(소수 avail), TAB `avail_days = covered_workdays − absence_days`(정수), load 비 대 load_pct % | TAB 식 하나(개인 = 팀). 오늘은 `as_of` 가 그날 표준창 끝을 지났을 때만 covered 에 넣는다. `mm.todayFraction` 폐지, 저장은 `load_pct`(R W-5·R-Q4 해소) | W §6.4 |
| X-211 | B_MEET 과제 귀속 | W '롤업에서 레지스트리 키워드로 과제에 직접 귀속 가능' 대 H X7·R W-3 '보조 표시만' | 보조 표시만, MM 이동 금지(I2·I3 보존) | W §4.7·§5.4 |
| X-212 | normalize 시그니처 | W 부록 A `(…, registry: dict) -> Evidence` 대 §2.4 `(…) -> Evidence, audit`, H X8 HierTags | `normalize(records, profile, cfg, as_of, tags: HierTags) -> (Evidence, audit)` | W §2.4·부록 A |
| X-213 | 결과 열·단위 | W tasks.json 열 미확정, attrib {slot,target,sec,level} 만(R W-1 obs·app·fam 요청), mm_month 시간 h float·QueueItem impact_h, R 은 pre_request_s·정수 분 요구(RP1) | `timecore/1.1` 열(§3.14), 모든 시간량 정수 초·분 저장, tasks.json 식별자 열 이름은 `unit_id`(UnitTask.id 의 값) | W §7.5 · 부록 A |
| X-214 | 코파일럿에 시간 전송 | W §7.3 '코파일럿에는 확인된 요약(등급·라벨·h)만 보낸다' 대 B1·G-B8(시간·MM 미전송) | h 를 보내지 않는다(등급·라벨만) | W §7.3 |
| X-215 | 원장 사적 차감 표기 | P R-P7 '사적 제외 n슬롯·사적 판정 n건' 대 W '사적차감 n분' | '사적차감 n분(n건 판정)'·'개인일정차감 n분'·'사용자제외 n분' | P §12.7 |
| X-216 | git 문서군 키 | W `repo:`+정규화명, P r16 을 doc_key 열에, H `repo:<doc_key>` | doc_key(r16) 그대로 fam_key | W §2.2 · H §4.1 |
| X-217 | W 내부 미정의 | DayInfo·MonthMM·TimeResult·CalibrationReport·ctx 형 미정의, preWindowMin 하위 키 이름 미정 | 형은 W 부록 A 확장으로 구현 시 정의(결과 파일 열은 §3.14가 고정), 하위 키는 `.mail` `.teams` `.file` `.code` `.commit` `.submit` | W 부록 A · §8.3 |
| X-218 | 근태 파서·화행 분류기 모듈 | W '근태 파서는 분류 명세 소관'인데 H 에 없음, 화행 분류기 경로 미지정 | `lm27.normalize.absence`·`lm27.normalize.act`(§2.7) | W §11.3 |

### 10.K 분류·레지스트리

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-230 | 어휘 정본 | TAB 예시·레지스트리 vocab 이 이름 문자열('회로'·'설계'·'개발'·'의뢰수신'), H X1 코드 | 코드(ELEC·DESIGN·DEV·REQ_IN), 이름은 vocab 의 name. 팀 묶음·레지스트리·R-8·P §14.5 ENUM 모두 코드 | TAB §2.3.1·§3.10·§4.6 · P §14.5 |
| X-231 | 업무 유형 수 | TAB activity_types 6종, H 7종(+EDU) | 7종 | TAB §3.10 |
| X-232 | 영역 허용 범위 | TAB PUT·proposals.domain_guess 6종(UNC 포함), H 과제·제안 5종 | 과제·제안 5종, UNC 는 파생 전용 | TAB §3.10·§2.3.2 |
| X-233 | ukey 정의 | TAB 'NFKC·공백 접기·casefold', H 구분자 치환·공백 제거·괄호 꼬리 보존 | H `lm27.hier.names.ukey`(서버도 import) | TAB §3.10 |
| X-234 | 예약 과제 | TAB 에 P-99xx 처리 없음(묶음의 P-99xx 가 unknown_project 경고) | 서버는 PUT 의 P-99xx 를 `reserved_id` 로 거부, 취합에 예약 5개 주입. PUT 검증은 `validate_registry(side="server")` | TAB §3.10·§4 |
| X-235 | 레지스트리 없을 때 | TAB '과제 미지정 = 제안으로만', H 예약 과제 + 영역 규칙 | H | TAB §3.10 |
| X-236 | agents 예시 | TAB axis '문서'·step_types '문서작성', H 예시 `DOC_WRITE` | 축 키·단계 유형 모두 코드, `DOC_WRITE` → `DOC_DOC` | TAB §3.10 · H §2.3.6 |
| X-237 | 레지스트리 캐시 읽기 제한 | TAB lint '`data\team\registry.json` 은 build·client·privacy 만', H `lm27/hier/registry.py` 가 직접 읽음 | 허용 목록에 `lm27/hier/registry.py` 추가(L-22) | TAB §2.3.3 |
| X-238 | pepper 저장 | H '분리 저장(TAB)', TAB §3.10 캐시 'pepper 포함'·§5.3 '분리 저장' | 클라이언트 캐시 registry.json 은 pepper 포함(반출 금지), 서버는 `secrets\pepper.json` 분리 | H §3.1 · TAB §5.3 |
| X-239 | person.function 명명 | 값은 분야(vocab.fields) 코드인데 이름이 function | `person.field` 로 개명 | TAB §2.3 · P §14.5 · H §12.4 |
| X-240 | 제안 영역 필드 이름 | H `dom_guess`, TAB `domain_guess` | `domain_guess`(로컬 proposals.json 도) | H §7.3 |
| X-241 | vocab.step_types 모양 | H 객체 목록, R T-1 코드 목록 + step_type_names·step_tool_access·step_verifiable | 객체 목록에 `tool_access`·`verifiable`·`kind`·`cls` 필드(§3.19) | R §13 T-1 |
| X-242 | 영역 색 | H DOMAIN_META MP `#e08a00`·COM `#8b929b`·UNC `#c0c4cc`, R H-1 대비 검증값 | R 값(§6.6) | H §1.2 |
| X-243 | 단계 유형·관리 화면 소유 | H Q5(step_types)·Q8(/admin) 미결 | R §3.3(`lm27.vocab.steps`)·R §7.9 | H §17.3 |
| X-244 | H 내부 | 오류 코드 `bad_domain`·`bad_domains` 혼용, title_src 값 집합 둘, Feat.kind 와 원천 이름 대응 없음, H 질문·골든 코드 겹침, 부록 A 예시 모순, §1.5 에 S1d·E1p 누락 | `bad_domain` 하나, title_src 저장값 = UnitLabel 값(§3.15), Feat.kind 대응 mail.*→mail · cal.*→cal · teams.*→teams · pc_file→file · pc.sampler→win · pc_git→git · pc_compute→compute · manual→manual · *.copilot→summary(pc.events 는 Feat 없음), 골든은 HG 접두, 예시는 R0-2, 경계 근거는 W | H §1.2·§1.5·§4.1·§5.3·§15 |
| X-245 | 앱 범주 두 축 | CP app_class 영문 소문자, H app_cat 한글 범주, `lm27/catalog.py` 정의처 없음 | 행에는 app_class(정제기), 범주는 `lm27.catalog.cat_of(app_id)`(한글 9종), 카탈로그 단일원 `lm27/catalog.py` | CP §6 · H X10 |
| X-246 | 상대 계급 라벨 | P sender_label '미상' 이 H dom_labels 에 없음, H 프롬프트 '외부'는 P 에 없음 | dom_labels 에 '미상' 포함, '외부'는 프롬프트 파생값 | H §4.1 |
| X-247 | 가명화 사전 출처 | H X4: 과제 코드네임 사전을 유효 레지스트리(팀 ⊕ 개인 L-…)로 볼지 미확인, P §8 은 레지스트리 projects 만 언급 | 사전 가명화 출처 = 유효 레지스트리(내장 ⊕ 팀 ⊕ 개인 로컬)의 `codenames`·`aliases`(mask_name) + `customers`·`partners` + `privacy.customers`·`privacy.partners`. 에이전트에는 context_cache 로 이름 목록만 | P §8.1 · H §3.4 |

### 10.L 코파일럿 브리지

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-250 | task_label 판 | B 1.0(`cand:` 키·field_hint·도메인 원문·dom 없음·NONE 뜻·regv 없음·P012 형식) 대 H 1.1 | H 1.1(§0.2 — 단계 내용 소유 H) | B §8.3·§8.0.3 |
| X-251 | compact 머리말 규칙 | B '후보 + 상위 빈도, 넘치면 BR-HEADER 중지', H '이 묶음 cands + 예약 5줄 + 안내' | H | B §8.0.3 |
| X-252 | 폴백·새 과제 산출 | B 폴백 제목 '미분류 업무'·wtype OFFICE, NEW 답을 `ai_out.proposals` 로 | H: 폴백 제목 = 규칙 이름, NEW 는 로컬 `proposals.json`(`on_new_name`), `ai_out.proposals` 폐지 | B §8.3 |
| X-253 | 단계 목록 | B '9종', §8.8 taxonomy_bootstrap 'v1 범위 밖', taxonomy_consolidate 없음, §14 는 조회 3단계를 lookup.py 한 파일로 | 11종(§2.12), taxonomy_* 는 v1 포함, `kind=single` 행 봉투 검증(H X6) 채택, 조회 3단계는 lookup.py 한 파일 | B §8.0.2·§8.8·§2.2 |
| X-254 | 웹 노출 열 표기 | B S4 '빈 값', H '열은 두고 값만 -' | H 표기(조립 결과는 같다) | B §9.7 |
| X-255 | agentic_match 머리말 | B 에이전트 '코드·이름·입력→출력·단계' 전송, H '`copilot_desc` 가 유일한 설명, desc 미전송' | 코드 + `copilot_desc` + 입력→출력·단계 유형만, name·desc 미전송 | B §8.6 |
| X-256 | subagent_review·폴백 | R B-1(플래그 T, /1.1), B-2(stages import 무부작용 관문), R 의 `why="no_ai_out"` | 모두 채택(§6.4 why, L-30) | B §8.7·§15 |
| X-257 | 어댑터 rc 3 뜻 | CM §11.4 '커넥터·라이선스 불가', CM §4.3 '드라이버 불가', B §8.1 '커밋 0 + blocked·transport_fail' | 수집기 rc 3 = 드라이버 불가·불완전(blocked 포함, 라이선스 불가도 blocked R-NOLIC) | CM §11.4 |
| X-258 | 증인 조각 크기 | CM '7~10일·100행 이하' 대 B 실효 36행 | B 규칙(`bridge.lookup.*`, 실효 = min(maxRows, 예산식)) | CM §11.4 |
| X-259 | 공통 단계 상태 계약 | B Q16 경로·필드 미정 | §8.5 공통 스키마 + §8.6 progress 하트비트(별도 파일 없음) | B §16 Q16 |

### 10.M 팀·보고서

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-270 | 팀 묶음 필드 대조표 | P §14.5 에 TAB 추가 필드(member_id·pepper_id·work_tz_offset_min·title_mode·apps_unknown_min·peers_external·proposals.kind/domain_guess·units 세부·workflows 수치·agentic chain·catalog_proposals.minutes) 없음, peers `.n` 대 `units`·`shared_effort_min`, built_at 값 클래스 UTC 대 ISO+offset → lint 8 실패 | `TEAM_SPEC_V1` 단일원 = `lm27\team\schema.py`(TAB §2.3.2 표에서 생성), P 표는 생성물. peers 는 TAB 필드, 시각은 `DATETIME_OFFSET` | P §14.5 |
| X-271 | TAB 내부 — 도달 결과와 사유 | reach result 10값 대 사유 5개, proxy·wrong_major 판정 관측 없음 | §6.1 매핑(R-TEAM-DNS·R-TEAM-PROXY 추가), hello 판정표에 proxy(프록시 응답 헤더)·wrong_major(accepts 주판 불일치) 관측 추가 | TAB §1.5·§2.9 |
| X-272 | TAB 내부 — 간트 구간 이름 | 묶음 `gantt_spans`, detail·team_data `spans`, R 모델 `spans` | `spans` 하나 | TAB §2.3·§4.6·§4.9 |
| X-273 | TAB 내부 — 반올림·null·배지 | team_data 예시 반올림 값 대 '반올림은 표시 때만', member_id '' 대 null, 배지 `cfg_diff` 대 '산식 설정 상이' | 원값 저장, '' → null, 배지 `cfg_mismatch` | TAB §4.9·§2.3·§3.11 |
| X-274 | TAB 내부 — 커서 기준 폴더 | evidence 와 privacy_audit 커서의 file 기준 폴더가 다름(명시 없음) | `agent\store\` 기준 상대 경로(§3.7) | TAB §1.4 |
| X-275 | TAB 내부 — 검증표 누락 | units[].evidence_n·first/last_evidence·lead_time_h·ax_link·role_id 참조, workflows steps n·median_min·agent_grade, needs.freq_per_month, chain.step_no 규칙 없음 | TAB §2.3.2 표에 형 규칙 추가(정수 ≥0, 날짜, 참조 무결성) | TAB §2.3.2 |
| X-276 | 대체 포트가 피할 포트 | TAB suggest_port 는 `ui.port` 설정값만, R T-7 은 실제 포트(ui_server.json)도 | 둘 다 피한다 | TAB §3.4 |
| X-277 | team_data 형 | TAB roles·activity_types 를 '…' 로 남김, quality `{excluded_from_comparison, pcs_matrix}` 대 R `quality.matrix`, coverage 목록 대 축 키 접근, subagents 단위(role 대 field×function) | R T-4 형 채택(§3.22). coverage 는 목록 유지·보고서가 axis 로 색인, subagents 는 묶음 role 단위 → 취합 (field, function) 단위 | TAB §4.9 |
| X-278 | workflows 필드 | TAB why 어휘에 tool_access 없음, wait_in_median_min·work_share·bottleneck·sample 없음(R T-2·T-3) | 채택(§3.18) | TAB §2.3 |
| X-279 | 팀 정적 파일 | TAB 고정 사전 `/static/team.css`, R 은 web/common 공용 렌더러 | `team.css` 없음, `/static/lm27.css`·`lm27charts.js`·`lm27ui.js` 추가(R T-6) | TAB §3.12 |
| X-280 | `%LOCALAPPDATA%` 배치 누락 | TAB 배치에 R 의 `ui\`(ui_server.json·logs·jobs) 없음 | §1.3 | TAB §1.1 |
| X-281 | R 내부 | §8.6.1 '색은 `var(--dom-*)`' 대 §8.1.3 '`--dom-*` 토큰을 만들지 않음', quick_reanalyze `time,mining,report` 대 `classify,time,mining,report`, `report ai-items --stage` 누락, 차트 함수 이름 둘·CHARTS 에 없는 CH-*, maxModelMb 초과 처리 §11 에 없음, api_*.py 에 bridge·hier·jobs·teamserver·calibration·queue 처리 모듈 없음, RP1 의 `ratio()` 정의처 없음 | `--dom-*` 없음(모델 domains[].color 를 그대로), 빠른 재분석은 classify 부터, `--stage` 선택 인자, 부록 A CHARTS 이름 정본·HTML 표 컴포넌트(CH-H02·P14·P15·T07·T09)는 CHARTS 밖, 모델 상한 초과 시 runs·드릴 섬 축소 + 경고, API 처리 모듈 배정(§2.14), `ratio()` = `fmt.fmt_ratio` | R §2.3·§2.4·§8·§9·§11 |

### 10.N 이름공간

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-290 | 코드 이름 충돌 | R-P1~P9(시간 규칙)·R-1~R-9(TAB 계약)·R-Q*(R 미결)가 사유 코드 접두와 겹침, H 질문 H01~H06 과 골든 H01~H46, 관문 G1~G12(W)·G1~G4(P), 불변식 I1~I12(P)·I1~I7(TAB), 각 명세 미결 Q* | §6.2 이름공간(사유 코드 정규식, HG 접두, 명세 접두 인용) | H §15 |

### 10.O 반증 점검 보정(v1.0.1)

v1.0 을 명세 다이제스트·원 명세에 대조해 찾은 이 문서 안의 누락·자기모순이다. '어긋남' 열의 '계약' 은 이 문서 v1.0 을 뜻한다.

| ID | 주제 | 어긋남 | 결정 | 반영 요청 |
|---|---|---|---|---|
| X-300 | 수집기 입출력·파이프 연결자 | 계약 §7.3 '오케스트레이터·감독이 연결' 대 §5.2·§8.2 'PS 수집기 골격이 파이프를 띄우고 Kill(code 99)'(P §3.5). `-CursorFile` 을 금지했으나 커서를 넘기고 돌려받는 수단이 없음(PS 는 디스크 쓰기 금지). §5.2 '읽는 곳'에 `.ps1` 을 적었으나 §7.3 은 '설정은 호출자가 인자로' | 연결자(§7.3)가 수집기·파이프를 잇고 `privacy.pipe.waitSec`·code 99 를 맡는다. 입력은 stdin 제어 줄 `_in{cursor, cfg, self_names}`, 출력 진전은 `_cursor`, 파이프가 성공 뒤에만 커서 저장. PS 수집기용 키의 레지스트리 owner = 연결자(§5.1-10) | P §3.5 · CM §5.1·§6.1 · CT §7.1 · CP §3.6·§4.5 · C §8.3 |
| X-301 | 커서 동시 쓰기 | 계약 `save_raw_cursor(paths, pc_id, cur)` 는 파일 통째 교체 — 에이전트 수확(pc.*)과 전경 수집(mail.* 등)이 겹치면 한쪽 커서가 사라진다 | `save_raw_cursor(paths, pc_id, src, value)` + 잠금 안 읽기·교체·원자 쓰기(§2.3) | TAB §1.6·§1.7 |
| X-302 | 경로형 설정 예외 | 계약 §5.1-7 '경로는 설정 키가 아니다'의 예외 목록에 `bridge.edge.profileDir`·`pc.git.exe`·`pc.git.repos`·`pc.git.scanRoots`·`pc.license.lmutilPath` 가 없는데 §5.2 는 이들을 경로 키로 등재 | 예외 목록에 추가(§5.1-7) | — |
| X-303 | 에이전트 설정·정제 문맥 부족 | §5.2 는 `agent.main` 이 `privacy.audit.retentionMonths`·`privacy.pipe.waitSec` 을, 수확이 `collect.lookbackDays` 를 읽는다고 하나 §5.1-8 부분집합에 없음. 에이전트 정제기의 `window_class`(`privacy.window.*`)·`path_excluded`(`privacy.path.excludeKeywords`)·`RecordContext.work_window`(근무창·휴일, P §3.2)·본인 표시명 원천도 `agent_config`·`context_cache` 어디에도 없음 | §3.9·§5.1-8 에 키와 문맥 항목을 명시 | P §3.6 · TAB §1.6 |
| X-304 | privacy ↔ team 순환 | P `check_team_payload(…, spec=None)` 기본값 = `TEAM_SPEC_V1` 인데 그 정의처는 `lm27.team.schema`(계약 §3.18), `team.schema` 는 다시 privacy 를 부른다 → 모듈 순환, 그리고 `lm27\team\` 이 없는 에이전트 사본에서 privacy import 실패 | `spec` 필수 인자, privacy → team import 금지. 같은 이유로 privacy 최상위의 `lm27.hier` import 도 금지(유효 레지스트리는 프로그램 폴더 모드에서만 함수 안 지연 import, §2.2) | P §3.3·§14.5 |
| X-305 | 에이전트 bin 사본 누락 | P `sanitize_record` 가 훅으로 부르는 `lm27.normalize.cues.extract`(act_cues)와 pc_id 재계산의 `lm27.bundle.ids`(구현 계획 CR-16)가 계약 §1.3 사본 목록에 없음 — 에이전트 정제(teams.uia 등)가 ImportError(L-06 은 삼키기 금지) | 사본 목록에 `normalize\{__init__, cues}`·`bundle\{__init__, ids}` 추가, 사본 모듈은 사본 안 모듈·표준 라이브러리만 import(§1.3). 구현 계획 CR-16 은 이것으로 반영 | TAB §1.6 · P §3.6 |
| X-306 | 본인 표시명 집합 모듈 | CT §4.4 '공통 모듈 1벌'의 경로·이름이 없고, `teams.selfNames` 폐지(X-115) 뒤 원천·전달 경로 미정 | `lm27.privacy.context.self_name_set(local, cfg, os_names)` 하나. 정제 문맥 `self_names`·`context_cache.self_names`·수집기 `_in.self_names` 가 같은 결과를 쓴다 | CT §4.4 |
| X-307 | ps 구현 수확 운영 파일 | 계약 §1.3 의 `run\harvest_done.json`·`.harvest.lock` 은 수확 자식이 쓰는데(TAB §1.7) ps 구현 수확 `harvest.ps1` 은 L-09 예외 밖 | L-09·§9.1 예외에 `harvest.ps1` 의 원문 없는 운영 파일 추가(X-147 보강) | CP §14.1 · TAB §1.6 |
| X-308 | rc 2 의 R-CA | 계약 §8.1 rc 2 칸이 'R-LOGIN(확정 안 함)'만 적어, §6.1 에서 확정 가능한 R-CA 의 셀 사유가 빠짐 | rc 2 = R-LOGIN(확정 안 함) 또는 R-CA(확정 가능) | — |
| X-309 | lookbackDays 미보정 표식 | §5.2 는 ★ 없이 120, §12.2 O-5 는 이 문서가 새로 정한 ★ 값으로 셈 | ★ 표시(§5.2) | — |
| X-310 | O-9 사실 오류 | O-9 '`.gitignore` 에 `config/config.json` 추가 필요' — 저장소 `.gitignore` 에 이미 있음 | O-9 닫음 | — |
| X-311 | 'COM 누락 의심' 사유 코드 | C §5.3·CM §8 이 `ledger.mismatchRatio` 초과 때 붙이는 'COM 누락 의심' 사유가 §6.1 단일 표에 없음(L-13 이 막는다) | `R-COMGAP`(경고, 확정 ✘) 등재 | C §4.2·§5.3 · CM §8 |
| X-312 | 이름 없는 상수 | C §8.4 '스테이지 절대 상한(기본 꺼짐)', C '광고·사적 점수 임계(키 미명명)' 가 키 표·상수 표 어디에도 없음 | §5.3: 절대 상한 없음(키 없음), 임계는 P 규칙 고정 상수 | C §8.4 |
| X-313 | 금지 접근 경로 관문 | D-3(Graph·IndexedDB/LevelDB·wpndatabase·OST/PST 직접 파싱 금지)을 막는 정적 관문이 없음(명세 문구로만 금지) | L-29 ② 로 확장 | — |
| X-314 | `.msg` 건너뜀 건수 | CM §11.5 `skipped_msg` 를 남길 곳이 없음 | 수집 `stage_result` 추가 필드(§8.5) | — |
| X-315 | 백필 빈칸 파일 형식 | CM §11.3 `--blanks-file <json>` 의 위치·형식 미정 | `data\derived\collect\<run_id>\blanks_<src>.json` = `[{todo_id, date_range, kind_axis}]`(§7.3) | CM §11.3 |
| X-316 | 파일 수집기 자기 제외 | CP §5.1 자기 제외 `data\bundle` 은 X-010 으로 사라진 경로 | `%LOCALAPPDATA%\LoadMonitor27\` + `data\bundle.json` 이 있는 폴더(§2.17) | CP §5.1 |
| X-317 | 이벤트 채널 상태 표기 | CP §4.5 채널 상태 `error:<msg>`(자유 문자열)를 pc.json 에 남김 — '탐침은 숫자·열거·사유 코드만'(§6.7)과 충돌, 계약 §3.8 은 채널 상태를 `pc.sampler` 아래에 둠 | `pc.events` value 의 채널별 열거 `ok` `none` `unauthorized` `error`(+ 예외 유형명), 메시지 문자열 없음(§3.8) | CP §4.5 |

해소한 불일치: **224행**(A 6 · B 23 · C 13 · D 33 · E 17 · F 29 · G 3 · H 9 · I 13 · J 19 · K 18 · L 10 · M 12 · N 1 · O 18). A~N 의 각 행은 다이제스트의 명세별 conflicts 항목 하나 이상을 묶고, O 는 v1.0 자체의 누락·자기모순이다.

---

## 11. 관문

관문은 1일차부터 돈다(D-13). 실패하면 머지·패키징을 막는다(성능 경고 제외). 구현은 `tools\lint.ps1`(정적)과 `tests\`(동적)이다.

### 11.1 lint 관문(정적)

| ID | 검사 | 근거 |
|---|---|---|
| L-01 | 텍스트 소스 제어문자 0(`0x00-0x08 0x0B 0x0C 0x0E-0x1F`) | 결정 §9 · CP §14.1 |
| L-02 | 인코딩(§9.2): .bat CP949+CRLF·BOM 없음·`>nul chcp 949`, .ps1 BOM+CRLF, 그 밖 UTF-8 LF | 결정 §0 · `hook_check.py` |
| L-03 | ruff(`ruff.toml`, `--no-cache`) | 저장소 정책 |
| L-04 | `zoneinfo.ZoneInfo` 0건 | W-G10 · 결정 §10.3 |
| L-05 | 코드(.bat·.ps1·.py)에 `python -m lm27` 호출 0건, 진입 스크립트 첫 실행문의 ROOT sys.path 삽입 | P H8 · D-1 |
| L-06 | `except ImportError` 로 기능을 삼키는 코드 0 | TAB lint 6 |
| L-07 | 최종 파일 `open(…, "w"/"a")` 는 `lm27\util\fsx.py`·`lm27\store\writer.py`·`lm27\bridge\fsio.py` 에만(`write_text_ttl` 은 `bridge\manual.py`·`bridge\exchange.py`) | TAB lint 6 · B G-B7 |
| L-08 | 단일 로더: `data\pcs` 경로 조립·open 은 `lm27\bundle\{loader,segment,manifest,export,pcreg,merge,move}.py` 에만, 데이터 경로 문자열 조립은 `lm27\paths.py` 에만(AST) | TAB lint 2 · R G-R10 · 결정 §9 |
| L-09 | 수집기 쓰기 금지: `collect\**\*.ps1` 의 Out-File·Set-Content·Add-Content·Export-Csv·`>`·`>>` 가 data\·store\·%LOCALAPPDATA% 를 가리키면 실패(예외 `collect\agent\agent.ps1`·`harvest.ps1` 의 `heartbeat.json`·`run\harvest_done.json`·`run\.harvest.lock`·`logs\` — §9.1) | P §3.4 · CP §14.1 |
| L-10 | 수집기 파이썬 import: `lm27.privacy` 에서는 `lm27.privacy.sanitize` 만. 그 밖 허용 `lm27.store` `lm27.paths` `lm27.config` `lm27.util` `lm27.catalog` `lm27.bridge`(세션·조회 어댑터) | P §3.4 |
| L-11 | 저장 경로 우회 0: `SanitizedRow` 생성은 `records.py` 안에서만, `_SEAL` 외부 참조 0, `SegmentWriter` 외 store 쓰기 0 | P I2 · T6 |
| L-12 | 설정 키: 코드가 읽는 키 ⊂ `settings_registry.json`, 등록 키 ⊂ 코드가 읽는 키(죽은 키 0), §5.2 표 = 레지스트리(생성 대조), snake_case 키 0 | 결정 §9 · W-G6 · R G-R9 |
| L-13 | 사유 코드: 코드·문서·화면 문구의 `R-<영문>` ⊂ §6.1 | 이 문서 |
| L-14 | 경로 ID·kind 상수 ⊂ §6.5·§3.1 | 이 문서 |
| L-15 | 작업·뮤텍스 이름에 install_id, 작업 XML Action·WorkingDirectory 가 ROOT 를 가리키지 않음, 시험 작업은 `LM27T-` | TAB lint 4 · CP §14.1 |
| L-16 | Edge: `--remote-allow-origins=*` 0, `--user-data-dir`·`--remote-debugging-port` 문자열과 Edge 프로필·포트 키는 `lm27\bridge\` 밖에 0, `office.com` 부분 문자열 0, `os.kill(` 0 | B G-B9 · G-B12 |
| L-17 | 브리지 G-B1~G-B5·G-B7·G-B10·G-B11(시계·숫자 상수·설정 일치·단계 완결성·쓰기·결과 봉투·ID 글자판) | B §15 |
| L-18 | 시간 미전송: send_fields 에 시간형 키 0, 프롬프트 템플릿에 `\d+(\.\d+)?\s*(MM\|M/M\|시간\|h)\b` 0 | B G-B8 · B1 |
| L-19 | 화면: `innerHTML` `outerHTML` `insertAdjacentHTML` `document.write` `eval(` `new Function` `setTimeout("` `DOMParser` `toFixed(` 0, 16진 색은 `lm27.css`·DOMAIN_META 에만, `round(`·나눗셈은 `lm27\report\fmt.py` 에만, 외부 참조(http·CDN·웹 글꼴) 0, 데이터 섬 이스케이프 | R G-R4~G-R7·G-R11·G-R5·G-R6 |
| L-20 | 서버 `allow_reuse_address=True`·`SO_REUSEADDR` 0(SO_EXCLUSIVEADDRUSE) | TAB lint 3 · 결정 §10.4 |
| L-21 | `team.serverHost`·`team.serverPort` 기본값이 `DEFAULT_TEAM_URL = "http://10.115.147.68:9310"` 과 바이트 일치(사설 IP 금지 lint 의 유일 예외) | TAB lint 1 · 결정 §1 |
| L-22 | 팀 빌더: `**dict`·`dict(obj)`·`deepcopy(analysis…)` 통째 전달 0. `data\team\registry.json` 을 읽는 모듈은 `lm27\team\build.py`·`client.py`·`lm27\privacy\`·`lm27\hier\registry.py` 뿐. `host_display` 를 빌더가 읽지 않음 | TAB lint 5 · §2.3.3 |
| L-23 | `TEAM_SPEC_V1`(lm27\team\schema.py) = TAB §2.3.2 표 생성 결과 = P §14.5 대조표 | TAB lint 8 · X-270 |
| L-24 | 정제 규칙 잠금(`RULES_HASH` = `rules.lock.json`), 배포 기본 설정에 `privacy.customers`·`partners`·과제·별칭·코드네임·고객·구성원·규칙·카탈로그 0 | P §16 · T24 · H G-H13 |
| L-25 | 분류: `learn.py`·`rules.py` 가 ai_out·proposals 미참조(G-H7), 영역 이름·색 하드코딩 0(G-H11) | H §15.3 |
| L-26 | 실명·코드네임·이메일 카나리아: 저장소 텍스트 전체에서 로컬 전용 금지어 목록(저장소 밖 파일) 0건, 이메일 형식은 `example.com`·`*.example` 만 | 결정 §1 |
| L-27 | JS 문법 `node --check web\**\*.js`(개발 PC 전용, 실행 환경에 node 불필요) | R G-R3 · 결정 §9 |
| L-28 | 별개 프로젝트·이전 판과 겹침 0: 포트 8765~8767·9333 사용 0, `LoadMonitor26`·`LM26-` 작업 이름 0 | 결정 §0 |
| L-29 | 폐기 산출물·금지 접근 경로 0: ① `mail.csv` `replies\` `mail_prompt_*.txt` `mail_source.json` `coverage.json` `teams_window*.csv` `teams_window_raw.txt` `teams_web.csv` `sanitize_audit.jsonl` `completion_ledger.jsonl` `git_source.json` 를 쓰는 코드 0. ② D-3 금지 경로: 코드(.py·.ps1·.bat·.js)에 `graph.microsoft.com`·`IndexedDB`·`LevelDB`·`wpndatabase` 문자열 0, `.ost`·`.pst` 파일을 여는 호출 0(확장자·제외 목록 안 표기는 허용). 검사 규칙 표를 담은 `tools\lint.ps1`·`tools\hook_check.py` 와 `docs\` 는 제외, 위반 표본은 시험 중 `%TEMP%` 에만(X-313) | CM §4 · CT §2·§14.4 · D-3 · 이 문서 |
| L-30 | `lm27\bridge\stages\*` import 무부작용(세션 없는 fallback 호출 가능) | R B-2 |

### 11.2 불변식·시험(동적)

| ID | 검사 | 근거 |
|---|---|---|
| T-01 | **시간 보존**: 날마다 Σ귀속 초 = 300 × 봉투 슬롯(정수). 실분석에서도 상시 assert, 실패 시 분석 중단 | W-G1 · D-9 |
| T-02 | **결정성**: 같은 입력·as_of·설정이면 결과 바이트 같음, 입력 순서를 섞어도 같음 | W-G2 · H G-H1 · R G-R1 |
| T-03 | 단조성 퍼즈: 양성 증거 추가 → 봉투 비감소, PC 가동 제거 → 비증가 | W-G3 |
| T-04 | 골든: W 시나리오 83 · H HG01~HG46 · R RPT 골든 · B `golden_sends.json`(+10% 초과 실패) | W-G4 · H G-H8 · R · B G-B5 |
| T-05 | **개인 = 팀**: 정수 분 표로 팀 재합산한 월 MM = 개인 MM(\|Δ\|≤1e-9), Σalloc ≤ env, effort = Σalloc, 화면 `fmt_mm` 문자열 일치 | W-G5 · TAB A01 · R RPT-10 |
| T-06 | 분류가 시간 값을 바꾸지 않음(분류 전후 team_tables.json 바이트 동일) | H G-H4 · H-I5 |
| T-07 | **PII 카나리아 0건**: 세그먼트·store·exe_meta·감사·코파일럿 프롬프트(가상 시계)·팀 페이로드·가림판 보고서 | P T19 · TAB U03 · B G-B6 · R G-R8 |
| T-08 | 정제 회귀 말뭉치 `run_selftest()`(lint·에이전트 설치·패키징 직전) | P §18.3 |
| T-09 | 미관측(not_attempted·blocked·transport_fail·out_of_horizon) ≠ 0h, date·summary·unknown 시간 기여 0 | C §5.3 · 결정 §5 |
| T-10 | 상한·예산에 걸리면 반드시 partial + cap_hit/budget_hit | C §10 |
| T-11 | 병합 후 건수 보존·중복 0(멀티 PC·멀티 경로·UTC 클라우드PC) | C §10 P10·P11 |
| T-12 | 세그먼트 불변·다른 pc_id 불변, 번들 합치기 2회째 변화 0 | TAB B01·B18 · D-18 |
| T-13 | 달력: 2026-09·2026-10 근무일 각 20, 2026 월별 평일이 검증표와 일치, 없는 해 분석 거부 | W-G10 · TAB A12 · D-17 |
| T-14 | 설정 read-check: 등록 키 전부 읽힘, 수치·선택 키 섭동 시 결과 변화 | W-G6 · R G-R9 |
| T-15 | 브리지 가상 시계 시뮬 T01~T55 | B §11.5 |
| T-16 | 수집 페르소나(합성·실데이터 없음): C P1~P12 · CM 1~20 · CT 1~18 · CP 1~14 — 원장 상태·todo·rc assert | C §10 · CM §15 · CT §15 · CP §15 |
| T-17 | 번들·에이전트 B01~B26, 팀 U01~U16·S01~S17·A01~A12·O01~O05 | TAB §9 |
| T-18 | **합성 E2E**: PC1 → PC2 → 클라우드PC(스텁 코파일럿) → 분석 → 업로드 → 팀 보고서. 카나리아 0, 개인 = 팀, 간트 드릴다운 | 결정 §9 |
| T-19 | 성능: 1명 × 3개월 시간 코어 ≤60초·≤500MB, 정제 20,000행 ≤5초, report build ≤10초 | W-G9 · P §18.3 · R RPT-46 |
| T-20 | **패키지 = 커밋 내용**: zip 목록·바이트가 커밋과 같고 `data\`·`out\`·`config\config.json`·키·`.part` 0건 | 결정 §9 |
| T-21 | 반출 금지: 팀 묶음·오프라인 내보내기·zip 에 keys·local_only·pepper·host_display 0 | TAB O01 · §2.3.3 |
| T-22 | 계층 불변식 H-I1~H-I7 + 퍼즈 5,000건 | H G-H3 |
| T-23 | 확인 큐 안정: 같은 입력 → 같은 qid 집합, 주당 노출 ≤ 상한 | W-G12 |
| T-24 | 접근성 점검표 KB-1~KB-9(배포 전 수동 1회) | R §12.3 |

### 11.3 시험 주입점(단일 목록)

`LM_OUTLOOK_SELFTEST=N` · `LM_INDEX_FAKE=<json>` · `LM_OWA_FAKE=<json>` · `LM_TEAMSWEB_FAKE=<json>` · `LM_COPILOT_STUB=<폴더>` · `LM_NO_BROWSER=1` · 샘플러 `-TestSamples N` · `Get-TeamsWindow.ps1 -RawFile` · `Get-EventActivity.ps1 -EventsCsv -Now -BootTime -OutDir` · `Get-FileActivity.ps1 -RecentDir -MruTextDir -NoToolMru` · `Get-OfficeMru.ps1 -MruRegFile` · ps 스크립트 `-TestNow` · 브리지 `VirtualClock` · 시간 코어 `as_of`. 배포 설정·바로가기에 주입 환경 변수가 있으면 탐침이 경고한다(`stub_env_set`). 시험은 `%TEMP%` 복제 트리에서만 돈다(`assert ROOT != 실제 설치 경로`).

### 11.4 실행 순서

편집 즉시 `hook_check.py`(PostToolUse 훅) → `tools\lint.ps1`(L-01~L-30) → `selftest privacy` → `tests\` 단위 → 골든 → 페르소나·E2E → 패키지(T-20). 앞 단계가 실패하면 다음 단계와 패키징을 하지 않는다. 커밋은 관문 통과 후 한국어 상세 메시지로, 즉시 푸시한다(결정 §1).

---

## 12. 미결

### 12.1 사용자 확인이 필요한 결정(기본값으로 진행한다)

| ID | 결정 | 기본값 | 근거 |
|---|---|---|---|
| U-1 | 1MM 분모: 공휴일 제외 근무일 × 8h 대 달력 평일 전체 | 근무일(팀 묶음은 고정) | W D1 · 결정 §10.3 |
| U-2 | '연장' 정의: 평일 표준창 밖 대 일 8h 초과 | 표준창 밖 | W D2 |
| U-3 | 키링 정본을 프로그램 폴더 `data\keys\` 에 두고 폴더째 이동(폴더를 남에게 통째로 넘길 때의 위험) | 폴더 동행 + 모든 반출 제외 | X-025 · P Q14 · TAB 미결 1 |
| U-4 | 조건부 액세스가 관리되지 않는 프로필을 막을 때 회사 기본 Edge 프로필 허용 | 불허(본인 전용 프로필) | CM 미결 7 |
| U-5 | 회고 기간·보관 사서함 | `collect.lookbackDays` 120 · `mail.includeArchiveStore` false | CM 미결 8 |
| U-6 | 코파일럿 전송 허용(정보보안), 웹 노출 정책 strict 대 block, 보정 왕복 허용 | 허용 · strict · 자동 보정 | B Q11·Q25·Q17 |
| U-7 | 팀 묶음 단위업무 제목 기본 포함, 첫 전송 승인(`team.autoSend=false`)이 '수동 조작 금지' 원칙과 맞는지 | 제목 포함 · 첫 전송만 승인 | W D13 · TAB 미결 8·9 |
| U-8 | 팀 공개 범위: self_label 실명 허용, `teamServer.readRequiresToken`, 평문 HTTP, pepper 배포 | 라벨 자유 입력(검사 통과분) · false · 사내망 평문 · 허용 | TAB 미결 2·3·4·15 · P Q10 |
| U-9 | 고객 기밀 범위(수량·납기), 회식·경조사 처리, 비공개 일정 | 금액·단가·율만 · social 삭제 · 개인 부재 블록 | P Q3·Q4·Q5 |
| U-10 | FlexLM 라이선스 수집 옵트인, 클라우드PC 가 없을 때 백필 PC 지정 | 끔 · 사용자가 1대 지정 | C · CP |
| U-11 | 업무 유형·분야·기능 어휘, 예약 과제, AX 연계 계상, 제안 과제 계상, 코드네임 검토 강제 | H 기본표 | H D-H1~D-H10 |
| U-12 | 동료 실명 전체판 생성, 로컬 화면의 동료 표시명 | 생성(경고) · 표시 | R R-Q1·R-Q2 |
| U-13 | 시간 모델 정책값(D3~D12: 근무창·AutoSave·단독 발신·추정 부재·date-only·사적 차감·무증거 배분·반복 문서·회의 혼합·솔버) | W 기본값 | W D3~D12 |
| U-14 | 원문 캡처(`bridge.rawCapture`) 유지 | 끔 | B Q20 |

### 12.2 남은 미결(계약 밖 작업)

| ID | 내용 | 막히면 |
|---|---|---|
| O-1 | 정규화(화행 규칙 세부·병합·근태 대응)와 분석 파이프라인 명세가 없다. 이 문서 §2.7·§2.13 이 임시 정본 | 이 문서 기준으로 구현하고 명세는 뒤에 쓴다 |
| O-2 | 명세 10종을 §10 '반영 요청' 열대로 고치는 커밋 | 구현은 이 문서를 따른다(R0-5) |
| O-3 | 결정 메모를 `docs\` 로 옮길지(현재 작업 폴더에만 있음) | §0.4 요약으로 대체 |
| O-4 | P Q21: `verify_doc_lm27.py` 실행으로 v1.1 신규 코드·ext 22건 검증 | 정제 관문 T-08 전에 필수 |
| O-5 | ★ 미보정 값 실자료 보정(이 문서가 새로 정한 `probe.subfolderRatio`·`probe.ostStaleH`·`collect.lookbackDays` 포함) | 기본값 + 미보정 배지 |
| O-6 | 현장 실측: Teams v2 DOM 메시지 ID 노출, OWA 분 정밀 비율, CLM·AppLocker 허용, Edge 정책 값, 이벤트 채널 권한, WTS SessionFlags, 클라우드PC 영구형·풀링 VDI, 클립보드 정책, 계정 등급 표식 | 탐침·사유 코드로 남기고 대체 경로 |
| O-7 | UIA 합성 chat_key 의 PC·언어 간 방 매핑 | 웹 chat_key 우선 + 날짜 포함 msg_key 병합 |
| O-8 | 패키지 도구(T-20 검사 포함)의 명세·파일 이름 미정 | 수동 zip 금지, 도구 작성 전 배포 보류 |
| O-9 | **닫힘**(v1.0.1): 저장소 `.gitignore` 에 이미 `config/config.json`·`data/`·`out/` 이 있다(구현 계획 CR-11 확인). 남은 이전 판 잔재 줄(`teamdata/`·`config/settings.local.json`) 정리는 WP-04 | — |
| O-10 | 이전 판 폴더의 `__pycache__` 생성 관찰(CP §17) — 읽기 전용 원칙 확인 | 이전 판 실행·import 금지 |
| O-11 | 단계 유형·분야·기능 어휘와 채널 우선순위의 실데이터 조정(CT 미결 8, R R-Q3) | 기본 어휘 |
| O-12 | `lm27.normalize.act` 의 화행 어미 규칙 세부와 act_cues 추출 규칙(P Q16) | CT §6 가중 규칙 그대로 |

