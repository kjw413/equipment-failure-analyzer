"""What a per-record correction saves. Only fields the user actually changed are stored."""

from __future__ import annotations

import json
import math

import pandas as pd

from core.fault_components import CATEGORY_FIELDS as CLASSIFICATION
from core.fault_components import COMPONENT_OVERRIDE as COMPONENT_FIELD
from core.fault_components import parse_components
from core.i18n import UNMATCHED, K
from core.models import UserError

FIELDS = (*CLASSIFICATION, COMPONENT_FIELD, "target", "product", "work_date", "minutes")
PLACEHOLDERS = (K["missing"], K["unclassified"], *UNMATCHED, K["target_missing"], K["nonfault"])


def shown(value) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in PLACEHOLDERS or text.casefold() in ("nan", "nat", "none") else text


def component_override(value, *, multiple: bool = False) -> str:
    """Persist only canonical category names, never candidate scores or rule metadata."""
    components = parse_components(value, strict=True)
    if multiple and len(components) < 2:
        raise UserError("복수 유형 확정에는 서로 다른 대/중/소분류가 2개 이상 필요합니다.")
    return (
        json.dumps(
            [{key: component[key] for key in CLASSIFICATION} for component in components],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if components
        else ""
    )


def initial_values(record: dict, existing: dict) -> dict[str, str]:
    """Show observed components without confirming them while editing another field."""
    values = {key: shown(record.get(key)) for key in (*CLASSIFICATION, "target", "product")}
    saved_components = existing.get(COMPONENT_FIELD)
    observed = (
        record.get("component_details")
        if record.get("classification_mode") in ("single", "multiple")
        else None
    )
    parsed = (
        parse_components(saved_components, strict=True)
        if saved_components
        else parse_components(observed)
    )
    values[COMPONENT_FIELD] = component_override(parsed) if parsed else ""
    if saved_components or record.get("classification_mode") == "multiple":
        # A composite event label is not a single standard category.
        for key in CLASSIFICATION:
            values[key] = shown(existing.get(key))
    values.update(
        work_date=shown(existing.get("work_date")), minutes=shown(existing.get("minutes"))
    )
    return values


def validate(values: dict[str, str], *, confirm_components: bool = False) -> str | None:
    if confirm_components:
        try:
            component_override(values.get(COMPONENT_FIELD), multiple=True)
        except (UserError, ValueError, TypeError) as exc:
            return str(exc)
    else:
        parts = [values.get(key, "").strip() for key in CLASSIFICATION]
        if any(parts) and not all(parts):
            return "대/중/소분류를 모두 선택하거나 모두 비우세요."
    if values.get("work_date", "").strip():
        from core.parsing import parse_date

        if pd.isna(parse_date(values["work_date"].strip())):
            return "작업일자를 YYYY-MM-DD 형식으로 입력하세요."
    if values.get("minutes", "").strip():
        try:
            minutes = float(values["minutes"])
            valid = math.isfinite(minutes) and minutes >= 0
        except ValueError:
            valid = False
        if not valid:
            return "확정 정지시간은 0 이상의 숫자(분)로 입력하세요."
    return None


def correction_patch(
    initial: dict[str, str],
    values: dict[str, str],
    existing: dict,
    confirm: bool,
    *,
    confirm_components: bool = False,
) -> dict[str, str | None]:
    """Require an explicit choice before confirming multiple observed fault types."""
    values = {key: str(values.get(key, "")).strip() for key in FIELDS}
    patch = {}
    parts = tuple(values[key] for key in CLASSIFICATION)
    before = tuple(initial.get(key, "") for key in CLASSIFICATION)
    if confirm_components:
        patch[COMPONENT_FIELD] = component_override(values[COMPONENT_FIELD], multiple=True)
        patch.update({key: None for key in CLASSIFICATION if key in existing})
    elif all(parts) and (confirm or parts != before):
        patch.update(zip(CLASSIFICATION, parts))
        if COMPONENT_FIELD in existing:
            patch[COMPONENT_FIELD] = None
    elif not any(parts) and any(existing.get(key) for key in CLASSIFICATION):
        patch.update({key: None for key in CLASSIFICATION})
    elif existing.get(COMPONENT_FIELD) and not values[COMPONENT_FIELD]:
        # Clearing all saved component rows removes only that classification override.
        patch[COMPONENT_FIELD] = None
    for key in ("target", "product", "work_date", "minutes"):
        if values[key] != initial.get(key, ""):
            patch[key] = values[key] or None
    return {key: value for key, value in patch.items() if value is not None or key in existing}
