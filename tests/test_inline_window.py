"""Persisted grid edits refresh analysis without losing the operator's place."""
# ruff: noqa: E402

import os
import time

import pandas as pd
import pytest
from openpyxl import Workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from core.config import ConfigStore
from core.excel_loader import load_excel
from core.i18n import K
from core.service import run_analysis
from gui.main_window import MainWindow
from report.export_bundle import report_paths


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def grid_window(app, tmp_path, monkeypatch):
    """Three independent unresolved events with complete dates, times and targets."""
    source = tmp_path / "grid_edit_events.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Events"
    sheet.append(
        [
            "발생일",
            "설비코드",
            "설비명",
            "제품명",
            "고장내용",
            "정지시간",
            "정지구분",
            "고장대상설비",
        ]
    )
    for number, equipment in enumerate(("ALPHA", "BETA", "GAMMA"), 1):
        sheet.append(
            [
                f"2026-01-0{number}",
                f"GRID{number}",
                equipment,
                "Original product",
                f"상세 기록 없음 {equipment}",
                number * 10,
                K["fault"],
                "검사기",
            ]
        )
    workbook.save(source)
    workbook.close()
    store = ConfigStore(tmp_path / "profile")
    # Chart rendering has separate coverage; these tests exercise the real worker,
    # persisted corrections, aggregation and table refresh.
    monkeypatch.setattr(MainWindow, "draw_chart", lambda self: None)
    window = MainWindow(store)
    errors = []
    monkeypatch.setattr(window, "show_error", lambda error: errors.append(str(error)))
    monkeypatch.setattr(window, "notice", lambda message: None)
    loaded = load_excel(source, store.load()["column_mapping"])
    window.loaded_ready(loaded)
    window.analysis_ready(run_analysis(loaded, store.load(), window.options()))
    window.grid_test_errors = errors
    window.show_page("review")
    window.show()
    app.processEvents()
    assert window.result.metrics["review_rows"] == 3
    yield window
    if window.task is not None:
        window.task.wait(20_000)
        app.processEvents()
    window.close()


def wait_refreshed(window, previous):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        QTest.qWait(10)
        if window.result is not previous and window.task is None:
            assert not window.grid_test_errors
            return
    pytest.fail(f"Grid reanalysis did not finish: {window.grid_test_errors}")


def cell(pane, field, row=0):
    return pane.proxy.index(row, pane.model.frame.columns.get_loc(field))


def event_ids(pane):
    return [
        cell(pane, "event_id", row).data(Qt.ItemDataRole.UserRole)
        for row in range(pane.proxy.rowCount())
    ]


def row_for(window, event_id):
    return window.result.selected.loc[window.result.selected.event_id.eq(event_id)].iloc[0]


def test_requested_tabs_reach_every_page_without_manual_correction_button(grid_window):
    window = grid_window
    assert window.tabs.count() == 7
    assert [window.tabs.tabText(index).split(" (")[0] for index in range(7)] == [
        "종합현황",
        "검토필요",
        "상세분석",
        "설비별 유형순위",
        "부품별 포함 건수",
        "월별 부품 추이",
        "그래프",
    ]
    assert not hasattr(window, "correct_button")
    assert all(K["correct"] not in button.text() for button in window.findChildren(QPushButton))
    expected_columns = [
        "major",
        "middle",
        "minor",
        "raw_equipment_name",
        "raw_mid",
        "raw_small",
        "raw_description",
        "component_types",
        "combination_decision",
    ]
    for key in ("review", "detail"):
        pane = window.panes[key]
        assert pane.model.frame.columns[:9].tolist() == expected_columns
        assert all(not pane.table.isColumnHidden(index) for index in range(9))
        for field in ("raw_equipment_name", "raw_mid", "raw_small", "raw_description"):
            assert not (cell(pane, field).flags() & Qt.ItemFlag.ItemIsEditable)
        assert cell(pane, "major").flags() & Qt.ItemFlag.ItemIsEditable
        assert cell(pane, "component_types").flags() & Qt.ItemFlag.ItemIsEditable
    for key in (
        "summary",
        "review",
        "detail",
        "equipment",
        "line",
        "type",
        "cross",
        "equipment_types",
        "component",
        "component_trend",
        "chart",
        "raw",
    ):
        window.show_page(key)
        assert window.current_page_key() == key
    assert window.panes["raw"].table.editTriggers().value == 0


