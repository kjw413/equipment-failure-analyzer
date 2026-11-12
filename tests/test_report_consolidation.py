"""Manager report consolidation preserves audit data and independent denominators."""

import re
from dataclasses import replace

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from core.i18n import DISPLAY, K
from core.models import AnalysisOptions
from report.classification import COMPONENT_FIELDS, classification_result
from report.excel_report import SHEETS, D, export_report

EXPECTED_SHEETS = [
    "01_종합현황",
    "02_설비별분석",
    "03_라인별분석",
    "04_유형별분석",
    "05_기간별추이",
    "06_부품별분석",
    "07_고장이력",
    "08_부품증상상세",
    "09_검토품질",
    "10_원본데이터",
    "11_기준정보",
    "12_제품교차분석",
]


def find_header(sheet, labels):
    return next(
        row
        for row in range(6, sheet.max_row + 1)
        if [sheet.cell(row, col).value for col in range(1, len(labels) + 1)] == labels
    )


def assert_cached_formulas(formulas, values):
    for sheet in formulas:
        for row in sheet:
            for cell in row:
                if cell.data_type == "f":
                    assert "#REF!" not in cell.value
                    for target in re.findall(r"'([^']+)'!", cell.value):
                        assert target in formulas.sheetnames, (sheet.title, cell.coordinate, target)
                    assert values[sheet.title][cell.coordinate].data_type != "e"
    assert formulas.calculation.fullCalcOnLoad
    assert formulas.calculation.forceFullCalc
    summary = SHEETS["summary"]
    assert formulas[summary]["A7"].data_type == "f"
    assert values[summary]["A7"].value == 4
    assert values[summary]["E7"].value == 95
    assert SHEETS["detail"] in formulas[summary]["E7"].value


def assert_product_crosses(result, sheet):
    for table_key, keys in (
        ("product_type", ["product", "type"]),
        ("equipment_product", ["equipment", "product"]),
        ("triple", ["equipment", "product", "type"]),
    ):
        header = find_header(sheet, [DISPLAY[key] for key in keys])
        count_column = len(keys) + 1
        time_column = len(keys) + 4
        rows = range(header + 1, header + 1 + len(result.tables[table_key]))
        assert sum(sheet.cell(row, count_column).value for row in rows) == 4
        assert sum(sheet.cell(row, time_column).value or 0 for row in rows) == 95
    assert not any(
        [sheet.cell(row, col).value for col in (1, 2)] == [DISPLAY["equipment"], DISPLAY["type"]]
        for row in range(6, sheet.max_row + 1)
    )
    for metric in ("count", "total"):
        header = find_header(sheet, [K["product"], K[metric]])
        rows = range(header + 1, header + 1 + len(result.tables["product"]))
        assert sum(sheet.cell(row, 2).value or 0 for row in rows) == (
            4 if metric == "count" else 95
        )


def assert_equipment_cross_statistics(result, formulas, values):
    headers = [
        row
        for row in range(7, values.max_row + 1)
        if values.cell(row, 1).value == "고장유형" and values.cell(row, 2).value == "건수"
    ]
    assert len(headers) == len(result.tables["equipment"])
    for header, equipment in zip(headers, result.tables["equipment"].equipment):
        assert [values.cell(header, column).value for column in (10, 11, 12)] == [
            "최대 정지(분)",
            "전체 분석 건수 비중",
            "전체 분석 시간 비중",
        ]
        subset = result.selected.loc[result.selected.equipment.eq(equipment)]
        for row in range(header + 1, header + 1 + subset.type.nunique()):
            matching = subset.loc[subset.type.eq(values.cell(row, 1).value)]
            assert not matching.empty
            expected_max = matching.minutes.max()
            if pd.isna(expected_max):
                assert values.cell(row, 10).value in (None, "")
            else:
                assert values.cell(row, 10).value == expected_max
                assert "MAX(" in formulas.cell(row, 10).value
                assert SHEETS["detail"] in formulas.cell(row, 10).value
            assert formulas.cell(row, 10).data_type == "f"
            assert values.cell(row, 3).value == pytest.approx(len(matching) / len(subset))
            assert values.cell(row, 11).value == pytest.approx(len(matching) / len(result.selected))
            assert "COUNTA(" in formulas.cell(row, 11).value
            assert SHEETS["detail"] in formulas.cell(row, 11).value
            expected_time = matching.minutes.sum(min_count=1)
            if pd.isna(expected_time):
                assert values.cell(row, 12).value in (None, "")
            else:
                assert values.cell(row, 12).value == pytest.approx(
                    expected_time / result.metrics["total_minutes"]
                )
            assert "SUM(" in formulas.cell(row, 12).value
            assert SHEETS["detail"] in formulas.cell(row, 12).value


