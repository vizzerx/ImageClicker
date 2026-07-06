@echo off
cd /d "%~dp0"

echo ============================================
echo    Image Clicker - setup and run
echo ============================================
echo.

REM --- find a working Python launcher ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>&1 && set "PYEXE=python"
)

REM --- make sure it really runs (skip the Microsoft Store stub) ---
if defined PYEXE (
    %PYEXE% --version >nul 2>&1 || set "PYEXE="
)

if not defined PYEXE (
    echo [!] Python NOT found on this PC.
    echo.
    echo 1^) Install Python from:  https://www.python.org/downloads/
    echo    During setup, TICK the box  "Add Python to PATH"  ^(important^)
    echo.
    echo 2^) If you already installed it, turn OFF the Store shortcut:
    echo    Settings ^> Apps ^> Advanced app settings ^>
    echo    App execution aliases ^> turn OFF  python.exe / python3.exe
    echo.
    echo Then run this file again.
    echo.
    pause
    exit /b
)

echo Using Python launcher: %PYEXE%
echo.

if not exist ".venv" (
    echo Creating environment and installing libraries...
    echo ^(first time only - please wait a moment^)
    %PYEXE% -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

echo.
echo Starting program...
python image_clicker.py

pause
