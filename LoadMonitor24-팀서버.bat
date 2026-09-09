@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor24 - 팀 서버

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

if not exist "teamserver.py" (
  echo [!] teamserver.py 가 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  pause
  exit /b 1
)
echo.
echo  [팀 서버] 이 PC 를 팀 취합 서버로 가동합니다 (포트: config.teamServerUrl 의 번호, 기본 9310).
echo           팀원들은 config.teamServerUrl 에 이 PC 주소를 넣고, 서버에 닿는 망에서
echo           대시보드 [팀 서버 업로드] (또는 LoadMonitor24-팀업로드.bat) 로 올립니다.
echo           브라우저 접속: http://이PC의IP:포트번호  (실제 번호는 아래 [team] 가동 줄에 찍힙니다)
echo           팀 통합 보고서: /full  (인별 로드율 제외 v3: /full_v3)
echo.
"%PY_EXE%" %PY_ARGS% teamserver.py
pause
