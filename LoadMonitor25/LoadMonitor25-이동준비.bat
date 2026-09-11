@echo off
setlocal DisableDelayedExpansion
>nul chcp 949
set "LM_ROOT=%~dp0"
set "LM_ROOT=%LM_ROOT:~0,-1%"
set "LM_ARG=%~1"
if "%LM_ARG:~0,2%"=="--" (
  echo PC 이동 준비는 정리와 ZIP 생성을 한 번에 수행합니다.
  echo 기존 CLI 옵션은 아래 도구를 직접 실행하세요:
  echo   python -B "%LM_ROOT%\tools\transfer.py" --root "%LM_ROOT%" --output "ZIP 전체 경로" --json
  echo   ^(--plan, --json, --root, --output 옵션 지원^)
  exit /b 2
)
if not exist "%LM_ROOT%\tools\Prepare-Move.ps1" (
  echo [미완료] tools\Prepare-Move.ps1이 없습니다. 배포 파일을 확인하세요.
  pause
  exit /b 1
)
set "LM_PREP=%TEMP%\LM25-Prepare-Move-%RANDOM%-%RANDOM%.ps1"
copy /y "%LM_ROOT%\tools\Prepare-Move.ps1" "%LM_PREP%" >nul
if errorlevel 1 (
  echo [미완료] 준비 도구를 TEMP로 복사하지 못했습니다.
  pause
  exit /b 1
)
rem 전용 창이 원본 폴더 밖에서 정리, 폴더 확인, ZIP 생성을 한 번만 수행합니다.
cd /d "%TEMP%"
start "LoadMonitor25 - PC 이동 준비" powershell -NoProfile -ExecutionPolicy Bypass -File "%LM_PREP%" -Root "%LM_ROOT%" %*
exit /b %ERRORLEVEL%
