@echo off
>nul chcp 949
setlocal
title LoadMonitor27 - 이동 준비
rem 이동 준비: 도우미 PS(collect\move\Prepare-Move.ps1)를 TEMP 의 lm27_move_<rand>.ps1 사본으로 띄우고
rem 이 창은 바로 끝낸다(계약 7.2, TAB 1.11). 이 창의 작업 폴더가 이 폴더를 잡으면 이름 바꾸기 시험이 실패하므로
rem 먼저 TEMP 로 옮긴다. 결과는 새로 뜨는 도우미 창에 나온다.
set "LM27_ROOT=%~dp0"
set "LM27_ROOT=%LM27_ROOT:~0,-1%"
set "LM27_HELPER=%LM27_ROOT%\collect\move\Prepare-Move.ps1"
set "LM27_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
pushd "%TEMP%"
if not exist "%LM27_HELPER%" goto NOHELPER
set "LM27_TMP=%TEMP%\lm27_move_%RANDOM%%RANDOM%.ps1"
copy /y "%LM27_HELPER%" "%LM27_TMP%" >nul
if errorlevel 1 goto NOCOPY
start "LoadMonitor27 - 이동 준비" "%LM27_PS%" -NoProfile -ExecutionPolicy Bypass -File "%LM27_TMP%" -Root "%LM27_ROOT%"
popd
endlocal
exit /b 0

:NOHELPER
echo.
echo  [!] 이동 도우미 collect\move\Prepare-Move.ps1 이 없습니다.
echo      프로그램 폴더를 통째로 다시 복사하세요.
popd
pause
endlocal
exit /b 3

:NOCOPY
echo.
echo  [!] 이동 도우미를 임시 폴더로 복사하지 못했습니다. 임시 폴더의 여유 공간과 권한을 확인하세요.
popd
pause
endlocal
exit /b 3
