"""The user's Excel design is fixed while formulas and chart data stay live."""

from __future__ import annotations

import re
from copy import copy
from dataclasses import replace
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
import pytest
import test_report_issue_views
from openpyxl import load_workbook
from PIL import Image

from core.analyzer import analyze
from report.excel_report import ReportBuilder
from report.locked_template import (
    LOCKED_SHEETS,
    METRICS_SHEET,
    NS,
    template_path,
)


@pytest.fixture
def organization_result(store, input_file):
    return test_report_issue_views.organization_result.__wrapped__(store, input_file)


def populate(result, path):
    from report.excel_report import export_report

    builder = ReportBuilder(result)
    export_report(result, path)
    return builder


def without_caches(raw):
    raw = re.sub(rb"<c:(strCache|numCache)\b[^>]*>.*?</c:\1>", b"", raw, flags=re.DOTALL)
    raw = re.sub(
        rb'(<c:numFmt\b[^>]*formatCode=")([^"]*)(")',
        lambda m: m[0] if b"%" in m[2] else m[1] + re.sub(rb"\.0+", b"", m[2]) + m[3],
        raw,
    )
    if b'<c:barDir val="bar"' in raw:
        raw = re.sub(
            rb'<c:orientation val="(?:minMax|maxMin)"/>', b'<c:orientation val="maxMin"/>', raw
        )
    return raw


def test_template_asset_contains_design_only():
    book = load_workbook(template_path())
    assert book.sheetnames == sorted(LOCKED_SHEETS)
    assert sum(len(sheet._charts) for sheet in book) == 6
    assert sum(len(sheet._images) for sheet in book) == 0
    assert not any(cell.data_type == "f" for sheet in book for row in sheet for cell in row)
    with ZipFile(template_path()) as archive:
        assert "xl/sharedStrings.xml" not in archive.namelist()
        assert "xl/calcChain.xml" not in archive.namelist()
        assert not any("printerSettings" in name for name in archive.namelist())
        for name in archive.namelist():
            if name.startswith("xl/media/"):
                assert Image.open(BytesIO(archive.read(name))).size == (1, 1)
            elif name.endswith(".xml"):
                text = archive.read(name).decode("utf-8")
                assert all(word not in text for word in ("38,802", "1P M/Y", "정태균", "서경식"))
                if name.startswith("xl/charts/chart"):
                    assert "<c:numCache>" not in text and "<c:strCache>" not in text
    book.close()


def test_locked_design_keeps_formats_and_approved_filter_space(organization_result, tmp_path):
    path = tmp_path / "locked.xlsx"
    builder = populate(organization_result, path)
    design = load_workbook(template_path())
    result = load_workbook(path)
    try:
        assert result.sheetnames[:4] == sorted(LOCKED_SHEETS)
        assert result._fonts[0] == design._fonts[0]
        for name in LOCKED_SHEETS:
            source = design[name]
            target = result[name]
            for address in ("A1", "A4"):
                assert target[address].font == copy(source[address].font)
                assert target[address].fill == copy(source[address].fill)
                assert target[address].alignment == copy(source[address].alignment)
            assert target.row_dimensions[1].height == source.row_dimensions[1].height
            assert target.row_dimensions[2].height == source.row_dimensions[2].height
            assert target.row_dimensions[5].height == source.row_dimensions[5].height
            assert target.column_dimensions["A"].width == 13
            assert target.page_margins == source.page_margins
            assert target.sheet_properties.pageSetUpPr.fitToPage
            assert target.page_setup.fitToWidth == 1
        assert {"B6:C6", "B8:C8", "E6:G6", "E8:G8", "A7:J7"} <= {
            str(x) for x in result["04.고장비교"].merged_cells.ranges
        }
        for name in LOCKED_SHEETS[1:]:
            assert len(result[name]._charts) == 2
    finally:
        builder.close()
        design.close()
        result.close()


