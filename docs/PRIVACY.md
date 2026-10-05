# PRIVACY.md — LM27 개인정보·고객정보 정제 명세 (v1.1)

| 항목 | 값 |
|---|---|
| 대상 | LoadMonitor27(LM27) 의 모든 수집기(PC 상주 에이전트 포함)·적재기·코파일럿 브리지·팀 업로더·팀 서버 수신 검증 |
| 규칙 버전 | `RULES_VERSION = "2026.10.0"` (§16) |
| 모듈 | `lm27.privacy` — 수집기 단일 관문 `lm27.privacy.sanitize`(§3.1), 표준 라이브러리만(파이썬 3.11) + PowerShell 5.1 수집기용 정제 파이프 `lm27_pipe.py`(§3.5) |
| 판 | v1.1 — LM26 이름으로 작성됐던 초판(v1, 검증 시제품으로 말뭉치 전부 통과)을 **LM27 로 이관**하고, 형제 명세(수집 공통·메일·PC·팀/번들·코파일럿 브리지)와 어긋난 열 이름·키·경로를 이 문서에서 확정(§0) |
| 상태 | 설계 확정안 — 구현자는 §5~§14 의 코드 블록을 그대로 옮기고 §18 관문을 통과시킨다 |
| 연계 명세 | `COLLECTION.md`(공통 증거 스키마·경로 ID), `COLLECT_MAIL.md`·`COLLECT_TEAMS.md`·`COLLECT_PC.md`(수집기), `TEAM_AND_BUNDLE.md`(운반 번들·팀 묶음·팀 서버), `COPILOT_BRIDGE.md`(L0~L4), 시간 모델·분류 명세. 이 문서가 정한 열·토큰·키·함수는 그 명세들이 그대로 쓴다 |
| 근거 | 이전 판 조사 `privacy.md`(LM24 v4 실측: 합성 18건 중 16건이 필터 통과), 시제품 `filter/sanitize_proto.py`·`classify_proto.py`, 초판 검증 시제품 `design/privacy/lm26_privacy_v1.py`(§18 말뭉치 전부 통과), 이관 검증 스크립트 `design/privacy_lm27/verify_doc_lm27.py`(부록 B) |

모든 예시 값은 **합성**이다(주민·카드·전화 번호, 도메인 `example.*`, 이름 홍길동·김철수, 과제A·고객사A 등). 실명·계정·이메일·사내 코드네임은 이 문서·코드·말뭉치·기본 설정 어디에도 넣지 않는다.

---

## 0. LM27 이관과 형제 명세 정합 결정

### 0.1 이름 바꾸기 (LM26 초판 → LM27)

| 항목 | LM26 초판 | LM27 (이 문서) |
|---|---|---|
| 파이썬 패키지 | `lm26.privacy` | `lm27.privacy` |
| 프로그램 폴더 | `D:\배포\loadmon26` | `D:\배포\loadmon27` (브랜치·패키지 zip 이름은 오케스트레이터 결정 메모를 따른다) |
| PC 상주 폴더 | `%LOCALAPPDATA%\LoadMonitor26\` | `%LOCALAPPDATA%\LoadMonitor27\` |
| 작업 스케줄러·뮤텍스 | `LM26-<install_id>` | `LM27-<install_id>` |
| 루트 진입점 | `lm26_pipe.py`, `tools\lm26_selftest.py` | `lm27_pipe.py`, `tools\lm27_selftest.py` |
| 파일 형식 표식 | `lm26-keyring/1` 등 | `lm27-keyring/1`, `lm27-subkeys/1`, `lm27-persondir/1` |
| HMAC 하위 키 도메인 | `b"lm26:" + purpose` | `b"lm27:" + purpose` — LM26 이름으로 만든 키·가명과 절대 섞이지 않는다 |
| 팀 묶음 스키마 상수 | `lm26.team_bundle` | `lm27.team_bundle` |
| pc_id 해시 접두 | `"LM26.pc\|"` | `"LM27.pc\|"` (H5) |

- `D:\배포\LM26`(다른 도구가 만든 별개 프로젝트)와 `D:\배포\loadmon26`(LM26 이름으로 쓴 초판 명세 트리)은 **읽기 전용**이다. LM27 코드는 그 폴더의 파일·키·자료를 읽거나 이어 쓰지 않는다.
- 탐지·판정 코드(§5 `rules.py`, §6 `detect.py`, §11·§12 `classify.py`, §13 게이트, §14.4 라벨 검사)는 초판에서 실행 검증된 것과 **같은 정규식·같은 상수**다. 바뀐 곳은 ① 경로 주석 ② HMAC 도메인 접두 ③ `SanitizeContext.person_subkey`(§6 — 주 키 없이 하위 키만 가진 에이전트도 같은 사람 태그를 만들게 하는 선택 필드, 출력 동일) 세 가지다. 규칙 해시(§16.2)에 들어가는 값은 하나도 바뀌지 않았으므로 `RULES_VERSION` 을 유지한다.

### 0.2 정합 결정 (형제 명세의 미결을 이 문서가 소유자로서 확정)

| ID | 쟁점(제기한 명세) | 결정 |
|---|---|---|
| H1 | 저장 kind 와 정제 kind 가 다름(PC 명세 §13.3 미결: session·compute 스키마 없음) | 정제 kind = 수집 공통 명세 §3 의 저장 kind 8종 `mail·cal·teams·pc_session·pc_file·pc_git·pc_compute·manual`. 초판의 `window·file·git·worklog·copilot_ev` 는 폐기하고 §10.2 로 흡수(창 샘플 = `pc_session`+`src=pc.sampler`, 이벤트 = `pc_session`+`src=pc.events`, 코파일럿 증인 = `mail/teams/cal`+`src=*.copilot`). 무텍스트 스키마(`pc.events`·`pc_compute`)를 정식으로 둔다 |
| H2 | 열 이름 불일치(메일 명세 미결 1) | 공통 봉투는 수집 공통 명세 §3.1 이름을 쓴다: 초판 `conv_key`→`thread_key`, `peer_keys`→`counterpart_keys`, `folder_class`→`folder_role`, `n_attendees`→`n_participants`, `cat_private`·광고 헤더 불리언→`flags` |
| H3 | `subject_tokens`(목록) vs `subject_masked`(문자열) | 정본은 정제 **문자열** `*_masked`. `subject_tokens` 는 저장하지 않고 적재기가 `tokens_of(masked)`(§6.2)로 파생한다(토큰만 저장하면 코파일럿·팀 라벨이 쓸 문장이 사라짐) |
| H4 | '사람 키'가 명세마다 다른 뜻 | 세 가지로 이름을 나눈다. `who_key` = 로컬 HMAC 가명 `w`+16hex(행에 저장) / `person_key` = 팀 묶음의 번들 주인 무작위 ID `p_`+12hex(팀/번들 명세 §1.2) / `peer_key` = 팀 pepper HMAC `c_`+12hex(팀 묶음 빌드 때만 계산, 행에 저장 안 함) |
| H5 | pc_id 를 '정제 키 HMAC' 으로 적은 명세 | pc_id 는 키 없는 해시 `"pc_" + sha256("LM27.pc\|" + MachineGuid.lower())[:16]`(팀/번들 명세 §1.2 식). 키가 도착하기 전에도 정해진다. MachineGuid 원값은 카나리아(§13.1) |
| H6 | 키 보관 위치(결정 메모 10.4 '키는 번들·팀 묶음에 넣지 않는다' vs 과제 지시 '키는 PC 간 이동·팀에는 안 감') | 키링 정본은 프로그램 폴더 `data\keys\privacy_keyring.json` — 폴더째 이동으로 PC 사이를 따라가지만 **세그먼트·manifest·팀 묶음·코파일럿·패키지 zip 에는 들어가지 않는다**. 팀/번들 명세의 `data\keys\person.key` 는 이 키링의 주 키로 대체. PC 상주 에이전트에는 주 키가 아닌 **용도별 하위 키만**(§9.4). 팀 pepper 는 2층(§9.7) |
| H7 | 평문 doc_key 예시(PC 명세 §3.1·§5.5) | `doc_key` 는 언제나 HMAC(`d`+16hex) of `doc_norm(basename)`(§9.3). 메일 `attach_keys`·팀즈 `file_keys` 도 같은 함수 → 교집합으로 '작성 완료 → 메일·팀즈 보고' 연결. 같은 이름 다른 폴더 구분은 `path_key`(pc_file 전용). 평문 문서명은 `name_masked`·`title_masked` 에만 |
| H8 | 정제 파이프 호출 형식 3가지(`-m …sanitize_stream`, `lm26_pipe.py --source --pc-id`, `--out` 유무) | 루트 진입점 하나: `lm27_pipe.py (--kind K \| --route-by-kind) --src <경로 ID> --pc <pc_id> --out <경로> [--mode new\|append]`(§3.5). `python -m` 형식은 쓰지 않는다(동봉 파이썬 `python311._pth` 가 루트를 sys.path 에 넣지 않음) |
| H9 | 팀/번들 명세 R-6 이 요구한 `scan(text)` | `scan(text, ctx) -> list[Hit]`(§6.2) 제공 — 치환 없이 범주·건수만, 값·위치는 돌려주지 않는다 |
| H10 | 팀 묶음 필드 목록 이중 정의(초판 §14.4 vs 팀/번들 명세 §2.3) | 필드 목록은 팀/번들 명세 소유, 이 문서는 **값 클래스·금지 값·라벨 검사**(§14) 소유. `peers[].peer_key` 허용(사내 도메인 주소에서 만든 것만) — 초판의 `peers_count` 전용 규칙은 폐기 |
| H11 | rules_ver 표기(`pii-2026.10` vs `2026.10.0`) | `YYYY.MM.N`(§16.1) 하나 |
| H12 | 판정 결과를 `flags` 에 둘지 열로 둘지 | 점수·등급·사유 코드는 최상위 열(`ad_score`·`ad_band`·`ad_why`·`ad_partial`·`priv_score`·`priv_class`·`priv_why`), 불리언 요약만 `flags.ad`(= suspect)·`flags.private`(= private 또는 social) |
| H13 | 감사 파일이 pc_id 폴더 안 가변 파일(불변 세그먼트 원칙과 충돌) | 감사 기록도 불변 세그먼트 스트림 `privacy_audit` 로 내보낸다(§15.1). 에이전트 로컬 원장에서는 추가 전용 |
| H14 | 레코드 `id` 의 `body_hash` 가 원문 무키 해시가 될 위험 | `id` 는 `sanitize_record()` 가 계산하고 `body_hash` 는 **정제문**의 sha1 이다(§10.1) |
| H15 | 에이전트 쪽 축약 정제 규칙(`rules\sanitize_min.json`) | 폐기. 에이전트도 같은 `lm27.privacy`(같은 `RULES_HASH`)를 돌린다. 에이전트 bin 에 동봉 파이썬·`lm27\privacy\` 사본을 두고 설치·[수집] 때 sha256 대조(§3.6). 폴더가 다른 PC 로 떠난 뒤에도 PC1 에이전트는 완전한 정제기를 가진다 |

이 표의 결정은 형제 명세를 LM27 판으로 옮길 때 같은 커밋에서 반영한다(§21 Q14~Q20).

---

## 1. 한눈에 보기

### 1.1 한 줄 요약

원문은 **수집기 메모리 안에서만** 다루고, 단일 관문 `lm27.privacy.sanitize.sanitize_record()`(내부에서 `sanitize()`)를 통과한 **열 허용 목록 행만** 디스크에 쓴다. 같은 정제기를 적재 시(규칙 버전 상향), 코파일럿 전송 직전, 팀 업로드 직전에 다시 건다. 기록은 **범주별 건수·규칙 버전·해시만** 남긴다.

### 1.2 관문 4개

```
[PC1·PC2·클라우드PC 수집기 / PC 상주 에이전트]      (원문은 여기 메모리에만 존재)
  Outlook COM / 색인 / OWA·Teams 웹(CDP) / Teams UIA / 창 샘플러 / 이벤트 / 파일·MRU·Recent / git / 반입 EML·CSV·ICS / 수동 기록
        │ raw dict (메모리 또는 stdin 파이프)
        ▼
 ┌─ G1 수집 경계 정제 ─ sanitize_record(kind, raw, rc) ───────────────────────────┐
 │  값 검증 → 키 계산(원문 HMAC) → 파생 특징(광고·부재 힌트) → 자격증명 행 폐기      │
 │  → PII 토큰 치환 → 금액 → 사전 가명화 → 이름 가명화 → 광고 점수 → 사적 점수     │
 │  → 열 허용 목록 조립 → SanitizedRow(봉인)                                       │
 └──────────────────────────────────────────────────────────────────────────────┘
        │ SanitizedRow 만 SegmentWriter 가 받음 (원문 쓰기 경로 없음)
        ▼
  에이전트 로컬 원장(%LOCALAPPDATA%\LoadMonitor27\agent\store\…)  ─내보내기→  data\pcs\<pc_id>\seg\<stream>\*.jsonl.gz
        │                                                              (pc_id 별 불변 세그먼트, 폴더째 이동)
 ┌─ G2 적재 시 재정제 ─ resanitize_row() : rules_ver 가 낮은 행만, 가림은 늘기만 함 ┐
 └──────────────────────────────────────────────────────────────────────────────┘
        │
        ├──► 로컬 분석·개인 보고서 (가명 토큰 + 로컬 전용 사람 사전으로 표시명 복원)
        │
 ┌─ G3 코파일럿 전송 직전 ─ gate_copilot(items, stage, gctx) + gate_prompt_text() ──┐
 │  사적·광고 의심 행 제외 → 재정제 → 고위험 잔여 PII 행 제외 → 카나리아 → 토큰 축약 │
 └──────────────────────────────────────────────────────────────────────────────┘
        │
 ┌─ G4 팀 업로드 직전 ─ check_team_payload(payload) : 값 클래스·금지 값·라벨 검사 ──┐
 └──────────────────────────────────────────────────────────────────────────────┘
        ▼
  팀 서버 (서버도 같은 검사로 재검증)

  감사: 각 관문이 AuditSink 로 {범주: 건수, rules_ver, rules_hash, sha256} 만 기록 (§15)
