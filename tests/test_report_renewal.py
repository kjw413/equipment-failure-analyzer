"""Locked main templates and styled appendices retain calculated report values."""

from datetime import datetime

import pytest
from conftest import analyze_file
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from report.excel_report import DETAIL_COLS, SHEETS, export_report


def test_renewal_summary_uses_correct_average_and_configured_department(
    store, input_file, tmp_path
):
    store.save_report_settings({"department": "생산기술팀"})
    result = analyze_file(store, input_file)
    path = export_report(result, tmp_path / "renewed.xlsx")
    values = load_workbook(path, data_only=True)
    formulas = load_workbook(path)
    try:
        summary = values[SHEETS["summary"]]
        metrics = values["_report_metrics"]
        assert [metrics[cell].value for cell in ("A2", "A3")] == [4, 95]
        # One of the four records has no duration; it is not a zero-minute stop.
        assert metrics["A4"].value == pytest.approx(95 / 3)
        assert "4건" in summary["A5"].value and "95분" in summary["A5"].value
        assert "32분" in summary["A5"].value
        assert formulas[SHEETS["summary"]]["A5"].data_type == "f"
        appendix = values[SHEETS["review"]]
        assert appendix["B3"].value == f"{datetime.now():%Y.%m.%d} 생산기술팀 작성"
        assert appendix["B3"].alignment.horizontal == "right"
        assert "AVERAGE(" in formulas["_report_metrics"]["A4"].value
        minutes_column = get_column_letter(DETAIL_COLS.index("minutes") + 2)
        assert f"${minutes_column}$" in formulas["_report_metrics"]["A4"].value
        assert len(summary._images) == 0
        assert values.sheetnames[:4] == [
            "01.종합현황",
            "02.팀별 주요이슈",
            "03.월별 주요이슈",
            "04.고장비교",
        ]
        for sheet in values:
            if sheet.sheet_state != "visible" or sheet.title in (*values.sheetnames[:4], SHEETS["source_review"]):
                continue
            assert all(cell.value is None for cell in sheet["A"])
            assert not any(area.min_col == 1 for area in sheet.merged_cells.ranges)
            assert sheet["B2"].font.name == "KoPubWorld돋움체 Medium"
            assert sheet["B2"].font.sz == 16
    finally:
        values.close()
        formulas.close()
