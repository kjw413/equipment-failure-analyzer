from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd

CLASSIFICATION_DECISION_COLUMNS = ("classification_reason", "candidate_evidence")

CLASSIFICATION_COMPONENT_COLUMNS = (
    "classification_mode",
    "component_count",
    "component_types",
    "component_details",
    "combination_key",
    "part_count",
    "classification_schema",
    "detail_equipment_source",
    "detail_equipment_evidence",
    "part_group",
    "repair_actions",
    "classification_missing_fields",
    "classification_known_fields",
)

Progress = Callable[[int, str], None]


def noop_progress(value: int, message: str) -> None:
    """Default callback for non-interactive callers."""


class UserError(Exception):
    """An actionable error suitable for display without a traceback."""


@dataclass
class LoadedData:
    path: Path
    sheet: str
    header_row: int
    frame: pd.DataFrame
    headers: list[str]
    mapping: dict[str, str | None]
    profile: str
    file_hash: str
    skipped: list[dict[str, Any]] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AnalysisOptions:
    scope: str = "fault"  # fault or all; unknown labels remain unknown
    equipment_basis: str = (
        "mapped"  # mapped / group / factory / team / target / registered / family
    )
    date_from: str | None = None
    date_to: str | None = None
    duration_unit: str = "minutes"
    deduplicate: bool = False
    top_n: int = 10
    factory: str | None = None
    team: str | None = None


@dataclass
class AnalysisResult:
    loaded: LoadedData
    all_records: pd.DataFrame
    selected: pd.DataFrame
    tables: dict[str, pd.DataFrame]
    options: AnalysisOptions
    metrics: dict[str, Any]
    notes: list[str]
    config_hash: str
    config_snapshot: dict[str, Any]
