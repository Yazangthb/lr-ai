"""Google Sheets export as a plan of Composio tool calls.

Composio's Google Sheets toolkit has no raw batchUpdate, so the plan uses its high-level tools
(values, formatting, conditional formats, validation, filter). Each plan file holds the `tools` array for
one COMPOSIO_MULTI_EXECUTE_TOOL call; calls inside a file are independent and may run in parallel.
Group/sub-group row styling is done with conditional-format rules keyed on the "▌"/"▸" row markers,
which keeps the number of calls small and survives sorting.
"""
from __future__ import annotations

import json
import os

from .layout import COLORS, GROUP_MARK, PRIORITY_CHOICES, READING_CHOICES, SUBGROUP_MARK, Tab

OVERVIEW_ID, METHOD_ID = 1001, 1002


def _letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _rgb(hex_color: str) -> dict:
    h = hex_color.lstrip("#")
    return {"red": round(int(h[0:2], 16) / 255, 4), "green": round(int(h[2:4], 16) / 255, 4),
            "blue": round(int(h[4:6], 16) / 255, 4)}


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v  # keep text as text under USER_ENTERED
    return v


def _runs(values: list) -> list[tuple[int, int, object]]:
    """Group consecutive equal values: [(start, end_exclusive, value)]."""
    runs: list[tuple[int, int, object]] = []
    for i, v in enumerate(values):
        if runs and runs[-1][2] == v and runs[-1][1] == i:
            runs[-1] = (runs[-1][0], i + 1, v)
        else:
            runs.append((i, i + 1, v))
    return runs


