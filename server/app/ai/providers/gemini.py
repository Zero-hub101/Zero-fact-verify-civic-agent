"""Google Gemini provider. Specialist role: RESEARCH (live web search with Grounding with Google Search).

Every finding carries the web sources Gemini actually retrieved (grounding citations), so each verdict
can be checked by a person. Gemini can also stand in for the translation and speech roles until a
specialist model is assigned to them in .env.

Two Gemini REST surfaces are supported and tried in order:
  1. Interactions API   POST /v1beta/interactions          (current docs)
  2. generateContent    POST /v1beta/models/{m}:generateContent (long-standing)
Models are tried in order: GEMINI_MODEL, then GEMINI_FALLBACK_MODELS.
"""
import base64
import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator, Optional

from ... import config
from ...forensics import language
from ..base import Provider, ProviderError

log = logging.getLogger("factverify.research")
API = "https://generativelanguage.googleapis.com/v1beta"
FACT_CHECKERS = ["pib.gov.in (PIB Fact Check)", "factly.in", "boomlive.in", "altnews.in", "vishvasnews.com",
                 "newschecker.in", "thequint.com/news/webqoof", "indiatoday.in/fact-check"]


class GeminiError(ProviderError):
    pass


def enabled() -> bool:
    return bool(config.GEMINI_API_KEY)


def _models(primary: str) -> list[str]:
    out = [primary] + [m.strip() for m in config.GEMINI_FALLBACK_MODELS.split(",")]
    return list(dict.fromkeys(m for m in out if m))


def _post(url: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:400]
        raise GeminiError(f"HTTP {e.code}: {detail}", e.code)
    except (urllib.error.URLError, TimeoutError) as e:
        raise GeminiError(f"Network error: {e}")


# ---------------- response parsing (tolerant to both API shapes) ----------------
def _walk(o: Any) -> Iterator[dict]:
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def parse_interactions(resp: dict) -> dict:
    steps = resp.get("steps") or resp.get("outputs") or []
    text_blocks: list[dict] = []
    for step in steps:                                   # final answer lives in model output steps
        stype = str(step.get("type", ""))
        if "search" in stype or stype == "thought":
            continue
        for d in _walk(step.get("content", step)):
            if d.get("type") == "text" and isinstance(d.get("text"), str):
                text_blocks.append(d)
    if not text_blocks:
        text_blocks = [d for d in _walk(resp) if d.get("type") == "text" and isinstance(d.get("text"), str)]
    text, citations, offset = "", [], 0
    for blk in text_blocks:
        for a in blk.get("annotations", []) or []:
            if a.get("url") or a.get("uri"):
                citations.append({"url": a.get("url") or a.get("uri"), "title": a.get("title") or "",
                                  "start": offset + int(a.get("start_index", 0) or 0),
                                  "end": offset + int(a.get("end_index", 0) or 0)})
        text += blk["text"]
        offset = len(text)
    queries = []
    for d in _walk(resp):
        for key in ("queries", "webSearchQueries", "web_search_queries"):
            if isinstance(d.get(key), list):
                queries += [q for q in d[key] if isinstance(q, str)]
    return {"text": text, "citations": citations, "queries": list(dict.fromkeys(queries))}


def _byte_to_char(text: str, b: int) -> int:
    return len(text.encode("utf-8")[:b].decode("utf-8", errors="ignore"))


