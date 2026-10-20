"""Exact, persistent asset-code -> report-name mapping.

This is separate from equipment_aliases (free-text spelling normalization).
An alias never changes the original workbook or an event's stable identity.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from core.models import LoadedData, UserError
from core.parsing import text as clean_text


def code_key(value: Any) -> str:
    """Normalize casing/outer whitespace, never use substring matching."""
    return unicodedata.normalize("NFKC", clean_text(value)).strip().upper()


def validate_names(mapping: dict[str, str]) -> dict[str, str]:
    if not isinstance(mapping, dict):
        raise UserError(
            "\uc124\ube44\uba85 \uc124\uc815 \ud615\uc2dd\uc744 \ud655\uc778\ud558\uc138\uc694."
        )
    checked: dict[str, str] = {}
    used_names: dict[str, str] = {}
    for original, value in mapping.items():
        if not isinstance(original, str) or not isinstance(value, str):
            raise UserError(
                "\uc124\ube44 \ucf54\ub4dc\uc640 \ud45c\uc2dc\uba85\uc740 \ubb38\uc790\uc5f4\uc774\uc5b4\uc57c \ud569\ub2c8\ub2e4."
            )
        key, name = code_key(original), value.strip()
        if not key:
            if name:
                raise UserError(
                    "\ud45c\uc2dc\uba85\uc5d0 \ub300\ud55c \uc124\ube44 \ucf54\ub4dc\ub97c \uc785\ub825\ud558\uc138\uc694."
                )
            continue
        if len(key) > 200 or len(name) > 120 or re.search(r"[\x00-\x1f\x7f]", key + name):
            raise UserError(
                "\uc124\ube44 \ucf54\ub4dc/\uc774\ub984\uc758 \uae38\uc774 \ub610\ub294 \uc904\ubc14\uafc8\uc744 \ud655\uc778\ud558\uc138\uc694."
            )
        if not name:
            continue  # Clearing the name removes the conversion, not source data.
        if key in checked:
            raise UserError(f"\uc124\ube44 \ucf54\ub4dc \uc911\ubcf5: {key}")
        name_key = unicodedata.normalize("NFKC", name).casefold()
        if name_key in used_names and used_names[name_key] != key:
            raise UserError(
                f"\uc11c\ub85c \ub2e4\ub978 \ucf54\ub4dc\uc5d0 \uac19\uc740 \uc774\ub984\uc744 \uc9c0\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4: {name}\n"
                "\uc124\ube44\ubcc4 \uc9d1\uacc4 \ud63c\uc120\uc744 \ub9c9\uae30 \uc704\ud574 \uad6c\ubd84\ud574 \uc785\ub825\ud558\uc138\uc694."
            )
        checked[key] = name
        used_names[name_key] = key
    # A display name identical to a different raw code would silently merge assets.
    for key, name in checked.items():
        if code_key(name) in checked and code_key(name) != key:
            raise UserError(
                f"\ub2e4\ub978 \uc124\ube44 \ucf54\ub4dc\uc640 \uac19\uc740 \ud45c\uc2dc\uba85: {name}"
            )
    return checked


def resolve_name(code: Any, raw_name: Any, mapping: dict[str, str]) -> tuple[str, bool]:
    key = code_key(code)
    if key and key in mapping:
        return mapping[key], True
    # Unknown assets stay recognizable and separate: do not guess a friendly name.
    fallback = key or clean_text(raw_name) or "\ubbf8\uae30\uc7ac"
    if not key and code_key(raw_name) in mapping:
        return mapping[code_key(raw_name)], True
    return fallback, False


def equipment_catalog(loaded: LoadedData | None) -> list[dict[str, str]]:
    """Unique source codes with original names for the editor's reference column."""
    if loaded is None:
        return []
    id_column = loaded.mapping.get("equipment_id")
    name_column = loaded.mapping.get("equipment_name")
    catalog: dict[str, dict] = {}
    for record in loaded.frame.to_dict("records"):
        code = clean_text(record.get(id_column)) if id_column else ""
        raw_name = clean_text(record.get(name_column)) if name_column else ""
        code = code or raw_name
        if not code:
            continue
        key = code_key(code)
        item = catalog.setdefault(key, {"code": key, "raw_names": set()})
        if raw_name:
            item["raw_names"].add(raw_name)
    return [
        {"code": key, "raw_name": " / ".join(sorted(v["raw_names"]))}
        for key, v in sorted(catalog.items())
    ]
