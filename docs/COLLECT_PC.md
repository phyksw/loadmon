# LM27 PC 사용이력 수집기 명세 (COLLECT_PC.md)

판: v1 · 대상 독자: PC 수집기·상주 에이전트 구현자 · 상위 규율(순서대로 우선): `docs/_decisions.md`(오케스트레이터 결정) → `docs/COLLECTION.md`(수집 공통 계약) → `docs/PRIVACY.md`(정제 명세) → 이 문서

이 문서는 **PC 상주 에이전트와 PC 사용이력 수집기**(샘플러·이벤트 수확기·문서 증거·프로그램 카탈로그·git·수동 기록·로컬 원장·세그먼트 내보내기)를 구현자가 그대로 코드로 옮길 수 있게 규정한다. 메일·일정·팀즈 수집, 시간 추론, 분류, 보고서는 범위 밖이다(별도 명세).

이 문서는 COLLECTION.md 의 레코드 스키마(§3)·경로 ID(§2)·사유 코드(§4.2)·커버리지 원장(§5)·오케스트레이션(§8)·정제 계약(§11)을 **그대로 따른다**. 여기서 새로 정하는 것은 그 계약의 PC 쪽 구체화뿐이다. 충돌 시 COLLECTION.md 가 이긴다.

규칙 재확인(어기면 결함):

- **문서화·지원되는 사용자 인터페이스만**. 금지(설계에 넣지 않음): Graph, 앱 내부 캐시 직접 판독, OST/PST 파싱, 숨김 폴더, 자격 증명, 관리자 권한 요구, 보안 정책 우회. PC 수집기는 Win32 API(user32·wtsapi32·kernel32)·이벤트 로그(사용자 권한 채널)·HKCU 레지스트리·지정 폴더 파일 mtime·`git log`(본인)만 쓴다.
- **원문은 메모리에서만**. 창 제목·전체 경로·커밋 메시지 원문은 어떤 파일에도 쓰지 않는다. 디스크에는 `lm27.privacy.sanitize_record()` 를 통과한 **열 허용 목록 레코드만**(§9·§13).
- 실명·계정·이메일·사내 코드네임을 코드·문서·샘플·프롬프트에 넣지 않는다(예시는 자리표시자 홍길동·과제A·사내해석기).
- 기존 폴더(`D:\배포\loadmon24_v4`, 다른 도구의 `D:\배포\LM26`) 수정 금지(읽기 전용, 이식 후보).
- 다른 사용자에게 수동 조작을 요구하지 않는다 — 자동 설치·자기 복구.

---

## 0. 한눈에 — 구성 요소와 경로 ID 매핑

| 경로 ID(COLLECTION §2) | 저장 kind(COLLECTION §3) | PRIVACY sanitize kind(§10) | 수집기 | 언어 | 상주/주기 |
|---|---|---|---|---|---|
| `pc.sampler` | `pc_session` | `window` | `Start-ActivitySampler.ps1` / `sampler.py` | PS/PY | 상주 60초 |
| `pc.events` | `pc_session` | `session`(§13.3 미결) | `Get-EventActivity.ps1` | PS | 로그온 + 6시간 |
| `pc.files` | `pc_file` | `file` | `Get-FileActivity.ps1` | PS | 수집 시 + 열린 문서 폴링 |
| `pc.mru` | `pc_file` | `file` | `Get-OfficeMru.ps1` | PS | 수집 시 |
| `pc.recent` | `pc_file` | `file` | `Get-RecentFiles.ps1` | PS | 수집 시 |
| `pc.git` | `pc_git` | `git` | `Get-GitActivity.py` | PY | 수집 시 |
| `pc.compute` | `pc_compute` | `compute`(§13.3 미결) | 샘플러 파생 + `Get-LicenseUsage.ps1`(옵트인) | PS | 상주 파생 |
| `manual` | `manual` | `worklog` | `Add-WorkLog.ps1` | PS | 사용자 호출 |

`pc.sampler`·`pc.events` 는 같은 저장 kind(`pc_session`)에 `layer`(L0~L3)로 구분해 쓴다. 저장 kind 와 PRIVACY sanitize kind 의 이름이 다른 종류(`pc_session`↔`window`/`session`, `pc_compute`↔`compute`)는 §13.3 에서 매핑과 미결을 명시한다.

---

## 1. PC 상주 에이전트

### 1.1 위치·배치

에이전트는 **운반 번들 밖**, PC 에 머무는 `%LOCALAPPDATA%` 아래에 설치한다. 폴더 드래그·OneDrive 동기화·이름 바꾸기와 무관하다(LM24 의 '운반 폴더가 데이터를 소유'하는 모델을 폐기 — pc-usage.md discard ①).

```
%LOCALAPPDATA%\LoadMonitor27\agent\<install_id>\
  agent.json                       # 설치 메타(§1.2)
  heartbeat.json                   # 마지막 틱·pid·버전·저장 경로·에이전트 버전(§1.5)
  keys\privacy_keyring.json        # 상주 에이전트용 키링 사본(PRIVACY 3.1 — PC 고정, 팀·번들 반출 금지)
  store\<pc_id>\
    raw_cursor.json                # (pc_id, src) 별 증분 커서(COLLECTION §8.3)
    evidence\<kind>\<src>\YYYYMM\DD.jsonl.gz   # 정제 통과 레코드(추가 전용 로컬 1차 적재)
    sanitize_audit.jsonl           # 정제 감사(유형별 건수만, PRIVACY §15)
    sampler_errors.log             # 루프 안 예외(원문 금지 — 예외 타입·시각만)
    exe_meta.json                  # 처음 본 exe 메타 캐시(§6.4)
    completion_ledger.jsonl        # 열린 문서 저장 이벤트 원장(§5.2)
  bridge_profile\                   # (클라우드PC만) Copilot 전용 Edge 프로필 — 번들에 넣지 않음
```

- `<install_id>` = 설치 시 1회 생성한 UUIDv4(하이픈 제거 32hex). **판·PC·사용자와 무관한 설치 인스턴스 식별자**. 작업명·뮤텍스에 들어가 '판 공통 이름 고착' 결함(pc-usage.md discard)을 막는다.
- `pc_id` = `MachineGuid`(HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid, 사용자 권한 읽기 가능)의 HMAC(PRIVACY 키). 번들·레코드에는 해시만. VDI 로 MachineGuid 가 바뀌면 사용자가 라벨로 별칭 병합(COLLECTION §4.4 aliases).
- 에이전트는 **번들 폴더를 잡지 않는다**(핸들을 열지 않는다) — 폴더 드래그·rename 중에도 죽지 않게. 번들 쓰기는 '수집' 실행 때 짧게만.

### 1.2 agent.json(형)

```json
{"install_id":"7c3f...e1","pc_id":"PCH#3f9a","agent_ver":"26.1.0",
 "installed_at":"2026-10-05T01:00:00Z","root":"D:\\배포\\loadmon27",
 "sampler_impl":"ps","python":"D:\\배포\\loadmon27\\python\\python.exe",
 "task_name":"LM27-7c3f...e1","mutex":"Local\\LM27-7c3f...e1-sampler"}
```

- `sampler_impl` ∈ {`ps`, `py`} — §3.5 자기 시험으로 결정, 캐시.
- `root` 는 '이 설치를 심은 프로그램 트리'. 자기 검증(§1.6)이 작업 Action 경로를 이 값과 대조한다.

### 1.3 설치 진입점 — `Install-Agent.ps1`

```
powershell -NoProfile -ExecutionPolicy Bypass -File collect\Install-Agent.ps1 [-Reinstall]
```

