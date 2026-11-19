"""Calendar-day summaries over retained fault facts."""

from __future__ import annotations

import calendar
import re
from datetime import date

import pandas as pd

DAY_COLUMNS = [
    "period",
    "count",
    "total_minutes",
    "mean_minutes",
    "valid_count",
    "review_count",
]


def _summarize(facts, dates, labels, periods):
    source = pd.DataFrame(
        {
            "period": labels,
            "minutes": pd.to_numeric(facts["minutes"], errors="coerce"),
            "review_count": pd.to_numeric(
                facts.get("review_count", pd.Series(0, index=facts.index)), errors="coerce"
            ).fillna(0),
        }
    ).loc[dates.notna()]
    groups = source.groupby("period", sort=True)
    table = groups.agg(
        count=("minutes", "size"),
        valid_count=("minutes", "count"),
        mean_minutes=("minutes", "mean"),
        review_count=("review_count", "sum"),
    )
    table["total_minutes"] = groups["minutes"].sum(min_count=1)
    table = table.reindex(periods)
    for column in ("count", "valid_count", "review_count"):
        table[column] = table[column].fillna(0).astype(int)
    table.loc[table["count"].eq(0), "total_minutes"] = 0.0
    table.index.name = "period"
    return table.reset_index()[DAY_COLUMNS]


def case_days(facts: pd.DataFrame, month: str | None = None) -> pd.DataFrame:
    """Keep empty days at zero and nonempty days with unavailable time at NaN.

    An explicit YYYY-MM includes the entire calendar month. Without a month,
    include every day from the first through the last dated record. Undated
    records do not enter either the calendar or its totals.
    """
    if month is not None:
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("month must be a valid YYYY-MM calendar month")
        try:
            start = date.fromisoformat(month + "-01")
        except ValueError as exc:
            raise ValueError("month must be a valid YYYY-MM calendar month") from exc
        periods = [
            f"{month}-{day:02d}"
            for day in range(1, calendar.monthrange(start.year, start.month)[1] + 1)
        ]
    dates = pd.to_datetime(facts["date"], errors="coerce", format="mixed")
    if month is None:
        dated = dates.dropna()
        periods = (
            []
            if dated.empty
            else pd.date_range(dated.min().normalize(), dated.max().normalize(), freq="D")
            .strftime("%Y-%m-%d")
            .tolist()
        )
    return _summarize(facts, dates, dates.dt.strftime("%Y-%m-%d"), periods)
