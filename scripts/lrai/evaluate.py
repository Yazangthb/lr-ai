"""Compare LR-AI's screening decisions with human labels, and repeated runs with each other.

Labels live on the papers themselves (`extra["label"]`, set by `lr.py import` or `--labels`), so two records
that happen to share an id can never swap or overwrite each other's label. Two decision rules are scored:
"core" (only core counts as included) and "core+skim" (anything not excluded counts, the high-recall setting).
Papers removed by the automatic filters count as excluded. Papers not screened yet are reported and left out.

Metrics: recall (sensitivity), specificity, precision, F1, negative predictive value, Cohen's kappa against the
human labels, the share of records a person no longer has to read, WSS (work saved over sampling at the recall
reached, Cohen et al. 2006) and WSS@95 when papers are read in LR-AI's order (status, then relevance score).
Undefined values (e.g. recall without any included paper) are None, never 0.
"""
from __future__ import annotations

import math
from collections import Counter

from .dedup import group
from .models import Paper

RULES = ("core", "core+skim")
_ORDER = {"core": 0, "skim": 1, "exclude": 2}


def label(p: Paper) -> int | None:
    v = p.extra.get("label")
    return v if v in (0, 1) and not isinstance(v, bool) else None


def attach_labels(papers: list[Paper], labelled: list[Paper]) -> dict:
    """Copy labels from `labelled` (e.g. a SYNERGY file) onto matching run papers. Returns counts, including
    included papers in the file that match nothing in the run (they lower the true recall)."""
    combined = list(papers) + [q for q in labelled if label(q) is not None]
    n = len(papers)
    matched = conflicts = 0
    unmatched_pos = unmatched_neg = 0
    for idxs in group(combined):
        run_idx = [i for i in idxs if i < n]
        file_labels = {label(combined[i]) for i in idxs if i >= n}
        if not file_labels:
            continue
        if not run_idx:
            unmatched_pos += 1 in file_labels
            unmatched_neg += file_labels == {0}
            continue
        value = max(file_labels)
        conflicts += len(file_labels) > 1
        for i in run_idx:
            if label(papers[i]) not in (None, value):
                conflicts += 1
            papers[i].extra["label"] = value
            matched += 1
    return {"matched": matched, "conflicts": conflicts, "unmatched_positives": unmatched_pos,
            "unmatched_negatives": unmatched_neg}


