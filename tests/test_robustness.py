"""Regression tests for the code-review findings: network edge cases, secrets, odd input."""
import http.client
import io
import json
import urllib.error

import pytest
from conftest import REAL_REQUEST, paper

from lrai import config, dedup, filters, http as lrhttp, layout, resolve, screening
from lrai.config import DEFAULTS
from lrai.models import Paper, norm_arxiv, read_jsonl, read_meta, write_jsonl
from lrai.sources import arxiv


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_net(monkeypatch):
    """Script urlopen's behaviour: each item is an exception to raise or bytes to return."""
    script: list = []
    sleeps: list = []

    def urlopen(req, timeout=None):
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeResponse(item)

    monkeypatch.setattr(lrhttp.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(lrhttp.time, "sleep", lambda s: sleeps.append(s))
    return script, sleeps


def http_error(code, body, headers=None):
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(body.encode()))


def test_truncated_body_and_ssl_errors_are_retried(fake_net):
    script, _ = fake_net
    script += [http.client.IncompleteRead(b"par"), OSError("ssl: bad record"), b'{"ok": 1}']
    assert REAL_REQUEST("https://api.example.org/x") == '{"ok": 1}'


def test_retry_hint_in_body_is_honoured(fake_net):
    script, sleeps = fake_net
    script += [http_error(429, '{"error": "Please retry in 37s, or use a free API key"}'), b"{}"]
    assert REAL_REQUEST("https://api.openalex.org/works") == "{}"
    assert sleeps[-1] == 38  # waited as told instead of giving up


def test_api_key_errors_get_one_retry_then_fail_persistently(fake_net):
    script, _ = fake_net
    body = '{"message": "Anonymous search is paused, use a free API key"}'
    script += [http_error(503, body), http_error(503, body)]
    with pytest.raises(lrhttp.HttpError) as e:
        REAL_REQUEST("https://api.openalex.org/works")
    assert e.value.persistent


def test_error_messages_never_contain_api_keys_or_emails(fake_net):
    script, _ = fake_net
    script += [http_error(400, "bad request")]
    with pytest.raises(lrhttp.HttpError) as e:
        REAL_REQUEST("https://api.openalex.org/works", {"api_key": "SECRET123", "mailto": "me@uni.edu"})
    assert "SECRET123" not in str(e.value) and "me@uni.edu" not in str(e.value)


def test_unwritable_cache_does_not_lose_the_response(fake_net, monkeypatch, tmp_path):
    script, _ = fake_net
    script += [b'{"ok": 2}']
    lrhttp.set_cache_dir(str(tmp_path))

    def locked(*a, **k):
        raise PermissionError("locked by sync client")

    monkeypatch.setattr(lrhttp, "replace_file", locked)
    assert REAL_REQUEST("https://api.example.org/y") == '{"ok": 2}'


def test_merging_keeps_manual_decisions_from_either_record():
    manual = paper("Graph neural networks for citation forecasting", arxiv_id="2301.00001", venue="arXiv",
                   status="exclude", status_reason="off topic", extra={"manual": ["status"]})
    llm = paper("Graph neural networks for citation forecasting", doi="10.1/pub", venue="KDD",
                status="core", status_reason="llm says yes")
    (m,) = dedup.dedup([manual, llm])
    assert (m.status, m.status_reason, m.extra["manual"]) == ("exclude", "off topic", ["status"])


def test_lone_surrogates_do_not_break_saving(tmp_path):
    p = Paper(title="Bad \ud835 title", abstract="x \udc00 y").normalize()
    path = str(tmp_path / "p.jsonl")
    write_jsonl(path, [p])
    assert read_jsonl(path)[0].title.startswith("Bad")


def test_math_in_titles_is_not_mistaken_for_markup():
    assert paper("Bounds for all a<b and c>d in graphs").title == "Bounds for all a<b and c>d in graphs"
    assert paper('Detecting <i>E. coli</i> in <span class="x">water</span>').title == "Detecting E. coli in water"


