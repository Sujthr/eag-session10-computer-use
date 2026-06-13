@echo off
setlocal enabledelayedexpansion

title Desktop Agent — Setup

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║          Desktop Agent Setup  ·  Session 10                 ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

REM ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo         Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK]    Python %PY_VER% found

REM ── Create .env symlink / copy ─────────────────────────────────────────────
set SHARED_ENV=D:\EAG\EAG\06JuneAssignment\cc33f915-5cf0-4ca5-b7ad-8d8e786736e8\.env
set LOCAL_ENV=%~dp0.env

if not exist "%LOCAL_ENV%" (
    if exist "%SHARED_ENV%" (
        copy /Y "%SHARED_ENV%" "%LOCAL_ENV%" >nul
        echo [OK]    .env copied from shared location
    ) else (
        echo [WARN]  Shared .env not found at:
        echo             %SHARED_ENV%
        echo         Create .env manually with at least GEMINI_API_KEY.
    )
) else (
    echo [OK]    .env already present
)

REM ── Install Python dependencies ────────────────────────────────────────────
echo.
echo Installing Python dependencies...
echo.
pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed — check requirements.txt
    pause
    exit /b 1
)
echo [OK]    Python dependencies installed

REM ── Check cua-driver ─────────────────────────────────────────────────────────
echo.
where cua-driver >nul 2>&1
if errorlevel 1 (
    echo [WARN]  cua-driver not found on PATH.
    echo         The dashboard and logging will work, but tasks will
    echo         fail until cua-driver is installed.
    echo         Install: cargo install cua-driver  (requires Rust)
    echo         Or download the pre-built binary from course materials.
) else (
    for /f %%v in ('cua-driver --version 2^>^&1') do echo [OK]    cua-driver %%v
)

REM ── Create log + recordings dirs ──────────────────────────────────────────────
if not exist "%~dp0logs"       mkdir "%~dp0logs"
if not exist "%~dp0recordings" mkdir "%~dp0recordings"
echo [OK]    Directories created

echo.
echo ══════════════════════════════════════════════════════════════
echo   Setup complete!
echo.
echo   To start:     start.bat
echo   To stop:      stop.bat
echo   Dashboard:    http://127.0.0.1:8765
echo ══════════════════════════════════════════════════════════════
echo.
pause
