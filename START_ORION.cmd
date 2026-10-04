@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup_orion.ps1" -Action Run
set "ORION_CODE=%ERRORLEVEL%"
if not "%ORION_CODE%"=="0" (
  echo.
  echo Orion exited with code %ORION_CODE%.
  echo Open ORION_MENU.cmd for diagnostics and configuration.
  pause
)
exit /b %ORION_CODE%
