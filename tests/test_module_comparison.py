"""별첨. 동일 상세설비 비교: one module compared across lines with named ranked bars."""

import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import SHEETS, export_report
from report.issue_workbook import report_issue_facts
from report.locked_template import NS
from report.module_comparison import SHEET, default_module

C = "{" + NS["c"] + "}"


def _chart_parts(path, sheet_name):
    """Chart XML parts drawn on one worksheet, in drawing order."""
    from report.locked_template import _relationships, _sheet_parts

    with ZipFile(path) as archive:
        sheet = _sheet_parts(archive)[sheet_name]
        drawing = next(
            target for target, kind in _relationships(archive, sheet).values() if "drawing" in kind
        )
        charts = [
            target
            for _, (target, kind) in sorted(_relationships(archive, drawing).items())
            if kind.endswith("/chart")
        ]
        return [ET.fromstring(archive.read(part)) for part in charts]


def test_old_overlapping_appendices_are_replaced(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "compare.xlsx")
    book = load_workbook(path)
    try:
        assert SHEETS["module_compare"] == SHEET
        assert SHEET in book.sheetnames
        assert not {"별첨. 라인별분석", "별첨. 상세설비별분석"} & set(book.sheetnames)
        assert not any(name.startswith("_breakdown_") for name in book.sheetnames)
    finally:
        book.close()


def test_default_module_is_shared_by_several_lines(organization_result):
    facts = report_issue_facts(organization_result.selected)
    # 펌프 appears on two lines, 컨베어 on one.
    assert default_module(facts) == "펌프"


def test_lines_are_compared_for_one_module(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "compare.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        sheet, source = values[SHEET], formulas[SHEET]
        # Common appendix layout shifts content one column right.
        assert sheet["C6"].value == "펌프" and sheet["G6"].value == "(전체)"
        assert sheet["C7"].value == "(전체)" and sheet["G7"].value == "(전체)"
        assert sheet["K6"].value == "건수"
        # 실제설비A: 10, 20, 5(검토) / 실제설비B: 100, 미기재. 컨베어 기록은 제외.
        assert sheet["C9"].value == 5 and sheet["F9"].value == 135
        header = [sheet.cell(28, col).value for col in range(2, 14)]
        assert header[:4] == ["순위", "공장", "팀", "라인"]
        rows = [
            [sheet.cell(row, col).value for col in (2, 3, 4, 5, 8, 9, 11, 12)] for row in (29, 30)
        ]
        assert rows[0][:6] == [1, "공장A", "팀1", "실제설비A", 3, 35]
        assert rows[1][:6] == [2, "공장B", "팀2", "실제설비B", 2, 100]
        # Shares are against the whole selection, never re-based on the shown rows.
        assert rows[0][6] == pytest.approx(3 / 5) and rows[1][7] == pytest.approx(100 / 135)
        assert source["E29"].data_type == "f" and "_module_compare" in source["E29"].value
        assert all("기타" not in str(cell.value) for row in sheet for cell in row)
        validations = {str(v.sqref): v.formula1 for v in source.data_validations.dataValidation}
        assert validations["C6"] == "=_Issue_module" and validations["G6"] == "=_Issue_part"
        assert validations["C7"] == "=_Issue_factory" and validations["G7"] == "=_Issue_team"
        assert validations["K6"] == '"건수,정지시간"'
    finally:
        values.close()
        formulas.close()


def test_module_comes_first_in_cascading_controls(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "compare.xlsx")
    book = load_workbook(path)
    try:
        controls = [
            row
            for row in book["_report_controls"].iter_rows(min_row=2, values_only=True)
            if row[0] == SHEET
        ]
        order = {field: position for _, field, _, position, _, _ in controls}
        assert order == {"module": 1, "part": 2, "factory": 3, "team": 4}
        committed = {field: value for _, field, _, _, _, value in controls}
        assert committed["module"] == "펌프" and committed["factory"] == "(전체)"
        flags = book["_selector_flags"]
        column = next(column for _, field, _, _, column, _ in controls if field == "module")
        # The module list is not narrowed by the factory/team chosen below it.
        assert SHEET not in str(flags.cell(2, column).value)
        team = next(column for _, field, _, _, column, _ in controls if field == "team")
        assert "$C$6" in str(flags.cell(2, team).value)
    finally:
        book.close()


def test_ranked_bars_name_real_lines_with_cached_points(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "compare.xlsx")
    charts = _chart_parts(path, SHEET)
    assert len(charts) == 2
    assert not any(list(chart.iter(C + "doughnutChart")) for chart in charts)
    expected = [
        (["실제설비A", "실제설비B"], [3.0, 2.0], "_Compare_CountLabels"),
        (["실제설비B", "실제설비A"], [100.0, 35.0], "_Compare_TimeLabels"),
    ]
    for chart, (labels, numbers, name) in zip(charts, expected, strict=True):
        assert chart.find(f".//{C}barDir").get("val") == "bar"
        category = chart.find(f".//{C}cat/{C}strRef")
        assert category.find(f"{C}f").text.endswith("!" + name)
        assert [pt.find(f"{C}v").text for pt in category.iter(C + "pt")] == labels
        cached = chart.find(f".//{C}val/{C}numRef/{C}numCache")
        assert [float(pt.find(f"{C}v").text) for pt in cached.iter(C + "pt")] == numbers
        assert chart.find(f".//{C}catAx/{C}scaling/{C}orientation").get("val") == "maxMin"
        assert chart.find(f".//{C}dLbls/{C}showVal").get("val") == "1"


def test_drill_names_point_at_line_identity(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "compare.xlsx")
    values = load_workbook(path, data_only=True)
    try:
        names = values.defined_names
        for name in ("_Compare_CountRows", "_Compare_TimeRows", "_Compare_TableRows"):
            assert name in names
        assert names["_Compare_TableRows"].attr_text.endswith("!$C$29:$E$30")
        helper = values["_module_compare"]
        assert [helper[f"{c}2"].value for c in "PQR"] == ["공장A", "팀1", "실제설비A"]
        assert [helper[f"{c}2"].value for c in "UVW"] == ["공장B", "팀2", "실제설비B"]
        assert helper["Y2"].value == 2 and helper["Y3"].value == 2
        scoped = values[SHEET].defined_names
        assert "INDEX('_module_compare'!$N$2:$N$11" in scoped["_Compare_CountLabels"].attr_text
    finally:
        values.close()


def test_sheet_views_have_no_orphan_pane_selections(organization_result, tmp_path):
    """Excel refuses to open a sheet whose selections name panes that do not exist."""
    path = export_report(organization_result, tmp_path / "compare.xlsm")
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith("xl/worksheets/sheet"):
                continue
            xml = archive.read(name).decode("utf-8")
            for view in re.findall(r"<(?:\w+:)?sheetView\b.*?</(?:\w+:)?sheetView>", xml, re.S):
                if re.search(r'<(?:\w+:)?selection [^>]*pane="', view):
                    assert re.search(r"<(?:\w+:)?pane\b", view), name


def test_chart_ranges_use_absolute_item_counts(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "compare.xlsx")
    book = load_workbook(path)
    try:
        for name, item in book[SHEET].defined_names.items():
            if name.startswith("_Compare_"):
                assert re.search(r"MAX\(1,'_module_compare'!\$Y\$[23]\)", item.attr_text), name
    finally:
        book.close()
