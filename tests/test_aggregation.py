"""Aggregation preserves missing durations and fills unrecorded periods."""

import pandas as pd
import pytest

from core.aggregation import grouped, trend


def records():
    return pd.DataFrame(
        {
            "record_id": ["1", "2", "3"],
            "type": ["A", "A", "B"],
            "equipment": ["Pump", "Pump", "Fan"],
            "minutes": [10.0, None, None],
            "date": pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-02"]),
        }
    )


def test_missing_duration_is_counted_without_becoming_zero():
    table = grouped(records(), ["equipment"]).set_index("equipment")
    assert table.loc["Pump", "count"] == 2
    assert table.loc["Pump", "valid_count"] == 1
    assert table.loc["Pump", "count_share"] == pytest.approx(2 / 3)
    assert table.loc["Pump", "time_share"] == 1
    assert table.loc["Fan", "count"] == 1
    assert pd.isna(table.loc["Fan", "total_minutes"])
    assert pd.isna(table.loc["Fan", "time_share"])


def test_day_trend_fills_gaps_and_preserves_unknown_recorded_duration():
    table = trend(records(), "day").set_index("period")
    assert set(table.index) == {"2025-12-31", "2026-01-01", "2026-01-02"}
    gap = table.loc["2026-01-01"]
    assert gap["count"] == gap["valid_count"] == gap["total_minutes"] == 0
    assert gap["top_type"] == gap["top_equipment"] == ""
    assert table.loc["2026-01-02", "count"] == 2
    assert pd.isna(table.loc["2026-01-02", "total_minutes"])


def test_analyzer_keeps_its_public_aggregation_api():
    from core import aggregation, analyzer

    for name in ("STAT_COLUMNS", "mode_text", "grouped", "trend"):
        assert getattr(analyzer, name) is getattr(aggregation, name)
