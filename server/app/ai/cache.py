"""Small on-disk cache for paid AI calls (Sightengine checks, Gemini research, spoken replies).

The same image or the same claim is only sent to a paid service once per AI_CACHE_HOURS (default 24).
Repeated test runs and demos then cost no credits and come back faster. Set AI_CACHE_HOURS=0 to turn it off.
"""
import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .. import config

DIR = config.RUNTIME_DIR / "ai_cache"


def _ttl() -> float:
    try:
        return float(os.getenv("AI_CACHE_HOURS", "24")) * 3600
    except ValueError:
        return 24 * 3600


def key(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"\x00")
    return h.hexdigest()


def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get(kind: str, k: str) -> Optional[Any]:
    if _ttl() <= 0:
        return None
    p = DIR / kind / f"{k}.json"
    try:
        if time.time() - p.stat().st_mtime > _ttl():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def put(kind: str, k: str, value: Any) -> None:
    if _ttl() <= 0:
        return
    try:
        d = DIR / kind
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{k}.tmp"
        tmp.write_text(json.dumps(value, default=str), encoding="utf-8")
        os.replace(tmp, d / f"{k}.json")
    except OSError:
        pass                                    # caching is best effort


def get_bytes(kind: str, k: str) -> Optional[tuple]:
    v = get(kind, k)
    if isinstance(v, dict) and "b64" in v:
        return base64.b64decode(v["b64"]), v.get("ext", "bin")
    return None


def put_bytes(kind: str, k: str, data: bytes, ext: str) -> None:
    put(kind, k, {"b64": base64.b64encode(data).decode(), "ext": ext})
