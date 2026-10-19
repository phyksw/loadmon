# -*- coding: utf-8 -*-
r"""
attendance.py — 출퇴근·근무 시간 추정 (LoadMonitor30 · LM30(2026-10-18))

이 PC가 이미 모으는 흔적만으로 날마다 언제 일을 시작해 언제 마쳤는지를 어림하고, 그 근무 시간으로 투입 MM을 잽니다.
새 수집기·상주 프로그램·이벤트 로그 원천은 쓰지 않습니다. 계산 함수뿐이고, 파일은 근태 기록 칸(load_records)만 읽습니다
(결과 저장은 core\extract.save_attendance). 분·시간 값은 config.attendance 로 바꿀 수 있습니다(norm).

규칙
 1. 근거
    · 확실한 흔적 — 내가 저장한 파일·코드, 커밋, 내가 보낸 메일·팀즈(그 시각의 한 점) · 수락한 회의, 시작·끝을 적은 수동 기록,
      출장·현장 약속(그 구간). 받은 메일·팀즈, 열어 보기만 한 파일, 날짜만 아는 글, 해석 프로그램이 쓴 출력은 근거가 아닙니다.
      수동 기록 신호의 09:00은 자리표라 점으로 쓰지 않습니다 — 수동 기록은 구간(시작·끝)이나 시간(바닥값)으로만 씁니다.
    · 약한 흔적 — 브라우저 방문 시각. 덩어리의 첫·마지막 확실한 흔적에서 60분 안일 때만 시작·끝을 늘립니다. 방문끼리 잇거나
      방문만으로 근무를 만들지 않습니다(밤새 저절로 새로 고친 페이지가 야근이 되지 않게).
    · PC 켜짐 — 켜기·로그온·잠금 해제·절전 해제·원격 접속부터 끄기·로그오프·잠금·절전까지(수집하는 동안 켜져 있었으면 지금까지).
      시작·끝 시각을 정할 때 쓰고(3·4), 10분 이하로 끊긴 켜짐(업데이트 재부팅·잠깐 잠금)은 하나로 잇습니다.
      LM30(2026-10-20) PC 를 실제로 쓴 시간 자체도 근무 재료입니다(19 — attendance.pcUsage, 기본 켬). 끄면 예전처럼 시작·끝에만 쓰고,
      흔적 없이 켜져만 있던 PC 는 근무가 아닙니다. 켜도 잊고 켜 둔 PC(16시간 넘게 이어진 켜짐)·업데이트 깨움은 근무로 세지 않습니다.
 2. 덩어리 — 흔적을 시각 순으로 놓고 공백이 90분 이하면 잇습니다. 낮(08~19시 — mm.pcFloorWindow) 안의 공백은 PC가 그 공백의
    80% 이상 켜져 있었으면 4시간까지 잇습니다(자리에서 읽기·실험·점심). 저녁·밤은 90분만 잇습니다 — 켜 둔 PC가 18:30과
    22:50을 한 덩어리로 만들지 않게.
 3. 시작 — 첫 흔적 전 2시간 안에 PC를 켰고 그 뒤 계속 켜져 있었으면 켠 시각 → 첫 흔적이 회의·수동 기록·출장이면 그 시작 →
    60분 안의 브라우저 방문 → 첫 흔적 30분 전.
 4. 끝 — 마지막 흔적 뒤 90분 안에 PC를 껐으면(끄기·로그오프·잠금·절전) 그 시각 → 마지막이 회의·수동 기록·출장이면 그 끝 →
    60분 안의 브라우저 방문 + 5분 → PC가 지금도 켜져 있고 마지막 흔적이 30분 안이면 지금(일하는 중) → 마지막 흔적 30분 뒤.
 5. PC 밖 — PC가 한 번도 켜져 있지 않던 덩어리(휴대폰·집)는 앞뒤를 10분만 붙입니다(회의·수동 기록 구간은 그대로). 그날 PC
    기록이 전혀 없으면 PC 밖 시간으로 세지 않습니다 — 기록이 없는 것과 꺼져 있던 것은 가를 수 없습니다.
 6. 근무일 — 덩어리가 시작한 날입니다. 새벽 5시 전에 시작한 덩어리는 전날 근무입니다. 자정을 넘긴 덩어리는 나누지 않고
    퇴근 시각에 '다음 날'을 붙입니다.
 7. 하루 — 출근 = 첫 덩어리 시작 · 퇴근 = 마지막 덩어리 끝 · 체류 = 덩어리 길이의 합. 휴게는 근태 시스템처럼 4시간마다
    30분이고, 덩어리 사이 15분 이상 빈 시간(한 번에 60분까지)은 이미 쉰 것으로 칩니다. 근무 = 체류 − 남은 휴게.
 8. 바닥값(LM29에서 이어 받음) — 종일 출장·교육일은 표준일(8시간 × (1 − 휴가)) · 시간만 적은 수동 기록 · PC 기록이 없는 날은
    LM29 방식 시간 · 덩어리가 없는 날의 날짜만 아는 발신 · 덩어리가 하나도 없는데 LM29 방식이 시간을 센 날은 그 시간
    (근거가 얇다는 이유로 LM29가 센 날을 버리지 않습니다). 이웃 날 덩어리가 그날 새벽을 이미 덮었으면 그만큼 빼고 씁니다
    (두 번 세지 않게). 24시간이 물리 한계이고, 16시간이 넘으면 표시만 합니다.
 9. 나눔 — 휴일 근무는 전부 휴일 시간 · 평일은 8시간 × (1 − 휴가)까지 정규, 넘으면 연장(반차면 4시간부터 연장) · 종일 휴가일에
    일하면 전부 연장('휴가일 근무') · 야간(22~06시)은 따로 겹쳐 셉니다 · 20시가 넘어 퇴근하면 늦은 퇴근입니다.
 10. 신뢰도 — 높음: 출근·퇴근 둘 다 PC·회의·수동 기록·출장 시각(LM30 2026-10-20 — PC 사용 구간의 시작·끝 pcuse 도) · 보통: 한쪽이라도
     어림(30분 앞뒤·브라우저·지금 · 켜 둔 날의 낮 창 pcwin) · 낮음: LM29 방식 시간·바닥값을 쓴 날이거나 그날 PC 기록이 없는 날.
 11. 합계 — 주(월~일: 40시간을 넘은 시간·52시간을 넘은 주) · 달 · 전체. 평소 출근·퇴근(최근 28일 평일의 가운데 값)은
     이 PC에만 둡니다.
 12. 근태 기록 칸 — data\근태\*.csv(날짜·출근·퇴근, 있으면 휴게(분)·인정연장·휴가 · 입실·퇴실)를 넣으면 날마다 근태 기록과
     견주어 +@(아래 14)를 셉니다. 폴더가 없으면 견주지 않습니다(오류 아님). 읽지 못한 행은 건너뛰고 개수만 셉니다.
     LM30(2026-10-19): 날짜만 있고 출근·퇴근·휴가가 빈 행(휴일·기록 없는 날)은 읽지 못한 행이 아니라 빈 날 — 파일 기간에만 넣습니다.
     GERP 근무 기록 읽기(시험 기능 — config.attendance.gerp, 기본 꺼짐 · norm_gerp)가 같은 칸에 gerp.csv 를 모읍니다.
 13. 개인정보 — 날짜별 출근·퇴근 시각·덩어리·평소 시각은 report\attendance_<기간>.json(이 PC)에만 둡니다. mm_meta·팀 업로드·
     공유폴더 사본의 출퇴근 절·Copilot에는 주·달 합계만 갑니다(take_local·scrub_meta가 떼어 냅니다).
     LM30(2026-10-19): 근태 기록·GERP·태깅에서 나온 값(비교 요약 records · unrecorded_h · plus_h · missing_h · gate_plus_h ·
     날짜별 rec)은 합계라도 이 PC 밖으로 내보내지 않습니다 — 팀으로 가는 합계는 근태 기록 없이 다시 잰 것(compute 의 team)뿐이고,
     strip_hr·scrub_meta 가 나가기 직전에 한 번 더 뺍니다.
     ([공유폴더로 저장]이 복사하는 얼린 보고서 원문 포함본의 '수집 데이터 열람' 원자료 — PC 켜고 끈 시각 등 — 는 LM29와 같습니다.)
 14. +@ — 근태 기록 = 확실히 일한 부분, +@ = 그 밖에서 LM이 찾은 근무(LM30(2026-10-19)). 투입 MM 은 그대로 LM 이 잰 근무시간
     (work_h)이고 근태 기록은 참고입니다(MM 을 바꾸지 않는다).
     · 근태 기록이 있는 날(기록 칸 기간 안) — 근태 창 = [출근, 퇴근](퇴근이 이르면 다음 날). +@ = 그날 덩어리 중 창 밖(일찍 온 시간·
       늦게 간 시간·따로 떨어진 저녁·PC 밖 덩어리)의 근무. 휴게는 근태 기록이 뺀 만큼(휴게 열, 없으면 4시간마다 breakPer4hMin)을
       창 안에서 먼저 빼고, 그래도 남은 LM 휴게(더 길게 일해 늘어난 휴게)는 창 밖에서 뺍니다(퇴근 뒤 쪽 먼저) — 창 안 근무 + +@ =
       덩어리 근무. 시각을 모르는 근무(LM29 방식·시간만 적은 수동 기록·출장 표준일로 채운 시간)는 창 안으로 봅니다.
       기간 안인데 근태 행이 없는 날(빈 날 포함)·종일 휴가인 날·출퇴근 시각이 없는 날의 근무는 전부 +@ 입니다.
     · missing_h(참고) = 근태 창 중 LM 이 흔적을 못 본 시간 − 근태 휴게 − 시각을 모르는 근무(회의·실험처럼 PC 를 떠난 시간).
     · gate_plus_h(참고) = 입실~퇴실(태깅) 중 근태 창 밖에 있던 시간 — 건물에 더 머문 시간이고 근무에 더하지 않습니다.
     · 근태 기록이 없는 날(기록 칸 기간 밖·기록 칸 없음) — +@ 추정 plus_est_h = 연장 + 휴일(평일 8시간 넘은 시간 · 휴일 근무 전부 ·
       종일 휴가일 근무 전부), 그중 PC 밖 plus_est_offpc_h = min(PC 밖, 추정). GERP 를 못 읽어도 +@ 가 늘 보입니다.
     · 합계(주·달·전체) — plus_h(근태와 견준 것) · plus_est_h(기록 없는 날의 추정) · plus_all_h(둘의 합 = +@) · plus_days ·
       missing_h · gate_plus_h · rec_days · gate_days. 팀으로 가는 합계(team)에는 근태가 없으므로 모든 날이 추정 — plus_est_h 만.
     보여 주기(day_why·usual_text·headline·rule_text·records_text·plus_line·day_plus — 맨 끝)는 화면 카드·리포트가 같은 쉬운 말을
     쓰게 하는 문구 도구입니다.
 15. LM29 보다 적게 세지 않음(config attendance.withLM29 · LM30(2026-10-19)). 엄격한 LM30 방식은 저녁·주말·
     휴일처럼 흔적이 드문 시간을 LM29 보다 적게 셌다(실측 로드율 108% → 94% — 토요일 10시·17시 저장이면 PC 가 종일 켜져 있어도 두 시간).
     LM30(2026-10-20) 기본 끔(키가 없어도 끔) — 사용자: "굳이 LM29 결과를 넣을 필요가" · 그 빈 곳은 PC 사용 시간(19)이 맡는다. 견줘 볼
     때만 켠다(코드는 그대로).
     켜 두면
     · LM29 가 시각까지 정해 근무로 센 구간(PC 하한 — 점심·저녁·절전을 뺀 뒤 그대로 센 날만 · 시차 근무 창 밖 인정 · 저녁 인정(자정 넘김
       포함) · 새벽 인정 · 주말 산출물 창 · 야간 해석)을 확실한 흔적처럼 덩어리에 넣는다(종류 lm29 — LM29 가 이미 근무로 봤으니 그것만으로도
       덩어리가 된다). 시작·끝은 LM29 구간의 시작·끝 그대로(앞뒤를 붙이지 않는다)와, 확실한 흔적으로 위 3·4 대로 잡은 시각 중 넓은 쪽이다.
       잇기(2)·근무일(6)·휴게(7)는 예전 그대로 합친 흔적 위에서 한다.
     · 모든 날 근무 = max(덩어리 근무, 그날 LM29 방식 시간 − 이웃 날 덩어리가 이미 덮은 시간)(8 의 바닥값을 모든 날에) — 시각 없이 센
       LM29 시간(표준일·날짜만 아는 발신·출장)도 잃지 않는다. 이 바닥값이 늘린 날의 나눔은 9 와 같고(평일 정규 → 연장 · 휴일은 휴일),
       야간은 덩어리 야간과 LM29 야간 꼬리표 중 큰 쪽이다.
     · LM30 방식이 더 찾은 것(PC 밖 저녁 덩어리·자정 넘김·시작·끝을 적은 수동 기록)은 그대로 더한다 — LM29 구간 없이 만든(엄격한)
       덩어리로 잰 근무·PC 밖 시간보다도 적게 세지 않는다(LM29 구간으로 이어 붙인 공백은 예전처럼 쉰 시간으로 본다 — 4시간마다 휴게
       규칙 때문에 이어 붙이면 오히려 줄던 것). false 면 예전(엄격한 LM30) 그대로.
 16. 시간외 나눠 보기(LM30(2026-10-19)) — 날·주·달·전체에 weekend_h(토·일 근무) · offday_h(주말 + 공휴일 근무 = holiday_h) ·
     evening_h(덩어리 중 19~22시) · night_h(22~06시 — 예전 그대로)를 낸다. 모두 투입(work_h)에 이미 든 시간을 나눠 본 값이다(LM 이 잰
     합계라 팀에 올려도 된다 — strip_hr 가 빼지 않는다).
 17. 발신 흔적 빈 곳(send_gap — LM30(2026-10-19)) — 분석 기간 끝 14일 안에 PC 를 켠 평일이 3일 이상인데 내 메일·팀즈 발신(시각 있는
     것·날짜만 아는 것 모두)이 하나도 없거나, PC 를 켠 평일이 5일 이상인 달에 발신이 하나도 없으면 두 카드가 경고한다(건수·날짜만 —
     메일 글은 보지 않는다). 새로 깐 PC 는 전용 Edge 에 한 번 로그인해야 메일·팀즈를 읽고, 저녁·주말 근무는 주로 그 발신으로 잡힌다.
 18. (번호만 둔다 — 법정 채움 MM(1MM = 그달 평일 전부 × 8시간)은 이 판에 없다. 19 는 같은 계산을 쓰는 다른 판과 번호를 맞췄다.)
 19. PC 사용 시간(LM30(2026-10-20) — config attendance.pcUsage, 기본 켬 · 키가 없어도 켬 · false = 예전 숫자 그대로). 사용자: "주말 근무를
     했는데 체크가 안 되고, 일정이나 HR 근태에 너무 연연했다 — PC 사용시간 로그도 봐야 하지 않았을까". 이미 모으는 PC 켜짐 기록(pc_spans 의
     이벤트 구간 — 브라우저 방문·창 샘플러 아님)에서 PC 를 실제로 쓴 구간을 만들어(pc_usage — 순수 함수) 덩어리 재료(종류 pc)로 넣는다.
     · 겹치거나 10분 이하로 끊긴 조각은 잇는다(자정에서 자른 조각·겹친 원장 행도). 수집 직후의 현재 세션은 지금까지(_Pres 와 같다).
     · pcUsageMaxSpanH(16시간)를 넘게 이어졌거나 20시간 캡으로 닫힌(event-cap) 켜짐 = 켜 둔 채(쓴 시간 모름) — 그 켜짐이 걸친 날 중
       확실한 흔적(해석 출력 아님 · 근무일은 6 의 dayStartHour 규칙)이 하나라도 있는 날만 그날 낮 창(mm.pcFloorWindow 08~19시) ∩ 켜짐
       (종류 pcwin — 예전 PC 하한의 '흔적 있는 날만' 규칙). 낮 창과 겹친 날은 모두 '켜 둔 날'(always_on_days — 흔적이 없으면 0시간)이고,
       근무가 있는 날의 행에는 AO_NOTE 를 단다.
     · pcUsageMinMin(15분)이 안 되는 켜짐은 안에 확실한·약한 흔적이 없으면 뺀다(업데이트 깨움·잠깐 켬).
     · 00~06시 안에 다 든 60분 미만 켜짐은 안에 확실한 흔적이 없으면 뺀다(새벽 업데이트 깨움 — 밤새 저절로 새로 고친 브라우저 방문은
       흔적으로 치지 않는다).
     PC 사용 구간의 시작·끝은 그대로 가장자리다(앞뒤를 붙이지 않는다 — 이름 pcuse, 신뢰도 높음 · 켜 둔 날의 낮 창은 pcwin, 어림이라 보통 ·
     지금까지 쓰는 중이면 now). 흔적 없이도 덩어리가 된다 — 주말·휴일·밤에 PC 를 쓴 시간은 저장·발신이 없어도 근무다. 확실한 흔적의
     가장자리(3·4)와 겹치면 넓은 쪽. 잇기(2)·합치기·근무일(6)·휴게(7)는 예전 그대로 합친 재료 위에서 한다. 다만 확실한 흔적만으로 만든
     (엄격한) 덩어리로 잰 근무·PC 밖 시간보다 적게 세지 않는다(15 와 같은 strict_bl — PC 사용 구간이 PC 를 끈 공백을 이어 이미 쉰 시간이
     근무가 되고 휴게가 늘어 오히려 줄지 않게). 날짜별 행에 pc_usage_h(그 근무일
     덩어리 안의 PC 사용 시간 — 휴게 빼기 전)·always_on, 합계(주·달·전체)에 pc_usage_h·pc_usage_off_h(그중 주말·휴일)·always_on_days 를
     더한다(LM 이 잰 합계 — 팀에 올려도 된다). 카드·리포트 문구는 pc_usage_lines. 끄면 행·합계에 이 칸이 없다(예전과 같은 글자).

시각은 '절대 분' — base 날짜 00:00부터 센 분 — 으로 다룹니다(자정을 넘는 덩어리를 그대로 잇기 위해).
"""
import bisect
import copy
import csv
import io
import math
import os
import re
import statistics
from datetime import date, timedelta
from urllib.parse import urlparse

