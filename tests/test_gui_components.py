"""Manual multi-type choices must not silently confirm ambiguous alternatives."""
# ruff: noqa: E402

import json
import os
from dataclasses import replace

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QMessageBox

from core.corrections import COMPONENT_FIELD, correction_patch, initial_values
from core.excel_loader import load_excel
from core.fault_components import (
    combination_category,
    component_payload,
    parse_components,
    type_label,
)
from core.i18n import K
from core.models import AnalysisOptions
from core.service import run_analysis
from gui.dialogs import CorrectionDialog
from gui.main_window import MainWindow

MEMBERS = [
    {"major": "기계", "middle": "벨트·풀리", "minor": "타이밍벨트"},
    {"major": "전기·제어", "middle": "센서·검출", "minor": "근접센서"},
]
RULES = [
    {**MEMBERS[0], "enabled": True, "role": "component"},
    {**MEMBERS[1], "enabled": True, "role": "component"},
    {
        "major": "기계",
        "middle": "벨트·풀리",
        "minor": "V벨트",
        "enabled": True,
        "role": "override",
    },
    {
        "major": "기계",
        "middle": "베어링",
        "minor": "베어링(종류 미상)",
        "enabled": True,
        "role": "fallback",
    },
    {
        "major": "비활성 대분류",
        "middle": "비활성 중분류",
        "minor": "비활성 소분류",
        "enabled": False,
        "role": "component",
    },
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def multiple_record(mode="multiple"):
    return {
        **combination_category(MEMBERS),
        **component_payload(MEMBERS, mode=mode),
        "status": K["review"],
        "minutes": 10.0,
    }


def select_category(picker, values):
    """Drive actual noneditable dropdowns in parent-to-child order."""
    for key in ("major", "middle", "minor"):
        combo = picker.combos[key]
        index = combo.findData(values.get(key, ""))
        assert index >= 0, (key, values, [combo.itemData(i) for i in range(combo.count())])
        combo.setCurrentIndex(index)


def combo_values(combo):
    return [combo.itemData(index) for index in range(combo.count()) if combo.itemData(index)]


def choose_components(dialog, members):
    for picker in tuple(dialog.component_picker.pickers):
        picker.remove_button.click()
    for member in members:
        dialog.component_picker.add_button.click()
        select_category(dialog.component_picker.pickers[-1], member)


def test_category_lists_are_noneditable_and_follow_active_parent_choices(app):
    dialog = CorrectionDialog({}, rules=RULES)
    picker = dialog.classification_picker
    assert all(isinstance(combo, QComboBox) for combo in picker.combos.values())
    assert all(
        not combo.isEditable() and combo.lineEdit() is None for combo in picker.combos.values()
    )
    assert combo_values(picker.combos["major"]) == ["기계", "전기·제어"]
    assert not combo_values(picker.combos["middle"])
    assert not combo_values(picker.combos["minor"])

    select_category(picker, {"major": "기계", "middle": "베어링", "minor": "베어링(종류 미상)"})
    assert combo_values(picker.combos["middle"]) == ["베어링", "벨트·풀리"]
    assert combo_values(picker.combos["minor"]) == ["베어링(종류 미상)"]
    picker.combos["middle"].setCurrentIndex(picker.combos["middle"].findData("벨트·풀리"))
    assert not picker.value()["minor"]
    assert combo_values(picker.combos["minor"]) == ["V벨트", "타이밍벨트"]
    picker.combos["minor"].setCurrentIndex(picker.combos["minor"].findData("타이밍벨트"))
    picker.combos["major"].setCurrentIndex(picker.combos["major"].findData("전기·제어"))
    assert picker.value() == {"major": "전기·제어", "middle": "", "minor": ""}
    assert combo_values(picker.combos["middle"]) == ["센서·검출"]
    assert not combo_values(picker.combos["minor"])
    dialog.reject()


def test_unlisted_current_value_is_preserved_without_becoming_a_new_rule(app):
    legacy = {"major": "과거 대분류", "middle": "과거 부품", "minor": "과거 고장"}
    dialog = CorrectionDialog(legacy, rules=RULES)
    assert dialog.classification_picker.value() == legacy
    assert not dialog.confirm.isChecked()
    for key, combo in dialog.classification_picker.combos.items():
        assert combo.currentData() == legacy[key]
    dialog.component_picker.add_button.click()
    blank_member = dialog.component_picker.pickers[-1]
    assert legacy["major"] not in combo_values(blank_member.combos["major"])
    dialog.edits["minutes"].setText("15")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "15"}

    replacement = CorrectionDialog(legacy, rules=RULES)
    select_category(replacement.classification_picker, MEMBERS[1])
    assert legacy["middle"] not in combo_values(replacement.classification_picker.combos["middle"])
    assert legacy["minor"] not in combo_values(replacement.classification_picker.combos["minor"])
    replacement.validate_and_accept()
    assert replacement.patch == MEMBERS[1]


