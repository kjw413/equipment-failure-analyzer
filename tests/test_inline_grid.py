"""Record-level table edits persist complete, validated patches only."""
# ruff: noqa: E402

import csv
import json
import os
from io import StringIO

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLineEdit,
    QStyleOptionViewItem,
)

from core.corrections import COMPONENT_FIELD
from gui.inline_editor import ClassificationCellEditor, field_patch
from gui.widgets import FrameModel, TablePane

PATHS = [
    ("유체·배관", "도징설비", "도징펌프", "손상"),
    ("유체·배관", "도징설비", "도징펌프", "누설"),
    ("전기·제어", "검사기", "근접센서", "고장·이상"),
    ("전기·제어", "검사기", "광전센서", "고장·이상"),
    ("전기·제어", "검사기", "모터", "고장·이상"),
]
FIELDS = ("major", "detail_equipment", "minor")
LEGACY_FIELDS = ("major", "detail_equipment", "middle", "minor")


def category(path):
    return dict(zip(FIELDS, (*path[:2], path[-1])))


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
        "detail_equipment": PATHS[0][1],
        "middle": PATHS[0][2],
        "minor": PATHS[0][3],
        "component_types": "도징펌프",
        "classification_mode": "single",
        "component_details": json.dumps([dict(zip(LEGACY_FIELDS, PATHS[0]))]),
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
    for field, value in category(path).items():
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


def test_corner_copies_all_filtered_rows_in_view_order_with_headers(app, pane, record):
    pane.set_frame(
        pd.DataFrame(
            [
                record,
                {
                    **record,
                    "event_id": "event-B",
                    "record_id": "row-B",
                    "minutes": 30,
                    "raw_description": "두 번째\t기록\n추가 설명",
                },
                {**record, "event_id": "event-C", "record_id": "row-C", "product": "숨김 제품"},
            ]
        )
    )
    pane.enable_corner_copy()
    pane.search.setText("제품 A")
    pane.table.sortByColumn(index(pane, "minutes").column(), Qt.SortOrder.DescendingOrder)
    pane.table.selectRow(1)
    pane.resize(900, 500)
    pane.show()
    app.processEvents()
    QTest.mouseClick(pane.table.findChild(QAbstractButton), Qt.MouseButton.LeftButton)
    copied = list(csv.reader(StringIO(app.clipboard().text()), delimiter="\t"))
    assert len(copied) == 3
    visible = [col for col in range(pane.proxy.columnCount()) if not pane.table.isColumnHidden(col)]
    assert copied[0] == [pane.proxy.headerData(col, Qt.Orientation.Horizontal) for col in visible]
    minutes = visible.index(index(pane, "minutes").column())
    description = visible.index(index(pane, "raw_description").column())
    assert [row[minutes] for row in copied[1:]] == ["30", "12"]
    assert copied[1][description] == "두 번째\t기록\n추가 설명"
    assert "원본 기록 ID" not in copied[0]
    assert "event-B" not in app.clipboard().text() and "row-B" not in app.clipboard().text()
    assert "2행" in pane.edit_status.text()


def test_empty_corner_copy_keeps_the_existing_clipboard(app, pane):
    pane.enable_corner_copy()
    pane.search.setText("일치하는 기록 없음")
    app.clipboard().setText("기존 클립보드")
    pane.table.findChild(QAbstractButton).click()
    assert app.clipboard().text() == "기존 클립보드"
    assert "복사할 이력이 없습니다" in pane.edit_status.text()


