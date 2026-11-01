"""Ollama provider: a free AI model running on your own laptop. No account, no API key, works offline.
Role: REVIEW (second opinion).

Setup: install from https://ollama.com/download, then run once:  ollama pull qwen3:8b
(smaller laptops: OLLAMA_MODEL=qwen3:4b or llama3.2:3b). The app finds it automatically at localhost:11434.
"""
import os
import time

import requests

from ..base import Provider, ProviderError
from ..review_common import build_prompt, parse

_cache = {"t": 0.0, "ok": False}


def _base() -> str:
    return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


class OllamaProvider(Provider):
    id = "ollama"
    name = "Ollama (local)"
    roles = {"review"}
    specialist_roles = {"review"}

    def enabled(self) -> bool:
        if time.time() - _cache["t"] < 30:
            return _cache["ok"]
        try:
            tags = requests.get(f"{_base()}/api/tags", timeout=0.8).json()
            want = self.model_for("review").split(":")[0]
            ok = any(m.get("name", "").split(":")[0] == want for m in tags.get("models", []))
        except (requests.RequestException, ValueError):
            ok = False
        _cache.update(t=time.time(), ok=ok)
        return ok

    def model_for(self, role: str) -> str:
        return os.getenv("OLLAMA_MODEL", "qwen3:8b")

    def review(self, claim, scheme):
        try:
            r = requests.post(f"{_base()}/api/chat", timeout=180, json={
                "model": self.model_for("review"), "stream": False, "format": "json",
                "messages": [{"role": "user", "content": build_prompt(claim, scheme)}]})
        except requests.RequestException as e:
            raise ProviderError(f"Ollama not reachable: {e}")
        if r.status_code >= 400:
            raise ProviderError(f"Ollama HTTP {r.status_code}: {r.text[:200]}", r.status_code)
        return parse((r.json().get("message") or {}).get("content", ""), self.model_for("review"))
