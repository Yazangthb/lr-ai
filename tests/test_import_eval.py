import json

import pytest
from conftest import paper

from lrai import cli, evaluate, importer
from lrai.dedup import merge_two
from lrai.sources import openalex


def test_csv_import_detects_columns_and_labels(tmp_path):
    f = tmp_path / "synergy.csv"
    f.write_text("openalex_id,doi,title,abstract,label_included,publication_year\n"
                 "https://openalex.org/W1,https://doi.org/10.1/A,First paper on screening,Abs one,1,2020\n"
                 "https://openalex.org/W2,,Second paper on screening,Abs two,0,2019\n", encoding="utf-8")
    a, b = importer.read_file(str(f))
    assert (a.openalex_id, a.doi, a.year, a.extra["label"]) == ("W1", "10.1/a", 2020, 1)
    assert b.extra["label"] == 0 and b.abstract == "Abs two"


def test_ids_only_rows_are_filled_from_openalex(tmp_path, monkeypatch):
    f = tmp_path / "x_ids.csv"
    f.write_text("doi,openalex_id,label_included\nhttps://doi.org/10.1/a,https://openalex.org/W1,1\n"
                 "https://doi.org/10.1/b,https://openalex.org/W9,0\n", encoding="utf-8")
    records = importer.read_file(str(f))
    assert records[0].title == "" and records[0].id == "doi:10.1/a"
    monkeypatch.setattr(openalex, "get_works", lambda ids: [paper("Fetched title one", openalex_id="W1",
                                                                  abstract="A")])
    # W9 was merged in OpenAlex: found through its DOI instead
    monkeypatch.setattr(openalex, "lookup_dois", lambda dois: [paper("Fetched title two", doi="10.1/b")])
    filled, errors = importer.fill_from_openalex(records)
    assert filled == 2 and not errors
    assert [r.title for r in records] == ["Fetched title one", "Fetched title two"]
    assert records[1].extra["label"] == 0


def test_ris_and_bibtex(tmp_path):
    ris = tmp_path / "x.ris"
    ris.write_text("TY  - JOUR\nTI  - A RIS paper about reviews\nAU  - Doe, J.\nAU  - Roe, K.\nPY  - 2021\n"
                   "DO  - 10.2/ris\nAB  - Abstract here\nN1  - label: 1\nER  - \n", encoding="utf-8")
    (p,) = importer.read_file(str(ris))
    assert (p.title, p.authors, p.year, p.doi, p.extra["label"]) == (
        "A RIS paper about reviews", ["Doe, J.", "Roe, K."], 2021, "10.2/ris", 1)
    bib = tmp_path / "x.bib"
    bib.write_text('@comment{x}\n@article{k1, title = {A {BibTeX} paper, with commas}, author = "Doe, J. and Roe, K.",'
                   ' year = 2022, doi = {10.3/BIB}, journal = {J. Tests}}\n'
                   "@misc{k2, title={An arXiv preprint}, eprint={2401.01234}, archivePrefix={arXiv}}\n",
                   encoding="utf-8")
    a, b = importer.read_file(str(bib))
    assert (a.title, a.authors, a.year, a.doi, a.venue) == (
        "A BibTeX paper, with commas", ["Doe, J.", "Roe, K."], 2022, "10.3/bib", "J. Tests")
    assert b.arxiv_id == "2401.01234"


