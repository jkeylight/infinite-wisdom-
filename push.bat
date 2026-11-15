@echo off
REM Infinite Wisdom Converter - PUSH TO GITHUB (Windows)
REM Double-click this file on Windows. It pushes ALL local commits + tags
REM to https://github.com/jkeylight/infinite-wisdom-.git
REM GitHub will ask for your username + password/token (first time only).
REM Tip: use a Personal Access Token as password (github.com/settings/tokens)
REM      so you don't type your real password. Git Credential Manager will
REM      remember it for next time.
setlocal
cd /d "%~dp0"

echo === Push to GitHub ===
echo Repo: https://github.com/jkeylight/infinite-wisdom-.git
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git not found.
    echo Install Git from https://git-scm.com/download/win
    echo Tick "Git from the Windows Command Prompt" during install, then try again.
    pause
    exit /b 1
)

REM --- Remote ---
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo Adding remote origin...
    git remote add origin https://github.com/jkeylight/infinite-wisdom-.git
) else (
    echo Remote already set:
    git remote -v
)

echo.
echo Status:
git status --short
git log --oneline -5
echo.

echo Pushing main + tags (you may be asked for GitHub login)...
git push -u origin main --tags
if errorlevel 1 (
    echo.
    echo [ERROR] Push failed. See message above.
    echo Common causes:
    echo  - Wrong username/password. Use a Personal Access Token as password.
    echo  - No internet connection.
    echo  - Repo name/owner wrong. Check: https://github.com/jkeylight/infinite-wisdom-
    pause
    exit /b 1
)

echo.
echo === Push complete! ===
echo Your code is now on GitHub: https://github.com/jkeylight/infinite-wisdom-
pause
endlocal
