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
        sheet = book[SHEETS["module_compare"]]
        # Count and time bars side by side above the full line table (row 28).
        assert [chart.anchor._from.row + 1 for chart in sheet._charts] == [12, 12]
        assert [chart.anchor._from.col for chart in sheet._charts] == [1, 7]
        assert sheet["B28"].value == "순위"
    finally:
        book.close()
