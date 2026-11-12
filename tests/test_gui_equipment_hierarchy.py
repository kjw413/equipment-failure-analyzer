"""Four-level manual choices keep equipment and its component separate."""
# ruff: noqa: E402

import json
import os

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.failure_modes import UNKNOWN_PART
from core.fault_components import CATEGORY_FIELDS
from core.models import UserError
from gui.category_index import ClassificationPathIndex
from gui.classification_picker import CandidateListPicker, ClassificationPicker
from gui.dialogs import CorrectionDialog
from gui.main_window import MainWindow
from gui.widgets import TablePane

PATHS = [
    ("전기·제어", "충전기", "모터", "과열"),
    ("전기·제어", "충전기", "모터", "소손·단락"),
    ("전기·제어", "검사기", "센서", "검출불량"),
    ("전기·제어", "상세설비 미상", "모터", "과열"),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def category(path):
    return dict(zip(CATEGORY_FIELDS, path))


def test_equipment_change_preserves_part_and_symptom(app):
    picker = ClassificationPicker(PATHS, category(PATHS[0]))
    combo = picker.combos["detail_equipment"]
    combo.setCurrentIndex(combo.findData("검사기"))
    assert picker.value() == {
        "major": "전기·제어",
        "detail_equipment": "검사기",
        "middle": "모터",
        "minor": "과열",
    }
    assert picker.validate_path()["detail_equipment"] == "검사기"
    picker.group_combo.setCurrentIndex(0)
    parts = picker.combos["middle"]
    assert {parts.itemData(i) for i in range(1, parts.count())} == {"센서", "모터"}
    picker.set_value({**category(PATHS[0]), "detail_equipment": "검사기"})
    picker.close()


def test_equipment_can_be_chosen_before_major_and_survives_major_changes(app):
    paths = [*PATHS, ("기계", "충전기", "베어링", "마모")]
    picker = ClassificationPicker(paths)
    equipment = picker.combos["detail_equipment"]
    assert equipment.isEnabled()
    equipment.setCurrentIndex(equipment.findData("검사기"))
    assert picker.value() == {"major": "", "detail_equipment": "검사기", "middle": "", "minor": ""}
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("전기·제어"))
    assert picker.value()["detail_equipment"] == "검사기"
    picker.set_value({**category(PATHS[0]), "detail_equipment": "검사기"})
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("기계"))
    assert picker.value() == {
        "major": "기계",
        "detail_equipment": "검사기",
        "middle": "모터",
        "minor": "과열",
    }
    picker.close()


def test_part_and_symptom_can_be_chosen_before_equipment(app):
    picker = ClassificationPicker(PATHS)
    picker.set_value({"major": "전기·제어", "middle": "모터", "minor": "과열"})
    assert picker.combos["middle"].isEnabled() and picker.combos["minor"].isEnabled()
    assert picker.value()["detail_equipment"] == ""
    with pytest.raises(UserError, match="모두 선택"):
        picker.validate_path()
    picker.combos["detail_equipment"].setCurrentIndex(
        picker.combos["detail_equipment"].findData("검사기")
    )
    assert picker.validate_path() == {
        "major": "전기·제어",
        "detail_equipment": "검사기",
        "middle": "모터",
        "minor": "과열",
    }
    picker.close()


@pytest.mark.parametrize(
    "order",
    [
        ("detail_equipment", "major", "middle", "minor"),
        ("major", "middle", "minor", "detail_equipment"),
        ("middle", "minor", "detail_equipment", "major"),
        ("middle", "major", "minor", "detail_equipment"),
    ],
)
def test_grid_accepts_independent_equipment_order_and_saves_once(app, order):
    record = {
        "event_id": "independent",
        "record_id": "independent",
        **dict.fromkeys(CATEGORY_FIELDS, ""),
        "classification_mode": "pending",
        "status": "검토필요",
    }
    pane = TablePane(sort_policy="source")
    pane.set_frame(pd.DataFrame([record]))
    saved = []
    pane.configure_editing(
        PATHS, lambda row, patch: saved.append(patch) or True, defer_classification=True
    )
    values = {**category(PATHS[0]), "detail_equipment": "검사기"}
    for position, field in enumerate(order):
        cell = pane.proxy.index(0, pane.model.frame.columns.get_loc(field))
        assert pane.proxy.setData(cell, values[field])
        assert len(saved) == int(position == 3)
    assert saved == [values]
    pane.close()


