"""The built-in OpenAlex key, and the notice shown when OpenAlex rate-limits us."""
import pytest

from lrai import cli, http as lrhttp
from lrai.http import HttpError
from lrai.sources import openalex


def capture_params(monkeypatch):
    seen = {}

    def fake_request(url, params=None, **kw):
        seen.update(params or {})
        return '{"results": []}'
    monkeypatch.setattr(lrhttp, "request", fake_request)
    return seen


def test_builtin_key_is_used_without_a_personal_one(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    seen = capture_params(monkeypatch)
    openalex._get("/works", {})
    assert seen["api_key"] == openalex.BUILTIN_API_KEY


def test_personal_key_wins(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "MINE")
    seen = capture_params(monkeypatch)
    openalex._get("/works", {})
    assert seen["api_key"] == "MINE"


def rate_limited(monkeypatch, message="Rate limit exceeded — Insufficient budget"):
    def refuse(*a, **kw):
        raise HttpError(429, f"api.openalex.org refused the request (HTTP 429): {message}", persistent=True)
    monkeypatch.setattr(lrhttp, "request", refuse)


def test_rate_limit_raises_persistent_error_and_explains_once(monkeypatch, capsys):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    rate_limited(monkeypatch)
    for _ in range(2):
        with pytest.raises(HttpError) as e:
            openalex._get("/works", {})
        assert e.value.persistent
    err = capsys.readouterr().err
    assert err.count("OPENALEX RATE LIMIT") == 1
    assert "shared OpenAlex API key built into LR-AI" in err and "OPENALEX_API_KEY" in err


def test_notice_names_the_personal_key_when_set(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "MINE")
    assert "your OpenAlex API key" in openalex.rate_limit_notice()


def test_other_errors_are_not_reported_as_rate_limits(monkeypatch):
    def broken(*a, **kw):
        raise HttpError(500, "HTTP 500 for https://api.openalex.org/works: server error")
    monkeypatch.setattr(lrhttp, "request", broken)
    with pytest.raises(HttpError):
        openalex._get("/works", {})
    assert not openalex.rate_limited


def test_cli_ends_with_the_notice_on_stdout(monkeypatch, capsys):
    rate_limited(monkeypatch)

    def cmd(args):
        try:
            openalex.search("graphs", limit=1)
        except HttpError:
            pass
    parser = cli.build_parser()
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    args = parser.parse_args(["status"])
    monkeypatch.setattr(parser, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(args, "func", cmd)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "OPENALEX RATE LIMIT" in out and "setx OPENALEX_API_KEY" in out
