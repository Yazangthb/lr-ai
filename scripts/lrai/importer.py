"""Import an existing list of papers (CSV/TSV, RIS, BibTeX), e.g. a Scopus export or a labelled benchmark.

Columns and tags are matched by common names, so exports from Scopus, Web of Science, Zotero, ASReview and
the SYNERGY dataset load without settings. A label column (label_included, included, label, ...) is kept in
`extra["label"]` (1 = included by the human reviewers, 0 = excluded) for `lr.py eval`.
Rows that carry only identifiers (SYNERGY's *_ids.csv) get their title and abstract from OpenAlex.
"""
from __future__ import annotations

import csv
import os
import re

from .http import HttpError
from .models import Paper, norm_doi
from .sources import openalex
from .util import info

# lower-cased header -> Paper field; the first matching column wins
COLUMNS = {
    "title": ("title", "ti", "article title", "document title", "primary title", "display_name"),
    "abstract": ("abstract", "ab", "abstract note", "abstractnote"),
    "doi": ("doi", "di", "do"),
    "openalex_id": ("openalex_id", "openalex", "openalex id"),
    "arxiv_id": ("arxiv_id", "arxiv", "eprint"),
    "year": ("year", "publication_year", "publication year", "py", "pubyear"),
    "venue": ("venue", "journal", "source title", "source", "publication title", "so", "journal/book",
              "secondary title"),
    "authors": ("authors", "author", "au", "author full names"),
    "url": ("url", "link"),
}
LABEL_COLUMNS = ("label_included", "included", "label", "inclusion", "final_included", "label_abstract_screening")
_TRUE = {"1", "1.0", "true", "yes", "y", "include", "included", "relevant"}
_FALSE = {"0", "0.0", "false", "no", "n", "exclude", "excluded", "irrelevant"}

RIS_TAGS = {"TI": "title", "T1": "title", "AB": "abstract", "N2": "abstract", "DO": "doi", "PY": "year",
            "Y1": "year", "DA": "year", "JO": "venue", "JF": "venue", "T2": "venue", "J2": "venue",
            "AU": "authors", "A1": "authors", "UR": "url"}


def parse_label(value) -> int | None:
    v = str(value if value is not None else "").strip().lower()
    if v in _TRUE:
        return 1
    if v in _FALSE:
        return 0
    return None


def _year(value) -> int | None:
    m = re.search(r"(1[89]\d\d|20\d\d)", str(value or ""))
    return int(m.group(1)) if m else None


def _authors(value) -> list[str]:
    if isinstance(value, list):
        return [str(a).strip() for a in value if str(a).strip()]
    parts = re.split(r";|\s+and\s+", str(value or ""))
    return [p.strip() for p in parts if p.strip()]


def _paper(fields: dict, label) -> Paper | None:
    p = Paper(
        title=fields.get("title") or "",
        abstract=fields.get("abstract") or None,
        doi=norm_doi(fields.get("doi")),
        openalex_id=fields.get("openalex_id") or None,
        arxiv_id=fields.get("arxiv_id") or None,
        year=_year(fields.get("year")),
        venue=fields.get("venue") or None,
        authors=_authors(fields.get("authors")),
        url=fields.get("url") or None,
    )
    if label is not None:
        p.extra["label"] = label
    if not (p.title or p.doi or p.openalex_id or p.arxiv_id):
        return None
    return p.normalize()


def read_table(path: str) -> list[Paper]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = "\t" if path.lower().endswith(".tsv") or sample.count("\t") > sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = {h.strip().lower(): h for h in reader.fieldnames or [] if h}
        cols = {field: next((headers[n] for n in names if n in headers), None) for field, names in COLUMNS.items()}
        label_col = next((headers[n] for n in LABEL_COLUMNS if n in headers), None)
        if not any(cols[k] for k in ("title", "doi", "openalex_id", "arxiv_id")):
            raise ValueError(f"{path}: no title, doi, openalex_id or arxiv_id column (found: {', '.join(headers)})")
        out, skipped = [], 0
        for row in reader:
            fields = {k: (row.get(c) or "").strip() for k, c in cols.items() if c}
            p = _paper(fields, parse_label(row.get(label_col)) if label_col else None)
            if p:
                out.append(p)
            else:
                skipped += 1
        if skipped:
            info(f"  {path}: skipped {skipped} rows with no title or identifier")
        return out


