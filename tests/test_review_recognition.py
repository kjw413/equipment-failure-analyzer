"""Source-backed recognition fixes do not change uncertainty into observed faults."""

import json
import shutil
from pathlib import Path

import pytest

from core.classifier import RuleClassifier, clauses
from core.config import ConfigStore
from core.defaults_merge import rule_digest
from core.failure_modes import action_names, extract_actions, symptom_names
from core.parsing import prepare_text
from core.rules import read_rules, write_rules
from tools.make_rules import build_rules, load_catalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def engine():
    normalization = json.loads((ROOT / "config/normalization.json").read_text("utf-8"))
    classifier = RuleClassifier(build_rules(load_catalog(), normalization))

    def recognize(text):
        chunks = clauses(prepare_text(text, normalization))
        return classifier.eligible_pairs(classifier.pairs(chunks), chunks)

    return recognize


def observed(pairs):
    return {
        (pair.rule["minor"], mode)
        for pair in pairs
        for mode in symptom_names(
            [s.text for s in pair.symptoms if s.kind == "F"],
            pair.context + "".join(s.text for s in pair.symptoms),
        )
    }


@pytest.mark.parametrize(
    "text,part,mode",
    [
        ("포밍몰드냉각수리크", "몰드", "누설"),
        ("롤스텐드 구동부 카플링 파손", "커플링", "손상·파손"),
        ("센터 씰러 테파롤러 베어링 고착으로 교체", "베어링(종류 미상)", "막힘·걸림"),
        ("3번 충진실린더 소손으로 교체", "실린더(종류 미상)", "소손·단락"),
        ("로킹부 스프링 소손 교체", "스프링(종류 미상)", "소손·단락"),
        ("컨베어벨트소손으로 교체", "컨베어벨트", "소손·단락"),
        ("제품로봇원점틀어짐", "로봇(세부 부품 미상)", "위치·설정이상"),
        ("스틱운반컨베어 원점틀어짐", "컨베어(종류 미상)", "위치·설정이상"),
        ("탱크 레벨센서 헌팅으로 밸브 폐쇄", "레벨센서(방식 미상)", "감지불량"),
        ("a번 날인기 온도 이상", "날인기(종류 미상)", "온도이상"),
        ("센터씰러 단선 오류", "센터씰러", "단선"),
        ("엔드씰러 온도 불량", "엔드씰러", "온도이상"),
        ("BIB 충진용 자바라 끝단 이음새에서 리크", "충진호스", "누설"),
        ("초코 디핑 솔밸브 망가짐", "솔밸브(종류 미상)", "고장·이상"),
    ],
)
def test_explicit_observations_are_bound_to_the_named_part(engine, text, part, mode):
    assert (part, mode) in observed(engine(text))


def test_cooling_water_leak_is_not_a_repair_even_with_legacy_custom_pattern(engine):
    assert extract_actions("포밍몰드냉각수리크") == []
    assert action_names(["냉각수리크"]) == []
    assert all(s.kind == "F" for pair in engine("포밍몰드냉각수리크") for s in pair.symptoms)
    old = RuleClassifier(
        [
            {
                "id": "test",
                "enabled": True,
                "priority": 80,
                "major": "기계",
                "middle": "성형기구",
                "minor": "몰드",
                "context": "몰드",
                "symptom": "수리|리크",
                "exclude": "",
                "role": "component",
            }
        ],
        {"replace_pattern": "교체|수리"},
    )
    assert [s.text for p in old.pairs(clauses("몰드냉각수리크")) for s in p.symptoms] == ["리크"]


def test_tc_abbreviation_requires_heating_context_and_keeps_tc_wire_separate(engine):
    pairs = engine("히팅박스 포밍상부 tc교체")
    assert any(p.rule["minor"] == "열전대(써머커플)" and "R" in p.kinds() for p in pairs)
    assert not engine("tc교체")
    assert all(p.rule["minor"] != "열전대(써머커플)" for p in engine("센터씰러 tc선 고장 교체"))
    assert any(p.rule["minor"] == "TC 센서선" for p in engine("센터씰러 tc선 고장 교체"))


def test_existing_user_confirmed_pump_alias_is_preserved(engine):
    pairs = engine("부스터 펌프 베어링 소손")
    # This special phrase was explicitly confirmed by the user on 2026-10-20.
    assert ("부스터펌프", "소손·단락") in observed(pairs)


def test_a_failure_is_not_shared_with_an_independently_replaced_part(engine):
    values = observed(engine("베어링 고착 / 센서 교체"))
    assert ("베어링(종류 미상)", "막힘·걸림") in values
    assert not any(part.startswith("센서") for part, _ in values)


@pytest.mark.parametrize(
    "text",
    ["베어링 고착 없음", "베어링 고착되지않음", "베어링 고착 예방 점검", "베어링 파손 방지 점검"],
)
def test_negative_and_preventive_failures_are_not_observations(engine, text):
    assert observed(engine(text)) == set()


def test_future_repair_is_not_completed_work(engine):
    pairs = engine("베어링 교체 예정 / 센서 감지불량")
    assert all(
        s.kind != "R" for p in pairs if p.rule["minor"].startswith("베어링") for s in p.symptoms
    )
    assert extract_actions("베어링 교체 예정") == []


