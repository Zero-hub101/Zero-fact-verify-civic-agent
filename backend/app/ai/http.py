"""Small HTTP helpers shared by providers (JSON + multipart), with clear errors."""
import json
from typing import Any, Optional

import requests

from .base import ProviderError

TIMEOUT = 90


def _raise(name: str, r: requests.Response) -> None:
    if r.status_code >= 400:
        raise ProviderError(f"{name} HTTP {r.status_code}: {r.text[:300]}", r.status_code)


def post_json(name: str, url: str, headers: dict, body: dict, timeout: int = TIMEOUT) -> Any:
    try:
        r = requests.post(url, headers={**headers, "Content-Type": "application/json"}, data=json.dumps(body),
                          timeout=timeout)
    except requests.RequestException as e:
        raise ProviderError(f"{name} network error: {e}")
    _raise(name, r)
    return r.json()


def post_bytes(name: str, url: str, headers: dict, body: dict, timeout: int = TIMEOUT) -> bytes:
    try:
        r = requests.post(url, headers={**headers, "Content-Type": "application/json"}, data=json.dumps(body),
                          timeout=timeout)
    except requests.RequestException as e:
        raise ProviderError(f"{name} network error: {e}")
    _raise(name, r)
    return r.content


def post_multipart(name: str, url: str, headers: dict, data: dict, file_field: str, file_path,
                   mime: str = "application/octet-stream", timeout: int = TIMEOUT,
                   params: Optional[dict] = None) -> Any:
    try:
        with open(file_path, "rb") as fh:
            r = requests.post(url, headers=headers, data=data, params=params,
                              files={file_field: (str(file_path).rsplit("/", 1)[-1], fh, mime)}, timeout=timeout)
    except requests.RequestException as e:
        raise ProviderError(f"{name} network error: {e}")
    _raise(name, r)
    return r.json()