@pytest.mark.parametrize("multiple", [False, True])
def test_opening_and_saving_unchanged_lists_does_not_confirm_classification(
    app, monkeypatch, multiple
):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[-1]))
    record = multiple_record() if multiple else {**MEMBERS[0], **component_payload([MEMBERS[0]])}
    dialog = CorrectionDialog(record, rules=RULES)
    assert not dialog.confirm.isChecked() and not dialog.multiple_confirm.isChecked()
    assert dialog.patch == {}
    dialog.validate_and_accept()
    assert messages and dialog.patch == {}
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.reject()


def test_incomplete_single_selection_cannot_save_an_invalid_parent_child_pair(app, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    dialog = CorrectionDialog(MEMBERS[0], rules=RULES)
    combo = dialog.classification_picker.combos["major"]
    combo.setCurrentIndex(combo.findData("전기·제어"))
    dialog.validate_and_accept()
    assert warnings and dialog.patch == {}
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.reject()


def test_component_row_buttons_do_not_confirm_and_preserve_other_rows(app):
    dialog = CorrectionDialog(multiple_record(), rules=RULES)
    first, second = dialog.component_picker.pickers
    first.remove_button.click()
    assert dialog.component_picker.pickers == [second]
    assert dialog.component_picker.values() == [MEMBERS[1]]
    dialog.component_picker.add_button.click()
    new = dialog.component_picker.pickers[-1]
    assert not any(new.value().values())
    select_category(new, MEMBERS[0])
    assert dialog.component_picker.values() == MEMBERS[::-1]
    assert not dialog.multiple_confirm.isChecked() and not dialog.confirm.isChecked()
    dialog.reject()


def test_time_only_edit_does_not_confirm_observed_multiple_types(app):
    record = multiple_record()
    dialog = CorrectionDialog(record, rules=RULES)
    assert dialog.component_picker.values() == MEMBERS
    assert not dialog.multiple_confirm.isChecked()
    assert not any(dialog.classification_picker.value().values())
    dialog.edits["minutes"].setText("25")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "25"}


def test_ambiguous_alternatives_are_not_seeded_as_multiple_choices(app):
    record = {**multiple_record("ambiguous"), **MEMBERS[0]}
    dialog = CorrectionDialog(record, rules=RULES)
    assert not dialog.component_picker.values()
    assert not dialog.multiple_confirm.isChecked()
    dialog.edits["minutes"].setText("25")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "25"}


def test_explicit_multiple_confirmation_is_canonical_and_replaces_single_override(app, store):
    existing = {**MEMBERS[0], "minutes": "10"}
    record = {**MEMBERS[0], **component_payload([MEMBERS[0]])}
    dialog = CorrectionDialog(record, existing, rules=RULES)
    choose_components(dialog, MEMBERS[::-1])
    dialog.confirm.setChecked(True)
    dialog.multiple_confirm.setChecked(True)
    assert not dialog.confirm.isChecked()
    assert not dialog.classification_picker.isEnabled()
    dialog.validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert parse_components(dialog.patch[COMPONENT_FIELD]) == MEMBERS
    assert all(dialog.patch[key] is None for key in ("major", "middle", "minor"))
    store.update_override("event", existing)
    store.update_override("event", dialog.patch)
    saved = store.override("event")
    assert parse_components(saved[COMPONENT_FIELD]) == MEMBERS
    assert not any(key in saved for key in ("major", "middle", "minor"))
    assert saved["minutes"] == "10"


