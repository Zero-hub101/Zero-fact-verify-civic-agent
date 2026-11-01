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
        if "groq.com" in url and "chat/completions" in url:
            return FakeResp({"choices": [{"message": {"content": json.dumps({"t": "[groq] translated"})}}]})
        if "groq.com" in url and "transcriptions" in url:
            return FakeResp({"text": "नमस्ते", "language": "hindi"})
        if "groq.com" in url and "translations" in url:
            return FakeResp({"text": "Hello"})
        if "mistral.ai" in url:
            v = json.dumps({"verdict": "fraudulent", "authenticity": 0.04, "reasons": ["fee via personal UPI"]})
            return FakeResp({"choices": [{"message": {"content": v}}]})
        if "cohere.com" in url:
            v = json.dumps({"verdict": "fraudulent", "authenticity": 0.06, "reasons": ["OTP request"]})
            return FakeResp({"message": {"content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": v}]}})
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
    monkeypatch.setenv("LOCAL_AI_IMAGE_DISABLED", "true")       # use the cloud detector in this test
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gm")
    monkeypatch.setattr(gemini, "_post", lambda url, body, timeout=120: _interactions_response())
    up = config.UPLOAD_DIR / "team_test.jpg"
    up.write_bytes((demo_media / "genuine_notice.jpg").read_bytes())
    res = pipeline.run({"text": HINDI, "reply_language": "ta", "files": [
        {"path": str(up), "name": "notice.jpg", "kind": "image", "public_url": "/media/team_test.jpg"}]})
    roles = {c["role"]: c["provider"] for c in res["ai_team"]}
    assert roles == {"ocr": "ocrspace", "image_ai": "sightengine", "vision": "openai", "research": "gemini",
                     "translation": "sarvam", "review": "groq"}
    m = res["media"][0]
    assert m["ai_detection"]["ai_generated"] == 0.93 and m["tamper_score"] >= 0.93 and res["deepfakeDetected"]
    assert m["vision"]["description"] and m["ocr_text"]
    assert res["research"]["localized"]["lang"] == "ta"
    assert res["voice"]["lang"] == "ta" and res["voice"]["service"] and res["voice"]["url"] is None
    spoken = pipeline.speak(res["voice"]["text"], res["voice"]["lang"])      # made when the citizen presses Listen
    assert spoken["credit"]["provider"] == "sarvam" and (config.ARTIFACT_DIR / spoken["url"].rsplit("/", 1)[-1]).exists()
    assert len({c["provider"] for c in res["ai_team"]}) >= 5
    team = {r["role"]: r["active"] for r in router.lineup()}
    assert team["speech"] == "sarvam" and team["voice"] == "sarvam"


def test_failing_provider_falls_back_gracefully(fake_http, monkeypatch, demo_media):
    monkeypatch.setenv("LOCAL_AI_IMAGE_DISABLED", "true")
    def broken(*a, **k):
        raise http.ProviderError("Sightengine HTTP 401: bad key", 401)
    monkeypatch.setattr(sightengine.SightengineProvider, "detect_ai_image", broken)
    up = config.UPLOAD_DIR / "team_test2.jpg"
    up.write_bytes((demo_media / "genuine_notice.jpg").read_bytes())
    res = pipeline.run({"text": "Central Sector Scholarship Rs 12,000 per year", "files": [
        {"path": str(up), "name": "n.jpg", "kind": "image", "public_url": "/media/x.jpg"}]})
    assert any("API key rejected" in w for w in res["warnings"])
    assert any(c["role"] == "image_ai" and c.get("error") for c in res["ai_team"])
    assert res["media"][0]["tamper_score"] == 0.0           # local forensics still ran


def test_mistral_and_cohere_reviewers(fake_http, monkeypatch):
    from app.ai.providers import cohere, mistral
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    monkeypatch.setenv("COHERE_API_KEY", "c")
    r = mistral.MistralProvider().review("Pay Rs 499 to UPI 98xxx@ybl", None)
    assert r["verdict"] == "fraudulent" and r["authenticity"] == 0.04
    assert fake_http[-1]["headers"]["Authorization"] == "Bearer m"
    assert fake_http[-1]["body"]["model"] == "mistral-small-latest"
    r = cohere.CohereProvider().review("Share your OTP on WhatsApp", None)
    assert r["verdict"] == "fraudulent" and r["authenticity"] == 0.06
    assert fake_http[-1]["url"] == "https://api.cohere.com/v2/chat"
    assert router.get("review").id == "mistral"                 # free options come first
    monkeypatch.setenv("MISTRAL_API_KEY", "")
    assert router.get("review").id == "cohere"


