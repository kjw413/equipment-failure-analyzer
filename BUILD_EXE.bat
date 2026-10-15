@echo off
setlocal
cd /d "%~dp0"
if not exist "./build.bat" (
  echo Extract ALL files from the ZIP first. Keep BUILD_EXE.bat next to the source folder.
  pause
  exit /b 1
)
call "./build.bat"
exit /b %errorlevel%
