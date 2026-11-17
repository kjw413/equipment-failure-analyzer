"""Apply the agreed Excel writing rules after the native report is assembled.

Only visible worksheets gain the left margin. References are changed as parsed
Excel range operands, so criteria strings and hidden fact coordinates stay intact.
This supports the A1 references, tables, selectors and drawings emitted by the
report writer; external-workbook and three-dimensional references are preserved.
"""

from __future__ import annotations

import re
from copy import copy
from datetime import date, datetime

from openpyxl.cell.cell import MergedCell
from openpyxl.chart.text import RichText
from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties
from openpyxl.drawing.text import Font as DrawingFont
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
from openpyxl.worksheet.dimensions import ColumnDimension
from openpyxl.worksheet.print_settings import PrintArea
from openpyxl.worksheet.table import TableStyleInfo

FONT_NAME = "KoPubWorld돋움체 Medium"
BLACK = "222222"
INPUT_BLUE = "2155A0"
HEADER_FILL = "F2F2F2"
INCREASE_FORMAT = '[Red]"▲ "#,##0.0;[Blue]"▼ "#,##0.0;"-"'
INCREASE_INT_FORMAT = '[Red]"▲ "#,##0;[Blue]"▼ "#,##0;"-"'
INCREASE_PERCENT_FORMAT = '[Red]"▲ "0.0%;[Blue]"▼ "0.0%;"-"'
_LINE = Side(style="thin", color="D9D9D9")
_CELL = re.compile(r"(?P<absolute>\$?)(?P<column>[A-Za-z]{1,3})(?P<row>\$?\d+)?$")
_REFERENCE = re.compile(
    r"(?:(?P<sheet>'(?:[^']|'')+'|[^'!]+)!)?"
    r"(?P<range>\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?"
    r"|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?\d+:\$?\d+)$"
)


def _sheet_name(value):
    return value[1:-1].replace("''", "'") if value.startswith("'") else value


def _shift_address(address):
    """Translate columns, retaining absolute markers and whole-row ranges."""
    parts = []
    for part in address.split(":"):
        match = _CELL.fullmatch(part)
        if not match:
            parts.append(part)
            continue
        column = column_index_from_string(match["column"]) + 1
        parts.append(match["absolute"] + get_column_letter(column) + (match["row"] or ""))
    return ":".join(parts)


def _range_operand(value, current_sheet, visible):
    match = _REFERENCE.fullmatch(value)
    if not match:
        return value
    sheet = match["sheet"]
    # Workbook links and 3D ranges are outside the report writer's vocabulary.
    if sheet and ("[" in sheet or "]" in sheet or ":" in _sheet_name(sheet)):
        return value
    target = _sheet_name(sheet) if sheet else current_sheet
    if target not in visible:
        return value
    prefix = sheet + "!" if sheet else ""
    return prefix + _shift_address(match["range"])


def _formula(value, current_sheet, visible):
    if not isinstance(value, str) or not value:
        return value
    leading_equal = value.startswith("=")
    parsed = Tokenizer(value if leading_equal else "=" + value)
    for token in parsed.items:
        if token.type == "OPERAND" and token.subtype == "RANGE":
            token.value = _range_operand(token.value, current_sheet, visible)
    translated = "".join(token.value for token in parsed.items)
    return ("=" if leading_equal else "") + translated


def _ranges(value):
    return MultiCellRange([CellRange(_shift_address(str(part))) for part in value.ranges])


def _defined_names(names, current_sheet, visible):
    for name in names.values():
        if name.attr_text:
            name.attr_text = _formula(name.attr_text, current_sheet, visible)


def _hyperlink(link, current_sheet, visible):
    for attribute in ("target", "location"):
        value = getattr(link, attribute, None)
        if not value or (attribute == "target" and not value.startswith("#")):
            continue
        prefix = "#" if value.startswith("#") else ""
        reference = value[1:] if prefix else value
        translated = _range_operand(reference, current_sheet, visible)
        # Internal navigation points to the relocated title instead of blank row 1.
        match = _REFERENCE.fullmatch(reference)
        if match and match["range"].replace("$", "").upper() == "A1":
            target = _sheet_name(match["sheet"]) if match["sheet"] else current_sheet
            if target in visible:
                translated = translated[:-1] + "2"
        setattr(link, attribute, prefix + translated)


def _drawing_anchor(drawing):
    anchor = drawing.anchor
    if isinstance(anchor, str):
        drawing.anchor = _shift_address(anchor)
    elif hasattr(anchor, "_from"):
        anchor._from.col += 1
        if hasattr(anchor, "to"):
            anchor.to.col += 1
    elif hasattr(anchor, "pos"):
        # The one-character margin occupies 12 pixels in Excel's standard width.
        anchor.pos.x += 12 * 9525


