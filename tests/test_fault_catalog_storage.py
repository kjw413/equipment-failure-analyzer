"""The new classification axes are explicit; old saved choices are never guessed."""

import json
from pathlib import Path

import pytest

from core.classification_catalog import catalog_signature, validate_catalog
from core.config import ConfigStore, resource_root
from core.defaults_merge import rule_digest
from core.failure_modes import CLASSIFICATION_SCHEMA
from core.models import UserError
from core.rules import MIN_APP_VERSION, RULES_SCHEMA, file_schema, read_rules, write_rules

V110_RULES = Path(__file__).parent / "fixtures/v110_config/classification_config.xlsx"


def test_catalogue_documents_internal_parts_and_output_axes():
    path = resource_root() / "config/classification_catalog.json"
    catalogue = json.loads(path.read_text("utf-8"))
    assert validate_catalog(catalogue) is catalogue
    assert catalogue["output_schema"] == CLASSIFICATION_SCHEMA
    assert catalogue["output_axes"] == {
        "major": "고장 분야",
        "detail_equipment": "상세설비·모듈",
        "part_group": "부품군",
        "middle": "세부 부품",
        "minor": "고장 현상",
        "actions": "조치 내역",
    }
    assert catalogue["part_axes"]["minor"] == "세부 부품 종류"
    assert len(catalogue["categories"]) == 250
    original = catalog_signature(catalogue)
    changed = {**catalogue, "output_axes": {**catalogue["output_axes"], "minor": "증상"}}
    assert catalog_signature(changed) != original
    malformed = {**catalogue, "output_axes": {"major": "분야"}}
    with pytest.raises(UserError, match="출력 축"):
        validate_catalog(malformed)


def test_schema_seven_blocks_a_pre_113_reader(monkeypatch):
    import openpyxl

    import core.rules

    path = resource_root() / "config/classification_config.xlsx"
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        assert file_schema(workbook) == (7, "1.18.0")
    finally:
        workbook.close()
    assert RULES_SCHEMA == 7 and MIN_APP_VERSION == "1.18.0"
    with monkeypatch.context() as patch:
        patch.setattr(core.rules, "RULES_SCHEMA", 6)
        patch.setattr(core.rules, "VERSION", "1.12.2")
        with pytest.raises(UserError, match="v1.18.0"):
            read_rules(path)


def test_new_single_manual_choice_has_schema_and_nonclassification_edits_preserve_it(store):
    category = {
        "major": "기계",
        "detail_equipment": "상세설비 미상",
        "middle": "베어링(종류 미상)",
        "minor": "손상·파손",
    }
    saved = store.update_override("event", {**category, "minutes": "12"})
    assert saved["classification_schema"] == CLASSIFICATION_SCHEMA
    changed = store.update_override("event", {"minutes": "15", "classification_schema": None})
    assert changed["classification_schema"] == CLASSIFICATION_SCHEMA
    assert all(changed[key] == value for key, value in category.items())
    assert changed["minutes"] == "15"


def test_legacy_manual_choices_remain_unmarked_and_unchanged_on_load(store):
    legacy = {"major": "기계", "middle": "베어링·부싱", "minor": "베어링(종류 미상)"}
    store.override_path.write_text(json.dumps({"event": legacy}, ensure_ascii=False), "utf-8")
    before = store.override_path.read_bytes()
    assert store.load()["overrides"] == {"event": legacy}
    assert store.override_path.read_bytes() == before
    saved = store.update_override("event", {"minutes": "10"})
    assert "classification_schema" not in saved
    assert all(saved[key] == value for key, value in legacy.items())
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="모두 입력"):
        store.update_override("event", {"minor": "손상·파손"})
    assert store.override_path.read_bytes() == before
    saved = store.update_override(
        "event",
        {
            "major": "기계",
            "detail_equipment": "상세설비 미상",
            "middle": "베어링(종류 미상)",
            "minor": "손상·파손",
        },
    )
    assert saved["classification_schema"] == CLASSIFICATION_SCHEMA
    assert saved["minutes"] == "10"


def test_clearing_a_classification_removes_its_marker_but_keeps_time(store):
    store.update_override(
        "event",
        {
            "major": "기계",
            "detail_equipment": "상세설비 미상",
            "middle": "베어링(종류 미상)",
            "minor": "손상·파손",
            "minutes": "12",
        },
    )
    saved = store.update_override(
        "event", {"major": None, "detail_equipment": None, "middle": None, "minor": None}
    )
    assert saved == {"minutes": "12"}


