---
name: export-sheet
description: Export a literature review to a styled, categorized Google Sheet (via Composio's Google Sheets tools) and an Excel file - grouped category rows, color-coded status and priority, reading-status dropdowns, filters, plus Overview and Method (PRISMA counts) tabs. Use when the user asks for the review as a Google Sheet, spreadsheet, Excel file, or table.
---

# Export (step 6)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>` (see `${CLAUDE_PLUGIN_ROOT}/docs/cli.md`). If the path still contains a `$` placeholder, the plugin root is two folders above this skill's base directory.

## 1. Excel file (always)
`lr.py export --run <dir>` writes `<run>/papers.xlsx` and prints the Google Sheet title. The workbook has
three tabs:
- **Papers**: category and sub-category header rows, papers sorted core → skim, then priority, then
  citations. Status and priority are color-coded. Reading-status and priority columns have dropdowns. There
  is a filter, and the header row and title column are frozen.
- **Overview**: counts by category, year and venue.
- **Method**: queries, sources, filters and the PRISMA-style flow.

## 2. Google Sheet via Composio (if available)
Composio tools are named like `mcp__<id>__COMPOSIO_*`. If none are present, skip to step 3.
1. Call `COMPOSIO_SEARCH_TOOLS` with the use case "create a google sheet and write values". This gives
   you a `session_id` and the Google Sheets connection status.
   - No active connection: call `COMPOSIO_MANAGE_CONNECTIONS` so the user can connect, or fall back to step 3.
   - Several connected accounts: ask the user which one, and pass its id as `--account` below.
2. Create the spreadsheet: `COMPOSIO_MULTI_EXECUTE_TOOL` with `GOOGLESHEETS_CREATE_GOOGLE_SHEET1`
   `{ "title": "<title printed by export>" }`. Note the `spreadsheetId`. Note the first tab's `sheetId`
   if the response shows it (normally 0; check with `GOOGLESHEETS_GET_SPREADSHEET_INFO` if unsure).
3. `lr.py sheet-plan --run <dir> --spreadsheet-id <ID> [--sheet-id <first tab id>] [--account <acc>]`.
   This writes numbered plan files to `<run>/export/gsheets/`.
4. Execute the files in order. Read each file and call `COMPOSIO_MULTI_EXECUTE_TOOL` once with
   `tools` = the file's `tools` array, copied verbatim, plus `session_id` and
   `sync_response_to_workbench: false`. Calls within a file are independent.
   - If calls fail with rate limits (Sheets allows about 60 writes per minute), wait about 60 seconds and
     re-send only the failed items.
   - If a call fails on its arguments, check the schema with `COMPOSIO_GET_TOOL_SCHEMAS`, fix that call,
     and continue.
   - With many `values_*` files (large reviews), delegate executing all plan files to one general-purpose
     subagent. Give it the file list and these rules, to keep the main context small.
5. Give the user the sheet URL (also saved in `<run>/sheet_url.txt`).

## 3. Without Composio
Tell the user to upload `papers.xlsx` to Google Drive and open it with Google Sheets (or use
File → Import in Sheets). Colors, dropdowns, frozen panes and filters carry over.