@pytest.mark.parametrize("has_products", [False, True])
def test_consolidated_report_keeps_manager_tables_and_audit_contract(
    store, catalog_input, tmp_path, has_products
):
    if not has_products:
        source = load_workbook(catalog_input)
        source.active.delete_cols(4)
        source.save(catalog_input)
        source.close()
    result = analyze_file(store, catalog_input, AnalysisOptions(top_n=2))
    source_bytes = catalog_input.read_bytes()
    selected_before = result.selected.copy(deep=True)
    all_before = result.all_records.copy(deep=True)
    loaded_before = result.loaded.frame.copy(deep=True)
    path = export_report(result, tmp_path / f"consolidated_{has_products}.xlsx")
    values = load_workbook(path, data_only=True)
    formulas = load_workbook(path, data_only=False)
    try:
        assert list(SHEETS.values()) == EXPECTED_SHEETS
        assert values.sheetnames == EXPECTED_SHEETS[: 12 if has_products else 11]
        assert_cached_formulas(formulas, values)

        # The overview retains the global denominator and the full local rankings.
        equipment = values[SHEETS["equipment"]]
        length = len(result.tables["equipment"])
        assert sum(equipment.cell(row, 2).value for row in range(7, 7 + length)) == 4
        assert sum(equipment.cell(row, 3).value for row in range(7, 7 + length)) == pytest.approx(1)
        assert sum(equipment.cell(row, 5).value for row in range(7, 7 + length)) == 95
        totals = [
            row for row in range(7, equipment.max_row + 1) if equipment.cell(row, 1).value == "합계"
        ]
        assert len(totals) == length
        assert sum(equipment.cell(row, 2).value for row in totals) == 4
        assert sum(equipment.cell(row, 5).value or 0 for row in totals) == 95
        assert all(equipment.cell(row, 3).value == pytest.approx(1) for row in totals)
        assert len(equipment._images) == length + 2
        assert len(values[SHEETS["type"]]._images) == 3
        assert_equipment_cross_statistics(
            classification_result(result), formulas[SHEETS["equipment"]], equipment
        )

        # One history owns all formula references, and only the requested TOP is marked.
        detail = values[SHEETS["detail"]]
        assert [detail[f"{D['minutes']}{row}"].value for row in range(7, 11)] == [65, 20, 10, None]
        assert {detail[f"{D['record_id']}{row}"].value for row in range(7, 11)} == set(
            result.selected.record_id
        )
        assert all(
            detail[f"{D['minutes']}{row}"].fill.fgColor.rgb.endswith("FFF2CC") for row in (7, 8)
        )
        assert not detail[f"{D['minutes']}9"].fill.fgColor.rgb.endswith("FFF2CC")
        assert not detail[f"{D['minutes']}10"].fill.fgColor.rgb.endswith("FFF2CC")

        review = values[SHEETS["review"]]
        assert [cell.value for cell in review[6]] == [
            "원본 행",
            "작업일자",
            "라인명",
            "등록 설비(변환)",
            "고장대상 설비",
            "원본 대분류",
            "원본 중분류",
            "원본 소분류",
            "분석 설비",
            "제품명",
            "정지시간(분)",
            "표준 유형",
            "분류 상태",
            "고장내용(설비명 변환)",
            "정규화 내용",
            "고장 분야",
            "상세설비·모듈",
            "부품군",
            "세부 부품",
            "고장 현상",
            "조치 내역",
            "후보 규칙",
        ]
        queue_length = len(result.tables["review"])
        queue_rows = {review.cell(row, 1).value for row in range(7, 7 + queue_length)}
        assert queue_rows == set(result.tables["review"].source_row)
        assert not review.column_dimensions["A"].hidden
        assert range_boundaries(review.auto_filter.ref)[3] == 6 + queue_length
        criteria = values[SHEETS["criteria"]]
        assert review.max_column == 22 and review.max_row == max(7, 6 + queue_length)
        quality_row = next(
            row
            for row in range(7, criteria.max_row + 1)
            if criteria.cell(row, 1).value == K["auto"]
        )
        assert criteria.cell(quality_row, 2).value == result.metrics["auto_rows"]
        assert formulas[SHEETS["criteria"]].cell(quality_row, 2).data_type == "f"

        # Monthly memberships remain a static snapshot with their own filter.
        component = formulas[SHEETS["component"]]
        monthly = next(
            row for row in range(7, component.max_row + 1) if component.cell(row, 6).value == "월"
        )
        count = len(result.tables["component_trend"])
        assert monthly > 6 + len(result.tables["component"])
        assert (
            sum(component.cell(row, 2).value for row in range(monthly + 1, monthly + 1 + count))
            == result.tables["component_trend"]["count"].sum()
        )
        assert all(
            component.cell(row, col).data_type != "f"
            for row in range(monthly + 1, monthly + 1 + count)
            for col in range(1, 7)
        )
        assert any(range_boundaries(table.ref)[1] == monthly for table in component.tables.values())

        criteria = values[SHEETS["criteria"]]
        assert range_boundaries(criteria.auto_filter.ref)[1] == 6
        rule_header = find_header(criteria, ["id", "enabled"])
        assert rule_header > range_boundaries(criteria.auto_filter.ref)[3]
        assert any(
            range_boundaries(table.ref)[1] == rule_header for table in criteria.tables.values()
        )
        assert [
            criteria.cell(row, 1).value
            for row in range(
                rule_header + 1, rule_header + 1 + len(result.config_snapshot["rules"])
            )
        ] == [rule["id"] for rule in result.config_snapshot["rules"]]

        raw = values[SHEETS["raw"]]
        assert [raw.cell(row, 1).value for row in range(7, 12)] == result.loaded.frame[
            "__source_row"
        ].tolist()
        included_column = next(cell.column for cell in raw[6] if cell.value == "_included")
        assert sum(raw.cell(row, included_column).value for row in range(7, 12)) == 4
        if has_products:
            assert_product_crosses(result, values[SHEETS["cross"]])
        else:
            assert SHEETS["cross"] not in values.sheetnames
    finally:
        values.close()
        formulas.close()
    assert catalog_input.read_bytes() == source_bytes
    pd.testing.assert_frame_equal(result.selected, selected_before)
    pd.testing.assert_frame_equal(result.all_records, all_before)
    pd.testing.assert_frame_equal(result.loaded.frame, loaded_before)


