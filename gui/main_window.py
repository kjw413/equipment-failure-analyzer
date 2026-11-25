from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

import pandas as pd
from PySide6.QtCore import QDate, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.classification_candidates import parse_candidates
from core.classification_catalog import fault_catalog_categories
from core.config import ConfigStore, output_root
from core.corrections import FIELDS, validate
from core.defaults_merge import describe
from core.equipment_breakdown import type_breakdown
from core.equipment_names import organization_filter_choices
from core.excel_loader import load_excel, validate_path
from core.fault_components import CATEGORY_FIELDS
from core.i18n import UNMATCHED, K
from core.models import AnalysisOptions, UserError
from core.preprocessing import event_ids
from core.rules import read_rules
from core.service import run_analysis
from gui.category_index import ClassificationPathIndex
from gui.dialogs import ColumnMappingDialog, EquipmentNamesDialog, RuleEditor
from gui.grouped_header import PRIMARY_FIELDS, GroupedHeader
from gui.navigation import WorkspaceNavigation
from gui.report_settings import ReportSettingsDialog
from gui.review_color_settings import ReviewColorSettingsDialog
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
        self._pending_classifications = {}
        self._pending_grid_events = set()
        self._pending_grid_update_queued = False
        self._confirmed_overrides = self.config.get("overrides", {})
        self._classification_categories = ClassificationPathIndex(
            fault_catalog_categories(
                self.config["rules"],
                self.config.get("classification_catalog", {}).get("equipment_types"),
            )
        )
        self._classification_catalog_stamp = None
        self._selected_event_ids = set()
        self._current_event_ids = set()
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
        self._build_source_controls(layout)
        self._build_analysis_controls(layout)
        self._build_report_controls(layout)
        self._build_tabs(layout)
        self._build_status(layout)

    def _build_header(self, layout):
        header = QHBoxLayout()
        title = QLabel(K["app"])
        title.setObjectName("title")
        subtitle = QLabel(K["offline"] + f"  |  v{VERSION}")
        subtitle.setObjectName("muted")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(subtitle)
        self.settings_button = QToolButton()
        self.settings_button.setText("기준정보 · 설정")
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.settings_button)
        self.names_button = menu.addAction(K["name_editor"], self.edit_names)
        self.rules_button = menu.addAction(K["rules"], self.edit_rules)
        menu.addSeparator()
        self.review_colors_action = menu.addAction("검토필요 색상 설정", self.edit_review_colors)
        self.folder_button = menu.addAction(K["config"], self.open_config)
        self.settings_button.setMenu(menu)
        header.addWidget(self.settings_button)
        self.actions.extend(
            [
                self.settings_button,
                self.names_button,
                self.rules_button,
                self.review_colors_action,
                self.folder_button,
            ]
        )
        layout.addLayout(header)

    def _build_source_controls(self, layout):
        self.source_panel = QWidget()
        source = QHBoxLayout(self.source_panel)
        source.setContentsMargins(0, 0, 0, 0)
        self.browse_change_button = self.button("파일 변경", self.browse, source)
        self.file_settings_button = self.button("파일 읽기 설정…", self.edit_file_settings, source)
        self.condition_summary = QLabel()
        self.condition_summary.setObjectName("muted")
        self.condition_summary.setWordWrap(True)
        self.condition_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.condition_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source.addWidget(self.condition_summary, 1)
        layout.addWidget(self.source_panel)

        self.drop = DropArea()
        self.drop.browse_requested.connect(self.browse)
        self.drop.file_dropped.connect(self.load_path)
        self.drop.invalid_drop.connect(self.notice)
        layout.addWidget(self.drop)

    def _build_analysis_controls(self, layout):
        self.filters_panel = QWidget()
        filters = QHBoxLayout(self.filters_panel)
        filters.setContentsMargins(0, 0, 0, 0)
        self.factory_filter = QComboBox()
        self.factory_filter.addItem(K["all_factories"], None)
        self.team_filter = QComboBox()
        self.team_filter.addItem(K["all_teams"], None)
        for combo, name in ((self.factory_filter, "공장"), (self.team_filter, "팀")):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(12)
            label = QLabel(name)
            label.setBuddy(combo)
            filters.addWidget(label)
            filters.addWidget(combo)
        self.limit_dates = QCheckBox(K["date_filter"])
        filters.addWidget(self.limit_dates)
        self.date_range = QWidget()
        dates = QHBoxLayout(self.date_range)
        dates.setContentsMargins(0, 0, 0, 0)
        self.date_from = QDateEdit(QDate.currentDate())
        self.date_to = QDateEdit(QDate.currentDate())
        for edit, name in ((self.date_from, "시작일"), (self.date_to, "종료일")):
            edit.setAccessibleName(name)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setCalendarPopup(True)
        dates.addWidget(self.date_from)
        dates.addWidget(QLabel("~"))
        dates.addWidget(self.date_to)
        filters.addWidget(self.date_range)
        filters.addStretch()
        self.advanced_toggle = QPushButton("고급 조건")
        self.advanced_toggle.setCheckable(True)
        filters.addWidget(self.advanced_toggle)
        layout.addWidget(self.filters_panel)

        self.advanced_panel = QWidget()
        advanced = QGridLayout(self.advanced_panel)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.addWidget(QLabel(K["scope"]), 0, 0)
        self.scope = QComboBox()
        self.scope.addItem(K["fault_only"], "fault")
        self.scope.addItem(K["all_stops"], "all")
        advanced.addWidget(self.scope, 0, 1)
        advanced.addWidget(QLabel(K["basis"]), 0, 2)
        self.basis = QComboBox()
        for value in ("mapped", "group", "factory", "team", "target", "registered", "family"):
            self.basis.addItem(K[value], value)
        advanced.addWidget(self.basis, 0, 3)
        advanced.addWidget(QLabel(K["units"]), 0, 4)
        self.units = QComboBox()
        for label, value in (
            (K["minutes_unit"], "minutes"),
            (K["hours_unit"], "hours"),
            (K["seconds_unit"], "seconds"),
            (K["excel_days"], "excel_days"),
        ):
            self.units.addItem(label, value)
        advanced.addWidget(self.units, 0, 5)
        self.dedup = QCheckBox(K["dedup"])
        advanced.addWidget(self.dedup, 1, 0, 1, 2)
        advanced.addWidget(QLabel("분석 상위 항목 수"), 1, 2)
        self.top = QSpinBox()
        self.top.setRange(1, 30)
        self.top.setValue(int(self.config["settings"].get("top_n", 10)))
        self.top.setToolTip(
            "그래프의 표시 항목 수와 정지시간 상위 기록을 설정합니다. 종합 보고서 순위는 보고서 옵션에서 설정합니다."
        )
        advanced.addWidget(self.top, 1, 3)
        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        layout.addWidget(self.advanced_panel)

    def _build_report_controls(self, layout):
        self.run_panel = QWidget()
        run = QHBoxLayout(self.run_panel)
        run.setContentsMargins(0, 0, 0, 0)
        self.analyze_button = self.button("분석 실행", self.standardize, run, "primary")

        self.report_button = QToolButton()
        self.report_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        options = QMenu(self.report_button)
        self.save_report_action = QAction("보고서 저장", self.report_button)
        self.save_report_action.triggered.connect(self.save_report)
        self.report_button.setDefaultAction(self.save_report_action)
        self.report_settings_action = options.addAction("보고서 옵션…", self.edit_report_settings)
        self.report_button.setMenu(options)
        run.addWidget(self.report_button)

        self.last_results_button = QToolButton()
        self.last_results_button.setText("마지막 결과")
        self.last_results_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        results = QMenu(self.last_results_button)
        self.open_button = results.addAction("Excel 열기", self.open_excel)
        self.pdf_button = results.addAction("PDF 열기", self.open_pdf)
        self.output_button = results.addAction("결과 폴더 열기", self.open_output)
        self.last_results_button.setMenu(results)
        run.addWidget(self.last_results_button)
        run.addStretch()
        layout.addWidget(self.run_panel)

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
        self.panes["detailed_equipment"] = TablePane(
            description="라인·상세설비별 고장이력입니다. 부품이 미기재이거나 최종 분류를 검토 중이어도 확인된 상세설비는 포함합니다. 미확인 설비는 '상세설비 미상'으로 표시하며 각 이력·정지시간은 한 번 집계합니다."
        )
        component_note = (
            "고장이력 한 건의 최종 분류는 하나입니다. "
            "미확정 추천 후보는 부품별 확정 건수에 포함하지 않습니다. "
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
        fault_detail = TablePane(
            sort_policy="source",
            description="한 고장이력을 부품·증상별로 나눈 표입니다. 같은 기록의 정지시간을 반복 배분하지 않습니다. "
            "행을 더블클릭하면 원본 기록으로 이동하여 분류를 수정할 수 있습니다.",
        )
        fault_detail.table.doubleClicked.connect(self._open_fault_source)
        self.panes["fault_detail"] = fault_detail
        self._build_chart_tab()
        self.navigation = WorkspaceNavigation(
            {**self.panes, "summary": self.summary, "chart": self.chart_page}
        )
        self.navigation.chart_requested.connect(self._select_table_chart)
        self.tabs = self.navigation.tabs
        layout.addWidget(self.navigation, 1)
        for key in ("review", "detail"):
            pane = self.panes[key]
            pane.prepare_classification_picker = self._refresh_classification_categories
            if key == "review":
                pane.enable_corner_copy()
            pane.configure_editing(
                lambda: self._classification_categories,
                self._save_grid_edit,
                self._grid_override,
                defer_classification=True,
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
            toolbar = pane.layout().itemAt(0).layout()
            toolbar.insertWidget(1, pane.extra_columns)
            pane.original_button = QPushButton("원본 행 보기")
            pane.original_button.setEnabled(False)
            toolbar.insertWidget(2, pane.original_button)
            pane.original_button.clicked.connect(
                lambda _checked=False, target=pane: self._open_original_row(target)
            )
            pane.table.selectionModel().selectionChanged.connect(
                lambda _selected, _deselected, target=pane: self._update_original_button(target)
            )
            pane.description.setText(
                "최종 분류 셀에서 후보를 비교하세요. 확정 대기 분류는 [분류 적용 및 재분석]을 눌러 저장합니다."
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
        self.chart_metric.addItem(K["count"], "count")
        self.chart_metric.addItem(K["total"], "total_minutes")
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
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
            self.factory_filter,
            self.team_filter,
            self.units,
            self.limit_dates,
            self.date_from,
            self.date_to,
            self.dedup,
            self.top,
        ]
        for combo in (self.scope, self.basis, self.units):
            combo.currentIndexChanged.connect(self.mark_stale)
        self.factory_filter.currentIndexChanged.connect(self._factory_filter_changed)
        self.team_filter.currentIndexChanged.connect(self._organization_filter_changed)
        for check in (self.limit_dates, self.dedup):
            check.toggled.connect(self.mark_stale)
        self.date_from.dateChanged.connect(self.mark_stale)
        self.date_to.dateChanged.connect(self.mark_stale)
        self.top.valueChanged.connect(self.mark_stale)

    @staticmethod
    def _set_filter_choices(combo, all_label, values, selected, *, preserve_unavailable=True):
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(all_label, None)
            for value in values:
                combo.addItem(value, value)
            index = combo.findData(selected)
            if selected is not None and index < 0 and preserve_unavailable:
                combo.addItem(f"{selected} (현재 자료 없음)", selected)
                index = combo.count() - 1
            combo.setCurrentIndex(max(index, 0))
            combo.setToolTip(combo.currentText())
        finally:
            combo.blockSignals(blocked)

    def _refresh_organization_filters(
        self, *, reset=False, settings=None, loaded=None, preserve_team_unavailable=True
    ):
        source = self.loaded if loaded is None else loaded
        factory = None if reset else self.factory_filter.currentData()
        team = None if reset else self.team_filter.currentData()
        if source is None:
            choices = {"factories": [], "teams": []}
        else:
            config = self.store.load() if settings is None else settings
            choices = organization_filter_choices(source, config, factory=factory)
        self._set_filter_choices(
            self.factory_filter,
            K["all_factories"],
            choices["factories"],
            factory,
            preserve_unavailable=not reset,
        )
        self._set_filter_choices(
            self.team_filter,
            K["all_teams"],
            choices["teams"],
            team,
            preserve_unavailable=not reset and preserve_team_unavailable,
        )

    def _factory_filter_changed(self, *_):
        try:
            self._refresh_organization_filters(preserve_team_unavailable=False)
        except Exception as exc:
            self.show_error(exc)
        self._organization_filter_changed()

    def _organization_filter_changed(self, *_):
        for combo in (self.factory_filter, self.team_filter):
            combo.setToolTip(combo.currentText())
        self.last_reports = None
        self.mark_stale()

    def _organization_filter_summary(self, options=None):
        factory = self.factory_filter.currentData() if options is None else options.factory
        team = self.team_filter.currentData() if options is None else options.team
        return "  |  ".join(
            f"{K[key]}: {value}"
            for key, value in (("factory", factory), ("team", team))
            if value is not None
        )

    def _update_condition_summary(self):
        if self.loaded is None:
            self.condition_summary.clear()
            self.condition_summary.setToolTip("")
            return
        parts = [self.loaded.path.name, f"원본 {len(self.loaded.frame):,}행"]
        if self.result is not None and not self._analysis_stale:
            parts.append(f"분석 {self.result.metrics['selected_rows']:,}건")
        parts.extend((self.factory_filter.currentText(), self.team_filter.currentText()))
        if self.limit_dates.isChecked():
            parts.append(f"{self.date_from.text()} ~ {self.date_to.text()}")
        else:
            parts.append("전체 기간")
        parts.extend((self.scope.currentText(), self.basis.currentText()))
        summary = "  |  ".join(parts)
        self.condition_summary.setText(summary)
        self.condition_summary.setToolTip(
            f"{self.loaded.path}\n{self.loaded.sheet} · 제목 {self.loaded.header_row}행\n{summary}"
        )

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
        cards = QGridLayout()
        self.card_labels = {}
        for index, (key, label) in enumerate(
            [
                ("selected_rows", K["count"]),
                ("total_minutes", K["total"]),
                ("mean_minutes", K["mean"]),
                ("auto_rows", "완전 자동분류"),
                ("partial_rows", "부분 자동분류"),
                ("review_rows", K["review_tab"]),
            ]
        ):
            group = QGroupBox(label)
            group_layout = QVBoxLayout(group)
            value = QLabel("-")
            value.setStyleSheet("font-size: 30px; font-weight: 700; padding: 12px; color: #355767;")
            group_layout.addWidget(value)
            cards.addWidget(group, index // 3, index % 3)
            self.card_labels[key] = value
        layout.addLayout(cards)
        self.notes = QTextBrowser()
        self.notes.setPlainText("Excel 파일을 등록한 뒤 [분석 실행]을 누르세요.")
        layout.addWidget(self.notes, 1)
        return page

    def notice(self, message):
        QMessageBox.information(self, K["notice"], str(message))

    def show_error(self, message):
        self.status_label.setText(K["error"])
        QMessageBox.warning(self, K["error"], str(message))

    def _update_pending_count(self):
        pending = len(self._current_event_ids.intersection(self._pending_classifications))
        self.analyze_button.setText(
            f"분류 {pending:,}건 적용 및 재분석" if pending else "분석 실행"
        )
        self.save_report_action.setToolTip(
            "대기 중인 분류를 보고서에 반영하려면 [분류 적용 및 재분석]을 먼저 누르세요."
            if pending
            else "분석 Excel과 PDF를 저장합니다. 원본 검토표시는 Excel에 포함됩니다."
        )

    def update_controls(self):
        busy = self.task is not None or self._grid_refresh_pending
        has_file = self.loaded is not None
        has_reports = self.last_reports is not None
        self._update_pending_count()
        for widget in self.actions + self.option_widgets + [self.drop]:
            widget.setEnabled(not busy)
        for widget in (
            self.analyze_button,
            self.report_button,
            self.save_report_action,
            self.report_settings_action,
            self.filters_panel,
            self.advanced_toggle,
            self.advanced_panel,
        ):
            widget.setEnabled(not busy and has_file)
        for widget in (
            self.source_panel,
            self.filters_panel,
            self.run_panel,
        ):
            widget.setVisible(has_file)
        self.drop.setVisible(not has_file)
        self.advanced_panel.setVisible(has_file and self.advanced_toggle.isChecked())
        self.date_range.setVisible(self.limit_dates.isChecked())
        for key in ("detail", "review"):
            pane = self.panes[key]
            pane.set_editing_enabled(
                not busy and self.result is not None and not self._analysis_stale
            )
            self._update_original_button(pane)
        self.last_results_button.setVisible(has_reports)
        for widget in (
            self.last_results_button,
            self.open_button,
            self.pdf_button,
            self.output_button,
        ):
            widget.setEnabled(not busy and has_reports)
        self.chart_choice.setEnabled(not busy)
        self.chart_metric.setEnabled(not busy)
        self.chart_equipment.setEnabled(not busy)
        self.date_from.setEnabled(not busy and has_file and self.limit_dates.isChecked())
        self.date_to.setEnabled(not busy and has_file and self.limit_dates.isChecked())
        self.progress.setVisible(self.task is not None)
        self._update_condition_summary()

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
        self.status_label.setText(f"{path.name} 읽는 중…")
        lookup = self.store.saved_mapping
        self.run_task(
            lambda progress: load_excel(
                path, config["column_mapping"], sheet, header_row, progress, lookup
            ),
            self.loaded_ready,
        )

    def loaded_ready(self, loaded):
        self.clear_results()
        self.loaded = loaded
        self._current_event_ids = set(event_ids(loaded, loaded.mapping))
        self._refresh_organization_filters(reset=True)
        self.panes["raw"].search.clear()
        self.panes["raw"].set_frame(loaded.frame.drop(columns=["__source_row"], errors="ignore"))
        self.notes.setPlainText("공장·팀·기간을 선택한 뒤 [분석 실행]을 누르세요.")
        self.show_page("raw")
        self.status_label.setText("파일 등록 완료. 분석을 실행할 수 있습니다.")
        self.update_controls()

    def edit_file_settings(self):
        if self.loaded is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("파일 읽기 설정")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        sheets = QComboBox()
        sheets.addItems(self.loaded.sheet_names)
        sheets.setCurrentText(self.loaded.sheet)
        form.addRow("시트", sheets)
        header = QSpinBox()
        header.setRange(0, 250000)
        header.setSpecialValueText("자동 감지")
        header.setValue(self.loaded.header_row)
        form.addRow("제목 행", header)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        apply_button = buttons.addButton("적용 후 읽기", QDialogButtonBox.ButtonRole.AcceptRole)
        mapping_button = buttons.addButton("컬럼 매핑…", QDialogButtonBox.ButtonRole.ActionRole)
        mapping_button.clicked.connect(self.edit_columns)
        apply_button.setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def update_mapping_button():
            current = (
                sheets.currentText() == self.loaded.sheet
                and header.value() == self.loaded.header_row
            )
            mapping_button.setEnabled(current)
            mapping_button.setToolTip(
                "" if current else "시트와 제목 행을 적용한 뒤 매핑할 수 있습니다."
            )

        def select_sheet():
            header.setValue(
                self.loaded.header_row if sheets.currentText() == self.loaded.sheet else 0
            )
            update_mapping_button()

        sheets.currentIndexChanged.connect(select_sheet)
        header.valueChanged.connect(update_mapping_button)
        dialog.setMinimumWidth(370)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_path(self.loaded.path, sheets.currentText(), header.value() or None)

    def clear_results(self):
        self.result = None
        self.last_reports = None
        self._analysis_stale = False
        self._grid_refresh_pending = False
        self._grid_view_state = None
        self._current_event_ids = set()
        for pane in self.panes.values():
            pane.set_frame(pd.DataFrame())
        for label in self.card_labels.values():
            label.setText("-")
        self.clear_chart()
        self.navigation.set_product_available(False)
        self.navigation.update_counts()

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
            factory=self.factory_filter.currentData(),
            team=self.team_filter.currentData(),
        )

    def analysis_inputs(self):
        if self.loaded is None:
            raise UserError(K["ready"])
        config = self.store.load()
        self._refresh_organization_filters(settings=config)
        self._update_condition_summary()
        return (
            replace(self.loaded, mapping=self.loaded.mapping.copy()),
            config,
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

    def standardize(self):
        """Only this explicit button commits staged classifications."""
        if self.task is not None or self._grid_refresh_pending:
            return
        count = 0
        try:
            loaded, config, options = self.analysis_inputs()
            ids = set(event_ids(loaded, loaded.mapping))
            batch = {
                key: value for key, value in self._pending_classifications.items() if key in ids
            }
            count = self.store.apply_classifications(batch)
            for event_id in batch:
                self._pending_classifications.pop(event_id, None)
            if count:
                config = self.store.load()
        except Exception as exc:
            if count:
                self._analysis_stale = True
                self.last_reports = None
            self.show_error(exc)
            self.update_controls()
            return
        if not count:
            self.run_task(
                lambda progress: run_analysis(loaded, config, options, progress),
                self.analysis_ready,
            )
            return
        self.last_reports = None
        self._grid_reanalyzing = True
        state = {
            "page": self.current_page_key(),
            "panes": {key: self._pane_state(pane) for key, pane in self.panes.items()},
        }

        def ready(result):
            self._apply_result(result, preserve_navigation=True)
            self.show_page(state["page"])
            for key, pane_state in state["panes"].items():
                self._restore_pane_state(self.panes[key], pane_state)
            self.status_label.setText(f"표준화 완료 · 임시 분류 {count:,}건 일괄 적용")

        self.run_task(lambda progress: run_analysis(loaded, config, options, progress), ready)

    def analysis_ready(self, result):
        self._apply_result(result)

    def _apply_result(self, result, *, preserve_navigation=False):
        self.last_reports = None
        self.result = result
        self._current_event_ids = set(result.all_records.event_id)
        self._selected_event_ids = set(result.selected.event_id)
        self._confirmed_overrides = result.config_snapshot.get("overrides", {})
        self._classification_categories = ClassificationPathIndex(
            fault_catalog_categories(
                result.config_snapshot["rules"],
                result.config_snapshot.get("classification_catalog", {}).get("equipment_types"),
            )
        )
        self._classification_catalog_stamp = None
        self._analysis_stale = False
        self._refresh_organization_filters(settings=result.config_snapshot, loaded=result.loaded)
        for key, label in self.card_labels.items():
            value = result.metrics.get(key, 0)
            label.setText(
                "-"
                if value is None
                else f"{value:,.1f}"
                if key == "mean_minutes"
                else f"{value:,.0f}"
            )
        for key in ("equipment", "line", "type"):
            self.panes[key].set_frame(result.tables[key])
        for key in ("component", "component_trend", "fault_detail", "detailed_equipment"):
            self.panes[key].set_frame(result.tables.get(key, pd.DataFrame()))
        fault_pane = self.panes["fault_detail"]
        if "record_id" in fault_pane.model.frame:
            fault_pane.table.setColumnHidden(
                fault_pane.model.frame.columns.get_loc("record_id"), False
            )
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
        self.panes["cross"].set_frame(result.tables["triple"] if has_product else pd.DataFrame())
        self.navigation.set_product_available(has_product)
        for key, frame in (("detail", result.selected), ("review", result.tables["review"])):
            self.panes[key].set_frame(self.classification_frame(frame, review=key == "review"))
            self._grid_columns(self.panes[key], self.panes[key].extra_columns.isChecked())
        self._update_pending_rows(self._pending_classifications)
        info = [
            f"{K['period']}: {result.metrics['period']}",
            f"{K['basis']}: {K[result.options.equipment_basis]}",
            self._organization_filter_summary(result.options) or "공장: 전체 공장  |  팀: 전체 팀",
            f"{K['raw_rows']}: {result.metrics['source_rows']:,}  |  {K['excluded_rows']}: {result.metrics['excluded_rows']:,}",
            f"{K['name_mapped']}: {result.metrics['mapped_name_rows']:,} / {result.metrics['selected_rows']:,}",
            f"자동처리 {result.metrics.get('auto_processed_rows', result.metrics['auto_rows']):,}건 = 완전 자동분류 {result.metrics['auto_rows']:,}건 + 부분 자동분류 {result.metrics.get('partial_rows', 0):,}건",
            "부분분류는 원문에서 확인한 항목을 보존하고 미기재 항목은 미상으로 표시합니다. 없는 정보의 추가 입력을 요구하지 않습니다.",
            f"{K['review_tab']}: {result.metrics['review_rows']:,}  |  {K['auto_resolved_rows']}: {result.metrics['auto_resolved_rows']:,}  |  {K['target_info']}: {result.metrics['missing_target_rows']:,}",
            "",
            *result.notes,
        ]
        self.notes.setPlainText("\n\n".join(info))
        self.draw_chart()
        self.navigation.update_counts(result.metrics["review_rows"], len(result.selected))
        if not preserve_navigation:
            if self.navigation.history_choice.currentData() == "raw":
                self.navigation.history_choice.setCurrentIndex(0)
            self.show_page("summary")
        self.status_label.setText(K["done"])
        self.update_controls()

    @staticmethod
    def classification_frame(frame: pd.DataFrame, *, review: bool = False) -> pd.DataFrame:
        frame = frame.copy()
        if "classification_mode" in frame:
            from core.known_classification import known_fields

            retained = {
                index: known_fields(record) for index, record in frame.to_dict("index").items()
            }
            unresolved = frame["classification_mode"].isin(("multiple", "ambiguous", "pending"))
            if "classification_candidates" in frame:
                unresolved |= frame["classification_mode"].ne("single") & frame[
                    "classification_candidates"
                ].map(lambda value: bool(parse_candidates(value)))
            for key in CATEGORY_FIELDS:
                if key in frame:
                    frame.loc[unresolved, key] = ""
            for index in frame.index[unresolved]:
                for key, value in retained[index].items():
                    frame.at[index, key] = value
            if "component_types" in frame:
                frame.loc[unresolved, "component_types"] = "미확정 · 후보 선택 필요"
            if "type" in frame:
                frame.loc[unresolved, "type"] = "미확정"
            frame["combination_decision"] = [
                "최종 미확정"
                if pending
                else "사용자확정"
                if status == K["manual"]
                else K.get("partial", "부분분류")
                if status == K.get("partial", "부분분류")
                else str(status)
                if status in UNMATCHED
                else "규칙분류"
                if mode == "single"
                else str(status)
                for mode, status, pending in zip(
                    frame["classification_mode"], frame["status"], unresolved
                )
            ]
        leading = [
            "major",
            "detail_equipment",
            "part_group",
            "middle",
            "minor",
            "repair_actions",
            "classification_missing_fields",
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

    def _open_fault_source(self, index):
        """A split classification row edits its one original event, never a copy."""
        source = self.panes["fault_detail"]
        row = source.proxy.mapToSource(index)
        if not row.isValid():
            return
        event_id = source.model.frame.iloc[row.row()].get("event_id")
        pane = self.panes["detail"]
        frame = pane.model.frame
        if "event_id" not in frame or not event_id:
            return
        matches = frame.index[frame["event_id"].eq(event_id)]
        if matches.empty:
            return
        pane.search.clear()
        position = frame.index.get_loc(matches[0])
        column = frame.columns.get_loc("component_types")
        original = pane.proxy.mapFromSource(pane.model.index(position, column))
        self.show_page("detail")
        pane.table.setCurrentIndex(original)
        pane.table.selectRow(original.row())
        pane.table.scrollTo(original)

    def _update_original_button(self, pane):
        record = pane.selected_record()
        pane.original_button.setEnabled(
            self.loaded is not None
            and self.task is None
            and record is not None
            and pd.notna(record.get("source_row"))
        )

    def _open_original_row(self, pane):
        record = pane.selected_record()
        if self.loaded is None or record is None:
            return
        source_rows = self.loaded.frame["__source_row"]
        matches = source_rows.index[source_rows.eq(record.get("source_row"))]
        if matches.empty:
            return
        raw = self.panes["raw"]
        raw.search.clear()
        position = source_rows.index.get_loc(matches[0])
        original = raw.proxy.mapFromSource(raw.model.index(position, 0))
        self.show_page("raw")
        raw.table.setCurrentIndex(original)
        raw.table.selectRow(original.row())
        raw.table.scrollTo(original)

    def save_report(self):
        if self.loaded is None:
            return
        default = output_root() / f"Equipment_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsm"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Excel + PDF \uc800\uc7a5",
            str(default),
            "검색형 Excel (*.xlsm);;일반 Excel (*.xlsx)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        paths = report_paths(path, source_path=self.loaded.path)
        outputs = (paths.excel, paths.pdf)
        existing = [p for p in outputs if p is not None and p.exists()]
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
            # One latest persisted snapshot feeds every output.
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
            "Excel + PDF 생성 완료 (원본 검토표시는 Excel 별첨) | " + str(paths.excel.parent)
        )
        outputs = ["Excel: " + str(paths.excel), "PDF: " + str(paths.pdf)]
        self.notice(f"{len(outputs)}개의 결과파일을 저장했습니다.\n\n" + "\n\n".join(outputs))

    def edit_review_colors(self):
        try:
            dialog = ReviewColorSettingsDialog(self.store, self)
        except Exception as exc:
            self.show_error(exc)
            return
        dialog.exec()
        if dialog.changed:
            self.config = self.store.load()
            self.status_label.setText(
                "검토필요 색상 설정 저장 완료 · 다음 파일 생성부터 적용됩니다."
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
                try:
                    self._refresh_organization_filters()
                except Exception as exc:
                    self.show_error(exc)
                    return
                self._organization_filter_changed()
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
            moves = dict(
                zip(event_ids(self.loaded, self.loaded.mapping), event_ids(self.loaded, mapping))
            )
            moved = self.store.rekey_overrides(moves)
            self.store.save_mapping(self.loaded.headers, mapping)
        except Exception as exc:
            self.show_error(exc)
            return
        self.loaded.mapping = mapping
        self._pending_classifications = {
            moves.get(key, key): value for key, value in self._pending_classifications.items()
        }
        self._current_event_ids = set(event_ids(self.loaded, mapping))
        self._refresh_organization_filters()
        self._organization_filter_changed()
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
            "detail_equipment": 135,
            "part_group": 140,
            "middle": 145,
            "minor": 150,
            "repair_actions": 190,
            "classification_missing_fields": 175,
            "raw_equipment_name": 128,
            "raw_mid": 110,
            "raw_small": 110,
            "raw_description": 300,
            "component_types": 205,
            "combination_decision": 108,
        }
        for index, key in enumerate(pane.model.frame.columns):
            hidden = key in ("event_id", "record_id", "__source_row", "classification_schema") or (
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
        edit_action = menu.addAction("최종 분류 한 건 선택")
        cancel_pending = menu.addAction("임시 분류 선택 취소")
        cancel_pending.setEnabled(record["event_id"] in self._pending_classifications)
        clear_class = menu.addAction("분류 보정 해제")
        class_patch = {
            key: None for key in (*CATEGORY_FIELDS, "classification_components") if key in existing
        }
        clear_class.setEnabled(bool(class_patch))
        menu.addSeparator()
        clear_all = menu.addAction("이 기록의 수동 보정 모두 해제")
        all_patch = {key: None for key in FIELDS if key in existing}
        clear_all.setEnabled(bool(all_patch))
        selected = menu.exec(pane.table.viewport().mapToGlobal(point))
        if selected is cancel_pending:
            self._pending_classifications.pop(record["event_id"], None)
            self._queue_pending_row(record["event_id"])
            return
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

    @staticmethod
    def _classification_only(patch):
        return bool(patch) and set(patch) <= {
            "major",
            "detail_equipment",
            "middle",
            "minor",
            "classification_components",
        }

    def _refresh_classification_categories(self):
        """Check external rule changes only when the optional comparison dialog opens."""
        path = self.store.config_dir / "classification_config.xlsx"
        info = path.stat()
        catalog_path = self.store.config_dir / "classification_catalog.json"
        catalog_info = catalog_path.stat()
        stamp = (
            info.st_mtime_ns,
            info.st_size,
            info.st_ino,
            catalog_info.st_mtime_ns,
            catalog_info.st_size,
            catalog_info.st_ino,
        )
        if stamp != self._classification_catalog_stamp:
            self._classification_categories = ClassificationPathIndex(
                fault_catalog_categories(
                    read_rules(path),
                    self.store.read("classification_catalog.json").get("equipment_types"),
                )
            )
            self._classification_catalog_stamp = stamp

    def _grid_override(self, event_id):
        current = dict(self._confirmed_overrides.get(event_id, {}))
        patch = self._pending_classifications.get(event_id)
        return (
            self.store._patch_override({event_id: current}, event_id, patch) if patch else current
        )

    def _update_pending_rows(self, events):
        for event_id in events:
            patch = self._pending_classifications.get(event_id)
            values = None
            if patch:
                values = {field: patch.get(field) or "" for field in CATEGORY_FIELDS}
                category = " / ".join(values.values())
                values.update(
                    classification_mode="staged",
                    status="확정 대기",
                    component_types=category if any(values.values()) else "분류 보정 해제 대기",
                    combination_decision="표준화 전 임시 선택",
                )
            for key in ("review", "detail"):
                self.panes[key].model.set_classification_preview(event_id, values)

    def _queue_pending_row(self, event_id):
        self._pending_grid_events.add(event_id)
        if not self._pending_grid_update_queued:
            self._pending_grid_update_queued = True
            QTimer.singleShot(0, self._refresh_pending_grid_views)

    def _refresh_pending_grid_views(self):
        self._pending_grid_update_queued = False
        events, self._pending_grid_events = self._pending_grid_events, set()
        if self.result is None or self.task is not None:
            return
        self._update_pending_rows(events)
        count = len(self._current_event_ids.intersection(self._pending_classifications))
        self.status_label.setText(
            f"확정 대기 {count:,}건 · [표준화 + 분석 실행]을 눌러 일괄 적용하세요."
            if count
            else "임시 분류 선택을 취소했습니다. 기존 확정값을 유지합니다."
        )
        self._update_pending_count()

    def _save_grid_edit(self, record, patch):
        if self.task is not None or self._grid_refresh_pending:
            return False
        try:
            if self.result is None or self._analysis_stale:
                raise UserError("분석을 먼저 실행한 뒤 수정하세요.")
            event_id = str(record.get("event_id") or "")
            if not event_id or event_id not in self._selected_event_ids:
                raise UserError("현재 분석 결과에 없는 기록입니다. 분석을 다시 실행하세요.")
            if not patch or set(patch) - set(FIELDS):
                raise UserError("수정할 수 없는 항목입니다.")
            values = {key: str(value or "").strip() for key, value in patch.items()}
            error = validate(
                values, confirm_components=bool(values.get("classification_components"))
            )
            if error:
                raise UserError(error)
            if self._classification_only(patch):
                current = dict(self._confirmed_overrides.get(event_id, {}))
                merged = self.store._patch_override({event_id: current}, event_id, patch)
                fields = (
                    "major",
                    "detail_equipment",
                    "middle",
                    "minor",
                    "classification_components",
                    "classification_schema",
                )
                if all(merged.get(key) == current.get(key) for key in fields):
                    self._pending_classifications.pop(event_id, None)
                else:
                    self._pending_classifications[event_id] = dict(patch)
                return True
            self.store.update_override(event_id, patch)
        except Exception as exc:
            self.show_error(exc)
            return False
        self.last_reports = None
        return True

    def _grid_edit_saved(self, record, patch):
        if self._classification_only(patch):
            self._queue_pending_row(record["event_id"])
            return
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

    def open_source_review(self):
        source_review = getattr(self.last_reports, "source_review", None)
        if source_review is not None:
            self.open_local_path(source_review)

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

    def _select_table_chart(self, key):
        index = self.chart_choice.findData(key)
        if index != -1:
            self.chart_choice.setCurrentIndex(index)

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
