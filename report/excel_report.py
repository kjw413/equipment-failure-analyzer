from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.views import Selection

from core.component_analysis import final_component
from core.equipment_names import active_name_mapping
from core.fault_components import mode_label
from core.i18n import DISPLAY, UNMATCHED, K
from core.models import AnalysisResult, Progress, UserError, noop_progress
from core.parsing import is_missing
from core.report_view import ReportNames
from core.sorting import descending
from report.cache import FormulaCache
from report.charts import chart_png
from report.classification import COMPONENT_FIELDS, DECISION_FIELDS, classification_result
from report.issue_workbook import ISSUE_SHEETS, IssueWorkbook
from report.locked_template import LOCKED_SHEETS, apply_locked_template, restore_template_charts
from report.output import atomic_output
from report.workbook_layout import apply_workbook_layout
from version import VERSION

SHEETS = {
    "summary": "01.종합현황",
    **ISSUE_SHEETS,
    "review": "별첨. 검토·분류현황",
    "detail": "별첨. 고장이력",
    "cross": "별첨. 제품교차분석",
    "source_review": "별첨. 원본 검토표시",
}
_DETAIL_DATA_FIELDS = [
    "record_id",
    "source_row",
    "date",
    "line",
    "registered",
    "target",
    "equipment",
    "product",
    "minutes",
    "type",
    "status",
    "normalized",
    "raw_description",
    "major",
    "detail_equipment",
    "minor",
    "repair_actions",
    "evidence",
    "candidates",
    "issues",
    "review_reason",
    "review_action",
    "aggregation_effect",
    "raw_big",
    "raw_mid",
    "raw_small",
    "start",
    "end",
    "elapsed_minutes",
    "duration_delta",
    "duration_source",
    "equipment_basis",
    "family",
    "raw_cause",
    "raw_action",
    "source_sheet",
    "event_id",
    "duplicate",
    "equipment_code",
    "raw_equipment_name",
    "report_equipment",
    "name_mapped",
    *DECISION_FIELDS,
    *(
        field
        for field in COMPONENT_FIELDS
        if field
        not in (
            "classification_schema",
            "part_group",
            "part_count",
            "component_details",
            "combination_key",
            "repair_actions",
            "classification_known_fields",
        )
    ),
    "line_code",
    "raw_line_name",
    "equipment_group",
    "factory",
    "team",
]
VISIBLE_DETAIL_COLS = (
    "date",
    "factory",
    "team",
    "report_equipment",
    "detail_equipment",
    "minor",
    "minutes",
    "normalized",
    "raw_description",
    "repair_actions",
    "status",
    "review_reason",
    "review_action",
    "evidence",
    "major",
    "source_row",
)
DETAIL_COLS = [
    *VISIBLE_DETAIL_COLS,
    *(field for field in _DETAIL_DATA_FIELDS if field not in VISIBLE_DETAIL_COLS),
    "recorded_actions",
    "fault_detail_evidence",
]
D = {k: get_column_letter(i + 1) for i, k in enumerate(DETAIL_COLS)}
STAT_KEYS = [
    "count",
    "count_share",
    "valid_count",
    "total_minutes",
    "mean_minutes",
    "max_minutes",
    "time_share",
    "top_type",
]
FONT = "Malgun Gothic"
DARK = "303942"
MUTED = "65717D"
ORANGE = "AD6817"
GREEN = "237245"
NUM = "#,##0;-#,##0"
INT = "#,##0"
PCT = "0.0%"


