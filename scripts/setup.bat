@echo off
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" goto check_python
call "%~dp0find_python.bat"
if errorlevel 1 goto python_error
echo Creating the local Python environment...
%EFA_PYTHON% -m venv .venv
if errorlevel 1 goto failure
:check_python
".venv\Scripts\python.exe" -c "import sys,struct; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 goto python_error
if exist "wheels\*.whl" (
    echo Installing from local wheels - no online fallback.
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links=wheels -r requirements.txt
) else (
    echo Installing program dependencies. Approved internet/package access is needed.
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -c "import PySide6, pandas, numpy, openpyxl, matplotlib, PIL, reportlab"
if errorlevel 1 goto failure
echo Setup complete. Use START.bat in the project folder.
if /i not "%~1"=="--no-pause" pause
exit /b 0
:python_error
echo Python 3.11, 3.12 or 3.13 - 64-bit is required on this PC.
echo Contact IT for approved Python installation. See USER_GUIDE.pdf.
echo If an incompatible local environment exists, ask IT to recreate the .venv folder.
if /i not "%~1"=="--no-pause" pause
exit /b 1
:failure
echo Setup failed. See the error above; no successful setup is claimed.
echo For offline setup, use a complete compatible wheels folder. See USER_GUIDE.pdf.
if /i not "%~1"=="--no-pause" pause
exit /b 1