def test_part_can_be_chosen_first_and_major_does_not_restrict_or_clear_it(app):
    paths = [*PATHS, ("기계", "충전기", "베어링", "마모")]
    picker = ClassificationPicker(paths)
    assert picker.combos["middle"].isEnabled()
    picker.set_value({"middle": "모터", "minor": "과열"})
    parts_before = picker.index.menu_choices("middle", picker.value())
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("기계"))
    assert picker.value() == {
        "major": "기계",
        "detail_equipment": "",
        "middle": "모터",
        "minor": "과열",
    }
    assert picker.index.menu_choices("middle", picker.value()) == parts_before
    picker.set_value({**picker.value(), "detail_equipment": "검사기"})
    assert picker.validate_path()["middle"] == "모터"
    picker.close()


def test_phenomenon_choices_are_independent_and_part_change_preserves_phenomenon(app):
    paths = [*PATHS, ("기계", "충전기", "베어링", "마모")]
    picker = ClassificationPicker(paths, category(PATHS[0]))
    before = picker.index.menu_choices("minor", picker.value())
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("기계"))
    assert picker.index.menu_choices("minor", picker.value()) == before
    picker._complete_part("베어링")
    assert picker.value()["minor"] == "과열"
    assert picker.index.menu_choices("minor", picker.value()) == before
    picker.close()


@pytest.mark.parametrize(
    "entered,missing",
    [
        (("major", "middle", "minor"), "detail_equipment"),
        (("middle", "minor"), "major"),
        (("detail_equipment", "middle", "minor"), "major"),
    ],
)
def test_keyboard_entry_returns_to_missing_field_before_leaving_row(app, entered, missing):
    record = {
        "event_id": "keyboard-independent",
        "record_id": "keyboard-independent",
        **dict.fromkeys(CATEGORY_FIELDS, ""),
        "classification_mode": "pending",
    }
    pane = TablePane(sort_policy="source")
    pane.set_frame(pd.DataFrame([record]))
    saved = []
    pane.configure_editing(
        PATHS, lambda row, patch: saved.append(patch) or True, defer_classification=True
    )
    for field in entered:
        cell = pane.proxy.index(0, pane.model.frame.columns.get_loc(field))
        assert pane.proxy.setData(cell, category(PATHS[0])[field])
    assert not saved
    pane._edit_next_classification(cell)
    assert pane.table.currentIndex().row() == 0
    assert pane.table.currentIndex().column() == pane.model.frame.columns.get_loc(missing)
    pane.cancel_editing()
    pane.close()


@pytest.mark.parametrize("last", ["major", "detail_equipment"])
def test_failed_save_can_retry_when_an_independent_field_is_entered_last(app, last):
    record = {
        "event_id": "retry-independent",
        "record_id": "retry-independent",
        **dict.fromkeys(CATEGORY_FIELDS, ""),
        "classification_mode": "pending",
    }
    pane = TablePane(sort_policy="source")
    pane.set_frame(pd.DataFrame([record]))
    attempts = []

    def save(row, patch):
        attempts.append(patch)
        return len(attempts) > 1

    pane.configure_editing(PATHS, save, defer_classification=True)
    for field in (*[key for key in CATEGORY_FIELDS if key != last], last):
        cell = pane.proxy.index(0, pane.model.frame.columns.get_loc(field))
        accepted = pane.proxy.setData(cell, category(PATHS[0])[field])
        assert accepted == (field != last)
    assert pane.proxy.setData(cell, category(PATHS[0])[last])
    assert attempts == [category(PATHS[0])] * 2
    pane.close()


def test_unknown_equipment_is_an_explicit_choice_and_unknown_symptom_is_not_final(app):
    unknown = (*PATHS[0][:-1], "증상 미기재")
    picker = ClassificationPicker([*PATHS, unknown])
    assert unknown not in picker.categories
    picker.set_value(category(PATHS[3]))
    assert picker.validate_path()["detail_equipment"] == "상세설비 미상"
    picker.close()


def test_legacy_record_does_not_gain_an_equipment_until_explicit_selection(app):
    legacy = {"major": "전기·제어", "middle": "모터", "minor": "과열"}
    picker = ClassificationPicker(PATHS, legacy)
    assert picker.value() == {**legacy, "detail_equipment": ""}
    with pytest.raises(UserError, match="모두 선택"):
        picker.validate_path()
    picker.set_value(category(PATHS[3]))
    assert picker.validate_path()["detail_equipment"] == "상세설비 미상"
    picker.close()


def test_candidate_table_keeps_each_equipment_and_displays_evidence(app):
    candidates = [
        {**category(path), "rank": rank, "reason": "원문 근거", "evidence": path[1]}
        for rank, path in enumerate((PATHS[0], PATHS[2]), 1)
    ]
    picker = CandidateListPicker(candidates)
    assert picker.table.columnCount() == 6
    assert picker.table.horizontalHeaderItem(2).text() == "상세설비·모듈"
    assert picker.table.horizontalHeaderItem(3).text() == "세부 부품"
    assert picker.table.item(0, 2).text() == "충전기"
    assert picker.table.item(1, 2).text() == "검사기"
    assert "원문 근거" in picker.table.item(1, 5).text()
    assert picker.table.currentRow() == -1
    picker.close()