def test_classification_dialog_centers_on_owner_and_is_movable(app, pane):
    configure(pane, [])
    pane.resize(700, 600)
    pane.move(30, 40)
    pane.show()
    app.processEvents()
    dialog = pane.open_classification_editor(index(pane, "type"))
    app.processEvents()
    assert dialog.windowType() == Qt.WindowType.Dialog
    assert dialog.windowFlags() & Qt.WindowType.WindowTitleHint
    assert dialog.windowTitle() == "최종 분류 한 건 선택"
    assert not dialog.isModal()
    available = pane.screen().availableGeometry()
    expected = dialog.frameGeometry()
    expected.moveCenter(pane.frameGeometry().center())
    expected.moveLeft(
        max(available.left(), min(expected.left(), available.right() - expected.width() + 1))
    )
    expected.moveTop(
        max(available.top(), min(expected.top(), available.bottom() - expected.height() + 1))
    )
    assert (dialog.frameGeometry().topLeft() - expected.topLeft()).manhattanLength() <= 2
    before = dialog.pos()
    dialog.move(before + QPoint(20, 30))
    app.processEvents()
    assert dialog.pos() == before + QPoint(20, 30)
    pane.cancel_editing()


def test_classification_dialog_compares_exact_raw_and_analyzed_text(app, record):
    raw = "보드에러 <비고>\n스패어 없음"
    normalized = "보드 에러 <비고> 스패어 없음"
    values = {**record, "raw_description": raw, "normalized": normalized}
    submitted = []
    dialog = ClassificationCellEditor(values, {}, PATHS, submitted.append)
    dialog.show()
    app.processEvents()
    comparison = dialog.text_comparison
    assert comparison.raw.toPlainText() == raw
    assert comparison.normalized.toPlainText() == normalized
    assert comparison.raw.isReadOnly() and not comparison.normalized.isReadOnly()
    assert (
        comparison.raw.mapToGlobal(QPoint()).x() < comparison.normalized.mapToGlobal(QPoint()).x()
    )
    comparison.normalized.setPlainText("저장하지 않을 수정")
    dialog.close()
    app.processEvents()
    assert not submitted
    assert values["raw_description"] == raw and values["normalized"] == normalized


def test_classification_dialog_does_not_fabricate_missing_normalization(app, record):
    dialog = ClassificationCellEditor(record, {}, PATHS, lambda patch: None)
    assert dialog.text_comparison.normalized.toPlainText() == ""
    assert dialog.text_comparison.normalized.placeholderText() == "표준화 후 내용 없음"
    dialog.close()


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
        "component_details": json.dumps([dict(zip(LEGACY_FIELDS, p)) for p in PATHS[:2]]),
    }
    assert field_patch(multi, {}, "minutes", "50") == {"minutes": "50"}
    assert field_patch(multi, {}, "date", "2026-11-01") == {"work_date": "2026-11-01"}
    assert field_patch(multi, {}, "product", "신제품") == {"product": "신제품"}


def test_major_change_saves_once_and_preserves_equipment_and_symptom(pane):
    saved = []
    configure(pane, saved)
    assert pane.proxy.setData(index(pane, "major"), "전기·제어")
    assert saved == [(saved[0][0], {**category(PATHS[0]), "major": "전기·제어"})]
    assert index(pane, "detail_equipment").data() == PATHS[0][1]
    assert not pane._classification_drafts


def test_leaf_change_is_atomic_but_same_selection_does_not_confirm(pane):
    saved = []
    configure(pane, saved)
    assert pane.proxy.setData(index(pane, "minor"), "손상")
    assert not saved
    assert pane.proxy.setData(index(pane, "minor"), "누설")
    assert saved[0][1] == category(PATHS[1])


def test_failed_complete_draft_retries_same_minor_without_confirming_unchanged_auto_value(pane):
    attempts = []

    def save(record, patch):
        attempts.append(patch)
        return len(attempts) > 1

    pane.configure_editing(PATHS, save)
    assert pane.proxy.setData(index(pane, "minor"), "손상")
    assert not attempts
    assert not pane.proxy.setData(index(pane, "minor"), "누설")
    assert len(attempts) == 1 and pane._classification_drafts
    assert pane.proxy.setData(index(pane, "minor"), "누설")
    assert attempts == [category(PATHS[1])] * 2
    assert not pane._classification_drafts


