"""Edit the department displayed on the Excel report."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)


class ReportSettingsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Excel 보고서 옵션")
        self.resize(420, 120)
        data = store.read("final_report.json")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.department = QLineEdit(str(data.get("department", "")))
        self.department.setMaxLength(120)
        form.addRow("부서", self.department)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("\uc800\uc7a5")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("\ucde8\uc18c")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            self.store.save_report_settings({"department": self.department.text()})
        except Exception as exc:
            QMessageBox.warning(self, "\uc124\uc815 \ud655\uc778", str(exc))
            return
        self.accept()
