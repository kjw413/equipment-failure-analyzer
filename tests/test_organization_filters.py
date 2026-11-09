"""Factory/team filters combine exactly with analysis scope and available source choices."""

from dataclasses import replace

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.analyzer import select_records
from core.equipment_names import organization_filter_choices
from core.excel_loader import load_excel
from core.i18n import K
from core.models import AnalysisOptions, LoadedData
from core.service import run_analysis


def selection_records():
    rows = [
        ("duplicate", "A", "T1", "fault", "2026-01-01"),
        ("duplicate", "A", "T1", "fault", "2026-01-01"),
        ("prefix-factory", "A2", "T1", "fault", "2026-01-02"),
        ("different-team", "A", "T2", "planned", "2026-01-02"),
        ("late", "A", "T1", "fault", "2026-01-03"),
        ("missing", K["missing"], K["missing"], "fault", "2026-01-02"),
        ("prefix-team", "A", "T10", "fault", "2026-01-02"),
        ("planned", "A", "T1", "planned", "2026-01-02"),
        ("selected", "A", "T1", "fault", "2026-01-02"),
    ]
    frame = pd.DataFrame(rows, columns=["event_id", "factory", "team", "kind", "date"])
    frame["kind"] = frame["kind"].map(K)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def test_new_options_preserve_previous_positional_arguments():
    options = AnalysisOptions("all", "registered", "2026-01-01", "2026-01-02", "hours", True, 3)
    assert options.scope == "all"
    assert options.top_n == 3 and options.duration_unit == "hours" and options.deduplicate
    assert options.factory is None and options.team is None


def test_factory_and_team_filters_are_exact_and_combine_with_scope_dates_and_deduplication():
    records = selection_records()
    options = AnalysisOptions(
        factory="A", team="T1", date_from="2026-01-01", date_to="2026-01-02", deduplicate=True
    )
    assert select_records(records, options).event_id.tolist() == ["duplicate", "selected"]
    assert select_records(records, replace(options, scope="all")).event_id.tolist() == [
        "duplicate",
        "planned",
        "selected",
    ]
    assert select_records(records, replace(options, deduplicate=False)).event_id.tolist() == [
        "duplicate",
        "duplicate",
        "selected",
    ]
    assert len(records) == 9


def test_team_can_filter_across_factories_and_missing_values_are_selectable():
    records = selection_records()
    assert select_records(records, AnalysisOptions(team="T1")).event_id.tolist() == [
        "duplicate",
        "duplicate",
        "prefix-factory",
        "late",
        "selected",
    ]
    assert select_records(
        records, AnalysisOptions(factory=K["missing"], team=K["missing"])
    ).event_id.tolist() == ["missing"]


@pytest.mark.parametrize(
    "options",
    [
        AnalysisOptions(factory="Unknown factory"),
        AnalysisOptions(factory="A", team="Unknown team"),
        AnalysisOptions(factory="A2", team="T2"),
        AnalysisOptions(factory=""),
        AnalysisOptions(team=""),
    ],
)
def test_unmatched_selection_is_empty_instead_of_falling_back_to_all(options):
    assert select_records(selection_records(), options).empty


@pytest.fixture
def source_choices(tmp_path):
    frame = pd.DataFrame(
        {
            "line_code": ["L1", "L1", "L2", "L3", "L4", "L5", None],
            "line_name": [
                "[A] North",
                "[A] North",
                "[A2] South",
                "[A] Unknown team",
                "No factory",
                "[B] Original factory",
                "[Raw] Name only",
            ],
            "equipment_code": ["E1", "E1", "E2", "E3", "E4", "E5", "E6"],
            "equipment_name": ["Machine " + str(i) for i in range(7)],
        }
    )
    loaded = LoadedData(
        tmp_path / "source.xlsx",
        "Events",
        1,
        frame,
        list(frame),
        {
            "line_id": "line_code",
            "line_name": "line_name",
            "equipment_id": "equipment_code",
            "equipment_name": "equipment_name",
        },
        "synthetic",
        "hash",
    )
    names = {
        "source": "line",
        "organization": {
            "line": {
                "L1": {"team": "T1"},
                "L2": {"team": "T2"},
                "L4": {"team": "NoFactory"},
                "L5": {"factory": "Manual", "team": "T3"},
                "[RAW] NAME ONLY": {"factory": "NameFactory", "team": "NameTeam"},
            },
            "equipment": {"E1": {"factory": "EquipmentFactory", "team": "EquipmentTeam"}},
        },
    }
    return loaded, names


