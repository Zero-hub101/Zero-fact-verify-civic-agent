@echo off
REM Stops any FactVerify server on port 8000 and starts it again in auto-reload mode.
REM Output is also written to server\runtime\server.log so problems can be diagnosed.
cd /d %~dp0server
if not exist runtime mkdir runtime
echo ==== restart %date% %time% ==== > runtime\server.log
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
  echo stopping old server PID %%p >> runtime\server.log
  taskkill /F /T /PID %%p >> runtime\server.log 2>&1
)
timeout /t 2 /nobreak >nul
if not exist .venv (
  echo First run: installing. This takes a few minutes...
  python -m venv .venv >> runtime\server.log 2>&1
  call .venv\Scripts\activate
  pip install -r requirements.txt >> runtime\server.log 2>&1
  python -m playwright install chromium >> runtime\server.log 2>&1
) else (
  call .venv\Scripts\activate
)
title FactVerify server (auto-reload) - keep this window open
echo FactVerify running at http://127.0.0.1:8000  (auto-reload ON, log: server\runtime\server.log)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-dir data >> runtime\server.log 2>&1
echo Server stopped. See server\runtime\server.log
pause
