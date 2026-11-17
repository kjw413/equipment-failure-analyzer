from datetime import date
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table
from PIL import Image as PillowImage

from report.cache import FormulaCache
from report.workbook_layout import FONT_NAME, apply_workbook_layout


def workbook_fixture():
    wb = Workbook()
    ws = wb.active
    ws.title = "공장 팀's 분석"
    ws.merge_cells("A1:F2")
    ws["A1"] = "고장 분석"
    ws.merge_cells("A3:F3")
    ws["A3"] = "2026-01-01 ~ 2026-11-11 | 고장 | 라인"
    ws.merge_cells("A4:F4")
    ws["A4"] = "source.xlsx | 기록"
    ws.merge_cells("A5:F5")
    ws["A5"] = "선택칸을 변경하세요."
    ws.append(["구분", "건수", "시간", "전월 대비", "비고", "상세"])
    ws.append(["(전체)", 3, 10, -0.5, "=수기 입력", None])
    ws["E7"].data_type = "s"
    ws["A6"].fill = PatternFill("solid", fgColor="303942")
    ws["A6"].font = Font(color="FFFFFF", size=10, bold=True)
    ws["A7"].font = Font(color="2155A0", size=10)
    ws["B7"].font = Font(color="237245", size=10)
    ws["C7"].fill = PatternFill("solid", fgColor="FFF2CC")
    ws["D7"].number_format = "0.0%"
    ws["B7"].border = Border(
        left=Side(style="thin"), right=Side(style="thin"), bottom=Side(style="thin")
    )
    cache = FormulaCache()
    cache.set(ws, "F7", '=SUM($B$7:B7)+COUNTIF(A7,"A1")+COUNTIF(A7,"=A*~?")', 6)
    ws["A8"] = "다음 시트"
    ws["A8"].hyperlink = "#'01_종합현황'!A1"
    ws.column_dimensions["A"].width = 19
    ws.column_dimensions["D"].hidden = True
    ws.column_dimensions.group("E", "F", hidden=True)
    ws.row_dimensions[7].height = 48
    ws.freeze_panes = "B7"
    ws.print_area = "A1:F20"
    ws.print_title_rows = "1:6"
    ws.print_title_cols = "A:B"
    ws.auto_filter.ref = "A6:F7"
    table = Table(displayName="Evidence", ref="A6:F7")
    ws.add_table(table)
    dv = DataValidation(type="list", formula1="'01_종합현황'!$A$6:$A$7")
    dv.add("A7")
    dv.add("B7:C7")
    ws.add_data_validation(dv)
    quoted = DataValidation(type="list", formula1='"A1,B2"')
    quoted.add("D7")
    ws.add_data_validation(quoted)
    ws.conditional_formatting.add("B7:C7", FormulaRule(formula=["$B7>0", 'A7="A1"']))
    chart = BarChart()
    chart.title = "발생 건수"
    chart.add_data(Reference(ws, min_col=2, min_row=6, max_row=7), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=7, max_row=7))
    ws.add_chart(chart, "A10")
    png = BytesIO()
    PillowImage.new("RGB", (10, 10), "white").save(png, format="PNG")
    png.seek(0)
    ws.add_image(Image(png), "D10")
    wb.defined_names.add(DefinedName("VisibleRange", attr_text="'공장 팀''s 분석'!$A$7:$B$7"))
    ws.defined_names.add(DefinedName("LocalRange", attr_text="$A$7:$B$7"))
    hidden = wb.create_sheet("_facts")
    hidden.sheet_state = "hidden"
    cache.set(hidden, "A1", "='공장 팀''s 분석'!$A$7", "(전체)")
    hidden["B1"] = "=SUM(A1,'공장 팀''s 분석'!B7,\"A1\")"
    wb.defined_names.add(DefinedName("Facts", attr_text="'_facts'!$A$1:$B$1"))
    summary = wb.create_sheet("01_종합현황")
    summary.merge_cells("A1:F2")
    summary["A1"] = "종합 현황"
    summary["A3"] = "분석 기간"
    summary["A6"] = "라인"
    summary["A7"] = "[남양주]ARCIL #1"
    summary["B7"] = "='공장 팀''s 분석'!A7"
    return wb, ws, hidden, cache


def test_coordinates_formulas_and_hidden_facts_move_together():
    wb, ws, hidden, cache = workbook_fixture()
    apply_workbook_layout(wb, cache, created_at=date(2026, 11, 16))
    assert ws["A7"].value is None
    assert ws["B7"].value == "(전체)"
    assert ws["G7"].value == '=SUM($C$7:C7)+COUNTIF(B7,"A1")+COUNTIF(B7,"=A*~?")'
    assert hidden["A1"].value == "='공장 팀''s 분석'!$B$7"
    assert hidden["B1"].value == "=SUM(A1,'공장 팀''s 분석'!C7,\"A1\")"
    assert (ws.title, "G7") in cache.values
    assert cache.values[("_facts", "A1")] == "(전체)"
    assert wb.defined_names["VisibleRange"].attr_text == "'공장 팀''s 분석'!$B$7:$C$7"
    assert wb.defined_names["Facts"].attr_text == "'_facts'!$A$1:$B$1"
    assert ws.defined_names["LocalRange"].attr_text == "$B$7:$C$7"
    assert ws["B8"].hyperlink.target == "#'01_종합현황'!B2"
    assert ws["B8"].hyperlink.ref == "B8"


