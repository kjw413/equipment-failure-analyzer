"""The November layout uses real rankings and repaired, exact filter locations."""

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import SHEETS, export_report


def test_line_rankings_and_repaired_controls(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "renewal.xlsm")
    values = load_workbook(path, data_only=True)
    formulas = load_workbook(path)
    try:
        summary = values["01.종합현황"]
        assert (summary["B10"].value, summary["D10"].value) == ("실제설비A", 4)
        assert (summary["B23"].value, summary["D23"].value) == ("실제설비B", 100)
        assert summary["A34"].value is None
        assert len(summary.conditional_formatting) == 2
        assert summary.row_dimensions[5].height == 21
        assert summary["A1"].font.sz == 20
        comparison = values["03.팀간 비교"]
        assert sum(comparison.cell(row, 3).value or 0 for row in range(22, 29)) == 6
        assert sum(comparison.cell(row, 4).value or 0 for row in range(22, 29)) == 144
        expected = {
            "02.팀별 주요이슈": {"B5", "D5", "G5", "K5", "K6"},
            "03.팀간 비교": {"B5", "E5", "I5"},
            "04.고장추이": {"B5", "D5", "F5", "J5", "J6"},
        }
        for name, positions in expected.items():
            assert {
                str(v.sqref) for v in formulas[name].data_validations.dataValidation
            } == positions
        assert "#REF!" not in formulas["_issue_filter_2"]["A2"].value
        assert "_Issue_comparison_mode" not in formulas["_issue_filter_2"]["A2"].value
        assert "$J$5" in formulas["_issue_filter_3"]["A2"].value
        assert "$J$6" in formulas["_issue_filter_3"]["A2"].value
        assert "생략" not in {c.value for row in summary for c in row if isinstance(c.value, str)}
        appendix = values[SHEETS["detail"]]
        assert appendix.row_dimensions[7].height == 21.95
        assert "$C$1:$M$" in str(appendix.print_area)
    finally:
        values.close()
        formulas.close()
