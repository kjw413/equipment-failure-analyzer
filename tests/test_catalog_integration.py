"""Fresh production rules keep detailed component types through analysis and export."""

from hashlib import sha256

from conftest import analyze_file
from openpyxl import load_workbook

from core.failure_modes import UNKNOWN_PART
from core.fault_components import parse_components
from core.i18n import K
from core.public_taxonomy import default_taxonomy
from report.excel_report import SHEETS, D, export_report


def test_current_catalog_types_and_ranked_candidates_survive_report_export(
    store, catalog_input, approved_catalog_paths, tmp_path
):
    original_hash = sha256(catalog_input.read_bytes()).hexdigest()
    result = analyze_file(store, catalog_input)
    rows = result.selected.set_index("source_row")
    expected_missing = {
        5: "세부 부품",  # A pump body establishes the module, not its inner failed part.
        6: "상세설비·모듈",
        8: "상세설비·모듈",
    }
    for source_row, path in {
        5: ("유체·배관", UNKNOWN_PART, "손상·파손"),
        6: ("기계", "타이밍벨트", "손상·파손"),
        8: ("공압·진공", "로드리스실린더", "손상·파손"),
    }.items():
        assert tuple(rows.loc[source_row, ["major", "middle", "minor"]]) == path
        assert rows.loc[source_row, "status"] == K["partial"]
        assert rows.loc[source_row, "classification_missing_fields"] == expected_missing[source_row]
        assert rows.loc[source_row, "component_count"] == 1
    representative = rows.loc[4]
    assert representative.classification_mode == "single"
    assert representative.status == K["partial"]
    assert representative.component_count == 1 and representative.part_count == 0
    assert representative.classification_missing_fields == "세부 부품"
    assert "1순위 대표 자동선택" in representative.classification_reason
    source_parts = {
        ("유체·배관", "펌프", "도징펌프"),
        ("전기·제어", "센서·검출", "근접센서"),
    }
    expected_members = {
        ("유체·배관", UNKNOWN_PART, "손상·파손"),
        ("전기·제어", "근접센서", "고장·이상"),
    }
    candidates = parse_components(representative.classification_candidates)
    assert {
        tuple(member[key] for key in ("major", "middle", "minor")) for member in candidates
    } == expected_members
    assert len(candidates) == 2
    selected = parse_components(representative.component_details)
    assert len(selected) == 1
    assert tuple(selected[0][key] for key in ("major", "detail_equipment", "middle", "minor")) == (
        "유체·배관",
        "펌프",
        UNKNOWN_PART,
        "손상·파손",
    )
    assert all(selected[0].get(key) == value for key, value in candidates[0].items())
    assert selected[0]["selected_rank"] == 1
    assert selected[0]["selection_method"] == "top_ranked_representative"
    assert source_parts <= approved_catalog_paths
    assert result.metrics["selected_rows"] == 4 and result.metrics["total_minutes"] == 95
    assert result.metrics["auto_rows"] == 0
    assert result.metrics["partial_rows"] == result.metrics["auto_processed_rows"] == 4
    assert result.metrics["classification_review_rows"] == 0
    assert result.metrics["review_rows"] == 1  # The unrelated missing-time record stays in review.
    assert result.tables["component"]["count"].sum() == 2
    assert rows.loc[5, "detail_equipment"] == "펌프" and rows.loc[5, "part_count"] == 0
    assert result.tables["fault_detail"].record_id.is_unique
    assert len(result.tables["fault_detail"]) == 4

    workbook = load_workbook(export_report(result, tmp_path / "catalog.xlsx"), data_only=True)
    try:
        assert workbook[SHEETS["summary"]]["A7"].value == 4
        assert workbook[SHEETS["summary"]]["E7"].value == 95
        detail = workbook[SHEETS["detail"]]
        representative_row = next(
            row
            for row in range(7, detail.max_row + 1)
            if detail[f"{D['source_row']}{row}"].value == 4
        )
        assert (
            "1순위 대표 자동선택"
            in detail[f"{D['classification_reason']}{representative_row}"].value
        )
        assert (
            parse_components(detail[f"{D['classification_candidates']}{representative_row}"].value)
            == candidates
        )
        assert (
            parse_components(detail[f"{D['component_details']}{representative_row}"].value)
            == selected
        )
        for row in range(7, detail.max_row + 1):
            for member in parse_components(detail[f"{D['component_details']}{row}"].value):
                assert (
                    member["middle"] == UNKNOWN_PART or member["middle"] in default_taxonomy().names
                )
                assert member["part_group"] == default_taxonomy().group(member["middle"])
        component_labels = {
            " / ".join(member[key] for key in ("major", "detail_equipment", "middle"))
            for value in result.selected.component_details
            for member in parse_components(value)
        }
        component = workbook[SHEETS["component"]]
        assert {
            component.cell(row, 1).value for row in range(7, 7 + len(result.tables["component"]))
        } <= component_labels
        assert all(cell.data_type != "e" for sheet in workbook for row in sheet for cell in row)
    finally:
        workbook.close()
    assert sha256(catalog_input.read_bytes()).hexdigest() == original_hash
