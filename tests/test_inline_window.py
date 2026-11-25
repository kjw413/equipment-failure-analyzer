"""Persisted grid edits refresh analysis without losing the operator's place."""
# ruff: noqa: E402

import csv
import os
import time
from io import StringIO

import pandas as pd
import pytest
from openpyxl import Workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QPushButton

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


def test_review_corner_copies_the_actual_grid_without_saving_corrections(app, grid_window):
    window = grid_window
    pane = window.panes["review"]
    before = window.store.override_path.read_bytes()
    previous = window.result
    pane.table.selectRow(1)
    corner = pane.table.findChild(QAbstractButton)
    assert corner.accessibleName() == "표 전체 복사"
    QTest.mouseClick(corner, Qt.MouseButton.LeftButton)
    copied = list(csv.reader(StringIO(app.clipboard().text()), delimiter="\t"))
    assert len(copied) == pane.proxy.rowCount() + 1 == 4
    visible = [
        column
        for column in range(pane.proxy.columnCount())
        if not pane.table.isColumnHidden(column)
    ]
    assert all(len(row) == len(visible) for row in copied)
    assert copied[0] == [
        pane.proxy.headerData(column, Qt.Orientation.Horizontal).removesuffix(" · 수정")
        for column in visible
    ]
    assert {"고장 분야", "상세설비·모듈", "부품군", "세부 부품", "고장 현상", "조치 내역"} <= set(
        copied[0]
    )
    assert {"상세 기록 없음 ALPHA", "상세 기록 없음 BETA", "상세 기록 없음 GAMMA"} <= {
        value for row in copied[1:] for value in row
    }
    assert window.store.override_path.read_bytes() == before
    assert window.result is previous and window.task is None


