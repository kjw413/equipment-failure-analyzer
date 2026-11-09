"""Factory/team overrides and source-line defaults survive analysis and restart."""

import pandas as pd
import pytest
from openpyxl import load_workbook

from core.config import ConfigStore, atomic_json
from core.equipment_names import (
    extract_factory,
    normalize_name_settings,
    normalize_organization,
    organization_catalog,
    resolve_organization,
)
from core.excel_loader import load_excel
from core.i18n import K
from core.models import AnalysisOptions, LoadedData, UserError
from core.service import run_analysis


@pytest.mark.parametrize(
    ("line", "factory"),
    [
        ("[공장A] A#1", "공장A"),
        ("A#2 [ Factory B ]", "Factory B"),
        ("[] [  ] [공장C] [다른 값] 라인", "공장C"),
        ("[ Factory\n  A ] 라인", "Factory A"),
        ("공장 없는 라인", ""),
        ("[닫히지 않은 라인", ""),
        (None, ""),
        (pd.NA, ""),
    ],
)
def test_factory_is_extracted_from_original_line_brackets(line, factory):
    assert extract_factory(line) == factory


def test_old_profiles_gain_empty_organization_without_changing_other_metadata():
    old = {
        "schema_version": 1,
        "mappings": {"EQ1": "Legacy#1"},
        "line_mappings": {"L1": "A#1"},
        "grouping": {"mode": "none", "separator": "#", "overrides": {"A#1": "Shared"}},
        "owner": "keep",
    }
    normalized = normalize_name_settings(old)
    assert normalized["organization"] == {"line": {}, "equipment": {}}
    for key, value in old.items():
        assert normalized[key] == value
    assert "organization" not in old


def test_organization_normalizes_codes_and_blank_values():
    assert normalize_organization(
        {
            "line": {
                " l1 ": {"factory": " Manual factory ", "team": " Team one "},
                "L2": {"factory": "", "team": "Team two"},
                "L3": {"factory": "  ", "team": ""},
            }
        }
    ) == {
        "line": {
            "L1": {"factory": "Manual factory", "team": "Team one"},
            "L2": {"factory": "", "team": "Team two"},
        },
        "equipment": {},
    }


@pytest.mark.parametrize(
    "organization",
    [
        [],
        {"unknown": {}},
        {"line": []},
        {"line": {"L1": "bad"}},
        {"line": {"": {"factory": "Factory"}}},
        {"line": {"L1": {"factory": "Bad\nname"}}},
        {"line": {"L1": {"team": 1}}},
        {"line": {"L1": {"team": "X" * 121}}},
        {"line": {"l1": {"team": "One"}, " L1 ": {"team": "Two"}}},
    ],
)
def test_invalid_organization_does_not_replace_good_settings(store, organization):
    path = store.config_dir / "equipment_names.json"
    before = path.read_bytes()
    with pytest.raises(UserError):
        store.save_equipment_names({"L1": "A#1"}, source="line", organization=organization)
    assert path.read_bytes() == before


def test_organization_saves_both_sources_and_is_preserved_when_omitted(store):
    path = store.config_dir / "equipment_names.json"
    existing = store.read(path.name)
    existing["owner"] = "Keep metadata"
    atomic_json(path, existing)
    organization = {
        "line": {"l1": {"factory": "Factory A", "team": "Team one"}},
        "equipment": {"eq1": {"factory": "Factory B", "team": "Team two"}},
    }
    saved = store.save_equipment_names({"L1": "A#1"}, source="line", organization=organization)
    assert saved["organization"] == normalize_organization(organization)
    assert saved["mappings"] == existing["mappings"]
    assert saved["owner"] == existing["owner"]
    changed = store.save_equipment_names({"EQ1": "Legacy#2"}, source="equipment")
    assert changed["organization"] == saved["organization"]
    assert changed["line_mappings"] == saved["line_mappings"]
    assert changed["grouping"] == saved["grouping"]
    assert ConfigStore(store.root).load()["equipment_names"] == changed
    before = path.read_bytes()
    store.save_equipment_names({"EQ1": "Legacy#2"}, source="equipment")
    assert path.read_bytes() == before
    updated = store.save_equipment_names(
        {"L1": "A#1"}, source="line", organization={"line": {"L1": {"team": "New team"}}}
    )
    assert updated["organization"]["equipment"] == saved["organization"]["equipment"]
    assert updated["organization"]["line"] == {"L1": {"factory": "", "team": "New team"}}
    unchanged = store.save_equipment_names({"L1": "A#1"}, source="line", organization={})
    assert unchanged["organization"] == updated["organization"]
    cleared = store.save_equipment_names({"L1": "A#1"}, source="line", organization={"line": {}})
    assert cleared["organization"]["line"] == {}
    assert cleared["organization"]["equipment"] == saved["organization"]["equipment"]


def test_manual_factory_and_team_override_auto_for_only_the_selected_source():
    settings = {
        "organization": {
            "line": {"L1": {"factory": "Manual factory", "team": "Production"}},
            "equipment": {"L1": {"factory": "", "team": "Maintenance"}},
        }
    }
    assert resolve_organization(" l1 ", "[Auto factory] line", settings) == {
        "factory": "Manual factory",
        "team": "Production",
    }
    assert resolve_organization("L1", "[Auto factory] line", settings, source="equipment") == {
        "factory": "Auto factory",
        "team": "Maintenance",
    }
    assert resolve_organization("L2", "No brackets", settings) == {
        "factory": K["missing"],
        "team": K["missing"],
    }
    assert resolve_organization("L2", "[Factory] line", {"equipment_names": settings}) == {
        "factory": "Factory",
        "team": K["missing"],
    }


