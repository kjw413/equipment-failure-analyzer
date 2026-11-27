"""Select complete classification paths from the currently enabled rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.corrections import COMPONENT_FIELD
from core.failure_modes import CLASSIFICATION_SCHEMA, UNKNOWN_SYMPTOM, manual_category
from core.fault_components import PUBLIC_CATEGORY_FIELDS, parse_components
from core.models import UserError
from core.public_taxonomy import REPAIR_ACTIONS
from gui.category_index import category_index

FIELDS = PUBLIC_CATEGORY_FIELDS
LABELS = {
    "major": "고장 분야",
    "detail_equipment": "상세설비·모듈",
    "minor": "고장 현상",
}


class ClassificationPicker(QWidget):
    """Select the fields of one detailed-equipment fault."""

    changed = Signal()

    def __init__(
        self,
        categories: Sequence[tuple[str, ...]],
        value: Mapping[str, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.index = category_index(categories)
        self.categories = self.index.paths
        original = tuple(str((value or {}).get(key, "")).strip() for key in FIELDS)
        self.legacy = original if any(original) and not self.index.matches(original) else None
        self.paths = self.categories + ((self.legacy,) if self.legacy else ())
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.combos = {}

        def add_selector(label, combo, stretch=1):
            column = QVBoxLayout()
            column.setSpacing(3)
            column.addWidget(QLabel(label))
            column.addWidget(combo)
            row.addLayout(column, stretch)

        for index, key in enumerate(FIELDS):
            combo = QComboBox()
            combo.setObjectName(f"classification_{key}")
            combo.setMinimumContentsLength(7)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setAccessibleName(LABELS[key])
            combo.currentIndexChanged.connect(lambda _, level=index: self._selection_changed(level))
            self.combos[key] = combo
            add_selector(LABELS[key], combo, 2 if key == "minor" else 1)
        layout.addLayout(row)
        self.legacy_note = QLabel(
            "기존 분류가 현재 활성 규칙 목록에 없습니다. 기존값은 유지되며, 새 분류는 목록에서 선택하세요."
        )
        self.legacy_note.setWordWrap(True)
        self.legacy_note.setObjectName("muted")
        layout.addWidget(self.legacy_note)
        equipment_note = QLabel(
            "고장 분야·상세설비·고장 현상을 선택하세요. 조치는 별도로 기록합니다."
        )
        equipment_note.setWordWrap(True)
        equipment_note.setObjectName("muted")
        layout.addWidget(equipment_note)
        self.set_value(dict(zip(FIELDS, original)))

    def _fill(self, level: int, values: Mapping[str, str]):
        key = FIELDS[level]
        combo = self.combos[key]
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(f"{LABELS[key]} 선택", "")
        active_choices = self.index.menu_choices(key, values)
        choices = set(active_choices)
        if (
            self.legacy
            and self.index.menu_context_matches(key, self.legacy, values)
            and self.legacy[level]
        ):
            choices.add(self.legacy[level])
        choices = sorted(choices, key=lambda text: (text.casefold(), text))
        for choice in choices:
            active = choice in active_choices
            combo.addItem(choice if active else f"[기존값] {choice}", choice)
        found = combo.findData(values.get(key, ""))
        combo.setCurrentIndex(found if found >= 0 else 0)
        combo.setEnabled(self.index.menu_enabled(key, values))
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
        values = self.value()
        values = self.index.changed_selection(values, FIELDS[level], values[FIELDS[level]])
        for child in range(len(FIELDS)):
            self._fill(child, values)
        self._updating = False
        self._refresh_note()
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {key: str(combo.currentData() or "") for key, combo in self.combos.items()}

    def set_value(self, value: Mapping[str, str]):
        """Set an available path without treating initialization as user confirmation."""
        selected = tuple(str(value.get(key, "")).strip() for key in FIELDS)
        legacy_match = self.legacy and all(
            not value or value == self.legacy[level] for level, value in enumerate(selected)
        )
        if any(selected) and not legacy_match and not self.index.matches(selected):
            raise UserError("현재 활성 규칙 목록에서 고장 분야·상세설비·고장 현상을 선택하세요.")
        self._updating = True
        for level in range(len(FIELDS)):
            self._fill(level, dict(zip(FIELDS, selected)))
        self._updating = False
        self._refresh_note()

    def validate_path(self):
        value = self.value()
        if not all(value.values()):
            raise UserError("고장 분야·상세설비·고장 현상을 모두 선택하세요.")
        if value["minor"] in (UNKNOWN_SYMPTOM, "증상 미기재", "현상 미기재", *REPAIR_ACTIONS):
            raise UserError(
                "현상 미기재는 최종 분류로 확정할 수 없습니다. 실제 고장 현상을 선택하세요."
            )
        if tuple(value[key] for key in FIELDS) not in self.index:
            raise UserError(
                "현재 활성 분류 목록에서 올바른 고장 분야·상세설비·고장 현상을 선택하세요."
            )
        return value

    def select_candidate(self, candidate):
        value = {key: str(candidate.get(key, "")).strip() for key in FIELDS}
        if value["minor"] in (UNKNOWN_SYMPTOM, "증상 미기재", "현상 미기재", *REPAIR_ACTIONS):
            value["minor"] = ""
        self.set_value(value)


class RepairActionsPicker(QWidget):
    """Store multiple standard actions separately from the observed failure."""

    changed = Signal()

    def __init__(self, value="", parent=None):
        super().__init__(parent)
        self._original = ""
        self._changed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.checkboxes = {}
        for action in REPAIR_ACTIONS:
            checkbox = QCheckBox(action)
            checkbox.toggled.connect(self._toggled)
            self.checkboxes[action] = checkbox
            row.addWidget(checkbox)
        row.addStretch()
        layout.addLayout(row)
        self.legacy_note = QLabel()
        self.legacy_note.setWordWrap(True)
        self.legacy_note.setObjectName("muted")
        layout.addWidget(self.legacy_note)
        self.set_value(value)

    def set_value(self, value):
        self._original = str(value or "").strip()
        selected = {item.strip() for item in self._original.split(",") if item.strip()}
        for action, checkbox in self.checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(action in selected)
            checkbox.blockSignals(False)
        legacy = selected.difference(self.checkboxes)
        self.legacy_note.setText(
            "기존 조치: " + self._original + " · 수정하면 선택한 표준 조치로 저장됩니다."
            if legacy
            else ""
        )
        self.legacy_note.setVisible(bool(legacy))
        self._changed = False

    def _toggled(self, _):
        self._changed = True
        self.legacy_note.hide()
        self.changed.emit()

    def value(self):
        if not self._changed:
            return self._original
        return ", ".join(
            action for action, checkbox in self.checkboxes.items() if checkbox.isChecked()
        )


def record_candidates(record, existing=None):
    """Keep recommendations and former multi-valued saves separate from the final value."""
    from core.classification_candidates import parse_candidates

    candidates = []
    existing = existing or {}
    legacy = parse_components(existing.get(COMPONENT_FIELD))
    if not legacy and record.get("classification_mode") == "multiple":
        legacy = parse_components(record.get("component_details"))
    seen = set()
    for item in parse_candidates(record.get("classification_candidates")) + legacy:
        if (
            not item.get("detail_equipment")
            and record.get("classification_schema") == CLASSIFICATION_SCHEMA
        ):
            item = manual_category(item, existing.get("classification_schema"))
        path = tuple(item.get(key, "") for key in FIELDS)
        if path in seen:
            continue
        candidates.append(
            {
                **item,
                "rank": len(candidates) + 1,
                "reason": item.get("reason") or "이전 확정값입니다. 최종 분류를 다시 선택하세요.",
            }
        )
        seen.add(path)
    return candidates


class CandidateListPicker(QWidget):
    """Evidence-based ranked suggestions; opening this list never chooses a winner."""

    selected = Signal(dict)

    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.candidates = list(candidates)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("분류 후보 · 근거 기반 추천 순위")
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)
        note = QLabel(
            "후보 한 건을 선택하거나 아래 목록에서 직접 분류하세요. 적용 전에는 저장되지 않습니다."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.table = QTableWidget(len(self.candidates), len(FIELDS) + 2)
        self.table.setObjectName("classificationCandidates")
        self.table.setHorizontalHeaderLabels(
            ["순위", *(LABELS[key] for key in FIELDS), "추천 사유 · 근거"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            len(FIELDS) + 1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setWordWrap(True)
        self.table.setMinimumHeight(175)
        self.table.setMaximumHeight(270)
        for row, candidate in enumerate(self.candidates):
            reasons = [str(candidate.get(key) or "").strip() for key in ("reason", "evidence")]
            if candidate.get("detail_equipment_evidence"):
                source = str(candidate.get("detail_equipment_source") or "기록")
                reasons.append(f"상세설비 근거({source}): {candidate['detail_equipment_evidence']}")
            if candidate.get("rule_id"):
                reasons.append("규칙: " + str(candidate["rule_id"]))
            actions = candidate.get("actions")
            if actions:
                reasons.append(
                    "조치: "
                    + (", ".join(map(str, actions)) if isinstance(actions, list) else str(actions))
                )
            reason = "\n".join(dict.fromkeys(text for text in reasons if text))
            values = [
                str(candidate.get("rank") or row + 1),
                *(str(candidate.get(key) or "") for key in FIELDS),
                reason,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                if column == 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, cell)
            self.table.setRowHeight(row, 70)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)
        if not self.candidates:
            note.setText(
                "추천 후보가 없습니다. 아래 선택 목록에서 최종 분류 한 건을 직접 선택하세요."
            )

    def _selection_changed(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.candidates) and self.table.selectedItems():
            self.selected.emit(dict(self.candidates[row]))
