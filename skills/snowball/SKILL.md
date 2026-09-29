---
name: snowball
description: Forward and backward citation snowballing for a literature review - collect the references of each paper and the papers that cite it (via OpenAlex, falling back to Semantic Scholar), for one or more rounds. Use when the user asks to snowball, expand a paper set through citations/references, or find related work from a start set.
---

# Snowballing (step 3)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>` (see `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`). If `${CLAUDE_PLUGIN_ROOT}` shows up unexpanded, the plugin root is two folders above this skill's base directory.

## Round 1 (usually enough)
1. Run `lr.py filter` first, so papers outside the year range or excluded types are not expanded.
2. Check the frontier size with `lr.py status`. Each paper costs about 2-3 API calls. The command refuses
   frontiers above 300 unless you pass `--force`. For large start sets, set `snowball.from: included` and
   screen first (skill `screen-papers`). This is the standard Wohlin guideline: snowball from included
   papers only.
3. Adjust `snowball.max_references` and `max_citations` if needed. Both keep the most-cited papers first.
   Defaults are 200 references and 50 citing papers per paper.
4. Run `lr.py snowball --run <dir>`. It reports references and citing papers found, new unique papers, and
   which backend served each paper.

## More rounds
Screen the new papers first (`filter`, then the `screen-papers` skill). Then run
`lr.py snowball --from included` to expand only the included papers from the previous round. The round
number increments automatically. Stop when a round adds few new included papers (saturation).

## Notes
- Every paper records who led to it (`found_via`: `backward:<parent>` / `forward:<parent>`). Papers
  linked from several start-set papers are strong candidates: `lr.py show --sort hits`.
- If OpenAlex's anonymous daily budget runs out, the command switches to Semantic Scholar and says so.
  Suggest `OPENALEX_API_KEY` to the user.

Next step: filtering and screening (skill `screen-papers`).
