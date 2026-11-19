"""Independent, live rankings for the two organization comparison charts."""

from __future__ import annotations

from numbers import Real

SHEET = "04.고장비교"
HELPER = "_comparison_rank"


def build_comparison_ranks(builder):
    """Keep the comparison table stable while charts use their own metric order."""
    if SHEET not in builder.wb:
        return
    source = builder.wb[SHEET]
    rows = [
        row
        for row in range(1, source.max_row + 1)
        if source.cell(row, 3).data_type == "f" and source.cell(row, 10).value not in (None, "")
    ]
    if HELPER in builder.wb:
        builder.wb.remove(builder.wb[HELPER])
    helper = builder.wb.create_sheet(HELPER)
    helper.sheet_state = "hidden"
    helper.append(
        [
            "조직",
            "건수",
            "정지(분)",
            "시간 값 유효",
            "건수 순위",
            "시간 순위",
            "건수 조직",
            "건수",
            "시간 조직",
            "정지(분)",
        ]
    )
    last = max(2, len(rows) + 1)
    source_ref = "'" + source.title.replace("'", "''") + "'"
    cached = []
    for row in rows:
        cached.append(
            {
                "label": source.cell(row, 10).value,
                "count": builder.cache.values.get((SHEET, f"C{row}"), ""),
                "time": builder.cache.values.get((SHEET, f"D{row}"), ""),
            }
        )
    count_order = sorted(range(len(cached)), key=lambda i: (-cached[i]["count"], i))
    time_order = sorted(
        (i for i in range(len(cached)) if isinstance(cached[i]["time"], Real)),
        key=lambda i: (-cached[i]["time"], i),
    )
    count_ranks = {item: rank for rank, item in enumerate(count_order, 1)}
    time_ranks = {item: rank for rank, item in enumerate(time_order, 1)}
    for index, source_row in enumerate(rows):
        row, item = index + 2, cached[index]
        for column, original, value in (
            ("A", "J", item["label"]),
            ("B", "C", item["count"]),
            ("C", "D", item["time"]),
        ):
            builder.cache.set(
                helper, f"{column}{row}", f"={source_ref}!{original}{source_row}", value
            )
        builder.cache.set(helper, f"D{row}", f"=IF(ISNUMBER(C{row}),1,0)", int(index in time_ranks))
        builder.cache.set(
            helper,
            f"E{row}",
            f'=COUNTIF($B$2:$B${last},">"&B{row})+COUNTIF($B$2:B{row},B{row})',
            count_ranks[index],
        )
        builder.cache.set(
            helper,
            f"F{row}",
            f'=IF(D{row}=0,"",COUNTIFS($D$2:$D${last},1,$C$2:$C${last},">"&C{row})+COUNTIFS($D$2:D{row},1,$C$2:C{row},C{row}))',
            time_ranks.get(index, ""),
        )
    for index in range(max(1, len(rows))):
        row = index + 2
        for rank, order, label_col, value_col, value_source, key in (
            ("E", count_order, "G", "H", "B", "count"),
            ("F", time_order, "I", "J", "C", "time"),
        ):
            match = f"MATCH({index + 1},${rank}$2:${rank}${last},0)"
            item = cached[order[index]] if index < len(order) else None
            for target, original, value in (
                (label_col, "A", item["label"] if item else ""),
                (value_col, value_source, item[key] if item else ""),
            ):
                builder.cache.set(
                    helper,
                    f"{target}{row}",
                    f'=IFERROR(INDEX(${original}$2:${original}${last},{match}),"")',
                    value,
                )
    for row in helper.iter_rows(min_row=2):
        for cell in row:
            cell.number_format = "General" if cell.column in (1, 7, 9) else "#,##0"
    builder._locked_template["sheets"][SHEET]["comparison_chart_ranges"] = {
        "C": {"category": f"'{HELPER}'!$G$2:$G${last}", "value": f"'{HELPER}'!$H$2:$H${last}"},
        "D": {"category": f"'{HELPER}'!$I$2:$I${last}", "value": f"'{HELPER}'!$J$2:$J${last}"},
    }
