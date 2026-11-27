"""A record confirms exactly one final classification after an explicit user choice."""
# ruff: noqa: E402

import json
import os

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core.corrections import COMPONENT_FIELD
from core.i18n import K
from core.models import UserError
from gui.classification_picker import ClassificationPicker
from gui.dialogs import CorrectionDialog
from gui.inline_editor import ClassificationCellEditor, classification_patch
from gui.main_window import MainWindow
from gui.widgets import FrameModel, TablePane

FIELDS = ("major", "detail_equipment", "minor")


def public(member):
    return {key: member[key] for key in FIELDS}


MEMBERS = [
    {"detail_equipment": "상세설비 미상", "major": "기계", "middle": "타이밍벨트", "minor": "마모"},
    {
        "detail_equipment": "상세설비 미상",
        "major": "전기·제어",
        "middle": "근접센서",
        "minor": "고장·이상",
    },
]
RULES = [
    {
        "major": "기계",
        "middle": "벨트·풀리",
        "minor": "타이밍벨트",
        "enabled": True,
        "role": "component",
    },
    {
        "major": "전기·제어",
        "middle": "센서·검출",
        "minor": "근접센서",
        "enabled": True,
        "role": "component",
    },
]
CATEGORIES = [tuple(member[key] for key in FIELDS) for member in MEMBERS]
CATEGORIES.append(("기계", "상세설비 미상", "타이밍벨트", "손상"))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def record():
    return {
        "event_id": "event-1",
        "record_id": "row-1",
        "minutes": 10.0,
        "raw_description": "타이밍벨트 마모 또는 근접센서 이상 확인",
        "classification_mode": "ambiguous",
        "status": K["review"],
        "major": "",
        "detail_equipment": "",
        "middle": "",
        "minor": "",
        "component_types": "",
        "classification_candidates": json.dumps(
            [
                {**member, "rank": rank, "reason": f"원문 근거 {rank}", "evidence": f"증거 {rank}"}
                for rank, member in enumerate(MEMBERS, 1)
            ],
            ensure_ascii=False,
        ),
    }


def select(picker, value):
    for key in FIELDS:
        combo = picker.combos[key]
        found = combo.findData(value.get(key, ""))
        assert found >= 0, (key, value)
        combo.setCurrentIndex(found)


@pytest.mark.parametrize("kind", ["popup", "dialog"])
def test_candidates_start_unselected_and_opening_never_saves_first_rank(app, record, kind):
    saved = []
    if kind == "popup":
        editor = ClassificationCellEditor(
            record, {}, CATEGORIES, lambda row, patch: saved.append(patch) or True
        )
        picker = editor.single_picker
    else:
        editor = CorrectionDialog(record, rules=RULES)
        picker = editor.classification_picker
    assert editor.candidate_list.currentRow() == -1
    assert not editor.candidate_list.selectedItems()
    assert not any(picker.value().values())
    assert not hasattr(editor, "mode_combo")
    assert not hasattr(editor, "component_picker")
    assert not hasattr(editor, "multiple_confirm")
    assert editor.candidate_list.rowCount() == 2
    assert "원문 근거 2" in editor.candidate_list.item(1, 4).text()
    assert all(
        "%" not in editor.candidate_list.item(row, column).text()
        for row in range(2)
        for column in range(5)
    )
    assert not saved
    editor.close()


@pytest.mark.parametrize("kind", ["popup", "dialog"])
def test_second_rank_requires_apply_and_preserves_other_saved_fields(app, record, kind):
    existing = {"minutes": "12", "work_date": "2026-11-01", "product": "기존 제품"}
    saved = []
    if kind == "popup":
        editor = ClassificationCellEditor(
            record, existing, CATEGORIES, lambda row, patch: saved.append(patch) or True
        )
        picker = editor.single_picker
    else:
        editor = CorrectionDialog(record, existing, rules=RULES)
        picker = editor.classification_picker
    editor.candidate_list.selectRow(1)
    assert picker.value() == public(MEMBERS[1])
    assert not saved
    if kind == "popup":
        editor.apply()
        assert saved == [public(MEMBERS[1])]
    else:
        assert editor.patch == {}
        editor.validate_and_accept()
        assert editor.result() == QDialog.DialogCode.Accepted
        assert editor.patch == public(MEMBERS[1])
    editor.close()


def test_apply_without_selection_and_invalid_path_are_rejected(app, record):
    saved = []
    editor = ClassificationCellEditor(
        record, {}, CATEGORIES, lambda row, patch: saved.append(patch) or True
    )
    editor.apply()
    assert not saved and "모두 선택" in editor.error.text()
    editor.choose_candidate(
        {
            "detail_equipment": "없는 설비",
            "major": "기계",
            "minor": "마모",
        }
    )
    editor.apply()
    assert not saved and not any(editor.single_picker.value().values())
    with pytest.raises(UserError):
        editor.single_picker.set_value(
            {
                "detail_equipment": "상세설비 미상",
                "major": "기계",
                "middle": "근접센서",
                "minor": "등록되지 않은 현상",
            }
        )
    editor.close()


