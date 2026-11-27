"""A two-level header keeps unmodified source fields visibly together."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionHeader

SOURCE_FIELDS = ("raw_equipment_name", "raw_mid", "raw_small", "raw_description")
PRIMARY_FIELDS = (
    "major",
    "detail_equipment",
    "minor",
    "repair_actions",
    "classification_missing_fields",
    *SOURCE_FIELDS,
    "component_types",
    "combination_decision",
)
LABELS = {
    "major": "고장 분야\n분야 확인",
    "detail_equipment": "상세설비·모듈\n고장 대상",
    "minor": "고장 현상\n관찰 증상",
    "repair_actions": "조치 내역\n복수 입력",
    "classification_missing_fields": "미기재 분류 항목\n원문에 없음",
    "raw_equipment_name": "설비명",
    "raw_mid": "비가동 코드(중)",
    "raw_small": "비가동 코드(소)",
    "raw_description": "고장내용/비고",
    "component_types": "최종 분류",
    "combination_decision": "분류 판정",
}


class GroupedHeader(QHeaderView):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setSectionsMovable(False)
        self.setMinimumHeight(58)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sectionResized.connect(lambda *_: self.viewport().update())

    def sizeHint(self):
        size = super().sizeHint()
        return QSize(size.width(), max(58, size.height() * 2))

    def _field(self, logical):
        model = self.model()
        source = model.sourceModel() if hasattr(model, "sourceModel") else model
        return (
            source.frame.columns[logical]
            if source is not None
            and hasattr(source, "frame")
            and 0 <= logical < len(source.frame.columns)
            else None
        )

    def _draw(self, painter, rect, text, logical=-1):
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = rect
        option.text = text
        option.textAlignment = Qt.AlignmentFlag.AlignCenter
        option.section = logical
        if self._field(logical) in (
            "major",
            "detail_equipment",
            "minor",
            "component_types",
        ):
            option.icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        option.sortIndicator = QStyleOptionHeader.SortIndicator.None_
        if logical >= 0 and logical == self.sortIndicatorSection() and self.isSortIndicatorShown():
            option.sortIndicator = (
                QStyleOptionHeader.SortIndicator.SortDown
                if self.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                else QStyleOptionHeader.SortIndicator.SortUp
            )
        self.style().drawControl(QStyle.ControlElement.CE_Header, option, painter, self)

    def paintSection(self, painter, rect, logical):
        field = self._field(logical)
        if field in SOURCE_FIELDS:
            half = rect.height() // 2
            rect = QRect(rect.x(), rect.y() + half, rect.width(), rect.height() - half)
        text = LABELS.get(
            field, str(self.model().headerData(logical, Qt.Orientation.Horizontal) or "")
        )
        self._draw(painter, rect, text, logical)

    def paintEvent(self, event):
        super().paintEvent(event)
        sections = [
            i
            for i in range(self.count())
            if self._field(i) in SOURCE_FIELDS and not self.isSectionHidden(i)
        ]
        if not sections:
            return
        left = min(self.sectionViewportPosition(i) for i in sections)
        right = max(self.sectionViewportPosition(i) + self.sectionSize(i) for i in sections)
        painter = QPainter(self.viewport())
        self._draw(painter, QRect(left, 0, right - left, self.height() // 2), "원본")
        painter.end()

    def mousePressEvent(self, event):
        logical = self.logicalIndexAt(event.position().toPoint())
        if self._field(logical) in SOURCE_FIELDS and event.position().y() < self.height() // 2:
            return
        super().mousePressEvent(event)
