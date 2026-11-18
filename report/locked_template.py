"""Populate the user's fixed report design and retain its native Excel graphics.

Only cell contents and chart data are replaced. The original drawing/chart XML
is restored after saving because an openpyxl round trip discards Excel extensions.
"""

from __future__ import annotations

import json
import math
import posixpath
import re
from copy import copy, deepcopy
from numbers import Real
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.utils.indexed_list import IndexedList
from openpyxl.worksheet.properties import PageSetupProperties

from core.config import resource_root
from version import VERSION

LOCKED_SHEETS = (
    "01.종합현황",
    "02.팀별 주요이슈",
    "03.팀간 비교",
    "04.월별 주요이슈",
)
ALIASES = (
    (LOCKED_SHEETS[0], "01_종합현황"),
    (LOCKED_SHEETS[1], "02.주요이슈_팀별", "주요이슈_팀별", "공장팀_주요이슈"),
    (LOCKED_SHEETS[2], "03.비교", "동일설비사례_비교"),
    (LOCKED_SHEETS[3], "고장사례_추이"),
)
METRICS_SHEET = "_report_metrics"
NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
}
CELL = re.compile(r"^(\$?)([A-Z]{1,3})(\$?)([1-9][0-9]*)$")


def template_path():
    return resource_root() / "config" / "report_template.xlsx"


def _style(source, target):
    for name in ("font", "fill", "border", "alignment", "protection"):
        setattr(target, name, copy(getattr(source, name)))
    target.number_format = source.number_format


def _copy_sheet(source, book):
    target = book.create_sheet(source.title)
    for row in source:
        for cell in row:
            dest = target.cell(cell.row, cell.column)
            _style(cell, dest)
            dest.value = cell.value
            dest.data_type = cell.data_type
    for key, dimension in source.row_dimensions.items():
        target.row_dimensions[key] = copy(dimension)
        target.row_dimensions[key].parent = target
        _style(dimension, target.row_dimensions[key])
    for key, dimension in source.column_dimensions.items():
        target.column_dimensions[key] = copy(dimension)
        target.column_dimensions[key].parent = target
        _style(dimension, target.column_dimensions[key])
    for name in (
        "sheet_format",
        "sheet_properties",
        "views",
        "page_setup",
        "page_margins",
        "print_options",
        "protection",
        "auto_filter",
        "data_validations",
        "conditional_formatting",
        "HeaderFooter",
    ):
        setattr(target, name, deepcopy(getattr(source, name)))
    for merged in source.merged_cells.ranges:
        target.merge_cells(str(merged))
    target.print_area = str(source.print_area)
    target.print_title_rows = source.print_title_rows
    target.print_title_cols = source.print_title_cols
    target._charts = deepcopy(source._charts)
    target._images = deepcopy(source._images)
    return target


def _map_cell(address, mapping):
    match = CELL.fullmatch(address)
    if not match:
        return address
    a, col, b, row = match.groups()
    mapped = mapping.get(col + row)
    if mapped is None:
        return address
    dest = CELL.fullmatch(mapped)
    if not dest:
        return mapped
    return a + dest[2] + b + dest[4]


def _formula(formula, owner, maps, names):
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula
    result = []
    for token in Tokenizer(formula).items:
        value = token.value
        if token.type == "OPERAND" and token.subtype == "RANGE":
            sheet, separator, addresses = value.rpartition("!")
            referenced = sheet.strip("'").replace("''", "'") if separator else owner
            if referenced in maps:
                addresses = addresses if separator else value
                addresses = ":".join(_map_cell(x, maps[referenced]) for x in addresses.split(":"))
                target_name = names[referenced]
                if separator or target_name != owner:
                    value = "'" + target_name.replace("'", "''") + "'!" + addresses
                else:
                    value = addresses
        result.append(value)
    return "=" + "".join(result)


def _row_map(mapping, first, count, offset, width):
    for row in range(first, first + count):
        for col in range(1, width + 1):
            letter = get_column_letter(col)
            mapping[f"{letter}{row}"] = f"{letter}{row + offset}"


