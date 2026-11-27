"""Scoped Excel selectors and line → detailed-equipment ranking."""

from __future__ import annotations

from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

from core.issue_analysis import ALL, FACT_COLUMNS, issue_summary
from report.formatting import bounded_int

MAIN_SHEET = "02.팀별 주요이슈"
FIELDS = ("factory", "team", "asset", "module")


def build_ranks(issues, filters):
    from report.issue_workbook import exact

    b = issues.b
    state = b.wb.create_sheet("_drill_state")
    state.append(["조회 단계", "값"])
    asset = filters["asset"]
    b.cache.set(
        state,
        "B2",
        f'=IF(OR({asset}="{ALL}",{asset}=""),"asset","module")',
        "asset",
    )
    b.cache.set(state, "B3", '=IF(B2="asset","라인","상세설비")', "라인")
    state.sheet_state = "hidden"
    rank = b.wb.create_sheet("_issue_rank")
    rank.append(["항목", "건수", "시간유효", "정지시간", "검토", "건수순위", "시간순위", "단계"])
    tables = {
        field: issue_summary(issues.facts, [field]).sort_values(field)
        for field in ("asset", "module")
    }
    end = max(2, 1 + sum(len(t) for t in tables.values()))
    row = 2
    for field, table in tables.items():
        items = table.to_dict("records")
        orders = [
            sorted(items, key=lambda x: (-x["count"], x[field])),
            sorted(
                (x for x in items if x["valid_count"]),
                key=lambda x: (-x["total_minutes"], x[field]),
            ),
        ]
        ranks = [{item[field]: i for i, item in enumerate(order, 1)} for order in orders]
        for item in items:
            label = item[field]
            b.put(rank, row, 1, label, project=False)
            b.put(rank, row, 8, field, project=False)
            args = issues.args(filters, [(issues.fact_range(field), exact(label))])
            for column, formula, cached in (
                ("B", issues.count_formula(args), item["count"]),
                ("C", issues.valid_formula(args), item["valid_count"]),
                (
                    "D",
                    f'=IF(C{row}=0,"",SUMIFS({issues.fact_range("minutes")},{args}))',
                    item["total_minutes"] if item["valid_count"] else "",
                ),
                ("E", f"=SUMIFS({issues.fact_range('review_count')},{args})", item["review_count"]),
                (
                    "F",
                    f'=IF(OR(B{row}=0,H{row}<>\'_drill_state\'!$B$2),"",COUNTIFS($H$2:$H${end},H{row},$B$2:$B${end},">"&B{row})+COUNTIFS($H$2:H{row},H{row},$B$2:B{row},B{row}))',
                    ranks[0][label] if field == "asset" else "",
                ),
                (
                    "G",
                    f'=IF(OR(C{row}=0,H{row}<>\'_drill_state\'!$B$2),"",COUNTIFS($H$2:$H${end},H{row},$C$2:$C${end},">0",$D$2:$D${end},">"&D{row})+COUNTIFS($H$2:H{row},H{row},$C$2:C{row},">0",$D$2:D{row},D{row}))',
                    ranks[1].get(label, "") if field == "asset" else "",
                ),
            ):
                issues.formula(
                    rank,
                    f"{column}{row}",
                    formula,
                    cached,
                    "#,##0" if column in "BCEF" else "#,##0.0",
                )
            row += 1
    rank.sheet_state = "hidden"
    return end, tables["asset"].rename(columns={"asset": "case"}).set_index("case")


def install_controls(builder):
    """Excel 2019-compatible formula lists work for both dropdowns and search UI."""
    from report.issue_workbook import criterion, exact, ref

    book = builder.wb
    if MAIN_SHEET not in book:
        return
    ws = book[MAIN_SHEET]
    for address in ("B27", "H27"):
        builder.cache.set(ws, address, "='_drill_state'!B3", "라인")
    top_n = bounded_int(
        builder.r.config_snapshot.get("final_report", {}).get("summary_top_n"), 5, 10
    )
    for name, column in (("_Drill_CountLabels", "B"), ("_Drill_TimeLabels", "H")):
        book.defined_names.add(
            DefinedName(name, attr_text=f"{ref(ws.title)}!${column}$28:${column}${27 + top_n}")
        )

    controls = book.create_sheet("_report_controls")
    controls.append(["sheet", "field", "cell", "order", "list_column", "committed"])
    controls.sheet_state = "hidden"
    flags = book.create_sheet("_selector_flags")
    lists = book.create_sheet("_selector_lists")
    flags.sheet_state = lists.sheet_state = "hidden"
    facts = book["_issue_facts"]
    last = max(2, facts.max_row)
    column = 0
    for sheet in list(book):
        if sheet.title == "04.고장비교":
            continue
        selected = {}
        for validation in sheet.data_validations.dataValidation:
            field = validation.formula1.removeprefix("=_Issue_")
            if field not in FIELDS:
                continue
            for area in validation.sqref.ranges:
                selected[field] = sheet.cell(area.min_row, area.min_col).coordinate
        for position, field in enumerate(FIELDS):
            if field not in selected:
                continue
            column += 1
            letter = get_column_letter(column)
            address = selected[field]
            committed = sheet[address].value
            controls.append([sheet.title, field, address, position + 1, column, committed or ALL])
            key_index = FACT_COLUMNS.index(field) + 1
            values = [
                ALL,
                *sorted(
                    {str(facts.cell(row, key_index).value) for row in range(2, facts.max_row + 1)}
                ),
            ]
            # _issue_lists keeps the canonical FIELDS column order on every sheet.
            source_col = get_column_letter(position + 1)
            count = len(values)
            source_range = f"'_issue_lists'!${source_col}$1:${source_col}${count}"
            conditions = []
            for parent in FIELDS[:position]:
                if parent not in selected:
                    continue
                col = get_column_letter(FACT_COLUMNS.index(parent) + 1)
                cell = sheet[selected[parent]]
                cell_ref = f"{ref(sheet.title)}!${cell.column_letter}${cell.row}"
                conditions.extend((f"'_issue_facts'!${col}$2:${col}${last}", criterion(cell_ref)))
            fact_col = get_column_letter(key_index)
            for row, value in enumerate(values, 1):
                args = [
                    *conditions,
                    f"'_issue_facts'!${fact_col}$2:${fact_col}${last}",
                    exact(value),
                ]
                formula = "=1" if row == 1 else f"=IF(COUNTIFS({','.join(args)})>0,1,0)"
                builder.cache.set(flags, f"{letter}{row}", formula, 1)
                index = f"_xlfn.AGGREGATE(15,6,(ROW({source_range})-ROW('_issue_lists'!${source_col}$1)+1)/('_selector_flags'!${letter}$1:${letter}${count}>0),{row})"
                builder.cache.set(
                    lists,
                    f"{letter}{row}",
                    f'=IFERROR(INDEX({source_range},{index}),"")',
                    value,
                )
            scope = f"'_selector_lists'!${letter}$1:${letter}${count}"
            # COUNTIF ?* excludes formula-empty strings. ALL is always the first item.
            expression = (
                f"'_selector_lists'!${letter}$1:INDEX({scope},MAX(1,COUNTIF({scope},\"?*\")))"
            )
            sheet.defined_names.add(DefinedName("_Issue_" + field, attr_text=expression))
