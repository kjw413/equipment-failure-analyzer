"""Hierarchical department / line / module comparisons over retained fault facts."""

from copy import copy

import pandas as pd
from openpyxl.styles import Border, PatternFill, Side
from openpyxl.utils import get_column_letter as letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from core.equipment_names import resolve_group
from core.issue_analysis import ALL
from report.issue_workbook import escaped_cell, exact, ref, report_issue_facts

SHEET = "04.고장비교"
FIRST = 26
# Captions occupy one column like the other report sheets; only the value spans columns.
# Line names are long, so only the line value spans three columns; the others span two.
CONTROLS = {
    "organization": "B7",
    "asset": "E7",
    "baseline_module": "I7",
    "compare_organization": "B9",
    "compare_asset": "E9",
    "compare_module": "I9",
}
FILTER_AREAS = {
    "organization": ("A7", "B7:C7", ""),
    "asset": ("D7", "E7:G7", ""),
    "baseline_module": ("H7", "I7:J7", "asset"),
    "compare_organization": ("A9", "B9:C9", ""),
    "compare_asset": ("D9", "E9:G9", "line_level"),
    "compare_module": ("H9", "I9:J9", "module_level"),
}
ROW_HEIGHT = 21


def _absolute(key):
    address = CONTROLS[key]
    return f"${address[0]}${address[1:]}"


def organization_label(factory, team):
    return f"[{factory}] {team}"


def _filter_box(ws, area):
    left, top, right, bottom = range_boundaries(area)
    edge = Side(style="thin", color="000000")
    base = ws.cell(top, left)
    font, fill, number_format = copy(base.font), copy(base.fill), base.number_format
    for row in ws.iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right):
        for cell in row:
            cell.font, cell.fill, cell.number_format = copy(font), copy(fill), number_format
            cell.border = Border(
                left=edge if cell.column == left else Side(),
                right=edge if cell.column == right else Side(),
                top=edge if cell.row == top else Side(),
                bottom=edge if cell.row == bottom else Side(),
            )


def _install_filter_view(builder, ws):
    reference = builder.wb.create_sheet("_fault_filter_styles")
    reference.sheet_state = "hidden"
    active_caption, active_edit = ws["A7"], ws["B7"]
    for caption, edit, _ in FILTER_AREAS.values():
        for area, style in ((caption, active_caption), (edit, active_edit)):
            top_left = ws[area.split(":")[0]]
            top_left.font, top_left.fill = copy(style.font), copy(style.fill)
        _filter_box(ws, caption)
        _filter_box(ws, edit)
    for row in ws.iter_rows(min_row=7, max_row=9, max_col=12):
        for cell in row:
            reference[cell.coordinate]._style = copy(cell._style)
    if not getattr(builder, "macro_navigation", False):
        return
    # The six fields stay in place. Dependent fields are enabled as the baseline deepens.
    for key in ("baseline_module", "compare_asset", "compare_module"):
        for area in FILTER_AREAS[key][:2]:
            left, top, right, bottom = range_boundaries(area)
            for row in ws.iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right):
                for cell in row:
                    font = copy(cell.font)
                    font.color = "808080"
                    cell.font = font
                    cell.fill = PatternFill("solid", fgColor="F2F2F2")
        ws.data_validations.dataValidation = [
            v for v in ws.data_validations.dataValidation if str(v.sqref) != CONTROLS[key]
        ]


def comparison_facts(result):
    facts = report_issue_facts(result.selected)
    source = result.selected.set_index("record_id")
    grouping = result.config_snapshot.get("equipment_names", {}).get("grouping")
    families = source.get("equipment_group", pd.Series(dtype=object)).to_dict()
    facts["family"] = [
        str(families[key]).strip()
        if pd.notna(families.get(key)) and str(families[key]).strip()
        else resolve_group(asset, grouping)
        for key, asset in zip(facts.record_id, facts.asset, strict=True)
    ]
    return facts


def line_catalog(facts):
    """Names shared by organizations must still select one physical line."""
    catalog = (
        facts[["factory", "team", "asset"]]
        .drop_duplicates()
        .sort_values(["factory", "team", "asset"])
        .copy()
    )
    repeated = catalog.asset.duplicated(keep=False)
    labels, used = [], set()
    for index, item in enumerate(catalog.itertuples(index=False), 1):
        label = (
            organization_label(item.factory, item.team) + " / " if repeated.iloc[index - 1] else ""
        ) + item.asset
        if label in used:
            label += f" (라인 {index})"
        used.add(label)
        labels.append(label)
    catalog["choice"] = labels
    return catalog


