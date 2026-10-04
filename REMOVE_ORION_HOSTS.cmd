@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup_orion.ps1" -Action RemoveHosts
set "ORION_CODE=%ERRORLEVEL%"
if not "%ORION_CODE%"=="0" pause
exit /b %ORION_CODE%
