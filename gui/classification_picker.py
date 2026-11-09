"""Select complete classification paths from the currently enabled rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.models import UserError

FIELDS = ("major", "middle", "minor")
LABELS = {"major": "대분류(분야)", "middle": "중분류(부품 종류)", "minor": "소분류(증상)"}


class ClassificationPicker(QWidget):
    """A cascade that retains a record's old path without offering arbitrary text entry."""

    changed = Signal()

    def __init__(
        self,
        categories: Sequence[tuple[str, str, str]],
        value: Mapping[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.categories = list(categories)
        original = tuple(str((value or {}).get(key, "")).strip() for key in FIELDS)
        self.legacy = original if any(original) and original not in self.categories else None
        self.paths = self.categories + ([self.legacy] if self.legacy else [])
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.combos = {}
        for index, key in enumerate(FIELDS):
            combo = QComboBox()
            combo.setObjectName(f"classification_{key}")
            combo.setEditable(False)
            combo.setMinimumContentsLength(7)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setAccessibleName(LABELS[key])
            combo.currentIndexChanged.connect(lambda _, level=index: self._selection_changed(level))
            self.combos[key] = combo
            row.addWidget(combo, 1 if index < 2 else 2)
        layout.addLayout(row)
        self.legacy_note = QLabel(
            "기존 분류가 현재 활성 규칙 목록에 없습니다. 기존값은 유지되며, 새 분류는 목록에서 선택하세요."
        )
        self.legacy_note.setWordWrap(True)
        self.legacy_note.setObjectName("muted")
        layout.addWidget(self.legacy_note)
        self.set_value(dict(zip(FIELDS, original)))

    def _fill(self, level: int, prefix: tuple[str, ...], selected: str = ""):
        key = FIELDS[level]
        combo = self.combos[key]
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(f"{LABELS[key]} 선택", "")
        choices = sorted(
            {path[level] for path in self.paths if path[:level] == prefix and path[level]},
            key=lambda text: (text.casefold(), text),
        )
        for choice in choices:
            path_prefix = (*prefix, choice)
            active = any(path[: level + 1] == path_prefix for path in self.categories)
            combo.addItem(choice if active else f"[기존값] {choice}", choice)
        found = combo.findData(selected)
        combo.setCurrentIndex(found if found >= 0 else 0)
        combo.setEnabled(level == 0 or all(prefix))
        combo.blockSignals(False)

    def _refresh_note(self):
        selected = tuple(self.value()[key] for key in FIELDS)
        self.legacy_note.setVisible(bool(self.legacy and selected == self.legacy))
        for combo in self.combos.values():
            combo.setToolTip(str(combo.currentData() or combo.currentText()))

    def _selection_changed(self, level: int):
        if self._updating:
            return
        self._updating = True
        for child in range(level + 1, len(FIELDS)):
            prefix = tuple(str(self.combos[key].currentData() or "") for key in FIELDS[:child])
            self._fill(child, prefix)
        self._updating = False
        self._refresh_note()
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {key: str(combo.currentData() or "") for key, combo in self.combos.items()}

    def set_value(self, value: Mapping[str, str]):
        """Set an available path without treating initialization as user confirmation."""
        selected = tuple(str(value.get(key, "")).strip() for key in FIELDS)
        if any(selected) and selected not in self.paths:
            raise UserError("현재 활성 규칙 목록에서 대·중·소분류를 선택하세요.")
        self._updating = True
        for level in range(len(FIELDS)):
            self._fill(level, selected[:level], selected[level])
        self._updating = False
        self._refresh_note()


class ComponentPicker(QWidget):
    """Each affected type is another complete path selected from the same catalog."""

    def __init__(self, categories, components=(), parent=None):
        super().__init__(parent)
        self.categories = list(categories)
        self.pickers: list[ClassificationPicker] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.rows = QVBoxLayout()
        layout.addLayout(self.rows)
        self.add_button = QPushButton("유형 추가")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda: self.add_row())
        layout.addWidget(self.add_button)
        for component in components:
            self.add_row(component)

    def add_row(self, value=None) -> ClassificationPicker:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        picker = ClassificationPicker(self.categories, value, row)
        row_layout.addWidget(picker, 1)
        picker.remove_button = QPushButton("삭제")
        picker.remove_button.setAutoDefault(False)
        picker.remove_button.clicked.connect(lambda: self.remove_row(picker))
        row_layout.addWidget(picker.remove_button)
        self.rows.addWidget(row)
        self.pickers.append(picker)
        return picker

    def remove_row(self, picker: ClassificationPicker):
        if picker not in self.pickers:
            return
        self.pickers.remove(picker)
        row = picker.parentWidget()
        self.rows.removeWidget(row)
        row.hide()
        row.deleteLater()

    def clear(self):
        for picker in list(self.pickers):
            self.remove_row(picker)

    def values(self) -> list[dict[str, str]]:
        components = []
        for number, picker in enumerate(self.pickers, 1):
            value = picker.value()
            if not any(value.values()):
                continue
            if not all(value.values()):
                raise UserError(f"복수 유형 {number}행: 대·중·소분류를 모두 선택하세요.")
            components.append(value)
        return components
