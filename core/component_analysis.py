"""Non-additive component inclusion counts alongside additive event summaries."""

from __future__ import annotations

import pandas as pd

from core.failure_modes import CLASSIFICATION_SCHEMA
from core.fault_components import parse_components, type_label
from core.i18n import UNMATCHED, K

COMPONENT_STATS = ["component_type", "count", "manual_count", "review_count", "count_share"]
FAULT_DETAIL_COLUMNS = [
    "record_id",
    "event_id",
    "date",
    "equipment",
    "line",
    "description",
    "major",
    "middle",
    "minor",
    "status",
    "evidence",
    "actions",
]


def component_tables(records: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Count each type once per source record; deliberately do not allocate time.

    The denominator is fault records, including unclassified records. A record
    may contribute to several types, so type counts and shares are non-additive.
    Pending interpretations remain visible in a separate review_count column.
    """
    empty = pd.DataFrame(columns=COMPONENT_STATS)
    empty_trend = pd.DataFrame(columns=["period", *COMPONENT_STATS])
    empty_detail = pd.DataFrame(columns=FAULT_DETAIL_COLUMNS)
    if records.empty or "component_details" not in records:
        return {"component": empty, "component_trend": empty_trend, "fault_detail": empty_detail}
    faults = records.loc[records["kind"].eq(K["fault"])].copy()
    rows = []
    details = []
    for record in faults.to_dict("records"):
        date = record.get("date")
        period = pd.Timestamp(date).strftime("%Y-%m") if pd.notna(date) else None
        manual = record.get("status") in (K["manual"], K["manual_multi"])
        review = record.get("status") in (K["review"], *UNMATCHED)
        for member in parse_components(record.get("component_details")):
            component_type = (
                f"{member['major']} / {member['middle']}"
                if member.get("schema") == CLASSIFICATION_SCHEMA
                else type_label(member)
            )
            rows.append(
                {
                    "record_id": record["record_id"],
                    "period": period,
                    "component_type": component_type,
                    "manual_count": int(manual),
                    "review_count": int(review),
                }
            )
            details.append(
                {
                    "record_id": record["record_id"],
                    "event_id": record.get("event_id", ""),
                    "date": date,
                    "equipment": record.get("equipment", ""),
                    "line": record.get("line", ""),
                    "description": record.get("raw_description", ""),
                    **{key: member[key] for key in ("major", "middle", "minor")},
                    "status": record.get("status", ""),
                    "evidence": member.get("symptom_evidence") or member.get("evidence", ""),
                    "actions": ", ".join(member.get("actions", [])),
                }
            )
    if not rows:
        return {"component": empty, "component_trend": empty_trend, "fault_detail": empty_detail}
    included = pd.DataFrame(rows).drop_duplicates(["record_id", "component_type"])

    def summarize(frame, keys, denominator):
        table = (
            frame.groupby(keys, observed=True, sort=True)
            .agg(
                count=("record_id", "size"),
                manual_count=("manual_count", "sum"),
                review_count=("review_count", "sum"),
            )
            .reset_index()
        )
        table["count_share"] = table["count"] / denominator
        return table

    totals = summarize(included, ["component_type"], len(faults))
    totals = totals.sort_values(["count", "component_type"], ascending=[False, True], kind="stable")
    valid = included.loc[included["period"].notna()]
    monthly = empty_trend
    dates = pd.to_datetime(faults["date"], errors="coerce").dropna()
    if not valid.empty and not dates.empty:
        monthly = summarize(valid, ["period", "component_type"], 1)
        periods = pd.period_range(dates.min(), dates.max(), freq="M").astype(str)
        index = pd.MultiIndex.from_product(
            [periods, sorted(totals["component_type"])], names=["period", "component_type"]
        )
        monthly = monthly.set_index(["period", "component_type"]).reindex(index).reset_index()
        for key in ("count", "manual_count", "review_count"):
            monthly[key] = monthly[key].fillna(0).astype(int)
        month_denominators = dates.dt.strftime("%Y-%m").value_counts()
        denominators = monthly["period"].map(month_denominators).fillna(0)
        monthly["count_share"] = monthly["count"].div(denominators.where(denominators.gt(0)))
        monthly = monthly[["period", *COMPONENT_STATS]]
    detail_table = (
        pd.DataFrame(details, columns=FAULT_DETAIL_COLUMNS)
        .drop_duplicates(["record_id", "major", "middle", "minor"])
        .reset_index(drop=True)
    )
    return {
        "component": totals[COMPONENT_STATS].reset_index(drop=True),
        "component_trend": monthly,
        "fault_detail": detail_table,
    }
