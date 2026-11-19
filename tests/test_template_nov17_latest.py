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
        assert main["A6"].value == "공장" and main["A9"].value is None
        assert main["A25"].value == "○ 고장이력 (건수 내림차순)"
        assert main["G25"].value == "○ 고장이력 (시간 내림차순)"
        for name, addresses in {
            main.title: ("A1", "A5", "A25", "G25", "A26", "D26", "G26", "K26", "D27", "K27"),
            "04.고장비교": ("A1", "A5"),
            "03.월별 주요이슈": ("A1", "A22", "H22", "A24", "B24"),
        }.items():
            sheet, design = result[name], source[name]
            for address in addresses:
                for attr in ("font", "fill", "border", "alignment"):
                    assert copy(getattr(sheet[address], attr)) == copy(
                        getattr(design[address], attr)
                    ), (name, address, attr)
            for row in range(1, 24):
                assert sheet.row_dimensions[row].height == design.row_dimensions[row].height
            for chart, original in zip(sheet._charts, design._charts, strict=True):
                assert chart.anchor == original.anchor
        assert result["04.고장비교"].auto_filter.ref.startswith("A24:L")
        assert {"A22:A23", "K22:K23"} <= set(
            map(str, result["03.월별 주요이슈"].merged_cells.ranges)
        )
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
