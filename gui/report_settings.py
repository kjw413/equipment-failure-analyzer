"""Small native dialog for optional final-report metadata."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from core.issue_analysis import issue_facts


class ReportSettingsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("\ucd5c\uc885\ubcf4\uace0\uc11c \uc124\uc815")
        self.resize(710, 540)
        data = store.read("final_report.json")
        layout = QVBoxLayout(self)
        info = QLabel(
            "\ube48 \ud56d\ubaa9\uc740 \uc0dd\ub7b5\ub429\ub2c8\ub2e4. \uc81c\ubaa9\uc744 \ube44\uc6b0\uba74 \ubd84\uc11d \ubc94\uc704\uc5d0 \ub9de\ub294 \uae30\ubcf8 \uc81c\ubaa9\uc744 \uc0ac\uc6a9\ud569\ub2c8\ub2e4."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        form = QFormLayout()
        self.fields = {}
        for key, title, limit in [
            ("title", "\ubcf4\uace0\uc11c \uc81c\ubaa9", 100),
            ("department", "\ubd80\uc11c", 120),
            ("prepared_by", "\uc791\uc131\uc790", 80),
        ]:
            edit = QLineEdit(str(data.get(key, "")))
            edit.setMaxLength(limit)
            form.addRow(title, edit)
            self.fields[key] = edit
        self.case = QComboBox()
        self.case.addItem("주요 사례 자동선정 (건수·정지시간)", "")
        result = getattr(parent, "result", None)
        saved_case = str(data.get("focus_case", "")).strip()
        cases = set(issue_facts(result.selected)["case"]) if result is not None else set()
        if saved_case:
            cases.add(saved_case)
        for case in sorted(cases):
            self.case.addItem(case, case)
        if saved_case:
            self.case.setCurrentIndex(self.case.findData(saved_case))
        self.case.setEditable(True)
        self.case.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.case.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.case.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.case.setMinimumContentsLength(25)
        self.case.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        form.addRow("비교·추이 고장사례", self.case)
        self.appendix = QCheckBox("PDF 끝에 개별 분류 이력 전체 포함 (기본은 Excel에서 확인)")
        self.appendix.setChecked(bool(data.get("include_record_appendix", False)))
        form.addRow("개별 이력 부록", self.appendix)
        self.note = QTextEdit()
        self.note.setPlainText(str(data.get("closing_note", "")))
        self.note.setPlaceholderText(
            "\ucd5c\ub300 1,600\uc790. PDF\uc5d0 \uc0ac\uc6a9\uc790 \uc785\ub825 \uc758\uacac\uc73c\ub85c \ud45c\uc2dc. \uc790\ub3d9 \ubd84\uc11d \uacb0\ub860\uacfc \uad6c\ubd84\ub429\ub2c8\ub2e4."
        )
        form.addRow("\ucd94\uac00 \uc758\uacac", self.note)
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
        case_index = self.case.findText(self.case.currentText(), Qt.MatchFlag.MatchExactly)
        if case_index < 0:
            QMessageBox.warning(
                self, "고장사례 선택", "목록에서 사례를 선택하거나 주요 사례 자동선정을 선택하세요."
            )
            return
        values = {key: edit.text() for key, edit in self.fields.items()}
        values["closing_note"] = self.note.toPlainText()
        values["focus_case"] = self.case.itemData(case_index) or ""
        values["include_record_appendix"] = self.appendix.isChecked()
        try:
            self.store.save_report_settings(values)
        except Exception as exc:
            QMessageBox.warning(self, "\uc124\uc815 \ud655\uc778", str(exc))
            return
        self.accept()
