"""One final classification counts once; ranked candidates remain review evidence."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from core.aggregation import grouped
from core.component_analysis import component_tables
from core.fault_components import component_payload, type_label
from core.i18n import K
from core.sorting import descending
from report.charts import figure_for, tidy_label
from report.classification import COMPONENT_FIELDS, classification_result
from report.excel_report import SHEETS, D, export_report
from report.pdf_report import export_pdf

OUTPUT_D = {
    key: get_column_letter(column_index_from_string(column) + 1) for key, column in D.items()
}


def test_type_chart_labels_keep_part_and_symptom_instead_of_collapsing_to_symptom():
    labels = ["기계 / 베어링 / 손상", "공압·진공 / 실린더 / 손상"]
    assert tidy_label(labels[0]) != tidy_label(labels[1])
    table = pd.DataFrame({"type": labels, "count": [1, 1], "total_minutes": [20, 10]})
    figure = figure_for(table, "type")
    try:
        shown = " ".join(tick.get_text() for tick in figure.axes[0].get_yticklabels())
        assert "베어링" in shown and "실린더" in shown and "손상" in shown
    finally:
        figure.clear()


@pytest.fixture
def component_result(store, input_file):
    result = analyze_file(store, input_file)
    selected = result.selected.copy(deep=True)
    a = {"major": "기계", "middle": "모터*?#1", "minor": "손상"}
    b = {"major": "전기", "middle": "센서*?#10", "minor": "감지불량"}
    for index in selected.index:
        category = a if index < 2 else {key: "" for key in a}
        for key, value in {
            **category,
            **component_payload([a] if index < 2 else [], "single" if index < 2 else "ambiguous"),
        }.items():
            selected.loc[index, key] = value
        selected.loc[index, "type"] = type_label(a) if index < 2 else K["review"]
        selected.loc[index, "classification_candidates"] = json.dumps(
            [a, b] if index == 2 else [], ensure_ascii=False
        )
    selected.loc[0, "status"] = K["manual"]
    selected.loc[1, "status"] = K["auto"]
    selected.loc[2, "status"] = K["review"]
    selected.loc[2, "candidate_evidence"] = "1. 모터*?#1 / 손상; 2. 센서*?#10 / 감지불량"
    selected.loc[3, "status"] = K["code_missing"]
    selected.loc[3, "classification_mode"] = "unclassified"
    tables = {
        **result.tables,
        **component_tables(selected),
        "type": grouped(selected, ["type"]),
        "equipment_type": grouped(selected, ["equipment", "type"]),
        "review": selected.iloc[[2, 3]].copy(),
        "long_stops": descending(selected, "minutes"),
    }
    return replace(
        result,
        selected=selected,
        tables=tables,
        metrics={
            **result.metrics,
            "manual_rows": 1,
            "auto_rows": 1,
            "review_rows": 2,
            "classification_review_rows": 1,
        },
    )


def test_excel_single_final_counts_exclude_pending_candidates(component_result, tmp_path):
    original = component_result.selected.copy(deep=True)
    path = export_report(component_result, tmp_path / "single.xlsx")
    values = load_workbook(path, data_only=True)
    formulas = load_workbook(path, data_only=False)
    try:
        assert [ws.title for ws in values if ws.sheet_state == "visible"] == list(SHEETS.values())
        assert values["_report_metrics"]["A2"].value == 4
        assert values["_report_metrics"]["A3"].value == 95
        assert "별첨. 부품별분석" not in values.sheetnames
        facts = values["_issue_facts"]
        headers = [cell.value for cell in facts[1]]
        parts = [facts.cell(row, headers.index("part") + 1).value for row in range(2, 6)]
        assert parts.count("모터*?#1") == 2
        assert "센서*?#10" not in parts
        assert len(parts) == 4  # Pending records remain, without adopting candidate parts.
        detail = values[SHEETS["detail"]]
        rows = {detail[f"{OUTPUT_D['record_id']}{row}"].value: row for row in range(7, 11)}
        for record in original.to_dict("records"):
            row = rows[record["record_id"]]
            members = json.loads(detail[f"{OUTPUT_D['component_details']}{row}"].value)
            assert len(members) <= 1
            if record["status"] == K["review"]:
                assert members == []
                assert (
                    len(json.loads(detail[f"{OUTPUT_D['classification_candidates']}{row}"].value))
                    == 2
                )
        faults = values[SHEETS["fault_detail"]]
        assert faults.max_row == 10
        assert len({faults.cell(row, 2).value for row in range(7, 11)}) == 4
        headers = [cell.value for cell in faults[6]]
        from core.i18n import DISPLAY

        status_column = headers.index(DISPLAY["status"]) + 1
        review_row = next(
            row for row in range(7, 11) if faults.cell(row, status_column).value == K["review"]
        )
        classification_columns = [
            headers.index(DISPLAY[key]) + 1
            for key in ("major", "detail_equipment", "middle", "minor")
        ]
        assert [faults.cell(review_row, column).value for column in classification_columns] == [
            None,
            None,
            None,
            None,
        ]
        manual_row = next(
            row
            for row in range(7, values[SHEETS["criteria"]].max_row + 1)
            if values[SHEETS["criteria"]].cell(row, 2).value == K["manual"]
        )
        assert values[SHEETS["criteria"]].cell(manual_row, 3).value == 1
        assert "COUNTIF" in formulas[SHEETS["criteria"]].cell(manual_row, 3).value
    finally:
        values.close()
        formulas.close()
    pd.testing.assert_frame_equal(component_result.selected, original)


def test_pdf_explains_single_selection_and_preserves_candidate_evidence(component_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(export_pdf(component_result, tmp_path / "single.pdf"))
    compact = "".join("".join(page.extract_text() or "" for page in reader.pages).split())
    for phrase in (
        "한 고장이력은 하나의 최종 분류",
        "최종 분류 하나",
        "미확정 후보",
        "모터*?#1",
        "센서*?#10",
        "100%보다 작을 수",
    ):
        assert "".join(phrase.split()) in compact
    assert "100%를초과" not in compact
    assert "복수유형조합" not in compact


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
            if key not in ("component", "component_trend", "combination", "fault_detail")
        },
    )
    workbook = load_workbook(export_report(result, tmp_path / "legacy.xlsx"), data_only=True)
    try:
        assert len([ws for ws in workbook if ws.sheet_state == "visible"]) == 11
        assert "별첨. 부품별분석" not in workbook.sheetnames
        assert workbook[SHEETS["detail"]][f"{OUTPUT_D['component_count']}7"].value is None
    finally:
        workbook.close()


def test_legacy_multiple_classification_is_candidates_only_and_one_detail_row(
    component_result, tmp_path
):
    selected = component_result.selected.copy(deep=True)
    members = [
        {"major": "기계", "middle": f"후보 부품 {index:02d}", "minor": f"증상 {index:02d}"}
        for index in range(40)
    ]
    for field, value in component_payload(members, "multiple").items():
        selected.loc[0, field] = value
    selected.loc[0, "status"] = K["manual_multi"]
    result = replace(component_result, selected=selected)
    snapshot = classification_result(result)
    pending = snapshot.selected.iloc[0]
    assert pending.status == K["review"]
    assert pending.component_details == "[]" and pending.component_count == 0
    assert len(json.loads(pending.classification_candidates)) == 40
    assert snapshot.tables["fault_detail"].record_id.is_unique
    assert len(snapshot.tables["fault_detail"]) == len(selected)
    assert snapshot.tables["component"]["count"].sum() == 1
    workbook = load_workbook(
        export_report(result, tmp_path / "older_multiple.xlsx"), data_only=True
    )
    try:
        detail = workbook[SHEETS["detail"]]
        row = next(
            row
            for row in range(7, 11)
            if detail[f"{OUTPUT_D['record_id']}{row}"].value == pending.record_id
        )
        candidates = json.loads(detail[f"{OUTPUT_D['classification_candidates']}{row}"].value)
        assert {member["middle"] for member in candidates} == {
            member["middle"] for member in members
        }
        assert detail[f"{OUTPUT_D['component_details']}{row}"].value == "[]"
        assert workbook["_report_metrics"]["A3"].value == 95
    finally:
        workbook.close()
    assert len(json.loads(result.selected.iloc[0].component_details)) == 40


def test_manual_single_confirmation_adds_only_selected_part_and_keeps_event_totals(
    component_result,
):
    selected = component_result.selected.copy(deep=True)
    candidates = json.loads(selected.iloc[2].classification_candidates)
    choice = candidates[1]
    for field, value in {**choice, **component_payload([choice], "single")}.items():
        selected.loc[2, field] = value
    selected.loc[2, "type"] = type_label(choice)
    selected.loc[2, "status"] = K["manual"]
    selected.loc[2, "classification_candidates"] = "[]"
    result = classification_result(replace(component_result, selected=selected))
    assert result.tables["component"]["count"].sum() == 3
    assert result.tables["component"]["count_share"].sum() == 0.75
    assert result.tables["component"]["manual_count"].sum() == 2
    assert result.tables["type"]["count"].sum() == 4
    assert result.tables["type"]["total_minutes"].sum() == 95
    assert len(result.tables["fault_detail"]) == 4