class _Plan:
    def __init__(self, spreadsheet_id: str, account: str | None):
        self.sid = spreadsheet_id
        self.account = account
        self.files: list[tuple[str, str, list[dict]]] = []

    def call(self, slug: str, arguments: dict) -> dict:
        item = {"tool_slug": slug, "arguments": arguments}
        if self.account:
            item["account"] = self.account
        return item

    def fmt(self, sheet_id: int, a1: str, *, bg: str = "#FFFFFF", fg: str | None = None, bold: bool = False,
            wrap: str | None = None, valign: str = "TOP", size: int = 10) -> dict:
        args = {"spreadsheet_id": self.sid, "worksheet_id": sheet_id, "range": a1, "background_color": bg,
                "bold": bold, "fontSize": size, "vertical_alignment": valign}
        if fg:
            args["text_color"] = fg
        if wrap:
            args["wrap_strategy"] = wrap
        return self.call("GOOGLESHEETS_FORMAT_CELL", args)

    def widths(self, sheet_id: int, widths: list[int]) -> list[dict]:
        return [self.call("GOOGLESHEETS_UPDATE_DIMENSION_PROPERTIES", {
            "spreadsheet_id": self.sid, "sheet_id": sheet_id, "dimension": "COLUMNS",
            "start_index": a, "end_index": b, "pixel_size": w}) for a, b, w in _runs(widths)]

    def rule(self, sheet_id: int, ranges: list[tuple[int, int, int, int]], condition: dict, bg: str,
             fg: str | None = None, bold: bool = False) -> dict:
        fmt: dict = {"backgroundColor": _rgb(bg)}
        text: dict = {"bold": bold} if bold else {}
        if fg:
            text["foregroundColor"] = _rgb(fg)
        if text:
            fmt["textFormat"] = text
        return self.call("GOOGLESHEETS_MUTATE_CONDITIONAL_FORMAT_RULES", {
            "spreadsheet_id": self.sid, "sheet_id": sheet_id, "operation": "ADD",
            "rule": {"ranges": [{"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                                 "startColumnIndex": c0, "endColumnIndex": c1} for r0, r1, c0, c1 in ranges],
                     "booleanRule": {"condition": condition, "format": fmt}}})


def build_plan(tabs: list[Tab], spreadsheet_id: str, papers_sheet_id: int = 0, account: str | None = None,
               chunk_chars: int = 40000) -> list[tuple[str, str, list[dict]]]:
    papers, overview, method = tabs
    plan = _Plan(spreadsheet_id, account)
    ids = {"Papers": papers_sheet_id, "Overview": OVERVIEW_ID, "Method": METHOD_ID}
    n, ncols = len(papers.rows), len(papers.widths)
    last = _letter(ncols - 1)

    # 1. tabs
    setup = [plan.call("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
        "spreadsheetId": spreadsheet_id,
        "updateSheetProperties": {
            "properties": {"sheetId": papers_sheet_id, "title": "Papers",
                           "gridProperties": {"rowCount": max(1000, n + 50), "columnCount": max(26, ncols),
                                              "frozenRowCount": 1, "frozenColumnCount": 1},
                           "tabColorStyle": {"rgbColor": _rgb(COLORS["group"][0])}},
            "fields": "title,gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount,"
                      "gridProperties.frozenColumnCount,tabColorStyle"}})]
    for tab in (overview, method):
        setup.append(plan.call("GOOGLESHEETS_ADD_SHEET", {
            "spreadsheet_id": spreadsheet_id,
            "properties": {"title": tab.name, "sheetId": ids[tab.name],
                           "gridProperties": {"rowCount": max(100, len(tab.rows) + 20), "columnCount": 10}}}))
    plan.files.append(("setup", "Rename the first tab to Papers and add the Overview and Method tabs", setup))

    # 2. values (chunked so each call stays a manageable size)
    def value_calls(tab: Tab) -> list[dict]:
        calls, start, rows, size = [], 0, [], 0
        for i, row in enumerate(tab.rows):
            clean = [_cell(v) for v in row]
            rows.append(clean)
            size += len(json.dumps(clean, ensure_ascii=False))
            if size >= chunk_chars or i == len(tab.rows) - 1:
                a1 = f"'{tab.name}'!A{start + 1}:{_letter(len(row) - 1)}{i + 1}"
                calls.append(plan.call("GOOGLESHEETS_UPDATE_VALUES_BATCH", {
                    "spreadsheet_id": spreadsheet_id, "valueInputOption": "USER_ENTERED",
                    "data": [{"range": a1, "majorDimension": "ROWS", "values": rows}]}))
                start, rows, size = i + 1, [], 0
        return calls

    paper_chunks = value_calls(papers)
    for k, c in enumerate(paper_chunks, 1):
        plan.files.append((f"values_{k:02d}", f"Write Papers rows (part {k} of {len(paper_chunks)})", [c]))
    plan.files.append(("values_summary", "Write the Overview and Method tabs",
                       value_calls(overview) + value_calls(method)))

    # 3. formatting and column widths
    pid = papers_sheet_id
    hdr_bg, hdr_fg = COLORS["header"]
    fmt = [plan.fmt(pid, f"A1:{last}1", bg=hdr_bg, fg=hdr_fg, bold=True, wrap="WRAP", valign="MIDDLE")]
    if n > 1:
        wraps = [i in papers.wrap_cols for i in range(ncols)]
        for a, b, wrap in _runs(wraps):
            fmt.append(plan.fmt(pid, f"{_letter(a)}2:{_letter(b - 1)}{n}", wrap="WRAP" if wrap else "CLIP"))
    fmt += plan.widths(pid, papers.widths)
    for tab in (overview, method):
        tid, tl = ids[tab.name], _letter(len(tab.widths) - 1)
        fmt.append(plan.fmt(tid, "A1", bold=True, size=14, valign="MIDDLE"))
        for a, b, kind in _runs(tab.kinds):
            if kind == "kv":
                fmt.append(plan.fmt(tid, f"A{a + 1}:A{b}", bg=COLORS["key"][0], fg=COLORS["key"][1], bold=True))
                fmt.append(plan.fmt(tid, f"B{a + 1}:{tl}{b}", wrap="WRAP"))
            elif kind == "section":
                fmt.append(plan.fmt(tid, f"A{a + 1}:{tl}{b}", bg=hdr_bg, fg=hdr_fg, bold=True, valign="MIDDLE"))
        fmt += plan.widths(tid, tab.widths)
    plan.files.append(("format", "Header style, text wrapping and column widths", fmt))

    # 4. conditional formats, dropdowns, filter
    rules: list[dict] = []
    if n > 1:
        keys = [c.key for c in papers.columns]
        body = (1, n)

        def cols(*names: str) -> list[int]:
            return [keys.index(k) for k in names if k in keys]

        for mark, kind in ((GROUP_MARK, "group"), (SUBGROUP_MARK, "subgroup")):
            bg, fg = COLORS[kind]
            rules.append(plan.rule(pid, [(*body, 0, ncols)], {"type": "CUSTOM_FORMULA", "values": [
                {"userEnteredValue": f'=LEFT($A2,1)="{mark}"'}]}, bg, fg, bold=True))
        for ci in cols("status"):
            for status in ("core", "skim", "exclude"):
                bg, fg = COLORS[status]
                rules.append(plan.rule(pid, [(*body, ci, ci + 1)], {"type": "TEXT_STARTS_WITH", "values": [
                    {"userEnteredValue": status}]}, bg, fg, bold=True))
        for ci in cols("priority"):
            for prio in PRIORITY_CHOICES:
                bg, fg = COLORS[prio]
                rules.append(plan.rule(pid, [(*body, ci, ci + 1)], {"type": "TEXT_EQ", "values": [
                    {"userEnteredValue": prio}]}, bg, fg, bold=prio == "high"))
        for ci in cols("reading"):
            skip = set(cols("status", "priority"))
            spans = [(a, b) for a, b, keep in _runs([i not in skip for i in range(ncols)]) if keep]
            rules.append(plan.rule(pid, [(*body, a, b) for a, b in spans], {"type": "CUSTOM_FORMULA", "values": [
                {"userEnteredValue": f'=${_letter(ci)}2="studied"'}]}, COLORS["studied"][0]))
        for key, choices in (("priority", PRIORITY_CHOICES), ("reading", READING_CHOICES)):
            for ci in cols(key):
                rules.append(plan.call("GOOGLESHEETS_SET_DATA_VALIDATION_RULE", {
                    "spreadsheet_id": spreadsheet_id, "sheet_id": pid, "mode": "SET",
                    "validation_type": "ONE_OF_LIST", "values": choices, "strict": False, "show_custom_ui": True,
                    "start_row_index": 1, "end_row_index": n, "start_column_index": ci, "end_column_index": ci + 1}))
        rules.append(plan.call("GOOGLESHEETS_SET_BASIC_FILTER", {
            "spreadsheetId": spreadsheet_id,
            "filter": {"range": {"sheet_id": pid, "start_row_index": 0, "end_row_index": n,
                                 "start_column_index": 0, "end_column_index": ncols}}}))
    if rules:
        plan.files.append(("rules", "Status/priority colors, category rows, dropdowns and filter", rules))
    return plan.files


def write_plan(files: list[tuple[str, str, list[dict]]], folder: str) -> list[str]:
    os.makedirs(folder, exist_ok=True)
    for old in os.listdir(folder):
        if old.endswith(".json"):
            os.remove(os.path.join(folder, old))
    paths = []
    for i, (name, description, tools) in enumerate(files, 1):
        path = os.path.join(folder, f"{i:02d}_{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"description": description, "tools": tools}, f, ensure_ascii=False, indent=1)
        paths.append(path)
    return paths
