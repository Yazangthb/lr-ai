"""Compare LR-AI's screening decisions with human labels, and repeated runs with each other.

Labels come from `extra["label"]` (set by `lr.py import`) or from a separate labels file. Two decision rules are
scored: "core" (only core counts as included) and "core+skim" (anything not excluded counts, the high-recall
setting). Papers removed by the automatic filters count as excluded. Papers not screened yet are reported and
left out of the metrics.

Metrics: recall (sensitivity), specificity, precision, F1, negative predictive value, Cohen's kappa against the
human labels, the share of records a person no longer has to read, WSS (work saved over sampling at the recall
reached, Cohen et al. 2006) and WSS@95, which ranks papers by status and relevance score.
"""
from __future__ import annotations

import math

from .models import Paper

RULES = ("core", "core+skim")
_ORDER = {"core": 0, "skim": 1, "exclude": 2}


def labels_from(papers: list[Paper]) -> dict[str, int]:
    return {p.id: p.extra["label"] for p in papers if p.extra.get("label") in (0, 1)}


def attach_labels(papers: list[Paper], labelled: list[Paper]) -> int:
    """Copy labels from `labelled` (e.g. a SYNERGY file) onto matching run papers. Returns matches."""
    by_key: dict[str, int] = {}
    for q in labelled:
        if q.extra.get("label") in (0, 1):
            for k in q.dedup_keys():
                by_key[k] = max(by_key.get(k, 0), q.extra["label"])
    n = 0
    for p in papers:
        found = [by_key[k] for k in p.dedup_keys() if k in by_key]
        if found:
            p.extra["label"] = max(found)
            n += 1
    return n


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
    """Cohen's kappa for two raters over any categories."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    cats = {c for pair in pairs for c in pair}
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def confusion(papers: list[Paper], labels: dict[str, int], rule: str) -> dict:
    tp = fp = fn = tn = 0
    for p in papers:
        y = labels.get(p.id)
        if y is None:
            continue
        pred = predicted(p, rule)
        if pred is None:
            continue
        if pred and y:
            tp += 1
        elif pred:
            fp += 1
        elif y:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def metrics(c: dict) -> dict:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    n = tp + fp + fn + tn
    recall, precision = _ratio(tp, tp + fn), _ratio(tp, tp + fp)
    f1 = 2 * recall * precision / (recall + precision) if recall and precision else (0.0 if n else None)
    pairs = [(1, 1)] * tp + [(0, 1)] * fp + [(1, 0)] * fn + [(0, 0)] * tn  # (label, prediction)
    saved = _ratio(tn + fn, n)
    return {
        **c, "n": n, "recall": recall, "specificity": _ratio(tn, tn + fp), "precision": precision, "f1": f1,
        "npv": _ratio(tn, tn + fn), "accuracy": _ratio(tp + tn, n), "kappa": kappa(pairs),
        "work_saved": saved, "wss": saved - (1 - recall) if saved is not None and recall is not None else None,
    }


def wss_at(papers: list[Paper], labels: dict[str, int], level: float = 0.95) -> float | None:
    """Work saved over sampling at `level` recall when reading papers in LR-AI's order (core, skim, exclude;
    higher relevance first; filtered papers last). Ties are broken by id, independent of the labels."""
    scored = [p for p in papers if p.id in labels and predicted(p, "core") is not None]
    positives = sum(labels[p.id] for p in scored)
    if not scored or not positives:
        return None
    scored.sort(key=lambda p: (1 if p.excluded_reason else 0, _ORDER.get(p.status or "exclude", 2),
                               -(p.relevance if p.relevance is not None else 0.0), p.id))
    need, seen = math.ceil(level * positives), 0
    for read, p in enumerate(scored, 1):
        seen += labels[p.id]
        if seen >= need:
            return (len(scored) - read) / len(scored) - (1 - level)
    return None


def evaluate(papers: list[Paper], labels: dict[str, int]) -> dict:
    labelled = [p for p in papers if p.id in labels]
    unscreened = [p for p in labelled if predicted(p, "core") is None]
    out = {
        "labelled": len(labelled),
        "included_by_humans": sum(labels[p.id] for p in labelled),
        "unscreened": len(unscreened),
        "rules": {rule: metrics(confusion(papers, labels, rule)) for rule in RULES},
        "wss@95": wss_at(papers, labels, 0.95),
    }
    out["missed"] = [
        {"id": p.id, "title": p.title, "status": p.status, "reason": p.excluded_reason or p.status_reason}
        for p in labelled if labels[p.id] and predicted(p, "core+skim") is False
    ]
    return out


def fleiss(ratings: list[list]) -> float | None:
    """Fleiss' kappa; `ratings` holds one list of category labels per item (same number of raters each)."""
    items = [r for r in ratings if len(r) >= 2]
    if not items:
        return None
    m = len(items[0])
    items = [r for r in items if len(r) == m]
    cats = sorted({c for r in items for c in r}, key=str)
    n = len(items)
    p_i = [(sum(r.count(c) ** 2 for c in cats) - m) / (m * (m - 1)) for r in items]
    p_bar = sum(p_i) / n
    p_j = [sum(r.count(c) for r in items) / (n * m) for c in cats]
    pe = sum(x * x for x in p_j)
    return 1.0 if pe == 1 else (p_bar - pe) / (1 - pe)


def agreement(runs: list[list[Paper]]) -> dict:
    """Agreement between repeated screenings of the same papers (papers screened in every run)."""
    maps = [{p.id: (p.status if not p.excluded_reason else "exclude") for p in ps
             if p.status or p.excluded_reason} for ps in runs]
    common = sorted(set.intersection(*(set(m) for m in maps))) if maps else []
    three = [[m[i] for m in maps] for i in common]
    binary = [[s in ("core", "skim") for s in r] for r in three]
    pairs = []
    for a in range(len(maps)):
        for b in range(a + 1, len(maps)):
            pairs.append({"runs": [a + 1, b + 1],
                          "agreement": _ratio(sum(maps[a][i] == maps[b][i] for i in common), len(common)),
                          "kappa": kappa([(maps[a][i], maps[b][i]) for i in common]),
                          "kappa_included": kappa([(maps[a][i] in ("core", "skim"), maps[b][i] in ("core", "skim"))
                                                   for i in common])})
    return {"runs": len(maps), "papers": len(common), "pairs": pairs,
            "fleiss_kappa": fleiss(three), "fleiss_kappa_included": fleiss(binary)}