@pytest.mark.parametrize(
    "members",
    [
        [],
        [MEMBERS[0]],
        [MEMBERS[0], MEMBERS[0]],
        [{"major": "기계"}, MEMBERS[1]],
    ],
)
def test_multiple_confirmation_rejects_missing_or_duplicate_types(app, monkeypatch, members):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    dialog = CorrectionDialog(multiple_record(), rules=RULES)
    choose_components(dialog, members)
    dialog.multiple_confirm.setChecked(True)
    dialog.validate_and_accept()
    assert warnings and dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.patch == {}
    dialog.reject()


def test_unconfirmed_member_changes_and_cancel_preserve_saved_classification(app):
    saved = {COMPONENT_FIELD: json.dumps(MEMBERS, ensure_ascii=False), "minutes": "12"}
    dialog = CorrectionDialog(multiple_record(), saved, rules=RULES)
    choose_components(dialog, [{"major": "기계"}])
    dialog.edits["minutes"].setText("13")
    dialog.validate_and_accept()
    assert dialog.patch == {"minutes": "13"}

    cancelled = CorrectionDialog(multiple_record(), saved, rules=RULES)
    choose_components(cancelled, MEMBERS[::-1])
    cancelled.multiple_confirm.setChecked(True)
    cancelled.reject()
    assert cancelled.patch == {} and not cancelled.cleared
    assert parse_components(saved[COMPONENT_FIELD]) == MEMBERS


def test_saved_multiple_can_be_reopened_removed_or_replaced_with_single(app, monkeypatch):
    saved = {COMPONENT_FIELD: json.dumps(MEMBERS, ensure_ascii=False), "minutes": "12"}
    record = multiple_record()
    reopened = CorrectionDialog(record, saved, rules=RULES)
    assert reopened.component_picker.values() == MEMBERS
    assert not reopened.multiple_confirm.isChecked()
    assert reopened.clear_button.isEnabled()
    choose_components(reopened, [])
    reopened.validate_and_accept()
    assert reopened.patch == {COMPONENT_FIELD: None}

    single = CorrectionDialog(record, saved, rules=RULES)
    select_category(single.classification_picker, MEMBERS[0])
    single.confirm.setChecked(True)
    single.validate_and_accept()
    assert single.patch == {**MEMBERS[0], COMPONENT_FIELD: None}

    clear = CorrectionDialog(record, saved, rules=RULES)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    clear.clear_all()
    assert clear.cleared and clear.result() == QDialog.DialogCode.Accepted
    assert clear.patch == {}


def test_correction_patch_never_confirms_a_component_list_without_explicit_choice():
    record = multiple_record()
    initial = initial_values(record, {})
    changed = {**initial, "minutes": "30", COMPONENT_FIELD: json.dumps(MEMBERS)}
    assert correction_patch(initial, changed, {}, confirm=False) == {"minutes": "30"}
    assert (
        parse_components(
            correction_patch(initial, changed, {}, confirm=False, confirm_components=True)[
                COMPONENT_FIELD
            ]
        )
        == MEMBERS
    )


def test_component_views_show_overlapping_event_counts_without_duplicating_minutes(
    app, store, input_file
):
    config = store.load()
    loaded = load_excel(input_file, config["column_mapping"])
    result = run_analysis(loaded, config, AnalysisOptions())
    frame = result.selected.assign(**component_payload(MEMBERS, mode="multiple"))
    components = pd.DataFrame(
        {
            "component_type": [type_label(member) for member in MEMBERS],
            "count": [3, 2],
            "manual_count": [1, 1],
            "review_count": [2, 1],
            "count_share": [0.75, 0.5],
        }
    )
    trends = components.assign(period="2026-01")
    result = replace(
        result,
        selected=frame,
        tables={
            **result.tables,
            "review": frame,
            "component": components,
            "component_trend": trends,
        },
    )
    window = MainWindow(store)
    window.loaded_ready(loaded)
    window.analysis_ready(result)
    for key in ("component", "component_trend"):
        pane = window.panes[key]
        assert pane.model.frame["count"].sum() > result.metrics["selected_rows"]
        assert "중복 포함" in pane.description.text()
        assert "정지시간" in pane.description.text()
        assert "total_minutes" not in pane.model.frame
    for key in ("detail", "review"):
        pane = window.panes[key]
        assert not pane.table.isColumnHidden(pane.model.frame.columns.get_loc("component_types"))
        assert pane.table.isColumnHidden(pane.model.frame.columns.get_loc("component_details"))
        pane.extra_columns.setChecked(True)
        for field in (
            "classification_mode",
            "component_count",
            "component_types",
            "component_details",
            "combination_key",
        ):
            column = pane.model.frame.columns.get_loc(field)
            assert not pane.table.isColumnHidden(column)
    assert (
        window.panes["type"].model.frame["total_minutes"].sum() == result.metrics["total_minutes"]
    )
    window.close()


