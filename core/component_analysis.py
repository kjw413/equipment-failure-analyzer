"""One final classification per fault record, with candidates kept out of counts."""

from __future__ import annotations

import pandas as pd

from core.failure_modes import CLASSIFICATION_SCHEMA, UNKNOWN_PART
from core.fault_components import CATEGORY_FIELDS, parse_components, type_label
from core.i18n import UNMATCHED, K
from core.public_taxonomy import part_group

COMPONENT_STATS = ["component_type", "count", "manual_count", "review_count", "count_share"]
FAULT_DETAIL_COLUMNS = [
    "record_id",
    "event_id",
    "date",
    "equipment",
    "line",
    "description",
    "major",
    "detail_equipment",
    "middle",
    "part_group",
    "minor",
    "status",
    "evidence",
    "actions",
    "repair_actions",
    "classification_missing_fields",
    "detail_equipment_source",
]


def final_component(record: dict) -> dict | None:
    """A pending or older multi selection never becomes an arbitrary first part."""
    if record.get("status") in (K["review"], *UNMATCHED, K["manual_multi"]):
        return None
    if record.get("classification_mode") in ("ambiguous", "multiple", "unclassified", "nonfault"):
        return None
    members = parse_components(record.get("component_details"))
    return members[0] if len(members) == 1 else None


def component_tables(records: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Count final parts once; retain every selected fault in the detail table.

    The share denominator includes every selected fault, including pending and
    unmatched records. Candidates contribute no part counts or downtime.
    """
    empty = pd.DataFrame(columns=COMPONENT_STATS)
    empty_trend = pd.DataFrame(columns=["period", *COMPONENT_STATS])
    empty_detail = pd.DataFrame(columns=FAULT_DETAIL_COLUMNS)
    if records.empty:
        return {"component": empty, "component_trend": empty_trend, "fault_detail": empty_detail}
    faults = records.loc[records["kind"].eq(K["fault"])].copy()
    rows = []
    details = []
    for record in faults.to_dict("records"):
        date = record.get("date")
        period = pd.Timestamp(date).strftime("%Y-%m") if pd.notna(date) else None
        manual = record.get("status") == K["manual"]
        member = final_component(record)
        if member is not None and member.get("middle") not in (
            UNKNOWN_PART,
            "제품·자재",
            "제품 걸림·막힘",
            "제품 낙하",
            "자재 불량",
        ):
            component_type = (
                " / ".join(member.get(key, "") for key in CATEGORY_FIELDS[:-1])
                if member.get("schema") == CLASSIFICATION_SCHEMA
                else type_label(member)
            )
            rows.append(
                {
                    "record_id": record["record_id"],
                    "period": period,
                    "component_type": component_type,
                    "manual_count": int(manual),
                    "review_count": 0,
                }
            )
        category = member or {key: "" for key in CATEGORY_FIELDS}
        details.append(
            {
                "record_id": record["record_id"],
                "event_id": record.get("event_id", ""),
                "date": date,
                "equipment": record.get("equipment", ""),
                "line": record.get("line", ""),
                "description": record.get("raw_description", ""),
                **{key: category.get(key, "") for key in CATEGORY_FIELDS},
                "status": record.get("status", ""),
                "evidence": (member.get("symptom_evidence") or member.get("evidence", ""))
                if member
                else record.get("candidate_evidence") or record.get("classification_reason", ""),
                "actions": ", ".join(member.get("actions", [])) if member else "",
                "repair_actions": record.get(
                    "repair_actions", ", ".join(member.get("actions", [])) if member else ""
                ),
                "part_group": part_group(category.get("middle", "")),
                "classification_missing_fields": record.get("classification_missing_fields", ""),
                "detail_equipment_source": record.get("detail_equipment_source", ""),
            }
        )
    detail_table = pd.DataFrame(details, columns=FAULT_DETAIL_COLUMNS).reset_index(drop=True)
    if not rows:
        return {"component": empty, "component_trend": empty_trend, "fault_detail": detail_table}
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
    return {
        "component": totals[COMPONENT_STATS].reset_index(drop=True),
        "component_trend": monthly,
        "fault_detail": detail_table,
    }
