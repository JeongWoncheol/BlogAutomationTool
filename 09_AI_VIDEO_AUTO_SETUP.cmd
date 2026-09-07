@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title AI Product Video Auto Setup v7.10
python 09_AI_VIDEO_AUTO_SETUP.py
pause
