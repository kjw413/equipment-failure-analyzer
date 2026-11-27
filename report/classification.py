"""Rule decisions and component evidence in report-only presentation snapshots."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace

import pandas as pd

from core.aggregation import grouped, trend
from core.classification_policy import unresolved_classifications
from core.component_analysis import detailed_equipment_table
from core.failure_modes import LEGACY_CLASSIFICATION_SCHEMAS, UNKNOWN_EQUIPMENT
from core.fault_components import CATEGORY_FIELDS, component_payload, parse_components, type_label
from core.i18n import UNMATCHED, K
from core.known_classification import KNOWN_FIELDS, known_fields
from core.models import CLASSIFICATION_COMPONENT_COLUMNS, CLASSIFICATION_DECISION_COLUMNS
from core.parsing import text
from core.public_taxonomy import part_group
from core.report_view import report_result
from core.sorting import descending

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
        "설비별 이력은 라인·상세설비까지 집계합니다. 한 고장이력은 하나의 최종 분류를 가지며 고장 분야·상세설비·고장 현상을 표시합니다. 조치는 별도로 기록합니다.",
        "상세설비는 고장·조치 근거가 붙은 원문과 비가동코드(중)를 확인해 표준화합니다. 근거가 없으면 상세설비 미상으로 보존하며, 등록 설비명만으로 실제 고장 설비를 추정하지 않습니다.",
        "고장 분야·상세설비·고장 현상은 독립적으로 선택합니다.",
        "분류 규칙의 부품·문맥·증상 조건과 원문이 일치하는지 확인하고 판정 사유와 후보별 근거를 기록합니다.",
        "명확한 단일 고장을 먼저 선택하고, 남은 복수 부품·현상·설비 후보는 원문 고장 또는 완료 조치 근거가 있는 1순위를 이력 대표로 자동 선택합니다. 의심·대안, 미등록 다른 물리 고장, 불명확한 공동주어, 같은 명사의 동률 상충 규칙, 부품명만 있는 기록은 검토합니다. 조치로 고장 현상을 추정하지 않으며 현상이 없으면 '현상 미기재'로 보존합니다.",
        "1순위 대표 자동선택은 분류 근거를 기준으로 이력당 한 건을 정합니다. 미확정 후보는 별도로 보존하며 이력 건수와 정지시간은 기록당 한 번 집계합니다.",
        "완전 자동분류는 세 분류 항목이 모두 확인된 기록입니다. 부분 자동분류는 단일 대상을 확인했지만 일부 분류축이 미기재인 기록입니다. 자동처리는 두 항목의 합이며, 검토 대상(중복 제외)은 충돌·미일치·시간/일자 등 품질 확인이 필요한 기록입니다. 각 숫자를 별도로 표시합니다.",
        "차단기 '떨어짐'은 보호장치 동작으로 분류합니다. 낙하나 과부하를 임의로 추정하지 않습니다. 손상·파손은 통합하고 마모·부식은 구별합니다.",
        "수동확정은 사용자가 선택한 유형을 보존합니다. 규칙과 일치하는 후보가 없으면 비가동코드(중·소)가 비어 있을 때 '비가동코드 미기입', 입력돼 있을 때 '규칙 미일치'로 남깁니다.",
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
            if "classification_candidates" not in value:
                value["classification_candidates"] = "[]"
            else:
                value["classification_candidates"] = value["classification_candidates"].map(
                    _components_without_legacy_fields
                )
            for index, record in value.to_dict("index").items():
                members = parse_components(record.get("component_details"))
                previous_axes = record.get(
                    "classification_schema"
                ) in LEGACY_CLASSIFICATION_SCHEMAS or any(
                    member.get("schema") in LEGACY_CLASSIFICATION_SCHEMAS for member in members
                )
                pending = (
                    previous_axes
                    or len(members) > 1
                    or record.get("classification_mode") in ("multiple", "ambiguous")
                    or record.get("status") in (K["review"], K["manual_multi"])
                )
                if not pending:
                    if len(members) == 1 and members[0].get("detail_equipment"):
                        label = type_label(members[0])
                        value.at[index, "type"] = label
                        value.at[index, "component_types"] = label
                    continue
                candidates = record.get("classification_candidates")
                try:
                    candidates = (
                        json.loads(candidates) if isinstance(candidates, str) else candidates
                    )
                except (TypeError, ValueError):
                    candidates = []
                candidates = candidates if isinstance(candidates, list) else []
                if not candidates:
                    candidates = members
                value.at[index, "classification_candidates"] = json.dumps(
                    candidates, ensure_ascii=False, separators=(",", ":")
                )
                for field, field_value in component_payload([], "ambiguous").items():
                    if field != "repair_actions":
                        value.at[index, field] = field_value
                value.at[index, "status"] = K["review"]
                retained = known_fields(record) if not previous_axes and not members else {}
                for field in CATEGORY_FIELDS:
                    value.at[index, field] = retained.get(field, "")
                if not retained:
                    value.at[index, KNOWN_FIELDS] = ""
                value.at[index, "type"] = K["review"]
                if previous_axes:
                    value.at[index, "classification_reason"] = (
                        "이전 분류를 후보로 보존했습니다. 고장 분야·상세설비·고장 현상을 새 기준으로 다시 확인하세요. 조치는 별도로 보존합니다."
                    )
                if members:
                    candidate_text = "\n".join(
                        f"{number}. {type_label(member)}"
                        + (" | " + str(member.get("evidence")) if member.get("evidence") else "")
                        for number, member in enumerate(members, 1)
                    )
                    previous = text(record.get("candidate_evidence"))
                    value.at[index, "candidate_evidence"] = "\n".join(
                        item for item in (previous, candidate_text) if item
                    )
                if len(members) > 1 or record.get("status") == K["manual_multi"]:
                    value.at[index, "classification_reason"] = (
                        "이전 복수 분류를 검토 후보로 보존했습니다. 원문과 후보 근거를 확인하여 최종 분류 하나를 선택하세요."
                    )
        for field, fallback in (
            ("classification_reason", "evidence"),
            ("candidate_evidence", "candidates"),
        ):
            if field not in value and fallback in value:
                value[field] = value[fallback]
        if legacy is not None and legacy.any():
            value.loc[legacy, "classification_reason"] = LEGACY_REASON
        if "status" in value:
            unresolved = value.status.isin([*UNMATCHED, K["review"], K["manual_multi"]])
            retained = {
                index: known_fields(record) for index, record in value.to_dict("index").items()
            }
            for field in CATEGORY_FIELDS:
                if field in value:
                    value.loc[unresolved, field] = ""
            for index in value.index[unresolved]:
                for field, field_value in retained[index].items():
                    value.at[index, field] = field_value
            if "part_group" in value:
                value.loc[unresolved, "part_group"] = ""
                for index in value.index[unresolved]:
                    value.at[index, "part_group"] = part_group(retained[index].get("middle", ""))
            if "type" in value:
                value.loc[unresolved, "type"] = K["review"]
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
    metrics["unresolved_classification_rows"] = len(unresolved_classifications(selected))
    tables = {
        key: frame(table)
        for key, table in projected.tables.items()
        if key not in ("component", "component_trend", "fault_detail")
    }
    tables["detailed_equipment"] = detailed_equipment_table(selected)
    if "component_details" in selected:
        # A caller may pass an older saved result directly to a low-level exporter.
        # Rebuild its classifications so stale multiple-member tables cannot leak
        # into the review workbook or charts.
        for key, keys in {
            "equipment": ["equipment"],
            "line": ["line"],
            "product": ["product"],
            "type": ["type"],
            "equipment_type": ["equipment", "type"],
            "product_type": ["product", "type"],
            "equipment_product": ["equipment", "product"],
            "triple": ["equipment", "product", "type"],
        }.items():
            if key in tables:
                source = selected
                if key == "product" and not metrics.get("product_count"):
                    source = selected.iloc[:0]
                tables[key] = grouped(source, keys)
        for freq in ("day", "week", "month", "year"):
            if "trend_" + freq in tables:
                tables["trend_" + freq] = trend(selected, freq)
        if "long_stops" in tables:
            tables["long_stops"] = descending(selected, "minutes").head(projected.options.top_n)
        if "review" in tables:
            previous_ids = set(tables["review"].get("record_id", []))
            mask = selected.record_id.isin(previous_ids) | selected.status.eq(K["review"])
            tables["review"] = descending(selected.loc[mask], "minutes")
            metrics["review_rows"] = int(mask.sum())
        if "combination" in tables:
            tables["combination"] = grouped(selected.iloc[:0], ["type"])
        metrics["auto_rows"] = int(selected.status.eq(K["auto"]).sum())
        metrics["partial_rows"] = int(selected.status.eq(K.get("partial", "부분분류")).sum())
        metrics["auto_processed_rows"] = metrics["auto_rows"] + metrics["partial_rows"]
        metrics["manual_rows"] = int(selected.status.eq(K["manual"]).sum())
        metrics["classification_review_rows"] = int(selected.status.eq(K["review"]).sum())
        metrics["missing_detail_equipment_rows"] = int(
            selected.get("detail_equipment", pd.Series("", index=selected.index))
            .eq(UNKNOWN_EQUIPMENT)
            .sum()
        )
        metrics["manual_multi_rows"] = metrics["combination_rows"] = 0
    legacy_count = int(selected["status"].eq(LEGACY_STATUS).sum()) if "status" in selected else 0
    if legacy_count:
        metrics["legacy_classification_rows"] = legacy_count
        metrics["auto_rows"] = int(selected["status"].eq(K["auto"]).sum())
        metrics.pop("auto_resolved_rows", None)
    return replace(
        projected,
        all_records=frame(projected.all_records),
        selected=selected,
        tables=tables,
        notes=[
            note
            for note in projected.notes
            if not _LEGACY_TEXT.search(note)
            and not any(
                phrase in note
                for phrase in (
                    "복수 유형 조합",
                    "중복을 허용",
                    "잠정검토 포함",
                    "세부 부품",
                    "부품군",
                )
            )
        ],
        metrics=metrics,
        config_snapshot=snapshot,
    )


def classification_review_count(result) -> int:
    """Classification review excludes unrelated time/date quality warnings."""
    if "status" not in result.selected:
        return 0
    return int(result.selected["status"].eq(K["review"]).sum())