```

### 1.3 불변식 (어기면 결함 — 각 항목은 §18·§19 관문으로 검사)

| ID | 불변식 |
|---|---|
| I1 | 메일 본문·헤더 원문·주소·표시명·창 제목 원문·팀즈 본문 원문·파일 전체 경로는 **어떤 파일에도** 쓰지 않는다. 예외는 §9.6 의 로컬 전용 사람 사전(표시명·주소)과, 그 이름 목록을 에이전트에 내려 준 정제 문맥 사본(§3.6 `context_cache.json`, 주소 없음) 둘뿐이다 |
| I2 | 저장소 쓰기는 `SegmentWriter.append(SanitizedRow)` 하나뿐이다. `SanitizedRow` 는 `sanitize_record()` 만 만든다(에이전트 포함 — H15) |
| I3 | 정제기가 실패하면 그 행은 버린다(fail-closed). 원문으로 대체 저장하는 경로는 없다 |
| I4 | `sanitize(sanitize(x)) == sanitize(x)` (멱등) — 기존 토큰은 다시 건드리지 않는다 |
| I5 | 규칙 버전이 올라가도 이미 가린 값은 되살아나지 않는다(단조) |
| I6 | 같은 입력·같은 키·같은 규칙 버전이면 같은 출력(결정적) — 난수·시각 의존 없음 |
| I7 | HMAC 주 키(키링)는 프로그램 폴더 `data\keys\` 로만 PC 사이를 이동하고, 세그먼트·manifest·팀 서버·코파일럿·패키지 zip 으로 가지 않는다. PC 상주 에이전트에는 용도별 하위 키만 둔다 |
| I8 | 감사 로그·오류 메시지·stderr 에는 원문·정제문·예시 문자열을 쓰지 않는다. 건수·코드·해시·버전만 |
| I9 | 조용한 삭제 금지 — 버린 행·가린 값은 반드시 사유별 건수로 남는다 |
| I10 | 모든 저장 행에 `rules_ver` 와 `kid`(키 ID)가 있다 |
| I11 | 코파일럿 프롬프트·팀 페이로드에 합성 카나리아(§18) 원값이 0건 |
| I12 | 텍스트가 아닌 열(열거·숫자·키·시각)은 형식 검증을 통과한 값만 저장한다 — 열거 열에 원문이 숨어 들어갈 수 없다(§10.1) |

---

## 2. 범위·용어·비목표

### 2.1 보호 대상

| 분류 | 대상 | 처리 |
|---|---|---|
| 개인 식별번호 | 주민등록번호·외국인등록번호·생년월일·여권·운전면허·카드·계좌·전화·이메일 로컬파트 | 유형 토큰 치환 |
| 자격증명 | 비밀번호·인증번호·OTP·API 키·토큰·개인키 | **행 폐기** |
| 기기·네트워크 | IP(v4·v6), URL, 파일 경로(사용자 폴더명 포함), PC 이름, 사용자 계정명, MachineGuid | 토큰 치환 / 카나리아 |
| 고객정보 | 수주·계약·견적 금액, 단가, 할인·마진율, 고객사명·도메인, 사업자·법인번호 | 토큰 치환 / 사전 가명화 |
| 과제 기밀 | 과제 코드네임 | 레지스트리 ID 토큰으로 가명화 |
| 사람 | 동료·상대·본인 이름 | 키 기반 가명 토큰 `[사람#xxxxxx]`, 본인 `[나]` |
| 사적 내용 | 사적 대화·개인 일정·비업무 앱·사이트 사용 | 내용 삭제 + 시간 근거 제외 규칙(§12.7) |
| 광고 | 업체 광고·뉴스레터·웨비나·프로모션 메일 | 점수 5 이상 행 폐기, 3~4 보류 |

### 2.2 용어

- **원문(raw)**: 수집기가 원천에서 읽은 값. 메모리(또는 정제 파이프의 stdin)에만 있다.
- **정제문(masked)**: `sanitize()` 출력. 열 이름 접미사 `_masked`.
- **토큰**: `[전화]` 같은 유형 자리표시자(§5.2 문법).
- **키 값(keyed)**: 키링 주 키에서 파생한 용도별 하위 키로 만든 HMAC-SHA256 16진 문자열(§9).
- **who_key / person_key / peer_key**: H4 참조.
- **pc_id**: `"pc_" + sha256("LM27.pc|" + MachineGuid.lower())[:16]`(H5). 번들 안에서만 쓰고 코파일럿·팀 묶음에는 보내지 않는다.
- **경로 ID(src)**: 수집 공통 명세 §2 의 `mail.com`·`teams.uia`·`pc.sampler` 같은 출처 식별자.

### 2.3 비목표(하지 않는 것 — 문서에 명시해 오해를 막는다)

- 기계학습 개체명 인식(NER). 이름은 **사전 + 호칭·멘션·라벨 문맥**으로만 잡는다(사전에 없고 문맥도 없는 이름은 못 잡는다 → §21 Q8).
- 첨부 파일 내용·이미지 속 글자(OCR) 판독. 첨부는 파일명만 정제해 저장한다. 파일 수집기의 OOXML 메타(`lastModifiedBy` 등 사람 이름)는 메모리에서 '나와 같은가'만 판정해 `flags.author_other` 로 남기고 이름은 버린다.
- 완전 익명화 보장. 가명 토큰 + 시각 조합으로 사람이 추정될 수 있다. `data\` 폴더 전체와 `%LOCALAPPDATA%\LoadMonitor27\` 가 보호 대상이다.
- OS 메모리·페이지 파일·원천 앱(Outlook·Teams) 저장소 통제.
- 앱 내부 캐시 직접 판독(Teams IndexedDB/LevelDB, 알림 DB, OST/PST) — 데이터 접근 원칙상 금지.
- 원문 디버그 저장. '켜면 암호화 저장' 같은 선택지도 두지 않는다(LM24 실패 프롬프트·팀즈 화면 덤프 잔재의 근본 제거).

---

## 3. 모듈 배치와 공개 인터페이스

### 3.1 파일 배치

```
lm27\privacy\__init__.py        공개 API 재수출(아래 3.3 표) — 분석·브리지·팀 코드는 이것만 import
lm27\privacy\sanitize.py        ★ 수집기 단일 관문(facade): sanitize, sanitize_record, make_record_context, scan,
                                  SanitizedRow, RecordOutcome 만 재수출 — 수집기는 이 모듈만 import (lint 로 강제, §3.4)
lm27\privacy\rules.py           버전 고정 규칙: 정규식·어휘·가중치·임계 (§5, §11, §12) — 설정으로 못 바꿈
lm27\privacy\rules.lock.json    {"rules_ver": "2026.10.0", "rules_hash": "<16hex>"} (§16)
lm27\privacy\detect.py          SanitizeContext, sanitize() 본체 (§4, §6)
lm27\privacy\scan.py            scan(), tokens_of() (§6.2)
lm27\privacy\classify.py        ad_score(), private_score(), window_class(), room_prior() (§11, §12)
lm27\privacy\records.py         SCHEMAS(열 허용 목록), sanitize_record(), resanitize_row(), SanitizedRow (§10)
lm27\privacy\keys.py            Keyring, AgentKeys, load_keyring(), keyed(), who_key(), doc_norm(), peer_key() (§9)
lm27\privacy\gate.py            gate_copilot(), gate_prompt_text(), check_team_payload(), check_team_label() (§13, §14)
lm27\privacy\audit.py           AuditSink (§15)
lm27\privacy\context.py         build_context(), make_record_context(), make_gate_context() — 설정·레지스트리·로컬 전용 사전 → 문맥 (§8, §13.1, §17)
lm27\privacy\sanitize_stream.py 정제 파이프 본체 main(argv) (§3.5)
lm27\privacy\selftest.py        회귀 말뭉치 관문 (§18) — `python\python.exe -B tools\lm27_selftest.py privacy`
lm27\privacy\corpus\regress_v1.jsonl   회귀 말뭉치 (§18.2)
lm27_pipe.py                    루트 진입점: sys.path.insert(0, 자기 폴더) → lm27.privacy.sanitize_stream.main()
```

데이터 위치(모두 `.gitignore` 의 `data/` 아래이거나 PC 상주 폴더 — 저장소·패키지에 들어가지 않는다):

| 경로 | 내용 | PC 간 이동 | 팀 업로드 |
|---|---|---|---|
| `data\keys\privacy_keyring.json` | HMAC 키링 정본(§9.2) | O (폴더째) — manifest·세그먼트에는 안 들어감 | **금지** |
| `%LOCALAPPDATA%\LoadMonitor27\agent\keys\subkeys.json` | 에이전트용 용도별 하위 키(§9.4) — 주 키 없음 | PC 고정 | 금지 |
| `data\local_only\person_dir.json` | who_key → 표시명·주소(로컬 표시·peer_key 계산용, §9.6) | O | 금지 |
| `data\local_only\corresp_domains.json` | 왕래 도메인 → 마지막 발신일(§11.3) | O | 금지 |
| `data\local_only\ad_lists.json` | 사용자 광고 차단·허용 목록(§11.5) | O | 금지 |
| `data\local_only\private_chats.json` | 사용자가 '사적'으로 지정한 chat_key 목록(§12.4) | O | 금지 |
| `data\local_only\redact_overlay.json` | 소급 가림 목록(§12.5) | O | 금지 |
| `data\pcs\<pc_id>\seg\<stream>\*.jsonl.gz` | 정제된 행 세그먼트(배치·이름은 팀/번들 명세 §1 소유) | O | 금지(집계만) |
| `data\pcs\<pc_id>\seg\privacy_audit\*.jsonl.gz` | 감사 세그먼트(§15) | O | 건수 요약만 |
| `%LOCALAPPDATA%\LoadMonitor27\agent\store\…` | 에이전트 로컬 원장(정제 통과 행만, 추가 전용) | PC 고정 | 금지 |

`data\local_only\` 는 번들 manifest 의 세그먼트 집합에 들어가지 않는 PC 간 공용 상태다. 병합 규칙은 파일별로 정한다(§9.6, §11.3, §12.4·§12.5).

### 3.2 자료구조

```python
# 자료구조 요약 — 실제 정의(기본값 포함)는 §6 의 detect.py
@dataclass(frozen=True)
class SanitizeResult:
    text: str                       # 정제문 (drop 이면 "")
    hits: dict[str, int]            # 범주 코드 → 건수 (§15.3 코드표)
    drop: bool = False              # True 면 행 전체 폐기
    drop_reason: str | None = None  # "cred"
    rules_ver: str = RULES_VERSION

@dataclass
class SanitizeContext:              # build_context() 가 만든다. 수집 실행 1회 동안 불변
    internal_domains: list[str]     # 사내 도메인(소문자). 본인 SMTP 도메인은 런타임에 자동 추가
    personal_mail_domains: list[str]
    customers: list[dict]           # [{"id": "C01", "names": [...], "domains": [...]}]
    partners: list[dict]            # [{"id": "V01", "names": [...], "domains": [...]}]
    projects: list[dict]            # [{"id": "P-0001", "codenames": [...]}]
    persons: dict[str, str]         # 표시명(원형) → who_key 의 16hex 부분. 로컬 사람 사전에서
    self_names: list[str]           # 본인 표시명 변형들 → [나]
    allow_patterns: list[str]       # 조직 허용 패턴(검증 통과한 것만, §17.3)
    extra_ctx: dict[str, list[str]] # 범주별 추가 문맥어 (account/passport/license/money/ip/card/eng)
    mask_company_suffix: bool = True
    mask_rates: bool = True
    key: bytes = b"\x00" * 32       # 키링 주 키의 비밀값(§9.3). 말뭉치 시험은 0 바이트 키
    person_subkey: bytes | None = None  # 주 키가 없는 에이전트용: subkey(주 키, "person"). 있으면 key 대신 사용(출력 동일)
```

```python
# lm27/privacy/records.py
@dataclass(frozen=True)
class SanitizedRow:                 # 생성자는 모듈 내부 전용(_SEAL 토큰 확인) — 수집기가 직접 만들 수 없음
    kind: str                       # KINDS 중 하나 (§10)
    data: dict                      # SCHEMAS[kind] 의 열만
    _seal: object = field(repr=False, compare=False)

@dataclass(frozen=True)
class RecordOutcome:
    status: str                     # "stored" | "dropped" | "error"
    row: SanitizedRow | None
    reason: str | None              # dropped: "cred" | "ad" | "private_folder" | "bad_raw" | "no_key"; error: 예외 타입명
    hits: dict[str, int]

    def as_pair(self) -> tuple[dict | None, dict]:
        """수집 공통 명세 §11 의 2-튜플 표기 `(record | None, audit)` 호환. audit 에는 status·reason·hits 만."""
        return (self.row.data if self.status == "stored" else None,
                {"status": self.status, "reason": self.reason, "hits": dict(self.hits)})

@dataclass
class RecordContext:                # 수집 실행 1회 단위 — make_record_context() 가 만든다
    pc_id: str
    src: str                        # 경로 ID (수집 공통 명세 §2): "mail.com" | "teams.uia" | "pc.sampler" | ...
    sctx: SanitizeContext
    keyring: "Keyring | AgentKeys"  # 프로그램 폴더 실행 = Keyring, 에이전트 = AgentKeys (§9.4)
    my_addrs: frozenset[str]        # 본인 SMTP 주소(소문자, 메모리 전용) — rcv·sender_key='self' 판정
    corresp_domains: set[str]       # §11.3
    ad_lists: dict                  # §11.5 (config 고정분 ∪ 로컬 사용자 목록)
    private_chats: set[str]         # §12.4
    room_stats: dict[str, "RoomStat"]  # §12.4
    work_window: "WorkWindow"       # 평일 표준창·공휴일 — 시간 명세의 개인 설정을 그대로 받음
    off_min: int                    # 근무 시간대 오프셋(분, 기본 540). zoneinfo 사용 금지
    audit: "AuditSink"
    no_key: bool = False            # 키 없음 모드(§9.4) — make_record_context() 가 정한다
```

### 3.3 공개 함수 시그니처 (`lm27.privacy` 에서 재수출, 수집기용은 `lm27.privacy.sanitize`)

```python
RULES_VERSION: str                       # "2026.10.0"
RULES_HASH: str                          # 규칙 정규화 덤프의 sha256 앞 16자 (§16.2)
KINDS: tuple[str, ...]                   # ("mail","cal","teams","pc_session","pc_file","pc_git","pc_compute","manual")

# ── 수집기 단일 관문 (lm27.privacy.sanitize) ──
def sanitize(text: str, field_name: str = "text", ctx: SanitizeContext | None = None,
             max_len: int | None = None) -> SanitizeResult
def sanitize_record(kind: str, raw: dict, rc: RecordContext) -> RecordOutcome
def make_record_context(root: Path | None, src: str, pc_id: str, *, agent_dir: Path | None = None,
                        stage: str = "collect") -> RecordContext   # root=None 이면 에이전트 모드(AgentKeys)
def scan(text: str, ctx: SanitizeContext | None = None) -> list[Hit]          # 치환 없이 범주·건수 (§6.2)

# ── 적재·유지보수 ──
def tokens_of(masked: str, max_tokens: int = 30) -> list[str]                  # subject_tokens 파생 (§6.2)
def resanitize_row(kind: str, row: dict, ctx: SanitizeContext) -> tuple[dict, dict[str, int]]
def redact_rewrite(segment_path: Path, kind: str, predicate: Callable[[dict], bool],
                   own_pc_id: str, audit: AuditSink) -> int          # 바꾼 행 수

# ── 판정 ──
def ad_score(f: dict) -> tuple[int, str, list[str]]                   # (점수, "keep"|"suspect"|"drop", 사유 코드)
def private_score(text: str, *, chat_type: str = "", offhours: bool = False, room_prior: str = "",
                  personal_mail: bool = False, sensitivity: int = 0, private_category: bool = False,
                  user_private_chat: bool = False) -> tuple[int, str, dict]   # (점수, "work"|"private"|"social", 세부)
def window_class(fg_exe: str, title: str, app_class: str, wctx: "WindowContext") -> "WindowVerdict"
def room_prior(stat: "RoomStat") -> str                                # "private" | "work" | ""

# ── 전송 게이트 ──
def make_gate_context(sctx: SanitizeContext, cfg: dict, kr: "Keyring", *, stage: str, audit: AuditSink,
                      web_grounding: bool = False) -> "GateContext"          # 카나리아는 메모리에서만 (§13.1)
def gate_copilot(items: list["GateItem"], stage: "StageSpec", gctx: "GateContext") -> "GateResult"
def gate_prompt_text(prompt: str, gctx: "GateContext") -> tuple[bool, dict[str, int]]
def check_team_payload(payload: dict, gctx: "GateContext", spec: dict | None = None) -> list["Violation"]
def check_team_label(s: str, gctx: "GateContext", max_len: int = 40) -> list[str]

# ── 키 ──
def load_keyring(data_dir: Path, audit: AuditSink, *, create: bool = False) -> "Keyring"
def write_agent_subkeys(kr: "Keyring", agent_dir: Path, audit: AuditSink) -> str       # 반환 kid
def load_agent_keys(agent_dir: Path, audit: AuditSink) -> "AgentKeys | None"
def keyed(kr: "Keyring | AgentKeys", purpose: str, value: str, n: int = 16) -> str
def who_key(kr: "Keyring | AgentKeys", ident: str) -> str                               # "w" + 16hex
def doc_norm(name: str) -> str                                                           # §9.3
def doc_key(kr: "Keyring | AgentKeys", name: str) -> str                                 # "d" + 16hex
def peer_key(pepper_hex: str | None, smtp: str, internal_domains: list[str],
             kr: "Keyring") -> tuple[str | None, str]                                    # (c_+12hex | None, "team"|"personal")
def build_context(cfg: dict, registry: dict, local: "LocalOnly", kr: "Keyring | AgentKeys") -> SanitizeContext

class AuditSink:
    def __init__(self, writer: "SegmentWriter", pc_id: str, stage: str, src: str): ...
    @classmethod
    def open(cls, data_dir: Path | None, pc_id: str, stage: str, src: str,
             agent_dir: Path | None = None) -> "AuditSink": ...           # 경로 해석은 §15.1 — 브리지·게이트·팀 업로더는 이것만 쓴다
    def add(self, counter: str, key: str, n: int = 1) -> None        # counter ∈ masked|dropped|priv|ad|err|remask|key|cfg
    def flush(self, **numbers) -> None                               # 이벤트 1줄 기록 후 카운터 초기화

def run_selftest(corpus_path: Path | None = None, *, update_lock: bool = False) -> int   # 0 = 통과
```

### 3.4 '단일 관문' 강제 장치

1. `SegmentWriter.append()`(저장소 명세 소유)는 `isinstance(x, SanitizedRow)` 이고 `x._seal is records._SEAL` 일 때만 받는다. 아니면 `TypeError` → 수집기 중단.
2. lint 관문(`tools\lint.ps1`, AST·정규식):
   - `lm27\collect\**\*.py`·`collect\*.py` 에서 `open(` 의 쓰기 모드(`"w"`·`"a"`·`"x"`), `json.dump(`, `csv.writer(`, `Path.write_text(`, `gzip.open(` 쓰기 모드 사용 금지. 허용 예외는 `lm27\store\` 와 `lm27\privacy\` 뿐.
   - 수집기 파이썬 모듈의 `lm27.privacy` import 는 `lm27.privacy.sanitize` 한 모듈만 허용(`from lm27.privacy.detect import …` 같은 우회 금지).
   - `collect\*.ps1` 에서 `Out-File`·`Set-Content`·`Add-Content`·`Export-Csv`·`>`·`>>` 로 `data\`·`store\` 아래에 쓰는 줄 금지(정규식: `(?i)(Out-File|Set-Content|Add-Content|Export-Csv)\b[^\r\n]*(data|store)\\` 및 `>>?\s*[^\r\n]*(data|store)\\`). 상태 파일은 정제 파이프가 대신 쓴다. 예외는 에이전트 운영 파일 `heartbeat.json`·`sampler_errors.log`(원문 없음 — 예외 타입·시각·건수만).
3. 런타임 표식: 저장 행에 `rules_ver`·`kid` 가 없으면 적재기가 그 행을 버리고 `err.unsealed_row` 로 센다.

### 3.5 정제 파이프 — PowerShell 수집기·상주 샘플러 연동 (H8)

PowerShell 수집기(Outlook COM·색인, Teams UIA, 창 샘플러, 이벤트·파일 수확기)는 원문을 **표준입력 파이프로만** 파이썬 정제기에 넘긴다. 파일·임시파일 경유 금지.

호출(인자 이름은 이것 하나로 고정):
```
<PY> -X utf8 -I -B "<LM27>\lm27_pipe.py" --kind mail --src mail.com --pc <pc_id> --out "<세그먼트 경로>" [--mode new|append]
<PY> -X utf8 -I -B "<LM27>\lm27_pipe.py" --route-by-kind --src mail.com --pc <pc_id> --out "<경로 — {kind} 자리표시자 포함>"
```
- `<PY>`·`<LM27>`: 프로그램 폴더 실행이면 `<ROOT>\python\python.exe`·`<ROOT>`, 에이전트 실행이면 `%LOCALAPPDATA%\LoadMonitor27\agent\bin\<ver>\py311\python.exe`·`…\bin\<ver>\`(§3.6).
- `lm27_pipe.py` 는 첫 줄에서 자기 폴더를 `sys.path.insert(0, …)` 한다(동봉 파이썬 `python311._pth` 가 스크립트 폴더를 넣지 않음) → `lm27.privacy.sanitize_stream.main(sys.argv[1:])`.
- 키·문맥: 자기 폴더 옆에 `data\` 가 있으면 프로그램 폴더 모드(`load_keyring`), 없으면 에이전트 모드(`load_agent_keys`). 판정 결과를 요약 줄 `mode` 에 남긴다.
- `--kind`: KINDS 중 하나. `--route-by-kind`: 줄마다 `"_kind"` 필드(KINDS)를 읽어 kind 별 출력으로 나눈다 — `--out` 에 `{kind}` 자리표시자가 없으면 인자 오류. 두 옵션을 함께 주면 인자 오류.
- `--src`: 경로 ID(수집 공통 명세 §2). `rc.src` 와 행의 `src` 열이 된다. 줄의 원시 필드로 `src` 를 덮어쓸 수 없다.
- `--out`: 쓸 경로(배치·이름은 저장소·번들 명세 소유 — 정제 파이프는 받은 경로에만 쓴다). `--mode new`(기본): EOF 에서 전체를 임시 파일 `<out>.<pid>.part` 로 쓰고 `os.replace` — 중간 실패 시 파일 없음. `--mode append`(에이전트 일별 원장용): EOF 에서 gzip **멤버 하나**를 메모리에 만든 뒤 한 번의 `write` + `flush` + `os.fsync` 로 덧붙인다. 읽는 쪽은 마지막 멤버가 잘려 있으면(`EOFError`) 그 멤버만 버리고 `err.truncated_tail` 로 센다.
- 입력: UTF-8(BOM 없음 — 있으면 첫 줄에서 벗김), 한 줄 = 원시 레코드 JSON 1개(§10.2 의 원시 입력 필드). 빈 줄 무시. 한 줄 최대 1 MB(초과 줄은 `bad_raw`).
- 처리: 줄마다 `sanitize_record()` → `stored` 는 메모리 버퍼 → EOF 에서 위 규칙으로 기록. 감사 이벤트도 같은 EOF 에서 1줄(§15).
- 출력: stdout 에 **EOF 후 요약 1줄만** `{"ok": true, "mode": "agent", "rows_in": 812, "stored": 640, "dropped": {"ad": 160, "cred": 2}, "errors": {"KeyError": 0}, "rules_ver": "2026.10.0", "kid": "k1a2b3c4d", "out_sha256": "<16hex>"}`. 줄마다 응답하지 않는다(파이프 버퍼 교착 방지).
- stderr: 예외 타입명과 줄 번호만. 원문·정제문 금지.
- 종료 코드: `0` 정상, `2` 입력 형식 오류 줄 존재(그 줄만 버리고 계속, 요약에 건수), `3` 정제기 내부 오류로 중단(출력 미기록), `5` 인자 오류(출력 미기록), `6` 키 없음(에이전트 모드에서 subkeys.json 없음·손상 — 키가 필요 없는 kind 만 처리하고 나머지는 `no_key` 로 셈, §9.4).

PowerShell 쪽 골격(UTF-8 BOM + CRLF 로 저장):
```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PyExe
$psi.Arguments = ('-X utf8 -I -B "{0}" --kind mail --src mail.com --pc {1} --out "{2}"' -f $PipePy, $PcId, $OutPath)
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$psi.CreateNoWindow = $true
$p = [System.Diagnostics.Process]::Start($psi)
# .NET Framework 4.x 에는 StandardInputEncoding 이 없다 → BaseStream 을 UTF-8(BOM 없음) 으로 감싼다
$sw = New-Object System.IO.StreamWriter($p.StandardInput.BaseStream, (New-Object System.Text.UTF8Encoding($false)))
$sw.NewLine = "`n"
$errTask = $p.StandardError.ReadToEndAsync()          # stderr 버퍼 교착 방지
try {
    foreach ($rec in $records) {                       # $rec = 원시 입력 필드 hashtable (메모리)
        $sw.WriteLine(($rec | ConvertTo-Json -Compress -Depth 4))
    }
} finally { $sw.Close() }
$summary = $p.StandardOutput.ReadToEnd()
if (-not $p.WaitForExit($WaitMs)) { $p.Kill(); $code = 99 } else { $code = $p.ExitCode }   # $WaitMs = privacy.pipe.wait_sec × 1000
$records = $null; [GC]::Collect()                      # 원문 참조 해제(보장 아님 — 비목표 2.3)
if ($code -ne 0) { <# 수집 상태 '정제기 실패'(사유 코드만) 기록 — 원문 대체 저장 절대 금지 #> }
```
- 파이프가 끊기면(`IOException`) 즉시 중단하고 상태만 남긴다. 재시도는 다음 수집 주기에서(원문은 원천에 그대로 있으므로 손실 없음).
- `ConvertTo-Json` 은 PS 5.1 에서 일부 문자를 `\u003c` 등으로 이스케이프한다 — 파이썬 `json.loads` 가 그대로 복원하므로 처리 불필요. `-Depth 4` 를 넘는 원시 필드는 두지 않는다(§10.2 원시 입력은 최대 2단).
- 파이썬 수집기는 파이프를 쓰지 않고 `from lm27.privacy.sanitize import sanitize_record, make_record_context` 로 in-process 호출한 뒤 `SegmentWriter.append(outcome.row)`.

### 3.6 PC 상주 에이전트의 정제기 (H15)

- 설치 전용 진입점과 [수집]은 `<ROOT>\python\`(동봉 런타임)과 `<ROOT>\lm27\privacy\`·`<ROOT>\lm27_pipe.py` 를 `%LOCALAPPDATA%\LoadMonitor27\agent\bin\<ver>\` 아래 `py311\`·`lm27\privacy\`·`lm27_pipe.py` 로 복사한다(같은 판이면 sha256 대조만). 복사본의 `RULES_HASH` 가 `rules.lock.json` 과 다르면 에이전트는 수집을 멈추고 `R-RULESMISMATCH` 를 heartbeat 에 남긴다(조용한 축약 정제 금지).
- 에이전트는 프로그램 폴더가 없어도(폴더를 PC2 로 옮긴 뒤) 완전한 정제기로 계속 수집한다. 사람 사전·고객사 사전·설정은 [수집] 때 `agent\context_cache.json`(정제 설정만: 사전 이름 목록·허용 패턴·문맥어 — 키 없음)으로 내려 준다. 사전에 실명(고객사명·동료 표시명)이 들어 있으므로 이 파일도 `local_only` 와 같은 보호 대상이다.
- PS 샘플러가 플러시할 때 부르는 파이프는 에이전트 bin 의 것이다(`--mode append`, 일별 원장).

---

## 4. 정제 파이프라인 `sanitize()` — 단계 순서

순서는 규칙의 일부다(바꾸면 `RULES_HASH` 가 바뀌지 않아도 결과가 달라지므로 §16 의 버전 상향 대상).

| 단계 | 내용 | 비고 |
|---|---|---|
| 0 | 빈 값이면 `""` 반환. 입력 앞 **4,000자**만 취함 → NFKC 정규화 → 제어문자·폭 0 문자·사설 영역 문자(U+E000–F8FF)를 공백으로 | NFKC 부수효과: `㈜→(주)`, 전각 숫자→반각, `²→2`, `℃→°C` (저장 정제문에 반영됨) |
| 1 | **자격증명** 검사 → 걸리면 `drop=True, hits={"cred":1}` 즉시 반환 | 행 폐기 |
| 2 | 보호 구간: ① 기존 토큰(멱등) ② 조직 허용 패턴 → 사설 영역 자리표시자로 치환 | 이후 탐지기가 못 건드림 |
| 3 | 생년월일 라벨형, 주민번호 앞자리 라벨형 → 토큰 | 날짜 보호보다 먼저 |
| 4 | 보호 구간: 날짜(YYYY-MM-DD 류·YYYYMMDD)·시각·버전·규격번호 | 오탐 방지의 핵심 |
| 5 | URL → 이메일(도메인 라벨화 — 로컬파트는 버림) → 파일 경로(기본 이름만 남김) | |
| 6 | 사전 가명화: 고객사 → 협력사 → 과제 코드네임 → 본인 → 사람 사전 | §8, §9 |
| 7 | 이름 문맥 규칙: 멘션(`@이름`) → 라벨형(`예금주: 이름`) → 호칭형(`이름 책임`) | §5.8 |
| 8 | 숫자형 PII(고정 순서): 주민·외국인등록 → 카드 → 전화(휴대·유선·대표·국제) → 사업자·법인 → 여권 → 운전면허 → 계좌 → IPv4 → IPv6 | 긴 패턴·체크섬 있는 것 먼저 |
| 9 | 금액: 비율 → 통화 기호 → 한국어 단위 → 통화 접미 → 금액어 인접 → 문맥 맨숫자 | §7 |
| 10 | 회사 접미형(`(주)XXX`, `XXX Co., Ltd.`) → `[회사]` | 설정으로 끌 수 있음 |
| 11 | 자리표시자 복원 → 공백 연속 축약 → `max_len` 이 있으면 **토큰을 자르지 않는** 절단(§6 `_safe_truncate`) | |

모든 토큰은 생성 즉시 자리표시자로 보호되므로 뒤 단계 탐지기가 토큰 안의 16진수·숫자를 다시 잡지 않는다.

---

## 5. 탐지 규칙 원문 — `lm27/privacy/rules.py`

아래 코드는 검증 시제품과 같은 정규식이다(파이썬 `re` 문법 그대로). 구현자는 이 블록을 그대로 `rules.py` 로 옮긴다. 한 글자라도 바꾸면 `RULES_HASH` 가 바뀌어 §18 관문이 실패한다 — 의도된 변경이면 §16.4 절차를 따른다.

### 5.1 ~ 5.8 규칙 코드

```python
# lm27/privacy/rules.py
# -*- coding: utf-8 -*-
"""LM27 정제 규칙 — 버전 고정. 조직별 보정은 설정의 허용 패턴·문맥어로만(§17)."""
from __future__ import annotations

import calendar
import re

RULES_VERSION = "2026.10.0"

# ── 5.1 공통 경계 ─────────────────────────────────────────────────────────────
NB = r"(?<![0-9A-Za-z])"                    # 앞에 영숫자 없음
NA = r"(?![0-9A-Za-z])"                     # 뒤에 영숫자 없음
NBX = r"(?<![0-9A-Za-z\-./\\])"             # 코드 일부가 아님(앞에 영숫자·-·.·/·\ 없음) — DWG-2026-… 차단. '_' 는 파일명 구분자로 허용
NAX = r"(?![0-9A-Za-z]|[-/][0-9A-Za-z]|\.(?![A-Za-z]{2,5}(?![0-9A-Za-z]))[0-9A-Za-z])"  # 뒤에 영숫자·'구분자+영숫자' 없음(.pdf 같은 확장자는 허용)
NBP = r"(?<![0-9A-Za-z+/\\\-])"             # 전화용 앞 경계('.'·':'·'('·'_' 허용 → Tel.010…, 견적_010…)
NAP = r"(?![0-9A-Za-z]|-\d)"                # 전화용 뒤 경계

# ── 5.2 토큰 문법 (이 정규식에 맞는 문자열만 '기존 토큰'으로 보호 → 멱등) ────────────
TOKEN_RX = re.compile(
    r"\[(?:주민번호|외국인등록번호|생년월일|카드|전화|사업자번호|법인번호|여권|운전면허|계좌|IP|URL|경로|금액|비율|회사|나"
    r"|사람(?:#[0-9a-f]{6})?|고객사:[A-Za-z0-9_\-]{1,16}|과제:[A-Za-z0-9_\-]{1,16}|협력사:[A-Za-z0-9_\-]{1,16}"
    r"|이메일@[A-Za-z0-9.\-:가-힣]{1,64})]")

# ── 5.3 보호 구간 (탐지 전에 자리표시자로 가림) ─────────────────────────────────
PROTECT = [
    ("date", re.compile(NB + r"(?:19|20)\d{2}([-./])(?:0?[1-9]|1[0-2])\1(?:0?[1-9]|[12]\d|3[01])" + NA)),
    ("date8", re.compile(NB + r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])" + NA)),
    ("time", re.compile(NB + r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?" + NA)),
    ("version", re.compile(r"(?i)(?:(?<![A-Za-z])(?:rev|ver|version|v|build|fw|sw|release)[._\s-]?"
                           r"|(?:버전|빌드|펌웨어|릴리스|개정)[_\s]?)\d+(?:\.\d+){1,3}")),
    ("std", re.compile(r"(?<![A-Za-z])(?:IEC|ISO|IEEE|KS\s?[A-Z]?|JIS|ASTM|MIL-STD|UL|EN|CISPR|SAE|JEDEC|IPC)"
                       r"[\s-]?\d{2,6}(?:[-.:]\d{1,4})*")),
]

# ── 5.4 자격증명 (하나라도 걸리면 행 폐기) ──────────────────────────────────────
CRED_KV = re.compile(
    r"(?i)(?:비밀번호|비번|패스워드|암호|password|passwd|pwd|pw|passcode|pin)\s*(?:[:=：]|은|는|is)\s*(?P<v>[^\s,;]{4,64})")
CRED_OTP = re.compile(r"(?i)(?:인증\s?번호|인증\s?코드|보안\s?코드|otp|verification\s?code)\s*(?:[:=：]|은|는|is)?\s*\[?\d{4,8}\]?")
CRED_TOKEN = re.compile(
    r"(?:eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
    r"|(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9\-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9_\-.=]{20,})")
CRED_APIKEY = re.compile(
    r"(?i)(?:api[_\-]?key|secret|access[_\-]?key|client[_\-]?secret|token|private[_\-]?key|connection\s?string)"
    r"\s*[:=：]\s*['\"]?(?P<v>[A-Za-z0-9_\-+/=.]{12,})")
CRED_STOP = re.compile(
    r"^(?:[가-힣]+|reset|change|changed|expired|expire|policy|required|update|updated|변경|재설정|초기화|만료|정책)$", re.I)


def _cred_value_ok(v: str) -> bool:
    """값처럼 보이면 True: 한글뿐·불용어가 아니고 (숫자 or 기호 or 대소문자 혼합)."""
    if CRED_STOP.match(v):
        return False
    has_digit = any(c.isdigit() for c in v)
    has_sym = any(not c.isalnum() for c in v)
    mixed = any(c.isupper() for c in v) and any(c.islower() for c in v)
    return has_digit or has_sym or mixed


def credential_hit(text: str) -> bool:
    for m in CRED_KV.finditer(text):
        if _cred_value_ok(m.group("v")):
            return True
    return bool(CRED_OTP.search(text) or CRED_TOKEN.search(text) or CRED_APIKEY.search(text))


# ── 5.5 문맥 사전 · 억제 문맥 ──────────────────────────────────────────────────
CTX = {
    "rrn": r"(?:주민|생년월일|외국인\s?등록|등록번호|resident)",
    "card": r"(?:카드|card|결제|신용|체크|visa|master|amex)",
    "brn": r"(?:사업자|등록번호|거래처|법인|business\s?(?:no|number|registration))",
    "corp": r"(?:법인\s?등록|법인번호)",
    "passport": r"(?:여권|passport|비자|visa|출입국|출국|입국|항공권|발권|e-?ticket|탑승)",
    "license": r"(?:면허|운전|license|licence|driver)",
    "account_strong": r"(?:계좌|입금|송금|이체|예금주|account\s?(?:no|number|#)|acct)",
    "account_weak": r"(?:은행|뱅크|bank|농협|수협|신협|새마을금고|우체국|증권|국민은행|우리은행|하나은행|신한은행|기업은행|SC제일|씨티)",
    "ip": r"(?:ip|서버|server|host|호스트|접속|주소|address|vpn|ssh|rdp|ping|gateway|게이트웨이|dns|http|ftp|방화벽|firewall)",
    "phone_rep": r"(?:대표|고객센터|콜센터|상담|문의|전화|tel|☎|call)",
    "money": r"(?:수주|계약|견적|단가|매출|매입|발주|입찰|투찰|낙찰|네고|금액|가격|비용|예산|대금|원가|판가|공급가|부가세|vat|price"
             r"|cost|quote|quotation|amount|revenue|budget|invoice|인보이스|(?<![A-Za-z])PO(?![A-Za-z]))",
}
# 공학·식별 억제 문맥: 후보 바로 앞 10자 안에 있으면 문맥 게이트형 탐지(여권·면허·계좌·체크섬 실패 카드 등)를 하지 않는다
ENG_CTX = re.compile(r"(?i)(?:문서\s?번호|도면|도번|dwg|부품|품번|p/?n|s/?n|시리얼|serial|lot|로트|관리\s?번호|접수\s?번호"
                     r"|과제\s?번호|eco|ecn|품목|코드|code|모델|model|rev|ver)")
ID_BEFORE = re.compile(r"(?i)(?:(?<![A-Za-z])(?:po|pr|so|no|order)|오더|번호|코드|#)\s*[:.#]?\s*$")
ENG_UNIT_AFTER = re.compile(
    r"(?i)^\s?(?:mm|cm|um|μm|µm|nm|km|m|mil|inch|in|kg|mg|g|ton|t|kn|n|mpa|kpa|gpa|pa|bar|psi|kv|mv|v|ma|ua|a|mw|kw|w|kwh|wh|mah|ah|"
    r"ghz|mhz|khz|hz|rpm|°c|°f|℃|k|%|ppm|ppb|dbm|db|lux|lx|lm|cd|ea|pcs|set|lot|px|dpi|fps|ms|us|μs|ns|sec|s|min|hrs|hr|h|"
    r"tb|gb|mb|kb|gbps|mbps|bps|bit|cells|cell|nodes|elements|cycles|times|"
    r"개|대|매|장|셀|노드|요소|회|번|건|명|시간|분|초|일|주|개월|년|층|차|호|점|줄|행|열|쪽|페이지|화소|세트)(?![A-Za-z가-힣])")
COUNT_AFTER = re.compile(r"^\s?(?:회|개|셀|화소|명|건|대|장|매|시간|번|세트|ea|pcs|km|rpm|cycles|대수|가지|종|개소|라인)", re.I)
DIM_NEAR = re.compile(r"^\s?[xX×*]\s?\d|(?:[xX×*])\s?$")      # 1,200 x 800 같은 치수


# ── 5.6 체크섬 ──────────────────────────────────────────────────────────────────
def luhn_ok(d: str) -> bool:
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def rrn_checksum_ok(d13: str) -> bool:          # 2020-10 이후 발급분은 안 맞을 수 있음 → '가점'으로만 사용
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(a) * b for a, b in zip(d13[:12], w, strict=False))
    return (11 - s % 11) % 10 == int(d13[12])


def brn_ok(d10: str) -> bool:                   # 사업자등록번호
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(a) * b for a, b in zip(d10[:9], w, strict=False)) + (int(d10[8]) * 5) // 10
    return (10 - s % 10) % 10 == int(d10[9])


def rrn_date_ok(d: str) -> bool:                # 앞 6자리 생년월일 + 7번째 성별자리(1~8) 유효성
    yy, mm, dd, g = int(d[0:2]), int(d[2:4]), int(d[4:6]), int(d[6])
    if not 1 <= g <= 8:
        return False
    year = (1900 if g in (1, 2, 5, 6) else 2000) + yy
    if not 1 <= mm <= 12:
        return False
    return 1 <= dd <= calendar.monthrange(year, mm)[1]


# ── 5.7 탐지기 표 ───────────────────────────────────────────────────────────────
RX = {
    "birth": re.compile(
        r"(?i)(?:생년월일|출생일|출생|date\s?of\s?birth|birth\s?date|dob)\s*[:：]?\s*(?P<d>(?:19|20)?\d{2}\s?[-./년]\s?"
        r"(?:0?[1-9]|1[0-2])\s?[-./월]\s?(?:0?[1-9]|[12]\d|3[01])\s?일?|(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
        r"|\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![0-9])"),
    "rrn_front": re.compile(r"(?:주민|주민등록|주민번호)[^\d\n]{0,8}(?P<d>\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![0-9\-–—*])"),
    "rrn": re.compile(NB + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?P<sep>\s?[-–—]\s?|\s?)[1-8]\d{6}" + NA),
    "rrn_masked": re.compile(NB + r"\d{6}\s?[-–—]\s?[1-8](?:[*xX●○■]{6}|\d[*xX●○■]{5})"),
    "card16": re.compile(NB + r"(?:\d{4}[-\s]?){3}\d{4}" + NA),
    "card15": re.compile(NB + r"3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}" + NA),
    "card_masked": re.compile(NB + r"\d{4}[-\s]?(?:[*xX●]{4}[-\s]?){2}\d{4}" + NA),
    "mobile": re.compile(NBP + r"(?:(?:\+|00)82[-.\s]?(?:\(0\))?\s?1[016789]|01[016789])[-.\s)]{0,2}\d{3,4}[-.\s]{0,2}\d{4}" + NAP),
    "landline": re.compile(NBP + r"\(?0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70|50[2-8])\)?[-.\s)]{1,2}\d{3,4}[-.\s]\d{4}" + NAP),
    "rep": re.compile(NBP + r"1(?:5[4-9]\d|6[0-9]\d|8[0-9]\d)-\d{4}" + NAP),
    "intl": re.compile(r"(?<![0-9A-Za-z])\+(?!82)\d{1,3}[-.\s]?\(?\d{1,4}\)?(?:[-.\s]?\d{2,4}){2,3}" + NA),
    "brn": re.compile(NBX + r"\d{3}-\d{2}-\d{5}" + NAX),
    "brn_bare": re.compile(NBX + r"\d{10}" + NAX),
    "corp": re.compile(NBX + r"\d{6}-\d{7}" + NAX),
    "passport": re.compile(NBX + r"[MSRODG]\d{3}[A-Z0-9]\d{4}" + NAX),
    "license": re.compile(NBX + r"(?:1[1-9]|2[0-8])-?\d{2}-?\d{6}-?\d{2}" + NAX),
    "license_region": re.compile(r"(?:서울|부산|경기|강원|충북|충남|전북|전남|경북|경남|제주|대구|인천|광주|대전|울산)\s?\d{2}-\d{6}-\d{2}" + NAX),
    "account_hy": re.compile(NBX + r"\d{2,6}(?:-\d{2,7}){1,4}" + NAX),
    "account_bare": re.compile(NBX + r"\d{10,16}" + NAX),
    "ipv4": re.compile(r"(?<![0-9A-Za-z.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
                       r"(?P<port>:\d{2,5})?(?![0-9A-Za-z]|\.\d)"),
    "ipv6": re.compile(r"(?<![0-9A-Za-z:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z:])"),
    "url": re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"'\]\)]+|\bwww\.[A-Za-z0-9\-]+\.[^\s<>\"'\]\)]+"),
    "email": re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@(?P<dom>[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})"
                        r"(?![A-Za-z0-9\-])"),
    "path": re.compile(r"(?:(?<![A-Za-z0-9])[A-Za-z]:\\|\\\\[A-Za-z0-9._\-$]+\\)(?:[^\\/:*?\"<>|\r\n]+\\)*"
                       r"(?P<base>[^\\/:*?\"<>|\r\n\s][^\\/:*?\"<>|\r\n]*?)?(?=\s+-\s|\s{2}|$|[\"'<>|])"),
    # 금액 (§7)
    "money_cur": re.compile(
        r"(?:₩|\$|€|¥|£|(?<![A-Za-z])(?:KRW|USD|US\$|EUR|JPY|CNY|RMB|GBP)(?![A-Za-z]))\s?\d[\d,]{0,24}(?:\.\d+)?"
        r"(?:\s?(?:[KMB](?![A-Za-z])|천만|백만|십만|천|만|억|조|million|billion|mil|bn)(?![A-Za-z]))?"
        r"|\\\d{1,3}(?:,\d{3})+"),
    "money_kor": re.compile(
        NB + r"\d[\d,]{0,24}(?:\.\d+)?\s?(?:조|억|천만|백만|십만|만|천)(?:\s?\d[\d,]{0,24}(?:\.\d+)?\s?(?:억|천만|백만|십만|만|천))*"
        r"(?P<cur>\s?(?:원|달러|유로|엔|위안))?"),
    "money_suffix": re.compile(
        NB + r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?:원|달러|유로|엔|위안|파운드|USD|KRW|EUR|JPY|CNY)"
        r"(?=$|[^가-힣A-Za-z0-9]|(?:이|은|을|의|에|으로|과|와|도|씩|대|선|짜리|정도|가량|까지|부터|이며|이고|입니다|이다|임)(?![가-힣]))"),
    "money_kw_adj": re.compile(
        r"(?i)(?P<kw>단가|금액|가격|견적가|공급가|판가|원가|계약금|대금|매출|수주액|수주\s?금액|price|amount|cost)\s*"
        r"(?:[:：=]|은|는|이|가|도)?\s*(?P<num>\d[\d,]{0,24}(?:\.\d+)?)" + NA),
    "money_bare": re.compile(NBX + r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)" + NAX),
    "rate": re.compile(r"(?i)(?P<kw>할인율|할인|인하율|인하|네고율|마진율|마진|이익률|dc|discount|margin)\s*(?:[:：=]|은|는|을|를)?\s*"
                       r"(?P<num>\d+(?:\.\d+)?\s?%)"),
    "company": re.compile(
        r"(?:\(주\)|\(유\)|\(재\)|\(사\)|주식회사|유한회사)\s?[가-힣A-Za-z0-9&]{2,20}|[가-힣A-Za-z0-9&]{2,20}\s?(?:\(주\)|주식회사)"
        r"|[A-Z][A-Za-z0-9&]{1,20}(?:\s[A-Z][A-Za-z0-9&]{1,20}){0,2},?\s(?:Co\.,?\s?Ltd\.?|Inc\.|Corp\.|GmbH|LLC|Ltd\.)"),
}

# ── 5.8 이름(호칭·멘션·라벨) ─────────────────────────────────────────────────────
SURNAMES = ("김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마"
            "길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부가복태목형피두감음빈동온호범좌팽승간상시갈단견당화창")
COMPOUND_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문", "동방")
TITLES = (r"(?:님|씨|책임|선임|수석|매니저|프로|팀장|파트장|그룹장|실장|센터장|본부장|부장|차장|과장|대리|사원|주임|연구원|위원|박사"
          r"|교수|님께)")
NAME_STOP = {"이번주", "지난주", "다음주", "이번달", "지난달", "다음달", "이번에", "우리측", "고객사", "협력사", "공급사", "제조사", "주관사",
             "발주처", "수요처", "담당자", "책임자", "관계자", "작성자", "검토자", "승인자", "요청자", "참석자", "사용자", "관리자", "운영자",
             "여러분", "선생님", "전체팀", "각부서"}
NAME_SUFFIX_STOP = ("팀", "측", "처", "실")
HONORIFIC = re.compile(r"(?<![가-힣])(?P<name>[가-힣]{2,4})\s?(?=" + TITLES
                       + r"(?:[^가-힣]|$|께|이|은|는|과|와|의|도|한테|에게|님))")
MENTION = re.compile(r"@(?P<name>[가-힣]{2,4}|[A-Za-z][A-Za-z.\-]{1,30})(?=[\s,.:)!?]|$)")
LABELED_NAME = re.compile(r"(?:예금주|성명|이름|수신인|받는\s?분|보내는\s?분|작성자|담당자)\s*[:：]?\s*(?P<name>[가-힣]{2,4})(?![가-힣])")


def plausible_korean_name(n: str) -> bool:
    """호칭형 후보가 사람 이름으로 그럴듯한가: 3자 + 흔한 성, 또는 4자 + 복성. 일반어·조직 접미 제외."""
    if n in NAME_STOP or n.endswith(NAME_SUFFIX_STOP):
        return False
    if len(n) == 3 and n[0] in SURNAMES:
        return True
    return len(n) == 4 and n[:2] in COMPOUND_SURNAMES


# 공용 개인 메일 도메인(내장 기본값 — 설정으로 추가·해제, §17)
PERSONAL_MAIL_DOMAINS = ("gmail.com", "naver.com", "daum.net", "hanmail.net", "kakao.com", "nate.com", "outlook.com",
                         "hotmail.com", "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me")

# 코파일럿 게이트에서 '잔여 시 행 제외'인 고위험 범주 (§13)
HIGH = {"rrn", "frn", "birth", "card", "passport", "license", "account", "phone", "email", "cred", "brn", "corp"}
```

### 5.9 탐지기별 판정 요약표

| 범주 코드 | 토큰 | 정규식 키 | 검증·문맥 | 억제 |
|---|---|---|---|---|
| `cred` | (행 폐기) | `CRED_*` | 값이 숫자·기호·대소문자 혼합일 때만(`비밀번호 변경 안내` 통과) | - |
| `birth` | `[생년월일]` | `birth` | 라벨(생년월일·출생·DOB) 바로 뒤 날짜 | - |
| `rrn` | `[주민번호]` | `rrn_front`, `rrn`, `rrn_masked` | 생년월일 유효 + 성별자리 1~8 + (하이픈 or 체크섬 or ±20자 문맥). 하이픈 없고 체크섬 실패·문맥 없음 → 통과(LOT 번호 보호). 2020-10 이후 발급분은 뒤 6자리가 임의라 체크섬이 맞지 않을 수 있으므로 체크섬은 '가점'일 뿐 필수 아님 | ENG_CTX |
| `frn` | `[외국인등록번호]` | `rrn` | 위와 같고 성별자리 5~8. 외국인등록번호 전용 체크섬은 쓰지 않는다(같은 2020-10 개편으로 무의미 — 형식·문맥이 판정) | ENG_CTX |
| `card` | `[카드]` | `card16`, `card15`, `card_masked` | Luhn 통과, 또는 Luhn 실패 + 카드 문맥. 가린 형태는 무조건 | ENG_CTX(S/N 등) |
| `phone` | `[전화]` | `mobile`, `landline`, `rep`, `intl` | 휴대(010·011·016~019, +82) 무조건 / 유선(지역번호+구분자 필수, 070·050x 포함) / 대표번호(15xx·16xx·18xx)는 ±15자 문맥 / `+국가번호` 무조건 | 유선·대표: ENG_CTX |
| `brn` | `[사업자번호]` | `brn`, `brn_bare` | 3-2-5 형식: 체크섬 or 문맥. 10자리 맨숫자: 문맥 **and** 체크섬 | ENG_CTX |
| `corp` | `[법인번호]` | `corp` | 6-7 형식 + `법인등록·법인번호` 문맥 (주민 규칙에 안 걸린 것만) | - |
| `passport` | `[여권]` | `passport` | M·S·R·O·D·G + 3숫자 + 영숫자 1 + 4숫자, ±25자 여권 문맥 필수(**문맥 게이트**) | ENG_CTX |
| `license` | `[운전면허]` | `license`, `license_region` | 숫자형은 ±25자 면허 문맥 필수(**문맥 게이트**), 지역명형은 형식만으로 | ENG_CTX |
| `account` | `[계좌]` | `account_hy`, `account_bare` | 숫자 10~16자리 + (강문맥: 앞 12자 안 계좌·입금·송금·이체·예금주 / 약문맥: ±20자 은행명) — **문맥 게이트**. 연도로 시작하는 후보는 강문맥 필수 | ENG_CTX |
| `email` | `[이메일@라벨]` | `email` | 로컬파트는 버리고 라벨만: 사내·개인메일·고객사:ID·협력사:ID·도메인(소문자) | - |
| `ip` | `[IP]` | `ipv4`, `ipv6` | `ipaddress` 로 검증. 사설·루프백·링크로컬은 무조건, 공인은 포트 or ±20자 문맥 | 버전 보호 구간 |
| `url` | `[URL]` | `url` | 무조건(쿼리에 계정·토큰이 들어갈 수 있음) | - |
| `path` | `[경로]\기본이름` | `path` | 드라이브·UNC 경로의 폴더 부분 전부 제거, 기본 이름은 뒤 단계에서 계속 정제 | - |
| `money`·`rate` | `[금액]`·`[비율]` | §7 | §7 | §7 |
| `customer`·`partner`·`project` | `[고객사:ID]`·`[협력사:ID]`·`[과제:ID]` | 사전(§8) | 경계 규칙 §8.2 | - |
| `person`·`self` | `[사람#6hex]`·`[나]` | 사전 + `MENTION`·`LABELED_NAME`·`HONORIFIC` | 호칭형은 `plausible_korean_name()` 통과만 | NAME_STOP |
| `company` | `[회사]` | `company` | (주)·주식회사·Co., Ltd. 등 접미·접두 | - |

---

## 6. `sanitize()` 본체 — `lm27/privacy/detect.py`

```python
# lm27/privacy/detect.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field

from .rules import *  # noqa: F403  (RX, CTX, PROTECT, TOKEN_RX, 체크섬, 이름 규칙 …)

CTRL_RX = re.compile("[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u2028-\u202e\ufeff\ue000-\uf8ff]")
MAX_SCAN = 4000            # 한 필드에서 검사하는 최대 글자 수(저장 상한보다 충분히 큼, 병적 입력 방어)


@dataclass
class SanitizeContext:
    internal_domains: list = field(default_factory=list)
    personal_mail_domains: list = field(default_factory=lambda: list(PERSONAL_MAIL_DOMAINS))  # noqa: F405
    customers: list = field(default_factory=list)
    partners: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    persons: dict = field(default_factory=dict)
    self_names: list = field(default_factory=list)
    allow_patterns: list = field(default_factory=list)
    extra_ctx: dict = field(default_factory=dict)
    mask_company_suffix: bool = True
    mask_rates: bool = True
    key: bytes = b"\x00" * 32
    person_subkey: bytes | None = None


@dataclass(frozen=True)
class SanitizeResult:
    text: str
    hits: dict
    drop: bool = False
    drop_reason: str | None = None
    rules_ver: str = RULES_VERSION  # noqa: F405


def subkey(master: bytes, purpose: str) -> bytes:
    return hmac.new(master, b"lm27:" + purpose.encode("ascii"), hashlib.sha256).digest()


def keyed_hex(master: bytes, purpose: str, value: str) -> str:
    return hmac.new(subkey(master, purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()


def norm_person(name: str) -> str:
    n = unicodedata.normalize("NFKC", name).lower()
    n = re.sub(r"\(.*?\)|\[.*?\]", "", n)
    n = re.sub(TITLES + r"$", "", n.strip())  # noqa: F405
    return re.sub(r"[\s.\-_·]", "", n)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _ctx_rx(ctx: SanitizeContext, key: str) -> str:
    base = CTX[key]  # noqa: F405
    extra = ctx.extra_ctx.get(key) or []
    return base if not extra else "(?:" + base + "|" + "|".join(re.escape(x) for x in extra) + ")"


def _safe_truncate(s: str, n: int) -> str:
    """토큰 중간을 자르지 않는다: 잘린 꼬리에 닫히지 않은 '[' (24자 이내)가 있으면 그 앞에서 자른다."""
    if len(s) <= n:
        return s
    cut = s[: n - 1]
    m = re.search(r"\[[^\[\]]{0,24}$", cut)
    if m:
        cut = cut[: m.start()]
    return cut.rstrip() + "…"


class _Ph:
    """보호 구간·토큰을 사설 영역 문자 자리표시자(\uE000 + 번호문자 + \uE001)로 바꿔 두고 마지막에 복원."""

    def __init__(self):
        self.items: list[str] = []

    def put(self, s: str) -> str:
        self.items.append(s)
        return "\ue000" + chr(0xE100 + len(self.items) - 1) + "\ue001"

    def restore(self, t: str) -> str:
        return re.sub("\ue000(.)\ue001", lambda m: self.items[ord(m.group(1)) - 0xE100], t)


def _dict_rx(names):
    """사전 매칭: 긴 이름 우선. ASCII 이름은 양쪽 영숫자 경계, 한글 포함 이름은 앞 경계만(뒤에는 조사가 붙음)."""
    names = sorted({n for n in names if n}, key=len, reverse=True)
    parts = []
    for n in names:
        e = re.escape(n)
        if re.fullmatch(r"[A-Za-z0-9 .&\-]+", n):
            parts.append(r"(?<![A-Za-z0-9])" + e + r"(?![A-Za-z0-9])")
        else:
            parts.append(r"(?<![가-힣A-Za-z0-9])" + e)
    return re.compile("|".join(parts), re.I) if parts else None


def sanitize(text: str, field_name: str = "text", ctx: SanitizeContext | None = None,
             max_len: int | None = None) -> SanitizeResult:
    ctx = ctx or SanitizeContext()
    hits: dict = {}

    def bump(k):
        hits[k] = hits.get(k, 0) + 1

    if not text:
        return SanitizeResult("", {})
    t = unicodedata.normalize("NFKC", text[:MAX_SCAN])
    t = CTRL_RX.sub(" ", t)

    # (1) 자격증명 → 행 폐기
    if credential_hit(t):  # noqa: F405
        return SanitizeResult("", {"cred": 1}, True, "cred")

    ph = _Ph()

    def tok(token: str, cat: str):
        bump(cat)
        return ph.put(token)

    def near(s, e, key, before=20, after=20):
        return re.search(_ctx_rx(ctx, key), t[max(0, s - before):e + after], re.I) is not None

    def eng_suppressed(s):
        return ENG_CTX.search(t[max(0, s - 10):s]) is not None  # noqa: F405

    # (2) 기존 토큰 보호(멱등) · 조직 허용 패턴
    t = TOKEN_RX.sub(lambda m: ph.put(m.group(0)), t)  # noqa: F405
    for p in ctx.allow_patterns:
        t = re.sub(p, lambda m: ph.put(m.group(0)), t)
    # (3) 라벨형 생년월일·주민 앞자리 (날짜 보호보다 먼저)
    t = RX["birth"].sub(lambda m: m.group(0)[:m.start("d") - m.start()] + tok("[생년월일]", "birth"), t)  # noqa: F405
    t = RX["rrn_front"].sub(lambda m: m.group(0)[:m.start("d") - m.start()] + tok("[주민번호]", "rrn"), t)  # noqa: F405
    # (4) 날짜·시각·버전·규격 보호
    for _, rx in PROTECT:  # noqa: F405
        t = rx.sub(lambda m: ph.put(m.group(0)), t)

    # (5) URL · 이메일 · 경로
    t = RX["url"].sub(lambda m: tok("[URL]", "url"), t)  # noqa: F405

    def email_rep(m):
        dom = m.group("dom").lower()
        label = dom
        if any(dom == d or dom.endswith("." + d) for d in ctx.internal_domains):
            label = "사내"
        elif dom in ctx.personal_mail_domains:
            label = "개인메일"
        else:
            for c in ctx.customers:
                if any(dom == d or dom.endswith("." + d) for d in c.get("domains", [])):
                    label = "고객사:" + c["id"]
            for v in ctx.partners:
                if any(dom == d or dom.endswith("." + d) for d in v.get("domains", [])):
                    label = "협력사:" + v["id"]
        return tok("[이메일@" + label + "]", "email")
    t = RX["email"].sub(email_rep, t)  # noqa: F405

    def path_rep(m):
        bump("path")
        base = m.group("base") or ""
        return ph.put("[경로]") + ("\\" + base if base else "")
    t = RX["path"].sub(path_rep, t)  # noqa: F405

    # (6) 사전 가명화: 고객사 → 협력사 → 과제 코드네임 → 본인 → 사람 사전
    for c in ctx.customers:
        rx = _dict_rx(c.get("names", []))
        if rx:
            t = rx.sub(lambda m, c=c: tok("[고객사:" + c["id"] + "]", "customer"), t)
    for v in ctx.partners:
        rx = _dict_rx(v.get("names", []))
        if rx:
            t = rx.sub(lambda m, v=v: tok("[협력사:" + v["id"] + "]", "partner"), t)
    for p in ctx.projects:
        rx = _dict_rx(p.get("codenames", []))
        if rx:
            t = rx.sub(lambda m, p=p: tok("[과제:" + p["id"] + "]", "project"), t)
    rx = _dict_rx(ctx.self_names)
    if rx:
        t = rx.sub(lambda m: tok("[나]", "self"), t)

    def person_token(name: str) -> str:
        v = "name:" + norm_person(name)
        pk = ctx.persons.get(name) or (hmac.new(ctx.person_subkey, v.encode("utf-8"), hashlib.sha256).hexdigest()
                                       if ctx.person_subkey else keyed_hex(ctx.key, "person", v))
        return "[사람#" + pk[:6] + "]"
    rx = _dict_rx(list(ctx.persons.keys()))
    if rx:
        t = rx.sub(lambda m: tok(person_token(m.group(0)), "person"), t)

    # (7) 이름 문맥 규칙: 멘션 → 라벨형 → 호칭형
    def name_sub(require_plausible: bool):
        def rep(m):
            n = m.group("name")
            if require_plausible and re.fullmatch(r"[가-힣]+", n) and not plausible_korean_name(n):  # noqa: F405
                return m.group(0)
            s, e = m.span("name")
            return m.group(0)[:s - m.start()] + tok(person_token(n), "person") + m.group(0)[e - m.start():]
        return rep
    t = MENTION.sub(name_sub(False), t)  # noqa: F405
    t = LABELED_NAME.sub(name_sub(False), t)  # noqa: F405
    t = HONORIFIC.sub(name_sub(True), t)  # noqa: F405

    # (8) 숫자형 PII — 순서 고정
    def v_rrn(m):
        d = _digits(m.group(0))
        if not rrn_date_ok(d):  # noqa: F405
            return m.group(0)
        hy = any(ch in m.group(0) for ch in "-–—")
        ok = (hy and not eng_suppressed(m.start())) or (rrn_checksum_ok(d) and not eng_suppressed(m.start()))  # noqa: F405
        ok = ok or near(m.start(), m.end(), "rrn")
        if not ok:
            return m.group(0)
        return tok("[외국인등록번호]", "frn") if d[6] in "5678" else tok("[주민번호]", "rrn")
    t = RX["rrn"].sub(v_rrn, t)  # noqa: F405
    t = RX["rrn_masked"].sub(  # noqa: F405
        lambda m: tok("[외국인등록번호]" if _digits(m.group(0))[6:7] in ("5", "6", "7", "8") else "[주민번호]", "rrn"), t)

    def v_card(m):
        d = _digits(m.group(0))
        if eng_suppressed(m.start()):
            return m.group(0)
        if luhn_ok(d) or near(m.start(), m.end(), "card"):  # noqa: F405
            return tok("[카드]", "card")
        return m.group(0)
    t = RX["card16"].sub(v_card, t)  # noqa: F405
    t = RX["card15"].sub(v_card, t)  # noqa: F405
    t = RX["card_masked"].sub(lambda m: tok("[카드]", "card"), t)  # noqa: F405

    t = RX["mobile"].sub(lambda m: tok("[전화]", "phone"), t)  # noqa: F405
    t = RX["landline"].sub(lambda m: m.group(0) if eng_suppressed(m.start()) else tok("[전화]", "phone"), t)  # noqa: F405
    t = RX["rep"].sub(lambda m: tok("[전화]", "phone")  # noqa: F405
                      if near(m.start(), m.end(), "phone_rep", 15, 5) and not eng_suppressed(m.start()) else m.group(0), t)
    t = RX["intl"].sub(lambda m: tok("[전화]", "phone"), t)  # noqa: F405

    def v_brn(m):
        if eng_suppressed(m.start()):
            return m.group(0)
        if brn_ok(_digits(m.group(0))) or near(m.start(), m.end(), "brn"):  # noqa: F405
            return tok("[사업자번호]", "brn")
        return m.group(0)
    t = RX["brn"].sub(v_brn, t)  # noqa: F405
    t = RX["brn_bare"].sub(lambda m: tok("[사업자번호]", "brn")  # noqa: F405
                           if near(m.start(), m.end(), "brn") and brn_ok(m.group(0)) and not eng_suppressed(m.start())  # noqa: F405
                           else m.group(0), t)
    t = RX["corp"].sub(lambda m: tok("[법인번호]", "corp") if near(m.start(), m.end(), "corp", 15, 5) else m.group(0), t)  # noqa: F405

    t = RX["passport"].sub(lambda m: tok("[여권]", "passport")  # noqa: F405
                           if near(m.start(), m.end(), "passport", 25, 25) and not eng_suppressed(m.start()) else m.group(0), t)
    t = RX["license"].sub(lambda m: tok("[운전면허]", "license")  # noqa: F405
                          if near(m.start(), m.end(), "license", 25, 25) and not eng_suppressed(m.start()) else m.group(0), t)
    t = RX["license_region"].sub(lambda m: tok("[운전면허]", "license"), t)  # noqa: F405

    def v_acct(m):
        g = m.group(0)
        if not 10 <= len(_digits(g)) <= 16 or eng_suppressed(m.start()):
            return g
        strong = re.search(_ctx_rx(ctx, "account_strong"), t[max(0, m.start() - 12):m.start()], re.I) is not None
        weak = near(m.start(), m.end(), "account_strong") or near(m.start(), m.end(), "account_weak")
        year_led = re.match(r"(?:19|20)\d{2}(?:-|$)", g) is not None or re.match(r"(?:19|20)\d{6}", g) is not None
        if year_led and not strong:
            return g
        return tok("[계좌]", "account") if (strong or weak) else g
    t = RX["account_hy"].sub(v_acct, t)  # noqa: F405
    t = RX["account_bare"].sub(v_acct, t)  # noqa: F405

    def v_ip(m):
        g = m.group(0)
        try:
            ip = ipaddress.ip_address(g.split(":")[0])
        except ValueError:
            return g
        if ip.is_private or ip.is_loopback or ip.is_link_local or m.group("port") or near(m.start(), m.end(), "ip"):
            return tok("[IP]", "ip")
        return g
    t = RX["ipv4"].sub(v_ip, t)  # noqa: F405

    def v_ip6(m):
        g = m.group(0)
        if g.count(":") < 2 or not re.search(r"[0-9A-Fa-f]", g):
            return g
        try:
            ipaddress.IPv6Address(g)
        except ValueError:
            return g
        return tok("[IP]", "ip")
    t = RX["ipv6"].sub(v_ip6, t)  # noqa: F405

    # (9) 금액·비율 (§7)
    if ctx.mask_rates:
        t = RX["rate"].sub(lambda m: m.group(0)[:m.start("num") - m.start()] + tok("[비율]", "rate"), t)  # noqa: F405
    t = RX["money_cur"].sub(lambda m: tok("[금액]", "money"), t)  # noqa: F405

    def v_kor(m):
        after = t[m.end():m.end() + 6]
        if m.group("cur"):
            return tok("[금액]", "money")
        if COUNT_AFTER.match(after) or ENG_UNIT_AFTER.match(after):  # noqa: F405
            return m.group(0)
        if "억" in m.group(0) or near(m.start(), m.end(), "money", 20, 10):
            return tok("[금액]", "money")
        return m.group(0)
    t = RX["money_kor"].sub(v_kor, t)  # noqa: F405

    def v_suffix(m):
        num = m.group("num")
        if "," in num or len(_digits(num)) >= 3 or near(m.start(), m.end(), "money", 20, 10):
            return tok("[금액]", "money")
        return m.group(0)
    t = RX["money_suffix"].sub(v_suffix, t)  # noqa: F405

    def v_kw_adj(m):
        after = t[m.end():m.end() + 6]
        if ENG_UNIT_AFTER.match(after) or COUNT_AFTER.match(after) or DIM_NEAR.match(after):  # noqa: F405
            return m.group(0)
        return m.group(0)[:m.start("num") - m.start()] + tok("[금액]", "money")
    t = RX["money_kw_adj"].sub(v_kw_adj, t)  # noqa: F405

    def v_bare(m):
        s, e = m.start(), m.end()
        if not re.search(_ctx_rx(ctx, "money"), t[max(0, s - 20):e + 10], re.I):
            return m.group(0)
        after, before = t[e:e + 6], t[max(0, s - 4):s]
        if ENG_UNIT_AFTER.match(after) or COUNT_AFTER.match(after) or DIM_NEAR.match(after) or DIM_NEAR.search(before):  # noqa: F405
            return m.group(0)
        if ID_BEFORE.search(t[max(0, s - 8):s]) or eng_suppressed(s):  # noqa: F405
            return m.group(0)
        return tok("[금액]", "money")
    t = RX["money_bare"].sub(v_bare, t)  # noqa: F405

    # (10) 회사 접미형
    if ctx.mask_company_suffix:
        t = RX["company"].sub(lambda m: tok("[회사]", "company"), t)  # noqa: F405

    # (11) 복원·정리·절단
    out = re.sub(r"[ \t]{2,}", " ", ph.restore(t)).strip()
    if max_len:
        out = _safe_truncate(out, max_len)
    return SanitizeResult(out, hits)
```

구현 주의:
- `re.sub` 의 치환 함수 안에서 참조하는 `t` 는 **치환 전 문자열**이다(파이썬은 `sub` 가 끝난 뒤 대입). 위치 계산이 이 성질에 기대므로 단계를 한 줄씩 유지한다.
- `ctx.allow_patterns` 와 사전 정규식은 `build_context()` 에서 미리 컴파일·캐시한다(위 코드는 명료성을 위해 매번 컴파일). 캐시 키는 `config_hash`(§16.3).
- `person_token` 의 세 갈래는 같은 값을 낸다: `hmac(subkey(key,"person"), v) == keyed_hex(key,"person",v)`. 에이전트는 주 키 대신 `person_subkey = subkey(주 키, "person")` 만 받으므로(§9.4) PC1 에이전트와 클라우드PC 적재기가 같은 이름에 같은 `[사람#…]` 태그를 붙인다.
- 성능 기준(초판 시제품 실측, 일반 PC): 평균 113자 행 20,000개 1.9초(0.095ms/행). 병적 입력(`"1,"×8000`, `"@"×10000` 등) 각 5ms 이하 — `\d[\d,]{0,24}` 처럼 반복 상한을 둔 것이 이차 시간 역추적을 막는다(상한 없을 때 2.1초 실측). **새 정규식에 무한 반복 `*`/`+` 를 숫자·구분자 묶음에 쓰지 말 것.**

### 6.2 `scan()`·`tokens_of()` — `lm27/privacy/scan.py` (H3·H9)

```python
# lm27/privacy/scan.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass

from .detect import SanitizeContext, sanitize


@dataclass(frozen=True)
class Hit:
    cat: str      # §15.3 범주 코드
    n: int        # 건수


def scan(text: str, ctx: SanitizeContext | None = None) -> list:
    """치환 없이 탐지만: 남아 있는 PII·금액·이메일·경로 등을 범주별 건수로. 값·위치는 돌려주지 않는다(I8).
    이미 정제된 문자열이면(토큰은 보호 구간) 빈 목록."""
    r = sanitize(text, "scan", ctx)
    if r.drop:
        return [Hit("cred", 1)]
    return [Hit(k, v) for k, v in sorted(r.hits.items())]


TOKEN_SPLIT = re.compile(r"\[[^\[\]]{1,40}\]|[0-9A-Za-z가-힣][0-9A-Za-z가-힣._\-]*")


def tokens_of(masked: str, max_tokens: int = 30) -> list:
    """정제문 → 토큰 목록(수집 공통 명세 §3.1 subject_tokens 의 정의). [전화] 같은 토큰은 한 덩어리로 유지,
    일반 낱말은 24자에서 자른다. 저장하지 않고 적재 때마다 다시 만든다(결정적)."""
    out = []
    for m in TOKEN_SPLIT.finditer(masked or ""):
        w = m.group(0)
        if len(w) > 24 and not w.startswith("["):
            w = w[:24]
        out.append(w)
        if len(out) >= max_tokens:
            break
    return out
```

- 예: `tokens_of("RE: [과제:P-0001] 샘플 시험 결과 [전화]")` → `["RE", "[과제:P-0001]", "샘플", "시험", "결과", "[전화]"]`.
- `scan()` 은 팀/번들 명세의 업로드 전 검사, 감사 화면 '정제 시험대', 게이트 최종 검사(§13.3)가 공용으로 쓴다. 반환값에 원문 조각이 없으므로 로그에 그대로 남겨도 된다.

---

## 7. 금액·수주·견적 규칙과 공학 오탐 방지

### 7.1 규칙 (순서대로 적용)

| 순 | 규칙 | 조건 | 예(합성) |
|---|---|---|---|
| M1 비율 | `rate` | 할인·인하·네고율·마진·이익률 뒤 `%` 숫자 → `[비율]` (`privacy.money.mask_rates`) | `네고율 5% 인하` → `네고율 [비율] 인하` |
| M2 통화 기호·코드 | `money_cur` | `₩ $ € ¥ £ KRW USD EUR JPY CNY RMB GBP` + 숫자(+K/M/B·만·억) → 무조건 | `USD 1250000`, `$1.2M`, `₩1,500,000` |
| M3 한국어 단위 | `money_kor` | 숫자+조·억·천만·백만·만·천(연쇄 허용). 뒤에 원·달러 등 → 무조건 / **억** 포함 → 무조건(단 뒤에 개수 명사·공학 단위면 통과) / 그 외(만·천·조) → ±금액 문맥일 때만 | `12억 3400만원`, `6억 규모` → `[금액]` / `1만 회`, `1200만 화소`, `3조 2교대` → 통과 |
| M4 통화 접미 | `money_suffix` | 숫자+원·달러·유로·엔·위안·파운드 (+조사). 쉼표 묶음 또는 3자리 이상, 또는 금액 문맥 | `3,000,000원`, `500,000원` / `3원색` → 통과 |
| M5 금액어 인접 | `money_kw_adj` | 단가·금액·가격·견적가·공급가·판가·원가·계약금·대금·매출·수주액 바로 뒤 숫자(자릿수 무관) — 단위·개수·치수가 뒤따르면 통과 | `단가: 850` → `단가: [금액]` |
| M6 문맥 맨숫자 | `money_bare` | 쉼표 묶음 or 4자리 이상 숫자 + 앞 20자·뒤 10자 안에 금액 문맥어. 아래 7.2 의 억제 조건이면 통과 | `견적 단가 1,250,000` → `[금액]` |

금액 문맥어(`CTX["money"]`): 수주·계약·견적·단가·매출·매입·발주·입찰·투찰·낙찰·네고·금액·가격·비용·예산·대금·원가·판가·공급가·부가세·VAT·price·cost·quote·quotation·amount·revenue·budget·invoice·인보이스·PO.

### 7.2 공학 단위·도면번호·부품번호 오탐 방지 (M5·M6 에 적용, M3 일부)

| 억제 | 판정 | 미끼 예(§18 N*) |
|---|---|---|
| 공학 단위 뒤따름 | `ENG_UNIT_AFTER`: mm·cm·um·nm·km·m·mil·inch·kg·g·N·MPa·bar·psi·V·mV·kV·A·mA·W·kW·Wh·mAh·Hz~GHz·rpm·°C·℃·K·%·ppm·dB·lux·ea·pcs·set·lot·px·dpi·fps·ms·s·min·h·TB~KB·bps·cells·nodes·elements·cycles 및 개·대·매·장·셀·노드·요소·회·번·건·명·시간·분·초·일·주·개월·년·층·차·호·점·줄·행·열·쪽·페이지·화소·세트 | `수량 300 ea`, `5,000 mAh` |
| 개수 명사 뒤따름 | `COUNT_AFTER` | `견적 요청 2건` |
| 치수 | `DIM_NEAR`: 앞뒤 `x × *` + 숫자 | `1,200 x 800 패널` |
| 식별자 앞섬 | `ID_BEFORE`: 바로 앞 8자에 PO·PR·SO·No·order·오더·번호·코드·# | `PO 4500012345 발행` |
| 공학·식별 문맥 | `ENG_CTX`: 앞 10자에 문서번호·도면·DWG·부품·품번·P/N·S/N·시리얼·LOT·관리번호·접수번호·과제번호·ECO·ECN·품목·코드·모델·Rev·Ver | `도면번호 110-123-456789` |
| 날짜·시각·버전·규격 | §5.3 보호 구간(탐지 전 가림) | `20260901`, `14:00`, `Rev 3.2.1`, `IEC 61000-4-2` |
| 코드 일부 | `NBX`/`NAX` 경계: 앞에 `영숫자 - . / \`, 뒤에 `영숫자` 또는 `구분자+영숫자`(단 `.pdf` 같은 2~5자 확장자는 허용). `_` 는 파일명 구분자로 보고 막지 않는다(`견적_010-…xlsx`, `여권사본_M…jpg` 는 잡아야 하므로) | `견적서_2026Q4_rev3.xlsx`, `DWG-2026-0012-03`, `도면 2026-0012-03.1` |

조직 고유의 부품·도면 번호 형식이 위 억제로 부족하면 `privacy.allow_patterns`(§17.3 검증)로 보호 구간을 추가한다 — 탐지 정규식 자체는 바꾸지 않는다.

### 7.3 고객 거래조건의 범위

- v1 은 **금액·단가·비율**만 가린다. 수량·납기는 업무 분류 단서라 남긴다(§21 Q3 — 고객이 수량·납기도 기밀로 보면 다음 규칙 판에서 `qty`·`due` 범주 추가).
- 코파일럿은 `[금액]` 토큰만 보고 '견적 업무'를 분류할 수 있다(분류 단서 '견적·단가'는 남고 값만 사라짐).

---

## 8. 사전 가명화 — 고객사·협력사·과제 코드네임

### 8.1 사전 출처와 기본값

| 사전 | 출처(설정 키) | 저장소 기본값 | 토큰 |
|---|---|---|---|
| 고객사 | `registry.customers[]` (팀 레지스트리) ∪ `privacy.customers[]` (개인 추가) | **빈 목록** | `[고객사:<id>]` |
| 협력사(외주·공급) | `registry.partners[]` ∪ `privacy.partners[]` | 빈 목록 | `[협력사:<id>]` |
| 과제 코드네임 | `registry.projects[].codenames` (+ `mask_name: true` 면 `name` 도) | 빈 목록 | `[과제:<registry id>]` |
| 사내 도메인 | `registry.internal_domains[]` ∪ `privacy.internal_domains[]` ∪ 런타임 본인 SMTP 도메인 | 빈 목록 | 이메일 라벨 `사내` |

항목 형식(과제 ID 는 팀/번들 명세의 레지스트리 형식 `P-\d{4}` 를 따른다):
```json
{"id": "C01", "names": ["고객사A", "CustA"], "domains": ["custa.example"]}
{"id": "P-0001", "codenames": ["과제A", "PROJ-A"], "mask_name": false}
```

### 8.2 매칭 규칙

1. 이름은 NFKC 후 비교, 대소문자 무시(`re.I`).
2. 긴 이름 먼저(겹칠 때 `고객사A2` 가 `고객사A` 보다 우선).
3. ASCII 로만 된 이름: 양쪽 영숫자 경계(`PROJ-A` 는 `XPROJ-A` 에 안 걸림).
4. 한글이 든 이름: **앞 경계만**(앞에 한글·영숫자가 없을 것), 뒤는 열어 둔다(조사 `고객사A와`, `과제A의`).
5. 이메일 도메인: 정확 일치 또는 하위 도메인(`mail.custa.example`).
6. 순서: 고객사 → 협력사 → 과제 → 본인 → 사람 사전(먼저 바뀐 것은 토큰으로 보호되어 뒤 사전이 못 건드림).

### 8.3 설정 검증 (`build_context()` 가 수행, 실패 항목은 건너뛰고 경고 코드만)

| 검사 | 실패 시 |
|---|---|
| `id` 가 `^[A-Za-z][A-Za-z0-9_\-]{0,15}$` | 항목 무시, `cfg.bad_id` |
| 이름 길이: 한글 포함 ≥2자, ASCII ≥3자 | 그 이름 무시, `cfg.short_alias` (오탐 폭주 방지) |
| 이름이 `NAME_STOP`·일반 업무어(`W_WORK` 어휘)와 같음 | 무시, `cfg.generic_alias` |
| 같은 이름이 둘 이상 id 에 | 먼저 정의된 쪽 유지, `cfg.dup_alias` |

### 8.4 토큰의 사용처

- 분류 규칙(레지스트리 매칭)은 `[과제:P-0001]`·`[고객사:C01]` 토큰을 **직접** 읽어 과제·고객을 결정할 수 있다(가장 강한 근거). 분류 명세는 이 토큰 문법을 그대로 쓴다.
- 실명 복원은 팀 서버의 권한 화면(레지스트리 표)에서만. 개인 보고서는 로컬 레지스트리 표로 표시명을 보여 줄 수 있다.
- 코파일럿에는 토큰 그대로 간다(코드네임·고객명 원문은 가지 않음).

---

## 9. 이름 가명화와 HMAC 키 관리

### 9.1 원칙 — 키 2층 (H6)

| 층 | 비밀 | 보관 | 용도 | 이동 |
|---|---|---|---|---|
| L1 개인 키링 | 32바이트 난수(kid 별) | `<ROOT>\data\keys\privacy_keyring.json`(정본) | 행에 저장하는 모든 로컬 키(who·msg·thread·chat·cal·doc·path·repo·commit·unit·host) + 정제문 속 `[사람#…]` 태그 | 프로그램 폴더째 PC 사이 이동. 세그먼트·manifest·팀 묶음·코파일럿·패키지 zip **금지** |
| L1′ 에이전트 하위 키 | L1 주 키에서 파생한 용도별 하위 키(`AGENT_PURPOSES` 만) | `%LOCALAPPDATA%\LoadMonitor27\agent\keys\subkeys.json` | 상주 수집기(pc.sampler·teams.uia·pc.events·pc.files·pc.mru·pc.recent)의 키 계산 | PC 고정 |
| L2 팀 pepper | 64 hex(팀 서버가 최초 기동 때 생성, 변경 불가) | 레지스트리 캐시 `data\team\registry.json` 의 `pepper` | `peer_key`(팀 묶음의 동료 연결)만 | 레지스트리로 배포. 행·세그먼트에 쓰지 않음 |

- 같은 사람을 PC1·PC2·클라우드PC 에서 같은 가명으로, 같은 메일을 여러 경로·PC 에서 한 번만 세려면 모든 PC 가 **같은 L1 키**를 써야 한다 → 키링은 프로그램 폴더와 함께 다닌다. 결정 메모 10.4 의 '키는 번들·팀 묶음에 넣지 않는다'는 '세그먼트·manifest(번들 내용물 목록)·팀 묶음에 키가 들어가지 않는다'로 구현한다(§21 Q14 에서 확인 요청).
- L1 은 팀 서버·코파일럿·패키지로 가지 않는다(I7). 그래서 서로 다른 팀원의 who_key 는 연결되지 않는다 — 팀 단위 동료 연결은 L2 `peer_key` 로만 한다.
- 키는 자체 난수다. Windows 자격 증명 저장소·DPAPI 는 쓰지 않는다(DPAPI 는 PC·사용자에 묶여 폴더 이동 후 풀리지 않는다 — LM24 브라우저 프로필 사고와 같은 이유). 키는 사용자 로그인·비밀번호와 무관하다.

### 9.2 키링 파일

```json
{
  "format": "lm27-keyring/1",
  "primary": "k3f9a1c2e",
  "keys": [
    {"kid": "k3f9a1c2e", "created_utc": "2026-10-05T00:12:03Z", "origin": "pc_9a1b2c3d4e5f6a7b",
     "secret_b64": "<base64 32바이트>", "state": "active"}
  ]
}
```
- `kid = "k" + sha256(secret)[:8]`, `origin` = 키를 만든 PC 의 pc_id(진단용), `state ∈ {active, retired}`.
- 비밀값 생성: `secrets.token_bytes(32)`.
- 쓰기: 임시 파일 → `os.replace` 원자 교체(팀/번들 명세 `atomic_write`). 내용·비밀값은 로그에 쓰지 않는다(감사에는 `kid` 만 허용).

### 9.3 파생 키·`keyed()`·문서 정규화

```python
# lm27/privacy/keys.py (발췌)
PURPOSES = ("person", "msg", "thread", "chat", "cal", "doc", "path", "repo", "commit", "unit", "host", "peer")
AGENT_PURPOSES = ("person", "msg", "thread", "chat", "doc", "path")


class NoKeyError(KeyError):
    """에이전트가 받지 못한 용도의 키를 요구함 → 그 행은 no_key 규칙으로 처리(§9.4)."""


@dataclass(frozen=True)
class Keyring:                       # 프로그램 폴더 실행(주 키 보유)
    primary_kid: str
    primary_secret: bytes
    all: dict                        # kid → secret (retired 포함 — 옛 행의 별칭 재계산용)

    @property
    def kid(self) -> str:
        return self.primary_kid

    def sub(self, purpose: str) -> bytes:
        return subkey(self.primary_secret, purpose)


@dataclass(frozen=True)
class AgentKeys:                     # PC 상주 에이전트(주 키 없음)
    kid: str
    subkeys: dict                    # purpose → bytes (AGENT_PURPOSES 만)

    def sub(self, purpose: str) -> bytes:
        try:
            return self.subkeys[purpose]
        except KeyError:
            raise NoKeyError(purpose) from None


def keyed(kr, purpose: str, value: str, n: int = 16) -> str:
    """HMAC-SHA256(용도 하위 키, value) 16진 앞 n자. purpose 는 PURPOSES 중 하나(아니면 ValueError)."""
    if purpose not in PURPOSES:
        raise ValueError("purpose")
    return hmac.new(kr.sub(purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()[:n]


def who_key(kr, ident: str) -> str:
    """ident: 'smtp:<소문자 주소>' 우선, 없으면 'name:<norm_person(표시명)>'. 반환 'w' + 16hex."""
    return "w" + keyed(kr, "person", ident, 16)


DOC_EXT = re.compile(r"\.[0-9a-z]{1,5}$")
DOC_TAIL = re.compile(r"(?:[\s_\-]+(?:복사본|사본|copy|최종|final|v\d{1,3}(?:\.\d{1,3}){0,2}|rev\.?\s?\d{1,3}|r\d{1,3})"
                      r"|\s?\(\d{1,3}\))+$")


def doc_norm(name: str) -> str:
    """문서 정규화 이름: 기본 이름 → NFKC·소문자 → 확장자 1개 제거 → 사본·판 꼬리 제거 → 구분자 통일.
    날짜 꼬리(주간보고_20261005)는 남긴다 — 서로 다른 주의 보고서를 한 문서로 묶지 않기 위해."""
    b = re.split(r"[\\/]", name or "")[-1]
    b = unicodedata.normalize("NFKC", b).lower().strip()
    b = DOC_EXT.sub("", b)
    b2 = DOC_TAIL.sub("", b)
    b = b2 if b2 else b
    return re.sub(r"[\s_\-.]+", "_", b).strip("_")


def doc_key(kr, name: str) -> str:
    """창 제목의 문서명·파일 기본 이름·메일 첨부명·팀즈 첨부명 모두 이 함수 하나 → 교집합으로 연결(H7)."""
    return "d" + keyed(kr, "doc", "n:" + doc_norm(name), 16)
```

`doc_norm` 예(합성): `과제A_열해석_v3.wbpj` → `과제a_열해석`, `보고서_최종.pptx`·`보고서_v3.pptx`·`보고서 - 복사본.pptx`·`보고서 (1).pptx` → 모두 `보고서`, `주간보고_20261005.xlsx` → `주간보고_20261005`, `v2.docx` → `v2`(꼬리를 다 지우면 빈 값이 되므로 원래 값 유지).

| 키 | 저장 열 | 입력(정제 **전** 원문, 메모리) | 형식 | purpose | 에이전트 |
|---|---|---|---|---|---|
| who_key | `sender_key`·`author_key`·`counterpart_keys` | `smtp:<주소 소문자>`(Exchange 사용자는 `PrimarySmtpAddress`) / 주소 없으면 `name:<norm_person(표시명)>` | `w`+16hex | person | O |
| msg_key(메일) | `msg_key` | `mid:<Internet Message-ID 소문자>` 우선, 없으면 `mail:<box>\|<UTC 분>\|<발신 주소 소문자>\|<제목 정규화 앞 80자>` | `m`+24hex | msg | O |
| msg_key(팀즈) | `msg_key` | `tid:<메시지 ID>` 우선, 없으면 `teams:<로컬 날짜>\|<대화방 원 ID>\|<작성자 정규화>\|<HH:MM>\|<sha256(본문 정규화)[:16]>` | `m`+24hex | msg | O |
| msg_key(일정) | `msg_key` | `gid:<GlobalAppointmentID>\|<시작 UTC 분>`, 없으면 `cal:<시작 UTC 분>\|<끝 UTC 분>\|<제목 정규화 앞 80자>` | `e`+24hex | cal | X |
| thread_key | `thread_key` | 메일: ConversationID 우선, 없으면 정규화 제목(RE/FW 접두 제거·공백 축약·소문자) / 팀즈: 답글 대상 원 ID | `t`+16hex | thread | O |
| chat_key | `chat_key` | 대화방 원 ID(웹 threadId, UIA 는 대화방 구조 키) | `h`+16hex | chat | O |
| doc_key | `doc_key`·`attach_keys`·`file_keys` | `doc_norm(기본 이름)` | `d`+16hex | doc | O |
| path_key | `path_key`(pc_file) | 정규화 전체 경로(소문자·`/`→`\`·사용자 폴더 → `%USERPROFILE%`) | `f`+16hex | path | O |
| repo_key | `doc_key`(pc_git) | 저장소 루트 정규화 경로 | `r`+16hex | repo | X |
| commit_key | `commit_key` | 커밋 SHA | `g`+16hex | commit | X |
| unit_id | (분석 산출) | 시작 근거 키 | `u_`+10hex(팀/번들 R-4) | unit | X |
| host_class | (팀/번들 §1.8) | 호스트명 앞 4글자 대문자 | 4hex | host | X |
| peer_key | (팀 묶음 빌드 때만) | SMTP 소문자 | `c_`+12hex | L2 pepper(없으면 L1 peer) | X |

- **정제 전 원문으로** 키를 계산한다: 규칙 판·PC 가 달라도 같은 메시지·문서가 같은 키가 되어야 병합·연결이 된다.
- 정제문 안의 `[사람#xxxxxx]` 는 who_key 의 16hex 부분 앞 6자다. 사람 사전에 있으면 사전의 키(주소 기반)를, 없으면 `name:` 기반 키를 쓴다(`sanitize()` 의 `person_token`). 같은 사람이 주소 기반·이름 기반 두 태그를 가질 수 있는데, §9.6 사람 사전이 표시명→주소 키를 알고 있으면 이름도 주소 키로 바뀐다(사전이 클수록 일관됨).
- 팀/번들 명세의 `link_key = HMAC(person.key, "doc-link")` 는 `subkey(주 키, "doc")` 로 대체한다(같은 역할, 이름 하나).

### 9.4 에이전트 하위 키 — `subkeys.json`

```json
{"format": "lm27-subkeys/1", "kid": "k3f9a1c2e", "written_utc": "2026-10-05T00:12:03Z",
 "purposes": {"person": "<base64 32B>", "msg": "<…>", "thread": "<…>", "chat": "<…>", "doc": "<…>", "path": "<…>"}}
```
- 쓰는 때: 설치 전용 진입점, 그리고 프로그램 폴더에서 [수집]을 시작할 때. `write_agent_subkeys()` 가 키링 주 키에서 `AGENT_PURPOSES` 만 파생해 원자 기록한다. 기존 파일의 kid 가 다르면 교체하고 `key.agent_rotated+1`.
- 에이전트는 키를 **만들지 않는다**. 설치 전용 진입점은 프로그램 폴더에 키링이 없으면 먼저 키링을 만들고(`load_keyring(create=True)`) 그다음 하위 키를 쓴다 → 첫 설치 PC 의 키링이 폴더와 함께 다음 PC 로 간다. 키가 PC 마다 따로 생기는 일은 '서로 다른 압축 해제본으로 설치'했을 때뿐이며 §9.8 로 복구한다.
- 에이전트의 `RecordContext.keyring` 은 `AgentKeys`, `SanitizeContext.person_subkey = subkeys["person"]`, `SanitizeContext.key` 는 0 바이트(쓰이지 않음).
- **0 바이트 키 금지**: `make_record_context()` 는 `key` 가 0 바이트이면서 `person_subkey` 도 없는 문맥을 '키 없음 모드'로 표시한다(`rc.no_key=True`). 이 모드에서 `sanitize_record()` 는 모든 텍스트 열의 `[사람#…]` 를 `[사람]` 으로 바꾼 뒤 저장한다. 0 바이트 키로 만든 태그가 디스크에 남는 경로는 말뭉치 시험(§18)뿐이다.
- `subkeys.json` 이 없거나 손상(정제 파이프 종료 코드 6, heartbeat 사유 `R-NOKEY`, 다음 [수집]이 다시 쓰면 해소):

| kind(src) | 처리 |
|---|---|
| `pc_session`(pc.sampler) | 행 저장, `doc_key=null`, `flags.no_key=true` — 시간 근거는 지킨다. 제목은 정상 정제한 뒤 `sanitize_record()` 가 `\[사람#[0-9a-f]{6}\]` 를 `[사람]` 으로 바꾼다(키 없는 상태의 `SanitizeContext.key` 는 0 바이트라 그 태그는 사전 대입에 약하다 — 저장 금지) |
| `pc_session`(pc.events) | 키 불필요 → 정상 |
| `pc_file` | 행 저장, `doc_key`·`path_key=null`, `flags.no_key=true` |
| `teams`(teams.uia) | `msg_key` 필수 → 행 폐기 `dropped.no_key`(커버리지 원장 셀은 partial — 수집 명세) |

- 보호: 하위 키는 그 용도에 한해 주 키와 같은 힘(사전 대입으로 who_key 를 되짚는 힘)을 가지므로 `data\` 와 같은 보호 대상이다. 에이전트 제거 때 함께 지운다.

### 9.5 키링 적재·병합 — `load_keyring()`

```
입력: <ROOT>\data\keys\privacy_keyring.json (+ 번들 병합 때 들어온 다른 번들의 같은 파일)
1. utf-8-sig 로 읽는다. JSON 오류·format 불일치 → 그 파일을 '<이름>.corrupt-<UTC시각>' 으로 바꾸고(자기 파일만) 없는 것으로 취급, audit key.corrupt+1
2. 없음: create=True 면 새 키 생성 → 원자 기록, audit key.created+1. create=False 면 NoKeyringError
   ([수집] 진입점은 이 예외를 받으면 스스로 create=True 로 다시 부른다 — 사용자에게 조작을 요구하지 않음)
3. 번들 병합(팀/번들 명세의 두 번들 합집합)으로 다른 키링이 들어오면 keys 를 kid 로 합집합
4. primary = created_utc 가 가장 이른 active 키(동률이면 kid 사전순). 나머지 active 는 retired 로 바꿔 다시 쓴다
5. 합집합 결과 키가 2개 이상이 된 순간 '키 충돌': audit key.conflict+1, §9.8 재매핑 예약
6. 폴더가 읽기 전용(압축 해제 전 미리보기 등): 메모리 키링으로 진행하고 쓰기(생성·병합 기록)는 다음 기회로, audit key.bundle_readonly+1
반환: Keyring(primary_kid, primary_secret, all={kid: secret})
```

정상 흐름: PC1 설치(키링 생성) → 폴더째 PC2 로 이동 → PC2 설치 전용 진입점이 폴더 키링에서 하위 키 기록 → 클라우드PC 도 같은 키. 사용자 조작 없음.

### 9.6 로컬 사람 사전 `data\local_only\person_dir.json`

```json
{"format": "lm27-persondir/1",
 "people": {
   "w3fa9c1d2e4b50617": {"names": ["김철수", "김철수 책임"], "smtp": ["user01@corp.example"], "self": false,
                          "internal": true, "first": "2026-09-01", "last": "2026-10-02"}
 }}
```
- 수집기가 메일 From/To/CC, 일정 주최자·참석자, 팀즈 작성자·참여자에서 얻은 (주소, 표시명)을 메모리에서 who_key 로 바꾸며 이 사전에 **추가만** 한다(행에는 키만 저장). 에이전트 수집분(teams.uia)은 에이전트 로컬 `agent\person_dir_delta.json` 에 쌓았다가 [수집] 때 이 파일로 합친다(같은 병합 규칙).
- 개인 보고서의 '같이 일한 동료' 표시명 복원과 팀 묶음 빌드 때 `peer_key` 계산(§9.7)에만 쓴다. 팀·코파일럿 금지. 이 파일은 I1 의 예외다.
- `build_context()` 는 이 사전의 `names` 를 `SanitizeContext.persons`(표시명 → who_key 의 16hex 부분)로, `self: true` 인 이름을 `self_names` 로 넣는다. 성만 있는 1~2자 이름(`김`, `이 책임`)은 넣지 않는다(오탐).
- PC 간 병합: `people` 키 단위 합집합, `names`·`smtp` 합집합, `first` 최소·`last` 최대, `self`·`internal` 은 OR.

### 9.7 팀 pepper 와 `peer_key` (L2 — H4·H10)

```python
# lm27/privacy/keys.py (peer_key)
def peer_key(pepper_hex, smtp, internal_domains, kr):
    """팀 묶음 빌더 전용. 행·세그먼트에 저장하지 않는다(person_dir 의 smtp 로 그때 계산)."""
    a = (smtp or "").strip().lower()
    dom = a.rsplit("@", 1)[-1] if "@" in a else ""
    if not dom or not any(dom == d or dom.endswith("." + d) for d in internal_domains):
        return None, ""                       # 외부 주소는 키 없음 — '외부(도메인 계급)' 집계로만
    if pepper_hex and re.fullmatch(r"[0-9a-f]{64}", pepper_hex):
        return "c_" + hmac.new(bytes.fromhex(pepper_hex), a.encode("utf-8"), hashlib.sha256).hexdigest()[:12], "team"
    return "c_" + keyed(kr, "peer", a, 12), "personal"
```
- `internal_domains` = 레지스트리 `internal_domains` ∪ `privacy.internal_domains`.
- 팀/번들 명세 §2.3.3 의 `HMAC-SHA256(pepper, lower(SMTP))` 에서 pepper 바이트는 `bytes.fromhex(pepper)` 로 확정한다(16진 문자열 바이트가 아님). 그 명세가 같은 커밋에서 맞춘다.
- 본인 `self_peer_key` 도 같은 식(본인 주소). 레지스트리를 아직 못 받았으면 `scope="personal"` 키 — 서버는 그 키를 동료 연결에 쓰지 않는다.
- 위험: pepper 를 아는 팀원은 추측 가능한 사내 주소를 대입해 peer_key 를 되짚을 수 있다. 팀 묶음에는 이름·주소가 없으므로 노출되는 것은 '누가 누구와 일했나'의 관계뿐이다. 공개 범위는 §21 Q10.

### 9.8 키 충돌 재매핑

키 충돌(서로 다른 압축 해제본에서 각자 키링을 만든 뒤 번들이 합쳐진 경우)이 생기면:
1. 사람 키: `person_dir` 의 `smtp`/`names` 로 주 키 기준 who_key 를 다시 계산해 별칭 표 `{옛 키 → 새 키}` 를 `data\local_only\person_alias.json` 에 쓴다. 적재기는 `kid ≠ primary` 인 행의 `sender_key`·`author_key`·`counterpart_keys` 에 별칭 표를 적용한다.
2. 원문이 필요한 키(`msg_key`·`thread_key`·`chat_key`·`doc_key`·`path_key`)는 다시 계산할 수 없다. 적재기의 중복 제거는 `kid` 가 다른 행끼리 **보조 키** `(src 계열, UTC 분, box/direction, 별칭 적용 sender/author 키, len(정제문)//10, sha1(정제문)[:12])` 로 비교한다. 보조 키로 합친 건수를 `merge.fuzzy` 로 센다. 문서 연결(doc_key 교집합)은 같은 kid 안에서만 성립한다 — 충돌 이전 구간의 '작성 완료 → 보고' 연결 손실 건수를 `merge.doclink_lost` 로 센다.
3. 이후 새 행은 주 키로만 만든다. 옛 키는 `state: retired` 로 남긴다(적재 시 kid 식별용, 새 계산에는 안 씀). 에이전트 하위 키는 다음 [수집]에서 주 키 것으로 교체된다.

---

## 10. 열 허용 목록과 `sanitize_record()`

이 절이 **저장 열의 정본**이다. 수집 공통 명세 §3 의 공통 봉투 이름을 그대로 쓰고(H2), 정제기가 만드는 열을 더한다. 표에 없는 열은 저장할 수 없다(조립 단계 assert). 텍스트가 아닌 열도 아래 '검증'을 통과한 값만 저장한다(I12) — 열거·숫자 열에 원문을 숨겨 넣는 경로를 막는다.

검증 표기: `re:<패턴>`(fullmatch) · `?`(null 허용) · `enum{…}` · `int[a,b]` · `float[a,b]` · `bool` · `list<검증, ≤n>` · `text≤n`(정제기 출력만, `_safe_truncate`) · `textlist ≤n×m` · `flags{…}`(kind 별 허용 키, 값은 bool 또는 지정 정수) · `counts`(§15.3 코드 → 정수 ≥0).

### 10.1 공통 봉투 열 (모든 kind)

| 열 | 검증 | 채우는 쪽 | 설명 |
|---|---|---|---|
| `id` | `re:^[0-9a-f]{16}$` | 정제기 | `sha1(src\|pc_id\|ts_utc\|<주 키>\|sha1(정제문 연결))[:16]`. 주 키 = msg_key·commit_key·path_key·doc_key 중 있는 첫 값(없으면 ""). 정제문 연결 = 이 행의 텍스트 열 값을 `\x1f` 로 이은 것(H14 — 원문 무키 해시 금지). 재수집해도 같은 값 |
| `kind` | `enum` KINDS | 인자 | |
| `src` | `re:^(?:(?:mail\|cal\|teams\|pc)\.[a-z]{2,10}\|manual)$` | `rc.src` | 수집 공통 명세 §2 경로 ID. 원시 필드로 덮어쓸 수 없다 |
| `pc_id` | `re:^pcx?_[0-9a-f]{16}$` | `rc.pc_id` | H5 |
| `ts_utc` | `re:^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?Z$` | 원시 | 레코드의 1차 시각 |
| `ts_local_offset` | `re:^[+-](?:0\d\|1[0-4]):[0-5]\d$` | 원시 | 관측 당시 오프셋. 분 정수가 필요한 쪽(팀/번들 명세 `off`)은 적재기가 변환 |
| `ts_precision` | `enum{exact,minute,date,summary,unknown}` | 원시 | `date`·`summary` 는 시간 근거 아님(시간 명세) |
| `ts_end` | `re?` UTC | 원시 | 구간 레코드의 끝 |
| `direction` | `enum?{in,out,unknown}`(mail) / `{sent,received,unknown}`(teams) / null(그 외) | 원시+정제기 | mail 은 `box=sent` 또는 발신자=나 → `out` |
| `act` | 상수 `""` | 정제기 | 화행은 정규화 단계가 채운다. 원시에 값이 있으면 `bad_raw` |
| `act_cues` | `list<enum{req,rep,done,ack,ask,sched,cancel,fyi}, ≤8>` | 정제기(훅) | 본문·제목에서 메모리 안에서 뽑은 화행 **단서 코드만**(본문은 저장하지 않으므로). 추출 규칙은 시간·분류 명세 소유 `lm27.normalize.cues.extract(text) -> list[str]` 를 `sanitize_record()` 가 호출하고, 출력이 이 열거 밖이면 버린다 |
| `thread_key` | `re?:^t[0-9a-f]{16}$` | 정제기 | §9.3 |
| `chat_key` | `re?:^h[0-9a-f]{16}$` | 정제기 | teams 만 |
| `counterpart_keys` | `list<re:^w[0-9a-f]{16}$, ≤20>` | 정제기 | 나를 뺀 상대들(정렬·중복 제거). 20명 초과는 자르고 `flags.cap_hit` |
| `n_participants` | `int[0,10000]` | 원시 | 나 포함 인원 |
| `doc_key` | `re?:^[dr][0-9a-f]{16}$` | 정제기 | pc_git 은 `r`(저장소) |
| `app_id` | `re?:^[a-z0-9_.:\-]{1,48}$` | 원시(카탈로그) | 카탈로그 slug 또는 `unknown:<exe 소문자>` |
| `attach_keys` | `list<re:^d[0-9a-f]{16}$, ≤10>` | 정제기 | mail 만(팀즈는 `file_keys`) |
| `flags` | `flags{kind 별 §10.2}` | 원시+정제기 | 없으면 생략(기본 false) |
| `confidence` | `float[0,1]` | 원시(수집 공통 명세 §3.4 기본값) | `*.copilot` 은 0.4 이하로 깎는다 |
| `observed_at` | `re` UTC | 원시 | 수집 시각 |
| `rules_ver` | `re:^\d{4}\.\d{1,2}\.\d{1,3}$` | 정제기 | I10 |
| `kid` | `re:^k[0-9a-f]{8}$` | 정제기 | 키 계산에 쓴 키 ID(에이전트는 하위 키의 kid) |
| `san` | `counts` | 정제기 | 이 행에서 가린 범주별 건수 |
| `priv_score` | `int?[-50,50]` | 정제기 | §12 (판정 없는 kind 는 null) |
| `priv_class` | `enum{work,unknown,media,private,social}` | 정제기 | 판정 없는 kind 는 `work` |
| `priv_why` | `list<enum{explicit,strong,weak,social,work,ack,reg_token,one_to_one,group_meeting,offhours,room_private,room_work,personal_mail,app,site,profile,inprivate,media}, ≤8>` | 정제기 | 사유 코드만 |

수집 공통 명세 §3.1 의 `subject_tokens` 는 저장하지 않는다(H3 — 적재기가 `tokens_of(subject_masked 또는 body_masked 또는 msg_masked)` 로 파생). `title_masked` 는 `pc_session` 전용 열이다.

### 10.2 kind 별 원시 입력(메모리) → 저장 열

**mail** — src `mail.com`·`mail.index`·`mail.owa`·`mail.import`·`mail.copilot`

| 원시 입력(메모리 전용) | 저장 열 | 검증·처리 |
|---|---|---|
| `internet_message_id`, `conversation_id`, `conversation_topic` (+ 대체 키 재료: `box`·시각·`sender_addr`·`subject`) | `msg_key`, `thread_key` | `re:^m[0-9a-f]{24}$` / §9.3 HMAC |
| `box` | `box` | `enum{inbox,sent,other}` |
| `folder_role` | `folder_role` | `enum{inbox,sent,junk,deleted,archive,subfolder,other}`. 폴더 경로 원문은 받지 않는다. `deleted` → 행 폐기 `dropped.folder_excluded`, `junk` → 광고 확정(§11) |
| `sender_addr`, `sender_name`, `rc.my_addrs` | `sender_key`, `sender_label` | `sender_key` = `"self"` 또는 `re:^w[0-9a-f]{16}$` 또는 null(B단 불가 경로). `sender_label` = `사내`·`개인메일`·`고객사:<ID>`·`협력사:<ID>`·`<도메인 소문자>`·`미상` (이메일 토큰 라벨과 같은 규칙, `re:^(?:사내\|개인메일\|미상\|고객사:[A-Za-z0-9_\-]{1,16}\|협력사:[A-Za-z0-9_\-]{1,16}\|[a-z0-9.\-]{3,80})$`) |
| `to[]`, `cc[]` (`{addr, name}`) | `counterpart_keys`(발신자+수신+참조−나), `n_to`, `n_cc`, `rcv` | `n_to`·`n_cc` `int[0,10000]`. `rcv` `enum{to,cc,bulk,na}`: 내 주소가 To → to, CC → cc, 둘 다 없음 → bulk, 보낸 메일 → na |
| `subject` | `subject_masked` | `text≤120` |
| `attach_names[]` | `attach_names_masked`, `attach_keys`, `attach_exts` | `textlist ≤5×80` / `doc_key()` ≤10 / `list<re:^\.[0-9a-z]{1,5}$, ≤10>` |
| `sensitivity`(0~3), `categories[]` | `flags.sensitivity`, `flags.cat_private`, `categories_masked` | 개인 범주 판정 §12.2 / `textlist ≤3×30` |
| `importance`, `has_attach`, `in_reply_to` 유무·제목 접두 | `importance`, `flags.has_file`, `is_reply`, `refw_depth` | `int[0,2]` / bool / bool / `int[0,9]` |
| `headers_text`(COM B단·EML 만) | `flags.list_unsub`, `flags.precedence`, `flags.esp` | §11.1 정규식으로 bool 만 뽑고 헤더 원문 즉시 폐기 |
| `body_text`(선택 — 앞 1,000자 + 끝 4,000자만 메모리) | `flags.body_unsub`, `act_cues`, `abs_hint` | 본문은 저장하지 않는다 |
| `focused_other`(가능한 경로만) | `focused_other` | `bool?` (§21 Q2) |
| (계산) | `ad_score`, `ad_band`, `ad_why`, `ad_partial`, `flags.ad` | `int[-20,20]` / `enum{keep,suspect}`(drop 은 저장 안 함) / `list<enum 사유 코드 §11.2, ≤10>` / bool |
| (계산) | `priv_score`, `priv_class`, `priv_why`, `flags.private`, `abs_hint` | §12 / `abs_hint` `enum{half_am,half_pm,half,leave,sick,early,out,trip,none}` |
| (계산) | `replied`, `i_sent_in_conv` | bool — 같은 thread 에 내 발신 있음 |
| `copilot_text`(`mail.copilot` 만) | `text_masked` | `text≤200`. `ts_precision ∈ {date, summary}` 강제 |

mail `flags` 허용 키: `has_file`·`list_unsub`·`precedence`·`esp`·`body_unsub`·`bulk`·`cc`·`sensitivity`(int 0~3)·`cat_private`·`ad`·`private`·`meeting_response`·`cap_hit`·`utc_suspect`.

**cal** — src `cal.com`·`cal.index`·`cal.owa`·`cal.import`·`cal.copilot`

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `global_appointment_id`, 시작·끝, `subject` | `msg_key` | `re:^e[0-9a-f]{24}$` |
| `start_utc`, `end_utc` | `ts_utc`, `ts_end` | UTC |
| `subject` | `subject_masked` | `text≤120`, 사적이면 `""` |
| `organizer{addr,name}`, `attendees[]` | `counterpart_keys`, `n_participants`, `flags.organizer_me` | |
| `busy_status` | `busy` | `enum{free,tentative,busy,oof,elsewhere}` |
| `response_status`, `meeting_status` | `flags.response`, `flags.meeting_status` | `int 0~5` / `int 0~7` |
| `location` | `location_class` | `enum{online,room,external,none}` — 장소 원문 저장 안 함 |
| `is_recurring`, `all_day`, `online`, `recurrence_incomplete` | `flags.recurring`, `flags.all_day`, `flags.online_meeting`, `flags.recurrence_incomplete` | bool |
| `sensitivity`, `categories[]` | `flags.sensitivity`, `flags.cat_private`, `categories_masked` | |
| `body_text`(선택, 앞 1,000자) | `abs_hint` | 저장 안 함 |
| (계산) | `priv_score`, `priv_class`, `priv_why`, `flags.private` | §12 |
| `copilot_text`(`cal.copilot` 만) | `text_masked` | `text≤200` |

cal `flags` 허용 키: `sensitivity`·`cat_private`·`private`·`recurring`·`all_day`·`online_meeting`·`organizer_me`·`recurrence_incomplete`·`response`·`meeting_status`·`cap_hit`·`utc_suspect`.

**teams** — src `teams.uia`·`teams.web`·`teams.copilot`

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `message_id`(있을 때) + 대체 키 재료 | `msg_key` | `re:^m[0-9a-f]{24}$` |
| `chat_id`, `chat_type`, `n_participants` | `chat_key`, `chat_type`, `n_participants` | `chat_type` `enum{1:1,group,channel,meeting,self}`(구조로 판정 — 팀즈 수집 명세) |
| `reply_to_id` | `thread_key` | |
| `author_addr`, `author_name`, `is_me` | `author_key`, `direction` | `"self"` / `w`+16hex / null(불명). 불명은 `direction=unknown`(수신 단정 금지) |
| `participants[]`(얻을 수 있을 때) | `counterpart_keys` | |
| `mentions_me` | `flags.mentions_me` | bool |
| `file_names[]` | `flags.has_file`, `file_names_masked`, `file_keys` | `textlist ≤5×80` / `list<re:^d[0-9a-f]{16}$, ≤10>` |
| `body_text` | `body_masked`, `act_cues`, `abs_hint` | `text≤300` |
| `chat_title` | `chat_title_masked` | group·channel·meeting 만 `text≤60`. **1:1 은 저장 안 함**(1:1 방 이름 = 상대 이름) |
| (계산) | `priv_score_base`, `priv_score`, `priv_class`, `priv_why`, `flags.private` | `priv_score_base` = 방 성향 제외 점수(§12.4) |
| `copilot_text`(`teams.copilot` 만) | `text_masked` | `text≤200` |

teams `flags` 허용 키: `mentions_me`·`has_file`·`private`·`cap_hit`·`utc_suspect`.

**pc_session** — src `pc.sampler`(창 샘플, 층 L2·L3) / `pc.events`(이벤트, 층 L0·L1)

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `fg_exe` | `app_id`(카탈로그가 준 값), `fg_exe` | `fg_exe` `re:^[a-z0-9_.\-]{1,64}\.exe$`(소문자) |
| `app_class` | `app_class` | `enum{office,cad,sim,eda,ide,pdf,viewer,browser,chat_work,mail_work,messenger_private,media,game,system,idle,other}` |
| `fg_title`(원문), `fg_doc_name`(선택 — 수집기가 제목에서 뽑은 문서명) | `title_masked`, `doc_key`, `site_class`, `flags.inprivate`, `priv_class` | `window_class()`(§12.6) 결과. `doc_key` = `doc_key(fg_doc_name)` — `fg_doc_name` 이 없고 `app_class ∈ TITLE_KEEP_CLASSES` 면 제목을 `" - "` 로 나눈 첫 조각. `title_masked` `text≤120`, `site_class` `enum{app,inprivate,profile,site,work_site,other}` |
| `session_state`, `idle_sec`, `layer`, `interval_sec` | `session_state`, `idle_sec`, `layer`, `ts_end` | `enum{active,locked,disconnected,remote}` / `int[0,4294968]` / `enum{L0,L1,L2,L3}` / `ts_end = ts_utc + interval` |
| `event_class`(pc.events — 수집기가 이벤트 ID 를 매핑한 값) | `event_class` | `enum{boot,shutdown,sleep,wake,logon,logoff,lock,unlock,rdp_connect,rdp_disconnect,crash}`. 이벤트 메시지 원문·사용자명·컴퓨터명은 받지 않는다(원시 필드에 있으면 `bad_raw`) |

pc_session `flags` 허용 키: `end_uncertain`·`stuck`·`always_on`·`remote`·`utc_suspect`·`no_key`·`inprivate`. 사용자명·컴퓨터 이름 열은 없다. `pc.events` 행에는 텍스트 열이 하나도 없다(무텍스트 스키마).

**pc_file** — src `pc.files`·`pc.mru`·`pc.recent`

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `path`(원문 전체 경로) | `doc_key`, `path_key`, `name_masked`, `ext`, `folder_role`, `root_id` | `doc_key(기본 이름)` / `f`+16hex / `text≤80`(기본 이름만 정제) / `re:^\.[0-9a-z]{1,5}$` / `enum{desktop,documents,downloads,onedrive,sharepoint,root,other}` / `re?:^R\d{2}$`(설정된 감시 루트 ID). 전체 경로 저장 안 함. 사적 폴더(§10.4) → 행 폐기 |
| `op`, `size` | `op`, `size_bucket` | `enum{create,modify,open,save}` / `enum{<100KB,100KB-1MB,1-4MB,4-16MB,16-64MB,>64MB}` |
| `ooxml_totaltime`, `ooxml_revision`, `ooxml_last_modified_by`(이름) | `ooxml_totaltime`, `ooxml_revision`, `flags.author_other` | `int[0,100000]` ×2 / 이름은 메모리에서 본인 표시명·주소와 비교만 하고 버린다 |
| `target_mtime`, `pdf_sibling`, 이름 패턴 | `flags.view_only`·`edit`·`pdf_export`·`final_name` | bool |

pc_file `flags` 허용 키: `view_only`·`edit`·`author_other`·`pdf_export`·`final_name`·`has_file`·`no_key`.

**pc_git** — src `pc.git`

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `repo_root`(원문 경로) | `doc_key` | `r`+16hex(§9.3 repo) |
| `commit_sha` | `commit_key` | `re:^g[0-9a-f]{16}$` |
| `subject`(커밋 제목) | `msg_masked` | `text≤120` |
| `n_commits`, `n_files`, `exts[]` | 그대로 | `int[1,10000]` / `int[0,100000]` / `list<re:^\.[0-9a-z]{1,5}$, ≤10>` |

작성자 신원(이름·메일)은 수집기가 '본인 정확 일치' 판정에만 쓰고 넘기지 않는다. pc_git `flags` 허용 키: `cap_hit`.

**pc_compute** — src `pc.compute`

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `fg_exe`/프로세스 이름, 카탈로그 라벨 | `app_id` | |
| 구간 | `ts_utc`, `ts_end` | |
| CPU 차분 평균 | `cpu_core` | `float[0,256]` |
| 라이선스 옵트인 행(본인 행만 수집기가 걸러 넘김) | `flags.license` | 사용자명·호스트명·서버 주소는 받지 않는다 |

pc_compute `flags` 허용 키: `solver`·`license`·`end_uncertain`. 텍스트 열 없음(무텍스트 스키마).

**manual** — src `manual`

| 원시 입력 | 저장 열 | 검증·처리 |
|---|---|---|
| `category` | `work_category` | `re:^[0-9A-Za-z가-힣_ \-]{1,20}$` + `check_team_label()` 통과(§14.4 — 사람 이름·번호가 들어갈 수 없게) |
| `hours`, `date`·`start`·`end` | `hours`, `ts_utc`, `ts_end`, `ts_precision` | `float[0,24]`. 시각 없으면 그날 00:00+offset·`date` |
| `note`, `entity` | `text_masked` | `text≤200` = `sanitize(note + " / " + entity)` |
| `project_id`, `role_field`, `role_func` | 그대로 | 레지스트리 ID(`re:^[A-Za-z][A-Za-z0-9_\-]{0,15}$`) / 레지스트리 어휘 `re:^[0-9A-Za-z가-힣_]{1,20}$` |

manual 은 `flags` 없음.

### 10.3 `sanitize_record()` 의사코드

```python
def sanitize_record(kind: str, raw: dict, rc: RecordContext) -> RecordOutcome:
    spec = SCHEMAS.get(kind)
    if spec is None:
        raise ValueError("unknown kind")                 # 프로그래밍 오류 → 수집기 중단(fail-closed)
    try:
        base = spec.validate_raw(raw, rc)                # 필수 원시 필드·타입·금지 원시 필드(§10.2). 실패 → dropped("bad_raw")
        if base is None:
            return RecordOutcome("dropped", None, "bad_raw", {})
        if kind == "pc_file" and path_excluded(base["path"], rc):   # §10.4
            return RecordOutcome("dropped", None, "private_folder", {})
        if kind == "mail" and base.get("folder_role") == "deleted":
            return RecordOutcome("dropped", None, "folder_excluded", {})
        try:
            keys = spec.derive_keys(base, rc.keyring)    # §9.3 — 정제 전 원문으로
        except NoKeyError:
            if spec.keys_required:                       # teams·mail·cal: msg_key 없이 저장 불가
                return RecordOutcome("dropped", None, "no_key", {})
            keys = spec.null_keys(); base["_no_key"] = True    # pc_session·pc_file: 키 열 null + flags.no_key
        feats = spec.derive_features(base, rc)           # 광고 헤더·본문 플래그, act_cues 훅, abs_hint, rcv, corresp
        hits, texts = {}, {}
        for col, (src, max_len, cap) in spec.text_fields.items():  # 예: {"subject_masked": ("subject", 120, None)}
            vals = base.get(src)
            if cap is not None:                          # textlist
                out = []
                for v in (vals or [])[:cap]:
                    r = sanitize(v, col, rc.sctx, max_len)
                    if r.drop:
                        return RecordOutcome("dropped", None, "cred", {"cred": 1})
                    _merge(hits, r.hits); out.append(r.text)
                texts[col] = out
            else:
                r = sanitize(vals or "", col, rc.sctx, max_len)
                if r.drop:
                    return RecordOutcome("dropped", None, "cred", {"cred": 1})
                _merge(hits, r.hits); texts[col] = r.text
        if kind == "mail" and base["box"] != "sent":
            score, band, why = ad_score(feats["ad"])            # §11
            if band == "drop":
                return RecordOutcome("dropped", None, "ad", hits)
            feats["ad_out"] = (score, band, why)
        pv = spec.privacy_verdict(base, texts, feats, rc)       # §12 → (priv_score, priv_class, why)
        if pv.priv_class in ("private", "social"):
            for col in spec.text_fields:                         # 내용 삭제(메타만 남김) — §12.7
                texts[col] = [] if isinstance(texts[col], list) else ""
            feats["act_cues"] = []
        if rc.no_key or base.get("_no_key"):                     # 0 바이트 키 태그 저장 금지(§9.4)
            texts = {c: _plain_person(v) for c, v in texts.items()}
        row = spec.assemble(base, keys, feats, texts, pv)        # spec.columns 에 있는 열만
        row.update(rules_ver=RULES_VERSION, kid=rc.keyring.kid, san=hits, src=rc.src, pc_id=rc.pc_id, act="")
        row["id"] = record_id(row, spec)                         # §10.1 — 정제문 해시
        bad = spec.validate_columns(row)                         # 모든 열 검증(I12). 허용 밖 열·형식 위반 → 열 이름 목록
        if bad:
            rc.audit.add("err", "column:" + bad[0])              # 열 이름만(값 금지)
            return RecordOutcome("error", None, "ColumnViolation", {})
        return RecordOutcome("stored", SanitizedRow(kind, row, _SEAL), None, hits)
    except Exception as e:                                       # noqa: BLE001 — 한 행 오류로 수집 전체 중단 금지
        rc.audit.add("err", type(e).__name__)                    # 원문·메시지 금지(I8)
        return RecordOutcome("error", None, type(e).__name__, {})


def _plain_person(v):
    if isinstance(v, list):
        return [_plain_person(x) for x in v]
    return re.sub(r"\[사람#[0-9a-f]{6}\]", "[사람]", v or "")
```

- `error`·`dropped` 행은 저장하지 않는다. 수집기는 `rows_in = stored + dropped + error` 를 확인하고 감사에 넘긴다.
- 커버리지 원장(일자×출처)에는 dropped 도 '관측 건수'로 센다(내용 없음) — 광고를 버려도 '그날 메일 수집 성공'은 사실이므로.
- `spec.validate_raw()` 의 '금지 원시 필드': `pc.events` 의 `message`·`user`·`computer`, `pc_compute` 의 `user`·`host`·`server`, 모든 kind 의 `username`·`computername`·`machine_guid`. 들어오면 그 행은 `bad_raw`(수집기 결함 신호).

### 10.4 사적 폴더 제외(파일 수집 경로 전용)

LM24 의 `excludePathKeywords` 의미론을 **경로 제외 전용**으로만 유지한다(텍스트 PII 탐지기로 쓰지 않음):
- 경로 전용 토큰(`temp`·`downloads`·`임시`·`다운로드`): 폴더명 **완전 일치**.
- ASCII 키워드: 단어 경계(`(?<![A-Za-z0-9])kw(?![A-Za-z0-9])`, 대소문자 무시).
- 한글 키워드: 부분 일치.
- 설정 키 `privacy.path.exclude_keywords`(기본: `개인`, `가족`, `사진`, `private`, `personal`) — 목록 의미론 §17.1.
- 경로 원문은 버리고 `dropped.private_folder` 건수만. git 저장소 루트에도 같은 규칙(걸리면 그 저장소 커밋 전부 건수만).

### 10.5 `resanitize_row()` — 적재 시 재정제(G2)

```python
def resanitize_row(kind, row, ctx):
    if version_tuple(row.get("rules_ver", "0.0.0")) >= version_tuple(RULES_VERSION):
        return row, {}
    row, hits = dict(row), {}                      # 원본 dict 를 바꾸지 않는다
    for col in SCHEMAS[kind].text_fields:
        v = row.get(col)
        vals = v if isinstance(v, list) else [v]
        out = []
        for x in vals:
            if not x:
                out.append(x)
                continue
            r = sanitize(x, col, ctx)
            out.append("" if r.drop else r.text)   # 자격증명이 뒤늦게 발견되면 그 값만 비움(행은 유지, 시간 근거 보존)
            _merge(hits, {"cred": 1} if r.drop else r.hits)
        row[col] = out if isinstance(v, list) else out[0]
    row["rules_ver"] = RULES_VERSION               # 메모리 사본만 갱신. 디스크 반영은 redact_rewrite(자기 pc_id)만
    return row, hits
```
- 단조성(I5): 정제문은 이미 토큰을 갖고 있고 토큰은 보호되므로 새 규칙은 **추가로** 가릴 수만 있다.
- 다른 pc_id 세그먼트는 디스크를 건드리지 않는다(읽기 시 적용). 자기 pc_id 세그먼트는 유지보수 단계에서 `redact_rewrite()` 로 반영할 수 있다(§12.5 와 같은 규칙).
- 재정제로 텍스트가 바뀌어도 `id` 는 다시 계산하지 않는다(행 정체성은 최초 저장 때 고정 — 중복 제거는 msg_key 등 키 열로).

### 10.6 kind 대조표 (LM26 초판·형제 명세 표기 → LM27)

| LM26 초판 정제 kind | PC 명세 제안 | LM27 저장 kind (src) |
|---|---|---|
| `mail` | - | `mail` (mail.*) |
| `cal` | - | `cal` (cal.*) |
| `teams` | - | `teams` (teams.*) |
| `window` | `window` | `pc_session` (pc.sampler) |
| - | `session` | `pc_session` (pc.events) |
| `file` | `file` | `pc_file` (pc.files·pc.mru·pc.recent) |
| `git` | `git` | `pc_git` (pc.git) |
| - | `compute` | `pc_compute` (pc.compute) |
| `worklog` | `worklog` | `manual` (manual) |
| `copilot_ev` | - | `mail`·`teams`·`cal` (`*.copilot`, `ts_precision ∈ {date,summary}`, `text_masked`) |

| LM26 초판 열 | LM27 열 |
|---|---|
| `conv_key` | `thread_key` |
| `peer_keys` | `counterpart_keys` |
| `folder_class` | `folder_role` |
| `cat_private`·`ad_hdr{list_unsub,precedence_bulk,esp}`·`ad_body_unsub` | `flags.cat_private`·`flags.list_unsub`·`flags.precedence`·`flags.esp`·`flags.body_unsub` |
| `sensitivity` | `flags.sensitivity` |
| `n_attendees`(cal) | `n_participants` |
| `organizer_is_me`·`recurring`·`all_day` | `flags.organizer_me`·`flags.recurring`·`flags.all_day` |
| `response`(cal 문자열) | `flags.response`(정수 0~5, 수집 공통 명세) |
| `cal_key` | `msg_key`(`e`+24hex) |
| `person_key`(`p`+16hex) | `who_key`(`w`+16hex) |
| `act`, `act_score`(수집 시 판정) | `act=""` + `act_cues`(단서 코드) |
| `source`(com·index·…) | `src`(경로 ID) |
| `text_masked`(worklog)·`text_masked`(copilot_ev) | `text_masked`(manual·`*.copilot`) |

---

## 11. 광고성 메일 점수

### 11.1 특징 추출 — 경로별 가능 여부

| 특징 | 클래식 Outlook COM | Windows Search 색인 | OWA·새 Outlook(CDP DOM) | EML 반입 | 코파일럿 요약 |
|---|---|---|---|---|---|
| 제목 | `Subject` | `System.Subject` | 목록 DOM | `Subject:` | 요약문 |
| 발신 SMTP | `PropertyAccessor` `http://schemas.microsoft.com/mapi/proptag/0x5D01001F`(PR_SENDER_SMTP_ADDRESS), Exchange 발신자는 `Sender.GetExchangeUser().PrimarySmtpAddress` (메일 명세의 B단 — 탐침이 보호 열 통과를 확인한 PC 에서만) | `System.Message.FromAddress` | 발신자 요소의 주소 속성(있을 때) | `From:` | 불가 |
| List-Unsubscribe·Precedence·ESP 헤더 | `0x007D001F`(PR_TRANSPORT_MESSAGE_HEADERS, B단) | 불가 | 불가 | 헤더 | 불가 |
| 본문 수신거부 문구 | `Body` 앞 1,000자 + 끝 4,000자(B단) | 불가 | 미리보기 문구(있을 때) | 본문 | 불가 |
| To/CC 에 내 주소 | `Recipients`(B단) | `System.Message.ToAddress`·`CcAddress` | 부분 | `To:`·`Cc:` | 불가 |
| 정크 폴더 | 폴더 역할 | 경로 조각 | 폴더 | 불가 | 불가 |

헤더를 못 읽는 경로(새 Outlook·OWA·색인·B단 불가 PC)는 `ad_partial=true` 로 표시하고 같은 임계로 판정한다(제목 표기·도메인·광고어만으로). 보고서의 '광고 판정 정밀도' 표에 경로별 `ad_partial` 비율을 낸다.

헤더 플래그(메모리에서 bool 만 추출, 헤더 원문 즉시 폐기):
```python
HDR_LIST_UNSUB = re.compile(r"(?im)^List-Unsubscribe\s*:")
HDR_PRECEDENCE = re.compile(r"(?im)^Precedence\s*:\s*(?:bulk|list|junk)\b")
HDR_ESP = re.compile(r"(?im)^(?:Feedback-ID|X-Campaign(?:ID|-Id)?|X-Mailgun-[A-Za-z-]+|X-SES-[A-Za-z-]+|X-SG-EID|X-SG-ID"
                     r"|X-MC-User|X-Mailchimp-[A-Za-z-]+|X-CSA-Complaints|X-Mailer-RecptId|X-Stibee-[A-Za-z-]+"
                     r"|X-Sendinblue-[A-Za-z-]+|X-Marketo-[A-Za-z-]+|X-HubSpot-[A-Za-z-]+|X-SFMC-Stack)\s*:"
                     r"|^X-Mailer\s*:.*(?:Mailchimp|SendGrid|Amazon SES|Mailgun|Sendinblue|Brevo|Stibee|HubSpot|Marketo"
                     r"|Salesforce|Constant Contact|MailerLite|Campaign Monitor)")
```

### 11.2 점수 규칙 — `classify.py`

```python
# lm27/privacy/classify.py (광고)
AD_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|회신|전달|답장)\s*[:：]\s*)*[\(\[<【〈{]\s*(?:광고|ad|광고성\s?정보|홍보|advertisement)"
                       r"\s*[\)\]>】〉}]", re.I)
AD_WORDS = re.compile(
    r"(?i)(수신\s?거부|구독\s?(?:취소|해지)|unsubscribe|opt[- ]?out|뉴스레터|newsletter|웨비나|webinar|프로모션|promotion|"
    r"할인|특가|쿠폰|coupon|이벤트|event|무료\s?체험|free\s?trial|신제품\s?출시|런칭|초대합니다|세미나\s?안내|전시회\s?초대|"
    r"limited\s?offer|sale|경품|사은품|당첨|혜택|얼리버드|early\s?bird)")
AD_LOCALPART = re.compile(r"(?i)^(?:newsletter|news|marketing|promo|promotion|event|events|webinar|campaign|mailer|edm|ad|ads"
                          r"|offers?)[._\-]?|(?:^|[._\-])(?:newsletter|marketing|promo|campaign|edm)(?:$|[._\-])")
BODY_UNSUB = re.compile(r"(?i)(수신\s?거부|수신을\s?원하지\s?않으시면|구독\s?(?:취소|해지)|unsubscribe|opt[- ]?out|이메일\s?수신\s?동의)")
AD_DROP, AD_SUSPECT = 5, 3


def ad_score(m: dict) -> tuple[int, str, list]:
    """m: 메모리 특징 dict — subject, internal, corresp_domain, partner, hdr{list_unsubscribe, precedence_bulk, esp},
    body_unsub, focused_other, folder, rcv, n_recipients, adlike_localpart, i_sent_in_conv, blocked, allowed."""
    why = []
    if m.get("blocked"):
        return 9, "drop", ["user_block"]
    if m.get("folder") == "junk":
        return 9, "drop", ["folder_junk"]
    if AD_PREFIX.search(m.get("subject", "")):
        return 9, "drop", ["ad_prefix"]            # 정보통신망법 제50조 광고 표기 — 단독 확정, 회신·허용 면제 무효
    s = 0
    h = m.get("hdr") or {}
    if h.get("list_unsubscribe"):
        s += 4; why.append("list_unsub")
    if h.get("precedence_bulk"):
        s += 3; why.append("precedence")
    if h.get("esp"):
        s += 2; why.append("esp")
    if m.get("body_unsub"):
        s += 2; why.append("body_unsub")
    if m.get("focused_other"):
        s += 3; why.append("focused_other")
    rel = m.get("internal") or m.get("corresp_domain") or m.get("partner")
    if not m.get("internal"):
        s += 1; why.append("external")
        if not m.get("corresp_domain"):
            s += 2; why.append("no_corresp")
    if m.get("rcv") == "bulk":
        s += 1; why.append("bulk")
    if (m.get("n_recipients") or 0) >= 20:
        s += 1; why.append("many_rcpt")
    words = {w.lower() for w in AD_WORDS.findall(m.get("subject", ""))}
    if words:
        s += 2 + (1 if len(words) >= 2 else 0); why.append("ad_words")
    if m.get("adlike_localpart"):
        s += 1; why.append("ad_localpart")
    if rel:
        s -= 3; why.append("work_relation")        # 사내·왕래·협력사: 감점만(면제 아님 — LM24 영구 면제 결함 수정)
    if m.get("i_sent_in_conv"):
        s -= 4; why.append("my_thread")
    if m.get("allowed"):
        s = min(s, 0); why.append("user_allow")
    band = "drop" if s >= AD_DROP else ("suspect" if s >= AD_SUSPECT else "keep")
    return s, band, why
```

`ad_score()` 입력 특징 dict 는 `sanitize_record()` 가 메모리에서 만든다: `subject`(**정제 전** 제목 — 광고 표기·광고어 판정용, 저장 안 함), `internal`(발신 도메인 ∈ 사내), `corresp_domain`(§11.3), `partner`(협력사 사전 도메인), `hdr`(§11.1 플래그), `body_unsub`, `focused_other`, `folder`(= folder_role), `rcv`, `n_recipients`(= n_to + n_cc), `adlike_localpart`(발신 주소 로컬파트에 `AD_LOCALPART` — 로컬파트 자체는 저장 안 함), `i_sent_in_conv`, `blocked`·`allowed`(§11.5). `privacy.ad.extra_words` 는 정규식을 바꾸지 않고 호출 쪽에서 처리한다: 제목에 설정 광고어가 있으면 `ad_score()` 점수에 +2(정규식 광고어가 이미 있었으면 +1 — 광고어 가점 합계 +3 상한)를 더한 뒤 같은 임계로 band 를 다시 정한다(확정 9 규칙·허용 상한 0 은 그대로 우선).

가중치 요약표:

| 특징 | 점수 | 비고 |
|---|---|---|
| 사용자 차단 목록(도메인·발신자 키) | 확정 9 | §11.5 |
| 정크 폴더 | 확정 9 | |
| 제목 `(광고)`·`[광고]`·`<광고>`·`【광고】`·`(AD)`·`(광고성 정보)`·`(홍보)` (RE/FW 뒤 포함) | 확정 9 | 허용 목록도 무효 |
| List-Unsubscribe | +4 | 대량 발송 단서 |
| Precedence: bulk/list/junk | +3 | 대량 발송 단서 |
| 대량 발송 서비스 헤더(ESP) | +2 | 대량 발송 단서 |
| 본문 수신거부 문구 | +2 | |
| Focused '기타' | +3 | 확정 아님(사내 알림도 섞임) |
| 외부 도메인 | +1 | |
| 외부 + 왕래 없음 | +2 추가 | §11.3 |
| 나는 숨은 참조·대량(rcv=bulk) | +1 | 대량 발송 단서 |
| 수신자 20명 이상 | +1 | 대량 발송 단서 |
| 제목 광고어 1종 / 2종 이상 | +2 / +3 | `AD_WORDS`(뉴스레터·웨비나·프로모션·수신거부·unsubscribe 등) |
| 발신 로컬파트 광고형 | +1 | `newsletter@`, `marketing.` 등 |
| 사내·왕래·협력사 | −3 | 1회만 |
| 같은 대화에 내 발신 있음 | −4 | |
| 사용자 허용 목록 | 상한 0 | 확정 9 규칙은 못 이김 |

임계: **5 이상 drop**(저장 안 함, 건수만) / **3~4 suspect**(저장, `flags.ad=true`, 코파일럿 제외, 로컬 '광고 의심' 큐) / **2 이하 keep**.

### 11.3 왕래 도메인

- 정의: 최근 365일 안에 내가 보낸 메일의 To/CC 에 나온 도메인(사내 제외).
- 저장: `data\local_only\corresp_domains.json` = `{"domain": "YYYY-MM-DD(마지막 발신일)"}`. PC 간 병합은 도메인별 최댓값. 에이전트는 메일을 수집하지 않으므로 사본이 필요 없다.
- 갱신 순서: 메일 수집은 **보낸 편지함을 먼저** 처리해 왕래 집합을 만든 뒤 받은 편지함을 점수화한다(첫 실행의 냉시작 오탐 방지).

### 11.4 사내 공지와의 경계

사내 대량 메일(사내 뉴스레터·공지)은 광고가 아니다(−3 감점으로 보통 keep). 이런 메일의 업무 가중치(수신 전용 감쇠·bulk 미계상)는 수집·시간 명세의 몫이다. 광고 점수는 **외부 상업 메일 제거**만 맡는다.

### 11.5 사용자 차단·허용 목록

- 로컬 감사 화면(§15.5)의 '광고 의심' 큐에서 사용자가 [차단]·[허용]을 누르면 `data\local_only\ad_lists.json` 에 `{"block_domains": [], "block_senders": [who_key], "allow_domains": [], "allow_senders": []}` 로 추가된다.
- 설정 고정분 `privacy.ad.block_domains`·`privacy.ad.allow_domains`·`privacy.ad.block_subject_regex` 와 합집합.
- `block_subject_regex` 는 제목에 맞으면 `blocked=True`(정규식은 §17.3 검증 통과분만).
- 사용자를 위한 선택 기능일 뿐, 다른 사용자에게 조작을 요구하지 않는다(기본 동작만으로 완결).

---

## 12. 공사(公私) 구분

### 12.1 판정 단위와 결과

| 대상 | 판정 함수 | 결과 클래스 |
|---|---|---|
| mail(제목) | `private_score(subject_masked, sensitivity, private_category, personal_mail, offhours)` | work·private·social |
| cal | 같은 함수(제목) + 민감도·범주 | work·private·social |
| teams 메시지 | `private_score(body_masked, chat_type, offhours, room_prior, user_private_chat)` | work·private·social |
| pc_session(pc.sampler) | `window_class()` | work·unknown·media·private |
| pc_session(pc.events)·pc_file·pc_git·pc_compute·manual | 판정 없음(`work`) — 사적 폴더는 §10.4 에서 제외 | work |

판정 입력 텍스트는 **정제문**이다(정제 후에 판정 → 토큰 `[과제:…]` 이 업무 근거로 쓰임). `offhours` = 그 행 시각이 `rc.work_window` 의 표준창 밖(평일 표준창 밖·주말·공휴일).

### 12.2 명시적 사적 표시 (즉시 private, 점수 9)

- Outlook 민감도 `1`(개인·olPersonal), `2`(비공개·olPrivate). `3`(기밀)은 사적이 아님 — 업무 기밀로 보고 일반 정제만.
- 범주(Categories)가 `privacy.private.categories`(기본 `개인`, `Personal`, `Private`, `가족`) 중 하나.
- 사용자가 사적으로 지정한 대화방(`private_chats.json`).

### 12.3 사적 점수 — `private_score()`

```python
# lm27/privacy/classify.py (공사 구분)
P_STRONG = re.compile(
    r"(가족|와이프|아내|남편|신랑|애기|아기|아이들|딸아이|아들|부모님|엄마|아빠|장모|시댁|처가|병원|치과|한의원|약국|진료|택배|배송|쇼핑|주문했|직구|"
    r"여행|휴가\s?계획|비행기\s?표|숙소|캠핑|게임|축구|야구|농구|영화|드라마|넷플|유튜브|주식|코인|대출|이사\s?(?:가|날|준비)|집들이|부동산|청약|전세|월세|"
    r"결혼식|소개팅|데이트|생일\s?선물|헬스장|골프)")
P_WEAK = re.compile(r"(점심|저녁|야식|커피|한잔|술|맥주|치킨|맛집|퇴근하고|퇴근\s?후에|주말에|휴일에|날씨|ㅋㅋ+|ㅎㅎ+|ㅠㅠ+|ㅜㅜ+|ㄱㄱ|헐|대박"
                    r"|😂|🤣|😆|🍺|🍻)")
P_SOCIAL = re.compile(r"(회식|경조사|축의|부의|조의|조문|돌잔치|동호회|송년회|신년회|뒤풀이|생일\s?축하|체육대회)")
W_WORK = re.compile(
    r"(?i)(검토|회신|보고|자료|첨부|일정|회의|미팅|도면|설계|시험|평가|해석|시뮬|샘플|발주|구매|견적|고객|과제|프로젝트|양산|개발|이슈|불량|대책|품질|"
    r"(?<![A-Za-z])(?:BOM|ECO|DR|PR|PO|spec)(?![A-Za-z])|사양|요청|부탁드립니다|공유드립니다|확인\s?부탁|승인|결재|기안|출장|교육|특허|예산|정산)")
W_ACK = re.compile(r"(넵|네\s?알겠습니다|알겠습니다|확인했습니다|감사합니다|수고하셨습니다)")
REG_TOKEN = re.compile(r"\[(?:과제|고객사|협력사):[^\]]+\]")
PRIV_THRESHOLD = 2


def private_score(text: str, *, chat_type: str = "", offhours: bool = False, room_prior: str = "",
                  personal_mail: bool = False, sensitivity: int = 0, private_category: bool = False,
                  user_private_chat: bool = False):
    if sensitivity in (1, 2) or private_category or user_private_chat:
        return 9, "private", {"explicit": 1}
    ps, pw, so = P_STRONG.findall(text), P_WEAK.findall(text), P_SOCIAL.findall(text)
    ww, ack = W_WORK.findall(text), W_ACK.findall(text)
    s = 2 * len(ps) + len(pw) + len(so) - 2 * min(len(ww), 4) - len(ack)
    if REG_TOKEN.search(text):
        s -= 3                                      # 레지스트리 토큰(과제·고객·협력사) = 강한 업무 근거
    if chat_type == "1:1":
        s += 1
    elif chat_type in ("meeting", "channel"):
        s -= 1
    if offhours:
        s += 1                                      # 평일 19~07시, 주말·공휴일 (시간 명세의 표준창 밖)
    if room_prior == "private":
        s += 2
    elif room_prior == "work":
        s -= 1
    if personal_mail:
        s += 3                                      # 상대가 공용 개인 메일 도메인
    if s >= PRIV_THRESHOLD:
        cls = "social" if so and not ps else "private"
    else:
        cls = "work"
    return s, cls, {"strong": len(ps), "weak": len(pw), "social": len(so), "work": len(ww), "ack": len(ack)}
```

| 항목 | 점수 |
|---|---|
| 강한 사적 어휘 1개마다 | +2 |
| 약한 사적 어휘 1개마다(식사·잡담·이모티콘) | +1 |
| 사내 친목 어휘(회식·경조사·동호회) 1개마다 | +1 (결과 클래스 social) |
| 업무 어휘 1개마다(최대 4개) | −2 |
| 업무 응답어(넵·알겠습니다·감사합니다) | −1 |
| 과제·고객·협력사 토큰 존재 | −3 |
| 1:1 대화 / 회의·채널 | +1 / −1 |
| 표준창 밖 시각 | +1 |
| 방 성향 사적 / 업무 | +2 / −1 |
| 개인 메일 상대 | +3 |
| **판정** | ≥2 → private(친목어만 있고 강한 사적어 없으면 social), 그 외 work |

- `privacy.private.extra_words`·`.extra_work_words` 는 위 정규식을 바꾸지 않는다. `spec.privacy_verdict()` 가 `private_score()` 결과 점수에 설정 어휘를 문자 그대로 센 건수를 더하고(사적어 1개마다 +2, 업무어 1개마다 −2 — 정규식 업무어와 합쳐 4개 상한), 같은 임계(`PRIV_THRESHOLD`)·같은 social 규칙으로 클래스를 다시 정한다(규칙 해시 불변 — 설정 해시 §16.3 에 반영).
- `social`(사내 친목)은 사적과 똑같이 내용을 지우고 시간 근거에서 뺀다. 보고서에서만 '사내 친목 n건'으로 따로 센다(경계 사례 정책 §21 Q4).
- 세부 dict 는 `priv_why` 코드(strong·weak·social·work·ack·reg_token·one_to_one·group_meeting·offhours·room_private·room_work·personal_mail·explicit)로 바꿔 저장한다(값이 0 인 코드는 넣지 않음).

### 12.4 1:1 대화방 성격(방 성향)

```python
@dataclass
class RoomStat:            # 적재기가 정제된 teams 행에서 계산(별도 파일 없음)
    n: int                 # 최근 30일 메시지 수(msg_key 중복 제거 후)
    n_private: int         # priv_score_base >= 2
    n_work: int            # priv_score_base <= -2

def room_prior(st: RoomStat) -> str:
    if st.n >= 10 and st.n_private / st.n >= 0.7:
        return "private"
    if st.n >= 10 and st.n_work / st.n >= 0.7:
        return "work"
    return ""
```
- 수집 시점: 그 PC 의 로컬 저장분 + 현재 배치로 계산한 `RoomStat` 을 쓴다(에이전트 teams.uia 는 에이전트 로컬 원장분).
- 적재 시점(클라우드PC 병합 후): 전체 중복 제거본으로 다시 계산한다. 방 성향이 `private` 가 되면 그 방의 행 중 `priv_score_base > −4`(강한 업무 2개 이상이 아닌 것) 를 `priv_class="private"` 로 바꾸고 `body_masked`·`file_names_masked` 를 숨긴다(§12.5 소급 가림).
- 사용자 지정(`private_chats.json`)은 방 전체를 즉시 private 로 한다. 병합은 합집합.

### 12.5 소급 가림 (불변 세그먼트 원칙의 유일한 예외)

- `data\local_only\redact_overlay.json` = `{"chat": {"<chat_key>": "<since UTC>"}, "msg": ["<msg_key>", ...]}`. 병합은 합집합(같은 chat 은 since 최솟값).
- **읽기 오버레이**: 적재기는 모든 pc_id 세그먼트에 오버레이를 적용해 해당 행의 텍스트 열을 비운 사본만 위로 넘긴다(코파일럿·보고서에 절대 안 감).
- **재작성**: 각 PC 는 자기 pc_id 세그먼트에 한해 `redact_rewrite()` 로 디스크에서도 지운다. 규칙: 행 수·키·시간 열 불변, 텍스트 열만 `""`/`[]` 로, 새 세그먼트를 쓰고 manifest 를 원자 교체(팀/번들 명세의 세그먼트 교체 절차 — sha256 집합이 바뀌므로 manifest 에 `supersedes` 기록), 감사 `rewrite_redact` 에 바꾼 행 수. 다른 pc_id 세그먼트는 그 PC 에 폴더가 돌아갔을 때 그 PC 가 지운다(이동·rename 금지 원칙 유지).

### 12.6 창 샘플(비업무 앱·사이트) — `window_class()`

```python
BROWSER_EXES = frozenset({"msedge.exe", "chrome.exe", "firefox.exe", "whale.exe", "opera.exe", "brave.exe", "iexplore.exe"})
PRIVATE_EXES = frozenset({"kakaotalk.exe", "telegram.exe", "discord.exe", "whatsapp.exe", "line.exe", "steam.exe",
                          "steamwebhelper.exe", "epicgameslauncher.exe", "battle.net.exe", "leagueclient.exe",
                          "riotclientservices.exe"})
MEDIA_EXES = frozenset({"spotify.exe"})
INPRIVATE_RX = re.compile(r"(?i)InPrivate|Incognito|시크릿|비공개\s?창|Private\s?Browsing")
BROWSER_SUFFIX_RX = re.compile(r"\s[-–—]\s(?:(?P<profile>[^-–—]{1,40}?)\s[-–—]\s)?"
                               r"(?:Microsoft\s*Edge|Google\s*Chrome|Mozilla\s*Firefox|Whale|Opera|Brave)\s*$", re.I)
PRIVATE_SITE_RX = re.compile(
    r"(?i)(쿠팡|11번가|G마켓|옥션|SSG\.COM|무신사|오늘의집|배달의민족|요기요|당근|번개장터|중고나라|넷플릭스|Netflix|티빙|TVING|웨이브|wavve"
    r"|왓챠|디즈니\+|Disney\+|쿠팡플레이|인터넷뱅킹|스마트뱅킹|증권|주식|코인|업비트|빗썸|웹툰|나무위키|디시인사이드|DC인사이드|인스타그램"
    r"|Instagram|Facebook|페이스북|트위터|Twitch|치지직|아프리카TV|SOOP|네이버\s?카페|다음\s?카페|부동산)")
MEDIA_SITE_RX = re.compile(r"(?i)(YouTube|유튜브|멜론|Melon|Spotify|SoundCloud)")
WORK_SITE_RX = re.compile(
    r"(?i)(SharePoint|OneDrive|Outlook|Teams|Microsoft 365|Office 365|Copilot|Power BI|Confluence|Jira|GitHub|GitLab|Bitbucket"
    r"|Jenkins|Redmine|Azure DevOps|Stack Overflow|Microsoft Learn|Datasheet|데이터시트|IEEE Xplore|ScienceDirect"
    r"|Google Scholar|DBpia|RISS|KIPRIS|Espacenet|Digi-?Key|Mouser|Octopart|PLM|ERP|MES|SAP|Windchill|Teamcenter|Polarion|DOORS)")
TITLE_KEEP_CLASSES = frozenset({"office", "cad", "sim", "eda", "ide", "pdf", "viewer"})


@dataclass(frozen=True)
class WindowVerdict:
    priv_class: str        # work | unknown | media | private
    title_masked: str
    inprivate: bool
    site_class: str        # app | inprivate | profile | site | work_site | other


def window_class(fg_exe: str, title: str, app_class: str, wctx) -> WindowVerdict:
    exe = (fg_exe or "").lower()
    t = unicodedata.normalize("NFKC", title or "")
    if exe in PRIVATE_EXES or exe in wctx.private_exes:
        return WindowVerdict("private", "", False, "app")
    if exe in MEDIA_EXES:
        return WindowVerdict("media", "", False, "app")
    if exe in BROWSER_EXES or app_class == "browser":
        if INPRIVATE_RX.search(t):
            return WindowVerdict("private", "", True, "inprivate")
        m = BROWSER_SUFFIX_RX.search(t)
        page = t[:m.start()] if m else t
        profile = (m.group("profile") or "").strip() if m else ""
        if profile and profile in wctx.private_profiles:
            return WindowVerdict("private", "", False, "profile")
        if PRIVATE_SITE_RX.search(page):
            return WindowVerdict("private", "", False, "site")
        if MEDIA_SITE_RX.search(page):
            return WindowVerdict("media", "", False, "site")
        if WORK_SITE_RX.search(page) or any(p.search(page) for p in wctx.work_title_patterns):
            r = sanitize(page, "title", wctx.sctx, 120)
            return WindowVerdict("work", "" if r.drop else r.text, False, "work_site")
        return WindowVerdict("unknown", "", False, "other")     # 미분류 웹: 제목 버림
    if app_class in ("chat_work", "mail_work"):                 # 팀즈·아웃룩 창 제목 = 사람·대화방 이름 → 저장 안 함
        return WindowVerdict("work", "", False, "app")
    if app_class in TITLE_KEEP_CLASSES:                         # Office·CAD·시뮬레이터·IDE: 문서명만 정제 저장
        r = sanitize(t, "title", wctx.sctx, 120)
        return WindowVerdict("work", "" if r.drop else r.text, False, "app")
    if app_class in ("system", "idle"):
        return WindowVerdict("unknown", "", False, "app")
    return WindowVerdict("work", "", False, "app")              # 미지 프로그램 = 업무 신호(요구사항), 제목은 저장 안 함
```
- `app_class` 는 프로그램 카탈로그(PC 사용 명세)가 준다. 카탈로그에 `messenger_private`·`game`·`media` 범주가 있으면 위 내장 목록과 합집합으로 쓴다(`messenger_private`·`game` → private, `media` → media).
- 브라우저 프로필 이름(`… - 개인 - Microsoft Edge`)이 `privacy.window.private_profiles`(기본 `개인`, `Personal`) 이면 private.
- 브랜드 이름 목록은 공개 서비스명이며 사내 정보가 아니다. 조직 고유 업무 사이트 제목어는 `privacy.window.work_title_patterns`(저장소 기본 빈 값).
- `WindowContext` = `{private_exes: set, private_profiles: set, work_title_patterns: list[re.Pattern], sctx: SanitizeContext}` — `make_record_context()` 가 설정에서 만든다.

### 12.7 사적 판정 시 처리 — 본문 삭제와 시간 근거 제외 규칙

**내용 처리**: private·social 행은 텍스트 열(`subject_masked`·`body_masked`·`attach_names_masked`·`file_names_masked`·`categories_masked`·`title_masked`·`chat_title_masked`·`text_masked`)을 비우고 `act_cues` 도 비운다. 메타(시각·방향·키·클래스)만 남긴다. 단, 비우기 **전에** 메모리에서 `abs_hint` 를 뽑는다:

```python
ABS_HINT = [
    ("half_am", re.compile(r"오전\s?반차")), ("half_pm", re.compile(r"오후\s?반차")), ("half", re.compile(r"반차")),
    ("leave", re.compile(r"연차|월차|휴가(?!\s?계획)|휴무")), ("sick", re.compile(r"병가")),
    ("early", re.compile(r"조퇴")), ("out", re.compile(r"외출")), ("trip", re.compile(r"출장")),
]   # 위에서부터 첫 일치 하나. 없으면 "none"
```

**시간 근거 규칙** (시간 명세가 반드시 구현 — 이 문서가 정책 소유):

| ID | 규칙 |
|---|---|
| R-P1 | private·social 행은 **능동 산출 신호(앵커)가 될 수 없다**(발신 메일·팀즈 발신이라도) |
| R-P2 | private·social 행은 단위 업무의 시작·종료·귀속 근거가 될 수 없다 |
| R-P3 정규 시간대 | 5분 슬롯의 근거가 사적(private·social, 그리고 정규 시간대의 media 는 R-P6)뿐인 슬롯이 **연속 `privacy.time.regular_private_run_min`(기본 30분 = 6슬롯) 이상**이면 그 구간 전체를 근무 봉투에서 뺀다. 더 짧으면 '중립'(봉투 판정에 영향 없음 — 앞뒤 업무 근거가 이어 주면 근무로 남음) |
| R-P4 표준창 밖 | 연장·야간·휴일에는 사적 근거만 있는 슬롯을 봉투에 넣지 않는다. 앵커 사이를 잇는 구간 계산에서 사적 전용 연속 구간이 **`privacy.time.offhours_private_break_min`(기본 15분 = 3슬롯) 이상**이면 그 지점에서 구간을 끊는다(앞 앵커 + pad 까지, 뒤 앵커 − pad 부터) |
| R-P5 개인 일정 | 민감도 1·2 또는 개인 범주 일정: 정규 시간대 → 그 슬롯을 '개인 부재'로 봉투에서 뺀다(같은 슬롯에 work 능동 산출 근거가 있으면 업무 우선). 표준창 밖 → 무시 |
| R-P6 unknown·media | 정규 시간대: unknown·media 는 일반 활동 근거. 표준창 밖: unknown 은 앵커 불가·앵커 사이 메우기만 허용, media 는 private 와 같음 |
| R-P7 기록 | 날짜별 설명 원장에는 '사적 제외 n슬롯', '사적 판정 n건'만 남긴다(내용·앱 이름 없음) |
| R-P8 부재 힌트 | `abs_hint` 는 사적 판정과 무관하게 부재·근무일 판정에 쓴다 |
| R-P9 차감 순서 | 사적 앱·사이트 전경 구간 차감은 봉투 계산의 **마지막 단계**(하한·다리·크레딧을 만든 뒤)에 하고, 차감량을 설명 원장에 남긴다(결정 메모 10.2) |

---

## 13. 코파일럿 전송 직전 게이트 (G3)

### 13.1 자료구조

```python
@dataclass
class GateItem:
    item_id: str                       # msg_key·unit_id 등 (HMAC 값 — 감사에 기록 가능)
    fields: dict[str, str | int | float]
    meta: dict                         # {"priv_class": ..., "ad_band": ..., "rules_ver": ...}

@dataclass(frozen=True)
class StageSpec:                       # 코파일럿 브리지 L4 단계마다 1개
    name: str                          # "classify" | "refine" | "workflow" | "agentic" ...
    allowed_fields: frozenset[str]     # 프롬프트에 직렬화할 수 있는 필드
    text_fields: frozenset[str]        # 그중 자유 텍스트(게이트 재검사 대상)
    max_item_chars: int = 400

@dataclass
class GateContext:
    sctx: SanitizeContext
    canaries: tuple[str, ...]          # PC 이름(COMPUTERNAME)·Windows 계정명·본인 주소 로컬파트·키 base64 앞 16자 …
    person_tokens: str = "plain"       # privacy.copilot.person_tokens
    audit: AuditSink | None = None

@dataclass
class GateResult:
    kept: list[GateItem]
    dropped: list[tuple[str, str]]     # (item_id, 사유 코드)
    counts: dict[str, int]
```

카나리아 목록(`make_gate_context()` 가 메모리에서 만든다 — 파일에 쓰지 않음): `COMPUTERNAME`, `USERNAME`, `USERDOMAIN`, `%USERPROFILE%` 의 마지막 폴더 이름, 본인 SMTP 주소 전체와 로컬파트, 본인 표시명(사람 사전 `self: true` 의 이름들), MachineGuid(하이픈 포함·제거 두 형태), 키링 각 키의 `secret_b64` 앞 16자, 팀 서버 업로드 토큰(설정에 있으면). 4자 미만은 무시(§13.2).

### 13.2 절차 — `gate_copilot()`

```python
def gate_copilot(items, stage, gctx):
    kept, dropped, counts = [], [], {}
    for it in items:
        if set(it.fields) - stage.allowed_fields:
            raise GateSpecError(stage.name)          # 프로그래밍 오류 → 단계 중단(fail-closed), 아무것도 안 보냄
        if it.meta.get("priv_class") in ("private", "social"):
            dropped.append((it.item_id, "class_private")); continue
        if it.meta.get("ad_band") == "suspect":
            dropped.append((it.item_id, "class_ad")); continue
        new_fields, bad = dict(it.fields), None
        for f in stage.text_fields & set(it.fields):
            out, info = gate_text(str(it.fields[f]), gctx)
            if out is None:
                bad = next(iter(info)); break
            for k, v in info.items():
                counts["remask:" + k] = counts.get("remask:" + k, 0) + v
            new_fields[f] = _safe_truncate(out, stage.max_item_chars)
        if bad:
            dropped.append((it.item_id, "pii:" + bad)); continue
        kept.append(GateItem(it.item_id, new_fields, it.meta))
    for _, why in dropped:
        counts["drop:" + why] = counts.get("drop:" + why, 0) + 1
    if gctx.audit:
        gctx.audit.flush(stage=stage.name, items_in=len(items), kept=len(kept), **counts)
    return GateResult(kept, dropped, counts)


def gate_text(text, gctx):
    """None 이면 그 항목 제외. 아니면 (재정제·축약된 텍스트, 재가림 건수)."""
    r = sanitize(text, "copilot", gctx.sctx)
    if r.drop:
        return None, {"cred": 1}
    high = {k: v for k, v in r.hits.items() if k in HIGH}
    if high:
        return None, high                            # 고위험 잔여 PII → 행 제외(값을 가려 보내지 않음: 정제 실패 신호이므로)
    t, low = r.text, r.text.lower()
    for c in gctx.canaries:
        c2 = c.lower()
        if len(c2) < 4:
            continue                                 # 너무 짧은 카나리아는 오탐 — 무시
        if re.fullmatch(r"[a-z0-9._\-]+", c2):
            if re.search(r"(?<![a-z0-9])" + re.escape(c2) + r"(?![a-z0-9])", low):
                return None, {"canary": 1}
        elif c2 in low:
            return None, {"canary": 1}
    if gctx.person_tokens == "plain":
        t = re.sub(r"\[사람#[0-9a-f]{6}\]", "[사람]", t)
    t = re.sub(r"\[이메일@([^\]]+)\]",
               lambda m: m.group(0) if m.group(1) in ("사내", "개인메일") or m.group(1).startswith(("고객사:", "협력사:"))
               else "[이메일@외부]", t)
    return t, r.hits                                 # MEDIUM(금액·고객사·사람·IP·URL·경로 등)은 재가림된 채 통과
```

### 13.3 최종 프롬프트 검사 — `gate_prompt_text()`

- L3 배치 실행기가 항목을 패킹해 프롬프트 문자열을 만든 **직후, L1 전송 직전**에 한 번 더 호출한다.
- 검사: `scan(prompt, gctx.sctx)` 가 빈 목록이어야 하고(토큰·날짜는 보호 구간이라 걸리지 않음), 카나리아 0건이어야 한다.
- 실패 시: 그 배치는 보내지 않는다(`status=gate_blocked`), 단계 저널에 사유 코드만. 항목 게이트를 통과한 뒤 실패했다면 템플릿·직렬화 결함이므로 재시도하지 않고 단계 오류로 올린다.
- 프롬프트 템플릿(코드 상수)은 §18 관문에서 전부 `scan()` 빈 목록을 확인한다.
- 코파일럿 계정이 '웹 근거' 토글을 켠 상태(브리지 탐침 결과)면 `person_tokens` 를 강제로 `plain` 으로 두고, MEDIUM 범주 중 `ip`·`url`·`path` 가 남은 항목도 제외한다(결정 메모 10.1 '재검사 강화').
- 수동 붙여넣기 대체 경로: 게이트를 통과한 프롬프트만 `%LOCALAPPDATA%\LoadMonitor27\agent\copilot_manual\` 에 쓰고, 성공 시 즉시 삭제·실패해도 7일 TTL 삭제. 번들(`data\`)에는 쓰지 않는다. 사용자가 붙여 넣어 돌려준 답도 같은 폴더·같은 TTL.

### 13.4 판정 표

| 상황 | 처리 | 감사 코드 |
|---|---|---|
| 행이 private·social | 제외 | `drop:class_private` |
| 행이 광고 의심(suspect) | 제외 | `drop:class_ad` |
| 재정제 시 자격증명 | 제외 | `drop:pii:cred` |
| 재정제 시 HIGH 범주(주민·외국인등록·생년월일·카드·여권·면허·계좌·전화·이메일·사업자·법인) | 제외 | `drop:pii:<범주>` |
| 카나리아 일치 | 제외 | `drop:pii:canary` |
| MEDIUM 범주(금액·비율·고객사·협력사·과제·사람·본인·IP·URL·경로·회사) | 재가림 후 통과 | `remask:<범주>` |
| 허용 밖 필드 | 단계 중단 | `err:GateSpecError` |
| 최종 프롬프트에 새 탐지 | 배치 미전송 | `gate_blocked` |

- 제외된 항목은 L3 가 재질의하지 않고 '로컬 규칙만으로 처리' 목록에 넣는다(분류 미정 → 확인 큐).
- 브리지 연동 메모(코파일럿 브리지 명세의 질문에 대한 답): ① `sanitize()` 의 `field_name` 은 감사·디버그용 이름표일 뿐 규칙 분기에 쓰이지 않는다 — 코파일럿 답 입수 정제에 `field_name="copilot_answer"` 를 그대로 써도 된다(답도 같은 정제기를 거친 뒤에만 저장). ② 목록형 텍스트를 `"\n"` 으로 이어 한 필드로 넣어도 된다 — 줄바꿈은 제어문자 치환 대상(§6 `CTRL_RX`)이 아니어서 남고, 탐지는 이은 문자열 전체에 대해 한 번 돈다. ③ `max_item_chars` 는 재정제 **후** 필드 하나당 길이 상한이다(이은 문자열 전체 기준, 토큰 안 자름). ④ 감사는 `AuditSink.open(data_dir, pc_id, stage="copilot:<단계>", src="copilot")` 로 연다(§3.3·§15.1).
- 코파일럿에 시간·MM·pc_id·who_key·kid 는 보내지 않는다(분류·명명·요약·연관성 서술만 — 결정 메모 §5). `StageSpec.allowed_fields` 에 이 이름들이 있으면 브리지 단계 등록 때 `GateSpecError`.

---

## 14. 팀 업로드 허용 목록 (G4)

### 14.1 원칙

- 업로드에는 **집계와 라벨만**. 신호 단위 행·정제문 원문 목록·표시명·주소·pc_id·호스트명·who_key·kid 는 금지.
- **필드 목록은 팀/번들 명세 §2.3 이 소유**한다(H10). 이 문서는 ① 값 클래스(§14.2) ② 어떤 필드에도 나타나면 안 되는 금지 값(§14.3) ③ 사람이 읽는 라벨 검사(§14.4)를 소유하고, 필드 → 클래스 대조표(§14.5)를 두 명세가 같은 커밋에서 맞춘다.
- 직렬화는 한 번만 하고(`canon_bytes`), 그 바이트로 검사·미리보기·전송을 한다(미리보기 = 실제 전송본). 전송본 sha256 을 감사에 남긴다.
- 서버도 수신 시 같은 `check_team_payload()` 로 재검증하고 위반이면 422 + 위반 코드 목록(값 없음)을 돌려준다.

### 14.2 값 클래스

| 클래스 | 검사 |
|---|---|
| `ENUM:<어휘>` | 닫힌 어휘 안의 값(업무 영역 `DEV·MP·EXT·COM·AX·UNC`, 분야, 기능, 업무 유형, 시간 꼬리표 `regular·extended·night·holiday`, 신뢰도 등급, 상태 등 — 어휘는 레지스트리·팀/번들 명세) |
| `PROJECT_ID` | `^P-\d{4}$` |
| `PROPOSAL_ID` | `^pr_\d{1,4}$` |
| `ROLE_ID` | `^r_[0-9a-f]{6}$` |
| `UNIT_ID` | `^u_[0-9a-f]{10}$` |
| `REG_ID` | `^[A-Za-z][A-Za-z0-9_\-]{0,23}$` (레지스트리 고객사·협력사·agentic 카탈로그 ID 등) |
| `PERSON_KEY` | `^p_[0-9a-f]{12}$` (번들 주인 무작위 ID — 신원에서 유도하지 않음) |
| `PEER_KEY` | `^c_[0-9a-f]{12}$` (§9.7 — 사내 도메인 주소에서 만든 것만) |
| `APP_ID` | `^[a-z0-9_.\-]{1,24}$` (카탈로그 앱 ID) |
| `NUM` | 유한한 int/float, ≥0 (팀/번들 명세가 범위를 더 좁힐 수 있음) |
| `DATE`·`MONTH`·`UTC` | `YYYY-MM-DD` / `YYYY-MM` / ISO 8601(Z 또는 오프셋) |
| `LABEL20`·`LABEL30`·`LABEL40`·`LABEL60` | `check_team_label(s, max_len)` 통과 |
| `COUNTS` | `{범주코드: NUM}` — 범주코드는 §15.3 표 |
| `VER` | `^\d{4}\.\d{1,2}\.\d{1,3}$` 또는 `^\d+\.\d+(?:\.\d+)?$` 또는 16hex 해시 |

### 14.3 금지 값 (클래스와 무관하게 모든 문자열 값·키 이름에 적용)

| 코드 | 정규식·판정 |
|---|---|
| `forbidden:who_key` | `(?<![0-9a-z_])w[0-9a-f]{16}(?![0-9a-f])` |
| `forbidden:local_key` | `(?<![0-9a-z_])[mehtdfrg][0-9a-f]{16,24}(?![0-9a-f])` (msg·cal·thread·chat·doc·path·repo·commit 키) |
| `forbidden:kid` | `(?<![0-9a-z_])k[0-9a-f]{8}(?![0-9a-f])` |
| `forbidden:pc_id` | `pcx?_[0-9a-f]{16}` |
| `forbidden:guid` | `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}` (MachineGuid 등) |
| `forbidden:email` | `RX["email"]` 일치 또는 `@` 포함 |
| `forbidden:path` | `RX["path"]` 일치 또는 `\` 포함 |
| `forbidden:url` | `RX["url"]` 일치 |
| `forbidden:ip` | `RX["ipv4"]` 일치(검증 통과분) |
| `forbidden:digits` | 숫자 9자리 이상 연속(`\d{9,}`) — `NUM`·`DATE`·`UTC`·`VER` 클래스 값은 제외 |
| `forbidden:canary` | 카나리아(§13.1) 포함 |

`PERSON_KEY`·`PEER_KEY`·`UNIT_ID`·`ROLE_ID`·`VER` 클래스 필드의 값은 그 클래스 정규식 검사만 받고 `local_key`·`digits` 금지 검사는 면제한다(16진 해시·`c_…` 같은 키 형식이 오탐되지 않게). 그 밖의 금지 검사(이메일·경로·카나리아 등)는 면제하지 않는다.

### 14.4 팀 라벨 검사 — `check_team_label()`

```python
LABEL_FORBID = re.compile(r"@|\\|\d{5,}|\[사람#|\[이메일@|\[URL\]|\[경로\]")

def check_team_label(s, gctx, max_len=40):
    v = []
    if not isinstance(s, str):
        return ["type"]
    if len(s) > max_len:
        v.append("too_long")
    if LABEL_FORBID.search(s):
        v.append("forbidden_pattern")             # 주소·경로·긴 숫자·사람 가명·이메일·URL
    r = sanitize(s, "label", gctx.sctx)
    if r.drop or r.text != s or r.hits:
        v.append("not_clean")                     # 정제기가 바꿀 것이 남아 있으면 불합격(이미 정제된 라벨만 허용)
    low = s.lower()
    if any(len(c) >= 4 and c.lower() in low for c in gctx.canaries):
        v.append("canary")
    return v
```
라벨에 허용되는 토큰은 `[금액]`·`[비율]`·`[과제:ID]`·`[고객사:ID]`·`[협력사:ID]`·`[회사]`·`[사람]`(평문)뿐이다. 라벨을 만드는 쪽(분석 단계)은 게이트 축약 규칙(§13.2 `gate_text`)을 먼저 적용해 둔다. 팀/번들 명세의 `team_text` 검사는 이 함수를 부른다(같은 판정).

### 14.5 팀 묶음 필드 → 값 클래스 대조 (팀/번들 명세 §2.3.2 기준 — 그쪽이 필드를 바꾸면 같은 커밋에서 이 표를 갱신)

| 경로 | 클래스 |
|---|---|
| `schema` | 상수 `"lm27.team_bundle"` |
| `schema_version` | `VER` |
| `generator.*` | `LABEL40` 또는 `NUM` |
| `built_at` | `UTC` |
| `person.person_key` | `PERSON_KEY` |
| `person.self_label` | `LABEL20`(비면 서버가 `팀원-<KEY4>` 표시) |
| `person.self_peer_key` | `PEER_KEY` 또는 null |
| `person.function` | `ENUM:fields` 또는 `""` |
| `person.peer_scope` | `ENUM{team, personal}` |
| `period.from`·`period.to`·`period.months[]`·`period.analyzed_until` | `DATE`·`DATE`·`MONTH`·`UTC` |
| `summary.std_day_min`·`summary.months[].*` | `NUM`(달 키는 `MONTH`) |
| `envelope_daily.rows[]` | `[DATE, NUM, NUM, NUM, NUM]` |
| `alloc_daily.rows[]` | `[DATE, UNIT_ID, ENUM:tag, NUM]` |
| `projects[].project_id`·`.domain` | `PROJECT_ID`·`ENUM:domain` |
| `proposals[].proposal_id`·`.label` | `PROPOSAL_ID`·`LABEL40` |
| `roles[].role_id`·`.project_id`·`.proposal_id`·`.field`·`.function` | `ROLE_ID`·`PROJECT_ID?`·`PROPOSAL_ID?`·`ENUM:fields`·`ENUM:functions` |
| `units[].unit_id`·`.title`·`.start.kind`·`.end.kind`·`.precision`·`.grade`·`.status`·`.effort_min`·`.gantt_spans[]`·`.apps[]` | `UNIT_ID`·`LABEL40`·`ENUM`·`ENUM`·`ENUM`·`ENUM:grade`·`ENUM`·`NUM`·`[DATE, DATE, ENUM{active,lead}]`·`APP_ID` |
| `workflows[].role_id`·`.steps[].type`·`.steps[].label`·`.edges[]` | `ROLE_ID`·`ENUM:step_types`·`LABEL30`·`[NUM, NUM]` |
| `agentic.*.agent_id`·`.grade`·`.needs[].label`·`.units[]` | `REG_ID`·`ENUM{상,중,하}`·`LABEL40`·`UNIT_ID` |
| `peers[].peer_key`·`.scope`·`.n`(공유 근거 수 등 수치) | `PEER_KEY`·`ENUM{team, personal}`·`NUM` |
| `quality.*` | `NUM`·`ENUM`·`LABEL20` |
| `integrity.*` | `NUM` |
| `privacy_counts` (**이 문서가 요구하는 추가 필드** — 팀/번들 명세에 반영 요청, §21 Q18) | `COUNTS`(기간 합계, §15) |
| `catalog_proposals[].exe`·`.company`·`.product`·`.n_days` (PC 명세 §6.4 '미상 프로그램 라벨링 제안' — 반영 요청) | `re:^[a-z0-9_.\-]{1,64}\.exe$`·`LABEL40`·`LABEL40`·`NUM` (회사·제품명은 정제 후 `check_team_label` 통과분만) |

```python
def check_team_payload(payload, gctx, spec=None) -> list[Violation]:
    """spec(기본 TEAM_SPEC_V1 = §14.5 표)를 재귀 순회. 모르는 키 → unknown_key, 클래스 불일치 → bad_<클래스>,
    라벨 위반 → label:<코드>. 모든 문자열 값·키 이름에 §14.3 금지 값 검사 → forbidden:<코드>.
    Violation(path='units[3].title', code='label:not_clean'). 위반이 하나라도 있으면 업로드하지 않는다(fail-closed).
    위반 목록에는 값이 아니라 경로·코드만."""
```

---

## 15. 감사 로그

### 15.1 위치·형식 (H13)

- **에이전트(상주 수집기)**: `%LOCALAPPDATA%\LoadMonitor27\agent\store\privacy_audit\<YYYYMM>\<YYYYMMDD>.jsonl`(추가 전용, UTF-8 LF). [수집]의 내보내기가 다른 스트림과 똑같이 번들 세그먼트로 옮긴다.
- **프로그램 폴더 실행(전경 수집기·적재·게이트·팀 업로드)**: 실행 1회의 감사 이벤트를 모아 불변 세그먼트 스트림 `privacy_audit` 으로 `data\pcs\<pc_id>\seg\privacy_audit\…jsonl.gz` 에 쓴다(배치·이름·manifest 등록은 팀/번들 명세 §1 의 세그먼트 규칙 그대로). 클라우드PC 의 게이트 감사는 클라우드PC 의 pc_id 아래로 간다.
- 보존: 에이전트 로컬 원장은 `privacy.audit.retention_months`(기본 24개월)가 지나면 자기 것만 지운다. 번들 세그먼트는 지우지 않는다(건수뿐이라 작다).
- 한 실행에서 이벤트가 많으면(월 5 MB 상당) 시간 단위로 합쳐 1줄씩 쓴다.

### 15.2 이벤트 스키마 (이 키 외에는 쓰지 않는다)

```json
{"ev": "collect_batch", "ts_utc": "2026-10-05T01:02:03Z", "pc_id": "pc_9a1b2c3d4e5f6a7b", "stage": "collect", "src": "mail.com",
 "rules_ver": "2026.10.0", "rules_hash": "4a684ebdcf99f956", "config_hash": "9c1e0b7a22d4f3e1", "kid": "k3f9a1c2e",
 "rows_in": 812, "rows_out": 640,
 "dropped": {"ad": 160, "cred": 2, "bad_raw": 10},
 "masked": {"phone": 14, "email": 230, "money": 9, "person": 412, "customer": 21},
 "priv": {"work": 598, "private": 37, "social": 5},
 "ad": {"keep": 621, "suspect": 19, "drop": 160, "partial": 0},
 "err": {"KeyError": 0},
 "out_sha256": "<출력 파일 sha256>", "dur_ms": 4210}
```
- `ev` ∈ `collect_batch`·`load_resanitize`·`gate_copilot`·`gate_prompt`·`gate_team`·`rewrite_redact`·`key`·`config`·`selftest`·`merge`.
- 값은 숫자·버전·16진 해시·범주 코드·경로 ID 뿐. 문자열 원문·정제문·예시·파일 경로·도메인 이름 금지(I8). §18 관문이 감사 기록을 검사한다(키 허용 목록·값 형식·숫자 9자리 이상 연속 금지·`@` 금지·한글 문장 금지).
- 위 예의 `rules_hash` 값은 형식 예시다 — 실제 값은 `rules.lock.json` 이 정본.

### 15.3 범주 코드표

| 코드 | 뜻 | 코드 | 뜻 |
|---|---|---|---|
| `rrn` | 주민번호 | `ip` | IP |
| `frn` | 외국인등록번호 | `url` | URL |
| `birth` | 생년월일 | `path` | 경로 |
| `card` | 카드 | `money` | 금액 |
| `phone` | 전화 | `rate` | 비율 |
| `brn` | 사업자번호 | `customer` | 고객사 |
| `corp` | 법인번호 | `partner` | 협력사 |
| `passport` | 여권 | `project` | 과제 코드네임 |
| `license` | 운전면허 | `company` | 회사 접미형 |
| `account` | 계좌 | `person` | 사람 |
| `email` | 이메일 | `self` | 본인 |
| `cred` | 자격증명(행 폐기) | `canary` | 카나리아 |

행 단위 사유: `ad`, `private_folder`, `folder_excluded`, `bad_raw`, `no_key`, `class_private`, `class_ad`, `unsealed_row`. 병합·유지보수: `fuzzy`(키 충돌 보조 병합), `doclink_lost`, `truncated_tail`, `rewrite_redact`. 키: `created`, `corrupt`, `conflict`, `bundle_readonly`, `agent_rotated`. 설정: `bad_id`, `short_alias`, `generic_alias`, `dup_alias`, `bad_regex`, `allow_too_broad`, `bad_value`. 오류: 예외 타입명, `column:<열 이름>`.

### 15.4 해시

- `rules_hash`: §16.2. `config_hash`: §16.3.
- `out_sha256`: 수집이면 쓴 출력 파일(append 모드면 덧붙인 gzip 멤버 바이트), 게이트면 보낸 프롬프트 문자열(UTF-8), 팀이면 전송 바이트.
- 코파일럿 브리지 저널의 `prompt_sha256` 와 같은 값이어야 한다(교차 확인).

### 15.5 로컬 감사 화면(개인 UI, 127.0.0.1 전용)

- 기간·출처별 표: 가린 범주 건수, 버린 행 사유 건수, 사적·광고 판정 건수, 경로별 `ad_partial` 비율, 에이전트 `no_key` 건수.
- '정제 시험대': 사용자가 입력한 문장을 그 자리에서 `sanitize()`·`scan()` 해 전후를 보여 준다(메모리만, 저장 안 함). 오탐 신고 → `privacy.allow_patterns` 후보로 제안(§17.3 검증 후 저장).
- '광고 의심' 큐: suspect 행의 정제 제목 + [차단]·[허용].
- 팀 보고서에는 범주별 건수(`privacy_counts`)만 간다.

---

## 16. 규칙 버전 관리

### 16.1 버전 문자열

`YYYY.MM.N` — 어휘·가중치·문맥어만 바뀌면 N 증가, 탐지기 추가·순서 변경이면 연·월 갱신(N=0). 비교는 `tuple(int(x) for x in v.split("."))`.

### 16.2 `RULES_HASH`

`rules.py`·`classify.py` 의 모든 `re.Pattern`(패턴 문자열 + 플래그), `RX`·`PROTECT`·`CTX` 표, `NAME_STOP`·`SURNAMES`·`HIGH`·가중치 상수(`AD_DROP`·`AD_SUSPECT`·`PRIV_THRESHOLD`)와 `RULES_VERSION` 을 키 이름순 JSON(`ensure_ascii=False, sort_keys=True`)으로 덤프해 sha256 앞 16자. 모듈 import 시 계산한다.

```python
def rules_hash() -> str:
    parts = {}
    for name, val in sorted(_rule_namespace().items()):          # rules·classify 모듈의 전역
        if isinstance(val, re.Pattern):
            parts[name] = [val.pattern, val.flags]
        elif name == "RX":
            parts[name] = {k: [x.pattern, x.flags] for k, x in val.items()}
        elif name == "PROTECT":
            parts[name] = [[k, x.pattern, x.flags] for k, x in val]
        elif name in ("CTX", "NAME_STOP", "NAME_SUFFIX_STOP", "SURNAMES", "COMPOUND_SURNAMES", "HIGH",
                      "AD_DROP", "AD_SUSPECT", "PRIV_THRESHOLD", "RULES_VERSION", "PERSONAL_MAIL_DOMAINS"):
            parts[name] = sorted(val) if isinstance(val, (set, frozenset)) else val
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
```

- `keys.py` 의 `DOC_EXT`·`DOC_TAIL`·`PURPOSES` 는 규칙 해시에 넣지 않는다 — 키 계산 규칙이므로 바뀌면 doc_key 연속성이 끊긴다. 대신 `KEYS_VERSION = "lm27-keys/1"` 상수를 두고, 바꾸면 그 상수를 올리고 적재기가 `kid` 처럼 판을 구분한다(§21 Q20).

### 16.3 `CONFIG_HASH`

정제에 영향을 주는 설정(§17 의 `privacy.*` 전부 + 레지스트리의 customers·partners·projects.codenames·internal_domains)을 같은 방식으로 덤프한 sha256 앞 16자. 행에는 넣지 않고 감사 이벤트에만 기록한다. 에이전트는 [수집] 때 받은 `context_cache.json` 의 해시를 쓴다.

### 16.4 변경 절차 (관문으로 강제)

1. 규칙 코드를 고친다.
2. 말뭉치(`regress_v1.jsonl`)에 그 변경을 증명하는 양성·미끼를 **먼저** 추가한다.
3. `RULES_VERSION` 을 올린다.
4. `python\python.exe -B tools\lm27_selftest.py privacy --update-lock` — 말뭉치 전부 통과할 때만 `rules.lock.json` 을 새 `{rules_ver, rules_hash}` 로 쓴다.
5. 커밋 메시지에 '정제 규칙 <옛 버전> → <새 버전>: 무엇을 왜'.

관문: import 시 계산한 `RULES_HASH` ≠ `rules.lock.json` 의 해시이거나, 버전은 같은데 해시가 다르면 selftest 실패("규칙이 바뀌었는데 버전·말뭉치 갱신 안 됨").

### 16.5 기존 자료에 대한 효과

- 새 규칙이 더 가리는 경우: 적재 시 `resanitize_row()` 가 반영(G2). 자기 pc_id 세그먼트는 유지보수 때 `redact_rewrite()`.
- 오탐 수정(덜 가리게)인 경우: 이미 가린 값은 원문이 없으므로 되살아나지 않는다(I5). 미래 행부터 적용.
- 코파일럿 단계 저널에 기록된 `rules_ver` 가 현재보다 낮은 결과는 재사용하되, 같은 항목을 다시 보낼 때는 현재 게이트를 다시 거친다.
- 에이전트 bin 의 정제기 사본은 [수집] 때 sha256 대조로 교체된다(§3.6). 교체 전후 행은 `rules_ver` 로 구분된다.

---

## 17. 설정 키

### 17.1 목록 의미론

모든 목록형 설정은 **내장 기본 ∪ add − disable**. 값은 배열(= add 로 간주) 또는 `{"add": [...], "disable": [...]}`. LM24 의 '대체'/'합집합' 혼재를 없앤다. 설정 키는 설정 레지스트리(단일 원천)에 아래 그대로 등록하고, 읽히지 않는 키(죽은 키)는 lint 가 실패시킨다. 각 키의 '읽는 곳' 열이 lint 의 근거다.

### 17.2 키 표

| 키 | 타입 | 기본값(저장소) | 뜻 | 읽는 곳 |
|---|---|---|---|---|
| `privacy.internal_domains` | list[str] | `[]` | 사내 도메인(레지스트리 `internal_domains` 와 합집합). 본인 SMTP 도메인은 런타임에 자동 추가(저장하지 않음) | `build_context`, `peer_key` |
| `privacy.personal_mail_domains` | list / {add,disable} | 내장 `PERSONAL_MAIL_DOMAINS` | 공용 개인 메일 도메인 | `build_context` |
| `privacy.customers` | list[{id,names,domains}] | `[]` | 개인 추가 고객사(팀 레지스트리 `registry.customers` 와 합집합) | `build_context` |
| `privacy.partners` | list[{id,names,domains}] | `[]` | 개인 추가 협력사 | `build_context` |
| `privacy.allow_patterns` | list[str 정규식] | `[]` | 조직 허용 패턴(부품·도면 번호 형식, 사내 대표번호 등) — §17.3 검증 | `build_context` |
| `privacy.extra_ctx.account` / `.passport` / `.license` / `.money` / `.ip` / `.card` | list[str] | `[]` | 범주별 추가 문맥어(정규식 아님, 문자 그대로) | `build_context` |
| `privacy.mask_company_suffix` | bool | `true` | `(주)XXX` 등 → `[회사]` | `build_context` |
| `privacy.money.mask_rates` | bool | `true` | 할인·마진율 → `[비율]` | `build_context` |
| `privacy.names.extra_stopwords` | list[str] | `[]` | 호칭형 이름 오탐 단어 추가 | `build_context`(사전 검증·호칭형 후처리) |
| `privacy.path.exclude_keywords` | list / {add,disable} | 내장 `개인`, `가족`, `사진`, `private`, `personal` | 파일·git 수집 사적 폴더(§10.4) | `records.path_excluded` |
| `privacy.ad.block_domains` / `.allow_domains` | list[str] | `[]` | 광고 차단·허용 고정분 | `make_record_context` |
| `privacy.ad.block_subject_regex` | list[str 정규식] | `[]` | 제목 차단 정규식 | `make_record_context` |
| `privacy.ad.extra_words` | list[str] | `[]` | 광고어 추가(문자 그대로, §11.2 호출 쪽 가점) | `records`(mail 광고 특징) |
| `privacy.private.categories` | list / {add,disable} | 내장 `개인`, `Personal`, `Private`, `가족` | Outlook 개인 범주 이름 | `records`(mail·cal) |
| `privacy.private.extra_words` / `.extra_work_words` | list[str] | `[]` | 사적 강한 어휘 / 업무 어휘 추가(§12.3 호출 쪽 보정) | `records.privacy_verdict` |
| `privacy.window.private_exes` | list / {add,disable} | 내장 `PRIVATE_EXES` | 비업무 프로그램(소문자 exe) | `make_record_context`(WindowContext) |
| `privacy.window.private_profiles` | list[str] | `["개인", "Personal"]` | 사적 브라우저 프로필 이름 | 〃 |
| `privacy.window.work_title_patterns` | list[str 정규식] | `[]` | 사내 업무 사이트 제목어(조직 고유 — 저장소 기본 빈 값) | 〃 |
| `privacy.time.regular_private_run_min` | int(분, 5의 배수) | `30` | R-P3 | 시간 모델 |
| `privacy.time.offhours_private_break_min` | int(분, 5의 배수) | `15` | R-P4 | 시간 모델 |
| `privacy.copilot.person_tokens` | `"plain"` / `"keyed"` | `"plain"` | 코파일럿에 `[사람]` 만 보낼지, `[사람#6hex]` 를 보낼지 | `make_gate_context` |
| `privacy.audit.retention_months` | int | `24` | 에이전트 로컬 감사 원장 보존 | 에이전트 유지보수 |
| `privacy.pipe.wait_sec` | int(30~1800) | `120` | PS 수집기가 정제 파이프 종료를 기다리는 시간(§3.5) | 수집기 PS 골격 |

읽기 전용 참조(레지스트리·팀/번들 명세 소유): `registry.customers[]`, `registry.partners[]`, `registry.projects[].codenames`, `registry.projects[].mask_name`, `registry.internal_domains[]`, `registry.pepper`.

가중치·임계·탐지 정규식은 **설정 키가 아니다**(규칙 버전으로만 바뀐다).

### 17.3 설정 검증 (`build_context()`)

| 대상 | 검사 | 실패 시 |
|---|---|---|
| 모든 정규식 값 | `re.compile` 성공, 길이 ≤200, 빈 문자열에 매치 안 함 | 그 항목 무시, `cfg.bad_regex` |
| `allow_patterns` | 말뭉치(§18) **양성 입력의 PII 값**(예: `010-1234-5678`) 중 하나라도 `fullmatch`/`search` 하면 거부 — '모든 숫자 허용' 같은 위험 패턴 차단 | 거부, `cfg.allow_too_broad` |
| 사전 항목 | §8.3 | |
| 시간 값 | 5의 배수, 5~240 | 기본값 사용, `cfg.bad_value` |
| `privacy.pipe.wait_sec` | 30~1800 | 기본값 사용, `cfg.bad_value` |
| 저장소 기본 설정(`config.default.json`) | 패키징 lint: `privacy.customers`·`privacy.partners`·`privacy.internal_domains`·`privacy.window.work_title_patterns`·`registry.*.codenames` 가 비어 있어야 함, 사설 IP·이메일 형식 문자열이 없어야 함(팀 서버 기본 주소처럼 결정 메모가 정한 값은 lint 허용 목록에 명시) | 패키징 실패 |

---

## 18. 회귀 말뭉치와 관문

### 18.1 파일 형식 `lm27/privacy/corpus/regress_v1.jsonl` (UTF-8 LF, 한 줄 1건)

```json
{"id": "P10", "type": "pos", "text": "제 번호 010-1234-5678 로 연락주세요", "expect": "제 번호 [전화] 로 연락주세요", "hits": {"phone": 1}, "ctx": null}
{"id": "X01", "type": "drop", "text": "VPN 비밀번호: Abc!2345 공유"}
{"id": "N03", "type": "neg", "text": "하우징 공차 0.05 mm, 전압 12 V, 1,500 rpm"}
{"id": "A05", "type": "ad", "meta": {"subject": "신제품 출시 안내", "internal": false, "corresp_domain": true, "hdr": {"list_unsubscribe": true}, "rcv": "bulk"}, "band": "drop"}
{"id": "Q05", "type": "priv", "text": "저녁 회식 장소 투표해 주세요", "kw": {"chat_type": "group"}, "class": "social"}
```
- `ctx: "A"` 인 항목은 아래 고정 문맥 A 로 실행한다(키는 `b"\0"*32`, `person_subkey` 없음). 문맥 A 의 과제 ID `P0001` 은 시험값이다 — 토큰 문법(`[과제:<1~16자 영숫자·_·->]`)은 레지스트리 형식 `P-0001` 도 똑같이 받는다.
```json
{"internal_domains": ["corp.example"],
 "customers": [{"id": "C01", "names": ["고객사A", "CustA"], "domains": ["custa.example"]}],
 "projects": [{"id": "P0001", "codenames": ["과제A", "PROJ-A"]}],
 "persons": {"김철수": "a1b2c3d4e5f60718"},
 "self_names": ["홍길동"]}
```
- 기대 출력의 `[사람#*]` 는 '임의 6hex 태그'를 뜻한다(사전에 없는 이름 — 키 값에 의존하지 않게). 그래서 HMAC 도메인 접두를 `lm26:` → `lm27:` 로 바꿔도 말뭉치 기대값은 그대로다.

### 18.2 말뭉치 v1 전체 (초판 시제품으로 전부 통과 확인 — LM27 이관에서 입력·기대값 변경 없음)

**양성 60건 (`pos`) — 정확히 기대 출력과 같아야 하고, 다시 정제하면 그대로(멱등)**

| ID | 입력(합성) | 기대 출력 | 건수 | ctx |
|---|---|---|---|---|
| P01 | `RE: 주민번호 900101-1234567 확인 요청` | `RE: 주민번호 [주민번호] 확인 요청` | {"rrn": 1} | - |
| P02 | `생년 및 주민 8001012345678 기재` | `생년 및 주민 [주민번호] 기재` | {"rrn": 1} | - |
| P03 | `등본상 900101-1****** 로 표기` | `등본상 [주민번호] 로 표기` | {"rrn": 1} | - |
| P04 | `외국인등록번호 950505-5123456 사본` | `외국인등록번호 [외국인등록번호] 사본` | {"frn": 1} | - |
| P05 | `신청서 8501011234566 첨부` | `신청서 [주민번호] 첨부` | {"rrn": 1} | - |
| P06 | `카드번호 4111-1111-1111-1111 결제 확인` | `카드번호 [카드] 결제 확인` | {"card": 1} | - |
| P07 | `법인카드 5555 5555 5555 4444 사용 내역` | `법인카드 [카드] 사용 내역` | {"card": 1} | - |
| P08 | `3782-822463-10005 승인` | `[카드] 승인` | {"card": 1} | - |
| P09 | `카드 1234-****-****-5678 결제 완료` | `카드 [카드] 결제 완료` | {"card": 1} | - |
| P10 | `제 번호 010-1234-5678 로 연락주세요` | `제 번호 [전화] 로 연락주세요` | {"phone": 1} | - |
| P11 | `연락처 01098765432` | `연락처 [전화]` | {"phone": 1} | - |
| P12 | `+82 10 1234 5678 / 대표 02-123-4567` | `[전화] / 대표 [전화]` | {"phone": 2} | - |
| P13 | `(031) 123-4567 로 회신` | `[전화] 로 회신` | {"phone": 1} | - |
| P14 | `인터넷전화 070-1234-5678` | `인터넷전화 [전화]` | {"phone": 1} | - |
| P15 | `고객센터 1588-1234 문의` | `고객센터 [전화] 문의` | {"phone": 1} | - |
| P16 | `안심번호 0505-123-4567` | `안심번호 [전화]` | {"phone": 1} | - |
| P17 | `사업자등록번호 123-45-67891 거래처 등록` | `사업자등록번호 [사업자번호] 거래처 등록` | {"brn": 1} | - |
| P18 | `번호 220-81-62517 확인` | `번호 [사업자번호] 확인` | {"brn": 1} | - |
| P19 | `여권번호 M12345678 로 출장 항공권 예약` | `여권번호 [여권] 로 출장 항공권 예약` | {"passport": 1} | - |
| P20 | `passport M123A4567 사본 송부` | `passport [여권] 사본 송부` | {"passport": 1} | - |
| P21 | `운전면허 11-23-456789-01 사본` | `운전면허 [운전면허] 사본` | {"license": 1} | - |
| P22 | `운전면허증 서울 12-345678-90 갱신` | `운전면허증 [운전면허] 갱신` | {"license": 1} | - |
| P23 | `계좌 110-123-456789 로 송금 부탁드립니다` | `계좌 [계좌] 로 송금 부탁드립니다` | {"account": 1} | - |
| P24 | `입금 계좌 3333012345678 카카오뱅크` | `입금 계좌 [계좌] 카카오뱅크` | {"account": 1} | - |
| P25 | `국민은행 123456-01-234567 예금주 홍길동` | `국민은행 [계좌] 예금주 [사람#*]` | {"account": 1, "person": 1} | - |
| P26 | `보고서 송부 drafter.kim@example.co.kr` | `보고서 송부 [이메일@example.co.kr]` | {"email": 1} | - |
| P27 | `회신: user01@corp.example` | `회신: [이메일@사내]` | {"email": 1} | A |
| P28 | `서버 10.1.2.3:8080 재기동` | `서버 [IP] 재기동` | {"ip": 1} | - |
| P29 | `접속 IP 203.0.113.25 차단` | `접속 IP [IP] 차단` | {"ip": 1} | - |
| P30 | `링크 https://portal.example.com/view?id=12345&user=kim 참고` | `링크 [URL] 참고` | {"url": 1} | - |
| P31 | `C:\Users\hong\Documents\견적.xlsx` | `[경로]\견적.xlsx` | {"path": 1} | - |
| P32 | `[과제X] 수주 금액 12억 3400만원 확정 건` | `[과제X] 수주 금액 [금액] 확정 건` | {"money": 1} | - |
| P33 | `고객사 견적 단가 USD 1250000 으로 회신` | `고객사 견적 단가 [금액] 으로 회신` | {"money": 1} | - |
| P34 | `견적 단가 1,250,000 / 수량 300 ea` | `견적 단가 [금액] / 수량 300 ea` | {"money": 1} | - |
| P35 | `계약금 3,000,000원 입금` | `계약금 [금액] 입금` | {"money": 1} | - |
| P36 | `단가: 850 로 확정` | `단가: [금액] 로 확정` | {"money": 1} | - |
| P37 | `Quote $1.2M for next lot` | `Quote [금액] for next lot` | {"money": 1} | - |
| P38 | `PO 금액 12,000,000 확정` | `PO 금액 [금액] 확정` | {"money": 1} | - |
| P39 | `고객사A 2차 미팅 준비` | `[고객사:C01] 2차 미팅 준비` | {"customer": 1} | A |
| P40 | `kim@custa.example 회신` | `[이메일@고객사:C01] 회신` | {"email": 1} | A |
| P41 | `PROJ-A 샘플 시험 결과` | `[과제:P0001] 샘플 시험 결과` | {"project": 1} | A |
| P42 | `김철수 책임님께 보고드립니다` | `[사람#*] 책임님께 보고드립니다` | {"person": 1} | - |
| P43 | `@홍길동 확인 부탁드립니다` | `@[사람#*] 확인 부탁드립니다` | {"person": 1} | - |
| P44 | `김철수 회신 대기` | `[사람#a1b2c3] 회신 대기` | {"person": 1} | A |
| P45 | `홍길동 작성 보고서` | `[나] 작성 보고서` | {"self": 1} | A |
| P46 | `네고율 5% 인하 합의` | `네고율 [비율] 인하 합의` | {"rate": 1} | - |
| P47 | `㈜가나다 견적 회신` | `[회사] 견적 회신` | {"company": 1} | - |
| P48 | `출장비 500,000원 정산` | `출장비 [금액] 정산` | {"money": 1} | - |
| P49 | `6억 규모 사업 검토` | `[금액] 규모 사업 검토` | {"money": 1} | - |
| P50 | `생년월일: 1990.01.01` | `생년월일: [생년월일]` | {"birth": 1} | - |
| P51 | `주민번호 앞자리 900101 만 기재` | `주민번호 앞자리 [주민번호] 만 기재` | {"rrn": 1} | - |
| P52 | `장애 서버 fe80::1ff:fe23:4567:890a` | `장애 서버 [IP]` | {"ip": 1} | - |
| P53 | `\\fs01\share\팀\보고서.pptx` | `[경로]\보고서.pptx` | {"path": 1} | - |
| P54 | `Fax.02-123-4568 / Tel.010-1234-5678` | `Fax.[전화] / Tel.[전화]` | {"phone": 2} | - |
| P55 | `견적 1억 5천만 원 / 납기 2026-11-30` | `견적 [금액] / 납기 2026-11-30` | {"money": 1} | - |
| P56 | `견적_고객사A_010-1234-5678.xlsx - Excel` | `견적_고객사A_[전화].xlsx - Excel` | {"phone": 1} | - |
| P57 | `여권사본_M12345678.jpg` | `여권사본_[여권].jpg` | {"passport": 1} | - |
| P58 | `사업자등록증_123-45-67891.pdf` | `사업자등록증_[사업자번호].pdf` | {"brn": 1} | - |
| P59 | `급여계좌_110-123-456789.pdf` | `급여계좌_[계좌].pdf` | {"account": 1} | - |
| P60 | `등본_900101-1234567.pdf` | `등본_[주민번호].pdf` | {"rrn": 1} | - |

(P25·P42·P43 은 사전 없이(ctx 없음) 실행해 이름 문맥 규칙(라벨형·호칭형·멘션)만으로 잡히는지 검증한다. P56~P60 은 초판 작성 중 검증에서 찾은 '파일명 밑줄·확장자' 누출의 회귀 방지용이다. P56 의 `고객사A` 는 ctx 없이 실행하므로 남는 것이 정상이다.)

**자격증명 행 폐기 6건 (`drop`) — `drop=True` 여야 함**

| ID | 입력(합성) |
|---|---|
| X01 | `VPN 비밀번호: Abc!2345 공유` |
| X02 | `인증번호는 482910 입니다` |
| X03 | `token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijk_lmnop` |
| X04 | `api_key=sk_test_51Habcdefghijklmnop` |
| X05 | `-----BEGIN RSA PRIVATE KEY----- 첨부` |
| X06 | `pw=hunter22 로 접속` |

**오탐 미끼 50건 (`neg`) — 출력이 입력과 같고 hits 가 비어야 함**

| ID | 입력(합성) | ID | 입력(합성) |
|---|---|---|---|
| N01 | `2026-09-01 회의록 / Rev 3.2.1` | N23 | `견적서_2026Q4_rev3.xlsx 저장` |
| N02 | `부품 M12345678 도면 개정` | N24 | `M3 볼트 12 ea, M12x1.5 탭` |
| N03 | `하우징 공차 0.05 mm, 전압 12 V, 1,500 rpm` | N25 | `회의실 3층 302호` |
| N04 | `DWG-2026-0012-03 배포` | N26 | `설계 책임 검토 회의` |
| N05 | `샘플 30 ea 입고검사 결과` | N27 | `고객님 요청사항 정리` |
| N06 | `시뮬레이션 메시 1250000 셀` | N28 | `3원색 LED 색좌표 측정` |
| N07 | `PO 검토회의 14:00` | N29 | `예산 회의 2026-10-15 10:00` |
| N08 | `Reminder: 주간회의` | N30 | `견적 검토 3회차, 1,200 x 800 패널` |
| N09 | `개인정보보호 교육 이수` | N31 | `견적서 20260901 버전 송부` |
| N10 | `비밀번호 변경 안내` | N32 | `SAP 오더 4500012345 생성` |
| N11 | `password reset required` | N33 | `가격 경쟁력 분석 보고서` |
| N12 | `내구 시험 1만 회 완료` | N34 | `우리 팀 하나의 목표` |
| N13 | `카메라 1200만 화소 모듈 평가` | N35 | `좌표 37.5012, 127.0012 측정` |
| N14 | `LOT 2609011000125 입고` | N36 | `펌웨어 v1.2.3 릴리스, 빌드 2026.10.1` |
| N15 | `S/N 1234-5678-9012-3456 장비 등록` | N37 | `도면번호 110-123-456789 은행 제출용 아님` |
| N16 | `버전 10.2.3.4 배포` | N38 | `신규 개발 책임자 선정` |
| N17 | `계좌 관련 서류 정리 (문서번호 2026-0012-0034)` | N39 | `1억 화소 센서 검토` |
| N18 | `PO 4500012345 발행 요청` | N40 | `이번주 책임 회의 일정` |
| N19 | `IEC 61000-4-2 정전기 시험` | N41 | `3조 2교대 근무표` |
| N20 | `ISO 26262-6:2018 검토` | N42 | `std::vector 사용` |
| N21 | `수주 목표 3건, 견적 요청 2건` | N43 | `12:30:45 로그 확인` |
| N22 | `주파수 2.4 GHz, 5,000 mAh 배터리` | N44 | `우리팀 책임 배정` |
| N45 | `견적_DWG_202600120003.pdf` | N48 | `PRJ_A_1234-5678-9012-3456` |
| N46 | `rev_10.1.2.3_build 배포` | N49 | `model_X1_2048x1536 견적` |
| N47 | `data_2026_10_05.csv` | N50 | `도면 2026-0012-03.1 개정` |

(N14 의 13자리는 생년월일형이지만 체크섬이 맞지 않게 만든 합성 LOT 번호다. 체크섬이 우연히 맞는 값은 미끼로 쓰지 않는다.)

**광고 14건 (`ad`) — band 가 기대와 같아야 함**

| ID | 제목(합성) | 특징 | 점수 | 기대 |
|---|---|---|---|---|
| A01 | `(광고) 9월 신제품 할인 프로모션 안내` | 외부, 왕래 없음, rcv=to | 9 | drop |
| A02 | `[광고] 추석 특가 쿠폰` | 외부, 왕래 없음, rcv=to | 9 | drop |
| A03 | `Webinar invitation - unsubscribe anytime` | 외부, 왕래 없음, List-Unsubscribe | 10 | drop |
| A04 | `[협력사] 샘플 납기 회신` | 외부, 왕래 있음 | −2 | keep |
| A05 | `신제품 출시 안내` | 외부, 왕래 있음, rcv=bulk, List-Unsubscribe | 5 | drop |
| A06 | `RE: 시험 결과 공유` | 사내 | −3 | keep |
| A07 | `사내 뉴스레터 10월호` | 사내, rcv=bulk | 0 | keep |
| A08 | `귀사에 맞는 솔루션 소개드립니다` | 외부, 왕래 없음, 헤더 없음 | 3 | suspect |
| A09 | `FW: (광고) 전시회 무료 초청` | 사내 전달 | 9 | drop |
| A10 | `견적 요청 회신` | 외부, 왕래 없음, 내 발신 대화 | −1 | keep |
| A11 | `월간 기술 소식` | 외부, 왕래 없음, bulk, Precedence·ESP, 본문 수신거부 | 11 | drop |
| A12 | `학회 등록 확인` | 외부, List-Unsubscribe, 사용자 허용 | 0 | keep |
| A13 | `업무 협의 요청` | 사용자 차단 | 9 | drop |
| A14 | `정기 점검 안내` | 외부, 왕래·협력사, List-Unsubscribe | 2 | keep |

**공사 구분 14건 (`priv`) — class 가 기대와 같아야 함**

| ID | 본문(합성) | 조건 | 점수 | 기대 |
|---|---|---|---|---|
| Q01 | `점심 뭐 먹을래요? 오늘 퇴근하고 한잔?` | 1:1 | 4 | private |
| Q02 | `주말에 가족이랑 여행 가요 ㅋㅋ` | 1:1, 표준창 밖 | 8 | private |
| Q03 | `도면 검토 부탁드립니다. 점심 전까지요` | 1:1 | −4 | work |
| Q04 | `[과제:P0001] 샘플 시험 결과 공유드립니다` | group | −11 | work |
| Q05 | `저녁 회식 장소 투표해 주세요` | group | 2 | social |
| Q06 | `넵 알겠습니다` | 1:1 | −1 | work |
| Q07 | `ㅋㅋ 그거 대박` | 1:1, 표준창 밖 | 4 | private |
| Q08 | `택배 왔어요?` | 1:1, 방 성향 사적 | 5 | private |
| Q09 | `내일 점심 회식 대신 팀 미팅으로 변경합니다` | group | 0 | work |
| Q10 | `병원 예약 때문에 오후 반차` | 1:1 | 3 | private (abs_hint=half_pm 은 남김) |
| Q11 | `정기 검진 일정` | 민감도 2 | 9 | private |
| Q12 | `주간 보고 자료 첨부` | channel | −7 | work |
| Q13 | `자료 보냈어` | 개인 메일 상대 | 1 | work |
| Q14 | `오랜만이야 주말에 볼까` | 개인 메일 상대 | 4 | private |

**게이트 8건 (`gate`) — 문맥: 고객사 C01(`고객사A`), 사람 사전 `김철수`**

| ID | 항목 텍스트(합성) | 카나리아 | 기대 |
|---|---|---|---|
| G01 | `회의 후 010-1234-5678 로 연락` | - | 제외 `pii:phone` |
| G02 | `견적 [금액] 검토 요청` | - | 통과, 변화 없음 |
| G03 | `고객사A 미팅 결과 공유` | - | 통과 `[고객사:C01] 미팅 결과 공유`, `remask:customer=1` |
| G04 | `[사람#a1b2c3] 책임 검토 요청` | - | 통과 `[사람] 책임 검토 요청` |
| G05 | `DESKTOP-AB12CD 에서 저장` | `DESKTOP-AB12CD` | 제외 `pii:canary` |
| G06 | `kim 님 자료` | `kim` | 통과(4자 미만 카나리아 무시) |
| G07 | `hong.gildong 폴더 정리` | `hong.gildong` | 제외 `pii:canary` |
| G08 | `초기 비밀번호: Temp#2026 안내` | - | 제외 `pii:cred` |

**팀 라벨 6건 (`label`)**

| 라벨 | 기대 위반 |
|---|---|
| `도면 검토` | 없음 |
| `견적 [금액] 회신` | 없음 |
| `[과제:P0001] 시험` | 없음 |
| `김철수 책임 보고` | `not_clean` |
| `결과 12345678 정리` | `forbidden_pattern` |
| `[사람#a1b2c3] 협의` | `forbidden_pattern` |

**LM27 추가 시험 22건 (`ext`) — scan·tokens_of·doc_norm·키 동치 (v1.1 신규 코드용, §19 T25~T28)**

| ID | 호출(합성) | 기대 |
|---|---|---|
| S01 | `scan("제 번호 010-1234-5678 로 연락주세요")` | `[Hit("phone", 1)]` |
| S02 | `scan("견적 [금액] 검토 요청")` | `[]` |
| S03 | `scan("pw=hunter22 로 접속")` | `[Hit("cred", 1)]` |
| S04 | `scan("하우징 공차 0.05 mm, 전압 12 V, 1,500 rpm")` | `[]` |
| S05 | `scan("국민은행 123456-01-234567 예금주 홍길동")` | `[Hit("account", 1), Hit("person", 1)]` |
| S06 | `scan(sanitize(P01~P60 각 입력).text)` 60건 | 전부 `[]` (멱등의 다른 표현) |
| K01 | `tokens_of("RE: [과제:P-0001] 샘플 시험 결과 [전화]")` | `["RE", "[과제:P-0001]", "샘플", "시험", "결과", "[전화]"]` |
| K02 | `tokens_of("")` | `[]` |
| K03 | `tokens_of("가 " * 40)` | 길이 30 |
| K04 | `tokens_of("견적_[전화].xlsx")` | `["견적_", "[전화]", "xlsx"]` |
| D01 | `doc_norm("과제A_열해석_v3.wbpj")` | `"과제a_열해석"` |
| D02 | `doc_norm("보고서_최종.pptx")` | `"보고서"` |
| D03 | `doc_norm("보고서 - 복사본.pptx")` | `"보고서"` |
| D04 | `doc_norm("보고서 (1).pptx")` | `"보고서"` |
| D05 | `doc_norm("주간보고_20261005.xlsx")` | `"주간보고_20261005"` |
| D06 | `doc_norm("v2.docx")` | `"v2"` |
| D07 | `doc_norm("C:\\Users\\hong\\Documents\\2026 사업계획 v2 최종.pptx")` | `"2026_사업계획"` |
| D08 | `doc_norm("photocopy.pdf")` | `"photocopy"` (구분자 없는 `copy` 는 꼬리 아님) |
| E01 | 주 키 `b"\x01"*32` 의 `Keyring` 과 `AgentKeys(subkeys={p: subkey(주 키, p) for p in AGENT_PURPOSES})` 로 `who_key("smtp:user01@corp.example")` | 두 값 같음 |
| E02 | 같은 두 키로 `doc_key("보고서_v3.pptx")` 와 `doc_key("보고서_최종.docx")` | 네 값 모두 같음 |
| E03 | 같은 주 키로 `sanitize("김철수 책임님께 보고드립니다", ctx=SanitizeContext(key=주 키))` 와 `ctx=SanitizeContext(person_subkey=subkey(주 키, "person"))` | 두 출력 같음 |
| E04 | `AgentKeys` 로 `keyed(ak, "repo", "x")` | `NoKeyError` |

### 18.3 관문 — `run_selftest()` 실패 조건

| 관문 | 조건 |
|---|---|
| 규칙 고정 | `RULES_HASH == rules.lock.json.rules_hash` 이고 `RULES_VERSION == lock.rules_ver` |
| 양성 | 60건 전부 `text == expect`(사람 태그 `#*` 정규화 후), `hits == 기대`, `drop == False` |
| 멱등 | 양성 60건 전부 `sanitize(out).text == out` 이고 `hits == {}` |
| 폐기 | 6건 전부 `drop == True` |
| 미끼 | 50건 전부 출력 = 입력(공백 정규화 후), `hits == {}` |
| 광고·사적 | 28건 band·class 일치 |
| 게이트·라벨 | 14건 기대 일치 |
| 추가(ext) | 22건 기대 일치 |
| 최소 규모 | 양성 ≥30, 미끼 ≥20 (말뭉치를 줄이는 변경 차단) |
| 성능 | 양성·미끼 전체를 섞어 이어 붙인 20,000행 처리 ≤ 5초, 병적 입력 12종 각각 ≤ 50ms (§19 T18) |
| 템플릿 | 코파일럿 프롬프트 템플릿 상수 전부 `scan()` 빈 목록 |
| 스키마 | `SCHEMAS` 의 모든 열이 §10.1·§10.2 표와 1:1(열 이름 집합 비교 — 표는 `schemas_v1.json` 으로 함께 배포), 텍스트 열은 모두 `text_fields` 에 있음 |
| 감사 형식 | 마지막 실행의 감사 기록이 §15.2 키·값 형식만 가짐 |

selftest 는 lint 관문(`tools\lint.ps1`)·에이전트 설치(§3.6)·패키징 직전에 실행한다. 실패하면 패키지를 만들지 않고, 에이전트는 설치를 거부한다.

---

## 19. 시험 시나리오

단위 시험은 `tests\privacy\`, 통합·E2E 는 합성 페르소나(홍길동, 과제A, 고객사A)로 한다. 모든 입력은 합성.

| ID | 시나리오 | 절차 | 기대 |
|---|---|---|---|
| T1 | 회귀 말뭉치 | `run_selftest()` | 0 반환 |
| T2 | 규칙 무단 변경 | `RX["mobile"]` 한 글자 수정 후 selftest | "규칙 고정" 실패 |
| T3 | 위험한 허용 패턴 | `privacy.allow_patterns=["\\d+"]` 로 `build_context()` | 거부 `cfg.allow_too_broad`, 정제 결과 불변 |
| T4 | PS 파이프 정상 | 합성 메일 200건(말뭉치 양성 문장을 제목·본문에 섞음)을 §3.5 골격으로 파이프 | 출력 1개, 열은 §10 허용 목록만, 출력 전체 텍스트에 말뭉치 양성 **원값**(번호·주소·이름) 0건 |
| T5 | PS 파이프 중단 | 100번째 줄 뒤 파이썬 프로세스 강제 종료 | 출력 없음(new 모드)·멤버 미추가(append 모드), 원문 파일 없음, 수집 상태 '정제기 실패', 다음 주기 재수집 |
| T6 | 단일 관문 우회 | 수집기 코드에서 `SegmentWriter.append(dict)`, `from lm27.privacy.detect import sanitize` | `TypeError`; lint 가 쓰기 모드 `open(` 과 우회 import 를 잡음 |
| T7 | 멀티 PC 키 | PC1(에이전트 A)에서 설치·키 생성 → 폴더 복사 → PC2(에이전트 B, 하위 키 없음) 설치 | PC2 하위 키 kid = 폴더 키 kid, 같은 주소의 who_key·같은 메일의 msg_key 동일 |
| T8 | 키 충돌 | 서로 다른 압축 해제본으로 PC1·PC2 설치(키 2개) 후 번들 병합, 같은 메일을 양쪽에서 수집 | 주 키 = 더 이른 키, `key.conflict=1`, 별칭 표 생성, 병합 후 그 메일 1건(`merge.fuzzy` ≥1), 다음 [수집] 후 PC2 에이전트 하위 키 kid = 주 키 |
| T9 | 방 성향 소급 | 1:1 방 12건 중 9건 사적 → 클라우드PC 적재 | 그 방 행 `priv_class=private`(강한 업무 행 제외), 코파일럿 항목·보고서에 본문 없음, 자기 pc_id 세그먼트 `redact_rewrite` 후 디스크에도 없음, 다른 pc_id 세그먼트는 디스크 불변·읽기 오버레이 적용 |
| T10 | 표준창 밖 사적 | 평일 22:00~23:30 KakaoTalk 전경만, 23:40 업무 메일 발신 | 22:00~23:30 봉투 제외, 23:40 앵커 + pad 만 인정 |
| T11 | 정규 시간대 사적 | 14:00~14:20 쇼핑 사이트, 15:00~15:40 게임 | 14:00~14:20 중립(봉투 유지), 15:00~15:40 봉투 제외 |
| T12 | 개인 일정 | 13:00~15:00 민감도 2 일정, 그 사이 업무 문서 저장 없음 | 슬롯 '개인 부재', 제목 저장 안 됨 |
| T13 | 광고 경로 차이 | 같은 합성 광고를 COM(헤더 있음)·색인(헤더 없음)으로 수집 | COM: drop. 색인: 점수 재계산·`ad_partial=true`. 감사 `ad.partial` 증가 |
| T14 | 광고 의심 큐 | A08 류 메일 → 사용자 [차단] | 다음 수집부터 같은 도메인 drop(`user_block`) |
| T15 | 게이트 잔여 PII | 옛 규칙 버전 행에 말뭉치 양성 원문 주입 → `gate_copilot` | HIGH 범주 항목 제외, MEDIUM 재가림 통과, 감사엔 건수만 |
| T16 | 최종 프롬프트 검사 | 템플릿에 `010-0000-0000` 을 일부러 넣은 시험 단계 | `gate_blocked`, 전송 0 |
| T17 | 팀 페이로드 위반 | 페이로드에 who_key·이메일·경로·9자리 숫자·MachineGuid·모르는 키 주입 | 업로드 안 함, 위반 경로·코드 목록(값 없음) |
| T18 | 성능 | 20,000행·병적 입력 12종(`"1,"×8000`, `"@"×10000`, `"-"×10000`, `"가"×10000`, `"[" ×5000`, 긴 URL, 긴 경로, `"0"×4000`, 전각 숫자 4000자, 이모지 4000자, 제어문자 4000자, 토큰 2000개) | ≤5초 / 각 ≤50ms |
| T19 | 카나리아 E2E | 합성 페르소나 한 달치(메일·팀즈·창·파일)에 말뭉치 양성 전부를 심고 PC1→PC2→클라우드→코파일럿(가상 시계 시뮬)→팀 업로드 | 모든 프롬프트 문자열·팀 페이로드에 카나리아 원값 0건, `scan()` 재실행 0건 (결정 메모 §9 'PII 카나리아' 관문) |
| T20 | 감사 원문 금지 | T19 후 모든 `privacy_audit` 기록 검사 | 허용 키만, 9자리 이상 숫자열·`@`·한글 문장 없음 |
| T21 | 절단 | 300자 넘는 팀즈 본문 끝에 토큰이 걸리게 구성 | 출력 ≤300자, 반쪽 토큰 없음 |
| T22 | 전각 입력 | `０１０－１２３４－５６７８` | `[전화]` |
| T23 | 규칙 상향 재정제 | v 낮은 행(새 탐지기 대상 값 포함) 적재 | 메모리 사본에서 가려짐, 디스크는 자기 pc_id 만 재작성 |
| T24 | 기본 설정 린트 | `config.default.json` 에 `privacy.customers` 항목 1개 추가 | 패키징 실패 |
| T25 | scan | 말뭉치 S01~S06 | 기대 일치 |
| T26 | tokens_of | 말뭉치 K01~K04 | 기대 일치 |
| T27 | doc_norm·문서 연결 | 말뭉치 D01~D08 + 같은 문서를 창(Excel 제목)·파일(mtime)·발신 메일 첨부로 관측 | 세 doc_key 가 같고 '작성 완료 → 메일 보고' 후보가 생김 |
| T28 | 에이전트 하위 키 동치 | 말뭉치 E01~E04 | 기대 일치 |
| T29 | 키 없음 모드 | 에이전트 `subkeys.json` 삭제 후 샘플러·teams.uia 플러시 | 파이프 rc 6, 샘플러 행 저장(`doc_key=null`, `flags.no_key`), teams.uia 행 `dropped.no_key`, 저장 텍스트에 `[사람#` 0건, heartbeat `R-NOKEY`. 다음 [수집] 후 정상 |
| T30 | 열 검증(I12) | 원시 `session_state` 에 `"홍길동 PC"`, `app_id` 에 공백 포함 문자열 주입 | 그 행 `error(ColumnViolation)` 또는 `bad_raw`, 저장 0, 감사에 열 이름만 |
| T31 | 금지 원시 필드 | `pc.events` 원시에 `user`·`message` 필드 포함 | `bad_raw` |
| T32 | peer_key | 사내 주소·외부 주소, pepper 있음/없음, 두 팀원 PC | 외부 → None, pepper 있음 → `team` 이고 두 PC 같은 값, 없음 → `personal` |
| T33 | route-by-kind | COM 혼합 stdout(mail·cal 섞임) → `--route-by-kind --out "...\{kind}\..."` | 출력 2개, kind 별 열만. `{kind}` 없으면 rc 5 |
| T34 | 에이전트 정제기 동일성 | 에이전트 bin 의 `rules.py` 한 글자 바꾼 사본으로 샘플러 기동 | 수집 중지, heartbeat `R-RULESMISMATCH`, 다음 [수집]이 사본 교체 후 재개 |
| T35 | 감사 세그먼트 | 클라우드PC 게이트 실행 후 번들 확인 | 클라우드PC pc_id 아래 `privacy_audit` 세그먼트 1개 추가, 다른 pc_id 폴더 바이트 불변 |
| T36 | 0 바이트 키 누출 | `make_record_context()` 를 키 없이 만들고 사람 이름 든 제목 정제 | 저장 행에 `[사람#` 0건(`[사람]` 으로 강등) |

---

## 20. 예외 처리 총괄

| 상황 | 처리 | 감사·상태 |
|---|---|---|
| `sanitize()` 내부 예외 | 그 행 `error` — 저장 안 함 | `err.<예외타입>` |
| 알 수 없는 kind | `ValueError` → 수집기 중단 | 수집 상태 '정제기 설정 오류' |
| raw 필수 필드 누락·형식 오류·금지 원시 필드 | 그 행 `dropped(bad_raw)` | `dropped.bad_raw` |
| 저장 열 검증 실패(I12) | 그 행 `error(ColumnViolation)` | `err.column:<열>` |
| 자격증명 탐지 | 행 폐기 | `dropped.cred` / `masked` 에는 안 셈 |
| 삭제 편지함 행 | 행 폐기 | `dropped.folder_excluded` |
| 정제기 프로세스(파이프) 비정상 종료 | 출력 미기록, 원문 대체 저장 금지 | 수집 상태 '정제기 실패' |
| 파이프 인자 오류 | rc 5, 출력 미기록 | 수집 상태 '정제기 호출 오류' |
| 키링 파일 손상 | 자기 파일 `.corrupt-<시각>` 로 옮기고, 키가 하나도 없으면 [수집]이 새로 생성 | `key.corrupt`, `key.created` |
| 키링 쓰기 불가(읽기 전용) | 메모리 키링으로 진행, 쓰기는 다음 기회 | `key.bundle_readonly` |
| 키 충돌 | 주 키 선정·별칭 재매핑·보조 키 병합 | `key.conflict`, `merge.fuzzy`, `merge.doclink_lost` |
| 에이전트 하위 키 없음·손상 | 키 없음 모드(§9.4), 파이프 rc 6 | `dropped.no_key`, heartbeat `R-NOKEY` |
| 에이전트가 받지 않은 용도의 키 요구 | `NoKeyError` → 키 필수 kind 는 `no_key` 폐기, 선택 kind 는 null + `flags.no_key` | `dropped.no_key` |
| 에이전트 정제기 사본 해시 불일치 | 수집 중지(축약 정제로 계속하지 않음) | heartbeat `R-RULESMISMATCH` |
| append 모드 출력의 잘린 마지막 멤버 | 읽는 쪽이 그 멤버만 버림 | `err.truncated_tail` |
| 설정 정규식 오류·과대 허용 | 그 항목 무시 | `cfg.bad_regex`, `cfg.allow_too_broad` |
| 사전 별칭이 너무 짧음·일반어 | 그 별칭 무시 | `cfg.short_alias`, `cfg.generic_alias` |
| 게이트 허용 밖 필드 | 단계 중단(전송 0) | `err.GateSpecError` |
| 최종 프롬프트 재탐지 | 배치 미전송 | `gate_blocked` |
| 팀 페이로드 위반 | 업로드 중단 | `gate_team.violations` |
| 감사 기록 실패 | 수집은 계속하되 다음 실행에서 누락 구간을 '감사 결손'으로 표시 | 수집 상태 경고 |
| 규칙 lock 불일치(배포본) | 실행은 하되 정제 결과를 '검증 안 된 규칙'으로 표시하고 팀 업로드 금지 | `selftest.lock_mismatch` |

---

## 21. 미결 사항

| ID | 질문 | 현재 기본 결정 | 결정 필요 주체 |
|---|---|---|---|
| Q1 | 새 Outlook·OWA·색인 경로에서 발신 SMTP·List-Unsubscribe 헤더를 얻을 방법 | 제목·도메인·광고어만으로 판정, `ad_partial` 비율을 보고서에 신뢰도로 표시 | 메일 수집 명세(실측) |
| Q2 | Focused Inbox '기타' 분류를 COM 으로 안정적으로 읽을 수 있는가(Outlook 버전별 속성) | 못 읽으면 `focused_other=null`, 점수 0 | 메일 수집 명세(실측) |
| Q3 | 수주 금액 외 수량·납기·단가율도 고객 기밀인가 | v1 은 금액·단가·할인/마진율만 가림 | 사용자·팀장 |
| Q4 | 회식·경조사·동호회를 '사적 삭제'로 볼지 '공통업무(팀 운영)'로 볼지 | `social` 로 내용 삭제 + 시간 근거 제외, 건수만 별도 집계 | 사용자 |
| Q5 | 비공개 일정을 부재 블록으로 쓸지 완전히 버릴지 | 정규 시간대 '개인 부재' 블록으로 봉투에서 제외(R-P5) | 사용자 |
| Q6 | 사내 M365 테넌트 코파일럿을 사내 경계로 보는가(마스킹 수준 완화 여부) | 완화 없음 — 고위험 잔여 PII 행 제외, 사람은 `[사람]` 평문 토큰 | 정보보안 정책 |
| Q7 | 여권번호 첫 글자 집합(M·S·R·O·D·G)과 2021년 이후 신형 형식(4번째 자리 영문)의 공식 규격 확인 | 두 형식 모두 + 문맥 게이트 | 공식 자료 확인 |
| Q8 | 사전·문맥 없는 이름(예: 문장 중간 `홍길동 내일 와요`) 처리 | 놓침(비목표). 로컬 사람 사전이 커질수록 줄어듦. 필요하면 다음 규칙 판에서 '성+2자 + 동사 문맥' 규칙 실험 | 설계 패널 |
| Q9 | `person_dir.json`·에이전트 `context_cache.json`(이름 목록) 의 보호 | 평문(키링과 같은 폴더라 암호화 실익 없음). `data\`·`%LOCALAPPDATA%\LoadMonitor27\` 전체가 보호 대상이라고 안내 | 사용자·정보보안 |
| Q10 | 팀 묶음 `peers[].peer_key`(팀 pepper)의 공개 범위 — pepper 를 아는 팀원은 사내 주소 대입으로 관계를 되짚을 수 있음 | 허용(H10). 팀 서버 `read_requires_token` 기본값과 함께 팀 합의 필요 | 사용자·팀장 |
| Q11 | 개인 브라우저 프로필 방문 시각을 PC 가동 힌트로 쓸지 | 업무 프로필만(프로필 이름 판정은 창 제목 기반) | PC 수집 명세 |
| Q12 | 레지스트리 키 이름(`registry.customers` 등)과 팀 묶음 필드의 최종 이름 | §14.5 표를 기본안으로, 팀/번들 명세와 같은 커밋에서 맞춤 | 레지스트리·팀/번들 명세 |
| Q13 | 소급 가림 재작성(§12.5)을 '불변 세그먼트' 원칙의 예외로 받아들이는가(세그먼트 교체 + manifest `supersedes`) | 텍스트 열만 비우는 자기 pc_id 재작성만 허용 | 팀/번들 명세 |
| Q14 | 결정 메모 10.4 '키는 번들에 넣지 않는다'와 과제 지시 '키는 PC 간 이동'의 해석 | 키링 = 프로그램 폴더 `data\keys\`(폴더째 이동, manifest·세그먼트·팀 묶음 밖), 에이전트 = 하위 키만(H6) | 오케스트레이터 |
| Q15 | 형제 명세의 LM27 반영: H1~H15(kind·열 이름·키 형식·pc_id 접두·doc_key HMAC·파이프 인자·감사 스트림·에이전트 정제기) | 이 문서가 정본. 각 명세를 LM27 판으로 옮길 때 같은 커밋에서 반영 | 수집 공통·메일·팀즈·PC·팀/번들·브리지 명세 |
| Q16 | `act_cues` 추출 규칙(어휘·정규식) | 열과 닫힌 어휘만 이 문서가 정함. 추출기 `lm27.normalize.cues` 는 시간·분류 명세 소유 | 시간·분류 명세 |
| Q17 | 팀/번들 명세 R-1 의 짧은 이름 `t`·`off`·`k` vs 공통 봉투 `ts_utc`·`ts_local_offset`·`msg_key` | 저장은 공통 봉투 이름. 짧은 이름이 필요하면 단일 로더가 변환 | 팀/번들·수집 공통 명세 |
| Q18 | 팀 묶음에 `privacy_counts`(범주별 건수)·`catalog_proposals` 필드 추가 | 이 문서는 요구, 필드 소유는 팀/번들 명세 | 팀/번들 명세 |
| Q19 | 에이전트 bin 에 동봉 파이썬·정제기 사본(PC 당 약 10~15 MB)을 두는 것 | 둔다(H15 — 폴더가 떠난 PC 에서도 단일 관문 유지) | 사용자 |
| Q20 | `doc_norm` 꼬리 규칙(최종·v3·복사본 제거, 날짜 유지)이 실제 문서명 관례에 맞는가, 바꿀 때 `KEYS_VERSION` 운용 | 합성 예 D01~D08 기준. 실사용 문서명 분포(이름은 보지 않고 꼬리 유형 건수만)로 보정 | PC 수집 명세(실측) |
| Q21 | v1.1 의 신규·변경 코드(§3.2 `as_pair`, §6 `person_subkey`, §6.2 `scan`·`tokens_of`, §9.3 키, §9.7 `peer_key`, §10.3)와 말뭉치 `ext` 22건은 이관 작업 세션에서 실행 검증하지 못했다(실행 도구가 막힘) | `design\privacy_lm27\verify_doc_lm27.py` 를 실행해 초판 말뭉치 150건 + ext 22건 + 게이트·라벨·창 분류가 통과하는지 확인한 뒤 확정 | 오케스트레이터(다음 세션) |

---

## 부록 A. LM24 대비 변경 요약

| LM24 v4 | LM27 |
|---|---|
| 원문 수집 → 원문 저장 → 키워드 필터 → 코파일럿이 광고·사적 'n' 판정(사후) | 수집기 메모리에서 정제 → 허용 열만 저장 → 코파일럿 전 재검사(사전) |
| PII 정규식·체크섬·금액 마스킹 0건 (합성 18건 중 16건 통과) | 한국형 탐지기 + 체크섬 + 문맥·억제 (양성 60/60, 미끼 50/50) |
| `excludePathKeywords` 를 텍스트 '개인정보필터'로 사용('개인정보보호 교육' 삭제) | 경로 제외 전용으로 축소(§10.4), 텍스트는 값만 토큰화 |
| `noticeSenders` 에 '(광고)'·'수신거부' 를 넣고 발신자 이름에만 대조 | 제목 표기·헤더·도메인·왕래·광고어 점수(§11) |
| 회신한 발신자 영구 면제 | 왕래는 감점(−3)만, (광고) 표기는 무조건 확정 |
| 창 샘플러 개인 앱 사용이 야간·주말 초과근무로 계상 | 비업무 앱·사이트·InPrivate 판정 + 시간 근거 제외 규칙(R-P1~R-P9) |
| `who` 열만 가리고 본문 속 이름은 그대로 | 사전 + 멘션·라벨·호칭 규칙으로 본문 속 이름도 가명 토큰 |
| 대화 키 = 제목 SHA1(사전 공격 가능), 중복 키 = 정제 후 텍스트 | 키 기반 HMAC, 중복 키는 정제 **전** 원문으로 |
| signals 원문(제목 100자 + 표시명)을 팀 서버로 업로드 | 집계·라벨·값 클래스 검사만(§14), 서버 재검증 |
| 실패 프롬프트 파일·팀즈 화면 원문 덤프가 디스크에 남음 | 원문 디버그 저장 기능 자체 없음, 게이트 통과 프롬프트만 TTL |
| 매분 창 제목 원문·USERNAME·COMPUTERNAME 기록 | 허용 앱만 정제 제목, 사용자명·컴퓨터명 열 없음(금지 원시 필드) |

## 부록 B. 근거·시제품·검증 상태

- **초판 검증(LM26 이름, 같은 규칙)**: `%TEMP%\claude\…\scratchpad\lm26_survey\design\privacy\lm26_privacy_v1.py`(이 문서 §5~§6·§11~§14 코드의 원본), `make_corpus.py`(말뭉치 생성 → `corpus_v1.jsonl`), `run_corpus.py`(관문 실행) — 결과 `{'pos': 60, 'drop': 6, 'neg': 50, 'ad': 14, 'priv': 14, 'idem': 60} FAIL 0`, 문서 코드 블록을 추출·조립한 `verify_doc.py` 도 같은 결과(게이트·라벨·창 분류 포함).
- **성능 실측(초판)**: 20,000행(평균 113자) 1.90초, 병적 입력 최대 4.8ms(반복 상한 적용 후; 적용 전 `"1,"×8000` 2.09초).
- **LM27 이관 검증**: `scratchpad\lm26_survey\design\privacy_lm27\verify_doc_lm27.py` — 이 문서(`D:\배포\loadmon27\docs\PRIVACY.md`)의 코드 블록을 추출·조립해 초판 말뭉치 `corpus_v1.jsonl` 150건 + 게이트 8건 + 라벨 6건 + 창 분류 9건 + ext 22건(§18.2)을 실행한다. 이관 세션에서는 실행 도구가 막혀 **아직 실행하지 못했다**(§21 Q21). 탐지·판정 코드 블록은 초판과 같은 바이트(경로 주석·HMAC 접두·`person_subkey` 만 다름)이므로 초판 결과가 그대로 성립할 것으로 보지만, 확정은 실행 후.
- **이전 판 조사**: `scratchpad\lm26_survey\privacy.md`(LM24 v4 현행 필터 분석·합성 프로브 16/18 생존), `filter\sanitize_proto.py`(양성 17/17·미끼 7/7), `filter\classify_proto.py`(광고·사적 점수 초안).
- **정합 근거(읽기 전용으로 대조한 형제 명세 초판)**: `D:\배포\loadmon26\docs\COLLECTION.md`(§2 경로 ID·§3 공통 스키마·§11 정제 계약), `COLLECT_MAIL.md`(§3 원시 후보 레코드·§16 미결 1·2·6), `COLLECT_PC.md`(§3·§5·§13.3 kind 매핑 미결), `TEAM_AND_BUNDLE.md`(§0.4 R-1·R-6, §1.1 배치, §1.2 식별자, §2.3 팀 묶음·가명 키), `COPILOT_BRIDGE.md`(게이트 호출부).

