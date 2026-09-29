---
description: Run a full literature review - seed search, database search, snowballing, screening, categorization and a Google Sheet
argument-hint: <topic or research question> [--step]
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Edit(lr-runs/**)
---

Run an LR-AI literature review on: $ARGUMENTS

Work through the steps below in order. For each step, load the named skill with the Skill tool and follow it.

**Automatic by default.** Run all six steps in one go, without stopping for approval. Make each decision
yourself (research questions, criteria, queries, filters, taxonomy, Google account), record it in the run's
`config.yaml`, and continue. After each step, post one short progress line. Stop early only when the review
cannot go on, for example when no database returns any papers or screening includes none.

**Step-by-step mode.** If the request contains `--step` or asks to confirm each step ("step by step",
"check with me"), stop at every checkpoint (listed below and marked **Checkpoint** in the skills), report
briefly, and wait for the user's go-ahead or corrections.

1. **Set up and seed**: skill `lr-ai:seed-search`. Check the environment, frame the review (RQs,
   criteria, year range), then draft and run the seed queries. Checkpoints: the framing and the queries,
   then the seed papers.
2. **Database search**: skill `lr-ai:database-search`. Checkpoints: the boolean queries, then the matches
   per database.
3. **Snowballing**: skill `lr-ai:snowball` (filter first; one round unless the user asks for more). When
   the start set is too large to snowball, the skill has you screen first and snowball from the included
   papers.
4. **Filter and screen**: skill `lr-ai:screen-papers` (deterministic filters, then parallel
   `lr-ai:paper-screener` agents). Checkpoint: the core/skim/exclude counts and the core papers.
5. **Categorize and summarize**: skill `lr-ai:categorize-papers`. Checkpoint: the taxonomy.
6. **Export**: skill `lr-ai:export-sheet` (Excel always; Google Sheet via Composio when available).

Rules:
- Pass `--run <dir>` to every `lr.py` command once the run exists. Keep all review state in the run folder.
- Keep the conversation short: summarize command output instead of pasting it. The run's `log.md`
  records every step.
- If an API is rate-limited or refuses anonymous access, the tool falls back to another source and
  says so. Mention once which API key would help, then continue.
- End with a short report:
  - the sheet URL (or the xlsx path), the PRISMA-style counts from `lr.py status`, and the run folder
  - in automatic mode, the choices you made, so the user can check them: research questions, criteria and
    year range, seed and boolean queries, any filters you tightened, the taxonomy (categories with paper
    counts) and the Google account. Add that they can change any of these in `config.yaml` and ask you
    to redo that step.
