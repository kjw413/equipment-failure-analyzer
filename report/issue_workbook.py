"""Excel selectors drive native charts and formulas over retained fault facts."""

from __future__ import annotations

import pandas as pd
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from core.issue_analysis import (
    ALL,
    FACT_COLUMNS,
    case_months,
    issue_facts,
    issue_summary,
)
from report.formatting import bounded_int

ISSUE_SHEETS = {
    "organization_issues": "02.팀별 주요이슈",
    "issue_trends": "03.월별 주요이슈",
    "issue_comparison": "04.고장비교",
}


def ref(name):
    return "'" + name.replace("'", "''") + "'"


def exact(value):
    value = str(value).replace("~", "~~").replace("*", "~*").replace("?", "~?")
    return '"=' + value.replace('"', '""') + '"'


def criterion(cell):
    return f'IF(OR({cell}="{ALL}",{cell}=""),"*","="&{escaped_cell(cell)})'


def report_issue_facts(records):
    """Aggregate each detailed equipment regardless of the observed symptom."""
    facts = issue_facts(records)
    facts["case"] = facts["module"]
    return facts


def escaped_cell(cell):
    return f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({cell},"~","~~"),"*","~*"),"?","~?")'


class IssueWorkbook:
    def __init__(self, builder):
        self.b = builder
        self.facts = report_issue_facts(builder.r.selected)
        self.last = max(2, len(self.facts) + 1)
        self.top_n = bounded_int(
            builder.r.config_snapshot.get("final_report", {}).get("summary_top_n"), 5, 10
        )
        self.default_case = ALL
        self.filter_scopes = {}
        self.organizations = (
            self.facts[["factory", "team"]].drop_duplicates().sort_values(["factory", "team"])
        )
        self.org_labels = []
        for number, (factory, team) in enumerate(
            self.organizations.itertuples(index=False, name=None), 1
        ):
            label = f"{factory} / {team}"
            if label in self.org_labels:
                label += f" (조직 {number})"
            self.org_labels.append(label)

    def fact_range(self, key):
        col = get_column_letter(FACT_COLUMNS.index(key) + 1)
        return f"'_issue_facts'!${col}$2:${col}${self.last}"

    def formula(self, ws, cell, formula, value, fmt="#,##0.0"):
        target = ws[cell]
        return self.b.formula(ws, target.row, target.column, formula, value, fmt)

    def prepare(self):
        ws = self.b.wb.create_sheet("_issue_facts")
        ws.append(FACT_COLUMNS)
        for row in self.facts.itertuples(index=False, name=None):
            ws.append([None if pd.isna(value) else value for value in row])
        # Text from names and source data must remain literal, including '=' prefixes.
        for row in ws:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        ws.sheet_state = "hidden"
        lists = self.b.wb.create_sheet("_issue_lists")
        self.lists = {}
        for index, key in enumerate(("factory", "team", "asset", "module", "organization"), 1):
            values = (
                self.org_labels if key == "organization" else [ALL, *sorted(set(self.facts[key]))]
            )
            if not values:
                values = [ALL]
            for row, value in enumerate(values, 1):
                cell = lists.cell(row, index, value)
                cell.data_type = "s"
            name = "_Issue_" + key
            col = get_column_letter(index)
            self.b.wb.defined_names.add(
                DefinedName(name, attr_text=f"'_issue_lists'!${col}$1:${col}${len(values)}")
            )
            self.lists[key] = name
        lists.sheet_state = "hidden"

    def sheet(self, key, title, span=12):
        ws = self.b.new_sheet(ISSUE_SHEETS[key], title, span=span)
        for col in range(1, span + 1):
            ws.column_dimensions[get_column_letter(col)].width = 13
        # Keep export metadata in the base coordinates for the shared layout pass.
        ws.freeze_panes = None
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        return ws

    def selector(self, ws, cell, key, label, value=ALL, span=1):
        target = ws[cell]
        caption = self.b.put(ws, target.row, target.column - 1, label, project=False)
        caption.alignment = Alignment(horizontal="center", vertical="center")
        caption.font = Font(name="KoPubWorld돋움체 Medium", size=11, bold=True, color="17212A")
        if span > 1:
            ws.merge_cells(
                start_row=target.row,
                start_column=target.column,
                end_row=target.row,
                end_column=target.column + span - 1,
            )
        edit = self.b.put(ws, target.row, target.column, value, role="input", project=False)
        edit.fill = PatternFill("solid", fgColor="E8F0FC")
        edit.font = Font(name="KoPubWorld돋움체 Medium", size=11, color="17212A")
        edit.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[target.row].height = 22
        validation = DataValidation(type="list", formula1="=" + self.lists[key], allow_blank=False)
        searchable = key in ("factory", "team", "asset", "module")
        validation.errorTitle = "목록에서 선택"
        validation.error = "목록의 값 또는 (전체)를 선택하세요."
        validation.showErrorMessage = True
        validation.showInputMessage = True
        validation.promptTitle = "필터 검색 / 목록 선택" if searchable else "목록 선택"
        validation.prompt = (
            "매크로 보고서는 셀 선택 시 검색창이 열립니다. 검색 후 후보 하나를 선택하세요. 기본 목록도 사용할 수 있습니다. (전체)로 해제합니다."
            if searchable
            else "목록에서 항목을 선택하세요."
        )
        validation.errorStyle = "stop"
        ws.add_data_validation(validation)
        validation.add(edit)
        return value

    def header(self, ws, row, labels, start=1):
        for column, label in enumerate(labels, start):
            cell = self.b.put(ws, row, column, label, project=False)
            cell.fill = PatternFill("solid", fgColor="E8EBEE")
            cell.font = Font(name="KoPubWorld돋움체 Medium", size=11, bold=True, color="17212A")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 22

    def table_borders(self, ws, first, last, left, right):
        line = Side(style="thin", color="C8CDD2")
        for row in ws.iter_rows(min_row=first, max_row=last, min_col=left, max_col=right):
            for cell in row:
                cell.border = Border(
                    top=line,
                    bottom=line,
                    left=line if cell.column > left else Side(),
                    right=line if cell.column < right else Side(),
                )
        for row in range(first, last + 1):
            ws.row_dimensions[row].height = 22

    def note(self, ws, row, text, span=12):
        ws.merge_cells(start_row=row, start_column=1, end_row=row + 1, end_column=span)
        self.b.put(ws, row, 1, text, role="muted", project=False)
        ws.row_dimensions[row].height = 22
        ws.row_dimensions[row + 1].height = 22

    def filters(self, ws, fields):
        return {key: f"{ref(ws.title)}!${cell[0]}${cell[1:]}" for key, cell in fields.items()}

    def args(self, filters, extra=()):
        pairs = [(self.filter_scope(filters), "1")] if filters else []
        pairs.extend(extra)
        return ",".join(value for pair in pairs for value in pair)

    def filter_scope(self, filters):
        """Aggregate only committed exact selections; query text never changes scope."""
        signature = tuple(filters.items())
        if signature not in self.filter_scopes:
            ws = self.b.wb.create_sheet(f"_issue_filter_{len(self.filter_scopes) + 1}")
            ws.append(["선택 범위 포함"])
            for row in range(2, len(self.facts) + 2):
                conditions = []
                for key, cell in filters.items():
                    col = get_column_letter(FACT_COLUMNS.index(key) + 1)
                    value = f"'_issue_facts'!${col}{row}"
                    conditions.append(f'IF(OR({cell}="{ALL}",{cell}=""),TRUE,{value}={cell})')
                self.formula(ws, f"A{row}", "=IF(AND(" + ",".join(conditions) + "),1,0)", 1, "0")
            ws.sheet_state = "hidden"
            self.filter_scopes[signature] = f"'{ws.title}'!$A$2:$A${self.last}"
        return self.filter_scopes[signature]

    def count_formula(self, args):
        return f"=COUNTIFS({args})"

    def valid_formula(self, args):
        return f'=COUNTIFS({args},{self.fact_range("minutes")},">=0",{self.fact_range("minutes")},"<>")'

    def time_formula(self, args, count_cell, valid_cell):
        return f'=IF({count_cell}=0,0,IF({valid_cell}=0,"",SUMIFS({self.fact_range("minutes")},{args})))'

    def chart(self, ws, start, end, category_col, value_col, anchor, title, unit, line=False):
        if end < start:
            return
        chart = LineChart() if line else BarChart()
        if not line:
            chart.type = "bar"
            chart.x_axis.scaling.orientation = "maxMin"
            chart.y_axis.scaling.orientation = "minMax"
        chart.title = f"{title} ({unit})" if not line else title
        chart.x_axis.title = "월" if line else None
        chart.y_axis.title = unit
        chart.legend = None
        chart.style = 13
        chart.width, chart.height = 14, 7.5
        chart.display_blanks = "gap"
        chart.add_data(
            Reference(ws, min_col=value_col, min_row=start - 1, max_row=end), titles_from_data=True
        )
        color = "166A70" if unit == "건" else "AD6817"
        for series in chart.series:
            series.graphicalProperties.solidFill = color
            series.graphicalProperties.line.solidFill = color
            if line:
                series.smooth = False
                series.marker.symbol = "circle"
                series.marker.size = 5
        if line:
            chart.smooth = False
        chart.set_categories(Reference(ws, min_col=category_col, min_row=start, max_row=end))
        if not line:
            chart.dLbls = DataLabelList(showVal=True, numFmt="#,##0", dLblPos="outEnd")
            # Long case labels leave little room for numeric time-axis ticks.
            # Native data labels retain the exact values after filter changes.
            if unit == "분":
                chart.y_axis.delete = True
        ws.add_chart(chart, anchor)

    def organization(self):
        ws = self.sheet("organization_issues", "공장·팀·라인의 주요 고장이슈")
        for index, width in enumerate((6, 20, 20, 9, 12, 9) * 2, 1):
            ws.column_dimensions[get_column_letter(index)].width = width
        fields = {"factory": "B6", "team": "D6", "asset": "F6", "module": "K6"}
        for key, cell in fields.items():
            self.selector(
                ws,
                cell,
                key,
                {
                    "factory": "공장",
                    "team": "팀",
                    "asset": "라인",
                    "module": "상세설비",
                }[key],
                span={"asset": 3, "module": 2}.get(key, 1),
            )
        filters = self.filters(ws, fields)
        args = self.args(filters)
        valid = int(self.facts.minutes.count())
        total = self.facts.minutes.sum(min_count=1)
        self.b.put(ws, 7, 1, "고장기록(건)")
        self.formula(ws, "B7", self.count_formula(args), len(self.facts), "#,##0")
        self.b.put(ws, 7, 3, "정지시간(분)")
        self.formula(
            ws,
            "D7",
            self.time_formula(args, "B7", "F7"),
            total if valid else 0 if self.facts.empty else "",
        )
        self.b.put(ws, 7, 5, "시간 유효(건)")
        self.formula(ws, "F7", self.valid_formula(args), valid, "#,##0")
        self.b.put(ws, 7, 7, "분류 검토(건)")
        self.formula(
            ws,
            "H7",
            f"=SUMIFS({self.fact_range('review_count')},{args})",
            int(self.facts.review_count.sum()),
            "#,##0",
        )
        self.table_borders(ws, 7, 7, 1, 8)
        from report.drilldown import build_ranks

        end, summaries = build_ranks(self, filters)
        cases = sorted(summaries.index)
        count_order = sorted(cases, key=lambda case: (-summaries.at[case, "count"], case))
        time_order = sorted(
            (case for case in cases if summaries.at[case, "valid_count"]),
            key=lambda case: (-summaries.at[case, "total_minutes"], case),
        )
        for left, metric, label, rank_col, order in (
            (1, "count", "발생 건수", "F", count_order),
            (7, "time", "정지시간", "G", time_order),
        ):
            ws.merge_cells(start_row=8, start_column=left, end_row=8, end_column=left + 5)
            self.b.put(ws, 8, left, f"{label} TOP {self.top_n}", role="title").font = Font(
                name="KoPubWorld돋움체 Medium", size=14, bold=True
            )
            self.header(ws, 9, ("순위", "라인", "", "건수", "정지(분)", "비중"), left)
            ws.merge_cells(start_row=9, start_column=left + 1, end_row=9, end_column=left + 2)
            for index in range(self.top_n):
                row, case = 10 + index, order[index] if index < len(order) else ""
                self.b.put(ws, row, left, index + 1)
                ws.merge_cells(
                    start_row=row, start_column=left + 1, end_row=row, end_column=left + 2
                )
                case_cell = f"{get_column_letter(left + 1)}{row}"
                self.formula(
                    ws,
                    case_cell,
                    f"=IFERROR(INDEX('_issue_rank'!$A$2:$A${end},MATCH({index + 1},'_issue_rank'!${rank_col}$2:${rank_col}${end},0)),\"\")",
                    case,
                    "General",
                ).alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
                item = summaries.loc[case] if case else None
                for offset, helper_col, key in ((3, "B", "count"), (4, "D", "total_minutes")):
                    value = item[key] if case else ""
                    self.formula(
                        ws,
                        f"{get_column_letter(left + offset)}{row}",
                        f"=IF({case_cell}=\"\",\"\",INDEX('_issue_rank'!${helper_col}$2:${helper_col}${end},MATCH({index + 1},'_issue_rank'!${rank_col}$2:${rank_col}${end},0)))",
                        value,
                        "#,##0" if key == "count" else "#,##0.0",
                    )
                value_col = get_column_letter(left + (3 if metric == "count" else 4))
                denominator = "$B$7" if metric == "count" else "$D$7"
                value = (
                    (
                        item["count"] / len(self.facts)
                        if metric == "count"
                        else item["total_minutes"] / total
                        if pd.notna(total) and total > 0
                        else ""
                    )
                    if case
                    else ""
                )
                self.formula(
                    ws,
                    f"{get_column_letter(left + 5)}{row}",
                    f'=IF(OR({case_cell}="",{denominator}=0,{denominator}=""),"",{value_col}{row}/{denominator})',
                    value,
                    "0.0%",
                )
                ws.row_dimensions[row].height = 22
            self.table_borders(ws, 9, 9 + self.top_n, left, left + 5)
            self.chart(
                ws,
                10,
                9 + self.top_n,
                left + 1,
                left + (3 if metric == "count" else 4),
                f"{get_column_letter(left)}{11 + self.top_n}",
                f"{label} TOP {self.top_n}",
                "건" if metric == "count" else "분",
            )
        last = 25 + self.top_n
        self.note(
            ws,
            last,
            "시간 미기재는 빈칸 표시. 건수·시간 순위는 동일 이력의 두 기준이며 합산하지 않음. 0건은 선택 범위에 해당 기록 없음.",
        )
        ws.print_area = f"A1:L{last + 2}"

    def comparison(self):
        ws = self.sheet("issue_comparison", "동일 상세설비의 공장·팀 비교", span=10)
        # Factory and team are already visible; retain their combined chart key privately.
        ws.column_dimensions["J"].hidden = True
        self.selector(
            ws,
            "B6",
            "organization",
            "기준 조직",
            next(iter(self.org_labels), ALL),
            span=3,
        )
        self.selector(ws, "B7", "asset", "라인", span=3)
        self.selector(ws, "G7", "module", "상세설비", span=4)
        filters = self.filters(ws, {"module": "G7", "asset": "B7"})
        selected = self.facts
        cached = issue_summary(selected, ["factory", "team"]).set_index(["factory", "team"])
        ws.merge_cells("A9:J9")
        self.b.put(ws, 9, 1, "조직별 고장 비교", role="title").font = Font(
            name="KoPubWorld돋움체 Medium", size=14, bold=True
        )
        self.header(
            ws,
            10,
            [
                "공장",
                "팀",
                "건수",
                "정지(분)",
                "평균(분)",
                "기준 대비 건수",
                "기준 대비 정지(분)",
                "분류 검토(건)",
                "시간 유효(건)",
                "조직",
            ],
        )
        end = max(11, 10 + len(self.organizations))
        baseline = (
            cached.loc[tuple(self.organizations.iloc[0])]
            if len(self.organizations) and tuple(self.organizations.iloc[0]) in cached.index
            else None
        )
        baseline_count = int(baseline["count"]) if baseline is not None else 0
        baseline_time = baseline["total_minutes"] if baseline is not None else 0
        for index, (factory, team) in enumerate(
            self.organizations.itertuples(index=False, name=None)
        ):
            row = 11 + index
            item = cached.loc[(factory, team)] if (factory, team) in cached.index else None
            count = int(item["count"]) if item is not None else 0
            valid = int(item["valid_count"]) if item is not None else 0
            time = item["total_minutes"] if item is not None else 0
            args = self.args(
                filters,
                [
                    (self.fact_range("factory"), exact(factory)),
                    (self.fact_range("team"), exact(team)),
                ],
            )
            for col, value in ((1, factory), (2, team), (10, self.org_labels[index])):
                self.b.put(ws, row, col, value, project=False)
            self.formula(ws, f"C{row}", self.count_formula(args), count, "#,##0")
            self.formula(ws, f"I{row}", self.valid_formula(args), valid, "#,##0")
            self.formula(ws, f"D{row}", self.time_formula(args, f"C{row}", f"I{row}"), time)
            self.formula(
                ws,
                f"E{row}",
                f'=IF(I{row}=0,"",D{row}/I{row})',
                item["mean_minutes"] if item is not None else "",
            )
            self.formula(
                ws,
                f"H{row}",
                f"=SUMIFS({self.fact_range('review_count')},{args})",
                int(item["review_count"]) if item is not None else 0,
                "#,##0",
            )
            base_count = f"INDEX($C$11:$C${end},MATCH({escaped_cell('$B$6')},$J$11:$J${end},0))"
            base_time = f"INDEX($D$11:$D${end},MATCH({escaped_cell('$B$6')},$J$11:$J${end},0))"
            self.formula(
                ws,
                f"F{row}",
                f'=IFERROR(C{row}-{base_count},"")',
                count - baseline_count,
                '[Red]"▲ "#,##0;[Blue]"▼ "#,##0;0',
            )
            self.formula(
                ws,
                f"G{row}",
                f'=IFERROR(IF(OR(D{row}="",{base_time}=""),"",D{row}-{base_time}),"")',
                time - baseline_time if pd.notna(time) and pd.notna(baseline_time) else "",
                '[Red]"▲ "#,##0.0;[Blue]"▼ "#,##0.0;0.0',
            )
            ws.row_dimensions[row].height = 22
        self.table_borders(ws, 10, end, 1, 10)
        chart_row = max(19, end + 3)
        if len(self.organizations):
            for col, anchor, title, unit in (
                (3, "A", "조직별 발생 건수", "건"),
                (4, "F", "조직별 정지시간", "분"),
            ):
                self.chart(ws, 11, end, 10, col, f"{anchor}{chart_row}", title, unit)
                ws._charts[-1].visible_cells_only = False
                ws._charts[-1].width = 12
        else:
            self.b.put(ws, 11, 1, "선택 범위에 고장 기록이 없습니다.", role="muted")
        last = chart_row + 14
        self.note(
            ws,
            last,
            "차이 = 해당 조직 - 기준 부서. 선택한 라인·상세설비 범위로 비교합니다. 가동시간·생산량 미보정. 시간 미기재는 빈칸.",
            span=10,
        )
        ws.print_area = f"A1:J{last + 2}"

    def trends(self):
        ws = self.sheet("issue_trends", "상세설비의 월별 건수·정지시간")
        fields = {"factory": "B6", "team": "D6", "asset": "F6", "module": "K6"}
        for key, cell in fields.items():
            self.selector(
                ws,
                cell,
                key,
                {
                    "factory": "공장",
                    "team": "팀",
                    "asset": "라인",
                    "module": "상세설비",
                }[key],
                ALL,
                span={"asset": 3, "module": 2}.get(key, 1),
            )
        ws.merge_cells("A8:L8")
        self.b.put(ws, 8, 1, "월별 고장 현황", role="title").font = Font(
            name="KoPubWorld돋움체 Medium", size=14, bold=True
        )
        self.header(
            ws,
            9,
            [
                "월",
                "건수",
                "정지(분)",
                "평균(분)",
                "시간 유효(건)",
                "분류 검토(건)",
                "전월 대비 건수",
                "전월 대비 정지(분)",
                "전년동월 대비 건수",
                "전년동월 대비 정지(분)",
                "기간 확인",
            ],
        )
        calendar = case_months(self.facts)
        cached = case_months(self.facts, calendar["period"])
        filters = self.filters(ws, fields)
        dates = self.facts.date.dropna()
        self.b.period_filter_range = self.filter_scope(filters)
        partial = set()
        if len(dates):
            first = (
                pd.Timestamp(self.b.r.options.date_from)
                if self.b.r.options.date_from
                else dates.min()
            )
            last = (
                pd.Timestamp(self.b.r.options.date_to) if self.b.r.options.date_to else dates.max()
            )
            if first.day != 1:
                partial.add(first.strftime("%Y-%m"))
            if last.day != last.days_in_month:
                partial.add(last.strftime("%Y-%m"))
        for index, item in enumerate(cached.to_dict("records")):
            row = 10 + index
            period = item["period"]
            begin = pd.Timestamp(period + "-01")
            finish = begin + pd.DateOffset(months=1)
            args = self.args(
                filters,
                [
                    (self.fact_range("date"), f'">="&DATE({begin.year},{begin.month},1)'),
                    (self.fact_range("date"), f'"<"&DATE({finish.year},{finish.month},1)'),
                ],
            )
            self.b.put(ws, row, 1, period, project=False)
            self.formula(ws, f"B{row}", self.count_formula(args), item["count"], "#,##0")
            self.formula(ws, f"E{row}", self.valid_formula(args), item["valid_count"], "#,##0")
            self.formula(
                ws, f"C{row}", self.time_formula(args, f"B{row}", f"E{row}"), item["total_minutes"]
            )
            self.formula(ws, f"D{row}", f'=IF(E{row}=0,"",C{row}/E{row})', item["mean_minutes"])
            self.formula(
                ws,
                f"F{row}",
                f"=SUMIFS({self.fact_range('review_count')},{args})",
                item["review_count"],
                "#,##0",
            )
            self.b.put(
                ws,
                row,
                11,
                "부분기간 가능" if period in partial else "",
                role="muted",
                project=False,
            )
            for lag, count_col, time_col in ((1, "G", "H"), (12, "I", "J")):
                if index < lag:
                    continue
                previous = cached.iloc[index - lag]
                comparable = period not in partial and previous["period"] not in partial
                self.formula(
                    ws,
                    f"{count_col}{row}",
                    f'=IF(OR(K{row}<>"",K{row - lag}<>""),"",B{row}-B{row - lag})',
                    item["count"] - previous["count"] if comparable else "",
                    '[Red]"▲ "#,##0;[Blue]"▼ "#,##0;0',
                )
                difference = (
                    item["total_minutes"] - previous["total_minutes"]
                    if comparable
                    and pd.notna(item["total_minutes"])
                    and pd.notna(previous["total_minutes"])
                    else ""
                )
                self.formula(
                    ws,
                    f"{time_col}{row}",
                    f'=IF(OR(K{row}<>"",K{row - lag}<>"",C{row}="",C{row - lag}=""),"",C{row}-C{row - lag})',
                    difference,
                    '[Red]"▲ "#,##0.0;[Blue]"▼ "#,##0.0;0.0',
                )
            ws.row_dimensions[row].height = 22
        end = 9 + len(cached)
        self.table_borders(ws, 9, max(10, end), 1, 11)
        chart_row = max(23, end + 3)
        for value, anchor, title, unit in (
            (2, "A", "월별 발생 건수", "건"),
            (3, "G", "월별 정지시간", "분"),
        ):
            self.chart(ws, 10, end, 1, value, f"{anchor}{chart_row}", title, unit, line=True)
        if cached.empty:
            self.b.put(ws, 10, 1, "날짜가 있는 고장 기록이 없습니다.", role="muted")
        last = chart_row + 14
        self.note(
            ws,
            last,
            "시간 미기재는 빈칸, 해당 기록이 없는 달은 0. 날짜 미상은 추이에서 제외. 첫·마지막 부분기간의 증감 비교는 공란.",
        )
        ws.print_area = f"A1:L{last + 2}"

    def build(self):
        self.prepare()
        self.organization()
        self.comparison()
        self.trends()
