"""Rollback integration: preserved user settings and manual corrections."""

import json

from conftest import analyze_file

from core.config import ConfigStore
from core.i18n import K
from core.models import CLASSIFICATION_DECISION_COLUMNS


def test_legacy_thresholds_are_ignored_without_rewriting_user_file(store, input_file):
    path = store.config_dir / "settings.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["classifier"]["scoring"] = {"min_score": 100, "min_margin": 100}
    path.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    config = store.load()
    assert "scoring" not in config["settings"]["classifier"]
    first = analyze_file(store, input_file)
    assert path.read_bytes() == before
    settings["classifier"]["scoring"] = {"min_score": 0, "min_margin": 0}
    path.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    second = analyze_file(store, input_file)
    assert first.selected.equals(second.selected)
    assert not any("score" in key for key in first.selected.columns)
    assert set(CLASSIFICATION_DECISION_COLUMNS) <= set(first.selected.columns)


def test_manual_confirmation_keeps_precedence_and_time_edit_does_not_confirm(store, input_file):
    original = analyze_file(store, input_file).selected.iloc[0]
    store.update_override(original.event_id, {"minutes": "25"})
    timed = analyze_file(store, input_file).selected.iloc[0]
    assert timed.status == original.status
    assert timed.candidate_evidence == original.candidate_evidence
    store.update_override(original.event_id, {"major": "A", "middle": "B", "minor": "C"})
    confirmed = analyze_file(ConfigStore(store.root), input_file).selected.iloc[0]
    assert confirmed.status == K["manual"] and confirmed.candidate_evidence == ""
    assert "사용자확정" in confirmed.classification_reason
    assert not any("score" in key for key in confirmed.index)
