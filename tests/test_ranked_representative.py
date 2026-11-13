"""Rank 1 represents the event while unsupported noun interpretations stay pending."""

import copy

import pytest

from core.classification_candidates import rank_candidates
from core.ranked_representative import choose_ranked_representative


def candidate(
    part="베어링(종류 미상)",
    *,
    mode="마모",
    major="기계",
    observed=True,
    actions=None,
    span=(0, 0, 3),
    priority=80,
    identifier="bearing",
    evidence="베어링, 마모",
    order=None,
):
    return {
        "major": major,
        "detail_equipment": "컨베어",
        "middle": part,
        "minor": mode,
        "rule_id": identifier,
        "evidence": evidence,
        "actions": list(actions or []),
        "_observed_failure": observed,
        "_span": span,
        "_priority": priority,
        "_order": order
        or (True, not observed, not bool(actions), True, 0, -priority, *span[:2], identifier, mode),
    }


def select(raw, **kwargs):
    return choose_ranked_representative(rank_candidates(raw), raw, **kwargs)


def test_returns_first_ranked_raw_member_without_mutating_either_input():
    raw = [candidate(actions=["교체"])]
    ranked = rank_candidates(raw)
    before = copy.deepcopy((ranked, raw))
    selected = choose_ranked_representative(ranked, raw)
    assert selected is not raw[0]
    assert selected["middle"] == raw[0]["middle"]
    assert selected["actions"] == ["교체"]
    assert selected["selection_method"] == "top_ranked_representative"
    assert selected["selected_rank"] == 1
    assert (ranked, raw) == before


def test_equal_evidence_for_distinct_real_parts_allows_one_event_representative():
    first = candidate(order=(True, False, True, True, 0, -80, 0, 0, "a", "마모"))
    second = candidate(
        "체인(종류 미상)",
        span=(0, 8, 10),
        identifier="chain",
        evidence="체인, 마모",
        order=(True, False, True, True, 0, -80, 0, 8, "z", "마모"),
    )
    assert first["_order"][:6] == second["_order"][:6]
    selected = select([second, first])
    assert selected["middle"] == first["middle"]
    assert selected["selected_rank"] == 1


@pytest.mark.parametrize("different", [{"part": "다른 부품"}, {"major": "전기·제어"}])
def test_equal_highest_priority_interpretations_on_one_noun_stay_unresolved(different):
    first = candidate()
    second = candidate(**different, identifier="other")
    assert select([first, second]) is None


def test_more_specific_rule_on_the_same_noun_can_supply_the_representative():
    first = candidate()
    lower = candidate("일반 부품", priority=20, identifier="general")
    selected = select([lower, first])
    assert selected["middle"] == first["middle"]


def test_repeated_interpretations_of_the_same_public_part_are_not_a_conflict():
    assert select([candidate(), candidate(identifier="duplicate")]) is not None


def test_one_part_with_explicit_modes_in_different_domains_allows_a_representative():
    damaged = candidate("오링", mode="손상·파손", major="기계", order=(0,))
    leaking = candidate("오링", mode="누설", major="유체·배관", order=(1,))
    selected = select([damaged, leaking])
    assert selected["minor"] == "손상·파손"
    assert selected["selected_rank"] == 1


@pytest.mark.parametrize("actions", [[], ["교체 예정"], ["미완료"], ["위치"]])
def test_weak_noun_or_unperformed_action_is_not_enough(actions):
    assert select([candidate(observed=False, mode="현상 미기재", actions=actions)]) is None


@pytest.mark.parametrize("action", ["교체", "점검", "조정", "청소·급유"])
def test_completed_action_supports_partial_representative_without_inventing_mode(action):
    selected = select([candidate(observed=False, mode="현상 미기재", actions=[action])])
    assert selected["minor"] == "현상 미기재"
    assert selected["actions"] == [action]


def test_unsupported_first_rank_never_falls_through_to_supported_second_rank():
    weak = candidate(observed=False, order=(0,), identifier="weak")
    strong = candidate("체인", span=(1, 0, 2), order=(1,), identifier="strong")
    assert select([weak, strong]) is None


@pytest.mark.parametrize(
    "field", ["major", "detail_equipment", "middle", "minor", "rule_id", "evidence"]
)
def test_ranked_first_must_match_the_exact_current_raw_candidate(field):
    raw = [candidate()]
    ranked = rank_candidates(raw)
    ranked[0][field] += " changed"
    assert choose_ranked_representative(ranked, raw) is None


def test_unmatched_first_rank_never_falls_back_to_the_matching_second_rank():
    raw = [candidate(), candidate("체인", span=(1, 0, 2), identifier="chain")]
    ranked = rank_candidates(raw)
    ranked[0]["evidence"] = "old saved evidence"
    assert choose_ranked_representative(ranked, raw) is None


def test_deduplicated_candidate_uses_the_same_raw_evidence_order_as_the_ranker():
    weak = candidate(observed=False, order=(1,))
    strong = candidate(observed=True, order=(0,))
    selected = select([weak, strong])
    assert selected["_observed_failure"] is True


def test_external_safety_block_always_keeps_the_event_pending():
    assert select([candidate()], blocked=True) is None


@pytest.mark.parametrize("ranked,raw", [([], []), ([{}], []), ([{}], [{}])])
def test_missing_candidate_data_does_not_produce_a_representative(ranked, raw):
    assert choose_ranked_representative(ranked, raw) is None
