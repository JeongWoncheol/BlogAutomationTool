@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title FFmpeg Automatic Setup v5.9

echo ============================================================
echo   FFmpeg automatic setup v5.9
echo ============================================================
echo.

where ffmpeg >nul 2>nul
if not errorlevel 1 goto :FOUND

echo [CHECK] FFmpeg not found in PATH.
echo [AUTO] Trying winget installation...

where winget >nul 2>nul
if errorlevel 1 goto :NOWINGET

winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [WARN] Gyan.FFmpeg install failed. Trying BtbN.FFmpeg.GPL...
    winget install --id BtbN.FFmpeg.GPL -e --accept-package-agreements --accept-source-agreements
)

echo.
echo [REFRESH] Searching installed FFmpeg...
for /f "delims=" %%F in ('where /r "%LOCALAPPDATA%\Microsoft\WinGet\Packages" ffmpeg.exe 2^>nul') do (
    set "FFMPEG_EXE=%%F"
    goto :FOUND_PATH
)
for /f "delims=" %%F in ('where /r "%ProgramFiles%" ffmpeg.exe 2^>nul') do (
    set "FFMPEG_EXE=%%F"
    goto :FOUND_PATH
)

set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
where ffmpeg >nul 2>nul
if not errorlevel 1 goto :FOUND

echo [FAIL] FFmpeg installation could not be verified.
echo Close this window, open a new terminal and run this file again.
goto :ENDFAIL

:FOUND_PATH
for %%D in ("!FFMPEG_EXE!") do set "FFMPEG_DIR=%%~dpD"
set "PATH=!FFMPEG_DIR!;%PATH%"
echo [PASS] FFmpeg found: !FFMPEG_EXE!
"!FFMPEG_EXE!" -version | findstr /b /c:"ffmpeg version"
goto :VERIFY

:FOUND
for /f "delims=" %%F in ('where ffmpeg') do (
    set "FFMPEG_EXE=%%F"
    goto :FOUND2
)
:FOUND2
echo [PASS] FFmpeg found: !FFMPEG_EXE!
ffmpeg -version | findstr /b /c:"ffmpeg version"

:VERIFY
echo.
echo [TEST] Encoding capability check...
ffmpeg -hide_banner -encoders 2>nul | findstr /i "libx264 h264" >nul
if errorlevel 1 (
    echo [WARN] H.264 encoder was not detected. Video export may need another encoder.
) else (
    echo [PASS] Video encoder available.
)
echo.
echo FFmpeg setup complete.
echo FFmpeg setup complete. You can now run START_STUDIO.cmd.
pause
exit /b 0

:NOWINGET
echo [FAIL] winget is not installed on this Windows PC.
echo Install/update 'App Installer' from Microsoft Store, then retry.
goto :ENDFAIL

:ENDFAIL
pause
exit /b 1
