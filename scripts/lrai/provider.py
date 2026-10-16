"""Screen batch files through any OpenAI-compatible chat API (OpenRouter, OpenAI, Yandex, a local server) or
Anthropic's Messages API (`--provider anthropic`), with the same
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
    # Yandex Cloud AI Studio; model ids are URIs with the cloud folder, e.g. gpt://<folder>/gpt-oss-120b
    "yandex": {"base_url": "https://llm.api.cloud.yandex.net/v1", "key_env": "YANDEX_API_KEY"},
    # Anthropic's own Messages API through the official SDK (not an OpenAI-compatible endpoint). The base URL is set
    # explicitly so a Claude Code environment's ANTHROPIC_BASE_URL never redirects the request.
    "anthropic": {"base_url": "https://api.anthropic.com", "key_env": "ANTHROPIC_API_KEY"},
}
# USD per 1M tokens: input, output, cache write (5 min), cache read; list prices of 16 Oct 2026, prompts up to 100K
ANTHROPIC_PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 12.5, 0.25), "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.20), "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01), "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
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
    """JSON objects with a wanted id, wherever they are in the reply: one per line, in fences or a JSON array, or
    written back to back on one line (gpt-oss-20b does this)."""
    decoder = json.JSONDecoder()
    text = text or ""
    ids = set(wanted)
    found: dict[str, dict] = {}
    i = text.find("{")
    while i != -1:
        try:
            r, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(r, dict) and r.get("id") in ids and r["id"] not in found:
            found[r["id"]] = r
        i = text.find("{", end)
    return found


def _chat(base_url: str, key: str, model: str, system: str, user: str, timeout: float) -> tuple[str, dict]:
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if "openrouter.ai" in base_url:
        body["usage"] = {"include": True}  # report the cost; other servers may reject the field (Yandex's Qwen does)
    text = http.request(base_url.rstrip("/") + "/chat/completions", body=body, cache=False, timeout=timeout,
                        headers={"Authorization": f"Bearer {key}"}, min_interval=3.5, retries=6)
    try:
        d = json.loads(text)
        reply = d["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError):
        raise http.HttpError(None, f"unexpected reply from {base_url}: {text[:200]!r}") from None
    return reply, d.get("usage") or {}


def _chat_anthropic(base_url: str, key: str, model: str, system: str, user: str, timeout: float) -> tuple[str, dict]:
    """One Messages API call with the model's default settings (no sampling or thinking options, which several current
    models reject or fix). No refusal fallback: an experiment must not switch models silently, so a refusal is
    reported and its papers stay pending."""
    try:
        import anthropic
    except ImportError:
        raise SystemExit("--provider anthropic needs the anthropic package: pip install anthropic") from None
    client = anthropic.Anthropic(api_key=key, base_url=base_url, timeout=timeout, max_retries=4)
    try:
        msg = client.messages.create(model=model, max_tokens=16000, system=system,
                                     messages=[{"role": "user", "content": user}])
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError,
            anthropic.BadRequestError) as e:
        raise http.HttpError(getattr(e, "status_code", None), f"Anthropic API: {e.message}", persistent=True) from None
    except anthropic.APIError as e:  # rate limits, server and connection errors left after the SDK's retries
        raise http.HttpError(getattr(e, "status_code", None), f"Anthropic API: {e}") from None
    reply = "".join(b.text for b in msg.content if b.type == "text")
    u = msg.usage
    cw, cr = (u.cache_creation_input_tokens or 0), (u.cache_read_input_tokens or 0)
    usage = {"prompt_tokens": u.input_tokens + cw + cr, "completion_tokens": u.output_tokens,
             "stop_reason": msg.stop_reason}
    price = ANTHROPIC_PRICES.get(model)
    if price:
        usage["cost"] = (u.input_tokens * price[0] + u.output_tokens * price[1] + cw * price[2] + cr * price[3]) / 1e6
    return reply, usage


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
                chat = _chat_anthropic if provider == "anthropic" else _chat
                reply, usage = chat(base_url, key, model, system, user, timeout)
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
                     "source": "api", **({"stop_reason": usage["stop_reason"]} if "stop_reason" in usage else {})}
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
