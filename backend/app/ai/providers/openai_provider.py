"""OpenAI provider. Specialist role: VISION (understands what an image shows and claims: logos, stamps,
visible text, signs of editing). Can also act as REVIEW (second opinion) if Claude is not configured.

Keys: https://platform.openai.com/api-keys  ->  OPENAI_API_KEY
"""
import base64
import json
import os
import re

from ..base import Provider, ProviderError
from ..http import post_json
from ..util import shrink_image

API = "https://api.openai.com/v1/chat/completions"

VISION_PROMPT = """You are helping fact-check a public-service notice or social-media image for Indian citizens.
Look at the image and return ONLY JSON:
{"description": "one sentence describing the image",
 "text_in_image": "all readable text, in its original language",
 "claims": ["each factual claim the image makes (amounts, fees, deadlines, eligibility, contacts)"],
 "red_flags": ["visual signs of fraud or editing: mismatched fonts, pasted text, fake logos, personal UPI IDs, WhatsApp numbers"]}"""

REVIEW_PROMPT = """You are a public-service fact checker. Compare the CLAIM with the OFFICIAL RECORD.
Return only JSON: {{"verdict": "authentic"|"misleading"|"fraudulent"|"unverifiable", "authenticity": 0-1, "reasons": [short strings]}}

OFFICIAL RECORD:
{record}

CLAIM:
{claim}"""


def _content(r: dict) -> str:
    try:
        return r["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ProviderError(f"OpenAI: unexpected response {str(r)[:200]}")


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


class OpenAIProvider(Provider):
    id = "openai"
    name = "OpenAI"
    roles = {"vision", "review"}
    specialist_roles = {"vision"}

    def enabled(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def model_for(self, role: str) -> str:
        return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"}

    def describe_image(self, image_path):
        small = shrink_image(image_path, 1280, 3_000_000)
        try:
            b64 = base64.b64encode(small.read_bytes()).decode()
        finally:
            small.unlink(missing_ok=True)
        r = post_json("OpenAI vision", API, self._h(), {
            "model": self.model_for("vision"),
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]})
        data = _json(_content(r))
        return {"description": str(data.get("description", ""))[:400],
                "text_in_image": str(data.get("text_in_image", ""))[:3000],
                "claims": [str(c)[:300] for c in data.get("claims", [])][:10],
                "red_flags": [str(c)[:300] for c in data.get("red_flags", [])][:10]}

    def review(self, claim, scheme):
        record = json.dumps(scheme) if scheme else "No matching scheme found."
        r = post_json("OpenAI review", API, self._h(), {
            "model": self.model_for("review"),
            "messages": [{"role": "user", "content": REVIEW_PROMPT.format(record=record, claim=claim[:4000])}]})
        data = _json(_content(r))
        try:
            data["authenticity"] = max(0.0, min(1.0, float(data.get("authenticity", 0.5))))
        except (TypeError, ValueError):
            data["authenticity"] = 0.5
        data["model"] = self.model_for("review")
        return data
