"""Drilldown keeps classification facts intact and scopes every selector by parents."""

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report


def test_drilldown_starts_with_lines_and_scoped_lists(organization_result, tmp_path):
    before = organization_result.selected.copy(deep=True)
    path = export_report(organization_result, tmp_path / "drill.xlsx")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        main = values["02.팀별 주요이슈"]
        assert main["B27"].value == main["H27"].value == "라인"
        assert main["B28"].value == "실제설비A" and main["D28"].value == 4
        assert main["H28"].value == "실제설비B" and main["K28"].value == 100
        assert main["K7"].value == "(전체)"
        assert main["J8"].value is None and main["K8"].value is None
        assert values["_drill_state"]["B2"].value == "asset"
        metadata = list(values["_report_controls"].iter_rows(min_row=2, values_only=True))
        rows = [r for r in metadata if r[0] == main.title]
        assert [(r[1], r[2]) for r in rows] == [
            ("factory", "B7"),
            ("team", "D7"),
            ("asset", "G7"),
            ("module", "K7"),
        ]
        for field in ("factory", "team", "asset", "module"):
            assert "COUNTIF(" in formulas[main.title].defined_names["_Issue_" + field].attr_text
        assert "_Issue_part" not in formulas.defined_names
        assert "_Issue_part" not in formulas[main.title].defined_names
        assert "part" not in [cell.value for cell in values["_issue_facts"][1]]
        # The line eligibility formula uses the selected factory AND team.
        eligible = formulas["_selector_flags"]["C2"].value
        assert "'02.팀별 주요이슈'!$B$7" in eligible
        assert "'02.팀별 주요이슈'!$D$7" in eligible
        assert "_xlfn.AGGREGATE" in formulas["_selector_lists"]["C2"].value
        assert set(
            r[0].value for r in formulas["_issue_rank"].iter_rows(min_row=2, min_col=8, max_col=8)
        ) == {"asset", "module"}
        for row in (28, 29):
            # Values are looked up by the active stage's rank, not a shared label.
            assert "MATCH(" in formulas[main.title][f"D{row}"].value
            assert "!$F$2" in formulas[main.title][f"D{row}"].value
        assert organization_result.selected.equals(before)
    finally:
        values.close()
        formulas.close()
