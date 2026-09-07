@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python 25_SET_COMFYUI_ROOT.py
pause
