"""All AI providers with their HTTP calls mocked: request format, response parsing, and the full pipeline
using every role at once (research, translation, speech, voice, ocr, image_ai, vision, review)."""
import base64
import json
from pathlib import Path

import pytest

from app import config, pipeline
from app.ai import http, router
from app.ai.providers import elevenlabs, gemini, groq, ocrspace, openai_provider, sarvam, sightengine
from tests.test_research import HINDI, _interactions_response

KEYS = {"SARVAM_API_KEY": "s", "ELEVENLABS_API_KEY": "e", "GROQ_API_KEY": "g", "SIGHTENGINE_API_USER": "u",
        "SIGHTENGINE_API_SECRET": "x", "OCR_SPACE_API_KEY": "o", "OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": ""}
WAV = base64.b64encode(b"RIFF" + b"\0" * 2000).decode()


class FakeResp:
    def __init__(self, payload=None, content=b"", status=200):
        self._p, self.content, self.status_code = payload, content, status
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._p


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def post(url, headers=None, data=None, files=None, params=None, timeout=None):
        body = json.loads(data) if isinstance(data, str) else (data or {})
        calls.append({"url": url, "headers": headers or {}, "body": body, "files": files})
        if "sarvam.ai/translate" in url:
            return FakeResp({"translated_text": f"[{body['target_language_code']}] {body['input'][:40]}"})
        if "sarvam.ai/speech-to-text" in url:
            return FakeResp({"transcript": "नमस्ते", "language_code": "hi-IN"})
        if "sarvam.ai/text-to-speech" in url:
            return FakeResp({"audios": [WAV]})
        if "elevenlabs.io/v1/text-to-speech" in url:
            return FakeResp(content=b"ID3" + b"\0" * 2000)
        if "elevenlabs.io/v1/speech-to-text" in url:
            return FakeResp({"text": "hello", "language_code": "hin"})
        if "groq.com" in url and "transcriptions" in url:
            return FakeResp({"text": "नमस्ते", "language": "hindi"})
        if "groq.com" in url and "translations" in url:
            return FakeResp({"text": "Hello"})
        if "sightengine" in url:
            return FakeResp({"status": "success", "type": {"ai_generated": 0.93}})
        if "ocr.space" in url:
            return FakeResp({"IsErroredOnProcessing": False, "ParsedResults": [{"ParsedText": "पोस्ट मैट्रिक ₹50,000"}]})
        if "openai.com" in url:
            content = json.dumps({"description": "A scholarship notice", "text_in_image": "Scholarship Rs 50,000",
                                  "claims": ["Rs 50,000 for all"], "red_flags": ["personal UPI ID"]})
            return FakeResp({"choices": [{"message": {"content": content}}]})
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(http.requests, "post", post)
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    return calls


def test_sarvam_translate_tts_stt(fake_http, tmp_path):
    p = sarvam.SarvamProvider()
    out = p.translate({"a": "Hello there."}, "ta")
    assert out["a"].startswith("[ta-IN]")
    c = fake_http[-1]
    assert c["headers"]["api-subscription-key"] == "s" and c["body"]["model"] == "mayura:v1"
    audio, ext = p.speak("नमस्ते", "hi")
    assert ext == "wav" and audio.startswith(b"RIFF")
    assert fake_http[-1]["body"]["target_language_code"] == "hi-IN" and fake_http[-1]["body"]["model"] == "bulbul:v3"
    f = tmp_path / "a.mp3"
    f.write_bytes(b"\0" * 3000)
    tr = p.transcribe(f)
    assert tr["language"] == "hi" and tr["transcript"] == "नमस्ते"
    assert fake_http[-1]["body"]["model"] == "saaras:v3"


def test_sarvam_urdu_uses_sarvam_translate(fake_http):
    sarvam.SarvamProvider().translate({"a": "Hello"}, "ur")
    assert fake_http[-1]["body"]["model"] == "sarvam-translate:v1"


def test_elevenlabs_and_groq(fake_http, tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"\0" * 3000)
    audio, ext = elevenlabs.ElevenLabsProvider().speak("hi", "hi")
    assert ext == "mp3" and fake_http[-1]["body"]["model_id"] == "eleven_multilingual_v2"
    assert elevenlabs.ElevenLabsProvider().transcribe(f)["language"] == "hi"
    g = groq.GroqProvider().transcribe(f)
    assert g == {"language": "hi", "transcript": "नमस्ते", "transcript_en": "Hello"}
    assert fake_http[-1]["headers"]["Authorization"] == "Bearer g"


def test_image_roles(fake_http, demo_media):
    img = demo_media / "tampered_notice.jpg"
    assert sightengine.SightengineProvider().detect_ai_image(img)["ai_generated"] == 0.93
    assert fake_http[-1]["body"]["models"] == "genai"
    o = ocrspace.OcrSpaceProvider().ocr(img, "hi")
    assert o["text"] and fake_http[-1]["body"]["language"] == "hin" and fake_http[-1]["body"]["OCREngine"] == "3"
    v = openai_provider.OpenAIProvider().describe_image(img)
    assert v["red_flags"] == ["personal UPI ID"]


def test_full_team_pipeline(fake_http, demo_media, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gm")
    monkeypatch.setattr(gemini, "_post", lambda url, body, timeout=120: _interactions_response())
    up = config.UPLOAD_DIR / "team_test.jpg"
    up.write_bytes((demo_media / "genuine_notice.jpg").read_bytes())
    res = pipeline.run({"text": HINDI, "reply_language": "ta", "files": [
        {"path": str(up), "name": "notice.jpg", "kind": "image", "public_url": "/media/team_test.jpg"}]})
    roles = {c["role"]: c["provider"] for c in res["ai_team"]}
    assert roles == {"ocr": "ocrspace", "image_ai": "sightengine", "vision": "openai", "research": "gemini",
                     "translation": "sarvam", "voice": "sarvam", "review": "openai"}
    m = res["media"][0]
    assert m["ai_detection"]["ai_generated"] == 0.93 and m["tamper_score"] >= 0.93 and res["deepfakeDetected"]
    assert m["vision"]["description"] and m["ocr_text"]
    assert res["research"]["localized"]["lang"] == "ta"
    assert res["voice"]["lang"] == "ta" and (config.ARTIFACT_DIR / res["voice"]["url"].rsplit("/", 1)[-1]).exists()
    assert len({c["provider"] for c in res["ai_team"]}) >= 5
    team = {r["role"]: r["active"] for r in router.lineup()}
    assert team["speech"] == "sarvam" and team["voice"] == "sarvam"


def test_failing_provider_falls_back_gracefully(fake_http, monkeypatch, demo_media):
    def broken(*a, **k):
        raise http.ProviderError("Sightengine HTTP 401: bad key", 401)
    monkeypatch.setattr(sightengine.SightengineProvider, "detect_ai_image", broken)
    up = config.UPLOAD_DIR / "team_test2.jpg"
    up.write_bytes((demo_media / "genuine_notice.jpg").read_bytes())
    res = pipeline.run({"text": "Post-Matric Merit Scholarship Rs 12,000 per year", "files": [
        {"path": str(up), "name": "n.jpg", "kind": "image", "public_url": "/media/x.jpg"}]})
    assert any("401" in w for w in res["warnings"])
    assert any(c["role"] == "image_ai" and c.get("error") for c in res["ai_team"])
    assert res["media"][0]["tamper_score"] == 0.0           # local forensics still ran
