"""Internal part paths and user-facing part/symptom classification choices."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from core.fault_components import CATEGORY_FIELDS
from core.models import UserError

CATALOG_FILE = "classification_catalog.json"


def validate_catalog(value: Any) -> dict:
    """Validate the versioned source catalogue before migrating an active profile."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise UserError(f"{CATALOG_FILE}: unsupported schema")
    if not isinstance(value.get("catalog_id"), str) or not value["catalog_id"].strip():
        raise UserError(f"{CATALOG_FILE}: catalog_id가 필요합니다.")
    if "output_schema" in value:
        from core.failure_modes import CLASSIFICATION_SCHEMA

        if value["output_schema"] != CLASSIFICATION_SCHEMA:
            raise UserError(f"{CATALOG_FILE}: unsupported output schema")
        axes = value.get("output_axes")
        if not isinstance(axes, dict) or not all(
            isinstance(axes.get(key), str) and axes[key].strip() for key in CATEGORY_FIELDS
        ):
            raise UserError(f"{CATALOG_FILE}: 분야·부품·증상 출력 축이 필요합니다.")
    rows = value.get("categories")
    if not isinstance(rows, list) or not rows:
        raise UserError(f"{CATALOG_FILE}: 분류 목록이 비어 있습니다.")
    paths, owners = set(), {}
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) and row[key].strip() for key in CATEGORY_FIELDS
        ):
            raise UserError(f"{CATALOG_FILE}: 모든 경로에 대·중·소분류가 필요합니다.")
        path = tuple(row[key].strip() for key in CATEGORY_FIELDS)
        if path in paths:
            raise UserError(f"{CATALOG_FILE}: 중복 분류 경로 {' / '.join(path)}")
        paths.add(path)
        if path[1] in owners and owners[path[1]] != path[0]:
            raise UserError(f"{CATALOG_FILE}: 중분류 {path[1]}의 대분류가 둘 이상입니다.")
        owners[path[1]] = path[0]
    return value


def catalog_signature(value: dict) -> str:
    """Stable revision identity without tying migration to a source file location."""
    validate_catalog(value)
    semantic = {"catalog_id": value["catalog_id"], "categories": value["categories"]}
    for key in ("output_schema", "output_axes", "part_axes"):
        if key in value:
            semantic[key] = value[key]
    return hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def catalog_categories(rules: Iterable[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """Return internal physical-part paths from all enabled rule roles.

    Disabled rules are excluded from new choices. Existing manual categories are
    preserved separately by the editor, rather than becoming new shared choices.
    """
    paths = set()
    for rule in rules:
        enabled = rule.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().casefold() in {"1", "true", "yes"}
        if not enabled:
            continue
        values = tuple(rule.get(key) for key in CATEGORY_FIELDS)
        if not all(isinstance(value, str) and value.strip() for value in values):
            continue
        paths.add(tuple(value.strip() for value in values))
    return sorted(paths, key=lambda path: (tuple(value.casefold() for value in path), path))


def fault_catalog_categories(rules: Iterable[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """Choices for the output axes: field, precise part type, observed symptom.

    The original part catalogue remains the name/alias library. Only parts with
    enabled rules become new choices; legacy saved values are retained by the
    editor for their own record instead of being added to this shared menu.
    """
    from core.failure_modes import SYMPTOM_NAMES, part_name

    choices = {
        (major, part_name(part), symptom)
        for major, _family, part in catalog_categories(rules)
        for symptom in SYMPTOM_NAMES
    }
    return sorted(choices, key=lambda path: (tuple(value.casefold() for value in path), path))
