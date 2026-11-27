"""PDF renderer regression tests."""

import json

import pytest

pypdf = pytest.importorskip("pypdf")
from conftest import analyze_file

from core.config import ConfigStore
from core.models import AnalysisOptions, UserError
from core.report_view import report_result
from report.pdf_report import export_pdf, number, percent, summary_findings


def pdf_text(path):
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(path).pages)


def test_pdf_summary_uses_analysis_totals(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    text = pdf_text(export_pdf(result, tmp_path / "analysis.pdf"))
    assert "미확정 분류" in text and "검토 중에도 출력 가능" in text
    assert "VITAL#2" in text and "IF18115" not in text
    assert "95" in text and "32" in text
    assert "31.7" not in text


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
