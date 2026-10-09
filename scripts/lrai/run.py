"""A review run: one folder holding config.yaml, the master paper list, raw fetches and the log.

    lr-runs/<slug>-<date>/
      config.yaml        what to search and how to filter (edited by the user / Claude)
      papers.jsonl       every unique paper found so far, with provenance and screening results
      raw/               exactly what each search / snowball call returned (for transparency)
      screen/, enrich/   batch files for screening subagents and their results
      runlog.jsonl       machine-readable log of every step (used for the Method tab / PRISMA counts)
      log.md             the same log, human-readable
"""
from __future__ import annotations

import datetime
import functools
import hashlib
import json
import os
import subprocess

from . import __version__
from . import config as cfgmod
from . import http
from .models import Paper, read_jsonl, write_jsonl


ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", ENGINE_ROOT, *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=10, check=True).stdout.strip()


@functools.lru_cache(maxsize=1)
def engine_commit() -> str | None:
    """Git commit of the LR-AI code that is running ("<sha>+dirty" if scripts/ has uncommitted changes), or None
    when the code is not its own git checkout (e.g. a plugin copy, even one inside some other repository)."""
    try:
        top = _git("rev-parse", "--show-toplevel")
        if not top or not os.path.samefile(top, ENGINE_ROOT):
            return None
        sha = _git("rev-parse", "--short=12", "HEAD")
        dirty = _git("status", "--porcelain", "--", "scripts")
    except (OSError, subprocess.SubprocessError):
        return None
    return sha + ("+dirty" if dirty else "") if sha else None


class Run:
    def __init__(self, path: str, use_cache: bool = True):
        self.path = os.path.abspath(path)
        cfg_path = os.path.join(self.path, "config.yaml")
        if not os.path.exists(cfg_path):
            raise SystemExit(f"No config.yaml in {self.path}. Create a run first: lr.py init \"<topic>\"")
        self.config = cfgmod.load(cfg_path)
        if use_cache:
            http.set_cache_dir(os.path.join(self.path, "cache"))

    def file(self, *parts: str) -> str:
        return os.path.join(self.path, *parts)

    @property
    def papers_path(self) -> str:
        return self.file("papers.jsonl")

    def load(self) -> list[Paper]:
        return read_jsonl(self.papers_path) if os.path.exists(self.papers_path) else []

    def save(self, papers: list[Paper]) -> None:
        write_jsonl(self.papers_path, papers)

    def save_raw(self, name: str, papers: list[Paper]) -> str:
        path = self.file("raw", name + ".jsonl")
        write_jsonl(path, papers)
        return path

    def provenance(self) -> dict:
        """What produced this step: LR-AI version, engine commit and a hash of config.yaml (for reproducibility)."""
        try:
            with open(self.file("config.yaml"), "rb") as f:  # line endings normalised: CRLF and LF hash alike
                config_sha = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()[:12]
        except OSError:
            config_sha = None  # a locked or missing file must not stop the step from being logged
        return {"lrai": __version__, "commit": engine_commit(), "config_sha": config_sha}

    def log(self, stage: str, summary: str, **data) -> None:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        entry = {"time": now, "stage": stage, "summary": summary, **data, "provenance": self.provenance()}
        with open(self.file("runlog.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        with open(self.file("log.md"), "a", encoding="utf-8") as f:
            f.write(f"- **{now.replace('T', ' ')} · {stage}** — {summary}\n")

    def runlog(self) -> list[dict]:
        path = self.file("runlog.jsonl")
        if not os.path.exists(path):
            return []
        entries = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue  # a line cut off by a crash or a sync conflict; the other entries still count
        return entries
