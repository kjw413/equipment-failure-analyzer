"""The edited template's visible design survives generation and row growth."""

from copy import copy
from zipfile import ZipFile

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report
from report.locked_template import template_path


def test_edited_template_preserves_tables_styles_and_merged_headers(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "edited.xlsm")
    result, source = load_workbook(path), load_workbook(template_path())
    try:
        main = result["02.팀별 주요이슈"]
        assert main["A6"].value is None and main["A9"].value is None
        assert "시트 사용 방법" in main["A11"].value
        assert main["A26"].value == "○ 고장이력 (건수 내림차순)"
        assert main["G26"].value == "○ 고장이력 (시간 내림차순)"
        for name, addresses in {
            main.title: ("A1", "A11", "A26", "G26", "A27", "D27", "G27", "K27", "D28", "K28"),
            "03.팀간 비교": ("A1", "A20", "F20", "A22", "C22"),
            "04.고장추이": ("A1", "A21", "H21", "A23", "B23"),
        }.items():
            sheet, design = result[name], source[name]
            for address in addresses:
                for attr in ("font", "fill", "border", "alignment"):
                    assert copy(getattr(sheet[address], attr)) == copy(
                        getattr(design[address], attr)
                    ), (name, address, attr)
            for row in range(1, 24):
                assert sheet.row_dimensions[row].height == 21
            for chart, original in zip(sheet._charts, design._charts, strict=True):
                assert chart.anchor == original.anchor
        assert {"A20:A21", "J20:J21"} <= set(map(str, result["03.팀간 비교"].merged_cells.ranges))
        assert {"A21:A22", "K21:K22"} <= set(map(str, result["04.고장추이"].merged_cells.ranges))
        with ZipFile(path) as archive:
            assert all(
                b"#REF!" not in archive.read(name)
                for name in archive.namelist()
                if name.startswith("xl/charts/") and name.endswith(".xml")
            )
        assert all(
            (name.localSheetId is None or name.localSheetId < 4)
            for name in source.defined_names.values()
        )
    finally:
        result.close()
        source.close()
