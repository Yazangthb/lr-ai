---
name: seed-search
description: Start a literature review - set up the review (topic, research questions, inclusion/exclusion criteria) and find an initial set of seed papers via Semantic Scholar queries and known DOIs/arXiv ids. Use when the user wants to begin a literature review, find initial or seed papers for a topic, or set up LR-AI.
---

# Seed search (step 1)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py"` (use `python3` if `python` is not Python 3). If `${CLAUDE_PLUGIN_ROOT}` shows up unexpanded, the plugin root is two folders above this skill's base directory.
Reference: `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`. Always pass `--run <run dir>` once a run exists.

## 1. Check the environment (once per session)
Run `lr.py doctor`. If `yaml` or `openpyxl` is missing, ask the user before running
`pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`. Mention missing API keys once. They're
optional, but `OPENALEX_API_KEY` (free) makes OpenAlex search reliable.

## 2. Frame the review
Collect from the user, asking only for what is missing:
- topic, and 1-3 research questions (RQ1, RQ2, ...)
- inclusion and exclusion criteria, for example "proposes a method for X" or "not peer-reviewed"
- publication year range, and any known key papers (DOIs, arXiv ids or titles)

Then run `lr.py init "<topic>" --name <short-name>` and fill `config.yaml` in the new run folder:
`research_questions`, `inclusion_criteria`, `exclusion_criteria`, `filters.year_min` / `year_max`.

## 3. Seed queries
Draft 3-6 natural-language queries that cover the RQs from different angles: synonyms, the method
side and the application side. Show them to the user and let them edit, then put them in
`seed.queries`. Put known papers in `seed.papers`.

If scholarly-search tools are available in this session (e.g. an alphaXiv / Consensus / Semantic Scholar
MCP, or web search), use them too. Put the DOIs or arXiv ids of highly relevant papers they return into
`seed.papers`. This often gives better seeds than keyword queries.

## 4. Run
`lr.py seed --run <dir>`. Each query falls back from Semantic Scholar to OpenAlex to arXiv if a service
is rate-limited. Show the user the returned list, grouped by relevance. Remove clearly off-topic seeds:
`lr.py set --run <dir> <id> status=exclude status_reason="off-topic seed"`. Excluded seeds are not
snowballed.

Next step: database search (skill `database-search`).
