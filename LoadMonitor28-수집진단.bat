@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor28 - 수집 진단
echo.
echo  [수집 진단] 이 PC 의 Outlook·Teams 버전/상태에서 무엇이 막혔는지 확인합니다 (최대 2분).
echo            결과: report\collect_diag.txt  (채팅·메일 내용은 마스킹 - [판정]대로 이 PC 안에서 조치, 막히면 아래 진단 묶음 파일을 보내 주세요)
echo            Outlook 은 '붙기'만 시도하므로 설정 마법사가 뜨거나 멈추지 않습니다.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "collect\Diagnose-Collectors.ps1"
rem PowerShell 이 [Console]::OutputEncoding 을 UTF-8 로 바꾸면서 이 창의 코드페이지까지 65001 로 바꿔 놓고 나간다
rem (실측: SetConsoleOutputCP(65001) 까지 수행). 그대로 두면 이 뒤에 cmd 가 찍는 한글(pause 안내문 포함)이
rem cp949 바이트로 나가는데 화면은 UTF-8 로 읽어 전부 깨진다 - 깨진 글자는 그 자체로 "오류가 났다" 로 읽힌다.
>nul chcp 949
echo.
echo  [진단 묶음] 실행 기록·날짜별 원장·출처별 상태·월별 건수를 바탕화면 파일 하나로 모읍니다(제목·이름·주소 없음).
set "PY_EXE="
if exist "%~dp0python\python.exe" set "PY_EXE=%~dp0python\python.exe"
if not defined PY_EXE set "PY_EXE=python"
"%PY_EXE%" -X utf8 -B tools\diag_bundle.py
>nul chcp 949
echo.
pause
