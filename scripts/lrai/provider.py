"""Screen batch files through any OpenAI-compatible chat API (OpenRouter, OpenAI, a local server), with the same
prompt the Claude Code `paper-screener` agent uses (agents/paper-screener.md), so models can be compared on the
same batches. Result files are written where the agent would write them; `lr.py apply --model ...` merges them.

The API key is read from an environment variable only and never written to logs, batch files or results.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import http
from .models import read_meta
from .run import ENGINE_ROOT

PROVIDERS = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
}
USAGE_FILE = "usage.jsonl"  # one line per API call or per applied result file, in the stage folder
_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.S)


def screener_prompt() -> str:
    """The agent's instructions without its frontmatter, plus how the file content arrives in a chat API."""
    with open(os.path.join(ENGINE_ROOT, "agents", "paper-screener.md"), encoding="utf-8") as f:
        text = _FRONTMATTER.sub("", f.read().replace("\r\n", "\n"), count=1)
    return text.strip() + (
        "\n\n## In this conversation\nYou have no tools. The user message is the batch file itself. Answer with the "
        "JSONL result lines only (one JSON object per paper, every id copied exactly), not the short reply line.")


def parse_results(text: str, wanted: list[str]) -> dict[str, dict]:
    """JSON objects with a wanted id, from a reply that may wrap them in fences, a JSON array or prose."""
    text = re.sub(r"```(?:jsonl?|json lines)?", "", text or "")
    found: dict[str, dict] = {}
    candidates = [line.strip().rstrip(",") for line in text.splitlines()]
    try:  # a model that answers with one JSON array instead of JSONL
        arr = json.loads(text.strip())
        if isinstance(arr, list):
            candidates = [json.dumps(x) for x in arr]
    except ValueError:
        pass
    ids = set(wanted)
    for c in candidates:
        if not c.startswith("{"):
            continue
        try:
            r = json.loads(c)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("id") in ids and r["id"] not in found:
            found[r["id"]] = r
    return found


def _chat(base_url: str, key: str, model: str, system: str, user: str, timeout: float) -> tuple[str, dict]:
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "usage": {"include": True}}  # OpenRouter: report the cost; other servers ignore it
    text = http.request(base_url.rstrip("/") + "/chat/completions", body=body, cache=False, timeout=timeout,
                        headers={"Authorization": f"Bearer {key}"}, min_interval=3.5, retries=6)
    try:
        d = json.loads(text)
        reply = d["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError):
        raise http.HttpError(None, f"unexpected reply from {base_url}: {text[:200]!r}") from None
    return reply, d.get("usage") or {}


def screen_batches(run, batches: list[str], provider: str, model: str, base_url: str | None = None,
                   key_env: str | None = None, timeout: float = 300.0, say=print) -> dict:
    """Screen each batch file that has no result file yet. Papers a reply leaves out are asked for once more in
    a second call; any still missing stay pending (apply reports them). Returns totals for the run log."""
    preset = PROVIDERS.get(provider, {})
    base_url = base_url or preset.get("base_url")
    key_env = key_env or preset.get("key_env") or "LLM_API_KEY"
    if not base_url:
        raise SystemExit(f"Unknown provider {provider!r}: pass --base-url (and --key-env) for an OpenAI-compatible API.")
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise SystemExit(f"Set {key_env} in the environment for this command (it is never stored).")
    system = screener_prompt()
    usage_path = os.path.join(run.file("screen"), USAGE_FILE)
    totals = {"batches": 0, "papers": 0, "screened": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0,
              "seconds": 0.0, "failed": []}
    for batch in batches:
        meta = read_meta(batch)
        out = meta["output"]
        if os.path.exists(out):
            continue
        with open(batch, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        rows = [json.loads(ln) for ln in lines[1:]]
        wanted = [r["id"] for r in rows]
        got: dict[str, dict] = {}
        for attempt in (1, 2):
            todo = [r for r in rows if r["id"] not in got]
            if not todo:
                break
            user = "\n".join([lines[0]] + [json.dumps(r, ensure_ascii=False) for r in todo])
            t0 = time.monotonic()
            try:
                reply, usage = _chat(base_url, key, model, system, user, timeout)
            except http.HttpError as e:
                say(f"  {meta['batch']}: {e}")
                if e.persistent:
                    raise SystemExit(f"Stopped at {meta['batch']}: {e}") from None
                break
            secs = time.monotonic() - t0
            new = parse_results(reply, [r["id"] for r in todo])
            got.update(new)
            entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "batch": meta["batch"], "attempt": attempt,
                     "provider": provider, "model": model, "papers": len(todo), "returned": len(new),
                     "seconds": round(secs, 1), "prompt_tokens": usage.get("prompt_tokens"),
                     "completion_tokens": usage.get("completion_tokens"), "cost": usage.get("cost"),
                     "source": "api"}
            with open(usage_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            for k in ("prompt_tokens", "completion_tokens", "cost"):
                totals[k] += usage.get(k) or 0
            totals["seconds"] += secs
        if got:
            with open(out, "w", encoding="utf-8") as f:
                for i in wanted:  # same order as the batch
                    if i in got:
                        f.write(json.dumps(got[i], ensure_ascii=False) + "\n")
        else:
            totals["failed"].append(meta["batch"])
        totals["batches"] += 1
        totals["papers"] += len(wanted)
        totals["screened"] += len(got)
        say(f"  {meta['batch']}: {len(got)}/{len(wanted)} papers screened")
    totals["seconds"] = round(totals["seconds"], 1)
    totals["cost"] = round(totals["cost"], 6)
    return totals


def estimate_tokens(chars: int) -> int:
    """Rough token count of English text and JSON (about 4 characters per token)."""
    return round(chars / 4)


def result_file_usage(batch: str, result: str, prompt_chars: int) -> dict:
    """Estimated size of one agent call (batch + prompt in, result out) and the time from writing the batch to its
    result. Claude Code agents do not report usage to LR-AI, so these are estimates; an agent's own overhead (its
    system prompt, tool calls) is not included."""
    b, r = os.stat(batch), os.stat(result)
    return {"input_tokens_est": estimate_tokens(b.st_size + prompt_chars),
            "output_tokens_est": estimate_tokens(r.st_size),
            "batch_written": b.st_mtime, "result_written": r.st_mtime}
