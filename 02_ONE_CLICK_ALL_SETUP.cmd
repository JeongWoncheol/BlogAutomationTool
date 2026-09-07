@echo off
cd /d "%~dp0"
title One Click Dependency Setup v8.04
echo ============================================================
echo  Blog Automation Studio - One Click Dependency Setup v8.04
echo ============================================================
echo.
echo [1/2] FFmpeg
call 03_SETUP_FFMPEG.cmd
echo.
echo [2/2] Toss Android / Appium
call 04_ANDROID_ONE_CLICK_REPAIR.cmd
echo.
echo All setup stages finished.
pause
