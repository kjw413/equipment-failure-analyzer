"""A direct recorded fault may outrank repairs, never another stated fault."""

import pytest

from core.representative_fault import choose_direct_fault


def member(part, mode, *, equipment="컨베어", observed=True, actions=None):
    return {
        "major": "기계",
        "detail_equipment": equipment,
        "middle": part,
        "minor": mode,
        "_observed_failure": observed,
        "actions": actions or [],
    }


def test_direct_damage_outweighs_a_separate_repair_only_mention():
    fault = member("베어링(종류 미상)", "손상·파손")
    repair = member("볼트", "현상 미기재", observed=False, actions=["교체"])
    assert choose_direct_fault([fault, repair]) == fault


@pytest.mark.parametrize(
    "other",
    [
        member("센서(종류 미상)", "감지불량"),
        member("볼트", "현상 미기재", observed=False, equipment="펌프", actions=["교체"]),
        member("볼트", "현상 미기재", observed=False),
        member("세부 부품 미기재", "고장·이상"),
    ],
)
def test_competing_fault_unknown_context_and_other_machine_still_need_review(other):
    assert choose_direct_fault([member("베어링(종류 미상)", "손상·파손"), other]) is None


@pytest.mark.parametrize("mode", ["동작불량", "온도이상", "압력이상"])
def test_general_state_is_not_a_direct_physical_fault(mode):
    assert (
        choose_direct_fault(
            [
                member("모터(종류 미상)", mode),
                member("센서(종류 미상)", "현상 미기재", observed=False, actions=["교체"]),
            ]
        )
        is None
    )


def test_explicit_alternative_or_independent_work_cannot_be_overridden():
    assert choose_direct_fault([member("베어링(종류 미상)", "마모")], blocked=True) is None
