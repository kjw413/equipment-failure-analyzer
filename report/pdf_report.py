"""Evidence-based management report, generated locally from AnalysisResult.

Tables and narratives use the same analysis snapshot as the Excel workbook.
No external AI, hidden causal inference or rate estimates are used.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Image, PageBreak, SimpleDocTemplate, Table, TableStyle

from core.equipment_breakdown import donut_slices, type_breakdown
from core.equipment_names import active_name_mapping
from core.i18n import K
from core.models import AnalysisResult, Progress, UserError, noop_progress
from core.preprocessing import review_target
from core.report_view import ReportNames
from report.charts import chart_png
from report.classification import (
    classification_principles,
    classification_result,
    classification_review_count,
    component_principles,
    evidence_excerpt,
)
from report.formatting import bounded_int, number, percent
from report.output import atomic_output
from report.pdf_layout import MUTED, RULE, Donut, Layout, Swatch, load_fonts
from version import VERSION


def brief_type(value: str) -> str:
    if str(value).startswith("복수 고장 / ") or " + " in str(value):
        return str(value)
    parts = str(value).split(" / ", 2)
    if len(parts) == 3:
        return parts[2] if parts[1] in parts[2] else " / ".join(parts[1:])
    return str(value)


def summary_findings(result: AnalysisResult) -> list[tuple[str, str]]:
    """Deterministic statements; ties and missing-time denominators are explicit."""
    m = result.metrics
    table = result.tables["equipment"]
    rows = []
    if table.empty:
        return [
            (
                "분석 범위",
                "선택한 조건에 해당하는 기록이 없습니다. 기간과 비가동 구분을 확인하세요.",
            )
        ]
    highest = int(table["count"].max())
    tied = table.loc[table["count"].eq(highest)]
    names = ", ".join(tied["equipment"].astype(str).head(3))
    if len(tied) > 3:
        names += f" 외 {len(tied) - 3}개"
    each = "각 " if len(tied) > 1 else ""
    rows.append(
        (
            "최다 기록 설비",
            f"{names}: {each}{highest:,}건 ({each}{highest / m['selected_rows']:.1%}). 전체 기록 건수 기준 비중입니다.",
        )
    )
    total = m["total_minutes"]
    if total is not None and total > 0:
        ranked = table.sort_values(
            ["total_minutes", "count", "equipment"],
            ascending=[False, False, True],
            na_position="last",
        )
        row = ranked.iloc[0]
        same = int(ranked["total_minutes"].eq(row["total_minutes"]).sum())
        tie = f" (동률 {same}개 중 하나)" if same > 1 else ""
        rows.append(
            (
                "최대 정지시간 설비",
                f"{row['equipment']}{tie}: {number(row['total_minutes'], 1)}분, 전체 유효 정지시간의 {row['total_minutes'] / total:.1%}.",
            )
        )
        n = min(3, len(ranked))
        share = ranked.head(n)["total_minutes"].sum() / total
        rows.append(
            (
                "정지시간 집중도",
                f"정지시간 상위 {n}개 설비의 비중은 {share:.1%}입니다. 점검 우선순위 검토용이며 고장률 비교는 아닙니다.",
            )
        )
    else:
        rows.append(
            ("정지시간 해석", "유효한 양수 정지시간 합계가 없어 시간 구성비는 산출하지 않았습니다.")
        )
    return rows


class FinalReport:
    def __init__(self, result: AnalysisResult):
        self.result = classification_result(result)
        self.names = ReportNames(
            active_name_mapping(result.loaded, result.config_snapshot.get("equipment_names", {})),
            protected=[
                value
                for field in ("equipment_group", "factory", "team")
                for value in result.all_records.get(field, [])
            ],
        )
        self.settings = result.config_snapshot.get("final_report", {})
        self.fonts = load_fonts(self.settings.get("font_path", ""))
        self.width = A4[0] - 88
        self.layout = Layout(self.fonts, self.width)
        self.story = []
        self.buffers: list[BytesIO] = []
        self.created = datetime.now().astimezone()
        default = (
            "설비 고장 최종 분석보고서"
            if result.options.scope == "fault"
            else "설비 비가동 최종 분석보고서"
        )
        self.title = self.names.text(self.settings.get("title", "").strip() or default)
        self.top_n = bounded_int(self.settings.get("summary_top_n"), 5, 10)
        self.donut_n = bounded_int(result.config_snapshot["settings"].get("donut_top_n"), 5, 5)

    def p(self, text, style="body"):
        return self.layout.p(self.names.text(text), style)

    def page(self, title):
        if self.story:
            self.story.append(PageBreak())
        self.story.append(self.layout.heading(self.names.text(title)))

    def header_footer(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(44, A4[1] - 30, A4[0] - 44, A4[1] - 30)
        canvas.setFillColor(MUTED)
        canvas.setFont(self.fonts.regular, 7.5)
        canvas.drawString(44, A4[1] - 22, "EQUIPMENT FAILURE ANALYSIS")
        canvas.drawRightString(A4[0] - 44, A4[1] - 22, f"v{VERSION}")
        canvas.line(44, 34, A4[0] - 44, 34)
        canvas.drawString(44, 22, f"{self.created:%Y-%m-%d}  |  사내 검토용 / 입력 기록 기반")
        canvas.drawRightString(A4[0] - 44, 22, f"{doc.page}")
        canvas.restoreState()

    def overview(self):
        r = self.result
        m = r.metrics
        layout = self.layout
        self.story += [self.p("FINAL ANALYSIS REPORT", "eyebrow"), self.p(self.title, "title")]
        scope = K["fault_only"] if r.options.scope == "fault" else K["all_stops"]
        self.story.append(self.p(f"분석기간  {m['period']}  |  범위  {scope}", "muted"))
        metadata = "  |  ".join(
            x
            for x in (self.settings.get("department", ""), self.settings.get("prepared_by", ""))
            if x
        )
        if metadata:
            self.story.append(self.p(metadata, "muted"))
        self.story.append(
            layout.kpis(
                [
                    ("분석 기록(건)", number(m["selected_rows"])),
                    ("정지시간(분)", number(m["total_minutes"], 1)),
                    ("평균 정지(분)", number(m["mean_minutes"], 1)),
                    ("분석 대상(개)", number(m["equipment_count"])),
                ]
            )
        )
        self.story.append(self.p("01  핵심 분석결과", "h2"))
        self.story.append(
            layout.table(
                ["구분", "분석 요약"],
                [list(item) for item in summary_findings(r)],
                [115, self.width - 115],
            )
        )
        self.story.append(self.p("02  분석 범위 및 자료", "h2"))
        rows = [
            ["원천 파일", self.names.text(r.loaded.path.name)],
            ["원천 시트", self.names.text(r.loaded.sheet)],
            ["설비 집계 기준", K[r.options.equipment_basis]],
            [
                "데이터 선별",
                f"원본 유효 행 {m['source_rows']:,} / 분석 행 {m['selected_rows']:,} / 제외 행 {m['excluded_rows']:,}",
            ],
            [
                "정지시간 유효성",
                f"유효 {m['valid_time_rows']:,}건 / 미기재·유효값 없음 {m['selected_rows'] - m['valid_time_rows']:,}건",
            ],
        ]
        for field in ("factory", "team"):
            selected = getattr(r.options, field)
            if selected is not None:
                rows.append([K[field + "_filter"], selected])
            if field in r.selected:
                values = sorted(
                    {
                        str(value)
                        for value in r.selected[field].dropna()
                        if str(value).strip() and value != K["missing"]
                    }
                )
                if values:
                    rows.append([K[field], ", ".join(values)])
        self.story.append(layout.table(["항목", "적용 기준"], rows, [115, self.width - 115]))
        self.story.append(
            layout.callout(
                "해석 유의: 건수는 기록 수이며, 정지시간은 기록별 유효값의 합계입니다. 동시 정지를 제거한 공장 순정지시간이 아닙니다. 원인 확정과 고장률·MTBF·MTTR 산출은 포함하지 않습니다."
            )
        )

    def components(self):
        table = self.result.tables.get("component")
        if table is None or table.empty:
            return
        self.page("03-1  부품별 발생 참고")
        for principle in component_principles():
            self.story.append(self.p(principle, "muted"))
        self.story.append(self.p(f"유형 포함 고장기록 TOP {self.top_n}", "h2"))
        rows = []
        for row in table.head(self.top_n).to_dict("records"):
            rows.append(
                [
                    row.get("component_type", ""),
                    number(row.get("count")),
                    number(row.get("manual_count")),
                    number(row.get("review_count")),
                    percent(row.get("count_share")),
                ]
            )
        self.story.append(
            self.layout.table(
                ["부품·고장유형", "포함 기록", "사용자확정", "잠정 검토", "전체 고장 대비"],
                rows,
                [243, 58, 67, 65, self.width - 433],
                (1, 2, 3, 4),
            )
        )
        self.story.append(
            self.p(
                "부품별 정지시간은 배분하지 않습니다. 부품 건수·월별 발생은 Excel 16·17 시트, 부품·증상별 전체 분류는 18 시트에서 확인합니다.",
                "small",
            )
        )

    def fault_details(self):
        table = self.result.tables.get("fault_detail")
        if table is None or table.empty:
            return
        self.page("03-2  부품·증상별 분류")
        self.story.append(
            self.p(
                "한 고장이력을 분야 / 부품 종류 / 증상으로 나눈 분류입니다. "
                "같은 기록 ID의 행들은 하나의 사건이며 정지시간을 중복 배분하지 않습니다.",
                "muted",
            )
        )
        self.story.append(
            self.p(
                "교체·점검·조정은 증상과 별도로 기록합니다. 조치만 있는 기록은 '증상 미기재'로 표시합니다.",
                "muted",
            )
        )
        rows = [
            [
                row.get("record_id", ""),
                row.get("equipment", ""),
                row.get("major", ""),
                row.get("middle", ""),
                row.get("minor", ""),
                row.get("actions", ""),
            ]
            for row in table.to_dict("records")
        ]
        self.story.append(
            self.layout.table(
                ["기록 ID", "설비", "분야", "부품 종류", "증상", "조치"],
                rows,
                [55, 97, 67, 110, 85, self.width - 414],
            )
        )

    def comparisons(self):
        r = self.result
        layout = self.layout
        self.page("03  설비·고장유형 종합 비교")
        self.story.append(self.p("설비별 정지시간 순위", "h2"))
        self.story.append(
            self.p("유효 정지시간 합계 내림차순. 시간 정보가 없는 설비는 하단 표시.", "muted")
        )
        rows = []
        for i, row in enumerate(r.tables["equipment"].to_dict("records"), 1):
            rows.append(
                [
                    str(i),
                    row["equipment"],
                    number(row["count"]),
                    number(row["total_minutes"], 1),
                    percent(row["time_share"]),
                    number(row["mean_minutes"], 1),
                ]
            )
        self.story.append(
            layout.table(
                ["순위", "설비", "건수", "정지(분)", "시간 비중", "평균(분)"],
                rows,
                [38, 148, 47, 91, 86, self.width - 410],
                (0, 2, 3, 4, 5),
            )
        )
        self.story.append(self.p(f"전체 표준 고장유형 TOP {self.top_n}", "h2"))
        self.story.append(
            self.p(
                "정지시간 기준. 유형명은 입력 문장의 표준화 결과이며 고장 원인을 확정한 결과가 아닙니다.",
                "muted",
            )
        )
        rows = []
        for i, row in enumerate(r.tables["type"].head(self.top_n).to_dict("records"), 1):
            rows.append(
                [
                    str(i),
                    brief_type(row["type"]),
                    number(row["count"]),
                    number(row["total_minutes"], 1),
                    percent(row["time_share"]),
                ]
            )
        self.story.append(
            layout.table(
                ["순위", "표준 고장유형", "건수", "정지(분)", "시간 비중"],
                rows,
                [38, 232, 47, 94, self.width - 411],
                (0, 2, 3, 4),
            )
        )
        self.story.append(
            layout.callout(
                "검토 관점: 기록 건수가 많은 항목과 장시간 정지를 동반한 항목을 구분해 보아야 합니다. 가동시간·생산량이 다른 설비의 본질적 성능 차이로 해석하지 않습니다."
            )
        )

    def monthly(self):
        r = self.result
        layout = self.layout
        table = r.tables["trend_month"]
        self.page("04  월별 발생 추이")
        self.story.append(self.p("월별 유효 정지시간 합계", "h2"))
        if not table.empty:
            buffer = chart_png(table, "period", "total_minutes", "trend")
            self.buffers.append(buffer)
            self.story.append(Image(buffer, width=self.width, height=self.width * 4.1 / 7.4))
        rows = [
            [
                row["period"],
                number(row["count"]),
                number(row["total_minutes"], 1),
                number(row["mean_minutes"], 1),
                number(row["valid_count"]),
            ]
            for row in table.to_dict("records")
        ]
        self.story.append(self.p("표: 정지시간 합계 내림차순 | 추이 그래프: 날짜순", "small"))
        monthly_table = layout.table(
            ["월", "기록(건)", "정지(분)", "평균(분)", "시간 유효(건)"],
            rows,
            [95, 92, 112, 104, self.width - 403],
            (1, 2, 3, 4),
        )
        monthly_table.setStyle(
            TableStyle(
                [("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
            )
        )
        self.story.append(monthly_table)
        self.story.append(
            self.p(
                f"날짜 없음·형식 오류 {r.metrics['date_missing_rows']:,}건은 추이에서 제외됩니다. 첫 달과 마지막 달은 부분 기간일 수 있습니다.",
                "muted",
            )
        )
        self.story.append(
            layout.callout(
                "이 그래프는 입력된 기록의 변화를 표시합니다. 월별 가동시간과 생산량을 보정하지 않았으며, 기록 0건은 무고장을 확정하는 의미가 아닙니다."
            )
        )

    def equipment(self, name: str, index: int, total_groups: int):
        r = self.result
        layout = self.layout
        table = type_breakdown(r.selected, name)
        selected = r.selected.loc[r.selected["equipment"].eq(name)]
        self.page(f"05  설비별 상세 분석  |  {index}/{total_groups}")
        self.story.append(self.p(name, "title"))
        total = selected["minutes"].sum(min_count=1)
        self.story.append(
            layout.kpis(
                [
                    ("기록(건)", number(len(selected))),
                    ("정지(분)", number(total, 1)),
                    ("고장유형(개)", str(len(table))),
                    ("시간 유효(건)", number(selected["minutes"].count())),
                ]
            )
        )
        self.story.append(self.p("고장유형 구성비  |  해당 설비 전체 건수=100%", "h2"))
        slices = donut_slices(table, "count", self.donut_n)
        legend = []
        for i, row in enumerate(slices.to_dict("records")):
            legend.append(
                [
                    Swatch(i),
                    self.p(brief_type(row["type"]), "cell"),
                    self.p(f"{number(row['value'])}건 ({percent(row['share'])})", "cell"),
                ]
            )
        legend_table = Table(
            legend or [["", self.p("기록 없음"), ""]],
            colWidths=[17, self.width - 278, 88],
            hAlign="LEFT",
            splitByRow=1,
            splitInRow=1,
        )
        legend_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        donut = Donut(slices["share"].tolist(), number(len(selected)), self.fonts)
        if legend_table.wrap(self.width - 173, A4[1])[1] > 350:
            # A long combination legend must flow across pages, outside the chart's single row.
            self.story.extend([donut, legend_table])
        else:
            chart = Table([[donut, legend_table]], colWidths=[173, self.width - 173])
            chart.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            self.story.append(chart)
        self.story.append(
            self.p(
                f"상위 {self.donut_n}개 + 기타. 비가동코드 미기입·규칙 미일치·검토필요 기록도 전체 건수에 포함. 반올림으로 % 합계는 미세한 차이 가능.",
                "small",
            )
        )
        self.story.append(self.p("유형별 주요 순위", "h2"))
        rows = []
        limit = bounded_int(self.settings.get("equipment_table_top_n"), 5, 10)
        display = table.head(limit).to_dict("records")
        if len(table) > limit:
            remaining = table.iloc[limit:]
            time = remaining["total_minutes"].sum(min_count=1)
            display.append(
                {
                    "rank": "-",
                    "type": f"기타 (나머지 {len(remaining)}개 유형)",
                    "count": int(remaining["count"].sum()),
                    "count_share": float(remaining["count_share"].sum()),
                    "total_minutes": time,
                    "time_share": time / total if pd.notna(total) and total > 0 else None,
                }
            )
        display.append(
            {
                "rank": "-",
                "type": "합계",
                "count": len(selected),
                "count_share": 1.0 if len(selected) else 0,
                "total_minutes": total,
                "time_share": 1.0 if pd.notna(total) and total > 0 else None,
            }
        )
        for row in display:
            rows.append(
                [
                    str(row["rank"]),
                    brief_type(row["type"]),
                    number(row["count"]),
                    percent(row["count_share"]),
                    number(row["total_minutes"], 1),
                    percent(row["time_share"]),
                ]
            )
        self.story.append(
            layout.table(
                ["순위", "고장유형", "건수", "건수 %", "정지(분)", "시간 %"],
                rows,
                [38, 213, 41, 66, 83, self.width - 441],
                (0, 2, 3, 4, 5),
            )
        )
        self.story.append(
            self.p(
                f"PDF는 상위 {limit}개 + 기타를 표시하며, 전체 유형은 Excel에 수록. 순위: 건수 내림차순, 동일 건수는 정지시간·유형명 순. 시간 %의 분모는 해당 설비의 유효 정지시간 합계.",
                "small",
            )
        )

    def actions(self):
        r = self.result
        layout = self.layout
        m = r.metrics
        self.page("06  관리 검토사항")
        self.story.append(self.p("정지시간 기준 우선 확인 대상", "h2"))
        self.story.append(
            self.p(
                "아래는 데이터 기반 검토 제안입니다. 고장 원인·조치 완료·담당자·일정을 자동 확정하지 않습니다.",
                "muted",
            )
        )
        rows = []
        n = bounded_int(self.settings.get("priority_equipment_n"), 3, 5)
        for row in (
            r.tables["equipment"]
            .loc[r.tables["equipment"]["total_minutes"].gt(0)]
            .head(n)
            .to_dict("records")
        ):
            table = type_breakdown(r.selected, row["equipment"])
            top = table.sort_values("total_minutes", ascending=False, na_position="last").iloc[0]
            evidence = f"{number(row['total_minutes'], 1)}분 / {percent(row['time_share'])}\n시간 상위 유형: {brief_type(top['type'])}"
            rows.append(
                [
                    row["equipment"],
                    evidence,
                    "원기록·정비이력 대조. 고장부위와 실제 조치내용을 확인한 뒤 재발방지 항목 수립.",
                ]
            )
        self.story.append(
            layout.table(["대상", "선정 근거", "확인 제안"], rows, [94, 208, self.width - 302])
        )
        self.story.append(self.p("장시간 정지 기록 TOP 3", "h2"))
        rows = []
        for row in (
            r.tables["long_stops"]
            .loc[r.tables["long_stops"]["minutes"].notna()]
            .head(3)
            .to_dict("records")
        ):
            date = "-" if pd.isna(row["date"]) else f"{row['date']:%Y-%m-%d}"
            raw = str(row.get("raw_description", ""))
            if len(raw) > 125:
                raw = raw[:125] + " [이하 Excel 참조]"
            rows.append([date, row["equipment"], number(row["minutes"], 1), raw])
        self.story.append(
            layout.table(
                ["발생일", "설비", "정지(분)", "기록 내용(발췌)"],
                rows,
                [80, 93, 68, self.width - 241],
                (2,),
            )
        )
        note = self.settings.get("closing_note", "").strip()
        if note:
            self.story.append(self.p("사용자 입력 의견", "h2"))
            self.story.append(layout.callout(self.names.text(note)))
        if self.settings.get("include_review", True):
            self.page("07  데이터 신뢰성 및 분석 기준")
            target_meaning = (
                "고장대상 설비 기준 집계라 검토 대상"
                if review_target(r.config_snapshot["settings"], r.options)
                else "참고 정보. 현재 설비 집계 기준에는 영향 없음"
            )
            rows = [
                [
                    "검토 대상(중복 제외)",
                    m["review_rows"],
                    "비가동코드 미기입·규칙 미일치·분류 검토·시간/날짜 이상 포함",
                ],
                [
                    K["code_missing"],
                    m.get("code_missing_rows", 0),
                    "원본 비가동코드 입력 확인 및 분류 필요",
                ],
                [K["rule_unmatched"], m.get("rule_unmatched_rows", 0), "분류 규칙 보완 대상"],
                [
                    "분류 검토필요",
                    classification_review_count(r),
                    "복수 후보·복수고장 등 규칙 판정 사유와 원기록 확인",
                ],
                [
                    K["multiple_fault_rows"],
                    m.get("multiple_fault_rows", 0),
                    "서로 다른 부품·고장 기록을 원문에서 함께 확인",
                ],
                [
                    K["alternative_type_rows"],
                    m.get("alternative_type_rows", 0),
                    "또는·혹은 등 대안 후보를 비교하여 확정. 실제 동시고장으로 합산하지 않음",
                ],
                [
                    "자동선택(복수 후보 해소)",
                    m.get("auto_resolved_rows", 0),
                    "부품·증상·교체 문맥 등 규칙 근거로 후보 해소, 판정 사유 기록",
                ],
                ["고장대상 미기재", m["missing_target_rows"], target_meaning],
                [
                    "시간 유효값 없음",
                    m["selected_rows"] - m["valid_time_rows"],
                    "건수에는 포함, 시간 합계·평균 분모에서는 제외",
                ],
                ["날짜 유효값 없음", m["date_missing_rows"], "월별 추이 제외"],
                [
                    "동일 기록 후보",
                    m["duplicate_candidate_rows"],
                    "중복 제외 선택 상태는 하단 표시",
                ],
            ]
            if m.get("legacy_classification_rows"):
                rows.append(
                    [
                        "이전 분석결과",
                        m["legacy_classification_rows"],
                        "현재 규칙으로 재분석하기 전의 분류이며 규칙분류 결과로 간주하지 않음",
                    ]
                )
            rows.sort(key=lambda item: item[1], reverse=True)
            rows = [[label, f"{count:,}건", meaning] for label, count, meaning in rows]
            self.story.append(
                layout.table(["항목", "건수", "의미"], rows, [129, 61, self.width - 190], (1,))
            )
            self.story.append(
                self.p(
                    "위 항목은 서로 중복될 수 있으므로 항목별 건수를 더해 검토 총건수로 사용하지 않습니다.",
                    "muted",
                )
            )
            self.classification_review()
            self.story.append(self.p("산출 기준·제한", "h2"))
            for note in r.notes:
                self.story.append(self.p(note, "muted"))
            dedup = "적용" if r.options.deduplicate else "미적용"
            self.story.append(
                self.p(
                    f"중복 제외: {dedup} | 사용자 지정 기간: {r.options.date_from or '-'} ~ {r.options.date_to or '-'}",
                    "muted",
                )
            )
            self.story.append(
                self.p(
                    f"입력시간 단위 옵션: {r.options.duration_unit} | 생성시각: {self.created.isoformat(timespec='seconds')}",
                    "metadata",
                )
            )
            self.story.append(self.p("Source SHA-256: " + r.loaded.file_hash, "metadata"))
            self.story.append(self.p("Config SHA-256: " + r.config_hash, "metadata"))

    def classification_review(self):
        self.story.append(self.p("규칙 기반 분류 원칙", "h2"))
        for principle in classification_principles():
            self.story.append(self.p(principle, "muted"))
        review = self.result.tables.get("review", pd.DataFrame())
        if review.empty:
            return
        self.story.append(self.p("검토 기록의 규칙 근거 (최대 3건)", "h2"))
        rows = []
        for row in review.head(3).to_dict("records"):
            source = f"{row.get('equipment', '-')}\n원본 행 {row.get('source_row', '-')}\n{row.get('status', '')}"
            details = []
            for label, field, limit in (
                ("판정", "classification_reason", 220),
                ("근거", "evidence", 220),
                ("후보", "candidate_evidence", 300),
            ):
                value = evidence_excerpt(row.get(field), limit)
                if value:
                    details.append(label + ": " + value)
            if not details:
                details.append(
                    evidence_excerpt(row.get("review_reason"), 180) or "원문과 분류 규칙 확인"
                )
            rows.append([source, "\n".join(details)])
        self.story.append(
            self.layout.table(
                ["검토 기록", "판정 사유·규칙 근거·유형 후보"],
                rows,
                [105, self.width - 105],
            )
        )
        self.story.append(
            self.p(
                "전체 검토 기록과 생략 없는 규칙 근거는 Excel의 검토필요·고장상세 시트에서 확인합니다.",
                "small",
            )
        )

    def build(self, path: Path, progress: Progress = noop_progress):
        try:
            self.overview()
            self.comparisons()
            self.components()
            self.fault_details()
            progress(20, "PDF 종합 분석 작성")
            if self.settings.get("include_monthly", True):
                self.monthly()
            equipment = self.result.tables["equipment"]["equipment"].tolist()
            if self.settings.get("include_equipment_details", True):
                for index, name in enumerate(equipment, 1):
                    self.equipment(name, index, len(equipment))
                    progress(20 + int(50 * index / max(1, len(equipment))), "PDF 설비별 분석 작성")
            self.actions()
            progress(80, "PDF 페이지 생성")
            doc = SimpleDocTemplate(
                str(path),
                pagesize=A4,
                rightMargin=44,
                leftMargin=44,
                topMargin=48,
                bottomMargin=46,
                title=self.title,
                author=str(self.settings.get("prepared_by", "")),
                subject="입력 엑셀 기록 기반 최종 분석",
                pageCompression=1,
            )
            doc.build(self.story, onFirstPage=self.header_footer, onLaterPages=self.header_footer)
        finally:
            for buffer in self.buffers:
                buffer.close()


def export_pdf(
    result: AnalysisResult, path: str | Path, progress: Progress = noop_progress
) -> Path:
    target = Path(path).expanduser().resolve().with_suffix(".pdf")
    if target == result.loaded.path.resolve():
        raise UserError("원본 파일은 덮어쓸 수 없습니다.")
    try:
        with atomic_output(target, prefix="efa_pdf_") as temp:
            FinalReport(result).build(temp, progress)
    except PermissionError as exc:
        raise UserError(
            "PDF가 열려 있거나 저장 권한이 없습니다. 다른 이름/폴더로 저장하세요."
        ) from exc
    progress(100, "PDF 생성 완료")
    return target
