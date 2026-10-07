"""Import an existing list of papers (CSV/TSV, RIS, BibTeX), e.g. a Scopus export or a labelled benchmark.

Columns and tags are matched by common names, so exports from Scopus, Web of Science, Zotero, ASReview and
the SYNERGY dataset load without settings. A label column (label_included, included, label, ...) is kept in
`extra["label"]` (1 = included by the human reviewers, 0 = excluded) for `lr.py eval`.
Rows that carry only identifiers (SYNERGY's *_ids.csv) get their title and abstract from OpenAlex.

Every reader fills a `stats` dict (rows read, rows skipped and how many of them were labelled included,
unreadable label values, the label column used), so nothing is dropped silently.
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
LABEL_COLUMNS = ("label_included", "included", "label", "inclusion", "final_included")
_TRUE = {"1", "1.0", "true", "yes", "y", "include", "included", "relevant"}
_FALSE = {"0", "0.0", "false", "no", "n", "exclude", "excluded", "irrelevant"}

RIS_TAGS = {"TI": "title", "T1": "title", "AB": "abstract", "N2": "abstract", "DO": "doi", "PY": "year",
            "Y1": "year", "DA": "year", "JO": "venue", "JF": "venue", "T2": "venue", "J2": "venue",
            "AU": "authors", "A1": "authors", "UR": "url"}
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])\s{1,2}-(?:\s(.*))?$")
_LATEX = {'"': "̈", "'": "́", "`": "̀", "^": "̂", "~": "̃", "c": "̧"}


def new_stats() -> dict:
    return {"rows": 0, "skipped": 0, "skipped_included": 0, "unreadable_labels": 0, "label_column": None}


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


def _add(out: list, stats: dict, fields: dict, raw_label) -> None:
    """Build one Paper; count it as skipped (and whether it was a labelled inclusion) when it is unusable."""
    stats["rows"] += 1
    lab = None
    if raw_label not in (None, ""):
        lab = parse_label(raw_label)
        if lab is None:
            stats["unreadable_labels"] += 1
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
    if lab is not None:
        p.extra["label"] = lab
    p.normalize()
    if not (p.title or p.doi or p.openalex_id or p.arxiv_id):
        stats["skipped"] += 1
        stats["skipped_included"] += lab == 1
        return
    out.append(p)


def _delimiter(header: str, path: str) -> str:
    if path.lower().endswith(".tsv"):
        return "\t"
    counts = {d: header.count(d) for d in ("\t", ";", ",")}
    return max(counts, key=lambda d: (counts[d], d == ","))


def read_table(path: str, stats: dict, label_column: str | None = None) -> list[Paper]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = f.readline()
        f.seek(0)
        delimiter = _delimiter(header, path)
        # tab-delimited exports (Web of Science) contain stray quotes inside titles: don't treat them as quoting
        quoting = csv.QUOTE_NONE if delimiter == "\t" else csv.QUOTE_MINIMAL
        reader = csv.DictReader(f, delimiter=delimiter, quoting=quoting)
        headers = {h.strip().lower(): h for h in reader.fieldnames or [] if h}
        cols = {field: next((headers[n] for n in names if n in headers), None) for field, names in COLUMNS.items()}
        if label_column:
            label_col = headers.get(label_column.strip().lower())
            if not label_col:
                raise ValueError(f"{path}: no column named {label_column!r}")
        else:
            label_col = next((headers[n] for n in LABEL_COLUMNS if n in headers), None)
        stats["label_column"] = label_col
        if not any(cols[k] for k in ("title", "doi", "openalex_id", "arxiv_id")):
            raise ValueError(f"{path}: no title, doi, openalex_id or arxiv_id column (found: {', '.join(headers)})")
        out: list[Paper] = []
        try:
            for row in reader:
                fields = {k: (row.get(c) or "").strip() for k, c in cols.items() if c}
                _add(out, stats, fields, row.get(label_col) if label_col else None)
        except csv.Error as e:
            raise ValueError(f"{path}: malformed CSV near line {reader.line_num}: {e}") from None
        return out


def read_ris(path: str, stats: dict, label_column: str | None = None) -> list[Paper]:
    out: list[Paper] = []
    fields: dict = {}
    raw_label = None
    last = None
    started = False

    def flush():
        nonlocal fields, raw_label, last, started
        if started:
            _add(out, stats, fields, raw_label)
        fields, raw_label, last, started = {}, None, None, False

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = _RIS_LINE.match(line)
            if not m:
                if last and line.strip():  # continuation of a multi-line field (abstracts)
                    if last == "authors":
                        fields["authors"][-1] += " " + line.strip()
                    else:
                        fields[last] = (fields.get(last, "") + " " + line.strip()).strip()
                continue
            tag, value = m.group(1), (m.group(2) or "").strip()
            if tag == "TY":
                flush()
                started = True
            elif tag == "ER":
                flush()
                continue
            started = True
            last = None
            if tag in RIS_TAGS:
                key = RIS_TAGS[tag]
                if key == "authors":
                    fields.setdefault("authors", []).append(value)
                    last = key
                elif key not in fields:
                    fields[key] = value
                    last = key
            elif tag == "N1" and re.match(r"^(label|included)\s*:", value, re.I):
                raw_label = value.split(":", 1)[1]
    flush()  # last record without ER
    return out


def _delatex(s: str) -> str:
    """M{\\"o}ller -> Möller, {BibTeX} -> BibTeX, \\& -> &."""
    s = re.sub(r"\{?\\([\"'`^~c])\{?([A-Za-z])\}?\}?",
               lambda m: m.group(2) + _LATEX[m.group(1)], s)
    s = re.sub(r"\\([&%$#_])", r"\1", s)
    return re.sub(r"[{}]", "", s)


_BIB_START = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
_BIB_FIELD = re.compile(r"\s*,?\s*([A-Za-z_][\w-]*)\s*=\s*")


def _bib_value(body: str, pos: int) -> tuple[str, int, bool]:
    """Value starting at body[pos]; returns (value, position after it, balanced)."""
    if body[pos] == "{":
        depth, e = 0, pos
        while e < len(body):
            if body[e] == "\\":
                e += 2
                continue
            depth += {"{": 1, "}": -1}.get(body[e], 0)
            if depth == 0:
                return body[pos + 1 : e], e + 1, True
            e += 1
        return body[pos + 1 :], len(body), False
    if body[pos] == '"':
        e, depth = pos + 1, 0
        while e < len(body):
            if body[e] == "\\":
                e += 2
                continue
            if body[e] == '"' and depth == 0:
                return body[pos + 1 : e], e + 1, True
            depth += {"{": 1, "}": -1}.get(body[e], 0)
            e += 1
        return body[pos + 1 :], len(body), False
    m = re.match(r"[^,}\s]*", body[pos:])
    return m.group(0), pos + m.end(), True


def _bib_entries(text: str, warn: list):
    """Yield the field dict of each @type{key, ...} or @type(key, ...) entry, reading fields in order so an
    "x = y" inside a value is never taken for a field."""
    i = 0
    while (start := text.find("@", i)) != -1:
        m = _BIB_START.match(text, start)  # match in place: slicing the rest of the file per entry is quadratic
        if not m:
            i = start + 1
            continue
        kind, opener = m.group(1).lower(), m.group(2)
        closer = "}" if opener == "{" else ")"
        j, depth = m.end() - 1, 0
        while j < len(text):
            if text[j] == "\\":
                j += 2
                continue
            if text[j] == opener or (opener == "(" and text[j] == "{"):
                depth += 1
            elif text[j] == closer or (opener == "(" and text[j] == "}"):
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            warn.append(f"unbalanced braces in @{kind} entry starting at character {start}; rest of file ignored")
            j = len(text)
        body, i = text[m.end() : j], j + 1
        if kind in ("comment", "string", "preamble"):
            continue
        fields: dict = {}
        pos = body.find(",") + 1 if "," in body else len(body)
        while pos < len(body):
            fm = _BIB_FIELD.match(body, pos)
            if not fm or fm.end() >= len(body):
                break
            value, pos, ok = _bib_value(body, fm.end())
            if not ok:
                warn.append(f"unterminated value for field {fm.group(1)!r} in @{kind} entry")
            fields.setdefault(fm.group(1).lower(), _delatex(" ".join(value.split())))
        yield fields


def read_bibtex(path: str, stats: dict, label_column: str | None = None) -> list[Paper]:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    out: list[Paper] = []
    warn: list[str] = []
    label_key = (label_column or "").lower()
    for e in _bib_entries(text, warn):
        is_arxiv = "arxiv" in ((e.get("archiveprefix") or "") + (e.get("eprinttype") or "")).lower()
        fields = {"title": e.get("title"), "abstract": e.get("abstract"), "doi": e.get("doi"),
                  "year": e.get("year") or e.get("date"), "venue": e.get("journal") or e.get("booktitle"),
                  "authors": e.get("author"), "url": e.get("url"),
                  "arxiv_id": e.get("eprint") if is_arxiv else None}
        raw = e.get(label_key) if label_key else (e.get("label") if e.get("label") is not None else e.get("included"))
        _add(out, stats, {k: v for k, v in fields.items() if v}, raw)
    for w in warn:
        info(f"  {path}: {w}")
    return out


READERS = {".csv": read_table, ".tsv": read_table, ".txt": read_table, ".ris": read_ris, ".bib": read_bibtex}


def read_file(path: str, stats: dict | None = None, label_column: str | None = None) -> list[Paper]:
    stats = new_stats() if stats is None else stats
    ext = os.path.splitext(path)[1].lower()
    if ext not in READERS:
        raise ValueError(f"{path}: unsupported file type {ext!r} (use .csv, .tsv, .txt, .ris or .bib)")
    try:
        papers = READERS[ext](path, stats, label_column)
    except UnicodeDecodeError as e:
        raise ValueError(f"{path}: not UTF-8 text ({e})") from None
    if not papers and os.path.getsize(path) > 0:
        raise ValueError(f"{path}: no records found")
    if stats["skipped"]:
        info(f"  {path}: skipped {stats['skipped']} rows with no title or identifier "
             f"({stats['skipped_included']} of them labelled included)")
    if stats["unreadable_labels"]:
        info(f"  {path}: {stats['unreadable_labels']} label values not understood (kept unlabelled)")
    return papers


def fill_from_openalex(papers: list[Paper]) -> tuple[int, list[str]]:
    """Fetch title/abstract/metadata for records that only carry identifiers. Returns (filled, errors).
    A failing batch is reported and the remaining batches still run."""
    bare = [p for p in papers if not p.title]
    if not bare:
        return 0, []
    info(f"  fetching titles and abstracts for {len(bare)} records from OpenAlex")
    errors: list[str] = []
    filled = 0
    by_oa: dict[str, list[Paper]] = {}
    for p in bare:
        if p.openalex_id:
            by_oa.setdefault(p.openalex_id, []).append(p)
    ids = list(by_oa)
    for i in range(0, len(ids), 50):
        try:
            for q in openalex.get_works(ids[i : i + 50]):
                for p in by_oa.get(q.openalex_id or "", []):
                    filled += _copy_metadata(p, q)
        except HttpError as e:
            errors.append(f"OpenAlex ids batch {i // 50 + 1}: {e}")
    # merged/unknown OpenAlex ids and records without one: by DOI (arXiv ids via their DataCite DOI)
    by_doi: dict[str, list[Paper]] = {}
    for p in bare:
        if not p.title and openalex.doi_of(p):
            by_doi.setdefault(openalex.doi_of(p), []).append(p)
    dois = list(by_doi)
    for i in range(0, len(dois), 50):
        try:
            for q in openalex.lookup_dois(dois[i : i + 50]):
                for p in by_doi.get(openalex.doi_of(q) or "", []):
                    filled += _copy_metadata(p, q)
        except HttpError as e:
            errors.append(f"OpenAlex DOI batch {i // 50 + 1}: {e}")
    return filled, errors


def _copy_metadata(p: Paper, q: Paper) -> int:
    had_title = bool(p.title)
    for name in ("title", "abstract", "doi", "openalex_id", "arxiv_id", "year", "venue", "authors", "url",
                 "pdf_url", "citation_count", "language", "type"):
        if getattr(p, name) in (None, "", []) and getattr(q, name) not in (None, "", []):
            setattr(p, name, getattr(q, name))
    p.normalize()
    return int(bool(p.title) and not had_title)
