@echo off
REM Infinite Wisdom Converter - AUTO RUN (GUI launcher)
REM Double-click this file. It auto-runs the GUI:
REM   1. Built exe if present (dist\Converter\Converter.exe)
REM   2. Otherwise Python from source (installs deps automatically)
setlocal
cd /d "%~dp0"

echo === Infinite Wisdom Converter ===
echo.

REM --- 1. Built exe (fastest, no Python needed) ---
if exist "dist\Converter\Converter.exe" (
    echo Starting built Converter.exe ...
    start "" "dist\Converter\Converter.exe"
    exit /b 0
)

REM --- 2. Python from source ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to tick "Add python.exe to PATH" during install.
    echo.
    echo Tip: run build.bat once to create a standalone Converter.exe,
    echo then this file will launch the exe directly (no Python needed).
    pause
    exit /b 1
)

echo Python found. Checking dependencies...
python -c "import pymupdf, lxml, PIL, PySide6" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies (first run only)...
    python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed. Check your internet connection.
        pause
        exit /b 1
    )
)

echo Starting GUI ...
python -m converter.gui
if errorlevel 1 (
    echo.
    echo [ERROR] Converter exited with an error. See message above.
    pause
)
endlocal
