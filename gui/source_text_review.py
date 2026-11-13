"""Read the source and the exact analyzed normalization side by side."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from core.corrections import shown


class ClassificationTextComparison(QWidget):
    def __init__(self, record, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.raw = self._column(
            layout,
            "고장내용/비고 · 원문",
            shown(record.get("raw_description")),
            "고장 내용 없음",
            "classificationRawText",
        )
        self.normalized = self._column(
            layout,
            "표준화 후 내용 · 분류 입력",
            shown(record.get("normalized")),
            "표준화 후 내용 없음",
            "classificationNormalizedText",
        )
        self.normalized.setToolTip(
            "현재 분석에서 분류에 사용한 표준화 내용입니다. 표준화 규칙을 수정했다면 분석을 다시 실행하세요."
        )

    @staticmethod
    def _column(layout, label, text, placeholder, name):
        column = QVBoxLayout()
        column.setSpacing(4)
        column.addWidget(QLabel(label))
        view = QPlainTextEdit()
        view.setObjectName(name)
        view.setAccessibleName(label)
        view.setReadOnly(True)
        view.setPlainText(text)
        view.setPlaceholderText(placeholder)
        view.setMinimumHeight(100)
        view.setMaximumHeight(150)
        view.setTabChangesFocus(True)
        column.addWidget(view)
        layout.addLayout(column, 1)
        return view
