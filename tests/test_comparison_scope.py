"""A baseline line must not narrow the factory comparison population."""

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report


def test_line_baseline_never_filters_population(organization_result, tmp_path):
    book = load_workbook(export_report(organization_result, tmp_path / "scope.xlsx"))
    try:
        rows = list(book["_fault_rows"].iter_rows(min_row=2, values_only=True))
        # Aggregate metrics never depend on the chosen baseline or comparison filters.
        assert all("04.고장비교" not in r[5] for r in rows)
        assert all("$E$6" not in r[11] and "$I$6" not in r[11] for r in rows if r[0] == "부서")
        assert all("$I$6" not in r[11] and "$I$8" not in r[11] for r in rows if r[0] == "라인")
        assert all("$I$6" in r[11] for r in rows if r[0] == "상세설비")
        controls = {
            r[0]: r[1] for r in book["_fault_controls"].iter_rows(min_row=2, values_only=True)
        }
        assert "family" not in controls and "mode" not in controls
        assert controls["baseline_module"] == "I6" and controls["compare_module"] == "I8"
        assert controls["asset"] == "E6"
        assert controls["organization"] == "B6"
        assert controls["compare_organization"] == "B8" and controls["compare_asset"] == "E8"
        # Lists are scoped to each side's own organization, never the other side.
        for address in ("B2", "E2"):
            formula = book["_fault_list_flags"][address].value
            assert "_fault_state" in formula
    finally:
        book.close()
