"""Per-equipment type ranking; each equipment supplies its own denominator."""

from __future__ import annotations

import pandas as pd

from core.aggregation import grouped
from core.sorting import descending


def type_breakdown(records: pd.DataFrame, equipment: str) -> pd.DataFrame:
    selected = records.loc[records["equipment"].eq(equipment)]
    table = grouped(selected, ["type"])
    if table.empty:
        table["rank"] = pd.Series(dtype="int64")
        return table
    table = descending(table.sort_values("type", kind="stable"), "count")
    # Rows are ordered by count, then time, then type for deterministic ties.
    table.insert(0, "rank", range(1, len(table) + 1))
    return table


def donut_slices(table: pd.DataFrame, metric: str = "count", top_n: int = 5) -> pd.DataFrame:
    """Retain all mass: top N positive types + the entire remainder (never drop it)."""
    if table.empty or metric not in table:
        return pd.DataFrame(columns=["type", "value", "share"])
    data = table[["type", metric]].rename(columns={metric: "value"}).copy()
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data = data.loc[data["value"].gt(0)]
    data = descending(data, "value")
    if data.empty:
        return pd.DataFrame(columns=["type", "value", "share"])
    limit = max(1, min(10, int(top_n)))
    if len(data) > limit:
        rest = data.iloc[limit:]
        data = pd.concat(
            [
                data.iloc[:limit],
                pd.DataFrame(
                    [
                        {
                            "type": f"\uae30\ud0c0 (\ub098\uba38\uc9c0 {len(rest)}\uac1c \uc720\ud615)",
                            "value": float(rest["value"].sum()),
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    data["share"] = data["value"] / data["value"].sum()
    return data
