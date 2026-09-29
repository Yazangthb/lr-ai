---
name: screen-papers
description: Filter and screen literature-review candidates - apply deterministic filters (year, language, type, citations, keywords) and then title/abstract screening by parallel subagents that label each paper core, skim or exclude. Use when the user wants to filter, screen, or narrow down the collected papers against inclusion criteria.
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Edit(lr-runs/**)
---

# Filtering and screening (step 4)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>`. Run it with the Bash tool exactly
as written, so it needs no permission prompt. `lr.py <command> --help` lists the options. If the path still
contains a `$` placeholder, the plugin root is two folders above this skill's base directory.

Automatic by default: make the choices below yourself and keep going. Lines marked **Checkpoint** apply only
in step-by-step mode (the user asked to confirm steps, e.g. `/lr-ai:lit-review --step`): there, stop and
wait for the user's reply.

## 1. Deterministic filters
Run `lr.py filter`. It recomputes `excluded_reason` from the `filters` in `config.yaml` every time and prints
how many papers await screening. Screening takes about one subagent per 25 papers, so keep it to roughly
400 papers unless the user asked for more. If more remain, tighten the filters in this order, re-running
`filter` after each change, until the rest fits:
1. `min_hits: 2`: snowballed papers must be linked from at least 2 start-set papers
2. `require_any`: 3-8 core terms of the topic, with `*` for word stems, e.g. `["citation*", "bibliometric*"]`
3. `min_citations` (e.g. 5); `citation_grace_years` keeps recent papers exempt

Keep track of what you tightened for the final report.

**Checkpoint:** show the counts and propose the stricter filters instead of applying them yourself.

Papers the user added (`seed.papers`, `add`) are never filtered out.

## 2. Screening with subagents
1. Run `lr.py batches --stage screen`. It writes batch files of `screening.batch_size` (default 25) papers
   each and prints their paths.
2. Launch one `lr-ai:paper-screener` subagent per batch file, in parallel. Send them in a single message,
   up to about 10 at a time. Prompt each one with just the batch file path. The criteria and research
   questions travel inside the file.
3. Run `lr.py apply --stage screen`. If it lists batches with missing results, re-launch agents for
   those batch files only, then `apply` again.

Status meanings: **core** means it directly addresses a research question and meets the inclusion
criteria. **skim** means it's related, background, or partially relevant. **exclude** means it's off-topic
or hits an exclusion criterion.

## 3. Results
Report the core/skim/exclude counts in one line. If no paper was included, stop and tell the user: the
criteria or the queries are probably off.

**Checkpoint:** show the core papers (`lr.py show --where status=core --fields year,citations,title,reason`)
and a few borderline ones (`--where status=skim`). Fix disagreements with
`lr.py set <id> status=core|skim|exclude status_reason="..."`. Manual edits are permanent: later `apply`
runs never overwrite them. If the user wants more rounds, go back to the `snowball` skill with
`--from included`.

Next step: categorization and summaries (skill `categorize-papers`).