def install_fault_comparison(b):
    book, ws = b.wb, b.wb[SHEET]
    facts = comparison_facts(b.r)
    catalog = line_catalog(facts)
    choices = {tuple(row[:3]): row[3] for row in catalog.itertuples(index=False, name=None)}
    facts["line_choice"] = [
        choices[key] for key in zip(facts.factory, facts.team, facts.asset, strict=True)
    ]
    body_styles = {cell.column_letter: copy(cell._style) for cell in ws[FIRST]}
    ws.data_validations.dataValidation.clear()

    def new(name, header):
        sheet = book.create_sheet(name)
        sheet.sheet_state = "hidden"
        sheet.append(header)
        return sheet

    def put(sheet, address, formula, cached):
        return b.cache.set(sheet, address, formula, cached)

    def named(name, target):
        book.defined_names.add(DefinedName(name, attr_text=target))

    data = new("_fault_facts", list(facts.columns))
    for row in facts.itertuples(index=False, name=None):
        data.append([None if pd.isna(value) else value for value in row])
    end = max(2, len(facts) + 1)

    def field(key):
        return f"'_fault_facts'!${letter(facts.columns.get_loc(key) + 1)}$2:${letter(facts.columns.get_loc(key) + 1)}${end}"

    orgs = sorted(set(zip(facts.factory, facts.team)))
    org = new("_fault_orgs", ["조직", "공장", "팀"])
    for factory, team in orgs:
        org.append([organization_label(factory, team), factory, team])
    first_org = organization_label(*orgs[0]) if orgs else ALL
    first_factory, first_team = orgs[0] if orgs else ("", "")
    families = (
        facts.groupby(["factory", "team", "asset"], sort=False)
        .family.agg(lambda items: ", ".join(sorted(set(items))))
        .to_dict()
    )
    units = new("_fault_units", ["라인 선택", "공장", "팀", "설비군", "라인"])
    for factory, team, asset, choice in catalog.itertuples(index=False, name=None):
        units.append([choice, factory, team, families[(factory, team, asset)], asset])
    defaults = {key: ALL for key in CONTROLS}
    defaults["organization"] = first_org
    for key, address in CONTROLS.items():
        ws[address] = defaults[key]

    owner = ref(SHEET)
    state = new("_fault_state", ["설정", "값"])
    org_end = max(2, org.max_row)
    for r, address, col, default in [
        (2, CONTROLS["organization"], "B", first_factory),
        (7, CONTROLS["organization"], "C", first_team),
        (8, CONTROLS["compare_organization"], "B", ""),
        (9, CONTROLS["compare_organization"], "C", ""),
    ]:
        match = f"MATCH({escaped_cell(owner + '!$' + address[0] + '$' + address[1:])},'_fault_orgs'!$A$2:$A${org_end},0)"
        put(
            state,
            f"B{r}",
            f"=IFERROR(INDEX('_fault_orgs'!${col}$2:${col}${org_end},{match}),\"\")",
            default,
        )
    put(
        state,
        "B3",
        f'=IF({owner}!{_absolute("asset")}="{ALL}","부서",IF({owner}!{_absolute("baseline_module")}="{ALL}","라인","상세설비"))',
        "부서",
    )

    rows = new(
        "_fault_rows",
        [
            "단위",
            "공장",
            "팀",
            "라인",
            "설비군",
            "건수",
            "시간 유효",
            "정지(분)",
            "평균(분)",
            "검토",
            "라벨",
            "표시",
            "순서",
            "상세설비",
            "역할",
        ],
    )
    groups = [
        dict(
            mode="부서",
            factory=f,
            team=t,
            asset="전체 라인",
            family="전체 설비군",
            module=ALL,
            choice=ALL,
        )
        for f, t in orgs
    ]
    for factory, team, asset, choice in catalog.itertuples(index=False, name=None):
        groups.append(
            dict(
                mode="라인",
                factory=factory,
                team=team,
                asset=asset,
                family=families[(factory, team, asset)],
                module=ALL,
                choice=choice,
            )
        )
    for factory, team, asset, module in (
        facts[["factory", "team", "asset", "module"]]
        .drop_duplicates()
        .sort_values(["factory", "team", "asset", "module"])
        .itertuples(index=False, name=None)
    ):
        groups.append(
            dict(
                mode="상세설비",
                factory=factory,
                team=team,
                asset=asset,
                family=families[(factory, team, asset)],
                module=module,
                choice=choices[(factory, team, asset)],
            )
        )
    cached = []
    for index, item in enumerate(
        (dict(item, role=role) for item in groups for role in ("기준", "비교")), 2
    ):
        record = facts
        keys = (
            ["factory", "team"]
            + (["asset"] if item["mode"] != "부서" else [])
            + (["module"] if item["mode"] == "상세설비" else [])
        )
        pairs = []
        for key in keys:
            pairs.extend((field(key), exact(item[key])))
            record = record.loc[record[key].eq(item[key])]
        args = ",".join(pairs)
        valid = int(record.minutes.count())
        total = record.minutes.sum(min_count=1)
        values = dict(
            count=len(record),
            valid=valid,
            minutes=float(total) if pd.notna(total) else "",
            mean=float(total) / valid if valid else "",
            review=int(record.review_count.sum()),
        )
        label = (
            organization_label(item["factory"], item["team"])
            if item["mode"] == "부서"
            else item["choice"]
        )
        if item["mode"] == "상세설비":
            label += " / " + item["module"]
        for col, key in [
            ("A", "mode"),
            ("B", "factory"),
            ("C", "team"),
            ("D", "asset"),
            ("E", "family"),
            ("N", "module"),
            ("O", "role"),
        ]:
            rows[f"{col}{index}"] = item[key]
            rows[f"{col}{index}"].data_type = "s"
        rows[f"K{index}"] = label
        rows[f"K{index}"].data_type = "s"
        for col, formula, key in [
            ("F", f"=COUNTIFS({args})", "count"),
            ("G", f'=COUNTIFS({args},{field("minutes")},">=0",{field("minutes")},"<>")', "valid"),
            (
                "H",
                f'=IF(F{index}=0,0,IF(G{index}=0,"",SUMIFS({field("minutes")},{args})))',
                "minutes",
            ),
            ("I", f'=IF(G{index}=0,"",H{index}/G{index})', "mean"),
            ("J", f"=SUMIFS({field('review_count')},{args})", "review"),
        ]:
            put(rows, f"{col}{index}", formula, values[key])
        base_scope = [f"B{index}='_fault_state'!$B$2", f"C{index}='_fault_state'!$B$7"]
        compare_scope = [
            f"OR({owner}!{_absolute('compare_organization')}=\"{ALL}\",AND(B{index}='_fault_state'!$B$8,C{index}='_fault_state'!$B$9))"
        ]
        if item["mode"] != "부서":
            base_scope.append(
                f'{exact(item["choice"])}="="&{escaped_cell(owner + "!" + _absolute("asset"))}'
            )
            compare_scope.append(
                f'OR({owner}!{_absolute("compare_asset")}="{ALL}",{exact(item["choice"])}="="&{escaped_cell(owner + "!" + _absolute("compare_asset"))})'
            )
        if item["mode"] == "상세설비":
            base_scope.append(f"N{index}={owner}!{_absolute('baseline_module')}")
            compare_scope.append(
                f'OR({owner}!{_absolute("compare_module")}="{ALL}",'
                f"N{index}={owner}!{_absolute('compare_module')})"
            )
        baseline = "AND(" + ",".join(base_scope) + ")"
        chosen = (
            baseline
            if item["role"] == "기준"
            else "AND(" + ",".join(compare_scope) + f",NOT({baseline}))"
        )
        eligible = f"AND(A{index}='_fault_state'!$B$3,{chosen})"
        initial = item["mode"] == "부서" and ((label == first_org) == (item["role"] == "기준"))
        put(rows, f"L{index}", f"=IF({eligible},1,0)", int(initial))
        put(
            rows,
            f"M{index}",
            f'=IF(L{index}=1,COUNTIF($L$2:L{index},1),"")',
            sum(x["initial"] for x in cached) + 1 if initial else "",
        )
        cached.append(dict(item, label=label, initial=initial, **values))
    last = max(2, rows.max_row)
    capacity = max(
        1, *(sum(x["mode"] == mode for x in groups) for mode in ("부서", "라인", "상세설비"))
    )
    initial_rows = [item for item in cached if item["initial"]]
    put(state, "B4", f"=SUM('_fault_rows'!$L$2:$L${last})", len(initial_rows))
    baseline_exists = (
        f"COUNTIFS('_fault_rows'!$O$2:$O${last},\"기준\",'_fault_rows'!$L$2:$L${last},1)"
    )
    first = next((item for item in initial_rows if item["role"] == "기준"), None)
    for row, col, key in [(5, "F", "count"), (6, "H", "minutes")]:
        expression = f"SUMIFS('_fault_rows'!${col}$2:${col}${last},'_fault_rows'!$O$2:$O${last},\"기준\",'_fault_rows'!$L$2:$L${last},1)"
        if row == 6:
            valid = f"SUMIFS('_fault_rows'!$G$2:$G${last},'_fault_rows'!$O$2:$O${last},\"기준\",'_fault_rows'!$L$2:$L${last},1)"
            expression = f'IF({valid}=0,"",{expression})'
        put(
            state,
            f"B{row}",
            f'=IF({baseline_exists}=0,"",{expression})',
            first[key] if first else "",
        )
    headers = [
        "공장",
        "팀",
        "라인",
        "설비군",
        "건수",
        "정지(분)",
        "평균(분)",
        "기준 대비 건수",
        "기준 대비 정지(분)",
        "분류 검토(건)",
        "시간 유효(건)",
        "상세설비",
    ]
    for col, text in enumerate(headers, 1):
        ws.cell(FIRST - 1, col, text)
    for offset in range(capacity):
        row = FIRST + offset
        item = initial_rows[offset] if offset < len(initial_rows) else None
        match = f"MATCH({offset + 1},'_fault_rows'!$M$2:$M${last},0)"
        for target, source, key in [
            ("A", "B", "factory"),
            ("B", "C", "team"),
            ("C", "D", "asset"),
            ("D", "E", "family"),
            ("E", "F", "count"),
            ("F", "H", "minutes"),
            ("G", "I", "mean"),
            ("J", "J", "review"),
            ("K", "G", "valid"),
            ("M", "K", "label"),
            ("L", "N", "module"),
        ]:
            put(
                ws,
                f"{target}{row}",
                f"=IFERROR(INDEX('_fault_rows'!${source}$2:${source}${last},{match}),\"\")",
                item[key] if item else "",
            )
            ws[f"{target}{row}"]._style = copy(body_styles.get(target))
            ws[f"{target}{row}"].number_format = "General" if target in "ABCDLM" else "#,##0"
        for target, metric, baseline_row, key in [("H", "E", 5, "count"), ("I", "F", 6, "minutes")]:
            base = first[key] if first else ""
            value = (
                item[key] - base
                if item and isinstance(item[key], (int, float)) and isinstance(base, (int, float))
                else ""
            )
            put(
                ws,
                f"{target}{row}",
                f'=IF(OR(M{row}="",{metric}{row}="",\'_fault_state\'!$B${baseline_row}=""),"",{metric}{row}-\'_fault_state\'!$B${baseline_row})',
                value,
            )
            ws[f"{target}{row}"]._style = copy(body_styles[target])
            ws[f"{target}{row}"].number_format = '[Red]"▲ "#,##0;[Blue]"▼ "#,##0;0'
        ws.row_dimensions[row].height = ROW_HEIGHT
        ws.row_dimensions[row].hidden = bool(
            getattr(b, "macro_navigation", False)
        ) and offset >= len(initial_rows)
    bottom = FIRST + capacity - 1
    ws.auto_filter.ref = f"A{FIRST - 1}:L{bottom}"
    ws.print_title_rows = f"{FIRST - 1}:{FIRST - 1}"
    ws.print_area = f"A1:L{FIRST + max(1, len(initial_rows)) - 1}"
    ws.page_setup.fitToHeight = 1
    named("_Fault_TableRows", f"{owner}!$A${FIRST}:$L${bottom}")
    named("_Fault_Labels", f"{owner}!$M${FIRST}:$M${bottom}")
    _selectors(b, ws, facts, orgs, defaults, field, first_factory, first_team)
    _install_filter_view(b, ws)
    _charts(b, ws, initial_rows, capacity)
    for sheet in (data, org, units):
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"


