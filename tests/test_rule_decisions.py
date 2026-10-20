"""Rule decisions have no numeric thresholds; later safety checks remain intact."""

import json

import pytest

from core.classifier import RuleClassifier
from core.i18n import K


def rule(name, **updates):
    return (
        dict(
            id=name,
            enabled=True,
            priority=10,
            major=name,
            middle=name,
            minor=name,
            context=name,
            symptom="failed|broken|replaced|adjusted|inspected",
            exclude="",
            role="component",
        )
        | updates
    )


def engine(rules, **settings):
    return RuleClassifier(
        rules,
        {"replace_pattern": "replaced|repair", "action_pattern": "adjusted|inspected", **settings},
    )


@pytest.mark.parametrize(
    "saved",
    [
        None,
        {},
        {"min_score": 100, "min_margin": 100},
        {"min_score": 0, "min_margin": 0},
        "invalid old value",
    ],
)
def test_saved_thresholds_do_not_change_rule_decisions(saved):
    classifier = engine([rule("pump")], scoring=saved)
    result = classifier.classify("pump failed")
    assert result == engine([rule("pump")]).classify("pump failed")
    assert result["status"] == K["auto"]
    assert not any("score" in field for field in result)
    assert all("score" not in item for item in json.loads(result["component_details"]))


def test_part_name_alone_does_not_satisfy_a_required_symptom():
    assert engine([rule("pump")]).classify("pump")["status"] == K["unclassified"]


def test_named_part_beats_unnamed_symptom_fallback():
    fallback = rule("broken", symptom=".", role="fallback")
    result = engine([rule("pump"), fallback]).classify("pump broken")
    assert result["major"] == "pump" and result["status"] == K["auto"]


def test_repaired_part_wins_over_an_inspected_part():
    result = engine([rule("pump"), rule("motor")]).classify("pump replaced / motor inspected")
    assert result["major"] == "pump" and result["status"] == K["auto"]
    assert "교체 부품 우선" in result["classification_reason"]


def test_specific_rule_uses_priority_on_the_same_part():
    first = rule("pump")
    refined = {**first, "id": "refined", "major": "Detailed", "priority": 100}
    result = engine([first, refined]).classify("pump failed")
    assert result["major"] == "Detailed" and result["status"] == K["auto"]
    assert "세부 규칙" in result["classification_reason"]


def test_causal_part_wins_over_its_outcome():
    result = engine([rule("pump"), rule("motor")]).classify("pump failed로 motor failed")
    assert result["major"] == "pump" and result["status"] == K["auto"]


@pytest.mark.parametrize("marker", ["별도로", "별개로", "추가로", "한편", "separately"])
def test_independent_failure_is_not_erased_by_prior_cause(marker):
    result = engine([rule("pump"), rule("motor"), rule("sensor")]).classify(
        f"pump failed로 motor failed / {marker} sensor broken"
    )
    assert result["status"] == K["review"] and result["component_count"] == 2
    assert {x["major"] for x in json.loads(result["component_details"])} == {"pump", "sensor"}


@pytest.mark.parametrize("text", ["pump failed 없음", "pump 정상", "pump inspected 예정"])
def test_negative_normal_or_planned_mentions_do_not_match(text):
    assert engine([rule("pump")]).classify(text)["status"] == K["unclassified"]


def test_unresolved_inspection_candidates_are_reviewed():
    result = engine([rule("pump"), rule("motor")]).classify("pump inspected / motor inspected")
    assert result["status"] == K["review"] and result["review_code"] == "multi_rule"


def test_mes_tie_break_does_not_hide_independent_faults():
    classifier = engine([rule("pump"), rule("motor")], part_code_majors={"MES": ["pump"]})
    result = classifier.classify("pump failed / motor failed", "MES")
    assert result["status"] == K["review"] and result["component_count"] == 2


@pytest.mark.parametrize("connector", ["or", "또는", "혹은", "아니면"])
def test_alternative_types_never_become_confirmed_combination(connector):
    result = engine([rule("pump"), rule("motor")]).classify(f"pump failed {connector} motor failed")
    assert result["status"] == K["review"] and result["component_count"] == 1
    assert result["review_code"] == "alternative_types"
