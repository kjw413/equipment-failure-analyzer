"""What a per-record correction saves. Only fields the user actually changed are stored."""

from __future__ import annotations

import json
import math

import pandas as pd

from core.failure_modes import UNKNOWN_SYMPTOM
from core.fault_components import CATEGORY_FIELDS as CLASSIFICATION
from core.fault_components import COMPONENT_OVERRIDE as COMPONENT_FIELD
from core.fault_components import parse_components
from core.i18n import UNMATCHED, K
from core.models import UserError
from core.public_taxonomy import parse_repair_actions

FIELDS = (
    *CLASSIFICATION,
    COMPONENT_FIELD,
    "repair_actions",
    "target",
    "product",
    "work_date",
    "minutes",
)
PLACEHOLDERS = (
    K["missing"],
    K["unclassified"],
    *UNMATCHED,
    K["target_missing"],
    K["nonfault"],
    K["review"],
    UNKNOWN_SYMPTOM,
    "증상 미기재",
    "복수 고장",
)


def shown(value) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in PLACEHOLDERS or text.casefold() in ("nan", "nat", "none") else text


def component_override(value, *, multiple: bool = False) -> str:
    """Persist only canonical category names, never candidate scores or rule metadata."""
    components = parse_components(value, strict=True)
    if multiple or len(components) > 1:
        raise UserError("고장이력 한 건에는 최종 분류 하나만 확정할 수 있습니다.")
    if any(not all(component.get(key) for key in CLASSIFICATION) for component in components):
        raise UserError("대분류·상세설비·세부 부품·소분류를 모두 선택하세요.")
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
    """Keep old saved data intact until a user explicitly chooses one final type."""
    values = {key: shown(record.get(key)) for key in (*CLASSIFICATION, "target", "product")}
    saved_components = existing.get(COMPONENT_FIELD)
    parsed = parse_components(saved_components or record.get("component_details"))
    values[COMPONENT_FIELD] = str(saved_components or "")
    if (
        saved_components
        or len(parsed) > 1
        or record.get("status") in (K["review"], *UNMATCHED)
        or record.get("classification_mode") in ("multiple", "ambiguous")
        or (record.get("minor") == UNKNOWN_SYMPTOM and record.get("status") != K["partial"])
        or (
            any(existing.get(key) for key in CLASSIFICATION)
            and not existing.get("detail_equipment")
        )
    ):
        for key in CLASSIFICATION:
            values[key] = ""
    values.update(
        work_date=shown(existing.get("work_date")), minutes=shown(existing.get("minutes"))
    )
    values["repair_actions"] = str(
        existing.get("repair_actions", record.get("repair_actions", "")) or ""
    )
    return values


def validate(values: dict[str, str], *, confirm_components: bool = False) -> str | None:
    if confirm_components:
        return "고장이력 한 건에는 최종 분류 하나만 확정할 수 있습니다."
    else:
        parts = [values.get(key, "").strip() for key in CLASSIFICATION]
        if any(parts) and not all(parts):
            return "대분류·상세설비·세부 부품·소분류를 모두 선택하거나 모두 비우세요."
        if all(parts) and any(part in PLACEHOLDERS for part in parts):
            return "검토 상태 대신 실제 대분류·상세설비·세부 부품·소분류를 선택하세요. 증상을 확인할 수 없으면 검토 상태로 남겨두세요."
        if values.get("minor") in {"교체", "수리", "조정", "점검", "청소", "급유"}:
            return "조치는 고장 현상 대신 조치 내역에서 선택하세요."
    if "repair_actions" in values:
        try:
            parse_repair_actions(values["repair_actions"], strict=True)
        except ValueError as exc:
            return str(exc)
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
    """Only an explicit single choice can replace a pending or legacy classification."""
    if confirm_components:
        raise UserError("고장이력 한 건에는 최종 분류 하나만 확정할 수 있습니다.")
    values = {key: str(values.get(key, "")).strip() for key in FIELDS}
    patch = {}
    parts = tuple(values[key] for key in CLASSIFICATION)
    before = tuple(initial.get(key, "") for key in CLASSIFICATION)
    if all(parts) and (confirm or parts != before):
        error = validate(dict(zip(CLASSIFICATION, parts)))
        if error:
            raise UserError(error)
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
    if values["repair_actions"] != initial.get("repair_actions", ""):
        try:
            patch["repair_actions"] = ", ".join(
                parse_repair_actions(values["repair_actions"], strict=True)
            )
        except ValueError as exc:
            raise UserError(str(exc)) from exc
    return {key: value for key, value in patch.items() if value is not None or key in existing}
