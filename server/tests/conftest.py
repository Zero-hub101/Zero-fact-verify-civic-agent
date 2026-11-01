"""Test setup: an isolated runtime folder and a live API server on a free port."""
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="factverify_test_")
_sock = socket.socket()
_sock.bind(("127.0.0.1", 0))
PORT = _sock.getsockname()[1]
_sock.close()

os.environ["FACTVERIFY_SKIP_DOTENV"] = "1"          # never use real API keys in tests
for _k in [k for k in os.environ if k.endswith(("_API_KEY", "_API_USER", "_API_SECRET"))]:
    os.environ.pop(_k)
os.environ["FACTVERIFY_RUNTIME_DIR"] = _tmp
os.environ["FACTVERIFY_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["FACTVERIFY_API_TOKEN"] = ""
os.environ["AGENT_STEP_TIMEOUT_MS"] = "8000"
os.environ["ALLOW_URL_FETCH"] = "false"
os.environ["AI_CACHE_HOURS"] = "0"                # every test sees fresh AI calls
os.environ["RATE_LIMIT_PER_10MIN"] = "100000"
os.environ["RATE_LIMIT_PER_MIN"] = "100000"


@pytest.fixture(scope="session")
def demo_media():
    media = ROOT / "demo" / "media"
    if not (media / "tampered_notice.jpg").exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "demo" / "make_demo_media.py")], check=True)
    return media


@pytest.fixture(scope="session")
def server(demo_media):
    import uvicorn
    from app.main import app

    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{PORT}"
    srv.should_exit = True
    t.join(timeout=5)
