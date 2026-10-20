@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0scripts\build.bat" (
  echo Extract ALL files from the ZIP first. Keep BUILD_EXE.bat in the project folder.
  pause
  exit /b 1
)
call "%~dp0scripts\build.bat"
exit /b %errorlevel%
