"""Validated table-cell corrections and a non-modal classification editor."""

from __future__ import annotations

import json
from collections.abc import Callable

import pandas as pd
from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from core.corrections import COMPONENT_FIELD, correction_patch, initial_values, shown, validate
from core.models import UserError
from core.parsing import parse_date
from gui.classification_picker import FIELDS, ClassificationPicker, ComponentPicker

EDITABLE_COLUMNS = {
    "date": "work_date",
    "minutes": "minutes",
    "target": "target",
    "product": "product",
    "type": "classification",
    "component_types": "classification",
    "major": "classification",
    "middle": "classification",
    "minor": "classification",
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


def classification_patch(record, existing, mode, single, components) -> dict:
    initial = initial_values(record, existing)
    values = dict(initial)
    multiple = mode == "multiple"
    if multiple:
        values[COMPONENT_FIELD] = json.dumps(components, ensure_ascii=False)
    else:
        if not all(single.get(key) for key in FIELDS):
            raise UserError("대·중·소분류를 모두 선택하세요.")
        values.update(single)
    error = validate(values, confirm_components=multiple)
    if error:
        raise UserError(error)
    patch = correction_patch(initial, values, existing, not multiple, confirm_components=multiple)
    return {key: value for key, value in patch.items() if key in (*FIELDS, COMPONENT_FIELD)}


class ClassificationCellEditor(QFrame):
    """A popup anchored to the classification cell; changes need an explicit Apply."""

    def __init__(self, record, existing, categories, submit: Callable, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("classificationCellEditor")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.record = dict(record)
        self.existing = {key: value for key, value in existing.items() if key != "saved_at"}
        self.submit = submit
        self.setMinimumWidth(660)
        outer = QVBoxLayout(self)
        heading = QLabel("분류 직접 수정")
        heading.setStyleSheet("font-weight: 700; font-size: 15px;")
        outer.addWidget(heading)
        source = QLabel(shown(record.get("raw_description")) or "고장 내용 없음")
        source.setWordWrap(True)
        source.setMaximumHeight(80)
        source.setToolTip(shown(record.get("raw_description")))
        source.setObjectName("muted")
        outer.addWidget(source)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("유형 선택"))
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName("단일 또는 복수 유형")
        self.mode_combo.addItem("단일 유형", "single")
        self.mode_combo.addItem("복수 유형", "multiple")
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        outer.addLayout(mode_row)
        initial = initial_values(record, self.existing)
        self.single_picker = ClassificationPicker(categories, initial)
        from core.fault_components import parse_components

        components = parse_components(initial.get(COMPONENT_FIELD))
        if not components and all(initial.get(key) for key in FIELDS):
            components = [{key: initial[key] for key in FIELDS}]
        self.component_picker = ComponentPicker(categories, components)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.single_picker)
        multiple_content = QWidget()
        multiple_layout = QVBoxLayout(multiple_content)
        multiple_layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            "동시에 발생한 서로 다른 유형을 2개 이상 선택하세요. 모호한 후보를 모두 확정하지 마세요."
        )
        note.setWordWrap(True)
        multiple_layout.addWidget(note)
        multiple_layout.addWidget(self.component_picker)
        multiple_layout.addStretch()
        self.stack.addWidget(multiple_content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.stack)
        scroll.setMinimumHeight(150)
        outer.addWidget(scroll, 1)
        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        initial_multiple = (
            bool(self.existing.get(COMPONENT_FIELD))
            or record.get("classification_mode") == "multiple"
        )
        self.mode_combo.setCurrentIndex(1 if initial_multiple else 0)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #a52a2a;")
        outer.addWidget(self.error)
        help_label = QLabel(
            "적용하면 이 기록의 분류만 사용자확정됩니다. 취소·Esc는 변경 내용을 저장하지 않습니다."
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
        self.apply_button = QPushButton("적용")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.apply_button)
        outer.addLayout(buttons)
        self.resize(850, 430 if initial_multiple else 340)

    def show_at(self, position: QPoint):
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            self.setMinimumWidth(min(660, available.width()))
            self.resize(
                min(self.width(), available.width()), min(self.height(), available.height())
            )
            position.setX(
                max(available.left(), min(position.x(), available.right() - self.width() + 1))
            )
            position.setY(
                max(available.top(), min(position.y(), available.bottom() - self.height() + 1))
            )
        self.move(position)
        self.show()
        self.mode_combo.setFocus()

    def apply(self):
        try:
            components = (
                self.component_picker.values()
                if self.mode_combo.currentData() == "multiple"
                else []
            )
            patch = classification_patch(
                self.record,
                self.existing,
                self.mode_combo.currentData(),
                self.single_picker.value(),
                components,
            )
            self._save(patch)
        except (UserError, ValueError, TypeError) as exc:
            self.error.setText(str(exc))

    def clear_classification(self):
        patch = {key: None for key in (*FIELDS, COMPONENT_FIELD) if key in self.existing}
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
            editor.activated.connect(lambda _: self.commitData.emit(editor))
            editor.activated.connect(
                lambda _: self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            )
            self.active_editor = editor
            editor.setProperty("edit_record", index.data(RECORD_ROLE))
            return editor
        editor = QLineEdit(parent)
        editor.setFrame(False)
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
        model.setData(index, value, Qt.ItemDataRole.EditRole)

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
