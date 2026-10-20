"""Record-level table edits persist complete, validated patches only."""
# ruff: noqa: E402

import json
import os

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QStyleOptionViewItem

from core.corrections import COMPONENT_FIELD
from gui.inline_editor import ClassificationCellEditor, classification_patch, field_patch
from gui.widgets import DropArea, FrameModel, TablePane

PATHS = [
    ("유체·배관", "펌프", "도징펌프"),
    ("유체·배관", "펌프", "로터리펌프"),
    ("전기·제어", "센서·검출", "근접센서"),
    ("전기·제어", "센서·검출", "광전센서"),
    ("전기·제어", "모터", "모터(종류 미상)"),
]
FIELDS = ("major", "middle", "minor")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def record():
    return {
        "event_id": "event-A",
        "record_id": "row-A",
        "date": pd.Timestamp("2026-10-20"),
        "minutes": 12.0,
        "target": "펌프",
        "product": "제품 A",
        "type": "도징펌프",
        "major": PATHS[0][0],
        "middle": PATHS[0][1],
        "minor": PATHS[0][2],
        "component_types": "도징펌프",
        "classification_mode": "single",
        "component_details": json.dumps([dict(zip(FIELDS, PATHS[0]))]),
        "raw_description": "도징펌프 파손 교체",
        "status": "규칙분류",
    }


@pytest.fixture
def pane(app, record):
    widget = TablePane(sort_policy="source")
    widget.set_frame(pd.DataFrame([record]))
    yield widget
    widget.close()
    app.processEvents()


def index(pane, column, row=0):
    return pane.proxy.index(row, pane.model.frame.columns.get_loc(column))


def select(picker, path):
    for field, value in zip(FIELDS, path):
        combo = picker.combos[field]
        combo.setCurrentIndex(combo.findData(value))


def configure(pane, saved, existing=None):
    pane.configure_editing(
        PATHS,
        lambda record, patch: saved.append((record, patch)) or True,
        lambda event_id: dict(existing or {}),
    )


