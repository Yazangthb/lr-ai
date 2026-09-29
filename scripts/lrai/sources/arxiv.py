"""arXiv API client (https://info.arxiv.org/help/api/). Asks for >= 3 s between requests."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Callable

from .. import query as q
from ..http import HttpError, request
from ..models import Paper, norm_arxiv

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
MIN_INTERVAL = 3.1


def total_results(xml_text: str) -> int | None:
    node = ET.fromstring(xml_text).find("os:totalResults", {"os": "http://a9.com/-/spec/opensearch/1.1/"})
    return int(node.text) if node is not None and (node.text or "").isdigit() else None


def parse_feed(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        id_url = e.findtext("a:id", default="", namespaces=NS)
        title = " ".join(e.findtext("a:title", default="", namespaces=NS).split())
        if "api/errors" in id_url or title == "Error":
            raise HttpError(400, "arXiv rejected the query: " + " ".join(e.findtext("a:summary", "", NS).split()))
        published = e.findtext("a:published", default="", namespaces=NS)
        pdf = next((ln.get("href") for ln in e.findall("a:link", NS) if ln.get("title") == "pdf"), None)
        journal_ref = e.findtext("arxiv:journal_ref", default="", namespaces=NS).strip()
        aid = norm_arxiv(id_url)
        out.append(Paper(
            title=title,
            authors=[a.findtext("a:name", default="", namespaces=NS) for a in e.findall("a:author", NS)],
            year=int(published[:4]) if published[:4].isdigit() else None,
            venue=journal_ref or "arXiv",
            doi=e.findtext("arxiv:doi", default=None, namespaces=NS),
            arxiv_id=aid,
            url=f"https://arxiv.org/abs/{aid}" if aid else None,
            pdf_url=pdf,
            abstract=e.findtext("a:summary", default="", namespaces=NS),
            type="preprint",
            language="en",
        ).normalize())
    return out


def _expected(total: int | None, start: int, n: int) -> int:
    return n if total is None else max(0, min(n, total - start))


def _complete_page(start: int, n: int) -> Callable[[str], bool]:
    """Cache a page only if it holds every entry it should (the API sometimes returns short pages)."""
    def check(text: str) -> bool:
        try:
            return len(parse_feed(text)) >= _expected(total_results(text), start, n)
        except (ET.ParseError, HttpError):
            return False
    return check


def search(query: str, limit: int = 100, year_min: int | None = None,
           year_max: int | None = None) -> tuple[list[Paper], int | None]:
    """Relevance-ranked search -> (papers, total matches)."""
    search_query = q.to_arxiv(query)
    if year_min or year_max:
        search_query = f"({search_query}) AND submittedDate:[{year_min or 1991}01010000 TO {year_max or 2100}12312359]"
    out: list[Paper] = []
    total = None
    start = 0
    while len(out) < limit:
        n = min(100, limit - len(out))
        params = {"search_query": search_query, "start": start, "max_results": n,
                  "sortBy": "relevance", "sortOrder": "descending"}
        batch: list[Paper] = []
        for attempt in range(3):  # the API occasionally returns empty, short or unreadable pages; retry those
            text = request(API, params, min_interval=MIN_INTERVAL, refresh=attempt > 0,
                           cache_check=_complete_page(start, n))
            try:
                batch = parse_feed(text)
                total = total_results(text) if total is None else total
            except ET.ParseError:
                if attempt == 2:
                    raise HttpError(None, f"arXiv returned an unreadable response: {text[:120]!r}") from None
                time.sleep(MIN_INTERVAL)
                continue
            if len(batch) >= _expected(total, start, n):
                break
            time.sleep(MIN_INTERVAL)
        out.extend(batch)
        start += n
        if not batch or (total is not None and start >= total):
            break
    return out[:limit], total
