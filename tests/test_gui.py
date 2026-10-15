"""Native Qt tests. Skipped when PySide6 is not installed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core.config import ConfigStore
from gui.dialogs import EquipmentNamesDialog
from gui.main_window import MainWindow


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_mapping_autosaves_and_flushes_last_text(app,tmp_path):
    store=ConfigStore(tmp_path/'profile')
    dialog=EquipmentNamesDialog(store)
    dialog.show()
    edit=dialog.table.cellWidget(0,2)
    edit.selectAll();QTest.keyClicks(edit,'VITAL#2 UPDATED')
    QTest.qWait(700)
    assert store.read('equipment_names.json')['mappings']['IF18115']=='VITAL#2 UPDATED'
    edit.selectAll();QTest.keyClicks(edit,'VITAL#2 LAST')
    dialog.accept()  # Close before the 450ms debounce: latest text must survive.
    assert ConfigStore(store.root).load()['equipment_names']['mappings']['IF18115']=='VITAL#2 LAST'
    reopened=EquipmentNamesDialog(ConfigStore(store.root))
    assert reopened.table.cellWidget(0,2).text()=='VITAL#2 LAST'
    reopened.accept()


def test_window_initialization_and_mapping_button(app,tmp_path):
    window=MainWindow(ConfigStore(tmp_path/'profile'))
    window.show();QTest.qWait(30)
    assert window.drop.acceptDrops()
    assert window.names_button.isEnabled()
    assert not window.report_button.isEnabled()
    window.close()


def visible_column(pane,key):
    from PySide6.QtCore import Qt
    column=pane.model.frame.columns.get_loc(key)
    return [pane.proxy.index(r,column).data(Qt.ItemDataRole.UserRole) for r in range(pane.proxy.rowCount())]


def test_all_analysis_tables_start_numeric_descending(app):
    import pandas as pd
    from gui.widgets import TablePane
    from PySide6.QtCore import Qt
    pane=TablePane()
    frame=pd.DataFrame({'line':['A','Z','B'],'count':[8,36,14],'total_minutes':[276.,1293.,491.]})
    pane.set_frame(frame)
    assert visible_column(pane,'total_minutes')==[1293.,491.,276.]
    assert pane.table.horizontalHeader().sortIndicatorSection()==2
    assert pane.table.horizontalHeader().sortIndicatorOrder()==Qt.SortOrder.DescendingOrder
    pane.table.sortByColumn(2,Qt.SortOrder.AscendingOrder)
    assert visible_column(pane,'total_minutes')==[276.,491.,1293.]
    pane.reset_sort()
    assert visible_column(pane,'total_minutes')==[1293.,491.,276.]
    pane.search.setText('Z')
    assert visible_column(pane,'count')==[36]
    pane.search.clear()
    pane.set_frame(frame)
    assert visible_column(pane,'count')==[36,14,8]
    pane.close()


def test_blanks_last_and_numeric_header_default(app):
    import pandas as pd
    from gui.widgets import TablePane
    from PySide6.QtCore import Qt
    pane=TablePane()
    pane.set_frame(pd.DataFrame({'line':list('ABCDE'),'total_minutes':[None,10.,100.,10.,0.],
                                 'count':[1000,2,1,8,20]}))
    assert visible_column(pane,'line')==list('CDBEA')
    pane.table.sortByColumn(1,Qt.SortOrder.AscendingOrder)
    assert visible_column(pane,'line')==list('EDBCA')
    assert pane.model.headerData(1,Qt.Orientation.Horizontal,Qt.ItemDataRole.InitialSortOrderRole)==Qt.SortOrder.DescendingOrder
    pane.close()


def test_grouped_ranking_and_raw_preview_preserve_source_order(app):
    import pandas as pd
    from gui.widgets import TablePane
    frame=pd.DataFrame({'equipment':['B','B','A','A'],'count':[10,2,8,3]})
    for policy in ('grouped','source'):
        pane=TablePane(sort_policy=policy)
        pane.set_frame(frame)
        assert visible_column(pane,'count')==[10,2,8,3]
        pane.reset_sort()
        assert visible_column(pane,'equipment')==['B','B','A','A']
        pane.close()


def test_correction_dialog_saves_only_changed_fields(app):
    import pandas as pd
    from core.i18n import K
    from gui.dialogs import CorrectionDialog
    record={'major':'기계','middle':'벨트·풀리','minor':'벨트·풀리 끊어짐·마모','status':K['review'],
            'target':K['target_missing'],'product':K['missing'],'date':pd.Timestamp('2026-01-01'),'minutes':None}
    dialog=CorrectionDialog(record,{})
    assert not dialog.clear_button.isEnabled()
    dialog.edits['minutes'].setText('25')
    dialog.validate_and_accept()
    assert dialog.patch=={'minutes':'25'}  # a tentative classification is not confirmed silently
    confirm=CorrectionDialog(record,{'minutes':'25','saved_at':'2026-10-14T10:00:00'})
    assert confirm.clear_button.isEnabled() and confirm.edits['minutes'].text()=='25'
    confirm.confirm.setChecked(True)
    confirm.validate_and_accept()
    assert confirm.patch=={'major':'기계','middle':'벨트·풀리','minor':'벨트·풀리 끊어짐·마모'}


def test_rule_editor_shows_role_column(app,tmp_path):
    from core.classifier import RULE_COLUMNS
    from gui.dialogs import RuleEditor
    editor=RuleEditor(ConfigStore(tmp_path/'profile'))
    headers=[editor.table.horizontalHeaderItem(i).text() for i in range(editor.table.columnCount())]
    assert headers==RULE_COLUMNS and 'role' in headers
    roles={editor.table.item(r,RULE_COLUMNS.index('role')).text() for r in range(editor.table.rowCount())}
    assert {'component','fallback','override'}<=roles
    editor.reject()
