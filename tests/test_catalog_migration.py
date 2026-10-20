"""Install the requested list in existing profiles without losing user evidence."""

import copy
import json
import shutil
from pathlib import Path

import pytest

from core.classification_catalog import catalog_categories, catalog_signature, validate_catalog
from core.config import ConfigStore, resource_root
from core.defaults_merge import DefaultsMerger
from core.models import UserError
from core.rules import read_rules, write_rules

BUNDLE = resource_root() / "config"
OLD_RULES = Path(__file__).parent / "fixtures/v172_config/classification_config.xlsx"


def old_profile(tmp_path, rules=None):
    root = tmp_path / "profile"
    directory = root / "config"
    directory.mkdir(parents=True)
    shutil.copy2(OLD_RULES, directory / "classification_config.xlsx")
    if rules is not None:
        write_rules(directory / "classification_config.xlsx", rules)
    return root, directory


def paths():
    catalog = json.loads((BUNDLE / "classification_catalog.json").read_text(encoding="utf-8"))
    return catalog_categories(catalog["categories"])


def test_existing_profile_gets_every_new_choice_and_keeps_manual_corrections(tmp_path):
    root, directory = old_profile(tmp_path)
    manual = {"old_record": {"major": "유체·배관", "middle": "펌프", "minor": "펌프 이상"}}
    original_manual = json.dumps(manual, ensure_ascii=False).encode("utf-8")
    (directory / "manual_overrides.json").write_bytes(original_manual)
    store = ConfigStore(root)
    config = store.load()
    assert len(paths()) == 237
    assert catalog_categories(config["rules"]) == paths()
    assert not any(rule["id"] == "PUMP" for rule in config["rules"])
    assert (directory / "manual_overrides.json").read_bytes() == original_manual
    assert config["overrides"] == manual
    backups = list((directory / "backup").glob("*/classification_config.xlsx"))
    assert len(backups) == 1 and backups[0].read_bytes() == OLD_RULES.read_bytes()


def test_custom_rules_are_preserved_but_old_category_paths_do_not_pollute_choices(tmp_path):
    rules = read_rules(OLD_RULES)
    rules = [rule for rule in rules if rule["id"] != "TANK"]
    custom = {
        **rules[0],
        "id": "CUSTOM_OLD",
        "priority": 999,
        "context": "USER_LEGACY_PART",
        "minor": "사용자 예전 분류",
    }
    major, middle, minor = paths()[0]
    valid = {
        **rules[0],
        "id": "CUSTOM_VALID",
        "priority": 998,
        "major": major,
        "middle": middle,
        "minor": minor,
        "context": "USER_VALID_PART",
    }
    root, _ = old_profile(tmp_path, [*rules, custom, valid])
    store = ConfigStore(root)
    migrated = {rule["id"]: rule for rule in store.load()["rules"]}
    assert migrated["CUSTOM_OLD"] == {**custom, "enabled": False}
    assert migrated["CUSTOM_VALID"] == valid
    assert "TANK" not in migrated
    assert catalog_categories(migrated.values()) == paths()
    assert store.merge_summary["rules"]["disabled"] == 1


def test_migration_is_idempotent_and_later_user_disabled_or_deleted_new_rules_stay_so(tmp_path):
    root, directory = old_profile(tmp_path)
    first = ConfigStore(root)
    tracked = [
        directory / name
        for name in (
            "classification_config.xlsx",
            "classification_catalog.json",
            ".defaults_state.json",
            "manual_overrides.json",
        )
    ]
    unchanged = {path: path.read_bytes() for path in tracked}
    assert ConfigStore(root).merge_summary == {}
    assert all(path.read_bytes() == value for path, value in unchanged.items())
    rules = first.load()["rules"]
    deleted_id, disabled_id = rules[0]["id"], rules[1]["id"]
    edited = [
        {**rule, "enabled": False} if rule["id"] == disabled_id else rule
        for rule in rules
        if rule["id"] != deleted_id
    ]
    write_rules(directory / "classification_config.xlsx", edited)
    latest = {rule["id"]: rule for rule in ConfigStore(root).load()["rules"]}
    assert deleted_id not in latest and latest[disabled_id]["enabled"] is False