def test_default_frame_and_pane_remain_read_only(app, pane):
    assert not (index(pane, "minutes").flags() & Qt.ItemFlag.ItemIsEditable)
    model = FrameModel(pane.model.frame)
    assert not (model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
    assert not index(pane, "minutes").model().setData(index(pane, "minutes"), "25")


def test_configured_fields_visible_as_editable_and_calculations_read_only(pane):
    configure(pane, [])
    for column in ("date", "minutes", "target", "product", *FIELDS, "type", "component_types"):
        item = index(pane, column)
        assert item.flags() & Qt.ItemFlag.ItemIsEditable
        assert item.data(Qt.ItemDataRole.BackgroundRole) is not None
        assert "수정" in item.model().headerData(item.column(), Qt.Orientation.Horizontal)
        assert "더블클릭" in item.data(Qt.ItemDataRole.ToolTipRole)
    for column in ("raw_description", "status", "record_id", "event_id"):
        assert not (index(pane, column).flags() & Qt.ItemFlag.ItemIsEditable)


def test_sorted_filtered_edit_uses_the_record_identity_without_overwriting_view(pane, record):
    other = {
        **record,
        "event_id": "event-B",
        "record_id": "row-B",
        "minutes": 99,
        "product": "제품 B",
    }
    pane.set_frame(pd.DataFrame([record, other]))
    saved = []
    configure(pane, saved)
    pane.table.sortByColumn(index(pane, "minutes").column(), Qt.SortOrder.DescendingOrder)
    pane.search.setText("제품 B")
    assert pane.proxy.rowCount() == 1
    assert pane.proxy.setData(index(pane, "minutes"), "37.5")
    assert saved[0][0]["event_id"] == "event-B"
    assert saved[0][0]["record_id"] == "row-B"
    assert saved[0][1] == {"minutes": "37.5"}
    assert pane.model.frame.loc[pane.model.frame.event_id.eq("event-B"), "minutes"].iloc[0] == 99


@pytest.mark.parametrize(
    "column,value",
    [("minutes", "-1"), ("minutes", "nan"), ("minutes", "inf"), ("date", "wrong-date")],
)
def test_invalid_scalar_input_never_saves(pane, column, value):
    saved, errors = [], []
    configure(pane, saved)
    pane.edit_failed.connect(errors.append)
    assert not pane.proxy.setData(index(pane, column), value)
    assert not saved and errors


def test_unchanged_scalar_is_not_an_override_and_clear_only_removes_that_field(pane):
    saved = []
    configure(pane, saved, {"minutes": "12", "major": PATHS[0][0], "product": "제품 A"})
    assert pane.proxy.setData(index(pane, "minutes"), "12.0")
    assert pane.proxy.setData(index(pane, "date"), "2026-10-20")
    assert not saved
    assert pane.proxy.setData(index(pane, "minutes"), "")
    assert saved[0][1] == {"minutes": None}


def test_other_fields_never_confirm_observed_multiple_types(record):
    multi = {
        **record,
        "classification_mode": "multiple",
        "component_details": json.dumps([dict(zip(FIELDS, p)) for p in PATHS[:2]]),
    }
    assert field_patch(multi, {}, "minutes", "50") == {"minutes": "50"}
    assert field_patch(multi, {}, "date", "2026-11-01") == {"work_date": "2026-11-01"}
    assert field_patch(multi, {}, "product", "신제품") == {"product": "신제품"}


def test_category_cascade_saves_one_complete_patch_after_all_children_selected(pane):
    saved = []
    configure(pane, saved)
    assert pane.proxy.setData(index(pane, "major"), "전기·제어")
    assert not saved
    assert index(pane, "middle").data().endswith("중분류 선택")
    assert index(pane, "minor").data().endswith("소분류 선택")
    assert "분류 선택 중" in pane.edit_status.text()
    assert pane.proxy.setData(index(pane, "middle"), "센서·검출")
    assert not saved
    assert pane.proxy.setData(index(pane, "minor"), "근접센서")
    assert saved[0][1] == dict(zip(FIELDS, PATHS[2]))
    assert not pane._classification_drafts


def test_leaf_change_is_atomic_but_same_selection_does_not_confirm(pane):
    saved = []
    configure(pane, saved)
    assert pane.proxy.setData(index(pane, "minor"), "도징펌프")
    assert not saved
    assert pane.proxy.setData(index(pane, "minor"), "로터리펌프")
    assert saved[0][1] == dict(zip(FIELDS, PATHS[1]))


def test_failed_complete_draft_retries_same_minor_without_confirming_unchanged_auto_value(pane):
    attempts = []

    def save(record, patch):
        attempts.append(patch)
        return len(attempts) > 1

    pane.configure_editing(PATHS, save)
    assert pane.proxy.setData(index(pane, "minor"), "도징펌프")
    assert not attempts
    assert not pane.proxy.setData(index(pane, "minor"), "로터리펌프")
    assert len(attempts) == 1 and pane._classification_drafts
    assert pane.proxy.setData(index(pane, "minor"), "로터리펌프")
    assert attempts == [dict(zip(FIELDS, PATHS[1]))] * 2
    assert not pane._classification_drafts


def test_drop_area_compacts_after_load_and_restores_original_prompt(app):
    drop = DropArea()
    original = drop.browse_button.text()
    drop.set_compact(True)
    assert drop.title.isHidden() and drop.subtitle.isHidden()
    assert drop.minimumHeight() == 56 and drop.maximumHeight() == 60
    assert drop.browse_button.text() == "다른 파일 선택"
    assert drop.acceptDrops()
    drop.set_compact(False)
    assert not drop.title.isHidden() and not drop.subtitle.isHidden()
    assert drop.minimumHeight() == 126
    assert drop.browse_button.text() == original
    drop.close()


def test_invalid_category_path_rejected_and_escape_cancels_pending_row(app, pane):
    saved = []
    configure(pane, saved)
    assert not pane.proxy.setData(index(pane, "minor"), "임의 입력")
    assert pane.proxy.setData(index(pane, "major"), "전기·제어")
    pane.table.setCurrentIndex(index(pane, "middle"))
    QTest.keyClick(pane.table, Qt.Key.Key_Escape)
    assert not pane._classification_drafts and not saved
    assert index(pane, "major").data() == "유체·배관"
    assert "취소" in pane.edit_status.text()


def test_combo_delegate_uses_current_parent_choices_and_scalar_delegate_uses_text(pane):
    configure(pane, [])
    delegate = pane.edit_delegate
    parent = pane.table.viewport()
    combo = delegate.createEditor(parent, QStyleOptionViewItem(), index(pane, "minor"))
    assert isinstance(combo, QComboBox) and not combo.isEditable()
    assert {combo.itemData(i) for i in range(1, combo.count())} == {"도징펌프", "로터리펌프"}
    delegate.setEditorData(combo, index(pane, "minor"))
    assert combo.currentData() == "도징펌프"
    delegate.destroyEditor(combo, index(pane, "minor"))
    edit = delegate.createEditor(parent, QStyleOptionViewItem(), index(pane, "minutes"))
    assert isinstance(edit, QLineEdit)
    delegate.setEditorData(edit, index(pane, "minutes"))
    assert edit.text() == "12"
    delegate.destroyEditor(edit, index(pane, "minutes"))


def test_popup_explicit_single_confirmation_and_multiple_transition_keep_other_fields(pane):
    saved = []
    existing = {**dict(zip(FIELDS, PATHS[0])), "minutes": "12", "product": "제품 A"}
    configure(pane, saved, existing)
    popup = pane.open_classification_editor(index(pane, "component_types"))
    popup.mode_combo.setCurrentIndex(1)
    assert len(popup.component_picker.pickers) == 1
    select(popup.component_picker.add_row(), PATHS[2])
    popup.apply_button.click()
    patch = saved[0][1]
    assert {tuple(p[k] for k in FIELDS) for p in json.loads(patch[COMPONENT_FIELD])} == {
        PATHS[0],
        PATHS[2],
    }
    assert all(patch[k] is None for k in FIELDS)
    assert "minutes" not in patch and "product" not in patch
    single = classification_patch(
        saved[0][0],
        {COMPONENT_FIELD: patch[COMPONENT_FIELD], "minutes": "12"},
        "single",
        dict(zip(FIELDS, PATHS[1])),
        [],
    )
    assert single == {**dict(zip(FIELDS, PATHS[1])), COMPONENT_FIELD: None}


def test_incomplete_multiple_is_not_saved_until_valid(pane):
    saved = []
    configure(pane, saved)
    popup = pane.open_classification_editor(index(pane, "type"))
    popup.mode_combo.setCurrentIndex(1)
    popup.component_picker.add_row()
    popup.apply_button.click()
    assert not saved and "2개 이상" in popup.error.text()
    popup.component_picker.pickers[-1].combos["major"].setCurrentIndex(1)
    popup.apply_button.click()
    assert not saved and "모두 선택" in popup.error.text()


def test_clear_classification_only_preserves_non_classification_overrides(pane):
    saved = []
    existing = {
        **dict(zip(FIELDS, PATHS[0])),
        "minutes": "12",
        "work_date": "2026-10-20",
        "target": "내 대상",
    }
    configure(pane, saved, existing)
    popup = pane.open_classification_editor(index(pane, "major"))
    popup.clear_button.click()
    assert saved[0][1] == dict.fromkeys(FIELDS)


def test_popup_cancel_and_busy_disable_cannot_persist(app, pane):
    saved = []
    configure(pane, saved)
    popup = pane.open_classification_editor(index(pane, "type"))
    select(popup.single_picker, PATHS[1])
    QTest.keyClick(popup, Qt.Key.Key_Escape)
    assert not saved and not popup.isVisible()
    pane.set_editing_enabled(False)
    assert not pane.proxy.setData(index(pane, "minutes"), "30")
    assert pane.open_classification_editor(index(pane, "type")) is None
    assert not (index(pane, "minutes").flags() & Qt.ItemFlag.ItemIsEditable)
    pane.set_editing_enabled(True)
    assert pane.proxy.setData(index(pane, "minutes"), "30")


def test_set_frame_preserves_edit_capability_and_discloses_incomplete_draft(pane):
    configure(pane, [])
    pane.proxy.setData(index(pane, "major"), "전기·제어")
    pane.set_frame(pane.model.frame)
    assert not pane._classification_drafts
    assert "저장되지 않았습니다" in pane.edit_status.text()
    assert index(pane, "minutes").flags() & Qt.ItemFlag.ItemIsEditable


def test_multiple_category_cells_show_dash_and_open_popup(app, pane, record):
    pane.set_frame(pd.DataFrame([{**record, "classification_mode": "multiple"}]))
    configure(pane, [])
    for column in FIELDS:
        assert index(pane, column).data() == "-"
    assert (
        pane.edit_delegate.createEditor(
            pane.table.viewport(), QStyleOptionViewItem(), index(pane, "major")
        )
        is None
    )
    assert isinstance(pane.classification_editor, ClassificationCellEditor)
    assert pane.classification_editor.mode_combo.currentData() == "multiple"


def test_supplier_refreshes_only_when_opened_and_legacy_paths_stay_local(pane, record):
    current = list(PATHS)
    pane.configure_editing(lambda: list(current), lambda record, patch: True)
    current.append(("기계", "벨트", "타이밍벨트"))
    popup = pane.open_classification_editor(index(pane, "type"))
    assert ("기계", "벨트", "타이밍벨트") in popup.single_picker.categories
    pane.cancel_editing()
    old = {**record, "minor": "펌프 이상"}
    pane.set_frame(pd.DataFrame([old]))
    popup = pane.open_classification_editor(index(pane, "type"))
    assert tuple(popup.single_picker.value().values()) == ("유체·배관", "펌프", "펌프 이상")
    assert ("유체·배관", "펌프", "펌프 이상") not in popup.single_picker.categories
    assert "펌프 이상" not in {p[2] for p in current}


def test_missing_record_identity_and_callback_failures_are_safe(pane, record):
    errors, saved = [], []
    pane.edit_failed.connect(errors.append)
    configure(pane, saved)
    pane.set_frame(pd.DataFrame([{**record, "event_id": "", "record_id": ""}]))
    assert not pane.proxy.setData(index(pane, "minutes"), "40")
    assert not saved
    pane.set_frame(pd.DataFrame([record]))

    def fail(record, patch):
        raise OSError("저장 실패")

    pane.configure_editing(PATHS, fail)
    assert not pane.proxy.setData(index(pane, "minutes"), "40")
    assert errors[-1] == "저장 실패"