def _extend(target, start, capacity, actual):
    extra = max(0, actual - capacity)
    if not extra:
        return 0
    old_end = start + capacity - 1
    for row in range(old_end + 1, old_end + extra + 1):
        for col in range(1, target.max_column + 1):
            _style(target.cell(old_end, col), target.cell(row, col))
        target.row_dimensions[row] = copy(target.row_dimensions[old_end])
        target.row_dimensions[row].index = row
    # Tables are below the charts; growing tables keep the chart anchors fixed.
    bounds = range_boundaries(str(target.print_area).split("!")[-1])
    target.print_area = (
        f"{get_column_letter(bounds[0])}{bounds[1]}:"
        f"{get_column_letter(bounds[2])}{bounds[3] + extra}"
    )
    return extra


def _summary_lines(builder, target):
    """Rank physical report lines independently of the GUI grouping selection."""
    from core.aggregation import grouped
    from report.issue_workbook import escaped_cell, exact, ref

    frame = builder.r.selected
    field = "report_equipment" if "report_equipment" in frame else "equipment"
    groups = grouped(frame.assign(equipment=frame[field]), ["equipment"])
    rows = sorted(groups.to_dict("records"), key=lambda item: str(item["equipment"]))
    detail = builder.wb[next(s.title for s in builder.wb if s.title.endswith("고장이력"))]
    headers = {cell.value: cell.column_letter for cell in detail[6]}
    line_col = headers[builder.display_header(field)]
    time_col = headers[builder.display_header("minutes")]
    last = max(7, 6 + len(frame))
    line_range = f"{ref(detail.title)}!${line_col}$7:${line_col}${last}"
    time_range = f"{ref(detail.title)}!${time_col}$7:${time_col}${last}"
    helper = builder.wb.create_sheet("_report_lines")
    helper.append(["라인", "건수", "시간 유효", "정지시간", "건수순위", "시간순위"])
    helper.sheet_state = "hidden"
    count_order = sorted(rows, key=lambda item: (-item["count"], str(item["equipment"])))
    time_order = sorted(
        [item for item in rows if item["valid_count"]],
        key=lambda item: (-item["total_minutes"], str(item["equipment"])),
    )
    ranks = [
        {item["equipment"]: i for i, item in enumerate(order, 1)}
        for order in (count_order, time_order)
    ]
    end = max(2, len(rows) + 1)
    for row, item in enumerate(rows, 2):
        label = str(item["equipment"])
        helper.cell(row, 1, label).data_type = "s"
        criterion = exact(label)
        for col, formula, cached in (
            ("B", f"=COUNTIF({line_range},{criterion})", item["count"]),
            (
                "C",
                f'=COUNTIFS({line_range},{criterion},{time_range},">=0",{time_range},"<>")',
                item["valid_count"],
            ),
            (
                "D",
                f'=IF(C{row}=0,"",SUMIF({line_range},{criterion},{time_range}))',
                item["total_minutes"] if item["valid_count"] else "",
            ),
            (
                "E",
                f'=IF(B{row}=0,"",RANK(B{row},$B$2:$B${end},0)+COUNTIF($B$2:B{row},B{row})-1)',
                ranks[0][label],
            ),
            (
                "F",
                f'=IF(C{row}=0,"",RANK(D{row},$D$2:$D${end},0)+COUNTIFS($C$2:C{row},">0",$D$2:D{row},D{row})-1)',
                ranks[1].get(label, ""),
            ),
        ):
            builder.cache.set(helper, f"{col}{row}", formula, cached)
    for first, order, rank_col, value_col, key in (
        (10, count_order, "E", "B", "count"),
        (23, time_order, "F", "D", "total_minutes"),
    ):
        for index in range(10):
            row = first + index
            item = order[index] if index < len(order) else None
            label = str(item["equipment"]) if item else ""
            builder.cache.set(
                target,
                f"B{row}",
                f"=IFERROR(INDEX('_report_lines'!$A$2:$A${end},MATCH({index + 1},'_report_lines'!${rank_col}$2:${rank_col}${end},0)),\"\")",
                label,
            )
            builder.cache.set(
                target,
                f"D{row}",
                f"=IF(B{row}=\"\",\"\",INDEX('_report_lines'!${value_col}$2:${value_col}${end},MATCH({escaped_cell(f'B{row}')},'_report_lines'!$A$2:$A${end},0)))",
                item[key] if item else "",
            )


