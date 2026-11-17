"""Row-by-row expectations for the user's second feedback workbook, through row 27."""

import json
from pathlib import Path

import pytest

from core.classifier import clauses
from core.defaults_merge import merge_named_defaults
from core.failure_classification import FaultClassifier
from core.fault_components import parse_components
from core.i18n import K
from core.parsing import prepare_text
from tools.make_rules import build_rules

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/feedback27_20261113.json").read_text(encoding="utf-8"))[
    "cases"
]
EXPECTED = {
    2: ("규칙분류", "전기·제어", "펌프", "차단기", "보호장치 동작"),
    3: ("규칙분류", "기계", "필러·충진기", "부싱", "마모"),
    4: ("규칙 미일치", "", "랩어라운드 케이서", "", ""),
    5: ("규칙 미일치", "", "", "", ""),
    6: ("규칙 미일치", "", "밸브", "", ""),
    7: ("검토필요", "온도·냉각", "프리저", "", "점도이상"),
    8: ("규칙 미일치", "", "", "", ""),
    9: ("규칙 미일치", "", "케이서", "", "터짐"),
    10: ("규칙분류", "공정·운전", "카토닝머신", "가이드(종류 미상)", "위치·설정이상"),
    11: ("규칙 미일치", "", "핫멜트", "", ""),
    12: ("부분분류", "분야 미상", "날인기", "세부 부품 미기재", "고장·이상"),
    13: ("검토필요", "", "날인기", "", ""),
    14: ("부분분류", "기계", "상세설비 미상", "이송 플레이트", "이탈·풀림"),
    15: ("규칙분류", "전기·제어", "스트로우부착기", "아이마크 센서", "감지불량"),
    16: ("규칙분류", "공정·운전", "필러·충진기", "호퍼", "막힘·걸림"),
    17: ("규칙분류", "공정·운전", "피더", "제품·자재", "손상·파손"),
    18: ("규칙분류", "공압·진공", "필러·충진기", "니플", "손상·파손"),
    19: ("검토필요", "", "핫멜트", "", ""),
    20: ("부분분류", "공압·진공", "포밍부(포머)", "솔밸브(종류 미상)", "현상 미기재"),
    21: ("부분분류", "분야 미상", "날인기", "세부 부품 미기재", "고장·이상"),
    22: ("규칙 미일치", "", "랩어플리케이터", "", ""),
    23: ("규칙 미일치", "", "", "", ""),
    24: ("부분분류", "전기·제어", "필러·충진기", "세부 부품 미기재", "에러코드 발생"),
    25: ("규칙 미일치", "", "필름·필로우 포장기", "", ""),
    26: ("규칙 미일치", "", "", "", ""),
    27: ("규칙분류", "공정·운전", "랩어라운드 케이서", "제품·자재", "터짐"),
}


@pytest.fixture(scope="module")
def classifier():
    return FaultClassifier(build_rules())


@pytest.fixture(scope="module")
def normalization():
    return json.loads((ROOT / "config/normalization.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"feedback-row-{case['row']}")
def test_first_26_feedback_records(case, classifier, normalization):
    row = classifier.classify(
        prepare_text(case["raw"], normalization),
        case["small"],
        prepare_text(case["small"], normalization),
        equipment_context=prepare_text(case["mid"], normalization),
        source_text=case["raw"],
    )
    assert (
        tuple(row[key] for key in ("status", "major", "detail_equipment", "middle", "minor"))
        == EXPECTED[case["row"]]
    )
    if row["status"] not in (K["auto"], K["partial"]):
        assert not parse_components(row["component_details"])
    if case["row"] == 20:
        assert row["repair_actions"] == "교체" and row["minor"] == "현상 미기재"
    if case["row"] == 24:
        assert row["part_count"] == 0  # WAGO brand/address is not an identified failed controller.


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("제품 터", "제품 터짐"),
        ("제품터", "제품 터짐"),
        ("아이마크 감지 불", "아이마크 감지 불량"),
        ("아이마크감지불", "아이마크감지 불량"),
        ("열전사에러발생 장비교체", "열전사 에러 발생 장비 교체"),
        ("핫멜", "핫멜트"),
        ("컴퓨터 모터 인버터 불꽃", "컴퓨터 모터 인버터 불꽃"),
        ("불 / 불 점검", "불 / 불 점검"),
        ("제품터미널", "제품터미널"),
    ],
)
def test_normalization_restores_only_supported_endings_and_is_stable(raw, expected, normalization):
    actual = prepare_text(raw, normalization)
    assert actual == expected
    assert prepare_text(actual, normalization) == actual


def test_mes_refines_generic_wrapper_but_does_not_replace_explicit_printer(classifier):
    generic = classifier.classify(
        "포장기 무접점홀더 고장", equipment_context="M/Y 필로우 포장기 #1"
    )
    assert generic["detail_equipment"] == "필름·필로우 포장기"
    explicit = classifier.classify("열전사 에러", equipment_context="M/Y 필로우 포장기 #1")
    assert explicit["detail_equipment"] == "날인기"
    assert not classifier.equipment.mentions("refiller")


@pytest.mark.parametrize(
    "source", ["아이마크 밀림", "wago 31", "wago 31 발생 없음", "wago 31 발생 예방 점검"]
)
def test_bare_marks_addresses_and_negated_or_planned_codes_are_not_confirmed(classifier, source):
    result = classifier.classify(source, equipment_context="Serac Filler")
    assert result["status"] != K["auto"]
    assert result["part_count"] == 0
    assert result["minor"] != "에러코드 발생"


def test_completed_replacement_and_suspected_cause_have_distinct_boundaries(classifier):
    assert len(clauses("솔밸브 교체, 공압 수분 문제 추정")) == 2
    assert len(clauses("가이드, 후크 교체")) == 1
    for source in ["솔밸브 교체 예정, 공압 문제 추정", "솔밸브 고장 의심 후 교체"]:
        row = classifier.classify(source)
        assert row["status"] not in (K["auto"], K["partial"])


def test_liquid_hopper_domain_rule_is_limited_to_approved_context(classifier):
    row = classifier.classify("충전부 초코 막힘")
    assert row["middle"] == "호퍼" and row["major"] == "공정·운전"
    plain = classifier.classify("필러 호퍼 파손")
    assert plain["middle"] == "호퍼" and plain["major"] == "기계"


def test_renamed_former_master_upgrades_without_reintroducing_removed_defaults():
    before = [{"name": "포밍부", "aliases": ["포밍부"]}]
    bundled = [{"name": "포밍부(포머)", "aliases": ["포밍부", "포머"]}]
    assert merge_named_defaults(before, bundled, before)[0] == bundled
    custom = [{"name": "포밍부", "aliases": ["포밍부", "현장 포머"]}]
    assert {item["name"] for item in merge_named_defaults(custom, bundled, before)[0]} == {
        "포밍부",
        "포밍부(포머)",
    }


def test_new_equipment_names_do_not_hide_explicit_parts_or_turn_compound_names_into_products(
    classifier,
):
    repaired = classifier.classify("핫멜트 분사 불량 / 노즐 교체")
    assert repaired["middle"] == "노즐(용도 미상)"
    for source in ["제품 흡착패드 타이밍 불량", "제품 정렬판 레버 휨"]:
        assert classifier.classify(source)["middle"] != "제품·자재"
