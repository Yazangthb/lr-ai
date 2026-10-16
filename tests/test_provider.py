import glob
import json
import os

import pytest
from conftest import paper

from lrai import cli, http, provider, screening
from lrai.models import read_meta


def _reply(rows, usage=None):
    lines = "\n".join(json.dumps(r) for r in rows)
    return json.dumps({"choices": [{"message": {"content": lines}}],
                       "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 200, "cost": 0.0}})


def test_parse_results_tolerates_fences_arrays_and_stray_text():
    wanted = ["doi:10.1/0", "doi:10.1/1"]
    fenced = '```jsonl\n{"id": "doi:10.1/0", "status": "core"}\nnot json\n{"id": "other", "status": "core"}\n```'
    assert list(provider.parse_results(fenced, wanted)) == ["doi:10.1/0"]
    arr = json.dumps([{"id": "doi:10.1/1", "status": "skim"}, {"id": "doi:10.1/0", "status": "exclude"}])
    assert provider.parse_results(arr, wanted)["doi:10.1/0"]["status"] == "exclude"
    glued = '{"id":"doi:10.1/0","status":"core"}{"id":"doi:10.1/1","status":"exclude","reason":"a {brace}"}'
    assert {k: v["status"] for k, v in provider.parse_results(glued, wanted).items()} == {
        "doi:10.1/0": "core", "doi:10.1/1": "exclude"}


def test_cost_field_is_sent_to_openrouter_only(monkeypatch):
    bodies = []
    monkeypatch.setattr(http, "request", lambda url, *a, body=None, **k: bodies.append(body) or _reply([]))
    provider._chat("https://openrouter.ai/api/v1", "k", "m", "s", "u", 10)
    provider._chat("https://llm.api.cloud.yandex.net/v1", "k", "m", "s", "u", 10)
    assert "usage" in bodies[0] and "usage" not in bodies[1]


def test_prompt_is_the_agent_prompt_without_frontmatter():
    text = provider.screener_prompt()
    assert not text.startswith("---") and "## stage = \"screen\"" in text and "You have no tools" in text


def test_screen_writes_results_retries_missing_once_and_never_stores_the_key(make_run, monkeypatch):
    run = make_run()
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(3)]
    (batch,) = screening.write_batches(run, "screen", papers, size=10)
    calls = []

    def fake_request(url, params=None, *, headers=None, body=None, **kw):
        calls.append(body)
        assert url == "https://openrouter.ai/api/v1/chat/completions"
        assert headers["Authorization"] == "Bearer secret-key-123" and body["temperature"] == 0
        if len(calls) == 1:  # first reply forgets one paper
            return _reply([{"id": "doi:10.1/0", "status": "core", "reason": "r"},
                           {"id": "doi:10.1/1", "status": "exclude", "reason": "r"}])
        assert "doi:10.1/2" in body["messages"][1]["content"] and "doi:10.1/0" not in body["messages"][1]["content"]
        return _reply([{"id": "doi:10.1/2", "status": "skim", "reason": "r"}], {"prompt_tokens": 400,
                                                                               "completion_tokens": 50, "cost": 0.001})

    monkeypatch.setattr(http, "request", fake_request)
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-key-123")
    cli.main(["screen", "--run", run.path, "--model", "some/model:free"])
    out = read_meta(batch)["output"]
    with open(out, encoding="utf-8") as f:
        assert [json.loads(line)["id"] for line in f] == ["doi:10.1/0", "doi:10.1/1", "doi:10.1/2"]
    usage = [json.loads(line) for line in open(os.path.join(run.file("screen"), "usage.jsonl"), encoding="utf-8")]
    assert [u["attempt"] for u in usage] == [1, 2] and usage[1]["cost"] == 0.001
    entry = run.runlog()[-1]
    assert entry["stage"] == "screen" and entry["screened"] == 3 and entry["prompt_tokens"] == 1400
    for path in glob.glob(os.path.join(run.path, "**", "*"), recursive=True):
        if os.path.isfile(path):
            assert "secret-key-123" not in open(path, encoding="utf-8", errors="replace").read(), path
    # a second call skips batches that already have results
    cli.main(["screen", "--run", run.path, "--model", "some/model:free"])
    assert len(calls) == 2


def test_screen_needs_the_key_in_the_environment(make_run, monkeypatch):
    run = make_run()
    screening.write_batches(run, "screen", [paper("A paper on citation forecasting", doi="10.1/0")], size=10)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
        cli.main(["screen", "--run", run.path, "--model", "m"])


def test_apply_logs_estimated_usage(make_run):
    run = make_run()
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(2)]
    run.save(papers)
    (batch,) = screening.write_batches(run, "screen", papers, size=10)
    with open(read_meta(batch)["output"], "w", encoding="utf-8") as f:
        for i in range(2):
            f.write(json.dumps({"id": f"doi:10.1/{i}", "status": "core", "reason": "x" * 40}) + "\n")
    cli.main(["apply", "--run", run.path, "--stage", "screen", "--model", "claude-haiku-5-5"])
    u = run.runlog()[-1]["usage"]
    assert u["batches"] == 1 and u["papers"] == 2 and u["input_tokens_est"] > u["output_tokens_est"] > 0
    assert u["wall_minutes"] >= 0 and u["source"].startswith("estimate")


def test_anthropic_provider_uses_the_official_api_and_logs_tokens_and_cost(make_run, monkeypatch):
    import types

    import anthropic
    run = make_run()
    papers = [paper(f"Paper number {i} on citation forecasting", doi=f"10.1/{i}") for i in range(2)]
    (batch,) = screening.write_batches(run, "screen", papers, size=10)
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            text = "\n".join(json.dumps({"id": f"doi:10.1/{i}", "status": "skim", "reason": "r"}) for i in range(2))
            usage = types.SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0,
                                          cache_read_input_tokens=0)
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], usage=usage,
                                         stop_reason="end_turn")

    class FakeClient:
        def __init__(self, **kw):
            seen["client"] = kw
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://claude-code-proxy.invalid")
    cli.main(["screen", "--run", run.path, "--provider", "anthropic", "--model", "claude-sonnet-4-6"])
    assert seen["client"]["base_url"] == "https://api.anthropic.com"  # never the Claude Code proxy
    assert seen["model"] == "claude-sonnet-4-6" and "temperature" not in seen and "thinking" not in seen
    usage = [json.loads(x) for x in open(os.path.join(run.file("screen"), "usage.jsonl"), encoding="utf-8")]
    assert usage[0]["returned"] == 2 and usage[0]["stop_reason"] == "end_turn"
    assert usage[0]["cost"] == pytest.approx((1000 * 3.0 + 200 * 15.0) / 1e6)
    with open(read_meta(batch)["output"], encoding="utf-8") as f:
        assert len(f.readlines()) == 2
