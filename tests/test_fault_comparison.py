from dataclasses import replace
from zipfile import ZipFile

from openpyxl import load_workbook
from test_report_issue_views import organization_result as organization_result

from core.analyzer import analyze
from report.excel_report import export_report
from report.fault_comparison import CONTROLS, FILTER_AREAS, comparison_facts, line_catalog


def test_saved_equipment_group_wins_and_line_identity_is_preserved(organization_result):
    records = organization_result.selected.copy(deep=True)
    records["equipment_group"] = ["같은 설비군"] * len(records)
    facts = comparison_facts(replace(organization_result, selected=records))
    assert set(facts.family) == {"같은 설비군"}
    assert set(facts.asset) == {"실제설비A", "실제설비B"}
    assert facts.record_id.is_unique and len(facts) == 6


def test_fault_comparison_replaces_team_sheet_and_keeps_filtered_population(
    organization_result, tmp_path
):
    path = export_report(organization_result, tmp_path / "fault.xlsm")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        assert values.sheetnames[:4] == [
            "01.종합현황",
            "02.팀별 주요이슈",
            "03.월별 주요이슈",
            "04.고장비교",
        ]
        assert "04.팀간 비교" not in values
        assert [s.title for s in formulas if s.sheet_view.tabSelected] == ["01.종합현황"]
        ws = values["04.고장비교"]
        assert ws["A7"].value == "기준 부서" and ws["A9"].value == "비교 부서"
        assert ws["A8"].value == "VS"
        assert "mode" not in CONTROLS and "_Fault_List_mode" not in formulas.defined_names
        assert ws["D25"].value == "설비군" and ws["C25"].value == "라인"
        assert [ws.cell(26, c).value for c in (1, 2, 5, 6, 8, 9)] == ["공장A", "팀1", 4, 44, 0, 0]
        assert [ws.cell(27, c).value for c in (1, 2, 5, 6, 8, 9)] == [
            "공장B",
            "팀2",
            2,
            100,
            -2,
            56,
        ]
        assert len(formulas[ws.title].data_validations.dataValidation) == 3
        assert ws["B7"].value == "[공장A] 팀1" and ws["B9"].value == "(전체)"
        assert ws["E7"].value == "(전체)" and ws["I7"].value == "(전체)"
        # Filter captions occupy one column like 02/03; only the value spans columns.
        assert {
            str(area) for area in formulas[ws.title].merged_cells.ranges if 7 <= area.min_row <= 9
        } == {"B7:C7", "E7:G7", "I7:J7", "A8:J8", "B9:C9", "E9:G9", "I9:J9"}
        assert [ws[f"{c}7"].value for c in "ADH"] == ["기준 부서", "기준 라인", "기준 상세설비"]
        assert all(ws.row_dimensions[r].height == 21 for r in (7, 8, 9, 25, 26, 27))
        assert formulas[ws.title]["I7"].font.color.rgb == "00808080"
        assert formulas[ws.title]["E9"].font.color.rgb == "00808080"
        assert formulas[ws.title]["I9"].font.color.rgb == "00808080"
        assert {str(v.sqref) for v in formulas[ws.title].data_validations.dataValidation} == {
            "B7",
            "E7",
            "B9",
        }
        for area in [
            area for caption, edit, _ in FILTER_AREAS.values() for area in (caption, edit)
        ]:
            from openpyxl.utils.cell import range_boundaries

            left, top, right, bottom = range_boundaries(area)
            assert formulas[ws.title].cell(top, left).border.left.style == "thin", area
            assert formulas[ws.title].cell(bottom, right).border.right.style == "thin", area
            assert formulas[ws.title].cell(top, left).border.top.style == "thin", area
            assert formulas[ws.title].cell(bottom, right).border.bottom.style == "thin", area
        assert all(s.freeze_panes is None and s.sheet_view.pane is None for s in formulas)
        assert all(x.pane is None for s in formulas for x in s.sheet_view.selection)
        assert ws.auto_filter.ref.startswith("A25:L")
        assert ws["L25"].value == "상세설비" and ws["L26"].value == "(전체)"
        assert "'04.고장비교'!$B$9" in formulas["_fault_rows"]["L3"].value
        assert "'04.고장비교'!$E$9" in formulas["_fault_rows"]["L7"].value
        rows = list(formulas["_fault_rows"].iter_rows(min_row=2, values_only=True))
        assert {r[3] for r in rows if r[0] == "라인"} == {"실제설비A", "실제설비B"}
        assert {r[0] for r in rows} == {"부서", "라인", "상세설비"}
        assert ws["A1"].value == "고장비교"
        assert ws["C26"].value == "전체 라인"
        for name in ("_Fault_CountLabels", "_Fault_TimeLabels", "_Fault_TableRows"):
            assert name in formulas.defined_names
        for chart in formulas[ws.title]._charts:
            assert chart.x_axis.scaling.orientation == "maxMin"
            assert "_Fault_" in chart.series[0].cat.strRef.f
        with ZipFile(path) as z:
            assert b"_comparison_rank" not in b"".join(
                z.read(n) for n in z.namelist() if n.startswith("xl/charts/") and n.endswith(".xml")
            )
    finally:
        values.close()
        formulas.close()


def test_line_choices_preserve_identity_when_names_are_shared(organization_result):
    facts = comparison_facts(organization_result)
    facts.loc[:, "asset"] = "동일 라인명"
    catalog = line_catalog(facts)
    assert len(catalog) == 2
    assert catalog.choice.is_unique
    assert set(catalog.choice) == {"[공장A] 팀1 / 동일 라인명", "[공장B] 팀2 / 동일 라인명"}


def test_unavailable_duration_chart_has_a_stable_label_and_omits_the_bar(
    organization_result, tmp_path
):
    records = organization_result.selected.copy(deep=True)
    records["minutes"] = float("nan")
    result = analyze(
        organization_result.loaded,
        records,
        organization_result.config_snapshot,
        organization_result.options,
    )
    path = export_report(result, tmp_path / "missing_time.xlsm")
    values, formulas = load_workbook(path, data_only=True), load_workbook(path)
    try:
        assert values["_fault_chart_rank"]["I2"].value == "시간 미기재"
        assert "NA()" in formulas["_fault_chart_rank"]["J2"].value
        assert values["_fault_chart_rank"]["J2"].value is None
        assert values["04.고장비교"]["F26"].value is None
    finally:
        values.close()
        formulas.close()
