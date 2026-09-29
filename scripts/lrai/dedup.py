"""Duplicate detection and record merging.

Two records are the same paper if they share a DOI, arXiv id, OpenAlex id or Semantic Scholar id,
or if their normalized titles match and their years are at most one apart (preprint vs. published).
"""
from __future__ import annotations

import copy
import difflib
import re

from .models import Paper, norm_title

_FILL_FIELDS = (
    "title", "year", "venue", "doi", "arxiv_id", "openalex_id", "s2_id", "url", "pdf_url",
    "language", "type", "excluded_reason", "status", "status_reason", "relevance", "short_summary",
    "summary", "rq_relation", "first_level", "second_level", "priority", "code",
)


def _years_compatible(a: Paper, b: Paper) -> bool:
    return a.year is None or b.year is None or abs(a.year - b.year) <= 1


def _published_rank(p: Paper) -> int:
    venue = (p.venue or "").lower()
    if venue and "arxiv" not in venue and "ssrn" not in venue and "rxiv" not in venue:
        return 2
    return 1 if venue else 0


def merge_two(a: Paper, b: Paper) -> Paper:
    """Merge two records of the same paper. The published version's metadata wins; blanks are filled."""
    primary, other = (b, a) if _published_rank(b) > _published_rank(a) else (a, b)
    m = copy.deepcopy(primary)
    for name in _FILL_FIELDS:
        if getattr(m, name) in (None, ""):
            setattr(m, name, getattr(other, name))
    if len(other.abstract or "") > len(m.abstract or ""):
        m.abstract = other.abstract
    if len(other.authors) > len(m.authors):
        m.authors = list(other.authors)
    counts = [c for c in (a.citation_count, b.citation_count) if c is not None]
    m.citation_count = max(counts) if counts else None
    m.found_via = list(dict.fromkeys(list(a.found_via) + list(b.found_via)))
    m.round = min(a.round, b.round)
    m.extra = {**other.extra, **primary.extra}
    return m.normalize()


_NUMBERING = re.compile(r"\b(?:\d+|i{1,3}|iv|vi{0,3}|ix|x)\b")


def similar_titles(a: str, b: str) -> bool:
    """Near-identical normalized titles, e.g. a preprint and its journal version with one word changed.
    Titles that differ in numbering ("Part I" vs "Part II", "GPT-3" vs "GPT-4") never match."""
    if _NUMBERING.findall(a) != _NUMBERING.findall(b):
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.93


def group(papers: list[Paper]) -> list[list[int]]:
    """Union-find over identifier keys, then fuzzy title matching within blocks of titles that share a
    prefix. Returns index groups ordered by first appearance."""
    parent = list(range(len(papers)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    seen: dict[str, int] = {}
    for i, p in enumerate(papers):
        for key in p.dedup_keys():
            j = seen.get(key)
            if j is None:
                seen[key] = i
            elif key.startswith("title:") and not _years_compatible(papers[j], p):
                continue
            else:
                union(i, j)

    blocks: dict[str, list[int]] = {}
    titles = [norm_title(p.title) for p in papers]
    for i, t in enumerate(titles):
        if len(t) >= 30:
            blocks.setdefault(t[:20], []).append(i)
    for idxs in blocks.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if find(i) != find(j) and titles[i] != titles[j] and _years_compatible(papers[i], papers[j]) \
                        and similar_titles(titles[i], titles[j]):
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(papers)):
        groups.setdefault(find(i), []).append(i)
    return [groups[r] for r in sorted(groups)]


def dedup(papers: list[Paper]) -> list[Paper]:
    out = []
    for idxs in group(papers):
        merged = papers[idxs[0]]
        for i in idxs[1:]:
            merged = merge_two(merged, papers[i])
        out.append(merged)
    return out


def merge_into(existing: list[Paper], new: list[Paper]) -> tuple[list[Paper], int]:
    """Add `new` records to `existing`, merging duplicates. Returns (merged list, number of genuinely new papers)."""
    combined = list(existing) + list(new)
    n_existing = len(existing)
    out, added = [], 0
    for idxs in group(combined):
        merged = combined[idxs[0]]
        for i in idxs[1:]:
            merged = merge_two(merged, combined[i])
        if idxs[0] >= n_existing:
            added += 1
        out.append(merged)
    return out, added