def test_requested_tabs_reach_every_page_without_manual_correction_button(grid_window):
    window = grid_window
    assert [window.tabs.tabText(index).split(" (")[0] for index in range(window.tabs.count())] == [
        "종합현황",
        "검토필요",
        "고장이력",
        "상세분석",
    ]
    assert not hasattr(window, "correct_button")
    assert all(K["correct"] not in button.text() for button in window.findChildren(QPushButton))
    expected_columns = [
        "major",
        "detail_equipment",
        "part_group",
        "middle",
        "minor",
        "repair_actions",
        "classification_missing_fields",
        "raw_equipment_name",
        "raw_mid",
        "raw_small",
        "raw_description",
        "component_types",
        "combination_decision",
    ]
    for key in ("review", "detail"):
        pane = window.panes[key]
        assert pane.model.frame.columns[: len(expected_columns)].tolist() == expected_columns
        assert all(not pane.table.isColumnHidden(index) for index in range(len(expected_columns)))
        for field in ("raw_equipment_name", "raw_mid", "raw_small", "raw_description"):
            assert not (cell(pane, field).flags() & Qt.ItemFlag.ItemIsEditable)
        assert cell(pane, "major").flags() & Qt.ItemFlag.ItemIsEditable
        assert cell(pane, "component_types").flags() & Qt.ItemFlag.ItemIsEditable
    for key in (
        "summary",
        "review",
        "detail",
        "fault_detail",
        "equipment",
        "line",
        "detailed_equipment",
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


def test_analysis_selectors_switch_to_graph_and_back_and_gate_product_table(grid_window):
    window = grid_window
    navigation = window.navigation
    window.tabs.setCurrentWidget(navigation.analysis)
    navigation.analysis_choice.setCurrentIndex(navigation.analysis_choice.findData("line"))
    assert window.current_page_key() == "line"
    navigation.chart_button.click()
    assert window.current_page_key() == "chart"
    assert window.chart_choice.currentData() == "line"
    navigation.chart_button.click()
    assert window.current_page_key() == "line"
    navigation.analysis_choice.setCurrentIndex(navigation.analysis_choice.findData("parts"))
    navigation.part_choice.setCurrentIndex(navigation.part_choice.findData("component_trend"))
    assert window.current_page_key() == "component_trend"
    window.show_page("cross")
    assert window.current_page_key() == "cross"
    window.loaded_ready(window.loaded)
    assert navigation.analysis_choice.findData("cross") == -1


def test_review_original_row_follows_filtered_selection(grid_window):
    window = grid_window
    pane = window.panes["review"]
    raw = window.panes["raw"]
    assert not pane.original_button.isEnabled()
    raw.search.setText("ALPHA")
    pane.search.setText("GAMMA")
    pane.table.selectRow(0)
    assert pane.original_button.isEnabled()
    pane.original_button.click()
    assert window.current_page_key() == "raw"
    assert raw.search.text() == ""
    assert raw.selected_record()["설비명"] == "GAMMA"
    assert pane.search.text() == "GAMMA"


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


def test_classification_waits_for_standardize_before_removing_review_row(grid_window):
    window = grid_window
    pane = window.panes["review"]
    before_ids = event_ids(pane)
    pane.table.selectRow(1)
    event_id, next_id = before_ids[1:]
    previous = window.result
    pane.open_classification_editor(cell(pane, "major", 1))
    editor = pane.classification_editor
    assert editor is not None
    for key, value in zip(
        ("major", "detail_equipment", "middle", "minor"),
        ("유체·배관", "상세설비 미상", "메카니칼씰", "손상·파손"),
    ):
        combo = editor.single_picker.combos[key]
        combo.setCurrentIndex(combo.findData(value))
        assert combo.currentData() == value
    editor.apply_button.click()
    QTest.qWait(20)
    assert window.result is previous and window.task is None
    assert not window.store.override(event_id)
    assert event_ids(pane) == before_ids
    assert cell(pane, "middle", 1).data() == "메카니칼씰"
    assert cell(pane, "status", 1).data() == "확정 대기"
    assert window.analyze_button.text() == "분류 1건 적용 및 재분석"
    assert window.result.metrics["review_rows"] == 3
    QTest.mouseClick(window.analyze_button, Qt.MouseButton.LeftButton)
    wait_refreshed(window, previous)
    assert row_for(window, event_id)["status"] == K["manual"]
    assert row_for(window, event_id)["middle"] == "메카니칼씰"
    assert row_for(window, event_id)["minor"] == "손상·파손"
    assert window.result.metrics["review_rows"] == 2
    assert event_id not in event_ids(pane)
    assert pane.selected_record()["event_id"] == next_id
    assert window.current_page_key() == "review"
    assert window.result.metrics["selected_rows"] == 3
    assert window.result.metrics["total_minutes"] == 60
    assert not window._pending_classifications


def test_multiple_pending_choices_survive_scalar_refresh_and_apply_as_one_batch(grid_window):
    window = grid_window
    pane = window.panes["review"]
    before = window.store.override_path.read_bytes()
    original = window.result
    ids = event_ids(pane)[:2]
    categories = [
        {
            "detail_equipment": "상세설비 미상",
            "major": "기계",
            "middle": "베어링(종류 미상)",
            "minor": "손상·파손",
        },
        {
            "detail_equipment": "상세설비 미상",
            "major": "유체·배관",
            "middle": "메카니칼씰",
            "minor": "누설",
        },
    ]
    for row, category in enumerate(categories):
        pane.open_classification_editor(cell(pane, "major", row))
        editor = pane.classification_editor
        editor.single_picker.set_value(category)
        editor.apply_button.click()
        QTest.qWait(10)
    assert window.store.override_path.read_bytes() == before
    assert window.result is original and window.result.metrics["review_rows"] == 3
    assert len(window._pending_classifications) == 2
    assert window.analyze_button.text() == "분류 2건 적용 및 재분석"
    # Reopening the dialog restores the staged choice, without selecting a candidate automatically.
    editor = pane.open_classification_editor(cell(pane, "major", 0))
    assert editor.single_picker.value() == categories[0]
    editor.close()
    assert pane.proxy.setData(cell(pane, "minutes", 0), "17")
    wait_refreshed(window, original)
    assert len(window._pending_classifications) == 2
    assert pane.model.frame.set_index("event_id").loc[ids[0], "middle"] == "베어링(종류 미상)"
    assert "major" not in window.store.override(ids[0])
    previous = window.result
    pane.search.setText("ALPHA")
    QTest.mouseClick(window.analyze_button, Qt.MouseButton.LeftButton)
    wait_refreshed(window, previous)
    assert all(row_for(window, event_id)["status"] == K["manual"] for event_id in ids)
    assert window.store.override(ids[0])["minutes"] == "17"
    assert window.result.metrics["review_rows"] == 1
    assert not window._pending_classifications


def test_pending_classification_is_discarded_after_reopening_the_program(grid_window):
    window = grid_window
    pane = window.panes["review"]
    category = {
        "detail_equipment": "상세설비 미상",
        "major": "기계",
        "middle": "베어링(종류 미상)",
        "minor": "손상·파손",
    }
    editor = pane.open_classification_editor(cell(pane, "major", 0))
    editor.single_picker.set_value(category)
    editor.apply_button.click()
    QTest.qWait(10)
    event_id = event_ids(pane)[0]
    restored = MainWindow(ConfigStore(window.store.root))
    try:
        restored.loaded_ready(window.loaded)
        restored.analysis_ready(
            run_analysis(window.loaded, restored.store.load(), restored.options())
        )
        record = restored.panes["review"].model.frame.set_index("event_id").loc[event_id]
        assert all(not record[key] for key in category)
        assert record["status"] != "확정 대기"
        assert restored.analyze_button.text() == "분석 실행"
        assert restored.result.metrics["review_rows"] == 3
        assert not restored.store.override(event_id)
    finally:
        restored.close()


def test_completed_grid_cascade_is_staged_until_standardize(grid_window):
    window = grid_window
    pane = window.panes["review"]
    event_id = event_ids(pane)[0]
    previous = window.result
    for field, value in zip(
        ("major", "detail_equipment", "middle", "minor"),
        ("기계", "상세설비 미상", "베어링(종류 미상)", "누설"),
    ):
        assert pane.proxy.setData(cell(pane, field, 0), value)
    QTest.qWait(10)
    assert window.result is previous and window.task is None
    assert not window.store.override(event_id)
    assert window._pending_classifications[event_id]["minor"] == "누설"
    assert pane.model.frame.set_index("event_id").loc[event_id, "status"] == "확정 대기"
    QTest.mouseClick(window.analyze_button, Qt.MouseButton.LeftButton)
    wait_refreshed(window, previous)
    assert row_for(window, event_id)["status"] == K["manual"]
    assert row_for(window, event_id)["minor"] == "누설"


def test_fast_cell_entry_advances_without_io_or_rebuilding_the_grid(grid_window, monkeypatch):
    window = grid_window
    pane = window.panes["review"]
    original = window.result
    model = pane.model
    before_ids = event_ids(pane)
    event_id = before_ids[0]
    pane.model.frame.at[
        pane.proxy.mapToSource(cell(pane, "major", 0)).row(), "classification_mode"
    ] = "ambiguous"

    def forbidden(*args, **kwargs):
        raise AssertionError("per-cell I/O or full grid rebuild")

    monkeypatch.setattr(window.store, "read", forbidden)
    monkeypatch.setattr(pane, "set_frame", forbidden)
    monkeypatch.setattr(window.panes["detail"], "set_frame", forbidden)
    monkeypatch.setattr(window, "_grid_columns", forbidden)
    pane.table.setCurrentIndex(cell(pane, "major", 0))
    pane.table.edit(cell(pane, "major", 0))
    for field, value in zip(
        ("major", "detail_equipment", "middle", "minor"),
        ("기계", "상세설비 미상", "베어링(종류 미상)", "누설"),
    ):
        assert pane.table.currentIndex().column() == pane.model.frame.columns.get_loc(field)
        editor = pane.edit_delegate.active_editor
        assert isinstance(editor, QComboBox)
        chosen = editor.findData(value)
        assert chosen > 0
        editor.setCurrentIndex(chosen)
        editor.activated.emit(chosen)
        QTest.qWait(15)
    assert pane.model is model
    assert window.result is original and window.task is None
    assert window._pending_classifications[event_id]["minor"] == "누설"
    assert pane.table.currentIndex() == cell(pane, "major", 1)
    assert event_ids(pane) == before_ids
    assert not window.grid_test_errors
    assert not (window.store.config_dir / "classification_drafts.json").exists()
    pane.cancel_editing()


def test_row_preview_retains_other_incomplete_choices_and_cancels_in_place(grid_window):
    window = grid_window
    pane = window.panes["review"]
    original_model = pane.model
    ids = event_ids(pane)
    assert pane.proxy.setData(cell(pane, "major", 1), "유체·배관")
    for field, value in zip(
        ("major", "detail_equipment", "middle", "minor"),
        ("기계", "상세설비 미상", "베어링(종류 미상)", "손상·파손"),
    ):
        assert pane.proxy.setData(cell(pane, field, 0), value)
    QTest.qWait(10)
    assert pane.model is original_model
    assert cell(pane, "major", 1).data() == "유체·배관"
    assert cell(pane, "middle", 1).data().endswith("선택")
    assert window._pending_classifications[ids[0]]["minor"] == "손상·파손"
    window._pending_classifications.pop(ids[0])
    window._queue_pending_row(ids[0])
    QTest.qWait(10)
    assert pane.model is original_model
    assert not pane.model.frame.set_index("event_id").loc[ids[0], "major"]
    assert cell(pane, "major", 1).data() == "유체·배관"


def test_failed_batch_save_keeps_pending_choices_and_confirmed_analysis(grid_window, monkeypatch):
    window = grid_window
    pane = window.panes["review"]
    editor = pane.open_classification_editor(cell(pane, "major", 0))
    editor.single_picker.set_value(
        {
            "detail_equipment": "상세설비 미상",
            "major": "기계",
            "middle": "베어링(종류 미상)",
            "minor": "손상·파손",
        }
    )
    editor.apply_button.click()
    QTest.qWait(10)
    previous = window.result
    before = window.store.override_path.read_bytes()
    drafts = window._pending_classifications

    def fail(*args):
        raise PermissionError("batch locked")

    monkeypatch.setattr(window.store, "apply_classifications", fail)
    QTest.mouseClick(window.analyze_button, Qt.MouseButton.LeftButton)
    assert window.result is previous and window.task is None
    assert window.store.override_path.read_bytes() == before
    assert window._pending_classifications == drafts
    assert window.analyze_button.text() == "분류 1건 적용 및 재분석"
    assert any("batch locked" in error for error in window.grid_test_errors)


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


def test_combination_decision_distinguishes_automatic_combinations():
    frame = pd.DataFrame(
        {
            "classification_mode": ["multiple", "multiple", "multiple", "single"]
            + ["unclassified"] * 2,
            "status": [K["auto"], K["manual_multi"], K["review"], K["auto"]]
            + [K["code_missing"], K["rule_unmatched"]],
        }
    )
    decisions = MainWindow.classification_frame(frame)["combination_decision"].tolist()
    assert decisions == [
        "최종 미확정",
        "최종 미확정",
        "최종 미확정",
        "규칙분류",
        K["code_missing"],
        K["rule_unmatched"],
    ]
