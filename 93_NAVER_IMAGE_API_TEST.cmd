@echo off
chcp 65001 >nul
cd /d "%~dp0"
python 93_NAVER_IMAGE_API_TEST.py
echo.
pause
