"""Style-only reference for the published appendices."""

import json
from copy import copy, deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.utils.cell import get_column_letter
from openpyxl.worksheet.dimensions import ColumnDimension

from core.config import resource_root

RAW = "별첨. 원본 검토표시"
STYLE_FILE = "report_appendix_layout.json"
FIXED_HEIGHT_SHEETS = ("별첨. 검토·분류현황", "별첨. 고장이력")


def read_layouts():
    return json.loads((resource_root() / "config" / STYLE_FILE).read_text(encoding="utf-8"))


def apply_appendix_styles(book, design):
    """Style generated records by column without using reference record positions."""
    cells = {}
    for title, layout in read_layouts().items():
        if title == RAW or title not in book:
            continue
        ws = book[title]
        if not layout.get("body"):
            continue
        ws.column_dimensions.clear()
        for attributes in layout["columns"]:
            letter = get_column_letter(attributes["min"])
            ws.column_dimensions[letter] = ColumnDimension(ws, index=letter, **attributes)
        for row, height in layout["heights"].items():
            ws.row_dimensions[int(row)].height = height
        for cell in list(ws._cells.values()):
            if isinstance(cell, MergedCell):
                continue
            body = cell.row > layout["header"]
            index = layout["body" if body else "header_styles"].get(
                cell.column_letter if body else cell.coordinate
            )
            if index is None:
                continue
            if index not in cells:
                ref = Cell(design.worksheets[0], row=1, column=1)
                ref._style = design._cell_styles[index]
                cells[index] = ref
            ref = cells[index]
            for key in ("font", "border", "alignment", "number_format", "protection"):
                setattr(cell, key, copy(getattr(ref, key)))
            if not body and cell.coordinate not in {"G11", "G12", "G13", "G14"}:
                cell.fill = copy(ref.fill)
    for title in FIXED_HEIGHT_SHEETS:
        if title in book:
            ws = book[title]
            ws.sheet_format.defaultRowHeight = 22
            ws.sheet_format.customHeight = True
            for row in range(1, ws.max_row + 1):
                ws.row_dimensions[row].height = 22


def apply_raw_styles(sheet, target, tag, merge_styles):
    layout = read_layouts().get(RAW)
    if not layout or not layout.get("headers"):
        return
    data = sheet.find(tag("sheetData"))
    header = data.find(f'{tag("row")}[@r="{layout["header"]}"]')
    if header is None:
        return
    observed = {c.get("r"): "".join(t.text or "" for t in c.iter(tag("t"))) for c in header}
    if any(observed.get(cell) != title for cell, title in layout["headers"].items()):
        return
    # The reference contains only style definitions. Keep each original cell's
    # fill and type-specific number format when its value uses date serials.
    with ZipFile(Path(resource_root()) / "config/report_template.xlsx") as archive:
        design = {
            n: archive.read(n)
            for n in ("xl/styles.xml", "xl/theme/theme1.xml", "xl/_rels/workbook.xml.rels")
        }
    start = merge_styles(target, design)["cellXfs"]
    styles = ET.fromstring(target["xl/styles.xml"])
    xfs = styles.find(tag("cellXfs"))
    combinations = {}
    for row in data:
        number = int(row.get("r"))
        height = layout["heights"].get(str(number))
        if height is not None:
            row.set("ht", str(height))
            row.set("customHeight", "1")
        for cell in row.findall(tag("c")):
            coordinate = cell.get("r")
            body = number > layout["header"]
            index = layout["body" if body else "header_styles"].get(
                coordinate.rstrip("0123456789") if body else coordinate
            )
            if index is None:
                continue
            old = xfs[int(cell.get("s", "0"))]
            fill = old.get("fillId", "0") if body else None
            fmt = old.get("numFmtId", "0") if cell.get("t", "n") in ("n", "d") else None
            key = (index, fill, fmt)
            if key not in combinations:
                style = deepcopy(xfs[start + index])
                if fill is not None:
                    style.set("fillId", fill)
                    style.set("applyFill", "1")
                if fmt is not None:
                    style.set("numFmtId", fmt)
                    style.set("applyNumberFormat", "1")
                combinations[key] = len(xfs)
                xfs.append(style)
            cell.set("s", str(combinations[key]))
    cols = sheet.find(tag("cols"))
    if cols is not None:
        sheet.remove(cols)
    cols = ET.Element(tag("cols"))
    for attributes in layout["columns"]:
        ET.SubElement(
            cols,
            tag("col"),
            {k: str(int(v) if isinstance(v, bool) else v) for k, v in attributes.items()},
        )
    sheet.insert(list(sheet).index(data), cols)
    xfs.set("count", str(len(xfs)))
    from report.source_review import _xml

    target["xl/styles.xml"] = _xml(styles, target["xl/styles.xml"])
