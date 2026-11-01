"""Local AI-image detector: an open model that runs on your laptop. Free, offline after the first
download, NO account or API key. Role: IMAGE_AI (replaces Sightengine).

Default model: Organika/sdxl-detector (Swin transformer, ~350 MB, 98% validation accuracy on
SDXL-vs-real images; licence: non-commercial / educational use, which fits a hackathon).
Any Hugging Face "image-classification" AI-vs-real model can be used via LOCAL_AI_IMAGE_MODEL.

Setup:  pip install transformers torch      (first run downloads the model automatically)
"""
import importlib.util
import os
import threading

from ..base import Provider, ProviderError

_lock = threading.Lock()
_pipe = {"model": None, "fn": None}
AI_WORDS = ("artificial", "ai", "fake", "generated", "synthetic", "sdxl")
REAL_WORDS = ("human", "real", "authentic", "natural")


def _is_ai(label: str) -> bool:
    l = label.lower().replace("_", " ").replace("-", " ")
    if any(w in l.split() or l.startswith(w) for w in REAL_WORDS):
        return False
    return any(w in l.split() or l.startswith(w) for w in AI_WORDS)


def _classifier(model: str):
    with _lock:
        if _pipe["model"] != model:
            from transformers import pipeline  # type: ignore
            _pipe["fn"] = pipeline("image-classification", model=model)
            _pipe["model"] = model
        return _pipe["fn"]


class LocalAiDetectorProvider(Provider):
    id = "localdetector"
    name = "Local AI-image detector (Hugging Face model)"
    roles = {"image_ai"}
    specialist_roles = {"image_ai"}

    def enabled(self) -> bool:
        if os.getenv("LOCAL_AI_IMAGE_DISABLED", "").lower() == "true":
            return False
        return bool(importlib.util.find_spec("transformers") and importlib.util.find_spec("torch"))

    def model_for(self, role: str) -> str:
        return os.getenv("LOCAL_AI_IMAGE_MODEL", "Organika/sdxl-detector")

    def detect_ai_image(self, image_path):
        from PIL import Image
        try:
            preds = _classifier(self.model_for("image_ai"))(Image.open(image_path).convert("RGB"), top_k=5)
        except Exception as e:  # noqa: BLE001 - download/offline errors become a clear message
            raise ProviderError(f"Local AI-image detector failed: {str(e)[:200]}")
        ai = sum(p["score"] for p in preds if _is_ai(p["label"]))
        if not any(_is_ai(p["label"]) for p in preds):         # unknown label names: assume 2 classes
            raise ProviderError(f"Unrecognised labels from {self.model_for('image_ai')}: {[p['label'] for p in preds]}")
        return {"ai_generated": round(min(1.0, ai), 4), "deepfake": None,
                "labels": {p["label"]: round(p["score"], 4) for p in preds}}


def warm_up() -> None:
    """Download and load the model in the background at startup, so the first check is not slow."""
    p = LocalAiDetectorProvider()
    if p.enabled():
        try:
            _classifier(p.model_for("image_ai"))
        except Exception:  # noqa: BLE001 - reported later when a check runs
            pass
