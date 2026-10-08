---
name: setup
description: Check or set up LR-AI, the literature-review plugin - run its doctor (Python packages, API reachability, API keys), install its Python dependencies, and explain the optional API keys. Use when the user asks to check, diagnose, test, install or configure LR-AI, or asks for the LR-AI doctor.
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
---

# LR-AI setup and health check

The tool is `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py"`. Use `python3` if `python` is not Python 3.
Don't search the disk for it; this is the command. Run it with the Bash tool exactly as written, so it needs
no permission prompt. If the path still contains a `$` placeholder, the plugin root is two folders above
this skill's base directory.

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" doctor`.
2. If `yaml` or `openpyxl` is missing, install them with
   `python -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"` (Claude Code asks the user to approve
   it).
3. Report the result in a few lines. A ⚠ next to a database is not fatal: LR-AI falls back to the other
   databases. Mention the optional environment variables once:
   - `OPENALEX_API_KEY`: free at openalex.org. LR-AI ships a shared key; a personal key has its own daily
     budget, so set one if OpenAlex reports a rate limit.
   - `S2_API_KEY`: free on request from Semantic Scholar. Gives a dedicated rate limit.
   - `OPENALEX_EMAIL`: identifies the user to OpenAlex (polite pool).
   - `LR_AI_GOOGLE_ACCOUNT`: the alias or id of the Composio Google account that gets the sheets, when
     several are connected. Otherwise the first connected account is used.

   To set one permanently on Windows: `setx OPENALEX_API_KEY "<key>"`, then restart Claude Code. On
   macOS/Linux: add `export OPENALEX_API_KEY=<key>` to the shell profile.
4. Point to the next step: `/lr-ai:lit-review <topic>` runs a whole review without stopping, and
   `/lr-ai:lit-review <topic> --step` pauses for approval after each step. To run and check phases one at a
   time, see `${CLAUDE_PLUGIN_ROOT}/docs/phases.md`. The full command reference is in
   `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`.
