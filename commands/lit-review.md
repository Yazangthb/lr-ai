---
description: Run a full literature review - seed search, database search, snowballing, screening, categorization and a Google Sheet
argument-hint: <topic or research question>
---

Run an LR-AI literature review on: $ARGUMENTS

Work through the steps in order. For each step, load the named skill with the Skill tool and follow it.
Stop at every **checkpoint**, report briefly, and wait for the user's go-ahead or corrections.

1. **Set up and seed**: skill `lr-ai:seed-search`. Check the environment, frame the review (RQs,
   criteria, year range), draft seed queries. **Checkpoint:** confirm the queries, then show the seed papers.
2. **Database search**: skill `lr-ai:database-search`. **Checkpoint:** confirm the boolean queries,
   then report matches per database.
3. **Snowballing**: skill `lr-ai:snowball` (filter first; one round unless the user asks for more).
4. **Filter and screen**: skill `lr-ai:screen-papers` (deterministic filters, then parallel
   `lr-ai:paper-screener` agents). **Checkpoint:** show core/skim/exclude counts and the core papers.
5. **Categorize and summarize**: skill `lr-ai:categorize-papers`. **Checkpoint:** confirm the taxonomy.
6. **Export**: skill `lr-ai:export-sheet` (Excel always; Google Sheet via Composio when available).

Rules:
- Pass `--run <dir>` to every `lr.py` command once the run exists. Keep all review state in the run folder.
- Keep the conversation short: summarize command output instead of pasting it. The run's `log.md`
  records every step.
- If an API is rate-limited or refuses anonymous access, the tool falls back to another source and
  says so. Tell the user once which API key would help, then continue.
- End with: the sheet URL (or xlsx path), the PRISMA-style counts from `lr.py status`, and the run folder path.
