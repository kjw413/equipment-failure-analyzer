"""Actual multiple failures are event members, not alternative rule candidates."""

import json

import pytest

from core.classifier import RuleClassifier
from core.i18n import K


def rule(
    name, *, context=None, category=None, priority=10, symptom=None, role="component", major=None
):
    category = category or name
    return dict(
        id=name,
        enabled=True,
        priority=priority,
        major=major or category,
        middle=category,
        minor=category,
        context=context or name,
        symptom=symptom or "failed|broken|replaced|adjusted|inspected",
        exclude="",
        role=role,
    )


def engine(rules, **settings):
    return RuleClassifier(
        rules,
        {"replace_pattern": "replaced|repair", "action_pattern": "adjusted|inspected", **settings},
    )


def members(result):
    assert isinstance(result["classification_reason"], str)
    assert isinstance(result["candidate_evidence"], str)
    assert not any("score" in field for field in result)
    components = json.loads(result["component_details"])
    assert all("score" not in member for member in components)
    return components


def member_types(result):
    return {
        tuple(member[key] for key in ("major", "middle", "minor")) for member in members(result)
    }


def test_two_actual_faults_return_the_full_combination_instead_of_the_top_type():
    result = engine([rule("pump"), rule("motor")]).classify("pump failed / motor failed")
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2
    assert member_types(result) == {("pump",) * 3, ("motor",) * 3}
    assert result["major"] == "복수 고장"
    assert result["middle"] == "2개 유형 조합"
    assert result["minor"] == "motor / motor / motor + pump / pump / pump"
    assert result["status"] == K["review"]
    assert result["review_code"] == "multiple_faults"
    assert "독립된 유형들을 조합으로 보존" in result["classification_reason"]
    assert all(term in result["candidate_evidence"] for term in ("[pump]", "[motor]", "failed"))
    assert {member["rule_id"] for member in members(result)} == {"pump", "motor"}


def test_combination_identity_and_label_are_independent_of_source_order():
    classifier = engine([rule("pump"), rule("motor"), rule("sensor")])
    first = classifier.classify("pump failed / motor failed / sensor failed")
    reverse = classifier.classify("sensor failed / pump failed / motor failed")
    for key in (
        "classification_mode",
        "component_count",
        "component_types",
        "combination_key",
        "major",
        "middle",
        "minor",
    ):
        assert first[key] == reverse[key]
    assert first["component_count"] == 3
    assert first["combination_key"].startswith("MULTI:")


def test_duplicate_rules_and_repeated_mentions_do_not_duplicate_types():
    original = rule("pump")
    duplicate = {**original, "id": "pump_duplicate", "priority": 9999}
    classifier = engine([original, duplicate, rule("motor")])
    result = classifier.classify("pump failed / pump replaced / motor failed")
    assert result["component_count"] == 2
    assert len(members(result)) == 2
    assert member_types(result) == {("pump",) * 3, ("motor",) * 3}


def test_three_distinct_detailed_types_are_all_preserved():
    rules = [
        rule("pump", category="Detail A", major="Mechanical"),
        rule("motor", category="Detail B", major="Electrical"),
        rule("sensor", category="Detail C", major="Electrical"),
    ]
    result = engine(rules).classify("pump failed / motor failed / sensor failed")
    assert result["component_count"] == 3
    assert member_types(result) == {
        ("Mechanical", "Detail A", "Detail A"),
        ("Electrical", "Detail B", "Detail B"),
        ("Electrical", "Detail C", "Detail C"),
    }


def test_local_alternatives_on_one_physical_part_are_one_member_only():
    rules = [
        rule("pump_specific", context="pump", category="Specific", symptom="failed|replaced"),
        rule("pump_general", context="pump", category="General", symptom="failed", priority=999),
        rule("motor"),
    ]
    result = engine(rules).classify("pump failed replaced / motor failed")
    assert result["component_count"] == 2
    assert member_types(result) == {("General",) * 3, ("motor",) * 3}
    assert "Specific" in result["candidate_evidence"]
    assert "Specific" not in result["component_types"]


def test_local_priority_selects_one_type_and_keeps_independent_multiple_review():
    rules = [
        rule("pump_first", context="pump", category="First", priority=100),
        rule("pump_second", context="pump", category="Second", priority=1),
        rule("motor"),
    ]
    result = engine(rules).classify("pump failed / motor failed")
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2
    assert member_types(result) == {("First",) * 3, ("motor",) * 3}
    assert "세부 규칙" in next(
        member["evidence"] for member in members(result) if member["minor"] == "First"
    )
    assert result["review_code"] == "multiple_faults"
    assert result["status"] == K["review"]


