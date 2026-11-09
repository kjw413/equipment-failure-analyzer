"""The production correction menu selects field, concrete part and symptom."""
# ruff: noqa: E402

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from conftest import analyze_file
from PySide6.QtWidgets import QApplication, QDialog

from core.failure_modes import SYMPTOM_NAMES
from core.fault_components import parse_components
from core.i18n import K
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


def test_fresh_profile_picker_selects_concrete_parts_and_observed_symptoms(app, store):
    dialog = CorrectionDialog({}, rules=store.load()["rules"])
    picker = dialog.classification_picker
    assert len(choices(picker.combos["major"])) == 6
    assert all(not combo.isEditable() for combo in picker.combos.values())
    assert not dialog.confirm.isChecked()
    for major, part in (
        ("공압·진공", "실린더"),
        ("기계", "베어링"),
        ("전기·제어", "광전센서"),
        ("유체·배관", "도징펌프"),
    ):
        for symptom in SYMPTOM_NAMES:
            select(picker, (major, part, symptom))
            assert picker.value() == dict(major=major, middle=part, minor=symptom)
        assert choices(picker.combos["minor"]) == set(SYMPTOM_NAMES)
    assert dialog.confirm.isChecked()
    dialog.reject()


@pytest.mark.parametrize(
    "major,required",
    [
        ("유체·배관", {"도징펌프", "로터리펌프", "부스터펌프", "펌프"}),
        ("전기·제어", {"근접센서", "광전센서", "엔코더", "센서"}),
        ("기계", {"타이밍벨트", "V벨트", "풀리", "벨트"}),
        ("공압·진공", {"로드리스실린더", "회전실린더", "실린더"}),
    ],
)
def test_part_subtypes_are_middle_choices_and_symptoms_are_minor_choices(
    app, store, major, required
):
    dialog = CorrectionDialog({}, rules=store.load()["rules"])
    picker = dialog.classification_picker
    select(picker, (major, sorted(required)[0], "손상"))
    assert required <= choices(picker.combos["middle"])
    assert not required.intersection(choices(picker.combos["minor"]))
    dialog.reject()


def test_legacy_manual_path_is_not_added_to_new_global_choices(app, store):
    legacy = {"major": "유체·배관", "middle": "펌프", "minor": "펌프 이상"}
    store.override_path.write_text(json.dumps({"saved-event": legacy}), encoding="utf-8")
    saved_bytes = store.override_path.read_bytes()
    dialog = CorrectionDialog(legacy, store.override("saved-event"), rules=store.load()["rules"])
    assert dialog.classification_picker.value() == legacy
    dialog.edits["minutes"].setText("15")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "15"}
    assert store.override_path.read_bytes() == saved_bytes
    blank = CorrectionDialog({}, rules=store.load()["rules"])
    select(blank.classification_picker, ("유체·배관", "펌프", "손상"))
    assert "펌프 이상" not in choices(blank.classification_picker.combos["minor"])
    blank.reject()
    dialog.reject()


def test_multiple_confirmation_saves_part_symptom_rows_and_preserves_event_totals(
    app, store, catalog_input
):
    before = analyze_file(store, catalog_input)
    record = before.selected.loc[before.selected.source_row.eq(4)].iloc[0].to_dict()
    expected = {
        ("유체·배관", "도징펌프", "파손"),
        ("전기·제어", "근접센서", "고장·이상"),
    }
    dialog = CorrectionDialog(record, rules=store.load()["rules"])
    observed = {
        tuple(member[key] for key in ("major", "middle", "minor"))
        for member in dialog.component_picker.values()
    }
    assert observed == expected
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
