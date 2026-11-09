"""Line-code display names and explicit equipment grouping preserve source identity."""

import json

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.config import ConfigStore, atomic_json
from core.equipment_names import (
    active_name_mapping,
    effective_name_source,
    equipment_catalog,
    normalize_name_settings,
    resolve_group,
)
from core.excel_loader import load_excel
from core.i18n import K
from core.models import AnalysisOptions, UserError
from core.service import run_analysis


@pytest.fixture
def line_file(input_file):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    sheet["J3"], sheet["K3"] = "라인코드", "라인명"
    for row, code, name in (
        (4, "LC1", "Original line one"),
        (5, "LC1", "Original line one"),
        (6, "LC2", "Original line two"),
        (7, "LC2", "Original line two"),
    ):
        sheet.cell(row, 10, code)
        sheet.cell(row, 11, name)
    # One line can contain several original equipment codes.
    sheet["B5"] = "IF99900"
    workbook.save(input_file)
    workbook.close()
    return input_file


def analyze(store, path, options=None):
    config = store.load()
    loaded = load_excel(path, config["column_mapping"])
    return run_analysis(loaded, config, options or AnalysisOptions())


def test_old_profile_gets_line_default_without_reusing_legacy_code_mapping():
    old = {"schema_version": 1, "mappings": {"if18115": "VITAL#2"}, "owner": "retained"}
    normalized = normalize_name_settings(old)
    assert normalized["source"] == "line"
    assert normalized["mappings"] == {"IF18115": "VITAL#2"}
    assert normalized["line_mappings"] == {}
    assert normalized["grouping"] == {"mode": "prefix", "separator": "#", "overrides": {}}
    assert normalized["owner"] == "retained"
    assert old == {"schema_version": 1, "mappings": {"if18115": "VITAL#2"}, "owner": "retained"}


def test_line_mapping_and_groups_persist_without_changing_legacy_mapping_or_metadata(store):
    path = store.config_dir / "equipment_names.json"
    original = store.read(path.name)
    original["owner"] = {"note": "keep"}
    atomic_json(path, original)
    grouping = {"mode": "prefix", "separator": "#", "overrides": {"A#2": "Custom group"}}
    saved = store.save_equipment_names(
        {"lc1": "A#1(1호기)", "LC2": "A#2"}, source="line", grouping=grouping
    )
    assert saved["mappings"] == original["mappings"]
    assert saved["line_mappings"] == {"LC1": "A#1(1호기)", "LC2": "A#2"}
    assert saved["owner"] == original["owner"]
    assert saved["source"] == "line"
    reopened = ConfigStore(store.root)
    assert reopened.load()["equipment_names"] == saved
    before = path.read_bytes()
    reopened.save_equipment_names(saved["line_mappings"], source="line", grouping=grouping)
    assert path.read_bytes() == before
    changed = reopened.save_equipment_names({"EQ1": "Legacy#1"})
    assert changed["source"] == "equipment"
    assert changed["line_mappings"] == saved["line_mappings"]
    assert changed["grouping"] == grouping
    assert changed["owner"] == original["owner"]


@pytest.mark.parametrize(
    "grouping",
    [
        {"mode": "prefix", "separator": ""},
        {"mode": "unknown"},
        {"overrides": {"A#1": "bad\nname"}},
        {"overrides": {"A#1": "A", " a#1 ": "B"}},
    ],
)
def test_invalid_grouping_keeps_existing_saved_names(store, grouping):
    path = store.config_dir / "equipment_names.json"
    before = path.read_bytes()
    with pytest.raises(UserError):
        store.save_equipment_names({"LC1": "A#1"}, source="line", grouping=grouping)
    assert path.read_bytes() == before


def test_default_grouping_and_explicit_assignments():
    assert resolve_group("A#1(1호기)") == "A"
    assert resolve_group("A#2") == "A"
    assert resolve_group("B") == "B"
    assert resolve_group("A#1", {"mode": "none"}) == "A#1"
    assert resolve_group(" A#1 ", {"overrides": {"a#1": "Shared", "B": "Shared"}}) == "Shared"
    assert resolve_group("A-1", {"separator": "-"}) == "A"


