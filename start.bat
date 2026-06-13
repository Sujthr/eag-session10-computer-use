@echo off
setlocal enabledelayedexpansion

title Desktop Agent — Starting

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║          Desktop Agent  ·  Session 10                       ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

REM ── Resolve project root ──────────────────────────────────────────────────────
set ROOT=%~dp0
if "%ROOT:~-1%"=="\" set ROOT=%ROOT:~0,-1%

REM ── Ensure .env exists ────────────────────────────────────────────────────────
set SHARED_ENV=D:\EAG\EAG\06JuneAssignment\cc33f915-5cf0-4ca5-b7ad-8d8e786736e8\.env
if not exist "%ROOT%\.env" (
    if exist "%SHARED_ENV%" (
        copy /Y "%SHARED_ENV%" "%ROOT%\.env" >nul
        echo [OK]    .env loaded from shared location
    ) else (
        echo [WARN]  .env not found — API calls may fail
    )
)

REM ── Start cua-driver daemon ────────────────────────────────────────────────────
where cua-driver >nul 2>&1
if not errorlevel 1 (
    cua-driver status >nul 2>&1
    if errorlevel 1 (
        echo [....] Starting cua-driver daemon...
        start /B cua-driver serve
        timeout /T 1 /NOBREAK >nul
        cua-driver status >nul 2>&1
        if not errorlevel 1 (
            echo [OK]    cua-driver daemon running
        ) else (
            echo [WARN]  cua-driver daemon may not have started correctly
        )
    ) else (
        echo [OK]    cua-driver daemon already running
    )
) else (
    echo [WARN]  cua-driver not found — install before running tasks
)

REM ── Write PID file for stop.bat ───────────────────────────────────────────────
set PID_FILE=%ROOT%\.agent.pid

REM ── Check if dashboard is already running ─────────────────────────────────────
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    tasklist /FI "PID eq !OLD_PID!" 2>nul | find "python" >nul
    if not errorlevel 1 (
        echo [OK]    Dashboard already running (PID=!OLD_PID!)
        echo         Open: http://127.0.0.1:8765
        echo.
        start "" "http://127.0.0.1:8765"
        goto :menu
    )
)

REM ── Start dashboard (FastAPI) ──────────────────────────────────────────────────
echo [....] Starting web dashboard...

REM Start in a minimized independent window so it survives after start.bat exits
start "Desktop Agent Dashboard" /MIN cmd /K "cd /D "%ROOT%" && python "%ROOT%\main.py" --dashboard --no-browser"
timeout /T 3 /NOBREAK >nul

REM Find the python process running main.py
for /f "tokens=1" %%p in ('wmic process where "commandline like '%%main.py%%dashboard%%'" get processid /value 2^>nul ^| findstr "="') do (
    set "PID_LINE=%%p"
)
set "DASH_PID="
for /f "tokens=2 delims==" %%v in ("!PID_LINE!") do set "DASH_PID=%%v"
if defined DASH_PID (
    echo !DASH_PID!> "%PID_FILE%"
    echo [OK]    Dashboard started
) else (
    echo [WARN]  Could not capture dashboard PID
)

timeout /T 1 /NOBREAK >nul

REM ── Open browser ──────────────────────────────────────────────────────────────
echo [OK]    Opening http://127.0.0.1:8765 in browser...
start "" "http://127.0.0.1:8765"

echo.
echo ══════════════════════════════════════════════════════════════
echo   Agent is running!
echo.
echo   Dashboard:   http://127.0.0.1:8765
echo   Logs:        %ROOT%\logs\
echo   Recordings:  %ROOT%\recordings\
echo.
echo   To run tasks from the terminal instead:
echo     python main.py --task calculator
echo     python main.py --task vscode
echo     python main.py --task browser_game
echo.
echo   To stop everything:  stop.bat
echo ══════════════════════════════════════════════════════════════
echo.

:menu
echo Press any key to launch the interactive CLI...
pause >nul
python "%ROOT%\main.py"
