"""Verification pipeline: runs text, URL and media analysis in parallel and combines them into one score."""
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from . import config, plain
from .ai import cache, router, sanitize
from .forensics import language, media, sources, text

log = logging.getLogger("factverify.pipeline")


def _public_scheme(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    return {k: s[k] for k in ("id", "name", "summary", "benefit_amount", "benefit_period", "application_fee",
                              "income_limit", "deadline", "eligibility", "official_domains", "playbook", "source")
            } | {"official_url": s.get("official_url")}


def _extract_audio(video: Path, out_dir: str) -> Optional[Path]:
    if not shutil.which("ffmpeg"):
        return None
    audio = Path(out_dir) / "audio.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "48k", "-t", "600", str(audio)], capture_output=True, timeout=180)
    return audio if audio.exists() and audio.stat().st_size > 2000 else None


def _check_video_frames(res: dict, use) -> Optional[dict]:
    """Send up to 3 frames (flagged first, then the middle one) to the IMAGE_AI role."""
    frames = res["frames"]
    picks = [f for f in frames if f.get("flagged")][:2] + [frames[len(frames) // 2]]
    best = None
    for fr in list({id(f): f for f in picks}.values())[:3]:
        path = config.ARTIFACT_DIR / fr["thumb_url"].rsplit("/", 1)[-1]
        det = use("image_ai", lambda pr, path=path: pr.detect_ai_image(path))
        if det:
            score = max(det.get("ai_generated") or 0, det.get("deepfake") or 0)
            fr["ai_generated"] = round(score, 3)
            if best is None or score > max(best.get("ai_generated") or 0, best.get("deepfake") or 0):
                best = {**det, "frame_time": fr["time"]}
    return best


def _apply_ai_detection(res: dict, det: dict) -> None:
    ai = det.get("ai_generated") or 0
    df = det.get("deepfake") or 0
    res["ai_detection"] = {"ai_generated": round(ai, 3), "deepfake": round(df, 3) if det.get("deepfake") is not None
                           else None, "frame_time": det.get("frame_time")}
    res.setdefault("signals", {})["ai_generated"] = round(max(ai, df), 3)
    score = max(ai, df)
    if score >= 0.7:
        res["tamper_score"] = round(max(res.get("tamper_score") or 0, score), 3)
        what = "a face deepfake" if df >= ai else "fully AI-generated"
        where = f" (frame at {det['frame_time']}s)" if det.get("frame_time") is not None else ""
        res.setdefault("findings", []).insert(0, f"AI detector: {round(score * 100)}% likely {what}{where}")
        res["findings"] = [f for f in res["findings"] if not f.startswith("No manipulation signals")]


def _spoken_summary(verdict: str, authenticity: float, found: Optional[dict], scheme: Optional[dict],
                    deepfake: bool) -> str:
    if found and found.get("summary"):
        return f"{found['summary']} {found.get('advice', '')}".strip()
    head = {"authentic": "This claim appears genuine.", "unverified": "This claim could not be verified.",
            "likely_fraudulent": "Warning. This claim is likely fraudulent.",
            "off_topic": "This does not look like a government scheme or public-service claim."}.get(
                verdict, "This claim could not be verified.")
    parts = [head, f"Trust score {round(authenticity * 100)} out of 100."]
    if deepfake:
        parts.append("The image or video shows signs of manipulation.")
    if scheme:
        fee = "free" if not scheme["application_fee"] else f"Rs {scheme['application_fee']}"
        parts.append(f"The official {scheme['name']} gives Rs {scheme['benefit_amount']:,} {scheme['benefit_period']}, "
                     f"and applying is {fee}.")
    if verdict != "authentic":
        parts.append("Do not pay any fee or share your OTP.")
    return " ".join(parts)


CIVIC_WORDS = re.compile(
    r"scheme|scholarship|yojana|pension|subsid|government|govt|ministry|department|benefit|grant|ration|aadhaar|"
    r"pan card|loan|portal|apply|application|registration|eligib|deadline|last date|fee|otp|upui?|refund|"
    r"certificate|welfare|stipend|allowance|official|notice|announcement|sarkari|"
    r"सरकार|योजना|छात्रवृत्ति|पेंशन|शुल्क|आवेदन|அரசு|திட்டம்|உதவித்தொகை|ప్రభుత్వ|పథకం|ಸರ್ಕಾರ|ಯೋಜನೆ",
    re.IGNORECASE)


def _off_topic(claim: str, scheme: Optional[dict], text_result: dict, media_tamper, found: Optional[dict]) -> bool:
    if scheme or text_result.get("scam_flags") or text_result.get("contradictions"):
        return False
    if media_tamper is not None and media_tamper >= 0.6:
        return False                                   # manipulated media is always worth reporting
    if found and found.get("grounded") and found.get("verdict") in ("fraudulent", "misleading"):
        return False
    return not CIVIC_WORDS.search(claim or "")


def run(inputs: dict) -> dict:
    t_start = time.time()
    files = inputs.get("files", [])
    url = inputs.get("url") or None
    warnings: list[str] = []
    if inputs.get("truncated"):
        warnings.append("Your message was very long, so only the first 4,000 characters were checked.")

    team: list[dict] = []                         # which model did which job in this run
    lock = threading.Lock()

    def use(role, fn):
        result, credit = router.call(role, fn)
        with lock:
            if credit:
                team.append(credit)
            if isinstance(result, dict) and result.get("error"):
                warnings.append(result["error"])
                return None
        return sanitize.clean(role, result)

    def translate(texts: dict, target: str):
        """Translation role, remembered per text so repeat runs (and the spoken reply built from it) are stable."""
        tp = router.get("translation")
        ck = cache.key("translation", router.assigned("translation"), texts, target)
        hit = cache.get("translation", ck)
        if hit is not None and tp:
            with lock:
                team.append({"role": "translation", "provider": tp.id, "name": tp.name, "model": tp.model_for("translation"),
                             "specialist": "translation" in tp.specialist_roles, "seconds": 0, "note": "cached"})
            return hit
        out = use("translation", lambda p: p.translate(texts, target))
        if out:
            cache.put("translation", ck, out)
        return out

    lang_hint = language.detect(inputs.get("text") or "")["code"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        url_future = pool.submit(sources.fetch_url_text, url) if url else None
        media_futures = []
        for f in files:
            p = Path(f["path"])
            if f["kind"] == "image":
                media_futures.append((f, p, pool.submit(media.analyze_image, p, Path(f["name"]).stem[:40]), {
                    # ---- OCR, IMAGE_AI and VISION roles run in parallel with local forensics
                    "ocr": pool.submit(use, "ocr", lambda pr, p=p: pr.ocr(p, lang_hint)),
                    "image_ai": pool.submit(use, "image_ai", lambda pr, p=p: pr.detect_ai_image(p)),
                    "vision": pool.submit(use, "vision", lambda pr, p=p: pr.describe_image(p)),
                }))
            elif f["kind"] == "video":
                media_futures.append((f, p, pool.submit(media.analyze_video, p), {}))

        url_result = url_future.result() if url_future else None
        media_results, ocr_texts = [], []
        for f, p, fut, extra in media_futures:
            res = fut.result()
            res["file_name"] = f["name"]
            res["media_url"] = f["public_url"]
            ocr = extra["ocr"].result() if extra else None
            if ocr and ocr.get("text"):
                res["ocr_text"] = ocr["text"]
                ocr_texts.append(ocr["text"])
            vis = extra["vision"].result() if extra else None
            if vis:
                res["vision"] = vis
                if not (ocr and ocr.get("text")) and vis.get("text_in_image"):
                    ocr_texts.append(vis["text_in_image"])
            det = extra["image_ai"].result() if extra else None
            if res["kind"] == "video" and res.get("frames"):
                det = _check_video_frames(res, use)
            if det:
                _apply_ai_detection(res, det)
            media_results.append(res)

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
            en = translate({"t": tr["transcript"]}, "en")
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
    # Nothing civic about it (no scheme, no warning signs, no civic words, no media)? Skip the paid AI research and
    # review: it saves time and credits, and the verdict stays a clean "off topic" instead of mixed AI opinions.
    clearly_off = (not text_result.get("matched_scheme") and not text_result.get("scam_flags")
                   and not text_result.get("contradictions") and not files and not CIVIC_WORDS.search(claim or ""))
    if text_result.get("present") and not clearly_off:
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
        claim_en = (translate({"claim": claim[:6000]}, "en") or {}).get("claim", "")
    if claim_en and lang["code"] != "en":
        text_result = text.analyze_claim(claim_en + "\n" + claim, url)
    if found:
        found["language"] = lang

    # ---- TRANSLATION role: verdict -> the citizen's language (if research did not already do it)
    if found and reply_code != "en" and not found.get("localized") and found.get("summary"):
        loc = translate({"summary": found["summary"], "advice": found.get("advice", "")}, reply_code)
        if loc:
            found["localized"] = {"lang": reply_code, **loc}
    if found and found.get("localized"):
        found["localized"]["lang_name"] = language.name_for(found["localized"]["lang"])

    # ---- REVIEW role
    ai = use("review", lambda p: p.review(claim, text_result.get("matched_scheme"))) \
        if text_result.get("present") and not clearly_off else None

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

    # Guardrail: off-topic input (a selfie, a random question) gets no trust verdict at all.
    if _off_topic(claim, scheme, text_result, media_tamper, found):
        verdict = "off_topic"

    agent_allowed = verdict == "authentic" and scheme is not None and bool(scheme.get("playbook")) and not deepfake
    if verdict == "authentic" and scheme is None:
        warnings.append("Claim looks clean but does not match any scheme in the registry, so no portal route is available.")

    # ---- VOICE role: speak the verdict in the citizen's language
    voice = None
    if verdict != "off_topic":
        spoken_lang, spoken = "en", _spoken_summary(verdict, authenticity, found, scheme, deepfake)
        loc = (found or {}).get("localized")
        if reply_code != "en":
            if loc and loc.get("summary"):
                spoken_lang, spoken = reply_code, f"{loc['summary']} {loc.get('advice', '')}".strip()
            else:
                tr = translate({"t": spoken}, reply_code)
                if tr and tr.get("t"):
                    spoken_lang, spoken = reply_code, tr["t"]
        # The text always goes back, so the page can read it aloud with the browser's own voice
        # when no voice service is available (no key, or out of credits).
        voice = {"url": None, "lang": spoken_lang, "lang_name": language.name_for(spoken_lang), "text": spoken}
        # Audio is made only when the citizen presses Listen (speak() below): voice services can take
        # 5-20 s, and the verdict should not wait for that.
        voice["service"] = router.get("voice") is not None

    # ---- Plain-language explanation for citizens (translated when they asked for another language)
    explain = plain.build(verdict, scheme, text_result, media_results, found, deepfake)
    explain["lang"] = "en"
    if reply_code != "en":
        flat = {"h": explain["headline"], **{f"w{i}": w for i, w in enumerate(explain["why"])},
                **{f"d{i}": d for i, d in enumerate(explain["do"])}}
        tr = translate(flat, reply_code)
        if tr and tr.get("h"):
            explain = {"headline": tr["h"], "why": [tr.get(f"w{i}") or w for i, w in enumerate(explain["why"])],
                       "do": [tr.get(f"d{i}") or d for i, d in enumerate(explain["do"])], "lang": reply_code,
                       "english": explain}

    return {
        "plain": explain,
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
        "ai_review": ai if ai else {"status": "skipped", "reason": (
            "Not about a government scheme, so no AI review was needed." if clearly_off else
            "No AI review service was available.")},
        "research": found if found else {"status": "skipped", "reason": (
            "Not about a government scheme, so no AI research was needed." if clearly_off else
            "No AI research service was available or the message had no text.")},
        "seconds": round(time.time() - t_start, 1),
        "language": lang,
        "reply_language": {"code": reply_code, "name": language.name_for(reply_code)},
        "claim_en": claim_en,
        "ai_team": team,
        "voice": voice,
        "rule_score": rule_score,
        "warnings": warnings,
    }


def speak(text_: str, lang: str) -> dict:
    """VOICE role on demand: read a verdict aloud. Remembered per text, so pressing Listen again is instant."""
    text_ = (text_ or "").strip()[:2500]
    if not text_:
        return {"error": "Nothing to read."}
    vp = router.get("voice")
    if not vp:
        return {"error": "No voice service is set up."}
    vkey = cache.key("voice", router.assigned("voice"), lang, text_)
    audio, credit = cache.get_bytes("voice", vkey), {"provider": vp.id, "name": vp.name, "note": "cached"}
    if not audio:
        audio, credit = router.call("voice", lambda p: p.speak(text_, lang))
        if isinstance(audio, dict) and audio.get("error"):
            return {"error": audio["error"]}
        audio = sanitize.clean("voice", audio)
        if not audio:
            return {"error": "The voice service returned no audio."}
        cache.put_bytes("voice", vkey, audio[0], audio[1])
    name = f"voice_{vkey[:16]}.{audio[1]}"
    path = config.ARTIFACT_DIR / name
    if not path.exists():
        path.write_bytes(audio[0])
    return {"url": f"/artifacts/{name}", "lang": lang, "lang_name": language.name_for(lang), "credit": credit}
