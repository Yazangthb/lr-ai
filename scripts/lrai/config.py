"""Run configuration (config.yaml): template, defaults, loading."""
from __future__ import annotations

import copy
import json
import re

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
        "require_any": [], "exclude_any": [], "venue_exclude": [], "min_hits": 0, "snowball_require_any": [],
        "block": [],
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
  papers: []           # papers you already know, in quotes: "10.1126/science.1237825", "2401.01234", or exact titles

search:
  sources: [openalex, semantic_scholar, arxiv]
  queries: []          # boolean keyword queries, translated for each database
  per_query: 100       # results kept per query per source (most relevant first)

snowball:
  rounds: 1
  direction: both      # backward | forward | both
  backend: auto        # auto (OpenAlex, falls back to Semantic Scholar) | openalex | semantic_scholar
  from: all            # all = every start-set paper; included = papers screened core/skim; core = core only
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
  snowball_require_any: []  # like require_any, but only for papers found by snowballing alone
  block: []            # papers that must never enter the review (DOI, arXiv id, OpenAlex id or exact title);
                       # e.g. the published review you are reproducing, so its reference list is not used

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
        elif isinstance(out.get(k), list) and isinstance(v, (str, int, float)) and not isinstance(v, bool):
            out[k] = [v]  # `languages: en` means [en], not ['e', 'n']
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


# Settings profiles: `standard` keeps result lists manageable; `wide` trades screening effort for recall (no
# citation-count threshold for snowballed papers, all references, more citing papers and search results).
# Topic-specific filters (years, keywords, block list) are never touched by a profile.
PROFILES: dict[str, dict[str, dict]] = {
    "standard": {
        "seed": {"per_query": 20},
        "search": {"per_query": 100},
        "snowball": {"from": "all", "max_references": 200, "max_citations": 50},
        "filters": {"min_hits": 0},
    },
    "wide": {
        "seed": {"per_query": 30},
        "search": {"per_query": 3000},  # in effect: all matches for most topic queries
        "snowball": {"from": "included", "max_references": None, "max_citations": 200},
        "filters": {"min_hits": 1},
    },
}


def _yaml_scalar(value) -> str:
    return "null" if value is None else (json.dumps(value) if isinstance(value, str) else str(value))


def set_values(text: str, section: str, values: dict) -> str:
    """Set `section.key: value` lines in config.yaml text, keeping comments and layout (keys missing from the
    section are appended to it; a missing section is appended at the end)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", ln)), None)
    if start is None:
        return text.rstrip("\n") + f"\n\n{section}:\n" + "".join(
            f"  {k}: {_yaml_scalar(v)}\n" for k, v in values.items())
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()
                and not lines[i].lstrip().startswith("#")), len(lines))
    for key, value in values.items():
        rx = re.compile(rf"^(\s+){re.escape(key)}:(\s*)([^#]*?)(\s*#.*)?$")
        for i in range(start + 1, end):
            m = rx.match(lines[i])
            if m and len(m.group(1)) == 2:
                lines[i] = f"{m.group(1)}{key}: {_yaml_scalar(value)}{m.group(4) or ''}"
                break
        else:
            lines.insert(end, f"  {key}: {_yaml_scalar(value)}")
            end += 1
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def apply_profile(text: str, name: str) -> str:
    if name not in PROFILES:
        raise SystemExit(f"Unknown profile {name!r}. Choose from: {', '.join(PROFILES)}")
    for section, values in PROFILES[name].items():
        text = set_values(text, section, values)
    return re.sub(r"^profile:.*$", f"profile: {name}", text, flags=re.M) if re.search(r"^profile:", text, re.M) \
        else text.replace("\n", f"\nprofile: {name}            # settings preset (lr.py profile); edit values freely\n", 1)