def test_selectors_tables_drawings_and_print_references_move():
    wb, ws, _, cache = workbook_fixture()
    apply_workbook_layout(wb, cache, created_at=date(2026, 11, 16))
    dv, quoted = ws.data_validations.dataValidation
    assert set(str(value) for value in dv.sqref.ranges) == {"B7", "C7:D7"}
    assert dv.formula1 == "'01_종합현황'!$B$6:$B$7"
    assert quoted.formula1 == '"A1,B2"'
    cf, rules = next(iter(ws.conditional_formatting._cf_rules.items()))
    assert str(cf.sqref) == "C7:D7"
    assert rules[0].formula == ["$C7>0", 'B7="A1"']
    assert ws.tables["Evidence"].ref == "B6:G7"
    assert ws.auto_filter.ref == "B6:G7"
    assert ws.freeze_panes == "C7"
    assert str(ws.print_area) == "'공장 팀''s 분석'!$B$1:$G$20"
    assert ws.print_title_cols == "$B:$C"
    assert ws.print_title_rows == "$1:$6"
    assert ws._charts[0].anchor == "B10"
    assert ws._images[0].anchor == "E10"
    series = ws._charts[0].series[0]
    assert series.val.numRef.f == "'공장 팀''s 분석'!$C$7"
    assert series.cat.numRef.f == "'공장 팀''s 분석'!$B$7"
    assert series.tx.strRef.f == "'공장 팀''s 분석'!C6"
    assert ws.column_dimensions["B"].width == 19
    assert ws.column_dimensions["E"].hidden
    assert ws.column_dimensions["F"].min == 6
    assert ws.column_dimensions["F"].max == 7


def test_house_style_metadata_and_original_highlights_are_preserved():
    wb, ws, _, cache = workbook_fixture()
    apply_workbook_layout(wb, cache, created_at=date(2026, 11, 16))
    assert ws["B2"].value == "고장 분석"
    assert ws["B2"].font.name == FONT_NAME
    assert ws["B2"].font.sz == 16
    assert ws["B3"].value == "2026.11.16 확인 필요 작성"
    assert ws["B3"].alignment.horizontal == "right"
    assert ws["B4"].value == "2026-01-01 ~ 2026-11-11 | 고장 | 라인"
    assert ws["B5"].value == "선택칸을 변경하세요."
    assert ws["B6"].fill.fgColor.rgb[-6:] == "F2F2F2"
    assert ws["B6"].font.color.rgb[-6:] == "222222"
    assert ws["B7"].font.color.rgb[-6:] == "2155A0"
    assert ws["C7"].font.color.rgb[-6:] == "222222"
    assert ws["D7"].fill.fgColor.rgb[-6:] == "FFF2CC"
    assert ws["B7"].border.left.style is None
    assert ws["G7"].border.right.style is None
    assert ws["C7"].border.left.style == "thin"
    assert ws["C7"].border.right.style == "thin"
    assert ws["C7"].border.bottom.style == "thin"
    assert ws["B7"].alignment.horizontal == "center"
    assert ws["C7"].alignment.horizontal == "right"
    assert ws.row_dimensions[7].height == 22
    assert ws.row_dimensions[1].height == 16.5
    assert ws.sheet_format.defaultRowHeight == 16.5
    assert ws.column_dimensions["A"].width == 1
    assert "▲" in ws["E7"].number_format
    assert "[Red]" in ws["E7"].number_format
    assert "[Blue]" in ws["E7"].number_format
    assert wb["01_종합현황"].page_setup.fitToHeight == 1
    assert ws.page_setup.fitToHeight == 0
    assert ws._charts[0].x_axis.txPr.p[0].pPr.defRPr.latin.typeface == FONT_NAME


def test_saved_workbook_and_formula_caches_round_trip(tmp_path):
    wb, ws, _, cache = workbook_fixture()
    apply_workbook_layout(wb, cache, created_at=date(2026, 11, 16))
    apply_workbook_layout(wb, cache, created_at=date(2026, 11, 17))
    assert ws["B3"].value == "2026.11.16 확인 필요 작성"
    target = tmp_path / "layout.xlsx"
    wb.save(target)
    cache.patch(target)
    formulas = load_workbook(target, data_only=False)
    values = load_workbook(target, data_only=True)
    assert formulas[ws.title]["G7"].value.startswith("=SUM($C$7:C7)")
    assert values[ws.title]["G7"].value == 6
    assert values["_facts"]["A1"].value == "(전체)"
    assert formulas[ws.title]._charts[0].anchor._from.col == 1
    assert formulas[ws.title]._images[0].anchor._from.col == 4


def test_whole_ranges_literals_external_links_and_two_cell_anchor():
    wb, ws, _, cache = workbook_fixture()
    ws["A9"] = '=SUM(A:A,$B:$C,1:2)+COUNTIF(A7,"A1 ""quoted""")'
    ws["B9"] = "='[another.xlsx]Sheet1'!A1"
    ws["C9"] = "=SUM('01_종합현황:공장 팀''s 분석'!A1)"
    ws._charts[0].anchor = TwoCellAnchor(
        _from=AnchorMarker(col=1, row=10), to=AnchorMarker(col=5, row=20)
    )
    apply_workbook_layout(wb, cache, created_at=date(2026, 11, 16))
    assert ws["B9"].value == '=SUM(B:B,$C:$D,1:2)+COUNTIF(B7,"A1 ""quoted""")'
    assert ws["C9"].value == "='[another.xlsx]Sheet1'!A1"
    assert ws["D9"].value == "=SUM('01_종합현황:공장 팀''s 분석'!A1)"
    assert ws._charts[0].anchor._from.col == 2
    assert ws._charts[0].anchor.to.col == 6
