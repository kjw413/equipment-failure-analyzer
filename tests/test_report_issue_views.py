"""Organization/case reports retain known facts and independent ranking metrics."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook
from pypdf import PdfReader

from core.analyzer import analyze
from core.equipment_breakdown import type_breakdown
from core.failure_modes import CLASSIFICATION_SCHEMA
from core.fault_components import component_payload, type_label
from core.i18n import K
from core.issue_analysis import (
    case_months,
    issue_facts,
    issue_summary,
    priority_cases,
    select_issues,
)
from report.charts import tidy_label
from report.excel_report import export_report
from report.issue_workbook import ISSUE_SHEETS
from report.pdf_report import brief_type, export_pdf


def test_rare_long_stop_is_first_in_time_ranking():
    rows = [
        {"record_id": str(i), "equipment": "설비A", "type": "자주 발생", "minutes": 1}
        for i in range(10)
    ]
    rows.append({"record_id": "long", "equipment": "설비A", "type": "장시간 정지", "minutes": 191})
    frame = pd.DataFrame(rows)
    assert type_breakdown(frame, "설비A").iloc[0]["type"] == "자주 발생"
    assert type_breakdown(frame, "설비A", "total_minutes").iloc[0]["type"] == "장시간 정지"
    assert len(frame) == 11


def test_chart_labels_retain_module_for_unknown_parts():
    printer = tidy_label("분야 미상 / 날인기 / 세부 부품 미기재 / 고장·이상")
    robot = tidy_label("분야 미상 / 로봇 / 세부 부품 미기재 / 고장·이상")
    assert "날인기" in printer and "로봇" in robot
    assert printer != robot
    assert brief_type("펌프 / 씰 / 누설") == "펌프 / 씰 / 누설"


@pytest.fixture
def organization_result(store, input_file):
    original = analyze_file(store, input_file)
    rows = []
    descriptions = [
        ("공장A", "팀1", "실제설비A", "2026-01-01", 10, "펌프", False),
        ("공장A", "팀1", "실제설비A", "2026-01-02", 20, "펌프", False),
        ("공장B", "팀2", "실제설비B", "2026-01-03", 100, "펌프", False),
        ("공장B", "팀2", "실제설비B", "2026-03-10", None, "펌프", False),
        ("공장A", "팀1", "실제설비A", "2026-04-01", 5, "펌프", True),
        ("공장A", "팀1", "실제설비A", "2026-04-02", 9, "컨베어", False),
    ]
    for index, (factory, team, asset, date, minutes, module, pending) in enumerate(descriptions):
        category = {
            "major": "유체·배관",
            "detail_equipment": module,
            "middle": "씰",
            "minor": "누설",
            "schema": CLASSIFICATION_SCHEMA,
        }
        record = original.selected.iloc[0].to_dict()
        record.update(component_payload([category], "single"))
        record.update(
            {
                "record_id": f"test-{index}",
                "event_id": f"event-{index}",
                "source_row": index + 4,
                "factory": factory,
                "team": team,
                "report_equipment": asset,
                "equipment": factory,
                "line": asset,
                "date": pd.Timestamp(date),
                "minutes": minutes,
                "kind": K["fault"],
                "type": type_label(category),
                "status": K["review"] if pending else K["auto"],
                **{key: category[key] for key in ("major", "detail_equipment", "middle", "minor")},
                "classification_schema": CLASSIFICATION_SCHEMA,
                "classification_known_fields": json.dumps(
                    {"detail_equipment": module} if pending else {}, ensure_ascii=False
                ),
            }
        )
        if pending:
            record.update(component_payload([], "ambiguous"))
        rows.append(record)
    planned = dict(
        rows[0],
        record_id="planned",
        event_id="planned",
        source_row=10,
        kind=K["planned"],
        minutes=999,
    )
    rows.append(planned)
    raw = [
        dict(original.loaded.frame.iloc[0], __source_row=index + 4) for index in range(len(rows))
    ]
    loaded = replace(original.loaded, frame=pd.DataFrame(raw))
    return analyze(loaded, pd.DataFrame(rows), original.config_snapshot, original.options)


def test_facts_use_retained_axes_and_actual_asset_independent_of_grouping(organization_result):
    facts = issue_facts(organization_result.selected)
    assert len(facts) == 6
    assert facts.minutes.sum() == 144
    assert set(facts.asset) == {"실제설비A", "실제설비B"}
    pending = facts.loc[facts.record_id.eq("test-4")].iloc[0]
    assert pending["case"] == "펌프 / 세부 부품 미기재 / 현상 미기재"
    assert pending.review_count == 1
    summary = issue_summary(facts, ["module"])
    pump = summary.loc[summary.module.eq("펌프")].iloc[0]
    assert pump["count"] == 5 and pump.total_minutes == 135


def test_all_stop_scope_still_uses_only_faults_in_case_views(organization_result):
    result = analyze(
        organization_result.loaded,
        organization_result.all_records,
        organization_result.config_snapshot,
        replace(organization_result.options, scope="all"),
    )
    assert len(result.selected) == 7
    facts = issue_facts(result.selected)
    assert len(facts) == 6 and facts.minutes.sum() == 144


def test_case_trend_keeps_zero_separate_from_unavailable_duration(organization_result):
    facts = issue_facts(organization_result.selected)
    calendar = case_months(facts)
    case = select_issues(facts, case="펌프 / 씰 / 누설")
    months = case_months(case, calendar.period).set_index("period")
    assert list(months.index) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert months.loc["2026-01", "count"] == 3
    assert months.loc["2026-01", "total_minutes"] == 130
    assert months.loc["2026-02", "count"] == 0
    assert months.loc["2026-02", "total_minutes"] == 0
    assert months.loc["2026-03", "count"] == 1
    assert pd.isna(months.loc["2026-03", "total_minutes"])


def test_unknown_modules_do_not_become_automatic_same_case_comparisons(organization_result):
    facts = issue_facts(organization_result.selected)
    unknown = facts.iloc[[0]].copy()
    unknown["module"] = "상세설비 미상"
    unknown["case"] = "상세설비 미상 / 씰 / 누설"
    unknown["minutes"] = 99999
    combined = pd.concat([facts, unknown], ignore_index=True)
    assert unknown.iloc[0]["case"] not in priority_cases(combined)
    assert combined.minutes.sum() == 100143
    assert priority_cases(unknown) == []


def test_excel_selectors_share_fact_formulas_and_native_charts(organization_result, tmp_path):
    path = export_report(organization_result, tmp_path / "organizations.xlsx")
    values = load_workbook(path, data_only=True)
    formulas = load_workbook(path, data_only=False)
    try:
        org = values[ISSUE_SHEETS["organization_issues"]]
        comparison = values[ISSUE_SHEETS["issue_comparison"]]
        trend = values[ISSUE_SHEETS["issue_trends"]]
        assert org["C9"].value == 6 and org["E9"].value == 144
        assert org["B27"].value == "실제설비A"
        case_labels = [org.cell(row, 2).value for row in range(27, org.max_row + 1)]
        assert set(case_labels) - {None, ""} == {"실제설비A", "실제설비B"}
        assert comparison["B6"].value == "부서"
        assert [comparison.cell(25, c).value for c in (1, 2, 5, 6, 8, 9)] == [
            "공장A",
            "팀1",
            4,
            44,
            0,
            0,
        ]
        assert [comparison.cell(26, c).value for c in (1, 2, 5, 6, 8, 9)] == [
            "공장B",
            "팀2",
            2,
            100,
            -2,
            56,
        ]
        assert trend["B24"].value == 3 and trend["C24"].value == 130
        assert trend["B25"].value == 0 and trend["C25"].value == 0
        assert trend["B26"].value == 1 and trend["C26"].value in (None, "")
        assert trend["B27"].value == 2 and trend["C27"].value == 14
        for key, validation_count in (
            ("organization_issues", 5),
            ("issue_comparison", 7),
            ("issue_trends", 7),
        ):
            sheet = formulas[ISSUE_SHEETS[key]]
            assert len(sheet.data_validations.dataValidation) == validation_count
            assert len(sheet._charts) == 2
        chart = formulas[ISSUE_SHEETS["organization_issues"]]._charts[0]
        assert chart.x_axis.scaling.orientation == "maxMin"
        assert chart.y_axis.scaling.orientation == "minMax"
        assert formulas[ISSUE_SHEETS["issue_trends"]]._charts[0].series[0].smooth is False
        assert "_fault_rows" in formulas[ISSUE_SHEETS["issue_comparison"]]["E25"].value
        assert "$B$6" in formulas["_issue_filter_1"]["A2"].value
        assert all(
            values[name].sheet_state == "hidden"
            for name in ("_issue_facts", "_issue_lists", "_issue_rank")
        )
        assert list(values.sheetnames[:4]) == ["01.종합현황", *ISSUE_SHEETS.values()]
    finally:
        values.close()
        formulas.close()


def test_pdf_comparisons_and_case_trends_precede_equipment_appendix(organization_result, tmp_path):
    path = export_pdf(organization_result, tmp_path / "organizations.pdf")
    pages = [page.extract_text() or "" for page in PdfReader(path).pages]
    text = "\n".join(pages)
    assert "공장·팀별 주요 이슈" in text
    assert "동일 설비·사례의 조직 간 비교" in text
    assert "고장사례별 월간 변화" in text
    assert text.index("05 고장사례별 월간 변화") < text.index("부록 A 라인별 상세 분석")
    assert "부록 C 개별 분류 이력" not in text
    assert len(PdfReader(path).outline) >= 6
    assert any("실제설비A" in entry.get("/Title", "") for entry in PdfReader(path).outline)
    appendix = text[text.index("부록 A 라인별 상세 분석") :]
    assert "실제설비A" in appendix and "실제설비B" in appendix


def test_excel_starts_with_all_cases_without_changing_saved_case(organization_result, tmp_path):
    config = dict(organization_result.config_snapshot)
    config["final_report"] = {**config["final_report"], "focus_case": "선택 사례 없음"}
    result = replace(organization_result, config_snapshot=config)
    path = export_report(result, tmp_path / "unavailable_case.xlsx")
    wb = load_workbook(path, data_only=True)
    try:
        trend = wb[ISSUE_SHEETS["issue_trends"]]
        assert trend["J6"].value == "(전체)"
        assert [trend.cell(row, 2).value for row in range(24, 28)] == [3, 0, 1, 2]
        assert result.config_snapshot["final_report"]["focus_case"] == "선택 사례 없음"
    finally:
        wb.close()


def test_year_over_year_comparison_uses_same_calendar_month(organization_result, tmp_path):
    records = organization_result.all_records.copy(deep=True)
    records.loc[records.record_id.eq("test-3"), "date"] = pd.Timestamp("2027-01-31")
    records.loc[records.record_id.eq("test-3"), "minutes"] = 40
    result = analyze(
        organization_result.loaded,
        records,
        organization_result.config_snapshot,
        organization_result.options,
    )
    wb = load_workbook(export_report(result, tmp_path / "year_over_year.xlsx"), data_only=True)
    try:
        sheet = wb[ISSUE_SHEETS["issue_trends"]]
        assert sheet["A36"].value == "2027-01"
        assert sheet["I36"].value == -2
        assert sheet["J36"].value == -90
    finally:
        wb.close()


def test_pdf_record_appendix_can_be_requested(organization_result, tmp_path):
    config = {
        **organization_result.config_snapshot,
        "final_report": {
            **organization_result.config_snapshot["final_report"],
            "include_record_appendix": True,
        },
    }
    path = export_pdf(
        replace(organization_result, config_snapshot=config), tmp_path / "appendix.pdf"
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    assert "부록 C 개별 분류 이력" in text
    assert text.index("07 관리 검토사항") < text.index("부록 C 개별 분류 이력")


def test_report_case_selection_and_appendix_setting_survive_save(store, organization_result):
    from PySide6.QtWidgets import QWidget

    from gui.report_settings import ReportSettingsDialog

    parent = QWidget()
    parent.result = organization_result
    dialog = ReportSettingsDialog(store, parent)
    selected = "컨베어 / 씰 / 누설"
    dialog.case.setCurrentIndex(dialog.case.findData(selected))
    dialog.appendix.setChecked(True)
    dialog.save()
    saved = store.read("final_report.json")
    assert saved["focus_case"] == selected
    assert saved["include_record_appendix"] is True
    dialog.close()
    parent.close()
