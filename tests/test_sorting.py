"""Regression coverage for descending views and suppression of empty-product notes."""

import ast
from pathlib import Path

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import load_workbook

from core.i18n import K
from core.sorting import default_metric, descending
from report.charts import figure_for
from report.excel_report import DETAIL_COLS, SHEETS, export_report
from report.pdf_report import export_pdf


@pytest.mark.parametrize(
    "values", [[8, 36, 14, 27], [1293, 276, 491, 892], [0.275, 0.061, 0.106, 0.206]]
)
def test_numeric_descending_not_text_order(values):
    frame = pd.DataFrame({"name": ["A", "Z", "B", "Y"], "count": values})
    before = frame.copy(deep=True)
    got = descending(frame, "count")
    assert got["count"].tolist() == sorted(values, reverse=True)
    pd.testing.assert_frame_equal(frame, before)


def test_ties_and_missing_values():
    frame = pd.DataFrame(
        {
            "equipment": list("ABCDE"),
            "total_minutes": [None, 10, 100, 10, 0],
            "count": [1000, 2, 1, 8, 20],
        }
    )
    got = descending(frame)
    assert got["equipment"].tolist() == list("CDBEA")
    assert pd.isna(got.iloc[-1]["total_minutes"])


def test_count_ranking_ties_use_time():
    frame = pd.DataFrame({"type": list("ABC"), "count": [3, 3, 8], "total_minutes": [10, 100, 1]})
    assert descending(frame, "count")["type"].tolist() == ["C", "B", "A"]


def test_empty_and_source_order():
    frame = pd.DataFrame({"label": ["Z", "A"]})
    assert default_metric(frame) is None
    pd.testing.assert_frame_equal(descending(frame), frame)
    assert descending(pd.DataFrame()).empty


def test_all_numeric_aggregate_tables_descending(store, input_file):
    result = analyze_file(store, input_file)
    for name, table in result.tables.items():
        if "total_minutes" in table:
            valid = table["total_minutes"].dropna().tolist()
            assert valid == sorted(valid, reverse=True), name
        elif name in ("long_stops", "review"):
            valid = table["minutes"].dropna().tolist()
            assert valid == sorted(valid, reverse=True), name


def test_period_table_ranked_but_chart_chronological():
    table = pd.DataFrame(
        {
            "period": ["2026-02", "2026-03", "2026-01"],
            "total_minutes": [100, 50, 10],
            "count": [2, 3, 1],
        }
    )
    fig = figure_for(table, "period", "total_minutes", "trend")
    ax = fig.axes[0]
    assert [tick.get_text() for tick in ax.get_xticklabels()] == ["2026-01", "2026-02", "2026-03"]
    assert ax.lines[0].get_ydata().tolist() == [10, 100, 50]
    fig.clear()


def test_detail_export_sorted_without_mutating_source(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    ids = result.selected.record_id.tolist()
    path = export_report(result, tmp_path / "descending.xlsx")
    wb = load_workbook(path, data_only=True)
    detail = wb[SHEETS["detail"]]
    minutes = DETAIL_COLS.index("minutes") + 1
    assert [detail.cell(r, minutes).value for r in range(7, 11)] == [65, 20, 10, None]
    for name in ("equipment", "line", "type"):
        table = wb[SHEETS[name]]
        values = [table.cell(r, 5).value for r in range(7, 7 + len(result.tables[name]))]
        actual = [v for v in values if v is not None]
        assert actual == sorted(actual, reverse=True)
    assert result.selected.record_id.tolist() == ids
    wb.close()


@pytest.fixture
def no_product_file(input_file):
    wb = load_workbook(input_file)
    wb.active.delete_cols(4)
    wb.save(input_file)
    wb.close()
    return input_file


def test_no_product_does_not_create_issues_or_notes(store, no_product_file):
    result = analyze_file(store, no_product_file)
    assert result.metrics["product_count"] == 0
    assert all("\uc81c\ud488" not in note for note in result.notes)
    assert not result.selected["issues"].str.contains("\uc81c\ud488").any()
    assert "no_product" not in K and "product_missing" not in K


def test_empty_product_report_blocks_are_omitted(store, no_product_file, tmp_path):
    result = analyze_file(store, no_product_file)
    wb = load_workbook(export_report(result, tmp_path / "without_product.xlsx"), data_only=True)
    all_text = "\n".join(
        str(cell.value) for sheet in wb for row in sheet for cell in row if cell.value is not None
    )
    for phrase in (
        "\uc81c\ud488 \ubbf8\uae30\uc7ac",
        "\uc81c\ud488\uba85 \uc815\ubcf4\uac00 \uc5c6\uc5b4",
    ):
        assert phrase not in all_text
    assert SHEETS["cross"] not in wb.sheetnames
    for name in ("equipment", "type"):
        text = "\n".join(
            str(cell.value) for row in wb[SHEETS[name]] for cell in row if cell.value is not None
        )
        assert "\uc81c\ud488" not in text
    ws = wb[SHEETS["detail"]]
    from openpyxl.utils import get_column_letter

    assert ws.column_dimensions[get_column_letter(DETAIL_COLS.index("product") + 1)].hidden
    wb.close()


def test_pdf_absent_product_notes_and_rank_order(store, no_product_file, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    result = analyze_file(store, no_product_file)
    path = export_pdf(result, tmp_path / "final.pdf")
    reader = pypdf.PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "\uc81c\ud488 \ubbf8\uae30\uc7ac" not in text
    assert "\uc81c\ud488\uba85 \uc815\ubcf4\uac00 \uc5c6\uc5b4" not in text
    comparison = reader.pages[1].extract_text()
    assert comparison.index("IF20000") < comparison.index("VITAL#2")


def test_obsolete_runtime_message_references_are_removed():
    root = Path(__file__).resolve().parents[1]
    banned = {"no_product", "product_missing", "missing_product_rows"}
    for directory in ("core", "gui", "report"):
        for path in (root / directory).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assert node.value not in banned, (path, node.lineno)