- 모든 PC(클라우드PC 포함)의 첫날에 심는 **'설치 전용' 진입점**(_decisions 10.4). 에이전트 생존 이전 기간은 원장에 '미관측'.
- 절차: ① `install_id` 생성(없으면) → ② `%LOCALAPPDATA%\LoadMonitor27\agent\<install_id>\` 생성 → ③ 샘플러 구현 자기 시험(§3.5)으로 `sampler_impl` 결정 → ④ `agent.json` 기록 → ⑤ `Register-Samplers.ps1 -InstallId <id>` 호출(작업 스케줄러 등록 + 지금 시작) → ⑥ heartbeat 60초 안 생성 확인(§1.6) → ⑦ 결과를 `pc.json` capability `pc.sampler` 절에 기록.
- 종료 코드: `0` 설치·생존 확인 완료 · `1` 자기 시험 실패(두 구현 모두 실패 — 사유 `R-CLM` 등) · `2` 작업 등록 실패(권한·정책) · `3` 이미 설치됨(변화 없음, `-Reinstall` 아님).
- **번들 폴더를 잡지 않음**: 설치는 `%LOCALAPPDATA%` 와 작업 스케줄러만 건드린다.

### 1.4 작업 스케줄러 등록 — `Register-Samplers.ps1`(LM24 이식 + 수정)

LM24 `Register-Samplers.ps1` 을 이식하되 다음을 고친다.

- 작업명·뮤텍스를 **`LM27-<install_id>`** 로(판 공통 'LoadMonitor24-Sampler'·`Local\LoadMonitor24-ActivitySampler' 폐기 — pc-usage.md discard·pitfall).
- **BEL(0x07) 제어문자 결함 수정**: LM24 `Register-Samplers.ps1:175` 의 확인 경로 리터럴 `'data\activity'` 에 `\a`(BEL)가 들어가 `data<BEL>ctivity` 로 깨져 등록 후 확인이 항상 실패하고 60초를 허비했다. LM27 은 경로를 리터럴로 쓰지 않고 `Join-Path $outDir 'evidence'` 조각으로 조립하고, **소스 제어문자 금지 lint 관문**(§14.1)으로 재발을 막는다.
- 옛 작업 정리 정규식을 `^LoadMonitor\d+-` → `^(?:LoadMonitor\d+|LM27-[0-9a-f]+)-` 로 넓혀, 이전 LM27 설치(다른 install_id)가 고아로 남지 않게 한다(이번 install_id 제외).
- 확인 단계는 `heartbeat.json` 존재·신선도(10분 내)로 본다(파일 존재 폴링이 아니라).
- **그대로 유지**(LM24 실측 결정체): XML v1.4 정의, `ExecutionTimeLimit PT0S`(무제한 — LM24 `schtasks /SC ONLOGON` 기본 PT72H 로 3일 뒤 멈춘 사고 A26 수정), `MultipleInstancesPolicy IgnoreNew`, `RestartOnFailure PT1M×99`, 배터리 제한 해제, `LogonTrigger`(이 사용자, Delay PT30S), `InteractiveToken`(화면 창 판독 필요), `LeastPrivilege`, COM `RegisterTaskDefinition` 실패 시 `schtasks /XML` 폴백 + 임시 XML 즉시 삭제(SID·경로 유출 방지), `-DryRun`(등록 없이 파서 검증).

인자: `-InstallId <32hex>`(필수) `-TaskPrefix LM27`(기본) `[-Remove] [-NoStart] [-DryRun]`. 종료 코드: `0` 등록·시작 완료 · `1` 일부 실패.

### 1.5 heartbeat.json(형)

샘플러가 **매 틱**(60초) 원자적으로(tmp→replace) 갱신한다.

```json
{"install_id":"7c3f...e1","pc_id":"PCH#3f9a","pid":12840,"agent_ver":"26.1.0",
 "tick_utc":"2026-10-05T04:05:00Z","tick_local_offset":"+09:00",
 "store":"C:\\Users\\...\\LoadMonitor27\\agent\\7c3f...e1\\store\\PCH#3f9a",
 "sampler_impl":"ps","last_flush_utc":"2026-10-05T04:00:00Z","buffered":37}
```

### 1.6 자기 검증(생존 판정 세 조건 — 모두 참이어야 '살아 있음')

LM24 는 작업명·프로세스 이름만 보고 '살아 있음'으로 판정해, 다른 폴더 샘플러가 돌면 이 폴더가 비어도 정상으로 봤다(pc-usage.md pitfall·discard). LM27 은 셋을 **모두** 확인한다.

1. 작업 스케줄러에 `LM27-<install_id>` 가 있고 그 **Action 경로**가 `agent.json.root\collect\Start-ActivitySampler.ps1`(또는 `sampler.py`)와 일치.
2. `heartbeat.json.tick_utc` 가 now−10분 이내.
3. `store\<pc_id>\evidence\pc_session\pc.sampler\` 의 **가장 최근 레코드**가 now−10분 이내(이 저장소에 실제로 쓰고 있음).

하나라도 거짓이면 분리 재기동(작업 Run). 재기동도 '이미 실행 중'이면 뮤텍스 좀비 의심 → 해당 pid 가 자기 설치의 것인지 `heartbeat.json.pid` 로 확인 후 조치. '미귀속 좀비'는 사유 `R-SAMPLER-ZOMBIE` 로 진단에만 남기고 사용자 조작을 요구하지 않는다.

### 1.7 단일 인스턴스

`New-Object System.Threading.Mutex($true, 'Local\LM27-<install_id>-sampler')`. 생성 실패(이미 있음) → 즉시 `exit 0`(단일 인스턴스). 테스트 실행(`-TestSamples`)은 뮤텍스 없이 별도 파일로.

---

## 2. 저장·운반 모델과 세그먼트 내보내기

### 2.1 두 저장소(COLLECTION §0 준수)

- **로컬 1차 적재**(이 PC 에 머묾): `store\<pc_id>\evidence\<kind>\<src>\YYYYMM\DD.jsonl.gz`. 상주 샘플러·이벤트 수확기·폴링이 추가 전용으로 쓴다.
- **운반 번들**(사용자가 드래그): `D:\배포\loadmon27\data\bundle\pcs\<pc_id>\seg\<seq>_<from_utc>_<to_utc>.jsonl.gz`. **불변**. `<seq>` 는 pc_id 안 단조 증가.

### 2.2 로컬 원장(추가 전용·커서) — LM24 계약 이식

LM24 `pc_ledger.py` 의 결정체(추가 전용·파생 한 벌·폴더 잠금·쓰기 시점 앵커·`live` upsert)를 이식하되, **단일 CSV 가 아니라 pc_id 별 gzip JSONL 세그먼트**에 적용한다(pc-usage.md keep·redesign ①).

- 추가 전용: `(id)` 완전 일치는 중복으로 건너뜀. `pc_session` 의 `live` 세그먼트(부팅 당 1행)는 `ts_utc`(start) 기준 upsert.
- 쓰기 시점 앵커: `pc.json.anchor_since` = min(프로필 생성 시각, 첫 물리 이벤트, now), 1회 기록·불변. 앵커 이전 구간은 쓰기 시점에 자른다(동기화된 타 PC 흔적이 과거 가동으로 새는 것 방지).
- 동시 실행 방어: 원자 쓰기(`.tmp`+PID → `os.replace` 재시도), 파일 잠금(`msvcrt`, 10초 재시도 후 진행). 파생(일별 집계)은 **읽기 시 매번 재생성**(LM24 '704.6h 중 593.5h 소실'·'같은 폴더 8h vs 618h 분열' 사고의 원인인 '세 벌 저장·네 곳 쓰기' 구조를 폐기 — pc-usage.md pitfall).

### 2.3 세그먼트 내보내기(수집 실행 시)

'수집'을 누르면(COLLECTION §0.2 흐름):

1. 에이전트 설치·자기 검증(§1.6).
2. 소스별 커서 이후만 증분 수확(로컬 store 에 1차 적재).
3. 그 pc_id 의 **마지막 내보내기 커서 이후** 로컬 적재분을 새 세그먼트 1개로 번들에 내보냄(`<seq>` 증가). 세그먼트는 `cursor.export_utc` 이후 레코드만. 기존 세그먼트는 **덧붙이기만**, 절대 rename·이동 없음.
4. `pc.json` 능력 탐침 갱신, `manifest.json` 의 세그먼트 sha256 집합 갱신(COLLECTION §0.2·_decisions 10.4 — 멱등 합집합 병합).
5. 커버리지 원장·todo 갱신(COLLECTION §5·§6).

**다른 pc_id 자료는 읽기도 쓰기도 건드리지 않는다.** 같은 pc_id 에 다시 와도 세그먼트를 덧붙일 뿐이므로 '같은 기계가 두 루트로 갈림'(LM24 discard ①)이 생기지 않는다.

---

## 3. 샘플러 v2 (`pc.sampler` → `pc_session`, sanitize kind `window`)

상주 60초 폴링. PC 사용이력의 1차 증거.

### 3.1 원시 틱(메모리 전용)과 저장 레코드

매 틱 메모리에서 수집하는 원시 필드(디스크에 **쓰지 않는다**):

| 원시 필드(메모리) | 획득 | 처리 |
|---|---|---|
| `fg_title`(전경 창 제목 원문) | `GetForegroundWindow`→`GetWindowText` | §3.4 로 doc_key·title_class·title_masked 로 변환 후 폐기 |
| `fg_exe`(전경 프로세스명, 소문자, 확장자 제거) | `GetWindowThreadProcessId`→프로세스 | 그대로 저장 가능(앱 식별자) |
| `fg_pid` | 위 | 저장 안 함 |
| `session_state` | WTS(§3.2) | 저장 |
| `idle_sec` | `GetLastInputInfo`(§3.3) | 저장 |
| `bg_cpu[exe: Δcpu]` | 프로세스 CPU 차분(§3.6) | compute 판정에만 |

플러시 시 `sanitize_record("window", raw, rc)` 를 거쳐 저장 kind `pc_session`(layer=L3) 레코드로 쓴다. 저장 열(COLLECTION §3 + PRIVACY §10.2 window):

```json
{"id":"c4a1...","kind":"pc_session","src":"pc.sampler","pc_id":"PCH#3f9a",
 "ts_utc":"2026-10-05T04:05:00Z","ts_local_offset":"+09:00","ts_precision":"exact","ts_end":"2026-10-05T04:06:00Z",
 "direction":null,"act":"","thread_key":null,"chat_key":null,"counterpart_keys":[],"n_participants":0,
 "app_id":"ansys_mechanical_apdl","doc_key":"과제A_열해석_v3","title_masked":"과제A_열해석_v3 - Ansys",
 "session_state":"active","idle_sec":12,"layer":"L3",
 "flags":{"stuck":false,"remote":false,"always_on":false,"end_uncertain":false},
 "confidence":1.0,"rules_ver":"2026.10.0","observed_at":"2026-10-05T04:06:02Z"}
