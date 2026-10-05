@echo off
>nul chcp 949
setlocal
title LoadMonitor27 - 팀 서버
rem 팀 서버: team-server [--host H] [--port N] [--store DIR] - 인자는 그대로 넘긴다(계약 7.2).
rem 팀 서버 저장소는 옮기지 않는 별도 폴더가 기본이다. 이 창을 닫으면 서버가 멈춘다.
rem 작업 폴더를 TEMP 로 옮겨 이 폴더를 잡지 않는다(TAB 1.9).
set "LM27_ROOT=%~dp0"
set "LM27_ROOT=%LM27_ROOT:~0,-1%"
set "LM27_PY=%LM27_ROOT%\python\python.exe"
set "LM27_CLI=%LM27_ROOT%\lm27_cli.py"
pushd "%TEMP%"
if not exist "%LM27_PY%" goto NOPY
echo.
echo  [팀 서버] 이 PC 를 팀 서버로 띄웁니다. 이 창을 닫으면 서버가 멈춥니다.
echo.
"%LM27_PY%" -X utf8 -B "%LM27_CLI%" team-server %*
set "LM27_RC=%ERRORLEVEL%"
popd
echo.
if not "%LM27_RC%"=="0" echo  [!] 팀 서버가 끝났습니다. 위의 안내를 확인하세요.
pause
endlocal & exit /b %LM27_RC%

:NOPY
echo.
echo  [!] 동봉 파이썬을 찾지 못했습니다: python\python.exe
echo      프로그램 폴더를 통째로 다시 복사하세요.
popd
pause
endlocal
exit /b 3
