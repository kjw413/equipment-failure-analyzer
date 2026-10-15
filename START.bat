@echo off
setlocal
cd /d "%~dp0"
if not exist "run.bat" (
  echo Extract ALL files from the ZIP first. Keep START.bat next to the source folder.
  pause
  exit /b 1
)
call "run.bat" %*
exit /b %errorlevel%
