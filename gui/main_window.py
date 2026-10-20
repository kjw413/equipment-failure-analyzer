from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

import pandas as pd
from PySide6.QtCore import QDate, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.classification_catalog import catalog_categories
from core.config import ConfigStore, output_root
from core.corrections import FIELDS, validate
from core.defaults_merge import describe
from core.equipment_breakdown import type_breakdown
from core.excel_loader import load_excel, validate_path
from core.i18n import UNMATCHED, K
from core.models import AnalysisOptions, UserError
from core.preprocessing import event_ids
from core.rules import read_rules
from core.service import run_analysis
from gui.dialogs import ColumnMappingDialog, EquipmentNamesDialog, RuleEditor
from gui.grouped_header import PRIMARY_FIELDS, GroupedHeader
from gui.navigation import WorkspaceNavigation
from gui.report_settings import ReportSettingsDialog
from gui.tasks import Task
from gui.theme import STYLE
from gui.widgets import DropArea, TablePane
from report.export_bundle import export_bundle, report_paths
from version import VERSION


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store = store
        self.loaded = None
        self.result = None
        self.task = None
        self.last_reports = None
        self._grid_refresh_pending = False
        self._grid_reanalyzing = False
        self._analysis_stale = False
        self._grid_view_state = None
        self.config = store.load()
        self.setWindowTitle(f"{K['app']}  v{VERSION}")
        self.setMinimumSize(1050, 690)
        self.resize(1430, 940)
        self.setStyleSheet(STYLE)
        self.actions = []
        self.panes = {}
        self._chart_canvas = None
        self._build_ui()
        self._connect_options()
        self.update_controls()
        merged = describe(getattr(store, "merge_summary", {}))
        if merged:
            self.status_label.setText(
                merged + " | 이전 설정 백업: " + str(store.config_dir / "backup")
            )

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        self._build_header(layout)
        condition_bar = QHBoxLayout()
        self.source_toggle = QToolButton()
        self.source_toggle.setText("파일 · 분석 조건")
        self.source_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.source_toggle.setCheckable(True)
        self.source_toggle.setChecked(True)
        self.source_toggle.setArrowType(Qt.ArrowType.UpArrow)
        condition_bar.addWidget(self.source_toggle)
        self.condition_summary = QLabel("Excel 파일을 등록하세요.")
        self.condition_summary.setObjectName("muted")
        condition_bar.addWidget(self.condition_summary, 1)
        layout.addLayout(condition_bar)
        self.source_panel = QWidget()
        source_layout = QVBoxLayout(self.source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(8)
        self._build_source_controls(source_layout)
        self._build_analysis_controls(source_layout)
        self.source_toggle.toggled.connect(self._toggle_source_panel)
        layout.addWidget(self.source_panel)
        self._build_report_controls(layout)
        self._build_tabs(layout)
        self._build_status(layout)

    def _toggle_source_panel(self, expanded):
        self.source_panel.setVisible(expanded)
        self.source_toggle.setArrowType(
            Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow
        )
        self.source_toggle.setToolTip(
            "파일·분석 조건 접기" if expanded else "파일·분석 조건 펼치기"
        )

    def _build_header(self, layout):
        header = QHBoxLayout()
        title = QLabel(K["app"])
        title.setObjectName("title")
        subtitle = QLabel(K["offline"] + f"  |  v{VERSION}")
        subtitle.setObjectName("muted")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(subtitle)
        layout.addLayout(header)

    def _build_source_controls(self, layout):
        self.drop = DropArea()
        self.drop.browse_requested.connect(self.browse)
        self.drop.file_dropped.connect(self.load_path)
        self.drop.invalid_drop.connect(self.notice)
        layout.addWidget(self.drop)
        self.file_label = QLabel(K["ready"])
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("muted")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.file_label)
        source = QHBoxLayout()
        source.addWidget(QLabel(K["choose_sheet"]))
        self.sheets = QComboBox()
        self.sheets.setMinimumWidth(220)
        source.addWidget(self.sheets)
        source.addWidget(QLabel(K["header"]))
        self.header_row = QSpinBox()
        self.header_row.setRange(1, 250000)
        self.header_row.setValue(1)
        source.addWidget(self.header_row)
        self.reload_button = self.button(K["reload"], self.reload, source)
        self.columns_button = self.button(K["mapping"], self.edit_columns, source)
        self.reset_button = self.button(K["reset"], self.reset, source)
        source.addStretch()
        self.settings_button = QToolButton()
        self.settings_button.setText("기준정보 · 설정")
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.settings_button)
        self.names_button = menu.addAction(K["name_editor"], self.edit_names)
        self.rules_button = menu.addAction(K["rules"], self.edit_rules)
        self.folder_button = menu.addAction(K["config"], self.open_config)
        self.settings_button.setMenu(menu)
        source.addWidget(self.settings_button)
        self.actions.extend(
            [self.settings_button, self.names_button, self.rules_button, self.folder_button]
        )
        layout.addLayout(source)

    def _build_analysis_controls(self, layout):
        filters = QGridLayout()
        filters.addWidget(QLabel(K["scope"]), 0, 0)
        self.scope = QComboBox()
        self.scope.addItem(K["fault_only"], "fault")
        self.scope.addItem(K["all_stops"], "all")
        filters.addWidget(self.scope, 0, 1)
        filters.addWidget(QLabel(K["basis"]), 0, 2)
        self.basis = QComboBox()
        for value in ("mapped", "target", "registered", "family"):
            self.basis.addItem(K[value], value)
        self.basis.setMinimumWidth(265)
        filters.addWidget(self.basis, 0, 3)
        filters.addWidget(QLabel(K["units"]), 0, 4)
        self.units = QComboBox()
        for label, value in (
            (K["minutes_unit"], "minutes"),
            (K["hours_unit"], "hours"),
            (K["seconds_unit"], "seconds"),
            (K["excel_days"], "excel_days"),
        ):
            self.units.addItem(label, value)
        filters.addWidget(self.units, 0, 5)
        self.limit_dates = QCheckBox(K["date_filter"])
        filters.addWidget(self.limit_dates, 1, 0)
        self.date_from = QDateEdit(QDate.currentDate())
        self.date_to = QDateEdit(QDate.currentDate())
        for edit in (self.date_from, self.date_to):
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setCalendarPopup(True)
        filters.addWidget(self.date_from, 1, 1)
        filters.addWidget(QLabel("~"), 1, 2)
        filters.addWidget(self.date_to, 1, 3)
        self.dedup = QCheckBox(K["dedup"])
        filters.addWidget(self.dedup, 1, 4, 1, 2)
        layout.addLayout(filters)

    def _build_report_controls(self, layout):
        run = QHBoxLayout()
        self.analyze_button = self.button(K["analyze"], self.analyze, run, "primary")
        self.report_button = self.button(
            "Excel + PDF \uc0dd\uc131", self.save_report, run, "primary"
        )
        self.open_button = self.button("Excel \uc5f4\uae30", self.open_excel, run)
        self.pdf_button = self.button("PDF \uc5f4\uae30", self.open_pdf, run)
        self.output_button = self.button("\uacb0\uacfc \ud3f4\ub354", self.open_output, run)
        self.report_settings_button = self.button(
            "\ubcf4\uace0\uc11c \uc124\uc815", self.edit_report_settings, run
        )
        run.addStretch()
        run.addWidget(QLabel("TOP"))
        self.top = QSpinBox()
        self.top.setRange(1, 30)
        self.top.setValue(int(self.config["settings"].get("top_n", 10)))
        run.addWidget(self.top)
        layout.addLayout(run)

    def _build_tabs(self, layout):
        self.summary = self.make_summary()
        for key, title_key in [
            ("raw", "preview"),
            ("equipment", "equipment_tab"),
            ("line", "line_tab"),
            ("type", "type_tab"),
            ("cross", "cross_tab"),
            ("detail", "detail_tab"),
            ("review", "review_tab"),
        ]:
            pane = TablePane(sort_policy="source" if key == "raw" else "auto")
            self.panes[key] = pane
        pane = TablePane(sort_policy="grouped")
        self.panes["equipment_types"] = pane
        component_note = (
            "유형 포함 사건수는 한 사건에 여러 유형을 중복 포함하므로 "
            "유형별 합계가 전체 사건수보다 클 수 있습니다. "
            f"정지시간은 부품별로 중복 배분하지 않으며 {K['type_tab']} 탭에서 확인하세요."
        )
        for key, title in (
            ("component", K["component_tab"]),
            ("component_trend", K["component_trend_tab"]),
        ):
            pane = TablePane(
                description=component_note,
                sort_policy="period" if key == "component_trend" else "auto",
            )
            self.panes[key] = pane
        self._build_chart_tab()
        self.navigation = WorkspaceNavigation(
            {**self.panes, "summary": self.summary, "chart": self.chart_page}
        )
        self.tabs = self.navigation.tabs
        layout.addWidget(self.navigation, 1)
        for key in ("review", "detail"):
            pane = self.panes[key]
            pane.configure_editing(
                lambda: catalog_categories(
                    read_rules(self.store.config_dir / "classification_config.xlsx")
                ),
                self._save_grid_edit,
                self.store.override,
            )
            pane.edit_saved.connect(self._grid_edit_saved)
            pane.edit_failed.connect(self.show_error)
            pane.table.setHorizontalHeader(GroupedHeader(pane.table))
            pane.table.setWordWrap(True)
            pane.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            pane.table.customContextMenuRequested.connect(
                lambda point, target=pane: self._grid_menu(target, point)
            )
            pane.table.horizontalHeader().setSectionResizeMode(
                pane.table.horizontalHeader().ResizeMode.Interactive
            )
            pane.extra_columns = QCheckBox("추가 열 표시 · 일자/시간/검토 근거")
            pane.extra_columns.toggled.connect(
                lambda checked, target=pane: self._grid_columns(target, checked)
            )
            pane.layout().itemAt(0).layout().insertWidget(1, pane.extra_columns)
            pane.description.setText(
                "분류 셀을 더블클릭하여 대 → 중 → 소분류를 선택하세요. "
                "세 항목이 완성되면 저장됩니다. 유형조합 셀에서는 단일·복수 유형을 확정할 수 있습니다. "
                "일자·시간·대상설비·제품명은 Enter 또는 셀 이동으로 저장합니다. Esc는 취소입니다."
            )
            pane.description.setVisible(True)

    def _build_chart_tab(self):
        self.chart_page = QWidget()
        self.chart_layout = QVBoxLayout(self.chart_page)
        chart_controls = QHBoxLayout()
        self.chart_choice = QComboBox()
        self.chart_choice.addItem(
            "\uc124\ube44\ubcc4 \uace0\uc7a5\uc720\ud615(\uc6d0\ud615)", "equipment_types"
        )
        for label, key in (
            (K["equipment_tab"], "equipment"),
            (K["type_tab"], "type"),
            (K["line_tab"], "line"),
            (K["monthly"], "trend_month"),
            (K["week"], "trend_week"),
            (K["day"], "trend_day"),
            (K["year"], "trend_year"),
        ):
            self.chart_choice.addItem(label, key)
        self.chart_metric = QComboBox()
        self.chart_metric.addItem(K["total"], "total_minutes")
        self.chart_metric.addItem(K["count"], "count")
        self.chart_metric.setCurrentIndex(1)
        self.chart_equipment = QComboBox()
        self.chart_equipment.setMinimumWidth(210)
        chart_controls.addWidget(self.chart_choice)
        chart_controls.addWidget(self.chart_equipment)
        chart_controls.addWidget(self.chart_metric)
        chart_controls.addStretch()
        self.chart_layout.addLayout(chart_controls)
        self.chart_empty = QLabel(K["empty"])
        self.chart_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_layout.addWidget(self.chart_empty, 1)
        self.chart_choice.currentIndexChanged.connect(self.draw_chart)
        self.chart_metric.currentIndexChanged.connect(self.draw_chart)
        self.chart_equipment.currentIndexChanged.connect(self.draw_chart)

    def _build_status(self, layout):
        status = QHBoxLayout()
        self.status_label = QLabel(K["ready"])
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(300)
        status.addWidget(self.status_label, 1)
        status.addWidget(self.progress)
        layout.addLayout(status)

    def _connect_options(self):
        self.option_widgets = [
            self.scope,
            self.basis,
            self.units,
            self.limit_dates,
            self.date_from,
            self.date_to,
            self.dedup,
            self.top,
            self.sheets,
            self.header_row,
        ]
        for combo in (self.scope, self.basis, self.units):
            combo.currentIndexChanged.connect(self.mark_stale)
        for check in (self.limit_dates, self.dedup):
            check.toggled.connect(self.mark_stale)
        self.date_from.dateChanged.connect(self.mark_stale)
        self.date_to.dateChanged.connect(self.mark_stale)
        self.top.valueChanged.connect(self.mark_stale)
        self.sheets.currentIndexChanged.connect(self.mark_stale)
        self.header_row.valueChanged.connect(self.mark_stale)

    def button(self, text, slot, layout, style=None):
        button = QPushButton(text)
        button.clicked.connect(slot)
        if style:
            button.setObjectName(style)
        layout.addWidget(button)
        self.actions.append(button)
        return button

    def make_summary(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        cards = QHBoxLayout()
        self.card_labels = {}
        for key, label in [
            ("selected_rows", K["count"]),
            ("total_minutes", K["total"]),
            ("mean_minutes", K["mean"]),
            ("review_rows", K["review_tab"]),
        ]:
            group = QGroupBox(label)
            group_layout = QVBoxLayout(group)
            value = QLabel("-")
            value.setStyleSheet("font-size: 30px; font-weight: 700; padding: 12px; color: #355767;")
            group_layout.addWidget(value)
            cards.addWidget(group)
            self.card_labels[key] = value
        layout.addLayout(cards)
        self.notes = QTextBrowser()
        self.notes.setPlainText(K["ready"] + "\n\n" + K["name_help"] + "\n\nIF18115  ->  VITAL#2")
        layout.addWidget(self.notes, 1)
        return page

    def notice(self, message):
        QMessageBox.information(self, K["notice"], str(message))

    def show_error(self, message):
        self.status_label.setText(K["error"])
        QMessageBox.warning(self, K["error"], str(message))

    def update_controls(self):
        busy = self.task is not None or self._grid_refresh_pending
        for widget in self.actions + self.option_widgets + [self.drop]:
            widget.setEnabled(not busy)
        for widget in (
            self.reload_button,
            self.columns_button,
            self.reset_button,
            self.sheets,
            self.header_row,
            self.analyze_button,
            self.report_button,
        ):
            widget.setEnabled(not busy and self.loaded is not None)
        for key in ("detail", "review"):
            self.panes[key].set_editing_enabled(
                not busy and self.result is not None and not self._analysis_stale
            )
        for widget in (self.open_button, self.pdf_button, self.output_button):
            widget.setEnabled(not busy and self.last_reports is not None)
        self.chart_choice.setEnabled(not busy)
        self.chart_metric.setEnabled(not busy)
        self.chart_equipment.setEnabled(not busy)
        self.date_from.setEnabled(not busy and self.limit_dates.isChecked())
        self.date_to.setEnabled(not busy and self.limit_dates.isChecked())

    def run_task(self, function, on_success):
        if self.task is not None:
            return
        task = Task(function, self)
        self.task = task
        task.progress.connect(self.on_progress)
        task.succeeded.connect(on_success)
        task.failed.connect(self._task_error)
        task.finished.connect(self.task_finished)
        self.progress.setValue(0)
        self.update_controls()
        task.start()

    def task_finished(self):
        task = self.task
        self.task = None
        self._grid_reanalyzing = False
        self.update_controls()
        if task is not None:
            task.deleteLater()

    def _task_error(self, message):
        if self._grid_reanalyzing:
            self._analysis_stale = True
            message = (
                "수정값은 저장되었으나 결과 갱신에 실패했습니다. 분석을 다시 실행하세요.\n"
                + str(message)
            )
        self.show_error(message)

    def on_progress(self, value, message):
        self.progress.setValue(value)
        self.status_label.setText(message)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, K["browse"], "", "Excel (*.xlsx *.xlsm)")
        if path:
            self.load_path(path)

    def load_path(self, path, sheet=None, header_row=None):
        if self.task is not None:
            return
        try:
            path = validate_path(path)
            config = self.store.load()
        except Exception as exc:
            self.show_error(exc)
            return
        self.clear_results()
        self.loaded = None
        self.file_label.setText(str(path))
        lookup = self.store.saved_mapping
        self.run_task(
            lambda progress: load_excel(
                path, config["column_mapping"], sheet, header_row, progress, lookup
            ),
            self.loaded_ready,
        )

    def loaded_ready(self, loaded):
        self.loaded = loaded
        self.drop.set_compact(True)
        self.source_toggle.setChecked(True)
        self.condition_summary.setText(loaded.path.name)
        self.condition_summary.setToolTip(str(loaded.path))
        self.sheets.clear()
        self.sheets.addItems(loaded.sheet_names)
        self.sheets.setCurrentText(loaded.sheet)
        self.header_row.setValue(loaded.header_row)
        self.file_label.setText(
            f"{loaded.path}\n{loaded.sheet}  |  {len(loaded.frame):,} rows / {len(loaded.headers)} columns  |  header {loaded.header_row}"
        )
        self.panes["raw"].set_frame(loaded.frame.drop(columns=["__source_row"], errors="ignore"))
        self.notes.setPlainText(K["name_help"])
        self.show_page("raw")
        self.status_label.setText(
            "\ud30c\uc77c \ub4f1\ub85d \uc644\ub8cc. \uc124\ube44\uba85 \ubcc0\ud658 \uc124\uc815 \ud6c4 \ubd84\uc11d\uc744 \uc2e4\ud589\ud558\uc138\uc694."
        )

    def reload(self):
        if self.loaded:
            self.load_path(self.loaded.path, self.sheets.currentText(), self.header_row.value())

    def clear_results(self):
        self.result = None
        self.last_reports = None
        self._analysis_stale = False
        self._grid_refresh_pending = False
        self._grid_view_state = None
        for pane in self.panes.values():
            pane.set_frame(pd.DataFrame())
        for label in self.card_labels.values():
            label.setText("-")
        self.clear_chart()
        self.navigation.update_counts()

    def reset(self):
        self.clear_results()
        self.loaded = None
        self.drop.set_compact(False)
        self.source_toggle.setChecked(True)
        self.condition_summary.setText("Excel 파일을 등록하세요.")
        self.condition_summary.setToolTip("")
        self.file_label.setText(K["ready"])
        self.notes.setPlainText(K["ready"])
        self.sheets.clear()
        self.status_label.setText(K["ready"])
        self.progress.setValue(0)
        self.update_controls()

    def options(self):
        begin = (
            self.date_from.date().toString("yyyy-MM-dd") if self.limit_dates.isChecked() else None
        )
        end = self.date_to.date().toString("yyyy-MM-dd") if self.limit_dates.isChecked() else None
        if begin and end and begin > end:
            raise UserError(
                "\uc2dc\uc791\uc77c\uc740 \uc885\ub8cc\uc77c\ubcf4\ub2e4 \ub2a6\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
            )
        return AnalysisOptions(
            scope=self.scope.currentData(),
            equipment_basis=self.basis.currentData(),
            date_from=begin,
            date_to=end,
            duration_unit=self.units.currentData(),
            deduplicate=self.dedup.isChecked(),
            top_n=self.top.value(),
        )

    def analysis_inputs(self):
        if self.loaded is None:
            raise UserError(K["ready"])
        if (
            self.sheets.currentText() != self.loaded.sheet
            or self.header_row.value() != self.loaded.header_row
        ):
            raise UserError(
                "\uc2dc\ud2b8/\uc81c\ubaa9 \ud589\uc744 \ubcc0\uacbd\ud55c \ud6c4\uc5d0\ub294 \uc2dc\ud2b8 \uc77d\uae30\ub97c \ub20c\ub7ec\uc8fc\uc138\uc694."
            )
        return (
            replace(self.loaded, mapping=self.loaded.mapping.copy()),
            self.store.load(),
            self.options(),
        )

    def analyze(self):
        try:
            loaded, config, options = self.analysis_inputs()
        except Exception as exc:
            self.show_error(exc)
            return
        self.run_task(
            lambda progress: run_analysis(loaded, config, options, progress), self.analysis_ready
        )

    def analysis_ready(self, result):
        self._apply_result(result)

    def _apply_result(self, result, *, preserve_navigation=False):
        self.last_reports = None
        self.result = result
        self._analysis_stale = False
        for key, label in self.card_labels.items():
            value = result.metrics[key]
            label.setText(
                "-"
                if value is None
                else f"{value:,.1f}"
                if key == "mean_minutes"
                else f"{value:,.0f}"
            )
        for key in ("equipment", "line", "type"):
            self.panes[key].set_frame(result.tables[key])
        for key in ("component", "component_trend"):
            self.panes[key].set_frame(result.tables.get(key, pd.DataFrame()))
        frames = []
        for equipment in result.tables["equipment"]["equipment"]:
            table = type_breakdown(result.selected, equipment)
            table.insert(0, "equipment", equipment)
            frames.append(table)
        self.panes["equipment_types"].set_frame(
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        )
        previous = self.chart_equipment.currentText()
        self.chart_equipment.blockSignals(True)
        self.chart_equipment.clear()
        self.chart_equipment.addItems([str(v) for v in result.tables["equipment"]["equipment"]])
        if previous in result.tables["equipment"]["equipment"].tolist():
            self.chart_equipment.setCurrentText(previous)
        self.chart_equipment.blockSignals(False)
        has_product = result.metrics["product_count"] > 0
        self.panes["cross"].set_frame(result.tables["triple" if has_product else "equipment_type"])
        for key, frame in (("detail", result.selected), ("review", result.tables["review"])):
            self.panes[key].set_frame(self.classification_frame(frame, review=key == "review"))
            self._grid_columns(self.panes[key], self.panes[key].extra_columns.isChecked())
        info = [
            f"{K['period']}: {result.metrics['period']}",
            f"{K['basis']}: {K[result.options.equipment_basis]}",
            f"{K['raw_rows']}: {result.metrics['source_rows']:,}  |  {K['excluded_rows']}: {result.metrics['excluded_rows']:,}",
            f"{K['name_mapped']}: {result.metrics['mapped_name_rows']:,} / {result.metrics['selected_rows']:,}",
            f"{K['review_tab']}: {result.metrics['review_rows']:,}  |  {K['auto_resolved_rows']}: {result.metrics['auto_resolved_rows']:,}  |  {K['target_info']}: {result.metrics['missing_target_rows']:,}",
            "",
            *result.notes,
        ]
        self.notes.setPlainText("\n\n".join(info))
        self.draw_chart()
        self.navigation.update_counts(result.metrics["review_rows"], len(result.selected))
        if not preserve_navigation:
            self.show_page("summary")
            self.source_toggle.setChecked(False)
        self.condition_summary.setText(
            f"{result.loaded.path.name}  |  {result.metrics['selected_rows']:,}건  |  "
            f"{K[result.options.equipment_basis]}"
        )
        self.status_label.setText(K["done"])
        self.update_controls()

    @staticmethod
    def classification_frame(frame: pd.DataFrame, *, review: bool = False) -> pd.DataFrame:
        frame = frame.copy()
        if "classification_mode" in frame:
            multiple = frame["classification_mode"].eq("multiple")
            for key in ("major", "middle", "minor"):
                if key in frame:
                    frame.loc[multiple, key] = ""
            frame["combination_decision"] = [
                "복수 · 확정"
                if mode == "multiple" and status == K["manual_multi"]
                else "복수 · 자동"
                if mode == "multiple" and status == K["auto"]
                else "복수 · 검토"
                if mode == "multiple"
                else "단일 · 확정"
                if status == K["manual"]
                else str(status)
                if status in UNMATCHED
                else "단일"
                if mode == "single"
                else str(status)
                for mode, status in zip(frame["classification_mode"], frame["status"])
            ]
        leading = [
            "major",
            "middle",
            "minor",
            "raw_equipment_name",
            "raw_mid",
            "raw_small",
            "raw_description",
            "component_types",
            "combination_decision",
            "date",
            "minutes",
            "target",
            "product",
            "status",
            "classification_reason",
            "review_reason",
            "review_action",
            "candidate_evidence",
            "type",
            "equipment",
            "classification_mode",
            "component_count",
            "component_details",
            "combination_key",
        ]
        columns = [column for column in leading if column in frame]
        return frame.loc[:, columns + [column for column in frame if column not in columns]]

    def save_report(self):
        if self.loaded is None:
            return
        default = output_root() / f"Equipment_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Excel + PDF \uc800\uc7a5",
            str(default),
            "Excel (*.xlsx)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        paths = report_paths(path)
        existing = [p for p in (paths.excel, paths.pdf) if p.exists()]
        if existing:
            message = (
                "\ub2e4\uc74c \uae30\uc874 \uacb0\uacfc\ub97c \uad50\uccb4\ud560\uae4c\uc694?\n\n"
                + "\n".join(str(p) for p in existing)
            )
            if (
                QMessageBox.question(
                    self,
                    "\ub36e\uc5b4\uc4f0\uae30 \ud655\uc778",
                    message,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        try:
            loaded, config, options = self.analysis_inputs()
        except Exception as exc:
            self.show_error(exc)
            return
        self.last_reports = None

        def task(progress):
            # One latest persisted snapshot feeds BOTH exports. No stale PDF names.
            result = run_analysis(loaded, config, options, lambda n, t: progress(int(n * 0.32), t))
            saved = export_bundle(
                result,
                paths.excel,
                lambda n, t: progress(32 + int(n * 0.68), t),
                overwrite=bool(existing),
            )
            return result, saved

        self.run_task(task, self.report_ready)

    def report_ready(self, payload):
        result, paths = payload
        self.analysis_ready(result)
        self.last_reports = paths
        self.status_label.setText(
            "Excel + PDF \uc0dd\uc131 \uc644\ub8cc | " + str(paths.excel.parent)
        )
        self.notice(
            "\ub450 \uac1c\uc758 \uacb0\uacfc\ud30c\uc77c\uc744 \uc800\uc7a5\ud588\uc2b5\ub2c8\ub2e4.\n\nExcel: "
            + str(paths.excel)
            + "\n\nPDF: "
            + str(paths.pdf)
        )

    def edit_report_settings(self):
        try:
            dialog = ReportSettingsDialog(self.store, self)
        except Exception as exc:
            self.show_error(exc)
            return
        dialog.exec()

    def edit_names(self):
        try:
            dialog = EquipmentNamesDialog(self.store, self.loaded, self)
        except Exception as exc:
            self.show_error(exc)
            return
        dialog.exec()
        if dialog.changed:
            if self.loaded is not None:
                self.status_label.setText(
                    "\ucd5c\uc2e0 \uc124\ube44\uba85\uc73c\ub85c \ubd84\uc11d \uacb0\uacfc\ub97c \uac31\uc2e0\ud569\ub2c8\ub2e4."
                )
                self.analyze()
            else:
                self.status_label.setText(K["autosave"])

    def edit_columns(self):
        if self.loaded is None:
            return
        dialog = ColumnMappingDialog(self.loaded, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mapping = dialog.mapping()
        if mapping == self.loaded.mapping:
            return
        try:
            # Record IDs depend on the mapped columns: carry saved corrections over to the new IDs.
            moved = self.store.rekey_overrides(
                dict(
                    zip(
                        event_ids(self.loaded, self.loaded.mapping), event_ids(self.loaded, mapping)
                    )
                )
            )
            self.store.save_mapping(self.loaded.headers, mapping)
        except Exception as exc:
            self.show_error(exc)
            return
        self.loaded.mapping = mapping
        self.mark_stale()
        message = "컬럼 매핑을 저장했습니다. 같은 제목 행을 가진 파일에는 다음부터 자동 적용됩니다."
        if moved:
            message += f"\n기존 수동 보정 {moved:,}건을 새 매핑의 기록 ID로 옮겼습니다."
        self.notice(message)

    def edit_rules(self):
        try:
            dialog = RuleEditor(self.store, self)
        except Exception as exc:
            self.show_error(exc)
            return
        dialog.exec()
        if dialog.changed:
            self.mark_stale()
            if self.loaded is not None:
                self.analyze()

    def show_page(self, key):
        self.navigation.show_page(key)

    @staticmethod
    def _grid_columns(pane, show_extra):
        widths = {
            "major": 88,
            "middle": 105,
            "minor": 150,
            "raw_equipment_name": 128,
            "raw_mid": 110,
            "raw_small": 110,
            "raw_description": 300,
            "component_types": 205,
            "combination_decision": 108,
        }
        for index, key in enumerate(pane.model.frame.columns):
            hidden = key in ("event_id", "record_id", "__source_row") or (
                not show_extra and key not in PRIMARY_FIELDS
            )
            pane.table.setColumnHidden(index, hidden)
            if key in widths:
                pane.table.setColumnWidth(index, widths[key])
        pane.table.verticalHeader().setDefaultSectionSize(46)
        pane.table.resizeRowsToContents()
        for row in range(pane.proxy.rowCount()):
            pane.table.setRowHeight(row, max(46, min(120, pane.table.rowHeight(row))))

    def _grid_menu(self, pane, point):
        if self.task is not None or self._grid_refresh_pending or self._analysis_stale:
            return
        index = pane.table.indexAt(point)
        if not index.isValid():
            return
        pane.table.selectRow(index.row())
        record = pane.selected_record()
        if not record or not record.get("event_id"):
            return
        try:
            existing = self.store.override(record["event_id"])
        except Exception as exc:
            self.show_error(exc)
            return
        menu = QMenu(pane.table)
        edit_action = menu.addAction("분류 편집 (단일·복수)")
        clear_class = menu.addAction("분류 보정 해제")
        class_patch = {
            key: None
            for key in ("major", "middle", "minor", "classification_components")
            if key in existing
        }
        clear_class.setEnabled(bool(class_patch))
        menu.addSeparator()
        clear_all = menu.addAction("이 기록의 수동 보정 모두 해제")
        all_patch = {key: None for key in FIELDS if key in existing}
        clear_all.setEnabled(bool(all_patch))
        selected = menu.exec(pane.table.viewport().mapToGlobal(point))
        if selected is edit_action:
            column = pane.model.frame.columns.get_loc("component_types")
            pane.open_classification_editor(pane.proxy.index(index.row(), column))
            return
        patch = (
            class_patch if selected is clear_class else all_patch if selected is clear_all else None
        )
        if patch and self._save_grid_edit(record, patch):
            self._grid_edit_saved(record, patch)

    def current_page_key(self):
        return self.navigation.current_page_key()

    def _save_grid_edit(self, record, patch):
        if self.task is not None or self._grid_refresh_pending:
            return False
        try:
            if self.result is None or self._analysis_stale:
                raise UserError("분석을 먼저 실행한 뒤 수정하세요.")
            event_id = str(record.get("event_id") or "")
            if not event_id or not self.result.selected["event_id"].eq(event_id).any():
                raise UserError("현재 분석 결과에 없는 기록입니다. 분석을 다시 실행하세요.")
            if not patch or set(patch) - set(FIELDS):
                raise UserError("수정할 수 없는 항목입니다.")
            values = {key: str(value or "").strip() for key, value in patch.items()}
            error = validate(
                values, confirm_components=bool(values.get("classification_components"))
            )
            if error:
                raise UserError(error)
            self.store.update_override(event_id, patch)
        except Exception as exc:
            self.show_error(exc)
            return False
        self.last_reports = None
        return True

    def _grid_edit_saved(self, record, patch):
        if self._grid_refresh_pending:
            return
        self._grid_view_state = {
            "page": self.current_page_key(),
            "panes": {key: self._pane_state(pane) for key, pane in self.panes.items()},
        }
        self._grid_refresh_pending = True
        self.status_label.setText("수정값 저장 완료 · 분석 결과를 갱신합니다.")
        self.update_controls()
        QTimer.singleShot(0, self._refresh_after_grid_edit)

    @staticmethod
    def _pane_state(pane):
        column = pane.proxy.sortColumn()
        current = pane.table.currentIndex()
        record = pane.selected_record() or {}
        return {
            "sort": pane.model.frame.columns[column] if column >= 0 else None,
            "order": pane.proxy.sortOrder(),
            "event_id": record.get("event_id"),
            "row": max(0, current.row()),
            "scroll_x": pane.table.horizontalScrollBar().value(),
            "scroll_y": pane.table.verticalScrollBar().value(),
            "widths": {
                key: pane.table.columnWidth(i) for i, key in enumerate(pane.model.frame.columns)
            },
        }

    @staticmethod
    def _restore_pane_state(pane, state):
        columns = pane.model.frame.columns
        for key, width in state["widths"].items():
            if key in columns:
                pane.table.setColumnWidth(columns.get_loc(key), width)
        if state["sort"] in columns:
            pane.table.sortByColumn(columns.get_loc(state["sort"]), state["order"])
        elif state["sort"] is None:
            pane.proxy.sort(-1)
        row = min(state["row"], pane.proxy.rowCount() - 1)
        if state["event_id"] and "event_id" in columns:
            source = pane.model.frame.index[pane.model.frame.event_id.eq(state["event_id"])]
            if len(source):
                visible = pane.proxy.mapFromSource(pane.model.index(int(source[0]), 0))
                if visible.isValid():
                    row = visible.row()
        if row >= 0:
            pane.table.selectRow(row)
        pane.table.horizontalScrollBar().setValue(state["scroll_x"])
        pane.table.verticalScrollBar().setValue(state["scroll_y"])

    def _refresh_after_grid_edit(self):
        self._grid_refresh_pending = False
        if self.loaded is None or self.result is None:
            self.update_controls()
            return
        try:
            loaded = replace(self.result.loaded, mapping=self.result.loaded.mapping.copy())
            config, options = self.store.load(), replace(self.result.options)
        except Exception as exc:
            self._analysis_stale = True
            self.show_error(exc)
            self.update_controls()
            return
        self._grid_reanalyzing = True

        def ready(result):
            state = self._grid_view_state
            self._apply_result(result, preserve_navigation=True)
            if state:
                self.show_page(state["page"])
                for key, pane_state in state["panes"].items():
                    self._restore_pane_state(self.panes[key], pane_state)
            self._grid_view_state = None
            self.status_label.setText("수정값 저장 및 분석 결과 갱신 완료")

        self.run_task(lambda progress: run_analysis(loaded, config, options, progress), ready)

    def mark_stale(self, *_):
        if self.result is not None:
            self._analysis_stale = True
            self.status_label.setText(K["stale"])
        self.update_controls()

    @staticmethod
    def open_local_path(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_config(self):
        self.open_local_path(self.store.config_dir)

    def open_excel(self):
        if self.last_reports:
            self.open_local_path(self.last_reports.excel)

    def open_pdf(self):
        if self.last_reports:
            self.open_local_path(self.last_reports.pdf)

    def open_output(self):
        if self.last_reports:
            self.open_local_path(self.last_reports.excel.parent)

    def clear_chart(self):
        if self._chart_canvas is not None:
            self.chart_layout.removeWidget(self._chart_canvas)
            self._chart_canvas.figure.clear()
            self._chart_canvas.deleteLater()
            self._chart_canvas = None
        if hasattr(self, "chart_empty"):
            self.chart_empty.setText(K["empty"])
            self.chart_empty.show()

    def draw_chart(self, *_):
        if not hasattr(self, "chart_layout"):
            return
        self.clear_chart()
        self.chart_equipment.setVisible(self.chart_choice.currentData() == "equipment_types")
        if self.result is None:
            return
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

            from report.charts import donut_figure, figure_for

            key = self.chart_choice.currentData()
            if key == "equipment_types":
                equipment = self.chart_equipment.currentText()
                table = type_breakdown(self.result.selected, equipment)
                figure = donut_figure(
                    table,
                    equipment,
                    self.result.config_snapshot["settings"].get("donut_top_n", 5),
                    self.chart_metric.currentData(),
                )
            else:
                table = self.result.tables[key]
                field = "period" if key.startswith("trend_") else key
                figure = figure_for(
                    table,
                    field,
                    self.chart_metric.currentData(),
                    "trend" if field == "period" else "bar",
                    self.result.options.top_n,
                )
            self._chart_canvas = FigureCanvasQTAgg(figure)
            self.chart_layout.addWidget(self._chart_canvas, 1)
            self.chart_empty.hide()
            self._chart_canvas.draw_idle()
        except Exception:
            logging.getLogger(__name__).exception("Chart preview failed")
            self.chart_empty.setText(
                "\uadf8\ub798\ud504\ub97c \ud45c\uc2dc\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. logs\ub97c \ud655\uc778\ud558\uc138\uc694."
            )

    def closeEvent(self, event):
        if self.task is not None or self._grid_refresh_pending:
            self.notice(K["close_busy"])
            event.ignore()
            return
        event.accept()