def sheet_ref(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def literal(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def criteria(value: str) -> str:
    return literal("=" + str(value).replace("~", "~~").replace("*", "~*").replace("?", "~?"))


def cell_value(value):
    if is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def decision_row_height(record, widths=None, minimum=42):
    """Show wrapped rule reasons and candidates without making every row tall."""
    widths = widths or {"classification_reason": 46, "candidate_evidence": 46}
    lines = 1
    for field, width in widths.items():
        value = record.get(field)
        if is_missing(value):
            continue
        count = sum(
            max(
                1,
                math.ceil(
                    sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line) / width
                ),
            )
            for line in str(value).splitlines()
        )
        lines = max(lines, count)
    return min(409, max(minimum, lines * 13 + 8))


class ReportBuilder:
    def __init__(self, result: AnalysisResult):
        self.names_view = ReportNames(
            active_name_mapping(result.loaded, result.config_snapshot.get("equipment_names", {})),
            protected=[
                value
                for field in ("equipment_group", "factory", "team")
                for value in result.all_records.get(field, [])
            ],
        )
        self.r = classification_result(result)
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.wb.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True, forceFullCalc=True)
        self.cache = FormulaCache()
        self.images = []
        self.helper = None
        self.data = descending(self.r.selected, "minutes")
        # The saved Pareto setting still enables the optional product appendix.
        sections = result.config_snapshot["settings"].get("report_sections", SHEETS)
        self.include_product_cross = bool({"cross", "pareto"}.intersection(sections))
        self.start = 7
        self.end = max(7, 6 + len(self.data))

    def close(self):
        """Release workbook and chart resources even when generation fails."""
        try:
            self.wb.close()
        finally:
            for buffer in self.images:
                buffer.close()
            self.images.clear()

    def new_sheet(self, key: str, title: str | None = None, span: int = 10):
        ws = self.wb.create_sheet(SHEETS.get(key, key))
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.print_options.horizontalCentered = True
        ws.oddFooter.center.text = "Page &P / &N"
        ws.oddFooter.right.text = f"EFA {VERSION}"
        ws.sheet_properties.outlinePr.summaryRight = False
        for col in range(1, span + 1):
            ws.column_dimensions[get_column_letter(col)].width = 16
        ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=span)
        self.put(ws, 1, 1, title or ws.title.split("_", 1)[-1], role="title")
        ws.row_dimensions[1].height = 28
        ws.row_dimensions[2].height = 20
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=span)
        scope = K["fault_only"] if self.r.options.scope == "fault" else K["all_stops"]
        self.put(
            ws,
            3,
            1,
            f"{self.r.metrics['period']}   |   {scope}   |   {K[self.r.options.equipment_basis]}",
            role="muted",
        )
        ws.row_dimensions[3].height = 23
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=span)
        self.put(ws, 4, 1, self.r.loaded.path.name + " | " + self.r.loaded.sheet, role="muted")
        ws.row_dimensions[4].height = 22
        ws.freeze_panes = "B7"
        ws.print_title_rows = "1:6"
        return ws

    def put(
        self,
        ws,
        row: int,
        col: int,
        value,
        role: str = "derived",
        fmt: str | None = None,
        *,
        project: bool = True,
    ):
        v = cell_value(self.names_view.text(value) if project else value)
        if isinstance(v, str):
            v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v)[:32767]
        c = ws.cell(row, col, v)
        if isinstance(v, str):
            c.data_type = "s"  # protect untrusted cells from formula injection
        color = {
            "raw": GREEN,
            "muted": MUTED,
            "input": "2155A0",
            "review": ORANGE,
            "title": DARK,
        }.get(role, "17212A")
        c.font = Font(
            name=FONT, size=22 if role == "title" else 10, color=color, bold=role == "title"
        )
        c.alignment = Alignment(vertical="center", wrap_text=True)
        if fmt:
            c.number_format = fmt
        elif isinstance(v, (datetime, pd.Timestamp)):
            c.number_format = "yyyy-mm-dd hh:mm"
        return c

    def formula(self, ws, row, col, formula, expected, fmt=NUM):
        c = self.cache.set(ws, f"{get_column_letter(col)}{row}", formula, expected)
        c.font = Font(name=FONT, size=10, color="17212A")
        c.number_format = fmt
        c.alignment = Alignment(vertical="center", horizontal="right")
        return c

    def header(self, ws, row, labels):
        for col, label in enumerate(labels, 1):
            c = self.put(ws, row, col, label)
            c.fill = PatternFill("solid", fgColor=DARK)
            c.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 32

    def section(self, ws, row, title, span=9):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
        self.put(ws, row, 1, title, role="title").font = Font(
            name=FONT, size=14, bold=True, color=DARK
        )
        ws.row_dimensions[row].height = 32
        return row + 1

    def range(self, field):
        return f"{sheet_ref(SHEETS['detail'])}!${D[field]}${self.start}:${D[field]}${self.end}"

    def add_image(
        self,
        ws,
        anchor,
        table,
        key,
        metric="total_minutes",
        kind="bar",
        width=650,
        height=360,
        *,
        company_style=True,
    ):
        buffer = chart_png(
            table, key, metric, kind, self.r.options.top_n, company_style=company_style
        )
        self.images.append(buffer)
        image = Image(buffer)
        image.width = width
        image.height = height
        ws.add_image(image, anchor)

    def detail(self):
        frame = self.data
        span = len(VISIBLE_DETAIL_COLS)
        last_visible = get_column_letter(span)
        ws = self.new_sheet("detail", span=span)
        ws.merge_cells(f"A5:{last_visible}5")
        self.put(
            ws,
            5,
            1,
            f"정지시간 내림차순. 시간 값이 있는 상위 {self.r.options.top_n}건을 연한 노랑으로 표시합니다. "
            "전체 이력은 필터로 조회하며, 분류·설정 변경 후에는 보고서를 다시 생성하세요.",
            role="muted",
        )
        ws.row_dimensions[5].height = 34
        self.header(ws, 6, [self.display_header(c) for c in DETAIL_COLS])
        for index, record in enumerate(frame.to_dict("records"), 7):
            final = final_component(record) or {}
            record["recorded_actions"] = ", ".join(final.get("actions", ()))
            record["fault_detail_evidence"] = (
                final.get("symptom_evidence")
                or final.get("evidence")
                or record.get("candidate_evidence")
                or record.get("classification_reason")
            )
            for col, name in enumerate(DETAIL_COLS, 1):
                role = (
                    "review"
                    if name in ("issues", "status")
                    and record.get(name) in (K["review"], *UNMATCHED)
                    else "raw"
                    if name.startswith("raw_")
                    else "derived"
                )
                value = record.get(name)
                if name == "classification_mode" and not is_missing(value):
                    value = mode_label(value)
                c = self.put(ws, index, col, value, role)
                if name in ("minutes", "elapsed_minutes", "duration_delta"):
                    c.number_format = NUM
                if name == "component_count":
                    c.number_format = INT
                if name == "date":
                    c.number_format = "yyyy-mm-dd"
            ws.row_dimensions[index].height = decision_row_height(
                record,
                {
                    "normalized": 43,
                    "raw_description": 43,
                    "review_reason": 43,
                    "review_action": 43,
                    "evidence": 37,
                },
                minimum=22,
            )
            if index < 7 + self.r.options.top_n and not is_missing(record.get("minutes")):
                for cell in ws[index]:
                    cell.fill = PatternFill("solid", fgColor="FFF2CC")
        for name in DETAIL_COLS:
            ws.column_dimensions[D[name]].width = 22
        for name in (
            "equipment",
            "target",
            "registered",
            "type",
            "raw_description",
            "normalized",
            "candidates",
            "issues",
            "review_reason",
            "review_action",
            "aggregation_effect",
            "raw_mid",
            "raw_cause",
            "raw_action",
            "classification_reason",
            "candidate_evidence",
            "component_types",
        ):
            ws.column_dimensions[D[name]].width = (
                48
                if name
                in (
                    "raw_description",
                    "normalized",
                    "issues",
                    "candidates",
                    "review_reason",
                    "review_action",
                    "aggregation_effect",
                    "classification_reason",
                    "candidate_evidence",
                    "component_types",
                )
                else 40
            )
        ws.column_dimensions[D["source_row"]].width = 11
        ws.column_dimensions[D["minutes"]].width = 18
        for field in (
            "date",
            "factory",
            "team",
            "minor",
            "major",
            "status",
        ):
            ws.column_dimensions[D[field]].width = 16
        for name in DETAIL_COLS[len(VISIBLE_DETAIL_COLS) :]:
            ws.column_dimensions[D[name]].hidden = True
        ws.auto_filter.ref = f"A6:{D[DETAIL_COLS[-1]]}{max(6, 6 + len(frame))}"
        ws.print_area = f"A1:{last_visible}{max(7, 6 + len(frame))}"
        if frame.empty:
            self.put(ws, 7, 2, K["empty"], role="muted")
        return ws

    def max_formula(self, matching: pd.DataFrame):
        valid = matching.loc[matching.minutes.notna()]
        if valid.empty:
            return '=""', ""
        indices = sorted(int(i) + 7 for i in valid.index)
        segments = []
        start = prev = indices[0]
        for r in indices[1:]:
            if r == prev + 1:
                prev = r
            else:
                segments.append((start, prev))
                start = prev = r
        segments.append((start, prev))
        refs = [
            f"{sheet_ref(SHEETS['detail'])}!{D['minutes']}{a}"
            + (f":{D['minutes']}{b}" if b > a else "")
            for a, b in segments
        ]
        if len(refs) <= 100 and sum(map(len, refs)) < 7000:
            return "=MAX(" + ",".join(refs) + ")", float(valid.minutes.max())
        if self.helper is None:
            self.helper = self.wb.create_sheet("_calc")
            self.helper.sheet_state = "hidden"
        first = self.helper.max_row + 1
        for start in range(0, len(refs), 100):
            r = self.helper.max_row + 1
            chunk = segments[start : start + 100]
            values = [self.data.iloc[a - 7 : b - 6].minutes.max() for a, b in chunk]
            self.cache.set(
                self.helper,
                f"A{r}",
                "=MAX(" + ",".join(refs[start : start + 100]) + ")",
                max(values),
            )
        return f"=MAX('_calc'!A{first}:A{self.helper.max_row})", float(valid.minutes.max())

    def stats(
        self,
        ws,
        table: pd.DataFrame,
        keys: list[str],
        row: int,
    ):
        table = descending(table, "total_minutes")
        cols = keys + STAT_KEYS
        self.header(ws, row, [DISPLAY.get(k, k) for k in cols])
        end = row
        for offset, record in enumerate(table.to_dict("records"), row + 1):
            end = offset
            matching = self.data
            args = []
            for key in keys:
                matching = matching.loc[matching[key].eq(record[key])]
                args.extend([self.range(key), criteria(record[key])])
            condition = ",".join(args)
            for col, key in enumerate(keys, 1):
                self.put(ws, offset, col, record[key], role="raw")
            ix = {key: len(keys) + 1 + i for i, key in enumerate(STAT_KEYS)}

            def cr(key):
                return f"{get_column_letter(ix[key])}{offset}"

            self.formula(ws, offset, ix["count"], f"=COUNTIFS({condition})", record["count"], INT)
            self.formula(
                ws,
                offset,
                ix["count_share"],
                f"=IFERROR({cr('count')}/COUNTA({self.range('record_id')}),0)",
                record["count"] / max(1, len(self.data)),
                PCT,
            )
            valid = float(record["valid_count"])
            self.formula(
                ws,
                offset,
                ix["valid_count"],
                f'=COUNTIFS({condition},{self.range("minutes")},">=0",{self.range("minutes")},"<>")',
                valid,
                INT,
            )
            sum_formula = (
                f'=IF({cr("valid_count")}=0,"",SUMIFS({self.range("minutes")},{condition}))'
            )
            self.formula(
                ws,
                offset,
                ix["total_minutes"],
                sum_formula,
                record["total_minutes"] if valid else "",
            )
            self.formula(
                ws,
                offset,
                ix["mean_minutes"],
                f'=IF({cr("valid_count")}=0,"",{cr("total_minutes")}/{cr("valid_count")})',
                record["mean_minutes"],
            )
            f, v = self.max_formula(matching)
            self.formula(ws, offset, ix["max_minutes"], f, v)
            self.formula(
                ws,
                offset,
                ix["time_share"],
                f'=IF(OR({cr("valid_count")}=0,SUM({self.range("minutes")})=0),"",{cr("total_minutes")}/SUM({self.range("minutes")}))',
                record["total_minutes"] / self.r.metrics["total_minutes"]
                if valid and self.r.metrics["total_minutes"]
                else "",
                PCT,
            )
            self.put(ws, offset, ix["top_type"], record.get("top_type", ""))
            if (offset - row) % 2 == 0:
                for c in ws[offset][: len(cols)]:
                    c.fill = PatternFill("solid", fgColor="F7F8FA")
            ws.row_dimensions[offset].height = 35 if len(keys) == 1 else 48
        if len(table) == 0:
            self.put(ws, row + 1, 1, K["empty"], role="review")
            end = row + 2
        for i, key in enumerate(cols, 1):
            ws.column_dimensions[get_column_letter(i)].width = (
                42 if key in keys or key == "top_type" else 18
            )
        ws.print_area = f"A1:{get_column_letter(len(cols))}{max(end, 8)}"
        return end + 3

    def summary(self):
        ws = self.new_sheet(
            "summary", self.r.config_snapshot["settings"].get("report_title", K["report"]), span=12
        )
        for col in range(1, 13):
            ws.column_dimensions[get_column_letter(col)].width = 11.5
        # Compact, formula-backed totals follow the user's renewed report layout.
        metrics = (
            (1, 4, f"=COUNTA({self.range('record_id')})", len(self.data), '"고장 건수 "#,##0"건"'),
            (
                5,
                8,
                f'=IF(COUNT({self.range("minutes")})=0,"",SUM({self.range("minutes")}))',
                self.r.metrics["total_minutes"],
                '"정지시간 "#,##0"분"',
            ),
            (
                9,
                12,
                f'=IF(COUNT({self.range("minutes")})=0,"",AVERAGE({self.range("minutes")}))',
                self.r.metrics["mean_minutes"],
                '"평균 정지시간 "#,##0"분"',
            ),
        )
        for left, right, formula, expected, fmt in metrics:
            ws.merge_cells(start_row=6, start_column=left, end_row=6, end_column=right)
            cell = self.formula(ws, 6, left, formula, expected, fmt)
            cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells("A7:L7")
        self.put(
            ws,
            7,
            1,
            f"완전 자동분류 {self.r.metrics['auto_rows']:,}건   "
            f"부분 자동분류 {self.r.metrics.get('partial_rows', 0):,}건   "
            f"검토 대상 {self.r.metrics['review_rows']:,}건",
        )
        ws.print_area = "A1:H41"
        ws.page_setup.orientation = "portrait"
        ws.page_setup.fitToHeight = 1

    def pareto(self, ws, key, row):
        row = self.section(ws, row, "개선 우선순위 · 건수와 정지시간의 누적 기여도")
        keys = [key]
        for key in keys:
            table = self.r.tables[key]
            if table.empty:
                self.put(ws, row, 1, K["empty"], role="review")
                row += 3
                continue
            for metric in ("count", "total_minutes"):
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
                self.put(
                    ws,
                    row,
                    1,
                    f"{K[key]} / {K['count'] if metric == 'count' else K['total']}",
                    role="muted",
                )
                self.header(
                    ws,
                    row + 1,
                    [
                        K[key],
                        K["count"] if metric == "count" else K["total"],
                        K["count_share"] if metric == "count" else K["time_share"],
                        K["cumulative"],
                    ],
                )
                first = row + 2
                ordered = descending(table, metric)
                denom = ordered[metric].sum(min_count=1)
                running = 0.0
                for n, record in enumerate(ordered.to_dict("records"), first):
                    self.put(ws, n, 1, record[key], role="raw")
                    args = f"{self.range(key)},{criteria(record[key])}"
                    if metric == "count":
                        f = f"=COUNTIF({args})"
                    else:
                        f = f'=IF(COUNTIFS({args},{self.range("minutes")},"<>")=0,"",SUMIF({args},{self.range("minutes")}))'
                    self.formula(ws, n, 2, f, record[metric], INT if metric == "count" else NUM)
                    valid = pd.notna(record[metric])
                    running += float(record[metric]) if valid else 0
                    end = first + len(ordered) - 1
                    self.formula(
                        ws,
                        n,
                        3,
                        f'=IF(OR(B{n}="",SUM($B${first}:$B${end})=0),"",B{n}/SUM($B${first}:$B${end}))',
                        float(record[metric]) / denom if valid and denom else "",
                        PCT,
                    )
                    self.formula(
                        ws,
                        n,
                        4,
                        f'=IF(SUM($B${first}:$B${end})=0,"",SUM($B${first}:B{n})/SUM($B${first}:$B${end}))',
                        running / denom if denom else "",
                        PCT,
                    )
                    ws.row_dimensions[n].height = 37
                chart_row = first + len(ordered) + 1
                self.add_image(
                    ws, f"A{chart_row}", ordered, key, metric, kind="pareto", width=650, height=350
                )
                row = chart_row + 16
        ws.print_area = f"A1:L{row}"
        return row

    def crosses(self):
        ws = self.new_sheet("cross", "제품별 교차분석", span=11)
        row = 6
        sections = [
            ("product_type", ["product", "type"]),
            ("equipment_product", ["equipment", "product"]),
            ("triple", ["equipment", "product", "type"]),
        ]
        for tablekey, keys in sections:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
            self.put(ws, row, 1, " x ".join(K[k] for k in keys), role="title").font = Font(
                name=FONT, size=14, bold=True, color=DARK
            )
            row = self.stats(ws, self.r.tables[tablekey], keys, row + 1)
        self.pareto(ws, "product", row)

    @staticmethod
    def display_header(key):
        # Codes remain available in the original workbook and in the name editor,
        # not in this human-readable report projection.
        return {
            "recorded_actions": "기록된 조치",
            "fault_detail_evidence": "고장 현상 근거",
            "line_code": "라인명(코드 변환)",
            "raw_line_name": "원본 라인명(변환)",
            "equipment_code": "\uc124\ube44\uba85(\ucf54\ub4dc \ubcc0\ud658)",
            "raw_equipment_name": "\ub4f1\ub85d \uc124\ube44\uba85(\ubcc0\ud658)",
            "registered": "\ub4f1\ub85d \uc124\ube44(\ubcc0\ud658)",
            "raw_description": "\uace0\uc7a5\ub0b4\uc6a9(\uc124\ube44\uba85 \ubcc0\ud658)",
            "normalized": "고장내용(표준화 후)",
            "equipment": "분석 라인",
            "report_equipment": "보고서 라인명",
        }.get(key, DISPLAY.get(key, key))

    def build(self, progress: Progress = noop_progress):
        self.detail()
        progress(25, K["exporting"])
        self.summary()
        issues = IssueWorkbook(self)
        issues.build()
        progress(55, K["exporting"])
        if self.include_product_cross and self.r.metrics["product_count"]:
            self.crosses()
        from report.review_overview import build_review_overview

        review = build_review_overview(self)
        appendix_row_heights = {
            sheet.title: {
                row: dim.height
                for row, dim in sheet.row_dimensions.items()
                if row > range_boundaries(sheet.auto_filter.ref)[1]
            }
            for sheet in (review, self.wb[SHEETS["detail"]])
        }
        # A clean current report only: no obsolete sheets from previous versions.
        order = {name: i for i, name in enumerate(SHEETS.values())}
        self.wb._sheets.sort(key=lambda ws: order.get(ws.title, 999))
        department = str(
            self.r.config_snapshot.get("final_report", {}).get("department", "")
        ).strip()
        apply_workbook_layout(
            self.wb, self.cache, author=department or "확인 필요", exclude_sheets=LOCKED_SHEETS
        )
        for title, heights in appendix_row_heights.items():
            for row, height in heights.items():
                self.wb[title].row_dimensions[row].height = height
        apply_locked_template(self)
        from report.fault_comparison import install_fault_comparison

        install_fault_comparison(self)
        from report.drilldown import install_controls

        install_controls(self)
        from report.rank_layout import apply_rank_layout

        apply_rank_layout(self)
        from report.period_drilldown import install_period_view

        install_period_view(self)
        self.wb.active = 0
        for sheet in self.wb:
            sheet.sheet_view.tabSelected = sheet is self.wb.worksheets[0]
            sheet.freeze_panes = None
            sheet.sheet_view.selection = [Selection(activeCell="A1", sqref="A1")]
            sheet.sheet_view.topLeftCell = "A1"
        progress(80, K["exporting"])
        return self.wb


