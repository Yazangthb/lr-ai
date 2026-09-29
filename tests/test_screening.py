import json

from conftest import paper

from lrai import screening
from lrai.models import read_meta


def write_results(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_batches_are_self_describing_and_skip_filtered_papers(make_run):
    run = make_run('research_questions:\n  - {id: RQ1, text: "How to forecast citations?"}\n')
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(5)]
    papers[0].excluded_reason = "published before 2019"
    todo = screening.pending(papers, "screen")
    paths = screening.write_batches(run, "screen", todo, size=3)
    assert len(todo) == 4 and len(paths) == 2
    meta = read_meta(paths[0])
    assert meta["stage"] == "screen" and meta["output"].endswith("batch_001.result.jsonl")
    assert meta["research_questions"][0]["id"] == "RQ1"
    # numbering continues instead of overwriting earlier batches
    more = screening.write_batches(run, "screen", todo[:1], size=3)
    assert more[0].endswith("batch_003.jsonl")


def test_apply_merges_results_and_reports_missing_and_invalid(make_run):
    run = make_run()
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(3)]
    (batch,) = screening.write_batches(run, "screen", papers, size=10)
    write_results(read_meta(batch)["output"], [
        {"id": "doi:10.1/0", "status": "core", "reason": "direct method", "relevance": 0.9, "short_summary": "S0"},
        {"id": "doi:10.1/1", "status": "Maybe", "reason": "related", "relevance": "0.4"},
        {"id": "doi:10.1/2", "status": "banana"},
        {"id": "doi:10.1/unknown", "status": "core"},
    ])
    rep = screening.apply_results(run, "screen", papers)
    assert (papers[0].status, papers[0].status_reason, papers[0].relevance) == ("core", "direct method", 0.9)
    assert papers[1].status == "skim" and papers[1].relevance == 0.4
    assert papers[2].status is None
    assert rep["unknown_ids"] == ["doi:10.1/unknown"]
    assert rep["missing"] == {"batch_001.jsonl": ["doi:10.1/2"]}
    assert any("banana" in p for p in rep["problems"])


def test_enrich_validates_priority_and_taxonomy(make_run):
    run = make_run("taxonomy:\n  - name: Forecasting\n    children: [Citations]\n")
    p = paper(doi="10.1/a", status="core")
    (batch,) = screening.write_batches(run, "enrich", screening.pending([p], "enrich"), size=10)
    write_results(read_meta(batch)["output"], [{
        "id": p.id, "summary": "Long summary.", "rq_relation": "RQ1", "first_level": "Forecasting",
        "second_level": "Citations", "priority": "HIGH", "code": "https://github.com/x/y"}])
    rep = screening.apply_results(run, "enrich", [p])
    assert (p.summary, p.priority, p.first_level, p.code) == ("Long summary.", "high", "Forecasting",
                                                              "https://github.com/x/y")
    assert rep["problems"] == [] and rep["missing"] == {}
