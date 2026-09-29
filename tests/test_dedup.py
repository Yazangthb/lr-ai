from conftest import paper

from lrai.dedup import dedup, merge_into, merge_two


def test_same_doi_merges_and_keeps_best_fields():
    a = paper(doi="10.1/x", citation_count=5, found_via=["seed:q1"])
    b = paper(doi="https://doi.org/10.1/X", citation_count=9, abstract="longer abstract", found_via=["forward:p"])
    (m,) = dedup([a, b])
    assert m.citation_count == 9
    assert m.abstract == "longer abstract"
    assert m.found_via == ["seed:q1", "forward:p"]


def test_preprint_and_published_version_merge_on_title_and_close_year():
    pre = paper("Graph Neural Networks for Citation Forecasting", arxiv_id="2301.00001", year=2023, venue="arXiv")
    pub = paper("Graph neural networks for citation forecasting.", doi="10.1/pub", year=2024, venue="KDD")
    (m,) = dedup([pre, pub])
    assert m.doi == "10.1/pub" and m.arxiv_id == "2301.00001"
    assert m.venue == "KDD" and m.year == 2024  # published metadata wins


def test_same_title_far_apart_years_do_not_merge():
    a = paper("Graph Neural Networks for Citation Forecasting", year=2010)
    b = paper("Graph Neural Networks for Citation Forecasting", year=2020)
    assert len(dedup([a, b])) == 2


def test_near_identical_titles_merge_fuzzily():
    pre = paper("Utilizing Citation Network Structure to Predict Citation Counts: A Deep Learning Approach",
                arxiv_id="2009.02647", year=2020, venue="arXiv")
    pub = paper("Utilizing citation network structure to predict paper citation counts: A Deep learning approach",
                doi="10.1016/j.ipm.2021.102500", year=2021, venue="Information Processing & Management")
    (m,) = dedup([pre, pub])
    assert m.doi and m.arxiv_id == "2009.02647"


def test_numbered_titles_never_merge():
    a = paper("Graph neural networks for citation forecasting: Part I", year=2020)
    b = paper("Graph neural networks for citation forecasting: Part II", year=2020)
    c = paper("Language models are few-shot learners: evaluating GPT-3 on citation tasks", year=2021)
    d = paper("Language models are few-shot learners: evaluating GPT-4 on citation tasks", year=2021)
    assert len(dedup([a, b, c, d])) == 4


def test_short_titles_are_not_used_for_matching():
    assert len(dedup([paper("Introduction", year=2020), paper("Introduction", year=2020)])) == 2


def test_transitive_merge_through_different_ids():
    a = paper("Some long enough title for matching", arxiv_id="2301.00001")
    b = paper("Other formatting of the title", arxiv_id="2301.00001", s2_id="abc")
    c = paper("Yet another", s2_id="abc", doi="10.1/c")
    (m,) = dedup([a, b, c])
    assert m.doi == "10.1/c" and m.arxiv_id == "2301.00001" and m.s2_id == "abc"


def test_merge_into_counts_only_genuinely_new_papers():
    existing = [paper("First paper about citation graphs", doi="10.1/a", status="core")]
    new = [paper("First paper about citation graphs", doi="10.1/a", found_via=["backward:x"]),
           paper("Second, unrelated paper about proteins", doi="10.1/b")]
    merged, added = merge_into(existing, new)
    assert added == 1 and len(merged) == 2
    assert merged[0].status == "core"  # screening results survive merging
    assert merged[0].found_via == ["backward:x"]


def test_merge_keeps_lowest_round():
    a = paper(doi="10.1/a", round=2)
    b = paper(doi="10.1/a", round=0)
    assert merge_two(a, b).round == 0
