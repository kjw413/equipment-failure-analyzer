"""Independent audit comparison: coverage is not classification accuracy."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/compare_review_stages.py"
SPEC = importlib.util.spec_from_file_location("compare_review_stages", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def record(event="one", **updates):
    value = {
        "event_id": event,
        "record_id": f"file:sheet:{event}",
        "source_row": 8,
        "source_sheet": "Events",
        "source_raw": {"비고": "베어링 교체", "_row": 8},
        "raw_description": "베어링 교체",
        "normalized": "베어링 교체",
        "minutes": 12.0,
        "kind": "고장",
        "status": "검토필요",
        "major": "",
        "detail_equipment": "",
        "middle": "",
        "minor": "",
        "classification_candidates": "[]",
        "component_details": "[]",
        "review_code": "symptom_missing",
        "evidence": "베어링, 교체",
    }
    value.update(updates)
    return value


def selected(**updates):
    return record(
        status="부분분류",
        major="기계",
        detail_equipment="컨베어",
        middle="베어링(종류 미상)",
        minor="현상 미기재",
        **updates,
    )


def test_old_auto_is_reexpressed_under_same_axis_completeness():
    legacy = selected()
    legacy["status"] = "규칙분류"
    assert audit.bucket(legacy) == "partial_auto"
    legacy["minor"] = "손상·파손"
    assert audit.bucket(legacy) == "complete_auto"
    legacy["detail_equipment"] = "상세설비 미상"
    assert audit.bucket(legacy) == "partial_auto"


def test_review_unmatched_and_partial_never_merge():
    rows = [record(), record("two", status="규칙 미일치"), selected(event="three")]
    assert audit.counts(rows) == {
        "complete_auto": 0,
        "partial_auto": 1,
        "review": 1,
        "unmatched": 1,
        "manual": 0,
        "nonfault": 0,
        "other": 0,
    }
    pending = selected()
    pending["status"] = "검토필요"
    assert audit.bucket(pending) == "review"


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_description", "베어링 손상"),
        ("source_row", 9),
        ("record_id", "different"),
        ("minutes", 15),
        ("source_raw", {"비고": "changed"}),
    ],
)
def test_source_change_stops_comparison(field, value):
    before, after = record(), selected()
    after[field] = value
    with pytest.raises(ValueError, match="immutable_fields_preserved"):
        audit.comparison([before], [after])


def test_event_id_drop_or_duplicate_cannot_hide_changed_records():
    with pytest.raises(ValueError, match="event_id must be populated and unique"):
        audit.comparison([record(), record()], [selected()])
    with pytest.raises(ValueError, match="event_id_set_preserved"):
        audit.comparison([record()], [selected(event="different")])


def test_changed_and_promoted_rows_keep_complete_source_trace_and_candidates():
    before = record(
        classification_candidates=json.dumps(
            [
                {
                    "major": "분야 미상",
                    "middle": "베어링(종류 미상)",
                    "minor": "현상 미기재",
                    "actions": ["교체"],
                    "evidence": "베어링, 교체",
                    "custom_evidence": "must remain",
                }
            ],
            ensure_ascii=False,
        )
    )
    after = selected(
        classification_candidates=before["classification_candidates"],
        repair_actions="교체",
        classifier_trace={"raw": {"evidence": "original trace"}},
    )
    summary, changes, promotions = audit.comparison([before], [after])
    assert summary["promoted_rows"] == 1
    assert changes == promotions
    assert promotions[0]["before_record"] == before
    assert promotions[0]["after_record"] == after
    assert promotions[0]["after_known_axes"]["minor"] == {"value": "현상 미기재", "known": False}
    assert promotions[0]["evidence_screen"]["screen_is_accuracy_measure"] is False


def test_only_auto_processing_transitions_count_as_promotions():
    assert audit.is_promotion(record(), selected())
    before, after = selected(), selected()
    after["status"], after["minor"] = "규칙분류", "고장·이상"
    assert audit.is_promotion(before, after)
    assert not audit.is_promotion(record(status="규칙 미일치"), record())
    assert not audit.is_promotion(before, before)


def test_new_empty_annotation_column_does_not_mark_every_row_changed():
    before = record()
    after = deepcopy(before)
    after["classification_missing_fields"] = ""
    summary, changes, promotions = audit.comparison([before], [after])
    assert summary["changed_rows"] == 0
    assert changes == promotions == []


def test_comparison_output_names_never_collide_with_audit_names(tmp_path):
    paths = audit.output_paths(tmp_path, "stage1_recognition")
    assert paths["summary"] == tmp_path / "stage1_recognition_comparison_summary.json"
    assert tmp_path / "stage1_recognition_summary.json" not in paths.values()
    assert tmp_path / "stage1_recognition_records.json" not in paths.values()


def test_literal_screen_detects_invented_symptom_and_planned_action():
    row = selected(repair_actions="교체")
    row["raw_description"] = row["normalized"] = "베어링 정상, 추후 교체 예정"
    row["minor"] = "소손·단락"
    row["component_details"] = json.dumps(
        [{"middle": "베어링(종류 미상)", "minor": "소손·단락", "symptom_evidence": "소손"}],
        ensure_ascii=False,
    )
    screen = audit.evidence_screen(row)
    assert "symptom_evidence_token_absent_from_raw_and_normalized" in screen["flags"]
    assert "no_literal_failure_or_unqualified_action_found" in screen["flags"]
    assert screen["action_mentions"][0]["has_risk_word_nearby"]


def test_cooling_water_leak_does_not_count_as_repair_action():
    row = selected()
    row["raw_description"] = row["normalized"] = "냉각수리크"
    screen = audit.evidence_screen(row)
    assert screen["action_mentions"] == []
    assert screen["explicit_failure_word_seen"]


def test_summary_source_sha_and_code_snapshot_fail_closed():
    summary = {
        "source_sha256_before": "original",
        "source_sha256_after": "original",
        "checks": {"source_bytes_unchanged": True, "code_and_config_unchanged_during_run": True},
    }
    other = deepcopy(summary)
    other["checks"]["code_and_config_unchanged_during_run"] = False
    with pytest.raises(ValueError, match="after_audit_checks_pass"):
        audit.comparison([record()], [selected()], summary, other)
    other = deepcopy(summary)
    other["source_sha256_before"] = other["source_sha256_after"] = "different"
    with pytest.raises(ValueError, match="same_source_sha256"):
        audit.comparison([record()], [selected()], summary, other)


def test_markdown_contains_every_promotion_and_does_not_claim_accuracy():
    summary, _, promotions = audit.comparison([record()], [selected()])
    document = audit.markdown(summary, promotions, "stage1")
    assert "원본 8행" in document and "베어링 교체" in document
    assert "정확도 측정 결과가 아닙니다" in document
    assert "이전 후보" in document and "이후 후보" in document
