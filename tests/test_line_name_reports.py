"""Line-code naming and configured groups must reach the final report outputs."""

import hashlib

import pytest
from conftest import analyze_file, finalize_classifications
from openpyxl import Workbook, load_workbook

import analyze_cli
from core.config import ConfigStore
from core.models import AnalysisOptions
from core.report_view import report_result
from report.excel_report import DETAIL_COLS, SHEETS, export_report
from report.export_bundle import export_bundle, report_paths
from report.pdf_report import export_pdf
from report.source_review import export_source_review


@pytest.fixture
def line_file(tmp_path):
    path = tmp_path / "line_codes.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "MES"
    sheet.append(
        [
            "작업일자",
            "순번",
            "라인(코드)",
            "라인명",
            "설비(코드)",
            "설비명",
            "고장내용",
            "정지시간",
            "정지구분",
        ]
    )
    for index, (line, equipment, minutes) in enumerate(
        [("LN01", "EQ01", 10), ("LN01", "EQ02", 20), ("LN02", "EQ03", 30)], 1
    ):
        sheet.append(
            [
                "2026-11-01",
                index,
                line,
                "원본 " + line,
                equipment,
                "원본 " + equipment,
                "타이밍벨트 파손 교체",
                minutes,
                "고장",
            ]
        )
    workbook.save(path)
    workbook.close()
    return path


def setup_line_names(store):
    store.save_equipment_names({"EQ01": "이전설비#9"}, source="equipment")
    store.save_equipment_names({"LN01": "A#1(1호기)", "LN02": "A#2"}, source="line")


def test_line_names_and_groups_reach_excel_and_pdf(store, line_file, tmp_path):
    setup_line_names(store)
    source_hash = hashlib.sha256(line_file.read_bytes()).hexdigest()
    result = analyze_file(store, line_file)
    assert result.loaded.mapping["line_id"] == "라인(코드)"
    assert result.selected.equipment.tolist() == ["A#1(1호기)", "A#1(1호기)", "A#2"]
    assert result.selected.equipment_code.tolist() == ["EQ01", "EQ02", "EQ03"]
    projected = report_result(result)
    assert projected.selected.line_code.tolist() == ["A#1(1호기)", "A#1(1호기)", "A#2"]
    assert projected.selected.equipment_code.tolist() == ["EQ01", "EQ02", "EQ03"]
    grouped = analyze_file(store, line_file, AnalysisOptions(equipment_basis="group"))
    assert grouped.tables["equipment"].equipment.tolist() == ["A"]
    assert grouped.tables["equipment"].iloc[0]["count"] == 3
    assert grouped.tables["equipment"].iloc[0]["total_minutes"] == 60
    assert grouped.selected.event_id.tolist() == result.selected.event_id.tolist()

    path = export_report(grouped, tmp_path / "group.xlsx")
    book = load_workbook(path, data_only=True)
    assert book["_report_metrics"]["A2"].value == 3
    assert book["_report_metrics"]["A3"].value == 60
    [(sheet_name, table_range)] = book.defined_names["_Fault_TableRows"].destinations
    assert sheet_name == SHEETS["issue_comparison"]
    rows = book[sheet_name][table_range]
    assert sum(row[4].value or 0 for row in rows) == 3
    assert sum(row[5].value or 0 for row in rows) == 60
    assert "별첨. 기준정보" not in book
    details = book[SHEETS["detail"]]
    group_column = DETAIL_COLS.index("equipment_group") + 2
    assert {details.cell(row, group_column).value for row in range(7, 10)} == {"A"}
    book.close()
    pypdf = pytest.importorskip("pypdf")
    pdf = export_pdf(grouped, tmp_path / "group.pdf")
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(pdf).pages)
    assert "설비군(이름 기준)" in text
    assert "이전설비#9" not in text
    assert hashlib.sha256(line_file.read_bytes()).hexdigest() == source_hash


def test_cli_line_mapping_and_group_basis(line_file, tmp_path, monkeypatch, capsys):
    observed = {}

    def export(result, output, *, overwrite):
        observed["result"] = result
        return report_paths(output, result.loaded.path)

    monkeypatch.setattr(analyze_cli, "export_bundle", export)
    profile = tmp_path / "cli_profile"
    assert (
        analyze_cli.main(
            [
                str(line_file),
                "--output",
                str(tmp_path / "out.xlsx"),
                "--data-dir",
                str(profile),
                "--name-source",
                "line",
                "--basis",
                "group",
                "--set-name",
                "LN01=A#1",
                "--set-name",
                "LN02=A#2",
            ]
        )
        == 0
    )
    assert observed["result"].tables["equipment"].equipment.tolist() == ["A"]
    names = ConfigStore(profile).load()["equipment_names"]
    assert names["line_mappings"] == {"LN01": "A#1", "LN02": "A#2"}
    assert names["mappings"]["IF18115"] == "VITAL#2"
    assert "Rows: 3" in capsys.readouterr().out