def test_four_grid_choices_save_once_and_preserve_one_event(app):
    record = {
        "event_id": "event-4-level",
        "record_id": "record-4-level",
        **dict.fromkeys(CATEGORY_FIELDS, ""),
        "classification_mode": "pending",
        "status": "검토필요",
        "classification_candidates": json.dumps([category(PATHS[0])], ensure_ascii=False),
        "raw_description": "충전기 모터 과열",
    }
    pane = TablePane(sort_policy="source")
    pane.set_frame(MainWindow.classification_frame(pd.DataFrame([record])))
    saved = []
    pane.configure_editing(
        PATHS, lambda row, patch: saved.append((row, patch)) or True, defer_classification=True
    )
    for index, (field, value) in enumerate(zip(CATEGORY_FIELDS, PATHS[0])):
        cell = pane.proxy.index(0, pane.model.frame.columns.get_loc(field))
        assert cell.flags() & Qt.ItemFlag.ItemIsEditable
        assert pane.proxy.setData(cell, value)
        assert len(saved) == int(index == len(CATEGORY_FIELDS) - 1)
    assert saved[0][0]["event_id"] == record["event_id"]
    assert saved[0][1] == category(PATHS[0])
    assert pane.proxy.rowCount() == 1
    pane.close()


def test_pending_view_clears_all_four_final_fields_but_keeps_candidate_equipment(app):
    record = {
        **category(PATHS[0]),
        "classification_mode": "pending",
        "status": "검토필요",
        "classification_candidates": json.dumps([category(PATHS[0])], ensure_ascii=False),
    }
    displayed = MainWindow.classification_frame(pd.DataFrame([record]))
    assert displayed.columns[:4].tolist() == list(CATEGORY_FIELDS)
    assert all(displayed.iloc[0][field] == "" for field in CATEGORY_FIELDS)
    assert (
        json.loads(displayed.iloc[0].classification_candidates)[0]["detail_equipment"] == "충전기"
    )


def test_correction_dialog_uses_the_profile_equipment_taxonomy(app):
    rules = [
        {
            "major": "전기·제어",
            "middle": "모터",
            "minor": "모터(종류 미상)",
            "enabled": True,
            "role": "component",
        }
    ]
    dialog = CorrectionDialog(
        {},
        rules=rules,
        equipment_types=[{"name": "사내 충전설비", "aliases": ["내부충전"]}],
    )
    assert {path[1] for path in dialog.categories} == {"사내 충전설비", "상세설비 미상"}
    dialog.close()


def test_unknown_part_is_a_valid_explicit_manual_choice(app):
    path = ("기계", "컨베어", UNKNOWN_PART, "막힘·걸림")
    picker = ClassificationPicker([path], category(path))
    assert picker.validate_path()["middle"] == "세부 부품 미기재"
    picker.close()


def test_picker_and_grid_reuse_shared_catalog_without_iterating_it(app):
    class IndexedCatalog(ClassificationPathIndex):
        def __iter__(self):
            raise AssertionError("Steady menu lookup scanned the full catalog")

    catalog = IndexedCatalog(PATHS)
    record = {
        **category(PATHS[0]),
        "event_id": "indexed",
        "record_id": "indexed",
        "classification_mode": "single",
        "status": "규칙분류",
    }
    picker = ClassificationPicker(catalog, record)
    assert picker.index is catalog
    assert picker.validate_path() == category(PATHS[0])
    picker.set_value(category(PATHS[2]))
    assert picker.validate_path() == category(PATHS[2])
    pane = TablePane(sort_policy="source")
    pane.set_frame(pd.DataFrame([record]))
    pane.configure_editing(lambda: catalog, lambda row, patch: True)
    assert pane._active_categories() is catalog
    assert pane._category_choices(record, "minor") == ["검출불량", "과열", "소손·단락"]
    picker.close()
    pane.close()


def test_mutable_supplier_replacement_invalidates_index_without_changing_old_menu(app):
    current = [PATHS[0]]
    record = {**category(PATHS[0]), "classification_mode": "pending"}
    pane = TablePane(sort_policy="source")
    pane.configure_editing(lambda: current, lambda row, patch: True)
    old_index = pane._active_categories()
    assert old_index.choices(()) == ("전기·제어",)
    current[:] = [("기계", "컨베어", "베어링", "마모")]
    assert pane._category_choices(record, "major") == ["기계", "전기·제어"]
    assert pane._active_categories().choices(()) == ("기계",)
    assert old_index.choices(()) == ("전기·제어",)
    assert isinstance(old_index.choices(()), tuple)
    pane.close()
