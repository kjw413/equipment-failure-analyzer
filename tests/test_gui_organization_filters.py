"""Factory/team selectors constrain analysis without losing unavailable selections."""
# ruff: noqa: E402

import os
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialog

from core.config import ConfigStore
from core.excel_loader import load_excel
from core.i18n import K
from core.service import run_analysis
from gui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def organization_store(tmp_path):
    store = ConfigStore(tmp_path / "profile")
    store.save_equipment_names(
        {},
        source="line",
        organization={
            "line": {
                "L1": {"team": "Red"},
                "L2": {"team": "Blue"},
                "L3": {"team": "Red"},
                "L4": {"team": "Planned"},
            }
        },
    )
    return store


@pytest.fixture
def organization_loaded(input_file, organization_store):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    sheet["J3"], sheet["K3"] = "라인코드", "라인명"
    for row, code, raw_name in (
        (4, "L1", "[North] First line"),
        (5, "L2", "[North] Second line"),
        (6, "L3", "[South] Third line"),
        (7, "L4", "[Archive] Planned line"),
        (8, "L5", "Line without factory"),
    ):
        sheet.cell(row, 10, code)
        sheet.cell(row, 11, raw_name)
    workbook.save(input_file)
    workbook.close()
    return load_excel(input_file, organization_store.load()["column_mapping"])


@pytest.fixture
def window_factory(app, organization_store, organization_loaded):
    windows = []

    def create(load=True):
        window = MainWindow(organization_store)
        window.draw_chart = lambda *_args: None
        windows.append(window)
        if load:
            window.loaded_ready(organization_loaded)
            window.update_controls()
        return window

    yield create
    for window in windows:
        window.task = None
        window.close()
        window.deleteLater()
    app.processEvents()


def combo_values(combo):
    return {combo.itemData(index) for index in range(combo.count())}


