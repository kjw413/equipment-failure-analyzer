"""Place the team's complete drilldown tables below its two TOP charts."""

import re
from copy import copy

from openpyxl.workbook.defined_name import DefinedName

from report.drilldown import MAIN_SHEET
from report.formatting import bounded_int

TABLE_HEADER = 27
FIRST_RANK = TABLE_HEADER + 1


def integer_times(builder):
    """Change displayed precision only, retaining exact source and formula values."""
    for sheet in builder.wb:
        for row in sheet:
            for cell in row:
                if "%" not in cell.number_format:
                    cell.number_format = re.sub(r"\.0+", "", cell.number_format)


def complete_rank_tables(builder):
    book = builder.wb
    if MAIN_SHEET not in book:
        return
    ws, helper = book[MAIN_SHEET], book["_issue_rank"]
    top_n = bounded_int(
        builder.r.config_snapshot.get("final_report", {}).get("summary_top_n"), 5, 10
    )
    levels = {key: [] for key in ("asset", "module", "part")}
    for row in range(2, helper.max_row + 1):
        levels[helper.cell(row, 8).value].append(row)
    capacity = max(top_n, *(len(rows) for rows in levels.values()))
    header_styles = [copy(c._style) for c in ws[TABLE_HEADER][:12]]
    body_styles = [copy(c._style) for c in ws[FIRST_RANK][:12]]
    body_height = ws.row_dimensions[FIRST_RANK].height
    header_height = ws.row_dimensions[TABLE_HEADER].height
    for area in list(ws.merged_cells.ranges):
        if area.min_row >= TABLE_HEADER:
            ws.unmerge_cells(str(area))
    for row in ws.iter_rows(
        min_row=TABLE_HEADER, max_row=max(ws.max_row, FIRST_RANK + capacity - 1), max_col=12
    ):
        for cell in row:
            cell.value = None
            cell._style = None
            builder.cache.values.pop((ws.title, cell.coordinate), None)
    for row in range(TABLE_HEADER, FIRST_RANK + capacity):
        ws.row_dimensions[row].height = body_height
    ws.row_dimensions[TABLE_HEADER].height = header_height
    end = helper.max_row
    active = levels["asset"]
    for left, rank_col, metric in ((1, "F", "count"), (7, "G", "time")):
        letters = [chr(64 + left + offset) for offset in range(6)]
        for offset, label in enumerate(("순위", "라인", None, "건수", "정지(분)", "비중")):
            cell = ws.cell(TABLE_HEADER, left + offset, label)
            cell._style = copy(header_styles[left + offset - 1])
        ws.merge_cells(
            start_row=TABLE_HEADER, end_row=TABLE_HEADER, start_column=left + 1, end_column=left + 2
        )
        builder.cache.set(ws, f"{letters[1]}{TABLE_HEADER}", "='_drill_state'!B3", "라인")
        ordered = sorted(
            active,
            key=lambda r: (
                builder.cache.values.get((helper.title, f"{rank_col}{r}"), float("inf"))
                or float("inf")
            ),
        )
        if metric == "time":
            ordered = [r for r in ordered if builder.cache.values.get((helper.title, f"C{r}"), 0)]
        for index in range(capacity):
            row = FIRST_RANK + index
            for offset in range(6):
                ws.cell(row, left + offset)._style = copy(body_styles[left + offset - 1])
            ws.merge_cells(start_row=row, end_row=row, start_column=left + 1, end_column=left + 2)
            label_cell = f"{letters[1]}{row}"
            match = f"MATCH({index + 1},'_issue_rank'!${rank_col}$2:${rank_col}${end},0)"
            item = ordered[index] if index < len(ordered) else None
            builder.cache.set(
                ws,
                f"{letters[0]}{row}",
                f'=IF({label_cell}="","",{index + 1})',
                index + 1 if item else "",
            )
            for offset, helper_col in ((1, "A"), (3, "B"), (4, "D")):
                cached = (
                    (
                        helper.cell(item, 1).value
                        if offset == 1
                        else builder.cache.values.get((helper.title, f"{helper_col}{item}"), "")
                    )
                    if item
                    else ""
                )
                address = f"{letters[offset]}{row}"
                builder.cache.set(
                    ws,
                    address,
                    f"=IFERROR(INDEX('_issue_rank'!${helper_col}$2:${helper_col}${end},{match}),\"\")",
                    cached,
                )
                ws[address].number_format = "General" if offset == 1 else "#,##0"
            value_cell = f"{letters[3 if metric == 'count' else 4]}{row}"
            denominator = "$C$9" if metric == "count" else "$E$9"
            value = builder.cache.values.get((ws.title, value_cell), "")
            total = builder.cache.values.get((ws.title, denominator.replace("$", "")), "")
            share = (
                value / total
                if isinstance(value, (int, float)) and isinstance(total, (int, float)) and total
                else ""
            )
            builder.cache.set(
                ws,
                f"{letters[5]}{row}",
                f'=IF(OR({label_cell}="",{denominator}="",{denominator}=0,{value_cell}=""),"",{value_cell}/{denominator})',
                share,
            )
            ws[f"{letters[5]}{row}"].number_format = "0.0%"
    for name, column in (("_Drill_CountLabels", "B"), ("_Drill_TimeLabels", "H")):
        book.defined_names.add(
            DefinedName(
                name,
                attr_text=f"'{ws.title}'!${column}${FIRST_RANK}:${column}${FIRST_RANK + capacity - 1}",
            )
        )
    for row in range(FIRST_RANK, FIRST_RANK + capacity):
        ws.row_dimensions[row].hidden = bool(
            getattr(builder, "macro_navigation", False)
        ) and row >= FIRST_RANK + len(active)
    shown = len(active) if getattr(builder, "macro_navigation", False) else capacity
    ws.print_area = f"A1:L{FIRST_RANK + max(1, shown) - 1}"
    # The native XML restoration applies the same move to the preserved graphics.
    builder._locked_template["sheets"][ws.title].update(chart_row_shift=0, rank_row_shift=0)


