"""Observed failures and completed work must survive independent-axis projection."""

import json
from pathlib import Path

import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.classification_candidates import parse_candidates
from core.failure_classification import FaultClassifier
from core.failure_modes import SYMPTOM_NAMES, UNKNOWN_EQUIPMENT, UNKNOWN_PART, UNKNOWN_SYMPTOM
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import K
from core.parsing import prepare_text
from core.public_taxonomy import parse_repair_actions
from tools.make_rules import build_rules

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def classify_current():
    normalization = json.loads((ROOT / "config/normalization.json").read_text(encoding="utf-8"))
    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))
    classifier = FaultClassifier(build_rules(), settings["classifier"])
    return lambda value: classifier.classify(prepare_text(value, normalization))


@pytest.mark.parametrize(
    "source, part, mode, equipment",
    [
        ("고정볼트 파손", "볼트", "손상·파손", UNKNOWN_EQUIPMENT),
        ("센터씰러 히터 소손", "히터", "소손·단락", "센터씰러"),
        ("타이밍벨트 파손", "타이밍벨트", "손상·파손", UNKNOWN_EQUIPMENT),
        ("텐션롤러 마모", "텐션롤러", "마모", UNKNOWN_EQUIPMENT),
        ("위치센서 감지불량", "센서(종류 미상)", "감지불량", UNKNOWN_EQUIPMENT),
        ("원점센서 감지불량", "센서(종류 미상)", "감지불량", UNKNOWN_EQUIPMENT),
    ],
)
def test_part_or_module_name_does_not_assert_completed_work(
    classify_current, source, part, mode, equipment
):
    result = classify_current(source)
    assert result["repair_actions"] == ""
    assert result["middle"] == part and result["minor"] == mode
    assert result["detail_equipment"] == equipment
    member = parse_components(result["component_details"])[0]
    assert member["actions"] == []
    if equipment == UNKNOWN_EQUIPMENT:
        assert result["status"] == K["partial"]
        assert result["classification_missing_fields"] == "상세설비·모듈"
    else:
        assert result["status"] == K["auto"]
        assert result["classification_missing_fields"] == ""


@pytest.mark.parametrize(
    "source, expected",
    [
        ("고정볼트 파손 후 체결", ["체결·조립"]),
        ("센터씰러 히터 소손 후 교체", ["교체"]),
        ("타이밍벨트 파손 교체 후 타이밍 조정", ["교체", "조정"]),
        ("텐션롤러 마모 조정 완료", ["조정"]),
    ],
)
def test_explicit_work_is_retained_next_to_component_name(classify_current, source, expected):
    result = classify_current(source)
    assert set(parse_repair_actions(result["repair_actions"])) == set(expected)


@pytest.mark.parametrize(
    "source",
    [
        "베어링 교체 필요",
        "베어링 교체 요청",
        "베어링 교체 미완료",
        "베어링 교체 안 했다",
        "베어링 교체 못함",
        "베어링 교체 예정",
        "not replaced motor",
        "motor repair planned",
    ],
)
def test_unperformed_work_is_not_saved_as_completed_action(classify_current, source):
    result = classify_current(source)
    assert result["repair_actions"] == ""
    assert parse_components(result["component_details"]) == []
    assert result["status"] not in (K["auto"], K["partial"])
    assert all(
        not item.get("actions") for item in parse_candidates(result["classification_candidates"])
    )


def test_only_completed_clause_supplies_actions(classify_current):
    result = classify_current("센서 교체 예정 / 베어링 파손 후 교체 완료")
    assert parse_repair_actions(result["repair_actions"]) == ["교체"]


def test_explicit_completion_after_an_earlier_plan_marker_is_completed_work(classify_current):
    result = classify_current("예정 작업 베어링 교체완료")
    assert parse_repair_actions(result["repair_actions"]) == ["교체"]
    member = parse_components(result["component_details"])[0]
    assert member["middle"] == "베어링(종류 미상)"
    assert member["actions"] == ["교체"]
    assert member["minor"] == UNKNOWN_SYMPTOM


@pytest.mark.parametrize(
    "source",
    [
        "network station in defect 예정",
        "network station in defect 의심",
        "network station in defect 아님",
        "inputs/outputs network 정상",
        "inputs/outputs network 에러 없음",
        "inputs/outputs network 점검 예정",
    ],
)
def test_network_supplement_never_confirms_planned_or_negated_fault(classify_current, source):
    result = classify_current(source)
    assert result["status"] != K["auto"]
    assert parse_components(result["component_details"]) == []


