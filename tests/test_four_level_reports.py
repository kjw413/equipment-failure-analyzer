"""Four classification axes retain event identity, totals and equipment context."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from core.component_analysis import component_tables
from core.failure_modes import (
    CLASSIFICATION_SCHEMA,
    LEGACY_CLASSIFICATION_SCHEMA,
    PREVIOUS_CLASSIFICATION_SCHEMA,
    UNKNOWN_PART,
    UNKNOWN_SYMPTOM,
)
from core.fault_components import CATEGORY_FIELDS, component_payload, type_label
from core.i18n import DISPLAY, K
from report.classification import classification_result
from report.excel_report import DETAIL_COLS, REVIEW_COLS, SHEETS, D, export_report
from report.pdf_report import export_pdf

OUTPUT_D = {
    key: get_column_letter(column_index_from_string(column) + 1) for key, column in D.items()
}


def event(number, equipment, *, pending=False):
    category = {
        "major": "기계",
        "detail_equipment": equipment,
        "middle": "베어링",
        "minor": "마모",
        "part_group": "베어링·부싱",
        "actions": ["교체"],
        "schema": CLASSIFICATION_SCHEMA,
    }
    return {
        "record_id": str(number),
        "event_id": f"event-{number}",
        "date": pd.Timestamp("2026-01-02"),
        "equipment": "공통 라인",
        "line": "L1",
        "kind": K["fault"],
        "minutes": 10,
        "raw_description": f"{equipment} 베어링 마모",
        "status": K["review"] if pending else K["auto"],
        "detail_equipment_source": "원문 고장 문맥",
        "repair_actions": "교체",
        "classification_candidates": json.dumps([category], ensure_ascii=False),
        **{key: "" if pending else category[key] for key in CATEGORY_FIELDS},
        **component_payload([] if pending else [category], "ambiguous" if pending else "single"),
    }


def test_same_part_on_different_detail_equipment_is_not_merged_or_double_counted():
    records = pd.DataFrame([event(1, "컨베어"), event(2, "필러"), event(3, "컨베어", pending=True)])
    tables = component_tables(records)
    assert tables["component"]["count"].sum() == 2
    assert set(tables["component"].component_type) == {
        "기계 / 컨베어 / 베어링",
        "기계 / 필러 / 베어링",
    }
    assert tables["component"].count_share.tolist() == pytest.approx([1 / 3, 1 / 3])
    details = tables["fault_detail"]
    assert len(details) == 3 and details.event_id.is_unique
    assert not set(details).intersection({"minutes", "total_minutes"})
    assert details.loc[details.record_id.eq("3"), list(CATEGORY_FIELDS)].eq("").all().all()


def test_machine_only_classification_keeps_detail_without_counting_an_invented_part():
    record = event(1, "컨베어")
    member = json.loads(record["component_details"])[0]
    member["middle"] = UNKNOWN_PART
    record.update({"middle": UNKNOWN_PART, **component_payload([member])})
    tables = component_tables(pd.DataFrame([record]))
    assert tables["component"].empty
    detail = tables["fault_detail"].iloc[0]
    assert detail.detail_equipment == "컨베어"
    assert detail.middle == UNKNOWN_PART
    assert detail.status == K["auto"]
    assert record["component_count"] == 1 and record["part_count"] == 0


@pytest.fixture
def hierarchy_result(store, input_file):
    result = analyze_file(store, input_file)
    records = result.selected.copy(deep=True)
    for index in records.index:
        category = {
            "major": "기계",
            "detail_equipment": "필러" if index % 2 else "컨베어",
            "middle": "베어링",
            "minor": "마모",
            "part_group": "베어링·부싱",
            "actions": ["교체"],
            "schema": CLASSIFICATION_SCHEMA,
        }
        for key, value in {**category, **component_payload([category])}.items():
            records.at[index, key] = value
        records.at[index, "status"] = K["auto"]
        records.at[index, "type"] = type_label(category)
        records.at[index, "detail_equipment_source"] = "원문 고장 문맥"
        records.at[index, "repair_actions"] = "교체"
    return replace(result, selected=records, tables={**result.tables, **component_tables(records)})


def test_four_axes_export_in_order_and_preserve_cached_totals(hierarchy_result, tmp_path):
    before = hierarchy_result.selected.copy(deep=True)
    workbook = load_workbook(
        export_report(hierarchy_result, tmp_path / "four_axes.xlsx"), data_only=True
    )
    try:
        for keys in (DETAIL_COLS, REVIEW_COLS):
            fields = [
                "major",
                "detail_equipment",
                "part_group",
                "middle",
                "minor",
                "repair_actions",
            ]
            positions = [keys.index(key) for key in fields]
            assert positions == list(range(positions[0], positions[0] + len(fields)))
        detail = workbook[SHEETS["detail"]]
        assert detail[f"{OUTPUT_D['detail_equipment']}6"].value == DISPLAY["detail_equipment"]
        assert detail[f"{OUTPUT_D['detail_equipment']}7"].value in {"컨베어", "필러"}
        assert detail[f"{OUTPUT_D['detail_equipment_source']}7"].value == "원문 고장 문맥"
        assert detail[f"{OUTPUT_D['part_group']}7"].value == "베어링·부싱"
        assert detail[f"{OUTPUT_D['repair_actions']}7"].value == "교체"
        assert workbook["_report_metrics"]["A3"].value == hierarchy_result.metrics["total_minutes"]
        faults = workbook[SHEETS["fault_detail"]]
        headers = [cell.value for cell in faults[6]]
        fields = ["major", "detail_equipment", "part_group", "middle", "minor", "repair_actions"]
        positions = [headers.index(DISPLAY[key]) for key in fields]
        assert positions == list(range(positions[0], positions[0] + len(fields)))
        assert faults.auto_filter.ref.startswith("B6:O")
        assert faults.column_dimensions["P"].hidden
        assert faults.cell(7, headers.index(DISPLAY["repair_actions"]) + 1).value == "교체"
    finally:
        workbook.close()
    pd.testing.assert_frame_equal(hierarchy_result.selected, before)


def test_pending_report_clears_all_four_final_axes(hierarchy_result):
    selected = hierarchy_result.selected.copy(deep=True)
    selected.loc[selected.index[0], "status"] = K["review"]
    projected = classification_result(replace(hierarchy_result, selected=selected))
    assert all(projected.selected.iloc[0][key] == "" for key in CATEGORY_FIELDS)
    assert projected.selected.iloc[0].part_group == ""
    assert projected.selected.iloc[0].repair_actions == "교체"
    assert projected.tables["fault_detail"].iloc[0].repair_actions == "교체"


def test_explicitly_cleared_action_does_not_reappear_from_original_evidence(
    hierarchy_result, tmp_path
):
    selected = hierarchy_result.selected.copy(deep=True)
    selected["repair_actions"] = ""
    cleared = replace(
        hierarchy_result,
        selected=selected,
        tables={**hierarchy_result.tables, **component_tables(selected)},
    )
    workbook = load_workbook(export_report(cleared, tmp_path / "cleared_action.xlsx"))
    try:
        detail = workbook[SHEETS["detail"]]
        assert detail[f"{OUTPUT_D['repair_actions']}7"].value is None
        faults = workbook[SHEETS["fault_detail"]]
        headers = [cell.value for cell in faults[6]]
        assert faults.cell(7, headers.index(DISPLAY["repair_actions"]) + 1).value is None
        assert faults.cell(7, headers.index(DISPLAY["actions"]) + 1).value == "교체"
    finally:
        workbook.close()
    pd.testing.assert_series_equal(selected["repair_actions"], cleared.selected["repair_actions"])


@pytest.mark.parametrize(
    "previous_schema", [LEGACY_CLASSIFICATION_SCHEMA, PREVIOUS_CLASSIFICATION_SCHEMA]
)
def test_explicit_previous_schema_is_preserved_as_review_candidates(
    hierarchy_result, previous_schema
):
    selected = hierarchy_result.selected.copy(deep=True)
    index = selected.index[0]
    old = {
        "major": "기계",
        "middle": "베어링",
        "minor": "마모",
        "schema": previous_schema,
    }
    selected.at[index, "component_details"] = json.dumps([old], ensure_ascii=False)
    selected.at[index, "classification_schema"] = previous_schema
    selected.at[index, "classification_candidates"] = "[]"
    projected = classification_result(replace(hierarchy_result, selected=selected))
    revised = projected.selected.loc[index]
    assert revised.status == K["review"]
    assert revised.component_count == 0
    assert all(revised[key] == "" for key in CATEGORY_FIELDS)
    assert json.loads(revised.classification_candidates)[0]["middle"] == "베어링"
    assert "새 기준" in revised.classification_reason
    assert revised.repair_actions == "교체"
    assert selected.loc[index].component_count == 1


def test_pdf_exposes_equipment_and_part_axes(hierarchy_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = export_pdf(hierarchy_result, tmp_path / "four_axes.pdf")
    compact = "".join(
        "".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages).split()
    )
    for expected in (
        "고장분야",
        "상세설비",
        "부품군",
        "세부부품",
        "고장현상",
        "조치",
        "컨베어",
        "필러",
        "베어링",
        "교체",
    ):
        assert expected in compact


@pytest.fixture
def partial_result(hierarchy_result):
    records = hierarchy_result.selected.copy(deep=True)
    records["classification_missing_fields"] = ""
    index = records.index[0]
    member = json.loads(records.at[index, "component_details"])[0]
    member["minor"] = UNKNOWN_SYMPTOM
    for key, value in {**member, **component_payload([member])}.items():
        records.at[index, key] = value
    records.at[index, "status"] = K["partial"]
    records.at[index, "type"] = type_label(member)
    records.at[index, "classification_missing_fields"] = "고장 현상"
    return replace(
        hierarchy_result,
        selected=records,
        tables={
            **hierarchy_result.tables,
            **component_tables(records),
            "review": records.iloc[:0].copy(),
        },
        metrics={**hierarchy_result.metrics, "review_rows": 0},
    )


def test_partial_projection_keeps_known_part_and_missing_axis_without_review(partial_result):
    before = partial_result.selected.copy(deep=True)
    projected = classification_result(partial_result)
    record = projected.selected.iloc[0]
    assert record.status == K["partial"]
    assert record.middle == "베어링"
    assert record.minor == UNKNOWN_SYMPTOM
    assert record.repair_actions == "교체"
    assert record.classification_missing_fields == "고장 현상"
    assert projected.metrics["partial_rows"] == 1
    assert projected.metrics["auto_rows"] == len(before) - 1
    assert projected.metrics["auto_processed_rows"] == len(before)
    assert projected.metrics["review_rows"] == 0
    assert projected.metrics["unresolved_classification_rows"] == 0
    assert len(projected.tables["fault_detail"]) == len(before)
    assert projected.tables["component"]["count"].sum() == len(before)
    pd.testing.assert_frame_equal(before, partial_result.selected)


def test_partial_excel_has_separate_counts_and_retains_missing_field(partial_result, tmp_path):
    workbook = load_workbook(
        export_report(partial_result, tmp_path / "partial.xlsx"), data_only=True
    )
    try:
        sheet = workbook[SHEETS["detail"]]
        partial = [
            row
            for row in sheet.iter_rows(min_row=7, values_only=True)
            if row[DETAIL_COLS.index("status") + 1] == K["partial"]
        ]
        assert len(partial) == 1
        assert partial[0][DETAIL_COLS.index("middle") + 1] == "베어링"
        assert partial[0][DETAIL_COLS.index("minor") + 1] == UNKNOWN_SYMPTOM
        assert partial[0][DETAIL_COLS.index("classification_missing_fields") + 1] == "고장 현상"
        summary = workbook[SHEETS["summary"]]["A6"].value
        assert "부분 자동분류 1건" in summary
        assert "완전 자동분류" in summary
        assert "검토 대상 0건" in summary
        quality = {
            row[1].value: row[2].value for row in workbook[SHEETS["criteria"]] if len(row) >= 3
        }
        assert quality[K["partial"]] == 1
        assert quality["자동처리 합계(완전+부분)"] == len(partial_result.selected)
    finally:
        workbook.close()


def test_partial_pdf_explains_automatic_coverage_separately(partial_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = export_pdf(partial_result, tmp_path / "partial.pdf")
    compact = "".join(
        "".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages).split()
    )
    for phrase in (
        "완전자동분류",
        "부분자동분류1건",
        "자동처리합계",
        "원문미기재항목",
        "현상미기재",
    ):
        assert phrase in compact