def _appendix_layout(builder, design):
    """Apply the reference's appendix geometry without fixed source-data row counts."""
    from openpyxl.worksheet.dimensions import ColumnDimension

    path = resource_root() / "config" / "report_appendix_layout.json"
    layouts = json.loads(path.read_text(encoding="utf-8"))
    reference_styles = {}

    def reference(style_id):
        if style_id not in reference_styles:
            cell = Cell(design.worksheets[0], row=1, column=1)
            cell._style = design._cell_styles[style_id]
            reference_styles[style_id] = cell
        return reference_styles[style_id]

    for name, layout in layouts.items():
        if name not in builder.wb:
            continue
        target = builder.wb[name]
        target.column_dimensions.clear()
        for attrs in layout["columns"]:
            key = get_column_letter(int(attrs["min"]))
            dimension = ColumnDimension(target, index=key)
            target.column_dimensions[key] = dimension
            # Apply grouped Excel column dimensions including hidden source IDs.
            for attr in ("min", "max", "width", "hidden", "bestFit", "outlineLevel", "collapsed"):
                if attr in attrs:
                    value = attrs[attr]
                    setattr(
                        dimension,
                        attr,
                        float(value)
                        if attr == "width"
                        else bool(int(value))
                        if attr in ("hidden", "bestFit", "collapsed")
                        else int(value),
                    )
            if "style" in attrs:
                _style(reference(int(attrs["style"])), dimension)
        for address, style_id in layout["header_styles"].items():
            cell = target[address]
            if not isinstance(cell, MergedCell):
                _style(reference(style_id), cell)
        for row in range(1, target.max_row + 1):
            target.row_dimensions[row].height = (
                layout["row_heights"].get(str(row), layout["body_height"])
                if row <= 6
                else layout["body_height"]
            )
        for key, value in layout["margins"].items():
            setattr(target.page_margins, key, float(value))
        for key, value in layout["page_setup"].items():
            if key in ("orientation", "paperSize", "fitToWidth", "fitToHeight", "scale"):
                setattr(target.page_setup, key, value if key == "orientation" else int(value))
        left, right = layout["print_columns"]
        bottom = max(target.max_row, 42) if name.endswith("분석") else target.max_row
        target.print_area = f"{left}1:{right}{bottom}"