# ── 설정 기본값·허용 범위(config.attendance) — 키가 없거나 블록이 없으면 기본값(useForMM 켬) ──
# LM30(2026-10-19) withLM29 — LM29 가 센 시간보다 적게 세지 않는다(머리말 15 · false = 엄격한 LM30 방식).
# LM30(2026-10-20) withLM29 기본 끔(키가 없어도 끔 — 견줘 볼 때만 켠다) · pcUsage(머리말 19 — PC 를 실제로 쓴 시간을 근무 재료로 · 키가
# 없어도 켬 · false = 예전 숫자) · pcUsageMinMin(이보다 짧은 켜짐은 흔적이 없으면 뺀다 — 업데이트 깨움) · pcUsageMaxSpanH(이보다 길게 이어진
# 켜짐은 켜 둔 채 — 쓴 시간 모름)
DEFAULTS = {"useForMM": True, "withLM29": False, "pcUsage": True, "pcUsageMinMin": 15, "pcUsageMaxSpanH": 16, "leadMin": 30,
            "tailMin": 30, "pcEdgeBeforeMin": 120, "pcEdgeAfterMin": 90, "bridgePcMin": 240, "bridgeAwayMin": 90, "webJoinMin": 60,
            "offpcPadMin": 10, "breakPer4hMin": 30, "dayStartHour": 5, "weekHours": 40, "weekMaxHours": 52}
RANGES = {"pcUsageMinMin": (0, 120), "pcUsageMaxSpanH": (4, 24), "leadMin": (0, 240), "tailMin": (0, 240),
          "pcEdgeBeforeMin": (0, 480), "pcEdgeAfterMin": (0, 480), "bridgePcMin": (0, 720), "bridgeAwayMin": (0, 480),
          "webJoinMin": (0, 240), "offpcPadMin": (0, 120), "breakPer4hMin": (0, 120), "dayStartHour": (0, 12),
          "weekHours": (1, 80), "weekMaxHours": (1, 120)}
SPAN_KINDS = ("meeting", "manual", "offsite")     # 구간 흔적 — 그 시작·끝이 곧 가장자리
# LM30(2026-10-20) pcuse = PC 사용 구간(머리말 19)의 시작·끝(켜기·로그온·절전 해제 ~ 끄기·로그오프·절전 — 기록된 시각) · pcwin = 켜 둔
# 날의 낮 창 가장자리(어림)
HARD_SRC = ("pc", "meeting", "manual", "offsite", "pcuse")   # 기록된 시각인 가장자리(신뢰도 높음)
EST_SRC = ("lead", "tail", "web", "lm29", "pcwin")           # 어림한 가장자리(est_edge_days)
# LM30(2026-10-19) LM29 구간의 종류(머리말 15) — LM29 가 시각까지 정해 센 근무 구간. 그 가장자리는 'PC 켜진 시간(LM29 방식)'(신뢰도 보통)
L29_KIND = "lm29"
# LM30(2026-10-20) PC 사용 시간(머리말 19) — 덩어리 재료의 종류: pc = PC 를 실제로 쓴 구간 · pcwin = 켜 둔 채인 PC(쓴 시간 모름)의 흔적
# 있는 날 낮 창. 둘 다 가장자리를 그대로 쓰고(앞뒤를 붙이지 않는다) 흔적 없이도 덩어리가 된다. 그 가장자리 이름은 PCU_EDGE·PCW_KIND
PCU_KIND, PCW_KIND, PCU_EDGE = "pc", "pcwin", "pcuse"
PCU_KINDS = (PCU_KIND, PCW_KIND)
SOFT_KINDS = (L29_KIND,) + PCU_KINDS               # 확실한 흔적이 아닌 구간 — 가장자리 규칙 3·4 의 재료가 아니다(clusters 의 rs·re 밖)
CAP_SRC = "event-cap"                              # 끄기 기록 없이 20시간 캡으로 닫힌 켜짐(수집기 Get-PcOnHistory) — 쓴 시간 모름
WAKE_END_MIN, WAKE_MAX_MIN = 360.0, 60.0           # 00~06시 안에 다 든 60분 미만 켜짐 — 흔적이 없으면 새벽 업데이트 깨움
AO_NOTE = "PC를 켜 둔 채(쓴 시간 모름) — 흔적이 있는 날만(평일은 낮 시간 · 주말·휴일은 흔적 앞뒤)"   # 켜 둔 날의 행 표시(day_why 가 그대로 보인다)
PCU_WHY = "PC 사용(켜기·로그온·절전 해제 ~ 끄기·로그오프·절전)"         # 출근·퇴근이 둘 다 PC 사용 구간 가장자리인 날의 근거
L29_FLOOR = "lm29+"                                # 모든 날 바닥값(withLM29)의 출처 이름(_day_row — 덩어리가 있는 날)
L29_MORE = "LM29 방식 시간이 더 많음"             # 그 바닥값이 근무를 늘린 날의 표시
EVENING_WIN = (19 * 60.0, 22 * 60.0)              # 저녁(19~22시) — evening_h(덩어리와 겹친 시간 · 보여 주기만, 투입에 이미 들어 있다)
SEND_GAP_DAYS, SEND_GAP_PC_DAYS, SEND_GAP_MONTH_PC_DAYS = 14, 3, 5   # 발신 흔적 빈 곳(머리말 17)
WEB_TAIL_MIN = 5.0          # 브라우저 방문으로 늘린 끝에 붙이는 분(방문 직후)
PC_COVER = 0.8              # 낮 공백을 PC 로 잇는 문턱 — 공백의 이 비율 이상 켜져 있어야
LIVE_SLACK_MIN = 120.0      # 수집 시각까지 켜져 있던 세션을 '지금' 까지 늘리는 한도(수집 직후 분석·판정 재산정)
PRES_JOIN_MIN = 10.0        # 이 분 이하로 끊긴 켜짐은 잇는다 — 아침 업데이트 재부팅·잠깐 잠금이 출근·퇴근 시각을 자르지 않게
BREAK_GAP_MIN, BREAK_GAP_MAX = 15.0, 60.0   # 덩어리 사이 공백이 이 분 이상이면 쉰 것 — 한 번에 60분까지
LATE_MIN = 20 * 60.0        # 늦은 퇴근(20:00 이후)
NIGHT_DAY_H = 0.5           # 야간(22~06) 0.5h 이상이면 야간 근무일
LONG_DAY_H = 16.0
PHYS_CAP_H = 24.0
USUAL_DAYS = 28
REC_EPS_H = 0.05            # 근태 기록과 이 시간(3분) 넘게 다를 때만 '근태에 없는 근무' · +@ 가 있는 날
RECORDS_DIR = "근태"        # data\근태\*.csv — 근태 기록 칸(사용자가 내려받아 넣는다)
# info 의 이 PC 전용 칸 — mm_meta 에 실리기 전에 뗀다. attendance_agg(LM30 2026-10-19) = 근태 기록과 견준 값까지 든 합계(이 PC 의
# attendance 파일로만 — info["attendance"] 는 근태 없이 잰 합계(compute 의 team))
LOCAL_KEYS = ("attendance_days", "attendance_usual", "attendance_agg")
CLOCK_KEYS = ("evening", "dawn")                       # LM29 날짜별 근거의 시각 창 — mm_meta 에는 길이(h)로만
# LM30(2026-10-19) weekend_h·evening_h — 시간외 나눠 보기(머리말 16 · offday_h = holiday_h 는 aggregate 가 붙인다)
_SUM_KEYS = ("work_h", "regular_h", "ext_h", "night_h", "holiday_h", "holiday_ext_h", "offpc_h", "lm29_h", "weekend_h",
             "evening_h")
_CNT_KEYS = ("days", "late_days", "night_days", "leave_work_days", "est_edge_days", "over52_weeks")
# LM30(2026-10-20) PC 사용 시간 합계 칸(머리말 19 — pcUsage 가 켜졌을 때만 · 셈 칸 always_on_days 는 따로) — LM 이 잰 값이라 팀에 올려도 된다
PCU_SUM_KEYS = ("pc_usage_h", "pc_usage_off_h")
_WEEK_KEYS = ("work_h", "regular_h", "ext_h", "night_h", "holiday_h", "offpc_h", "weekend_h", "evening_h")
# LM30(2026-10-19) +@ 합계 칸 — EST 는 LM 이 잰 값만(연장 + 휴일 — 팀에 올려도 된다), HR 은 근태 기록·GERP·태깅에서 나온 값(이 PC 전용 —
# strip_hr·scrub_meta 가 팀·공유폴더·얼린 사본으로 나가기 전에 뺀다)
EST_KEYS = ("plus_est_h", "plus_est_offpc_h")
HR_SUM_KEYS = ("unrecorded_h", "plus_h", "plus_offpc_h", "plus_all_h", "missing_h", "gate_plus_h")
HR_CNT_KEYS = ("plus_days", "rec_days", "gate_days")
HR_KEYS = HR_SUM_KEYS + HR_CNT_KEYS


# ════════════════════════════════ 설정 ════════════════════════════════
def _num(v, dflt, lo, hi, key, warns):
    """숫자 키 — 없음·빈 값은 기본값(경고 없음), bool·글자·범위 밖은 기본값 + 경고(extract.norm_cfg 와 같은 꼴)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return float(dflt)
    x = None
    if not isinstance(v, bool):
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = None
        if x is not None and not math.isfinite(x):
            x = None
    if x is not None and lo <= x <= hi:
        return x
    warns.append(f"{key}={v!r} 는 쓸 수 없는 값(허용 {lo:g}~{hi:g}) — 기본값 {dflt} 적용")
    return float(dflt)


def _bool(v, dflt, key, warns):
    if v is None:
        return dflt
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v == v:
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off", ""):
        return False
    warns.append(f"{key}={v!r} 는 true/false 가 아님 — 기본값 {str(dflt).lower()} 적용")
    return dflt


def norm(cfg):
    """config.attendance → (값 dict, 경고 list) — 한 곳에서 검증한다. 블록·키가 없으면 기본값(useForMM 켬): LM29 의 config.json 을
    그대로 가져와도 LM30 방식으로 잰다. 형식·범위가 틀린 값은 기본값 + 경고 한 줄."""
    warns = []
    p = {k: (v if isinstance(v, bool) else float(v)) for k, v in DEFAULTS.items()}
    a = cfg.get("attendance") if isinstance(cfg, dict) else None
    if a is None:
        return p, warns
    if not isinstance(a, dict):
        warns.append(f"attendance 는 객체({{…}})여야 함({type(a).__name__}) — 출퇴근 추정 설정 전부 기본값")
        return p, warns
    p["useForMM"] = _bool(a.get("useForMM"), True, "attendance.useForMM", warns)
    # LM30(2026-10-19) 머리말 15 · LM30(2026-10-20) 키가 없으면 끔(견줘 볼 때만 켠다)
    p["withLM29"] = _bool(a.get("withLM29"), False, "attendance.withLM29", warns)
    p["pcUsage"] = _bool(a.get("pcUsage"), True, "attendance.pcUsage", warns)        # LM30(2026-10-20) 머리말 19
    for k, (lo, hi) in RANGES.items():
        p[k] = _num(a.get(k), DEFAULTS[k], lo, hi, "attendance." + k, warns)
    if p["weekMaxHours"] < p["weekHours"]:
        warns.append(f"attendance.weekMaxHours={a.get('weekMaxHours')!r} 가 weekHours 보다 작음 — "
                     f"{max(p['weekHours'], float(DEFAULTS['weekMaxHours'])):g} 적용")
        p["weekMaxHours"] = max(p["weekHours"], float(DEFAULTS["weekMaxHours"]))
    return p, warns


# ── LM30(2026-10-19) GERP 근무 기록 읽기(시험 기능 — 기본 꺼짐) · config.attendance.gerp ──
# 회사 인사 시스템(GERP)의 근무시간 현황 화면을 사람이 로그인해 둔 전용 Edge 에서 읽어 data\근태\gerp.csv(근태 기록 칸)에 모으는 선택 기능의
# 설정이다(읽기 collect\Get-GerpWork.py · 해석·저장·문구 core\gerp.py). 블록이 없으면 꺼짐. 켜도 url 이 http(s) 주소가 아니면 아무것도
# 하지 않는다. norm() 과 따로 둔다 — norm() 의 값은 cfg_used.attendance(숫자만)로 mm_meta 에 실리고 그 경고는 config_warnings 로 팀
# 서버까지 간다. 그래서 GERP 경고는 GERP 단계만 찍고, 경고 글에 주소를 싣지 않는다(질의 문자열에 회사 코드·사번이 들 수 있다).
GERP_DEFAULTS = {"enabled": False, "url": "", "readGate": True, "maxGateDays": 40, "timeoutSec": 60}
GERP_RANGES = {"maxGateDays": (0, 400), "timeoutSec": (10, 600)}
_URL_BAD = re.compile(r"[\s\x00-\x1f\x7f]")


def _gerp_url(v):
    """GERP 근무 현황 주소 → (쓸 주소 | "", 형식이 틀렸나). http·https 이고 호스트가 있는 주소만 받는다 — 공백·제어 문자·사용자 정보
    (아이디@호스트)가 든 주소, 2000자 넘는 주소, 글자가 아닌 값은 받지 않는다. 비었으면 ("", False)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return "", False
    if not isinstance(v, str):
        return "", True
    s = v.strip()
    if len(s) > 2000 or _URL_BAD.search(s):
        return "", True
    try:
        u = urlparse(s)
        host = u.hostname or ""
        _ = u.port                                            # 숫자가 아닌 포트는 ValueError
    except ValueError:
        return "", True
    if u.scheme.lower() not in ("http", "https") or not host or u.username or u.password:
        return "", True
    return s, False


def norm_gerp(cfg):
    """config.attendance.gerp → (값 dict, 경고 list). 값 = GERP_DEFAULTS 의 키 + on(enabled 이고 url 을 쓸 수 있다).
    블록이 없으면 꺼짐(경고 없음). 블록이 객체가 아니면 꺼짐 + 경고. enabled·readGate 는 true/false(글자 'true' 도), maxGateDays(0~400 —
    0 이면 태깅을 읽지 않는다)·timeoutSec(10~600 — 화면이 뜨기를 기다리는 초)은 범위 밖·글자면 기본값 + 경고. 경고 글에 주소는 싣지 않는다."""
    warns = []
    g = dict(GERP_DEFAULTS)
    a = cfg.get("attendance") if isinstance(cfg, dict) else None
    blk = a.get("gerp") if isinstance(a, dict) else None
    if blk is None:
        g["on"] = False
        return g, warns
    if not isinstance(blk, dict):
        warns.append(f"attendance.gerp 는 객체({{…}})여야 함({type(blk).__name__}) — GERP 근무 기록 읽기를 끕니다")
        g["on"] = False
        return g, warns
    g["enabled"] = _bool(blk.get("enabled"), False, "attendance.gerp.enabled", warns)
    g["readGate"] = _bool(blk.get("readGate"), True, "attendance.gerp.readGate", warns)
    for k, (lo, hi) in GERP_RANGES.items():
        g[k] = int(_num(blk.get(k), GERP_DEFAULTS[k], lo, hi, "attendance.gerp." + k, warns))
    url, bad = _gerp_url(blk.get("url"))
    if bad:
        warns.append("attendance.gerp.url 이 http(s) 주소가 아닙니다 — GERP 근무 기록을 읽지 않습니다(주소 글은 적지 않습니다)")
    g["url"] = url
    g["on"] = bool(g["enabled"] and url)
    return g, warns


def _dur(m):
    m = int(round(float(m)))
    h, r = divmod(m, 60)
    if h and r:
        return f"{h}시간 {r}분"
    return f"{h}시간" if h else f"{r}분"


def _win_hh(win):
    """낮 창(mm.pcFloorWindow — ['08:00','19:00'] · [8, 19] · (480.0, 1140.0) 분) → ('08', '19'). 모르면 08~19."""
    if not (isinstance(win, (list, tuple)) and len(win) == 2):
        return "08", "19"
    out = []
    for i, dflt in ((0, "08"), (1, "19")):
        v = win[i]
        if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 24:
            v = int(float(v)) // 60                                  # 분으로 준 창(compute 의 day_win)
        out.append(_hh(v, dflt))
    return out[0], out[1]


