"""Supported axes survive a pending final classification; candidates never count."""

from __future__ import annotations

import json

from core.classification_completeness import MISSING_VALUES
from core.fault_components import CATEGORY_FIELDS

KNOWN_FIELDS = "classification_known_fields"


def known_fields(record: dict) -> dict[str, str]:
    """Read only explicitly retained values that still match the record's axes.

    Older results containing candidate values in the category columns have no
    marker and remain unconfirmed. This is not a candidate-selection shortcut.
    """
    try:
        values = json.loads(record.get(KNOWN_FIELDS) or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(values, dict):
        return {}
    return {
        key: value
        for key, value in values.items()
        if key in CATEGORY_FIELDS
        and isinstance(value, str)
        and value.strip()
        and value == record.get(key)
        and value not in MISSING_VALUES[key]
    }