```

- `title_masked` 는 `TITLE_KEEP_CLASSES`(office·cad·sim·eda·ide·pdf·viewer) 앱에서만 채움(PRIVACY §12.6). 브라우저·메신저·메일 창은 비움(제목이 사람·대화방·사이트 이름이므로).
- `app_class`(window_class 입력)는 프로그램 카탈로그(§6)가 준다. `priv_class`·`site_class`·`inprivate` 는 window 레코드 열에 포함(PRIVACY §10.2).
- `ts_end` = `ts_utc + interval`(이 틱의 커버 구간). `idle_sec > idleActiveSec`(기본 300)인 틱은 활동으로 세지 않음(정규화 단계 규칙, 수집은 값만 남김).

### 3.2 세션 상태 — WTS(LM24 결함 수정)

LM24 샘플러는 잠금·RDP 단절·절전을 기록하지 않고 idle 로만 추정했다. LM27 은 매 틱 WTS 로 직접 관측한다.

- `WTSQuerySessionInformation(WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSSessionInfoEx)` → `SessionFlags`(0=locked, 1=unlocked; OS 판 차이 주의 — §13 미결)와 `WTSConnectState`(Active/Connected/ConnectQuery/Shadow/Disconnected/Idle/Listen/Reset/Down/Init).
- 매핑: `session_state` ∈ {`active`(연결+잠금 해제), `locked`(연결+잠금), `disconnected`(Disconnected), `remote`(세션이 RDP 로 연결 — WTSClientProtocolType≠0)}.
- `locked`/`disconnected` 슬롯은 근무 근거가 아니다(상한으로만, 정규화 단계). 수집은 상태만 남긴다.

### 3.3 idle — GetLastInputInfo 2^32 모듈로(LM24 결함 이식·유지)

```
diff = (GetTickCount64() - LASTINPUTINFO.dwTime)
idle_sec = round( ((diff mod 2^32) + 2^32) mod 2^32 / 1000 )
```

- `dwTime` 은 uint32(GetTickCount 하위 32비트). `TickCount64` 의 하위 32비트와 **2^32 모듈로 차이**가 정답. LM24 의 `Max(0, TickCount32 - dwTime)` 은 가동 24.9~49.7일 구간에서 항상 0 이 되어 점심·이석·야간을 전부 활동으로 계상한 사고(A1).
- `remote` 세션은 idle 이 0 으로 고착될 수 있다 → §3.7 고착 판정으로 거른다.

### 3.4 전경 창 제목 → doc_key·title_class(원문 비저장)

- Office/CAD/시뮬레이터 창의 `문서명 - 앱` 패턴에서 **문서 basename 정규화값**만 `doc_key` 로 뽑는다(확장자·경로·버전꼬리 제거, NFKC, 공백 축약). 예: `과제A_열해석_v3.wbpj - Ansys Workbench` → doc_key `과제A_열해석_v3`.
- `title_class`(=`app_class` 로 전달) ∈ {`office`, `cad`, `sim`, `eda`, `ide`, `pdf`, `viewer`, `browser`, `chat_work`, `mail_work`, `messenger_private`, `media`, `game`, `system`, `idle`, `other`} — 프로그램 카탈로그(§6)의 cat 에서 유도.
- 제목 정제는 `window_class()`(PRIVACY §12.6) + `sanitize(title, "title", ...)`. 원문 제목은 플러시 직후 참조 해제(저장 경로 없음).

### 3.5 두 구현 — PowerShell Add-Type vs 파이썬 ctypes, 자기 시험으로 선택

CLM/AppLocker 환경에서 `Add-Type`(user32/wtsapi32)이 루프 진입 전 조용히 죽는 문제(LM24 pitfall) 대비. 두 구현을 두고 **설치 시 자기 시험 통과 쪽**을 쓴다.

- `Start-ActivitySampler.ps1`(PS, `Add-Type` 으로 user32·wtsapi32·kernel32 P/Invoke).
- `sampler.py`(동봉 CPython 3.11, `ctypes` 로 같은 API). 진입점은 루트를 스스로 `sys.path.insert(0, root)`.
- 자기 시험(`Install-Agent.ps1` 내): 각 구현을 `-TestSamples 3` 로 2초 간격 3틱 돌려 ① 예외 없이 종료 ② 전경 exe·idle·session_state 를 하나라도 실제로 얻었는지 확인. PS 실패(`R-CLM`: LanguageMode≠FullLanguage, 또는 Add-Type 거부) → PY 시험. 둘 다 실패 → `R-CLM` 로 `pc.sampler.ok=false`, 설치 rc 1.
- 두 구현의 **출력 레코드 스키마는 동일**(§3.1). 선택 결과는 `agent.json.sampler_impl` 에 캐시.

### 3.6 정제·플러시 경로(원문 메모리에서만)

상주 루프는 python 파이프를 매 틱 띄울 수 없으므로 배치 플러시한다(PRIVACY §3.5 파이프 재사용).

- 메모리 버퍼에 원시 틱(제목 포함)을 쌓는다. `flushSec`(기본 300) 경과 또는 버퍼 `flushN`(기본 120) 도달 시 플러시.
- 플러시: 버퍼의 원시 틱을 NDJSON 으로 `python\python.exe -X utf8 -I lm27_pipe.py --kind window --source sampler --pc-id <pc_id> --root <root> --out <store>\evidence\pc_session\pc.sampler\YYYYMM\DD.jsonl.gz` stdin 으로 넘긴다. 파이프가 `sanitize_record` 로 줄마다 정제해 **통과분만** gzip append. 요약 1줄(rows_in/stored/dropped)로 heartbeat·감사 갱신.
- `sampler_impl=py` 는 `sanitize_record` 를 in-process 호출(파이프 없이) 후 `lm27.store.append` 로 append.
- 플러시 후 버퍼 참조 해제. **원문 제목은 버퍼(메모리)에만 존재, 디스크에 안 남음.**
- PS 샘플러는 `data\`·`store\` 에 직접 쓰지 않는다(PRIVACY §3.4 lint: `collect\*.ps1` 의 `Out-File`/`Add-Content`/`>>`→`data\` 금지). 모든 디스크 쓰기는 파이프(`lm27.privacy.pipe`→`lm27.store`)가 한다. 예외: `sampler_errors.log`·`heartbeat.json` 은 **에이전트 운영 파일**(evidence 아님)이라 샘플러가 쓰되 원문을 담지 않는다(예외 타입·시각·건수만).

### 3.7 고착 판정 — pc_id 별로(LM24 결함 수정)

LM24 `_activity_spans` 의 고착 통계가 **날짜 키 하나로 모든 PC 를 합쳐** 희석됐다. 합성 실험: PC A(idle 0 1440틱 고착) 단독이면 stuck → 0h, 같은 날 PC B(정상 8h)와 섞이면 stuck 사라지고 **24.0h** 로 계상(pc-usage.md 결함 ②·pitfall).

- LM27 수집기는 고착을 **판정하지 않는다**(판정은 정규화 단계). 다만 수집이 다음을 남겨 정규화가 **(pc_id, 날짜) 단위**로 판정하게 한다: `session_state`(remote 고착 구분), `idle_sec`(원값), `interval`(레코드 ts_end−ts_utc, LM24 'config 간격 가정'으로 120s 샘플러가 절반 계상된 사고 수정).
- 정규화 규칙(참고, 별도 명세 구현): 한 (pc_id, 날짜)에서 커버≥`STUCK_COVER_H`(14h)이고 `idle>0` 비율<`STUCK_IDLE_RATIO`(2%)면 그 PC·그 날만 고착 → 그 PC 하한 모드. **다른 PC 와 섞지 않는다.** 수집기는 이 판정에 필요한 pc_id·interval·idle 을 모든 레코드에 보장한다.

---

## 4. 이벤트 수확기 (`pc.events` → `pc_session`, layer L0/L1)

로그온 시 + 6시간마다. 사용자 권한으로 읽히는 채널만. LM24 `Get-PcOnHistory.ps1` 이식 + 수정.

### 4.1 채널·이벤트 ID(LM24 목록 이식 + TS 추가)

| 채널 | ID | 뜻 | on/off |
|---|---|---|---|
| System(6005/6006) | 6005/6006 | 이벤트 로그 서비스 시작/정지(부팅/종료) | on/off |
| Kernel-Power 42 | 42 | 절전 진입 | off |
| Power-Troubleshooter 1 | 1 | 절전 해제 | on |
| Kernel-Power 506/507 | 506/507 | Modern Standby 진입/이탈(노트북 '가동 없음' 주원인) | off/on |
| System 1074/6008 | 1074/6008 | 종료/비정상 종료 | off |
| Winlogon 7001/7002 | 7001/7002 | 로그온/로그오프(**내 SID 만** — 타 세션이 내 구간을 닫지 않게) | on/off |
| Kernel-General 12/13 | 12/13 | OS 시작/종료 | on/off |
| Kernel-Power 107 | 107 | 절전 해제 | on |
| Diagnostics-Performance/Operational | 100/200 | 부팅/종료(System 롤오버 보완, 권한 필요) | on/off |
| TerminalServices-LocalSessionManager/Operational | 21/23/24/25 | RDP 세션 로그온/로그오프/단절/재연결(VDI·클라우드PC, 권한 될 때) | on/off |

- `Security 4800/4801`(잠금/해제)은 **기대 근거에서 제외**: 비관리자가 거의 항상 `unauthorized`(LM24 discard). 잠금은 샘플러 `session_state` 가 1차 근거. 4800/4801 은 읽히면 보너스로만, 못 읽으면 `R-NOEVT`(사유로 남김, '없음'으로 숨기지 않음).
- `BOOT_IDS`={6005,12,100,21}, `SLEEP_IDS`={42,506,6006,13,1074,6008,200,23,24}.

### 4.2 구간화 규칙(LM24 이식 + end_uncertain)

- `on` 열림 / `off` 닫힘. 켜짐 중의 부팅(boot)이 30분 넘게 뒤에 오면 앞 세션 종료 유실 → `event-gap` 으로 닫음. 같은 부팅의 12/6005/100 은 30분 안이면 같은 부팅으로 묶음.
- **지어낸 끝을 시간으로 세지 않는다**(LM24 discard): LM24 는 종료 유실 시 20h 상한으로 끝을 지어내 가동으로 계상. LM27 은 끝이 불확실한 구간에 `flags.end_uncertain=true` 만 달고, `ts_end` 는 다음 부팅 시각(또는 수확 시점)으로 두되 **정규화가 end_uncertain 구간을 시간으로 세지 않도록** 신호만 남긴다. 20h 상한 절단은 하지 않는다.
- 현재 부팅 세션(`LastBootUpTime` 이후 짝 없는 on)은 `live` 로 '지금까지 켜짐'. `flags.always_on` = 부팅 이벤트는 있는데 절전·종료 이벤트가 기간 내 0 + range≥2일(항상 켜두는 PC — 켜짐=근무 과대계상 경고).
- 1분 미만 구간도 남김(LM20 과 일치 — 버리면 가동이 줄어든 실측).

### 4.3 레코드(pc_session, layer L0/L1)

```json
{"id":"e71a...","kind":"pc_session","src":"pc.events","pc_id":"PCH#3f9a",
 "ts_utc":"2026-10-05T23:02:00Z","ts_local_offset":"+09:00","ts_precision":"minute","ts_end":"2026-10-06T09:11:00Z",
 "act":"","session_state":"active","layer":"L1","idle_sec":null,
 "flags":{"end_uncertain":false,"always_on":false,"remote":false,"stuck":false},
 "confidence":1.0,"rules_ver":"2026.10.0","observed_at":"2026-10-06T09:20:00Z"}
