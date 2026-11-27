"""Review color preferences stay local until saved and cover the extra export."""
# ruff: noqa: E402

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLabel, QMessageBox

from core.config import ConfigStore
from core.review_colors import normalized_review_colors
from gui.main_window import MainWindow
from gui.review_color_settings import ReviewColorSettingsDialog
from report.export_bundle import report_paths


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_review_colors_choose_save_reopen_and_cancel(app, tmp_path, monkeypatch):
    import gui.review_color_settings as color_module

    store = ConfigStore(tmp_path / "profile")
    original = store.load()["settings"]["review_colors"]
    dialog = ReviewColorSettingsDialog(store)
    assert list(dialog.color_buttons) == ["multi_match", "unmatched_rule", "missing_code", "other"]
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert {"복수검토", "규칙 미일치", "비가동코드 미기입", "기타"}.issubset(labels)
    assert any("A열~X열" in label for label in labels)
    assert any("기타에는 날짜·정지시간·고장대상" in label for label in labels)
    monkeypatch.setattr(color_module.QColorDialog, "getColor", lambda *args: QColor("#123ABC"))
    dialog.color_buttons["missing_code"].click()
    assert dialog.color_buttons["missing_code"].text() == "#123ABC"
    assert store.load()["settings"]["review_colors"] == original
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.changed

    reopened = ReviewColorSettingsDialog(ConfigStore(store.root))
    assert reopened.color_buttons["missing_code"].text() == "#123ABC"
    monkeypatch.setattr(color_module.QColorDialog, "getColor", lambda *args: QColor("#ABCDEF"))
    reopened.color_buttons["missing_code"].click()
    reopened.reject()
    assert store.load()["settings"]["review_colors"]["missing_code"] == "#123ABC"
    assert not reopened.changed


def test_default_colors_restore_only_when_saved_and_picker_cancel_keeps_color(
    app, tmp_path, monkeypatch
):
    import gui.review_color_settings as color_module

    store = ConfigStore(tmp_path / "profile")
    store.save_review_colors({"multi_match": "#123ABC"})
    dialog = ReviewColorSettingsDialog(store)
    monkeypatch.setattr(color_module.QColorDialog, "getColor", lambda *args: QColor())
    dialog.color_buttons["multi_match"].click()
    assert dialog.colors["multi_match"] == "#123ABC"
    dialog.restore_defaults()
    assert dialog.colors == normalized_review_colors(None)
    assert store.load()["settings"]["review_colors"]["multi_match"] == "#123ABC"
    dialog.save()
    assert store.load()["settings"]["review_colors"] == normalized_review_colors(None)


def test_failed_color_save_keeps_dialog_open(app, tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "profile")
    before = store.load()["settings"]["review_colors"]
    dialog = ReviewColorSettingsDialog(store)
    dialog.colors["missing_code"] = "#123ABC"

    def fail_save(colors):
        raise PermissionError("Settings file is locked")

    errors = []
    monkeypatch.setattr(store, "save_review_colors", fail_save)
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: errors.append(text))
    dialog.show()
    dialog.save()
    assert dialog.isVisible()
    assert not dialog.changed
    assert errors == ["Settings file is locked"]
    assert store.load()["settings"]["review_colors"] == before
    dialog.reject()


def test_review_settings_entry_and_source_output_open(app, tmp_path, monkeypatch):
    window = MainWindow(ConfigStore(tmp_path / "profile"))
    assert window.review_colors_action in window.settings_button.menu().actions()
    assert window.review_colors_action.text() == "검토필요 색상 설정"
    assert window.review_colors_action.isEnabled()
    assert not hasattr(window, "source_review_button")
    opened, notices = [], []
    monkeypatch.setattr(window, "open_local_path", opened.append)
    monkeypatch.setattr(window, "notice", notices.append)
    monkeypatch.setattr(window, "analysis_ready", lambda result: None)
    paths = report_paths(tmp_path / "analysis.xlsx", source_path=tmp_path / "original.xlsm")
    window.report_ready((object(), paths))
    window.update_controls()
    assert not hasattr(window, "source_review_button")
    window.open_excel()
    assert opened == [paths.excel]
    assert notices == [f"Excel 보고서를 저장했습니다.\n\n{paths.excel}"]
    assert window.last_results_button.menu().actions() == [window.open_button, window.output_button]
    assert paths.source_review is None
    window.task = object()
    window.update_controls()
    assert not window.review_colors_action.isEnabled()
    assert not hasattr(window, "source_review_button")
    window.task = None
    window.close()


def test_workbook_collision_requires_overwrite_confirmation(app, tmp_path, monkeypatch):
    window = MainWindow(ConfigStore(tmp_path / "profile"))
    source = tmp_path / "original.xlsm"
    window.loaded = SimpleNamespace(path=source)
    destination = tmp_path / "analysis.xlsx"
    paths = report_paths(destination, source_path=source)
    paths.excel.write_text("existing workbook", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(destination), "")
    )
    questions = []

    def decline(parent, title, text, *args):
        questions.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    monkeypatch.setattr(
        window, "run_task", lambda *args: pytest.fail("Export started after decline")
    )
    window.save_report()
    assert len(questions) == 1
    assert str(paths.excel) in questions[0]
    assert paths.excel.read_text(encoding="utf-8") == "existing workbook"
    window.close()
