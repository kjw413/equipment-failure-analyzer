"""Report-only name projection. The original workbook and stable IDs stay intact.

Known asset-code tokens are converted once, never through chained replacements.
All report tables, chart labels and free-text cells use the same projection.
"""
from __future__ import annotations
from dataclasses import replace
import re
import pandas as pd
from core.equipment_names import code_key
from core.models import AnalysisResult


class ReportNames:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = {code_key(k): v for k, v in mapping.items() if k and v}
        # Preserve a display name that itself contains another code as a token.
        # Replacing twice must not turn a previously projected name into a new name.
        self.protected = set(self.mapping.values())
        codes = sorted(self.mapping, key=len, reverse=True)
        if codes:
            protected = sorted(self.protected, key=len, reverse=True)
            pattern = (r'(?P<display>' + '|'.join(map(re.escape, protected)) + r')|'
                       r'(?P<code>(?<![A-Za-z0-9_])(?:' + '|'.join(map(re.escape, codes)) + r')(?![A-Za-z0-9_]))')
            self.pattern = re.compile(pattern, re.IGNORECASE)
        else:
            self.pattern = None

    def text(self, value):
        if not isinstance(value, str) or self.pattern is None or value in self.protected:
            return value
        return self.pattern.sub(lambda m: m.group() if m.lastgroup == 'display' else self.mapping.get(code_key(m.group()), m.group()), value)

    def frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy(deep=True)
        # Hashes and event IDs are not display names and must never be modified.
        for column in result.columns:
            if column in ('record_id', 'event_id'):
                continue
            if pd.api.types.is_object_dtype(result[column]) or isinstance(result[column].dtype, pd.StringDtype):
                result[column] = result[column].map(self.text)
        return result


def report_result(result: AnalysisResult) -> AnalysisResult:
    """Return a presentation snapshot, not a change to the analysis/source data."""
    names = ReportNames(result.config_snapshot.get('equipment_names', {}).get('mappings', {}))
    loaded = replace(result.loaded, frame=names.frame(result.loaded.frame))
    return replace(result, loaded=loaded,
                   all_records=names.frame(result.all_records),
                   selected=names.frame(result.selected),
                   tables={key: names.frame(table) for key, table in result.tables.items()},
                   notes=[names.text(note) for note in result.notes])
