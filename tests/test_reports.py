"""Report rendering, shared resources, and safe output failure paths."""

from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock

import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.models import AnalysisOptions
from report import charts
from report import excel_report as excel
from report import pdf_report as pdf
from report.output import atomic_output


def test_missing_time_excel_summary_does_not_name_a_time_leader(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(date_from="2026-01-03"))
    path = excel.export_report(result, tmp_path / "missing.xlsx")
    workbook = load_workbook(path, data_only=True)
    try:
        summary = workbook[excel.SHEETS["summary"]]
        assert summary["E7"].value in (None, "")
        text = "\n".join(
            str(cell.value) for row in summary for cell in row if cell.value is not None
        )
        assert "nan" not in text.lower()
        assert "시간 기준 최다 설비를 선정하지 않았습니다" in text
        assert "최다 설비:" not in text
    finally:
        workbook.close()


def test_equipment_charts_share_rendering_and_describe_configured_limit(
    store, input_file, tmp_path, monkeypatch
):
    result = analyze_file(store, input_file)
    settings = {**result.config_snapshot["settings"], "donut_top_n": 3}
    result = replace(result, config_snapshot={**result.config_snapshot, "settings": settings})
    render = Mock(wraps=excel.donut_png)
    breakdown = Mock(wraps=excel.type_breakdown)
    monkeypatch.setattr(excel, "donut_png", render)
    monkeypatch.setattr(excel, "type_breakdown", breakdown)
    path = excel.export_report(result, tmp_path / "shared.xlsx")
    assert render.call_count == result.metrics["equipment_count"]
    assert breakdown.call_count == result.metrics["equipment_count"]
    assert all(call.kwargs["top_n"] == 3 for call in render.call_args_list)
    workbook = load_workbook(path, data_only=True)
    try:
        for key in ("equipment", "equipment_types"):
            assert len(workbook[excel.SHEETS[key]]._images) == result.metrics["equipment_count"]
        overview = "\n".join(
            str(cell.value) for row in workbook[excel.SHEETS["equipment"]] for cell in row
        )
        quality = "\n".join(
            str(cell.value) for row in workbook[excel.SHEETS["quality"]] for cell in row
        )
        assert "상위 3개 유형 + 기타" in overview
        assert "상위 3개 외 유형 합산" in quality
    finally:
        workbook.close()


@pytest.mark.parametrize("writer", ["excel", "pdf"])
def test_report_failure_preserves_existing_file_and_cleans_resources(
    store, input_file, tmp_path, monkeypatch, writer
):
    result = analyze_file(store, input_file)
    resources = {}

    def fail(report, *args):
        buffer = BytesIO(b"chart")
        resources["buffer"] = buffer
        if writer == "excel":
            report.images.append(buffer)
            resources["close"] = Mock(wraps=report.wb.close)
            monkeypatch.setattr(report.wb, "close", resources["close"])
        else:
            report.buffers.append(buffer)
        raise RuntimeError("Generation failed")

    if writer == "excel":
        monkeypatch.setattr(excel.ReportBuilder, "build", fail)
        exporter = excel.export_report
        suffix = ".xlsx"
    else:
        # Failure during story assembly must release charts created so far.
        monkeypatch.setattr(pdf.FinalReport, "overview", fail)
        exporter = pdf.export_pdf
        suffix = ".pdf"
    target = tmp_path / ("existing" + suffix)
    target.write_bytes(b"previous report")
    with pytest.raises(RuntimeError, match="Generation failed"):
        exporter(result, target)
    assert target.read_bytes() == b"previous report"
    assert resources["buffer"].closed
    if writer == "excel":
        resources["close"].assert_called_once_with()
    assert not list(tmp_path.glob("efa_*"))


def test_png_encoding_failure_releases_figure_and_buffer(monkeypatch):
    buffer = BytesIO()
    monkeypatch.setattr(charts, "BytesIO", lambda: buffer)
    figure = charts.Figure()
    figure.add_subplot(111)

    def fail(*args):
        raise RuntimeError("PNG encoding failed")

    monkeypatch.setattr(charts.FigureCanvasAgg, "print_png", fail)
    with pytest.raises(RuntimeError, match="PNG encoding failed"):
        charts._figure_png(figure)
    assert buffer.closed
    assert not figure.axes


def test_atomic_output_commits_only_completed_content(tmp_path):
    target = tmp_path / "nested" / "report.pdf"
    with atomic_output(target, prefix="test_") as temporary:
        assert temporary.parent == target.parent
        temporary.write_bytes(b"complete report")
        assert not target.exists()
    assert target.read_bytes() == b"complete report"
    assert list(target.parent.iterdir()) == [target]
