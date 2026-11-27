"""One retained fault per row, independent of the selected equipment grouping."""

from __future__ import annotations

import pandas as pd

from core.aggregation import grouped
from core.component_analysis import final_component
from core.i18n import UNMATCHED, K
from core.known_classification import known_fields
from core.sorting import descending

ALL = "(전체)"
FACT_COLUMNS = [
    "record_id",
    "date",
    "factory",
    "team",
    "asset",
    "line",
    "module",
    "symptom",
    "domain",
    "case",
    "minutes",
    "review_count",
    "period",
]
MISSING = {"module": "상세설비 미상", "symptom": "현상 미기재"}


def _label(value, fallback):
    return str(value).strip() if pd.notna(value) and str(value).strip() else fallback


def issue_facts(records: pd.DataFrame) -> pd.DataFrame:
    """Pending candidates are excluded; explicitly retained independent axes survive."""
    rows = []
    for record in records.to_dict("records"):
        if record.get("kind") != K["fault"]:
            continue
        category = final_component(record) or known_fields(record)
        axes = {
            axis: _label(category.get(field), MISSING[axis])
            for axis, field in (
                ("module", "detail_equipment"),
                ("symptom", "minor"),
            )
        }
        rows.append(
            {
                "record_id": record["record_id"],
                "date": record.get("date"),
                "factory": _label(record.get("factory"), K["missing"]),
                "team": _label(record.get("team"), K["missing"]),
                "asset": _label(
                    record.get("report_equipment"), _label(record.get("equipment"), K["missing"])
                ),
                "line": _label(record.get("line"), K["missing"]),
                **axes,
                "domain": _label(category.get("major"), "분야 미상"),
                "case": " / ".join(axes[key] for key in ("module", "symptom")),
                "minutes": record.get("minutes"),
                "review_count": int(
                    record.get("status") in (K["review"], *UNMATCHED, K["manual_multi"])
                ),
            }
        )
    facts = pd.DataFrame(rows, columns=FACT_COLUMNS)
    facts["date"] = pd.to_datetime(facts["date"], errors="coerce")
    facts["minutes"] = pd.to_numeric(facts["minutes"], errors="coerce")
    facts["period"] = facts["date"].dt.strftime("%Y-%m")
    return facts


def issue_summary(facts: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Counts include missing duration; all-missing duration remains unavailable."""
    source = facts.assign(type=facts["case"], equipment=facts["asset"])
    table = grouped(source, keys)
    if table.empty:
        table["review_count"] = pd.Series(dtype="int64")
        return table
    reviews = facts.groupby(keys, dropna=False, observed=True)["review_count"].sum().reset_index()
    return table.merge(reviews, on=keys, how="left", validate="one_to_one")


def select_issues(facts: pd.DataFrame, **filters) -> pd.DataFrame:
    selected = facts
    for field, value in filters.items():
        if value is not None and value != ALL:
            selected = selected.loc[selected[field].eq(value)]
    return selected.copy()


def ranked_issues(facts: pd.DataFrame, metric="total_minutes", limit=10) -> pd.DataFrame:
    table = issue_summary(facts, ["case"])
    if metric == "total_minutes":
        table = table.loc[table["valid_count"].gt(0)]
    return descending(table.sort_values("case", kind="stable"), metric).head(limit)


def case_months(facts: pd.DataFrame, periods=None) -> pd.DataFrame:
    """Calendar order; 0 means no matching records, NaN means time unavailable."""
    valid = facts.loc[facts["date"].notna()]
    if periods is None:
        dates = valid["date"]
        periods = (
            [] if dates.empty else pd.period_range(dates.min(), dates.max(), freq="M").astype(str)
        )
    table = issue_summary(valid, ["period"]).set_index("period").reindex(periods)
    for key in ("count", "valid_count", "review_count"):
        table[key] = pd.to_numeric(table[key], errors="coerce").fillna(0).astype(int)
    table.loc[table["count"].eq(0), "total_minutes"] = 0.0
    table.index.name = "period"
    return table.reset_index()


def priority_cases(facts: pd.DataFrame, limit=3) -> list[str]:
    """Union of time/count leaders, reserving room for both metrics."""
    # Unidentified equipment is a quality bucket, not evidence of the same case.
    facts = facts.loc[facts["module"].ne(MISSING["module"])]
    leaders = []
    rankings = [
        ranked_issues(facts, metric, limit)["case"].tolist()
        for metric in ("total_minutes", "count")
    ]
    for pair in zip(*[items + [None] * (limit - len(items)) for items in rankings]):
        for case in pair:
            if case and case not in leaders:
                leaders.append(case)
                if len(leaders) == limit:
                    return leaders
    return leaders
