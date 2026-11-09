"""Line/equipment naming choices and group previews survive GUI editing and restart."""
# ruff: noqa: E402

import os
from dataclasses import replace

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import ConfigStore
from core.models import LoadedData
from gui.dialogs import EquipmentNamesDialog
from gui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def loaded_lines(tmp_path):
    frame = pd.DataFrame(
        {
            "라인코드": ["C01", "C02"],
            "라인명": ["Original line one", "Original line two"],
            "설비코드": ["E01", "E02"],
            "설비명": ["Original equipment one", "Original equipment two"],
        }
    )
    return LoadedData(
        path=tmp_path / "line_and_equipment.xlsx",
        sheet="Events",
        header_row=1,
        frame=frame,
        headers=list(frame.columns),
        mapping={
            "line_id": "라인코드",
            "line_name": "라인명",
            "equipment_id": "설비코드",
            "equipment_name": "설비명",
        },
        profile="synthetic",
        file_hash="synthetic-line-and-equipment",
    )


@pytest.fixture
def name_store(tmp_path):
    store = ConfigStore(tmp_path / "profile")
    store.save_equipment_names({"E01": "Legacy#1", "E02": "Legacy#2"}, source="equipment")
    store.save_equipment_names({"C01": "A#1", "C02": "A#2"}, source="line")
    return store


@pytest.fixture
def dialog_factory(app, loaded_lines):
    dialogs = []

    def create(store, loaded=None):
        dialog = EquipmentNamesDialog(store, loaded_lines if loaded is None else loaded)
        dialogs.append(dialog)
        dialog.show()
        return dialog

    yield create
    for dialog in dialogs:
        # Do not flush invalid edits if an assertion fails during validation tests.
        dialog.timer.stop()
        dialog.hide()
        dialog.deleteLater()
    app.processEvents()


def rows_by_code(dialog):
    return {dialog.table.cellWidget(row, 0).text(): row for row in range(dialog.table.rowCount())}


def edit_text(edit, value):
    edit.selectAll()
    QTest.keyClicks(edit, value)