def test_invalid_category_path_rejected_and_escape_cancels_pending_row(app, pane):
    saved = []
    configure(pane, saved)
    assert not pane.proxy.setData(index(pane, "minor"), "임의 입력")
    pane.model.frame.at[0, "minor"] = ""
    assert pane.proxy.setData(index(pane, "detail_equipment"), "검사기")
    pane.table.setCurrentIndex(index(pane, "detail_equipment"))
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
    assert {combo.itemData(i) for i in range(1, combo.count())} == {"손상", "누설", "고장·이상"}
    delegate.setEditorData(combo, index(pane, "minor"))
    assert combo.currentData() == "손상"
    delegate.destroyEditor(combo, index(pane, "minor"))
    edit = delegate.createEditor(parent, QStyleOptionViewItem(), index(pane, "minutes"))
    assert isinstance(edit, QLineEdit)
    delegate.setEditorData(edit, index(pane, "minutes"))
    assert edit.text() == "12"
    delegate.destroyEditor(edit, index(pane, "minutes"))


def test_popup_single_confirmation_replaces_legacy_multiple_without_changing_other_fields(pane):
    saved = []
    existing = {
        COMPONENT_FIELD: json.dumps([dict(zip(LEGACY_FIELDS, path)) for path in PATHS[:2]]),
        "minutes": "12",
        "product": "제품 A",
    }
    configure(pane, saved, existing)
    popup = pane.open_classification_editor(index(pane, "component_types"))
    assert not hasattr(popup, "mode_combo")
    assert not hasattr(popup, "component_picker")
    assert popup.candidate_list.currentRow() == -1
    select(popup.single_picker, PATHS[1])
    popup.apply_button.click()
    patch = saved[0][1]
    assert patch == {**category(PATHS[1]), COMPONENT_FIELD: None}
    assert "minutes" not in patch and "product" not in patch


def test_incomplete_classification_is_not_saved_until_valid(pane):
    saved = []
    configure(pane, saved)
    popup = pane.open_classification_editor(index(pane, "type"))
    popup.single_picker.set_value(dict.fromkeys(FIELDS, ""))
    popup.apply_button.click()
    assert not saved and "모두 선택" in popup.error.text()
    popup.single_picker.combos["major"].setCurrentIndex(1)
    popup.apply_button.click()
    assert not saved and "모두 선택" in popup.error.text()


def test_clear_classification_only_preserves_non_classification_overrides(pane):
    saved = []
    existing = {
        **dict(zip(LEGACY_FIELDS, PATHS[0])),
        "minutes": "12",
        "work_date": "2026-10-20",
        "target": "내 대상",
    }
    configure(pane, saved, existing)
    popup = pane.open_classification_editor(index(pane, "major"))
    popup.clear_button.click()
    assert saved[0][1] == dict.fromkeys(LEGACY_FIELDS)


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
    pane.model.frame.at[0, "minor"] = ""
    pane.proxy.setData(index(pane, "detail_equipment"), "검사기")
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
    assert pane.classification_editor.candidate_list.currentRow() == -1
    assert not any(pane.classification_editor.single_picker.value().values())


def test_supplier_refreshes_only_when_opened_and_legacy_paths_stay_local(pane, record):
    current = list(PATHS)
    pane.configure_editing(lambda: list(current), lambda record, patch: True)
    current.append(("기계", "이송기", "타이밍벨트", "마모"))
    popup = pane.open_classification_editor(index(pane, "type"))
    assert ("기계", "이송기", "마모") in popup.single_picker.categories
    pane.cancel_editing()
    old = {**record, "minor": "펌프 이상"}
    pane.set_frame(pd.DataFrame([old]))
    popup = pane.open_classification_editor(index(pane, "type"))
    assert tuple(popup.single_picker.value().values()) == (
        "유체·배관",
        "도징설비",
        "펌프 이상",
    )
    assert ("유체·배관", "도징설비", "펌프 이상") not in popup.single_picker.categories
    assert "펌프 이상" not in {p[-1] for p in current}


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
