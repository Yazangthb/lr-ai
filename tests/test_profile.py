from lrai import cli
from lrai import config as cfgmod
from lrai.config import render_template


def test_wide_profile_changes_only_its_keys_and_keeps_comments():
    text = render_template("digital twins", "2026-10-11")
    text = text.replace("  require_any: []", '  require_any: ["digital twin*"]')
    wide = cfgmod.apply_profile(text, "wide")
    import yaml
    cfg = yaml.safe_load(wide)
    assert cfg["profile"] == "wide"
    assert cfg["filters"]["min_hits"] == 1 and cfg["snowball"]["max_references"] is None
    assert cfg["snowball"]["from"] == "included" and cfg["snowball"]["max_citations"] == 200
    assert cfg["search"]["per_query"] == 3000 and cfg["seed"]["per_query"] == 30
    assert cfg["filters"]["require_any"] == ["digital twin*"]  # topic filters untouched
    assert "# snowballed papers must be linked from at least this many papers" in wide
    back = yaml.safe_load(cfgmod.apply_profile(wide, "standard"))
    assert back["filters"]["min_hits"] == 0 and back["snowball"]["max_references"] == 200
    assert back["profile"] == "standard"


def test_extra_wide_switches_the_keyword_rule_off_and_keeps_the_keywords():
    import yaml
    text = render_template("digital twins", "2026-10-13").replace(
        "  snowball_require_any: []", '  snowball_require_any: ["*twin*"]')
    extra = yaml.safe_load(cfgmod.apply_profile(text, "extra-wide"))
    assert extra["profile"] == "extra-wide" and extra["snowball"]["max_citations"] == 500
    assert extra["search"]["per_query"] == 3000 and extra["filters"]["min_hits"] == 1
    assert extra["filters"]["snowball_keyword_rule"] is False
    assert extra["filters"]["snowball_require_any"] == ["*twin*"]  # the list stays for the other profiles
    back = yaml.safe_load(cfgmod.apply_profile(cfgmod.apply_profile(text, "extra-wide"), "wide"))
    assert back["filters"]["snowball_keyword_rule"] is True and back["snowball"]["max_citations"] == 200


def test_snowball_keyword_rule_off_keeps_snowballed_papers_without_the_keywords():
    from conftest import paper
    from lrai import filters
    snowballed = paper("A survey of anomaly detection methods", found_via=["backward:doi:10.1/x"], round=1)
    f = {"snowball_require_any": ["*twin*"]}
    filters.apply([snowballed], f)
    assert snowballed.excluded_reason == "snowballed, none of the required keywords"
    filters.apply([snowballed], {**f, "snowball_keyword_rule": False})
    assert snowballed.excluded_reason is None


def test_set_values_appends_missing_keys_and_sections():
    text = "topic: x\nfilters:\n  year_min: 2020\nscreening:\n  batch_size: 25\n"
    out = cfgmod.set_values(text, "filters", {"min_hits": 1})
    out = cfgmod.set_values(out, "snowball", {"from": "core"})
    import yaml
    cfg = yaml.safe_load(out)
    assert cfg["filters"] == {"year_min": 2020, "min_hits": 1} and cfg["screening"]["batch_size"] == 25
    assert cfg["snowball"]["from"] == "core"


def test_profile_command_and_init_option(make_run, tmp_path, capsys):
    run = make_run()
    cli.main(["profile", "wide", "--run", run.path])
    assert "Applied profile 'wide'" in capsys.readouterr().out
    assert run.runlog()[-1]["profile"] == "wide"
    cfg = cfgmod.load(run.file("config.yaml"))
    assert cfg["filters"]["min_hits"] == 1
    cli.main(["init", "wide topic", "--root", str(tmp_path / "runs"), "--profile", "wide"])
    (folder,) = (tmp_path / "runs").iterdir()
    assert cfgmod.load(str(folder / "config.yaml"))["snowball"]["max_citations"] == 200
