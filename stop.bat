@echo off
setlocal enabledelayedexpansion

title Desktop Agent — Stopping

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║          Desktop Agent  ·  Shutdown                         ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

set ROOT=%~dp0
if "%ROOT:~-1%"=="\" set ROOT=%ROOT:~0,-1%

set PID_FILE=%ROOT%\.agent.pid
set EXIT_CODE=0

REM ── Stop cua-driver daemon ────────────────────────────────────────────────────
where cua-driver >nul 2>&1
if not errorlevel 1 (
    echo [....] Stopping cua-driver daemon...
    cua-driver shutdown >nul 2>&1
    if errorlevel 1 (
        echo [WARN]  cua-driver shutdown returned non-zero (may already be stopped)
    ) else (
        echo [OK]    cua-driver daemon stopped
    )
) else (
    echo [SKIP]  cua-driver not found, nothing to stop
)

REM ── Stop dashboard process ─────────────────────────────────────────────────────
if exist "%PID_FILE%" (
    set /p DASH_PID=<"%PID_FILE%"
    echo [....] Stopping dashboard (PID=!DASH_PID!)...
    taskkill /PID !DASH_PID! /F >nul 2>&1
    if errorlevel 1 (
        echo [WARN]  Process !DASH_PID! not found (may already be stopped)
    ) else (
        echo [OK]    Dashboard stopped
    )
    del "%PID_FILE%" >nul 2>&1
) else (
    echo [INFO]  No PID file found — looking for orphan python processes...
)

REM ── Kill any remaining uvicorn / main.py processes ────────────────────────────
for /f "tokens=1" %%p in (
    'wmic process where "commandline like ''%%main.py%%''" get processid /value 2^>nul ^| findstr /R "[0-9]"'
) do (
    for /f "tokens=2 delims==" %%v in ("%%p") do (
        taskkill /PID %%v /F >nul 2>&1
        echo [OK]    Killed orphan process %%v
    )
)

echo.
echo [OK]    All agent processes stopped.
echo.
echo ══════════════════════════════════════════════════════════════
echo   Shutdown complete.
echo   Logs preserved at:  %ROOT%\logs\
echo   Recordings at:      %ROOT%\recordings\
echo ══════════════════════════════════════════════════════════════
echo.
pause
