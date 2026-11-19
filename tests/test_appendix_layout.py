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
        assert "별첨. 동일 상세설비 비교" not in book
        assert book[SHEETS["review"]]["B7"].value == len(result.selected)
    finally:
        book.close()