@pytest.mark.parametrize("names", [("first", "second"), ("second", "first")])
def test_equal_priority_rules_on_one_part_require_review_regardless_of_rule_order(names):
    result = engine([rule(name, context="pump") for name in names]).classify("pump failed")
    assert result["classification_mode"] == "ambiguous"
    assert result["component_count"] == 1
    assert result["major"] != "복수 고장"
    assert result["combination_key"] == ""
    assert result["review_code"] == "multi_rule"
    assert all(term in result["candidate_evidence"] for term in ("[first]", "[second]"))


def test_independent_literal_fallback_is_an_actual_member_with_rule_evidence():
    result = engine([rule("pump"), rule("leak", symptom=".", role="fallback")]).classify(
        "pump failed / separately leak"
    )
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2
    assert member_types(result) == {("pump",) * 3, ("leak",) * 3}
    leak = next(member for member in members(result) if member["minor"] == "leak")
    assert leak["rule_id"] == "leak" and "leak" in leak["evidence"]


def test_inspection_and_part_only_candidates_do_not_become_components():
    result = engine([rule("pump"), rule("motor"), rule("sensor"), rule("valve")]).classify(
        "pump failed / motor failed / sensor inspected / valve"
    )
    assert result["component_count"] == 2
    assert member_types(result) == {("pump",) * 3, ("motor",) * 3}
    assert "sensor" in result["candidates"] and "valve" not in result["candidates"]


def test_listed_adjustments_only_remain_ambiguous_not_confirmed_multiple_faults():
    result = engine([rule("pump"), rule("motor")]).classify("pump 및 motor adjusted")
    assert result["review_code"] == "multiple_faults"  # Existing conservative review gate.
    assert result["classification_mode"] == "ambiguous"
    assert result["component_count"] == 1
    assert result["major"] != "복수 고장"


def test_causal_outcome_is_not_added_to_an_independent_combination():
    result = engine([rule("pump"), rule("motor"), rule("sensor")]).classify(
        "pump failed로 motor failed / separately sensor failed"
    )
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2
    assert member_types(result) == {("pump",) * 3, ("sensor",) * 3}
    assert "motor" not in result["component_types"]


def test_plain_cause_and_its_outcome_are_one_type():
    result = engine([rule("pump"), rule("motor")]).classify("pump failed로 motor failed")
    assert result["classification_mode"] == "single"
    assert result["component_count"] == 1
    assert member_types(result) == {("pump",) * 3}


@pytest.mark.parametrize(
    "text, expected_mode",
    [("unknown", "unclassified"), ("pump", "unclassified"), ("pump failed", "single")],
)
def test_component_contract_for_non_multiple_results(text, expected_mode):
    result = engine([rule("pump")]).classify(text)
    assert result["classification_mode"] == expected_mode
    assert result["component_count"] == (0 if expected_mode == "unclassified" else 1)
    assert isinstance(result["component_details"], str)
    assert result["combination_key"] == ""
    assert isinstance(result["classification_reason"], str)
    assert isinstance(result["candidate_evidence"], str)
    assert not any("score" in field for field in result)


def test_repeated_failure_and_repair_of_one_part_are_not_two_fault_components():
    rules = [
        rule("failure", context="pump", category="Failure", symptom="failed"),
        rule("repair", context="pump", category="Repair", symptom="replaced"),
    ]
    result = engine(rules).classify("pump failed / pump replaced")
    assert result["classification_mode"] == "ambiguous"
    assert result["component_count"] == 1
    assert result["major"] != "복수 고장"
    assert result["status"] == K["review"]
    assert member_types(result) == {("Repair",) * 3}


def test_repeated_part_alternatives_add_only_one_member_beside_another_fault():
    rules = [
        rule("failure", context="pump", category="Failure", symptom="failed"),
        rule("repair", context="pump", category="Repair", symptom="replaced"),
        rule("motor"),
    ]
    result = engine(rules).classify("pump failed / pump replaced / motor failed")
    assert result["component_count"] == 2
    assert member_types(result) == {("Repair",) * 3, ("motor",) * 3}