def select_data(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_default_line_source_lists_line_codes_and_original_line_names(tmp_path, dialog_factory):
    dialog = dialog_factory(ConfigStore(tmp_path / "default-profile"))
    assert dialog.source == dialog.source_combo.currentData() == "line"
    assert dialog.table.columnCount() == 6
    rows = rows_by_code(dialog)
    assert set(rows) == {"C01", "C02"}
    assert dialog.table.item(rows["C01"], 1).text() == "Original line one"
    assert dialog.table.item(rows["C02"], 1).text() == "Original line two"
    dialog.accept()


def test_switch_flushes_pending_edits_and_keeps_both_source_maps(name_store, dialog_factory):
    dialog = dialog_factory(name_store)
    edit_text(dialog.table.cellWidget(rows_by_code(dialog)["C01"], 2), "A#7")
    assert dialog.timer.isActive()
    # Switch immediately, before the 450 ms autosave timer can run.
    select_data(dialog.source_combo, "equipment")
    assert dialog.source == "equipment"
    assert set(rows_by_code(dialog)) == {"E01", "E02"}
    saved = name_store.read("equipment_names.json")
    assert saved["line_mappings"] == {"C01": "A#7", "C02": "A#2"}
    assert saved["mappings"] == {"E01": "Legacy#1", "E02": "Legacy#2"}
    edit_text(dialog.table.cellWidget(rows_by_code(dialog)["E01"], 2), "Legacy#8")
    select_data(dialog.source_combo, "line")
    assert dialog.table.cellWidget(rows_by_code(dialog)["C01"], 2).text() == "A#7"
    select_data(dialog.source_combo, "equipment")
    dialog.accept()

    restarted = dialog_factory(ConfigStore(name_store.root))
    assert restarted.source == restarted.source_combo.currentData() == "equipment"
    assert restarted.table.cellWidget(rows_by_code(restarted)["E01"], 2).text() == "Legacy#8"
    select_data(restarted.source_combo, "line")
    assert restarted.table.cellWidget(rows_by_code(restarted)["C01"], 2).text() == "A#7"
    assert name_store.read("equipment_names.json")["mappings"] == {
        "E01": "Legacy#8",
        "E02": "Legacy#2",
    }
    restarted.accept()


def test_group_preview_and_explicit_override_survive_restart(name_store, dialog_factory):
    name_store.save_equipment_names(
        name_store.read("equipment_names.json")["line_mappings"],
        source="line",
        grouping={
            "mode": "prefix",
            "separator": "#",
            "overrides": {"Unloaded#1": "Preserved group"},
        },
    )
    dialog = dialog_factory(name_store)
    rows = rows_by_code(dialog)
    assert [dialog.table.cellWidget(rows[code], 3).text() for code in ("C01", "C02")] == ["A", "A"]
    edit_text(dialog.table.cellWidget(rows["C01"], 3), "Shared group")
    dialog.accept()
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {
        "A#1": "Shared group",
        "Unloaded#1": "Preserved group",
    }

    restarted = dialog_factory(ConfigStore(name_store.root))
    rows = rows_by_code(restarted)
    assert restarted.table.cellWidget(rows["C01"], 3).text() == "Shared group"
    assert restarted.table.cellWidget(rows["C02"], 3).text() == "A"
    group_edit = restarted.table.cellWidget(rows["C01"], 3)
    group_edit.selectAll()
    QTest.keyClick(group_edit, Qt.Key.Key_Backspace)
    restarted.accept()
    assert group_edit.text() == "A"
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {
        "Unloaded#1": "Preserved group"
    }


def test_group_separator_and_mode_changes_are_saved_and_refresh_preview(name_store, dialog_factory):
    dialog = dialog_factory(name_store)
    rows = rows_by_code(dialog)
    edit_text(dialog.table.cellWidget(rows["C01"], 2), "Area:1")
    edit_text(dialog.table.cellWidget(rows["C02"], 2), "Area:2")
    edit_text(dialog.group_separator, ":")
    assert [dialog.table.cellWidget(rows[code], 3).text() for code in ("C01", "C02")] == [
        "Area",
        "Area",
    ]
    dialog.accept()

    restarted = dialog_factory(ConfigStore(name_store.root))
    assert restarted.group_mode.currentData() == "prefix"
    assert restarted.group_separator.text() == ":"
    select_data(restarted.group_mode, "none")
    assert restarted.table.cellWidget(rows_by_code(restarted)["C01"], 3).text() == "Area:1"
    restarted.accept()
    assert name_store.read("equipment_names.json")["grouping"] == {
        "mode": "none",
        "separator": ":",
        "overrides": {},
    }

    final = dialog_factory(ConfigStore(name_store.root))
    assert final.group_mode.currentData() == "none"
    assert final.group_separator.text() == ":"
    assert final.table.cellWidget(rows_by_code(final)["C02"], 3).text() == "Area:2"
    final.accept()


def test_invalid_mapping_blocks_source_switch_and_preserves_saved_data(
    name_store, dialog_factory, monkeypatch
):
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    before = name_store.read("equipment_names.json")
    dialog = dialog_factory(name_store)
    edit_text(dialog.table.cellWidget(rows_by_code(dialog)["C02"], 2), "A#1")
    select_data(dialog.source_combo, "equipment")
    assert dialog.source == dialog.source_combo.currentData() == "line"
    assert set(rows_by_code(dialog)) == {"C01", "C02"}
    assert dialog.table.cellWidget(rows_by_code(dialog)["C02"], 2).text() == "A#1"
    assert name_store.read("equipment_names.json") == before
    edit_text(dialog.table.cellWidget(rows_by_code(dialog)["C02"], 2), "A#2")
    dialog.accept()


def test_main_window_exposes_group_analysis_basis(app, tmp_path):
    window = MainWindow(ConfigStore(tmp_path / "window-profile"))
    try:
        values = {window.basis.itemData(index) for index in range(window.basis.count())}
        assert {"mapped", "group", "target", "registered", "family"} <= values
        select_data(window.basis, "group")
        assert window.options().equipment_basis == "group"
    finally:
        window.close()


def test_missing_line_columns_keep_preferred_source_and_line_mapping(
    name_store, loaded_lines, dialog_factory
):
    frame = loaded_lines.frame.drop(columns=["라인코드", "라인명"])
    no_lines = replace(
        loaded_lines,
        frame=frame,
        headers=list(frame.columns),
        mapping={
            key: value for key, value in loaded_lines.mapping.items() if not key.startswith("line_")
        },
    )
    original = name_store.read("equipment_names.json")
    dialog = dialog_factory(name_store, no_lines)
    assert dialog.source == dialog.source_combo.currentData() == "line"
    assert set(rows_by_code(dialog)) == {"C01", "C02"}
    assert dialog.table.cellWidget(rows_by_code(dialog)["C01"], 2).text() == "A#1"
    assert all(word in dialog.source_note.text() for word in ("라인", "분석", "설비"))
    dialog.accept()
    assert name_store.read("equipment_names.json") == original

    with_lines = dialog_factory(ConfigStore(name_store.root))
    assert with_lines.source == with_lines.source_combo.currentData() == "line"
    assert set(rows_by_code(with_lines)) == {"C01", "C02"}
    with_lines.accept()

    explicit = dialog_factory(ConfigStore(name_store.root), no_lines)
    select_data(explicit.source_combo, "equipment")
    assert explicit.source == explicit.source_combo.currentData() == "equipment"
    assert set(rows_by_code(explicit)) == {"E01", "E02"}
    explicit.accept()
    saved = name_store.read("equipment_names.json")
    assert saved["source"] == "equipment"
    assert saved["line_mappings"] == original["line_mappings"]
    assert saved["mappings"] == original["mappings"]


@pytest.mark.parametrize("rule_change", ["mode", "separator"])
def test_cleared_group_override_stays_cleared_when_rule_changes_before_autosave(
    name_store, dialog_factory, rule_change
):
    name_store.save_equipment_names(
        name_store.read("equipment_names.json")["line_mappings"],
        source="line",
        grouping={"mode": "prefix", "separator": "#", "overrides": {"A#1": "Manual"}},
    )
    dialog = dialog_factory(name_store)
    group = dialog.table.cellWidget(rows_by_code(dialog)["C01"], 3)
    assert group.text() == "Manual"
    group.selectAll()
    QTest.keyClick(group, Qt.Key.Key_Backspace)
    assert dialog.timer.isActive()
    if rule_change == "mode":
        select_data(dialog.group_mode, "none")
    else:
        edit_text(dialog.group_separator, ":")
    assert group.text() == "A#1"
    dialog.accept()
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {}

    restarted = dialog_factory(ConfigStore(name_store.root))
    assert restarted.table.cellWidget(rows_by_code(restarted)["C01"], 3).text() == "A#1"
    restarted.accept()
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {}


@pytest.mark.parametrize("rule_change", ["mode", "separator"])
def test_explicit_group_equal_to_auto_is_saved_and_survives_later_rule_change(
    name_store, dialog_factory, rule_change
):
    dialog = dialog_factory(name_store)
    group = dialog.table.cellWidget(rows_by_code(dialog)["C01"], 3)
    assert group.text() == "A"
    edit_text(group, "A")
    assert dialog.save_silently()
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {"A#1": "A"}
    if rule_change == "mode":
        select_data(dialog.group_mode, "none")
    else:
        edit_text(dialog.group_separator, ":")
    assert group.text() == "A"
    dialog.accept()
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {"A#1": "A"}

    restarted = dialog_factory(ConfigStore(name_store.root))
    assert restarted.table.cellWidget(rows_by_code(restarted)["C01"], 3).text() == "A"
    restarted.accept()
    assert name_store.read("equipment_names.json")["grouping"]["overrides"] == {"A#1": "A"}
