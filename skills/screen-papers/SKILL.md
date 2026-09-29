---
name: screen-papers
description: Filter and screen literature-review candidates - apply deterministic filters (year, language, type, citations, keywords) and then title/abstract screening by parallel subagents that label each paper core, skim or exclude. Use when the user wants to filter, screen, or narrow down the collected papers against inclusion criteria.
---

# Filtering and screening (step 4)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>` (see `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`). If `${CLAUDE_PLUGIN_ROOT}` shows up unexpanded, the plugin root is two folders above this skill's base directory.

## 1. Deterministic filters
Run `lr.py filter`. It recomputes `excluded_reason` from `config.yaml` `filters` every time. Review
the counts with the user. If too many papers remain for LLM screening (roughly more than 400), propose
stricter filters and re-run `filter`:
- `require_any` keywords, e.g. `["citation*", "bibliometric*"]`
- `min_citations` with `citation_grace_years`
- `min_hits: 2` for snowballed papers

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

## 3. Checkpoint with the user
Report counts and show the core papers (`lr.py show --where status=core --fields year,citations,title,reason`).
Also show a few borderline ones (`--where status=skim`). Fix disagreements with
`lr.py set <id> status=core|skim|exclude status_reason="..."`. Manual edits are permanent: later `apply`
runs never overwrite them. If the user wants more rounds, go back to the `snowball` skill with
`--from included`.

Next step: categorization and summaries (skill `categorize-papers`).
