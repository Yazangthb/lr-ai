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
    assert r == {"screened_in": 6, "list": 4, "core": 2, "skim": 2, "beyond_limit": 2, "max_list": 4,
                 "rank_method": "relevance"}
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


def test_links_ranking_puts_papers_linked_to_more_included_papers_first():
    papers = _screened(0, 4)
    parent_a, parent_b, lonely, linked = papers
    parent_a.relevance, parent_b.relevance, lonely.relevance, linked.relevance = 0.2, 0.2, 0.9, 0.5
    linked.found_via = [f"backward:{parent_a.id}", f"forward:doi:{parent_b.doi}", "backward:doi:10.9/not-included"]
    assert screening.link_counts(papers)[linked.id] == 2  # the paper outside the list does not count
    screening.limit_list(papers, 1, "links")
    assert [p.id for p in papers if p.included] == [linked.id]
    screening.limit_list(papers, 1, "relevance")
    assert [p.id for p in papers if p.included] == [lonely.id]


def test_rank_command_saves_the_method_and_finalize_uses_it(make_run):
    import yaml
    run = make_run()
    papers = _screened(0, 2)
    papers[1].relevance = 0.1
    papers[1].found_via = [f"forward:{papers[0].id}"]
    run.save(papers)
    cli.main(["rank", "--run", run.path, "--method", "relevance"])
    assert yaml.safe_load(open(run.file("config.yaml"), encoding="utf-8"))["screening"]["rank"] == "relevance"
    assert all(p.included for p in run.load())  # ranking alone does not cut
    cli.main(["finalize", "--run", run.path, "--max", "1"])
    assert [p.id for p in run.load() if p.included] == [papers[0].id]
    cli.main(["rank", "--run", run.path, "--method", "links"])  # after finalize, re-ranking keeps a cut
    assert run.runlog()[-1]["rank_method"] == "links"
    assert yaml.safe_load(open(run.file("config.yaml"), encoding="utf-8"))["screening"]["rank"] == "links"
