"""Claim verification: match a claim to the trusted scheme registry, check its facts, detect scam patterns."""
import json
import re
from datetime import date, datetime
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

from .. import config

STOPWORDS = set("""a an the of for to and or in on at by with from is are was be this that these those it its as
your you our we they their them i me my he she his her will shall can may must not no all any each per get
gets got apply application scheme yojana government govt official new now only also than then into about""".split())

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


@lru_cache
def registry() -> list[dict]:
    return json.loads((config.DATA_DIR / "registry.json").read_text(encoding="utf-8"))["schemes"]


@lru_cache
def scam_patterns() -> list[dict]:
    pats = json.loads((config.DATA_DIR / "scam_patterns.json").read_text(encoding="utf-8"))["patterns"]
    for p in pats:
        p["_re"] = re.compile(p["regex"], re.IGNORECASE)
    return pats


@lru_cache
def trusted_domains() -> dict:
    return json.loads((config.DATA_DIR / "trusted_domains.json").read_text(encoding="utf-8"))


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 2}


# ---------------- fact extraction ----------------
_AMOUNT_RE = re.compile(
    r"(?:(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|k)?)|(?:([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)?\s*(?:rupees|rs\b|inr))",
    re.IGNORECASE)
_FEE_WORDS = r"fee|charge|pay|deposit|transfer|send|processing|registration|शुल्क|फीस|पंजीकरण|भुगतान|கட்டணம்|రుసుము|ಶುಲ್ಕ|ഫീസ്"
_FEE_CONTEXT = re.compile(_FEE_WORDS, re.IGNORECASE)
_INCOME_CONTEXT = re.compile(r"income|earning|salary", re.IGNORECASE)
_FREE_RE = re.compile(r"\b(free of cost|no (application )?fee|free to apply|apply (for )?free|without any fee|zero fee|fee[- ]free)\b",
                      re.IGNORECASE)


def _to_number(num: str, unit: Optional[str]) -> float:
    value = float(num.replace(",", ""))
    unit = (unit or "").lower()
    if unit in ("lakh", "lac"):
        value *= 100_000
    elif unit == "crore":
        value *= 10_000_000
    elif unit == "k":
        value *= 1_000
    return value


def extract_amounts(text: str) -> list[dict]:
    out = []
    for m in _AMOUNT_RE.finditer(text):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if not num or not re.search(r"\d", num):
            continue
        before = text[max(0, m.start() - 45):m.start()]
        after = text[m.end():m.end() + 25]
        kind = "benefit"
        if _INCOME_CONTEXT.search(before):
            kind = "income_limit"
        elif _FEE_CONTEXT.search(before) or re.match(r"\s*(fee|charge|पंजीकरण|शुल्क|फीस|கட்டணம்|రుసుము|ಶುಲ್ಕ)", after, re.IGNORECASE):
            kind = "fee"
        out.append({"value": _to_number(num, unit), "kind": kind, "text": m.group(0).strip()})
    return out


