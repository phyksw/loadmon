# LM27 업무시간·단위업무 추론 방법론 (WORKTIME_METHOD.md)

| 항목 | 값 |
|---|---|
| 판 | v1.0 (2026-10-05) — 설계 확정본, 구현 전 |
| 제품명 | **LoadMonitor27(LM27)**. 초기 설계 자료의 'LM26' 표기는 잘못 붙은 이름이다. `D:\배포\LM26` 은 다른 AI 도구가 만든 별개 프로젝트이며 이 문서와 무관하다(읽기만). 이 문서의 모듈·경로·설정 키는 LM27 기준이다 |
| 대상 코드 | `lm27/time/**`(시간 코어), `tools/calibrate.py`(파라미터 보정 도구), `tests/time/**`(관문) |
| 소유 범위 | 근무 봉투(하루 몇 시간 일했나) · 단위업무(무슨 일을 언제 시작·종료했나) · 슬롯 귀속(그 시간이 어느 일에 쓰였나) · MM·초과 · 신뢰도 등급·확인 큐·설명 원장. 업무 영역·과제·역할 업무·업무 유형 **분류**는 분류 명세가 소유하고, 이 문서는 분류 라벨을 받아 MM 을 굴려 올리기만 한다 |
| 상위 결정 | 오케스트레이터 결정 메모 §5(시간 모델 원칙)·§9(품질)·§10.2(시간 모델 보강)·§10.3(시간대·달력) |
| 근거 | 심사 결과(골격 = 관점 A '보수적 증거 원장', B·C 접목, must_fix 15건, extra 시나리오), 설계안 A·B·C, 이전 판 조사 `time-mm.md`(LM24 K1~K16·R1~R14·V1~V30), `lessons.md` |
| 형제 명세 계약 | `PRIVACY.md` v1.1 §12.7(시간 근거 규칙 R-P1~R-P9 — 이 문서가 구현한다), `COLLECTION.md` §3(공통 증거 레코드)·§5(커버리지 원장), `COLLECT_PC.md` §3(샘플러)·§5(문서 증거)·§7(작성 완료 증거)·§13(증거 층), `TEAM_AND_BUNDLE.md` §0.4 R-2~R-5(꼬리표 배타·정수 분 표·unit_id 안정·1MM 분모)·§2.3(팀 묶음) |
| 참조 구현 | `scratchpad\lm26_survey\design\worktime_sim.py`(엔진, 표준 라이브러리만) · `design\worktime\scenarios.py`(§9 시나리오 83개 + 골든 `golden.json`) · `design\worktime\gates.py`(§10 관문). 이 문서의 수치는 모두 이 참조 구현으로 계산했다(scratchpad 의 `lm26_survey` 는 작업 당시 임시 폴더 이름일 뿐 제품명과 무관) |
| 런타임 | 동봉 CPython 3.11 embeddable, **표준 라이브러리만**. `zoneinfo.ZoneInfo` 사용 금지(관문). 수집은 Windows PowerShell 5.1(이 문서 범위 밖) |
| 자리표시자 | 홍길동·김철수(사람), 과제A~J, 고객사A, P1~P40(상대 가명 키). 실명·계정·이메일·사내 코드네임 없음 |

---

## 0. 요약 — 이 도구가 내 업무시간을 어떻게 재는가 (사용자용 한 페이지)

**한 줄로**: LM27 은 PC·메일·팀즈·일정에 남은 흔적으로 ① 하루에 몇 시간 일했는지를 먼저 재고, ② 그 시간을 내가 한 일(단위 업무)에 나눠 담습니다. 나눠 담기만 하므로, 여러 일을 동시에 진행해도 총시간이 부풀지 않습니다.

1. **시간은 5분 칸으로 잽니다.** 하루를 5분짜리 칸 288개로 보고, 그 칸에 '일한 흔적'이 절반(2분 30초) 이상 있으면 근무로 칩니다. 흔적은 PC 에서 업무 프로그램을 쓰던 기록, 문서 저장, 메일·팀즈 발신, 수락한 회의, 직접 적어 넣은 업무 기록입니다. 여러 PC 를 함께 써도 같은 칸은 한 번만 셉니다.
2. **흔적이 없으면 시간을 만들지 않습니다.** "PC 가 켜져 있었다"나 "평일이니 8시간"만으로는 시간을 주지 않습니다. 다만 근무시간(기본 09~18시) 안에서 PC 가 켜져 있고 그날 실제 작업 흔적이 있으면, 기록이 빈 부분을 '낮은 신뢰'로 채웁니다.
3. **퇴근 후·주말은 실제 산출물이 있을 때만** 셉니다. 저녁에 문서를 저장했거나 메일을 보냈거나 업무 프로그램을 15분 넘게 썼다면 그 앞뒤 30분 범위만 인정합니다. 저녁 내내 인터넷만 봤다면 세지 않습니다. 늦게 시작해 새벽에 보고 메일을 보낸 경우는 작업이 이어진 만큼 연속으로 인정합니다. PC 없이 휴대폰으로 보낸 메일도 20분(팀즈 10분)을 인정하고 확인 질문을 띄웁니다.
4. **개인적인 사용은 뺍니다.** 쇼핑·메신저·시크릿 창처럼 사적으로 판정된 화면 사용은 근무시간에서 30분 이상 이어지면 빼고, 퇴근 후에는 항상 뺍니다. 뺀 시간은 설명 원장에 숫자로 남습니다.
5. **단위 업무는 '의뢰 → 작업 → 보고'로 묶습니다.** 메일·팀즈로 받은 의뢰, 그 일의 문서·프로그램 작업, 보고 메일(첨부)을 같은 대화방·같은 첨부 파일·제목 낱말로 잇습니다. 말로 받은 지시처럼 디지털 흔적이 없는 시작·종료는 '첫 작업 30분 전', '마지막 작업 30분 후 + 5근무일 조용함', '의뢰자가 연 검토 회의' 같은 규칙으로 추정하고, 추정했다는 사실을 등급으로 보여 줍니다.
6. **등급**: A = 의뢰와 보고가 모두 디지털로 정확히 남음, B = 한쪽이 완료 파일·날짜만·본인 확인, C = 한쪽이 추정, D = 끝이 '조용해진 시점' 추정, E = 둘 다 추정. C·D·E 는 '확인 질문'으로 물어보고, 답하면 등급이 올라갑니다(답은 업무 번호가 아니라 메일·문서 키로 저장되어 다시 분석해도 유지됩니다).
7. **두 가지 시간을 따로 보여 줍니다.** '리드타임'(의뢰부터 보고까지 걸린 날짜·시간)과 '투입'(내가 실제로 그 일에 쓴 시간)은 다릅니다. 간트 막대의 길이는 리드타임이고, 투입은 막대 안의 진한 칸과 숫자로 따로 보여 줍니다.
8. **MM**: 1MM = 하루 8시간 × 그 달 근무일(주말·공휴일 제외). 2026년 9월·10월은 각각 근무일 20일이라 1MM = 160시간입니다. 초과근무로 1MM 을 넘을 수 있고 잘라내지 않습니다. 근무시간 밖은 '연장', 22시~06시는 '야간', 주말·공휴일은 '휴일'로 따로 집계합니다.
9. **어느 일에도 묶이지 않은 근무시간**은 숨기지 않고 '근무 중 미분류'(일반 앱·소통·회의·PC 밖·미상 다섯 갈래)로 보여 줍니다. 근거 없이 아무 일에나 나눠 주지 않습니다.
10. **못 하는 것**: 디지털 흔적이 전혀 없는 대면 지시·대면 보고·현장 업무는 확인 질문이나 직접 기록으로만 반영됩니다. 휴대폰으로 읽기만 한 시간, 일정에 없는 즉석 회의는 대부분 잡히지 않습니다. 수치(30분·5근무일 등)는 아직 실제 자료로 보정하기 전 값이며, 직접 기록을 정답으로 삼아 보정하는 도구(§8.3)를 둡니다.

---

## 1. 용어

### 1.1 업무 계층(분류 명세가 라벨을 붙이고, 이 문서는 MM 을 굴려 올린다)

| 용어 | 뜻 | 이 문서에서의 역할 |
|---|---|---|
| **업무 영역** | 큰 업무. 고정 5종 + 미분류: 개발 프로젝트 / 양산 프로젝트 / 외부 업무지원 / 공통 업무 / AX 프로젝트 / 미분류(팀 묶음 코드 `DEV·MP·EXT·COM·AX·UNC`) | 단위업무 라벨의 최상위. MM 롤업의 1단 |
| **과제** | 영역 아래의 프로젝트. 팀 레지스트리 ID(`P-0007`) 기반 | 연결 단계에서 레지스트리 ID 충돌 = 연결 금지(§4.5) |
| **역할 업무** | 중간 업무. 과제 × 분야(기구·회로·SW…) × 기능(설계·해석·시험·외주·구매·문서·회의/조율·PM…) | MM 롤업의 중간 단 |
| **단위 업무**(unit task) | 단일 업무. 시작 근거·종료 근거·투입 슬롯을 가진 **인스턴스**. 같은 일의 재의뢰는 같은 인스턴스의 차수(cycle) | 이 문서가 만든다(§4) |
| **업무 유형** | 단위업무에서 한 일의 종류(개발·사무·현장·PM·PL·지원…) — 계층과 직교하는 패싯 | 롤업의 별도 축 |

### 1.2 시간 모델 용어

| 용어 | 정의 |
|---|---|
| **근무 봉투**(envelope) | 사람별·날짜별로 '일했다'고 판정한 5분 슬롯의 **집합**. 모든 PC·모든 경로의 합집합이라 겹쳐 세지 않는다. 총 투입(MM)은 여기서만 나온다 |
| **슬롯**(slot) | 근무 시간대 벽시계 기준 5분(300초) 칸. 슬롯 번호 = `lsec // 300`. 슬롯 안을 증거가 150초 이상 덮으면 봉투에 든다 |
| lsec | 근무 시간대(기본 +09:00) 로컬 벽시계를 2026-01-01 00:00 기준 정수 초로 센 값. 원천은 `ts_utc` + `ts_local_offset` 로 저장되어 있고 정규화 단계에서 바뀐다 |
| **귀속**(attribution) | 봉투의 슬롯마다 300초를 단위업무·버킷에 정수 초로 나누는 것. Σ귀속 = 봉투(보존 법칙, 날마다 assert) |
| **버킷**(bucket) | 어느 단위업무에도 귀속되지 않은 근무 시간 = '근무 중 미분류'. 5종: `B_GENERIC`(일반 앱) · `B_COMM`(무연결 소통) · `B_MEET`(무연결 회의) · `B_OFFPC`(PC 밖 공백) · `B_UNKNOWN`(PC 하한 등 미상) |
| **리드타임**(lead) | 차수별 (종료 − 시작) 경과 시간의 합. 영업 리드 = 그 구간 안 정규 구역(평일 표준창 − 점심) 시간. **투입이 아니다** |
| **투입**(effort) | 그 단위업무에 귀속된 슬롯 초의 합 |
| **등급**(grade) | 단위업무 경계의 신뢰도 A~E(+O 진행 중, Z 미착수, M 수동 기록만). 슬롯 신뢰는 high·mid·low, 분 단위 원장 등급은 O(관측)·I(추정)·X(버킷) |
| **앵커**(anchor) | 능동 산출 신호: 정확 시각(exact·minute) 발신 메일·팀즈, 문서 저장·내보내기·생성(자동 저장 제외), 본인 커밋, 해석 제출. 퇴근 후 시간을 여는 핵심 근거(업무 앱 15분 이상 능동 사용·회의·수동 기록과 함께) |
| **정규 구역** | 근무일 S_eff − 점심. S_eff = 개인 표준창(기본 09:00~18:00)에서 반차·연차를 뺀 그날의 근무창 |
| **창 밖** | 정규 구역이 아닌 모든 시각(평일 표준창 밖, 점심, 주말·공휴일, 연차·반차 시간) |
| **흔적**(trace) | 식사 시간 차감 판정용 흔적 = 앵커 직전 5분 + 업무 앱 전경 + 정규 구역 활동 + 회의 + 수동 기록 |
| **부정 증거** | 샘플러가 관측한 잠금·연결 끊김·절전·유휴·사적 화면. 샘플러 권위는 **부정 증거로만** 행사한다 |
| **양성 증거** | 앵커·능동 표본·수락 회의·직접 수신·수동 업무 기록. 더하면 봉투가 줄지 않는다(단조성, §3.12) |

### 1.3 경계 근거 코드(§4.10 에서 조합표로 쓴다)

결정 메모 §10.2 의 방향 축 이름과의 대응: **S1 = S1i**(받은 의뢰), **S1o**(내가 보낸 지시), **E1 = E1o**(내가 보낸 보고), **E1i**(내가 받은 보고). 팀 묶음 코드는 §4.11.

| 코드 | 시작/종료 | 뜻 |
|---|---|---|
| S1 | 시작 | 디지털 의뢰: 나에게 직접(To·1:1·@멘션, 참여 ≤ 5명) 온 수신 메시지 중 화행 `request`, 시각 정밀(exact·minute) |
| S1d | 시작 | 날짜만 아는 디지털 의뢰(웹·코파일럿 경로의 date-only). 경계는 그날 표준창 시작, 리드타임은 '일 해상도' 표시 |
| S1o | 시작 | 내가 보낸 지시(발신 `request`, 수신자 ≤ 5명) — 조율형(PM/PL) 단위업무 |
| S2a | 시작 | 오프라인 지시 뒤 내가 보낸 수락(`ack`) 발신 — 디지털 의뢰가 없는 대화에서 수락이 시작 |
| S2M | 시작 | 사용자가 확인한 오프라인 지시 시각(확인 큐 응답·수동 기록) |
| S2m | 시작 | 의뢰자(보고 수신자·주최자) 동석 회의 시작 — 첫 진행 증거 전 48시간 안에 끝난 연결 회의 |
| S2p | 시작 | 그 밖: 첫 진행 증거 − 30분(오프라인 지시 또는 자체 진행 추정) |
| E1 | 종료 | 디지털 보고 발신(내 `report`, 또는 `info` + 첨부), 시각 정밀. 보완 보고가 이어지면 마지막 보고로 연장 |
| E1d | 종료 | 날짜만 아는 보고. 경계는 그날 표준창 끝 |
| E1i | 종료 | 내가 받은 보고(조율형 업무의 종료) |
| E1p | (중간) | 중간 보고 — 종료가 아니라 리드타임 분할 표식(보고 낱말 '중간·경과·진행상황·1차' 또는 보완 보고로 덮인 앞 보고) |
| E2h / E2l | 종료 | 작성·산출 완료 후보(점수 ≥ 0.7 / ≥ 0.5, §4.9.2) |
| E3M | 종료 | 사용자가 확인한 오프라인 보고 시각 |
| E3c | 종료 | 의뢰자가 주최한 리뷰·보고형 회의가 마지막 진행 증거 후 24시간 안에 열림 → 회의 끝(달력 근거) |
| E3i | 종료 | 휴면 추정: 마지막 진행 증거 후 5근무일 조용 → 마지막 진행 + 30분 |
| NEXT_REQ | 종료 | 열린 차수에 '조용한 기간(≥ 3근무일)' 뒤 같은 화제 추가 요청 → 앞 차수를 마지막 진행 + 30분에 닫고 새 차수 |
| OPEN | 종료 | 진행 중(업무 창 끝 = 분석 시각) |

---

## 2. 입력 증거 계약

### 2.1 원칙

1. 시간 코어는 **정제기(`lm27.privacy`)를 통과하고 병합(`msg_key` 중복 제거, PC·경로 합집합)이 끝난 레코드만** 받는다. 원문 텍스트는 없다. 토큰·문서명은 로컬 분석에만 쓰고 팀 반출물에 넣지 않는다.
2. 모든 시각은 `ts_utc`(UTC) + `ts_local_offset`(관측 당시 오프셋)로 들어온다. 정규화가 근무 시간대 로컬 초 `lsec` 로 바꾼다. 근무 시간대는 설정 `time.tzOffsetMin`(기본 +540분, 개인 프로필) 하나다. `zoneinfo` 는 쓰지 않는다(동봉 파이썬에 tzdata 없음, 결정 메모 §10.3).
3. **정밀도가 시간 근거 자격을 정한다.**

| `ts_precision` | 봉투 근거 | 경계 근거 | 비고 |
|---|---|---|---|
| exact · minute | 예(앵커·수신 크레딧·회의·표본) | 예 | COM·색인·OWA 분 단위·UIA·샘플러·파일 mtime·git |
| date | **아니오**(옵션 `time.envelope.dateOnlyGate` 를 켤 때만 '그날 PC 하한 게이트', 신뢰 low + Q06) | 일 해상도로만(S1d·E1d) | 같은 (날짜, 방향, 대화)에 정확 사본이 있으면 버린다 |
| summary | 아니오 | 아니오 | 코파일럿 요약 증인. 확인 큐 Q07 의 힌트로만 |
| unknown | 아니오 | 아니오 | 격리(건수만 감사) |

4. **사적·친목·광고**(정제기의 `priv_class ∈ {private, social}`, `flags.ad`)는 앵커·경계·귀속 근거가 될 수 없다(PRIVACY R-P1·R-P2). 메시지는 정규화에서 버리고 건수만 남긴다. 창 표본은 버리지 않고 **사적 표본**(부정 증거)으로 남겨 §3.11 차감에 쓴다.
5. 수집기·메일 첨부·창 제목의 문서명 정규화는 **같은 함수**(`lm27.time.tokens.fam`, §4.1)를 쓴다. 해시 전 이름으로 계산해 `fam_key = HMAC(team_or_person_key, fam)` 를 두 쪽이 같게 만든다(must_fix '첨부명·문서군 정규화 fam()도 수집기와 같은 함수').

### 2.2 원천 레코드 → 시간 코어 레코드 매핑

공통 증거 레코드(`COLLECTION.md` §3)의 `kind` 별로 아래 형으로 바꾼다. 형 이름은 구현 모듈 `lm27/time/evidence.py` 의 dataclass 이름이다.

| 원천 kind(src) | 시간 코어 형 | 핵심 필드(원천 필드 ← ) |
|---|---|---|
| `pc_session`(`pc.sampler`, layer L2/L3) | `Samp` | `pc ← pc_id`, `a ← ts_utc`, `b ← ts_end`, `state ← session_state`(active·locked·disconnected·remote) + `idle_sec`, `cls ← app_class`(카탈로그), `fam ← fam(doc_key)`, `priv ← priv_class`, `idle ← idle_sec`, `app ← app_id` |
| `pc_session`(`pc.events`, L0/L1) | `PcSpan` | `pc`, `a`, `b`(`flags.end_uncertain` 이면 지어낸 끝은 쓰지 않음), `layer` |
| `mail` · `teams` | `Msg` | `dir ← direction`, `act ← 정규화 화행`, `conv ← thread_key`(메일) / `chat_key`(+채널 답글 루트), `peer ← 주 상대 counterpart_keys[0]`, `prec ← ts_precision`, `direct ← (n_to 직접 수신 ∧ ¬flags.cc) ∨ chat_type=1:1 ∨ mentions_me`, `atts ← fam(첨부명)`(HMAC `attach_keys` 와 같은 정규화), `tokens ← subject_tokens`, `n_part ← n_participants`, `key ← msg_key`, `proj ← 레지스트리 과제 ID`(분류 규칙이 붙였을 때), `flags`(cc·notice·bulk·deferred·utc·meeting_response) |
| `cal` | `Meet` | `a`, `b`, `status ← flags.response`(accepted·organizer·tentative·declined) + `meeting_status`(취소), `organizer`, `attendees`, `n_att`, `tokens`, `online ← flags.online_meeting`, `personal ← sensitivity ≥ 1 ∨ 개인 범주`, `all_day`, `category`(근태 파서: offsite·edu·trip·leave·''), `series_key` |
| `pc_file`(`pc.files`·`pc.mru`·`pc.recent`·열린 문서 폴링) | `DocE` | `t ← 저장 시각`, `kind ← op`(create·save·export·open·result), `fam ← fam(doc_key)`, `folder ← 상위 폴더 해시 2단계`, `autosave ← M365 자동 저장 문서`, `other ← flags.author_other`, `proj` |
| `pc_compute`(`pc.compute`) | `Comp` | `pc`, `a`, `b`, `app ← app_id`, `fam ← fam(결과 파일 doc_key)` |
| `pc_git` | `Commit` | `t`, `fam ← 'repo:' + repo 정규화명`, `tokens ← subject_tokens` |
| `manual`(worklog·확인 큐 응답) | `Man` | `kind`(§2.7), `d`, `a`, `b`, `hours`, `ref`(문서명·대화 키·라벨), `tokens`, `key`(응답이 가리키는 증거 키: msg_key·doc_key) |
| 근태(`cal` 근태 파서·`abs_hint`·수동 `leave`) | `leaves[date]` | `full · am · pm` |
| 커버리지 원장(`coverage_ledger.jsonl`) | `coverage[(date, axis)]` | `ok · zero_ok · partial · out_of_horizon · blocked · transport_fail · not_attempted` |

#### 2.2.1 형 정의(구현자가 그대로 옮긴다)

```python
@dataclass(frozen=True)
class Samp:            # 샘플러 표본(틱) — 실측 간격 구간 [a, b)
    pc: str; a: int; b: int
    state: str         # active | idle | locked | disconnected | sleep   (active = 세션 active ∧ idle_sec ≤ 300)
    cls: str           # office|cad|cae|sim|eda|ide|eng|browser|mail|chat|meet|remote|explorer|system|other
    fam: str           # 문서군 키('' = 문서 키 없음)
    priv: str          # work | unknown | media | private | social   (PRIVACY window_class)
    idle: int | None   # idle_sec 원값(다중 PC 동시 활동 판정·고착 판정)
    app: str           # app_id(미지 프로그램 = 'unknown:<exe>')

@dataclass(frozen=True)
class PcSpan:          # L0/L1 가동(이벤트 로그) — 샘플러 없는 PC 의 하한·다리 재료
    pc: str; a: int; b: int; layer: str

@dataclass(frozen=True)
class Msg:
    id: str; t: int; dir: str          # in | out
    act: str                           # request|ack|question|report|info|notice|social (정규화 화행 분류기)
    conv: str                          # 메일 thread_key / 팀즈 chat_key(+루트)
    peer: str; prec: str; direct: bool
    atts: tuple[str, ...]              # 첨부 문서군 키
    tokens: frozenset[str]             # 정제된 제목·본문 토큰(로컬 전용)
    ch: str                            # mail | teams
    flags: frozenset[str]; key: str; n_part: int; proj: str | None

@dataclass(frozen=True)
class Meet:
    id: str; a: int; b: int; status: str; organizer: str; attendees: tuple[str, ...]; n_att: int
    tokens: frozenset[str]; online: bool; personal: bool; all_day: bool; category: str

@dataclass(frozen=True)
class DocE:
    id: str; pc: str; t: int; kind: str; raw: str; fam: str; folder: str
    autosave: bool; burst: bool; other: bool; proj: str | None

@dataclass(frozen=True)
class Comp:  pc: str; a: int; b: int; app: str; fam: str
@dataclass(frozen=True)
class Commit: pc: str; t: int; fam: str; tokens: frozenset[str]
@dataclass(frozen=True)
class Man:
    kind: str          # work|offsite|instr|report|absence|exclude|attended|must_link|cannot_link
    d: date | None; a: int | None; b: int | None; hours: float | None
    ref: str; tokens: frozenset[str]; key: str
```

### 2.3 필드별 정밀도·출처·용도

| 필드 | 출처(우선순위) | 정밀도 | 시간 코어 용도 |
|---|---|---|---|
| 메일 발신 시각 | COM > 색인 > OWA(보낸 편지함, 항목 열어 분) > OWA date > 코파일럿 | exact/minute/date/summary | 앵커(exact·minute만), E1·S1o 경계, 원격 발신 판정 |
| 메일 수신 시각 | COM > 색인 > OWA(받은 편지함은 date) | 〃 | S1 경계, 수신 크레딧(C5), 수신 사슬 하한(C9) |
| 팀즈 메시지 | UIA(로컬, 실시간) > 웹(백필) > '놓친 활동' 알림 메일(존재만) | minute / date | 앵커·S1·E1·ACK, 대화방 짝짓기 |
| 일정 | COM > 색인 > OWA | exact | 회의 구간(C2)·S2m·E3c·근태(반차·연차·외근) |
| 샘플러 표본 | 상주 에이전트(60초 폴링, 실측 간격) | exact | 1차 증거(C1)·부정 증거·L3 맥락 |
| PC 가동(L0/L1) | 이벤트 수확기 | exact(끝 불확실 표식) | 샘플러 없는 PC 의 하한(C8)·PC 다리(C7) |
| 문서 저장 | 열린 문서 mtime 폴링 > 파일 mtime 스캔 > MRU·Recent(열람) | minute | 앵커(저장·내보내기·생성), E2 점수, 문서군 연결 |
| 연산(솔버) | 샘플러 CPU 차분 3틱 > 라이선스 옵트인 | exact | 기계 시간(MM 미포함), 제출 앵커, 솔버 흡수 |
| 커밋 | git log(본인 신원 정확 일치) | exact | 앵커, 저장소 문서군 |
| 수동 기록·응답 | 개인 보고서 화면 | exact 또는 date+hours | 하한(C11)·L1 귀속·경계 확정(S2M·E3M)·제약 |

