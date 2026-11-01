"""Routes each AI role to the model assigned to it in .env.

    AI_RESEARCH=gemini                                  live web research with sources
    AI_TRANSLATION=sarvam,gemini                        language communication (claims in, replies out)
    AI_SPEECH=sarvam,groq,elevenlabs,whisper,gemini     audio in videos -> text
    AI_VOICE=sarvam,elevenlabs                          verdict read aloud in the user's language
    AI_OCR=ocrspace,tesseract,gemini                    text printed in images
    AI_IMAGE_AI=localdetector,sightengine               AI-generated image detection (free local model first)
    AI_VISION=openai,gemini                             what an image shows and claims
    AI_REVIEW=mistral,cohere,ollama,claude,openai       independent second opinion (free options first)

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
from .providers.cohere import CohereProvider
from .providers.elevenlabs import ElevenLabsProvider
from .providers.gemini import GeminiProvider
from .providers.groq import GroqProvider
from .providers.local_ai_detector import LocalAiDetectorProvider
from .providers.local_tesseract import TesseractProvider
from .providers.local_whisper import LocalWhisperProvider
from .providers.mistral import MistralProvider
from .providers.ocrspace import OcrSpaceProvider
from .providers.ollama import OllamaProvider
from .providers.openai_provider import OpenAIProvider
from .providers.sarvam import SarvamProvider
from .providers.sightengine import SightengineProvider

log = logging.getLogger("factverify.router")

PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    GeminiProvider(), SarvamProvider(), ElevenLabsProvider(), GroqProvider(), SightengineProvider(),
    OcrSpaceProvider(), OpenAIProvider(), MistralProvider(), CohereProvider(), OllamaProvider(), ClaudeProvider(),
    LocalWhisperProvider(), TesseractProvider(), LocalAiDetectorProvider())}

ROLES = {
    "research": ("AI_RESEARCH", "gemini", "Live web research with sources"),
    "translation": ("AI_TRANSLATION", "sarvam,gemini,groq", "Language communication"),
    "speech": ("AI_SPEECH", "sarvam,groq,elevenlabs,whisper,gemini", "Speech to text"),
    "voice": ("AI_VOICE", "sarvam,elevenlabs", "Spoken reply (text to speech)"),
    "ocr": ("AI_OCR", "ocrspace,tesseract,gemini", "Text in images"),
    "image_ai": ("AI_IMAGE_AI", "localdetector,sightengine", "AI-generated image & deepfake detection"),
    "vision": ("AI_VISION", "openai,gemini", "Image understanding"),
    "review": ("AI_REVIEW", "mistral,cohere,ollama,groq,claude,openai", "Independent second opinion"),
}


def register(provider: Provider) -> None:
    """Add a provider at runtime (used by plugins and tests)."""
    PROVIDERS[provider.id] = provider


def assigned(role: str) -> list[str]:
    """Providers for a role, in order. Gemini is always added last as the universal backup (AI_UNIVERSAL_BACKUP),
    so with only a Gemini key every job still has an AI behind it."""
    env, default, _ = ROLES[role]
    out = [x.strip() for x in os.getenv(env, default).split(",") if x.strip()]
    backup = os.getenv("AI_UNIVERSAL_BACKUP", "gemini").strip()
    if backup and backup not in out:
        out.append(backup)
    return out


def get(role: str) -> Optional[Provider]:
    c = candidates(role)
    return c[0] if c else None


def candidates(role: str) -> list[Provider]:
    out = []
    for pid in assigned(role):
        p = PROVIDERS.get(pid)
        if p and role in p.roles and p.enabled():
            out.append(p)
    return out


def call(role: str, method: Callable[[Provider], Any]) -> tuple[Any, Optional[dict]]:
    """Run `method(provider)` for `role`, trying each configured provider in order until one succeeds.

    Returns (result, credit). If every provider fails, returns ({"error": ...}, credit of the last attempt)
    and the earlier failures are listed in credit["failed"]."""
    failed: list[dict] = []
    for p in candidates(role):
        t0 = time.time()
        credit = {"role": role, "provider": p.id, "name": p.name, "model": p.model_for(role),
                  "specialist": role in p.specialist_roles}
        try:
            result = method(p)
            err = result.get("error") if isinstance(result, dict) else None
        except Exception as e:  # noqa: BLE001 - one model failing must never break the audit
            result, err = None, str(e)
        credit["seconds"] = round(time.time() - t0, 1)
        if not err:
            if failed:
                credit["fallback_from"] = [f["provider"] for f in failed]
            return result, credit
        log.warning("%s via %s failed: %s", role, p.id, err)
        failed.append({"provider": p.id, "name": p.name, "error": short_error(err)})
    if not failed:
        return None, None
    last = failed[-1]
    credit = {"role": role, "provider": last["provider"], "name": last["name"], "model": "", "specialist": False,
              "error": last["error"], "failed": failed}
    names = ", ".join(f"{f['name']} ({f['error']})" for f in failed)
    return {"error": f"No AI service available for {role}: {names}"}, credit


def short_error(msg: str) -> str:
    """Turn raw provider errors into one readable line (shown to users and in reports)."""
    m = msg.lower()
    if "missing the permission" in m or "missing_permissions" in m:
        return "API key lacks permission for this feature (edit the key's permissions)"
    if "credit" in m or "insufficient_quota" in m or "quota" in m:
        return "out of credits or quota"
    if " 401" in m or " 403" in m or "api key not valid" in m or "invalid_api_key" in m or "e555" in m:
        return "API key rejected (check the key in your settings file)"
    if " 429" in m or "rate limit" in m:
        return "rate limited, try again in a minute"
    if " 404" in m or "not found" in m:
        return "model not found (check the model name setting)"
    if "network" in m or "timed out" in m or "timeout" in m:
        return "network problem or timeout"
    return msg.split("\n")[0][:160]


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
