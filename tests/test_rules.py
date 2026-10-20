"""Rule persistence failures must preserve the last usable workbook."""

import pytest

from core.models import UserError
from core.rules import read_rules, validate_rules, write_rules


def sample_rule():
    return dict(
        id="PUMP",
        enabled=True,
        priority=10,
        major="Mechanical",
        middle="Pump",
        minor="Pump failure",
        context="pump",
        symptom="failed",
        exclude="",
        role="component",
    )


def test_invalid_rules_do_not_replace_the_current_workbook(tmp_path):
    path = tmp_path / "rules.xlsx"
    rules = [sample_rule()]
    write_rules(path, rules)
    before = path.read_bytes()
    with pytest.raises(UserError):
        write_rules(path, [{**rules[0], "context": "["}])
    assert path.read_bytes() == before
    assert read_rules(path) == validate_rules(rules)
    assert not path.with_suffix(".xlsx.bak").exists()


def test_replacing_rules_preserves_the_previous_workbook_as_backup(tmp_path):
    path = tmp_path / "rules.xlsx"
    original = [sample_rule()]
    revised = [{**original[0], "minor": "Pump replaced", "symptom": "replaced"}]
    write_rules(path, original)
    original_bytes = path.read_bytes()
    write_rules(path, revised)
    assert read_rules(path) == validate_rules(revised)
    assert path.with_suffix(".xlsx.bak").read_bytes() == original_bytes


def test_classifier_keeps_its_public_rule_storage_api():
    from core import classifier, rules

    for name in (
        "RULE_COLUMNS",
        "REQUIRED_COLUMNS",
        "RULES_SCHEMA",
        "RULES_SHEET",
        "LEGACY_GUARD",
        "read_rules",
        "write_rules",
        "validate_rules",
        "needs_format_upgrade",
        "upgrade_rules_format",
    ):
        assert getattr(classifier, name) is getattr(rules, name)


def test_interrupted_rule_replacement_keeps_last_good_file_and_cleans_temp(monkeypatch, tmp_path):
    from core import rules

    path = tmp_path / "rules.xlsx"
    original = [sample_rule()]
    write_rules(path, original)
    original_bytes = path.read_bytes()

    def interrupted(source, destination):
        raise OSError("Simulated file replacement failure")

    monkeypatch.setattr(rules.os, "replace", interrupted)
    with pytest.raises(OSError, match="Simulated"):
        write_rules(path, [{**original[0], "priority": 20}])
    assert path.read_bytes() == original_bytes
    assert set(item.name for item in tmp_path.iterdir()) == {"rules.xlsx", "rules.xlsx.bak"}
