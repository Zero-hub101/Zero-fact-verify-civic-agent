"""Turn a verdict into short, everyday words for a citizen: what it is, why, and what to do.

The technical details (scores, forensics, model names) stay in the result for fact-checkers; this is the part
an ordinary person reads first. Sentences are short and avoid jargon on purpose.
"""
import hashlib
from typing import Optional

# A few equally simple phrasings, so answers don't feel copy-pasted. The choice is fixed per message
# (same message -> same wording), so results stay consistent and reproducible.
HEADLINES = {
    "authentic": ["This looks genuine.", "Good news: this looks real.", "This matches the official scheme. It looks genuine."],
    "unverified": ["We could not confirm this. Be careful.", "We are not sure about this one. Please check before you act.",
                   "We could not prove this is real. Go carefully."],
    "likely_fraudulent": ["This looks like a scam. Do not act on it.", "Careful: this looks like a scam. Please do not act on it.",
                          "This has the signs of a scam. Do not pay or share anything."],
    "off_topic": ["This does not look like a message about a government scheme.",
                  "This doesn't seem to be about a government scheme or benefit."],
}
HEADLINE = {k: v[0] for k, v in HEADLINES.items()}
CLOSERS = {
    "likely_fraudulent": ["Stay safe, and feel free to share this check with your family.",
                          "When in doubt, ask a family member or visit an official office before acting.", ""],
    "authentic": ["Good luck with your application!", "Keep your documents ready before you apply.", ""],
}


def _pick(options: list[str], seed: str, salt: str) -> str:
    if not options:
        return ""
    h = int(hashlib.sha256(f"{salt}|{seed}".encode()).hexdigest(), 16)
    return options[h % len(options)]

# Why: one plain line per warning sign (by rule id).
WHY_FLAG = {
    "upfront_fee": "It asks you to pay money first. Real government schemes do not charge you to get a benefit.",
    "otp_request": "It asks for your OTP, PIN or password. No real officer will ever ask for these.",
    "personal_payment": "It asks you to send money to a personal UPI ID or phone number, not an official account.",
    "messaging_channel": "It tells you to apply through WhatsApp or Telegram. Real schemes use official websites.",
    "false_urgency": "It rushes you (\"only 24 hours\", \"hurry\"). Scammers do this so you don't stop to check.",
    "guaranteed": "It promises money to everyone or with no documents. Real schemes have rules about who can apply.",
    "share_forward": "It asks you to forward it to many groups. Hoaxes spread this way.",
    "shortened_link": "It uses a shortened link that hides where it really goes.",
    "sensitive_documents": "It asks you to send Aadhaar or bank details on chat. Never share these over chat.",
    "lookalike_domain": "The link only looks like a government website. Its address is not a real government address.",
}
WHY_FACT = {
    "application_fee": "The real scheme is free to apply for, but this message asks for a fee.",
    "benefit_amount": "The amount of money it promises does not match the real scheme.",
    "income_limit": "The income limit it mentions does not match the real scheme.",
    "deadline": "The last date it mentions does not match the official date.",
}


def build(verdict: str, scheme: Optional[dict], text_result: dict, media_results: list[dict],
          found: Optional[dict], deepfake: bool, seed: str = "") -> dict:
    why: list[str] = []
    for c in text_result.get("contradictions") or []:
        line = WHY_FACT.get(c.get("field"))
        if line and line not in why:
            why.append(line)
    for f in text_result.get("scam_flags") or []:
        line = WHY_FLAG.get(f.get("id"))
        if line and line not in why:
            why.append(line)
    if deepfake:
        why.insert(0, "The picture or video looks edited or made by AI.")
    elif any((m.get("tamper_score") or 0) >= 0.6 for m in media_results):
        why.insert(0, "Part of the picture or video looks edited (something was pasted in or changed).")
    if found and found.get("verdict") == "fraudulent" and len(why) < 2:
        why.append("Our AI research also found that this claim is false.")

    if verdict == "authentic":
        if scheme:
            why = [f"It matches the official {scheme['name']}."] + why
            if (text_result.get("confirmations") or []):
                why.append("The amounts and rules in the message match the official record.")
        why.append("We found no warning signs such as fees, OTP requests or fake links.")
    if verdict == "unverified" and not why:
        why.append("We could not match it to an official scheme or find enough proof either way.")

    do: list[str]
    official = (scheme or {}).get("official_url") or (
        f"https://{scheme['official_domains'][0]}" if scheme and scheme.get("official_domains") else "")
    site = official.replace("https://", "").replace("http://", "").rstrip("/")
    if verdict == "likely_fraudulent":
        do = ["Do not pay any money and do not share any OTP, PIN or documents.",
              "Do not click links in the message or forward it to others."]
        do.append(f"If you want this benefit, apply only on {site}." if site else
                  "Check the scheme only on an official government website (ending in .gov.in).")
        do.append("If you already paid or shared details, call the cyber crime helpline 1930 or report at cybercrime.gov.in.")
    elif verdict == "unverified":
        do = ["Do not pay or share personal details until you confirm it.",
              f"Check it yourself on {site}." if site else
              "Check it on an official government website (ending in .gov.in) or ask at a government office."]
    elif verdict == "authentic":
        do = [f"Apply only on the official website: {site}." if site else "Apply only through the official website.",
              "You never have to pay anyone or share your OTP to apply."]
    else:
        do = ["Paste a message, link, picture or video about a government scheme, benefit, fee or official notice."]

    closer = _pick(CLOSERS.get(verdict, []), seed, "closer")
    if closer:
        do.append(closer)
    headline = _pick(HEADLINES.get(verdict, HEADLINES["unverified"]), seed, "headline")
    return {"headline": headline, "why": why[:4], "do": do}
