from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.views import Selection

from core.equipment_breakdown import type_breakdown
from core.equipment_names import (
    active_name_mapping,
    effective_name_source,
    equipment_catalog,
    organization_catalog,
    resolve_group,
)
from core.fault_components import mode_label
from core.i18n import DISPLAY, UNMATCHED, K
from core.issue_analysis import issue_summary
from core.models import AnalysisResult, Progress, UserError, noop_progress
from core.parsing import is_missing
from core.preprocessing import review_target
from core.report_view import ReportNames
from core.rules import RULE_COLUMNS
from core.sorting import descending
from report.cache import FormulaCache
from report.charts import chart_png, donut_png
from report.classification import (
    COMPONENT_FIELDS,
    DECISION_FIELDS,
    classification_principles,
    classification_result,
    classification_review_count,
    component_principles,
)
from report.formatting import bounded_int
from report.issue_workbook import ISSUE_SHEETS, IssueWorkbook, report_issue_facts
from report.locked_template import LOCKED_SHEETS, apply_locked_template, restore_template_charts
from report.output import atomic_output
from report.workbook_layout import apply_workbook_layout
from version import VERSION

SHEETS = {
    "summary": "01.종합현황",
    **ISSUE_SHEETS,
    "review": "별첨. 검토·분류현황",
    "detail": "별첨. 고장이력",
    "fault_detail": "별첨. 부품증상상세",
    "cross": "별첨. 제품교차분석",
    "source_review": "별첨. 원본 검토표시",
}
DETAIL_COLS = [
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
    "part_group",
    "middle",
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
            "repair_actions",
            "classification_known_fields",
        )
    ),
    "line_code",
    "raw_line_name",
    "equipment_group",
    "factory",
    "team",
    "classification_candidates",
    "classification_known_fields",
]
D = {k: get_column_letter(i + 1) for i, k in enumerate(DETAIL_COLS)}
REVIEW_COLS = [
    "source_row",
    "date",
    "line",
    "registered",
    "target",
    "raw_big",
    "raw_mid",
    "raw_small",
    "equipment",
    "product",
    "minutes",
    "type",
    "status",
    "raw_description",
    "normalized",
    "major",
    "detail_equipment",
    "part_group",
    "middle",
    "minor",
    "repair_actions",
    "candidates",
]
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
FILL = "F1F3F5"
TEAL = "166A70"
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
        self.source_loaded = result.loaded
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
        self._breakdowns: dict[str, pd.DataFrame] = {}
        self._donut_png: dict[str, bytes] = {}
        self.donut_top_n = bounded_int(result.config_snapshot["settings"].get("donut_top_n"), 5, 10)
        self.data = descending(self.r.selected, "minutes")
        self.issue_types = issue_summary(report_issue_facts(self.r.selected), ["case"]).rename(
            columns={"case": "module_part"}
        )
        self.sections = set(
            result.config_snapshot["settings"].get("report_sections", SHEETS.keys())
        )
        self.sections.discard("product")
        # Accept saved section choices from reports before consolidation.
        for old, destinations in {
            "equipment_types": ("equipment",),
            "pareto": ("equipment", "type", "cross"),
            "component_trend": ("component",),
            "top": ("detail",),
            "quality": ("review",),
            "rules": ("review",),
            "names": ("review",),
        }.items():
            if old in self.sections:
                self.sections.update(destinations)
        self.sections.difference_update(("type", "component", "component_trend", "raw"))
        self.sections.update(("summary", "detail", "review", "source_review"))
        self.start = 7
        self.end = max(7, 6 + len(self.data))
        self.raw_helpers = {}

    def close(self):
        """Release workbook and chart resources even when generation fails."""
        try:
            self.wb.close()
        finally:
            for buffer in self.images:
                buffer.close()
            self.images.clear()
            self._donut_png.clear()
            self._breakdowns.clear()

    def equipment_breakdown(self, equipment: str) -> pd.DataFrame:
        if equipment not in self._breakdowns:
            self._breakdowns[equipment] = type_breakdown(self.data, equipment)
        return self._breakdowns[equipment]

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

    def filter_table(self, ws, name, row, last, span):
        if last <= row:
            return
        table = Table(displayName=name, ref=f"A{row}:{get_column_letter(span)}{last}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)

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

    def detail(self, key="detail", frame=None):
        if key == "review":
            return self.review(frame)
        frame = self.data if frame is None else descending(frame, "minutes")
        ws = self.new_sheet(key, span=12)
        ws.merge_cells("A5:L5")
        self.put(
            ws,
            5,
            1,
            f"정지시간 내림차순. 시간 값이 있는 상위 {self.r.options.top_n}건을 연한 노랑으로 표시합니다. "
            "전체 이력은 필터로 조회하며, 분류·설정 변경 후에는 보고서를 다시 생성하세요."
            if key == "detail"
            else "검토 중에도 출력할 수 있습니다.",
            role="muted",
        )
        ws.row_dimensions[5].height = 34
        self.header(ws, 6, [self.display_header(c) for c in DETAIL_COLS])
        for index, record in enumerate(frame.to_dict("records"), 7):
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
                if name in ("component_count", "part_count"):
                    c.number_format = INT
                if name == "date":
                    c.number_format = "yyyy-mm-dd"
            ws.row_dimensions[index].height = decision_row_height(record)
            if (
                key == "detail"
                and index < 7 + self.r.options.top_n
                and not is_missing(record.get("minutes"))
            ):
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
            "component_details",
            "classification_candidates",
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
                    "component_details",
                    "classification_candidates",
                )
                else 40
            )
        ws.column_dimensions[D["source_row"]].width = 11
        ws.column_dimensions[D["minutes"]].width = 18
        ws.column_dimensions[D["record_id"]].hidden = True
        ws.column_dimensions[D["event_id"]].hidden = True
        ws.column_dimensions[D["classification_known_fields"]].hidden = True
        if self.r.metrics["product_count"] == 0:
            ws.column_dimensions[D["product"]].hidden = True
        ws.freeze_panes = "G7"
        ws.auto_filter.ref = f"A6:{D[DETAIL_COLS[-1]]}{max(6, 6 + len(frame))}"
        ws.print_area = f"B1:L{max(7, 6 + len(frame))}"
        if frame.empty:
            self.put(
                ws, 7, 2, "검토필요 이력 없음" if key == "review" else K["empty"], role="muted"
            )
        return ws

    def review(self, frame):
        frame = descending(frame, "minutes")
        ws = self.new_sheet("review", span=len(REVIEW_COLS))
        last_column = get_column_letter(len(REVIEW_COLS))
        ws.merge_cells(f"A5:{last_column}5")
        self.put(
            ws,
            5,
            1,
            "정지시간 내림차순. 검토 중에도 출력할 수 있습니다. "
            "품질 집계·분석 조건은 11_기준정보, 이력 ID·상세 근거는 07_고장이력에서 확인하세요.",
            role="muted",
        )
        ws.row_dimensions[5].height = 32
        self.header(ws, 6, [self.display_header(name) for name in REVIEW_COLS])
        widths = {
            "source_row": 11,
            "date": 14,
            "minutes": 18,
            "type": 40,
            "raw_description": 48,
            "normalized": 48,
            "candidates": 48,
            "repair_actions": 30,
        }
        for column, name in enumerate(REVIEW_COLS, 1):
            ws.column_dimensions[get_column_letter(column)].width = widths.get(name, 26)
        for row, record in enumerate(frame.to_dict("records"), 7):
            for column, name in enumerate(REVIEW_COLS, 1):
                cell = self.put(
                    ws,
                    row,
                    column,
                    record.get(name),
                    role="raw"
                    if name.startswith("raw_")
                    else "review"
                    if name == "status"
                    else "derived",
                )
                if name == "date":
                    cell.number_format = "yyyy-mm-dd"
                elif name == "minutes":
                    cell.number_format = NUM
            ws.row_dimensions[row].height = decision_row_height(
                record, widths={"raw_description": 48, "normalized": 48, "candidates": 48}
            )
        if frame.empty:
            self.put(ws, 7, 1, "검토필요 이력 없음", role="muted")
        ws.freeze_panes = "D7"
        ws.auto_filter.ref = f"A6:{last_column}{max(6, 6 + len(frame))}"
        ws.print_area = f"A1:{last_column}{max(7, 6 + len(frame))}"
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
        row: int = 6,
        auto_filter: bool = True,
        period_freq: str | None = None,
    ):
        table = (
            table.sort_values("period", kind="stable").reset_index(drop=True)
            if period_freq
            else descending(table, "total_minutes")
        )
        cols = keys + STAT_KEYS
        self.header(ws, row, [DISPLAY.get(k, k) for k in cols])
        end = row
        for offset, record in enumerate(table.to_dict("records"), row + 1):
            end = offset
            matching = self.data
            for key in keys:
                if key == "period":
                    continue
                matching = matching.loc[matching[key].eq(record[key])]
            args = []
            if period_freq:
                period = str(record["period"])
                begin = pd.Timestamp(
                    period + "-01-01"
                    if period_freq == "year"
                    else period + "-01"
                    if period_freq == "month"
                    else period
                )
                finish = begin + (
                    pd.DateOffset(years=1)
                    if period_freq == "year"
                    else pd.DateOffset(months=1)
                    if period_freq == "month"
                    else timedelta(days=7 if period_freq == "week" else 1)
                )
                args = [
                    self.range("date"),
                    f'">="&DATE({begin.year},{begin.month},{begin.day})',
                    self.range("date"),
                    f'"<"&DATE({finish.year},{finish.month},{finish.day})',
                ]
                matching = matching.loc[matching.date.ge(begin) & matching.date.lt(finish)]
            else:
                for key in keys:
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
        if auto_filter and len(table):
            ws.auto_filter.ref = f"A{row}:{get_column_letter(len(cols))}{end}"
        ws.print_area = f"A1:{get_column_letter(len(cols))}{max(end, 8)}"
        return end + 3

    def raw(self):
        # Only two quality-control inputs remain; the source workbook is separate.
        ws = self.wb.create_sheet("_source_quality")
        ws.append(["kind", "minutes"])
        for record in self.r.all_records.to_dict("records"):
            ws.append([cell_value(record.get("kind")), cell_value(record.get("minutes"))])
        for row in ws:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        ws.sheet_state = "hidden"

    def quality(self, ws, row):
        row = self.section(ws, row, "데이터 품질 및 분석 조건", span=8)
        ws.column_dimensions["A"].hidden = False
        ws.column_dimensions["A"].width = 32
        items = [
            ("Source file", self.r.loaded.path.name),
            ("Source sheet", self.r.loaded.sheet),
            ("SHA256", self.r.loaded.file_hash),
            ("Header row", self.r.loaded.header_row),
            ("Profile", self.r.loaded.profile),
            ("Version", VERSION),
            ("Report generated", datetime.now().isoformat(timespec="seconds")),
            ("Config SHA256", self.r.config_hash),
            (K["source_period"], self.r.metrics["source_period"]),
            (K["period"], self.r.metrics["period"]),
            (K["raw_rows"], self.r.metrics["source_rows"]),
            (K["analyzed_rows"], self.r.metrics["selected_rows"]),
            (K["excluded_rows"], self.r.metrics["excluded_rows"]),
            ("Duration unit", self.r.options.duration_unit),
            (K["basis"], K[self.r.options.equipment_basis]),
            (
                K["factory_filter"],
                self.r.options.factory
                if self.r.options.factory is not None
                else K["all_factories"],
            ),
            (
                K["team_filter"],
                self.r.options.team if self.r.options.team is not None else K["all_teams"],
            ),
            ("Deduplicate", str(self.r.options.deduplicate)),
            (
                "Personal columns omitted",
                str(self.r.config_snapshot["settings"].get("omit_personal_columns", True)),
            ),
        ]
        for label, value in items:
            self.put(ws, row, 1, label, role="muted")
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
            self.put(
                ws,
                row,
                2,
                value,
                role="raw",
                project=label not in (K["factory_filter"], K["team_filter"]),
            )
            ws.row_dimensions[row].height = 23
            row += 1
        row += 2
        self.header(ws, row, [K["kind"], K["count"], K["total"]])
        row += 1
        last = max(2, 1 + len(self.r.all_records))
        kr = f"'_source_quality'!$A$2:$A${last}"
        dr = f"'_source_quality'!$B$2:$B${last}"
        for item in self.r.tables["raw_kind"].to_dict("records"):
            self.put(ws, row, 1, item["kind"])
            self.formula(ws, row, 2, f"=COUNTIF({kr},{criteria(item['kind'])})", item["count"], INT)
            self.formula(
                ws,
                row,
                3,
                f'=IF(COUNTIFS({kr},{criteria(item["kind"])},{dr},"<>")=0,"",SUMIF({kr},{criteria(item["kind"])},{dr}))',
                item["total_minutes"],
            )
            row += 1
        row += 2
        self.header(ws, row, [K["quality"], K["count"]])
        row += 1
        target_label = (
            K["target_missing"]
            if review_target(self.r.config_snapshot["settings"], self.r.options)
            else K["target_info"]
        )
        quality_rows = [
            (K["auto"], "auto_rows", True),
            (K.get("partial", "부분분류"), "partial_rows", True),
            ("자동처리 합계(완전+부분)", "auto_processed_rows", False),
            (K["manual"], "manual_rows", True),
            (K["code_missing"], "code_missing_rows", True),
            (K["rule_unmatched"], "rule_unmatched_rows", True),
            (K["review"], "ambiguous_rows", True),
            ("상세설비 미상", "missing_detail_equipment_rows", False),
            ("세부 부품 미기재", "missing_part_rows", False),
            (K["multiple_fault_rows"], "multiple_fault_rows", False),
            (K["alternative_type_rows"], "alternative_type_rows", False),
            (K["auto_resolved_rows"], "auto_resolved_rows", False),
            (target_label, "missing_target_rows", False),
            (K["duplicate"], "duplicate_candidate_rows", False),
            (K["review_tab"] + "(중복 제거)", "review_rows", False),
        ]
        if self.r.metrics.get("legacy_classification_rows"):
            quality_rows.append(("이전 분석결과(재분석 필요)", "legacy_classification_rows", False))
        for label, field, is_status in sorted(
            quality_rows, key=lambda item: self.r.metrics.get(item[1], 0), reverse=True
        ):
            self.put(ws, row, 1, label)
            if is_status:
                formula = f"=COUNTIF({self.range('status')},{criteria(label)})"
                if field == "manual_rows":
                    formula += f"+COUNTIF({self.range('status')},{criteria(K.get('manual_multi', '복수유형확정'))})"
                self.formula(
                    ws,
                    row,
                    2,
                    formula,
                    classification_review_count(self.r)
                    if field == "ambiguous_rows"
                    else self.r.metrics.get(field, 0),
                    INT,
                )
            else:
                self.put(ws, row, 2, self.r.metrics.get(field, 0), fmt=INT)
            row += 1
        row += 2
        for note in [
            *self.r.notes,
            *classification_principles(),
            *component_principles(),
            "\ubcf4\uace0\uc11c \uc804\uccb4\uc758 \ub4f1\ub85d \uc124\ube44 \ucf54\ub4dc\ub294 \uc9c0\uc815\ud55c \uc774\ub984\uc73c\ub85c \ubcc0\ud658\ud568. \uc5c5\ub85c\ub4dc\ud55c \uc6d0\ubcf8 \ud30c\uc77c\uc740 \ubcc0\uacbd \uc5c6\uc74c.",
            "동일 상세설비 비교 별첨의 비중은 현재 선택한 상세설비·세부부품·공장·팀 범위의 전체 건수 또는 정지시간=100%. 차트는 상위 10개 라인만 표시하고 기타로 합산하지 않으며, 나머지 라인은 아래 표에서 개별 확인. 미기재 항목도 분모에 포함.",
            "02~04와 동일 상세설비 비교 별첨은 입력칸 변경 시 표·차트 갱신. 01의 이미지와 기간별 차트는 생성 시점 자료이며 분류·표준화 규칙 변경 후에는 재생성 필요.",
        ]:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
            self.put(ws, row, 1, note, role="review")
            ws.row_dimensions[row].height = 33
            row += 1
        row += 2
        self.header(ws, row, ["Field", K["mapping"]])
        row += 1
        for key, value in self.r.loaded.mapping.items():
            if key == "product_name" and not value:
                continue
            self.put(ws, row, 1, key)
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
            self.put(ws, row, 2, value or K["unmapped"], role="raw")
            row += 1
        row += 2
        self.header(ws, row, [K["row"], K["skipped"]])
        row += 1
        for item in self.r.loaded.skipped:
            self.put(ws, row, 1, item["row"])
            self.put(ws, row, 2, item["reason"])
            row += 1
        row += 2
        self.header(ws, row, ["Config snapshot", "JSON"])
        row += 1
        for key in (
            "settings",
            "normalization",
            "equipment_aliases",
            "product_aliases",
            "equipment_families",
            "equipment_names",
        ):
            self.put(ws, row, 1, key)
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
            self.put(
                ws, row, 2, json.dumps(self.r.config_snapshot[key], ensure_ascii=False), role="raw"
            )
            ws.row_dimensions[row].height = 65
            row += 1
        ws.print_area = f"A1:L{row}"

    def names(self):
        store = self.r.config_snapshot.get("equipment_names", {})
        source = effective_name_source(self.source_loaded, store)
        ws = self.new_sheet("criteria", "설비명 및 분류 기준정보", span=len(RULE_COLUMNS))
        ws.merge_cells(start_row=5, start_column=1, end_row=5, end_column=len(RULE_COLUMNS))
        self.put(
            ws,
            5,
            1,
            "설비명·공장·팀 연결표와 아래 부품 식별 규칙은 분석 시점의 설정입니다. 변경은 프로그램에서 저장한 뒤 보고서를 다시 생성하세요.",
            role="muted",
        )
        ws.row_dimensions[5].height = 34
        headers = [
            "라인코드(변환)" if source == "line" else "설비코드(변환)",
            "원본 라인명(변환)" if source == "line" else "등록 설비명(변환)",
            K["report_equipment"],
            K["equipment_group"],
            K["factory"],
            K["team"],
            K["status"],
            "Last saved",
        ]
        self.header(ws, 6, headers)
        catalog = {
            r["code"]: r["raw_name"] for r in equipment_catalog(self.source_loaded, source=source)
        }
        mapping = active_name_mapping(self.source_loaded, store)
        automatic = organization_catalog(self.source_loaded, source=source)
        organization = store.get("organization", {}).get(source, {})
        codes = sorted(set(catalog) | set(mapping) | set(organization))
        for row, code in enumerate(codes, 7):
            name = mapping.get(code, code)
            assigned = organization.get(code, {})
            values = [
                code,
                catalog.get(code, ""),
                name,
                resolve_group(name, store.get("grouping", {})),
                assigned.get("factory") or automatic.get(code, {}).get("factory") or K["missing"],
                assigned.get("team") or K["missing"],
                K["configured"] if code in mapping else K["code_fallback"],
                store.get("updated_at") or "Initial configuration",
            ]
            for col, value in enumerate(values, 1):
                self.put(
                    ws,
                    row,
                    col,
                    value,
                    "input" if col == 3 else "raw",
                    project=col not in (4, 5, 6),
                )
            ws.row_dimensions[row].height = 42
        for col, width in zip("ABCDEFGH", [22, 42, 26, 24, 24, 24, 24, 32]):
            ws.column_dimensions[col].width = width
        ws.auto_filter.ref = f"A6:H{max(6, 6 + len(codes))}"
        row = max(9, 10 + len(codes))
        equipment_types = self.r.config_snapshot.get("classification_catalog", {}).get(
            "equipment_types", []
        )
        if equipment_types:
            row = self.section(ws, row, "상세설비 표준명과 별칭", span=len(RULE_COLUMNS))
            self.header(ws, row, ["상세설비", "원문 별칭"])
            for item in equipment_types:
                row += 1
                self.put(ws, row, 1, item["name"], role="raw")
                self.put(ws, row, 2, ", ".join(item.get("aliases", [])), role="raw")
                ws.row_dimensions[row].height = 42
            row += 3
        public = self.r.config_snapshot.get("classification_catalog", {}).get("public_taxonomy", {})
        if public:
            row = self.section(ws, row, "표준 고장 분야·현상·조치", span=len(RULE_COLUMNS))
            self.header(ws, row, ["구분", "표준 선택 목록"])
            for label, key in (
                ("고장 분야", "domains"),
                ("고장 현상", "modes"),
                ("별도 조치", "actions"),
            ):
                row += 1
                self.put(ws, row, 1, label, role="raw")
                ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
                self.put(ws, row, 2, ", ".join(public.get(key, [])), role="raw")
                ws.row_dimensions[row].height = 60 if key == "modes" else 42
            row += 3
            row = self.section(ws, row, "표준 부품군과 세부 부품", span=len(RULE_COLUMNS))
            self.header(ws, row, ["부품군", "세부 부품", "원문 별칭"])
            for part in public.get("parts", []):
                row += 1
                self.put(ws, row, 1, part["family"], role="raw")
                self.put(ws, row, 2, part["name"], role="raw")
                self.put(ws, row, 3, ", ".join(part.get("aliases", [])), role="raw")
                ws.row_dimensions[row].height = 42
            row += 3
        self.rules(ws, row)

    def rules(self, ws, row):
        keys = RULE_COLUMNS
        row = self.section(
            ws, row, "부품 식별 규칙 · 긴 조건식은 셀을 선택해 수식 입력줄에서 확인", span=len(keys)
        )
        labels = {"major": "분야", "middle": "부품군", "minor": "부품 종류"}
        self.header(ws, row, [labels.get(key, key) for key in keys])
        for index, rule in enumerate(self.r.config_snapshot["rules"], row + 1):
            for col, key in enumerate(keys, 1):
                cell = self.put(ws, index, col, rule.get(key, ""), role="raw")
                if key in ("context", "symptom", "exclude"):
                    cell.alignment = Alignment(vertical="center", wrap_text=False)
            ws.row_dimensions[index].height = 45
        for i, key in enumerate(keys, 1):
            dimension = ws.column_dimensions[get_column_letter(i)]
            dimension.width = max(
                dimension.width, 42 if key in ("minor", "context", "symptom", "exclude") else 22
            )
        last = get_column_letter(len(keys))
        end = row + len(self.r.config_snapshot["rules"])
        self.filter_table(ws, "ClassificationRules", row, end, len(keys))
        ws.print_area = f"A1:{last}{end}"

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
            row = self.stats(ws, self.r.tables[tablekey], keys, row + 1, False)
        self.pareto(ws, "product", row)

    @staticmethod
    def display_header(key):
        # Codes remain available in the original workbook and in the name editor,
        # not in this human-readable report projection.
        return {
            "classification_candidates": "검토 후보 목록(순위·근거 JSON)",
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

    def add_donut(self, ws, anchor, equipment, table, width=970, height=335):
        if equipment not in self._donut_png:
            with donut_png(
                table, equipment, top_n=self.donut_top_n, company_style=True
            ) as rendered:
                self._donut_png[equipment] = rendered.getvalue()
        # openpyxl closes each image stream while saving, so each placement owns one.
        buffer = BytesIO(self._donut_png[equipment])
        self.images.append(buffer)
        image = Image(buffer)
        image.width = width
        image.height = height
        ws.add_image(image, anchor)

    def equipment_types(self, ws, row):
        """One equipment's chart + full ranked table, then the next beneath it."""
        row = self.section(ws, row, "설비별 고장유형 구성비와 전체 순위", span=12)
        for column in ("J", "K", "L"):
            ws.column_dimensions[column].width = 20
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
        self.put(
            ws,
            row,
            1,
            f"상위 {self.donut_top_n}개 유형 + 기타. 전체 유형을 생략 없이 표시합니다. 건수 내림차순 / 동률 시 정지시간순. 비중은 설비 내부 기준이며 K·L열은 전체 분석 기준입니다. 비가동코드 미기입·규칙 미일치 포함.",
            role="muted",
        )
        ws.row_dimensions[row].height = 34
        row += 2
        for number, equipment in enumerate(self.r.tables["equipment"]["equipment"], 1):
            table = self.equipment_breakdown(equipment)
            selected = self.data.loc[self.data.equipment.eq(equipment)]
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
            cell = self.put(ws, row, 1, f"{number:02d}  {equipment}", role="title")
            cell.font = Font(name=FONT, size=17, bold=True, color=DARK)
            ws.row_dimensions[row].height = 33
            row += 1
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
            total_minutes = selected.minutes.sum(min_count=1)
            time_text = (
                f"{total_minutes:,.0f}\ubd84"
                if pd.notna(total_minutes)
                else "\uc815\ubcf4 \uc5c6\uc74c"
            )
            self.put(
                ws,
                row,
                1,
                f"\uc804\uccb4 {len(selected):,}\uac74  |  \uc720\ud615 {len(table):,}\uac1c  |  \uc815\uc9c0\uc2dc\uac04 {time_text}  |  \uc2dc\uac04 \ubbf8\uae30\uc7ac {selected.minutes.isna().sum():,}\uac74",
                role="muted",
            )
            ws.row_dimensions[row].height = 24
            row += 1
            for r in range(row, row + 17):
                ws.row_dimensions[r].height = 20
            self.add_donut(ws, f"A{row}", equipment, table, width=1000, height=342)
            row += 18
            labels = [
                "\uace0\uc7a5\uc720\ud615",
                "\uac74\uc218",
                "\uac74\uc218 \ube44\uc911",
                "\ub204\uc801 \ube44\uc911",
                "\uc815\uc9c0\uc2dc\uac04(\ubd84)",
                "\uc2dc\uac04 \ube44\uc911",
                "\ud3c9\uade0 \uc815\uc9c0(\ubd84)",
                "\uc2dc\uac04 \uc720\ud6a8 \uac74\uc218",
                "\uc21c\uc704",
                "최대 정지(분)",
                "전체 분석 건수 비중",
                "전체 분석 시간 비중",
            ]
            self.header(ws, row, labels)
            first = row + 1
            last = row + len(table)
            total_row = last + 1
            for r, item in enumerate(table.to_dict("records"), first):
                cond = f"{self.range('equipment')},{criteria(equipment)},{self.range('type')},{criteria(item['type'])}"
                self.put(ws, r, 9, item["rank"], fmt=INT)
                self.put(ws, r, 1, item["type"])
                self.formula(ws, r, 2, f"=COUNTIFS({cond})", item["count"], INT)
                self.formula(ws, r, 3, f"=IFERROR(B{r}/$B${total_row},0)", item["count_share"], PCT)
                cumulative = table.loc[: r - first, "count"].sum() / len(selected)
                self.formula(
                    ws, r, 4, f"=IFERROR(SUM($B${first}:B{r})/$B${total_row},0)", cumulative, PCT
                )
                self.formula(
                    ws,
                    r,
                    8,
                    f'=COUNTIFS({cond},{self.range("minutes")},">=0",{self.range("minutes")},"<>")',
                    item["valid_count"],
                    INT,
                )
                self.formula(
                    ws,
                    r,
                    5,
                    f'=IF(H{r}=0,"",SUMIFS({self.range("minutes")},{cond}))',
                    item["total_minutes"],
                )
                self.formula(
                    ws,
                    r,
                    6,
                    f'=IF(OR(H{r}=0,$E${total_row}=0),"",E{r}/$E${total_row})',
                    item["time_share"],
                    PCT,
                )
                self.formula(ws, r, 7, f'=IF(H{r}=0,"",E{r}/H{r})', item["mean_minutes"])
                matching = selected.loc[selected.type.eq(item["type"])]
                formula, value = self.max_formula(matching)
                self.formula(ws, r, 10, formula, value)
                self.formula(
                    ws,
                    r,
                    11,
                    f"=IFERROR(B{r}/COUNTA({self.range('record_id')}),0)",
                    item["count"] / len(self.data),
                    PCT,
                )
                self.formula(
                    ws,
                    r,
                    12,
                    f'=IF(OR(H{r}=0,SUM({self.range("minutes")})=0),"",E{r}/SUM({self.range("minutes")}))',
                    item["total_minutes"] / self.r.metrics["total_minutes"]
                    if item["valid_count"] and self.r.metrics["total_minutes"]
                    else "",
                    PCT,
                )
                if (r - first) % 2:
                    for c in ws[r][:12]:
                        c.fill = PatternFill("solid", fgColor=FILL)
                ws.row_dimensions[r].height = 35
            self.put(ws, total_row, 1, "\ud569\uacc4")
            self.formula(ws, total_row, 2, f"=SUM(B{first}:B{last})", len(selected), INT)
            self.formula(
                ws,
                total_row,
                3,
                f"=IFERROR(SUM(C{first}:C{last}),0)",
                1 if len(selected) else 0,
                PCT,
            )
            self.formula(
                ws, total_row, 8, f"=SUM(H{first}:H{last})", int(selected.minutes.count()), INT
            )
            self.formula(
                ws, total_row, 5, f'=IF(H{total_row}=0,"",SUM(E{first}:E{last}))', total_minutes
            )
            self.formula(
                ws,
                total_row,
                6,
                f'=IF(OR(H{total_row}=0,E{total_row}=0),"",SUM(F{first}:F{last}))',
                1 if pd.notna(total_minutes) and total_minutes > 0 else "",
                PCT,
            )
            self.formula(
                ws,
                total_row,
                7,
                f'=IF(H{total_row}=0,"",E{total_row}/H{total_row})',
                selected.minutes.mean(),
            )
            for c in ws[total_row][:12]:
                c.fill = PatternFill("solid", fgColor=FILL)
                c.font = Font(name=FONT, size=10, bold=True, color=DARK)
                c.border = Border(top=Side(style="thin", color="ABB3BA"))
            ws.row_dimensions[total_row].height = 28
            row = total_row + 3
            ws.merge_cells(start_row=row - 2, start_column=1, end_row=row - 2, end_column=12)
            self.put(
                ws,
                row - 2,
                1,
                "\ucc28\ud2b8\uc758 \uae30\ud0c0=\uc0c1\uc704 \uc720\ud615 \uc678 \ub098\uba38\uc9c0. \uc0c1\uc138\ud45c\ub294 \uc0dd\ub7b5 \uc5c6\uc74c. % \ud569\uacc4\ub294 \ubc18\uc62c\ub9bc\uc73c\ub85c \ud45c\uc2dc\uc0c1 100%\uc640 \ubbf8\uc138\ud55c \ucc28\uc774 \uac00\ub2a5.",
                role="muted",
            )
            ws.row_dimensions[row - 2].height = 27
        if self.r.tables["equipment"].empty:
            self.put(ws, row, 1, K["empty"], role="review")
        ws.print_area = f"A1:N{max(row, 8)}"
        return row + 2

    def component_statistics(self, key: str, table: pd.DataFrame, ws=None, row=6):
        """Render the validated event-membership snapshot without allocating downtime."""
        monthly = key == "component_trend"
        columns = [
            "component_type",
            "count",
            "manual_count",
            "review_count",
            "count_share",
        ] + (["period"] if monthly else [])
        labels = {
            "period": "월",
            "component_type": "포함된 부품·고장유형",
            "count": "유형 포함 고장기록(건)",
            "manual_count": "사용자확정(건)",
            "review_count": "잠정 검토(건)",
            "count_share": "해당 월 전체 고장기록 대비 비율"
            if monthly
            else "전체 고장기록 대비 비율",
        }
        span = len(columns)
        if ws is None:
            ws = self.new_sheet("component", "부품별 발생 및 월별 추이", span=6)
            ws.merge_cells("A5:F5")
            self.put(
                ws,
                5,
                1,
                "집계 스냅샷(정적표): 최종 단일 부품으로 분류된 고장기록 수. 미확정 후보는 집계하지 않으며, 비율 분모에는 전체 고장기록을 포함합니다. 변경 후에는 보고서를 다시 생성하세요.",
                role="muted",
            )
            ws.row_dimensions[5].height = 34
        else:
            row = self.section(ws, row, "월별 부품 발생 추이", span=6)
        self.header(ws, row, [labels[column] for column in columns])
        records = table.to_dict("records")
        for number, record in enumerate(records, row + 1):
            for col, name in enumerate(columns, 1):
                fmt = (
                    PCT
                    if name == "count_share"
                    else INT
                    if name in ("count", "manual_count", "review_count")
                    else None
                )
                self.put(ws, number, col, record.get(name), fmt=fmt)
            ws.row_dimensions[number].height = 42
        last = row + len(records)
        if not records:
            self.put(ws, row + 1, 1, K["empty"], role="review")
            last = row + 1
        if records:
            self.filter_table(ws, "MonthlyComponents" if monthly else "Components", row, last, span)
        for index, column in enumerate(columns, 1):
            ws.column_dimensions[get_column_letter(index)].width = (
                66 if column == "component_type" else 26 if column == "count_share" else 23
            )
        if not monthly and "component_trend" in self.r.tables:
            return self.component_statistics(
                "component_trend", self.r.tables["component_trend"], ws, last + 3
            )
        notes = component_principles()
        for number, note in enumerate(notes, last + 3):
            ws.merge_cells(start_row=number, start_column=1, end_row=number, end_column=6)
            self.put(ws, number, 1, note, role="muted")
            ws.row_dimensions[number].height = 42
        ws.print_area = f"A1:F{last + 2 + len(notes)}"

    def fault_details(self, table: pd.DataFrame):
        """One displayed row per event, with failure and action kept separate."""
        columns = [
            "record_id",
            "date",
            "equipment",
            "line",
            "major",
            "detail_equipment",
            "part_group",
            "middle",
            "minor",
            "repair_actions",
            "status",
            "description",
            "evidence",
            "actions",
            "event_id",
        ]
        visible = len(columns) - 1
        last_column = get_column_letter(visible)
        ws = self.new_sheet("fault_detail", title="상세설비·부품·고장 현상 상세", span=visible)
        ws.merge_cells(f"A5:{last_column}5")
        self.put(
            ws,
            5,
            1,
            "한 고장이력당 한 행을 보존합니다. 고장 분야 / 상세설비·모듈 / 부품군 / 세부 부품 / 고장 현상과 별도 조치를 표시합니다. "
            "미확정 기록은 최종 분류를 비워 두고 상태와 후보 근거를 확인합니다.",
            role="muted",
        )
        ws.row_dimensions[5].height = 34
        self.header(ws, 6, [self.display_header(key) for key in columns])
        records = table.to_dict("records")
        for number, record in enumerate(records, 7):
            for column, key in enumerate(columns, 1):
                cell = self.put(ws, number, column, record.get(key))
                if key == "date":
                    cell.number_format = "yyyy-mm-dd"
            ws.row_dimensions[number].height = min(
                220,
                max(
                    48,
                    14
                    * max(
                        3,
                        len(str(record.get("description", ""))) // 42 + 1,
                        len(str(record.get("evidence", ""))) // 27 + 1,
                    ),
                ),
            )
        if not records:
            self.put(ws, 7, 1, K["empty"], role="muted")
        last = max(7, 6 + len(records))
        ws.auto_filter.ref = f"A6:{last_column}{last}"
        widths = {"description": 55, "evidence": 38, "repair_actions": 30, "actions": 28}
        for index, key in enumerate(columns, 1):
            ws.column_dimensions[get_column_letter(index)].width = widths.get(key, 23)
        ws.column_dimensions[get_column_letter(len(columns))].hidden = True
        ws.freeze_panes = "E7"
        ws.print_area = f"A1:{last_column}{last}"

    def detailed_equipment(self, ws, row):
        """Preserved module facts remain useful without a complete part path."""
        table = self.r.tables.get("detailed_equipment", pd.DataFrame())
        row = self.section(ws, row, "라인·상세설비별 고장이력 (확인된 항목 기준)", span=9)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        self.put(
            ws,
            row,
            1,
            "부품 미기재·검토 중인 기록도 확인된 상세설비에 포함합니다. 검토 중인 부품 후보를 확정 고장으로 합산하지 않습니다. 미확인 설비는 미상으로 표시하며 이력·정지시간은 각각 한 번 집계합니다. 변경 후 보고서를 다시 생성하세요.",
            role="muted",
        )
        ws.row_dimensions[row].height = 42
        row += 2
        columns = [
            "line",
            "detail_equipment",
            "count",
            "count_share",
            "total_minutes",
            "valid_count",
            "review_count",
        ]
        self.header(
            ws,
            row,
            [
                "라인",
                "상세설비·모듈",
                "고장이력(건)",
                "전체 고장이력 비율",
                "정지시간(분)",
                "시간 기재(건)",
                "분류 검토 중(건)",
            ],
        )
        for number, record in enumerate(table.to_dict("records"), row + 1):
            for column, key in enumerate(columns, 1):
                self.put(
                    ws,
                    number,
                    column,
                    record[key],
                    fmt=PCT
                    if key == "count_share"
                    else INT
                    if key in ("count", "valid_count", "review_count")
                    else None,
                )
            ws.row_dimensions[number].height = 32
        last = row + max(1, len(table))
        if table.empty:
            self.put(ws, last, 1, K["empty"], role="review")
        if not table.empty:
            self.filter_table(ws, "DetailedEquipment", row, last, len(columns))
        ws.print_area = f"A1:R{last}"

    def build(self, progress: Progress = noop_progress):
        self.detail()
        progress(25, K["exporting"])
        if "summary" in self.sections:
            self.summary()
        issues = IssueWorkbook(self)
        issues.build()
        progress(55, K["exporting"])
        if "cross" in self.sections and self.r.metrics["product_count"]:
            self.crosses()
        from report.review_overview import build_review_overview

        build_review_overview(self)
        if "fault_detail" in self.r.tables:
            self.fault_details(self.r.tables["fault_detail"])
        # A clean current report only: no obsolete sheets from previous versions.
        order = {name: i for i, name in enumerate(SHEETS.values())}
        self.wb._sheets.sort(key=lambda ws: order.get(ws.title, 999))
        department = str(
            self.r.config_snapshot.get("final_report", {}).get("department", "")
        ).strip()
        apply_workbook_layout(
            self.wb, self.cache, author=department or "확인 필요", exclude_sheets=LOCKED_SHEETS
        )
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
