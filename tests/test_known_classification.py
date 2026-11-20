"""Certain axes remain usable while missing or conflicting axes stay open."""

import json

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.classification_completeness import missing_fields
from core.component_analysis import component_tables, detailed_equipment_table
from core.corrections import initial_values
from core.failure_classification import FaultClassifier
from core.fault_components import parse_components
from core.i18n import K
from core.known_classification import KNOWN_FIELDS, known_fields
from report.classification import classification_result
from report.excel_report import SHEETS, export_report
from tools.make_rules import build_rules


@pytest.fixture(scope="module")
def classifier():
    return FaultClassifier(build_rules())


@pytest.mark.parametrize(
    "name, expected", [("필러", "필러·충진기"), ("카토닝머신", "카토닝머신"), ("컨베어", "컨베어")]
)
def test_repeated_general_problem_keeps_machine_without_inventing_part(classifier, name, expected):
    result = classifier.classify(f"A라인 {name} 반복적 문제 발생으로 조치 완료")
    assert result["status"] == K["partial"]
    assert result["detail_equipment"] == expected
    assert result["major"] == "분야 미상"
    assert result["middle"] == "세부 부품 미기재"
    assert result["minor"] == "고장·이상"
    assert set(missing_fields(result)) == {"major", "middle"}
    assert result["part_count"] == 0
    assert result["repair_actions"] == ""  # '조치 완료' does not mean replacement.
    assert len(parse_components(result["component_details"])) == 1


@pytest.mark.parametrize(
    "source",
    [
        "필러",
        "필러 정상",
        "필러 고장 없음",
        "필러 문제 없음",
        "필러 고장 의심",
        "필러 고장 예정",
        "필러 문제 점검 예정",
        "필러 고장 또는 센서 문제",
        "필러 고장 및 무접점홀더 소손",
        "필러 무접점홀더 고장",
        "필러 고장 예방 점검",
        "필러 이상유무 확인",
        "필러 고장 아님",
        "필러 문제 없었음",
    ],
)
def test_machine_fallback_does_not_confirm_bare_normal_planned_suspected_or_unknown_part(
    classifier, source
):
    row = classifier.classify(source)
    assert row["status"] not in (K["auto"], K["partial"])
    assert not parse_components(row["component_details"])


def test_suspected_part_preserves_location_only_and_stays_review(classifier):
    row = classifier.classify("컨베어 모터 또는 센서 고장 의심")
    assert row["status"] == K["review"]
    assert known_fields(row) == {"detail_equipment": "컨베어"}
    assert row["major"] == row["middle"] == row["minor"] == ""
    assert initial_values(row, {})["detail_equipment"] == "컨베어"
    assert initial_values(row, {"minutes": "13"})["detail_equipment"] == "컨베어"


def test_unknown_part_still_keeps_explicit_location(classifier):
    row = classifier.classify("필러 무접점홀더 고장")
    assert known_fields(row) == {"detail_equipment": "필러·충진기"}


def test_new_machine_fallback_does_not_rely_on_a_clipped_syllable_expansion(classifier):
    row = classifier.classify("필러 에러", source_text="필러 에")
    assert row["status"] not in (K["auto"], K["partial"])
    assert known_fields(row) == {"detail_equipment": "필러·충진기"}


def test_process_condition_is_preserved_without_inventing_failed_sensor(classifier):
    row = classifier.classify("프리저 점도 헌팅")
    assert row["status"] == K["review"]
    assert row["minor"] == "점도이상" and row["detail_equipment"] == "프리저"
    assert row["middle"] == "" and not parse_components(row["component_details"])


def test_conflicting_modules_do_not_become_a_known_first_candidate(classifier):
    row = classifier.classify("컨베어 베어링 파손 또는 펌프 베어링 파손")
    assert row["status"] == K["review"]
    assert row["detail_equipment"] == ""
    assert "detail_equipment" not in known_fields(row)


def test_unmapped_alternative_is_not_erased_by_the_only_recognized_part(classifier):
    row = classifier.classify("필러 고장 또는 센서 문제")
    assert row["status"] == K["review"]
    assert known_fields(row) == {"detail_equipment": "필러·충진기"}
    assert row["middle"] == row["minor"] == row["major"] == ""


