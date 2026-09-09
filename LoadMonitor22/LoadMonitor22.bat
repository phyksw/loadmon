@echo off
>nul chcp 949
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title LoadMonitor22 - 업무 로드 MM 추출

echo.
echo  ==========================================================
echo   LoadMonitor22 - 개인 PC 흔적에서 업무 로드 MM 추출
echo  ==========================================================
echo.

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

echo   분석 기간을 고르세요.
echo.
echo     1. 최근 1개월
echo     2. 최근 3개월   [기본]
echo     3. 최근 6개월
echo     4. 직접 입력
echo.
set "SEL="
set /p SEL=  번호 :
if "%SEL%"=="" set "SEL=2"

set "DAYS=90"
if "%SEL%"=="1" set "DAYS=30"
if "%SEL%"=="3" set "DAYS=180"

set "FROM="
set "TO="
if "%SEL%"=="4" goto ASKDATE

"%PY_EXE%" %PY_ARGS% -c "import datetime,sys;print((datetime.date.today()-datetime.timedelta(days=int(sys.argv[1]))).isoformat())" %DAYS% > "%TEMP%\lm_from.txt"
set /p FROM=<"%TEMP%\lm_from.txt"
"%PY_EXE%" %PY_ARGS% -c "import datetime;print(datetime.date.today().isoformat())" > "%TEMP%\lm_to.txt"
set /p TO=<"%TEMP%\lm_to.txt"
goto ASKAI

:ASKDATE
set /p FROM=  시작일 YYYY-MM-DD :
set /p TO=  종료일 YYYY-MM-DD :

:ASKAI
echo.
set "USEAI="
set /p USEAI=  Copilot AI 판정까지 할까요 (raw를 직접 읽음) [Y/n] :
set "AIFLAG=--ai"
if /i "%USEAI%"=="n" set "AIFLAG="

set "SKIP="
set /p SKIP=  이미 수집한 데이터로 재분석만 [y/N] :
set "SKIPFLAG="
if /i "%SKIP%"=="y" set "SKIPFLAG=--skip-collect"

echo.
echo  ----------------------------------------------------------
echo   기간 %FROM% ~ %TO%   %AIFLAG% %SKIPFLAG%
echo  ----------------------------------------------------------
echo.

"%PY_EXE%" %PY_ARGS% run.py --from %FROM% --to %TO% %AIFLAG% %SKIPFLAG%
set "RC=%errorlevel%"

echo.
if not "%RC%"=="0" goto FAIL

echo  [완료] 결과는 report 폴더에 있습니다.
echo         mm_rows_*_refined.csv  = 최종 업무 행
echo         evidence_*.md          = 각 행의 원문 근거
echo.
set "OPENIT="
set /p OPENIT=  결과 폴더를 열까요 [Y/n] :
if /i not "%OPENIT%"=="n" start "" "%~dp0report"
goto END

:FAIL
echo  [!] 실행 중 문제가 있었습니다. 위 메시지를 확인하세요.
echo      - 신호 0건이면 config\config.json 의 watchFolders 를 실제 작업 폴더로 바꾸세요.
echo      - Outlook 수집은 클래식 Outlook 이 켜져 있어야 합니다.

:END
echo.
pause
endlocal
