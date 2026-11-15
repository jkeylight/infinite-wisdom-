@echo off
REM Infinite Wisdom Converter - Windows portable build (personal use, no signing)
REM Double-click this file on Windows. Requires Python 3.11+ on PATH.
setlocal
cd /d "%~dp0"

echo === Infinite Wisdom Converter - Build ===
python --version || (echo Python not found. Install Python 3.11+ from python.org & pause & exit /b 1)

echo Installing dependencies...
python -m pip install -r requirements.txt pyinstaller || (echo pip install failed & pause & exit /b 1)

echo.
echo Building GUI (one-folder, windowed)...
python -m PyInstaller --noconfirm --windowed --name Converter ^
  --collect-all pymupdf --collect-all lxml --collect-all PySide6 ^
  --version-file version_info.txt ^
  -p . run_gui.py || (echo GUI build failed & pause & exit /b 1)

echo.
echo Building CLI (one-folder, console)...
python -m PyInstaller --noconfirm --console --name converter-cli ^
  --collect-all pymupdf --collect-all lxml ^
  -p . run_cli.py || (echo CLI build failed & pause & exit /b 1)

echo.
echo === Build complete ===
echo   GUI : dist\Converter\Converter.exe   (double-click to run)
echo   CLI : dist\converter-cli\converter-cli.exe
echo.
echo Copy the dist\Converter folder anywhere - it is portable.
echo Settings are saved to config.json next to the exe.
echo.
pause
