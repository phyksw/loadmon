@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor22 - PC 이동 준비
echo.
echo  [PC 이동 준비] 이 폴더를 다른 PC 로 옮길 수 있게 정리합니다.
echo.
echo   - 대시보드, 팀 서버, Copilot 전용 Edge, 상시 샘플러를 종료합니다
echo   - 그런 다음 폴더를 옮길 수 있는지 실제로 확인합니다
echo   - 수집한 데이터와 분석 결과는 그대로 둡니다 (지우지 않습니다)
echo.
if not exist "tools\Prepare-Move.ps1" (
  echo  [!] tools\Prepare-Move.ps1 이 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  pause
  exit /b 1
)
rem 이 창(cmd)이 폴더를 잡고 있으면 이동 확인이 항상 실패한다 - TEMP 로 복사해 새 창에서 실행하고 즉시 종료
copy /y "tools\Prepare-Move.ps1" "%TEMP%\LM22-Prepare-Move.ps1" >nul
rem 폴더 경로는 끝 역슬래시를 뗀 정규 경로로 넘긴다. 예전의 -Root "%%~dp0." 는 "...\LoadMonitor22\." 로 들어가
rem 이름 바꾸기 시험이 폴더를 _이동확인_임시 로 바꿔 놓고 되돌리지 못했다(실측). 끝 역슬래시는 닫는 따옴표를 삼키므로 잘라 낸다.
set "LM_ROOT=%~dp0"
set "LM_ROOT=%LM_ROOT:~0,-1%"
rem 새 창은 이 폴더 밖(TEMP)에서 띄운다 - cd /d "%%~dp0" 상태로 start 하면 powershell 이 이 폴더를 cwd 로 물려받아
rem 자기 자신이 폴더를 잡은 채 "다른 프로세스가 사용 중" 으로 이동 확인이 항상 실패했다(실측).
cd /d "%TEMP%"
start "" powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\LM22-Prepare-Move.ps1" -Root "%LM_ROOT%"
exit
