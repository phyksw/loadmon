# LM27 운반 번들 · 팀 업로드 · 팀 서버 명세 (TEAM_AND_BUNDLE)

- 문서 판: v1 (2026-10-05) · 대상: **LoadMonitor27(LM27)** · 런타임: 동봉 CPython 3.11 embeddable(표준 라이브러리만) + Windows PowerShell 5.1
- **이름 교정**: 사용자 지시("LM27로 해달라는 걸 LM26으로 했다")에 따라 제품 이름을 LM27 로 바로잡은 판이다. 이 문서의 모든 식별자 — 프로그램 폴더 `LoadMonitor27\`, 개발 트리 `D:\배포\loadmon27`, 파이썬 패키지 `lm27`, 에이전트 폴더 `%LOCALAPPDATA%\LoadMonitor27\`, 작업 스케줄러 이름 `LM27-<install_id>`, 팀 묶음 `lm27_team_bundle.json`, 서버 신원 `LM27-team`, HTTP 헤더 `X-LM27-*`, 스키마 이름 `lm27.*` — 는 LM27 이다. `D:\배포\loadmon26\docs\TEAM_AND_BUNDLE.md`(LM26 이름판)는 이 문서로 대체되며, 내용이 다르면 이 문서가 우선한다(차이: §0.6).
- `D:\배포\LM26` 은 다른 도구가 만든 **별개 프로젝트**(127.0.0.1:8765~8767)다. 읽기만 하고, LM27 은 이름·포트·작업 이름 어느 것도 겹치지 않는다.
- 이 문서가 정하는 것: ① 여러 PC 를 오가는 **운반 번들**과 **PC 상주 에이전트**(§1), ② 팀으로 보내는 **팀 업로드 묶음** `lm27_team_bundle.json`(§2), ③ **팀 서버**(§3), ④ **팀 취합 산식**(§4), ⑤ **오프라인 대체 경로**(§5).
- 이 문서가 정하지 않는 것(다른 명세 소관): 수집기별 레코드 내용(COLLECTION·COLLECT_*), 정제 규칙표(PRIVACY), 시간 모델(봉투·귀속) 알고리즘, 분류·워크플로우·agentic 판정, 화면 배치. 여기서는 그 결과물을 **어떤 모양으로 담고 옮기고 합치는지**만 정한다. 다른 명세에 요구하는 성질은 §0.4, 경로·이름이 어긋난 곳은 §0.5 에 모았다.
- 자리표시자: 사람 = 홍길동·김철수, 과제 = 과제A, 고객 = 고객사A, 메일 도메인 = example.com. 실명·계정·이메일·사내 코드네임은 이 문서와 코드·샘플 어디에도 쓰지 않는다. 팀 서버 기본 주소 `http://10.115.147.68:9310` 은 사용자가 고정을 지시한 값이다.

---

## 0. 공통 전제

### 0.1 용어

