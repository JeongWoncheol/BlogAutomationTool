@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 84_COUPANG_PARTNERS_API_TEST.py
pause
