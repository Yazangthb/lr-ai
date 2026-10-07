"""`lr.py` commands. Progress goes to stderr; stdout carries a short summary meant to be read by Claude or a human."""
from __future__ import annotations

import argparse
import glob
import os
import sys

from . import __version__, filters, report, screening
from .complete import complete_metadata
from .config import render_template, taxonomy_names
from .dedup import dedup, merge_into
from .http import HttpError
from .models import PRIORITIES, STATUSES, Paper
from .query import keywords
from .resolve import resolve
from .run import Run
from .snowball import snowball_round
from .sources import arxiv, openalex
from .sources import semantic_scholar as s2
from .util import info, shorten, slugify, today

SEARCHERS = {"openalex": openalex.search, "semantic_scholar": s2.search, "arxiv": arxiv.search}
OPENALEX_KEY_HINT = ("OpenAlex refused an anonymous request. Get a free API key at https://openalex.org/ and "
                     "set OPENALEX_API_KEY (lookups/snowballing still work without one; search may not).")
GOOGLE_ACCOUNT_VAR = "LR_AI_GOOGLE_ACCOUNT"


# ---------------------------------------------------------------- helpers

def google_account(explicit: str | None = None) -> str | None:
    """Composio Google account for the sheet: --account, else $LR_AI_GOOGLE_ACCOUNT, else None (the only one)."""
    return (explicit or os.environ.get(GOOGLE_ACCOUNT_VAR) or "").strip() or None

def _latest_run(root: str = "lr-runs") -> str | None:
    runs = [d for d in glob.glob(os.path.join(glob.escape(root), "*")) if os.path.isfile(os.path.join(d, "config.yaml"))]
    return max(runs, key=os.path.getmtime) if runs else None


def _run(args) -> Run:
    path = args.run or _latest_run()
    if not path:
        raise SystemExit("No run found. Create one with: lr.py init \"<topic>\" (or pass --run DIR)")
    return Run(path, use_cache=not getattr(args, "no_cache", False))


def _seq(run: Run, prefix: str) -> int:
    return len(glob.glob(os.path.join(glob.escape(run.file("raw")), prefix + "*.jsonl"))) + 1


def _field(p: Paper, name: str):
    """Paper attribute by name, plus a few display aliases (citations, found, reason)."""
    if name == "citations":
        return p.citation_count
    if name == "found":
        return ",".join(p.found_kinds)
    if name == "reason":
        return p.excluded_reason or p.status_reason
    return getattr(p, name, None)


def _table(papers: list[Paper], fields: list[str], limit: int) -> str:
    lines = []
    for p in papers[:limit]:
        row = []
        for f in fields:
            v = _field(p, f)
            if isinstance(v, list):
                v = ", ".join(map(str, v[:3])) + ("…" if len(v) > 3 else "")
            row.append(shorten("" if v is None else str(v), 110 if f in ("title", "short_summary") else 300))
        lines.append("\t".join(row))
    if len(papers) > limit:
        lines.append(f"… {len(papers) - limit} more")
    return "\n".join(lines)


def _year_bounds(run: Run) -> tuple[int | None, int | None]:
    f = run.config["filters"]
    return f.get("year_min"), f.get("year_max")


def _finish(run: Run, papers: list[Paper], new: list[Paper], stage: str, summary: str, **data) -> None:
    if new:
        data["metadata_completed"] = complete_metadata(papers)
    run.save(papers)
    run.log(stage, summary, **data)


# ---------------------------------------------------------------- commands

