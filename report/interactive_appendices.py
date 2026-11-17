"""Compact, selectable line/module breakdowns instead of repeated static charts."""

from __future__ import annotations

import pandas as pd
from openpyxl.chart import DoughnutChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from core.issue_analysis import issue_summary
from report.issue_workbook import exact


def build_appendices(issues):
    for key, keys, title in (
        ("equipment", ["module", "part"], "라인별 고장 분포"),
        ("line", ["asset", "module", "part"], "상세설비별 고장 분포"),
    ):
        _breakdown(issues, key, keys, title)


def _breakdown(issues, key, keys, title):
    b = issues.b
    ws = b.new_sheet(key, title, span=12)
    for column in range(1, 13):
        ws.column_dimensions[get_column_letter(column)].width = 13
    ws.merge_cells("A5:L5")
    b.put(
        ws,
        5,
        1,
        "필터 셀 선택 → 검색 → 후보 선택. (전체)는 조건 해제. 동일 부품의 고장 현상은 합산합니다.",
        role="muted",
    )
    for field, address, label, span in (
        ("factory", "B6", "공장", 2),
        ("team", "F6", "팀", 2),
        ("asset", "B7", "라인", 4),
        ("module", "H7", "상세설비", 5),
    ):
        issues.selector(ws, address, field, label, span=span)
    b.put(ws, 6, 9, "분석 기준")
    ws.merge_cells("J6:L6")
    b.put(ws, 6, 10, "건수", role="input")
    validation = DataValidation(type="list", formula1='"건수,정지시간"', allow_blank=False)
    validation.showErrorMessage = True
    validation.error = "건수 또는 정지시간을 선택하세요."
    ws.add_data_validation(validation)
    validation.add(ws["J6"])
    filters = issues.filters(ws, {"factory": "B6", "team": "F6", "asset": "B7", "module": "H7"})
    args = issues.args(filters)
    total = issues.facts.minutes.sum(min_count=1)
    valid = int(issues.facts.minutes.count())
    for label, address, formula, cached, fmt in (
        ("고장이력(건)", "B9", issues.count_formula(args), len(issues.facts), "#,##0"),
        (
            "정지시간(분)",
            "E9",
            issues.time_formula(args, "B9", "H9"),
            total if valid else 0 if issues.facts.empty else "",
            "#,##0.0",
        ),
        ("시간 유효(건)", "H9", issues.valid_formula(args), valid, "#,##0"),
        (
            "분류 검토(건)",
            "K9",
            f"=SUMIFS({issues.fact_range('review_count')},{args})",
            int(issues.facts.review_count.sum()),
            "#,##0",
        ),
    ):
        target = ws[address]
        b.put(ws, 9, target.column - 1, label).alignment = Alignment(
            horizontal="center", vertical="center"
        )
        ws.merge_cells(
            start_row=9, end_row=9, start_column=target.column, end_column=target.column + 1
        )
        issues.formula(ws, address, formula, cached, fmt).alignment = Alignment(
            horizontal="right", vertical="center", indent=1
        )
    ws.merge_cells("A11:L11")
    b.put(ws, 11, 1, "차트: 상위 10개와 기타 · 하단 표: 전체 항목", role="title")
    label = "상세설비 / 세부부품" if key == "equipment" else "라인 / 상세설비 / 세부부품"
    issues.header(
        ws,
        12,
        [label, "", "", "", "", "", "건수", "정지(분)", "", "건수 비중", "시간 비중", "검토(건)"],
    )
    ws.merge_cells("A12:F12")
    ws.merge_cells("H12:I12")
    helper = b.wb.create_sheet("_breakdown_" + key)
    helper.append(["항목", "건수", "시간유효", "정지시간", "검토", "건수순위", "시간순위"])
    table = issue_summary(issues.facts, keys)
    items = table.to_dict("records")
    items.sort(key=lambda record: tuple(str(record[field]) for field in keys))
    end = max(2, 1 + len(items))
    orders = {
        "count": sorted(range(len(items)), key=lambda i: (-items[i]["count"], i)),
        "time": sorted(
            (i for i in range(len(items)) if items[i]["valid_count"]),
            key=lambda i: (-items[i]["total_minutes"], i),
        ),
    }
    ranks = {name: {i: rank for rank, i in enumerate(order, 1)} for name, order in orders.items()}
    for index, item in enumerate(items):
        row = index + 2
        b.put(helper, row, 1, " / ".join(str(item[field]) for field in keys), project=False)
        scoped = issues.args(
            filters, [(issues.fact_range(field), exact(item[field])) for field in keys]
        )
        issues.formula(helper, f"B{row}", issues.count_formula(scoped), item["count"], "#,##0")
        issues.formula(
            helper, f"C{row}", issues.valid_formula(scoped), item["valid_count"], "#,##0"
        )
        issues.formula(
            helper,
            f"D{row}",
            f'=IF(C{row}=0,"",SUMIFS({issues.fact_range("minutes")},{scoped}))',
            item["total_minutes"] if item["valid_count"] else "",
        )
        issues.formula(
            helper,
            f"E{row}",
            f"=SUMIFS({issues.fact_range('review_count')},{scoped})",
            item["review_count"],
            "#,##0",
        )
        issues.formula(
            helper,
            f"F{row}",
            f'=IF(B{row}=0,"",RANK(B{row},$B$2:$B${end},0)+COUNTIF($B$2:B{row},B{row})-1)',
            ranks["count"][index],
            "#,##0",
        )
        issues.formula(
            helper,
            f"G{row}",
            f'=IF(C{row}=0,"",RANK(D{row},$D$2:$D${end},0)+COUNTIFS($C$2:C{row},">0",$D$2:D{row},D{row})-1)',
            ranks["time"].get(index, ""),
            "#,##0",
        )
    helper.sheet_state = "hidden"
    helper_ref = "'" + helper.title + "'"
    for offset in range(max(10, len(items))):
        row = 13 + offset
        ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=6)
        ws.merge_cells(start_row=row, end_row=row, start_column=8, end_column=9)
        item = items[orders["count"][offset]] if offset < len(items) else None
        match = f'MATCH({offset + 1},IF($J$6="정지시간",{helper_ref}!$G$2:$G${end},{helper_ref}!$F$2:$F${end}),0)'
        for column, helper_column, value, fmt in (
            ("A", "A", " / ".join(str(item[field]) for field in keys) if item else "", "General"),
            ("G", "B", item["count"] if item else "", "#,##0"),
            (
                "H",
                "D",
                item["total_minutes"] if item is not None and item["valid_count"] else "",
                "#,##0.0",
            ),
            ("L", "E", item["review_count"] if item else "", "#,##0"),
        ):
            prefix = f'"{offset + 1}. "&' if column == "A" else ""
            if column == "A" and value:
                value = f"{offset + 1}. {value}"
            issues.formula(
                ws,
                f"{column}{row}",
                f'=IFERROR({prefix}INDEX({helper_ref}!${helper_column}$2:${helper_column}${end},{match}),"")',
                value,
                fmt,
            )
        ws[f"A{row}"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        for col, numerator, denominator in (("J", "G", "$B$9"), ("K", "H", "$E$9")):
            numerator_value = item["count" if col == "J" else "total_minutes"] if item else None
            denominator_value = len(issues.facts) if col == "J" else total
            cached = (
                numerator_value / denominator_value
                if pd.notna(numerator_value)
                and pd.notna(denominator_value)
                and denominator_value > 0
                else ""
            )
            issues.formula(
                ws,
                f"{col}{row}",
                f'=IF(OR(A{row}="",{denominator}=0,{denominator}="",{numerator}{row}=""),"",{numerator}{row}/{denominator})',
                cached,
                "0.0%",
            )
    # Only the chart groups the remainder; the table retains every individual item.
    top = [items[i] for i in orders["count"][:10]]
    remaining_count = len(issues.facts) - sum(item["count"] for item in top)
    issues.table_borders(ws, 12, 12 + max(10, len(items)), 1, 12)
    chart = DoughnutChart()
    chart.title, chart.holeSize = "순위별 구성비 (표의 순위 기준)", 55
    chart.legend.position = "b"
    chart.width, chart.height = 28, 9
    owner = "'" + ws.title.replace("'", "''") + "'"
    b.put(helper, 12, 8, "선택 기준", project=False)
    for row in range(13, 24):
        label = "기타" if row == 23 else f"{row - 12}위"
        has_item = row == 23 or bool(b.cache.values.get((ws.title, f"A{row}"), ""))
        issues.formula(
            helper,
            f"I{row}",
            f'="{label}"' if row == 23 else f'=IF({owner}!A{row}="","","{label}")',
            label if has_item else "",
            "General",
        )
        issues.formula(
            helper,
            f"H{row}",
            (
                f'=IF({owner}!$J$6="정지시간",IF({owner}!$E$9="","",{owner}!$E$9-SUM({owner}!H13:H22)),{owner}!$B$9-SUM({owner}!G13:G22))'
                if row == 23
                else f'=IF({owner}!$J$6="정지시간",{owner}!H{row},{owner}!G{row})'
            ),
            remaining_count if row == 23 else b.cache.values.get((ws.title, f"G{row}"), ""),
        )
    chart.add_data(Reference(helper, min_col=8, min_row=12, max_row=23), titles_from_data=True)
    chart.set_categories(Reference(helper, min_col=9, min_row=13, max_row=23))
    chart.visible_cells_only = False
    chart.dataLabels = DataLabelList(
        showPercent=False, showVal=False, showCatName=False, showSerName=False
    )
    palette = [
        "166A70",
        "AD6817",
        "65717D",
        "467E9B",
        "78995E",
        "9A7D65",
        "7E708C",
        "4C8E83",
        "A4935C",
        "827168",
        "D6DADF",
    ]
    chart.series[0].data_points = [DataPoint(idx=i, spPr=None) for i in range(11)]
    for point, color in zip(chart.series[0].data_points, palette):
        point.graphicalProperties.solidFill = color
    ws.add_chart(chart, "A26")
    ws.freeze_panes = "G13"
    ws.print_area = f"A1:L{max(42, 12 + len(items))}"
    ws.page_setup.orientation = "landscape"
