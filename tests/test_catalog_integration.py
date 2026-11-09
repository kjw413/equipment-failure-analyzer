"""Fresh production rules keep detailed component types through analysis and export."""

from hashlib import sha256

from conftest import analyze_file
from openpyxl import load_workbook

from core.failure_modes import part_name
from core.fault_components import parse_components
from core.i18n import K
from report.excel_report import SHEETS, D, export_report


def test_current_catalog_types_and_multi_part_members_survive_report_export(
    store, catalog_input, approved_catalog_paths, tmp_path
):
    original_hash = sha256(catalog_input.read_bytes()).hexdigest()
    result = analyze_file(store, catalog_input)
    rows = result.selected.set_index("source_row")
    for source_row, path in {
        5: ("유체·배관", "로터리펌프", "파손"),
        6: ("기계", "타이밍벨트", "파손"),
        8: ("공압·진공", "로드리스실린더", "파손"),
    }.items():
        assert tuple(rows.loc[source_row, ["major", "middle", "minor"]]) == path
        assert rows.loc[source_row, "status"] == K["auto"]
    multiple = rows.loc[4]
    assert multiple.classification_mode == "multiple" and multiple.status == K["review"]
    source_parts = {
        ("유체·배관", "펌프", "도징펌프"),
        ("전기·제어", "센서·검출", "근접센서"),
    }
    expected_members = {
        (major, part_name(part), "파손" if part == "도징펌프" else "고장·이상")
        for major, _, part in source_parts
    }
    assert {
        tuple(member[key] for key in ("major", "middle", "minor"))
        for member in parse_components(multiple.component_details)
    } == expected_members
    assert source_parts <= approved_catalog_paths
    assert result.metrics["selected_rows"] == 4 and result.metrics["total_minutes"] == 95
    assert result.tables["component"]["count"].sum() == 5

    workbook = load_workbook(export_report(result, tmp_path / "catalog.xlsx"), data_only=True)
    try:
        assert workbook[SHEETS["summary"]]["A7"].value == 4
        assert workbook[SHEETS["summary"]]["E7"].value == 95
        detail = workbook[SHEETS["detail"]]
        for row in range(7, detail.max_row + 1):
            for member in parse_components(detail[f"{D['component_details']}{row}"].value):
                assert (
                    member["major"],
                    member["part_group"],
                    member["part_type"],
                ) in approved_catalog_paths
        component_labels = {
            f"{major} / {part_name(part)}" for major, _, part in approved_catalog_paths
        }
        component = workbook[SHEETS["component"]]
        assert {component.cell(row, 1).value for row in range(7, 12)} <= component_labels
        assert all(cell.data_type != "e" for sheet in workbook for row in sheet for cell in row)
    finally:
        workbook.close()
    assert sha256(catalog_input.read_bytes()).hexdigest() == original_hash
