"""Part/symptom classification keeps event identity and downtime additive."""

import json
from pathlib import Path

import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.classification_candidates import parse_candidates
from core.classification_completeness import missing_fields
from core.failure_classification import FaultClassifier
from core.failure_modes import UNKNOWN_EQUIPMENT, UNKNOWN_SYMPTOM
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import K
from core.models import UserError
from core.parsing import prepare_text
from core.rules import read_rules

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "equipment_part_failure_v3"


@pytest.fixture(scope="module")
def classify_fault():
    normalization = json.loads((ROOT / "config/normalization.json").read_text("utf-8"))
    settings = json.loads((ROOT / "config/settings.json").read_text("utf-8"))["classifier"]
    classifier = FaultClassifier(read_rules(ROOT / "config/classification_config.xlsx"), settings)
    return lambda source: classifier.classify(prepare_text(source, normalization))


def classifications(result):
    return parse_components(result["component_details"], strict=True)


def pairs(result):
    return {(member["middle"], member["minor"]) for member in classifications(result)}


def recommendations(result):
    return parse_candidates(result["classification_candidates"], strict=True)


def recommendation_pairs(result):
    return {(member["middle"], member["minor"]) for member in recommendations(result)}


def assert_pending(result):
    assert result["status"] == K["review"]
    assert result["classification_mode"] == "ambiguous"
    assert result["part_count"] == result["component_count"] == 0
    assert classifications(result) == []
    assert all(result[key] == "" for key in ("major", "middle", "minor"))


def assert_partial(result, *missing):
    assert result["status"] == K["partial"]
    assert result["classification_mode"] == "single"
    assert result["component_count"] == len(classifications(result)) == 1
    assert result["classification_missing_fields"] == ", ".join(missing)
    assert result["review_code"] == ""


def assert_top_representative(result):
    candidates = recommendations(result)
    (member,) = classifications(result)
    expected = tuple(candidates[0][field] for field in CATEGORY_FIELDS)
    assert tuple(result[field] for field in CATEGORY_FIELDS) == expected
    assert tuple(member[field] for field in CATEGORY_FIELDS) == expected
    assert member["selection_method"] == "top_ranked_representative"
    assert member["selected_rank"] == candidates[0]["rank"] == 1
    assert member["rule_id"] == candidates[0]["rule_id"]
    assert member["evidence"] == candidates[0]["evidence"]
    assert result["status"] == (K["partial"] if missing_fields(result) else K["auto"])
    assert result["classification_mode"] == "single" and result.get("review_code", "") == ""
    assert result["component_count"] == result["part_count"] == 1


def test_shared_damage_keeps_every_part_candidate_and_selects_one_representative(classify_fault):
    result = classify_fault("실린더 및 베어링 손상")
    assert recommendation_pairs(result) == {
        ("실린더(종류 미상)", "손상·파손"),
        ("베어링(종류 미상)", "손상·파손"),
    }
    assert_top_representative(result)
    members = recommendations(result)
    assert {member["major"] for member in members} == {"공압·진공", "기계"}
    assert all("손상" in member["evidence"] for member in members)


def test_different_symptoms_are_bound_to_their_own_parts(classify_fault):
    result = classify_fault("실린더 누설 및 베어링 마모")
    assert recommendation_pairs(result) == {
        ("실린더(종류 미상)", "누설"),
        ("베어링(종류 미상)", "마모"),
    }
    assert_top_representative(result)
    assert ("실린더(종류 미상)", "마모") not in recommendation_pairs(result)
    assert ("베어링(종류 미상)", "누설") not in recommendation_pairs(result)


def test_several_symptoms_do_not_turn_one_part_into_several_parts(classify_fault):
    result = classify_fault("베어링 마모 및 파손")
    assert recommendation_pairs(result) == {
        ("베어링(종류 미상)", "마모"),
        ("베어링(종류 미상)", "손상·파손"),
    }
    assert_top_representative(result)
    assert result["minor"] == "마모"


def test_repeated_part_symptom_mentions_count_once_per_history(classify_fault):
    result = classify_fault("베어링 손상 / 베어링 손상으로 교체")
    assert pairs(result) == {("베어링(종류 미상)", "손상·파손")}
    assert result["part_count"] == result["component_count"] == 1


