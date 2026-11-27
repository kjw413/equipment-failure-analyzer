"""Line and detailed-equipment reporting aggregate retained facts."""

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
        "middle": "메카니칼씰",
        "minor": "마모",
        "schema": records.loc[index, "classification_schema"],
    }
    for field, value in component_payload([category], "single").items():
        records.at[index, field] = value
    records.at[index, "minor"] = "마모"
    records.at[index, "middle"] = category["middle"]
    facts = report_issue_facts(records)
    pumps = facts.loc[facts["case"].eq("펌프")]
    assert len(pumps) == 5 and pumps.minutes.sum() == 135
    assert set(pumps.symptom) == {"마모", "누설", "현상 미기재"}
    assert "part" not in facts
    assert organization_result.selected.equals(before)


def test_selectable_appendices_and_equipment_controls_preserve_original_rows(
    organization_result, tmp_path
):
    source = organization_result.loaded.path.read_bytes()
    path = export_report(organization_result, tmp_path / "line_parts.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        visible = [sheet.title for sheet in values if sheet.sheet_state == "visible"]
        assert "별첨. 동일 상세설비 비교" not in visible
        assert "별첨. 원본 검토표시" in visible
        assert "별첨. 라인별분석" not in visible and "별첨. 상세설비별분석" not in visible
        assert not any(
            word in name for name in visible for word in ("유형별분석", "부품별분석", "원본데이터")
        )
        assert "_source_quality" not in values
        assert values["04.고장비교"]["D7"].value == "기준 라인"
        assert values["03.월별 주요이슈"]["I8"].value is None
        validation = next(
            v
            for v in formulas["03.월별 주요이슈"].data_validations.dataValidation
            if str(v.sqref) == "J7"
        )
        assert validation.formula1 == "=_Issue_module"
        assert validation.showErrorMessage and validation.showInputMessage
        assert len(formulas["04.고장비교"].data_validations.dataValidation) == 6
        sheet = values["04.고장비교"]
        assert sum(sheet.cell(row, 5).value or 0 for row in range(26, sheet.max_row + 1)) == 6
        assert sum(sheet.cell(row, 6).value or 0 for row in range(26, sheet.max_row + 1)) == 144
        assert len(sheet._charts) == 2 and not sheet._images
        assert DETAIL_COLS.index("normalized") < DETAIL_COLS.index("raw_description")
        detail = values[SHEETS["detail"]]
        assert {"middle", "part_group", "part_count"}.isdisjoint(DETAIL_COLS)
        assert all("부품" not in str(cell.value) for cell in detail[6])
        assert detail.cell(6, DETAIL_COLS.index("normalized") + 2).value == "고장내용(표준화 후)"
        record_column = DETAIL_COLS.index("record_id") + 2
        assert {detail.cell(row, record_column).value for row in range(7, 13)} == set(
            organization_result.selected.record_id
        )
        filter_formula = formulas["_issue_filter_1"]["A2"].value
        assert "SEARCH(" not in filter_formula and "COUNTIF(_Issue_asset" not in filter_formula
        assert "'_issue_facts'!$E2='02.팀별 주요이슈'!$G$7" in filter_formula
        for name, cells in (
            ("02.팀별 주요이슈", ("D28", "E28", "F28")),
            ("04.고장비교", ("E26", "F26", "G26")),
            ("03.월별 주요이슈", ("B25", "C25", "D25")),
        ):
            for cell in cells:
                target = formulas[name][cell]
                assert "[Red]" not in target.number_format and "[Blue]" not in target.number_format
                if target.font.color.type == "rgb":
                    assert not target.font.color.rgb.endswith(("FF0000", "0000FF"))
        assert "[Red]" in formulas["04.고장비교"]["H26"].number_format
        assert "[Blue]" in formulas["03.월별 주요이슈"]["G26"].number_format
        for sheet in formulas:
            for row in sheet:
                for cell in row:
                    if cell.data_type == "f":
                        assert "#REF!" not in cell.value
    finally:
        values.close()
        formulas.close()
    assert organization_result.loaded.path.read_bytes() == source