def extract_dates(text: str) -> list[date]:
    found = []
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text):
        if mon[:3].lower() in MONTHS:
            found.append((int(y), MONTHS[mon[:3].lower()], int(d)))
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text):
        if mon[:3].lower() in MONTHS:
            found.append((int(y), MONTHS[mon[:3].lower()], int(d)))
    for y, mo, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        found.append((int(y), int(mo), int(d)))
    for d, mo, y in re.findall(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", text):
        found.append((int(y), int(mo), int(d)))
    dates = []
    for y, mo, d in found:
        try:
            dates.append(date(y, mo, d))
        except ValueError:
            continue
    return dates


def extract_urls(text: str) -> list[str]:
    return re.findall(r"(?:https?://|www\.)[^\s<>\"')]+|\b(?:bit\.ly|tinyurl\.com|wa\.me|t\.me)/[^\s<>\"')]+", text)


# ---------------- domain trust ----------------
def domain_trust(url: str) -> dict:
    if not re.match(r"https?://", url):
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    td = trusted_domains()
    if host in td["trusted_exact"] or any(host == s or host.endswith("." + s) for s in td["trusted_suffixes"]):
        return {"host": host, "trust": "official", "score": 1.0}
    if host in td["low_trust_hosts"]:
        return {"host": host, "trust": "low", "score": 0.1}
    return {"host": host, "trust": "unknown", "score": 0.5}


# ---------------- registry matching ----------------
def match_scheme(text: str) -> tuple[Optional[dict], float]:
    t = tokens(text)
    low = text.lower()
    best, best_score = None, 0.0
    for s in registry():
        name_tokens = tokens(s["name"])
        score = len(t & name_tokens) / max(1, len(name_tokens))           # coverage of the scheme name
        if any(a in low for a in [s["name"].lower(), *s.get("aliases", [])]):
            score = max(score, 0.9)
        ctx = tokens(s["summary"] + " " + " ".join(s.get("eligibility", [])))
        score = 0.8 * score + 0.2 * (len(t & ctx) / max(1, len(t)))
        if score > best_score:
            best, best_score = s, score
    return (best, round(best_score, 3)) if best_score >= 0.35 else (None, round(best_score, 3))


def _close(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol * max(a, b, 1)


def check_facts(text: str, scheme: dict) -> tuple[list[dict], list[dict]]:
    confirmations, contradictions = [], []
    amounts = extract_amounts(text)

    benefits = [a for a in amounts if a["kind"] == "benefit"]
    if benefits:
        if any(_close(a["value"], scheme["benefit_amount"]) for a in benefits):
            confirmations.append({"field": "benefit_amount", "detail":
                                  f"Benefit amount matches the registry (Rs {scheme['benefit_amount']:,} {scheme['benefit_period']})."})
        else:
            claimed = ", ".join(dict.fromkeys(a["text"] for a in benefits))
            contradictions.append({"field": "benefit_amount", "severity": "high", "detail":
                                   f"Claim states {claimed}; the registry lists Rs {scheme['benefit_amount']:,} {scheme['benefit_period']}."})

    fees = [a for a in amounts if a["kind"] == "fee" and a["value"] > 0]
    if fees and scheme["application_fee"] == 0:
        contradictions.append({"field": "application_fee", "severity": "high", "detail":
                               f"Claim asks for {fees[0]['text']}; the official application is free."})
    elif _FREE_RE.search(text) and scheme["application_fee"] == 0:
        confirmations.append({"field": "application_fee", "detail": "Claim correctly says the application is free."})

    incomes = [a for a in amounts if a["kind"] == "income_limit"]
    for a in incomes:
        if _close(a["value"], scheme["income_limit"]):
            confirmations.append({"field": "income_limit", "detail": f"Income limit matches (Rs {scheme['income_limit']:,})."})
        else:
            contradictions.append({"field": "income_limit", "severity": "medium", "detail":
                                   f"Claim states an income limit of {a['text']}; the registry lists Rs {scheme['income_limit']:,}."})

    deadline = datetime.strptime(scheme["deadline"], "%Y-%m-%d").date()
    dates = extract_dates(text)
    if dates:
        if deadline in dates:
            confirmations.append({"field": "deadline", "detail": f"Deadline matches ({deadline:%d %b %Y})."})
        else:
            contradictions.append({"field": "deadline", "severity": "medium", "detail":
                                   f"Claim gives {', '.join(f'{d:%d %b %Y}' for d in dates)}; the official deadline is {deadline:%d %b %Y}."})
    return confirmations, contradictions


def detect_scam_patterns(text: str) -> list[dict]:
    hits = []
    for p in scam_patterns():
        m = p["_re"].search(text)
        if m:
            hits.append({"id": p["id"], "label": p["label"], "weight": p["weight"], "evidence": m.group(0)})
    return hits


def analyze_claim(text: str, source_url: Optional[str] = None) -> dict:
    text = (text or "").strip()
    if not text:
        return {"present": False, "score": None}

    scheme, match_score = match_scheme(text)
    confirmations, contradictions = check_facts(text, scheme) if scheme else ([], [])
    scam_hits = detect_scam_patterns(text)
    sources = [domain_trust(u) for u in ([source_url] if source_url else []) + extract_urls(text)]

    score = 0.5
    if scheme:
        score += 0.25 * min(1.0, match_score / 0.6)
    score += min(0.24, 0.08 * len(confirmations))
    score -= sum(0.3 if c["severity"] == "high" else 0.15 for c in contradictions)
    score -= min(0.8, sum(h["weight"] for h in scam_hits))
    if sources:
        worst = min(s["score"] for s in sources)
        if worst >= 1.0:
            score += 0.1
        elif worst <= 0.1:
            score -= 0.2
        if scheme and any(s["trust"] != "official" for s in sources if s["host"] not in scheme["official_domains"]):
            score -= 0.05
    score = max(0.0, min(0.98, score))

    return {
        "present": True,
        "score": round(score, 3),
        "matched_scheme": scheme,
        "match_score": match_score,
        "confirmations": confirmations,
        "contradictions": contradictions,
        "scam_flags": scam_hits,
        "sources": sources,
        "extracted": {"amounts": extract_amounts(text), "dates": [d.isoformat() for d in extract_dates(text)]},
    }