def test_single_and_multiple_events_use_the_same_part_symptom_axes(classify_fault):
    result = classify_fault("실린더 손상")
    assert (result["major"], result["middle"], result["minor"]) == (
        "공압·진공",
        "실린더(종류 미상)",
        "손상·파손",
    )
    assert pairs(result) == {("실린더(종류 미상)", "손상·파손")}
    assert result["part_count"] == result["component_count"] == 1


@pytest.mark.parametrize(
    "source, part, symptom",
    [
        ("타이밍벨트 끊어짐", "타이밍벨트", "손상·파손"),
        ("광전센서 단선", "광전센서", "단선"),
        ("모터 트립", "모터(종류 미상)", "보호장치 동작"),
    ],
)
def test_other_component_families_keep_their_explicit_kind_and_symptom(
    classify_fault, source, part, symptom
):
    result = classify_fault(source)
    assert pairs(result) == {(part, symptom)}
    assert result["middle"] == part and result["minor"] == symptom


def test_completed_replacement_keeps_known_part_and_missing_failure_as_partial(classify_fault):
    result = classify_fault("베어링 교체")
    assert_partial(result, "상세설비·모듈", "고장 현상")
    assert recommendation_pairs(result) == {("베어링(종류 미상)", "현상 미기재")}
    assert pairs(result) == {("베어링(종류 미상)", UNKNOWN_SYMPTOM)}
    assert result["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert result["part_count"] == 1
    member = classifications(result)[0]
    assert "교체" in member["actions"]
    assert member["minor"] not in {"교체", "마모", "손상·파손"}
    assert result["repair_actions"] == "교체"


def test_completed_repair_preserves_the_observed_symptom_separately(classify_fault):
    result = classify_fault("베어링 손상으로 교체")
    assert pairs(result) == {("베어링(종류 미상)", "손상·파손")}
    assert "교체" in classifications(result)[0]["actions"]


def test_overlapping_damage_terms_are_one_failure_without_duplicate_parts(classify_fault):
    result = classify_fault("베어링 손상 및 파손으로 교체")
    assert pairs(result) == {("베어링(종류 미상)", "손상·파손")}
    assert_partial(result, "상세설비·모듈")
    assert result["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert result["component_count"] == result["part_count"] == 1
    assert classifications(result)[0]["actions"] == ["교체"]


@pytest.mark.parametrize(
    "source,major,part,mode,equipment",
    [
        ("모터 소손", "전기·제어", "모터(종류 미상)", "소손·단락", UNKNOWN_EQUIPMENT),
        ("모터 마모", "기계", "모터(종류 미상)", "마모", UNKNOWN_EQUIPMENT),
        ("모터 축 마모", "기계", "축(종류 미상)", "마모", UNKNOWN_EQUIPMENT),
        ("차단기 떨어짐", "전기·제어", "차단기", "보호장치 동작", UNKNOWN_EQUIPMENT),
        ("엔드실러 히터 단락", "전기·제어", "히터", "소손·단락", "엔드씰러"),
        ("엔드실러 히터 나감", "전기·제어", "히터", "고장·이상", "엔드씰러"),
    ],
)
def test_field_feedback_uses_observed_failure_instead_of_inferred_cause(
    classify_fault, source, major, part, mode, equipment
):
    result = classify_fault(source)
    if equipment == UNKNOWN_EQUIPMENT:
        assert_partial(result, "상세설비·모듈")
    else:
        assert result["status"] == K["auto"]
        assert result["classification_missing_fields"] == ""
    assert result["detail_equipment"] == equipment
    assert (result["major"], result["middle"], result["minor"]) == (major, part, mode)
    assert classifications(result)[0]["part_group"]
    assert result["minor"] != "낙하"


@pytest.mark.parametrize("part", ["센서", "베어링", "모터"])
def test_named_generic_part_never_invents_a_specific_subtype(classify_fault, part):
    result = classify_fault(f"{part} 고장")
    assert recommendation_pairs(result) == {(f"{part}(종류 미상)", "고장·이상")}


def test_named_plc_keeps_its_communication_failure_before_nopart_rules(classify_fault):
    result = classify_fault("PLC 통신불량")
    assert pairs(result) == {("PLC", "통신·입출력 이상")}
    assert (result["middle"], result["minor"]) == ("PLC", "통신·입출력 이상")
    assert result["part_count"] == 1


def test_plc_power_cut_keeps_raw_evidence_without_inventing_a_standard_failure(classify_fault):
    result = classify_fault("PLC 전원차단")
    assert recommendation_pairs(result) == {("PLC", "현상 미기재")}
    assert_pending(result)
    # A shutdown alone establishes neither a failure nor a reset/restart.
    assert recommendations(result)[0]["actions"] == []
    assert "전원차단" in recommendations(result)[0]["evidence"]


def test_single_normal_inspection_does_not_leave_a_fault_component(classify_fault):
    result = classify_fault("실린더 점검 결과 정상")
    assert classifications(result) == []
    assert result["component_count"] == result["part_count"] == 0
    assert result["status"] != K["auto"]


@pytest.mark.parametrize(
    "source",
    [
        "실린더 점검 결과 정상 / 베어링 손상",
        "실린더 교체 예정 / 베어링 손상",
        "실린더 교체 안함 / 베어링 손상",
    ],
)
def test_normal_future_and_unperformed_work_do_not_create_fault_members(classify_fault, source):
    result = classify_fault(source)
    assert pairs(result) == {("베어링(종류 미상)", "손상·파손")}
    assert result["part_count"] == 1


def test_negated_shared_replacement_does_not_confirm_either_part(classify_fault):
    result = classify_fault("실린더 및 베어링 교체 안함")
    assert result["status"] != K["auto"]
    assert result["component_count"] == result["part_count"] == 0


@pytest.mark.parametrize("source", ["실린더 또는 베어링 손상", "실린더 및 베어링 손상 의심"])
def test_alternative_or_suspected_parts_are_not_automatically_confirmed(classify_fault, source):
    result = classify_fault(source)
    assert_pending(result)
    assert {item["middle"] for item in recommendations(result)} == {
        "실린더(종류 미상)",
        "베어링(종류 미상)",
    }


@pytest.fixture
def fault_axes_input(input_file):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    for row, source in {
        4: "실린더 및 베어링 손상",
        5: "베어링 마모 및 파손",
        6: "실린더 누설",
    }.items():
        sheet.cell(row, 5, source)
    workbook.save(input_file)
    workbook.close()
    return input_file


def test_analysis_keeps_one_history_and_only_one_final_classification_per_record(
    store, fault_axes_input
):
    source_bytes = fault_axes_input.read_bytes()
    result = analyze_file(store, fault_axes_input)
    assert result.metrics["selected_rows"] == len(result.selected) == 4
    assert result.metrics["total_minutes"] == 95
    assert result.tables["type"]["count"].sum() == 4
    assert result.tables["type"]["total_minutes"].sum() == 95
    details = result.tables["fault_detail"]
    first_three = result.selected.iloc[:3]
    selected_details = details.loc[details["record_id"].isin(first_three.record_id)]
    assert len(selected_details) == 3
    assert selected_details.groupby("record_id").size().to_dict() == {
        first_three.iloc[0].record_id: 1,
        first_three.iloc[1].record_id: 1,
        first_three.iloc[2].record_id: 1,
    }
    assert set(result.selected.source_row) == {4, 5, 6, 8}
    assert result.selected.record_id.is_unique and result.selected.event_id.is_unique
    assert all(row.component_count == row.part_count == 1 for _, row in first_three.iterrows())
    for index in (0, 1):
        assert_top_representative(first_three.iloc[index])
        assert len(recommendations(first_three.iloc[index])) == 2
    assert {"event_id", "major", "middle", "minor", "evidence", "actions"} <= set(details)
    assert not any("minutes" in column for column in details)
    parts = result.tables["component"]
    assert parts["count"].sum() == 3
    bearings = parts.loc[parts.component_type.str.contains("베어링(종류 미상)", regex=False)]
    assert bearings["count"].sum() == 1
    cylinders = parts.loc[parts.component_type.str.contains("실린더(종류 미상)", regex=False)]
    assert cylinders["count"].sum() == 2
    assert fault_axes_input.read_bytes() == source_bytes


def test_old_manual_part_confirmation_is_projected_without_guessing_or_rewriting(
    store, fault_axes_input
):
    original = analyze_file(store, fault_axes_input).selected.iloc[0]
    old_category = {"major": "기계", "middle": "베어링·부싱", "minor": "베어링(종류 미상)"}
    saved = {original.event_id: {**old_category, "saved_at": "2026-10-20T10:00:00"}}
    store.override_path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    before = store.override_path.read_bytes()
    updated = analyze_file(store, fault_axes_input).selected.iloc[0]
    assert_pending(updated)
    assert ("베어링(종류 미상)", "현상 미기재") in recommendation_pairs(updated)
    assert store.override_path.read_bytes() == before
    assert (
        json.loads(store.override_path.read_text("utf-8"))[original.event_id]["minor"]
        == old_category["minor"]
    )


def test_new_manual_selection_preserves_part_symptom_meaning_and_schema(store, fault_axes_input):
    original = analyze_file(store, fault_axes_input).selected.iloc[0]
    category = {
        "major": "기계",
        "detail_equipment": "상세설비 미상",
        "middle": "베어링(종류 미상)",
        "minor": "손상·파손",
    }
    assert recommendations(original)[0]["middle"] != category["middle"]
    store.update_override(original.event_id, category)
    saved = store.override(original.event_id)
    assert saved["classification_schema"] == SCHEMA
    updated = analyze_file(store, fault_axes_input).selected.iloc[0]
    assert (updated.major, updated.middle, updated.minor) == (
        "기계",
        "베어링(종류 미상)",
        "손상·파손",
    )
    assert updated.status == K["manual"]
    assert updated.part_count == updated.component_count == 1
    assert updated.event_id == original.event_id and updated.minutes == original.minutes


def test_v2_manual_replacement_stays_reviewable_without_rewriting_saved_bytes(
    store, fault_axes_input
):
    original = analyze_file(store, fault_axes_input).selected.iloc[0]
    legacy = {
        "major": "기계",
        "detail_equipment": "컨베어",
        "middle": "베어링",
        "minor": "교체",
        "classification_schema": "equipment_part_symptom_v2",
        "minutes": "10",
    }
    store.override_path.write_text(
        json.dumps({original.event_id: legacy}, ensure_ascii=False), encoding="utf-8"
    )
    before = store.override_path.read_bytes()
    revised = analyze_file(store, fault_axes_input).selected.iloc[0]
    assert_pending(revised)
    candidates = recommendations(revised)
    assert any(
        item["middle"] == "베어링(종류 미상)"
        and item["minor"] == "현상 미기재"
        and item["detail_equipment"] == "컨베어"
        and item["actions"] == ["교체"]
        for item in candidates
    )
    assert revised.minutes == 10
    assert store.override_path.read_bytes() == before


def test_old_manual_process_combination_keeps_explicit_symptoms_without_rewriting(
    store, fault_axes_input
):
    event = analyze_file(store, fault_axes_input).selected.iloc[0]
    old_categories = [
        {"major": "공정·운전", "middle": "제품·자재", "minor": "제품 걸림·막힘"},
        {"major": "공정·운전", "middle": "제품·자재", "minor": "제품 낙하"},
    ]
    saved = {
        event.event_id: {
            "classification_components": json.dumps(old_categories, ensure_ascii=False),
            "saved_at": "2026-10-20T10:00:00",
        }
    }
    store.override_path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    before = store.override_path.read_bytes()
    result = analyze_file(store, fault_axes_input)
    updated = result.selected.iloc[0]
    assert_pending(updated)
    assert {("제품·자재", "막힘·걸림"), ("제품·자재", "낙하")} <= recommendation_pairs(updated)
    assert result.metrics["selected_rows"] == 4 and result.metrics["total_minutes"] == 95
    assert store.override_path.read_bytes() == before


def test_new_manual_multiple_symptom_selection_is_rejected_without_changing_totals(
    store, fault_axes_input
):
    before = analyze_file(store, fault_axes_input)
    event = before.selected.iloc[0]
    selected = [
        {"major": "기계", "middle": "베어링(종류 미상)", "minor": "마모"},
        {"major": "기계", "middle": "베어링(종류 미상)", "minor": "손상·파손"},
    ]
    with pytest.raises(UserError, match="하나"):
        store.update_override(event.event_id, {"classification_components": json.dumps(selected)})
    assert store.override(event.event_id) == {}
    after = analyze_file(store, fault_axes_input)
    updated = after.selected.iloc[0]
    assert_top_representative(updated)
    assert updated.component_details == event.component_details
    assert updated.classification_candidates == event.classification_candidates
    assert updated.record_id == event.record_id and updated.event_id == event.event_id
    assert after.metrics["selected_rows"] == before.metrics["selected_rows"]
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"]