def parse_generate_content(resp: dict) -> dict:
    cands = resp.get("candidates") or []
    if not cands:
        raise GeminiError(f"No candidates returned: {json.dumps(resp)[:300]}")
    cand = cands[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    gm = cand.get("groundingMetadata") or cand.get("grounding_metadata") or {}
    chunks = gm.get("groundingChunks") or gm.get("grounding_chunks") or []
    citations = []
    for sup in gm.get("groundingSupports") or gm.get("grounding_supports") or []:
        seg = sup.get("segment", {})
        s = _byte_to_char(text, int(seg.get("startIndex", seg.get("start_index", 0)) or 0))
        e = _byte_to_char(text, int(seg.get("endIndex", seg.get("end_index", 0)) or 0))
        for i in sup.get("groundingChunkIndices") or sup.get("grounding_chunk_indices") or []:
            if i < len(chunks) and chunks[i].get("web"):
                citations.append({"url": chunks[i]["web"].get("uri"), "title": chunks[i]["web"].get("title", ""),
                                  "start": s, "end": e})
    for c in chunks:                                     # sources retrieved but not tied to a sentence
        if c.get("web") and not any(x["url"] == c["web"].get("uri") for x in citations):
            citations.append({"url": c["web"].get("uri"), "title": c["web"].get("title", ""), "start": -1, "end": -1})
    queries = gm.get("webSearchQueries") or gm.get("web_search_queries") or []
    return {"text": text, "citations": citations, "queries": queries}


def extract_json(text: str) -> Optional[dict]:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [m.group(1)] if m else []
    if "{" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


# ---------------- calling Gemini ----------------
def _call(prompt: str, model: str, use_search: bool, parts: Optional[list] = None, timeout: int = 120) -> dict:
    """Try the Interactions API, then generateContent. Returns parsed {text, citations, queries, api}."""
    errors = []
    body: dict = {"model": model, "store": False}
    if parts:
        body["input"] = [{"type": "text", "text": prompt}] + [
            {"type": p["kind"], "data": p["data"], "mime_type": p["mime_type"]} for p in parts]
    else:
        body["input"] = prompt
    if use_search:
        body["tools"] = [{"type": "google_search"}]
    try:
        parsed = parse_interactions(_post(f"{API}/interactions", body, timeout))
        if parsed["text"].strip():
            return {**parsed, "api": "interactions"}
        errors.append("interactions: empty response")
    except GeminiError as e:
        if e.status in (401, 403):
            raise
        errors.append(f"interactions: {e}")

    gc_parts: list[dict] = [{"text": prompt}] + [
        {"inline_data": {"mime_type": p["mime_type"], "data": p["data"]}} for p in (parts or [])]
    gc_body: dict = {"contents": [{"role": "user", "parts": gc_parts}]}
    if use_search:
        gc_body["tools"] = [{"google_search": {}}]
    try:
        parsed = parse_generate_content(_post(f"{API}/models/{model}:generateContent", gc_body, timeout))
        return {**parsed, "api": "generateContent"}
    except GeminiError as e:
        if e.status in (401, 403):
            raise
        errors.append(f"generateContent: {e}")
    raise GeminiError(" | ".join(errors), 404)


_search_blocked_until = 0.0    # set when the key has no quota for Google Search grounding


def _call_with_fallback(prompt: str, primary: str, use_search: bool, parts: Optional[list] = None) -> dict:
    global _search_blocked_until
    if use_search and time.time() < _search_blocked_until:
        out = _call_with_fallback(prompt, primary, use_search=False, parts=parts)
        out["search_unavailable"] = True
        return out
    errors = []
    for model in _models(primary):
        try:
            t0 = time.time()
            out = _call(prompt, model, use_search, parts)
            out["model"] = model
            out["seconds"] = round(time.time() - t0, 1)
            return out
        except GeminiError as e:
            errors.append(f"{model}: {e}")
            if e.status in (401, 403):
                break
            log.warning("Gemini model %s failed: %s", model, e)
    joined = " || ".join(errors)
    if use_search and ("429" in joined or "quota" in joined.lower() or "RESOURCE_EXHAUSTED" in joined):
        # Free keys often have no quota for Google Search grounding. Answer without it, clearly marked.
        log.warning("Gemini search grounding unavailable (quota); retrying without search")
        _search_blocked_until = time.time() + 600
        out = _call_with_fallback(prompt, primary, use_search=False, parts=parts)
        out["search_unavailable"] = True
        return out
    raise GeminiError(joined[:900])


# ---------------- research ----------------
RESEARCH_PROMPT = """You are a meticulous public-service fact checker for Indian citizens.
Research the CLAIM below using Google Search before answering.

Rules:
- Prefer official sources: *.gov.in, *.nic.in, pib.gov.in (including PIB Fact Check), state government sites, official scheme portals.
- Also check whether reputable fact-checkers ({fact_checkers}) have already debunked it.
- Check every concrete detail: scheme name, benefit amount, fees, eligibility, income limit, deadline, how and where to apply, contact numbers/UPI IDs/links.
- Legitimate government schemes never ask for fees via personal UPI IDs, OTPs or WhatsApp. Treat that as a strong fraud signal.
- Base each finding only on what you found. Never invent sources. If you found nothing, mark it "unverified".
- The claim may be in any language or code-mixed. Translate it faithfully.
{reference}
Return ONLY a JSON object (no prose before or after) with exactly these keys:
{{
  "claim_language": "ISO 639-1 code of the claim, e.g. hi, ta, en",
  "claim_en": "faithful English translation of the claim",
  "verdict": "authentic" | "misleading" | "fraudulent" | "unverifiable",
  "authenticity": number between 0 and 1,
  "already_debunked": true | false,
  "findings": [
    {{"point": "the specific detail checked (English)", "status": "supported" | "contradicted" | "unverified",
      "evidence": "one sentence stating what the official/reputable source says"}}
  ],
  "official_source_name": "name of the most authoritative source you found, or empty",
  "summary": "2-3 sentence verdict in English",
  "advice": "one or two sentences of practical advice for the citizen, in English"{local_keys}
}}

CLAIM:
\"\"\"{claim}\"\"\"
"""


def _overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def _source_entry(c: dict) -> dict:
    from ...forensics.text import domain_trust
    label = c.get("title") or ""
    host_hint = label if re.match(r"^[\w.-]+\.[a-z]{2,}$", label) else (re.sub(r"^https?://", "", c["url"]).split("/")[0])
    trust = domain_trust(host_hint)["trust"]
    if any(fc.split(" ")[0] in host_hint for fc in FACT_CHECKERS):
        trust = "fact_checker"
    return {"url": c["url"], "title": label or host_hint, "host": host_hint, "trust": trust}


def research_claim(claim: str, scheme: Optional[dict], reply_lang: Optional[str] = None) -> Optional[dict]:
    """Run grounded research. If reply_lang is given, the localised verdict is written in the same call
    (saves a round trip when Gemini also holds the translation role)."""
    if not enabled() or not claim.strip():
        return None
    detected = language.detect(claim)
    reply_code = reply_lang
    reference = ""
    if scheme:
        reference = ("\nInternal registry record (may be outdated; verify it too): " + json.dumps(
            {k: scheme[k] for k in ("name", "benefit_amount", "benefit_period", "application_fee", "income_limit",
                                    "deadline", "official_domains") if k in scheme}) + "\n")
    local_keys = "" if not reply_code or reply_code == "en" else (
        f',\n  "summary_local": "the same verdict written in {language.name_for(reply_code)}",'
        f'\n  "advice_local": "the same advice written in {language.name_for(reply_code)}"')
    prompt = RESEARCH_PROMPT.format(fact_checkers=", ".join(FACT_CHECKERS), reference=reference,
                                    local_keys=local_keys, claim=claim[:6000])
    try:
        raw = _call_with_fallback(prompt, config.GEMINI_MODEL, use_search=True)
    except GeminiError as e:
        return {"error": f"Gemini research unavailable: {e}", "language": detected}
    data_reply = reply_code

    data = extract_json(raw["text"]) or {}
    text = raw["text"]
    sources, seen = [], {}
    for c in raw["citations"]:
        if c.get("url") and c["url"] not in seen:
            seen[c["url"]] = len(sources)
            sources.append(_source_entry(c))

    findings = []
    for f in data.get("findings", [])[:12]:
        if not isinstance(f, dict):
            continue
        idx = set()
        for field in ("evidence", "point"):
            val = str(f.get(field, ""))
            pos = text.find(val[:80]) if val else -1
            if pos >= 0:
                span = (pos, pos + len(val))
                idx |= {seen[c["url"]] for c in raw["citations"]
                        if c.get("url") in seen and c["start"] >= 0 and _overlap(span[0], span[1], c["start"], c["end"])}
        status = f.get("status") if f.get("status") in ("supported", "contradicted", "unverified") else "unverified"
        findings.append({"point": str(f.get("point", ""))[:300], "status": status,
                         "evidence": str(f.get("evidence", ""))[:600], "source_ids": sorted(idx)})

    try:
        authenticity = max(0.0, min(1.0, float(data.get("authenticity"))))
    except (TypeError, ValueError):
        authenticity = None
    verdict = data.get("verdict") if data.get("verdict") in ("authentic", "misleading", "fraudulent", "unverifiable") \
        else "unverifiable"
    grounded = len(sources) > 0
    if not grounded and authenticity is not None:
        authenticity = 0.5 + (authenticity - 0.5) * 0.4     # unsourced opinion counts for little
    return {
        "provider": "Google Gemini" + ("" if raw.get("search_unavailable") else " + Grounding with Google Search"),
        "search_unavailable": bool(raw.get("search_unavailable")),
        "model": raw["model"], "api": raw["api"], "seconds": raw["seconds"],
        "language": detected,
        "claim_en": str(data.get("claim_en") or "")[:6000],
        "verdict": verdict, "authenticity": authenticity, "already_debunked": bool(data.get("already_debunked")),
        "findings": findings, "sources": sources[:20], "search_queries": raw["queries"][:10],
        "official_source_name": str(data.get("official_source_name") or ""),
        "summary": str(data.get("summary") or (text if not data else ""))[:1500],
        "advice": str(data.get("advice") or "")[:800],
        "localized": ({"lang": data_reply, "summary": str(data.get("summary_local") or "")[:1500],
                       "advice": str(data.get("advice_local") or "")[:800]}
                      if data_reply and data_reply != "en" and data.get("summary_local") else None),
        "grounded": grounded,
        "parse_ok": bool(data),
    }


# ---------------- stand-in roles: speech and translation ----------------
TRANSCRIBE_PROMPT = """Transcribe the speech in this audio exactly, in its original language and script.
Then translate it to English. Return ONLY JSON:
{"language": "ISO 639-1 code", "transcript": "original-language transcript", "transcript_en": "English translation"}"""


def transcribe_mp3(audio: Path) -> dict:
    data = base64.b64encode(audio.read_bytes()).decode()
    raw = _call_with_fallback(TRANSCRIBE_PROMPT, config.GEMINI_FAST_MODEL, use_search=False,
                              parts=[{"kind": "audio", "mime_type": "audio/mp3", "data": data}])
    parsed = extract_json(raw["text"]) or {"transcript": raw["text"], "transcript_en": "", "language": ""}
    parsed["model"] = raw["model"]
    return parsed


TRANSLATE_PROMPT = """Translate every value in this JSON object into {lang}. Keep the keys unchanged.
Use simple, clear words a citizen would understand; keep numbers, amounts, URLs and names exact.
Return ONLY the JSON object.

{payload}"""


def translate_texts(texts: dict, target: str) -> dict:
    raw = _call_with_fallback(TRANSLATE_PROMPT.format(lang=language.name_for(target),
                                                      payload=json.dumps(texts, ensure_ascii=False)),
                              config.GEMINI_FAST_MODEL, use_search=False)
    out = extract_json(raw["text"]) or {}
    return {k: str(out.get(k) or v) for k, v in texts.items()}


VISION_PROMPT = """Describe this image for a fact-checker. Return ONLY JSON:
{"description": "one sentence", "text_in_image": "all readable text, original language",
 "claims": ["factual claims made (amounts, fees, deadlines, contacts)"],
 "red_flags": ["visual signs of fraud or editing"]}"""


def describe_image(path: Path) -> dict:
    from ..util import shrink_image
    small = shrink_image(path, 1280, 3_000_000)
    try:
        data = base64.b64encode(small.read_bytes()).decode()
    finally:
        small.unlink(missing_ok=True)
    raw = _call_with_fallback(VISION_PROMPT, config.GEMINI_FAST_MODEL, use_search=False,
                              parts=[{"kind": "image", "mime_type": "image/jpeg", "data": data}])
    d = extract_json(raw["text"]) or {}
    return {"description": str(d.get("description", ""))[:400], "text_in_image": str(d.get("text_in_image", ""))[:3000],
            "claims": [str(x)[:300] for x in d.get("claims", [])][:10],
            "red_flags": [str(x)[:300] for x in d.get("red_flags", [])][:10]}


class GeminiProvider(Provider):
    id = "gemini"
    name = "Google Gemini"
    roles = {"research", "translation", "speech", "vision"}
    specialist_roles = {"research"}

    def enabled(self) -> bool:
        return enabled()

    def model_for(self, role: str) -> str:
        return config.GEMINI_MODEL if role in ("research", "review") else config.GEMINI_FAST_MODEL

    def research(self, claim, scheme, reply_lang):
        return research_claim(claim, scheme, reply_lang)

    def translate(self, texts, target_lang):
        return translate_texts(texts, target_lang)

    def transcribe(self, audio_path):
        return transcribe_mp3(audio_path)

    def describe_image(self, image_path):
        return describe_image(image_path)