### 2.4 정규화 규칙(`normalize`)

```text
normalize(records, profile, cfg, as_of) -> Evidence, audit
  for r in records:
      if r.ts_precision == 'unknown': audit['격리_시각불명'] += 1; continue
      t = to_lsec(r.ts_utc, cfg['time.tzOffsetMin'])                          # 근무 시간대 로컬 초
      if r.kind in (mail, teams) and 'utc' in r.flags and cfg['time.envelope.mailTimeOffsetH'] is not None:
          t += mailTimeOffsetH × 3600                                           # UTC 저장으로 확인된 경로만 보정
      if r.ts_precision in (exact, minute) and t > as_of + futureSlackMin: audit['미래시각_폐기'] += 1; continue
      if r.kind in (mail, teams) and (priv_class ∈ {private, social} or flags.ad or act == social):
          audit['사적·광고_시간근거제외'] += 1; continue                         # R-P1·R-P2 — 창 표본은 버리지 않음
  메시지: msg_key 별로 정밀도 순위 exact < minute < date < summary 가 가장 좋은 사본 하나(동률은 id 사전순)
          같은 (날짜, 방향, 대화)에 exact·minute 사본이 있는 date 사본은 버린다(COLLECTION §7.3)
  UTC 의심: exact 발신 ≥ 5건이고 그중 00~08시 비율 ≥ utcSuspectShare(0.6) → run_meta 경고 + 큐 Q13(보정은 하지 않음)
  샘플러 고착: (pc, 날짜)별 커버 ≥ stuckCoverH(14h) 이고 idle>0 표본 비율 < stuckIdleRatio(2%) → 그 PC·그날 표본 폐기(→ 하한 폴백)
  문서 뭉치: (pc, 폴더, 분) 같은 칸에 ≥ fileBurstN(8)건 → 첫 1건만 앵커·진행 후보, 나머지는 burst(건수만)
  타인 작성(author_other)·열람(open)·결과(result)·자동 저장(autosave) 사건은 앵커가 아니다(문서군 시각·E2 재료로는 쓴다)
  IDF: (토큰 있는 메시지 + 문서군) 노드가 idfMinN(20)개 이상이면 df/N > idfMaxDf(0.3) 인 토큰을 '상용 토큰'으로 연결 비교에서 뺀다
  입력 정준 정렬: 모든 목록을 (t0, kind, 원천 키) 로 정렬 — 입력 순서와 무관한 결과(관문 G2)
```

### 2.5 달력·근무 프로필

- **달력은 `calendar.json` 하나**다(팀 서버 레지스트리 `calendar` 배포가 우선, 내장은 공고로 확인된 해만). 내장 공휴일 표를 코드에 두지 않는다(must_fix [달력] — LM24 의 2026-09-28 대체공휴일 오류가 MM·휴면 판정·귀속까지 번졌다).
- 형:

```json
{"version": "kr-2026.3", "std_day_min": 480, "weekdays": [0, 1, 2, 3, 4],
 "years": [{"year": 2026, "holidays": [{"date": "2026-09-24", "name": "추석 연휴", "kind": "법정",
                                        "source_url": "…", "confirmed": "2026-10-05"}]}],
 "company_off": ["2026-12-31"]}
```

- 분석 기간에 `years` 에 없는 해가 섞이면 **분석하지 않는다**(fail-closed, 사유 '달력 미확인 연도').
- 관문(G10): 2026-09 근무일 20일(추석 9/24·9/25 평일, 9/26 토 — 토요일 겹침은 대체공휴일 없음), 2026-10 근무일 20일(10/5 개천절 대체·10/9 한글날).
- 개인 근무 프로필(설정 레지스트리, 개인 덮어쓰기): 표준창 `time.window.std`(09:00-18:00), 점심 `time.window.lunch`(12:00-13:00), 저녁 `time.window.dinner`(18:00-18:30), 야간 `time.window.night`(22:00-06:00), 반차 창 `halfAmOff`(09:00-14:00)·`halfPmOff`(14:00-18:00), 근무 요일 `time.window.weekdays`.
- 날짜 정보(`build_days`): 날짜 d 마다 `hol`(주말·공휴일·회사 휴무), `S_eff`(연차 = 빈 창, 오전 반차 = 표준창 − 09~14, 오후 반차 = 표준창 − 14~18), `lunch`·`dinner`(휴일이면 없음), `leave`(1·0.5·0), `confirmed_absence`(사용자 확인 부재). 자정 문제를 없애려 기간 전체를 **연속된 하나의 시간축**에서 계산한 뒤 슬롯 시작 시각의 달력 날짜로 나눈다.

### 2.6 커버리지 원장 입력

- `coverage[(date, axis)]`, axis ∈ {`mail_out`, `mail_in`, `cal`, `teams`, `pc`}. 시간 코어는 `mail_out`·`teams` 의 결손(`blocked`·`out_of_horizon`·`transport_fail`·`not_attempted`)을 **E3i(휴면 종료) 판정 보류**에 쓴다(§4.9.4). 결손 날을 '보고 메일이 없었다'로 읽어 대면 보고로 오판하지 않기 위해서다(must_fix [커버리지 판정]).
- 미관측 날은 0h 가 아니라 '근거 없음'으로 원장에 표시한다(COLLECTION §5.3).

### 2.7 확인 응답(제약) 입력 — 업무 ID 가 아니라 증거 키로 저장

| `Man.kind` | 필드 | 효과 |
|---|---|---|
| `work` | `a`·`b`(시각) 또는 `d`+`hours`, `ref`/`tokens` | 봉투 C11(하한, 대체 아님) + L1 귀속(ref 가 가리키는 업무, 없으면 MANUAL 업무) |
| `offsite` | `d` | 그날 S_eff 전체를 C11 |
| `instr` | `a`, `ref`(문서명·대화 키) 또는 `key`(msg_key) | 시작 근거가 S2p·S2m 인 업무의 시작을 S2M 으로 |
| `report` | `a`, `ref`/`key` | 종료가 OPEN·E3i·E2l·NEXT_REQ·E3c 인 업무의 끝을 E3M 으로 |
| `must_link` / `cannot_link` | `key`(msg_key), `ref`(문서명) | 그 의뢰와 문서군을 반드시 잇는다 / 잇지 않는다 |
| `attended` | `ref`(회의 ID) | 회의 불참 의심(Q14) 해제 — 회의 귀속 우선 |
| `absence` | `d` | 확인된 부재 → 가용에서 뺀다 |
| `exclude` | `a`·`b` | 사용자가 '업무 아님' 확인 → 봉투에서 뺀다(봉투가 줄어드는 유일한 사용자 경로) |

- 응답은 로컬 `worklog`(추가 전용)에 쌓고, 재분석은 전체를 다시 계산한다(증분 상태 없음 → 응답 반영 누락이 구조적으로 없다).
- **키는 업무 ID 가 아니다.** `instr`/`report` 는 문서군·msg_key·토큰으로 업무를 다시 찾는다. 자체 업무가 나중에 백필된 의뢰 메일을 얻어 S1 업무로 바뀌어도(업무 ID 가 바뀌어도) 응답이 따라간다(시나리오 W47a/b).

### 2.8 예외 처리(입력·실행)

| 상황 | 처리 | 기록 |
|---|---|---|
| `ts_precision = unknown` | 격리(어떤 근거에도 쓰지 않음) | audit `격리_시각불명` |
| 정밀 시각이 분석 시각 + 5분 이후 | 폐기 | audit `미래시각_폐기` |
| 구간 끝 ≤ 시작(표본·PC 가동) | 폐기 | audit `샘플_역순` |
| `flags.end_uncertain`(지어낸 끝) | 확실한 끝까지만 가동으로 본다 | — |
| 같은 PC·같은 시각에 능동과 잠금 표본이 겹침 | 능동이 이긴다(`lockall`·`neg_all` 은 능동을 빼고 계산) | 경고 |
| 표본에 `idle_sec` 없음 | 정상으로 본다(고착 판정 제외) | — |
| 메시지에 대화 키 없음 | 대화 키 = 자기 `msg_key`(혼자인 대화) | — |
| 문서명이 비거나 정제로 지워짐(`doc_key = null`) | 앵커로는 쓰되 업무 연결·자체 업무는 만들지 않음(귀속은 일반 관측) | — |
| UTC 저장 의심 | 자동 보정하지 않음(사용자가 경로를 확인해 `mailTimeOffsetH` 설정) | 경고 + Q13 |
| `calendar.json` 에 분석 기간의 해가 없음 | **분석 거부**(fail-closed) | 사유 '달력 미확인 연도' |
| 미등록 설정 키 | 오류(실행 중단) | — |
| 설정 형 불일치 | 기본값 사용 | `run_meta.warnings` |
| 보존 assert 실패(Σ귀속 ≠ 봉투) | **분석 중단**, 결과·팀 묶음 생성 안 함(코드 결함) | 오류 리포트(날짜·차이 초) |
| 하루 봉투 > 16h | 자르지 않음 | 큐 Q10 |
| 그 달 가용 0일 | 로드율 None('가용 0') | — |
| 커버리지 결손 기간의 휴면 종료 | E3i 보류(OPEN) | 큐 Q03 |
| 확인 응답이 가리키는 증거가 사라짐(재수집으로 키 변경) | 응답은 보존, 적용 못 한 응답은 '미적용 응답' 목록 | 원장 표식 |

---

## 3. 근무 봉투 알고리즘

### 3.0 한눈에

봉투 = 아래 구성요소의 **합집합**을 5분 슬롯으로 양자화한 것. 그 뒤에 수신 크레딧(C5)을 '빈 슬롯에만' 후선택하고, **마지막 단계에서** 사적 사용·개인 일정·사용자 제외를 차감한다(PRIVACY R-P9, 결정 메모 §10.2).

| 코드 | 이름 | 어디서 | 신뢰 | 한 줄 규칙 |
|---|---|---|---|---|
| C1 | 샘플러 활동 | 모든 시각 | high | PC별 능동 표본. 창 밖·점심은 자격(업무 앱 ≥15분 ∨ 앵커 ±15분 ∨ 회의·수동) + **골격 ±30분**만 |
| C1b | 샘플러 다리 | 모든 시각 | mid | 같은 PC 능동 사이 ≤60분, 그 PC 표본이 다 덮고, 창 밖이면 잠금 없음 |
| C2 | 회의 | 모든 시각 | high | 수락·주최(미정은 회의 창 전경 ≥50% 일 때만), 패드 없음 |
| C3 | 앵커 세션 | 모든 시각 | high | 앵커 **직전 창**(메일 20·팀즈 10·파일 30·코드 45·커밋 45·제출 30분). 샘플러가 덮은 PC 앵커는 그 PC 의 부정 증거만 뺀다 |
| C4 | 원격 발신 | 모든 시각 | mid | 활동 ±5분 없고 샘플러 없는 PC 도 켜져 있지 않은 발신의 직전 창 |
| C4L | 원격 연결 다리 | 모든 시각 | mid | 원격 발신과 같은 연결 키(대화·첨부 문서군)의 앞 관측이 60분 안 → 잇는다 |
| C6 | 사슬 다리 | 모든 시각 | mid | C1·C3·C4·C4L 블록 사이 ≤45분. 창 밖은 전 PC 잠금 ≥15분 또는 사적 전용 ≥15분이면 끊는다 |
| C7 | PC 다리 | 모든 시각 | mid | 45~120분 공백: 부정 증거 없고 (샘플러 없는 PC 가동 ∪ 능동 관측)이 다 덮을 때 |
| C8 | PC 하한 | 평일 S_eff | low | 게이트(그날 앵커·회의·샘플러 활동·수동) 있을 때 (PC 가동 − 그 PC 샘플러 커버) ∩ S_eff, 양끝 다듬기 |
| C8d | date-only 하한 | 평일 S_eff | low | 옵션(기본 끔): 게이트 없고 date-only 발신만 있는 날 |
| C9 | 수신 사슬 하한 | 평일 S_eff | low | 직접 수신 간격 ≤90분 3건 이상 사슬 ∩ (PC 가동 − 샘플러) |
| C10 | 흔적 창 | 평일 S_eff | low | 그날 앵커 ≥2건: [첫 − 30분, 끝 + 30분] ∩ S_eff − 샘플러 커버 |
| C10r | 원격 흔적 창 | 평일 S_eff | low | 어떤 PC 가 잠긴 동안 보낸 발신 ≥2건: [첫 − 30분, 끝 + 30분] ∩ S_eff − 잠금 해제 관측 |
| C11 | 수동·종일 외근 | 기록 시각 | high | 시각 있는 수동 업무 기록, 수락한 종일 외근·교육·출장(S_eff 전체) |
| C11u | 수동(시각 없음) | 그날 | high | 시간만 있는 수동 기록 — 그날 정규 구역의 빈 슬롯에 배치 |
| C12 | 솔버 cap | 창 밖 | low | 옵션(기본 끔): LM24 호환. 창 밖 연산을 밤당 4h(사람 흔적 있으면 전부) |
| C5 | 수신 크레딧 | 정규 구역 | mid | 직접 수신 1건 = 그 시각 슬롯 1칸. **아직 봉투가 아닌 슬롯만**, 이른 순, 하루 60분 |

### 3.1 공통 정의

```text
S_all   = ∪_d S_eff(d)                 lunches = ∪_d 점심(d)          meals = lunches ∪ ∪_d 저녁(d)
reg     = S_all − lunches              # 정규 구역(정규 꼬리표가 붙는 곳)
cov[pc] = ∪ 그 PC 표본 구간(모든 상태)     act[pc] = ∪ 능동(state=active ∧ priv ∉ {private, social}) 구간
          media 표본은 reg 안에서는 act, 밖에서는 사적(R-P6)
lock[pc]= ∪ locked·disconnected·sleep    priv[pc] = ∪ 사적(private·social·창 밖 media) 능동 구간
fgwork[pc] = act[pc] 중 cls ∈ WORK_CLS 또는 문서 키 있음      WORK_CLS = {office, cad, cae, sim, eda, ide, eng}
fallback_on = ∪_pc (PC 가동[pc] − cov[pc])           # 샘플러 없는(옛·실패·미설치) 가동 구간
neg_all     = ∪ cov − ∪ act                           # 부정 증거(잠금·유휴·사적)
lockall     = ∪ lock − ∪ act − fallback_on            # '모든 관측 PC 가 잠김'
unlocked_cov= ∪_pc (cov[pc] − lock[pc])
anchors     = 정렬된 (t, kind, pre_min, pc, ref):
              발신(exact·minute, deferred 아님)  mail 20 / teams 10
              문서 save·export·create(자동 저장·뭉치 나머지·타인 작성 아님)  file 30 / code(.py .c .cpp .h .m .js .ts .java .cs .v .vhd) 45
              커밋 45,  해석 제출(연산 시작) 30
trace       = ∪ [t − 5분, t + 1분](앵커) ∪ ∪fgwork ∪ (∪act ∩ reg) ∪ 회의 ∪ 수동     # 식사 차감 판정용
trim_trace  = trace ∪ ∪ [t ± 5분](앵커) ∪ ∪ [act ± 5분]                              # 하한 양끝 다듬기용
meal_cut(X, W=meals) = X − ((X ∩ W) − trace)                                         # 흔적 없는 식사 시간 제거
pre_iv(t, m) = [ (⌊t/300⌋+1)·300 − n·300 , (⌊t/300⌋+1)·300 ),  n = max(1, round(m/5))  # 앵커 슬롯을 끝으로 하는 직전 창
```

- 점심·저녁의 **일반 앱 사용은 흔적이 아니다**(그래서 식사 시간 다리·하한이 개인 사용으로 메워지지 않는다, 시나리오 W34).
- 앵커 흔적은 '직전 5분 + 그 분'이다. 11:58 저장이 12:00~12:05 점심 슬롯을 근무로 만들지 않게 하기 위해서다.

### 3.2 C1 샘플러 활동 + C1b 샘플러 다리

```text
for pc in PCs:
    A = act[pc]; br = []
    for 연속 활동 블록 (…, b0) (a1, …):
        g = [b0, a1)
        if |g| ≤ samplerBridgeMin(60분) and g ⊆ cov[pc] and (g − S_all) ∩ lock[pc] = ∅:
            br += meal_cut(g)                                        # PC 내부 다리(정규창 안 잠깐 자리 비움·읽기)
    run = A ∪ br
    for part in 연결성분(run − reg):                                  # 창 밖·점심·휴일·휴가 조각
        ok = |part ∩ fgwork[pc]| ≥ afterHoursFgMin(15분)
             or ∃ 앵커 t ∈ [part.a − afterHoursAnchorMin(15분), part.b + 15분]
             or part ∩ (회의 ∪ 수동) ≠ ∅
        if not ok: run −= part;  원장 '창밖_무자격_제외' += |part|;  continue
        skel = (part ∩ fgwork[pc]) ∪ (part ∩ ∪[t − 30분, t + 5분](앵커)) ∪ (part ∩ (회의 ∪ 수동))
        keep = skel ∪ (part ∩ ∪[x − 30분, y + 30분](skel))          # 골격 ±30분(skeletonPadMin)
        run −= (part − keep);  원장 '창밖_골격밖_제외' += |part − keep|
    C1 ∪= run − br;  C1b ∪= br ∩ run
```

- **골격 ±30분 규칙**이 연결 성분 전체 자격(원본 A)을 대체한다(must_fix [A 창 밖 자격]). 퇴근 후 5시간 개인 브라우저 + 22:50 저장 1건 → 원본 A 13.00h, 이 규칙 **9.17h**(W27: 정규 8 + 21:50~23:00).
- 점심 근무도 같은 자격으로 판정한다. 점심 브라우저 1h 는 0(W34), 점심 문서 편집 ≥15분은 연장으로 인정.
- AutoSave 문서 편집은 저장 이벤트가 없어도 업무 앱 전경 ≥15분이면 창 밖 자격이 된다(**정책 고정**, W43: 퇴근 후 40분 → 연장 0.67h). 사용자 확인 항목(§11).
- 고착 PC·날(§2.4)은 표본 자체가 없으므로 C8 하한으로 폴백한다(W57: 24h 고착 → 7.67h).

### 3.3 C2 회의

```text
for m in 일정:
    if m.status ∈ {declined, cancelled}: skip
    if m.personal: personal_iv += [a, b); skip                       # R-P5 — §3.11 에서 차감
    if m.all_day: if category ∈ {offsite, edu, trip} ∧ 수락: offsite_days += d; skip
    ok = status ∈ {accepted, organizer}
    if status == tentative:
        ok = tentative=='count' or (tentative=='evidence' and |[a,b) ∩ 회의 창(cls=meet) 능동| ≥ 0.5·|[a,b)|)
        if not ok: 큐 Q15
    if ok: C2 ∪= [a, b)
```

- 패드 없음(LM24 E17b: 패드로 1h × 4 = 6h). 회의 사이 공백은 **잇지 않는다**(C 의 '회의 사이 ≤60분 다리' 접목 금지: 1h 회의 4건 = 4.0h, W37).
- 회의는 사슬(C6) 원소가 아니다. 대신 창 밖 자격의 골격·흔적·게이트에는 들어간다.

### 3.4 C3 앵커 세션 · C4 원격 발신 — 최소 크레딧은 늘 '직전 창'

```text
for (t, kind, pre, pc, ref) in anchors:
    iv   = pre_iv(t, pre)
    tail = 앵커가 든 슬롯
    iv   = (meal_cut(iv) ∪ tail) 중 tail 을 포함하는 연결 조각
    if pc 가 있고 그 PC 샘플러가 t 를 덮음:                           # 샘플러 권위 = 부정 증거로만(must_fix [A 단조성 1])
        keep = (iv − (cov[pc] − act[pc])) ∪ tail                      # 그 PC 의 잠금·유휴·사적 표본만 뺀다. 앵커 슬롯은 항상 남김
        C3 ∪= keep;  continue
    if kind == sent and ∪act ∩ [t − 5분, t + 5분] = ∅:                  # 원격(휴대폰·웹) 발신 후보
        remote_sends += (t, ref, iv)
        if t ∉ fallback_on:  C4 ∪= iv;  if t ∉ S_all: 원장 표식 '원격발신' → 큐 Q04;  continue
    C3 ∪= iv
```

- 원본 A 의 '샘플러가 덮은 저장은 세션 없음'(P5)을 버렸다. 그 규칙 때문에 21:00 저장 1건(0.5h)에 샘플러 2분을 더하면 0h 가 됐다. 이제 **W29a 0.50h = W29b 0.50h**.
- 직전 창의 식사 시간은 흔적이 없으면 뺀다(앵커 슬롯은 남긴다). 발신 1통만 있는 PC 없는 날은 20분이다(LM24 V11 의 '1통 = 1.0h' 는 버렸다 — 단조성과 맞바꾼 선택, §11 보정 항목).

### 3.5 C4L 원격 연결 다리(C 접목)

```text
for (t, ref, iv) in remote_sends:
    cand = { 첨부 문서군 f ∈ ref.atts 의 능동 전경 끝·저장·내보내기 시각 x : iv.a − remoteLinkGapMin(60분) ≤ x ≤ iv.a }
         ∪ { 같은 대화(ref.conv)의 앞 발신 시각 x : iv.a − 60분 ≤ x < t − 5분 }
    if cand: C4L ∪= meal_cut([max(cand), iv.a))
```

- 연결 키는 **키 동일성**(같은 대화·같은 문서군)만 본다. 그래프 성분(IDF·허브 억제처럼 증거가 늘면 약해지는 요소)은 봉투에 쓰지 않는다 — 봉투 단조성을 지키기 위해서다.
- W61: 클라우드PC 22:00~22:50 문서 → 연결 끊김(부정 증거) → 00:05 휴대폰 회신(같은 문서 첨부): 22:50~23:50 다리(1.00h) + 직전 창 → 야간 2.17h.

### 3.6 C6 사슬 다리 · C7 PC 다리

```text
chain = U(C1 ∪ C1b ∪ C3 ∪ C4 ∪ C4L)                                 # 회의·수신은 사슬 원소가 아니다
for 연속 블록 사이 공백 g = [b0, a1):
    if |g| ≤ sessionGapMin(45분):
        off = g − S_all
        if off ∩ lockall 에 lockBreakMin(15분) 이상 연속 조각: 원장 '잠금단절_다리없음'; continue     # 창 밖 잠금은 잇지 않음
        if off ∩ (∪priv − ∪act) 에 privacy.time.offhours_private_break_min(15분) 이상 연속 조각:
            원장 '사적단절_다리없음'; continue                                                       # R-P4
        C6 ∪= meal_cut(g)
    elif |g| ≤ pcBridgeMin(120분) and g ∩ neg_all = ∅ and g ⊆ (fallback_on ∪ ∪act):
        C7 ∪= meal_cut(g)
```

- 정규 구역 안의 ≤45분 잠금 공백은 잇는다(복도·실험실·즉석 대면 — PC 밖 업무로 본다). 창 밖에서는 **샘플러가 관측한 전 PC 잠금 15분 이상이면 끊는다**(B 의 'bridge45 가 잠금 공백까지 잇는다' 접목 금지). W28: 01:40~02:30 잠금 → 01:40~02:25 는 근무가 아니다(11.83h). 같은 하루를 샘플러 없이 PC 가동만으로 보면(W28b, LM24 V9) 23:05~01:05·01:35~02:25 를 C7 로 이어 22:35~02:45 가 연속(12.00h).
- C7 은 원본 A 의 '샘플러 커버 없음' 조건을 '부정 증거 없음 ∧ (가동 ∪ 능동 관측)이 덮음'으로 바꿨다. 능동 표본 하나를 더해 다리가 끊기는 비단조(퍼즈 반례)를 없애기 위해서다. 창 밖 일반 앱은 앵커 사이 메우기로만 허용한다는 PRIVACY R-P6 과 같은 방향이다.
- 퇴근 후 공백을 19:00 고정으로 메우던 LM24 저녁 크레딧은 없다(R5). 늦은 재개는 첫 흔적부터 센다.

### 3.7 C8 PC 하한 · C8d · C9 수신 사슬 하한 (평일 S_eff 안)