def test_mapped_line_source_ignores_equipment_names_and_keeps_empty_lines_empty(store, line_file):
    store.save_equipment_names({"LC1": "A#1(1호기)", "LC2": "A#2"}, source="line")
    result = analyze(store, line_file)
    records = result.all_records.set_index("source_row")
    assert records.loc[4, "report_equipment"] == "A#1(1호기)"
    assert records.loc[5, "report_equipment"] == "A#1(1호기)"
    assert records.loc[6, "report_equipment"] == "A#2"
    assert records.loc[8, "report_equipment"] == K["missing"]
    assert records.loc[8, "name_mapped"] == False  # noqa: E712
    assert records.loc[4, "line_code"] == "LC1"
    assert records.loc[4, "raw_line_name"] == "Original line one"
    assert records.loc[4, "equipment_code"] == "IF18115"
    assert records.loc[5, "equipment_code"] == "IF99900"
    assert records.loc[4, "equipment_group"] == "A"
    assert records.loc[6, "equipment_group"] == "A"
    assert result.metrics["total_minutes"] == 95
    assert effective_name_source(result.loaded, result.config_snapshot) == "line"
    assert active_name_mapping(result.loaded, result.config_snapshot) == {
        "LC1": "A#1(1호기)",
        "LC2": "A#2",
    }
    assert equipment_catalog(result.loaded, source="line") == [
        {"code": "LC1", "raw_name": "Original line one"},
        {"code": "LC2", "raw_name": "Original line two"},
    ]


def test_group_basis_combines_converted_names_without_merging_source_identities(store, line_file):
    store.save_equipment_names({"LC1": "A#1(1호기)", "LC2": "A#2"}, source="line")
    mapped = analyze(store, line_file)
    grouped = analyze(store, line_file, AnalysisOptions(equipment_basis="group"))
    assert grouped.all_records.event_id.tolist() == mapped.all_records.event_id.tolist()
    assert (
        grouped.all_records.report_equipment.tolist()
        == mapped.all_records.report_equipment.tolist()
    )
    group = grouped.tables["equipment"].set_index("equipment").loc["A"]
    assert group["count"] == 3
    assert group["total_minutes"] == 95
    assert set(grouped.selected.equipment) == {"A", K["missing"]}
    assert grouped.metrics["total_minutes"] == mapped.metrics["total_minutes"]


def test_unknown_raw_line_code_collision_is_still_rejected(store, line_file):
    store.save_equipment_names({"LC1": "LC2"}, source="line")
    with pytest.raises(UserError):
        analyze(store, line_file)


def test_no_mapped_line_column_uses_equipment_legacy_mapping(store, input_file):
    result = analyze(store, input_file)
    assert effective_name_source(result.loaded, result.config_snapshot) == "equipment"
    assert result.all_records.iloc[0].report_equipment == "VITAL#2"
    assert "IF18115" in active_name_mapping(result.loaded, result.config_snapshot)


def test_line_name_only_is_line_identity_and_never_uses_equipment_code(store, line_file):
    config = store.load()
    config["equipment_names"]["line_mappings"] = {"ORIGINAL LINE ONE": "A#1"}
    loaded = load_excel(line_file, config["column_mapping"])
    loaded.mapping["line_id"] = None
    loaded.frame.loc[loaded.frame["__source_row"].eq(8), "라인명"] = pd.NA
    result = run_analysis(loaded, config, AnalysisOptions())
    records = result.all_records.set_index("source_row")
    assert effective_name_source(loaded, config) == "line"
    assert records.loc[4, "report_equipment"] == "A#1"
    assert records.loc[8, "report_equipment"] == K["missing"]
    assert records.loc[4, "equipment_code"] == "IF18115"


def test_saved_equipment_source_remains_selectable_with_line_columns(store, line_file):
    store.save_equipment_names({"IF18115": "Legacy machine"}, source="equipment")
    result = analyze(store, line_file)
    assert effective_name_source(result.loaded, result.config_snapshot) == "equipment"
    assert result.all_records.iloc[0].report_equipment == "Legacy machine"
    assert (
        json.loads((store.config_dir / "equipment_names.json").read_text(encoding="utf-8"))[
            "source"
        ]
        == "equipment"
    )
