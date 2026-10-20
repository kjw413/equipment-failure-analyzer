from __future__ import annotations

import hashlib
import json
from datetime import time, timedelta

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.classifier import RuleClassifier
from core.config import ConfigStore
from core.equipment_names import code_key, equipment_catalog, resolve_name, validate_names
from core.excel_loader import validate_path
from core.i18n import K
from core.models import AnalysisOptions, UserError
from core.preprocessing import normalize, parse_date, parse_duration
from report.excel_report import DETAIL_COLS, SHEETS, export_report


def test_exact_code_matching_and_case():
    assert code_key(" if18115 ") == "IF18115"
    assert resolve_name(" if18115 ", "Original", {"IF18115": "VITAL#2"}) == ("VITAL#2", True)
    assert resolve_name("IF181150", "Original", {"IF18115": "VITAL#2"}) == ("IF181150", False)
    assert resolve_name("IF000", "Original", {}) == ("IF000", False)
    assert resolve_name("", "Name only", {}) == ("Name only", False)


def test_save_reload_replace_backup_and_delete(store):
    store.save_equipment_names({"IF18115": "VITAL#2", "IF20000": "OTHER#1"})
    store.save_equipment_names({"IF18115": "VITAL#2 NEW", "IF20000": "OTHER#1"})
    restarted = ConfigStore(store.root)
    saved = restarted.load()["equipment_names"]
    assert saved["mappings"] == {"IF18115": "VITAL#2 NEW", "IF20000": "OTHER#1"}
    assert saved["updated_at"]
    backup = json.loads((store.config_dir / "equipment_names.json.bak").read_text())
    assert backup["mappings"]["IF18115"] == "VITAL#2"
    restarted.save_equipment_names({"IF18115": "", "IF20000": "OTHER#1"})
    assert "IF18115" not in restarted.load()["equipment_names"]["mappings"]
    # Recreating ConfigStore never restores bundled defaults over an existing user file.
    assert "IF18115" not in ConfigStore(store.root).load()["equipment_names"]["mappings"]


def test_invalid_mapping_keeps_last_good_save(store):
    before = (store.config_dir / "equipment_names.json").read_bytes()
    for mapping in (
        {"A": "Same", "B": "Same"},
        {"A": "bad\nname"},
        {"": "Name"},
        {"A": "B", "B": "C"},
    ):
        with pytest.raises(UserError):
            store.save_equipment_names(mapping)
        assert (store.config_dir / "equipment_names.json").read_bytes() == before


def test_canonical_duplicate_code_rejected():
    with pytest.raises(UserError):
        validate_names({"a": "One", " A ": "Two"})


def test_last_input_changes_name_not_totals_or_source(store, input_file):
    source_hash = hashlib.sha256(input_file.read_bytes()).hexdigest()
    first = analyze_file(store, input_file)
    assert first.metrics["selected_rows"] == 4
    assert first.metrics["total_minutes"] == 95
    assert first.metrics["valid_time_rows"] == 3
    assert first.metrics["product_count"] == 2
    assert "VITAL#2" in first.tables["equipment"].equipment.to_list()
    assert len(equipment_catalog(first.loaded)) == 2
    store.save_equipment_names({"IF18115": "VITAL#2 RENAMED"})
    second = analyze_file(ConfigStore(store.root), input_file)
    assert "VITAL#2 RENAMED" in second.tables["equipment"].equipment.to_list()
    assert "VITAL#2" not in second.tables["equipment"].equipment.to_list()
    assert second.metrics["total_minutes"] == first.metrics["total_minutes"]
    assert second.selected.event_id.to_list() == first.selected.event_id.to_list()
    assert (
        second.selected.raw_equipment_name.to_list() == first.selected.raw_equipment_name.to_list()
    )
    assert hashlib.sha256(input_file.read_bytes()).hexdigest() == source_hash


