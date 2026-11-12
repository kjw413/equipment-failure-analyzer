"""Identify fault events awaiting a valid single final category; exports remain available."""

from __future__ import annotations

import pandas as pd

from core.classification_completeness import missing_fields_text
from core.failure_modes import UNKNOWN_SYMPTOM
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import UNMATCHED, K
from core.models import AnalysisResult, UserError


def unresolved_classifications(records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return records.copy()
    faults = records.loc[records["kind"].eq(K["fault"])].copy()
    placeholders = {
        *UNMATCHED,
        K["review"],
        K["missing"],
        K["unclassified"],
        K["nonfault"],
        UNKNOWN_SYMPTOM,
        "증상 미기재",
        "교체",
        "복수 고장",
    }

    def resolved(record):
        members = parse_components(record.get("component_details"))
        if record.get("status") not in (K["auto"], K["manual"], K["partial"]):
            return False
        if record.get("classification_mode") != "single" or len(members) != 1:
            return False
        partial = record.get("status") == K["partial"]
        if partial and (
            not missing_fields_text(record)
            or record.get("classification_missing_fields") != missing_fields_text(record)
        ):
            return False
        return all(
            isinstance(record.get(key), str)
            and record[key].strip()
            and (
                record[key] not in placeholders
                or (partial and key == "minor" and record[key] == UNKNOWN_SYMPTOM)
            )
            and record[key] == members[0].get(key)
            for key in CATEGORY_FIELDS
        )

    mask = [not resolved(record) for record in faults.to_dict("records")]
    return faults.loc[mask]


def validate_final_classifications(result: AnalysisResult) -> None:
    pending = unresolved_classifications(result.selected)
    if pending.empty:
        return
    raise UserError(
        f"최종 분류가 확정되지 않은 고장이력 {len(pending):,}건이 있습니다. "
        "[검토필요]에서 추천 후보를 확인하고 이력마다 대분류·상세설비·세부 부품·소분류 하나를 선택할 수 있습니다. 보고서 출력은 가능합니다."
    )
