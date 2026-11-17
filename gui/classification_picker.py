"""Select complete classification paths from the currently enabled rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
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
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.models import UserError
from core.public_taxonomy import REPAIR_ACTIONS, part_group
from gui.category_index import category_index

FIELDS = CATEGORY_FIELDS
LABELS = {
    "major": "고장 분야",
    "detail_equipment": "상세설비·모듈",
    "middle": "세부 부품",
    "minor": "고장 현상",
}


class ClassificationPicker(QWidget):
    """Select independent semantic fields, using a derived group to browse parts."""

    changed = Signal()

    def __init__(
        self,
        categories: Sequence[tuple[str, str, str, str]],
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
        self._group_filter = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.group_combo = QComboBox()
        self.group_combo.setObjectName("classification_part_group")
        self.group_combo.setAccessibleName("부품군 탐색")
        self.group_combo.setMinimumContentsLength(7)
        self.group_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.group_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.group_combo.addItem("부품군 전체", "")
        for group in sorted({part_group(name) for name in self.index.menu_choices("middle", {})}):
            if group:
                self.group_combo.addItem(group, group)
        self.group_combo.setToolTip(
            "부품 목록을 좁히는 탐색 필터입니다. 부품을 선택하면 부품군이 자동 표시됩니다."
        )
        self.group_combo.currentIndexChanged.connect(self._group_changed)
        self.combos = {}
        self._part_completion_model = QStringListModel(
            list(self.index.menu_choices("middle", {})), self
        )

        def add_selector(label, combo, stretch=1):
            column = QVBoxLayout()
            column.setSpacing(3)
            column.addWidget(QLabel(label))
            column.addWidget(combo)
            row.addLayout(column, stretch)

        for index, key in enumerate(FIELDS):
            combo = QComboBox()
            combo.setObjectName(f"classification_{key}")
            combo.setEditable(key == "middle")
            if key == "middle":
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                completer = QCompleter(self._part_completion_model, combo)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                completer.setFilterMode(Qt.MatchFlag.MatchContains)
                completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                combo.setCompleter(completer)
                completer.activated[str].connect(self._complete_part)
            combo.setMinimumContentsLength(7)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setAccessibleName(LABELS[key])
            combo.currentIndexChanged.connect(lambda _, level=index: self._selection_changed(level))
            self.combos[key] = combo
            if key == "middle":
                add_selector("부품군 · 탐색", self.group_combo)
            add_selector(LABELS[key], combo, 2 if key == "minor" else 1)
        layout.addLayout(row)
        self.legacy_note = QLabel(
            "기존 분류가 현재 활성 규칙 목록에 없습니다. 기존값은 유지되며, 새 분류는 목록에서 선택하세요."
        )
        self.legacy_note.setWordWrap(True)
        self.legacy_note.setObjectName("muted")
        layout.addWidget(self.legacy_note)
        equipment_note = QLabel(
            "설비 → 부품 → 고장 현상 → 분야 확인 순서로 입력할 수 있습니다. 각 항목은 독립 선택이며 부품군은 탐색 필터입니다. 조치는 별도로 기록합니다."
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
        if key == "middle" and self._group_filter:
            choices = {name for name in choices if part_group(name) == self._group_filter}
            if values.get(key) in active_choices:
                choices.add(values[key])
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
        if key == "middle":
            combo.completer().setModel(self._part_completion_model)
        combo.blockSignals(False)

    def _group_changed(self, _=None):
        if self._updating:
            return
        self._group_filter = str(self.group_combo.currentData() or "")
        self._fill(FIELDS.index("middle"), self.value())

    def _sync_group(self, part):
        self._group_filter = part_group(part) if part else ""
        self.group_combo.blockSignals(True)
        self.group_combo.setCurrentIndex(max(0, self.group_combo.findData(self._group_filter)))
        self.group_combo.blockSignals(False)

    def _complete_part(self, name):
        if name not in self.index.menu_choices("middle", {}):
            return
        values = self.value()
        values["middle"] = name
        self._updating = True
        self._sync_group(name)
        for level in range(len(FIELDS)):
            self._fill(level, values)
        self._updating = False
        self._refresh_note()
        self.changed.emit()

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
        if FIELDS[level] == "middle":
            self._sync_group(values["middle"])
        for child in range(len(FIELDS)):
            self._fill(child, values)
        self._updating = False
        self._refresh_note()
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {
            key: str(combo.currentData() or "")
            if not combo.isEditable() or combo.currentText() == combo.itemText(combo.currentIndex())
            else ""
            for key, combo in self.combos.items()
        }

    def set_value(self, value: Mapping[str, str]):
        """Set an available path without treating initialization as user confirmation."""
        selected = tuple(str(value.get(key, "")).strip() for key in FIELDS)
        legacy_match = self.legacy and all(
            not value or value == self.legacy[level] for level, value in enumerate(selected)
        )
        if any(selected) and not legacy_match and not self.index.matches(selected):
            raise UserError(
                "현재 활성 규칙 목록에서 분야·상세설비·세부 부품·고장 현상을 선택하세요."
            )
        self._updating = True
        self._sync_group(value.get("middle", ""))
        for level in range(len(FIELDS)):
            self._fill(level, dict(zip(FIELDS, selected)))
        self._updating = False
        self._refresh_note()

    def validate_path(self):
        value = self.value()
        if not all(value.values()):
            raise UserError("분야·상세설비·세부 부품·고장 현상을 모두 선택하세요.")
        if value["minor"] in (UNKNOWN_SYMPTOM, "증상 미기재", "현상 미기재", *REPAIR_ACTIONS):
            raise UserError(
                "현상 미기재는 최종 분류로 확정할 수 없습니다. 실제 고장 현상을 선택하세요."
            )
        if tuple(value[key] for key in FIELDS) not in self.index:
            raise UserError(
                "현재 활성 분류 목록에서 올바른 분야·상세설비·세부 부품·고장 현상을 선택하세요."
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

    candidates = parse_candidates(record.get("classification_candidates"))
    existing = existing or {}
    legacy = parse_components(existing.get(COMPONENT_FIELD))
    if not legacy and record.get("classification_mode") == "multiple":
        legacy = parse_components(record.get("component_details"))
    seen = {tuple(item.get(key, "") for key in FIELDS) for item in candidates}
    for item in legacy:
        if record.get("classification_schema") == CLASSIFICATION_SCHEMA:
            item = manual_category(item, existing.get("classification_schema"))
        path = tuple(item.get(key, "") for key in FIELDS)
        if path in seen:
            continue
        candidates.append(
            {
                **item,
                "rank": len(candidates) + 1,
                "reason": "이전 복수 확정값입니다. 최종 분류 한 건을 다시 선택하세요.",
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
