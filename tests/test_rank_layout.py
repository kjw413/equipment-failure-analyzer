"""A TOP chart must not truncate its supporting data or round stored durations."""

from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from core.analyzer import analyze
from report.excel_report import export_report
from report.locked_template import NS


def test_full_tables_below_top_charts_keep_fractional_minutes(organization_result, tmp_path):
    base = organization_result.all_records.iloc[0].to_dict()
    rows = [
        dict(
            base,
            record_id=f"rank-{i}",
            event_id=f"rank-{i}",
            source_row=i + 4,
            report_equipment=f"라인{i:02d}",
            line=f"라인{i:02d}",
            minutes=1.25,
        )
        for i in range(12)
    ]
    result = analyze(
        organization_result.loaded,
        pd.DataFrame(rows),
        organization_result.config_snapshot,
        organization_result.options,
    )
    original = result.selected.copy(deep=True)
    path = export_report(result, tmp_path / "full.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        main = values["02.팀별 주요이슈"]
        assert [main.cell(row, 2).value for row in range(28, 40)] == [
            f"라인{i:02d}" for i in range(12)
        ]
        assert sum(main.cell(row, 4).value or 0 for row in range(28, main.max_row + 1)) == 12
        assert sum(main.cell(row, 5).value or 0 for row in range(28, main.max_row + 1)) == 15
        assert main["E28"].value == 1.25 and formulas[main.title]["E28"].number_format == "#,##0"
        assert "%" in formulas[main.title]["F28"].number_format
        assert not any(
            formulas[main.title].row_dimensions[row].hidden for row in range(28, main.max_row + 1)
        )
        appendix = values["별첨. 동일 상세설비 비교"]
        labels = [appendix.cell(row, 5).value for row in range(29, appendix.max_row + 1)]
        assert len([value for value in labels if value]) == 12
        assert (
            sum(appendix.cell(row, 8).value or 0 for row in range(29, appendix.max_row + 1)) == 12
        )
        assert "기타" not in labels
        for name in ("02.팀별 주요이슈", "03.팀간 비교", "04.월별 주요이슈"):
            sheet = formulas[name]
            assert all(chart.anchor._from.row < 26 for chart in sheet._charts)
            assert (
                sheet[
                    {"02.팀별 주요이슈": "A27", "03.팀간 비교": "A20", "04.월별 주요이슈": "A21"}[
                        name
                    ]
                ].value
                is not None
            )
        trend = formulas["04.월별 주요이슈"]
        assert trend.column_dimensions["L"].width == trend.column_dimensions["A"].width
        assert all(chart.anchor._from.row < 28 for chart in formulas[appendix.title]._charts)
        assert result.selected.equals(original)
        with ZipFile(path) as archive:
            charts = [
                ET.fromstring(archive.read(name))
                for name in archive.namelist()
                if name.startswith("xl/charts/chart") and name.endswith(".xml")
            ]
            horizontal = [
                root for root in charts if root.find('.//c:barDir[@val="bar"]', NS) is not None
            ]
            assert horizontal
            assert all(
                root.find(".//c:catAx/c:scaling/c:orientation", NS).get("val") == "maxMin"
                for root in horizontal
            )
            assert any(
                "$B$28:$B$32" in node.text
                for root in horizontal
                for node in root.findall(".//c:f", NS)
            )
    finally:
        values.close()
        formulas.close()