def _chart_references(chart, current_sheet, visible):
    for series in chart.series:
        for data in ("cat", "val", "xVal", "yVal", "zVal", "bubbleSize", "tx"):
            source = getattr(series, data, None)
            if source is None:
                continue
            for kind in ("numRef", "strRef", "multiLvlStrRef"):
                reference = getattr(source, kind, None)
                if reference is not None and reference.f:
                    reference.f = _formula(reference.f, current_sheet, visible)
    title = getattr(chart, "title", None)
    reference = getattr(getattr(title, "tx", None), "strRef", None)
    if reference is not None and reference.f:
        reference.f = _formula(reference.f, current_sheet, visible)
    _style_chart(chart)
    # Combined charts own additional series that are not in the primary chart.
    for subchart in getattr(chart, "_charts", ()):
        if subchart is not chart:
            _chart_references(subchart, current_sheet, visible)


def _rich_text(value, size):
    value = value or RichText(p=[Paragraph()])
    for paragraph in value.p:
        if paragraph.pPr is None:
            paragraph.pPr = ParagraphProperties()
        properties = copy(paragraph.pPr.defRPr) if paragraph.pPr.defRPr else CharacterProperties()
        properties.sz = size * 100
        properties.latin = DrawingFont(typeface=FONT_NAME)
        properties.ea = DrawingFont(typeface=FONT_NAME)
        paragraph.pPr.defRPr = properties
        for run in paragraph.r:
            run.rPr = copy(properties)
        paragraph.endParaRPr = copy(properties)
    return value


def _style_chart(chart):
    for element in (chart.title, getattr(chart, "legend", None)):
        if element is not None:
            element.txPr = _rich_text(element.txPr, 14 if element is chart.title else 11)
            rich = getattr(getattr(element, "tx", None), "rich", None)
            if rich is not None:
                _rich_text(rich, 14 if element is chart.title else 11)
    for name in ("x_axis", "y_axis", "z_axis"):
        axis = getattr(chart, name, None)
        if axis is not None:
            axis.txPr = _rich_text(axis.txPr, 11)
            if axis.title is not None:
                axis.title.txPr = _rich_text(axis.title.txPr, 11)
                rich = getattr(getattr(axis.title, "tx", None), "rich", None)
                if rich is not None:
                    _rich_text(rich, 11)
    if getattr(chart, "dLbls", None) is not None:
        chart.dLbls.txPr = _rich_text(chart.dLbls.txPr, 11)


def _filter_references(auto_filter):
    if auto_filter is None:
        return
    if auto_filter.ref:
        auto_filter.ref = _shift_address(auto_filter.ref)
    _sort_references(auto_filter.sortState)


def _sort_references(state):
    if state is not None:
        if state.ref:
            state.ref = _shift_address(state.ref)
        for condition in state.sortCondition:
            if condition.ref:
                condition.ref = _shift_address(condition.ref)


def _worksheet_references(ws, visible, shifted):
    for cell in list(ws._cells.values()):
        if cell.data_type == "f":
            cell.value = _formula(cell.value, ws.title, visible)
        if getattr(cell, "hyperlink", None):
            _hyperlink(cell.hyperlink, ws.title, visible)
            if shifted:
                cell.hyperlink.ref = _shift_address(cell.hyperlink.ref)
    for validation in ws.data_validations.dataValidation:
        if shifted:
            validation.sqref = _ranges(validation.sqref)
        for attr in ("formula1", "formula2"):
            value = getattr(validation, attr)
            if value:
                setattr(validation, attr, _formula(value, ws.title, visible))
    old_rules = list(ws.conditional_formatting._cf_rules.items())
    ws.conditional_formatting._cf_rules.clear()
    for conditional, rules in old_rules:
        target = copy(conditional)
        if shifted:
            target.sqref = _ranges(conditional.sqref)
        for rule in rules:
            if rule.formula:
                rule.formula = [_formula(value, ws.title, visible) for value in rule.formula]
        ws.conditional_formatting._cf_rules[target] = rules
    for table in ws.tables.values():
        for column in table.tableColumns:
            for attr in ("calculatedColumnFormula", "totalsRowFormula"):
                value = getattr(column, attr, None)
                if value is not None and value.text:
                    value.text = _formula(value.text, ws.title, visible)
        if shifted:
            table.ref = _shift_address(table.ref)
            _filter_references(table.autoFilter)
            _sort_references(table.sortState)
    _defined_names(ws.defined_names, ws.title, visible)
    for chart in ws._charts:
        _chart_references(chart, ws.title, visible)
        if shifted:
            _drawing_anchor(chart)
    if not shifted:
        return
    for image in ws._images:
        _drawing_anchor(image)
    _filter_references(ws.auto_filter)
    if ws.freeze_panes:
        ws.freeze_panes = _shift_address(ws.freeze_panes)
    if ws.print_area:
        ws.print_area = [
            _shift_address(str(area)) for area in PrintArea.from_string(ws.print_area).ranges
        ]
    if ws.print_title_cols:
        ws.print_title_cols = _shift_address(ws.print_title_cols)
    for page_break in ws.col_breaks.brk:
        page_break.id += 1


