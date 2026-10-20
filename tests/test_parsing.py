"""Boundary cases for shared source-value parsing."""

from datetime import time

import numpy as np
import pandas as pd
import pytest

from core.equipment_names import code_key, equipment_catalog, resolve_name
from core.models import LoadedData
from core.parsing import is_missing, parse_date, parse_duration, parse_stamp, text


@pytest.mark.parametrize("value", [None, pd.NA, pd.NaT, float("nan"), " NULL ", " NaN "])
def test_missing_values_share_one_text_and_equipment_policy(value):
    assert is_missing(value)
    assert text(value) == ""
    assert code_key(value) == ""
    assert resolve_name(value, "Name only", {}) == ("Name only", False)


def test_missing_catalog_codes_fall_back_to_source_name(tmp_path):
    frame = pd.DataFrame({"code": [pd.NA, "EQ1"], "name": ["Pump", pd.NA]})
    loaded = LoadedData(
        tmp_path / "source.xlsx",
        "Sheet",
        1,
        frame,
        ["code", "name"],
        {"equipment_id": "code", "equipment_name": "name"},
        "generic",
        "hash",
    )
    assert equipment_catalog(loaded) == [
        {"code": "EQ1", "raw_name": ""},
        {"code": "PUMP", "raw_name": "Pump"},
    ]


def test_zero_is_a_real_source_value():
    assert not is_missing(0)
    assert text(0) == "0"
    assert code_key(0) == "0"
    assert parse_duration(0) == 0


@pytest.mark.parametrize("value", [float("inf"), -float("inf"), float("nan"), np.float64("inf")])
def test_nonfinite_source_values_cannot_become_dates_or_durations(value):
    assert pd.isna(parse_date(value))
    assert parse_duration(value) is None


def test_timezone_dates_preserve_the_reported_calendar_day():
    assert parse_date("2026-10-15T00:30:00+09:00") == pd.Timestamp("2026-10-15 00:30:00")


def test_clock_time_requires_a_day_and_does_not_wrap_invalid_values():
    day = pd.Timestamp("2026-10-15")
    assert parse_stamp(time(23, 59, 30), day) == pd.Timestamp("2026-10-15 23:59:30")
    assert pd.isna(parse_stamp("08:10", pd.NaT))
    assert pd.isna(parse_stamp("24:00", day))
    assert parse_duration("25:00") == 1500  # Durations can exceed a calendar day.


def test_preprocessing_keeps_its_public_parsing_api():
    from core import parsing, preprocessing

    for name in (
        "is_missing",
        "text",
        "normalize",
        "expand_endings",
        "prepare_text",
        "parse_date",
        "is_time_only",
        "parse_stamp",
        "parse_duration",
    ):
        assert getattr(preprocessing, name) is getattr(parsing, name)
