"""Shared record aggregation and complete time-period series."""

from __future__ import annotations

import pandas as pd

from core.sorting import descending

STAT_COLUMNS = [
    "count",
    "count_share",
    "valid_count",
    "total_minutes",
    "mean_minutes",
    "max_minutes",
    "time_share",
    "top_type",
    "top_equipment",
]


def mode_text(series: pd.Series) -> str:
    counts = series.value_counts(dropna=False)
    return str(counts.index[0]) if len(counts) else ""


def grouped(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    columns = keys + STAT_COLUMNS
    if df.empty:
        return pd.DataFrame(columns=columns)
    groups = df.groupby(keys, dropna=False, sort=True, observed=True)
    agg = groups.agg(
        count=("record_id", "size"),
        valid_count=("minutes", "count"),
        total_minutes=("minutes", lambda s: s.sum(min_count=1)),
        mean_minutes=("minutes", "mean"),
        max_minutes=("minutes", "max"),
        top_type=("type", mode_text),
        top_equipment=("equipment", mode_text),
    ).reset_index()
    agg["count_share"] = agg["count"] / len(df)
    denominator = df["minutes"].sum(min_count=1)
    agg["time_share"] = (
        agg["total_minutes"] / denominator
        if pd.notna(denominator) and denominator > 0
        else float("nan")
    )
    return descending(agg[columns], "total_minutes")


def trend(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    valid = df.loc[df["date"].notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=["period", *STAT_COLUMNS])
    if freq == "day":
        valid["period"] = valid["date"].dt.strftime("%Y-%m-%d")
        periods = pd.date_range(valid["date"].min(), valid["date"].max(), freq="D").strftime(
            "%Y-%m-%d"
        )
    elif freq == "week":
        starts = valid["date"].dt.to_period("W-SUN").dt.start_time
        valid["period"] = starts.dt.strftime("%Y-%m-%d")
        periods = pd.date_range(starts.min(), starts.max(), freq="W-MON").strftime("%Y-%m-%d")
    elif freq == "year":
        valid["period"] = valid["date"].dt.strftime("%Y")
        periods = [str(y) for y in range(valid["date"].min().year, valid["date"].max().year + 1)]
    else:
        valid["period"] = valid["date"].dt.strftime("%Y-%m")
        periods = pd.period_range(valid["date"].min(), valid["date"].max(), freq="M").astype(str)
    table = grouped(valid, ["period"]).set_index("period").reindex(periods)
    for col in ("count", "valid_count"):
        table[col] = table[col].fillna(0).astype(int)
    empty = table["count"].eq(0)
    table.loc[empty, ["total_minutes", "count_share", "time_share"]] = 0
    table.loc[empty, ["top_type", "top_equipment"]] = ""
    table.index.name = "period"
    return descending(table.reset_index(), "total_minutes")
