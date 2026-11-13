@echo off
>nul chcp 949
cd /d "%~dp0"
title AgentFinder32 - 조직장 팀 서버 주소

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
echo  [조직장 팀 서버 주소] 조직장이 알려 준 주소와 참여 코드를 저장합니다 - 설치 폴더의 config\af32_team_server.json
echo     저장만 합니다. 공유는 화면 [공유] 탭에서 내가 미리 보고 고를 때만 보냅니다.
echo     화면은 주소를 보여 주기만 합니다 - 바꾸는 곳은 이 파일 하나입니다.
echo.
"%PY_EXE%" %PY_ARGS% core\teamaddr.py --show
echo.
echo  바꿀 값만 입력하고, 그대로 둘 값은 Enter 만 누르세요.
echo  주소 칸에는 접속정보의 주소를 그대로 붙여 넣어도 됩니다(예: http://10.0.0.5:포트 - https 면 https://).
rem 입력값은 명령줄에 끼워 넣지 않고 환경변수로만 넘긴다 - 특수문자가 섞여도 명령으로 해석되지 않게.
rem 이름은 AF32_TA_* (core\teamaddr.py --set-env 가 읽는 이름과 같다)
set "AF32_TA_HOST="
set "AF32_TA_PORT="
set "AF32_TA_JOIN="
set /p "AF32_TA_HOST=  서버 주소 (IP 또는 PC 이름)  : "
set /p "AF32_TA_PORT=  포트                         : "
set /p "AF32_TA_JOIN=  참여 코드 (XXXX-XXXX-XXXX)    : "
echo.
"%PY_EXE%" %PY_ARGS% core\teamaddr.py --set-env
if errorlevel 1 (
  set "AF32_TA_JOIN="
  echo.
  echo  [주의] 저장하지 않았습니다 - 위 사유를 확인하고 다시 실행하세요.
  echo.
  pause
  exit /b 1
)
set "AF32_TA_JOIN="
echo.
rem 저장만으로는 조직장 서버에 붙지 않는다 - 연결 확인은 y 를 입력했을 때만(Enter 는 하지 않음). 확인은 서버의 인사만 받는다.
set "TA_PING="
set /p "TA_PING=  지금 조직장 서버에 연결해 볼까요 - 연결 확인만 하고 자료는 보내지 않습니다 [y/N] : "
rem 입력값 비교는 지연 확장으로만 한다 - 따옴표·앰퍼샌드가 섞여도 if 줄이 깨지지 않게.
setlocal EnableDelayedExpansion
if /i not "!TA_PING!"=="y" (
  endlocal
  goto END
)
endlocal
echo.
echo  조직장 서버에 연결해 봅니다.
"%PY_EXE%" %PY_ARGS% teamup.py --ping
if errorlevel 1 (
  echo.
  echo  지금은 닿지 않습니다 - 주소는 저장됐습니다. 사내망에서 다시 확인하세요.
)
:END
echo.
pause
exit /b 0
