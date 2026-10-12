"""Fill gaps in paper metadata (abstracts, citation counts, ids).

arXiv records have no citation counts and OpenAlex lacks many abstracts; screening needs both.
Semantic Scholar's batch endpoint is tried first (500 papers per call), then OpenAlex's DOI lookup.
A source is remembered as checked for a paper only after it actually answered, so papers skipped
because of rate limits are retried on the next step.
"""
from __future__ import annotations

from .http import HttpError
from .models import Paper
from .sources import openalex
from .sources import semantic_scholar as s2
from .util import info

_FILL = ("abstract", "citation_count", "doi", "arxiv_id", "s2_id", "openalex_id", "venue", "year", "published",
         "pdf_url", "language")


def _fill(p: Paper, q: Paper | None) -> bool:
    if q is None:
        return False
    changed = False
    for name in _FILL:
        if getattr(p, name) in (None, "") and getattr(q, name) not in (None, ""):
            setattr(p, name, getattr(q, name))
            changed = True
    if changed:
        p.normalize()
    return changed


def _missing(p: Paper) -> bool:
    return not p.abstract or p.citation_count is None


def _checked(p: Paper, source: str) -> bool:
    return source in (p.extra.get("meta_checked") or [])


def _mark(p: Paper, source: str) -> None:
    p.extra["meta_checked"] = sorted(set(p.extra.get("meta_checked") or []) | {source})


def complete_dates(papers: list[Paper], years: set[int] | None = None) -> int:
    """Fill the publication date (OpenAlex) of papers that have none, optionally only those published in `years`
    (the cut-off years of a date filter: only there does the exact date decide). Returns how many gained a date."""
    targets = [p for p in papers if not p.published and (years is None or p.year in years)]
    if not targets:
        return 0
    info(f"  looking up publication dates for {len(targets)} papers")
    filled = 0
    try:
        by_id = {p.openalex_id: p for p in targets if p.openalex_id}
        for q in openalex.get_works(list(by_id)):
            p = by_id.get(q.openalex_id or "")
            if p is not None and q.published:
                p.published, filled = q.published, filled + 1
        by_doi = {openalex.doi_of(p): p for p in targets if not p.published and openalex.doi_of(p)}
        for q in openalex.lookup_dois(list(by_doi)) if by_doi else []:
            p = by_doi.get(openalex.doi_of(q) or "")
            if p is not None and q.published and not p.published:
                p.published, filled = q.published, filled + 1
    except HttpError as e:
        info(f"  OpenAlex date lookup stopped: {e}")
    return filled


def complete_metadata(papers: list[Paper], force: bool = False) -> int:
    """Look up papers missing an abstract or citation count. Returns how many records gained data.
    `force` retries sources that already answered for a paper."""
    s2_targets = [p for p in papers if _missing(p) and s2.paper_key(p) and (force or not _checked(p, "s2"))]
    oa_candidates = [p for p in papers if _missing(p) and openalex.doi_of(p) and (force or not _checked(p, "openalex"))]
    if not s2_targets and not oa_candidates:
        return 0
    info(f"  completing metadata for {len({id(p) for p in s2_targets + oa_candidates})} papers")
    improved = 0
    for i in range(0, len(s2_targets), 500):
        chunk = s2_targets[i : i + 500]
        try:
            found = s2.lookup([s2.paper_key(p) for p in chunk])
        except HttpError as e:
            info(f"  Semantic Scholar lookup failed ({e}); trying OpenAlex")
            continue
        for p, q in zip(chunk, found):
            _mark(p, "s2")
            improved += _fill(p, q)
    by_doi = {openalex.doi_of(p): p for p in oa_candidates if _missing(p)}
    if by_doi:
        try:
            for q in openalex.lookup_dois(list(by_doi)):
                p = by_doi.get(openalex.doi_of(q) or "")
                if p is not None:
                    improved += _fill(p, q)
            for p in by_doi.values():
                _mark(p, "openalex")
        except HttpError as e:
            info(f"  OpenAlex lookup failed: {e}")
    return improved
