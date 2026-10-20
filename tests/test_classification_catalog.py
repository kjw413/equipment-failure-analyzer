"""A correction menu must expose actual enabled hierarchy paths, not rule duplicates."""

from copy import deepcopy

from core.classification_catalog import catalog_categories
from core.rules import read_rules


def test_enabled_complete_paths_are_deduplicated_without_mutating_rules():
    rules = [
        {"major": " 기계 ", "middle": " 벨트 ", "minor": " 마모 ", "enabled": True},
        {"major": "기계", "middle": "벨트", "minor": "마모", "enabled": "yes"},
        {"major": "기계", "middle": "체인", "minor": "절단", "enabled": False},
        {"major": "기계", "middle": "체인", "minor": "절단", "enabled": "false"},
        {"major": "기계", "middle": "", "minor": "누락", "enabled": True},
        {"major": None, "middle": "체인", "minor": "누락", "enabled": True},
    ]
    original = deepcopy(rules)
    assert catalog_categories(rules) == [("기계", "벨트", "마모")]
    assert rules == original


def test_all_rule_roles_are_available_and_parent_child_paths_remain_distinct():
    rules = [
        {"major": "B", "middle": "same", "minor": "part", "role": "component"},
        {"major": "A", "middle": "same", "minor": "generic", "role": "fallback"},
        {"major": "A", "middle": "other", "minor": "cause", "role": "override"},
        {"major": "B", "middle": "same", "minor": "other", "role": "component"},
    ]
    expected = [
        ("A", "other", "cause"),
        ("A", "same", "generic"),
        ("B", "same", "other"),
        ("B", "same", "part"),
    ]
    assert catalog_categories(rules) == expected
    assert catalog_categories(reversed(rules)) == expected


def test_bundled_catalog_covers_every_approved_full_path(approved_catalog_paths):
    from core.config import resource_root

    rules = read_rules(resource_root() / "config" / "classification_config.xlsx")
    paths = catalog_categories(rules)
    assert len(paths) == 237
    assert len({path[0] for path in paths}) == 6
    assert len({path[:2] for path in paths}) == 58
    assert set(paths) == approved_catalog_paths
    assert set(paths) == {
        (row["major"], row["middle"], row["minor"]) for row in rules if row["enabled"]
    }
