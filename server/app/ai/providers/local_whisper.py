"""Offline speech-to-text with Whisper (faster-whisper or openai-whisper), when installed. Role: SPEECH."""
import logging

from ..base import Provider

log = logging.getLogger("factverify.whisper")


def _engine():
    try:
        from faster_whisper import WhisperModel  # type: ignore # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass
    try:
        import whisper  # type: ignore # noqa: F401
        return "openai-whisper"
    except ImportError:
        return None


class LocalWhisperProvider(Provider):
    id = "whisper"
    name = "Whisper (offline)"
    roles = {"speech"}
    specialist_roles = {"speech"}

    def enabled(self) -> bool:
        return _engine() is not None

    def model_for(self, role: str) -> str:
        return f"{_engine()} base" if _engine() else ""

    def transcribe(self, audio_path):
        if _engine() == "faster-whisper":
            from faster_whisper import WhisperModel  # type: ignore
            segments, info = WhisperModel("base", device="cpu", compute_type="int8").transcribe(str(audio_path))
            return {"language": info.language, "transcript": " ".join(s.text.strip() for s in segments), "transcript_en": ""}
        import whisper  # type: ignore
        out = whisper.load_model("base").transcribe(str(audio_path))
        return {"language": out.get("language", ""), "transcript": out.get("text", "").strip(), "transcript_en": ""}