def test_group_label_that_matches_a_line_code_is_not_renamed(store, line_file, tmp_path):
    workbook = load_workbook(line_file)
    workbook.active["C4"] = "A"
    workbook.save(line_file)
    workbook.close()
    store.save_equipment_names({"LN01": "A#1", "A": "B#2"}, source="line")
    result = analyze_file(store, line_file, AnalysisOptions(equipment_basis="group"))
    projected = report_result(result)
    assert projected.selected.equipment_group.tolist() == ["A", "A", "B"]
    assert projected.tables["equipment"].equipment.tolist() == ["A", "B"]
    assert projected.selected.line_code.tolist() == ["A#1", "A#1", "B#2"]
    output = export_report(result, tmp_path / "collision.xlsx")
    book = load_workbook(output, data_only=True)
    assert {book["_issue_facts"].cell(row, 5).value for row in range(2, 5)} == {"A#1", "B#2"}
    book.close()


def test_factory_team_overrides_and_line_defaults_reach_reports(store, line_file, tmp_path):
    workbook = load_workbook(line_file)
    for row, value in ((2, "[원본공장] 포장1"), (3, "[원본공장] 포장1"), (4, "가공 [부산공장]")):
        workbook.active.cell(row, 4, value)
    workbook.save(line_file)
    workbook.close()
    source_hash = hashlib.sha256(line_file.read_bytes()).hexdigest()
    setup_line_names(store)
    store.save_equipment_names(
        {"LN01": "A#1", "LN02": "A#2"},
        source="line",
        organization={
            "line": {
                "LN01": {"factory": "직접공장", "team": "생산팀"},
                "LN02": {"team": "생산팀"},
            },
            "equipment": {"EQ01": {"factory": "설비코드 전용"}},
        },
    )
    normal = analyze_file(store, line_file)
    assert normal.selected.factory.tolist() == ["직접공장", "직접공장", "부산공장"]
    assert normal.selected.team.tolist() == ["생산팀"] * 3
    by_factory = analyze_file(store, line_file, AnalysisOptions(equipment_basis="factory"))
    assert set(by_factory.tables["equipment"].equipment) == {"직접공장", "부산공장"}
    by_team = analyze_file(store, line_file, AnalysisOptions(equipment_basis="team"))
    assert set(by_team.tables["equipment"].equipment) == {"직접공장 / 생산팀", "부산공장 / 생산팀"}
    assert by_team.metrics["selected_rows"] == 3 and by_team.metrics["total_minutes"] == 60
    assert by_team.selected.event_id.tolist() == normal.selected.event_id.tolist()
    path = export_report(by_team, tmp_path / "organization.xlsx")
    book = load_workbook(path, data_only=True)
    assert "별첨. 기준정보" not in book
    details = book[SHEETS["detail"]]
    factory_column = DETAIL_COLS.index("factory") + 2
    assert {details.cell(row, factory_column).value for row in range(7, 10)} == {
        "직접공장",
        "부산공장",
    }
    assert book["_report_metrics"]["A2"].value == 3
    assert book["_report_metrics"]["A3"].value == 60
    book.close()
    pypdf = pytest.importorskip("pypdf")
    pdf = export_pdf(by_team, tmp_path / "organization.pdf")
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(pdf).pages)
    assert "직접공장" in text and "부산공장" in text and "생산팀" in text
    assert "설비코드 전용" not in text
    assert hashlib.sha256(line_file.read_bytes()).hexdigest() == source_hash


def test_organization_names_matching_line_codes_are_not_projected(store, line_file, tmp_path):
    store.save_equipment_names(
        {"LN01": "A#1", "LN02": "A#2"},
        source="line",
        organization={
            "line": {
                "LN01": {"factory": "LN02", "team": "LN01"},
                "LN02": {"factory": "LN01", "team": "LN02"},
            }
        },
    )
    result = analyze_file(store, line_file, AnalysisOptions(equipment_basis="team"))
    projected = report_result(result)
    assert projected.selected.factory.tolist() == ["LN02", "LN02", "LN01"]
    assert projected.selected.team.tolist() == ["LN01", "LN01", "LN02"]
    assert set(projected.tables["equipment"].equipment) == {"LN02 / LN01", "LN01 / LN02"}
    path = export_report(result, tmp_path / "organization_codes.xlsx")
    book = load_workbook(path, data_only=True)
    assert {book["_issue_facts"].cell(row, 3).value for row in range(2, 5)} == {"LN02", "LN01"}
    assert {book["_issue_facts"].cell(row, 4).value for row in range(2, 5)} == {"LN01", "LN02"}
    book.close()


