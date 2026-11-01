"""Offline language detection by Unicode script (covers English and the major Indian scripts)."""
import re

SCRIPTS = [
    ("hi", "Hindi", "हिन्दी", r"[ऀ-ॿ]"),        # Devanagari (Hindi / Marathi / Nepali)
    ("bn", "Bengali", "বাংলা", r"[ঀ-৿]"),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ", r"[਀-੿]"),
    ("gu", "Gujarati", "ગુજરાતી", r"[઀-૿]"),
    ("or", "Odia", "ଓଡ଼ିଆ", r"[଀-୿]"),
    ("ta", "Tamil", "தமிழ்", r"[஀-௿]"),
    ("te", "Telugu", "తెలుగు", r"[ఀ-౿]"),
    ("kn", "Kannada", "ಕನ್ನಡ", r"[ಀ-೿]"),
    ("ml", "Malayalam", "മലയാളം", r"[ഀ-ൿ]"),
    ("ur", "Urdu", "اردو", r"[؀-ۿ]"),
]
LANGUAGES = {"en": ("English", "English"), **{c: (n, native) for c, n, native, _ in SCRIPTS}, "mr": ("Marathi", "मराठी")}


def detect(text: str) -> dict:
    text = text or ""
    counts = {code: len(re.findall(rx, text)) for code, _, _, rx in SCRIPTS}
    latin = len(re.findall(r"[A-Za-z]", text))
    code, n = max(counts.items(), key=lambda kv: kv[1]) if counts else ("en", 0)
    if n == 0 or n < latin * 0.25:
        code = "en"
    mixed = code != "en" and latin > n * 0.3
    name, native = LANGUAGES[code]
    return {"code": code, "name": name, "native": native, "code_mixed": mixed}


def name_for(code: str) -> str:
    return LANGUAGES.get(code, ("English", "English"))[0]