def test_unqualified_bellows_does_not_become_a_fluid_hose(engine):
    assert not any("호스" in p.rule["minor"] for p in engine("축 자바라 커버 파손"))


def test_v113_upgrade_updates_defaults_and_preserves_user_edits_and_manual_bytes(tmp_path):
    source = ROOT / "config"
    profile = tmp_path / "profile"
    directory = profile / "config"
    shutil.copytree(source, directory)
    prior = json.loads((ROOT / "tests/fixtures/v113_review_defaults.json").read_text("utf-8"))
    old = {row["id"]: row for row in prior["rules"]}
    current = {row["id"]: row for row in read_rules(source / "classification_config.xlsx")}
    previous = {**current, **old}
    user_rules = {key: dict(row) for key, row in previous.items()}
    del user_rules["CAT_M_AE7B25F"]
    user_rules["CAT_M_7DA5883"]["enabled"] = False
    user_rules["CAT_E_C253B27"]["context"] += "|USER_THERMOCOUPLE"
    write_rules(directory / "classification_config.xlsx", list(user_rules.values()))
    catalog = json.loads((directory / "classification_catalog.json").read_text("utf-8"))
    catalog["catalog_version"] = "1.13.0"
    catalog["installed_signature"] = "prior-v113-profile"
    catalog["installed_rules"] = {key: rule_digest(row) for key, row in previous.items()}
    (directory / "classification_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False), "utf-8"
    )
    normal_path = directory / "normalization.json"
    normal = json.loads(normal_path.read_text("utf-8"))
    for new_name in ("카플링", "카풀링", "타 이밍"):
        normal["replacements"].pop(new_name)
    normal["replacements"]["모타"] = "현장 전용 모터"
    del normal["replacements"]["컨베이어"]
    normal_path.write_text(json.dumps(normal, ensure_ascii=False), "utf-8")
    manual = '{"existing":{"major":"기계","detail_equipment":"컨베어","middle":"베어링(종류 미상)","minor":"마모","classification_schema":"equipment_part_failure_v3"}}'.encode()
    manual_path = directory / "manual_overrides.json"
    manual_path.write_bytes(manual)

    loaded = ConfigStore(profile).load()
    installed = {row["id"]: row for row in loaded["rules"]}
    assert installed["CAT_M_53B6486"] == current["CAT_M_53B6486"]
    assert installed["CAT_E_C253B27"] == user_rules["CAT_E_C253B27"]
    assert installed["CAT_M_7DA5883"]["enabled"] is False
    assert "CAT_M_AE7B25F" not in installed
    replacement = loaded["normalization"]["replacements"]
    assert replacement["카플링"] == "커플링"
    assert replacement["모타"] == "현장 전용 모터"
    assert "컨베이어" not in replacement
    assert manual_path.read_bytes() == manual


@pytest.mark.parametrize(
    "suffix", ["브라인교체", "새용액교체", "미등록물질교체", "브라인교체/교체"]
)
def test_unknown_new_subject_breaks_previous_part_continuation(engine, suffix):
    pairs = engine("몰드 고착/" + suffix)
    mold = [pair for pair in pairs if pair.rule["minor"] == "몰드"]
    assert mold and any("F" in pair.kinds() for pair in mold)
    assert all("R" not in pair.kinds() for pair in mold)


@pytest.mark.parametrize("continuation", ["교체", "후교체", "신품교체", "파손/교체"])
def test_subjectless_adjacent_repair_clauses_still_continue_the_part(engine, continuation):
    pairs = engine("로드리스 실린더/" + continuation)
    assert any("실린더" in pair.rule["minor"] and "R" in pair.kinds() for pair in pairs)


def test_person_name_list_does_not_supply_a_failure_to_the_previous_part(engine):
    pairs = engine("이찬우/8번포장기 앤드씰러 정비/이상영,이찬우")
    assert not any(mode == "고장·이상" for _, mode in observed(pairs))
    assert any("R" in pair.kinds() for pair in pairs)
    assert observed(engine("베어링,실린더 파손")) >= {
        ("베어링(종류 미상)", "손상·파손"),
        ("실린더(종류 미상)", "손상·파손"),
    }


@pytest.mark.parametrize("text", ["세척장 벨트 교체", "세척기 고장", "세척설비 정비"])
def test_washing_equipment_nouns_do_not_imply_completed_cleaning(text):
    assert "청소·급유" not in extract_actions(text)


def test_explicit_cleaning_after_a_washing_equipment_name_is_still_an_action():
    assert "청소·급유" in extract_actions("세척기 세척 완료")


@pytest.mark.parametrize(
    "text", ["베어링 교체늦음", "베어링 늦은교체", "베어링 교체지연", "베어링 교체대기"]
)
def test_delayed_or_waiting_replacement_is_not_completed_work(engine, text):
    assert "교체" not in extract_actions(text)
    assert all("R" not in pair.kinds() for pair in engine(text))


def test_completed_independent_repair_remains_when_another_repair_is_waiting(engine):
    text = "베어링 교체대기/센서 교체완료"
    assert extract_actions(text) == ["교체"]
    assert any(
        pair.rule["minor"] == "센서(종류 미상)" and "R" in pair.kinds() for pair in engine(text)
    )
