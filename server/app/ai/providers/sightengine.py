"""Sightengine provider. Specialist role: IMAGE_AI (detects fully AI-generated images such as Midjourney,
DALL-E, Stable Diffusion, Flux output, and optionally face deepfakes).

Keys: https://sightengine.com (sign up -> dashboard -> API keys)  ->  SIGHTENGINE_API_USER + SIGHTENGINE_API_SECRET
"""
import os

from .. import cache
from ..base import Provider, ProviderError
from ..http import post_multipart
from ..util import shrink_image


class SightengineProvider(Provider):
    id = "sightengine"
    name = "Sightengine"
    roles = {"image_ai"}
    specialist_roles = {"image_ai"}

    def enabled(self) -> bool:
        return bool(os.getenv("SIGHTENGINE_API_USER") and os.getenv("SIGHTENGINE_API_SECRET"))

    def model_for(self, role: str) -> str:
        return os.getenv("SIGHTENGINE_MODELS", "genai")      # add ",deepfake" if your plan includes it

    def detect_ai_image(self, image_path):
        ck = cache.key("sightengine", self.model_for("image_ai"), cache.file_hash(image_path))
        hit = cache.get("image_ai", ck)
        if hit is not None:
            return {**hit, "cached": True}
        small = shrink_image(image_path, 1600, 4_000_000)
        try:
            r = post_multipart("Sightengine", "https://api.sightengine.com/1.0/check.json", {},
                               {"models": self.model_for("image_ai"), "api_user": os.getenv("SIGHTENGINE_API_USER", ""),
                                "api_secret": os.getenv("SIGHTENGINE_API_SECRET", "")},
                               "media", small, "image/jpeg")
        finally:
            small.unlink(missing_ok=True)
        if r.get("status") != "success":
            raise ProviderError(f"Sightengine: {(r.get('error') or {}).get('message', r)}")
        t = r.get("type") or {}
        out = {"ai_generated": t.get("ai_generated"), "deepfake": t.get("deepfake")}
        cache.put("image_ai", ck, out)
        return out