def basis_text(p, win=None):
    """info["basis"] 한 문장(쉬운 말) — 보고서·대시보드의 '산출 근거'. win = 낮 창(mm.pcFloorWindow — 켜 둔 PC 를 세는 창).
    LM30(2026-10-20) pcUsage(머리말 19)면 PC 를 실제로 쓴 시간 + PC 밖 일 − 휴게로 말한다(끄면 예전 문장)."""
    if p.get("pcUsage"):
        w0, w1 = _win_hh(win)
        head = (f"투입 = 출퇴근 추정 — PC를 실제로 쓴 시간(켜기·로그온·절전 해제 ~ 끄기·로그오프·절전)에 PC 밖에서 한 일(휴대폰 메일·"
                f"팀즈·회의·수동 기록·출장)을 더하고, 휴게(4시간마다 {_dur(p['breakPer4hMin'])} — 덩어리 사이에 쉰 만큼 줄임)를 뺍니다. "
                f"흔적이 없어도 PC를 쓴 시간은 주말·휴일·밤 모두 셉니다. {float(p['pcUsageMaxSpanH']):g}시간 넘게 켜 둔 채인 PC는 쓴 "
                f"시간을 알 수 없어 흔적이 있는 날의 낮({w0}~{w1}시 — 주말·휴일은 흔적 앞뒤)만 세고, {_dur(p['pcUsageMinMin'])}이 안 되는 켜짐과 새벽 업데이트 "
                f"깨움은 흔적이 없으면 뺍니다")
    else:
        head = (f"투입 = 출퇴근 추정 — 내가 남긴 흔적(저장·발신·커밋·수락한 회의·수동 기록·출장)을 이어 근무 덩어리를 만들고, "
                f"시작·끝은 PC를 켜고 끈 시각(첫 흔적 {_dur(p['pcEdgeBeforeMin'])} 전부터·마지막 흔적 "
                f"{_dur(p['pcEdgeAfterMin'])} 뒤까지)으로, 그런 시각이 없으면 흔적 {_dur(p['leadMin'])} 앞·"
                f"{_dur(p['tailMin'])} 뒤로 잡습니다. PC가 켜져만 있던 시간은 세지 않고, 휴게는 4시간마다 "
                f"{_dur(p['breakPer4hMin'])}(덩어리 사이에 쉰 만큼 줄임)을 뺍니다")
    # LM30(2026-10-19) 머리말 15 — 켜져 있으면 한 문장 더(p = norm() 값 — 키가 늘 있다)
    return head + (". LM29 방식이 센 시간(저녁·주말·휴일 포함)보다 적게 세지 않습니다" if p.get("withLM29") else "")


# ════════════════════════════════ 시각 도구 ════════════════════════════════
def hm(m):
    """분 → 'HH:MM'(24시를 넘으면 다음 날 시각 — 날 수는 leave_day 등으로 따로 적는다)."""
    v = int(round(float(m))) % 1440
    return f"{v // 60:02d}:{v % 60:02d}"


def _hm2m(s):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(s or ""))
    if not m:
        return None
    v = int(m.group(1)) * 60 + int(m.group(2))
    return float(v) if 0 <= v <= 1440 else None


def _r(x):
    return round(float(x) + 0.0, 2)


def _union(spans):
    out = []
    for a, b in sorted((float(a), float(b)) for a, b in spans if b > a):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1][1] = b
        else:
            out.append([a, b])
    return out


class _Pres:
    """PC 켜짐 구간(절대 분, 겹침 없음) — (시작, 끝, live). live = 수집 시각까지 켜져 있던 현재 세션(끝이 '끔' 이 아니다) —
    수집 직후(LIVE_SLACK_MIN 안)면 지금까지 늘린다. PRES_JOIN_MIN 이하로 끊긴 구간은 하나로 잇는다(재부팅·잠깐 잠금)."""

    def __init__(self, spans, live_ends, now_abs):
        self.iv = []
        for a, b in _union(spans):
            live = any(abs(b - x) <= 1.0 for x in live_ends)
            if live and 0.0 <= now_abs - b <= LIVE_SLACK_MIN:
                b = now_abs
            if self.iv and a - self.iv[-1][1] <= PRES_JOIN_MIN:
                self.iv[-1] = (self.iv[-1][0], max(b, self.iv[-1][1]), live)
            else:
                self.iv.append((a, b, live))
        self.starts = [x[0] for x in self.iv]

    def at(self, t):
        """t 를 덮는 구간 또는 None"""
        i = bisect.bisect_right(self.starts, t) - 1
        if i >= 0 and self.iv[i][0] <= t <= self.iv[i][1]:
            return self.iv[i]
        return None

    def cover(self, g0, g1):
        """[g0, g1] 중 켜져 있던 분"""
        if g1 <= g0:
            return 0.0
        tot = 0.0
        for a, b, _l in self.iv[max(0, bisect.bisect_right(self.starts, g0) - 1):]:
            if a >= g1:
                break
            if b > g0:
                tot += min(b, g1) - max(a, g0)
        return tot

    def days(self, base):
        """켜짐이 걸친 달력 날짜(PC 기록이 있는 날)"""
        out = set()
        for a, b, _l in self.iv:
            for k in range(int(math.floor(a / 1440.0)), int(math.floor((b - 1e-6) / 1440.0)) + 1):
                out.add(base + timedelta(days=k))
        return out


def _inside_day(g0, g1, win):
    """공백 [g0, g1] 이 한 날의 낮 창(win, 그날 분) 안에 있는가"""
    k = math.floor(g0 / 1440.0) * 1440.0
    return k + win[0] <= g0 and g1 <= k + win[1]


def night_overlap(s, e, nw):
    """[s, e](절대 분)와 야간 창(nw = (시작 분, 끝 분) — 자정을 넘을 수 있다)이 겹친 분"""
    a0, a1 = float(nw[0]), float(nw[1])
    tot = 0.0
    for k in range(int(math.floor(s / 1440.0)) - 1, int(math.floor(e / 1440.0)) + 1):
        lo = k * 1440.0 + a0
        hi = (k + 1) * 1440.0 + a1 if a0 > a1 else k * 1440.0 + a1
        tot += max(0.0, min(e, hi) - max(s, lo))
    return tot


# ════════════════════════════════ PC 사용 시간(LM30 2026-10-20 — 머리말 19) ════════════════════════════════
def pc_usage(raw, points, spans, weak, live_ends, now_abs, p, day_win=(480.0, 1140.0), off_k=None):
    r"""PC 켜짐 원자료 → PC 를 실제로 쓴 구간(순수 함수 — 규칙은 머리말 19) → (구간 [(a, b, kind)], 켜 둔 날 집합 {k}).
      raw       [(a, b, src)] 절대 분 — 이벤트 구간만(브라우저 방문·창 샘플러 아님). 자정에서 자른 조각·겹친 원장 행이 섞여도 된다.
                src 가 event-cap(끄기 기록 없이 20시간 캡으로 닫힘)인 조각이 든 켜짐은 쓴 시간을 모른다
      points    확실한 흔적 점 · spans [(a, b, kind)] 확실한 흔적 구간(meeting·manual·offsite — LM29 구간 아님) · weak 약한 흔적(브라우저
                방문) 점 — compute 의 입력 그대로(해석 출력은 호출측이 이미 뺐다)
      live_ends 수집 시각까지 켜져 있던 세션의 끝 · now_abs 지금 · p = norm() 값 · day_win 낮 창(그날 분 — mm.pcFloorWindow)
    kind = pc(쓴 구간 그대로) | pcwin(켜 둔 채인 켜짐의 흔적 있는 날 낮 창). k = base 로부터 날 수(그 날 00:00 = k × 1440) — 켜 둔 켜짐이
    그날 낮 창과 겹친 날(흔적이 없어 0시간인 날도). 구간은 지금 뒤로 넘지 않고 시작 순이다.
      off_k     (선택) k → 그날이 주말·휴일인가. LM30(2026-10-20): 켜 둔 PC 의 주말·휴일은 낮 창(08~19시) 통째가 아니라 그날 첫 확실한
                흔적 − leadMin ~ 마지막 확실한 흔적 + tailMin(예전 주말 창과 같은 폭) — 주말에 한 번 저장했다고 11시간을 세지 않게.
                없으면 모든 날을 평일처럼 낮 창으로 센다(순수 시험용 기본)."""
    max_m = float(p.get("pcUsageMaxSpanH", DEFAULTS["pcUsageMaxSpanH"])) * 60.0
    lead = float(p.get("leadMin", DEFAULTS["leadMin"]))
    tail = float(p.get("tailMin", DEFAULTS["tailMin"]))
    min_m = float(p.get("pcUsageMinMin", DEFAULTS["pcUsageMinMin"]))
    ds = float(p.get("dayStartHour", DEFAULTS["dayStartHour"])) * 60.0
    now_abs = float(now_abs)
    rows = []
    for x in raw or ():
        try:
            a, b = float(x[0]), float(x[1])
        except (TypeError, ValueError, IndexError):
            continue
        src = str(x[2] if len(x) > 2 and x[2] is not None else "").strip().lower()
        if math.isfinite(a) and math.isfinite(b) and b > a:
            rows.append((a, b, src == CAP_SRC))
    rows.sort()
    joined = []                                               # [시작, 끝, cap] — 겹치거나 PRES_JOIN_MIN 이하로 끊긴 조각을 잇는다
    for a, b, cap in rows:
        if joined and a - joined[-1][1] <= PRES_JOIN_MIN:
            j = joined[-1]
            j[1], j[2] = max(j[1], b), (j[2] or cap)
        else:
            joined.append([a, b, cap])
    pts = sorted(float(t) for t in points)
    wk = sorted(float(t) for t in weak)
    sps = sorted((float(s[0]), float(s[1])) for s in spans if float(s[1]) >= float(s[0]))

    def _has(lst, a, b):
        i = bisect.bisect_left(lst, a)
        return i < len(lst) and lst[i] <= b

    def strong_in(a, b):
        return _has(pts, a, b) or any(s0 <= b and s1 >= a for s0, s1 in sps)

    def wd(t):
        return int(math.floor((t - ds) / 1440.0))            # 근무일(머리말 6 — 새벽 5시 전은 전날)
    ev_days = {wd(t) for t in pts}                            # 확실한 흔적이 있는 근무일 — 켜 둔 PC 의 낮 창을 세는 날
    for s0, s1 in sps:
        ev_days.update(range(wd(s0), wd(max(s0, s1)) + 1))
    out, ao = [], set()
    w0, w1 = float(day_win[0]), float(day_win[1])
    for a, b, cap in joined:
        if any(abs(b - x) <= 1.0 for x in live_ends) and 0.0 <= now_abs - b <= LIVE_SLACK_MIN:
            b = now_abs                                       # 수집 직후 — 지금도 켜져 있다(_Pres 와 같다)
        b = min(b, now_abs)                                   # 아직 오지 않은 시각까지 늘리지 않는다
        if b <= a:
            continue
        if cap or b - a > max_m:
            # 켜 둔 채(쓴 시간 모름) — 흔적 있는 날의 낮 창만(예전 PC 하한의 '흔적 있는 날만' 규칙). 낮 창과 겹친 날은 모두 켜 둔 날
            for k in range(int(math.floor(a / 1440.0)), int(math.floor((b - 1e-6) / 1440.0)) + 1):
                x0, x1 = max(a, k * 1440.0 + w0), min(b, k * 1440.0 + w1)
                if x1 <= x0:
                    continue
                ao.add(k)
                if off_k is not None and off_k(k):
                    # 주말·휴일 — 그날(달력 날) 확실한 흔적의 처음 − leadMin ~ 끝 + tailMin ∩ 켜짐. 흔적이 없으면 0
                    d0, d1 = k * 1440.0, (k + 1) * 1440.0
                    ts = pts[bisect.bisect_left(pts, d0):bisect.bisect_left(pts, d1)]
                    ts = ts + [t for s0, s1 in sps if s0 < d1 and s1 >= d0 for t in (max(s0, d0), min(s1, d1))]
                    if ts:
                        y0, y1 = max(a, d0, min(ts) - lead), min(b, d1, max(ts) + tail)
                        if y1 > y0:
                            out.append((y0, y1, PCW_KIND))
                    continue
                if k in ev_days:
                    out.append((x0, x1, PCW_KIND))
            continue
        if b - a < min_m and not strong_in(a, b) and not _has(wk, a, b):
            continue                                          # 업데이트 깨움·잠깐 켬(흔적 없음)
        d0m = math.floor(a / 1440.0) * 1440.0
        if b <= d0m + WAKE_END_MIN and b - a < WAKE_MAX_MIN and not strong_in(a, b):
            continue                                          # 새벽 업데이트 깨움(00~06시 · 브라우저 방문은 흔적으로 치지 않는다)
        out.append((a, b, PCU_KIND))
    return sorted(out), ao


# ════════════════════════════════ 덩어리 ════════════════════════════════
def clusters(points, spans, pres, p, day_win):
    """확실한 흔적(점 points · 구간 spans[(a, b, kind)]) → 덩어리 [{s, e, sk, ek, rs, re, rsk, rek, ls, le}] — s·e 는 첫·마지막 흔적,
    sk·ek 는 그 흔적의 종류('pt' 또는 meeting·manual·offsite·lm29). 공백 ≤ bridgeAwayMin 이면 잇고, 낮 창 안의 공백은 PC 가
    PC_COVER 이상 켜져 있었으면 bridgePcMin 까지 잇는다.
    LM30(2026-10-19) LM29 구간(kind lm29 — 머리말 15)도 같은 규칙으로 잇되, 확실한 흔적의 첫·끝(rs·re — 그 종류 rsk·rek)과 LM29 구간의
    첫·끝(ls·le)을 따로 적는다 — edges 가 둘 중 넓은 쪽을 쓴다(LM29 구간 끝이 저장 시각과 같아도 PC 를 끈 시각까지 늘릴 수 있게).
    LM29 구간이 없으면 rs·re·rsk·rek = s·e·sk·ek(예전 그대로).
    LM30(2026-10-20) PC 사용 구간(kind pc·pcwin — 머리말 19)도 같은 규칙으로 잇되 그 첫·끝(us·ue)과 그 종류(usk·uek)를 따로 적는다 —
    edges 가 확실한 흔적 쪽과 넓은 쪽을 쓴다."""
    items = [(float(t), float(t), "pt") for t in points]
    items += [(float(a), float(b), k) for a, b, k in spans if b >= a]
    items.sort(key=lambda x: (x[0], x[2] == "pt", -x[1]))     # 같은 시각이면 구간(기록된 가장자리)이 먼저
    out = []
    for s, e, k in items:
        l29, pcu = k == L29_KIND, k in PCU_KINDS
        soft = k in SOFT_KINDS
        if out:
            c = out[-1]
            gap = s - c["e"]
            if gap <= p["bridgeAwayMin"] or (gap <= p["bridgePcMin"] and _inside_day(c["e"], s, day_win)
                                              and pres.cover(c["e"], s) >= PC_COVER * gap):
                if e > c["e"] or (e == c["e"] and k != "pt"):
                    c["e"], c["ek"] = e, k
                if l29:
                    c["ls"] = s if c["ls"] is None else min(c["ls"], s)
                    c["le"] = e if c["le"] is None else max(c["le"], e)
                elif pcu:
                    if c["us"] is None or s < c["us"]:
                        c["us"], c["usk"] = s, k
                    if c["ue"] is None or e > c["ue"]:
                        c["ue"], c["uek"] = e, k
                elif c["rs"] is None:
                    c.update(rs=s, re=e, rsk=k, rek=k)
                elif e > c["re"] or (e == c["re"] and k != "pt"):
                    c["re"], c["rek"] = e, k
                continue
        out.append({"s": s, "e": e, "sk": k, "ek": k,
                    "rs": None if soft else s, "re": None if soft else e, "rsk": None if soft else k,
                    "rek": None if soft else k, "ls": s if l29 else None, "le": e if l29 else None,
                    "us": s if pcu else None, "ue": e if pcu else None, "usk": k if pcu else None, "uek": k if pcu else None})
    return out


