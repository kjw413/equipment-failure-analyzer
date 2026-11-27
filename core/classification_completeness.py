"""Keep missing classification data separate from competing interpretations."""

from core.failure_modes import UNKNOWN_EQUIPMENT, UNKNOWN_PART, UNKNOWN_SYMPTOM
from core.fault_components import PUBLIC_CATEGORY_FIELDS
from core.i18n import K
from core.public_taxonomy import UNKNOWN_DOMAIN

MISSING_VALUES = {
    "major": {UNKNOWN_DOMAIN},
    "detail_equipment": {UNKNOWN_EQUIPMENT},
    "middle": {UNKNOWN_PART},
    "minor": {UNKNOWN_SYMPTOM, "증상 미기재"},
}


def missing_fields(category: dict) -> tuple[str, ...]:
    return tuple(
        key
        for key in PUBLIC_CATEGORY_FIELDS
        if not category.get(key) or category[key] in MISSING_VALUES[key]
    )


def missing_fields_text(category: dict) -> str:
    return ", ".join(K[key] for key in missing_fields(category))