```text
for 평일 d (분석 기간 안, S_eff(d) ≠ ∅):
    gate    = 그날 앵커 ≥1 ∨ 회의 ∨ C1 활동 ∨ 수동 work/offsite
    gate_do = ¬gate ∧ dateOnlyGate ∧ 그날 date-only 발신 ≥ 1                     # 기본 False(must_fix [date-only 게이트])
    base = ∪_pc ((PC 가동[pc] − cov[pc]) ∩ S_eff(d))                             # (pc, 시각) 단위 — 다른 PC 샘플러가 지우지 않는다
        항상 켜짐(그날 가동 ≥ alwaysOnH 20h): 그 PC 몫 ∩ [첫 trim_trace − 25분, 끝 + 25분]
    if base and (gate or gate_do):
        b2 = trim_edges(base, trim_trace, trimEdgesMin 10분)                     # 양끝 10분 안에 흔적 없으면 최대 10분 다듬기
        (C8 if gate else C8d) ∪= meal_cut(b2, lunches);  원장 '점심차감'
    if base:                                                                     # 게이트와 무관하게 늘 계산(합집합 → 단조)
        직접 수신(exact·minute, ¬cc·notice·bulk, n_part ≤ 10, S_eff 안)을 간격 ≤ passiveChainGapMin(90분)으로 사슬
        for 사슬 c with |c| ≥ passiveChainMinN(3): C9 ∪= meal_cut([c.first − 5분, c.last + 5분] ∩ base, lunches)
```

- 하한 창은 표준창(S_eff)이다. LM24 의 08~19 하한(파일 1건 + PC 08~19 → 9.67h·초과 1.7h, E8)은 **7.67h·초과 0**(W39).
- 다른 PC 의 샘플러 5분이 PC1 하한을 지우지 않는다(C 의 날 단위 스위치 접목 금지): W30a 7.67h = W30b 7.67h.
- 에이전트를 15시에 중도 설치한 날(W31a 7.83h) ≥ 샘플러를 뺀 같은 날(W31b 7.67h).
- 수신 연속형(R7): 직접 수신 8통(1시간 간격) 6.17h, 80통 7.08h, CC 1통 0h(W36). 7→8통 절벽(0.58→7.83h)이 없다.

### 3.8 C10 흔적 창 · C10r 원격 흔적 창 — 'PC 기록 없는 날' 체제 전환 폐지

```text
for 평일 d:
    if 그날 앵커 ≥ traceWindowMinAnchors(2):
        C10 ∪= meal_cut(I([첫 앵커 − 30분, 끝 앵커 + 30분], S_eff(d)) − ∪cov, lunches)       # 조건 없이 합집합
        (하한 b2 밖으로 더해지는 부분이 있으면 표식 '흔적창(낮은 신뢰)' → 큐 Q05)
    r = { 그날 정확 발신 시각 t : 어떤 PC 의 샘플러가 t 에 잠금 }
    if |r| ≥ remoteSpanMinSends(2):
        C10r ∪= meal_cut(I([min r − 30분, max r + 30분], S_eff(d)) − unlocked_cov, lunches)  # 잠금·꺼짐 구간도 흔적(low)
        표식 '원격발신 흔적창(낮은 신뢰)' → 큐 Q05
```

- 원본 A 는 흔적 창을 'PC 기록이 전혀 없는 날'에만 켰다. 그래서 PC 가동 기록을 빼면 봉투가 늘었다(퍼즈 15/300, 6.08h → 9.17h). 합집합형으로 바꿔 **W65a 8.50h = W65b(PC 기록 제거) 8.50h**, 퍼즈 6,000 세계에서 0건(§10 G3).
- 원격 흔적 창(must_fix [A 단조성 2]): 수집 안 된 노트북으로 오후 내내 메일을 보낸 날(PC1 은 오후 잠금) → 4.00h(원본 A) → **7.00h**(W33) + 큐 Q05. 발신 판정은 '어떤 PC 가 잠김'(부정 증거)에만 의존하므로 능동 표본을 더해도 줄지 않는다.
- PC 기록 없는 평일 외근(LM24 V11): 10:00·15:00 발신 → 09:30~15:30 − 점심 = **5.00h**(W38) + 큐 Q05('미등록 외근 후보').

### 3.9 C11 수동·종일 외근 · C12 솔버 cap(옵션)

- C11 = 시각 있는 수동 work ∪ 종일 외근일의 S_eff. 수동 기록은 **대체가 아니라 하한**이다(합집합이라 관측과 겹치면 한 번만, LM24 K11).
- C12(`time.envelope.solverMode = 'cap'`, 기본 `anchor`): 연산 구간의 창 밖 부분에 사람 활동이 있으면 그 부분 전체, 없으면 끝쪽 `solverCapH`(4h). W42b: 같은 입력이 anchor 모드 15.00h, cap 모드 19.00h(야간 4h). 기본 anchor 모드는 기계 시간을 봉투에 넣지 않고 단위업무의 `machine_s`(MM 미포함)로만 보고한다(결정 메모 §10.2 '기계 시간' 열).

### 3.10 양자화 · 근거 코드 · 수신 크레딧(C5 후선택)

```text
cover[s] = |(∪ C*) ∩ [300s, 300s + 300)|
slots    = { s : cover[s] ≥ time.slotCoverSec(150초) }                      # 반올림 무편향(절반 이상)
basis(s) = PRIO 순 첫 구성요소 중 슬롯 안 ≥ 60초인 것
           PRIO = C11 > C11u > C2 > C1 > C3 > C4 > C1b > C4L > C6 > C7 > C8 > C8d > C9 > C10 > C10r > C12 > C5
# 수신 크레딧: 다리에 투명, 마지막에 '아직 봉투가 아닌 슬롯'만
for 직접 수신 t (정밀, ¬cc·notice·bulk, n_part ≤ 10) 시각순:
    if t ∉ reg or t ∈ (neg_all − fallback_on): continue                       # 샘플러가 잠금·유휴·사적으로 본 시각은 아님
    s = ⌊t/300⌋                                                              # 1건 = 그 슬롯 1칸(passiveCreditMin 5분)
    if s ∉ slots and s 가 reg 안: 하루 누적 < passiveDayCapMin(60분) 이면 slots += s, basis = C5
                                   아니면 원장 '수신상한_제외'
```

- 이 '후선택'은 C 접목이다. 원본 A 의 '샘플러 미커버일 때만 수신 세션'(체제 전환)을 없애, 표본을 더해 수신 크레딧이 사라지는 일이 없다.
- PC 기록 없는 평일 수신 8통(40분 간격)만 → **0.67h**(W62, LM24 V2 '≤60분').

### 3.11 마지막 단계 차감 — 사적 사용(R-P3·R-P4·R-P9) · 개인 일정(R-P5) · 사용자 제외

```text
priv_only(s) = |슬롯 ∩ (∪priv − ∪act)| ≥ 150초 ∧ |슬롯 ∩ (∪act ∪ 회의 ∪ 수동 ∪ 외근)| < 60초
               ∧ 슬롯 안 앵커 없음 ∧ basis(s) ∉ {C11, C11u, C2}
연속 priv_only 슬롯 묶음마다:
    정규 구역 부분: 길이 ≥ privacy.time.regular_private_run_min(30분) 이면 전부 차감, 짧으면 중립(R-P3)
    창 밖 부분: 전부 차감(R-P4)
개인 일정(민감도 1·2 또는 개인 범주): 정규 구역 슬롯 중 그 슬롯에 앵커가 없으면 차감(R-P5, 창 밖은 무시)
사용자 exclude(a, b): 차감
→ 원장 '사적차감 n분', '개인일정차감 n분', '사용자제외 n분'(내용·앱 이름 없음, R-P7)
```

- 차감은 **봉투가 줄어드는 것**이지 다른 업무로 옮겨 붙는 것이 아니다(보존 법칙이 봉투 뒤에 돌기 때문). W48: 근무창 안 사적 사이트 30분 → 7.50h, 원장 '사적차감 −0.50'.
- 시각 없는 수동 기록(C11u)은 차감 **뒤에** 배치한다: 그날 정규 구역의 빈 슬롯을 시각순으로 채우고 모자라면 표준창 끝부터 이어서 채운다(사용자 선언 하한).

### 3.12 단조성 — 정의와 구조적 근거

**정의**(관문 G3):
1. **양성 증거**(능동 표본·앵커·수락 회의·직접 수신·수동 업무 기록)를 하나 더하면 봉투는 **줄지 않는다**.
2. **PC 가동 기록**(L0/L1)을 빼면 봉투는 **늘지 않는다**.
3. **부정 증거**(잠금·유휴·사적 표본, 개인 일정, 사용자 제외)를 더하면 봉투가 줄 수 있다 — 정의상 허용.

구조적 근거(각 구성요소가 양성 증거에 대해 단조인 이유):

| 구성요소 | 단조 근거 |
|---|---|
| C1 | 자격 조건(업무 앱 길이·앵커 근접·회의)과 골격은 증거가 늘수록 넓어진다. 능동 표본을 더하면 정규 구역은 무조건 포함 |
| C3·C4 | 직전 창은 증거와 무관하게 늘 준다. 샘플러 권위는 부정 증거로만 뺀다 |
| C4L | 키 동일성만 본다(그래프 가중·IDF 미사용) |
| C6 | 끊는 조건은 부정 증거(전 PC 잠금·사적)에만 의존. lockall 은 능동 관측을 빼고 계산한다 |
| C7 | 조건이 '부정 증거 없음 ∧ (가동 ∪ 능동)이 덮음' → 능동을 더하면 더 쉽게 성립 |
| C8 | (PC 가동 − 그 PC 커버): 능동 표본이 지운 부분은 C1 이 정규 구역에서 그대로 가져간다 |
| C9 | 게이트와 무관하게 늘 계산(합집합) |
| C10 | 조건 없는 합집합. 커버로 지운 부분은 C1(능동) 또는 부정 증거 |
| C10r | 발신 판정이 '어떤 PC 잠김'(부정 증거)에만 의존 |
| C5 | 후선택: 빈 슬롯 수 = min(상한, 후보 − 봉투) 이므로 봉투가 늘어도 총량이 줄지 않는다 |

퍼즈 결과(§10 G3): 기본 세계 3,000건 + 확장 세계(3일·PC 2대·창 밖·사적·연산·반차) 3,000건에서 **양성 증거 추가 → 감소 0건, PC 기록 제거 → 증가 0건**.

### 3.13 꼬리표

```text
tag(s) = 휴일  if 그 날짜 hol(주말·공휴일·회사 휴무)
       = 야간  elif 슬롯 시각 ∈ night(22:00~06:00)
       = 정규  elif 슬롯 ⊆ S_eff − 점심
       = 연장  otherwise                                  # 평일 창 밖·점심 근무·연차·반차 시간 근무
```

- 배타 4분류이며 우선순위는 휴일 > 야간 > 연장 > 정규(TEAM R-2, 정규·연장은 정의상 겹치지 않는다). 팀 묶음 코드 `holiday·night·extended·regular`.
- 보조 꼬리표: `holiday_night`(휴일 중 22~06, 참고 집계), `on_leave`(연차·반차 시간 근무 — 큐 Q16).
- 자정을 넘는 근무는 슬롯 시작 시각의 달력 날짜로 나뉜다(금 23:00~토 01:00 회의 = 금 야간 1h + 토 휴일 1h, W53).

---

## 4. 단위업무 형성

### 4.0 흐름

```text
build_tasks(ev, env, days, cfg, cal) -> list[UnitTask], queue
  (a) conversations()   대화 상태기계(관점 A 골격): 의뢰·수락·지시·보고로 단위업무 뼈대와 차수를 만든다
  (b) families()        문서군 구간화: 휴면 분리 또는 반복 문서 ISO 주 분리
  (c) link_docs()       키 사슬 연결(관점 B 접목): 첨부(강)·토큰+시간+과제(약 합산) → 구간을 업무에 잇는다
  (d) self_tasks()      남은 구간 → 자체 업무(SELF), 문서 키 없는 공학 앱 → APP, 고아 보고 → SELF 종료 또는 REPORT_ONLY
  (e) collect_progress()진행 시각 P 모으기(여러 업무에 연결된 구간은 시각별 예비 창으로 나눔)
  (f) meetings()        회의 연결 → S2m 시작·E3c 종료·L2 귀속 대상
  (g) manual_answers()  확인 응답(증거 키) → S2M·E3M
  (h) boundaries()      S2p 시작·선행 착수·NEXT_REQ 차수·E2/E3c/E3i/OPEN·미착수·등급·상태
  (i) machine()         연산 시간 → 업무 machine_s
  (j) 거대 성분 가드
```

AI(코파일럿)는 이 단계에 개입하지 않는다. 코파일럿은 완성된 단위업무에 이름·분류 라벨·서술만 붙이고 시간·경계·등급은 덮어쓰지 못한다(결정 메모 §5).

### 4.1 토큰·문서군 정제(수집기와 공용 모듈 `lm27/time/tokens.py`)

```python
FAM_TAIL = r'([_\-\s]?(v\d+(\.\d+)?|rev\d+|r\d+|최종|final|수정본?|사본|copy|\(\d+\)|\d{6,8}))$'
def fam(name):          # 문서군 키(해시 전 이름) — 메일 첨부·창 제목 doc_key·파일 이름 모두 이 함수
    x = NFKC(name).lower().strip()
    x = strip_ext(x)    # .gz/.zip/.7z 복합, Creo .prt.12, 일반 확장자 1~5자
    repeat ≤5: x = re.sub(FAM_TAIL, '', x).strip(' _-')
    return x            # 저장·비교는 fam_key = HMAC(키, x)

def doc_key(name, folder):  # 자체 업무 구간 묶음용 — 범용 이름이면 폴더 해시 2단계를 붙여 다른 폴더의 같은 이름을 가른다
    f = fam(name); return f if not is_generic(f) else f + '@' + folder_hash2

def is_generic(f): return f in episode.docs.genericStems or re.match(r'^(book|문서|통합 문서|presentation|프레젠테이션|image|untitled|document|새 문서)\s*\d*$', f)
  # 기본 불용 사전: 보고서·자료·문서·첨부·발표자료·회의록·정리·초안·최종본·untitled·image·presentation·book·
  #               '새 Microsoft Excel 워크시트'·'새 Microsoft Word 문서'·'새 Microsoft PowerPoint 프레젠테이션'·'제목 없음'·'통합 문서'·document

def raw_tokens(parts): # 분리 [_ - 공백 . , / ( ) [ ] + & ~], 소문자, 길이 ≥ 2, 상용구·버전·숫자 제거
  # 상용구(episode.tokens.boilerplate): 검토·부탁드립니다·부탁·요청·요청드립니다·드립니다·회신·공유·보고·보고드립니다·건·
  #   re·fw·fwd·관련·자료·송부·확인·결과·건입니다·및·문의·수정·회의·미팅·the·첨부

def tok_sim(A, B, minSubLen=2):   # 한국어 합성어 대응 — 부분 문자열(길이 ≥ 2) 포함을 일치로 본다
    hit(x, Y) = ∃y∈Y: x == y or (len(x) ≥ 2 and x in y) or (len(y) ≥ 2 and y in x)
    return (|{a∈A: hit(a,B)}| + |{b∈B: hit(b,A)}|) / (|A| + |B|)      # 부분 문자열 Dice
```

- 예: 의뢰 토큰 {견적}(검토는 상용구) ↔ 문서 '견적검토.xlsx' {견적검토} → 1.0. 원본 A 의 Jaccard 는 0 이었다(must_fix [한국어 토큰], W23).
- 연결 비교 전에 IDF 상용 토큰(§2.4)을 뺀다. 문서군 토큰 `ftoks(f) = raw_tokens([f]) − 상용 토큰`.
- 과제 코드명·별칭은 팀 레지스트리 설정에만 있고(저장소 기본값 빈 값) 분류 규칙이 메시지·문서에 `proj`(과제 ID)를 붙인다. 시간 코어는 그 ID 만 본다.

### 4.2 대화 상태기계(관점 A 골격 + B·C 접목)

대화 키 `conv` = 메일 대화(thread_key) 또는 팀즈 대화방(chat_key, 채널은 답글 루트까지). 메시지를 시각순으로 걷는다. `topic(m, tk)` = 3 × |m 첨부 문서군 ∩ tk 문서군| + 2.5 × tok_sim(m 토큰 ∪ 첨부 문서군 토큰, tk 토큰 ∪ tk 문서군 토큰).

```text
for m in msgs(시각순):
  if m.prec == summary: 큐 Q07; continue
  open_ = conv 의 열린 업무(마지막 차수 끝 없음)
  ① 받은 의뢰(dir=in, act=request, direct, n_part ≤ requestMaxParticipants 5):
       sb, s = (S1, m.t) if 정밀 else (S1d, 그날 표준창 시작)
       if open_: best = argmax topic
           if topic(best) > 0 or m 에 내용 토큰·첨부가 없음: best.추가지시 += (m.t, m.id)   # 시작은 바꾸지 않는다
               continue
           # 같은 방·다른 화제(토큰·첨부 불일치) → 새 업무(병행) — 1:1·그룹 상시 대화방 must_fix
       closed = conv 의 닫힌(보고된) 업무 중 마지막 끝 → s 근무일 ≤ reworkWindowWd(10)
       if closed: best = argmax topic
           if topic(best) > 0 or 내용 없음: best.차수 += Cycle(s, sb)                          # 재의뢰·수정 rev k+1
               continue
           # 같은 스레드라도 무관한 새 의뢰(X24) → 새 업무
       새 업무 S1(kind=S1, 시작 sb, peer=m.peer, 토큰, 첨부 문서군 강도 3, proj)
  ② 보낸 지시(dir=out, act=request, 수신 ≤ 5): 열린 COORD 와 화제 같으면 추가지시, 아니면 새 업무 COORD(시작 S1o)
  ③ 보낸 수락(dir=out, act=ack): open_ 있으면 best topic 업무의 진행(수락 시각 표식, 대기시간 지표)
                                  없으면(디지털 의뢰 없음) 새 업무 ACK(시작 S2a)
  ④ 보낸 보고(dir=out, act=report 또는 info+첨부): §4.3
  ⑤ 받은 보고(dir=in, report 또는 info+첨부): conv 의 열린 COORD 가 있으면 E1i 로 닫고 첨부를 그 업무 문서군(강도 3)에
  ⑥ 그 밖의 정밀 발신: open_ 의 best topic 업무(없으면 conv 의 최근 업무가 supplementWd 2근무일 안이면 그 업무) 진행 P
                       어느 것도 아니면 '무연결 발신' → §4.6 토큰 연결
```

- 그룹방에서 멘션 없는 의뢰는 `direct=False` 라 S1 이 아니다. 참여 6명 이상 단체 요청도 S1 이 아니다(연결만).
- 1:1 상시 대화방(X19): 10:00 브라켓 의뢰 → 10:02 수락 → 13:30 모터 의뢰(화제 다름 → 새 업무) → 14:00 브라켓 보고 → 16:30 모터 보고. 결과 **업무 2개 A·A, 3.17h / 2.92h**(W17). 원본 A 는 5.67h/0h, C 는 0h/5.33h 였다.

### 4.3 보고 종료 — 짝짓기 · 다대다 · 보완 · 중간 보고

```text
on 보낸 보고 m (첨부 문서군 fa, 토큰 mt):
  interim = mt ∩ interimWords(중간·경과·진행상황·1차·중간보고) ≠ ∅
  if open_:  primary = argmax_{open_} (topic, 시작, id)          # 대화방 짝: 토큰·첨부 겹침 최대 → 최근
  else:
     rec = 닫힌 업무 중 (같은 conv ∧ 끝 → m 근무일 ≤ 1) ∨ (fa ∩ 문서군 ≠ ∅ ∧ 끝 → m ≤ supplementWd 2)
     if rec: 그 업무 끝을 m 으로 연장, 앞 끝은 E1p(중간 보고)로 차수 안에 기록  # 보완 보고·전달 보고(E1o)
             return
     cands = 다른 대화의 열린 S1·ACK 업무 중 peer == m.peer ∧ (fa ∩ 문서군 ≠ ∅ ∨ topic ≥ 2.5·reportSim(0.3))
     primary = argmax cands
  if primary 없음: 고아 보고(§4.6)
  if interim: primary 차수에 E1p 기록(종료 아님), 첨부 문서군 강도 3; return
  primary 마지막 차수 끝 = m.t (E1, date-only 면 그날 표준창 끝 E1d)
  # 다대다(결정 v2): 같은 의뢰자의 다른 열린 업무 중 첨부 문서군이 그 업무의 것(문서군 일치 또는 tok_sim ≥ multiCloseSim 0.6)
  for tk in 열린 S1·ACK, tk.peer == m.peer, tk ≠ primary:
     hit = { f ∈ fa : f ∈ tk.문서군 ∨ tok_sim(ftoks(f), tk.토큰) ≥ 0.6 }
     if hit: tk 를 같은 E1 로 닫는다(표식 '다대다 종료'); 그 첨부가 primary 와 맞지 않으면 primary 문서군에서 뺀다
```

- 상용구만 겹치는 보고('검토 부탁드립니다 결과')는 어느 의뢰와도 짝이 되지 않고 단발 보고가 된다(W25).
- X20(W18): M1 스레드 보고 1통에 원가·일정 두 파일 첨부 → **두 의뢰 모두 E1(A)**, 서로 합쳐지지 않음.
- 조율형(X21, W19): 내가 P5 에게 지시(S1o) → P5 보고 수신(E1i, 첨부) → 검토 → P1 에게 같은 첨부로 전달 보고 → 보완 규칙으로 끝 연장. **조율형 업무 1개(A), 투입 2.67h**(내 발신 작성 창·검토 전경·전달 작성 창만). 원본 A 는 24h 중 22.08h 를 미귀속으로 남겼다.

### 4.4 문서군 구간화와 반복 문서

```text
문서군 f 의 시각 집합 times(f) = 저장·생성·내보내기(뭉치 대표만, 타인 작성 제외)
                                 ∪ 능동 전경 표본 [a, b) 의 양끝 ∪ 연산 제출 ∪ 커밋('repo:<키>')
recurring(f) = |ISO 주(times)| ≥ recurringMinWeeks(4) ∧ 주당 활동일 중앙값 ≤ recurringMaxDaysPerWeek(2)
구간 = recurring 이면 ISO 주마다 하나, 아니면 이웃 시각 사이 근무일 간격 > splitWd(5)에서 자른다
```

- 주간보고처럼 '매주 드문드문' 손대는 문서는 주마다 다른 단위업무가 된다: 9/2~10/21 매주 수요일 주간보고.xlsx → **인스턴스 8개, 각 1.17h**(W20). 원본 A 는 리드 50일짜리 1건(E)이었다.
- B 의 '6주 초과면 반복' 규칙은 조밀한 장기 문서(주 3일 이상 편집하는 두 달짜리 설계서)까지 주마다 쪼갠다. 그래서 **주당 활동일 조건**을 붙였다(심사 접목의 취지 — 허브 억제 — 는 유지). 범위를 넘은 같은 키는 합치지 않고 `follow_of`(같은 문서군의 앞 인스턴스)로만 잇는다.

### 4.5 키 사슬 연결(관점 B 접목) — 구간 → 업무

```text
for tk in 업무(kind ∈ {S1, ACK, COORD}):
    s0 = 첫 차수 시작;  W = [s0 − preWorkH(24h), (닫힘 ? 마지막 끝의 날 + reworkWindowWd 근무일 : 분석 시각)]
    for 문서군 f:
        if (tk.첫 근거 키, f) ∈ cannot_link 응답: skip
        if tk.과제 ID 와 f 의 과제 ID 가 모두 있고 다르면: skip                       # 과제 레지스트리 충돌 = cannot-link
        강도 = 3  if f ∈ tk.첨부 문서군 ∪ must_link 응답
             = 2  if ¬범용(f) ∧ 어떤 구간 sg ⊂≈ W 에 대해
                    wToken(2.5)·tok_sim(ftoks(f), tk.토큰)
                  + wTime(0.5)·[sg.시작 ≥ s0 − 24h ∧ s0 → sg.시작 근무일 ≤ linkWindowWd(3)]
                  + wProject(0.7)·[과제 ID 같음]   ≥ link.theta(2.0)
             = 0  otherwise
        if 강도: W 와 겹치는 f 의 구간마다 links[tk] = 강도
                 (반복 문서 구간은 그 업무 차수의 시작·끝 ISO 주와 같은 주만)
공용 문서: 팀 레지스트리 '공용 문서' 표식 문서군, 또는 한 구간에 sharedDocMinTasks(3) 개 이상 업무가 연결 → shared(귀속 시 B_GENERIC) + 큐 Q18
```

- **강한 키**(첨부↔문서, 확인 응답 must_link)는 단독으로 잇고, **약한 키**(토큰·시간·과제)는 합산이 θ 이상일 때만 잇는다. 토큰만 같고 시간이 안 맞거나, 과제 코드만 겹치는 경우는 잇지 않는다(유사도 0.4 = 1.0 + 0.5 = 1.5 < 2.0).
- 범용 이름(보고서.pptx)은 토큰으로 잇지 않는다. 첨부로 이은 범용 문서는 **시각 창으로 나눈다**(§5.2 resolve): X23(W21) 두 의뢰가 같은 '보고서.pptx' → 업무 2개(A·A) 2.50h / 11.50h. B 는 16h 업무 1개로 합쳤다.
- 과제 충돌(B S32, W24): 같은 상대·같은 토큰 의뢰 2건이 과제A·과제B 로 갈리면 각자 자기 과제 문서만 잇는다. 과제 ID 가 같으면 약한 토큰 연결을 보강한다(W24b: 유사도 0.67 → 1.67 + 0.5 + 0.7 ≥ 2.0).
- 공용 문서(W45): 업무 3개가 같은 주에 '팀공용_마스터.xlsx' 를 함께 쓰고 각 보고에 첨부 → 마스터 편집 시간 8.92h 는 **B_GENERIC**(최근 시작 업무로 쏠리지 않음).
- 거대 성분 가드: 한 업무의 진행 시각이 giantNodes(500) 개를 넘거나 기간이 giantDays(90일)를 넘으면 표식 + 큐 Q12(분할 제안). 시간 코어는 업무를 합치는 연산이 자체 업무 병합(§4.6)뿐이라 B 의 '의뢰 378건 → 업무 45개' 같은 붕괴가 구조적으로 작다.