def apply_locked_template(builder):
    """Replace scratch front sheets with the template, retaining live formulas."""
    book, cache = builder.wb, builder.cache
    design = load_workbook(template_path())
    # Excel measures column widths using the Normal font, including chart offsets.
    # Copying only individual cell fonts leaves the same width=13 visibly narrower.
    book._fonts = IndexedList([copy(design._fonts[0]), *book._fonts[1:]])
    sources = [
        next((book[n] for n in aliases if n in book.sheetnames), None) for aliases in ALIASES
    ]
    maps, names = {}, {}
    states = {}
    old_cache = dict(cache.values)
    for index, source in enumerate(sources):
        if source is None:
            continue
        mapping = {}
        if index == 0:
            mapping.update({"A3": "A4", "A7": "A6"})
        elif index == 1:
            mapping.update(
                {
                    "B6": "B5",
                    "D6": "D5",
                    "F6": "G5",
                    "K6": "K5",
                    "K7": "K6",
                    "B7": "C9",
                    "D7": "E9",
                    "F7": "G9",
                    "H7": "I9",
                }
            )
            count = sum(source.cell(row, 4).data_type == "f" for row in range(10, 20))
            _row_map(mapping, 10, count, 18, 12)
            states[LOCKED_SHEETS[index]] = {
                "actual": count,
                "capacity": 5,
                "start": 28,
                "chart_row_shift": 0,
            }
        elif index == 2:
            mapping.update({"B6": "B5", "B7": "E5", "G7": "I5"})
            # The issue source excludes planned stops and can contain fewer organizations.
            count = sum(
                source.cell(row, 1).value is not None
                for row in range(11, source.max_row + 1)
                if source.cell(row, 3).data_type == "f"
            )
            _row_map(mapping, 11, count, 11, 10)
            states[LOCKED_SHEETS[index]] = {
                "actual": count,
                "capacity": 7,
                "start": 22,
                "chart_row_shift": 0,
            }
        else:
            mapping.update({"B6": "B5", "D6": "D5", "F6": "F5", "K6": "J5", "B7": "J6"})
            count = sum(
                source.cell(row, 2).data_type == "f" for row in range(10, source.max_row + 1)
            )
            _row_map(mapping, 10, count, 13, 11)
            states[LOCKED_SHEETS[index]] = {
                "actual": count,
                "capacity": 11,
                "start": 23,
                "chart_row_shift": 0,
            }
        maps[source.title], names[source.title] = mapping, LOCKED_SHEETS[index]
    metrics = None
    if sources[0]:
        if METRICS_SHEET in book:
            book.remove(book[METRICS_SHEET])
        metrics = book.create_sheet(METRICS_SHEET)
        metrics["A1"] = "metric"
        metrics.sheet_state = "hidden"
        for address, source_cell, label in (
            ("A2", "A6", "count"),
            ("A3", "E6", "total_minutes"),
            ("A4", "I6", "mean_minutes"),
        ):
            source = sources[0]
            cell = source[source_cell]
            metrics[address] = _formula(cell.value, source.title, maps, names)
            metrics[address].number_format = "#,##0" if address == "A2" else "#,##0.0"
            metrics.cell(int(address[1:]), 2, label)
            cache.values[(METRICS_SHEET, address)] = old_cache.get((source.title, source_cell), "")
    for source in sources:
        if source is not None:
            book.remove(source)
    targets, style_map = {}, {}
    for index, source in enumerate(sources):
        if source is None:
            continue
        name = LOCKED_SHEETS[index]
        target = _copy_sheet(design[name], book)
        if str(target.oddFooter.right.text).startswith("EFA "):
            target.oddFooter.right.text = f"EFA {VERSION}"
        targets[name] = target
        for row in design[name]:
            for cell in row:
                style_map[cell.style_id] = target.cell(cell.row, cell.column).style_id
        for key, dim in design[name].column_dimensions.items():
            style_map[dim.style_id] = target.column_dimensions[key].style_id
        for key, dim in design[name].row_dimensions.items():
            style_map[dim.style_id] = target.row_dimensions[key].style_id
        state = states.get(name, {})
        state["extra"] = (
            _extend(target, state.get("start", 1), state.get("capacity", 0), state.get("actual", 0))
            if state
            else 0
        )
        states[name] = state
        if target.sheet_properties.pageSetUpPr is None:
            target.sheet_properties.pageSetUpPr = PageSetupProperties()
        target.sheet_properties.pageSetUpPr.fitToPage = True
        target.page_setup.fitToWidth = 1
        if index == 3:
            # The reference's right-hand chart reaches L; include it when printing.
            bottom = range_boundaries(str(target.print_area).split("!")[-1])[3]
            target.print_area = f"A1:L{bottom}"
        # Controls come from the current report logic, never stale template lists.
        target.data_validations = deepcopy(source.data_validations)
        for validation in target.data_validations.dataValidation:
            validation.sqref = " ".join(
                _map_cell(address, maps[source.title]) for address in str(validation.sqref).split()
            )
        for old, new in maps[source.title].items():
            cell, dest = source[old], target[new]
            if isinstance(dest, MergedCell):
                continue
            if cell.data_type == "f":
                cache.set(
                    target,
                    new,
                    _formula(cell.value, source.title, maps, names),
                    old_cache.get((source.title, old), ""),
                )
            else:
                dest.value = cell.value
                if isinstance(dest.value, str):
                    dest.data_type = "s"
        if index == 0:
            target["A4"] = "집계기간: " + str(builder.r.metrics["period"])
            count = old_cache.get((source.title, "A6"), "")
            total = old_cache.get((source.title, "E6"), "")
            mean = old_cache.get((source.title, "I6"), "")

            def display(value, digits=0):
                return (
                    format(float(value), f",.{digits}f") + "분"
                    if isinstance(value, Real) and math.isfinite(float(value))
                    else "확인 필요"
                )

            text = f"총 기록 건수 {int(count):,}건  |  정지시간 합계 {display(total)}  |  평균 정지시간 {display(mean)}"
            formula = (
                '="총 기록 건수 "&TEXT(\'_report_metrics\'!A2,"#,##0")&"건  |  정지시간 합계 "&'
                'IF(ISNUMBER(\'_report_metrics\'!A3),TEXT(\'_report_metrics\'!A3,"#,##0")&"분","확인 필요")&'
                '"  |  평균 정지시간 "&IF(ISNUMBER(\'_report_metrics\'!A4),TEXT(\'_report_metrics\'!A4,"#,##0")&"분","확인 필요")'
            )
            cache.set(target, "A5", formula, text)
        if index == 0:
            _summary_lines(builder, target)
    _appendix_layout(builder, design)
    # Rewrite references in hidden rank helpers and the rest of the report once.
    source_names = set(maps)
    for sheet in book:
        if sheet.title in targets or sheet.title == METRICS_SHEET:
            continue
        for row in sheet:
            for cell in row:
                if cell.data_type == "f":
                    cell.value = _formula(cell.value, sheet.title, maps, names)
    # Drop stale source cache entries; retain only newly populated destination cells.
    populated = {
        (name, cell.coordinate)
        for name, ws in targets.items()
        for row in ws
        for cell in row
        if cell.data_type == "f"
    }
    cache.values = {
        key: value
        for key, value in cache.values.items()
        if key[0] not in source_names or key in populated
    }
    book._sheets = [targets[n] for n in LOCKED_SHEETS if n in targets] + [
        ws for ws in book if ws.title not in targets
    ]
    book.loaded_theme = design.loaded_theme
    builder._locked_template = {"sheets": states, "styles": style_map, "images": []}
    design.close()


