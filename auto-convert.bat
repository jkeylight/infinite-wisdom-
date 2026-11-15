@echo off
REM Infinite Wisdom Converter - AUTO CONVERT (no GUI, bulk CLI)
REM Double-click to auto-convert a folder of books without opening the GUI.
REM
REM How it picks the source folder (first match wins):
REM   1. Folder passed as argument:  auto-convert.bat C:\MyBooks
REM   2. .\Books\          (create this folder next to the .bat and drop books in)
REM   3. .\sample_books\   (demo folder shipped with the repo)
REM Output always goes to .\Converted\  (sidecar folders + optional flat TXTs)
REM
REM Examples:
REM   auto-convert.bat
REM   auto-convert.bat C:\Books
REM   auto-convert.bat C:\Books --flat-txt
setlocal
cd /d "%~dp0"

echo === Infinite Wisdom Auto-Convert ===
echo.

REM --- Pick source folder ---
set "SRC=%~1"
if "%SRC%"=="" (
    if exist "Books\" (
        set "SRC=Books"
    ) else if exist "sample_books\" (
        set "SRC=sample_books"
    ) else (
        echo [ERROR] No source folder found.
        echo Create a "Books" folder next to this file and put your .epub/.pdf files in it,
        echo or pass a folder:  auto-convert.bat C:\MyBooks
        pause
        exit /b 1
    )
)
if not exist "%SRC%\" (
    echo [ERROR] Source folder not found: %SRC%
    pause
    exit /b 1
)

REM --- Pick converter (built CLI exe first, else Python) ---
set "USE_EXE=0"
if exist "dist\converter-cli\converter-cli.exe" set "USE_EXE=1"

if "%USE_EXE%"=="1" (
    echo Using built converter-cli.exe
    echo Source : %SRC%
    echo Output : Converted\
    echo.
    "dist\converter-cli\converter-cli.exe" "%SRC%" -o Converted --skip-existing %*
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found and no built converter-cli.exe.
        echo Run build.bat once to build the exe, or install Python 3.11+.
        pause
        exit /b 1
    )
    python -c "import pymupdf, lxml, PIL" >nul 2>&1
    if errorlevel 1 (
        echo Installing dependencies (first run only)...
        python -m pip install -q -r requirements.txt
    )
    echo Using Python CLI
    echo Source : %SRC%
    echo Output : Converted\
    echo.
    python -m converter "%SRC%" -o Converted --skip-existing %*
)

echo.
echo Done. Converted books are in the Converted\ folder.
echo Each book:  Converted\<BookName>\<BookName>.txt + book.json + assets\
pause
endlocal
