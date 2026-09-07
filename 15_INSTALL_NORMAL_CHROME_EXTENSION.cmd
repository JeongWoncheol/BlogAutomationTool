@echo off
setlocal
cd /d "%~dp0"
title Normal Chrome Collector Guided Setup v7.4
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python 15_INSTALL_NORMAL_CHROME_EXTENSION.py
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [PASS] Guided extension setup completed.) else (echo [CHECK] Guided setup returned %RC%.)
pause
exit /b %RC%
