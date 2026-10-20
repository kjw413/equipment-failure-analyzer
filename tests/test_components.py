"""Event/type combinations, manual confirmation and non-additive part trends."""

import json

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.component_analysis import component_tables
from core.config import ConfigStore
from core.fault_components import (
    canonical_components,
    combination_category,
    component_evidence_text,
    component_payload,
    parse_components,
    type_label,
)
from core.i18n import K
from core.models import CLASSIFICATION_COMPONENT_COLUMNS, AnalysisOptions, UserError
from core.report_view import ReportNames
from report.charts import tidy_label

A = {"major": "전기", "middle": "모터", "minor": "모터 고장"}
B = {"major": "전기", "middle": "센서", "minor": "센서 고장"}
C = {"major": "기계", "middle": "체인", "minor": "체인 파손"}


@pytest.fixture
def combination_input(input_file):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    for row, description in (
        (4, "모터 트립 / 별도로 센서 고장"),
        (5, "센서 고장 / 별도로 모터 트립"),
        (6, "실린더 파손 / 별도로 체인 파손"),
    ):
        sheet.cell(row, 5).value = description
    sheet.cell(5, 1).value = "2026-03-01"
    workbook.save(input_file)
    workbook.close()
    return input_file


def test_canonical_types_are_order_independent_and_duplicate_rules_do_not_add_members():
    first = component_payload([A, B, {**A, "score": 83}, {**A, "score": 90}], "multiple")
    second = component_payload([B, {**A, "score": 90}], "multiple")
    assert first == second
    assert first["component_count"] == 2
    assert parse_components(first["component_details"]) == [A, B]
    assert all("score" not in item for item in json.loads(first["component_details"]))
    assert first["combination_key"] != component_payload([A, C], "multiple")["combination_key"]
    assert combination_category([A, B]) == combination_category([B, A, A])


@pytest.mark.parametrize("value", ["invalid json", {}, [{"major": "A"}], [None]])
def test_bad_members_are_rejected_for_manual_input_but_tolerated_for_legacy_display(value):
    with pytest.raises(UserError):
        parse_components(value, strict=True)
    assert parse_components(value) == []


def test_manual_combination_requires_distinct_types():
    with pytest.raises(UserError, match="2개 이상"):
        combination_category([A, A])
    assert canonical_components([{**A, "score": float("nan")}]) == [A]


def test_legacy_member_scores_are_ignored_without_losing_rule_evidence():
    legacy = json.dumps([{**A, "score": 82.5, "rule_id": "MOTOR", "evidence": "모터 트립"}, B])
    members = parse_components(legacy, strict=True)
    assert members == [{**A, "rule_id": "MOTOR", "evidence": "모터 트립"}, B]
    displayed = component_evidence_text(legacy)
    assert "모터 트립" in displayed and "82.5" not in displayed
    payload = component_payload(members, "multiple")
    assert "score" not in payload["component_details"]
    assert payload["combination_key"] == component_payload([A, B], "multiple")["combination_key"]


def test_combinations_group_by_members_and_preserve_event_time(store, combination_input):
    result = analyze_file(store, combination_input)
    rows = result.selected
    first, reversed_, different = [rows.iloc[index] for index in range(3)]
    assert set(CLASSIFICATION_COMPONENT_COLUMNS) <= set(rows)
    assert first.classification_mode == reversed_.classification_mode == "multiple"
    assert first.type == reversed_.type and first.combination_key == reversed_.combination_key
    assert different.type != first.type and different.combination_key != first.combination_key
    assert first.component_count == reversed_.component_count == 2
    assert result.metrics["selected_rows"] == 4
    assert result.metrics["total_minutes"] == 95
    assert result.tables["type"]["count"].sum() == 4
    assert result.tables["type"]["total_minutes"].sum() == 95
    combined = result.tables["combination"].set_index("type")
    assert combined.loc[first.type, "count"] == 2
    assert combined.loc[first.type, "total_minutes"] == 30
    assert result.metrics["combination_rows"] == 3
    assert "조합" in first.aggregation_effect and "한 번" in first.aggregation_effect
    parts = result.tables["component"]
    assert parts["count"].sum() == 6
    assert not any("minutes" in key for key in parts)
    assert parts["review_count"].sum() == 6


