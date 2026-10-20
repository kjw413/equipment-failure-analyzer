@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo Run scripts\setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q %*
set "EFA_TEST_EXIT=%errorlevel%"
pause
exit /b %EFA_TEST_EXIT%