def export_report(
    result: AnalysisResult, path: str | Path, progress: Progress = noop_progress
) -> Path:
    p = Path(path).expanduser().resolve()
    if p.suffix.casefold() not in (".xlsx", ".xlsm"):
        p = p.with_suffix(".xlsm")
    if p == result.loaded.path.resolve():
        raise UserError(
            "\uc6d0\ubcf8 \ud30c\uc77c\uc740 \ub36e\uc5b4\uc4f8 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ub2e4\ub978 \uc774\ub984\uc744 \uc0ac\uc6a9\ud558\uc138\uc694."
        )
    builder = ReportBuilder(result)
    builder.macro_navigation = p.suffix.casefold() == ".xlsm"
    try:
        with atomic_output(p, prefix="efa_") as temp:
            wb = builder.build(progress)
            wb.save(temp)
            builder.cache.patch(temp)
            restore_template_charts(temp, builder)
            from report.source_appendix import append_source_review

            append_source_review(temp, result)
            if p.suffix.casefold() == ".xlsm":
                from report.search_project import embed_search_project

                embed_search_project(temp)
    except PermissionError as e:
        raise UserError(
            "\ubcf4\uace0\uc11c\uac00 Excel\uc5d0\uc11c \uc5f4\ub824 \uc788\uac70\ub098 \uc800\uc7a5 \uad8c\ud55c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \ub2e4\ub978 \uc774\ub984/\ud3f4\ub354\ub85c \uc800\uc7a5\ud558\uc138\uc694."
        ) from e
    finally:
        builder.close()
    progress(100, K["done"])
    return p
