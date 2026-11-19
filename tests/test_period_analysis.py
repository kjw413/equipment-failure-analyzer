"""Daily drilldown reconciles dated records without inventing missing durations."""

import pandas as pd
import pytest

from core.period_analysis import DAY_COLUMNS, case_days


def test_month_includes_empty_days_and_retains_missing_time_and_reviews():
    facts = pd.DataFrame(
        {
            "date": ["2026-01-01 08:30", "2026-01-01 16:00", "2026-01-03", None, "2026-02-01"],
            "minutes": [1.25, 2.5, None, 99, 50],
            "review_count": [0, 1, 1, 1, 0],
        }
    )
    before = facts.copy(deep=True)
    result = case_days(facts, "2026-01").set_index("period")
    assert list(result.index) == [f"2026-01-{day:02d}" for day in range(1, 32)]
    assert result.loc["2026-01-01", "count"] == 2
    assert result.loc["2026-01-01", "total_minutes"] == 3.75
    assert result.loc["2026-01-01", "mean_minutes"] == 1.875
    assert result.loc["2026-01-01", "valid_count"] == 2
    assert result.loc["2026-01-02", "count"] == 0
    assert result.loc["2026-01-02", "total_minutes"] == 0
    assert pd.isna(result.loc["2026-01-02", "mean_minutes"])
    assert result.loc["2026-01-03", "count"] == 1
    assert result.loc["2026-01-03", "valid_count"] == 0
    assert pd.isna(result.loc["2026-01-03", "total_minutes"])
    assert pd.isna(result.loc["2026-01-03", "mean_minutes"])
    assert result["count"].sum() == 3
    assert result["review_count"].sum() == 2
    assert result["total_minutes"].sum() == 3.75
    pd.testing.assert_frame_equal(facts, before)


@pytest.mark.parametrize(("month", "days"), [("2024-02", 29), ("2026-02", 28), ("2026-04", 30)])
def test_empty_selected_month_uses_the_real_calendar(month, days):
    facts = pd.DataFrame(columns=["date", "minutes", "review_count"])
    result = case_days(facts, month)
    assert list(result.columns) == DAY_COLUMNS
    assert len(result) == days
    assert result.iloc[-1]["period"] == f"{month}-{days}"
    assert result["count"].sum() == 0 and result["total_minutes"].sum() == 0
    assert result["mean_minutes"].isna().all()


def test_unselected_month_spans_dated_days_and_never_uses_unknown_dates():
    facts = pd.DataFrame(
        {"date": ["2026-01-31", "invalid", "2026-02-02"], "minutes": [0, 500, None]}
    )
    result = case_days(facts)
    assert result["period"].tolist() == ["2026-01-31", "2026-02-01", "2026-02-02"]
    assert result["count"].tolist() == [1, 0, 1]
    assert result["review_count"].tolist() == [0, 0, 0]
    assert result["total_minutes"].iloc[:2].tolist() == [0, 0]
    assert pd.isna(result["total_minutes"].iloc[2])
    undated = case_days(facts.loc[facts.date.eq("invalid")])
    assert undated.empty and list(undated.columns) == DAY_COLUMNS


@pytest.mark.parametrize(
    "month", ["2026-00", "2026-13", "2026-2", "2026-02-01", "0000-01", "x", 202602]
)
def test_invalid_month_is_rejected(month):
    facts = pd.DataFrame(columns=["date", "minutes"])
    with pytest.raises(ValueError, match="YYYY-MM"):
        case_days(facts, month)
