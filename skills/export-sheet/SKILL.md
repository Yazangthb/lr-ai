---
name: export-sheet
description: Export a literature review to a styled, categorized Google Sheet (via Composio's Google Sheets tools) and an Excel file - grouped category rows, color-coded status and priority, reading-status dropdowns, filters, plus Overview and Method (PRISMA counts) tabs. Use when the user asks for the review as a Google Sheet, spreadsheet, Excel file, or table.
allowed-tools:
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" *)
  - Edit(lr-runs/**)
---

# Export (step 6)

CLI: `python "${CLAUDE_PLUGIN_ROOT}/scripts/lr.py" <command> --run <run dir>`. Run it with the Bash tool exactly
as written, so it needs no permission prompt. `lr.py <command> --help` lists the options. If the path still
contains a `$` placeholder, the plugin root is two folders above this skill's base directory.

Automatic by default: make the choices below yourself and keep going. Lines marked **Checkpoint** apply only
in step-by-step mode (the user asked to confirm steps, e.g. `/lr-ai:lit-review --step`): there, stop and
wait for the user's reply.

## 1. Excel file (always)
`lr.py export --run <dir>` writes `<run>/papers.xlsx` and prints the Google Sheet title, plus the Google
account if `LR_AI_GOOGLE_ACCOUNT` is set. The workbook has three tabs:
- **Papers**: category and sub-category header rows, papers sorted core → skim, then priority, then
  citations. Status and priority are color-coded. Reading-status and priority columns have dropdowns. There
  is a filter, and the header row and title column are frozen.
- **Overview**: counts by category, year and venue.
- **Method**: queries, sources, filters and the PRISMA-style flow.

## 2. Google Sheet via Composio (if available)
Composio tools are named like `mcp__<id>__COMPOSIO_*`. If none are present, skip to step 3.
1. Call `COMPOSIO_SEARCH_TOOLS` with the use case "create a google sheet and write values". This gives
   you a `session_id` and the Google Sheets connection status.
   - No active connection: don't wait for one. Go to step 3, and in the final report say that the sheet
     can be made later: connect Google Sheets in Composio, then ask to "export the review to Google
     Sheets". **Checkpoint:** offer to connect now with `COMPOSIO_MANAGE_CONNECTIONS`.
   - Several connected accounts: Composio needs the account in every call. Use the account the user named,
     else the one `lr.py export` printed (`LR_AI_GOOGLE_ACCOUNT`), else the first account listed. Name it
     in the final report. **Checkpoint:** if the user named none, ask which one.
2. Create the spreadsheet: `COMPOSIO_MULTI_EXECUTE_TOOL` with `GOOGLESHEETS_CREATE_GOOGLE_SHEET1`
   `{ "title": "<title printed by export>" }`, and `"account": "<account>"` in the tool entry when you
   chose one. Note the `spreadsheetId`. Note the first tab's `sheetId` if the response shows it (normally 0;
   check with `GOOGLESHEETS_GET_SPREADSHEET_INFO` if unsure).
3. `lr.py sheet-plan --run <dir> --spreadsheet-id <ID> [--sheet-id <first tab id>] [--account <account>]`.
   This writes numbered plan files to `<run>/export/gsheets/`. Without `--account`, it uses
   `LR_AI_GOOGLE_ACCOUNT` when that is set.
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
