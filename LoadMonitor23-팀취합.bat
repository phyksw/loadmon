@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor23 - 팀 취합 뷰어

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

if not exist "ui\app.py" goto MISSING
if not exist "aggregate.py" goto MISSING

echo.
echo   팀 취합 뷰어를 시작합니다. 브라우저가 자동으로 열립니다.
echo   - 공유폴더(config.teamShareDir)의 인별 결과를 실시간으로 시각화
echo   - [Copilot으로 유사 항목 정리] : 갈라진 표기를 통합 (되돌리기 가능)
echo   - [팀 통합 보고서 열기] [v3] [스냅샷 저장] : team_full_report.html (v2) / _v3.html - 업로드마다 자동 갱신
echo   - [정적 리포트 다시 만들기] : team_report.html / team_agentic.html / 통합 보고서 다시 생성
echo   창을 닫거나 Ctrl+C 를 누르면 종료됩니다.
echo.
"%PY_EXE%" %PY_ARGS% ui\app.py --team
if errorlevel 1 (
  echo.
  echo  [!] 서버가 오류로 종료됐습니다.
  if exist "ui_error.log" echo      원인이 ui_error.log 에 저장돼 있습니다 - 이 파일을 공유해 주세요.
  echo.
)
pause
exit /b 0

:MISSING
echo.
echo  [!] 파일이 빠졌습니다 - LoadMonitor23 폴더를 통째로 다시 복사하세요.
echo      ^(data, report 폴더는 빼고 - 개인정보^)
pause
exit /b 1
