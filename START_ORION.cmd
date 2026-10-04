@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL%==0 goto use_py
where python >nul 2>&1
if %ERRORLEVEL%==0 goto use_python
echo Python 3.10+ was not found in PATH.
echo Install Python from python.org and enable Add Python to PATH.
pause
exit /b 10
:use_py
py -3 "%~dp0tools\launcher.py" run
set "ORION_CODE=%ERRORLEVEL%"
goto done
:use_python
python "%~dp0tools\launcher.py" run
set "ORION_CODE=%ERRORLEVEL%"
:done
if not "%ORION_CODE%"=="0" (
  echo.
  echo Orion exited with code %ORION_CODE%.
  echo Run ORION_MENU.cmd for diagnostics.
  pause
)
exit /b %ORION_CODE%
