"""A single filtered month/day view for Excel 2019/2021."""

from copy import copy
from datetime import timedelta

import pandas as pd
from openpyxl.utils.cell import absolute_coordinate
from openpyxl.utils.datetime import to_excel
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from core.issue_analysis import FACT_COLUMNS, case_months
from core.period_analysis import case_days
from report.issue_workbook import ref, report_issue_facts

SHEET = "03.월별 주요이슈"
FIRST = 25
MODES = ("월별", "일별")
HELPER_HEADER = [
    "기간",
    "건수",
    "정지(분)",
    "평균(분)",
    "시간유효",
    "검토",
    "이전건수",
    "이전정지",
    "전년건수",
    "전년정지",
    "기간확인",
]
CALENDARS = {
    "월별": {
        "helper": "_period_monthly",
        "parse": lambda key: (pd.Timestamp(key + "-01"), pd.DateOffset(months=1)),
        "stop": lambda begin: f"EDATE({begin},1)",
        "lags": ((1, "전월"), (12, "전년동월")),
    },
}


def _choose(monthly, daily):
    """Pick the expression for the active view unit (월별 or 일별)."""
    return f"IF('_period_state'!$B$3=\"일별\",{daily},{monthly})"


def _text(value):
    return '"' + value.replace('"', '""') + '"'


