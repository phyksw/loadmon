@echo off
>nul chcp 949
setlocal
cd /d "%~dp0"
title AgentFinder32 - Agentic AI 전환 과제 발굴

echo.
echo  ==========================================================
echo   AgentFinder32 - Agentic AI 전환 과제 발굴
echo   내 Outlook 메일과 일정에서 Agentic AI 로 바꿀 만한 업무를 찾습니다.
echo   사람을 평가하거나 근태, 업무량을 보는 데 쓰지 않습니다.
echo  ==========================================================
echo.
echo   이 도구는 서면 동의서를 낸 사람만 씁니다. 동의는 서면으로 따로 받으며, 이 도구는 동의를 묻거나 기록하지 않습니다.
echo.

set "PY_EXE="
set "PY_ARGS="
set "RC=1"
rem 실행할 파이썬 찾기 - 실행파일(PY_EXE)과 인자(PY_ARGS)를 나눠 둔다.
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

rem 1) 설치 위치(클라우드, 네트워크와 동기화되는 폴더), 옛 LoadMonitor 프로그램 파일, 설치 폴더 권한(다른 사용자가 열 수 있으면
rem    내 계정 전용으로 바꾼다) - 문제가 있으면 시작하지 않는다
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\install.py --check
if errorlevel 1 (
  set "RC=4"
  goto END
)

rem 2) 옛 LoadMonitor 자료와 보관기한이 지난 자료를 지운다(run.py 도 시작할 때 한 번 더 본다).
rem    끝나지 않은 [모두 지우기]가 있으면 여기서 이어서 지운다 - 다 지웠으면(종료 코드 3) 이번에는 분석하지 않고 끝낸다
rem    (run.py 를 바로 돌릴 때와 같다). 다시 실행하면 새로 시작한다.
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\retention.py --purge
if "%errorlevel%"=="3" goto WIPED

rem 3) 시작 확인 - 이 폴더의 자료가 내 것인지, [모두 지우기]가 끝났는지만 본다. core\consent.py --status 의 종료 코드:
rem    0 쓸 수 있음, 3 지우는 중, 4 다른 사용자의 자료이거나 주인을 모르는 자료. 쓰겠다는 뜻은 여기서 묻지 않는다(서면으로 따로 받는다).
rem    이 단계는 조직장에게 아무것도 보내지 않는다.
:GATE
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\consent.py --status --json >nul
set "CRC=%errorlevel%"
if "%CRC%"=="0" goto PERIOD
if "%CRC%"=="4" goto OTHERUSER
if "%CRC%"=="3" goto WIPING
echo.
echo  [!] 시작 확인을 하지 못했습니다 - 이 폴더에 쓸 수 있는지, 설치 파일이 빠지지 않았는지 확인하고 다시 실행하세요.
set "RC=1"
goto END

:WIPED
echo.
echo  [!] 자료를 모두 지웠습니다 - 이번에는 분석하지 않습니다. 다시 시작하면 새로 시작합니다.
set "RC=3"
goto END

:WIPING
echo.
echo  [!] 자료를 지우는 중입니다 - 다 지운 뒤 다시 시작할 수 있습니다.
echo      [모두 지우기]가 끝나지 않았습니다. 지우지 못한 파일을 연 프로그램을 닫고 다시 실행하면 마저 지웁니다.
set "RC=3"
goto END

:OTHERUSER
echo.
echo  [!] 다른 사용자의 자료입니다 - 열지 않고 지웁니다.
echo      이 폴더의 data, report 자료는 다른 Windows 사용자가 만들었거나, 설치 정보가 없어 주인을 확인할 수 없습니다.
echo      지울 때 이 자료로 조직장 서버에 공유한 사본이 있으면 그 서버에서 먼저 지웁니다.
set "DEL="
set /p DEL=  지금 지우고 새로 시작하려면 Y 를 입력하세요 [y/N] :
if /i not "%DEL%"=="y" (
  set "RC=4"
  goto END
)
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\retention.py --purge-all
if errorlevel 1 (
  echo  [!] 지우지 못한 것이 있습니다 - 위 [지우기] 줄의 까닭을 확인하고 다시 실행하세요.
  set "RC=4"
  goto END
)
echo  지웠습니다. 새로 시작합니다.
goto GATE

