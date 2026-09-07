@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 95_IMAGE_SOURCE_CHAIN_DIAGNOSTIC.py
pause