def _selectors(b, ws, facts, orgs, defaults, field, first_factory, first_team):
    book, owner = b.wb, ref(SHEET)
    source = book.create_sheet("_fault_list_source")
    flags = book.create_sheet("_fault_list_flags")
    lists = book.create_sheet("_fault_lists")
    metadata = book.create_sheet("_fault_controls")
    for sheet in (source, flags, lists, metadata):
        sheet.sheet_state = "hidden"
    metadata.append(["field", "cell", "committed", "caption_area", "edit_area", "parent"])
    for col, (key, address) in enumerate(CONTROLS.items(), 1):
        compared = key.startswith("compare_")
        if key in ("organization", "compare_organization"):
            values = ([ALL] if compared else []) + [organization_label(f, t) for f, t in orgs]
        else:
            values = [
                ALL,
                *sorted(
                    set(facts.line_choice if key in ("asset", "compare_asset") else facts.module)
                ),
            ]
        values = values or [ALL]
        column, cached = letter(col), []
        for row, value in enumerate(values, 1):
            source.cell(row, col, value).data_type = "s"
            formula, eligible = "=1", True
            if value != ALL and key not in ("organization", "compare_organization"):
                conditions = []
                for fact, base_row, compare_row in [("factory", 2, 8), ("team", 7, 9)]:
                    state_cell = f"'_fault_state'!$B${compare_row if compared else base_row}"
                    token = '"="&' + escaped_cell(state_cell)
                    if compared:
                        token = (
                            f'IF({owner}!{_absolute("compare_organization")}="{ALL}","*",{token})'
                        )
                    conditions.extend((field(fact), token))
                module = key in ("baseline_module", "compare_module")
                conditions.extend((field("module" if module else "line_choice"), exact(value)))
                if module:
                    parent = owner + "!" + _absolute("compare_asset" if compared else "asset")
                    conditions.extend((field("line_choice"), '"="&' + escaped_cell(parent)))
                    active = f'{parent}<>"{ALL}"'
                    if compared:
                        active += ",'_fault_state'!$B$3=\"상세설비\""
                    formula = f"=IF(AND({active},COUNTIFS({','.join(conditions)})>0),1,0)"
                    eligible = False
                else:
                    active = "'_fault_state'!$B$3<>\"부서\"," if compared else ""
                    formula = f"=IF(AND({active}COUNTIFS({','.join(conditions)})>0),1,0)"
                    eligible = not compared and value in set(
                        facts.loc[
                            facts.factory.eq(first_factory) & facts.team.eq(first_team),
                            "line_choice",
                        ]
                    )
            if eligible:
                cached.append(value)
            b.cache.set(flags, f"{column}{row}", formula, int(eligible))
        n = len(values)
        base = f"'_fault_list_source'!${column}$1:${column}${n}"
        for row in range(1, n + 1):
            index = f"_xlfn.AGGREGATE(15,6,(ROW({base})-ROW('_fault_list_source'!${column}$1)+1)/('_fault_list_flags'!${column}$1:${column}${n}>0),{row})"
            b.cache.set(
                lists,
                f"{column}{row}",
                f'=IFERROR(INDEX({base},{index}),"")',
                cached[row - 1] if row <= len(cached) else "",
            )
        area = f"'_fault_lists'!${column}$1:${column}${n}"
        name = "_Fault_List_" + key
        book.defined_names.add(
            DefinedName(
                name,
                attr_text=f"'_fault_lists'!${column}$1:INDEX({area},MAX(1,COUNTIF({area},\"?*\")))",
            )
        )
        validation = DataValidation(type="list", formula1="=" + name, allow_blank=False)
        validation.showErrorMessage = True
        validation.error = "목록에서 선택하세요."
        ws.add_data_validation(validation)
        validation.add(ws[address])
        metadata.append([key, address, defaults[key], *FILTER_AREAS[key]])


