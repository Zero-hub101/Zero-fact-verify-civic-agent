"""Cohere provider. Role: REVIEW (second opinion with Command models; free trial key, no credit card).

Keys: https://dashboard.cohere.com/api-keys  ->  COHERE_API_KEY  (header: Authorization: Bearer)
"""
import os

from ..base import Provider, ProviderError
from ..http import post_json
from ..review_common import build_prompt, parse


class CohereProvider(Provider):
    id = "cohere"
    name = "Cohere"
    roles = {"review"}
    specialist_roles = {"review"}

    def enabled(self) -> bool:
        return bool(os.getenv("COHERE_API_KEY"))

    def model_for(self, role: str) -> str:
        return os.getenv("COHERE_MODEL", "command-a-03-2025")

    def review(self, claim, scheme):
        r = post_json("Cohere review", "https://api.cohere.com/v2/chat",
                      {"Authorization": f"Bearer {os.getenv('COHERE_API_KEY', '')}"},
                      {"model": self.model_for("review"), "temperature": 0,
                       "messages": [{"role": "user", "content": build_prompt(claim, scheme)}]})
        blocks = ((r.get("message") or {}).get("content")) or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise ProviderError(f"Cohere: unexpected response {str(r)[:200]}")
        return parse(text, self.model_for("review"))
