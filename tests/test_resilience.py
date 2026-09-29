"""Behavior under partial API failures: nothing may be silently wrong or silently missing."""
import json
import os

from conftest import paper

from lrai import complete, http, report, resolve, screening
from lrai.http import HttpError
from lrai.models import read_meta, write_jsonl
from lrai.sources import arxiv

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
<opensearch:totalResults>{total}</opensearch:totalResults>{entries}</feed>"""
ENTRY = ("<entry><id>http://arxiv.org/abs/2101.{n:05d}v1</id><published>2021-01-01T00:00:00Z</published>"
         "<title>Paper {n}</title><summary>Abstract</summary></entry>")


def feed(total, numbers):
    return FEED.format(total=total, entries="".join(ENTRY.format(n=n) for n in numbers))


def test_title_lookup_rejects_a_different_paper(monkeypatch):
    wrong = paper("Eine ganz andere Arbeit über Proteine", doi="10.9/wrong", year=1990)
    monkeypatch.setattr(resolve.s2, "match_title", lambda t: wrong)
    monkeypatch.setattr(resolve.openalex, "search", lambda *a, **k: ([], 0))
    monkeypatch.setattr(resolve.arxiv, "search", lambda *a, **k: ([], 0))
    found, errors = resolve.resolve(["Graph neural networks for citation forecasting"], "seed:known")
    assert found == []
    assert "closest title differs" in errors[0]


def test_title_lookup_accepts_near_identical_title(monkeypatch):
    right = paper("Graph Neural Networks for Citation Forecasting.", doi="10.1/right")
    monkeypatch.setattr(resolve.s2, "match_title", lambda t: right)
    found, errors = resolve.resolve(["graph neural networks for citation forecasting"], "seed:known")
    assert [p.doi for p in found] == ["10.1/right"] and errors == [] and found[0].found_via == ["seed:known"]


def test_lookup_errors_are_not_reported_as_not_found(monkeypatch):
    def boom(*a, **k):
        raise HttpError(429, "Too Many Requests")
    monkeypatch.setattr(resolve.openalex, "lookup_dois", boom)
    monkeypatch.setattr(resolve.s2, "lookup", boom)
    found, errors = resolve.resolve(["doi.org/10.1145/12345"], "manual")  # scheme-less DOI URL
    assert found == [] and "lookup failed" in errors[0] and "Too Many Requests" in errors[0]
    assert "not found" not in errors[0]


def test_manual_edits_survive_later_apply(make_run):
    run = make_run()
    p = paper(doi="10.1/a")
    (batch,) = screening.write_batches(run, "screen", [p], size=10)
    with open(read_meta(batch)["output"], "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": p.id, "status": "core", "reason": "llm"}) + "\n")
    rep = screening.apply_results(run, "screen", [p])
    screening.save_state(run, "screen", rep["state"])
    assert p.status == "core"
    # the user overrides the decision, then apply runs again (e.g. after another snowball round)
    p.status, p.status_reason, p.extra["manual"] = "exclude", "off topic", ["status"]
    rep = screening.apply_results(run, "screen", [p])
    assert rep["files"] == 0 and p.status == "exclude"
    # even replaying every file keeps the manual decision
    screening.apply_results(run, "screen", [p], replay_all=True)
    assert (p.status, p.status_reason) == ("exclude", "off topic")


def test_arxiv_short_page_is_retried_and_not_cached(monkeypatch, tmp_path):
    http.set_cache_dir(str(tmp_path))
    pages = {0: [feed(150, range(100))], 100: [feed(150, []), feed(150, range(100, 150))]}
    calls = []

    def fake_request(url, params=None, **kw):
        calls.append((params["start"], kw.get("refresh", False)))
        text = pages[params["start"]].pop(0) if len(pages[params["start"]]) > 1 else pages[params["start"]][0]
        if kw.get("cache_check"):
            assert kw["cache_check"](text) == (params["start"] == 0 or "2101.00100" in text)
        return text

    monkeypatch.setattr(arxiv, "request", fake_request)
    monkeypatch.setattr(arxiv.time, "sleep", lambda s: None)
    papers, total = arxiv.search("graph", limit=150)
    assert total == 150 and len(papers) == 150
    assert calls == [(0, False), (100, False), (100, True)]


def test_complete_marks_only_sources_that_answered(monkeypatch):
    p = paper(doi="10.1/a")  # no abstract, no citation count

    def boom(keys):
        raise HttpError(429, "Too Many Requests")

    monkeypatch.setattr(complete.s2, "lookup", boom)
    monkeypatch.setattr(complete.openalex, "lookup_dois", lambda dois: [])
    complete.complete_metadata([p])
    assert p.extra["meta_checked"] == ["openalex"]  # Semantic Scholar never answered: retry it next time
    monkeypatch.setattr(complete.s2, "lookup", lambda keys: [paper(doi="10.1/a", abstract="Found it.",
                                                                  citation_count=3)])
    assert complete.complete_metadata([p]) == 1
    assert p.abstract == "Found it." and p.extra["meta_checked"] == ["openalex", "s2"]


def test_identified_counts_do_not_double_count_reruns(make_run):
    run = make_run()
    first = [paper(doi=f"10.1/{i}", found_via=["search:arxiv:q1"]) for i in range(3)]
    write_jsonl(run.file("raw", "search-01-arxiv.jsonl"), first)
    write_jsonl(run.file("raw", "search-02-arxiv.jsonl"), first + [paper(doi="10.1/9", found_via=["search:arxiv:q1"])])
    assert report.identified(run) == {"arxiv": 4}
    assert os.path.exists(run.file("raw"))
