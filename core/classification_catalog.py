"""Selectable classification paths derived from the currently enabled rules."""

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
    return hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def catalog_categories(rules: Iterable[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """Return complete, distinct paths across component, fallback and override rules.

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
