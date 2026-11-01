#!/usr/bin/env bash
# One-time setup and start for macOS / Linux. Requires Python 3.10+.
set -e
cd "$(dirname "$0")/server"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt
  python -m playwright install chromium
else
  . .venv/bin/activate
fi
echo "FactVerify running at http://127.0.0.1:8000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
