"""Canonical fault-type members and stable labels for one downtime record.

Members describe types linked to an event; they never duplicate its downtime.
Alternative interpretations of one part must not be supplied as separate members.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.failure_modes import CLASSIFICATION_SCHEMA, UNKNOWN_PART, part_key
from core.models import UserError
from core.public_taxonomy import part_group

PART_CATEGORY_FIELDS = ("major", "middle", "minor")
CATEGORY_FIELDS = ("major", "detail_equipment", "middle", "minor")
COMPONENT_OVERRIDE = "classification_components"


def type_label(component: dict) -> str:
    fields = CATEGORY_FIELDS if component.get("detail_equipment") else PART_CATEGORY_FIELDS
    return " / ".join(str(component[key]).strip() for key in fields)


def canonical_components(components: list[dict]) -> list[dict]:
    """One evidence entry per complete type, in input-order-independent order."""
    if not isinstance(components, list):
        raise UserError("고장 유형 목록은 배열이어야 합니다.")
    unique: dict[tuple[str, ...], dict] = {}
    for item in components:
        if not isinstance(item, dict):
            raise UserError("각 고장 유형에 대·중·소분류를 입력하세요.")
        fields = (
            CATEGORY_FIELDS
            if item.get("schema") == CLASSIFICATION_SCHEMA or item.get("detail_equipment")
            else PART_CATEGORY_FIELDS
        )
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in fields):
            raise UserError("각 고장 유형에 대분류·상세설비·세부 부품·소분류를 모두 입력하세요.")
        member = {key: item[key].strip() for key in fields}
        for key in (
            "rule_id",
            "evidence",
            "schema",
            "part_key",
            "part_group",
            "part_type",
            "symptom_evidence",
            "detail_equipment_source",
            "detail_equipment_evidence",
            "legacy_schema",
            "selection_method",
            "selection_basis",
        ):
            if isinstance(item.get(key), str) and item[key].strip():
                member[key] = item[key].strip()
        selected_rank = item.get("selected_rank")
        if (
            isinstance(selected_rank, int)
            and not isinstance(selected_rank, bool)
            and selected_rank > 0
        ):
            member["selected_rank"] = selected_rank
        for list_field in ("actions", "observed_symptoms"):
            if not isinstance(item.get(list_field), list):
                continue
            member[list_field] = list(
                dict.fromkeys(
                    action.strip()
                    for action in item[list_field]
                    if isinstance(action, str) and action.strip()
                )
            )
        legacy = item.get("legacy_category")
        if isinstance(legacy, dict) and all(
            isinstance(legacy.get(key), str) for key in PART_CATEGORY_FIELDS
        ):
            member["legacy_category"] = {key: legacy[key] for key in PART_CATEGORY_FIELDS}
        category = tuple(member.get(key, "") for key in CATEGORY_FIELDS)
        previous = unique.get(category)

        def evidence_key(value):
            return (
                len(value.get("evidence", "")),
                value.get("evidence", ""),
                value.get("rule_id", ""),
            )

        if previous is None or evidence_key(member) > evidence_key(previous):
            unique[category] = member
    return [unique[key] for key in sorted(unique)]


def parse_components(value: Any, strict: bool = False) -> list[dict]:
    """Read structured event members; strict is used for saved manual input."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return []
        if isinstance(value, str):
            value = json.loads(value)
        return canonical_components(value)
    except (TypeError, ValueError, UserError) as exc:
        if strict:
            if isinstance(exc, UserError):
                raise
            raise UserError("복수 고장 유형의 저장 형식을 확인하세요.") from exc
        return []


def component_payload(components: list[dict], mode: str = "single") -> dict:
    """Attach typed members without counting them as separate downtime records."""
    members = canonical_components(components)
    labels = [type_label(member) for member in members]
    categories = [[member.get(key, "") for key in CATEGORY_FIELDS] for member in members]
    key = ""
    if len(members) > 1:
        identity = json.dumps(categories, ensure_ascii=False, separators=(",", ":"))
        key = "MULTI:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return {
        "classification_mode": mode,
        "component_count": len(members),
        "part_count": len(
            {
                part_key(member["major"], member["middle"], member.get("detail_equipment", ""))
                if member.get("schema") == CLASSIFICATION_SCHEMA
                else type_label(member)
                for member in members
                if member["middle"]
                not in (UNKNOWN_PART, "제품·자재", "제품 걸림·막힘", "제품 낙하", "자재 불량")
            }
        ),
        "component_types": "\n".join(labels),
        "component_details": json.dumps(members, ensure_ascii=False, separators=(",", ":")),
        "combination_key": key,
        "part_group": part_group(members[0]["middle"]) if len(members) == 1 else "",
    }


def combination_category(components: list[dict]) -> dict[str, str]:
    """Use complete type names so distinct combinations remain distinct groups."""
    members = canonical_components(components)
    if len(members) < 2:
        raise UserError("복수 유형을 확정하려면 서로 다른 유형을 2개 이상 입력하세요.")
    return {
        "major": "복수 고장",
        "middle": f"{len(members)}개 유형 조합",
        "minor": " + ".join(type_label(member) for member in members),
    }


def mode_label(value: str) -> str:
    """Present the internal mode without exposing enum names to end users."""
    return {
        "single": "단일 유형",
        "multiple": "복수 유형 조합",
        "ambiguous": "유형 검토 중",
        "unclassified": "유형 없음",
        "nonfault": "분류대상 외",
    }.get(value, value)


def component_evidence_text(value: Any) -> str:
    """Readable evidence for controls; the structured source remains unchanged."""
    lines = []
    for index, member in enumerate(parse_components(value), 1):
        lines.append(f"{index}. {type_label(member)}")
        if member.get("evidence"):
            lines.append("근거: " + member["evidence"])
    return "\n".join(lines)
