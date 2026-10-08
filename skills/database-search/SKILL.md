---
name: database-search
description: Run boolean keyword searches for a literature review across scholarly databases (OpenAlex, Semantic Scholar, arXiv) and merge the results with deduplication. Use after seed search, or when the user asks to search databases, index databases, or run keyword/boolean queries for papers.
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Edit(lr-runs/**)
---

# Database keyword search (step 2)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>`. Run it with the Bash tool exactly
as written, so it needs no permission prompt. `lr.py <command> --help` lists the options. If the path still
contains a `$` placeholder, the plugin root is two folders above this skill's base directory.

Automatic by default: make the choices below yourself and keep going. Lines marked **Checkpoint** apply only
in step-by-step mode (the user asked to confirm steps, e.g. `/lr-ai:lit-review --step`): there, stop and
wait for the user's reply.

## 1. Build the queries
Read `config.yaml` (topic, RQs, criteria) and a sample of the seed papers
(`lr.py show --fields title,short_summary --limit 30`). Write 1-4 boolean queries:
- one OR-group per concept, joined with AND: `("citation network" OR "citation graph") AND (forecast* OR predict*)`
- quote multi-word phrases; use `*` for word stems; add `NOT` only for clear noise (e.g. `NOT protein`)
- use uppercase AND / OR / NOT. The tool translates the query for each database.

Put them in `search.queries`. `search.per_query` (default 100) caps the results kept per query per
database, most relevant first.

**Checkpoint:** show the queries before running them.

## 2. Run
`lr.py search --run <dir>`. The output reports how many matches each database has in total:
- tens of thousands of matches: the query is too broad, so add a concept or tighten the phrases.
- very few matches: loosen the query (more synonyms, fewer ANDs).

Fix such a query in `config.yaml` and run `search` once more. Unchanged queries are answered from the cache.

Errors from one database don't stop the others. If the output has an `OPENALEX RATE LIMIT` notice, show
it to the user word for word (what happened and how to set their own `OPENALEX_API_KEY`), then continue
with the other databases.

## 3. Report
Run `lr.py status --run <dir>` and summarize it in one line: records per source, duplicates merged, unique
papers.

**Checkpoint:** wait for the user before snowballing.

Next step: snowballing (skill `snowball`).