rem 4) 분석 기간 - core\period.py 가 정한다(끝은 늘 어제, 최대 92일)
:PERIOD
echo.
echo   분석 기간을 고르세요. 끝은 늘 어제입니다 - 오늘은 넣지 않습니다.
echo.
echo     1. 최근 1개월 - 30일
echo     2. 최근 3개월 - 92일   [기본]
echo.
set "SEL="
set /p SEL=  번호 :
set "MONTHS=3"
if "%SEL%"=="1" set "MONTHS=1"
set "FROM="
set "TO="
rem 날짜는 임시 파일로 받는다 - for /f 안에서 따옴표 붙은 실행 파일 경로를 쓰면 파싱이 깨져 날짜가 빈 값이 된다(실측).
rem 임시 파일 이름은 af32_ 접두 - 같은 PC 의 다른 판 bat 과 동시에 돌려도 서로 덮어쓰지 않는다.
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\period.py --months %MONTHS% > "%TEMP%\af32_period.txt"
for /f "usebackq tokens=1,2" %%a in ("%TEMP%\af32_period.txt") do (
  set "FROM=%%a"
  set "TO=%%b"
)
del "%TEMP%\af32_period.txt" >nul 2>&1
if not defined TO (
  echo  [!] 기간을 정하지 못했습니다 - config\config.json 의 period 설정을 확인하세요.
  goto END
)

echo.
set "USEAI="
set /p USEAI=  회사 M365 Copilot 으로 업무 분류와 Agentic AI 후보까지 만들까요 [Y/n] :
set "AIFLAG=--ai"
if /i "%USEAI%"=="n" set "AIFLAG="

set "SKIP="
set /p SKIP=  이미 모은 메일, 일정으로 다시 분석만 할까요 [y/N] :
set "SKIPFLAG="
if /i "%SKIP%"=="y" set "SKIPFLAG=--skip-collect"

echo.
echo  ----------------------------------------------------------
echo   기간 %FROM% ~ %TO%   %AIFLAG% %SKIPFLAG%
echo  ----------------------------------------------------------
echo.

"%PY_EXE%" %PY_ARGS% run.py --from %FROM% --to %TO% %AIFLAG% %SKIPFLAG%
set "RC=%errorlevel%"
set "TAG=%FROM:-=%-%TO:-=%"

echo.
if "%RC%"=="0" goto DONE
if "%RC%"=="2" goto PARTIAL
if "%RC%"=="3" goto WIPING_RUN
if "%RC%"=="4" goto REFUSED
goto FAIL

:DONE
echo  [완료] 개인 리포트는 report 폴더에 있습니다 - 이 PC 안에서만 봅니다.
goto OPEN

:PARTIAL
echo  [일부만] 위 메시지를 확인하세요.
echo      - Outlook 웹, Copilot 은 전용 Edge 창에서 회사 계정으로 한 번 로그인해야 합니다.
echo      - AI 단계가 일부만 끝났으면 다시 실행할 때 남은 것만 이어서 합니다.
echo      - 위 안내의 [다시 읽지 않고 분석만], [분석 실행]은 AgentFinder32-UI.bat 화면의 이름입니다.
echo        이 창에서는 다시 실행해 "다시 분석만 할까요" 에 y 를 입력합니다.
goto OPEN

:OPEN
echo  공유는 AgentFinder32-UI.bat 화면의 [공유] 탭에서 본인이 고를 때만 합니다.
echo  이 실행은 조직장에게 아무것도 보내지 않았습니다(AI 분석은 회사 M365 Copilot 을 씁니다).
if not exist "report\개인리포트_%TAG%.html" goto END
echo.
set "OPENIT="
set /p OPENIT=  개인 리포트를 열까요 [Y/n] :
if /i not "%OPENIT%"=="n" start "" "report\개인리포트_%TAG%.html"
goto END

:WIPING_RUN
echo  [!] 자료를 지우는 중이라 분석하지 않았습니다 - 위 [!] 줄을 확인하고 다시 실행하세요.
goto END

:REFUSED
echo  [!] 시작 조건이 맞지 않아 분석하지 않았습니다 - 위 [!] 줄의 안내대로 고친 뒤 다시 실행하세요.
goto END

:FAIL
echo  [!] 실행 중 문제가 있었습니다. 위 메시지를 확인하세요.
echo      - Outlook 앱 수집은 클래식 Outlook 이 켜져 있어야 합니다.
echo      - Outlook 웹, Copilot 은 전용 Edge 창에서 회사 계정으로 한 번 로그인해야 합니다.
echo      - 위 안내의 [다시 읽지 않고 분석만], [분석 실행]은 AgentFinder32-UI.bat 화면의 이름입니다.
echo        이 창에서는 다시 실행해 "다시 분석만 할까요" 에 y 를 입력합니다.

:END
echo.
pause
endlocal & exit /b %RC%
