"""별첨. 동일 상세설비 비교: one detailed equipment compared across lines.

02.팀별 주요이슈 answers "where should my team improve first" (organization →
line → module → part). This appendix answers the complementary question "the
same module fails on which lines?". The module is chosen first; factory/team only
narrow the compared lines. Two ranked bar charts name the real lines, and the
table lists every line with shares against the whole selected scope (no "기타").
"""

from __future__ import annotations

import pandas as pd
from openpyxl.chart import BarChart
from openpyxl.chart.data_source import (
    AxDataSource,
    NumData,
    NumDataSource,
    NumRef,
    NumVal,
    StrData,
    StrRef,
    StrVal,
)
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import Series, SeriesLabel
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from core.issue_analysis import ALL, MISSING, select_issues
from report.issue_workbook import exact, ref

SHEET = "별첨. 동일 상세설비 비교"
HELPER = "_module_compare"
KEY = "module_compare"
# Selector order drives cascading lists and resets: the module comes first.
FIELD_ORDER = ("module", "part", "factory", "team")
CHART_TOP = 10
TABLE_HEADER = 28
FIRST_ROW = TABLE_HEADER + 1
GROUP = ["factory", "team", "asset"]


def default_module(facts: pd.DataFrame) -> str:
    """Open on the most frequent identified module that occurs on several lines."""
    known = facts.loc[facts["module"].ne(MISSING["module"])]
    if known.empty:
        return ALL
    stats = known.groupby("module").agg(count=("record_id", "size"), lines=("asset", "nunique"))
    shared = stats.loc[stats["lines"].gt(1)]
    pool = shared if len(shared) else stats
    return str(
        pool.reset_index()
        .sort_values(["count", "module"], ascending=[False, True])
        .iloc[0]["module"]
    )


def _groups(facts):
    """Every factory/team/line in the analysis; labels stay unique for chart axes."""
    groups = facts[GROUP].drop_duplicates().sort_values(GROUP).to_dict("records")
    duplicated = pd.Series([g["asset"] for g in groups]).duplicated(keep=False).tolist()
    for group, repeated in zip(groups, duplicated, strict=True):
        group["label"] = f"{group['asset']} ({group['team']})" if repeated else group["asset"]
    return groups


def _stats(scoped, groups):
    for group in groups:
        rows = scoped
        for field in GROUP:
            rows = rows.loc[rows[field].eq(group[field])]
        minutes = rows["minutes"]
        valid = int(minutes.count())
        group.update(
            count=len(rows),
            valid=valid,
            minutes=float(minutes.sum()) if valid else "",
            review=int(rows["review_count"].sum()),
            mean=float(minutes.sum()) / valid if valid else "",
        )
    present = [i for i, g in enumerate(groups) if g["count"]]
    count_order = sorted(present, key=lambda i: (-groups[i]["count"], i))
    timed = [i for i in present if groups[i]["valid"]]
    time_order = sorted(timed, key=lambda i: (-groups[i]["minutes"], i))
    untimed = sorted(
        (i for i in present if not groups[i]["valid"]), key=lambda i: (-groups[i]["count"], i)
    )
    return count_order, time_order, time_order + untimed


def _bar_chart(title, color, labels_ref, values_ref, labels, values, fmt, series_name):
    chart = BarChart()
    chart.type = "bar"
    chart.style = 13
    chart.title = title
    # Without an explicit flag Excel draws the title over the first bars.
    chart.title.overlay = False
    chart.legend = None
    chart.width, chart.height = 15.0, 10.5
    chart.gapWidth = 60
    chart.display_blanks = "gap"
    chart.visible_cells_only = False
    # Rank 1 on top; values are read from labels, so the value axis is omitted.
    chart.x_axis.scaling.orientation = "maxMin"
    chart.x_axis.delete = False
    chart.y_axis.delete = True
    chart.y_axis.majorGridlines = None
    points = len(labels)
    series = Series()
    series.tx = SeriesLabel(v=series_name)
    # Cached points keep real line names visible before Excel recalculates.
    series.cat = AxDataSource(
        strRef=StrRef(
            f=labels_ref,
            strCache=StrData(
                ptCount=points, pt=[StrVal(idx=i, v=str(v)) for i, v in enumerate(labels)]
            ),
        )
    )
    series.val = NumDataSource(
        numRef=NumRef(
            f=values_ref,
            numCache=NumData(
                formatCode=fmt,
                ptCount=points,
                pt=[NumVal(idx=i, v=v) for i, v in enumerate(values) if v != ""],
            ),
        )
    )
    series.spPr = GraphicalProperties(solidFill=color)
    series.spPr.line.solidFill = color
    series.dLbls = DataLabelList(showVal=True, numFmt="#,##0", dLblPos="outEnd")
    for flag in ("showSerName", "showCatName", "showLegendKey", "showPercent"):
        setattr(series.dLbls, flag, False)
    chart.series.append(series)
    return chart


