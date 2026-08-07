@echo off
REM ==========================================================
REM  Launch Streamlit + expose it via Cloudflare Tunnel
REM  Share the printed https:// URL with anyone.
REM ==========================================================
setlocal
title Project Scaffolding - server (Cloudflare Tunnel)
cd /d "%~dp0"

echo ============================================================
echo   Project Scaffolding - Streamlit + Cloudflare Tunnel
echo   Public https:// URL will print below. Share it to expose
echo   this app. Ctrl+C to stop the tunnel.
echo ============================================================
echo.

set PORT=8501

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

where cloudflared >nul 2>&1
if errorlevel 1 (
    echo [ERROR] cloudflared is not installed.
    echo   winget install Cloudflare.cloudflared
    echo   -- or --
    echo   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
    pause
    exit /b 1
)

echo [1/2] Starting Streamlit on port %PORT% ...
REM  Capture Streamlit's PID at spawn so the cleanup below can actually reach it.
REM  `start "title" /B` gives the child no console window of its own, so the
REM  `windowtitle eq` filter it was paired with never matched anything and
REM  Streamlit was orphaned holding %PORT% (#210). The PID is handed back through
REM  a file rather than captured stdout: cmd-side capture of an inline
REM  `powershell -Command` result is unreliable (#54).
set "PIDFILE=%TEMP%\scaffolding-streamlit-%RANDOM%%RANDOM%.pid"
del "%PIDFILE%" >nul 2>&1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%~dp0.venv\Scripts\python.exe' -ArgumentList '-m','streamlit','run','%~dp0app\app.py','--server.port','%PORT%','--server.headless','true','--browser.gatherUsageStats=false' -WorkingDirectory '%~dp0' -NoNewWindow -PassThru; Set-Content -LiteralPath '%PIDFILE%' -Value $p.Id"

set "STREAMLIT_PID="
if exist "%PIDFILE%" set /p STREAMLIT_PID=<"%PIDFILE%"
del "%PIDFILE%" >nul 2>&1

if not defined STREAMLIT_PID (
    echo [ERROR] Streamlit did not start - no process id was captured.
    echo         Not opening the tunnel: without a pid this script could not
    echo         stop Streamlit afterwards and would leave port %PORT% held.
    pause
    exit /b 1
)

timeout /t 3 /nobreak >nul

echo [2/2] Opening Cloudflare Tunnel ...
echo.
echo   Share the https:// URL printed below with anyone.
echo   Press Ctrl+C to stop the tunnel, then close this window.
echo.
cloudflared tunnel --url http://localhost:%PORT% 2>&1 | findstr /V /C:"Cannot determine default origin certificate path"

echo.
echo Stopping Streamlit, pid %STREAMLIT_PID% ...
REM  /T as well as /PID: on Python 3.14 the venv's python.exe is a launcher that
REM  re-execs the real interpreter as a child, so the captured pid is the parent
REM  of the process actually serving %PORT%.
taskkill /F /T /PID %STREAMLIT_PID% >nul 2>&1

timeout /t 1 /nobreak >nul
netstat -ano | findstr /c:":%PORT% " | findstr /c:"LISTENING" >nul
if errorlevel 1 (
    echo Server stopped - port %PORT% released.
) else (
    echo [WARN] Port %PORT% is STILL held after stopping pid %STREAMLIT_PID%.
    echo        Something is left running. Inspect it with:
    echo            netstat -ano ^| findstr :%PORT%
)
pause
