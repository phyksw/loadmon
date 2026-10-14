@echo off
>nul chcp 949
cd /d "%~dp0"
title LoadMonitor28 - 강제 종료
rem 이 폴더의 LM28 작업(대시보드·분석·수집기·전용 Edge·그 콘솔 창)을 묻지 않고 모두 끝낸다 - tools\Stop-LM28.ps1.
rem 창을 닫았는데 뒤에서 계속 도는 것 같을 때 쓰는 비상 단추다. 일반 Edge·다른 폴더(LM24 등)·팀 서버는 건드리지 않는다.
rem 팀 서버까지 끄려면 명령 창에서  LoadMonitor28-강제종료.bat -IncludeTeamServer  · 목록만 보려면  -Status
rem 관리자 권한·임시 파일·예약 작업 없음.
if not exist "tools\Stop-LM28.ps1" (
  echo.
  echo  [!] tools\Stop-LM28.ps1 이 없습니다 - FILES.txt 목록대로 복사됐는지 확인하세요.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Stop-LM28.ps1" %*
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
