@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor28 - 팀 서버 주소 설정

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

if not exist "core\teamaddr.py" (
  echo  [!] core\teamaddr.py 가 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  pause
  exit /b 1
)
echo.
echo  [팀 서버 주소] 팀 서버의 IP 와 포트를 따로 저장합니다 - 설치 폴더의 config\team_server.json
echo     팀원 PC    : 분석 후 이 주소로 올립니다 - 대시보드 [팀 서버 업로드] 또는 LoadMonitor28-팀업로드.bat
echo     팀 서버 PC : 이 포트로 팀 서버가 열리고, 이 IP 로 들어온 결과를 모아 취합합니다.
echo     이 폴더를 통째로 옮기거나 팀원에게 나눠 주면 바꾼 주소가 그대로 따라갑니다.
echo     대시보드는 주소를 보여 주기만 합니다 - 바꾸는 곳은 이 파일 하나입니다.
echo.
"%PY_EXE%" %PY_ARGS% core\teamaddr.py --show
echo.
echo  바꿀 값만 입력하고, 그대로 둘 값은 Enter 만 누르세요.
rem 입력값은 명령줄에 끼워 넣지 않고 환경변수로만 넘긴다 - 특수문자가 섞여도 명령으로 해석되지 않게.
rem 이름은 LM28_TA_* (core\teamaddr.py --set-env 가 읽는 이름과 같다)
set "LM28_TA_HOST="
set "LM28_TA_PORT="
set /p "LM28_TA_HOST=  새 서버 IP (예: 10.0.0.5) : "
set /p "LM28_TA_PORT=  새 포트 (1~65535)        : "
echo.
"%PY_EXE%" %PY_ARGS% core\teamaddr.py --set-env
if errorlevel 1 (
  echo.
  echo  [주의] 저장하지 않았습니다 - 위 사유를 확인하고 다시 실행하세요.
  echo.
  pause
  exit /b 1
)
echo.
echo  이 PC 에서 팀 서버가 켜져 있었다면 [중지] 후 다시 시작해야 새 포트로 열립니다.
set "TA_PING="
set /p "TA_PING=  지금 이 망에서 팀 서버에 닿는지 확인할까요 [Y/n] : "
rem 입력값 비교는 지연 확장으로만 한다 - 따옴표·앰퍼샌드가 섞여도 if 줄이 깨지지 않게.
setlocal EnableDelayedExpansion
if /i "!TA_PING!"=="n" (
  endlocal
  goto END
)
endlocal
echo.
"%PY_EXE%" %PY_ARGS% teamup.py --ping
if errorlevel 1 (
  echo.
  echo  이 망에서는 닿지 않습니다 - 주소는 저장됐습니다. 서버에 닿는 망에서 다시 확인하세요.
)
:END
echo.
pause
exit /b 0