@pytest.mark.parametrize("source", ["베어링 마모", "모터 소손"])
def test_independent_network_fault_preserves_all_candidates_with_one_representative(
    classify_current, source
):
    result = classify_current(source + " / network station in defect")
    assert result["status"] == K["partial"]
    (representative,) = parse_components(result["component_details"])
    ranked = parse_candidates(result["classification_candidates"])
    assert all(representative[key] == ranked[0][key] for key in CATEGORY_FIELDS)
    assert representative["selection_method"] == "top_ranked_representative"
    candidates = parse_candidates(result["classification_candidates"])
    assert any(item["minor"] == "통신·입출력 이상" for item in candidates)
    assert any(item["middle"] != UNKNOWN_PART for item in candidates)


def test_network_fault_is_preserved_after_recovery(classify_current):
    result = classify_current("network station in defect 발생 후 정상 복구")
    assert result["status"] == K["partial"]
    member = parse_components(result["component_details"])[0]
    assert (member["middle"], member["minor"]) == (UNKNOWN_PART, "통신·입출력 이상")
    assert member["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert result["classification_missing_fields"] == "상세설비·모듈"
    assert parse_repair_actions(result["repair_actions"]) == ["리셋·재가동"]


def test_hot_air_dryer_body_does_not_become_a_replacement_part(classify_current):
    result = classify_current("열풍건조기 고장")
    assert result["status"] == K["partial"]
    member = parse_components(result["component_details"])[0]
    assert member["detail_equipment"] == "열풍건조기"
    assert member["middle"] == UNKNOWN_PART and member["minor"] == "고장·이상"
    assert member["major"] == "분야 미상"
    assert result["part_count"] == 0
    assert result["classification_missing_fields"] == "고장 분야"
    assert result["repair_actions"] == "" and member["actions"] == []
    candidates = parse_candidates(result["classification_candidates"])
    assert any(
        item["detail_equipment"] == "열풍건조기"
        and item["middle"] == UNKNOWN_PART
        and item["major"] == "분야 미상"
        for item in candidates
    )


def test_replacement_never_becomes_the_observed_failure(classify_current):
    assert "교체" not in SYMPTOM_NAMES
    result = classify_current("베어링 교체")
    assert result["status"] == K["partial"]
    member = parse_components(result["component_details"])[0]
    assert member["middle"] == "베어링(종류 미상)"
    assert member["minor"] == UNKNOWN_SYMPTOM
    assert member["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert member["actions"] == ["교체"]
    assert set(result["classification_missing_fields"].split(", ")) == {
        "상세설비·모듈",
        "고장 현상",
    }
    candidates = parse_candidates(result["classification_candidates"])
    assert candidates and all(item["minor"] == UNKNOWN_SYMPTOM for item in candidates)
    assert parse_repair_actions(result["repair_actions"]) == ["교체"]


def test_saved_empty_manual_action_clears_inference_and_none_restores_it(store, input_file):
    workbook = load_workbook(input_file)
    workbook["Events"].cell(4, 5).value = "컨베어 베어링 파손 후 교체"
    workbook.save(input_file)
    workbook.close()
    source_bytes = input_file.read_bytes()
    initial = analyze_file(store, input_file)
    record = initial.selected.loc[initial.selected.source_row.eq(4)].iloc[0]
    assert record.repair_actions == "교체"
    store.update_override(record.event_id, {"repair_actions": ""})
    cleared = (
        analyze_file(store, input_file)
        .selected.loc[lambda frame: frame.record_id.eq(record.record_id)]
        .iloc[0]
    )
    assert cleared.repair_actions == ""
    assert store.read("manual_overrides.json")[record.event_id]["repair_actions"] == ""
    # The editable action is separate from the retained original evidence.
    assert (
        parse_components(cleared.component_details)[0]["actions"]
        == parse_components(record.component_details)[0]["actions"]
    )
    store.update_override(record.event_id, {"repair_actions": None})
    restored = (
        analyze_file(store, input_file)
        .selected.loc[lambda frame: frame.record_id.eq(record.record_id)]
        .iloc[0]
    )
    assert restored.repair_actions == "교체"
    assert restored.status == record.status
    assert restored.minutes == record.minutes
    assert input_file.read_bytes() == source_bytes