def test_unloaded_organization_labels_are_kept_exactly_in_settings_sheet(
    store, line_file, tmp_path
):
    store.save_equipment_names(
        {"LN01": "A#1", "LN02": "A#2"},
        source="line",
        grouping={"overrides": {"ORG_ONLY": "LN02"}},
        organization={"line": {"ORG_ONLY": {"factory": "LN01", "team": "LN02"}}},
    )
    result = analyze_file(store, line_file)
    path = export_report(result, tmp_path / "unloaded_organization.xlsx")
    book = load_workbook(path, data_only=True)
    assert "별첨. 기준정보" not in book
    assert result.config_snapshot["equipment_names"]["organization"]["line"]["ORG_ONLY"] == {
        "factory": "LN01",
        "team": "LN02",
    }
    book.close()


def test_factory_team_filters_apply_to_all_three_outputs(store, line_file, tmp_path):
    workbook = load_workbook(line_file)
    workbook.active["G2"] = "판정할 수 없는 기록 92837"
    workbook.active["G4"] = "판정할 수 없는 기록 92838"
    workbook.save(line_file)
    workbook.close()
    before = line_file.read_bytes()
    store.save_equipment_names(
        {"LN01": "A#1", "LN02": "B#1"},
        source="line",
        organization={
            "line": {
                "LN01": {"factory": "서울공장", "team": "포장팀"},
                "LN02": {"factory": "부산공장", "team": "포장팀"},
            }
        },
    )
    result = analyze_file(store, line_file, AnalysisOptions(factory="서울공장", team="포장팀"))
    assert result.metrics["selected_rows"] == 2 and result.metrics["total_minutes"] == 30
    assert result.metrics["excluded_rows"] == 1 and result.metrics["review_rows"] == 1
    draft = export_source_review(result, tmp_path / "before_confirmation.xlsx")
    marked = load_workbook(draft)
    assert marked["MES"]["A2"].fill.patternType == "solid"
    assert marked["MES"]["A4"].fill.patternType is None
    marked.close()
    result = finalize_classifications(
        store, line_file, AnalysisOptions(factory="서울공장", team="포장팀")
    )
    assert result.metrics["review_rows"] == 0
    files = export_bundle(result, tmp_path / "filtered.xlsx")
    book = load_workbook(files.excel, data_only=True)
    assert book["_report_metrics"]["A2"].value == 2
    assert book["_report_metrics"]["A3"].value == 30
    assert book[SHEETS["review"]]["B7"].value == 2
    assert "별첨. 기준정보" not in book
    book.close()
    assert files.source_review is None
    marked = load_workbook(files.excel)
    assert marked[SHEETS["source_review"]]["A2"].fill.patternType is None
    assert marked[SHEETS["source_review"]]["A4"].fill.patternType is None
    marked.close()
    pdf = export_pdf(result, tmp_path / "filtered-check.pdf")
    pypdf = pytest.importorskip("pypdf")
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(pdf).pages)
    assert "공장 필터" in text and "서울공장" in text and "팀 필터" in text and "포장팀" in text
    assert "부산공장" not in text
    assert line_file.read_bytes() == before


def test_unmatched_filter_names_are_exported_exactly_and_select_no_records(
    store, line_file, tmp_path
):
    setup_line_names(store)
    result = analyze_file(store, line_file, AnalysisOptions(factory="LN02", team="LN01"))
    assert result.selected.empty and result.metrics["selected_rows"] == 0
    path = export_report(result, tmp_path / "empty_filter.xlsx")
    book = load_workbook(path, data_only=True)
    assert book[SHEETS["review"]]["B7"].value == 0
    assert "별첨. 기준정보" not in book
    book.close()


def test_cli_factory_team_filters_keep_persisted_metadata(store, line_file, tmp_path, monkeypatch):
    store.save_equipment_names(
        {},
        source="line",
        organization={
            "line": {
                "LN01": {"factory": "Factory one", "team": "Team one"},
                "LN02": {"factory": "Factory two", "team": "Team one"},
            }
        },
    )
    before = (store.config_dir / "equipment_names.json").read_bytes()
    observed = {}

    def export(result, output, *, overwrite):
        observed["result"] = result
        return report_paths(output, result.loaded.path)

    monkeypatch.setattr(analyze_cli, "export_bundle", export)
    assert (
        analyze_cli.main(
            [
                str(line_file),
                "--output",
                str(tmp_path / "filtered_cli.xlsx"),
                "--data-dir",
                str(store.root),
                "--factory",
                "Factory one",
                "--team",
                "Team one",
            ]
        )
        == 0
    )
    assert observed["result"].metrics["selected_rows"] == 2
    assert observed["result"].options.factory == "Factory one"
    assert observed["result"].options.team == "Team one"
    assert (store.config_dir / "equipment_names.json").read_bytes() == before
