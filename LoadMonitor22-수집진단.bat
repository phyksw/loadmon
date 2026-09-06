@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor22 - 수집 진단
echo.
echo  [수집 진단] 이 PC 의 Outlook·Teams 버전/상태에서 무엇이 막혔는지 확인합니다 (최대 2분).
echo            결과: report\collect_diag.txt  (채팅·메일 내용은 마스킹 - [판정]대로 이 PC 안에서 조치, 밖으로 보낼 필요 없음)
echo            Outlook 은 '붙기'만 시도하므로 설정 마법사가 뜨거나 멈추지 않습니다.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "collect\Diagnose-Collectors.ps1"
echo.
pause
