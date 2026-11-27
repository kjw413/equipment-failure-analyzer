"""Compare the source text and the classification input side by side."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from core.corrections import shown


class ClassificationTextComparison(QWidget):
    def __init__(self, record, parent=None, *, editable=False):
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
        self.raw.setReadOnly(True)
        normalized = record.get("normalized")
        self.normalized = self._column(
            layout,
            "표준화 후 내용 · 분류 입력 (수정 가능)" if editable else "표준화 후 내용 · 분류 입력",
            normalized if isinstance(normalized, str) else "",
            "표준화 후 내용 없음",
            "classificationNormalizedText",
        )
        self.normalized.setReadOnly(not editable)
        if editable:
            self.normalized.setToolTip(
                "수기로 입력한 내용으로 이 기록을 다시 분석합니다. "
                "저장된 수기 내용을 지우고 적용하면 자동 표준화로 돌아갑니다."
            )
        else:
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
        view.setPlainText(text)
        view.setPlaceholderText(placeholder)
        view.setMinimumHeight(100)
        view.setMaximumHeight(150)
        view.setTabChangesFocus(True)
        column.addWidget(view)
        layout.addLayout(column, 1)
        return view
