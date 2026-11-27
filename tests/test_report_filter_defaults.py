"""New report filters start at the first choice without erasing saved settings."""

from copy import deepcopy

import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.issue_analysis import ALL
from report.excel_report import export_report
from report.issue_workbook import ISSUE_SHEETS


@pytest.mark.parametrize("saved_case", ["", "사용자가 저장한 별도 고장사례"])
def test_excel_filter_values_start_at_first_list_item(store, input_file, tmp_path, saved_case):
    store.save_report_settings({"focus_case": saved_case})
    result = analyze_file(store, input_file)
    original_config = deepcopy(result.config_snapshot)
    workbook = load_workbook(export_report(result, tmp_path / "defaults.xlsx"))
    try:
        checked = 0
        for sheet_name in ISSUE_SHEETS.values():
            sheet = workbook[sheet_name]
            for validation in sheet.data_validations.dataValidation:
                assert validation.type == "list"
                name = validation.formula1.removeprefix("=")
                if name.startswith('"'):
                    first_choice = name.strip('"').split(",")[0]
                elif name.startswith("_Fault_List_"):
                    from report.fault_comparison import CONTROLS

                    column = list(CONTROLS).index(name.removeprefix("_Fault_List_")) + 1
                    first_choice = workbook["_fault_list_source"].cell(1, column).value
                else:
                    destinations = list(workbook.defined_names[name].destinations)
                    assert len(destinations) == 1
                    source_sheet, source_range = destinations[0]
                    first_choice = workbook[source_sheet][source_range][0][0].value
                for target_range in validation.sqref.ranges:
                    value = sheet.cell(target_range.min_row, target_range.min_col).value
                    assert value in (ALL, first_choice), (sheet_name, str(target_range), value)
                    checked += 1
        assert checked == 16
        assert result.config_snapshot == original_config
        assert store.read("final_report.json")["focus_case"] == saved_case
    finally:
        workbook.close()


def test_main_window_filters_start_at_first_choice(store, input_file):
    pytest.importorskip("PySide6")
    from gui.main_window import MainWindow

    window = MainWindow(store)
    window.draw_chart = lambda *_args: None
    try:
        window.loaded_ready(analyze_file(store, input_file).loaded)
        for combo in (
            window.scope,
            window.basis,
            window.units,
            window.factory_filter,
            window.team_filter,
            window.chart_choice,
            window.chart_metric,
        ):
            assert combo.currentIndex() == 0
        assert window.chart_metric.currentData() == "count"
        window.chart_metric.setCurrentIndex(1)
        assert window.chart_metric.currentData() == "total_minutes"
    finally:
        window.close()
        window.deleteLater()


def test_report_settings_reopens_saved_department(store):
    pytest.importorskip("PySide6")
    from gui.report_settings import ReportSettingsDialog

    department = "생산기술팀"
    store.save_report_settings({"department": department})
    dialog = ReportSettingsDialog(store)
    try:
        assert dialog.department.text() == department
    finally:
        dialog.close()
        dialog.deleteLater()