def test_failed_rule_migration_never_marks_old_list_current_and_can_retry(tmp_path, monkeypatch):
    root, directory = old_profile(tmp_path)
    original = (directory / "classification_config.xlsx").read_bytes()
    import core.rules

    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            raise OSError("simulated rule write failure")

        patch.setattr(core.rules, "write_rules", fail)
        failed = ConfigStore(root)
        with pytest.raises(UserError, match="simulated rule write failure"):
            failed.load()
        assert not (directory / ".defaults_state.json").exists()
        assert (directory / "classification_config.xlsx").read_bytes() == original
    assert catalog_categories(ConfigStore(root).load()["rules"]) == paths()


def test_catalogue_rejects_duplicate_paths_and_multiple_major_owners():
    data = json.loads((BUNDLE / "classification_catalog.json").read_text(encoding="utf-8"))
    duplicate = copy.deepcopy(data)
    duplicate["categories"].append(copy.deepcopy(duplicate["categories"][0]))
    with pytest.raises(UserError, match="중복"):
        validate_catalog(duplicate)
    other_owner = copy.deepcopy(data)
    other_owner["categories"][0]["major"] = "다른 대분류"
    with pytest.raises(UserError, match="대분류가 둘 이상"):
        validate_catalog(other_owner)
    elsewhere = {**data, "source": {"path": "another copy.xlsx"}}
    assert catalog_signature(data) == catalog_signature(elsewhere)


def test_invalid_catalogue_cannot_commit_migration_state(tmp_path):
    root, directory = old_profile(tmp_path)
    bundle = tmp_path / "bundle"
    shutil.copytree(BUNDLE, bundle)
    (bundle / "classification_catalog.json").write_text('{"schema_version":99}', encoding="utf-8")
    with pytest.raises(UserError, match="unsupported schema"):
        DefaultsMerger(bundle, directory).run()
    assert not (directory / ".defaults_state.json").exists()


def test_pre_18_reader_refuses_new_catalogue_rules_before_interpreting_them(monkeypatch):
    import core.rules

    with monkeypatch.context() as patch:
        patch.setattr(core.rules, "RULES_SCHEMA", 2)
        patch.setattr(core.rules, "VERSION", "1.7.2")
        with pytest.raises(UserError, match="v1.8.0 이상"):
            core.rules.read_rules(BUNDLE / "classification_config.xlsx")


def test_older_defaults_cache_cannot_reset_new_rule_deletions(tmp_path):
    root, directory = old_profile(tmp_path)
    store = ConfigStore(root)
    rules = store.load()["rules"]
    deleted = rules[0]["id"]
    write_rules(directory / "classification_config.xlsx", rules[1:])
    # Old programs know neither this catalogue marker nor its rule IDs.
    (directory / ".defaults_state.json").write_text(
        '{"bundle":"older executable cache","rules":{}}', encoding="utf-8"
    )
    latest = ConfigStore(root).load()["rules"]
    assert deleted not in {row["id"] for row in latest}


@pytest.mark.parametrize("older_cache", [False, True])
def test_same_catalogue_revision_preserves_deletions_and_merges_new_defaults(tmp_path, older_cache):
    root, directory = old_profile(tmp_path)
    rules = ConfigStore(root).load()["rules"]
    deleted_id, updated_id = rules[0]["id"], rules[1]["id"]
    write_rules(directory / "classification_config.xlsx", rules[1:])
    if older_cache:
        (directory / ".defaults_state.json").write_text(
            '{"bundle":"older executable cache","rules":{}}', encoding="utf-8"
        )
    bundle = tmp_path / "revised_bundle"
    shutil.copytree(BUNDLE, bundle)
    catalog_path = bundle / "classification_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["categories"][0]["definition"] += " (설명 보완)"
    additional = {
        **catalog["categories"][0],
        "code": "TEST-ADDED",
        "minor": "새로 추가한 부품",
    }
    catalog["categories"].append(additional)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    revised = [
        {**rule, "context": rule["context"] + "|NEW_ALIAS"} if rule["id"] == updated_id else rule
        for rule in read_rules(bundle / "classification_config.xlsx")
    ]
    revised.append({**revised[0], "id": "CAT_TEST_ADDED", "minor": additional["minor"]})
    write_rules(bundle / "classification_config.xlsx", revised)
    DefaultsMerger(bundle, directory).run()
    actual = {rule["id"]: rule for rule in read_rules(directory / "classification_config.xlsx")}
    expected = {rule["id"]: rule for rule in revised}
    assert deleted_id not in actual
    assert actual[updated_id] == expected[updated_id]
    assert actual["CAT_TEST_ADDED"] == expected["CAT_TEST_ADDED"]
    assert DefaultsMerger(bundle, directory).run() == {}
