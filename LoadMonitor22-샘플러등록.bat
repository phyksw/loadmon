@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor22 - 창 샘플러 등록
echo.
echo  [창 샘플러 등록] 로그온할 때마다 자동으로 시작되게 1회 등록합니다.
echo.
echo   - 1분마다 맨 앞 창 이름과 무입력 시간만 이 PC 안의 CSV 에 적습니다 (내용은 읽지 않습니다)
echo   - 이것이 없으면 투입시간을 PC 가동 하한으로만 계산해 실제보다 적게 나옵니다
echo   - 해제: 이 창에서 collect\Register-Samplers.ps1 -Remove
echo.
if not exist "collect\Register-Samplers.ps1" (
  echo  [!] collect\Register-Samplers.ps1 이 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "collect\Register-Samplers.ps1" %*
rem PowerShell 이 이 창의 코드페이지를 65001 로 바꿔 놓고 나간다 - 되돌리지 않으면
rem 아래 pause 안내문이 깨져 나온다(깨진 글자는 그 자체로 오류로 읽힌다).
>nul chcp 949
echo.
pause
