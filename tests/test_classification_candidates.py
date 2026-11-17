"""Recommendation ranks are auditable inspection order, never final choices."""

import json

import pytest

from core.classification_candidates import parse_candidates, rank_candidates
from core.failure_classification import FaultClassifier
from core.fault_components import parse_components
from core.i18n import K
from core.models import UserError


def rule(
    identifier, part, *, context=None, priority=10, major="기계", role="component", symptom=None
):
    return {
        "id": identifier,
        "enabled": True,
        "priority": priority,
        "major": major,
        "middle": "부품군",
        "minor": part,
        "context": context or part,
        "symptom": symptom or "손상|마모|파손|누설|교체|점검",
        "exclude": "",
        "role": role,
    }


def candidates(result):
    values = parse_candidates(result["classification_candidates"], strict=True)
    assert [item["rank"] for item in values] == list(range(1, len(values) + 1))
    assert all(
        "score" not in item and "probability" not in item and "_order" not in item
        for item in values
    )
    return values


def test_helper_keeps_ordinal_ranks_instead_of_alphabetical_component_order():
    source = [
        {"major": "기계", "middle": "가부품", "minor": "손상", "rank": 2},
        {"major": "기계", "middle": "하부품", "minor": "손상", "rank": 1, "evidence": "원문"},
    ]
    before = json.dumps(source)
    parsed = parse_candidates(json.dumps(source), strict=True)
    assert [item["middle"] for item in parsed] == ["하부품", "가부품"]
    assert parsed[0]["evidence"] == "원문"
    assert json.dumps(source) == before


def test_helper_deduplicates_complete_paths_after_evidence_ordering():
    path = {"major": "기계", "middle": "베어링", "minor": "마모"}
    ranked = rank_candidates(
        [
            {**path, "_order": (1, 2), "evidence": "weak"},
            {**path, "_order": (0, 2), "evidence": "strong"},
        ]
    )
    assert len(ranked) == 1 and ranked[0]["rank"] == 1
    assert ranked[0]["evidence"] == "strong"
    assert "_order" not in ranked[0]


@pytest.mark.parametrize("value", ["not json", "{}", '[{"major":"기계"}]'])
def test_malformed_candidate_storage_is_safe_and_strict_mode_explains_it(value):
    assert parse_candidates(value) == []
    with pytest.raises(UserError):
        parse_candidates(value, strict=True)


def test_all_equal_priority_rule_alternatives_survive_without_a_final_selection():
    classifier = FaultClassifier(
        [
            rule("second", "하부품", context="부품"),
            rule("first", "가부품", context="부품"),
        ]
    )
    result = classifier.classify("부품 손상")
    assert result["status"] == K["review"]
    assert result["classification_mode"] == "ambiguous"
    assert parse_components(result["component_details"]) == []
    assert {item["middle"] for item in candidates(result)} == {"가부품", "하부품"}
    assert result["middle"] == ""
    assert (result["major"], result["minor"]) == ("기계", "손상·파손")
    assert result["component_count"] == result["part_count"] == 0


def test_resolved_rule_keeps_eligible_lower_priority_alternative_as_a_candidate():
    result = FaultClassifier(
        [
            rule("general", "일반부품", context="부품", priority=1),
            rule("specific", "상세부품", context="부품", priority=100),
        ]
    ).classify("부품 손상")
    # A more specific rule on the same noun span remains resolved; only the
    # absent machine information makes this a partial classification.
    assert result["status"] == K["partial"]
    assert result["classification_missing_fields"] == "상세설비·모듈"
    assert result["middle"] == "상세부품"
    assert result["component_count"] == result["part_count"] == 1
    assert [item["middle"] for item in candidates(result)] == ["상세부품", "일반부품"]


def test_cause_and_explicit_failure_precede_action_only_context():
    classifier = FaultClassifier([rule("a", "실린더"), rule("z", "베어링")])
    result = classifier.classify("실린더 점검 / 원인은 베어링 손상")
    ranked = candidates(result)
    assert ranked[0]["middle"] == "베어링(종류 미상)"
    assert "원인" in ranked[0]["reason"] and "고장" in ranked[0]["reason"]
    assert any(item["middle"] == "실린더(종류 미상)" for item in ranked)


def test_mes_compatibility_is_an_explained_tie_breaker_and_not_a_probability():
    classifier = FaultClassifier(
        [rule("a", "센서", major="전기"), rule("z", "베어링")],
        {"part_code_majors": {"MES": ["기계"]}},
    )
    ranked = candidates(classifier.classify("센서 손상 / 베어링 손상", "MES"))
    assert ranked[0]["middle"] == "베어링(종류 미상)"
    assert "MES" in ranked[0]["reason"]
    assert not any("%" in item["reason"] for item in ranked)


def test_closer_part_and_symptom_precede_distant_context_deterministically():
    rules = [rule("a", "실린더", priority=100), rule("z", "베어링", priority=1)]
    first = FaultClassifier(rules).classify("실린더 앞부분 손상 / 베어링 손상")
    reversed_rules = FaultClassifier(list(reversed(rules))).classify(
        "실린더 앞부분 손상 / 베어링 손상"
    )
    assert candidates(first)[0]["middle"] == "베어링(종류 미상)"
    assert first["classification_candidates"] == reversed_rules["classification_candidates"]


def test_unmatched_part_context_is_a_weak_recommendation_without_invented_symptom():
    result = FaultClassifier([rule("bearing", "베어링")]).classify("베어링 기록 확인")
    assert result["status"] == K["rule_unmatched"]
    assert parse_components(result["component_details"]) == []
    ranked = candidates(result)
    assert ranked[0]["middle"] == "베어링(종류 미상)" and ranked[0]["minor"] == "현상 미기재"
    assert "약한 근거" in ranked[0]["reason"]


@pytest.mark.parametrize(
    "source",
    [
        "베어링 정상",
        "베어링 점검 결과 정상",
        "베어링 손상 없음",
        "베어링 교체 예정",
        "추후 베어링 교체",
        "베어링 교체 안함",
    ],
)
def test_normal_negated_and_planned_mentions_never_return_as_weak_candidates(source):
    result = FaultClassifier([rule("bearing", "베어링")]).classify(source)
    assert candidates(result) == []
    assert parse_components(result["component_details"]) == []


def test_human_candidate_text_uses_the_same_public_axes_and_order_as_json():
    result = FaultClassifier([rule("a", "실린더"), rule("z", "베어링")]).classify(
        "실린더 교체 / 베어링 손상"
    )
    ranked = candidates(result)
    assert result["candidates"].split(" | ")[0] == (
        f"1. {ranked[0]['major']} / {ranked[0]['detail_equipment']} / "
        f"{ranked[0]['middle']} / {ranked[0]['minor']}"
    )
    assert (
        result["candidate_evidence"]
        .splitlines()[0]
        .startswith(result["candidates"].split(" | ")[0])
    )
    assert "부품군" not in result["candidates"]


def test_literal_process_symptom_remains_a_real_symptom():
    result = FaultClassifier(
        [
            rule(
                "jam",
                "제품 걸림·막힘",
                context="걸림",
                symptom=".",
                role="nopart",
                major="공정·운전",
            )
        ]
    ).classify("제품 걸림")
    assert result["status"] == K["partial"]
    assert result["classification_missing_fields"] == "상세설비·모듈"
    assert result["component_count"] == 1 and result["part_count"] == 0
    assert result["middle"] == "제품·자재" and result["minor"] == "막힘·걸림"
