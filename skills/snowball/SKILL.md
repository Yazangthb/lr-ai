---
name: snowball
description: Forward and backward citation snowballing for a literature review - collect the references of each paper and the papers that cite it (via OpenAlex, falling back to Semantic Scholar), for one or more rounds. Use when the user asks to snowball, expand a paper set through citations/references, or find related work from a start set.
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Edit(lr-runs/**)
---

# Snowballing (step 3)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>`. Run it with the Bash tool exactly
as written, so it needs no permission prompt. `lr.py <command> --help` lists the options. If the path still
contains a `$` placeholder, the plugin root is two folders above this skill's base directory.

Automatic by default: make the choices below yourself and keep going. Lines marked **Checkpoint** apply only
in step-by-step mode (the user asked to confirm steps, e.g. `/lr-ai:lit-review --step`): there, stop and
wait for the user's reply.

## No run yet
If the user just names papers to expand (DOIs, arXiv ids or titles), create a run first:
`lr.py init "<topic>" --name <short-name>`, then `lr.py add --run <dir> <paper> <paper> ...`. Papers added
this way are never filtered out.

## Round 1 (usually enough)
1. Run `lr.py filter` first, so papers outside the year range or excluded types are not expanded.
2. Adjust `snowball.max_references` and `max_citations` if needed. Both keep the most-cited papers first.
   Defaults are 200 references and 50 citing papers per paper.
3. Run `lr.py snowball --run <dir>`. Each start paper costs about 2-3 API calls. The command reports
   references and citing papers found, new unique papers, and which backend served each paper.
4. If it refuses because more than 300 papers would be expanded, don't pass `--force`. Snowball from the
   included papers only, which is the standard Wohlin guideline: set `snowball.from: included`, screen
   first (skill `screen-papers`), run `snowball` again, then screen the new papers (`screen-papers` again;
   only unscreened papers go to the screeners).

## More rounds
Screen the new papers first (`filter`, then the `screen-papers` skill). Then run
`lr.py snowball --from included` to expand only the included papers from the previous round. The round
number increments automatically. Stop when a round adds few new included papers (saturation).

## Notes
- Every paper records who led to it (`found_via`: `backward:<parent>` / `forward:<parent>`). Papers
  linked from several start-set papers are strong candidates: `lr.py show --sort hits`.
- If OpenAlex's daily budget runs out, the command switches to Semantic Scholar and prints an
  `OPENALEX RATE LIMIT` notice. Show it to the user word for word: it says what happened and how to set
  their own `OPENALEX_API_KEY`.

Next step: filtering and screening (skill `screen-papers`).
