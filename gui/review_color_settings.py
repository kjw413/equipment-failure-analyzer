"""Persisted review-reason colors for the annotated source workbook."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.review_colors import REVIEW_TYPES, normalized_review_colors


class ReviewColorSettingsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.changed = False
        self.colors = normalized_review_colors(store.load()["settings"].get("review_colors"))
        self.setWindowTitle("검토필요 색상 설정")
        self.resize(520, 370)
        self.setMinimumSize(470, 350)
        layout = QVBoxLayout(self)
        info = QLabel(
            "Excel 보고서를 저장할 때 별첨. 원본 검토표시에 적용합니다. "
            "검토필요 행의 A열~X열을 같은 색상으로 표시하며 입력 원본은 보존됩니다."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        priority = QLabel(
            "여러 사유가 겹치면 아래 목록 위쪽 유형의 색상을 행 전체에 적용합니다. "
            "행의 메모에서 모든 검토 사유를 확인할 수 있습니다.\n"
            "기타에는 날짜·정지시간·고장대상 등 나머지 검토 사유가 포함됩니다."
        )
        priority.setWordWrap(True)
        layout.addWidget(priority)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.color_buttons = {}
        for key, label, _default in REVIEW_TYPES:
            button = QPushButton()
            button.setObjectName("review_color_" + key)
            button.setMinimumWidth(145)
            button.setToolTip(label + " 행 색상 선택")
            button.clicked.connect(lambda checked=False, reason=key: self.choose_color(reason))
            self.color_buttons[key] = button
            form.addRow(label, button)
        layout.addLayout(form, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        defaults = self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        defaults.setText("기본 색상 복원")
        defaults.clicked.connect(self.restore_defaults)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.refresh_swatches()

    def refresh_swatches(self):
        for key, button in self.color_buttons.items():
            value = self.colors[key]
            color = QColor(value)
            # Keep color codes legible on both pale and dark selections.
            foreground = "#17212B" if color.lightnessF() >= 0.5 else "#FFFFFF"
            button.setText(value)
            button.setStyleSheet(
                f"QPushButton {{ background-color: {value}; color: {foreground}; "
                "border: 1px solid #8895A3; border-radius: 4px; padding: 6px 16px; }"
            )

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.colors[key]), self, "행 색상 선택")
        if color.isValid():
            self.colors[key] = color.name().upper()
            self.refresh_swatches()

    def restore_defaults(self):
        self.colors = normalized_review_colors(None)
        self.refresh_swatches()

    def save(self):
        try:
            self.store.save_review_colors(self.colors)
        except Exception as exc:
            QMessageBox.warning(self, "설정 확인", str(exc))
            return
        self.changed = True
        self.accept()