def predicted(p: Paper, rule: str) -> bool | None:
    """True/False for a decision, None when the paper still awaits screening."""
    if p.excluded_reason:
        return False
    if p.status is None:
        return None
    return p.status == "core" if rule == "core" else p.status in ("core", "skim")


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def kappa(pairs: list[tuple]) -> float | None:
    """Cohen's kappa for two raters over any categories; None when chance agreement is 1 (undefined)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    cats = {c for pair in pairs for c in pair}
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def confusion(papers: list[Paper], rule: str) -> dict:
    c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for p in papers:
        y, pred = label(p), predicted(p, rule)
        if y is None or pred is None:
            continue
        c[("t" if bool(pred) == bool(y) else "f") + ("p" if pred else "n")] += 1
    return c


def metrics(c: dict) -> dict:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    n = tp + fp + fn + tn
    recall, precision = _ratio(tp, tp + fn), _ratio(tp, tp + fp)
    if recall is None:
        f1 = None
    elif tp == 0:
        f1 = 0.0
    else:
        f1 = 2 * recall * precision / (recall + precision)
    pairs = [(1, 1)] * tp + [(0, 1)] * fp + [(1, 0)] * fn + [(0, 0)] * tn  # (label, prediction)
    saved = _ratio(tn + fn, n)
    return {
        **c, "n": n, "recall": recall, "specificity": _ratio(tn, tn + fp), "precision": precision, "f1": f1,
        "npv": _ratio(tn, tn + fn), "accuracy": _ratio(tp + tn, n), "kappa": kappa(pairs),
        "work_saved": saved, "wss": saved - (1 - recall) if saved is not None and recall is not None else None,
    }


def _rank_key(p: Paper) -> tuple:
    return (1 if p.excluded_reason else 0, _ORDER.get(p.status or "exclude", 2),
            -(p.relevance if p.relevance is not None else 0.0))


def wss_at(papers: list[Paper], level: float = 0.95) -> dict | None:
    """Work saved over sampling at `level` recall when reading papers in LR-AI's order (core, skim, exclude;
    higher relevance first; filtered papers last). Papers with the same rank are a tie: `low` assumes the
    included ones come last within a tie (conservative), `high` that they come first."""
    scored = [p for p in papers if label(p) is not None and predicted(p, "core") is not None]
    positives = sum(label(p) for p in scored)
    if not scored or not positives:
        return None
    need, n = math.ceil(level * positives - 1e-9), len(scored)
    ties = Counter()
    pos_in = Counter()
    for p in scored:
        ties[_rank_key(p)] += 1
        pos_in[_rank_key(p)] += label(p)
    out = {}
    for name, worst in (("low", True), ("high", False)):
        read = seen = 0
        for key in sorted(ties):
            size, pos = ties[key], pos_in[key]
            if seen + pos >= need:
                still = need - seen
                # worst case: all negatives of the tie first, best case: positives first
                read += (size - pos + still) if worst else still
                break
            read += size
            seen += pos
        out[name] = (n - read) / n - (1 - level)
    return out


def evaluate(papers: list[Paper]) -> dict:
    labelled = [p for p in papers if label(p) is not None]
    unscreened = [p for p in labelled if predicted(p, "core") is None]
    w = wss_at(papers, 0.95)
    return {
        "labelled": len(labelled),
        "included_by_humans": sum(label(p) for p in labelled),
        "unscreened": len(unscreened),
        "unscreened_included": sum(label(p) for p in unscreened),
        "no_abstract": sum(1 for p in labelled if not p.abstract),
        "label_conflicts": sum(1 for p in labelled if p.extra.get("label_conflict")),
        "rules": {rule: metrics(confusion(papers, rule)) for rule in RULES},
        "wss@95": w["low"] if w else None,
        "wss@95_best_case": w["high"] if w else None,
        "missed": [{"id": p.id, "title": p.title, "status": p.status,
                    "reason": p.excluded_reason or p.status_reason}
                   for p in labelled if label(p) and predicted(p, "core+skim") is False],
    }


def _coverage_rank(p: Paper) -> tuple:
    """LR-AI's reading order for a whole run: included (core, then skim) by relevance, then papers screened
    out, then papers removed by the filters or not screened."""
    if p.excluded_reason or p.status is None:
        return (3, 0.0)
    return (_ORDER[p.status], -(p.relevance if p.relevance is not None else 0.0))


def coverage(papers: list[Paper], gold: list[Paper], at: list[int] | None = None) -> dict:
    """How much of a published review LR-AI reproduces when it searched on its own.

    `gold` is the review's labelled list (label 1 = included in the review, 0 = screened and excluded).
    Reports recall of the included studies in the whole run, in LR-AI's own included list (core + skim) and
    in LR-AI's top-N for each N in `at` (e.g. N = the size of the review's own lists, for an equal-length
    comparison), which stage found each included study, and LR-AI's included papers that the review never
    screened (candidates for a manual relevance check; precision against the review is a lower bound)."""
    gold = [g for g in gold if label(g) is not None]
    combined = list(papers) + gold
    n = len(papers)
    order = sorted(range(n), key=lambda i: (_coverage_rank(papers[i]), papers[i].id))
    rank_of = {i: r for r, i in enumerate(order, 1)}
    rows = []  # one per gold record group
    extras = []
    for idxs in group(combined):
        run_idx = [i for i in idxs if i < n]
        gold_idx = [i for i in idxs if i >= n]
        if not gold_idx:
            if any(papers[i].included for i in run_idx):
                extras.append(min(run_idx, key=lambda i: rank_of[i]))
            continue
        lab = max(label(combined[i]) for i in gold_idx)
        best = min(run_idx, key=lambda i: rank_of[i]) if run_idx else None
        rows.append({"label": lab, "gold": combined[gold_idx[0]], "run": best,
                     "rank": rank_of[best] if best is not None else None})
    positives = [r for r in rows if r["label"] == 1]
    total = len(positives)
    in_run = [r for r in positives if r["run"] is not None]
    kept = [r for r in in_run if papers[r["run"]].included]
    list_size = sum(1 for p in papers if p.included)
    sizes = sorted((set(at or []) | {total, list_size}) - {0})
    stage = Counter()
    for r in in_run:
        kinds = set(papers[r["run"]].found_kinds)
        snow = bool(kinds & {"backward", "forward"})
        searched = bool(kinds - {"backward", "forward"})
        stage["search and snowballing" if snow and searched else "snowballing only" if snow else "search only"] += 1
    missed = []
    for r in positives:
        if r["run"] is None:
            missed.append({"title": r["gold"].title, "id": r["gold"].id, "why": "never found"})
        elif not papers[r["run"]].included:
            p = papers[r["run"]]
            missed.append({"title": p.title, "id": p.id,
                           "why": p.excluded_reason or ("screened out: " + (p.status_reason or "")
                                                        if p.status else "not screened")})
    return {
        "review_included": total,
        "review_screened": len(rows),
        "run_papers": n,
        "run_included": list_size,
        "found_in_run": len(in_run),
        "kept_by_lrai": len(kept),
        "recall_run": _ratio(len(in_run), total),
        "recall_included_list": _ratio(len(kept), total),
        "precision_vs_review": _ratio(len(kept), list_size),
        "recall_at": {str(k): _ratio(sum(1 for r in in_run if r["rank"] <= k), total) for k in sizes},
        "overlap_with_review_screened": _ratio(sum(1 for r in rows if r["run"] is not None), len(rows)),
        "found_by_stage": dict(stage),
        "missed": missed,
        "extras_count": len(extras),
        "extras": [{"id": papers[i].id, "title": papers[i].title, "status": papers[i].status,
                    "relevance": papers[i].relevance} for i in sorted(extras, key=lambda i: rank_of[i])],
    }


def fleiss(ratings: list[list]) -> float | None:
    """Fleiss' kappa; `ratings` holds one list of category labels per item (same number of raters each)."""
    items = [r for r in ratings if len(r) >= 2]
    if not items:
        return None
    m = len(items[0])
    items = [r for r in items if len(r) == m]
    cats = sorted({c for r in items for c in r}, key=str)
    n = len(items)
    p_bar = sum((sum(r.count(c) ** 2 for c in cats) - m) / (m * (m - 1)) for r in items) / n
    pe = sum((sum(r.count(c) for r in items) / (n * m)) ** 2 for c in cats)
    return None if pe == 1 else (p_bar - pe) / (1 - pe)


