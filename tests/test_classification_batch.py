"""Validate session selections together and save the confirmed file only once."""

from unittest.mock import Mock

import pytest

import core.config as config_module
from core.models import UserError

CATEGORIES = [
    {
        "major": "기계",
        "detail_equipment": "컨베어",
        "middle": "베어링(종류 미상)",
        "minor": "손상·파손",
    },
    {"major": "유체·배관", "detail_equipment": "세척기", "middle": "오링", "minor": "누설"},
]


def test_batch_writes_once_and_preserves_the_latest_other_corrections(store, monkeypatch):
    store.update_override("one", {"minutes": "19", "product": "Keep"})
    write = Mock(wraps=config_module.atomic_json)
    monkeypatch.setattr(config_module, "atomic_json", write)
    assert store.apply_classifications(dict(zip(("one", "two"), CATEGORIES))) == 2
    write.assert_called_once()
    assert write.call_args.args[0] == store.override_path
    assert store.override("one")["minutes"] == "19"
    assert store.override("one")["product"] == "Keep"
    assert store.override("two")["minor"] == "누설"


def test_invalid_member_prevents_every_write_in_a_batch(store, monkeypatch):
    before = store.override_path.read_bytes()
    write = Mock()
    monkeypatch.setattr(config_module, "atomic_json", write)
    with pytest.raises(UserError):
        store.apply_classifications(
            {"valid": CATEGORIES[0], "invalid": {**CATEGORIES[1], "minor": ""}}
        )
    write.assert_not_called()
    assert store.override_path.read_bytes() == before


def test_failed_save_keeps_confirmed_values_and_does_not_mutate_the_batch(store, monkeypatch):
    before = store.override_path.read_bytes()
    batch = {"one": dict(CATEGORIES[0])}
    monkeypatch.setattr(
        config_module, "atomic_json", Mock(side_effect=PermissionError("file locked"))
    )
    with pytest.raises(PermissionError, match="file locked"):
        store.apply_classifications(batch)
    assert store.override_path.read_bytes() == before
    assert batch == {"one": CATEGORIES[0]}


def test_classification_clear_preserves_other_corrections(store):
    store.update_override("one", {**CATEGORIES[0], "minutes": "12"})
    assert store.apply_classifications({"one": dict.fromkeys(CATEGORIES[0])}) == 1
    assert store.override("one").keys() == {"minutes", "saved_at"}


def test_empty_batch_does_not_read_or_write_profile(store, monkeypatch):
    read = Mock(side_effect=AssertionError("unexpected I/O"))
    monkeypatch.setattr(store, "read", read)
    assert store.apply_classifications({}) == 0
    read.assert_not_called()
