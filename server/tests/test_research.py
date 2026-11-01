"""Multi-model AI layer: Gemini research parsing (both API shapes), role routing and pipeline integration.
Network calls are mocked."""
import json

import pytest

from app import config, pipeline
from app.ai import router
from app.ai.base import Provider
from app.ai.providers import gemini as research
from app.forensics import language

HINDI = ("जरूरी सूचना!! पोस्ट मैट्रिक मेरिट छात्रवृत्ति में सभी छात्रों को ₹50,000 मिलेंगे। 24 घंटे में ₹499 "
         "पंजीकरण शुल्क UPI 9876543210@ybl पर भेजें और OTP व्हाट्सएप पर शेयर करें।")

ANSWER = {
    "claim_language": "hi",
    "claim_en": "Urgent! Central Sector Scholarship gives Rs 50,000 to all students. Send Rs 499 registration "
                "fee to UPI 9876543210@ybl within 24 hours and share the OTP on WhatsApp.",
    "verdict": "fraudulent", "authenticity": 0.04, "already_debunked": True,
    "findings": [
        {"point": "Benefit amount", "status": "contradicted",
         "evidence": "The official scheme pays Rs 12,000 per year, not Rs 50,000."},
        {"point": "Registration fee", "status": "contradicted",
         "evidence": "PIB Fact Check says the scholarship portal never charges a fee."},
    ],
    "official_source_name": "PIB Fact Check",
    "summary": "This message is a scam.", "summary_local": "यह संदेश धोखाधड़ी है।",
    "advice_local": "कोई पैसा या OTP न भेजें।",
}


def _interactions_response():
    text = json.dumps(ANSWER, ensure_ascii=False)
    s1 = text.index("The official scheme pays")
    s2 = text.index("PIB Fact Check says")
    return {"id": "int_1", "steps": [
        {"type": "google_search_call", "arguments": {"queries": ["post matric scholarship fee fake PIB"]}},
        {"type": "google_search_result", "content": [{"search_suggestions": "<div/>"}]},
        {"type": "model_output", "content": [{"type": "text", "text": text, "annotations": [
            {"type": "url_citation", "url": "https://scholarships.gov.in/faq", "title": "scholarships.gov.in",
             "start_index": s1, "end_index": s1 + 40},
            {"type": "url_citation", "url": "https://pib.gov.in/factcheck/123", "title": "pib.gov.in",
             "start_index": s2, "end_index": s2 + 30}]}]}]}


def _generate_content_response():
    text = json.dumps(ANSWER, ensure_ascii=False)
    b = text.encode()
    s1 = b.index("The official scheme pays".encode())
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "groundingMetadata": {
        "webSearchQueries": ["post matric scholarship amount"],
        "groundingChunks": [{"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                                     "title": "scholarships.gov.in"}},
                            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/def",
                                     "title": "factly.in"}}],
        "groundingSupports": [{"segment": {"startIndex": s1, "endIndex": s1 + 45},
                               "groundingChunkIndices": [0]}]}}]}


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    calls = []

    def install(mode):
        def fake_post(url, body, timeout=120):
            calls.append((url, body))
            if "interactions" in url:
                if mode == "interactions":
                    return _interactions_response()
                raise research.GeminiError("HTTP 404: not found", 404)
            return _generate_content_response()
        monkeypatch.setattr(research, "_post", fake_post)
        return calls
    return install


def test_language_detection():
    assert language.detect(HINDI)["code"] == "hi"
    assert language.detect("இந்த உதவித்தொகை மோசடி")["code"] == "ta"
    assert language.detect("Scholarship for all students")["code"] == "en"


def test_research_interactions_api(gemini):
    calls = gemini("interactions")
    r = research.research_claim(HINDI, None, "hi")
    assert calls[0][1]["model"] == config.GEMINI_MODEL and calls[0][1]["tools"] == [{"type": "google_search"}]
    assert "summary_local" in calls[0][1]["input"]                 # localisation folded into the same call
    assert r["api"] == "interactions" and r["verdict"] == "fraudulent" and r["grounded"]
    assert r["language"]["code"] == "hi" and r["localized"]["summary"]
    assert {s["host"] for s in r["sources"]} == {"scholarships.gov.in", "pib.gov.in"}
    assert all(f["source_ids"] for f in r["findings"])          # each finding linked to its proof
    assert r["search_queries"] == ["post matric scholarship fee fake PIB"]


def test_research_generate_content_fallback(gemini):
    gemini("generate")
    r = research.research_claim(HINDI, None, None)
    assert r["api"] == "generateContent" and r["localized"] is None
    assert r["findings"][0]["source_ids"] == [0]
    assert r["sources"][1]["trust"] == "fact_checker"


def test_pipeline_uses_translation_and_research(gemini):
    gemini("interactions")
    res = pipeline.run({"text": HINDI, "files": [], "reply_language": "auto"})
    assert res["language"]["code"] == "hi"
    assert res["research"]["localized"]["summary"]
    roles = {c["role"]: c for c in res["ai_team"]}
    assert roles["research"]["provider"] == "gemini" and roles["research"]["specialist"]
    assert roles["translation"]["note"] == "combined with research"
    assert res["matched_scheme"]["id"] == "sch_csss"
    assert res["verdict"] == "likely_fraudulent" and res["agentAllowed"] is False
    assert any(c["field"] == "application_fee" for c in res["text"]["contradictions"])


def test_research_disabled_without_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert research.research_claim("anything", None) is None


def test_research_errors_are_reported(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "bad")

    def deny(url, body, timeout=120):
        raise research.GeminiError("HTTP 403: API key not valid", 403)
    monkeypatch.setattr(research, "_post", deny)
    r = research.research_claim("Scholarship claim", None)
    assert "error" in r and "403" in r["error"]


class FakeLanguageModel(Provider):
    """Stands in for a future specialist (e.g. an Indian-language translation/speech model)."""
    id = "fakelang"
    name = "Fake Language Specialist"
    roles = {"translation", "speech"}
    specialist_roles = {"translation", "speech"}
    calls: list = []

    def enabled(self):
        return True

    def model_for(self, role):
        return "fake-1"

    def translate(self, texts, target_lang):
        self.calls.append(target_lang)
        return {k: f"[{target_lang}] {v}" for k, v in texts.items()}


def test_lineup_defaults(gemini):
    gemini("interactions")
    team = {r["role"]: r for r in router.lineup()}
    assert team["research"]["active"] == "gemini" and team["research"]["status"] == "specialist"
    assert team["translation"]["active"] == "gemini" and team["translation"]["status"] == "stand-in"


def test_specialist_model_plugs_in(gemini, monkeypatch):
    calls = gemini("interactions")
    router.register(FakeLanguageModel())
    monkeypatch.setenv("AI_TRANSLATION", "fakelang")
    res = pipeline.run({"text": HINDI, "files": [], "reply_language": "ta"})
    assert "summary_local" not in calls[0][1]["input"]           # Gemini only researches now
    assert res["research"]["localized"]["lang"] == "ta"
    assert res["research"]["localized"]["summary"].startswith("[ta]")
    roles = {c["role"]: c["provider"] for c in res["ai_team"]}
    assert roles == {"research": "gemini", "translation": "fakelang"}
    assert {r["role"]: r["active"] for r in router.lineup()}["translation"] == "fakelang"


def test_role_switched_off(monkeypatch):
    monkeypatch.setenv("AI_RESEARCH", "")
    assert router.get("research") is None
