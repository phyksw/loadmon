@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor24 - 팀 로드율 재계산 (판 무관)

rem 팀취합본(인별 폴더의 signals_*.csv + mm_meta_*.json)만으로 모든 인원의 로드율을 하나의 산식·달력으로 다시 잰다.
rem  - LM20 과 LM24 가 섞인 팀 폴더도 그대로 (판은 파일 키로 자동 판별)
rem  - 기존 team_report.html 등은 건드리지 않고 팀로드율_재계산_<시각>.html + CSV 2개를 새로 만든다
rem  - 이 bat 과 team_recalc.py 두 파일을 팀 폴더(인별 폴더가 있는 곳 / teamdata)에 붙여 넣고 실행하면 된다.
rem    LoadMonitor24 설치 폴더에서 실행하면 teamdata\ 또는 config.teamShareDir 를 자동으로 찾는다.
rem    인자로 팀 폴더를 줄 수도 있다(끝의 \ 는 빼고):  LoadMonitor24-팀로드율재계산.bat "\서버\팀공유\LoadMonitor"
rem    지정한 폴더가 없거나 인별 폴더가 없으면 실패한다 - 다른 폴더로 조용히 바꾸지 않는다.

set "PY_EXE="
set "PY_ARGS="
rem 실행할 파이썬 찾기 - 동봉 파이썬(이 폴더 또는 상위 폴더) → PATH python → py -3
if exist "%~dp0python\python.exe" set "PY_EXE=%~dp0python\python.exe"
if not defined PY_EXE if exist "%~dp0..\python\python.exe" set "PY_EXE=%~dp0..\python\python.exe"
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
if not defined PY_EXE (
  echo  [!] 실행 가능한 Python 이 없습니다 - python.org 에서 Python 3.11+ 설치하거나
  echo      LoadMonitor24 폴더의 python\ 을 이 폴더에 함께 복사하세요.
  pause
  exit /b 1
)

if not exist "%~dp0team_recalc.py" (
  echo  [!] team_recalc.py 가 이 폴더에 없습니다 - bat 과 같은 폴더에 두세요.
  pause
  exit /b 1
)

echo.
echo   팀취합본만으로 로드율을 다시 계산합니다 (LM20 / LM24 판 무관, 기존 보고서는 그대로).
echo.
"%PY_EXE%" %PY_ARGS% "%~dp0team_recalc.py" %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo  [!] 재계산이 완료되지 않았습니다 - 위 메시지를 확인하세요.
  echo      팀 폴더를 못 찾으면 인자로 주세요:  %~nx0 "팀 폴더 경로"   ^(경로 끝의 \ 는 빼세요^)
)
echo.
pause
exit /b %RC%
