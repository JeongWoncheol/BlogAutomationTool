@echo off
setlocal
cd /d "%~dp0"
title Select Normal Chrome Profile v7.3
set "PYTHONUTF8=1"
python chrome_profile.py
pause
