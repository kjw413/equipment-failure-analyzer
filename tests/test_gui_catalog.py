"""The production correction menu selects field, detailed equipment and symptom."""
# ruff: noqa: E402

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from conftest import analyze_file
from PySide6.QtWidgets import QApplication, QDialog

from core.failure_modes import SYMPTOM_NAMES, UNKNOWN_SYMPTOM
from core.i18n import K
from gui.dialogs import CorrectionDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def choices(combo):
    return {combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)}


def select(picker, path):
    for field, value in zip(("major", "detail_equipment", "minor"), path):
        combo = picker.combos[field]
        index = combo.findData(value)
        assert index >= 0, (field, value, choices(combo))
        combo.setCurrentIndex(index)


def test_fresh_profile_picker_selects_detailed_equipment_and_observed_symptoms(app, store):
    dialog = CorrectionDialog({}, rules=store.load()["rules"])
    picker = dialog.classification_picker
    assert len(choices(picker.combos["major"])) == 7
    assert set(picker.combos) == {"major", "detail_equipment", "minor"}
    assert all(not combo.isEditable() for combo in picker.combos.values())
    assert not dialog.confirm.isChecked()
    for major, equipment in (
        ("공압·진공", "진공펌프"),
        ("기계", "컨베어"),
        ("전기·제어", "로봇"),
        ("유체·배관", "펌프"),
    ):
        for symptom in (name for name in SYMPTOM_NAMES if name != UNKNOWN_SYMPTOM):
            select(picker, (major, equipment, symptom))
            assert picker.value() == dict(major=major, detail_equipment=equipment, minor=symptom)
        assert choices(picker.combos["minor"]) == set(SYMPTOM_NAMES) - {UNKNOWN_SYMPTOM}
    assert dialog.confirm.isChecked()
    dialog.reject()


@pytest.mark.parametrize(
    "major,required",
    [
        ("유체·배관", {"메카니칼씰", "피스톤씰", "오일씰", "오링"}),
        ("전기·제어", {"근접센서", "광전센서", "엔코더", "센서(종류 미상)"}),
        ("기계", {"타이밍벨트", "V벨트", "풀리", "벨트(종류 미상)"}),
        ("공압·진공", {"로드리스실린더", "회전실린더", "실린더(종류 미상)"}),
    ],
)
def test_part_subtypes_are_not_equipment_or_symptom_choices(app, store, major, required):
    dialog = CorrectionDialog({}, rules=store.load()["rules"])
    picker = dialog.classification_picker
    select(picker, (major, "상세설비 미상", "손상·파손"))
    assert not required.intersection(choices(picker.combos["detail_equipment"]))
    assert not required.intersection(choices(picker.combos["minor"]))
    dialog.reject()


def test_legacy_manual_path_is_not_added_to_new_global_choices(app, store):
    legacy = {
        "detail_equipment": "상세설비 미상",
        "major": "유체·배관",
        "middle": "펌프",
        "minor": "펌프 이상",
    }
    store.override_path.write_text(json.dumps({"saved-event": legacy}), encoding="utf-8")
    saved_bytes = store.override_path.read_bytes()
    dialog = CorrectionDialog(legacy, store.override("saved-event"), rules=store.load()["rules"])
    assert dialog.classification_picker.value() == {
        key: value for key, value in legacy.items() if key != "middle"
    }
    dialog.edits["minutes"].setText("15")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "15"}
    assert store.override_path.read_bytes() == saved_bytes
    blank = CorrectionDialog({}, rules=store.load()["rules"])
    select(blank.classification_picker, ("유체·배관", "상세설비 미상", "손상·파손"))
    assert "펌프 이상" not in choices(blank.classification_picker.combos["minor"])
    blank.reject()
    dialog.reject()


def test_second_candidate_saves_one_final_type_and_preserves_event_totals(
    app, store, catalog_input
):
    before = analyze_file(store, catalog_input)
    record = before.selected.loc[before.selected.source_row.eq(4)].iloc[0].to_dict()
    dialog = CorrectionDialog(record, rules=store.load()["rules"])
    assert dialog.candidate_list.currentRow() == -1
    assert dialog.candidate_list.rowCount() >= 2
    dialog.candidate_list.selectRow(1)
    expected = dialog.classification_picker.value()
    dialog.validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    store.update_override(record["event_id"], dialog.patch)
    after = analyze_file(store, catalog_input)
    row = after.selected.loc[after.selected.event_id.eq(record["event_id"])].iloc[0]
    assert row.status == K["manual"]
    assert row.classification_mode == "single"
    assert {key: row[key] for key in ("major", "detail_equipment", "minor")} == expected
    assert after.metrics["selected_rows"] == before.metrics["selected_rows"] == 4
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"] == 95


def test_manual_equipment_and_domain_survive_save_and_reanalysis(app, store, catalog_input):
    before = analyze_file(store, catalog_input)
    record = before.selected.loc[before.selected.source_row.eq(4)].iloc[0].to_dict()
    dialog = CorrectionDialog(record, rules=store.load()["rules"])
    picker = dialog.classification_picker
    picker.set_value({"detail_equipment": "펌프", "minor": "온도이상"})
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("기계"))
    expected = picker.validate_path()
    assert expected["detail_equipment"] == "펌프"
    dialog.validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    store.update_override(record["event_id"], dialog.patch)
    after = analyze_file(store, catalog_input)
    row = after.selected.loc[after.selected.event_id.eq(record["event_id"])].iloc[0]
    assert {key: row[key] for key in expected} == expected
    assert row.status == K["manual"]
    assert after.metrics["selected_rows"] == before.metrics["selected_rows"]
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"]
    dialog.close()
