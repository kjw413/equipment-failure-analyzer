"""Factory/team metadata stays manual while source-derived factory names stay previews."""
# ruff: noqa: E402

import os
from dataclasses import replace

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.config import ConfigStore
from core.models import LoadedData
from gui.dialogs import EquipmentNamesDialog
from gui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def factory_loaded(tmp_path):
    frame = pd.DataFrame(
        {
            "라인코드": ["C01", "C02"],
            "라인명": ["[North] Original line one", "[South] Original line two"],
            "설비코드": ["E01", "E02"],
            "설비명": ["Original equipment one", "Original equipment two"],
        }
    )
    return LoadedData(
        path=tmp_path / "factory_and_team.xlsx",
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
        file_hash="synthetic-factory-and-team",
    )


@pytest.fixture
def organization_store(tmp_path):
    store = ConfigStore(tmp_path / "profile")
    store.save_equipment_names({"E02": "Legacy equipment"}, source="equipment")
    store.save_equipment_names({"C02": "Named line"}, source="line")
    return store


@pytest.fixture
def dialog_factory(app, factory_loaded):
    dialogs = []

    def create(store, loaded=None):
        dialog = EquipmentNamesDialog(store, factory_loaded if loaded is None else loaded)
        dialogs.append(dialog)
        dialog.show()
        return dialog

    yield create
    for dialog in dialogs:
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


def test_automatic_factory_is_only_a_placeholder_and_team_is_not_inferred(
    organization_store, dialog_factory
):
    dialog = dialog_factory(organization_store)
    assert dialog.table.columnCount() == 6
    rows = rows_by_code(dialog)
    for code, factory_name in (("C01", "North"), ("C02", "South")):
        factory = dialog.table.cellWidget(rows[code], 4)
        team = dialog.table.cellWidget(rows[code], 5)
        assert factory.text() == ""
        assert factory_name in factory.placeholderText()
        assert team.text() == ""
    dialog.accept()
    saved = organization_store.read("equipment_names.json")
    assert saved["organization"]["line"] == {}
    assert saved["line_mappings"] == {"C02": "Named line"}


def test_manual_factory_and_team_flush_on_close_without_creating_a_report_name(
    organization_store, dialog_factory
):
    dialog = dialog_factory(organization_store)
    row = rows_by_code(dialog)["C01"]
    assert dialog.table.cellWidget(row, 2).text() == ""
    edit_text(dialog.table.cellWidget(row, 4), "Manual factory")
    edit_text(dialog.table.cellWidget(row, 5), "Manual team")
    assert dialog.timer.isActive()
    dialog.accept()  # Flush immediately, before the 450 ms debounce timer.
    saved = organization_store.read("equipment_names.json")
    assert saved["organization"]["line"]["C01"] == {
        "factory": "Manual factory",
        "team": "Manual team",
    }
    assert saved["line_mappings"] == {"C02": "Named line"}

    restarted = dialog_factory(ConfigStore(organization_store.root))
    row = rows_by_code(restarted)["C01"]
    assert restarted.table.cellWidget(row, 2).text() == ""
    assert restarted.table.cellWidget(row, 4).text() == "Manual factory"
    assert restarted.table.cellWidget(row, 5).text() == "Manual team"
    restarted.accept()


def test_clearing_manual_factory_restores_auto_preview_without_persisting_derived_value(
    organization_store, dialog_factory
):
    organization_store.save_equipment_names(
        {"C02": "Named line"},
        source="line",
        organization={
            "line": {"C01": {"factory": "Manual factory", "team": "Keep team"}},
            "equipment": {},
        },
    )
    dialog = dialog_factory(organization_store)
    factory = dialog.table.cellWidget(rows_by_code(dialog)["C01"], 4)
    assert factory.text() == "Manual factory"
    factory.selectAll()
    QTest.keyClick(factory, Qt.Key.Key_Backspace)
    assert factory.text() == ""
    assert "North" in factory.placeholderText()
    dialog.accept()
    entry = organization_store.read("equipment_names.json")["organization"]["line"]["C01"]
    assert not entry.get("factory")
    assert entry["team"] == "Keep team"

    restarted = dialog_factory(ConfigStore(organization_store.root))
    row = rows_by_code(restarted)["C01"]
    assert restarted.table.cellWidget(row, 4).text() == ""
    assert "North" in restarted.table.cellWidget(row, 4).placeholderText()
    assert restarted.table.cellWidget(row, 5).text() == "Keep team"
    restarted.accept()
    assert not organization_store.read("equipment_names.json")["organization"]["line"]["C01"].get(
        "factory"
    )


def test_ambiguous_factories_for_one_code_do_not_show_an_arbitrary_factory(
    organization_store, factory_loaded, dialog_factory
):
    conflict = factory_loaded.frame.iloc[[0]].copy()
    conflict["라인명"] = "[South] Another name for the same line"
    loaded = replace(
        factory_loaded, frame=pd.concat([factory_loaded.frame, conflict], ignore_index=True)
    )
    dialog = dialog_factory(organization_store, loaded)
    rows = rows_by_code(dialog)
    factory = dialog.table.cellWidget(rows["C01"], 4)
    assert factory.text() == ""
    assert "North" not in factory.placeholderText()
    assert "South" not in factory.placeholderText()
    assert "South" in dialog.table.cellWidget(rows["C02"], 4).placeholderText()
    assert dialog.table.cellWidget(rows["C01"], 5).text() == ""
    dialog.accept()
    assert organization_store.read("equipment_names.json")["organization"]["line"] == {}


