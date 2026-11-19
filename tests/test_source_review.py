"""Review workbook preservation, type colors and three-file export failure paths."""

import hashlib
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import analyze_file, finalize_classifications
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Border, Font, PatternFill, Side

from core.i18n import K
from core.models import AnalysisOptions, UserError
from report import export_bundle as bundle
from report.export_bundle import export_bundle, report_paths
from report.source_review import export_source_review


def archive_parts(path):
    with zipfile.ZipFile(path) as book:
        return {info.filename: book.read(info) for info in book.infolist()}


def test_source_copy_preserves_values_formulas_styles_comments_and_unrelated_parts(
    store, input_file, tmp_path
):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    sheet["J3"] = "Formula"
    sheet["J4"] = "=F4*2"
    sheet["E8"].comment = Comment("Original note", "Original author")
    sheet["F8"].font = Font(name="Arial", bold=True, color="001122")
    sheet["F8"].number_format = "0.00"
    sheet["F8"].border = Border(left=Side(style="thin", color="112233"))
    sheet["D8"].fill = PatternFill("solid", fgColor="123456")
    sheet["Y3"] = "Outside highlight range"
    sheet["Y8"] = "=F4*2"
    sheet["Y8"].fill = PatternFill("solid", fgColor="123456")
    sheet.column_dimensions["E"].width = 43
    sheet.freeze_panes = "D4"
    other = workbook.create_sheet("Unanalyzed")
    other["A1"] = "=Events!F4"
    workbook.save(input_file)
    workbook.close()
    with zipfile.ZipFile(input_file, "a") as package:
        package.writestr("xl/vendor/unsupported.bin", b"opaque Excel extension")
    original = input_file.read_bytes()
    before = archive_parts(input_file)
    result = analyze_file(store, input_file)
    result.config_snapshot["settings"]["review_colors"] = {
        "missing_code": "#112233",
        "other": "#778899",
    }
    output = export_source_review(result, tmp_path / "marked.xlsx")
    assert input_file.read_bytes() == original
    after = archive_parts(output)
    changed = {name for name in before if before[name] != after[name]}
    assert changed <= {
        "xl/worksheets/sheet1.xml",
        "xl/styles.xml",
        "[Content_Types].xml",
        "xl/worksheets/_rels/sheet1.xml.rels",
        "xl/comments/comment1.xml",
        "xl/drawings/commentsDrawing1.vml",
    }
    assert after["xl/vendor/unsupported.bin"] == b"opaque Excel extension"
    assert after["xl/worksheets/sheet2.xml"] == before["xl/worksheets/sheet2.xml"]
    marked = load_workbook(output, data_only=False)
    sheet = marked["Events"]
    assert sheet["J4"].value == "=F4*2"
    assert marked["Unanalyzed"]["A1"].value == "=Events!F4"
    assert all(sheet.cell(8, column).fill.fgColor.rgb == "FF112233" for column in range(1, 25))
    assert sheet["Y8"].fill.fgColor.rgb == "00123456" and sheet["Y8"].value == "=F4*2"
    assert sheet["F8"].font.bold and sheet["F8"].font.name == "Arial"
    assert sheet["F8"].number_format == "0.00" and sheet["F8"].border.left.style == "thin"
    assert sheet.column_dimensions["E"].width == 43 and sheet.freeze_panes == "D4"
    assert sheet["E8"].comment.text.startswith("Original note\n\n")
    assert "비가동코드 미기입" in sheet["E8"].comment.text
    assert "정지시간 미기재" in sheet["E8"].comment.text
    assert sheet["E8"].comment.author == "Original author"
    assert sum(sheet.cell(8, column).comment is not None for column in range(1, 25)) == 1
    marked.close()


def test_only_current_review_scope_is_marked(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(date_from="2026-01-03"))
    path = export_source_review(result, tmp_path / "scoped.xlsx")
    marked = load_workbook(path)
    assert marked["Events"]["E4"].comment is None
    assert all(marked["Events"].cell(4, col).fill.patternType is None for col in range(1, 25))
    assert marked["Events"]["E8"].comment is not None
    assert all(marked["Events"].cell(8, col).fill.patternType == "solid" for col in range(1, 25))
    assert marked["Events"].max_column == 24
    marked.close()


