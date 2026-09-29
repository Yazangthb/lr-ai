# The phases, and how to run each one on its own

LR-AI runs as a pipeline, but every phase is a separate command, so you can run and verify each one alone.
All commands run from the repository root. Inside Claude Code, `/lr-ai:lit-review <topic>` runs every phase
in one go (add `--step` to approve each phase first), and each phase is also its own skill
(`/lr-ai:setup`, `/lr-ai:seed-search`, `/lr-ai:database-search`, `/lr-ai:snowball`, `/lr-ai:screen-papers`,
`/lr-ai:categorize-papers`, `/lr-ai:export-sheet`).

| # | Phase | Command(s) | Needs network | Needs an LLM |
|---|---|---|---|---|
| 0 | Setup and health check | `doctor`, `init` | yes | no |
| 1 | Seed search | `seed`, `add` | yes | no |
| 2 | Database search | `search` | yes | no |
| 3 | Snowballing | `snowball` | yes | no |
| 4a | Automatic filters | `filter` | no | no |
| 4b | Screening | `batches --stage screen`, `apply --stage screen` | no | yes (or write results by hand) |
| 5 | Categorize and summarize | `batches --stage enrich`, `apply --stage enrich` | no | yes (or by hand) |
| 6 | Export | `export`, `sheet-plan` | only for the Google Sheet | no |

At any time, `python scripts/lr.py status` prints PRISMA-style counts and the suggested next step, and the
run's `log.md` lists every step that ran.

## 0. Setup and health check

```bash
pip install -r requirements.txt pytest
python -m pytest -q                      # offline tests covering the logic of every phase
python scripts/lr.py doctor              # packages, API reachability, API keys
python scripts/lr.py init "phase test" --name test
```

`init` creates `lr-runs/test-<date>/` with a `config.yaml`. Later commands use the most recently modified
run automatically; pass `--run <folder>` to choose another one.

## 1. Seed search

Runs natural-language queries on Semantic Scholar. If Semantic Scholar is rate-limited, the query goes to
OpenAlex, then arXiv. It also resolves papers you already know (DOIs, arXiv ids, exact titles).

```bash
python scripts/lr.py seed --query "predicting citation counts with graph neural networks" --limit 5
python scripts/lr.py add 10.1126/science.1237825 arXiv:2009.02647
```

Check:
- the printed paper list, and which database answered each query
- `raw/seed-01.jsonl` (exactly what came back) and `papers.jsonl` (the de-duplicated master list)

`--query` runs ad hoc queries. For a real review, put queries in `seed.queries` and known papers in
`seed.papers` in `config.yaml`, then run `seed` with no flags.

## 2. Database search

Runs boolean keyword queries, translated into each database's own syntax, then merges and de-duplicates
the results with everything found so far.

```bash
python scripts/lr.py search --query "(citation OR bibliometric) AND graph AND predict*" --sources arxiv --limit 5
python scripts/lr.py search --query "(citation OR bibliometric) AND graph AND predict*" --sources openalex --limit 5
python scripts/lr.py search --query "(citation OR bibliometric) AND graph AND predict*" --sources semantic_scholar --limit 5
```

Check:
- `kept N of M matches` for each database. M is the database's total, which tells you how broad the query is.
- `raw/search-NN-<source>.jsonl`, and `status` for how many duplicates were merged.

Quoted phrases such as `"citation network"` are easiest to put in `config.yaml` (`search.queries`). On the
command line, bash needs `'("citation network" OR x) AND y'`, and Windows PowerShell 5 needs the inner
quotes written as `\"`.

## 3. Snowballing

Collects each paper's references (backward) and the papers that cite it (forward), most-cited first.
OpenAlex comes first, and Semantic Scholar fills whatever direction OpenAlex is missing.

To test it alone, start a fresh run from a single paper:

```bash
python scripts/lr.py init "snowball test" --name snow
python scripts/lr.py add 10.1126/science.1237825
python scripts/lr.py snowball --max-references 5 --max-citations 5
python scripts/lr.py show --where found=forward --fields year,citations,title
```

Check:
- one line per paper, like `5 refs, 5 citing (openalex)`
- `--backend semantic_scholar` tests the fallback source on its own
- `show --sort hits` lists papers linked from several start papers

## 4a. Automatic filters (offline)

Edit `filters:` in the run's `config.yaml`, for example `year_min: 2016` or
`require_any: ["citation*"]`, then:

```bash
python scripts/lr.py filter
python scripts/lr.py show --where excluded=true --fields year,reason,title
```

Check the count per exclusion reason. Filters are recomputed every time, so change them and run again.
Papers you added yourself (`add`, `seed.papers`) are never filtered out.

## 4b. Screening

`batches` writes batch files, one per screener subagent. Each subagent writes a result file, and `apply`
merges the results back.

```bash
python scripts/lr.py batches --stage screen --size 5
```

- **With the real LLM:** in Claude Code, say *"Run the lr-ai:paper-screener agent on
  lr-runs/test-<date>/screen/batch_001.jsonl"*.
- **Without an LLM** (tests the mechanics only): the first line of each batch file names its result file
  (`_meta.output`). Write one JSON line per paper there:

  ```json
  {"id": "doi:10.1126/science.1237825", "status": "core", "reason": "test", "relevance": 0.8, "short_summary": "Test."}
  ```

Then:

```bash
python scripts/lr.py apply --stage screen
python scripts/lr.py show --where status=core --fields status,reason,title
```

Check:
- the core/skim/exclude counts
- batches with missing results are listed (re-run just those)
- `set <id> status=exclude` overrides a decision permanently

## 5. Categorize and summarize

Add a taxonomy to `config.yaml`:

```yaml
taxonomy:
  - name: "Science of science"
    children: ["Impact prediction", "Team science"]
```

```bash
python scripts/lr.py batches --stage enrich
# run the lr-ai:paper-screener agent on each batch file, or write results by hand:
# {"id": "...", "summary": "...", "short_summary": "...", "rq_relation": "RQ1", "first_level": "Science of science",
#  "second_level": "Impact prediction", "priority": "high", "code": ""}
python scripts/lr.py apply --stage enrich
python scripts/lr.py show --where included=true --fields first_level,second_level,priority,title
```

Check that every included paper has a category, and that `apply` reports no categories outside the taxonomy.

## 6. Export

```bash
python scripts/lr.py export                                  # writes <run>/papers.xlsx
python scripts/lr.py sheet-plan --spreadsheet-id TEST        # writes <run>/export/gsheets/*.json (offline)
```

Check:
- open `papers.xlsx`: category rows, colored status and priority, dropdowns, filter, and the Overview and
  Method tabs
- the plan files in `export/gsheets/` are the exact Composio calls that build the Google Sheet

To test the export without screening, mark a few papers by hand first:
`python scripts/lr.py set <id> status=core` (ids come from `show`).

The live Google Sheet is created from Claude Code with Composio connected. Say *"export the review to
Google Sheets"*, which runs the `lr-ai:export-sheet` skill.
