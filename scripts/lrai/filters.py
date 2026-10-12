"""Deterministic inclusion filters (year, language, type, citations, keywords, ...).

Filters are recomputed from config on every run, so changing config.yaml and re-running is always safe.
Papers the user supplied explicitly (seed.papers / manual additions) are never filtered out.
"""
from __future__ import annotations

import re

from .models import Paper, norm_arxiv, norm_doi, norm_title
from .util import this_year

PROTECTED = ("seed:known", "manual")


def _term_regex(term: str) -> re.Pattern:
    """'citation graph' also matches 'citation graphs'; 'predict*' matches 'prediction', 'predicting', ...;
    a leading * matches inside a word: '*twin*' matches 'Cybertwin', 'cyber-physical twins', 'TwinNet'."""
    term = str(term).strip().strip('"').lower()
    prefix, suffix = term.endswith("*"), term.startswith("*")
    words = [re.escape(w) for w in term.strip("*").split()]
    body = r"[\s-]+".join(words)
    # lookarounds instead of \b, so terms that start or end with symbols ("c++", "C#", ".NET") still match
    start = r"\w*" if suffix else r"(?<!\w)"
    return re.compile(start + body + (r"\w*" if prefix else r"(?:s|es)?(?!\w)"), re.I)


def compile_terms(terms) -> list[tuple[str, re.Pattern]]:
    return [(t, _term_regex(t)) for t in terms or [] if str(t).strip().strip('"*')]


def block_keys(items) -> set[str]:
    """Dedup keys for the `block` list: DOIs, arXiv ids, OpenAlex ids (W...) or exact titles."""
    keys = set()
    for item in items or []:
        s = str(item).strip()
        if not s:
            continue
        doi, arxiv = norm_doi(s), norm_arxiv(s)
        if doi:
            keys.add("doi:" + doi)
        elif arxiv:
            keys.add("arxiv:" + arxiv.lower())
        elif re.fullmatch(r"(?:https?://openalex\.org/)?[Ww]\d+", s):
            keys.add("openalex:" + s.rsplit("/", 1)[-1].upper())
        elif norm_title(s):
            keys.add("title:" + norm_title(s))
    return keys


def _date_reason(p: Paper, f: dict) -> str | None:
    """date_min / date_max (YYYY-MM-DD, e.g. a review's search date). Compared on the precision both sides have
    ("2024-01" passes date_max 2024-01-31). Without a date only the year can decide, so papers from the cut-off
    year itself stay in (`lr.py complete --dates` looks their dates up)."""
    dmin, dmax = (str(f[k]) if f.get(k) else None for k in ("date_min", "date_max"))
    if dmax:
        if p.published:
            n = min(len(p.published), len(dmax))
            if p.published[:n] > dmax[:n]:
                return f"published after {dmax}"
        elif p.year and p.year > int(dmax[:4]):
            return f"published after {dmax}"
    if dmin:
        if p.published:
            n = min(len(p.published), len(dmin))
            if p.published[:n] < dmin[:n]:
                return f"published before {dmin}"
        elif p.year and p.year < int(dmin[:4]):
            return f"published before {dmin}"
    return None


def undated_in_cutoff_years(papers: list[Paper], f: dict) -> list[Paper]:
    """Papers a date filter cannot decide yet: no publication date, published in a cut-off year."""
    years = {int(str(f[k])[:4]) for k in ("date_min", "date_max") if f.get(k)}
    return [p for p in papers if years and not p.published and p.year in years]


def exclusion_reason(p: Paper, f: dict, require_any=None, exclude_any=None, year_now: int | None = None,
                     blocked: set | None = None, hits: int | None = None) -> str | None:
    """Return why `p` fails the filters, or None if it passes. `hits`: for a snowballed paper, the number of papers
    linking to it that themselves pass the filters (default: all of them)."""
    blocked = block_keys(f.get("block")) if blocked is None else blocked
    if blocked and blocked.intersection(p.dedup_keys()):
        return "blocked"  # before the protection below: a blocked paper never enters, even as a seed
    if any(v in PROTECTED for v in p.found_via):
        return None
    year_now = year_now or this_year()
    if f.get("year_min") and p.year and p.year < int(f["year_min"]):
        return f"published before {f['year_min']}"
    if f.get("year_max") and p.year and p.year > int(f["year_max"]):
        return f"published after {f['year_max']}"
    why = _date_reason(p, f)
    if why:
        return why
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
    if p.round > 0 and hits == 0 and p.hits > 0:
        return "linked only from papers removed by the filters"
    min_hits = int(f.get("min_hits") or 0)
    if min_hits and p.round > 0 and (p.hits if hits is None else hits) < min_hits:
        return f"linked from fewer than {min_hits} papers"
    snow_req = compile_terms(f.get("snowball_require_any")) if p.round > 0 else []
    if snow_req and not any(rx.search(text) for _, rx in snow_req):
        return "snowballed, none of the required keywords"
    return None


def apply(papers: list[Paper], f: dict) -> dict[str, int]:
    """Set `excluded_reason` on every paper. Returns counts per reason."""
    req, exc = compile_terms(f.get("require_any")), compile_terms(f.get("exclude_any"))
    year_now = this_year()
    blocked = block_keys(f.get("block"))
    counts: dict[str, int] = {}
    removed: set[str] = set()  # ids of papers the filters remove; their snowballing links no longer count
    for p in sorted(papers, key=lambda q: q.round):  # earlier rounds first: they are the later rounds' sources
        hits = None
        if p.round > 0:
            sources = {v.split(":", 1)[1] for v in p.found_via if v.startswith(("backward:", "forward:"))}
            hits = len(sources - removed)
        p.excluded_reason = exclusion_reason(p, f, req, exc, year_now, blocked, hits)
        if p.excluded_reason:
            # every id form, since a link may name the paper by an id it had before a merge (arxiv: -> doi:)
            removed.update(k for k in (p.id, p.doi and "doi:" + p.doi, p.arxiv_id and "arxiv:" + p.arxiv_id.lower(),
                                       p.openalex_id and "openalex:" + p.openalex_id, p.s2_id and "s2:" + p.s2_id) if k)
            key =re.sub(r":.*$", "", p.excluded_reason) if p.excluded_reason.startswith(("language", "publication type", "venue")) else p.excluded_reason
            counts[key] = counts.get(key, 0) + 1
    return counts
