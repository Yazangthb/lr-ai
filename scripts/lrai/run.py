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
import json
import os

from . import config as cfgmod
from . import http
from .models import Paper, read_jsonl, write_jsonl


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

    def log(self, stage: str, summary: str, **data) -> None:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        with open(self.file("runlog.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": now, "stage": stage, "summary": summary, **data}, ensure_ascii=False) + "\n")
        with open(self.file("log.md"), "a", encoding="utf-8") as f:
            f.write(f"- **{now.replace('T', ' ')} · {stage}** — {summary}\n")

    def runlog(self) -> list[dict]:
        path = self.file("runlog.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
