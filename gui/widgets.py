from __future__ import annotations

from numbers import Real

import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.corrections import shown
from core.fault_components import component_evidence_text, mode_label
from core.i18n import DISPLAY, K
from core.models import UserError
from core.parsing import is_missing
from core.sorting import default_metric, descending
from gui.classification_picker import FIELDS
from gui.inline_editor import (
    CHOICES_ROLE,
    EDITABLE_COLUMNS,
    MULTIPLE_ROLE,
    RECORD_ROLE,
    CellEditDelegate,
    ClassificationCellEditor,
    classification_patch,
    field_patch,
    field_text,
)
from gui.tasks import Task as Task  # Preserve the existing import path.


class DropArea(QFrame):
    file_dropped = Signal(str)
    browse_requested = Signal()
    invalid_drop = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        self.setMinimumHeight(126)
        layout = QVBoxLayout(self)
        self.title = QLabel(K["drop"])
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setObjectName("dropTitle")
        self.subtitle = QLabel(".xlsx / .xlsm   |   " + K["one_file"])
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setObjectName("muted")
        self.browse_button = QPushButton(K["browse"])
        self.browse_button.setMinimumWidth(190)
        self.browse_button.clicked.connect(self.browse_requested.emit)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.browse_button)
        buttons.addStretch()
        layout.addLayout(buttons)

    def set_compact(self, compact: bool):
        """Make room for analysis after loading; retain the drop target."""
        self.title.setVisible(not compact)
        self.subtitle.setVisible(not compact)
        self.browse_button.setText("다른 파일 선택" if compact else K["browse"])
        self.setMinimumHeight(56 if compact else 126)
        self.setMaximumHeight(60 if compact else 16777215)
        self.setToolTip("다른 Excel 파일을 끌어 놓거나 선택하세요." if compact else "")

    def dragEnterEvent(self, event):
        if self.isEnabled() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) != 1:
            self.invalid_drop.emit(K["one_file"])
            event.ignore()
            return
        if not urls[0].isLocalFile():
            self.invalid_drop.emit(K["unsupported"])
            event.ignore()
            return
        self.file_dropped.emit(urls[0].toLocalFile())
        event.acceptProposedAction()


