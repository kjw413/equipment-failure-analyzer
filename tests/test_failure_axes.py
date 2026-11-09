"""Part/symptom classification keeps event identity and downtime additive."""

import json
from pathlib import Path

import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.failure_classification import FaultClassifier
from core.fault_components import parse_components
from core.i18n import K
from core.parsing import prepare_text
from core.rules import read_rules

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "part_symptom_v1"


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


def test_shared_damage_is_attached_to_every_explicitly_listed_part(classify_fault):
    result = classify_fault("실린더 및 베어링 손상")
    assert pairs(result) == {("실린더", "손상"), ("베어링", "손상")}
    assert result["part_count"] == result["component_count"] == 2
    assert result["status"] == K["auto"]
    members = classifications(result)
    assert {member["major"] for member in members} == {"공압·진공", "기계"}
    assert all(member["schema"] == SCHEMA for member in members)
    assert all("손상" in member["symptom_evidence"] for member in members)


def test_different_symptoms_are_bound_to_their_own_parts(classify_fault):
    result = classify_fault("실린더 누설 및 베어링 마모")
    assert pairs(result) == {("실린더", "누설"), ("베어링", "마모")}
    assert result["part_count"] == 2
    assert ("실린더", "마모") not in pairs(result)
    assert ("베어링", "누설") not in pairs(result)


def test_several_symptoms_do_not_turn_one_part_into_several_parts(classify_fault):
    result = classify_fault("베어링 마모 및 파손")
    assert pairs(result) == {("베어링", "마모"), ("베어링", "파손")}
    assert result["part_count"] == 1
    assert result["component_count"] == 2


def test_repeated_part_symptom_mentions_count_once_per_history(classify_fault):
    result = classify_fault("베어링 손상 / 베어링 손상으로 교체")
    assert pairs(result) == {("베어링", "손상")}
    assert result["part_count"] == result["component_count"] == 1


def test_single_and_multiple_events_use_the_same_part_symptom_axes(classify_fault):
    result = classify_fault("실린더 손상")
    assert (result["major"], result["middle"], result["minor"]) == (
        "공압·진공",
        "실린더",
        "손상",
    )
    assert pairs(result) == {("실린더", "손상")}
    assert result["part_count"] == result["component_count"] == 1


@pytest.mark.parametrize(
    "source, part, symptom",
    [
        ("타이밍벨트 끊어짐", "타이밍벨트", "파손"),
        ("광전센서 단선", "광전센서", "단선"),
        ("모터 트립", "모터", "과부하"),
    ],
)
def test_other_component_families_keep_their_explicit_kind_and_symptom(
    classify_fault, source, part, symptom
):
    result = classify_fault(source)
    assert pairs(result) == {(part, symptom)}
    assert result["middle"] == part and result["minor"] == symptom


def test_completed_replacement_is_action_without_inventing_a_symptom(classify_fault):
    result = classify_fault("베어링 교체")
    assert pairs(result) == {("베어링", "증상 미기재")}
    member = classifications(result)[0]
    assert "교체" in member["actions"]
    assert member["part_type"] == "베어링(종류 미상)"
    assert member["part_group"] == "베어링·부싱"
    assert member["minor"] not in {"마모", "손상"}


def test_completed_repair_preserves_the_observed_symptom_separately(classify_fault):
    result = classify_fault("베어링 손상으로 교체")
    assert pairs(result) == {("베어링", "손상")}
    assert "교체" in classifications(result)[0]["actions"]


def test_named_plc_keeps_its_communication_failure_before_nopart_rules(classify_fault):
    result = classify_fault("PLC 통신불량")
    assert pairs(result) == {("PLC", "통신이상")}
    assert (result["middle"], result["minor"]) == ("PLC", "통신이상")
    assert result["part_count"] == 1


def test_plc_power_cut_is_kept_as_action_without_inventing_failure(classify_fault):
    result = classify_fault("PLC 전원차단")
    assert pairs(result) == {("PLC", "증상 미기재")}
    assert classifications(result)[0]["actions"] == ["전원 차단·종료"]


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
    assert pairs(result) == {("베어링", "손상")}
    assert result["part_count"] == 1


def test_negated_shared_replacement_does_not_confirm_either_part(classify_fault):
    result = classify_fault("실린더 및 베어링 교체 안함")
    assert result["status"] != K["auto"]
    assert result["component_count"] == result["part_count"] == 0


