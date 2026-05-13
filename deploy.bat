@echo off
cd /d "%~dp0"
git add .
git commit -m "site update"
git push
echo.
echo Done! Your site will be live in ~30 seconds.
pause
