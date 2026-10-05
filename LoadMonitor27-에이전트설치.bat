@echo off
>nul chcp 949
setlocal
title LoadMonitor27 - 에이전트 설치
rem agent install --only - 설치 전용 진입점: 에이전트만 심고 수집·탐침·내보내기는 하지 않는다(TAB 1.6.6).
rem 작업 폴더를 TEMP 로 옮겨 이 폴더를 잡지 않는다(TAB 1.9).
set "LM27_ROOT=%~dp0"
set "LM27_ROOT=%LM27_ROOT:~0,-1%"
set "LM27_PY=%LM27_ROOT%\python\python.exe"
set "LM27_CLI=%LM27_ROOT%\lm27_cli.py"
pushd "%TEMP%"
if not exist "%LM27_PY%" goto NOPY
"%LM27_PY%" -X utf8 -B "%LM27_CLI%" agent install --only %*
set "LM27_RC=%ERRORLEVEL%"
popd
echo.
if "%LM27_RC%"=="0" echo  [완료] 이 PC 에 기록 에이전트를 설치했습니다. 이 PC 의 사용 기록은 오늘부터 쌓입니다.
if "%LM27_RC%"=="0" echo         나중에 이 폴더로 [수집]을 누르면 번들에 들어옵니다.
if "%LM27_RC%"=="4" echo  [완료] 이 PC 의 기록 에이전트가 이미 정상으로 돌고 있습니다.
if "%LM27_RC%"=="2" echo  [안내] 에이전트는 설치했지만 일부를 마치지 못했습니다. 위의 안내를 확인하세요.
if "%LM27_RC%"=="3" echo  [!] 이 PC 환경에서는 에이전트를 실행할 수 없습니다. 위의 안내를 확인하세요.
if "%LM27_RC%"=="1" echo  [!] 설치 중 오류가 났습니다. 위의 안내를 확인하세요.
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
