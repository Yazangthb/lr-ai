from conftest import paper

from lrai import filters
from lrai.config import DEFAULTS


def cfg(**overrides):
    f = dict(DEFAULTS["filters"])
    f.update(overrides)
    return f


def reason(p, **overrides):
    return filters.exclusion_reason(p, cfg(**overrides), year_now=2026)


def test_year_bounds_keep_unknown_years():
    assert reason(paper(year=2015), year_min=2019) == "published before 2019"
    assert reason(paper(year=2027), year_max=2026) == "published after 2026"
    assert reason(paper(year=None), year_min=2019) is None


def test_language_and_type():
    assert reason(paper(language="de")) == "language: de"
    assert reason(paper(language=None)) is None
    assert reason(paper(type="Editorial")) == "publication type: Editorial"
    assert reason(paper(type="article")) is None


def test_min_citations_with_grace_period_and_unknown_counts():
    assert reason(paper(year=2018, citation_count=1), min_citations=5) == "fewer than 5 citations"
    assert reason(paper(year=2025, citation_count=0), min_citations=5, citation_grace_years=2) is None
    assert reason(paper(year=2018, citation_count=None), min_citations=5) is None


def test_keywords_support_phrases_and_prefixes():
    p = paper("Forecasting impact with citation graphs", abstract="We predict future citations.")
    assert reason(p, require_any=["predict*"]) is None
    assert reason(p, require_any=["citation graph"]) is None  # plural forms match
    assert reason(p, require_any=["predict"]) is None
    assert reason(p, require_any=["impacts"]) == "none of the required keywords"
    assert reason(p, require_any=["protein"]) == "none of the required keywords"
    assert reason(p, exclude_any=["forecast*"]) == "mentions 'forecast*'"


def test_keywords_match_hyphenated_forms():
    p = paper("A graph-based approach to citation forecasting")
    assert reason(p, require_any=["graph based"]) is None


def test_known_and_manual_papers_are_protected():
    assert reason(paper(year=1990, found_via=["seed:known"]), year_min=2019) is None
    assert reason(paper(year=1990, found_via=["manual"]), year_min=2019) is None


def test_min_hits_applies_only_to_snowballed_papers():
    snowballed = paper(round=1, found_via=["forward:a"])
    assert reason(snowballed, min_hits=2) == "linked from fewer than 2 papers"
    assert reason(paper(round=0), min_hits=2) is None


def test_apply_sets_and_clears_reasons():
    papers = [paper("Old paper on the forecasting of things", year=2000), paper(year=2022)]
    papers[1].excluded_reason = "stale reason"
    counts = filters.apply(papers, cfg(year_min=2019))
    assert papers[0].excluded_reason == "published before 2019"
    assert papers[1].excluded_reason is None
    assert counts == {"published before 2019": 1}
