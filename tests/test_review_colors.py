"""Stable review categories and user-specific highlight settings."""

import pytest

from core.config import ConfigStore, atomic_json
from core.i18n import K
from core.models import UserError
from core.review_colors import REVIEW_TYPES, normalized_review_colors, review_types


def test_only_four_configurable_review_types_in_priority_order():
    assert REVIEW_TYPES == (
        ("multi_match", "복수검토", "#FFE699"),
        ("unmatched_rule", "규칙 미일치", "#F4CCCC"),
        ("missing_code", "비가동코드 미기입", "#FFF2CC"),
        ("other", "기타", "#E7E6E6"),
    )
    assert tuple(normalized_review_colors()) == (
        "multi_match",
        "unmatched_rule",
        "missing_code",
        "other",
    )


@pytest.mark.parametrize(
    ("status", "issue", "expected"),
    [
        ("review", "multi_rule", "multi_match"),
        ("review", "multiple_faults", "multi_match"),
        ("review", "alternative_types", "multi_match"),
        ("review", "uncertain_fault", "multi_match"),
        ("code_missing", None, "missing_code"),
        ("rule_unmatched", None, "unmatched_rule"),
        ("auto", "date_invalid", "other"),
        ("auto", "time_invalid", "other"),
        ("auto", "time_missing", "other"),
        ("auto", "time_negative", "other"),
        ("auto", "time_diff", "other"),
        ("auto", "target_missing", "other"),
    ],
)
def test_review_reason_maps_to_its_grouped_color_type(status, issue, expected):
    row = {"status": K[status], "issues": K[issue] if issue else ""}
    assert review_types(row) == (expected,)


@pytest.mark.parametrize(
    ("status", "primary"),
    [
        ("review", "multi_match"),
        ("rule_unmatched", "unmatched_rule"),
        ("code_missing", "missing_code"),
    ],
)
def test_multiple_reasons_keep_classification_color_before_other(status, primary):
    row = {
        "status": K[status],
        "issues": " | ".join([K["time_missing"], K["date_invalid"], K["target_missing"]]),
    }
    assert review_types(row) == (primary, "other")
    assert review_types(row, target_review=False) == (primary, "other")


def test_missing_target_is_other_only_for_the_active_equipment_basis():
    row = {"status": K["auto"], "issues": K["target_missing"]}
    assert review_types(row) == ("other",)
    assert review_types(row, target_review=False) == ()


def test_multiple_classification_and_quality_flags_are_consolidated():
    row = {
        "status": K["review"],
        "issues": " | ".join(
            K[key]
            for key in (
                "multi_rule",
                "multiple_faults",
                "alternative_types",
                "uncertain_fault",
                "date_invalid",
                "time_invalid",
                "time_missing",
                "time_negative",
                "time_diff",
            )
        ),
    }
    assert review_types(row) == ("multi_match", "other")


def test_normal_records_and_informational_flags_have_no_review_color():
    assert not review_types({"status": K["auto"], "issues": K["overnight"]})
    assert not review_types({"status": K["manual_multi"], "issues": ""})
    assert review_types({"status": K["review"], "issues": ""}) == ("multi_match",)


def test_save_survives_restart_and_preserves_other_settings(store):
    original = store.read("settings.json")
    store.save_review_colors({"missing_code": "#abcdef"})
    store.save_review_colors({"multi_match": "#112233"})
    reloaded = ConfigStore(store.root).load()["settings"]
    assert reloaded["review_colors"]["missing_code"] == "#ABCDEF"
    assert reloaded["review_colors"]["multi_match"] == "#112233"
    assert {k: v for k, v in reloaded.items() if k != "review_colors"} == {
        k: v for k, v in original.items() if k != "review_colors"
    }


def test_upgrade_fills_four_types_without_overwriting_custom_colors(store):
    path = store.config_dir / "settings.json"
    settings = store.read("settings.json")
    settings["review_colors"] = {"missing_code": "#123456"}
    atomic_json(path, settings)
    (store.config_dir / ".defaults_state.json").unlink()
    colors = ConfigStore(store.root).load()["settings"]["review_colors"]
    assert colors["missing_code"] == "#123456"
    assert len(colors) == len(REVIEW_TYPES)


def test_legacy_extra_colors_are_ignored_without_losing_remaining_choices(store):
    path = store.config_dir / "settings.json"
    settings = store.read("settings.json")
    retained = {
        "multi_match": "#123456",
        "unmatched_rule": "#234567",
        "missing_code": "#345678",
        "other": "#456789",
    }
    settings["review_colors"] = dict(
        retained,
        multiple_faults="#556677",
        alternative_types="#667788",
        uncertain_fault="#778899",
        invalid_date="#8899AA",
        time_missing="#99AABB",
        missing_target="#AABBCC",
    )
    atomic_json(path, settings)
    reopened = ConfigStore(store.root)
    assert reopened.load()["settings"]["review_colors"] == retained
    reopened.save_review_colors({"missing_code": "#abcdef"})
    expected = dict(retained, missing_code="#ABCDEF")
    assert reopened.read("settings.json")["review_colors"] == expected
    assert ConfigStore(store.root).load()["settings"]["review_colors"] == expected


@pytest.mark.parametrize("value", [{"missing_code": "red"}, {"bad_key": "#123456"}, []])
def test_invalid_color_save_keeps_previous_settings(store, value):
    path = store.config_dir / "settings.json"
    before = path.read_bytes()
    with pytest.raises(UserError):
        store.save_review_colors(value)
    assert path.read_bytes() == before


def test_older_or_malformed_color_settings_fall_back_to_defaults():
    defaults = normalized_review_colors()
    assert normalized_review_colors(None) == defaults
    assert normalized_review_colors([]) == defaults
    assert normalized_review_colors({"multi_match": "invalid"}) == defaults
