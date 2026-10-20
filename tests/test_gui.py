"""Native Qt tests. Skipped when PySide6 is not installed."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

pytest.importorskip("PySide6")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.config import ConfigStore
from gui.dialogs import EquipmentNamesDialog
from gui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_mapping_autosaves_and_flushes_last_text(app, tmp_path):
    store = ConfigStore(tmp_path / "profile")
    dialog = EquipmentNamesDialog(store)
    dialog.show()
    edit = dialog.table.cellWidget(0, 2)
    edit.selectAll()
    QTest.keyClicks(edit, "VITAL#2 UPDATED")
    QTest.qWait(700)
    assert store.read("equipment_names.json")["mappings"]["IF18115"] == "VITAL#2 UPDATED"
    edit.selectAll()
    QTest.keyClicks(edit, "VITAL#2 LAST")
    dialog.accept()  # Close before the 450ms debounce: latest text must survive.
    assert (
        ConfigStore(store.root).load()["equipment_names"]["mappings"]["IF18115"] == "VITAL#2 LAST"
    )
    reopened = EquipmentNamesDialog(ConfigStore(store.root))
    assert reopened.table.cellWidget(0, 2).text() == "VITAL#2 LAST"
    reopened.accept()


def test_window_initialization_and_mapping_button(app, tmp_path):
    window = MainWindow(ConfigStore(tmp_path / "profile"))
    window.show()
    QTest.qWait(30)
    assert window.drop.acceptDrops()
    assert window.names_button.isEnabled()
    assert not window.report_button.isEnabled()
    window.close()


def visible_column(pane, key):
    from PySide6.QtCore import Qt

    column = pane.model.frame.columns.get_loc(key)
    return [
        pane.proxy.index(r, column).data(Qt.ItemDataRole.UserRole)
        for r in range(pane.proxy.rowCount())
    ]


def test_all_analysis_tables_start_numeric_descending(app):
    import pandas as pd
    from PySide6.QtCore import Qt

    from gui.widgets import TablePane

    pane = TablePane()
    frame = pd.DataFrame(
        {"line": ["A", "Z", "B"], "count": [8, 36, 14], "total_minutes": [276.0, 1293.0, 491.0]}
    )
    pane.set_frame(frame)
    assert visible_column(pane, "total_minutes") == [1293.0, 491.0, 276.0]
    assert pane.table.horizontalHeader().sortIndicatorSection() == 2
    assert pane.table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    pane.table.sortByColumn(2, Qt.SortOrder.AscendingOrder)
    assert visible_column(pane, "total_minutes") == [276.0, 491.0, 1293.0]
    pane.reset_sort()
    assert visible_column(pane, "total_minutes") == [1293.0, 491.0, 276.0]
    pane.search.setText("Z")
    assert visible_column(pane, "count") == [36]
    pane.search.clear()
    pane.set_frame(frame)
    assert visible_column(pane, "count") == [36, 14, 8]
    pane.close()


def test_blanks_last_and_numeric_header_default(app):
    import pandas as pd
    from PySide6.QtCore import Qt

    from gui.widgets import TablePane

    pane = TablePane()
    pane.set_frame(
        pd.DataFrame(
            {
                "line": list("ABCDE"),
                "total_minutes": [None, 10.0, 100.0, 10.0, 0.0],
                "count": [1000, 2, 1, 8, 20],
            }
        )
    )
    assert visible_column(pane, "line") == list("CDBEA")
    pane.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert visible_column(pane, "line") == list("EDBCA")
    assert (
        pane.model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.InitialSortOrderRole)
        == Qt.SortOrder.DescendingOrder
    )
    pane.close()


def test_grouped_ranking_and_raw_preview_preserve_source_order(app):
    import pandas as pd

    from gui.widgets import TablePane

    frame = pd.DataFrame({"equipment": ["B", "B", "A", "A"], "count": [10, 2, 8, 3]})
    for policy in ("grouped", "source"):
        pane = TablePane(sort_policy=policy)
        pane.set_frame(frame)
        assert visible_column(pane, "count") == [10, 2, 8, 3]
        pane.reset_sort()
        assert visible_column(pane, "equipment") == ["B", "B", "A", "A"]
        pane.close()


def test_correction_dialog_saves_only_changed_fields(app):
    import pandas as pd

    from core.i18n import K
    from gui.dialogs import CorrectionDialog

    record = {
        "major": "기계",
        "middle": "벨트·풀리",
        "minor": "벨트·풀리 끊어짐·마모",
        "status": K["review"],
        "target": K["target_missing"],
        "product": K["missing"],
        "date": pd.Timestamp("2026-01-01"),
        "minutes": None,
    }
    dialog = CorrectionDialog(record, {})
    assert not dialog.clear_button.isEnabled()
    dialog.edits["minutes"].setText("25")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "25"}  # a tentative classification is not confirmed silently
    confirm = CorrectionDialog(record, {"minutes": "25", "saved_at": "2026-10-14T10:00:00"})
    assert confirm.clear_button.isEnabled() and confirm.edits["minutes"].text() == "25"
    confirm.confirm.setChecked(True)
    confirm.validate_and_accept()
    assert confirm.patch == {
        "major": "기계",
        "middle": "벨트·풀리",
        "minor": "벨트·풀리 끊어짐·마모",
    }


def test_grid_classification_picker_uses_current_profile_rules_when_opened(analyzed_window):
    from core.rules import write_rules

    window = analyzed_window
    custom = {
        "id": "CUSTOM_REVIEW",
        "enabled": True,
        "priority": 1,
        "major": "사용자 대분류",
        "middle": "사용자 부품",
        "minor": "사용자 고장",
        "context": "custom",
        "symptom": ".",
        "exclude": "",
        "role": "component",
    }
    # Change the profile after analysis: opening a grid picker must use the current list.
    write_rules(window.store.config_dir / "classification_config.xlsx", [custom])
    pane = window.panes["review"]
    window.show_page("review")
    pane.table.selectRow(0)
    column = pane.model.frame.columns.get_loc("major")
    pane.open_classification_editor(pane.proxy.index(0, column))
    editor = pane.classification_editor
    picker = editor.single_picker
    for field in ("major", "middle", "minor"):
        combo = picker.combos[field]
        index = combo.findData(custom[field])
        assert index >= 0
        combo.setCurrentIndex(index)
    assert picker.value() == {key: custom[key] for key in ("major", "middle", "minor")}
    editor.cancel_button.click()
    assert not window.store.override(pane.selected_record()["event_id"])


def test_rule_editor_shows_role_column(app, tmp_path):
    from core.classifier import RULE_COLUMNS
    from core.rules import ROLES
    from gui.dialogs import RuleEditor

    store = ConfigStore(tmp_path / "profile")
    editor = RuleEditor(store)
    headers = [
        editor.table.horizontalHeaderItem(i).text() for i in range(editor.table.columnCount())
    ]
    assert headers == RULE_COLUMNS and "role" in headers
    roles = {
        editor.table.item(r, RULE_COLUMNS.index("role")).text()
        for r in range(editor.table.rowCount())
    }
    assert roles == {rule["role"] for rule in store.load()["rules"]}
    assert roles <= set(ROLES)
    editor.reject()


def test_save_dialog_starts_in_output_folder(app, tmp_path, monkeypatch, input_file):
    from PySide6.QtWidgets import QFileDialog

    from core.config import app_root

    monkeypatch.delenv("EFA_OUTPUT_DIR", raising=False)
    window = MainWindow(ConfigStore(tmp_path / "profile"))
    window.load_path(input_file)
    while window.task is not None:
        QTest.qWait(50)
    seen = {}

    def fake_dialog(parent, title, directory, *args, **kwargs):
        seen["directory"] = directory
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_dialog)
    window.save_report()
    from pathlib import Path

    assert Path(seen["directory"]).parent == app_root() / "output"
    assert Path(seen["directory"]).name.startswith("Equipment_Analysis_")
    window.close()


@pytest.fixture
def analyzed_window(app, tmp_path, input_file):
    from core.excel_loader import load_excel
    from core.service import run_analysis

    store = ConfigStore(tmp_path / "profile")
    window = MainWindow(store)
    config = store.load()
    loaded = load_excel(input_file, config["column_mapping"])
    window.loaded_ready(loaded)
    window.analysis_ready(run_analysis(loaded, config, window.options()))
    yield window
    window.close()


@pytest.mark.parametrize("source_option", ["sheet", "header"])
def test_source_option_changes_mark_results_stale(analyzed_window, source_option):
    from core.i18n import K
    from core.models import UserError

    window = analyzed_window
    assert window.status_label.text() == K["done"]
    if source_option == "sheet":
        window.sheets.addItem("Another sheet")
        window.sheets.setCurrentText("Another sheet")
    else:
        window.header_row.setValue(window.loaded.header_row + 1)

    assert window.status_label.text() == K["stale"]
    with pytest.raises(UserError):
        window.analysis_inputs()


def test_reanalysis_invalidates_previous_report_links(analyzed_window, tmp_path, monkeypatch):
    from report.export_bundle import report_paths

    window = analyzed_window
    monkeypatch.setattr(window, "notice", lambda message: None)
    paths = report_paths(tmp_path / "previous.xlsx")
    window.report_ready((window.result, paths))
    window.update_controls()
    report_buttons = (window.open_button, window.pdf_button, window.output_button)
    assert all(button.isEnabled() for button in report_buttons)

    window.top.setValue(2)
    window.analyze()
    task = window.task
    assert task is not None and task.wait(20_000)
    QTest.qWait(30)

    assert window.task is None
    assert window.result.options.top_n == 2
    assert window.last_reports is None
    assert all(not button.isEnabled() for button in report_buttons)


def test_reset_clears_chart_failure_message(analyzed_window, monkeypatch):
    import report.charts
    from core.i18n import K

    def fail_chart(*args, **kwargs):
        raise RuntimeError("Simulated chart failure")

    window = analyzed_window
    monkeypatch.setattr(report.charts, "donut_figure", fail_chart)
    window.draw_chart()
    assert window._chart_canvas is None
    assert window.chart_empty.text() != K["empty"]

    window.reset()
    assert window.chart_empty.text() == K["empty"]
    assert not window.chart_empty.isHidden()


def test_rule_classification_has_no_threshold_settings_button(app, tmp_path):
    from PySide6.QtWidgets import QPushButton

    window = MainWindow(ConfigStore(tmp_path / "profile"))
    assert not hasattr(window, "classifier_settings_button")
    assert not hasattr(window, "edit_classifier_settings")
    assert all("분류 점수" not in button.text() for button in window.findChildren(QPushButton))
    window.close()


def test_decision_fields_are_visible_in_details_and_prioritized_in_review(analyzed_window):
    from dataclasses import replace

    from PySide6.QtCore import Qt

    from core.i18n import K

    window = analyzed_window
    frame = window.result.selected.assign(
        classification_reason="서로 다른 고장 유형의 규칙이 일치하여 검토필요",
        candidate_evidence="BELT: 벨트 / 마모 | SENSOR: 센서 / 불량",
    )
    result = replace(
        window.result, selected=frame, tables={**window.result.tables, "review": frame}
    )
    window.analysis_ready(result)
    for key in ("detail", "review"):
        pane = window.panes[key]
        assert pane.table.isColumnHidden(pane.model.frame.columns.get_loc("classification_reason"))
        pane.extra_columns.setChecked(True)
        for field in ("classification_reason", "candidate_evidence"):
            column = pane.model.frame.columns.get_loc(field)
            assert not pane.table.isColumnHidden(column)
            assert pane.model.headerData(column, Qt.Orientation.Horizontal) == K[field]
            assert pane.model.index(0, column).data() == frame.iloc[0][field]
        assert not hasattr(pane, "score_note")
    assert window.panes["review"].model.frame.columns[:3].tolist() == ["major", "middle", "minor"]


def test_correction_dialog_explains_rule_evidence_without_auto_confirming(app):
    from core.i18n import K
    from gui.dialogs import CorrectionDialog

    record = {
        "major": "기계",
        "middle": "벨트·풀리",
        "minor": "벨트 마모",
        "classification_reason": "서로 다른 유형의 규칙이 일치하여 검토필요",
        "candidate_evidence": "BELT: 벨트 / 마모 | SENSOR: 센서 / 불량",
        "evidence": "BELT | 벨트, 마모",
        "candidates": "BELT: 벨트 마모 | SENSOR: 센서 불량",
    }
    dialog = CorrectionDialog(record)
    text = dialog.diagnostic.toPlainText()
    assert text.startswith(K["classification_reason"] + ": " + record["classification_reason"])
    assert record["candidate_evidence"] in text
    assert record["evidence"] in text and record["candidates"] in text
    assert not hasattr(dialog, "score_note") and not hasattr(dialog, "score_summary")
    assert not dialog.confirm.isChecked()
    dialog.edits["minutes"].setText("25")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "25"}

    confirmed = CorrectionDialog(record)
    confirmed.confirm.setChecked(True)
    confirmed.validate_and_accept()
    assert confirmed.patch == {key: record[key] for key in ("major", "middle", "minor")}
