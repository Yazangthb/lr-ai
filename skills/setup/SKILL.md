---
name: setup
description: Check or set up LR-AI, the literature-review plugin - run its doctor (Python packages, API reachability, API keys), install its Python dependencies, and explain the optional API keys. Use when the user asks to check, diagnose, test, install or configure LR-AI, or asks for the LR-AI doctor.
---

# LR-AI setup and health check

The tool is `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py"`. Use `python3` if `python` is not Python 3.
Don't search the disk for it; this is the command. If the path still contains a `$` placeholder, the
plugin root is two folders above this skill's base directory.

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" doctor`.
2. If `yaml` or `openpyxl` is missing, ask the user, then run
   `python -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`.
3. Report the result in a few lines. A ⚠ next to a database is not fatal: LR-AI falls back to the other
   databases. Mention the optional keys once:
   - `OPENALEX_API_KEY`: free at openalex.org. Makes OpenAlex search reliable and raises the daily budget.
   - `S2_API_KEY`: free on request from Semantic Scholar. Gives a dedicated rate limit.
   - `OPENALEX_EMAIL`: identifies the user to OpenAlex (polite pool).

   To set one permanently on Windows: `setx OPENALEX_API_KEY "<key>"`, then open a new terminal. On
   macOS/Linux: add `export OPENALEX_API_KEY=<key>` to the shell profile.
4. Point to the next step: `/lr-ai:lit-review <topic>` runs a whole review. To run and check phases one at
   a time, see `${CLAUDE_PLUGIN_ROOT}/docs/phases.md`. The full command reference is in
   `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`.