def test_gui_multiple_confirmation_is_applied_and_can_be_cleared(
    app, store, input_file, monkeypatch
):
    config = store.load()
    loaded = load_excel(input_file, config["column_mapping"])
    before = run_analysis(loaded, config, AnalysisOptions())
    record = before.selected.iloc[0].to_dict()
    dialog = CorrectionDialog(record, rules=RULES)
    choose_components(dialog, MEMBERS)
    dialog.multiple_confirm.setChecked(True)
    dialog.validate_and_accept()
    store.update_override(record["event_id"], dialog.patch)

    after = run_analysis(loaded, store.load(), AnalysisOptions())
    row = after.selected.loc[after.selected["event_id"].eq(record["event_id"])].iloc[0]
    assert row["status"] == K["manual_multi"]
    assert row["component_count"] == 2
    assert parse_components(row["component_details"]) == MEMBERS
    assert after.metrics["selected_rows"] == before.metrics["selected_rows"]
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"]
    assert "사용자확정" in row["classification_reason"]

    reopened = CorrectionDialog(row.to_dict(), store.override(record["event_id"]), rules=RULES)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    reopened.clear_all()
    assert reopened.cleared
    store.clear_override(record["event_id"])
    restored = run_analysis(loaded, store.load(), AnalysisOptions())
    actual = restored.selected.loc[restored.selected["event_id"].eq(record["event_id"])].iloc[0]
    assert actual["status"] == record["status"]
    assert actual["type"] == record["type"]


def test_component_display_is_readable_while_raw_mode_and_json_are_preserved(app):
    from PySide6.QtCore import Qt

    from gui.widgets import FrameModel

    members = [
        {**MEMBERS[0], "rule_id": "BELT", "evidence": "타이밍벨트 마모 확인"},
        {**MEMBERS[1], "rule_id": "SENSOR", "evidence": "근접센서 교체 확인"},
    ]
    payload = component_payload(members, mode="multiple")
    original = pd.DataFrame([payload])
    model = FrameModel(original)
    mode_index = model.index(0, model.frame.columns.get_loc("classification_mode"))
    details_index = model.index(0, model.frame.columns.get_loc("component_details"))
    assert mode_index.data() == "복수 유형 조합"
    assert mode_index.data(Qt.ItemDataRole.UserRole) == "multiple"
    text = details_index.data()
    assert all(
        word in text for word in ("타이밍벨트", "타이밍벨트 마모 확인", "근접센서 교체 확인")
    )
    assert "\n" in text and text == details_index.data(Qt.ItemDataRole.ToolTipRole)
    assert details_index.data(Qt.ItemDataRole.UserRole) == payload["component_details"]
    pd.testing.assert_frame_equal(model.frame, original)

    dialog = CorrectionDialog({**combination_category(members), **payload})
    diagnostic = dialog.diagnostic.toPlainText()
    assert "조합 판정: 복수 유형 조합" in diagnostic
    assert text in diagnostic
    assert payload["component_details"] not in diagnostic
    dialog.reject()


def test_monthly_component_table_preserves_chronology_after_numeric_sort(app):
    from PySide6.QtCore import Qt

    from gui.widgets import TablePane

    frame = pd.DataFrame(
        {
            "period": ["2026-03", "2026-01", "2026-02"],
            "component_type": ["A"] * 3,
            "count": [10, 2, 1],
        }
    )
    pane = TablePane(sort_policy="period")
    pane.set_frame(frame)
    assert pane.model.frame.period.tolist() == ["2026-01", "2026-02", "2026-03"]
    count_column = pane.model.frame.columns.get_loc("count")
    pane.table.sortByColumn(count_column, Qt.SortOrder.DescendingOrder)
    assert pane.proxy.index(0, 0).data() == "2026-03"
    pane.reset_sort()
    assert [pane.proxy.index(row, 0).data() for row in range(3)] == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]
    assert pane.reset_sort_button.text() == "시간순 정렬"