### 4.6 자체 업무(SELF) · 앱 업무(APP) · 고아 보고 · 무연결 발신

```text
# SELF: 어느 업무에도 연결되지 않은 구간을 시각순으로
for sg in 미연결 구간(시작 시각순):
    merged = (¬범용(sg.f)) 이고 기존 SELF 중 tok_sim(ftoks(sg.f), SELF.토큰) ≥ selfMergeSim(0.5)
             ∧ |sg.시작 − SELF 첫 진행| ≤ selfMergeDays(3일) 인 첫 것
    없으면 새 SELF(첫 근거 키 = f|날짜, 시작 S2p)
# APP: 문서 키 없는 공학 앱(cad·cae·sim·eda·ide·eng) 능동 사용 → app_id 별, 근무일 간격 > 5 에서 분리
# 고아 보고: 첨부 문서군을 가진, 보고 시각 전에 시작한 열린 SELF 가 있으면 그 SELF 를 E1 로 닫고 peer = 보고 수신자(S2p×E1 = C)
#            없으면 REPORT_ONLY(창 = 보고 직전 창, 종료 E1, 등급 D, 표식 '단발보고')
# 무연결 발신: 업무 대화 밖의 정밀 발신 중 토큰이 어떤 업무(토큰 ∪ 문서군 토큰)와 tok_sim ≥ sendTokenSim(0.6) → 그 업무 진행 + L4 귀속
```

- W63: '열해석_모델.cas'(월) → '열해석_결과정리.xlsx'(화) → 자체 업무 1개(11.00h). 업무 ID 는 가장 이른 구간의 키(열해석_모델|10-26)가 정한다.
- W33: 오후에 '검토의견' 제목으로 보낸 정보 발신 3통 → 문서 '검토의견_과제B' 자체 업무와 토큰 유사 0.67 → 그 업무의 진행·발신 창 귀속.

### 4.7 회의 연결 — S2m · E3c · L2 귀속 대상

```text
for 산입된 회의 mt:
    후보 = 업무(S1·ACK·COORD·SELF·REPORT_ONLY) 중 mt.시작 ∈ [시작 − s2MeetLookbackH(48h), (끝 또는 분석 시각) + e3cLookaheadH(24h)]
    score = 2·[mt.주최자 ∈ 업무 상대들] + 2.5·tok_sim(mt 토큰, 업무 토큰 ∪ 문서군 토큰)
    best ≥ meetLinkMin(2.0) → 연결(L2 대상).  review = (mt 토큰 ∩ reviewWords(리뷰·review·DR·보고·검토회의·결과보고·발표) ≠ ∅) ∨ 토큰 유사 > 0
    연결 안 되면 B_MEET(회의 시리즈 키는 원장에 남겨 롤업 단계에서 레지스트리 키워드로 과제 직접 귀속 가능)
S2m: 시작이 S2p 인 업무에 연결된 회의가 첫 진행 전 48h 안에 끝났으면 시작 = 그 회의 시작(가장 최근 회의)
E3c: 종료 근거가 없는 차수에서, review 회의 ∧ 주최자 ∈ 업무 상대들 ∧ 회의 시작 ∈ [마지막 진행, 마지막 진행 + 24h] → 끝 = 회의 끝
```

- X30(W08): 의뢰 → 이틀 작업 → 다음 날 의뢰자 주최 '구조해석 리뷰' 회의 → **E3c, 등급 C, 끝 = 회의 끝 10/14 11:00**, 회의 슬롯은 그 업무로. 원본 A·B 는 E3c 가 없었다.

### 4.8 확인 응답 반영(증거 키)

```text
for 응답 a in worklog(kind ∈ {instr, report}):
    후보 = 업무 중 (fam(a.ref) ∈ 문서군) ∨ (a.key == 업무 첫 근거 키) ∨ tok_sim(a.토큰, 업무 토큰) ≥ 0.5
    tk = 첫 진행 시각이 응답 시각에 가장 가까운 후보
    instr: 첫 차수 시작이 S2p·S2m 이면 S2M(응답 시각)            # 디지털 시작(S1·S1o·S2a)은 덮지 않는다
    report: 마지막 차수 끝이 없음·OPEN·E3i·E2l·NEXT_REQ·E3c 이면 E3M(응답 시각)   # 디지털 보고(E1)는 덮지 않는다
```

### 4.9 경계 확정

#### 4.9.1 시작

| 상황 | 시작 | 근거 |
|---|---|---|
| 디지털 의뢰 | 의뢰 수신 시각 | S1 (date-only 면 그날 표준창 시작, S1d) |
| 내가 보낸 지시 | 지시 발신 시각 | S1o |
| 디지털 의뢰 없이 수락 발신 | 수락 시각 | S2a |
| 확인 응답 | 응답 시각 | S2M |
| 의뢰자 동석 회의 | 회의 시작 | S2m |
| 그 밖 | 첫 진행 − s2PrePadMin(30분) | S2p |

- **선행 착수**(C 의 pre_request_h = B 의 S2r, 표기를 하나로): S1·S1o·S2a 업무의 첫 진행이 시작보다 preStartTolMin(60분) 넘게 앞서면 표식 '선행착수' + `pre_request_h` = 시작 전 귀속 시간. 리드타임은 **공식 시작부터** 잰다. W15: 전날 구두 예고 뒤 3h 선행 작업 → 투입 8.50h(선행 3.0h 포함), 리드 6.0h.

#### 4.9.2 완료 후보(E2) 점수 — 계산 규칙(must_fix: C 의 E2 는 입력 필드뿐이었다)

```text
completion(tk, cycle, nxt):                               # nxt = 다음 차수 시작(없으면 분석 시각)
  P_c   = 그 차수의 진행 시각;  tail_lo = max(P_c) − e2TailMin(120분)
  for f in tk.문서군(정렬):
      saves, exports, results = 그 차수 안 [시작, nxt) 의 사건;  fg = 그 안 전경 끝(자동 저장 문서만 사용)
      last = max(saves ∪ exports ∪ results ∪ (자동 저장 문서면 fg))
      if last < tail_lo: continue                          # 후보 뒤에도 그 업무 작업이 이어지면 종료가 아니다
      score = 0.4·[last → min(nxt, 분석 시각) 근무일 ≥ quietWd(3) (자동 저장 문서는 autosaveQuietWd)]
            + 0.3·[내보내기가 있고 마지막 저장 후 1일 안 (저장이 없으면 내보내기만으로)]
            + 0.2·[원 이름에 최종·final·v1.0·확정·완료·제출]
            + 0.3·[해석 결과 파일(연산 종료)]
            + 0.3·[last 후 7일 안 이 문서군을 첨부한 발신]
      후보 if score ≥ e2Low(0.5);  가장 늦은 last 의 후보 → (last, E2h if score ≥ e2High(0.7) else E2l)
```

- 단일 증거로는 E2 가 되지 않는다(조용함만 0.4). 조용함 + PDF 내보내기 = 0.7 = E2h. W02: 목 15:00 저장 → 15:05 PDF → 3근무일 조용 → **E2h 10/15 15:05, 등급 B**. 금 10:00 보고가 오면 E1 로 연장(W03, A).
- 자동 저장(M365 AutoSave) 문서의 '저장'은 완료가 아니다. 마지막 전경 편집을 last 로 쓰고 조용한 기간은 `autosaveQuietWd`(미보정)로 잰다(W43b).
- W42(밤샘 솔버): 결과 파일(04:00) + 조용함 = 0.7 이지만 다음 날 보고서 작업이 이어져 `e2TailMin` 에 걸린다 → E2 아님.

#### 4.9.3 NEXT_REQ — 조용한 기간 뒤 같은 화제 추가 요청

```text
for (ta, 추가 요청) in tk.추가지시(S1·ACK 업무):
    c = ta 를 포함하는 차수(끝 없음 또는 끝 > ta)
    before = c 안 ta 이전 진행
    if before ∧ before[-1] → ta 근무일 ≥ reopenQuietWd(3):
        c.끝 = E2 후보(있으면) 아니면 before[-1] + 30분 (NEXT_REQ);  새 차수 [ta, c 의 원래 끝) 삽입
```

- W16: 의뢰 → 이틀 작업 → (대면 보고) → 4근무일 조용 → 같은 스레드 '보완' 요청 → **차수 2개**(1차 NEXT_REQ, 2차 E3i), 리드 36.5h, 등급 D.

#### 4.9.4 종료 추론 순서

```text
for 끝이 없는 차수 c(다음 차수 시작 nxt):
    ps = c 안 진행 시각
    if E2 후보:                                    end = E2h/E2l
    elif E3c 회의:                                 end = 회의 끝
    elif ps ∧ ps[-1] → 분석 시각 근무일 ≥ dormantWd(5):
        if requireCommsCoverageForE3 ∧ (ps[-1] ~ 분석 시각) 안 mail_out·teams 커버리지 결손: OPEN 유지 + 큐 Q03(보류)
        else:                                      end = ps[-1] + e3PostPadMin(30분) (E3i)
    elif ps 없음 ∧ kind ∈ {S1, ACK, COORD} ∧ 첫 차수: 미착수(Z) — 업무 창 없음, 투입 0
    else:                                          OPEN(진행 중)
```

- W55: W07 과 같은 작업인데 그 뒤 메일 발신 수집이 막힌 날(blocked)이 있음 → E3i 대신 **OPEN + Q03**.
- 미착수 업무의 의뢰 수신 시각은 투입이 아니다(W10: 0.00h, Z). 의뢰 후 unstartedWd(10) 근무일이 지나면 큐 Q02.

### 4.10 시작·종료 조합표와 등급

#### 4.10.1 등급 산식

```text
SG = {S1: A, S1o: A, S1d: B, S2a: B, S2M: B, S2m: C, S2p: C}
EG = {E1: A, E1i: A, E1d: B, E2h: B, E3M: B, E2l: C, E3c: C, NEXT_REQ: D, E3i: D}
grade(sb, eb) = O                                   if eb == OPEN
              = worst(SG[sb], EG[eb])               (A < B < C < D < E)
                한 단계 강등 if sb ∈ {S2p, S2m} ∧ eb ∈ {E2l, E3i, NEXT_REQ}   # 양 끝 모두 추정
                = C if sb == S1d ∧ eb == E1d                                # 양 끝 모두 날짜만
업무 등급 = grade(첫 차수 시작, 마지막 차수 끝).  REPORT_ONLY = D, 미착수 = Z, 수동 기록 전용 = M
```

#### 4.10.2 조합표(시작 7 × 종료 9) — 표의 각 칸이 등급

| 시작 \ 종료 | E1 | E1i | E1d | E2h | E3M | E2l | E3c | NEXT_REQ | E3i | OPEN |
|---|---|---|---|---|---|---|---|---|---|---|
| **S1** 디지털 의뢰 | **A** | A | B | B | B | C | C | D | **D** | O |
| **S1o** 내 지시(조율형) | A | **A** | B | B | B | C | C | D | D | O |
| **S1d** 날짜만 의뢰 | B | B | **C** | B | B | C | C | D | D | O |
| **S2a** 수락 발신 | B | B | B | B | B | C | C | D | D | O |
| **S2M** 확인한 지시 | B | B | B | B | **B** | C | C | D | D | O |
| **S2m** 의뢰자 회의 | C | C | C | C | C | **D** | C | **E** | **E** | O |
| **S2p** 첫 진행 − 30분 | **C** | C | C | C | C | **D** | C | **E** | **E** | O |

등급 뜻: **A** 두 경계 모두 정밀한 디지털 근거 · **B** 한 경계가 산출 완료·날짜만·본인 확인·수락 · **C** 한 경계가 추정(S2) 또는 약한 완료·달력(E3c) · **D** 끝이 휴면 추정 또는 양 끝이 추정·약함 · **E** 양 끝 모두 추정. C·D·E 이고 투입 ≥ 0.5h 면 큐 Q01. 확인 응답(S2M·E3M)으로 등급이 오른다(W47a: E → B).

#### 4.10.3 사용자 요구 조합([업무시간]6·[단일업무시작/종료]) 처리표

| 요구 표현 | 관측 | 시작 | 종료 | 등급 | 투입 | 확인 큐 | 시나리오 |
|---|---|---|---|---|---|---|---|
| 시작_1 + 종료_1 | 의뢰 + 보고 | 의뢰 시각 | 보고 시각(보완 보고면 마지막) | A | Σ귀속 | – | W01, W13, W17, W18 |
| 시작_1 + 종료_2 | 의뢰 + 완료 후보 | 의뢰 시각 | 완료 시각(뒤에 보고 오면 보고로 연장) | B(강)/C(약) | Σ귀속 | C 면 Q01 | W02, W03 |
| 시작_1 + 종료_3 | 의뢰 + 대면 보고 | 의뢰 시각 | 의뢰자 리뷰 회의 끝(E3c) / 5근무일 조용 → 마지막 진행 + 30분(E3i) / 확인 응답(E3M) | C / D / B | Σ귀속 | Q01 | W07, W08, W47b |
| 시작_2 + 종료_1 | 대면 지시 + 보고 | 의뢰자 회의(S2m) / 수락 발신(S2a) / 첫 진행 − 30분(S2p) / 확인(S2M) | 보고 | C / B / C / B | Σ귀속 | C 면 Q01 | W04, W05, W14, W11 |
| 시작_2 + 종료_2 | 대면 지시 + 완료 | 위와 같음 | 완료 시각 | C(강)·D(약) | Σ귀속 | Q01 | W06, W43b |
| 시작_2 + 종료_3 | 둘 다 대면 | 위와 같음 | E3c / E3i / E3M | C / E / B | Σ귀속(MM 손실 0) | Q01 | W09, W47a |
| 시작만 | 의뢰, 진행 없음 | 의뢰 시각 | 없음 | Z | **0** | 10근무일 뒤 Q02 | W10, W25 |
| 종료만(진행 있음) | 보고 + 그 첨부 문서 작업 | 첫 진행 − 30분 | 보고 | C | Σ귀속 | Q01 | W11 |
| 종료만(진행 없음) | 보고만 | 보고 직전 창 | 보고 | D(REPORT_ONLY) | 직전 창 + 공백 라벨 | Q01 | W12, W38 |
| 둘 다 없음 | 문서·앱 작업만 | 첫 진행 − 30분 | E2 / 휴면 E3i / 진행 중 | C·D / E / O | Σ귀속 | Q01 | W09, W26, W42 |
| 재의뢰·수정 반복 | 보고 뒤 같은 화제 요청(10근무일 안) | 차수별 | 차수별 | 첫 시작 × 마지막 끝 | 누적 | – | W13 |
| 조용한 뒤 추가 요청 | 보고 없이 3근무일 조용 → 같은 화제 요청 | 차수별 | NEXT_REQ / … | 〃 | 누적 | Q01 | W16 |
| 선행 착수 | 공식 의뢰 전 작업 | 공식 의뢰(리드 기준) | – | 의뢰 기준 | 선행분 포함(pre_request_h) | – | W15 |
| 조율형 | 내 지시 + 받은 보고(+전달) | S1o | E1i(전달 보고면 연장) | A | 내 발신·검토 슬롯만 | – | W19 |
| 다대다 | 보고 1통이 의뢰 여러 건 | 각 의뢰 | 같은 보고 | 각자 | 각자 | – | W18 |
| 날짜만 의뢰·보고 | 웹·코파일럿 date-only | 그날 표준창 시작 | 그날 표준창 끝 | B 이하(양끝 날짜 C) | Σ귀속 | – | (규칙) |
| 코파일럿 요약만 | summary | 경계 아님 | 경계 아님 | – | 0 | Q07 | (규칙) |

### 4.11 업무 ID 와 팀 묶음 코드 대응

- 업무 ID(TEAM R-4): `unit_id = "u_" + keyed(kr, "unit", <시작 근거 키>, 10)` — PRIVACY §9.3 의 목적별 하위 키 함수(purpose `unit`), 형식 `^u_[0-9a-f]{10}$`. **시작 근거 키** = S1·S1d·S1o·ACK 업무는 그 메시지의 `msg_key`, SELF 는 가장 이른 구간의 `fam_key|날짜`, APP 는 `app:<app_id>|날짜`, REPORT_ONLY 는 보고 `msg_key`, MANUAL 은 `manual:<ref>`. 같은 입력이면 같은 ID(관문 G2), 재분석해도 같은 단위업무면 같은 값. (참조 구현은 시뮬레이터 키로 같은 구조의 HMAC 을 쓴다.)
- 팀 묶음(`TEAM_AND_BUNDLE.md` LM27 판 §2.3 `units[]`, `start.kind ∈ {S1i, S1o, S2, M}`, `end.kind ∈ {E1o, E1i, E2, E3c, M, null}`, `precision ∈ exact·minute·date·none`) 코드 대응. 근거 종류 열거는 이 문서 소관이며(팀 명세 '늘리면 MINOR'), **`end.kind` 에 `E3i` 를 추가한다**(휴면 추정·NEXT_REQ 종료를 담을 칸이 없다 — 팀 스키마 MINOR 판 올림 요청, §11.3).

| 시간 코어 | 팀 묶음 |
|---|---|
| 시작 S1 / S1d | `start.kind = "S1i"`, `precision` = exact·minute / date |
| 시작 S1o | `start.kind = "S1o"`, precision exact·minute |
| 시작 S2a · S2m · S2p | `start.kind = "S2"`, precision exact(S2a·S2m) / none(S2p) |
| 시작 S2M | `start.kind = "M"`(본인 확인), precision exact |
| 종료 E1 / E1d | `end.kind = "E1o"`, precision exact·minute / date |
| 종료 E1i | `end.kind = "E1i"` |
| 종료 E2h · E2l | `end.kind = "E2"`, precision exact |
| 종료 E3c | `end.kind = "E3c"`, precision exact |
| 종료 E3M | `end.kind = "M"`, precision exact |
| 종료 E3i · NEXT_REQ | `end.kind = "E3i"`(**추가**), precision none |
| 종료 OPEN | `end = null` |
| 등급 A~E | `grade` 그대로 |
| 등급 O(진행 중) | `grade` = SG[시작](잠정), `status = "open"` |
| 상태 | `closed`(E1·E1d·E1i·E2h·E3M·E3c), `estimated`(E2l·E3i·NEXT_REQ), `open` |
| 미착수 Z·투입 0 업무 | 팀 묶음에 올리지 않는다(개인 보고서 '미착수 의뢰' 목록에만) |
| 버킷 5종 | `alloc_daily` 에 넣지 않는다 = `unattributed_min`(팀 R-3) |
| `gantt_spans` | `lead` 띠 정확히 1개 = [첫 차수 시작, 마지막 차수 끝(진행 중이면 분석 시각)]; `active` = 귀속 슬롯이 있는 날을 이어 붙인 묶음(투입 밀도) |

---

## 5. 귀속과 보존 법칙

### 5.1 보존 법칙(요구 [업무시간]8)

- 봉투 슬롯 하나는 **정수 300초**다. 귀속은 그 300초를 단위업무·버킷에 정수 초로 나누기만 한다. 같은 시각에 업무가 몇 개 열려 있어도 그 슬롯은 300초다. 그래서 병행 업무로 MM 이 부풀 수 없다.
- 날마다 `assert Σ귀속 초 == 300 × 봉투 슬롯 수`. 실패는 코드 결함이므로 분석을 멈춘다(fail-closed).
- 나누기는 최대잉여법 `split_int(300, 가중)`(동률은 키 사전순)으로 Σ = 300 을 정확히 보장한다. C 의 실수 분수 귀속(1/3, 0.5×5/len)은 쓰지 않는다(must_fix [정수 보존]).
- 병행 3업무를 30분 단위로 교차 편집한 날(W54): X 3.00 + Y 2.50 + Z 2.50 = 8.00h = 그날 봉투. 리드타임 합(93.0h)이 투입보다 훨씬 커도 투입 합은 봉투를 넘지 않는다.

### 5.2 업무 창과 문서 사건의 업무 결정(resolve)

```text
업무 창(tk) = ∪ 차수 [시작, 끝 + pad]   pad = postPadMin(30분) if 끝 ∈ {E1, E1d, E1i, E2h, E2l, E3c} else 0
              (E3i 는 이미 +30분, E3M 은 확인 시각, NEXT_REQ 는 이미 +30분) · OPEN → 분석 시각 · 미착수 차수 → 창 없음
resolve(f, t):                                   # 문서군 f 의 시각 t 사건이 어느 업무 것인가
    sg = t 를 담은(없으면 가장 가까운) f 의 구간
    if sg 미연결: None        if sg.shared: 'B_GENERIC'
    inwin = sg 에 연결된 업무 중 창이 t 를 포함하는 것
    if inwin: 그중 연결 강도 최대인 업무들(동률이면 **균등 분할** — '최근 시작'으로 쏠리지 않음)
    elif t 이전에 시작한 연결 업무: 시작이 가장 늦은 것(창 밖 편집, 표식)
    else: 시작이 가장 이른 것(표식 '선행')
```

### 5.3 우선순위 사슬 L1~L7

```text
for 봉투 슬롯 s(시각순):
  L1 수동    : 시각 있는 수동 work(또는 시각 없는 기록이 배치된 슬롯) → ref 업무(없으면 MANUAL 업무) 300초
  L2 회의    : 회의가 슬롯을 ≥150초 덮음 → 대상 = 연결 업무 또는 B_MEET
               o = 그 슬롯의 다른 업무 L3 초
               불참 의심(회의 전체 슬롯의 다른 업무 L3 초 합 ≥ meetAbsentCover(0.9) × 회의 길이, 'attended' 응답 없음):
                     L3 업무가 자기 초를, 회의가 나머지를 갖는다 + 큐 Q14            [L2회의(불참의심)]
               elif o > 0 ∧ 참석 ≥ meetSplitMinAtt(6명): 다른 업무 o × meetSplitShare(0.5), 회의 나머지  [L2회의(대형분할)]
               else 회의 300초                                                                 [L2회의]
  L3 PC 맥락 : 슬롯 안 능동 표본 조각(사적 제외)을 초 단위로 훑는다
               · 같은 초에 여러 PC 가 능동이면: 원격 데스크톱 클라이언트(cls=remote) 조각은 다른 PC 관측이 있으면 버림(대상 PC 에 양보)
                 → 유휴(idle_sec)가 가장 짧은 PC(최근 입력 장치) → 동률이면 PC 끼리 균등
               · 조각 대상: 문서 키 → resolve(f, t) / 문서 키 없는 공학 앱 → APP 업무 / 메일·채팅·회의 창 → '소통' 관측 /
                 그 밖(브라우저·탐색기·기타·원격 미양보) → '일반' 관측 / 공용 문서 → '공용' 관측
               · 점 사건(저장·내보내기·커밋)은 그 업무에 pointWeightSec(60초) 가중
               업무 가중이 있으면 split_int(300, 업무별 초)                                    [L3PC]
  L4 앵커    : 직전 창 세션 겹침 초 — 발신 → 상태기계가 정한 업무(없으면 첨부 resolve), 저장·제출·커밋 → resolve [L4앵커]
               (솔버 cap 옵션 슬롯 C12 → 그 연산의 업무)                                         [L4솔버cap]
  ── 여기까지가 '직접'. 나머지 슬롯은 봉투 연속 구간 안의 '빈 블록' 단위로:
  L5a 흡수   : 블록 유형 ⊆ {일반, 소통} 이고 길이 ≤ absorbGenericMaxMin(10분), 양쪽이 같은 단일 업무 → 그 업무        [L5흡수]
               블록 전체가 어떤 업무의 연산 중(solverAbsorbGeneric) → 그 업무(솔버 대기 중 일반 앱)              [L5솔버흡수]
  L5b 공백   : 블록 유형 = PC 밖(다리·흔적 창, C1b·C4L·C6·C7·C10·C10r)
               한쪽 이상 직접 이웃 있음: 길이 ≤ gapSplitMaxMin(30분) → 중점 분할(앞 절반 = 왼쪽 분포, 뒤 = 오른쪽; 한쪽뿐이면 그쪽)
                                         길이 > 30분 → 양쪽이 같은 단일 업무면 그 업무, 아니면 B_OFFPC          [L5공백]
               이웃 없음: B_OFFPC
  L5c 하한근접: 유형 = 미상(PC 하한 C8·C9) 슬롯은 floorNearMin(30분) 안의 가장 가까운 단일 업무 이웃              [L5하한근접]
  L6 비례    : 남은 슬롯(공용 문서 관측 슬롯 제외) — 그 시각 창이 열렸고 그날 직접 초 D_tk > 0 인 업무들에
               split_int(300, D_tk 비례), 업무별 그날 L6 누적 ≤ l6MaxRatio(1.0) × D_tk, 넘치는 초 → 슬롯 유형 버킷     [L6비례]
  L7 버킷    : 그 밖 → 슬롯 유형 버킷(공용 문서 관측 슬롯 → B_GENERIC)                                          [L7버킷]
assert 날마다 Σ초 = 300 × 슬롯 수
```

