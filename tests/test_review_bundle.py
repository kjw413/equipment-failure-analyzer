import hashlib
from datetime import datetime
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from conftest import analyze_file
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Border, Font, Side

from core.models import UserError
from report.excel_report import export_report
from report.export_bundle import export_bundle
from report.review_overview import SOURCE_SHEET


def test_one_workbook_has_review_summary_and_annotated_input(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    digest = hashlib.sha256(input_file.read_bytes()).hexdigest()
    paths = export_bundle(result, tmp_path / "reports/analysis.xlsm")
    assert paths.source_review is None
    assert list(paths.excel.parent.iterdir()) == [paths.excel]
    book = load_workbook(paths.excel, data_only=True)
    try:
        visible = [s.title for s in book if s.sheet_state == "visible"]
        assert len(visible) == 8  # 7 required sheets plus product cross-analysis.
        assert "별첨. 부품증상상세" not in book
        assert "별첨. 동일 상세설비 비교" not in book and "별첨. 기준정보" not in book
        assert "_module_compare" not in book and "_source_quality" not in book
        overview = book["별첨. 검토·분류현황"]
        assert overview["B7"].value == len(result.selected)
        assert overview["C7"].value == len(result.tables["review"])
        assert sum(
            overview.cell(r, 3).value or 0 for r in range(11, 11 + result.selected.status.nunique())
        ) == len(result.selected)
        raw = book[SOURCE_SHEET]
        original = load_workbook(input_file, data_only=True)
        try:
            for row in original[result.loaded.sheet]:
                for cell in row:
                    assert raw[cell.coordinate].value == cell.value, cell.coordinate
        finally:
            original.close()
        assert raw["E8"].comment and "검토필요 유형" in raw["E8"].comment.text
        assert raw["E8"].fill.patternType == "solid"
        assert all(s.freeze_panes is None for s in book)
    finally:
        book.close()
    formulas = load_workbook(paths.excel)
    try:
        links = [
            c.value
            for row in formulas["별첨. 검토·분류현황"]
            for c in row
            if c.data_type == "f" and "HYPERLINK" in c.value
        ]
        assert sum(SOURCE_SHEET in value for value in links) == len(result.tables["review"])
        assert sum("별첨. 고장이력" in value and "MATCH(" in value for value in links) == len(
            result.tables["review"]
        )
        assert all(c.data_type != "f" for row in formulas[SOURCE_SHEET] for c in row)
    finally:
        formulas.close()
    assert hashlib.sha256(input_file.read_bytes()).hexdigest() == digest


def test_input_snapshot_preserves_coordinates_styles_notes_and_formula_information(
    store, input_file, tmp_path
):
    source = load_workbook(input_file)
    ws = source["Events"]
    ws["F8"].font = Font(name="Arial", bold=True, color="001122")
    ws["F8"].number_format = "0.00"
    ws["F8"].border = Border(left=Side(style="thin", color="123456"))
    ws["E8"].comment = Comment("원본 메모", "User")
    ws["J4"] = "=F4*2"
    ws.column_dimensions["E"].width = 43
    ws.row_dimensions[8].height = 48
    ws.freeze_panes = "D4"
    source.save(input_file)
    source.close()
    result = analyze_file(store, input_file)
    digest = input_file.read_bytes()
    output = export_report(result, tmp_path / "snapshot.xlsx")
    book = load_workbook(output)
    try:
        ws = book[SOURCE_SHEET]
        assert ws["F8"].font.name == "Arial" and ws["F8"].font.bold
        assert ws["F8"].number_format == "0.00"
        assert ws["F8"].border.left.color.rgb == "00123456"
        assert ws["E8"].comment.text.startswith("원본 메모\n\n")
        assert ws["E8"].comment.author == "User"
        assert ws["J4"].value == "=F4*2" and ws["J4"].data_type == "s"
        assert ws.column_dimensions["E"].width == 43 and ws.row_dimensions[8].height == 48
        assert ws.freeze_panes is None
        with ZipFile(output) as archive:
            assert len(archive.namelist()) == len(set(archive.namelist()))
    finally:
        book.close()
    assert input_file.read_bytes() == digest


def test_changed_source_does_not_replace_existing_analysis(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    output = tmp_path / "existing.xlsx"
    output.write_bytes(b"keep existing")
    with open(input_file, "ab") as stream:
        stream.write(b"changed")
    with pytest.raises(UserError, match="원본 파일이 변경"):
        export_report(result, output)
    assert output.read_bytes() == b"keep existing"


def test_raw_snapshot_keeps_dates_when_source_uses_1904_epoch(store, input_file, tmp_path):
    from openpyxl.utils.datetime import CALENDAR_MAC_1904

    book = load_workbook(input_file)
    book.epoch = CALENDAR_MAC_1904
    book["Events"]["A4"] = datetime(2026, 1, 1)
    book.save(input_file)
    book.close()
    result = analyze_file(store, input_file)
    output = export_report(result, tmp_path / "epoch.xlsx")
    book = load_workbook(output, data_only=True)
    try:
        assert book[SOURCE_SHEET]["A4"].value == datetime(2026, 1, 1)
    finally:
        book.close()


def test_raw_snapshot_uses_cached_formula_results_including_empty_strings(
    store, input_file, tmp_path
):
    book = load_workbook(input_file)
    book["Events"]["J4"] = "=10+10.5"
    book["Events"]["J5"] = '=IF(1=1,"","x")'
    book.save(input_file)
    book.close()
    with ZipFile(input_file) as source:
        parts = {n: source.read(n) for n in source.namelist()}
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    sheet.find(f'.//{ns}c[@r="J4"]/{ns}v').text = "20.5"
    sheet.find(f'.//{ns}c[@r="J5"]').set("t", "str")
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
    with ZipFile(input_file, "w") as target:
        for name, data in parts.items():
            target.writestr(name, data)
    result = analyze_file(store, input_file)
    book = load_workbook(export_report(result, tmp_path / "cached.xlsx"), data_only=False)
    try:
        assert book[SOURCE_SHEET]["J4"].value == 20.5
        assert book[SOURCE_SHEET]["J5"].value in ("", None)
        assert all(book[SOURCE_SHEET][c].data_type != "f" for c in ("J4", "J5"))
    finally:
        book.close()
