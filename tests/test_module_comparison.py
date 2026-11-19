"""The former module-comparison appendix is consolidated into 04."""

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report


def test_module_comparison_has_one_home(organization_result, tmp_path):
    book = load_workbook(export_report(organization_result, tmp_path / "consolidated.xlsm"))
    try:
        assert "별첨. 동일 상세설비 비교" not in book
        assert "_module_compare" not in book
        assert len(book["04.고장비교"]._charts) == 2
        assert "_Fault_List_baseline_module" in book.defined_names
        assert "_Fault_List_compare_module" in book.defined_names
        assert all(
            s.sheet_view.pane is None and all(x.pane is None for x in s.sheet_view.selection)
            for s in book
        )
    finally:
        book.close()
