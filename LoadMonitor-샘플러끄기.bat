@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor 샘플러 끄기
echo.
echo  [LoadMonitor 샘플러 끄기] LM20~LM25 의 창 샘플러·팀즈 샘플러가 돌고 있는지 확인하고 끕니다.
echo   - 먼저 상태를 보여 주고 끌지 묻습니다 (Y 를 누르기 전에는 아무것도 바꾸지 않습니다)
echo   - 끄면: 샘플러 프로세스 종료 + 로그온 자동 시작 작업을 '사용 안 함'으로
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
