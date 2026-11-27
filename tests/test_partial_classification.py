"""Missing source information is retained separately from classification conflict."""

import json
from pathlib import Path

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.classification_candidates import parse_candidates
from core.classification_completeness import missing_fields
from core.classification_policy import unresolved_classifications
from core.corrections import correction_patch, initial_values
from core.failure_classification import FaultClassifier
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import K
from core.parsing import prepare_text
from tools.make_rules import build_rules

ROOT = Path(__file__).resolve().parents[1]


def assert_top_representative(result):
    candidates = parse_candidates(result["classification_candidates"], strict=True)
    (member,) = parse_components(result["component_details"], strict=True)
    expected = tuple(candidates[0][field] for field in CATEGORY_FIELDS)
    assert tuple(result[field] for field in CATEGORY_FIELDS) == expected
    assert tuple(member[field] for field in CATEGORY_FIELDS) == expected
    assert member["selection_method"] == "top_ranked_representative"
    assert member["selected_rank"] == candidates[0]["rank"] == 1
    assert member["rule_id"] == candidates[0]["rule_id"]
    assert member["evidence"] == candidates[0]["evidence"]
    assert result["status"] == (K["partial"] if missing_fields(result) else K["auto"])
    assert result["classification_mode"] == "single" and result["component_count"] == 1
    assert result["part_count"] == (
        0 if member["middle"] in {"세부 부품 미기재", "제품·자재"} else 1
    )
    assert result["review_code"] == ""
    assert "1순위" in result["classification_reason"] and "대표" in result["classification_reason"]
    return candidates


@pytest.fixture(scope="module")
def classify():
    normalization = json.loads((ROOT / "config/normalization.json").read_text(encoding="utf-8"))
    engine = FaultClassifier(build_rules())
    return lambda text: engine.classify(prepare_text(text, normalization))


@pytest.mark.parametrize(
    "source, part, mode",
    [
        ("베어링 교체", "베어링(종류 미상)", "현상 미기재"),
        ("모터 교체", "모터(종류 미상)", "현상 미기재"),
        ("프리저 고장", "세부 부품 미기재", "고장·이상"),
        ("베어링 파손", "베어링(종류 미상)", "손상·파손"),
    ],
)
def test_partial_classification_keeps_known_axes_and_missing_values(classify, source, part, mode):
    result = classify(source)
    assert result["status"] == K["partial"]
    assert result["middle"] == part and result["minor"] == mode
    assert result["classification_mode"] == "single"
    assert result["classification_missing_fields"]
    assert missing_fields(result)
    (member,) = parse_components(result["component_details"])
    assert member["middle"] == part and member["minor"] == mode
    assert result["part_count"] == (0 if part == "세부 부품 미기재" else 1)


def test_complete_observed_classification_has_no_missing_axis(classify):
    result = classify("컨베어 베어링 파손 후 교체")
    assert result["status"] == K["auto"]
    assert result["classification_missing_fields"] == ""
    assert missing_fields(result) == ()


@pytest.mark.parametrize(
    "source,domain",
    [
        ("프리저 냉매 배관 누설", "온도·냉각"),
        ("프리저 냉각수 배관 누설", "유체·배관"),
        ("에어 공급 배관 누설", "공압·진공"),
        ("냉매 밸브 정상 / 냉각수 배관 누설", "유체·배관"),
    ],
)
def test_only_adjacent_medium_qualifies_pipe_domain(classify, source, domain):
    row = classify(source)
    assert row["status"] in (K["auto"], K["partial"])
    assert row["major"] == domain
    assert row["minor"] == "누설"


def test_truncated_operating_statement_does_not_invent_repair(classify):
    source = "설비 메인에어압 저하로 설비 정"
    assert prepare_text(source, {"clause_end_expansions": {"정": "정비"}}) == source
    row = classify(source)
    assert row["repair_actions"] == ""
    assert row["status"] not in (K["auto"], K["partial"])


def test_later_machine_and_its_mes_area_do_not_locate_earlier_fault():
    engine = FaultClassifier(build_rules())
    row = engine.classify(
        "성형몰드 고착되어서 정지 발생 이후 프리저 다운 / 밸브 세척 후 생산",
        equipment_context="FREEZER #1",
    )
    assert row["status"] == K["partial"]
    assert (row["middle"], row["minor"]) == ("몰드", "막힘·걸림")
    assert row["detail_equipment"] == "상세설비 미상"
    assert row["detail_equipment_source"] == "미기재"


def test_unrecognized_separate_fault_is_not_hidden_by_machine_outcome(classify):
    row = classify("씰러 온도 다운 / 무접점 홀더 소손 및 홀더 교체")
    assert row["status"] == K["review"]
    assert row["review_code"] == "unmapped_fault_context"
    assert not parse_components(row["component_details"])


@pytest.mark.parametrize(
    "source,part",
    [
        ("컨베이어 (브라쉬) 파손 교체", "브러시"),
        ("구동볼트 파손. 파손부위 용접", "볼트"),
    ],
)
def test_attached_parenthetical_or_repeated_fault_is_not_new_subject(classify, source, part):
    row = classify(source)
    assert row["status"] in (K["auto"], K["partial"])
    assert row["middle"] == part
    assert row["minor"] == "손상·파손"
    assert row["repair_actions"]


