"""Rule decisions remain inspectable and obsolete score fields are not exported."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.i18n import DISPLAY, K
from report.classification import (
    COMPONENT_FIELDS,
    DECISION_FIELDS,
    LEGACY_REASON,
    LEGACY_SCORE_FIELDS,
    LEGACY_STATUS,
)
from report.excel_report import DETAIL_COLS, SHEETS, D, export_report
from report.pdf_report import export_pdf


@pytest.fixture
def decision_result(store, input_file):
    result = analyze_file(store, input_file)
    selected = result.selected.copy(deep=True)
    for index in selected.index:
        selected.loc[index, "classification_reason"] = f"규칙 판정 사유 {index}: 부품·증상 일치"
        selected.loc[index, "candidate_evidence"] = f"후보 규칙 {index}: 센서 문맥 및 이상 표현"
    selected.loc[1, "status"] = K["manual"]
    selected.loc[2, "status"] = K["review"]
    tables = {
        **result.tables,
        "long_stops": selected.copy(deep=True),
        "review": selected.iloc[[2, 1]].copy(deep=True),
    }
    return replace(
        result,
        selected=selected,
        tables=tables,
        metrics={**result.metrics, "manual_rows": 1, "review_rows": 2},
    )


def workbook_text(workbook):
    return "\n".join(
        str(cell.value)
        for sheet in workbook
        for row in sheet
        for cell in row
        if cell.value is not None
    )


def test_decision_columns_preserve_existing_formula_column_positions():
    assert len(DETAIL_COLS) == 48
    assert DETAIL_COLS[:12] == [
        "record_id",
        "source_row",
        "date",
        "line",
        "registered",
        "target",
        "equipment",
        "product",
        "minutes",
        "type",
        "status",
        "raw_description",
    ]
    assert DETAIL_COLS[36:41] == [
        "duplicate",
        "equipment_code",
        "raw_equipment_name",
        "report_equipment",
        "name_mapped",
    ]
    assert DETAIL_COLS[41:43] == list(DECISION_FIELDS)
    assert DETAIL_COLS[43:] == list(COMPONENT_FIELDS)
    assert D["record_id"] == "A" and D["minutes"] == "I" and D["type"] == "J"
    assert not set(LEGACY_SCORE_FIELDS).intersection(DETAIL_COLS)


def test_excel_detail_review_top_expose_rule_decisions(decision_result, tmp_path):
    workbook = load_workbook(
        export_report(decision_result, tmp_path / "rules.xlsx"), data_only=True
    )
    try:
        for key in ("detail", "review", "top"):
            sheet = workbook[SHEETS[key]]
            headers = {cell.value: cell.column for cell in sheet[6]}
            for field in DECISION_FIELDS:
                column = headers[DISPLAY[field]]
                assert any(sheet.cell(row, column).value for row in range(7, sheet.max_row + 1))
            assert not any(DISPLAY.get(field, field) in headers for field in LEGACY_SCORE_FIELDS)
        quality_counts = {
            row[0].value: row[1].value for row in workbook[SHEETS["quality"]] if len(row) >= 2
        }
        assert quality_counts[K["review"]] == 1
        assert workbook[SHEETS["summary"]]["E7"].value == decision_result.metrics["total_minutes"]
        text = workbook_text(workbook)
        assert "판정 사유와 후보별 근거를 기록합니다" in text
        assert "최소점수" not in text and "점수 격차" not in text
    finally:
        workbook.close()


def test_pdf_exposes_rule_reason_and_candidates(decision_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = export_pdf(decision_result, tmp_path / "rules.pdf")
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)
    compact = "".join(text.split())
    for phrase in (
        "규칙 기반 분류 원칙",
        "검토 기록의 규칙 근거",
        "규칙 판정 사유 2",
        "후보 규칙 2",
        "수동확정",
        "후보별 근거",
    ):
        assert "".join(phrase.split()) in compact
    assert "근거점수" not in compact and "격차" not in compact
    assert "nan" not in text.lower()


def test_older_results_ignore_scores_without_mutating_input(decision_result, tmp_path):
    def older(frame):
        frame = frame.copy(deep=True).drop(columns=list(DECISION_FIELDS), errors="ignore")
        for field in LEGACY_SCORE_FIELDS:
            frame[field] = 88.5 if field in LEGACY_SCORE_FIELDS[:3] else "OLD_SCORE_88.5점"
        if "status" in frame:
            frame.loc[frame["status"].eq(K["auto"]), "status"] = "점수분류"
        if "evidence" in frame:
            frame["evidence"] = "MOTOR | 모터, 이상 | 근거 점수 88.5/100"
        if "component_details" in frame:
            frame["component_details"] = frame["component_details"].map(
                lambda value: json.dumps(
                    [{**member, "score": 88.5} for member in json.loads(value or "[]")],
                    ensure_ascii=False,
                )
            )
        return frame

    snapshot = {
        **decision_result.config_snapshot,
        "settings": {
            **decision_result.config_snapshot["settings"],
            "classifier": {"scoring": {"min_score": 81, "min_margin": 15}},
        },
    }
    result = replace(
        decision_result,
        selected=older(decision_result.selected),
        all_records=older(decision_result.all_records),
        tables={key: older(frame) for key, frame in decision_result.tables.items()},
        notes=[*decision_result.notes, "점수 기준: 최고 81점, 격차 15점"],
        metrics={**decision_result.metrics, "low_score_rows": 1, "close_score_rows": 1},
        config_snapshot=snapshot,
    )
    before = result.selected.copy(deep=True)
    workbook = load_workbook(export_report(result, tmp_path / "older.xlsx"), data_only=True)
    try:
        text = workbook_text(workbook)
        for obsolete in (
            "OLD_SCORE",
            "근거 점수",
            "점수 기준",
            "min_score",
            "min_margin",
            '"score":',
        ):
            assert obsolete not in text
        assert workbook[SHEETS["summary"]]["E7"].value == result.metrics["total_minutes"]
        detail = workbook[SHEETS["detail"]]
        legacy_rows = [
            row
            for row in range(7, detail.max_row + 1)
            if detail[f"{D['status']}{row}"].value == LEGACY_STATUS
        ]
        assert legacy_rows
        assert all(
            detail[f"{D['classification_reason']}{row}"].value == LEGACY_REASON
            for row in legacy_rows
        )
        counts = {
            row[0].value: row[1].value for row in workbook[SHEETS["quality"]] if len(row) >= 2
        }
        assert counts[K["auto"]] == 0
        assert counts["이전 분석결과(재분석 필요)"] == len(legacy_rows)
    finally:
        workbook.close()
    pypdf = pytest.importorskip("pypdf")
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(export_pdf(result, tmp_path / "older.pdf")).pages
    )
    assert "OLD_SCORE" not in pdf_text and "근거 점수" not in pdf_text
    assert "이전분석결과" in "".join(pdf_text.split())
    assert "현재규칙으로재분석하기전의분류" in "".join(pdf_text.split())
    pd.testing.assert_frame_equal(result.selected, before)
    assert result.config_snapshot["settings"]["classifier"]["scoring"]["min_score"] == 81
