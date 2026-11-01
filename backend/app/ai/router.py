"""Routes each AI role to the model assigned to it in .env.

    AI_RESEARCH=gemini            live web research with sources
    AI_TRANSLATION=gemini         language communication (claims in, replies out)
    AI_SPEECH=whisper,gemini      audio in videos -> text
    AI_REVIEW=claude              independent second opinion

A comma-separated list is an order of preference: the first provider that is enabled
(has its key / package) and supports the role is used. Leave a role empty to switch it off.
To add a model, see app/ai/providers/_template.py.
"""
import logging
import os
import time
from typing import Any, Callable, Optional

from .base import Provider, ProviderError
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider
from .providers.local_whisper import LocalWhisperProvider

log = logging.getLogger("factverify.router")

PROVIDERS: dict[str, Provider] = {p.id: p for p in (GeminiProvider(), ClaudeProvider(), LocalWhisperProvider())}

ROLES = {
    "research": ("AI_RESEARCH", "gemini", "Live web research with sources"),
    "translation": ("AI_TRANSLATION", "gemini", "Language communication"),
    "speech": ("AI_SPEECH", "whisper,gemini", "Speech to text"),
    "review": ("AI_REVIEW", "claude", "Independent second opinion"),
}


def register(provider: Provider) -> None:
    """Add a provider at runtime (used by plugins and tests)."""
    PROVIDERS[provider.id] = provider


def assigned(role: str) -> list[str]:
    env, default, _ = ROLES[role]
    return [x.strip() for x in os.getenv(env, default).split(",") if x.strip()]


def get(role: str) -> Optional[Provider]:
    for pid in assigned(role):
        p = PROVIDERS.get(pid)
        if p and role in p.roles and p.enabled():
            return p
    return None


def call(role: str, method: Callable[[Provider], Any]) -> tuple[Any, Optional[dict]]:
    """Run `method(provider)` on the provider for `role`. Returns (result, credit) or (None, None)."""
    p = get(role)
    if not p:
        return None, None
    t0 = time.time()
    credit = {"role": role, "provider": p.id, "name": p.name, "model": p.model_for(role),
              "specialist": role in p.specialist_roles}
    try:
        result = method(p)
        credit["seconds"] = round(time.time() - t0, 1)
        if isinstance(result, dict) and result.get("error"):
            credit["error"] = result["error"]
        return result, credit
    except (ProviderError, NotImplementedError, OSError, ValueError) as e:
        log.warning("%s via %s failed: %s", role, p.id, e)
        credit["error"] = str(e)[:300]
        credit["seconds"] = round(time.time() - t0, 1)
        return {"error": f"{p.name} ({role}) failed: {str(e)[:200]}"}, credit


def lineup() -> list[dict]:
    out = []
    for role, (env, _, label) in ROLES.items():
        p = get(role)
        out.append({
            "role": role, "label": label, "env": env, "assigned": assigned(role),
            "active": p.id if p else None, "name": p.name if p else None,
            "model": p.model_for(role) if p else None,
            "specialist": bool(p and role in p.specialist_roles),
            "status": "off" if not p else ("specialist" if role in p.specialist_roles else "stand-in"),
        })
    return out
