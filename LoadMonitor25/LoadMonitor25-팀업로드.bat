@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor25 - 팀 업로드

set "PY_EXE="
set "PY_ARGS="
rem 실행할 파이썬 찾기 - 실행파일(PY_EXE)과 인자(PY_ARGS)를 나눠 둔다.
rem 한 변수에 따옴표째 담으면 for /f 안에서 파싱이 깨져 날짜가 빈 값이 된다(실측).
rem 0) 폴더에 동봉된 내장 파이썬이 최우선 - PC에 Python이 없어도 구동된다
rem    (없으면 tools\Get-EmbeddedPython.ps1 을 한 번 실행해 받아둘 수 있음, 약 11MB)
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
if defined PY_EXE set "PY_CMD=defined"
if not defined PY_CMD (
  echo  [!] 실행 가능한 Python 이 없습니다 - python.org 에서 Python 3.11+ 설치하거나
  echo      설정 ^> 앱 실행 별칭에서 python.exe 별칭을 끄세요.
  pause
  exit /b 1
)

if not exist "teamup.py" (
  echo [!] teamup.py 가 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  pause
  exit /b 1
)
echo.
echo  [팀 업로드] 분석 결과 묶음을 팀 서버로 보냅니다.
echo             분석 때는 자동으로 보내지 않습니다 - 서버에 닿는 망에서 이것을 실행하세요.
echo             닿지 않으면 아무것도 잃지 않고 그대로 대기합니다.
echo.
"%PY_EXE%" %PY_ARGS% teamup.py --list
echo.
echo  [연결 확인] ...
"%PY_EXE%" %PY_ARGS% teamup.py --ping
if errorlevel 1 (
  echo.
  echo  이 망에서는 팀 서버에 닿지 않습니다 - 묶음은 그대로 대기합니다.
  echo  사내망에서 이 파일을 다시 실행하면 밀린 기간까지 한 번에 올라갑니다.
  echo.
  pause
  exit /b 1
)
echo.
"%PY_EXE%" %PY_ARGS% teamup.py --upload
echo.
pause
