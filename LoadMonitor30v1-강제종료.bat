@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor30v1 - 강제 종료
rem 이 폴더의 LM30v1 작업(대시보드·분석·수집기·전용 Edge·그 콘솔 창)을 묻지 않고 모두 끝낸다 - tools\Stop-LM30v1.ps1.
rem 창을 닫았는데 뒤에서 계속 도는 것 같을 때 쓰는 비상 단추다. 일반 Edge·다른 폴더(LM24 등)·팀 서버는 건드리지 않는다.
rem 팀 서버까지 끄려면 명령 창에서  LoadMonitor30v1-강제종료.bat -IncludeTeamServer  · 목록만 보려면  -Status
rem 관리자 권한·임시 파일·예약 작업 없음.
if not exist "tools\Stop-LM30v1.ps1" (
  echo.
  echo  [!] tools\Stop-LM30v1.ps1 이 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  echo.
  pause
  exit /b 1
)
rem 파이썬이 있으면 tools\stop_lm30v1.py 를 거쳐 띄운다 - 2026-10-15 실측: PowerShell 이 켜지는 순간 0xc0000142 로 실패해
rem 오류 창만 남고 아무것도 끝내지 못했다. 이 길은 오류 창 없이 3초·8초 뒤 두 번 다시 띄우고, 그래도 안 되면 파이썬이
rem 같은 규칙대로 직접 끝낸다(이 파이썬과 이 창은 끝내지 않는다). 파이썬이 없으면 예전처럼 PowerShell 을 바로 띄운다.
set "PY_EXE="
set "PY_ARGS="
if exist "%~dp0python\python.exe" set "PY_EXE=%~dp0python\python.exe"
if not defined PY_EXE (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE (
  py -3 --version >nul 2>&1
  if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
  )
)
if defined PY_EXE if exist "tools\stop_lm30v1.py" goto VIA_PY
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Stop-LM30v1.ps1" %*
set "RC=%errorlevel%"
goto DONE
:VIA_PY
"%PY_EXE%" %PY_ARGS% -X utf8 -B "%~dp0tools\stop_lm30v1.py" %*
set "RC=%errorlevel%"
:DONE
echo.
pause
exit /b %RC%