def test_workbook_names_formulas_and_report_code_conversion(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    out = export_report(result, tmp_path / "output.xlsx")
    formulas = load_workbook(out, data_only=False)
    values = load_workbook(out, data_only=True)
    equipment = values[SHEETS["equipment"]]
    assert "VITAL#2" in [equipment.cell(row, 1).value for row in range(7, equipment.max_row + 1)]
    assert values[SHEETS["summary"]]["A7"].value == 4
    assert values[SHEETS["summary"]]["E7"].value == 95
    assert formulas[SHEETS["summary"]]["E7"].data_type == "f"
    detail = values[SHEETS["detail"]]
    code_col = DETAIL_COLS.index("equipment_code") + 1
    name_col = DETAIL_COLS.index("report_equipment") + 1
    named_row = next(
        row for row in range(7, detail.max_row + 1) if detail.cell(row, code_col).value == "VITAL#2"
    )
    assert detail.cell(named_row, code_col).value == "VITAL#2"
    assert result.selected.iloc[0]["equipment_code"] == "IF18115"
    assert "product" not in SHEETS
    assert not any("\uc81c\ud488\ubcc4\ubd84\uc11d" in name for name in values.sheetnames)
    assert [int(name[:2]) for name in values.sheetnames if not name.startswith("_")] == list(
        range(1, 18)
    )
    assert len(values[SHEETS["equipment_types"]]._images) == result.metrics["equipment_count"]
    assert len(values[SHEETS["equipment"]]._images) == result.metrics["equipment_count"]
    for sheet in values:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    assert "IF18115" not in cell.value
    assert detail.cell(named_row, name_col).value == "VITAL#2"
    assert SHEETS["names"] in values.sheetnames
    errors = []
    for sheet in values:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "e":
                    errors.append((sheet.title, cell.coordinate, cell.value))
    assert not errors
    for sheet in formulas:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    assert "#REF!" not in cell.value
                    assert values[sheet.title][cell.coordinate].data_type != "e"
    assert len(values[SHEETS["summary"]]._images) == 2
    values.close()
    formulas.close()


def test_empty_fault_report(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(date_from="2030-01-01"))
    assert result.metrics["selected_rows"] == 0
    assert result.metrics["total_minutes"] is None
    out = export_report(result, tmp_path / "empty.xlsx")
    book = load_workbook(out, data_only=True)
    assert book[SHEETS["summary"]]["A7"].value == 0
    assert book[SHEETS["summary"]]["E7"].value in (None, "")
    book.close()


def test_alias_collision_with_unknown_raw_code_rejected(store, input_file):
    store.save_equipment_names({"IF18115": "IF20000"})
    with pytest.raises(UserError):
        analyze_file(store, input_file)


def test_manual_override_survives_renaming(store, input_file):
    before = analyze_file(store, input_file)
    event = before.selected.iloc[0].event_id
    store.save_override(
        event, {"major": "A", "middle": "B", "minor": "C", "product": "Corrected product"}
    )
    store.save_equipment_names({"IF18115": "NEW NAME"})
    after = analyze_file(store, input_file)
    row = after.selected.loc[after.selected.event_id.eq(event)].iloc[0]
    assert row.type == "A / B / C"
    assert row.equipment == "NEW NAME"
    assert row["product"] == "Corrected product"


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        ("1\uc2dc\uac04 20\ubd84", "minutes", 80),
        ("01:30", "minutes", 90),
        (1, "hours", 60),
        (120, "seconds", 2),
        (0.5, "excel_days", 720),
        (timedelta(seconds=90), "minutes", 1.5),
        (time(0, 30), "minutes", 30),
        ("no data", "minutes", None),
        (-10, "minutes", None),
        ("00:99", "minutes", None),
        (0, "minutes", 0),
        ("10min", "minutes", 10),
    ],
)
def test_duration(value, unit, expected):
    assert parse_duration(value, unit) == expected


def test_dates():
    assert parse_date(20260928) == pd.Timestamp("2026-09-28")
    assert pd.isna(parse_date("not a date"))


def test_file_validation(tmp_path):
    with pytest.raises(UserError):
        validate_path(tmp_path / "file.txt")
    with pytest.raises(UserError):
        validate_path(tmp_path / "missing.xlsx")


def test_synthetic_classifier_never_guesses_unknown(store):
    classifier = RuleClassifier(store.load()["rules"])
    unknown = classifier.classify("unique unknown problem 92838475")
    assert unknown["status"] == K["unclassified"]
    motor = classifier.classify(normalize("MOTOR TRIP"))
    assert motor["status"] in (K["auto"], K["review"])


def test_name_projection_boundary_case_and_idempotence():
    from core.report_view import ReportNames

    names = ReportNames({"IF18115": "VITAL#2", "IF20000": "OTHER#1"})
    assert names.text("if18115 / IF20000: trip") == "VITAL#2 / OTHER#1: trip"
    assert names.text("IF181150") == "IF181150"
    assert names.text("XIF18115") == "XIF18115"
    assert names.text("IF18115_suffix") == "IF18115_suffix"
    assert names.text(None) is None
    text = names.text("IF18115: trip")
    assert names.text(text) == text
    nested = ReportNames({"A": "LINE B", "B": "BETA"})
    assert nested.text(nested.text("A trip")) == "LINE B trip"


