"""Event/type combinations, manual confirmation and non-additive part trends."""

import json

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.classification_candidates import parse_candidates
from core.component_analysis import component_tables
from core.config import ConfigStore
from core.failure_modes import CLASSIFICATION_SCHEMA, canonical_symptom
from core.fault_components import (
    CATEGORY_FIELDS,
    canonical_components,
    combination_category,
    component_evidence_text,
    component_payload,
    parse_components,
    type_label,
)
from core.i18n import K
from core.models import CLASSIFICATION_COMPONENT_COLUMNS, AnalysisOptions, UserError
from core.public_taxonomy import canonical_part_name
from core.report_view import ReportNames
from report.charts import tidy_label

A = {"major": "전기", "middle": "모터", "minor": "모터 고장"}
B = {"major": "전기", "middle": "센서", "minor": "센서 고장"}
C = {"major": "기계", "middle": "체인", "minor": "체인 파손"}


def current(category):
    return {
        **category,
        "major": "전기·제어" if category["major"] == "전기" else category["major"],
        "detail_equipment": "상세설비 미상",
        "middle": canonical_part_name(category["middle"]),
        "minor": canonical_symptom(
            {"모터 고장": "고장·이상", "센서 고장": "고장·이상", "체인 파손": "손상·파손"}.get(
                category["minor"], category["minor"]
            )
        ),
    }


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


def test_multiple_candidates_do_not_become_final_members_and_preserve_event_time(
    store, combination_input
):
    result = analyze_file(store, combination_input)
    rows = result.selected
    first, reversed_, different = [rows.iloc[index] for index in range(3)]
    assert set(CLASSIFICATION_COMPONENT_COLUMNS) <= set(rows)
    assert first.classification_mode == reversed_.classification_mode == "ambiguous"
    assert first.status == reversed_.status == different.status == K["review"]
    first_types = {
        (item["middle"], item["minor"])
        for item in parse_candidates(first.classification_candidates)
    }
    reverse_types = {
        (item["middle"], item["minor"])
        for item in parse_candidates(reversed_.classification_candidates)
    }
    other_types = {
        (item["middle"], item["minor"])
        for item in parse_candidates(different.classification_candidates)
    }
    assert first_types == reverse_types and first_types != other_types
    assert len(first_types) == 2
    assert first.component_count == reversed_.component_count == 0
    assert result.metrics["selected_rows"] == 4
    assert result.metrics["total_minutes"] == 95
    assert result.tables["type"]["count"].sum() == 4
    assert result.tables["type"]["total_minutes"].sum() == 95
    assert result.tables["combination"].empty
    assert result.metrics["combination_rows"] == 0
    assert "후보는 확정 부품으로 합산하지 않습니다" in first.aggregation_effect
    parts = result.tables["component"]
    assert parts.empty
    assert not any("minutes" in key for key in parts)
    assert len(result.tables["fault_detail"]) == len(rows)
    assert result.tables["fault_detail"].record_id.is_unique


def test_user_selects_one_ranked_candidate_and_keeps_event_totals(store, combination_input):
    before = analyze_file(store, combination_input)
    original = before.selected.iloc[0]
    candidates = parse_candidates(original.classification_candidates)
    chosen = candidates[1]
    category = {key: chosen[key] for key in CATEGORY_FIELDS}
    store.update_override(original.event_id, category)
    after = analyze_file(ConfigStore(store.root), combination_input)
    confirmed = after.selected.iloc[0]
    assert confirmed.status == K["manual"]
    assert confirmed.component_count == 1 and confirmed.combination_key == ""
    assert all(confirmed[key] == value for key, value in category.items())
    assert "사용자확정" in confirmed.classification_reason and confirmed.candidate_evidence == ""
    assert not any("score" in column for column in after.selected)
    assert all("score" not in item for item in parse_components(confirmed.component_details))
    assert K["multiple_faults"] not in confirmed.issues
    assert after.metrics["manual_rows"] == 1 and after.metrics["manual_multi_rows"] == 0
    assert after.metrics["review_rows"] == before.metrics["review_rows"] - 1
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"]
    parts = after.tables["component"].set_index("component_type")
    assert (
        parts.loc[
            f"{chosen['major']} / {chosen['detail_equipment']} / {chosen['middle']}", "manual_count"
        ]
        == 1
    )
    assert parts["count"].sum() == 1
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
    store.update_override(before.event_id, current(A))
    after = analyze_file(store, combination_input).selected.iloc[0]
    assert after.status == K["manual"] and after.component_count == 1
    assert after.combination_key == "" and after.component_types == type_label(current(A))


