@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
where py >nul 2>nul && (py -3 88_OLLAMA_FREE_AUTO_SETUP.py & pause & exit /b %ERRORLEVEL%)
python 88_OLLAMA_FREE_AUTO_SETUP.py
pause