def install_period_view(builder):
    if SHEET not in builder.wb:
        return
    b, book, ws = builder, builder.wb, builder.wb[SHEET]
    facts = report_issue_facts(b.r.selected)
    months = case_months(facts)
    keys = months.period.tolist()
    first_month = keys[0] if keys else ""
    state = book.create_sheet("_period_state")
    state.sheet_state = "hidden"
    state.append(["설정", "값"])
    for address, formula, cached in (
        (
            "B2",
            f"=IFERROR(DATE(VALUE(LEFT({ref(SHEET)}!$D$8,4)),VALUE(RIGHT({ref(SHEET)}!$D$8,2)),1),0)",
            to_excel(pd.Timestamp(first_month + "-01").to_pydatetime()) if keys else 0,
        ),
        ("B3", f"={ref(SHEET)}!$B$8", "월별"),
        ("B9", "=" + _choose('"월"', '"일"'), "월"),
        ("B4", "=" + _choose(str(len(keys)), "IF(B2=0,0,DAY(EOMONTH(B2,0)))"), len(keys)),
        (
            "B7",
            "=" + _choose('"월별 발생 건수"', f'{ref(SHEET)}!$D$8&" 일별 발생 건수"'),
            "월별 발생 건수",
        ),
        (
            "B8",
            "=" + _choose('"월별 정지시간"', f'{ref(SHEET)}!$D$8&" 일별 정지시간"'),
            "월별 정지시간",
        ),
    ):
        b.cache.set(state, address, formula, cached)
    month_list = book.create_sheet("_period_months")
    month_list.sheet_state = "hidden"
    for row, key in enumerate(keys or [""], 1):
        month_list.cell(row, 1, key).data_type = "s"

    def named(name, target):
        book.defined_names.add(DefinedName(name, attr_text=target))

    named("_Period_Months", f"'_period_months'!$A$1:$A${max(1, len(keys))}")
    for label, address, value, merge in (
        ("조회 단위", "B8", "월별", "B8:B8"),
        ("일별 조회 월", "D8", first_month, "D8:D8"),
    ):
        target = ws[address]
        ws.cell(8, target.column - 1, label)
        ws.merge_cells(merge)
        target.value = value
        target.number_format = "@"
    if "L7:L8" in ws.merged_cells:
        ws.unmerge_cells("L7:L8")
    ws["L7"].value = None
    ws["L7"]._style = None
    for address, formula in (("B8", '"' + ",".join(MODES) + '"'), ("D8", "=_Period_Months")):
        dv = DataValidation(type="list", formula1=formula, allow_blank=False)
        dv.showErrorMessage = True
        dv.error = "목록에서 선택하세요."
        ws.add_data_validation(dv)
        dv.add(ws[address])
    for name, address in (("Mode", "B8"), ("Month", "D8")):
        named("_Period_" + name, f"{ref(SHEET)}!{absolute_coordinate(address)}")
    named("_Period_ActiveCount", "'_period_state'!$B$4")
    b.cache.set(
        ws,
        "A1",
        "=" + _choose('"월별 주요이슈"', 'D8&" 일별 주요이슈"'),
        "월별 주요이슈",
    )
    ws.merge_cells("A4:K4")
    ws["A4"] = "상단 필터와 조회 단위에 따라 차트와 표가 갱신됩니다. 일별 조회는 월을 선택하세요."
    dates = pd.to_datetime(facts.date, errors="coerce").dropna()
    start = (
        pd.Timestamp(b.r.options.date_from).normalize()
        if b.r.options.date_from
        else dates.min().normalize()
        if len(dates)
        else None
    )
    finish = (
        pd.Timestamp(b.r.options.date_to).normalize()
        if b.r.options.date_to
        else dates.max().normalize()
        if len(dates)
        else None
    )
    end = max(2, len(facts) + 1)

    def field(key):
        from openpyxl.utils import get_column_letter

        col = get_column_letter(FACT_COLUMNS.index(key) + 1)
        return f"'_issue_facts'!${col}$2:${col}${end}"

    scope = b.period_filter_range

    def args(begin, stop):
        return f'{scope},1,{field("date")},">="&{begin},{field("date")},"<"&{stop}'

    def values(begin, stop):
        a = args(begin, stop)
        count = f"COUNTIFS({a})"
        valid = f'COUNTIFS({a},{field("minutes")},">=0",{field("minutes")},"<>")'
        minutes = f'IF({count}=0,0,IF({valid}=0,"",SUMIFS({field("minutes")},{a})))'
        return count, valid, minutes, f"SUMIFS({field('review_count')},{a})"

    helpers = {}
    cached_days = case_days(facts, first_month) if keys else None
    day_lookup = case_days(facts).set_index("period").to_dict("index") if len(dates) else {}

    def calendar_helper(mode, records):
        """Month/week/year rows: one fixed calendar period per row with lagged deltas."""
        spec = CALENDARS[mode]
        helper = book.create_sheet(spec["helper"])
        helper.sheet_state = "hidden"
        helper.append(HELPER_HEADER)
        for index, item in enumerate(records):
            row = index + 2
            key = item["period"]
            day, step = spec["parse"](key)
            begin = f"DATE({day.year},{day.month},{day.day})"
            stop = spec["stop"](begin)
            count, valid, minutes, review = values(begin, stop)
            helper.cell(row, 1, key).data_type = "s"
            for col, formula, cached in (
                ("B", count, item["count"]),
                ("C", minutes, item["total_minutes"]),
                ("D", f'IF(E{row}=0,"",C{row}/E{row})', item["mean_minutes"]),
                ("E", valid, item["valid_count"]),
                ("F", review, item["review_count"]),
            ):
                b.cache.set(helper, f"{col}{row}", f'=IF(A{row}="","",{formula})', cached)
            # A period cut by the analysis range is not compared with a full one.
            partial = start is not None and (day < start or day + step - timedelta(days=1) > finish)
            b.cache.set(
                helper,
                f"K{row}",
                '="부분기간 가능"' if partial else '=""',
                "부분기간 가능" if partial else "",
            )
            for slot, (cc, tc) in enumerate((("G", "H"), ("I", "J"))):
                lag = spec["lags"][slot][0] if slot < len(spec["lags"]) else None
                previous = records[index - lag] if lag and index >= lag else None
                if previous is None:
                    for col in (cc, tc):
                        b.cache.set(helper, f"{col}{row}", '=""', "")
                    continue
                prior_row = row - lag
                comparable = (
                    not partial
                    and b.cache.values.get((helper.title, f"K{prior_row}")) != "부분기간 가능"
                )
                for col, base, value in (
                    (cc, "B", item["count"] - previous["count"]),
                    (tc, "C", item["total_minutes"] - previous["total_minutes"]),
                ):
                    b.cache.set(
                        helper,
                        f"{col}{row}",
                        f'=IF(OR(K{row}<>"",K{prior_row}<>"",{base}{row}="",{base}{prior_row}=""),"",{base}{row}-{base}{prior_row})',
                        value if comparable else "",
                    )
        helpers[mode] = (helper, len(records))
        return helper

    calendar_helper("월별", months.to_dict("records"))

    helper = book.create_sheet("_period_daily")
    helper.sheet_state = "hidden"
    helper.append(HELPER_HEADER)
    records = cached_days.to_dict("records") if keys else []
    for index in range(31):
        row = index + 2
        item = records[index] if index < len(records) else None
        key = item["period"] if item else ""
        day = pd.Timestamp(key) if key else None
        begin = f"'_period_state'!$B$2+{index}"
        stop = f"({begin})+1"
        count, valid, minutes, review = values(begin, stop)
        period_formula = f"=IF(OR('_period_state'!$B$2=0,{index + 1}>DAY(EOMONTH('_period_state'!$B$2,0))),\"\",TEXT({begin},\"yyyy-mm-dd\"))"
        b.cache.set(helper, f"A{row}", period_formula, key)
        for col, formula, cached in (
            ("B", count, item["count"] if item else ""),
            ("C", minutes, item["total_minutes"] if item else ""),
            ("D", f'IF(E{row}=0,"",C{row}/E{row})', item["mean_minutes"] if item else ""),
            ("E", valid, item["valid_count"] if item else ""),
            ("F", review, item["review_count"] if item else ""),
        ):
            b.cache.set(helper, f"{col}{row}", f'=IF(A{row}="","",{formula})', cached)
            start_serial = to_excel(start.to_pydatetime()) if start is not None else 0
            end_serial = to_excel(finish.to_pydatetime()) if finish is not None else 0
            b.cache.set(
                helper,
                f"K{row}",
                f'=IF(A{row}="","",IF(OR({begin}<{start_serial},{begin}>{end_serial}),"집계기간 외",IF(OR({begin}={start_serial},{begin}={end_serial}),"부분기간 가능","")))',
                "집계기간 외"
                if day is not None and (day < start or day > finish)
                else "부분기간 가능"
                if day is not None and day in (start, finish)
                else "",
            )
            # Daily comparisons use calendar dates, never the monthly row-12 lag.
            for lag, count_col, time_col in ((1, "G", "H"), (365, "I", "J")):
                previous = (
                    f"({begin})-1"
                    if lag == 1
                    else f"DATE(YEAR({begin})-1,MONTH({begin}),DAY({begin}))"
                )
                pc, pv, pt, _ = values(previous, f"({previous})+1")
                guard = (
                    f'OR(A{row}="",K{row}<>"",{previous}<={start_serial},{previous}>={end_serial},MONTH({previous})<>MONTH({begin}))'
                    if lag != 1
                    else f'OR(A{row}="",K{row}<>"",{previous}<={start_serial},{previous}>={end_serial})'
                )
                before = None
                if day is not None:
                    try:
                        date_value = day.to_pydatetime()
                        before = pd.Timestamp(
                            date_value - timedelta(days=1)
                            if lag == 1
                            else date_value.replace(year=date_value.year - 1)
                        )
                    except ValueError:
                        pass
                comparable = (
                    day is not None
                    and before is not None
                    and start < day < finish
                    and start < before < finish
                    and (lag == 1 or (before.month, before.day) == (day.month, day.day))
                )
                prior_item = day_lookup.get(before.strftime("%Y-%m-%d"), {}) if comparable else {}
                for col, formula, cached in (
                    (
                        count_col,
                        f'IF({guard},"",B{row}-{pc})',
                        item["count"] - prior_item.get("count", 0) if comparable else "",
                    ),
                    (
                        time_col,
                        f'IF(OR({guard},C{row}="",{pt}=""),"",C{row}-{pt})',
                        item["total_minutes"] - prior_item.get("total_minutes", 0)
                        if comparable
                        else "",
                    ),
                ):
                    b.cache.set(helper, f"{col}{row}", "=" + formula, cached)
    helpers["일별"] = (helper, 31)
    # Extend styled output rows for all 31 days while retaining the edited header.
    count = max(31, len(keys), 1)
    monthly = helpers["월별"][0]
    for area in list(ws.merged_cells.ranges):
        if area.min_row >= FIRST:
            ws.unmerge_cells(str(area))
    styles = [copy(ws.cell(FIRST, col)._style) for col in range(1, 12)]
    for row in range(FIRST, max(ws.max_row, FIRST + count - 1) + 1):
        for col in range(1, 12):
            cell = ws.cell(row, col)
            cell.value = None
            b.cache.values.pop((SHEET, cell.coordinate), None)
            cell._style = copy(styles[col - 1])
        ws.row_dimensions[row].height = 21
        ws.row_dimensions[row].hidden = bool(
            getattr(b, "macro_navigation", False)
        ) and row >= FIRST + len(keys)
    display = book.create_sheet("_period_display")
    display.sheet_state = "hidden"
    for index in range(count):
        row = FIRST + index
        for col in range(1, 12):
            from openpyxl.utils import get_column_letter

            letter = get_column_letter(col)
            old = (
                (
                    keys[index]
                    if col == 1
                    else b.cache.values.get(
                        (monthly.title, f"{letter}{index + 2}"),
                        monthly.cell(index + 2, col).value,
                    )
                )
                if index < len(keys)
                else ""
            )
            choices = []
            for mode in MODES:
                helper, size = helpers[mode]
                last = max(2, size + 1)
                choices.append(
                    f"IF({index + 1}>{size},\"\",INDEX('{helper.title}'!{letter}$2:{letter}${last},{index + 1}))"
                )
            formula = f'=IFERROR({_choose(*choices)},"")'
            b.cache.set(ws, f"{letter}{row}", formula, old)
            if col in (7, 8, 9, 10):
                ws[f"{letter}{row}"].number_format = '[Red]"▲ "#,##0;[Blue]"▼ "#,##0;0'
        b.cache.set(
            display,
            f"A{index + 2}",
            # Keep the full period in the table for drilldown and shorten only the chart.
            f'=IF({ref(SHEET)}!A{row}="","",'
            + _choose(f'"\'"&RIGHT({ref(SHEET)}!A{row},5)', f"RIGHT({ref(SHEET)}!A{row},2)")
            + ")",
            "'" + keys[index][2:] if index < len(keys) else "",
        )
        for col in "BC":
            b.cache.set(
                display,
                f"{col}{index + 2}",
                f"={ref(SHEET)}!{col}{row}",
                b.cache.values[(SHEET, f"{col}{row}")],
            )
            display[f"{col}{index + 2}"].number_format = "#,##0"
    for address, labels in (
        ("A23", ("월", "일")),
        ("G23", ("전월 대비 건수", "전일 대비 건수")),
        ("H23", ("전월 대비 정지(분)", "전일 대비 정지(분)")),
        ("I23", ("전년동월 대비 건수", "전년동일 대비 건수")),
        ("J23", ("전년동월 대비 정지(분)", "전년동일 대비 정지(분)")),
    ):
        b.cache.set(ws, address, "=" + _choose(*map(_text, labels)), labels[0])
    named("_Period_Rows", f"{ref(SHEET)}!$A${FIRST}:$A${FIRST + count - 1}")
    for name, col in (("ChartLabels", "A"), ("ChartCount", "B"), ("ChartMinutes", "C")):
        target = f"'_period_display'!${col}$2:INDEX('_period_display'!${col}$2:${col}${count + 1},MAX(1,'_period_state'!$B$4))"
        named("_Period_" + name, target)
        ws.defined_names.add(DefinedName("_Period_" + name, attr_text=target))
    ws.print_area = f"A1:L{FIRST + max(1, len(keys)) - 1}"
    b._locked_template["sheets"][SHEET]["period_chart_ranges"] = {
        "category": f"{ref(SHEET)}!_Period_ChartLabels",
        "B": f"{ref(SHEET)}!_Period_ChartCount",
        "C": f"{ref(SHEET)}!_Period_ChartMinutes",
        "cache_category": f"'_period_display'!$A$2:$A${max(2, len(keys) + 1)}",
        "cache_B": f"'_period_display'!$B$2:$B${max(2, len(keys) + 1)}",
        "cache_C": f"'_period_display'!$C$2:$C${max(2, len(keys) + 1)}",
    }
