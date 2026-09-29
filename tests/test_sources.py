"""Parsing of API payloads (no network)."""
from lrai.sources import arxiv, openalex
from lrai.sources import semantic_scholar as s2

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1234</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2009.02647v2</id>
    <published>2020-09-06T00:00:00Z</published>
    <title>Utilizing Citation Network Structure
      to Predict Citation Counts</title>
    <summary>  We predict   citations. </summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Roe</name></author>
    <arxiv:doi>10.1016/j.ipm.2021.102500</arxiv:doi>
    <link title="pdf" href="http://arxiv.org/pdf/2009.02647v2" rel="related"/>
  </entry>
</feed>"""


def test_arxiv_feed_parsing():
    (p,) = arxiv.parse_feed(ARXIV_FEED)
    assert p.arxiv_id == "2009.02647"
    assert p.title == "Utilizing Citation Network Structure to Predict Citation Counts"
    assert p.abstract == "We predict citations."
    assert p.year == 2020 and p.authors == ["Jane Doe", "John Roe"]
    assert p.doi == "10.1016/j.ipm.2021.102500" and p.id == "doi:10.1016/j.ipm.2021.102500"
    assert arxiv.total_results(ARXIV_FEED) == 1234


def test_openalex_work_parsing_rebuilds_abstract():
    work = {
        "id": "https://openalex.org/W123", "doi": "https://doi.org/10.1/ABC", "title": "Citation <i>graphs</i>",
        "publication_year": 2021, "cited_by_count": 7, "language": "en", "type": "article",
        "primary_location": {"source": {"display_name": "Scientometrics"}, "landing_page_url": "https://x.org/a"},
        "authorships": [{"author": {"display_name": "A. Author"}}],
        "abstract_inverted_index": {"world": [1], "Hello": [0], "again": [2]},
        "locations": [{"landing_page_url": "https://arxiv.org/abs/2101.00001v1"}],
        "best_oa_location": {"pdf_url": "https://x.org/a.pdf"},
    }
    p = openalex.to_paper(work)
    assert p.title == "Citation graphs" and p.doi == "10.1/abc" and p.openalex_id == "W123"
    assert p.abstract == "Hello world again"
    assert p.arxiv_id == "2101.00001" and p.venue == "Scientometrics" and p.pdf_url == "https://x.org/a.pdf"


def test_semantic_scholar_parsing():
    d = {"paperId": "abc123", "title": "A paper", "year": 2019, "citationCount": 3,
         "externalIds": {"DOI": "10.1/Y", "ArXiv": "1901.00001"}, "venue": "",
         "publicationVenue": {"name": "NeurIPS"}, "authors": [{"name": "X"}], "abstract": None,
         "openAccessPdf": {"url": ""}, "publicationTypes": ["JournalArticle", "Review"]}
    p = s2.to_paper(d)
    assert p.doi == "10.1/y" and p.arxiv_id == "1901.00001" and p.s2_id == "abc123"
    assert p.venue == "NeurIPS" and p.pdf_url is None and p.type == "JournalArticle, Review"
    assert s2.to_paper({"paperId": None, "title": None}) is None


def test_semantic_scholar_paper_key():
    from conftest import paper
    assert s2.paper_key(paper(s2_id="abc")) == "abc"
    assert s2.paper_key(paper(doi="10.1/x")) == "DOI:10.1/x"
    assert s2.paper_key(paper(arxiv_id="2101.00001")) == "ARXIV:2101.00001"
    assert s2.paper_key(paper()) is None
