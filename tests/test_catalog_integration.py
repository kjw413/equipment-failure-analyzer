"""Fresh production rules keep detailed component types through analysis and export."""

from hashlib import sha256

from conftest import analyze_file
from openpyxl import load_workbook

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
        5: ("유체·배관", "펌프", "로터리펌프"),
        6: ("기계", "벨트·풀리", "타이밍벨트"),
        8: ("공압·진공", "실린더", "로드리스실린더"),
    }.items():
        assert tuple(rows.loc[source_row, ["major", "middle", "minor"]]) == path
        assert rows.loc[source_row, "status"] == K["auto"]
    multiple = rows.loc[4]
    assert multiple.classification_mode == "multiple" and multiple.status == K["review"]
    expected_members = {
        ("유체·배관", "펌프", "도징펌프"),
        ("전기·제어", "센서·검출", "근접센서"),
    }
    assert {
        tuple(member[key] for key in ("major", "middle", "minor"))
        for member in parse_components(multiple.component_details)
    } == expected_members
    assert expected_members <= approved_catalog_paths
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
                    tuple(member[key] for key in ("major", "middle", "minor"))
                    in approved_catalog_paths
                )
        component_labels = {" / ".join(path) for path in approved_catalog_paths}
        component = workbook[SHEETS["component"]]
        assert {component.cell(row, 1).value for row in range(7, 12)} <= component_labels
        assert all(cell.data_type != "e" for sheet in workbook for row in sheet for cell in row)
    finally:
        workbook.close()
    assert sha256(catalog_input.read_bytes()).hexdigest() == original_hash
