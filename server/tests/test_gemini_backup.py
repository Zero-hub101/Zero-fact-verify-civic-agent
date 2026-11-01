"""Gemini is the universal backup: with only a Gemini key, every AI job (incl. review, AI-image check, voice) works."""
import base64
import json

from PIL import Image

from app.ai import router
from app.ai.providers import gemini


def test_gemini_is_last_backup_for_every_role(monkeypatch):
    monkeypatch.setenv("AI_REVIEW", "groq")
    for role in router.ROLES:
        assert router.assigned(role)[-1] == "gemini" or "gemini" in router.assigned(role)
        assert role in gemini.GeminiProvider.roles, role
    monkeypatch.setenv("AI_UNIVERSAL_BACKUP", "")
    assert router.assigned("review") == ["groq"]


def test_gemini_review_ai_image_and_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(gemini.config, "GEMINI_API_KEY", "test")
    monkeypatch.setenv("AI_CACHE_HOURS", "0")
    replies = {
        "review": '{"verdict": "fraudulent", "authenticity": 0.1, "reasons": ["asks for a fee"]}',
        "image": '```json\n{"ai_generated": 0.9, "deepfake": null, "reason": "smooth AI texture"}\n```',
    }

    def fake_post(url, body, timeout=120):
        if "tts" in url:
            pcm = b"\x00\x01" * 2400
            return {"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}
        text = json.dumps(body)
        reply = replies["image"] if "image forensics" in text else replies["review"]
        if url.endswith("/interactions"):
            return {"outputs": [{"type": "text", "text": reply}]}
        return {"candidates": [{"content": {"parts": [{"text": reply}]}}]}

    monkeypatch.setattr(gemini, "_post", fake_post)
    p = gemini.GeminiProvider()
    rv = p.review("Pay Rs 499 fee", None)
    assert rv["verdict"] == "fraudulent" and rv["authenticity"] == 0.1
    img = tmp_path / "x.jpg"
    Image.new("RGB", (64, 64), (10, 200, 10)).save(img, "JPEG")
    det = p.detect_ai_image(img)
    assert abs(det["ai_generated"] - 0.765) < 1e-6 and det["deepfake"] is None     # scaled down: general model
    audio, ext = p.speak("नमस्ते", "hi")
    assert ext == "wav" and audio[:4] == b"RIFF"
