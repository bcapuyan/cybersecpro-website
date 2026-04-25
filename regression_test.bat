@echo off
REM CyberSec Pro Academy — regression test launcher
REM Double-click this file after deploy_bat to verify the live site.

cd /d "%~dp0"

REM Prefer `py` (Python launcher), fall back to `python`
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 regression_test.py %*
) else (
    python regression_test.py %*
)

set EXITCODE=%ERRORLEVEL%
echo.
if %EXITCODE%==0 (
    echo ==============================================
    echo  ALL CHECKS PASSED
    echo ==============================================
) else (
    echo ==============================================
    echo  FAILURES DETECTED - see HTML report
    echo ==============================================
)
echo.
pause
exit /b %EXITCODE%