```

- `layer`: L0 = 전원/부팅(6005·12·100·42·506·107·1074), L1 = 세션(7001/7002·21/23/24/25). `confidence`: event 분 단위 1.0, `event-gap`/`event-cap`/추정 끝 0.4(COLLECTION §3.4).
- 이벤트는 **자유 텍스트 없음**(이벤트 ID→on/off·시각만). 정제는 키·시각·열거값만 통과(§13.3 미결: PRIVACY 에 `session` 무텍스트 스키마 추가 필요).

### 4.4 수확 주기화(LM24 pitfall 수정)

- 회사 PC System 로그는 수일~수개월만 남고 롤오버된다(실측 '3개월에 2건', '199일 중 90일'). LM24 는 분석 때만 돌려 과거를 통째로 잃었다.
- LM27 은 **로그온 시 + 6시간마다** 수확해 로컬 원장에 추가 전용으로 쌓는다(수확 주기 < 롤오버 주기). 과거 손실을 구조적으로 제거.
- 증분: `raw_cursor.json` 의 `(pc_id, pc.events)` 커서(마지막 수확 시각) 이후만. 매번 전 기간 재스캔 금지.

### 4.5 인자·종료 코드·상태

`Get-EventActivity.ps1 -InstallId <id> [-From yyyy-MM-dd] [-To yyyy-MM-dd] [-Days 120] [-EventsCsv ev.csv] [-Now '...'] [-BootTime '...'] [-OutDir <폴더>]`(뒤 넷은 시험 주입). 채널별 상태를 `ok|none|unauthorized|error:<msg>` 로 `pc.json` capability 에 숨김없이 남긴다(권한·전원 정책 차이를 사람 차이로 읽지 않게 — LM24 keep). 종료 코드는 §12 공통 계약(0 신규 / 1 없음 / 3 권한 등 불완전).

---

## 5. 문서 증거 (`pc.files`·`pc.mru`·`pc.recent` → `pc_file`)

### 5.1 파일 mtime 스캔 — `Get-FileActivity.ps1`(LM24 이식 + 수정)

- **그대로 이식**: 자동 발견(Recent .lnk 부모, ComDlg32 OpenSavePidlMRU/LastVisitedPidlMRU PIDL 해석, 도구별 MRU 텍스트[MATLAB·Altium·KiCad·Notepad++·VS·IAR·COMSOL·LabVIEW·Eclipse], HKCU 하이브[SolidWorks·Zemax·Altium·Keil·CATIA·LTspice]), 빈도≥2 상위 16 폴더 깊이 6, 복합 확장자(.cas.gz)·Creo 판번호(.prt.12) 판정, 빌드/패키지 폴더는 **표식으로**(이름만으로 X — 'temp'→Temperature_Test·template 오삭제 사고 수정), 자기 설치 폴더 되먹임 차단, 경로 전용 토큰 세그먼트 완전 일치, 관측 이력 400일 합집합, 같은 분·폴더 뭉치 상한(`fileBurstN`, OneDrive 재동기화 야근 오탐 방지), OOXML `docProps/core.xml` `lastModifiedBy` 로 동료 저장 파일 판별(OneDrive 자리표시자 0x400000/0x40000/0x1000 은 열지 않음), author 읽기 90초 예산, 제외는 **건수만**(경로 비기록 — 조용한 삭제 금지).
- **고칠 점**: 수집기가 `data\`·`store\` 에 직접 쓰지 않는다(PRIVACY lint) → NDJSON stdout → `lm27_pipe.py --kind file`. `-Path` 대괄호 와일드카드 함정은 `-LiteralPath` 로. 자기 제외에 **LM27 번들·에이전트 경로 모두** 추가(`data\bundle`, `%LOCALAPPDATA%\LoadMonitor27`).
- **추가**: `op`(create/modify/open) 판정, `root_id`(설정된 감시 루트 ID), `folder_class`(desktop·documents·downloads·onedrive·root·other).

### 5.2 열린 문서 mtime 폴링 → 저장 이벤트 원장화(신규)

- 에이전트가 `filePoll.intervalSec`(기본 300) 마다 **현재 열린 문서**(샘플러 doc_key 가 가리키는 파일) + Recent 상위 `filePoll.topN`(기본 40)의 현재 mtime 을 읽는다. mtime 이 지난 폴링보다 커지면 **저장 이벤트**로 `completion_ledger.jsonl` 에 원장화(op=modify, 저장 시각).
- 목적: LM24 는 mtime 이 마지막 저장만 남겨 실행 사이 중간 저장이 유실됐다(실측 -10pt). 폴링으로 저장 이력을 복원.
- 레코드는 `pc_file`(op=modify)로 세그먼트에 들어가고, `completion_ledger.jsonl` 은 §7 완료 점수의 '저장 이력' 입력.

### 5.3 Office MRU 14/15/16 전수 — `Get-OfficeMru.ps1`(신규, LM24 하드코딩 수정)

- LM24 `Get-RecentFiles.ps1:310` 은 `Office\16.0` **하드코딩** → Office 2013(15.0)·2010(14.0) PC 가 0건(실측). LM27 은 `mru.officeVersions`(기본 `["14.0","15.0","16.0"]`) 전수 열거.
- 경로: 각 버전·앱(Word/Excel/PowerPoint/OneNote/...)의 `HKCU\Software\Microsoft\Office\<ver>\<App>\File MRU`(로컬 계정) **그리고** `...\<App>\User MRU\{LiveId_*|ADAL_*}\File MRU`(M365/조직 로그인 — 최상위 File MRU 는 0건, User MRU 아래 139건 실측). `Place MRU`(폴더 목록)는 제외.
- 파싱: 값 `[T<16진 FILETIME>][O...]*<경로>` → `target_mtime`(FILETIME→UTC)·경로. `target_mtime`(대상 현재 LastWriteTime) 비교로 `op`=open(열람만, target_mtime 이 열람보다 2분+ 과거)/modify.
- Windows **Jump Lists**(`%APPDATA%\Microsoft\Windows\Recent\AutomaticDestinations\*.automaticDestinations-ms`)를 보조 출처로(CAD·해석 도구 .lnk 미생성 보완). `-NoJumpList` 로 끔.

### 5.4 Recent 바로가기 — `Get-RecentFiles.ps1`(LM24 이식)

- `%APPDATA%\Microsoft\Windows\Recent\*.lnk` 의 대상·LastWriteTime(열람 시각)·`target_mtime`. `.lnk` 는 약 150건 롤링. SharePoint URL 은 target 없음(`op`=open).
- MRU 부분은 §5.3 으로 분리(이 수집기는 .lnk 전담). `-RecentDir`(시험)·`-NoMru`.

### 5.5 pc_file 레코드

```json
{"id":"f9b2...","kind":"pc_file","src":"pc.files","pc_id":"PCH#3f9a",
 "ts_utc":"2026-10-05T08:40:00Z","ts_local_offset":"+09:00","ts_precision":"minute","act":"",
 "doc_key":"과제A_설계검토","name_masked":"과제A_설계검토","ext":".pptx","root_id":"R03","folder_class":"documents",
 "app_id":null,"counterpart_keys":[],
 "flags":{"view_only":false,"edit":true,"author_other":false,"pdf_export":false,"final_name":false,"has_file":true},
 "ooxml_totaltime":182,"ooxml_revision":37,"size_bucket":"1-4MB","op":"modify",
 "confidence":1.0,"rules_ver":"2026.10.0","observed_at":"2026-10-05T18:00:00Z"}