def _resolve(base, target):
    return (
        target.lstrip("/")
        if target.startswith("/")
        else posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    )


def _rels_path(part):
    return posixpath.dirname(part) + "/_rels/" + posixpath.basename(part) + ".rels"


def _relationships(archive, part):
    path = _rels_path(part)
    if path not in archive.namelist():
        return {}
    return {
        item.get("Id"): (_resolve(part, item.get("Target")), item.get("Type"))
        for item in ET.fromstring(archive.read(path))
    }


def _sheet_parts(archive):
    rels = _relationships(archive, "xl/workbook.xml")
    book = ET.fromstring(archive.read("xl/workbook.xml"))
    return {
        item.get("name"): rels[item.get("{" + NS["r"] + "}id")][0]
        for item in book.find("s:sheets", NS)
    }


def _cache_value(builder, name, address):
    cell = builder.wb[name][address]
    return builder.cache.values.get((name, address), "") if cell.data_type == "f" else cell.value


def _chart_data(raw, builder, name, extra):
    # Patch only data-bearing XML substrings. Serializing the full native chart
    # would rename namespaces and can invalidate Excel's extension declarations.
    state = builder._locked_template["sheets"][name]
    raw_text = raw.decode("utf-8")
    metric_match = re.search(r"<c:numRef><c:f>[^<]*!\$([A-Z]+)\$[0-9]+:", raw_text)
    metric = metric_match[1] if metric_match else None
    period = state.get("period_chart_ranges")
    if period and metric in ("B", "C"):
        title_cell = "B7" if metric == "B" else "B8"
        raw_text = re.sub(
            r"(<c:title>.*?)<c:tx>.*?</c:tx>",
            lambda m: (
                m[1]
                + f"<c:tx><c:strRef><c:f>'_period_state'!${title_cell[0]}${title_cell[1:]}</c:f></c:strRef></c:tx>"
            ),
            raw_text,
            count=1,
            flags=re.DOTALL,
        )
        raw_text = re.sub(
            r"<c:catAx\b.*?</c:catAx>",
            lambda axis: re.sub(
                r"(<c:title>.*?)<c:tx>.*?</c:tx>",
                lambda title: (
                    title[1] + "<c:tx><c:strRef><c:f>'_period_state'!$B$9</c:f></c:strRef></c:tx>"
                ),
                axis[0],
                count=1,
                flags=re.DOTALL,
            ),
            raw_text,
            flags=re.DOTALL,
        )

    def replace_reference(match):
        kind, inner = match[2], match[3]
        text = re.search(r"<c:f>(.*?)</c:f>", inner, flags=re.DOTALL)
        if text is None:
            return match[0]
        formula = ET.fromstring("<f>" + text[1] + "</f>").text
        sheet, _, address = formula.rpartition("!")
        if extra and ":" in address:
            first, last = address.split(":")
            match = CELL.fullmatch(last)
            address = first + ":" + match[1] + match[2] + match[3] + str(int(match[4]) + extra)
            formula = sheet + "!" + address
        if state.get("rank_row_shift"):
            mapping = {}
            for row in range(11, 21):
                for col in range(1, 13):
                    letter = get_column_letter(col)
                    mapping[f"{letter}{row}"] = f"{letter}{row + state['rank_row_shift']}"
        else:
            mapping = state.get("cell_map", {})
        if mapping:
            formula = _formula("=" + formula, name, {name: mapping}, {name: name})[1:]
            sheet, _, address = formula.rpartition("!")
        cache_formula = formula
        if ":" in address:
            ranks = state.get("comparison_chart_ranges", {}).get(metric)
            if ranks:
                formula = ranks["category" if kind == "strRef" else "value"]
                cache_formula = formula
            elif period and metric in ("B", "C"):
                key = "category" if kind == "strRef" else metric
                formula, cache_formula = period[key], period["cache_" + key]
        sheet, _, address = cache_formula.rpartition("!")
        sheet = sheet.strip("'").replace("''", "'")
        bounds = range_boundaries(address)
        values = [
            _cache_value(builder, sheet, f"{get_column_letter(col)}{row}")
            for row in range(bounds[1], bounds[3] + 1)
            for col in range(bounds[0], bounds[2] + 1)
        ]
        numeric = kind == "numRef"
        cache_tag = "numCache" if numeric else "strCache"
        cache = [f"<c:{cache_tag}>"]
        if numeric:
            cache.append(
                "<c:formatCode>"
                + escape(builder.wb[sheet].cell(bounds[1], bounds[0]).number_format)
                + "</c:formatCode>"
            )
        cache.append(f'<c:ptCount val="{len(values)}"/>')
        for index, value in enumerate(values):
            if numeric and (
                value is None
                or value == ""
                or not isinstance(value, Real)
                or not math.isfinite(float(value))
            ):
                continue
            value = format(float(value), ".15g") if numeric else "" if value is None else str(value)
            cache.append(f'<c:pt idx="{index}"><c:v>{escape(value)}</c:v></c:pt>')
        cache.append(f"</c:{cache_tag}>")
        inner = re.sub(
            r"<c:f>.*?</c:f>", "<c:f>" + escape(formula) + "</c:f>", inner, count=1, flags=re.DOTALL
        )
        inner = re.sub(
            r"<c:(?:strCache|numCache)\b[^>]*>.*?</c:(?:strCache|numCache)>",
            "",
            inner,
            flags=re.DOTALL,
        )
        return f"<c:{kind}>" + inner + "".join(cache) + f"</c:{kind}>"

    result = re.sub(
        r"(<c:(strRef|numRef)\b[^>]*>)(.*?)(</c:\2>)",
        replace_reference,
        raw_text,
        flags=re.DOTALL,
    )
    # Preserve the native design while changing only display precision and order.
    result = re.sub(
        r'(<c:numFmt\b[^>]*formatCode=")([^"]*)(")',
        lambda m: m[0] if "%" in m[2] else m[1] + re.sub(r"\.0+", "", m[2]) + m[3],
        result,
    )
    if '<c:barDir val="bar"' in result:
        result = re.sub(
            r"<c:catAx\b.*?</c:catAx>",
            lambda m: re.sub(
                r'<c:orientation val="[^"]*"\s*/>', '<c:orientation val="maxMin"/>', m[0]
            ),
            result,
            flags=re.DOTALL,
        )
    return result.encode("utf-8")


