"""The approved component catalogue is selectable, reproducible and conservative."""

import json
import re
from pathlib import Path

import pytest

from core.classification_catalog import catalog_categories
from core.classifier import RuleClassifier
from core.fault_components import parse_components
from core.i18n import K
from core.parsing import prepare_text
from core.rules import read_rules
from tools.make_rules import build_rules, load_catalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def normalization():
    return json.loads((ROOT / "config" / "normalization.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def classifier(catalog, normalization):
    engine = RuleClassifier(build_rules(catalog, normalization))
    return lambda text: engine.classify(prepare_text(text, normalization))


def test_approved_paths_and_source_rows_are_complete(catalog):
    categories = catalog["categories"]
    # Keep the original 237 paths and three user decisions. The yearly MES
    # exports additionally evidence a PLC card, a suction valve and two bodies.
    sourced = [
        item for item in categories if item["source"].get("sha256") == catalog["source"]["sha256"]
    ]
    decided = [item for item in categories if item["source"].get("type") == "user_decision"]
    observed = [item for item in categories if item["source"].get("type") == "three_year_observed"]
    feedback = [item for item in categories if item["source"].get("type") == "user_feedback"]
    assert (
        len(sourced) == 237
        and len(decided) == 3
        and len(observed) == 4
        and len(feedback) == 4
        and len(categories) == 248
    )
    assert {row["minor"] for row in observed} == {
        "PLC 카드",
        "석션 제어밸브",
        "열풍건조기(세부 부품 미상)",
        "냉각수 공급부(세부 부품 미상)",
    }
    assert {source["sha256"] for row in observed for source in row["sources"]} <= {
        source["sha256"] for source in catalog["three_year_sources"]
    }
    assert len(catalog["groups"]) == 59
    assert all(item["kind"] == "process" for item in decided)
    assert len({item["major"] for item in categories}) == 6
    paths = {(item["major"], item["middle"], item["minor"]) for item in categories}
    assert len(paths) == 248
    assert {item["source_row"] for item in sourced} == set(range(6, 243))
    assert re.fullmatch("[a-f0-9]{64}", catalog["source"]["sha256"])
    assert (
        catalog["source"]["sha256"]
        == "6c4158911b05e5e438cdd97c158b2287ada7b9c4a3f7092a302917726b488f30"
    )
    assert all(item["source"]["sha256"] == catalog["source"]["sha256"] for item in sourced)
    assert all(item["source"]["sheet"] == "세부유형근거" for item in sourced)
    assert all(item["aliases"] and item["definition"] for item in categories)


def test_every_selection_has_one_enabled_rule_and_part_less_rules_are_nopart(
    catalog, normalization
):
    rules = build_rules(catalog, normalization)
    assert len(rules) == 249
    assert all(rule["enabled"] for rule in rules)
    assert sum(rule["role"] == "component" for rule in rules) == 245
    process = {
        (item["major"], item["middle"], item["minor"])
        for item in catalog["categories"]
        if item["kind"] == "process"
    }
    nopart = {
        (rule["major"], rule["middle"], rule["minor"]) for rule in rules if rule["role"] == "nopart"
    }
    assert nopart == process | {("전기·제어", "제어기·I/O·통신", "제어기(종류 미상)")}
    assert len({rule["id"] for rule in rules}) == 249
    assert all(rule["id"].startswith("CAT_") for rule in rules)
    expected = {(item["major"], item["middle"], item["minor"]) for item in catalog["categories"]}
    assert set(catalog_categories(rules)) == expected
    assert all(rule["symptom"] != "." for rule in rules)
    for rule in rules:
        for field in ("context", "symptom", "exclude"):
            assert len(rule[field]) <= 1000
            re.compile(rule[field], re.I)


def test_exported_rules_reproduce_the_canonical_catalogue(catalog, normalization):
    assert read_rules(ROOT / "config" / "classification_config.xlsx") == build_rules(
        catalog, normalization
    )


def test_retired_defaults_remain_known_to_migration(catalog):
    history = json.loads((ROOT / "config" / "defaults_history.json").read_text(encoding="utf-8"))
    assert len(catalog["legacy_rule_ids"]) == 67
    assert all(history["rules"].get(rule_id) for rule_id in catalog["legacy_rule_ids"])
    assert not set(catalog["legacy_rule_ids"]) & {rule["id"] for rule in build_rules(catalog)}


@pytest.mark.parametrize("text", ["광전센서 손상", "PLC 손상", "센서 마모"])
def test_explicit_physical_damage_matches_parts_across_families(classifier, text):
    result = classifier(text)
    assert result["status"] == K["auto"]
    assert result["component_count"] == 1


@pytest.mark.parametrize(
    "text,minor",
    [
        ("근접센서 교체", "근접센서"),
        ("광전센서 교체", "광전센서"),
        ("타이밍벨트 끊어짐", "타이밍벨트"),
        ("V벨트 파손", "V벨트"),
        ("V-벨트 교체", "V벨트"),
        ("C/V벨트 교체", "컨베어벨트"),
        ("센서 반사경 교체", "센서 반사경"),
        ("TC선 단선 교체", "TC 센서선"),
        ("T.C 센서 교체", "온도센서(방식 미상)"),
        ("T/C센서 교체", "온도센서(방식 미상)"),
        ("에어커넥터 누설 교체", "에어커넥터"),
        ("실린더로드 파손 교체", "실린더로드"),
        ("실린더축 파손", "실린더로드"),
        ("서보모터컨트롤러 교체", "서보컨트롤러"),
        ("마그네틱필터 교체", "마그네틱필터"),
        ("고정블록단자 교체", "단자대·블록단자"),
        ("스크르우기어 교체", "스크류기어"),
        ("볼트 풀리면서 이탈", "볼트"),
        ("PC재부팅", "컴퓨터·PC"),
        ("WAGO3모듈카드 교체", "제어모듈·카드"),
        ("i/o터미널모듈 교체", "I/O 터미널 모듈"),
        ("(플라스틱) 벨트 교체", "플라스틱벨트"),
        ("Sol v/v 교체", "솔밸브(종류 미상)"),
        ("motor trip", "모터(종류 미상)"),
        ("sensor error", "센서(종류 미상)"),
        ("pump fault", "펌프(종류 미상)"),
        ("bearing 교체", "베어링(종류 미상)"),
        ("belt 파손", "벨트(종류 미상)"),
        ("chain 교체", "체인(종류 미상)"),
        ("cylinder 파손", "실린더(종류 미상)"),
        ("air connector 교체", "에어커넥터"),
        ("PLC error", "PLC"),
        ("PLC 카드 접점 불량", "PLC 카드"),
        ("PLC카드 교체", "PLC 카드"),
        ("메인 보드 교체", "메인보드"),
        ("베아링 파손", "베어링(종류 미상)"),
        ("쎈서 미감지", "센서(종류 미상)"),
        ("썸머카플 교체", "열전대(써머커플)"),
        ("가스킷 손상", "가스켓"),
        ("메카니컬씰 누설", "메카니칼씰"),
        ("히타 교체", "히터"),
        ("석션자동컨트롤밸브 고장", "석션 제어밸브"),
        ("ICM 밸브 교체", "석션 제어밸브"),
        ("냉각수공급부라인 파손", "배관"),
        ("리데나 누설", "리데나"),
        ("씽크탑 교체", "밸브 제어헤드"),
        ("열풍건조기 고장", "열풍건조기(세부 부품 미상)"),
        ("냉각수 공급부 고장", "냉각수 공급부(세부 부품 미상)"),
        ("히팅박스 TC 교체", "열전대(써머커플)"),
    ],
)
def test_named_components_keep_their_specific_type(classifier, text, minor):
    result = classifier(text)
    assert result["minor"] == minor
    assert result["status"] == K["auto"]
    assert result["component_count"] == 1
    assert "score" not in " ".join(result)


@pytest.mark.parametrize(
    "text",
    [
        "TC 교체",
        "실린더커넥터 교체",
        "cylinder connector 교체",
        "압축 공기 공급불량",
        "APC 교체",
        "monkey 교체",
        "센서 정상 / 펌프 교체 예정",
        "근접센서",
        "열풍건조기 정상",
        "열풍건조기 교체 예정",
    ],
)
def test_ambiguous_or_absent_part_names_are_not_guessed(classifier, text):
    result = classifier(text)
    assert result["status"] == K["rule_unmatched"]
    assert result["component_count"] == 0


def test_new_body_suspicion_is_not_automatically_confirmed(catalog, normalization):
    from core.failure_classification import FaultClassifier

    engine = FaultClassifier(build_rules(catalog, normalization))
    result = engine.classify(prepare_text("냉각수공급부 고장 의심", normalization))
    assert result["status"] == K["review"]


@pytest.mark.parametrize("text", ["sealer 고장", "packing machine 고장"])
def test_english_equipment_names_do_not_become_seal_parts(classifier, text):
    result = classifier(text)
    parts = {item.get("minor") for item in parse_components(result.get("components", ""))}
    assert "씰·패킹(종류 미상)" not in parts
    assert result.get("minor") != "씰·패킹(종류 미상)"


@pytest.mark.parametrize(
    "text,minor",
    [
        ("펌프 교체", "펌프(종류 미상)"),
        ("실린더 파손", "실린더(종류 미상)"),
        ("센서 교체", "센서(종류 미상)"),
        ("벨트 파손", "벨트(종류 미상)"),
        ("서보 에러", "서보 구동부(세부 미상)"),
        ("용수탱크 리크", "탱크(세부 부품 미상)"),
    ],
)
def test_unspecified_types_do_not_invent_more_specific_parts(classifier, text, minor):
    assert classifier(text)["minor"] == minor


@pytest.mark.parametrize(
    "text, minor",
    [
        # Overlapping names of one part, repeated in a later clause.
        ("몰드 체인 연결핀 끊어짐 / 연결핀 용접, 교체", "체인연결핀"),
        # Only one listed part has failure or repair evidence; the other was serviced.
        ("필러 브러쉬 청소 및 필러 17,18번 카드 교체", "제어기판·카드(종류 미상)"),
        ("버켓 교체 및 포장 집적부 실린더 조정", "버켓"),
    ],
)
def test_one_evidenced_type_after_grouping_is_confirmed(classifier, text, minor):
    result = classifier(text)
    assert result["status"] == K["auto"], result
    assert result["review_code"] == ""
    assert result["classification_mode"] == "single"
    assert result["minor"] == minor


@pytest.mark.parametrize(
    "text, minor",
    [
        ("몰드체인 연결핀 끊어짐", "체인연결핀"),  # Same family: the specific part.
        ("s자 플랙시블 컨베어 이탈", "플렉시블컨베어"),  # Truncated specific alias.
        ("플렉시블 컨베어 날개 파손", "컨베어날개"),  # Other family: the head noun.
    ],
)
def test_overlapping_part_names_resolve_to_one_part(classifier, text, minor):
    result = classifier(text)
    assert result["status"] == K["auto"], result
    assert result["minor"] == minor
    assert result["candidates"].count("|") == 0, result["candidates"]


@pytest.mark.parametrize(
    "text, minors",
    [
        (
            "포장 기립컨베어 2라인 베어링 및 축 마모로 인한 운휴",
            {"베어링(종류 미상)", "축(종류 미상)"},
        ),
        ("제품이송 컨베이어 모터, 감속기 교체", {"모터(종류 미상)", "감속기(종류 미상)"}),
        ("#29 씰러 히터및 ssr 교체", {"히터", "SSR"}),
        # '밸브' inside '솔밸브' must not cut the sensor off from '교체'.
        ("컵 공급센서, 솔밸브 교체 및 실린더 센서 고정", {"센서(종류 미상)", "솔밸브(종류 미상)"}),
    ],
)
def test_parts_listed_with_one_failure_statement_form_a_confirmed_combination(
    classifier, text, minors
):
    result = classifier(text)
    assert result["status"] == K["auto"], result
    assert result["review_code"] == ""
    assert result["classification_mode"] == "multiple"
    assert result["major"] == "복수 고장"
    assert {member["minor"] for member in parse_components(result["component_details"])} == minors


@pytest.mark.parametrize(
    "text",
    [
        "모터, 감속기 고장 의심",  # A suspicion is not a recorded fault.
        "캡 소진감지센서, 솔밸브 동작 이상으로 전기반 점검조치 , 광센서 교체",
        "구동 모터 교체 / 감속기 교체",  # Separate statements stay a user decision.
    ],
)
def test_uncertain_or_separate_listings_remain_under_review(classifier, text):
    result = classifier(text)
    assert result["status"] == K["review"], result


def test_connection_location_does_not_assign_replacement_to_mainboard(classifier):
    result = classifier("엔드하단선 메인보드와연결되는 선 교체")
    assert result["status"] == K["auto"]
    assert result["minor"] == "배선(종류 미상)"
    assert result["classification_mode"] == "single"
    assert "메인보드" not in {m["minor"] for m in parse_components(result["component_details"])}


def test_real_multiple_types_and_explicit_alternatives_remain_distinct(classifier):
    multiple = classifier("근접센서 고장 / 별도로 광전센서 교체")
    assert multiple["status"] == K["review"]
    assert multiple["review_code"] == "multiple_faults"
    assert {member["minor"] for member in parse_components(multiple["component_details"])} == {
        "근접센서",
        "광전센서",
    }
    alternative = classifier("근접센서 고장 또는 광전센서 고장")
    assert alternative["status"] == K["review"]
    assert alternative["review_code"] == "alternative_types"
    assert alternative["component_count"] == 1