def _move_visible_cells(ws):
    merged = list(ws.merged_cells.ranges)
    title_span = next(
        (area.max_col for area in merged if area.min_col == 1 and area.min_row == 1),
        min(ws.max_column, 12),
    )
    title, scope = ws["A1"].value, ws["A3"].value
    for area in merged:
        ws.unmerge_cells(str(area))
    cells = list(ws._cells.values())
    ws._cells = {}
    for cell in cells:
        if not isinstance(cell, MergedCell):
            cell.column += 1
            ws._cells[(cell.row, cell.column)] = cell
    dimensions = list(ws.column_dimensions.values())
    ws.column_dimensions.clear()
    for dimension in dimensions:
        moved = copy(dimension)
        old_min = dimension.min or column_index_from_string(dimension.index)
        old_max = dimension.max or old_min
        moved.index = get_column_letter(old_min + 1)
        moved.min, moved.max = old_min + 1, old_max + 1
        ws.column_dimensions[moved.index] = moved
    ws.column_dimensions["A"] = ColumnDimension(ws, index="A", width=1)
    for area in merged:
        if area.min_row <= 4 and area.max_row <= 4:
            continue
        ws.merge_cells(_shift_address(str(area)))
    for row in range(1, 5):
        for col in range(2, title_span + 2):
            ws.cell(row, col).value = None
    for row in (2, 3, 4):
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=title_span + 1)
    ws["B2"] = title
    ws["B4"] = scope


def _is_blue(font):
    color = font.color
    return color is not None and color.type == "rgb" and color.rgb[-6:] == INPUT_BLUE


def _table_regions(ws):
    regions = [CellRange(table.ref) for table in ws.tables.values()]
    header_rows = {area.min_row for area in regions}
    # Legacy analytical tables have no Excel Table object. Their dark fills
    # identify headers without depending on translated column labels.
    header_columns = {}
    for cell in ws._cells.values():
        if isinstance(cell, MergedCell) or cell.row < 6:
            continue
        fill = cell.fill
        if fill.patternType == "solid" and fill.fgColor.type == "rgb":
            if fill.fgColor.rgb[-6:] in {"303942", "17212A", "166A70", "E8EBEE", "F2F2F2"}:
                header_rows.add(cell.row)
                header_columns.setdefault(cell.row, set()).add(cell.column)
    for row, columns in header_columns.items():
        for merged in ws.merged_cells.ranges:
            if merged.min_row == row == merged.max_row and merged.min_col in columns:
                columns.update(range(merged.min_col, merged.max_col + 1))
        columns = sorted(columns)
        groups = []
        start = previous = columns[0]
        has_internal_lines = any(
            ws.cell(row, col).border.right.style
            for col in columns
            if ws.cell(row, col).border.right
        )
        for col in columns[1:]:
            left, right = ws.cell(row, col).border.left, ws.cell(row, previous).border.right
            outer_edge = (
                has_internal_lines and not (left and left.style) and not (right and right.style)
            )
            if col != previous + 1 or outer_edge:
                groups.append((start, previous))
                start = col
            previous = col
        groups.append((start, previous))
        for first, last in groups:
            if any(
                area.min_row == row and area.min_col <= first <= area.max_col for area in regions
            ):
                continue
            end = row
            for current in range(row + 1, ws.max_row + 1):
                values = [ws.cell(current, col) for col in range(first, last + 1)]
                if current in header_rows or not any(cell.value is not None for cell in values):
                    break
                if any(
                    cell.font.sz and cell.font.sz >= 14 for cell in values if cell.value is not None
                ):
                    break
                end = current
            regions.append(CellRange(min_col=first, max_col=last, min_row=row, max_row=end))
    return regions, header_rows


def _cell_alignment(cell, region, ws):
    alignment = copy(cell.alignment)
    alignment.vertical = "center"
    if cell.row == region.min_row:
        alignment.horizontal = "center"
    elif isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        alignment.horizontal = "right"
    elif cell.data_type == "f" and cell.number_format not in {"General", "@"}:
        alignment.horizontal = "right"
    else:
        heading = str(ws.cell(region.min_row, cell.column).value or "")
        long_text = any(
            word in heading
            for word in (
                "원문",
                "내용",
                "비고",
                "근거",
                "JSON",
                "별칭",
                "후보",
                "사유",
                "설명",
                "표준화",
                "정규화",
            )
        )
        value = str(cell.value or "")
        alignment.horizontal = "left" if long_text or len(value) > 24 or "\n" in value else "center"
        if cell.data_type == "f" and cell.number_format in {"General", "@"}:
            alignment.horizontal = "left" if cell.alignment.horizontal == "left" else "center"
    cell.alignment = alignment


