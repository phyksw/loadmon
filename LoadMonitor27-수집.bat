@echo off
>nul chcp 949
setlocal
title LoadMonitor27 - 수집
rem [수집] = collect --auto - 묻지 않고 한 번 모으고, 끝에 대기 중인 팀 업로드도 보낸다(계약 7.2).
rem 작업 폴더를 TEMP 로 옮겨 이 폴더를 잡지 않는다(TAB 1.9).
set "LM27_ROOT=%~dp0"
set "LM27_ROOT=%LM27_ROOT:~0,-1%"
set "LM27_PY=%LM27_ROOT%\python\python.exe"
set "LM27_CLI=%LM27_ROOT%\lm27_cli.py"
pushd "%TEMP%"
if not exist "%LM27_PY%" goto NOPY
"%LM27_PY%" -X utf8 -B "%LM27_CLI%" collect --auto %*
set "LM27_RC=%ERRORLEVEL%"
popd
echo.
if "%LM27_RC%"=="0" echo  [완료] 수집을 마쳤습니다.
if "%LM27_RC%"=="4" echo  [완료] 새로 모을 기록이 없습니다 - 이미 최신입니다.
if "%LM27_RC%"=="2" echo  [안내] 일부만 모았습니다. 위의 안내를 확인하세요 - 다음 수집이 이어서 합니다.
if "%LM27_RC%"=="3" echo  [!] 이 PC 환경 때문에 수집하지 못했습니다. 위의 안내를 확인하세요.
if "%LM27_RC%"=="1" echo  [!] 수집 중 오류가 났습니다. 위의 안내를 확인하세요.
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