- **사슬 순서의 이유**: L1 사람이 명시 > L2 달력으로 관측된 협업 > L3 전경 문서·앱(가장 정밀) > L4 발신·저장의 함의 시간 > L5 이웃 맥락 > L6 직접 증거 비례(결정 v2 '무증거 슬롯 배분: 직접 증거 분 비례, 없으면 미귀속') > L7 버킷.
- **회의 혼합(MIX)**: A 의 '8인 이상 + 180초 이상'과 C 의 '6인 이상 0.5/0.5'를 하나로 묶었다(설정 `time.attrib.meetSplitMinAtt`·`meetSplitShare`). 소형 회의 중 PC 사용은 회의 참여(메모·자료 띄우기)로 본다. W41: 30명 설명회 중 문서Y 40분 → 문서Y 0.34h + 설명회 0.66h, 4명 주간회의 중 문서Y 20분 → 회의 1.00h.
- **불참 의심**(extra): 수락 회의 10~11시 동안 노트북에서 다른 업무 능동 입력 60분 → 봉투 1h(이중 계산 없음), 귀속은 PC 업무, 큐 Q14(W44). 사용자가 '참석'으로 답하면(`attended`) 회의 귀속으로 돌아간다.
- **여러 PC·RDP**: 봉투는 합집합이라 두 PC 가 동시에 활성이어도 1분은 1분이다. 귀속은 최근 입력 PC 의 맥락을 따른다. W40: 데스크톱 09~10 문서A, 10~12 원격창(→클라우드PC 문서B), 노트북 13~18 문서A → 봉투 8.00h = 문서A 6.00 + 문서B 2.00(4h 이중 계산 없음).
- **공백 라벨**(C 접목): 원본 A 의 L5(양쪽 45분 안 가까운 쪽 복사)를 대체했다. 30분 넘는 PC 밖 공백은 앞뒤가 같은 업무가 아니면 지어내지 않고 B_OFFPC 로 둔다.
- **L6 상한**: 추정 배분은 그날 직접 증거보다 클 수 없다(상한 1.0, 미보정). LM24 V25: 직접 A 3h·B 1h + 무증거 브라우저 4h → **A 6h·B 2h**(W56).
- **증거 추가의 영향**: 무관한 업무에 증거를 더해도 다른 업무의 직접 귀속(L1~L4)은 변하지 않는다. 변하는 것은 L5·L6 분배뿐이고 원장에 그 단계가 표시된다. LM24 의 '가중치×건수 share' 는 증거 하나가 모든 비율을 흔들었다.

### 5.4 버킷 5종('근무 중 미분류')과 귀속률

| 버킷 | 슬롯 유형(그 슬롯의 주된 관측) | 계층 롤업 |
|---|---|---|
| `B_GENERIC` | 일반 앱(웹·탐색기·기타) 관측, 공용 문서, 무연결 저장 | 근무 중 미분류 |
| `B_COMM` | 무연결 메일·채팅 창, 무연결 발신 직전 창, 수신 크레딧(C5) | 근무 중 미분류(소통) |
| `B_MEET` | 어느 업무에도 연결되지 않은 회의 | 근무 중 미분류(회의). 회의 시리즈 키를 남겨 롤업 단계에서 레지스트리 키워드로 **과제에 직접** 귀속할 수 있다(단위업무는 만들지 않음) |
| `B_OFFPC` | 30분 넘는 PC 밖 공백(앞뒤 업무 다름), 이웃 없는 흔적 창·다리 | 근무 중 미분류(PC 밖) |
| `B_UNKNOWN` | PC 하한(C8·C8d·C9)·솔버 cap 중 이웃 업무가 없는 부분 | 근무 중 미분류(미상) |

- 버킷은 숨기지 않는다. 보고서 KPI 로 **귀속률 = 1 − Σ버킷 / 봉투**를 보인다. 연속 60분 이상 버킷 블록은 큐 Q17(후보 업무 상위 3개 제시).

### 5.5 병행도 · 리드타임 · 투입

- 업무별 **투입** = Σ 귀속 초. 레벨별(L1~L7) 내역을 함께 남긴다(설명 원장).
- **리드타임** = Σ차수(끝 − 시작). **영업 리드** = 그 구간 안 정규 구역 시간. 미착수·진행 중은 리드 없음(진행 중은 '경과'만 표시).
- **병행도**: 업무별 = 그 업무가 귀속받은 슬롯에서 창이 열린 업무 수의 평균. 사람별 = 슬롯당 열린 업무 수 분포. 병행도 > parallelMax(5) 면 큐 Q12('분할 과다 의심'). 개인 보고서에는 리드타임·투입·병행도를 나란히 보여 '오래 걸렸지만 투입은 작다(병행)'를 구별한다.
- 간트(결정 메모 §10.2): 옅은 **리드타임 띠**(차수 [시작, 끝]) 위에 진한 **투입 밀도 칸**(귀속 슬롯이 있는 날), 행 끝에 투입 h·병행도·리드타임. 막대 길이는 투입이 아니다.

### 5.6 정수 분 표(개인 = 팀, TEAM R-3)

```text
team_tables(slots, assign, days):
    env_min[(d, tag)] = 5 × 그 (날짜, 꼬리표) 슬롯 수                         # envelope_daily
    for (d, tag): sec[t] = 그 칸 슬롯들의 업무·버킷별 초 합
                  mins = split_int(env_min[(d, tag)], sec)                  # 최대잉여법 → Σ = env_min 정확
                  alloc[(d, unit, tag)] = mins[unit] (버킷은 넣지 않음 = unattributed)
    assert Σ_unit alloc[(d, ·, tag)] ≤ env_min[(d, tag)]
```

- 개인 보고서의 숫자도 **이 정수 분 표에서** 낸다. 그래야 개인 MM 과 팀 서버 재합산 MM 이 정수 분까지 같다(관문 G5: 시나리오 83개 + 퍼즈 12,000 실행 전부 완전 일치).

---

## 6. MM · 초과 산식

### 6.1 분모·MM·업무 MM·계층 롤업

```text
W(m)      = 그 달 근무일 = 평일 − 공휴일 − 회사 휴무(calendar.json)          # mm.denominator='workdays'(기본)
            (옵션 mm.denominator='weekdays' = 공휴일을 빼지 않은 달력 평일 — 사용자 확인 항목, 화면에 분모 정의 표시)
D(m)      = mm.stdDayMin(480분, 팀 레지스트리 calendar.std_day_min 우선) × W(m)
E(m)      = 그 달 봉투 분(슬롯 시작 시각의 날짜 기준)
MM(m)     = E(m) / D(m)                                                      # 상한 없음 — 1.0 초과 허용
MM(m, u)  = Σ 그 달 u 귀속 분 / D(m);   Σ_u MM(m, u) + MM(m, 버킷) = MM(m)  # 정확히(정수 분)
MM(m, x)  = Σ_{u ∈ x} MM(m, u)        x = 역할 업무 / 과제 / 업무 영역 / 업무 유형(라벨 없음 → '미분류', 숨기지 않음)
기간 MM   = Σ_m MM(m)                  # 기간 평일로 나누지 않는다(부분월 부풀림 금지, LM24 3개월 → 4.0MM 함정)
```

- 2026-09·2026-10: W = 20, D = 160h.

### 6.2 꼬리표·초과(정규·연장·야간·휴일)

- 꼬리표는 §3.13(배타, 슬롯 단위). Σ꼬리표 h = E(m).
- **초과 h** = 연장 + 야간 + 휴일(`mm.overtimeBasis = 'window'`, 기본).
- 옵션 `mm.overtimeBasis = 'daily8h'`: 초과 = Σ_평일 max(0, 일 h − 8) + 휴일 h(정규창 밖에서 일하고 창 안에서 쉰 날은 window 기준과 다르다). 두 값을 모두 계산해 결과에 싣고(`overtime_window_h`, `overtime_daily8h_h`) 화면에는 설정한 쪽을 쓴다. 법정 연장(주 40h 초과) 기준이 필요하면 사용자 결정(§11).
- 휴일 중 야간은 보조 집계(`holiday_night_h`), 휴가 중 근무는 `on_leave_h`(연장으로 집계 + 큐 Q16).

### 6.3 월 경계와 자정

- 슬롯은 **시작 시각의 달력 날짜**에 속하고 그 날짜의 달에 속한다. 단위업무가 달을 넘으면 귀속은 슬롯의 달로 나뉘고, 리드타임은 단위업무 단위로 **한 번만** 낸다(그 업무가 끝난 달의 표에 싣고, 진행 중이면 경과로만).
- W46: 9/30 23:00~10/1 01:30 같은 문서 + 01:20 보고 → **9월 야간 1.0h, 10월 야간 1.5h**. 정수 분 표: (9/30, 정규) 480·(9/30, 야간) 60·(10/1, 야간) 90. 업무 리드 15.33h 는 한 번만.

### 6.4 부재 · 가용 · 로드율

```text
avail(m) = Σ_{d ∈ m, 근무일, 분석 기간 안, d ≤ 분석 날짜} max(0, frac(d) − min(frac(d), 부재(d)))
           frac(오늘) = 표준창 경과 비율(mm.todayFraction), 미래 근무일 = 0
           부재: 연차 1.0 · 반차 0.5 · 확인된 부재(absence 응답) 1.0
           추정 부재(근거 0 평일): mm.inferredAbsence='confirm_only'(기본) → 빼지 않고 큐 Q09 만 / 'exclude' → 1.0 으로 뺀다
load(m)  = E(m) / (mm.stdDayMin × avail(m))     avail = 0 이면 None('가용 0' 표기, 합계에서 제외)
```

- 휴가 중 근무는 봉투에 넣는다(꼬리표 연장 + on_leave). 부재일 수는 줄이지 않는다.
- 개인·팀이 같은 규칙을 쓴다(LM24 개인 '분모 제외' 대 팀 '미포함' 이원화 폐기, R10).

### 6.5 예

| 시나리오 | 입력 | 결과 |
|---|---|---|
| W51 월 MM | 2026-09 근무일 20일: 평일 8h, 9/8·9/15 연장 2h, 토 9/19 4h, 9/22 야간 22~24, 9/10 연차, 9/17 오후 반차 | 봉투 **158.00h** = 정규 148 + 연장 4 + 야간 2 + 휴일 4. **MM = 158/160 = 0.9875**, 초과 10h, 가용 18.5일, **로드 = 158/148 = 1.068** |
| (참고) 원본 A S35 입력을 바른 달력으로 | 9/28 를 대체공휴일로 잘못 둔 원본: MM 0.987(150/152)·로드 1.071 | 바른 달력: **MM 0.9375(150/160), 로드 1.014(150/148)** — 골든 값은 이 달력으로 다시 만든다 |
| W64 부분월 | 10/1~10/14 분석, 분석 시각 10/14 13:30, 평일 8h + 오늘 오전 | 봉투 59.33h, **MM 0.371**(분모는 그 달 전체 160h — 부분월을 부풀리지 않음), 가용 7.5일(오늘 0.5일), 로드 0.989 |
| W52 연차·반차 | 연차 10/22 + 15:00 휴대폰 발신, 오후 반차 10/23 + 오전 근무 | 4.33h(정규 4 + 연장 0.33), 가용 0.5일, Q04·Q16 |

### 6.6 팀 재합산 항등식(관문 G5)

```text
개인 MM(p, m) = Σ envelope_daily(p, m) / (stdDayMin × W(m))      (팀 서버가 같은 달력·같은 코어로 다시 계산)
I1 일 보존: 모든 (p, d, tag) Σ_u alloc ≤ envelope, 차 = 미귀속
I2 개인 = 팀: 묶음 summary.mm == 재합산 MM (|Δ| ≤ 1e-9, 달력 버전이 같을 때)
I3 계층 보존: Σ_영역 MM + 미귀속 MM == MM
I6 effort: units[].effort_min == Σ 그 unit 의 alloc
```

---

## 7. 신뢰도 등급 · 확인 큐 · 설명 원장

### 7.1 슬롯 신뢰와 분 등급

| 슬롯 근거(basis) | 신뢰 |
|---|---|
| C11(확인)·C11u·C2·C1·C3 | high |
| C1b·C4·C4L·C5·C6·C7 | mid |
| C8·C8d·C9·C10·C10r·C12 | low |

- 구간 원장의 분 등급: **O** = 관측 귀속(L1 수동·L2 회의·L3 PC), **I** = 추정 귀속(L2 분할·L4·L5·L6), **X** = 버킷.
- 보고서는 관측(O)과 추정(I)을 시각적으로 구분하고(결정 메모 §8), 날짜별 'low 비중'을 표시한다.

### 7.2 업무 등급·상태

- 등급 A~E·O·Z·M(§4.10). 상태 `closed`·`estimated`·`open`·`not_started`.
- 개인 보고서의 단위업무 행: `등급 · 시작 근거(코드·시각·근거 키) → 종료 근거 · 리드(영업 리드) · 투입(L1~L7 내역) · 병행도 · 기계 시간 · 선행 착수 h · 표식`.

### 7.3 확인 큐

| 코드 | 이름 | 발생 조건 | 묻는 것(선택지) | 응답 → 저장(`Man`) |
|---|---|---|---|---|
| Q01 | 경계확인 | 등급 C·D·E ∧ 투입 ≥ minEffortH(0.5h) | 언제 지시받았나 / 언제 보고했나 / 같은 업무 합치기 | instr / report(S2M·E3M), must_link |
| Q02 | 미착수의뢰 | 미착수(Z) ∧ 의뢰 후 ≥ unstartedWd(10) 근무일 | 착수 안 함 / 다른 업무에 포함 / 오프라인 처리(시각·h) | must_link / work |
| Q03 | 오래열림·보류 | OPEN ≥ openLongWd(20) 근무일, 또는 커버리지 결손으로 E3 보류 | 끝났나(시각) / 진행 중 | report |
| Q04 | 원격발신 | 창 밖 C4(PC 밖 발신) | 업무로 보냈나 / 사적 | (승인) / exclude |
| Q05 | 흔적창·미등록외근 | C10·C10r 이 하한 밖으로 더해진 날 | 외근·출장·현장이었나(시각) / 정정 | offsite·work / exclude |
| Q06 | date-only 게이트 | (옵션) C8d 사용일 | 근무했나·몇 h | work / exclude |
| Q07 | 요약근거 | 코파일럿 summary 신호 | 가리키는 의뢰·보고 시각 | instr / report |
| Q08 | 근무창공백 | 근무일 정규 구역 안 무근거 ≥ gapMin(90분) | 오프라인 업무였나(시각·업무) | work |
| Q09 | 추정부재 | 평일, 봉투 0, 표식 없음(존재 증거만 있으면 그 건수 표시) | 부재였나 / 근무(수동 입력) | absence / work |
| Q10 | 장시간일 | 하루 봉투 > longDayH(16h) | 맞나 | (확인) / exclude |
| Q11 | 솔버대량 | 업무 machine_s > solverDayH(8h) | 결과 확인 시간 기록(선택) | work |
| Q12 | 분할제안·분할과다 | 거대 성분 가드, 병행도 > parallelMax | 나눌까요 / 합칠까요 | cannot_link / must_link |
| Q13 | UTC의심 | 발신 60% 이상이 00~08시 | 그 경로가 UTC 저장인가 | mailTimeOffsetH 설정(경로 utc 표식) |
| Q14 | 회의불참의심 | 회의 중 다른 업무 PC 능동 ≥ 90% | 참석했나 | attended / (그대로) |
| Q15 | 미정회의 | tentative ∧ 회의 창 근거 부족 | 참석했나 | attended(→ 산입) |
| Q16 | 휴가중근무 | 연차·반차 시간에 봉투 | 근무 맞나 | (확인) / exclude |
| Q17 | 미귀속블록 | 버킷 연속 ≥ bucketRunMin(60분) | 어느 업무(후보 3개) / 개인 시간 | work(ref) / exclude |
| Q18 | 공용문서의심 | 공용 문서 자동 판정 | 공용 문서로 등록 / 특정 업무 것 | 레지스트리 공용 표식 / must_link |

- **qid** = `sha1(유형 | 대상 | 핵심 근거)[:12]` — 재분석해도 같은 질문은 같은 ID(두 번 묻지 않는다).
- **우선순위** = (영향 h + 0.01) × 유형 가중(Q01·Q09·Q13 1.0, Q05·Q06 0.9, Q03 0.8, Q08 0.7, Q04·Q14·Q17 0.6, Q10·Q16·Q18 0.5, Q12·Q15 0.4, Q02 0.3, Q07 0.2, Q11 0.1). ISO 주마다 상위 `maxPerWeek`(15) 건만 띄운다.
- 응답 전의 추정은 등급·신뢰와 함께 그대로 산출한다. 자동 승인은 없다. 다른 사용자에게 수동 조작을 요구하지 않는다(본인 보고서 화면에서만).
- 코파일럿에는 확인된 요약(등급·라벨·h)만 보낸다. 시간 계산은 맡기지 않는다.

### 7.4 설명 원장

**날짜 원장**(A, 구성요소 기여·차감·제외·꼬리표):

```text
2026-10-26 9.83h = 샘플러 9.33 + 샘플러다리 0.50 | - | 야간 1.83 · 정규 8.00
2026-10-27 2.00h = 샘플러 1.92 + 앵커세션 0.08 | 잠금단절_다리없음 −0.75 | 야간 2.00          (W28)
2026-10-20 7.50h = 샘플러 7.50 | 사적차감 −0.50 | 정규 7.50                                   (W48)
2026-10-14 8.00h = 샘플러 8.00 | 창밖_무자격_제외 −1.00 | 정규 8.00                            (W26)
```

**구간 원장**(C, 같은 출처·귀속·등급이 이어지는 구간을 한 줄로 — 버린 시간도 숫자로):

```text
2026-10-14 (W41, 회의 혼합)
  09:00~10:00 정규 샘플러   SELF:문서x_과제a [O]
  10:00~10:35 정규 회의     B_MEET×0.50+SELF:문서y_과제b×0.50 [I]      ← 30명 설명회 중 다른 업무 PC 입력(0.5/0.5)
  10:40~11:00 정규 회의     B_MEET [X]
  14:00~15:00 정규 회의     B_MEET [X]                                  ← 4명 회의 중 PC 사용 = 회의 참여
2026-10-28 (W61, 원격 연결 다리)
  22:00~22:50 야간 샘플러   SELF:대응방안_고객사a [O]
  22:50~23:50 야간 원격연결다리 SELF:대응방안_고객사a [I]               ← 같은 문서 첨부 원격 회신까지 60분 안
  23:50~00:00 야간 원격발신  SELF:대응방안_고객사a [I]
2026-10-16 (W38, PC 기록 없는 외근일)
  09:30~09:45 정규 흔적창    B_OFFPC [X]
  09:45~10:05 정규 원격발신  B_COMM [X]                                  ← 무연결 정보 발신
  14:45~15:05 정규 원격발신  REPORT:M9c [I]
  15:05~15:30 정규 흔적창    REPORT:M9c [I]                               ← 30분 이하 공백 = 이웃 업무
```

**업무 원장**:

```text
S1:chat_p31#1  A  S1 10-13 10:00(msg m1) → E1 10-13 14:00(msg m4) | 리드 4.0h(영업 3.0) | 투입 3.17h = L3 2.83 + L4 0.33 | 표식 수락 10:02
```

원장 규칙: 숫자는 모두 정수 초·분에서 파생한다. 근거는 키(ev_id·msg_key·doc_key 해시·회의 ID)만 남기고 본문·제목 원문은 없다(PII 카나리아 관문 G8). 화면은 로컬에서만 키를 정제된 제목으로 풀어 보인다.

### 7.5 결과 파일(분석 1회, `data\analysis\<run_id>\time\`)

| 파일 | 내용 |
|---|---|
| `env_slots.jsonl` | 슬롯 행 `{date, slot, tag, basis, conf, on_leave, pcs}` |
| `day_ledger.jsonl` | 날짜 원장(구성요소 기여·차감·제외·꼬리표·신뢰 비중·커버리지·표식) |
| `interval_ledger.jsonl` | 구간 원장 |
| `tasks.json` | 단위업무(차수·근거 키·등급·상태·리드·투입·레벨 내역·병행도·기계·선행·표식·라벨) |
| `attrib.jsonl` | 슬롯 귀속 `{slot, target, sec, level}` |
| `team_tables.json` | 정수 분 표(envelope_daily·alloc_daily) — 팀 묶음 빌더 입력 |
| `mm_month.json` | 월 MM·꼬리표·초과(두 기준)·가용·로드·업무 MM·롤업 |
| `confirm_queue.json` | 확인 큐(qid·유형·대상·영향 h·근거 키·제안) |
| `run_meta.json` | core_version · calendar_version · cfg_used(읽힌 키와 값) · as_of · 입력 다이제스트 · audit(버린 건수) · 경고 |

---

## 8. 파라미터 표

### 8.1 레지스트리 규약

- 모든 키는 단일 설정 레지스트리(`lm27/time/registry.py`, 직렬화 `config/schema_time.json`)에 있다. 네임스페이스는 `time.*`(시간대·근무창·봉투·귀속·확인 큐) · `episode.*`(단위업무) · `mm.*`(MM) 이고, 사적 사용 문턱 2개는 PRIVACY.md 가 소유하는 `privacy.time.*` 를 그대로 읽는다.
- **미등록 키는 오류**(오타·죽은 키 차단), 형이 틀린 값은 기본값 + 경고(`run_meta.warnings`). 실제로 읽힌 키와 값을 `run_meta.cfg_used` 에 남긴다(관문 G6).
- ★ = **미보정**(실측 근거 없는 정책값). §8.3 보정 도구의 대상이며 화면 설정 옆에 '미보정' 표식을 단다(결정 메모 §10.2).
- 슬롯 길이 300초는 상수다(설정 아님 — 팀 R-3 정수 분 표의 바닥).

### 8.2 키 · 기본값 · 근거

#### 8.2.1 시간대·근무창(`time.window.*`, 개인 프로필이 덮어쓴다)

| 키 | 기본 | 단위 | 근거 |
|---|---|---|---|
| `time.tzOffsetMin` | 540 | 분 | 근무 시간대 오프셋(+09:00). zoneinfo 금지(결정 메모 §10.3) |
| `time.slotCoverSec` | 150 | 초 | 슬롯 절반 이상 덮임 = 반올림 무편향 |
| `time.window.std` | 09:00-18:00 | 시각 | 결정 메모 §5 표준창. 시차 근무는 개인 설정(창 밖 무조건 인정 flex 는 폐기) |
| `time.window.lunch` | 12:00-13:00 | 시각 | LM24 A35. 흔적 없으면 하한·다리에서 뺀다 |
| `time.window.dinner` | 18:00-18:30 | 시각 | LM24 A33. 흔적 없으면 다리·직전 창에서 뺀다 |
| `time.window.night` | 22:00-06:00 | 시각 | 법정 야간(수집 경계 08/19 와 분리) |
| `time.window.halfAmOff` / `halfPmOff` | 09:00-14:00 / 14:00-18:00 | 시각 | 반차 4h(점심 포함 창) |
| `time.window.weekdays` | 0,1,2,3,4 | 요일 | 월~금(달력 calendar.json 의 weekdays 와 같아야 함) |

#### 8.2.2 근무 봉투(`time.envelope.*`)

