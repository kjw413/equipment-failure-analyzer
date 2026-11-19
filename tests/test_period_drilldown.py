"""The month/day view preserves filters, dates and duration semantics."""

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from report.excel_report import export_report


def test_monthly_daily_view_keeps_periods_and_exact_data(organization_result, tmp_path):
    source = organization_result.selected.copy(deep=True)
    path = export_report(organization_result, tmp_path / "period.xlsm")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        ws = values["03.월별 주요이슈"]
        assert "04.고장추이" not in values
        assert (ws["B7"].value, ws["D7"].value) == ("월별", "2026-01")
        assert [ws.cell(row, 1).value for row in range(24, 28)] == [
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
        ]
        assert sum(ws.cell(row, 2).value or 0 for row in range(24, 55)) == 6
        assert sum(ws.cell(row, 3).value or 0 for row in range(24, 55)) == 144
        assert ws["G24"].value in ("", None)
        assert ws["K25"].value in ("", None)
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
        assert formulas.defined_names["_Period_Month"].attr_text.endswith("!$D$7")
        assert formulas[ws.title]._charts[0].x_axis.title.tx.strRef.f == "'_period_state'!$B$9"
        assert "_issue_filter_3" in formulas["_period_daily"]["B2"].value
        assert "_period_daily" in formulas[ws.title]["B24"].value
        assert "DATE(YEAR(" in formulas["_period_daily"]["I2"].value
        assert organization_result.selected.equals(source)
    finally:
        values.close()
        formulas.close()


def test_month_day_view_replaces_the_period_appendix(organization_result, tmp_path):
    """별첨. 기간별추이 is gone; 04 keeps only the month view and its day drill."""
    path = export_report(organization_result, tmp_path / "period_units.xlsm")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        assert "별첨. 기간별추이" not in values.sheetnames
        assert "_period_weekly" not in values.sheetnames
        assert "_period_yearly" not in values.sheetnames
        source = formulas["03.월별 주요이슈"]
        mode = next(v for v in source.data_validations.dataValidation if str(v.sqref) == "B7")
        assert mode.formula1 == '"월별,일별"'
        assert values["03.월별 주요이슈"]["I7"].value == "월별로 돌아가기"
        assert "더블클릭" in values["03.월별 주요이슈"]["A3"].value
        assert formulas["_period_state"]["B4"].value.startswith("=IF('_period_state'!$B$3=\"일별\"")
    finally:
        values.close()
        formulas.close()
