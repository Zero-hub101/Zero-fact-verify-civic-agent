"""ElevenLabs provider. Specialist roles: VOICE (multilingual text-to-speech) and SPEECH (Scribe speech-to-text).

Keys: https://elevenlabs.io/app/settings/api-keys  ->  ELEVENLABS_API_KEY  (header: xi-api-key)
"""
import os

from ..base import Provider, ProviderError
from ..http import post_bytes, post_multipart
from ..util import to_iso1

API = "https://api.elevenlabs.io/v1"


class ElevenLabsProvider(Provider):
    id = "elevenlabs"
    name = "ElevenLabs"
    roles = {"voice", "speech"}
    specialist_roles = {"voice", "speech"}

    def enabled(self) -> bool:
        return bool(os.getenv("ELEVENLABS_API_KEY"))

    def model_for(self, role: str) -> str:
        return os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2") if role == "voice" \
            else os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2")

    def _h(self) -> dict:
        return {"xi-api-key": os.getenv("ELEVENLABS_API_KEY", "")}

    def speak(self, text, lang):
        voice = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
        audio = post_bytes("ElevenLabs TTS", f"{API}/text-to-speech/{voice}?output_format=mp3_44100_128",
                           {**self._h(), "Accept": "audio/mpeg"},
                           {"text": text[:2500], "model_id": self.model_for("voice")})
        if len(audio) < 500:
            raise ProviderError("ElevenLabs TTS returned no audio")
        return audio, "mp3"

    def transcribe(self, audio_path):
        r = post_multipart("ElevenLabs STT", f"{API}/speech-to-text", self._h(),
                           {"model_id": self.model_for("speech")}, "file", audio_path, "audio/mpeg", timeout=180)
        return {"language": to_iso1(r.get("language_code") or ""), "transcript": (r.get("text") or "").strip(),
                "transcript_en": ""}
