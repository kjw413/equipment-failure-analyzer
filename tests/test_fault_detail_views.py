"""Split part/symptom display rows keep their one source event and downtime."""
# ruff: noqa: E402

import os
from hashlib import sha256

import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.fault_components import parse_components
from core.i18n import DISPLAY, K
from report.excel_report import SHEETS, export_report
from report.pdf_report import export_pdf


@pytest.fixture
def split_result(store, input_file):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    sheet.cell(4, 5).value = "실린더 및 베어링 손상"
    sheet.cell(5, 5).value = "실린더 누설 또는 베어링 마모"
    workbook.save(input_file)
    workbook.close()
    return analyze_file(store, input_file)


def test_excel_has_one_detail_row_per_fault_including_pending_classifications(
    split_result, tmp_path
):
    original_hash = sha256(split_result.loaded.path.read_bytes()).hexdigest()
    source = split_result.selected.loc[split_result.selected.source_row.eq(4)].iloc[0]
    rows = split_result.tables["fault_detail"]
    members = rows.loc[rows.record_id.eq(source.record_id)]
    assert len(members) == 1 and members.event_id.nunique() == 1
    assert members.iloc[0].status == K["partial"]
    assert tuple(members.iloc[0][key] for key in ("major", "middle", "minor")) == (
        "기계",
        "베어링(종류 미상)",
        "손상·파손",
    )
    assert "1순위 대표 자동선택" in source.classification_reason
    candidates = parse_components(source.classification_candidates)
    assert len(candidates) == 2
    assert {(candidate["middle"], candidate["minor"]) for candidate in candidates} == {
        ("베어링(종류 미상)", "손상·파손"),
        ("실린더(종류 미상)", "손상·파손"),
    }
    protected = split_result.selected.loc[split_result.selected.source_row.eq(5)].iloc[0]
    pending = rows.loc[rows.record_id.eq(protected.record_id)]
    assert len(pending) == 1 and pending.iloc[0].status == K["review"]
    assert not any(pending.iloc[0][key] for key in ("major", "middle", "minor"))
    assert len(parse_components(protected.classification_candidates)) == 2
    assert len(rows) == len(split_result.selected) and rows.record_id.is_unique
    assert not any("minutes" in key for key in rows)
    assert split_result.metrics["selected_rows"] == 4
    assert split_result.metrics["total_minutes"] == 95
    workbook = load_workbook(export_report(split_result, tmp_path / "split.xlsx"), data_only=True)
    try:
        assert len(workbook.sheetnames) == 12
        sheet = workbook[SHEETS["fault_detail"]]
        headers = [cell.value for cell in sheet[6]]
        assert DISPLAY["middle"] in headers and DISPLAY["minor"] in headers
        assert not any("정지시간" in str(value) for value in headers)
        record_column = headers.index(DISPLAY.get("record_id", "record_id")) + 1
        middle_column = headers.index(DISPLAY["middle"]) + 1
        minor_column = headers.index(DISPLAY["minor"]) + 1
        observed = {
            (sheet.cell(row, middle_column).value, sheet.cell(row, minor_column).value)
            for row in range(7, sheet.max_row + 1)
            if sheet.cell(row, record_column).value == source.record_id
        }
        assert observed == {("베어링(종류 미상)", "손상·파손")}
        pending_values = {
            (sheet.cell(row, middle_column).value, sheet.cell(row, minor_column).value)
            for row in range(7, sheet.max_row + 1)
            if sheet.cell(row, record_column).value == protected.record_id
        }
        assert pending_values == {(None, None)}
        assert {sheet.cell(row, record_column).value for row in range(7, sheet.max_row + 1)} == set(
            split_result.selected.record_id
        )
    finally:
        workbook.close()
    assert sha256(split_result.loaded.path.read_bytes()).hexdigest() == original_hash


def test_pdf_explains_single_classification_and_preserves_pending_evidence(split_result, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(export_pdf(split_result, tmp_path / "split.pdf"))
    compact = "".join("".join(page.extract_text() or "" for page in reader.pages).split())
    for expected in (
        "상세설비·세부부품분류",
        "한고장이력은한행",
        "고장분야/상세설비·모듈/세부부품/고장현상",
        "실린더",
        "베어링",
        "손상",
    ):
        assert expected in compact


def test_split_gui_rows_are_read_only_and_open_the_original_event(split_result, store, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "draw_chart", lambda self: None)
    window = MainWindow(store)
    window.loaded_ready(split_result.loaded)
    window.analysis_ready(split_result)
    pane = window.panes["fault_detail"]
    index = pane.proxy.index(0, pane.model.frame.columns.get_loc("middle"))
    assert not (index.flags() & Qt.ItemFlag.ItemIsEditable)
    row = pane.model.frame.iloc[pane.proxy.mapToSource(index).row()]
    window.panes["detail"].search.setText("no matching record")
    window._open_fault_source(index)
    app.processEvents()
    detail = window.panes["detail"]
    selected = detail.proxy.mapToSource(detail.table.currentIndex())
    assert detail.model.frame.iloc[selected.row()].event_id == row.event_id
    assert window.navigation.current_page_key() == "detail"
    assert not detail.search.text()
    window.close()
