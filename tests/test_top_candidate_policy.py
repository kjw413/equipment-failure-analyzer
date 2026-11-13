"""Representative rank selection retains evidence and never guesses a missing fact."""

import json
from pathlib import Path

import pytest

from core.classification_candidates import parse_candidates
from core.failure_classification import FaultClassifier
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import K
from core.parsing import prepare_text
from tools.make_rules import build_rules

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def classify():
    normalization = json.loads((ROOT / "config/normalization.json").read_text("utf-8"))
    classifier = FaultClassifier(build_rules())
    return lambda value: classifier.classify(prepare_text(value, normalization))


@pytest.mark.parametrize(
    "source",
    [
        "컨베어 베어링 마모 / 별도로 센서 감지불량",
        "컨베어 베어링 손상 / 펌프 씰 교체",
        "베어링 교체 / 모터 점검",
        "컨베어 베어링 파손 및 마모",
    ],
)
def test_supported_first_candidate_becomes_one_representative(classify, source):
    result = classify(source)
    ranked = parse_candidates(result["classification_candidates"], strict=True)
    assert len(ranked) >= 2
    assert result["status"] in (K["auto"], K["partial"])
    assert result["review_code"] == ""
    assert all(result[key] == ranked[0][key] for key in CATEGORY_FIELDS)
    (member,) = parse_components(result["component_details"], strict=True)
    assert member["selection_method"] == "top_ranked_representative"
    assert member["selected_rank"] == 1
    assert result["component_count"] == result["part_count"] == 1
    assert "1순위 대표 자동선택" in result["classification_reason"]
    assert "유일한 고장" in result["classification_reason"]


@pytest.mark.parametrize(
    "source",
    [
        "모터 소손 의심 / 베어링 파손",
        "베어링 손상 또는 센서 교체",
        "박스 공급 에어라인 및 피팅 교체",
        "씰러 온도 다운 / 무접점 홀더 소손 및 홀더 교체",
        "구동볼트 파손. 파손부위 용접 및 무접점홀더 소손",
        "그리퍼 위치",
        "베어링 교체 미완료",
    ],
)
def test_uncertainty_alternatives_and_insufficient_evidence_still_need_review(classify, source):
    result = classify(source)
    assert result["status"] not in (K["auto"], K["partial"])
    assert parse_components(result["component_details"]) == []


@pytest.mark.parametrize(
    "source,part,mode",
    [
        ("센터씰러 히터 단선으로 인한 온도 떨어짐", "히터", "단선"),
        ("로봇 컨트롤 박스 볼트 풀리며 떨어져 컨트롤 박스 고정", "볼트", "이탈·풀림"),
        (
            "성형몰드 받침가이드 파손 정비 / 초지 다발로 떨어짐으로 몰드걸림",
            "가이드(종류 미상)",
            "손상·파손",
        ),
        ("포장기 타이밍 벨트 풀리 고정 셋트 볼트 풀림", "볼트", "이탈·풀림"),
        ("버켓 플레이트 파손 (카톤 진입시 플레이트 가이드 카톤 이탈)", "버켓", "손상·파손"),
    ],
)
def test_literal_subject_and_antecedent_precede_result_or_part_name_substrings(
    classify, source, part, mode
):
    result = classify(source)
    assert result["status"] in (K["auto"], K["partial"])
    assert (result["middle"], result["minor"]) == (part, mode)
    ranked = parse_candidates(result["classification_candidates"])
    assert (ranked[0]["middle"], ranked[0]["minor"]) == (part, mode)


def test_explicit_product_subject_is_not_confirmed_as_belt_failure(classify):
    result = classify("스틱인서터 스틱이 스틱정렬벨트 위치 이탈 및 게이트바디에 걸림")
    assert result["status"] not in (K["auto"], K["partial"])
    assert not parse_components(result["component_details"])


def test_set_bolt_modifier_does_not_invent_completed_fastening(classify):
    result = classify("포장기 타이밍벨트 풀리 고정 셋트볼트 풀림")
    assert result["repair_actions"] == ""
    assert (result["middle"], result["minor"]) == ("볼트", "이탈·풀림")


def test_reject_transport_name_does_not_supply_a_failure_to_previous_chain(classify):
    result = classify("버켓 구동부 체인 고착 및 늘어남. 체인교체 및 불량이송컨베어 감속기 교체")
    ranked = parse_candidates(result["classification_candidates"])
    assert result["status"] in (K["auto"], K["partial"])
    assert (result["middle"], result["minor"]) == ("체인(종류 미상)", "막힘·걸림")
    assert not any(
        item["middle"] == "체인(종류 미상)" and item["minor"] == "고장·이상" for item in ranked
    )


def test_pockets_leaving_guide_do_not_supply_guide_displacement(classify):
    result = classify("포장기 포켓 다수 가이드 이탈 발생, 체인 이탈 / 가이드 조정")
    assert result["status"] in (K["auto"], K["partial"])
    assert (result["middle"], result["minor"]) == ("체인(종류 미상)", "이탈·풀림")
    ranked = parse_candidates(result["classification_candidates"])
    assert not any(
        item["middle"] == "가이드(종류 미상)" and item["minor"] == "이탈·풀림" for item in ranked
    )
