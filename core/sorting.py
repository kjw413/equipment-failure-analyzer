"""One numeric descending-order policy shared by GUI, Excel and PDF.

Source records are never reordered in place. A returned presentation copy has a
fresh index so row references and cached Excel formulas remain consistent.
"""
from __future__ import annotations
import pandas as pd


def default_metric(frame: pd.DataFrame) -> str | None:
    return next((name for name in ('total_minutes', 'minutes', 'count', 'value')
                 if name in frame.columns), None)


def descending(frame: pd.DataFrame, metric: str | None = None) -> pd.DataFrame:
    """Largest first, ties by the complementary metric, unknown values last.

    Equal keys keep their input order. This preserves deterministic label order
    from groupby and source order for equally long individual stop records.
    Display strings (commas and percentages) are applied only after this step.
    """
    result = frame.reset_index(drop=True).copy()
    primary = metric or default_metric(result)
    if result.empty or primary not in result.columns:
        return result
    candidates = [primary]
    if primary == 'total_minutes':
        candidates.append('count')
    elif primary == 'count':
        candidates.append('total_minutes')
    columns = [column for column in candidates if column in result.columns]
    keys = pd.DataFrame({column: pd.to_numeric(result[column], errors='coerce')
                         for column in columns})
    order = keys.sort_values(columns, ascending=False, na_position='last',
                             kind='stable').index
    return result.iloc[order].reset_index(drop=True)