def test_organization_only_codes_and_other_source_metadata_survive_source_switches(
    organization_store, dialog_factory
):
    organization_store.save_equipment_names(
        {"C02": "Named line"},
        source="line",
        organization={
            "line": {"UNKNOWN": {"factory": "Stored factory", "team": "Stored team"}},
            "equipment": {"E99": {"factory": "Legacy factory", "team": "Legacy team"}},
        },
    )
    dialog = dialog_factory(organization_store)
    rows = rows_by_code(dialog)
    assert "UNKNOWN" in rows
    assert dialog.table.cellWidget(rows["UNKNOWN"], 2).text() == ""
    assert dialog.table.cellWidget(rows["UNKNOWN"], 4).text() == "Stored factory"
    assert dialog.table.cellWidget(rows["UNKNOWN"], 5).text() == "Stored team"
    edit_text(dialog.table.cellWidget(rows["C01"], 4), "Line factory")
    edit_text(dialog.table.cellWidget(rows["C01"], 5), "Line team")
    select_data(dialog.source_combo, "equipment")
    saved = organization_store.read("equipment_names.json")
    assert saved["organization"]["line"]["C01"] == {"factory": "Line factory", "team": "Line team"}
    assert saved["organization"]["line"]["UNKNOWN"] == {
        "factory": "Stored factory",
        "team": "Stored team",
    }
    assert saved["organization"]["equipment"]["E99"] == {
        "factory": "Legacy factory",
        "team": "Legacy team",
    }
    rows = rows_by_code(dialog)
    assert "E99" in rows
    assert dialog.table.cellWidget(rows["E99"], 2).text() == ""
    edit_text(dialog.table.cellWidget(rows["E01"], 5), "Equipment team")
    select_data(dialog.source_combo, "line")
    assert dialog.table.cellWidget(rows_by_code(dialog)["C01"], 4).text() == "Line factory"
    dialog.accept()

    restarted = dialog_factory(ConfigStore(organization_store.root))
    assert "UNKNOWN" in rows_by_code(restarted)
    assert restarted.table.cellWidget(rows_by_code(restarted)["UNKNOWN"], 5).text() == "Stored team"
    restarted.accept()
    saved = organization_store.read("equipment_names.json")
    assert saved["organization"]["equipment"]["E01"]["team"] == "Equipment team"
    assert not saved["organization"]["equipment"]["E01"].get("factory")
    assert saved["organization"]["equipment"]["E99"] == {
        "factory": "Legacy factory",
        "team": "Legacy team",
    }
    assert saved["line_mappings"] == {"C02": "Named line"}
    assert saved["mappings"] == {"E02": "Legacy equipment"}


def test_main_window_exposes_factory_and_team_analysis_bases(app, tmp_path):
    window = MainWindow(ConfigStore(tmp_path / "window-profile"))
    try:
        for basis in ("factory", "team"):
            select_data(window.basis, basis)
            assert window.options().equipment_basis == basis
    finally:
        window.close()


def test_renaming_new_organization_only_code_replaces_its_saved_identity(
    organization_store, dialog_factory
):
    dialog = dialog_factory(organization_store)
    dialog.add_empty()
    row = dialog.table.rowCount() - 1
    key = dialog.table.cellWidget(row, 0)
    edit_text(key, "CNEW1")
    edit_text(dialog.table.cellWidget(row, 4), "New factory")
    edit_text(dialog.table.cellWidget(row, 5), "New team")
    assert dialog.table.cellWidget(row, 2).text() == ""
    assert dialog.save_silently()
    metadata = {"factory": "New factory", "team": "New team"}
    assert organization_store.read("equipment_names.json")["organization"]["line"] == {
        "CNEW1": metadata
    }
    assert not key.isReadOnly()
    edit_text(key, "CNEW2")
    assert dialog.timer.isActive()
    assert dialog.save_silently()
    assert organization_store.read("equipment_names.json")["organization"]["line"] == {
        "CNEW2": metadata
    }
    dialog.accept()

    restarted = dialog_factory(ConfigStore(organization_store.root))
    rows = rows_by_code(restarted)
    assert "CNEW1" not in rows
    assert "CNEW2" in rows
    assert restarted.table.cellWidget(rows["CNEW2"], 2).text() == ""
    assert restarted.table.cellWidget(rows["CNEW2"], 4).text() == "New factory"
    assert restarted.table.cellWidget(rows["CNEW2"], 5).text() == "New team"
    restarted.accept()


def test_deleting_renamed_new_row_before_autosave_removes_old_and_new_metadata(
    organization_store, dialog_factory
):
    dialog = dialog_factory(organization_store)
    dialog.add_empty()
    row = dialog.table.rowCount() - 1
    key = dialog.table.cellWidget(row, 0)
    edit_text(key, "CNEW1")
    edit_text(dialog.table.cellWidget(row, 4), "New factory")
    edit_text(dialog.table.cellWidget(row, 5), "New team")
    assert dialog.save_silently()
    assert "CNEW1" in organization_store.read("equipment_names.json")["organization"]["line"]
    edit_text(key, "CNEW2")
    assert dialog.timer.isActive()
    dialog.table.clearSelection()
    dialog.table.selectRow(row)
    dialog.delete_rows()
    assert dialog.save_silently()
    organization = organization_store.read("equipment_names.json")["organization"]["line"]
    assert "CNEW1" not in organization
    assert "CNEW2" not in organization
    dialog.accept()

    restarted = dialog_factory(ConfigStore(organization_store.root))
    rows = rows_by_code(restarted)
    assert "CNEW1" not in rows
    assert "CNEW2" not in rows
    restarted.accept()