def _style_visible(ws, created_at, author):
    regions, header_rows = _table_regions(ws)
    variance_ranges = [
        (area, column)
        for area in regions
        for column in range(area.min_col, area.max_col + 1)
        if any(
            word in str(ws.cell(area.min_row, column).value or "")
            for word in ("증감", "기준 대비", "전월 대비", "전년", "전기 대비")
        )
    ]
    occupied_rows = set()
    for cell in ws._cells.values():
        if isinstance(cell, MergedCell):
            continue
        if cell.value is not None:
            occupied_rows.add(cell.row)
        old = cell.font
        size = 14 if old.sz and old.sz >= 14 and cell.row >= 6 else 11
        font = copy(old)
        font.name, font.sz = FONT_NAME, size
        font.color = INPUT_BLUE if _is_blue(old) else BLACK
        cell.font = font
        border = cell.border
        cell.border = Border(
            left=border.left,
            right=border.right,
            top=border.top,
            bottom=border.bottom,
            diagonal=border.diagonal,
            diagonal_direction=border.diagonal_direction,
            diagonalUp=border.diagonalUp,
            diagonalDown=border.diagonalDown,
            outline=False,
        )
        if cell.row in header_rows and cell.value is not None:
            cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
            cell.font = Font(name=FONT_NAME, size=11, color=BLACK, bold=True)
        region = next((area for area in regions if cell.coordinate in area), None)
        if region is not None:
            cell.border = Border(
                left=_LINE if cell.column > region.min_col else Side(),
                right=_LINE if cell.column < region.max_col else Side(),
                top=_LINE if cell.row == region.min_row else cell.border.top,
                bottom=_LINE,
            )
            _cell_alignment(cell, region, ws)
        cell.number_format = re.sub(r"\[(?:Red|Blue)\]", "", cell.number_format, flags=re.I)
        if any(
            column == cell.column and cell.row > area.min_row and cell.coordinate in area
            for area, column in variance_ranges
        ):
            if cell.data_type == "f" or isinstance(cell.value, (int, float)):
                if "%" in cell.number_format:
                    cell.number_format = INCREASE_PERCENT_FORMAT
                elif "." not in cell.number_format:
                    cell.number_format = INCREASE_INT_FORMAT
                else:
                    cell.number_format = INCREASE_FORMAT
    for row in range(1, ws.max_row + 1):
        ws.row_dimensions[row].height = 22 if row in occupied_rows and row >= 6 else 16.5
    ws.sheet_format.defaultRowHeight = 16.5
    ws.row_dimensions[2].height = 24
    ws["B2"].font = Font(name=FONT_NAME, size=16, color=BLACK, bold=True)
    ws["B2"].alignment = Alignment(vertical="center", horizontal="left")
    ws["B3"] = f"{created_at:%Y.%m.%d} {author} 작성"
    ws["B3"].font = Font(name=FONT_NAME, size=11, color=BLACK)
    ws["B3"].alignment = Alignment(horizontal="right", vertical="center")
    ws["B4"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    for table in ws.tables.values():
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleLight1",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=False,
            showColumnStripes=False,
        )
    ws.sheet_view.showGridLines = False
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if ws.title == "01_종합현황" else 0


def apply_workbook_layout(
    workbook, cache=None, *, created_at=None, author="확인 필요", exclude_sheets=()
):
    """Move visible report content to B and apply the adopted house style once.

    Hidden sheets retain their coordinates, but references to visible sheets are
    translated there as well. ``cache`` is the writer's FormulaCache instance.
    The input workbook is updated in place and returned for convenient chaining.
    """
    if getattr(workbook, "_efa_layout_applied", False):
        return workbook
    created_at = created_at or datetime.now()
    if not isinstance(created_at, date):
        raise TypeError("created_at must be a date or datetime")
    visible = {
        ws.title
        for ws in workbook
        if ws.sheet_state == "visible" and ws.title not in exclude_sheets
    }
    _defined_names(workbook.defined_names, None, visible)
    for ws in workbook:
        shifted = ws.title in visible
        _worksheet_references(ws, visible, shifted)
        if shifted:
            _move_visible_cells(ws)
            _style_visible(ws, created_at, author)
    if cache is not None:
        cache.values = {
            (sheet, _shift_address(address) if sheet in visible else address): value
            for (sheet, address), value in cache.values.items()
        }
    workbook._efa_layout_applied = True
    return workbook