def test_non_latin_titles_get_distinct_ids():
    assert paper("图神经网络的引文预测").id != paper("基于引文网络的影响力预测").id


def test_arxiv_ids_are_validated():
    assert norm_arxiv("https://arxiv.org/html/2401.01234v2") == "2401.01234"
    assert norm_arxiv("https://arxiv.org/list/cs.LG/recent") is None


def test_unreadable_arxiv_page_is_retried(monkeypatch):
    good = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
            '<opensearch:totalResults>1</opensearch:totalResults><entry><id>http://arxiv.org/abs/2101.00001v1</id>'
            '<published>2021-01-01</published><title>T</title><summary>S</summary></entry></feed>')
    pages = ["<html>busy</html>", good]
    monkeypatch.setattr(arxiv, "request", lambda *a, **k: pages.pop(0))
    monkeypatch.setattr(arxiv.time, "sleep", lambda s: None)
    papers, total = arxiv.search("graph", limit=5)
    assert total == 1 and papers[0].arxiv_id == "2101.00001"


def test_brackets_in_folder_names(make_run, tmp_path):
    run = make_run()
    import os
    bracketed = tmp_path / "Reviews [2025]"
    os.rename(run.path, bracketed)
    from lrai.run import Run
    run = Run(str(bracketed), use_cache=False)
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(2)]
    (batch,) = screening.write_batches(run, "screen", papers, size=10)
    with open(read_meta(batch)["output"], "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": papers[0].id, "status": "core"}) + "\n")
    rep = screening.apply_results(run, "screen", papers)
    assert rep["applied"] == 1 and papers[0].status == "core"
    assert screening.write_batches(run, "screen", papers[1:], size=10)[0].endswith("batch_002.jsonl")


def test_symbol_terms_match():
    f = dict(DEFAULTS["filters"])
    p = paper("A fast parser written in C++ for the .NET runtime")
    assert filters.exclusion_reason(p, {**f, "require_any": ["c++"]}, year_now=2026) is None
    assert filters.exclusion_reason(p, {**f, "exclude_any": [".net"]}, year_now=2026) == "mentions '.net'"


def test_scalar_lists_in_yaml_are_wrapped(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("filters:\n  languages: en\n  exclude_types: editorial\nseed:\n  papers: 2101.00010\n",
                    encoding="utf-8")
    cfg = config.load(str(path))
    assert cfg["filters"]["languages"] == ["en"] and cfg["filters"]["exclude_types"] == ["editorial"]
    found, errors = resolve.resolve(cfg["seed"]["papers"], "seed:known")  # unquoted id became a float
    assert found == [] and "quotes" in errors[0]


def test_result_rows_with_lists_and_bom(make_run):
    run = make_run()
    p = paper(doi="10.1/a")
    (batch,) = screening.write_batches(run, "screen", [p], size=10)
    row = {"id": p.id, "status": "skim", "reason": ["related", "background"], "short_summary": 42}
    with open(read_meta(batch)["output"], "w", encoding="utf-8-sig") as f:  # BOM, as Notepad writes it
        f.write(json.dumps(row) + "\n")
    rep = screening.apply_results(run, "screen", [p])
    assert rep["bad_lines"] == [] and (p.status, p.status_reason, p.short_summary) == (
        "skim", "related; background", "42")


def test_method_tab_says_all_for_uncapped_citations(make_run):
    run = make_run("snowball:\n  max_citations: null\n")
    stats = {"identified": {}, "identified_total": 0, "unique": 0, "duplicates": 0, "filtered_out": 0,
             "filter_reasons": {}, "screened": 0, "awaiting_screening": 0, "excluded_at_screening": 0,
             "core": 0, "skim": 0, "enriched": 0}
    tab = layout.method_tab(run.config, stats)
    text = " ".join(str(v) for row in tab.rows for v in row)
    assert "all citing papers" in text and "None" not in text
