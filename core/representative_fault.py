"""Choose one directly stated fault without treating every repair as a fault."""

from core.failure_modes import UNKNOWN_EQUIPMENT, UNKNOWN_PART

DIRECT_FAILURE_MODES = frozenset(
    {
        "손상·파손",
        "마모",
        "부식",
        "변형",
        "이탈·풀림",
        "누설",
        "막힘·걸림",
        "단선",
        "소손·단락",
        "보호장치 동작",
        "과부하·과전류",
        "감지불량",
        "통신·입출력 이상",
        "소음·진동",
        "위치·설정이상",
        "오염",
        "낙하",
        "고장·이상",
    }
)


def choose_direct_fault(members: list[dict], *, blocked: bool = False) -> dict | None:
    """Promote only a unique, observed physical fault over repair-only mentions.

    Location/stop/temperature statements cannot establish a replacement part's
    failure. Callers separately guard alternatives, independent work and causes.
    """
    if blocked:
        return None
    direct = [
        member
        for member in members
        if member.get("_observed_failure")
        and member.get("minor") in DIRECT_FAILURE_MODES
        and member.get("middle") not in (UNKNOWN_PART, "제품·자재")
    ]
    paths = {
        tuple(member.get(key) for key in ("major", "detail_equipment", "middle", "minor"))
        for member in direct
    }
    if len(paths) != 1:
        return None
    chosen = direct[0]
    identity = (chosen.get("detail_equipment"), chosen.get("middle"))
    known_equipment = {
        member.get("detail_equipment")
        for member in members
        if member.get("detail_equipment") not in (None, "", UNKNOWN_EQUIPMENT)
    }
    if len(known_equipment) > 1:
        return None
    for member in members:
        if (member.get("detail_equipment"), member.get("middle")) == identity:
            continue
        if member.get("_observed_failure"):
            return None
        if not member.get("actions"):
            return None
    return chosen
