"""Resolve user-supplied references (DOIs, arXiv ids, Semantic Scholar ids, exact titles) to papers.

Papers resolved here are protected from the automatic filters, so a title lookup is only accepted when
the returned title really matches; otherwise the user gets an explicit error.
"""
from __future__ import annotations

import re

from .dedup import similar_titles
from .http import HttpError
from .models import Paper, norm_arxiv, norm_doi, norm_title
from .sources import arxiv, openalex
from .sources import semantic_scholar as s2
from .util import shorten

_DOI = re.compile(r"^(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)$", re.I)
_ARXIV = re.compile(r"^(?:arxiv:\s*|(?:https?://)?arxiv\.org/(?:abs|pdf)/)?"
                    r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?$", re.I)
_S2 = re.compile(r"^[0-9a-f]{40}$")


def classify(item: str) -> tuple[str, str]:
    s = str(item).strip()
    if m := _DOI.match(s):
        return "doi", norm_doi(m.group(1)) or s
    if m := _ARXIV.match(s):
        return "arxiv", norm_arxiv(m.group(1)) or s
    if _S2.match(s):
        return "s2", s
    return "title", s


def same_title(a: str, b: str) -> bool:
    na, nb = norm_title(a), norm_title(b)
    return bool(na) and (na == nb or similar_titles(na, nb))


def _match_title(title: str) -> tuple[Paper | None, str]:
    """-> (paper, "") or (None, why). Tries Semantic Scholar, OpenAlex, then arXiv."""
    notes: list[str] = []
    clean = title.replace('"', " ")
    attempts = (
        ("Semantic Scholar", lambda: [p for p in [s2.match_title(title)] if p]),
        ("OpenAlex", lambda: openalex.search(f'"{clean}"', limit=5)[0]),
        ("arXiv", lambda: arxiv.search(f'ti:"{clean}"', limit=5)[0]),
    )
    for name, fetch in attempts:
        try:
            candidates = fetch()
        except HttpError as e:
            notes.append(f"{name} lookup failed ({shorten(str(e), 80)})")
            continue
        match = next((p for p in candidates if same_title(p.title, title)), None)
        if match:
            return match, ""
        if candidates:
            notes.append(f"{name}'s closest title differs: {shorten(candidates[0].title, 70)!r}")
    return None, "; ".join(notes) or "no match in any database"


def resolve(items: list, tag: str) -> tuple[list[Paper], list[str]]:
    """-> (papers with found_via=[tag], errors). OpenAlex first (free lookups), then Semantic Scholar."""
    errors: list[str] = []
    ids = []
    for item in items:
        if isinstance(item, str):
            ids.append(classify(item))
        else:  # YAML reads an unquoted 2101.00010 as the number 2101.0001, i.e. a different paper
            errors.append(f"{item!r} is not text: put DOIs and arXiv ids in quotes in config.yaml")
    found: list[Paper] = []
    remaining: list[tuple[str, str]] = []
    oa_error = ""

    wanted = {}
    for kind, val in ids:
        if kind == "doi":
            wanted[val.lower()] = (kind, val)
        elif kind == "arxiv":
            wanted[f"10.48550/arxiv.{val.lower()}"] = (kind, val)
    if wanted:
        try:
            got = {openalex.doi_of(p): p for p in openalex.lookup_dois(list(wanted))}
        except HttpError as e:
            got, oa_error = {}, f" (OpenAlex lookup failed: {shorten(str(e), 80)})"
        for doi, ref in wanted.items():
            if doi in got:
                found.append(got[doi])
            else:
                remaining.append(ref)
    remaining += [(k, v) for k, v in ids if k == "s2"]

    if remaining:
        keys = [{"doi": "DOI:", "arxiv": "ARXIV:", "s2": ""}[k] + v for k, v in remaining]
        try:
            for key, p in zip(keys, s2.lookup(keys)):
                if p is None:
                    errors.append(f"not found: {key}{oa_error}")
                else:
                    found.append(p)
        except HttpError as e:
            errors.append(f"lookup failed for {', '.join(keys)}: {shorten(str(e), 100)}{oa_error}")

    for kind, title in ids:
        if kind == "title":
            p, why = _match_title(title)
            if p is None:
                errors.append(f"no confirmed match for title {shorten(title, 70)!r}: {why}")
            else:
                found.append(p)
    for p in found:
        p.found_via = [tag]
    return found, errors
