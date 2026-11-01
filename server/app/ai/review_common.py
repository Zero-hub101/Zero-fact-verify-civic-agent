"""Shared prompt + parsing for the REVIEW role (any chat model)."""
import json
import re
from typing import Optional

PROMPT = """You are a public-service fact checker for Indian citizens. Compare the CLAIM with the OFFICIAL RECORD.
Legitimate government schemes never ask for fees via personal UPI IDs, OTPs or WhatsApp.
Return ONLY JSON: {{"verdict": "authentic"|"misleading"|"fraudulent"|"unverifiable", "authenticity": number 0-1,
"reasons": ["short reason", "..."]}}

OFFICIAL RECORD:
{record}

CLAIM:
{claim}"""


def build_prompt(claim: str, scheme: Optional[dict]) -> str:
    keys = ("name", "summary", "benefit_amount", "benefit_period", "application_fee", "income_limit", "deadline",
            "eligibility", "official_domains")
    record = json.dumps({k: scheme[k] for k in keys if k in scheme}) if scheme else "No matching scheme found."
    return PROMPT.format(record=record, claim=claim[:4000])


def parse(text: str, model: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)     # reasoning models
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    try:
        data["authenticity"] = max(0.0, min(1.0, float(data.get("authenticity", 0.5))))
    except (TypeError, ValueError):
        data["authenticity"] = 0.5
    if data.get("verdict") not in ("authentic", "misleading", "fraudulent", "unverifiable"):
        data["verdict"] = "unverifiable"
    data["reasons"] = [str(r)[:200] for r in data.get("reasons", [])][:6]
    data["model"] = model
    return data
