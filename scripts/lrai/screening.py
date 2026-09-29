"""Batch files for LLM screening/enrichment subagents, and merging their results back.

Each batch file is self-describing: the first line is {"_meta": {...}} with the review criteria, the
taxonomy (for enrichment) and the path where the subagent must write its results. Result files are JSONL,
one object per paper, keyed by "id".

stage "screen": title/abstract screening -> status (core|skim|exclude), reason, relevance, short_summary
stage "enrich": included papers -> summary, rq_relation, first_level, second_level, priority, code
"""
from __future__ import annotations

import glob
import json
import os
import re

from .config import taxonomy_names
from .models import PRIORITIES, Paper, write_jsonl
from .util import replace_file, shorten

STAGES = ("screen", "enrich")
_STATUS_SYNONYMS = {"include": "core", "included": "core", "maybe": "skim", "uncertain": "skim",
                    "excluded": "exclude", "reject": "exclude", "rejected": "exclude"}


def pending(papers: list[Paper], stage: str, force: bool = False) -> list[Paper]:
    if stage == "screen":
        return [p for p in papers if p.excluded_reason is None and (force or p.status is None)]
    return [p for p in papers if p.included and (force or not p.summary)]


def _compact(p: Paper, stage: str) -> dict:
    d = {
        "id": p.id, "title": p.title, "year": p.year, "venue": p.venue, "citations": p.citation_count,
        "abstract": shorten(p.abstract, 2500) if p.abstract else None,
    }
    if stage == "enrich":
        d.update(status=p.status, reason=p.status_reason, short_summary=p.short_summary, link=p.link,
                 pdf=p.pdf_url)
    return {k: v for k, v in d.items() if v not in (None, "")}


def _batch_files(folder: str) -> list[str]:
    return sorted(f for f in glob.glob(os.path.join(folder, "batch_*.jsonl")) if not f.endswith(".result.jsonl"))


def write_batches(run, stage: str, papers: list[Paper], size: int) -> list[str]:
    folder = run.file(stage)
    os.makedirs(folder, exist_ok=True)
    numbers = [int(m.group(1)) for f in _batch_files(folder) if (m := re.search(r"batch_(\d+)\.jsonl$", f))]
    start = max(numbers, default=0) + 1
    cfg = run.config
    base_meta = {
        "stage": stage,
        "topic": cfg.get("topic"),
        "research_questions": cfg.get("research_questions") or [],
        "inclusion_criteria": cfg.get("inclusion_criteria") or [],
        "exclusion_criteria": cfg.get("exclusion_criteria") or [],
    }
    if stage == "enrich":
        base_meta["taxonomy"] = cfg.get("taxonomy") or []
    paths = []
    for k, i in enumerate(range(0, len(papers), size)):
        name = f"batch_{start + k:03d}"
        path = os.path.join(folder, name + ".jsonl")
        meta = {**base_meta, "batch": name, "output": os.path.join(folder, name + ".result.jsonl"),
                "count": len(papers[i : i + size])}
        write_jsonl(path, [_compact(p, stage) for p in papers[i : i + size]], meta=meta)
        paths.append(path)
    return paths


def _num(v) -> float | None:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None


def _apply_one(p: Paper, r: dict, stage: str, firsts: list[str], problems: list[str]) -> bool:
    """Apply one result row; returns False if it was unusable (the paper then stays pending).
    Fields the user set by hand (`lr.py set`, recorded in extra["manual"]) are never overwritten."""
    manual = set(p.extra.get("manual") or [])

    def put(name: str, value) -> None:
        if name not in manual and not (name == "status_reason" and "status" in manual):
            setattr(p, name, value)

    if stage == "screen":
        status = str(r.get("status", "")).strip().lower()
        status = _STATUS_SYNONYMS.get(status, status)
        if status not in ("core", "skim", "exclude"):
            problems.append(f"{p.id}: invalid status {r.get('status')!r}")
            return False
        put("status", status)
        put("status_reason", (r.get("reason") or "").strip() or None)
        put("relevance", _num(r.get("relevance")))
        put("short_summary", (r.get("short_summary") or "").strip() or p.short_summary)
        return True
    if not r.get("summary"):
        problems.append(f"{p.id}: result has no summary")
        return False
    for name in ("summary", "rq_relation", "first_level", "second_level", "code", "short_summary"):
        if r.get(name) not in (None, ""):
            put(name, str(r[name]).strip())
    prio = str(r.get("priority", "")).strip().lower()
    if prio:
        if prio in PRIORITIES:
            put("priority", prio)
        else:
            problems.append(f"{p.id}: invalid priority {r.get('priority')!r}")
    if firsts and p.first_level and p.first_level not in firsts:
        problems.append(f"{p.id}: category {p.first_level!r} is not in the taxonomy")
    return True


def _state_path(run, stage: str) -> str:
    return os.path.join(run.file(stage), "applied.json")


def apply_results(run, stage: str, papers: list[Paper], replay_all: bool = False) -> dict:
    """Merge new or changed *.result.jsonl files of a stage into `papers` (later batches win).

    Result files already applied are skipped (tracked in <stage>/applied.json by size and mtime), so an
    old result never overwrites a later decision; `replay_all` re-applies everything. Call save_state()
    with report["state"] after the papers are saved.
    """
    folder = run.file(stage)
    by_id = {p.id: p for p in papers}
    # results may name a paper by an id it had before a later merge (e.g. arxiv:… -> doi:…)
    for p in papers:
        for key in p.dedup_keys():
            if not key.startswith("title:"):
                by_id.setdefault(key, p)
    firsts, _ = taxonomy_names(run.config)
    state: dict = {}
    if not replay_all and os.path.exists(_state_path(run, stage)):
        with open(_state_path(run, stage), encoding="utf-8") as f:
            state = json.load(f)
    report = {"applied": 0, "files": 0, "unknown_ids": [], "problems": [], "missing": {}, "bad_lines": [],
              "state": dict(state)}
    for batch in _batch_files(folder):
        result_path = batch[: -len(".jsonl")] + ".result.jsonl"
        with open(batch, encoding="utf-8") as f:
            wanted = [json.loads(line)["id"] for line in f if line.strip() and '"_meta"' not in line[:12]]
        got = set()
        name = os.path.basename(result_path)
        if os.path.exists(result_path):
            st = os.stat(result_path)
            signature = [st.st_size, st.st_mtime_ns]
            if state.get(name) != signature:
                report["files"] += 1
                report["state"][name] = signature
                with open(result_path, encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        line = line.strip().rstrip(",")
                        if not line or line in ("[", "]"):
                            continue
                        try:
                            r = json.loads(line)
                        except json.JSONDecodeError:
                            report["bad_lines"].append(f"{name}:{n}")
                            continue
                        pid = r.get("id") if isinstance(r, dict) else None
                        p = by_id.get(pid)
                        if p is None:
                            report["unknown_ids"].append(pid)
                            continue
                        if _apply_one(p, r, stage, firsts, report["problems"]):
                            got.add(p.id)
                            report["applied"] += 1
        missing = [i for i in wanted if i in by_id and by_id[i].id not in got and _still_pending(by_id[i], stage)]
        if missing:
            report["missing"][os.path.basename(batch)] = missing
    return report


def save_state(run, stage: str, state: dict) -> None:
    path = _state_path(run, stage)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    replace_file(tmp, path)


def _still_pending(p: Paper, stage: str) -> bool:
    return p.status is None if stage == "screen" else (p.included and not p.summary)
