"""Groq provider. Specialist role: SPEECH (Whisper Large v3 on Groq LPUs: very fast transcription,
plus direct speech-to-English translation).

Keys: https://console.groq.com/keys  ->  GROQ_API_KEY  (header: Authorization: Bearer)
"""
import os

from ..base import Provider
from ..http import post_multipart
from ..util import to_iso1

API = "https://api.groq.com/openai/v1/audio"


class GroqProvider(Provider):
    id = "groq"
    name = "Groq (Whisper)"
    roles = {"speech"}
    specialist_roles = {"speech"}

    def enabled(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    def model_for(self, role: str) -> str:
        return os.getenv("GROQ_STT_MODEL", "whisper-large-v3")

    def transcribe(self, audio_path):
        h = {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"}
        r = post_multipart("Groq STT", f"{API}/transcriptions", h,
                           {"model": self.model_for("speech"), "response_format": "verbose_json", "temperature": "0"},
                           "file", audio_path, "audio/mpeg")
        lang = to_iso1(r.get("language") or "")
        out = {"language": lang, "transcript": (r.get("text") or "").strip(), "transcript_en": ""}
        if lang and lang != "en" and out["transcript"]:
            en = post_multipart("Groq translate", f"{API}/translations", h,
                                {"model": "whisper-large-v3", "response_format": "json", "temperature": "0"},
                                "file", audio_path, "audio/mpeg")
            out["transcript_en"] = (en.get("text") or "").strip()
        return out
