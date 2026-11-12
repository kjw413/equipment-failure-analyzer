"""Semantic safeguards for the source-backed taxonomy draft, not accuracy scores."""

import pytest

from scripts.taxonomy_rebuild_policy import UNKNOWN_MODE, UNKNOWN_PART, draft_classify


@pytest.fixture
def masters():
    equipment = [
        {"name": name, "family": "설비", "aliases": aliases}
        for name, aliases in (
            ("펌프", ["펌프"]),
            ("컨베어", ["컨베어"]),
            ("엔드씰러", ["엔드실러", "엔드씰러"]),
            ("씰러", ["sealer"]),
            ("열풍건조기", ["열풍건조기"]),
            ("프리저", ["프리저"]),
        )
    ]
    parts = [
        {"name": name, "family": family, "aliases": aliases, "original_domain": domain}
        for name, family, aliases, domain in (
            ("모터(종류 미상)", "모터", ["모터"], "전기·제어"),
            ("베어링(종류 미상)", "베어링", ["베어링"], "기계"),
            ("축(종류 미상)", "축", ["축"], "기계"),
            ("히터", "히터", ["히터"], "전기·제어"),
            ("차단기", "보호장치", ["차단기"], "전기·제어"),
            ("센서(종류 미상)", "센서", ["센서"], "전기·제어"),
            ("광전센서", "센서", ["광전센서"], "전기·제어"),
            ("체인(종류 미상)", "체인", ["체인"], "기계"),
            ("퓨즈", "보호장치", ["퓨즈"], "전기·제어"),
            ("부싱", "부싱", ["부싱"], "기계"),
        )
    ]
    return equipment, parts


def classify(masters, text, mid=""):
    return draft_classify(text, mid, *masters)


def test_motor_burn_uses_electrical_evidence_and_keeps_replacement_separate(masters):
    result = classify(masters, "펌프 모터 소손, 모터 교체", "기계파트")
    assert result["candidates"][0]["major"] == "전기·제어"
    assert {x["minor"] for x in result["candidates"]} == {"소손·단락"}
    assert "교체" in result["actions"]


def test_motor_wear_is_not_fixed_to_electrical_by_part_name(masters):
    result = classify(masters, "펌프 모터 마모")
    assert result["candidates"][0]["major"] == "기계"


def test_replacement_without_a_symptom_does_not_invent_a_failure_mode(masters):
    result = classify(masters, "펌프 모터 교체")
    assert result["candidates"][0]["minor"] == UNKNOWN_MODE
    assert result["status"] == "검토 필요"


def test_breaker_falling_is_protection_operation_not_falling_or_overload(masters):
    result = classify(masters, "펌프 가동시 차단기 떨어짐")
    assert {x["minor"] for x in result["candidates"]} == {"보호장치 동작"}


def test_concrete_sensor_surface_owns_the_generic_sensor_span(masters):
    result = classify(masters, "컨베어 광전센서 고장")
    assert {x["middle"] for x in result["candidates"]} == {"광전센서"}


def test_unspecified_sensor_stays_unspecified(masters):
    result = classify(masters, "컨베어 센서 고장")
    assert {x["middle"] for x in result["candidates"]} == {"센서(종류 미상)"}


def test_machine_only_failure_does_not_invent_an_inner_part(masters):
    result = classify(masters, "열풍건조기 고장")
    assert result["candidates"][0]["detail_equipment"] == "열풍건조기"
    assert result["candidates"][0]["middle"] == UNKNOWN_PART


def test_explicit_part_list_shares_a_symptom_without_selecting_one_winner(masters):
    result = classify(masters, "컨베어 베어링 및 축 마모")
    assert {x["middle"] for x in result["candidates"]} == {"베어링(종류 미상)", "축(종류 미상)"}
    assert result["status"] == "검토 필요"


def test_actual_typo_in_broken_chain_is_a_surface_variant(masters):
    result = classify(masters, "부싱 마모 및 체인 끈어짐 정비")
    assert {x["middle"] for x in result["candidates"]} == {"부싱", "체인(종류 미상)"}


def test_network_description_does_not_assert_a_plc_card_failure(masters):
    result = classify(
        masters,
        "def0283 Inputs/outputs network station in defect, address : 31 에러로 Sealer 셧다운 발생 / 차단기 전원 재동작 후 복구",
    )
    assert {x["minor"] for x in result["candidates"]} == {"통신·입출력 이상"}
    assert all(x["middle"] == UNKNOWN_PART for x in result["candidates"])
    assert all(x["detail_equipment"] == "씰러" for x in result["candidates"])


def test_bare_error_code_is_not_used_as_a_manufacturer_fault_dictionary(masters):
    result = classify(masters, "def0283")
    assert not result["candidates"]


def test_suspected_short_circuit_remains_review(masters):
    result = classify(masters, "설비 퓨즈이상 (오일펌프 쇼트의심)")
    assert "의심·추정 표현" in result["review_reasons"]
    assert not any(x["minor"] == "소손·단락" for x in result["candidates"])


def test_planned_replacement_is_not_a_completed_action(masters):
    assert "교체" not in classify(masters, "센서 교체 예정")["actions"]


def test_heater_out_is_generic_failure_not_automatically_burned(masters):
    result = classify(masters, "엔드실러 히터 나감, 히터 교체")
    assert {x["minor"] for x in result["candidates"]} == {"고장·이상"}


def test_explicit_short_circuit_word_is_recognized(masters):
    result = classify(masters, "엔드실러 히터 단락 조치")
    assert {x["minor"] for x in result["candidates"]} == {"소손·단락"}
