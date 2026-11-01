"""Runtime configuration, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # server/
DATA_DIR = BASE_DIR / "data"
RUNTIME_DIR = Path(os.getenv("FACTVERIFY_RUNTIME_DIR", BASE_DIR / "runtime"))
UPLOAD_DIR = RUNTIME_DIR / "uploads"
ARTIFACT_DIR = RUNTIME_DIR / "artifacts"                    # heatmaps, screenshots, receipts
DB_PATH = Path(os.getenv("FACTVERIFY_DB_PATH", RUNTIME_DIR / "factverify.db"))
CLIENT_DIST = BASE_DIR.parent / "client" / "dist"


def _load_dotenv() -> None:
    """Minimal .env loader so the app runs without python-dotenv. Tests set FACTVERIFY_SKIP_DOTENV=1."""
    if os.getenv("FACTVERIFY_SKIP_DOTENV") == "1":
        return
    for candidate in (BASE_DIR / ".env", BASE_DIR.parent / ".env", BASE_DIR.parent / "factverify.env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

ENCRYPTION_KEY = os.getenv("FACTVERIFY_ENCRYPTION_KEY", "")          # base64, 32 bytes
API_TOKEN = os.getenv("FACTVERIFY_API_TOKEN", "")                     # optional auth for /api
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-4-argon")                    # flagship reasoning model
GEMINI_FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.8-flash,gemini-2.5-pro")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-3.8-flash")       # audio transcription
PUBLIC_BASE_URL = os.getenv("FACTVERIFY_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
AGENT_HEADLESS = os.getenv("AGENT_HEADLESS", "true").lower() != "false"
AUTHENTICITY_THRESHOLD = float(os.getenv("AUTHENTICITY_THRESHOLD", "0.75"))
MAX_AGENT_STEPS = 10
STEP_TIMEOUT_MS = int(os.getenv("AGENT_STEP_TIMEOUT_MS", "15000"))
HUMAN_WAIT_SECONDS = int(os.getenv("AGENT_HUMAN_WAIT_SECONDS", "900"))
RETENTION_HOURS = float(os.getenv("PROFILE_RETENTION_HOURS", "24"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
ALLOW_URL_FETCH = os.getenv("ALLOW_URL_FETCH", "true").lower() != "false"

for d in (RUNTIME_DIR, UPLOAD_DIR, ARTIFACT_DIR):
    d.mkdir(parents=True, exist_ok=True)
