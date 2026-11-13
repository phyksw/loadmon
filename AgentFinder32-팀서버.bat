@echo off
>nul chcp 949
cd /d "%~dp0"
title AgentFinder32 - 조직장 팀 서버

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
  echo  [!] teamserver.py 가 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  pause
  exit /b 1
)

:MENU
echo.
echo  [조직장 팀 서버] 팀원이 [공유] 탭에서 직접 골라 보낸 것만 받습니다 - 자동으로 오는 자료는 없습니다.
echo     받는 것: 조직장만 여는 개인 리포트, 이름 없는 익명 팀 집계 기여분.
echo     공유하지 않아도 팀원에게 불이익이 없고, 조직장은 공유를 요구하거나 권하지 않습니다.
echo     조직장 화면은 이 PC 의 브라우저에서만 열립니다 - 서버를 켜면 주소가 찍힙니다.
echo     팀원에게는 teamdata\접속정보.txt 의 주소와 참여 코드만 알려 주세요.
echo.
echo     1  서버 시작
echo     2  조직장 키 다시 만들기
echo     3  참여 코드 바꾸기
echo     4  서버 자료 모두 삭제
echo     Q  끝내기
echo.
choice /c 1234Q /n /m "  번호를 고르세요 [1, 2, 3, 4, Q] : "
if errorlevel 5 goto END
if errorlevel 4 goto DELALL
if errorlevel 3 goto NEWJOIN
if errorlevel 2 goto NEWKEY
if errorlevel 1 goto START
goto END

:START
echo.
echo  서버를 켭니다. 처음이면 조직 이름과 HTTP 로 개인 리포트를 받을지 묻고, 조직장 키를 한 번만 보여 줍니다.
echo  끄려면 이 창에서 Ctrl+C 를 누르세요.
echo.
"%PY_EXE%" %PY_ARGS% teamserver.py
echo.
pause
goto MENU

:NEWKEY
echo.
"%PY_EXE%" %PY_ARGS% teamserver.py --new-key
echo.
pause
goto MENU

:NEWJOIN
echo.
"%PY_EXE%" %PY_ARGS% teamserver.py --new-join
echo.
pause
goto MENU

:DELALL
echo.
"%PY_EXE%" %PY_ARGS% teamserver.py --delete-all
echo.
pause
goto MENU

:END
exit /b 0
