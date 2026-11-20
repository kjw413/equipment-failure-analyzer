"""Macro packaging must preserve the report and never alter its source workbook."""

import hashlib
import json
from pathlib import Path
from shutil import copyfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report
from report.export_bundle import export_bundle, report_paths
from report.search_project import VBA_REL, embed_search_project


def test_report_paths_preserve_explicit_format_and_default_to_search(tmp_path):
    assert report_paths(tmp_path / "report").excel.suffix == ".xlsm"
    assert report_paths(tmp_path / "report.xlsm").excel.suffix == ".xlsm"
    assert report_paths(tmp_path / "report.xlsx").excel.suffix == ".xlsx"
    assert report_paths(tmp_path / "report.xlsm", "source.xlsx").source_review is None


def test_embedded_project_matches_reviewable_vba_source():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config/report_search_vba.json").read_text(encoding="utf-8"))
    assert manifest["workbook_codename"] == "ThisWorkbook"
    # OLE directory names are UTF-16. The old localized document module caused
    # workbook events to silently disappear despite working public VBA functions.
    assert (
        manifest["workbook_codename"].encode("utf-16-le")
        in (root / "config/report_search_vba.bin").read_bytes()
    )
    assert (
        hashlib.sha256((root / "config/report_search_vba.bin").read_bytes()).hexdigest()
        == manifest["project_sha256"]
    )
    for name, digest in manifest["source_sha256"].items():
        assert hashlib.sha256((root / "report/vba" / name).read_bytes()).hexdigest() == digest


def test_macro_report_keeps_values_charts_and_exact_lists(organization_result, tmp_path):
    source = organization_result.loaded.path.read_bytes()
    plain = export_report(organization_result, tmp_path / "plain.xlsx")
    macro = export_report(organization_result, tmp_path / "search.xlsm")
    injected = tmp_path / "injected.xlsm"
    copyfile(plain, injected)
    embed_search_project(injected)
    with ZipFile(plain) as before, ZipFile(injected) as after, ZipFile(macro) as exported:
        assert "xl/vbaProject.bin" not in before.namelist()
        assert after.read("xl/vbaProject.bin").startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
        assert exported.read("xl/vbaProject.bin") == after.read("xl/vbaProject.bin")
        for name in before.namelist():
            if name not in (
                "[Content_Types].xml",
                "xl/workbook.xml",
                "xl/_rels/workbook.xml.rels",
            ):
                assert before.read(name) == after.read(name), name
        relationships = ET.fromstring(after.read("xl/_rels/workbook.xml.rels"))
        assert sum(item.get("Type") == VBA_REL for item in relationships) == 1
        contents = ET.fromstring(after.read("[Content_Types].xml"))
        properties = ET.fromstring(after.read("xl/workbook.xml")).find(
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbookPr"
        )
        assert properties.get("codeName") == "ThisWorkbook"
        assert b'<Types xmlns="' in after.read("[Content_Types].xml")
        workbook_type = next(
            e.get("ContentType") for e in contents if e.get("PartName") == "/xl/workbook.xml"
        )
        assert workbook_type == "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
    book = load_workbook(macro, keep_vba=True, data_only=True)
    try:
        issues = book["02.팀별 주요이슈"]
        assert issues["B7"].value == "(전체)"
        assert len(issues._charts) == 2
        validation = next(v for v in issues.data_validations.dataValidation if "B7" in v.sqref)
        assert validation.formula1 == "=_Issue_factory" and validation.showErrorMessage
        assert book.vba_archive is not None
    finally:
        book.close()
    assert organization_result.loaded.path.read_bytes() == source


def test_macro_bundle_keeps_source_review_inside_one_workbook(organization_result, tmp_path):
    before = organization_result.loaded.path.read_bytes()
    files = export_bundle(organization_result, tmp_path / "bundle.xlsm")
    assert files.excel.suffix == ".xlsm"
    assert files.pdf.read_bytes().startswith(b"%PDF")
    assert files.source_review is None
    with ZipFile(files.excel) as result:
        assert "xl/vbaProject.bin" in result.namelist()
        assert any(n.startswith("xl/source_snapshot/") for n in result.namelist())
    assert organization_result.loaded.path.read_bytes() == before
