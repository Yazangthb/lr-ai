"""Backward (references) and forward (citations) snowballing.

One call = one round: every frontier paper is expanded, and the neighbors are returned as new records
carrying provenance ("backward:<parent id>" / "forward:<parent id>") and the round number.

OpenAlex is tried first; Semantic Scholar fills in per direction (OpenAlex's reference lists are
incomplete for many preprints). A source is switched off for the rest of the round only after an error
that will not go away (quota, missing key) or three consecutive failures.
"""
from __future__ import annotations

from .http import HttpError
from .models import Paper
from .sources import openalex
from .sources import semantic_scholar as s2
from .util import info, shorten

ALL_CITATIONS_CAP = 2000  # "max_citations: null" means all, with a safety net for extremely cited papers


def _by_citations(papers: list[Paper]) -> list[Paper]:
    return sorted(papers, key=lambda p: -(p.citation_count or 0))


def _persistent(e: HttpError) -> bool:
    """Errors that retrying later in this round won't fix. Transient 429s are handled by the HTTP layer and
    by the three-consecutive-failures rule instead."""
    msg = str(e).lower()
    return e.persistent or e.status in (401, 403) or any(w in msg for w in ("quota", "credit", "budget"))


class _Source:
    """Tracks whether a backend is still worth calling during this round."""

    def __init__(self, name: str, enabled: bool):
        self.name, self.enabled, self.failures = name, enabled, 0

    def failed(self, e: HttpError, stats: dict) -> None:
        stats["errors"].append(f"{self.name}: {shorten(str(e), 200)}")
        self.failures += 1
        if _persistent(e) or self.failures >= 3:
            self.enabled = False
            info(f"  {self.name} unavailable ({shorten(str(e), 120)}); not using it for the rest of this round")

    def ok(self) -> None:
        self.failures = 0


def snowball_round(frontier: list[Paper], round_no: int, direction: str = "both", backend: str = "auto",
                   max_refs: int | None = 200, max_cites: int | None = 50) -> tuple[list[Paper], dict]:
    backward = direction in ("backward", "both")
    cites_cap = ALL_CITATIONS_CAP if max_cites is None else int(max_cites)
    forward = direction in ("forward", "both") and cites_cap > 0
    stats = {"frontier": len(frontier), "references": 0, "citations": 0, "backend": {},
             "unresolved": [], "failed": [], "errors": []}
    oa = _Source("OpenAlex", backend in ("auto", "openalex"))
    ss = _Source("Semantic Scholar", backend in ("auto", "semantic_scholar"))
    found: list[Paper] = []

    for i, p in enumerate(frontier, 1):
        refs: list[Paper] | None = None  # None = not obtained
        cites: list[Paper] | None = None
        used: list[str] = []
        errored = False
        if oa.enabled:
            try:
                work = openalex.resolve(p)
                if work:
                    wid = work["id"].rstrip("/").rsplit("/", 1)[-1]
                    p.openalex_id = p.openalex_id or wid
                    refs = _by_citations(openalex.get_works(work.get("referenced_works") or [])) if backward else []
                    cites = openalex.cited_by(wid, cites_cap) if forward else []
                    used.append("openalex")
                oa.ok()
            except HttpError as e:
                errored = True
                oa.failed(e, stats)
        need_refs = backward and not refs
        need_cites = forward and not cites
        if ss.enabled and (need_refs or need_cites):
            try:
                got = False
                if need_refs:
                    r = s2.references(p)
                    if r is not None:
                        refs, got = _by_citations(r), got or bool(r)
                if need_cites:
                    c = s2.citations(p, cap=max(1000, cites_cap))
                    if c is not None:
                        cites, got = _by_citations(c)[:cites_cap], got or bool(c)
                if got:
                    used.append("semantic_scholar")
                ss.ok()
            except HttpError as e:
                errored = True
                ss.failed(e, stats)
        if refs is None and cites is None:
            (stats["failed"] if errored else stats["unresolved"]).append(p.id)
            info(f"  [{i}/{len(frontier)}] {'API error' if errored else 'not found in any database'}: "
                 f"{shorten(p.title, 70)}")
            continue
        if errored:
            stats["failed"].append(p.id)  # partially expanded; re-running the round fills the gap
        refs = (refs or [])[:max_refs] if max_refs else (refs or [])
        cites = cites or []
        key = "+".join(used) or "none"
        stats["backend"][key] = stats["backend"].get(key, 0) + 1
        stats["references"] += len(refs)
        stats["citations"] += len(cites)
        for q in refs:
            q.found_via = [f"backward:{p.id}"]
            q.round = round_no
        for q in cites:
            q.found_via = [f"forward:{p.id}"]
            q.round = round_no
        found.extend(refs)
        found.extend(cites)
        info(f"  [{i}/{len(frontier)}] {len(refs)} refs, {len(cites)} citing ({key}): {shorten(p.title, 60)}")
    return found, stats