@pytest.mark.parametrize(
    "text", ["1번 pump failed / 2번 pump replaced", "pump failed / separately pump replaced"]
)
def test_explicitly_distinct_parts_are_not_merged_by_the_same_context_word(text):
    rules = [
        rule("failure", context="pump", category="Failure", symptom="failed"),
        rule("repair", context="pump", category="Repair", symptom="replaced"),
    ]
    result = engine(rules).classify(text)
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2


@pytest.mark.parametrize("connector", ["또는", "혹은", "아니면", "or"])
@pytest.mark.parametrize("thresholds", [None, {"min_score": 0, "min_margin": 0}])
def test_explicit_choices_are_one_ambiguous_group_and_never_auto_confirmed(connector, thresholds):
    result = engine([rule("pump"), rule("motor")], scoring=thresholds).classify(
        f"pump failed {connector} motor failed"
    )
    assert result["classification_mode"] == "ambiguous"
    assert result["component_count"] == 1
    assert result["status"] == K["review"]
    assert result["review_code"] == "alternative_types"
    assert "대안" in result["classification_reason"]


def test_repeated_uncertain_endings_are_an_explicit_alternative():
    result = engine([rule("pump"), rule("motor")]).classify(
        "pump failed인지 motor failed인지 확인 필요"
    )
    assert result["classification_mode"] == "ambiguous"
    assert result["component_count"] == 1
    assert result["review_code"] == "alternative_types"


def test_alternative_group_keeps_another_independent_fault_as_one_more_member():
    result = engine([rule("pump"), rule("motor"), rule("sensor")]).classify(
        "pump failed 또는 motor failed / separately sensor broken"
    )
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2
    assert ("sensor",) * 3 in member_types(result)
    assert len(member_types(result) & {("pump",) * 3, ("motor",) * 3}) == 1
    assert result["review_code"] == "alternative_types"
    assert "대안" in result["classification_reason"]


def test_an_additional_listed_part_is_not_swallowed_by_a_prior_alternative():
    result = engine([rule("pump"), rule("motor"), rule("sensor")]).classify(
        "pump failed 또는 motor failed 및 sensor broken"
    )
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2
    assert ("sensor",) * 3 in member_types(result)
    assert result["review_code"] == "alternative_types"


def test_alternative_connector_after_a_clause_separator_still_requires_review():
    result = engine([rule("pump"), rule("motor")]).classify("pump failed / 혹은 motor failed")
    assert result["classification_mode"] == "ambiguous"
    assert result["component_count"] == 1
    assert result["review_code"] == "alternative_types"


def test_error_word_is_not_mistaken_for_the_english_or_connector():
    result = engine([rule("pump", symptom="error")]).classify("pump error")
    assert result["review_code"] == ""
    assert result["classification_mode"] == "single"


@pytest.mark.parametrize(
    "legacy", [{"min_score": 0, "min_margin": 0}, {"min_score": 100, "min_margin": 100}]
)
def test_legacy_score_settings_do_not_change_rule_matching_or_add_numeric_results(legacy):
    rules = [rule("pump"), rule("motor")]
    for text in ("pump", "pump failed", "pump failed / motor failed"):
        expected = engine(rules).classify(text)
        actual = engine(rules, scoring=legacy).classify(text)
        assert actual == expected
        assert not any("score" in field for field in actual)


@pytest.mark.parametrize(
    "text",
    ["pump replaced 예정 / separately motor failed", "pump 교체예정 / separately motor failed"],
)
def test_future_repair_is_not_an_additional_fault_member(text):
    classifier = engine(
        [rule("pump", symptom="replaced|교체"), rule("motor")], replace_pattern="replaced|교체"
    )
    result = classifier.classify(text)
    assert result["classification_mode"] == "single"
    assert member_types(result) == {("motor",) * 3}


@pytest.fixture(scope="module")
def bundled_classifier():
    from core.config import resource_root
    from core.parsing import prepare_text
    from core.rules import read_rules

    bundle = resource_root() / "config"
    settings = json.loads((bundle / "settings.json").read_text(encoding="utf-8"))["classifier"]
    normalization = json.loads((bundle / "normalization.json").read_text(encoding="utf-8"))
    classifier = RuleClassifier(read_rules(bundle / "classification_config.xlsx"), settings)
    return lambda text: classifier.classify(prepare_text(text, normalization))