| 키 | 기본 | 단위 | 근거 / 민감도 |
|---|---|---|---|
| `stuckCoverH` / `stuckIdleRatio` | 14 / 0.02 | h / 비 | LM24 A1(TickCount 고착), (PC, 날) 단위 판정 |
| `samplerBridgeMin` ★ | 60 | 분 | LM24 K7 샘플러 공백 다리. 창 밖은 잠금을 잇지 않음 |
| `sessionGapMin` ★ | 45 | 분 | LM24 K2 능동끼리 다리(조각 vs 과대 절충) |
| `pcBridgeMin` ★ | 120 | 분 | V9(새벽 90분 공백 연결)과 E1(퇴근 후 200분 재개 차단) 사이 |
| `lockBreakMin` ★ | 15 | 분 | 창 밖 전 PC 잠금이 이만큼 이어지면 다리 없음(B bridge45 접목 금지) |
| `preWindowMin` ★ | 메일 20 · 팀즈 10 · 파일 30 · 코드 45 · 커밋 45 · 제출 30 | 분 | 최소 크레딧 직전 창(LM24 LONE 20/10/60/90 의 '작성 후 발신' 비대칭판, B·C 공통) |
| `tracePadMin` | 5 | 분 | 흔적 폭(LM24 A33). 식사 판정은 앵커 직전 5분만 |
| `trimEdgesMin` | 10 | 분 | 하한 양끝 다듬기(출근 전·퇴근 후 켜 둔 시간) |
| `alwaysOnH` | 20 | h | 항상 켜진 PC(LM24 A3f) → 하한을 흔적 범위 ±25분으로 |
| `traceWindowPadMin` ★ | 30 | 분 | 흔적 창 ±30분(LM24 A9, V11 5.0h) |
| `traceWindowMinAnchors` | 2 | 건 | 흔적 창을 여는 최소 앵커 수 |
| `remoteSpanMinSends` | 2 | 건 | 잠금 중 발신이 이만큼이면 원격 흔적 창(must_fix [A 단조성 2]) |
| `remoteLinkGapMin` ★ | 60 | 분 | 원격 연결 다리(time-mm R6/V10, C19a) |
| `afterHoursFgMin` ★ | 15 | 분 | 창 밖·점심 자격: 업무 앱 능동 최소량(AutoSave 편집 인정 정책 포함) |
| `afterHoursAnchorMin` | 15 | 분 | 창 밖 자격: 산출물 근접 |
| `skeletonPadMin` ★ | 30 | 분 | 창 밖 인정 = 골격 ±30분(must_fix [A 창 밖 자격]) |
| `skeletonAnchorPreMin` | 30 | 분 | 골격 = 앵커 직전 30분 |
| `passiveCreditMin` ★ | 5 | 분 | 수신 1건 크레딧(1슬롯) |
| `passiveDayCapMin` ★ | 60 | 분 | 수신만으로 하루 3h 과대(LM24 A18) 방지 |
| `passiveMaxParticipants` | 10 | 명 | 단체 수신 제외 |
| `passiveChainGapMin` ★ / `passiveChainMinN` | 90 / 3 | 분 / 건 | R7 수신 연속형(7→8통 절벽 제거) |
| `dateOnlyGate` | false | — | 결정 메모 §5 'date-only 는 시간 근거 아님'(must_fix). 켜면 low + Q06 |
| `tentative` / `tentativeEvidenceRatio` | evidence / 0.5 | — / 비 | 미정 회의는 회의 창 전경 50% 이상일 때만(C) |
| `solverMode` / `solverCapH` | anchor / 4 | — / h | 기계 시간 ≠ 사람 시간(결정 메모 §10.2). cap 은 LM24 호환 옵션(K6) |
| `futureSlackMin` | 5 | 분 | 미래 시각 폐기(LM24) |
| `fileBurstN` | 8 | 건/분 | 동기화·복사 뭉치(LM24 K8) |
| `utcSuspectShare` | 0.6 | 비 | UTC 저장 의심(LM24 K14) |
| `mailTimeOffsetH` | null | h | 'utc' 표식 경로의 보정량(확인 후에만) |
| `longDayH` | 16 | h | 표시·큐만(자르지 않음, LM24 함정 'MAX_WORK 12 → 78% 누락') |
| `privacy.time.regular_private_run_min` | 30 | 분 | PRIVACY R-P3 소유 — 정규 구역 사적 전용 연속 차감 문턱 |
| `privacy.time.offhours_private_break_min` | 15 | 분 | PRIVACY R-P4 소유 — 창 밖 사적 전용이 다리를 끊는 문턱 |

#### 8.2.3 귀속(`time.attrib.*`)

| 키 | 기본 | 단위 | 근거 |
|---|---|---|---|
| `pointWeightSec` | 60 | 초 | 저장·커밋 1건의 L3 가중 |
| `postPadMin` | 30 | 분 | E1·E2·E3c 종료 뒤 마무리 창 |
| `meetSplitMinAtt` ★ / `meetSplitShare` ★ | 6 / 0.5 | 명 / 비 | 대형 회의 중 다른 업무 PC 입력 분할(A 8명·180초 + C 6명·0.5 통합) |
| `meetAbsentCover` ★ | 0.9 | 비 | 회의 시간의 90% 이상 다른 업무 PC 능동 → 불참 의심 |
| `gapSplitMaxMin` ★ | 30 | 분 | PC 밖 공백 중점 분할 한도(C) |
| `absorbGenericMaxMin` | 10 | 분 | 같은 업무 사이 일반 앱 흡수(파일 찾기·알트탭, C) |
| `floorNearMin` | 30 | 분 | PC 하한 슬롯의 근접 업무 반경(C) |
| `solverAbsorbGeneric` | true | — | 솔버 대기 중 일반 앱 → 솔버 업무(C) |
| `l6MaxRatio` ★ | 1.0 | 배 | 추정 배분 ≤ 그날 직접 증거(None = 무제한) |

#### 8.2.4 확인 큐(`time.queue.*`)

| 키 | 기본 | 근거 |
|---|---|---|
| `gapMin` | 90분 | 근무창 공백 질문(Q08) |
| `bucketRunMin` | 60분 | 미귀속 블록 질문(Q17) |
| `minEffortH` | 0.5h | 경계 확인(Q01) 대상 최소 투입 |
| `maxPerWeek` | 15건 | 응답 부담 상한(우선순위 순) |
| `openLongWd` | 20근무일 | 오래 열린 업무(Q03) |
| `solverDayH` | 8h | 솔버 대량(Q11) |
| `parallelMax` | 5.0 | 분할 과다 의심(Q12) |

#### 8.2.5 단위업무(`episode.*`)

| 키 | 기본 | 단위 | 근거 |
|---|---|---|---|
| `requestMaxParticipants` | 5 | 명 | 단체 요청은 S1 아님(C) |
| `reworkWindowWd` ★ | 10 | 근무일 | 보고 뒤 같은 화제 재의뢰 = 같은 업무 차수(B·C) |
| `reopenQuietWd` | 3 | 근무일 | NEXT_REQ: 조용한 기간 뒤 추가 요청 → 새 차수 |
| `supplementWd` | 2 | 근무일 | 보완·전달 보고로 끝 연장 |
| `preStartTolMin` | 60 | 분 | 선행 착수 표식(B S2r = C pre_request) |
| `preWorkH` | 24 | h | 의뢰 전 선행 작업 연결 창 |
| `linkWindowWd` | 3 | 근무일 | 의뢰 후 첫 손댐 시간 보너스 창 |
| `link.theta` ★ | 2.0 | 점 | 약한 키 합산 문턱(B θ_union) |
| `link.wToken` / `wTime` / `wProject` | 2.5 / 0.5 / 0.7 | 점 | B 가중(토큰 2.5×유사도, 과제 0.7) + 시간 근접 0.5 |
| `link.reportSim` | 0.3 | 유사도 | 다른 대화 보고 ↔ 같은 상대 열린 의뢰(A) |
| `link.multiCloseSim` | 0.6 | 유사도 | 다대다 종료: 첨부 문서군 ↔ 다른 의뢰 토큰 |
| `link.sendTokenSim` | 0.6 | 유사도 | 무연결 발신 → 업무 토큰 연결 |
| `tokens.minSubLen` | 2 | 자 | 한국어 합성어 부분 문자열 일치 최소 길이(C) |
| `tokens.idfMaxDf` / `idfMinN` | 0.3 / 20 | 비 / 노드 | 상용 토큰 제거(B) |
| `tokens.boilerplate` | §4.1 목록 | — | LM24 EP_BOILER(상용구 오매칭 실측) |
| `docs.genericStems` | §4.1 목록 | — | 범용 파일명 불용 사전(must_fix B(5)) |
| `finalWords` / `reviewWords` / `interimWords` | §4.9.2·§4.7·§4.3 | — | E2 최종 이름·E3c 리뷰 회의·E1p 중간 보고 낱말 |
| `recurringMinWeeks` ★ / `recurringMaxDaysPerWeek` | 4 / 2 | 주 / 일 | 반복 문서(B ISO 주 + 주당 활동일 조건) |
| `selfMergeSim` / `selfMergeDays` | 0.5 / 3 | 유사도 / 일 | 자체 업무 문서군 병합(A) |
| `splitWd` ★ | 5 | 근무일 | 자체 업무·앱 업무 휴면 분리(A) |
| `dormantWd` ★ | 5 | 근무일 | E3i 휴면 종료(1주) |
| `quietWd` ★ / `autosaveQuietWd` ★ | 3 / 3 | 근무일 | E2 '조용한 기간'(자동 저장 문서는 따로) |
| `e2Weights` ★ | 조용 0.4 · 내보내기 0.3 · 최종 0.2 · 결과 0.3 · 첨부 0.3 | 점 | 단일 증거로는 E2 불가 |
| `e2High` ★ / `e2Low` ★ | 0.7 / 0.5 | 점 | E2h / E2l |
| `e2TailMin` ★ | 120 | 분 | 완료 후보 뒤 작업이 이어지면 종료 아님(C) |
| `s2PrePadMin` ★ / `e3PostPadMin` ★ | 30 / 30 | 분 | 추정 경계 여유(리드타임 전용, 투입 무관) |
| `s2MeetLookbackH` ★ / `e3cLookaheadH` ★ | 48 / 24 | h | 의뢰자 회의로 S2m·E3c(C, 결정 v2) |
| `meetLinkMin` | 2.0 | 점 | 회의 ↔ 업무 연결 문턱(주최자 2 + 토큰 2.5×유사도) |
| `sharedDocMinTasks` | 3 | 업무 | 공용 문서 자동 판정 |
| `giantNodes` / `giantDays` | 500 / 90 | 건 / 일 | 거대 성분 가드(B) |
| `requireCommsCoverageForE3` | true | — | 수집 결손을 대면 보고로 오판하지 않기 |
| `unstartedWd` | 10 | 근무일 | 미착수 의뢰 질문(Q02) |

#### 8.2.6 MM(`mm.*`)

| 키 | 기본 | 근거 |
|---|---|---|
| `mm.stdDayMin` | 480 | 요구 [업무시간]1. 팀 레지스트리 `calendar.std_day_min` 이 우선(팀 R-5) |
| `mm.denominator` | workdays | 공휴일 제외 평일 × 8h. `weekdays` 선택 가능 — 사용자 확인 항목(결정 메모 §10.3) |
| `mm.inferredAbsence` | confirm_only | 추정 부재는 확인 전 가용에서 빼지 않음(R10). `exclude` 선택 가능 |
| `mm.todayFraction` | true | 오늘은 표준창 경과 비율만 가용(LM24 A34) |
| `mm.overtimeBasis` | window | 슬롯 꼬리표 기준 초과. `daily8h` 선택 가능 |

### 8.3 보정 도구(`tools/calibrate.py`) — 수동 기록을 정답 세트로

- **정답 세트**: 사용자가 남긴 시각 있는 수동 업무 기록(`work` a·b·ref), 확인 큐 응답(`instr`·`report`·`must_link`·`exclude`), '이날은 정확' 표시를 받은 날. 정답 세트는 개인 PC 에만 있고 팀으로 나가지 않는다.
- **목적 함수**(낮을수록 좋음): `J = w1 · |봉투 h − 정답 근무 h|/정답 h  +  w2 · 경계 오차(분, 시작·종료 평균) / 60  +  w3 · (1 − 귀속 일치율)`. 기본 w = (1.0, 0.5, 1.0). 정답이 일부 구간만 있으면 그 구간에서만 잰다.
- **격자**: ★ 키만 대상. 한 번에 2~3개 키, 키당 3~5단계(예 `dormantWd` ∈ {3,5,7,10}, `preWindowMin.mail` ∈ {10,20,30}, `s2PrePadMin` ∈ {15,30,60}). 다른 키는 기본값 고정.
- **가드**: ① 단조성 관문(G3)·보존(G1)을 통과하는 값만 후보 ② 기본값 대비 J 개선이 5% 미만이면 바꾸지 않는다 ③ 정답 날짜 수 < 10 이면 '자료 부족'만 보고 ④ **자동 적용 금지** — 민감도 표(키 × 값 → J, 봉투 h 변화, 등급 분포 변화)를 보여 주고 사용자가 승인해야 레지스트리 개인 덮어쓰기에 쓴다 ⑤ 보정한 키는 `run_meta.cfg_used` 에 '보정됨(날짜·J)' 으로 남긴다.
- 출력: `calibration_report.json`(키별 민감도, 추천값, 표본 수, 적용 여부). 팀 공용 기본값 변경은 팀장이 여러 사람의 보고서를 보고 레지스트리에서 한다.

---

## 9. 시나리오 표 (83개, 참조 구현으로 계산한 골든 값)

공통 조건:

- 달력 = `calendar_verified.json`(2026-09 근무일 20일: 9/24·9/25 공휴일, 9/28 근무일 / 2026-10 근무일 20일: 10/5·10/9). 분석 시각은 따로 적지 않으면 2026-10-30 18:00.
- '표준 근무일(office_day)' = 샘플러 09~12·13~18 능동(지정 구간 외는 브라우저), 12~13 잠금, PC 가동 08:50~18:05.
- 단위업무 칸: `종류:라벨 투입h (등급 · 시작근거→종료근거 · 리드h · 차수/선행/기계)`. 종류 S1 = 디지털 의뢰 업무, ACK = 수락 시작 업무, COORD = 조율형, SELF = 자체 업무, APP = 앱 업무, REPORT = 단발 보고, MANUAL = 수동 기록 업무.
- 버킷 칸: `GENERIC·COMM·MEET·OFFPC·UNKNOWN` 은 `B_*` 버킷 h.
- 확인 큐 칸은 §7.3 코드. 모든 시나리오에서 날마다 보존 assert 가 통과했고(G1), 입력 순서를 섞어도 결과가 같았으며(G2), 정수 분 표 재합산이 개인 MM 과 일치했다(G5).
- 골든: `design\worktime\golden.json`(`python -B scenarios.py --check` → 83/83 PASS). 파라미터를 바꾸면 차이를 리뷰한다(G4).

