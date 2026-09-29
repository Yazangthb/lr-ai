# `lr.py` command reference

Run as `python scripts/lr.py <command> [--run DIR] ...` (inside Claude Code the path is
`${CLAUDE_PLUGIN_ROOT}/scripts/lr.py`). Without `--run`, commands use the most recently modified run
under `./lr-runs`. Progress goes to stderr; a short summary goes to stdout.

| Command | Step | What it does |
|---|---|---|
| `init "<topic>" [--name short] [--root lr-runs]` | setup | Creates `lr-runs/<name>-<date>/config.yaml` |
| `doctor` | setup | Checks Python packages, API reachability and API keys |
| `seed [--limit N]` | 1 | Runs `seed.queries` (Semantic Scholar → OpenAlex → arXiv fallback) and resolves `seed.papers` |
| `search [--sources a,b] [--limit N]` | 2 | Runs boolean `search.queries` on OpenAlex, Semantic Scholar and arXiv |
| `snowball [--round N] [--from all\|included] [--direction ...] [--force]` | 3 | One round of backward + forward snowballing |
| `filter` | 4a | Applies the deterministic `filters` from config (recomputed every time) |
| `batches --stage screen\|enrich [--size N] [--force]` | 4b / 5 | Writes self-describing batch files for `paper-screener` subagents |
| `apply --stage screen\|enrich [--all]` | 4b / 5 | Merges new or changed `*.result.jsonl` files into `papers.jsonl`, reports missing results. Manual `set` edits always win |
| `export [--out file.xlsx]` | 6 | Writes the styled workbook (Papers, Overview, Method tabs) |
| `sheet-plan --spreadsheet-id ID [--sheet-id 0] [--account ACC]` | 6 | Writes the Composio calls that build the Google Sheet (`--account` defaults to `LR_AI_GOOGLE_ACCOUNT`) |
| `status` | any | PRISMA-style counts and the suggested next step |
| `show [--where k=v] [--fields a,b] [--sort citations] [--limit N]` | any | Lists papers (`--where status=core`, `included=true`, `found=forward`, `round=1`) |
| `add <doi\|arXiv id\|title> ...` | any | Adds papers manually (never removed by filters) |
| `set <paper id> key=value ...` | any | Manual override, e.g. `status=exclude status_reason="off topic"`. Never overwritten by `apply` |
| `complete [--all]` | any | Fills missing abstracts / citation counts |

## Run folder

```
lr-runs/<name>-<date>/
  config.yaml      topic, research questions, criteria, queries, filters, taxonomy
  papers.jsonl     every unique paper with provenance, filter and screening results (the master list)
  raw/             exactly what each search / snowball call returned
  screen/ enrich/  batch files and subagent results
  export/gsheets/  Google Sheets plan files
  papers.xlsx      the exported workbook
  log.md           human-readable log; runlog.jsonl is the machine-readable version
  cache/           cached API responses (re-running a step is free)
```

## Paper fields

`id` (doi:… / arxiv:… / openalex:… / s2:…), `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`,
`abstract`, `citation_count`, `found_via` (e.g. `seed:q1`, `search:openalex:q2`, `backward:<parent id>`),
`round`, `excluded_reason` (filters), `status` (core/skim/exclude), `status_reason`, `relevance`,
`short_summary`, `summary`, `rq_relation`, `first_level`, `second_level`, `priority` (high/medium/low), `code`.

## Boolean query syntax (`search.queries`)

`("citation network" OR "citation graph") AND (forecast* OR predict*) NOT survey`: uppercase operators,
quoted phrases, parentheses, `*` prefix wildcard. Translated to each database's own syntax.

## Environment variables (optional)

- `OPENALEX_API_KEY`: free at openalex.org. Without it, OpenAlex search may be paused under load and
  lookups share a small daily budget.
- `S2_API_KEY`: free on request from Semantic Scholar. Without it, requests share a busy public pool.
- `OPENALEX_EMAIL`: identifies you to OpenAlex (polite pool).
- `LR_AI_GOOGLE_ACCOUNT`: alias or id of the Composio Google account that gets the sheet when several are
  connected. `export` prints it and `sheet-plan` uses it unless `--account` is given.