def build_module_comparison(issues):
    b, facts = issues.b, issues.facts
    ws = b.new_sheet(KEY, "동일 상세설비의 라인별 고장 비교", span=12)
    for column in range(1, 13):
        ws.column_dimensions[get_column_letter(column)].width = 13
    ws.merge_cells("A5:L5")
    b.put(
        ws,
        5,
        1,
        "① 상세설비 선택 → ② 필요 시 세부부품 선택 → 공장·팀으로 비교 범위 축소. "
        "막대 또는 표의 라인을 더블클릭하면 02.팀별 주요이슈의 해당 라인 세부부품(또는 고장이력)으로 이동합니다.",
        role="muted",
    )
    module = default_module(facts)
    fields = {"module": "B6", "part": "F6", "factory": "B7", "team": "F7"}
    labels = {"module": "상세설비", "part": "세부부품", "factory": "공장", "team": "팀"}
    for field in FIELD_ORDER:
        issues.selector(
            ws,
            fields[field],
            field,
            labels[field],
            module if field == "module" else ALL,
            span=3,
        )
    b.put(ws, 6, 9, "표 정렬")
    ws.merge_cells("J6:L6")
    b.put(ws, 6, 10, "건수", role="input")
    toggle = DataValidation(type="list", formula1='"건수,정지시간"', allow_blank=False)
    toggle.showErrorMessage = True
    toggle.error = "건수 또는 정지시간을 선택하세요."
    toggle.showInputMessage = True
    toggle.promptTitle = "표 정렬 기준"
    toggle.prompt = (
        "차트는 건수·정지시간을 각각 표시합니다. 아래 전체 라인 표의 정렬 기준만 바꿉니다."
    )
    ws.add_data_validation(toggle)
    toggle.add(ws["J6"])

    filters = issues.filters(ws, fields)
    args = issues.args(filters)
    scoped = select_issues(facts, module=module)
    valid = int(scoped["minutes"].count())
    total = float(scoped["minutes"].sum()) if valid else 0 if scoped.empty else ""
    for label, address, formula, cached, fmt in (
        ("고장이력(건)", "B9", issues.count_formula(args), len(scoped), "#,##0"),
        ("정지시간(분)", "E9", issues.time_formula(args, "B9", "H9"), total, "#,##0.0"),
        ("시간 유효(건)", "H9", issues.valid_formula(args), valid, "#,##0"),
        (
            "분류 검토(건)",
            "K9",
            f"=SUMIFS({issues.fact_range('review_count')},{args})",
            int(scoped["review_count"].sum()),
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
    b.put(
        ws,
        11,
        1,
        f"라인별 비교 — 차트: 상위 {CHART_TOP}개 · 아래 표: 전체 라인 (비중은 선택 범위 전체 대비)",
        role="title",
    )

    groups = _groups(facts)
    count_order, time_order, table_order = _stats(scoped, groups)
    helper = b.wb.create_sheet(HELPER)
    helper.sheet_state = "hidden"
    helper.append(
        [
            "공장",
            "팀",
            "라인",
            "표시명",
            "건수",
            "시간유효",
            "정지시간",
            "검토",
            "평균",
            "건수순위",
            "시간순위",
            "표 시간정렬",
            None,
            "건수 라벨",
            "건수",
            "공장",
            "팀",
            "라인",
            "시간 라벨",
            "정지시간",
            "공장",
            "팀",
            "라인",
            None,
            "차트 항목 수",
        ]
    )
    end = max(2, len(groups) + 1)
    count_rank = {i: rank for rank, i in enumerate(count_order, 1)}
    time_rank = {i: rank for rank, i in enumerate(time_order, 1)}
    table_rank = {i: rank for rank, i in enumerate(table_order, 1)}
    for index, group in enumerate(groups):
        row = index + 2
        for column, field in zip("ABCD", (*GROUP, "label"), strict=True):
            b.put(helper, row, "ABCD".index(column) + 1, group[field], project=False)
        scope = issues.args(
            filters, [(issues.fact_range(field), exact(group[field])) for field in GROUP]
        )
        for column, formula, cached, fmt in (
            ("E", issues.count_formula(scope), group["count"], "#,##0"),
            ("F", issues.valid_formula(scope), group["valid"], "#,##0"),
            (
                "G",
                f'=IF(F{row}=0,"",SUMIFS({issues.fact_range("minutes")},{scope}))',
                group["minutes"],
                "#,##0.0",
            ),
            (
                "H",
                f"=SUMIFS({issues.fact_range('review_count')},{scope})",
                group["review"],
                "#,##0",
            ),
            ("I", f'=IF(F{row}=0,"",G{row}/F{row})', group["mean"], "#,##0.0"),
            (
                "J",
                f'=IF(E{row}=0,"",COUNTIF($E$2:$E${end},">"&E{row})+COUNTIF($E$2:E{row},E{row}))',
                count_rank.get(index, ""),
                "#,##0",
            ),
            (
                "K",
                f'=IF(F{row}=0,"",COUNTIFS($F$2:$F${end},">0",$G$2:$G${end},">"&G{row})'
                f'+COUNTIFS($F$2:F{row},">0",$G$2:G{row},G{row}))',
                time_rank.get(index, ""),
                "#,##0",
            ),
            (
                # Lines without any recorded duration follow the timed lines by count.
                "L",
                f'=IF(E{row}=0,"",IF(F{row}>0,K{row},COUNTIF($F$2:$F${end},">0")'
                f'+COUNTIFS($F$2:$F${end},0,$E$2:$E${end},">"&E{row})'
                f"+COUNTIFS($F$2:F{row},0,$E$2:E{row},E{row})))",
                table_rank.get(index, ""),
                "#,##0",
            ),
        ):
            issues.formula(helper, f"{column}{row}", formula, cached, fmt)

    # Ranked chart rows: label, value and the factory/team/line used for drilling.
    for index in range(CHART_TOP):
        row = index + 2
        for rank_col, order, columns, value_col, key in (
            ("J", count_order, "NOPQR", "E", "count"),
            ("K", time_order, "STUVW", "G", "minutes"),
        ):
            match = f"MATCH({index + 1},${rank_col}$2:${rank_col}${end},0)"
            item = groups[order[index]] if index < len(order) else None
            for column, source, field in zip(
                columns, ("D", value_col, "A", "B", "C"), ("label", key, *GROUP), strict=True
            ):
                issues.formula(
                    helper,
                    f"{column}{row}",
                    f'=IFERROR(INDEX(${source}$2:${source}${end},{match}),"")',
                    item[field] if item else "",
                    "General" if column not in "OT" else "#,##0.0",
                )
    issues.formula(
        helper,
        "Y2",
        f'=MIN({CHART_TOP},COUNTIF($E$2:$E${end},">0"))',
        min(CHART_TOP, len(count_order)),
        "0",
    )
    issues.formula(
        helper,
        "Y3",
        f'=MIN({CHART_TOP},COUNTIF($F$2:$F${end},">0"))',
        min(CHART_TOP, len(time_order)),
        "0",
    )
    owner = ref(SHEET)
    last_chart = CHART_TOP + 1
    for name, column, size in (
        ("CountLabels", "N", "$Y$2"),
        ("CountValues", "O", "$Y$2"),
        ("TimeLabels", "S", "$Y$3"),
        ("TimeValues", "T", "$Y$3"),
    ):
        # Charts shrink to the lines present instead of drawing empty slots.
        ws.defined_names.add(
            DefinedName(
                "_Compare_" + name,
                attr_text=f"'{HELPER}'!${column}$2:INDEX('{HELPER}'!${column}$2:${column}${last_chart},MAX(1,'{HELPER}'!{size}))",
            )
        )
    for name, columns in (("_Compare_CountRows", "P:R"), ("_Compare_TimeRows", "U:W")):
        first, final = columns.split(":")
        b.wb.defined_names.add(
            DefinedName(name, attr_text=f"'{HELPER}'!${first}$2:${final}${last_chart}")
        )

    for order, title, color, fmt, kind, anchor in (
        (count_order, f"발생 건수 TOP {CHART_TOP} (건)", "166A70", "#,##0", "Count", "A12"),
        (time_order, f"정지시간 TOP {CHART_TOP} (분)", "AD6817", "#,##0", "Time", "G12"),
    ):
        shown = [groups[i] for i in order[:CHART_TOP]]
        key = "count" if kind == "Count" else "minutes"
        chart = _bar_chart(
            title,
            color,
            f"{owner}!_Compare_{kind}Labels",
            f"{owner}!_Compare_{kind}Values",
            [g["label"] for g in shown] or [""],
            [g[key] for g in shown] or [""],
            fmt,
            "건수" if kind == "Count" else "정지시간(분)",
        )
        ws.add_chart(chart, anchor)

    issues.header(
        ws,
        TABLE_HEADER,
        [
            "순위",
            "공장",
            "팀",
            "라인",
            "",
            "",
            "건수",
            "정지(분)",
            "평균(분)",
            "건수 비중",
            "시간 비중",
            "검토(건)",
        ],
    )
    ws.merge_cells(f"D{TABLE_HEADER}:F{TABLE_HEADER}")
    capacity = max(1, len(groups))
    helper_ref = f"'{HELPER}'"
    for offset in range(capacity):
        row = FIRST_ROW + offset
        ws.merge_cells(start_row=row, end_row=row, start_column=4, end_column=6)
        position = count_order[offset] if offset < len(count_order) else None
        item = groups[position] if position is not None else None
        match = (
            f'MATCH({offset + 1},IF($J$6="정지시간",{helper_ref}!$L$2:$L${end},'
            f"{helper_ref}!$J$2:$J${end}),0)"
        )
        issues.formula(
            ws, f"A{row}", f'=IF(D{row}="","",{offset + 1})', offset + 1 if item else "", "0"
        )
        for column, source, field, fmt in (
            ("B", "A", "factory", "General"),
            ("C", "B", "team", "General"),
            ("D", "C", "asset", "General"),
            ("G", "E", "count", "#,##0"),
            ("H", "G", "minutes", "#,##0.0"),
            ("I", "I", "mean", "#,##0.0"),
            ("L", "H", "review", "#,##0"),
        ):
            issues.formula(
                ws,
                f"{column}{row}",
                f'=IFERROR(INDEX({helper_ref}!${source}$2:${source}${end},{match}),"")',
                item[field] if item else "",
                fmt,
            )
        ws[f"D{row}"].alignment = Alignment(horizontal="left", vertical="center")
        for column, numerator, denominator, key, base in (
            ("J", "G", "$B$9", "count", len(scoped)),
            ("K", "H", "$E$9", "minutes", total),
        ):
            value = item[key] if item else ""
            cached = (
                value / base
                if isinstance(value, (int, float)) and isinstance(base, (int, float)) and base
                else ""
            )
            issues.formula(
                ws,
                f"{column}{row}",
                f'=IF(OR({numerator}{row}="",{denominator}="",{denominator}=0),"",{numerator}{row}/{denominator})',
                cached,
                "0.0%",
            )
    last = FIRST_ROW + capacity - 1
    issues.table_borders(ws, TABLE_HEADER, last, 1, 12)
    b.wb.defined_names.add(
        DefinedName("_Compare_TableRows", attr_text=f"{owner}!$B${FIRST_ROW}:$D${last}")
    )
    b.wb.defined_names.add(
        DefinedName("_Compare_TableLabels", attr_text=f"{owner}!$D${FIRST_ROW}:$D${last}")
    )
    for row in range(FIRST_ROW, last + 1):
        ws.row_dimensions[row].hidden = bool(getattr(b, "macro_navigation", False)) and (
            row - FIRST_ROW >= len(count_order)
        )
    # No freeze panes: assigning None leaves pane-less selections Excel refuses to open.
    ws.print_area = f"A1:L{last}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToHeight = 0
