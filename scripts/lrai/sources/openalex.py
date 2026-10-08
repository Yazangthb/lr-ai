"""OpenAlex API client (https://docs.openalex.org). Free; set OPENALEX_EMAIL for the faster polite pool.
LR-AI ships a shared API key; set OPENALEX_API_KEY to use your own instead."""
from __future__ import annotations

import os
import urllib.parse

from .. import query as q
from ..http import HttpError, NotFound, get_json
from ..models import Paper, norm_arxiv
from ..util import info

# Shared key built into LR-AI, used when the user has not set OPENALEX_API_KEY.
BUILTIN_API_KEY = "J18xW4EuZ867r29fFlAPRJ"
KEY_STEPS = (
    "To keep working, use your own free OpenAlex API key:\n"
    "  1. Sign up at https://openalex.org/ and copy your API key from your account settings\n"
    "     (help: https://help.openalex.org/api/authentication/).\n"
    "  2. Set it as OPENALEX_API_KEY:\n"
    "     - Windows: setx OPENALEX_API_KEY \"<your key>\"\n"
    "     - macOS/Linux: add  export OPENALEX_API_KEY=<your key>  to your shell profile (~/.zshrc or ~/.bashrc)\n"
    "     - Claude Code cloud session: add  OPENALEX_API_KEY=<your key>  under Environment variables in the\n"
    "       cloud environment's settings\n"
    "  3. Restart Claude Code and run the step again (finished API calls are cached, nothing is lost)."
)
_RATE_LIMIT_WORDS = ("rate limit", "budget", "quota", "credit", "api key", "too many requests")
rate_limited = False  # set once OpenAlex refuses us for the rest of the day; the CLI then tells the user


def api_key() -> str:
    return os.environ.get("OPENALEX_API_KEY") or BUILTIN_API_KEY


def rate_limit_notice() -> str:
    whose = ("your OpenAlex API key (OPENALEX_API_KEY)" if os.environ.get("OPENALEX_API_KEY")
             else "the shared OpenAlex API key built into LR-AI")
    return (f"OPENALEX RATE LIMIT: OpenAlex stopped answering because the daily budget of {whose} is used up "
            "(it resets at midnight UTC). LR-AI continues with the other databases, so results may be "
            "incomplete.\n" + KEY_STEPS)


def _is_rate_limit(e: HttpError) -> bool:
    msg = str(e).lower()
    return e.status == 429 or any(w in msg for w in _RATE_LIMIT_WORDS)

BASE = "https://api.openalex.org"
SELECT = (
    "id,doi,title,display_name,publication_year,primary_location,authorships,cited_by_count,"
    "abstract_inverted_index,language,type,open_access,best_oa_location,locations"
)
MIN_INTERVAL = 0.15


def _params(extra: dict) -> dict:
    p = dict(extra)
    if os.environ.get("OPENALEX_EMAIL"):
        p["mailto"] = os.environ["OPENALEX_EMAIL"]
    p["api_key"] = api_key()
    return p


def _get(path: str, params: dict) -> dict:
    global rate_limited
    try:
        return get_json(BASE + path, _params(params), min_interval=MIN_INTERVAL)
    except NotFound:
        raise
    except HttpError as e:
        if not _is_rate_limit(e):
            raise
        if not rate_limited:
            rate_limited = True
            info(rate_limit_notice())
        raise HttpError(e.status, f"OpenAlex rate limit reached (see OPENALEX RATE LIMIT above): {e}",
                        persistent=True) from None


def rebuild_abstract(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    words = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    return " ".join(w for _, w in words) or None


def _arxiv_from_locations(w: dict) -> str | None:
    for loc in w.get("locations") or []:
        for key in ("landing_page_url", "pdf_url"):
            url = loc.get(key) or ""
            if "arxiv.org/" in url:
                return norm_arxiv(url)
    return None


def to_paper(w: dict | None) -> Paper | None:
    if not w:
        return None
    title = w.get("title") or w.get("display_name")
    if not title:
        return None
    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}
    best_oa = w.get("best_oa_location") or {}
    return Paper(
        title=title,
        authors=[(a.get("author") or {}).get("display_name") for a in w.get("authorships") or []],
        year=w.get("publication_year"),
        venue=source.get("display_name"),
        doi=w.get("doi"),
        arxiv_id=_arxiv_from_locations(w),
        openalex_id=w.get("id"),
        url=primary.get("landing_page_url"),
        pdf_url=best_oa.get("pdf_url") or (w.get("open_access") or {}).get("oa_url"),
        abstract=rebuild_abstract(w.get("abstract_inverted_index")),
        citation_count=w.get("cited_by_count"),
        language=w.get("language"),
        type=w.get("type"),
    ).normalize()