def edges(c, pres, weak, p, now_abs):
    """덩어리 하나의 시작·끝 → {s, e, ss, es, kind}. ss·es = pc·meeting·manual·offsite·web·lead·tail·now·lm29·pcuse·pcwin(LM30
    2026-10-20 — PC 사용 구간 · 켜 둔 날의 낮 창), kind = pc | offpc.
    weak = 정렬된 약한 흔적(브라우저 방문) 시각.
    LM30(2026-10-19) LM29 구간이 든 덩어리(머리말 15) — 확실한 흔적의 첫·끝(rs·re)으로 아래 규칙대로 잡은 시작·끝과 LM29 구간의
    첫·끝(ls·le — 앞뒤를 붙이지 않는다) 중 넓은 쪽(같으면 확실한 흔적 쪽 이름). LM29 구간만 있는 덩어리는 그 구간 그대로."""
    fs, ls = c["s"], c["e"]
    offpc = pres.at(fs) is None and pres.at(ls) is None and pres.cover(fs, ls) <= 0.0
    if "rs" in c:
        rs, re_, rsk, rek = c["rs"], c["re"], c["rsk"], c["rek"]
    else:
        rs, re_, rsk, rek = fs, ls, c["sk"], c["ek"]
    s = e = None
    ss = es = ""
    if rs is not None:
        pf, pl = pres.at(rs), pres.at(re_)
        j = float(p["webJoinMin"])
        if pf is not None and pf[0] >= rs - p["pcEdgeBeforeMin"]:
            s, ss = pf[0], "pc"                               # 첫 흔적 전 2시간 안에 켰고 그 뒤 계속 켜짐
        elif rsk in SPAN_KINDS:
            s, ss = rs, rsk
        else:
            i = bisect.bisect_left(weak, rs - j)
            if i < len(weak) and weak[i] < rs:
                s, ss = weak[i], "web"                        # 가장 이른 방문(60분 안) — 방문끼리는 잇지 않는다
            else:
                s, ss = rs - (p["offpcPadMin"] if offpc else p["leadMin"]), "lead"
        if pl is not None and not pl[2] and pl[1] <= re_ + p["pcEdgeAfterMin"]:
            e, es = pl[1], "pc"                               # 마지막 흔적 뒤 90분 안에 끔·로그오프·잠금·절전
        elif rek in SPAN_KINDS:
            e, es = re_, rek
        else:
            i = bisect.bisect_right(weak, re_ + j) - 1
            if i >= 0 and weak[i] > re_:
                e, es = weak[i] + WEB_TAIL_MIN, "web"
            elif pl is not None and pl[2] and now_abs - re_ <= p["tailMin"]:
                e, es = now_abs, "now"                        # 지금 켜져 있고 방금까지 흔적 — 일하는 중
            else:
                e, es = re_ + (p["offpcPadMin"] if offpc else p["tailMin"]), "tail"
        e = max(re_, min(e, max(now_abs, re_)))               # 아직 오지 않은 시각까지 늘리지 않는다
    if c.get("ls") is not None:                               # LM29 구간 — 그 시작·끝 그대로(LM29 가 이미 근무로 셌다)
        if s is None or c["ls"] < s - 1e-9:
            s, ss = c["ls"], L29_KIND
        if e is None or c["le"] > e + 1e-9:
            e, es = c["le"], L29_KIND
    if c.get("us") is not None:
        # LM30(2026-10-20) PC 사용 구간(머리말 19) — 그 시작·끝 그대로(앞뒤를 붙이지 않는다). 쓴 구간은 pcuse(기록된 시각), 켜 둔 날의
        # 낮 창은 pcwin(어림). 지금까지 쓰는 중(수집 직후 세션을 지금까지 늘렸다)이면 끝은 now(일하는 중)
        if s is None or c["us"] < s - 1e-9:
            s, ss = c["us"], (PCU_EDGE if c["usk"] == PCU_KIND else PCW_KIND)
        if e is None or c["ue"] > e + 1e-9:
            e, es = c["ue"], (PCU_EDGE if c["uek"] == PCU_KIND else PCW_KIND)
            if es == PCU_EDGE and e >= now_abs - 1e-6:
                es = "now"
    return {"s": min(s, fs), "e": e, "ss": ss, "es": es, "kind": "offpc" if offpc else "pc"}


def merge(blocks):
    """가장자리를 늘린 뒤 겹치는 덩어리를 합친다(한쪽이라도 PC 덩어리면 pc)."""
    out = []
    for b in sorted(blocks, key=lambda x: (x["s"], x["e"])):
        if out and b["s"] <= out[-1]["e"]:
            m = out[-1]
            if b["e"] > m["e"]:
                m["e"], m["es"] = b["e"], b["es"]
            if b["kind"] == "pc":
                m["kind"] = "pc"
        else:
            out.append(dict(b))
    return out


# ════════════════════════════════ 하루 ════════════════════════════════
def _raw_brk(bl, p):
    """그날 덩어리(시작 순) → (체류 분, 남은 휴게 분) — 휴게는 4시간마다 breakPer4hMin, 덩어리 사이 15분 이상 빈 시간(한 번에 60분까지)은
    이미 쉰 것(머리말 7)."""
    raw = sum(b["e"] - b["s"] for b in bl)
    need = p["breakPer4hMin"] * math.floor(raw / 240.0 + 1e-9)
    taken = sum(min(g, BREAK_GAP_MAX) for g in (bl[i]["s"] - bl[i - 1]["e"] for i in range(1, len(bl)))
                if g >= BREAK_GAP_MIN)
    return raw, max(0.0, need - taken)