def test_projection_preserves_source_snapshot_and_ids(store, input_file):
    from core.report_view import report_result

    before = analyze_file(store, input_file)
    projected = report_result(before)
    assert before.selected.iloc[0].equipment_code == "IF18115"
    assert projected.selected.iloc[0].equipment_code == "VITAL#2"
    assert projected.selected.record_id.tolist() == before.selected.record_id.tolist()
    assert projected.metrics == before.metrics
    assert projected.loaded is not before.loaded
    assert projected.loaded.file_hash == before.loaded.file_hash


def test_per_equipment_rank_and_local_denominator(store, input_file):
    from core.equipment_breakdown import donut_slices, type_breakdown

    result = analyze_file(store, input_file)
    for equipment in result.tables["equipment"].equipment:
        subset = result.selected.loc[result.selected.equipment.eq(equipment)]
        table = type_breakdown(result.selected, equipment)
        assert table["count"].sum() == len(subset)
        assert table.count_share.sum() == pytest.approx(1)
        assert table["count"].tolist() == sorted(table["count"], reverse=True)
        assert table["rank"].tolist() == list(range(1, len(table) + 1))
        slices = donut_slices(table)
        assert slices.value.sum() == len(subset)
        assert slices.share.sum() == pytest.approx(1)


def test_donut_other_includes_all_smaller_types():
    from core.equipment_breakdown import donut_slices

    table = pd.DataFrame({"type": [f"Type {i}" for i in range(12)], "count": list(range(1, 13))})
    slices = donut_slices(table, top_n=5)
    assert len(slices) == 6
    assert slices.value.sum() == sum(range(1, 13))
    assert slices.iloc[-1].value == sum(range(1, 8))
    assert slices.share.sum() == pytest.approx(1)
    assert donut_slices(pd.DataFrame()).empty
    zero = pd.DataFrame({"type": ["A"], "count": [0]})
    assert donut_slices(zero).empty


def test_current_settings_hide_old_product_sheet(store):
    old = store.read("settings.json")
    old["report_sections"] = ["summary", "equipment", "product", "type"]
    from core.config import atomic_json

    atomic_json(store.config_dir / "settings.json", old)
    cfg = ConfigStore(store.root).load()
    assert "product" not in cfg["settings"]["report_sections"]
    assert "equipment_types" in cfg["settings"]["report_sections"]
    assert cfg["equipment_names"]["mappings"]["IF18115"] == "VITAL#2"


def test_breakdown_total_cached_and_formulas(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    path = export_report(result, tmp_path / "ranked.xlsx")
    wb = load_workbook(path, data_only=True)
    ws = wb[SHEETS["equipment_types"]]
    totals = [r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == "\ud569\uacc4"]
    assert len(totals) == 2
    assert sum(ws.cell(r, 3).value for r in totals) == 4
    assert sum(ws.cell(r, 6).value or 0 for r in totals) == 95
    assert all(ws.cell(r, 4).value == 1 for r in totals)
    assert all(ws.cell(r, 7).value == 1 for r in totals)
    wb.close()


def test_name_with_wildcards_and_formula_like_text(store, input_file, tmp_path):
    store.save_equipment_names({"IF18115": "=LINE*?#2", "IF20000": "Line 'B'"})
    result = analyze_file(store, input_file)
    path = export_report(result, tmp_path / "safe_names.xlsx")
    wb = load_workbook(path, data_only=False)
    detail = wb[SHEETS["detail"]]
    column = DETAIL_COLS.index("report_equipment") + 1
    row = next(
        row for row in range(7, detail.max_row + 1) if detail.cell(row, column).value == "=LINE*?#2"
    )
    cell = detail.cell(row, column)
    assert cell.value == "=LINE*?#2"
    assert cell.data_type == "s"
    vals = load_workbook(path, data_only=True)
    assert vals[SHEETS["summary"]]["A7"].value == 4
    for sheet in vals:
        for row in sheet.iter_rows():
            assert not any(c.data_type == "e" for c in row)
    wb.close()
    vals.close()


def test_legacy_override_save_merges_values_without_removing_existing_corrections(store):
    store.update_override("event", {"major": "A", "middle": "B", "minor": "C", "minutes": "12"})
    store.save_override("event", {"minutes": "", "product": "Updated product"})
    saved = store.override("event")
    assert {key: value for key, value in saved.items() if key != "saved_at"} == {
        "major": "A",
        "middle": "B",
        "minor": "C",
        "minutes": "12",
        "product": "Updated product",
    }
    assert saved["saved_at"]