def test_saved_legacy_section_names_route_to_consolidated_sheets(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    settings = {
        **result.config_snapshot["settings"],
        "report_sections": [
            "summary",
            "equipment_types",
            "pareto",
            "component_trend",
            "top",
            "quality",
            "rules",
            "names",
        ],
    }
    result = replace(result, config_snapshot={**result.config_snapshot, "settings": settings})
    workbook = load_workbook(
        export_report(result, tmp_path / "legacy_sections.xlsx"), data_only=True
    )
    try:
        assert SHEETS["equipment"] in workbook.sheetnames
        assert SHEETS["type"] in workbook.sheetnames
        assert SHEETS["review"] in workbook.sheetnames
        assert SHEETS["criteria"] in workbook.sheetnames
        # Older Pareto choices also retain the product Pareto after consolidation.
        assert SHEETS["cross"] in workbook.sheetnames
        assert_product_crosses(result, workbook[SHEETS["cross"]])
        assert all(name in EXPECTED_SHEETS for name in workbook.sheetnames)
        assert len(workbook.sheetnames) == len(set(workbook.sheetnames))
        assert workbook[SHEETS["summary"]]["E7"].value == 95
    finally:
        workbook.close()


def test_period_tables_show_calendar_order_even_when_downtime_ranking_differs(
    store, input_file, tmp_path
):
    source = load_workbook(input_file)
    for row, date in {4: "2026-01-01", 5: "2026-03-01", 6: "2026-02-01", 8: "2026-03-02"}.items():
        source.active.cell(row, 1, date)
    source.save(input_file)
    source.close()
    result = analyze_file(store, input_file)
    workbook = load_workbook(export_report(result, tmp_path / "calendar.xlsx"), data_only=True)
    try:
        sheet = workbook[SHEETS["trend"]]
        header = find_header(sheet, [DISPLAY["period"], DISPLAY["count"]])
        rows = range(header + 1, header + 1 + len(result.tables["trend_month"]))
        assert [sheet.cell(row, 1).value for row in rows] == ["2026-01", "2026-02", "2026-03"]
        assert [sheet.cell(row, 5).value for row in rows] == [10, 65, 20]
    finally:
        workbook.close()


def test_legacy_result_without_memberships_or_products_uses_nine_sheets(
    store, input_file, tmp_path
):
    source = load_workbook(input_file)
    source.active.delete_cols(4)
    source.save(input_file)
    source.close()
    result = analyze_file(store, input_file)
    result = replace(
        result,
        selected=result.selected.drop(columns=list(COMPONENT_FIELDS), errors="ignore"),
        tables={
            key: table
            for key, table in result.tables.items()
            if key not in ("component", "component_trend", "combination", "fault_detail")
        },
    )
    workbook = load_workbook(
        export_report(result, tmp_path / "legacy_without_products.xlsx"), data_only=True
    )
    try:
        assert len(workbook.sheetnames) == 9
        assert SHEETS["component"] not in workbook.sheetnames
        assert SHEETS["fault_detail"] not in workbook.sheetnames
        assert SHEETS["cross"] not in workbook.sheetnames
        assert workbook[SHEETS["summary"]]["A7"].value == 4
        assert workbook[SHEETS["summary"]]["E7"].value == 95
    finally:
        workbook.close()