def _day_row(d, base, bl, prev_bl, p, std, off, lf, offsite_day, man_h, nopc_day, un_min, l29, l29n, rec, day_cap,
             night_win, with_l29=False, strict_bl=None, pcu_on=False, always_on=False):
    """하루(근무일 d)의 행 — 덩어리·바닥값·나눔·신뢰도. 덩어리도 시간도 LM29 시간도 없으면 None.
    LM30(2026-10-19) with_l29(attendance.withLM29 — 머리말 15) — 덩어리가 있는 날에도 LM29 방식 시간(이웃 날이 덮은 만큼 뺀 것)을
    바닥으로 쓴다 · strict_bl = LM29 구간(LM30 2026-10-20 — PC 사용 구간도) 없이 만든(엄격한) 덩어리 중 이 날 덩어리 안에 든 것 —
    그 근무·PC 밖보다 적게 세지 않는다 ·
    행에 evening_h(19~22시)·weekend_h(토·일 근무)를 더한다(머리말 16).
    LM30(2026-10-20) pcu_on(attendance.pcUsage — 머리말 19)이면 행에 pc_usage_h(그날 덩어리 안의 PC 사용 시간 — 덩어리의 pcu 분 합 ·
    휴게 빼기 전)·always_on(켜 둔 날)을 더하고, 켜 둔 날이면 AO_NOTE 를 맨 앞에 단다. 끄면 예전과 같은 글자다."""
    d0m = (d - base).days * 1440.0
    bl = sorted(bl, key=lambda b: b["s"])
    # 전날 근무 덩어리가 이 달력 날(00:00~)을 덮은 분 — LM29 방식은 달력 날짜로 셌으니 그만큼 빼고 쓴다(두 번 세지 않게)
    other = sum(max(0.0, min(b["e"], d0m + 1440.0) - max(b["s"], d0m)) for b in prev_bl)
    l29_adj = max(0.0, l29 - other / 60.0)
    notes, floors = ([AO_NOTE] if (pcu_on and always_on) else []), []
    if bl:
        raw, brk = _raw_brk(bl, p)
        work = (raw - brk) / 60.0
        night = sum(night_overlap(b["s"], b["e"], night_win) for b in bl) / 60.0
        evening = sum(night_overlap(b["s"], b["e"], EVENING_WIN) for b in bl) / 60.0
        offpc = sum(b["e"] - b["s"] for b in bl if b["kind"] == "offpc") / 60.0
        if strict_bl:
            # LM30(2026-10-19) LM29 구간으로 이어 붙인 공백은 예전에 '이미 쉰 시간'(덩어리 사이 공백)이었다 — 이어 붙이면 체류가 늘어
            # 4시간마다 휴게를 더 빼 오히려 줄 수 있다. 엄격한 덩어리로 잰 근무보다 적으면 그 차이를 휴게로 본다(LM30 이 더 찾은 것을 지킨다).
            # LM30(2026-10-20) PC 사용 구간(머리말 19)으로 이어 붙인 공백도 같다(엄격한 덩어리 = 확실한 흔적만).
            # PC 밖 시간도 엄격한 덩어리 쪽이 크면 그 값(PC 덩어리에 이어 붙어도 휴대폰 발신·수동 기록 구간은 PC 밖이다)
            sb = sorted(strict_bl, key=lambda b: b["s"])
            s_raw, s_brk = _raw_brk(sb, p)
            if (s_raw - s_brk) / 60.0 > work + 1e-9:
                work = (s_raw - s_brk) / 60.0
                brk = max(0.0, raw - work * 60.0)
            offpc = max(offpc, sum(b["e"] - b["s"] for b in sb if b["kind"] == "offpc") / 60.0)
        last = max(bl, key=lambda b: b["e"])
        a_m, l_m = int(round(bl[0]["s"] - d0m)), int(round(last["e"] - d0m))
        a_src, l_src = bl[0]["ss"], last["es"]
    else:
        raw = brk = work = night = evening = offpc = 0.0
        a_m = l_m = None
        a_src = l_src = ""

    def _floor(val, src, note):
        nonlocal work
        if val > work + 1e-9:
            work = val
            floors.append(src)
            notes.append(note)
    if offsite_day and not off and lf < 1.0:
        _floor(std * (1.0 - lf), "offsite", "종일 출장·교육 — 표준일")
    if man_h > 0:
        _floor(man_h, "manual", "수동 기록 시간")
    if nopc_day or not rec:
        _floor(l29_adj, "lm29", "PC 기록 없음 — LM29 방식 시간")
    if not bl and un_min > 0:
        _floor(un_min / 60.0, "untimed", "날짜만 아는 발신")
    if not bl:
        _floor(l29_adj, "lm29", "근거가 얇아 LM29 방식 시간")
        if work <= 0 and l29 <= 0:
            return None
        a_src = l_src = floors[-1] if floors else ""
    elif with_l29:
        # LM30(2026-10-19) 모든 날 바닥값(머리말 15) — 시각 없이 센 LM29 시간(표준일·날짜만 아는 발신·출장)과 휴게 차이를 잃지 않게.
        # 출근·퇴근 시각은 덩어리 그대로라 신뢰도는 '보통'까지만 낮춘다(다른 바닥값처럼 '낮음' 으로 만들지 않는다)
        _floor(l29_adj, L29_FLOOR, L29_MORE)
    if day_cap and work > day_cap:
        work = float(day_cap)
        notes.append(f"하루 상한 {day_cap:g}시간")
    if work > PHYS_CAP_H:
        work = PHYS_CAP_H
        notes.append("24시간 물리 한계")
    if work > LONG_DAY_H:
        notes.append("16시간 넘음")
    if off:
        reg = ext = 0.0
        hol, hol_ext = work, max(0.0, work - std)
    else:
        reg = min(work, std * max(0.0, 1.0 - lf))
        ext = max(0.0, work - reg)
        hol = hol_ext = 0.0
        if lf >= 1.0 and work > 0:
            notes.append("휴가일 근무")
    if bl:
        night = min(night, work)
        if with_l29 and ("lm29" in floors or L29_FLOOR in floors):
            # LM29 시간으로 늘린 날의 야간 = 덩어리 야간과 LM29 야간 꼬리표 중 큰 쪽(전날 덩어리가 이 날 새벽에 이미 센 야간은 뺀다)
            o_n = sum(night_overlap(max(b["s"], d0m), min(b["e"], d0m + 1440.0), night_win)
                      for b in prev_bl if min(b["e"], d0m + 1440.0) > max(b["s"], d0m)) / 60.0
            night = min(max(night, l29n - o_n), work)
    else:
        night = min(l29n, work) if "lm29" in floors else 0.0
    evening = min(evening, work)
    weekend = work if d.isoweekday() > 5 else 0.0              # 토·일 근무(머리말 16) — 공휴일까지는 holiday_h·offday_h
    offpc = min(offpc, work) if rec else 0.0
    if not rec and not any(n.startswith("PC 기록 없음") for n in notes):
        notes.append("PC 기록 없음")
    if l_src == "now":
        notes.append("일하는 중")
    if [f for f in floors if f != L29_FLOOR] or not rec or not bl:
        conf = "low"
    elif a_src in HARD_SRC and l_src in HARD_SRC and L29_FLOOR not in floors:
        conf = "high"
    else:
        conf = "mid"                                          # LM29 구간 가장자리(lm29)·모든 날 바닥값이 늘린 날도 보통
    row = {"arrive": hm(a_m) if a_m is not None else "", "leave": hm(l_m) if l_m is not None else "",
           "arrive_day": int(a_m // 1440) if a_m is not None else 0,
           "leave_day": int(l_m // 1440) if l_m is not None else 0,
           "arrive_src": a_src, "leave_src": l_src,
           "blocks": [[int(round(b["s"] - d0m)), int(round(b["e"] - d0m)), b["kind"]] for b in bl],
           "raw_h": _r(raw / 60.0), "break_h": _r(brk / 60.0), "work_h": _r(work), "regular_h": _r(reg),
           "ext_h": _r(ext), "night_h": _r(night), "holiday_h": _r(hol), "holiday_ext_h": _r(hol_ext),
           "offpc_h": _r(offpc), "lm29_h": _r(l29), "kind": "off" if off else "workday", "leave_frac": lf,
           "conf": conf, "notes": notes, "late": bool(l_m is not None and l_m >= LATE_MIN),
           "evening_h": _r(evening), "weekend_h": _r(weekend)}
    if pcu_on:                                                # LM30(2026-10-20) 머리말 19 — 끄면 예전과 같은 칸
        row["pc_usage_h"] = _r(sum(float(b.get("pcu") or 0.0) for b in bl) / 60.0)
        row["always_on"] = bool(always_on)
    return row


def compute(base, points, spans, weak, presence, live_ends, d0, d1, now, p, std=8.0, day_win=(480.0, 1140.0),
            night_win=(1320.0, 360.0), is_off=None, leave=None, offsite=(), manual_floor=None, nopc=(),
            untimed_min=None, lm29=None, lm29_night=None, rec_days=None, day_cap=None, records=None, lm29_spans=None,
            pc_spans=None):
    """흔적 → 날짜별 출퇴근·근무 + 합계. 시각 입력은 모두 절대 분(base 00:00 부터).
      points   확실한 흔적 점 · spans [(a, b, meeting|manual|offsite)] · weak 브라우저 방문 점
      presence PC 켜짐 [(a, b)] · live_ends 수집 시각까지 켜져 있던 세션의 끝(끔이 아니다)
      d0·d1    결과를 낼 근무일 범위 · now 지금(datetime) · p = norm() 값
      std      표준일(h) · day_win 낮 창(그날 분 — mm.pcFloorWindow) · night_win 야간 창(mm.nightWindow)
      is_off(날짜) 휴일 여부 · leave {날짜: 0.5|1} · offsite 종일 출장·교육 날짜 · manual_floor {날짜: 시간만 적은 수동 기록 h}
      nopc     PC 기록 없는 달의 표준일 추정 날짜(LM29) · untimed_min {날짜: 날짜만 아는 발신 인정 분}
      lm29     {날짜: LM29 방식 시간} · lm29_night {날짜: LM29 야간 꼬리표 h} · rec_days PC 기록이 있는 날(없으면 presence 로)
      day_cap  선택 상한(h) · records load_records() 결과(없으면 비교 안 함)
    returns {"days": {iso: 행}, "agg": 합계(시각 없음 — 근태 기록과 견준 값까지: 이 PC 전용), "team": 근태 기록 없이 잰 합계(팀·
    mm_meta 로 가는 것 — records 가 None 이면 agg 와 같은 dict), "usual": 평소 출근·퇴근(이 PC 전용)}.
    LM30(2026-10-19) +@ — 근태 기록이 있으면 hr_compare 가 날마다 견주어 행에 rec 을 붙인다(투입 시간 work_h 는 그대로).
    LM30(2026-10-19) lm29_spans [(a, b)] — LM29 가 시각까지 정해 근무로 센 구간(머리말 15). p["withLM29"](LM30 2026-10-20 — 기본 끔)일
    때만 흔적(종류 lm29)에 더하고 모든 날에 LM29 시간 바닥값을 쓴다. 꺼져 있으면 그 구간을 쓰지 않는다.
    LM30(2026-10-20) pc_spans [(a, b, src)] — PC 켜짐 원자료(이벤트 구간 · src 가 event-cap 이면 쓴 시간 모름 — 머리말 19). p["pcUsage"]
    (기본 켬)면 pc_usage 로 PC 를 실제로 쓴 구간을 만들어 덩어리 재료(종류 pc·pcwin)로 더한다 — 없으면 presence 를 그 원자료로 쓴다(src
    event). 행·합계에 pc_usage_h·always_on(_days)·pc_usage_off_h 가 붙는다. 꺼져 있으면 예전 숫자·칸 그대로."""
    is_off = is_off or (lambda dd: dd.isoweekday() > 5)
    leave, manual_floor, untimed_min = leave or {}, manual_floor or {}, untimed_min or {}
    lm29, lm29_night = lm29 or {}, lm29_night or {}
    offsite, nopc = set(offsite or ()), set(nopc or ())
    now_abs = (now.date() - base).days * 1440.0 + now.hour * 60 + now.minute + now.second / 60.0
    pres = _Pres(presence, live_ends, now_abs)
    rec_days = pres.days(base) if rec_days is None else set(rec_days)
    weak = sorted(float(x) for x in weak)
    with_l29 = bool(p.get("withLM29", False))
    pcu_on = bool(p.get("pcUsage", True))
    sp = list(spans)
    # LM30(2026-10-20) PC 사용 구간(머리말 19) — 덩어리 재료(종류 pc·pcwin · 가장자리 그대로 · 흔적 없이도 덩어리)
    usage, ao_dates = [], set()
    if pcu_on:
        raw = pc_spans if pc_spans is not None else [(a, b, "event") for a, b in presence]
        usage, ao_k = pc_usage(raw, points, spans, weak, live_ends, now_abs, p, day_win,
                               off_k=lambda k: bool(is_off(base + timedelta(days=k))))
        sp += usage
        ao_dates = {base + timedelta(days=k) for k in ao_k}
    if with_l29 and lm29_spans:
        sp += [(float(a), float(b), L29_KIND) for a, b in lm29_spans if float(b) > float(a)]
    blocks = merge([edges(c, pres, weak, p, now_abs) for c in clusters(points, sp, pres, p, day_win)])
    if pcu_on:
        # 덩어리마다 그 안의 PC 사용 분(pcu — 행의 pc_usage_h). PC 사용 구간은 저마다 한 덩어리 안에 든다(가장자리를 그대로 쓴다)
        uu = _union([(a, b) for a, b, _k in usage])
        for b in blocks:
            b["pcu"] = sum(max(0.0, min(u1, b["e"]) - max(u0, b["s"])) for u0, u1 in uu)
    ds = float(p["dayStartHour"]) * 60.0
    by_day, own = {}, []
    for b in blocks:
        k = int(math.floor(b["s"] / 1440.0))
        if b["s"] - k * 1440.0 < ds:
            k -= 1                                            # 새벽 5시 전에 시작 — 전날 근무
        by_day.setdefault(base + timedelta(days=k), []).append(b)
        own.append((b["s"], b["e"], base + timedelta(days=k)))
    # LM30(2026-10-19) LM29 구간을 더했으면 엄격한 덩어리도 만들어, 저마다 그것을 품은 덩어리의 근무일에 맡긴다(_day_row 의 strict_bl —
    # 엄격한 근무보다 적게 세지 않게). 덩어리는 늘 엄격한 덩어리를 품는다(흔적이 같고 가장자리는 넓은 쪽) — 못 찾은 것은 쓰지 않는다
    # LM30(2026-10-20) PC 사용 구간(머리말 19)을 더했을 때도 같다 — 엄격한 덩어리 = 확실한 흔적만(spans)으로 만든 덩어리. PC 를 18:00 에
    # 끄고 19:00~21:00 수동 기록이면 PC 사용 구간이 둘을 이어(공백 60분 ≤ 90분) 이미 쉰 공백이 근무가 되고 휴게가 늘어 오히려 줄던 것
    # (11.0h → 10.5h · PC 밖 2.0h → 0)을 막는다
    strict_by = None
    if len(sp) != len(spans):
        strict_by = {}
        starts = [o[0] for o in own]
        for b in merge([edges(c, pres, weak, p, now_abs) for c in clusters(points, spans, pres, p, day_win)]):
            i = bisect.bisect_right(starts, b["s"] + 1e-6) - 1
            if i >= 0 and b["e"] <= own[i][1] + 1e-6:
                strict_by.setdefault(own[i][2], []).append(b)
    days = {}
    d = d0
    while d <= d1:
        row = _day_row(d, base, by_day.get(d, []), by_day.get(d - timedelta(days=1), []), p, float(std),
                       bool(is_off(d)), float(leave.get(d, 0.0) or 0.0), d in offsite, float(manual_floor.get(d, 0.0)),
                       d in nopc, float(untimed_min.get(d, 0.0) or 0.0), float(lm29.get(d, 0.0) or 0.0),
                       float(lm29_night.get(d, 0.0) or 0.0), d in rec_days, day_cap, night_win, with_l29,
                       strict_by.get(d) if strict_by is not None else None, pcu_on, d in ao_dates)
        if row is not None:
            days[d.isoformat()] = row
        d += timedelta(days=1)
    ao = ao_dates if pcu_on else None                         # 켜 둔 날(합계의 always_on_days — 근무가 없어 행이 없는 날도)
    if records is None:
        agg = aggregate(days, d0, d1, p, ao=ao)
        return {"days": days, "agg": agg, "team": agg, "usual": usual_times(days, d1, now)}
    hr = hr_compare(days, records, d0, d1, p)
    rec_sum = compare_records(days, records, d0, d1, p, hr)
    # 팀 쪽 합계는 근태 기록 없이 다시 잰다 — 근태에서 나온 칸이 없고, +@ 추정도 모든 날의 연장 + 휴일(근태가 있는 날을 빼지 않는다)
    return {"days": days, "agg": aggregate(days, d0, d1, p, rec_sum, hr, ao=ao), "team": aggregate(days, d0, d1, p, ao=ao),
            "usual": usual_times(days, d1, now)}


# ════════════════════════════════ 합계 ════════════════════════════════
def _zero():
    z = dict.fromkeys(_SUM_KEYS, 0.0)
    z.update(dict.fromkeys(_CNT_KEYS, 0))
    return z


def _est(r):
    """날짜별 행 → (+@ 추정 h, 그중 PC 밖 h) — 근태 기록이 없는 날의 +@ = 연장 + 휴일(평일 8시간 넘은 시간 · 휴일 근무 전부 · 종일 휴가일
    근무 전부). LM 이 잰 값만 쓴다(팀에 올려도 된다). PC 밖은 많아야 그만큼."""
    def f(k):
        try:
            x = float(r.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0
        return x if math.isfinite(x) else 0.0
    e = max(0.0, f("ext_h") + f("holiday_h"))
    return e, min(max(0.0, f("offpc_h")), e)


def _week_key(d):
    y, w, _wd = d.isocalendar()
    return f"{y}-W{w:02d}"


def aggregate(days, d0, d1, p, records=None, hr=None, ao=None):
    """날짜별 행 → {"schema", "method", "weeks", "months", "total"[, "records"]} — 시각이 없는 합계뿐.
      weeks  {"YYYY-Www": {from, to, work_h…offpc_h, days, over40_h, over52, partial, plus_est_h, plus_est_offpc_h}} (ISO 주 월~일)
      months {"YYYY-MM": {work_h, regular_h, ext_h, night_h, holiday_h, holiday_ext_h, offpc_h, lm29_h, days, late_days,
              night_days, leave_work_days, est_edge_days, over52_weeks, plus_est_h, plus_est_offpc_h}} — 52시간 넘은 주는 그 주
              목요일의 달
      total  months 와 같은 키 + weeks(주 수)·over40_h(주마다 40시간 넘은 시간의 합)
    records = compare_records 요약·hr = hr_compare 값(LM30 2026-10-19 +@). 근태 기록이 있으면(records.present — 이 PC 전용 합계)
    weeks·months·total 에 HR_KEYS(unrecorded_h(달·전체) · plus_h · plus_offpc_h · plus_all_h · missing_h · gate_plus_h · plus_days ·
    rec_days · gate_days)를 더하고 plus_est_h 는 기록 칸 기간 밖의 날만 센다. 없으면(팀으로 가는 합계) plus_est_h 는 모든 날.
    근태에만 있는 날(이 PC 행이 없다)의 값은 그 주·달에 LM 행이 있을 때만 그 칸에, 전체에는 늘 들어간다.
    LM30(2026-10-20) ao = 켜 둔 날 집합(pcUsage 가 켜졌을 때만 compute 가 준다 — 머리말 19) — 주어지면 weeks·months·total 에
    pc_usage_h(PC 사용 시간 — 휴게 빼기 전)·pc_usage_off_h(그중 주말·휴일)·always_on_days(켜 둔 날 — [d0, d1] 안 · 근무가 없어 행이
    없는 날은 그 주·달에 행이 있을 때만 그 칸에, 전체에는 늘)를 더한다. None 이면 예전과 같은 칸."""
    has_rec = bool(records and records.get("present"))
    hr = hr if (has_rec and isinstance(hr, dict)) else {}
    rng = records.get("range") if has_rec and isinstance(records.get("range"), (list, tuple)) else []
    rng = [str(x)[:10] for x in rng] if len(rng) == 2 else []
    eps = REC_EPS_H
    pcu = ao is not None                                      # LM30(2026-10-20) PC 사용 시간 칸(머리말 19)

    def zero():
        z = _zero()
        z.update(dict.fromkeys(EST_KEYS, 0.0))
        if has_rec:
            z.update(dict.fromkeys(HR_SUM_KEYS, 0.0))
            z.update(dict.fromkeys(HR_CNT_KEYS, 0))
        if pcu:
            z.update(dict.fromkeys(PCU_SUM_KEYS, 0.0), always_on_days=0)
        return z
    weeks, months, total = {}, {}, zero()
    for iso in sorted(days):
        r = days[iso]
        d = date.fromisoformat(iso)
        m = months.get(iso[:7])
        if m is None:
            m = months[iso[:7]] = zero()
        worked = r["work_h"] > 0
        un = 0.0
        rc = r.get("rec")
        if has_rec and isinstance(rc, dict) and rc.get("diff_h", 0) > REC_EPS_H:
            un = rc["diff_h"]
        covered = bool(rng) and rng[0] <= iso <= rng[1]           # 근태 기록 칸 기간 안 — +@ 는 hr 에서
        est, est_off = (0.0, 0.0) if covered else _est(r)
        mon = d - timedelta(days=d.isoweekday() - 1)
        wk = weeks.get(_week_key(d))
        if wk is None:
            wk = weeks[_week_key(d)] = {"from": mon.isoformat(), "to": (mon + timedelta(days=6)).isoformat(),
                                        "days": 0, **dict.fromkeys(_WEEK_KEYS + EST_KEYS, 0.0)}
            if has_rec:                                       # 주에는 unrecorded_h 가 없다(예전과 같이 달·전체만)
                wk.update(dict.fromkeys((k for k in HR_SUM_KEYS if k != "unrecorded_h"), 0.0))
                wk.update(dict.fromkeys(HR_CNT_KEYS, 0))
            if pcu:
                wk.update(dict.fromkeys(PCU_SUM_KEYS, 0.0), always_on_days=0)
        if pcu:
            pu = _num0(r.get("pc_usage_h"))
            for t in (m, total, wk):
                t["pc_usage_h"] += pu
                t["pc_usage_off_h"] += pu if r.get("kind") == "off" else 0.0     # 주말·휴일에 PC 를 쓴 시간
        for t in (m, total):
            for k in _SUM_KEYS:
                t[k] += float(r.get(k) or 0.0)                # weekend_h·evening_h 가 없는 옛 행(LM30 2026-10-19 전)은 0
            t["days"] += 1 if worked else 0
            t["late_days"] += 1 if (worked and r["late"]) else 0
            t["night_days"] += 1 if r["night_h"] >= NIGHT_DAY_H else 0
            t["leave_work_days"] += 1 if (worked and r["leave_frac"] >= 1.0) else 0
            t["est_edge_days"] += 1 if (worked and (r["arrive_src"] in EST_SRC or r["leave_src"] in EST_SRC)) else 0
            if has_rec:
                t["unrecorded_h"] += un
        for t in (m, total, wk):
            t["plus_est_h"] += est
            t["plus_est_offpc_h"] += est_off
            if has_rec:
                t["plus_days"] += 1 if est > eps else 0
        for k in _WEEK_KEYS:
            wk[k] += float(r.get(k) or 0.0)
        wk["days"] += 1 if worked else 0
    # 근태와 견준 값(이 PC 전용) — 근태에만 있는 날(LM 행 없음)도 hr 에 있다
    for iso in sorted(hr):
        x = hr[iso]
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        for t in (total, months.get(iso[:7]), weeks.get(_week_key(d))):
            if t is None:
                continue
            t["plus_h"] += x["plus"] / 60.0
            t["plus_offpc_h"] += x["plus_off"] / 60.0
            t["missing_h"] += x["missing"] / 60.0
            t["gate_plus_h"] += x["gate_plus"] / 60.0
            t["plus_days"] += 1 if x["plus"] / 60.0 > eps else 0
            t["rec_days"] += 1 if x["row"] else 0
            t["gate_days"] += 1 if x["gate"] else 0
    if has_rec:
        for t in [total] + list(months.values()) + list(weeks.values()):
            t["plus_all_h"] = t["plus_h"] + t["plus_est_h"]
    if pcu:
        # LM30(2026-10-20) 켜 둔 날(머리말 19) — 근무가 없어 행이 없는 날도 센다(그 주·달에 행이 있을 때만 그 칸에, 전체에는 늘)
        for dd in sorted(x for x in ao if isinstance(x, date) and d0 <= x <= d1):
            for t in (total, months.get(dd.isoformat()[:7]), weeks.get(_week_key(dd))):
                if t is not None:
                    t["always_on_days"] += 1
    for t in [total] + list(months.values()) + list(weeks.values()):
        t["offday_h"] = t["holiday_h"]                        # LM30(2026-10-19) 주말 + 공휴일 근무(머리말 16 — holiday_h 와 같은 값)
    total["over40_h"] = 0.0
    for wk in weeks.values():
        for k, v in list(wk.items()):
            if isinstance(v, float):
                wk[k] = _r(v)
        wk["over40_h"] = _r(max(0.0, wk["work_h"] - p["weekHours"]))
        wk["over52"] = bool(wk["work_h"] > p["weekMaxHours"] + 1e-9)
        wk["partial"] = bool(wk["from"] < d0.isoformat() or wk["to"] > d1.isoformat())
        total["over40_h"] += wk["over40_h"]
        if wk["over52"]:
            mk = (date.fromisoformat(wk["from"]) + timedelta(days=3)).isoformat()[:7]
            if mk not in months:
                mk = min(wk["to"], d1.isoformat())[:7]
            if mk in months:
                months[mk]["over52_weeks"] += 1
            total["over52_weeks"] += 1
    for t in list(months.values()) + [total]:
        for k, v in list(t.items()):
            if isinstance(v, float):
                t[k] = _r(v)
    total["weeks"] = len(weeks)
    out = {"schema": 1, "method": "출퇴근 추정", "weeks": weeks, "months": months, "total": total}
    if records is not None:
        out["records"] = records
    return out


def usual_times(days, d1, now):
    """평소 출근·퇴근(이 PC 전용) — 최근 28일(기간 끝·오늘 중 이른 날까지)의 휴가 없는 평일 중 신뢰도 보통 이상·일하는 중이 아닌
    날의 가운데 값. 시차 출퇴근·선택 근로인 사람이 자기 평소 시각을 본다. → {arrive, leave, leave_day, n, from, to}"""
    end = min(d1, now.date())
    start = end - timedelta(days=USUAL_DAYS - 1)
    arr, lev = [], []
    for iso, r in days.items():
        d = date.fromisoformat(iso)
        if (not (start <= d <= end) or r["kind"] != "workday" or r["leave_frac"] > 0 or r["conf"] not in ("high", "mid")
                or not r["blocks"] or r["leave_src"] == "now"):
            continue
        arr.append(r["blocks"][0][0])
        lev.append(max(b[1] for b in r["blocks"]))
    out = {"arrive": "", "leave": "", "leave_day": 0, "n": len(arr), "from": start.isoformat(), "to": end.isoformat()}
    if arr:
        a, lv = statistics.median(arr), statistics.median(lev)
        out.update(arrive=hm(a), leave=hm(lv), leave_day=int(int(round(lv)) // 1440))
    return out


# ════════════════════════════════ 근태 기록 칸 ════════════════════════════════
_REC_COLS = {"date": ("날짜", "date"), "in": ("출근", "in", "start"), "out": ("퇴근", "out", "end"),
             "break": ("휴게(분)", "break"), "approved_ot": ("인정연장", "approved_ot"), "leave": ("휴가", "leave"),
             # LM30(2026-10-19) 태깅(출입 기록) — 첫 입실·마지막 퇴실(GERP 기록의 gerp.csv 에 있다 · 참고 — gate_plus_h)
             "gate_in": ("입실", "gate_in"), "gate_out": ("퇴실", "gate_out")}
_DATE_RE = re.compile(r"(\d{4})\s*[-./년]?\s*(\d{1,2})\s*[-./월]?\s*(\d{1,2})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::\d{2})?")
_LEAVE_HALF = ("반차", "반휴", "오전", "오후", "half")
_LEAVE_FULL = ("연차", "휴가", "병가", "경조", "공가", "휴무", "휴직", "leave", "vacation", "pto")


def _hkey(h):
    return re.sub(r"\s+", "", str(h or "").replace("﻿", "")).lower()


def _decode(b):
    """UTF-8(BOM 있음·없음) → 아니면 CP949(엑셀 '다른 이름으로 저장' 기본)"""
    if b[:3] == b"\xef\xbb\xbf":
        return b[3:].decode("utf-8", "replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp949", "replace")


def _rdate(s):
    m = _DATE_RE.search(str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _rtime(s):
    """'08:30'·'8:30:00'·'2026-09-01 08:30'·'오후 6:10' → 그날 분(24시를 넘는 '25:30' 도 받는다). 못 읽으면 None."""
    s = str(s or "").strip()
    ms = _TIME_RE.findall(s)
    if not ms:
        return None
    h, m = int(ms[-1][0]), int(ms[-1][1])
    low = s.lower()
    if ("오후" in s or "pm" in low) and h < 12:
        h += 12
    elif ("오전" in s or "am" in low) and h == 12:
        h = 0
    if m >= 60 or h > 47:
        return None
    return float(h * 60 + m)


def _rleave(s):
    s = str(s or "").strip()
    if not s:
        return 0.0
    try:
        return min(1.0, max(0.0, float(s)))
    except ValueError:
        pass
    low = s.lower()
    if any(k in low for k in _LEAVE_HALF):
        return 0.5
    return 1.0 if any(k in low for k in _LEAVE_FULL) else 0.0


def _rec_row(r, idx):
    """CSV 한 행 → (날짜, {in, out, break_min, approved_ot, leave}) · (날짜, None)(빈 날) · None(읽을 수 없는 행).
    LM30(2026-10-19) 빈 날 — 날짜만 있고 출근·퇴근이 둘 다 비었고 휴가도 아닌 행(주말·휴일·근무 기록이 없는 날). 내려받은 근태 기록과
    GERP 기록(core\\gerp — data\\근태\\gerp.csv)에는 이런 날이 늘 섞인다. 읽지 못한 행이 아니다(예전에는 '읽지 못한 행'으로 셌다) —
    기록으로 쓰지 않고 파일 기간(range)에만 넣는다(그 기간 안의 근무는 '근태 기록이 없는 근무일'로 견준다)."""
    def cell(k):
        i = idx.get(k)
        return str(r[i]).strip() if i is not None and i < len(r) else ""
    d = _rdate(cell("date"))
    if d is None:
        return None
    t_in, t_out = _rtime(cell("in")), _rtime(cell("out"))
    if (cell("in") and t_in is None) or (cell("out") and t_out is None):
        return None
    lv = _rleave(cell("leave"))
    if t_in is None or t_out is None:
        if t_in is None and t_out is None and lv > 0:
            return d, {"in": None, "out": None, "break_min": None, "approved_ot": None, "leave": lv}
        if t_in is None and t_out is None:
            return d, None
        return None
    if t_out <= t_in:
        t_out += 1440.0                                       # 자정을 넘긴 퇴근
    bm = None
    if cell("break"):
        try:
            bm = float(cell("break"))
        except ValueError:
            return None
        if not (0 <= bm <= 600):
            return None
    try:
        ot = float(cell("approved_ot")) if cell("approved_ot") else None
    except ValueError:
        ot = None
    return d, {"in": t_in, "out": t_out, "break_min": bm, "approved_ot": ot, "leave": lv}


def _rec_merge(cur, v):
    """같은 날 두 행(나눠 찍은 출퇴근) — 이른 출근·늦은 퇴근, 휴게·인정연장은 더하고, 휴가는 큰 쪽."""
    if cur is None:
        return v
    out = dict(cur)
    ins = [x for x in (cur["in"], v["in"]) if x is not None]
    outs = [x for x in (cur["out"], v["out"]) if x is not None]
    out["in"], out["out"] = (min(ins) if ins else None), (max(outs) if outs else None)
    for k in ("break_min", "approved_ot"):
        vals = [x for x in (cur[k], v[k]) if x is not None]
        out[k] = sum(vals) if vals else None
    out["leave"] = max(cur["leave"], v["leave"])
    return out


def _rec_gate(r, idx):
    """CSV 한 행의 태깅 칸(입실·퇴실 — LM30 2026-10-19) → {"in": 분|None, "out": 분|None} | None(둘 다 없거나 못 읽음).
    '25:30'(다음 날 새벽)을 받고, 퇴실이 입실보다 이르면 다음 날로 본다. 못 읽은 태깅은 근태 행을 버리지 않는다(참고 칸이다)."""
    def cell(k):
        i = idx.get(k)
        return str(r[i]).strip() if i is not None and i < len(r) else ""
    gi, go = _rtime(cell("gate_in")), _rtime(cell("gate_out"))
    if gi is None and go is None:
        return None
    if gi is not None and go is not None and go < gi:
        go += 1440.0
    return {"in": gi, "out": go}


def _gate_merge(cur, g):
    """같은 날 두 행의 태깅 — 이른 입실·늦은 퇴실"""
    if cur is None:
        return g
    ins = [x for x in (cur["in"], g["in"]) if x is not None]
    outs = [x for x in (cur["out"], g["out"]) if x is not None]
    return {"in": min(ins) if ins else None, "out": max(outs) if outs else None}


def load_records(data_dir):
    r"""근태 기록 칸 — data\근태\*.csv(ERP 등에서 내려받아 넣는 파일 · GERP 근무 기록 읽기가 모으는 gerp.csv). 머리말: 날짜|date ·
    출근|in|start · 퇴근|out|end · (있으면) 휴게(분)|break · 인정연장|approved_ot · 휴가|leave · 입실|gate_in · 퇴실|gate_out(그 밖의
    열은 읽지 않는다). 인코딩은 UTF-8(BOM 있음·없음), 아니면 CP949.
    → {"present": 파일이 있었나, "files": 읽은 파일 수, "rows": {날짜: {in, out(분 — 자정 넘김은 +1440), break_min, approved_ot,
       leave}}, "bad": 읽지 못한 행 수, "blank": 빈 날 수(_rec_row — 기록 없이 기간에만), "range": (첫 날짜, 끝 날짜) | None,
       "gates": {날짜: {in, out}(분 — 첫 입실·마지막 퇴실, 다음 날 새벽은 +1440)}(근태 행·빈 날 모두 — 참고)}.
    폴더가 없으면 present False(오류 아님)."""
    out = {"present": False, "files": 0, "rows": {}, "bad": 0, "blank": 0, "range": None, "gates": {}}
    blank = set()
    folder = os.path.join(str(data_dir or ""), RECORDS_DIR)
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".csv"))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(folder, n), "rb") as f:
                raw = f.read()
        except OSError:
            continue
        out["present"] = True
        try:
            rows = [r for r in csv.reader(io.StringIO(_decode(raw))) if any(str(c).strip() for c in r)]
        except csv.Error:
            out["bad"] += 1
            continue
        if not rows:
            continue
        out["files"] += 1
        hdr = [_hkey(h) for h in rows[0]]
        idx = {}
        for key, names_ok in _REC_COLS.items():
            want = {_hkey(x) for x in names_ok}
            for i, h in enumerate(hdr):
                if h in want:
                    idx[key] = i
                    break
        if "date" not in idx or not (("in" in idx and "out" in idx) or "leave" in idx):
            out["bad"] += len(rows) - 1                       # 머리말을 알아볼 수 없는 파일 — 행 전부를 못 읽은 것으로
            continue
        for r in rows[1:]:
            got = _rec_row(r, idx)
            if got is None:
                out["bad"] += 1
                continue
            g = _rec_gate(r, idx)                             # 태깅(입실·퇴실) — 빈 날(기록 없이 건물에 온 날)에도(LM30 2026-10-19)
            if g is not None:
                out["gates"][got[0]] = _gate_merge(out["gates"].get(got[0]), g)
            if got[1] is None:
                blank.add(got[0])                             # 빈 날 — 기록이 아니라 파일 기간에만(LM30 2026-10-19)
                continue
            out["rows"][got[0]] = _rec_merge(out["rows"].get(got[0]), got[1])
    out["blank"] = len(blank - set(out["rows"]))
    span = set(out["rows"]) | blank
    if span:
        ds = sorted(span)
        out["range"] = (ds[0], ds[-1])
    return out


def _rec_minutes(v, p):
    """근태 행 → (근태 시간 분, 근태 휴게 분) — (퇴근 − 출근) − (휴게 열, 없으면 4시간마다 breakPer4hMin). 시각이 없으면 (0, 0)."""
    if v is None or v.get("in") is None or v.get("out") is None:
        return 0.0, 0.0
    span = float(v["out"]) - float(v["in"])
    bm = v["break_min"] if v.get("break_min") is not None else p["breakPer4hMin"] * math.floor(span / 240.0 + 1e-9)
    return max(0.0, span - float(bm)), float(bm)


def _ov(a0, a1, b0, b1):
    """[a0, a1] 과 [b0, b1] 이 겹친 길이"""
    return max(0.0, min(a1, b1) - max(a0, b0))


def _hr_day(r, v, g, p):
    r"""근태 기록 칸 기간 안의 하루 → 근태와 견준 값(분 — 이 PC 전용: 근태·GERP·태깅에서 나온 값) | None(견줄 것이 없다).
    LM30(2026-10-19) +@ — 규칙은 머리말 14.
      r = 날짜별 행(없으면 None — 근태에만 있는 날) · v = 근태 행(없으면 None — 기록 없는 날·빈 날) · g = 태깅 {in, out}(분) | None
    → {kind: window(출근~퇴근 창이 있다)|norow(기록 없는 날)|leave(종일 휴가)|notimes(출퇴근 시각이 없는 날), row(근태 행이 있나),
       rec_m(근태 시간), plus(+@), plus_off(그중 PC 밖), early·late(근태 출근 전·퇴근 뒤 — 휴게를 뺀 뒤, 합 = plus),
       missing(창 중 LM 이 못 본 시간 − 근태 휴게 − 시각을 모르는 근무 — 참고), gate(태깅이 있나), gate_in·gate_out(분 | None),
       gate_plus(입실~퇴실 중 창 밖 — 참고, 근무에 더하지 않는다)}"""
    rr = r if isinstance(r, dict) else {}

    def num(k):
        try:
            x = float(rr.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0
        return x if math.isfinite(x) else 0.0
    work = num("work_h") * 60.0
    bl = []
    for b in rr.get("blocks") or []:
        if isinstance(b, (list, tuple)) and len(b) >= 3:
            try:
                a0, a1 = float(b[0]), float(b[1])
            except (TypeError, ValueError):
                continue
            if a1 > a0:
                bl.append((a0, a1, str(b[2])))
    raw = sum(b - a for a, b, _k in bl)
    brk = min(raw, num("break_h") * 60.0)
    gi = g.get("in") if isinstance(g, dict) else None
    go = g.get("out") if isinstance(g, dict) else None
    no_gate = gi is None and go is None
    if v is None and work / 60.0 <= REC_EPS_H and no_gate:
        return None                                         # 기록도 근무도 태깅도 없는 날 — 견줄 것이 없다
    rec_m, hb = _rec_minutes(v, p)
    lv = float((v or {}).get("leave") or 0)
    win = None
    if v is not None and v.get("in") is not None and v.get("out") is not None and lv < 1.0:
        win = (float(v["in"]), float(v["out"]))
    kind = "window" if win else ("norow" if v is None else ("leave" if lv >= 1.0 else "notimes"))
    x = {"kind": kind, "row": v is not None, "rec_m": rec_m, "plus": 0.0, "plus_off": 0.0, "early": 0.0, "late": 0.0,
         "missing": 0.0, "gate": not no_gate, "gate_in": gi, "gate_out": go, "gate_plus": 0.0}
    if win is None:
        x["plus"] = work                                     # 기록 없는 날·종일 휴가·시각 없는 날 — 그날 근무 전부가 +@
        x["plus_off"] = min(work, num("offpc_h") * 60.0)
    else:
        w0, w1 = win
        in_raw = sum(_ov(a, b, w0, w1) for a, b, _k in bl)
        early = sum(_ov(a, b, -1e9, w0) for a, b, _k in bl)
        out_raw = max(0.0, raw - in_raw)
        late = max(0.0, out_raw - early)
        b_in = min(brk, in_raw, hb)                          # 근태 기록이 뺀 만큼은 창 안에서(점심은 보통 창 안)
        b_out = min(brk - b_in, out_raw)                     # 더 길게 일해 늘어난 휴게는 창 밖에서 — 퇴근 뒤 쪽 먼저
        plus = max(0.0, min(out_raw - b_out, work))          # 하루 상한(dayCapHours·24시간)으로 줄인 날은 그 근무까지
        late_n = late - min(b_out, late)
        early_n = max(0.0, early - (b_out - min(b_out, late)))
        if late_n + early_n > plus + 1e-9:
            f = plus / (late_n + early_n)
            late_n, early_n = late_n * f, early_n * f
        unplaced = max(0.0, work - (raw - brk))              # 시각을 모르는 근무(LM29 방식·수동 기록·출장 표준일) — 창 안으로
        # PC 밖 덩어리 중 창 밖 — 그날 PC 기록이 없으면 PC 밖으로 세지 않는다(_day_row 의 offpc_h 와 같다)
        off_out = sum((b - a) - _ov(a, b, w0, w1) for a, b, k in bl if k == "offpc") if num("offpc_h") > 0 else 0.0
        x.update(plus=plus, plus_off=min(plus, off_out), early=early_n, late=late_n,
                 missing=max(0.0, (w1 - w0) - in_raw - hb - unplaced))
    if gi is not None and go is not None:
        g0, g1 = float(gi), float(go)
        if g1 < g0:
            g1 += 1440.0
        x["gate_plus"] = max(0.0, (g1 - g0) - (_ov(g0, g1, *win) if win is not None else 0.0))
    return x


def _rec_view(r, v, x):
    """_hr_day 값 → 날짜별 행의 rec(화면·리포트 — 근태 시각·시간: 이 PC 전용). 예전 칸(in·out·h·diff_h·out_day·leave·approved_ot·
    missing(근태 행이 없는 날))은 그대로 두고 +@ 칸(kind·plus_h·plus_offpc_h·early_h·late_h·missing_h·gate_in·gate_out·
    gate_out_day·gate_plus_h — 0 인 시간 칸은 뺀다)을 더한다."""
    work = float(r.get("work_h") or 0)
    if v is None:
        rc = {"in": "", "out": "", "h": 0.0, "diff_h": _r(work), "missing": True}
    else:
        rc = {"in": hm(v["in"]) if v.get("in") is not None else "", "out": hm(v["out"]) if v.get("out") is not None else "",
              "h": _r(x["rec_m"] / 60.0), "diff_h": _r(work - x["rec_m"] / 60.0)}
        if v.get("out") is not None and v["out"] >= 1440:
            rc["out_day"] = int(v["out"] // 1440)
        if v.get("leave"):
            rc["leave"] = v["leave"]
        if v.get("approved_ot") is not None:
            rc["approved_ot"] = v["approved_ot"]
    rc["kind"] = x["kind"]
    rc["plus_h"] = _r(x["plus"] / 60.0)
    for k, key in (("plus_off", "plus_offpc_h"), ("early", "early_h"), ("late", "late_h"), ("missing", "missing_h"),
                   ("gate_plus", "gate_plus_h")):
        if x[k] / 60.0 >= 0.005:
            rc[key] = _r(x[k] / 60.0)
    if x["gate_in"] is not None:
        rc["gate_in"] = hm(x["gate_in"])
        if x["gate_in"] >= 1440:
            rc["gate_in_day"] = int(x["gate_in"] // 1440)
    if x["gate_out"] is not None:
        go = float(x["gate_out"])
        if x["gate_in"] is not None and go < float(x["gate_in"]):
            go += 1440.0
        rc["gate_out"] = hm(go)
        if go >= 1440:
            rc["gate_out_day"] = int(go // 1440)
    return rc


def hr_compare(days, rec, d0, d1, p):
    r"""근태 기록 칸(load_records)과 날짜별 행을 날마다 견준다(LM30 2026-10-19 +@) → {iso: _hr_day 값(분)} — 기록 칸 기간 안이고
    [d0, d1] 안인 날만(근태에만 있는 날 포함). LM 행이 있는 날에는 rec(_rec_view — 화면·리포트용, 이 PC 전용)을 붙인다.
    투입 시간(work_h)·다른 칸은 건드리지 않는다(MM 이 그대로다)."""
    rec = rec if isinstance(rec, dict) else {}
    out = {}
    rng = rec.get("range")
    if not rec.get("present") or not rng:
        return out
    rows, gates = rec.get("rows") or {}, rec.get("gates") or {}
    d, end = max(d0, rng[0]), min(d1, rng[1])
    while d <= end:
        iso = d.isoformat()
        r, v = days.get(iso), rows.get(d)
        x = _hr_day(r, v, gates.get(d), p)
        if x is not None:
            out[iso] = x
            if isinstance(r, dict):
                r["rec"] = _rec_view(r, v, x)
        d += timedelta(days=1)
    return out


def compare_records(days, rec, d0, d1, p, hr=None):
    """날짜별 행에 근태 기록 비교(rec — hr_compare)를 붙이고 요약을 낸다(시각 없음 — 그래도 근태에서 나온 값이라 이 PC 전용).
    근태 시간 = (퇴근 − 출근) − (휴게 열, 없으면 4시간마다 breakPer4hMin). diff_h = 추정 근무 − 근태 시간. hr = hr_compare 값(없으면 잰다).
    → {present, files, bad_rows, days(기간 안 기록 행), unrecorded_h(+ 차이의 합 + 파일 기간 안인데 기록 행이 없는 날의 근무),
       unrecorded_days, no_record_work_days, rec_only_days(근태에는 근무가 있는데 이 PC 흔적은 없는 날), range,
       plus_h·plus_offpc_h·plus_days(+@ — 근태와 견준 것), missing_h, gate_plus_h, gate_days(LM30 2026-10-19)}"""
    rec = rec if isinstance(rec, dict) else {}
    s = {"present": bool(rec.get("present")), "files": int(rec.get("files") or 0), "bad_rows": int(rec.get("bad") or 0),
         "days": 0, "unrecorded_h": 0.0, "unrecorded_days": 0, "no_record_work_days": 0, "rec_only_days": 0, "range": [],
         "plus_h": 0.0, "plus_offpc_h": 0.0, "plus_days": 0, "missing_h": 0.0, "gate_plus_h": 0.0, "gate_days": 0}
    if not s["present"]:
        return s
    hr = hr_compare(days, rec, d0, d1, p) if hr is None else hr
    rows, rng = rec.get("rows") or {}, rec.get("range")
    if rng:
        s["range"] = [rng[0].isoformat(), rng[1].isoformat()]
    d = d0
    while d <= d1:
        r, v = days.get(d.isoformat()), rows.get(d)
        work = float(r.get("work_h") or 0) if isinstance(r, dict) else 0.0
        if v is not None:
            s["days"] += 1
            rec_h = _rec_minutes(v, p)[0] / 60.0
            diff = work - rec_h
            if r is None and rec_h > 0:
                s["rec_only_days"] += 1
            if diff > REC_EPS_H:
                s["unrecorded_h"] += diff
                s["unrecorded_days"] += 1
        elif rng and rng[0] <= d <= rng[1] and work > REC_EPS_H:
            s["no_record_work_days"] += 1
            s["unrecorded_days"] += 1
            s["unrecorded_h"] += work
        d += timedelta(days=1)
    for x in hr.values():
        s["plus_h"] += x["plus"] / 60.0
        s["plus_offpc_h"] += x["plus_off"] / 60.0
        s["plus_days"] += 1 if x["plus"] / 60.0 > REC_EPS_H else 0
        s["missing_h"] += x["missing"] / 60.0
        s["gate_plus_h"] += x["gate_plus"] / 60.0
        s["gate_days"] += 1 if x["gate"] else 0
    for k in ("unrecorded_h", "plus_h", "plus_offpc_h", "missing_h", "gate_plus_h"):
        s[k] = _r(s[k])
    return s


# ════════════════════════════════ 이 PC 전용 칸 떼기 ════════════════════════════════
def clock_to_hours(db):
    """LM29 날짜별 근거(day_basis[날짜])의 시각 창(evening·dawn — [["19:00","21:30"]]) → 길이(evening_h·dawn_h)."""
    for k in CLOCK_KEYS:
        if k not in db:
            continue
        w = db.pop(k)
        tot = 0.0
        for x in (w if isinstance(w, list) else []):
            if isinstance(x, (list, tuple)) and len(x) == 2:
                a, b = _hm2m(x[0]), _hm2m(x[1])
                if a is not None and b is not None and b > a:
                    tot += b - a
        db[k + "_h"] = round(tot / 60.0, 2)


def take_local(info):
    r"""info(day_work_hours)에서 이 PC에만 둘 것을 떼어 낸다 → (days, usual, agg). mm_meta 를 쓰기 전에 부른다 — 날짜별 출근·퇴근·
    덩어리·평소 시각은 report\attendance_<기간>.json 으로만 간다(core\extract.save_attendance). LM29 날짜별 근거의 저녁·새벽
    창(시각)도 같은 까닭으로 길이(evening_h·dawn_h)로 바꾼다. info 가 dict 가 아니면 (None, None, None).
    LM30(2026-10-19) agg = 근태 기록과 견준 값까지 든 합계(info["attendance_agg"] — 없으면 info["attendance"] 의 사본) — attendance
    파일의 agg 로 쓴다. info["attendance"](mm_meta 로 가는 것)에는 근태 없이 잰 합계만 남는다(scrub_meta → strip_hr 가 한 번 더 본다)."""
    if not isinstance(info, dict):
        return None, None, None
    days, usual = info.pop("attendance_days", None), info.pop("attendance_usual", None)
    agg = info.pop("attendance_agg", None)
    if agg is None or agg is info.get("attendance"):
        agg = copy.deepcopy(info.get("attendance")) if isinstance(info.get("attendance"), dict) else agg
    scrub_meta(info)
    return days, usual, agg


def strip_hr(a):
    """출퇴근 합계(dict — weeks·months·total·records)에서 근태 기록·GERP·태깅에서 나온 값을 뺀다(제자리) → 뺀 것이 있나.
    LM30(2026-10-19) — mm_meta·팀 묶음·공유폴더·얼린 보고서로 나가기 직전의 관문(scrub_meta·freeze). 근태 칸(HR_KEYS)이 섞인 칸의
    +@ 추정(EST_KEYS)은 근태 기록이 있는 날을 뺀 값이라 같이 뺀다(보여 줄 때는 연장 + 휴일로 다시 낸다 — est_of)."""
    if not isinstance(a, dict):
        return False
    hit = False
    if "records" in a:
        a.pop("records")
        hit = True
    blocks = [a.get("total")]
    for k in ("months", "weeks"):
        if isinstance(a.get(k), dict):
            blocks += list(a[k].values())
    for t in blocks:
        if isinstance(t, dict) and any(k in t for k in HR_KEYS):
            for k in HR_KEYS + EST_KEYS:
                t.pop(k, None)
            hit = True
    return hit


def hr_view(agg):
    """attendance 파일의 합계(근태 기록과 견준 값까지 — compute 의 agg) → 근태에서 나온 칸만 {"weeks", "months", "total", "records"}
    (각 칸은 HR_KEYS + 그 합계의 plus_est_h·plus_est_offpc_h — 근태 기록이 없는 날만 센 추정) | None(근태 기록이 없었다).
    화면 카드·리포트 §8 이 근태 없이 잰 합계(mm_meta) 위에 얹는다 — 이 PC 화면·리포트에서만 쓴다(얼린 사본·분석리포트는 쓰지 않는다)."""
    if not isinstance(agg, dict):
        return None
    rc = agg.get("records")
    if not (isinstance(rc, dict) and rc.get("present")):
        return None
    keys = HR_KEYS + EST_KEYS

    def pick(t):
        return {k: t[k] for k in keys if isinstance(t, dict) and k in t}
    out = {"records": rc, "total": pick(agg.get("total"))}
    for k in ("weeks", "months"):
        src = agg.get(k) if isinstance(agg.get(k), dict) else {}
        out[k] = {str(n): pick(v) for n, v in src.items() if isinstance(v, dict)}
    return out


def scrub_meta(mj):
    """mm_meta(dict — 최상위와 mm_basis)에서 이 PC 전용 칸을 뺀다: attendance_days·attendance_usual·attendance_agg·
    attendance.usual/days·근태 기록에서 나온 합계 칸(strip_hr — LM30 2026-10-19)·day_basis 의 시각 창. 팀 묶음·공유폴더로 나가기
    직전의 두 번째 관문(teamup·export·freeze). 뺀 것이 있으면 True."""
    hit = False
    for h in (mj, mj.get("mm_basis") if isinstance(mj, dict) else None):
        if not isinstance(h, dict):
            continue
        for k in LOCAL_KEYS:
            if k in h:
                h.pop(k)
                hit = True
        a = h.get("attendance")
        if isinstance(a, dict):
            for k in ("usual", "days"):
                if k in a:
                    a.pop(k)
                    hit = True
            if strip_hr(a):
                hit = True
        db = h.get("day_basis")
        if isinstance(db, dict):
            for v in db.values():
                if isinstance(v, dict) and any(k in v for k in CLOCK_KEYS):
                    clock_to_hours(v)
                    hit = True
    return hit


# ════════════════════════════════ 보여 주기(화면 카드·리포트 §8 공용 문구) ════════════════════════════════
# LM30(2026-10-18) — 대시보드 '출퇴근·시간외 근무' 카드(ui\app.py /api/attendance)·리포트 §8(report_out.attendance_section)·분석리포트
# (freeze — 날짜별 표 없이)가 같은 쉬운 말을 쓰게 한 곳에 둔다. day_why·usual_text 는 시각을 담는다 — 이 PC 의 화면·리포트에서만 쓴다
# (얼린 사본·분석리포트는 그 칸을 싣지 않는다). headline·rule_text 는 합계·규칙뿐이라 어디에 실려도 된다.
# LM30(2026-10-19) +@ — records_text·day_plus·hr 를 준 plus_line 은 근태 기록에서 나온 값을 담는다(이 PC 의 화면·리포트에서만). 얼린
# 사본·분석리포트는 plus_line(hr 없이 — 근태 없이 추정한 +@)과 FROZEN_REC_TEXT 를 쓴다.
CONF_KO = {"high": "높음", "mid": "보통", "low": "낮음"}
# LM30(2026-10-19) lm29 — LM29 구간의 가장자리(머리말 15) · LM30(2026-10-20) pcuse·pcwin — PC 사용 구간·켜 둔 날 낮 창의 가장자리(19)
_IN_KO = {"pc": "PC 켬", "meeting": "회의 시작", "manual": "수동 기록 시작", "offsite": "출장·현장 시작", "web": "브라우저 사용",
          L29_KIND: "PC 켜진 시간(LM29 방식)", PCU_EDGE: "PC 사용 시작", PCW_KIND: "낮 시작"}
_OUT_KO = {"pc": "PC 끔·잠금", "meeting": "회의 끝", "manual": "수동 기록 끝", "offsite": "출장·현장 끝",
           L29_KIND: "PC 켜진 시간(LM29 방식)", PCU_EDGE: "PC 사용 끝", PCW_KIND: "낮 끝"}
_DAY_KO = {"lm29": "흔적이 적어 LM29 방식 값", "untimed": "시각 없이 날짜만 아는 발신", "offsite": "종일 출장·교육 — 표준일",
           "manual": "수동 기록 시간"}
_FLOOR_KO = {"종일 출장·교육 — 표준일": "종일 출장·교육이라 표준일로 채움", "수동 기록 시간": "수동 기록 시간으로 채움",
             "PC 기록 없음 — LM29 방식 시간": "PC 기록이 없어 LM29 방식 값으로 채움",
             "날짜만 아는 발신": "날짜만 아는 발신으로 채움", "근거가 얇아 LM29 방식 시간": "흔적이 적어 LM29 방식 값으로 채움",
             L29_MORE: "LM29 방식 값이 더 커서 그 값으로 채움"}
_WHY_SKIP = ("일하는 중",)          # 퇴근 쪽 '지금 일하는 중' 과 겹치는 표시


def _p_view(p):
    """norm() 값 또는 mm_meta 의 cfg_used.attendance(반올림한 수) → 기본값 위에 얹은 dict"""
    q = dict(DEFAULTS)
    if isinstance(p, dict):
        q.update({k: v for k, v in p.items() if k in DEFAULTS and v is not None})
    return q


def _clock(t, day):
    """'HH:MM' — 다음 날이면 앞에 '다음 날'"""
    return ("다음 날 " if int(day or 0) > 0 else "") + str(t or "")


def _h1(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = 0.0
    return f"{x:.1f}h"


def day_why(r, p=None):
    r"""날짜별 행(compute 의 days[날짜]) → '근거' 한 줄(쉬운 말) — 화면·리포트의 날짜별 표. 출근 쪽 → 퇴근 쪽, 바닥값·표시는 뒤에.
    예) 'PC 켬 08:05 → 마지막 흔적 뒤 30분' · '회의 시작 09:00 → PC 끔·잠금 18:10 · 휴가일 근무' · '흔적이 적어 LM29 방식 값'.
    p = norm() 값(또는 cfg_used.attendance) — 앞뒤로 붙인 분(30분·PC 밖 10분)을 그 설정대로 적는다. 시각을 담는다(이 PC 전용)."""
    r = r if isinstance(r, dict) else {}
    q = _p_view(p)
    bl = [b for b in (r.get("blocks") or []) if isinstance(b, (list, tuple)) and len(b) >= 3]
    notes = [str(n) for n in (r.get("notes") or []) if str(n) and str(n) not in _WHY_SKIP]
    if not bl:
        main = _DAY_KO.get(str(r.get("arrive_src") or ""), "")
        if not main:
            main = "앞날 근무에 이어져 따로 세지 않음" if not float(r.get("work_h") or 0) else "근무 흔적"
        rest = [n for n in notes if n not in _FLOOR_KO]
        return " · ".join([main] + rest)
    first_off = bl[0][2] == "offpc"
    last_off = max(bl, key=lambda b: b[1])[2] == "offpc"
    a_src, l_src = str(r.get("arrive_src") or ""), str(r.get("leave_src") or "")
    if a_src == PCU_EDGE and l_src == PCU_EDGE:
        # LM30(2026-10-20) 출근·퇴근이 둘 다 PC 사용 구간의 시작·끝(머리말 19) — 'PC 사용(켜기·로그온·절전 해제 ~ 끄기·로그오프·절전)'
        return " · ".join([f"{PCU_WHY} {_clock(r.get('arrive'), r.get('arrive_day'))} → "
                           f"{_clock(r.get('leave'), r.get('leave_day'))}"] + [_FLOOR_KO.get(n, n) for n in notes])
    if a_src in _IN_KO:
        a = f"{_IN_KO[a_src]} {_clock(r.get('arrive'), r.get('arrive_day'))}"
    elif a_src == "lead":
        a = f"첫 흔적 {_dur(q['offpcPadMin'] if first_off else q['leadMin'])} 전"
    else:
        a = f"출근 {_clock(r.get('arrive'), r.get('arrive_day'))}"
    if l_src in _OUT_KO:
        lv = f"{_OUT_KO[l_src]} {_clock(r.get('leave'), r.get('leave_day'))}"
    elif l_src == "web":
        lv = f"마지막 브라우저 사용 뒤 {int(WEB_TAIL_MIN)}분"
    elif l_src == "now":
        lv = "지금 일하는 중"
    elif l_src == "tail":
        lv = f"마지막 흔적 뒤 {_dur(q['offpcPadMin'] if last_off else q['tailMin'])}"
    else:
        lv = f"퇴근 {_clock(r.get('leave'), r.get('leave_day'))}"
    return " · ".join([f"{a} → {lv}"] + [_FLOOR_KO.get(n, n) for n in notes])


def usual_text(u):
    """평소 출근·퇴근(usual_times) → '평소 출근 08:41 · 퇴근 18:05 — 최근 4주(평일 17일의 가운데 값)'. 낼 수 없으면 까닭 한 줄.
    시각을 담는다(이 PC 전용)."""
    u = u if isinstance(u, dict) else {}
    try:
        n = int(u.get("n") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0 or not u.get("arrive") or not u.get("leave"):
        return "평소 출근·퇴근 — 최근 4주에 출근·퇴근 시각이 확실한 평일이 없어 아직 내지 않았습니다"
    return (f"평소 출근 {u['arrive']} · 퇴근 {_clock(u.get('leave'), u.get('leave_day'))} — 최근 {USUAL_DAYS // 7}주"
            f"(평일 {n}일의 가운데 값)")


def _hh(v, dflt):
    """'22:00'·22·'22' → '22' (야간 창 표기)"""
    m = re.match(r"^\s*(\d{1,2})", str(v if v is not None else dflt))
    return f"{int(m.group(1)):02d}" if m else dflt


def rule_text(p=None, std=None, night=None, win=None):
    """재는 법 한 문장(쉬운 말) — 카드·리포트가 같은 문구. std = 표준일(h — mm.standardDayHours) · night = 야간 창(mm.nightWindow) ·
    win = 낮 창(mm.pcFloorWindow — 켜 둔 PC 를 세는 창).
    LM30(2026-10-20) 그 결과를 잰 설정(cfg_used.attendance)에 pcUsage 가 켜져 있으면(머리말 19) 'PC 를 실제로 쓴 시간 + PC 밖 일 − 휴게'
    로 말한다 — 그 키가 없는 옛 결과는 예전 문장(흔적으로 출근·퇴근을 어림하고 켜져만 있던 PC 는 세지 않던 방식)이다."""
    q = _p_view(p)
    try:
        sd = float(std) if std is not None else 8.0
    except (TypeError, ValueError):
        sd = 8.0
    nw = night if isinstance(night, (list, tuple)) and len(night) == 2 else ("22:00", "06:00")
    split = (f"하루 {sd:g}시간을 넘으면 연장, {_hh(nw[0], '22')}~{_hh(nw[1], '06')}시는 야간, 주말·휴일 근무는 휴일 근무로 셉니다.")
    if isinstance(p, dict) and p.get("pcUsage"):
        w0, w1 = _win_hh(win)
        head = (f"근무시간 = PC를 실제로 쓴 시간(켜기·로그온·절전 해제 ~ 끄기·로그오프·절전) + PC 밖에서 한 일(휴대폰 메일·팀즈·회의) "
                f"− 휴게(4시간마다 {_dur(q['breakPer4hMin'])})입니다. 흔적이 없어도 PC를 쓴 시간은 주말·휴일·밤 모두 셉니다. "
                f"{_num0(q['pcUsageMaxSpanH']):g}시간 넘게 켜 둔 채인 PC는 쓴 시간을 알 수 없어 흔적이 있는 날의 낮({w0}~{w1}시 — 주말·휴일은 흔적 앞뒤)만 세고, "
                f"업데이트 깨움({_dur(q['pcUsageMinMin'])}이 안 되는 켜짐·새벽의 짧은 켜짐 — 흔적이 없을 때)은 뺍니다. " + split)
    else:
        head = (f"출근·퇴근은 PC를 켜고 끈 시각과 메일·파일·팀즈·회의 흔적으로 추정합니다. 출근~퇴근에서 4시간마다 "
                f"{_dur(q['breakPer4hMin'])} 휴게를 뺀 시간이 근무시간이고, " + split + " PC가 켜져만 있던 시간은 세지 않습니다.")
    # LM30(2026-10-19) 머리말 15 — 그 결과를 잰 설정(cfg_used.attendance)에 withLM29 가 켜져 있을 때만 한 문장 더(그 키가 없는
    # 옛 결과는 엄격한 방식으로 잰 것이다)
    return head + (" 다만 LM29 방식이 근무로 센 시간(저녁·주말·휴일에 PC를 켜고 일한 시간 포함)보다 적게 세지 않습니다."
                   if isinstance(p, dict) and p.get("withLM29") else "")


def pc_usage_lines(t, win=None):
    """LM30(2026-10-20) PC 사용 시간 줄(머리말 19 — 카드 두 장·리포트 1절·8절 공용) — 합계 칸(주·달·전체의 한 칸) →
    ['PC를 쓴 시간 Xh(주말·휴일 Yh) — 근무시간은 여기에 PC 밖 일(휴대폰 메일·팀즈·회의)을 더하고 휴게를 뺀 시간입니다'
     (+ 켜 둔 날이 있으면 'PC를 켜 둔 채라 쓴 시간을 알 수 없는 날 N일 — 흔적이 있는 날의 낮(08~19시 — 주말·휴일은 흔적 앞뒤)만 셉니다')].
    win = 낮 창(mm.pcFloorWindow). 칸에 pc_usage_h 가 없으면(pcUsage 끔·옛 결과) [] — 합계뿐이라 어디에 실려도 된다."""
    if not isinstance(t, dict) or "pc_usage_h" not in t:
        return []
    out = [f"PC를 쓴 시간 {_num0(t.get('pc_usage_h')):.1f}h(주말·휴일 {_num0(t.get('pc_usage_off_h')):.1f}h) — 근무시간은 여기에 "
           "PC 밖 일(휴대폰 메일·팀즈·회의)을 더하고 휴게를 뺀 시간입니다"]
    n = int(_num0(t.get("always_on_days")))
    if n > 0:
        w0, w1 = _win_hh(win)
        out.append(f"PC를 켜 둔 채라 쓴 시간을 알 수 없는 날 {n}일 — 흔적이 있는 날의 낮({w0}~{w1}시 — 주말·휴일은 흔적 앞뒤)만 셉니다")
    return out


# ── LM30(2026-10-19) 시간외 나눠 보기(머리말 16)·발신 흔적 빈 곳(머리말 17) — 카드·리포트 공용 문구 ──
SEND_GAP_TEXT = ("최근 2주 메일·팀즈 발신 흔적이 없습니다 — 새로 깔았다면 [AI 연결 진단]에서 전용 Edge에 한 번 로그인해야 "
                 "메일·팀즈를 읽습니다. 저녁·주말 근무는 주로 이 흔적으로 잡힙니다.")


def offhours_line(t, night=None, used=True):
    """합계 칸(주·달·전체 — weeks·months·total 의 한 칸) → '주말·휴일 4.0h · 저녁(19~22시) 6.5h · 야간(22~06시) 1.0h — 모두 투입에
    들어 있습니다'. 주말·휴일 = offday_h(없는 옛 합계면 holiday_h) · 저녁 = evening_h(없는 옛 합계면 그 조각을 뺀다) · 야간 = night_h.
    night = 야간 창(mm.nightWindow — 표기만) · used = 이 근무시간으로 투입 MM 을 쟀나(아니면 '참고'). 칸이 dict 가 아니면 ''."""
    if not isinstance(t, dict):
        return ""
    nw = night if isinstance(night, (list, tuple)) and len(night) == 2 else ("22:00", "06:00")
    bits = [f"주말·휴일 {_num0(t.get('offday_h') if 'offday_h' in t else t.get('holiday_h')):.1f}h"]
    if "evening_h" in t:
        bits.append(f"저녁(19~22시) {_num0(t.get('evening_h')):.1f}h")
    bits.append(f"야간({_hh(nw[0], '22')}~{_hh(nw[1], '06')}시) {_num0(t.get('night_h')):.1f}h")
    return " · ".join(bits) + (" — 모두 투입에 들어 있습니다" if used else " — 참고(투입 MM은 LM29 방식으로 쟀습니다)")


def send_gap(pc_days, sends, d0, d1, today, is_off=None, untimed=None):
    """발신 흔적 빈 곳(머리말 17) — 건수·날짜만 본다(메일 글은 보지 않는다).
      pc_days = PC 를 켠 날(집합) · sends = {날짜: 시각 있는 내 발신 수} · untimed = {날짜: 날짜만 아는 내 발신 수} ·
      d0·d1 = 분석 기간 · today = 오늘(기간 끝이 앞날이면 오늘까지) · is_off(날짜) = 휴일인가(없으면 토·일)
    → {"days": 14, "from", "to", "pc_days"(그 안의 PC 켠 평일), "sends"(시각 있는 발신), "untimed"(날짜만 아는 발신),
       "recent"(PC 켠 평일 ≥ 3 인데 발신 0), "months": [PC 켠 평일 ≥ 5 인데 발신 0 인 달 'YYYY-MM'], "warn"}.
    날짜만 아는 발신도 '발신이 있다'로 본다 — 메일·팀즈를 읽고 있는데 '로그인하라'는 말이 나오지 않게."""
    is_off = is_off or (lambda dd: dd.isoweekday() > 5)
    sends, untimed = sends or {}, untimed or {}
    end = min(d1, today) if today is not None else d1
    start = max(d0, end - timedelta(days=SEND_GAP_DAYS - 1))

    def n_of(m, dd):
        try:
            return max(0, int(m.get(dd) or 0))
        except (TypeError, ValueError):
            return 0
    pcd = {dd for dd in (pc_days or ()) if isinstance(dd, date) and d0 <= dd <= end and not is_off(dd)}
    rec_pc = sum(1 for dd in pcd if start <= dd)
    rec_t = sum(n_of(sends, dd) for dd in sends if isinstance(dd, date) and start <= dd <= end)
    rec_u = sum(n_of(untimed, dd) for dd in untimed if isinstance(dd, date) and start <= dd <= end)
    mon = {}
    for dd in pcd:
        mon.setdefault(dd.strftime("%Y-%m"), [0, 0])[0] += 1
    for src in (sends, untimed):
        for dd in src:
            if isinstance(dd, date) and d0 <= dd <= end:
                mon.setdefault(dd.strftime("%Y-%m"), [0, 0])[1] += n_of(src, dd)
    months = sorted(k for k, (n_pc, n_s) in mon.items() if n_pc >= SEND_GAP_MONTH_PC_DAYS and n_s == 0)
    recent = bool(end >= start and rec_pc >= SEND_GAP_PC_DAYS and rec_t + rec_u == 0)
    return {"days": SEND_GAP_DAYS, "from": start.isoformat(), "to": end.isoformat(), "pc_days": rec_pc, "sends": rec_t,
            "untimed": rec_u, "recent": recent, "months": months, "warn": bool(recent or months)}


def send_gap_text(sg):
    """send_gap 값 → 경고 한 줄(쉬운 말) · 경고가 없으면 ''. 최근 2주면 SEND_GAP_TEXT, 달만이면 '2026년 9월에 메일·팀즈 발신 흔적이
    없습니다 — …'(같은 뒷말)."""
    if not isinstance(sg, dict) or not sg.get("warn"):
        return ""
    if sg.get("recent"):
        return SEND_GAP_TEXT
    ms = [str(m) for m in (sg.get("months") or []) if re.match(r"^\d{4}-\d{2}$", str(m))]
    if not ms:
        return ""
    lab = "·".join(f"{m[:4]}년 {int(m[5:7])}월" for m in ms[:4]) + (" 등" if len(ms) > 4 else "")
    return f"{lab}에 메일·팀즈 발신 흔적이 없습니다 — " + SEND_GAP_TEXT.split(" — ", 1)[1]


def headline(agg, d1=None):
    """가장 최근 달의 결론 한 줄 — '2026년 10월(18일까지) — 근무 120.5h · 연장 12.0h · 야간 1.5h · 휴일 4.0h · 52시간 넘은 주 0주'.
    d1 = 분석 기간 끝(그 달이 덜 끝났으면 '(N일까지)'). 달 합계가 없으면 ''."""
    ms = agg.get("months") if isinstance(agg, dict) and isinstance(agg.get("months"), dict) else {}
    keys = sorted(k for k in ms if re.match(r"^\d{4}-\d{2}$", str(k)) and isinstance(ms[k], dict))
    if not keys:
        return ""
    mk = keys[-1]
    m = ms[mk]
    lab = _month_lab(mk, d1)
    try:
        n52 = int(m.get("over52_weeks") or 0)
    except (TypeError, ValueError):
        n52 = 0
    return (f"{lab} — 근무 {_h1(m.get('work_h'))} · 연장 {_h1(m.get('ext_h'))} · 야간 {_h1(m.get('night_h'))} · "
            f"휴일 {_h1(m.get('holiday_h'))} · 52시간 넘은 주 {n52}주")


def _month_lab(mk, d1=None, today=None):
    """'YYYY-MM' → '2026년 10월' · today(날짜)가 그 달이면 '이번 달' · 분석 기간 끝(d1)이 그 달 중간이면 뒤에 '(N일까지)'."""
    lab = f"{mk[:4]}년 {int(mk[5:7])}월"
    if today is not None and hasattr(today, "strftime") and today.strftime("%Y-%m") == mk:
        lab = "이번 달"
    try:
        end = date.fromisoformat(str(d1)[:10]) if d1 else None
    except ValueError:
        end = None
    if end is not None and end.strftime("%Y-%m") == mk and (end + timedelta(days=1)).month == end.month:
        lab += f"({end.day}일까지)"
    return lab


def records_text(rc, folder="data\\" + RECORDS_DIR):
    """근태 기록 비교 요약(compare_records — 시각 없음, 그래도 근태에서 나온 값이라 이 PC 의 화면·리포트에서만) → 한 줄.
    기록 칸이 비었으면 CSV 를 넣는 법. LM30(2026-10-19) 요약에 plus_h 가 있으면 +@·근태 시간 중 PC 흔적 없는 시간·태깅을 말한다."""
    rc = rc if isinstance(rc, dict) else {}

    def n(k):
        try:
            return int(rc.get(k) or 0)
        except (TypeError, ValueError):
            return 0
    if not rc.get("present"):
        return (f"근태 기록과 견주려면 ERP에서 내려받은 출퇴근 CSV(열: 날짜,출근,퇴근)를 {folder} 폴더에 넣고 [분석 실행]을 "
                "누르세요 — 날마다 견주어 근태 기록 밖에서 일한 시간(+@)을 셉니다.")
    if "plus_h" in rc:
        ph, ms, gp = _num0(rc.get("plus_h")), _num0(rc.get("missing_h")), _num0(rc.get("gate_plus_h"))
        bits = [f"근태 기록과 견준 +@ {ph:.1f}시간({n('plus_days')}일)" if ph > 0 else "근태 기록과 견준 +@가 없습니다"]
        if ms > 0:
            bits.append(f"근태 시간 중 PC 흔적 없는 시간 {ms:.1f}h(회의·실험 등 — 참고)")
        if n("gate_days"):
            bits.append(f"입실·퇴실로 본 근태 밖 체류 {gp:.1f}h(참고 — 태깅 {n('gate_days')}일)")
        bits.append(f"기록 없는 근무일 {n('no_record_work_days')}일")
    else:
        try:
            un = float(rc.get("unrecorded_h") or 0)
        except (TypeError, ValueError):
            un = 0.0
        bits = [f"근태 기록보다 {un:.1f}시간 더 일했습니다({n('unrecorded_days')}일)" if un > 0
                else "근태 기록에 없는 근무가 없습니다", f"기록 없는 근무일 {n('no_record_work_days')}일"]
    if n("rec_only_days"):
        bits.append(f"근태 기록에만 있는 근무일 {n('rec_only_days')}일(이 PC 흔적 없음)")
    if n("bad_rows"):
        bits.append(f"읽지 못한 행 {n('bad_rows')}개")
    rg = rc.get("range") if isinstance(rc.get("range"), (list, tuple)) and len(rc.get("range")) == 2 else None
    return (" · ".join(bits) + f" — 근태 기록 {n('days')}일 · 파일 {n('files')}개"
            + (f" · {rg[0]}~{rg[1]}" if rg else ""))


# ── LM30(2026-10-19) +@ 보여 주기 — 카드 결론 줄·설명 줄·날짜별 +@ 칸(규칙은 머리말 14) ──
# 얼린 사본·분석리포트(공유폴더로 복사된다)의 '근태 기록 비교' 줄 — 근태에서 나온 값은 싣지 않는다
FROZEN_REC_TEXT = ("근태 기록(GERP 포함)과 견준 값은 본인 PC의 화면·리포트에서만 보입니다 — 이 사본의 +@는 근태 기록 없이 "
                   "추정한 값입니다.")


def _num0(v):
    """숫자 → float · 아니면(None·글자·NaN) 0"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _std(std):
    """표준일(h — mm.standardDayHours) · 없거나 틀리면 8"""
    x = _num0(std)
    return x if x > 0 else 8.0


def plus_note(std=None):
    """+@ 가 무엇인지 한 줄(카드·리포트 공용)"""
    return (f"근태 기록 = 확실히 일한 부분, +@ = 그 밖에서 LM이 찾은 근무입니다(근태를 못 읽으면 하루 {_std(std):g}시간 넘은 "
            "시간·휴일 근무로 추정합니다). 투입 MM은 그대로 LM이 잰 근무시간이고 근태 기록은 참고입니다.")


def est_of(t):
    """합계 칸(주·달·전체) → +@ 추정 h — plus_est_h, 없으면(예전 합계·근태 칸을 뺀 사본) 연장 + 휴일(날마다 연장 + 휴일이라 합도 같다)"""
    if not isinstance(t, dict):
        return 0.0
    if "plus_est_h" in t:
        return _num0(t.get("plus_est_h"))
    return max(0.0, _num0(t.get("ext_h")) + _num0(t.get("holiday_h")))


def plus_of(t, ht=None):
    """합계 칸의 +@ — 근태와 견준 칸(ht — hr_view 의 같은 칸)이 있으면 plus_all_h(근태와 견준 것 + 기록 없는 날의 추정), 없으면 추정"""
    if isinstance(ht, dict) and "plus_all_h" in ht:
        return _num0(ht.get("plus_all_h"))
    return est_of(t)


def plus_line(agg, hr=None, d1=None, today=None, std=None):
    """가장 최근 달의 +@ 결론 한 줄 — '이번 달(16일까지) +@ 12.5시간 — 근태 기록과 견준 것 9.0h · 기록 없이 추정한 것 3.5h ·
    그중 PC 밖 1.0h'. hr(hr_view)가 없으면 '… +@ 3.5시간 — 근태 기록 없이 추정한 것(하루 8시간 넘은 시간·휴일 근무)'.
    agg = 근태 없이 잰 합계(mm_meta) · d1 = 분석 기간 끝 · today 를 주면 그 달은 '이번 달'(화면 — 리포트·사본은 주지 않는다).
    달 합계가 없으면 ''. hr 를 주면 근태에서 나온 값을 담는다(이 PC 의 화면·리포트에서만)."""
    ms = agg.get("months") if isinstance(agg, dict) and isinstance(agg.get("months"), dict) else {}
    keys = sorted(k for k in ms if re.match(r"^\d{4}-\d{2}$", str(k)) and isinstance(ms[k], dict))
    if not keys:
        return ""
    mk = keys[-1]
    lab = _month_lab(mk, d1, today)
    hm_ = ((hr or {}).get("months") or {}).get(mk) if isinstance(hr, dict) else None
    if isinstance(hm_, dict) and "plus_h" in hm_:
        a, b = _num0(hm_.get("plus_h")), est_of(hm_)
        off = _num0(hm_.get("plus_offpc_h")) + _num0(hm_.get("plus_est_offpc_h"))
        s = f"{lab} +@ {a + b:.1f}시간 — 근태 기록과 견준 것 {a:.1f}h · 기록 없이 추정한 것 {b:.1f}h"
    else:
        b = est_of(ms[mk])
        off = _num0(ms[mk].get("plus_est_offpc_h"))
        s = f"{lab} +@ {b:.1f}시간 — 근태 기록 없이 추정한 것(하루 {_std(std):g}시간 넘은 시간·휴일 근무)"
    if off >= 0.05:
        s += f" · 그중 PC 밖 {off:.1f}h"
    return s


def day_plus(r, std=None):
    r"""날짜별 행 → {"h": +@ 시간, "est": 근태 기록 없이 추정했나, "why": 까닭 한 줄(쉬운 말)} — 화면·리포트의 날짜별 표(이 PC 전용 —
    근태 출퇴근 시각을 담는다). 근태와 견준 날(rec 의 plus_h — hr_compare)은 그 값, 아니면 연장 + 휴일 추정(_est).
    예) '근태 퇴근 18:00 뒤 2.0h(그중 PC 밖 0.8h) · 입실·퇴실로 보면 근태 밖 체류 0.5h(참고)' · '근태 기록 없는 근무' ·
        '하루 8시간 넘은 시간 — 근태 기록 없이 추정'"""
    r = r if isinstance(r, dict) else {}
    eps = REC_EPS_H
    rc = r.get("rec") if isinstance(r.get("rec"), dict) else None
    if rc is not None and "plus_h" in rc:
        h = _num0(rc.get("plus_h"))
        kind = str(rc.get("kind") or "")
        if kind == "norow":
            why = "근태 기록 없는 근무" if h > eps else "근태 기록 없음"
        elif kind == "leave":
            why = "휴가인 날 근무" if h > eps else "휴가"
        elif kind == "notimes":
            why = "근태에 출퇴근 시각이 없는 날의 근무" if h > eps else "근태에 출퇴근 시각 없음"
        else:
            bits = []
            e_, l_ = _num0(rc.get("early_h")), _num0(rc.get("late_h"))
            if e_ >= 0.05:
                bits.append(f"근태 출근 {rc.get('in') or ''} 전 {e_:.1f}h")
            if l_ >= 0.05:
                bits.append(f"근태 퇴근 {_clock(rc.get('out'), rc.get('out_day'))} 뒤 {l_:.1f}h")
            why = " · ".join(bits) if bits else "근태 시간 안에서 일함"
        off = _num0(rc.get("plus_offpc_h"))
        if h > eps and off >= 0.05:
            why += f"(그중 PC 밖 {off:.1f}h)"
        more = []
        ms = _num0(rc.get("missing_h"))
        if ms >= 0.05:
            more.append(f"근태 시간 중 PC 흔적 없는 시간 {ms:.1f}h(회의·실험 등 — 참고)")
        gp = _num0(rc.get("gate_plus_h"))
        if gp >= 0.05:
            more.append(f"입실·퇴실로 보면 근태 밖 체류 {gp:.1f}h(참고)")
        return {"h": _r(h), "est": False, "why": " · ".join([why] + more)}
    est, off = _est(r)
    if est <= eps:
        return {"h": 0.0, "est": True, "why": ""}
    lf = _num0(r.get("leave_frac"))
    sd = _std(std)
    if r.get("kind") == "off":
        why = "휴일 근무"
    elif lf >= 1.0:
        why = "휴가일 근무"
    elif lf > 0:
        why = f"반차라 {sd * (1.0 - lf):g}시간 넘은 시간"
    else:
        why = f"하루 {sd:g}시간 넘은 시간"
    why += " — 근태 기록 없이 추정"
    if off >= 0.05:
        why += f"(그중 PC 밖 {off:.1f}h)"
    return {"h": _r(est), "est": True, "why": why}
