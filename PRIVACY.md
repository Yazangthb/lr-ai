# Privacy policy

LR-AI is an open-source plugin for Claude Code, maintained by Yazan Alnakri. This policy describes what LR-AI
does with data.

Last updated: 2026-09-30

## Summary

LR-AI runs on your computer. It has no server of its own, collects no telemetry and sends nothing to its
author. It contacts only the services below, and only to carry out the review you asked for.

## What LR-AI sends, and to whom

| Service | What LR-AI sends | Why |
|---|---|---|
| OpenAlex (`api.openalex.org`) | Your queries, paper identifiers and titles, plus `OPENALEX_API_KEY` and `OPENALEX_EMAIL` if you set them | Search, snowballing, metadata |
| Semantic Scholar (`api.semanticscholar.org`) | Your queries, paper identifiers and titles, plus `S2_API_KEY` if you set it | Search, snowballing, metadata |
| arXiv (`export.arxiv.org`) | Your queries and paper titles | Search, title lookups |
| Google Sheets, through your own Composio connection | The review: papers, summaries, categories and the Method tab | Building the sheet in your Google account |
| PyPI (`pypi.org`) | A download request for `pyyaml` and `openpyxl`, only if they're missing and you approve the install | Setup |

Each service handles these requests under its own terms and privacy policy.

## Claude

Screening, summaries and categories are written by Claude in your own Claude session. The paper data this
needs (titles, abstracts and metadata) and your review settings are processed there under your agreement with
Anthropic, like any other Claude Code task.

## What LR-AI stores

Everything stays on your computer, in the review's folder (`lr-runs/<name>-<date>/`): your settings, the papers
found, screening decisions, summaries, the exported workbook and cached API responses. Deleting the folder
deletes all of it.

## API keys and email

`OPENALEX_API_KEY`, `S2_API_KEY` and `OPENALEX_EMAIL` are optional. LR-AI reads them from your environment
variables and sends each one only to the service it belongs to. It doesn't write them to the review folder:
cached responses are stored under hashed names, and error messages mask them.

## Changes and contact

Changes to this policy are published in this file, and the repository history shows each one. For questions,
open an issue at <https://github.com/YAZANGTHB/lr-ai/issues>.