def select_data(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def analyze_current(window):
    loaded, config, options = window.analysis_inputs()
    result = run_analysis(loaded, config, options)
    window.analysis_ready(result)
    return result


def save_organization(store, organization):
    current = store.read("equipment_names.json")
    store.save_equipment_names(current["line_mappings"], source="line", organization=organization)


def test_loaded_choices_use_all_resolved_rows_and_factory_cascades_without_classification(
    window_factory, monkeypatch
):
    def unexpected_classification(*_args, **_kwargs):
        pytest.fail("Organization choices must not instantiate the classifier")

    monkeypatch.setattr("core.preprocessing.FaultClassifier", unexpected_classification)
    window = window_factory()
    assert window.options().scope == "fault"
    assert combo_values(window.factory_filter) == {None, "North", "South", "Archive", K["missing"]}
    assert combo_values(window.team_filter) == {None, "Red", "Blue", "Planned", K["missing"]}
    assert window.factory_filter.currentData() is None
    assert window.team_filter.currentData() is None

    select_data(window.factory_filter, "North")
    assert combo_values(window.team_filter) == {None, "Red", "Blue"}
    select_data(window.team_filter, "Blue")
    select_data(window.factory_filter, "South")
    assert combo_values(window.team_filter) == {None, "Red"}
    assert window.team_filter.currentData() is None
    select_data(window.team_filter, "Red")
    select_data(window.factory_filter, "North")
    assert window.team_filter.currentData() == "Red"
    select_data(window.factory_filter, K["missing"])
    assert combo_values(window.team_filter) == {None, K["missing"]}
    assert window.team_filter.currentData() is None
    select_data(window.team_filter, K["missing"])
    assert window.options().factory == window.options().team == K["missing"]


@pytest.mark.parametrize(
    ("factory", "team", "source_row", "minutes"),
    [("North", "Blue", 5, 20.0), ("South", "Red", 6, 65.0), (K["missing"], K["missing"], 8, None)],
)
def test_selected_filters_control_real_counts_and_appear_in_summary_and_notes(
    window_factory, factory, team, source_row, minutes
):
    window = window_factory()
    select_data(window.factory_filter, factory)
    select_data(window.team_filter, team)
    result = analyze_current(window)
    assert result.options.factory == factory
    assert result.options.team == team
    assert result.metrics["selected_rows"] == 1
    assert result.metrics["total_minutes"] == minutes
    assert result.selected["source_row"].tolist() == [source_row]
    assert window.card_labels["selected_rows"].text() == "1"
    assert len(window.panes["detail"].model.frame) == 1
    for text in (window.condition_summary.text(), window.notes.toPlainText()):
        assert factory in text
        assert team in text
    # Analysis results must not narrow available factories to the selected subset.
    assert combo_values(window.factory_filter) == {None, "North", "South", "Archive", K["missing"]}


@pytest.mark.parametrize(
    ("selector", "value"), [("factory_filter", "North"), ("team_filter", "Blue")]
)
def test_filter_changes_mark_results_stale_and_invalidate_report_links(
    window_factory, tmp_path, monkeypatch, selector, value
):
    window = window_factory()
    analyze_current(window)
    window.last_reports = SimpleNamespace(
        excel=tmp_path / "old.xlsx",
        pdf=tmp_path / "old.pdf",
        source_review=tmp_path / "old_review.xlsx",
    )
    window.update_controls()
    buttons = (
        window.open_button,
        window.pdf_button,
        window.output_button,
    )
    assert all(button.isEnabled() for button in buttons)
    opened = []
    monkeypatch.setattr(window, "open_local_path", opened.append)
    select_data(getattr(window, selector), value)
    assert window._analysis_stale
    assert window.last_reports is None
    assert not any(button.isEnabled() for button in buttons)
    for open_report in (
        window.open_excel,
        window.open_pdf,
        window.open_source_review,
        window.open_output,
    ):
        open_report()
    assert opened == []


def test_filter_controls_disable_when_busy_and_reset_on_new_file(
    window_factory, organization_loaded
):
    window = window_factory(load=False)
    assert not window.factory_filter.isEnabled()
    assert not window.team_filter.isEnabled()
    window.loaded_ready(organization_loaded)
    window.update_controls()
    assert window.factory_filter.isEnabled()
    assert window.team_filter.isEnabled()
    select_data(window.factory_filter, "North")
    select_data(window.team_filter, "Blue")
    window.task = object()
    window.update_controls()
    assert not window.factory_filter.isEnabled()
    assert not window.team_filter.isEnabled()
    window.task = None
    window.update_controls()
    assert window.factory_filter.isEnabled()
    assert window.team_filter.isEnabled()

    window.loaded_ready(
        replace(organization_loaded, path=organization_loaded.path.with_name("next.xlsx"))
    )
    assert window.factory_filter.currentData() is None
    assert window.team_filter.currentData() is None


def test_edit_names_refreshes_choices_from_latest_manual_metadata_before_analysis(
    window_factory, organization_store, organization_loaded, monkeypatch
):
    import gui.main_window as window_module

    window = window_factory()
    captured = {}

    class SavedNamesDialog:
        changed = True

        def __init__(self, store, loaded, parent):
            assert store is organization_store
            assert loaded is organization_loaded
            assert parent is window

        def exec(self):
            organization = deepcopy(organization_store.read("equipment_names.json")["organization"])
            organization["line"]["L5"] = {"factory": "New factory", "team": "New team"}
            save_organization(organization_store, organization)

    def capture_analysis():
        captured["factories"] = combo_values(window.factory_filter)
        captured["teams"] = combo_values(window.team_filter)
        captured["inputs"] = window.analysis_inputs()

    monkeypatch.setattr(window_module, "EquipmentNamesDialog", SavedNamesDialog)
    monkeypatch.setattr(window, "analyze", capture_analysis)
    window.edit_names()
    assert "New factory" in captured["factories"]
    assert "New team" in captured["teams"]
    assert K["missing"] not in captured["factories"]
    assert K["missing"] not in captured["teams"]
    assert captured["inputs"][1]["equipment_names"]["organization"]["line"]["L5"] == {
        "factory": "New factory",
        "team": "New team",
    }
    assert captured["inputs"][2].factory is None
    assert captured["inputs"][2].team is None


def test_column_remap_refreshes_effective_equipment_choices_and_preserves_selection(
    window_factory, organization_store, monkeypatch
):
    import gui.main_window as window_module

    window = window_factory()
    select_data(window.factory_filter, "North")
    select_data(window.team_filter, "Blue")
    organization_store.save_equipment_names(
        {},
        source="line",
        organization={
            "equipment": {"IF18115": {"factory": "Equipment factory", "team": "Equipment team"}}
        },
    )
    mapping = dict(window.loaded.mapping, line_id=None, line_name=None)

    class RemappedColumnsDialog:
        def __init__(self, *_args):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def mapping(self):
            return mapping

    monkeypatch.setattr(window_module, "ColumnMappingDialog", RemappedColumnsDialog)
    monkeypatch.setattr(window, "notice", lambda *_args: None)
    window.last_reports = object()
    window.edit_columns()
    assert window.loaded.mapping == mapping
    assert "Equipment factory" in combo_values(window.factory_filter)
    assert window.factory_filter.currentData() == "North"
    assert window.team_filter.currentData() == "Blue"
    assert "현재 자료 없음" in window.factory_filter.currentText()
    assert window.last_reports is None
    select_data(window.factory_filter, "Equipment factory")
    assert combo_values(window.team_filter) == {None, "Equipment team"}
    assert window.team_filter.currentData() is None


def test_metadata_and_result_refresh_preserve_unavailable_selections_without_broadening(
    window_factory, organization_store
):
    window = window_factory()
    select_data(window.factory_filter, "North")
    select_data(window.team_filter, "Blue")
    analyze_current(window)
    organization = deepcopy(organization_store.read("equipment_names.json")["organization"])
    organization["line"]["L1"] = {"factory": "West", "team": "Red"}
    organization["line"]["L2"] = {"factory": "West", "team": "Yellow"}
    save_organization(organization_store, organization)
    window._refresh_organization_filters()
    assert window.factory_filter.currentData() == "North"
    assert window.team_filter.currentData() == "Blue"
    assert "현재 자료 없음" in window.factory_filter.currentText()
    assert "현재 자료 없음" in window.team_filter.currentText()
    result = analyze_current(window)
    assert result.options.factory == "North"
    assert result.options.team == "Blue"
    assert result.metrics["selected_rows"] == 0
    assert window.factory_filter.currentData() == "North"
    assert window.team_filter.currentData() == "Blue"
    assert "현재 자료 없음" in window.factory_filter.currentText()
    assert "현재 자료 없음" in window.team_filter.currentText()
    # A user-selected new factory may clear an unavailable team through the normal cascade.
    select_data(window.factory_filter, "West")
    assert combo_values(window.team_filter) == {None, "Red", "Yellow"}
    assert window.team_filter.currentData() is None