def test_choices_use_manual_factory_override_raw_name_fallback_and_exact_team_cascade(
    source_choices,
):
    loaded, names = source_choices
    expected_factories = sorted(["A", "A2", "Manual", "NameFactory", K["missing"]])
    choices = organization_filter_choices(loaded, names)
    assert choices == {
        "factories": expected_factories,
        "teams": sorted(["T1", "T2", "T3", "NoFactory", "NameTeam", K["missing"]]),
    }
    assert organization_filter_choices(loaded, {"equipment_names": names}, factory="A") == {
        "factories": expected_factories,
        "teams": sorted(["T1", K["missing"]]),
    }
    assert organization_filter_choices(loaded, names, factory="A2")["teams"] == ["T2"]
    assert organization_filter_choices(loaded, names, factory=K["missing"])["teams"] == [
        "NoFactory"
    ]
    assert organization_filter_choices(loaded, names, factory="Unknown")["teams"] == []
    assert organization_filter_choices(loaded, names, factory="")["teams"] == []


def test_choices_follow_selected_equipment_source_instead_of_line_overrides(source_choices):
    loaded, names = source_choices
    names = {**names, "source": "equipment"}
    choices = organization_filter_choices(loaded, names)
    assert choices["factories"] == sorted(["A", "A2", "B", "Raw", "EquipmentFactory", K["missing"]])
    assert choices["teams"] == sorted(["EquipmentTeam", K["missing"]])
    assert organization_filter_choices(loaded, names, factory="EquipmentFactory")["teams"] == [
        "EquipmentTeam"
    ]


def test_no_mapped_line_columns_fall_back_to_equipment_choices(source_choices):
    loaded, names = source_choices
    no_lines = replace(
        loaded, mapping={"equipment_id": "equipment_code", "equipment_name": "equipment_name"}
    )
    assert organization_filter_choices(no_lines, names) == {
        "factories": sorted(["EquipmentFactory", K["missing"]]),
        "teams": sorted(["EquipmentTeam", K["missing"]]),
    }


def test_line_name_only_and_empty_line_values_never_fall_back_to_equipment(source_choices):
    loaded, names = source_choices
    mapping = {**loaded.mapping, "line_id": None}
    line_names = replace(loaded, mapping=mapping, frame=loaded.frame.iloc[[-1]].copy())
    assert organization_filter_choices(line_names, names) == {
        "factories": ["NameFactory"],
        "teams": ["NameTeam"],
    }
    line_names.frame["line_name"] = pd.NA
    assert organization_filter_choices(line_names, names) == {
        "factories": [K["missing"]],
        "teams": [K["missing"]],
    }


def test_no_loaded_or_no_source_rows_have_no_choices(source_choices):
    loaded, names = source_choices
    assert organization_filter_choices(None, names) == {"factories": [], "teams": []}
    assert organization_filter_choices(replace(loaded, frame=loaded.frame.iloc[:0]), names) == {
        "factories": [],
        "teams": [],
    }


def test_analysis_filters_use_resolved_organization_and_leave_zero_result_zero(store, input_file):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    sheet["J3"], sheet["K3"] = "라인코드", "라인명"
    for row, code, name in (
        (4, "L1", "[A] Original one"),
        (5, "L1", "[A] Original one"),
        (6, "L2", "[A2] Original two"),
        (7, "L2", "[A2] Original two"),
        (8, "L3", "No factory"),
    ):
        sheet.cell(row, 10, code)
        sheet.cell(row, 11, name)
    workbook.save(input_file)
    workbook.close()
    original = input_file.read_bytes()
    store.save_equipment_names(
        {},
        source="line",
        organization={
            "line": {
                "L1": {"team": "Production"},
                "L2": {"factory": "Manual", "team": "Production"},
            }
        },
    )
    config = store.load()
    loaded = load_excel(input_file, config["column_mapping"])
    options = AnalysisOptions(factory="Manual", team="Production")
    selected = run_analysis(loaded, config, options)
    assert selected.selected.source_row.tolist() == [6]
    assert selected.metrics["total_minutes"] == 65
    assert set(selected.all_records.factory) == {"A", "Manual", K["missing"]}
    assert organization_filter_choices(loaded, config)["factories"] == sorted(
        selected.all_records.factory.unique()
    )
    empty = run_analysis(loaded, config, replace(options, team="Unknown"))
    assert empty.metrics["selected_rows"] == 0
    assert empty.tables["equipment"].empty and empty.tables["review"].empty
    assert empty.metrics["total_minutes"] is None
    missing = run_analysis(loaded, config, AnalysisOptions(factory=K["missing"], team=K["missing"]))
    assert missing.selected.source_row.tolist() == [8]
    assert input_file.read_bytes() == original