def _replace_node(raw, tag, node):
    ET.register_namespace("", NS["s"])
    replacement = ET.tostring(node, encoding="unicode") if node is not None else ""
    pattern = rf"<(?:\w+:)?{tag}(?:\s[^>]*)?(?:/>|>.*?</(?:\w+:)?{tag}>)"
    if re.search(pattern, raw, flags=re.DOTALL):
        return re.sub(pattern, lambda _: replacement, raw, count=1, flags=re.DOTALL)
    return raw


def restore_template_charts(path, builder):
    """Restore original native graphics and sheet geometry after cache patching."""
    state = getattr(builder, "_locked_template", None)
    if not state:
        return
    path = Path(path)
    replacements = {}
    with ZipFile(template_path()) as design, ZipFile(path) as output:
        src_sheets, dst_sheets = _sheet_parts(design), _sheet_parts(output)
        for name, sheet_state in state["sheets"].items():
            src, dst = src_sheets[name], dst_sheets[name]
            original_raw = design.read(src).decode("utf-8")
            original = ET.fromstring(original_raw)
            generated = ET.fromstring(output.read(dst))
            for tag in (
                "sheetPr",
                "pageSetup",
                "sheetData",
                "cols",
                "mergeCells",
                "dataValidations",
                "dimension",
                "headerFooter",
            ):
                original_raw = _replace_node(original_raw, tag, generated.find("s:" + tag, NS))
            src_rels, dst_rels = _relationships(design, src), _relationships(output, dst)
            sd = original.find("s:drawing", NS)
            dd = generated.find("s:drawing", NS)
            if sd is not None and dd is not None:
                src_drawing = src_rels[sd.get("{" + NS["r"] + "}id")][0]
                dst_drawing = dst_rels[dd.get("{" + NS["r"] + "}id")][0]
                original_raw = _replace_node(original_raw, "drawing", dd)
                source_tree = ET.fromstring(design.read(src_drawing))
                target_tree = ET.fromstring(output.read(dst_drawing))
                sr, dr = _relationships(design, src_drawing), _relationships(output, dst_drawing)
                relationship_root = ET.Element("Relationships", xmlns=NS["p"])
                image_index = 0
                for source_anchor, dest_anchor in zip(source_tree, target_tree, strict=True):
                    source_ref = source_anchor.find(".//c:chart", NS)
                    dest_ref = dest_anchor.find(".//c:chart", NS)
                    chart = source_ref is not None
                    if not chart:
                        source_ref = next(
                            x for x in source_anchor.iter() if x.tag.endswith("}blip")
                        )
                        dest_ref = next(x for x in dest_anchor.iter() if x.tag.endswith("}blip"))
                    attribute = "id" if chart else "embed"
                    source_id = source_ref.get("{" + NS["r"] + "}" + attribute)
                    dest_id = dest_ref.get("{" + NS["r"] + "}" + attribute)
                    source_part, kind = sr[source_id]
                    dest_part, _ = dr[dest_id]
                    ET.SubElement(
                        relationship_root,
                        "Relationship",
                        {
                            "Id": source_id,
                            "Type": kind,
                            "Target": posixpath.relpath(dest_part, posixpath.dirname(dst_drawing)),
                        },
                    )
                    if chart:
                        extra = sheet_state.get("extra", 0)
                        replacements[dest_part] = _chart_data(
                            design.read(source_part), builder, name, extra
                        )
                        if extra:
                            for marker in ("xdr:from/xdr:row", "xdr:to/xdr:row"):
                                node = source_anchor.find(marker, NS)
                                if node is not None:
                                    node.text = str(int(node.text) + extra)
                    elif image_index < len(state["images"]):
                        replacements[dest_part] = state["images"][image_index]
                        image_index += 1
                drawing_raw = design.read(src_drawing).decode("utf-8")
                if sheet_state.get("chart_row_shift", sheet_state.get("extra", 0)):
                    extra = sheet_state.get("chart_row_shift", sheet_state.get("extra", 0))
                    drawing_raw = re.sub(
                        r"<xdr:row>([0-9]+)</xdr:row>",
                        lambda m: "<xdr:row>" + str(int(m[1]) + extra) + "</xdr:row>",
                        drawing_raw,
                    )
                replacements[dst_drawing] = drawing_raw.encode("utf-8")
                replacements[_rels_path(dst_drawing)] = ET.tostring(
                    relationship_root, encoding="utf-8", xml_declaration=True
                )
            replacements[dst] = original_raw.encode("utf-8")
        data = [
            (item, replacements.get(item.filename, output.read(item.filename)))
            for item in output.infolist()
        ]
    temporary = path.with_suffix(path.suffix + ".template.tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as target:
            for item, content in data:
                target.writestr(item, content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
