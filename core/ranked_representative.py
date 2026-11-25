"""Choose the approved first-ranked event representative from its raw evidence."""

from __future__ import annotations

from collections.abc import Mapping

from core.failure_modes import UNKNOWN_EQUIPMENT
from core.fault_components import CATEGORY_FIELDS
from core.public_taxonomy import REPAIR_ACTIONS

MATCH_FIELDS = (*CATEGORY_FIELDS, "rule_id", "evidence")


def _identity(candidate: Mapping) -> tuple[str, ...]:
    return tuple(str(candidate.get(key) or "").strip() for key in MATCH_FIELDS)


def _order(candidate: Mapping, position: int) -> tuple:
    order = candidate.get("_order")
    if isinstance(order, (tuple, list)):
        return tuple(order)
    ordinal = candidate.get("rank")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal <= 0:
        ordinal = position + 1
    return (ordinal,)


def choose_ranked_representative(
    ranked_candidates: list[dict], raw_candidates: list[dict], *, blocked: bool = False
) -> dict | None:
    """Return only rank 1 when its current raw evidence supports classification.

    Different observed parts may tie: the result represents this event and does
    not claim to be its only failure or its confirmed root cause. Equal-priority
    interpretations of the same noun span remain unresolved. Callers enforce
    uncertainty, alternatives and unrecognized independent-fault guards.
    """
    if blocked or not ranked_candidates or not raw_candidates:
        return None
    first = ranked_candidates[0]
    if not isinstance(first, Mapping) or any(not first.get(key) for key in CATEGORY_FIELDS):
        return None
    ordinal = first.get("rank", 1)
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal != 1:
        return None
    matches = [
        (position, raw)
        for position, raw in enumerate(raw_candidates)
        if isinstance(raw, Mapping) and _identity(raw) == _identity(first)
    ]
    if not matches:
        return None
    position, chosen = min(matches, key=lambda item: (_order(item[1], item[0]), item[0]))
    actions = chosen.get("actions")
    completed_work = isinstance(actions, (tuple, list)) and any(
        action in REPAIR_ACTIONS for action in actions if isinstance(action, str)
    )
    if chosen.get("_observed_failure") is not True and not completed_work:
        return None

    span = chosen.get("_span")
    if isinstance(span, (tuple, list)) and len(span) == 3:
        same_span = [
            raw
            for raw in raw_candidates
            if isinstance(raw, Mapping)
            and isinstance(raw.get("_span"), (tuple, list))
            and tuple(raw["_span"]) == tuple(span)
            and isinstance(raw.get("_priority"), int)
            and not isinstance(raw["_priority"], bool)
        ]
        if same_span:
            highest = max(raw["_priority"] for raw in same_span)
            strongest = [raw for raw in same_span if raw["_priority"] == highest]
            parts = {str(raw.get("middle") or "").strip() for raw in strongest}
            # A compound MES location label is contextual evidence. Competing
            # locations stated for the same fault in the description are ambiguous.
            locations = {
                raw["detail_equipment"]
                for raw in strongest
                if raw.get("detail_equipment") not in (None, "", UNKNOWN_EQUIPMENT)
                and raw.get("detail_equipment_source", "").startswith("원문")
            }
            domains_by_mode = {}
            for raw in strongest:
                domains_by_mode.setdefault(raw.get("minor"), set()).add(raw.get("major"))
            if (
                len(parts) > 1
                or len(locations) > 1
                or any(len(domains) > 1 for domains in domains_by_mode.values())
            ):
                return None

    return {**chosen, "selection_method": "top_ranked_representative", "selected_rank": 1}
