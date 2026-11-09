"""Shared review categories and persisted Excel highlight colors."""

from __future__ import annotations

import re
from collections.abc import Mapping

from core.i18n import K
from core.models import UserError

# Order is also the priority when one source record has several review reasons.
REVIEW_TYPES = (
    ("multi_match", "복수검토", "#FFE699"),
    ("unmatched_rule", "규칙 미일치", "#F4CCCC"),
    ("missing_code", "비가동코드 미기입", "#FFF2CC"),
    ("other", "기타", "#E7E6E6"),
)


def normalized_review_colors(value=None) -> dict[str, str]:
    """Fill missing/invalid saved entries with defaults for older profiles."""
    saved = value if isinstance(value, Mapping) else {}
    colors = {}
    for key, _label, default in REVIEW_TYPES:
        color = saved.get(key)
        colors[key] = (
            color.upper()
            if isinstance(color, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", color)
            else default
        )
    return colors


def validate_review_colors(value) -> dict[str, str]:
    """Reject invalid edits before writing settings, accepting partial updates."""
    if not isinstance(value, Mapping):
        raise UserError("검토필요 색상 설정은 유형별 색상이어야 합니다.")
    labels = {key: label for key, label, _color in REVIEW_TYPES}
    for key, color in value.items():
        if key not in labels:
            raise UserError(f"알 수 없는 검토필요 유형: {key}")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise UserError(f"{labels[key]}: 색상은 #RRGGBB 형식으로 지정하세요.")
    return {key: color.upper() for key, color in value.items()}


def review_types(record, target_review: bool = True) -> tuple[str, ...]:
    """Map current classification/quality flags to color keys, in priority order."""
    flags = str(record.get("issues", "") or "")
    issues = {part.strip() for part in flags.split(" | ") if part.strip()}
    status = record.get("status", "")
    found = set()
    if status == K["review"]:
        found.add("multi_match")
    elif status == K["code_missing"]:
        found.add("missing_code")
    elif status == K["rule_unmatched"]:
        found.add("unmatched_rule")
    for issue in (
        "date_invalid",
        "time_invalid",
        "time_missing",
        "time_negative",
        "time_diff",
    ):
        if K[issue] in issues:
            found.add("other")
    if target_review and K["target_missing"] in issues:
        found.add("other")
    return tuple(key for key, _label, _color in REVIEW_TYPES if key in found)
