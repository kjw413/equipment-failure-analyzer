"""Rule decisions and component evidence in report-only presentation snapshots."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace

from core.i18n import K
from core.models import CLASSIFICATION_COMPONENT_COLUMNS, CLASSIFICATION_DECISION_COLUMNS
from core.parsing import text
from core.report_view import report_result

COMPONENT_FIELDS = CLASSIFICATION_COMPONENT_COLUMNS
DECISION_FIELDS = CLASSIFICATION_DECISION_COLUMNS
LEGACY_STATUS = "이전 분석결과"
LEGACY_REASON = "이전 분석결과입니다. 현재 규칙으로 재분석해야 판정 사유를 확인할 수 있습니다."

# Earlier saved analysis objects may still contain these fields. They are never
# displayed, converted into rule decisions, or used to classify an event.
LEGACY_SCORE_FIELDS = (
    "match_score",
    "runner_up_score",
    "score_margin",
    "score_evidence",
    "candidate_scores",
    "score_reason",
)
_LEGACY_TEXT = re.compile(r"점수|격차|저점수|접전|\bscore\b", re.IGNORECASE)


def classification_principles() -> list[str]:
    return [
        "분류 규칙의 부품·문맥·증상 조건과 원문이 일치하는지 확인하고 판정 사유와 후보별 근거를 기록합니다.",
        "하나의 유형으로 결정하기 어려운 복수 후보, 독립된 복수 고장, 대안 유형은 원문과 규칙 근거를 확인하여 확정합니다.",
        "수동확정은 사용자가 선택한 유형을 보존합니다. 규칙과 일치하는 후보가 없으면 미분류로 남깁니다.",
    ]


def component_principles() -> list[str]:
    return [
        "조합별 유형과 설비별 유형순위는 하나의 고장기록을 사건 1회·정지시간 1회로 집계합니다. 복수유형의 정지시간을 각 부품에 나누거나 반복 합산하지 않습니다.",
        "부품별 발생 건수는 해당 유형이 포함된 고장기록 수입니다. 비율의 분모는 선택한 전체 고장기록이며, 월별 표에서는 해당 월 전체 고장기록입니다. 한 사건에 여러 유형이 포함될 수 있어 비율 합계는 100%를 초과할 수 있습니다.",
        "부품별 사용자확정 건수와 잠정 검토 건수를 구분합니다. 검토필요 유형은 확정된 부품 고장이 아니며 원문과 후보 근거를 확인해야 합니다.",
        "'또는'·'혹은' 등 대안 유형은 실제 동시고장 구성원이 아닙니다. 대안 후보의 규칙 근거와 원문을 비교해 유형을 확정하며, 서로 대안인 유형들을 동시에 구성원으로 합산하지 않습니다.",
    ]


def evidence_excerpt(value, limit: int) -> str:
    """Bound PDF excerpts; the Excel detail keeps complete rule evidence."""
    value = text(value)
    return value if len(value) <= limit else value[:limit] + " [이하 Excel 참조]"


def _rule_text(value):
    if not isinstance(value, str) or not _LEGACY_TEXT.search(value):
        return value
    # Keep the original rule/part evidence before the obsolete annotation.
    prefix = re.split(r"\s*\|\s*(?:근거\s*점수|자동선택:)", value, maxsplit=1)[0]
    return "" if _LEGACY_TEXT.search(prefix) else prefix.strip()


def _components_without_legacy_fields(value):
    if not isinstance(value, str) or not value:
        return value
    try:
        members = json.loads(value)
    except (TypeError, ValueError):
        return value
    if not isinstance(members, list):
        return value
    cleaned = []
    for member in members:
        if not isinstance(member, dict):
            cleaned.append(member)
            continue
        item = {key: val for key, val in member.items() if key != "score"}
        if "evidence" in item:
            item["evidence"] = _rule_text(item["evidence"])
        cleaned.append(item)
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def classification_result(result):
    """Project current or older results without changing analysis/source objects."""
    projected = report_result(result)

    def frame(value):
        value = value.drop(columns=list(LEGACY_SCORE_FIELDS), errors="ignore").copy(deep=True)
        legacy = value["status"].eq("점수분류") if "status" in value else None
        if legacy is not None:
            value.loc[legacy, "status"] = LEGACY_STATUS
        for field in (
            "evidence",
            "classification_reason",
            "candidate_evidence",
            "review_reason",
            "review_action",
            "aggregation_effect",
        ):
            if field in value:
                value[field] = value[field].map(_rule_text)
        if "component_details" in value:
            value["component_details"] = value["component_details"].map(
                _components_without_legacy_fields
            )
        for field, fallback in (
            ("classification_reason", "evidence"),
            ("candidate_evidence", "candidates"),
        ):
            if field not in value and fallback in value:
                value[field] = value[fallback]
        if legacy is not None and legacy.any():
            value.loc[legacy, "classification_reason"] = LEGACY_REASON
        return value

    snapshot = copy.deepcopy(projected.config_snapshot)
    classifier = snapshot.get("settings", {}).get("classifier", {})
    if isinstance(classifier, dict):
        classifier.pop("scoring", None)
    metrics = {
        key: value
        for key, value in projected.metrics.items()
        if key not in ("scoring_review_rows", "low_score_rows", "close_score_rows")
    }
    selected = frame(projected.selected)
    legacy_count = int(selected["status"].eq(LEGACY_STATUS).sum()) if "status" in selected else 0
    if legacy_count:
        metrics["legacy_classification_rows"] = legacy_count
        metrics["auto_rows"] = int(selected["status"].eq(K["auto"]).sum())
        metrics.pop("auto_resolved_rows", None)
    return replace(
        projected,
        all_records=frame(projected.all_records),
        selected=selected,
        tables={key: frame(table) for key, table in projected.tables.items()},
        notes=[note for note in projected.notes if not _LEGACY_TEXT.search(note)],
        metrics=metrics,
        config_snapshot=snapshot,
    )


def classification_review_count(result) -> int:
    """Classification review excludes unrelated time/date quality warnings."""
    if "status" not in result.selected:
        return 0
    return int(result.selected["status"].eq(K["review"]).sum())
