import pytest

import json

from conftest import paper

from lrai import cli, screening
from lrai.models import read_meta


def _screen_batch(run, papers, rows):
    run.save(papers)
    (batch,) = screening.write_batches(run, "screen", papers, size=10)
    with open(read_meta(batch)["output"], "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_every_log_entry_records_version_commit_and_config_hash(make_run):
    run = make_run()
    run.log("seed", "first step")
    with open(run.file("config.yaml"), "a", encoding="utf-8") as f:
        f.write("\n# edited\n")
    run.log("search", "second step")
    first, second = run.runlog()
    for entry in (first, second):
        prov = entry["provenance"]
        assert prov["lrai"] and len(prov["config_sha"]) == 12 and "commit" in prov
    assert first["provenance"]["config_sha"] != second["provenance"]["config_sha"]


def test_apply_records_the_screening_model_per_paper_and_in_the_log(make_run, capsys):
    run = make_run()
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(2)]
    _screen_batch(run, papers, [{"id": "doi:10.1/0", "status": "core", "reason": "r"},
                                {"id": "doi:10.1/1", "status": "exclude", "reason": "r"}])
    cli.main(["apply", "--stage", "screen", "--run", run.path, "--model", "claude-haiku-5-5"])
    assert "no --model given" not in capsys.readouterr().out
    assert {p.extra.get("screen_model") for p in run.load()} == {"claude-haiku-5-5"}
    assert run.runlog()[-1]["model"] == "claude-haiku-5-5"
    cli.main(["status", "--run", run.path])
    out = capsys.readouterr().out
    assert "screen model: claude-haiku-5-5 (2 papers)" in out and "LR-AI:" in out


def test_apply_without_model_marks_results_unknown_and_warns(make_run, capsys):
    run = make_run()
    papers = [paper("Paper number 0 on citation forecasting", doi="10.1/0")]
    _screen_batch(run, papers, [{"id": "doi:10.1/0", "status": "skim", "reason": "r"}])
    cli.main(["apply", "--stage", "screen", "--run", run.path])
    assert "no --model given" in capsys.readouterr().out
    assert run.load()[0].extra["screen_model"] == "unknown"
    assert run.runlog()[-1]["model"] == "unknown"


def test_reapply_without_model_keeps_the_recorded_model(make_run):
    run = make_run()
    papers = [paper("Paper number 0 on citation forecasting", doi="10.1/0")]
    _screen_batch(run, papers, [{"id": "doi:10.1/0", "status": "core", "reason": "r"}])
    cli.main(["apply", "--stage", "screen", "--run", run.path, "--model", "claude-haiku-5-5"])
    cli.main(["apply", "--stage", "screen", "--run", run.path, "--all"])
    assert run.load()[0].extra["screen_model"] == "claude-haiku-5-5"


def test_rejected_results_get_no_model_and_noop_apply_logs_no_model(make_run, capsys):
    run = make_run()
    papers = [paper("Paper number 0 on citation forecasting", doi="10.1/0")]
    _screen_batch(run, papers, [{"id": "doi:10.1/0", "status": "banana"}])
    cli.main(["apply", "--stage", "screen", "--run", run.path])
    assert "screen_model" not in run.load()[0].extra
    assert run.runlog()[-1]["model"] is None and "no --model given" not in capsys.readouterr().out


def test_status_handles_old_and_damaged_logs_and_mixed_models(make_run, capsys):
    run = make_run()
    a = paper("Paper number 0 on citation forecasting", doi="10.1/0")
    b = paper("Paper number 1 on citation forecasting", doi="10.1/1")
    a.status, b.status = "core", "skim"
    a.extra["screen_model"], b.extra["screen_model"] = "claude-haiku-5-5", "unknown"
    b.extra["enrich_model"] = "claude-sonnet-5-5"
    run.save([a, b])
    with open(run.file("runlog.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"time": "2026-10-01T10:00:00", "stage": "seed", "summary": "old entry"}\n{"time": "2026-10-0')
    cli.main(["status", "--run", run.path])
    out = capsys.readouterr().out
    assert "screen model: claude-haiku-5-5 (1 papers), unknown (1 papers)" in out
    assert "enrich model: claude-sonnet-5-5 (1 papers)" in out
    assert "logged steps: 2026-10-01T10:00:00" in out


def test_config_hash_ignores_line_endings(make_run, tmp_path):
    run = make_run()
    data = open(run.file("config.yaml"), "rb").read().replace(b"\r\n", b"\n")  # write_text gives CRLF on Windows
    open(run.file("config.yaml"), "wb").write(data)
    lf = run.provenance()["config_sha"]
    open(run.file("config.yaml"), "wb").write(data.replace(b"\n", b"\r\n"))
    assert run.provenance()["config_sha"] == lf


@pytest.mark.real_git
def test_engine_commit_is_none_without_its_own_git_checkout(monkeypatch, tmp_path):
    import subprocess

    from lrai import run as runmod
    runmod.engine_commit.cache_clear()

    def no_git(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(subprocess, "run", no_git)
    assert runmod.engine_commit() is None
    runmod.engine_commit.cache_clear()
    monkeypatch.setattr(runmod, "_git", lambda *a: str(tmp_path) if a[0] == "rev-parse" and "--show-toplevel" in a else "abc")
    assert runmod.engine_commit() is None  # an enclosing repository is not LR-AI's own
    runmod.engine_commit.cache_clear()
