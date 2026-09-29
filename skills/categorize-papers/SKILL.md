---
name: categorize-papers
description: Build a two-level taxonomy for the included papers of a literature review and have subagents write summaries, research-question relations, categories and reading priorities for each paper. Use after screening, or when the user asks to categorize, classify, group or summarize the review papers.
---

# Taxonomy and summaries (step 5)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>` (see `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`). If `${CLAUDE_PLUGIN_ROOT}` shows up unexpanded, the plugin root is two folders above this skill's base directory.

## 1. Propose a taxonomy
Read the included papers compactly:
`lr.py show --where included=true --fields status,title,short_summary --limit 500`.

Propose 3-7 first-level categories, each with 2-6 sub-categories.
- Align first-level categories with the research questions where possible, e.g. "Graph-Based Forecasting (RQ1)".
- Categories should be mutually exclusive enough that each paper has one obvious home.
- Every category should hold at least 2 papers. Use a small "Other / background" category for leftovers.

Show the taxonomy to the user as a short tree with an estimated count per category, and let them rename,
merge or split. Then write it to `config.yaml`:

```yaml
taxonomy:
  - name: "Graph-Based Forecasting (RQ1)"
    rq: RQ1
    children: ["Citation Analysis & Recommendations", "Link Prediction"]
```

## 2. Enrich with subagents
1. Run `lr.py batches --stage enrich`. Each batch file carries the taxonomy and research questions.
2. Launch one `lr-ai:paper-screener` subagent per batch file, in parallel, with the batch path as the
   prompt. It writes a summary, short summary, RQ relation, category, sub-category, priority and code
   availability for each paper.
3. Run `lr.py apply --stage enrich`. Re-run agents for any batches it reports as missing. If it reports
   categories outside the taxonomy, fix them with `lr.py set <id> first_level="..." second_level="..."`
   or re-run the batch.

## 3. Check
Show the distribution (`lr.py export` prints it, or `show --fields first_level,second_level,title`) and ask
whether anything should move. Then continue to the `export-sheet` skill.
