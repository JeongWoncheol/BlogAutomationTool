@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem v8.08.38: always prefer the current Python source tree.
rem This prevents an old EXE or stale __pycache__ from silently running older
rem SmartEditor code while the folder name says a newer version.
set "PYTHONDONTWRITEBYTECODE=1"
if exist "%~dp0__pycache__" rmdir /s /q "%~dp0__pycache__" >nul 2>nul
if exist "%~dp0modules\__pycache__" rmdir /s /q "%~dp0modules\__pycache__" >nul 2>nul

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0app.py"
  set "RC=!ERRORLEVEL!"
  if not "!RC!"=="0" pause
  exit /b !RC!
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0app.py"
  set "RC=!ERRORLEVEL!"
  if not "!RC!"=="0" pause
  exit /b !RC!
)

rem Fallback only when Python is not installed.
if exist "%~dp0NaverBlogAutomationStudio.exe" (
  echo [WARN] Python was not found. Falling back to packaged EXE.
  start "" "%~dp0NaverBlogAutomationStudio.exe"
  exit /b 0
)

echo [ERROR] Python 3 was not found.
pause
exit /b 1