def test_repair_restatement_with_new_subject_still_requires_review(classify):
    row = classify("구동볼트 파손. 파손부위 용접 및 무접점홀더 소손")
    assert row["status"] == K["review"]


@pytest.mark.parametrize("tail", ["무접점 홀더 소손 없음", "무접점 홀더 소손 점검 예정"])
def test_negated_or_planned_unrecognized_subject_is_not_competing_fault(classify, tail):
    row = classify("씰러 고장 / " + tail)
    assert row["status"] == K["partial"]
    assert row["middle"] == "세부 부품 미기재"


@pytest.mark.parametrize(
    "source", ["그리퍼 위치", "프리저", "정비", "센서 교체 예정", "프리저 정상", "베어링 교체 안함"]
)
def test_context_only_and_unperformed_work_are_not_partial_automatic(classify, source):
    result = classify(source)
    assert result["status"] not in (K["auto"], K["partial"])
    assert not parse_components(result["component_details"])


def test_independent_observed_faults_keep_all_candidates_and_select_rank_one(classify):
    result = classify("컨베어 베어링 마모 / 별도로 센서 감지불량")
    candidates = assert_top_representative(result)
    assert {(item["middle"], item["minor"]) for item in candidates} == {
        ("베어링(종류 미상)", "마모"),
        ("센서(종류 미상)", "감지불량"),
    }
    assert result["component_count"] == result["part_count"] == 1


@pytest.mark.parametrize(
    "source,part,mode",
    [
        ("히터 단선 및 볼트 교체", "히터", "단선"),
        ("베어링 손상 / 센서 교체", "베어링(종류 미상)", "손상·파손"),
        ("차단기 떨어짐 / 메카니컬씰 교체", "차단기", "보호장치 동작"),
        ("컨베어 레일 이탈로 걸림", "레일(종류 미상)", "이탈·풀림"),
    ],
)
def test_unique_direct_fault_is_retained_over_repair_or_stated_result(classify, source, part, mode):
    row = classify(source)
    assert row["status"] in (K["auto"], K["partial"])
    assert (row["middle"], row["minor"]) == (part, mode)


@pytest.mark.parametrize(
    "source",
    [
        "베어링 손상 또는 센서 교체",
        "박스 공급 에어라인 및 피팅 교체",
    ],
)
def test_alternatives_and_unrecognized_joined_subjects_stay_under_review(classify, source):
    row = classify(source)
    assert row["status"] == K["review"]
    assert not parse_components(row["component_details"])


@pytest.mark.parametrize(
    "source, expected_parts",
    [
        ("베어링 손상 / 별도로 센서 교체", {"베어링(종류 미상)", "센서(종류 미상)"}),
        ("베어링 손상 / 원인은 센서 교체", {"베어링(종류 미상)", "센서(종류 미상)"}),
        ("컨베어 베어링 손상 / 펌프 씰 교체", {"베어링(종류 미상)", "씰·패킹(종류 미상)"}),
        ("모터 정지 / 센서 교체", {"모터(종류 미상)", "센서(종류 미상)"}),
        (
            "노즐 솔밸브 및 통신카드 점검",
            {"노즐(용도 미상)", "솔밸브(종류 미상)", "제어기판·카드(종류 미상)"},
        ),
    ],
)
def test_observed_faults_or_completed_work_select_top_one_and_keep_other_candidates(
    classify, source, expected_parts
):
    result = classify(source)
    candidates = assert_top_representative(result)
    assert {item["middle"] for item in candidates} == expected_parts
    assert len(candidates) == len(expected_parts)


def test_partial_is_complete_for_workflow_but_missing_data_is_explicit(classify):
    row = {**classify("베어링 교체"), "kind": K["fault"]}
    assert unresolved_classifications(pd.DataFrame([row])).empty
    row["minor"] = "교체"
    assert not unresolved_classifications(pd.DataFrame([row])).empty


def test_partial_editor_keeps_known_axes_and_action_change_does_not_confirm(classify):
    row = classify("컨베어 베어링 교체")
    initial = initial_values(row, {})
    assert initial["detail_equipment"] == "컨베어"
    assert initial["major"] == "기계"
    assert initial["minor"] == ""
    values = {**initial, "repair_actions": "교체, 점검"}
    assert correction_patch(initial, values, {}, False) == {"repair_actions": "교체, 점검"}


def test_partial_keeps_event_accounting_and_action_overrides(store, input_file):
    book = load_workbook(input_file)
    book["Events"].cell(4, 5).value = "컨베어 베어링 교체"
    book.save(input_file)
    book.close()
    before = input_file.read_bytes()
    first = analyze_file(store, input_file)
    row = first.selected.loc[first.selected.source_row.eq(4)].iloc[0]
    assert row.status == K["partial"]
    assert row.classification_missing_fields == "고장 현상"
    assert row.record_id in set(first.selected.loc[first.selected.kind.eq(K["fault"])].record_id)
    assert row.event_id not in set(first.tables["review"].event_id)
    store.update_override(row.event_id, {"repair_actions": "", "minutes": "17"})
    second = analyze_file(store, input_file)
    revised = second.selected.loc[second.selected.event_id.eq(row.event_id)].iloc[0]
    assert revised.status == K["partial"] and revised.minutes == 17
    assert revised.repair_actions == "" and revised["middle"] == row["middle"]
    assert input_file.read_bytes() == before
