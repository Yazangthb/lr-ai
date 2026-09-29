from conftest import paper

from lrai.models import Paper, norm_arxiv, norm_doi, norm_title, read_jsonl, write_jsonl


def test_norm_doi_strips_prefixes_and_lowercases():
    assert norm_doi("https://doi.org/10.1145/ABC.123") == "10.1145/abc.123"
    assert norm_doi("doi: 10.1/X") == "10.1/x"
    assert norm_doi("not a doi") is None
    assert norm_doi(None) is None


def test_norm_arxiv_handles_urls_versions_and_prefixes():
    assert norm_arxiv("arXiv:2401.01234v3") == "2401.01234"
    assert norm_arxiv("https://arxiv.org/abs/2401.01234v1") == "2401.01234"
    assert norm_arxiv("https://arxiv.org/pdf/2401.01234.pdf") == "2401.01234"
    assert norm_arxiv("cs/0112017v2") == "cs/0112017"


def test_arxiv_doi_becomes_arxiv_id():
    p = paper(doi="10.48550/arXiv.2401.01234")
    assert p.doi is None
    assert p.arxiv_id == "2401.01234"
    assert p.id == "arxiv:2401.01234"


def test_id_prefers_doi_then_arxiv_then_openalex():
    assert paper(doi="10.1/x", arxiv_id="2401.1", openalex_id="W1").id == "doi:10.1/x"
    assert paper(arxiv_id="2401.00001", openalex_id="https://openalex.org/W1").id == "arxiv:2401.00001"
    assert paper(openalex_id="https://openalex.org/w123").id == "openalex:W123"
    assert paper(title="Only a title here").id.startswith("title:")


def test_markup_and_entities_are_cleaned():
    p = paper(title="Detecting <i>E. coli</i> &amp; friends", venue="Stats &amp; Computing",
              abstract="<jats:p>Hello   world</jats:p>")
    assert p.title == "Detecting E. coli & friends"
    assert p.venue == "Stats & Computing"
    assert p.abstract == "Hello world"


def test_norm_title_ignores_case_accents_and_punctuation():
    assert norm_title("Café: A Graph-Based Study!") == norm_title("cafe a graph based study")


def test_found_kinds_and_hits():
    p = paper(found_via=["seed:q1", "search:openalex:q2", "backward:doi:10.1/a", "forward:doi:10.1/b",
                         "backward:doi:10.1/b"])
    assert p.found_kinds == ["seed", "openalex", "backward", "forward"]
    assert p.hits == 2


def test_jsonl_round_trip_keeps_extra_and_skips_meta(tmp_path):
    path = str(tmp_path / "p.jsonl")
    original = paper(doi="10.1/x", authors=["A", "B"], year=2020, extra={"note": 1})
    write_jsonl(path, [original], meta={"stage": "screen"})
    (loaded,) = read_jsonl(path)
    assert loaded == original
    assert isinstance(loaded, Paper)
