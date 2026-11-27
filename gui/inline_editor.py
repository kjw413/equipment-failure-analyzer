"""Validated table-cell corrections and a non-modal classification editor."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from PySide6.QtCore import QEvent, QPersistentModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
)

from core.corrections import COMPONENT_FIELD, correction_patch, initial_values, shown, validate
from core.models import UserError
from core.parsing import parse_date
from core.public_taxonomy import REPAIR_ACTIONS
from gui.classification_picker import (
    FIELDS,
    CandidateListPicker,
    ClassificationPicker,
    RepairActionsPicker,
    record_candidates,
)
from gui.source_text_review import ClassificationTextComparison

EDITABLE_COLUMNS = {
    "date": "work_date",
    "minutes": "minutes",
    "target": "target",
    "product": "product",
    "type": "classification",
    "component_types": "classification",
    "major": "classification",
    "detail_equipment": "classification",
    "minor": "classification",
    "repair_actions": "repair_actions",
}
RECORD_ROLE = int(Qt.ItemDataRole.UserRole) + 31
CHOICES_ROLE = RECORD_ROLE + 1
MULTIPLE_ROLE = RECORD_ROLE + 2


def field_text(record: dict, column: str) -> str:
    """Use the effective row value as the starting text, not an empty override."""
    value = record.get(column)
    if column == "date":
        parsed = parse_date(value)
        return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")
    if column == "minutes" and shown(value):
        try:
            return format(float(value), ".15g")
        except (ValueError, TypeError):
            pass
    return shown(value)


def field_patch(record: dict, existing: dict, column: str, text: str) -> dict:
    """Edit only the requested field; time/date edits never confirm classification."""
    field = EDITABLE_COLUMNS.get(column)
    if field in (None, "classification"):
        raise UserError("이 열은 직접 수정할 수 없습니다.")
    value = str(text).strip()
    error = validate({field: value})
    if error:
        raise UserError(error)
    if column == "date" and value:
        value = parse_date(value).strftime("%Y-%m-%d")
    elif column == "minutes" and value:
        value = format(float(value), ".15g")
    if value == field_text(record, column):
        return {}
    initial = initial_values(record, existing)
    values = {**initial, field: value}
    # The shared correction builder applies the same clearing and preservation rules.
    patch = correction_patch(initial, values, existing, False)
    return {field: patch[field]} if field in patch else {}


def classification_patch(
    record, existing, mode, single, components, *, repair_actions=None
) -> dict:
    if mode != "single" or components:
        raise UserError("최종 분류는 고장이력 한 건당 하나만 선택할 수 있습니다.")
    initial = initial_values(record, existing)
    values = dict(initial)
    unchanged = all(single.get(key, "") == initial.get(key, "") for key in FIELDS)
    if (
        record.get("status") == "부분분류" or record.get("classification_known_fields")
    ) and unchanged:
        if repair_actions is None or repair_actions == initial.get("repair_actions", ""):
            return {}
        return field_patch(record, existing, "repair_actions", repair_actions)
    if not all(single.get(key) for key in FIELDS):
        raise UserError("고장 분야·상세설비·고장 현상을 모두 선택하세요.")
    values.update(single)
    if repair_actions is not None:
        values["repair_actions"] = repair_actions
    checked = dict(values)
    if checked.get("repair_actions", "") == initial.get("repair_actions", ""):
        checked.pop("repair_actions", None)
    error = validate(checked)
    if error:
        raise UserError(error)
    patch = correction_patch(initial, values, existing, True)
    return {
        key: value
        for key, value in patch.items()
        if key in (*FIELDS, COMPONENT_FIELD, "middle", "repair_actions")
    }


class ClassificationCellEditor(QDialog):
    """A movable, centered non-modal dialog; changes need an explicit Apply."""

    def __init__(
        self, record, existing, categories, submit: Callable, parent=None, *, deferred=False
    ):
        super().__init__(
            parent,
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        self.setObjectName("classificationCellEditor")
        self.setWindowTitle("최종 분류 한 건 선택")
        self.setSizeGripEnabled(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.record = dict(record)
        self.existing = {key: value for key, value in existing.items() if key != "saved_at"}
        self.submit = submit
        self.setMinimumWidth(880)
        outer = QVBoxLayout(self)
        heading = QLabel("최종 분류 한 건 선택")
        heading.setStyleSheet("font-weight: 700; font-size: 15px;")
        outer.addWidget(heading)
        self.text_comparison = ClassificationTextComparison(record, editable=True)
        self.initial_normalized = self.text_comparison.normalized.toPlainText().strip()
        outer.addWidget(self.text_comparison)
        initial = initial_values(record, self.existing)
        self.initial_classification = {key: initial.get(key, "") for key in FIELDS}
        if not record.get("classification_known_fields") and (
            record.get("classification_mode")
            in (
                "multiple",
                "pending",
                "ambiguous",
            )
            or self.existing.get(COMPONENT_FIELD)
        ):
            initial = {**initial, **dict.fromkeys(FIELDS, "")}
        self.single_picker = ClassificationPicker(categories, initial)
        self.initial_selection = self.single_picker.value()
        self.candidate_picker = CandidateListPicker(record_candidates(record, self.existing))
        self.candidate_list = self.candidate_picker.table
        self.candidate_picker.selected.connect(self.choose_candidate)
        outer.addWidget(self.candidate_picker, 1)
        outer.addWidget(QLabel("직접 선택 · 상세설비, 고장 현상, 고장 분야"))
        outer.addWidget(self.single_picker)
        if record.get("classification_known_fields"):
            note = QLabel(
                "검토 중에도 확인된 항목은 유지됩니다. 빈 항목과 의심·대안 후보를 확인하세요. "
                "확인된 상세설비는 상세설비별 고장이력에 포함합니다."
            )
            note.setWordWrap(True)
            outer.addWidget(note)
        if record.get("status") == "부분분류":
            note = QLabel(
                "부분분류 · 확인된 항목은 유지됩니다. 원문에 없는 현상·분야를 추측해 입력할 필요가 없습니다. "
                "조치만 바꾸면 분류를 재확정하지 않고 저장합니다."
                + (
                    "\n미기재: " + str(record["classification_missing_fields"])
                    if record.get("classification_missing_fields")
                    else ""
                )
            )
            note.setWordWrap(True)
            note.setObjectName("muted")
            outer.addWidget(note)
        outer.addWidget(QLabel("조치 내역 · 복수 선택 가능"))
        self.actions_picker = RepairActionsPicker(initial.get("repair_actions", ""))
        outer.addWidget(self.actions_picker)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #a52a2a;")
        outer.addWidget(self.error)
        help_label = QLabel(
            "수기 입력은 선택을 누르면 저장하고 다시 분석합니다. 최종 분류는 분석 실행에서 일괄 확정합니다."
            if deferred
            else "적용하면 수정한 내용을 저장합니다. 취소·Esc로 변경을 취소할 수 있습니다."
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("muted")
        outer.addWidget(help_label)
        buttons = QHBoxLayout()
        self.clear_button = QPushButton("분류 보정 해제")
        self.clear_button.setToolTip(
            "이 기록의 분류 보정만 해제합니다. 시간·일자·제품·대상 보정은 유지합니다."
        )
        self.clear_button.setEnabled(
            any(key in self.existing for key in (*FIELDS, COMPONENT_FIELD))
        )
        self.clear_button.clicked.connect(self.clear_classification)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.close)
        self.apply_button = QPushButton("선택" if deferred else "적용")
        if deferred:
            self.apply_button.setDefault(True)
            self.candidate_list.activated.connect(lambda _: self.apply())
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.apply_button)
        outer.addLayout(buttons)
        self.resize(1000, 670)

    def choose_candidate(self, candidate):
        try:
            self.single_picker.select_candidate(candidate)
            self.error.setStyleSheet(
                "color: #AD6817;" if not self.single_picker.value()["minor"] else "color: #697681;"
            )
            self.error.setText(
                "실제 고장 현상을 선택한 뒤 적용하세요."
                if not self.single_picker.value()["minor"]
                else "선택한 후보를 확인한 뒤 적용하세요."
            )
        except UserError as exc:
            self.single_picker.set_value(dict.fromkeys(FIELDS, ""))
            self.error.setStyleSheet("color: #a52a2a;")
            self.error.setText(str(exc))

    def show_centered(self):
        owner = self.parentWidget().window() if self.parentWidget() else None
        screen = owner.screen() if owner is not None else self.screen()
        available = screen.availableGeometry() if screen is not None else None
        if screen is not None:
            self.setMinimumWidth(min(660, available.width()))
            self.resize(
                min(self.width(), available.width()), min(self.height(), available.height())
            )
        self.show()
        frame = self.frameGeometry()
        if available is not None:
            # Fit the native title bar and borders as well as the dialog contents.
            width = max(1, available.width() - (frame.width() - self.width()))
            height = max(1, available.height() - (frame.height() - self.height()))
            self.setMinimumWidth(min(660, width))
            self.resize(min(self.width(), width), min(self.height(), height))
            frame = self.frameGeometry()
        if owner is not None:
            frame.moveCenter(owner.frameGeometry().center())
        elif available is not None:
            frame.moveCenter(available.center())
        if available is not None:
            frame.moveLeft(
                max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
            )
            frame.moveTop(
                max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
            )
        self.move(frame.topLeft())
        self.raise_()
        self.activateWindow()
        self.candidate_list.setFocus()

    def apply(self):
        try:
            normalized = self.text_comparison.normalized.toPlainText().strip()
            text_edited = normalized != self.initial_normalized
            patch = {}
            if text_edited and (normalized or "normalized" in self.existing):
                error = validate({"normalized": normalized})
                if error:
                    raise UserError(error)
                patch["normalized"] = normalized or None
            single = self.single_picker.value()
            if text_edited and single == self.initial_selection:
                patch.update(
                    field_patch(
                        self.record, self.existing, "repair_actions", self.actions_picker.value()
                    )
                )
                self._save(patch)
                return
            keep_partial = (
                self.record.get("status") == "부분분류"
                or self.record.get("classification_known_fields")
            ) and single == self.initial_classification
            if not keep_partial:
                single = self.single_picker.validate_path()
            patch.update(
                classification_patch(
                    self.record,
                    self.existing,
                    "single",
                    single,
                    [],
                    repair_actions=self.actions_picker.value(),
                )
            )
            self._save(patch)
        except (UserError, ValueError, TypeError) as exc:
            self.error.setStyleSheet("color: #a52a2a;")
            self.error.setText(str(exc))

    def clear_classification(self):
        patch = {key: None for key in (*FIELDS, "middle", COMPONENT_FIELD) if key in self.existing}
        self._save(patch)

    def _save(self, patch):
        if not patch:
            self.error.setText("변경된 내용이 없습니다.")
            return
        if self.submit(self.record, patch):
            self.close()
        else:
            self.error.setText("변경 내용을 저장하지 못했습니다. 안내를 확인하고 다시 시도하세요.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)


class CellEditDelegate(QStyledItemDelegate):
    classification_requested = Signal(object)
    classification_advanced = Signal(object)
    draft_cancel_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_editor = None

    def createEditor(self, parent, option, index):
        column = index.model().headerData(
            index.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.UserRole
        )
        if column in ("type", "component_types") or (
            column in FIELDS and index.data(MULTIPLE_ROLE)
        ):
            self.classification_requested.emit(index)
            return None
        if column not in EDITABLE_COLUMNS:
            return None
        if column in FIELDS:
            editor = QComboBox(parent)
            editor.setEditable(False)
            editor.addItem("목록에서 선택", "")
            for choice in index.data(CHOICES_ROLE) or []:
                editor.addItem(choice, choice)
            position = QPersistentModelIndex(index)

            def chosen(_):
                self.commitData.emit(editor)
                accepted = editor.property("edit_accepted")
                self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)
                if accepted:
                    self.classification_advanced.emit(position)

            editor.activated.connect(chosen)
            self.active_editor = editor
            editor.setProperty("edit_record", index.data(RECORD_ROLE))
            return editor
        editor = QLineEdit(parent)
        editor.setFrame(False)
        if column == "repair_actions":
            editor.setPlaceholderText("교체, 점검 · 쉼표로 복수 입력 / 비우면 조치 없음")
            editor.setToolTip(
                ", ".join(REPAIR_ACTIONS) + "\n쉼표로 복수 입력 · 비우면 조치 없음으로 저장"
            )
        else:
            editor.setPlaceholderText("비우면 원본 값으로 복원")
            editor.setToolTip("Enter 또는 다른 셀 클릭: 저장 / Esc: 취소 / 비우기: 해당 보정 해제")
        self.active_editor = editor
        return editor

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            selected = editor.findData(index.data(Qt.ItemDataRole.EditRole))
            editor.setCurrentIndex(max(0, selected))
            return
        editor.setText(str(index.data(Qt.ItemDataRole.EditRole) or ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        value = editor.currentData() if isinstance(editor, QComboBox) else editor.text()
        editor.setProperty("edit_accepted", model.setData(index, value, Qt.ItemDataRole.EditRole))

    def destroyEditor(self, editor, index):
        if self.active_editor is editor:
            self.active_editor = None
        super().destroyEditor(editor, index)

    def cancel_editing(self):
        if self.active_editor is not None:
            self.closeEditor.emit(
                self.active_editor, QAbstractItemDelegate.EndEditHint.RevertModelCache
            )

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            record = editor.property("edit_record")
            if record:
                self.draft_cancel_requested.emit(record)
        return super().eventFilter(editor, event)
