"""Media forensics: error level analysis (ELA), copy-move detection, metadata inspection, video frame analysis.

These are established image-forensics techniques. They produce *signals* of manipulation, not proof;
the UI presents them as such.
"""
import io
import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import ExifTags, Image, ImageDraw

from .. import config

log = logging.getLogger("factverify.media")
BLOCK = 16
EDITOR_KEYWORDS = ["photoshop", "gimp", "canva", "snapseed", "picsart", "faceapp", "facetune", "lightroom",
                   "pixlr", "affinity", "stable diffusion", "midjourney", "dall-e", "dall·e", "firefly",
                   "generative", "deepfake", "faceswap", "reface"]
AI_CHUNK_KEYS = ["parameters", "prompt", "workflow", "sd-metadata", "dream", "invokeai_metadata"]


def _artifact(name: str) -> tuple[Path, str]:
    fname = f"{uuid.uuid4().hex[:10]}_{name}"
    return config.ARTIFACT_DIR / fname, f"/artifacts/{fname}"


# ---------------- core image signals ----------------
def _luma_recompress_errors(img: Image.Image, qualities) -> dict:
    rgb = img.convert("RGB")
    y = np.asarray(rgb.convert("L"), dtype=np.float32)
    out = {}
    for q in qualities:
        buf = io.BytesIO()
        rgb.save(buf, "JPEG", quality=q)
        buf.seek(0)
        r = np.asarray(Image.open(buf).convert("L"), dtype=np.float32)
        out[q] = _block_means((y - r) ** 2)
    return out


