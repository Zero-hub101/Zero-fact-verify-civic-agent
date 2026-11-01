"""Helpers shared by providers: language codes, image shrinking, audio chunking."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

# ISO 639-1 -> Sarvam / BCP-47 style
BCP47 = {"en": "en-IN", "hi": "hi-IN", "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN", "ml": "ml-IN",
         "mr": "mr-IN", "gu": "gu-IN", "pa": "pa-IN", "or": "od-IN", "ur": "ur-IN"}
# ISO 639-3 / Whisper language names -> ISO 639-1
ISO3 = {"eng": "en", "hin": "hi", "ben": "bn", "tam": "ta", "tel": "te", "kan": "kn", "mal": "ml", "mar": "mr",
        "guj": "gu", "pan": "pa", "ori": "or", "ory": "or", "urd": "ur"}
NAMES = {"english": "en", "hindi": "hi", "bengali": "bn", "tamil": "ta", "telugu": "te", "kannada": "kn",
         "malayalam": "ml", "marathi": "mr", "gujarati": "gu", "punjabi": "pa", "panjabi": "pa", "odia": "or",
         "oriya": "or", "urdu": "ur"}


def to_iso1(code: str) -> str:
    """Normalise 'hi-IN', 'hin', 'hindi' or 'od-IN' to 'hi' / 'or'."""
    c = (code or "").strip().lower()
    if not c:
        return ""
    if c in NAMES:
        return NAMES[c]
    if c in ISO3:
        return ISO3[c]
    base = c.split("-")[0].split("_")[0]
    return "or" if base == "od" else base


def shrink_image(path: Path, max_side: int = 1000, max_bytes: int = 950_000) -> Path:
    """JPEG copy within free-tier limits (OCR.space: 1 MB, 1000 px). Caller deletes the temp file."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    fd, name = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)                       # Windows cannot reopen or delete a file that is still open
    out = Path(name)
    for q in (90, 80, 70, 60, 50):
        img.save(out, "JPEG", quality=q)
        if out.stat().st_size <= max_bytes:
            break
    return out


def split_audio(path: Path, seconds: int, max_parts: int, out_dir: str) -> list[Path]:
    """Split audio into chunks (APIs with per-request duration limits). Returns the original if ffmpeg is missing."""
    if not shutil.which("ffmpeg"):
        return [path]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-f", "segment", "-segment_time", str(seconds),
                    "-c", "copy", f"{out_dir}/part_%03d.mp3"], capture_output=True, timeout=120)
    parts = sorted(Path(out_dir).glob("part_*.mp3"))
    return parts[:max_parts] or [path]