| 용어 | 뜻 |
|---|---|
| ROOT | 사용자가 PC 사이로 통째로 끌어 옮기는 프로그램 폴더(`LoadMonitor27\`) |
| 번들(BUNDLE) | `ROOT\data\` — PC 별 불변 세그먼트·manifest·pc.json 을 담는 운반 저장소 |
| 에이전트 | 각 PC 의 `%LOCALAPPDATA%\LoadMonitor27\agent\` 에 머무는 상주 부분(샘플러·이벤트 수확기·로컬 원장·heartbeat). 폴더 이동과 무관하게 그 PC 에 남는다 |
| 전경 프로세스 | 사람이 띄운 화면 서버·bat·CLI. 번들에 쓰는 유일한 주체 |
| pc_id | PC 식별자 `pc_`+16hex. MachineGuid 의 해시(§1.2) |
| install_id | 에이전트 설치 식별자(32hex, COLLECT_PC §1.1 과 같음). `agent\agent.json` 에 남아 재설치·판 올림에도 유지. 이름에 넣을 때는 앞 8자 `inst8` |
| kind | 증거 레코드 종류(COLLECTION §3.1: `mail`·`cal`·`teams`·`pc_session`·`pc_file`·`pc_git`·`pc_compute`·`manual`). 세그먼트는 kind 별로 나뉜다(+ 정제 감사 스트림 `privacy_audit`, PRIVACY §15.1) |
| 세그먼트 | `pcs\<pc_id>\seg\<kind>\` 아래의 불변 `.jsonl.gz` 파일. 한 번 쓰면 바꾸지 않는다(유일한 예외: §1.14 소급 가림) |
| manifest | PC 별 세그먼트 목록 + sha256 + 내보내기 커서 + 무덤표(tombstone) |
| 팀 묶음 | 팀 서버로 보내는 집계·라벨 전용 JSON 1개(`lm27_team_bundle.json`) |
| 팀 서버 | 팀 공용 PC 에서 도는 표준 라이브러리 HTTP 서버. 기본 `0.0.0.0:9310` |
| 레지스트리 | 팀장이 관리하고 팀 서버가 배포하는 과제·어휘·구성원·에이전트 카탈로그·달력 JSON |
| person_key | 팀 묶음 속 사람 가명 키 `p_`+12hex(번들 생성 때 난수 — HMAC 아님) |
| peer_key | 동료 가명 키 `c_`+12hex(팀 pepper 의 HMAC — 팀원끼리 같은 동료는 같은 키) |

### 0.2 파일·시각 규칙

- `.py`·`.md`·`.json`·`.jsonl` = UTF-8 LF(BOM 없음). JSON 은 **읽을 때만** `utf-8-sig` 허용(메모장·PowerShell 이 붙인 BOM 방어). `.ps1` = UTF-8 BOM + CRLF. `.bat` = CP949 + CRLF + 첫 줄 근처 `>nul chcp 949`.
- 모든 저장 시각은 **UTC ISO8601(`…Z`) + 관측 당시 로컬 offset** 두 값으로 남긴다(레코드 필드는 COLLECTION §3.1 의 `ts_utc`·`ts_local_offset`). 표시·일자 경계는 사람의 근무 시간대 `person.work_tz_offset_min`(기본 540 = +09:00)로 계산한다.
  - 실측(이 PC, 동봉 파이썬 3.11.9): `zoneinfo.ZoneInfo("Asia/Seoul")` → `ZoneInfoNotFoundError`(tzdata 미포함). **IANA 시간대 이름으로 계산하지 않고 고정 offset(분)만 쓴다**(lint 관문: `zoneinfo.ZoneInfo` 호출 금지). 한국은 서머타임이 없어 손실이 없다.
- 원자적 쓰기 함수 하나만 쓴다(§0.3). 최종 파일에 `open(path,"w")` 로 직접 쓰는 코드는 금지(lint 관문).
- **읽기는 열고·다 읽고·즉시 닫는다.** 실측: 다른 프로세스가 대상 파일을 `open()` 으로 열어 둔 동안 `os.replace` 는 `PermissionError(WinError 5)` 로 실패했고, 상대가 닫자 재시도로 성공했다(3초 보유 → 재시도 누계 3.1초). 핸들을 쥔 채 기다리는 코드는 상대의 원자 교체를 막는다.
- 긴 경로: 240자 이상이면 `\\?\`(UNC 는 `\\?\UNC\`) 접두로 다시 연다(LM24 `teamup.longp` 계승). `os.makedirs` 는 확장 경로에서 부모를 거슬러 오르다 깨지므로 한 단계씩 `os.mkdir`.

### 0.3 공용 하위 함수(이 문서 전체가 쓴다)

```python
# lm27/util/fsx.py
def canon_bytes(obj) -> bytes:
    """정규 JSON 바이트 — 같은 값이면 언제나 같은 바이트(미리보기=실전송·sha 멱등의 기초)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")

def atomic_write(path: str, data: bytes, *, fsync=True) -> None:
    """같은 폴더에 <path>.<pid>.<thread>.<rand4>.part 로 쓰고 flush+fsync → os.replace.
    os.replace 가 PermissionError 면 0.1·0.2·0.4·0.8·1.6s 간격으로 재시도(누계 3.1s — 위 실측의 보유 시간과 같은 규모),
    끝내 실패하면 .part 를 지우고 예외를 올린다(반쪽 파일을 남기지 않는다)."""

def read_bytes(path) -> bytes:
    """with open(longp(path), 'rb') as f: return f.read() — 핸들을 즉시 닫는다."""

def read_json(path, default=None, *, want=dict):
    """utf-8-sig 로 읽고 json.loads(object_pairs_hook=reject_dup_keys, parse_constant=reject_nan).
    파일 없음·형식 깨짐·want 타입 아님 → default 반환 + 경고 1줄(조용히 삼키지 않는다)."""

def gzip_bytes(raw: bytes) -> bytes:
    """gzip.GzipFile(filename="", mtime=0, compresslevel=6) — 헤더에 시각·이름을 넣지 않아 결정적(실측)."""

def sha256_hex(b: bytes) -> str: ...
def longp(p: str) -> str: ...            # §0.2
def utcnow_iso() -> str: ...             # 'YYYY-MM-DDTHH:MM:SSZ' (초 단위)
```

`reject_dup_keys`: 같은 객체 안 중복 키 → `ValueError("dup key")`. `reject_nan`: `NaN`·`Infinity` → `ValueError`. (둘 다 실측으로 동작 확인)

### 0.4 다른 명세에 요구하는 성질(이 문서의 전제 계약)

| 번호 | 요구 | 소관 명세 |
|---|---|---|
| R-1 | 모든 수집 레코드는 저장 전에 정제기를 통과한다(원문 비저장). 레코드는 COLLECTION §3.1 공통 필드(`id`·`kind`·`src`·`pc_id`·`ts_utc`·`ts_local_offset`·`observed_at`·`rules_ver`, PRIVACY 의 `kid`)를 가진다. `id` 는 재수집해도 같은 값이다 | COLLECTION·PRIVACY |
| R-2 | 슬롯 꼬리표 `regular`·`extended`·`night`·`holiday` 는 **서로 배타**다(한 슬롯에 하나. 우선순위 휴일 > 야간 > 연장 > 정규) | 시간 모델 |
| R-3 | 귀속 결과는 **정수 분** 표(일자 × 단위업무 × 꼬리표)로 확정한다. 한 슬롯을 여러 업무에 나눌 때는 일자·꼬리표 단위 **최대 잔여법**(동률은 unit_id 사전순)으로 반올림해 Σ귀속 ≤ 봉투(차 = 미귀속)를 정수로 지킨다(원형 2,000회 무작위 시험에서 합 불일치 0). **개인 보고서도 이 정수 표에서 숫자를 낸다**(그래야 개인=팀이 소수점까지 같다) | 시간 모델 |
| R-4 | `unit_id` = `"u_" + keyed(kr, "unit", <시작 근거 키>, 10)`(PRIVACY §9.3 purpose `unit`, §14.2 `UNIT_ID` `^u_[0-9a-f]{10}$`). 재분석해도 같은 단위업무면 같은 값 | 분석·PRIVACY |
| R-5 | 1MM 분모 = `std_day_min`(480) × 그 달 평일 수(주말·공휴일·회사 휴무 제외). 달력은 레지스트리 `calendar` 하나. 관문: 2026-07 = 22, 2026-08 = 20, 2026-09 = 20, 2026-10 = 20 평일(제헌절 7/17 공휴일, 8/17·10/5 대체공휴일 반영 — `calendar_verified.json` 과 일치 실측) | 시간 모델·달력 |
| R-6 | 정제기는 `scan(text, ctx) -> list[Hit]`(§6.2, 치환 없이 범주·건수만), `check_team_label(s, gctx, max_len)`(§14.4), `check_team_payload(obj, gctx, spec)`(§14.5)와 §14.3 금지 값 판정 `forbidden_codes(s, gctx) -> list[str]`(이 이름으로 `lm27.privacy` 에서 재수출 요청)을 제공한다 | PRIVACY |
| R-7 | 에이전트 로컬 원장은 **쓰기(플러시) 시각 기준 일자 파일**에 추가 전용으로 쓴다(`…\YYYYMM\YYYYMMDD.jsonl.gz`, 정제 파이프 `--mode append` 의 gzip 멤버 덧붙이기 — PRIVACY §3.5). 이벤트 날짜로 파일을 고르지 않는다. 그래야 (파일, 마지막 완전한 멤버 끝 바이트 오프셋) 커서가 늦게 수확된 과거 이벤트까지 빠짐없이 잡는다 | COLLECT_PC·PRIVACY |
| R-8 | `role_id` = `"r_" + sha256("LM27.role\|" + (project_id 또는 proposal_id 또는 "UNC") + "\|" + field + "\|" + function)[:6]`(PRIVACY §14.2 `ROLE_ID`) — 키 없는 결정적 값이라 같은 과제·분야·기능이면 팀원 사이에서도 같다. 서로 다른 세 값이 같은 role_id 가 되면(24비트 충돌) 서버가 `role_id_collision` 경고 후 두 역할을 따로 센다 | 분류 |
| R-9 | 팀 묶음의 `apps` 에는 카탈로그(COLLECT_PC §6) 등재 앱 ID 만 싣는다. 미지 프로그램은 이름 없이 분 합계(`apps_unknown_min`)로만(사내 도구 이름 = 사내 코드네임일 수 있다) | COLLECT_PC |

### 0.5 다른 명세와의 정합(이 문서가 우선하는 항목)

LM26 이름판 형제 명세(`D:\배포\loadmon26\docs\`)와 어긋나는 곳이다. LM27 판으로 옮길 때 아래 '맞출 곳'을 이 문서에 맞춘다.

| 항목 | 이 문서(우선) | 형제 명세의 현재 기술 | 맞출 곳·이유 |
|---|---|---|---|
| 번들 루트 | `ROOT\data\pcs\<pc_id>\` | `data\bundle\pcs\…` | COLLECTION §0.2·COLLECT_PC §2.1 |
| manifest | **PC 별** `pcs\<pc_id>\manifest.json`(그 PC 만 쓴다) | 번들 최상위 단일 `manifest.json` | COLLECTION §0.2 — 단일 파일은 사본 번들 병합 때 서로 덮는다 |
| 세그먼트 이름·단위 | kind 별 `seg\<kind>\<seq6>-<inst8>-<t0>-<t1>-<sha8>.jsonl.gz` | kind 통합 `seg\<seq>_<from>_<to>.jsonl.gz` | COLLECTION §0.2·COLLECT_PC §2.3 — 이름에 sha·install 이 있어야 사본 병합에서 충돌이 없다 |
| 내보내기 커서 | manifest `cursors[install_id]["<kind>/<src>"]` = (store 파일, 바이트 오프셋) | `cursor.export_utc`(시각) | COLLECT_PC §2.3 — 시각 커서는 6시간 뒤 수확된 과거 이벤트를 건너뛴다 |
| pc_id | `pc_` + sha256(`"LM27.pc\|"` + MachineGuid 소문자)[:16] — 키 무관·불변 | MachineGuid 의 HMAC(`PCH#3f9a`, 4자) | COLLECTION §3.1·COLLECT_PC §1.1 — HMAC 은 키링 충돌 재매핑(PRIVACY §9.6) 때 바뀌어 폴더가 갈린다. 4자는 충돌 위험 |
| 에이전트 실행 위치 | `%LOCALAPPDATA%\LoadMonitor27\agent\bin\<ver>\` **사본**(동봉 파이썬 `py311\`·정제기 포함 — PRIVACY §3.6 과 같은 위치), 작업 Action 도 그 사본 | Action = `ROOT\collect\Start-ActivitySampler.ps1`, 폴더 `agent\<install_id>\` | COLLECT_PC §1.1·§1.2·§1.6 — 폴더를 PC2 로 옮기면 PC1 의 작업이 없는 파일을 가리켜 다음 로그온부터 PC1 기록이 끊긴다. 에이전트 폴더는 PRIVACY(LM27) 처럼 평면(`agent\`) |
| 로컬 원장 파일 | 쓰기 시각 일자 `YYYYMMDD.jsonl.gz`, gzip 멤버 덧붙이기(R-7) | `…\YYYYMM\DD.jsonl.gz`(일자 기준 미정) | COLLECT_PC §2.1 — 이벤트 날짜로 파일을 고르면 늦게 수확된 과거 이벤트가 이미 내보낸 파일 안쪽에 끼어 커서를 벗어난다 |
| 커버리지 원장·todo | 파생물 `data\derived\coverage_ledger.jsonl`·`data\derived\todo.json`(병합 후 재생성) | 번들 최상위 영구 파일 | COLLECTION §5·§6(결정 메모 10.4 '파생물') |
| 팀 페이로드 필드 | 이 문서 §2.3(`lm27.team_bundle` 1.0)이 소유, 값 클래스·금지 값·라벨 검사는 PRIVACY(LM27) §14 소유(H10) | PRIVACY(LM27) §14.5 대조표는 LM26 이름판 이 문서 기준 | 이번 판에서 추가한 `person.member_id`·`person.pepper_id`·`units[].title_mode`·`units[].apps_unknown_min`·`peers_external`·최상위 `privacy_counts`(PRIVACY Q18 요청 반영)·선택 `catalog_proposals`(PRIVACY §14.5 요청 반영)를 §14.5 에 같은 커밋으로 추가 |
| ID 형식 | 과제 `P-\d{4}`, 역할 `r_`+6hex, 단위업무 `u_`+10hex, 그 밖 레지스트리 ID `^[A-Za-z][A-Za-z0-9_\-]{0,23}$` | PRIVACY(LM27) §8·§14.2 와 같음 | 맞출 것 없음(LM26 이름판 PRIVACY 의 `P0001` 예시는 폐기) |
| 키 위치 | PRIVACY(LM27) §9 그대로: 키링 정본 `data\keys\privacy_keyring.json`(폴더와 이동, 세그먼트·manifest·팀 묶음·코파일럿·패키지 금지), 에이전트에는 용도별 하위 키 `agent\keys\subkeys.json` 만, 팀 pepper 는 레지스트리 캐시 `data\team\registry.json` | 결정 메모 10.4 "개인 비밀은 %LOCALAPPDATA%, 키는 번들·팀 묶음에 넣지 않는다" | PRIVACY H6 의 해석('번들 내용물·팀 묶음에 넣지 않는다')을 따른다 — **미결 1**(PRIVACY Q14) |
| PC 능력 기록 그릇 | `pc.json.capabilities.<키>` 한 항목에 COLLECTION 필드(`ok`·`value`·`reasons`) + `history`·`verdict` | COLLECTION §4.4 `capability`(단수, ok/reasons) · COPILOT_BRIDGE(LM27) §7.13 `capabilities` verdict 어휘 | 둘 다 만족(COPILOT_BRIDGE Q19 해소). COLLECTION 의 그릇 이름을 `capabilities` 로 |
| 정제 감사 위치 | 불변 세그먼트 스트림 `seg\privacy_audit\`(에이전트분은 `agent\store\privacy_audit\` 에서 내보내기) | (LM26 이름판 PRIVACY) `pcs\<pc_id>\audit\privacy_YYYYMM.jsonl` 가변 파일 | PRIVACY(LM27) §15.1(H13)과 같음 |

### 0.6 LM26 이름판(같은 파일명)과 달라진 점

| 구분 | 바뀐 것 |
|---|---|
| 이름 | 전부 LM27(머리말 참조) |
| 달력 | 2026-07 평일을 23 → **22**(제헌절 7/17 공휴일 재지정 반영), 레지스트리 예시 공휴일 목록 보정(10/5 대체공휴일 누락 수정), 부분월 시험 A08 의 분모 21 → **20**, 겹침 시험 수치 재실측 |
| 번들 | 형제 명세와 정합(§0.5): kind 별 세그먼트·COLLECTION 레코드 필드·평면 `agent\` 배치·키링/하위 키/pepper 를 PRIVACY(LM27) 위치로·감사 스트림 `privacy_audit`, 무덤표(§1.4)·소급 가림 재작성(§1.14)·도착 PC 의 누락 세그먼트 이름별 표시(§1.12)·'번들 도착 경로' 탐침(§1.5)·설치 전용 진입점(§1.6.6) 추가 |
| 에이전트 | 에이전트 bin 에 동봉 파이썬·정제기를 두어 PC1 을 떠난 뒤에도 완전한 정제(PRIVACY H15), `py`(파이썬 샘플러)·`ps`(PS 샘플러 + 동봉 정제 파이프) 둘 다 같은 정제기, 로컬 원장 gzip 멤버 덧붙이기와 (파일, 멤버 끝) 커서, 작업 XML `Hidden=false`·`RegisterTaskDefinition` 7인자 |
| 팀 묶음 | `member_id`(선택)·`pepper_id`·`title_mode`·`apps_unknown_min`·`peers_external`·최상위 `privacy_counts`·선택 `catalog_proposals` 추가, 금지 값·`peer_key` 식은 PRIVACY(LM27) §14.3·§9.7, 항목별 가림(§2.5), 품질 절을 COLLECTION 커버리지 상태로 |
| 팀 서버 | 저장소 기본 위치를 `%LOCALAPPDATA%\LoadMonitor27\teamserver` 로(폴더 이동과 분리), 옛 묶음 역전 방지(`stale_kept`), Host 헤더 검사, 방화벽 차단 진단(§3.14, 실측), 이 PC 임시 포트 범위가 9310 을 포함한다는 실측 반영 |
| 취합 | 간트 기본 행 계층을 결정 메모 10.2 대로 **담당자 → 영역 → 과제 → 역할**(피벗 토글), 투입 밀도·병행도 산식 추가, 레지스트리 과제 병합 사슬(`merged_into`) |

---

## 1. 운반 번들(멀티 PC)

### 1.1 배치

```
LoadMonitor27\                                   ← ROOT (폴더째 드래그·복사)
├─ python\  lm27\  collect\  web\  tools\         코드(실행 중 수정하지 않는다)
├─ config\config.json                            사용자 설정(이동 따라감, 비밀 없음)
├─ LoadMonitor27*.bat
├─ out\                                          개인 보고서 산출물(.gitignore)
└─ data\                                         ★ 운반 번들 루트(.gitignore)
   ├─ bundle.json                                번들 신원(§1.2)
   ├─ .bundle.lock                               쓰기 잠금 파일(§1.9)
   ├─ keys\                                      세그먼트·manifest·팀 묶음·코파일럿·패키지·오프라인 내보내기 어디에도 넣지 않는다
   │  ├─ privacy_keyring.json                    HMAC 키링 정본(PRIVACY §9.1·§9.2)
   │  └─ secrets.json                            선택적 업로드 토큰(§7.1)
   ├─ local_only\                                PRIVACY §3.1(사람 사전·소급 가림 목록 등 — 로컬 표시 전용)
   ├─ pc_aliases.json                            논리 PC 결정 기록(추가 전용, §1.8)
   ├─ pcs\<pc_id>\                               ★ 그 PC 만 쓴다. 다른 PC 는 읽기만
   │  ├─ pc.json                                 PC 레지스트리(§1.5)
   │  ├─ manifest.json · manifest.prev.json      세그먼트 목록·sha256·커서·무덤표(§1.4)
   │  ├─ seg\<kind>\<seq6>-<inst8>-<t0>-<t1>-<sha8>.jsonl.gz   (kind 8종 + 정제 감사 `privacy_audit`, PRIVACY §15.1)
   │  ├─ move_ready.json                          이동 준비 결과(§1.11)
   │  └─ quarantine\                             검증 실패 세그먼트(지우지 않고 격리)
   ├─ team\                                      registry.json(팀 pepper 포함 캐시 — PRIVACY §9.1 L2, keys\ 와 같은 반출 금지)·registry.etag·overrides.json(§2.5)
   ├─ outbox\team\{pending,sent,failed,dropped}\  팀 업로드 대기열(§2.8)
   ├─ derived\                                   파생물(언제든 재생성): coverage_ledger.jsonl·todo.json·verify_cache.json·정규화 원장·분석 결과
   └─ logs\
```

```
%LOCALAPPDATA%\LoadMonitor27\                    ← PC 에 남는 부분(이동하지 않는다)
├─ agent\                                        (= AGENT)
│  ├─ agent.json · agent_config.json             설치 메타(install_id 포함, §1.6.2)·에이전트 설정 사본
│  ├─ context_cache.json                         정제 문맥 사본(PRIVACY §3.6 — local_only 와 같은 보호)
│  ├─ keys\subkeys.json                          용도별 하위 키(PRIVACY §9.4 — 주 키 없음)
│  ├─ heartbeat.json                             §1.6.3
│  ├─ bin\<agent_ver>\                           실행 사본: py311\(동봉 파이썬) · lm27\privacy\ · lm27\agent\ · lm27_pipe.py · agent_main.py · ps\ — ROOT 를 참조하지 않는다
│  ├─ store\<pc_id>\evidence\<kind>\<src>\YYYYMM\YYYYMMDD.jsonl.gz   로컬 원장(쓰기 날짜, gzip 멤버 덧붙이기, R-7)
│  ├─ store\<pc_id>\raw_cursor.json              수확 커서(COLLECTION §8.3)
│  ├─ store\privacy_audit\YYYYMM\YYYYMMDD.jsonl    정제 감사(PRIVACY §15.1)
│  ├─ person_dir_delta.json                      에이전트가 본 (주소·표시명) 추가분(PRIVACY §9.6 — [수집] 때 번들 사람 사전으로 합침)
│  ├─ copilot_manual\                            COPILOT_BRIDGE·PRIVACY 소관
│  ├─ export_log.jsonl                           어느 번들로 어디까지 내보냈는지(진단용)
│  ├─ run\                                       stop.flag · harvest_now.flag · harvest_done.json · .harvest.lock
│  └─ logs\agent_YYYYMMDD.log
├─ edge_copilot\                                 코파일럿 전용 Edge 프로필(클라우드PC 에서만, COPILOT_BRIDGE)
├─ bridge\                                       COPILOT_BRIDGE 진단·추적
└─ teamserver\                                   팀 서버 저장소 기본 위치(팀 서버 PC 에서만, §3.7)
```

원칙:
- 번들에는 **정제된 수집물과 그 목록만** 들어간다. 브라우저 프로필·원문·에이전트 실행 파일·팀 서버 저장소는 번들 밖이다(LM24 에서 프로필이 폴더 용량의 96% 였고, DPAPI 에 묶여 도착 PC 에서 죽은 채 수집을 조용히 비게 만든 결함의 근본 제거).
- **다른 pc_id 의 폴더는 읽기만 한다.** rename·이동·삭제·수정 금지(LM24 `archive_other_pc` 의 os.rename 모델 폐기). 예외 없음.
- 번들 읽기는 단일 로더(§1.15)만 한다. `data\pcs` 경로를 직접 조합해 여는 코드는 lint 관문(AST)으로 막는다.

### 1.2 식별자

| 이름 | 생성 규칙 | 저장 | 비고 |
|---|---|---|---|
| `pc_id` | `"pc_" + sha256("LM27.pc\|" + MachineGuid.lower())[:16]` | pc.json·agent.json | MachineGuid = `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`, `winreg.KEY_READ \| KEY_WOW64_64KEY` 로 사용자 권한에서 읽힘(실측). 원값은 어디에도 저장하지 않는다. 키와 무관하므로 키링이 바뀌어도 불변 |
| `pc_id`(대체) | 읽기 실패 시 `"pcx_" + sha256("LM27.pcx\|" + COMPUTERNAME + "\|" + USERPROFILE 폴더 생성시각)[:16]` | 〃 | `id_source="fallback"` 표시. 형식 관문: `^pcx?_[0-9a-f]{16}$` |
| `install_id` | `uuid.uuid4().hex`(32hex) | `agent\agent.json` | (Windows 사용자 × 에이전트 폴더) 당 하나. 재설치·판 올림에도 agent.json 의 값을 그대로 쓴다(새로 만들면 커서가 비어 같은 기록을 다시 내보낸다). `inst8 = install_id[:8]` 을 이름에 쓴다. agent.json 이 사라졌으면 `LM27-*` 작업 중 Action 경로가 이 사용자의 `agent\bin\` 을 가리키는 것의 이름에서 복구, 그것도 없으면 새로 만든다 |
| `bundle_id` | `uuid.uuid4().hex` | bundle.json | 번들 최초 생성 시 |
| `person_key` | `"p_" + secrets.token_hex(6)` | bundle.json | 번들 최초 생성 시 1회. 번들이 이동·복사돼도 그대로 |
| `seq` | (pc_id, kind) 별 manifest 의 최대 seq + 1 | 세그먼트 이름 | 6자리 0 채움 |

`bundle.json`:

```json
{"schema": "lm27.bundle/1", "bundle_id": "3f1c…", "person_key": "p_7fa3c2d19e01",
 "created_at": "2026-10-05T00:12:00Z", "created_on_pc": "pc_9a1b2c3d4e5f6a7b", "lm27_version": "0.1.0"}
```

### 1.3 세그먼트

**이름**: `<seq:06d>-<inst8>-<t0>-<t1>-<sha8>.jsonl.gz` — t0·t1 = 첫·마지막 레코드 `ts_utc` 의 `YYYYMMDDTHHMMZ`, sha8 = 압축 바이트 sha256 앞 8자. 이름에 install·sha 가 들어가므로 **두 사본 번들을 합쳐도 이름이 충돌하지 않는다.** 경로 길이: `pcs\pc_xxxxxxxxxxxxxxxx\seg\pc_compute\000012-a1b2c3d4-20261004T2300Z-20261005T0859Z-5e0c11aa.jsonl.gz` = 96자이므로 ROOT 가 140자를 넘으면 탐침이 경고한다(§1.5 `R-BUNDLE-LONGPATH`).

**내용**(gzip 안의 UTF-8 JSON Lines, 각 줄 = `canon_bytes`):

```
{"_h":1,"schema":"lm27.seg/1","kind":"pc_session","pc_id":"pc_…","install_id":"7c3f…e1","seq":12,
 "t0":"2026-10-04T23:00:00Z","t1":"2026-10-05T08:59:00Z","n":600,"srcs":["pc.events","pc.sampler"],
 "rules_ver":"2026.10.0","kid":"k3f9a1c2e","agent_ver":"0.1.0","created":"2026-10-05T09:02:11Z",
 "src_from":{…커서…},"src_to":{…커서…}}
{"id":"7a1c9f2b0e4d6a81","kind":"pc_session","src":"pc.sampler","pc_id":"pc_…","ts_utc":"2026-10-04T23:00:00Z","ts_local_offset":"+09:00", …COLLECTION §3 필드…}
…
{"_f":1,"n":600}
```

- 머리말(`_h`)·꼬리말(`_f`)이 있어 manifest 없이도 세그먼트만으로 자기 검증·목록 재구성이 된다.
- 레코드는 `(ts_utc, id)` 순 정렬. 같은 세그먼트 안 `id` 중복 금지. 레코드의 `pc_id` 는 폴더의 pc_id 와 같아야 한다(다르면 쓰기 거부).
- **분할 규칙**: (a) 로컬 달(`ts_utc + ts_local_offset` 의 연월)이 바뀌면 새 세그먼트(세그먼트가 두 달에 걸치지 않게 — 기간 선택이 쉬워진다), (b) 레코드 `bundle.segment_max_records`(50,000)건 또는 비압축 `bundle.segment_max_raw_mb`(16MB) 초과 시.
- 크기 감(설계 추정, 실측 아님): pc_session 1분 주기 ≈ 250B/건 × 1,440건/일 → gzip 후 ≈ 30KB/일/PC ≈ 1MB/월/PC.

**kind 표**(레코드 필드는 COLLECTION §3 소관, 여기서는 생산자와 경로만):

| kind | 생산자(경로 ID) | 번들까지 | 중복 접기 |
|---|---|---|---|
| `pc_session` | 에이전트 — 샘플러 `pc.sampler`, 수확기 `pc.events` | store → 내보내기(§1.7) | 로더가 `(kind, id)` |
| `pc_file` | 에이전트 수확기 — `pc.files`·`pc.mru`·`pc.recent` | store → 내보내기 | 〃 |
| `pc_compute` | 에이전트 — 샘플러 파생 `pc.compute` | store → 내보내기 | 〃 |
| `teams` | 에이전트 `teams.uia` + 전경 `teams.web`·`teams.copilot` | 에이전트분은 내보내기, 전경분은 직접 | 〃 (+ 정규화 단계의 `msg_key` 병합, COLLECTION §7) |
| `mail` · `cal` | 전경 수집기(`mail.*`·`cal.*`) | 세그먼트 직접 기록 | 〃 (+ `msg_key`) |
| `pc_git` | 전경 `pc.git` | 직접 | 〃 |
| `manual` | 화면 수동 기록 | 직접 | 〃 |
| `privacy_audit` | 정제 감사 이벤트(PRIVACY §15) — 에이전트 `store\privacy_audit\`, 전경 실행 1회분 | 에이전트분은 내보내기, 전경분은 직접 | 이벤트에 `id` 가 없으므로 내보낼 때 `id = sha256(canon_bytes(이벤트))[:16]`, `kind="privacy_audit"`, `src="agent"`·`"<stage>"` 를 붙인다 |

- 에이전트 kind 는 커서 이후분만 내보내므로 같은 레코드가 두 번 나가지 않는다. 전경 수집기는 같은 기간을 다시 읽으면 같은 `id` 가 다른 세그먼트에 또 생길 수 있다 — **세그먼트는 고치지 않고** 로더가 `(kind, id)` 로 접는다(§1.15). 출처가 다른 같은 메시지의 병합(`msg_key`)은 정규화 단계(COLLECTION §7) 소관이다.

**쓰기**(번들 잠금을 쥔 채로만):

```python
def write_segment(pcdir, kind, ident, records, *, rules_ver, kid, src_from=None, src_to=None) -> dict:
    recs = sorted(records, key=lambda r: (r["ts_utc"], r["id"]))
    if not recs: raise ValueError("empty")
    if len({r["id"] for r in recs}) != len(recs): raise ValueError("dup id")
    if any(r["kind"] != kind or r["pc_id"] != ident.pc_id for r in recs): raise ValueError("foreign record")
    m = load_manifest(pcdir)
    seq = 1 + max((s["seq"] for s in m["segments"] if s["kind"] == kind), default=0)
    head = {"_h": 1, "schema": "lm27.seg/1", "kind": kind, "pc_id": ident.pc_id, "install_id": ident.install_id,
            "seq": seq, "t0": recs[0]["ts_utc"], "t1": recs[-1]["ts_utc"], "n": len(recs),
            "srcs": sorted({r["src"] for r in recs}), "rules_ver": rules_ver, "kid": kid,
            "agent_ver": ident.agent_ver, "created": utcnow_iso(), "src_from": src_from, "src_to": src_to}
    raw = b"\n".join([canon_bytes(head), *map(canon_bytes, recs), canon_bytes({"_f": 1, "n": len(recs)})]) + b"\n"
    gz = gzip_bytes(raw); sha = sha256_hex(gz)
    name = f"{seq:06d}-{ident.install_id[:8]}-{stamp(head['t0'])}-{stamp(head['t1'])}-{sha[:8]}.jsonl.gz"
    dst = join(pcdir, "seg", kind, name)
    if exists(dst):                        # 같은 이름 = 같은 내용이어야 한다
        if sha256_hex(read_bytes(dst)) == sha: return seg_info(dst, head, gz, sha)
        raise SegmentConflict(dst)         # 덮어쓰지 않는다
    atomic_write(dst, gz)
    return {"kind": kind, "seq": seq, "file": relpath(dst, pcdir).replace("\\", "/"), "install_id": ident.install_id,
            "t0": head["t0"], "t1": head["t1"], "n": len(recs), "bytes": len(gz), "sha256": sha,
            "rules_ver": rules_ver, "kid": kid, "created": head["created"], "src_to": src_to}
```

세그먼트를 쓴 **뒤에** manifest 를 갱신한다(2단계). 둘 사이에 죽으면 manifest 에 없는 "고아 세그먼트"가 남는데, 다음 내보내기 때 `adopt_orphans()` 가 머리말·꼬리말·sha 를 검사해 manifest 에 편입한다(커서는 고아의 `src_to` 로 전진). 검사 실패 고아는 `quarantine\` 로 옮긴다(그 PC 자기 폴더 안에서만 이동).

### 1.4 manifest.json

```json
{
  "schema": "lm27.manifest/1",
  "pc_id": "pc_9a1b2c3d4e5f6a7b",
  "gen": 17,
  "updated_at": "2026-10-05T09:02:12Z",
  "segments": [
    {"kind": "pc_session", "seq": 12,
     "file": "seg/pc_session/000012-7c3f1a2b-20261004T2300Z-20261005T0859Z-5e0c11aa.jsonl.gz",
     "install_id": "7c3f1a2b…", "t0": "2026-10-04T23:00:00Z", "t1": "2026-10-05T08:59:00Z", "n": 600,
     "bytes": 18234, "sha256": "5e0c11aa…", "rules_ver": "2026.10.0", "kid": "k3f9a1c2e",
     "created": "2026-10-05T09:02:11Z",
     "src_to": {"pc.sampler": {"file": "pc_session/pc.sampler/202610/20261005.jsonl.gz", "offset": 41872}}}
  ],
  "cursors": {
    "7c3f1a2b…": {
      "pc_session/pc.sampler": {"file": "pc_session/pc.sampler/202610/20261005.jsonl.gz", "offset": 41872, "last_ts": "2026-10-05T08:59:00Z"},
      "pc_session/pc.events":  {"file": "pc_session/pc.events/202610/20261005.jsonl.gz",  "offset": 2210,  "last_ts": "2026-10-05T08:31:07Z"},
      "privacy_audit/agent":   {"file": "privacy_audit/202610/20261005.jsonl",               "offset": 3307,  "last_ts": "2026-10-05T09:00:00Z"}
    }
  },
  "observed_from": {"7c3f1a2b…": "2026-09-01T00:10:30Z"},
  "gaps": [{"install_id": "7c3f1a2b…", "stream": "pc_session/pc.sampler", "from_t": "2025-08-01T00:00:00Z",
            "to_t": "2025-08-03T00:00:00Z", "reason": "store_pruned"}],
  "tombstones": [{"seq": 9, "kind": "teams", "old_sha256": "…", "new_sha256": "…", "reason": "redact", "at": "…"}],
  "quarantine": [{"file": "quarantine/000007-….jsonl.gz", "reason": "sha_mismatch", "at": "…"}],
  "agent_status": {"install_id": "7c3f1a2b…", "impl": "py", "last_tick": "…", "healthy": true, "checked_at": "…"}
}
```

- **manifest 는 세그먼트 sha256 의 집합이다**(결정 메모 10.4). 두 사본 번들을 합치는 일 = sha 합집합이므로 몇 번을 합쳐도 결과가 같다(멱등, §1.13).
- **커서는 번들 쪽(manifest)에 둔다.** 사본 번들이 둘이면 각자 자기가 받지 못한 분량을 내보내야 하기 때문이다. 커서 키는 `"<kind>/<src>"`, 값은 store 의 상대 파일과 **마지막 완전한 gzip 멤버 끝**의 압축 바이트 오프셋(평문 `.jsonl` 이면 마지막 `\n` 다음)(R-7). 에이전트 쪽 `export_log.jsonl` 은 진단용일 뿐 판단 근거가 아니다.
- `observed_from[install_id]` = 그 설치의 첫 heartbeat 시각. 이보다 앞선 기간은 에이전트 kind 에 대해 **'미관측'**(COLLECTION 커버리지 상태 `not_attempted`)이다 — 0시간으로 보지 않는다(결정 메모 10.4).
- `tombstones`: 소급 가림(§1.14)으로 다시 쓴 세그먼트의 옛 sha. 병합·로더는 무덤표에 오른 sha 의 세그먼트를 **읽지도 들여오지도 않는다**(사본 번들에서 가리기 전 판이 되살아나는 것 방지).
- `gen` 은 쓸 때마다 +1. 저장 = `manifest.json` 을 `manifest.prev.json` 으로 복사 → `atomic_write(manifest.json)`.
- 읽기 실패(형식 깨짐) 시 자동 복구 순서: ① `manifest.prev.json` ② `rebuild_manifest()` = `seg\**\*.jsonl.gz` 전수 스캔 → 머리말·꼬리말·sha 로 목록 재구성, 커서는 install·`<kind>/<src>` 별 최신 `src_to`, 무덤표는 `quarantine\tombstones.json` 사본(§1.14)에서. 사용자에게 아무것도 묻지 않고 화면에 "목록을 다시 만들었습니다(세그먼트 N개)"만 알린다.

### 1.5 pc.json

```json
{
  "schema": "lm27.pc/1",
  "pc_id": "pc_9a1b2c3d4e5f6a7b",
  "id_source": "machineguid",
  "label_auto": "PC1",
  "label_user": "",
  "host_display": "<이 PC 이름 — 로컬 표시 전용>",
  "host_class": "a3f9",
  "kind": "desktop",
  "kind_evidence": {"battery": false, "chassis": [3], "model_virtual": false, "rdp_session": false, "host_prefix_cloud": false},
  "kind_confirmed": false,
  "tz": {"utc_offset_min": 540, "windows_tz": "Korea Standard Time", "changes": []},
  "roles": ["pc_usage", "mail_local", "teams_window"],
  "first_seen": "2026-09-01T00:10:00Z",
  "last_seen": "2026-10-05T09:02:12Z",
  "anchor_since": "2026-08-30T23:55:00Z",
  "installs": [{"install_id": "7c3f1a2b…", "created": "2026-09-01T00:10:00Z", "task": "LM27-7c3f1a2b…", "impl": "py"}],
  "visits": [{"at": "2026-10-05T09:02:12Z", "install_id": "7c3f1a2b…", "agent_ver": "0.1.0", "manifest_gen": 17}],
  "flags": [],
  "capabilities": {
    "env":        {"ok": true, "value": {"language_mode": "FullLanguage", "elevated": false, "ctypes_ok": true}, "reasons": [],
                   "history": [{"date": "2026-10-05", "status": "ok"}]},
    "mail.com":   {"ok": false, "value": {"hresult": "0x8001010A"}, "reasons": ["R-COM-BUSY"],
                   "history": [{"date": "2026-10-05", "status": "transport_fail"}], "verdict": "미확인"},
    "mail.owa":   {"ok": false, "value": null, "reasons": ["R-EDGEPOL"],
                   "history": [{"date": "2026-10-02", "status": "fail"}, {"date": "2026-10-05", "status": "fail"}], "verdict": "불가(확정)"},
    "bundle_location":   {"ok": true, "value": {"drive_type": "fixed", "onedrive": false, "redirected": false,
                          "network": false, "writable": true, "free_mb": 51234, "root_len": 38}, "reasons": []},
    "team_server_reach": {"ok": false, "value": {"target": "primary", "result": "timeout", "ms": 4003}, "reasons": ["R-TEAM-TIMEOUT"]}
  }
}
```

- `capabilities` 의 경로 키·`ok`·`reasons`(R-*)·측정값은 **COLLECTION §4 가 소유**한다(코파일럿 쪽 `edge_cdp_policy`·`web_login`·`copilot_connector`·`copilot_env` 는 COPILOT_BRIDGE §7.13 이 채운다). 이 문서는 그릇 형식과 아래 세 가지만 정한다: ① 모든 항목에 `history`(최근 30건, 오래된 것부터 버리고 버린 수는 `history_dropped`), ② `verdict` 계산(아래), ③ 번들·팀 관련 탐침 두 개(`bundle_location`·`team_server_reach`).
- `host_display` 는 그 사용자의 로컬 화면 표시용. **팀 묶음 빌더는 이 필드를 읽지 않는다**(§2.4 허용 목록 방식이라 구조적으로 못 읽는다) — 카나리아 관문이 확인한다. `host_class` = `keyed(kr, "host", 호스트명 앞 4글자 대문자)[:4]`(PRIVACY §9.3 purpose `host`) — VDI 자동 별칭 판단(§1.8)에만 쓴다.
- `label_auto`: 번들에 처음 등장한 순서대로 `PC1`, `PC2`, … ; kind 가 cloud 면 `클라우드PC`, `클라우드PC2`. `label_user` 는 사람이 붙인 이름(로컬 전용, 팀 묶음 금지).
- `kind` 추정: cloud = (모델 문자열에 `Cloud PC` 또는 호스트 접두가 클라우드PC 기본 명명 패턴) ; vdi = 가상 모델(Virtual Machine·VMware·VirtualBox) + 원격 세션 ; laptop = 배터리 있음 또는 섀시 유형 {8,9,10,14,30,31,32} ; 그 밖 desktop. 화면에서 사람이 확정하면 `kind_confirmed=true`.
- `roles`: 그 PC 에서 돌릴 수집 역할. 기본값 — desktop/laptop: `pc_usage, mail_local, teams_window` ; cloud: `pc_usage, account_backfill, copilot`(COLLECTION §1 표, 결정 메모 §3). 화면에서 바꿀 수 있다.
- `anchor_since` = min(사용자 프로필 생성 시각, 그 PC 첫 물리 이벤트, 지금). **처음 한 번만 기록하고 바꾸지 않는다.** 이보다 앞선 시각의 브라우저 힌트·동기화 흔적은 그 PC 의 증거로 쓰지 않는다(LM24 pc_anchor 계승).

**판정**(결정 메모 §3: '불가'는 서로 다른 날 2회 이상 + 수송 실패 아님일 때만 확정, 다시 되면 즉시 해제):

```python
def verdict(history) -> str:
    """history: [{"date": "YYYY-MM-DD", "status": "ok|fail|transport_fail|unknown"}] (오래된 순)
    transport_fail = 시간초과·프로세스 기동 실패·COM 바쁨(대화상자)처럼 '측정 자체가 안 된' 경우 — 불가 근거로 세지 않는다."""
    real = [h for h in history if h["status"] in ("ok", "fail")]
    if not real:
        return "미확인"
    if real[-1]["status"] == "ok":
        return "가능"
    last_ok = max((h["date"] for h in real if h["status"] == "ok"), default="")
    fail_days = {h["date"] for h in real if h["status"] == "fail" and h["date"] > last_ok}
    return "불가(확정)" if len(fail_days) >= confirm_blocked_count() else "불가(잠정)"   # COLLECTION §6.2 설정값(기본 2)
```

**`bundle_location` 탐침**(결정 메모 10.4 '번들 도착 경로', 매 [수집]·화면 기동, 측정은 잠금 없이):

| 값 | 측정 | 사유 코드(경고 — 수집은 막지 않음) |
|---|---|---|
| `drive_type` | `ctypes.windll.kernel32.GetDriveTypeW(ROOT 드라이브 루트)` → 2 removable·3 fixed·4 network(UNC 포함) | `R-BUNDLE-NETWORK`(네트워크 드라이브: 잠금·원자 교체가 불안정할 수 있음) |
| `onedrive` | ROOT 가 `%OneDrive%`·`%OneDriveCommercial%` 아래이거나 `GetFileAttributesW(ROOT\data)` 에 `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS(0x400000)`·`OFFLINE(0x1000)` | `R-BUNDLE-ONEDRIVE`(동기화 충돌 사본·잠금 위험 — 번들 안 파일명에 pc_id 가 있어 동명 충돌은 없음) |
| `redirected` | 바탕화면·문서 Known Folder(`SHGetKnownFolderPath`) 가 UNC 이고 ROOT 가 그 아래 | `R-BUNDLE-REDIRECT` |
| `writable` | `data\.probe_<rand>` 생성·삭제 | `R-BUNDLE-READONLY`(이때 번들 쓰기를 하지 않고 화면에 사유) |
| `free_mb` | `shutil.disk_usage` | `R-BUNDLE-LOWSPACE`(500MB 미만) |
| `root_len` | `len(ROOT)` | `R-BUNDLE-LONGPATH`(140자 초과) |

**`team_server_reach` 탐침**(결정 메모 10.4, [수집]·화면 기동·보내기 직전): `hello()`(§2.9) 결과를 `result ∈ {ok, timeout, refused, dns, proxy, lm24, other_lm, other_app, http_error, wrong_major}` 와 `ms` 로 남기고 사유 코드 `R-TEAM-TIMEOUT`(방화벽·망 분리 의심)·`R-TEAM-REFUSED`(그 주소에 서버 없음)·`R-TEAM-LM24`·`R-TEAM-OTHERAPP`·`R-TEAM-VERSION` 를 붙인다. URL·IP 는 값에 쓰지 않고 `target`(`primary`·`alt1`…)만 쓴다.

### 1.6 PC 상주 에이전트

#### 1.6.1 구성

| 부품 | 실행 | 하는 일 | 쓰는 곳 |
|---|---|---|---|
| 감독(agent 본체) | 작업 스케줄러 `LM27-<install_id>` 가 로그온 시 1개 기동 | 단일 인스턴스 보장, 샘플러 루프, 수확기 주기 기동, heartbeat, 플러시 | `heartbeat.json`, `store\` |
| 샘플러 | 감독 안 루프(60s) | 전경 프로세스·유휴(2^32 모듈로)·세션 상태(WTS)·doc_key·title_class·팀즈 창 UIA(`teams.uia`) — 세부는 COLLECT_PC §3·COLLECT_TEAMS | `store\<pc_id>\evidence\pc_session\pc.sampler\…` 등 |
| 이벤트 수확기 | 감독이 로그온 직후 + `agent.harvest_interval_h`(6) 마다 + `harvest_now.flag` 시 자식 프로세스로 | 이벤트 로그(커서 이후 RecordId), 파일 mtime·MRU·Recent | `store\<pc_id>\evidence\{pc_session,pc_file}\…`, `raw_cursor.json` |
| 로컬 원장 | 파일 | 위 kind 의 추가 전용 일자 파일(R-7) + 정제 감사 `store\privacy_audit\` | `store\` |

**구현 선택**(설치 때 자기 시험, 결과는 `agent.json.impl`):

에이전트 bin 에는 동봉 파이썬(`bin\<ver>\py311\`, 약 21MB — LM24 동봉본 실측)·`lm27\privacy\`·`lm27_pipe.py` 사본이 늘 함께 있다(PRIVACY §3.6·H15). 그래서 두 구현 모두 **같은 정제기**를 거치고, 폴더가 PC2 로 떠난 뒤에도 PC1 에이전트는 완전한 정제기로 계속 수집한다(창 제목 원문은 메모리에서만 — PRIVACY I1). 복사본의 `RULES_HASH` 가 `rules.lock.json` 과 다르면 수집을 멈추고 heartbeat 에 `R-RULESMISMATCH`(조용한 축약 정제 금지).

1. `py`(우선): `bin\<ver>\py311\pythonw.exe bin\<ver>\agent_main.py --install-id <id>`. 파이썬 샘플러(ctypes)가 한 프로세스 안에서 정제까지 한다. `python311._pth` 는 스크립트 폴더를 sys.path 에 넣지 않으므로 `agent_main.py` 가 첫 줄에서 자기 폴더를 스스로 넣는다. 자기 시험: 사본 파이썬 기동 + ctypes `GetForegroundWindow`·`GetLastInputInfo` 호출 + 정제 회귀 표본 5건 통과.
2. `ps`: `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File bin\<ver>\ps\agent.ps1 -InstallId <id>`(Add-Type user32·kernel32·wtsapi32). 원문은 메모리 버퍼에만 두고 플러시 때 **표준입력 파이프로** `bin\<ver>\py311\python.exe bin\<ver>\lm27_pipe.py --kind pc_session --src pc.sampler --pc <pc_id> --out <일자 파일> --mode append` 에 넘긴다(PRIVACY §3.5 — PS 가 store 에 직접 쓰는 줄은 lint 금지). 자기 시험: `$ExecutionContext.SessionState.LanguageMode -eq 'FullLanguage'` + Add-Type 성공 + 파이프 왕복 1건.
3. `none`: 둘 다 실패(AppLocker·CLM 이 `%LOCALAPPDATA%` 실행을 막는 등). 파이썬 없이 PS 만으로 정제 안 된 기록을 쓰는 대체 경로는 두지 않는다(PRIVACY 단일 관문). `agent_status.impl="none"` 과 사유 코드(`R-CLM`·`R-APPLOCKER`)를 기록하고 그 PC 는 [수집] 때 전경에서 되는 경로(이벤트 로그 백필·파일·MRU)만 쓴다. 사람 조치 요구 없음.

- 정책 우회 금지: `-ExecutionPolicy Bypass` 는 프로세스 범위 지정일 뿐이며, 그룹 정책(MachinePolicy/UserPolicy)이 정해져 있으면 무력하다. 그 경우 우회를 시도하지 않고 다음 구현으로 내려간다.

#### 1.6.2 agent.json · agent_config.json

```json
{"schema": "lm27.agent/1", "install_id": "7c3f1a2b…", "pc_id": "pc_9a1b2c3d4e5f6a7b", "agent_ver": "0.1.0",
 "installed_at": "2026-09-01T00:10:00Z", "impl": "py", "task_name": "LM27-7c3f1a2b…",
 "mutex": "Local\\LM27-7c3f1a2b…-agent", "bin": "bin\\0.1.0", "keep_bins": ["0.1.0"],
 "rules_hash": "4a684ebdcf99f956", "subkeys_kid": "k3f9a1c2e"}
```

- `agent_config.json` 은 [수집]·설치 때 ROOT 설정에서 에이전트에 필요한 키만 복사한 것(`agent.*`, 정제 설정 해시). 하위 키는 `keys\subkeys.json`(PRIVACY §9.4 `write_agent_subkeys`), 정제 문맥은 `context_cache.json`(PRIVACY §3.6). **에이전트는 ROOT 의 어떤 파일도 읽지 않는다**(§1.9).
- 에이전트 시작 때 현재 `pc_id` 가 `agent.json.pc_id` 와 다르면(프로필이 따라다니는 풀링 VDI 등) `agent.json.pc_id` 를 고치고 이후 기록을 `store\<새 pc_id>\` 에 쓴다(§1.8).
- LM26 이름판 형제 명세(COLLECT_PC §1.2)의 `root` 필드는 두지 않는다 — 에이전트가 ROOT 에 의존하지 않기 때문이다. "이 설치를 심은 번들"은 manifest `cursors` 의 install_id 로 안다.

#### 1.6.3 heartbeat.json

```json
{"schema": "lm27.hb/1", "install_id": "7c3f1a2b…", "pc_id": "pc_9a1b2c3d4e5f6a7b", "pid": 12345, "agent_ver": "0.1.0",
 "impl": "py", "started_at": "2026-10-05T00:01:02Z", "last_tick": "2026-10-05T09:02:00Z", "interval_s": 60,
 "samples_today": 541, "harvest": {"last_at": "2026-10-05T06:01:10Z", "last_rc": 0, "next_at": "2026-10-05T12:01:10Z"},
 "last_error": ""}
```

매 틱 원자적으로 갱신(tmp → replace, 실패 시 3회 재시도). 마지막 오류는 예외 유형·코드만 200자 이내(경로·사용자명·원문 없이, PRIVACY I8).

#### 1.6.4 작업 스케줄러 등록

- 이름 `LM27-<install_id>`, 뮤텍스 `Local\LM27-<install_id>-agent`. 판·폴더 공통 이름 금지(LM24 공통 이름 때문에 다른 폴더 샘플러를 "살아 있음"으로 오판한 결함).
- XML(작업 스케줄러 스키마 1.4) 핵심값 — LM24 `Register-Samplers.ps1` 의 실측 세트를 계승하고 두 곳을 고친다(★):

```xml
<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{현재 사용자}</UserId><Delay>PT30S</Delay></LogonTrigger></Triggers>
<Principals><Principal id="Author"><UserId>{현재 사용자}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings>
  <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
  <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>          <!-- 기본 PT72H 면 3일 뒤 조용히 멈춘다(LM24 실사고) -->
  <RestartOnFailure><Interval>PT1M</Interval><Count>99</Count></RestartOnFailure>
  <StartWhenAvailable>true</StartWhenAvailable>
  <Hidden>false</Hidden>                                  <!-- 작업 목록에서 사용자가 볼 수 있게(투명성). 창은 pythonw/-WindowStyle Hidden 이 숨긴다 -->
</Settings>
<Actions Context="Author"><Exec>
  <Command>{AGENT}\bin\{ver}\py311\pythonw.exe</Command>    <!-- ps 구현이면 powershell.exe + 위 인자 -->
  <Arguments>"{AGENT}\bin\{ver}\agent_main.py" --install-id {install_id}</Arguments>
  <WorkingDirectory>{AGENT}</WorkingDirectory>             <!-- ★ LM24 는 ROOT 였다 — 폴더 잠금의 원인. 절대 ROOT 를 쓰지 않는다 -->
</Exec></Actions>
```

- 등록 1순위: COM `Schedule.Service` → `GetFolder('\')` → `NewTask(0)` → `XmlText` → `RegisterTaskDefinition(name, def, 6 /*CREATE_OR_UPDATE*/, $null, $null, 3 /*INTERACTIVE_TOKEN*/, $null)`(★ 7인자 — LM24 실측 호출과 같게). 2순위: `schtasks.exe /Create /TN LM27-<id> /XML <tmp> /F` — XML 임시 파일은 **UTF-16 LE BOM** 으로 쓰고 등록 직후 삭제(계정 SID·도메인\사용자·경로가 든 파일을 남기지 않는다, LM24 계승). 관리자 권한 불필요.
- 정리: 이름이 `LM27-*` 이고 Action 경로가 **이 사용자의 `%LOCALAPPDATA%\LoadMonitor27\agent\`** 아래를 가리키지만 install_id 가 `agent.json` 과 다른 작업만 지운다. 다른 경로를 가리키는 `LM27-*`, `LoadMonitor24-*`, `LM26*` 등 남의 작업은 건드리지 않는다.

#### 1.6.5 생존 판정과 자동 복구

```python
def agent_health(ident) -> dict:
    t = query_task(f"LM27-{ident.install_id}")                     # COM, 실패 시 schtasks /Query /XML
    reg = t is not None
    action_ok = reg and same_path(t.action_target, agent_entry(ident))   # pythonw.exe+agent_main.py 또는 powershell+agent.ps1
    hb = read_json(AGENT / "heartbeat.json", {})
    hb_fresh = hb.get("install_id") == ident.install_id and age_s(hb.get("last_tick")) <= cfg.agent.heartbeat_stale_s
    store_fresh = age_s(last_record_ts(AGENT / "store" / ident.pc_id / "evidence/pc_session/pc.sampler")) <= cfg.agent.heartbeat_stale_s
    return {"registered": reg, "action_ok": action_ok, "hb_fresh": hb_fresh, "store_fresh": store_fresh,
            "healthy": reg and action_ok and hb_fresh and store_fresh}

def ensure_agent(ident) -> dict:
    """[수집]·화면 기동·설치 전용 진입점이 호출. 사용자에게 묻지 않는다. rc: 0 정상 / 3 환경 실패(사유 코드)"""
    install_or_upgrade_bin(ident)            # ROOT\python\·lm27\privacy\·lm27\agent\·lm27_pipe.py·collect\agent\*.ps1 → AGENT\bin\<ver>\ 복사
                                             # (같은 판이면 sha256 대조만, 판 2개까지 보관, RULES_HASH 대조 — PRIVACY §3.6)
    kr = load_keyring(ROOT, create=True)     # PRIVACY §9.5 — 키링이 없으면 여기서 만든다(첫 설치 PC 의 키가 폴더와 함께 다음 PC 로 간다)
    write_agent_subkeys(kr, AGENT, audit)    # PRIVACY §9.4 — 주 키가 아닌 용도별 하위 키만
    write_context_cache(AGENT)               # PRIVACY §3.6 — 사전·허용 패턴(키 없음)
    write_agent_config(ident)
    h = agent_health(ident)
    if not h["registered"] or not h["action_ok"]:
        register_task(ident)                 # 같은 이름 덮어쓰기
    if not (h["hb_fresh"] and h["store_fresh"]):
        stop_stale_agent(ident)              # heartbeat.pid 가 살아 있고 명령줄에 install_id 가 있으면 stop.flag → 15s 대기 → 그 pid 만 종료
        run_task(ident)                      # task.Run($null)
        wait_until(lambda: agent_health(ident)["hb_fresh"], timeout_s=60)
    return agent_health(ident)
```

- 판 올림: ROOT 의 에이전트 판이 설치본보다 새것이면 `bin\<새판>\` 복사 → 작업 재등록(Action 경로 교체) → 옛 프로세스에 stop.flag → 새 판 기동. 옛 `bin\` 은 2판까지만 보관.
- 제거: `lm27 agent uninstall` — 작업 삭제 + stop.flag. `store\` 는 남긴다(`--purge` 일 때만 삭제).

#### 1.6.6 설치 전용 진입점

결정 메모 10.4: 모든 PC(클라우드PC 포함)에 **첫날 에이전트만** 심는다. 그 PC 에서 본격 수집을 하기 전부터 샘플러가 쌓이게 하기 위함이다.

- `LoadMonitor27-에이전트설치.bat` = `pushd "%TEMP%"` → `"<ROOT>\python\python.exe" <단일 진입점> agent install --only` → `popd`. 하는 일: `identify_pc()` → `ensure_agent()` → 번들에 `pcs\<pc_id>\pc.json`(최소: 식별·kind·tz·installs)만 쓰고 끝(수집·탐침·내보내기 없음, 5초 안팎).
- 화면 결과: "[완료] 이 PC 에 기록 에이전트를 설치했습니다(LM27-7c3f1a2b…). 이 PC 의 사용 기록은 오늘부터 쌓이며, 나중에 이 폴더로 [수집]을 누르면 번들에 들어옵니다."
- 설치 전 기간은 `observed_from` 이전이므로 에이전트 kind 에 대해 '미관측'으로 원장에 남는다(이벤트 로그 백필로 L0/L1 만 일부 복원).

#### 1.6.7 감독 루프(py 구현 요지 — ps 구현도 같은 구조)

```python
def main(install_id):
    m = win_mutex(f"Local\\LM27-{install_id}-agent")      # CreateMutexW + GetLastError()==ERROR_ALREADY_EXISTS → 종료
    if m.already_exists: return 0
    os.chdir(AGENT_HOME)                                   # cwd 는 언제나 에이전트 폴더
    next_harvest = now()                                   # 로그온 직후 1회
    buf = []                                               # 정제된 샘플 버퍼(원문 아님)
    while True:
        if exists(RUN / "stop.flag"): break
        try:
            s = take_sample()                              # 원문은 메모리에서만 → sanitize_record("pc_session", …) (src=pc.sampler)
            if s is not None: buf.append(s)
            if buf and (age(buf[0]) >= cfg.agent.flush_interval_s or session_locking() or stopping()):
                append_member(store_path("pc_session", "pc.sampler", today_utc()), buf); buf.clear()
            write_heartbeat()
            if now() >= next_harvest or exists(RUN / "harvest_now.flag"):
                start_harvest_child()                      # 숨김 자식 프로세스, 기다리지 않음. .harvest.lock 으로 중복 방지
                next_harvest = now() + hours(cfg.agent.harvest_interval_h)
                remove(RUN / "harvest_now.flag")
        except Exception as e:                             # 루프 안 예외로 죽지 않는다(유형·코드만 기록)
            log_error(type(e).__name__)
        sleep_until_next_tick(cfg.agent.sample_interval_s) # 실제 간격은 레코드에 남긴다
```

- 기록은 **gzip 멤버 단위**다: 정제된 행 묶음을 메모리에서 멤버 하나로 만들어 한 번의 `write` + `flush` + `os.fsync` 로 그 날(쓰기 날짜 UTC) 파일 끝에 덧붙이고 닫는다(핸들 보유 금지, PRIVACY §3.5 `--mode append` 와 같은 형식). 플러시 주기 `agent.flush_interval_s`(300) 또는 세션 잠금·종료 때. 매 플러시 store 폴더 존재를 확인하고 없으면 다시 만든다. 비정상 종료 시 잃는 것은 버퍼(최대 플러시 주기분)뿐이며 그 사실은 다음 heartbeat 의 `last_error` 에 `unflushed_lost` 로 남긴다.
- 읽는 쪽(내보내기)은 완전한 멤버까지만 읽는다(잘린 마지막 멤버는 쓰는 중이거나 깨진 것 — 읽지 않고 오프셋을 그 앞에 둔다).
- 보존: store 일자 파일은 `agent.store_keep_days`(400일)보다 오래되면 삭제. 커서보다 앞선 파일이 지워졌으면 내보내기가 manifest `gaps` 에 `store_pruned` 로 기록한다(조용한 손실 금지).

### 1.7 수집 흐름 — PC1 → PC2 → 클라우드PC, 재방문

[수집](화면 버튼·bat `--auto`) 한 번이 하는 일(COLLECTION §8 오케스트레이션의 번들 쪽 골격):

```python
def collect_here(root, cfg) -> CollectResult:
    ident = identify_pc()                                   # pc_id, install_id(agent.json 또는 새로), kind 추정
    lock = lambda p: BundleLock(root, purpose=p, timeout_s=cfg.bundle.lock_timeout_s)
    loc = probe_bundle_location(root)                       # §1.5 — 읽기 전용이면 여기서 rc=3, 사유 표시
    with lock("collect-init"):
        b = ensure_bundle(root)                             # bundle.json·keys\ 없으면 생성(키링은 PRIVACY load_keyring)
        pcdir = ensure_pc_dir(root, ident)                  # pcs\<pc_id>\ 없으면 생성 — 다른 pc_id 폴더는 손대지 않는다
        redact_rewrite_own(pcdir)                           # §1.14 — 이 PC 세그먼트에 대해 미처리 소급 가림이 있으면
    h = ensure_agent(ident)                                 # ① 에이전트 설치·등록·생존(번들 잠금 불필요)
    request_harvest_now(ident, wait_s=cfg.agent.harvest_wait_s)   # ② harvest_now.flag → harvest_done.json 대기(최대 120s)
    with lock("export"):
        ex = export_agent_streams(pcdir, ident, cfg)        # ③ store → 세그먼트(커서 이후분, 정제기 재적용)
    fg = run_foreground_collectors(pcdir, ident, roles=pc_roles(pcdir), lock=lock)
                                                            # ④ COLLECTION §8.2 단계. 수집은 잠금 없이, 세그먼트·manifest
                                                            #    쓰기 구간에서만 lock("fg-write") — 긴 백필이 다른 쓰기를 막지 않게
    pr = probe_capabilities(pcdir, ident)                   # ⑤ 능력 탐침(측정은 잠금 없이) + team_server_reach
    with lock("collect-finish"):
        record_probes(pcdir, pr, loc)                       #    → pc.json
        touch_visit(pcdir, ident, h, gen=ex.manifest_gen)   # ⑥ last_seen·visits·agent_status
        al = auto_alias(root, cfg)                          # ⑦ 논리 PC 병합 판단(§1.8)
    rebuild_derived_coverage(root)                          # ⑧ coverage_ledger·todo 재생성(파생물, 잠금 없이 원자 교체)
    send_due(cfg)                                           # ⑨ 승인된 팀 묶음 대기분 자동 전송(§2.8) — 클라우드PC 에서 승인한 것이 사내 PC 에서 나간다
    return CollectResult(...)                               # 화면: kind 별 새 레코드 수·gaps·격리·탐침 판정
```

```python
def export_agent_streams(pcdir, ident, cfg):
    m = load_manifest(pcdir)
    adopt_orphans(pcdir, m)
    for stream in agent_streams(ident):                     # "pc_session/pc.sampler", "pc_session/pc.events", "pc_file/pc.files", …
        kind, src = stream.split("/")
        cur = m["cursors"].get(ident.install_id, {}).get(stream)
        recs, new_cur, gap = read_store_since(ident, kind, src, cur)   # 완전한 gzip 멤버만, 일자 파일 경계 넘어 쓰기 순서대로
        if gap: m["gaps"].append(gap)
        recs = [resanitize_row(kind, r) for r in recs]     # PRIVACY §10.5 — 현재 규칙으로 한 번 더(단조: 가린 값은 되살아나지 않음)
        recs = [r for r in recs if r is not None]          # 폐기 행은 건수만 감사(I9)
        recs = [r for r in recs if r["ts_utc"] >= pc_anchor(pcdir)]    # anchor_since 이전 흔적 제외
        for chunk in split_by_local_month_and_size(recs):
            info = write_segment(pcdir, kind, ident, chunk, rules_ver=RULES_VER, kid=KID,
                                 src_from={src: cur}, src_to={src: chunk_cursor(chunk, new_cur)})
            m["segments"].append(info)
        m["cursors"].setdefault(ident.install_id, {})[stream] = new_cur
        m["observed_from"].setdefault(ident.install_id, first_heartbeat(ident))
    save_manifest(pcdir, m)                                 # gen+1, prev 보관, 원자적
    append_export_log(ident, m)
    merge_person_dir_delta(AGENT, root)                     # PRIVACY §9.6 — 에이전트가 본 (주소·표시명) 추가분을 번들 사람 사전으로

def read_store_since(ident, kind, src, cur):
    """store\\<pc_id>\\evidence\\<kind>\\<src>\\ 의 일자 파일을 이름(=쓰기 날짜) 순으로 cur.file 부터 읽는다.
    .jsonl.gz: cur.offset(압축 바이트)부터 멤버를 하나씩 푼다 —
        d = zlib.decompressobj(wbits=31); data = d.decompress(buf[pos:])
        d.eof 이면 완전한 멤버: 줄로 나눠 레코드, 다음 멤버 시작 = len(buf) - len(d.unused_data)
        d.eof 가 아닌 채 끝나면 잘린 마지막 멤버: 버리고 offset 을 pos 에 둔다(다음 내보내기 때 다시 본다).
    .jsonl(privacy_audit): 마지막 '\\n' 까지만.
    cur.file 이 지워졌으면(보존 기한) 다음 파일부터 읽고 gap(store_pruned, 지워진 날짜 범위)을 돌려준다.
    반환: (레코드 목록, 새 커서 {file, offset, last_ts}, gap|None)"""
```

단계별 시나리오:

| 단계 | 어디서 | 무엇이 생기나 | 핵심 |
|---|---|---|---|
| 설치 전용(선택, 첫날) | PC1·PC2·클라우드 | 각 PC 에 에이전트, 번들에 최소 pc.json | §1.6.6. 이후 기록이 각 PC 에 쌓인다 |
| PC1 첫 [수집] | PC1 | `pcs\<pc1>\` 세그먼트, 이벤트 로그 백필(남은 만큼), 파일·MRU, 메일 로컬 경로 | 브라우저 힌트는 `anchor_since` 이후·낮은 신뢰도 백필 전용 |
| PC1 반복 | PC1 | 커서 이후 세그먼트 추가 | 같은 폴더에서 몇 번을 눌러도 중복 없음(rc 4 = 새것 없음) |
| [이동 준비] | PC1 | 마지막 내보내기 + 이동 가능 시험 + move_ready.json(§1.11) | **에이전트는 멈추지 않는다** — 떠난 뒤에도 PC1 에 계속 쌓인다 |
| PC2 첫 실행 | PC2 | `pcs\<pc2>\` 생성(PC1 폴더는 그대로), PC2 에이전트·백필 | `label_auto=PC2`, 도착 점검(§1.12) |
| 클라우드PC | 클라우드 | `pcs\<cloud>\`, 계정 단위 백필(메일·팀즈·일정 기간 전체), 코파일럿 분석, 팀 묶음 빌드·승인 | Edge 프로필은 `%LOCALAPPDATA%\LoadMonitor27\edge_copilot\`. 팀 서버가 안 닿으면 묶음은 `outbox\team\pending\` 에 승인 상태로 대기 |
| PC1 재방문 | PC1 | PC1 커서 이후분(떠나 있던 동안 쌓인 것 포함) 추가 + 대기 묶음 자동 전송 | rename 없음 → "같은 기계가 두 뿌리로 갈림"이 원천적으로 없다 |

- 계정 단위 자료(메일·팀즈·일정)는 PC 마다 일부, 클라우드PC 가 전체를 가질 수 있다. 각 PC 의 것이 각자 `pcs\<pc_id>\seg\mail\` 에 들어가고, 정규화 단계가 `msg_key` 로 접는다.
- 도착 PC 에서 "이 PC 자료 없음 + 다른 PC 자료 있음"이어도 [재분석]만 눌렀다고 수집을 건너뛰지 않는다: 분석 시작 전에 이 PC 의 `pcs\<pc_id>\` 가 없거나 마지막 내보내기가 24시간 넘었으면 `collect_here()` 를 1회 먼저 돈다(LM24 `--skip-collect` 결함 계승 방어).
- 화면(번들 현황)은 PC 마다 "마지막 내보내기 10-05 09:03 — 그 뒤 기록은 PC1 에 남아 있음(PC1 에서 [수집]하면 들어옴)"을 보인다. 번들이 그 PC 로 돌아가지 않으면 그 뒤 기록은 분석에 없다는 사실을 숨기지 않는다.

### 1.8 VDI·MachineGuid 변동과 논리 PC

- 이름(COMPUTERNAME) 변동: pc_id 가 MachineGuid 기반이라 무관.
- 풀링 VDI·재이미징으로 **MachineGuid 자체가 바뀌면** 세션마다 새 pc_id 폴더가 생긴다. 폴더는 그대로 두고(불변), `pc_aliases.json` 에 "같은 논리 PC" 결정만 추가한다.
- 풀링 VDI 의 에이전트: 작업 스케줄러 작업은 이미지에 남지 않으므로 새 세션에는 에이전트가 없다. 프로필(`%LOCALAPPDATA%`)이 따라다니는 구성이면 `agent\` 와 install_id 는 남아 있고, 그 세션에서 [수집]·설치 전용 진입점을 한 번 실행하면 같은 install_id 로 작업을 다시 등록한다(`agent.json.pc_id` 는 새 값으로 갱신, 기록은 `store\<새 pc_id>\`). 로그온 때 자동 재등록은 IT 의 로그온 스크립트 영역이라 LM27 이 하지 않는다(미결 19). 그 전 구간은 '미관측'.

```json
{"schema": "lm27.pcalias/1",
 "decisions": [
   {"at": "2026-10-05T09:02:12Z", "pc_id": "pc_c3…", "logical": "pc_a1…", "rule": "auto_vdi",
    "why": {"kind": "vdi", "host_class": "a3f9", "tz": 540, "gap_min": 1440}},
   {"at": "2026-10-06T01:00:00Z", "pc_id": "pc_c3…", "logical": "pc_c3…", "rule": "user_undo"}]}
```

```python
def auto_alias(root, cfg):
    if not cfg.bundle.auto_alias_vdi: return []
    pcs = load_all_pc_json(root); amap = logical_map(root)            # 같은 pc_id 는 마지막 결정(at 순)이 이긴다
    made = []
    for new in sorted(pcs, key=lambda p: p.first_seen):
        if new.pc_id in amap or new.kind not in ("vdi", "cloud"): continue
        cands = [old for old in pcs
                 if old.pc_id != new.pc_id and old.kind == new.kind
                 and old.host_class == new.host_class and old.tz.utc_offset_min == new.tz.utc_offset_min
                 and not samples_overlap(root, old.pc_id, new.pc_id, tol_min=cfg.bundle.overlap_tolerance_min)]
        if len({logical_of(c, amap) for c in cands}) == 1:              # 후보 논리 PC 가 정확히 하나일 때만
            made.append(record_alias(root, new.pc_id, logical_of(cands[0], amap), rule="auto_vdi"))
    return made
```

- `samples_overlap`: 두 pc_id 의 pc_session 세그먼트 시간 구간이 `overlap_tolerance_min`(10분) 넘게 겹치면 **동시에 쓰인 서로 다른 기계**이므로 합치지 않는다.
- 논리 PC 는 표시·PC 단위 품질 집계(PC 수·라벨)에만 쓴다. 시간 봉투는 원래 모든 PC 합집합이므로 별칭과 무관하게 같다(병합 오판이 MM 을 바꾸지 않는다).
- **같은 MachineGuid 를 가진 두 기계**(sysprep 없이 복제된 이미지): 같은 pc_id 아래 install_id 가 둘이고 pc_session 이 겹치면 pc.json `flags` 에 `"pc_id_collision"` 을 넣고, 로더는 고착·간격·커버리지 판정을 `(pc_id, install_id)` 단위로 한다(LM24 의 '날짜 단위 고착 판정 희석' 결함 방어 — 고착 PC 와 정상 PC 를 섞으면 고착이 24h 활동으로 계상됐다). pc.json 은 두 기계가 번갈아 쓰므로 `installs`·`visits` 는 합집합으로만 갱신한다.

### 1.9 폴더 잠금 방지와 번들 쓰기 잠금

실측(이 PC, 동봉 파이썬, 2026-10-05 재실측): 폴더 안 파일을 연 프로세스가 있거나 **어떤 프로세스의 cwd 가 폴더 안에 있으면** 폴더 이름 바꾸기가 `WinError 5` 로 실패한다. Restart Manager(`rstrtmgr.dll` `RmGetList`)는 비관리자로도 **파일**을 쥔 프로세스를 정확히 찾았으나(pid·이름) **폴더(cwd)** 는 오류 5 로 답하지 못했다. 아무도 쥐지 않으면 성공.

규칙:
1. 에이전트는 ROOT 의 어떤 파일도 열지 않는다. 실행 파일·파이썬·정제기는 `agent\bin\<ver>\` 사본, cwd 는 `agent\`, 설정은 `agent_config.json`·`context_cache.json`·`keys\subkeys.json`(§1.6.2).
2. 번들에 쓰는 주체는 전경 프로세스(화면 서버·bat·CLI)뿐이며, 쓸 때마다 `BundleLock` 을 쥔다.
3. 전경 프로세스는 쓰기가 끝나면 번들 파일 핸들을 닫는다(열어 둔 채 대기 금지). 화면 서버의 cwd 는 ROOT 이므로 [이동 준비]가 화면 서버를 내린다(§1.11). bat 은 `pushd "%TEMP%"` 로 cwd 를 ROOT 밖에 둔다.

```python
class BundleLock:
    """data\.bundle.lock 의 0번 바이트를 msvcrt.locking(LK_NBLCK, 1) 으로 잠근다.
    OS 잠금이라 잡은 프로세스가 죽으면 자동으로 풀린다(실측: 잡은 자식을 kill 하자 즉시 획득 — 낡은 잠금 파일 문제 없음).
    대기: 0.25s 간격으로 timeout_s(기본 30)까지. 시간 초과 → BundleBusy(누가: 잠금 파일 1번 바이트 이후에 적힌 pid·purpose·시각).
    표시용 내용: {"pid":…, "purpose":"collect-init|export|fg-write|collect-finish|team_build|move|merge|redact", "at":"…"}
    (0번 바이트는 잠금 전용으로 비워 두고 내용은 그 뒤에 덮어쓴다 — 잠근 바이트에 쓰면 다른 프로세스의 읽기가 막힌다)."""
```

읽기(분석·화면)는 잠금 없이 한다. 세그먼트는 불변이고 manifest 는 원자 교체이므로, manifest 읽기에서 `PermissionError` 가 나면 0.1s × 5회 재시도만 한다.

### 1.10 용량

- 번들에는 정제된 레코드만 → 사람 1명 PC 3대 1년 ≈ 수십 MB 수준(설계 추정). 브라우저 프로필은 번들 밖이므로 이동 크기에 들어가지 않는다.
- `bundle.warn_size_mb`(기본 300) 초과 시 화면에 상위 소비처(kind 별·PC 별 MB)를 보여 준다. 자동 삭제는 하지 않는다.
- `derived\` 는 언제든 재생성되므로 [이동 준비] 크기 계산에서 따로 표시한다(지우지는 않는다).
- [이동 준비]·화면 기동 때 ROOT 아래에 `User Data`·`*Profile*`·`Local State`·`Cookies` 같은 브라우저 프로필 흔적이 있으면 경고한다(번들 밖이어야 한다는 계약 위반 탐지).

### 1.11 이동 준비 버튼

목표: 사용자는 [이동 준비] → "[완료]" 확인 → 폴더 드래그만 한다(zip·수동 종료 요구 금지).

1. **마지막 내보내기**: `collect_here()` 를 ④(전경 수집기) 없이 돈다(에이전트 kind + 탐침만).
2. **검증**: 이 PC 의 manifest 를 다시 읽어 모든 세그먼트 sha 를 재계산(검증 캐시에 있는 것은 생략). 불일치 → 격리 + 표시(이동은 막지 않는다).
3. **팀 서버 확인**: 이 ROOT 의 `python.exe` 로 팀 서버가 돌고 있으면(§3.3 `server.json` 의 pid 가 살아 있고 그 실행 경로가 ROOT 아래) 이동을 멈추고 "이 폴더의 파이썬으로 팀 서버가 실행 중입니다 — 폴더를 옮기면 팀 서버가 멈춥니다. 팀 서버는 옮기지 않는 별도 설치 폴더에서 운영하세요." 를 보인다(조용히 죽이지 않는다). [그래도 진행]을 누를 때만 다음 단계.
4. **이동 시험 도우미 기동**: 파이썬은 `python\python.exe` 가 ROOT 안에 있어 실행 중에는 폴더 이름을 바꿀 수 없다. 그래서 PS 도우미 `Prepare-Move.ps1` 을 `%TEMP%\lm27_move_<rand>.ps1` 로 복사해 **보이는 콘솔 창**으로 기동하고(`-Root <ROOT> -WaitPid <화면 서버 pid> -Gen <manifest gen>`), 화면에는 "대시보드를 닫고 결과 창을 엽니다"를 띄운 뒤 화면 서버가 스스로 종료한다.
5. 도우미(PS 5.1)가 하는 일:
   - `Set-Location $env:TEMP; [Environment]::CurrentDirectory = $env:TEMP`, 경로는 `[IO.Path]::GetFullPath()` 로 정규화(`…\.` 꼬리 제거 — LM24 빈 껍데기 폴더 사고 방어).
   - `-WaitPid` 종료를 최대 `move.stop_wait_s`(15s) 기다린다.
   - **ExecutablePath 또는 CommandLine 이 ROOT 아래**인 `python.exe`·`pythonw.exe`·`powershell.exe`·`cmd.exe` 만 종료(자기 자신·부모 제외). 에이전트는 경로가 ROOT 밖이므로 대상이 아니다.
   - 이름 바꾸기 시험: `ROOT` → `ROOT.__mvtest_<rand>` → 원래 이름. 각각 최대 `move.rename_retries`(4)회, 0.5·1·2·4s 간격. 되돌리기는 5회까지 재시도하고, 그래도 실패하면 바뀐 이름을 화면에 크게 알린다(폴더를 잃지 않게).
   - 실패하면 원인 후보: Restart Manager 로 `data\.bundle.lock`·`config\config.json`·`python\python311.dll` 을 쥔 프로세스(pid·이름), ROOT 아래를 실행 경로로 가진 프로세스 목록, 그 밖은 "탐색기 창이나 명령 창이 이 폴더를 열어 두고 있을 수 있습니다 — 그 창을 닫고 다시 실행". 탐색기·사용자가 연 Office 창은 **절대 종료하지 않는다.**
   - 성공하면 `data\pcs\<pc_id>\move_ready.json` 을 쓰고 `[완료] 이 폴더를 다음 PC 로 옮겨도 됩니다 (크기 N MB)` 출력, 60초 뒤 창 자동 닫힘. 성공 경로에서 `[!]` 표기 금지(LM24 문구 규칙).
6. bat 진입(`LoadMonitor27-이동준비.bat`)도 같은 도우미를 쓴다. bat 은 `pushd "%TEMP%"` 후 `start "" powershell … -File "%TEMP%\lm27_move_<rand>.ps1"` 로 띄우고 즉시 `exit` 한다(cmd.exe 의 cwd 가 ROOT 를 잡지 않게).

`move_ready.json`(그 PC 폴더 안 — 다른 PC 폴더에 쓰지 않는다):

```json
{"schema": "lm27.moveready/1", "at": "2026-10-05T09:03:40Z", "pc_id": "pc_9a1b…", "label_auto": "PC1",
 "manifest_gen": 17, "bundle_mb": 41.2, "derived_mb": 12.8, "sha_ok": true,
 "segments": [["seg/pc_session/000012-7c3f1a2b-20261004T2300Z-20261005T0859Z-5e0c11aa.jsonl.gz", "5e0c11aa…", 18234]],
 "other_pcs_seen": {"pc_c3…": 9}}
```

`segments` 는 이 PC 폴더 manifest 의 전 목록(이름·sha·크기), `other_pcs_seen` 은 그 시점 번들 안 다른 PC 별 세그먼트 수다. 도착 PC 가 이것으로 누락을 이름별로 찾는다(§1.12).

### 1.12 도착 PC 첫 실행

- 화면 기동 시 `identify_pc()` → pcs 에 없는 pc_id 면 "새 PC 로 인식했습니다(PC2)" 배너 후 `collect_here()` 자동 1회(사용자 질문 없음, `--auto` 와 같음).
- **도착 점검**(결정 메모 10.4 '도착 후 누락 세그먼트를 이름별로'): 모든 `pcs\*\move_ready.json` 을 읽어 각 목록의 파일이 실제로 있고 크기가 같은지 본다(sha 는 백그라운드). 결과:
  - 모두 있음: "PC1 에서 10-05 09:03 에 이동 준비됨 — 세그먼트 214개 모두 도착" (한 줄).
  - 누락·크기 다름: 표로 `PC 라벨 · kind · 세그먼트 이름 · 기대 크기 · 상태(없음/크기 다름/sha 다름)` 를 보이고 "이 파일들이 복사되지 않았습니다. 원래 PC(또는 USB)에서 같은 폴더를 다시 복사하면 자동으로 채워집니다(이미 있는 파일은 건드리지 않음)". 자동 삭제·자동 재구성 없음. 로더는 누락분을 빼고 읽으며 `load_report` 에 남긴다.
  - move_ready.json 보다 manifest 가 더 새것이면(그 뒤에 그 PC 에서 또 수집) 점검 기준은 manifest 다.
- 번들 안에 LM24 식 `data\추가PC\`·`copilot_profile` 같은 옛 구조가 있으면 읽지 않고 경고만 한다.

### 1.13 사본 분기 번들 합치기

사용자가 폴더를 이동이 아니라 복사해 두 곳에서 쓰면 번들이 갈라진다.

- `lm27 bundle merge <다른 data 폴더>`(화면: [다른 번들 가져오기]): 두 `bundle.json` 의 `person_key` 가 다르면 거부("다른 사람의 번들입니다"). 같으면:
  1. `BundleLock("merge")` 을 쥔다. 원본 쪽은 읽기만 한다.
  2. 상대 `pcs\<pc_id>\` 마다: 상대 manifest 의 세그먼트 중 **이쪽에 같은 sha 가 없고, 양쪽 어느 무덤표에도 없는 것만** 복사(이름에 sha·install 이 있어 충돌 없음). 상대에만 있는 pc_id 폴더는 통째로 복사(pc.json·manifest 포함). 둘 다 있는 pc_id 는 `adopt_orphans()` 로 이쪽 manifest 에 편입하고, 커서는 install·stream 별로 `(file, offset)` 이 더 앞선 쪽, `observed_from` 은 더 이른 값, 무덤표·gaps 는 합집합, pc.json 의 `installs`·`visits`·`capabilities.*.history` 는 합집합(날짜·상태 중복 제거).
  3. `pc_aliases.json` 은 결정 합집합(at·pc_id 중복 제거). `keys\` 는 PRIVACY `load_keyring()` 병합 규칙. `outbox\` 는 sha 기준 합집합(같은 sha 는 하나).
  4. 끝나면 `derived\` 를 다시 만든다. 결과는 몇 번을 다시 해도 같다(멱등 — sha 집합 합집합).

### 1.14 소급 가림 재작성(PRIVACY §12.5 의 번들 쪽 절차)

PRIVACY §12.5 는 "사용자가 사적으로 지정한 대화·메시지를 디스크에서도 지운다"를 세그먼트 불변 원칙의 유일한 예외로 둔다. 번들 형식에서는 이렇게 한다.

- 실행 주체: **그 PC 의 전경 프로세스**(에이전트가 아니다 — 에이전트는 번들을 만지지 않는다). [수집]의 `collect-init` 단계와 화면의 [소급 가림 적용]. 대상은 **자기 pc_id 폴더의 세그먼트뿐**이다. 다른 PC 세그먼트는 그 PC 에서 같은 절차가 돌 때 지워지며, 그 전까지는 로더의 읽기 오버레이가 가린다.
- 절차(세그먼트 하나마다, `BundleLock("redact")`):
  1. 세그먼트를 풀어 `local_only\redact_overlay.json` 에 걸리는 행의 텍스트 열만 비운다(행 수·`id`·시간 열 불변 — PRIVACY 규칙).
  2. 같은 `seq` 로 새 세그먼트를 쓴다(이름의 sha8 이 바뀐다). 머리말에 `"redacted_from": "<옛 sha>"`.
  3. manifest 에서 그 seq 항목을 새 정보로 바꾸고 `tombstones` 에 `{seq, kind, old_sha256, new_sha256, reason:"redact", at}` 추가 → 저장.
  4. 옛 파일 삭제. 무덤표는 `quarantine\tombstones.json` 에도 사본을 둔다(manifest 재구성용).
- 사본 번들 병합(§1.13)과 로더(§1.15)는 무덤표의 옛 sha 를 절대 들이지 않는다. 감사: PRIVACY `rewrite_redact` 이벤트에 바꾼 행 수.

### 1.15 단일 로더(번들 읽기)

```python
# lm27/bundle/loader.py — data\pcs 를 읽는 유일한 모듈(lint 관문)
def iter_records(root, kind, d0=None, d1=None, *, pcs=None, dedupe=True) -> Iterator[dict]:
    """모든 pc_id 의 manifest 를 열거 → 기간과 겹치는 세그먼트만(t0·t1·로컬 달) → 무덤표 제외 → sha 검증(캐시) → 레코드 산출.
    - 각 레코드에 _pc(pc_id)·_inst(install_id)·_lpc(논리 PC) 를 붙인다.
    - dedupe: (kind, id) 가 같으면 하나만(먼저 쓰인 세그먼트 = created 순). 출처 간 msg_key 병합은 하지 않는다(COLLECTION §7 소관).
    - PRIVACY 읽기 오버레이(redact_overlay)와 resanitize_row 를 적용한 사본만 위로 넘긴다.
    - 손상 세그먼트: 격리 목록에 넣고 건너뛴다. 건너뛴 수·레코드 추정치는 load_report() 로 노출(조용한 손실 금지)."""

def bundle_status(root) -> dict:
    """PC 별 {label_auto, kind, first/last_seen, kind 별 세그먼트·레코드 수, gaps, 격리, observed_from, agent_status,
    탐침 verdict, move_ready 대비 누락} — 화면·보고서·팀 묶음 quality 의 원천"""
```

검증 캐시: `derived\verify_cache.json` = `{relpath: {"size", "mtime_ns", "sha256", "ok"}}`. size·mtime 이 같으면 재해시 생략. 캐시는 파생물이라 이동 후 다시 만들어져도 된다.

---

## 2. 팀 업로드 묶음 `lm27_team_bundle.json`

### 2.1 원칙

| 번호 | 원칙 | 구현 |
|---|---|---|
| TP1 | **집계·라벨만**. 신호 원문·메일 제목·동료 표시명·호스트명·사용자명·경로·이메일 주소·pc_id·kid·who_key·로컬 키 금지(PRIVACY §14.1·§14.3) | 허용 목록 빌더(§2.4) + 빌드 시 금지 패턴 검사 + PRIVACY `check_team_payload` + 서버 재검사 + 카나리아 관문 |
| TP2 | 사람·동료는 가명 키 | `person_key`(난수), `peer_key`(팀 pepper HMAC)(§2.3.3) |
| TP3 | **미리보기 = 실전송** 바이트 동일 | 정규 바이트 파일 1개를 미리보기와 전송이 함께 쓴다(§2.7) |
| TP4 | 개인 = 팀 재합산 | 일자 정수 분 표를 싣고 서버가 같은 산식으로 다시 합친다(§4) |
| TP5 | 버전 명시 | `schema_version`(MAJOR.MINOR) + 생성기 판(§2.6) |
| TP6 | 보내기 실패는 대기·재시도, 조용히 사라지지 않는다 | 대기열 상태 기계(§2.8) |
| TP7 | 사람이 항목별로 가릴 수 있다 | 미리보기의 가림(§2.5) — 시간 수치는 가리지 않는다(개인=팀 보존) |

### 2.2 이름

- 논리 이름: `lm27_team_bundle.json`.
- 대기열 파일: `data\outbox\team\pending\lm27_team_bundle_<period_key>_<sha12>.json` + 옆에 `….json.meta.json`.
- 오프라인 내보내기 파일: `lm27_team_bundle_<person_key>_<period_key>_<sha12>.json`.
- `period_key` = `<from>_<to>` (예: `2026-07-01_2026-09-30`).

### 2.3 스키마 v1.0

#### 2.3.1 전체 모양(예시 — 값은 합성, 배열은 일부만 보임)

```json
{
  "schema": "lm27.team_bundle",
  "schema_version": "1.0",
  "generator": {"app": "LM27", "app_version": "0.1.0", "core_version": "timecore/1",
                "rules_ver": "2026.10.0", "rules_hash": "4a684ebdcf99f956", "registry_version": 7,
                "calendar_version": "kr-2026.3", "catalog_version": "ag-3"},
  "built_at": "2026-08-03T09:12:00+09:00",
  "person": {"person_key": "p_7fa3c2d19e01", "member_id": "M003", "self_label": "팀원A",
             "self_peer_key": "c_1a2b3c4d5e6f", "pepper_id": "9f2c01ab", "function": "회로",
             "work_tz_offset_min": 540, "peer_scope": "team"},
  "period": {"from": "2026-07-01", "to": "2026-07-31", "analyzed_until": "2026-07-31T23:59:59+09:00",
             "months": ["2026-07"]},
  "summary": {"std_day_min": 480, "months": [
    {"month": "2026-07", "workdays": 22, "covered_workdays": 22, "absence_days": 1.0, "avail_days": 21.0,
     "envelope_min": 11520, "by_tag": {"regular": 10200, "extended": 900, "night": 120, "holiday": 300},
     "attributed_min": 10980, "unattributed_min": 540,
     "mm": 1.0909090909090908, "load_pct": 114.28571428571428}]},
  "envelope_daily": {"cols": ["date", "regular", "extended", "night", "holiday"],
                     "rows": [["2026-07-01", 480, 30, 0, 0]]},
  "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"],
                  "rows": [["2026-07-03", "u_3e9a01c2d4", "regular", 240]]},
  "projects": [{"project_id": "P-0007", "domain": "DEV"}],
  "proposals": [{"proposal_id": "pr_1", "kind": "project", "label": "과제A 후속", "domain_guess": "DEV"}],
  "roles": [{"role_id": "r_5c0d11", "project_id": "P-0007", "proposal_id": null, "field": "회로", "function": "설계"}],
  "units": [{"unit_id": "u_3e9a01c2d4", "role_id": "r_5c0d11", "title": "전원부 검증", "title_mode": "label",
             "activity_type": "개발", "ax_link": false,
             "start": {"kind": "S1i", "at": "2026-07-03T10:12:00+09:00", "precision": "exact"},
             "end": {"kind": "E1o", "at": "2026-07-09T16:40:00+09:00", "precision": "exact"},
             "grade": "B", "status": "closed", "first_evidence": "2026-07-03", "last_evidence": "2026-07-09",
             "lead_time_h": 150.5, "effort_min": 1260,
             "gantt_spans": [["2026-07-03", "2026-07-09", "lead"], ["2026-07-03", "2026-07-03", "active"],
                             ["2026-07-08", "2026-07-09", "active"]],
             "peers": ["c_9d8e7f6a5b4c"], "apps": ["excel", "spice"], "apps_unknown_min": 35,
             "evidence_n": {"mail": 3, "teams": 2, "file": 11, "app": 40, "meeting": 1}}],
  "workflows": [{"role_id": "r_5c0d11", "units": ["u_3e9a01c2d4"],
                 "steps": [{"no": 1, "type": "의뢰수신", "label": "요청 접수", "n": 5, "median_min": 20,
                            "agent_grade": "상", "subagent": "적합", "why": ["digital_io", "repeat_weekly"]}],
                 "edges": [[1, 2, 5]]}],
  "agentic": {"catalog_version": "ag-3",
              "matches": [{"agent_id": "AG003", "role_id": "r_5c0d11", "step_type": "문서작성", "grade": "상",
                           "units": ["u_3e9a01c2d4"]}],
              "needs": [{"need_id": "n_01", "step_type": "자료조사", "label": "사양 비교표 자동 작성", "grade": "상",
                         "freq_per_month": 4.0, "units": ["u_3e9a01c2d4"]}],
              "subagents": [{"role_id": "r_5c0d11", "fit": "조건부",
                             "chain": [{"step_no": 2, "proposal": "자료 수집 서브에이전트"}]}]},
  "peers": [{"peer_key": "c_9d8e7f6a5b4c", "scope": "team", "units": 3, "shared_effort_min": 420}],
  "peers_external": {"customer": 4, "partner": 2, "other": 1},
  "privacy_counts": {"phone": 12, "rrn": 0, "account": 1, "money": 7, "person": 412, "ad": 143, "class_private": 9},
  "catalog_proposals": [],
  "quality": {
    "grade": "reliable", "reasons": [],
    "pcs": [{"ord": 1, "label_auto": "PC1", "kind": "desktop", "agent_impl": "py", "observed_days": 22,
             "event_days": 23, "stuck_days": 0,
             "probe": {"mail.com": "가능", "mail.index": "가능", "teams.uia": "가능", "mail.owa": "불가(확정)"}}],
    "coverage": [{"axis": "mail_out", "days": {"ok": 20, "zero_ok": 2, "partial": 0, "out_of_horizon": 0,
                                               "blocked": 0, "transport_fail": 0, "not_attempted": 0},
                  "srcs": ["mail.com", "mail.index"], "exact_ratio": 0.97}],
    "days": {"weekdays": 22, "no_evidence_weekdays": 1, "long_days_16h": 0, "anomaly_days": 0},
    "confirm_queue": {"open": 3, "resolved": 11},
    "estimated_min_ratio": 0.08,
    "team_text_rejected": 0,
    "copilot": {"used": true, "items": 180, "failed_items": 2}},
  "integrity": {"envelope_min": 11520, "alloc_min": 10980, "unattributed_min": 540,
                "rows_env": 23, "rows_alloc": 96, "units": 14}
}
```

예시 숫자 검산(원형 실측): 2026-07 평일 22일(제헌절 7/17 공휴일) → `mm` = 11520 ÷ (480 × 22) = 1.0909…, 가용 21일 → `load_pct` = 11520 ÷ (480 × 21) × 100 = 114.2857….

#### 2.3.2 필드 규칙(빌더·서버 공용 검증기 `lm27/team/schema.py: validate_team_bundle(obj, registry, side) -> list[Err]`)

`Err(path, code, msg, blocking)`. `blocking=False` 는 경고(저장은 하되 `/api/members` 의 `flags` 에 표시).

| 경로 | 형 | 제약 |
|---|---|---|
| (최상위) | obj | 아래 키만. 모르는 키 → MINOR 가 서버보다 높으면 무시(경고 `unknown_key`), 같거나 낮으면 422 `schema` |
| `schema` | str | `== "lm27.team_bundle"` |
| `schema_version` | str | `^\d+\.\d+$`, MAJOR 는 서버 허용 목록(§2.6) |
| `generator.*` | str/int | 각 ≤ 40자, 제어문자 없음. `rules_ver` 는 PRIVACY 형식 `^\d{4}\.\d{1,2}\.\d{1,3}$`, `rules_hash` 16hex |
| `built_at` | str | ISO8601 + offset |
| `person.person_key` | str | `^p_[0-9a-f]{12}$` |
| `person.member_id` | str/null | `REG_ID` 이고 `M` 으로 시작. 레지스트리 `members` 에 없으면 경고 `unknown_member`(무시하고 계속) |
| `person.self_label` | str | 0~20자, §2.4 `team_text` 통과. 비면 서버가 `팀원-<KEY4>` 표시 |
| `person.self_peer_key` | str/null | `^c_[0-9a-f]{12}$` |
| `person.pepper_id` | str/null | `^[0-9a-f]{8}$`. 서버 pepper 의 id 와 다르면 그 묶음의 동료 키를 연결에 쓰지 않는다(경고 `pepper_mismatch`) |
| `person.function` | str | 레지스트리 `vocab.fields` 값 또는 "" |
| `person.peer_scope` | str | `team`(팀 pepper 로 만든 키) / `personal`(pepper 없음 — 서버가 동료 연결에 쓰지 않음) |
| `period.from/to` | date | from ≤ to, 기간 ≤ 400일, `months` = from~to 사이 달 전부(오름차순) |
| `period.analyzed_until` | datetime | from ≤ 이 값의 날짜 ≤ to+1일 |
| `summary.std_day_min` | int | 레지스트리 `calendar.std_day_min`(기본 480)과 같음(다르면 경고 `calendar_mismatch`) |
| `summary.months[]` | obj | `months` 와 1:1. `workdays` = 서버 달력값과 같아야 함(다르면 422 아님 — 경고 `calendar_mismatch`) |
| `summary.months[]` 자체 일관성 | — | `envelope_min` = 그 달 envelope 행 합, `by_tag` = 꼬리표별 합, `attributed_min` = 그 달 alloc 합, `unattributed_min` = 차, `mm` = envelope_min ÷ (std_day_min × workdays) (\|Δ\| ≤ 1e-9), `avail_days` = covered_workdays − absence_days, `load_pct` = envelope_min ÷ (std_day_min × avail_days) × 100(avail_days ≤ 0 이면 null, \|Δ\| ≤ 1e-6). 하나라도 어긋나면 422 `integrity` |
| `envelope_daily.rows[]` | [date, int×4] | 날짜 오름차순·중복 없음·기간 안. 각 값 0~1440, 합 ≤ 1440 |
| `alloc_daily.rows[]` | [date, unit_id, tag, int] | tag ∈ 4종, min 1~1440, (date, unit_id, tag) 중복 없음, unit_id 는 `units` 에 있음 |
| 일자 무결성 | — | 모든 (date, tag): Σ_unit alloc ≤ envelope(그 날짜 행이 없으면 envelope = 0). 어기면 422 `integrity`(서버가 조용히 재스케일하지 않는다) |
| `projects[].project_id` | str | `^P-\d{4}$`(PRIVACY `PROJECT_ID`). 레지스트리에 없으면 경고 `unknown_project`(영역은 묶음의 `domain` 사용) |
| `projects[].domain` | str | `DEV`·`MP`·`EXT`·`COM`·`AX`·`UNC` (개발 프로젝트·양산 프로젝트·외부 업무지원·공통 업무·AX 프로젝트·미분류) |
| `proposals[]` | obj | `proposal_id` `^pr_\d{1,4}$`, `kind` ∈ project·role, `label` ≤ 40자 `team_text` 통과, `domain_guess` ∈ 6종 |
| `roles[]` | obj | `role_id` `^r_[0-9a-f]{6}$` 이고 R-8 식으로 다시 계산한 값과 같음, `project_id`·`proposal_id` 중 최대 하나(둘 다 null 이면 미분류 역할), field·function 은 레지스트리 어휘 |
| `units[]` | obj | `unit_id` `^u_[0-9a-f]{10}$`, `title` ≤ 40자 `team_text`(또는 generic 라벨), `title_mode` ∈ label·generic, `activity_type` ∈ 레지스트리 `vocab.activity_types`, `start.kind` ∈ {S1i, S1o, S2, M}, `end.kind` ∈ {E1o, E1i, E2, E3c, M, null}(근거 종류 — 시간 모델 명세 소관, 늘리면 MINOR), `precision` ∈ exact·minute·date·none, `grade` ∈ A~E, `status` ∈ closed·open·estimated, `effort_min` = 그 unit 의 alloc 합(정확히), `gantt_spans` 각 [from, to, kind] from ≤ to, kind ∈ lead·active, lead 는 정확히 1개, `apps` 는 카탈로그 앱 ID(≤ 20개, 각 `^[a-z0-9_.-]{1,24}$`), `apps_unknown_min` ≥ 0 정수 |
| `units[].gantt_spans`(active) | — | 서버가 alloc 에서 같은 함수(`active_spans(days, gap=2)`, §4.6)로 다시 만든 것과 같아야 한다. 다르면 경고 `gantt_mismatch` 후 서버 값 사용 |
| `workflows[]` | obj | `role_id` 존재, `units` ⊆ 그 역할의 units, `steps[].type` ∈ 레지스트리 `vocab.step_types`, `label` ≤ 30자 `team_text`, `subagent` ∈ 적합·조건부·부적합, `why[]` ∈ 고정 어휘(digital_io·repeat_weekly·repeat_monthly·structured_input·low_accountability·verifiable), `edges` 의 번호는 steps 안 |
| `agentic.*` | obj | `agent_id` 는 `REG_ID` 이고 `AG` 로 시작하며 카탈로그에 있음, `grade` ∈ 상·중·하, `needs[].label` ≤ 40자 `team_text`, `chain[].proposal` ≤ 40자 `team_text`, `units` 참조 존재 |
| `peers[]` | obj | `peer_key` 형식, `scope` ∈ team·personal, `units`·`shared_effort_min` ≥ 0 정수 |
| `peers_external` | obj | 키 ∈ customer·partner·other, 값 ≥ 0 정수 |
| `privacy_counts` | obj | PRIVACY `COUNTS` — 키는 §15.3 범주·행 사유 코드, 값은 기간 합계 정수(PRIVACY Q18 요청) |
| `catalog_proposals[]` | obj | 기본 빈 목록. `team.share_unknown_apps=true` 일 때만 미상 프로그램 라벨링 제안(COLLECT_PC §6.4): `exe` `^[a-z0-9_.\-]{1,64}\.exe$` 이고 `check_team_label` 통과(사내 도구 이름 = 코드네임일 수 있어 사전 검사), `company`·`product` 는 `LABEL40`, `n_days`·`minutes` 정수. 미리보기에서 항목별 [빼기] |
| `quality.*` | obj | 숫자는 유한, 비율 0~1, 문자열은 고정 어휘 또는 ≤ 20자. `grade` ∈ reliable·caution·unreliable·"" |
| `integrity.*` | int | 본문에서 다시 센 값과 정확히 같음 |
| 문자열 전체 | — | 제어문자(Cc·Cf) 없음. 서버도 PRIVACY `check_team_payload`(§14.3 금지 값·§14.5 값 클래스)를 다시 돌린다 → 걸리면 422 `forbidden_content`(값은 응답에 싣지 않고 경로·코드만) |

크기 상한: 클라이언트 `team.max_bundle_mb`(8MB) — 빌드 때 넘으면 `blockers` 에 "기간을 나눠 다시 만드세요". 서버 상한 `team_server.max_body_mb`(16MB). JSON 중첩 깊이 ≤ 32.

#### 2.3.3 가명 키

결정 메모 10.4 의 2층 구조를 PRIVACY(LM27) §9.1 대로 구현한다.

| 층 | 키 | 어디에 | 무엇을 만드나 | 팀 묶음 |
|---|---|---|---|---|
| L1 개인 | PRIVACY 키링 | `data\keys\privacy_keyring.json`(폴더와 이동) + 에이전트 하위 키 | 행에 저장하는 로컬 키(`who_key` `w`+16hex, msg·doc·… 키, `unit_id`) | `who_key`·로컬 키 **금지**(PRIVACY §14.3). `unit_id` 만 사람 안 식별자로 허용 |
| L2 팀 | 팀 pepper(32B 난수, 64hex) | 팀 서버가 최초 기동 때 생성 → `/api/registry` 의 `pepper` 로 배포 → 클라이언트 레지스트리 캐시 `data\team\registry.json` | `peer_key`, `self_peer_key` | 허용 |
| 사람 식별 | `person_key`(난수) | `bundle.json` | 팀 묶음의 번들 주인 키 | 허용(신원에서 유도하지 않아 사전 공격 불가) |

- `peer_key` 는 PRIVACY §9.7 `peer_key(pepper_hex, smtp, internal_domains, kr)` 를 그대로 쓴다: 사내 도메인 주소 `a = lower(strip(주소))` 에 대해 `"c_" + HMAC-SHA256(bytes.fromhex(pepper), a.encode("utf-8"))[:12]`(scope `team`). pepper 가 아직 없으면 `"c_" + keyed(kr, "peer", a, 12)`(scope `personal` — 서버는 동료 연결에 쓰지 않고 그 사람 안의 동료 수·공유 투입 표시에만 쓴다).
- 주소는 행에 없으므로 **빌드 때 로컬 사람 사전**(`data\local_only\person_dir.json`, PRIVACY §9.6)으로 `who_key` → 주소 → `peer_key` 를 계산한다. 사내 도메인 = 레지스트리 `internal_domains` ∪ `privacy.internal_domains`. 외부 주소는 키 없이 `peers_external` 의 도메인 계급(고객사 사전·협력사 사전·그 밖) 단위 수만 남긴다. 주소를 모르는(이름만 아는) 사람은 동료 목록에서 빠지고 `quality.reasons` 에 `peer_unresolved:<수>`.
- `self_peer_key`: 사람 사전의 `self: true` 항목 주소로 같은 식. 모르면 null. 서버는 이 값이 같은 두 person_key 를 같은 사람으로 자동 연결하고(§3.11, 같은 `pepper_id` 일 때만), 다른 사람 묶음의 `peers` 에서 이 키를 팀원으로 인식한다.
- `pepper_id = sha256(bytes.fromhex(pepper)).hexdigest()[:8]`(pepper 없으면 null). 서버가 바뀌어(새 store) pepper 가 달라지면 다음 빌드부터 새 키를 쓰고, 이미 보낸 묶음은 그대로 둔다 — 서버는 `pepper_id` 가 자기 것과 다른 묶음의 동료 키를 연결에 쓰지 않는다.
- `data\team\registry.json`(pepper 포함)은 `keys\` 와 같은 반출 금지 대상이다: 팀 묶음·오프라인 내보내기·코파일럿·패키지에 들어가지 않는다(lint: 그 경로를 읽는 모듈은 `lm27/team/build.py`·`client.py`·`lm27/privacy/` 뿐).

### 2.4 허용 목록 빌더와 금지 내용

빌더는 분석 결과 객체를 **그대로 직렬화하지 않는다.** §2.3.2 표의 필드를 하나씩 골라 새 dict 를 만든다(통째 전달 금지 — lint 관문). 모든 자유 문자열은 아래 함수를 거친다.

```python
from lm27.privacy import forbidden_codes, check_team_label     # PRIVACY §14.3·§14.4 — 금지 값 표를 이 문서에서 다시 정의하지 않는다

BYTES_GUARD = [                                                 # 정규 바이트 전체에 거는 마지막 그물(문자열 경계와 무관한 것만)
    re.compile(rb"[^\s@\"]{1,64}@[^\s@\"]{1,255}\.[A-Za-z]{2,}"),   # 이메일
    re.compile(rb"(?<![0-9a-z_])w[0-9a-f]{16}(?![0-9a-f])"),           # who_key
    re.compile(rb"pcx?_[0-9a-f]{16}"),                                 # pc_id
    re.compile(rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),   # GUID
    re.compile(rb"(?i)https?://"),
]

def team_text(s, maxlen, field, ctx) -> str | None:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))   # 제어·서식 문자(zero-width·BOM) 제거
    s = " ".join(s.split())[:maxlen]
    if not s:
        return ""
    if check_team_label(s, ctx.gctx, maxlen) or forbidden_codes(s, ctx.gctx) or ctx.local_dict_hit(s):
        ctx.audit["team_text_rejected"] += 1; ctx.audit_fields[field] += 1
        return None                                   # 호출자가 대체 라벨(예: "<분야>·<기능> 단위업무 #3")을 넣는다
    return s
```

- `check_team_label`: PRIVACY §14.4(정제기가 더 바꿀 것이 있으면 불합격, 허용 토큰은 `[금액]`·`[비율]`·`[과제:ID]`·`[고객사:ID]`·`[협력사:ID]`·`[회사]`·`[사람]` 뿐, 카나리아).
- `ctx.local_dict_hit`: 이 번들 모든 PC 의 `host_display`, Windows 사용자명, 사람 사전의 표시명(로컬 전용), `label_user` 에 대한 부분 문자열 일치(대소문자 무시). 사전 항목은 한글 2자 이상·ASCII 4자 이상만 쓴다(짧은 항목의 오탐 방지).
- `forbidden_codes`: PRIVACY §14.3 금지 값(who_key·로컬 키·kid·pc_id·GUID·이메일/`@`·경로/`\`·URL·IPv4·9자리 이상 숫자·카나리아) 중 걸린 코드 목록.
- `person.self_label` 은 본인이 일부러 입력한 값이므로 `local_dict_hit` 는 적용하지 않고 `check_team_label`·`forbidden_codes` 만 적용한다(미결 2).
- 마지막 3중 검사(빌드 실패 = rc 1, 필드 경로와 유형만 표시 — 값은 화면에도 찍지 않는다):
  1. 객체를 순회해 **자유 문자열 필드**(`units[].title`·`workflows[].steps[].label`·`proposals[].label`·`agentic.needs[].label`·`agentic.subagents[].chain[].proposal`·`person.self_label`)마다 위 검사 재실행.
  2. PRIVACY `check_team_payload(obj, gctx, spec=TEAM_SPEC_V1)` — 모든 문자열 값·키 이름에 §14.3 금지 값, 필드별 §14.5 값 클래스. `TEAM_SPEC_V1` 은 §2.3.2 표와 PRIVACY §14.5 표를 한 모듈 상수로 둔 것이다(두 명세가 한 표를 공유).
  3. 정규 바이트 전체에 `BYTES_GUARD` 만 재검사. (`\`·9자리 숫자 같은 문자열 단위 규칙과 사전 검사는 바이트 전체에 걸지 않는다 — JSON 이스케이프 `\"`·16진 ID·sha 안의 우연한 글자열이 오탐을 만들기 때문이다. ID·날짜·열거형 필드는 형식 정규식으로 이미 막혀 있어 자유 문자열이 들어갈 수 없다.)
- 통과하면 PRIVACY 감사 이벤트 `gate_team` 에 `out_sha256`(전송 바이트 sha)·필드별 거절 수를 남긴다.

### 2.5 항목별 가림(미리보기에서)과 제목 모드

결정 메모 10.4: 단위업무 제목은 간트 드릴다운을 위해 기본 포함하되, 업로드 전 미리보기에서 **항목별 제외**가 가능하고 설정으로 제목 제외 모드를 둔다.

- `team.unit_title_mode`: `label`(기본 — 분류 단계가 만든 짧은 제목) / `generic`(모든 제목 대신 `<분야>·<기능> 단위업무 #n`, n = 그 역할 안 시작 시각 순번).
- 미리보기의 단위업무 표에서 행마다 [제목 가림]·[세부 가림], 니즈·매칭 행마다 [빼기] 를 누를 수 있다. 선택은 `data\team\overrides.json` 에 남고 다음 빌드에도 적용된다.

```json
{"schema": "lm27.team_overrides/1",
 "units": {"u_3e9a01c2d4": "title", "u_0b1c2d3e4f": "detail"},
 "needs": {"n_02": "drop"}, "matches": {}, "subagents": {}}
```

| 가림 | 묶음에서 바뀌는 것 | 바뀌지 않는 것 |
|---|---|---|
| `title` | `title` → generic 라벨, `title_mode="generic"` | 나머지 전부 |
| `detail` | `title` generic + `peers: []` + `apps: []` + `apps_unknown_min: 0` + `evidence_n: {}` + 그 역할 workflows 의 단계 `label` 을 단계 유형 이름으로 | `unit_id`·`role_id`·start/end 종류·등급·리드타임·`gantt_spans`·`effort_min`·alloc |
| `drop`(니즈·매칭·서브에이전트) | 그 항목 삭제 | 시간 수치 |

- **시간 수치(envelope·alloc·단위업무 존재)는 가릴 수 없다** — 빼면 개인=팀 재합산(I2·I3)이 깨진다. 단위업무를 통째로 숨기고 싶으면 `detail` 가림을 쓴다(그 시간은 역할·과제 투입으로 남는다). 이 제약을 미리보기 화면에 한 줄로 적는다.
- 가림을 바꾸면 다시 빌드한다 → 새 바이트·새 sha → 같은 기간의 이전 미전송 항목은 `dropped(superseded)`. 미리보기=실전송 보장은 그대로다.

### 2.6 버전 규칙

- `schema_version` = `MAJOR.MINOR`. MINOR 올림 = 필드 추가(옛 서버는 모르는 필드를 무시해도 뜻이 같음). MAJOR 올림 = 뜻이 바뀜.
- 서버는 `/api/hello` 의 `accepts.team_bundle` 에 받는 MAJOR 목록과 최고 MINOR 를 알린다(v1 서버: `{"1": 0}`). MAJOR 불일치 → 422 `unknown_major` + "LM27 을 같은 판으로 맞추세요". 클라이언트는 보내기 전에 hello 로 먼저 판단하고 보내지 않는다.
- 서버는 받은 바이트를 그대로 저장하므로 나중에 서버가 올라가도 옛 묶음을 다시 해석할 수 있다. 취합기는 MAJOR 별 읽기 함수를 둔다(`read_v1`).
- `generator.core_version`·`rules_ver`·`calendar_version`·`registry_version` 이 팀 다수와 다른 사람은 팀 화면에 "산식 설정 상이" 배지(LM24 `cfg_mismatch` 계승 — 다수가 없으면(동수·2명 미만) 아무도 표시하지 않음).

### 2.7 미리보기 = 실전송 보장

```python
def build_and_queue(analysis, period, cfg) -> QueueItem:
    reg = load_registry_cache(root)                           # data\team\registry.json, 없으면 None
    pep = (reg or {}).get("pepper")                           # 없으면 None → peer_scope=personal
    ov = read_json(root / "data/team/overrides.json", {})
    obj, audit = build_team_bundle(analysis, period, reg, pep, ov, cfg)   # 허용 목록 빌더
    errs = validate_team_bundle(obj, registry=reg, side="client")
    raw = canon_bytes(obj); sha = sha256_hex(raw)
    blockers = [e.msg for e in errs if e.blocking] + size_blockers(raw, cfg)
    with BundleLock(root, purpose="team_build"):
        same = find_pending(sha)                              # 같은 바이트가 이미 대기 중이면 그대로 둔다(승인 상태 유지)
        if same: return same
        supersede_pending(period_key(period))                 # 같은 기간의 다른 미전송 항목 → dropped(superseded)
        path = PENDING / f"lm27_team_bundle_{period_key(period)}_{sha[:12]}.json"
        atomic_write(path, raw)
        atomic_write(str(path) + ".meta.json", canon_bytes(new_meta(sha, len(raw), period, obj, blockers)))
    audit_gate_team(sha, audit)
    return QueueItem(path)
```

- `built_at` 은 빌드 시각이며 분석 입력이 같아도 바뀐다. 결정성 시험(U02)은 `built_at` 을 주입해 고정한다.
- **미리보기 화면은 이 파일의 바이트를 읽어** sha 를 재계산·대조한 뒤 보여 준다: 요약(월별 MM·영역별 분·단위업무 수), 가림 표(§2.5), 금지 내용 검사 결과(0건), 원문 JSON 보기(같은 바이트), `sha256 앞 12자`·크기.
- [보내기]는 같은 파일 바이트를 그대로 POST 본문으로 보낸다. 보내기 직전에 sha 를 다시 대조하고, 다르면 보내지 않는다("미리보기 이후 파일이 바뀌었습니다 — 다시 만드세요").
- 보내는 시점의 정보(보낸 시각·클라이언트 판)는 **본문을 고치지 않고** HTTP 헤더로만 보낸다(LM24 는 보낼 때 member 에 `uploaded_at`·`uploaded_from`(호스트명)을 덧써 미리보기와 실전송이 달랐고 호스트명이 팀 서버에 쌓였다).
- 서버는 본문 sha 를 다시 계산해 헤더 `X-LM27-Bundle-SHA256` 과 비교하고, 응답에 저장한 sha 를 돌려준다. 클라이언트는 응답 sha == 보낸 sha 일 때만 `sent` 로 옮긴다.
- 같은 바이트를 다시 보내면 서버는 `status: "already_have"` 로 200(멱등, 원형 실측).

### 2.8 대기열·재시도

`meta.json`:

```json
{"schema": "lm27.outbox/1", "sha256": "…", "bytes": 81234, "period_key": "2026-07-01_2026-09-30",
 "person_key": "p_7fa3c2d19e01", "built_at": "…", "built_on": "클라우드PC", "blockers": [],
 "approved": false, "approved_at": null, "state": "pending", "attempts": 0, "next_at": null,
 "last_error": null, "last_target": null,
 "history": [{"at": "…", "event": "built"}]}
```

`built_on` 은 `label_auto`(PC 라벨)다 — 호스트명이 아니다. `last_target` 은 `primary`·`alt1`… (주소 문자열을 쓰지 않는다 — 번들이 이동해도 그 망의 주소 설정을 따른다).

상태 기계:

```
built ─(미리보기에서 [보내기] = approved)─▶ sending ─200─▶ sent  (파일+meta → sent\, sent 는 team.sent_keep=20 개까지)
   │                                        ├─네트워크오류·시간초과·429·5xx──────▶ retry_wait ─(next_at)─▶ sending
   │                                        ├─400·411·415·422·413───────────────▶ failed   ([다시 만들기]만 가능)
   │                                        ├─401──────────────────────────────▶ auth_needed (토큰 설정이 바뀌면 자동 재개)
   │                                        └─hello 가 LM27 아님(모든 주소)·404·410─▶ wrong_server (주소 설정이 바뀌면 자동 재개)
   ├─같은 기간 새 빌드─────────────────────────▶ dropped(superseded)
   ├─[파일로 내보내기]──────────────────────────▶ exported ─(서버 /api/members 에 같은 sha 확인)─▶ delivered
   └─[치우기]────────────────────────────────▶ dropped
```

- `blockers` 가 하나라도 있는 항목은 미리보기에서 [보내기]·[파일로 내보내기]가 비활성이고 사유를 그대로 보인다(LM24 '준비 시점에 알린다' 계승 — 며칠 뒤 서버망에서야 실패를 알게 되지 않게).
- 재시도 간격 `team.retry_schedule_s` = [60, 300, 900, 3600, 10800, 21600] (마지막 값 반복), 각 ±10% 흔들기. `team.retry_max_attempts`(50) 넘으면 `failed(retry_exhausted)` — 화면에 [다시 시도] 버튼.
- 재시도는 **승인된 항목만** 자동으로 한다. 계기: 화면 기동, 빌드 직후, 화면이 떠 있는 동안 15분마다, [팀 업로드] 버튼, **[수집](bat `--auto` 포함)의 끝**(§1.7 ⑨). 그래서 클라우드PC 에서 승인해 둔 묶음은 폴더가 사내 PC 로 돌아와 [수집]만 눌러도 나간다(결정 메모 10.4 — 수동 조작 없음). 에이전트는 번들을 읽지 않으므로 업로드하지 않는다.
- `retry_wait` 의 `next_at` 은 망이 바뀌면 의미가 없으므로, [수집]·화면 기동 계기에서는 `next_at` 을 기다리지 않고 hello 1회를 먼저 해 본다(닿으면 즉시 보냄, 안 닿으면 `attempts` 를 올리지 않고 다음 계기를 기다림 — 클라우드PC 에서 며칠 머무는 동안 시도 횟수가 소진되지 않게).
- 중복 전송 방지: 보내기 전 `<item>.lease` 를 `os.open(O_CREAT|O_EXCL)` 로 만든다(내용 `{pid, until=+10분}`). 이미 있고 만료 전이며 그 pid 가 살아 있으면 건너뛴다. 서버도 sha 멱등이라 겹쳐도 안전.
- `team.auto_send`(기본 false): true 면 빌드 직후 승인 없이 보낸다(팀이 합의한 경우만). 기본은 기간마다 첫 전송을 사람이 미리보기에서 승인(미결 9).

### 2.9 보내기 절차

```python
def send_item(item, cfg) -> str:                               # 새 상태를 돌려준다
    raw = read_bytes(item.path)
    if sha256_hex(raw) != item.meta["sha256"]:
        return mark(item, "failed", "묶음 파일이 미리보기 이후 바뀌었습니다 — 다시 만드세요")
    tgt, h = pick_target(cfg)                                  # 기본 주소 → 대체 주소 목록 순회
    if tgt is None:
        if h.all_unreachable:
            return retry(item, f"이 망에서 팀 서버에 닿지 않습니다({h.reason_ko}) — 묶음은 그대로 대기합니다")
        return mark(item, "wrong_server", h.describe_ko())     # "기본 주소에는 LM24 팀 서버가 응답합니다 …" — POST 하지 않는다
    if "1" not in h.accepts.get("team_bundle", {}):
        return mark(item, "failed", "팀 서버 판과 맞지 않습니다(묶음 v1) — LM27 판을 맞추세요")
    if h.auth_upload and not secret("team.upload_token"):
        return mark(item, "auth_needed", "팀 서버가 업로드 토큰을 요구합니다 — 설정 > 팀 서버 > 토큰")
    hdr = {"Content-Type": "application/json; charset=utf-8", "X-LM27-Bundle-SHA256": item.meta["sha256"],
           "X-LM27-Client": APP_VERSION, "X-LM27-Sent-At": local_now_iso()}
    if secret("team.upload_token"): hdr["X-LM27-Upload-Token"] = secret("team.upload_token")
    st, body = http_post(tgt.url + "/api/bundles", raw, hdr, timeout=cfg.team.upload_timeout_s)
    item.meta["last_target"] = tgt.name                        # primary / alt1 …
    return classify_and_mark(item, st, body)                   # §2.8 표대로; 200 이면 body["sha256"] 대조

def pick_target(cfg):
    """기본 주소(http://<server_host>:<server_port>)를 먼저, 아니면 team.server_alternates 를 순서대로.
    hello 가 LM27-team 이고 accepts 가 맞는 첫 주소를 고른다. 설정 값은 바꾸지 않는다(기본 주소 고정 — 사용자 지시)."""
```

**hello 판정**(`lm27/team/client.py: hello(base, timeout) -> Hello`):

| 관측 | `result` | 사람에게 보일 문구(요지) |
|---|---|---|
| 200 + `app == "LM27-team"` + `proto` 가 `lm27-team/` 로 시작 | `ok` | — |
| 200 + `app` 이 `LM` 으로 시작하는 다른 값(예: `LM26-team`) | `other_lm` | "이 주소에는 LM27 이 아닌 다른 판(…)의 팀 서버가 응답합니다" |
| `/api/hello` 404 + `/api/whoami` 가 `root` 키를 가진 객체 **또는** `/api/team` 이 `members` + (`uploads` 또는 `agg_note`) 모양 | `lm24` | "이 주소에는 LM27 이 아니라 이전 판(LM24) 팀 서버가 응답합니다. LM27 팀 서버의 포트를 확인해 설정에서 바꾸세요" |
| 그 밖의 HTTP 응답 | `other_app` / `http_error` | "LM27 팀 서버가 아닌 프로그램이 응답합니다(HTTP 코드)" |
| 연결 시간 초과(`team.connect_timeout_s`=4) | `timeout` | "응답이 없습니다 — 다른 망(클라우드PC·재택)이거나 방화벽이 막고 있을 수 있습니다" |
| `ConnectionRefusedError`(WinError 10061) | `refused` | "그 주소의 PC 는 켜져 있으나 그 포트에 서버가 없습니다(팀 서버가 꺼졌거나 포트가 다름)" |
| `socket.gaierror` | `dns` | — (기본 설정은 IP 라 드묾) |

- LM24 판정을 위해 `/api/whoami`·`/api/team` 응답을 읽을 때 본문은 **모양만 보고 버린다**(LM24 응답에는 경로·토큰이 들어 있다 — 기록·표시 금지).
- HTTP 클라이언트: `urllib.request.build_opener(urllib.request.ProxyHandler({}))` — **시스템 프록시를 쓰지 않는다**(사내 IP 로 가는 요청이 레지스트리 프록시 설정을 타서 막히는 것 방지). `team.use_system_proxy=true` 일 때만 기본 opener. 오류 응답은 `HTTPError.read()` 로 JSON 본문을 읽어 `error`(한국어)를 화면에 그대로 보인다.
- 결과는 pc.json `team_server_reach` 탐침에도 남긴다(§1.5).

---

## 3. 팀 서버

### 3.1 실행

- 진입: `LoadMonitor27-팀서버.bat` = `pushd "%TEMP%"` → `"<ROOT>\python\python.exe" <단일 진입점> team-server [--host H] [--port N] [--store DIR]` (진입점 이름·sys.path 처리는 공용 진입점 규약을 따른다 — 동봉 파이썬 `python311._pth` 가 스크립트 폴더를 sys.path 에 넣지 않으므로 진입점이 ROOT 를 스스로 넣는다. LM24 `aggregate.py` 실측: 이것이 빠지면 import 실패가 try/except 에 묻혀 기능이 조용히 사라졌다). 화면(대시보드)의 [팀 서버] 카드에서도 같은 명령을 띄운다.
- 권장 운영: 팀 서버는 **옮기지 않는 별도 설치 폴더**(예: 팀 공용 PC 의 `D:\LoadMonitor27_팀서버\`)에서 돌린다. 개인 번들 폴더로 돌려도 되지만 [이동 준비]가 그 사실을 알리고 멈춘다(§1.11 3).
- 표준 라이브러리만: `http.server.ThreadingHTTPServer`(daemon_threads=True), `json`, `hashlib`, `hmac`, `ipaddress`, `threading`, `subprocess`, `msvcrt`, `socket`, `secrets`.
- 저장소: `team_server.store_dir`(기본 빈 값 → `%LOCALAPPDATA%\LoadMonitor27\teamserver\`). 프로그램 폴더 밖이라 폴더 이동·교체·판 올림과 무관하다. 공유 드라이브 경로는 권장하지 않는다(잠금·원자 교체가 SMB 에서 불안정할 수 있음 — 미결 11). 서버와 취합기는 언제나 같은 `--store` 를 쓴다(LM24 '받는 곳과 보는 곳이 갈라져 업로드가 화면에 영영 안 뜸' 결함 계승 방어).

### 3.2 설정 키(서버)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `team_server.bind_host` | `"0.0.0.0"` | 받는 주소. 화면에서 이 PC 의 IPv4 목록 중 하나 또는 모든 인터페이스 선택 |
| `team_server.bind_port` | `9310` | 받는 포트(1024~65535). 화면에서 변경 |
| `team_server.store_dir` | `""` | 비면 `%LOCALAPPDATA%\LoadMonitor27\teamserver` |
| `team_server.display_name` | `""` | hello·대시보드 제목에 쓰는 이름(예: "팀A 팀 서버") |
| `team_server.upload_token_sha256` | `""` | 비면 업로드 인증 없음. 화면에서 토큰을 입력하면 sha256 만 저장 |
| `team_server.read_requires_token` | `false` | true 면 `/api/team`·`/api/team/detail`·`/api/members`·`/api/registry` 도 업로드 토큰(같은 값, 헤더 `X-LM27-Upload-Token`)을 요구. 대시보드 셸(`/`·`/static/*`)은 데이터가 없으므로 공개이고, 화면이 토큰을 입력받아(sessionStorage) API 헤더에 싣는다. 이때 `/report*` 직접 열기는 403 이고 대시보드의 [보고서 내려받기](헤더를 실은 fetch → 파일 저장)로만 받는다 |
| `team_server.admin_token_sha256` | `""` | 레지스트리 편집·인원 관리·재취합 토큰. 비면 **이 PC(127.0.0.1·::1)에서만** 허용 |
| `team_server.allow_cidrs` | `[]` | 비면 모두 허용. 예 `["10.0.0.0/8"]`(루프백은 항상 허용) |
| `team_server.allowed_hosts` | `[]` | `Host` 헤더 허용 이름 추가분. 기본 허용 = 이 PC 의 IPv4 들 · `127.0.0.1` · `localhost` · `[::1]` (각 `:포트`). DNS 재바인딩 방어 |
| `team_server.max_body_mb` | `16` | 업로드 본문 상한 |
| `team_server.max_concurrent_uploads` | `4` | 동시 업로드 수(넘으면 429 + Retry-After 30) |
| `team_server.request_timeout_s` | `60` | 소켓 읽기 시간 제한(느린 연결이 스레드를 붙잡지 않게) |
| `team_server.aggregate_debounce_s` | `3` | 연속 업로드를 한 번의 재취합으로 묶는 대기 |
| `team_server.aggregate_wait_s` | `20` | 업로드 응답이 재취합 완료를 기다리는 최대 시간 |
| `team_server.aggregate_timeout_s` | `300` | 재취합 하위 프로세스 시간 제한 |
| `team_server.history_keep` | `5` | 사람×기간별 옛 묶음 보관 수 |
| `team_server.gen_keep` | `3` | 취합 산출 세대 보관 수 |
| `team_server.inbox_dirs` | `[]` | 오프라인 반입 감시 폴더(읽기 전용 스캔) — `<store>\inbox\` 는 항상 감시 |
| `team_server.inbox_poll_s` | `30` | 반입 폴더 확인 주기 |
| `team_server.publish_dir` | `""` | 레지스트리를 파일로도 게시할 공유폴더(오프라인 클라이언트용) |
| `team_server.log_keep_days` | `30` | 로그 보관 일수 |
| `team_server.suggest_ranges` | `[[19310, 19330], [9311, 9330]]` | 대체 포트 후보 구간(앞 구간 우선 — 이 PC 실측 임시 포트 범위 1024~15000 밖) |
| `team_server.firewall_hint_after_min` | `30` | 가동 후 이 시간 동안 다른 PC 요청이 0건이면 방화벽 진단을 띄움(§3.14) |
| `team_server.gantt_merge_gap_days` | `2` | 간트 active 구간을 이을 최대 빈 날(§4.6) |

### 3.3 시작 순서와 배타 바인드

```python
class LM27HTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False          # ★ 기본 HTTPServer 는 1 — 윈도우에서 살아 있는 리스너 위 덧바인드를 허용한다
    daemon_threads = True
    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()
```

실측(이 PC, 3.11.9, 2026-10-05 재실측): 기본 `HTTPServer` 로 연 포트에 다른 소켓이 `SO_REUSEADDR` 로 **덧바인드에 성공**했다(업로드가 엉뚱한 프로세스로 가는 최악 상태). `SO_EXCLUSIVEADDRUSE` 로 연 포트(위 클래스 원형 포함)는 덧바인드가 `WinError 10013` 으로 막혔다. 평범한 두 번째 바인드는 `10048`. → **오류 코드만으로 원인을 단정하지 않고**(10013 은 '예약 범위'일 수도, '배타 점유'일 수도 있다) §3.4 의 OS 사실로 판정한다.

```python
def serve(cfg) -> int:
    store = open_store(cfg)          # 저장소 잠금 <store>\run\server.lock (msvcrt). 실패 → "이 저장소를 이미 쓰는 서버가 있습니다(pid …)" rc=3
    host, port = cfg.team_server.bind_host, cfg.team_server.bind_port
    try:
        srv = LM27HTTPServer((host, port), make_handler(store, cfg))
    except OSError as e:
        d = diagnose_port(port, winerror_of(e), cfg)
        print_ko(d.message); atomic_write(store.run / "port_diag.json", canon_bytes(d.as_dict()))
        return 3
    write_server_json(store, pid=os.getpid(), port=port, host=host, instance_id=secrets.token_hex(8),
                      exe=sys.executable)
    start_workers(store, cfg)        # 재취합 워커, 반입 폴더 감시, 로그 정리, 방화벽 진단 타이머
    print_ko("[팀 서버] 가동 — 팀원에게 알릴 주소: " + ", ".join(f"http://{ip}:{port}" for ip in local_ipv4s()))
    print_ko(f"[팀 서버] 저장소: {store.dir}")       # 경로는 이 콘솔에만(응답·로그 파일에는 쓰지 않는다)
    try: srv.serve_forever()
    finally: clear_server_json_if_mine(store); release_store_lock(store)
    return 0
```

`<store>\run\server.json` = `{pid, port, bind_host, started_at, instance_id, store_id, version, exe}` — 자기 pid 일 때만 지운다(뒤에 뜬 인스턴스 기록을 지우지 않게, LM24 `clear_pid` 계승).

"내 서버" 증명(화면이 "이 저장소의 서버가 돌고 있다"고 말할 근거): `hello.instance_id == server.json.instance_id` **그리고** `server.json.pid ∈ listeners(port)`. 네트워크 응답만으로는 판단하지 않는다(그 포트에 먼저 붙은 아무 프로그램이나 흉내낼 수 있다 — LM24 반박 검증).

### 3.4 포트 점유 진단과 대체 포트 제안

```python
def diagnose_port(port, code, cfg) -> PortDiag:
    lis = listeners(port)            # netstat -ano 파싱('-p TCP' 쓰지 않음 — IPv6 행이 빠진다). 출력은 ascii 로 디코드
                                     # (한국어 헤더만 CP949, 데이터 행은 ASCII). 실패 시 powershell
                                     # (Get-NetTCPConnection -LocalPort N -State Listen).OwningProcess. 못 알아냄 = None(≠ 빈 목록)
    procs = proc_info(lis or [])     # Get-CimInstance Win32_Process: Name·ExecutablePath·CommandLine(다른 계정이면 NULL → '확인 불가')
    ident = probe_identity(port)     # 127.0.0.1 로 §2.9 hello 판정과 같은 함수
    rsv = reserved_range_of(port)    # netsh interface ipv4 show excludedportrange protocol=tcp (CP949 디코드, 숫자 쌍 정규식)
    lo, hi = dynamic_range()         # netsh interface ipv4 show dynamicport tcp → (시작, 시작+개수-1)
    kind = classify(lis, procs, ident, rsv, (lo, hi), port)
    return PortDiag(kind=kind, code=code, listeners=lis, procs=procs, ident=ident, reserved=rsv,
                    dynamic=(lo, hi), suggest=suggest_port(port, cfg), message=message_ko(kind, …))
```

| kind | 판정 | 화면/콘솔 문구(요지) | 조치 버튼 |
|---|---|---|---|
| `lm27_same` | hello=LM27 이고 `store_id` 가 이 저장소 | "이 저장소의 LM27 팀 서버가 이미 실행 중입니다(pid N). 새로 띄울 필요가 없습니다." | [열기] |
| `lm27_other` | hello=LM27, 다른 store_id | "다른 저장소의 LM27 팀 서버(이름 …)가 이 포트를 쓰고 있습니다." | [대체 포트 N 으로 시작] |
| `lm24` | §2.9 판정이 LM24 | "이전 판(LM24) 팀 서버가 9310 을 쓰고 있습니다(프로세스 python.exe, pid N). 두 서버가 같은 포트를 쓸 수 없습니다. LM27 은 대체 포트 N 으로 열고, 팀원 설정의 포트(또는 대체 주소)를 N 으로 바꾸세요." | [대체 포트 N 으로 시작] |
| `other_lm` | hello 의 app 이 다른 LM 판 | "다른 판(…)의 팀 서버가 이 포트를 쓰고 있습니다." | 〃 |
| `other_program` | 리스너 있음, 신원 불명 | "다른 프로그램(<이름>.exe, pid N, <경로 또는 '확인 불가'>)이 이 포트를 쓰고 있습니다." | 〃 |
| `reserved` | 리스너 없음 + 예약 범위 | "윈도우가 a~b 포트를 예약해 두었습니다." | 〃 |
| `ephemeral` | 리스너 없음 + 임시 포트 범위 안 | "다른 프로그램의 바깥 연결이 이 번호를 잠깐 쓰고 있습니다(임시 포트 범위 lo~hi). 잠시 뒤 다시 시도하거나 범위 밖 포트를 쓰세요." | [다시 시도] [대체 포트] |
| `unknown` | 리스너 조회 실패(None) | "누가 쓰는지 알아내지 못했습니다(조회 차단)." | [대체 포트] |

- **이 PC 실측**: 임시(동적) 포트 범위가 `1024~15000`(시작 1024, 13,977개)이라 **9310 이 그 안에 있다**. 이런 PC 에서는 아무 프로그램의 바깥 연결이 9310 을 잠깐 차지해 서버가 못 뜰 수 있다(`ephemeral`). 기본값 9310 은 사용자 지시로 바꾸지 않으므로, 진단은 이 사실을 문구에 넣고 대체 포트(19310~)를 제안한다. 임시 범위를 바꾸는 `netsh int ipv4 set dynamicport`·예약 추가는 관리자 권한이 필요하므로 하지 않고 "IT 에 요청할 수 있는 내용"으로만 보인다.
- **LM27 서버는 남의 프로세스를 죽이지 않는다.** LM24 서버·다른 프로그램 종료 버튼을 두지 않는다(LM24 동결 원칙, 오종료 위험). 자기 저장소의 LM27 서버(`lm27_same`)만 `/api/shutdown`(로컬)으로 끌 수 있다.
- 포트를 몰래 바꾸지 않는다. 대체 포트는 제안만 하고, 사람이 [대체 포트 N 으로 시작]을 누르면 `team_server.bind_port` 를 저장하고 시작한다. 콘솔(bat)에서는 `--port N` 안내를 출력한다.

```python
AVOID = set(range(8765, 8768)) | set(range(9148, 9168))      # D:\배포\LM26(다른 도구) 개인·팀·데모 포트, LM24 대시보드 대역

def suggest_port(cur, cfg) -> int:
    lo, hi = dynamic_range()
    avoid = AVOID | {cfg.ui.port}                             # 이 LM27 개인 대시보드 포트(ui.port — 화면 명세 소관 키)
    for a, b in cfg.team_server.suggest_ranges:
        for p in range(a, b + 1):
            if p == cur or p in avoid or (lo and lo <= p <= hi) or reserved_range_of(p):
                continue
            if bind_test(p):                                  # SO_EXCLUSIVEADDRUSE 로 0.0.0.0·127.0.0.1 둘 다 bind → 즉시 close
                return p
    return 0                                                  # 못 찾음 → "포트를 직접 입력하세요"
```

### 3.5 `/api/hello` — 신원

```json
{"app": "LM27-team", "proto": "lm27-team/1", "version": "0.1.0", "api": 1,
 "accepts": {"team_bundle": {"1": 0}}, "auth": {"upload": false, "read": false},
 "max_body_mb": 16, "instance_id": "9c1e2a7b4d5f6e8a", "store_id": "5b2a…", "name": "팀A 팀 서버",
 "registry_version": 7, "pepper_id": "9f2c01ab", "server_time": "2026-10-05T09:12:00+09:00"}
```

- 경로·pid·호스트명·토큰을 돌려주지 않는다(LM24 `/api/team` 이 root·store·pid·token 을, 업로드 응답이 `host`(COMPUTERNAME)·store·root 를 돌려준 노출 결함 제거).
- 클라이언트 판정은 §2.9 표. hello 는 인증 없이 항상 응답한다(`read_requires_token` 이어도) — 신원 확인이 먼저다.

### 3.6 API 목록

| 메서드·경로 | 권한 | 요청 | 응답 |
|---|---|---|---|
| `GET /api/hello` | 없음 | — | §3.5 |
| `POST /api/bundles` | 업로드 토큰(설정 시) | 본문 = 팀 묶음 바이트, 헤더 `X-LM27-Bundle-SHA256` 필수 | `{"ok":true,"status":"stored\|already_have\|stale_kept","person_key","period_key","sha256","replaced":<옛 sha12\|null>,"aggregate":{"gen":N,"state":"done\|queued\|failed","note"}}` |
| `GET /api/registry` | 읽기 토큰(설정 시) | `If-None-Match: "<version>"` | 200 레지스트리 JSON(+`pepper`) + `ETag: "<version>"` / 304 |
| `PUT /api/registry` | 관리 토큰 또는 로컬 | 레지스트리 전체, `version` = 현재+1 | 200 `{"ok":true,"version":N}` / 409 `registry_version_conflict` |
| `GET /api/members` | 읽기 토큰(설정 시) | — | §3.11 |
| `PATCH /api/members/<person_key>` | 관리 | `{"label"?, "member_id"?, "retired"?, "link_to"?, "drop_period"?}` | 200 (`drop_period` = 그 기간 현재 묶음을 current 에서 빼기, 파일은 history 로) |
| `GET /api/team` | 읽기 토큰(설정 시) | — | 현재 세대 `team_data.json`(§4.9) |
| `GET /api/team/detail?person=<person_key>&role=<role_id>` | 〃 | — | 그 사람·역할의 워크플로우 + 단위업무 목록(간트 드릴다운, §4.6) |
| `GET /api/status` | 없음 | — | `{"uploads_today","last_upload_at","aggregate":{"gen","state","at","sec","note"},"members","inbox":{"pending","rejected"},"external_requests","firewall_hint"}` |
| `POST /api/aggregate` | 관리 | — | 재취합 즉시 요청(LM24 의 부작용 있는 `GET /refresh` 대체) |
| `POST /api/shutdown` | 로컬만 | — | 200 후 종료 |
| `POST /api/upload` | — | (LM24 클라이언트) | 410 `{"ok":false,"code":"lm24_endpoint","error":"이 서버는 LM27 팀 서버입니다. LM24 업로드는 받지 않습니다."}` |
| `GET /` · `/admin` · `/static/<이름>` | 없음(데이터 없는 셸) | — | 대시보드 정적 파일(§3.12). 데이터는 화면이 API 로 가져온다 |
| `GET /report` · `/report/share` | 없음. 단 `read_requires_token=true` 면 403 | — | 생성된 팀 보고서(§3.9). 토큰 모드에서는 대시보드 [보고서 내려받기]로만 |
| `OPTIONS *` | — | — | 405(교차 출처 사전 요청에 허용을 주지 않는다 — 다른 사이트 페이지의 JSON POST·PUT 차단) |

공통 처리(모든 요청, 핸들러 진입 직후): ① `Host` 헤더가 허용 목록(§3.2 `allowed_hosts`)에 없으면 421 `bad_host` ② `allow_cidrs` 위반 403 ③ 응답에 `Cache-Control: no-store`(API), `X-Content-Type-Options: nosniff`. `Access-Control-Allow-Origin` 은 보내지 않는다.

오류 응답 형식(모든 4xx·5xx): `{"ok": false, "code": "<영문 코드>", "error": "<한국어 설명>", "detail": [<최대 20개 — 경로·코드만, 값 없음>]}`.

| HTTP | code | 상황 |
|---|---|---|
| 400 | `bad_json`·`not_object`·`dup_key`·`sha_mismatch`·`sha_missing` | 본문 해석 실패, sha 불일치 |
| 401 | `token_required`·`token_invalid` | 토큰 |
| 403 | `forbidden_ip`·`admin_only`·`read_token_mode` | allow_cidrs, 관리 권한, 토큰 모드의 /report |
| 404 | `not_found` | |
| 405 | `method` | |
| 409 | `registry_version_conflict` | |
| 410 | `lm24_endpoint` | |
| 411 | `length_required` | Content-Length 없음 |
| 413 | `too_large` | |
| 415 | `content_type` | `application/json` 아님(교차 출처 폼 POST 차단도 겸함) |
| 421 | `bad_host` | Host 헤더 불일치(DNS 재바인딩) |
| 422 | `schema`·`unknown_major`·`forbidden_content`·`integrity`·`ref_missing` | 검증 실패 |
| 429 | `busy` | 동시 업로드 초과(`Retry-After: 30`) |
| 500 | `store_failed` | 저장 실패(디스크·권한) |

### 3.7 저장소 배치

```
<store>\                           (기본 %LOCALAPPDATA%\LoadMonitor27\teamserver\)
├─ store.json                     {"schema":"lm27.teamstore/1","store_id":"…","created_at":"…"}
├─ secrets\pepper.json            {"pepper":"<64hex>","pepper_id":"…","created_at":"…"} — 정적 제공 금지, /api/registry 로만
├─ registry.json                  현재 레지스트리(pepper 없이 저장, 응답 때 합성) + registry_history\v0007.json …
├─ roster.json                    {"labels":{person_key: 표시 라벨}, "links":{person_key: 대표 person_key}, "retired":[…], "member_of":{person_key: member_id}}
├─ members\<person_key>\
│  ├─ current.json                {"<period_key>": {"sha256","file","received_at","built_at","client","via"}, …}
│  ├─ current.json.bak
│  └─ bundles\<period_key>__<sha12>.json     받은 바이트 그대로(불변)
├─ inbox\  (done\ · rejected\)     오프라인 반입(§5)
├─ out\gen_<N>\                   team_data.json · team_report.html · team_report_share.html · result.json
├─ out\current.json               {"gen":N,"dir":"gen_N","at":"…","members":M,"warnings":[…]}
├─ run\                           server.lock · server.json · port_diag.json · inbox_seen.json · firewall_diag.json
└─ logs\                          server_YYYYMMDD.log · uploads.jsonl · aggregate_YYYYMMDD.log
```

- 폴더 이름은 서버가 만든 것뿐이다. `person_key` 는 `^p_[0-9a-f]{12}$` 이므로 경로 문자·윈도우 장치 예약어(CON 등)·취합 산출물 접두와 충돌할 수 없다(LM24 `owner` 폴더명 결함군 — 같은 사람 두 폴더·CON 폴더·산출물 접두 충돌 — 을 형식으로 원천 차단).

### 3.8 업로드 처리(사람 단위 원자 교체)

HTTP 와 오프라인 반입이 **같은 함수**를 쓴다.

```python
def handle_post_bundles(h):                                  # BaseHTTPRequestHandler 메서드
    n = content_length(h)                                    # 헤더 없음 → None, 음수·숫자 아님 → -1
    def reject(http, code, **kw):                            # 본문이 있는 요청은 '읽고' 거절한다 — 안 읽고 답하면
        drain(h, min(max(n or 0, 0), 64 * MB))               # 클라이언트가 아직 보내는 중이라 RST 로 오류 응답조차
        if (n or 0) > 64 * MB: h.close_connection = True     # 못 간다(LM24 실측). 64MB 넘는 허위 길이는 연결을 닫는다
        return err(http, code, **kw)
    if not ip_allowed(h.client_address[0], cfg.allow_cidrs): return reject(403, "forbidden_ip")
    if cfg.upload_token_sha256 and not token_ok(h.headers.get("X-LM27-Upload-Token"), cfg.upload_token_sha256):
        return reject(401, "token_required" if not h.headers.get("X-LM27-Upload-Token") else "token_invalid")
    if not h.headers.get("Content-Type", "").startswith("application/json"): return reject(415, "content_type")
    if n is None: return reject(411, "length_required")
    if n <= 0: return reject(400, "bad_json")
    if n > cfg.max_body_mb * MB: return reject(413, "too_large")
    if not UPLOAD_SEM.acquire(blocking=False): return reject(429, "busy", retry_after=30)
    try:
        raw = read_exact(h.rfile, n)                         # 소켓 timeout = request_timeout_s
        r = ingest_bytes(STORE, raw, source="http", claimed_sha=h.headers.get("X-LM27-Bundle-SHA256"),
                         client=h.headers.get("X-LM27-Client", "")[:20], ip=h.client_address[0])
    finally:
        UPLOAD_SEM.release()
    if not r.ok: return err(r.http, r.code, r.msg, r.detail)
    agg = AGG.request_and_wait(timeout_s=cfg.aggregate_wait_s) if r.status == "stored" else AGG.status()
    return ok({"status": r.status, "person_key": r.person_key, "period_key": r.period_key,
               "sha256": r.sha, "replaced": r.replaced, "aggregate": agg})

def token_ok(given, want_sha):
    return bool(given) and hmac.compare_digest(sha256_hex(given.encode("utf-8")), want_sha)

def ingest_bytes(store, raw, *, source, claimed_sha=None, client="", ip="") -> IngestResult:
    sha = sha256_hex(raw)
    if source == "http" and not claimed_sha: return fail(400, "sha_missing")
    if claimed_sha and claimed_sha.lower() != sha: return fail(400, "sha_mismatch")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_dup_keys, parse_constant=reject_nan)
    except UnicodeDecodeError: return fail(400, "bad_json", "UTF-8 이 아닙니다")
    except ValueError as e:   return fail(400, "dup_key" if "dup key" in str(e) else "bad_json")
    if not isinstance(obj, dict): return fail(400, "not_object")
    if depth(obj) > 32: return fail(422, "schema", "중첩이 너무 깊습니다")
    errs = validate_team_bundle(obj, registry=store.registry(), side="server")   # 공용 검증기(+ PRIVACY check_team_payload 재검사)
    if blocking(errs): return fail(422, first_code(errs), detail=[e.path + ": " + e.code for e in errs][:20])
    pk, per, built = obj["person"]["person_key"], period_key_of(obj), parse_iso(obj["built_at"])
    with store.person_lock(pk):                              # 같은 사람 동시 업로드 직렬화(LM24 OWNER_LOCKS 계승)
        cur = read_json(store.member(pk) / "current.json", {}, want=dict)
        old = cur.get(per, {})
        if old.get("sha256") == sha:
            log_upload(…, status="already_have"); return ok_status("already_have")
        fn = f"{per}__{sha[:12]}.json"
        atomic_write(store.member(pk) / "bundles" / fn, raw)              # ① 불변 묶음(새 이름 → 기존 것 안 건드림)
        if old and parse_iso(old["built_at"]) > built:                    # ② 옛 묶음 역전 방지(USB 로 늦게 온 옛 파일 등)
            log_upload(…, status="stale_kept"); return ok_status("stale_kept")   # 보관만, current 는 그대로
        new = dict(cur); new[per] = {"sha256": sha, "file": fn, "received_at": now_iso(), "built_at": obj["built_at"],
                                     "client": client, "via": source}
        copy_if_exists(store.member(pk) / "current.json", store.member(pk) / "current.json.bak")
        atomic_write(store.member(pk) / "current.json", canon_bytes(new))  # ③ 색인 한 파일 교체 = 원자적 전환점
        prune_history(store.member(pk), per, keep=cfg.history_keep)       # current 가 가리키지 않는 옛 묶음만
    log_upload(ts=now_iso(), person_key=pk, period_key=per, sha=sha, bytes=len(raw), ip=ip, client=client,
               source=source, status="stored", replaced=old.get("sha256", "")[:12] or None)
    return ok_status("stored", replaced=…)
```

- 원자성: 새 묶음은 새 파일 이름으로 쓰고, "무엇이 현재인가"는 `current.json` 한 파일의 `os.replace` 로만 바뀐다. 취합기는 `current.json` 을 읽은(열고·읽고·닫은) 뒤 불변 묶음만 읽으므로 반쪽 상태를 볼 수 없다. LM24 의 `.part/.bak` 다중 파일 교체·되돌리기보다 단순하고, 되돌릴 일이 생기지 않는다.
- 원형 실측(스크래치): 같은 사람 6건(기간 2개 × 3변형) + 다른 사람 3건을 동시에 보냈을 때 9건 모두 `stored`, `current.json` 의 두 기간이 각각 저장 파일의 sha 와 일치, `.part` 잔존 0, 같은 바이트 재전송은 `already_have`. 이 원형에는 `stale_kept` 규칙이 없어 같은 기간은 마지막 도착이 이겼다 — 본 규칙(②)은 그 경우 `built_at` 이 가장 늦은 묶음이 남게 한다.
- `current.json` 이 깨졌으면(손편집 등) `.bak` → 그것도 깨졌으면 `bundles\` 파일에서 기간별 `built_at` 최신으로 재구성하고 경고를 남긴다.

### 3.9 재취합과 팀 보고서 생성

- 워커 스레드 1개(`AGG`). `request()` 는 세대 번호를 올리고 이벤트를 세운다. 워커는 `aggregate_debounce_s` 동안 더 오는 요청을 모은 뒤 한 번 돈다 — 여럿이 동시에 올려도 취합은 1~2회(LM24 `AGG_LOCK` 직렬화 계승, 산출물을 서로 밟지 않음).
- 실행은 하위 프로세스: `python\python.exe <진입점> team-aggregate --store <dir> --gen N`(시간 제한 `aggregate_timeout_s`, cwd = store). 하위 프로세스는 `out\gen_N\` 에 산출물을 쓰고 마지막에 `result.json`(`{"ok","members","warnings","sec"}`)을 쓴다. 서버는 **표준출력이 아니라 result.json 을 읽는다**(LM24 의 '마지막 줄 JSON' 파싱 취약점 제거). stderr 끝 20줄은 `aggregate_YYYYMMDD.log` 로.
- 성공하면 `out\current.json` 을 원자 교체(디렉터리 rename 하지 않음 — 서빙 중인 파일이 열려 있어도 안전, LM24 의 '열린 대상 위 replace 실패 → 덮어쓰기' 우회가 필요 없다). 실패하면 이전 세대를 그대로 서빙하고 `/api/status` 와 대시보드 상단에 실패 사유 1줄.
- 오래된 세대 삭제는 `gen_keep` 초과분만, 지우기 실패(열려 있음)는 다음 회차에 다시.
- 산출물: `team_data.json`(대시보드 데이터, §4.9), `team_report.html`(자기완결 보고서, 데이터 섬 `<script type="application/json">` 안의 `<` 를 전부 `\u003c` 로 — LM24 실측 저장형 XSS 방어 계승), `team_report_share.html`(사람별 로드율·초과 시간 열을 뺀 공유판 — 제거 키가 HTML 전체에서 0회인지 관문 검사).
- 서버 시작 때도 재취합 1회(옛 세대가 없거나 레지스트리가 바뀌었으면).

### 3.10 레지스트리 배포·편집

레지스트리 의미 스키마(과제·어휘·카탈로그의 뜻)는 계층·분류 명세 소관이다. 여기서는 운반·버전·검증의 최소 형식만 정한다.

```json
{"schema": "lm27.registry/1", "version": 7, "updated_at": "…", "updated_label": "팀장",
 "team": {"label": "팀A"},
 "pepper": "<64hex — 응답에서만 합성, PUT 으로 못 바꿈>", "pepper_id": "9f2c01ab",
 "domains": ["DEV", "MP", "EXT", "COM", "AX", "UNC"],
 "projects": [{"id": "P-0007", "name": "과제A", "domain": "DEV", "aliases": [], "keywords": [], "codenames": [],
               "mask_name": false, "never": [], "status": "active", "merged_into": null}],
 "members": [{"id": "M003", "label": "홍길동"}],
 "vocab": {"fields": ["기구", "회로", "SW"], "functions": ["설계", "해석/분석", "시험"],
           "activity_types": ["개발", "사무", "현장", "PM", "PL", "지원"],
           "step_types": ["의뢰수신", "자료조사", "설계", "문서작성", "보고"]},
 "agents": [{"id": "AG003", "name": "문서 초안 작성", "axis": "문서", "desc": "", "step_types": ["문서작성"],
             "inputs": ["메일 본문 요약"], "outputs": ["보고서 초안"], "keywords": []}],
 "calendar": {"version": "kr-2026.3", "std_day_min": 480, "std_window": "09:00-18:00", "lunch": "12:00-13:00",
              "night": "22:00-06:00",
              "holidays": [{"date": "2026-07-17", "name": "제헌절", "kind": "법정", "source_url": "…", "checked": "2026-10-05"},
                           {"date": "2026-08-17", "name": "대체공휴일(광복절)", "kind": "대체", "source_url": "…", "checked": "…"},
                           {"date": "2026-09-24", "name": "추석 연휴", "kind": "법정", "source_url": "…", "checked": "…"},
                           {"date": "2026-09-25", "name": "추석", "kind": "법정", "source_url": "…", "checked": "…"},
                           {"date": "2026-10-05", "name": "대체공휴일(개천절)", "kind": "대체", "source_url": "…", "checked": "…"},
                           {"date": "2026-10-09", "name": "한글날", "kind": "법정", "source_url": "…", "checked": "…"}],
              "company_off": []},
 "internal_domains": ["example.com"],
 "customers": [{"id": "C01", "names": [], "domains": []}],
 "partners": []}
```

- 배포 패키지의 기본 레지스트리는 **빈 과제·빈 별칭·빈 코드네임·빈 고객 사전·빈 구성원**이다. 실제 값은 팀장이 팀 서버 `/admin` 에서 넣는다. 달력은 공고 근거 URL·확인일이 달린 항목만(결정 메모 10.3 — 확인된 해만 내장).
- ID 형식: 과제 `^P-\d{4}$`(PRIVACY §8·§14.2 `PROJECT_ID`), 그 밖 레지스트리 ID 는 `^[A-Za-z][A-Za-z0-9_\-]{0,23}$`(`REG_ID`) — 구성원 `M`, 고객 `C`, 협력사 `V`, 에이전트 `AG` 로 시작.
- `GET /api/registry`: `ETag: "<version>"`. 클라이언트는 분석 전(그리고 `team.registry_refresh_h`=12h 마다) `If-None-Match` 로 받아 통째로 `data\team\registry.json` 에 캐시한다(pepper 포함 — PRIVACY §9.1 L2, `keys\` 와 같은 반출 금지). 못 받으면 캐시를 쓰고 화면에 "레지스트리 v7(10-03 받음) 사용 중" 표시. 캐시도 없으면 레지스트리 없이 분석(과제 미지정 = 제안으로만).
- `PUT /api/registry`(팀장 편집, `/admin` 화면이 부른다): 본문 `version` 이 현재+1 이 아니면 409(동시 편집 보호). 검증: ID 형식·중복 없음, domain ∈ 6종, 별칭은 정규화(ukey: NFKC·공백 접기·casefold) 후 과제 간 중복 없음, `merged_into` 는 존재하는 과제 ID 이고 사슬에 순환 없음, pepper 는 서버 값으로 덮어씀, 달력 항목은 날짜 형식·중복 없음, 크기 ≤ 2MB. 통과하면 `registry_history\v0007.json` 보관 → `registry.json` 원자 교체 → `publish_dir` 설정 시 `lm27_registry.json`(pepper 포함 — 미결 3) 게시 → 재취합 요청(과제 소속 영역이 바뀌면 팀 집계가 달라지므로).
- **과제 병합**: 팀장이 두 과제가 같다고 판단하면 한쪽에 `merged_into` 를 단다. 취합은 `resolve_project(id)` 로 사슬을 끝까지 따라가 대표 과제로 합친다(LM24 `resolve_chain` 계승: 순환이면 사슬 안에서 묶음 수가 가장 많은 ID, 동률은 사전순). 팀원 재업로드가 필요 없다.

### 3.11 `/api/members`

```json
{"members": [
  {"i": 0, "person_key": "p_7fa3c2d19e01", "label": "팀원A", "label_source": "roster|member|self|auto",
   "member_id": "M003", "linked": ["p_0b1c2d3e4f50"], "retired": false,
   "periods": [{"period_key": "2026-07-01_2026-09-30", "sha12": "a1b2c3d4e5f6", "received_at": "…", "built_at": "…",
                "via": "http", "used_months": ["2026-07", "2026-08"], "schema_version": "1.0"}],
   "last_upload_at": "…", "client": "0.1.0", "quality": "reliable",
   "flags": ["calendar_mismatch", "cfg_diff", "pepper_mismatch"]}]}
```

- 표시 라벨 우선순위: roster(팀장) > 레지스트리 `members[member_id].label` > 묶음 `self_label` > `팀원-<person_key[2:6] 대문자>`.
- 연결(같은 사람): roster `links`, 같은 `member_id`, 또는 두 person_key 의 `self_peer_key` 가 같을 때(그리고 `pepper_id` 가 서버와 같을 때) 자동. 연결된 사람은 취합에서 한 사람으로 합치고(§4.2), 대표 키 = 가장 먼저 받은 키.
- 클라이언트는 이 응답에서 자기 `person_key` 의 `sha12` 를 보고 오프라인 내보낸 항목을 `delivered` 로 맞춘다.

### 3.12 대시보드 정적 제공·보안 헤더

- 정적 파일은 **고정 사전**만 제공: `{"/": "web/team/index.html", "/admin": "web/team/admin.html", "/static/team.js": …, "/static/team.css": …, "/static/icons.svg": …}`. 경로 조합(`os.path.join(base, 요청경로)`) 금지. 외부 CDN 금지(로컬 SVG·CSS). 디자인 언어는 화면 명세 소관(LM20: 상단 가로 pill 메뉴·#f2f4f7 바탕·#2a78d6 파랑·KPI 카드).
- 대시보드·관리 화면 헤더: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. API 는 `Cache-Control: no-store`.
- 생성 보고서(`/report`, `/report/share`): `Content-Security-Policy: sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox`(origin 분리 — 이스케이프가 한 곳 새도 `/api/*` 를 부를 수 없다, LM24 계승).
- 업로드로 들어온 모든 문자열은 화면에 낼 때 이스케이프(JS 는 `textContent` 만, `innerHTML` 금지). 사람 키·라벨을 JS 객체 키로 직접 쓰지 않고 정수 인덱스 `i` 로 참조(LM24 이름 하나로 절 전체가 죽은 결함 방어).
- 이 문서가 보장하는 데이터 경로: KPI·영역별 투입·과제×인원·역할/유형 분포·agentic 취합 = `/api/team` ; 간트 막대·행 클릭 → `/api/team/detail?person=<person_key>&role=<role_id>`.

### 3.13 로그

- `logs\server_YYYYMMDD.log`: 시작·종료·포트·오류·업로드 결과 1줄씩. 형식 `2026-10-05T09:12:00+09:00 [upload] p_7fa3… 2026-07-01_2026-09-30 a1b2c3d4e5f6 81KB stored 10.0.0.12`.
- `logs\uploads.jsonl`: 업로드·반입 1건 1줄(§3.8 `log_upload`).
- `logs\aggregate_YYYYMMDD.log`: 세대·소요·경고·stderr 끝.
- **묶음 내용(라벨·제목)·저장소 경로·토큰은 로그에 쓰지 않는다.** 키·크기·상태·IP 만.
- `log_keep_days` 지난 파일은 시작 시와 매일 0시에 삭제. `BaseHTTPRequestHandler.log_message` 는 덮어써서 콘솔 소음을 막고 위 로그로만 남긴다.

### 3.14 방화벽 차단 진단

결정 메모 10.4: 외부 도달 0건이면 '방화벽 차단 의심' 사유를 보인다. 서버는 클라이언트의 실패를 볼 수 없으므로 아래 사실들로 **의심**만 표시한다(확정 아님, 규칙을 바꾸지 않는다 — 관리자 권한이 필요하고 정책 우회 금지).

- 계측: 핸들러가 루프백이 아닌 출발지 요청 수를 센다(`external_requests`). 가동 후 `firewall_hint_after_min`(30분) 동안 0건이면 진단을 1회 돌린다. [진단] 버튼으로 즉시도 가능.
- 진단 항목(모두 비관리자로 읽힘 — 이 PC 실측):

| 항목 | 명령 | 해석 |
|---|---|---|
| 현재 망 범주 | `Get-NetConnectionProfile` → `NetworkCategory`(Public/Private/DomainAuthenticated) | Public 이면 인바운드 기본 차단일 가능성이 크다 |
| 프로필 상태 | `netsh advfirewall show currentprofile` → `State ON`·`Firewall Policy BlockInbound,…` | 켜져 있고 BlockInbound 면 허용 규칙이 있어야 들어온다 |
| 이 서버 실행 파일의 규칙 | `Get-NetFirewallApplicationFilter -Program "<sys.executable>" \| Get-NetFirewallRule` → 사용 중·인바운드 규칙의 Action·Profile | **Block 규칙이 있으면 확정에 가까운 의심**. 실측: 이 PC 에는 LM24 의 python.exe 에 대한 인바운드 Block(Public) 규칙 2개가 있었다(첫 실행 때 Windows 보안 경고에서 '취소'하면 생기는 규칙과 같은 모양) |
| 포트 규칙 | `Get-NetFirewallPortFilter` | 실측: 비관리자는 "Access is denied" → 조회하지 않는다 |

- 결과는 `run\firewall_diag.json`·`/api/status.firewall_hint` 와 콘솔에 한국어로: "다른 PC 에서 들어온 요청이 30분 동안 0건입니다. 이 PC 의 방화벽에 이 프로그램(python.exe)을 막는 규칙(공용 네트워크)이 있습니다. 사내 IT 에 'TCP 9310 인바운드 허용' 또는 이 프로그램 허용을 요청하세요. 그동안 팀원은 공유폴더로 보낼 수 있습니다(§5)." 경로는 콘솔에만 보이고 API·로그에는 쓰지 않는다.
- 클라이언트 쪽 짝: hello 가 `timeout` 이면 "방화벽·망 분리 의심", `refused` 면 "서버 꺼짐·포트 다름"(§2.9) — 두 쪽 문구가 같은 원인 후보를 가리킨다.

### 3.15 LM24 와의 공존

- 같은 PC 에서 LM24 팀 서버가 9310 을 쓰고 있으면 LM27 은 9310 을 열 수 없다. §3.4 가 원인을 "LM24 팀 서버"로 이름 붙이고 대체 포트를 제안한다. 팀원 LM27 은 `team.server_alternates` 에 `"10.115.147.68:19310"` 같은 대체 주소를 넣으면 기본 주소(9310, 사용자 지시로 고정)를 그대로 둔 채 hello 로 LM27 서버를 찾아 보낸다(§2.9).
- LM27 클라이언트는 hello 로 LM24 서버를 알아보고 **절대 POST 하지 않는다.** LM24 클라이언트가 LM27 서버에 `/api/upload` 를 보내면 410 + 한국어 사유.
- LM24 저장소(`teamdata\<이름>\member.json`)를 읽거나 변환하지 않는다(동결).

---

## 4. 팀 취합 산식

### 4.1 기호

- 사람 p(연결된 person_key 들을 합친 하나), 그 사람의 현재 묶음 집합 B_p(`current.json` 이 가리키는 기간별 묶음), 달 m, 일자 d, 단위업무 u, 역할 r(u), 과제 j(r), 영역 k(j), 꼬리표 τ ∈ {regular, extended, night, holiday}.
- env_b(d, τ): 묶음 b 의 `envelope_daily` 값(분). alloc_b(d, u, τ): `alloc_daily` 값(분, 없으면 0).
- W(m): 서버 레지스트리 달력의 그 달 평일 수(주말·공휴일·회사 휴무 제외). D = `calendar.std_day_min` = 480.
- 모든 합은 **정수 분**으로 하고, MM·비율은 마지막에 한 번 나눈다. 반올림은 화면 표시 때만(소수 2자리).

### 4.2 입력 정리

```python
def load_people(store) -> dict[str, Person]:
    roster = read_json(store / "roster.json", {})
    reg = store.registry()
    by_key = {}
    for pk in list_member_dirs(store):                      # ^p_[0-9a-f]{12}$ 인 폴더만
        cur = read_current(store, pk)                       # 깨지면 .bak → 재구성(§3.8)
        bundles = {}
        for per, ent in cur.items():
            raw = read_bytes(store.member(pk) / "bundles" / ent["file"])
            if sha256_hex(raw) != ent["sha256"]:            # 저장 후 변조·손상
                warn(f"{pk} {per}: 저장본 sha 불일치 — 이 묶음 제외"); continue
            try:
                obj = READERS[major_of(raw)](raw)          # MAJOR 별 읽기 함수(read_v1)
            except Exception as e:                          # 한 묶음 때문에 팀 취합을 잃지 않는다
                warn(f"{pk} {per}: 해석 실패({type(e).__name__}) — 이 묶음 제외"); continue
            bundles[ent["sha256"]] = obj
        by_key[pk] = Person(pk, bundles)
    return merge_links(by_key, roster, reg)                 # roster.links · 같은 member_id · self_peer_key(같은 pepper_id) → 대표 키로 묶음 합침
```

한 사람의 묶음 하나가 깨져도 그 묶음만 빠지고, 한 사람이 깨져도 팀 취합은 계속된다(LM24 `load_members` 방어 계승 — BOM 하나·객체 아닌 JSON 하나로 취합 전체가 죽던 결함). 빠진 것은 `warnings` 에 남는다.

### 4.3 기간 겹침 — 사람·달마다 묶음 하나

```python
def covered_workdays(b, m) -> int:
    lo = max(b.period.from_, first_day(m)); hi = min(b.period.analyzed_until.date(), b.period.to, last_day(m))
    return count(d for d in days(lo, hi) if is_workday(d))          # 서버 달력 기준

def pick_month_sources(bundles) -> dict[str, str]:                 # m → sha
    cand = defaultdict(list)
    for sha, b in bundles.items():
        for m in b.period.months: cand[m].append(sha)
    return {m: max(shas, key=lambda h: (covered_workdays(bundles[h], m), bundles[h].built_at_utc, h))
            for m, shas in cand.items()}
```

- 규칙: 그 달을 **더 많이 덮는 묶음** → 같으면 **나중에 만든 묶음**(`built_at` 을 UTC 로 바꿔 비교) → 같으면 sha 사전순 큰 쪽(결정적).
- 한 (p, m) 은 정확히 한 묶음에서만 읽는다. 서로 다른 묶음의 같은 달을 섞지 않는다(이중 계상·단위업무 ID 불일치 방지).
- 원형 실측(스크래치, 검증 달력): 7–9월 묶음 A(10/1 빌드)와 9–11월 묶음 B(10/5 까지 분석, 10/5 빌드)가 9월을 겹칠 때 — 9월은 둘 다 평일 20일을 덮어 동률 → 나중 빌드 B 선택. 단순 합 **2.279MM** → 선택 후 **1.128MM**(한 번만). 10월은 B 만, 덮는 평일 2/20(10/5 대체공휴일 제외)로 부분월.
- 어떤 달에서도 선택되지 않은 현재 묶음은 지우지 않고 `/api/members` 에 `used_months: []`("사용 안 됨")로만 보인다. 치우기는 팀장이 `/admin` 에서 한다(`PATCH /api/members/<key>` 의 `drop_period`). `history_keep` 은 같은 기간의 옛 묶음(현재가 아닌 것)에만 적용된다.

### 4.4 사람별 월 수치

src = pick(p, m), b = 그 묶음.

- 봉투: `E(p,m,τ) = Σ_{d∈m} env_b(d,τ)`, `E(p,m) = Σ_τ E(p,m,τ)`
- 귀속: `A(p,m,u,τ) = Σ_{d∈m} alloc_b(d,u,τ)`
- 미귀속: `U(p,m) = E(p,m) − Σ_u Σ_τ A(p,m,u,τ)` (≥ 0 이 업로드 검증에서 보장됨)
- 투입 MM: `MM(p,m) = E(p,m) / (D × W(m))` — 1.0 초과 허용, 자르지 않는다.
- 계층 MM: 단위업무 u → 역할 r(u) → 과제 j(r) = `resolve_project(role.project_id)`(§3.10 병합 사슬) → 영역 k(j). 임의 묶음 x 에 대해 `MM(p,m,x) = Σ_{u∈x} Σ_τ A(p,m,u,τ) / (D × W(m))`. 과제의 영역은 **서버 레지스트리 값**을 쓴다(묶음의 `projects[].domain` 은 레지스트리에 없을 때만). 역할이 레지스트리 과제가 아니라 `proposal_id` 를 가리키면 그 제안의 `domain_guess`(없으면 `UNC`)로 계상하고 "제안 과제" 표시를 단다. 과제도 제안도 없는 역할은 `UNC`(미분류).
- 초과: `OT(p,m) = E(p,m,extended) + E(p,m,night) + E(p,m,holiday)`(분) — 화면은 시간으로. 꼬리표별 따로도 보인다.
- 가용: `avail(p,m) = covered_workdays(b,m) − absence_days(b,m)`(확인된 부재만, `summary.months[].absence_days`). `load(p,m) = E(p,m) / (D × avail(p,m))`, avail ≤ 0 이면 null(0% 로 넣지 않음).
- 기간 합: `MM(p,·) = Σ_m MM(p,m)`, `load(p,·) = Σ_m E(p,m) / (D × Σ_m avail(p,m))`.
- 부분월: `covered_workdays < W(m)` 이면 "부분월(c/W 평일)" 표시. 1MM 분모는 그 달 전체 평일 그대로(부분월을 부풀리지 않는다).
- 묶음이 없는 달은 0 이 아니라 "자료 없음" — 월 평균·추이에서 제외하고 빈칸으로 그린다.

### 4.5 팀 집계와 사람별 측정 품질

- 영역별 투입: `TeamMM(k,m) = Σ_p MM(p,m,k)`, 미귀속 `TeamMM(UNATTR,m) = Σ_p U(p,m)/(D×W(m))`.
- 과제×인원, 역할(분야×기능)·업무 유형 분포: 같은 식으로 x 만 바꾼다. 분포 비율은 귀속분 기준(`Σ_x` 분모에서 미귀속 제외), 미귀속은 별도 막대.
- 팀 전체: `TeamMM(m) = Σ_p MM(p,m)`.
- **사람별 측정 품질**(묶음 `quality`): 서버는 그 사람의 선택된 달 묶음들의 `quality.grade` 중 가장 나쁜 것을 그 사람의 등급으로 쓰고, 이유 코드·PC 표·커버리지 표를 그대로 사람 상세에 보인다(값 해석은 바꾸지 않음).
  - `unreliable` 인 사람은 팀 **합계**(영역별 투입·팀 전체 MM)에는 포함하되 그 몫을 빗금으로 구분 표시한다(빼면 팀 투입이 과소 보고된다).
  - 팀 **비교 집계**(평균·순위·분포 비율·사람 간 비교 막대)에서는 제외하고 별도 표에 회색으로 둔다(LM24 D5(b) 계승: 수집 실패를 '낮은 로드'로 읽지 않게).
  - grade 가 빈 값·모르는 값이면 unreliable 로 간주하지 않는다(LM24 `norm_coverage` 계승).
- "산식 설정 상이"(§2.6) 사람은 배지만 단다(계산은 서버 달력으로 통일).

### 4.6 간트(담당자 × 영역/과제/역할, 다월)

결정 메모 10.2 를 따른다.

- **행 계층 기본 = 담당자 → 업무 영역 → 과제 → 역할 업무**. 피벗 토글로 **업무 영역 → 과제 → 역할 업무 → 담당자**. 행 = 그 계층 마디, 막대 = 그 마디에 속한 단위업무들.
- 막대 한 개 = 단위업무 하나: 옅은 **리드타임 띠**(`gantt_spans` 의 lead 구간 = 의뢰~보고, 근거 없으면 첫~마지막 근거) 위에 진한 **투입 밀도 칸**(주 단위).
- 행 끝에 **투입 h · 병행도 · 리드타임**.

```python
def active_spans(days: list[date], gap: int = 2) -> list[tuple[date, date]]:
    """alloc 이 있는 날들을 정렬해, 사이 빈 날이 gap 이하이면 한 구간으로 잇는다(결정적). 묶음의 active 와 비교(§2.3.2)."""
    out = []
    for d in sorted(set(days)):
        if out and (d - out[-1][1]).days <= gap + 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out

def density(p, u) -> dict[str, int]:            # ISO 주(월요일 시작, 근무 시간대 날짜) → 분
    return {iso_week(d): Σ_τ alloc(p, d, u, τ) for d in alloc_days(p, u)}   # 같은 주는 합산

def parallel(p, d) -> int:                       # 그 날 투입이 있는 단위업무 수
    return len({u for u in units(p) if Σ_τ alloc(p, d, u, τ) > 0})

def unit_parallel(p, u) -> float:                # 그 단위업무 투입일들의 평균 병행도(소수 1자리)
    ds = alloc_days(p, u); return round(sum(parallel(p, d) for d in ds) / len(ds), 1) if ds else 0.0
```

- 밀도 칸의 진하기는 고정 단계 `[0, 120, 360, 720, 1200]`분(주당)으로 5단계 — 사람·과제 사이에서 비교 가능하게(상대 척도 금지).
- 역할·과제·영역 행의 끝 수치: 투입 h = 소속 단위업무 alloc 합 ÷ 60, 병행도 = 소속 단위업무 투입일 평균 병행도, 리드타임 = 소속 lead 띠의 합집합 길이(일).
- **막대 길이는 투입이 아니다**(첫~마지막 근거 범위). 투입은 행 끝·툴팁·상세에 `effort_min` 으로 따로 표시.
- 단위업무의 월 소속: 그 unit 의 alloc 이 있는 달. 서로 다른 묶음에서 선택된 달들에 같은 `unit_id` 가 나오면 같은 업무로 합친다(lead 띠 = 가장 이른 시작~가장 늦은 끝, active·밀도 = alloc 합집합으로 다시 계산, title·role 은 가장 늦은 달 묶음의 값). R-4(unit_id 안정성)가 깨진 경우는 두 막대로 보이며, 같은 역할·겹치는 기간·같은 제목이면 `warnings` 에 "단위업무 ID 불안정 의심"을 남긴다(자동 병합하지 않음).
- 기간이 24개월을 넘으면 최근 24개월 창 + "앞 N개월 생략" 표기(LM24 계승).
- 막대·행 클릭 → `/api/team/detail?person=<person_key>&role=<role_id>`:

```json
{"person": {"i": 0, "label": "팀원A"}, "role": {"role_id": "r_5c0d11", "project_id": "P-0007", "project_label": "과제A",
 "domain": "DEV", "field": "회로", "function": "설계"},
 "workflow": {"steps": [{"no": 1, "type": "의뢰수신", "label": "요청 접수", "n": 5, "median_min": 20,
                         "agent_grade": "상", "subagent": "적합", "why": ["digital_io"]}], "edges": [[1, 2, 5]]},
 "units": [{"unit_id": "u_3e9a01c2d4", "title": "전원부 검증", "start": {"kind": "S1i", "at": "…"}, "end": {"kind": "E1o", "at": "…"},
            "grade": "B", "status": "closed", "lead_time_h": 150.5, "effort_min": 1260, "parallel": 1.8,
            "spans": [["2026-07-03", "2026-07-09", "lead"], ["2026-07-03", "2026-07-03", "active"], ["2026-07-08", "2026-07-09", "active"]],
            "density": {"2026-W27": 300, "2026-W28": 960}}],
 "agentic": {"matches": [{"agent_id": "AG003", "name": "문서 초안 작성", "step_type": "문서작성", "grade": "상"}]}}
```

### 4.7 agentic 취합

- 매칭: `agent_id` 별로 {사람 수, 역할 수, 단위업무 수, 관련 투입 MM}. **관련 투입은 묶음이 적은 숫자를 믿지 않고** 매칭에 연결된 `units` 의 alloc 을 서버가 다시 합쳐 구한다(같은 단위업무가 여러 에이전트에 걸리면 각 에이전트에 전부 표시하되 팀 합계에서는 한 번만 — "중복 포함" 표기). LM24 의 'Copilot 판정 대체 가능 MM(≈)' 같은 추정치는 만들지 않는다.
- 새 니즈: `(step_type, ukey(label))` 로 묶어 {사람 수, 월 빈도 합, 관련 투입 MM, 등급 분포}. 같은 step_type 의 라벨 변형은 묶지 않고 나란히 보인다(자동 이름 병합 금지 — 팀장이 레지스트리 카탈로그로 승격).
- 서브에이전트: 역할별 `fit` 분포와 제안 체인 목록.

### 4.8 불변식(취합 때 assert → 위반은 `warnings` + 대시보드 상단 배지, 산출은 계속)

| 번호 | 식 | 비고 |
|---|---|---|
| I1 일 보존 | 모든 (p, d, τ): Σ_u alloc ≤ env, 차 = 미귀속 | 업로드 때 422 로 이미 막힘. 취합 때 재확인 |
| I2 개인=팀 | `MM(p,m)` == 묶음 `summary.months[m].mm` (\|Δ\| ≤ 1e-9) | 묶음의 `calendar_version` 이 서버와 같을 때. 다르면 `calendar_mismatch` 배지 + 두 값 모두 표시 |
| I3 계층 보존 | Σ_k MM(p,m,k) + U(p,m)/(D×W(m)) == MM(p,m) | |
| I4 팀 합 | Σ_p MM(p,m) == TeamMM(m) | |
| I5 월 단일 출처 | 각 (p,m) 의 출처 묶음은 정확히 1개 | §4.3 |
| I6 effort | 각 unit 의 `effort_min` == Σ 그 unit 의 alloc(그 묶음 안) | 업로드 검증과 같음 |
| I7 간트 | 각 unit 의 active 구간 == `active_spans(alloc 일자, gantt_merge_gap_days)` | 다르면 서버 값 사용 + `gantt_mismatch` |

### 4.9 `team_data.json`(대시보드 데이터)

```json
{"schema": "lm27.teamdata/1", "gen": 12, "built_at": "…", "registry_version": 7, "calendar_version": "kr-2026.3",
 "months": ["2026-07", "2026-08", "2026-09"],
 "workdays": {"2026-07": 22, "2026-08": 20, "2026-09": 20},
 "people": [{"i": 0, "person_key": "p_…", "label": "팀원A", "quality": "reliable", "flags": [],
             "months": [{"m": "2026-07", "mm": 1.09, "env_min": 11520, "by_tag": {…}, "avail_days": 21.0,
                         "load_pct": 114.3, "partial": null, "src12": "a1b2c3d4e5f6"}]}],
 "domains": [{"code": "DEV", "by_month": {"2026-07": {"mm": 3.1, "by_person": [[0, 0.8]]}}, "total_mm": 9.2}],
 "projects": [{"project_id": "P-0007", "domain": "DEV", "label": "과제A", "proposal": false, "total_mm": 4.1,
               "by_person": [[0, 1.2]]}],
 "roles": […], "activity_types": {…}, "unattributed": {"by_person": [[0, 0.05]]},
 "gantt": [{"person": 0, "domain": "DEV", "project_id": "P-0007", "role_id": "r_5c0d11",
            "row_end": {"effort_h": 21.0, "parallel": 1.8, "lead_days": 7},
            "units": [{"unit_id": "u…", "title": "전원부 검증", "spans": [["2026-07-03", "2026-07-09", "lead"]],
                       "density": {"2026-W27": 300, "2026-W28": 960}, "effort_min": 1260, "parallel": 1.8, "grade": "B", "status": "closed"}]}],
 "agentic": {"matches": […], "needs": […], "subagents": […]},
 "quality": {"excluded_from_comparison": [2], "pcs_matrix": […]},
 "warnings": ["…"]}
```

사람은 정수 인덱스 `i` 로만 참조한다(라벨을 키로 쓰지 않는다 — `by_person` 도 `[i, 값]` 쌍 목록).

---

## 5. 오프라인 대체(공유폴더·USB)

서버에 닿지 않는 망(클라우드PC 등)에서 쓴다. 내용·검증은 HTTP 와 완전히 같다.

### 5.1 클라이언트 — [파일로 내보내기]

```python
def export_to_dir(item, folder) -> str:
    folder = os.path.expandvars(str(folder).strip().strip('"').strip("'"))
    if not os.path.isabs(folder): raise UserError("절대경로나 \\\\서버\\공유 형식이어야 합니다")   # 상대경로·오타가 엉뚱한 폴더를 만들던 LM24 결함
    if not os.path.isdir(longp(folder)): raise UserError("폴더가 없거나 이 망에서 닿지 않습니다")
    raw = read_bytes(item.path)
    if sha256_hex(raw) != item.meta["sha256"]: raise UserError("묶음 파일이 미리보기 이후 바뀌었습니다 — 다시 만드세요")
    name = f"lm27_team_bundle_{item.meta['person_key']}_{item.meta['period_key']}_{item.meta['sha256'][:12]}.json"
    dst = os.path.join(folder, name)
    atomic_write(longp(dst), raw)                                     # .part → replace: 반쪽 파일이 서버에 반입되지 않게
    if sha256_hex(read_bytes(longp(dst))) != item.meta["sha256"]:     # 되읽어 확인
        raise UserError("저장 확인 실패 — 다시 시도하세요")
    mark(item, "exported", dst_display=folder)                        # '전달됨' 이 아니다 — 서버 반영은 /api/members 로 확인
    return dst
```

- 폴더 기본값 `team.offline_dir`(비면 화면에서 입력, 바탕화면 제안). USB 도 같은 함수. 파일 하나만 쓰므로 폴더 안에 하위 폴더를 만들지 않는다(260자·`makedirs` 함정 회피).
- 개인 HTML 보고서·원문·`data\keys\` 는 함께 내보내지 않는다(팀 묶음 하나만 — LM24 `push_reports` 의 개인 보고서 동반 복사 폐기).
- 나중에 서버에 닿으면 `/api/members` 의 자기 `sha12` 로 `exported → delivered` 를 맞춘다.

### 5.2 서버 — 반입

- `<store>\inbox\`(항상) + `team_server.inbox_dirs`(선택, 예: 팀 공유폴더)를 `inbox_poll_s`(30s)마다 확인한다.
- 파일 이름 화이트리스트: `^lm27_team_bundle(_[0-9A-Za-z_\-]{1,80})?\.json$` 만(`re.fullmatch` — LM24 `NAME_OK` 의 `$` 개행 통과 결함 방어). 크기 ≤ `max_body_mb`. `.part`·숨김·0바이트·1분 이내 수정(복사 중) 파일은 건너뛴다.
- 내용은 `ingest_bytes(raw, source="inbox:<파일명>")` — HTTP 와 같은 검증·원자 교체·`stale_kept` 규칙. **신원은 파일명이 아니라 본문의 person_key** 로 정한다(대리 반입이어도 원저자 유지, LM24 대리 업로드 원칙 계승 — 본문을 고치지 않는다).
- `<store>\inbox\` 의 파일: 성공 → `inbox\done\`, 실패 → `inbox\rejected\` + `<파일>.reason.json`(`{"code","error","detail"}`).
- `inbox_dirs` 의 파일: 남의 폴더일 수 있으므로 **옮기거나 지우지 않는다.** `run\inbox_seen.json` = `{sha256: {"file","at","result"}}` 로 한 번 처리한 것은 건너뛴다.
- 서버를 띄우지 않은 상태의 반입: `lm27 team-import <파일|폴더> [--store DIR]` — 저장소 잠금이 비어 있으면 직접 `ingest_bytes` 후 재취합, 서버가 실행 중(잠금 점유)이면 파일을 `inbox\` 로 **복사만** 하고 "서버가 30초 안에 반영합니다" 안내.

### 5.3 레지스트리 오프라인

- 서버: `publish_dir` 가 설정돼 있으면 레지스트리가 바뀔 때마다 `<publish_dir>\lm27_registry.json` 을 원자적으로 게시(pepper 포함 — 그 폴더 접근 권한이 곧 pepper 접근 권한이 된다, 미결 3).
- 클라이언트: 서버에 닿지 않고 `team.offline_dir\lm27_registry.json` 이 있으며 그 `version` 이 캐시보다 크면 그것을 캐시로 채택(형식 검증 통과 시, pepper 는 §2.3.3 처럼 분리 저장).

---

## 6. LM24 방어 패턴 계승표

근거 파일: `D:\배포\loadmon24_v4\teamserver.py`·`teamup.py`·`aggregate.py`·`ui\app.py`(포트 도우미)·`collect\Register-Samplers.ps1` (읽기 전용으로 확인).

| LM24 (근거) | 무엇을 막았나 | LM27 구현 |
|---|---|---|
| `teamserver.NAME_OK` **fullmatch** 화이트리스트 | 임의 파일·HTML 업로드, `'x.csv\n'` 이 `$` 를 통과해 500 | 업로드는 단일 JSON 본문(파일명 없음). 정적 파일 고정 사전, 반입 파일명 정규식 `fullmatch` |
| `MAX_BODY` + 초과 본문 소진(64MB 까지) 후 응답 | RST 로 오류 응답 유실·허위 Content-Length | §3.8 `drain` 동일 + 413(원형 실측: 3MB 초과 본문에 413 이 클라이언트에 도착) |
| `OWNER_LOCKS` 사람 단위 잠금 | 같은 사람 동시 업로드가 서로 파일을 지움 | `store.person_lock(pk)`(원형 실측: 9건 동시 업로드 후 current 일관) |
| `_save` 의 `.part/.bak` 원자 교체·원복 | 반쪽 저장(파일 옛것·member 새것) | 불변 묶음 + `current.json` 단일 교체(되돌릴 일이 생기지 않는 구조) |
| `AGG_LOCK` 취합 직렬화 | 동시 취합이 산출물을 밟음(3명 동시 업로드 실측) | 단일 워커 + 디바운스 + 세대 디렉터리 + 포인터 교체 |
| `run_aggregate` 의 '마지막 줄 JSON' 파싱 | 안내 줄 하나로 메모가 엉뚱해짐 | 하위 프로세스가 `result.json` 을 쓰고 서버는 그것만 읽음 |
| `norm_owner`·`owner_problem`(NFKC·Cc/Cf·예약어·접두) | 같은 사람 두 폴더·CON 폴더·산출물 접두 충돌 | person_key 형식 강제(폴더명은 서버가 만듦), self_label·자유 문자열은 NFKC·Cc/Cf 제거 |
| `esc()`·숫자 강제(`fnum`·`fint`) | 저장형 XSS·저장형 DoS('abc' 한 칸이 취합 rc=1) | 스키마 검증으로 **거절**(조용히 고치지 않음) + 렌더 시 textContent + JSON 섬 `<` 전면 인코딩 |
| 정적 보고서 CSP `sandbox` | 이스케이프 누락 시 API 호출 | 동일 + 대시보드 CSP `default-src 'self'` |
| `/api/shutdown` 루프백 전용 | 팀원 누구나 서버 종료 | 동일 |
| pid·token 파일로 '내 서버' 증명 | 남의 프로세스가 신원 흉내(반박 검증 재현) | instance_id(`server.json`) + 리스너 pid 대조 |
| `_share_root`(받는 곳 = 보는 곳) | 서버 저장 위치와 취합 위치가 갈라져 업로드가 안 보임 | 서버·취합기 모두 같은 `--store` 하나 |
| `_cfg_port`(URL 문자열에서 포트 정규식) | 설정 해석 불일치 | `server_host`·`server_port` 분리 키 |
| `ui/app._listeners`(netstat, `-p TCP` 금지, ascii 디코드, None≠빈 목록) | IPv6 리스너 누락·'모름'을 '없음'으로 | 동일 |
| `_proc_info`(다른 계정이면 NULL → '확인 불가') | 우리 서버를 남의 것으로 단정 | 동일 |
| `_bind_free` SO_REUSEADDR 금지 | 살아 있는 리스너 위 덧바인드 | `allow_reuse_address=False` + `SO_EXCLUSIVEADDRUSE`(재실측) |
| `_suggest_port`(임시 범위·대시보드 대역 회피) | 9310 이 언제든 뺏김 | 동일 + `D:\배포\LM26` 포트 8765~8767 회피 + 기본 후보를 임시 범위 밖 19310~ 로 |
| `_dyn_range`·`_reserved_ranges`(netsh, 1회 캐시) | 원인 불명 '시작 실패' | 동일 + 7종 분류(10013 이 배타 점유일 수도 있음을 실측) |
| `teamup.blockers` 를 **준비 시점**에 | 며칠 뒤 서버망에서야 실패를 앎 | 빌드 시 `blockers` + 미리보기 버튼 비활성 |
| `teamup` 대기 → 버튼(자동 전송 실패가 조용히 사라짐) | 분석 망에서 매번 실패 | 승인 + 대기열 상태 기계 + [수집] 끝 자동 전송 |
| `upload_one` — 이름을 고칠 때도 원저자 유지 | USB 대리 업로드 시 이름 바뀜 | 신원 = 본문 person_key, 본문은 절대 고치지 않음 |
| `upload_one` 이 `uploaded_at`·`uploaded_from` 을 본문에 덧씀 | (결함) 미리보기 ≠ 실전송, 호스트명 축적 | 보내는 시점 정보는 HTTP 헤더로만 |
| `ping` 이 `/api/team` 으로 도달 확인 | (결함) 다른 앱도 '닿음' | `/api/hello` 신원 확인 + 사유 분류 |
| `to_folder` 절대경로 검사·`longp`·한 단계 `mkdir`·member.json 마지막 | 상대경로 오타 폴더·260자·반쪽 저장 | 단일 파일 원자 쓰기 + 되읽기 확인 + `longp` |
| `push_reports`(개인 HTML 을 공유폴더로) | (위험) 원문 포함 보고서 반출 | 폐기 — 팀 묶음 하나만 |
| `arg()` — `--to-folder --json` 이 `--json` 폴더를 만들던 결함 | 인자 해석 오류 | CLI 는 `argparse`(값 필수 인자 `required`/`nargs` 명시) |
| `aggregate.py` 의 `sys.path.insert(ROOT)` | 동봉 파이썬 `_pth` 때문에 import 가 조용히 실패 | 단일 진입점이 ROOT 를 넣는다 + `except ImportError` 로 기능을 삼키는 코드 금지(lint) |
| `load_members`(utf-8-sig, 한 명 깨져도 계속) | BOM·형식 하나로 취합 전체 사망 | §4.2 동일(묶음·사람 단위 격리) |
| `norm_coverage`(모르는 등급은 unreliable 아님) | 구판 자료를 측정 불충분으로 오분류 | §4.5 동일 |
| `coverage.unreliable` 비교 제외(D5(b)) | 수집 실패를 낮은 로드로 오독 | 합계 포함(빗금)·비교 제외로 세분 |
| `cfg_mismatch`(과반, 동수·2명 미만이면 표시 없음) | 분모 다른 사람 비교 | 판·달력 상이 배지, 같은 규칙 |
| `mm_scale` 재스케일 | 행 합 ≠ 공식 투입 | **폐기** — 불일치는 업로드 422(I1·I6), 조용히 맞추지 않음 |
| 정제본이 원본보다 오래되면 원본 사용(mtime) | 옛 정제본이 새 결과를 덮어 MM 몇 배 | 같은 기간 옛 `built_at` 묶음은 `stale_kept`(§3.8) |
| `resolve_chain`·`_AliasMap`(사슬·순환·정규화) | 같은 과제 두 줄 | 레지스트리 `merged_into` 사슬 + ukey 정규화(§3.10) |
| `visual_report` 의 `<` → `\u003c`, pid 붙은 tmp | 저장형 XSS, 동시 취합 tmp 충돌 | 동일 + 세대 디렉터리(열린 파일 위 replace 불필요) |
| `/api/team` 이 root·store·pid·token 반환, 업로드 응답이 host·root | (결함) 서버 경로·증명 토큰·호스트명 노출 | hello·members 에 경로·pid·토큰·호스트명 없음 |
| `signals_*.csv` 원문 반출, 보고서 'raw 단서' 절이 그 경로 노출 | (결함) 팀 서버에 원문 축적 | 집계·라벨 전용 묶음 + 카나리아 관문 |
| `GET /refresh` 가 재취합 실행 | (결함) 링크 하나로 누구나 부하 유발 | `POST /api/aggregate` 관리 권한 |
| `Register-Samplers` XML 정의(PT0S·IgnoreNew·RestartOnFailure·배터리·InteractiveToken) | 3일 뒤 조용히 멈춤(PT72H 실사고) | 동일 |
| `Register-Samplers` 의 `WorkingDirectory = $root` | (결함) 에이전트가 프로그램 폴더를 잡음 | `WorkingDirectory = agent\<id>\`, 실행 파일도 사본 |
| 판 공통 작업·뮤텍스 이름 `LoadMonitor24-Sampler` | 다른 폴더 샘플러를 '살아 있음'으로 오판 | `LM27-<install_id>` + 생존 4조건(§1.6.5) |
| schtasks 폴백 XML 즉시 삭제 | SID·경로가 든 파일 잔존 | 동일 |

---

## 7. 설정 키(이 문서 소관 — 단일 설정 레지스트리에 그대로 등록)

### 7.1 클라이언트·번들·에이전트

| 키 | 형 | 기본값 | 쓰는 곳 |
|---|---|---|---|
| `team.server_host` | str | `"10.115.147.68"` | 팀 서버 IP(화면에서 변경). **기본값 바이트 고정(관문)** |
| `team.server_port` | int | `9310` | 팀 서버 포트(화면에서 변경). **기본값 고정(관문)** |
| `team.server_alternates` | list[str] | `[]` | 대체 주소 `"host:port"` 목록 — 기본 주소가 LM27 이 아니거나 안 닿을 때 순서대로(§2.9) |
| `team.upload_token` | secret | 없음 | 선택적 업로드 토큰(팀 앱 공유 비밀 — 계정 비밀번호 아님). **config.json 이 아니라 `data\keys\secrets.json` 에 저장**, 설정 레지스트리에는 '비밀 등급' 키로만 등록(값 표시·내보내기 금지) |
| `team.self_label` | str | `""` | 팀 화면 표시 라벨(본인이 직접 입력) |
| `team.member_id` | str | `""` | 레지스트리 구성원 ID(화면에서 목록 선택, 선택 사항) |
| `team.unit_title_mode` | str | `"label"` | `label`·`generic`(§2.5) |
| `team.share_unknown_apps` | bool | `false` | 미상 프로그램 라벨링 제안(`catalog_proposals`)을 팀 묶음에 싣기 |
| `team.auto_send` | bool | `false` | 빌드 직후 승인 없이 전송 |
| `team.retry_schedule_s` | list[int] | `[60,300,900,3600,10800,21600]` | 재시도 간격 |
| `team.retry_max_attempts` | int | `50` | |
| `team.max_bundle_mb` | int | `8` | 빌드 상한 |
| `team.connect_timeout_s` | int | `4` | hello |
| `team.upload_timeout_s` | int | `120` | POST |
| `team.use_system_proxy` | bool | `false` | |
| `team.allow_public_host` | bool | `false` | false 면 `server_host`·대체 주소는 사설 IPv4(10/8·172.16/12·192.168/16)·루프백만 허용, 호스트 이름 불가 |
| `team.offline_dir` | str | `""` | 오프라인 내보내기·레지스트리 파일 폴더 |
| `team.registry_refresh_h` | int | `12` | |
| `team.sent_keep` | int | `20` | sent 보관 수 |
| `person.work_tz_offset_min` | int | `540` | 근무 시간대(고정 offset) |
| `bundle.segment_max_records` | int | `50000` | |
| `bundle.segment_max_raw_mb` | int | `16` | |
| `bundle.warn_size_mb` | int | `300` | |
| `bundle.lock_timeout_s` | int | `30` | |
| `bundle.auto_alias_vdi` | bool | `true` | |
| `bundle.overlap_tolerance_min` | int | `10` | |
| `agent.sample_interval_s` | int | `60` | |
| `agent.harvest_interval_h` | int | `6` | 이벤트 로그 롤오버보다 짧게 |
| `agent.store_keep_days` | int | `400` | |
| `agent.heartbeat_stale_s` | int | `600` | |
| `agent.impl` | str | `"auto"` | `auto`(py → ps → none)·`py`·`ps` |
| `agent.harvest_wait_s` | int | `120` | |
| `agent.flush_interval_s` | int | `300` | 샘플 버퍼를 gzip 멤버로 덧붙이는 주기(§1.6.7) |
| `move.rename_retries` | int | `4` | |
| `move.stop_wait_s` | int | `15` | |

화면의 서버 주소 입력은 IP·포트 두 칸 + [연결 확인](hello 결과 문구 그대로) + 대체 주소 목록. 저장 전 검증: 포트 1~65535 정수, IP 는 `ipaddress.ip_address` 통과 + `allow_public_host` 규칙. 잘못된 값은 저장하지 않고 이유를 보인다. 설정 파일에 잘못된 값이 있으면 기본값으로 동작하고 `config_warnings` 에 표기. 기본값 되돌리기 버튼은 `10.115.147.68:9310` 으로 정확히 되돌린다.

### 7.2 서버

§3.2 표 전체(`team_server.*`).

---

## 8. 인터페이스 요약

### 8.1 CLI(`lm27 <명령>` = `python\python.exe <단일 진입점> <명령>`)

종료 코드: `collect` 는 COLLECTION §8.4(0 성공·2 부분·1 치명)를 따른다. 그 밖 명령은 0 성공 · 4 할 일 없음(0건 정상) · 2 사람 조치 필요 · 3 환경 실패(재시도 가능) · 1 내부 오류.

| 명령 | 하는 일 |
|---|---|
| `collect [--auto]` | §1.7 `collect_here` |
| `agent install [--only]\|status\|repair\|uninstall [--purge]` | §1.6 (`--only` = 설치 전용 진입점 §1.6.6) |
| `bundle status\|verify\|merge <dir>\|alias <pc_id> <logical>\|unalias <pc_id>\|redact` | §1.4·1.8·1.13·1.14·1.15 |
| `move-prepare` | §1.11 |
| `team build --from D --to D` | §2.7 |
| `team list` · `team preview <item>` · `team approve <item>` · `team send [<item>\|--all]` · `team drop <item>` | §2.7·2.8·2.9 |
| `team mask <unit_id> title\|detail\|none` · `team drop-need <need_id>` | §2.5 |
| `team export <item> --dir <폴더>` | §5.1 |
| `team ping [--host H --port N]` | hello 만(§2.9 판정 문구) |
| `team-server [--host H] [--port N] [--store DIR]` | §3 |
| `team-aggregate --store <dir> --gen N` | §3.9·§4(서버 하위 프로세스) |
| `team-import <파일\|폴더> [--store DIR]` | §5.2 |
| `team-firewall-diag [--store DIR]` | §3.14 |

### 8.2 파이썬 모듈 경계

| 모듈 | 공개 함수 |
|---|---|
| `lm27/util/fsx.py` | `canon_bytes`, `atomic_write`, `read_bytes`, `read_json`, `gzip_bytes`, `sha256_hex`, `longp`, `utcnow_iso` |
| `lm27/bundle/ids.py` | `identify_pc() -> PcIdentity(pc_id, id_source, install_id, agent_ver, kind_guess, tz)` |
| `lm27/bundle/lock.py` | `BundleLock(root, purpose, timeout_s)` |
| `lm27/bundle/segment.py` | `write_segment(...)`, `read_segment(path, expect_sha=None) -> Iterator[dict]`, `verify_segment(path) -> (ok, reason)` |
| `lm27/bundle/manifest.py` | `load_manifest`, `save_manifest`, `rebuild_manifest`, `adopt_orphans`, `add_tombstone` |
| `lm27/bundle/pcreg.py` | `ensure_pc_dir`, `load_pc`, `update_pc`, `record_probe(pcdir, key, ok, value, reasons, status)`, `verdict(history)`, `probe_bundle_location(root)` |
| `lm27/bundle/aliases.py` | `logical_map(root)`, `auto_alias(root, cfg)`, `record_alias`, `undo_alias` |
| `lm27/bundle/export.py` | `export_agent_streams(pcdir, ident, cfg)`, `read_store_since(ident, kind, src, cursor)` |
| `lm27/bundle/loader.py` | `iter_records(...)`, `bundle_status(root)`, `load_report()` |
| `lm27/bundle/merge.py` | `merge_bundle(root, other_data_dir) -> MergeResult`, `redact_rewrite_own(pcdir)` |
| `lm27/bundle/move.py` | `prepare_move(root, cfg) -> MoveLaunch`(PS 도우미 기동), `arrival_check(root) -> list[Missing]` |
| `lm27/agent/install.py` | `ensure_agent(ident)`, `agent_health(ident)`, `register_task(ident)`, `request_harvest_now(ident, wait_s)`, `uninstall(ident, purge)` (키·문맥은 PRIVACY `write_agent_subkeys`·`write_context_cache`) |
| `lm27/agent/main.py` | (에이전트 사본의 진입) `main(install_id)` |
| `lm27/team/schema.py` | `validate_team_bundle(obj, registry, side) -> list[Err]`, `TEAM_SPEC_V1`, `BYTES_GUARD`, `team_text(...)`, `active_spans(days, gap)` |
| `lm27/team/build.py` | `build_team_bundle(analysis, period, registry, pepper, overrides, cfg) -> (obj, audit)`, `build_and_queue(...)` |
| `lm27/team/queue.py` | `list_items()`, `approve(item)`, `send_due(cfg)`, `mark(item, state, msg)`, `reconcile_delivered(members)` |
| `lm27/team/client.py` | `hello(base, timeout) -> Hello`, `pick_target(cfg)`, `http_post(...)`, `fetch_registry(base, etag)`, `fetch_members(base)` |
| `lm27/team/server.py` | `serve(cfg) -> int`, `LM27HTTPServer`, 핸들러 |
| `lm27/team/store.py` | `open_store(cfg)`, `ingest_bytes(store, raw, *, source, claimed_sha, client, ip) -> IngestResult` |
| `lm27/team/aggregate.py` | `aggregate(store, gen) -> TeamData`, `pick_month_sources(bundles)`, `resolve_project(reg, id)`, `check_invariants(td)` |
| `lm27/team/report.py` | `render_team_report(td, share=False) -> str` |
| `lm27/team/portdiag.py` | `listeners(port)`, `proc_info(pids)`, `probe_identity(port)`, `diagnose_port(port, code, cfg)`, `suggest_port(port, cfg)`, `bind_test(port)`, `dynamic_range()`, `reserved_range_of(port)` |
| `lm27/team/firewall.py` | `firewall_diag(exe_path) -> dict` |
| `lm27/team/offline.py` | `export_to_dir(item, folder)`, `scan_inboxes(store, cfg)` |

### 8.3 PowerShell(`collect\agent\`·`collect\move\`, UTF-8 BOM + CRLF)

`agent.ps1 -InstallId <id>`(ps 구현 감독), `harvest.ps1 -InstallId <id> -Streams pc_session/pc.events,pc_file/pc.files,pc_file/pc.mru,pc_file/pc.recent`, `Register-Agent.ps1 -InstallId <id> -AgentVer <v> -Impl py|ps [-Remove] [-NoStart] [-DryRun]`, `Prepare-Move.ps1 -Root <경로> -WaitPid <pid> -Gen <n>`. 모든 스크립트는 `-TestNow`·`-OutDir` 주입 인자를 받아 실데이터 없이 시험 가능해야 한다(LM24 수집기 주입 파라미터 계승). 방화벽 진단은 파이썬이 `powershell -NoProfile -Command` 한 줄로 부른다(30초 시간 제한).

---

## 9. 시험 시나리오(관문 포함)

모든 시험은 `%TEMP%` 복제 트리에서 합성 자료로만 돈다(`assert ROOT != 실제 설치 경로`). 실제 메일·팀즈 수집 금지. 작업 스케줄러 시험은 이름 접두 `LM27T-` 로 등록하고 끝에 지운다.

### 9.1 번들·에이전트

| ID | 절차 | 기대 |
|---|---|---|
| B01 PC1→PC2→PC1 | 가상 pc_id 2개, 가상 에이전트 store 2개. PC1 내보내기 → PC2 내보내기 → PC1 store 에 레코드 추가 → PC1 내보내기 | `pcs\` 아래 폴더 2개, 어떤 폴더도 rename 없음(폴더 생성시각 불변), PC1 manifest 세그먼트 증가, 레코드 중복 0, 로더 레코드 수 = store 총합 |
| B02 커서 멱등 | 같은 PC 에서 내보내기 3회 연속 | 2·3회째 새 세그먼트 0 |
| B03 고아 편입 | 세그먼트 쓴 뒤 manifest 저장 전 강제 예외 | 다음 내보내기에서 고아 편입, 레코드 중복 0 |
| B04 manifest 손상 | manifest.json 을 쓰레기로, prev 도 삭제 | 자동 재구성, 세그먼트 수·커서·무덤표 일치, 화면 문구 1줄 |
| B05 세그먼트 변조 | 한 세그먼트 1바이트 변경 | 격리, 나머지 정상 로드, `load_report` 에 격리 1·레코드 추정치 |
| B06 동시 쓰기 | 두 프로세스가 동시에 `collect_here` | 하나는 대기 후 진행, seq 중복 0, 레코드 중복 0 |
| B07 VDI | 같은 kind=vdi·host_class·tz, 겹치지 않는 3세션 pc_id | 자동 별칭 1개 논리 PC. 두 세션 구간을 20분 겹치게 바꾸면 별칭 안 함 |
| B08 GUID 충돌 | 같은 pc_id, install_id 2개, pc_session 겹침 | `pc_id_collision` 플래그, 고착 판정이 (pc_id, install_id) 단위 |
| B09 UTC 클라우드 | offset 0 인 PC 레코드 + offset 540 PC | 일자 경계가 사람 시간대(540) 기준으로 같게 계산 |
| B10 store 정리 | 커서보다 앞선 store 파일 삭제 | manifest `gaps` 1건, 조용한 손실 없음 |
| B11 늦은 수확 | 6시간 뒤 수확된 '과거 시각' 이벤트가 오늘 파일에 추가됨 | (파일, 오프셋) 커서가 빠짐없이 내보냄(시각 커서였다면 놓쳤을 레코드 수 > 0 을 대조로 보임) |
| B12 에이전트 ROOT 독립 | (실 Windows, TEMP) 에이전트 기동 후 ROOT 이름 바꾸기 → 작업 다시 실행(로그온 모사) | 이름 바꾸기 성공, 에이전트 heartbeat 계속, 재실행도 성공(Action 이 ROOT 밖) |
| B13 이동 준비 | ROOT 의 python 이 화면 서버로 실행 중 → move-prepare | 화면 서버 종료, 이름 바꾸기 시험 성공, move_ready.json(세그먼트 목록 포함), 에이전트 heartbeat 계속 갱신 |
| B14 잠금 원인 | ROOT\data 안 파일을 다른 프로세스가 연 채 move-prepare | 실패 + Restart Manager 가 그 pid·이름 표시, 폴더 이름 원상 |
| B15 팀 서버 동거 | 같은 ROOT python 으로 팀 서버 실행 중 move-prepare | 멈추고 안내, [그래도 진행] 전에는 아무것도 종료하지 않음 |
| B16 작업 등록 | Register-Agent 를 2번, 옛 install_id 작업 1개 미리 생성 | `LM27T-<현재 id>` 하나만, Action = agent\<id>\ 아래 사본, WorkingDirectory = agent\<id>\, 남의 `LM27T-*`(다른 경로)·`LoadMonitor24-*` 보존 |
| B17 생존 복구 | heartbeat 를 20분 전으로 조작 | `ensure_agent` 가 재기동, 60s 안 hb_fresh |
| B18 사본 합치기 | 번들 복사본 A·B 에 각각 다른 세그먼트 추가 → merge 2회 | 합집합, 같은 sha 중복 0, 2회째 변화 0(멱등), person_key 다르면 거부 |
| B19 소급 가림 | A 에서 세그먼트 1개 가림 재작성 → 가리기 전 사본 B 와 merge | 무덤표의 옛 sha 는 들어오지 않음, 로더 결과에 가린 텍스트 0 |
| B20 도착 점검 | move_ready 목록 중 2개 파일을 지우고 PC2 첫 실행 | 표에 이름 2개·'없음', 분석은 나머지로 진행, 파일을 다시 넣으면 다음 실행에서 표가 사라짐 |
| B21 설치 전용 | `agent install --only` | 5초 안팎, 번들에 pc.json 만, seg 없음, 작업 등록됨, `observed_from` 이전 '미관측' |
| B22 PS 구현 | `agent.impl=ps` 강제 | PS 샘플러가 store 에 직접 쓰지 않고 동봉 파이프(`--mode append`)로만 기록, 같은 입력에서 py 구현과 같은 레코드(`id`·`doc_key` 일치) |
| B25 gzip 멤버 커서 | 일자 파일 마지막 멤버를 반쯤 잘라 둔 채 내보내기 → 잘린 부분을 마저 쓴 뒤 다시 내보내기 | 1회째는 잘린 멤버를 읽지 않고 오프셋을 그 앞에, 2회째에 그 멤버가 한 번만 들어옴(중복 0·누락 0) |
| B26 VDI 프로필 이동 | 같은 `agent\` 에서 MachineGuid 만 바꿔 에이전트 재시작 | `agent.json.pc_id` 갱신, 이후 기록이 `store\<새 pc_id>\`, install_id 유지 |
| B23 도착 경로 탐침 | `%OneDrive%` 를 TEMP 부모로 두고 ROOT 를 그 아래에 | `R-BUNDLE-ONEDRIVE`, 수집은 계속 |
| B24 제어문자 | 모든 소스 파일 바이트 검사 | 0x00–0x08·0x0B·0x0C·0x0E–0x1F 없음(LM24 BEL 결함) |

### 9.2 팀 묶음·대기열

| ID | 절차 | 기대 |
|---|---|---|
| U01 미리보기=실전송 | 빌드 → 미리보기 바이트 sha → 시험 서버 수신 바이트 sha | 셋 모두 같음, 응답 sha 동일 |
| U02 결정성 | 같은 분석 입력으로 2회 빌드(`built_at` 주입 고정) | 바이트 동일(원형 실측) |
| U03 **PII 카나리아(관문)** | 합성 페르소나에 카나리아 삽입: 형식이 맞는 가짜 전화·주민·계좌·카드(Luhn)·이메일·호스트명·Windows 사용자명·동료 표시명·`C:\`·UNC·사설 IP·URL·who_key(`w`+16hex)·로컬 키·pc_id·kid·MachineGuid 형식 GUID | 빌드 결과 바이트에 카나리아 0건, `team_text_rejected` 수 = 자유 문자열 삽입 수, 서버 재검사도 0건 |
| U04 금지 문자열 거절 | 빌더를 우회해 이메일이 든 묶음을 직접 POST | 422 `forbidden_content`, 저장 없음, 응답에 값 없음 |
| U05 대기·재시도 | 서버 꺼짐 → 보내기 | `retry_wait`, next_at 60s±10%. 서버 켬 → 다음 계기에 `sent` |
| U06 LM24 서버 | LM24 흉내 서버(`/api/whoami` root·`/api/team` 모양)를 기본 주소에 | `wrong_server`, POST 0회(서버 접근 로그로 확인), 응답 본문 기록 0 |
| U07 판 불일치 | hello `accepts={"2":0}` | `failed`, POST 0회 |
| U08 토큰 | 서버 토큰 설정, 클라이언트 토큰 없음/틀림/맞음 | auth_needed / 401 token_invalid → auth_needed / sent |
| U09 대체 | 같은 기간 미전송 항목이 있을 때 새 빌드 | 옛 항목 dropped(superseded) |
| U10 중복 전송 | 두 프로세스가 동시에 send | lease 로 1회만 POST, 그래도 겹치면 서버 already_have |
| U11 크기 | 9MB 묶음 | 빌드 blockers, 보내기 버튼 비활성 |
| U12 가림 | 단위업무 하나 `title`, 하나 `detail`, 니즈 하나 `drop` | 제목 generic, detail 의 peers·apps 비움, 니즈 사라짐, **envelope·alloc·effort 불변**, 서버 I2·I3 통과 |
| U13 대체 주소 | 기본 주소 = LM24 흉내, 대체 1 = 응답 없음, 대체 2 = LM27 | 대체 2 로 전송, `last_target=alt2`, `team.server_host`/`port` 설정 불변 |
| U14 클라우드→사내 | 클라우드 모사(서버 안 닿음)에서 빌드·승인 → 폴더 복사 → 사내 모사에서 `collect --auto` | [수집] 끝에 자동 `sent`, 사람 조작 0, 클라우드에서 시도 횟수 소진 0 |
| U15 pepper 없음 | 레지스트리 캐시 없이 빌드 | `peers[].scope=personal`(개인 키링 `peer` 키), `peer_scope=personal`, `pepper_id=null`, 서버가 그 동료 키를 연결에 쓰지 않음 |
| U16 동료 키 일치 | 같은 pepper 로 두 팀원 묶음 빌드(서로를 동료로) | A 의 peers 에 B 의 self_peer_key 가, B 에 A 의 것이 그대로 |

### 9.3 팀 서버

| ID | 절차 | 기대 |
|---|---|---|
| S01 hello | GET /api/hello | app=LM27-team, 경로·pid·토큰·호스트명 키 없음 |
| S02 LM24 점유 | 시험 포트에 LM24 흉내 서버 → LM27 서버 기동 | rc=3, kind=`lm24`, 프로세스 이름 표시, 대체 포트 제안(임시 범위·회피 대역 밖), 자동 전환 없음 |
| S03 배타 바인드 | LM27 서버 가동 중 같은 포트에 SO_REUSEADDR 바인드 시도 | 실패(10013, 원형 실측) |
| S04 초과 본문 | Content-Length 20MB | 413 응답이 클라이언트에 도착(RST 아님, 원형 실측) |
| S05 동시 업로드 | 같은 사람 2기간×3변형 + 다른 사람 3건 동시 | current.json 일관, 묶음 파일 손상 0, `.part` 잔존 0, 재취합 1~2회 |
| S06 악성 라벨 | self_label·title 에 `</script><!--<script>` | 검증 단계에서 정제 라벨 위반이면 422, 통과하는 변형은 저장·렌더 후 보고서 정상·스크립트 실행 0(데이터 섬 `\u003c`) |
| S07 레지스트리 | PUT version 현재+1 / 현재 / 원격에서 토큰 없이 / merged_into 순환 | 200 / 409 / 403 / 422 |
| S08 형식 손상 | current.json 을 `[]` 로 손편집 | .bak 복구 또는 재구성, 다른 사람 취합 정상 |
| S09 Content-Type·길이 | text/plain / Content-Length 없음 | 415 / 411 |
| S10 allow_cidrs | `["10.0.0.0/8"]` 에서 사설 아닌 출발지 모사 | 403(루프백은 허용) |
| S11 shutdown | 원격 POST /api/shutdown | 403, 서버 계속 |
| S12 LM24 클라이언트 | POST /api/upload | 410 + 한국어 사유 |
| S13 옛 묶음 역전 | 같은 기간, built_at 10/5 묶음 저장 후 10/1 묶음 반입 | `stale_kept`, current 는 10/5 그대로, 10/1 파일은 보관 |
| S14 Host 헤더 | `Host: evil.example:9310` | 421 `bad_host` |
| S15 교차 출처 | OPTIONS /api/bundles · 폼 형식 POST | 405 · 415 |
| S16 방화벽 진단 | 명령 출력 모사(Public·BlockInbound·python.exe Block 규칙) | 의심 문구·`firewall_hint`, 경로가 API·로그에 없음 |
| S17 임시 포트 | 동적 범위 모사 1024~15000, 9310 리스너 없음 + bind 10048 | kind=`ephemeral`, 제안 19310 이상 |

### 9.4 취합

| ID | 절차 | 기대 |
|---|---|---|
| A01 **개인=팀(관문)** | 합성 E2E: PC1→PC2→클라우드 번들 → 분석 → 묶음 → 서버 → 취합 | 사람·월 MM, 영역·과제 MM, 꼬리표별 분이 개인 보고서 값과 정수 분 일치, MM \|Δ\| ≤ 1e-9 |
| A02 기간 겹침 | 7–9월(10/1 빌드), 9–11월(10/5 까지·10/5 빌드) 묶음 | 9월 한 번만(덮는 평일 동률 20 → 나중 빌드), 원형 수치 단순합 2.279 → 1.128MM |
| A03 무결성 위반 | alloc 합 > env 인 묶음 | 업로드 422 `integrity` |
| A04 측정 불충분 | 1명 unreliable | 팀 합계 포함(빗금), 평균·순위·분포에서 제외, 별도 표 |
| A05 달력 상이 | calendar_version 다른 묶음(7월 23일로 계산한 옛 판) | 서버 달력(22일)으로 계산 + `calendar_mismatch` 배지 + 개인값 병기 |
| A06 같은 사람 연결 | self_peer_key 같은 두 person_key / 같은 member_id | 한 사람으로 합산, members 의 linked 표시 |
| A07 단위업무 이월 | 같은 unit_id 가 8월(묶음 A)·9월(묶음 B) | 간트 막대 하나(lead 띠 합침, active·밀도는 alloc 에서 재계산) |
| A08 부분월 | analyzed_until 2026-10-05 | 10월 "부분월(2/20 평일)", 분모는 20 평일 그대로 |
| A09 손상 묶음 | 저장본 1개 sha 변조 | 그 묶음만 제외 + 경고, 나머지 정상 |
| A10 과제 병합 | 레지스트리 P-0002.merged_into=P-0001, P-0003↔P-0004 순환 | P-0002 투입이 P-0001 행으로, 순환은 규칙대로 대표 하나, 재업로드 없음 |
| A11 간트 | 합성 단위업무 alloc(빈 날 1·3일 섞음) | active 구간 = `active_spans(gap=2)`, 주별 밀도 합 = effort_min, 행 계층 기본 담당자→영역→과제→역할, 피벗 토글 결과 같은 합 |
| A12 2026 평일 관문 | 레지스트리 달력으로 W(m) 계산 | 2026-07=22, 08=20, 09=20, 10=20(`calendar_verified.json` 표와 12개월 모두 일치) |

### 9.5 오프라인

| ID | 절차 | 기대 |
|---|---|---|
| O01 내보내기 바이트 | export_to_dir | 파일 sha = pending sha, `.part` 잔존 0, `data\keys\` 동반 0 |
| O02 반입 | inbox 에 정상 1·변조 1·이름 위반 1·복사 중(30초 전 수정) 1 | 1 done, 1 rejected(+reason), 이름 위반 무시, 복사 중은 다음 회차 |
| O03 읽기 전용 감시 폴더 | inbox_dirs 에 같은 파일 반복 존재 | 1회만 반입(seen), 원본 파일 그대로 |
| O04 서버 실행 중 CLI 반입 | team-import | inbox 로 복사만, 30초 안 반영 |
| O05 delivered | exported 항목 후 서버 members 에 같은 sha | 클라이언트 상태 delivered |

### 9.6 lint 관문(이 문서 관련)

1. `team.server_host`·`team.server_port` 기본값과 상수 `DEFAULT_TEAM_URL == "http://10.115.147.68:9310"` 바이트 일치(사용자 지시 고정값). 사설 IP 금지 lint 는 이 값 하나만 예외.
2. `data\pcs` 직접 경로 조합·open 금지(AST) — `lm27/bundle/loader.py`·`segment.py`·`manifest.py`·`export.py`·`pcreg.py`·`merge.py`·`move.py` 만 예외.
3. 서버 코드에 `allow_reuse_address = True`·`SO_REUSEADDR` 사용 금지.
4. 작업 이름·뮤텍스 문자열에 `install_id` 포함(상수 `LM27-` 단독 사용 금지), 작업 XML 의 `WorkingDirectory`·`Command` 가 ROOT 를 가리키지 않음(생성 함수 단위 시험).
5. 팀 묶음 빌더에서 `**dict`·`dict(obj)`·`copy.deepcopy(analysis…)` 같은 통째 전달 금지(허용 목록 생성만).
6. `zoneinfo.ZoneInfo` 호출 금지, 최종 파일 `open(…, "w")` 직접 쓰기 금지(`atomic_write` 만), `except ImportError:` 로 기능을 삼키는 코드 금지.
7. `.ps1` UTF-8 BOM+CRLF, `.bat` CP949+CRLF, 소스 제어문자 0.
8. `TEAM_SPEC_V1`(PRIVACY `check_team_payload` 입력)이 §2.3.2 표 생성기에서 나온 것과 같음(두 명세 한 표).

---

## 10. 실측 근거(2026-10-05, 이 PC — Windows 11 Pro, 비관리자, 동봉 파이썬 3.11.9)

스크래치 `…\scratchpad\lm26_survey\design\team_bundle_lm27\` 의 `probe_facts.py`·`probe_lock.py`·`proto_lm27.py`(합성 자료만)와 출력 `*_out.txt`·`env_facts.txt`.

| 사실 | 결과 | 쓰인 곳 |
|---|---|---|
| `zoneinfo.ZoneInfo("Asia/Seoul")` | `ZoneInfoNotFoundError` | §0.2 |
| MachineGuid 사용자 권한 읽기 | 가능 | §1.2 |
| gzip(`mtime=0`, `filename=""`) 결정성 | 같은 입력 같은 sha | §1.3 |
| 정규 JSON·중복 키·NaN 거부 | 동작 | §0.3·§3.8 |
| 기본 `HTTPServer.allow_reuse_address` | 1 → 덧바인드 **성공**(위험) | §3.3 |
| `SO_EXCLUSIVEADDRUSE` 리스너(서버 원형 포함) 위 덧바인드 | 10013 으로 막힘 | §3.3·S03 |
| 평범한 두 번째 바인드 | 10048 | §3.3 |
| 파일을 연 프로세스·cwd 가 폴더 안인 프로세스 | 폴더 rename `WinError 5` | §1.9 |
| Restart Manager(비관리자) | 파일 보유 pid·이름 찾음 / 폴더(cwd)는 오류 5 | §1.9·§1.11 |
| `msvcrt.locking` 보유 프로세스 kill 후 | 즉시 획득 | §1.9 |
| 다른 프로세스가 연 파일 위 `os.replace` | `PermissionError(5)`, 닫힌 뒤 재시도 성공(누계 3.1s) | §0.2·§0.3 |
| 3MB 초과 본문 + drain 후 413 | 클라이언트가 413 수신 | §3.8·S04 |
| 같은 사람 동시 업로드 9건 | 전부 stored, current 일관, `.part` 0, 재전송 already_have | §3.8·S05 |
| 최대 잔여법 2,000회 무작위 | 합 불일치 0 | R-3 |
| 검증 달력 2026 월별 평일 | 21·17·21·22·18·21·**22**·20·20·20·21·22 — `calendar_verified.json` 과 일치 | R-5·A12 |
| 겹친 9월 단순합 → 선택 | 2.279 → 1.128MM, 개인=팀 일치, 변조 탐지 | §4.3·A02 |
| 동적 포트 범위 | 1024~15000(9310 포함) | §3.4 |
| 방화벽 프로필·앱 규칙 읽기(비관리자) | 가능(~1s), LM24 python.exe 에 인바운드 Block(Public) 2개 / 포트 필터는 Access denied | §3.14 |
| 현재 망 범주 | Public | §3.14 |
| 동봉 파이썬(embeddable) 크기·구성 | 약 21MB, `pythonw.exe` 포함, `_pth` = `python311.zip` + `.`(스크립트 폴더 없음) | §1.6.1 |

---

## 11. 미결

1. **키 위치(결정 메모와의 해석 차이)** — 결정 메모 10.4 는 "개인 비밀은 %LOCALAPPDATA%, 키는 번들·팀 묶음에 넣지 않는다"이나, PC1·PC2·클라우드PC 가 같은 가명을 만들려면 키가 폴더와 함께 움직여야 한다. PRIVACY(LM27) H6 대로 키링 정본은 `data\keys\`(세그먼트·manifest·팀 묶음·코파일럿·패키지·오프라인 내보내기 금지), 에이전트에는 하위 키만, 팀 pepper 는 `data\team\registry.json` 캐시에 둔다. 폴더가 통째로 남에게 넘어가면 키와 가명 자료가 함께 넘어가는 위험이 남는다 — 오케스트레이터 확인 필요(PRIVACY Q14 와 같은 질문).
2. **`self_label` 허용 여부** — 본인이 직접 입력한 라벨만 싣고 수집에서 얻은 표시명은 막는다. 실명 입력까지 막고 팀장이 서버 roster·레지스트리 `members` 에서만 이름을 붙이게 할지 사용자 결정 필요.
3. **팀 pepper 와 사전 공격** — 사내 메일 주소는 추측 가능하므로 pepper 를 가진 사람은 peer_key 를 되돌릴 수 있다. pepper 는 `/api/registry`(기본 토큰 없음)와 `publish_dir` 로 배포된다. `read_requires_token` 기본값과 공유폴더 게시 허용 여부 결정 필요.
4. **평문 HTTP** — 표준 라이브러리 `ssl` 로 TLS 는 가능하나 인증서 배포·갱신이 사람 손을 요구한다. v1 은 HTTP(사내망 전제)로 두고 묶음에 원문이 없도록 막는 것으로 위험을 줄였다.
5. **같은 호스트의 LM24 서버(9310)** — 그동안 LM27 은 대체 포트 + 팀원 `server_alternates` 로 운영된다. LM24 서버를 내릴 시점·주체(사용자 결정).
6. **임시 포트 범위가 9310 을 포함**(이 PC 실측 1024~15000) — 팀 서버 PC 도 같다면 9310 이 수시로 막힐 수 있다. 예약 범위 추가는 관리자 권한이라 LM27 은 하지 않는다. IT 요청 여부 결정 필요.
7. **방화벽** — 이 PC 에는 LM24 python.exe 의 인바운드 Block 규칙이 이미 있다. LM27 은 다른 경로의 python.exe 이므로 첫 실행 때 Windows 보안 경고에서 '허용'이 필요하고(관리자 권한이 요구될 수 있음), 취소하면 같은 Block 규칙이 생긴다. 팀 서버 PC 의 허용 절차를 운영 문서에 넣을지 결정 필요.
8. **단위업무 제목 업로드 기본값** — 기본 `label`(결정 메모 10.4). 과제 성격상 제목 자체가 민감한 팀은 `generic` 을 기본으로 할지.
9. **첫 전송 승인(`team.auto_send=false`)** — "다른 사용자에게 수동 조작 요구 금지" 원칙과의 관계. 승인은 기간당 1회 본인 확인이며 이후 재시도·클라우드→사내 전송은 자동이다. 이 정도 확인이 허용되는지.
10. **시간 모델·분석 계약** — R-2(꼬리표 배타)·R-3(정수 분 최대 잔여법)·R-4(unit_id)·R-8(role_id)·근거 종류 코드(S1i·S1o·S2·E1o·E1i·E2·E3c)를 해당 명세가 채택해야 개인=팀 소수점 일치·다월 간트가 성립한다.
11. **팀 서버 저장소 백업·위치** — 기본 `%LOCALAPPDATA%\LoadMonitor27\teamserver`. 백업 주기·위치 미정. 공유 드라이브 저장소는 SMB 에서 잠금·원자 교체를 실측한 뒤에만 허용.
12. **형제 명세 정합(§0.5)** — COLLECTION·COLLECT_PC·PRIVACY(LM26 이름판)의 번들 경로·manifest 위치·세그먼트 이름·커서·pc_id·에이전트 실행 위치·로컬 원장 파일 형식·팀 페이로드 표를 LM27 판으로 옮길 때 이 문서에 맞춰야 한다. 특히 COLLECT_PC 의 "작업 Action = ROOT 의 스크립트"는 폴더 이동 후 PC1 기록이 끊기는 결함이다.
13. **에이전트 파이썬 사본 용량** — 에이전트는 PC 마다 `%LOCALAPPDATA%` 에 동봉 파이썬(약 21MB, LM24 동봉본 실측)·정제기 사본을 둔다(판 2개 보관 시 최대 약 45MB). 허용 여부와, AppLocker·CLM 으로 `%LOCALAPPDATA%` 실행이 막힌 PC(에이전트 `none`) 비율은 사내 표준 이미지 실측 필요.
14. **고객사 사전 배포** — 레지스트리로 고객사 이름 사전을 모든 팀원 PC 에 배포하는 것의 보안 판단.
15. **읽기 공개 범위** — `read_requires_token=false` 면 사내망 누구나 `/api/team`(사람별 MM·초과 시간)을 볼 수 있다(LM24 와 같은 수준). 공유판만 공개하고 전체판은 토큰으로 가릴지.
16. **달력 관리 주체** — 공휴일·회사 휴무를 팀장이 레지스트리로 관리한다(근거 URL·확인일 필수). 회사 공용 달력 출처가 따로 있는지.
17. **풀링 VDI 자동 별칭 오병합** — host_class·tz·비겹침 규칙의 실환경 정확도 미검증(오병합은 MM 에 영향 없음, PC 표시·품질 집계에만 영향).
18. **LM26 이름판 산출물 처리** — `D:\배포\loadmon26\` 트리(이번 작업 이전에 같은 설계팀이 만든 LM26 이름판 문서들)를 지울지·보존할지는 사용자 결정. 이 문서는 그 트리를 수정하지 않았다.
19. **풀링 VDI 의 에이전트 재등록** — 작업 스케줄러 작업이 이미지에 남지 않아 새 세션마다 [수집]·설치 전용 진입점을 한 번 실행해야 그 세션부터 기록된다(§1.8). 로그온 스크립트로 자동 등록할지는 IT 결정.
20. **미상 프로그램 이름 공유(`catalog_proposals`)** — PRIVACY §14.5 가 요청한 필드를 기본 꺼짐(`team.share_unknown_apps=false`)으로 넣었다. 사내 도구 exe 이름이 코드네임일 수 있어 사전 검사·미리보기 [빼기]를 거치지만, 기본값을 켤지는 팀 결정.
