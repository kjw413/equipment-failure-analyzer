"""Independent failure dimensions, searchable part groups and separate repair actions."""
# ruff: noqa: E402

import os

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.corrections import initial_values
from core.failure_modes import UNKNOWN_SYMPTOM
from core.i18n import K
from core.models import UserError
from core.public_taxonomy import REPAIR_ACTIONS, part_group
from gui.classification_picker import ClassificationPicker, RepairActionsPicker
from gui.dialogs import CorrectionDialog
from gui.inline_editor import ClassificationCellEditor, classification_patch, field_patch
from gui.main_window import MainWindow
from gui.widgets import TablePane

FIELDS = ("major", "detail_equipment", "middle", "minor")
PATHS = [
    ("기계", "컨베어", "타이밍벨트", "마모"),
    ("전기·제어", "검사기", "광전센서", "감지불량"),
    ("기계", "상세설비 미상", "베어링", "손상·파손"),
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def category(path):
    return dict(zip(FIELDS, path))


def choose(picker, field, name):
    combo = picker.combos[field]
    index = combo.findData(name)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_phenomenon_is_available_first_and_survives_part_and_domain_changes(app):
    picker = ClassificationPicker(PATHS)
    assert all(combo.isEnabled() for combo in picker.combos.values())
    choose(picker, "minor", "마모")
    choose(picker, "middle", "광전센서")
    choose(picker, "major", "기계")
    choose(picker, "detail_equipment", "컨베어")
    assert picker.validate_path() == {
        "major": "기계",
        "detail_equipment": "컨베어",
        "middle": "광전센서",
        "minor": "마모",
    }
    picker.group_combo.setCurrentIndex(0)
    choose(picker, "middle", "타이밍벨트")
    assert picker.value()["minor"] == "마모"
    picker.close()


def test_part_group_is_derived_and_global_search_bypasses_browse_filter(app):
    picker = ClassificationPicker(PATHS, category(PATHS[0]))
    assert picker.group_combo.currentData() == part_group("타이밍벨트")
    assert picker.combos["middle"].isEditable()
    selected = picker.value()
    sensor_group = picker.group_combo.findData(part_group("광전센서"))
    picker.group_combo.setCurrentIndex(sensor_group)
    assert picker.value() == selected
    assert picker.combos["middle"].findData("광전센서") >= 0
    picker._complete_part("광전센서")
    assert picker.value() == {**selected, "middle": "광전센서"}
    assert picker.group_combo.currentData() == part_group("광전센서")
    picker._complete_part("타이밍벨트")
    assert picker.value() == selected
    assert picker.group_combo.currentData() == part_group("타이밍벨트")
    picker.close()


def test_freeform_part_text_cannot_be_confirmed(app):
    picker = ClassificationPicker(PATHS, category(PATHS[0]))
    picker.combos["middle"].setEditText("등록되지 않은 임의 부품")
    with pytest.raises(UserError, match="모두 선택"):
        picker.validate_path()
    picker.close()


@pytest.mark.parametrize("phenomenon", ["교체", "현상 미기재", "증상 미기재"])
def test_action_or_missing_phenomenon_is_preserved_as_legacy_but_not_new_final(app, phenomenon):
    legacy = {**category(PATHS[0]), "minor": phenomenon}
    picker = ClassificationPicker([*PATHS, (*PATHS[0][:-1], phenomenon)], legacy)
    assert picker.value() == legacy
    assert phenomenon not in picker.index.menu_choices("minor", {})
    with pytest.raises(UserError):
        picker.validate_path()
    picker.select_candidate(legacy)
    assert picker.value()["minor"] == ""
    picker.close()


def test_repair_actions_are_multiple_standard_choices_and_preserve_untouched_legacy(app):
    picker = RepairActionsPicker("기존 비표준 조치")
    assert picker.value() == "기존 비표준 조치"
    assert set(picker.checkboxes) == set(REPAIR_ACTIONS)
    picker.checkboxes["교체"].setChecked(True)
    picker.checkboxes["점검"].setChecked(True)
    assert picker.value() == ", ".join(
        action for action in REPAIR_ACTIONS if action in {"교체", "점검"}
    )
    picker.close()


def test_popup_saves_actions_separately_without_saving_derived_group(app):
    saved = []
    record = {"event_id": "actions", "classification_mode": "single", **category(PATHS[0])}
    editor = ClassificationCellEditor(
        record, {}, PATHS, lambda row, patch: saved.append(patch) or True
    )
    editor.actions_picker.checkboxes["교체"].setChecked(True)
    editor.actions_picker.checkboxes["점검"].setChecked(True)
    editor.apply()
    assert saved == [{**category(PATHS[0]), "repair_actions": editor.actions_picker.value()}]
    assert "part_group" not in saved[0]
    editor.close()


def test_action_scalar_edit_leaves_classification_unconfirmed(app):
    record = {"classification_mode": "pending", "repair_actions": "점검"}
    assert field_patch(record, {}, "repair_actions", "교체, 점검") == {
        "repair_actions": "교체, 점검"
    }
    with pytest.raises(UserError):
        field_patch(record, {}, "repair_actions", "임의 조치")
    patch = classification_patch(
        record, {}, "single", category(PATHS[0]), [], repair_actions="교체"
    )
    assert patch == {**category(PATHS[0]), "repair_actions": "교체"}
    assert field_patch(record, {}, "repair_actions", "") == {"repair_actions": ""}


def test_actions_only_correction_does_not_confirm_pending_classification(app):
    record = {"classification_mode": "pending", "repair_actions": "교체"}
    dialog = CorrectionDialog(record)
    assert not dialog.confirm.isChecked()
    dialog.actions_picker.checkboxes["교체"].setChecked(False)
    dialog.validate_and_accept()
    assert dialog.patch == {"repair_actions": ""}
    assert not dialog.confirm.isChecked()
    dialog.close()


def test_unchanged_legacy_actions_do_not_block_new_classification(app):
    record = {"repair_actions": "이전 작업 메모"}
    patch = classification_patch(
        record, {}, "single", category(PATHS[0]), [], repair_actions="이전 작업 메모"
    )
    assert patch == category(PATHS[0])


def test_grid_group_is_derived_readonly_and_action_is_separate_editable_field(app):
    record = {
        "event_id": "grid-v3",
        "record_id": "grid-v3",
        "classification_mode": "single",
        "repair_actions": "점검",
        **category(PATHS[0]),
    }
    pane = TablePane(sort_policy="source")
    pane.set_frame(pd.DataFrame([record]))
    saved = []
    pane.configure_editing(PATHS, lambda row, patch: saved.append(patch) or True)
    group = pane.proxy.index(0, pane.model.frame.columns.get_loc("part_group"))
    actions = pane.proxy.index(0, pane.model.frame.columns.get_loc("repair_actions"))
    assert group.data() == part_group("타이밍벨트")
    assert not (group.flags() & Qt.ItemFlag.ItemIsEditable)
    assert actions.flags() & Qt.ItemFlag.ItemIsEditable
    assert pane.proxy.setData(actions, "교체")
    assert saved == [{"repair_actions": "교체"}]
    pane.close()


def partial_record():
    return {
        "event_id": "partial-actions",
        "record_id": "partial-actions",
        "status": K["partial"],
        "classification_mode": "single",
        **category(PATHS[0]),
        "minor": UNKNOWN_SYMPTOM,
        "repair_actions": "교체",
        "classification_missing_fields": "고장 현상",
    }


def test_partial_editor_keeps_known_axes_and_can_save_only_actions(app):
    record = partial_record()
    initial = initial_values(record, {})
    assert {key: initial[key] for key in FIELDS[:-1]} == {key: record[key] for key in FIELDS[:-1]}
    assert initial["minor"] == ""
    saved = []
    editor = ClassificationCellEditor(
        record, {}, PATHS, lambda row, patch: saved.append(patch) or True
    )
    assert editor.single_picker.value() == {key: initial[key] for key in FIELDS}
    editor.actions_picker.checkboxes["교체"].setChecked(False)
    editor.actions_picker.checkboxes["점검"].setChecked(True)
    editor.apply()
    assert saved == [{"repair_actions": "점검"}]
    editor.close()


def test_partial_correction_action_only_does_not_require_invented_phenomenon(app):
    dialog = CorrectionDialog(partial_record(), rules=[])
    assert dialog.classification_picker.value()["middle"] == PATHS[0][2]
    assert not dialog.confirm.isChecked()
    dialog.actions_picker.checkboxes["교체"].setChecked(False)
    dialog.validate_and_accept()
    assert dialog.patch == {"repair_actions": ""}
    assert not dialog.confirm.isChecked()
    dialog.close()


def test_partial_unchanged_apply_does_not_request_missing_information(app):
    saved = []
    editor = ClassificationCellEditor(
        partial_record(), {}, PATHS, lambda row, patch: saved.append(patch) or True
    )
    editor.apply()
    assert not saved
    assert editor.error.text() == "변경된 내용이 없습니다."
    editor.close()


def test_partial_grid_presentation_keeps_known_axes_and_explicit_status():
    record = partial_record()
    frame = MainWindow.classification_frame(pd.DataFrame([record]))
    assert frame.iloc[0]["middle"] == record["middle"]
    assert frame.iloc[0]["minor"] == UNKNOWN_SYMPTOM
    assert frame.iloc[0]["combination_decision"] == K["partial"]
    assert frame.iloc[0]["classification_missing_fields"] == "고장 현상"
