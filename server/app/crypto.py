"""AES-256-GCM encryption for citizen profile data at rest."""
import base64
import json
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config

log = logging.getLogger("factverify.crypto")
_KEY_FILE = config.RUNTIME_DIR / ".dev_encryption_key"


def _load_key() -> bytes:
    if config.ENCRYPTION_KEY:
        key = base64.b64decode(config.ENCRYPTION_KEY)
        if len(key) != 32:
            raise RuntimeError("FACTVERIFY_ENCRYPTION_KEY must be base64 of exactly 32 bytes (AES-256).")
        return key
    # Development fallback: generate a key once and keep it outside the repo.
    if _KEY_FILE.exists():
        return base64.b64decode(_KEY_FILE.read_text().strip())
    key = AESGCM.generate_key(bit_length=256)
    _KEY_FILE.write_text(base64.b64encode(key).decode())
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    log.warning("FACTVERIFY_ENCRYPTION_KEY not set; generated a development key at %s", _KEY_FILE)
    return key


_AES = AESGCM(_load_key())


def encrypt_json(data: dict) -> bytes:
    nonce = os.urandom(12)
    return nonce + _AES.encrypt(nonce, json.dumps(data).encode(), b"factverify-profile")


def decrypt_json(blob: bytes) -> dict:
    return json.loads(_AES.decrypt(blob[:12], blob[12:], b"factverify-profile"))
