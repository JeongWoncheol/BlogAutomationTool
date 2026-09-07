@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title Android Toss Repair v6.2
python 04_ANDROID_ONE_CLICK_REPAIR.py
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [DONE] Android/Appium setup completed.
) else (
  echo [FAIL] Setup failed. Check logs\android_repair.log
)
pause
exit /b %RC%
