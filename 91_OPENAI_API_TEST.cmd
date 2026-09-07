@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
where py >nul 2>nul && (py -3 91_OPENAI_API_TEST.py & pause & exit /b %ERRORLEVEL%)
python 91_OPENAI_API_TEST.py
pause
