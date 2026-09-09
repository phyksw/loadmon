@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor22 - PC 이동 준비
rem 여기서 찍는 글자는 바로 아래 start 뒤 exit 로 이 창이 닫혀 읽히기 전에 사라진다(감사 확정).
rem 안내는 새로 뜨는 '정리 창'이 전부 다시 찍으므로 여기서는 한 줄만 남긴다.
echo.
echo  [PC 이동 준비] 정리 창을 엽니다...
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
start "LoadMonitor22 - PC 이동 준비" powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\LM22-Prepare-Move.ps1" -Root "%LM_ROOT%"
exit
