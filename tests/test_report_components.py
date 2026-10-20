"""Combined events retain one downtime and expose separate member-event counts."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.aggregation import grouped
from core.fault_components import combination_category, component_payload, type_label
from core.i18n import K
from core.sorting import descending
from report.classification import COMPONENT_FIELDS
from report.excel_report import SHEETS, D, export_report
from report.pdf_report import brief_type, export_pdf


@pytest.fixture
def component_result(store, input_file):
    result = analyze_file(store, input_file)
    selected = result.selected.copy(deep=True)
    a = {"major": "기계", "middle": "구동", "minor": "모터*?#1 이상"}
    b = {"major": "기계", "middle": "구동", "minor": "모터*?#10 이상"}
    c = {"major": "전기", "middle": "감지", "minor": "센서 동시 이상"}
    members = ([a, b], [a, c], [b], [])
    for index, values in enumerate(members):
        mode = "multiple" if len(values) > 1 else "single"
        for field, value in component_payload(values, mode).items():
            selected.loc[index, field] = value
        if len(values) > 1:
            category = combination_category(values)
            for field, value in category.items():
                selected.loc[index, field] = value
            selected.loc[index, "type"] = type_label(category)
    selected.loc[0, "status"] = K["manual_multi"]
    selected.loc[1, "status"] = K["review"]
    selected.loc[2, "status"] = K["auto"]
    selected.loc[2, "type"] = type_label(b)
    tables = dict(result.tables)
    tables["type"] = grouped(selected, ["type"])
    tables["equipment_type"] = grouped(selected, ["equipment", "type"])
    tables["review"] = selected.iloc[[1]].copy()
    tables["long_stops"] = descending(selected, "minutes")
    tables["component"] = pd.DataFrame(
        [
            {
                "component_type": type_label(a),
                "count": 2,
                "manual_count": 1,
                "review_count": 1,
                "count_share": 0.5,
            },
            {
                "component_type": type_label(b),
                "count": 2,
                "manual_count": 1,
                "review_count": 0,
                "count_share": 0.5,
            },
            {
                "component_type": type_label(c),
                "count": 1,
                "manual_count": 0,
                "review_count": 1,
                "count_share": 0.25,
            },
        ]
    )
    tables["component_trend"] = tables["component"].assign(period="2026-01")
    tables["combination"] = grouped(selected.iloc[:2], ["type"])
    return replace(
        result,
        selected=selected,
        tables=tables,
        metrics={**result.metrics, "manual_rows": 1},
    )


def test_excel_components_are_snapshot_event_counts_without_time_allocation(
    component_result, tmp_path
):
    path = export_report(component_result, tmp_path / "components.xlsx")
    values = load_workbook(path, data_only=True)
    formulas = load_workbook(path, data_only=False)
    try:
        assert values.sheetnames == list(SHEETS.values())
        assert values[SHEETS["summary"]]["A7"].value == 4
        assert values[SHEETS["summary"]]["E7"].value == 95
        component = values[SHEETS["component"]]
        assert [component.cell(row, 2).value for row in (7, 8, 9)] == [2, 2, 1]
        assert [component.cell(row, 3).value for row in (7, 8, 9)] == [1, 1, 0]
        assert [component.cell(row, 4).value for row in (7, 8, 9)] == [1, 0, 1]
        assert sum(component.cell(row, 5).value for row in (7, 8, 9)) == 1.25
        assert "정적표" in component["A5"].value
        assert "정지시간" not in " ".join(str(cell.value) for cell in component[6])
        assert values[SHEETS["component_trend"]]["A7"].value == "2026-01"
        assert values[SHEETS["component_trend"]]["F6"].value == "해당 월 전체 고장기록 대비 비율"
        detail = values[SHEETS["detail"]]
        for record in component_result.selected.to_dict("records"):
            row = next(
                row for row in range(7, 11) if detail.cell(row, 1).value == record["record_id"]
            )
            assert detail[f"{D['component_count']}{row}"].value == record["component_count"]
            assert json.loads(detail[f"{D['component_details']}{row}"].value) == json.loads(
                record["component_details"]
            )
            if record["status"] == K["manual_multi"]:
                assert detail[f"{D['classification_mode']}{row}"].value == "복수 유형 조합"
                assert record["classification_mode"] == "multiple"
        quality = values[SHEETS["quality"]]
        manual_row = next(
            row
            for row in range(1, quality.max_row + 1)
            if quality.cell(row, 1).value == K["manual"]
        )
        assert quality.cell(manual_row, 2).value == 1
        assert "COUNTIF" in formulas[SHEETS["quality"]].cell(manual_row, 2).value
        assert K["manual_multi"] in formulas[SHEETS["quality"]].cell(manual_row, 2).value
        type_table = values[SHEETS["type"]]
        assert (
            sum(
                type_table.cell(row, 5).value or 0
                for row in range(7, 7 + len(component_result.tables["type"]))
            )
            == 95
        )
    finally:
        values.close()
        formulas.close()


def test_pdf_components_explain_combination_policy_and_keep_full_names(component_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(export_pdf(component_result, tmp_path / "components.pdf"))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    compact = "".join(text.split())
    for phrase in (
        "사건 1회·정지시간 1회",
        "100%를 초과",
        "잠정 검토",
        "규칙 기반 분류 원칙",
        "모터*?#1 이상",
        "모터*?#10 이상",
        "센서 동시 이상",
    ):
        assert "".join(phrase.split()) in compact
    label = component_result.selected.iloc[0]["type"]
    assert brief_type(label) == label


def test_legacy_report_without_component_fields_or_tables_still_exports(
    store, input_file, tmp_path
):
    result = analyze_file(store, input_file)
    result = replace(
        result,
        selected=result.selected.drop(columns=list(COMPONENT_FIELDS), errors="ignore"),
        tables={
            key: table.drop(columns=list(COMPONENT_FIELDS), errors="ignore")
            for key, table in result.tables.items()
            if key not in ("component", "component_trend", "combination")
        },
    )
    workbook = load_workbook(export_report(result, tmp_path / "legacy.xlsx"), data_only=True)
    try:
        assert len(workbook.sheetnames) == 15
        assert SHEETS["component"] not in workbook.sheetnames
        assert workbook[SHEETS["detail"]][f"{D['component_count']}7"].value is None
    finally:
        workbook.close()


def test_pdf_preserves_many_long_manual_component_names_across_pages(component_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    selected = component_result.selected.copy(deep=True)
    members = [
        {
            "major": "장문 부품 검증",
            "middle": f"다중확정 구성 {index:02d}",
            "minor": f"구성{index:02d}시작 "
            + "고장 부위와 증상 상세 설명 " * 9
            + f" 구성{index:02d}끝",
        }
        for index in range(40)
    ]
    category = combination_category(members)
    for field, value in {**category, **component_payload(members, "multiple")}.items():
        selected.loc[0, field] = value
    selected.loc[0, "type"] = type_label(category)
    tables = {
        **component_result.tables,
        "type": grouped(selected, ["type"]),
        "equipment_type": grouped(selected, ["equipment", "type"]),
        "long_stops": descending(selected, "minutes"),
    }
    result = replace(component_result, selected=selected, tables=tables)
    reader = pypdf.PdfReader(export_pdf(result, tmp_path / "long_components.pdf"))
    text = "".join((page.extract_text() or "") for page in reader.pages)
    compact = "".join(text.split())
    assert len(reader.pages) > 5
    for index in range(40):
        assert f"구성{index:02d}시작" in compact
        assert f"구성{index:02d}끝" in compact


def test_alternative_type_quality_counts_preserve_rule_review(component_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    result = replace(
        component_result,
        metrics={**component_result.metrics, "alternative_type_rows": 1},
    )
    workbook = load_workbook(export_report(result, tmp_path / "alternative.xlsx"), data_only=True)
    try:
        quality = workbook[SHEETS["quality"]]
        counts = {row[0].value: row[1].value for row in quality if len(row) >= 2}
        assert counts[K["alternative_type_rows"]] == 1
        assert counts[K["review"]] == 1
        sheet = workbook[SHEETS["component"]]
        policy_row = next(
            row[0].row
            for row in sheet
            if "대안 유형은 실제 동시고장 구성원이 아닙니다" in str(row[0].value)
        )
        assert int(str(sheet.print_area).rsplit("$", 1)[-1]) >= policy_row
    finally:
        workbook.close()
    reader = pypdf.PdfReader(export_pdf(result, tmp_path / "alternative.pdf"))
    compact = "".join("".join(page.extract_text() or "" for page in reader.pages).split())
    assert "대안유형검토1건" in compact
    assert "분류검토필요1건" in compact
    assert "대안유형은실제동시고장구성원이아닙니다" in compact
