import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from lrai import http  # noqa: E402
from lrai.config import render_template  # noqa: E402
from lrai.models import Paper  # noqa: E402
from lrai.sources import openalex  # noqa: E402

REAL_REQUEST = http.request  # for tests that drive the HTTP layer against a fake urlopen


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never hit the real APIs."""
    def refuse(*args, **kwargs):
        raise AssertionError("network access in tests")
    monkeypatch.setattr(http, "request", refuse)
    monkeypatch.setattr(openalex, "rate_limited", False)
    http.set_cache_dir(None)


@pytest.fixture
def make_run(tmp_path):
    """Create a run folder with a config.yaml; `extra_yaml` is appended to the template."""
    def factory(extra_yaml: str = "", topic: str = "citation graph forecasting"):
        from lrai.run import Run
        path = tmp_path / "run"
        path.mkdir()
        text = render_template(topic, "2026-01-01")
        (path / "config.yaml").write_text(text + "\n" + extra_yaml, encoding="utf-8")
        return Run(str(path), use_cache=False)
    return factory


def paper(title="A study of citation networks for forecasting", **kw) -> Paper:
    return Paper(title=title, **kw).normalize()
