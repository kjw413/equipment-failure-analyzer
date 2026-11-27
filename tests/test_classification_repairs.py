"""Regression examples for category/status separation, equipment names and replacement."""

from contextlib import closing
from dataclasses import replace

import pytest
from conftest import analyze_file
from openpyxl import Workbook, load_workbook
from test_classification_candidates import rule

from core.classification_candidates import parse_candidates
from core.excel_loader import load_excel
from core.failure_classification import FaultClassifier
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import K
from core.preprocessing import event_ids
from report.excel_report import SHEETS, export_report
from report.review_overview import FIELDS


@pytest.fixture
def location_classifier():
    return FaultClassifier([rule("tank", "탱크"), rule("filter", "제균필터")])


@pytest.mark.parametrize("source", ["탱크 제균필터", "탱크 제균필터 교체"])
def test_mes_equipment_mention_is_not_a_weak_fault_candidate(location_classifier, source):
    result = location_classifier.classify(source, equipment_context="1호 탱크")
    assert {item["middle"] for item in parse_candidates(result["classification_candidates"])} == {
        "제균필터"
    }


def test_equipment_with_its_own_failure_is_still_a_candidate(location_classifier):
    result = location_classifier.classify("탱크 손상 / 제균필터 교체", equipment_context="탱크")
    assert {
        (item["middle"], item["minor"])
        for item in parse_candidates(result["classification_candidates"])
    } == {("세부 부품 미기재", "손상·파손"), ("제균필터", "현상 미기재")}
    assert any(
        item["detail_equipment"] == "탱크" and item["middle"] == "세부 부품 미기재"
        for item in parse_candidates(result["classification_candidates"])
    )


@pytest.mark.parametrize("code", ["교체", "교환"])
def test_small_code_replacement_completes_a_named_part(location_classifier, code):
    result = location_classifier.classify("탱크 제균필터", code, equipment_context="탱크")
    assert result["status"] == K["partial"]
    assert result["classification_missing_fields"] == "고장 현상"
    assert result["repair_actions"] == "교체"
    members = parse_components(result["component_details"])
    assert len(members) == result["component_count"] == result["part_count"] == 1
    assert members[0]["middle"] == "제균필터"
    assert members[0]["minor"] == "현상 미기재"
    assert result["detail_equipment"] == "탱크"
    assert any(
        c["middle"] == "제균필터" and c["minor"] == "현상 미기재"
        for c in parse_candidates(result["classification_candidates"])
    )


@pytest.mark.parametrize("source", ["제균필터 교체 예정", "제균필터 교체 안함", "제균필터 정상"])
def test_replacement_code_never_overrides_planned_negated_or_normal_text(
    location_classifier, source
):
    result = location_classifier.classify(source, "교체")
    assert parse_components(result["component_details"]) == []


def test_source_codes_categories_and_legacy_report_projection(store, tmp_path):
    source = tmp_path / "repairs.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(
        [
            "발생일",
            "설비코드",
            "설비명",
            "고장내용",
            "정지시간",
            "정지구분",
            "비가동 코드(중)",
            "비가동 코드(소)",
        ]
    )
    for text, mid, small in [
        ("unknown issue", "", ""),
        ("베어링 및 실린더 손상", "", ""),
        ("탱크 제균필터 교체", "탱크", ""),
        ("탱크 제균필터", "탱크", "교체"),
        ("베어링 손상 후 교체", "", ""),
    ]:
        sheet.append(["2026-11-01", "EQ1", "탱크", text, 10, "고장", mid, small])
    book.save(source)
    book.close()
    before = source.read_bytes()
    loaded = load_excel(source, store.load()["column_mapping"])
    source_event_ids = event_ids(loaded, loaded.mapping)
    result = analyze_file(store, source)
    records = result.selected.set_index("raw_description")
    unknown = records.loc["unknown issue"]
    assert all(unknown[key] == "" for key in CATEGORY_FIELDS)
    assert unknown["classification_reason"]
    # The approved policy selects the displayed rank 1 as the event's
    # representative; it retains both observed damaged parts as candidates.
    representative = records.loc["베어링 및 실린더 손상"]
    candidates = parse_candidates(representative["classification_candidates"])
    members = parse_components(representative["component_details"])
    assert representative["status"] == K["partial"]
    assert representative["classification_missing_fields"] == "상세설비·모듈"
    assert len(members) == representative["component_count"] == representative["part_count"] == 1
    assert members[0]["selection_method"] == "top_ranked_representative"
    assert members[0]["selected_rank"] == candidates[0]["rank"] == 1
    assert all(
        representative[key] == members[0][key] == candidates[0][key] for key in CATEGORY_FIELDS
    )
    assert candidates[0]["middle"] == "베어링(종류 미상)"
    assert {item["middle"] for item in candidates} == {"베어링(종류 미상)", "실린더(종류 미상)"}
    assert all(item["minor"] == "손상·파손" and item["symptom_evidence"] for item in candidates)
    assert "베어링 및 실린더 손상" not in set(result.tables["review"].raw_description)
    for text in ("탱크 제균필터 교체", "탱크 제균필터"):
        assert records.loc[text, "minor"] == "현상 미기재"
        assert records.loc[text, "middle"] == "제균필터"
        assert records.loc[text, "detail_equipment"] == "탱크"
        assert records.loc[text, "classification_missing_fields"] == "고장 현상"
        assert records.loc[text, "component_count"] == records.loc[text, "part_count"] == 1
        assert records.loc[text, "repair_actions"] == "교체"
        assert records.loc[text, "status"] == K["partial"]
        assert "탱크" not in {
            item["middle"]
            for item in parse_candidates(records.loc[text, "classification_candidates"])
        }
    assert records.loc["베어링 손상 후 교체", "minor"] == "손상·파손"
    # Old results with reasons in category cells must also export cleanly.
    old_records = result.selected.copy(deep=True)
    old_records.loc[
        old_records.raw_description.eq("unknown issue"), ["major", "middle", "minor"]
    ] = K["code_missing"]
    output = export_report(replace(result, selected=old_records), tmp_path / "output.xlsx")
    with closing(load_workbook(output, data_only=True)) as report:
        for key in ("detail",):
            ws = report[SHEETS[key]]
            header_row = (
                int(__import__("re").search(r"[0-9]+", ws.auto_filter.ref)[0])
                if key == "review"
                else 6
            )
            headers = {cell.value: cell.column for cell in ws[header_row]}
            assert "세부 부품" not in headers
            for name in ("고장 분야", "상세설비·모듈", "고장 현상"):
                assert not any(
                    ws.cell(row, headers[name]).value
                    in {K["review"], K["code_missing"], K["rule_unmatched"]}
                    for row in range(header_row + 1, ws.max_row + 1)
                )
        assert report[SHEETS["review"]].max_column == len(FIELDS) + 1 == 10
    assert source.read_bytes() == before
    assert result.selected.event_id.tolist() == source_event_ids
    assert result.selected.record_id.is_unique
    assert (
        len(result.selected.loc[result.selected.kind.eq(K["fault"])]) == len(result.selected) == 5
    )
    assert result.selected.loc[result.selected.kind.eq(K["fault"])].record_id.is_unique
    assert result.tables["type"]["count"].sum() == 5
    assert result.tables["type"].total_minutes.sum() == 50
    assert result.metrics["total_minutes"] == 50
