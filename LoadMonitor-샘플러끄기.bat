@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor 샘플러 끄기
echo.
echo  [LoadMonitor 샘플러 끄기] LM20~LM25 의 창 샘플러·팀즈 샘플러를 확인하고 바로 끕니다.
echo   - 샘플러 프로세스를 종료하고, 로그온 자동 시작 작업을 지웁니다 (묻지 않습니다)
echo   - 확인만 하려면: LoadMonitor-샘플러끄기.bat -Status
echo.
if not exist "%~dp0Stop-LMSampler.ps1" (
  echo  [!] Stop-LMSampler.ps1 이 이 bat 과 같은 폴더에 없습니다 - 압축을 모두 푼 뒤 실행하세요.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-LMSampler.ps1" %*
rem PowerShell 이 바꿔 놓은 코드페이지를 되돌린다 - 그래야 아래 안내문이 깨지지 않는다
>nul chcp 949
echo.
pause