```

- 전체 경로 저장 안 함(기본 이름만 정제). 사적 폴더 제외(PRIVACY §10.4: `privacy.path.exclude_keywords` 기본 개인·가족·사진·private·personal, 경로 전용 토큰 완전 일치)에 걸리면 **행 폐기** + `dropped.private_folder` 건수만.
- OOXML `docProps/app.xml` `TotalTime`(편집 분)·`docProps/core.xml` `revision`·`modified`·`lastModifiedBy`(동료≠나 → `flags.author_other`) 를 §7 완료 점수 입력으로 저장(`ooxml_totaltime`·`ooxml_revision`).

---

## 6. 상용/미지 프로그램 카탈로그 (`app_id` 산출)

### 6.1 카탈로그 이식 — LM24 `core/programs.py`

LM24 `programs.py` 를 **그대로 이식**(약 100종 CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통, `_CATALOG`·`EXCLUDE`·`SOLVER_HINTS`·exact/prefix·긴 접두 우선·EXCLUDE 최우선). 단 **'프로그램 사용은 신호가 아니다' 규칙은 폐기**(LM24 `programs.py:10-15`): LM27 목적상 상용/미지 프로그램 사용은 **1급 업무 신호**. 이 규칙의 원인이던 '가중치 비율 MM 배분'은 _decisions §5 의 '구간 귀속' 모델로 대체되므로 안전.

- `is_noise(proc)`: `EXCLUDE` 접두(라이선스 대리자 ansysli·lmgrd…·OS 서비스 svchost…) → True(앱으로 세지 않음).
- `classify(proc, extra)`: `programsExtra`(설정) → exact → 긴 접두 → None. 반환 `{name, vendor, kind(상용/비상용), cat}`. `app_id` = 카탈로그 매칭 시 정규화 표시명 slug, 미상이면 서명자/회사 휴리스틱(§6.3), 그래도 미상이면 `unknown:<exe>`.

### 6.2 solver 기본 목록

`solver_names()` = `SOLVER_HINTS`(ansys·fluent·abaqus·nastran·comsol·lsdyna·…, GUI 전용 hypermesh·patran 제외). `config.solverProcesses` 누락 시 기본값으로 쓴다(LM24: 설정 누락 시 solvers 열 통째 빔 사고). `solverProcessesExclude` 로 ansysli_client 류 상주 대리자 제거.

### 6.3 미지 프로그램 식별(신규)

- 처음 보는 exe 는 1회 `FileVersionInfo`(`CompanyName`·`ProductName`·`FileDescription`·`ProductVersion`)와 Authenticode **서명자**를 `exe_meta.json` 에 캐시.
- 판정 순서: 카탈로그 → `programsExtra` → **서명자/회사 휴리스틱**(예: CompanyName 에 'Ansys'·'Dassault'·'Siemens' 등 알려진 공급사 → 그 공급사의 미분류 상용 도구로 잠정 라벨; 서명자가 Microsoft 면 OS/Office 류) → 미상.
- `exe_meta.json` 형: `{"<exe>":{"company":"...","product":"...","desc":"...","ver":"...","signer":"...","first_seen":"2026-10-05T...","guess_cat":"해석","guess_kind":"상용","source":"signer"}}`. **회사·제품명은 공개 메타데이터**이나 사내 도구명이 들어갈 수 있으므로 `product`·`desc` 는 `sanitize()` 를 거쳐 저장(사내 코드네임 가명화).

### 6.4 팀 공용 라벨링 순환(신규)

- 미상 exe 목록(해시·메타만, 경로·사용자 없음)을 팀 업로드에 '카탈로그 제안'으로 올려(PRIVACY §14 게이트 통과), 팀 서버에서 **팀 공용 카탈로그**로 1회 라벨링해 내려받는다(`programsTeam`). 다음 수집부터 미상이 줄어든다. 개인 exe_meta 는 로컬 유지.

---

## 7. '작성 완료' 후보 점수 (단일업무 종료_2 근거)

문서·상용 프로그램 산출물의 '작성 완료' 시각을 **후보 점수 + 신뢰도**로 낸다. 수집기는 증거를 남기고, 점수 계산은 `lm27.pc.completion.score_doc()` 가 한다(정규화 입력). 이것이 _decisions 의 **종료_2**(상용 프로그램·MS 자료 작성완료) 근거.

### 7.1 증거 항목과 가중(doc_key 단위)

| 증거 | 출처 | 가중 |
|---|---|---|
| (a) 마지막 저장 + 저장 이력 | §5.2 completion_ledger | 기준점(종료 시각 후보) |
| (b) OOXML `app.xml` TotalTime·`core.xml` revision 증가 정체 | §5.5 | +2 (편집량이 큰데 이후 변화 없음) |
| (c) 이후 `completion.quietWorkdays`(기본 3) 근무일 무수정(조용한 기간) | 폴링·mtime | +3 |
| (d) 같은 stem PDF 생성(내보내기) | §7.2 | +2 |
| (e) 같은 파일명(stem)이 발신 메일/팀즈 첨부로 등장 | 메일·팀즈 명세의 `attach_keys` 일치 | +3 |
| (f) 이름 패턴 `최종/final/vN.N/rev/배포` | name_masked 패턴 | +1, `flags.final_name` |
| (g) 그 doc_key 창의 마지막 전경 시각(샘플러) | §3 | 종료 시각 정밀화 |
| 상용 프로그램: compute 종료 + 결과 파일 뭉치 끝 + 마지막 전경 | §8·§5 | (a)~(c) 와 같은 틀 |

- M365 AutoSave 문서는 '저장'이 완료를 뜻하지 않으므로 (c)·(e) 가중을 올린다(§13 미결: 1차 기준 N 값 사용자 결정).

### 7.2 같은 stem PDF 생성 감지

- 같은 폴더(또는 Recent)에 doc_key 와 같은 stem 의 `.pdf` 가 원본 수정 직후 생기면 `flags.pdf_export=true`. 내보내기 = 완료 신호.

### 7.3 출력

- `score_doc(doc_key_evidence) -> (score:int, confidence:float, reasons:list[str])`. `confidence` 등급(A/B/C → 0.8/0.5/0.3). 증거 없으면 '종료 미상'으로 남겨 방법론 계층(시작/종료 조합 추정, _decisions 10.2)에 넘긴다. 코파일럿은 시간·점수를 만들지 않는다.
- 완료 후보는 `pc_file` 레코드 `flags`(final_name·pdf_export)와 별도 파생 산출물(정규화 소유)로 표현. 수집기는 (a)~(g) 입력을 보장할 뿐 점수를 세그먼트에 쓰지 않는다.

---

## 8. 배경 연산(solver) — `pc.compute`

- LM24 는 프로세스 '존재'만으로 solver 를 셌다(ansysli_client 라이선스 대리자가 로그온 내내 떠 '하루 종일 해석' 오탐). LM27 은 **CPU 시간 차분**으로 판정(pc-usage.md redesign ④).
- 샘플러가 매 틱 비시스템 프로세스 `TotalProcessorTime` 을 틱 간 차분. `compute.cpuCoreThreshold`(기본 코어 0.5)·`compute.consecutiveTicks`(기본 3) 연속 초과면 compute 구간. 상주 대리자는 CPU 가 낮아 자동 제외 → EXCLUDE 의존 감소.
- `pc_compute` 레코드: 구간(`ts_utc`·`ts_end`)·`app_id`(카탈로그 라벨)·`flags.solver`. **사람 증거(전경·입력·발신)가 있는 슬롯에서는 귀속 근거로 쓰지 않는다**(_decisions 10.2 '기계 시간' 열, MM 미포함). 사람 증거 없는 제출~대기 슬롯만 상한 규칙 입력.
- 라이선스(FlexLM) 옵트인 — `Get-LicenseUsage.ps1`: LM24 는 호출·소비 없이 **모든 사용자** 체크아웃을 기록(동료 정보 수집). LM27 은 `license.enabled=false` 기본, 켜면 `lmutil lmstat -a -c <server>` 에서 **본인 사용자명·본인 호스트 행만** 남겨 `pc_compute`(src=pc.compute, app_id=제품명)로 편입. 서버 해석이 로컬 샘플러에 안 보이는 공백 보완용.

---

## 9. git (`pc.git` → `pc_git`)

LM24 `Get-GitActivity.py` 이식.

- **본인 신원 정확 일치만**: `git config user.name`/`user.email`(저장소별·전역)과 `%an`/`%ae` 가 **정확히** 같은 커밋만 내 것. `--author` 는 앵커 정규식(`^이름 <`·`<메일>$`, 대소문자 무시)으로 1차 거르고 파이썬이 재확인. 계정명(USERNAME) 부분일치는 **쓰지 않는다**(LM24 'kim'→동료 커밋 혼입 C2 수정, git 신원 전무일 때만 보조).
- 전 브랜치(`--branches --remotes --source --no-merges`), 해시 중복 제거, `LC_ALL=C`(한국어 shortstat 대비), `--date=format-local`(UTC WSL/CI 9h 어긋남 방지). `--since=(from−60일)` 로 넉넉히 받고 기간 필터는 파이썬이 작성일로 재적용(rebase·amend 회수).
- git 실행 파일: `git.exe`(설정) → PATH → Git for Windows·GitHub Desktop·SourceTree·VS 내장 순. 하나도 없으면 '0건 성공'이 아니라 **불완전**(rc 3, 사유 `R-NOGIT`)으로 알림(LM24: GUI git 사용자 개발 신호 통째 누락을 몰랐던 사고 수정).
- 커밋 제목은 **PII 정제 지점**(§11): `msg_masked`(≤120)는 `sanitize()` 통과분. 경로 전용 키워드로 뺀 저장소는 건수만.
- `pc_git` 레코드: `doc_key`=repo 정규화명(`repo_key` HMAC), `subject_tokens`(정제 커밋 제목), `n_commits`(날짜별 묶음), 선택 `n_files`·`exts[]`. `counterpart_keys` 보통 빔(본인 커밋).

인자: `Get-GitActivity.py --install-id <id> [--from yyyy-MM-dd] [--to yyyy-MM-dd] [--scan <경로>]`. 종료 코드는 §12 공통(0/1/3). `git_source.json` 에 status(ok/no_git/all_failed/no_repos)·missing[]·identities·others_excluded.

---

## 10. 수동 업무 기록 (`manual` → `worklog`)

LM24 `Add-WorkLog.ps1` 이식 — **키보드 밖 업무(오프라인 지시·보고·출장·장비점검·현장)의 유일한 신뢰 근거**(_decisions, 요구 '오프라인 지시/보고').

- 인자: `Add-WorkLog.ps1 -Category <자리표시자> -Hours <double> [-Entity <정제대상>] [-Note <정제대상>] [-Date yyyy-MM-dd] [-Start HH:mm] [-End HH:mm]`. `-Start`/`-End` 추가(구간 투입 — PRIVACY worklog 의 start_utc/end_utc).
- `worklog` 레코드: `text_masked`(≤200, Note 정제), `work_category`(Category 자리표시자), `hours`, `start_utc`/`end_utc`(없으면 ts_utc=그 날 00:00+offset, `ts_precision='date'`), 선택 `project_id`·`role_field`·`role_func`(레지스트리 ID). Entity·Note 는 `sanitize()` 통과.
- 수동 기록은 **정답 세트**로 쓸 수 있다(calibrate — _decisions 10.2: 휴면 K·pad 등 파라미터 격자 보정).

---

## 11. PII 정제 지점(요약 — PRIVACY.md 가 소유)

PC 수집기에서 원문이 메모리에 들어오는 세 지점. 전부 디스크 쓰기 직전 `sanitize_record()`/`sanitize()` 통과, 원문 비저장.

| 지점 | 원문 | 저장값 | 규칙 |
|---|---|---|---|
| 창 제목 | `GetWindowText` 결과 | `doc_key`·`title_class`·`title_masked`(허용 앱만) | `window_class()`(PRIVACY §12.6) + `sanitize(.,"title")`. 브라우저 사적 사이트·시크릿·메신저·게임은 priv_class 판정 후 제목 폐기 |
| 파일/문서 경로·이름 | 전체 경로·basename | `name_masked`·`doc_key`·`ext`·`folder_class`·`root_id` | 전체 경로 저장 안 함. 사적 폴더(PRIVACY §10.4)는 행 폐기 |
| 커밋 메시지 | git `%s` | `subject_tokens`/`msg_masked`(≤120) | `sanitize(.,"subject")` — 주민·카드·전화·금액·고객사·사람 토큰화 |

- exe 메타(`product`·`desc`)도 사내 코드네임 가능 → `sanitize()` 통과(§6.3).
- PowerShell 수집기는 레코드를 직접 쓰지 않고 NDJSON stdout → `lm27_pipe.py`(PRIVACY §3.5). 파이썬 수집기는 `sanitize_record` in-process.
- 전송 직전(코파일럿·팀 업로드)은 클라우드PC 가 같은 정제기로 재검사(PRIVACY G3/G4, 별도 명세).

---

## 12. 오케스트레이션·종료 코드·워치독(COLLECTION §8 준수)

- 진입점: `python -m lm27 collect` 가 §0 표의 PC 수집기를 COLLECTION §8.2 순서로 돈다(probe → pc 묶음: sampler 생존 확인 → events → files → mru → recent → git → compute; `parallelMax` 기본 2). 샘플러는 상주이므로 '등록·생존 확인'만.
- **수집기 종료 코드**(COLLECTION §8.4): `0` 저장(신규) · `1` 대상 없음/0건 · `2` 로그인 필요(PC 수집기엔 거의 없음) · `3` 드라이버·권한 불가/불완전 · `4` 읽었지만 신규 0. LM24 git 의 127/124 는 이 계약으로 매핑(없음→3·R-NOGIT, 타임아웃→3·R-TRANSPORT).
- 각 스테이지는 `finally` 에서 `report\stage_result_<stage>.json`(COLLECTION §8.4 형)을 원자적으로 쓴다.
- **타임아웃·워치독**: 샘플러 틱 작업 ≤2초 / 플러시 파이프 ≤120초(초과 kill) / 파일 author 읽기 2초·전체 90초 예산 / 파일 스캔 스테이지 `files.budgetSec` 기본 180초 / git repo 당 60초·스테이지 240초 / 이벤트 수확 ≤60초. 스테이지 감시(COLLECTION §8.4): 하트비트·stdout 15분 무응답=정체, 커서 진전 45분 정지=무진전 → `kill_tree`. 절대 상한 기본 꺼짐.
- 증분 커서(COLLECTION §8.3): `(pc_id, src)` 별 `raw_cursor.json`. 예산은 **커서 진전량**으로 감시(매번 전 기간 재스캔 금지 — LM24 300s 재스캔 사고 수정).

### 12.1 PC 수집기 사유 코드(COLLECTION §4.2 R-* 확장)

COLLECTION §4.2 의 `R-CLM`·`R-NOEVT`·`R-UIAEMPTY`·`R-CAP`·`R-BUDGET`·`R-TRANSPORT` 를 쓰고, PC 전용으로 다음을 추가한다(진단·todo·stage_result 용).

| 코드 | 뜻 | 트리거 |
|---|---|---|
| `R-SAMPLER-CLM` | 두 샘플러 구현 모두 CLM/AppLocker 로 막힘 | PS Add-Type·PY ctypes 자기시험 실패 |
| `R-SAMPLER-ZOMBIE` | 뮤텍스는 쥐었는데 이 저장소에 안 씀 | 생존 3조건 중 ③ 거짓 |
| `R-NOGIT` | git 실행 파일 없음/전 저장소 실패 | git_source.status∈{no_git,all_failed} |
| `R-MRUEMPTY` | Office MRU·Recent 0건 | 설치했으나 문서 연 적 없음 or 정책 |
| `R-RECENTPOLICY` | Recent 정책 차단 | ClearRecentDocsOnExit 등 |
| `R-NOMACHGUID` | MachineGuid 읽기 실패 → pc_id 불확정 | HKLM 읽기 실패 |
| `R-STUCK` | idle 0 고착 의심(품질 플래그, '불가' 아님) | §3.7 판정(정규화) |

`R-STUCK`·`R-SAMPLER-ZOMBIE` 는 '불가 확정'(COLLECTION §6.2) 근거로 쓰지 않는다. `R-TRANSPORT` 와 마찬가지로 품질/수송 범주.

---

## 13. 증거 층·시간대·스키마 매핑

### 13.1 증거 층 L0~L4 정규화(pc-usage.md redesign ⑨)

모든 PC 레코드에 `layer` 또는 유도 가능한 층을 보장한다. 정규화가 층으로 근무 구간을 만든다.

| 층 | 뜻 | 출처 |
|---|---|---|
| L0 | 전원/부팅 | pc.events(6005·12·100·42·506·107·1074) |
| L1 | 세션(로그온·잠금·RDP) | pc.events(7001/7002·21/23/24/25), 샘플러 session_state |
| L2 | 입력 활동(샘플러 idle≤임계) | pc.sampler |
| L3 | 전경 앱·문서 | pc.sampler(fg_exe·doc_key) |
| L4 | 산출물(저장·커밋·발신) | pc.files·pc.mru·pc.recent·pc.git(+메일·팀즈 발신) |

- 근무 구간은 **L2 활동을 1차**, L3/L4 로 귀속, L0/L1 은 L2 없는 날의 상한·하한 폴백(_decisions 5 '근무 봉투'와 정합). 수집은 층·시각만 남기고, 주간/야간/주말/공휴일 경계·고착 판정·귀속은 정규화가 개인 근무제 설정으로(LM24 08/19 하드코딩 폐기).
- 여러 PC 는 시간축 **합집합**으로(병행 사용 중복 계상 방지). mstsc 원격 중인 PC 는 대상 PC 세션과 겹치면 대상으로 귀속(§13 미결 정책).

### 13.2 시간대 — UTC + 오프셋(zoneinfo 금지)

- 모든 레코드에 `ts_utc`(UTC) + `ts_local_offset`(관측 당시 오프셋, 예 `+09:00`). 동봉 파이썬에 tzdata 없음 → `zoneinfo.ZoneInfo('Asia/Seoul')` 실패(실측). **`zoneinfo.ZoneInfo` 사용 금지(관문)**.
- 오프셋은 `ctypes GetDynamicTimeZoneInformation`(또는 PS `[TimeZoneInfo]::Local.GetUtcOffset`)으로 관측 시점에 계산. UTC 설정 클라우드PC 는 `flags.utc_suspect` + 사유 `R-TZ`(COLLECTION), 병합 시 중복 2배 방지(UTC 로 비교).

### 13.3 저장 kind ↔ sanitize kind 매핑과 미결

| 저장 kind(COLLECTION §3) | PRIVACY sanitize kind(§10) | 상태 |
|---|---|---|
| `pc_session`(src=pc.sampler) | `window` | PRIVACY §10.2 존재 — 그대로 |
| `pc_session`(src=pc.events) | **`session`** | PRIVACY 에 무텍스트 스키마 **없음 → 미결(§15)** |
| `pc_file` | `file` | 존재 |
| `pc_git` | `git` | 존재 |
| `pc_compute` | **`compute`** | PRIVACY 에 무텍스트 스키마 **없음 → 미결(§15)** |
| `manual` | `worklog` | 존재 |

- `session`·`compute` 는 자유 텍스트가 없고 키·시각·열거값만이다. 임시 처리: 이들은 `sanitize_record` 의 텍스트 필드가 비어 통과하지만 **여전히 `SanitizedRow` 봉인을 거쳐 `SegmentWriter` 로만** 쓴다(PRIVACY I2). PRIVACY.md 에 두 무텍스트 스키마(텍스트 열 0, 키·시각·열거·flags 허용)를 추가하는 것을 §15 미결로 올린다. 그 전까지 구현은 `window`/`file` 스키마의 텍스트 열을 비운 변형으로 대체하지 않는다(열 누출 assert 회피를 위해 전용 스키마 필요).

---

## 14. 관문(1일차부터)

### 14.1 lint 관문

- **제어문자 금지**: 소스(.ps1/.py/.bat/.md)에 `0x00-0x08,0x0B,0x0C,0x0E-0x1F` 금지(LM24 BEL 사고 재발 방지). `tools\lint.ps1` 에 추가.
- **단일 로더**: 데이터 읽기는 `lm27.store` 로더만(직접 경로 조인 금지 — LM24 'UI 단일 뿌리 함정' 재발 방지).
- **수집기 쓰기 금지**: `collect\*.ps1` 의 `Out-File`/`Set-Content`/`Add-Content`/`Export-Csv`/`>`/`>>` → `data\`·`store\` 금지(PRIVACY §3.4). 예외는 `heartbeat.json`·`sampler_errors.log`(운영 파일, 원문 없음).
- **작업명·뮤텍스 상수에 `install_id` 포함** 확인(판 공통 이름 금지).
- **경로 상수 존재 시험**: `Register-Samplers.ps1`·`Start-ActivitySampler.ps1` 의 저장 경로를 단위시험으로 실제 존재 확인(BEL 류 깨짐 즉시 적발).
- **인코딩**: .ps1=UTF-8 BOM+CRLF, .bat=CP949+CRLF+`>nul chcp 949`, .py/.md/.json=UTF-8 LF, `.gitattributes`에 `* -text`.
- **zoneinfo.ZoneInfo 사용 금지**.

### 14.2 불변식

- 세그먼트 추가만(기존 세그먼트 불변), 다른 pc_id 자료 불변.
- 미관측(not_attempted/blocked/transport_fail/out_of_horizon)을 0h(zero_ok)로 보지 않음(COLLECTION §5.3).
- PII 카나리아 0건(세그먼트·exe_meta·프롬프트·팀 페이로드).
- 시간 보존: 정규화가 (pc_id,날짜) 합집합으로, 병행 PC 중복 계상 0.

---

## 15. 시험 시나리오(합성 하네스 — 실데이터 없이)

하네스는 **저장소 경로를 인자로 받아 실물을 import·실행**한다(LM24 '수정 전 스냅샷을 돌려 안 고쳐진 것으로 보임' 사고 방지). 주입점: 샘플러 `-TestSamples`·가상 시계, `Get-EventActivity -EventsCsv/-Now/-BootTime/-OutDir`, 파일 `-RecentDir/-MruTextDir/-NoToolMru`, MRU `-MruTextDir`.

| # | 시나리오 | 기대 판정 |
|---|---|---|
| 1 | 고착 PC(A: idle 0 1440틱) + 정상 PC(B: 8h) 같은 날 | A 는 그 날 stuck·하한, B 8h. 합집합이 24h 로 희석되지 않음(LM24 결함 ② 회귀) |
| 2 | PC1→PC2→PC1 재방문 | 세그먼트 덧붙임만, 같은 기계 두 루트 분열 없음, 커서 이후분 자연 합류 |
| 3 | VDI 이름 변동·MachineGuid 변동 | 라벨 별칭으로 1 PC 병합, 추가PC 폴더 증식 없음 |
| 4 | UTC 클라우드PC | ts_utc+offset 정합, 병합 중복 2배 없음, `utc_suspect`·`R-TZ` |
| 5 | 롤오버로 이벤트 사라진 뒤 재수확 | 6h 수확분이 원장에 남아 불변, 과거 손실 0 |
| 6 | 동시 실행 2프로세스(UI+bat) | 원장 유실 0, PermissionError 0(잠금·원자 쓰기) |
| 7 | 샘플러 간격 30/60/120s | interval 레코드값으로 시간 계산(120s 절반 계상 사고 회귀) |
| 8 | Office 2013(15.0)·2010(14.0) MRU | MRU 건수>0(16.0 하드코딩 회귀), User MRU 전수 |
| 9 | CLM/AppLocker PC | PS 실패→PY 자기시험, 둘 다 실패면 `R-SAMPLER-CLM`·`pc.sampler.ok=false`, PC 나머지 수집 정상 |
| 10 | BEL 류 깨진 경로 | 제어문자 lint·경로 존재 단위시험이 즉시 실패(FAIL) |
| 11 | 사적 폴더·시크릿 창·메신저 | 사적 폴더 파일 행 폐기(private_folder 건수만), 시크릿·메신저 priv_class private·제목 폐기, 카나리아 0 |
| 12 | 작성 완료(저장→조용한 기간→PDF→발신 첨부) | score_doc 종료_2 후보 점수·confidence·reasons 산출, 증거 없으면 '종료 미상' |
| 13 | 좀비 샘플러(타 install_id 뮤텍스) | 생존 3조건으로 재기동 판정, `R-SAMPLER-ZOMBIE` 진단, 사용자 조작 요구 0 |
| 14 | git 신원 유사 동료명 | 정확 일치만 수집(동료 커밋 혼입 0), git 없음→rc 3·R-NOGIT |

공통 판정: 제어문자 0, PII 카나리아 0, 세그먼트 불변·다른 pc_id 불변, 미관측≠0h, 설정 키 단일 레지스트리(죽은 키 0), bat/ps1 인코딩.

---

## 16. 설정 키(단일 레지스트리)

| 키 | 기본 | 뜻 |
|---|---|---|
| `agent.sampler.intervalSec` | 60 | 샘플러 주기(5 하한) |
| `agent.sampler.flushSec` | 300 | 정제 플러시 주기 |
| `agent.sampler.flushN` | 120 | 버퍼 상한 플러시 |
| `agent.sampler.impl` | `auto` | auto/ps/py(auto=자기시험) |
| `agent.harvest.eventIntervalHours` | 6 | 이벤트 수확 주기 |
| `agent.filePoll.intervalSec` | 300 | 열린 문서 mtime 폴링 |
| `agent.filePoll.topN` | 40 | Recent 폴링 상위 N |
| `agent.heartbeatStaleMin` | 10 | 생존 신선도 |
| `pc.watchFolders` | `[]` | 감시 루트(자리표시자) |
| `pc.watchExtensions` | LM24 248종 이식 | 산출물 확장자 |
| `pc.autoDiscoverFolders` | true | MRU·PIDL·하이브 폴더 자동 발견 |
| `pc.excludeFolderNames` | LM24 목록 | 폴더명 제외 |
| `pc.excludePackageDirs` | true | 빌드·패키지 표식 제외 |
| `pc.fileBurstN` | LM24값 | 같은 분·폴더 뭉치 상한 |
| `pc.files.budgetSec` | 180 | 파일 스캔 예산 |
| `pc.compute.cpuCoreThreshold` | 0.5 | compute 코어 임계 |
| `pc.compute.consecutiveTicks` | 3 | 연속 틱 |
| `pc.programsExtra` | `[]` | 사내 도구 라벨 |
| `pc.solverProcesses` | `SOLVER_HINTS` | solver 이름 |
| `pc.solverProcessesExclude` | ansysli 등 | 상주 대리자 제외 |
| `pc.git.exe` | `""` | git 경로(비우면 자동) |
| `pc.git.repos` | `[]` | 저장소 목록 |
| `pc.git.scanRoots` | `[]` | 자동 탐색 루트 |
| `pc.mru.officeVersions` | `["14.0","15.0","16.0"]` | Office MRU 전수 |
| `pc.mru.jumpList` | true | Jump Lists 보조 |
| `pc.completion.quietWorkdays` | 3 | 조용한 기간 근무일 |
| `pc.license.enabled` | false | FlexLM 옵트인 |
| `pc.license.lmutilPath` | `""` | lmutil 경로 |
| `pc.license.servers` | `[]` | 라이선스 서버 |
| `privacy.path.exclude_keywords` | 개인·가족·사진·private·personal | 사적 폴더 제외(PRIVACY §10.4 소유) |
| `privacy.window.private_exes` | PRIVATE_EXES | 비업무 프로그램(PRIVACY §12.6) |
| `privacy.window.private_profiles` | 개인·Personal | 사적 브라우저 프로필 |
| `privacy.window.work_title_patterns` | `[]` | 사내 업무 사이트 제목어(저장소 기본 빈 값) |
| `probe.budgetSec` | 60 | 능력 탐침 예산(COLLECTION) |
| `confirmBlockedCount` | 2 | 불가 확정 횟수(COLLECTION) |
| `collect.parallelMax` | 2 | 병렬 상한(COLLECTION) |

---

## 17. 미결(사용자·오케스트레이터 결정 필요)

- PRIVACY.md 에 무텍스트 sanitize 스키마 **`session`**(pc.events)·**`compute`**(pc.compute) 추가 필요(§13.3). 그 전까지 두 kind 는 전용 스키마 없이 저장 불가(열 누출 assert).
- 사내 PC 의 CLM/AppLocker 가 `Add-Type`(user32/wtsapi32)·동봉 `python.exe`(ctypes) 실행을 허용하는가 — 샘플러 구현 결정의 전제.
- 클라우드PC 가 영구형인가 풀링 VDI 인가 — MachineGuid 안정성·UTC 여부·RDP 단절 중 예약 작업/idle 동작 실측 필요.
- `TerminalServices-LocalSessionManager/Operational`·`Diagnostics-Performance/Operational` 을 사내 표준 이미지에서 비관리자가 읽는가.
- WTS `SessionFlags` 의 locked/unlocked 의미가 OS 판마다 반전된 사례 — 실측 검증 필요.
- M365 AutoSave '작성 완료' 1차 기준(조용한 기간 N vs 발신 첨부 매칭)과 N 값 — 사용자 결정.
- RDP 로 데스크톱 접속해 일한 시간의 귀속(접속 PC vs 대상 PC)과 원격 측 전경 앱 처리 — 정책 결정.
- UserAssist·ActivitiesCache 등 소급 포커스 이력을 개인정보 동의 범위에서 수집해도 되는가(이번 설계는 미포함).
- FlexLM lmstat 본인 행 조회 권한이 일반 사용자에게 있는가.
- 관찰: `D:\배포\loadmon24_v4\core\__pycache__\progress.cpython-311.pyc` 가 2026-10-05 01:15 에 생성됨(이 설계 작업은 해당 파일을 건드리지 않음) — 저장소 무변경 규칙 관점에서 오케스트레이터 확인 필요.

---

## 반환 요약

- 경로: `D:\배포\loadmon27\docs\COLLECT_PC.md`
- PC 상주 에이전트(`%LOCALAPPDATA%\LoadMonitor27\agent\<install_id>\`, 작업 `LM27-<install_id>`, 생존 3조건 자기검증, 번들 미점유)와 pc_id 별 불변 세그먼트 내보내기를 COLLECTION 계약 위에 구체화.
- 샘플러 v2(WTS 세션 상태·2^32 모듈로 idle·메모리 전용 제목→doc_key/title_class·CPU 차분 compute·exe 메타·PS/PY 자기시험 선택·배치 플러시 정제), 이벤트 6h 수확(end_uncertain, 지어낸 끝 비계상), 문서 증거(mtime·Office MRU 14/15/16 전수·Recent·열린 문서 폴링 저장 원장·OOXML·PDF), 작성 완료 점수(종료_2), 프로그램 카탈로그 이식+서명자 휴리스틱+팀 라벨링, git 본인 신원, 수동 기록, 증거 층 L0~L4, UTC+offset.
- LM24 결함 수정: BEL 제어문자 경로(§1.4·§14.1), PC 미구분 고착 판정(§3.7), 판 공통 작업명·뮤텍스(§1.1), Office 16.0 하드코딩(§5.3), 지어낸 끝 시각(§4.2), 운반폴더 소유 모델·좀비 샘플러(§1.6·§2), Get-LicenseUsage 전 사용자 수집(§8), git 동료 혼입(§9).
