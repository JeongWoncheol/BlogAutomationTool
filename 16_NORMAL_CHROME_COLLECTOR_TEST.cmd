@echo off
setlocal
cd /d "%~dp0"
title Coupang Naver Chrome Collector Test v7.35 FIXED
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python 16_NORMAL_CHROME_COLLECTOR_TEST.py
pause
