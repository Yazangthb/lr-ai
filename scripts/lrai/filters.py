"""Deterministic inclusion filters (year, language, type, citations, keywords, ...).

Filters are recomputed from config on every run, so changing config.yaml and re-running is always safe.
Papers the user supplied explicitly (seed.papers / manual additions) are never filtered out.
"""
from __future__ import annotations

import re

from .models import Paper
from .util import this_year

PROTECTED = ("seed:known", "manual")


def _term_regex(term: str) -> re.Pattern:
    """'citation graph' also matches 'citation graphs'; 'predict*' matches 'prediction', 'predicting', ..."""
    term = str(term).strip().strip('"').lower()
    prefix = term.endswith("*")
    words = [re.escape(w) for w in term.rstrip("*").split()]
    body = r"[\s-]+".join(words)
    # lookarounds instead of \b, so terms that start or end with symbols ("c++", "C#", ".NET") still match
    return re.compile(r"(?<!\w)" + body + (r"\w*" if prefix else r"(?:s|es)?(?!\w)"), re.I)


def compile_terms(terms) -> list[tuple[str, re.Pattern]]:
    return [(t, _term_regex(t)) for t in terms or [] if str(t).strip().strip('"*')]


def exclusion_reason(p: Paper, f: dict, require_any=None, exclude_any=None, year_now: int | None = None) -> str | None:
    """Return why `p` fails the filters, or None if it passes."""
    if any(v in PROTECTED for v in p.found_via):
        return None
    year_now = year_now or this_year()
    if f.get("year_min") and p.year and p.year < int(f["year_min"]):
        return f"published before {f['year_min']}"
    if f.get("year_max") and p.year and p.year > int(f["year_max"]):
        return f"published after {f['year_max']}"
    langs = [str(x).lower() for x in f.get("languages") or []]
    if langs and p.language and p.language.lower() not in langs:
        return f"language: {p.language}"
    types = [str(t).lower() for t in f.get("exclude_types") or []]
    if types and p.type and any(t in p.type.lower() for t in types):
        return f"publication type: {p.type}"
    if f.get("require_abstract") and not p.abstract:
        return "no abstract"
    min_c = int(f.get("min_citations") or 0)
    grace = int(f.get("citation_grace_years") or 0)
    if min_c and p.citation_count is not None and p.citation_count < min_c:
        if not (p.year and year_now - p.year < grace):
            return f"fewer than {min_c} citations"
    venue = (p.venue or "").lower()
    for v in f.get("venue_exclude") or []:
        if venue and str(v).lower() in venue:
            return f"venue: {p.venue}"
    text = f"{p.title} {p.abstract or ''}"
    for term, rx in exclude_any if exclude_any is not None else compile_terms(f.get("exclude_any")):
        if rx.search(text):
            return f"mentions '{term}'"
    req = require_any if require_any is not None else compile_terms(f.get("require_any"))
    if req and not any(rx.search(text) for _, rx in req):
        return "none of the required keywords"
    min_hits = int(f.get("min_hits") or 0)
    if min_hits and p.round > 0 and p.hits < min_hits:
        return f"linked from fewer than {min_hits} papers"
    return None


def apply(papers: list[Paper], f: dict) -> dict[str, int]:
    """Set `excluded_reason` on every paper. Returns counts per reason."""
    req, exc = compile_terms(f.get("require_any")), compile_terms(f.get("exclude_any"))
    year_now = this_year()
    counts: dict[str, int] = {}
    for p in papers:
        p.excluded_reason = exclusion_reason(p, f, req, exc, year_now)
        if p.excluded_reason:
            key = re.sub(r":.*$", "", p.excluded_reason) if p.excluded_reason.startswith(("language", "publication type", "venue")) else p.excluded_reason
            counts[key] = counts.get(key, 0) + 1
    return counts
