from conftest import paper

from lrai import cli, evaluate, screening


def _screened(n_core, n_skim, n_excl=0):
    papers = []
    for i in range(n_core + n_skim + n_excl):
        p = paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}")
        p.status = "core" if i < n_core else "skim" if i < n_core + n_skim else "exclude"
        p.relevance = 1 - i / 100
        papers.append(p)
    return papers


def test_limit_keeps_core_first_then_relevance_and_marks_the_rest():
    papers = _screened(2, 4, 1)
    papers[3].relevance = 0.99  # a high-relevance skim still comes after every core paper
    r = screening.limit_list(papers, 4)
    assert r == {"screened_in": 6, "list": 4, "core": 2, "skim": 2, "beyond_limit": 2, "max_list": 4}
    assert [p.id for p in papers if p.included] == ["doi:10.1/0", "doi:10.1/1", "doi:10.1/2", "doi:10.1/3"]
    assert papers[4].extra["beyond_list_limit"] and papers[4].screened_in and not papers[4].included
    assert papers[3].extra["list_rank"] == 3 and "list_rank" not in papers[6].extra  # excluded papers get no rank
    screening.limit_list(papers, None)  # no limit: everything screened in is back
    assert sum(p.included for p in papers) == 6 and not any("beyond_list_limit" in p.extra for p in papers)


def test_coverage_reports_studies_cut_by_the_limit():
    papers = _screened(1, 2)
    screening.limit_list(papers, 1)
    gold = [paper("Paper number 2 on citation forecasting", doi="10.1/2")]
    gold[0].extra["label"] = 1
    r = evaluate.coverage(papers, gold)
    assert r["found_in_run"] == 1 and r["kept_by_lrai"] == 0 and r["run_included"] == 1
    assert r["missed"][0]["why"] == "beyond the reading-list limit" and r["studies"][0]["beyond_list_limit"]


def test_finalize_command_uses_the_config_limit_and_filter_keeps_it_current(make_run):
    run = make_run("screening:\n  max_list: 3\n")
    papers = _screened(2, 3)
    run.save(papers)
    cli.main(["finalize", "--run", run.path])
    assert sum(p.included for p in run.load()) == 3 and run.runlog()[-1]["stage"] == "finalize"
    cli.main(["filter", "--run", run.path])  # filters change nothing here, but the cut is re-applied
    assert sum(p.included for p in run.load()) == 3
    cli.main(["finalize", "--run", run.path, "--max", "0"])
    assert sum(p.included for p in run.load()) == 5


def test_snowball_frontier_ignores_the_reading_list_cut():
    papers = _screened(1, 2)
    screening.limit_list(papers, 1)
    assert sum(p.screened_in for p in papers) == 3 and sum(p.included for p in papers) == 1