def _charts(b, ws, cached, capacity):
    book = b.wb
    rank = book.create_sheet("_fault_chart_rank")
    rank.sheet_state = "hidden"
    rank.append(
        [
            "라벨",
            "건수",
            "정지(분)",
            "표시",
            "건수순위",
            "시간순위",
            "건수라벨",
            "건수",
            "시간라벨",
            "시간",
        ]
    )
    last = capacity + 1
    count_order = sorted(cached, key=lambda x: -x["count"])
    time_order = sorted(
        (x for x in cached if isinstance(x["minutes"], (int, float))), key=lambda x: -x["minutes"]
    )
    for i in range(capacity):
        r = i + 2
        sr = FIRST + i
        item = cached[i] if i < len(cached) else None
        for col, original, key in [("A", "M", "label"), ("B", "E", "count"), ("C", "F", "minutes")]:
            b.cache.set(
                rank, f"{col}{r}", f"={ref(SHEET)}!{original}{sr}", item[key] if item else ""
            )
        b.cache.set(
            rank, f"D{r}", f'=IF(A{r}="",0,SUBTOTAL(103,{ref(SHEET)}!$A${sr}))', int(bool(item))
        )
        for col, metric in [("E", "B"), ("F", "C")]:
            expression = f'COUNTIFS($D$2:$D${last},1,${metric}$2:${metric}${last},">"&{metric}{r})+COUNTIFS($D$2:D{r},1,${metric}$2:{metric}{r},{metric}{r})'
            value = next(
                (
                    n
                    for n, x in enumerate(count_order if col == "E" else time_order, 1)
                    if item and x["label"] == item["label"]
                ),
                "",
            )
            b.cache.set(
                rank,
                f"{col}{r}",
                f'=IF(OR(D{r}=0,NOT(ISNUMBER({metric}{r}))),"",{expression})',
                value,
            )
    top = min(10, capacity)
    for i in range(top):
        r = i + 2
        for rank_col, label_col, value_col, metric, order in [
            ("E", "G", "H", "B", count_order),
            ("F", "I", "J", "C", time_order),
        ]:
            match = f"MATCH({i + 1},${rank_col}$2:${rank_col}${last},0)"
            item = order[i] if i < len(order) else None
            for target, src, value in [
                (label_col, "A", item["label"] if item else ""),
                (value_col, metric, item["count" if metric == "B" else "minutes"] if item else ""),
            ]:
                # A stable category prevents Excel dropping its named-range binding
                # while all result rows are temporarily hidden during a refresh.
                # NA() omits unavailable measurements instead of drawing a zero bar.
                empty_label = "해당 조건의 이력 없음" if metric == "B" else "시간 미기재"
                fallback = (
                    (f'"{empty_label}"' if target == label_col else "NA()") if i == 0 else '""'
                )
                if not order and i == 0:
                    value = empty_label if target == label_col else None
                b.cache.set(
                    rank,
                    f"{target}{r}",
                    f'=IF(COUNT(${rank_col}$2:${rank_col}${last})=0,{fallback},IFERROR(INDEX(${src}$2:${src}${last},{match}),""))',
                    value,
                )
    ranges = {}
    for key, metric, col, values in [("C", "Count", "G", "H"), ("D", "Time", "I", "J")]:
        for suffix, column in [("Labels", col), ("Values", values)]:
            name = "_Fault_" + metric + suffix
            rank_column = "E" if key == "C" else "F"
            expression = f"'_fault_chart_rank'!${column}$2:INDEX('_fault_chart_rank'!${column}$2:${column}${top + 1},MAX(1,MIN(10,COUNT('_fault_chart_rank'!${rank_column}$2:${rank_column}${last}))))"
            book.defined_names.add(DefinedName(name, attr_text=expression))
            ws.defined_names.add(DefinedName(name, attr_text=expression))
        ranges[key] = {
            "category": f"{ref(SHEET)}!_Fault_{metric}Labels",
            "value": f"{ref(SHEET)}!_Fault_{metric}Values",
            "cache_category": f"'_fault_chart_rank'!${col}$2:${col}${min(top, max(1, len(cached))) + 1}",
            "cache_value": f"'_fault_chart_rank'!${values}$2:${values}${min(top, max(1, len(cached))) + 1}",
        }
    b._locked_template["sheets"][SHEET]["comparison_chart_ranges"] = ranges
    state = book["_fault_state"]
    for row, unit in [(20, "발생 건수 [건]"), (21, "정지시간 [분]")]:
        b.cache.set(
            state,
            f"B{row}",
            f'=B3&"별 {unit}"',
            "부서별 " + unit,
        )
