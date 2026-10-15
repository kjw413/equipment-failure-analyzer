from __future__ import annotations
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QComboBox, QCheckBox,
    QMessageBox, QDialogButtonBox, QFormLayout, QTextEdit, QAbstractItemView)
from core.i18n import K, FIELD_LABELS
from core.models import UserError
from core.config import ConfigStore
from core.classifier import read_rules, write_rules, RULE_COLUMNS
from core.corrections import initial_values, validate, correction_patch, shown
from core.equipment_names import equipment_catalog, code_key, validate_names


class EquipmentNamesDialog(QDialog):
    """Editable names persist after a short typing pause, including close/ESC.

    Text fields are real QLineEdits: pending in-cell text is never lost waiting
    for a QTableWidget delegate's commit signal. Invalid edits do not replace
    the last valid on-disk mapping.
    """
    saved = Signal()

    def __init__(self, store: ConfigStore, loaded=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.changed = False
        self.catalog = {item['code']: item['raw_name'] for item in equipment_catalog(loaded)}
        self.setWindowTitle(K['name_editor']); self.resize(1100, 630)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(450)
        self.timer.timeout.connect(self.save_silently)
        layout = QVBoxLayout(self)
        for text in (K['name_help'], K['name_fallback'], K['name_unique']):
            label=QLabel(text); label.setWordWrap(True); layout.addWidget(label)
        self.table=QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([K['equipment_code'], K['raw_equipment_name'], K['report_equipment']])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 190); self.table.setColumnWidth(2, 280)
        self.table.verticalHeader().setDefaultSectionSize(43)
        layout.addWidget(self.table)
        self.status=QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        path=QLabel(str(store.config_dir/'equipment_names.json'))
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setObjectName('muted'); path.setWordWrap(True); layout.addWidget(path)
        buttons=QHBoxLayout()
        add=QPushButton(K['add_code']); add.clicked.connect(self.add_empty)
        delete=QPushButton(K['delete']); delete.clicked.connect(self.delete_rows)
        restore=QPushButton('\ub9c8\uc9c0\ub9c9 \uc800\uc7a5\uac12 \ubd88\ub7ec\uc624\uae30'); restore.clicked.connect(self.reload_saved)
        close=QPushButton(K['close']); close.clicked.connect(self.accept)
        for button in (add,delete,restore,close):
            button.setAutoDefault(False)
        buttons.addWidget(add);buttons.addWidget(delete);buttons.addWidget(restore);buttons.addStretch();buttons.addWidget(close)
        layout.addLayout(buttons)
        self.reload_saved()

    def add_row(self, code: str, raw_name: str, display: str, read_only: bool):
        row=self.table.rowCount(); self.table.insertRow(row)
        key=QLineEdit(code); key.setReadOnly(read_only)
        key.setPlaceholderText('IF18115')
        name=QLineEdit(display); name.setPlaceholderText('\ubcf4\uace0\uc11c\uc5d0 \ud45c\uc2dc\ud560 \uc774\ub984')
        name.setStyleSheet('QLineEdit { color: #2155A0; }')
        self.table.setCellWidget(row,0,key)
        item=QTableWidgetItem(raw_name); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(raw_name); self.table.setItem(row,1,item)
        self.table.setCellWidget(row,2,name)
        key.textEdited.connect(self.schedule_save); name.textEdited.connect(self.schedule_save)

    def reload_saved(self):
        self.timer.stop()
        try:
            self.snapshot=self.store.read('equipment_names.json')
            mapping=validate_names(self.snapshot.get('mappings',{}))
        except Exception as exc:
            QMessageBox.warning(self,K['error'],str(exc));return
        self.table.setRowCount(0)
        for key in sorted(set(self.catalog)|set(mapping)):
            self.add_row(key,self.catalog.get(key,''),mapping.get(key,''),True)
        self.status.setText(K['autosave']+' | '+(self.snapshot.get('updated_at') or '\ucd08\uae30 \uc124\uc815'))
        self.status.setStyleSheet('color: #237245;')

    def add_empty(self):
        self.add_row('','','',False)
        self.table.setCurrentCell(self.table.rowCount()-1,0)
        self.table.cellWidget(self.table.rowCount()-1,0).setFocus()

    def delete_rows(self):
        rows=sorted({i.row() for i in self.table.selectionModel().selectedRows()},reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows=[self.table.currentRow()]
        for row in rows:
            key=code_key(self.table.cellWidget(row,0).text())
            if key in self.catalog:
                self.table.cellWidget(row,2).clear()
            else:
                self.table.removeRow(row)
        if rows:
            self.schedule_save()

    def schedule_save(self, *_):
        self.status.setText(K['saving']);self.status.setStyleSheet('color: #65717D;')
        self.timer.start()

    def collect(self):
        values={}
        for row in range(self.table.rowCount()):
            code=code_key(self.table.cellWidget(row,0).text())
            name=self.table.cellWidget(row,2).text().strip()
            if not code and not name:
                continue
            if not code:
                raise UserError(f'{row+1}: \uc124\ube44 \ucf54\ub4dc\ub97c \uc785\ub825\ud558\uc138\uc694.')
            if code in values:
                raise UserError('\uac19\uc740 \ucf54\ub4dc\uac00 \ub450 \ubc88 \uc785\ub825\ub418\uc5c8\uc2b5\ub2c8\ub2e4: '+code)
            values[code]=name
        return validate_names(values)

    def save_silently(self) -> bool:
        self.timer.stop()
        try:
            values=self.collect()
            before=self.store.read('equipment_names.json').get('mappings',{})
            snapshot=self.store.save_equipment_names(values)
        except Exception as exc:
            self.status.setText(K['save_failed']+'\n'+str(exc))
            self.status.setStyleSheet('color: #A52A2A;')
            return False
        self.snapshot=snapshot
        self.status.setText(K['autosave']+' | '+datetime.now().strftime('%H:%M:%S'))
        self.status.setStyleSheet('color: #237245;')
        if before != values:
            self.changed=True;self.saved.emit()
        return True

    def done(self, result):
        # Always flush the last text on close, including X/ESC during debounce.
        if not self.save_silently():
            QMessageBox.warning(self,K['error'],self.status.text())
            return
        super().done(result)


class ColumnMappingDialog(QDialog):
    def __init__(self, loaded, parent=None):
        super().__init__(parent)
        self.setWindowTitle(K['mapping']);self.resize(720,670)
        layout=QVBoxLayout(self)
        self.table=QTableWidget(len(loaded.mapping),2)
        self.table.setHorizontalHeaderLabels(['\ud504\ub85c\uadf8\ub7a8 \ud56d\ubaa9','Excel \uc5f4'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fields=list(loaded.mapping)
        for row,key in enumerate(self.fields):
            item=QTableWidgetItem(FIELD_LABELS.get(key,key));item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row,0,item)
            combo=QComboBox();combo.addItem(K['unmapped'],None)
            for column in loaded.headers:combo.addItem(column,column)
            index=combo.findData(loaded.mapping[key]);combo.setCurrentIndex(max(0,index))
            self.table.setCellWidget(row,1,combo)
        layout.addWidget(self.table)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def mapping(self):
        return {key:self.table.cellWidget(row,1).currentData() for row,key in enumerate(self.fields)}


class RuleEditor(QDialog):
    def __init__(self, store:ConfigStore, parent=None):
        super().__init__(parent)
        self.path=store.config_dir/'classification_config.xlsx';self.changed=False
        self.setWindowTitle(K['rules']);self.resize(1250,630)
        layout=QVBoxLayout(self)
        note=QLabel(K['rule_help']);note.setWordWrap(True);layout.addWidget(note)
        rules=read_rules(self.path)
        self.table=QTableWidget(len(rules),len(RULE_COLUMNS));self.table.setHorizontalHeaderLabels(RULE_COLUMNS)
        self.table.setAlternatingRowColors(True)
        for row,rule in enumerate(rules):
            for col,key in enumerate(RULE_COLUMNS):
                value=int(rule[key]) if key=='enabled' else rule[key]
                self.table.setItem(row,col,QTableWidgetItem(str(value)))
        for col in range(len(RULE_COLUMNS)):self.table.setColumnWidth(col,230 if 5<=col<=8 else 120)
        layout.addWidget(self.table)
        buttons=QHBoxLayout()
        add=QPushButton(K['add']);add.clicked.connect(lambda:self.table.insertRow(self.table.rowCount()))
        delete=QPushButton(K['delete']);delete.clicked.connect(self.delete)
        save=QPushButton(K['save']);save.clicked.connect(self.save)
        cancel=QPushButton(K['cancel']);cancel.clicked.connect(self.reject)
        buttons.addWidget(add);buttons.addWidget(delete);buttons.addStretch();buttons.addWidget(save);buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def delete(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()},reverse=True):
            self.table.removeRow(row)

    def save(self):
        rows=[]
        for row in range(self.table.rowCount()):
            rows.append({key:self.table.item(row,col).text() if self.table.item(row,col) else '' for col,key in enumerate(RULE_COLUMNS)})
        try:write_rules(self.path,rows)
        except Exception as exc:QMessageBox.warning(self,K['error'],str(exc));return
        self.changed=True;self.accept()


class CorrectionDialog(QDialog):
    """Saves only what the user changed; [수동 보정 해제] removes every saved field of the record."""
    def __init__(self, record:dict, existing:dict | None = None, parent=None):
        super().__init__(parent)
        self.existing={k:v for k,v in (existing or {}).items() if k!='saved_at'}
        self.initial=initial_values(record,self.existing)
        self.patch={};self.cleared=False
        self.setWindowTitle(K['correct']);self.resize(820,740)
        layout=QVBoxLayout(self)
        note=QLabel(K['correction_help']);note.setWordWrap(True);layout.addWidget(note)
        diagnostic=QTextEdit();diagnostic.setReadOnly(True)
        saved=', '.join(f'{K.get(k,k)}={v}' for k,v in self.existing.items()) or '없음'
        diagnostic.setPlainText('검토 사유: '+str(record.get('review_reason',''))+'\n\n수정 방법: '+str(record.get('review_action',''))
                                +'\n\n현재 집계 영향: '+str(record.get('aggregation_effect',''))+'\n\n분류 근거: '+str(record.get('evidence',''))
                                +'\n분류 후보: '+str(record.get('candidates',''))+'\n\n저장된 수동 보정: '+saved)
        diagnostic.setMinimumHeight(165);layout.addWidget(diagnostic)
        source=QTextEdit();source.setReadOnly(True);source.setPlainText(str(record.get('raw_description','')))
        source.setMaximumHeight(120);layout.addWidget(source)
        form=QFormLayout();self.edits={}
        self.confirm=QCheckBox('위 대·중·소분류를 사용자확정으로 저장')
        self.confirm.setToolTip('체크하지 않고 분류를 그대로 두면 분류는 저장하지 않습니다. 시간·일자만 고칠 때는 비워 두세요.')
        for key in ('major','middle','minor'):
            edit=QLineEdit(self.initial[key]);self.edits[key]=edit;form.addRow(K[key],edit)
            edit.textEdited.connect(lambda *_:self.confirm.setChecked(True))
        form.addRow('',self.confirm)
        for key in ('target','product'):
            edit=QLineEdit(self.initial[key]);self.edits[key]=edit;form.addRow(K[key],edit)
        for key,label,value in (('work_date','확정 작업일자 (YYYY-MM-DD)',record.get('date')),
                                ('minutes','확정 정지시간 (분)',record.get('minutes'))):
            # Empty unless already corrected; the source value is only a hint. Clearing removes it.
            edit=QLineEdit(self.initial[key])
            hint=shown(value)
            edit.setPlaceholderText('원본: '+hint[:19] if hint else '')
            self.edits[key]=edit;form.addRow(label,edit)
        layout.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(K['save'])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(K['cancel'])
        self.clear_button=buttons.addButton('수동 보정 해제',QDialogButtonBox.ButtonRole.ResetRole)
        self.clear_button.setEnabled(bool(self.existing));self.clear_button.clicked.connect(self.clear_all)
        buttons.accepted.connect(self.validate_and_accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def values(self):
        return {key:edit.text().strip() for key,edit in self.edits.items()}

    def clear_all(self):
        answer=QMessageBox.question(self,K['notice'],'이 기록에 저장된 수동 보정을 모두 해제하고 원본·규칙 값으로 되돌릴까요?')
        if answer==QMessageBox.StandardButton.Yes:
            self.cleared=True;self.accept()

    def validate_and_accept(self):
        values=self.values()
        error=validate(values)
        if error:
            QMessageBox.warning(self,K['notice'],error);return
        self.patch=correction_patch(self.initial,values,self.existing,self.confirm.isChecked())
        if not self.patch:
            QMessageBox.information(self,K['notice'],'변경된 내용이 없습니다.');return
        self.accept()
