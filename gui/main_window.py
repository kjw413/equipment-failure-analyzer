from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import copy
import logging
import pandas as pd
from PySide6.QtCore import Qt, QDate, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QComboBox, QSpinBox, QCheckBox,
    QDateEdit, QTabWidget, QProgressBar, QTextBrowser, QGroupBox, QDialog)
from core.config import ConfigStore, output_root
from core.defaults_merge import describe
from core.excel_loader import load_excel, validate_path
from core.preprocessing import event_ids
from core.models import AnalysisOptions, UserError
from core.service import run_analysis
from core.equipment_breakdown import type_breakdown
from core.i18n import K
from report.export_bundle import export_bundle, report_paths
from gui.report_settings import ReportSettingsDialog
from gui.widgets import DropArea, TablePane, Task
from gui.dialogs import EquipmentNamesDialog, ColumnMappingDialog, RuleEditor, CorrectionDialog
from version import VERSION

STYLE = '''
QMainWindow, QDialog { background: #F3F4F6; color: #25313B; }
QLabel { color: #25313B; }
QLabel#muted { color: #697681; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#dropTitle { font-size: 15px; font-weight: 600; }
QFrame#dropArea { background: #FFFFFF; border: 2px dashed #AAB3BC; border-radius: 10px; }
QPushButton { background: #FFFFFF; border: 1px solid #C5CCD3; border-radius: 5px; padding: 7px 13px; min-height: 20px; }
QPushButton:hover { background: #E8EDF1; }
QPushButton:disabled { color: #A7AFB7; background: #F2F3F4; }
QPushButton#primary { background: #354451; color: white; border: 1px solid #354451; font-weight: 600; }
QPushButton#primary:disabled { background: #ADB6BE; border-color: #ADB6BE; }
QLineEdit, QComboBox, QSpinBox, QDateEdit { background: white; border: 1px solid #C9D0D6; padding: 5px; border-radius: 4px; min-height: 19px; }
QLineEdit:read-only { background: #F1F3F5; color: #626F7B; }
QTableView, QTableWidget { background: white; alternate-background-color: #F5F7F8; gridline-color: #E6E9ED; border: 1px solid #D4DAE0; selection-background-color: #D9E4ED; selection-color: #172A3A; }
QHeaderView::section { background: #E8ECF0; color: #34414E; font-weight: 600; padding: 7px; border: 0; border-right: 1px solid #D6DCE1; border-bottom: 1px solid #D6DCE1; }
QTabWidget::pane { border: 1px solid #D2D9DF; background: white; }
QTabBar::tab { background: #E5E9ED; padding: 9px 13px; border: 1px solid #D2D9DF; }
QTabBar::tab:selected { background: white; border-bottom-color: white; font-weight: 600; }
QGroupBox { border: 1px solid #D4DBE1; border-radius: 6px; margin-top: 13px; padding-top: 12px; background: white; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QProgressBar { border: 1px solid #CFD7DE; border-radius: 4px; text-align: center; background: white; max-height: 20px; }
QProgressBar::chunk { background: #758D9E; }
QTextBrowser { background: white; border: none; }
'''


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store=store;self.loaded=None;self.result=None;self.task=None;self.last_reports=None
        self.config=store.load()
        self.setWindowTitle(f'{K["app"]}  v{VERSION}')
        self.setMinimumSize(1050,690);self.resize(1430,940)
        self.setStyleSheet(STYLE)
        self.actions=[];self.panes={};self._chart_canvas=None
        central=QWidget();self.setCentralWidget(central)
        layout=QVBoxLayout(central);layout.setContentsMargins(18,12,18,12);layout.setSpacing(8)
        header=QHBoxLayout()
        title=QLabel(K['app']);title.setObjectName('title')
        subtitle=QLabel(K['offline']+f'  |  v{VERSION}');subtitle.setObjectName('muted')
        header.addWidget(title);header.addStretch();header.addWidget(subtitle);layout.addLayout(header)
        self.drop=DropArea();self.drop.browse_requested.connect(self.browse)
        self.drop.file_dropped.connect(self.load_path);self.drop.invalid_drop.connect(self.notice)
        layout.addWidget(self.drop)
        self.file_label=QLabel(K['ready']);self.file_label.setWordWrap(True);self.file_label.setObjectName('muted')
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.file_label)
        source=QHBoxLayout()
        source.addWidget(QLabel(K['choose_sheet']))
        self.sheets=QComboBox();self.sheets.setMinimumWidth(220);source.addWidget(self.sheets)
        source.addWidget(QLabel(K['header']))
        self.header_row=QSpinBox();self.header_row.setRange(1,250000);self.header_row.setValue(1);source.addWidget(self.header_row)
        self.reload_button=self.button(K['reload'],self.reload,source)
        self.columns_button=self.button(K['mapping'],self.edit_columns,source)
        self.reset_button=self.button(K['reset'],self.reset,source)
        source.addStretch()
        self.names_button=self.button(K['name_editor'],self.edit_names,source)
        self.rules_button=self.button(K['rules'],self.edit_rules,source)
        self.folder_button=self.button(K['config'],self.open_config,source)
        layout.addLayout(source)
        filters=QGridLayout()
        filters.addWidget(QLabel(K['scope']),0,0)
        self.scope=QComboBox();self.scope.addItem(K['fault_only'],'fault');self.scope.addItem(K['all_stops'],'all');filters.addWidget(self.scope,0,1)
        filters.addWidget(QLabel(K['basis']),0,2)
        self.basis=QComboBox()
        for value in ('mapped','target','registered','family'):self.basis.addItem(K[value],value)
        self.basis.setMinimumWidth(265);filters.addWidget(self.basis,0,3)
        filters.addWidget(QLabel(K['units']),0,4)
        self.units=QComboBox()
        for label,value in ((K['minutes_unit'],'minutes'),(K['hours_unit'],'hours'),(K['seconds_unit'],'seconds'),(K['excel_days'],'excel_days')):
            self.units.addItem(label,value)
        filters.addWidget(self.units,0,5)
        self.limit_dates=QCheckBox(K['date_filter']);filters.addWidget(self.limit_dates,1,0)
        self.date_from=QDateEdit(QDate.currentDate());self.date_to=QDateEdit(QDate.currentDate())
        for edit in (self.date_from,self.date_to):edit.setDisplayFormat('yyyy-MM-dd');edit.setCalendarPopup(True)
        filters.addWidget(self.date_from,1,1);filters.addWidget(QLabel('~'),1,2);filters.addWidget(self.date_to,1,3)
        self.dedup=QCheckBox(K['dedup']);filters.addWidget(self.dedup,1,4,1,2)
        layout.addLayout(filters)
        run=QHBoxLayout()
        self.analyze_button=self.button(K['analyze'],self.analyze,run,'primary')
        self.report_button=self.button('Excel + PDF \uc0dd\uc131',self.save_report,run,'primary')
        self.open_button=self.button('Excel \uc5f4\uae30',self.open_excel,run)
        self.pdf_button=self.button('PDF \uc5f4\uae30',self.open_pdf,run)
        self.output_button=self.button('\uacb0\uacfc \ud3f4\ub354',self.open_output,run)
        self.report_settings_button=self.button('\ubcf4\uace0\uc11c \uc124\uc815',self.edit_report_settings,run)
        self.correct_button=self.button(K['correct'],self.correct,run)
        run.addStretch();run.addWidget(QLabel('TOP'))
        self.top=QSpinBox();self.top.setRange(1,30);self.top.setValue(int(self.config['settings'].get('top_n',10)));run.addWidget(self.top)
        layout.addLayout(run)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.summary=self.make_summary();self.tabs.addTab(self.summary,K['summary'])
        for key,title_key in [('raw','preview'),('equipment','equipment_tab'),('line','line_tab'),
                              ('type','type_tab'),('cross','cross_tab'),('detail','detail_tab'),('review','review_tab')]:
            pane=TablePane(sort_policy='source' if key=='raw' else 'auto');self.panes[key]=pane;self.tabs.addTab(pane,K[title_key])
        pane=TablePane(sort_policy='grouped');self.panes['equipment_types']=pane
        self.tabs.addTab(pane,'\uc124\ube44\ubcc4 \uc720\ud615\uc21c\uc704')
        self.chart_page=QWidget();self.chart_layout=QVBoxLayout(self.chart_page)
        chart_controls=QHBoxLayout();self.chart_choice=QComboBox()
        self.chart_choice.addItem('\uc124\ube44\ubcc4 \uace0\uc7a5\uc720\ud615(\uc6d0\ud615)', 'equipment_types')
        for label,key in ((K['equipment_tab'],'equipment'),(K['type_tab'],'type'),(K['line_tab'],'line'),(K['monthly'],'trend_month'),(K['week'],'trend_week'),(K['day'],'trend_day'),(K['year'],'trend_year')):
            self.chart_choice.addItem(label,key)
        self.chart_metric=QComboBox();self.chart_metric.addItem(K['total'],'total_minutes');self.chart_metric.addItem(K['count'],'count')
        self.chart_metric.setCurrentIndex(1)
        self.chart_equipment=QComboBox();self.chart_equipment.setMinimumWidth(210)
        chart_controls.addWidget(self.chart_choice);chart_controls.addWidget(self.chart_equipment)
        chart_controls.addWidget(self.chart_metric);chart_controls.addStretch()
        self.chart_layout.addLayout(chart_controls)
        self.chart_empty=QLabel(K['empty']);self.chart_empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.chart_layout.addWidget(self.chart_empty,1)
        self.tabs.addTab(self.chart_page,K['chart_tab'])
        self.chart_choice.currentIndexChanged.connect(self.draw_chart);self.chart_metric.currentIndexChanged.connect(self.draw_chart)
        self.chart_equipment.currentIndexChanged.connect(self.draw_chart)
        status=QHBoxLayout();self.status_label=QLabel(K['ready']);self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0)
        self.progress.setMaximumWidth(300);status.addWidget(self.status_label,1);status.addWidget(self.progress);layout.addLayout(status)
        self.option_widgets=[self.scope,self.basis,self.units,self.limit_dates,self.date_from,self.date_to,self.dedup,self.top,self.sheets,self.header_row]
        for combo in (self.scope,self.basis,self.units):combo.currentIndexChanged.connect(self.mark_stale)
        for check in (self.limit_dates,self.dedup):check.toggled.connect(self.mark_stale)
        self.date_from.dateChanged.connect(self.mark_stale);self.date_to.dateChanged.connect(self.mark_stale);self.top.valueChanged.connect(self.mark_stale)
        self.update_controls()
        merged=describe(getattr(store,'merge_summary',{}))
        if merged:self.status_label.setText(merged+' | 이전 설정 백업: '+str(store.config_dir/'backup'))

    def button(self,text,slot,layout,style=None):
        button=QPushButton(text);button.clicked.connect(slot)
        if style:button.setObjectName(style)
        layout.addWidget(button);self.actions.append(button);return button

    def make_summary(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(15,15,15,15)
        cards=QHBoxLayout();self.card_labels={}
        for key,label in [('selected_rows',K['count']),('total_minutes',K['total']),('mean_minutes',K['mean']),('review_rows',K['review_tab'])]:
            group=QGroupBox(label);group_layout=QVBoxLayout(group);value=QLabel('-');value.setStyleSheet('font-size: 30px; font-weight: 700; padding: 12px; color: #355767;')
            group_layout.addWidget(value);cards.addWidget(group);self.card_labels[key]=value
        layout.addLayout(cards)
        self.notes=QTextBrowser();self.notes.setPlainText(K['ready']+'\n\n'+K['name_help']+'\n\nIF18115  ->  VITAL#2')
        layout.addWidget(self.notes,1);return page

    def notice(self,message):
        QMessageBox.information(self,K['notice'],str(message))

    def show_error(self,message):
        self.status_label.setText(K['error']);QMessageBox.warning(self,K['error'],str(message))

    def update_controls(self):
        busy=self.task is not None
        for widget in self.actions+self.option_widgets+[self.drop]:widget.setEnabled(not busy)
        for widget in (self.reload_button,self.columns_button,self.reset_button,self.sheets,self.header_row,self.analyze_button,self.report_button):
            widget.setEnabled(not busy and self.loaded is not None)
        self.correct_button.setEnabled(not busy and self.result is not None)
        for widget in (self.open_button,self.pdf_button,self.output_button):
            widget.setEnabled(not busy and self.last_reports is not None)
        self.chart_choice.setEnabled(not busy);self.chart_metric.setEnabled(not busy);self.chart_equipment.setEnabled(not busy)
        self.date_from.setEnabled(not busy and self.limit_dates.isChecked());self.date_to.setEnabled(not busy and self.limit_dates.isChecked())

    def run_task(self,function,on_success):
        if self.task is not None:return
        task=Task(function,self);self.task=task
        task.progress.connect(self.on_progress);task.succeeded.connect(on_success);task.failed.connect(self.show_error)
        task.finished.connect(self.task_finished)
        self.progress.setValue(0);self.update_controls();task.start()

    def task_finished(self):
        task=self.task;self.task=None;self.update_controls()
        if task is not None:task.deleteLater()

    def on_progress(self,value,message):
        self.progress.setValue(value);self.status_label.setText(message)

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,K['browse'],'','Excel (*.xlsx *.xlsm)')
        if path:self.load_path(path)

    def load_path(self,path,sheet=None,header_row=None):
        if self.task is not None:return
        try:
            path=validate_path(path);config=self.store.load()
        except Exception as exc:self.show_error(exc);return
        self.clear_results();self.loaded=None;self.file_label.setText(str(path))
        lookup=self.store.saved_mapping
        self.run_task(lambda progress:load_excel(path,config['column_mapping'],sheet,header_row,progress,lookup),self.loaded_ready)

    def loaded_ready(self,loaded):
        self.loaded=loaded
        self.sheets.clear();self.sheets.addItems(loaded.sheet_names);self.sheets.setCurrentText(loaded.sheet)
        self.header_row.setValue(loaded.header_row)
        self.file_label.setText(f'{loaded.path}\n{loaded.sheet}  |  {len(loaded.frame):,} rows / {len(loaded.headers)} columns  |  header {loaded.header_row}')
        self.panes['raw'].set_frame(loaded.frame.drop(columns=['__source_row'],errors='ignore'))
        self.notes.setPlainText(K['name_help'])
        self.tabs.setCurrentWidget(self.panes['raw'])
        self.status_label.setText('\ud30c\uc77c \ub4f1\ub85d \uc644\ub8cc. \uc124\ube44\uba85 \ubcc0\ud658 \uc124\uc815 \ud6c4 \ubd84\uc11d\uc744 \uc2e4\ud589\ud558\uc138\uc694.')

    def reload(self):
        if self.loaded:self.load_path(self.loaded.path,self.sheets.currentText(),self.header_row.value())

    def clear_results(self):
        self.result=None;self.last_reports=None
        for pane in self.panes.values():pane.set_frame(pd.DataFrame())
        for label in self.card_labels.values():label.setText('-')
        self.clear_chart()

    def reset(self):
        self.clear_results();self.loaded=None;self.file_label.setText(K['ready']);self.notes.setPlainText(K['ready'])
        self.sheets.clear();self.status_label.setText(K['ready']);self.progress.setValue(0);self.update_controls()

    def options(self):
        begin=self.date_from.date().toString('yyyy-MM-dd') if self.limit_dates.isChecked() else None
        end=self.date_to.date().toString('yyyy-MM-dd') if self.limit_dates.isChecked() else None
        if begin and end and begin>end:raise UserError('\uc2dc\uc791\uc77c\uc740 \uc885\ub8cc\uc77c\ubcf4\ub2e4 \ub2a6\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.')
        return AnalysisOptions(scope=self.scope.currentData(),equipment_basis=self.basis.currentData(),date_from=begin,date_to=end,
            duration_unit=self.units.currentData(),deduplicate=self.dedup.isChecked(),top_n=self.top.value())

    def analysis_inputs(self):
        if self.loaded is None:raise UserError(K['ready'])
        if self.sheets.currentText() != self.loaded.sheet or self.header_row.value() != self.loaded.header_row:
            raise UserError('\uc2dc\ud2b8/\uc81c\ubaa9 \ud589\uc744 \ubcc0\uacbd\ud55c \ud6c4\uc5d0\ub294 \uc2dc\ud2b8 \uc77d\uae30\ub97c \ub20c\ub7ec\uc8fc\uc138\uc694.')
        return replace(self.loaded,mapping=self.loaded.mapping.copy()),self.store.load(),self.options()

    def analyze(self):
        try:loaded,config,options=self.analysis_inputs()
        except Exception as exc:self.show_error(exc);return
        self.run_task(lambda progress:run_analysis(loaded,config,options,progress),self.analysis_ready)

    def analysis_ready(self,result):
        self.result=result
        for key,label in self.card_labels.items():
            value=result.metrics[key]
            label.setText('-' if value is None else f'{value:,.1f}' if key=='mean_minutes' else f'{value:,.0f}')
        for key in ('equipment','line','type'):self.panes[key].set_frame(result.tables[key])
        frames=[]
        for equipment in result.tables['equipment']['equipment']:
            table=type_breakdown(result.selected,equipment)
            table.insert(0,'equipment',equipment);frames.append(table)
        self.panes['equipment_types'].set_frame(pd.concat(frames,ignore_index=True) if frames else pd.DataFrame())
        previous=self.chart_equipment.currentText()
        self.chart_equipment.blockSignals(True);self.chart_equipment.clear()
        self.chart_equipment.addItems([str(v) for v in result.tables['equipment']['equipment']])
        if previous in result.tables['equipment']['equipment'].tolist():self.chart_equipment.setCurrentText(previous)
        self.chart_equipment.blockSignals(False)
        has_product=result.metrics['product_count'] > 0
        self.panes['cross'].set_frame(result.tables['triple' if has_product else 'equipment_type'])
        for key,frame in (('detail',result.selected),('review',result.tables['review'])):
            self.panes[key].set_frame(frame if has_product else frame.drop(columns=['product'],errors='ignore'))
        info=[f'{K["period"]}: {result.metrics["period"]}',f'{K["basis"]}: {K[result.options.equipment_basis]}',
              f'{K["raw_rows"]}: {result.metrics["source_rows"]:,}  |  {K["excluded_rows"]}: {result.metrics["excluded_rows"]:,}',
              f'{K["name_mapped"]}: {result.metrics["mapped_name_rows"]:,} / {result.metrics["selected_rows"]:,}',
              f'{K["review_tab"]}: {result.metrics["review_rows"]:,}  |  {K["auto_resolved_rows"]}: {result.metrics["auto_resolved_rows"]:,}  |  {K["target_info"]}: {result.metrics["missing_target_rows"]:,}',
              '',*result.notes]
        self.notes.setPlainText('\n\n'.join(info));self.draw_chart();self.tabs.setCurrentWidget(self.summary)
        self.status_label.setText(K['done']);self.update_controls()

    def save_report(self):
        if self.loaded is None:return
        default=output_root()/f'Equipment_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsx'
        path,_=QFileDialog.getSaveFileName(self,'Excel + PDF \uc800\uc7a5',str(default),'Excel (*.xlsx)',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:return
        paths=report_paths(path)
        existing=[p for p in (paths.excel,paths.pdf) if p.exists()]
        if existing:
            message='\ub2e4\uc74c \uae30\uc874 \uacb0\uacfc\ub97c \uad50\uccb4\ud560\uae4c\uc694?\n\n'+'\n'.join(str(p) for p in existing)
            if QMessageBox.question(self,'\ub36e\uc5b4\uc4f0\uae30 \ud655\uc778',message,
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        try:loaded,config,options=self.analysis_inputs()
        except Exception as exc:self.show_error(exc);return
        self.last_reports=None
        def task(progress):
            # One latest persisted snapshot feeds BOTH exports. No stale PDF names.
            result=run_analysis(loaded,config,options,lambda n,t:progress(int(n*.32),t))
            saved=export_bundle(result,paths.excel,lambda n,t:progress(32+int(n*.68),t),overwrite=bool(existing))
            return result,saved
        self.run_task(task,self.report_ready)

    def report_ready(self,payload):
        result,paths=payload;self.analysis_ready(result);self.last_reports=paths
        self.status_label.setText('Excel + PDF \uc0dd\uc131 \uc644\ub8cc | '+str(paths.excel.parent))
        self.notice('\ub450 \uac1c\uc758 \uacb0\uacfc\ud30c\uc77c\uc744 \uc800\uc7a5\ud588\uc2b5\ub2c8\ub2e4.\n\nExcel: '+str(paths.excel)+'\n\nPDF: '+str(paths.pdf))

    def edit_report_settings(self):
        try:dialog=ReportSettingsDialog(self.store,self)
        except Exception as exc:self.show_error(exc);return
        dialog.exec()

    def edit_names(self):
        try:dialog=EquipmentNamesDialog(self.store,self.loaded,self)
        except Exception as exc:self.show_error(exc);return
        dialog.exec()
        if dialog.changed:
            if self.loaded is not None:
                self.status_label.setText('\ucd5c\uc2e0 \uc124\ube44\uba85\uc73c\ub85c \ubd84\uc11d \uacb0\uacfc\ub97c \uac31\uc2e0\ud569\ub2c8\ub2e4.')
                self.analyze()
            else:self.status_label.setText(K['autosave'])

    def edit_columns(self):
        if self.loaded is None:return
        dialog=ColumnMappingDialog(self.loaded,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        mapping=dialog.mapping()
        if mapping==self.loaded.mapping:return
        try:
            # Record IDs depend on the mapped columns: carry saved corrections over to the new IDs.
            moved=self.store.rekey_overrides(dict(zip(event_ids(self.loaded,self.loaded.mapping),event_ids(self.loaded,mapping))))
            self.store.save_mapping(self.loaded.headers,mapping)
        except Exception as exc:
            self.show_error(exc);return
        self.loaded.mapping=mapping;self.mark_stale()
        message='컬럼 매핑을 저장했습니다. 같은 제목 행을 가진 파일에는 다음부터 자동 적용됩니다.'
        if moved:message+=f'\n기존 수동 보정 {moved:,}건을 새 매핑의 기록 ID로 옮겼습니다.'
        self.notice(message)

    def edit_rules(self):
        try:dialog=RuleEditor(self.store,self)
        except Exception as exc:self.show_error(exc);return
        dialog.exec()
        if dialog.changed:
            self.mark_stale()
            if self.loaded is not None:self.analyze()

    def correct(self):
        if self.result is None:return
        pane=self.tabs.currentWidget()
        record=pane.selected_record() if pane in (self.panes['detail'],self.panes['review']) else None
        if not record or not record.get('event_id'):
            self.notice('\uace0\uc7a5 \uc0c1\uc138 \ub610\ub294 \uac80\ud1a0\ud544\uc694 \ud0ed\uc5d0\uc11c \uc218\uc815\ud560 \ud589\uc744 \uc120\ud0dd\ud558\uc138\uc694.');return
        try:existing=self.store.override(record['event_id'])
        except Exception as exc:self.show_error(exc);return
        dialog=CorrectionDialog(record,existing,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:
            if dialog.cleared:self.store.clear_override(record['event_id'])
            else:self.store.update_override(record['event_id'],dialog.patch)
        except Exception as exc:self.show_error(exc);return
        self.analyze()

    def mark_stale(self,*_):
        if self.result is not None:self.status_label.setText(K['stale'])
        self.update_controls()

    def open_config(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.config_dir)))

    def open_excel(self):
        if self.last_reports:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_reports.excel)))

    def open_pdf(self):
        if self.last_reports:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_reports.pdf)))

    def open_output(self):
        if self.last_reports:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_reports.excel.parent)))

    def clear_chart(self):
        if self._chart_canvas is not None:
            self.chart_layout.removeWidget(self._chart_canvas)
            self._chart_canvas.figure.clear();self._chart_canvas.deleteLater();self._chart_canvas=None
        if hasattr(self,'chart_empty'):self.chart_empty.show()

    def draw_chart(self,*_):
        if not hasattr(self,'chart_layout'):return
        self.clear_chart()
        self.chart_equipment.setVisible(self.chart_choice.currentData()=='equipment_types')
        if self.result is None:return
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from report.charts import figure_for, donut_figure
            key=self.chart_choice.currentData()
            if key=='equipment_types':
                equipment=self.chart_equipment.currentText()
                table=type_breakdown(self.result.selected,equipment)
                figure=donut_figure(table,equipment,self.result.config_snapshot['settings'].get('donut_top_n',5),self.chart_metric.currentData())
            else:
                table=self.result.tables[key]
                field='period' if key.startswith('trend_') else key
                figure=figure_for(table,field,self.chart_metric.currentData(),'trend' if field=='period' else 'bar',self.result.options.top_n)
            self._chart_canvas=FigureCanvasQTAgg(figure);self.chart_layout.addWidget(self._chart_canvas,1)
            self.chart_empty.hide();self._chart_canvas.draw_idle()
        except Exception:
            logging.getLogger(__name__).exception('Chart preview failed')
            self.chart_empty.setText('\uadf8\ub798\ud504\ub97c \ud45c\uc2dc\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. logs\ub97c \ud655\uc778\ud558\uc138\uc694.')

    def closeEvent(self,event):
        if self.task is not None:
            self.notice(K['close_busy']);event.ignore();return
        event.accept()
