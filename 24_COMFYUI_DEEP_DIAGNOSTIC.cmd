@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python 24_COMFYUI_DEEP_DIAGNOSTIC.py
pause
