"""Sarvam AI provider (India). Specialist roles: TRANSLATION (Mayura / Sarvam-Translate),
SPEECH (Saaras v3 speech-to-text) and VOICE (Bulbul v3 text-to-speech) for Indian languages.

Keys: https://dashboard.sarvam.ai  ->  SARVAM_API_KEY  (header: api-subscription-key)
"""
import base64
import os
import tempfile

from ..base import Provider, ProviderError
from ..http import post_json, post_multipart
from ..util import BCP47, split_audio, to_iso1

API = "https://api.sarvam.ai"
MAYURA_LANGS = {"en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te"}
TTS_LANGS = {"en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te"}


def _key() -> str:
    return os.getenv("SARVAM_API_KEY", "")


def _chunks(text: str, size: int) -> list[str]:
    out, cur = [], ""
    for sentence in text.replace("\n", " \n").split(". "):
        piece = sentence if sentence.endswith((".", "\n")) else sentence + ". "
        if len(cur) + len(piece) > size and cur:
            out.append(cur.strip())
            cur = ""
        cur += piece
    if cur.strip():
        out.append(cur.strip())
    return [c[:size] for c in out] or [text[:size]]


class SarvamProvider(Provider):
    id = "sarvam"
    name = "Sarvam AI"
    roles = {"translation", "speech", "voice"}
    specialist_roles = {"translation", "speech", "voice"}

    def enabled(self) -> bool:
        return bool(_key())

    def model_for(self, role: str) -> str:
        return {"translation": "mayura:v1 / sarvam-translate:v1", "speech": os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
                "voice": os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")}.get(role, "")

    def _h(self) -> dict:
        return {"api-subscription-key": _key()}

    def translate(self, texts, target_lang):
        target = to_iso1(target_lang)
        if target not in BCP47:
            raise ProviderError(f"Sarvam: unsupported target language '{target_lang}'")
        model = "mayura:v1" if target in MAYURA_LANGS else "sarvam-translate:v1"
        limit = 900 if model == "mayura:v1" else 1900
        out = {}
        for k, v in texts.items():
            if not str(v).strip():
                out[k] = v
                continue
            parts = []
            for chunk in _chunks(str(v), limit):
                body = {"input": chunk, "source_language_code": "auto", "target_language_code": BCP47[target],
                        "model": model}
                if model == "mayura:v1":
                    body["mode"] = "formal"
                r = post_json("Sarvam translate", f"{API}/translate", self._h(), body)
                parts.append(r.get("translated_text", ""))
            out[k] = " ".join(p for p in parts if p)
        return out

    def transcribe(self, audio_path):
        # The real-time REST endpoint accepts up to 30 s per request, so long audio is sent in chunks.
        texts, lang = [], ""
        with tempfile.TemporaryDirectory() as tmp:
            for part in split_audio(audio_path, 29, 20, tmp):
                r = post_multipart("Sarvam STT", f"{API}/speech-to-text", self._h(),
                                   {"model": self.model_for("speech"), "mode": "transcribe"},
                                   "file", part, "audio/mpeg")
                texts.append(r.get("transcript", ""))
                lang = lang or to_iso1(r.get("language_code") or "")
        return {"language": lang, "transcript": " ".join(t for t in texts if t).strip(), "transcript_en": ""}

    def speak(self, text, lang):
        code = to_iso1(lang)
        if code not in TTS_LANGS:
            raise ProviderError(f"Sarvam TTS: language '{lang}' not supported")
        r = post_json("Sarvam TTS", f"{API}/text-to-speech", self._h(), {
            "text": text[:1400], "target_language_code": BCP47[code],
            "speaker": os.getenv("SARVAM_TTS_SPEAKER", "shubh"), "model": self.model_for("voice")})
        audios = r.get("audios") or []
        if not audios:
            raise ProviderError("Sarvam TTS returned no audio")
        return base64.b64decode("".join(audios)), "wav"
