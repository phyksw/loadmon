@echo off
>nul chcp 949
cd /d "%~dp0"
title AgentFinder32 - 수집 진단
echo.
echo  [수집 진단] 이 PC 의 Outlook 앱, Outlook 웹, Copilot 연결에서 무엇이 막혔는지 확인합니다 (최대 2분).
echo            결과: report\collect_diag.txt  (메일 제목, 이름, 주소는 적지 않습니다 - 이 PC 안에서만)
echo            Outlook 은 '붙기'만 시도하므로 설정 마법사가 뜨거나 멈추지 않습니다.
echo.
rem 파이썬으로 시작 확인을 하고, PowerShell 을 tools\ps_launch.py 를 거쳐 띄운다 - 켜지는 순간 실패(0xc0000142)해도
rem 오류 창 없이 3초, 8초 뒤 두 번 다시 띄운다. 파이썬이 없으면 진단하지 않는다(종료 코드 3) - 시작 확인은 core\consent.py 가
rem 하고(화면, run.py 와 같은 판정) 진단 스크립트의 시작 확인도 그 파이썬을 쓴다.
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
if not defined PY_EXE goto NOPY

rem 시작 확인 - 이 폴더의 자료가 내 것이고 지우는 중이 아닐 때만 진단한다(진단도 Outlook 과 전용 Edge 의 상태를 읽는다).
rem core\consent.py --status 의 종료 코드: 0 쓸 수 있음, 3 지우는 중, 4 다른 사용자의 자료이거나 주인을 모르는 자료
"%PY_EXE%" %PY_ARGS% -X utf8 -B core\consent.py --status --json >nul
set "CRC=%errorlevel%"
if "%CRC%"=="4" goto OTHERUSER
if "%CRC%"=="3" goto WIPING
if not "%CRC%"=="0" goto NOCHECK
if not exist "tools\ps_launch.py" goto PS_RUN
"%PY_EXE%" %PY_ARGS% -X utf8 -B tools\ps_launch.py "collect\Diagnose-Collectors.ps1"
goto DIAG_DONE

:PS_RUN
powershell -NoProfile -ExecutionPolicy Bypass -File "collect\Diagnose-Collectors.ps1"

:DIAG_DONE
rem PowerShell 이 [Console]::OutputEncoding 을 UTF-8 로 바꾸면서 이 창의 코드페이지까지 65001 로 바꿔 놓고 나간다.
rem 그대로 두면 이 뒤에 cmd 가 찍는 한글(pause 안내문 포함)이 깨진다 - 깨진 글자는 그 자체로 "오류가 났다" 로 읽힌다.
>nul chcp 949
echo.
echo  진단 결과는 report\collect_diag.txt 에 있습니다. 이 파일은 이 PC 안에서만 보고, 보관기한이 지나면 지워집니다.
echo.
pause
exit /b 0

:OTHERUSER
>nul chcp 949
echo.
echo  [!] 다른 사용자의 자료라서 진단하지 않았습니다 - 이 폴더의 data, report 자료는 다른 Windows 사용자가 만들었거나,
echo      설치 정보가 없어 주인을 확인할 수 없습니다. AgentFinder32.bat 이나 AgentFinder32-UI.bat 화면에서 지운 뒤 새로 시작할 수 있습니다.
echo.
pause
exit /b 4

:WIPING
>nul chcp 949
echo.
echo  [!] 자료를 지우는 중이라서 진단하지 않았습니다 - AgentFinder32.bat 이나 AgentFinder32-UI.bat 화면을 다시 시작하면 마저 지웁니다.
echo.
pause
exit /b 3

:NOCHECK
>nul chcp 949
echo.
echo  [!] 시작 확인을 하지 못해 진단하지 않았습니다 - 이 폴더에 쓸 수 있는지, 설치 파일이 빠지지 않았는지 확인하세요.
echo.
pause
exit /b 1

:NOPY
echo.
echo  [!] 시작 확인에 쓸 파이썬이 없어 진단하지 않았습니다 - tools\Get-EmbeddedPython.ps1 로 받을 수 있습니다.
echo.
pause
exit /b 3
