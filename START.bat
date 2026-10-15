@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0run.bat" (
  echo Extract ALL files from the ZIP first. Keep START.bat in the project folder.
  pause
  exit /b 1
)
call "%~dp0run.bat" %*
exit /b %errorlevel%
