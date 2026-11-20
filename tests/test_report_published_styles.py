from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report


def test_edited_report_positions_and_month_labels(organization_result, tmp_path):
    workbook = load_workbook(
        export_report(organization_result, tmp_path / "report.xlsm"), data_only=True
    )
    try:
        summary, team, month, comparison = workbook.worksheets[:4]
        assert summary["B9"].value == "실제설비A"
        assert all(
            s["A3"].value.startswith("집계기간:") for s in (summary, team, month, comparison)
        )
        assert {str(rule.sqref) for rule in team.data_validations.dataValidation} == {
            "B7",
            "D7",
            "G7",
            "K7",
            "K8",
        }
        assert {"B27:C27", "H27:I27"} <= {str(area) for area in team.merged_cells}
        assert team["B27"].value == team["H27"].value == "라인"
        for title in ("별첨. 검토·분류현황", "별첨. 고장이력"):
            sheet = workbook[title]
            assert sheet.sheet_format.defaultRowHeight == 22
            assert sheet.sheet_format.customHeight
            assert {sheet.row_dimensions[row].height for row in range(1, sheet.max_row + 1)} == {22}
        assert "L7:L8" in month.merged_cells
        assert month["A25"].value == "2026-01"
        assert workbook["_period_display"]["A2"].value == "'26-01"
        for chart in month._charts:
            assert chart.series[0].cat.strRef.strCache.pt[0].v == "'26-01"
        assert [chart.anchor._from.row for chart in month._charts] == [9, 9]
        assert comparison.auto_filter.ref.startswith("A25:L")
        assert comparison["E26"].value == 4
    finally:
        workbook.close()