def test_ollama_local_review(monkeypatch):
    from app.ai.providers import ollama
    ollama._cache.update(t=0.0, ok=False)
    sent = {}
    monkeypatch.setattr(ollama.requests, "get", lambda url, timeout=None: FakeResp({"models": [{"name": "qwen3:8b"}]}))

    def post(url, json=None, timeout=None):
        sent.update(json)
        return FakeResp({"message": {"content": '<think>checking</think>{"verdict": "fraudulent", "authenticity": 0.1, '
                                                '"reasons": ["fee via personal UPI"]}'}})
    monkeypatch.setattr(ollama.requests, "post", post)
    p = ollama.OllamaProvider()
    assert p.enabled()
    r = p.review("Pay Rs 499 to UPI 98xxx@ybl", None)
    assert r["verdict"] == "fraudulent" and r["authenticity"] == 0.1 and sent["format"] == "json"
    ollama._cache.update(t=0.0, ok=False)


def test_local_ai_image_detector(monkeypatch, demo_media):
    from app.ai.providers import local_ai_detector as lad
    monkeypatch.setattr(lad.LocalAiDetectorProvider, "enabled", lambda self: True)
    monkeypatch.setenv("SIGHTENGINE_API_USER", "u")
    monkeypatch.setenv("SIGHTENGINE_API_SECRET", "x")
    assert router.get("image_ai").id == "localdetector"           # free local model is preferred
    seen = {}

    def fake_classifier(model):
        seen["model"] = model
        return lambda img, top_k=5: [{"label": "artificial", "score": 0.91}, {"label": "human", "score": 0.09}]
    monkeypatch.setattr(lad, "_classifier", fake_classifier)
    r = lad.LocalAiDetectorProvider().detect_ai_image(demo_media / "genuine_notice.jpg")
    assert r["ai_generated"] == 0.91 and seen["model"] == "Organika/sdxl-detector"
    for labels, expect in (([("FAKE", 0.8), ("REAL", 0.2)], 0.8), ([("AI-generated", 0.3), ("human", 0.7)], 0.3)):
        monkeypatch.setattr(lad, "_classifier", lambda m, labels=labels: (
            lambda img, top_k=5: [{"label": l, "score": sc} for l, sc in labels]))
        assert lad.LocalAiDetectorProvider().detect_ai_image(demo_media / "genuine_notice.jpg")["ai_generated"] == expect


def test_failed_key_falls_back_to_next_service(fake_http, monkeypatch):
    def bad(*a, **k):
        raise http.ProviderError("Sarvam translate HTTP 403: invalid_api_key_error", 403)
    monkeypatch.setattr(sarvam.SarvamProvider, "translate", bad)
    monkeypatch.setenv("AI_TRANSLATION", "sarvam,groq")
    result, credit = router.call("translation", lambda p: p.translate({"t": "hello"}, "hi"))
    assert result == {"t": "[groq] translated"}
    assert credit["provider"] == "groq" and credit["fallback_from"] == ["sarvam"]
    assert router.short_error("Sarvam translate HTTP 403: invalid") == "API key rejected (check the key in your settings file)"


def test_c2pa_provenance_is_not_tampering(tmp_path, demo_media):
    from app.forensics import media
    raw = (demo_media / "genuine_notice.jpg").read_bytes()
    tagged = tmp_path / "tagged.jpg"
    payload = b"JP\x00\x01jumb....jumdc2pa....Anthropic Claude"
    segment = b"\xff\xeb" + (len(payload) + 2).to_bytes(2, "big") + payload
    tagged.write_bytes(raw[:20] + segment + raw[20:])
    r = media.analyze_image(tagged, "t")
    assert r["signals"]["metadata"] == 0.0 and r["metadata"].get("provenance")