def _block_means(arr: np.ndarray, block: int = BLOCK) -> np.ndarray:
    h, w = arr.shape[0] // block * block, arr.shape[1] // block * block
    if h == 0 or w == 0:
        return np.zeros((1, 1), dtype=np.float32)
    a = arr[:h, :w]
    return a.reshape(h // block, block, w // block, block).mean(axis=(1, 3))


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, comp = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            comp.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        comps.append(comp)
    return comps


def _regions(mask: np.ndarray, strength_map: np.ndarray, img_w: int, img_h: int, block: int = BLOCK,
             min_blocks: int = 4) -> list[dict]:
    regions = []
    for comp in _components(mask):
        if len(comp) < min_blocks:
            continue
        ys, xs = zip(*comp)
        regions.append({
            "x": min(xs) * block / img_w, "y": min(ys) * block / img_h,
            "w": (max(xs) - min(xs) + 1) * block / img_w, "h": (max(ys) - min(ys) + 1) * block / img_h,
            "strength": round(float(np.mean([strength_map[p] for p in comp])), 3), "blocks": len(comp),
            "area": len(comp) / mask.size,
        })
    regions.sort(key=lambda r: -r["blocks"] * r["strength"])
    return regions


def compression_analysis(img: Image.Image) -> dict:
    """JPEG-ghost analysis (Farid, 2009).

    An image that was saved as JPEG at quality Q shows a dip ("ghost") in recompression error at Q.
    Content pasted in afterwards does not share that history, so it shows no dip at Q.
    Blocks whose ghost is missing while the rest of the image has it are flagged.
    """
    qs = list(range(50, 100, 5))
    D = _luma_recompress_errors(img, qs)
    valid = D[50] > 5.0                                        # textureless blocks carry no signal
    empty = {"score": 0.0, "heat": np.zeros_like(D[50]), "regions": [], "ghost_quality": None}
    if valid.sum() < 12:
        return empty
    best_q, best_dip = None, 1.0
    for q in range(60, 90, 5):
        ratio = D[q] / (0.5 * (D[q - 10] + D[q + 10]) + 1e-3)
        dip = float(np.median(ratio[valid]))
        if dip < best_dip:
            best_q, best_dip = q, dip
    if best_q is None or best_dip > 0.6:                      # no earlier compression to compare against
        return empty
    ratio = D[best_q] / (0.5 * (D[best_q - 10] + D[best_q + 10]) + 1e-3)
    ratio = np.where(valid, ratio, 0.0)
    thresh = max(0.75, 3 * best_dip)
    mask = valid & (ratio > thresh)
    regions = [r for r in _regions(mask, ratio, img.width, img.height) if r["area"] < 0.5]
    score = 0.0
    if regions:
        top = regions[0]
        score = min(1.0, 0.55 + 0.3 * min(1.0, (top["strength"] - thresh) / 0.3) + min(0.15, top["blocks"] / 200))
    heat = np.where(valid, np.clip((ratio - best_dip) / (1.0 - best_dip + 1e-3), 0, 1), 0)
    return {"score": round(score, 3), "heat": heat, "regions": regions[:6], "ghost_quality": best_q,
            "ghost_depth": round(best_dip, 3)}


def copy_move_analysis(img: Image.Image) -> dict:
    """Detect duplicated (cloned) textured blocks at a consistent offset."""
    g = np.asarray(img.convert("L").resize((min(img.width, 512), int(img.height * min(img.width, 512) / img.width)))
                   if img.width > 512 else img.convert("L"), dtype=np.int16)
    step, size = 8, 16
    seen: dict[bytes, tuple[int, int]] = {}
    offsets: dict[tuple[int, int], int] = {}
    for y in range(0, g.shape[0] - size + 1, step):
        for x in range(0, g.shape[1] - size + 1, step):
            blk = g[y:y + size, x:x + size]
            if blk.std() < 12:
                continue
            key = (blk // 8).astype(np.int8).tobytes()
            if key in seen:
                oy, ox = seen[key]
                d = (y - oy, x - ox)
                if abs(d[0]) + abs(d[1]) > 2 * size:
                    offsets[d] = offsets.get(d, 0) + 1
            else:
                seen[key] = (y, x)
    best = max(offsets.values(), default=0)
    return {"score": round(min(1.0, best / 8), 3) if best >= 4 else 0.0, "matched_blocks": best}


def metadata_analysis(img: Image.Image, raw_path: Optional[Path] = None) -> dict:
    findings, meta = [], {}
    try:
        exif = img.getexif()
        for k, v in exif.items():
            name = ExifTags.TAGS.get(k, str(k))
            if name in ("Software", "Make", "Model", "DateTime", "Artist", "ProcessingSoftware"):
                meta[name] = str(v)[:120]
    except Exception:  # noqa: BLE001 - corrupt EXIF should not stop the audit
        pass
    for k, v in (img.info or {}).items():
        if isinstance(v, (str, bytes)) and k.lower() not in ("icc_profile", "exif"):
            meta[f"info:{k}"] = (v.decode(errors="ignore") if isinstance(v, bytes) else v)[:200]
    blob = " ".join(f"{k}={v}" for k, v in meta.items()).lower()
    for kw in EDITOR_KEYWORDS:
        if kw in blob:
            findings.append(f"Metadata references editing/generation software: '{kw}'")
    if any(k.lower().replace("info:", "") in AI_CHUNK_KEYS for k in meta):
        findings.append("Embedded AI-generation parameters found in file metadata")
    if raw_path and raw_path.exists():
        head = raw_path.read_bytes()[:400_000]
        if b"c2pa" in head or b"jumb" in head:
            findings.append("Content Credentials (C2PA) manifest present - check its edit history")
    score = 0.0
    if findings:
        score = 0.85 if any("AI-generation" in f or "generation software" in f for f in findings) else 0.6
    return {"score": score, "findings": findings, "metadata": meta}


def _heatmap(size: tuple[int, int], heat: np.ndarray, regions: list[dict], name: str) -> str:
    """Red overlay (transparent PNG) the frontend lays over the media."""
    h = np.clip(heat, 0, 1)
    overlay = np.zeros((*h.shape, 4), dtype=np.uint8)
    overlay[..., 0] = 255
    overlay[..., 1] = (60 * (1 - h)).astype(np.uint8)
    overlay[..., 3] = (h ** 1.5 * 170).astype(np.uint8)
    ov = Image.fromarray(overlay, "RGBA").resize(size, Image.BILINEAR)
    draw = ImageDraw.Draw(ov)
    for r in regions:
        x0, y0 = r["x"] * size[0], r["y"] * size[1]
        draw.rectangle([x0, y0, x0 + r["w"] * size[0], y0 + r["h"] * size[1]], outline=(255, 0, 0, 255),
                       width=max(3, size[0] // 250))
    path, url = _artifact(name)
    ov.save(path, "PNG")
    return url


def analyze_image(path: Path, label: str = "image") -> dict:
    img = Image.open(path)
    img.load()
    w, h = img.size
    comp = compression_analysis(img)
    cm = copy_move_analysis(img)
    meta = metadata_analysis(img, path)
    tamper = max(comp["score"], cm["score"], meta["score"])
    if sum(1 for s in (comp["score"], cm["score"], meta["score"]) if s > 0.3) >= 2:
        tamper = min(1.0, tamper + 0.1)                          # independent signals agreeing
    low_res = h < 240
    findings = list(meta["findings"])
    if comp["score"] > 0:
        findings.append(f"{len(comp['regions'])} region(s) lack the compression history of the rest of the image "
                        f"(image previously saved at ~Q{comp['ghost_quality']}); typical of pasted-in content")
    if cm["score"] > 0:
        findings.append(f"Cloned area detected ({cm['matched_blocks']} duplicated blocks at one offset)")
    if low_res:
        findings.append("Resolution below 240p: fine editing artifacts may be missed")
    if not findings:
        findings.append("No manipulation signals found")
    regions = [{k: v for k, v in r.items() if k != "area"} for r in comp["regions"]] if comp["score"] > 0 else []
    return {
        "kind": "image", "label": label, "width": w, "height": h,
        "tamper_score": round(tamper, 3),
        "signals": {"compression_ghost": comp["score"], "copy_move": cm["score"], "metadata": meta["score"]},
        "regions": regions, "findings": findings, "metadata": meta["metadata"],
        "heatmap_url": _heatmap(img.size, comp["heat"] if comp["score"] > 0 else comp["heat"] * 0.35, regions,
                                f"{label}_heatmap.png"),
        "low_resolution_confidence_degraded": low_res,
    }


# ---------------- video ----------------
def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
    data = json.loads(out.stdout or "{}")
    vstreams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    return {"width": vstreams[0].get("width") if vstreams else None,
            "height": vstreams[0].get("height") if vstreams else None,
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
            "duration": float(data.get("format", {}).get("duration") or 0)}


def _local_edit_events(frames: list[np.ndarray]) -> list[dict]:
    """Find moments where a localised area changes while the rest of the frame stays consistent.

    Camera motion changes the whole frame evenly; text or a face replaced mid-clip changes one area.
    """
    events = []
    for i in range(1, len(frames)):
        a, b = frames[i - 1], frames[i]
        d = _block_means(np.abs(a - b), 8)
        gy, gx = np.gradient(b)
        r = d / (_block_means(np.abs(gx) + np.abs(gy), 8) + 5)
        med = float(np.median(r))
        mad = float(np.median(np.abs(r - med))) * 1.4826 + 1e-3
        z = (r - med) / mad
        regs = [x for x in _regions(z > 15, z, b.shape[1], b.shape[0], block=8, min_blocks=3) if x["area"] < 0.4]
        if regs:
            events.append({"frame": i, "strength": regs[0]["strength"], "regions": regs[:4],
                           "heat": np.clip((z - 6) / 24, 0, 1), "global_change": med})
    return events


def analyze_video(path: Path, max_frames: int = 16) -> dict:
    if not ffmpeg_available():
        return {"kind": "video", "error": "ffmpeg is not installed; video forensics skipped.", "tamper_score": None,
                "findings": ["Install ffmpeg to enable video forensics"], "frames": []}
    info = _probe(path)
    dur = max(info["duration"], 0.1)
    fps = min(4.0, max_frames / dur)
    results, small = [], []
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps:.4f}", "-frames:v", str(max_frames),
                        f"{tmp}/f_%03d.png"], capture_output=True, timeout=180)
        for i, fp in enumerate(sorted(Path(tmp).glob("f_*.png"))):
            img = Image.open(fp).convert("RGB")
            small.append(np.asarray(img.convert("L").resize((320, max(1, int(320 * img.height / img.width)))),
                                    dtype=np.float32))
            comp = compression_analysis(img)
            thumb = img.copy()
            thumb.thumbnail((480, 480))
            tpath, turl = _artifact(f"frame_{i:02d}.jpg")
            thumb.save(tpath, "JPEG", quality=85)
            results.append({"index": i, "time": round(i / fps, 2), "score": comp["score"],
                            "flagged": comp["score"] > 0.5, "regions": comp["regions"] if comp["score"] > 0.5 else [],
                            "thumb_url": turl, "heatmap_url": None, "_size": thumb.size, "_heat": comp["heat"]})
    events = _local_edit_events(small)
    for ev in events:
        fr = results[ev["frame"]]
        score = min(1.0, 0.6 + 0.3 * min(1.0, (ev["strength"] - 15) / 30))
        fr["score"] = max(fr["score"], round(score, 3))
        fr["flagged"] = True
        fr["regions"] = [{k: v for k, v in r.items() if k != "area"} for r in ev["regions"]]
        fr["event"] = "localised_content_change"
    for fr in results:
        if fr["flagged"]:
            ev = next((e for e in events if e["frame"] == fr["index"]), None)
            fr["heatmap_url"] = _heatmap(fr["_size"], ev["heat"] if ev else fr["_heat"], fr["regions"],
                                         f"frame_{fr['index']:02d}_heat.png")
        fr.pop("_size"), fr.pop("_heat")
    meds = [e["global_change"] for e in events]
    flagged = [r for r in results if r["flagged"]]
    tamper = max((r["score"] for r in results), default=0.0)
    findings = []
    for ev in events:
        findings.append(f"At {results[ev['frame']]['time']}s one area of the frame changes while the rest stays "
                        f"consistent (content replaced mid-clip)")
    for r in results:
        if r["flagged"] and r.get("event") is None:
            findings.append(f"Frame at {r['time']}s has a region without the compression history of the rest")
    low_res = bool(info["height"] and info["height"] < 240)
    if low_res:
        findings.append("Resolution below 240p: fine editing artifacts may be missed")
    transcript = None                          # filled by the SPEECH role in pipeline.py
    if not findings:
        findings.append("No manipulation signals found in sampled frames")
    return {
        "kind": "video", "width": info["width"], "height": info["height"], "duration": round(dur, 2),
        "has_audio": info["has_audio"], "transcript": transcript, "transcription_available": transcript is not None,
        "tamper_score": round(tamper, 3), "frames": results, "flagged_frames": len(flagged),
        "findings": findings, "low_resolution_confidence_degraded": low_res
    }
