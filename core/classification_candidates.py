"""Ordered human-review recommendations, separate from final event members."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from core.failure_modes import UNKNOWN_EQUIPMENT
from core.fault_components import CATEGORY_FIELDS, PART_CATEGORY_FIELDS
from core.models import UserError


def rank_candidates(candidates: Iterable[Mapping]) -> list[dict]:
    """Deduplicate paths and retain evidence order; ranks are never probabilities.

    Extractors may supply a private ``_order`` tuple of evidence precedence.
    Saved recommendations use positive ordinal ranks; unranked legacy selections
    retain their input order. Private fields never appear in returned candidates.
    """
    prepared = []
    for position, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping) or any(
            not isinstance(candidate.get(key), str) or not candidate[key].strip()
            for key in PART_CATEGORY_FIELDS
        ):
            raise UserError("각 추천 후보에 분야·부품·증상을 모두 입력하세요.")
        item = {key: candidate[key].strip() for key in PART_CATEGORY_FIELDS}
        item["detail_equipment"] = str(
            candidate.get("detail_equipment") or UNKNOWN_EQUIPMENT
        ).strip()
        for key in ("reason", "evidence", "rule_id"):
            item[key] = str(candidate.get(key) or "").strip()
        for key in (
            "schema",
            "detail_equipment_source",
            "detail_equipment_evidence",
            "part_group",
            "part_type",
            "symptom_evidence",
            "legacy_schema",
        ):
            if candidate.get(key):
                item[key] = str(candidate[key]).strip()
        if isinstance(candidate.get("legacy_category"), dict):
            item["legacy_category"] = dict(candidate["legacy_category"])
        actions = candidate.get("actions")
        if isinstance(actions, list):
            item["actions"] = list(
                dict.fromkeys(
                    value.strip() for value in actions if isinstance(value, str) and value.strip()
                )
            )
        ordinal = candidate.get("rank")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal <= 0:
            ordinal = position + 1
        order = candidate.get("_order")
        prepared.append(
            (tuple(order) if isinstance(order, (tuple, list)) else (ordinal,), position, item)
        )
    prepared.sort(key=lambda value: (value[0], value[1]))
    ranked = []
    seen = set()
    for _, _, item in prepared:
        identity = tuple(item[key] for key in CATEGORY_FIELDS)
        if identity in seen:
            continue
        seen.add(identity)
        ranked.append({**item, "rank": len(ranked) + 1})
    return ranked


def parse_candidates(value, strict: bool = False) -> list[dict]:
    """Read recommendation JSON without treating any candidate as a final choice."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return []
        decoded = json.loads(value) if isinstance(value, str) else value
        if not isinstance(decoded, list):
            raise UserError("추천 후보 목록은 배열이어야 합니다.")
        return rank_candidates(decoded)
    except (TypeError, ValueError, UserError) as exc:
        if strict:
            if isinstance(exc, UserError):
                raise
            raise UserError("추천 후보의 저장 형식을 확인하세요.") from exc
        return []
