"""Generate the demo media used by the two acceptance scenarios.

genuine_notice.jpg   - an unedited scholarship notice (photo of a printed notice)
tampered_notice.jpg  - the same notice with the benefit/fee lines replaced by a pasted-in patch
genuine_notice.mp4   - short clip panning over the genuine notice
tampered_notice.mp4  - the same clip with the pasted patch spliced in partway through

Run:  python demo/make_demo_media.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent / "media"
W, H = 1200, 800


def font(size: int, bold: bool = False):
    for name in (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"] if bold else
                 ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def photographic_background(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:H, 0:W]
    base = 225 + 18 * np.sin(x / 210.0) * np.cos(y / 170.0)
    paper = np.stack([base, base - 4, base - 14], axis=-1)
    paper += rng.normal(0, 6, paper.shape)                            # sensor noise / paper grain
    return Image.fromarray(np.clip(paper, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))


def draw_notice(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle([60, 50, W - 60, 150], fill=(20, 60, 120))
    d.text((90, 72), "DEPARTMENT OF HIGHER EDUCATION", font=font(40, True), fill="white")
    d.text((90, 185), "Post-Matric Merit Scholarship 2026-27", font=font(44, True), fill=(20, 30, 60))
    lines = [
        "Scholarship: Rs 12,000 per year for eligible students.",
        "Family income limit: Rs 2,50,000 per year.",
        "Application fee: NONE. Apply free on the official portal only.",
        "Last date to apply: 15 December 2026.",
        "Never share your OTP or bank PIN with anyone.",
    ]
    for i, line in enumerate(lines):
        d.text((90, 280 + i * 70), line, font=font(32), fill=(25, 25, 25))
    d.text((90, 690), "Issued by the Scholarship Cell  |  scholarships.gov.in", font=font(26), fill=(70, 70, 90))


def fake_patch() -> Image.Image:
    """The forger's replacement lines, made separately (different noise and compression history)."""
    rng = np.random.default_rng(99)
    patch = np.full((150, 1000, 3), (236, 232, 222), dtype=np.float32)
    patch += rng.normal(0, 1.5, patch.shape)
    p = Image.fromarray(np.clip(patch, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(p)
    d.text((0, 10), "Scholarship: Rs 50,000 for ALL students.", font=font(32), fill=(25, 25, 25))
    d.text((0, 80), "Pay Rs 499 registration fee to UPI 98xxxx1234@ybl", font=font(32), fill=(25, 25, 25))
    return p


def build_images() -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    img = photographic_background(7)
    draw_notice(img)
    genuine = OUT / "genuine_notice.jpg"
    img.save(genuine, "JPEG", quality=72)                             # as forwarded on messaging apps

    shot = Image.open(genuine).convert("RGB")                          # forger downloads the real notice...
    d = ImageDraw.Draw(shot)
    d.rectangle([85, 275, 1150, 410], fill=(232, 228, 218))           # ...erases two lines...
    shot.paste(fake_patch(), (90, 272))                                # ...pastes their own text...
    tampered = OUT / "tampered_notice.jpg"
    shot.save(tampered, "JPEG", quality=95)                            # ...and re-saves it
    return genuine, tampered


def build_videos(genuine: Path, tampered: Path) -> None:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found - skipping demo videos")
        return
    for src_list, name in (([genuine] * 24, "genuine_notice.mp4"), ([genuine] * 10 + [tampered] * 14, "tampered_notice.mp4")):
        with tempfile.TemporaryDirectory() as tmp:
            for i, src in enumerate(src_list):
                im = Image.open(src).convert("RGB")
                zoom = 1 + i * 0.004                                   # slow push-in like a phone recording
                cw, ch = int(W / zoom), int(H / zoom)
                im = im.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((960, 640))
                im.save(f"{tmp}/f_{i:03d}.png")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", "8", "-i", f"{tmp}/f_%03d.png",
                            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(OUT / name)], check=True)


if __name__ == "__main__":
    g, t = build_images()
    if "--no-video" not in sys.argv:
        build_videos(g, t)
    print("Demo media written to", OUT)
