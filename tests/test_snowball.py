import pytest
from conftest import paper

from lrai import snowball
from lrai.http import HttpError


def refs(n, prefix="r"):
    return [paper(f"Reference paper number {i} about graphs", doi=f"10.1/{prefix}{i}", citation_count=i)
            for i in range(n)]


@pytest.fixture
def no_s2(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("Semantic Scholar should not be called")
    monkeypatch.setattr(snowball.s2, "references", fail)
    monkeypatch.setattr(snowball.s2, "citations", fail)


def test_openalex_neighbors_get_provenance_round_and_caps(monkeypatch, no_s2):
    seed = paper(doi="10.1/seed")
    monkeypatch.setattr(snowball.openalex, "resolve", lambda p: {"id": "https://openalex.org/W9",
                                                                "referenced_works": ["W1", "W2", "W3"]})
    monkeypatch.setattr(snowball.openalex, "get_works", lambda ids: refs(5))
    monkeypatch.setattr(snowball.openalex, "cited_by", lambda wid, limit: refs(limit, "c"))
    found, stats = snowball.snowball_round([seed], round_no=1, max_refs=2, max_cites=3)
    backward = [p for p in found if p.found_via == ["backward:doi:10.1/seed"]]
    forward = [p for p in found if p.found_via == ["forward:doi:10.1/seed"]]
    assert [p.citation_count for p in backward] == [4, 3]  # most cited first, capped
    assert len(forward) == 3
    assert all(p.round == 1 for p in found)
    assert seed.openalex_id == "W9"
    assert stats["backend"] == {"openalex": 1} and stats["failed"] == []


def test_falls_back_to_semantic_scholar_when_openalex_unknown(monkeypatch):
    seed = paper(arxiv_id="2101.00001")
    monkeypatch.setattr(snowball.openalex, "resolve", lambda p: None)
    monkeypatch.setattr(snowball.s2, "references", lambda p, cap=1000: refs(2))
    monkeypatch.setattr(snowball.s2, "citations", lambda p, cap=1000: refs(4, "c"))
    found, stats = snowball.snowball_round([seed], round_no=1, max_refs=None, max_cites=2)
    assert len(found) == 4
    assert stats["backend"] == {"semantic_scholar": 1}


def test_missing_openalex_references_are_filled_from_semantic_scholar(monkeypatch):
    """OpenAlex often has citing papers but no reference list for preprints."""
    monkeypatch.setattr(snowball.openalex, "resolve", lambda p: {"id": "W1", "referenced_works": []})
    monkeypatch.setattr(snowball.openalex, "get_works", lambda ids: [])
    monkeypatch.setattr(snowball.openalex, "cited_by", lambda wid, limit: refs(2, "c"))
    monkeypatch.setattr(snowball.s2, "references", lambda p, cap=1000: refs(3))

    def no_citations(*a, **k):
        raise AssertionError("citations already came from OpenAlex")

    monkeypatch.setattr(snowball.s2, "citations", no_citations)
    found, stats = snowball.snowball_round([paper(doi="10.1/a")], 1, max_cites=5)
    assert stats["references"] == 3 and stats["citations"] == 2
    assert stats["backend"] == {"openalex+semantic_scholar": 1}


def test_null_max_citations_means_all_not_none(monkeypatch, no_s2):
    seen = {}
    monkeypatch.setattr(snowball.openalex, "resolve", lambda p: {"id": "W1", "referenced_works": []})
    monkeypatch.setattr(snowball.openalex, "get_works", lambda ids: [])

    def cited_by(wid, limit):
        seen["limit"] = limit
        return refs(3, "c")

    monkeypatch.setattr(snowball.openalex, "cited_by", cited_by)
    found, stats = snowball.snowball_round([paper(doi="10.1/a")], 1, direction="forward", max_cites=None)
    assert seen["limit"] == snowball.ALL_CITATIONS_CAP and stats["citations"] == 3


def test_persistent_openalex_error_disables_it_for_the_round(monkeypatch):
    calls = []

    def failing(p):
        calls.append(p)
        raise HttpError(503, "use a free API key", persistent=True)

    monkeypatch.setattr(snowball.openalex, "resolve", failing)
    monkeypatch.setattr(snowball.s2, "references", lambda p, cap=1000: refs(1))
    monkeypatch.setattr(snowball.s2, "citations", lambda p, cap=1000: [])
    found, stats = snowball.snowball_round([paper(doi="10.1/a"), paper(doi="10.1/b")], 1, max_cites=5)
    assert len(calls) == 1 and len(found) == 2 and stats["errors"]


def test_transient_rate_limit_does_not_disable_openalex_immediately(monkeypatch):
    calls = []

    def flaky(p):
        calls.append(p)
        if len(calls) == 1:
            raise HttpError(429, "Please retry in 37s, or use a free API key")
        return {"id": "W1", "referenced_works": []}

    monkeypatch.setattr(snowball.openalex, "resolve", flaky)
    monkeypatch.setattr(snowball.openalex, "get_works", lambda ids: [])
    monkeypatch.setattr(snowball.openalex, "cited_by", lambda wid, limit: refs(1, "c"))
    monkeypatch.setattr(snowball.s2, "references", lambda p, cap=1000: [])
    monkeypatch.setattr(snowball.s2, "citations", lambda p, cap=1000: [])
    snowball.snowball_round([paper(doi="10.1/a"), paper(doi="10.1/b")], 1, max_cites=5)
    assert len(calls) == 2  # still asked OpenAlex for the second paper


def test_transient_errors_are_reported_as_failed_not_unresolved(monkeypatch):
    def failing(p):
        raise HttpError(502, "bad gateway")

    monkeypatch.setattr(snowball.openalex, "resolve", failing)
    monkeypatch.setattr(snowball.s2, "references", lambda p, cap=1000: (_ for _ in ()).throw(HttpError(500, "x")))
    monkeypatch.setattr(snowball.s2, "citations", lambda p, cap=1000: [])
    seeds = [paper(doi=f"10.1/{i}") for i in range(2)]
    found, stats = snowball.snowball_round(seeds, 1)
    assert found == [] and stats["unresolved"] == [] and stats["failed"] == [p.id for p in seeds]


def test_unresolvable_papers_are_reported(monkeypatch):
    monkeypatch.setattr(snowball.openalex, "resolve", lambda p: None)
    monkeypatch.setattr(snowball.s2, "references", lambda p, cap=1000: None)
    monkeypatch.setattr(snowball.s2, "citations", lambda p, cap=1000: None)
    seed = paper(title="A paper nobody indexed at all")
    found, stats = snowball.snowball_round([seed], 1)
    assert found == [] and stats["unresolved"] == [seed.id] and stats["failed"] == []
