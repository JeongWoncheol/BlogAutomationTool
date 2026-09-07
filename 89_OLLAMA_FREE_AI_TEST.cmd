@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
where py >nul 2>nul && (py -3 89_OLLAMA_FREE_AI_TEST.py & pause & exit /b %ERRORLEVEL%)
python 89_OLLAMA_FREE_AI_TEST.py
pause
