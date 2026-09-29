"""Semantic Scholar Graph API client (https://api.semanticscholar.org/api-docs/graph).

Works without a key (shared, heavily rate-limited pool); set S2_API_KEY for a dedicated 1 req/s limit.
"""
from __future__ import annotations

import os
import urllib.parse

from .. import query as q
from ..http import NotFound, get_json
from ..models import Paper

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "paperId,externalIds,title,abstract,year,venue,publicationVenue,journal,authors,"
    "citationCount,url,openAccessPdf,publicationTypes"
)


def _opts() -> dict:
    key = os.environ.get("S2_API_KEY")
    # Without a key the shared anonymous pool is often saturated: give up sooner so callers can fall back.
    return {"headers": {"x-api-key": key} if key else {}, "min_interval": 1.05 if key else 1.5,
            "retries": 6 if key else 4}


def _years(year_min: int | None, year_max: int | None) -> str | None:
    if not year_min and not year_max:
        return None
    return f"{year_min or ''}-{year_max or ''}"


def to_paper(d: dict | None) -> Paper | None:
    if not d or not d.get("title"):
        return None
    ext = d.get("externalIds") or {}
    venue = (d.get("publicationVenue") or {}).get("name") or d.get("venue") or (d.get("journal") or {}).get("name")
    return Paper(
        title=d["title"],
        authors=[a.get("name") for a in d.get("authors") or [] if a.get("name")],
        year=d.get("year"),
        venue=venue or None,
        doi=ext.get("DOI"),
        arxiv_id=ext.get("ArXiv"),
        s2_id=d.get("paperId"),
        url=d.get("url"),
        pdf_url=(d.get("openAccessPdf") or {}).get("url") or None,
        abstract=d.get("abstract"),
        citation_count=d.get("citationCount"),
        type=", ".join(d.get("publicationTypes") or []) or None,
    ).normalize()


def search(query: str, limit: int = 20, year_min: int | None = None,
           year_max: int | None = None) -> tuple[list[Paper], int | None]:
    """Relevance-ranked search -> (papers, total matches). Boolean syntax is flattened to plain words
    (the endpoint supports none) and hyphens are dropped (they break matching)."""
    text = q.to_plain(query).replace("-", " ")
    out: list[Paper] = []
    total = None
    offset = 0
    while len(out) < limit and offset < 1000:
        page = min(100, limit - len(out), 1000 - offset)
        data = get_json(f"{BASE}/paper/search", {
            "query": text, "fields": FIELDS, "limit": page, "offset": offset, "year": _years(year_min, year_max),
        }, **_opts())
        total = data.get("total", total)
        items = data.get("data") or []
        out.extend(p for p in map(to_paper, items) if p)
        if not items or "next" not in data:
            break
        offset = data["next"]
    return out[:limit], total


def search_bulk(query: str, limit: int = 100, year_min: int | None = None,
                year_max: int | None = None) -> tuple[list[Paper], int | None]:
    """Boolean keyword search (bulk endpoint), most-cited first -> (papers, total matches).
    Note: the bulk endpoint cannot rank by relevance, so a capped result favors highly cited papers."""
    out: list[Paper] = []
    total = None
    token = None
    while len(out) < limit:
        data = get_json(f"{BASE}/paper/search/bulk", {
            "query": q.to_semantic_scholar(query), "fields": FIELDS, "sort": "citationCount:desc",
            "year": _years(year_min, year_max), "token": token,
        }, **_opts())
        total = data.get("total", total)
        items = data.get("data") or []
        out.extend(p for p in map(to_paper, items) if p)
        token = data.get("token")
        if not items or not token:
            break
    return out[:limit], total


def paper_key(p: Paper) -> str | None:
    if p.s2_id:
        return p.s2_id
    if p.doi:
        return "DOI:" + p.doi
    if p.arxiv_id:
        return "ARXIV:" + p.arxiv_id
    return None


def _edges(key: str, kind: str, cap: int) -> list[Paper]:
    node = "citedPaper" if kind == "references" else "citingPaper"
    out: list[Paper] = []
    offset = 0
    while offset < cap:
        data = get_json(f"{BASE}/paper/{urllib.parse.quote(key, safe=':')}/{kind}", {
            "fields": FIELDS, "limit": min(1000, cap - offset), "offset": offset,
        }, **_opts())
        items = data.get("data") or []
        out.extend(p for p in (to_paper(it.get(node)) for it in items) if p)
        if not items or "next" not in data:
            break
        offset = data["next"]
    return out


def references(p: Paper, cap: int = 1000) -> list[Paper] | None:
    """Papers cited by `p`, or None if Semantic Scholar doesn't know the paper."""
    key = paper_key(p)
    if not key:
        return None
    try:
        return _edges(key, "references", cap)
    except NotFound:
        return None


def citations(p: Paper, cap: int = 1000) -> list[Paper] | None:
    """Papers citing `p` (unordered; callers sort), or None if unknown."""
    key = paper_key(p)
    if not key:
        return None
    try:
        return _edges(key, "citations", cap)
    except NotFound:
        return None


def lookup(ids: list[str]) -> list[Paper | None]:
    """Resolve DOIs / arXiv ids / S2 ids (e.g. 'DOI:10.1/x', 'ARXIV:2401.01234') via the batch endpoint.
    The result is aligned with `ids`; unknown ids give None."""
    out: list[Paper | None] = []
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        data = get_json(f"{BASE}/paper/batch", {"fields": FIELDS}, body={"ids": chunk}, **_opts())
        rows = data if isinstance(data, list) else []
        rows += [None] * (len(chunk) - len(rows))
        out.extend(to_paper(d) for d in rows[: len(chunk)])
    return out


def match_title(title: str) -> Paper | None:
    try:
        data = get_json(f"{BASE}/paper/search/match", {"query": title, "fields": FIELDS}, **_opts())
    except NotFound:
        return None
    items = data.get("data") or []
    return to_paper(items[0]) if items else None