def agreement(runs: list[list[Paper]]) -> dict:
    """Agreement between repeated LLM screenings of the same papers. Papers are matched across runs by their
    identifiers and titles (not by id strings, which can change when metadata is completed). Only papers the
    LLM screened in every run count: papers removed by the automatic filters would agree trivially."""
    combined, owner = [], []
    for r, papers in enumerate(runs):
        for p in papers:
            if not p.excluded_reason and p.status:
                combined.append(p)
                owner.append(r)
    rows = []
    for idxs in group(combined):
        by_run = {}
        for i in idxs:
            by_run.setdefault(owner[i], combined[i].status)
        if len(by_run) == len(runs):
            rows.append([by_run[r] for r in range(len(runs))])
    incl = [[s in ("core", "skim") for s in row] for row in rows]
    pairs = []
    for a in range(len(runs)):
        for b in range(a + 1, len(runs)):
            pairs.append({"runs": [a + 1, b + 1],
                          "agreement": _ratio(sum(row[a] == row[b] for row in rows), len(rows)),
                          "kappa": kappa([(row[a], row[b]) for row in rows]),
                          "kappa_included": kappa([(row[a], row[b]) for row in incl])})
    screened = [sum(1 for p in ps if not p.excluded_reason and p.status) for ps in runs]
    return {"runs": len(runs), "papers": len(rows), "screened_per_run": screened, "pairs": pairs,
            "fleiss_kappa": fleiss(rows), "fleiss_kappa_included": fleiss(incl)}
