@echo off
REM One-time setup and start for Windows. Requires Python 3.10+.
cd /d %~dp0server
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r requirements.txt
  python -m playwright install chromium
) else (
  call .venv\Scripts\activate
)
echo.
echo FactVerify running at http://127.0.0.1:8000
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
