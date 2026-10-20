@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import PySide6, pandas, numpy, openpyxl, matplotlib, PIL, reportlab" >nul 2>nul
if errorlevel 1 goto setup
goto launch
:setup
echo First launch needs Python and approved dependencies.
echo After setup, the analysis program runs offline.
call "%~dp0setup.bat" --no-pause
if errorlevel 1 goto failure
:launch
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 goto failure
exit /b 0
:failure
echo Launch failed. This is the SOURCE launcher, not a standalone EXE.
echo Python 3.11-3.13 64-bit is required here. See USER_GUIDE.pdf.
echo Use BUILD_EXE.bat on a prepared Windows PC for PCs without Python.
pause
exit /b 1
