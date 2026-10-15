@echo off
setlocal
cd /d "%~dp0"
echo Building a Windows executable. This may take several minutes.
call "%~dp0setup.bat" --no-pause
if errorlevel 1 goto failure
if exist "wheels\*.whl" (
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links=wheels -r requirements-build.txt
) else (
    ".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
)
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean EquipmentFailureAnalyzer.spec
if errorlevel 1 goto failure
if not exist "dist\EquipmentFailureAnalyzer.exe" goto failure
rem The copied file carries the program version, so an old build is never mistaken for the current one.
set "EFA_VERSION="
for /f "tokens=2 delims='" %%v in ('findstr /b /c:"VERSION = " version.py') do set "EFA_VERSION=%%v"
if not defined EFA_VERSION goto failure
copy /y "dist\EquipmentFailureAnalyzer.exe" "EquipmentFailureAnalyzer_v%EFA_VERSION%.exe" >nul
if errorlevel 1 goto failure
echo.
echo DONE: EquipmentFailureAnalyzer_v%EFA_VERSION%.exe is in this project folder.
if exist "EquipmentFailureAnalyzer.exe" echo NOTE: EquipmentFailureAnalyzer.exe without a version number is an older build. Delete it so it is not started by mistake.
echo Test this file here before copying it to the destination Windows PC.
echo The destination PC does not need Python or this project folder.
echo This EXE is not code-signed. Follow your organization's IT policy.
echo Existing names/rules remain in LOCALAPPDATA\EquipmentFailureAnalyzer.
pause
exit /b 0
:failure
echo Build failed. Do NOT assume an EXE from a previous build is up-to-date.
echo No successfully built EXE is claimed for this attempt. See USER_GUIDE.pdf.
pause
exit /b 1
