"""Offline OCR with Tesseract (needs `pip install pytesseract` and the Tesseract program). Role: OCR."""
from ..base import Provider

LANGS = {"hi": "hin+eng", "ta": "tam+eng", "te": "tel+eng", "kn": "kan+eng", "ml": "mal+eng", "bn": "ben+eng"}


class TesseractProvider(Provider):
    id = "tesseract"
    name = "Tesseract (offline)"
    roles = {"ocr"}
    specialist_roles = {"ocr"}

    def enabled(self) -> bool:
        try:
            import pytesseract  # type: ignore
            pytesseract.get_tesseract_version()
            return True
        except Exception:  # noqa: BLE001
            return False

    def model_for(self, role: str) -> str:
        return "tesseract"

    def ocr(self, image_path, lang_hint=""):
        import pytesseract  # type: ignore
        from PIL import Image
        langs = LANGS.get(lang_hint, "eng")
        try:
            text = pytesseract.image_to_string(Image.open(image_path), lang=langs)
        except pytesseract.TesseractError:
            text = pytesseract.image_to_string(Image.open(image_path))
        return {"text": text.strip(), "language": lang_hint if text.strip() else ""}