def test_invalid_saved_multi_does_not_silently_fall_back_to_automatic(store, combination_input):
    record = analyze_file(store, combination_input).selected.iloc[0]
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="하나만"):
        store.update_override(record.event_id, {"classification_components": json.dumps([A, B])})
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
    assert type_label(A) not in parts.index
    assert parts.loc[type_label(B), "count"] == 1
    assert parts["count_share"].sum() == pytest.approx(0.5)
    assert parts.loc[type_label(B), "manual_count"] == 1
    assert parts.loc[type_label(B), "review_count"] == 0
    assert not any("minutes" in key for key in parts)
    monthly = tables["component_trend"].set_index(["period", "component_type"])
    assert monthly.loc[("2026-01", type_label(B)), "count_share"] == 0
    assert monthly.loc[("2026-03", type_label(B)), "count"] == 1
    assert monthly.loc[("2026-02", type_label(B)), "count"] == 0
    assert pd.isna(monthly.loc[("2026-02", type_label(B)), "count_share"])


def test_unclassified_faults_remain_in_component_share_denominator():
    frame = component_records()
    unknown = {
        "record_id": "4",
        "date": pd.Timestamp("2026-01-02"),
        "kind": K["fault"],
        "status": K["rule_unmatched"],
        "component_details": "[]",
    }
    table = component_tables(pd.concat([frame, pd.DataFrame([unknown])], ignore_index=True))[
        "component"
    ]
    assert table.set_index("component_type").loc[type_label(B), "count_share"] == pytest.approx(
        1 / 3
    )


def test_missing_dates_affect_monthly_only_and_empty_inputs_are_supported():
    frame = component_records()
    frame.loc[0, "date"] = pd.NaT
    tables = component_tables(frame)
    assert tables["component"]["count"].sum() == 1
    assert tables["component_trend"]["count"].sum() == 1
    assert component_tables(frame.iloc[:0])["component"].empty
    assert component_tables(frame.drop(columns="component_details"))["component"].empty


def test_nonfault_records_have_no_component_types(store, combination_input):
    result = analyze_file(store, combination_input, AnalysisOptions(scope="all"))
    nonfault = result.selected.loc[result.selected.kind.ne(K["fault"])]
    assert nonfault.component_count.eq(0).all()
    assert nonfault.component_details.eq("[]").all()
    assert len(result.tables["fault_detail"]) == len(
        result.selected.loc[result.selected.kind.eq(K["fault"])]
    )


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
    store.save_override(record.event_id, {**current(A), "minutes": "15"})
    with pytest.raises(UserError, match="하나만"):
        store.update_override(record.event_id, {"classification_components": json.dumps([A, B])})
    saved = store.override(record.event_id)
    assert all(saved[key] == value for key, value in current(A).items())
    assert saved["classification_schema"] == CLASSIFICATION_SCHEMA
    assert saved["minutes"] == "15"
    store.save_override(record.event_id, current(C))
    saved = store.override(record.event_id)
    assert "classification_components" not in saved
    assert all(saved[key] == value for key, value in current(C).items())
    after = analyze_file(store, combination_input).selected.iloc[0]
    assert after.status == K["manual"] and after.component_types == type_label(current(C))


def test_conflicting_or_partial_transition_keeps_previous_override_file(store):
    store.override_path.write_text(
        json.dumps({"record": {"classification_components": json.dumps([A, B])}}), encoding="utf-8"
    )
    before = store.override_path.read_bytes()
    with pytest.raises(UserError, match="모두 입력"):
        store.update_override("record", {"major": "New"})
    assert store.override_path.read_bytes() == before
    with pytest.raises(UserError, match="동시에"):
        store.update_override(
            "record", {**current(A), "classification_components": json.dumps([A, B])}
        )
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
    assert record.classification_mode == "ambiguous" and record.component_count == 0
    assert len(parse_candidates(record.classification_candidates)) == 2
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
