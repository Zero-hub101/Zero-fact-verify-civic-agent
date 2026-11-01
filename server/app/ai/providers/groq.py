"""Groq provider (free tier). Specialist role: SPEECH (Whisper Large v3 on Groq LPUs: very fast
transcription, plus direct speech-to-English translation). Also stands in for REVIEW and TRANSLATION
with an open chat model (openai/gpt-oss-120b by default) using the same key.

Keys: https://console.groq.com/keys  ->  GROQ_API_KEY  (header: Authorization: Bearer)
"""
import json
import os
import re

from ..base import Provider
from ..base import ProviderError
from ..http import post_json, post_multipart
from ..review_common import build_prompt, parse
from ..util import to_iso1

API = "https://api.groq.com/openai/v1/audio"


class GroqProvider(Provider):
    id = "groq"
    name = "Groq (Whisper)"
    roles = {"speech", "review", "translation"}
    specialist_roles = {"speech"}

    def enabled(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    def model_for(self, role: str) -> str:
        if role in ("review", "translation"):
            return os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
        return os.getenv("GROQ_STT_MODEL", "whisper-large-v3")

    def _chat(self, prompt: str) -> str:
        r = post_json("Groq chat", "https://api.groq.com/openai/v1/chat/completions",
                      {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"},
                      {"model": self.model_for("review"), "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]})
        try:
            return r["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Groq chat: unexpected response {str(r)[:200]}")

    def review(self, claim, scheme):
        return parse(self._chat(build_prompt(claim, scheme)), self.model_for("review"))

    def translate(self, texts, target_lang):
        from ...forensics.language import name_for
        prompt = (f"Translate every value in this JSON object into {name_for(target_lang)}. Keep the keys unchanged. "
                  "Use simple words a citizen understands; keep numbers, amounts, URLs and names exact. "
                  f"Return ONLY the JSON object.\n\n{json.dumps(texts, ensure_ascii=False)}")
        text = re.sub(r"<think>.*?</think>", "", self._chat(prompt), flags=re.DOTALL)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            out = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            out = {}
        return {k: str(out.get(k) or v) for k, v in texts.items()}

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
