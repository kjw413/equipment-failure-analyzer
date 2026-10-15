@echo off
rem Shared interpreter selection. Do not use setlocal: return EFA_PYTHON to caller.
set "EFA_PYTHON="
call :probe py -3.13
call :probe py -3.12
call :probe py -3.11
call :probe py -3
call :probe python
call :probe python3
if not defined EFA_PYTHON exit /b 1
exit /b 0
:probe
if defined EFA_PYTHON exit /b 0
%* -c "import sys,struct; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8 else 1)" >nul 2>nul
if not errorlevel 1 set "EFA_PYTHON=%*"
exit /b 0
