"""If an AI service returns a malformed answer, the check must still finish with a valid verdict."""
import json
import random

from PIL import Image

from app import pipeline
from app.ai import router


class _Fake:
    id, name, specialist_roles = "fake", "Fake", set()

    def model_for(self, role):
        return "m"


def _junk(r, depth=0):
    c = r.random()
    if depth > 2 or c < .15:
        return r.choice([None, "", "x", 0, -1, 1.5, float("nan"), True, [], {}])
    if c < .3:
        return [_junk(r, depth + 1) for _ in range(r.randint(0, 3))]
    keys = ["text", "language", "transcript", "t", "claim", "summary", "advice", "verdict", "authenticity", "findings",
            "sources", "localized", "lang", "grounded", "ai_generated", "deepfake", "text_in_image", "reasons", "error"]
    return {r.choice(keys): _junk(r, depth + 1) for _ in range(r.randint(0, 8))}


def test_pipeline_survives_malformed_ai_answers(monkeypatch, tmp_path):
    r = random.Random(11)
    monkeypatch.setattr(router, "get", lambda role: _Fake())
    monkeypatch.setattr(router, "assigned", lambda role: ["fake"])
    monkeypatch.setattr(router, "call", lambda role, fn: (_junk(r), {"role": role, "provider": "fake", "name": "Fake",
                                                                       "model": "m", "specialist": False, "seconds": 0}))
    img = tmp_path / "a.jpg"
    Image.new("RGB", (120, 90), (90, 30, 30)).save(img, "JPEG")
    for _ in range(300):
        res = pipeline.run({"text": r.choice(["PM Kisan pay Rs 499 fee", "पीएम किसान ₹499 भेजें", "scholarship"]),
                            "url": "", "transcript": "", "reply_language": r.choice(["auto", "hi", "en"]),
                            "files": [{"path": str(img), "name": "a.jpg", "kind": "image", "public_url": "/m/a.jpg"}]
                            if r.random() < .4 else []})
        json.dumps(res, default=str)
        assert 0 <= res["authenticity"] <= 1