def test_filtered_sorted_grid_edit_saves_the_visible_event_and_retains_context(grid_window):
    window = grid_window
    pane = window.panes["review"]
    pane.search.setText("BETA")
    pane.table.sortByColumn(
        pane.model.frame.columns.get_loc("minutes"), Qt.SortOrder.AscendingOrder
    )
    assert pane.proxy.rowCount() == 1
    event_id = event_ids(pane)[0]
    previous = window.result
    source_bytes = window.loaded.path.read_bytes()
    assert pane.proxy.setData(cell(pane, "product"), "Reviewed product", Qt.ItemDataRole.EditRole)
    wait_refreshed(window, previous)
    assert window.store.override(event_id)["product"] == "Reviewed product"
    assert row_for(window, event_id)["product"] == "Reviewed product"
    other_rows = window.result.selected.loc[window.result.selected.event_id.ne(event_id)]
    assert other_rows["product"].eq("Original product").all()
    assert window.current_page_key() == "review"
    assert pane.search.text() == "BETA"
    assert pane.proxy.sortOrder() == Qt.SortOrder.AscendingOrder
    assert event_ids(pane) == [event_id]
    assert window.loaded.path.read_bytes() == source_bytes


def test_grid_minutes_recalculates_totals_and_invalidates_old_report_links(grid_window, tmp_path):
    window = grid_window
    pane = window.panes["review"]
    event_id = event_ids(pane)[0]
    old_minutes = row_for(window, event_id)["minutes"]
    previous = window.result
    window.last_reports = report_paths(tmp_path / "previous.xlsx")
    window.update_controls()
    assert window.open_button.isEnabled()
    assert pane.proxy.setData(cell(pane, "minutes"), "12.5", Qt.ItemDataRole.EditRole)
    wait_refreshed(window, previous)
    assert window.store.override(event_id)["minutes"] == "12.5"
    assert row_for(window, event_id)["minutes"] == 12.5
    assert window.result.metrics["total_minutes"] == 60 - old_minutes + 12.5
    assert window.last_reports is None
    assert not window.open_button.isEnabled()
    assert not window.pdf_button.isEnabled()


@pytest.mark.parametrize("commit", ["enter", "focus_out"])
def test_real_cell_editor_commits_before_deferred_model_replacement(grid_window, commit):
    window = grid_window
    pane = window.panes["review"]
    pane.extra_columns.setChecked(True)
    index = cell(pane, "product")
    event_id = event_ids(pane)[0]
    previous = window.result
    pane.table.setCurrentIndex(index)
    pane.table.scrollTo(index)
    pane.table.edit(index)
    editor = pane.edit_delegate.active_editor
    assert editor is not None
    editor.selectAll()
    QTest.keyClicks(editor, "Saved from editor")
    if commit == "enter":
        QTest.keyClick(editor, Qt.Key.Key_Return)
    else:
        QTest.mouseClick(pane.search, Qt.MouseButton.LeftButton)
    wait_refreshed(window, previous)
    assert window.store.override(event_id)["product"] == "Saved from editor"
    assert row_for(window, event_id)["product"] == "Saved from editor"
    assert pane.edit_delegate.active_editor is None
    assert window.current_page_key() == "review"


def test_classification_confirmation_removes_review_row_and_selects_next_event(grid_window):
    window = grid_window
    pane = window.panes["review"]
    before_ids = event_ids(pane)
    pane.table.selectRow(1)
    event_id, next_id = before_ids[1:]
    previous = window.result
    pane.open_classification_editor(cell(pane, "major", 1))
    editor = pane.classification_editor
    assert editor is not None
    for key, value in zip(("major", "middle", "minor"), ("유체·배관", "펌프", "도징펌프")):
        combo = editor.single_picker.combos[key]
        combo.setCurrentIndex(combo.findData(value))
        assert combo.currentData() == value
    editor.apply_button.click()
    wait_refreshed(window, previous)
    assert row_for(window, event_id)["status"] == K["manual"]
    assert row_for(window, event_id)["minor"] == "도징펌프"
    assert window.result.metrics["review_rows"] == 2
    assert event_id not in event_ids(pane)
    assert pane.selected_record()["event_id"] == next_id
    assert window.current_page_key() == "review"
    assert window.result.metrics["selected_rows"] == 3
    assert window.result.metrics["total_minutes"] == 60


