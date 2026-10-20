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
    assert len(categories) == 237 and len(catalog["groups"]) == 58
    assert len({item["major"] for item in categories}) == 6
    paths = {(item["major"], item["middle"], item["minor"]) for item in categories}
    assert len(paths) == 237
    assert {item["source_row"] for item in categories} == set(range(6, 243))
    assert re.fullmatch("[a-f0-9]{64}", catalog["source"]["sha256"])
    assert (
        catalog["source"]["sha256"]
        == "6c4158911b05e5e438cdd97c158b2287ada7b9c4a3f7092a302917726b488f30"
    )
    assert all(item["source"]["sha256"] == catalog["source"]["sha256"] for item in categories)
    assert all(item["source"]["sheet"] == "세부유형근거" for item in categories)
    assert all(item["aliases"] and item["definition"] for item in categories)


def test_every_selection_has_one_enabled_component_rule(catalog, normalization):
    rules = build_rules(catalog, normalization)
    assert len(rules) == 237
    assert all(rule["enabled"] and rule["role"] == "component" for rule in rules)
    assert len({rule["id"] for rule in rules}) == 237
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
        "히팅박스 TC 교체",
        "WAGO31 재부팅",
        "와고29 에러",
        "실린더커넥터 교체",
        "cylinder connector 교체",
        "압축 공기 공급불량",
        "APC 교체",
        "monkey 교체",
        "센서 정상 / 펌프 교체 예정",
        "근접센서",
    ],
)
def test_ambiguous_or_absent_part_names_are_not_guessed(classifier, text):
    result = classifier(text)
    assert result["status"] == K["unclassified"]
    assert result["component_count"] == 0


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
