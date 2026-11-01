"""Anthropic Claude provider. Specialist role: REVIEW (independent second opinion on a claim)."""
import json
import logging
import re
import urllib.request
from typing import Optional

from ... import config
from ..base import Provider

log = logging.getLogger("factverify.claude")


def claude_review(claim: str, scheme: Optional[dict]) -> Optional[dict]:
    """Optional second opinion from Claude. Returns None when no API key is configured or the call fails."""
    if not config.ANTHROPIC_API_KEY or not claim.strip():
        return None
    reference = json.dumps({k: scheme[k] for k in ("name", "summary", "benefit_amount", "benefit_period",
                                                   "application_fee", "income_limit", "deadline", "eligibility",
                                                   "official_domains")}) if scheme else "No matching scheme found."
    prompt = (
        "You are a public-service fact checker. Compare the CLAIM with the OFFICIAL RECORD. "
        "Return only JSON: {\"verdict\": \"authentic\"|\"misleading\"|\"fraudulent\"|\"unverifiable\", "
        "\"authenticity\": number 0-1, \"reasons\": [short strings]}.\n\n"
        f"OFFICIAL RECORD:\n{reference}\n\nCLAIM:\n{claim[:4000]}"
    )
    body = json.dumps({"model": config.ANTHROPIC_MODEL, "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        parsed = json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0))
        parsed["authenticity"] = max(0.0, min(1.0, float(parsed.get("authenticity", 0.5))))
        parsed["model"] = config.ANTHROPIC_MODEL
        return parsed
    except Exception as e:  # noqa: BLE001
        log.warning("Claude review failed: %s", e)
        return {"error": f"Claude review unavailable: {e.__class__.__name__}"}


class ClaudeProvider(Provider):
    id = "claude"
    name = "Anthropic Claude"
    roles = {"review"}
    specialist_roles = {"review"}

    def enabled(self) -> bool:
        return bool(config.ANTHROPIC_API_KEY)

    def model_for(self, role: str) -> str:
        return config.ANTHROPIC_MODEL

    def review(self, claim, scheme):
        return claude_review(claim, scheme)
