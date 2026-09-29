"""Minimal HTTP client (stdlib only) with per-host rate limiting, retries and an optional disk cache."""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from . import __url__, __version__
from .util import info, replace_file

USER_AGENT = f"lr-ai/{__version__} (+{__url__})"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 120  # seconds; longer waits (e.g. a daily quota reset) fail immediately instead

_last_call: dict[str, float] = {}
_cache_dir: str | None = None


class HttpError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status


class NotFound(HttpError):
    pass


def set_cache_dir(path: str | None) -> None:
    """Cache successful GET responses on disk so interrupted runs can resume for free."""
    global _cache_dir
    _cache_dir = path
    if path:
        os.makedirs(path, exist_ok=True)


def build_url(url: str, params: dict | None = None) -> str:
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)


def _cache_path(key: str) -> str | None:
    if not _cache_dir:
        return None
    return os.path.join(_cache_dir, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".txt")


def request(
    url: str,
    params: dict | None = None,
    *,
    headers: dict | None = None,
    body: dict | None = None,
    min_interval: float = 0.0,
    retries: int = 6,
    timeout: float = 60.0,
    cache: bool = True,
    refresh: bool = False,
    cache_check: Callable[[str], bool] | None = None,
) -> str:
    """Perform a GET (or POST when `body` is given) and return the response text.

    With a cache dir set, successful responses are stored unless `cache_check(text)` rejects them (e.g. an
    empty or truncated page); `refresh=True` skips the cached copy but still stores a good response.
    """
    full = build_url(url, params)
    method = "POST" if body is not None else "GET"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    cache_key = full + ("\n" + data.decode("utf-8") if data else "")
    cpath = _cache_path(cache_key) if cache else None
    if cpath and not refresh and os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as f:
            return f.read()

    host = urllib.parse.urlsplit(full).netloc
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml;q=0.9, */*;q=0.5"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})

    for attempt in range(retries + 1):
        wait = _last_call.get(host, 0.0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        req = urllib.request.Request(full, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            if cpath and (cache_check is None or cache_check(text)):
                tmp = cpath + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                replace_file(tmp, cpath)
            return text
        except urllib.error.HTTPError as e:
            detail = _error_message(e.read()[:1000].decode("utf-8", errors="replace"))
            if e.code in RETRY_STATUS and attempt < retries:
                retry_after = e.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else min(60.0, 2.0 ** attempt + random.random())
                if delay > MAX_RETRY_AFTER or "api key" in detail.lower():
                    raise HttpError(e.code, f"{host} refused the request (HTTP {e.code}): {detail}") from None
                info(f"  HTTP {e.code} from {host}; retrying in {delay:.0f}s")
                time.sleep(delay)
                continue
            if e.code == 404:
                raise NotFound(404, f"not found: {full}") from None
            raise HttpError(e.code, f"HTTP {e.code} for {full}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries:
                delay = min(60.0, 2.0 ** attempt + random.random())
                info(f"  network error from {host} ({e}); retrying in {delay:.0f}s")
                time.sleep(delay)
                continue
            raise HttpError(None, f"network error for {full}: {e}") from None
    raise HttpError(None, f"giving up on {full}")


def _error_message(body: str) -> str:
    """Pull the human-readable part out of a JSON error body."""
    try:
        d = json.loads(body)
    except ValueError:
        return " ".join(body.split())[:300]
    if isinstance(d, dict):
        parts = [str(d[k]) for k in ("error", "message") if d.get(k)]
        if parts:
            return " — ".join(parts)[:300]
    return " ".join(body.split())[:300]


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def get_json(url: str, params: dict | None = None, **kwargs) -> dict:
    text = request(url, params, cache_check=_is_json, **kwargs)
    try:
        return json.loads(text)
    except ValueError:
        raise HttpError(None, f"non-JSON response from {build_url(url, params)}: {text[:200]!r}") from None
