@echo off
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title Android Device Connection Assistant v6.4
python 04B_CONNECT_ANDROID_DEVICE.py
pause
