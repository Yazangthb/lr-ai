"""Workbook layout shared by the .xlsx and Google Sheets exporters.

Papers tab: one row per included paper, grouped under category rows ("▌ Category — N papers") and
sub-category rows ("▸ Sub-category (N)"), like a hand-made review sheet. Overview and Method tabs summarize
the review. Colors live here so both exporters look the same.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import __url__, __version__
from .config import taxonomy_names
from .models import Paper
from .report import flow_rows
from .util import today

GROUP_MARK = "▌"
SUBGROUP_MARK = "▸"
READING_CHOICES = ["to read", "reading", "studied"]
PRIORITY_CHOICES = ["high", "medium", "low"]

# name -> (background, text) hex colors
COLORS = {
    "header": ("#263238", "#FFFFFF"),
    "group": ("#3C5A82", "#FFFFFF"),
    "subgroup": ("#DFE8F3", "#1F3B5C"),
    "section": ("#263238", "#FFFFFF"),
    "core": ("#D8EFD3", "#1C5E21"),
    "skim": ("#FFF2CC", "#7A5405"),
    "exclude": ("#F4CCCC", "#990000"),
    "high": ("#F4C7C3", "#A50E0E"),
    "medium": ("#FCE8B2", "#7A5405"),
    "low": ("#E8EAED", "#5F6368"),
    "studied": ("#B7E1CD", None),
    "key": ("#F1F3F4", "#202124"),
}


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    width: int  # pixels
    wrap: bool = False


COLUMNS = [
    Column("title", "Title", 360, True),
    Column("status", "Status", 230, True),
    Column("priority", "Priority", 80),
    Column("reading", "Reading", 95),
    Column("notes", "Notes", 200, True),
    Column("reviewer", "Reviewer", 85),
    Column("year", "Year", 55),
    Column("venue", "Venue", 190, True),
    Column("citations", "Citations", 75),
    Column("code", "Code", 90),
    Column("short_summary", "Short summary", 300, True),
    Column("summary", "Summary", 440),  # clipped to keep rows compact; full text shows when the cell is selected
    Column("rq", "RQ relation", 170, True),
    Column("category", "Category", 170, True),
    Column("subcategory", "Sub-category", 170, True),
    Column("found_via", "Found via", 130, True),
    Column("authors", "Authors", 220),
    Column("link", "Link", 230),
    Column("pdf", "PDF", 200),
    Column("id", "ID", 170),
]

FOUND_LABELS = {"seed": "seed", "openalex": "database", "semantic_scholar": "database", "arxiv": "database",
                "backward": "backward", "forward": "forward", "manual": "manual", "known": "seed"}


@dataclass
class Tab:
    name: str
    widths: list[int]
    rows: list[list] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)  # per row: header|group|subgroup|paper|title|section|kv|blank
    links: dict = field(default_factory=dict)  # (row, col) -> url
    wrap_cols: list[int] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)

    def add(self, kind: str, values: list) -> int:
        self.rows.append(values)
        self.kinds.append(kind)
        return len(self.rows) - 1


def select_columns(keys) -> list[Column]:
    if not keys:
        return list(COLUMNS)
    by_key = {c.key: c for c in COLUMNS}
    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise SystemExit(f"Unknown export column(s): {', '.join(unknown)}. Valid: {', '.join(by_key)}")
    return [by_key[k] for k in keys]


def _authors(p: Paper) -> str:
    names = p.authors or []
    return ", ".join(names[:6]) + (f", … (+{len(names) - 6})" if len(names) > 6 else "")


def _found(p: Paper) -> str:
    return ", ".join(dict.fromkeys(FOUND_LABELS.get(k, k) for k in p.found_kinds)) or "manual"


def paper_values(p: Paper) -> dict:
    status = f"{p.status} - {p.status_reason}" if p.status_reason else (p.status or "")
    return {
        "title": p.title, "status": status, "priority": p.priority or "", "reading": "", "notes": "",
        "reviewer": "", "year": p.year if p.year else "", "venue": p.venue or "",
        "citations": p.citation_count if p.citation_count is not None else "", "code": p.code or "",
        "short_summary": p.short_summary or "", "summary": p.summary or "", "rq": p.rq_relation or "",
        "category": p.first_level or "", "subcategory": p.second_level or "", "found_via": _found(p),
        "authors": _authors(p), "link": p.link or "", "pdf": p.pdf_url or "", "id": p.id,
    }


_STATUS_RANK = {"core": 0, "skim": 1}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _sort_key(p: Paper):
    return (_STATUS_RANK.get(p.status, 2), _PRIORITY_RANK.get(p.priority, 3), -(p.citation_count or 0),
            p.title.lower())


def _grouped(papers: list[Paper], cfg: dict) -> list[tuple[str | None, list[tuple[str | None, list[Paper]]]]]:
    """[(category, [(sub-category, papers)])] in taxonomy order; unknown categories after, largest first."""
    firsts, seconds = taxonomy_names(cfg)
    by_first: dict[str | None, dict[str | None, list[Paper]]] = {}
    for p in papers:
        by_first.setdefault(p.first_level or None, {}).setdefault(p.second_level or None, []).append(p)
    extra = sorted((k for k in by_first if k is not None and k not in firsts),
                   key=lambda k: -sum(len(v) for v in by_first[k].values()))
    order = [k for k in firsts if k in by_first] + extra + ([None] if None in by_first else [])
    out = []
    for first in order:
        subs = by_first[first]
        known = seconds.get(first, []) if first else []
        sub_order = ([None] if None in subs else []) + [s for s in known if s in subs] + \
            sorted((s for s in subs if s is not None and s not in known), key=lambda s: -len(subs[s]))
        out.append((first, [(s, sorted(subs[s], key=_sort_key)) for s in sub_order]))
    return out


def papers_tab(papers: list[Paper], cfg: dict, columns: list[Column]) -> Tab:
    tab = Tab("Papers", [c.width for c in columns], columns=columns,
              wrap_cols=[i for i, c in enumerate(columns) if c.wrap])
    tab.add("header", [c.header for c in columns])
    included = [p for p in papers if p.included]
    categorized = any(p.first_level for p in included)
    blank = [""] * (len(columns) - 1)

    def add_paper(p: Paper) -> None:
        vals = paper_values(p)
        r = tab.add("paper", [vals[c.key] for c in columns])
        for ci, c in enumerate(columns):
            if c.key in ("link", "pdf") and vals[c.key]:
                tab.links[(r, ci)] = vals[c.key]

    if not categorized:
        for p in sorted(included, key=_sort_key):
            add_paper(p)
        return tab
    for first, subs in _grouped(included, cfg):
        n = sum(len(ps) for _, ps in subs)
        tab.add("group", [f"{GROUP_MARK} {first or 'Uncategorized'} — {n} paper{'s' if n != 1 else ''}"] + blank)
        for second, ps in subs:
            if second:
                tab.add("subgroup", [f"{SUBGROUP_MARK} {second} ({len(ps)})"] + blank)
            for p in ps:
                add_paper(p)
    return tab


def overview_tab(papers: list[Paper], cfg: dict) -> Tab:
    tab = Tab("Overview", [260, 220, 70, 70, 70])
    included = [p for p in papers if p.included]
    core = sum(1 for p in included if p.status == "core")
    tab.add("title", ["Overview", "", "", "", ""])
    tab.add("kv", ["Topic", cfg.get("topic") or "", "", "", ""])
    tab.add("kv", ["Included papers", len(included), "", "", ""])
    tab.add("kv", ["Core / skim", f"{core} / {len(included) - core}", "", "", ""])
    tab.add("kv", ["Generated", today(), "", "", ""])
    tab.add("blank", [""] * 5)
    tab.add("section", ["Category", "Sub-category", "Core", "Skim", "Total"])
    for first, subs in _grouped(included, cfg):
        for second, ps in subs:
            c = sum(1 for p in ps if p.status == "core")
            tab.add("data", [first or "Uncategorized", second or "", c, len(ps) - c, len(ps)])
    tab.add("blank", [""] * 5)
    tab.add("section", ["Year", "Papers", "", "", ""])
    years = Counter(p.year for p in included if p.year)
    for year in sorted(years, reverse=True):
        tab.add("data", [year, years[year], "", "", ""])
    tab.add("blank", [""] * 5)
    tab.add("section", ["Venue (top 15)", "Papers", "", "", ""])
    for venue, n in Counter(p.venue for p in included if p.venue).most_common(15):
        tab.add("data", [venue, n, "", "", ""])
    return tab


def _lines(items) -> str:
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(f"{it.get('id', '')}: {it.get('text', '')}".strip(": "))
        else:
            out.append(str(it))
    return "\n".join(out)


def _filters_text(f: dict) -> str:
    parts = []
    if f.get("year_min") or f.get("year_max"):
        parts.append(f"years {f.get('year_min') or '…'}–{f.get('year_max') or '…'}")
    if f.get("languages"):
        parts.append("language: " + ", ".join(f["languages"]))
    if f.get("min_citations"):
        parts.append(f"≥ {f['min_citations']} citations (papers < {f.get('citation_grace_years', 0)} years old exempt)")
    if f.get("require_abstract"):
        parts.append("abstract required")
    if f.get("require_any"):
        parts.append("must mention: " + ", ".join(map(str, f["require_any"])))
    if f.get("exclude_any"):
        parts.append("must not mention: " + ", ".join(map(str, f["exclude_any"])))
    if f.get("exclude_types"):
        parts.append("excluded types: " + ", ".join(f["exclude_types"]))
    if f.get("min_hits"):
        parts.append(f"snowballed papers linked from ≥ {f['min_hits']} papers")
    return "\n".join(parts)


def method_tab(cfg: dict, stats: dict) -> Tab:
    tab = Tab("Method", [260, 640])
    s, sb = cfg["seed"], cfg["snowball"]
    tab.add("title", ["Method", ""])
    rows = [
        ("Topic", cfg.get("topic") or ""),
        ("Research questions", _lines(cfg.get("research_questions"))),
        ("Inclusion criteria", _lines(cfg.get("inclusion_criteria"))),
        ("Exclusion criteria", _lines(cfg.get("exclusion_criteria"))),
        ("Seed queries", _lines(s.get("queries"))),
        ("Known seed papers", _lines(s.get("papers"))),
        ("Database queries", _lines(cfg["search"].get("queries"))),
        ("Databases", ", ".join(cfg["search"].get("sources") or [])),
        ("Snowballing", f"{sb.get('rounds', 1)} round(s), {sb.get('direction')}; up to "
                        f"{sb.get('max_references') or 'all'} references and {sb.get('max_citations')} citing "
                        f"papers per paper (most cited first)"),
        ("Automatic filters", _filters_text(cfg["filters"])),
        ("Screening", "Title/abstract screening by an LLM against the criteria above; "
                      "core = directly relevant, skim = partially relevant."),
    ]
    for k, v in rows:
        if v:
            tab.add("kv", [k, v])
    tab.add("blank", ["", ""])
    tab.add("section", ["Stage", "Records"])
    for label, n in flow_rows(stats):
        tab.add("data", [label, n])
    tab.add("blank", ["", ""])
    tab.add("kv", ["Generated with", f"LR-AI {__version__} · {__url__} · {today()}"])
    return tab


def build(papers: list[Paper], cfg: dict, stats: dict) -> list[Tab]:
    columns = select_columns((cfg.get("export") or {}).get("columns"))
    return [papers_tab(papers, cfg, columns), overview_tab(papers, cfg), method_tab(cfg, stats)]
