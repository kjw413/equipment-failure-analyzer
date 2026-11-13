"""Four public axes preserve evidence, old confirmations and one event total."""

import json
from pathlib import Path

import pytest
from conftest import analyze_file

from core.classification_candidates import parse_candidates, rank_candidates
from core.classification_catalog import (
    catalog_categories,
    catalog_signature,
    fault_catalog_categories,
)
from core.classification_completeness import missing_fields
from core.equipment_taxonomy import EquipmentResolver
from core.failure_classification import FaultClassifier
from core.failure_modes import CLASSIFICATION_SCHEMA, UNKNOWN_EQUIPMENT, UNKNOWN_PART
from core.fault_components import CATEGORY_FIELDS, component_payload, parse_components
from core.i18n import K
from core.models import UserError
from core.parsing import prepare_text
from core.public_taxonomy import PublicTaxonomy
from core.rules import MIN_APP_VERSION, RULES_SCHEMA, read_rules
from gui.category_index import category_index

ROOT = Path(__file__).resolve().parents[1]


def assert_top_representative(result):
    candidates = parse_candidates(result["classification_candidates"], strict=True)
    (member,) = parse_components(result["component_details"], strict=True)
    expected = tuple(candidates[0][key] for key in CATEGORY_FIELDS)
    assert tuple(result[key] for key in CATEGORY_FIELDS) == expected
    assert tuple(member[key] for key in CATEGORY_FIELDS) == expected
    assert member["selection_method"] == "top_ranked_representative"
    assert member["selected_rank"] == candidates[0]["rank"] == 1
    assert member["rule_id"] == candidates[0]["rule_id"]
    assert member["evidence"] == candidates[0]["evidence"]
    assert result["status"] == (K["partial"] if missing_fields(result) else K["auto"])
    assert result["classification_mode"] == "single" and result["review_code"] == ""
    assert result["component_count"] == result["part_count"] == 1


@pytest.fixture(scope="module")
def hierarchy_classifier():
    normalization = json.loads((ROOT / "config/normalization.json").read_text("utf-8"))
    classifier = FaultClassifier(read_rules(ROOT / "config/classification_config.xlsx"))

    def classify(source, middle="", registered=""):
        return classifier.classify(
            prepare_text(source, normalization),
            equipment_context=middle,
            registered_equipment=registered,
        )

    return classify


def test_fault_machine_overrides_unrelated_registered_asset(hierarchy_classifier):
    result = hierarchy_classifier("컨베어 베어링 손상", "세척기", "카토닝머신")
    assert tuple(result[key] for key in CATEGORY_FIELDS) == (
        "기계",
        "컨베어",
        "베어링(종류 미상)",
        "손상·파손",
    )
    assert result["detail_equipment_source"] == "원문"
    assert result["classification_schema"] == CLASSIFICATION_SCHEMA
    assert result["component_count"] == result["part_count"] == 1


def test_middle_downtime_equipment_precedes_registered_asset(hierarchy_classifier):
    result = hierarchy_classifier("베어링 손상", "제대기", "세척기")
    assert result["detail_equipment"] == "제대기"
    assert result["detail_equipment_source"] == "비가동코드(중)"


