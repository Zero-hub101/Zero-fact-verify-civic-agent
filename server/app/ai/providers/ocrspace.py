"""OCR.space provider. Specialist role: OCR (reads text in images; Engine 3 handles Hindi, Tamil,
Telugu and Kannada scripts).

Keys: https://ocr.space/ocrapi (free key by email)  ->  OCR_SPACE_API_KEY  (header: apikey)
"""
import os

from ..base import Provider, ProviderError
from ..http import post_multipart
from ..util import shrink_image

ENGINE3_LANGS = {"hi": "hin", "ta": "tam", "te": "tel", "kn": "kan"}


class OcrSpaceProvider(Provider):
    id = "ocrspace"
    name = "OCR.space"
    roles = {"ocr"}
    specialist_roles = {"ocr"}

    def enabled(self) -> bool:
        return bool(os.getenv("OCR_SPACE_API_KEY"))

    def model_for(self, role: str) -> str:
        return "OCR Engine 2/3"

    def _parse(self, small, language: str, engine: str) -> str:
        r = post_multipart("OCR.space", "https://api.ocr.space/parse/image",
                           {"apikey": os.getenv("OCR_SPACE_API_KEY", "")},
                           {"language": language, "OCREngine": engine, "scale": "true", "isOverlayRequired": "false"},
                           "file", small, "image/jpeg")
        if r.get("IsErroredOnProcessing"):
            msg = r.get("ErrorMessage")
            raise ProviderError(f"OCR.space: {msg if isinstance(msg, str) else '; '.join(msg or [])}")
        return "\n".join((p.get("ParsedText") or "") for p in r.get("ParsedResults") or []).strip()

    def ocr(self, image_path, lang_hint=""):
        small = shrink_image(image_path)
        try:
            if lang_hint in ENGINE3_LANGS:
                return {"text": self._parse(small, ENGINE3_LANGS[lang_hint], "3"), "language": lang_hint}
            text = self._parse(small, "auto", "2")
            return {"text": text, "language": "en" if text else ""}
        finally:
            small.unlink(missing_ok=True)
