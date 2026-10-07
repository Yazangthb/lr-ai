import json
import shutil

import pytest
from conftest import paper

from lrai import cli, evaluate, importer
from lrai.dedup import dedup, merge_two
from lrai.run import Run
from lrai.sources import openalex


def read(path, **kw):
    stats = importer.new_stats()
    return importer.read_file(str(path), stats, **kw), stats


# ------------------------------------------------------------------ import

def test_csv_import_detects_columns_and_labels(tmp_path):
    f = tmp_path / "synergy.csv"
    f.write_text("openalex_id,doi,title,abstract,label_included,publication_year\n"
                 "https://openalex.org/W1,https://doi.org/10.1/A,First paper on screening,Abs one,1,2020\n"
                 "https://openalex.org/W2,,Second paper on screening,Abs two,0,2019\n", encoding="utf-8")
    (a, b), stats = read(f)
    assert (a.openalex_id, a.doi, a.year, a.extra["label"]) == ("W1", "10.1/a", 2020, 1)
    assert b.extra["label"] == 0 and b.abstract == "Abs two"
    assert stats["label_column"] == "label_included" and stats["rows"] == 2


def test_skipped_rows_and_unreadable_labels_are_counted(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("doi,title,label_included\n,,1\n,,0\n10.1/a,A paper,maybe\n10.1/b,B paper,1\n", encoding="utf-8")
    papers, stats = read(f)
    assert len(papers) == 2
    assert (stats["skipped"], stats["skipped_included"], stats["unreadable_labels"]) == (2, 1, 1)
    assert "label" not in papers[0].extra and papers[1].extra["label"] == 1


def test_label_column_option(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("title,label_included,label_abstract_screening\nA paper on things,0,1\n", encoding="utf-8")
    (p,), _ = read(f)
    assert p.extra["label"] == 0
    (p,), stats = read(f, label_column="label_abstract_screening")
    assert p.extra["label"] == 1 and stats["label_column"] == "label_abstract_screening"
    with pytest.raises(ValueError):
        read(f, label_column="nope")


def test_semicolon_csv_and_wos_tab_export_with_stray_quotes(tmp_path):
    semi = tmp_path / "excel.csv"
    semi.write_text("Title;DOI;Abstract\nA paper, with commas;10.1/s;Some, text\n", encoding="utf-8")
    (p,), _ = read(semi)
    assert (p.title, p.doi, p.abstract) == ("A paper, with commas", "10.1/s", "Some, text")
    wos = tmp_path / "savedrecs.txt"
    wos.write_text("PT\tTI\tAB\tDI\tPY\n"
                   'J\t"Quoted" start of a title\tAbstract, with, many, commas\t10.1/one\t2020\n'
                   "J\tSecond title\tMore, commas, here\t10.1/two\t2021\n", encoding="utf-8")
    papers, _ = read(wos)
    assert [p.doi for p in papers] == ["10.1/one", "10.1/two"]
    assert papers[0].title.startswith('"Quoted"')


def test_unknown_columns_and_empty_results_are_errors(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read(f)
    ris = tmp_path / "empty.ris"
    ris.write_text("not a ris file\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read(ris)


def test_ids_only_rows_are_filled_from_openalex(tmp_path, monkeypatch):
    f = tmp_path / "x_ids.csv"
    f.write_text("doi,openalex_id,label_included\nhttps://doi.org/10.1/a,https://openalex.org/W1,1\n"
                 "https://doi.org/10.1/b,https://openalex.org/W9,0\n", encoding="utf-8")
    records, _ = read(f)
    assert records[0].title == "" and records[0].id == "doi:10.1/a"
    monkeypatch.setattr(openalex, "get_works", lambda ids: [paper("Fetched title one", openalex_id="W1",
                                                                  abstract="A")])
    # W9 was merged in OpenAlex: found through its DOI instead
    monkeypatch.setattr(openalex, "lookup_dois", lambda dois: [paper("Fetched title two", doi="10.1/b")])
    filled, errors = importer.fill_from_openalex(records)
    assert filled == 2 and not errors
    assert [r.title for r in records] == ["Fetched title one", "Fetched title two"]
    assert records[1].extra["label"] == 0


def test_openalex_errors_do_not_stop_other_batches(monkeypatch):
    from lrai.http import HttpError
    records = [paper("", openalex_id=f"W{i}", doi=f"10.1/{i}") for i in range(60)]

    def flaky(ids):
        if "W0" in ids:
            raise HttpError(503, "boom")
        return [paper(f"Title {i}", openalex_id=i) for i in ids]
    monkeypatch.setattr(openalex, "get_works", flaky)
    monkeypatch.setattr(openalex, "lookup_dois", lambda dois: [])
    filled, errors = importer.fill_from_openalex(records)
    assert filled == 10 and len(errors) == 1


def test_ris_records_without_er_continuations_and_single_spaces(tmp_path):
    ris = tmp_path / "x.ris"
    ris.write_text("TY  - JOUR\nTI  - First RIS paper\nAU  - Doe, J.\nAU  - Roe, K.\nPY  - 2021\n"
                   "AB  - Line one of the abstract\ncontinues on line two\nN1  - label: 1\n"
                   "TY  - JOUR\nTI  - Second paper\nDO  - 10.2/ris\nER  - \n"
                   "TY - JOUR\nTI - Third paper with single spaces\n", encoding="utf-8")
    papers, _ = read(ris)
    assert [p.title for p in papers] == ["First RIS paper", "Second paper", "Third paper with single spaces"]
    first = papers[0]
    assert first.authors == ["Doe, J.", "Roe, K."] and first.year == 2021 and first.extra["label"] == 1
    assert first.abstract == "Line one of the abstract continues on line two"
    assert papers[1].doi == "10.2/ris" and "label" not in papers[1].extra


def test_bibtex_fields_inside_values_are_not_read_as_fields(tmp_path):
    bib = tmp_path / "x.bib"
    bib.write_text('@comment{x}\n'
                   '@article{k1, title = {A {BibTeX} paper, with commas}, author = "Doe, J. and M{\\"o}ller, K.",'
                   ' abstract = {We fit year = 1850 and label = 1 here}, year = 2022, doi = {10.3/BIB},'
                   ' journal = {J. Tests \\& More}, label = {0}}\n'
                   "@misc(k2, title={An arXiv preprint}, eprint={2401.01234}, eprinttype={arxiv})\n",
                   encoding="utf-8")
    (a, b), _ = read(bib)
    assert (a.title, a.year, a.doi, a.venue, a.extra["label"]) == (
        "A BibTeX paper, with commas", 2022, "10.3/bib", "J. Tests & More", 0)
    assert a.authors[1].startswith("Mo") and len(a.authors) == 2
    assert b.arxiv_id == "2401.01234"


# ------------------------------------------------------------------ labels and duplicates

def test_label_survives_merge_and_conflict_is_flagged():
    a = paper("Same paper about screening tools", doi="10.1/x")
    b = paper("Same paper about screening tools", doi="10.1/x")
    a.extra["label"], b.extra["label"] = 0, 1
    m = merge_two(a, b)
    assert m.extra["label"] == 1 and m.extra["label_conflict"]


def test_labelled_records_with_different_ids_are_not_merged():
    a = paper("Randomised trial of drug A versus placebo in adults with hypertension", doi="10.1/a")
    b = paper("Randomised trial of drug B versus placebo in adults with hypertension", doi="10.1/b")
    a.extra["label"], b.extra["label"] = 1, 0
    assert len(dedup([a, b])) == 2
    a2 = paper("Exactly the same title for two different records", doi="10.1/c")
    b2 = paper("Exactly the same title for two different records", doi="10.1/d")
    a2.extra["label"], b2.extra["label"] = 1, 0
    assert len(dedup([a2, b2])) == 2
    # unlabelled (normal reviews): preprint and journal version still merge
    assert len(dedup([paper(a.title, doi="10.1/a"), paper(a.title + "s", doi="10.1/b")])) == 1


def test_same_id_papers_keep_their_own_labels():
    """Two records with the same title-hash id (no identifiers, years far apart) are scored separately."""
    old = paper("Effects of exercise on sleep quality in adults", year=2001)
    new = paper("Effects of exercise on sleep quality in adults", year=2015)
    assert old.id == new.id
    old.extra["label"], old.status = 1, "core"
    new.extra["label"], new.status = 0, "exclude"
    m = evaluate.metrics(evaluate.confusion([old, new], "core"))
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 0, 0, 1)


def test_attach_labels_reports_unmatched_positives():
    run_papers = [paper("A paper LR-AI found about screening", doi="10.1/a"),
                  paper("Another paper LR-AI found about tools", doi="10.1/b")]
    gold = [paper("A paper LR-AI found about screening", doi="10.1/a"),
            paper("An included paper the search never found", doi="10.1/z"),
            paper("An excluded paper the search never found", doi="10.1/y")]
    for g, lab in zip(gold, (1, 1, 0)):
        g.extra["label"] = lab
    rep = evaluate.attach_labels(run_papers, gold)
    assert rep == {"matched": 1, "conflicts": 0, "unmatched_positives": 1, "unmatched_negatives": 1}
    assert run_papers[0].extra["label"] == 1 and "label" not in run_papers[1].extra


# ------------------------------------------------------------------ metrics

def _screened(n_pos=10, n_neg=90):
    papers = []
    for i in range(n_pos + n_neg):
        p = paper(f"Paper number {i} about review automation", doi=f"10.1/{i}")
        p.extra["label"] = 1 if i < n_pos else 0
        papers.append(p)
    return papers


def test_metrics_for_known_confusion():
    papers = _screened()
    for i, p in enumerate(papers):
        if i < 8:
            p.status, p.relevance = "core", 0.9   # 8 TP
        elif i < 10:
            p.status, p.relevance = "exclude", 0.1  # 2 FN
        elif i < 15:
            p.status, p.relevance = "skim", 0.5   # 5 FP under core+skim
        else:
            p.status, p.relevance = "exclude", 0.0
    r = evaluate.evaluate(papers)
    core, wide = r["rules"]["core"], r["rules"]["core+skim"]
    assert (core["tp"], core["fp"], core["fn"], core["tn"]) == (8, 0, 2, 90)
    assert core["recall"] == pytest.approx(0.8) and core["precision"] == 1.0
    assert (wide["tp"], wide["fp"]) == (8, 5)
    assert wide["specificity"] == pytest.approx(85 / 90)
    assert wide["work_saved"] == pytest.approx(87 / 100)
    assert wide["wss"] == pytest.approx(0.87 - 0.2)
    assert len(r["missed"]) == 2
    # 10 positives -> 10 needed: 8 core + 5 skim, then the two missed ones lead the excluded papers
    # (relevance 0.1 > 0.0), so 15 of 100 are read: WSS@95 = 85/100 - 0.05; no ties straddle the cut
    assert r["wss@95"] == pytest.approx(0.80) and r["wss@95_best_case"] == pytest.approx(0.80)


def test_wss95_ceil_boundary_and_ties():
    # 20 positives -> ceil(19) = 19 needed. 19 core (rel 0.9), 1 positive + 79 negatives all "exclude" rel 0.
    papers = _screened(20, 80)
    for i, p in enumerate(papers):
        p.status, p.relevance = ("core", 0.9) if i < 19 else ("exclude", 0.0)
    w = evaluate.wss_at(papers)
    assert w["low"] == pytest.approx(81 / 100 - 0.05) == pytest.approx(w["high"])
    # 21 positives -> ceil(19.95) = 20 needed: the 20th positive sits in an 81-paper tie
    papers = _screened(21, 79)
    for i, p in enumerate(papers):
        p.status, p.relevance = ("core", 0.9) if i < 19 else ("exclude", 0.0)
    w = evaluate.wss_at(papers)
    assert w["high"] == pytest.approx((100 - 20) / 100 - 0.05)   # positive read first in the tie
    assert w["low"] == pytest.approx((100 - 99) / 100 - 0.05)    # 79 negatives read before it


def test_undefined_metrics_are_none_not_zero():
    papers = _screened(0, 5)
    for p in papers:
        p.status = "exclude"
    m = evaluate.evaluate(papers)["rules"]["core"]
    assert m["recall"] is None and m["f1"] is None and m["kappa"] is None and m["precision"] is None
    assert m["specificity"] == 1.0


def test_filtered_papers_count_as_excluded_and_unscreened_are_skipped():
    papers = _screened(2, 2)
    papers[0].status = "core"
    papers[1].excluded_reason = "published before 2019"
    papers[2].status = "exclude"
    r = evaluate.evaluate(papers)
    assert r["unscreened"] == 1 and r["unscreened_included"] == 0
    m = r["rules"]["core"]
    assert (m["tp"], m["fn"], m["tn"], m["n"]) == (1, 1, 1, 3)


def test_kappa_and_fleiss_against_known_values():
    assert evaluate.kappa([(1, 1), (0, 0), (1, 1), (0, 0)]) == 1.0
    assert evaluate.kappa([(1, 0), (0, 1)]) == pytest.approx(-1.0)
    # 2x2 table a=20 b=5 c=10 d=15: po=0.7, pe=0.5 -> kappa 0.4
    pairs = [(1, 1)] * 20 + [(1, 0)] * 5 + [(0, 1)] * 10 + [(0, 0)] * 15
    assert evaluate.kappa(pairs) == pytest.approx(0.4)
    # Fleiss (1971)-style check: 3 raters, perfect agreement on mixed items -> 1; independent check below
    assert evaluate.fleiss([["a", "a", "a"], ["b", "b", "b"]]) == pytest.approx(1.0)
    # 4 items, 2 raters, equals Cohen's kappa computed with pooled marginals (Scott's pi): agreement 3/4,
    # pooled p(a)=p(b)=0.5 -> pe=0.5 -> 0.5
    assert evaluate.fleiss([["a", "a"], ["b", "b"], ["a", "b"], ["b", "b"]]) == pytest.approx(
        (0.75 - (3 / 8) ** 2 - (5 / 8) ** 2) / (1 - (3 / 8) ** 2 - (5 / 8) ** 2))


def test_agreement_ignores_filtered_papers_and_matches_by_identifiers():
    run1 = [paper(f"Paper {i} on screening automation tools", doi=f"10.1/{i}") for i in range(4)]
    run2 = [paper(f"Paper {i} on screening automation tools", openalex_id=f"W{i}") for i in range(4)]
    for p in run2:  # same papers, different id strings (no DOI yet): matched through their titles
        p.doi = None
    run1[3].excluded_reason = run2[3].excluded_reason = "published before 2019"
    for r in (run1, run2):
        r[0].status, r[1].status, r[2].status = "core", "exclude", "skim"
    run2[2].status = "exclude"
    agr = evaluate.agreement([run1, run2])
    assert agr["papers"] == 3                       # the filtered paper does not count
    assert agr["pairs"][0]["agreement"] == pytest.approx(2 / 3)


# ------------------------------------------------------------------ commands

def test_import_and_eval_commands_end_to_end(make_run, tmp_path, capsys, monkeypatch):
    run = make_run()
    f = tmp_path / "labelled.csv"
    rows = ["title,abstract,doi,label_included"] + [
        f"Paper {i} on screening automation tools,Abstract {i},10.9/{i},{1 if i < 3 else 0}" for i in range(10)]
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "complete_metadata", lambda papers, force=False: 0)  # no network in tests
    cli.main(["import", str(f), "--run", run.path, "--no-fetch"])
    out = capsys.readouterr().out
    assert "labels after merging duplicates: 10 papers, 3 included" in out
    papers = run.load()
    for i, p in enumerate(sorted(papers, key=lambda p: p.doi)):
        p.status = "core" if i < 4 else "exclude"
    run.save(papers)
    cli.main(["eval", "--run", run.path])
    out = capsys.readouterr().out
    assert "Labelled papers: 10 (3 included by the reviewers)" in out
    data = json.loads(open(run.file("eval.json"), encoding="utf-8").read())
    assert data["rules"]["core"]["recall"] == 1.0 and data["rules"]["core"]["fp"] == 1
    other = tmp_path / "run2"
    shutil.copytree(run.path, other)
    r2 = Run(str(other), use_cache=False)
    ps = r2.load()
    ps[0].status = "exclude" if ps[0].status == "core" else "core"
    r2.save(ps)
    cli.main(["eval", "--run", run.path, "--compare", str(other)])
    out = capsys.readouterr().out
    assert "agreement 0.900" in out


def test_eval_with_separate_labels_file(make_run, tmp_path, capsys):
    run = make_run()
    papers = [paper(f"Found paper {i} about screening tools", doi=f"10.5/{i}") for i in range(3)]
    for p in papers:
        p.status = "core"
    run.save(papers)
    gold = tmp_path / "gold.csv"
    gold.write_text("doi,label_included\n10.5/0,1\n10.5/1,0\n10.5/99,1\n", encoding="utf-8")
    cli.main(["eval", "--run", run.path, "--labels", str(gold)])
    out = capsys.readouterr().out
    assert "1 included papers in the file are not in the run" in out
    assert "end-to-end recall is lower" in out
