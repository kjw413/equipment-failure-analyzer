"""Line/part reporting aggregates unreliable symptom wording without losing facts."""

from copy import deepcopy

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from core.fault_components import component_payload
from report.excel_report import DETAIL_COLS, SHEETS, export_report
from report.issue_workbook import report_issue_facts


def test_different_symptoms_share_one_reporting_case(organization_result):
    records = organization_result.selected.copy(deep=True)
    before = deepcopy(organization_result.selected)
    index = records.index[1]
    category = {
        "major": "유체·배관",
        "detail_equipment": "펌프",
        "middle": "씰",
        "minor": "마모",
        "schema": records.loc[index, "classification_schema"],
    }
    for field, value in component_payload([category], "single").items():
        records.at[index, field] = value
    records.at[index, "minor"] = "마모"
    facts = report_issue_facts(records)
    seals = facts.loc[facts["case"].eq("펌프 / 씰")]
    assert len(seals) == 4 and seals.minutes.sum() == 130
    assert set(seals.symptom) == {"마모", "누설"}
    assert "펌프 / 세부 부품 미기재" in set(facts["case"])
    assert organization_result.selected.equals(before)


def test_selectable_appendices_and_part_controls_preserve_original_rows(
    organization_result, tmp_path
):
    source = organization_result.loaded.path.read_bytes()
    path = export_report(organization_result, tmp_path / "line_parts.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        visible = [sheet.title for sheet in values if sheet.sheet_state == "visible"]
        assert "별첨. 라인별분석" in visible and "별첨. 상세설비별분석" in visible
        assert not any(
            word in name for name in visible for word in ("유형별분석", "부품별분석", "원본데이터")
        )
        assert values["_source_quality"].sheet_state == "hidden"
        assert values["_source_quality"].max_column == 2
        assert values["03.팀간 비교"]["D5"].value == "라인"
        assert values["04.고장추이"]["I6"].value == "세부부품"
        validation = next(
            v
            for v in formulas["04.고장추이"].data_validations.dataValidation
            if str(v.sqref) == "J6"
        )
        assert validation.formula1 == "=_Issue_part"
        assert validation.showErrorMessage and validation.showInputMessage
        assert len(formulas["03.팀간 비교"].data_validations.dataValidation) == 3
        for key in ("equipment", "line"):
            sheet = values[SHEETS[key]]
            # Common appendix layout adds one column; B9 -> C9, E9 -> F9.
            assert sheet["C9"].value == 6 and sheet["F9"].value == 144
            assert sum(sheet.cell(row, 8).value or 0 for row in range(33, sheet.max_row + 1)) == 6
            assert sum(sheet.cell(row, 9).value or 0 for row in range(33, sheet.max_row + 1)) == 144
            assert len(sheet._charts) == 1 and not sheet._images
            assert [chart.anchor._from.col for chart in sheet._charts] == [1]
            assert sheet._charts[0].anchor._from.row + 1 < 32
            assert formulas[SHEETS[key]]["B33"].data_type == "f"
        assert DETAIL_COLS.index("normalized") < DETAIL_COLS.index("raw_description")
        detail = values[SHEETS["detail"]]
        assert detail.cell(6, DETAIL_COLS.index("normalized") + 2).value == "고장내용(표준화 후)"
        assert {detail.cell(row, 2).value for row in range(7, 13)} == set(
            organization_result.selected.record_id
        )
        filter_formula = formulas["_issue_filter_1"]["A2"].value
        assert "SEARCH(" not in filter_formula and "COUNTIF(_Issue_asset" not in filter_formula
        assert "'_issue_facts'!$E2='02.팀별 주요이슈'!$G$5" in filter_formula
        for name, cells in (
            ("02.팀별 주요이슈", ("D28", "E28", "F28")),
            ("03.팀간 비교", ("C23", "D23", "E23")),
            ("04.고장추이", ("B23", "C23", "D23")),
        ):
            for cell in cells:
                target = formulas[name][cell]
                assert "[Red]" not in target.number_format and "[Blue]" not in target.number_format
                if target.font.color.type == "rgb":
                    assert not target.font.color.rgb.endswith(("FF0000", "0000FF"))
        assert "[Red]" in formulas["03.팀간 비교"]["F23"].number_format
        assert "[Blue]" in formulas["04.고장추이"]["G25"].number_format
        for sheet in formulas:
            for row in sheet:
                for cell in row:
                    if cell.data_type == "f":
                        assert "#REF!" not in cell.value
    finally:
        values.close()
        formulas.close()
    assert organization_result.loaded.path.read_bytes() == source
