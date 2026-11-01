"""TEMPLATE - copy this file to add a new AI model to the FactVerify team.

Example: a specialist for Indian-language speech and translation.

1. Copy to app/ai/providers/<name>.py and fill in the methods for the roles it supports.
2. Register it in app/ai/router.py -> PROVIDERS.
3. Assign it in .env, e.g.:   AI_SPEECH=<id>   AI_TRANSLATION=<id>
4. Add its API key variable to .env.example.

Nothing else changes: the pipeline, dashboard and reports pick it up automatically.
Return shapes are documented in app/ai/base.py.
"""
import os

from ..base import Provider, ProviderError  # noqa: F401


class ExampleProvider(Provider):
    id = "example"                      # value used in .env
    name = "Example Model"
    roles = {"translation", "speech"}   # roles it can do
    specialist_roles = {"translation", "speech"}

    def enabled(self) -> bool:
        return bool(os.getenv("EXAMPLE_API_KEY"))

    def model_for(self, role: str) -> str:
        return "example-model-v1"

    def translate(self, texts, target_lang):
        # call the API; return {key: translated_text} with the same keys
        raise NotImplementedError

    def transcribe(self, audio_path):
        # audio_path is a mono 16 kHz MP3; return {"language": "hi", "transcript": "...", "transcript_en": "..."}
        raise NotImplementedError
