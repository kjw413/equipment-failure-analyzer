"""Internal part paths and user-facing part/symptom classification choices."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any

from core.fault_components import CATEGORY_FIELDS, PART_CATEGORY_FIELDS
from core.models import UserError

CATALOG_FILE = "classification_catalog.json"


def validate_catalog(value: Any) -> dict:
    """Validate the versioned source catalogue before migrating an active profile."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise UserError(f"{CATALOG_FILE}: unsupported schema")
    if not isinstance(value.get("catalog_id"), str) or not value["catalog_id"].strip():
        raise UserError(f"{CATALOG_FILE}: catalog_id가 필요합니다.")
    if "output_schema" in value:
        from core.failure_modes import CLASSIFICATION_SCHEMA, LEGACY_CLASSIFICATION_SCHEMAS

        if value["output_schema"] not in {CLASSIFICATION_SCHEMA, *LEGACY_CLASSIFICATION_SCHEMAS}:
            raise UserError(f"{CATALOG_FILE}: unsupported output schema")
        axes = value.get("output_axes")
        output_fields = (
            CATEGORY_FIELDS if value["output_schema"] != "part_symptom_v1" else PART_CATEGORY_FIELDS
        )
        if not isinstance(axes, dict) or not all(
            isinstance(axes.get(key), str) and axes[key].strip() for key in output_fields
        ):
            raise UserError(f"{CATALOG_FILE}: 분야·부품·증상 출력 축이 필요합니다.")
    rows = value.get("categories")
    if not isinstance(rows, list) or not rows:
        raise UserError(f"{CATALOG_FILE}: 분류 목록이 비어 있습니다.")
    paths, owners = set(), {}
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) and row[key].strip() for key in PART_CATEGORY_FIELDS
        ):
            raise UserError(f"{CATALOG_FILE}: 모든 경로에 대·중·소분류가 필요합니다.")
        path = tuple(row[key].strip() for key in PART_CATEGORY_FIELDS)
        if path in paths:
            raise UserError(f"{CATALOG_FILE}: 중복 분류 경로 {' / '.join(path)}")
        paths.add(path)
        if path[1] in owners and owners[path[1]] != path[0]:
            raise UserError(f"{CATALOG_FILE}: 중분류 {path[1]}의 대분류가 둘 이상입니다.")
        owners[path[1]] = path[0]
    if "equipment_types" in value:
        from core.equipment_taxonomy import equipment_type_names, validate_equipment_types

        validate_equipment_types(value["equipment_types"])
        if not equipment_type_names(value["equipment_types"]):
            raise UserError(f"{CATALOG_FILE}: 상세설비 목록이 비어 있습니다.")
    public = value.get("public_taxonomy")
    if public is not None:
        if not isinstance(public, dict):
            raise UserError(f"{CATALOG_FILE}: 공개 분류 목록 형식을 확인하세요.")
        for key in ("domains", "modes", "actions"):
            names = public.get(key)
            if (
                not isinstance(names, list)
                or not names
                or any(not isinstance(n, str) or not n.strip() for n in names)
                or len(set(names)) != len(names)
            ):
                raise UserError(f"{CATALOG_FILE}: {key} 항목을 확인하세요.")
        names = set()
        for row in public.get("parts", []):
            if (
                not isinstance(row, dict)
                or not all(
                    isinstance(row.get(k), str) and row[k].strip() for k in ("name", "family")
                )
                or row["name"] in names
            ):
                raise UserError(f"{CATALOG_FILE}: 부품명·부품군과 중복 항목을 확인하세요.")
            names.add(row["name"])
            if any(
                not isinstance(row.get(k, []), list)
                or any(not isinstance(a, str) or not a.strip() for a in row.get(k, []))
                for k in ("aliases", "old_names")
            ):
                raise UserError(f"{CATALOG_FILE}: 부품 동의어 목록을 확인하세요.")
        if not names:
            raise UserError(f"{CATALOG_FILE}: 부품 목록이 비어 있습니다.")
    return value


def catalog_signature(value: dict) -> str:
    """Stable revision identity without tying migration to a source file location."""
    validate_catalog(value)
    semantic = {"catalog_id": value["catalog_id"], "categories": value["categories"]}
    for key in ("output_schema", "output_axes", "part_axes", "equipment_types", "public_taxonomy"):
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
        values = tuple(rule.get(key) for key in PART_CATEGORY_FIELDS)
        if not all(isinstance(value, str) and value.strip() for value in values):
            continue
        paths.add(tuple(value.strip() for value in values))
    return sorted(paths, key=lambda path: (tuple(value.casefold() for value in path), path))


def fault_catalog_categories(
    rules: Iterable[Mapping[str, Any]], equipment_types=None
) -> list[tuple[str, str, str, str]]:
    """Choices for the output axes: field, precise part type, observed symptom.

    The original part catalogue remains the name/alias library. Only parts with
    enabled rules become new choices; legacy saved values are retained by the
    editor for their own record instead of being added to this shared menu.
    """
    from core.equipment_taxonomy import equipment_types as checked_types
    from core.public_taxonomy import default_catalog

    if equipment_types is None:
        equipment_types = default_catalog().get("equipment_types")
    types = tuple((row["name"], tuple(row["aliases"])) for row in checked_types(equipment_types))
    return list(_fault_paths(tuple(catalog_categories(rules)), types))


def equipment_classification_categories(rules, equipment_types=None):
    """Project the selectable fault fields onto the detailed-equipment hierarchy."""
    from core.equipment_taxonomy import equipment_types as checked_types
    from core.failure_modes import UNKNOWN_EQUIPMENT
    from core.public_taxonomy import UNKNOWN_DOMAIN, default_catalog

    if equipment_types is None:
        equipment_types = default_catalog().get("equipment_types")
    equipment = sorted(
        {UNKNOWN_EQUIPMENT, *(row["name"] for row in checked_types(equipment_types))}
    )
    domains = tuple(sorted({UNKNOWN_DOMAIN, *(path[0] for path in catalog_categories(rules))}))
    return _equipment_classification_paths(domains, tuple(equipment))


@lru_cache(maxsize=4)
def _equipment_classification_paths(domains, equipment):
    from core.failure_modes import SYMPTOM_NAMES

    return tuple(
        (domain, module, symptom)
        for domain in domains
        for module in equipment
        for symptom in SYMPTOM_NAMES
    )


@lru_cache(maxsize=4)
def _fault_paths(parts, types):
    """Reuse the full menu across editor openings without sharing mutable lists."""
    from core.failure_modes import SYMPTOM_NAMES, UNKNOWN_EQUIPMENT, UNKNOWN_PART
    from core.public_taxonomy import UNKNOWN_DOMAIN, default_taxonomy

    equipment_names = {UNKNOWN_EQUIPMENT, *(name for name, _ in types)}
    taxonomy = default_taxonomy()
    part_choices = {
        (major, equipment, taxonomy.component_name(part, equipment))
        for major, _family, part in parts
        for equipment in equipment_names
    }
    part_choices.update(
        (major, equipment, UNKNOWN_PART)
        for major in {path[0] for path in parts}
        for equipment in equipment_names
    )
    # The picker indexes independent axes, so one anchor exposes the unknown
    # domain without multiplying the already independent choice sets.
    part_choices.add((UNKNOWN_DOMAIN, UNKNOWN_EQUIPMENT, UNKNOWN_PART))
    choices = (path + (symptom,) for path in part_choices for symptom in SYMPTOM_NAMES)
    return tuple(
        sorted(choices, key=lambda path: (tuple(value.casefold() for value in path), path))
    )
