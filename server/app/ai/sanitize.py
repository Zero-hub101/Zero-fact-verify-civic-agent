"""Check every AI answer before the pipeline uses it.

Providers parse their own replies, but a model can still return the wrong shape (a list instead of an object,
a number as text, a missing field). One malformed answer must never break the whole check, so each role's
result is coerced to the shape the pipeline expects; anything unusable becomes None (treated as "no answer").
"""
import math
from typing import Any, Optional


def _str(v: Any, limit: int = 6000) -> str:
    return v[:limit] if isinstance(v, str) else ""


def _prob(v: Any) -> Optional[float]:
    """A probability in 0..1, or None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return max(0.0, min(1.0, f))


def _strs(v: Any, n: int = 20, limit: int = 600) -> list[str]:
    return [x[:limit] for x in v if isinstance(x, str) and x.strip()][:n] if isinstance(v, list) else []


def _dicts(v: Any, n: int = 30) -> list[dict]:
    return [x for x in v if isinstance(x, dict)][:n] if isinstance(v, list) else []


def _ocr(r: dict) -> Optional[dict]:
    return {"text": _str(r.get("text")), "language": _str(r.get("language"), 10)}


def _vision(r: dict) -> Optional[dict]:
    return {"description": _str(r.get("description"), 400), "text_in_image": _str(r.get("text_in_image"), 3000),
            "claims": _strs(r.get("claims"), 10, 300), "red_flags": _strs(r.get("red_flags"), 10, 300)}


def _image_ai(r: dict) -> Optional[dict]:
    ai, df = _prob(r.get("ai_generated")), _prob(r.get("deepfake"))
    if ai is None and df is None:
        return None
    out = {**{k: v for k, v in r.items() if k in ("cached", "frame_time", "model") and isinstance(v, (str, int, float, bool))},
           "ai_generated": ai, "deepfake": df}
    if out.get("frame_time") is not None and not isinstance(out["frame_time"], (int, float)):
        out.pop("frame_time")
    return out


def _speech(r: dict) -> Optional[dict]:
    t = _str(r.get("transcript"), 20000)
    return {"transcript": t, "transcript_en": _str(r.get("transcript_en"), 20000),
            "language": _str(r.get("language"), 10)} if t else None


def _translation(r: dict) -> Optional[dict]:
    out = {k: v[:6000] for k, v in r.items() if isinstance(k, str) and isinstance(v, str)}
    return out or None


def _research(r: dict) -> Optional[dict]:
    verdict = r.get("verdict") if r.get("verdict") in ("authentic", "misleading", "fraudulent", "unverifiable") \
        else "unverifiable"
    findings = []
    for f in _dicts(r.get("findings")):
        status = f.get("status") if f.get("status") in ("supported", "contradicted", "unverified") else "unverified"
        findings.append({**{k: v for k, v in f.items() if k == "source_ids" and isinstance(v, list)},
                         "point": _str(f.get("point"), 300), "status": status, "evidence": _str(f.get("evidence"), 600)})
    sources = [{k: v for k, v in s.items() if isinstance(v, (str, int, float, bool))} for s in _dicts(r.get("sources"))]
    loc = r.get("localized")
    localized = None
    if isinstance(loc, dict) and isinstance(loc.get("lang"), str) and _str(loc.get("summary")):
        localized = {"lang": loc["lang"][:10], "summary": _str(loc.get("summary"), 1500),
                     "advice": _str(loc.get("advice"), 800)}
    lang = r.get("language") if isinstance(r.get("language"), dict) else None
    return {**{k: v for k, v in r.items() if k in ("provider", "model", "api", "official_source_name") and isinstance(v, str)},
            "seconds": r.get("seconds") if isinstance(r.get("seconds"), (int, float)) else 0,
            "language": lang, "claim_en": _str(r.get("claim_en")), "verdict": verdict,
            "authenticity": _prob(r.get("authenticity")), "already_debunked": r.get("already_debunked") is True,
            "findings": findings, "sources": sources[:20], "search_queries": _strs(r.get("search_queries"), 10, 200),
            "summary": _str(r.get("summary"), 1500), "advice": _str(r.get("advice"), 800), "localized": localized,
            "grounded": bool(sources) and r.get("grounded") is not False,
            "search_unavailable": r.get("search_unavailable") is True, "parse_ok": r.get("parse_ok") is not False}


def _review(r: dict) -> Optional[dict]:
    out = {k: v for k, v in r.items() if isinstance(v, (str, int, float, bool)) and k not in ("authenticity",)}
    out["verdict"] = _str(r.get("verdict"), 40)
    out["reasons"] = _strs(r.get("reasons"), 8, 400)
    a = _prob(r.get("authenticity"))
    if a is not None:
        out["authenticity"] = a
    return out


def _voice(r: Any) -> Optional[tuple]:
    if isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], (bytes, bytearray)) and isinstance(r[1], str) \
            and r[1].isalnum() and len(r[1]) <= 5:
        return bytes(r[0]), r[1].lower()
    return None


_BY_ROLE = {"ocr": _ocr, "vision": _vision, "image_ai": _image_ai, "speech": _speech, "translation": _translation,
            "research": _research, "review": _review}


def clean(role: str, result: Any) -> Any:
    """Return the result in the expected shape, or None if it cannot be used."""
    if role == "voice":
        return _voice(result)
    fn = _BY_ROLE.get(role)
    if fn is None:
        return result
    if not isinstance(result, dict):
        return None
    try:
        return fn(result)
    except Exception:  # noqa: BLE001 - a malformed answer is simply no answer
        return None