@pytest.mark.parametrize("source", ["실린더 또는 베어링 손상", "실린더 및 베어링 손상 의심"])
def test_alternative_or_suspected_parts_are_not_automatically_confirmed(classify_fault, source):
    result = classify_fault(source)
    assert result["status"] == K["review"]


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


def test_analysis_explodes_fault_classifications_without_duplicating_history_or_time(
    store, fault_axes_input
):
    result = analyze_file(store, fault_axes_input)
    assert result.metrics["selected_rows"] == len(result.selected) == 4
    assert result.metrics["total_minutes"] == 95
    assert result.tables["type"]["count"].sum() == 4
    assert result.tables["type"]["total_minutes"].sum() == 95
    details = result.tables["fault_detail"]
    first_three = result.selected.iloc[:3]
    selected_details = details.loc[details["record_id"].isin(first_three.record_id)]
    assert len(selected_details) == 5
    assert selected_details.groupby("record_id").size().to_dict() == {
        first_three.iloc[0].record_id: 2,
        first_three.iloc[1].record_id: 2,
        first_three.iloc[2].record_id: 1,
    }
    assert {"event_id", "major", "middle", "minor", "evidence", "actions"} <= set(details)
    assert not any("minutes" in column for column in details)
    parts = result.tables["component"]
    assert parts["count"].sum() == 4
    bearings = parts.loc[parts.component_type.str.contains("베어링", regex=False)]
    assert bearings["count"].sum() == 2


def test_old_manual_part_confirmation_is_projected_without_guessing_or_rewriting(
    store, fault_axes_input
):
    original = analyze_file(store, fault_axes_input).selected.iloc[0]
    old_category = {"major": "기계", "middle": "베어링·부싱", "minor": "베어링(종류 미상)"}
    saved = {original.event_id: {**old_category, "saved_at": "2026-10-20T10:00:00"}}
    store.override_path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    before = store.override_path.read_bytes()
    updated = analyze_file(store, fault_axes_input).selected.iloc[0]
    assert updated.status == K["manual"]
    assert (updated.major, updated.middle, updated.minor) == ("기계", "베어링", "증상 미기재")
    assert updated.part_count == 1
    assert store.override_path.read_bytes() == before
    member = parse_components(updated.component_details, strict=True)[0]
    assert member["legacy_category"] == old_category


def test_new_manual_selection_preserves_part_symptom_meaning_and_schema(store, fault_axes_input):
    original = analyze_file(store, fault_axes_input).selected.iloc[0]
    category = {"major": "기계", "middle": "베어링", "minor": "손상"}
    store.update_override(original.event_id, category)
    saved = store.override(original.event_id)
    assert saved["classification_schema"] == SCHEMA
    updated = analyze_file(store, fault_axes_input).selected.iloc[0]
    assert (updated.major, updated.middle, updated.minor) == ("기계", "베어링", "손상")
    assert updated.status == K["manual"]
    assert updated.part_count == updated.component_count == 1


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
    assert pairs(updated) == {("제품·자재", "막힘·걸림"), ("제품·자재", "낙하")}
    assert {member["major"] for member in classifications(updated)} == {"공정·운전"}
    assert updated.part_count == 1 and updated.component_count == 2
    assert updated.status == K["manual_multi"]
    assert result.metrics["selected_rows"] == 4 and result.metrics["total_minutes"] == 95
    assert store.override_path.read_bytes() == before


def test_manual_multiple_symptoms_remain_one_part_without_allocating_downtime(
    store, fault_axes_input
):
    before = analyze_file(store, fault_axes_input)
    event = before.selected.iloc[0]
    selected = [
        {"major": "기계", "middle": "베어링", "minor": "마모"},
        {"major": "기계", "middle": "베어링", "minor": "파손"},
    ]
    store.update_override(event.event_id, {"classification_components": json.dumps(selected)})
    saved = store.override(event.event_id)
    assert saved["classification_schema"] == SCHEMA
    after = analyze_file(store, fault_axes_input)
    updated = after.selected.iloc[0]
    assert pairs(updated) == {("베어링", "마모"), ("베어링", "파손")}
    assert updated.status == K["manual_multi"]
    assert updated.part_count == 1 and updated.component_count == 2
    assert after.metrics["selected_rows"] == before.metrics["selected_rows"]
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"]
