"""Consistent display values and bounded report settings."""

from __future__ import annotations

import pandas as pd


def number(value, decimals: int = 0) -> str:
    return "-" if value is None or pd.isna(value) else f"{float(value):,.{decimals}f}"


def percent(value) -> str:
    return "-" if value is None or pd.isna(value) else f"{float(value):.1%}"


def bounded_int(value, default: int, maximum: int = 20) -> int:
    try:
        return max(1, min(maximum, int(value)))
    except (ValueError, TypeError):
        return default
