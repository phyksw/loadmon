@echo off
setlocal DisableDelayedExpansion
>nul chcp 949
call "%~dp0LoadMonitor25-이동준비.bat" %*
exit /b %ERRORLEVEL%
