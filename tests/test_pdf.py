"""PDF and pair-export regression tests, including failure/rollback paths."""

import hashlib
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

pypdf = pytest.importorskip("pypdf")
from conftest import analyze_file, finalize_classifications

import report.export_bundle as bundle
from core.config import ConfigStore
from core.models import AnalysisOptions, UserError
from core.report_view import report_result
from report.excel_report import SHEETS
from report.export_bundle import export_bundle, report_paths
from report.pdf_report import export_pdf, number, percent, summary_findings


def pdf_text(path):
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)


def test_bundle_generates_three_files_same_totals_and_name(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    original = hashlib.sha256(input_file.read_bytes()).hexdigest()
    files = export_bundle(result, tmp_path / "pair" / "analysis.xlsx")
    assert {p.name for p in files.excel.parent.iterdir()} == {
        files.excel.name,
        files.pdf.name,
        files.source_review.name,
    }
    text = pdf_text(files.pdf)
    assert "미확정 분류" in text and "검토 중에도 출력 가능" in text
    assert "VITAL#2" in text and "IF18115" not in text
    assert "95" in text and "32" in text
    assert "31.7" not in text
    wb = load_workbook(files.excel, data_only=True)
    assert wb["_report_metrics"]["A2"].value == 4
    assert wb["_report_metrics"]["A3"].value == 95
    assert "95분" in wb[SHEETS["summary"]]["A5"].value
    assert len([ws for ws in wb if ws.sheet_state == "visible"]) == 12 and not any(
        "\uc81c\ud488\ubcc4\ubd84\uc11d" in x for x in wb.sheetnames
    )
    wb.close()
    assert hashlib.sha256(input_file.read_bytes()).hexdigest() == original
    assert result.selected.iloc[0]["equipment_code"] == "IF18115"


def test_pdf_uses_latest_saved_name_everywhere(store, input_file, tmp_path):
    store.save_equipment_names({"IF18115": "LATEST#2", "IF20000": "SECOND#1"})
    result = analyze_file(ConfigStore(store.root), input_file)
    path = export_pdf(result, tmp_path / "latest.pdf")
    text = pdf_text(path)
    for value in ("IF18115", "IF20000", "VITAL#2"):
        assert value not in text
    assert "LATEST#2" in text and "SECOND#1" in text


def test_empty_selection_produces_pdf_without_division_errors(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(date_from="2030-01-01"))
    text = pdf_text(export_pdf(result, tmp_path / "empty.pdf"))
    assert "\uc120\ud0dd\ud55c \uc870\uac74" in text
    assert "nan" not in text.lower()
    assert summary_findings(result)[0][0] == "\ubd84\uc11d \ubc94\uc704"


def test_all_scope_title_and_count(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(scope="all"))
    text = pdf_text(export_pdf(result, tmp_path / "all.pdf"))
    assert "\ube44\uac00\ub3d9 \ucd5c\uc885" in text
    assert result.metrics["selected_rows"] == 5


def test_pdf_missing_times_do_not_become_fake_zero(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(date_from="2026-01-03"))
    assert result.metrics["total_minutes"] is None
    text = pdf_text(export_pdf(result, tmp_path / "missing.pdf"))
    assert "\uc720\ud6a8\ud55c \uc591\uc218" in text
    assert "nan" not in text.lower() and "inf%" not in text.lower()
    assert number(None) == "-" and percent(float("nan")) == "-"


def test_metadata_escapes_markup_and_persists(store, input_file, tmp_path):
    store.save_report_settings(
        {
            "title": "Report <R&D>",
            "department": "Production & QA",
            "prepared_by": "OP",
            "closing_note": "User note: <tag> & not an automatically inferred cause.",
        }
    )
    result = analyze_file(ConfigStore(store.root), input_file)
    text = pdf_text(export_pdf(result, tmp_path / "meta.pdf"))
    assert "Report <R&D>" in text and "Production & QA" in text
    assert "<tag> & not" in text
    assert store.read("final_report.json")["title"] == "Report <R&D>"


def test_settings_length_validation_keeps_good_file(store):
    original = (store.config_dir / "final_report.json").read_bytes()
    with pytest.raises(UserError):
        store.save_report_settings({"title": "x" * 101})
    assert (store.config_dir / "final_report.json").read_bytes() == original


def test_upgrade_adds_pdf_settings_without_overwriting_names(store):
    store.save_equipment_names({"IF18115": "KEPT"})
    (store.config_dir / "final_report.json").unlink()
    cfg = ConfigStore(store.root).load()
    assert cfg["equipment_names"]["mappings"] == {"IF18115": "KEPT"}
    assert cfg["final_report"]["schema_version"] == 1


def test_pdf_optional_sections(store, input_file, tmp_path):
    path = store.config_dir / "final_report.json"
    data = json.loads(path.read_text())
    data.update(include_monthly=False, include_equipment_details=False, include_review=False)
    path.write_text(json.dumps(data))
    text = pdf_text(export_pdf(analyze_file(store, input_file), tmp_path / "short.pdf"))
    assert "04  \uc6d4\ubcc4" not in text
    assert "05  \uc124\ube44\ubcc4" not in text
    assert "\uad00\ub9ac \uac80\ud1a0\uc0ac\ud56d" in text


def test_pdf_has_korean_embedded_font(store, input_file, tmp_path):
    path = export_pdf(analyze_file(store, input_file), tmp_path / "fonts.pdf")
    fonts = pypdf.PdfReader(path).pages[0]["/Resources"]["/Font"].get_object().values()
    assert any(
        "/FontDescriptor" in f.get_object()
        and "/FontFile2" in f.get_object()["/FontDescriptor"].get_object()
        for f in fonts
    )


def test_ties_are_not_reported_as_a_unique_winner(store, input_file):
    result = analyze_file(store, input_file)
    rows = summary_findings(report_result(result))
    assert "\uac01 2\uac74" in rows[0][1]
    assert "VITAL#2" in rows[0][1] and "IF20000" in rows[0][1]


def test_paths_use_one_common_stem(tmp_path):
    files = report_paths(tmp_path / "Korean report.XLSX")
    assert files.excel.name == "Korean report.xlsx"
    assert files.pdf.name == "Korean report_\ucd5c\uc885\ubcf4\uace0\uc11c.pdf"


def test_input_overwrite_forbidden(store, input_file):
    with pytest.raises(UserError):
        export_bundle(analyze_file(store, input_file), input_file, overwrite=True)


@pytest.fixture
def fake_writers(monkeypatch):
    def excel(result, path, progress):
        Path(path).write_bytes(b"new excel")
        return Path(path)

    def pdf(result, path, progress):
        Path(path).write_bytes(b"new pdf")
        return Path(path)

    monkeypatch.setattr(bundle, "export_report", excel)
    monkeypatch.setattr(bundle, "export_pdf", pdf)


@pytest.mark.parametrize("target_index", [0, 1])
def test_either_existing_file_prevents_unconfirmed_overwrite(
    store, input_file, tmp_path, fake_writers, target_index
):
    result = analyze_file(store, input_file)
    files = report_paths(tmp_path / "out.xlsx")
    path = (files.excel, files.pdf)[target_index]
    path.write_bytes(b"existing")
    with pytest.raises(UserError):
        export_bundle(result, files.excel)
    assert path.read_bytes() == b"existing"


def test_confirmed_overwrite_replaces_both_files(store, input_file, tmp_path, fake_writers):
    result = finalize_classifications(store, input_file)
    files = report_paths(tmp_path / "out.xlsx")
    files.excel.write_bytes(b"old excel")
    files.pdf.write_bytes(b"old pdf")
    export_bundle(result, files.excel, overwrite=True)
    assert files.excel.read_bytes() == b"new excel" and files.pdf.read_bytes() == b"new pdf"


@pytest.mark.parametrize("existing", [False, True])
def test_pdf_failure_leaves_no_half_pair(
    store, input_file, tmp_path, monkeypatch, fake_writers, existing
):
    result = finalize_classifications(store, input_file)
    files = report_paths(tmp_path / "out.xlsx")
    if existing:
        files.excel.write_bytes(b"old excel")
        files.pdf.write_bytes(b"old pdf")

    def fail(*args):
        raise RuntimeError("PDF failed")

    monkeypatch.setattr(bundle, "export_pdf", fail)
    with pytest.raises(RuntimeError):
        export_bundle(result, files.excel, overwrite=existing)
    if existing:
        assert files.excel.read_bytes() == b"old excel" and files.pdf.read_bytes() == b"old pdf"
    else:
        assert not files.excel.exists() and not files.pdf.exists()
    assert not list(tmp_path.glob(".efa_export_*"))


@pytest.mark.parametrize("existing", [False, True])
def test_second_commit_failure_rolls_back_excel(
    store, input_file, tmp_path, monkeypatch, fake_writers, existing
):
    result = finalize_classifications(store, input_file)
    files = report_paths(tmp_path / "out.xlsx")
    if existing:
        files.excel.write_bytes(b"old excel")
        files.pdf.write_bytes(b"old pdf")
    original = bundle.os.replace

    def fail_pdf(source, destination):
        if Path(destination) == files.pdf:
            raise PermissionError("Simulated PDF lock")
        return original(source, destination)

    monkeypatch.setattr(bundle.os, "replace", fail_pdf)
    with pytest.raises(UserError):
        export_bundle(result, files.excel, overwrite=existing)
    if existing:
        assert files.excel.read_bytes() == b"old excel" and files.pdf.read_bytes() == b"old pdf"
    else:
        assert not files.excel.exists() and not files.pdf.exists()
    assert not list(tmp_path.glob(".efa_export_*"))
