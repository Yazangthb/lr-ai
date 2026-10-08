---
name: seed-search
description: Start a literature review - set up the review (topic, research questions, inclusion/exclusion criteria) and find an initial set of seed papers via Semantic Scholar queries and known DOIs/arXiv ids. Use when the user wants to begin a literature review, find initial or seed papers for a topic, or set up LR-AI.
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Edit(lr-runs/**)
---

# Seed search (step 1)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command>`. Run it with the Bash tool exactly as written, so
it needs no permission prompt (use `python3` if `python` is not Python 3). `lr.py <command> --help` lists the
options. Always pass `--run <run dir>` once a run exists. If the path still contains a `$` placeholder, the
plugin root is two folders above this skill's base directory.

Automatic by default: make the choices below yourself and keep going. Lines marked **Checkpoint** apply only
in step-by-step mode (the user asked to confirm steps, e.g. `/lr-ai:lit-review --step`): there, stop and
wait for the user's reply.

## 1. Check the environment (once per session)
Run `lr.py doctor`. If `yaml` or `openpyxl` is missing, install them with
`python -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"` (Claude Code asks the user to approve
it). Mention missing API keys in one line and continue. They're optional: LR-AI ships a shared OpenAlex
key. If any command prints an `OPENALEX RATE LIMIT` notice, show it to the user word for word.

## 2. Frame the review
Take the topic, research questions, criteria, year range and known papers from the user's request, and
decide the rest yourself:
- 1-3 research questions (RQ1, RQ2, ...) that the topic implies
- inclusion and exclusion criteria that follow from them, for example "proposes a method for X" or
  "not peer-reviewed"
- no year limit unless the request implies one

**Checkpoint:** ask the user for what the request left out instead of deciding it yourself.

Then run `lr.py init "<topic>" --name <short-name>` and fill `config.yaml` in the new run folder:
`research_questions`, `inclusion_criteria`, `exclusion_criteria`, `filters.year_min` / `year_max`.

## 3. Seed queries
Draft 3-6 natural-language queries that cover the RQs from different angles: synonyms, the method
side and the application side. Put them in `seed.queries`, and known papers in `seed.papers`.

**Checkpoint:** show the queries and let the user edit them.

If scholarly-search tools are available in this session (e.g. an alphaXiv / Consensus / Semantic Scholar
MCP, or web search), use them too. Put the DOIs or arXiv ids of highly relevant papers they return into
`seed.papers`. This often gives better seeds than keyword queries.

## 4. Run
`lr.py seed --run <dir>`. Each query falls back from Semantic Scholar to OpenAlex to arXiv if a service
is rate-limited. Look over the returned list and exclude clearly off-topic seeds:
`lr.py set --run <dir> <id> status=exclude status_reason="off-topic seed"`. Excluded seeds are not
snowballed.

**Checkpoint:** show the seed papers, grouped by relevance, before moving on.

Next step: database search (skill `database-search`).
