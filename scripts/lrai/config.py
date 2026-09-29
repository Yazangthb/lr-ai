"""Run configuration (config.yaml): template, defaults, loading."""
from __future__ import annotations

import copy
import json

try:
    import yaml
except ImportError:  # pragma: no cover - reported by `lr.py doctor`
    yaml = None

DEFAULTS: dict = {
    "topic": "",
    "research_questions": [],
    "inclusion_criteria": [],
    "exclusion_criteria": [],
    "seed": {"queries": [], "per_query": 20, "papers": []},
    "search": {"sources": ["openalex", "semantic_scholar", "arxiv"], "queries": [], "per_query": 100},
    "snowball": {
        "rounds": 1, "direction": "both", "backend": "auto", "from": "all",
        "max_references": 200, "max_citations": 50,
    },
    "filters": {
        "year_min": None, "year_max": None, "languages": ["en"], "min_citations": 0,
        "citation_grace_years": 2, "require_abstract": False,
        "exclude_types": ["erratum", "editorial", "retraction", "paratext", "letter", "peer-review",
                          "supplementary-materials"],
        "require_any": [], "exclude_any": [], "venue_exclude": [], "min_hits": 0,
    },
    "screening": {"batch_size": 25},
    "taxonomy": [],
    "export": {"title": None, "columns": None},
}

TEMPLATE = """\
# LR-AI review configuration. Every `lr.py` command reads this file; edit it freely.
# Boolean query syntax (search.queries): ("phrase one" OR "phrase two") AND (term* OR other) NOT excluded

topic: {topic}
created: "{date}"

research_questions: []
#  - id: RQ1
#    text: "How ...?"

inclusion_criteria: []
#  - "Proposes or evaluates a method for ..."
exclusion_criteria: []
#  - "Opinion pieces, editorials, or papers not written in English"

seed:
  queries: []          # natural-language queries (Semantic Scholar, falling back to OpenAlex / arXiv)
  per_query: 20
  papers: []           # papers you already know: DOIs, arXiv ids, or exact titles

search:
  sources: [openalex, semantic_scholar, arxiv]
  queries: []          # boolean keyword queries, translated for each database
  per_query: 100       # results kept per query per source (most relevant first)

snowball:
  rounds: 1
  direction: both      # backward | forward | both
  backend: auto        # auto (OpenAlex, falls back to Semantic Scholar) | openalex | semantic_scholar
  from: all            # all = every start-set paper; included = only papers screened core/skim
  max_references: 200  # per paper, most-cited first (null = all)
  max_citations: 50    # per paper, most-cited first

filters:
  year_min: null
  year_max: null
  languages: [en]      # papers with unknown language are kept
  min_citations: 0
  citation_grace_years: 2   # papers younger than this are exempt from min_citations
  require_abstract: false
  exclude_types: [erratum, editorial, retraction, paratext, letter, peer-review, supplementary-materials]
  require_any: []      # keep only papers whose title/abstract mentions one of these (supports prefix*)
  exclude_any: []      # drop papers whose title/abstract mentions any of these
  venue_exclude: []
  min_hits: 0          # snowballed papers must be linked from at least this many papers

screening:
  batch_size: 25       # papers per screening subagent

taxonomy: []           # two-level categories, filled in after screening
#  - name: "Graph-based forecasting"
#    rq: RQ1
#    children: ["Citation analysis", "Link prediction"]

export:
  title: null          # Google Sheet title (default: "LR — <topic>")
  columns: null        # null = all columns, or a list of column keys to keep
"""


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif v is None and isinstance(out.get(k), (list, dict)):
            continue  # `key:` left empty in YAML -> keep the default list/section
        else:
            out[k] = v
    return out


def render_template(topic: str, date: str) -> str:
    return TEMPLATE.format(topic=json.dumps(topic, ensure_ascii=False), date=date)


def load(path: str) -> dict:
    if yaml is None:
        raise SystemExit("PyYAML is missing: run `pip install -r requirements.txt` (see `lr.py doctor`).")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a YAML mapping at the top level")
    return _merge(DEFAULTS, data)


def taxonomy_names(cfg: dict) -> tuple[list[str], dict[str, list[str]]]:
    """-> (first-level names in order, {first-level: [second-level names]})."""
    firsts, seconds = [], {}
    for node in cfg.get("taxonomy") or []:
        if isinstance(node, str):
            name, children = node, []
        else:
            name, children = str(node.get("name", "")).strip(), node.get("children") or []
        if name:
            firsts.append(name)
            seconds[name] = [str(c).strip() for c in children if str(c).strip()]
    return firsts, seconds