def _year_filters(year_min: int | None, year_max: int | None) -> list[str]:
    out = []
    if year_min:
        out.append(f"from_publication_date:{year_min}-01-01")
    if year_max:
        out.append(f"to_publication_date:{year_max}-12-31")
    return out


def _paged(params: dict, limit: int) -> tuple[list[dict], int | None]:
    """Cursor pagination over /works -> (works, total count)."""
    out: list[dict] = []
    total = None
    cursor = "*"
    while len(out) < limit and cursor:
        data = _get("/works", {**params, "per-page": min(200, max(1, limit - len(out))), "cursor": cursor})
        meta = data.get("meta") or {}
        total = meta.get("count", total)
        results = data.get("results") or []
        out.extend(results)
        cursor = meta.get("next_cursor")
        if not results:
            break
    return out[:limit], total


def search(query: str, limit: int = 100, year_min: int | None = None,
           year_max: int | None = None) -> tuple[list[Paper], int | None]:
    """Boolean keyword search over titles and abstracts, most relevant first -> (papers, total matches)."""
    filters = [f"title_and_abstract.search:{q.to_openalex(query)}"] + _year_filters(year_min, year_max)
    works, total = _paged({"filter": ",".join(filters), "select": SELECT}, limit)
    return [p for p in map(to_paper, works) if p], total


def search_relevance(query: str, limit: int = 20, year_min: int | None = None,
                     year_max: int | None = None) -> tuple[list[Paper], int | None]:
    """Natural-language query (seed-search fallback) -> (papers, total matches).
    All content words must appear in the title/abstract; the plain `search=` parameter is avoided because its
    ranking favors highly cited but off-topic papers."""
    return search(q.keywords(q.to_plain(query)), limit, year_min, year_max)


def lookup_dois(dois: list[str]) -> list[Paper]:
    """Batch lookup by DOI (50 per request; arXiv papers via their 10.48550/arxiv.* DOIs)."""
    out: list[Paper] = []
    clean = [d for d in dict.fromkeys(d.lower() for d in dois if d)]
    for i in range(0, len(clean), 50):
        chunk = "|".join(clean[i : i + 50])
        data = _get("/works", {"filter": "doi:" + chunk, "per-page": 50, "select": SELECT})
        out.extend(p for p in map(to_paper, data.get("results") or []) if p)
    return out


def doi_of(p: Paper) -> str | None:
    """The DOI OpenAlex indexes a paper under (arXiv preprints use their DataCite DOI)."""
    if p.doi:
        return p.doi
    return f"10.48550/arxiv.{p.arxiv_id.lower()}" if p.arxiv_id else None


def get_work(key: str, select: str = SELECT) -> dict | None:
    """key: 'W123', 'doi:10.1/x'. Returns None when OpenAlex doesn't know it."""
    try:
        return _get("/works/" + urllib.parse.quote(key, safe="/:"), {"select": select})
    except NotFound:
        return None


def resolve(p: Paper) -> dict | None:
    """Find the OpenAlex work for a paper (with its reference list)."""
    select = SELECT + ",referenced_works"
    if p.openalex_id:
        w = get_work(p.openalex_id, select)
        if w:
            return w
    if p.doi:
        w = get_work("doi:" + p.doi, select)
        if w:
            return w
    if p.arxiv_id:
        return get_work("doi:10.48550/arxiv." + p.arxiv_id, select)
    return None


def get_works(ids: list[str]) -> list[Paper]:
    """Fetch many works by OpenAlex id (W...)."""
    short = [i.rstrip("/").rsplit("/", 1)[-1] for i in ids]
    out: list[Paper] = []
    for i in range(0, len(short), 50):
        chunk = short[i : i + 50]
        data = _get("/works", {"filter": "openalex:" + "|".join(chunk), "per-page": 50, "select": SELECT})
        out.extend(p for p in map(to_paper, data.get("results") or []) if p)
    return out


def cited_by(openalex_id: str, limit: int = 50, sort: str = "cited_by_count:desc") -> list[Paper]:
    works, _ = _paged({"filter": f"cites:{openalex_id}", "sort": sort, "select": SELECT}, limit)
    return [p for p in map(to_paper, works) if p]