def test_manual_multi_confirmation_persists_with_rule_decision_fields(store, combination_input):
    before = analyze_file(store, combination_input)
    original = before.selected.iloc[0]
    members = parse_components(original.component_details)
    store.update_override(original.event_id, {"classification_components": json.dumps(members)})
    after = analyze_file(ConfigStore(store.root), combination_input)
    confirmed = after.selected.iloc[0]
    assert confirmed.status == K["manual_multi"]
    assert confirmed.component_count == 2 and confirmed.combination_key == original.combination_key
    assert "사용자확정" in confirmed.classification_reason and confirmed.candidate_evidence == ""
    assert not any("score" in column for column in after.selected)
    assert all("score" not in item for item in parse_components(confirmed.component_details))
    assert K["multiple_faults"] not in confirmed.issues
    assert after.metrics["manual_rows"] == after.metrics["manual_multi_rows"] == 1
    assert after.metrics["review_rows"] == before.metrics["review_rows"] - 1
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"]
    parts = after.tables["component"].set_index("component_type")
    assert all(parts.loc[type_label(item), "manual_count"] == 1 for item in members)
    store.clear_override(original.event_id)
    reset = analyze_file(store, combination_input).selected.iloc[0]
    assert reset.status == K["review"] and reset.combination_key == original.combination_key


def test_time_only_change_does_not_confirm_combination(store, combination_input):
    before = analyze_file(store, combination_input).selected.iloc[0]
    store.update_override(before.event_id, {"minutes": "25"})
    after = analyze_file(store, combination_input).selected.iloc[0]
    assert after.status == K["review"] and after.combination_key == before.combination_key
    assert (
        after.component_details == before.component_details
        and after.classification_reason == before.classification_reason
        and after.candidate_evidence == before.candidate_evidence
    )
    assert after.minutes == 25


def test_single_confirmation_replaces_the_whole_combination(store, combination_input):
    before = analyze_file(store, combination_input).selected.iloc[0]
    store.update_override(before.event_id, A)
    after = analyze_file(store, combination_input).selected.iloc[0]
    assert after.status == K["manual"] and after.component_count == 1
    assert after.combination_key == "" and after.component_types == type_label(A)


def test_invalid_saved_multi_does_not_silently_fall_back_to_automatic(store, combination_input):
    record = analyze_file(store, combination_input).selected.iloc[0]
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="2개 이상"):
        store.update_override(record.event_id, {"classification_components": json.dumps([A, A])})
    assert store.override_path.read_bytes() == before


def component_records():
    return pd.DataFrame(
        [
            {
                "record_id": "1",
                "date": pd.Timestamp("2026-01-01"),
                "kind": K["fault"],
                "status": K["review"],
                "component_details": json.dumps([A, A, B]),
            },
            {
                "record_id": "2",
                "date": pd.Timestamp("2026-03-01"),
                "kind": K["fault"],
                "status": K["manual"],
                "component_details": json.dumps([B]),
            },
            {
                "record_id": "3",
                "date": pd.Timestamp("2026-01-01"),
                "kind": K["planned"],
                "status": K["nonfault"],
                "component_details": json.dumps([A, B]),
            },
        ]
    )


def test_inclusion_counts_deduplicate_members_and_exclude_nonfault_denominator():
    tables = component_tables(component_records())
    parts = tables["component"].set_index("component_type")
    assert parts.loc[type_label(A), "count"] == 1
    assert parts.loc[type_label(B), "count"] == 2
    assert parts["count_share"].sum() == pytest.approx(1.5)
    assert parts.loc[type_label(B), "manual_count"] == 1
    assert parts.loc[type_label(B), "review_count"] == 1
    assert not any("minutes" in key for key in parts)
    monthly = tables["component_trend"].set_index(["period", "component_type"])
    assert monthly.loc[("2026-01", type_label(B)), "count_share"] == 1
    assert monthly.loc[("2026-03", type_label(A)), "count"] == 0
    assert monthly.loc[("2026-02", type_label(A)), "count"] == 0
    assert pd.isna(monthly.loc[("2026-02", type_label(A)), "count_share"])


def test_unclassified_faults_remain_in_component_share_denominator():
    frame = component_records()
    unknown = {
        "record_id": "4",
        "date": pd.Timestamp("2026-01-02"),
        "kind": K["fault"],
        "status": K["unclassified"],
        "component_details": "[]",
    }
    table = component_tables(pd.concat([frame, pd.DataFrame([unknown])], ignore_index=True))[
        "component"
    ]
    assert table.set_index("component_type").loc[type_label(B), "count_share"] == pytest.approx(
        2 / 3
    )