def test_all_four_types_color_entire_row_with_primary_reason_priority(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    records = result.selected.copy()
    records["issues"] = ""
    for source_row, status, issues in (
        (4, "review", " | ".join([K["multi_rule"], K["date_invalid"]])),
        (5, "rule_unmatched", K["time_diff"]),
        (6, "code_missing", ""),
        (8, "auto", K["time_missing"]),
    ):
        records.loc[records.source_row.eq(source_row), ["status", "issues"]] = [K[status], issues]
    result = replace(result, tables=dict(result.tables, review=records))
    colors = {
        "multi_match": "#112233",
        "unmatched_rule": "#223344",
        "missing_code": "#334455",
        "other": "#445566",
    }
    result.config_snapshot["settings"]["review_colors"] = colors
    path = export_source_review(result, tmp_path / "four_types.xlsx")
    marked = load_workbook(path)
    for source_row, key in zip((4, 5, 6, 8), colors):
        assert all(
            marked["Events"].cell(source_row, col).fill.fgColor.rgb == "FF" + colors[key][1:]
            for col in range(1, 25)
        )
    assert marked["Events"]["A7"].fill.patternType is None
    marked.close()


def test_changed_source_is_rejected_before_any_output(store, input_file, tmp_path):
    result = analyze_file(store, input_file)
    with input_file.open("ab") as stream:
        stream.write(b"changed")
    path = tmp_path / "marked.xlsx"
    with pytest.raises(UserError, match="원본 파일이 변경"):
        export_source_review(result, path)
    assert not path.exists()


def test_no_review_preserves_every_original_part(store, input_file, tmp_path):
    result = analyze_file(store, input_file, AnalysisOptions(date_from="2030-01-01"))
    path = export_source_review(result, tmp_path / "no_review.xlsx")
    assert archive_parts(path) == archive_parts(input_file)


def test_vertical_merged_cell_does_not_color_a_different_record(store, input_file, tmp_path):
    workbook = load_workbook(input_file)
    workbook["Events"].merge_cells("E4:E5")
    workbook.save(input_file)
    workbook.close()
    result = analyze_file(store, input_file)
    record = result.selected.loc[result.selected.source_row.eq(5)].copy()
    record["status"], record["issues"] = K["code_missing"], ""
    tables = dict(result.tables, review=record)
    path = export_source_review(replace(result, tables=tables), tmp_path / "merged.xlsx")
    marked = load_workbook(path)
    assert marked["Events"]["E4"].comment is None
    assert marked["Events"]["E4"].fill.patternType is None
    assert marked["Events"]["A5"].comment is not None
    assert "E4:E5" in marked["Events"].merged_cells
    marked.close()


def test_xlsm_extension_and_opaque_macro_part_are_preserved(store, input_file, tmp_path):
    source = input_file.with_suffix(".xlsm")
    source.write_bytes(input_file.read_bytes())
    with zipfile.ZipFile(source, "a") as package:
        package.writestr("xl/vbaProject.bin", b"macro fixture")
    result = analyze_file(store, source)
    paths = report_paths(tmp_path / "report.xlsx", source)
    assert paths.source_review is None
    marked = tmp_path / "marked.xlsm"
    export_source_review(result, marked)
    assert archive_parts(marked)["xl/vbaProject.bin"] == b"macro fixture"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == result.loaded.file_hash


@pytest.fixture
def fake_all_writers(monkeypatch):
    for name, value in (
        ("export_report", b"new Excel"),
        ("export_pdf", b"new PDF"),
    ):

        def write(result, path, progress, value=value):
            Path(path).write_bytes(value)
            return Path(path)

        monkeypatch.setattr(bundle, name, write)


def test_previous_sidecar_is_not_an_output_or_modified(
    store, input_file, tmp_path, fake_all_writers
):
    paths = report_paths(tmp_path / "report.xlsx", input_file)
    old_sidecar = tmp_path / "report_원본_검토표시.xlsx"
    old_sidecar.write_bytes(b"keep previous file")
    export_bundle(analyze_file(store, input_file), paths.excel)
    assert paths.source_review is None and old_sidecar.read_bytes() == b"keep previous file"


@pytest.mark.parametrize("existing", [False, True])
def test_third_commit_failure_rolls_back_entire_bundle(
    store, input_file, tmp_path, monkeypatch, fake_all_writers, existing
):
    paths = report_paths(tmp_path / "report.xlsx", input_file)
    targets = [paths.excel, paths.pdf]
    if existing:
        for index, path in enumerate(targets):
            path.write_bytes(f"old {index}".encode())
    original_replace = bundle.os.replace

    def fail_review(source, target):
        if Path(target) == paths.pdf:
            raise PermissionError("review workbook locked")
        return original_replace(source, target)

    monkeypatch.setattr(bundle.os, "replace", fail_review)
    with pytest.raises(UserError):
        export_bundle(finalize_classifications(store, input_file), paths.excel, overwrite=existing)
    for index, path in enumerate(targets):
        assert path.read_bytes() == f"old {index}".encode() if existing else not path.exists()
    assert not list(tmp_path.glob(".efa_export_*"))


def test_third_target_cannot_be_original_source(store, input_file, tmp_path, fake_all_writers):
    source = input_file.with_name("report_원본_검토표시.xlsx")
    source.write_bytes(input_file.read_bytes())
    before = source.read_bytes()
    files = export_bundle(analyze_file(store, source), tmp_path / "report.xlsx", overwrite=True)
    assert files.source_review is None and source.read_bytes() == before


@pytest.mark.parametrize("variant", ["absent", "empty_sections"])
def test_optional_or_incomplete_styles_are_supported(store, input_file, tmp_path, variant):
    parts = archive_parts(input_file)
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    if variant == "absent":
        del parts["xl/styles.xml"]
        for name in ("xl/_rels/workbook.xml.rels", "[Content_Types].xml"):
            root = ET.fromstring(parts[name])
            for item in list(root):
                if (
                    item.get("Type", "").endswith("/styles")
                    or item.get("PartName") == "/xl/styles.xml"
                ):
                    root.remove(item)
            parts[name] = ET.tostring(root)
    else:
        root = ET.fromstring(parts["xl/styles.xml"])
        for name in ("fills", "cellXfs", "cellStyles"):
            root.remove(root.find(f"{{{namespace}}}{name}"))
        parts["xl/styles.xml"] = ET.tostring(root)
    # A style-free workbook has no cell style indexes; this is a valid OOXML source.
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    for cell in root.iter(f"{{{namespace}}}c"):
        cell.attrib.pop("s", None)
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    with zipfile.ZipFile(input_file, "w") as package:
        for name, value in parts.items():
            package.writestr(name, value)
    result = analyze_file(store, input_file)
    path = export_source_review(result, tmp_path / "optional_styles.xlsx")
    marked = load_workbook(path)
    assert marked["Events"]["E8"].comment is not None
    assert marked["Events"]["E8"].fill.patternType == "solid"
    marked.close()


@pytest.mark.parametrize("safe_column", [False, True])
def test_merged_record_without_physical_row_does_not_break_export(
    store, input_file, tmp_path, safe_column
):
    workbook = load_workbook(input_file)
    sheet = workbook["Events"]
    for column in range(1, 10):
        if safe_column and column == 4:
            continue
        sheet.merge_cells(start_row=4, end_row=5, start_column=column, end_column=column)
    if not safe_column:
        # Cover the entire requested A:X range, including blank columns.
        for column in range(10, 25):
            sheet.merge_cells(start_row=4, end_row=5, start_column=column, end_column=column)
    workbook.save(input_file)
    workbook.close()
    parts = archive_parts(input_file)
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    data = root.find(f"{{{namespace}}}sheetData")
    data.remove(data.find(f"{{{namespace}}}row[@r='5']"))
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    if not safe_column:
        # No safely markable cell plus optional styles must not create dangling relations.
        del parts["xl/styles.xml"]
        for name in ("xl/_rels/workbook.xml.rels", "[Content_Types].xml"):
            root = ET.fromstring(parts[name])
            for item in list(root):
                if (
                    item.get("Type", "").endswith("/styles")
                    or item.get("PartName") == "/xl/styles.xml"
                ):
                    root.remove(item)
            parts[name] = ET.tostring(root)
    with zipfile.ZipFile(input_file, "w") as package:
        for name, value in parts.items():
            package.writestr(name, value)
    result = analyze_file(store, input_file)
    record = result.selected.loc[result.selected.source_row.eq(5)].copy()
    assert len(record) == 1
    record["status"], record["issues"] = K["code_missing"], ""
    result = replace(result, tables=dict(result.tables, review=record))
    path = export_source_review(result, tmp_path / "implicit_merged_row.xlsx")
    marked = load_workbook(path)
    assert marked["Events"]["E4"].comment is None
    if safe_column:
        assert marked["Events"]["D5"].comment is not None
    else:
        assert not any(cell.comment for row in marked["Events"] for cell in row)
        assert archive_parts(path) == archive_parts(input_file)
    marked.close()
