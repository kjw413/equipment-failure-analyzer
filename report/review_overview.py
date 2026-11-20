"""One appendix for classification coverage, review reasons and the work queue."""

from collections import Counter
from copy import copy

from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from core.preprocessing import review_target
from core.review_colors import REVIEW_TYPES, normalized_review_colors, review_types
from core.sorting import descending

SOURCE_SHEET = "별첨. 원본 검토표시"
FIELDS = (
    "source_row",
    "date",
    "factory",
    "team",
    "report_equipment",
    "minutes",
    "status",
    "review_reason",
    "history_link",
)


def build_review_overview(b):
    from report.excel_report import decision_row_height

    result = b.r
    review = descending(result.tables["review"], "minutes")
    ws = b.new_sheet("review", "검토필요 및 분류현황", span=len(FIELDS))
    ws.merge_cells(f"A5:{get_column_letter(len(FIELDS))}5")
    b.put(
        ws,
        5,
        1,
        "정지시간 내림차순. 상세 이력에서 표준화 내용과 분류 근거를 확인할 수 있습니다. 원본 행 번호를 클릭하면 색칠된 원본으로 이동합니다.",
        project=False,
    )
    b.header(ws, 6, ["분석 이력(건)", "검토필요 이력(건)", "정지시간(분)", "시간 기재(건)"])
    for col, value in enumerate(
        (
            len(result.selected),
            len(review),
            result.selected.minutes.sum(min_count=1),
            result.selected.minutes.count(),
        ),
        1,
    ):
        b.put(ws, 7, col, value, fmt="#,##0")
    b.header(ws, 10, ["분류 상태", "건수"])
    statuses = result.selected.status.fillna("상태 미기재").value_counts()
    for row, (status, count) in enumerate(statuses.items(), 11):
        b.put(ws, row, 1, status, project=False)
        b.formula(ws, row, 2, f'=COUNTIF({b.range("status")},"="&A{row})', int(count), "#,##0")
    for col, label in enumerate(("검토 사유", "건수(중복 포함)", "색상"), 4):
        cell = b.put(ws, 10, col, label, role="header", project=False)
        cell.alignment = copy(ws["A10"].alignment)
    settings = result.config_snapshot.get("settings", {})
    colors = normalized_review_colors(settings.get("review_colors"))
    reasons = Counter()
    for record in review.to_dict("records"):
        reasons.update(review_types(record, review_target(settings, result.options)) or ("other",))
    for row, (key, label, _) in enumerate(REVIEW_TYPES, 11):
        b.put(ws, row, 4, label, project=False)
        b.put(ws, row, 5, reasons[key], fmt="#,##0")
        b.put(ws, row, 6, " ", project=False).fill = PatternFill(
            "solid", fgColor=colors[key].lstrip("#")
        )
    ws.merge_cells("D16:I16")
    b.put(
        ws,
        16,
        4,
        "한 이력에 사유가 여러 개이면 사유별 건수는 중복 집계합니다. 원본 색상은 위쪽 사유부터 우선 적용합니다.",
        project=False,
    )
    header = max(20, 13 + len(statuses))
    headers = [b.display_header(field) for field in FIELDS]
    headers[4] = "라인"
    for field, label in {
        "review_reason": "검토 사유",
        "history_link": "상세 이력",
    }.items():
        headers[FIELDS.index(field)] = label
    b.header(ws, header, headers)
    for row, record in enumerate(review.to_dict("records"), header + 1):
        for col, field in enumerate(FIELDS, 1):
            if field == "source_row":
                source_row = int(record[field])
                b.formula(
                    ws,
                    row,
                    col,
                    f"=HYPERLINK(\"#'{SOURCE_SHEET}'!A{source_row}\",{source_row})",
                    source_row,
                    "0",
                )
            elif field == "history_link":
                b.formula(
                    ws,
                    row,
                    col,
                    f'=IFERROR(HYPERLINK("#\'별첨. 고장이력\'!B"&(MATCH(A{row},{b.range("source_row")},0)+6),"이력 보기"),"")',
                    "이력 보기",
                    "General",
                )
            else:
                b.put(
                    ws,
                    row,
                    col,
                    record.get(field),
                    project=False,
                    fmt="yyyy-mm-dd"
                    if field == "date"
                    else "#,##0"
                    if field == "minutes"
                    else None,
                )
        ws.row_dimensions[row].height = decision_row_height(
            record, {"review_reason": 41}, minimum=24
        )
    if review.empty:
        b.put(ws, header + 1, 1, "검토필요 이력 없음", project=False)
    for col, field in enumerate(FIELDS, 1):
        ws.column_dimensions[get_column_letter(col)].width = {
            "report_equipment": 25,
            "review_reason": 46,
            "history_link": 14,
        }.get(field, 16)
    ws.column_dimensions["A"].width = 14
    last_column = get_column_letter(len(FIELDS))
    ws.auto_filter.ref = f"A{header}:{last_column}{max(header, header + len(review))}"
    ws.print_area = f"A1:{last_column}{max(header + 1, header + len(review))}"
    ws.print_title_rows = f"{header}:{header}"
    return ws