@pytest.mark.parametrize(
    "text, mode, expected_path",
    [
        (
            "봉함기 사이드벨트 구동모터 멈춤(로봇쪽) 추후 정비필요",
            "single",
            ("전기·제어", "모터", "모터(종류 미상)"),
        ),
        (
            "냉동기 과부하 다운, 믹스 동결 온도 상승",
            "single",
            ("온도·냉각", "냉동·냉각장치", "냉동기"),
        ),
        (
            "생산중 갑자기 ht-300 설비 작동중지 정지, 비상정지, 리셋, 시작 버튼 반으없음\r\n-전기반 의뢰, 원인으로 메인판넬 plc 접촉불량에러 조치 후 생산",
            "single",
            ("전기·제어", "제어기·I/O·통신", "PLC"),
        ),
        ("qft온도 불량", "unclassified", None),
        (
            "봉함기 릴레이 파손 접촉불량 단자대 재조임",
            "single",
            ("전기·제어", "스위치·릴레이", "릴레이(종류 미상)"),
        ),
        (
            "인입컨베어 좌측 바닥 가이드 휘어져 제품 찌그러짐 휘어진 부분 조치후 생산",
            "single",
            ("기계", "가이드·레일", "가이드(종류 미상)"),
        ),
        ("멀티팩 떨어짐으로 설비 센터틀어짐 정비", "unclassified", None),
    ],
)
def test_real_descriptions_do_not_turn_alternatives_plans_or_results_into_multiple_parts(
    bundled_classifier, text, mode, expected_path
):
    result = bundled_classifier(text)
    assert result["classification_mode"] == mode
    assert result["component_count"] == (1 if expected_path else 0)
    if expected_path:
        assert tuple(result[key] for key in ("major", "middle", "minor")) == expected_path
    else:
        # A symptom or machine name alone must not invent a detailed component.
        assert result["status"] == K["unclassified"]
        assert not members(result)


@pytest.mark.parametrize(
    "text, count, mode, expected_paths",
    [
        (
            "제품이송 모터 고장 / 별도로 센서 고장",
            2,
            "multiple",
            {
                ("전기·제어", "모터", "모터(종류 미상)"),
                ("전기·제어", "센서·검출", "센서(종류 미상)"),
            },
        ),
        (
            "믹스 펌프 파손 / 별도로 모터 고장",
            2,
            "multiple",
            {("유체·배관", "펌프", "펌프(종류 미상)"), ("전기·제어", "모터", "모터(종류 미상)")},
        ),
        (
            "센서 고장 / 별도로 모터 교체 예정",
            1,
            "single",
            {("전기·제어", "센서·검출", "센서(종류 미상)")},
        ),
        (
            "모터 교체 완료 / 별도로 센서 고장",
            2,
            "multiple",
            {
                ("전기·제어", "모터", "모터(종류 미상)"),
                ("전기·제어", "센서·검출", "센서(종류 미상)"),
            },
        ),
        (
            "냉동기 정지, 원인으로 plc 접촉불량, 별도로 모터 고장",
            2,
            "multiple",
            {("전기·제어", "제어기·I/O·통신", "PLC"), ("전기·제어", "모터", "모터(종류 미상)")},
        ),
    ],
)
def test_outcome_and_planned_work_filters_keep_explicit_actual_faults(
    bundled_classifier, text, count, mode, expected_paths
):
    result = bundled_classifier(text)
    assert result["component_count"] == count
    assert result["classification_mode"] == mode
    assert member_types(result) == expected_paths


@pytest.mark.parametrize("prefix", ["향후", "추후", "예정된"])
def test_future_marker_before_the_part_does_not_become_a_repair_component(prefix):
    result = engine([rule("pump"), rule("motor")]).classify(
        f"{prefix} pump replaced / motor failed"
    )
    assert result["classification_mode"] == "single"
    assert member_types(result) == {("motor",) * 3}


def test_explicit_completion_is_kept_even_near_an_earlier_plan_marker():
    result = engine([rule("pump"), rule("motor")]).classify(
        "예정 작업 pump replaced완료 / separately motor failed"
    )
    assert result["classification_mode"] == "multiple"
    assert result["component_count"] == 2


def test_independent_listed_fault_before_an_alternative_is_not_swallowed():
    result = engine([rule("pump"), rule("motor"), rule("sensor")]).classify(
        "sensor broken 및 pump failed 또는 motor failed"
    )
    assert result["component_count"] == 2
    assert ("sensor",) * 3 in member_types(result)
    assert result["review_code"] == "alternative_types"
