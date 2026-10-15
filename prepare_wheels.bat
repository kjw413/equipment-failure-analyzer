@echo off
setlocal
cd /d "%~dp0"
echo Run on an approved internet-enabled Windows PC with the SAME Python version and architecture.
if exist ".venv\Scripts\python.exe" (
    set "EFA_PYTHON=".venv\Scripts\python.exe""
    goto download
)
call find_python.bat
if errorlevel 1 goto failure
:download
if not exist wheels mkdir wheels
%EFA_PYTHON% -m pip download --only-binary=:all: --dest wheels -r requirements-build.txt
if errorlevel 1 goto failure
echo Download complete. Copy the whole wheels folder into the offline project's source folder.
echo Always keep the Python minor version and 64-bit architecture the same.
pause
exit /b 0
:failure
echo Download failed. A partial wheels folder is NOT a complete offline installation kit.
echo Use Python 3.11-3.13 64-bit and approved package access. See USER_GUIDE.pdf.
pause
exit /b 1