def read_ris(path: str) -> list[Paper]:
    out, fields, label = [], {}, None
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            m = re.match(r"^([A-Z][A-Z0-9])  -\s?(.*)$", line.rstrip("\r\n"))
            if not m:
                continue
            tag, value = m.group(1), m.group(2).strip()
            if tag == "ER":
                p = _paper(fields, label)
                if p:
                    out.append(p)
                fields, label = {}, None
            elif tag in RIS_TAGS:
                key = RIS_TAGS[tag]
                if key == "authors":
                    fields.setdefault("authors", []).append(value)
                else:
                    fields.setdefault(key, value)
            elif tag == "N1" and value.lower().startswith(("label:", "included:")):
                label = parse_label(value.split(":", 1)[1])
    return out


def _bib_entries(text: str):
    """Yield the field dict of each @type{key, ...} entry; handles nested braces and quoted values."""
    i = 0
    while (start := text.find("@", i)) != -1:
        brace = text.find("{", start)
        if brace == -1:
            return
        kind = text[start + 1 : brace].strip().lower()
        depth, j = 0, brace
        while j < len(text):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                break
            j += 1
        body, i = text[brace + 1 : j], j + 1
        if kind in ("comment", "string", "preamble"):
            continue
        fields, k = {}, body.find(",") + 1
        for m in re.finditer(r"([A-Za-z_-]+)\s*=\s*", body[k:]):
            pos = k + m.end()
            if pos >= len(body):
                break
            if body[pos] == "{":
                depth, e = 0, pos
                while e < len(body):
                    depth += {"{": 1, "}": -1}.get(body[e], 0)
                    if depth == 0:
                        break
                    e += 1
                value = body[pos + 1 : e]
            elif body[pos] == '"':
                e = body.find('"', pos + 1)
                value = body[pos + 1 : e if e != -1 else len(body)]
            else:
                value = re.match(r"[^,}\s]*", body[pos:]).group(0)
            fields.setdefault(m.group(1).lower(), re.sub(r"[{}]", "", " ".join(value.split())))
        yield fields


def read_bibtex(path: str) -> list[Paper]:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    out = []
    for e in _bib_entries(text):
        fields = {"title": e.get("title"), "abstract": e.get("abstract"), "doi": e.get("doi"),
                  "year": e.get("year"), "venue": e.get("journal") or e.get("booktitle"),
                  "authors": e.get("author"), "url": e.get("url"),
                  "arxiv_id": e.get("eprint") if (e.get("archiveprefix") or "").lower() == "arxiv" else None}
        p = _paper({k: v for k, v in fields.items() if v}, parse_label(e.get("label") or e.get("included")))
        if p:
            out.append(p)
    return out


READERS = {".csv": read_table, ".tsv": read_table, ".txt": read_table, ".ris": read_ris, ".bib": read_bibtex}


def read_file(path: str) -> list[Paper]:
    ext = os.path.splitext(path)[1].lower()
    if ext not in READERS:
        raise ValueError(f"{path}: unsupported file type {ext!r} (use .csv, .tsv, .ris or .bib)")
    return READERS[ext](path)


def fill_from_openalex(papers: list[Paper]) -> tuple[int, list[str]]:
    """Fetch title/abstract/metadata for records that only carry identifiers. Returns (filled, errors)."""
    bare = [p for p in papers if not p.title]
    if not bare:
        return 0, []
    info(f"  fetching titles and abstracts for {len(bare)} records from OpenAlex")
    errors, filled = [], 0
    try:
        by_oa = {p.openalex_id: p for p in bare if p.openalex_id}
        for q in openalex.get_works(list(by_oa)):
            p = by_oa.get(q.openalex_id or "")
            if p is not None:
                filled += _copy_metadata(p, q)
        # merged or unknown OpenAlex ids: fall back to the DOI
        by_doi = {p.doi: p for p in bare if p.doi and not p.title}
        for q in openalex.lookup_dois(list(by_doi)):
            p = by_doi.get(q.doi or "")
            if p is not None:
                filled += _copy_metadata(p, q)
    except HttpError as e:
        errors.append(f"OpenAlex: {e}")
    return filled, errors


def _copy_metadata(p: Paper, q: Paper) -> bool:
    for name in ("title", "abstract", "doi", "openalex_id", "arxiv_id", "year", "venue", "authors", "url",
                 "pdf_url", "citation_count", "language", "type"):
        if getattr(p, name) in (None, "", []) and getattr(q, name) not in (None, "", []):
            setattr(p, name, getattr(q, name))
    p.normalize()
    return bool(p.title)
