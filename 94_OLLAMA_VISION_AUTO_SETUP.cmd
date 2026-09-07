@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 94_OLLAMA_VISION_AUTO_SETUP.py
if errorlevel 1 pause
