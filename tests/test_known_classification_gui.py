"""The review grid and both editors expose certain axes without confirming them."""

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from core.classification_catalog import equipment_classification_categories
from core.failure_classification import FaultClassifier
from gui.category_index import ClassificationPathIndex
from gui.dialogs import CorrectionDialog
from gui.inline_editor import ClassificationCellEditor, classification_patch
from gui.main_window import MainWindow
from gui.widgets import TablePane
from tools.make_rules import build_rules


def test_review_grid_and_editors_preserve_known_equipment(qt_application_lifetime):
    rules = build_rules()
    row = {
        **FaultClassifier(rules).classify("컨베어 모터 또는 센서 고장 의심"),
        "raw_description": "컨베어 모터 또는 센서 고장 의심",
        "normalized": "컨베어 모터 또는 센서 고장 의심",
        "event_id": "known-event",
        "record_id": "known-row",
    }
    frame = MainWindow.classification_frame(pd.DataFrame([row]), review=True)
    assert frame.loc[0, "detail_equipment"] == "컨베어"
    assert "middle" not in frame
    paths = ClassificationPathIndex(equipment_classification_categories(rules))
    editor = ClassificationCellEditor(row, {}, paths, lambda *args: None)
    correction = CorrectionDialog(row, {}, rules=rules)
    try:
        assert editor.single_picker.value()["detail_equipment"] == "컨베어"
        assert "middle" not in editor.single_picker.value()
        assert editor.single_picker.legacy is None
        assert editor.single_picker.legacy_note.isHidden()
        assert correction.classification_picker.value()["detail_equipment"] == "컨베어"
        initial = editor.single_picker.value()
        assert classification_patch(row, {}, "single", initial, [], repair_actions="교체") == {
            "repair_actions": "교체"
        }
        pane = TablePane()
        try:
            pane.set_frame(frame)
            pane.model.edit_request = lambda *args: None
            column = pane.model.frame.columns.get_loc("detail_equipment")
            assert pane.model.index(0, column).data() == "컨베어"
        finally:
            pane.close()
    finally:
        editor.close()
        correction.close()