def charts_before_tables(builder):
    """Move complete data regions without breaking formulas pointing into them."""
    from openpyxl.cell.cell import MergedCell
    from openpyxl.utils import get_column_letter

    from report.locked_template import _formula

    book, maps = builder.wb, {}
    regions = [(name, 12, 32, 12) for name in ("별첨. 라인별분석", "별첨. 상세설비별분석")]
    for name, first, destination, chart_row in regions:
        if name not in book:
            continue
        ws = book[name]
        if name == "04.고장추이":
            # The reference's narrow L column otherwise clips the right-hand chart.
            ws.column_dimensions["L"].width = ws.column_dimensions["A"].width
        last, width = ws.max_row, ws.max_column
        offset = destination - first
        mapping = {
            f"{get_column_letter(col)}{row}": f"{get_column_letter(col)}{row + offset}"
            for row in range(first, last + 1)
            for col in range(1, width + 1)
        }
        maps[name] = mapping
        cells = [
            (
                cell.row,
                cell.column,
                cell.value,
                cell.data_type,
                copy(cell._style),
                builder.cache.values.pop((name, cell.coordinate), None),
            )
            for row in ws.iter_rows(min_row=first, max_row=last)
            for cell in row
            if not isinstance(cell, MergedCell)
        ]
        merges = [area for area in ws.merged_cells.ranges if area.min_row >= first]
        for area in merges:
            ws.unmerge_cells(str(area))
        heights = {row: ws.row_dimensions[row].height for row in range(first, last + 1)}
        for row in ws.iter_rows(min_row=first, max_row=last):
            for cell in row:
                cell.value, cell._style = None, None
        for row, col, value, data_type, style, cached in cells:
            cell = ws.cell(row + offset, col, value)
            cell.data_type, cell._style = data_type, style
            if data_type == "f":
                builder.cache.values[(name, cell.coordinate)] = cached
        for area in merges:
            ws.merge_cells(
                start_row=area.min_row + offset,
                end_row=area.max_row + offset,
                start_column=area.min_col,
                end_column=area.max_col,
            )
        for row, height in heights.items():
            ws.row_dimensions[row + offset].height = height
        state = builder._locked_template["sheets"].get(name)
        if state is not None:
            state.update(
                cell_map=mapping,
                chart_row_shift=chart_row
                - 1
                - (ws._charts[0].anchor._from.row - state.get("extra", 0)),
            )
        for chart in ws._charts:
            if isinstance(chart.anchor, str):
                chart.anchor = f"B{chart_row}"
                continue
            old = chart.anchor._from.row
            chart.anchor._from.row = chart_row - 1
            if hasattr(chart.anchor, "to"):
                chart.anchor.to.row += chart_row - 1 - old
        ws.print_area = f"A1:{get_column_letter(max(12, width))}{last + offset}"
        ws.page_setup.fitToHeight = 0 if last - first > 12 else 1
        if name.startswith("별첨"):
            ws.freeze_panes = f"H{destination + 1}"
            key = "equipment" if name == "별첨. 라인별분석" else "line"
            book.defined_names.add(
                DefinedName(
                    "_Breakdown_" + key + "Labels",
                    attr_text=f"'{name}'!$B${destination + 1}:$B${last + offset}",
                )
            )
            for row in range(destination + 1, last + offset + 1):
                ws.row_dimensions[row].hidden = bool(
                    getattr(builder, "macro_navigation", False)
                ) and not bool(builder.cache.values.get((name, f"B{row}"), ""))
    names = {name: name for name in maps}
    for ws in book:
        for row in ws:
            for cell in row:
                if cell.data_type == "f":
                    cell.value = _formula(cell.value, ws.title, maps, names)


def apply_rank_layout(builder):
    complete_rank_tables(builder)
    charts_before_tables(builder)
    integer_times(builder)
