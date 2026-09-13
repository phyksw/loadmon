@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor24 - PC 가동시간 비교
echo.
echo  [PC 가동시간 비교] 이 PC 에서 LM20 수집기와 현재 수집기를 같은 기간으로 나란히 돌려
echo                     달별 PC 가동시간을 비교합니다 (1~3분).
echo    - 실제 data 폴더는 읽기만 합니다. 두 수집기는 임시 폴더에서 돌고 끝나면 지웁니다.
echo    - 결과: report\pc_hours_compare.txt  (날짜별 시간과 건수만 - URL·제목·내용 없음)
echo.
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
if not defined PY_EXE (
  echo  [!] 실행 가능한 Python 이 없습니다.
  pause
  exit /b 1
)
"%PY_EXE%" %PY_ARGS% "tools\pc_hours_compare.py" %*
rem PowerShell 자식이 코드페이지를 65001 로 바꿔 놓고 나갈 수 있다 - pause 안내가 깨지지 않게 되돌린다
>nul chcp 949
echo.
pause
