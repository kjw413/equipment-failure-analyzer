@echo off
setlocal
cd /d "%~dp0"
echo Building a Windows executable. This may take several minutes.
call setup.bat --no-pause
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
copy /y "dist\EquipmentFailureAnalyzer.exe" "..\EquipmentFailureAnalyzer.exe" >nul
if errorlevel 1 goto failure
echo.
echo DONE: EquipmentFailureAnalyzer.exe is in the top-level folder.
echo Test this file here before copying it to the destination Windows PC.
echo The destination PC does not need Python or the source folder.
echo This EXE is not code-signed. Follow your organization's IT policy.
echo Existing names/rules remain in LOCALAPPDATA\EquipmentFailureAnalyzer.
pause
exit /b 0
:failure
echo Build failed. Do NOT assume an EXE from a previous build is up-to-date.
echo No successfully built EXE is claimed for this attempt. See USER_GUIDE.pdf.
pause
exit /b 1
