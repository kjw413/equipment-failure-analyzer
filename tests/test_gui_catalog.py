"""The production correction menu uses the approved 240-path catalog."""
# ruff: noqa: E402

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from conftest import analyze_file
from PySide6.QtWidgets import QApplication, QDialog

from core.classification_catalog import catalog_categories
from core.fault_components import parse_components
from core.i18n import K
from core.rules import read_rules
from gui.dialogs import CorrectionDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def choices(combo):
    return {combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)}


def select(picker, path):
    for field, value in zip(("major", "middle", "minor"), path):
        combo = picker.combos[field]
        index = combo.findData(value)
        assert index >= 0, (field, value, choices(combo))
        combo.setCurrentIndex(index)


def test_fresh_profile_picker_traverses_all_approved_paths(app, store, approved_catalog_paths):
    rules = store.load()["rules"]
    dialog = CorrectionDialog({}, rules=rules)
    picker = dialog.classification_picker
    assert set(picker.categories) == approved_catalog_paths
    assert len(picker.categories) == 240
    assert len(choices(picker.combos["major"])) == 6
    assert all(not combo.isEditable() for combo in picker.combos.values())
    assert not dialog.confirm.isChecked()
    visited = set()
    for path in sorted(approved_catalog_paths):
        select(picker, path)
        visited.add(tuple(picker.value()[key] for key in ("major", "middle", "minor")))
        assert choices(picker.combos["middle"]) == {
            candidate[1] for candidate in approved_catalog_paths if candidate[0] == path[0]
        }
        assert choices(picker.combos["minor"]) == {
            candidate[2] for candidate in approved_catalog_paths if candidate[:2] == path[:2]
        }
    assert visited == approved_catalog_paths
    assert len({path[:2] for path in visited}) == 59
    assert dialog.confirm.isChecked()  # Explicitly selecting a new path is a correction.
    dialog.reject()


@pytest.mark.parametrize(
    "major,middle,required",
    [
        ("유체·배관", "펌프", {"도징펌프", "로터리펌프", "부스터펌프", "펌프(종류 미상)"}),
        ("전기·제어", "센서·검출", {"근접센서", "광전센서", "엔코더", "센서(종류 미상)"}),
        ("기계", "벨트·풀리", {"타이밍벨트", "V벨트", "풀리", "벨트(종류 미상)"}),
        ("공압·진공", "실린더", {"로드리스실린더", "회전실린더", "실린더(종류 미상)"}),
    ],
)
def test_current_component_families_show_concrete_types(
    app, store, approved_catalog_paths, major, middle, required
):
    dialog = CorrectionDialog({}, rules=store.load()["rules"])
    picker = dialog.classification_picker
    select(picker, (major, middle, sorted(required)[0]))
    actual = choices(picker.combos["minor"])
    assert required <= actual
    assert actual == {p[2] for p in approved_catalog_paths if p[:2] == (major, middle)}
    if middle == "펌프":
        assert actual == required
    dialog.reject()


def test_old_manual_path_stays_local_and_never_pollutes_shared_lists(
    app, store, approved_catalog_paths
):
    rules = store.load()["rules"]
    legacy = {"major": "유체·배관", "middle": "펌프", "minor": "펌프 이상"}
    store.update_override("saved-event", legacy)
    saved_bytes = store.override_path.read_bytes()
    old_dialog = CorrectionDialog(legacy, store.override("saved-event"), rules=rules)
    assert old_dialog.classification_picker.value() == legacy
    assert not old_dialog.confirm.isChecked()
    old_dialog.edits["minutes"].setText("15")
    old_dialog.validate_and_accept()
    assert old_dialog.patch == {"minutes": "15"}
    assert store.override_path.read_bytes() == saved_bytes

    blank = CorrectionDialog({}, rules=rules)
    old_rules = read_rules(
        Path(__file__).parent / "fixtures" / "v172_config" / "classification_config.xlsx"
    )
    old_paths = set(catalog_categories(old_rules))
    assert set(blank.classification_picker.categories) == approved_catalog_paths
    assert not (old_paths - approved_catalog_paths).intersection(blank.classification_picker.paths)
    select(blank.classification_picker, ("유체·배관", "펌프", "도징펌프"))
    assert "펌프 이상" not in choices(blank.classification_picker.combos["minor"])
    old_dialog.component_picker.add_button.click()
    fresh_member = old_dialog.component_picker.pickers[-1]
    select(fresh_member, ("유체·배관", "펌프", "로터리펌프"))
    assert "펌프 이상" not in choices(fresh_member.combos["minor"])
    blank.reject()
    old_dialog.reject()


def test_actual_catalog_multiple_confirmation_preserves_cross_family_types_and_totals(
    app, store, catalog_input, approved_catalog_paths
):
    before = analyze_file(store, catalog_input)
    record = before.selected.loc[before.selected.source_row.eq(4)].iloc[0].to_dict()
    expected = {
        ("유체·배관", "펌프", "도징펌프"),
        ("전기·제어", "센서·검출", "근접센서"),
    }
    assert record["classification_mode"] == "multiple"
    dialog = CorrectionDialog(record, rules=store.load()["rules"])
    observed = {
        tuple(member[key] for key in ("major", "middle", "minor"))
        for member in dialog.component_picker.values()
    }
    assert observed == expected and observed <= approved_catalog_paths
    assert not dialog.multiple_confirm.isChecked()
    dialog.multiple_confirm.setChecked(True)
    dialog.validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    store.update_override(record["event_id"], dialog.patch)
    after = analyze_file(store, catalog_input)
    row = after.selected.loc[after.selected.event_id.eq(record["event_id"])].iloc[0]
    assert row.status == K["manual_multi"]
    assert {
        tuple(member[key] for key in ("major", "middle", "minor"))
        for member in parse_components(row.component_details)
    } == expected
    assert after.metrics["selected_rows"] == before.metrics["selected_rows"] == 4
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"] == 95
