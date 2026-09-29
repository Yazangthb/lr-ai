"""The Paper record, identifier normalization, and JSONL persistence."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, fields

from .util import replace_file

STATUSES = ("core", "skim", "exclude")
PRIORITIES = ("high", "medium", "low")

_DOI_PREFIX = re.compile(r"^\s*(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:\s*)", re.I)
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?(?:[?#].*)?$", re.I)
_ARXIV_VERSION = re.compile(r"v\d+$", re.I)
_ARXIV_ID = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})$", re.I)
# HTML/JATS tags only: attributes must look like name="value", so math such as "a<b and c>d" survives
_MARKUP = re.compile(r"</?(?:i|b|u|em|strong|sub|sup|scp|span|p|jats:[a-z-]+)"
                     r"(?:\s+[a-z:-]+=(?:\"[^\"]*\"|'[^']*'))*\s*/?>", re.I)


def clean_text(s: str) -> str:
    """Repair lone UTF-16 surrogates (they arrive via JSON escapes) so the text can be written as UTF-8."""
    return s.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = _DOI_PREFIX.sub("", str(doi)).strip().lower()
    return d if d.startswith("10.") else None


def norm_arxiv(aid: str | None) -> str | None:
    """'arXiv:2401.01234v2', 'https://arxiv.org/abs/2401.01234' -> '2401.01234'. Old ids keep their case."""
    if not aid:
        return None
    a = str(aid).strip()
    m = _ARXIV_URL.search(a)
    if m:
        a = m.group(1)
    a = re.sub(r"^arxiv:\s*", "", a, flags=re.I)
    a = _ARXIV_VERSION.sub("", a)
    return a if _ARXIV_ID.match(a) else None


def norm_title(title: str | None) -> str:
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _MARKUP.sub(" ", t)
    t = re.sub(r"[\W_]+", " ", t.lower())  # keeps letters of every script, not just a-z
    return " ".join(t.split())


@dataclass
class Paper:
    title: str = ""
    authors: list = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    s2_id: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    abstract: str | None = None
    citation_count: int | None = None
    language: str | None = None
    type: str | None = None
    # provenance: "seed:q1", "search:openalex:q2", "backward:<parent id>", "forward:<parent id>", "manual"
    found_via: list = field(default_factory=list)
    round: int = 0  # 0 = seed/database search, n = found in snowballing round n
    excluded_reason: str | None = None  # set by deterministic filters
    # screening (title/abstract)
    status: str | None = None  # core | skim | exclude
    status_reason: str | None = None
    relevance: float | None = None
    short_summary: str | None = None
    # enrichment
    summary: str | None = None
    rq_relation: str | None = None
    first_level: str | None = None
    second_level: str | None = None
    priority: str | None = None  # high | medium | low
    code: str | None = None  # "yes" / "no" / repository URL
    extra: dict = field(default_factory=dict)

    def normalize(self) -> "Paper":
        self.title = " ".join(_MARKUP.sub("", html.unescape(clean_text(self.title or ""))).split())
        if self.venue:
            self.venue = " ".join(html.unescape(clean_text(str(self.venue))).split()) or None
        doi = norm_doi(self.doi)
        m = _ARXIV_DOI.match(doi or "")
        if m:  # arXiv's own DOIs just duplicate the arXiv id
            self.arxiv_id = self.arxiv_id or m.group(1)
            doi = None
        self.doi = doi
        self.arxiv_id = norm_arxiv(self.arxiv_id)
        if self.openalex_id:
            self.openalex_id = str(self.openalex_id).rstrip("/").rsplit("/", 1)[-1].upper()
        if isinstance(self.year, str):
            self.year = int(self.year) if self.year.isdigit() else None
        if self.abstract:
            self.abstract = " ".join(_MARKUP.sub("", html.unescape(clean_text(str(self.abstract)))).split()) or None
        self.authors = [clean_text(str(a)) for a in (self.authors or []) if a]
        return self

    @property
    def id(self) -> str:
        if self.doi:
            return "doi:" + self.doi
        if self.arxiv_id:
            return "arxiv:" + self.arxiv_id.lower()
        if self.openalex_id:
            return "openalex:" + self.openalex_id
        if self.s2_id:
            return "s2:" + self.s2_id
        key = norm_title(self.title) or self.title.casefold().strip()
        return "title:" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:12]

    def dedup_keys(self) -> list[str]:
        keys = []
        if self.doi:
            keys.append("doi:" + self.doi)
        if self.arxiv_id:
            keys.append("arxiv:" + self.arxiv_id.lower())
        if self.openalex_id:
            keys.append("openalex:" + self.openalex_id)
        if self.s2_id:
            keys.append("s2:" + self.s2_id)
        nt = norm_title(self.title)
        if len(nt) >= 20:  # short titles ("Introduction", "Editorial") are too ambiguous to match on
            keys.append("title:" + nt)
        return keys

    @property
    def link(self) -> str | None:
        if self.doi:
            return "https://doi.org/" + self.doi
        if self.arxiv_id:
            return "https://arxiv.org/abs/" + self.arxiv_id
        if self.url:
            return self.url
        if self.openalex_id:
            return "https://openalex.org/" + self.openalex_id
        if self.s2_id:
            return "https://www.semanticscholar.org/paper/" + self.s2_id
        return None

    @property
    def hits(self) -> int:
        """Number of distinct papers that reference or cite this one via snowballing."""
        return len({v.split(":", 1)[1] for v in self.found_via if v.startswith(("backward:", "forward:"))})

    @property
    def found_kinds(self) -> list[str]:
        """Human-readable provenance kinds, e.g. ['seed', 'openalex', 'backward']."""
        kinds = []
        for v in self.found_via:
            head, _, rest = v.partition(":")
            kind = rest.split(":", 1)[0] if head == "search" else head
            if kind not in kinds:
                kinds.append(kind)
        return kinds

    @property
    def included(self) -> bool:
        return self.excluded_reason is None and self.status in ("core", "skim")

    def to_dict(self) -> dict:
        d = {"id": self.id}
        for f in fields(self):
            v = getattr(self, f.name)
            if v is None or v == [] or v == {} or (f.name == "round" and v == 0):
                continue
            d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Paper":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in known}
        extra = dict(kwargs.pop("extra", None) or {})
        extra.update({k: v for k, v in d.items() if k not in known and k not in ("id", "_meta")})
        return cls(**kwargs, extra=extra).normalize()


def read_jsonl(path: str) -> list[Paper]:
    papers = []
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: invalid JSON ({e})") from None
            if "_meta" not in d:
                papers.append(Paper.from_dict(d))
    return papers


def read_meta(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        first = f.readline().strip()
    if first:
        d = json.loads(first)
        if "_meta" in d:
            return d["_meta"]
    return {}


def write_jsonl(path: str, papers, meta: dict | None = None) -> None:
    """Atomic write: never leaves a half-written file behind if interrupted."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="replace", newline="\n") as f:
        if meta is not None:
            f.write(json.dumps({"_meta": meta}, ensure_ascii=False) + "\n")
        for p in papers:
            d = p.to_dict() if isinstance(p, Paper) else p
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    replace_file(tmp, path)
