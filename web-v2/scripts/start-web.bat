@echo off
setlocal
set "WEB_DIR=%~dp0.."
if not exist "%WEB_DIR%\.venv\Scripts\python.exe" (
    echo Set up the web application using web-v2\README.md.
    pause
    exit /b 1
)
"%WEB_DIR%\.venv\Scripts\python.exe" "%WEB_DIR%\run.py" --open %*
set "WEB_EXIT=%ERRORLEVEL%"
if not "%WEB_EXIT%"=="0" (
    echo The web launcher stopped with exit code %WEB_EXIT%.
    pause
)
exit /b %WEB_EXIT%