def test_catalog_separates_conflicting_factories_and_uses_line_names_for_equipment(tmp_path):
    frame = pd.DataFrame(
        {
            "line_code": ["L1", "L1", "L2", "L2", None],
            "line_name": [
                "[Factory A] line",
                "line without bracket",
                "[Factory A] line",
                "[Factory B] line",
                "[Factory C] only name",
            ],
            "equipment_code": ["E1", "E1", "E2", "E2", "E3"],
            "equipment_name": ["[Wrong factory] equipment"] * 5,
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
    assert organization_catalog(loaded) == {
        "L1": {"factory": "Factory A", "team": ""},
        "L2": {"factory": "", "team": ""},
        "[FACTORY C] ONLY NAME": {"factory": "Factory C", "team": ""},
    }
    assert organization_catalog(loaded, source="equipment") == {
        "E1": {"factory": "Factory A", "team": ""},
        "E2": {"factory": "", "team": ""},
        "E3": {"factory": "Factory C", "team": ""},
    }


@pytest.fixture
def organization_file(input_file):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    sheet["J3"], sheet["K3"] = "라인코드", "라인명"
    for row, code, raw_name in (
        (4, "L1", "[공장A] 원본 라인1"),
        (5, "L1", "[공장A] 원본 라인1"),
        (6, "L2", "[공장B] 원본 라인2"),
        (7, "L2", "[공장B] 원본 라인2"),
        (8, "L3", "공장 미지정 라인3"),
    ):
        sheet.cell(row, 10, code)
        sheet.cell(row, 11, raw_name)
    workbook.save(input_file)
    workbook.close()
    return input_file


def analyze(store, path, basis="mapped"):
    config = store.load()
    loaded = load_excel(path, config["column_mapping"])
    return run_analysis(loaded, config, AnalysisOptions(equipment_basis=basis))


def test_runtime_auto_factory_manual_override_and_clear_keep_original_records(
    store, organization_file
):
    original = organization_file.read_bytes()
    before = analyze(store, organization_file)
    assert before.all_records.factory.tolist() == ["공장A", "공장A", "공장B", "공장B", K["missing"]]
    store.save_equipment_names(
        {},
        source="line",
        organization={
            "line": {
                "L1": {"factory": "수정 공장", "team": "생산팀"},
                "L3": {"team": "정비팀"},
            }
        },
    )
    manual = analyze(ConfigStore(store.root), organization_file)
    records = manual.all_records.set_index("source_row")
    assert records.loc[4, "factory"] == "수정 공장"
    assert records.loc[4, "team"] == "생산팀"
    assert records.loc[8, "factory"] == K["missing"]
    assert records.loc[8, "team"] == "정비팀"
    assert records.loc[4, "line_code"] == "L1"
    assert records.loc[4, "raw_line_name"] == "[공장A] 원본 라인1"
    assert records.loc[4, "equipment_code"] == "IF18115"
    assert manual.all_records.event_id.tolist() == before.all_records.event_id.tolist()
    assert manual.metrics["total_minutes"] == before.metrics["total_minutes"]
    store.save_equipment_names(
        {}, source="line", organization={"line": {"L1": {"factory": "", "team": "생산팀"}}}
    )
    cleared = analyze(store, organization_file)
    assert cleared.all_records.iloc[0].factory == "공장A"
    assert organization_file.read_bytes() == original


def test_factory_and_team_basis_keep_equal_team_names_in_separate_factories(
    store, organization_file
):
    store.save_equipment_names(
        {},
        source="line",
        organization={
            "line": {
                "L1": {"team": "생산팀"},
                "L2": {"team": "생산팀"},
                "L3": {"team": "정비팀"},
            }
        },
    )
    factories = analyze(store, organization_file, "factory")
    assert set(factories.tables["equipment"].equipment) == {"공장A", "공장B", K["missing"]}
    teams = analyze(store, organization_file, "team")
    table = teams.tables["equipment"].set_index("equipment")
    assert set(table.index) == {"공장A / 생산팀", "공장B / 생산팀", "정비팀"}
    assert table.loc["공장A / 생산팀", "count"] == 2
    assert table.loc["공장A / 생산팀", "total_minutes"] == 30
    assert table.loc["공장B / 생산팀", "count"] == 1
    assert table.loc["공장B / 생산팀", "total_minutes"] == 65
    assert teams.metrics["total_minutes"] == factories.metrics["total_minutes"] == 95


def test_equipment_source_factory_still_comes_from_original_line_name(store, organization_file):
    store.save_equipment_names(
        {},
        source="equipment",
        organization={
            "equipment": {
                "IF18115": {"team": "설비팀"},
                "IF20000": {"factory": "설비 지정 공장"},
            }
        },
    )
    result = analyze(store, organization_file)
    records = result.all_records.set_index("source_row")
    assert records.loc[4, "factory"] == "공장A"
    assert records.loc[4, "team"] == "설비팀"
    assert records.loc[6, "factory"] == "설비 지정 공장"
    assert records.loc[6, "team"] == K["missing"]


def test_runtime_line_name_only_assignment_uses_raw_name_as_identity(store, organization_file):
    config = store.load()
    config["equipment_names"]["organization"] = {
        "line": {"[공장A] 원본 라인1": {"factory": "이름 기준 공장", "team": "이름 기준 팀"}}
    }
    loaded = load_excel(organization_file, config["column_mapping"])
    loaded.mapping["line_id"] = None
    result = run_analysis(loaded, config, AnalysisOptions())
    assert result.all_records.iloc[0].factory == "이름 기준 공장"
    assert result.all_records.iloc[0].team == "이름 기준 팀"