def test_failed_grid_save_preserves_model_result_and_persisted_profile(grid_window, monkeypatch):
    window = grid_window
    pane = window.panes["review"]
    event_id = event_ids(pane)[0]
    previous = window.result
    before_value = cell(pane, "product").data()
    before_file = window.store.override_path.read_bytes()

    def fail_save(*args, **kwargs):
        raise PermissionError("Simulated correction file lock")

    monkeypatch.setattr(window.store, "update_override", fail_save)
    assert not pane.proxy.setData(cell(pane, "product"), "Unsaved value", Qt.ItemDataRole.EditRole)
    QTest.qWait(30)
    assert window.result is previous
    assert window.task is None
    assert cell(pane, "product").data() == before_value
    assert window.store.override_path.read_bytes() == before_file
    assert not window.store.override(event_id)
    assert any("Simulated correction file lock" in error for error in window.grid_test_errors)


def test_busy_analysis_prevents_grid_save(grid_window):
    window = grid_window
    pane = window.panes["review"]
    record = pane.model.frame.iloc[0].to_dict()
    before_file = window.store.override_path.read_bytes()
    window.task = object()  # A task owns the current analysis snapshot.
    try:
        window.update_controls()
        assert not (cell(pane, "product").flags() & Qt.ItemFlag.ItemIsEditable)
        assert not window._save_grid_edit(record, {"product": "Racing edit"})
        assert window.store.override_path.read_bytes() == before_file
    finally:
        window.task = None
        window.update_controls()


def test_queued_refresh_locks_out_a_second_edit_until_the_new_snapshot_arrives(grid_window):
    window = grid_window
    pane = window.panes["review"]
    event_id = event_ids(pane)[0]
    record = pane.model.frame.loc[pane.model.frame.event_id.eq(event_id)].iloc[0].to_dict()
    previous = window.result
    assert pane.proxy.setData(cell(pane, "product"), "First edit", Qt.ItemDataRole.EditRole)
    # The refresh is queued, so no event-loop turn or worker has started yet.
    assert not (cell(pane, "product").flags() & Qt.ItemFlag.ItemIsEditable)
    assert not window._save_grid_edit(record, {"minutes": "444"})
    wait_refreshed(window, previous)
    saved = window.store.override(event_id)
    assert saved["product"] == "First edit" and "minutes" not in saved
    assert cell(pane, "product").flags() & Qt.ItemFlag.ItemIsEditable


def test_saved_edit_survives_refresh_failure_and_recovers_on_reanalysis(grid_window, monkeypatch):
    import gui.main_window as window_module

    window = grid_window
    pane = window.panes["review"]
    event_id = event_ids(pane)[0]
    previous = window.result
    original_analysis = window_module.run_analysis

    def fail_refresh(*args, **kwargs):
        raise RuntimeError("Simulated analysis failure")

    monkeypatch.setattr(window_module, "run_analysis", fail_refresh)
    assert pane.proxy.setData(
        cell(pane, "product"), "Persisted before failure", Qt.ItemDataRole.EditRole
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and (not window.grid_test_errors or window.task is not None):
        QTest.qWait(10)
    assert window.task is None
    assert window.result is previous
    assert window.store.override(event_id)["product"] == "Persisted before failure"
    assert any("수정값은 저장되었으나" in error for error in window.grid_test_errors)
    assert window.analyze_button.isEnabled()
    assert not (cell(pane, "product").flags() & Qt.ItemFlag.ItemIsEditable)
    monkeypatch.setattr(window_module, "run_analysis", original_analysis)
    window.grid_test_errors.clear()
    window.analyze()
    wait_refreshed(window, previous)
    assert row_for(window, event_id)["product"] == "Persisted before failure"
    assert cell(pane, "product").flags() & Qt.ItemFlag.ItemIsEditable


def test_blank_grid_value_removes_only_that_override_and_restores_source(grid_window):
    window = grid_window
    pane = window.panes["detail"]
    window.show_page("detail")
    event_id = event_ids(pane)[0]
    window.store.update_override(event_id, {"minutes": "99", "product": "Keep product"})
    window.analysis_ready(run_analysis(window.loaded, window.store.load(), window.options()))
    window.show_page("detail")
    pane.search.setText(event_id)
    assert pane.proxy.rowCount() == 1
    original = window.loaded.frame.loc[
        window.loaded.frame["__source_row"].eq(row_for(window, event_id).source_row), "정지시간"
    ].iloc[0]
    previous = window.result
    assert pane.proxy.setData(cell(pane, "minutes"), "", Qt.ItemDataRole.EditRole)
    wait_refreshed(window, previous)
    assert window.store.override(event_id)["product"] == "Keep product"
    assert "minutes" not in window.store.override(event_id)
    assert row_for(window, event_id)["minutes"] == original
    assert pd.notna(row_for(window, event_id)["date"])
