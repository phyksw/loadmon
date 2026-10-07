@echo off
>nul chcp 949
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title LoadMonitor28 - 업무 로드 MM 추출

echo.
echo  ==========================================================
echo   LoadMonitor28 - 개인 PC 흔적에서 업무 로드 MM 추출
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

echo   분석 기간을 고르세요. 기본은 대시보드와 같은 '올해' 입니다 - 팀 취합은 같은 기간이어야 맞습니다.
echo.
echo     1. 올해 (1월 1일부터 오늘까지)   [기본]
echo     2. 최근 1개월
echo     3. 최근 3개월
echo     4. 최근 6개월
echo     5. 직접 입력
echo     6. 1분기   7. 2분기   8. 3분기   9. 4분기   (올해 - 진행 중이면 끝은 오늘)
echo    10. 상반기 11. 하반기
echo.
set "SEL="
set /p SEL=  번호 :
if "%SEL%"=="" set "SEL=1"

rem DAYS=ytd 는 올해 1월 1일부터. 예전 기본(최근 3개월)은 화면 기본(올해)과 달라, bat 으로 한 번 돌리면
rem 짧은 기간 결과가 화면을 차지해 "1월부터 보던 추이가 사라졌다" 로 읽혔다(실측).
rem 분기·반기는 대시보드 기간 칩과 같은 규칙(ui\app.py quarter_range) - 끝이 미래면 오늘로 자르고,
rem 아직 시작하지 않은 기간은 고를 수 없다.
set "DAYS=ytd"
if "%SEL%"=="2" set "DAYS=30"
if "%SEL%"=="3" set "DAYS=90"
if "%SEL%"=="4" set "DAYS=180"
if "%SEL%"=="6" set "DAYS=q1"
if "%SEL%"=="7" set "DAYS=q2"
if "%SEL%"=="8" set "DAYS=q3"
if "%SEL%"=="9" set "DAYS=q4"
if "%SEL%"=="10" set "DAYS=h1"
if "%SEL%"=="11" set "DAYS=h2"

set "FROM="
set "TO="
if "%SEL%"=="5" goto ASKDATE

rem 날짜 계산은 파이썬 1회 - 시작·끝을 한 번에 두 파일로 쓴다(예전에는 2회 실행. 프로세스를 아낀다).
rem 임시 파일 이름은 lm28_ 접두 - 같은 PC 의 LM24 bat 과 동시에 돌려도 서로 덮어쓰지 않는다
"%PY_EXE%" %PY_ARGS% -c "import datetime as D,sys;t=D.date.today();k=sys.argv[1];y=t.year;S={'q1':(1,1,3,31),'q2':(4,1,6,30),'q3':(7,1,9,30),'q4':(10,1,12,31),'h1':(1,1,6,30),'h2':(7,1,12,31)};a,b=((D.date(y,S[k][0],S[k][1]),D.date(y,S[k][2],S[k][3])) if k in S else ((D.date(y,1,1) if k=='ytd' else t-D.timedelta(days=int(k))),t));b=min(b,t);ok=a<=t;open(sys.argv[2],'w').write(a.isoformat() if ok else '');open(sys.argv[3],'w').write(b.isoformat() if ok else '')" %DAYS% "%TEMP%\lm28_from.txt" "%TEMP%\lm28_to.txt"
set /p FROM=<"%TEMP%\lm28_from.txt"
set /p TO=<"%TEMP%\lm28_to.txt"
del "%TEMP%\lm28_from.txt" "%TEMP%\lm28_to.txt" >nul 2>&1
if not defined FROM (
  echo  [!] 아직 시작하지 않은 기간입니다 - 다른 번호를 고르세요.
  goto END
)
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
