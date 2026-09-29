---
name: database-search
description: Run boolean keyword searches for a literature review across scholarly databases (OpenAlex, Semantic Scholar, arXiv) and merge the results with deduplication. Use after seed search, or when the user asks to search databases, index databases, or run keyword/boolean queries for papers.
---

# Database keyword search (step 2)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>` (see `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`). If `${CLAUDE_PLUGIN_ROOT}` shows up unexpanded, the plugin root is two folders above this skill's base directory.

## 1. Build the queries
Read `config.yaml` (topic, RQs, criteria) and a sample of the seed papers
(`lr.py show --fields title,short_summary --limit 30`). Write 1-4 boolean queries:
- one OR-group per concept, joined with AND: `("citation network" OR "citation graph") AND (forecast* OR predict*)`
- quote multi-word phrases; use `*` for word stems; add `NOT` only for clear noise (e.g. `NOT protein`)
- use uppercase AND / OR / NOT. The tool translates the query for each database.

Show the queries to the user before running. Put them in `search.queries`. `search.per_query`
(default 100) caps the results kept per query per database, most relevant first.

## 2. Run
`lr.py search --run <dir>`. The output reports how many matches each database has in total:
- tens of thousands of matches: the query is too broad, so add a concept or tighten the phrases.
- very few matches: loosen the query (more synonyms, fewer ANDs).

Errors from one database don't stop the others. If OpenAlex refuses anonymous search, tell the user
about the free `OPENALEX_API_KEY` and continue with the other databases.

## 3. Report
Run `lr.py status --run <dir>` and summarize: records per source, duplicates merged, unique papers.

Next step: snowballing (skill `snowball`).
