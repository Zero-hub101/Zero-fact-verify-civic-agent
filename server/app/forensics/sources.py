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


def _friendly_fetch_error(e: Exception, host: str) -> str:
    msg = str(e).lower()
    if isinstance(e, socket.gaierror) or "getaddrinfo" in msg or "name or service not known" in msg \
            or "nodename nor servname" in msg or "no address associated" in msg:
        return (f"The link's website ({host}) does not exist. Fake sites often disappear quickly; "
                "do not trust links you cannot verify.")
    if "timed out" in msg or "timeout" in msg:
        return f"The link ({host}) did not respond, so its content could not be checked."
    code = getattr(e, "code", None)
    if code:
        return f"The link ({host}) returned an error (HTTP {code}), so its content could not be checked."
    if "certificate" in msg or "ssl" in msg:
        return f"The link ({host}) has an invalid security certificate, a common sign of an unsafe site."
    return f"The link ({host}) could not be opened, so its content could not be checked."


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
        log.info("URL fetch failed for %s: %r", parsed.hostname, e)
        return {"ok": False, "error": _friendly_fetch_error(e, parsed.hostname), "unreachable": True}
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    meta_desc = re.findall(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description|og:title)["\'][^>]+content=["\']([^"\']+)',
                           raw, re.IGNORECASE)
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", " ".join(meta_desc) + " " + body).strip()
    return {"ok": True, "title": html.unescape(title.group(1).strip()) if title else "", "text": text[:8000],
            "final_url": parsed.geturl()}
