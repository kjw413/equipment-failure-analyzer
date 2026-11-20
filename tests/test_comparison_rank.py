"""Different leading organizations must lead each metric's comparison chart."""

from types import SimpleNamespace

from openpyxl import Workbook, load_workbook
from test_report_issue_views import organization_result as organization_result

from report.cache import FormulaCache
from report.excel_report import export_report
from report.fault_comparison import FIRST, SHEET, _charts

HELPER = "_fault_chart_rank"


def test_comparison_charts_rank_independently_without_reordering_table(
    organization_result, tmp_path
):
    before = organization_result.selected.copy(deep=True)
    path = export_report(organization_result, tmp_path / "rank.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        table = values[SHEET]
        assert [(table.cell(r, 1).value, table.cell(r, 5).value) for r in (FIRST, FIRST + 1)] == [
            ("공장A", 4),
            ("공장B", 2),
        ]
        helper = values[HELPER]
        assert [helper.cell(r, 7).value for r in (2, 3)] == ["[공장A] 팀1", "[공장B] 팀2"]
        assert [helper.cell(r, 8).value for r in (2, 3)] == [4, 2]
        assert [helper.cell(r, 9).value for r in (2, 3)] == ["[공장B] 팀2", "[공장A] 팀1"]
        assert [helper.cell(r, 10).value for r in (2, 3)] == [100, 44]
        assert helper.sheet_state == "hidden"
        assert formulas[HELPER]["C2"].value == f"='{SHEET}'!F{FIRST}"
        assert "COUNTIFS(" in formulas[HELPER]["F2"].value
        assert organization_result.selected.equals(before)
    finally:
        values.close()
        formulas.close()


def test_comparison_zero_missing_and_ties_have_distinct_meaning():
    book, cache = Workbook(), FormulaCache()
    sheet = book.active
    sheet.title = SHEET
    book.create_sheet("_fault_state")
    examples = [("A", 3, 50), ("B", 3, ""), ("C", 0, 0), ("D", 1, 50)]
    cached = [dict(label=label, count=count, minutes=minutes) for label, count, minutes in examples]
    builder = SimpleNamespace(wb=book, cache=cache, _locked_template={"sheets": {SHEET: {}}})
    _charts(builder, sheet, cached, len(cached))
    values = cache.values
    assert [values[(HELPER, f"G{r}")] for r in range(2, 6)] == ["A", "B", "D", "C"]
    assert [values[(HELPER, f"I{r}")] for r in range(2, 6)] == ["A", "D", "C", ""]
    assert [values[(HELPER, f"J{r}")] for r in range(2, 6)] == [50, 50, 0, ""]
    assert values[(HELPER, "C3")] == "" and values[(HELPER, "F3")] == ""
    assert values[(HELPER, "C4")] == 0 and values[(HELPER, "F4")] == 3
    ranges = builder._locked_template["sheets"][SHEET]["comparison_chart_ranges"]
    assert ranges["C"]["category"] != ranges["D"]["category"]
