@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto launch_py
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto launch_python
echo Install Python 3.11 or newer with Tcl/Tk and pip, then open this launcher again.
pause
exit /b 1
:launch_py
py -3 "%~dp0scripts\launch.py"
goto finished
:launch_python
python "%~dp0scripts\launch.py"
:finished
if not errorlevel 1 exit /b 0
echo Startup failed. Review the message above and try again.
pause
exit /b 1
