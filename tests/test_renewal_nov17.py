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
        assert (summary["B9"].value, summary["D9"].value) == ("실제설비A", 4)
        assert (summary["B22"].value, summary["D22"].value) == ("실제설비B", 100)
        assert summary["A34"].value is None
        assert len(summary.conditional_formatting) == 2
        assert summary.row_dimensions[5].height == 21
        assert summary["A1"].font.sz == 20
        [(sheet_name, table_range)] = values.defined_names["_Fault_TableRows"].destinations
        assert sheet_name == SHEETS["issue_comparison"]
        rows = values[sheet_name][table_range]
        assert sum(row[4].value or 0 for row in rows) == 6
        assert sum(row[5].value or 0 for row in rows) == 144
        expected = {
            "02.팀별 주요이슈": {"B7", "D7", "G7", "K7", "K8"},
            "04.고장비교": {"B7", "E7", "B9"},
            "03.월별 주요이슈": {"B7", "D7", "F7", "J7", "J8", "B8", "D8"},
        }
        for name, positions in expected.items():
            assert {
                str(v.sqref) for v in formulas[name].data_validations.dataValidation
            } == positions
        assert "#REF!" not in formulas["_issue_filter_2"]["A2"].value
        assert "_Issue_comparison_mode" not in formulas["_issue_filter_2"]["A2"].value
        assert "$J$7" in formulas["_issue_filter_3"]["A2"].value
        assert "$J$8" in formulas["_issue_filter_3"]["A2"].value
        assert "생략" not in {c.value for row in summary for c in row if isinstance(c.value, str)}
        appendix = values[SHEETS["detail"]]
        assert appendix.column_dimensions["B"].hidden is False
        assert appendix.column_dimensions["T"].hidden is True
    finally:
        values.close()
        formulas.close()