def test_unknown_machine_is_explicit_without_inventing_a_cause(hierarchy_classifier):
    result = hierarchy_classifier("베어링 교체")
    assert result["status"] == K["partial"]
    assert result["classification_mode"] == "single"
    assert result["classification_missing_fields"] == "상세설비·모듈, 고장 현상"
    assert result["component_count"] == result["part_count"] == 1
    candidates = parse_candidates(result["classification_candidates"], strict=True)
    assert len(candidates) == 1
    assert candidates[0]["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert candidates[0]["detail_equipment_source"] == "미기재"
    assert candidates[0]["minor"] == "현상 미기재"
    assert candidates[0]["actions"] == ["교체"]
    member = parse_components(result["component_details"], strict=True)[0]
    assert member["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert member["middle"] == "베어링(종류 미상)" and member["minor"] == "현상 미기재"


def test_whole_machine_fault_does_not_invent_a_subpart(hierarchy_classifier):
    result = hierarchy_classifier("프리저 고장")
    assert result["status"] == K["partial"] and result["review_code"] == ""
    assert result["classification_missing_fields"] == "고장 분야, 세부 부품"
    member = parse_components(result["component_details"], strict=True)[0]
    assert member["major"] == "분야 미상"
    assert member["detail_equipment"] == "프리저"
    assert member["middle"] == member["part_type"] == UNKNOWN_PART
    assert member["minor"] == "고장·이상"
    assert result["component_count"] == 1 and result["part_count"] == 0
    assert member["rule_id"] and member["evidence"]


def test_named_pump_is_the_precise_module_without_inventing_an_internal_part(hierarchy_classifier):
    result = hierarchy_classifier("필러 펌프 누설")
    assert result["detail_equipment"] == "펌프"
    assert result["middle"] == UNKNOWN_PART
    assert result["component_count"] == 1 and result["part_count"] == 0
    assert result["minor"] == "누설"


def test_specific_machine_subpart_is_not_replaced_by_unknown(hierarchy_classifier):
    result = hierarchy_classifier("프리저 베어링 마모")
    assert result["detail_equipment"] == "프리저"
    assert result["middle"] == "베어링(종류 미상)"
    assert result["middle"] != UNKNOWN_PART
    assert result["part_count"] == 1


def test_body_name_matches_an_exact_alias_instead_of_a_substring():
    legacy = EquipmentResolver([{"name": "컨베어", "aliases": ["컨베이어"]}])
    assert legacy.component_name("컨베이어(종류 미상)", "컨베어") == UNKNOWN_PART
    resolver = PublicTaxonomy(equipment_types=[{"name": "컨베어", "aliases": ["컨베이어"]}])
    assert resolver.component_name("컨베이어(종류 미상)", "컨베어") == UNKNOWN_PART
    assert resolver.component_name("컨베이어 체인", "컨베어") == "컨베이어 체인"
    assert resolver.component_name("컨베이어", "필러") == UNKNOWN_PART
    assert resolver.component_name("프리저 스크래퍼", "프리저") == "프리저 스크래퍼"


def test_repeated_part_binds_symptom_to_its_own_equipment(hierarchy_classifier):
    result = hierarchy_classifier("컨베어 베어링 손상 / 포장기 베어링 마모")
    candidates = parse_candidates(result["classification_candidates"], strict=True)
    assert {(item["detail_equipment"], item["middle"], item["minor"]) for item in candidates} == {
        ("컨베어", "베어링(종류 미상)", "손상·파손"),
        ("포장기", "베어링(종류 미상)", "마모"),
    }
    assert_top_representative(result)
    assert result["status"] == K["auto"]


def test_unrelated_normal_machine_does_not_take_failure_location(hierarchy_classifier):
    result = hierarchy_classifier("포장기 점검 결과 정상 / 컨베어 베어링 손상", "세척기")
    assert result["detail_equipment"] == "컨베어"
    assert result["middle"] == "베어링(종류 미상)"


@pytest.mark.parametrize(
    "source", ["모터 트립 필러 정상", "필러 교체 예정 / 모터 트립", "필러 이상 없음 / 모터 트립"]
)
def test_normal_or_planned_machine_cannot_be_revived_from_downtime_code(
    hierarchy_classifier, source
):
    result = hierarchy_classifier(source, "필러", "세척기")
    assert result["detail_equipment"] == UNKNOWN_EQUIPMENT


def test_registered_asset_alone_does_not_establish_fault_machine(hierarchy_classifier):
    result = hierarchy_classifier("베어링 손상", "", "세척기")
    assert result["detail_equipment"] == UNKNOWN_EQUIPMENT
    assert result["detail_equipment_source"] == "미기재"


def test_ascii_machine_alias_survives_classifier_whitespace_removal(hierarchy_classifier):
    result = hierarchy_classifier("filler motor trip", "세척기")
    assert result["detail_equipment"] == "필러·충진기"
    assert result["detail_equipment_source"] == "원문"


def test_registered_replacement_candidates_remain_when_rank_one_is_representative(
    hierarchy_classifier,
):
    result = hierarchy_classifier("y실러 1차 2차 #9#10 PLC카드및히타 썸머카플교체")
    assert_top_representative(result)
    assert result["status"] == K["partial"]
    assert result["classification_missing_fields"] == "고장 현상"
    assert parse_components(result["component_details"])[0]["actions"] == ["교체"]
    assert {item["middle"] for item in parse_candidates(result["classification_candidates"])} >= {
        "PLC 카드",
        "열전대",
    }


def test_specific_alias_owns_generic_embedded_robot():
    resolver = EquipmentResolver()
    assert [item[2] for item in resolver.mentions("로봇파렛타이져 모터 고장")] == ["파렛타이저"]


def test_internal_parts_keep_three_fields_but_public_paths_have_four():
    rule = {"enabled": True, "major": "기계", "middle": "베어링·부싱", "minor": "베어링(종류 미상)"}
    assert catalog_categories([rule]) == [("기계", "베어링·부싱", "베어링(종류 미상)")]
    choices = fault_catalog_categories([rule], [{"name": "제대기", "aliases": []}])
    assert ("기계", "제대기", "베어링(종류 미상)", "손상·파손") in choices
    assert ("기계", UNKNOWN_EQUIPMENT, "베어링(종류 미상)", "손상·파손") in choices
    assert ("기계", "제대기", UNKNOWN_PART, "손상·파손") in choices
    assert all(len(choice) == 4 for choice in choices)


def test_manual_part_choices_do_not_depend_on_detail_equipment():
    rules = [{"enabled": True, "major": "기계", "middle": "이송", "minor": "컨베어"}]
    choices = fault_catalog_categories(
        rules, [{"name": "컨베어", "aliases": []}, {"name": "필러", "aliases": []}]
    )
    index = category_index(choices)
    by_equipment = {
        equipment: index.menu_choices("middle", {"detail_equipment": equipment})
        for equipment in ("컨베어", "필러", UNKNOWN_EQUIPMENT)
    }
    assert by_equipment["컨베어"] == by_equipment["필러"] == by_equipment[UNKNOWN_EQUIPMENT]
    assert "세부 부품 미기재" in by_equipment["컨베어"]


def test_equipment_is_part_of_candidate_and_member_identity():
    members = [
        {
            "major": "기계",
            "detail_equipment": equipment,
            "middle": "베어링(종류 미상)",
            "minor": "손상·파손",
            "schema": CLASSIFICATION_SCHEMA,
        }
        for equipment in ("컨베어", "포장기")
    ]
    assert len(rank_candidates(members)) == 2
    payload = component_payload(members)
    assert payload["part_count"] == payload["component_count"] == 2
    assert len(parse_components(payload["component_details"], strict=True)) == 2


def test_current_manual_selection_requires_all_four_axes(store):
    with pytest.raises(UserError, match="상세설비"):
        store.update_override(
            "event", {"major": "기계", "middle": "베어링(종류 미상)", "minor": "손상·파손"}
        )
    values = dict(zip(CATEGORY_FIELDS, ("기계", "컨베어", "베어링(종류 미상)", "손상·파손")))
    store.update_override("event", values)
    assert store.override("event")["classification_schema"] == CLASSIFICATION_SCHEMA
    store.update_override("event", {"minutes": "12"})
    assert all(store.override("event")[key] == value for key, value in values.items())
    assert RULES_SCHEMA == 7 and MIN_APP_VERSION == "1.16.0"


def test_v1_manual_confirmation_remains_unmodified_and_needs_equipment_review(store, input_file):
    before_result = analyze_file(store, input_file)
    event = before_result.selected.iloc[0]
    legacy = {
        "major": "전기·제어",
        "middle": "모터",
        "minor": "과부하",
        "classification_schema": "part_symptom_v1",
        "minutes": "10",
    }
    store.override_path.write_text(
        json.dumps({event.event_id: legacy}, ensure_ascii=False), "utf-8"
    )
    original_bytes = store.override_path.read_bytes()
    after_result = analyze_file(store, input_file)
    revised = after_result.selected.loc[after_result.selected.event_id.eq(event.event_id)].iloc[0]
    assert revised.status == K["review"]
    assert all(revised[key] == "" for key in CATEGORY_FIELDS)
    assert "이전 기준" in revised.classification_reason
    assert any(
        item["middle"] == "모터(종류 미상)" and item["minor"] == "과부하·과전류"
        for item in parse_candidates(revised.classification_candidates)
    )
    assert store.override_path.read_bytes() == original_bytes
    assert len(after_result.selected) == len(before_result.selected)
    assert after_result.metrics["total_minutes"] == before_result.metrics["total_minutes"]


def test_equipment_alias_revision_changes_catalog_signature():
    catalog = json.loads((ROOT / "config/classification_catalog.json").read_text("utf-8"))
    changed = json.loads(json.dumps(catalog))
    changed["equipment_types"] = [{"name": "제대기", "aliases": ["테스트별칭"]}]
    assert catalog_signature(changed) != catalog_signature(catalog)


def test_incomplete_current_manual_file_is_not_silently_confirmed(store, input_file):
    event = analyze_file(store, input_file).selected.iloc[0]
    saved = {
        event.event_id: {
            "major": "전기·제어",
            "middle": "모터",
            "minor": "과부하",
            "classification_schema": CLASSIFICATION_SCHEMA,
        }
    }
    store.override_path.write_text(json.dumps(saved, ensure_ascii=False), "utf-8")
    original_bytes = store.override_path.read_bytes()
    revised = analyze_file(store, input_file).selected.iloc[0]
    assert revised.status == K["review"]
    assert all(revised[key] == "" for key in CATEGORY_FIELDS)
    assert store.override_path.read_bytes() == original_bytes