def cmd_init(args) -> None:
    root = os.path.abspath(args.root)
    base = os.path.join(root, f"{slugify(args.name or args.topic)}-{today()}")
    path, k = base, 2
    while os.path.exists(path):
        path, k = f"{base}-{k}", k + 1
    os.makedirs(path)
    with open(os.path.join(path, "config.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(render_template(args.topic, today()))
    with open(os.path.join(path, "log.md"), "w", encoding="utf-8") as f:
        f.write(f"# Review log: {args.topic}\n\n")
    print(f"Created run: {path}\nNext: fill in config.yaml (research questions, criteria, seed queries), then run `seed`.")


def cmd_doctor(args) -> None:
    ok = True
    print(f"LR-AI {__version__} · Python {sys.version.split()[0]}")
    if sys.version_info < (3, 9):
        print("  ✗ Python 3.9+ required")
        ok = False
    for mod in ("yaml", "openpyxl"):
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ✗ {mod} missing — pip install -r requirements.txt")
            ok = False
    checks = {
        "Semantic Scholar": lambda: s2.search("literature review automation", limit=1),
        "OpenAlex (lookup)": lambda: openalex.get_work("W2741809807", select="id"),
        "OpenAlex (search)": lambda: openalex.search("systematic review", limit=1),
        "arXiv": lambda: arxiv.search("systematic review", limit=1),
    }
    degraded = False
    for name, fn in checks.items():
        try:
            fn()
            print(f"  ✓ {name} reachable")
        except Exception as e:  # noqa: BLE001 - diagnostics only
            print(f"  ⚠ {name}: {shorten(str(e), 160)}")
            degraded = True  # not fatal: every step falls back to another source
    for var, why in (("S2_API_KEY", "higher Semantic Scholar rate limit"),
                     ("OPENALEX_API_KEY", "reliable OpenAlex search and a larger daily budget"),
                     ("OPENALEX_EMAIL", "OpenAlex polite pool")):
        print(f"  {'✓' if os.environ.get(var) else '·'} {var} {'set' if os.environ.get(var) else 'not set'} ({why})")
    account = google_account()
    print(f"  {'✓' if account else '·'} {GOOGLE_ACCOUNT_VAR} {'= ' + account if account else 'not set'} "
          "(Google account for the sheet when several are connected in Composio)")
    if not ok:
        print("Not ready: install the missing Python packages.")
    elif degraded:
        print("Ready. Some services are unavailable or rate-limited right now; LR-AI will fall back to the others "
              "(API keys above make this rarer).")
    else:
        print("Ready.")


def cmd_seed(args) -> None:
    run = _run(args)
    cfg = run.config["seed"]
    adhoc = bool(args.query)  # --query runs only the given queries (handy for testing this step alone)
    queries = args.query if adhoc else cfg.get("queries") or []
    known = [] if adhoc else cfg.get("papers") or []
    tag = "x" if adhoc else "q"
    if not queries and not known:
        raise SystemExit("config.yaml has no seed.queries or seed.papers (or pass --query).")
    y0, y1 = _year_bounds(run)
    per_query = args.limit or int(cfg.get("per_query") or 20)
    found, totals, errors = [], {}, []
    for i, q in enumerate(queries, 1):
        res, failures = [], []
        for name, search in SEED_SOURCES:
            try:
                res, total = search(q, limit=per_query, year_min=y0, year_max=y1)
            except HttpError as e:
                failures.append(f"{name}: {shorten(str(e), 150)}")
                info(f"  {tag}{i}: {name} failed, trying the next source")
                continue
            if res:
                totals[f"{tag}{i}:{name}"] = total
                info(f"  {tag}{i}: {len(res)} papers from {name} (of {total} matches) — {q}")
                break
        if not res:
            errors.append(f"{tag}{i} returned nothing" + (" (" + "; ".join(failures) + ")" if failures else ""))
        for p in res:
            p.found_via = [f"seed:{tag}{i}"]
        found.extend(res)
    if known:
        resolved, errs = resolve(known, "seed:known")
        found.extend(resolved)
        errors.extend(errs)
    run.save_raw(f"seed-{_seq(run, 'seed-'):02d}", found)
    papers, added = merge_into(run.load(), found)
    _finish(run, papers, found, "seed", f"{len(queries)} queries + {len(known)} known papers → {len(found)} "
            f"records, {added} new (total {len(papers)})", records=len(found), added=added, totals=totals,
            errors=errors, queries=queries, adhoc=adhoc)
    print(f"Seed search: {len(found)} records, {added} new, {len(papers)} unique papers in the run.")
    for e in errors:
        print(f"  error: {e}")
    seeds = [p for p in papers if any(v.startswith("seed:") for v in p.found_via)]
    print(_table(seeds, ["year", "citations", "title"], args.show))


def _arxiv_keywords(query: str, **kw):
    return arxiv.search(keywords(query), **kw)


# Seed search: relevance-ranked engines, first one that answers wins.
SEED_SOURCES = (("semantic_scholar", s2.search), ("openalex", openalex.search_relevance), ("arxiv", _arxiv_keywords))


def cmd_search(args) -> None:
    run = _run(args)
    cfg = run.config["search"]
    adhoc = bool(args.query)
    queries = args.query if adhoc else cfg.get("queries") or []
    tag = "x" if adhoc else "q"
    if not queries:
        raise SystemExit("config.yaml has no search.queries (or pass --query).")
    sources = args.sources.split(",") if args.sources else cfg.get("sources") or []
    unknown = [s for s in sources if s not in SEARCHERS]
    if unknown:
        raise SystemExit(f"Unknown source(s): {', '.join(unknown)}. Choose from: {', '.join(SEARCHERS)}")
    y0, y1 = _year_bounds(run)
    per_query = args.limit or int(cfg.get("per_query") or 100)
    by_source: dict[str, list[Paper]] = {s: [] for s in sources}
    totals, errors = {}, []
    for qi, q in enumerate(queries, 1):
        for src in sources:
            try:
                res, total = SEARCHERS[src](q, limit=per_query, year_min=y0, year_max=y1)
            except HttpError as e:
                msg = OPENALEX_KEY_HINT if src == "openalex" and "api key" in str(e).lower() else str(e)
                errors.append(f"{src} {tag}{qi}: {msg}")
                info(f"  {src} {tag}{qi} failed: {shorten(msg, 200)}")
                continue
            for p in res:
                p.found_via = [f"search:{src}:{tag}{qi}"]
            by_source[src].extend(res)
            totals[f"{src}:{tag}{qi}"] = total
            info(f"  {src} {tag}{qi}: kept {len(res)} of {total if total is not None else '?'} matches")
    seq = _seq(run, "search-")
    found = []
    for src, res in by_source.items():
        if res:
            run.save_raw(f"search-{seq:02d}-{src}", res)
            found.extend(res)
    papers, added = merge_into(run.load(), found)
    _finish(run, papers, found, "search", f"{len(queries)} queries × {len(sources)} sources → {len(found)} records, "
            f"{added} new (total {len(papers)})", records=len(found), added=added, totals=totals, errors=errors,
            queries=queries, sources=sources, adhoc=adhoc)
    print(f"Database search: {len(found)} records, {added} new, {len(papers)} unique papers in the run.")
    for k, v in totals.items():
        print(f"  {k}: {v if v is not None else '?'} matches in the database")
    for e in errors:
        print(f"  error: {e}")


def cmd_snowball(args) -> None:
    run = _run(args)
    cfg = run.config["snowball"]
    papers = run.load()
    if not papers:
        raise SystemExit("No papers yet. Run seed/search first.")
    rounds_done = max((p.round for p in papers), default=0)
    round_no = args.round or rounds_done + 1
    source = args.source or cfg.get("from") or "all"

    blocked = filters.block_keys(run.config["filters"].get("block"))

    def eligible(p: Paper) -> bool:
        if p.round != round_no - 1 or p.excluded_reason or blocked.intersection(p.dedup_keys()):
            return False
        return p.included if source == "included" else p.status != "exclude"

    frontier = [p for p in papers if eligible(p)]
    if not frontier:
        raise SystemExit(f"No papers to snowball from for round {round_no} (from: {source}).")
    if len(frontier) > args.max_frontier and not args.force:
        raise SystemExit(f"{len(frontier)} papers in the frontier (> {args.max_frontier}). Screen first "
                         f"(snowball.from: included), tighten filters, or re-run with --force.")
    direction = args.direction or cfg.get("direction") or "both"
    backend = args.backend or cfg.get("backend") or "auto"
    max_refs = cfg.get("max_references") if args.max_references is None else args.max_references
    max_cites = cfg.get("max_citations") if args.max_citations is None else args.max_citations
    info(f"Snowballing round {round_no}: {len(frontier)} papers, {direction}, backend {backend}")
    found, stats = snowball_round(frontier, round_no, direction, backend, max_refs, max_cites)
    run.save_raw(f"snowball-r{round_no}-{_seq(run, f'snowball-r{round_no}-'):02d}", found)
    papers, added = merge_into(papers, found)
    _finish(run, papers, found, "snowball", f"round {round_no} from {len(frontier)} papers → {len(found)} records "
            f"({stats['references']} refs, {stats['citations']} citing), {added} new (total {len(papers)})",
            records=len(found), added=added, round=round_no, stats=stats)
    print(f"Snowball round {round_no}: {stats['references']} references + {stats['citations']} citing papers "
          f"→ {added} new unique papers (run total {len(papers)}).")
    print(f"  backends: {stats['backend']}; not in any database: {len(stats['unresolved'])}")
    if stats["failed"]:
        print(f"  {len(stats['failed'])} papers hit API errors and may be incomplete. Re-run "
              f"`snowball --round {round_no}` later to retry them (completed calls are cached, so it is cheap).")
    for e in stats["errors"][:3]:
        print(f"  error: {shorten(e, 200)}")
    if any("api key" in e.lower() for e in stats["errors"]):
        print("  " + OPENALEX_KEY_HINT)


def cmd_complete(args) -> None:
    run = _run(args)
    papers = run.load()
    filled = complete_metadata(papers, force=args.all)
    run.save(papers)
    run.log("complete", f"metadata completed for {filled} papers")
    print(f"Filled missing metadata for {filled} papers.")


def cmd_filter(args) -> None:
    run = _run(args)
    before = run.load()
    papers = dedup(before)  # cheap and idempotent; catches duplicates left by older runs
    counts = filters.apply(papers, run.config["filters"])
    kept = sum(1 for p in papers if not p.excluded_reason)
    run.save(papers)
    run.log("filter", f"{kept} of {len(papers)} papers pass the filters", excluded=counts,
            merged_duplicates=len(before) - len(papers))
    if len(before) > len(papers):
        print(f"Merged {len(before) - len(papers)} duplicate records.")
    print(f"Filters: {kept} of {len(papers)} papers pass.")
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  excluded {n}: {reason}")
    todo = len(screening.pending(papers, "screen"))
    print(f"{todo} papers await screening.")


def cmd_batches(args) -> None:
    run = _run(args)
    papers = run.load()
    todo = screening.pending(papers, args.stage, args.force)
    if args.stage == "enrich" and not taxonomy_names(run.config)[0]:
        print("Warning: config.yaml has no taxonomy; categories will be free-form.")
    if not todo:
        print(f"Nothing to {args.stage}.")
        return
    size = args.size or int(run.config["screening"].get("batch_size") or 25)
    paths = screening.write_batches(run, args.stage, todo, size)
    run.log("batches", f"{len(todo)} papers → {len(paths)} {args.stage} batches")
    print(f"{len(todo)} papers → {len(paths)} {args.stage} batch files (each names its result file in _meta.output):")
    for p in paths:
        print("  " + p)


def cmd_apply(args) -> None:
    run = _run(args)
    papers = run.load()
    rep = screening.apply_results(run, args.stage, papers, replay_all=args.all)
    run.save(papers)
    screening.save_state(run, args.stage, rep["state"])
    live = [p for p in papers if not p.excluded_reason]
    if args.stage == "screen":
        counts = {s: sum(1 for p in live if p.status == s) for s in ("core", "skim", "exclude")}
        summary = f"screening applied: {counts['core']} core, {counts['skim']} skim, {counts['exclude']} excluded"
    else:
        done = sum(1 for p in live if p.included and p.summary)
        summary = f"enrichment applied: {done} of {sum(1 for p in live if p.included)} included papers summarized"
    run.log(f"apply {args.stage}", summary, applied=rep["applied"], missing=rep["missing"],
            problems=rep["problems"][:50])
    print(summary + f" ({rep['applied']} new results from {rep['files']} new or changed result files).")
    if rep["missing"]:
        print("Batches with missing results (re-run these):")
        for batch, ids in rep["missing"].items():
            print(f"  {batch}: {len(ids)} papers")
    for label in ("unknown_ids", "problems", "bad_lines"):
        if rep[label]:
            print(f"{label}: " + "; ".join(map(str, rep[label][:10])) + (" …" if len(rep[label]) > 10 else ""))


def cmd_show(args) -> None:
    run = _run(args)
    papers = run.load()
    for cond in args.where or []:
        key, _, val = cond.partition("=")
        papers = [p for p in papers if _matches(p, key.strip(), val.strip())]
    if args.sort:
        def sort_key(p: Paper):
            v = _field(p, args.sort)
            return (v is None, -v if isinstance(v, (int, float)) else 0)
        papers.sort(key=sort_key)  # descending, unknown values last
    fields = args.fields.split(",") if args.fields else ["id", "year", "citations", "title"]
    print(f"{len(papers)} papers\n" + "\t".join(fields))
    print(_table(papers, fields, args.limit))


def _matches(p: Paper, key: str, val: str) -> bool:
    if key == "included":
        return p.included == (val.lower() in ("1", "true", "yes"))
    if key == "excluded":
        return bool(p.excluded_reason) == (val.lower() in ("1", "true", "yes"))
    if key == "found":
        return val in p.found_kinds
    if key == "round":
        return str(p.round) == val
    v = getattr(p, key, None)
    if val.lower() in ("none", "null", ""):
        return v in (None, "")
    return str(v).lower() == val.lower()


def cmd_add(args) -> None:
    run = _run(args)
    found, errors = resolve(args.items, "manual")
    run.save_raw(f"manual-{_seq(run, 'manual-'):02d}", found)
    papers, added = merge_into(run.load(), found)
    run.save(papers)
    run.log("add", f"{len(found)} papers added manually ({added} new)", errors=errors)
    print(f"Added {len(found)} papers ({added} new).")
    for e in errors:
        print(f"  {e}")


def cmd_import(args) -> None:
    from .evaluate import label
    from .importer import fill_from_openalex, new_stats, read_file
    run = _run(args)
    found, errors, stats = [], [], new_stats()
    for path in args.files:
        file_stats = new_stats()
        try:
            records = read_file(path, file_stats, args.label_column)
        except (OSError, ValueError) as e:
            raise SystemExit(f"Cannot import {path}: {e}")
        for p in records:
            p.found_via = [f"import:{os.path.basename(path)}"]
        info(f"  {path}: {len(records)} records" + (f", labels from column {file_stats['label_column']!r}"
                                                    if file_stats["label_column"] else ""))
        for k in ("rows", "skipped", "skipped_included", "unreadable_labels"):
            stats[k] += file_stats[k]
        found.extend(records)
    filled, errs = fill_from_openalex(found) if not args.no_fetch else (0, [])
    errors.extend(errs)
    run.save_raw(f"import-{_seq(run, 'import-'):02d}", found)
    papers, added = merge_into(run.load(), found)
    imported = [p for p in papers if any(v.startswith("import:") for v in p.found_via)]
    labelled = [p for p in imported if label(p) is not None]
    counts = {"labelled": len(labelled), "labelled_included": sum(label(p) for p in labelled),
              "label_conflicts": sum(1 for p in labelled if p.extra.get("label_conflict")),
              "untitled": sum(1 for p in imported if not p.title),
              "no_abstract": sum(1 for p in imported if not p.abstract)}
    _finish(run, papers, found, "import", f"{len(args.files)} files → {len(found)} records, {added} new "
            f"(total {len(papers)})", records=len(found), added=added, files=args.files, fetched=filled,
            errors=errors, **stats, **counts)
    print(f"Imported {len(found)} records ({stats['rows']} rows read, {stats['skipped']} skipped), {added} new, "
          f"{len(papers)} unique papers in the run.")
    if stats["skipped_included"]:
        print(f"  warning: {stats['skipped_included']} skipped rows were labelled included (no title or identifier)")
    if labelled:
        print(f"  labels after merging duplicates: {counts['labelled']} papers, {counts['labelled_included']} included")
    if counts["label_conflicts"]:
        print(f"  warning: {counts['label_conflicts']} papers merged records with conflicting labels (kept 'included')")
    if stats["unreadable_labels"]:
        print(f"  warning: {stats['unreadable_labels']} label values not understood (kept unlabelled)")
    if filled:
        print(f"  fetched titles/abstracts for {filled} records from OpenAlex")
    if counts["untitled"] or counts["no_abstract"]:
        print(f"  {counts['untitled']} papers have no title and {counts['no_abstract']} no abstract "
              f"(try: lr.py complete)")
    for e in errors:
        print(f"  error: {e}")


def _fmt(v) -> str:
    return "–" if v is None else f"{v:.3f}"


def cmd_eval(args) -> None:
    import json
    from . import evaluate
    run = _run(args)
    papers = run.load()
    result: dict = {}
    if args.labels:
        from .importer import read_file
        try:
            labelled = read_file(args.labels, label_column=args.label_column)
        except (OSError, ValueError) as e:
            raise SystemExit(f"Cannot read {args.labels}: {e}")
        result["label_matching"] = lm = evaluate.attach_labels(papers, labelled)
        print(f"Labels from {args.labels}: {lm['matched']} run papers matched; "
              f"{lm['unmatched_positives']} included papers in the file are not in the run")
        if lm["conflicts"]:
            print(f"  warning: {lm['conflicts']} label conflicts (kept 'included')")
    if any(evaluate.label(p) is not None for p in papers):
        result.update(evaluate.evaluate(papers))
        unmatched = result.get("label_matching", {}).get("unmatched_positives", 0)
        print(f"Labelled papers: {result['labelled']} ({result['included_by_humans']} included by the reviewers); "
              f"unscreened: {result['unscreened']} ({result['unscreened_included']} of them included); "
              f"no abstract: {result['no_abstract']}")
        keys = ("recall", "specificity", "precision", "f1", "kappa", "work_saved", "wss")
        print("rule\t" + "\t".join(keys) + "\tTP\tFP\tFN\tTN")
        for rule, m in result["rules"].items():
            print(f"{rule}\t" + "\t".join(_fmt(m[k]) for k in keys) + f"\t{m['tp']}\t{m['fp']}\t{m['fn']}\t{m['tn']}")
        print(f"WSS@95 (reading in LR-AI's order; ties counted pessimistically): {_fmt(result['wss@95'])} "
              f"(optimistic ties: {_fmt(result['wss@95_best_case'])})")
        if unmatched:
            print(f"  note: recall above counts only papers in the run; {unmatched} included papers were never "
                  "found, so the end-to-end recall is lower")
        if result["missed"]:
            print(f"Included by the reviewers but excluded by LR-AI ({len(result['missed'])}):")
            for m in result["missed"][: args.show]:
                print(f"  {m['id']}\t{m['status'] or 'filtered'}\t{shorten(m['title'], 90)}\t{shorten(m['reason'], 90)}")
    elif not args.compare:
        raise SystemExit("No labelled papers. Import a labelled file (lr.py import) or pass --labels FILE.")
    if args.compare:
        runs = [papers] + [Run(path, use_cache=False).load() for path in args.compare]
        result["agreement"] = agr = evaluate.agreement(runs)
        print(f"Agreement across {agr['runs']} runs on {agr['papers']} papers screened by the LLM in all of them "
              f"(screened per run: {', '.join(map(str, agr['screened_per_run']))}):")
        for pr in agr["pairs"]:
            print(f"  runs {pr['runs'][0]} vs {pr['runs'][1]}: agreement {_fmt(pr['agreement'])}, "
                  f"kappa {_fmt(pr['kappa'])} (core/skim/exclude), {_fmt(pr['kappa_included'])} (included or not)")
        print(f"  Fleiss kappa: {_fmt(agr['fleiss_kappa'])} (3 classes), "
              f"{_fmt(agr['fleiss_kappa_included'])} (included or not)")
    out = args.out or run.file("eval.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    run.log("eval", f"evaluation written to {os.path.basename(out)}",
            **{k: v for k, v in result.items() if k != "missed"})
    print(f"Wrote {out}")


def cmd_coverage(args) -> None:
    import json
    from . import evaluate
    from .importer import read_file
    run = _run(args)
    papers = run.load()
    try:
        gold = read_file(args.labels, label_column=args.label_column)
    except (OSError, ValueError) as e:
        raise SystemExit(f"Cannot read {args.labels}: {e}")
    at = [int(x) for x in args.at.split(",")] if args.at else []
    r = evaluate.coverage(papers, gold, at)
    if not r["review_included"]:
        raise SystemExit(f"{args.labels} has no records labelled included.")
    print(f"Review: {r['review_included']} included of {r['review_screened']} screened records. "
          f"LR-AI run: {r['run_papers']} papers, {r['run_included']} included (core + skim).")
    print(f"  included studies found anywhere in the run: {r['found_in_run']} ({_fmt(r['recall_run'])})")
    print(f"  ... and kept in LR-AI's included list:     {r['kept_by_lrai']} ({_fmt(r['recall_included_list'])}); "
          f"precision against the review {_fmt(r['precision_vs_review'])} (lower bound)")
    print("  recall in LR-AI's top N (included first, by relevance):")
    for k, v in r["recall_at"].items():
        print(f"    top {k}: {_fmt(v)}")
    print(f"  share of the review's screened records that LR-AI also found: {_fmt(r['overlap_with_review_screened'])}")
    print("  found by: " + ", ".join(f"{k} {v}" for k, v in r["found_by_stage"].items()))
    if r["missed"]:
        print(f"Included in the review but not in LR-AI's included list ({len(r['missed'])}):")
        for m in r["missed"][: args.show]:
            print(f"  {m['id']}\t{shorten(m['why'], 60)}\t{shorten(m['title'], 90)}")
    print(f"LR-AI included {r['extras_count']} papers the review never screened (check a sample for relevance).")
    out = args.out or run.file("coverage.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    run.log("coverage", f"coverage against {os.path.basename(args.labels)} written to {os.path.basename(out)}",
            **{k: v for k, v in r.items() if k not in ("missed", "extras")})
    print(f"Wrote {out}")


EDITABLE = ("status", "status_reason", "priority", "first_level", "second_level", "summary", "short_summary",
            "rq_relation", "code")
CHOICES = {"status": STATUSES, "priority": PRIORITIES}


def cmd_set(args) -> None:
    """Manual edits win: fields set here are recorded in extra["manual"] and never overwritten by `apply`."""
    run = _run(args)
    papers = run.load()
    by_id = {p.id: p for p in papers}
    p = by_id.get(args.id)
    if p is None:
        raise SystemExit(f"No paper with id {args.id} (see `show`).")
    manual = set(p.extra.get("manual") or [])
    keys = []
    for assignment in args.assignments:
        key, _, val = assignment.partition("=")
        if key not in EDITABLE:
            raise SystemExit(f"Cannot set {key!r}. Editable: {', '.join(EDITABLE)}")
        value = None if val.lower() in ("", "none", "null") else val
        if value is not None and key in CHOICES:
            value = value.lower()
            if value not in CHOICES[key]:
                raise SystemExit(f"{key} must be one of: {', '.join(CHOICES[key])}")
        setattr(p, key, value)
        keys.append(key)
    if "status" in keys and "status_reason" not in keys:
        p.status_reason = "set manually"
    p.extra["manual"] = sorted(manual | set(keys))
    run.save(papers)
    run.log("set", f"{args.id}: {', '.join(args.assignments)}")
    print(f"Updated {args.id}.")


def cmd_status(args) -> None:
    run = _run(args)
    papers = run.load()
    s = report.stats(run, papers)
    print(f"Run: {run.path}\nTopic: {run.config.get('topic')}")
    for label, n in report.flow_rows(s):
        print(f"  {label}: {n}")
    print(f"  Summarized (enriched): {s['enriched']}")
    print("Next: " + report.next_step(s, run.config))


def _tabs(run: Run):
    from . import layout
    papers = run.load()
    return papers, layout.build(papers, run.config, report.stats(run, papers))


def sheet_title(run: Run) -> str:
    return (run.config.get("export") or {}).get("title") or f"LR — {run.config.get('topic') or 'review'}"


def cmd_export(args) -> None:
    from .export_xlsx import write_xlsx
    run = _run(args)
    papers, tabs = _tabs(run)
    included = [p for p in papers if p.included]
    if not included:
        raise SystemExit("No included papers yet (screen first).")
    out = args.out or run.file("papers.xlsx")
    write_xlsx(tabs, out)
    run.log("export", f"{len(included)} papers → {os.path.basename(out)}")
    print(f"Wrote {out} ({len(included)} papers, {len(tabs[0].rows) - 1} rows incl. category rows).")
    for row, kind in zip(tabs[0].rows, tabs[0].kinds):
        if kind in ("group", "subgroup"):
            print(("  " if kind == "group" else "      ") + str(row[0]))
    print(f"Google Sheet title: {sheet_title(run)}")
    account = google_account()
    if account:
        print(f"Google account: {account} (from {GOOGLE_ACCOUNT_VAR})")
    print("Next for Google Sheets: create the spreadsheet, then run sheet-plan --spreadsheet-id <ID>.")


def cmd_sheet_plan(args) -> None:
    from .export_gsheets import build_plan, write_plan
    run = _run(args)
    _, tabs = _tabs(run)
    account = google_account(args.account)
    files = build_plan(tabs, args.spreadsheet_id, args.sheet_id, account)
    paths = write_plan(files, run.file("export", "gsheets"))
    url = f"https://docs.google.com/spreadsheets/d/{args.spreadsheet_id}/edit"
    with open(run.file("sheet_url.txt"), "w", encoding="utf-8") as f:
        f.write(url + "\n")
    run.log("sheet-plan", f"{sum(len(t) for _, _, t in files)} Composio calls in {len(paths)} files for {url}")
    print(f"Google Sheets plan: {len(paths)} files; execute them in order, one COMPOSIO_MULTI_EXECUTE_TOOL call each:")
    for path, (_, desc, tools) in zip(paths, files):
        print(f"  {path}  ({len(tools)} calls) — {desc}")
    if account:
        print(f"Google account: {account}")
    print(f"Sheet URL: {url}")


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lr.py", description="LR-AI: automated literature review pipeline.")
    ap.add_argument("--version", action="version", version=f"LR-AI {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    def cmd(name: str, fn, help_text: str, run: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        if run:
            p.add_argument("--run", help="run directory (default: most recent under ./lr-runs)")
            p.add_argument("--no-cache", action="store_true", help="ignore cached API responses")
        p.set_defaults(func=fn)
        return p

    p = cmd("init", cmd_init, "Create a run folder with a config.yaml template.", run=False)
    p.add_argument("topic")
    p.add_argument("--root", default="lr-runs")
    p.add_argument("--name", help="short name for the folder (default: from topic)")

    cmd("doctor", cmd_doctor, "Check dependencies, API reachability and API keys.", run=False)

    p = cmd("seed", cmd_seed, "Step 1: seed queries (Semantic Scholar, falling back to OpenAlex / arXiv) + known papers (seed.papers).")
    p.add_argument("--query", action="append", help="run this query instead of seed.queries (repeatable; ad hoc)")
    p.add_argument("--limit", type=int, help="papers per query (default: seed.per_query)")
    p.add_argument("--show", type=int, default=30, help="how many seed papers to list")

    p = cmd("search", cmd_search, "Step 2: boolean keyword search in databases (search.queries).")
    p.add_argument("--query", action="append", help="run this boolean query instead of search.queries (repeatable)")
    p.add_argument("--sources", help="comma-separated: openalex,semantic_scholar,arxiv")
    p.add_argument("--limit", type=int, help="papers per query per source (default: search.per_query)")

    p = cmd("snowball", cmd_snowball, "Step 3: one round of backward/forward snowballing.")
    p.add_argument("--round", type=int, help="round number (default: next round)")
    p.add_argument("--from", dest="source", choices=["all", "included"], help="default: snowball.from")
    p.add_argument("--direction", choices=["backward", "forward", "both"])
    p.add_argument("--backend", choices=["auto", "openalex", "semantic_scholar"])
    p.add_argument("--max-references", type=int)
    p.add_argument("--max-citations", type=int)
    p.add_argument("--max-frontier", type=int, default=300)
    p.add_argument("--force", action="store_true", help="allow a frontier larger than --max-frontier")

    p = cmd("complete", cmd_complete, "Fill missing abstracts/citation counts (Semantic Scholar, then OpenAlex).")
    p.add_argument("--all", action="store_true", help="also retry sources that already answered for a paper")

    cmd("filter", cmd_filter, "Step 4a: apply the deterministic filters from config.yaml.")

    p = cmd("batches", cmd_batches, "Write batch files for screening/enrichment subagents.")
    p.add_argument("--stage", choices=screening.STAGES, required=True)
    p.add_argument("--size", type=int, help="papers per batch (default: screening.batch_size)")
    p.add_argument("--force", action="store_true", help="include papers that already have results")

    p = cmd("apply", cmd_apply, "Merge new subagent result files into papers.jsonl (manual `set` edits win).")
    p.add_argument("--stage", choices=screening.STAGES, required=True)
    p.add_argument("--all", action="store_true", help="re-apply result files that were already applied")

    p = cmd("show", cmd_show, "List papers (filter with --where key=value).")
    p.add_argument("--where", action="append", help="e.g. status=core, included=true, found=forward, round=1")
    p.add_argument("--fields", help="comma-separated, e.g. id,year,citations,title,short_summary,reason")
    p.add_argument("--sort", help="citations | year | relevance | hits")
    p.add_argument("--limit", type=int, default=50)

    p = cmd("add", cmd_add, "Add papers by DOI, arXiv id or exact title (never filtered out).")
    p.add_argument("items", nargs="+")

    p = cmd("import", cmd_import, "Import papers from CSV/TSV, RIS or BibTeX files (e.g. a database export or a "
                                  "labelled benchmark such as SYNERGY).")
    p.add_argument("files", nargs="+")
    p.add_argument("--no-fetch", action="store_true", help="don't fetch missing titles/abstracts from OpenAlex")
    p.add_argument("--label-column", help="column (or BibTeX field) holding the human decision "
                                          "(default: label_included, included, label, ...)")

    p = cmd("eval", cmd_eval, "Compare screening decisions with human labels (recall, precision, kappa, WSS) "
                              "and, with --compare, with other runs of the same papers.")
    p.add_argument("--labels", help="labelled file (CSV/RIS/BibTeX) to match onto the run's papers")
    p.add_argument("--label-column", help="label column in --labels (default: label_included, included, ...)")
    p.add_argument("--compare", nargs="+", metavar="RUN", help="other run folders that screened the same papers")
    p.add_argument("--out", help="output path (default: <run>/eval.json)")
    p.add_argument("--show", type=int, default=20, help="how many missed papers to list")

    p = cmd("coverage", cmd_coverage, "Compare the run with a published review's labelled list: recall of the "
                                      "review's included studies in the run, in LR-AI's included list and in "
                                      "LR-AI's top N, and which stage found them.")
    p.add_argument("--labels", required=True, help="the review's labelled file (CSV/RIS/BibTeX)")
    p.add_argument("--label-column", help="label column (default: label_included, included, ...)")
    p.add_argument("--at", help="comma-separated list sizes N for recall in the top N, e.g. 104,300,1000")
    p.add_argument("--out", help="output path (default: <run>/coverage.json)")
    p.add_argument("--show", type=int, default=30, help="how many missed studies to list")

    p = cmd("set", cmd_set, "Manually set fields on one paper, e.g. status=exclude status_reason='off topic'.")
    p.add_argument("id")
    p.add_argument("assignments", nargs="+", metavar="key=value")

    cmd("status", cmd_status, "Show counts per stage and the suggested next step.")

    p = cmd("export", cmd_export, "Step 6a: write the styled .xlsx (Papers, Overview, Method).")
    p.add_argument("--out", help="output path (default: <run>/papers.xlsx)")

    p = cmd("sheet-plan", cmd_sheet_plan, "Step 6b: write Composio calls that build the Google Sheet.")
    p.add_argument("--spreadsheet-id", required=True)
    p.add_argument("--sheet-id", type=int, default=0, help="sheetId of the new spreadsheet's first tab")
    p.add_argument("--account", help="Composio account alias or id, if several Google accounts are connected "
                                     f"(default: ${GOOGLE_ACCOUNT_VAR})")
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        info("Interrupted. Completed API calls are cached; re-run the command to resume.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