def test_locked_values_formulas_and_native_graphics(organization_result, tmp_path):
    path = tmp_path / "values.xlsx"
    builder = populate(organization_result, path)
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        assert values[METRICS_SHEET]["A2"].value == 6
        assert values[METRICS_SHEET]["A3"].value == 144
        assert values[METRICS_SHEET]["A4"].value == 28.8
        assert "평균 정지시간 29분" in values[LOCKED_SHEETS[0]]["A5"].value
        assert values[LOCKED_SHEETS[1]]["C9"].value == 6
        assert values[LOCKED_SHEETS[1]]["E9"].value == 144
        comparison = values["04.고장비교"]
        assert [comparison.cell(26, col).value for col in (5, 6, 8, 9)] == [2, 100, -2, 56]
        trend = values["03.월별 주요이슈"]
        assert [(trend.cell(row, 2).value, trend.cell(row, 3).value) for row in range(24, 28)] == [
            (3, 130),
            (0, 0),
            (1, None),
            (2, 14),
        ]
        with ZipFile(path) as output:
            for number in range(1, 7):
                raw = output.read(f"xl/charts/chart{number}.xml")
                assert b"xmlns:c=" in raw
                root = ET.fromstring(raw)
                for label in root.findall(".//c:dLbls", NS):
                    assert label.find("c:showVal", NS).get("val") == "1"
                    assert label.find("c:numFmt", NS).get("formatCode") == "#,##0"
    finally:
        builder.close()
        values.close()
        formulas.close()


@pytest.mark.parametrize("minutes,empty", [(None, False), (0, False), (None, True)])
def test_summary_missing_time_and_zero_stay_distinct(organization_result, tmp_path, minutes, empty):
    records = organization_result.all_records.copy()
    records["minutes"] = minutes
    result = analyze(
        organization_result.loaded,
        records,
        organization_result.config_snapshot,
        replace(organization_result.options, factory="없는 공장")
        if empty
        else organization_result.options,
    )
    path = tmp_path / "missing.xlsx"
    builder = populate(result, path)
    values = load_workbook(path, data_only=True)
    try:
        text = values[LOCKED_SHEETS[0]]["A5"].value
        if minutes == 0 and not empty:
            assert "정지시간 합계 0분" in text
            assert "평균 정지시간 0분" in text
        else:
            assert "정지시간 합계 확인 필요" in text
            assert "평균 정지시간 확인 필요" in text
            assert values[METRICS_SHEET]["A3"].value is None
    finally:
        builder.close()
        values.close()


def test_longer_tables_preserve_every_organization_and_month(organization_result, tmp_path):
    rows = []
    for index in range(24):
        row = organization_result.all_records.iloc[0].to_dict()
        row.update(
            record_id=f"grow-{index}",
            event_id=f"grow-{index}",
            source_row=index + 4,
            factory=f"공장{index % 9}",
            team="팀",
            date=pd.Timestamp("2025-01-01") + pd.DateOffset(months=index),
        )
        rows.append(row)
    result = analyze(
        replace(
            organization_result.loaded,
            frame=pd.DataFrame(
                [
                    dict(organization_result.loaded.frame.iloc[0], __source_row=index + 4)
                    for index in range(24)
                ]
            ),
        ),
        pd.DataFrame(rows),
        organization_result.config_snapshot,
        organization_result.options,
    )
    path = tmp_path / "grow.xlsx"
    builder = populate(result, path)
    values = load_workbook(path, data_only=True)
    try:
        comparison, trend = values["04.고장비교"], values["03.월별 주요이슈"]
        assert (
            sum(comparison.cell(row, 5).value or 0 for row in range(25, comparison.max_row + 1))
            == 24
        )
        assert sum(trend.cell(row, 2).value or 0 for row in range(24, 48)) == 24
        assert comparison["A33"].value == "공장8"
        assert trend["A47"].value == "2026-12"
        assert comparison._charts[0].anchor._from.row < 24
        assert trend._charts[0].anchor._from.row < 24
        assert trend.row_dimensions[47].height > 0
    finally:
        builder.close()
        values.close()
