"""Counts for the status command, log.md and the Method tab (PRISMA-style flow)."""
from __future__ import annotations

import glob
import os
from collections import Counter

from .models import Paper, read_jsonl

KIND_LABELS = {
    "seed": "Seed search",
    "openalex": "Database search: OpenAlex",
    "semantic_scholar": "Database search: Semantic Scholar",
    "arxiv": "Database search: arXiv",
    "backward": "Backward snowballing (references)",
    "forward": "Forward snowballing (citations)",
    "manual": "Added manually",
}


def identified(run) -> Counter:
    """Distinct records returned per provenance kind (seed, openalex, backward, ...), before cross-source
    de-duplication. Re-running a step does not inflate the counts."""
    seen: dict[str, set] = {}
    for path in sorted(glob.glob(os.path.join(glob.escape(run.file("raw")), "*.jsonl"))):
        for p in read_jsonl(path):
            kinds = p.found_kinds
            seen.setdefault(kinds[0] if kinds else "manual", set()).add(p.id)
    return Counter({kind: len(ids) for kind, ids in seen.items()})


def stats(run, papers: list[Paper]) -> dict:
    ident = identified(run)
    total = sum(ident.values())
    live = [p for p in papers if p.excluded_reason is None]
    reasons = Counter(p.excluded_reason for p in papers if p.excluded_reason)
    return {
        "identified": dict(ident),
        "identified_total": total,
        "unique": len(papers),
        "duplicates": max(0, total - len(papers)),
        "filtered_out": sum(reasons.values()),
        "filter_reasons": dict(reasons.most_common()),
        "screened": sum(1 for p in live if p.status),
        "awaiting_screening": sum(1 for p in live if not p.status),
        "excluded_at_screening": sum(1 for p in live if p.status == "exclude"),
        "core": sum(1 for p in live if p.status == "core"),
        "skim": sum(1 for p in live if p.status == "skim"),
        "enriched": sum(1 for p in live if p.included and p.summary),
    }


def flow_rows(s: dict) -> list[tuple[str, object]]:
    """PRISMA-style (stage, count) rows."""
    rows: list[tuple[str, object]] = []
    for kind, label in KIND_LABELS.items():
        if s["identified"].get(kind):
            rows.append((label, s["identified"][kind]))
    for kind, n in s["identified"].items():
        if kind not in KIND_LABELS:
            rows.append((kind, n))
    rows += [
        ("Records identified (total)", s["identified_total"]),
        ("Duplicates removed", s["duplicates"]),
        ("Unique records", s["unique"]),
        ("Excluded by automatic filters", s["filtered_out"]),
    ]
    rows += [(f"    {reason}", n) for reason, n in list(s["filter_reasons"].items())[:8]]
    rows += [
        ("Screened (title & abstract)", s["screened"]),
        ("Excluded at screening", s["excluded_at_screening"]),
        ("Included", s["core"] + s["skim"]),
        ("    core", s["core"]),
        ("    skim", s["skim"]),
    ]
    return rows


def next_step(s: dict, cfg: dict) -> str:
    if not s["unique"]:
        if not (cfg["seed"].get("queries") or cfg["seed"].get("papers")):
            return "Add seed queries to config.yaml (seed.queries), then run: seed"
        return "Run: seed"
    if not s["identified"].get("openalex") and not s["identified"].get("semantic_scholar") \
            and not s["identified"].get("arxiv") and cfg["search"].get("queries"):
        return "Run: search"
    if not (s["identified"].get("backward") or s["identified"].get("forward")):
        return "Run: snowball (then filter)"
    if s["awaiting_screening"]:
        return f"{s['awaiting_screening']} papers await screening: run filter, then batches --stage screen"
    if s["core"] + s["skim"] > s["enriched"]:
        if not cfg.get("taxonomy"):
            return "Define the taxonomy in config.yaml, then: batches --stage enrich"
        return "Run: batches --stage enrich"
    return "Run: export"