def test_multiple_manual_choices_are_rejected_without_replacing_single_choice(store):
    first = {
        "major": "기계",
        "detail_equipment": "상세설비 미상",
        "middle": "베어링(종류 미상)",
        "minor": "손상·파손",
    }
    second = {
        "major": "공압·진공",
        "detail_equipment": "상세설비 미상",
        "middle": "실린더(종류 미상)",
        "minor": "손상·파손",
    }
    store.update_override("event", first)
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="하나만"):
        store.update_override(
            "event", {"classification_components": json.dumps([first, second], ensure_ascii=False)}
        )
    assert store.override_path.read_bytes() == before
    saved = store.override("event")
    assert saved["classification_schema"] == CLASSIFICATION_SCHEMA
    assert all(saved[key] == value for key, value in first.items())
    assert "classification_components" not in saved
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="지원하지 않는"):
        store.update_override("event", {"classification_schema": "future_schema"})
    assert store.override_path.read_bytes() == before


def test_v110_profile_upgrade_preserves_rule_choices_and_legacy_manual_bytes(store):
    import openpyxl

    original_rules = read_rules(V110_RULES)
    old_by_id = {row["id"]: row for row in original_rules}
    current_by_id = {row["id"]: row for row in store.load()["rules"]}
    deleted = "CAT_E_1082948"  # 광전센서: deleted by the user in the real 1.10 library.
    edited = "CAT_E_27F9854"  # 근접센서: custom context and priority must win.
    untouched = "CAT_E_3CF1EBE"  # 농도센서: the untouched old default must update.
    disabled = "CAT_E_9587790"  # 레벨센서: user-disabled remains disabled.
    assert old_by_id[untouched]["symptom"] != current_by_id[untouched]["symptom"]
    revised = [
        {
            **rule,
            "context": rule["context"] + "|USER_SENSOR_ALIAS",
            "priority": rule["priority"] + 7,
        }
        if rule["id"] == edited
        else {**rule, "enabled": False}
        if rule["id"] == disabled
        else rule
        for rule in original_rules
        if rule["id"] != deleted
    ]
    rules_path = store.config_dir / "classification_config.xlsx"
    write_rules(rules_path, revised)
    workbook = openpyxl.load_workbook(rules_path)
    workbook["meta"]["B2"] = 4
    workbook["meta"]["B3"] = "1.10.0"
    workbook["meta"]["B4"] = "1.10.0"
    workbook.save(rules_path)
    workbook.close()
    catalogue = store.read("classification_catalog.json")
    for field in ("output_schema", "output_axes", "part_axes"):
        catalogue.pop(field, None)
    catalogue["catalog_version"] = "1.10.0"
    catalogue["installed_signature"] = catalog_signature(catalogue)
    catalogue["installed_rules"] = {rule["id"]: rule_digest(rule) for rule in original_rules}
    (store.config_dir / "classification_catalog.json").write_text(
        json.dumps(catalogue, ensure_ascii=False), "utf-8"
    )
    (store.config_dir / ".defaults_state.json").write_text(
        json.dumps(
            {"bundle": "v1.10.0", "classification_catalog": {"catalog_id": catalogue["catalog_id"]}}
        ),
        "utf-8",
    )
    legacy = {"old-event": {"major": "기계", "middle": "베어링·부싱", "minor": "베어링(종류 미상)"}}
    store.override_path.write_text(json.dumps(legacy, ensure_ascii=False), "utf-8")
    original_manual = store.override_path.read_bytes()
    upgraded = ConfigStore(store.root)
    rules = {row["id"]: row for row in upgraded.load()["rules"]}
    assert deleted not in rules and not rules[disabled]["enabled"]
    assert rules[edited] == next(rule for rule in revised if rule["id"] == edited)
    assert rules[untouched] == current_by_id[untouched]
    assert upgraded.override_path.read_bytes() == original_manual
    assert upgraded.load()["overrides"] == legacy
    assert upgraded.read("classification_catalog.json")["output_schema"] == CLASSIFICATION_SCHEMA
    workbook = openpyxl.load_workbook(rules_path, read_only=True)
    try:
        assert file_schema(workbook) == (7, "1.18.0")
    finally:
        workbook.close()
    assert ConfigStore(store.root).merge_summary == {}


def test_changed_v110_rule_fingerprints_are_recorded_before_default_patterns_change():
    original = read_rules(V110_RULES)
    current = {
        row["id"]: row for row in read_rules(resource_root() / "config/classification_config.xlsx")
    }
    history = json.loads((resource_root() / "config/defaults_history.json").read_text("utf-8"))
    changed = [row for row in original if rule_digest(row) != rule_digest(current[row["id"]])]
    assert changed
    assert all(rule_digest(row) in history["rules"].get(row["id"], []) for row in changed)
