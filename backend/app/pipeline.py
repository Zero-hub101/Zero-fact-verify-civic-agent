"""Verification pipeline: runs text, URL and media analysis in parallel and combines them into one score."""
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import shutil
import subprocess
import tempfile

from . import config
from .ai import router
from .forensics import language, media, sources, text

log = logging.getLogger("factverify.pipeline")


def ocr_image(path: Path) -> Optional[str]:
    """Read text from an image when Tesseract is installed (optional)."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image
        out = pytesseract.image_to_string(Image.open(path))
        return out.strip() or None
    except Exception:  # noqa: BLE001 - optional dependency
        return None


def _public_scheme(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    return {k: s[k] for k in ("id", "name", "summary", "benefit_amount", "benefit_period", "application_fee",
                              "income_limit", "deadline", "eligibility", "official_domains", "playbook", "source")}


def _extract_audio(video: Path, out_dir: str) -> Optional[Path]:
    if not shutil.which("ffmpeg"):
        return None
    audio = Path(out_dir) / "audio.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "48k", "-t", "600", str(audio)], capture_output=True, timeout=180)
    return audio if audio.exists() and audio.stat().st_size > 2000 else None


def run(inputs: dict) -> dict:
    files = inputs.get("files", [])
    url = inputs.get("url") or None
    warnings: list[str] = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        url_future = pool.submit(sources.fetch_url_text, url) if url else None
        media_futures = []
        for f in files:
            p = Path(f["path"])
            if f["kind"] == "image":
                media_futures.append((f, pool.submit(media.analyze_image, p, Path(f["name"]).stem[:40])))
                media_futures.append((f, pool.submit(ocr_image, p)))
            elif f["kind"] == "video":
                media_futures.append((f, pool.submit(media.analyze_video, p)))

        url_result = url_future.result() if url_future else None
        media_results, ocr_texts = [], []
        for f, fut in media_futures:
            res = fut.result()
            if isinstance(res, dict):
                res["file_name"] = f["name"]
                res["media_url"] = f["public_url"]
                media_results.append(res)
            elif isinstance(res, str):
                ocr_texts.append(res)

    team: list[dict] = []                         # which model did which job in this run

    def use(role, fn):
        result, credit = router.call(role, fn)
        if credit:
            team.append(credit)
        if isinstance(result, dict) and result.get("error"):
            warnings.append(result["error"])
            return None
        return result

    # ---- SPEECH role: audio track of each video -> text (+ English via the translation role)
    for m in media_results:
        if m.get("kind") != "video" or not m.get("has_audio") or (inputs.get("transcript") or "").strip():
            continue
        path = next((Path(f["path"]) for f in files if f["name"] == m["file_name"]), None)
        if not path:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            audio = _extract_audio(path, tmp)
            tr = use("speech", lambda p: p.transcribe(audio)) if audio else None
        if not tr or not tr.get("transcript"):
            if not router.get("speech"):
                m.setdefault("findings", []).append(
                    "Audio present but no speech model is assigned (AI_SPEECH); paste the transcript to fact-check it")
            continue
        if not tr.get("transcript_en") and tr.get("language") not in ("en", "") :
            en = use("translation", lambda p: p.translate({"t": tr["transcript"]}, "en"))
            tr["transcript_en"] = (en or {}).get("t", "")
        m.update({"transcript": tr["transcript"], "transcript_en": tr.get("transcript_en", ""),
                  "transcript_language": tr.get("language", ""), "transcription_available": True})

    claim_parts = [inputs.get("text") or "", inputs.get("transcript") or ""]
    if url_result and url_result.get("ok"):
        claim_parts.append(f"{url_result['title']}. {url_result['text'][:3000]}")
    elif url_result:
        warnings.append(url_result["error"])
    for m in media_results:
        if m.get("transcript"):
            claim_parts.append(m["transcript"])
        if m.get("error"):
            warnings.append(m["error"])
    claim_parts.extend(ocr_texts)

    for m in media_results:
        if m.get("transcript_en"):
            claim_parts.append(m["transcript_en"])
    claim = "\n".join(p for p in claim_parts if p.strip())
    lang = language.detect(claim)

    text_result = text.analyze_claim(claim, url)
    reply = inputs.get("reply_language") or "auto"
    reply_code = lang["code"] if reply == "auto" else reply

    # ---- RESEARCH role (+ TRANSLATION in the same call when one model holds both roles: one round trip)
    found = None
    if text_result.get("present"):
        rp, tp = router.get("research"), router.get("translation")
        same = rp is not None and tp is not None and rp.id == tp.id
        found = use("research", lambda p: p.research(claim, text_result.get("matched_scheme"),
                                                    reply_code if same else None))
        if found and found.get("localized"):
            team.append({"role": "translation", "provider": tp.id, "name": tp.name, "model": tp.model_for("research"),
                         "specialist": "translation" in tp.specialist_roles, "seconds": 0, "note": "combined with research"})

    # ---- TRANSLATION role: claim -> English for the rule engine and registry
    claim_en = (found or {}).get("claim_en") or ""
    if lang["code"] != "en" and not claim_en and text_result.get("present"):
        claim_en = (use("translation", lambda p: p.translate({"claim": claim[:6000]}, "en")) or {}).get("claim", "")
    if claim_en and lang["code"] != "en":
        text_result = text.analyze_claim(claim_en + "\n" + claim, url)
    if found:
        found["language"] = lang

    # ---- TRANSLATION role: verdict -> the citizen's language (if research did not already do it)
    if found and reply_code != "en" and not found.get("localized") and found.get("summary"):
        loc = use("translation", lambda p: p.translate(
            {"summary": found["summary"], "advice": found.get("advice", "")}, reply_code))
        if loc:
            found["localized"] = {"lang": reply_code, **loc}
    if found and found.get("localized"):
        found["localized"]["lang_name"] = language.name_for(found["localized"]["lang"])

    # ---- REVIEW role
    ai = use("review", lambda p: p.review(claim, text_result.get("matched_scheme"))) if text_result.get("present") else None

    rule_score = text_result.get("score")
    text_score = rule_score
    if rule_score is not None:
        parts = [(rule_score, 0.45)]
        if found and found.get("authenticity") is not None:
            parts.append((found["authenticity"], 0.40 if found.get("grounded") else 0.15))
        if ai and "authenticity" in ai:
            parts.append((ai["authenticity"], 0.15))
        text_score = sum(v * w for v, w in parts) / sum(w for _, w in parts)
        if found and found.get("grounded") and found.get("verdict") == "fraudulent":
            text_score = min(text_score, 0.3)
        if found and found.get("already_debunked"):
            text_score = min(text_score, 0.25)

    tampers = [m["tamper_score"] for m in media_results if m.get("tamper_score") is not None]
    media_tamper = max(tampers) if tampers else None
    deepfake = bool(media_tamper is not None and media_tamper >= 0.6)

    if text_score is not None and media_tamper is not None:
        authenticity = 0.5 * text_score + 0.5 * (1 - media_tamper)
    elif text_score is not None:
        authenticity = text_score
    elif media_tamper is not None:
        authenticity = min(0.7, 1 - media_tamper)       # clean media alone cannot confirm the facts
        warnings.append("No claim text to check against the registry. Add the caption, transcript or link.")
    else:
        authenticity = 0.0
        warnings.append("Nothing to analyse.")
    if deepfake:
        authenticity = min(authenticity, 0.3)
    if text_result.get("contradictions") and any(c["severity"] == "high" for c in text_result["contradictions"]):
        authenticity = min(authenticity, 0.45)
    authenticity = round(max(0.0, min(1.0, authenticity)), 2)

    scheme = text_result.get("matched_scheme")
    low_res = any(m.get("low_resolution_confidence_degraded") for m in media_results)
    if low_res:
        warnings.append("low_resolution_confidence_degraded: media below 240p, editing artifacts are less reliable.")

    if authenticity >= config.AUTHENTICITY_THRESHOLD:
        verdict = "authentic"
    elif authenticity >= 0.4:
        verdict = "unverified"
    else:
        verdict = "likely_fraudulent"

    agent_allowed = verdict == "authentic" and scheme is not None and not deepfake
    if verdict == "authentic" and scheme is None:
        warnings.append("Claim looks clean but does not match any scheme in the registry, so no portal route is available.")

    return {
        "authenticity": authenticity,
        "manipulationScore": round(1 - authenticity, 2),
        "verdict": verdict,
        "deepfakeDetected": deepfake,
        "agentAllowed": agent_allowed,
        "threshold": config.AUTHENTICITY_THRESHOLD,
        "low_resolution_confidence_degraded": low_res,
        "claim_text": claim[:6000],
        "text": {**{k: v for k, v in text_result.items() if k != "matched_scheme"}, "score": text_result.get("score")},
        "matched_scheme": _public_scheme(scheme),
        "media": media_results,
        "url": url_result,
        "ai_review": ai,
        "research": found,
        "language": lang,
        "reply_language": {"code": reply_code, "name": language.name_for(reply_code)},
        "claim_en": claim_en,
        "ai_team": team,
        "rule_score": rule_score,
        "warnings": warnings,
    }
