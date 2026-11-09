"""Report-only name projection. The original workbook and stable IDs stay intact.

Known asset-code tokens are converted once, never through chained replacements.
All report tables, chart labels and free-text cells use the same projection.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pandas as pd

from core.equipment_names import active_name_mapping, code_key
from core.models import AnalysisResult


class ReportNames:
    def __init__(self, mapping: dict[str, str], *, protected=()):
        self.mapping = {code_key(k): v for k, v in mapping.items() if k and v}
        # Preserve a display name that itself contains another code as a token.
        # Replacing twice must not turn a previously projected name into a new name.
        self.protected = set(self.mapping.values()) | set(protected)
        codes = sorted(self.mapping, key=len, reverse=True)
        if codes:
            protected = sorted(self.protected, key=len, reverse=True)
            pattern = (
                r"(?P<display>" + "|".join(map(re.escape, protected)) + r")|"
                r"(?P<code>(?<![A-Za-z0-9_])(?:"
                + "|".join(map(re.escape, codes))
                + r")(?![A-Za-z0-9_]))"
            )
            self.pattern = re.compile(pattern, re.IGNORECASE)
        else:
            self.pattern = None

    def text(self, value):
        if not isinstance(value, str) or self.pattern is None or value in self.protected:
            return value
        return self.pattern.sub(
            lambda m: (
                m.group()
                if m.lastgroup == "display"
                else self.mapping.get(code_key(m.group()), m.group())
            ),
            value,
        )

    def components(self, value):
        """Project structured display fields while preserving valid JSON and identity."""
        if not isinstance(value, str) or not value or self.pattern is None:
            return value
        try:
            members = json.loads(value)
        except (TypeError, ValueError):
            return value
        if not isinstance(members, list):
            return value
        projected = []
        for member in members:
            if not isinstance(member, dict):
                projected.append(member)
                continue
            item = dict(member)
            for key in (
                "major",
                "middle",
                "minor",
                "part_group",
                "part_type",
                "symptom_evidence",
                "evidence",
            ):
                if isinstance(item.get(key), str):
                    item[key] = self.text(item[key])
            if isinstance(item.get("actions"), list):
                item["actions"] = [self.text(action) for action in item["actions"]]
            elif isinstance(item.get("actions"), str):
                item["actions"] = self.text(item["actions"])
            projected.append(item)
        return json.dumps(projected, ensure_ascii=False, separators=(",", ":"))

    def frame(self, frame: pd.DataFrame, *, preserve=()) -> pd.DataFrame:
        result = frame.copy(deep=True)
        # Hashes and event IDs are not display names and must never be modified.
        for column in result.columns:
            if column in (
                "record_id",
                "event_id",
                "combination_key",
                "equipment_group",
                "factory",
                "team",
                *preserve,
            ):
                continue
            if column == "component_details":
                result[column] = result[column].map(self.components)
                continue
            if pd.api.types.is_object_dtype(result[column]) or isinstance(
                result[column].dtype, pd.StringDtype
            ):
                result[column] = result[column].map(self.text)
        return result


def report_result(result: AnalysisResult) -> AnalysisResult:
    """Return a presentation snapshot, not a change to the analysis/source data."""
    names = ReportNames(
        active_name_mapping(result.loaded, result.config_snapshot.get("equipment_names", {}))
    )
    preserve = (
        ("equipment",) if result.options.equipment_basis in ("group", "factory", "team") else ()
    )
    loaded = replace(result.loaded, frame=names.frame(result.loaded.frame))
    return replace(
        result,
        loaded=loaded,
        all_records=names.frame(result.all_records, preserve=preserve),
        selected=names.frame(result.selected, preserve=preserve),
        tables={key: names.frame(table, preserve=preserve) for key, table in result.tables.items()},
        notes=[names.text(note) for note in result.notes],
    )