| ID | 다루는 것 | 입력 요약 | 기대 봉투 h (꼬리표) | 단위업무 귀속 h (등급 · 시작→종료 · 리드 h) | 버킷 h | 확인 큐 |
|---|---|---|---|---|---|---|
| W01 | [업무시간]6 S1×E1 | S1×E1: 팀즈 의뢰 → 3일 문서 → 같은 방 보고(첨부) | 24.00 (정규 24) | S1:chat_kim#1 16.50 (A · S1→E1 · 54)<br>SELF:주간회의록_과제b@10-13 5.00 (E · S2p→E3i · 6) | GENERIC 2.5 | Q01 Q17 |
| W02 | [업무시간]6 S1×E2 | S1×E2: 의뢰 메일 → 목 15:00 마지막 저장·15:05 PDF 내보내기, 보고 없음(3업무일 조용) | 40.00 (정규 40) | S1:M2#1 24.00 (B · S1→E2h · 77.08) | GENERIC 16 | Q17 |
| W03 | E2→E1 연장 | S1×E2 → E1: W02 + 금 10:00 보고 메일(PDF 첨부) → 종료가 보고로 연장 | 40.00 (정규 40) | S1:M2#1 24.67 (A · S1→E1 · 96) | GENERIC 15.33 | Q17 |
| W04 | [업무시간]6 S2×E1 | S2×E1: 신호 없는 대면 지시 → 문서 3일 → 메일 보고(첨부) | 24.00 (정규 24) | SELF:원가분석_과제b@10-13 17.33 (C · S2p→E1 · 54.83) | GENERIC 6.67 | Q01 Q17 |
| W05 | S2m(의뢰자 회의) | S2m×E1: W04 + 첫 작업 전 의뢰자(보고 수신자) 주최 회의 09:00~09:30 | 24.00 (정규 24) | SELF:원가분석_과제b@10-13 18.50 (C · S2m→E1 · 55) | GENERIC 5.5 | Q01 Q17 |
| W06 | [업무시간]6 S2×E2 | S2×E2: 신호 없는 지시 → 월·화 문서 → 화 11:50 PDF 내보내기 → 이후 조용 | 16.00 (정규 16) | SELF:배선도_과제c@10-12 8.00 (C · S2p→E2h · 23.33) | GENERIC 8 | Q01 Q17 |
| W07 | [업무시간]6 S1×E3 | S1×E3i: 의뢰 메일 → 3일 작업 → 대면 보고(무신호) → 5업무일 휴면 | 24.00 (정규 24) | S1:M7#1 18.50 (D · S1→E3i · 55) | GENERIC 5.5 | Q01 Q17 |
| W08 | E3c(결정 v2) | S1×E3c: 의뢰 → 2일 작업 → 다음 날 의뢰자 주최 리뷰 회의(대면 보고) | 24.00 (정규 24) | S1:M8#1 15.50 (C · S1→E3c · 49.5) | GENERIC 8.5 | Q01 Q17 |
| W09 | S2×E3·휴면 분리 | S2×E3 분리: CAD 9/1·9/2·9/4 → 10업무일 공백(추석 연휴는 근무일 아님) → 9/21 재개 | 32.00 (정규 32) | SELF:하우징_과제d@09-01 15.00 (E · S2p→E3i · 76)<br>SELF:하우징_과제d@09-21 3.00 (E · S2p→E3i · 4) | GENERIC 14 | Q01 Q09 Q17 |
| W10 | 시작만(미착수) | 시작만(미착수): 9/1 팀즈 의뢰, 진행 증거 없음, 그날 PC 는 일반 사용 | 8.00 (정규 8) | S1:chat_z#1 0.00 (Z · S1→OPEN) | GENERIC 8 | Q02 Q17 |
| W11 | 종료만(진행 있음) | 종료만(진행 있음): 의뢰 없이 14:00~14:50 주간보고 작성 → 15:00 보고(첨부) | 8.00 (정규 8) | SELF:주간업무_과제e@10-16 2.00 (C · S2p→E1 · 1.5) | GENERIC 6 | Q01 Q17 |
| W12 | 종료만(진행 없음) | 종료만(진행 없음): 15:00 보고 메일, 첨부 파일의 작성 흔적 없음 | 8.00 (정규 8) | REPORT:M12 0.67 (D · S2p→E1 · 0.33) | GENERIC 7.33 | Q01 Q17 |
| W13 | 재의뢰 차수 | 재의뢰 차수: 의뢰 → 보고(v1) → 같은 스레드 수정 요청 → 보고(v2) | 24.00 (정규 24) | S1:M13#1 19.00 (A · S1→E1 · 36 · 차수 2) | GENERIC 5 | Q17 |
| W14 | ACK 시작(S2a) | ACK 시작(S2a): 대면 지시 뒤 팀즈 '수락' 발신 → 작업 → 같은 방 보고 | 16.00 (정규 16) | ACK:chat_lee#1 9.58 (B · S2a→E1 · 25) | GENERIC 6.42 | Q17 |
| W15 | 선행 착수 | 선행 착수: 의뢰 전날 구두 예고 → 10~13 선행 작업 → 다음 날 09:00 공식 의뢰 → 15:00 보고 | 16.00 (정규 16) | S1:M15#1 8.50 (A · S1→E1 · 6 · 선행 3h) | GENERIC 7.5 | Q17 |
| W16 | NEXT_REQ 차수 | NEXT_REQ: 의뢰 → 2일 작업 → (대면 보고, 무신호) → 4업무일 조용 → 같은 스레드 같은 화제 추가 요청 → 1일 작업 | 24.00 (정규 24) | S1:M16#1 14.50 (D · S1→E3i · 36.5 · 차수 2) | GENERIC 9.5 | Q01 Q09 Q17 |
| W17 | 1:1 상시 대화방(X19) | 1:1 상시 대화방 의뢰 2건: 10:00 브라켓·10:02 수락·13:30 모터·14:00/16:30 보고(첨부) | 8.00 (정규 8) | S1:chat_p31#1 3.17 (A · S1→E1 · 4)<br>S1:chat_p31#2 2.92 (A · S1→E1 · 3) | GENERIC 1.92 | Q17 |
| W18 | 다대다 종료(X20) | 다대다: 같은 상대의 의뢰 2건(M1 원가·M2 일정)을 M1 스레드 보고 1통(두 파일 첨부)으로 닫음 | 16.00 (정규 16) | S1:M1#1 6.38 (A · S1→E1 · 31)<br>S1:M2#1 8.12 (A · S1→E1 · 30.5) | GENERIC 1.5 | Q17 |
| W19 | 조율형 S1o/E1i(X21) | 조율형(S1o/E1i): P5 에게 지시 → P5 보고 수신(첨부) → 검토(열람) → P1 에게 전달 보고(E1o) | 24.00 (정규 24) | COORD:M21#1 2.67 (A · S1o→E1 · 54) | COMM 0.08 · GENERIC 21.25 | Q17 |
| W20 | 반복 문서(X22) | 반복 문서: 9/2~10/21 매주 수 16~17시 주간보고.xlsx 작성·저장(8주) | 9.33 (정규 9.33) | SELF:주간보고@09-02 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@09-09 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@09-16 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@09-23 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@09-30 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@10-07 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@10-14 1.17 (E · S2p→E3i · 2)<br>SELF:주간보고@10-21 1.17 (E · S2p→E3i · 2) | 0 | Q01 Q08 Q09 |
| W21 | 범용 파일명(X23) | 범용 파일명: P1 의뢰(M1)·P2 의뢰(M2)를 둘 다 '보고서.pptx' 로 작업·첨부 보고 | 16.00 (정규 16) | S1:M1#1 2.50 (A · S1→E1 · 2.47)<br>S1:M2#1 11.50 (A · S1→E1 · 27) | GENERIC 2 | Q17 |
| W22 | 같은 스레드 새 의뢰(X24) | 같은 메일 스레드, 보고 후 2업무일 만에 무관한 새 의뢰(토큰·첨부 불일치) → 새 업무 | 16.00 (정규 16) | S1:M1#1 6.17 (A · S1→E1 · 6.67)<br>S1:M1#2 4.67 (A · S1→E1 · 5.17) | GENERIC 5.17 | Q09 Q17 |
| W23 | [업무시간]3·합성어(X08) | [업무시간]3 + 한국어 합성어: '견적·검토' 의뢰 ↔ '견적검토.xlsx', 21:30 휴대폰 보고(PC 꺼짐) | 8.33 (연장 0.33 · 정규 8) | S1:M8#1 4.33 (A · S1→E1 · 11.5) | GENERIC 4 | Q04 Q17 |
| W24 | 과제 충돌 cannot-link | 과제 레지스트리 충돌(cannot-link): 같은 상대·같은 토큰 의뢰 2건이 과제A·과제B 로 갈림 | 8.00 (정규 8) | S1:M24a#1 2.74 (D · S1→E3i · 3.33)<br>S1:M24b#1 3.59 (D · S1→E3i · 7.17) | GENERIC 1.67 | Q01 Q17 |
| W25 | 상용구 오매칭 방지 | 상용구 오매칭 방지: 두 의뢰(P1·P2) → P2 에게 상용구만의 보고 1통 + 토큰이 맞는 보고 1통 | 8.00 (정규 8) | S1:M25a#1 0.00 (Z · S1→OPEN)<br>S1:M25b#1 6.17 (A · S1→E1 · 6.67)<br>REPORT:M25c 0.00 (D · S2p→E1 · 0.33) | GENERIC 1.83 | Q17 |
| W26 | [업무시간]5 무신호(X06) | [업무시간]5: 18~19 개인 브라우저 능동(업무 앱·산출물 없음) → 19~23 잠금 | 8.00 (정규 8) | SELF:사양서@10-14 8.00 (E · S2p→E3i · 10) | 0 | Q01 |
| W27 | 골격 ±30분(X06b) | 창 밖 자격 = 골격 ±30분: 18:00~22:45 개인 브라우저 + 22:45~22:51 문서 + 22:50 저장 1건 | 9.17 (야간 1 · 연장 0.17 · 정규 8) | SELF:사양서@10-14 9.17 (E · S2p→E3i · 14.85) | 0 | Q01 |
| W28 | [업무시간]4·잠금 단절(X07) | [업무시간]4: 정규 후 18:05 잠금 → 22:10 재개 → 같은 문서 → 01:40~02:30 잠금 → 02:40 보고 메일 | 11.83 (야간 3.83 · 정규 8) | SELF:해석보고서_과제a@10-26 11.83 (C · S2p→E1 · 18.17) | 0 | Q01 Q08 |
| W28B | [업무시간]4 V9 | W28 의 샘플러 없는 판(LM24 V9): PC 08:30~익일 03:00 가동, 저장·발신만 | 12.00 (야간 4.17 · 정규 7.83) | SELF:해석보고서_과제a@10-26 7.83 (C · S2p→E1 · 15.33) | UNKNOWN 4.17 | Q01 Q08 Q17 |
| W29A | 단조성 기준(X25a) | 단조성 기준: 평일 21:00 저장 1건(샘플러 없음) | 0.50 (연장 0.5) | SELF:계산서_과제a@10-14 0.50 (E · S2p→E3i · 1) | 0 | Q01 Q08 |
| W29B | 단조성(X25b) | W29a + 같은 PC 샘플러 21:00~21:02 능동(같은 문서) — 양성 증거 추가 → 비감소 | 0.50 (연장 0.5) | SELF:계산서_과제a@10-14 0.50 (E · S2p→E3i · 1.03) | 0 | Q01 Q08 |
| W30A | 다중 PC 하한(X25c) | 샘플러 없는 PC1(09~18 가동), 저장 10:00·16:00 | 7.67 (정규 7.67) | SELF:설계서_과제a@10-14 3.92 (E · S2p→E3i · 7) | UNKNOWN 3.75 | Q01 Q17 |
| W30B | 다중 PC 하한(X25d) | W30a + 다른 PC2 샘플러 11:00~11:05 브라우저 능동 — PC1 하한 유지 | 7.67 (정규 7.67) | SELF:설계서_과제a@10-14 3.42 (E · S2p→E3i · 7) | UNKNOWN 4.25 | Q01 Q17 |
| W31A | 샘플러 중도 설치(X12) | 에이전트 15시 중도 설치: PC1 이벤트 08:50~18:05, 샘플러 15:00~18:00, 저장 10:00·11:30·16:00 | 7.83 (정규 7.83) | SELF:설계변경_과제a@10-13 7.83 (E · S2p→E3i · 9) | 0 | Q01 |
| W31B | X12b | W31a 에서 샘플러를 뺀 것(비교 기준) | 7.67 (정규 7.67) | SELF:설계변경_과제a@10-13 5.83 (E · S2p→E3i · 7) | UNKNOWN 1.83 | Q01 Q17 |
| W32 | 유휴 공백(X13) | 샘플러 정상, 11~16시 무입력(잠그지 않음) — 근거 없는 낮 공백 | 4.00 (정규 4) | SELF:검토_과제e@10-13 4.00 (E · S2p→E3i · 10) | 0 | Q01 Q08 |
| W33 | 미수집 노트북(X33) | 수집 안 된 노트북: PC1 오전 능동·오후 잠금, 오후 발신 14:00·15:30·17:00(같은 화제) | 7.00 (정규 7) | SELF:검토의견_과제b@10-14 7.00 (E · S2p→E3i · 9) | 0 | Q01 Q05 |
| W34 | 점심 개인 사용(X26) | 점심 개인 사용: 12~13 브라우저 능동(업무 앱·산출물 없음, 잠금 없음) | 8.00 (정규 8) | SELF:보고서_과제a@10-14 8.00 (E · S2p→E3i · 10) | 0 | Q01 |
| W35 | date-only(X27) | date-only 발신 5통 + PC 09~18(샘플러 없음) — 기본 0h | 0.00 (-) | - | 0 | - |
| W35B | date-only 게이트 옵션 | W35 + 게이트 옵션(time.envelope.dateOnlyGate=true) → 낮은 신뢰 하한 + Q06 | 7.67 (정규 7.67) | - | UNKNOWN 7.67 | Q06 Q17 |
| W36 | 수신 연속형 V1(X14) | V1·R7: 샘플러 없음, PC 09~18, 직접 수신만 — 10/13 8통(1h 간격), 10/14 80통, 10/15 CC 1통 | 13.25 (정규 13.25) | - | UNKNOWN 13.25 | Q09 Q17 |
| W37 | 회의 4건 V4(X15) | V4: 1h 회의 4건(수락, 사이 30·60분 공백) + 회의 중 저장 1건, PC 기록 없음 | 4.00 (정규 4) | - | MEET 4 | Q08 Q17 |
| W38 | 흔적 창 V11(X09) | V11: PC 기록 없는 평일(외근) 10:00 정보 발신·15:00 첨부 보고 발신 + 11:00 의뢰 수신 | 5.00 (정규 5) | S1:M9b#1 0.00 (Z · S1→OPEN)<br>REPORT:M9c 0.75 (D · S2p→E1 · 0.33) | COMM 0.33 · OFFPC 3.92 | Q01 Q02 Q05 Q08 Q17 |
| W39 | V12 E8(X10) | V12·E8: 샘플러 없음, PC 08~19 켜짐, 파일 저장 1건(10:00) | 7.67 (정규 7.67) | SELF:메모_과제d@10-13 1.42 (E · S2p→E3i · 1) | UNKNOWN 6.25 | Q01 Q17 |
| W40 | 다중 PC·RDP V8(X16) | V8: 데스크톱 09~10 문서A, 10~12 원격창(→클라우드PC 문서B), 노트북 13~18 문서A | 8.00 (정규 8) | SELF:문서a_과제a@10-14 6.00 (E · S2p→E3i · 10)<br>SELF:문서b_과제b@10-14 2.00 (E · S2p→E3i · 3) | 0 | Q01 |
| W41 | 회의 중 PC(MIX) | 회의 중 PC: 30명 설명회 10~11 중 10:00~10:40 문서Y, 4명 주간회의 14~15 중 14:20~14:40 문서Y | 8.00 (정규 8) | SELF:문서x_과제a@10-14 6.00 (E · S2p→E3i · 10)<br>SELF:문서y_과제b@10-14 0.34 (E · S2p→E3i · 5.67) | MEET 1.66 | Q01 Q17 |
| W42 | 장시간 솔버(X18) | 장시간 솔버: 15:30~16:30 설정·제출 → 연산 16:30~익일 04:00 → 익일 09:10~10:00 결과 확인 | 15.00 (정규 15) | SELF:결과보고서_과제a@10-19 12.65 (E · S2p→E3i · 34)<br>SELF:열해석_모델@10-19 2.35 (E · S2p→E3i · 19.5 · 기계 11.5h) | 0 | Q01 Q11 |
| W43 | AutoSave 퇴근 후 | 퇴근 후 AutoSave 문서 40분 편집(저장 이벤트 없음, 열린 문서 mtime 폴링만) → 업무 앱 전경 ≥15분 자격 | 8.67 (연장 0.67 · 정규 8) | SELF:제안서_과제j@10-15 8.67 (E · S2p→E3i · 12.67) | 0 | Q01 |
| W43B | AutoSave E2 | AutoSave 문서의 완료 후보: W43 + 20:38 같은 stem PDF 내보내기 → 조용한 기간(autosaveQuietWd) + 내보내기 = E2h | 8.67 (연장 0.67 · 정규 8) | SELF:제안서_과제j@10-15 8.67 (C · S2p→E2h · 12.17) | 0 | Q01 |
| W44 | 회의 불참 의심 | 수락 회의 10~11 동안 노트북에서 다른 업무 능동 입력 60분 → 봉투 1h, 귀속 PC 업무, 불참 의심 큐 | 8.00 (정규 8) | SELF:도면검토_과제c@10-15 3.00 (E · S2p→E3i · 4) | GENERIC 5 | Q01 Q14 Q17 |
| W45 | 공용 문서 | 공용 마스터 엑셀: 업무 3개(같은 주)가 '팀공용_마스터.xlsx' 를 함께 쓰고 각 보고에 첨부 → B_GENERIC | 24.00 (정규 24) | S1:M45a#1 3.77 (A · S1→E1 · 56.17)<br>S1:M45b#1 3.74 (A · S1→E1 · 55.83)<br>S1:M45c#1 7.57 (A · S1→E1 · 55.5) | GENERIC 8.92 | Q17 Q18 |
| W46 | 월 경계 자정 | 월 경계 자정 넘김: 9/30 23:00~10/1 01:30 같은 문서 + 01:20 보고 발신 | 10.50 (야간 2.5 · 정규 8) | S1:M46#1 7.17 (A · S1→E1 · 15.33) | GENERIC 3.33 | Q08 Q17 |
| W47A | 확인 응답(1회차) | 확인 응답 지속성(1회차): 자체 업무(의뢰·보고 신호 없음) + 사용자 확인 '지시 9/14 08:50, 대면 보고 9/16 17:00' | 24.00 (정규 24) | SELF:점검표_과제h@09-14 18.00 (B · S2M→E3M · 56.17) | GENERIC 6 | Q17 |
| W47B | 확인 응답 지속(2회차) | 확인 응답 지속성(2회차): W47a + 클라우드PC 백필로 의뢰 메일(9/14 08:55) 발견 → S1 업무로 바뀌어도 응답(증거 키) 유지 | 24.00 (정규 24) | S1:M47#1 18.00 (B · S1→E3M · 56.08) | GENERIC 6 | Q17 |
| W48 | 사적 차감 R-P3 | 사적 앱 전경 30분(사적 사이트)이 근무창 안에 있음 → 마지막 단계 차감, 원장에 남김, 다른 업무로 옮겨 붙지 않음 | 7.50 (정규 7.5) | SELF:설계서_과제a@10-20 7.50 (E · S2p→E3i · 10) | 0 | Q01 |
| W49 | 놓친 활동 알림 | 팀즈 '놓친 활동' 알림 메일만 있는 날(PC 기록 없음) → 존재 증거일 뿐 봉투 0 | 0.00 (-) | - | 0 | Q09 |
| W50 | 정밀 사본·UTC 의심 | 같은 발신이 PC1 COM(정확 15:00)·클라우드PC 웹(date-only)에 둘 다, 다른 날 발신은 UTC 저장 의심 | 3.92 (야간 2.17 · 연장 1.42 · 정규 0.33) | - | COMM 2.33 · OFFPC 1.58 | Q04 Q08 Q09 Q13 Q17 |
| W50B | UTC 보정 | W50 + 그 경로를 UTC 저장으로 확인(utc 표식) 후 time.envelope.mailTimeOffsetH=9 → 오전 근무 시간으로 옮겨짐 | 6.67 (연장 0.17 · 정규 6.5) | - | COMM 2.17 · OFFPC 4.5 | Q05 Q08 Q09 Q17 |
| W51 | [업무시간]1·7 월 MM | 월 MM(2026-09, 평일 20일): 평일 8h, 연장 2일×2h, 토 4h, 연차 1, 오후반차 1, 9/22 야간 22~24 | 158.00 (야간 2 · 연장 4 · 정규 148 · 휴일 4) | SELF:양산지원_과제b@09-01 152.00 (O · S2p→OPEN)<br>SELF:치구도면_과제c@09-19 6.00 (O · S2p→OPEN) | 0 | - |
| W52 | 연차·오후 반차 | 연차·반차: 연차 10/22 + 15:00 휴대폰 발신 1통, 오후반차 10/23 + 오전 근무 09~12·13~14 | 4.33 (연장 0.33 · 정규 4) | SELF:보고서_과제d@10-23 4.00 (E · S2p→E3i · 6) | COMM 0.33 | Q01 Q04 Q16 |
| W53 | [업무시간]2 주말·야간 | 주말·야간: 금 정상 + 금 23:00~토 01:00 수락 회의 + 토 13~17 문서 + 일 수신 3통만 | 14.00 (야간 1 · 정규 8 · 휴일 5) | SELF:사양검토_과제a@10-16 8.00 (E · S2p→E3i · 10)<br>SELF:주말작업_과제e@10-17 4.00 (E · S2p→E3i · 5) | MEET 2 | Q01 Q17 |
| W54 | [업무시간]8 병행 보존 | 병행 3업무: 10/12 의뢰 X·Y·Z → 10/13 30분 단위 교차 편집(보존) | 16.00 (정규 16) | S1:MX#1 3.00 (D · S1→E3i · 32.5)<br>S1:MY#1 2.50 (D · S1→E3i · 30.5)<br>S1:MZ#1 2.50 (D · S1→E3i · 30) | GENERIC 8 | Q01 Q17 |
| W55 | 커버리지 보류 | 커버리지 보류: W07 + 의뢰 후 메일 발신 수집이 10/16~10/23 막힘(blocked) → E3i 보류(OPEN)·Q03 | 24.00 (정규 24) | S1:M7#1 20.00 (O · S1→OPEN) | GENERIC 4 | Q03 Q17 |
| W56 | L6 비례 V25 | V25 무증거 배분(L6): 직접 증거 A 3h·B 1h, 14~18 브라우저 4h → A 6h·B 2h | 8.00 (정규 8) | S1:M56a#1 6.00 (O · S1→OPEN)<br>S1:M56b#1 2.00 (O · S1→OPEN) | 0 | - |
| W42B | 솔버 cap 옵션 | W42 와 같은 입력, 솔버 cap 옵션(LM24 호환: 창 밖 연산 밤당 4h, 사람 흔적 있으면 상한 해제) | 19.00 (야간 4 · 정규 15) | SELF:결과보고서_과제a@10-19 12.65 (E · S2p→E3i · 34)<br>SELF:열해석_모델@10-19 6.35 (E · S2p→E3i · 19.5 · 기계 11.5h) | 0 | Q01 Q11 |
| W24B | 과제 ID 보강 연결 | 과제 레지스트리 일치가 약한 토큰 연결을 보강: '과제A 일정' 의뢰 ↔ '과제A_마일스톤.xlsx'(같은 과제 ID) | 8.00 (정규 8) | S1:M24c#1 2.83 (D · S1→E3i · 3.33) | GENERIC 5.17 | Q01 Q17 |
| W26B | [업무시간]5 근접 자격 | 퇴근 후 18:30~18:45 브라우저(업무 앱 아님) → 18:55 메일 발신(샘플러 없는 휴대폰): 산출물 ±15분 근접 자격 | 8.50 (연장 0.5 · 정규 8) | SELF:사양서@10-27 8.50 (O · S2p→OPEN) | 0 | Q04 |
| W48B | 사적 단절 R-P4 | 창 밖 사적 단절(R-P4): 19:00 저장 → 19:10~19:25 사적 앱 → 19:45 발신, 그 사이 샘플러 없음 19:05~19:10 | 8.92 (연장 0.92 · 정규 8) | SELF:설계서_과제a@10-27 8.92 (O · S2p→OPEN) | 0 | Q04 |
| W57 | 고착 샘플러 V5 | 고착 샘플러: PC1 샘플러가 24시간 '능동·유휴 0초'로만 기록(TickCount 고착) + 저장 10:00·15:00, PC 08:50~18:05 | 7.67 (정규 7.67) | SELF:점검일지_과제e@10-27 3.92 (O · S2p→OPEN) | UNKNOWN 3.75 | Q17 |
| W58A | 미정 회의(근거 없음) | 미정(tentative) 회의 19:00~20:00, 회의 창 근거 없음 → 미산입 + Q15 | 8.00 (정규 8) | SELF:시험보고_과제f@10-28 8.00 (O · S2p→OPEN) | 0 | Q15 |
| W58B | 미정 회의(근거 있음) | W58a + 회의 창(온라인 회의 전경) 19:00~19:45 → 참석 근거 50% 이상 → 회의 1h 산입(연장) | 9.00 (연장 1 · 정규 8) | SELF:시험보고_과제f@10-28 8.00 (O · S2p→OPEN) | MEET 1 | Q17 |
| W59 | 저녁 차감 | 저녁 식사 시간: 18:00 퇴근(샘플러 끝) → 18:50 저장(샘플러 없는 PC9) → 19:30 메일 발신 | 9.08 (연장 1.08 · 정규 8) | SELF:발표자료_과제g@10-21 9.08 (E · S2p→E3i · 11.5) | 0 | Q01 Q04 |
| W52B | 오전 반차·휴가 중 근무 | 오전 반차(10/26, 09~14 휴가) + 10:30~11:30 문서 작업(휴가 중 근무) + 14:00~18:00 정규 작업 | 5.00 (연장 1 · 정규 4) | SELF:견적서_과제h@10-26 5.00 (O · S2p→OPEN) | 0 | Q16 |
| W60 | 샘플러 공백 다리 | 정규창 안 샘플러 공백 50분(잠그지 않음, 유휴) — PC 내부 다리(≤60분)로 잇는다 | 8.00 (정규 8) | SELF:회로검토_과제i@10-27 8.00 (O · S2p→OPEN) | 0 | - |
| W61 | 원격 연결 다리 V10 | 원격 연결 다리: 클라우드PC 22:00~22:50 문서 → 연결 끊김 → 00:05 휴대폰 회신(같은 문서 첨부, 55분 공백) | 18.17 (야간 2.17 · 정규 16) | SELF:대응방안_고객사a@10-28 10.17 (C · S2p→E1 · 15.58)<br>SELF:주간보고_과제a@10-29 6.00 (O · S2p→OPEN) | GENERIC 2 | Q01 Q04 Q17 |
| W62 | 수신만 V2 | V2: PC 기록 없는 평일, 직접 수신 8통(40분 간격)만 → 수신 크레딧 5분×8 = 40분(하루 상한 60분) | 0.67 (정규 0.67) | - | COMM 0.67 | Q08 |
| W64 | 부분월·오늘 비율 V15 | 부분월·오늘 경과 비율: 10/1~10/14 분석, 분석 시각 10/14 13:30, 평일 8h + 오늘 오전 3h | 59.33 (정규 59.33) | SELF:양산이관_과제b@10-01 59.33 (O · S2p→OPEN) | 0 | Q08 |
| W63 | 자체 업무 병합 | 자체 업무 문서군 병합: '열해석_모델.cas'(월) → 다음 날 '열해석_결과정리.xlsx' → 토큰 유사(≥0.5)·3일 안 → 한 자체 업무 | 16.00 (정규 16) | SELF:열해석_모델@10-26 11.00 (O · S2p→OPEN) | GENERIC 5 | Q17 |
| W65A | 퍼즈 반례 기준 | 심사 퍼즈 반례(seed 7 #6) 기준: PC 13~19만 가동(샘플러 없음), 09:07 발신 + 14~15 수락 회의 + 21:30 발신 | 8.50 (연장 0.5 · 정규 8) | - | COMM 0.67 · MEET 1 · OFFPC 3.17 · UNKNOWN 3.67 | Q04 Q05 Q17 |
| W65B | PC 기록 제거 비증가 | W65a 에서 PC 가동 기록을 뺀 것 → 봉투가 늘면 안 된다(원본 A: 6.08h → 9.17h 증가 결함) | 8.50 (연장 0.5 · 정규 8) | - | COMM 0.67 · MEET 1 · OFFPC 6.83 | Q04 Q05 Q17 |
| W66 | 항상 켜짐 V14 | V14 항상 켜진 PC: 48h 연속 가동(샘플러 없음), 저장 10:00·13:30·17:00 → 흔적 범위 ±25분 하한 | 7.00 (정규 7) | SELF:도면_과제c@10-28 4.92 (O · S2p→OPEN) | OFFPC 0.17 · UNKNOWN 1.92 | Q05 Q17 |
| W67A | 연결 키 없음 | 이름이 다른 산출 문서: '검증 절차 작성' 의뢰 ↔ 작업 문서 '과제J_검증서.docx'(토큰 불일치) → 연결 안 됨(미착수 Z + 자체 업무) | 8.00 (정규 8) | S1:M67#1 0.00 (Z · S1→OPEN)<br>SELF:과제j_검증서@10-29 8.00 (O · S2p→OPEN) | 0 | - |
| W67B | must_link 응답 | W67a + 확인 응답 '같은 업무'(must_link, 증거 키 = 의뢰 msg_key K67 · 문서군) → 의뢰 업무로 합쳐짐(재분석에도 유지) | 8.00 (정규 8) | S1:M67#1 7.83 (O · S1→OPEN) | GENERIC 0.17 | - |

### 9.1 시나리오 읽는 법 — 주요 행 해설

- **W27 대 원본 A**: 퇴근 후 개인 브라우저 18:00~22:45 + 22:45 문서 6분 + 22:50 저장 → 골격(22:20~22:51)±30분 = 21:50~23:00 만 인정, **9.17h**(원본 A 13.00h, 심사 기준 ≤ 9.2h).
- **W28 대 W28b**: 같은 하루라도 샘플러가 01:40~02:30 잠금을 관측하면 그 구간을 잇지 않는다(11.83h). 샘플러 없이 PC 가동만 있으면 V9 처럼 22:35~02:45 연속(12.00h). '샘플러 권위는 부정 증거로만'의 두 얼굴이다.
- **W29a = W29b, W30a = W30b, W31a ≥ W31b, W65a = W65b**: 심사 단조성 반례 4종(X25a/b·X25c/d·X12/X12b·퍼즈 seed 7 #6)이 모두 해소됐다.
- **W33**: 원격 흔적 창으로 4.00h(원본 A) → 7.00h, 오후 발신 3통이 토큰으로 자체 업무에 이어져 투입도 그 업무로.
- **W35/W35b**: date-only 발신만 있는 날은 기본 0h. 옵션을 켜야 7.67h(low)·Q06.
- **W36**: 수신만(샘플러 없음) 8통 6.17h · 80통 7.08h · CC 1통 0h — 계단 없음(LM24 V1·R7).
- **W37**: 1h 회의 4건 = 4.00h(회의 사이 공백을 잇지 않는다, LM24 V4).
- **W41**: 대형 회의 0.5/0.5 분할, 소형 회의는 회의 100%. **W44**: 회의 시간 내내 다른 업무 PC 입력 → 불참 의심, PC 업무 귀속, Q14.
- **W42/W42b**: 기본 anchor 모드는 기계 11.5h 를 투입에 넣지 않는다(봉투 15.00h). cap 옵션은 야간 4h 를 그 연산 업무에 귀속(19.00h).
- **W45**: 공용 마스터 문서 8.92h 는 B_GENERIC — 가장 최근 시작 업무(M45c)로 쏠리지 않는다.
- **W46**: 월 경계 자정 — 9월 야간 1.0h, 10월 야간 1.5h, 리드는 한 번만.
- **W47a/b**: 확인 응답이 문서군 키로 저장되어, 백필로 의뢰 메일이 나타나 업무 종류·ID 가 SELF → S1 로 바뀌어도 E3M 이 유지된다(E → B).
- **W51**: 2026-09 월 MM = 158/160 = **0.9875**, 로드 158/148 = **1.068**, 초과 10h(연장 4·야간 2·휴일 4).
- **W54**: 병행 3업무 투입 합 8.00h = 그날 봉투(리드 합 93.0h).
- **W56**: L6 비례(LM24 V25) A 6h·B 2h.
- **W67a/b**: 이름이 다른 산출 문서는 잇지 않는다(Z + 자체 업무). 사용자가 '같은 업무'라고 답하면(must_link, 증거 키) 의뢰 업무 7.83h 로 합쳐지고 재분석에도 유지된다.

---

## 10. 검증 관문

모든 관문은 구현 1일차부터 `tests/time/` 과 lint 단계에서 돈다. 아래 '현재 결과'는 참조 구현(`design\worktime\gates.py`, `scenarios.py`)으로 2026-10-05 에 실행한 값이다(`gates_out.txt`).

| 관문 | 내용 | 실패 시 | 현재 결과 |
|---|---|---|---|
| **G1 보존 assert** | 모든 분석에서 날마다 Σ귀속 초 = 300 × 봉투 슬롯 수(정수). 실데이터 분석 중에도 상시 | 분석 중단(fail-closed) | 시나리오 83개 + 퍼즈 12,000 실행 통과 |
| **G2 결정성·순서 무관** | 같은 입력·as_of·설정으로 2회 실행 해시 동일 + 입력 목록 순서를 섞어도 동일(정준 정렬 `(t0, kind, 원천 키)`) | 머지 차단 | 시나리오 83개 × 섞기 4회: 순서 의존 0건 |
| **G3 단조성 퍼즈** | 무작위 세계 ≥ 1,000건/시드: 양성 증거 1건 추가 → 봉투 비감소, PC 가동 기록 제거 → 비증가. 기본 세계(심사 mono_fuzz 분포)와 확장 세계(3일·PC 2대·창 밖·점심·사적·잠금·원격·연산·반차·수동) 둘 다 | 머지 차단 | 기본 3,000 + 확장 3,000 세계: 감소 **0**, 증가 **0** |
| **G4 골든 시나리오** | §9 의 83행을 골든으로 고정. 파라미터·코드를 바꾸면 차이 목록을 리뷰 | 리뷰 필수 | 83/83 PASS |
| **G5 개인 = 팀** | 정수 분 표(envelope_daily·alloc_daily)로 팀 서버가 재합산한 월 MM = 개인 MM(**정수 분 완전 일치**), Σalloc ≤ envelope, effort_min = Σalloc | 업로드 422 | 시나리오 83개 + 퍼즈 12,000 실행 완전 일치 |
| **G6 설정 read-check** | ① 모든 등록 키가 실제로 읽힌다(죽은 키 금지) ② 수치·선택 키를 섭동하면 결과(봉투·업무·MM·큐 서명)가 바뀐다 ③ 미등록 키 = 오류 | 머지 차단 | 키 110개 중 미사용 0(제품 전용 `time.tzOffsetMin` 1개 제외), 섭동 104개 전부 결과 변화 |
| **G7 구현 동치** | 실구현(정렬 구간 + 색인)과 참조 구현을 무작위 세계 1,000건에서 비교 → 슬롯 집합·귀속 초·업무 경계 동일 | 머지 차단 | 구현 단계 |
| **G8 PII 카나리아** | 시간 산출물(원장·attrib·team_tables·팀 묶음)에 합성 카나리아 본문·제목·문서명 문자열 0건 | 머지 차단 | 구현 단계(원장은 키·숫자만 담도록 설계) |
| **G9 성능** | 사람 1명 × 3개월 × 신호 약 4.3만~5만 건(심사 perf 분포) 실행 시간 ≤ 60초(개발 PC), 메모리 ≤ 500MB | 경고 → 2회 연속 차단 | 3개월 43,100 신호 **6.5초**(1개월 14,368 신호 0.9초). 원본 A 47초, C 515초, B 1,051초 |
| **G10 달력** | 2026-09 근무일 20, 2026-10 근무일 20, calendar.json 에 없는 해는 분석 거부, `zoneinfo.ZoneInfo` 미사용 | 머지 차단 | 통과 |
| **G11 LM24 회귀** | V1(W36)·V2(W62)·V3(G3)·V4(W37)·V5(W57)·V6(W42/W42b)·V7(W35·W50)·V8(W40)·V9(W28b)·V10(W23·W61)·V11(W38)·V12(W39)·V13(W53)·V14(W66)·V15(W64)·V16(W52·W52b, 근태 파서 자체는 분류 명세)·V17(W50/W50b)·V18~V26(W01~W16·W54·W56)·V27(W35)·V28(W48)·V29(G5)·V30(G6) | 리뷰 | 시나리오로 이식 완료 |
| **G12 큐 안정** | 같은 입력이면 같은 qid 집합, 주당 노출 ≤ maxPerWeek | 머지 차단 | 결정성 서명에 노출 qid 포함(G2 통과) |

실행:

```text
cd scratchpad\lm26_survey\design\worktime
python -B scenarios.py              # 83개 결과
python -B scenarios.py W17 W33      # 상세(업무·날짜 원장·구간 원장·큐)
python -B scenarios.py --check      # G4 골든 대조     (--freeze 로 다시 고정, --md 로 §9 표 생성)
python -B gates.py mono 1000 7      # G3 기본 세계        python -B gates.py mono2 1000 7   # G3 확장 세계
python -B gates.py order 4          # G2                python -B gates.py team           # G5
python -B gates.py cfg              # G6                python -B gates.py cal            # G10
python -B gates.py perf 3 26        # G9
```

---

## 11. 한계와 사용자 확인이 필요한 결정

### 11.1 한계

1. **오프라인 업무는 신호가 없으면 0 이거나 추정이다.** 대면 지시·대면 보고·현장 업무는 확인 큐(Q01·Q02·Q05·Q08·Q17)와 수동 기록만이 보완 경로다. 경계 추정이 틀려도 투입·MM 총량은 봉투가 지키지만, 리드타임·등급은 틀린다.
2. **PC 하한(C8)은 낮은 신뢰다.** 샘플러가 없는 날 '앵커 1건 + PC 켜짐'이면 표준창을 낮은 신뢰로 채운다(W39: 저장 1건 → 7.67h). 샘플러 보급이 근본 해결이다. 반대로 샘플러가 있으면 잠그지 않은 유휴 5시간은 0 이다(W32 4.00h) — 실제로 종이 검토였다면 과소다(Q08 로 묻는다).
3. **흔적 창(C10)은 넓을 수 있다.** 앵커 2건이 아침·밤에 하나씩 있으면 그 사이 정규 구역 전부가 낮은 신뢰로 들어간다(W65a: 09:07·21:30 발신 → 8h). 단조성을 위해 고른 규칙(심사 B 접목)이며 Q05 로 확인한다.
4. **발신 1통만 있는 PC 없는 날은 20분**이다(LM24 V11 의 '1통 = 1.0h' 는 단조성과 맞바꿔 버렸다). 보정 항목.
5. **업무용 웹 앱**(사내 웹 PLM·ERP·그룹웨어·웹 오피스)은 브라우저로 분류되면 창 밖 자격·L3 귀속을 놓친다. 정제기의 `work_site`(PRIVACY §12.6 `work_title_patterns`)·앱 카탈로그 등록이 필요하다.
6. **연결 키가 없으면 잇지 않는다.** 같은 일을 다른 이름의 문서로 하면 자체 업무로 갈라진다(W67a) — Q01·Q12 와 must_link 응답으로 보완. 공용 템플릿은 공용 문서 판정으로 미분류가 된다(W45).
7. **긴 메일 스레드 안의 화제 판정은 토큰 휴리스틱**이다. 토큰이 없는 '넵/완료' 보고가 연속되면 가장 최근 의뢰와 짝지어질 수 있다(등급은 유지되나 업무가 뒤바뀔 위험 → Q01).
8. **회의는 달력이 진실이라고 가정한다.** 불참한 수락 회의는 다른 업무 PC 입력이 90% 이상일 때만 의심하고(W44), 달력 없는 즉석 회의는 과소다.
9. **L6 비례 배분·회의 분할 0.5·불참 90%·휴면 5근무일·E2 가중치는 정책값**(★ 미보정)이다. §8.3 보정 도구로 사용자 자료에 맞춰야 한다.
10. **자정 넘는 근무의 꼬리표는 달력 날짜 기준**이다. '업무일(06시 경계)' 보고 묶음은 옵션으로 설계만 했다.
11. **샘플러 품질에 크게 좌우된다**(간격·고착·세션 상태 정확도). (PC, 날) 품질 판정이 실패하면 하한 폴백으로 내려가 신뢰가 떨어진다(W57).
12. **참조 구현은 설계 검증용 축약판**이다: 근태 파서, 화행 분류기, 정제기 판정, 확인 큐 화면, 팀 묶음 빌더는 다른 명세 소관이라 입력값으로 가정했다. `tzOffsetMin` 변환은 제품에서만 동작한다(시뮬레이터 입력은 이미 로컬 시각).

### 11.2 사용자 확인이 필요한 결정

| # | 결정 | 이 문서의 기본 | 선택지 | 영향 |
|---|---|---|---|---|
| D1 | 1MM 분모 | 공휴일 제외 근무일 × 8h(`mm.denominator=workdays`) | 달력 평일 전체(`weekdays`) | 2026-09: 160h 대 176h. 화면에 분모 정의 표시 |
| D2 | '연장' 정의 | 평일 표준창 밖(`mm.overtimeBasis=window`) | 일 8h 초과(`daily8h`), 주 40h 초과(미구현) | 정규창 밖에서 일하고 창 안에서 쉰 날 차이 |
| D3 | 표준 근무창 | 09:00~18:00, 점심 12~13, 저녁 18:00~18:30(개인 설정) | 시차 근무·유연근무 개인값 | 정규/연장 경계, 하한 범위 |
| D4 | 퇴근 후 AutoSave 편집(저장 이벤트 없음) | 업무 앱 전경 ≥ 15분이면 인정(W43) | 저장·발신이 있어야만 인정(C21b 방식) | 퇴근 후 문서 편집의 인정 여부 |
| D5 | PC 없는 날 발신 1통 | 직전 창 20분(팀즈 10분) | LM24 1.0h · 확인 전 0 | 외근일 과소/과대 |
| D6 | 추정 부재 | 확인 전 가용에서 빼지 않음(`confirm_only`) | `exclude` | 로드율 |
| D7 | date-only 게이트 | 끔(0h) | 켬(낮은 신뢰 하한 + Q06) | MS 수집 결손자 과소 대 근거 없는 시간 |
| D8 | 사적 판정 차감 | 정규 30분 이상 연속·창 밖 전부(PRIVACY R-P3·R-P4) | 문턱 조정(`privacy.time.*`) | 봉투 감소량 |
| D9 | 무증거 배분 | 직접 증거 비례, 상한 = 직접 × 1.0, 넘치면 버킷 | 상한 없음 / 버킷만 | 팀 보고서 '근무 중 미분류' 비중 |
| D10 | 반복 문서 판정 | ISO 주 ≥ 4 ∧ 주당 활동일 중앙값 ≤ 2 | 심사 B 원안(ISO 주 > 6) | 주간보고형 문서의 인스턴스 수 |
| D11 | 회의 혼합 | 6명 이상 회의 중 다른 업무 PC 입력 0.5/0.5, 그 미만은 회의 100% | 문턱·비율 조정 | 회의·문서 업무 간 배분 |
| D12 | 솔버 기계 시간 | 투입 미포함(`solverMode=anchor`), 기계 시간 열로만 | LM24 호환 cap(밤당 4h 투입) | 야간 초과 h |
| D13 | 팀 묶음의 단위업무 제목 | (결정 메모 §10.4: 정제된 제목 기본 포함) | 제목 제외 모드 | 간트 드릴다운 가독성 |
| D14 | 휴가 중 근무 | 연장으로 집계 + Q16, 부재일 수는 그대로 | 부재 취소 | 가용·로드율 |

### 11.3 다른 명세·오케스트레이터에 넘기는 일

- **명칭**: 결정 메모·형제 명세·모듈 경로·패키지명의 LM26 / loadmon26 표기를 LM27 / loadmon27 로 옮긴다(오케스트레이터). 이 문서는 처음부터 LM27 기준으로 썼다.
- 정제기(`PRIVACY.md`): 창 표본 `priv_class` 를 시간 코어 입력에 그대로 싣는다(R-P3~R-P6 구현 전제). `work_site` 패턴 배포 경로.
- 수집(`COLLECTION.md`·`COLLECT_PC.md`): 문서군 정규화 `fam()` 을 `lm27/time/tokens.py` 하나로 공용화, `pc_file.folder` 에 상위 폴더 해시 2단계, 샘플러 표본에 `idle_sec` 보존(고착·다중 PC 판정), 회의 일정에 `personal`·`online` 표식.
- 화행 분류기(정규화 단계): `act ∈ {request, ack, question, report, info, notice, social}` — '기한 있는 질문'은 request 로 올리는 규칙(B).
- 팀(`TEAM_AND_BUNDLE.md`): §4.11 코드 대응표와 §5.6 정수 분 표를 묶음 빌더 입력으로. **`units[].end.kind` 열거에 `E3i` 추가(MINOR)** — 휴면 추정·NEXT_REQ 종료를 담는다. 최대잉여 동률 규칙은 팀 R-3 과 같다(키 사전순 — `u_*` 업무와 `B_*` 버킷을 함께 정렬).
- PRIVACY(`PRIVACY.md` §9.3): `keyed(kr, "unit", …)` 하위 키를 시간 코어가 단위업무 ID 에 쓴다.

---

## 부록 A. 구현 인터페이스(모듈·함수 시그니처)

`lm27/time/` — 개인 PC·클라우드PC·팀 서버가 **같은 모듈**을 쓴다(LM24 사본 drift 교훈 X5). 결과에 `core_version`(형식 `timecore/<판>`, 이 문서 = `timecore/1` — 팀 묶음 `generator.core_version`)·`calendar_version`·`cfg_hash` 를 싣는다. 이 문서의 산식·기본값이 바뀌어 같은 입력의 결과가 달라지면 판을 올린다.

```python
# lm27/time/registry.py
DEFAULTS: dict[str, object]; UNCALIBRATED: set[str]
class Cfg:                                    # 미등록 키 오류, 형 불일치 → 기본값 + 경고, 읽힌 키 기록
    def __init__(self, overrides: dict | None = None): ...
    def __getitem__(self, key: str) -> object: ...
    def used(self) -> dict[str, object]: ...  # run_meta.cfg_used

# lm27/time/calendar.py
class Calendar:
    def __init__(self, path: Path, company_off: Iterable[date] = (), weekdays: Iterable[int] = (0, 1, 2, 3, 4)): ...
    version: str
    def is_holiday(self, d: date) -> bool: ...            # calendar.json 에 없는 해 → ValueError(fail-closed)
    def wd_between(self, d1: date, d2: date) -> int: ...  # (d1, d2] 근무일 수, 누적합 O(1)
    def month_workdays(self, y: int, m: int) -> int: ...
    def month_weekdays(self, y: int, m: int) -> int: ...
def build_days(ev: "Evidence", cfg: Cfg, cal: Calendar) -> dict[date, DayInfo]: ...
def slot_tag(slot: int, days: dict, cfg: Cfg) -> Literal['정규', '연장', '야간', '휴일']: ...

# lm27/time/intervals.py
def U(iv) -> list[tuple[int, int]]: ...;  def I(A, B): ...;  def SUB(A, B): ...;  def L(A) -> int: ...
class IvIx:                                   # 이분 탐색 색인
    def has(self, t: int) -> bool: ...; def hit(self, a: int, b: int) -> bool: ...; def clip(self, a: int, b: int): ...
def pre_iv(t: int, pre_s: int) -> tuple[int, int]: ...
def split_int(total: int, weights: dict) -> dict: ...  # 최대잉여, Σ = total
def lr_minutes(sec_by_key: dict, total_min: int) -> dict: ...

# lm27/time/tokens.py  (수집기와 공용)
def fam(name: str) -> str: ...;  def doc_key(name: str, folder: str) -> str: ...;  def is_generic(f: str, cfg: Cfg) -> bool: ...
def raw_tokens(parts: Iterable[str], boiler: set[str]) -> set[str]: ...
def tok_sim(a: set[str], b: set[str], min_sub_len: int = 2) -> float: ...

# lm27/time/evidence.py
@dataclass(frozen=True) class Samp / PcSpan / Msg / Meet / DocE / Comp / Commit / Man   # §2.2.1
@dataclass class Evidence: samples; pcon; msgs; meets; docs; comps; commits; manual; leaves; coverage; audit; as_of; d0; d1; common_tokens; utc_suspect; shared_docs
def normalize(records: Iterable[dict], profile: dict, cfg: Cfg, as_of: int, registry: dict) -> Evidence: ...

# lm27/time/envelope.py
@dataclass class Envelope: slots: set[int]; basis: dict[int, str]; comp_cov: dict; ledger: dict[date, Counter]; flags: dict
                           anchors: list; anchor_sessions: list; counted_meetings: list; tentative_unconfirmed: list; reg: list
def build_envelope(ev: Evidence, cfg: Cfg, days: dict) -> Envelope: ...

# lm27/time/episodes.py
@dataclass class Cycle: s: int; sb: str; e: int | None; eb: str | None; s_ref: str | None; e_ref: str | None; interim: list; unstarted: bool
@dataclass class UnitTask: id: str; label: str; kind: str; conv: str; peer: str; peers: set; tokens: set; docs: dict[str, int]
                           cycles: list[Cycle]; p_times: list[int]; flags: list[str]; grade: str; status: str; machine_s: int
                           proj: str | None; first_key: str; pre_from: int | None; follow_of: str | None; labels: dict
def build_tasks(ev: Evidence, env: Envelope, days: dict, cfg: Cfg, cal: Calendar) -> tuple[list[UnitTask], list[QueueItem]]: ...
def grade_of(sb: str, eb: str | None) -> str: ...
def completion(task: UnitTask, cycle: Cycle, nxt: int, ctx) -> tuple[int, str, float] | None: ...

# lm27/time/attribute.py
def attribute(ev: Evidence, env: Envelope, tasks: list[UnitTask], days: dict, cfg: Cfg)\
        -> tuple[dict[int, dict[str, int]], dict[int, str]]: ...      # (슬롯 → {업무|버킷: 초}, 슬롯 → 단계)
def resolve(fam_key: str, t: int, ctx) -> dict[str, int] | Literal['B_GENERIC'] | None: ...

# lm27/time/mm.py
def month_mm(env, assign, days, cfg, cal, as_of) -> dict[tuple[int, int], MonthMM]: ...
def team_tables(slots, assign, days, cfg) -> dict: ...                 # envelope_daily · alloc_daily(정수 분)
def rollup(month: MonthMM, labels: dict[str, dict]) -> dict[str, dict[str, float]]: ...   # 영역·과제·역할·유형

# lm27/time/ledger.py
def day_ledger(result, day: date) -> str: ...; def interval_ledger(result, day: date) -> list[str]: ...
def task_ledger(result, task_id: str) -> str: ...

# lm27/time/queue.py
@dataclass class QueueItem: qid: str; code: str; target: str; impact_h: float; evidence_keys: list[str]; proposal: dict; status: str
def make_queue(ev, cfg, env, tasks, days, effort, assign, attrib_ctx) -> list[QueueItem]: ...
def prioritize(items: list[QueueItem], cfg: Cfg) -> list[QueueItem]: ...

# lm27/time/__init__.py
def analyze_time(person_key: bytes, records: Iterable[dict], profile: dict, calendar_path: Path,
                 as_of: datetime, overrides: dict | None = None) -> TimeResult: ...
    # normalize → build_days → build_envelope → build_tasks → attribute → month_mm·team_tables → make_queue → 원장·결과 파일(§7.5)

# tools/calibrate.py
def calibrate(records, truth: list[Man], keys: list[str], grid: dict[str, list], cfg: Cfg) -> CalibrationReport: ...
```

---

## 부록 B. 심사 반영 대조

### B.1 골격·접목

| 심사 항목 | 반영 위치 | 확인 시나리오·관문 |
|---|---|---|
| 골격 A(C1~C12, L1~L7, 조합표, 정수 초 보존, 결정적 qid) | §3·§4.10·§5·§7.3 | 전 시나리오, G1·G2 |
| P1 최소 크레딧 = 직전 창, 권위 = 부정 증거 | §3.4 | W29a/b, G3 |
| P2 창 밖 자격 = 골격 ±30분 | §3.2 | W27·W26·W26b·W34 |
| P3 흔적 창 합집합 + 원격 흔적 창 | §3.8 | W33·W38·W65a/b, G3 |
| [B] 키 사슬(강한 키 단독·약한 키 합산·시간창) | §4.5 | W21·W23·W24·W24b |
| [B] 1:1·그룹 상시 대화방 짝짓기 | §4.2·§4.3 | W17 |
| [B] 반복 문서 ISO 주·follow_of | §4.4 | W20 |
| [B] cannot-link·증거 키 응답·IDF·문서 불용어·거대 성분 가드 | §4.1·§4.5·§2.7 | W24·W67b·W47b |
| [B] 봉투 단조화(합집합형 하한·흔적 창) | §3.7·§3.8 | G3 |
| [B] 정준 정렬·순서 퍼즈·구현 동치 | §2.4·§10 | G2·G7 |
| [C] 최소 크레딧 직전 창(비대칭) | §3.4 | W29a/b |
| [C] 창 밖·휴일 골격 단위 인정 | §3.2 | W27 |
| [C] 분 단위 맥락(다중 PC·RDP·회의 혼합) | §5.3 L3·L2 | W40·W41·W44 |
| [C] 공백 라벨·일반 앱 흡수·솔버 흡수 | §5.3 L5 | W17·W38·W42 |
| [C] 버킷 5종·귀속률 | §5.4 | 전 시나리오 |
| [C] ACK 시작·의뢰자 회의 S2m/E3c·NEXT_REQ·pre_request_h | §4.2·§4.7·§4.9 | W14·W05·W08·W16·W15 |
| [C] 한국어 부분 문자열·같은 방 다른 화제 새 업무 | §4.1·§4.2 | W23·W17 |
| [C] 수신 크레딧 후선택 | §3.10 | W62·W36 |
| [C] 원격 연결 다리 | §3.5 | W61 |
| [C] 구간 원장(버린 시간 포함) | §7.4 | — |
| [B·C] 퍼즈 관문 1,000건 이상 | §10 G3 | 6,000 세계 |

### B.2 must_fix

| must_fix | 처리 |
|---|---|
| [달력] 9/28 대체공휴일 오류, 내장 표 금지 | calendar.json 단일(§2.5), G10, 골든 재생성(W51 0.9875·원본 A S35 → 0.9375/1.014) |
| [A 창 밖 자격] | 골격 ±30분(§3.2), 점심 동일 규칙 — W27 9.17h |
| [A 단조성 1] P5 샘플러 권위 | 직전 창 늘 부여 + 부정 증거만 빼기(§3.4), 단조성 정의(§3.12) — W29a = W29b |
| [A 단조성 2] C10 체제 전환·X33 | 합집합형 C10·C10r(§3.8) — W65a = W65b, W33 7.00h |
| [A 1:1 상시 대화방] | 화제 다르면 새 업무, 보고 = 토큰 겹침 최대 의뢰(§4.2·§4.3) — W17 |
| [A 반복 문서] | ISO 주 분리(§4.4) — W20 8개 |
| [결정 v2 누락] (a) S1o/E1i (b) 다대다·E1p (c) E3c (d) 사적 차감 마지막 단계·원장 (e) calibrate·미보정 | (a) §4.2 W19 (b) §4.3 W18 (c) §4.7 W08 (d) §3.11 W48·W48b (e) §8.3, ★ 표식 |
| [date-only 게이트] 기본 false, B 의 빈 E 업무 | `dateOnlyGate=false`(W35 0h), date-only 발신만으로는 업무를 만들지 않는다(W35 업무 0개) |
| [한국어 토큰] | 부분 문자열 Dice + 상용구·IDF 하나의 정제 모듈(§4.1), fam() 수집기 공용 — W23 |
| [커버리지 판정] | E3i 보류 + Q03(§4.9.4) — W55 |
| [접목 금지 — B 봉투] (1) 가동 − 잠금 하한 (2) 아무 앱 샘플러 봉투 (3) bridge45 잠금 (4) 같은 스레드 무조건 차수 (5) 문서 키 원형 단독 병합 | (1) 하한 = 가동 − 샘플러 커버(W32 4.00h) (2) 창 밖 자격(W26·W34) (3) 창 밖 잠금 단절(W28) (4) 화제 확인(W22) (5) fam + 폴더 해시 + 범용 불용(W21) |
| [접목 금지 — C 봉투] (1) 날 단위 하한 스위치 (2) 회의 사이 다리 (3) 점심 아무 관측 (4) 하한 흔적 ±30 축소 (5) 메일 항상 related (6) 최근 업무에 보고 (7) E2 입력 필드 | (1) (pc, 시각) 단위(W30a = W30b, W31a ≥ W31b) (2) 금지(W37 4.00h) (3) 점심 자격(W34) (4) 표준창 하한 유지(W39 7.67h, W36) (5) 화제 확인(W22) (6) 토큰 최대 짝(W17·W18) (7) 계산 규칙(§4.9.2) |
| [정수 보존] | 슬롯마다 split_int, 팀 표는 정수 분 최대잉여(§5.1·§5.6) — G5 정수 일치 |
| [성능 관문] | 이분 색인·일별 처리(G9 6.5초/43,100 신호), 상한 60초 |
| [명칭] | 이 문서는 LM27 기준. 다른 산출물 이관은 오케스트레이터(§11.3) |

### B.3 심사 extra 시나리오 대응

| extra | 시나리오 | 결과 |
|---|---|---|
| X06b ≤ 9.2h | W27 | 9.17h |
| X12 ≥ X12b | W31a/b | 7.83 ≥ 7.67 |
| X13 4.00h + 공백 큐 | W32 | 4.00h, Q08 |
| X19 업무 2개 A·A | W17 | 3.17 / 2.92, A·A |
| X20 다대다 | W18 | 둘 다 E1(A) |
| X21 조율형 | W19 | COORD 1개 A, 2.67h |
| X22 인스턴스 8개 | W20 | 8개 × 1.17h |
| X23 분리 | W21 | 2.50 / 11.50 |
| X24 새 업무 | W22 | 2개 |
| X25a/b 비감소 | W29a/b | 0.50 = 0.50 |
| X25c/d PC1 하한 유지 | W30a/b | 7.67 = 7.67 |
| 퍼즈 seed 7 #6 | W65a/b | 8.50 = 8.50 |
| X33 ≈ 7h + T2 | W33 | 7.00h + Q05 |
| X26 8.0h | W34 | 8.00h |
| X27 0h / 옵션 low + T3 | W35/W35b | 0h / 7.67h + Q06 |
| X30 E3c C | W08 | E3c, C, 끝 = 회의 끝 |
| X14 V1 | W36 | 6.17 / 7.08 / 0 |
| X15 V4 4.0h | W37 | 4.00h |
| X09 5.0h + 외근 큐 | W38 | 5.00h + Q05 |
| AutoSave 퇴근 후 정책 | W43/W43b | 인정 0.67h(정책 D4) / E2h |
| 회의 불참 의심 | W44 | 봉투 8h, PC 업무, Q14 |
| 공용 마스터 엑셀 | W45 | B_GENERIC 8.92h, 쏠림 없음 |
| 월 경계 자정 | W46 | 9월 야간 1.0 / 10월 야간 1.5 |
| 확인 응답 지속 | W47a/b | E → B, ID 바뀌어도 유지 |
| 사적 30분 차감 | W48 | −0.50h, 원장 기록 |
| 놓친 활동 알림만 | W49 | 0h |
| COM + 웹 사본·UTC | W50/W50b | 1건 병합, Q13 / 보정 후 주간 |
| 3개월 × 5만 관문 | G9 | 6.5초, G1·G5 통과 |

---

## 부록 C. 참조 구현 파일

| 파일(`scratchpad\lm26_survey\design\`) | 내용 |
|---|---|
| `worktime_sim.py` | 엔진: 설정 레지스트리·달력·정규화·봉투·단위업무·귀속·MM·팀 정수 표·확인 큐·원장 |
| `worktime\scenarios.py` | 시나리오 83개(W01~W67b), `--check`(골든)·`--freeze`·`--md`(§9 표) |
| `worktime\golden.json` | 골든 값 |
| `worktime\gates.py` | G2·G3(기본·확장)·G5·G6·G9·G10 실행기 |
| `worktime\gates_out.txt` · `scenarios_out.txt` · `table.md` | 실행 결과 |
| `judge\` | 심사 산출물(교차 시나리오·퍼즈·성능, 읽기만) |
