"""Common interface for every AI model in FactVerify.

FactVerify runs a team of models, each doing the job it is best at:

    role          what it does                                          method
    ----------    ---------------------------------------------------   ------------------
    research      search the live web and judge a claim, with sources   research()
    translation   translate claims and write replies in the user's      translate()
                  language
    speech        turn audio in videos into text (any language)         transcribe()
    voice         read the verdict aloud in the user's language         speak()
    ocr           read printed text in images (Indian scripts too)      ocr()
    image_ai      detect AI-generated images and deepfakes              detect_ai_image()
    vision        understand an image: what it shows and claims         describe_image()
    review        independent second opinion on the claim               review()

A provider implements only the methods for roles it supports and lists them in `roles`.
Which provider fills each role is set in .env (see router.py).
"""
from pathlib import Path
from typing import Optional


class ProviderError(Exception):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class Provider:
    #: short id used in .env, e.g. AI_RESEARCH=gemini
    id: str = ""
    #: display name
    name: str = ""
    #: roles this provider can perform
    roles: set[str] = set()
    #: roles this provider is a specialist in (others are stand-in only)
    specialist_roles: set[str] = set()

    def enabled(self) -> bool:
        """True when credentials/dependencies are present."""
        return False

    def model_for(self, role: str) -> str:
        return ""

    # --- role methods (override the ones you support) ---
    def research(self, claim: str, scheme: Optional[dict], reply_lang: Optional[str]) -> dict:
        """Return {verdict, authenticity, claim_en, findings[{point,status,evidence,source_ids}], sources[{url,title,host,trust}],
        search_queries, summary, already_debunked, grounded, (summary_local, advice_local if reply_lang given)}."""
        raise NotImplementedError

    def translate(self, texts: dict[str, str], target_lang: str) -> dict[str, str]:
        """Translate each value of `texts` into target_lang (ISO 639-1). Keys are preserved."""
        raise NotImplementedError

    def transcribe(self, audio_path: Path) -> dict:
        """Return {language, transcript, transcript_en}. audio_path is a mono 16 kHz MP3."""
        raise NotImplementedError

    def review(self, claim: str, scheme: Optional[dict]) -> dict:
        """Return {verdict, authenticity, reasons[]}."""
        raise NotImplementedError

    def speak(self, text: str, lang: str) -> tuple[bytes, str]:
        """Return (audio_bytes, file_extension) of `text` spoken in lang (ISO 639-1)."""
        raise NotImplementedError

    def ocr(self, image_path: Path, lang_hint: str = "") -> dict:
        """Return {text, language}."""
        raise NotImplementedError

    def detect_ai_image(self, image_path: Path) -> dict:
        """Return {ai_generated: 0-1, deepfake: 0-1 or None}."""
        raise NotImplementedError

    def describe_image(self, image_path: Path) -> dict:
        """Return {description, text_in_image, claims[], red_flags[]}."""
        raise NotImplementedError
