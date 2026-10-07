import pytest
from conftest import paper

from lrai import cli, evaluate, filters


def test_block_list_beats_protection_and_matches_all_id_kinds():
    review = paper("A systematic review of fault prediction", doi="10.1109/tse.2011.103", found_via=["seed:known"])
    pre = paper("Some preprint", arxiv_id="2401.01234")
    oa = paper("Some OpenAlex record", openalex_id="W123")
    titled = paper("A Systematic Review of Things", year=2020)
    ok = paper("An unrelated study of fault prediction", doi="10.1/ok")
    f = {"block": ["https://doi.org/10.1109/TSE.2011.103", "arXiv:2401.01234v2", "https://openalex.org/W123",
                   "a systematic review of things"]}
    counts = filters.apply([review, pre, oa, titled, ok], f)
    assert [p.excluded_reason for p in (review, pre, oa, titled)] == ["blocked"] * 4
    assert ok.excluded_reason is None and counts == {"blocked": 4}


def test_blocked_paper_is_never_snowballed(make_run, monkeypatch):
    run = make_run('filters:\n  block: ["10.1/review"]\n')
    review = paper("The review being reproduced", doi="10.1/review")
    other = paper("A normal seed paper about faults", doi="10.1/seed")
    run.save([review, other])
    seen = []

    def fake_round(frontier, *a, **k):
        seen.extend(p.doi for p in frontier)
        return [], {"references": 0, "citations": 0, "backend": {}, "unresolved": [], "failed": [], "errors": []}
    monkeypatch.setattr(cli, "snowball_round", fake_round)
    monkeypatch.setattr(cli, "complete_metadata", lambda papers, force=False: 0)
    cli.main(["snowball", "--run", run.path])  # filter not run: the guard in snowball itself must hold
    assert seen == ["10.1/seed"]


def _gold(n_inc, n_exc):
    g = []
    for i in range(n_inc + n_exc):
        p = paper(f"Gold record {i} on fault prediction models", doi=f"10.9/{i}")
        p.extra["label"] = 1 if i < n_inc else 0
        g.append(p)
    return g


def test_coverage_counts_recall_at_n_stages_and_extras():
    gold = _gold(4, 6)                       # 4 included, 6 screened-and-excluded in the review
    run = []
    # included 0: found by search, core; 1: snowballing, skim; 2: found but screened out; 3: never found
    for i, (status, rel, via) in enumerate([("core", 0.9, ["search:openalex:q1"]),
                                            ("skim", 0.4, ["backward:doi:10.9/0"]),
                                            ("exclude", 0.1, ["search:arxiv:q1", "forward:x"])]):
        p = paper(f"Gold record {i} on fault prediction models", doi=f"10.9/{i}", found_via=via)
        p.status, p.relevance = status, rel
        run.append(p)
    excl = paper("Gold record 5 on fault prediction models", doi="10.9/5", found_via=["search:openalex:q1"])
    excl.status, excl.relevance = "exclude", 0.0
    extra = paper("A relevant paper the review never screened", doi="10.8/new", found_via=["forward:y"])
    extra.status, extra.relevance = "core", 0.8
    filtered = paper("An old paper outside the date range", doi="10.8/old", found_via=["search:openalex:q1"])
    filtered.excluded_reason = "published after 2010"
    run += [excl, extra, filtered]
    r = evaluate.coverage(run, gold, at=[2, 3, 10])
    assert (r["review_included"], r["review_screened"], r["found_in_run"], r["kept_by_lrai"]) == (4, 10, 3, 2)
    assert r["recall_run"] == pytest.approx(0.75) and r["recall_included_list"] == pytest.approx(0.5)
    assert r["run_included"] == 3 and r["precision_vs_review"] == pytest.approx(2 / 3)
    # ranking: gold0 (core .9), extra (core .8), gold1 (skim), gold2 (excl .1), gold5 (excl 0), filtered
    assert r["recall_at"]["2"] == pytest.approx(0.25)
    assert r["recall_at"]["3"] == pytest.approx(0.5)
    assert r["recall_at"]["10"] == pytest.approx(0.75)
    assert r["overlap_with_review_screened"] == pytest.approx(4 / 10)
    assert r["found_by_stage"] == {"search only": 1, "snowballing only": 1, "search and snowballing": 1}
    assert [m["why"] for m in r["missed"]] == ["screened out: ", "never found"]
    assert r["extras_count"] == 1 and r["extras"][0]["id"] == "doi:10.8/new"


def test_coverage_command(make_run, tmp_path, capsys):
    run = make_run()
    p = paper("Gold record 0 on fault prediction models", doi="10.9/0", found_via=["search:openalex:q1"])
    p.status = "core"
    run.save([p])
    labels = tmp_path / "review.csv"
    labels.write_text("doi,label_included\n10.9/0,1\n10.9/1,1\n10.9/2,0\n", encoding="utf-8")
    cli.main(["coverage", "--run", run.path, "--labels", str(labels), "--at", "5"])
    out = capsys.readouterr().out
    assert "Review: 2 included of 3 screened records" in out
    assert "kept in LR-AI's included list:     1 (0.500)" in out
    assert "top 5: 0.500" in out
