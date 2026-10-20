"""Canonical fault-type members and stable labels for one downtime record.

Members describe types linked to an event; they never duplicate its downtime.
Alternative interpretations of one part must not be supplied as separate members.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.models import UserError

CATEGORY_FIELDS = ("major", "middle", "minor")
COMPONENT_OVERRIDE = "classification_components"


def type_label(component: dict) -> str:
    return " / ".join(str(component[key]).strip() for key in CATEGORY_FIELDS)


def canonical_components(components: list[dict]) -> list[dict]:
    """One evidence entry per complete type, in input-order-independent order."""
    if not isinstance(components, list):
        raise UserError("고장 유형 목록은 배열이어야 합니다.")
    unique: dict[tuple[str, ...], dict] = {}
    for item in components:
        if not isinstance(item, dict):
            raise UserError("각 고장 유형에 대·중·소분류를 입력하세요.")
        if any(
            not isinstance(item.get(key), str) or not item[key].strip() for key in CATEGORY_FIELDS
        ):
            raise UserError("각 고장 유형에 대·중·소분류를 모두 입력하세요.")
        member = {key: item[key].strip() for key in CATEGORY_FIELDS}
        for key in ("rule_id", "evidence"):
            if isinstance(item.get(key), str) and item[key].strip():
                member[key] = item[key].strip()
        category = tuple(member[key] for key in CATEGORY_FIELDS)
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
    categories = [[member[key] for key in CATEGORY_FIELDS] for member in members]
    key = ""
    if len(members) > 1:
        identity = json.dumps(categories, ensure_ascii=False, separators=(",", ":"))
        key = "MULTI:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return {
        "classification_mode": mode,
        "component_count": len(members),
        "component_types": "\n".join(labels),
        "component_details": json.dumps(members, ensure_ascii=False, separators=(",", ":")),
        "combination_key": key,
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
        "unclassified": "미분류",
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
