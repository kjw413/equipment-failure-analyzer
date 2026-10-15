from __future__ import annotations
import logging
from typing import Callable
from numbers import Real
import pandas as pd
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QThread
from PySide6.QtWidgets import (QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLineEdit, QTableView, QWidget, QAbstractItemView, QHeaderView)
from core.i18n import K, DISPLAY
from core.models import UserError
from core.preprocessing import is_missing
from core.sorting import descending, default_metric


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, function: Callable, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            result = self.function(self.progress.emit)
        except UserError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logging.getLogger(__name__).exception('Processing failed')
            self.failed.emit('\ucc98\ub9ac \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4. \uc124\uc815 \ud3f4\ub354\uc758 logs\ub97c \ud655\uc778\ud558\uc138\uc694.')
        else:
            self.succeeded.emit(result)


class DropArea(QFrame):
    file_dropped = Signal(str)
    browse_requested = Signal()
    invalid_drop = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName('dropArea')
        self.setMinimumHeight(126)
        layout = QVBoxLayout(self)
        title = QLabel(K['drop']); title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName('dropTitle')
        subtitle = QLabel('.xlsx / .xlsm   |   '+K['one_file'])
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter); subtitle.setObjectName('muted')
        button = QPushButton(K['browse']); button.setMinimumWidth(190)
        button.clicked.connect(self.browse_requested.emit)
        layout.addWidget(title); layout.addWidget(subtitle)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(button); buttons.addStretch()
        layout.addLayout(buttons)

    def dragEnterEvent(self, event):
        if self.isEnabled() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) != 1:
            self.invalid_drop.emit(K['one_file']); event.ignore(); return
        if not urls[0].isLocalFile():
            self.invalid_drop.emit(K['unsupported']); event.ignore(); return
        self.file_dropped.emit(urls[0].toLocalFile())
        event.acceptProposedAction()


class FrameModel(QAbstractTableModel):
    def __init__(self, frame: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.frame = frame.reset_index(drop=True).copy()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.frame.iat[index.row(), index.column()]
        missing = is_missing(value)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if missing:
                return ''
            column = self.frame.columns[index.column()]
            if isinstance(value, pd.Timestamp):
                return value.strftime('%Y-%m-%d' if column == 'date' else '%Y-%m-%d %H:%M:%S')
            if isinstance(value, Real) and not isinstance(value, bool):
                if str(column).endswith('_share'):
                    return f'{value:.1%}'
                return f'{value:,.0f}' if float(value).is_integer() else f'{value:,.2f}'
            return str(value)
        if role == Qt.ItemDataRole.UserRole:
            if missing:
                return None
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            if hasattr(value, 'item'):
                return value.item()
            return value
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and not 0 <= section < len(self.frame.columns):
            return None
        if role == Qt.ItemDataRole.InitialSortOrderRole and orientation == Qt.Orientation.Horizontal:
            # The first click on a numeric header starts with the largest value.
            column = self.frame.columns[section]
            if pd.api.types.is_numeric_dtype(self.frame[column]):
                return Qt.SortOrder.DescendingOrder
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            key = self.frame.columns[section]
            return DISPLAY.get(key, str(key))
        return str(section+1)


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
        return (left_index.row() > right_index.row() if descending_order
                else left_index.row() < right_index.row())

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(section + 1)
        return super().headerData(section, orientation, role)


class TablePane(QWidget):
    def __init__(self, parent=None, *, sort_policy: str = 'auto'):
        super().__init__(parent)
        self.sort_policy = sort_policy
        self.default_key = None
        layout = QVBoxLayout(self); layout.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText(K['search'])
        self.sort_hint = QLabel(); self.sort_hint.setObjectName('muted')
        self.reset_sort_button = QPushButton('큰 값순 정렬')
        self.reset_sort_button.clicked.connect(self.reset_sort)
        self.info = QLabel('0'); self.info.setObjectName('muted')
        top.addWidget(self.search, 1); top.addWidget(self.sort_hint)
        top.addWidget(self.reset_sort_button); top.addWidget(self.info)
        self.table = QTableView()
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
        # Do not enable sorting on column 0 before installing a numeric default.
        self.search.textChanged.connect(self.filter)
        layout.addLayout(top); layout.addWidget(self.table)
        self.set_frame(pd.DataFrame())

    def set_frame(self, frame: pd.DataFrame):
        self.default_key = default_metric(frame) if self.sort_policy == 'auto' else None
        prepared = descending(frame, self.default_key) if self.default_key else frame
        self.table.setSortingEnabled(False)
        self.proxy.sort(-1)
        old = self.proxy.sourceModel()
        self.model = FrameModel(prepared, self)
        self.proxy.setSourceModel(self.model)
        if old is not None:
            old.deleteLater()
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.DescendingOrder)
        self.table.setSortingEnabled(True)
        for index, column in enumerate(prepared.columns):
            hidden = column in ('record_id', 'event_id', '__source_row')
            self.table.setColumnHidden(index, hidden)
            width = 270 if column in ('raw_description', 'normalized', 'issues', 'evidence', 'candidates', 'raw_equipment_name', 'review_reason', 'review_action', 'aggregation_effect') else 180 if column in ('equipment', 'target', 'registered', 'type', 'report_equipment', 'product') else 135
            self.table.setColumnWidth(index, width)
        if self.default_key:
            self.sort_hint.setText('기본: ' + DISPLAY.get(self.default_key, self.default_key) + ' ↓')
        elif self.sort_policy == 'grouped':
            self.sort_hint.setText('설비 정지시간 ↓ / 설비 내 유형 건수 ↓')
        else:
            self.sort_hint.setText('원본 행 순서')
        self.reset_sort_button.setVisible(self.sort_policy != 'source')
        self.reset_sort_button.setEnabled(not frame.empty)
        self.reset_sort()
        self.filter(self.search.text())

    def reset_sort(self, *_):
        """Restore the agreed default after optional header-click sorting."""
        column = (self.model.frame.columns.get_loc(self.default_key)
                  if self.default_key is not None else -1)
        self.table.sortByColumn(int(column), Qt.SortOrder.DescendingOrder)
        if column == -1:
            # A grouped ranking must not be flattened into one global count rank.
            self.proxy.sort(-1)

    def filter(self, text):
        self.proxy.setFilterFixedString(text)
        self.info.setText(f'{self.proxy.rowCount():,} / {self.model.rowCount():,}')

    def selected_record(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        index = self.proxy.mapToSource(selected[0]).row()
        return self.model.frame.iloc[index].to_dict()