def test_conflicting_source_locations_cannot_leak_an_unmarked_mes_fallback(classifier):
    row = classifier.classify("멀티포장기 프린터기 오류", equipment_context="포장기")
    assert row["status"] not in (K["auto"], K["partial"])
    assert row["detail_equipment"] == ""
    assert "detail_equipment" not in known_fields(row)


def test_registered_asset_is_not_an_independent_module_fact(classifier):
    row = classifier.classify("메인", registered_equipment="컨베어")
    assert not known_fields(row)
    coded = classifier.classify("메인", equipment_context="컨베어")
    assert known_fields(coded) == {"detail_equipment": "컨베어"}
    assert coded["detail_equipment_source"] == "비가동코드(중)"
    assert coded["status"] not in (K["auto"], K["partial"])


def test_old_or_mismatched_candidate_columns_are_not_known():
    assert known_fields({"detail_equipment": "컨베어"}) == {}
    assert (
        known_fields({"detail_equipment": "펌프", KNOWN_FIELDS: '{"detail_equipment":"컨베어"}'})
        == {}
    )


def test_pending_module_counts_once_but_candidates_do_not_count_as_failed_parts(classifier):
    records = []
    for index, source in enumerate(
        ["필러 반복적 문제 발생으로 조치 완료", "컨베어 모터 또는 센서 고장 의심", "메인"]
    ):
        records.append(
            {
                **classifier.classify(source),
                "record_id": str(index),
                "kind": K["fault"],
                "line": "A라인",
                "minutes": [10, 20, None][index],
            }
        )
    frame = pd.DataFrame(records)
    table = detailed_equipment_table(frame).set_index("detail_equipment")
    assert table["count"].sum() == 3 and table["total_minutes"].sum() == 30
    assert table.loc["필러·충진기", "count"] == table.loc["컨베어", "count"] == 1
    assert table.loc["컨베어", "review_count"] == 1
    assert pd.isna(table.loc["상세설비 미상", "total_minutes"])
    tables = component_tables(frame)
    assert tables["component"].empty
    assert tables["fault_detail"].loc[1, "detail_equipment"] == "컨베어"


def test_current_pipeline_and_report_keep_known_axes_and_equipment_statistics(
    store, input_file, tmp_path
):
    book = load_workbook(input_file)
    book["Events"].cell(4, 5).value = "필러 반복적 문제 발생으로 조치 완료"
    book["Events"].cell(5, 5).value = "컨베어 모터 또는 센서 고장 의심"
    book.save(input_file)
    book.close()
    original = input_file.read_bytes()
    result = analyze_file(store, input_file)
    pending = result.selected.loc[result.selected.source_row.eq(5)].iloc[0]
    assert pending.status == K["review"] and pending.detail_equipment == "컨베어"
    projected = classification_result(result)
    after = projected.selected.loc[projected.selected.source_row.eq(5)].iloc[0]
    assert known_fields(after.to_dict()) == {"detail_equipment": "컨베어"}
    details = projected.tables["fault_detail"]
    assert (
        details.loc[details.record_id.eq(pending.record_id), "detail_equipment"].iloc[0] == "컨베어"
    )
    stats = projected.tables["detailed_equipment"]
    assert stats["count"].sum() == len(result.selected)
    assert stats["total_minutes"].sum() == result.metrics["total_minutes"]
    exported = export_report(result, tmp_path / "known.xlsx")
    workbook = load_workbook(exported, data_only=True)
    try:
        sheet = workbook[SHEETS["issue_comparison"]]
        assert sheet["A1"].value == "고장비교"
        choices = [cell.value for cell in workbook["_issue_lists"]["D"]]
        assert "필러·충진기" in choices and "컨베어" in choices
        facts = workbook["_issue_facts"]
        modules = [facts.cell(row, 7).value for row in range(2, facts.max_row + 1)]
        assert "컨베어" in modules and "필러·충진기" in modules
        assert json.loads(after[KNOWN_FIELDS]) == {"detail_equipment": "컨베어"}
    finally:
        workbook.close()
    assert input_file.read_bytes() == original
