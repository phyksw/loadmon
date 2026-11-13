@echo off
>nul chcp 949
cd /d "%~dp0"
title AgentFinder32 UI

rem 실행할 파이썬 찾기: python 이 실제로 실행되면 그것, 아니면 py 런처(-3) 폴백
rem (Microsoft Store 별칭은 where 를 통과해도 실행하면 Store 만 열리고 아무 일도 안 생긴다)
set "PY_EXE="
set "PY_ARGS="
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
  echo.
  echo  ==========================================================
  echo   [!] 실행 가능한 Python 이 없습니다
  echo  ==========================================================
  echo.
  echo   python 명령이 없거나 Microsoft Store 별칭^(실행해도 Store만 열림^)입니다.
  echo   해결: python.org 에서 Python 3.11+ 설치 ^("Add to PATH" 체크^) 하거나
  echo         설정 ^> 앱 ^> 고급 앱 설정 ^> 앱 실행 별칭에서 python.exe 별칭을 끄세요.
  echo.
  pause
  exit /b 1
)

if not exist "ui\app.py" goto MISSING
if not exist "run.py" goto MISSING
if not exist "core\consent.py" goto MISSING
if not exist "core\privacy.py" goto MISSING
if not exist "core\progress.py" goto MISSING

rem 설치 위치(클라우드, 네트워크와 동기화되는 폴더), 옛 LoadMonitor 프로그램 파일, 설치 폴더 권한(다른 사용자가 열 수 있으면
rem 내 계정 전용으로 바꾼다) - 문제가 있으면 화면을 열지 않는다
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\install.py --check
if errorlevel 1 (
  echo.
  pause
  exit /b 4
)

echo.
echo   AgentFinder32 화면을 시작합니다. 브라우저가 자동으로 열립니다.
echo   이 도구는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다.
echo   결과는 이 PC 에 남고, 공유는 [공유] 탭에서 고를 때만 보냅니다.
echo   화면 창이나 이 창을 닫으면 실행 중인 작업도 함께 멈추고 끝납니다 ^(Ctrl+C 도 종료^).
echo   그래도 남은 것 같으면 AgentFinder32-강제종료.bat
echo.
"%PY_EXE%" %PY_ARGS% ui\app.py
rem 정상 종료(화면 창을 닫아 자동으로 끝남, [서버 종료], Ctrl+C)면 이 창도 바로 닫는다 - 멈춰 있는 창이 남으면
rem "아직 도는 중" 으로 읽힌다. 오류로 끝났을 때만 원인을 보여 주고 기다린다.
if errorlevel 1 (
  echo.
  echo  [!] 화면 서버가 오류로 종료됐습니다.
  if exist "ui_error.log" echo      원인이 ui_error.log 에 저장돼 있습니다 - 이 파일을 운영 담당에게 알려 주세요.
  echo.
  pause
  exit /b 1
)
exit /b 0

:MISSING
echo.
echo  ==========================================================
echo   [!] 파일이 빠졌습니다 - 복사가 불완전합니다
echo  ==========================================================
echo.
echo   현재 폴더: %CD%
echo.
echo   받은 AgentFinder32 압축 파일을 새 폴더에 다시 푸세요.
echo   ^(data, report 폴더는 옮기지 마세요 - 개인 자료입니다^)
echo.
echo   전체 목록은 FILES.txt, 누락 확인은  python 자가점검.py
echo.
pause
exit /b 1
