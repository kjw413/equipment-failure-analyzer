"""Different leading organizations must lead each metric's comparison chart."""

from types import SimpleNamespace

from openpyxl import Workbook, load_workbook
from test_report_issue_views import organization_result as organization_result

from report.cache import FormulaCache
from report.comparison_rank import HELPER, SHEET, build_comparison_ranks
from report.excel_report import export_report


def test_comparison_charts_rank_independently_without_reordering_table(
    organization_result, tmp_path
):
    before = organization_result.selected.copy(deep=True)
    path = export_report(organization_result, tmp_path / "rank.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        table = values[SHEET]
        assert [(table.cell(r, 1).value, table.cell(r, 5).value) for r in (25, 26)] == [
            ("공장A", 4),
            ("공장B", 2),
        ]
        helper = values["_fault_chart_rank"]
        assert [helper.cell(r, 7).value for r in (2, 3)] == ["[공장A] 팀1", "[공장B] 팀2"]
        assert [helper.cell(r, 8).value for r in (2, 3)] == [4, 2]
        assert [helper.cell(r, 9).value for r in (2, 3)] == ["[공장B] 팀2", "[공장A] 팀1"]
        assert [helper.cell(r, 10).value for r in (2, 3)] == [100, 44]
        assert helper.sheet_state == "hidden"
        assert formulas["_fault_chart_rank"]["C2"].value == "='04.고장비교'!F25"
        assert "COUNTIFS(" in formulas["_fault_chart_rank"]["F2"].value
        assert organization_result.selected.equals(before)
    finally:
        values.close()
        formulas.close()


def test_comparison_zero_missing_and_ties_have_distinct_meaning():
    book, cache = Workbook(), FormulaCache()
    sheet = book.active
    sheet.title = SHEET
    examples = [("A", 3, 50), ("B", 3, ""), ("C", 0, 0), ("D", 1, 50)]
    for row, (label, count, minutes) in enumerate(examples, 22):
        sheet.cell(row, 10, label)
        cache.set(sheet, f"C{row}", "=1", count)
        cache.set(sheet, f"D{row}", '=IF(1=1,"",0)', minutes)
    builder = SimpleNamespace(wb=book, cache=cache, _locked_template={"sheets": {SHEET: {}}})
    build_comparison_ranks(builder)
    values = cache.values
    assert [values[(HELPER, f"G{r}")] for r in range(2, 6)] == ["A", "B", "D", "C"]
    assert [values[(HELPER, f"I{r}")] for r in range(2, 6)] == ["A", "D", "C", ""]
    assert [values[(HELPER, f"J{r}")] for r in range(2, 6)] == [50, 50, 0, ""]
    assert values[(HELPER, "C3")] == "" and values[(HELPER, "D3")] == 0
    assert values[(HELPER, "C4")] == 0 and values[(HELPER, "D4")] == 1
    ranges = builder._locked_template["sheets"][SHEET]["comparison_chart_ranges"]
    assert ranges["C"]["category"] != ranges["D"]["category"]