class FrameModel(QAbstractTableModel):
    def __init__(self, frame: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.frame = frame.reset_index(drop=True).copy()
        self.editing_enabled = False
        self.edit_request = None
        self.draft_provider = lambda record: None
        self.choices_provider = lambda record, column: []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.frame.iat[index.row(), index.column()]
        missing = is_missing(value)
        column = self.frame.columns[index.column()]
        record = None
        if (
            role
            in (
                RECORD_ROLE,
                CHOICES_ROLE,
                MULTIPLE_ROLE,
                Qt.ItemDataRole.EditRole,
                Qt.ItemDataRole.BackgroundRole,
            )
            or column in FIELDS
        ):
            record = self.frame.iloc[index.row()].to_dict()
        if role == RECORD_ROLE:
            return record
        if role == MULTIPLE_ROLE:
            return record.get("classification_mode") == "multiple"
        if role == CHOICES_ROLE:
            return self.choices_provider(record, column)
        if role == Qt.ItemDataRole.EditRole:
            if column in FIELDS:
                draft = self.draft_provider(record)
                return (draft or record).get(column, "")
            return field_text(record, column) if column in EDITABLE_COLUMNS else value
        if (
            role == Qt.ItemDataRole.BackgroundRole
            and self.edit_request
            and column in EDITABLE_COLUMNS
        ):
            draft = self.draft_provider(record)
            return QBrush(QColor("#fff0bd" if draft and column in FIELDS else "#edf5ff"))
        if column in FIELDS and role == Qt.ItemDataRole.DisplayRole and self.edit_request:
            if record.get("classification_mode") == "multiple":
                return "-"
            draft = self.draft_provider(record)
            if draft is not None:
                return draft.get(column) or DISPLAY.get(column, column) + " 선택"
        if role == Qt.ItemDataRole.ToolTipRole and self.edit_request and column in EDITABLE_COLUMNS:
            instruction = "더블클릭 또는 F2로 수정 · Esc로 취소"
            if column in FIELDS:
                instruction += (
                    "\n대 → 중 → 소분류를 모두 선택하면 저장됩니다. 노란 셀은 선택 중입니다."
                )
                instruction += "\n선택 중 Esc를 누르면 이 행의 분류 선택을 취소합니다. 재분석 시 미완성 선택은 초기화됩니다."
            elif column in ("type", "component_types"):
                instruction += "\n목록에서 단일/복수 유형을 선택한 뒤 적용하세요."
            else:
                instruction += "\nEnter/다른 셀 클릭: 저장 · 비우기: 해당 보정 해제"
            return ("" if missing else str(value) + "\n\n") + instruction
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if missing:
                return ""
            column = self.frame.columns[index.column()]
            if column == "classification_mode":
                return mode_label(value)
            if column == "component_details":
                return component_evidence_text(value)
            if isinstance(value, pd.Timestamp):
                return value.strftime("%Y-%m-%d" if column == "date" else "%Y-%m-%d %H:%M:%S")
            if isinstance(value, Real) and not isinstance(value, bool):
                if str(column).endswith("_share"):
                    return f"{value:.1%}"
                return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
            return str(value)
        if role == Qt.ItemDataRole.UserRole:
            if missing:
                return None
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            if hasattr(value, "item"):
                return value.item()
            return value
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and not 0 <= section < len(self.frame.columns):
            return None
        if orientation == Qt.Orientation.Horizontal:
            column = self.frame.columns[section]
            if role == Qt.ItemDataRole.UserRole:
                return column
            if self.edit_request and column in EDITABLE_COLUMNS:
                if role == Qt.ItemDataRole.ToolTipRole:
                    return "직접 수정 가능 · 더블클릭 또는 F2"
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QBrush(QColor("#1c5a91"))
        if (
            role == Qt.ItemDataRole.InitialSortOrderRole
            and orientation == Qt.Orientation.Horizontal
        ):
            # The first click on a numeric header starts with the largest value.
            column = self.frame.columns[section]
            if pd.api.types.is_numeric_dtype(self.frame[column]):
                return Qt.SortOrder.DescendingOrder
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            key = self.frame.columns[section]
            label = DISPLAY.get(key, str(key))
            return label + " · 수정" if self.edit_request and key in EDITABLE_COLUMNS else label
        return str(section + 1)

    def flags(self, index):
        flags = super().flags(index)
        if (
            index.isValid()
            and self.editing_enabled
            and self.edit_request
            and self.frame.columns[index.column()] in EDITABLE_COLUMNS
        ):
            record = self.frame.iloc[index.row()].to_dict()
            if any(shown(record.get(key)) for key in ("event_id", "record_id")):
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not (self.flags(index) & Qt.ItemFlag.ItemIsEditable):
            return False
        record = self.frame.iloc[index.row()].to_dict()
        accepted = self.edit_request(record, self.frame.columns[index.column()], value)
        if accepted:
            self.dataChanged.emit(
                self.index(index.row(), 0), self.index(index.row(), self.columnCount() - 1)
            )
        return accepted


class NumericSortProxy(QSortFilterProxyModel):
    """Sort raw numbers (not formatted strings), with blanks last both ways."""

    def lessThan(self, left_index, right_index):
        left = self.sourceModel().data(left_index, Qt.ItemDataRole.UserRole)
        right = self.sourceModel().data(right_index, Qt.ItemDataRole.UserRole)
        left_missing, right_missing = is_missing(left), is_missing(right)
        descending_order = self.sortOrder() == Qt.SortOrder.DescendingOrder
        if left_missing != right_missing:
            return left_missing if descending_order else not left_missing
        if not left_missing:
            if isinstance(left, Real) and isinstance(right, Real):
                if left != right:
                    return bool(left < right)
            else:
                left_text, right_text = str(left).casefold(), str(right).casefold()
                if left_text != right_text:
                    return left_text < right_text
        # Stable ties preserve the secondary numeric order of the source frame.
        return (
            left_index.row() > right_index.row()
            if descending_order
            else left_index.row() < right_index.row()
        )

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(section + 1)
        return super().headerData(section, orientation, role)


class TablePane(QWidget):
    edit_failed = Signal(str)
    edit_saved = Signal(object, object)

    def __init__(self, parent=None, *, sort_policy: str = "auto", description: str = ""):
        super().__init__(parent)
        self.sort_policy = sort_policy
        self.default_key = None
        self._categories = []
        self._edit_handler = None
        self._override_provider = lambda event_id: {}
        self._editing_enabled = True
        self._classification_drafts = {}
        self.classification_editor = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(K["search"])
        self.sort_hint = QLabel()
        self.sort_hint.setObjectName("muted")
        self.reset_sort_button = QPushButton("큰 값순 정렬")
        self.reset_sort_button.clicked.connect(self.reset_sort)
        self.info = QLabel("0")
        self.info.setObjectName("muted")
        top.addWidget(self.search, 1)
        top.addWidget(self.sort_hint)
        top.addWidget(self.reset_sort_button)
        top.addWidget(self.info)
        self.table = QTableView()
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.proxy = NumericSortProxy(self)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.table.setModel(self.proxy)
        self.edit_delegate = CellEditDelegate(self.table)
        self.table.setItemDelegate(self.edit_delegate)
        self.edit_delegate.classification_requested.connect(self.open_classification_editor)
        self.edit_delegate.draft_cancel_requested.connect(self.cancel_classification_draft)
        # Do not enable sorting on column 0 before installing a numeric default.
        self.search.textChanged.connect(self.filter)
        layout.addLayout(top)
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setObjectName("muted")
        self.description.setVisible(bool(description))
        layout.addWidget(self.description)
        self.edit_status = QLabel()
        self.edit_status.setWordWrap(True)
        self.edit_status.setObjectName("muted")
        self.edit_status.hide()
        layout.addWidget(self.edit_status)
        layout.addWidget(self.table)
        self.set_frame(pd.DataFrame())

    def set_frame(self, frame: pd.DataFrame):
        self.cancel_editing()
        if self._classification_drafts:
            self.edit_status.setText(
                "완료하지 않은 분류 선택은 저장되지 않았습니다. 대·중·소분류를 모두 선택하면 저장됩니다."
            )
            self.edit_status.show()
        self._classification_drafts.clear()
        self.default_key = default_metric(frame) if self.sort_policy == "auto" else None
        prepared = descending(frame, self.default_key) if self.default_key else frame
        if self.sort_policy == "period" and "period" in frame:
            keys = [key for key in ("period", "component_type") if key in frame]
            prepared = frame.sort_values(keys, kind="stable").reset_index(drop=True)
        self.table.setSortingEnabled(False)
        self.proxy.sort(-1)
        old = self.proxy.sourceModel()
        self.model = FrameModel(prepared, self)
        self._configure_model()
        self.proxy.setSourceModel(self.model)
        if old is not None:
            old.deleteLater()
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.DescendingOrder)
        self.table.setSortingEnabled(True)
        for index, column in enumerate(prepared.columns):
            hidden = column in ("record_id", "event_id", "__source_row")
            self.table.setColumnHidden(index, hidden)
            width = (
                270
                if column
                in (
                    "raw_description",
                    "normalized",
                    "issues",
                    "evidence",
                    "classification_reason",
                    "candidate_evidence",
                    "component_type",
                    "component_types",
                    "component_details",
                    "combination_key",
                    "candidates",
                    "raw_equipment_name",
                    "review_reason",
                    "review_action",
                    "aggregation_effect",
                )
                else 180
                if column
                in ("equipment", "target", "registered", "type", "report_equipment", "product")
                else 135
            )
            self.table.setColumnWidth(index, width)
        if self.default_key:
            self.sort_hint.setText(
                "기본: " + DISPLAY.get(self.default_key, self.default_key) + " ↓"
            )
        elif self.sort_policy == "period":
            self.sort_hint.setText("월 ↑ / 유형명 ↑")
            self.reset_sort_button.setText("시간순 정렬")
        elif self.sort_policy == "grouped":
            self.sort_hint.setText("설비 정지시간 ↓ / 설비 내 유형 건수 ↓")
        else:
            self.sort_hint.setText("원본 행 순서")
        self.reset_sort_button.setVisible(self.sort_policy != "source")
        self.reset_sort_button.setEnabled(not frame.empty)
        self.reset_sort()
        self.filter(self.search.text())

    def configure_editing(self, categories, edit_handler, override_provider=None):
        """Enable validated corrections only on record-level panes.

        ``categories`` may be a list or a supplier so newly edited rules are visible
        the next time a list is opened. The handler saves the supplied patch and
        returns success; callers may schedule a reanalysis from ``edit_saved``.
        """
        self.cancel_editing()
        self._categories = categories
        self._edit_handler = edit_handler
        self._override_provider = override_provider or (lambda event_id: {})
        self._classification_drafts.clear()
        self._configure_model()

    def _configure_model(self):
        if not hasattr(self, "model"):
            return
        self.model.edit_request = self._edit_cell if self._edit_handler else None
        self.model.editing_enabled = bool(self._editing_enabled and self._edit_handler)
        self.model.draft_provider = lambda record: self._classification_drafts.get(
            self._record_key(record)
        )
        self.model.choices_provider = self._category_choices
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            if self.model.editing_enabled
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        if self.model.columnCount():
            self.model.headerDataChanged.emit(
                Qt.Orientation.Horizontal, 0, self.model.columnCount() - 1
            )
        self.table.viewport().update()

    def set_editing_enabled(self, enabled):
        self._editing_enabled = bool(enabled)
        if not enabled:
            self.cancel_editing()
        self._configure_model()

    def cancel_editing(self):
        if hasattr(self, "edit_delegate"):
            self.edit_delegate.cancel_editing()
        if self.classification_editor is not None:
            self.classification_editor.close()
            self.classification_editor = None

    @staticmethod
    def _record_key(record):
        return tuple(shown(record.get(key)) for key in ("event_id", "record_id"))

    def _categories_for(self, record):
        paths = self._active_categories()
        current = tuple(shown(record.get(key)) for key in FIELDS)
        if (
            record.get("classification_mode") != "multiple"
            and all(current)
            and current not in paths
        ):
            paths.append(current)
        return paths

    def _active_categories(self):
        categories = self._categories() if callable(self._categories) else self._categories
        return list(categories)

    def _category_choices(self, record, column):
        try:
            paths = self._categories_for(record)
        except Exception as exc:
            self.edit_failed.emit(str(exc))
            return []
        level = FIELDS.index(column)
        draft = self._classification_drafts.get(self._record_key(record), record)
        prefix = tuple(shown(draft.get(key)) for key in FIELDS[:level])
        return sorted({path[level] for path in paths if path[:level] == prefix}, key=str.casefold)

    def _existing(self, record):
        return dict(self._override_provider(shown(record.get("event_id"))) or {})

    def _submit_patch(self, record, patch):
        if not self._editing_enabled or not self._edit_handler:
            return False
        if not any(self._record_key(record)):
            self.edit_failed.emit("수정할 기록을 식별할 수 없습니다. 다시 분석한 뒤 수정하세요.")
            return False
        if not patch:
            return True
        try:
            accepted = bool(self._edit_handler(dict(record), dict(patch)))
        except Exception as exc:
            self.edit_failed.emit(str(exc))
            return False
        if accepted:
            self.edit_saved.emit(dict(record), dict(patch))
        return accepted

    def _edit_cell(self, record, column, value):
        try:
            existing = self._existing(record)
            if column in FIELDS:
                return self._edit_category(record, existing, column, value)
            patch = field_patch(record, existing, column, value)
            return self._submit_patch(record, patch)
        except Exception as exc:
            self.edit_failed.emit(str(exc))
            return False

    def _edit_category(self, record, existing, column, value):
        if record.get("classification_mode") == "multiple":
            return False
        value = shown(value)
        if not value:
            return False
        key = self._record_key(record)
        current = self._classification_drafts.get(
            key, {field: shown(record.get(field)) for field in FIELDS}
        )
        retry_completed = (
            column == "minor" and key in self._classification_drafts and all(current.values())
        )
        if current.get(column) == value and not retry_completed:
            return True
        if value not in self._category_choices(record, column):
            raise UserError("현재 분류 목록에서 값을 선택하세요.")
        draft = dict(current)
        level = FIELDS.index(column)
        draft[column] = value
        for child in FIELDS[level + 1 :]:
            draft[child] = ""
        self._classification_drafts[key] = draft
        self.edit_status.setText(
            f"분류 선택 중 {len(self._classification_drafts)}행 · 노란 셀의 대 → 중 → 소분류를 모두 선택하세요. Esc로 이 행 선택을 취소할 수 있습니다."
        )
        self.edit_status.show()
        if not all(draft.values()):
            return True
        if tuple(draft[field] for field in FIELDS) not in self._categories_for(record):
            raise UserError("대·중·소분류의 상하위 관계를 확인하세요.")
        patch = classification_patch(record, existing, "single", draft, [])
        saved = self._submit_patch(record, patch)
        if saved:
            self._classification_drafts.pop(key, None)
            self.edit_status.setText("분류를 저장했습니다. 분석 결과를 갱신합니다.")
        return saved

    def open_classification_editor(self, index):
        if not self._editing_enabled or not self._edit_handler or not index.isValid():
            return None
        record = index.data(RECORD_ROLE)
        if not record or not any(self._record_key(record)):
            return None
        try:
            existing = self._existing(record)
            categories = self._active_categories()
        except Exception as exc:
            self.edit_failed.emit(str(exc))
            return None
        self.cancel_editing()
        self.cancel_classification_draft(record)
        editor = ClassificationCellEditor(
            record, existing, categories, self._submit_patch, self.table
        )
        self.classification_editor = editor
        editor.destroyed.connect(lambda: self._editor_destroyed(editor))
        editor.show_at(self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))
        self.table.viewport().update()
        return editor

    def _editor_destroyed(self, editor):
        if self.classification_editor is editor:
            self.classification_editor = None

    def cancel_classification_draft(self, record):
        if self._classification_drafts.pop(self._record_key(record), None) is None:
            return False
        self.edit_status.setText("분류 선택을 취소했습니다. 저장된 값은 변경되지 않았습니다.")
        self.edit_status.show()
        self.table.viewport().update()
        return True

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            index = self.table.currentIndex()
            record = index.data(RECORD_ROLE) if index.isValid() else None
            if record and self.cancel_classification_draft(record):
                self.cancel_editing()
                self.table.viewport().update()
                return True
        return super().eventFilter(watched, event)

    def reset_sort(self, *_):
        """Restore the agreed default after optional header-click sorting."""
        column = (
            self.model.frame.columns.get_loc(self.default_key)
            if self.default_key is not None
            else -1
        )
        self.table.sortByColumn(int(column), Qt.SortOrder.DescendingOrder)
        if column == -1:
            # A grouped ranking must not be flattened into one global count rank.
            self.proxy.sort(-1)

    def filter(self, text):
        self.proxy.setFilterFixedString(text)
        self.info.setText(f"{self.proxy.rowCount():,} / {self.model.rowCount():,}")

    def selected_record(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        index = self.proxy.mapToSource(selected[0]).row()
        return self.model.frame.iloc[index].to_dict()
