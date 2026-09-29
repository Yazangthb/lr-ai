# LR-AI

**Automated literature reviews for Claude Code: from a research question to a categorized, summarized
Google Sheet of papers.**

LR-AI automates the repetitive part of a literature review (LR). You describe the topic, research questions
and inclusion criteria. It finds seed papers, searches scholarly databases, snowballs through references
and citations, removes duplicates, filters, screens every candidate with parallel subagents, builds a
taxonomy, and exports a styled Google Sheet and an Excel file.

It ships as a Claude Code plugin (skills, a command and a subagent) on top of a small, dependency-light
Python engine that you can also run on its own.

## Pipeline

```
Research question + criteria
      │
 1. Seed search       Semantic Scholar queries (falls back to OpenAlex / arXiv) + papers you already know
 2. Database search   boolean keyword queries on OpenAlex, Semantic Scholar and arXiv
      │               ── all results merged and de-duplicated (DOI, arXiv id, fuzzy title match)
 3. Snowballing       backward (references) + forward (citations) via OpenAlex / Semantic Scholar, N rounds
 4. Filter & screen   deterministic filters (year, language, type, citations, keywords), then
      │               title/abstract screening by parallel subagents → core / skim / exclude
 5. Categorize        two-level taxonomy (confirmed by you) + summaries, RQ relation, priority, code link
 6. Export            styled .xlsx + Google Sheet (via Composio): grouped rows, colors, dropdowns, filters
```

By default, Claude runs all six steps without stopping. It ends with the sheet link and a list of the choices
it made (research questions, criteria, queries, tightened filters, taxonomy). Every choice is saved in the
run's `config.yaml`, so you can change one and have Claude redo that step. Add `--step` to approve the
queries, screening results and taxonomy along the way instead.

## The output sheet

- **Papers**: one row per included paper, grouped under category and sub-category rows
  (`▌ Graph-Based Forecasting (RQ1) — 24 papers`, then `▸ Citation Analysis (6)`). Columns: Title, Status
  (`core - …` in green, `skim - …` in amber), Priority, Reading status (dropdown: to read / reading /
  studied, which highlights the row), Notes, Reviewer, Year, Venue, Citations, Code, Short summary, Summary,
  RQ relation, Category, Sub-category, Found via (seed / database / backward / forward), Authors, Link, PDF,
  ID. The header row and title column are frozen and there is a filter.
- **Overview**: papers per category and sub-category, per year, and top venues.
- **Method**: topic, RQs, criteria, every query, databases, snowballing settings, filters, and a
  PRISMA-style flow (identified → duplicates → filtered → screened → included), ready for a methods section.

## Install

Requirements: [Claude Code](https://claude.com/claude-code) and Python 3.9+.

```bash
# in Claude Code
/plugin marketplace add YAZANGTHB/lr-ai
/plugin install lr-ai@lr-ai
```

```bash
pip install -r requirements.txt   # pyyaml, openpyxl (Claude offers to do this on first use)
```

For the Google Sheet, connect [Composio](https://composio.dev)'s Google Sheets toolkit to Claude Code.
Without it you get the `.xlsx`, which you can open in Google Sheets (File → Import) with all formatting.
If several Google accounts are connected in Composio, set `LR_AI_GOOGLE_ACCOUNT` to the alias or id of the
one that should get the sheets. Otherwise the first connected account is used.

### API keys (optional, recommended)

Everything works without keys, but the public APIs are shared and sometimes throttle anonymous users:

| Variable | Why | Where |
|---|---|---|
| `OPENALEX_API_KEY` | reliable OpenAlex search, larger daily budget | free at [openalex.org](https://openalex.org) |
| `S2_API_KEY` | dedicated Semantic Scholar rate limit | free on request at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) |
| `OPENALEX_EMAIL` | OpenAlex polite pool | your email |

When a service refuses a request, LR-AI falls back to another one and tells you.

## Usage

In Claude Code:

```
/lr-ai:lit-review forecasting scientific impact with citation graphs
```

This runs the whole review in one go. To approve each step first:

```
/lr-ai:lit-review forecasting scientific impact with citation graphs --step
```

While a review runs, LR-AI pre-approves its own `lr.py` commands and file edits under `./lr-runs`, so Claude
Code doesn't ask about each one. It can still ask about other tools, such as Composio's Google Sheets calls
or the result files the screening agents write. Answer "Yes, and don't ask again", or switch to the
"accept edits" permission mode for the run.

Or use the steps on their own. The skills trigger from plain requests like "snowball these papers",
"screen the candidates", or "make a Google Sheet of the review":

| Skill | Step |
|---|---|
| `lr-ai:setup` | health check ("run the LR-AI doctor"), dependencies, API keys |
| `lr-ai:seed-search` | set up the review, seed papers |
| `lr-ai:database-search` | boolean keyword search |
| `lr-ai:snowball` | forward/backward snowballing |
| `lr-ai:screen-papers` | filters + subagent screening |
| `lr-ai:categorize-papers` | taxonomy, summaries, priorities |
| `lr-ai:export-sheet` | Excel + Google Sheet |

### Without Claude

The engine is a plain CLI ([full reference](docs/cli.md)):

```bash
python scripts/lr.py init "forecasting scientific impact with citation graphs" --name impact
# edit lr-runs/impact-<date>/config.yaml: research questions, seed.queries, search.queries, filters
python scripts/lr.py seed
python scripts/lr.py search
python scripts/lr.py filter
python scripts/lr.py snowball
python scripts/lr.py filter
python scripts/lr.py status
```

Screening and summaries need an LLM: `batches` writes self-describing batch files, and `apply` merges JSONL
results back, so any model or a human can fill them. See [`agents/paper-screener.md`](agents/paper-screener.md)
for the expected format.

Every phase can be run and checked on its own. See [docs/phases.md](docs/phases.md).

## Transparency and reproducibility

Every review lives in one folder (`lr-runs/<name>-<date>/`):
- `config.yaml`: the exact queries, filters and taxonomy
- `papers.jsonl`: every paper with its provenance (`seed:q1`, `search:openalex:q2`, `backward:<parent>`),
  the filter decision and screening reason
- `raw/`: what each API call returned
- `log.md`: a timestamped log of every step

API responses are cached, so re-running a step costs nothing and interrupted runs resume where they stopped.

## Limitations

- LLM screening is an assistant, not a replacement for your judgment. Check the core/skim decisions,
  especially borderline ones (`lr.py show --where status=skim`).
- Abstracts are missing for some publishers. Those papers are screened on the title only.
- Coverage depends on OpenAlex, Semantic Scholar and arXiv. Scopus, Web of Science and IEEE Xplore are not
  included (they need institutional licenses).

## Roadmap

- Web UI for screening (include/exclude with reasons) and a citation-graph view
- Updating an existing Google Sheet instead of creating a new one
- More sources (Crossref, PubMed, DBLP) and optional Scopus/IEEE adapters with your own keys

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
claude plugin validate .
```

Contributions are welcome. Please open an issue first for larger changes.

## Citation

If LR-AI helps your research, please cite it (see [`CITATION.cff`](CITATION.cff)).

## License

[MIT](LICENSE)
