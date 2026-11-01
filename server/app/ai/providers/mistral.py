"""Mistral AI provider. Role: REVIEW (free second opinion on the free Experiment plan, no credit card).

Keys: https://console.mistral.ai/api-keys  ->  MISTRAL_API_KEY  (header: Authorization: Bearer)
Note: on the free plan Mistral may use requests to improve its models, so citizen data is never sent:
only the claim text and the official scheme record.
"""
import os

from ..base import Provider, ProviderError
from ..http import post_json
from ..review_common import build_prompt, parse


class MistralProvider(Provider):
    id = "mistral"
    name = "Mistral AI"
    roles = {"review"}
    specialist_roles = {"review"}

    def enabled(self) -> bool:
        return bool(os.getenv("MISTRAL_API_KEY"))

    def model_for(self, role: str) -> str:
        return os.getenv("MISTRAL_MODEL", "mistral-small-latest")

    def review(self, claim, scheme):
        r = post_json("Mistral review", "https://api.mistral.ai/v1/chat/completions",
                      {"Authorization": f"Bearer {os.getenv('MISTRAL_API_KEY', '')}"},
                      {"model": self.model_for("review"), "temperature": 0,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "user", "content": build_prompt(claim, scheme)}]})
        try:
            text = r["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Mistral: unexpected response {str(r)[:200]}")
        return parse(text if isinstance(text, str) else str(text), self.model_for("review"))