@pytest.mark.parametrize("gesture", ["enter", "double_click"])
def test_deferred_candidate_can_be_selected_without_a_separate_save_click(app, record, gesture):
    saved = []
    editor = ClassificationCellEditor(
        record,
        {},
        CATEGORIES,
        lambda row, patch: saved.append(patch) or True,
        deferred=True,
    )
    editor.show()
    editor.candidate_list.selectRow(1)
    app.processEvents()
    if gesture == "enter":
        QTest.keyClick(editor.candidate_list, Qt.Key.Key_Return)
    else:
        item = editor.candidate_list.item(1, 1)
        position = editor.candidate_list.visualItemRect(item).center()
        QTest.mouseClick(editor.candidate_list.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseDClick(editor.candidate_list.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert saved == [public(MEMBERS[1])]
    assert not editor.isVisible()


@pytest.mark.parametrize("kind", ["popup", "dialog"])
def test_unknown_symptom_candidate_fills_equipment_only_until_observed_symptom_chosen(
    app, record, kind, monkeypatch
):
    record["classification_candidates"] = json.dumps(
        [{**MEMBERS[0], "minor": "증상 미기재", "rank": 1}]
    )
    saved, warnings = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    if kind == "popup":
        editor = ClassificationCellEditor(
            record, {}, CATEGORIES, lambda row, patch: saved.append(patch) or True
        )
        picker = editor.single_picker
    else:
        editor = CorrectionDialog(record, rules=RULES)
        picker = editor.classification_picker
    editor.candidate_list.selectRow(0)
    assert picker.value() == {**public(MEMBERS[0]), "minor": ""}
    if kind == "popup":
        editor.apply()
        assert not saved
    else:
        editor.validate_and_accept()
        assert not editor.patch and warnings
    select(picker, MEMBERS[0])
    if kind == "popup":
        editor.apply()
        assert saved == [public(MEMBERS[0])]
    else:
        editor.validate_and_accept()
        assert editor.patch == public(MEMBERS[0])
    editor.close()


def test_escape_after_candidate_selection_leaves_saved_values_unchanged(app, record):
    saved = []
    editor = ClassificationCellEditor(
        record, {}, CATEGORIES, lambda row, patch: saved.append(patch) or True
    )
    editor.show()
    editor.candidate_list.selectRow(1)
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert not saved and not editor.isVisible()
    dialog = CorrectionDialog(record, rules=RULES)
    dialog.show()
    dialog.candidate_list.selectRow(1)
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.patch and dialog.result() == QDialog.DialogCode.Rejected
    dialog.close()


def test_legacy_multiple_saved_choices_are_candidates_and_replaced_with_one_final(app, record):
    legacy = {COMPONENT_FIELD: json.dumps(MEMBERS), "minutes": "12"}
    record.update(
        classification_mode="multiple",
        classification_candidates="",
        component_details=json.dumps(MEMBERS),
    )
    editor = CorrectionDialog(record, legacy, rules=RULES)
    assert editor.candidate_list.rowCount() == 2
    assert editor.candidate_list.currentRow() == -1
    assert not any(editor.classification_picker.value().values())
    editor.edits["minutes"].setText("13")
    editor.validate_and_accept()
    assert editor.patch == {"minutes": "13"}
    editor.close()
    replacement = CorrectionDialog(record, legacy, rules=RULES)
    replacement.candidate_list.selectRow(1)
    replacement.validate_and_accept()
    assert replacement.patch == {**public(MEMBERS[1]), COMPONENT_FIELD: None}
    replacement.close()
    with pytest.raises(UserError, match="하나"):
        classification_patch(record, legacy, "multiple", {}, MEMBERS)


def test_current_single_edit_remains_local_and_does_not_change_other_overrides(app):
    current = {**MEMBERS[0], "classification_mode": "single", "status": K["manual"]}
    dialog = CorrectionDialog(current, {**MEMBERS[0], "minutes": "12"}, rules=RULES)
    assert dialog.classification_picker.value() == public(MEMBERS[0])
    assert not dialog.confirm.isChecked()
    select(dialog.classification_picker, MEMBERS[1])
    dialog.validate_and_accept()
    assert dialog.patch == public(MEMBERS[1])
    dialog.close()


def test_equipment_selection_preserves_phenomena_and_rejects_unregistered_values(app):
    picker = ClassificationPicker(CATEGORIES, MEMBERS[0])
    assert set(picker.combos) == set(FIELDS)
    assert all(not combo.isEditable() for combo in picker.combos.values())
    with pytest.raises(UserError):
        picker.set_value({"detail_equipment": "등록되지 않은 설비"})
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("전기·제어"))
    assert picker.validate_path() == {**public(MEMBERS[0]), "major": "전기·제어"}
    picker.close()


def test_review_and_full_record_tables_keep_candidates_and_share_single_choice_popup(app, record):
    shown = MainWindow.classification_frame(pd.DataFrame([record]))
    assert shown.iloc[0].classification_candidates == record["classification_candidates"]
    assert shown.iloc[0].component_types == "미확정 · 후보 선택 필요"
    assert shown.iloc[0].combination_decision == "최종 미확정"
    for review in (False, True):
        pane = TablePane(sort_policy="source")
        pane.set_frame(MainWindow.classification_frame(pd.DataFrame([record]), review=review))
        saved = []
        pane.configure_editing(CATEGORIES, lambda row, patch: saved.append(patch) or True)
        column = pane.model.frame.columns.get_loc("component_types")
        editor = pane.open_classification_editor(pane.proxy.index(0, column))
        assert editor.candidate_list.rowCount() == 2
        assert editor.candidate_list.currentRow() == -1
        editor.candidate_list.selectRow(1)
        editor.apply()
        assert saved == [public(MEMBERS[1])]
        label = pane.model.headerData(column, Qt.Orientation.Horizontal)
        assert "최종 분류" in label and "조합" not in label
        pane.close()
    model = FrameModel(pd.DataFrame([{"classification_mode": "multiple"}]))
    assert model.index(0, 0).data() == "최종 미확정"
