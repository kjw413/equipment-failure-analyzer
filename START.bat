@echo off
setlocal
cd /d "%~dp0"
if not exist "source\run.bat" (
  echo Extract ALL files from the ZIP first. Keep START.bat next to the source folder.
  pause
  exit /b 1
)
call "source\run.bat" %*
exit /b %errorlevel%