def test_unknown_columns_are_rejected(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        importer.read_file(str(f))


def test_label_survives_merge_with_excluded_duplicate():
    a = paper("Same paper about screening tools", doi="10.1/x")
    b = paper("Same paper about screening tools", doi="10.1/x")
    a.extra["label"], b.extra["label"] = 0, 1
    assert merge_two(a, b).extra["label"] == 1


def _screened(n_pos=10, n_neg=90):
    papers, labels = [], {}
    for i in range(n_pos + n_neg):
        p = paper(f"Paper number {i} about review automation", doi=f"10.1/{i}")
        labels[p.id] = 1 if i < n_pos else 0
        papers.append(p)
    return papers, labels


def test_metrics_for_known_confusion():
    papers, labels = _screened()
    for i, p in enumerate(papers):
        if i < 8:
            p.status, p.relevance = "core", 0.9   # 8 TP
        elif i < 10:
            p.status, p.relevance = "exclude", 0.1  # 2 FN
        elif i < 15:
            p.status, p.relevance = "skim", 0.5   # 5 FP under core+skim
        else:
            p.status, p.relevance = "exclude", 0.0
    r = evaluate.evaluate(papers, labels)
    core, wide = r["rules"]["core"], r["rules"]["core+skim"]
    assert (core["tp"], core["fp"], core["fn"], core["tn"]) == (8, 0, 2, 90)
    assert core["recall"] == pytest.approx(0.8) and core["precision"] == 1.0
    assert (wide["tp"], wide["fp"]) == (8, 5)
    assert wide["specificity"] == pytest.approx(85 / 90)
    assert wide["work_saved"] == pytest.approx(87 / 100)
    assert wide["wss"] == pytest.approx(0.87 - 0.2)
    assert len(r["missed"]) == 2
    # 95% of 10 positives = 10 needed: 8 core + 5 skim, then the two missed ones lead the excluded papers
    # (relevance 0.1 > 0.0), so 15 of 100 are read: WSS@95 = 85/100 - 0.05
    assert r["wss@95"] == pytest.approx(0.80)


def test_filtered_papers_count_as_excluded_and_unscreened_are_skipped():
    papers, labels = _screened(2, 2)
    papers[0].status = "core"
    papers[1].excluded_reason = "published before 2019"
    papers[2].status = "exclude"
    r = evaluate.evaluate(papers, labels)
    assert r["unscreened"] == 1
    m = r["rules"]["core"]
    assert (m["tp"], m["fn"], m["tn"], m["n"]) == (1, 1, 1, 3)


def test_kappa_and_fleiss():
    assert evaluate.kappa([(1, 1), (0, 0), (1, 1), (0, 0)]) == 1.0
    assert evaluate.kappa([(1, 0), (0, 1)]) == pytest.approx(-1.0)
    assert evaluate.fleiss([["a", "a"], ["b", "b"], ["a", "a"]]) == 1.0


def test_import_and_eval_commands_end_to_end(make_run, tmp_path, capsys, monkeypatch):
    run = make_run()
    f = tmp_path / "labelled.csv"
    rows = ["title,abstract,doi,label_included"] + [
        f"Paper {i} on screening automation tools,Abstract {i},10.9/{i},{1 if i < 3 else 0}" for i in range(10)]
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "complete_metadata", lambda papers, force=False: 0)  # no network in tests
    cli.main(["import", str(f), "--run", run.path, "--no-fetch"])
    papers = run.load()
    assert len(papers) == 10 and sum(p.extra["label"] for p in papers) == 3
    for i, p in enumerate(sorted(papers, key=lambda p: p.doi)):
        p.status = "core" if i < 4 else "exclude"
    run.save(papers)
    cli.main(["eval", "--run", run.path])
    out = capsys.readouterr().out
    assert "Labelled papers: 10 (3 included by the reviewers)" in out
    data = json.loads(open(run.file("eval.json"), encoding="utf-8").read())
    assert data["rules"]["core"]["recall"] == 1.0 and data["rules"]["core"]["fp"] == 1
    # a second run with one disagreement
    import shutil
    other = tmp_path / "run2"
    shutil.copytree(run.path, other)
    from lrai.run import Run
    r2 = Run(str(other), use_cache=False)
    ps = r2.load()
    ps[0].status = "exclude" if ps[0].status == "core" else "core"
    r2.save(ps)
    cli.main(["eval", "--run", run.path, "--compare", str(other)])
    out = capsys.readouterr().out
    assert "agreement 0.900" in out
