@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
where py >nul 2>nul && (py -3 90_OPENAI_API_SETUP.py & pause & exit /b %ERRORLEVEL%)
python 90_OPENAI_API_SETUP.py
pause
