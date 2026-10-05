@echo off
>nul chcp 949
setlocal
title LoadMonitor27
rem LoadMonitor27 - 로컬 앱(화면) 기동. 기본 진입(계약 7.2).
rem 작업 폴더를 TEMP 로 옮겨 이 폴더를 잡지 않는다 - 폴더 이동과 이름 바꾸기를 막지 않게(TAB 1.9).
rem 화면은 pythonw 로 창 없이 띄운다. 먼저 python 의 ui --check 로 기동 가능 여부를 확인해 실패하면 안내를 남긴다.
set "LM27_ROOT=%~dp0"
set "LM27_ROOT=%LM27_ROOT:~0,-1%"
set "LM27_PY=%LM27_ROOT%\python\python.exe"
set "LM27_CLI=%LM27_ROOT%\lm27_cli.py"
set "LM27_PYW=%LM27_ROOT%\python\pythonw.exe"
pushd "%TEMP%"
if not exist "%LM27_PY%" goto NOPY
if not exist "%LM27_PYW%" goto NOPY
"%LM27_PY%" -X utf8 -B "%LM27_CLI%" ui --check
if errorlevel 1 goto FAIL
start "" "%LM27_PYW%" -X utf8 -B "%LM27_CLI%" ui %*
popd
endlocal
exit /b 0

:FAIL
echo.
echo  [!] 화면을 띄우지 못했습니다. 위의 안내를 확인하세요.
popd
pause
endlocal
exit /b 3

:NOPY
echo.
echo  [!] 동봉 파이썬을 찾지 못했습니다: python\python.exe
echo      프로그램 폴더를 통째로 다시 복사하세요.
popd
pause
endlocal
exit /b 3
