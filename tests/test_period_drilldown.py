"""The month/day view preserves filters, dates and duration semantics."""

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report


def test_monthly_daily_view_keeps_periods_and_exact_data(organization_result, tmp_path):
    source = organization_result.selected.copy(deep=True)
    path = export_report(organization_result, tmp_path / "period.xlsm")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        ws = values["04.월별 주요이슈"]
        assert "04.고장추이" not in values
        assert (ws["B7"].value, ws["F7"].value) == ("월별", "2026-01")
        assert [ws.cell(row, 1).value for row in range(23, 27)] == [
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
        ]
        assert sum(ws.cell(row, 2).value or 0 for row in range(23, 54)) == 6
        assert sum(ws.cell(row, 3).value or 0 for row in range(23, 54)) == 144
        assert ws["G23"].value in ("", None)
        assert ws["K24"].value in ("", None)
        assert len(formulas[ws.title].data_validations.dataValidation) == 7
        assert values["_period_daily"]["A32"].value == "2026-01-31"
        assert values["_period_daily"]["B2"].value == 1
        assert values["_period_daily"]["C2"].value == 10
        assert values["_period_daily"]["B4"].value == 1
        assert values["_period_daily"]["C4"].value == 100
        assert all(
            name in formulas.defined_names
            for name in (
                "_Period_Mode",
                "_Period_Month",
                "_Period_Back",
                "_Period_Rows",
                "_Period_ActiveCount",
            )
        )
        assert formulas.defined_names["_Period_Mode"].attr_text.endswith("!$B$7")
        assert formulas.defined_names["_Period_Month"].attr_text.endswith("!$F$7")
        assert formulas[ws.title]._charts[0].x_axis.title.tx.strRef.f == "'_period_state'!$B$9"
        assert "_issue_filter_3" in formulas["_period_daily"]["B2"].value
        assert "_period_daily" in formulas[ws.title]["B23"].value
        assert "DATE(YEAR(" in formulas["_period_daily"]["I2"].value
        assert organization_result.selected.equals(source)
    finally:
        values.close()
        formulas.close()


def test_week_and_year_units_replace_the_period_appendix(organization_result, tmp_path):
    """별첨. 기간별추이 is gone; its week/year units are filtered views of 04."""
    path = export_report(organization_result, tmp_path / "period_units.xlsm")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        assert "별첨. 기간별추이" not in values.sheetnames
        ws, source = values["04.월별 주요이슈"], formulas["04.월별 주요이슈"]
        mode = next(v for v in source.data_validations.dataValidation if str(v.sqref) == "B7")
        assert mode.formula1 == '"월별,주별,연도별,일별"'
        weekly, yearly = values["_period_weekly"], values["_period_yearly"]
        # Weeks start on Monday: 2026-01-01 (Thu) belongs to the week of 2025-12-29.
        assert weekly["A2"].value == "2025-12-29"
        assert (weekly["B2"].value, weekly["C2"].value) == (3, 130)
        assert weekly["A15"].value == "2026-03-30" and weekly["A16"].value is None
        assert (weekly["B15"].value, weekly["C15"].value) == (2, 14)
        # A week holding only an unrecorded duration keeps its time blank, not zero.
        march = next(row for row in range(2, 16) if weekly[f"A{row}"].value == "2026-03-09")
        assert weekly[f"B{march}"].value == 1 and weekly[f"C{march}"].value in ("", None)
        assert sum(weekly[f"B{row}"].value for row in range(2, 16)) == 6
        assert "+7" in formulas["_period_weekly"]["B2"].value
        assert "_issue_filter_3" in formulas["_period_weekly"]["B2"].value
        assert (yearly["A2"].value, yearly["B2"].value, yearly["C2"].value) == ("2026", 6, 144)
        # Data covers 2026-01-01..04-02, so the year is a partial period.
        assert yearly["K2"].value == "부분기간 가능" and yearly["G2"].value in ("", None)
        state = formulas["_period_state"]
        assert state["B4"].value.startswith("=CHOOSE('_period_state'!$B$5,4,14,1,")
        assert "MATCH(B3" in state["B5"].value
        display = source["B23"].value
        for helper in ("_period_monthly", "_period_weekly", "_period_yearly", "_period_daily"):
            assert helper in display
        # The default monthly view is unchanged.
        assert ws["A21"].value == "월" and ws["A23"].value == "2026-01"
        assert "주(시작일)" in source["A21"].value and "전주 대비" in source["G21"].value
        # Capacity covers the 14 weeks and 31 days.
        assert formulas.defined_names["_Period_Rows"].attr_text.endswith("$A$23:$A$53")
    finally:
        values.close()
        formulas.close()
