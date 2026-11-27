"""One-to-one final classifications and exportable pending review records."""

import json
from contextlib import closing
from dataclasses import replace

import pytest
from conftest import analyze_file, finalize_classifications
from openpyxl import load_workbook

from core.classification_candidates import parse_candidates
from core.classification_policy import unresolved_classifications, validate_final_classifications
from core.corrections import correction_patch, initial_values, validate
from core.failure_modes import CLASSIFICATION_SCHEMA, LEGACY_CLASSIFICATION_SCHEMA, manual_category
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.models import AnalysisOptions, UserError
from report import export_bundle as bundle
from report.excel_report import SHEETS

CATEGORIES = [
    {
        "major": "기계",
        "detail_equipment": "컨베어",
        "middle": "베어링(종류 미상)",
        "minor": "손상·파손",
    },
    {
        "major": "공압·진공",
        "detail_equipment": "필러·충진기",
        "middle": "실린더(종류 미상)",
        "minor": "누설",
    },
]


def test_legacy_multiple_choices_wait_for_a_person_and_keep_other_corrections(store, input_file):
    event = analyze_file(store, input_file).selected.iloc[0].event_id
    legacy_categories = [
        {"major": "기계", "middle": "베어링", "minor": "손상"},
        {"major": "공압·진공", "middle": "실린더", "minor": "누설"},
    ]
    saved = {
        event: {
            "classification_components": json.dumps(legacy_categories, ensure_ascii=False),
            "classification_schema": LEGACY_CLASSIFICATION_SCHEMA,
            "minutes": "18",
            "product": "User product",
            "saved_at": "2026-01-01T00:00:00",
        }
    }
    store.override_path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    before = store.override_path.read_bytes()
    source = input_file.read_bytes()
    pending = analyze_file(store, input_file).selected.iloc[0]
    assert pending.component_count == 0 and parse_components(pending.component_details) == []
    choices = parse_candidates(pending.classification_candidates)
    assert {tuple(c[key] for key in ("major", "middle", "minor")) for c in choices} >= {
        tuple(
            manual_category(c, LEGACY_CLASSIFICATION_SCHEMA)[key]
            for key in ("major", "middle", "minor")
        )
        for c in legacy_categories
    }
    assert store.override_path.read_bytes() == before
    initial = initial_values(pending.to_dict(), store.override(event))
    assert all(not initial.get(key) for key in CATEGORY_FIELDS)
    assert correction_patch(
        initial, {**initial, "minutes": "19"}, store.override(event), False
    ) == {"minutes": "19"}
    store.update_override(event, {"minutes": "19"})
    assert "classification_components" in store.override(event)
    store.update_override(event, CATEGORIES[1])
    assert store.override(event)["classification_schema"] == CLASSIFICATION_SCHEMA
    final = analyze_file(store, input_file).selected.iloc[0]
    assert all(final[key] == value for key, value in CATEGORIES[1].items())
    assert len(parse_components(final.component_details)) == final.component_count == 1
    assert final.minutes == 19 and final["product"] == "User product"
    assert "classification_components" not in store.override(event)
    assert input_file.read_bytes() == source


def test_unresolved_classification_exports_with_compact_review(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    assert not unresolved_classifications(result.selected).empty
    source = input_file.read_bytes()
    target = tmp_path / "final.xlsx"
    target.write_bytes(b"previous report")
    files = bundle.export_bundle(result, target, overwrite=True)
    assert files.excel.is_file()
    assert input_file.read_bytes() == source
    assert not list(tmp_path.glob(".efa_export_*"))
    with closing(load_workbook(files.excel, data_only=True)) as wb:
        review = wb[SHEETS["review"]]
        from openpyxl.utils.cell import range_boundaries

        from report.review_overview import FIELDS

        assert review.max_column == len(FIELDS) + 1
        expected = result.tables["review"].set_index("source_row")
        header = range_boundaries(review.auto_filter.ref)[1]
        for row in range(header + 1, header + 1 + len(expected)):
            record = expected.loc[review.cell(row, 2).value]
            for name in ("review_reason", "status"):
                assert review.cell(row, FIELDS.index(name) + 2).value == (record[name] or None)
            assert review.cell(row, FIELDS.index("history_link") + 2).value == "이력 보기"
        assert review.max_row == max(header + 1, header + len(expected))
        assert wb["_report_metrics"]["A2"].value == result.metrics["selected_rows"]
    assert {"fault_detail", "component", "component_trend"}.isdisjoint(result.tables)


def test_completed_faults_have_one_detail_row_and_one_final_type_each(store, input_file):
    result = finalize_classifications(store, input_file, AnalysisOptions(scope="all"))
    validate_final_classifications(result)
    faults = result.selected.loc[result.selected.kind.eq("고장")]
    detail = faults
    assert set(detail.record_id) == set(faults.record_id)
    assert detail.record_id.is_unique and len(detail) == len(faults)
    assert faults.component_count.eq(1).all()
    assert "component" not in result.tables
    assert result.tables["type"]["count"].sum() == len(result.selected)
    assert result.tables["type"].total_minutes.sum() == result.metrics["total_minutes"]


@pytest.mark.parametrize(
    "category",
    [
        {"major": "기계", "detail_equipment": "컨베어", "middle": "베어링", "minor": "증상 미기재"},
        {
            "major": "규칙 미일치",
            "detail_equipment": "상세설비 미상",
            "middle": "규칙 미일치",
            "minor": "규칙 미일치",
        },
    ],
)
def test_quality_labels_cannot_be_saved_as_final_categories(store, category):
    before = store.override_path.read_bytes()
    assert validate(category)
    with pytest.raises(UserError):
        store.update_override("event", category)
    assert store.override_path.read_bytes() == before


def test_partial_clear_or_multiple_payload_cannot_break_single_choice(store):
    store.update_override("event", CATEGORIES[0])
    before = store.override_path.read_bytes()
    for patch in ({"minor": None}, {"classification_components": json.dumps(CATEGORIES)}):
        with pytest.raises(UserError):
            store.update_override("event", patch)
        assert store.override_path.read_bytes() == before


def test_final_gate_rechecks_member_cardinality_and_path_consistency(store, input_file):
    result = finalize_classifications(store, input_file)
    for payload in (json.dumps(CATEGORIES), json.dumps([CATEGORIES[1]])):
        records = result.selected.copy(deep=True)
        records.loc[0, "component_details"] = payload
        if payload == json.dumps([CATEGORIES[1]]):
            # Force a different member even if the auto category happens to match it.
            records.loc[0, "minor"] = "일치하지 않는 증상"
        with pytest.raises(UserError):
            validate_final_classifications(replace(result, selected=records))
