"""Fetch a claim URL's text."""
import html
import ipaddress
import json
import logging
import re
import socket
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from .. import config

log = logging.getLogger("factverify.sources")


def _is_private(host: str) -> bool:
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
    except socket.gaierror:
        return False
    return False


def fetch_url_text(url: str, allow_local: bool = True, max_bytes: int = 1_000_000) -> dict:
    """Download a page and return its title and visible text. Never raises; errors are reported."""
    if not config.ALLOW_URL_FETCH:
        return {"ok": False, "error": "URL fetching disabled (ALLOW_URL_FETCH=false)"}
    parsed = urlparse(url if re.match(r"https?://", url) else "https://" + url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "error": "Only http(s) URLs are supported"}
    if not allow_local and _is_private(parsed.hostname):
        return {"ok": False, "error": "Refusing to fetch a private network address"}
    try:
        req = urllib.request.Request(parsed.geturl(), headers={"User-Agent": "FactVerify/1.0 (claim verification)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(max_bytes).decode(resp.headers.get_content_charset() or "utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Could not fetch URL: {e.__class__.__name__}: {e}"}
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    meta_desc = re.findall(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description|og:title)["\'][^>]+content=["\']([^"\']+)',
                           raw, re.IGNORECASE)
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", " ".join(meta_desc) + " " + body).strip()
    return {"ok": True, "title": html.unescape(title.group(1).strip()) if title else "", "text": text[:8000],
            "final_url": parsed.geturl()}
