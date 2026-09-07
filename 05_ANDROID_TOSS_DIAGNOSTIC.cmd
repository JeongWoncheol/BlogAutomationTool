@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "%CD%\tools\platform-tools\adb.exe" set "PATH=%CD%\tools\platform-tools;%PATH%"
set "PATH=%APPDATA%\npm;%ProgramFiles%\nodejs;%PATH%"
python 05_ANDROID_TOSS_DIAGNOSTIC.py
pause
