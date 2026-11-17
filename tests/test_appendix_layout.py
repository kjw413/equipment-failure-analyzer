"""Evidence sheets put their charts above complete tables, without side scrolling."""

from conftest import analyze_file
from openpyxl import load_workbook

from report.excel_report import SHEETS, export_report


def test_appendix_images_use_left_edge_above_tabular_data(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    book = load_workbook(export_report(result, tmp_path / "appendices.xlsx"))
    try:
        for name in list(SHEETS.values())[4:]:
            if name not in book:
                continue
            assert name.startswith("별첨. ")
            for image in book[name]._images:
                assert image.anchor._from.col == 1  # B: shared appendix left margin
                assert image.anchor._from.row >= 6
        sheet = book[SHEETS["line"]]
        chart_row = sheet._charts[0].anchor._from.row + 1
        assert chart_row < 32
        assert all(chart.anchor._from.col == 1 for chart in sheet._charts)
        trend = book[SHEETS["trend"]]
        assert trend._images[0].anchor._from.row + 1 < 26
        assert trend["B26"].value == "기간"
    finally:
        book.close()