def test_missing_dates_affect_monthly_only_and_empty_inputs_are_supported():
    frame = component_records()
    frame.loc[0, "date"] = pd.NaT
    tables = component_tables(frame)
    assert tables["component"]["count"].sum() == 3
    assert tables["component_trend"]["count"].sum() == 1
    assert component_tables(frame.iloc[:0])["component"].empty
    assert component_tables(frame.drop(columns="component_details"))["component"].empty


def test_nonfault_records_have_no_component_types(store, combination_input):
    result = analyze_file(store, combination_input, AnalysisOptions(scope="all"))
    nonfault = result.selected.loc[result.selected.kind.ne(K["fault"])]
    assert nonfault.component_count.eq(0).all()
    assert nonfault.component_details.eq("[]").all()
    assert not result.tables["component"].empty


def test_structured_member_names_project_consistently_without_breaking_json_or_identity():
    member = {**A, "minor": "IF18115 고장", "evidence": "IF18115", "rule_id": "IF18115"}
    payload = component_payload([member, B], "multiple")
    name = '설비 "이름" \\ 라인'
    projected = ReportNames({"IF18115": name}).frame(pd.DataFrame([payload]))
    members = json.loads(projected.iloc[0].component_details)
    selected = next(item for item in members if "evidence" in item)
    assert selected["minor"] in projected.iloc[0].component_types
    assert selected["evidence"] == name and selected["rule_id"] == "IF18115"
    assert projected.iloc[0].combination_key == payload["combination_key"]
    assert json.loads(payload["component_details"])[0]["evidence"] == "IF18115"


def test_chart_combination_label_keeps_both_members_and_marks_additional_types():
    category = combination_category([A, B])
    label = tidy_label(" / ".join(category.values()))
    assert "모터" in label and "센서" in label and "복수" in label
    three = combination_category([A, B, C])
    assert "외 1유형" in tidy_label(" / ".join(three.values()))


def test_public_override_api_enforces_exclusive_single_multiple_transitions(
    store, combination_input
):
    record = analyze_file(store, combination_input).selected.iloc[0]
    store.save_override(record.event_id, {**A, "minutes": "15"})
    store.update_override(record.event_id, {"classification_components": json.dumps([A, B])})
    saved = store.override(record.event_id)
    assert not any(key in saved for key in ("major", "middle", "minor"))
    assert saved["minutes"] == "15"
    store.save_override(record.event_id, C)
    saved = store.override(record.event_id)
    assert "classification_components" not in saved
    assert all(saved[key] == value for key, value in C.items())
    after = analyze_file(store, combination_input).selected.iloc[0]
    assert after.status == K["manual"] and after.component_types == type_label(C)


def test_conflicting_or_partial_transition_keeps_previous_override_file(store):
    store.save_override("record", {"classification_components": json.dumps([A, B])})
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="모두 입력"):
        store.update_override("record", {"major": "New"})
    assert store.override_path.read_bytes() == before
    with pytest.raises(UserError, match="동시에"):
        store.update_override("record", {**A, "classification_components": json.dumps([A, B])})
    assert store.override_path.read_bytes() == before


def test_explicit_alternatives_stay_reviewed_without_creating_a_combination(store, input_file):
    workbook = load_workbook(input_file)
    workbook["Events"].cell(4, 5).value = "모터 고장 또는 센서 고장"
    workbook.save(input_file)
    workbook.close()
    settings = store.read("settings.json")
    settings["classifier"]["scoring"] = {"min_score": 0, "min_margin": 0}
    (store.config_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    assert "scoring" not in store.load()["settings"]["classifier"]
    result = analyze_file(store, input_file)
    record = result.selected.iloc[0]
    assert record.classification_mode == "ambiguous" and record.component_count == 1
    assert record.status == K["review"] and K["alternative_types"] in record.issues
    assert record.combination_key == ""
    assert result.metrics["alternative_type_rows"] == 1
    assert "대안" in record.review_reason


def test_corrupt_stored_multi_is_reported_instead_of_ignored(store, input_file):
    record = analyze_file(store, input_file).selected.iloc[0]
    store.override_path.write_text(
        json.dumps({record.event_id: {"classification_components": "invalid json"}}),
        encoding="utf-8",
    )
    with pytest.raises(UserError, match="저장 형식"):
        analyze_file(store, input_file)
