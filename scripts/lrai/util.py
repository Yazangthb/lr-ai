"""Small shared helpers: progress logging, slugs, dates."""
from __future__ import annotations

import datetime
import os
import re
import sys
import time
import unicodedata


def info(msg: str) -> None:
    """Progress/diagnostic output goes to stderr so stdout stays clean for results."""
    print(msg, file=sys.stderr, flush=True)


def slugify(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen].rstrip("-") or "review"


def today() -> str:
    return datetime.date.today().isoformat()


def this_year() -> int:
    return datetime.date.today().year


def replace_file(tmp: str, path: str, attempts: int = 5) -> None:
    """os.replace with retries: sync clients (OneDrive, Dropbox) and antivirus briefly lock files on Windows."""
    for i in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.2 * (i + 1))


def shorten(text: str | None, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
