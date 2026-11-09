from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.classification_catalog import fault_catalog_categories
from core.config import ConfigStore
from core.corrections import (
    COMPONENT_FIELD,
    correction_patch,
    initial_values,
    shown,
    validate,
)
from core.equipment_names import (
    code_key,
    effective_name_source,
    equipment_catalog,
    normalize_name_settings,
    organization_catalog,
    resolve_group,
    validate_names,
)
from core.fault_components import component_evidence_text, mode_label, parse_components
from core.i18n import FIELD_LABELS, K
from core.models import UserError
from core.rules import RULE_COLUMNS, read_rules, write_rules
from gui.classification_picker import ClassificationPicker, ComponentPicker


class EquipmentNamesDialog(QDialog):
    """Keep line/equipment mappings separate and flush pending edits before switching."""

    saved = Signal()

    def __init__(self, store: ConfigStore, loaded=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.loaded = loaded
        self.changed = False
        self.snapshot = normalize_name_settings(store.read("equipment_names.json"))
        self.source = self.snapshot["source"]
        self.catalog = {}
        self.organization_catalog = {}
        self._removed_organization_codes = set()
        self._loading = False
        self.setWindowTitle(K["name_editor"])
        self.resize(1380, 760)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self.save_silently)
        layout = QVBoxLayout(self)
        for text in (
            "명명 기준을 선택한 뒤 코드별 보고서 설비명을 입력하세요. "
            "라인 코드(C열)와 설비 코드(E열)의 이름은 각각 저장됩니다.",
            "입력 원본은 보존됩니다. 변환명이 없으면 코드 또는 원본 이름을 표시합니다. "
            "라인 기준에서 빈 라인코드를 설비코드로 대신하지 않습니다.",
            "서로 다른 코드의 보고서 설비명은 다르게 입력하세요. "
            "설비군은 A#1·A#2 → A처럼 같은 이름으로 묶을 수 있습니다.",
            "공장은 원본 라인명의 [공장명]을 자동 표시합니다. "
            "공장·팀을 직접 입력하면 우선 적용하며, 공장을 비우면 자동값으로 돌아갑니다.",
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            layout.addWidget(label)
        source_bar = QHBoxLayout()
        source_bar.addWidget(QLabel("보고서 명명 기준"))
        self.source_combo = QComboBox()
        self.source_combo.addItem("라인 코드 기준 (C열)", "line")
        self.source_combo.addItem("설비 코드 기준 (E열 · 기존 설정)", "equipment")
        self.source_combo.setCurrentIndex(self.source_combo.findData(self.source))
        self.source_combo.currentIndexChanged.connect(self.change_source)
        source_bar.addWidget(self.source_combo)
        self.source_note = QLabel()
        self.source_note.setWordWrap(True)
        source_bar.addWidget(self.source_note, 1)
        layout.addLayout(source_bar)
        grouping_bar = QHBoxLayout()
        grouping_bar.addWidget(QLabel("설비군 규칙"))
        self.group_mode = QComboBox()
        self.group_mode.addItem("구분자 앞 이름", "prefix")
        self.group_mode.addItem("보고서 설비명 그대로", "none")
        self.group_mode.currentIndexChanged.connect(self.group_rule_changed)
        grouping_bar.addWidget(self.group_mode)
        grouping_bar.addWidget(QLabel("구분자"))
        self.group_separator = QLineEdit("#")
        self.group_separator.setMaximumWidth(110)
        self.group_separator.setMaxLength(20)
        self.group_separator.textEdited.connect(self.group_rule_changed)
        grouping_bar.addWidget(self.group_separator)
        group_help = QLabel("설비군 열에서 개별 지정할 수 있습니다. 비우면 규칙을 적용합니다.")
        group_help.setWordWrap(True)
        grouping_bar.addWidget(group_help, 1)
        layout.addLayout(grouping_bar)
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(2, 230)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 160)
        self.table.verticalHeader().setDefaultSectionSize(43)
        layout.addWidget(self.table)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        path = QLabel(str(store.config_dir / "equipment_names.json"))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setObjectName("muted")
        path.setWordWrap(True)
        layout.addWidget(path)
        buttons = QHBoxLayout()
        add = QPushButton(K["add_code"])
        add.clicked.connect(self.add_empty)
        delete = QPushButton(K["delete"])
        delete.clicked.connect(self.delete_rows)
        restore = QPushButton("마지막 저장값 불러오기")
        restore.clicked.connect(self.reload_saved)
        close = QPushButton(K["close"])
        close.clicked.connect(self.accept)
        for button in (add, delete, restore, close):
            button.setAutoDefault(False)
        buttons.addWidget(add)
        buttons.addWidget(delete)
        buttons.addWidget(restore)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.reload_saved()

    @staticmethod
    def mapping_key(source):
        return "line_mappings" if source == "line" else "mappings"

    def grouping_rule(self):
        return {
            "mode": self.group_mode.currentData(),
            "separator": self.group_separator.text(),
            "overrides": {},
        }

    @staticmethod
    def row_report_name(key, name):
        return name.text().strip() or code_key(key.text()) or "미기재"

    def add_row(self, code: str, raw_name: str, display: str, read_only: bool):
        row = self.table.rowCount()
        self.table.insertRow(row)
        key = QLineEdit(code)
        saved_code = code_key(code)
        key.setProperty(
            "saved_organization_code",
            saved_code if saved_code in self.snapshot["organization"][self.source] else "",
        )
        key.setReadOnly(read_only)
        key.setPlaceholderText("라인 코드" if self.source == "line" else "IF18115")
        name = QLineEdit(display)
        name.setPlaceholderText("보고서에 표시할 이름")
        name.setStyleSheet("QLineEdit { color: #2155A0; }")
        self.table.setCellWidget(row, 0, key)
        item = QTableWidgetItem(raw_name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(raw_name)
        self.table.setItem(row, 1, item)
        self.table.setCellWidget(row, 2, name)
        group = QLineEdit()
        group.setPlaceholderText("비우면 설비군 규칙 적용")
        group.setToolTip("자동 설비군을 확인하거나 이 이름의 설비군을 직접 지정합니다.")
        self.table.setCellWidget(row, 3, group)
        report_name = self.row_report_name(key, name)
        overrides = self.snapshot["grouping"]["overrides"]
        group.setProperty(
            "manual_group", any(code_key(k) == code_key(report_name) for k in overrides)
        )
        group.setProperty("group_override_cleared", False)
        group.setText(resolve_group(report_name, self.snapshot["grouping"]))
        for edit in (key, name):
            edit.textEdited.connect(
                lambda _text, code_edit=key, name_edit=name, group_edit=group: self.name_edited(
                    code_edit, name_edit, group_edit
                )
            )
        group.textEdited.connect(lambda _text, group_edit=group: self.group_edited(group_edit))
        organization = self.snapshot["organization"][self.source].get(code_key(code), {})
        factory = QLineEdit(organization.get("factory", ""))
        team = QLineEdit(organization.get("team", ""))
        team.setPlaceholderText("직접 입력")
        team.setToolTip("팀을 직접 입력합니다. 비우면 팀 미기재로 표시합니다.")
        self.table.setCellWidget(row, 4, factory)
        self.table.setCellWidget(row, 5, team)
        self.refresh_factory_preview(key, factory)
        key.textEdited.connect(
            lambda _text, code_edit=key, factory_edit=factory: self.refresh_factory_preview(
                code_edit, factory_edit
            )
        )
        factory.textEdited.connect(self.schedule_save)
        team.textEdited.connect(self.schedule_save)

    def refresh_factory_preview(self, key, factory):
        automatic = self.organization_catalog.get(code_key(key.text()), {}).get("factory", "")
        factory.setPlaceholderText("자동: " + automatic if automatic else "자동값 없음 · 직접 입력")
        factory.setToolTip(
            "원본 라인명에서 확인한 공장: "
            + (automatic or "없음 또는 여러 공장")
            + "\n직접 입력하면 우선 적용하며 비우면 자동값을 사용합니다."
        )

    def refresh_group_preview(self, key, name, group):
        if not group.property("manual_group"):
            # Invalid in-progress rules must not discard pending table edits.
            try:
                overrides = (
                    {}
                    if group.property("group_override_cleared")
                    else self.snapshot["grouping"]["overrides"]
                )
                rule = {**self.grouping_rule(), "overrides": overrides}
                report_name = self.row_report_name(key, name)
                group.setText(resolve_group(report_name, rule))
                if any(code_key(k) == code_key(report_name) for k in rule["overrides"]):
                    group.setProperty("manual_group", True)
            except UserError:
                pass

    def name_edited(self, key, name, group):
        self.refresh_group_preview(key, name, group)
        self.schedule_save()

    def group_edited(self, group):
        manual = bool(group.text().strip())
        group.setProperty("manual_group", manual)
        group.setProperty("group_override_cleared", not manual)
        self.schedule_save()

    def group_rule_changed(self, *_):
        if self._loading:
            return
        self.group_separator.setEnabled(self.group_mode.currentData() == "prefix")
        for row in range(self.table.rowCount()):
            self.refresh_group_preview(
                self.table.cellWidget(row, 0),
                self.table.cellWidget(row, 2),
                self.table.cellWidget(row, 3),
            )
        self.schedule_save()

    def reload_saved(self):
        self.timer.stop()
        try:
            snapshot = normalize_name_settings(self.store.read("equipment_names.json"))
            mapping = validate_names(snapshot[self.mapping_key(self.source)])
            catalog = {
                item["code"]: item["raw_name"]
                for item in equipment_catalog(self.loaded, self.source)
            }
            automatic_organization = organization_catalog(self.loaded, self.source)
        except Exception as exc:
            QMessageBox.warning(self, K["error"], str(exc))
            return
        self.snapshot = snapshot
        self.catalog = catalog
        self.organization_catalog = automatic_organization
        self._removed_organization_codes.clear()
        self._loading = True
        self.group_mode.setCurrentIndex(self.group_mode.findData(snapshot["grouping"]["mode"]))
        self.group_separator.setText(snapshot["grouping"]["separator"])
        self.group_separator.setEnabled(self.group_mode.currentData() == "prefix")
        self.source_combo.setCurrentIndex(self.source_combo.findData(self.source))
        self.table.setHorizontalHeaderLabels(
            [
                "라인 코드 (C열)" if self.source == "line" else "설비 코드 (E열)",
                "원본 라인명" if self.source == "line" else K["raw_equipment_name"],
                K["report_equipment"],
                "설비군 · 미리보기 / 개별 지정",
                "공장 · 자동 / 개별 지정",
                "팀 · 개별 지정",
            ]
        )
        self.table.setRowCount(0)
        organization = snapshot["organization"][self.source]
        for key in sorted(set(self.catalog) | set(mapping) | set(organization)):
            self.add_row(key, self.catalog.get(key, ""), mapping.get(key, ""), True)
        if (
            self.loaded is not None
            and snapshot["source"] == "line"
            and effective_name_source(self.loaded, snapshot) == "equipment"
        ):
            self.source_note.setText(
                "이 파일에는 라인 열이 없어 분석에는 설비 코드 기준이 적용됩니다. "
                "아래는 저장된 라인 이름 설정입니다."
            )
        else:
            self.source_note.setText("기준을 바꾸기 전에 현재 입력을 저장합니다.")
        self._loading = False
        self.status.setText(K["autosave"] + " | " + (snapshot.get("updated_at") or "초기 설정"))
        self.status.setStyleSheet("color: #237245;")

    def change_source(self, *_):
        if self._loading:
            return
        source = self.source_combo.currentData()
        if source == self.source:
            return
        if not self.save_silently():
            self.restore_source_selection()
            return
        before = self.snapshot
        try:
            snapshot = self.store.save_equipment_names(
                before[self.mapping_key(source)],
                source=source,
                grouping=before["grouping"],
                organization=before["organization"],
            )
        except Exception as exc:
            self.status.setText(K["save_failed"] + "\n" + str(exc))
            self.status.setStyleSheet("color: #A52A2A;")
            self.restore_source_selection()
            return
        self.source = source
        if before != snapshot:
            self.changed = True
            self.saved.emit()
        self.reload_saved()

    def restore_source_selection(self):
        self.source_combo.blockSignals(True)
        self.source_combo.setCurrentIndex(self.source_combo.findData(self.source))
        self.source_combo.blockSignals(False)

    def add_empty(self):
        self.add_row("", "", "", False)
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.cellWidget(self.table.rowCount() - 1, 0).setFocus()

    def delete_rows(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        for row in rows:
            key_edit = self.table.cellWidget(row, 0)
            key = code_key(key_edit.text())
            self._removed_organization_codes.update(
                (key, code_key(key_edit.property("saved_organization_code") or ""))
            )
            if key in self.catalog:
                self.table.cellWidget(row, 2).clear()
                group = self.table.cellWidget(row, 3)
                group.setProperty("manual_group", False)
                group.setProperty("group_override_cleared", True)
                group.clear()
                self.table.cellWidget(row, 4).clear()
                self.table.cellWidget(row, 5).clear()
            else:
                self.table.removeRow(row)
        if rows:
            self.schedule_save()

    def schedule_save(self, *_):
        self.status.setText(K["saving"])
        self.status.setStyleSheet("color: #65717D;")
        self.timer.start()

    def collect(self):
        values = {}
        for row in range(self.table.rowCount()):
            code = code_key(self.table.cellWidget(row, 0).text())
            name = self.table.cellWidget(row, 2).text().strip()
            if not code and not name:
                group = self.table.cellWidget(row, 3)
                manual_group = group.property("manual_group") and group.text().strip()
                organization = any(self.table.cellWidget(row, col).text().strip() for col in (4, 5))
                if not manual_group and not organization:
                    continue
            if not code:
                raise UserError(f"{row + 1}: 코드를 입력하세요.")
            if code in values:
                raise UserError("같은 코드가 두 번 입력되었습니다: " + code)
            values[code] = name
        return validate_names(values)

    def collect_grouping(self):
        grouping = self.grouping_rule()
        overrides = dict(self.snapshot["grouping"]["overrides"])
        for row in range(self.table.rowCount()):
            key, name = self.table.cellWidget(row, 0), self.table.cellWidget(row, 2)
            if not key.text().strip() and not name.text().strip():
                continue
            report_name = self.row_report_name(key, name)
            group = self.table.cellWidget(row, 3)
            for old in list(overrides):
                if code_key(old) == code_key(report_name):
                    overrides.pop(old)
            value = group.text().strip()
            if group.property("manual_group") and value:
                overrides[report_name] = value
        return {**grouping, "overrides": overrides}

    def collect_organization(self):
        organization = {
            source: dict(codes) for source, codes in self.snapshot["organization"].items()
        }
        current = organization[self.source]
        for code in self._removed_organization_codes:
            current.pop(code, None)
        # Remove previous identities before writing any new ones, including code swaps.
        for row in range(self.table.rowCount()):
            key = self.table.cellWidget(row, 0)
            saved_code = code_key(key.property("saved_organization_code") or "")
            if saved_code and saved_code != code_key(key.text()):
                current.pop(saved_code, None)
        for row in range(self.table.rowCount()):
            code = code_key(self.table.cellWidget(row, 0).text())
            if not code:
                continue
            values = {
                field: self.table.cellWidget(row, column).text().strip()
                for field, column in (("factory", 4), ("team", 5))
                if self.table.cellWidget(row, column).text().strip()
            }
            if values:
                current[code] = values
            else:
                current.pop(code, None)
        return organization

    def save_silently(self) -> bool:
        self.timer.stop()
        try:
            values = self.collect()
            grouping = self.collect_grouping()
            organization = self.collect_organization()
            before = normalize_name_settings(self.store.read("equipment_names.json"))
            snapshot = self.store.save_equipment_names(
                values, source=self.source, grouping=grouping, organization=organization
            )
        except Exception as exc:
            self.status.setText(K["save_failed"] + "\n" + str(exc))
            self.status.setStyleSheet("color: #A52A2A;")
            return False
        self.snapshot = normalize_name_settings(snapshot)
        self._removed_organization_codes.clear()
        for row in range(self.table.rowCount()):
            key = self.table.cellWidget(row, 0)
            code = code_key(key.text())
            key.setProperty(
                "saved_organization_code",
                code if code in self.snapshot["organization"][self.source] else "",
            )
            self.table.cellWidget(row, 3).setProperty("group_override_cleared", False)
            self.refresh_group_preview(
                self.table.cellWidget(row, 0),
                self.table.cellWidget(row, 2),
                self.table.cellWidget(row, 3),
            )
        self.status.setText(K["autosave"] + " | " + datetime.now().strftime("%H:%M:%S"))
        self.status.setStyleSheet("color: #237245;")
        if before != self.snapshot:
            self.changed = True
            self.saved.emit()
        return True

    def done(self, result):
        # Always flush the last text on close, including X/ESC during debounce.
        if not self.save_silently():
            QMessageBox.warning(self, K["error"], self.status.text())
            return
        super().done(result)


class ColumnMappingDialog(QDialog):
    def __init__(self, loaded, parent=None):
        super().__init__(parent)
        self.setWindowTitle(K["mapping"])
        self.resize(720, 670)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(loaded.mapping), 2)
        self.table.setHorizontalHeaderLabels(
            ["\ud504\ub85c\uadf8\ub7a8 \ud56d\ubaa9", "Excel \uc5f4"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fields = list(loaded.mapping)
        for row, key in enumerate(self.fields):
            item = QTableWidgetItem(FIELD_LABELS.get(key, key))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            combo = QComboBox()
            combo.addItem(K["unmapped"], None)
            for column in loaded.headers:
                combo.addItem(column, column)
            index = combo.findData(loaded.mapping[key])
            combo.setCurrentIndex(max(0, index))
            self.table.setCellWidget(row, 1, combo)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mapping(self):
        return {
            key: self.table.cellWidget(row, 1).currentData() for row, key in enumerate(self.fields)
        }


class RuleEditor(QDialog):
    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.path = store.config_dir / "classification_config.xlsx"
        self.changed = False
        self.setWindowTitle(K["rules"])
        self.resize(1250, 630)
        layout = QVBoxLayout(self)
        note = QLabel(K["rule_help"])
        note.setWordWrap(True)
        layout.addWidget(note)
        rules = read_rules(self.path)
        self.table = QTableWidget(len(rules), len(RULE_COLUMNS))
        rule_labels = {"major": "분야", "middle": "부품군", "minor": "부품 종류"}
        self.table.setHorizontalHeaderLabels([rule_labels.get(key, key) for key in RULE_COLUMNS])
        self.table.setAlternatingRowColors(True)
        for row, rule in enumerate(rules):
            for col, key in enumerate(RULE_COLUMNS):
                value = int(rule[key]) if key == "enabled" else rule[key]
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        for col in range(len(RULE_COLUMNS)):
            self.table.setColumnWidth(col, 230 if 5 <= col <= 8 else 120)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton(K["add"])
        add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        delete = QPushButton(K["delete"])
        delete.clicked.connect(self.delete)
        save = QPushButton(K["save"])
        save.clicked.connect(self.save)
        cancel = QPushButton(K["cancel"])
        cancel.clicked.connect(self.reject)
        buttons.addWidget(add)
        buttons.addWidget(delete)
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def delete(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def save(self):
        rows = []
        for row in range(self.table.rowCount()):
            rows.append(
                {
                    key: self.table.item(row, col).text() if self.table.item(row, col) else ""
                    for col, key in enumerate(RULE_COLUMNS)
                }
            )
        try:
            write_rules(self.path, rows)
        except Exception as exc:
            QMessageBox.warning(self, K["error"], str(exc))
            return
        self.changed = True
        self.accept()


class CorrectionDialog(QDialog):
    """Saves only what the user changed; [수동 보정 해제] removes every saved field of the record."""

    def __init__(self, record: dict, existing: dict | None = None, parent=None, *, rules=None):
        super().__init__(parent)
        self.existing = {k: v for k, v in (existing or {}).items() if k != "saved_at"}
        self.initial = initial_values(record, self.existing)
        self.categories = fault_catalog_categories(rules or [])
        self.patch = {}
        self.cleared = False
        self.setWindowTitle(K["correct"])
        self.resize(900, 850)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        note = QLabel(
            K["correction_help"] + "\n일치한 규칙과 원문 근거를 확인한 뒤 분류를 사용자확정하세요. "
            "저장된 수동 보정은 자동 분류보다 우선합니다."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.diagnostic = QTextEdit()
        self.diagnostic.setReadOnly(True)
        saved = ", ".join(f"{K.get(k, k)}={v}" for k, v in self.existing.items()) or "없음"
        diagnostics = [
            (K["classification_reason"], record.get("classification_reason")),
            (K["candidate_evidence"], record.get("candidate_evidence")),
            ("유형 조합", record.get("component_types")),
            ("조합 판정", mode_label(record.get("classification_mode"))),
            ("구성원별 유형·근거", component_evidence_text(record.get("component_details"))),
            ("검토 사유", record.get("review_reason")),
            ("수정 방법", record.get("review_action")),
            ("현재 집계 영향", record.get("aggregation_effect")),
            ("분류 근거", record.get("evidence")),
            ("후보 규칙", record.get("candidates")),
            ("저장된 수동 보정", saved),
        ]
        self.diagnostic.setPlainText(
            "\n\n".join(f"{label}: {shown(value) or '-'}" for label, value in diagnostics)
        )
        self.diagnostic.setMinimumHeight(165)
        layout.addWidget(self.diagnostic)
        source = QTextEdit()
        source.setReadOnly(True)
        source.setPlainText(str(record.get("raw_description", "")))
        source.setMaximumHeight(120)
        layout.addWidget(source)
        form = QFormLayout()
        self.edits = {}
        self.confirm = QCheckBox("위 대·중·소분류를 사용자확정으로 저장")
        self.confirm.setToolTip(
            "체크하지 않고 분류를 그대로 두면 분류는 저장하지 않습니다. 시간·일자만 고칠 때는 비워 두세요."
        )
        self.classification_picker = ClassificationPicker(self.categories, self.initial)
        self.classification_picker.changed.connect(lambda: self.confirm.setChecked(True))
        form.addRow("단일 유형\n대 → 중 → 소", self.classification_picker)
        form.addRow("", self.confirm)
        self.multiple_confirm = QCheckBox("아래 복수 유형 조합을 사용자확정으로 저장")
        self.multiple_confirm.setToolTip(
            "서로 다른 유형 2개 이상을 목록에서 선택하고 직접 체크한 뒤 저장하세요. "
            "시간만 고칠 때는 체크하지 않습니다."
        )
        self.component_picker = ComponentPicker(
            self.categories, parse_components(self.initial.get(COMPONENT_FIELD))
        )
        self.component_help = QLabel(
            "각 행에서 분야 → 부품 종류 → 증상을 차례로 선택하세요. "
            "동시에 발생한 유형만 선택하며, 모호한 대안을 모두 확정하지 마세요. "
            "복수 확정 체크 후 저장해야 분류에 반영됩니다. "
            "저장된 조합의 행을 모두 삭제하고 저장하면 복수 유형 보정만 해제됩니다."
        )
        self.component_help.setWordWrap(True)
        self.component_help.setObjectName("muted")
        form.addRow("", self.multiple_confirm)
        form.addRow("복수 유형 구성원\n대 → 중 → 소", self.component_picker)
        form.addRow("", self.component_help)
        if not self.categories:
            warning = QLabel(
                "활성 분류 규칙이 없습니다. 기존값은 유지되며, 새 유형을 선택하려면 분류 규칙을 확인하세요."
            )
            warning.setWordWrap(True)
            form.addRow("", warning)
        self.confirm.toggled.connect(self.single_confirmation_changed)
        self.multiple_confirm.toggled.connect(self.multiple_confirmation_changed)
        for key in ("target", "product"):
            edit = QLineEdit(self.initial[key])
            self.edits[key] = edit
            form.addRow(K[key], edit)
        for key, label, value in (
            ("work_date", "확정 작업일자 (YYYY-MM-DD)", record.get("date")),
            ("minutes", "확정 정지시간 (분)", record.get("minutes")),
        ):
            # Empty unless already corrected; the source value is only a hint. Clearing removes it.
            edit = QLineEdit(self.initial[key])
            hint = shown(value)
            edit.setPlaceholderText("원본: " + hint[:19] if hint else "")
            self.edits[key] = edit
            form.addRow(label, edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(K["save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(K["cancel"])
        self.clear_button = buttons.addButton(
            "수동 보정 해제", QDialogButtonBox.ButtonRole.ResetRole
        )
        self.clear_button.setEnabled(bool(self.existing))
        self.clear_button.clicked.connect(self.clear_all)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def single_confirmation_changed(self, checked):
        if checked:
            self.multiple_confirm.setChecked(False)

    def multiple_confirmation_changed(self, checked):
        if checked:
            self.confirm.setChecked(False)
        self.classification_picker.setEnabled(not checked)

    def component_values(self) -> str:
        components = self.component_picker.values()
        return json.dumps(components, ensure_ascii=False) if components else ""

    def values(self):
        values = {key: edit.text().strip() for key, edit in self.edits.items()}
        values.update(self.classification_picker.value())
        if self.multiple_confirm.isChecked():
            values[COMPONENT_FIELD] = self.component_values()
        elif not self.component_picker.pickers:
            values[COMPONENT_FIELD] = ""
        else:
            # Unconfirmed edits must not alter saved classification while correcting time.
            values[COMPONENT_FIELD] = self.initial.get(COMPONENT_FIELD, "")
        return values

    def clear_all(self):
        answer = QMessageBox.question(
            self,
            K["notice"],
            "이 기록에 저장된 수동 보정을 모두 해제하고 원본·규칙 값으로 되돌릴까요?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cleared = True
            self.accept()

    def validate_and_accept(self):
        try:
            values = self.values()
        except UserError as exc:
            QMessageBox.warning(self, K["notice"], str(exc))
            return
        error = validate(values, confirm_components=self.multiple_confirm.isChecked())
        if error:
            QMessageBox.warning(self, K["notice"], error)
            return
        self.patch = correction_patch(
            self.initial,
            values,
            self.existing,
            self.confirm.isChecked(),
            confirm_components=self.multiple_confirm.isChecked(),
        )
        if not self.patch:
            QMessageBox.information(self, K["notice"], "변경된 내용이 없습니다.")
            return
        self.accept()
